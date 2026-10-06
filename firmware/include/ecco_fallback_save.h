#pragma once

// FB-B2: Fallback Profile SAVE / REPLACE CORRUPT / INVALIDATE - PURE MODEL.
//
// FB-B2 turns the read-only REVIEW candidate (ecco_fallback_capture.h) into a durable known-good profile: a SAVE
// gate, the dispatch re-read, one synchronous final lambda that calls the FB-B0 writer, and the INVALIDATE gate+commit.
// Every DECISION those lambdas take is a PURE function of plain values and lives here; the lambdas only gather RAM
// flags into the POD structs below (lambda locals only - never the type of a firmware global), make ONE call per
// decision, publish the result and make the one writer call themselves. This header is deliberately STANDALONE and
// BEHAVIOUR-FREE, exactly like the capture header it builds on:
//   - it includes only standard headers, the FB-B0 model header and the FB-B1 capture header; no ESPHome header, no
//     storage, no inverter bus, no entity, no clock: time is always a parameter (`now_ms`);
//   - it NEVER calls the FB-B0 writer, never touches a RAM mirror, never reads or sets a flag: it only DECIDES
//     (gates), BUILDS the intended record pair (plan_save / plan_invalidate) and RENDERS text;
//   - it declares no durable record, key or tag, and no operator text lives anywhere else (the firmware lambdas may
//     not contain a text literal, so every refusal, outcome and log line is a builder below);
//   - everything is constexpr, text included (the capture header's TextBuf), so the golden vectors, golden strings and
//     golden-case tables at the bottom are static_asserts evaluated by registry/tests/test_fallback_save_host_compile.py
//     (host C++ compile, -Wall -Wextra -Werror) and re-derived from the Python mirror.
//
// Offline mirror: registry/fallback_save.py (same names, same behaviour).
//
// ENTRY POINTS (one line each; every one is documented at its definition)
//   action router          action_token  is_invalidate_action  action_refusal_text  unsupported_action_text
//   confirmation grammar   is_hex16  parse_hex16  parse_phrase  expected_phrase  phrase_equals  put_sanitised
//   timing / integrity     arm_expired  save_integrity_ok  overlay_class
//   SAVE gate              save_in_flight_gate  save_gate_decide  save_gate_with_result  save_gate_refusal_text  save_in_progress_text
//   SAVE final             final_phase_inputs  final_gate_decide  commit_bus_quiet  clock_trusted_for_save  plan_save
//   INVALIDATE             invalidate_in_flight_gate  invalidate_gate_decide  invalidate_bus_idle  plan_invalidate
//   outcome                txn_outcome_text  first_non_ok  total_us  txn_op_name  txn_log_text  replace_corrupt_log_text
//   SAVE / INVALIDATE texts every builder named *_text (refusals, read failures, comparisons, outcomes)
//
// WHO CALLS WHAT (each firmware lambda gathers plain values into the POD structs, makes these calls, publishes)
//   the execute api action                  is_invalidate_action routes INVALIDATE to its script, every other token to SAVE
//   fallback_profile_save (gate)            save_in_flight_gate (before the one-shot preamble), then save_gate_decide
//   dispatch (existing)                     PRECOMMIT_WAIT_MS bounds the pre-commit drain; the REVIEW read texts are unchanged
//   SAVE final                              save_integrity_ok, save_read_fail_text, first_diff / save_changed_* texts, capture_refusals /
//                                           save_l2_text, final_gate_decide (own-hold masked), clock_trusted_for_save,
//                                           plan_save, commit_bus_quiet, then the lambda's writer call, txn_outcome_text,
//                                           first_non_ok / total_us (B2 werr / us), overlay_class, txn_log_text
//   fallback_profile_invalidate             invalidate_in_flight_gate, invalidate_gate_decide, plan_invalidate, invalidate_bus_idle (LAST
//                                           statement before the writer call), then the same outcome builders
//   housekeeping tick                       arm_expired (arm TTL)
//
// DEFAULTS ARE FAIL-CLOSED in every input POD below (a deliberate deviation from the permissive idle defaults of the
// capture gate inputs): a forgotten assignment can only REFUSE. The lambdas must still assign EVERY field (the firmware
// suite pins this by parsing the field lists of these structs). Two exceptions that are inherited, not new: the
// embedded capture BusInputs of InvalidateGateInputs keeps ITS permissive idle values (every busy flag false), and the
// capture GateInputs passed to the SAVE gate keeps the capture header's DEFAULTS note; both must be assigned in full.
// Fail-closed defaults: action not recognised, arm off, no candidate (id 0, not saveable), unconfirmed true,
// read_anomaly 0xFF, hb_ok false, time_trusted false, boot_loaded false, class UNREADABLE, seen_hw_gen 0xFFFFFFFF (no
// generation can pass it), tx_buffer_empty false, tx_blocked true, load codes UNAVAILABLE, captured_epoch 0.
//
// Discipline (pinned by the offline suites): standard headers + the FB-B0 model header + the FB-B1 capture header only;
// every namespace-scope object is constexpr; no `static`, no `inline`; one namespace.

#include <array>
#include <cstddef>
#include <cstdint>
#include <type_traits>

#include "ecco_fallback_durable_model.h"
#include "ecco_fallback_capture.h"

namespace ecco_fbsave {

using ecco_fbcap::BusInputs;
using ecco_fbcap::CaptureWords;
using ecco_fbcap::GateInputs;
using ecco_fbcap::GateResult;
using ecco_fbcap::ProbeResults;
using ecco_fbcap::SlotClass;
using ecco_fbcap::TextBuf;
using ecco_fbcap::put;
using ecco_fbcap::put_char;
using ecco_fbcap::put_hex;
using ecco_fbcap::put_u;
using ecco_fbcap::str_is;
using ecco_fbcap::text_is;

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------
constexpr uint32_t ARM_TTL_MS = 120000u;        // the FB arm switch lives at most this long (applied by the 10 s tick)
constexpr uint32_t PRECOMMIT_WAIT_MS = 3000u;   // wait_until bus idle after the last read, before the SAVE final lambda
constexpr uint8_t PURPOSE_SAVE = 2;             // dispatch purpose: REVIEW is 1, nothing is 0
constexpr size_t ECHO_MAX = 24;                 // an unsupported action token is echoed at most this long
constexpr size_t ECHO_LOOK = 4;                 // ... and the echo examines this many bytes beyond that (the longest masked hazard word, "defer", minus one)
constexpr size_t ID_DIGITS = 16;                // a candidate id / profile binding is 16 upper-case hex digits
constexpr size_t PHRASE_SCAN_MAX = 64;          // a NUL-terminated confirmation is read at most this far (+1 byte)
constexpr size_t ACTION_SCAN_MAX = 16;          // a NUL-terminated action is read at most this far (+1 byte)

constexpr char SAVE_REFUSED_PREFIX[] = "SAVE REFUSED - ";
constexpr char INVALIDATE_REFUSED_PREFIX[] = "INVALIDATE REFUSED - ";

// ---------------------------------------------------------------------------
// Enums (explicit decimal numbers; 0 is always the fail-closed value)
// ---------------------------------------------------------------------------
enum ActionToken : uint8_t {
  ACT_UNSUPPORTED = 0,  // anything that is not one of the four tokens below (the retired tokens included)
  ACT_SAVE = 1,
  ACT_INVALIDATE = 2,
  ACT_RESTORE = 3,      // reserved: refused, not implemented
  ACT_ACKNOWLEDGE = 4,  // reserved: refused, not implemented
};

enum PhraseKind : uint8_t {
  PHRASE_INVALID = 0,
  PHRASE_SAVE = 1,
  PHRASE_SAVE_REPLACE_CORRUPT = 2,
  PHRASE_INVALIDATE = 3,
};

// SAVE gate decision. G0-G16 of the S1 8.5 table, first failure wins (the order of the enumerators is NOT the order of
// evaluation: see save_gate_with_result).
enum SaveGateCode : uint8_t {
  SG_UNSET = 0,  // no decision (fail-closed: never accepts)
  SG_ACCEPT = 1,
  SG_IN_FLIGHT = 2,     // G1
  SG_UNSUPPORTED = 3,   // G0
  SG_ARM_OFF = 4,       // G2
  SG_NO_CANDIDATE = 5,  // G3
  SG_EXPIRED = 6,       // G4
  SG_ID_FORMAT = 7,     // G5
  SG_ID_MISMATCH = 8,   // G6
  SG_PHRASE = 9,        // G7
  SG_NOT_LOADED = 10,   // G8
  SG_UNCONFIRMED = 11,  // G9
  SG_ANOMALY = 12,      // G9a
  SG_HB = 13,           // G10
  SG_TIME = 14,         // G11
  SG_ARMS = 15,         // G12
  SG_WRITES = 16,       // G13
  SG_BUS = 17,          // G14
  SG_FBS = 18,          // G15
  SG_FP = 19,           // G16
  SG_DUMP = 20,         // G16
  SG_R244 = 21,         // G16
  SG_MTOU = 22,         // G16
};

// INVALIDATE gate decision (S2 Part B 4.2 as amended by master 4.8): no arms, obligation or heartbeat requirement.
enum InvalidateGateCode : uint8_t {
  IG_UNSET = 0,
  IG_ACCEPT = 1,
  IG_IN_FLIGHT = 2,    // I1
  IG_UNSUPPORTED = 3,  // token
  IG_ARM_OFF = 4,      // I2
  IG_ID_FORMAT = 5,    // I3
  IG_PHRASE = 6,       // I4
  IG_NOT_LOADED = 7,   // I5
  IG_ANOMALY = 8,      // I6
  IG_UNCONFIRMED = 9,  // I7
  IG_CLASS = 10,       // I8
  IG_ID_MISMATCH = 11, // I9
  IG_GENERATION = 12,  // I10
  IG_BUS = 13,         // I11
  IG_FBS = 14,         // I12
};

// plan_save / plan_invalidate verdict.
enum PlanCode : uint8_t {
  PLAN_UNSET = 0,
  PLAN_OK = 1,
  PLAN_PRIOR_CHANGED = 2,    // the stored profile is not the one the candidate was reviewed against
  PLAN_UNCONFIRMED = 3,      // the RAM overlay is set
  PLAN_ANOMALY = 4,          // a read anomaly this boot
  PLAN_CLASS = 5,            // the effective class does not permit the operation
  PLAN_CONTEXT = 6,          // the dispatch context is inconsistent
  PLAN_CLOCK = 7,            // no trusted capture time
  PLAN_GENERATION = 8,       // the generation counter is exhausted / not ahead
  PLAN_INTERNAL = 9,         // the built record pair did not validate
  PLAN_BINDING_CHANGED = 10  // INVALIDATE: the stored profile is not the one named by the operator
};

// ---------------------------------------------------------------------------
// Bounded string primitives. A caller either passes a NUL-terminated string (at most limit + 1 bytes are read, an
// unterminated or over-long buffer cannot run away, a null pointer is empty) or an explicit byte length (embedded NULs
// then count as characters, so a string object with a NUL in it is never read as its prefix).
// ---------------------------------------------------------------------------
constexpr size_t bounded_len(const char *s, size_t limit) {
  if (s == nullptr)
    return 0;
  size_t i = 0;
  while (i <= limit) {
    if (s[i] == '\0')
      return i;
    i++;
  }
  return limit + 1;
}

// Exact comparison of the n bytes at s against a string literal.
template<size_t N> constexpr bool exact(const char *s, size_t n, const char (&lit)[N]) {
  if (s == nullptr || n != N - 1)
    return false;
  for (size_t i = 0; i + 1 < N; i++) {
    if (s[i] != lit[i])
      return false;
  }
  return true;
}

// The n bytes at s start with the string literal.
template<size_t N> constexpr bool starts_with(const char *s, size_t n, const char (&lit)[N]) {
  if (s == nullptr || n < N - 1)
    return false;
  for (size_t i = 0; i + 1 < N; i++) {
    if (s[i] != lit[i])
      return false;
  }
  return true;
}

// ---------------------------------------------------------------------------
// Action token (case-sensitive, byte-exact)
// ---------------------------------------------------------------------------
constexpr uint8_t action_token(const char *action, size_t n) {
  return exact(action, n, "SAVE")              ? ACT_SAVE
         : exact(action, n, "INVALIDATE")      ? ACT_INVALIDATE
         : exact(action, n, "RESTORE")         ? ACT_RESTORE
         : exact(action, n, "ACKNOWLEDGE")     ? ACT_ACKNOWLEDGE
                                               : ACT_UNSUPPORTED;
}
constexpr uint8_t action_token(const char *action) { return action_token(action, bounded_len(action, ACTION_SCAN_MAX)); }

// The router: INVALIDATE goes to its own script, EVERY other token goes to the SAVE gate (which refuses it).
constexpr bool is_invalidate_action(const char *action, size_t n) { return action_token(action, n) == ACT_INVALIDATE; }
constexpr bool is_invalidate_action(const char *action) { return action_token(action) == ACT_INVALIDATE; }

constexpr bool echo_char_ok(char c) {
  return (c >= 'A' && c <= 'Z') || (c >= 'a' && c <= 'z') || (c >= '0' && c <= '9') || c == '_';
}

// The ASCII lower-case fold of a SANITISED echo byte (only [A-Za-z0-9_?] reach it).
constexpr char echo_fold(char c) { return (c >= 'A' && c <= 'Z') ? (char) (c + ('a' - 'A')) : c; }

// Byte i of the sanitised token: [A-Za-z0-9_] kept, every other byte (an embedded NUL and every UTF-8 byte included) '?'.
constexpr char echo_byte(const char *s, size_t i) { return echo_char_ok(s[i]) ? s[i] : '?'; }

// Does the lower-case hazard word `lit` (N - 1 letters) start at byte i of the sanitised token of m bytes?
template<size_t N> constexpr bool echo_word_at(const char *s, size_t m, size_t i, const char (&lit)[N]) {
  if (i + (N - 1) > m)
    return false;
  for (size_t k = 0; k + 1 < N; k++) {
    if (echo_fold(echo_byte(s, i + k)) != lit[k])
      return false;
  }
  return true;
}

// F2: is byte i of the sanitised token of m bytes covered by a case-insensitive occurrence of "fail" or "defer"? (An occurrence
// starting at j covers j .. j + 3 / j + 4; the two words can overlap neither each other nor themselves.)
constexpr bool echo_masked(const char *s, size_t m, size_t i) {
  for (size_t j = i >= ECHO_LOOK ? i - ECHO_LOOK : 0; j <= i; j++) {
    if ((j + 4 > i && echo_word_at(s, m, j, "fail")) || (j + 5 > i && echo_word_at(s, m, j, "defer")))
      return true;
  }
  return false;
}

// The sanitised echo of an operator-supplied token: every byte outside [A-Za-z0-9_] becomes '?', every case-insensitive "fail" and
// "defer" becomes '?' too (the matched letters only: "failed" -> "????ed", "xDeFeRrEdx" -> "x?????rEdx" - the words failed / deferred
// are never published to B9), and at most ECHO_MAX bytes are published. The mask looks ECHO_LOOK bytes past the cut, so an occurrence
// cut by the ECHO_MAX truncation is masked as far as visible.
constexpr void put_sanitised(TextBuf &t, const char *s, size_t n) {
  if (s == nullptr)
    return;
  const size_t m = n < ECHO_MAX + ECHO_LOOK ? n : ECHO_MAX + ECHO_LOOK;  // the bytes examined
  for (size_t i = 0; i < m && i < ECHO_MAX; i++)
    put_char(t, echo_masked(s, m, i) ? '?' : echo_byte(s, i));
}
constexpr void put_sanitised(TextBuf &t, const char *s) { put_sanitised(t, s, bounded_len(s, ECHO_MAX + ECHO_LOOK)); }

constexpr TextBuf unsupported_action_text(const char *action, size_t n) {
  TextBuf t;
  put(t, "REFUSED - unsupported action '");
  put_sanitised(t, action, n);
  put_char(t, '\'');
  return t;
}
constexpr TextBuf unsupported_action_text(const char *action) { return unsupported_action_text(action, bounded_len(action, ECHO_MAX + ECHO_LOOK)); }

// RESTORE and ACKNOWLEDGE are reserved tokens (not implemented in this firmware); every other value of `token` is an
// unsupported action and echoes the sanitised text.
constexpr TextBuf action_refusal_text(uint8_t token, const char *action, size_t n) {
  if (token == ACT_RESTORE) {
    TextBuf t;
    put(t, "RESTORE REFUSED - not implemented in this firmware");
    return t;
  }
  if (token == ACT_ACKNOWLEDGE) {
    TextBuf t;
    put(t, "ACKNOWLEDGE REFUSED - not implemented in this firmware");
    return t;
  }
  return unsupported_action_text(action, n);
}

// ---------------------------------------------------------------------------
// Confirmation grammar:  ^(SAVE|INVALIDATE) [0-9A-F]{16}( REPLACE CORRUPT)?$  with REPLACE CORRUPT only after SAVE.
// Byte-exact: lower-case hex, a trailing newline or space, a double space or a missing id are all INVALID.
// ---------------------------------------------------------------------------
constexpr bool hex_digit_ok(char c) { return (c >= '0' && c <= '9') || (c >= 'A' && c <= 'F'); }

constexpr bool is_hex16(const char *s, size_t n) {
  if (s == nullptr || n != ID_DIGITS)
    return false;
  for (size_t i = 0; i < ID_DIGITS; i++) {
    if (!hex_digit_ok(s[i]))
      return false;
  }
  return true;
}
constexpr bool is_hex16(const char *s) { return is_hex16(s, bounded_len(s, ID_DIGITS)); }

constexpr uint64_t parse_hex16(const char *s, size_t n) {
  if (!is_hex16(s, n))
    return 0;
  uint64_t v = 0;
  for (size_t i = 0; i < ID_DIGITS; i++) {
    const char c = s[i];
    const uint64_t d = (c >= 'A') ? (uint64_t) (c - 'A' + 10) : (uint64_t) (c - '0');
    v = (v << 4) | d;
  }
  return v;
}
constexpr uint64_t parse_hex16(const char *s) { return parse_hex16(s, bounded_len(s, ID_DIGITS)); }

struct Phrase {
  uint8_t kind = PHRASE_INVALID;
  uint64_t id = 0;
};

constexpr Phrase parse_phrase(const char *confirmation, size_t n) {
  Phrase p{};
  size_t head = 0;
  uint8_t kind = PHRASE_INVALID;
  if (starts_with(confirmation, n, "SAVE ")) {
    head = 5;
    kind = PHRASE_SAVE;
  } else if (starts_with(confirmation, n, "INVALIDATE ")) {
    head = 11;
    kind = PHRASE_INVALIDATE;
  } else {
    return p;
  }
  if (n < head + ID_DIGITS || !is_hex16(confirmation + head, ID_DIGITS))
    return p;
  const size_t after = head + ID_DIGITS;
  if (n == after) {
    p.kind = kind;
    p.id = parse_hex16(confirmation + head, ID_DIGITS);
    return p;
  }
  if (kind == PHRASE_SAVE && n > after && exact(confirmation + after, n - after, " REPLACE CORRUPT")) {
    p.kind = PHRASE_SAVE_REPLACE_CORRUPT;
    p.id = parse_hex16(confirmation + head, ID_DIGITS);
  }
  return p;
}
constexpr Phrase parse_phrase(const char *confirmation) { return parse_phrase(confirmation, bounded_len(confirmation, PHRASE_SCAN_MAX)); }

// The phrase the operator must type: "SAVE <id>", "SAVE <id> REPLACE CORRUPT" or "INVALIDATE <id>"; empty for any other kind.
constexpr TextBuf expected_phrase(uint8_t kind, uint64_t id) {
  TextBuf t;
  if (kind == PHRASE_SAVE || kind == PHRASE_SAVE_REPLACE_CORRUPT)
    put(t, "SAVE ");
  else if (kind == PHRASE_INVALIDATE)
    put(t, "INVALIDATE ");
  else
    return t;
  put_hex(t, id, 16);
  if (kind == PHRASE_SAVE_REPLACE_CORRUPT)
    put(t, " REPLACE CORRUPT");
  return t;
}

// Byte compare of the n bytes at `confirmation` against an expected phrase (an empty expected phrase never matches).
constexpr bool phrase_equals(const char *confirmation, size_t n, const TextBuf &expected) {
  if (confirmation == nullptr || expected.size() == 0 || n != expected.size())
    return false;
  for (size_t i = 0; i < n; i++) {
    if (confirmation[i] != expected.buf[i])
      return false;
  }
  return true;
}
constexpr bool phrase_equals(const char *confirmation, const TextBuf &expected) {
  return phrase_equals(confirmation, bounded_len(confirmation, expected.size()), expected);
}

// ---------------------------------------------------------------------------
// Arm TTL, integrity, class overlay
// ---------------------------------------------------------------------------
// Wrap-safe: an arm that has been on for ARM_TTL_MS or more is expired (the housekeeping tick turns it off).
constexpr bool arm_expired(uint32_t now_ms, uint32_t on_ms) { return (uint32_t) (now_ms - on_ms) >= ARM_TTL_MS; }

// The SAVE final lambda's integrity check: an operation is in flight and its purpose is SAVE.
constexpr bool save_integrity_ok(bool op_in_progress, uint8_t op_purpose) { return op_in_progress && op_purpose == PURPOSE_SAVE; }

// The RAM overlay: after an UNKNOWN write outcome the class is SAVE_UNCONFIRMED for the rest of the boot, whatever the
// composed class says.
constexpr uint8_t overlay_class(uint8_t cls, bool unconfirmed) {
  return unconfirmed ? (uint8_t) ecco_fbdurable::EPC_SAVE_UNCONFIRMED : cls;
}

// ---------------------------------------------------------------------------
// Text: SAVE refusals (prefix "SAVE REFUSED - ")
// ---------------------------------------------------------------------------
constexpr TextBuf save_refused(const char *body) {
  TextBuf t;
  put(t, SAVE_REFUSED_PREFIX);
  put(t, body);
  return t;
}
constexpr TextBuf invalidate_refused(const char *body) {
  TextBuf t;
  put(t, INVALIDATE_REFUSED_PREFIX);
  put(t, body);
  return t;
}

constexpr TextBuf save_in_flight_text() { return save_refused("another Fallback Profile operation is in progress"); }
constexpr TextBuf save_arm_off_text() { return save_refused("ECCO Fallback Profile Arm is not on"); }
constexpr TextBuf save_no_candidate_text() { return save_refused("no saveable candidate - press Review Current Configuration first"); }
constexpr TextBuf save_expired_text() { return save_refused("candidate expired (120 s) - review again"); }
constexpr TextBuf save_id_format_text() { return save_refused("candidate ID must be 16 hex characters"); }
constexpr TextBuf save_id_mismatch_text() { return save_refused("candidate ID does not match the current candidate"); }
constexpr TextBuf save_phrase_text(const TextBuf &expected) {
  TextBuf t;
  put(t, SAVE_REFUSED_PREFIX);
  put(t, "confirmation phrase mismatch (expected '");
  put(t, expected.c_str());
  put(t, "')");
  return t;
}
constexpr TextBuf save_not_loaded_text() { return save_refused("durable state not loaded yet"); }
constexpr TextBuf save_prior_unknown_text() { return save_refused("previous save outcome unknown this boot - reboot to re-verify first"); }
constexpr TextBuf save_anomaly_text() { return save_refused("stored profile read anomaly this boot; reboot to re-derive it first"); }
constexpr TextBuf save_hb_text() {
  return save_refused("Home Assistant heartbeat is not stable; wait until the dashboard shows it healthy, then review and save again");
}
constexpr TextBuf save_time_text() { return save_refused("clock not NTP-synchronised this boot; the capture time would be untrusted"); }
constexpr TextBuf save_arms_text() {
  return save_refused("a Free Power / Dump to Grid / Manual Configuration write arm is on; finish or turn it off first");
}
constexpr TextBuf save_writes_text() { return save_refused("another ECCO inverter write started since Review - review again"); }
constexpr TextBuf save_internal_text() { return save_refused("internal: gate state unavailable; nothing written"); }
// The B9 line published when the SAVE gate accepts (lower case like the REVIEW in-progress line: it is not an outcome).
constexpr TextBuf save_in_progress_text() {
  TextBuf t;
  put(t, "save in progress - re-reading live configuration");
  return t;
}

constexpr const char *slot_label(uint8_t slot) {
  return slot == ecco_fbcap::SLOT_FP     ? "Free Power"
         : slot == ecco_fbcap::SLOT_DUMP ? "Dump to Grid"
         : slot == ecco_fbcap::SLOT_R244 ? "Register 244 test"
         : slot == ecco_fbcap::SLOT_FBS  ? "Failback record"
         : slot == ecco_fbcap::SLOT_MTOU ? "Manual TOU"
                                         : "";
}

// The body of one slot's refusal (S1 4.5 with the SAVE wording). `owner` names the bus owner, `lock_age_s` the stuck lock
// age in seconds, `dump_containment` the Dump K detail.
constexpr void put_slot_refusal_body(TextBuf &t, uint8_t slot, const SlotClass &c, uint8_t dump_containment, const char *owner,
                                     uint32_t lock_age_s) {
  const char *d = slot_label(slot);
  if (slot == ecco_fbcap::SLOT_BUS) {
    if (c.kind == ecco_fbcap::UNK_BUS_OR_LOCK_STUCK) {
      put(t, "inverter write lock held for ");
      put_u(t, lock_age_s);
      put(t, " s (possible leak); a reboot may be required");
    } else {
      put(t, "another inverter transaction is in progress (");
      put(t, owner);
      put(t, "); try again shortly");
    }
    return;
  }
  if (c.kind == ecco_fbcap::UNK_BOOT_NOT_LOADED) {
    put(t, "durable state not loaded yet");
    return;
  }
  if (c.kind == ecco_fbcap::UNK_DURABLE_UNREADABLE) {
    put(t, d);
    if (c.basis == ecco_fbcap::BASIS_RUNTIME_PROBE) {
      put(t, " recovery marker became unreadable at runtime; saving blocked until reboot. After reboot it may read "
             "absent: verify live settings first; do not erase NVS");
    } else {
      put(t, " recovery state UNKNOWN since boot (marker unreadable); an obligation cannot be ruled out; Fallback "
             "never proceeds past it");
    }
    return;
  }
  if (c.kind == ecco_fbcap::UNK_METADATA_CORRUPT) {
    put(t, d);
    if (c.basis == ecco_fbcap::BASIS_RUNTIME_PROBE) {
      put(t, " recovery marker is malformed (found at runtime); saving blocked until reboot, which re-derives it as "
             "a hard lockout");
    } else {
      put(t, " recovery metadata is CORRUPT (hard lockout); Fallback never overwrites or proceeds past it; do not "
             "erase NVS");
      if (slot == ecco_fbcap::SLOT_DUMP && dump_containment != 0) {
        put(t, "; containment K=");
        put_u(t, dump_containment);
      }
    }
    return;
  }
  if (c.kind == ecco_fbcap::UNK_DIVERGED) {
    put(t, d);
    if (c.basis == ecco_fbcap::BASIS_GHOST_RR || c.basis == ecco_fbcap::BASIS_GHOST_PC) {
      put(t, " stored marker says ");
      put(t, c.basis == ecco_fbcap::BASIS_GHOST_RR ? "RESTORE_REQUIRED" : "PENDING_CLEAR");
      put(t, " but memory says clear; saving blocked until reboot, which re-derives it (the domain may then restore "
             "its saved original)");
    } else {
      put(t, " in-memory recovery state is inconsistent; a reboot must re-derive it before saving");
    }
    return;
  }
  if (c.kind == ecco_fbcap::UNK_BUS_OR_LOCK_STUCK) {
    put(t, d);
    put(t, " in-progress flag is set with no running operation (possible leak); a reboot re-derives it");
    return;
  }
  if (c.kind == ecco_fbcap::OBL_ACTIVE) {
    if (c.basis == ecco_fbcap::BASIS_FBS_EPISODE) {
      put(t, "a failback episode record exists; only the firmware that created it can resolve it");
    } else {
      put(t, d);
      put(t, " is active; live settings are a temporary overlay - end it first");
    }
    return;
  }
  if (c.kind == ecco_fbcap::OBL_RESTORE_REQUIRED) {
    put(t, d);
    put(t, " must restore original settings first");
    return;
  }
  if (c.kind == ecco_fbcap::OBL_PENDING_CLEAR) {
    put(t, d);
    put(t, " restore verified; durable clear still pending");
    if (slot == ecco_fbcap::SLOT_R244)
      put(t, " - press Restore Original (armed)");
    return;
  }
  if (c.kind == ecco_fbcap::OBL_OPERATOR_NEEDED) {
    put(t, d);
    put(t, " needs an operator recovery action first");
    return;
  }
  if (c.kind == ecco_fbcap::OBL_STARTING) {
    put(t, "a ");
    put(t, d);
    put(t, " start is in progress; live settings are about to become a temporary overlay");
    return;
  }
  if (c.kind == ecco_fbcap::OBL_ENDING) {
    put(t, "a ");
    put(t, d);
    put(t, " restore or recovery action is running; try again when it finishes");
    return;
  }
  put(t, d);
  put(t, " state does not permit saving");
}

constexpr TextBuf save_slot_refusal_text(uint8_t slot, const SlotClass &c, uint8_t dump_containment, const char *owner,
                                         uint32_t lock_age_s) {
  TextBuf t;
  put(t, SAVE_REFUSED_PREFIX);
  put_slot_refusal_body(t, slot, c, dump_containment, owner, lock_age_s);
  return t;
}

// A capture-gate decision rendered with the SAVE wording. `g` must be the SAME inputs the decision was made over (it names
// the bus owner, the stuck-lock age and the Dump containment). An accepted / probe-pending decision has no text; an
// unset or unknown decision is an internal refusal (fail-closed).
constexpr TextBuf save_gate_refusal_text(const GateResult &gr, const GateInputs &g) {
  const char *owner = ecco_fbcap::bus_owner_text_with_leases(g.bus, gr.fp, gr.dump);
  const uint32_t age_s = ecco_fbcap::lock_age_ms(g.bus) / 1000u;
  const uint8_t dc = g.dump.dump_containment_state;
  switch (gr.code) {
    case ecco_fbcap::GATE_ACCEPT:
    case ecco_fbcap::GATE_NEED_PROBE:
      return TextBuf{};
    case ecco_fbcap::GATE_REFUSE_IN_FLIGHT:
      return save_in_flight_text();
    case ecco_fbcap::GATE_REFUSE_NOT_LOADED:
      return save_not_loaded_text();
    case ecco_fbcap::GATE_REFUSE_ARMS:
      return save_arms_text();
    case ecco_fbcap::GATE_REFUSE_BUS:
      return save_slot_refusal_text(ecco_fbcap::SLOT_BUS, gr.bus, dc, owner, age_s);
    case ecco_fbcap::GATE_REFUSE_FBS:
      return save_slot_refusal_text(ecco_fbcap::SLOT_FBS, gr.fbs, dc, owner, age_s);
    case ecco_fbcap::GATE_REFUSE_FP:
      return save_slot_refusal_text(ecco_fbcap::SLOT_FP, gr.fp, dc, owner, age_s);
    case ecco_fbcap::GATE_REFUSE_DUMP:
      return save_slot_refusal_text(ecco_fbcap::SLOT_DUMP, gr.dump, dc, owner, age_s);
    case ecco_fbcap::GATE_REFUSE_R244:
      return save_slot_refusal_text(ecco_fbcap::SLOT_R244, gr.r244, dc, owner, age_s);
    case ecco_fbcap::GATE_REFUSE_MTOU:
      return save_slot_refusal_text(ecco_fbcap::SLOT_MTOU, gr.mtou, dc, owner, age_s);
    default:
      return save_internal_text();
  }
}

// ---------------------------------------------------------------------------
// The SAVE gate
// ---------------------------------------------------------------------------
struct SaveGateInputs {
  bool arm_was_on = false;       // the arm switch state, read BEFORE the one-shot turn-off
  bool cand_valid = false;       // a candidate exists (the copy taken before the invalidation)
  bool cand_saveable = false;    // ... and it is saveable (a NOT SAVEABLE preview also has cand_valid)
  uint64_t cand_id = 0;          // the candidate id (0 when not saveable)
  uint32_t cand_ms = 0;          // the candidate birth time (uptime ms)
  uint8_t cand_prior_class = 0;  // the effective class of the stored profile the candidate was reviewed against
  uint32_t cand_writes_fp = 0;   // the writes fingerprint at Review
  uint32_t now_ms = 0;           // the lambda's current uptime ms
  uint32_t writes_fp_now = 0;    // the writes fingerprint now (a different value is a different one: not zero-sum safe)
  bool boot_loaded = false;      // the boot load of the durable state finished
  bool unconfirmed = true;       // the RAM overlay: an earlier write outcome this boot is unknown
  uint8_t read_anomaly = 0xFF;   // the per-boot read-anomaly latch
  bool hb_ok = false;            // the heartbeat snapshot taken in the action lambda
  bool time_trusted = false;     // the clock is synchronised and valid
};

struct SaveGateResult {
  uint8_t code = SG_UNSET;
  bool arm_off_only = false;      // a G1 refusal touches NOTHING but the arm
  bool replace_corrupt = false;   // the accepted SAVE replaces a CORRUPT profile (the phrase carried REPLACE CORRUPT)
  TextBuf obl;                    // the capture gate's six-slot vector text (B3 obl=)
  TextBuf text;                   // the B9 text of a refusal; empty on SG_ACCEPT
};

// G1 only: is another Fallback Profile operation in flight? It has to run BEFORE the one-shot preamble (turn the arm
// off, copy the candidate, invalidate it): the refusal touches nothing but the arm. SG_UNSET (empty text) = not in flight.
constexpr SaveGateResult save_in_flight_gate(bool op_in_progress, bool dispatch_running) {
  SaveGateResult r{};
  if (op_in_progress || dispatch_running) {
    r.code = SG_IN_FLIGHT;
    r.arm_off_only = true;
    r.text = save_in_flight_text();
  }
  return r;
}

constexpr SaveGateResult save_refuse(SaveGateResult r, uint8_t code, const TextBuf &text) {
  r.code = code;
  r.text = text;
  return r;
}

// G1-G16 in the S1 8.5 order over an ALREADY computed capture gate decision `gr` (the capture gate over `g` with no
// durable probe: GATE_NEED_PROBE counts as clear). First failure wins.
constexpr SaveGateResult save_gate_with_result(const SaveGateInputs &in, const char *action, size_t action_len,
                                               const char *target_id, size_t target_len, const char *confirmation,
                                               size_t confirmation_len, const GateInputs &g, const GateResult &gr) {
  SaveGateResult r{};
  r.obl = gr.obl;
  if (gr.code == ecco_fbcap::GATE_REFUSE_IN_FLIGHT) {  // G1
    r = save_refuse(r, SG_IN_FLIGHT, save_in_flight_text());
    r.arm_off_only = true;
    return r;
  }
  const uint8_t token = action_token(action, action_len);
  if (token != ACT_SAVE)  // G0
    return save_refuse(r, SG_UNSUPPORTED, action_refusal_text(token, action, action_len));
  if (!in.arm_was_on)  // G2
    return save_refuse(r, SG_ARM_OFF, save_arm_off_text());
  if (!in.cand_valid || !in.cand_saveable || in.cand_id == 0)  // G3
    return save_refuse(r, SG_NO_CANDIDATE, save_no_candidate_text());
  if (ecco_fbcap::candidate_expired(in.now_ms, in.cand_ms))  // G4
    return save_refuse(r, SG_EXPIRED, save_expired_text());
  if (!is_hex16(target_id, target_len))  // G5
    return save_refuse(r, SG_ID_FORMAT, save_id_format_text());
  if (parse_hex16(target_id, target_len) != in.cand_id)  // G6
    return save_refuse(r, SG_ID_MISMATCH, save_id_mismatch_text());
  const bool replace = ecco_fbdurable::save_requires_replace_phrase(in.cand_prior_class);
  const TextBuf expected = expected_phrase(replace ? PHRASE_SAVE_REPLACE_CORRUPT : PHRASE_SAVE, in.cand_id);
  if (!phrase_equals(confirmation, confirmation_len, expected))  // G7
    return save_refuse(r, SG_PHRASE, save_phrase_text(expected));
  if (!in.boot_loaded)  // G8
    return save_refuse(r, SG_NOT_LOADED, save_not_loaded_text());
  if (in.unconfirmed)  // G9
    return save_refuse(r, SG_UNCONFIRMED, save_prior_unknown_text());
  if (in.read_anomaly != 0)  // G9a
    return save_refuse(r, SG_ANOMALY, save_anomaly_text());
  if (!in.hb_ok)  // G10
    return save_refuse(r, SG_HB, save_hb_text());
  if (!in.time_trusted)  // G11
    return save_refuse(r, SG_TIME, save_time_text());
  if (gr.code == ecco_fbcap::GATE_REFUSE_NOT_LOADED)  // the capture gate disagrees with G8: still not loaded
    return save_refuse(r, SG_NOT_LOADED, save_not_loaded_text());
  if (gr.code == ecco_fbcap::GATE_REFUSE_ARMS)  // G12
    return save_refuse(r, SG_ARMS, save_arms_text());
  if (in.writes_fp_now != in.cand_writes_fp)  // G13
    return save_refuse(r, SG_WRITES, save_writes_text());
  const TextBuf slot_text = save_gate_refusal_text(gr, g);
  switch (gr.code) {  // G14-G16
    case ecco_fbcap::GATE_REFUSE_BUS:
      return save_refuse(r, SG_BUS, slot_text);
    case ecco_fbcap::GATE_REFUSE_FBS:
      return save_refuse(r, SG_FBS, slot_text);
    case ecco_fbcap::GATE_REFUSE_FP:
      return save_refuse(r, SG_FP, slot_text);
    case ecco_fbcap::GATE_REFUSE_DUMP:
      return save_refuse(r, SG_DUMP, slot_text);
    case ecco_fbcap::GATE_REFUSE_R244:
      return save_refuse(r, SG_R244, slot_text);
    case ecco_fbcap::GATE_REFUSE_MTOU:
      return save_refuse(r, SG_MTOU, slot_text);
    case ecco_fbcap::GATE_ACCEPT:
    case ecco_fbcap::GATE_NEED_PROBE:
      r.code = SG_ACCEPT;
      r.replace_corrupt = replace;
      return r;
    default:  // GATE_UNSET or an unknown code: never an accept
      return save_refuse(r, SG_UNSET, save_internal_text());
  }
}

// THE SAVE gate: the capture gate over `g` with NO durable probe (the SAVE gate reads no NVS), then G1-G16. `action`,
// `target_id` and `confirmation` are the three API strings with their byte lengths.
constexpr SaveGateResult save_gate_decide(const SaveGateInputs &in, const char *action, size_t action_len,
                                          const char *target_id, size_t target_len, const char *confirmation,
                                          size_t confirmation_len, const GateInputs &g) {
  return save_gate_with_result(in, action, action_len, target_id, target_len, confirmation, confirmation_len, g,
                               ecco_fbcap::gate_decide(g, ProbeResults{}));
}

// ---------------------------------------------------------------------------
// SAVE final: own-hold masking, bus-quiet, clock
// ---------------------------------------------------------------------------
// Inside the SAVE final lambda the operation flag, the capture dispatch and the shared write lock are all held BY THE
// SAVE ITSELF, so the capture gate would refuse them. This clears exactly those three flags and nothing else: every other
// busy flag, the write arms, the FBS slot, the lease domains and the probe latch are untouched.
constexpr GateInputs final_phase_inputs(GateInputs g) {
  g.bus.fallback_profile_op_in_progress = false;
  g.bus.fallback_profile_capture_dispatch_running = false;
  g.bus.manual_write_in_progress = false;
  return g;
}

struct FinalGate {
  GateResult gr{};  // the capture gate over the masked inputs (probe_* / latch / obl for the lambda)
  TextBuf text;     // the SAVE REFUSED text of a refusal; empty when accepted or probes are pending
};

// The obligation re-vector of the SAVE final lambda (FBS, the RAM legs, then the lazy marker probes with latching): call
// it with ProbeResults{} first and again with the probe results when it answers GATE_NEED_PROBE.
constexpr FinalGate final_gate_decide(const GateInputs &g, const ProbeResults &pr) {
  FinalGate f{};
  const GateInputs m = final_phase_inputs(g);
  f.gr = ecco_fbcap::gate_decide(m, pr);
  f.text = save_gate_refusal_text(f.gr, m);
  return f;
}

// The last check before the writer call of the SAVE final lambda: the SAVE still owns the operation flag and the write
// lock, and nobody else touches the bus.
constexpr bool commit_bus_quiet(bool op_in_progress, bool mutex_held, bool correction_in_progress, bool tx_buffer_empty,
                                bool tx_blocked) {
  return op_in_progress && mutex_held && !correction_in_progress && tx_buffer_empty && !tx_blocked;
}
constexpr TextBuf save_bus_quiet_text() { return save_refused("inverter bus not quiet at commit; profile unchanged"); }

// SAVE final step 6: the clock is synchronised AND the captured epoch is not zero.
constexpr bool clock_trusted_for_save(bool time_trusted, uint32_t epoch) { return time_trusted && epoch != 0; }

// ---------------------------------------------------------------------------
// Text: SAVE final refusals
// ---------------------------------------------------------------------------
constexpr TextBuf save_prior_changed_text() { return save_refused("stored profile changed since Review; profile unchanged"); }
constexpr TextBuf save_generation_text() { return save_refused("profile generation counter exhausted; profile unchanged"); }
constexpr TextBuf save_internal_record_text() { return save_refused("internal: built record did not validate; nothing written"); }

// The effective class does not permit a Save: UNREADABLE names its why; every other class is a generic refusal.
constexpr TextBuf save_class_text(uint8_t cls, uint8_t why) {
  if (cls == ecco_fbdurable::EPC_SAVE_UNCONFIRMED)
    return save_prior_unknown_text();
  TextBuf t;
  put(t, SAVE_REFUSED_PREFIX);
  if (cls == ecco_fbdurable::EPC_UNREADABLE) {
    put(t, "stored profile UNREADABLE (");
    put(t, ecco_fbcap::why_name(why));
    put(t, "); reboot to re-derive it (it will then read VALID, LOST or NOT_CAPTURED)");
  } else {
    put(t, "stored profile state does not permit saving");
  }
  return t;
}

// A read step did not deliver its words: the REVIEW detail with the SAVE prefix and the unchanged-profile suffix.
constexpr TextBuf save_read_fail_text(uint8_t code, uint8_t step, uint8_t exception_code) {
  TextBuf t;
  put(t, SAVE_REFUSED_PREFIX);
  if (code == ecco_fbcap::READ_IDLE_TIMEOUT) {
    put(t, "inverter bus stayed busy for 7 s; profile unchanged; review again");
    return t;
  }
  const TextBuf detail = ecco_fbcap::read_fail_text(code, step, exception_code);
  const size_t skip = sizeof(ecco_fbcap::NOT_COMPLETED_PREFIX) - 1;
  for (size_t i = skip; i < detail.size(); i++)
    put_char(t, detail.buf[i]);
  put(t, "; profile unchanged");
  return t;
}

// Pass 1 and pass 2 disagree (the first differing register named).
constexpr TextBuf save_changed_during_read_text(const CaptureWords &a, const CaptureWords &b) {
  TextBuf t;
  const int k = ecco_fbcap::first_diff(a, b);
  put(t, SAVE_REFUSED_PREFIX);
  put(t, "live configuration changed during the read (register ");
  put_u(t, ecco_fbcap::reg_of(k));
  put(t, ": ");
  put_u(t, k >= 0 ? a[(size_t) k] : (uint16_t) 0);
  put(t, " then ");
  put_u(t, k >= 0 ? b[(size_t) k] : (uint16_t) 0);
  put(t, "); profile unchanged");
  return t;
}

// Pass 2 differs from the reviewed candidate (the first differing register named).
constexpr TextBuf save_changed_since_review_text(const CaptureWords &candidate, const CaptureWords &pass2) {
  TextBuf t;
  const int k = ecco_fbcap::first_diff(candidate, pass2);
  put(t, SAVE_REFUSED_PREFIX);
  put(t, "live configuration changed since Review (register ");
  put_u(t, ecco_fbcap::reg_of(k));
  put(t, ": reviewed ");
  put_u(t, k >= 0 ? candidate[(size_t) k] : (uint16_t) 0);
  put(t, ", now ");
  put_u(t, k >= 0 ? pass2[(size_t) k] : (uint16_t) 0);
  put(t, "); profile unchanged; review again");
  return t;
}

// The live words no longer pass the capture checks (defence in depth): the first two reasons of the REVIEW text.
constexpr TextBuf save_l2_text(const ecco_fbcap::Refusals &r, const CaptureWords &words) {
  TextBuf t;
  put(t, SAVE_REFUSED_PREFIX);
  const TextBuf reasons = ecco_fbcap::not_saveable_text(r, words, ecco_fbdurable::EPC_VALID, 0);
  const size_t skip = 25;  // "CANDIDATE NOT SAVEABLE - "
  for (size_t i = skip; i < reasons.size(); i++)
    put_char(t, reasons.buf[i]);
  put(t, "; profile unchanged");
  return t;
}

// ---------------------------------------------------------------------------
// The INVALIDATE gate (one synchronous lambda: it never waits and holds no lock)
// ---------------------------------------------------------------------------
struct InvalidateGateInputs {
  bool arm_was_on = false;                                  // read BEFORE the one-shot turn-off
  bool boot_loaded = false;
  uint8_t read_anomaly = 0xFF;
  bool unconfirmed = true;
  uint8_t cls = ecco_fbdurable::EPC_UNREADABLE;             // the RAM mirror's effective class
  uint8_t p_load = ecco_fallback::LOAD_STORAGE_UNAVAILABLE;
  ecco_fallback::FallbackProfileV1 p{};                     // the RAM mirror's profile
  uint8_t w_load = ecco_fallback::LOAD_STORAGE_UNAVAILABLE;
  ecco_fbdurable::FailbackProvisionV1 w{};                  // the RAM mirror's witness
  uint32_t seen_hw_gen = 0xFFFFFFFFu;                       // fail-closed: nothing can pass the high-water mark
  BusInputs bus{};                                          // PERMISSIVE idle defaults: assign every field
  bool tx_buffer_empty = false;
  bool tx_blocked = true;
  uint8_t fbs_slot = ecco_fbdurable::FBS_UNREADABLE;
};

struct InvalidateGateResult {
  uint8_t code = IG_UNSET;
  bool arm_off_only = false;
  TextBuf text;
};

constexpr TextBuf invalidate_in_flight_text() { return invalidate_refused("another Fallback Profile operation is in progress"); }
constexpr TextBuf invalidate_arm_off_text() { return invalidate_refused("ECCO Fallback Profile Arm is not on"); }
constexpr TextBuf invalidate_id_format_text() { return invalidate_refused("profile ID must be 16 hex characters"); }
constexpr TextBuf invalidate_phrase_text(const TextBuf &expected) {
  TextBuf t;
  put(t, INVALIDATE_REFUSED_PREFIX);
  put(t, "confirmation phrase mismatch (expected '");
  put(t, expected.c_str());
  put(t, "')");
  return t;
}
constexpr TextBuf invalidate_not_loaded_text() { return invalidate_refused("durable state not loaded yet (starting up)"); }
constexpr TextBuf invalidate_anomaly_text() { return invalidate_refused("stored profile read anomaly this boot; reboot to re-derive first"); }
constexpr TextBuf invalidate_prior_unknown_text() {
  return invalidate_refused("previous Fallback Profile write outcome unknown this boot - reboot to re-verify first");
}
constexpr TextBuf invalidate_class_text(uint8_t cls) {
  TextBuf t;
  put(t, INVALIDATE_REFUSED_PREFIX);
  put(t, "profile is ");
  put(t, ecco_fbcap::epc_name(cls));
  put(t, "; only a VALID profile can be invalidated");
  return t;
}
constexpr TextBuf invalidate_id_mismatch_text() { return invalidate_refused("profile ID does not match the stored VALID profile"); }
constexpr TextBuf invalidate_generation_text(bool exhausted) {
  return exhausted ? invalidate_refused("generation counter exhausted")
                   : invalidate_refused("profile generation is not ahead of this boot's generation high-water mark; reboot to re-verify");
}
constexpr TextBuf invalidate_busy_text() { return invalidate_refused("inverter busy; try again"); }
constexpr TextBuf invalidate_fbs_text(const SlotClass &c) {
  TextBuf t;
  put(t, INVALIDATE_REFUSED_PREFIX);
  put_slot_refusal_body(t, ecco_fbcap::SLOT_FBS, c, 0, "", 0u);
  return t;
}

// The INVALIDATE bus predicate: nothing owns the bus (all eleven capture busy flags, a superset of the master 4.8 list)
// and the transmit queue is empty and not blocked.
constexpr bool invalidate_bus_idle(const BusInputs &b, bool tx_buffer_empty, bool tx_blocked) {
  return !ecco_fbcap::bus_busy(b) && tx_buffer_empty && !tx_blocked;
}

constexpr InvalidateGateResult invalidate_in_flight_gate(bool op_in_progress, bool dispatch_running) {
  InvalidateGateResult r{};
  if (op_in_progress || dispatch_running) {
    r.code = IG_IN_FLIGHT;
    r.arm_off_only = true;
    r.text = invalidate_in_flight_text();
  }
  return r;
}

constexpr InvalidateGateResult invalidate_refuse(InvalidateGateResult r, uint8_t code, const TextBuf &text) {
  r.code = code;
  r.text = text;
  return r;
}

// I1-I12 over the RAM mirror (cheap first: a refusal never costs an NVS read). First failure wins.
constexpr InvalidateGateResult invalidate_gate_decide(const InvalidateGateInputs &in, const char *action, size_t action_len,
                                                      const char *target_id, size_t target_len, const char *confirmation,
                                                      size_t confirmation_len) {
  InvalidateGateResult r{};
  if (in.bus.fallback_profile_op_in_progress || in.bus.fallback_profile_capture_dispatch_running) {  // I1
    r = invalidate_refuse(r, IG_IN_FLIGHT, invalidate_in_flight_text());
    r.arm_off_only = true;
    return r;
  }
  const uint8_t token = action_token(action, action_len);
  if (token != ACT_INVALIDATE)
    return invalidate_refuse(r, IG_UNSUPPORTED, action_refusal_text(token, action, action_len));
  if (!in.arm_was_on)  // I2
    return invalidate_refuse(r, IG_ARM_OFF, invalidate_arm_off_text());
  if (!is_hex16(target_id, target_len))  // I3
    return invalidate_refuse(r, IG_ID_FORMAT, invalidate_id_format_text());
  const uint64_t id = parse_hex16(target_id, target_len);
  const TextBuf expected = expected_phrase(PHRASE_INVALIDATE, id);
  if (!phrase_equals(confirmation, confirmation_len, expected))  // I4
    return invalidate_refuse(r, IG_PHRASE, invalidate_phrase_text(expected));
  if (!in.boot_loaded)  // I5
    return invalidate_refuse(r, IG_NOT_LOADED, invalidate_not_loaded_text());
  if (in.read_anomaly != 0)  // I6
    return invalidate_refuse(r, IG_ANOMALY, invalidate_anomaly_text());
  if (in.unconfirmed)  // I7
    return invalidate_refuse(r, IG_UNCONFIRMED, invalidate_prior_unknown_text());
  if (!ecco_fbdurable::invalidate_class_permitted(in.cls))  // I8
    return invalidate_refuse(r, IG_CLASS, invalidate_class_text(in.cls));
  if (in.p_load != ecco_fallback::LOAD_OK || in.p.binding != id)  // I9
    return invalidate_refuse(r, IG_ID_MISMATCH, invalidate_id_mismatch_text());
  const uint8_t wc = ecco_fbdurable::classify_witness(in.w_load, in.w);
  if (!ecco_fallback::profile_invalidate_permitted(in.p) ||
      !ecco_fbdurable::invalidate_generation_permitted(in.p.generation, wc, in.w.hw_generation, in.seen_hw_gen))  // I10
    return invalidate_refuse(r, IG_GENERATION, invalidate_generation_text(in.p.generation == ecco_fbdurable::GENERATION_MAX));
  if (!invalidate_bus_idle(in.bus, in.tx_buffer_empty, in.tx_blocked))  // I11
    return invalidate_refuse(r, IG_BUS, invalidate_busy_text());
  if (!ecco_fbdurable::fbs_slot_clear(in.fbs_slot)) {  // I12
    GateInputs gi{};
    gi.boot_loaded = in.boot_loaded;
    gi.fbs_slot = in.fbs_slot;
    return invalidate_refuse(r, IG_FBS, invalidate_fbs_text(ecco_fbcap::classify_fbs(gi)));
  }
  r.code = IG_ACCEPT;
  return r;
}

// ---------------------------------------------------------------------------
// Building the intended FBP / FBW pair
// ---------------------------------------------------------------------------
struct SavePlanInputs {
  uint8_t p_load = ecco_fallback::LOAD_STORAGE_UNAVAILABLE;   // the FRESH read of the profile key
  ecco_fallback::FallbackProfileV1 p{};
  uint32_t p_stored_len = 0;                                  // its ReadDiag.stored_len
  uint8_t w_load = ecco_fallback::LOAD_STORAGE_UNAVAILABLE;   // the FRESH read of the witness key
  ecco_fbdurable::FailbackProvisionV1 w{};
  uint32_t w_stored_len = 0;
  uint8_t cls = ecco_fbdurable::EPC_UNREADABLE;               // the composed class of that read (the latch-aware evaluate_read class)
  uint8_t why = 0;                                            // its why
  uint8_t read_anomaly = 0xFF;                                // the read latch after that read
  bool unconfirmed = true;                                    // the RAM overlay
  uint32_t seen_hw_gen = 0xFFFFFFFFu;                         // the high-water after that read
  uint8_t cand_prior_class = 0;                               // the candidate's bound prior
  uint32_t cand_prior_gen = 0;
  uint64_t cand_prior_binding = 0;
  bool replace_corrupt = false;                               // the SAVE context: the phrase carried REPLACE CORRUPT
  CaptureWords words{};                                       // pass 2 (never the candidate copy)
  uint32_t captured_epoch = 0;                                // the trusted epoch (never 0)
};

struct InvalidatePlanInputs {
  uint8_t p_load = ecco_fallback::LOAD_STORAGE_UNAVAILABLE;
  ecco_fallback::FallbackProfileV1 p{};
  uint32_t p_stored_len = 0;
  uint8_t w_load = ecco_fallback::LOAD_STORAGE_UNAVAILABLE;
  ecco_fbdurable::FailbackProvisionV1 w{};
  uint32_t w_stored_len = 0;
  uint8_t cls = ecco_fbdurable::EPC_UNREADABLE;
  uint8_t read_anomaly = 0xFF;
  bool unconfirmed = true;
  uint32_t seen_hw_gen = 0xFFFFFFFFu;
  uint64_t target_id = 0;                                     // the operator's profile id (parsed)
};

struct Plan {
  uint8_t code = PLAN_UNSET;
  TextBuf text;                                               // the refusal text; empty on PLAN_OK
  uint8_t op = 0;                                             // PROV_OP_SAVE / PROV_OP_REPLACE_CORRUPT / PROV_OP_INVALIDATE
  uint32_t generation = 0;                                    // the generation the pair carries
  ecco_fallback::FallbackProfileV1 p_new{};
  ecco_fbdurable::FailbackProvisionV1 w_new{};
};

constexpr TextBuf invalidate_changed_text() { return invalidate_refused("stored profile changed; nothing written"); }
constexpr TextBuf invalidate_internal_text() { return invalidate_refused("internal: built record did not validate; nothing written"); }
constexpr TextBuf invalidate_class_now_text(uint8_t cls) {
  TextBuf t;
  put(t, INVALIDATE_REFUSED_PREFIX);
  put(t, "profile is now ");
  put(t, ecco_fbcap::epc_name(cls));
  put(t, "; nothing written");
  return t;
}

constexpr Plan plan_refuse(Plan r, uint8_t code, const TextBuf &text) {
  r.code = code;
  r.text = text;
  return r;
}

// PO14 for a SAVE / REPLACE CORRUPT pair: the profile is VALID, the witness valid, the two compose to VALID / WHY_NONE, the
// witness names the new profile and the generation advances past `base`.
constexpr bool save_pair_valid(const ecco_fallback::FallbackProfileV1 &pn, const ecco_fbdurable::FailbackProvisionV1 &wn,
                               uint32_t base) {
  const ecco_fbdurable::EffectiveProfile e =
      ecco_fbdurable::compose_profile_class(ecco_fallback::LOAD_OK, pn, ecco_fallback::LOAD_OK, wn, 0);
  return ecco_fallback::classify_profile(ecco_fallback::LOAD_OK, pn) == ecco_fallback::PROFILE_VALID &&
         ecco_fbdurable::classify_witness(ecco_fallback::LOAD_OK, wn) == ecco_fbdurable::W_VALID &&
         e.cls == ecco_fbdurable::EPC_VALID && e.why == ecco_fbdurable::WHY_NONE && pn.generation > base &&
         wn.hw_generation == pn.generation && wn.hw_binding == pn.binding;
}

// The built SAVE / REPLACE CORRUPT pair for a FRESH prior read (S2 3.2 steps 2-8): the prior must be the one the candidate
// was reviewed against, the class must permit a Save, the generation is max(authentic prior, valid witness, seen) + 1 and
// never wraps, the payload is exactly pass 2, the witness leads (hw = the new generation) and names the AUTHENTIC prior
// (generation and binding) or 0 / 0. The result is also run through the writer's own transition check, so a PLAN_OK pair
// can never be refused as an invalid transition.
constexpr Plan plan_save(const SavePlanInputs &in) {
  Plan r{};
  const ecco_fbcap::PriorFingerprint f = ecco_fbcap::prior_fingerprint(in.p_load, in.p, in.p_stored_len);
  if (in.cls != in.cand_prior_class || f.generation != in.cand_prior_gen || f.binding != in.cand_prior_binding)
    return plan_refuse(r, PLAN_PRIOR_CHANGED, save_prior_changed_text());
  const uint8_t cls = overlay_class(in.cls, in.unconfirmed);
  if (in.unconfirmed)
    return plan_refuse(r, PLAN_UNCONFIRMED, save_prior_unknown_text());
  if (in.read_anomaly != 0)
    return plan_refuse(r, PLAN_ANOMALY, save_anomaly_text());
  if (!ecco_fbdurable::save_class_permitted(cls))
    return plan_refuse(r, PLAN_CLASS, save_class_text(cls, in.why));
  const bool replace = ecco_fbdurable::save_requires_replace_phrase(cls);
  if (in.replace_corrupt != replace)
    return plan_refuse(r, PLAN_CONTEXT, ecco_fbcap::internal_context_text());
  if (in.captured_epoch == 0)
    return plan_refuse(r, PLAN_CLOCK, save_time_text());
  const uint8_t pc = ecco_fallback::classify_profile(in.p_load, in.p);
  const uint8_t wc = ecco_fbdurable::classify_witness(in.w_load, in.w);
  const uint32_t base = ecco_fbdurable::save_generation_base(pc, in.p.generation, wc, in.w.hw_generation, in.seen_hw_gen);
  if (!ecco_fbdurable::save_generation_available(base))
    return plan_refuse(r, PLAN_GENERATION, save_generation_text());
  const uint32_t gen = base + 1u;
  ecco_fallback::FallbackProfileV1 pn = ecco_fbcap::profile_from_words(in.words);
  pn.generation = gen;
  pn.captured_epoch = in.captured_epoch;
  pn.flags = 0;
  pn.reserved0 = 0;
  pn.reserved1 = 0;
  pn = ecco_fallback::seal_profile(pn);
  const bool authentic = ecco_fbdurable::fba_authentic(pc);
  const uint8_t op = replace ? ecco_fbdurable::PROV_OP_REPLACE_CORRUPT : ecco_fbdurable::PROV_OP_SAVE;
  const ecco_fbdurable::FailbackProvisionV1 wn = ecco_fbdurable::make_provision(
      gen, pn.binding, authentic ? in.p.generation : 0u, authentic ? in.p.binding : 0u, ecco_fbdurable::FALLBACK_PROFILE_KEY,
      ecco_fallback::PROFILE_SCHEMA, op);
  if (!save_pair_valid(pn, wn, base) ||
      !ecco_fbdurable::validate_transition(wn, in.w, ecco_fbdurable::PriorDesc{in.w_load, in.w_stored_len}, pn, in.p,
                                           ecco_fbdurable::PriorDesc{in.p_load, in.p_stored_len}))
    return plan_refuse(r, PLAN_INTERNAL, save_internal_record_text());
  r.code = PLAN_OK;
  r.op = op;
  r.generation = gen;
  r.p_new = pn;
  r.w_new = wn;
  return r;
}

// PO14 for an INVALIDATE pair: the profile is INVALIDATED, the witness valid, the two compose to INVALIDATED / WHY_NONE,
// the witness names the new profile and the payload bytes [0,8) [12,16) [18,88) are exactly the prior's.
constexpr bool invalidate_pair_valid(const ecco_fallback::FallbackProfileV1 &pn, const ecco_fbdurable::FailbackProvisionV1 &wn,
                                     const ecco_fallback::FallbackProfileV1 &prior) {
  const ecco_fbdurable::EffectiveProfile e =
      ecco_fbdurable::compose_profile_class(ecco_fallback::LOAD_OK, pn, ecco_fallback::LOAD_OK, wn, 0);
  const ecco_fallback::ProfileBytes a = ecco_fallback::encode_profile(pn);
  const ecco_fallback::ProfileBytes b = ecco_fallback::encode_profile(prior);
  for (size_t i = 0; i < ecco_fallback::PROFILE_BOUND_BYTES; i++) {
    const bool changed_field = (i >= 8 && i < 12) || (i >= 16 && i < 18);  // generation, flags
    if (!changed_field && a[i] != b[i])
      return false;
  }
  return ecco_fallback::classify_profile(ecco_fallback::LOAD_OK, pn) == ecco_fallback::PROFILE_INVALIDATED &&
         ecco_fbdurable::classify_witness(ecco_fallback::LOAD_OK, wn) == ecco_fbdurable::W_VALID &&
         e.cls == ecco_fbdurable::EPC_INVALIDATED && e.why == ecco_fbdurable::WHY_NONE && wn.hw_generation == pn.generation &&
         wn.hw_binding == pn.binding && wn.last_op == ecco_fbdurable::PROV_OP_INVALIDATE;
}

// The built INVALIDATE pair for a FRESH prior read (S2 4.3): the stored profile must be effectively VALID and the one the
// operator named; invalidate_profile is called ONLY behind profile_invalidate_permitted and the generation check.
constexpr Plan plan_invalidate(const InvalidatePlanInputs &in) {
  Plan r{};
  const uint8_t cls = overlay_class(in.cls, in.unconfirmed);
  if (in.unconfirmed)
    return plan_refuse(r, PLAN_UNCONFIRMED, invalidate_prior_unknown_text());
  if (in.read_anomaly != 0)
    return plan_refuse(r, PLAN_ANOMALY, invalidate_anomaly_text());
  if (!ecco_fbdurable::invalidate_class_permitted(cls))
    return plan_refuse(r, PLAN_CLASS, invalidate_class_now_text(cls));
  if (in.p_load != ecco_fallback::LOAD_OK || in.p.binding != in.target_id)
    return plan_refuse(r, PLAN_BINDING_CHANGED, invalidate_changed_text());
  const uint8_t wc = ecco_fbdurable::classify_witness(in.w_load, in.w);
  if (!ecco_fallback::profile_invalidate_permitted(in.p) ||
      !ecco_fbdurable::invalidate_generation_permitted(in.p.generation, wc, in.w.hw_generation, in.seen_hw_gen))
    return plan_refuse(r, PLAN_GENERATION, invalidate_generation_text(in.p.generation == ecco_fbdurable::GENERATION_MAX));
  const ecco_fallback::FallbackProfileV1 pn = ecco_fallback::invalidate_profile(in.p);
  const ecco_fbdurable::FailbackProvisionV1 wn = ecco_fbdurable::make_provision(
      pn.generation, pn.binding, in.p.generation, in.p.binding, ecco_fbdurable::FALLBACK_PROFILE_KEY,
      ecco_fallback::PROFILE_SCHEMA, ecco_fbdurable::PROV_OP_INVALIDATE);
  if (!invalidate_pair_valid(pn, wn, in.p) ||
      !ecco_fbdurable::validate_transition(wn, in.w, ecco_fbdurable::PriorDesc{in.w_load, in.w_stored_len}, pn, in.p,
                                           ecco_fbdurable::PriorDesc{in.p_load, in.p_stored_len}))
    return plan_refuse(r, PLAN_INTERNAL, invalidate_internal_text());
  r.code = PLAN_OK;
  r.op = ecco_fbdurable::PROV_OP_INVALIDATE;
  r.generation = pn.generation;
  r.p_new = pn;
  r.w_new = wn;
  return r;
}

// ---------------------------------------------------------------------------
// The outcome of the writer call
// ---------------------------------------------------------------------------
// werr (B2): the first non-zero error code of the witness write, then the profile write; 0 when neither reported one.
constexpr uint32_t first_non_ok(int32_t err_w, int32_t err_p) { return (uint32_t) (err_w != 0 ? err_w : err_p); }
// us (B2): the two write durations, u32 sum.
constexpr uint32_t total_us(uint32_t w_us, uint32_t p_us) { return (uint32_t) (w_us + p_us); }

// The long operation name of the log line (S2 1.9); "-" for any other value.
constexpr const char *txn_op_name(uint8_t op) {
  return op == ecco_fbdurable::PROV_OP_SAVE              ? "SAVE"
         : op == ecco_fbdurable::PROV_OP_INVALIDATE      ? "INVALIDATE"
         : op == ecco_fbdurable::PROV_OP_REPLACE_CORRUPT ? "REPLACE_CORRUPT"
                                                         : "-";
}
constexpr const char *txn_name(uint8_t outcome) {
  return outcome == ecco_fbdurable::TXN_UNKNOWN_REBOOT    ? "UNKNOWN_REBOOT"
         : outcome == ecco_fbdurable::TXN_COMMITTED       ? "COMMITTED"
         : outcome == ecco_fbdurable::TXN_NOT_COMMITTED   ? "NOT_COMMITTED"
         : outcome == ecco_fbdurable::TXN_REFUSED_LATCHED ? "REFUSED_LATCHED"
                                                          : "?";
}
constexpr const char *key_name(uint8_t outcome) {
  return outcome == ecco_fbdurable::KEY_UNKNOWN_REBOOT   ? "UNKNOWN_REBOOT"
         : outcome == ecco_fbdurable::KEY_COMMITTED      ? "COMMITTED"
         : outcome == ecco_fbdurable::KEY_NOT_COMMITTED  ? "NOT_COMMITTED"
         : outcome == ecco_fbdurable::KEY_NOT_ATTEMPTED  ? "NOT_ATTEMPTED"
                                                         : "?";
}
constexpr const char *rb_name(uint8_t rb_class) {
  return rb_class == ecco_fbdurable::RB_NOT_READ            ? "NOT_READ"
         : rb_class == ecco_fbdurable::RB_INTENDED          ? "INTENDED"
         : rb_class == ecco_fbdurable::RB_PRIOR             ? "PRIOR"
         : rb_class == ecco_fbdurable::RB_OTHER_BYTES       ? "OTHER_BYTES"
         : rb_class == ecco_fbdurable::RB_ABSENT_UNEXPECTED ? "ABSENT_UNEXPECTED"
         : rb_class == ecco_fbdurable::RB_WRONG_SIZE        ? "WRONG_SIZE"
         : rb_class == ecco_fbdurable::RB_READ_ERROR        ? "READ_ERROR"
         : rb_class == ecco_fbdurable::RB_UNAVAILABLE       ? "UNAVAILABLE"
                                                            : "?";
}

// An error code as B2 renders it: E<hex>, or - for 0.
constexpr void put_err(TextBuf &t, uint32_t err) {
  if (err == 0) {
    put_char(t, '-');
    return;
  }
  put_char(t, 'E');
  put_hex(t, err, 1);
}

// The key whose outcome is unknown: the witness unless it COMMITTED (then the profile).
constexpr void put_unknown_detail(TextBuf &t, const ecco_fbdurable::TxnResult &r) {
  const ecco_fbdurable::KeyReport &k = r.w.outcome == ecco_fbdurable::KEY_UNKNOWN_REBOOT ? r.w : r.p;
  put_err(t, (uint32_t) k.err);
  put_char(t, '/');
  put(t, rb_name(k.rb_class));
}

constexpr TextBuf saved_text(uint32_t generation) {
  TextBuf t;
  put(t, "SAVED - known-good profile generation ");
  put_u(t, generation);
  put(t, " saved (verified this boot)");
  return t;
}
constexpr TextBuf save_not_committed_text(uint32_t err) {
  TextBuf t;
  put(t, "SAVE NOT COMMITTED - storage refused the write (");
  put_err(t, err);
  put(t, "); nothing changed");
  return t;
}
constexpr TextBuf save_witness_advanced_text() {
  TextBuf t;
  put(t, "SAVE NOT COMMITTED - witness advanced; profile unchanged; stored profile is now out of step - review and save again");
  return t;
}
constexpr TextBuf save_unknown_text(const ecco_fbdurable::TxnResult &r) {
  TextBuf t;
  put(t, "SAVE OUTCOME UNKNOWN - storage reported ");
  put_unknown_detail(t, r);
  put(t, "; reboot the dongle (when no temporary operation is active) to re-verify; saving disabled until then");
  return t;
}
constexpr TextBuf invalidated_text(uint32_t prior_generation, uint32_t generation) {
  TextBuf t;
  put(t, "INVALIDATED - profile generation ");
  put_u(t, prior_generation);
  put(t, " is no longer usable (now INVALIDATED g");
  put_u(t, generation);
  put(t, "); payload kept for reference; save a new profile to re-enable");
  return t;
}
constexpr TextBuf invalidate_not_committed_text(uint32_t err, uint32_t prior_generation) {
  TextBuf t;
  put(t, "INVALIDATE NOT COMMITTED - storage refused the write (");
  put_err(t, err);
  put(t, "); profile still VALID g");
  put_u(t, prior_generation);
  return t;
}
constexpr TextBuf invalidate_witness_advanced_text(uint32_t prior_generation) {
  TextBuf t;
  put(t, "INVALIDATE NOT COMMITTED for the profile record, but the generation record advanced: g");
  put_u(t, prior_generation);
  put(t, " is now STALE (unusable)");
  return t;
}
constexpr TextBuf invalidate_unknown_text(const ecco_fbdurable::TxnResult &r) {
  TextBuf t;
  put(t, "INVALIDATE OUTCOME UNKNOWN - ");
  put_unknown_detail(t, r);
  put(t, "; treat the profile as unusable; reboot to re-verify (Fallback Profile writes locked until reboot)");
  return t;
}

// The writer refused before writing anything (TxnOutcome REFUSED, keyed on TxnResult.refusal).
constexpr TextBuf txn_refusal_text(uint8_t op, uint8_t refusal) {
  const bool inv = op == ecco_fbdurable::PROV_OP_INVALIDATE;
  if (refusal == ecco_fbdurable::REFUSAL_LATCHED)
    return inv ? invalidate_prior_unknown_text() : save_prior_unknown_text();
  if (refusal == ecco_fbdurable::REFUSAL_INVALID_TRANSITION)
    return inv ? invalidate_internal_text() : save_internal_record_text();
  if (refusal == ecco_fbdurable::REFUSAL_STORAGE_UNAVAILABLE)
    return inv ? invalidate_refused("storage unavailable - nothing written") : save_refused("storage unavailable - nothing saved");
  if (refusal == ecco_fbdurable::REFUSAL_STORAGE_UNHEALTHY)
    return inv ? invalidate_refused("storage not healthy - nothing written") : save_refused("storage not healthy - nothing saved");
  return inv ? invalidate_refused("internal: write refused for an unknown reason; nothing written")
             : save_refused("internal: write refused for an unknown reason; nothing written");
}

// The B9 text of a finished writer call. `op` is the ProvisionOp of the plan (SAVE and REPLACE CORRUPT share the SAVE
// texts; any other op is an internal context text), `generation` the generation the plan carried and `prior_generation`
// the stored profile's generation (INVALIDATE only).
constexpr TextBuf txn_outcome_text(uint8_t op, uint8_t outcome, const ecco_fbdurable::TxnResult &r, uint32_t generation,
                                   uint32_t prior_generation) {
  const bool inv = op == ecco_fbdurable::PROV_OP_INVALIDATE;
  if (!inv && op != ecco_fbdurable::PROV_OP_SAVE && op != ecco_fbdurable::PROV_OP_REPLACE_CORRUPT)
    return ecco_fbcap::internal_context_text();
  if (outcome == ecco_fbdurable::TXN_COMMITTED)
    return inv ? invalidated_text(prior_generation, generation) : saved_text(generation);
  if (outcome == ecco_fbdurable::TXN_NOT_COMMITTED) {
    if (r.witness_advanced != 0)
      return inv ? invalidate_witness_advanced_text(prior_generation) : save_witness_advanced_text();
    return inv ? invalidate_not_committed_text((uint32_t) r.w.err, prior_generation) : save_not_committed_text((uint32_t) r.w.err);
  }
  if (outcome == ecco_fbdurable::TXN_REFUSED_LATCHED)
    return txn_refusal_text(op, r.refusal);
  return inv ? invalidate_unknown_text(r) : save_unknown_text(r);  // TXN_UNKNOWN_REBOOT and any unknown outcome: never success
}

// The serial-log line of one writer call (S2 1.9): the long operation name, the generation, both keys (error, readback, outcome) and
// total_us, then the TxnOutcome. The per-key us= fields of S2 1.9 are NOT printed: with the long operation names the line would be 213
// characters at the widest values (over the 200-character TextBuf), without them it is 185. total_us is their wrapping sum.
constexpr TextBuf txn_log_text(uint8_t op, uint8_t outcome, const ecco_fbdurable::TxnResult &r, uint32_t generation) {
  TextBuf t;
  put(t, "txn=");
  put(t, txn_op_name(op));
  put(t, " gen=");
  put_u(t, generation);
  put(t, " w:err=");
  put_err(t, (uint32_t) r.w.err);
  put(t, " rb=");
  put(t, rb_name(r.w.rb_class));
  put(t, " out=");
  put(t, key_name(r.w.outcome));
  put(t, " p:err=");
  put_err(t, (uint32_t) r.p.err);
  put(t, " rb=");
  put(t, rb_name(r.p.rb_class));
  put(t, " out=");
  put(t, key_name(r.p.outcome));
  put(t, " total_us=");
  put_u(t, total_us(r.w.us, r.p.us));
  put(t, " -> ");
  put(t, txn_name(outcome));
  return t;
}

// The forensic log of a REPLACE CORRUPT: the discarded stored profile, in two parts of 48 bytes (part 0 / 1), or its
// stored length when it was the wrong size. Empty for any other load or part.
constexpr TextBuf replace_corrupt_log_text(uint8_t p_load, const ecco_fallback::FallbackProfileV1 &p, uint32_t stored_len,
                                           uint8_t part) {
  TextBuf t;
  if (p_load == ecco_fallback::LOAD_WRONG_SIZE && part == 0) {
    put(t, "REPLACE CORRUPT discards a stored profile of the wrong size, stored length ");
    put_u(t, stored_len);
    return t;
  }
  if (p_load != ecco_fallback::LOAD_OK || part > 1)
    return t;
  const ecco_fallback::ProfileBytes b = ecco_fallback::encode_profile(p);
  put(t, part == 0 ? "REPLACE CORRUPT discards stored profile bytes 0-47: " : "REPLACE CORRUPT discards stored profile bytes 48-95: ");
  for (size_t i = (size_t) part * 48; i < (size_t) part * 48 + 48; i++)
    put_hex(t, b[i], 2);
  return t;
}

// ---- GOLDENS-BEGIN ----

// ---------------------------------------------------------------------------
// Compile-time golden vectors and golden-case tables. registry/tests/test_fallback_save_host_compile.py parses every
// labelled static_assert below and requires the Python mirror to reproduce each value / string EXACTLY; the model suite
// (registry/tests/test_fallback_save_model.py) re-derives the golden-case tables from registry/fallback_save.py. Nothing in
// the firmware calls anything below the GOLDENS-BEGIN marker (the fx_* fixtures exist only for these golden expressions).
// ---------------------------------------------------------------------------

constexpr uint64_t FX_ID = 0x0123456789ABCDEFULL;  // the candidate id of the SAVE gate fixtures
constexpr uint32_t FX_BORN_MS = 4294960000u;       // a candidate born just before the 2^32 uptime wrap
constexpr uint32_t FX_EPOCH = 1790000500u;         // a trusted capture time

// ---- profile / witness fixtures (ecco_fbcap::GOLDEN_PROFILE is the FB-A golden VALID profile, generation 7) ----
constexpr ecco_fallback::FallbackProfileV1 fx_profile(uint32_t generation, uint16_t flags) {
  ecco_fallback::FallbackProfileV1 p = ecco_fbcap::GOLDEN_PROFILE;
  p.generation = generation;
  p.flags = flags;
  return ecco_fallback::seal_profile(p);
}
constexpr ecco_fallback::FallbackProfileV1 fx_profile_bad(uint32_t generation) {  // a binding defect: CORRUPT
  ecco_fallback::FallbackProfileV1 p = fx_profile(generation, 0);
  p.binding ^= 1u;
  return p;
}
constexpr ecco_fallback::FallbackProfileV1 fx_profile_domain(uint32_t generation) {  // 244 = 1, sealed: CORRUPT_DOMAIN
  ecco_fallback::FallbackProfileV1 p = ecco_fbcap::GOLDEN_PROFILE;
  p.generation = generation;
  p.reg244 = 1;
  return ecco_fallback::seal_profile(p);
}

struct FxP {
  uint8_t load;
  ecco_fallback::FallbackProfileV1 p;
  uint32_t len;
};
// pk: 0 ABSENT, 1 VALID g7, 2 INVALIDATED g8, 3 CORRUPT_DOMAIN g9, 4 CORRUPT g11 (binding), 5 WRONG_SIZE (40 bytes), 6 READ_ERROR,
// 7 STORAGE_UNAVAILABLE, 8 VALID g0xFFFFFFFF, 9 VALID g3
constexpr FxP fx_p(uint8_t pk) {
  const ecco_fallback::FallbackProfileV1 none{};
  switch (pk) {
    case 0:
      return FxP{ecco_fallback::LOAD_ABSENT, none, 0u};
    case 1:
      return FxP{ecco_fallback::LOAD_OK, fx_profile(7u, 0), 0u};
    case 2:
      return FxP{ecco_fallback::LOAD_OK, fx_profile(8u, 1), 0u};
    case 3:
      return FxP{ecco_fallback::LOAD_OK, fx_profile_domain(9u), 0u};
    case 4:
      return FxP{ecco_fallback::LOAD_OK, fx_profile_bad(11u), 0u};
    case 5:
      return FxP{ecco_fallback::LOAD_WRONG_SIZE, none, 40u};
    case 6:
      return FxP{ecco_fallback::LOAD_READ_ERROR, none, 0u};
    case 7:
      return FxP{ecco_fallback::LOAD_STORAGE_UNAVAILABLE, none, 0u};
    case 8:
      return FxP{ecco_fallback::LOAD_OK, fx_profile(0xFFFFFFFFu, 0), 0u};
    default:
      return FxP{ecco_fallback::LOAD_OK, fx_profile(3u, 0), 0u};
  }
}

struct FxW {
  uint8_t load;
  ecco_fbdurable::FailbackProvisionV1 w;
  uint32_t len;
};
constexpr ecco_fbdurable::FailbackProvisionV1 fx_witness(uint32_t hw, uint64_t hw_binding, uint32_t prior_gen,
                                                         uint64_t prior_binding, uint32_t tag_key, uint8_t op) {
  return ecco_fbdurable::make_provision(hw, hw_binding, prior_gen, prior_binding, tag_key, 1, op);
}
// wk (relative to the stored profile p; a record-less prior uses generation 9): 0 ABSENT, 1 consistent (hw = g), 2 lagging (hw = g - 1),
// 3 corrupt, 4 WRONG_SIZE, 5 READ_ERROR, 6 first save unconfirmed (hw 1), 7 lost high-water 5, 8 interrupted (hw = g + 1, prior = g),
// 9 rollback (hw = g + 3), 10 hw 0xFFFFFFFF consistent, 11 foreign tag, 12 last op INVALIDATE, 13 same generation, other binding,
// 14 corrupt with hw 0x7FFFFFFF, 15 WRONG_SIZE carrying a record with hw 0x7FFFFFFF, 16 ABSENT carrying a record with hw 0x7FFFFFFF (14-16: a
// witness that is not VALID must never raise the generation high-water, whatever its hw field says)
constexpr FxW fx_w(uint8_t wk, const ecco_fallback::FallbackProfileV1 &p) {
  const ecco_fbdurable::FailbackProvisionV1 none{};
  const uint32_t g = p.generation != 0u ? p.generation : 9u;
  const uint64_t b = p.binding;
  const uint64_t pb = 0x1122334455667788ULL;
  const uint32_t key = ecco_fbdurable::FALLBACK_PROFILE_KEY;
  switch (wk) {
    case 0:
      return FxW{ecco_fallback::LOAD_ABSENT, none, 0u};
    case 1:
      return FxW{ecco_fallback::LOAD_OK, fx_witness(g, b, g > 1u ? g - 1u : 0u, g > 1u ? pb : 0ULL, key, ecco_fbdurable::PROV_OP_SAVE), 0u};
    case 2:
      return FxW{ecco_fallback::LOAD_OK, fx_witness(g - 1u, 0x77ULL, g - 2u, pb, key, ecco_fbdurable::PROV_OP_SAVE), 0u};
    case 3: {
      ecco_fbdurable::FailbackProvisionV1 w = fx_witness(g, b, g > 1u ? g - 1u : 0u, g > 1u ? pb : 0ULL, key, ecco_fbdurable::PROV_OP_SAVE);
      w.binding ^= 1u;
      return FxW{ecco_fallback::LOAD_OK, w, 0u};
    }
    case 4:
      return FxW{ecco_fallback::LOAD_WRONG_SIZE, none, 40u};
    case 5:
      return FxW{ecco_fallback::LOAD_READ_ERROR, none, 0u};
    case 6:
      return FxW{ecco_fallback::LOAD_OK, fx_witness(1u, 0x99ULL, 0u, 0ULL, key, ecco_fbdurable::PROV_OP_SAVE), 0u};
    case 7:
      return FxW{ecco_fallback::LOAD_OK, fx_witness(5u, 0x99ULL, 4u, 0xABULL, key, ecco_fbdurable::PROV_OP_SAVE), 0u};
    case 8:
      return FxW{ecco_fallback::LOAD_OK, fx_witness(g + 1u, 0x99ULL, g, b, key, ecco_fbdurable::PROV_OP_SAVE), 0u};
    case 9:
      return FxW{ecco_fallback::LOAD_OK, fx_witness(g + 3u, 0x99ULL, g + 2u, 0xABULL, key, ecco_fbdurable::PROV_OP_SAVE), 0u};
    case 10:
      return FxW{ecco_fallback::LOAD_OK, fx_witness(0xFFFFFFFFu, b, 0xFFFFFFFEu, 0xABULL, key, ecco_fbdurable::PROV_OP_SAVE), 0u};
    case 11:
      return FxW{ecco_fallback::LOAD_OK, fx_witness(g, b, g > 1u ? g - 1u : 0u, g > 1u ? pb : 0ULL, 5u, ecco_fbdurable::PROV_OP_SAVE), 0u};
    case 12:
      return FxW{ecco_fallback::LOAD_OK, fx_witness(g, b, g > 1u ? g - 1u : 0u, g > 1u ? pb : 0ULL, key, ecco_fbdurable::PROV_OP_INVALIDATE), 0u};
    case 14: {
      ecco_fbdurable::FailbackProvisionV1 w = fx_witness(0x7FFFFFFFu, b, g > 1u ? g - 1u : 0u, g > 1u ? pb : 0ULL, key, ecco_fbdurable::PROV_OP_SAVE);
      w.binding ^= 1u;
      return FxW{ecco_fallback::LOAD_OK, w, 0u};
    }
    case 15:
      return FxW{ecco_fallback::LOAD_WRONG_SIZE, fx_witness(0x7FFFFFFFu, b, 0u, 0ULL, key, ecco_fbdurable::PROV_OP_SAVE), 40u};
    case 16:
      return FxW{ecco_fallback::LOAD_ABSENT, fx_witness(0x7FFFFFFFu, b, 0u, 0ULL, key, ecco_fbdurable::PROV_OP_SAVE), 0u};
    default:
      return FxW{ecco_fallback::LOAD_OK, fx_witness(g, b ^ 1u, g > 1u ? g - 1u : 0u, g > 1u ? pb : 0ULL, key, ecco_fbdurable::PROV_OP_SAVE), 0u};
  }
}

// A faithful SAVE plan input for a stored pair: the composed class, the candidate bound to exactly this prior, pass-2 words = the
// golden words, a trusted epoch.
constexpr SavePlanInputs fx_save_from(uint8_t pl, const ecco_fallback::FallbackProfileV1 &p, uint32_t plen, uint8_t wl,
                                      const ecco_fbdurable::FailbackProvisionV1 &w, uint32_t wlen, uint32_t seen) {
  SavePlanInputs in{};
  in.p_load = pl;
  in.p = p;
  in.p_stored_len = plen;
  in.w_load = wl;
  in.w = w;
  in.w_stored_len = wlen;
  const ecco_fbdurable::EffectiveProfile e = ecco_fbdurable::compose_profile_class(pl, p, wl, w, 0);
  in.cls = e.cls;
  in.why = e.why;
  in.read_anomaly = 0;
  in.unconfirmed = false;
  in.seen_hw_gen = seen;
  const ecco_fbcap::PriorFingerprint f = ecco_fbcap::prior_fingerprint(pl, p, plen);
  in.cand_prior_class = e.cls;
  in.cand_prior_gen = f.generation;
  in.cand_prior_binding = f.binding;
  in.replace_corrupt = e.cls == ecco_fbdurable::EPC_CORRUPT;
  in.words = ecco_fbcap::GOLDEN_WORDS;
  in.captured_epoch = FX_EPOCH;
  return in;
}
constexpr SavePlanInputs fx_save_inputs(uint8_t pk, uint8_t wk, uint32_t seen) {
  const FxP pr = fx_p(pk);
  const FxW wr = fx_w(wk, pr.p);
  return fx_save_from(pr.load, pr.p, pr.len, wr.load, wr.w, wr.len, seen);
}
// The input mutations of the SAVE plan table (see SP_CASES).
constexpr SavePlanInputs fx_save_mut(SavePlanInputs in, uint8_t mut) {
  switch (mut) {
    case 1:
      in.unconfirmed = true;
      break;
    case 2:
      in.read_anomaly = 4;
      break;
    case 3:
      in.replace_corrupt = !in.replace_corrupt;
      break;
    case 4:
      in.captured_epoch = 0;
      break;
    case 5:
      in.cand_prior_class = in.cand_prior_class != 1 ? 1 : 5;
      break;
    case 6:
      in.cand_prior_gen += 1u;
      break;
    case 7:
      in.cand_prior_binding ^= 1u;
      break;
    case 8:
      in.cand_prior_class = in.cand_prior_class != 1 ? 1 : 5;
      in.unconfirmed = true;
      break;
    case 9:
      in.unconfirmed = true;
      in.read_anomaly = 4;
      break;
    case 10:
      in.read_anomaly = 4;
      in.replace_corrupt = !in.replace_corrupt;
      break;
    case 11:
      in.replace_corrupt = !in.replace_corrupt;
      in.captured_epoch = 0;
      break;
    case 12:
      in.captured_epoch = 0;
      in.seen_hw_gen = 0xFFFFFFFFu;
      break;
    case 13:  // the class the caller passes is the SAVE_UNCONFIRMED overlay value itself (bound to the candidate)
      in.cls = 7;
      in.cand_prior_class = 7;
      break;
    case 14:  // ... or a class value outside the table
      in.cls = 9;
      in.cand_prior_class = 9;
      break;
    case 15:  // SEM-1: the candidate's bound prior binding differs only in its HIGH 32 bits (bit 63) ...
      in.cand_prior_binding ^= 0x8000000000000000ULL;
      break;
    case 16:  // ... only in bit 32 (the lowest bit of the high word) ...
      in.cand_prior_binding ^= 0x100000000ULL;
      break;
    case 17:  // ... or is only its LOW 32 bits (the high word cleared)
      in.cand_prior_binding &= 0xFFFFFFFFULL;
      break;
    default:
      break;
  }
  return in;
}

constexpr InvalidatePlanInputs fx_inv_from(uint8_t pl, const ecco_fallback::FallbackProfileV1 &p, uint32_t plen, uint8_t wl,
                                           const ecco_fbdurable::FailbackProvisionV1 &w, uint32_t wlen, uint32_t seen) {
  InvalidatePlanInputs in{};
  in.p_load = pl;
  in.p = p;
  in.p_stored_len = plen;
  in.w_load = wl;
  in.w = w;
  in.w_stored_len = wlen;
  in.cls = ecco_fbdurable::compose_profile_class(pl, p, wl, w, 0).cls;
  in.read_anomaly = 0;
  in.unconfirmed = false;
  in.seen_hw_gen = seen;
  in.target_id = p.binding;
  return in;
}
constexpr InvalidatePlanInputs fx_inv_inputs(uint8_t pk, uint8_t wk, uint32_t seen) {
  const FxP pr = fx_p(pk);
  const FxW wr = fx_w(wk, pr.p);
  return fx_inv_from(pr.load, pr.p, pr.len, wr.load, wr.w, wr.len, seen);
}
// mut: 0 none, 1 unconfirmed, 2 anomaly, 3 the operator named another binding, 4 target id 0, 5 unconfirmed and anomaly, 6 the named binding differs
// only in bit 63, 7 only in bit 32, 8 in every bit of the high word, 9 is only the LOW 32 bits (high word cleared), 10 the composed class is forced to VALID
constexpr InvalidatePlanInputs fx_inv_mut(InvalidatePlanInputs in, uint8_t mut) {
  switch (mut) {
    case 1:
      in.unconfirmed = true;
      break;
    case 2:
      in.read_anomaly = 4;
      break;
    case 3:
      in.target_id ^= 1u;
      break;
    case 4:
      in.target_id = 0;
      break;
    case 5:
      in.unconfirmed = true;
      in.read_anomaly = 4;
      break;
    case 6:
      in.target_id ^= 0x8000000000000000ULL;
      break;
    case 7:
      in.target_id ^= 0x100000000ULL;
      break;
    case 8:
      in.target_id ^= 0xFFFFFFFF00000000ULL;
      break;
    case 9:
      in.target_id &= 0xFFFFFFFFULL;
      break;
    case 10:
      in.cls = ecco_fbdurable::EPC_VALID;
      break;
    default:
      break;
  }
  return in;
}

// Every field of m equals the field of g, except the three own holds, which m must have cleared (final_phase_inputs exactness).
constexpr bool fx_same_except_holds(const GateInputs &m, const GateInputs &g) {
  return m.boot_loaded == g.boot_loaded && m.fbs_slot == g.fbs_slot && m.probe_latch == g.probe_latch &&
         m.free_power_write_enable == g.free_power_write_enable && m.dump_write_enable == g.dump_write_enable &&
         m.manual_config_write_enable == g.manual_config_write_enable && !m.bus.manual_write_in_progress &&
         m.bus.correction_in_progress == g.bus.correction_in_progress && m.bus.verification_pending == g.bus.verification_pending &&
         m.bus.verification_read_active == g.bus.verification_read_active &&
         m.bus.free_power_operation_in_progress == g.bus.free_power_operation_in_progress &&
         m.bus.free_power_recovery_force_in_progress == g.bus.free_power_recovery_force_in_progress &&
         m.bus.free_power_recovery_accept_in_progress == g.bus.free_power_recovery_accept_in_progress &&
         m.bus.reg244_apply_in_progress == g.bus.reg244_apply_in_progress &&
         m.bus.dump_operation_in_progress == g.bus.dump_operation_in_progress && !m.bus.fallback_profile_op_in_progress &&
         !m.bus.fallback_profile_capture_dispatch_running && m.bus.diag_write_lock_held == g.bus.diag_write_lock_held &&
         m.bus.diag_write_lock_since_ms == g.bus.diag_write_lock_since_ms && m.bus.now_ms == g.bus.now_ms &&
         m.fp.free_power_marker_boot_load == g.fp.free_power_marker_boot_load &&
         m.fp.free_power_recovery_metadata_corrupt == g.fp.free_power_recovery_metadata_corrupt &&
         m.fp.free_power_snapshot_valid == g.fp.free_power_snapshot_valid && m.fp.free_power_marker_state == g.fp.free_power_marker_state &&
         m.fp.free_power_operator_needed == g.fp.free_power_operator_needed &&
         m.fp.free_power_active_persisted == g.fp.free_power_active_persisted &&
         m.fp.free_power_restore_requested == g.fp.free_power_restore_requested && m.fp.expired == g.fp.expired &&
         m.fp.run_start == g.fp.run_start && m.fp.run_restore == g.fp.run_restore && m.fp.run_operator == g.fp.run_operator &&
         m.dump.dump_marker_boot_load == g.dump.dump_marker_boot_load &&
         m.dump.dump_recovery_metadata_corrupt == g.dump.dump_recovery_metadata_corrupt &&
         m.dump.dump_containment_state == g.dump.dump_containment_state && m.dump.dump_snapshot_valid == g.dump.dump_snapshot_valid &&
         m.dump.dump_marker_state == g.dump.dump_marker_state && m.dump.dump_operator_needed == g.dump.dump_operator_needed &&
         m.dump.dump_active_persisted == g.dump.dump_active_persisted &&
         m.dump.dump_restore_requested == g.dump.dump_restore_requested && m.dump.expired == g.dump.expired &&
         m.dump.run_start == g.dump.run_start && m.dump.run_restore == g.dump.run_restore &&
         m.r244.reg244_marker_boot_load == g.r244.reg244_marker_boot_load &&
         m.r244.reg244_recovery_metadata_corrupt == g.r244.reg244_recovery_metadata_corrupt &&
         m.r244.reg244_snapshot_valid == g.r244.reg244_snapshot_valid && m.r244.reg244_marker_state == g.r244.reg244_marker_state &&
         m.r244.run_apply == g.r244.run_apply && m.r244.run_restore == g.r244.run_restore;
}

// ---- string fixtures: the action, target id and confirmation of the gate golden cases ----
// tok: 0 SAVE 1 INVALIDATE 2 RESTORE 3 ACKNOWLEDGE 4 CAPTURE 5 "" 6 save 7 "SAVE " 8 ACCEPT_LIVE 9 PROVISION 10 APPLY 11 RETRY_APPLY
//      12 "SAVE" NUL "x" 13 "INVALIDATE " 14 invalidate 15 "INVALIDATE" NUL "x"
constexpr TextBuf fx_action(uint8_t tok) {
  TextBuf t;
  switch (tok) {
    case 0: put(t, "SAVE"); break;
    case 1: put(t, "INVALIDATE"); break;
    case 2: put(t, "RESTORE"); break;
    case 3: put(t, "ACKNOWLEDGE"); break;
    case 4: put(t, "CAPTURE"); break;
    case 5: break;
    case 6: put(t, "save"); break;
    case 7: put(t, "SAVE "); break;
    case 8: put(t, "ACCEPT_LIVE"); break;
    case 9: put(t, "PROVISION"); break;
    case 10: put(t, "APPLY"); break;
    case 11: put(t, "RETRY_APPLY"); break;
    case 12: put(t, "SAVE"); put_char(t, '\0'); put_char(t, 'x'); break;
    case 13: put(t, "INVALIDATE "); break;
    case 14: put(t, "invalidate"); break;
    default: put(t, "INVALIDATE"); put_char(t, '\0'); put_char(t, 'x'); break;
  }
  return t;
}
constexpr void fx_put_hex_lower(TextBuf &t, uint64_t id) {
  TextBuf h;
  put_hex(h, id, 16);
  for (size_t i = 0; i < h.size(); i++)
    put_char(t, (h.buf[i] >= 'A' && h.buf[i] <= 'F') ? (char) (h.buf[i] + 32) : h.buf[i]);
}
// tgt: 0 hex(id) 1 lower-case hex 2 15 digits 3 17 digits 4 hex(id ^ 1) 5 "" 6 hex + newline 7 space + hex 8 non-hex first character
//      9 "0x" + 14 digits 10 an embedded NUL 11 hex(id ^ 2^63) (differs only in the HIGH 32 bits) 12 hex(id ^ 2^32) 13 hex(id ^ 0xFFFFFFFF00000000)
//      14 hex(id ^ 0xFFFFFFFF) (differs only in the LOW 32 bits)
constexpr TextBuf fx_target(uint8_t kind, uint64_t id) {
  TextBuf t;
  TextBuf h;
  put_hex(h, id, 16);
  switch (kind) {
    case 0: put(t, h.c_str()); break;
    case 1: fx_put_hex_lower(t, id); break;
    case 2: for (size_t i = 0; i + 1 < h.size(); i++) put_char(t, h.buf[i]); break;
    case 3: put(t, h.c_str()); put_char(t, '0'); break;
    case 4: put_hex(t, id ^ 1u, 16); break;
    case 5: break;
    case 6: put(t, h.c_str()); put_char(t, '\n'); break;
    case 7: put_char(t, ' '); put(t, h.c_str()); break;
    case 8: put_char(t, 'G'); for (size_t i = 1; i < h.size(); i++) put_char(t, h.buf[i]); break;
    case 9: put(t, "0x"); for (size_t i = 2; i < h.size(); i++) put_char(t, h.buf[i]); break;
    case 11: put_hex(t, id ^ 0x8000000000000000ULL, 16); break;
    case 12: put_hex(t, id ^ 0x100000000ULL, 16); break;
    case 13: put_hex(t, id ^ 0xFFFFFFFF00000000ULL, 16); break;
    case 14: put_hex(t, id ^ 0xFFFFFFFFULL, 16); break;
    default: for (size_t i = 0; i < h.size(); i++) put_char(t, i == 8 ? '\0' : h.buf[i]); break;
  }
  return t;
}
// cnf: 0 "SAVE id" 1 "SAVE id REPLACE CORRUPT" 2 "INVALIDATE id" 3 "SAVE id\n" 4 "SAVE id " 5 lower-case id 6 "SAVE  id" 7 "" 8 "SAVE "
//      9 "SAVE id REPLACE CORRUPT " 10 "INVALIDATE id REPLACE CORRUPT" 11 "save id" 12 "SAVE id REPLACE  CORRUPT" 13 "SAVE id replace corrupt"
//      14 "SAVE id^1" 15 "SAVE id REPLACE" 16 15 digits 17 17 digits 18 "INVALIDATE id\n" 19 "INVALIDATE" lower-case id 20 "INVALIDATE id^1"
//      21 "SAVE id" NUL "x" 22 "SAVE id" NUL 23 "INVALIDATE id" NUL 24 "INVALIDATE " + hex(id ^ 2^63) 25 ... hex(id ^ 2^32) 26 ... hex(id ^ 0xFFFFFFFF00000000)
//      27 ... hex(id ^ 0xFFFFFFFF)
constexpr TextBuf fx_conf(uint8_t kind, uint64_t id) {
  TextBuf t;
  TextBuf h;
  put_hex(h, id, 16);
  switch (kind) {
    case 0: put(t, "SAVE "); put(t, h.c_str()); break;
    case 1: put(t, "SAVE "); put(t, h.c_str()); put(t, " REPLACE CORRUPT"); break;
    case 2: put(t, "INVALIDATE "); put(t, h.c_str()); break;
    case 3: put(t, "SAVE "); put(t, h.c_str()); put_char(t, '\n'); break;
    case 4: put(t, "SAVE "); put(t, h.c_str()); put_char(t, ' '); break;
    case 5: put(t, "SAVE "); fx_put_hex_lower(t, id); break;
    case 6: put(t, "SAVE  "); put(t, h.c_str()); break;
    case 7: break;
    case 8: put(t, "SAVE "); break;
    case 9: put(t, "SAVE "); put(t, h.c_str()); put(t, " REPLACE CORRUPT "); break;
    case 10: put(t, "INVALIDATE "); put(t, h.c_str()); put(t, " REPLACE CORRUPT"); break;
    case 11: put(t, "save "); put(t, h.c_str()); break;
    case 12: put(t, "SAVE "); put(t, h.c_str()); put(t, " REPLACE  CORRUPT"); break;
    case 13: put(t, "SAVE "); put(t, h.c_str()); put(t, " replace corrupt"); break;
    case 14: put(t, "SAVE "); put_hex(t, id ^ 1u, 16); break;
    case 15: put(t, "SAVE "); put(t, h.c_str()); put(t, " REPLACE"); break;
    case 16: put(t, "SAVE "); for (size_t i = 0; i + 1 < h.size(); i++) put_char(t, h.buf[i]); break;
    case 17: put(t, "SAVE "); put(t, h.c_str()); put_char(t, '0'); break;
    case 18: put(t, "INVALIDATE "); put(t, h.c_str()); put_char(t, '\n'); break;
    case 19: put(t, "INVALIDATE "); fx_put_hex_lower(t, id); break;
    case 20: put(t, "INVALIDATE "); put_hex(t, id ^ 1u, 16); break;
    case 21: put(t, "SAVE "); put(t, h.c_str()); put_char(t, '\0'); put_char(t, 'x'); break;
    case 22: put(t, "SAVE "); put(t, h.c_str()); put_char(t, '\0'); break;
    case 24: put(t, "INVALIDATE "); put_hex(t, id ^ 0x8000000000000000ULL, 16); break;
    case 25: put(t, "INVALIDATE "); put_hex(t, id ^ 0x100000000ULL, 16); break;
    case 26: put(t, "INVALIDATE "); put_hex(t, id ^ 0xFFFFFFFF00000000ULL, 16); break;
    case 27: put(t, "INVALIDATE "); put_hex(t, id ^ 0xFFFFFFFFULL, 16); break;
    default: put(t, "INVALIDATE "); put(t, h.c_str()); put_char(t, '\0'); break;
  }
  return t;
}

// ---- gate fixtures ----
// fx_gate scenarios: 0 all clear (nothing probed yet), 1 operation flag, 2 capture dispatch running, 3 boot not loaded, 4 Free Power arm,
// 5 Dump arm, 6 Manual arm, 7 manual write mutex, 8 clock correction, 9 stuck write lock (301 s), 10 FBS episode, 11 FBS corrupt, 12 FBS unreadable,
// 13 Free Power lease active, 14 Dump operator needed, 15 R244 pending clear, 16 Free Power latched, 17 arm + busy bus, 18 busy bus + FBS episode,
// 19 Free Power and Dump leases, 20 verification pending, 21 R244 apply, 22 Free Power operation flag, 23 FBS valid CLEAR, 24 Dump operation flag,
// 25 Free Power force restore, 26 write lock held ALONE + ACTIVE Free Power lease, 27 write lock held ALONE + ACTIVE Dump to Grid lease
constexpr GateInputs fx_gate(uint8_t k) {
  GateInputs g = ecco_fbcap::golden_gate_clear();
  switch (k) {
    case 1: g.bus.fallback_profile_op_in_progress = true; break;
    case 2: g.bus.fallback_profile_capture_dispatch_running = true; break;
    case 3: g.boot_loaded = false; break;
    case 4: g.free_power_write_enable = true; break;
    case 5: g.dump_write_enable = true; break;
    case 6: g.manual_config_write_enable = true; break;
    case 7: g.bus.manual_write_in_progress = true; break;
    case 8: g.bus.correction_in_progress = true; break;
    case 9:
      g.bus.manual_write_in_progress = true;
      g.bus.diag_write_lock_held = true;
      g.bus.diag_write_lock_since_ms = 1000u;
      g.bus.now_ms = 302000u;
      break;
    case 10: g.fbs_slot = ecco_fbdurable::FBS_OBLIGATION; break;
    case 11: g.fbs_slot = ecco_fbdurable::FBS_CORRUPT; break;
    case 12: g.fbs_slot = ecco_fbdurable::FBS_UNREADABLE; break;
    case 13:
      g.fp.free_power_marker_boot_load = 0;
      g.fp.free_power_snapshot_valid = true;
      g.fp.free_power_marker_state = 1;
      g.fp.free_power_active_persisted = true;
      break;
    case 14:
      g.dump.dump_marker_boot_load = 0;
      g.dump.dump_snapshot_valid = true;
      g.dump.dump_marker_state = 1;
      g.dump.dump_operator_needed = true;
      break;
    case 15:
      g.r244.reg244_snapshot_valid = true;
      g.r244.reg244_marker_state = 2;
      break;
    case 16: g.probe_latch = 0x0001; break;
    case 17:
      g.free_power_write_enable = true;
      g.bus.manual_write_in_progress = true;
      break;
    case 18:
      g.bus.manual_write_in_progress = true;
      g.fbs_slot = ecco_fbdurable::FBS_OBLIGATION;
      break;
    case 19:
      g.fp.free_power_marker_state = 1;
      g.dump.dump_marker_state = 1;
      break;
    case 20: g.bus.verification_pending = true; break;
    case 21: g.bus.reg244_apply_in_progress = true; break;
    case 22: g.bus.free_power_operation_in_progress = true; break;
    case 23: g.fbs_slot = ecco_fbdurable::FBS_CLEAR_VALID; break;
    case 24: g.bus.dump_operation_in_progress = true; break;
    case 25: g.bus.free_power_recovery_force_in_progress = true; break;
    case 26:
      g.bus.manual_write_in_progress = true;
      g.fp.free_power_marker_boot_load = 0;
      g.fp.free_power_snapshot_valid = true;
      g.fp.free_power_marker_state = 1;
      g.fp.free_power_active_persisted = true;
      break;
    case 27:
      g.bus.manual_write_in_progress = true;
      g.dump.dump_marker_boot_load = 0;
      g.dump.dump_snapshot_valid = true;
      g.dump.dump_marker_state = 1;
      g.dump.dump_active_persisted = true;
      break;
    default: break;
  }
  return g;
}
// fx_bus scenarios (BusInputs): 0 idle, 1 operation flag, 2 capture dispatch, 3 manual write mutex, 4 clock correction, 5 verification pending,
// 6 verification read active, 7 Free Power operation, 8 Free Power force restore, 9 Free Power accept, 10 R244 apply, 11 Dump operation
constexpr BusInputs fx_bus(uint8_t k) {
  BusInputs b{};
  switch (k) {
    case 1: b.fallback_profile_op_in_progress = true; break;
    case 2: b.fallback_profile_capture_dispatch_running = true; break;
    case 3: b.manual_write_in_progress = true; break;
    case 4: b.correction_in_progress = true; break;
    case 5: b.verification_pending = true; break;
    case 6: b.verification_read_active = true; break;
    case 7: b.free_power_operation_in_progress = true; break;
    case 8: b.free_power_recovery_force_in_progress = true; break;
    case 9: b.free_power_recovery_accept_in_progress = true; break;
    case 10: b.reg244_apply_in_progress = true; break;
    case 11: b.dump_operation_in_progress = true; break;
    default: break;
  }
  return b;
}
// The SAVE gate inputs of a golden-case row. cand: 0 saveable + id, 1 none, 2 valid not saveable id 0, 3 saveable id 0, 4 not valid but saveable,
// 5 valid + id, not saveable. age: 0 -> 0 ms, 1 -> 119999, 2 -> 120000, 3 -> 120001 since the (wrapping) birth. wfp (the writes fingerprint at
// Review / now): 0 equal (1000), 1 now 1001, 2 now 999 (BELOW), 3 reviewed 0xFFFFFFFF / now 0 (wrap up), 4 reviewed 0 / now 0xFFFFFFFF (wrap down),
// 5 both 0xFFFFFFFF (equal), 6 reviewed 0x80000000 / now 0x7FFFFFFF (below across the signed boundary), 7 reviewed 0x7FFFFFFF / now 0x80000000, 8 both 0,
// 9 reviewed 0 / now 0x10000 (differ only in bit 16), 10 reviewed 0x12340000 / now 0x56780000 (differ only in the high 16 bits).
constexpr SaveGateInputs fx_sg(uint8_t cand, uint8_t age, uint8_t cls, uint8_t boot, uint8_t unc, uint8_t anom, uint8_t hb, uint8_t time,
                               uint8_t arm, uint8_t wfp) {
  SaveGateInputs si{};
  si.arm_was_on = arm != 0;
  si.cand_valid = cand == 0 || cand == 2 || cand == 3 || cand == 5;
  si.cand_saveable = cand == 0 || cand == 3 || cand == 4;
  si.cand_id = (cand == 0 || cand == 4 || cand == 5) ? FX_ID : 0ULL;
  si.cand_ms = FX_BORN_MS;
  si.cand_prior_class = cls;
  si.cand_writes_fp = 1000u;
  const uint32_t ages[4] = {0u, 119999u, 120000u, 120001u};
  si.now_ms = FX_BORN_MS + ages[age & 3u];
  si.writes_fp_now = 1000u;
  switch (wfp) {
    case 1: si.writes_fp_now = 1001u; break;
    case 2: si.writes_fp_now = 999u; break;
    case 3: si.cand_writes_fp = 0xFFFFFFFFu; si.writes_fp_now = 0u; break;
    case 4: si.cand_writes_fp = 0u; si.writes_fp_now = 0xFFFFFFFFu; break;
    case 5: si.cand_writes_fp = 0xFFFFFFFFu; si.writes_fp_now = 0xFFFFFFFFu; break;
    case 6: si.cand_writes_fp = 0x80000000u; si.writes_fp_now = 0x7FFFFFFFu; break;
    case 7: si.cand_writes_fp = 0x7FFFFFFFu; si.writes_fp_now = 0x80000000u; break;
    case 8: si.cand_writes_fp = 0u; si.writes_fp_now = 0u; break;
    case 9: si.cand_writes_fp = 0u; si.writes_fp_now = 0x10000u; break;
    case 10: si.cand_writes_fp = 0x12340000u; si.writes_fp_now = 0x56780000u; break;
    default: break;
  }
  si.boot_loaded = boot != 0;
  si.unconfirmed = unc != 0;
  si.read_anomaly = anom;
  si.hb_ok = hb != 0;
  si.time_trusted = time != 0;
  return si;
}
// SG columns: tok action (0 SAVE 1 INVALIDATE 2 RESTORE 3 ACKNOWLEDGE 4 CAPTURE 5 empty 6 save 7 'SAVE ' 8 ACCEPT_LIVE 9 PROVISION 10 APPLY 11 RETRY_APPLY
//   12 'SAVE' + NUL + x (length 6) 13 'INVALIDATE ' 14 invalidate 15 'INVALIDATE' + NUL + x (length 12)) |
//   arm arm_was_on | cand (0 saveable+id 1 none 2 valid not saveable id 0 3 saveable id 0 4 not valid but saveable 5 valid, id, not saveable) |
//   age ms since Review (0 -> 0, 1 -> 119999, 2 -> 120000, 3 -> 120001; born 4294960000, wraps) | tgt target id kind | cnf confirmation kind |
//   cls cand_prior_class | boot boot_loaded | unc unconfirmed | anom read_anomaly | hb hb_ok | time time_trusted |
//   wfp writes fingerprint kind (0 equal, 1 now = +1, 2 now = -1, 3 / 4 wrap up / down, 5 equal at the maximum, 6 / 7 across the signed boundary, 8 equal at 0,
//   9 / 10 differ only in the high 16 bits) |
//   gate capture-gate scenario (fx_gate) | EXPECT SaveGateCode
struct SgRow {
  uint8_t tok, arm, cand, age, tgt, cnf, cls, boot, unc, anom, hb, time, wfp, gate, expect;
};
// clang-format off
constexpr SgRow SG_CASES[] = {
    {0, 1, 0, 0, 0, 0, 5, 1, 0, 0, 1, 1, 0, 0, SG_ACCEPT},  // all pass: plain SAVE over a VALID prior
    {0, 1, 0, 0, 0, 1, 2, 1, 0, 0, 1, 1, 0, 0, SG_ACCEPT},  // all pass: REPLACE CORRUPT phrase for a CORRUPT prior
    {0, 1, 0, 0, 0, 0, 1, 1, 0, 0, 1, 1, 0, 0, SG_ACCEPT},  // all pass: plain phrase for a NOT_CAPTURED prior
    {0, 1, 0, 0, 0, 0, 3, 1, 0, 0, 1, 1, 0, 0, SG_ACCEPT},  // all pass: plain phrase for a CORRUPT_DOMAIN prior
    {0, 1, 0, 0, 0, 0, 4, 1, 0, 0, 1, 1, 0, 0, SG_ACCEPT},  // all pass: plain phrase for a INVALIDATED prior
    {0, 1, 0, 0, 0, 0, 6, 1, 0, 0, 1, 1, 0, 0, SG_ACCEPT},  // all pass: plain phrase for a PROFILE_LOST prior
    {0, 1, 0, 0, 0, 0, 8, 1, 0, 0, 1, 1, 0, 0, SG_ACCEPT},  // all pass: plain phrase for a PROFILE_STALE prior
    {0, 1, 0, 1, 0, 0, 5, 1, 0, 0, 1, 1, 0, 0, SG_ACCEPT},  // all pass: the candidate is 119999 ms old (one ms before the TTL)
    {0, 1, 0, 0, 0, 0, 5, 1, 0, 0, 1, 1, 0, 0, SG_ACCEPT},  // all pass: a NEEDS-PROBE capture gate counts as clear (nothing probed in the gate)
    {0, 1, 0, 0, 0, 0, 5, 1, 0, 0, 1, 1, 0, 23, SG_ACCEPT},  // all pass: FBS CLEAR (valid record) is clear
    {0, 1, 0, 0, 0, 0, 5, 1, 0, 0, 1, 1, 0, 1, SG_IN_FLIGHT},  // G1 an operation flag is set
    {0, 1, 0, 0, 0, 0, 5, 1, 0, 0, 1, 1, 0, 2, SG_IN_FLIGHT},  // G1 the capture dispatch is running
    {1, 1, 0, 0, 0, 0, 5, 1, 0, 0, 1, 1, 0, 1, SG_IN_FLIGHT},  // G1 outranks an unsupported token
    {0, 0, 0, 0, 0, 0, 5, 1, 0, 0, 1, 1, 0, 2, SG_IN_FLIGHT},  // G1 outranks the arm (arm off AND in flight)
    {4, 0, 1, 3, 5, 7, 5, 0, 1, 4, 0, 0, 1, 1, SG_IN_FLIGHT},  // G1 outranks everything else wrong
    {1, 1, 0, 0, 0, 0, 5, 1, 0, 0, 1, 1, 0, 0, SG_UNSUPPORTED},  // G0 token INVALIDATE
    {2, 1, 0, 0, 0, 0, 5, 1, 0, 0, 1, 1, 0, 0, SG_UNSUPPORTED},  // G0 token RESTORE (reserved)
    {3, 1, 0, 0, 0, 0, 5, 1, 0, 0, 1, 1, 0, 0, SG_UNSUPPORTED},  // G0 token ACKNOWLEDGE (reserved)
    {4, 1, 0, 0, 0, 0, 5, 1, 0, 0, 1, 1, 0, 0, SG_UNSUPPORTED},  // G0 token CAPTURE (retired)
    {5, 1, 0, 0, 0, 0, 5, 1, 0, 0, 1, 1, 0, 0, SG_UNSUPPORTED},  // G0 token an empty action
    {6, 1, 0, 0, 0, 0, 5, 1, 0, 0, 1, 1, 0, 0, SG_UNSUPPORTED},  // G0 token a lower-case save
    {7, 1, 0, 0, 0, 0, 5, 1, 0, 0, 1, 1, 0, 0, SG_UNSUPPORTED},  // G0 token a padded 'SAVE '
    {8, 1, 0, 0, 0, 0, 5, 1, 0, 0, 1, 1, 0, 0, SG_UNSUPPORTED},  // G0 token ACCEPT_LIVE (retired)
    {9, 1, 0, 0, 0, 0, 5, 1, 0, 0, 1, 1, 0, 0, SG_UNSUPPORTED},  // G0 token PROVISION (retired)
    {10, 1, 0, 0, 0, 0, 5, 1, 0, 0, 1, 1, 0, 0, SG_UNSUPPORTED},  // G0 token APPLY (retired)
    {11, 1, 0, 0, 0, 0, 5, 1, 0, 0, 1, 1, 0, 0, SG_UNSUPPORTED},  // G0 token RETRY_APPLY (retired)
    {12, 1, 0, 0, 0, 0, 5, 1, 0, 0, 1, 1, 0, 0, SG_UNSUPPORTED},  // G0 token an action with an embedded NUL
    {14, 1, 0, 0, 0, 0, 5, 1, 0, 0, 1, 1, 0, 0, SG_UNSUPPORTED},  // G0 token a lower-case invalidate
    {13, 1, 0, 0, 0, 0, 5, 1, 0, 0, 1, 1, 0, 0, SG_UNSUPPORTED},  // G0 token a padded 'INVALIDATE '
    {15, 1, 0, 0, 0, 0, 5, 1, 0, 0, 1, 1, 0, 0, SG_UNSUPPORTED},  // G0 token INVALIDATE with an embedded NUL
    {1, 0, 0, 0, 0, 0, 5, 1, 0, 0, 1, 1, 0, 0, SG_UNSUPPORTED},  // G0 outranks the arm
    {0, 0, 0, 0, 0, 0, 5, 1, 0, 0, 1, 1, 0, 0, SG_ARM_OFF},  // G2 the arm was off
    {0, 0, 1, 0, 0, 0, 5, 1, 0, 0, 1, 1, 0, 0, SG_ARM_OFF},  // G2 outranks a missing candidate
    {0, 1, 1, 0, 0, 0, 5, 1, 0, 0, 1, 1, 0, 0, SG_NO_CANDIDATE},  // G3 no candidate
    {0, 1, 2, 0, 0, 0, 5, 1, 0, 0, 1, 1, 0, 0, SG_NO_CANDIDATE},  // G3 a NOT SAVEABLE preview (valid, not saveable, id 0)
    {0, 1, 3, 0, 0, 0, 5, 1, 0, 0, 1, 1, 0, 0, SG_NO_CANDIDATE},  // G3 saveable with id 0: SAVE 0000000000000000 must never pass
    {0, 1, 4, 0, 0, 0, 5, 1, 0, 0, 1, 1, 0, 0, SG_NO_CANDIDATE},  // G3 not valid but saveable
    {0, 1, 5, 0, 0, 0, 5, 1, 0, 0, 1, 1, 0, 0, SG_NO_CANDIDATE},  // G3 valid, id set, but not saveable
    {0, 1, 3, 0, 0, 0, 5, 1, 0, 0, 1, 1, 0, 0, SG_NO_CANDIDATE},  // G3 id-0 trap with the matching target AND phrase still refuses
    {0, 1, 1, 2, 0, 0, 5, 1, 0, 0, 1, 1, 0, 0, SG_NO_CANDIDATE},  // G3 outranks an expired candidate
    {0, 1, 0, 2, 0, 0, 5, 1, 0, 0, 1, 1, 0, 0, SG_EXPIRED},  // G4 expired exactly at 120000 ms
    {0, 1, 0, 3, 0, 0, 5, 1, 0, 0, 1, 1, 0, 0, SG_EXPIRED},  // G4 expired at 120001 ms
    {0, 1, 0, 2, 2, 0, 5, 1, 0, 0, 1, 1, 0, 0, SG_EXPIRED},  // G4 outranks a malformed target id
    {0, 1, 0, 0, 1, 0, 5, 1, 0, 0, 1, 1, 0, 0, SG_ID_FORMAT},  // G5 target id: lower-case hex
    {0, 1, 0, 0, 2, 0, 5, 1, 0, 0, 1, 1, 0, 0, SG_ID_FORMAT},  // G5 target id: 15 hex digits
    {0, 1, 0, 0, 3, 0, 5, 1, 0, 0, 1, 1, 0, 0, SG_ID_FORMAT},  // G5 target id: 17 hex digits
    {0, 1, 0, 0, 5, 0, 5, 1, 0, 0, 1, 1, 0, 0, SG_ID_FORMAT},  // G5 target id: an empty id
    {0, 1, 0, 0, 6, 0, 5, 1, 0, 0, 1, 1, 0, 0, SG_ID_FORMAT},  // G5 target id: a trailing newline
    {0, 1, 0, 0, 7, 0, 5, 1, 0, 0, 1, 1, 0, 0, SG_ID_FORMAT},  // G5 target id: a leading space
    {0, 1, 0, 0, 8, 0, 5, 1, 0, 0, 1, 1, 0, 0, SG_ID_FORMAT},  // G5 target id: a non-hex character
    {0, 1, 0, 0, 9, 0, 5, 1, 0, 0, 1, 1, 0, 0, SG_ID_FORMAT},  // G5 target id: a 0x prefix
    {0, 1, 0, 0, 10, 0, 5, 1, 0, 0, 1, 1, 0, 0, SG_ID_FORMAT},  // G5 target id: an embedded NUL
    {0, 1, 0, 0, 2, 7, 5, 1, 0, 0, 1, 1, 0, 0, SG_ID_FORMAT},  // G5 outranks a malformed phrase
    {0, 1, 0, 0, 4, 0, 5, 1, 0, 0, 1, 1, 0, 0, SG_ID_MISMATCH},  // G6 a well-formed id that is not the candidate's
    {0, 1, 0, 0, 4, 7, 5, 1, 0, 0, 1, 1, 0, 0, SG_ID_MISMATCH},  // G6 outranks the phrase
    {0, 1, 0, 0, 11, 0, 5, 1, 0, 0, 1, 1, 0, 0, SG_ID_MISMATCH},  // G6 an id that differs only in the HIGH 32 bits (bit 63): a 32-bit compare would pass it
    {0, 1, 0, 0, 12, 0, 5, 1, 0, 0, 1, 1, 0, 0, SG_ID_MISMATCH},  // G6 differs only in bit 32 (the lowest bit of the high word)
    {0, 1, 0, 0, 13, 0, 5, 1, 0, 0, 1, 1, 0, 0, SG_ID_MISMATCH},  // G6 differs in every bit of the high word and in no bit of the low word
    {0, 1, 0, 0, 14, 0, 5, 1, 0, 0, 1, 1, 0, 0, SG_ID_MISMATCH},  // G6 differs in every bit of the low word and in no bit of the high word
    {0, 1, 0, 0, 11, 7, 5, 1, 0, 0, 1, 1, 0, 0, SG_ID_MISMATCH},  // G6 (high word) outranks the phrase: a 32-bit compare would fall through to G7
    {0, 1, 0, 0, 12, 7, 5, 1, 0, 0, 1, 1, 0, 0, SG_ID_MISMATCH},  // G6 (bit 32) outranks the phrase
    {0, 1, 0, 0, 0, 1, 5, 1, 0, 0, 1, 1, 0, 0, SG_PHRASE},  // G7 REPLACE CORRUPT offered for a VALID prior
    {0, 1, 0, 0, 0, 0, 2, 1, 0, 0, 1, 1, 0, 0, SG_PHRASE},  // G7 plain phrase for a CORRUPT prior (REPLACE CORRUPT required)
    {0, 1, 0, 0, 0, 2, 5, 1, 0, 0, 1, 1, 0, 0, SG_PHRASE},  // G7 the INVALIDATE phrase
    {0, 1, 0, 0, 0, 3, 5, 1, 0, 0, 1, 1, 0, 0, SG_PHRASE},  // G7 phrase: a trailing newline
    {0, 1, 0, 0, 0, 4, 5, 1, 0, 0, 1, 1, 0, 0, SG_PHRASE},  // G7 phrase: a trailing space
    {0, 1, 0, 0, 0, 5, 5, 1, 0, 0, 1, 1, 0, 0, SG_PHRASE},  // G7 phrase: lower-case hex
    {0, 1, 0, 0, 0, 6, 5, 1, 0, 0, 1, 1, 0, 0, SG_PHRASE},  // G7 phrase: a double space
    {0, 1, 0, 0, 0, 7, 5, 1, 0, 0, 1, 1, 0, 0, SG_PHRASE},  // G7 phrase: an empty phrase
    {0, 1, 0, 0, 0, 8, 5, 1, 0, 0, 1, 1, 0, 0, SG_PHRASE},  // G7 phrase: a missing id
    {0, 1, 0, 0, 0, 14, 5, 1, 0, 0, 1, 1, 0, 0, SG_PHRASE},  // G7 phrase: another candidate's id
    {0, 1, 0, 0, 0, 16, 5, 1, 0, 0, 1, 1, 0, 0, SG_PHRASE},  // G7 phrase: 15 hex digits
    {0, 1, 0, 0, 0, 17, 5, 1, 0, 0, 1, 1, 0, 0, SG_PHRASE},  // G7 phrase: 17 hex digits
    {0, 1, 0, 0, 0, 11, 5, 1, 0, 0, 1, 1, 0, 0, SG_PHRASE},  // G7 phrase: a lower-case verb
    {0, 1, 0, 0, 0, 21, 5, 1, 0, 0, 1, 1, 0, 0, SG_PHRASE},  // G7 phrase: an embedded NUL after the id
    {0, 1, 0, 0, 0, 9, 2, 1, 0, 0, 1, 1, 0, 0, SG_PHRASE},  // G7 phrase for a CORRUPT prior: a trailing space after REPLACE CORRUPT
    {0, 1, 0, 0, 0, 12, 2, 1, 0, 0, 1, 1, 0, 0, SG_PHRASE},  // G7 phrase for a CORRUPT prior: a double space inside REPLACE CORRUPT
    {0, 1, 0, 0, 0, 13, 2, 1, 0, 0, 1, 1, 0, 0, SG_PHRASE},  // G7 phrase for a CORRUPT prior: lower-case replace corrupt
    {0, 1, 0, 0, 0, 15, 2, 1, 0, 0, 1, 1, 0, 0, SG_PHRASE},  // G7 phrase for a CORRUPT prior: REPLACE without CORRUPT
    {0, 1, 0, 0, 0, 10, 2, 1, 0, 0, 1, 1, 0, 0, SG_PHRASE},  // G7 INVALIDATE <id> REPLACE CORRUPT is never valid
    {0, 1, 0, 0, 0, 22, 5, 1, 0, 0, 1, 1, 0, 0, SG_PHRASE},  // G7 phrase: a trailing NUL after the id (explicit length)
    {0, 1, 0, 0, 0, 7, 5, 0, 0, 0, 1, 1, 0, 0, SG_PHRASE},  // G7 outranks durable state not loaded
    {0, 1, 0, 0, 0, 0, 5, 0, 0, 0, 1, 1, 0, 0, SG_NOT_LOADED},  // G8 durable state not loaded
    {0, 1, 0, 0, 0, 0, 5, 0, 1, 0, 1, 1, 0, 0, SG_NOT_LOADED},  // G8 outranks an unconfirmed outcome
    {0, 1, 0, 0, 0, 0, 5, 1, 0, 0, 1, 1, 0, 3, SG_NOT_LOADED},  // G8 the capture gate disagrees: its boot_loaded is false (position of G12)
    {0, 1, 0, 0, 0, 0, 5, 1, 1, 0, 1, 1, 0, 0, SG_UNCONFIRMED},  // G9 a previous write outcome is unknown
    {0, 1, 0, 0, 0, 0, 5, 1, 1, 4, 1, 1, 0, 0, SG_UNCONFIRMED},  // G9 outranks a read anomaly
    {0, 1, 0, 0, 0, 0, 5, 1, 0, 1, 1, 1, 0, 0, SG_ANOMALY},  // G9a read anomaly 1
    {0, 1, 0, 0, 0, 0, 5, 1, 0, 2, 1, 1, 0, 0, SG_ANOMALY},  // G9a read anomaly 2
    {0, 1, 0, 0, 0, 0, 5, 1, 0, 3, 1, 1, 0, 0, SG_ANOMALY},  // G9a read anomaly 3
    {0, 1, 0, 0, 0, 0, 5, 1, 0, 4, 1, 1, 0, 0, SG_ANOMALY},  // G9a read anomaly 4
    {0, 1, 0, 0, 0, 0, 5, 1, 0, 255, 1, 1, 0, 0, SG_ANOMALY},  // G9a read anomaly 255
    {0, 1, 0, 0, 0, 0, 5, 1, 0, 4, 0, 1, 0, 0, SG_ANOMALY},  // G9a outranks the heartbeat
    {0, 1, 0, 0, 0, 0, 5, 1, 0, 0, 0, 1, 0, 0, SG_HB},  // G10 the heartbeat is not stable
    {0, 1, 0, 0, 0, 0, 5, 1, 0, 0, 0, 0, 0, 0, SG_HB},  // G10 outranks the clock
    {0, 1, 0, 0, 0, 0, 5, 1, 0, 0, 1, 0, 0, 0, SG_TIME},  // G11 no trusted time
    {0, 1, 0, 0, 0, 0, 5, 1, 0, 0, 1, 0, 0, 4, SG_TIME},  // G11 outranks a write arm
    {0, 1, 0, 0, 0, 0, 5, 1, 0, 0, 1, 1, 0, 4, SG_ARMS},  // G12 the Free Power write arm is on
    {0, 1, 0, 0, 0, 0, 5, 1, 0, 0, 1, 1, 0, 5, SG_ARMS},  // G12 the Dump to Grid write arm is on
    {0, 1, 0, 0, 0, 0, 5, 1, 0, 0, 1, 1, 0, 6, SG_ARMS},  // G12 the Manual Configuration write arm is on
    {0, 1, 0, 0, 0, 0, 5, 1, 0, 0, 1, 1, 0, 17, SG_ARMS},  // G12 an arm outranks a busy bus
    {0, 1, 0, 0, 0, 0, 5, 1, 0, 0, 1, 1, 1, 4, SG_ARMS},  // G12 outranks the writes fingerprint
    {0, 1, 0, 0, 0, 0, 5, 1, 0, 0, 1, 1, 1, 0, SG_WRITES},  // G13 another ECCO inverter write started since Review
    {0, 1, 0, 0, 0, 0, 5, 1, 0, 0, 1, 1, 1, 7, SG_WRITES},  // G13 outranks a busy bus
    {0, 1, 0, 0, 0, 0, 5, 1, 0, 0, 1, 1, 2, 0, SG_WRITES},  // G13 the fingerprint is BELOW the reviewed one (999 vs 1000): any difference refuses, not only a larger one
    {0, 1, 0, 0, 0, 0, 5, 1, 0, 0, 1, 1, 3, 0, SG_WRITES},  // G13 across the uint32 wrap upwards (reviewed 0xFFFFFFFF, now 0)
    {0, 1, 0, 0, 0, 0, 5, 1, 0, 0, 1, 1, 4, 0, SG_WRITES},  // G13 across the uint32 wrap downwards (reviewed 0, now 0xFFFFFFFF)
    {0, 1, 0, 0, 0, 0, 5, 1, 0, 0, 1, 1, 6, 0, SG_WRITES},  // G13 below across the signed boundary (reviewed 0x80000000, now 0x7FFFFFFF)
    {0, 1, 0, 0, 0, 0, 5, 1, 0, 0, 1, 1, 7, 0, SG_WRITES},  // G13 above across the signed boundary (reviewed 0x7FFFFFFF, now 0x80000000)
    {0, 1, 0, 0, 0, 0, 5, 1, 0, 0, 1, 1, 5, 0, SG_ACCEPT},  // G13 equal at the maximum is clear
    {0, 1, 0, 0, 0, 0, 5, 1, 0, 0, 1, 1, 8, 0, SG_ACCEPT},  // G13 equal at zero is clear
    {0, 1, 0, 0, 0, 0, 5, 1, 0, 0, 1, 1, 9, 0, SG_WRITES},  // G13 the fingerprints differ only in bit 16: a 16-bit compare would pass it
    {0, 1, 0, 0, 0, 0, 5, 1, 0, 0, 1, 1, 10, 0, SG_WRITES},  // G13 the fingerprints differ only in the high 16 bits
    {0, 1, 0, 0, 0, 0, 5, 1, 0, 0, 1, 1, 2, 7, SG_WRITES},  // G13 (below) outranks a busy bus
    {0, 1, 0, 0, 0, 0, 5, 1, 0, 0, 1, 1, 2, 4, SG_ARMS},  // G12 outranks the writes fingerprint (below)
    {0, 1, 0, 0, 0, 0, 5, 1, 0, 0, 1, 1, 0, 7, SG_BUS},  // G14 BUS: the manual write mutex
    {0, 1, 0, 0, 0, 0, 5, 1, 0, 0, 1, 1, 0, 8, SG_BUS},  // G14 BUS: a clock correction
    {0, 1, 0, 0, 0, 0, 5, 1, 0, 0, 1, 1, 0, 9, SG_BUS},  // G14 BUS: a stuck write lock (301 s)
    {0, 1, 0, 0, 0, 0, 5, 1, 0, 0, 1, 1, 0, 20, SG_BUS},  // G14 BUS: a pending clock verification
    {0, 1, 0, 0, 0, 0, 5, 1, 0, 0, 1, 1, 0, 21, SG_BUS},  // G14 BUS: a Register 244 apply
    {0, 1, 0, 0, 0, 0, 5, 1, 0, 0, 1, 1, 0, 22, SG_BUS},  // G14 BUS: a Free Power operation flag
    {0, 1, 0, 0, 0, 0, 5, 1, 0, 0, 1, 1, 0, 24, SG_BUS},  // G14 BUS: a Dump operation flag
    {0, 1, 0, 0, 0, 0, 5, 1, 0, 0, 1, 1, 0, 25, SG_BUS},  // G14 BUS: a Free Power force restore
    {0, 1, 0, 0, 0, 0, 5, 1, 0, 0, 1, 1, 0, 18, SG_BUS},  // G14 the bus outranks an FBS episode
    {0, 1, 0, 0, 0, 0, 5, 1, 0, 0, 1, 1, 0, 26, SG_BUS},  // G14 BUS: the write lock held by an ACTIVE Free Power lease (the text names the lease)
    {0, 1, 0, 0, 0, 0, 5, 1, 0, 0, 1, 1, 0, 27, SG_BUS},  // G14 BUS: the write lock held by an ACTIVE Dump to Grid lease (the text names the lease)
    {0, 1, 0, 0, 0, 0, 5, 1, 0, 0, 1, 1, 0, 10, SG_FBS},  // G15 FBS: an open failback episode
    {0, 1, 0, 0, 0, 0, 5, 1, 0, 0, 1, 1, 0, 11, SG_FBS},  // G15 FBS: a CORRUPT failback record
    {0, 1, 0, 0, 0, 0, 5, 1, 0, 0, 1, 1, 0, 12, SG_FBS},  // G15 FBS: an unreadable failback record
    {0, 1, 0, 0, 0, 0, 5, 1, 0, 0, 1, 1, 0, 13, SG_FP},  // G16 a Free Power lease is active
    {0, 1, 0, 0, 0, 0, 5, 1, 0, 0, 1, 1, 0, 14, SG_DUMP},  // G16 Dump to Grid needs an operator
    {0, 1, 0, 0, 0, 0, 5, 1, 0, 0, 1, 1, 0, 15, SG_R244},  // G16 Register 244 restore verified, clear pending
    {0, 1, 0, 0, 0, 0, 5, 1, 0, 0, 1, 1, 0, 16, SG_FP},  // G16 a latched Free Power marker
    {0, 1, 0, 0, 0, 0, 5, 1, 0, 0, 1, 1, 0, 19, SG_FP},  // G16 Free Power outranks Dump to Grid
    {4, 0, 1, 3, 5, 7, 5, 0, 1, 4, 0, 0, 1, 17, SG_UNSUPPORTED},  // everything wrong except in-flight: the unsupported token comes first
    {0, 0, 1, 3, 5, 7, 5, 0, 1, 4, 0, 0, 1, 17, SG_ARM_OFF},  // everything wrong except in-flight and the token: the arm comes first
    {0, 1, 1, 3, 5, 7, 5, 0, 1, 4, 0, 0, 1, 17, SG_NO_CANDIDATE},  // everything after the candidate wrong: the candidate gate comes first
};
// clang-format on

// IG columns: tok action | arm arm_was_on | tgt target id kind (id = the stored profile's binding) | cnf confirmation kind | boot | anom | unc |
//   cls_o class override (255 = the faithful composed class) | pk stored profile kind | wk witness kind | seen seen_hw_gen |
//   bus bus scenario (fx_bus) | tx 0 queue empty and free, 1 not empty, 2 blocked | fbs FbsSlot | EXPECT InvalidateGateCode
struct IgRow {
  uint8_t tok, arm, tgt, cnf, boot, anom, unc, cls_o, pk, wk;
  uint32_t seen;
  uint8_t bus, tx, fbs, expect;
};
// clang-format off
constexpr IgRow IG_CASES[] = {
    {1, 1, 0, 2, 1, 0, 0, 255, 1, 1, 0, 0, 0, 1, IG_ACCEPT},  // all pass: a VALID profile with a consistent witness
    {1, 1, 0, 2, 1, 0, 0, 255, 1, 2, 0, 0, 0, 1, IG_ACCEPT},  // all pass: a VALID profile with a lagging witness (B8) is invalidatable
    {1, 1, 0, 2, 1, 0, 0, 255, 1, 0, 0, 0, 0, 1, IG_ACCEPT},  // all pass: a VALID profile with a missing witness (B14)
    {1, 1, 0, 2, 1, 0, 0, 255, 1, 3, 0, 0, 0, 1, IG_ACCEPT},  // all pass: a VALID profile with a corrupt witness (B15)
    {1, 1, 0, 2, 1, 0, 0, 255, 1, 4, 0, 0, 0, 1, IG_ACCEPT},  // all pass: a VALID profile with a wrong-size witness (B15)
    {1, 1, 0, 2, 1, 0, 0, 255, 1, 12, 0, 0, 0, 1, IG_ACCEPT},  // all pass: the witness' last op is INVALIDATE
    {1, 1, 0, 2, 1, 0, 0, 255, 1, 1, 0, 0, 0, 2, IG_ACCEPT},  // all pass: FBS CLEAR (valid record)
    {1, 1, 0, 2, 1, 0, 0, 255, 1, 1, 7, 0, 0, 1, IG_ACCEPT},  // all pass: seen high-water exactly g (7): g+1 is ahead
    {1, 1, 0, 2, 1, 0, 0, 255, 1, 1, 0, 0, 0, 1, IG_ACCEPT},  // all pass: no heartbeat, time, arm switches or obligations are inputs of the INVALIDATE gate
    {1, 1, 0, 2, 1, 0, 0, 255, 1, 1, 0, 1, 0, 1, IG_IN_FLIGHT},  // I1 an operation flag is set
    {1, 1, 0, 2, 1, 0, 0, 255, 1, 1, 0, 2, 0, 1, IG_IN_FLIGHT},  // I1 the capture dispatch is running
    {0, 0, 0, 2, 1, 0, 0, 255, 1, 1, 0, 1, 0, 1, IG_IN_FLIGHT},  // I1 outranks the token and the arm
    {0, 1, 0, 2, 1, 0, 0, 255, 1, 1, 0, 0, 0, 1, IG_UNSUPPORTED},  // token SAVE
    {2, 1, 0, 2, 1, 0, 0, 255, 1, 1, 0, 0, 0, 1, IG_UNSUPPORTED},  // token RESTORE
    {3, 1, 0, 2, 1, 0, 0, 255, 1, 1, 0, 0, 0, 1, IG_UNSUPPORTED},  // token ACKNOWLEDGE
    {4, 1, 0, 2, 1, 0, 0, 255, 1, 1, 0, 0, 0, 1, IG_UNSUPPORTED},  // token CAPTURE
    {5, 1, 0, 2, 1, 0, 0, 255, 1, 1, 0, 0, 0, 1, IG_UNSUPPORTED},  // token an empty action
    {14, 1, 0, 2, 1, 0, 0, 255, 1, 1, 0, 0, 0, 1, IG_UNSUPPORTED},  // token a lower-case invalidate
    {13, 1, 0, 2, 1, 0, 0, 255, 1, 1, 0, 0, 0, 1, IG_UNSUPPORTED},  // token a padded 'INVALIDATE '
    {15, 1, 0, 2, 1, 0, 0, 255, 1, 1, 0, 0, 0, 1, IG_UNSUPPORTED},  // token INVALIDATE with an embedded NUL
    {0, 0, 0, 2, 1, 0, 0, 255, 1, 1, 0, 0, 0, 1, IG_UNSUPPORTED},  // token outranks the arm
    {1, 0, 0, 2, 1, 0, 0, 255, 1, 1, 0, 0, 0, 1, IG_ARM_OFF},  // I2 the arm was off
    {1, 1, 1, 2, 1, 0, 0, 255, 1, 1, 0, 0, 0, 1, IG_ID_FORMAT},  // I3 target id: lower-case hex
    {1, 1, 2, 2, 1, 0, 0, 255, 1, 1, 0, 0, 0, 1, IG_ID_FORMAT},  // I3 target id: 15 hex digits
    {1, 1, 3, 2, 1, 0, 0, 255, 1, 1, 0, 0, 0, 1, IG_ID_FORMAT},  // I3 target id: 17 hex digits
    {1, 1, 5, 2, 1, 0, 0, 255, 1, 1, 0, 0, 0, 1, IG_ID_FORMAT},  // I3 target id: an empty id
    {1, 1, 6, 2, 1, 0, 0, 255, 1, 1, 0, 0, 0, 1, IG_ID_FORMAT},  // I3 target id: a trailing newline
    {1, 1, 7, 2, 1, 0, 0, 255, 1, 1, 0, 0, 0, 1, IG_ID_FORMAT},  // I3 target id: a leading space
    {1, 1, 8, 2, 1, 0, 0, 255, 1, 1, 0, 0, 0, 1, IG_ID_FORMAT},  // I3 target id: a non-hex character
    {1, 1, 9, 2, 1, 0, 0, 255, 1, 1, 0, 0, 0, 1, IG_ID_FORMAT},  // I3 target id: a 0x prefix
    {1, 1, 10, 2, 1, 0, 0, 255, 1, 1, 0, 0, 0, 1, IG_ID_FORMAT},  // I3 target id: an embedded NUL
    {1, 1, 2, 7, 1, 0, 0, 255, 1, 1, 0, 0, 0, 1, IG_ID_FORMAT},  // I3 outranks the phrase
    {1, 1, 0, 0, 1, 0, 0, 255, 1, 1, 0, 0, 0, 1, IG_PHRASE},  // I4 the SAVE phrase
    {1, 1, 0, 23, 1, 0, 0, 255, 1, 1, 0, 0, 0, 1, IG_PHRASE},  // I4 phrase: a trailing NUL after the id (explicit length)
    {1, 1, 0, 1, 1, 0, 0, 255, 1, 1, 0, 0, 0, 1, IG_PHRASE},  // I4 the SAVE REPLACE CORRUPT phrase
    {1, 1, 0, 7, 1, 0, 0, 255, 1, 1, 0, 0, 0, 1, IG_PHRASE},  // I4 phrase: an empty phrase
    {1, 1, 0, 18, 1, 0, 0, 255, 1, 1, 0, 0, 0, 1, IG_PHRASE},  // I4 phrase: a trailing newline
    {1, 1, 0, 19, 1, 0, 0, 255, 1, 1, 0, 0, 0, 1, IG_PHRASE},  // I4 phrase: lower-case hex
    {1, 1, 0, 10, 1, 0, 0, 255, 1, 1, 0, 0, 0, 1, IG_PHRASE},  // I4 phrase: INVALIDATE <id> REPLACE CORRUPT
    {1, 1, 0, 20, 1, 0, 0, 255, 1, 1, 0, 0, 0, 1, IG_PHRASE},  // I4 phrase: another id
    {1, 1, 0, 6, 1, 0, 0, 255, 1, 1, 0, 0, 0, 1, IG_PHRASE},  // I4 phrase: SAVE with a double space
    {1, 1, 0, 21, 1, 0, 0, 255, 1, 1, 0, 0, 0, 1, IG_PHRASE},  // I4 phrase: an embedded NUL after the id
    {1, 1, 4, 2, 1, 0, 0, 255, 1, 1, 0, 0, 0, 1, IG_PHRASE},  // I4 the phrase must carry the TARGET id, not the stored profile's
    {1, 1, 0, 7, 0, 0, 0, 255, 1, 1, 0, 0, 0, 1, IG_PHRASE},  // I4 outranks durable state not loaded
    {1, 1, 0, 2, 0, 0, 0, 255, 1, 1, 0, 0, 0, 1, IG_NOT_LOADED},  // I5 durable state not loaded
    {1, 1, 0, 2, 0, 4, 0, 255, 1, 1, 0, 0, 0, 1, IG_NOT_LOADED},  // I5 outranks a read anomaly
    {1, 1, 0, 2, 1, 1, 0, 255, 1, 1, 0, 0, 0, 1, IG_ANOMALY},  // I6 read anomaly 1
    {1, 1, 0, 2, 1, 2, 0, 255, 1, 1, 0, 0, 0, 1, IG_ANOMALY},  // I6 read anomaly 2
    {1, 1, 0, 2, 1, 3, 0, 255, 1, 1, 0, 0, 0, 1, IG_ANOMALY},  // I6 read anomaly 3
    {1, 1, 0, 2, 1, 4, 0, 255, 1, 1, 0, 0, 0, 1, IG_ANOMALY},  // I6 read anomaly 4
    {1, 1, 0, 2, 1, 255, 0, 255, 1, 1, 0, 0, 0, 1, IG_ANOMALY},  // I6 read anomaly 255
    {1, 1, 0, 2, 1, 4, 1, 255, 1, 1, 0, 0, 0, 1, IG_ANOMALY},  // I6 outranks an unconfirmed outcome (read anomaly before unconfirmed)
    {1, 1, 0, 2, 1, 0, 1, 255, 1, 1, 0, 0, 0, 1, IG_UNCONFIRMED},  // I7 a previous write outcome is unknown
    {1, 1, 0, 2, 1, 0, 1, 255, 2, 1, 0, 0, 0, 1, IG_UNCONFIRMED},  // I7 outranks the class
    {1, 1, 0, 2, 1, 0, 0, 255, 2, 1, 0, 0, 0, 1, IG_CLASS},  // I8 the profile is INVALIDATED
    {1, 1, 0, 2, 1, 0, 0, 255, 3, 1, 0, 0, 0, 1, IG_CLASS},  // I8 the profile is CORRUPT_DOMAIN
    {1, 1, 0, 2, 1, 0, 0, 255, 4, 1, 0, 0, 0, 1, IG_CLASS},  // I8 the profile is CORRUPT
    {1, 1, 0, 2, 1, 0, 0, 255, 5, 1, 0, 0, 0, 1, IG_CLASS},  // I8 the profile is CORRUPT (wrong size)
    {1, 1, 0, 2, 1, 0, 0, 255, 6, 1, 0, 0, 0, 1, IG_CLASS},  // I8 the profile is UNREADABLE (read error)
    {1, 1, 0, 2, 1, 0, 0, 255, 7, 1, 0, 0, 0, 1, IG_CLASS},  // I8 the profile is UNREADABLE (storage unavailable)
    {1, 1, 0, 2, 1, 0, 0, 255, 0, 0, 0, 0, 0, 1, IG_CLASS},  // I8 the profile is NOT_CAPTURED (both records absent)
    {1, 1, 0, 2, 1, 0, 0, 255, 0, 1, 0, 0, 0, 1, IG_CLASS},  // I8 the profile is PROFILE_LOST (profile absent, witness valid)
    {1, 1, 0, 2, 1, 0, 0, 255, 1, 8, 0, 0, 0, 1, IG_CLASS},  // I8 the profile is STALE (interrupted)
    {1, 1, 0, 2, 1, 0, 0, 255, 1, 9, 0, 0, 0, 1, IG_CLASS},  // I8 the profile is STALE (rollback)
    {1, 1, 0, 2, 1, 0, 0, 255, 1, 11, 0, 0, 0, 1, IG_CLASS},  // I8 the profile is STALE (superseded)
    {1, 1, 0, 2, 1, 0, 0, 255, 1, 13, 0, 0, 0, 1, IG_CLASS},  // I8 the profile is STALE (mismatch)
    {1, 1, 0, 2, 1, 0, 0, 255, 1, 5, 0, 0, 0, 1, IG_CLASS},  // I8 the profile is UNREADABLE (witness read error)
    {1, 1, 0, 2, 1, 0, 0, 7, 1, 1, 0, 0, 0, 1, IG_CLASS},  // I8 the class overlay SAVE_UNCONFIRMED (7) is not VALID
    {1, 1, 0, 2, 1, 0, 0, 0, 1, 1, 0, 0, 0, 1, IG_CLASS},  // I8 UNREADABLE (0) is not VALID
    {1, 1, 4, 20, 1, 0, 0, 255, 2, 1, 0, 0, 0, 1, IG_CLASS},  // I8 outranks the id mismatch
    {1, 1, 4, 20, 1, 0, 0, 255, 1, 1, 0, 0, 0, 1, IG_ID_MISMATCH},  // I9 a well-formed id that is not the stored profile's binding
    {1, 1, 0, 2, 1, 0, 0, 5, 0, 1, 0, 0, 0, 1, IG_ID_MISMATCH},  // I9 the mirror class says VALID but no profile is loaded
    {1, 1, 4, 20, 1, 0, 0, 255, 8, 1, 0, 0, 0, 1, IG_ID_MISMATCH},  // I9 outranks a bad generation
    {1, 1, 11, 24, 1, 0, 0, 255, 1, 1, 0, 0, 0, 1, IG_ID_MISMATCH},  // I9 a phrase-consistent target that differs from the binding only in the HIGH 32 bits (bit 63): a 32-bit compare would pass it
    {1, 1, 12, 25, 1, 0, 0, 255, 1, 1, 0, 0, 0, 1, IG_ID_MISMATCH},  // I9 differs only in bit 32 (the lowest bit of the high word)
    {1, 1, 13, 26, 1, 0, 0, 255, 1, 1, 0, 0, 0, 1, IG_ID_MISMATCH},  // I9 differs in every bit of the high word and in no bit of the low word
    {1, 1, 14, 27, 1, 0, 0, 255, 1, 1, 0, 0, 0, 1, IG_ID_MISMATCH},  // I9 differs in every bit of the low word and in no bit of the high word
    {1, 1, 0, 2, 1, 0, 0, 5, 2, 1, 0, 0, 0, 1, IG_GENERATION},  // I10 the mirror class says VALID but the record is INVALIDATED (permission guard)
    {1, 1, 0, 2, 1, 0, 0, 255, 1, 14, 0, 0, 0, 1, IG_ACCEPT},  // all pass: a CORRUPT witness whose hw field is huge never raises the high-water (only a VALID witness counts)
    {1, 1, 0, 2, 1, 0, 0, 255, 1, 15, 0, 0, 0, 1, IG_ACCEPT},  // all pass: a WRONG_SIZE witness whose bytes carry a huge hw field never raises it
    {1, 1, 0, 2, 1, 0, 0, 255, 1, 16, 0, 0, 0, 1, IG_ACCEPT},  // all pass: an ABSENT witness whose bytes carry a huge hw field never raises it
    {1, 1, 0, 2, 1, 0, 0, 5, 1, 8, 0, 0, 0, 1, IG_GENERATION},  // I10 a VALID witness at hw g+1 counts: g+1 is not above it (the class is forced to VALID)
    {1, 1, 0, 2, 1, 0, 0, 5, 1, 9, 0, 0, 0, 1, IG_GENERATION},  // I10 a VALID witness at hw g+3 counts
    {1, 1, 0, 2, 1, 0, 0, 255, 8, 10, 0, 0, 0, 1, IG_GENERATION},  // I10 generation 0xFFFFFFFF cannot be invalidated
    {1, 1, 0, 2, 1, 0, 0, 255, 8, 1, 0, 0, 0, 1, IG_GENERATION},  // I10 generation 0xFFFFFFFF with a consistent witness
    {1, 1, 0, 2, 1, 0, 0, 255, 1, 1, 8, 0, 0, 1, IG_GENERATION},  // I10 g+1 is not above the seen high-water mark (seen 8)
    {1, 1, 0, 2, 1, 0, 0, 255, 1, 1, 100, 0, 0, 1, IG_GENERATION},  // I10 seen far above
    {1, 1, 0, 2, 1, 0, 0, 255, 1, 1, 4294967295, 0, 0, 1, IG_GENERATION},  // I10 seen 0xFFFFFFFF
    {1, 1, 0, 2, 1, 0, 0, 255, 1, 1, 8, 3, 0, 1, IG_GENERATION},  // I10 outranks a busy bus
    {1, 1, 0, 2, 1, 0, 0, 255, 1, 1, 0, 3, 0, 1, IG_BUS},  // I11 busy: the manual write mutex
    {1, 1, 0, 2, 1, 0, 0, 255, 1, 1, 0, 4, 0, 1, IG_BUS},  // I11 busy: a clock correction
    {1, 1, 0, 2, 1, 0, 0, 255, 1, 1, 0, 5, 0, 1, IG_BUS},  // I11 busy: a pending clock verification
    {1, 1, 0, 2, 1, 0, 0, 255, 1, 1, 0, 6, 0, 1, IG_BUS},  // I11 busy: an active clock verification read
    {1, 1, 0, 2, 1, 0, 0, 255, 1, 1, 0, 7, 0, 1, IG_BUS},  // I11 busy: a Free Power operation flag
    {1, 1, 0, 2, 1, 0, 0, 255, 1, 1, 0, 8, 0, 1, IG_BUS},  // I11 busy: a Free Power force restore
    {1, 1, 0, 2, 1, 0, 0, 255, 1, 1, 0, 9, 0, 1, IG_BUS},  // I11 busy: a Free Power accept
    {1, 1, 0, 2, 1, 0, 0, 255, 1, 1, 0, 10, 0, 1, IG_BUS},  // I11 busy: a Register 244 apply
    {1, 1, 0, 2, 1, 0, 0, 255, 1, 1, 0, 11, 0, 1, IG_BUS},  // I11 busy: a Dump operation flag
    {1, 1, 0, 2, 1, 0, 0, 255, 1, 1, 0, 0, 1, 1, IG_BUS},  // I11 the transmit queue is not empty
    {1, 1, 0, 2, 1, 0, 0, 255, 1, 1, 0, 0, 2, 1, IG_BUS},  // I11 the transmit queue is blocked
    {1, 1, 0, 2, 1, 0, 0, 255, 1, 1, 0, 3, 0, 3, IG_BUS},  // I11 outranks an FBS episode
    {1, 1, 0, 2, 1, 0, 0, 255, 1, 1, 0, 0, 0, 3, IG_FBS},  // I12 FBS: an open failback episode
    {1, 1, 0, 2, 1, 0, 0, 255, 1, 1, 0, 0, 0, 4, IG_FBS},  // I12 FBS: a CORRUPT failback record
    {1, 1, 0, 2, 1, 0, 0, 255, 1, 1, 0, 0, 0, 0, IG_FBS},  // I12 FBS: an unreadable failback record
};
// clang-format on

// SP columns: pk stored profile kind | wk witness kind | seen seen_hw_gen | mut input mutation | EXPECT PlanCode | gen | op | pg prior_generation of the witness | pbk 1 = the authentic prior's binding
struct SpRow {
  uint8_t pk, wk;
  uint32_t seen;
  uint8_t mut, expect;
  uint32_t gen;
  uint8_t op;
  uint32_t pg;
  uint8_t pbk;
};
// clang-format off
constexpr SpRow SP_CASES[] = {
    {0, 0, 0u, 0, PLAN_OK, 1u, 1, 0u, 0},  // first save: NOT_CAPTURED, both records absent -> generation 1, op SAVE, prior 0/0
    {0, 0, 5u, 0, PLAN_OK, 6u, 1, 0u, 0},  // first save after a same-boot read of g5 (the seen floor) -> 6
    {1, 1, 0u, 0, PLAN_OK, 8u, 1, 7u, 1},  // VALID g7, consistent witness -> 8, prior 7 / its binding
    {1, 2, 0u, 0, PLAN_OK, 8u, 1, 7u, 1},  // VALID g7, lagging witness (B8, hw 6) -> 8
    {1, 0, 0u, 0, PLAN_OK, 8u, 1, 7u, 1},  // VALID g7, witness missing (B14) -> 8
    {1, 3, 0u, 0, PLAN_OK, 8u, 1, 7u, 1},  // VALID g7, witness corrupt (B15) -> 8
    {1, 4, 0u, 0, PLAN_OK, 8u, 1, 7u, 1},  // VALID g7, witness wrong size (B15) -> 8
    {1, 14, 0u, 0, PLAN_OK, 8u, 1, 7u, 1},  // VALID g7, witness corrupt with a huge hw field: a corrupt witness' hw never counts -> 8
    {1, 15, 0u, 0, PLAN_OK, 8u, 1, 7u, 1},  // VALID g7, wrong-size witness carrying a huge hw field -> 8
    {1, 16, 0u, 0, PLAN_OK, 8u, 1, 7u, 1},  // VALID g7, absent witness carrying a huge hw field -> 8
    {1, 5, 0u, 0, PLAN_CLASS, 0u, 0, 0u, 0},  // VALID g7, witness unreadable -> the class is UNREADABLE
    {1, 1, 20u, 0, PLAN_OK, 21u, 1, 7u, 1},  // VALID g7, seen 20 -> 21
    {1, 1, 7u, 0, PLAN_OK, 8u, 1, 7u, 1},  // VALID g7, seen 7 -> 8
    {1, 1, 4294967295u, 0, PLAN_GENERATION, 0u, 0, 0u, 0},  // VALID g7, seen 0xFFFFFFFF -> the counter is exhausted
    {8, 10, 0u, 0, PLAN_GENERATION, 0u, 0, 0u, 0},  // VALID gMAX, witness hw MAX -> exhausted
    {8, 1, 0u, 0, PLAN_GENERATION, 0u, 0, 0u, 0},  // VALID gMAX, consistent witness -> exhausted
    {1, 1, 4294967294u, 0, PLAN_OK, 4294967295u, 1, 7u, 1},  // VALID g7, seen 0xFFFFFFFE -> generation 0xFFFFFFFF (the last one)
    {2, 1, 0u, 0, PLAN_OK, 9u, 1, 8u, 1},  // INVALIDATED g8 -> 9, prior 8 / its binding
    {3, 1, 0u, 0, PLAN_OK, 10u, 1, 9u, 1},  // CORRUPT_DOMAIN g9 -> 10, prior 9 / its binding
    {0, 7, 0u, 0, PLAN_OK, 6u, 1, 0u, 0},  // PROFILE_LOST B6: profile absent, witness hw 5 -> 6, prior 0/0
    {0, 6, 0u, 0, PLAN_OK, 2u, 1, 0u, 0},  // PROFILE_LOST B5: first save unconfirmed (hw 1) -> 2
    {0, 3, 0u, 0, PLAN_OK, 1u, 1, 0u, 0},  // PROFILE_LOST B7: witness corrupt, nothing seen -> 1
    {0, 3, 3u, 0, PLAN_OK, 4u, 1, 0u, 0},  // PROFILE_LOST B7: witness corrupt, seen 3 -> 4
    {0, 4, 0u, 0, PLAN_OK, 1u, 1, 0u, 0},  // PROFILE_LOST B7: witness wrong size -> 1
    {1, 8, 0u, 0, PLAN_OK, 9u, 1, 7u, 1},  // PROFILE_STALE INTERRUPTED: profile g7, witness hw 8 -> 9, prior 7 / the stale record's binding
    {9, 9, 0u, 0, PLAN_OK, 7u, 1, 3u, 1},  // PROFILE_STALE ROLLBACK: profile g3, witness hw 6 -> 7, prior 3
    {1, 11, 0u, 0, PLAN_OK, 8u, 1, 7u, 1},  // PROFILE_STALE SUPERSEDED (foreign tag): profile g7 -> 8
    {1, 13, 0u, 0, PLAN_OK, 8u, 1, 7u, 1},  // PROFILE_STALE MISMATCH: same generation, other binding -> 8
    {4, 1, 0u, 0, PLAN_OK, 12u, 3, 0u, 0},  // CORRUPT (binding defect, g11) with a valid witness hw 11 -> 12 REPLACE_CORRUPT, prior 0/0
    {4, 0, 0u, 0, PLAN_OK, 1u, 3, 0u, 0},  // CORRUPT with the witness missing -> 1 REPLACE_CORRUPT
    {4, 0, 12u, 0, PLAN_OK, 13u, 3, 0u, 0},  // CORRUPT with the witness missing, seen 12 -> 13
    {4, 3, 0u, 0, PLAN_OK, 1u, 3, 0u, 0},  // CORRUPT with a corrupt witness -> 1
    {5, 1, 0u, 0, PLAN_OK, 10u, 3, 0u, 0},  // CORRUPT wrong-size profile (stored 40 bytes), witness hw 9 -> 10 REPLACE_CORRUPT
    {5, 0, 0u, 0, PLAN_OK, 1u, 3, 0u, 0},  // CORRUPT wrong-size profile, witness missing -> 1
    {5, 4, 0u, 0, PLAN_OK, 1u, 3, 0u, 0},  // CORRUPT wrong-size profile, witness wrong size -> 1
    {6, 1, 0u, 0, PLAN_CLASS, 0u, 0, 0u, 0},  // UNREADABLE (profile read error)
    {7, 1, 0u, 0, PLAN_CLASS, 0u, 0, 0u, 0},  // UNREADABLE (storage unavailable)
    {6, 0, 0u, 0, PLAN_CLASS, 0u, 0, 0u, 0},  // UNREADABLE (profile read error, witness absent)
    {1, 1, 0u, 1, PLAN_UNCONFIRMED, 0u, 0, 0u, 0},  // the SAVE_UNCONFIRMED overlay is set
    {1, 1, 0u, 2, PLAN_ANOMALY, 0u, 0, 0u, 0},  // a read anomaly (4) this boot
    {1, 1, 0u, 3, PLAN_CONTEXT, 0u, 0, 0u, 0},  // the SAVE context says REPLACE CORRUPT but the prior is VALID
    {4, 1, 0u, 3, PLAN_CONTEXT, 0u, 0, 0u, 0},  // the SAVE context says plain SAVE but the prior is CORRUPT
    {1, 1, 0u, 4, PLAN_CLOCK, 0u, 0, 0u, 0},  // no trusted capture time (epoch 0)
    {1, 1, 0u, 13, PLAN_CLASS, 0u, 0, 0u, 0},  // the class passed is the SAVE_UNCONFIRMED overlay value (7) itself, bound to the candidate
    {1, 1, 0u, 14, PLAN_CLASS, 0u, 0, 0u, 0},  // an out-of-table class value (9), bound to the candidate
    {1, 1, 0u, 5, PLAN_PRIOR_CHANGED, 0u, 0, 0u, 0},  // the candidate was reviewed against another class
    {1, 1, 0u, 6, PLAN_PRIOR_CHANGED, 0u, 0, 0u, 0},  // the candidate was reviewed against another generation
    {1, 1, 0u, 7, PLAN_PRIOR_CHANGED, 0u, 0, 0u, 0},  // the candidate was reviewed against another binding
    {4, 1, 0u, 7, PLAN_PRIOR_CHANGED, 0u, 0, 0u, 0},  // a CORRUPT prior whose raw binding changed since Review
    {1, 1, 0u, 15, PLAN_PRIOR_CHANGED, 0u, 0, 0u, 0},  // the candidate's prior binding differs only in the HIGH 32 bits (bit 63): a 32-bit compare would pass it
    {1, 1, 0u, 16, PLAN_PRIOR_CHANGED, 0u, 0, 0u, 0},  // ... only in bit 32
    {1, 1, 0u, 17, PLAN_PRIOR_CHANGED, 0u, 0, 0u, 0},  // ... or is only the low 32 bits of the stored binding
    {4, 1, 0u, 15, PLAN_PRIOR_CHANGED, 0u, 0, 0u, 0},  // a CORRUPT prior's raw-fingerprint binding differs only in the HIGH 32 bits (bit 63)
    {4, 1, 0u, 16, PLAN_PRIOR_CHANGED, 0u, 0, 0u, 0},  // ... only in bit 32
    {4, 1, 0u, 17, PLAN_PRIOR_CHANGED, 0u, 0, 0u, 0},  // ... or is only the low 32 bits of the raw binding
    {2, 1, 0u, 15, PLAN_PRIOR_CHANGED, 0u, 0, 0u, 0},  // an INVALIDATED prior's binding differs only in the HIGH 32 bits
    {5, 1, 0u, 6, PLAN_PRIOR_CHANGED, 0u, 0, 0u, 0},  // a wrong-size prior whose stored length changed since Review (generation off)
    {0, 0, 0u, 5, PLAN_PRIOR_CHANGED, 0u, 0, 0u, 0},  // a NOT_CAPTURED prior is VALID now (class off)
    {1, 1, 0u, 8, PLAN_PRIOR_CHANGED, 0u, 0, 0u, 0},  // a changed prior outranks an unconfirmed overlay (D14 order)
    {1, 1, 0u, 9, PLAN_UNCONFIRMED, 0u, 0, 0u, 0},  // unconfirmed outranks a read anomaly
    {4, 1, 0u, 10, PLAN_ANOMALY, 0u, 0, 0u, 0},  // a read anomaly outranks a wrong REPLACE flag
    {1, 1, 0u, 11, PLAN_CONTEXT, 0u, 0, 0u, 0},  // a wrong REPLACE flag outranks the missing clock
    {1, 1, 4294967295u, 12, PLAN_CLOCK, 0u, 0, 0u, 0},  // a missing clock outranks an exhausted counter
};
// clang-format on

// IP columns: pk | wk | seen | mut | EXPECT PlanCode | gen | pg
struct IpRow {
  uint8_t pk, wk;
  uint32_t seen;
  uint8_t mut, expect;
  uint32_t gen, pg;
};
// clang-format off
constexpr IpRow IP_CASES[] = {
    {1, 1, 0u, 0, PLAN_OK, 8u, 7u},  // VALID g7, consistent witness -> INVALIDATED g8
    {1, 2, 0u, 0, PLAN_OK, 8u, 7u},  // VALID g7, lagging witness (B8) -> g8
    {1, 0, 0u, 0, PLAN_OK, 8u, 7u},  // VALID g7, witness missing (B14) -> g8
    {1, 3, 0u, 0, PLAN_OK, 8u, 7u},  // VALID g7, witness corrupt (B15) -> g8
    {1, 4, 0u, 0, PLAN_OK, 8u, 7u},  // VALID g7, witness wrong size -> g8
    {1, 1, 7u, 0, PLAN_OK, 8u, 7u},  // VALID g7, seen exactly 7 -> g8
    {1, 12, 0u, 0, PLAN_OK, 8u, 7u},  // VALID g7, witness op INVALIDATE -> g8
    {1, 14, 0u, 0, PLAN_OK, 8u, 7u},  // VALID g7, corrupt witness with a huge hw field: only a VALID witness' hw counts -> g8
    {1, 15, 0u, 0, PLAN_OK, 8u, 7u},  // VALID g7, wrong-size witness carrying a huge hw field -> g8
    {1, 16, 0u, 0, PLAN_OK, 8u, 7u},  // VALID g7, absent witness carrying a huge hw field -> g8
    {2, 1, 0u, 0, PLAN_CLASS, 0u, 0u},  // an INVALIDATED profile cannot be invalidated again
    {3, 1, 0u, 0, PLAN_CLASS, 0u, 0u},  // CORRUPT_DOMAIN is refused
    {4, 1, 0u, 0, PLAN_CLASS, 0u, 0u},  // CORRUPT is refused
    {5, 1, 0u, 0, PLAN_CLASS, 0u, 0u},  // a wrong-size profile is refused
    {0, 0, 0u, 0, PLAN_CLASS, 0u, 0u},  // NOT_CAPTURED is refused
    {0, 7, 0u, 0, PLAN_CLASS, 0u, 0u},  // PROFILE_LOST is refused
    {1, 8, 0u, 0, PLAN_CLASS, 0u, 0u},  // PROFILE_STALE (interrupted) is refused
    {9, 9, 0u, 0, PLAN_CLASS, 0u, 0u},  // PROFILE_STALE (rollback) is refused
    {6, 1, 0u, 0, PLAN_CLASS, 0u, 0u},  // UNREADABLE is refused
    {1, 5, 0u, 0, PLAN_CLASS, 0u, 0u},  // a witness read error is UNREADABLE
    {1, 1, 0u, 1, PLAN_UNCONFIRMED, 0u, 0u},  // the overlay is set
    {1, 1, 0u, 2, PLAN_ANOMALY, 0u, 0u},  // a read anomaly
    {1, 1, 0u, 5, PLAN_UNCONFIRMED, 0u, 0u},  // the overlay outranks a read anomaly
    {1, 1, 0u, 3, PLAN_BINDING_CHANGED, 0u, 0u},  // the stored profile is not the one the operator named
    {1, 1, 0u, 4, PLAN_BINDING_CHANGED, 0u, 0u},  // a zero target id never matches
    {1, 1, 0u, 6, PLAN_BINDING_CHANGED, 0u, 0u},  // the named binding differs only in the HIGH 32 bits (bit 63): a 32-bit compare would pass it
    {1, 1, 0u, 7, PLAN_BINDING_CHANGED, 0u, 0u},  // ... only in bit 32
    {1, 1, 0u, 8, PLAN_BINDING_CHANGED, 0u, 0u},  // ... in every bit of the high word
    {1, 1, 0u, 9, PLAN_BINDING_CHANGED, 0u, 0u},  // ... or is only the low 32 bits of the stored binding
    {1, 1, 8u, 0, PLAN_GENERATION, 0u, 0u},  // g+1 is not above the seen high-water mark (seen 8)
    {1, 1, 4294967295u, 0, PLAN_GENERATION, 0u, 0u},  // seen 0xFFFFFFFF
    {8, 1, 0u, 0, PLAN_GENERATION, 0u, 0u},  // generation 0xFFFFFFFF with a consistent witness
    {8, 10, 0u, 0, PLAN_GENERATION, 0u, 0u},  // generation 0xFFFFFFFF with a witness hw MAX
    {1, 8, 0u, 10, PLAN_GENERATION, 0u, 0u},  // a VALID witness at hw g+1 counts: g+1 is not above it (the composed class is forced to VALID)
    {1, 9, 0u, 10, PLAN_GENERATION, 0u, 0u},  // a VALID witness at hw g+3 counts
};
// clang-format on

// The result of one SAVE gate golden-case row.
constexpr SaveGateResult sg_run(const SgRow &c) {
  const SaveGateInputs si = fx_sg(c.cand, c.age, c.cls, c.boot, c.unc, c.anom, c.hb, c.time, c.arm, c.wfp);
  const uint64_t id = (c.cand == 0 || c.cand == 4 || c.cand == 5) ? FX_ID : 0ULL;
  const TextBuf act = fx_action(c.tok);
  const TextBuf tgt = fx_target(c.tgt, id);
  const TextBuf cnf = fx_conf(c.cnf, id);
  return save_gate_decide(si, act.c_str(), act.size(), tgt.c_str(), tgt.size(), cnf.c_str(), cnf.size(), fx_gate(c.gate));
}
constexpr bool sg_case_holds(const SgRow &c) { return sg_run(c).code == c.expect; }
constexpr bool sg_cases_hold() {
  for (size_t i = 0; i < sizeof(SG_CASES) / sizeof(SG_CASES[0]); i++) {
    if (!sg_case_holds(SG_CASES[i]))
      return false;
  }
  return true;
}

// The INVALIDATE gate inputs of a golden-case row (the id is the stored profile's binding).
constexpr InvalidateGateInputs fx_ig(const IgRow &c) {
  InvalidateGateInputs in{};
  const FxP pr = fx_p(c.pk);
  const FxW wr = fx_w(c.wk, pr.p);
  in.arm_was_on = c.arm != 0;
  in.boot_loaded = c.boot != 0;
  in.read_anomaly = c.anom;
  in.unconfirmed = c.unc != 0;
  in.cls = c.cls_o != 255 ? c.cls_o : ecco_fbdurable::compose_profile_class(pr.load, pr.p, wr.load, wr.w, 0).cls;
  in.p_load = pr.load;
  in.p = pr.p;
  in.w_load = wr.load;
  in.w = wr.w;
  in.seen_hw_gen = c.seen;
  in.bus = fx_bus(c.bus);
  in.tx_buffer_empty = c.tx != 1;
  in.tx_blocked = c.tx == 2;
  in.fbs_slot = c.fbs;
  return in;
}
constexpr InvalidateGateResult ig_run(const IgRow &c) {
  const InvalidateGateInputs in = fx_ig(c);
  const uint64_t id = in.p.binding;
  const TextBuf act = fx_action(c.tok);
  const TextBuf tgt = fx_target(c.tgt, id);
  const TextBuf cnf = fx_conf(c.cnf, id);
  return invalidate_gate_decide(in, act.c_str(), act.size(), tgt.c_str(), tgt.size(), cnf.c_str(), cnf.size());
}
constexpr bool ig_cases_hold() {
  for (size_t i = 0; i < sizeof(IG_CASES) / sizeof(IG_CASES[0]); i++) {
    if (ig_run(IG_CASES[i]).code != IG_CASES[i].expect)
      return false;
  }
  return true;
}

// FNV-1a-64 over both records of a plan (zero records for a refusal) and its verdict.
constexpr uint64_t fx_digest(const Plan &r) {
  uint64_t h = ecco_fallback::FNV1A64_OFFSET_BASIS;
  const ecco_fallback::ProfileBytes pb = ecco_fallback::encode_profile(r.p_new);
  for (size_t i = 0; i < pb.size(); i++)
    h = ecco_fallback::fnv1a64_step(h, pb[i]);
  const ecco_fbdurable::ProvisionBytes wb = ecco_fbdurable::encode_provision(r.w_new);
  for (size_t i = 0; i < wb.size(); i++)
    h = ecco_fallback::fnv1a64_step(h, wb[i]);
  return h;
}

constexpr SavePlanInputs sp_inputs(const SpRow &c) { return fx_save_mut(fx_save_inputs(c.pk, c.wk, c.seen), c.mut); }
constexpr InvalidatePlanInputs ip_inputs(const IpRow &c) { return fx_inv_mut(fx_inv_inputs(c.pk, c.wk, c.seen), c.mut); }

// A SAVE plan row: the verdict, the generation, the op and the witness' prior fields; an accepted plan must also be accepted by the
// FB-B0 writer's own transition check (the plan can never be refused as an invalid transition) and carry the pass-2 payload.
constexpr bool sp_case_holds(const SpRow &c) {
  const SavePlanInputs in = sp_inputs(c);
  const Plan r = plan_save(in);
  if (r.code != c.expect)
    return false;
  if (c.expect != PLAN_OK)
    return r.op == 0 && r.generation == 0 && r.text.size() != 0;
  const ecco_fbdurable::PriorDesc wpd{in.w_load, in.w_stored_len};
  const ecco_fbdurable::PriorDesc ppd{in.p_load, in.p_stored_len};
  return r.generation == c.gen && r.op == c.op && r.w_new.last_op == c.op && r.w_new.hw_generation == c.gen && r.p_new.generation == c.gen &&
         r.w_new.hw_binding == r.p_new.binding && r.w_new.prior_generation == c.pg &&
         r.w_new.prior_binding == (c.pbk != 0 ? in.p.binding : 0ULL) && r.p_new.captured_epoch == FX_EPOCH && r.p_new.flags == 0 &&
         ecco_fbcap::first_diff(ecco_fbcap::words_of(r.p_new), in.words) == -1 && r.text.size() == 0 &&
         ecco_fbdurable::validate_transition(r.w_new, in.w, wpd, r.p_new, in.p, ppd);
}
constexpr bool sp_cases_hold() {
  for (size_t i = 0; i < sizeof(SP_CASES) / sizeof(SP_CASES[0]); i++) {
    if (!sp_case_holds(SP_CASES[i]))
      return false;
  }
  return true;
}
// An INVALIDATE plan row: the payload is preserved byte for byte, the generation is the prior's + 1, the witness names the prior.
constexpr bool ip_case_holds(const IpRow &c) {
  const InvalidatePlanInputs in = ip_inputs(c);
  const Plan r = plan_invalidate(in);
  if (r.code != c.expect)
    return false;
  if (c.expect != PLAN_OK)
    return r.op == 0 && r.generation == 0 && r.text.size() != 0;
  const ecco_fbdurable::PriorDesc wpd{in.w_load, in.w_stored_len};
  const ecco_fbdurable::PriorDesc ppd{in.p_load, in.p_stored_len};
  return r.generation == c.gen && r.op == ecco_fbdurable::PROV_OP_INVALIDATE && r.p_new.generation == c.gen &&
         r.p_new.flags == ecco_fallback::PROFILE_FLAG_INVALIDATED && r.p_new.captured_epoch == in.p.captured_epoch &&
         r.w_new.hw_generation == c.gen && r.w_new.hw_binding == r.p_new.binding && r.w_new.prior_generation == c.pg &&
         r.w_new.prior_binding == in.p.binding && r.w_new.last_op == ecco_fbdurable::PROV_OP_INVALIDATE &&
         ecco_fbcap::first_diff(ecco_fbcap::words_of(r.p_new), ecco_fbcap::words_of(in.p)) == -1 &&
         ecco_fallback::classify_profile(ecco_fallback::LOAD_OK, r.p_new) == ecco_fallback::PROFILE_INVALIDATED &&
         ecco_fbdurable::validate_transition(r.w_new, in.w, wpd, r.p_new, in.p, ppd);
}
constexpr bool ip_cases_hold() {
  for (size_t i = 0; i < sizeof(IP_CASES) / sizeof(IP_CASES[0]); i++) {
    if (!ip_case_holds(IP_CASES[i]))
      return false;
  }
  return true;
}

static_assert(sg_cases_hold(), "FB-B2 golden cases: SAVE GATE");
static_assert(ig_cases_hold(), "FB-B2 golden cases: INVALIDATE GATE");
static_assert(sp_cases_hold(), "FB-B2 golden cases: SAVE PLAN");
static_assert(ip_cases_hold(), "FB-B2 golden cases: INVALIDATE PLAN");

// SEM-4: the fail-closed DEFAULT of every input field that has to refuse. Each assertion takes an input that passes everything (the all-pass
// fixture), puts exactly ONE field back to its in-struct default and requires the decision to refuse with the named code: a default flipped to its
// fail-open value (hb_ok = true, time_trusted = true, seen_hw_gen = 0, ...) no longer compiles. Fields that are NOT listed cannot refuse by their
// default alone, by design: now_ms / cand_prior_class (a time stamp / the class the plan re-checks), the lone witness load and record (a lost
// witness is tolerated: B14 / B15), p_stored_len / why (not read for a LOAD_OK prior), replace_corrupt / words (data of the plan) and the capture
// BusInputs of InvalidateGateInputs (the documented permissive exception).
template<auto M, typename S> constexpr S dflt(S in) {
  in.*M = S{}.*M;
  return in;
}
constexpr SaveGateInputs fx_sg_pass() { return fx_sg(0, 0, 5, 1, 0, 0, 1, 1, 1, 0); }
constexpr uint8_t sgd(const SaveGateInputs &in) {
  const TextBuf act = fx_action(0);
  const TextBuf tgt = fx_target(0, FX_ID);
  const TextBuf cnf = fx_conf(0, FX_ID);
  return save_gate_decide(in, act.c_str(), act.size(), tgt.c_str(), tgt.size(), cnf.c_str(), cnf.size(), fx_gate(0)).code;
}
constexpr InvalidateGateInputs fx_ig_pass() { return fx_ig(IG_CASES[0]); }
constexpr uint8_t igd(const InvalidateGateInputs &in) {
  const uint64_t id = fx_ig_pass().p.binding;
  const TextBuf act = fx_action(1);
  const TextBuf tgt = fx_target(0, id);
  const TextBuf cnf = fx_conf(2, id);
  return invalidate_gate_decide(in, act.c_str(), act.size(), tgt.c_str(), tgt.size(), cnf.c_str(), cnf.size()).code;
}
constexpr SavePlanInputs fx_sp_pass() { return fx_save_inputs(1, 1, 0u); }
constexpr uint8_t spd(const SavePlanInputs &in) { return plan_save(in).code; }
constexpr InvalidatePlanInputs fx_ip_pass() { return fx_inv_inputs(1, 1, 0u); }
constexpr uint8_t ipd(const InvalidatePlanInputs &in) { return plan_invalidate(in).code; }

static_assert(sgd(fx_sg_pass()) == SG_ACCEPT, "FB-B2 default control: the SAVE gate all-pass input accepts");
static_assert(igd(fx_ig_pass()) == IG_ACCEPT, "FB-B2 default control: the INVALIDATE gate all-pass input accepts");
static_assert(spd(fx_sp_pass()) == PLAN_OK, "FB-B2 default control: the SAVE plan all-pass input is built");
static_assert(ipd(fx_ip_pass()) == PLAN_OK, "FB-B2 default control: the INVALIDATE plan all-pass input is built");
static_assert(sgd(dflt<&SaveGateInputs::arm_was_on>(fx_sg_pass())) == SG_ARM_OFF, "FB-B2 default: SaveGateInputs.arm_was_on refuses (SG_ARM_OFF)");
static_assert(sgd(dflt<&SaveGateInputs::cand_valid>(fx_sg_pass())) == SG_NO_CANDIDATE, "FB-B2 default: SaveGateInputs.cand_valid refuses (SG_NO_CANDIDATE)");
static_assert(sgd(dflt<&SaveGateInputs::cand_saveable>(fx_sg_pass())) == SG_NO_CANDIDATE, "FB-B2 default: SaveGateInputs.cand_saveable refuses (SG_NO_CANDIDATE)");
static_assert(sgd(dflt<&SaveGateInputs::cand_id>(fx_sg_pass())) == SG_NO_CANDIDATE, "FB-B2 default: SaveGateInputs.cand_id refuses (SG_NO_CANDIDATE)");
static_assert(sgd(dflt<&SaveGateInputs::cand_ms>(fx_sg_pass())) == SG_EXPIRED, "FB-B2 default: SaveGateInputs.cand_ms refuses (SG_EXPIRED)");
static_assert(sgd(dflt<&SaveGateInputs::cand_writes_fp>(fx_sg_pass())) == SG_WRITES, "FB-B2 default: SaveGateInputs.cand_writes_fp refuses (SG_WRITES)");
static_assert(sgd(dflt<&SaveGateInputs::writes_fp_now>(fx_sg_pass())) == SG_WRITES, "FB-B2 default: SaveGateInputs.writes_fp_now refuses (SG_WRITES)");
static_assert(sgd(dflt<&SaveGateInputs::boot_loaded>(fx_sg_pass())) == SG_NOT_LOADED, "FB-B2 default: SaveGateInputs.boot_loaded refuses (SG_NOT_LOADED)");
static_assert(sgd(dflt<&SaveGateInputs::unconfirmed>(fx_sg_pass())) == SG_UNCONFIRMED, "FB-B2 default: SaveGateInputs.unconfirmed refuses (SG_UNCONFIRMED)");
static_assert(sgd(dflt<&SaveGateInputs::read_anomaly>(fx_sg_pass())) == SG_ANOMALY, "FB-B2 default: SaveGateInputs.read_anomaly refuses (SG_ANOMALY)");
static_assert(sgd(dflt<&SaveGateInputs::hb_ok>(fx_sg_pass())) == SG_HB, "FB-B2 default: SaveGateInputs.hb_ok refuses (SG_HB)");
static_assert(sgd(dflt<&SaveGateInputs::time_trusted>(fx_sg_pass())) == SG_TIME, "FB-B2 default: SaveGateInputs.time_trusted refuses (SG_TIME)");
static_assert(igd(dflt<&InvalidateGateInputs::arm_was_on>(fx_ig_pass())) == IG_ARM_OFF, "FB-B2 default: InvalidateGateInputs.arm_was_on refuses (IG_ARM_OFF)");
static_assert(igd(dflt<&InvalidateGateInputs::boot_loaded>(fx_ig_pass())) == IG_NOT_LOADED, "FB-B2 default: InvalidateGateInputs.boot_loaded refuses (IG_NOT_LOADED)");
static_assert(igd(dflt<&InvalidateGateInputs::read_anomaly>(fx_ig_pass())) == IG_ANOMALY, "FB-B2 default: InvalidateGateInputs.read_anomaly refuses (IG_ANOMALY)");
static_assert(igd(dflt<&InvalidateGateInputs::unconfirmed>(fx_ig_pass())) == IG_UNCONFIRMED, "FB-B2 default: InvalidateGateInputs.unconfirmed refuses (IG_UNCONFIRMED)");
static_assert(igd(dflt<&InvalidateGateInputs::cls>(fx_ig_pass())) == IG_CLASS, "FB-B2 default: InvalidateGateInputs.cls refuses (IG_CLASS)");
static_assert(igd(dflt<&InvalidateGateInputs::p_load>(fx_ig_pass())) == IG_ID_MISMATCH, "FB-B2 default: InvalidateGateInputs.p_load refuses (IG_ID_MISMATCH)");
static_assert(igd(dflt<&InvalidateGateInputs::p>(fx_ig_pass())) == IG_ID_MISMATCH, "FB-B2 default: InvalidateGateInputs.p refuses (IG_ID_MISMATCH)");
static_assert(igd(dflt<&InvalidateGateInputs::seen_hw_gen>(fx_ig_pass())) == IG_GENERATION, "FB-B2 default: InvalidateGateInputs.seen_hw_gen refuses (IG_GENERATION)");
static_assert(igd(dflt<&InvalidateGateInputs::tx_buffer_empty>(fx_ig_pass())) == IG_BUS, "FB-B2 default: InvalidateGateInputs.tx_buffer_empty refuses (IG_BUS)");
static_assert(igd(dflt<&InvalidateGateInputs::tx_blocked>(fx_ig_pass())) == IG_BUS, "FB-B2 default: InvalidateGateInputs.tx_blocked refuses (IG_BUS)");
static_assert(igd(dflt<&InvalidateGateInputs::fbs_slot>(fx_ig_pass())) == IG_FBS, "FB-B2 default: InvalidateGateInputs.fbs_slot refuses (IG_FBS)");
static_assert(spd(dflt<&SavePlanInputs::p_load>(fx_sp_pass())) == PLAN_PRIOR_CHANGED, "FB-B2 default: SavePlanInputs.p_load refuses (PLAN_PRIOR_CHANGED)");
static_assert(spd(dflt<&SavePlanInputs::p>(fx_sp_pass())) == PLAN_PRIOR_CHANGED, "FB-B2 default: SavePlanInputs.p refuses (PLAN_PRIOR_CHANGED)");
static_assert(spd(dflt<&SavePlanInputs::cls>(fx_sp_pass())) == PLAN_PRIOR_CHANGED, "FB-B2 default: SavePlanInputs.cls refuses (PLAN_PRIOR_CHANGED)");
static_assert(spd(dflt<&SavePlanInputs::read_anomaly>(fx_sp_pass())) == PLAN_ANOMALY, "FB-B2 default: SavePlanInputs.read_anomaly refuses (PLAN_ANOMALY)");
static_assert(spd(dflt<&SavePlanInputs::unconfirmed>(fx_sp_pass())) == PLAN_UNCONFIRMED, "FB-B2 default: SavePlanInputs.unconfirmed refuses (PLAN_UNCONFIRMED)");
static_assert(spd(dflt<&SavePlanInputs::seen_hw_gen>(fx_sp_pass())) == PLAN_GENERATION, "FB-B2 default: SavePlanInputs.seen_hw_gen refuses (PLAN_GENERATION)");
static_assert(spd(dflt<&SavePlanInputs::cand_prior_class>(fx_sp_pass())) == PLAN_PRIOR_CHANGED, "FB-B2 default: SavePlanInputs.cand_prior_class refuses (PLAN_PRIOR_CHANGED)");
static_assert(spd(dflt<&SavePlanInputs::cand_prior_gen>(fx_sp_pass())) == PLAN_PRIOR_CHANGED, "FB-B2 default: SavePlanInputs.cand_prior_gen refuses (PLAN_PRIOR_CHANGED)");
static_assert(spd(dflt<&SavePlanInputs::cand_prior_binding>(fx_sp_pass())) == PLAN_PRIOR_CHANGED, "FB-B2 default: SavePlanInputs.cand_prior_binding refuses (PLAN_PRIOR_CHANGED)");
static_assert(spd(dflt<&SavePlanInputs::captured_epoch>(fx_sp_pass())) == PLAN_CLOCK, "FB-B2 default: SavePlanInputs.captured_epoch refuses (PLAN_CLOCK)");
static_assert(ipd(dflt<&InvalidatePlanInputs::p_load>(fx_ip_pass())) == PLAN_BINDING_CHANGED, "FB-B2 default: InvalidatePlanInputs.p_load refuses (PLAN_BINDING_CHANGED)");
static_assert(ipd(dflt<&InvalidatePlanInputs::p>(fx_ip_pass())) == PLAN_BINDING_CHANGED, "FB-B2 default: InvalidatePlanInputs.p refuses (PLAN_BINDING_CHANGED)");
static_assert(ipd(dflt<&InvalidatePlanInputs::cls>(fx_ip_pass())) == PLAN_CLASS, "FB-B2 default: InvalidatePlanInputs.cls refuses (PLAN_CLASS)");
static_assert(ipd(dflt<&InvalidatePlanInputs::read_anomaly>(fx_ip_pass())) == PLAN_ANOMALY, "FB-B2 default: InvalidatePlanInputs.read_anomaly refuses (PLAN_ANOMALY)");
static_assert(ipd(dflt<&InvalidatePlanInputs::unconfirmed>(fx_ip_pass())) == PLAN_UNCONFIRMED, "FB-B2 default: InvalidatePlanInputs.unconfirmed refuses (PLAN_UNCONFIRMED)");
static_assert(ipd(dflt<&InvalidatePlanInputs::seen_hw_gen>(fx_ip_pass())) == PLAN_GENERATION, "FB-B2 default: InvalidatePlanInputs.seen_hw_gen refuses (PLAN_GENERATION)");
static_assert(ipd(dflt<&InvalidatePlanInputs::target_id>(fx_ip_pass())) == PLAN_BINDING_CHANGED, "FB-B2 default: InvalidatePlanInputs.target_id refuses (PLAN_BINDING_CHANGED)");

// ---- GENERATED-GOLDENS-BEGIN (registry/tests/test_fallback_save_host_compile.py --emit-goldens) ----
static_assert((ARM_TTL_MS) == 120000, "FB-B2 value: constant ARM_TTL_MS");
static_assert((PRECOMMIT_WAIT_MS) == 3000, "FB-B2 value: constant PRECOMMIT_WAIT_MS");
static_assert((PURPOSE_SAVE) == 2, "FB-B2 value: constant PURPOSE_SAVE");
static_assert((ECHO_MAX) == 24, "FB-B2 value: constant ECHO_MAX");
static_assert((ECHO_LOOK) == 4, "FB-B2 value: constant ECHO_LOOK");
static_assert((ID_DIGITS) == 16, "FB-B2 value: constant ID_DIGITS");
static_assert((PHRASE_SCAN_MAX) == 64, "FB-B2 value: constant PHRASE_SCAN_MAX");
static_assert((ACTION_SCAN_MAX) == 16, "FB-B2 value: constant ACTION_SCAN_MAX");
static_assert((ecco_fbcap::CAPTURE_SAVING) == 4, "FB-B2 value: constant ecco_fbcap::CAPTURE_SAVING (D8)");
static_assert((ecco_fbcap::TEXT_CAP) == 200, "FB-B2 value: constant ecco_fbcap::TEXT_CAP");
static_assert(str_is(SAVE_REFUSED_PREFIX, "SAVE REFUSED - "), "FB-B2 name: SAVE_REFUSED_PREFIX");
static_assert(str_is(INVALIDATE_REFUSED_PREFIX, "INVALIDATE REFUSED - "), "FB-B2 name: INVALIDATE_REFUSED_PREFIX");
static_assert(str_is(ecco_fbcap::capture_state_name(0), "IDLE"), "FB-B2 name: capture_state_name 0 (D8: 4 is SAVING, 5.. IDLE)");
static_assert(str_is(ecco_fbcap::capture_state_name(1), "READING"), "FB-B2 name: capture_state_name 1 (D8: 4 is SAVING, 5.. IDLE)");
static_assert(str_is(ecco_fbcap::capture_state_name(2), "CANDIDATE_READY"), "FB-B2 name: capture_state_name 2 (D8: 4 is SAVING, 5.. IDLE)");
static_assert(str_is(ecco_fbcap::capture_state_name(3), "CANDIDATE_NOT_SAVEABLE"), "FB-B2 name: capture_state_name 3 (D8: 4 is SAVING, 5.. IDLE)");
static_assert(str_is(ecco_fbcap::capture_state_name(4), "SAVING"), "FB-B2 name: capture_state_name 4 (D8: 4 is SAVING, 5.. IDLE)");
static_assert(str_is(ecco_fbcap::capture_state_name(5), "IDLE"), "FB-B2 name: capture_state_name 5 (D8: 4 is SAVING, 5.. IDLE)");
static_assert(str_is(ecco_fbcap::capture_state_name(6), "IDLE"), "FB-B2 name: capture_state_name 6 (D8: 4 is SAVING, 5.. IDLE)");
static_assert(str_is(ecco_fbcap::capture_state_name(7), "IDLE"), "FB-B2 name: capture_state_name 7 (D8: 4 is SAVING, 5.. IDLE)");
static_assert(str_is(ecco_fbcap::capture_state_name(8), "IDLE"), "FB-B2 name: capture_state_name 8 (D8: 4 is SAVING, 5.. IDLE)");
static_assert(str_is(txn_name(0), "UNKNOWN_REBOOT"), "FB-B2 name: txn_name 0");
static_assert(str_is(txn_name(1), "COMMITTED"), "FB-B2 name: txn_name 1");
static_assert(str_is(txn_name(2), "NOT_COMMITTED"), "FB-B2 name: txn_name 2");
static_assert(str_is(txn_name(3), "REFUSED_LATCHED"), "FB-B2 name: txn_name 3");
static_assert(str_is(txn_name(4), "\?"), "FB-B2 name: txn_name 4");
static_assert(str_is(txn_name(5), "\?"), "FB-B2 name: txn_name 5");
static_assert(str_is(txn_op_name(0), "-"), "FB-B2 name: txn_op_name 0");
static_assert(str_is(txn_op_name(1), "SAVE"), "FB-B2 name: txn_op_name 1");
static_assert(str_is(txn_op_name(2), "INVALIDATE"), "FB-B2 name: txn_op_name 2");
static_assert(str_is(txn_op_name(3), "REPLACE_CORRUPT"), "FB-B2 name: txn_op_name 3");
static_assert(str_is(txn_op_name(4), "-"), "FB-B2 name: txn_op_name 4");
static_assert(str_is(txn_op_name(5), "-"), "FB-B2 name: txn_op_name 5");
static_assert(str_is(key_name(0), "UNKNOWN_REBOOT"), "FB-B2 name: key_name 0");
static_assert(str_is(key_name(1), "COMMITTED"), "FB-B2 name: key_name 1");
static_assert(str_is(key_name(2), "NOT_COMMITTED"), "FB-B2 name: key_name 2");
static_assert(str_is(key_name(3), "NOT_ATTEMPTED"), "FB-B2 name: key_name 3");
static_assert(str_is(key_name(4), "\?"), "FB-B2 name: key_name 4");
static_assert(str_is(key_name(5), "\?"), "FB-B2 name: key_name 5");
static_assert(str_is(rb_name(0), "NOT_READ"), "FB-B2 name: rb_name 0");
static_assert(str_is(rb_name(1), "INTENDED"), "FB-B2 name: rb_name 1");
static_assert(str_is(rb_name(2), "PRIOR"), "FB-B2 name: rb_name 2");
static_assert(str_is(rb_name(3), "OTHER_BYTES"), "FB-B2 name: rb_name 3");
static_assert(str_is(rb_name(4), "ABSENT_UNEXPECTED"), "FB-B2 name: rb_name 4");
static_assert(str_is(rb_name(5), "WRONG_SIZE"), "FB-B2 name: rb_name 5");
static_assert(str_is(rb_name(6), "READ_ERROR"), "FB-B2 name: rb_name 6");
static_assert(str_is(rb_name(7), "UNAVAILABLE"), "FB-B2 name: rb_name 7");
static_assert(str_is(rb_name(8), "\?"), "FB-B2 name: rb_name 8");
static_assert(str_is(rb_name(9), "\?"), "FB-B2 name: rb_name 9");
static_assert(str_is(slot_label(0), ""), "FB-B2 name: slot_label 0");
static_assert(str_is(slot_label(1), "Failback record"), "FB-B2 name: slot_label 1");
static_assert(str_is(slot_label(2), "Free Power"), "FB-B2 name: slot_label 2");
static_assert(str_is(slot_label(3), "Dump to Grid"), "FB-B2 name: slot_label 3");
static_assert(str_is(slot_label(4), "Register 244 test"), "FB-B2 name: slot_label 4");
static_assert(str_is(slot_label(5), "Manual TOU"), "FB-B2 name: slot_label 5");
static_assert(str_is(slot_label(6), ""), "FB-B2 name: slot_label 6");
static_assert((echo_char_ok('A')) == 1, "FB-B2 value: echo_char_ok byte 65");
static_assert((hex_digit_ok('A')) == 1, "FB-B2 value: hex_digit_ok byte 65");
static_assert(((uint8_t) echo_fold('A')) == 97, "FB-B2 value: echo_fold byte 65");
static_assert((echo_char_ok('Z')) == 1, "FB-B2 value: echo_char_ok byte 90");
static_assert((hex_digit_ok('Z')) == 0, "FB-B2 value: hex_digit_ok byte 90");
static_assert(((uint8_t) echo_fold('Z')) == 122, "FB-B2 value: echo_fold byte 90");
static_assert((echo_char_ok('a')) == 1, "FB-B2 value: echo_char_ok byte 97");
static_assert((hex_digit_ok('a')) == 0, "FB-B2 value: hex_digit_ok byte 97");
static_assert(((uint8_t) echo_fold('a')) == 97, "FB-B2 value: echo_fold byte 97");
static_assert((echo_char_ok('z')) == 1, "FB-B2 value: echo_char_ok byte 122");
static_assert((hex_digit_ok('z')) == 0, "FB-B2 value: hex_digit_ok byte 122");
static_assert(((uint8_t) echo_fold('z')) == 122, "FB-B2 value: echo_fold byte 122");
static_assert((echo_char_ok('0')) == 1, "FB-B2 value: echo_char_ok byte 48");
static_assert((hex_digit_ok('0')) == 1, "FB-B2 value: hex_digit_ok byte 48");
static_assert(((uint8_t) echo_fold('0')) == 48, "FB-B2 value: echo_fold byte 48");
static_assert((echo_char_ok('9')) == 1, "FB-B2 value: echo_char_ok byte 57");
static_assert((hex_digit_ok('9')) == 1, "FB-B2 value: hex_digit_ok byte 57");
static_assert(((uint8_t) echo_fold('9')) == 57, "FB-B2 value: echo_fold byte 57");
static_assert((echo_char_ok('_')) == 1, "FB-B2 value: echo_char_ok byte 95");
static_assert((hex_digit_ok('_')) == 0, "FB-B2 value: hex_digit_ok byte 95");
static_assert(((uint8_t) echo_fold('_')) == 95, "FB-B2 value: echo_fold byte 95");
static_assert((echo_char_ok(' ')) == 0, "FB-B2 value: echo_char_ok byte 32");
static_assert((hex_digit_ok(' ')) == 0, "FB-B2 value: hex_digit_ok byte 32");
static_assert(((uint8_t) echo_fold(' ')) == 32, "FB-B2 value: echo_fold byte 32");
static_assert((echo_char_ok('-')) == 0, "FB-B2 value: echo_char_ok byte 45");
static_assert((hex_digit_ok('-')) == 0, "FB-B2 value: hex_digit_ok byte 45");
static_assert(((uint8_t) echo_fold('-')) == 45, "FB-B2 value: echo_fold byte 45");
static_assert((echo_char_ok('?')) == 0, "FB-B2 value: echo_char_ok byte 63");
static_assert((hex_digit_ok('?')) == 0, "FB-B2 value: hex_digit_ok byte 63");
static_assert(((uint8_t) echo_fold('?')) == 63, "FB-B2 value: echo_fold byte 63");
static_assert((echo_char_ok('@')) == 0, "FB-B2 value: echo_char_ok byte 64");
static_assert((hex_digit_ok('@')) == 0, "FB-B2 value: hex_digit_ok byte 64");
static_assert(((uint8_t) echo_fold('@')) == 64, "FB-B2 value: echo_fold byte 64");
static_assert((echo_char_ok('[')) == 0, "FB-B2 value: echo_char_ok byte 91");
static_assert((hex_digit_ok('[')) == 0, "FB-B2 value: hex_digit_ok byte 91");
static_assert(((uint8_t) echo_fold('[')) == 91, "FB-B2 value: echo_fold byte 91");
static_assert((echo_char_ok('`')) == 0, "FB-B2 value: echo_char_ok byte 96");
static_assert((hex_digit_ok('`')) == 0, "FB-B2 value: hex_digit_ok byte 96");
static_assert(((uint8_t) echo_fold('`')) == 96, "FB-B2 value: echo_fold byte 96");
static_assert((echo_char_ok('{')) == 0, "FB-B2 value: echo_char_ok byte 123");
static_assert((hex_digit_ok('{')) == 0, "FB-B2 value: hex_digit_ok byte 123");
static_assert(((uint8_t) echo_fold('{')) == 123, "FB-B2 value: echo_fold byte 123");
static_assert((echo_char_ok('/')) == 0, "FB-B2 value: echo_char_ok byte 47");
static_assert((hex_digit_ok('/')) == 0, "FB-B2 value: hex_digit_ok byte 47");
static_assert(((uint8_t) echo_fold('/')) == 47, "FB-B2 value: echo_fold byte 47");
static_assert((echo_char_ok(':')) == 0, "FB-B2 value: echo_char_ok byte 58");
static_assert((hex_digit_ok(':')) == 0, "FB-B2 value: hex_digit_ok byte 58");
static_assert(((uint8_t) echo_fold(':')) == 58, "FB-B2 value: echo_fold byte 58");
static_assert((echo_char_ok('F')) == 1, "FB-B2 value: echo_char_ok byte 70");
static_assert((hex_digit_ok('F')) == 1, "FB-B2 value: hex_digit_ok byte 70");
static_assert(((uint8_t) echo_fold('F')) == 102, "FB-B2 value: echo_fold byte 70");
static_assert((echo_char_ok('G')) == 1, "FB-B2 value: echo_char_ok byte 71");
static_assert((hex_digit_ok('G')) == 0, "FB-B2 value: hex_digit_ok byte 71");
static_assert(((uint8_t) echo_fold('G')) == 103, "FB-B2 value: echo_fold byte 71");
static_assert((echo_char_ok('f')) == 1, "FB-B2 value: echo_char_ok byte 102");
static_assert((hex_digit_ok('f')) == 0, "FB-B2 value: hex_digit_ok byte 102");
static_assert(((uint8_t) echo_fold('f')) == 102, "FB-B2 value: echo_fold byte 102");
static_assert((echo_char_ok('\n')) == 0, "FB-B2 value: echo_char_ok byte 10");
static_assert((hex_digit_ok('\n')) == 0, "FB-B2 value: hex_digit_ok byte 10");
static_assert(((uint8_t) echo_fold('\n')) == 10, "FB-B2 value: echo_fold byte 10");
static_assert((echo_char_ok('\0')) == 0, "FB-B2 value: echo_char_ok byte 0");
static_assert((hex_digit_ok('\0')) == 0, "FB-B2 value: hex_digit_ok byte 0");
static_assert(((uint8_t) echo_fold('\0')) == 0, "FB-B2 value: echo_fold byte 0");
static_assert((echo_char_ok('\377')) == 0, "FB-B2 value: echo_char_ok byte 255");
static_assert((hex_digit_ok('\377')) == 0, "FB-B2 value: hex_digit_ok byte 255");
static_assert(((uint8_t) echo_fold('\377')) == 255, "FB-B2 value: echo_fold byte 255");
static_assert((action_token("SAVE")) == 1, "FB-B2 value: action_token 'SAVE' (NUL-terminated)");
static_assert((action_token("SAVE", 4)) == 1, "FB-B2 value: action_token 'SAVE' (explicit length 4)");
static_assert((is_invalidate_action("SAVE", 4)) == 0, "FB-B2 value: is_invalidate_action 'SAVE'");
static_assert((is_invalidate_action("SAVE")) == 0, "FB-B2 value: is_invalidate_action 'SAVE' (NUL-terminated)");
static_assert((action_token("INVALIDATE")) == 2, "FB-B2 value: action_token 'INVALIDATE' (NUL-terminated)");
static_assert((action_token("INVALIDATE", 10)) == 2, "FB-B2 value: action_token 'INVALIDATE' (explicit length 10)");
static_assert((is_invalidate_action("INVALIDATE", 10)) == 1, "FB-B2 value: is_invalidate_action 'INVALIDATE'");
static_assert((is_invalidate_action("INVALIDATE")) == 1, "FB-B2 value: is_invalidate_action 'INVALIDATE' (NUL-terminated)");
static_assert((action_token("RESTORE")) == 3, "FB-B2 value: action_token 'RESTORE' (NUL-terminated)");
static_assert((action_token("RESTORE", 7)) == 3, "FB-B2 value: action_token 'RESTORE' (explicit length 7)");
static_assert((is_invalidate_action("RESTORE", 7)) == 0, "FB-B2 value: is_invalidate_action 'RESTORE'");
static_assert((is_invalidate_action("RESTORE")) == 0, "FB-B2 value: is_invalidate_action 'RESTORE' (NUL-terminated)");
static_assert((action_token("ACKNOWLEDGE")) == 4, "FB-B2 value: action_token 'ACKNOWLEDGE' (NUL-terminated)");
static_assert((action_token("ACKNOWLEDGE", 11)) == 4, "FB-B2 value: action_token 'ACKNOWLEDGE' (explicit length 11)");
static_assert((is_invalidate_action("ACKNOWLEDGE", 11)) == 0, "FB-B2 value: is_invalidate_action 'ACKNOWLEDGE'");
static_assert((is_invalidate_action("ACKNOWLEDGE")) == 0, "FB-B2 value: is_invalidate_action 'ACKNOWLEDGE' (NUL-terminated)");
static_assert((action_token("")) == 0, "FB-B2 value: action_token '' (NUL-terminated)");
static_assert((action_token("", 0)) == 0, "FB-B2 value: action_token '' (explicit length 0)");
static_assert((is_invalidate_action("", 0)) == 0, "FB-B2 value: is_invalidate_action ''");
static_assert((is_invalidate_action("")) == 0, "FB-B2 value: is_invalidate_action '' (NUL-terminated)");
static_assert((action_token("save")) == 0, "FB-B2 value: action_token 'save' (NUL-terminated)");
static_assert((action_token("save", 4)) == 0, "FB-B2 value: action_token 'save' (explicit length 4)");
static_assert((is_invalidate_action("save", 4)) == 0, "FB-B2 value: is_invalidate_action 'save'");
static_assert((is_invalidate_action("save")) == 0, "FB-B2 value: is_invalidate_action 'save' (NUL-terminated)");
static_assert((action_token("Save")) == 0, "FB-B2 value: action_token 'Save' (NUL-terminated)");
static_assert((action_token("Save", 4)) == 0, "FB-B2 value: action_token 'Save' (explicit length 4)");
static_assert((is_invalidate_action("Save", 4)) == 0, "FB-B2 value: is_invalidate_action 'Save'");
static_assert((is_invalidate_action("Save")) == 0, "FB-B2 value: is_invalidate_action 'Save' (NUL-terminated)");
static_assert((action_token("SAVE ")) == 0, "FB-B2 value: action_token 'SAVE ' (NUL-terminated)");
static_assert((action_token("SAVE ", 5)) == 0, "FB-B2 value: action_token 'SAVE ' (explicit length 5)");
static_assert((is_invalidate_action("SAVE ", 5)) == 0, "FB-B2 value: is_invalidate_action 'SAVE '");
static_assert((is_invalidate_action("SAVE ")) == 0, "FB-B2 value: is_invalidate_action 'SAVE ' (NUL-terminated)");
static_assert((action_token(" SAVE")) == 0, "FB-B2 value: action_token ' SAVE' (NUL-terminated)");
static_assert((action_token(" SAVE", 5)) == 0, "FB-B2 value: action_token ' SAVE' (explicit length 5)");
static_assert((is_invalidate_action(" SAVE", 5)) == 0, "FB-B2 value: is_invalidate_action ' SAVE'");
static_assert((is_invalidate_action(" SAVE")) == 0, "FB-B2 value: is_invalidate_action ' SAVE' (NUL-terminated)");
static_assert((action_token("SAVE\n")) == 0, "FB-B2 value: action_token 'SAVE~0A' (NUL-terminated)");
static_assert((action_token("SAVE\n", 5)) == 0, "FB-B2 value: action_token 'SAVE~0A' (explicit length 5)");
static_assert((is_invalidate_action("SAVE\n", 5)) == 0, "FB-B2 value: is_invalidate_action 'SAVE~0A'");
static_assert((is_invalidate_action("SAVE\n")) == 0, "FB-B2 value: is_invalidate_action 'SAVE~0A' (NUL-terminated)");
static_assert((action_token("SAVEX")) == 0, "FB-B2 value: action_token 'SAVEX' (NUL-terminated)");
static_assert((action_token("SAVEX", 5)) == 0, "FB-B2 value: action_token 'SAVEX' (explicit length 5)");
static_assert((is_invalidate_action("SAVEX", 5)) == 0, "FB-B2 value: is_invalidate_action 'SAVEX'");
static_assert((is_invalidate_action("SAVEX")) == 0, "FB-B2 value: is_invalidate_action 'SAVEX' (NUL-terminated)");
static_assert((action_token("SAV")) == 0, "FB-B2 value: action_token 'SAV' (NUL-terminated)");
static_assert((action_token("SAV", 3)) == 0, "FB-B2 value: action_token 'SAV' (explicit length 3)");
static_assert((is_invalidate_action("SAV", 3)) == 0, "FB-B2 value: is_invalidate_action 'SAV'");
static_assert((is_invalidate_action("SAV")) == 0, "FB-B2 value: is_invalidate_action 'SAV' (NUL-terminated)");
static_assert((action_token("S")) == 0, "FB-B2 value: action_token 'S' (NUL-terminated)");
static_assert((action_token("S", 1)) == 0, "FB-B2 value: action_token 'S' (explicit length 1)");
static_assert((is_invalidate_action("S", 1)) == 0, "FB-B2 value: is_invalidate_action 'S'");
static_assert((is_invalidate_action("S")) == 0, "FB-B2 value: is_invalidate_action 'S' (NUL-terminated)");
static_assert((action_token("INVALIDATE ")) == 0, "FB-B2 value: action_token 'INVALIDATE ' (NUL-terminated)");
static_assert((action_token("INVALIDATE ", 11)) == 0, "FB-B2 value: action_token 'INVALIDATE ' (explicit length 11)");
static_assert((is_invalidate_action("INVALIDATE ", 11)) == 0, "FB-B2 value: is_invalidate_action 'INVALIDATE '");
static_assert((is_invalidate_action("INVALIDATE ")) == 0, "FB-B2 value: is_invalidate_action 'INVALIDATE ' (NUL-terminated)");
static_assert((action_token("invalidate")) == 0, "FB-B2 value: action_token 'invalidate' (NUL-terminated)");
static_assert((action_token("invalidate", 10)) == 0, "FB-B2 value: action_token 'invalidate' (explicit length 10)");
static_assert((is_invalidate_action("invalidate", 10)) == 0, "FB-B2 value: is_invalidate_action 'invalidate'");
static_assert((is_invalidate_action("invalidate")) == 0, "FB-B2 value: is_invalidate_action 'invalidate' (NUL-terminated)");
static_assert((action_token("INVALID")) == 0, "FB-B2 value: action_token 'INVALID' (NUL-terminated)");
static_assert((action_token("INVALID", 7)) == 0, "FB-B2 value: action_token 'INVALID' (explicit length 7)");
static_assert((is_invalidate_action("INVALID", 7)) == 0, "FB-B2 value: is_invalidate_action 'INVALID'");
static_assert((is_invalidate_action("INVALID")) == 0, "FB-B2 value: is_invalidate_action 'INVALID' (NUL-terminated)");
static_assert((action_token("INVALIDATEX")) == 0, "FB-B2 value: action_token 'INVALIDATEX' (NUL-terminated)");
static_assert((action_token("INVALIDATEX", 11)) == 0, "FB-B2 value: action_token 'INVALIDATEX' (explicit length 11)");
static_assert((is_invalidate_action("INVALIDATEX", 11)) == 0, "FB-B2 value: is_invalidate_action 'INVALIDATEX'");
static_assert((is_invalidate_action("INVALIDATEX")) == 0, "FB-B2 value: is_invalidate_action 'INVALIDATEX' (NUL-terminated)");
static_assert((action_token("RESTORE ")) == 0, "FB-B2 value: action_token 'RESTORE ' (NUL-terminated)");
static_assert((action_token("RESTORE ", 8)) == 0, "FB-B2 value: action_token 'RESTORE ' (explicit length 8)");
static_assert((is_invalidate_action("RESTORE ", 8)) == 0, "FB-B2 value: is_invalidate_action 'RESTORE '");
static_assert((is_invalidate_action("RESTORE ")) == 0, "FB-B2 value: is_invalidate_action 'RESTORE ' (NUL-terminated)");
static_assert((action_token("restore")) == 0, "FB-B2 value: action_token 'restore' (NUL-terminated)");
static_assert((action_token("restore", 7)) == 0, "FB-B2 value: action_token 'restore' (explicit length 7)");
static_assert((is_invalidate_action("restore", 7)) == 0, "FB-B2 value: is_invalidate_action 'restore'");
static_assert((is_invalidate_action("restore")) == 0, "FB-B2 value: is_invalidate_action 'restore' (NUL-terminated)");
static_assert((action_token("ACKNOWLEDGE\n")) == 0, "FB-B2 value: action_token 'ACKNOWLEDGE~0A' (NUL-terminated)");
static_assert((action_token("ACKNOWLEDGE\n", 12)) == 0, "FB-B2 value: action_token 'ACKNOWLEDGE~0A' (explicit length 12)");
static_assert((is_invalidate_action("ACKNOWLEDGE\n", 12)) == 0, "FB-B2 value: is_invalidate_action 'ACKNOWLEDGE~0A'");
static_assert((is_invalidate_action("ACKNOWLEDGE\n")) == 0, "FB-B2 value: is_invalidate_action 'ACKNOWLEDGE~0A' (NUL-terminated)");
static_assert((action_token("acknowledge")) == 0, "FB-B2 value: action_token 'acknowledge' (NUL-terminated)");
static_assert((action_token("acknowledge", 11)) == 0, "FB-B2 value: action_token 'acknowledge' (explicit length 11)");
static_assert((is_invalidate_action("acknowledge", 11)) == 0, "FB-B2 value: is_invalidate_action 'acknowledge'");
static_assert((is_invalidate_action("acknowledge")) == 0, "FB-B2 value: is_invalidate_action 'acknowledge' (NUL-terminated)");
static_assert((action_token("CAPTURE")) == 0, "FB-B2 value: action_token 'CAPTURE' (NUL-terminated)");
static_assert((action_token("CAPTURE", 7)) == 0, "FB-B2 value: action_token 'CAPTURE' (explicit length 7)");
static_assert((is_invalidate_action("CAPTURE", 7)) == 0, "FB-B2 value: is_invalidate_action 'CAPTURE'");
static_assert((is_invalidate_action("CAPTURE")) == 0, "FB-B2 value: is_invalidate_action 'CAPTURE' (NUL-terminated)");
static_assert((action_token("APPLY")) == 0, "FB-B2 value: action_token 'APPLY' (NUL-terminated)");
static_assert((action_token("APPLY", 5)) == 0, "FB-B2 value: action_token 'APPLY' (explicit length 5)");
static_assert((is_invalidate_action("APPLY", 5)) == 0, "FB-B2 value: is_invalidate_action 'APPLY'");
static_assert((is_invalidate_action("APPLY")) == 0, "FB-B2 value: is_invalidate_action 'APPLY' (NUL-terminated)");
static_assert((action_token("RETRY_APPLY")) == 0, "FB-B2 value: action_token 'RETRY_APPLY' (NUL-terminated)");
static_assert((action_token("RETRY_APPLY", 11)) == 0, "FB-B2 value: action_token 'RETRY_APPLY' (explicit length 11)");
static_assert((is_invalidate_action("RETRY_APPLY", 11)) == 0, "FB-B2 value: is_invalidate_action 'RETRY_APPLY'");
static_assert((is_invalidate_action("RETRY_APPLY")) == 0, "FB-B2 value: is_invalidate_action 'RETRY_APPLY' (NUL-terminated)");
static_assert((action_token("ACCEPT_LIVE")) == 0, "FB-B2 value: action_token 'ACCEPT_LIVE' (NUL-terminated)");
static_assert((action_token("ACCEPT_LIVE", 11)) == 0, "FB-B2 value: action_token 'ACCEPT_LIVE' (explicit length 11)");
static_assert((is_invalidate_action("ACCEPT_LIVE", 11)) == 0, "FB-B2 value: is_invalidate_action 'ACCEPT_LIVE'");
static_assert((is_invalidate_action("ACCEPT_LIVE")) == 0, "FB-B2 value: is_invalidate_action 'ACCEPT_LIVE' (NUL-terminated)");
static_assert((action_token("PROVISION")) == 0, "FB-B2 value: action_token 'PROVISION' (NUL-terminated)");
static_assert((action_token("PROVISION", 9)) == 0, "FB-B2 value: action_token 'PROVISION' (explicit length 9)");
static_assert((is_invalidate_action("PROVISION", 9)) == 0, "FB-B2 value: is_invalidate_action 'PROVISION'");
static_assert((is_invalidate_action("PROVISION")) == 0, "FB-B2 value: is_invalidate_action 'PROVISION' (NUL-terminated)");
static_assert((action_token("XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX")) == 0, "FB-B2 value: action_token 'XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX' (NUL-terminated)");
static_assert((action_token("XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX", 40)) == 0, "FB-B2 value: action_token 'XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX' (explicit length 40)");
static_assert((is_invalidate_action("XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX", 40)) == 0, "FB-B2 value: is_invalidate_action 'XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX'");
static_assert((is_invalidate_action("XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX")) == 0, "FB-B2 value: is_invalidate_action 'XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX' (NUL-terminated)");
static_assert((action_token("SAVE\000x")) == 1, "FB-B2 value: action_token 'SAVE~00x' (NUL-terminated)");
static_assert((action_token("SAVE\000x", 6)) == 0, "FB-B2 value: action_token 'SAVE~00x' (explicit length 6)");
static_assert((is_invalidate_action("SAVE\000x", 6)) == 0, "FB-B2 value: is_invalidate_action 'SAVE~00x'");
static_assert((is_invalidate_action("SAVE\000x")) == 0, "FB-B2 value: is_invalidate_action 'SAVE~00x' (NUL-terminated)");
static_assert((action_token("INVALIDATE\000")) == 2, "FB-B2 value: action_token 'INVALIDATE~00' (NUL-terminated)");
static_assert((action_token("INVALIDATE\000", 11)) == 0, "FB-B2 value: action_token 'INVALIDATE~00' (explicit length 11)");
static_assert((is_invalidate_action("INVALIDATE\000", 11)) == 0, "FB-B2 value: is_invalidate_action 'INVALIDATE~00'");
static_assert((is_invalidate_action("INVALIDATE\000")) == 1, "FB-B2 value: is_invalidate_action 'INVALIDATE~00' (NUL-terminated)");
static_assert((action_token("RESTORE\000RESTORE")) == 3, "FB-B2 value: action_token 'RESTORE~00RESTORE' (NUL-terminated)");
static_assert((action_token("RESTORE\000RESTORE", 15)) == 0, "FB-B2 value: action_token 'RESTORE~00RESTORE' (explicit length 15)");
static_assert((is_invalidate_action("RESTORE\000RESTORE", 15)) == 0, "FB-B2 value: is_invalidate_action 'RESTORE~00RESTORE'");
static_assert((is_invalidate_action("RESTORE\000RESTORE")) == 0, "FB-B2 value: is_invalidate_action 'RESTORE~00RESTORE' (NUL-terminated)");
static_assert((action_token(nullptr)) == 0, "FB-B2 value: action_token: a null action");
static_assert((action_token(nullptr, 4)) == 0, "FB-B2 value: action_token: a null action with a length");
static_assert((is_invalidate_action(nullptr)) == 0, "FB-B2 value: is_invalidate_action: a null action");
static_assert((action_token("SAVEX", 4)) == 1, "FB-B2 value: action_token: a shorter explicit length cuts the token (SAVEX, 4)");
static_assert((action_token("SAVE", 5)) == 0, "FB-B2 value: action_token: a longer explicit length never matches (SAVE, 5 reads the NUL)");
static_assert((bounded_len("", 0)) == 0, "FB-B2 value: bounded_len '' limit 0");
static_assert((bounded_len("", 5)) == 0, "FB-B2 value: bounded_len '' limit 5");
static_assert((bounded_len("abc", 2)) == 3, "FB-B2 value: bounded_len 'abc' limit 2");
static_assert((bounded_len("abc", 3)) == 3, "FB-B2 value: bounded_len 'abc' limit 3");
static_assert((bounded_len("abc", 4)) == 3, "FB-B2 value: bounded_len 'abc' limit 4");
static_assert((bounded_len("abcdef", 3)) == 4, "FB-B2 value: bounded_len 'abcdef' limit 3");
static_assert((bounded_len("a\000b", 5)) == 1, "FB-B2 value: bounded_len 'a~00b' limit 5");
static_assert((bounded_len("0123456789ABCDEF", 16)) == 16, "FB-B2 value: bounded_len '0123456789ABCDEF' limit 16");
static_assert((bounded_len("0123456789ABCDEF0", 16)) == 17, "FB-B2 value: bounded_len '0123456789ABCDEF0' limit 16");
static_assert((bounded_len(nullptr, 9)) == 0, "FB-B2 value: bounded_len: a null pointer is empty");
static_assert((exact("SAVE", 4, "SAVE")) == 1, "FB-B2 value: exact: equal literal");
static_assert((exact("SAVEX", 4, "SAVEX")) == 0, "FB-B2 value: exact: a prefix is not exact");
static_assert((exact("SAVE", 3, "SAVE")) == 0, "FB-B2 value: exact: a longer length is not exact");
static_assert((exact("SAVF", 4, "SAVE")) == 0, "FB-B2 value: exact: a different character");
static_assert((exact(nullptr, 4, "SAVE")) == 0, "FB-B2 value: exact: a null pointer");
static_assert((starts_with("SAVE x", 6, "SAVE ")) == 1, "FB-B2 value: starts_with: a longer string");
static_assert((starts_with("SAVE", 4, "SAVE ")) == 0, "FB-B2 value: starts_with: too short");
static_assert((starts_with("save x", 6, "SAVE ")) == 0, "FB-B2 value: starts_with: another verb");
static_assert(([]{ const TextBuf s = fx_target(0, 0x123456789ABCDEFULL); return is_hex16(s.c_str(), s.size()); }()) == 1, "FB-B2 value: is_hex16 target kind 0 id 123456789ABCDEF");
static_assert(([]{ const TextBuf s = fx_target(0, 0x123456789ABCDEFULL); return parse_hex16(s.c_str(), s.size()); }()) == 0x123456789ABCDEFULL, "FB-B2 value: parse_hex16 target kind 0 id 123456789ABCDEF");
static_assert(([]{ const TextBuf s = fx_target(0, 0x123456789ABCDEFULL); return is_hex16(s.c_str()); }()) == 1, "FB-B2 value: is_hex16 target kind 0 id 123456789ABCDEF (NUL-terminated)");
static_assert(([]{ const TextBuf s = fx_target(1, 0x123456789ABCDEFULL); return is_hex16(s.c_str(), s.size()); }()) == 0, "FB-B2 value: is_hex16 target kind 1 id 123456789ABCDEF");
static_assert(([]{ const TextBuf s = fx_target(1, 0x123456789ABCDEFULL); return parse_hex16(s.c_str(), s.size()); }()) == 0, "FB-B2 value: parse_hex16 target kind 1 id 123456789ABCDEF");
static_assert(([]{ const TextBuf s = fx_target(1, 0x123456789ABCDEFULL); return is_hex16(s.c_str()); }()) == 0, "FB-B2 value: is_hex16 target kind 1 id 123456789ABCDEF (NUL-terminated)");
static_assert(([]{ const TextBuf s = fx_target(2, 0x123456789ABCDEFULL); return is_hex16(s.c_str(), s.size()); }()) == 0, "FB-B2 value: is_hex16 target kind 2 id 123456789ABCDEF");
static_assert(([]{ const TextBuf s = fx_target(2, 0x123456789ABCDEFULL); return parse_hex16(s.c_str(), s.size()); }()) == 0, "FB-B2 value: parse_hex16 target kind 2 id 123456789ABCDEF");
static_assert(([]{ const TextBuf s = fx_target(2, 0x123456789ABCDEFULL); return is_hex16(s.c_str()); }()) == 0, "FB-B2 value: is_hex16 target kind 2 id 123456789ABCDEF (NUL-terminated)");
static_assert(([]{ const TextBuf s = fx_target(3, 0x123456789ABCDEFULL); return is_hex16(s.c_str(), s.size()); }()) == 0, "FB-B2 value: is_hex16 target kind 3 id 123456789ABCDEF");
static_assert(([]{ const TextBuf s = fx_target(3, 0x123456789ABCDEFULL); return parse_hex16(s.c_str(), s.size()); }()) == 0, "FB-B2 value: parse_hex16 target kind 3 id 123456789ABCDEF");
static_assert(([]{ const TextBuf s = fx_target(3, 0x123456789ABCDEFULL); return is_hex16(s.c_str()); }()) == 0, "FB-B2 value: is_hex16 target kind 3 id 123456789ABCDEF (NUL-terminated)");
static_assert(([]{ const TextBuf s = fx_target(4, 0x123456789ABCDEFULL); return is_hex16(s.c_str(), s.size()); }()) == 1, "FB-B2 value: is_hex16 target kind 4 id 123456789ABCDEF");
static_assert(([]{ const TextBuf s = fx_target(4, 0x123456789ABCDEFULL); return parse_hex16(s.c_str(), s.size()); }()) == 0x123456789ABCDEEULL, "FB-B2 value: parse_hex16 target kind 4 id 123456789ABCDEF");
static_assert(([]{ const TextBuf s = fx_target(4, 0x123456789ABCDEFULL); return is_hex16(s.c_str()); }()) == 1, "FB-B2 value: is_hex16 target kind 4 id 123456789ABCDEF (NUL-terminated)");
static_assert(([]{ const TextBuf s = fx_target(5, 0x123456789ABCDEFULL); return is_hex16(s.c_str(), s.size()); }()) == 0, "FB-B2 value: is_hex16 target kind 5 id 123456789ABCDEF");
static_assert(([]{ const TextBuf s = fx_target(5, 0x123456789ABCDEFULL); return parse_hex16(s.c_str(), s.size()); }()) == 0, "FB-B2 value: parse_hex16 target kind 5 id 123456789ABCDEF");
static_assert(([]{ const TextBuf s = fx_target(5, 0x123456789ABCDEFULL); return is_hex16(s.c_str()); }()) == 0, "FB-B2 value: is_hex16 target kind 5 id 123456789ABCDEF (NUL-terminated)");
static_assert(([]{ const TextBuf s = fx_target(6, 0x123456789ABCDEFULL); return is_hex16(s.c_str(), s.size()); }()) == 0, "FB-B2 value: is_hex16 target kind 6 id 123456789ABCDEF");
static_assert(([]{ const TextBuf s = fx_target(6, 0x123456789ABCDEFULL); return parse_hex16(s.c_str(), s.size()); }()) == 0, "FB-B2 value: parse_hex16 target kind 6 id 123456789ABCDEF");
static_assert(([]{ const TextBuf s = fx_target(6, 0x123456789ABCDEFULL); return is_hex16(s.c_str()); }()) == 0, "FB-B2 value: is_hex16 target kind 6 id 123456789ABCDEF (NUL-terminated)");
static_assert(([]{ const TextBuf s = fx_target(7, 0x123456789ABCDEFULL); return is_hex16(s.c_str(), s.size()); }()) == 0, "FB-B2 value: is_hex16 target kind 7 id 123456789ABCDEF");
static_assert(([]{ const TextBuf s = fx_target(7, 0x123456789ABCDEFULL); return parse_hex16(s.c_str(), s.size()); }()) == 0, "FB-B2 value: parse_hex16 target kind 7 id 123456789ABCDEF");
static_assert(([]{ const TextBuf s = fx_target(7, 0x123456789ABCDEFULL); return is_hex16(s.c_str()); }()) == 0, "FB-B2 value: is_hex16 target kind 7 id 123456789ABCDEF (NUL-terminated)");
static_assert(([]{ const TextBuf s = fx_target(8, 0x123456789ABCDEFULL); return is_hex16(s.c_str(), s.size()); }()) == 0, "FB-B2 value: is_hex16 target kind 8 id 123456789ABCDEF");
static_assert(([]{ const TextBuf s = fx_target(8, 0x123456789ABCDEFULL); return parse_hex16(s.c_str(), s.size()); }()) == 0, "FB-B2 value: parse_hex16 target kind 8 id 123456789ABCDEF");
static_assert(([]{ const TextBuf s = fx_target(8, 0x123456789ABCDEFULL); return is_hex16(s.c_str()); }()) == 0, "FB-B2 value: is_hex16 target kind 8 id 123456789ABCDEF (NUL-terminated)");
static_assert(([]{ const TextBuf s = fx_target(9, 0x123456789ABCDEFULL); return is_hex16(s.c_str(), s.size()); }()) == 0, "FB-B2 value: is_hex16 target kind 9 id 123456789ABCDEF");
static_assert(([]{ const TextBuf s = fx_target(9, 0x123456789ABCDEFULL); return parse_hex16(s.c_str(), s.size()); }()) == 0, "FB-B2 value: parse_hex16 target kind 9 id 123456789ABCDEF");
static_assert(([]{ const TextBuf s = fx_target(9, 0x123456789ABCDEFULL); return is_hex16(s.c_str()); }()) == 0, "FB-B2 value: is_hex16 target kind 9 id 123456789ABCDEF (NUL-terminated)");
static_assert(([]{ const TextBuf s = fx_target(10, 0x123456789ABCDEFULL); return is_hex16(s.c_str(), s.size()); }()) == 0, "FB-B2 value: is_hex16 target kind 10 id 123456789ABCDEF");
static_assert(([]{ const TextBuf s = fx_target(10, 0x123456789ABCDEFULL); return parse_hex16(s.c_str(), s.size()); }()) == 0, "FB-B2 value: parse_hex16 target kind 10 id 123456789ABCDEF");
static_assert(([]{ const TextBuf s = fx_target(10, 0x123456789ABCDEFULL); return is_hex16(s.c_str()); }()) == 0, "FB-B2 value: is_hex16 target kind 10 id 123456789ABCDEF (NUL-terminated)");
static_assert(([]{ const TextBuf s = fx_target(11, 0x123456789ABCDEFULL); return is_hex16(s.c_str(), s.size()); }()) == 1, "FB-B2 value: is_hex16 target kind 11 id 123456789ABCDEF");
static_assert(([]{ const TextBuf s = fx_target(11, 0x123456789ABCDEFULL); return parse_hex16(s.c_str(), s.size()); }()) == 0x8123456789ABCDEFULL, "FB-B2 value: parse_hex16 target kind 11 id 123456789ABCDEF");
static_assert(([]{ const TextBuf s = fx_target(11, 0x123456789ABCDEFULL); return is_hex16(s.c_str()); }()) == 1, "FB-B2 value: is_hex16 target kind 11 id 123456789ABCDEF (NUL-terminated)");
static_assert(([]{ const TextBuf s = fx_target(12, 0x123456789ABCDEFULL); return is_hex16(s.c_str(), s.size()); }()) == 1, "FB-B2 value: is_hex16 target kind 12 id 123456789ABCDEF");
static_assert(([]{ const TextBuf s = fx_target(12, 0x123456789ABCDEFULL); return parse_hex16(s.c_str(), s.size()); }()) == 0x123456689ABCDEFULL, "FB-B2 value: parse_hex16 target kind 12 id 123456789ABCDEF");
static_assert(([]{ const TextBuf s = fx_target(12, 0x123456789ABCDEFULL); return is_hex16(s.c_str()); }()) == 1, "FB-B2 value: is_hex16 target kind 12 id 123456789ABCDEF (NUL-terminated)");
static_assert(([]{ const TextBuf s = fx_target(13, 0x123456789ABCDEFULL); return is_hex16(s.c_str(), s.size()); }()) == 1, "FB-B2 value: is_hex16 target kind 13 id 123456789ABCDEF");
static_assert(([]{ const TextBuf s = fx_target(13, 0x123456789ABCDEFULL); return parse_hex16(s.c_str(), s.size()); }()) == 0xFEDCBA9889ABCDEFULL, "FB-B2 value: parse_hex16 target kind 13 id 123456789ABCDEF");
static_assert(([]{ const TextBuf s = fx_target(13, 0x123456789ABCDEFULL); return is_hex16(s.c_str()); }()) == 1, "FB-B2 value: is_hex16 target kind 13 id 123456789ABCDEF (NUL-terminated)");
static_assert(([]{ const TextBuf s = fx_target(14, 0x123456789ABCDEFULL); return is_hex16(s.c_str(), s.size()); }()) == 1, "FB-B2 value: is_hex16 target kind 14 id 123456789ABCDEF");
static_assert(([]{ const TextBuf s = fx_target(14, 0x123456789ABCDEFULL); return parse_hex16(s.c_str(), s.size()); }()) == 0x123456776543210ULL, "FB-B2 value: parse_hex16 target kind 14 id 123456789ABCDEF");
static_assert(([]{ const TextBuf s = fx_target(14, 0x123456789ABCDEFULL); return is_hex16(s.c_str()); }()) == 1, "FB-B2 value: is_hex16 target kind 14 id 123456789ABCDEF (NUL-terminated)");
static_assert(([]{ const TextBuf s = fx_target(0, 0x0ULL); return is_hex16(s.c_str(), s.size()); }()) == 1, "FB-B2 value: is_hex16 target kind 0 id 0");
static_assert(([]{ const TextBuf s = fx_target(0, 0x0ULL); return parse_hex16(s.c_str(), s.size()); }()) == 0, "FB-B2 value: parse_hex16 target kind 0 id 0");
static_assert(([]{ const TextBuf s = fx_target(0, 0x0ULL); return is_hex16(s.c_str()); }()) == 1, "FB-B2 value: is_hex16 target kind 0 id 0 (NUL-terminated)");
static_assert(([]{ const TextBuf s = fx_target(1, 0x0ULL); return is_hex16(s.c_str(), s.size()); }()) == 1, "FB-B2 value: is_hex16 target kind 1 id 0");
static_assert(([]{ const TextBuf s = fx_target(1, 0x0ULL); return parse_hex16(s.c_str(), s.size()); }()) == 0, "FB-B2 value: parse_hex16 target kind 1 id 0");
static_assert(([]{ const TextBuf s = fx_target(1, 0x0ULL); return is_hex16(s.c_str()); }()) == 1, "FB-B2 value: is_hex16 target kind 1 id 0 (NUL-terminated)");
static_assert(([]{ const TextBuf s = fx_target(2, 0x0ULL); return is_hex16(s.c_str(), s.size()); }()) == 0, "FB-B2 value: is_hex16 target kind 2 id 0");
static_assert(([]{ const TextBuf s = fx_target(2, 0x0ULL); return parse_hex16(s.c_str(), s.size()); }()) == 0, "FB-B2 value: parse_hex16 target kind 2 id 0");
static_assert(([]{ const TextBuf s = fx_target(2, 0x0ULL); return is_hex16(s.c_str()); }()) == 0, "FB-B2 value: is_hex16 target kind 2 id 0 (NUL-terminated)");
static_assert(([]{ const TextBuf s = fx_target(3, 0x0ULL); return is_hex16(s.c_str(), s.size()); }()) == 0, "FB-B2 value: is_hex16 target kind 3 id 0");
static_assert(([]{ const TextBuf s = fx_target(3, 0x0ULL); return parse_hex16(s.c_str(), s.size()); }()) == 0, "FB-B2 value: parse_hex16 target kind 3 id 0");
static_assert(([]{ const TextBuf s = fx_target(3, 0x0ULL); return is_hex16(s.c_str()); }()) == 0, "FB-B2 value: is_hex16 target kind 3 id 0 (NUL-terminated)");
static_assert(([]{ const TextBuf s = fx_target(4, 0x0ULL); return is_hex16(s.c_str(), s.size()); }()) == 1, "FB-B2 value: is_hex16 target kind 4 id 0");
static_assert(([]{ const TextBuf s = fx_target(4, 0x0ULL); return parse_hex16(s.c_str(), s.size()); }()) == 1, "FB-B2 value: parse_hex16 target kind 4 id 0");
static_assert(([]{ const TextBuf s = fx_target(4, 0x0ULL); return is_hex16(s.c_str()); }()) == 1, "FB-B2 value: is_hex16 target kind 4 id 0 (NUL-terminated)");
static_assert(([]{ const TextBuf s = fx_target(5, 0x0ULL); return is_hex16(s.c_str(), s.size()); }()) == 0, "FB-B2 value: is_hex16 target kind 5 id 0");
static_assert(([]{ const TextBuf s = fx_target(5, 0x0ULL); return parse_hex16(s.c_str(), s.size()); }()) == 0, "FB-B2 value: parse_hex16 target kind 5 id 0");
static_assert(([]{ const TextBuf s = fx_target(5, 0x0ULL); return is_hex16(s.c_str()); }()) == 0, "FB-B2 value: is_hex16 target kind 5 id 0 (NUL-terminated)");
static_assert(([]{ const TextBuf s = fx_target(6, 0x0ULL); return is_hex16(s.c_str(), s.size()); }()) == 0, "FB-B2 value: is_hex16 target kind 6 id 0");
static_assert(([]{ const TextBuf s = fx_target(6, 0x0ULL); return parse_hex16(s.c_str(), s.size()); }()) == 0, "FB-B2 value: parse_hex16 target kind 6 id 0");
static_assert(([]{ const TextBuf s = fx_target(6, 0x0ULL); return is_hex16(s.c_str()); }()) == 0, "FB-B2 value: is_hex16 target kind 6 id 0 (NUL-terminated)");
static_assert(([]{ const TextBuf s = fx_target(7, 0x0ULL); return is_hex16(s.c_str(), s.size()); }()) == 0, "FB-B2 value: is_hex16 target kind 7 id 0");
static_assert(([]{ const TextBuf s = fx_target(7, 0x0ULL); return parse_hex16(s.c_str(), s.size()); }()) == 0, "FB-B2 value: parse_hex16 target kind 7 id 0");
static_assert(([]{ const TextBuf s = fx_target(7, 0x0ULL); return is_hex16(s.c_str()); }()) == 0, "FB-B2 value: is_hex16 target kind 7 id 0 (NUL-terminated)");
static_assert(([]{ const TextBuf s = fx_target(8, 0x0ULL); return is_hex16(s.c_str(), s.size()); }()) == 0, "FB-B2 value: is_hex16 target kind 8 id 0");
static_assert(([]{ const TextBuf s = fx_target(8, 0x0ULL); return parse_hex16(s.c_str(), s.size()); }()) == 0, "FB-B2 value: parse_hex16 target kind 8 id 0");
static_assert(([]{ const TextBuf s = fx_target(8, 0x0ULL); return is_hex16(s.c_str()); }()) == 0, "FB-B2 value: is_hex16 target kind 8 id 0 (NUL-terminated)");
static_assert(([]{ const TextBuf s = fx_target(9, 0x0ULL); return is_hex16(s.c_str(), s.size()); }()) == 0, "FB-B2 value: is_hex16 target kind 9 id 0");
static_assert(([]{ const TextBuf s = fx_target(9, 0x0ULL); return parse_hex16(s.c_str(), s.size()); }()) == 0, "FB-B2 value: parse_hex16 target kind 9 id 0");
static_assert(([]{ const TextBuf s = fx_target(9, 0x0ULL); return is_hex16(s.c_str()); }()) == 0, "FB-B2 value: is_hex16 target kind 9 id 0 (NUL-terminated)");
static_assert(([]{ const TextBuf s = fx_target(10, 0x0ULL); return is_hex16(s.c_str(), s.size()); }()) == 0, "FB-B2 value: is_hex16 target kind 10 id 0");
static_assert(([]{ const TextBuf s = fx_target(10, 0x0ULL); return parse_hex16(s.c_str(), s.size()); }()) == 0, "FB-B2 value: parse_hex16 target kind 10 id 0");
static_assert(([]{ const TextBuf s = fx_target(10, 0x0ULL); return is_hex16(s.c_str()); }()) == 0, "FB-B2 value: is_hex16 target kind 10 id 0 (NUL-terminated)");
static_assert(([]{ const TextBuf s = fx_target(11, 0x0ULL); return is_hex16(s.c_str(), s.size()); }()) == 1, "FB-B2 value: is_hex16 target kind 11 id 0");
static_assert(([]{ const TextBuf s = fx_target(11, 0x0ULL); return parse_hex16(s.c_str(), s.size()); }()) == 0x8000000000000000ULL, "FB-B2 value: parse_hex16 target kind 11 id 0");
static_assert(([]{ const TextBuf s = fx_target(11, 0x0ULL); return is_hex16(s.c_str()); }()) == 1, "FB-B2 value: is_hex16 target kind 11 id 0 (NUL-terminated)");
static_assert(([]{ const TextBuf s = fx_target(12, 0x0ULL); return is_hex16(s.c_str(), s.size()); }()) == 1, "FB-B2 value: is_hex16 target kind 12 id 0");
static_assert(([]{ const TextBuf s = fx_target(12, 0x0ULL); return parse_hex16(s.c_str(), s.size()); }()) == 0x100000000ULL, "FB-B2 value: parse_hex16 target kind 12 id 0");
static_assert(([]{ const TextBuf s = fx_target(12, 0x0ULL); return is_hex16(s.c_str()); }()) == 1, "FB-B2 value: is_hex16 target kind 12 id 0 (NUL-terminated)");
static_assert(([]{ const TextBuf s = fx_target(13, 0x0ULL); return is_hex16(s.c_str(), s.size()); }()) == 1, "FB-B2 value: is_hex16 target kind 13 id 0");
static_assert(([]{ const TextBuf s = fx_target(13, 0x0ULL); return parse_hex16(s.c_str(), s.size()); }()) == 0xFFFFFFFF00000000ULL, "FB-B2 value: parse_hex16 target kind 13 id 0");
static_assert(([]{ const TextBuf s = fx_target(13, 0x0ULL); return is_hex16(s.c_str()); }()) == 1, "FB-B2 value: is_hex16 target kind 13 id 0 (NUL-terminated)");
static_assert(([]{ const TextBuf s = fx_target(14, 0x0ULL); return is_hex16(s.c_str(), s.size()); }()) == 1, "FB-B2 value: is_hex16 target kind 14 id 0");
static_assert(([]{ const TextBuf s = fx_target(14, 0x0ULL); return parse_hex16(s.c_str(), s.size()); }()) == 4294967295u, "FB-B2 value: parse_hex16 target kind 14 id 0");
static_assert(([]{ const TextBuf s = fx_target(14, 0x0ULL); return is_hex16(s.c_str()); }()) == 1, "FB-B2 value: is_hex16 target kind 14 id 0 (NUL-terminated)");
static_assert(([]{ const TextBuf s = fx_target(0, 0xFFFFFFFFFFFFFFFFULL); return is_hex16(s.c_str(), s.size()); }()) == 1, "FB-B2 value: is_hex16 target kind 0 id FFFFFFFFFFFFFFFF");
static_assert(([]{ const TextBuf s = fx_target(0, 0xFFFFFFFFFFFFFFFFULL); return parse_hex16(s.c_str(), s.size()); }()) == 0xFFFFFFFFFFFFFFFFULL, "FB-B2 value: parse_hex16 target kind 0 id FFFFFFFFFFFFFFFF");
static_assert(([]{ const TextBuf s = fx_target(0, 0xFFFFFFFFFFFFFFFFULL); return is_hex16(s.c_str()); }()) == 1, "FB-B2 value: is_hex16 target kind 0 id FFFFFFFFFFFFFFFF (NUL-terminated)");
static_assert(([]{ const TextBuf s = fx_target(1, 0xFFFFFFFFFFFFFFFFULL); return is_hex16(s.c_str(), s.size()); }()) == 0, "FB-B2 value: is_hex16 target kind 1 id FFFFFFFFFFFFFFFF");
static_assert(([]{ const TextBuf s = fx_target(1, 0xFFFFFFFFFFFFFFFFULL); return parse_hex16(s.c_str(), s.size()); }()) == 0, "FB-B2 value: parse_hex16 target kind 1 id FFFFFFFFFFFFFFFF");
static_assert(([]{ const TextBuf s = fx_target(1, 0xFFFFFFFFFFFFFFFFULL); return is_hex16(s.c_str()); }()) == 0, "FB-B2 value: is_hex16 target kind 1 id FFFFFFFFFFFFFFFF (NUL-terminated)");
static_assert(([]{ const TextBuf s = fx_target(2, 0xFFFFFFFFFFFFFFFFULL); return is_hex16(s.c_str(), s.size()); }()) == 0, "FB-B2 value: is_hex16 target kind 2 id FFFFFFFFFFFFFFFF");
static_assert(([]{ const TextBuf s = fx_target(2, 0xFFFFFFFFFFFFFFFFULL); return parse_hex16(s.c_str(), s.size()); }()) == 0, "FB-B2 value: parse_hex16 target kind 2 id FFFFFFFFFFFFFFFF");
static_assert(([]{ const TextBuf s = fx_target(2, 0xFFFFFFFFFFFFFFFFULL); return is_hex16(s.c_str()); }()) == 0, "FB-B2 value: is_hex16 target kind 2 id FFFFFFFFFFFFFFFF (NUL-terminated)");
static_assert(([]{ const TextBuf s = fx_target(3, 0xFFFFFFFFFFFFFFFFULL); return is_hex16(s.c_str(), s.size()); }()) == 0, "FB-B2 value: is_hex16 target kind 3 id FFFFFFFFFFFFFFFF");
static_assert(([]{ const TextBuf s = fx_target(3, 0xFFFFFFFFFFFFFFFFULL); return parse_hex16(s.c_str(), s.size()); }()) == 0, "FB-B2 value: parse_hex16 target kind 3 id FFFFFFFFFFFFFFFF");
static_assert(([]{ const TextBuf s = fx_target(3, 0xFFFFFFFFFFFFFFFFULL); return is_hex16(s.c_str()); }()) == 0, "FB-B2 value: is_hex16 target kind 3 id FFFFFFFFFFFFFFFF (NUL-terminated)");
static_assert(([]{ const TextBuf s = fx_target(4, 0xFFFFFFFFFFFFFFFFULL); return is_hex16(s.c_str(), s.size()); }()) == 1, "FB-B2 value: is_hex16 target kind 4 id FFFFFFFFFFFFFFFF");
static_assert(([]{ const TextBuf s = fx_target(4, 0xFFFFFFFFFFFFFFFFULL); return parse_hex16(s.c_str(), s.size()); }()) == 0xFFFFFFFFFFFFFFFEULL, "FB-B2 value: parse_hex16 target kind 4 id FFFFFFFFFFFFFFFF");
static_assert(([]{ const TextBuf s = fx_target(4, 0xFFFFFFFFFFFFFFFFULL); return is_hex16(s.c_str()); }()) == 1, "FB-B2 value: is_hex16 target kind 4 id FFFFFFFFFFFFFFFF (NUL-terminated)");
static_assert(([]{ const TextBuf s = fx_target(5, 0xFFFFFFFFFFFFFFFFULL); return is_hex16(s.c_str(), s.size()); }()) == 0, "FB-B2 value: is_hex16 target kind 5 id FFFFFFFFFFFFFFFF");
static_assert(([]{ const TextBuf s = fx_target(5, 0xFFFFFFFFFFFFFFFFULL); return parse_hex16(s.c_str(), s.size()); }()) == 0, "FB-B2 value: parse_hex16 target kind 5 id FFFFFFFFFFFFFFFF");
static_assert(([]{ const TextBuf s = fx_target(5, 0xFFFFFFFFFFFFFFFFULL); return is_hex16(s.c_str()); }()) == 0, "FB-B2 value: is_hex16 target kind 5 id FFFFFFFFFFFFFFFF (NUL-terminated)");
static_assert(([]{ const TextBuf s = fx_target(6, 0xFFFFFFFFFFFFFFFFULL); return is_hex16(s.c_str(), s.size()); }()) == 0, "FB-B2 value: is_hex16 target kind 6 id FFFFFFFFFFFFFFFF");
static_assert(([]{ const TextBuf s = fx_target(6, 0xFFFFFFFFFFFFFFFFULL); return parse_hex16(s.c_str(), s.size()); }()) == 0, "FB-B2 value: parse_hex16 target kind 6 id FFFFFFFFFFFFFFFF");
static_assert(([]{ const TextBuf s = fx_target(6, 0xFFFFFFFFFFFFFFFFULL); return is_hex16(s.c_str()); }()) == 0, "FB-B2 value: is_hex16 target kind 6 id FFFFFFFFFFFFFFFF (NUL-terminated)");
static_assert(([]{ const TextBuf s = fx_target(7, 0xFFFFFFFFFFFFFFFFULL); return is_hex16(s.c_str(), s.size()); }()) == 0, "FB-B2 value: is_hex16 target kind 7 id FFFFFFFFFFFFFFFF");
static_assert(([]{ const TextBuf s = fx_target(7, 0xFFFFFFFFFFFFFFFFULL); return parse_hex16(s.c_str(), s.size()); }()) == 0, "FB-B2 value: parse_hex16 target kind 7 id FFFFFFFFFFFFFFFF");
static_assert(([]{ const TextBuf s = fx_target(7, 0xFFFFFFFFFFFFFFFFULL); return is_hex16(s.c_str()); }()) == 0, "FB-B2 value: is_hex16 target kind 7 id FFFFFFFFFFFFFFFF (NUL-terminated)");
static_assert(([]{ const TextBuf s = fx_target(8, 0xFFFFFFFFFFFFFFFFULL); return is_hex16(s.c_str(), s.size()); }()) == 0, "FB-B2 value: is_hex16 target kind 8 id FFFFFFFFFFFFFFFF");
static_assert(([]{ const TextBuf s = fx_target(8, 0xFFFFFFFFFFFFFFFFULL); return parse_hex16(s.c_str(), s.size()); }()) == 0, "FB-B2 value: parse_hex16 target kind 8 id FFFFFFFFFFFFFFFF");
static_assert(([]{ const TextBuf s = fx_target(8, 0xFFFFFFFFFFFFFFFFULL); return is_hex16(s.c_str()); }()) == 0, "FB-B2 value: is_hex16 target kind 8 id FFFFFFFFFFFFFFFF (NUL-terminated)");
static_assert(([]{ const TextBuf s = fx_target(9, 0xFFFFFFFFFFFFFFFFULL); return is_hex16(s.c_str(), s.size()); }()) == 0, "FB-B2 value: is_hex16 target kind 9 id FFFFFFFFFFFFFFFF");
static_assert(([]{ const TextBuf s = fx_target(9, 0xFFFFFFFFFFFFFFFFULL); return parse_hex16(s.c_str(), s.size()); }()) == 0, "FB-B2 value: parse_hex16 target kind 9 id FFFFFFFFFFFFFFFF");
static_assert(([]{ const TextBuf s = fx_target(9, 0xFFFFFFFFFFFFFFFFULL); return is_hex16(s.c_str()); }()) == 0, "FB-B2 value: is_hex16 target kind 9 id FFFFFFFFFFFFFFFF (NUL-terminated)");
static_assert(([]{ const TextBuf s = fx_target(10, 0xFFFFFFFFFFFFFFFFULL); return is_hex16(s.c_str(), s.size()); }()) == 0, "FB-B2 value: is_hex16 target kind 10 id FFFFFFFFFFFFFFFF");
static_assert(([]{ const TextBuf s = fx_target(10, 0xFFFFFFFFFFFFFFFFULL); return parse_hex16(s.c_str(), s.size()); }()) == 0, "FB-B2 value: parse_hex16 target kind 10 id FFFFFFFFFFFFFFFF");
static_assert(([]{ const TextBuf s = fx_target(10, 0xFFFFFFFFFFFFFFFFULL); return is_hex16(s.c_str()); }()) == 0, "FB-B2 value: is_hex16 target kind 10 id FFFFFFFFFFFFFFFF (NUL-terminated)");
static_assert(([]{ const TextBuf s = fx_target(11, 0xFFFFFFFFFFFFFFFFULL); return is_hex16(s.c_str(), s.size()); }()) == 1, "FB-B2 value: is_hex16 target kind 11 id FFFFFFFFFFFFFFFF");
static_assert(([]{ const TextBuf s = fx_target(11, 0xFFFFFFFFFFFFFFFFULL); return parse_hex16(s.c_str(), s.size()); }()) == 0x7FFFFFFFFFFFFFFFULL, "FB-B2 value: parse_hex16 target kind 11 id FFFFFFFFFFFFFFFF");
static_assert(([]{ const TextBuf s = fx_target(11, 0xFFFFFFFFFFFFFFFFULL); return is_hex16(s.c_str()); }()) == 1, "FB-B2 value: is_hex16 target kind 11 id FFFFFFFFFFFFFFFF (NUL-terminated)");
static_assert(([]{ const TextBuf s = fx_target(12, 0xFFFFFFFFFFFFFFFFULL); return is_hex16(s.c_str(), s.size()); }()) == 1, "FB-B2 value: is_hex16 target kind 12 id FFFFFFFFFFFFFFFF");
static_assert(([]{ const TextBuf s = fx_target(12, 0xFFFFFFFFFFFFFFFFULL); return parse_hex16(s.c_str(), s.size()); }()) == 0xFFFFFFFEFFFFFFFFULL, "FB-B2 value: parse_hex16 target kind 12 id FFFFFFFFFFFFFFFF");
static_assert(([]{ const TextBuf s = fx_target(12, 0xFFFFFFFFFFFFFFFFULL); return is_hex16(s.c_str()); }()) == 1, "FB-B2 value: is_hex16 target kind 12 id FFFFFFFFFFFFFFFF (NUL-terminated)");
static_assert(([]{ const TextBuf s = fx_target(13, 0xFFFFFFFFFFFFFFFFULL); return is_hex16(s.c_str(), s.size()); }()) == 1, "FB-B2 value: is_hex16 target kind 13 id FFFFFFFFFFFFFFFF");
static_assert(([]{ const TextBuf s = fx_target(13, 0xFFFFFFFFFFFFFFFFULL); return parse_hex16(s.c_str(), s.size()); }()) == 4294967295u, "FB-B2 value: parse_hex16 target kind 13 id FFFFFFFFFFFFFFFF");
static_assert(([]{ const TextBuf s = fx_target(13, 0xFFFFFFFFFFFFFFFFULL); return is_hex16(s.c_str()); }()) == 1, "FB-B2 value: is_hex16 target kind 13 id FFFFFFFFFFFFFFFF (NUL-terminated)");
static_assert(([]{ const TextBuf s = fx_target(14, 0xFFFFFFFFFFFFFFFFULL); return is_hex16(s.c_str(), s.size()); }()) == 1, "FB-B2 value: is_hex16 target kind 14 id FFFFFFFFFFFFFFFF");
static_assert(([]{ const TextBuf s = fx_target(14, 0xFFFFFFFFFFFFFFFFULL); return parse_hex16(s.c_str(), s.size()); }()) == 0xFFFFFFFF00000000ULL, "FB-B2 value: parse_hex16 target kind 14 id FFFFFFFFFFFFFFFF");
static_assert(([]{ const TextBuf s = fx_target(14, 0xFFFFFFFFFFFFFFFFULL); return is_hex16(s.c_str()); }()) == 1, "FB-B2 value: is_hex16 target kind 14 id FFFFFFFFFFFFFFFF (NUL-terminated)");
static_assert(([]{ const TextBuf s = fx_target(0, 0xABULL); return is_hex16(s.c_str(), s.size()); }()) == 1, "FB-B2 value: is_hex16 target kind 0 id AB");
static_assert(([]{ const TextBuf s = fx_target(0, 0xABULL); return parse_hex16(s.c_str(), s.size()); }()) == 171, "FB-B2 value: parse_hex16 target kind 0 id AB");
static_assert(([]{ const TextBuf s = fx_target(0, 0xABULL); return is_hex16(s.c_str()); }()) == 1, "FB-B2 value: is_hex16 target kind 0 id AB (NUL-terminated)");
static_assert(([]{ const TextBuf s = fx_target(1, 0xABULL); return is_hex16(s.c_str(), s.size()); }()) == 0, "FB-B2 value: is_hex16 target kind 1 id AB");
static_assert(([]{ const TextBuf s = fx_target(1, 0xABULL); return parse_hex16(s.c_str(), s.size()); }()) == 0, "FB-B2 value: parse_hex16 target kind 1 id AB");
static_assert(([]{ const TextBuf s = fx_target(1, 0xABULL); return is_hex16(s.c_str()); }()) == 0, "FB-B2 value: is_hex16 target kind 1 id AB (NUL-terminated)");
static_assert(([]{ const TextBuf s = fx_target(2, 0xABULL); return is_hex16(s.c_str(), s.size()); }()) == 0, "FB-B2 value: is_hex16 target kind 2 id AB");
static_assert(([]{ const TextBuf s = fx_target(2, 0xABULL); return parse_hex16(s.c_str(), s.size()); }()) == 0, "FB-B2 value: parse_hex16 target kind 2 id AB");
static_assert(([]{ const TextBuf s = fx_target(2, 0xABULL); return is_hex16(s.c_str()); }()) == 0, "FB-B2 value: is_hex16 target kind 2 id AB (NUL-terminated)");
static_assert(([]{ const TextBuf s = fx_target(3, 0xABULL); return is_hex16(s.c_str(), s.size()); }()) == 0, "FB-B2 value: is_hex16 target kind 3 id AB");
static_assert(([]{ const TextBuf s = fx_target(3, 0xABULL); return parse_hex16(s.c_str(), s.size()); }()) == 0, "FB-B2 value: parse_hex16 target kind 3 id AB");
static_assert(([]{ const TextBuf s = fx_target(3, 0xABULL); return is_hex16(s.c_str()); }()) == 0, "FB-B2 value: is_hex16 target kind 3 id AB (NUL-terminated)");
static_assert(([]{ const TextBuf s = fx_target(4, 0xABULL); return is_hex16(s.c_str(), s.size()); }()) == 1, "FB-B2 value: is_hex16 target kind 4 id AB");
static_assert(([]{ const TextBuf s = fx_target(4, 0xABULL); return parse_hex16(s.c_str(), s.size()); }()) == 170, "FB-B2 value: parse_hex16 target kind 4 id AB");
static_assert(([]{ const TextBuf s = fx_target(4, 0xABULL); return is_hex16(s.c_str()); }()) == 1, "FB-B2 value: is_hex16 target kind 4 id AB (NUL-terminated)");
static_assert(([]{ const TextBuf s = fx_target(5, 0xABULL); return is_hex16(s.c_str(), s.size()); }()) == 0, "FB-B2 value: is_hex16 target kind 5 id AB");
static_assert(([]{ const TextBuf s = fx_target(5, 0xABULL); return parse_hex16(s.c_str(), s.size()); }()) == 0, "FB-B2 value: parse_hex16 target kind 5 id AB");
static_assert(([]{ const TextBuf s = fx_target(5, 0xABULL); return is_hex16(s.c_str()); }()) == 0, "FB-B2 value: is_hex16 target kind 5 id AB (NUL-terminated)");
static_assert(([]{ const TextBuf s = fx_target(6, 0xABULL); return is_hex16(s.c_str(), s.size()); }()) == 0, "FB-B2 value: is_hex16 target kind 6 id AB");
static_assert(([]{ const TextBuf s = fx_target(6, 0xABULL); return parse_hex16(s.c_str(), s.size()); }()) == 0, "FB-B2 value: parse_hex16 target kind 6 id AB");
static_assert(([]{ const TextBuf s = fx_target(6, 0xABULL); return is_hex16(s.c_str()); }()) == 0, "FB-B2 value: is_hex16 target kind 6 id AB (NUL-terminated)");
static_assert(([]{ const TextBuf s = fx_target(7, 0xABULL); return is_hex16(s.c_str(), s.size()); }()) == 0, "FB-B2 value: is_hex16 target kind 7 id AB");
static_assert(([]{ const TextBuf s = fx_target(7, 0xABULL); return parse_hex16(s.c_str(), s.size()); }()) == 0, "FB-B2 value: parse_hex16 target kind 7 id AB");
static_assert(([]{ const TextBuf s = fx_target(7, 0xABULL); return is_hex16(s.c_str()); }()) == 0, "FB-B2 value: is_hex16 target kind 7 id AB (NUL-terminated)");
static_assert(([]{ const TextBuf s = fx_target(8, 0xABULL); return is_hex16(s.c_str(), s.size()); }()) == 0, "FB-B2 value: is_hex16 target kind 8 id AB");
static_assert(([]{ const TextBuf s = fx_target(8, 0xABULL); return parse_hex16(s.c_str(), s.size()); }()) == 0, "FB-B2 value: parse_hex16 target kind 8 id AB");
static_assert(([]{ const TextBuf s = fx_target(8, 0xABULL); return is_hex16(s.c_str()); }()) == 0, "FB-B2 value: is_hex16 target kind 8 id AB (NUL-terminated)");
static_assert(([]{ const TextBuf s = fx_target(9, 0xABULL); return is_hex16(s.c_str(), s.size()); }()) == 0, "FB-B2 value: is_hex16 target kind 9 id AB");
static_assert(([]{ const TextBuf s = fx_target(9, 0xABULL); return parse_hex16(s.c_str(), s.size()); }()) == 0, "FB-B2 value: parse_hex16 target kind 9 id AB");
static_assert(([]{ const TextBuf s = fx_target(9, 0xABULL); return is_hex16(s.c_str()); }()) == 0, "FB-B2 value: is_hex16 target kind 9 id AB (NUL-terminated)");
static_assert(([]{ const TextBuf s = fx_target(10, 0xABULL); return is_hex16(s.c_str(), s.size()); }()) == 0, "FB-B2 value: is_hex16 target kind 10 id AB");
static_assert(([]{ const TextBuf s = fx_target(10, 0xABULL); return parse_hex16(s.c_str(), s.size()); }()) == 0, "FB-B2 value: parse_hex16 target kind 10 id AB");
static_assert(([]{ const TextBuf s = fx_target(10, 0xABULL); return is_hex16(s.c_str()); }()) == 0, "FB-B2 value: is_hex16 target kind 10 id AB (NUL-terminated)");
static_assert(([]{ const TextBuf s = fx_target(11, 0xABULL); return is_hex16(s.c_str(), s.size()); }()) == 1, "FB-B2 value: is_hex16 target kind 11 id AB");
static_assert(([]{ const TextBuf s = fx_target(11, 0xABULL); return parse_hex16(s.c_str(), s.size()); }()) == 0x80000000000000ABULL, "FB-B2 value: parse_hex16 target kind 11 id AB");
static_assert(([]{ const TextBuf s = fx_target(11, 0xABULL); return is_hex16(s.c_str()); }()) == 1, "FB-B2 value: is_hex16 target kind 11 id AB (NUL-terminated)");
static_assert(([]{ const TextBuf s = fx_target(12, 0xABULL); return is_hex16(s.c_str(), s.size()); }()) == 1, "FB-B2 value: is_hex16 target kind 12 id AB");
static_assert(([]{ const TextBuf s = fx_target(12, 0xABULL); return parse_hex16(s.c_str(), s.size()); }()) == 0x1000000ABULL, "FB-B2 value: parse_hex16 target kind 12 id AB");
static_assert(([]{ const TextBuf s = fx_target(12, 0xABULL); return is_hex16(s.c_str()); }()) == 1, "FB-B2 value: is_hex16 target kind 12 id AB (NUL-terminated)");
static_assert(([]{ const TextBuf s = fx_target(13, 0xABULL); return is_hex16(s.c_str(), s.size()); }()) == 1, "FB-B2 value: is_hex16 target kind 13 id AB");
static_assert(([]{ const TextBuf s = fx_target(13, 0xABULL); return parse_hex16(s.c_str(), s.size()); }()) == 0xFFFFFFFF000000ABULL, "FB-B2 value: parse_hex16 target kind 13 id AB");
static_assert(([]{ const TextBuf s = fx_target(13, 0xABULL); return is_hex16(s.c_str()); }()) == 1, "FB-B2 value: is_hex16 target kind 13 id AB (NUL-terminated)");
static_assert(([]{ const TextBuf s = fx_target(14, 0xABULL); return is_hex16(s.c_str(), s.size()); }()) == 1, "FB-B2 value: is_hex16 target kind 14 id AB");
static_assert(([]{ const TextBuf s = fx_target(14, 0xABULL); return parse_hex16(s.c_str(), s.size()); }()) == 4294967124u, "FB-B2 value: parse_hex16 target kind 14 id AB");
static_assert(([]{ const TextBuf s = fx_target(14, 0xABULL); return is_hex16(s.c_str()); }()) == 1, "FB-B2 value: is_hex16 target kind 14 id AB (NUL-terminated)");
static_assert(([]{ const TextBuf s = fx_conf(0, 0x123456789ABCDEFULL); return parse_phrase(s.c_str(), s.size()).kind; }()) == 1, "FB-B2 value: parse_phrase kind of confirmation kind 0 id 123456789ABCDEF");
static_assert(([]{ const TextBuf s = fx_conf(0, 0x123456789ABCDEFULL); return parse_phrase(s.c_str(), s.size()).id; }()) == 0x123456789ABCDEFULL, "FB-B2 value: parse_phrase id of confirmation kind 0 id 123456789ABCDEF");
static_assert(([]{ const TextBuf s = fx_conf(0, 0x123456789ABCDEFULL); return parse_phrase(s.c_str()).kind; }()) == 1, "FB-B2 value: parse_phrase kind of confirmation kind 0 id 123456789ABCDEF (NUL-terminated)");
static_assert(([]{ const TextBuf s = fx_conf(0, 0x123456789ABCDEFULL); return phrase_equals(s.c_str(), s.size(), expected_phrase(1, 0x123456789ABCDEFULL)); }()) == 1, "FB-B2 value: phrase_equals confirmation kind 0 vs expected_phrase kind 1");
static_assert(([]{ const TextBuf s = fx_conf(0, 0x123456789ABCDEFULL); return phrase_equals(s.c_str(), expected_phrase(1, 0x123456789ABCDEFULL)); }()) == 1, "FB-B2 value: phrase_equals (NUL-terminated) confirmation kind 0 vs expected_phrase kind 1");
static_assert(([]{ const TextBuf s = fx_conf(0, 0x123456789ABCDEFULL); return phrase_equals(s.c_str(), s.size(), expected_phrase(2, 0x123456789ABCDEFULL)); }()) == 0, "FB-B2 value: phrase_equals confirmation kind 0 vs expected_phrase kind 2");
static_assert(([]{ const TextBuf s = fx_conf(0, 0x123456789ABCDEFULL); return phrase_equals(s.c_str(), expected_phrase(2, 0x123456789ABCDEFULL)); }()) == 0, "FB-B2 value: phrase_equals (NUL-terminated) confirmation kind 0 vs expected_phrase kind 2");
static_assert(([]{ const TextBuf s = fx_conf(0, 0x123456789ABCDEFULL); return phrase_equals(s.c_str(), s.size(), expected_phrase(3, 0x123456789ABCDEFULL)); }()) == 0, "FB-B2 value: phrase_equals confirmation kind 0 vs expected_phrase kind 3");
static_assert(([]{ const TextBuf s = fx_conf(0, 0x123456789ABCDEFULL); return phrase_equals(s.c_str(), expected_phrase(3, 0x123456789ABCDEFULL)); }()) == 0, "FB-B2 value: phrase_equals (NUL-terminated) confirmation kind 0 vs expected_phrase kind 3");
static_assert(([]{ const TextBuf s = fx_conf(1, 0x123456789ABCDEFULL); return parse_phrase(s.c_str(), s.size()).kind; }()) == 2, "FB-B2 value: parse_phrase kind of confirmation kind 1 id 123456789ABCDEF");
static_assert(([]{ const TextBuf s = fx_conf(1, 0x123456789ABCDEFULL); return parse_phrase(s.c_str(), s.size()).id; }()) == 0x123456789ABCDEFULL, "FB-B2 value: parse_phrase id of confirmation kind 1 id 123456789ABCDEF");
static_assert(([]{ const TextBuf s = fx_conf(1, 0x123456789ABCDEFULL); return parse_phrase(s.c_str()).kind; }()) == 2, "FB-B2 value: parse_phrase kind of confirmation kind 1 id 123456789ABCDEF (NUL-terminated)");
static_assert(([]{ const TextBuf s = fx_conf(1, 0x123456789ABCDEFULL); return phrase_equals(s.c_str(), s.size(), expected_phrase(1, 0x123456789ABCDEFULL)); }()) == 0, "FB-B2 value: phrase_equals confirmation kind 1 vs expected_phrase kind 1");
static_assert(([]{ const TextBuf s = fx_conf(1, 0x123456789ABCDEFULL); return phrase_equals(s.c_str(), expected_phrase(1, 0x123456789ABCDEFULL)); }()) == 0, "FB-B2 value: phrase_equals (NUL-terminated) confirmation kind 1 vs expected_phrase kind 1");
static_assert(([]{ const TextBuf s = fx_conf(1, 0x123456789ABCDEFULL); return phrase_equals(s.c_str(), s.size(), expected_phrase(2, 0x123456789ABCDEFULL)); }()) == 1, "FB-B2 value: phrase_equals confirmation kind 1 vs expected_phrase kind 2");
static_assert(([]{ const TextBuf s = fx_conf(1, 0x123456789ABCDEFULL); return phrase_equals(s.c_str(), expected_phrase(2, 0x123456789ABCDEFULL)); }()) == 1, "FB-B2 value: phrase_equals (NUL-terminated) confirmation kind 1 vs expected_phrase kind 2");
static_assert(([]{ const TextBuf s = fx_conf(1, 0x123456789ABCDEFULL); return phrase_equals(s.c_str(), s.size(), expected_phrase(3, 0x123456789ABCDEFULL)); }()) == 0, "FB-B2 value: phrase_equals confirmation kind 1 vs expected_phrase kind 3");
static_assert(([]{ const TextBuf s = fx_conf(1, 0x123456789ABCDEFULL); return phrase_equals(s.c_str(), expected_phrase(3, 0x123456789ABCDEFULL)); }()) == 0, "FB-B2 value: phrase_equals (NUL-terminated) confirmation kind 1 vs expected_phrase kind 3");
static_assert(([]{ const TextBuf s = fx_conf(2, 0x123456789ABCDEFULL); return parse_phrase(s.c_str(), s.size()).kind; }()) == 3, "FB-B2 value: parse_phrase kind of confirmation kind 2 id 123456789ABCDEF");
static_assert(([]{ const TextBuf s = fx_conf(2, 0x123456789ABCDEFULL); return parse_phrase(s.c_str(), s.size()).id; }()) == 0x123456789ABCDEFULL, "FB-B2 value: parse_phrase id of confirmation kind 2 id 123456789ABCDEF");
static_assert(([]{ const TextBuf s = fx_conf(2, 0x123456789ABCDEFULL); return parse_phrase(s.c_str()).kind; }()) == 3, "FB-B2 value: parse_phrase kind of confirmation kind 2 id 123456789ABCDEF (NUL-terminated)");
static_assert(([]{ const TextBuf s = fx_conf(2, 0x123456789ABCDEFULL); return phrase_equals(s.c_str(), s.size(), expected_phrase(1, 0x123456789ABCDEFULL)); }()) == 0, "FB-B2 value: phrase_equals confirmation kind 2 vs expected_phrase kind 1");
static_assert(([]{ const TextBuf s = fx_conf(2, 0x123456789ABCDEFULL); return phrase_equals(s.c_str(), expected_phrase(1, 0x123456789ABCDEFULL)); }()) == 0, "FB-B2 value: phrase_equals (NUL-terminated) confirmation kind 2 vs expected_phrase kind 1");
static_assert(([]{ const TextBuf s = fx_conf(2, 0x123456789ABCDEFULL); return phrase_equals(s.c_str(), s.size(), expected_phrase(2, 0x123456789ABCDEFULL)); }()) == 0, "FB-B2 value: phrase_equals confirmation kind 2 vs expected_phrase kind 2");
static_assert(([]{ const TextBuf s = fx_conf(2, 0x123456789ABCDEFULL); return phrase_equals(s.c_str(), expected_phrase(2, 0x123456789ABCDEFULL)); }()) == 0, "FB-B2 value: phrase_equals (NUL-terminated) confirmation kind 2 vs expected_phrase kind 2");
static_assert(([]{ const TextBuf s = fx_conf(2, 0x123456789ABCDEFULL); return phrase_equals(s.c_str(), s.size(), expected_phrase(3, 0x123456789ABCDEFULL)); }()) == 1, "FB-B2 value: phrase_equals confirmation kind 2 vs expected_phrase kind 3");
static_assert(([]{ const TextBuf s = fx_conf(2, 0x123456789ABCDEFULL); return phrase_equals(s.c_str(), expected_phrase(3, 0x123456789ABCDEFULL)); }()) == 1, "FB-B2 value: phrase_equals (NUL-terminated) confirmation kind 2 vs expected_phrase kind 3");
static_assert(([]{ const TextBuf s = fx_conf(3, 0x123456789ABCDEFULL); return parse_phrase(s.c_str(), s.size()).kind; }()) == 0, "FB-B2 value: parse_phrase kind of confirmation kind 3 id 123456789ABCDEF");
static_assert(([]{ const TextBuf s = fx_conf(3, 0x123456789ABCDEFULL); return parse_phrase(s.c_str(), s.size()).id; }()) == 0, "FB-B2 value: parse_phrase id of confirmation kind 3 id 123456789ABCDEF");
static_assert(([]{ const TextBuf s = fx_conf(3, 0x123456789ABCDEFULL); return parse_phrase(s.c_str()).kind; }()) == 0, "FB-B2 value: parse_phrase kind of confirmation kind 3 id 123456789ABCDEF (NUL-terminated)");
static_assert(([]{ const TextBuf s = fx_conf(3, 0x123456789ABCDEFULL); return phrase_equals(s.c_str(), s.size(), expected_phrase(1, 0x123456789ABCDEFULL)); }()) == 0, "FB-B2 value: phrase_equals confirmation kind 3 vs expected_phrase kind 1");
static_assert(([]{ const TextBuf s = fx_conf(3, 0x123456789ABCDEFULL); return phrase_equals(s.c_str(), expected_phrase(1, 0x123456789ABCDEFULL)); }()) == 0, "FB-B2 value: phrase_equals (NUL-terminated) confirmation kind 3 vs expected_phrase kind 1");
static_assert(([]{ const TextBuf s = fx_conf(3, 0x123456789ABCDEFULL); return phrase_equals(s.c_str(), s.size(), expected_phrase(2, 0x123456789ABCDEFULL)); }()) == 0, "FB-B2 value: phrase_equals confirmation kind 3 vs expected_phrase kind 2");
static_assert(([]{ const TextBuf s = fx_conf(3, 0x123456789ABCDEFULL); return phrase_equals(s.c_str(), expected_phrase(2, 0x123456789ABCDEFULL)); }()) == 0, "FB-B2 value: phrase_equals (NUL-terminated) confirmation kind 3 vs expected_phrase kind 2");
static_assert(([]{ const TextBuf s = fx_conf(3, 0x123456789ABCDEFULL); return phrase_equals(s.c_str(), s.size(), expected_phrase(3, 0x123456789ABCDEFULL)); }()) == 0, "FB-B2 value: phrase_equals confirmation kind 3 vs expected_phrase kind 3");
static_assert(([]{ const TextBuf s = fx_conf(3, 0x123456789ABCDEFULL); return phrase_equals(s.c_str(), expected_phrase(3, 0x123456789ABCDEFULL)); }()) == 0, "FB-B2 value: phrase_equals (NUL-terminated) confirmation kind 3 vs expected_phrase kind 3");
static_assert(([]{ const TextBuf s = fx_conf(4, 0x123456789ABCDEFULL); return parse_phrase(s.c_str(), s.size()).kind; }()) == 0, "FB-B2 value: parse_phrase kind of confirmation kind 4 id 123456789ABCDEF");
static_assert(([]{ const TextBuf s = fx_conf(4, 0x123456789ABCDEFULL); return parse_phrase(s.c_str(), s.size()).id; }()) == 0, "FB-B2 value: parse_phrase id of confirmation kind 4 id 123456789ABCDEF");
static_assert(([]{ const TextBuf s = fx_conf(4, 0x123456789ABCDEFULL); return parse_phrase(s.c_str()).kind; }()) == 0, "FB-B2 value: parse_phrase kind of confirmation kind 4 id 123456789ABCDEF (NUL-terminated)");
static_assert(([]{ const TextBuf s = fx_conf(4, 0x123456789ABCDEFULL); return phrase_equals(s.c_str(), s.size(), expected_phrase(1, 0x123456789ABCDEFULL)); }()) == 0, "FB-B2 value: phrase_equals confirmation kind 4 vs expected_phrase kind 1");
static_assert(([]{ const TextBuf s = fx_conf(4, 0x123456789ABCDEFULL); return phrase_equals(s.c_str(), expected_phrase(1, 0x123456789ABCDEFULL)); }()) == 0, "FB-B2 value: phrase_equals (NUL-terminated) confirmation kind 4 vs expected_phrase kind 1");
static_assert(([]{ const TextBuf s = fx_conf(4, 0x123456789ABCDEFULL); return phrase_equals(s.c_str(), s.size(), expected_phrase(2, 0x123456789ABCDEFULL)); }()) == 0, "FB-B2 value: phrase_equals confirmation kind 4 vs expected_phrase kind 2");
static_assert(([]{ const TextBuf s = fx_conf(4, 0x123456789ABCDEFULL); return phrase_equals(s.c_str(), expected_phrase(2, 0x123456789ABCDEFULL)); }()) == 0, "FB-B2 value: phrase_equals (NUL-terminated) confirmation kind 4 vs expected_phrase kind 2");
static_assert(([]{ const TextBuf s = fx_conf(4, 0x123456789ABCDEFULL); return phrase_equals(s.c_str(), s.size(), expected_phrase(3, 0x123456789ABCDEFULL)); }()) == 0, "FB-B2 value: phrase_equals confirmation kind 4 vs expected_phrase kind 3");
static_assert(([]{ const TextBuf s = fx_conf(4, 0x123456789ABCDEFULL); return phrase_equals(s.c_str(), expected_phrase(3, 0x123456789ABCDEFULL)); }()) == 0, "FB-B2 value: phrase_equals (NUL-terminated) confirmation kind 4 vs expected_phrase kind 3");
static_assert(([]{ const TextBuf s = fx_conf(5, 0x123456789ABCDEFULL); return parse_phrase(s.c_str(), s.size()).kind; }()) == 0, "FB-B2 value: parse_phrase kind of confirmation kind 5 id 123456789ABCDEF");
static_assert(([]{ const TextBuf s = fx_conf(5, 0x123456789ABCDEFULL); return parse_phrase(s.c_str(), s.size()).id; }()) == 0, "FB-B2 value: parse_phrase id of confirmation kind 5 id 123456789ABCDEF");
static_assert(([]{ const TextBuf s = fx_conf(5, 0x123456789ABCDEFULL); return parse_phrase(s.c_str()).kind; }()) == 0, "FB-B2 value: parse_phrase kind of confirmation kind 5 id 123456789ABCDEF (NUL-terminated)");
static_assert(([]{ const TextBuf s = fx_conf(5, 0x123456789ABCDEFULL); return phrase_equals(s.c_str(), s.size(), expected_phrase(1, 0x123456789ABCDEFULL)); }()) == 0, "FB-B2 value: phrase_equals confirmation kind 5 vs expected_phrase kind 1");
static_assert(([]{ const TextBuf s = fx_conf(5, 0x123456789ABCDEFULL); return phrase_equals(s.c_str(), expected_phrase(1, 0x123456789ABCDEFULL)); }()) == 0, "FB-B2 value: phrase_equals (NUL-terminated) confirmation kind 5 vs expected_phrase kind 1");
static_assert(([]{ const TextBuf s = fx_conf(5, 0x123456789ABCDEFULL); return phrase_equals(s.c_str(), s.size(), expected_phrase(2, 0x123456789ABCDEFULL)); }()) == 0, "FB-B2 value: phrase_equals confirmation kind 5 vs expected_phrase kind 2");
static_assert(([]{ const TextBuf s = fx_conf(5, 0x123456789ABCDEFULL); return phrase_equals(s.c_str(), expected_phrase(2, 0x123456789ABCDEFULL)); }()) == 0, "FB-B2 value: phrase_equals (NUL-terminated) confirmation kind 5 vs expected_phrase kind 2");
static_assert(([]{ const TextBuf s = fx_conf(5, 0x123456789ABCDEFULL); return phrase_equals(s.c_str(), s.size(), expected_phrase(3, 0x123456789ABCDEFULL)); }()) == 0, "FB-B2 value: phrase_equals confirmation kind 5 vs expected_phrase kind 3");
static_assert(([]{ const TextBuf s = fx_conf(5, 0x123456789ABCDEFULL); return phrase_equals(s.c_str(), expected_phrase(3, 0x123456789ABCDEFULL)); }()) == 0, "FB-B2 value: phrase_equals (NUL-terminated) confirmation kind 5 vs expected_phrase kind 3");
static_assert(([]{ const TextBuf s = fx_conf(6, 0x123456789ABCDEFULL); return parse_phrase(s.c_str(), s.size()).kind; }()) == 0, "FB-B2 value: parse_phrase kind of confirmation kind 6 id 123456789ABCDEF");
static_assert(([]{ const TextBuf s = fx_conf(6, 0x123456789ABCDEFULL); return parse_phrase(s.c_str(), s.size()).id; }()) == 0, "FB-B2 value: parse_phrase id of confirmation kind 6 id 123456789ABCDEF");
static_assert(([]{ const TextBuf s = fx_conf(6, 0x123456789ABCDEFULL); return parse_phrase(s.c_str()).kind; }()) == 0, "FB-B2 value: parse_phrase kind of confirmation kind 6 id 123456789ABCDEF (NUL-terminated)");
static_assert(([]{ const TextBuf s = fx_conf(6, 0x123456789ABCDEFULL); return phrase_equals(s.c_str(), s.size(), expected_phrase(1, 0x123456789ABCDEFULL)); }()) == 0, "FB-B2 value: phrase_equals confirmation kind 6 vs expected_phrase kind 1");
static_assert(([]{ const TextBuf s = fx_conf(6, 0x123456789ABCDEFULL); return phrase_equals(s.c_str(), expected_phrase(1, 0x123456789ABCDEFULL)); }()) == 0, "FB-B2 value: phrase_equals (NUL-terminated) confirmation kind 6 vs expected_phrase kind 1");
static_assert(([]{ const TextBuf s = fx_conf(6, 0x123456789ABCDEFULL); return phrase_equals(s.c_str(), s.size(), expected_phrase(2, 0x123456789ABCDEFULL)); }()) == 0, "FB-B2 value: phrase_equals confirmation kind 6 vs expected_phrase kind 2");
static_assert(([]{ const TextBuf s = fx_conf(6, 0x123456789ABCDEFULL); return phrase_equals(s.c_str(), expected_phrase(2, 0x123456789ABCDEFULL)); }()) == 0, "FB-B2 value: phrase_equals (NUL-terminated) confirmation kind 6 vs expected_phrase kind 2");
static_assert(([]{ const TextBuf s = fx_conf(6, 0x123456789ABCDEFULL); return phrase_equals(s.c_str(), s.size(), expected_phrase(3, 0x123456789ABCDEFULL)); }()) == 0, "FB-B2 value: phrase_equals confirmation kind 6 vs expected_phrase kind 3");
static_assert(([]{ const TextBuf s = fx_conf(6, 0x123456789ABCDEFULL); return phrase_equals(s.c_str(), expected_phrase(3, 0x123456789ABCDEFULL)); }()) == 0, "FB-B2 value: phrase_equals (NUL-terminated) confirmation kind 6 vs expected_phrase kind 3");
static_assert(([]{ const TextBuf s = fx_conf(7, 0x123456789ABCDEFULL); return parse_phrase(s.c_str(), s.size()).kind; }()) == 0, "FB-B2 value: parse_phrase kind of confirmation kind 7 id 123456789ABCDEF");
static_assert(([]{ const TextBuf s = fx_conf(7, 0x123456789ABCDEFULL); return parse_phrase(s.c_str(), s.size()).id; }()) == 0, "FB-B2 value: parse_phrase id of confirmation kind 7 id 123456789ABCDEF");
static_assert(([]{ const TextBuf s = fx_conf(7, 0x123456789ABCDEFULL); return parse_phrase(s.c_str()).kind; }()) == 0, "FB-B2 value: parse_phrase kind of confirmation kind 7 id 123456789ABCDEF (NUL-terminated)");
static_assert(([]{ const TextBuf s = fx_conf(7, 0x123456789ABCDEFULL); return phrase_equals(s.c_str(), s.size(), expected_phrase(1, 0x123456789ABCDEFULL)); }()) == 0, "FB-B2 value: phrase_equals confirmation kind 7 vs expected_phrase kind 1");
static_assert(([]{ const TextBuf s = fx_conf(7, 0x123456789ABCDEFULL); return phrase_equals(s.c_str(), expected_phrase(1, 0x123456789ABCDEFULL)); }()) == 0, "FB-B2 value: phrase_equals (NUL-terminated) confirmation kind 7 vs expected_phrase kind 1");
static_assert(([]{ const TextBuf s = fx_conf(7, 0x123456789ABCDEFULL); return phrase_equals(s.c_str(), s.size(), expected_phrase(2, 0x123456789ABCDEFULL)); }()) == 0, "FB-B2 value: phrase_equals confirmation kind 7 vs expected_phrase kind 2");
static_assert(([]{ const TextBuf s = fx_conf(7, 0x123456789ABCDEFULL); return phrase_equals(s.c_str(), expected_phrase(2, 0x123456789ABCDEFULL)); }()) == 0, "FB-B2 value: phrase_equals (NUL-terminated) confirmation kind 7 vs expected_phrase kind 2");
static_assert(([]{ const TextBuf s = fx_conf(7, 0x123456789ABCDEFULL); return phrase_equals(s.c_str(), s.size(), expected_phrase(3, 0x123456789ABCDEFULL)); }()) == 0, "FB-B2 value: phrase_equals confirmation kind 7 vs expected_phrase kind 3");
static_assert(([]{ const TextBuf s = fx_conf(7, 0x123456789ABCDEFULL); return phrase_equals(s.c_str(), expected_phrase(3, 0x123456789ABCDEFULL)); }()) == 0, "FB-B2 value: phrase_equals (NUL-terminated) confirmation kind 7 vs expected_phrase kind 3");
static_assert(([]{ const TextBuf s = fx_conf(8, 0x123456789ABCDEFULL); return parse_phrase(s.c_str(), s.size()).kind; }()) == 0, "FB-B2 value: parse_phrase kind of confirmation kind 8 id 123456789ABCDEF");
static_assert(([]{ const TextBuf s = fx_conf(8, 0x123456789ABCDEFULL); return parse_phrase(s.c_str(), s.size()).id; }()) == 0, "FB-B2 value: parse_phrase id of confirmation kind 8 id 123456789ABCDEF");
static_assert(([]{ const TextBuf s = fx_conf(8, 0x123456789ABCDEFULL); return parse_phrase(s.c_str()).kind; }()) == 0, "FB-B2 value: parse_phrase kind of confirmation kind 8 id 123456789ABCDEF (NUL-terminated)");
static_assert(([]{ const TextBuf s = fx_conf(8, 0x123456789ABCDEFULL); return phrase_equals(s.c_str(), s.size(), expected_phrase(1, 0x123456789ABCDEFULL)); }()) == 0, "FB-B2 value: phrase_equals confirmation kind 8 vs expected_phrase kind 1");
static_assert(([]{ const TextBuf s = fx_conf(8, 0x123456789ABCDEFULL); return phrase_equals(s.c_str(), expected_phrase(1, 0x123456789ABCDEFULL)); }()) == 0, "FB-B2 value: phrase_equals (NUL-terminated) confirmation kind 8 vs expected_phrase kind 1");
static_assert(([]{ const TextBuf s = fx_conf(8, 0x123456789ABCDEFULL); return phrase_equals(s.c_str(), s.size(), expected_phrase(2, 0x123456789ABCDEFULL)); }()) == 0, "FB-B2 value: phrase_equals confirmation kind 8 vs expected_phrase kind 2");
static_assert(([]{ const TextBuf s = fx_conf(8, 0x123456789ABCDEFULL); return phrase_equals(s.c_str(), expected_phrase(2, 0x123456789ABCDEFULL)); }()) == 0, "FB-B2 value: phrase_equals (NUL-terminated) confirmation kind 8 vs expected_phrase kind 2");
static_assert(([]{ const TextBuf s = fx_conf(8, 0x123456789ABCDEFULL); return phrase_equals(s.c_str(), s.size(), expected_phrase(3, 0x123456789ABCDEFULL)); }()) == 0, "FB-B2 value: phrase_equals confirmation kind 8 vs expected_phrase kind 3");
static_assert(([]{ const TextBuf s = fx_conf(8, 0x123456789ABCDEFULL); return phrase_equals(s.c_str(), expected_phrase(3, 0x123456789ABCDEFULL)); }()) == 0, "FB-B2 value: phrase_equals (NUL-terminated) confirmation kind 8 vs expected_phrase kind 3");
static_assert(([]{ const TextBuf s = fx_conf(9, 0x123456789ABCDEFULL); return parse_phrase(s.c_str(), s.size()).kind; }()) == 0, "FB-B2 value: parse_phrase kind of confirmation kind 9 id 123456789ABCDEF");
static_assert(([]{ const TextBuf s = fx_conf(9, 0x123456789ABCDEFULL); return parse_phrase(s.c_str(), s.size()).id; }()) == 0, "FB-B2 value: parse_phrase id of confirmation kind 9 id 123456789ABCDEF");
static_assert(([]{ const TextBuf s = fx_conf(9, 0x123456789ABCDEFULL); return parse_phrase(s.c_str()).kind; }()) == 0, "FB-B2 value: parse_phrase kind of confirmation kind 9 id 123456789ABCDEF (NUL-terminated)");
static_assert(([]{ const TextBuf s = fx_conf(9, 0x123456789ABCDEFULL); return phrase_equals(s.c_str(), s.size(), expected_phrase(1, 0x123456789ABCDEFULL)); }()) == 0, "FB-B2 value: phrase_equals confirmation kind 9 vs expected_phrase kind 1");
static_assert(([]{ const TextBuf s = fx_conf(9, 0x123456789ABCDEFULL); return phrase_equals(s.c_str(), expected_phrase(1, 0x123456789ABCDEFULL)); }()) == 0, "FB-B2 value: phrase_equals (NUL-terminated) confirmation kind 9 vs expected_phrase kind 1");
static_assert(([]{ const TextBuf s = fx_conf(9, 0x123456789ABCDEFULL); return phrase_equals(s.c_str(), s.size(), expected_phrase(2, 0x123456789ABCDEFULL)); }()) == 0, "FB-B2 value: phrase_equals confirmation kind 9 vs expected_phrase kind 2");
static_assert(([]{ const TextBuf s = fx_conf(9, 0x123456789ABCDEFULL); return phrase_equals(s.c_str(), expected_phrase(2, 0x123456789ABCDEFULL)); }()) == 0, "FB-B2 value: phrase_equals (NUL-terminated) confirmation kind 9 vs expected_phrase kind 2");
static_assert(([]{ const TextBuf s = fx_conf(9, 0x123456789ABCDEFULL); return phrase_equals(s.c_str(), s.size(), expected_phrase(3, 0x123456789ABCDEFULL)); }()) == 0, "FB-B2 value: phrase_equals confirmation kind 9 vs expected_phrase kind 3");
static_assert(([]{ const TextBuf s = fx_conf(9, 0x123456789ABCDEFULL); return phrase_equals(s.c_str(), expected_phrase(3, 0x123456789ABCDEFULL)); }()) == 0, "FB-B2 value: phrase_equals (NUL-terminated) confirmation kind 9 vs expected_phrase kind 3");
static_assert(([]{ const TextBuf s = fx_conf(10, 0x123456789ABCDEFULL); return parse_phrase(s.c_str(), s.size()).kind; }()) == 0, "FB-B2 value: parse_phrase kind of confirmation kind 10 id 123456789ABCDEF");
static_assert(([]{ const TextBuf s = fx_conf(10, 0x123456789ABCDEFULL); return parse_phrase(s.c_str(), s.size()).id; }()) == 0, "FB-B2 value: parse_phrase id of confirmation kind 10 id 123456789ABCDEF");
static_assert(([]{ const TextBuf s = fx_conf(10, 0x123456789ABCDEFULL); return parse_phrase(s.c_str()).kind; }()) == 0, "FB-B2 value: parse_phrase kind of confirmation kind 10 id 123456789ABCDEF (NUL-terminated)");
static_assert(([]{ const TextBuf s = fx_conf(10, 0x123456789ABCDEFULL); return phrase_equals(s.c_str(), s.size(), expected_phrase(1, 0x123456789ABCDEFULL)); }()) == 0, "FB-B2 value: phrase_equals confirmation kind 10 vs expected_phrase kind 1");
static_assert(([]{ const TextBuf s = fx_conf(10, 0x123456789ABCDEFULL); return phrase_equals(s.c_str(), expected_phrase(1, 0x123456789ABCDEFULL)); }()) == 0, "FB-B2 value: phrase_equals (NUL-terminated) confirmation kind 10 vs expected_phrase kind 1");
static_assert(([]{ const TextBuf s = fx_conf(10, 0x123456789ABCDEFULL); return phrase_equals(s.c_str(), s.size(), expected_phrase(2, 0x123456789ABCDEFULL)); }()) == 0, "FB-B2 value: phrase_equals confirmation kind 10 vs expected_phrase kind 2");
static_assert(([]{ const TextBuf s = fx_conf(10, 0x123456789ABCDEFULL); return phrase_equals(s.c_str(), expected_phrase(2, 0x123456789ABCDEFULL)); }()) == 0, "FB-B2 value: phrase_equals (NUL-terminated) confirmation kind 10 vs expected_phrase kind 2");
static_assert(([]{ const TextBuf s = fx_conf(10, 0x123456789ABCDEFULL); return phrase_equals(s.c_str(), s.size(), expected_phrase(3, 0x123456789ABCDEFULL)); }()) == 0, "FB-B2 value: phrase_equals confirmation kind 10 vs expected_phrase kind 3");
static_assert(([]{ const TextBuf s = fx_conf(10, 0x123456789ABCDEFULL); return phrase_equals(s.c_str(), expected_phrase(3, 0x123456789ABCDEFULL)); }()) == 0, "FB-B2 value: phrase_equals (NUL-terminated) confirmation kind 10 vs expected_phrase kind 3");
static_assert(([]{ const TextBuf s = fx_conf(11, 0x123456789ABCDEFULL); return parse_phrase(s.c_str(), s.size()).kind; }()) == 0, "FB-B2 value: parse_phrase kind of confirmation kind 11 id 123456789ABCDEF");
static_assert(([]{ const TextBuf s = fx_conf(11, 0x123456789ABCDEFULL); return parse_phrase(s.c_str(), s.size()).id; }()) == 0, "FB-B2 value: parse_phrase id of confirmation kind 11 id 123456789ABCDEF");
static_assert(([]{ const TextBuf s = fx_conf(11, 0x123456789ABCDEFULL); return parse_phrase(s.c_str()).kind; }()) == 0, "FB-B2 value: parse_phrase kind of confirmation kind 11 id 123456789ABCDEF (NUL-terminated)");
static_assert(([]{ const TextBuf s = fx_conf(11, 0x123456789ABCDEFULL); return phrase_equals(s.c_str(), s.size(), expected_phrase(1, 0x123456789ABCDEFULL)); }()) == 0, "FB-B2 value: phrase_equals confirmation kind 11 vs expected_phrase kind 1");
static_assert(([]{ const TextBuf s = fx_conf(11, 0x123456789ABCDEFULL); return phrase_equals(s.c_str(), expected_phrase(1, 0x123456789ABCDEFULL)); }()) == 0, "FB-B2 value: phrase_equals (NUL-terminated) confirmation kind 11 vs expected_phrase kind 1");
static_assert(([]{ const TextBuf s = fx_conf(11, 0x123456789ABCDEFULL); return phrase_equals(s.c_str(), s.size(), expected_phrase(2, 0x123456789ABCDEFULL)); }()) == 0, "FB-B2 value: phrase_equals confirmation kind 11 vs expected_phrase kind 2");
static_assert(([]{ const TextBuf s = fx_conf(11, 0x123456789ABCDEFULL); return phrase_equals(s.c_str(), expected_phrase(2, 0x123456789ABCDEFULL)); }()) == 0, "FB-B2 value: phrase_equals (NUL-terminated) confirmation kind 11 vs expected_phrase kind 2");
static_assert(([]{ const TextBuf s = fx_conf(11, 0x123456789ABCDEFULL); return phrase_equals(s.c_str(), s.size(), expected_phrase(3, 0x123456789ABCDEFULL)); }()) == 0, "FB-B2 value: phrase_equals confirmation kind 11 vs expected_phrase kind 3");
static_assert(([]{ const TextBuf s = fx_conf(11, 0x123456789ABCDEFULL); return phrase_equals(s.c_str(), expected_phrase(3, 0x123456789ABCDEFULL)); }()) == 0, "FB-B2 value: phrase_equals (NUL-terminated) confirmation kind 11 vs expected_phrase kind 3");
static_assert(([]{ const TextBuf s = fx_conf(12, 0x123456789ABCDEFULL); return parse_phrase(s.c_str(), s.size()).kind; }()) == 0, "FB-B2 value: parse_phrase kind of confirmation kind 12 id 123456789ABCDEF");
static_assert(([]{ const TextBuf s = fx_conf(12, 0x123456789ABCDEFULL); return parse_phrase(s.c_str(), s.size()).id; }()) == 0, "FB-B2 value: parse_phrase id of confirmation kind 12 id 123456789ABCDEF");
static_assert(([]{ const TextBuf s = fx_conf(12, 0x123456789ABCDEFULL); return parse_phrase(s.c_str()).kind; }()) == 0, "FB-B2 value: parse_phrase kind of confirmation kind 12 id 123456789ABCDEF (NUL-terminated)");
static_assert(([]{ const TextBuf s = fx_conf(12, 0x123456789ABCDEFULL); return phrase_equals(s.c_str(), s.size(), expected_phrase(1, 0x123456789ABCDEFULL)); }()) == 0, "FB-B2 value: phrase_equals confirmation kind 12 vs expected_phrase kind 1");
static_assert(([]{ const TextBuf s = fx_conf(12, 0x123456789ABCDEFULL); return phrase_equals(s.c_str(), expected_phrase(1, 0x123456789ABCDEFULL)); }()) == 0, "FB-B2 value: phrase_equals (NUL-terminated) confirmation kind 12 vs expected_phrase kind 1");
static_assert(([]{ const TextBuf s = fx_conf(12, 0x123456789ABCDEFULL); return phrase_equals(s.c_str(), s.size(), expected_phrase(2, 0x123456789ABCDEFULL)); }()) == 0, "FB-B2 value: phrase_equals confirmation kind 12 vs expected_phrase kind 2");
static_assert(([]{ const TextBuf s = fx_conf(12, 0x123456789ABCDEFULL); return phrase_equals(s.c_str(), expected_phrase(2, 0x123456789ABCDEFULL)); }()) == 0, "FB-B2 value: phrase_equals (NUL-terminated) confirmation kind 12 vs expected_phrase kind 2");
static_assert(([]{ const TextBuf s = fx_conf(12, 0x123456789ABCDEFULL); return phrase_equals(s.c_str(), s.size(), expected_phrase(3, 0x123456789ABCDEFULL)); }()) == 0, "FB-B2 value: phrase_equals confirmation kind 12 vs expected_phrase kind 3");
static_assert(([]{ const TextBuf s = fx_conf(12, 0x123456789ABCDEFULL); return phrase_equals(s.c_str(), expected_phrase(3, 0x123456789ABCDEFULL)); }()) == 0, "FB-B2 value: phrase_equals (NUL-terminated) confirmation kind 12 vs expected_phrase kind 3");
static_assert(([]{ const TextBuf s = fx_conf(13, 0x123456789ABCDEFULL); return parse_phrase(s.c_str(), s.size()).kind; }()) == 0, "FB-B2 value: parse_phrase kind of confirmation kind 13 id 123456789ABCDEF");
static_assert(([]{ const TextBuf s = fx_conf(13, 0x123456789ABCDEFULL); return parse_phrase(s.c_str(), s.size()).id; }()) == 0, "FB-B2 value: parse_phrase id of confirmation kind 13 id 123456789ABCDEF");
static_assert(([]{ const TextBuf s = fx_conf(13, 0x123456789ABCDEFULL); return parse_phrase(s.c_str()).kind; }()) == 0, "FB-B2 value: parse_phrase kind of confirmation kind 13 id 123456789ABCDEF (NUL-terminated)");
static_assert(([]{ const TextBuf s = fx_conf(13, 0x123456789ABCDEFULL); return phrase_equals(s.c_str(), s.size(), expected_phrase(1, 0x123456789ABCDEFULL)); }()) == 0, "FB-B2 value: phrase_equals confirmation kind 13 vs expected_phrase kind 1");
static_assert(([]{ const TextBuf s = fx_conf(13, 0x123456789ABCDEFULL); return phrase_equals(s.c_str(), expected_phrase(1, 0x123456789ABCDEFULL)); }()) == 0, "FB-B2 value: phrase_equals (NUL-terminated) confirmation kind 13 vs expected_phrase kind 1");
static_assert(([]{ const TextBuf s = fx_conf(13, 0x123456789ABCDEFULL); return phrase_equals(s.c_str(), s.size(), expected_phrase(2, 0x123456789ABCDEFULL)); }()) == 0, "FB-B2 value: phrase_equals confirmation kind 13 vs expected_phrase kind 2");
static_assert(([]{ const TextBuf s = fx_conf(13, 0x123456789ABCDEFULL); return phrase_equals(s.c_str(), expected_phrase(2, 0x123456789ABCDEFULL)); }()) == 0, "FB-B2 value: phrase_equals (NUL-terminated) confirmation kind 13 vs expected_phrase kind 2");
static_assert(([]{ const TextBuf s = fx_conf(13, 0x123456789ABCDEFULL); return phrase_equals(s.c_str(), s.size(), expected_phrase(3, 0x123456789ABCDEFULL)); }()) == 0, "FB-B2 value: phrase_equals confirmation kind 13 vs expected_phrase kind 3");
static_assert(([]{ const TextBuf s = fx_conf(13, 0x123456789ABCDEFULL); return phrase_equals(s.c_str(), expected_phrase(3, 0x123456789ABCDEFULL)); }()) == 0, "FB-B2 value: phrase_equals (NUL-terminated) confirmation kind 13 vs expected_phrase kind 3");
static_assert(([]{ const TextBuf s = fx_conf(14, 0x123456789ABCDEFULL); return parse_phrase(s.c_str(), s.size()).kind; }()) == 1, "FB-B2 value: parse_phrase kind of confirmation kind 14 id 123456789ABCDEF");
static_assert(([]{ const TextBuf s = fx_conf(14, 0x123456789ABCDEFULL); return parse_phrase(s.c_str(), s.size()).id; }()) == 0x123456789ABCDEEULL, "FB-B2 value: parse_phrase id of confirmation kind 14 id 123456789ABCDEF");
static_assert(([]{ const TextBuf s = fx_conf(14, 0x123456789ABCDEFULL); return parse_phrase(s.c_str()).kind; }()) == 1, "FB-B2 value: parse_phrase kind of confirmation kind 14 id 123456789ABCDEF (NUL-terminated)");
static_assert(([]{ const TextBuf s = fx_conf(14, 0x123456789ABCDEFULL); return phrase_equals(s.c_str(), s.size(), expected_phrase(1, 0x123456789ABCDEFULL)); }()) == 0, "FB-B2 value: phrase_equals confirmation kind 14 vs expected_phrase kind 1");
static_assert(([]{ const TextBuf s = fx_conf(14, 0x123456789ABCDEFULL); return phrase_equals(s.c_str(), expected_phrase(1, 0x123456789ABCDEFULL)); }()) == 0, "FB-B2 value: phrase_equals (NUL-terminated) confirmation kind 14 vs expected_phrase kind 1");
static_assert(([]{ const TextBuf s = fx_conf(14, 0x123456789ABCDEFULL); return phrase_equals(s.c_str(), s.size(), expected_phrase(2, 0x123456789ABCDEFULL)); }()) == 0, "FB-B2 value: phrase_equals confirmation kind 14 vs expected_phrase kind 2");
static_assert(([]{ const TextBuf s = fx_conf(14, 0x123456789ABCDEFULL); return phrase_equals(s.c_str(), expected_phrase(2, 0x123456789ABCDEFULL)); }()) == 0, "FB-B2 value: phrase_equals (NUL-terminated) confirmation kind 14 vs expected_phrase kind 2");
static_assert(([]{ const TextBuf s = fx_conf(14, 0x123456789ABCDEFULL); return phrase_equals(s.c_str(), s.size(), expected_phrase(3, 0x123456789ABCDEFULL)); }()) == 0, "FB-B2 value: phrase_equals confirmation kind 14 vs expected_phrase kind 3");
static_assert(([]{ const TextBuf s = fx_conf(14, 0x123456789ABCDEFULL); return phrase_equals(s.c_str(), expected_phrase(3, 0x123456789ABCDEFULL)); }()) == 0, "FB-B2 value: phrase_equals (NUL-terminated) confirmation kind 14 vs expected_phrase kind 3");
static_assert(([]{ const TextBuf s = fx_conf(15, 0x123456789ABCDEFULL); return parse_phrase(s.c_str(), s.size()).kind; }()) == 0, "FB-B2 value: parse_phrase kind of confirmation kind 15 id 123456789ABCDEF");
static_assert(([]{ const TextBuf s = fx_conf(15, 0x123456789ABCDEFULL); return parse_phrase(s.c_str(), s.size()).id; }()) == 0, "FB-B2 value: parse_phrase id of confirmation kind 15 id 123456789ABCDEF");
static_assert(([]{ const TextBuf s = fx_conf(15, 0x123456789ABCDEFULL); return parse_phrase(s.c_str()).kind; }()) == 0, "FB-B2 value: parse_phrase kind of confirmation kind 15 id 123456789ABCDEF (NUL-terminated)");
static_assert(([]{ const TextBuf s = fx_conf(15, 0x123456789ABCDEFULL); return phrase_equals(s.c_str(), s.size(), expected_phrase(1, 0x123456789ABCDEFULL)); }()) == 0, "FB-B2 value: phrase_equals confirmation kind 15 vs expected_phrase kind 1");
static_assert(([]{ const TextBuf s = fx_conf(15, 0x123456789ABCDEFULL); return phrase_equals(s.c_str(), expected_phrase(1, 0x123456789ABCDEFULL)); }()) == 0, "FB-B2 value: phrase_equals (NUL-terminated) confirmation kind 15 vs expected_phrase kind 1");
static_assert(([]{ const TextBuf s = fx_conf(15, 0x123456789ABCDEFULL); return phrase_equals(s.c_str(), s.size(), expected_phrase(2, 0x123456789ABCDEFULL)); }()) == 0, "FB-B2 value: phrase_equals confirmation kind 15 vs expected_phrase kind 2");
static_assert(([]{ const TextBuf s = fx_conf(15, 0x123456789ABCDEFULL); return phrase_equals(s.c_str(), expected_phrase(2, 0x123456789ABCDEFULL)); }()) == 0, "FB-B2 value: phrase_equals (NUL-terminated) confirmation kind 15 vs expected_phrase kind 2");
static_assert(([]{ const TextBuf s = fx_conf(15, 0x123456789ABCDEFULL); return phrase_equals(s.c_str(), s.size(), expected_phrase(3, 0x123456789ABCDEFULL)); }()) == 0, "FB-B2 value: phrase_equals confirmation kind 15 vs expected_phrase kind 3");
static_assert(([]{ const TextBuf s = fx_conf(15, 0x123456789ABCDEFULL); return phrase_equals(s.c_str(), expected_phrase(3, 0x123456789ABCDEFULL)); }()) == 0, "FB-B2 value: phrase_equals (NUL-terminated) confirmation kind 15 vs expected_phrase kind 3");
static_assert(([]{ const TextBuf s = fx_conf(16, 0x123456789ABCDEFULL); return parse_phrase(s.c_str(), s.size()).kind; }()) == 0, "FB-B2 value: parse_phrase kind of confirmation kind 16 id 123456789ABCDEF");
static_assert(([]{ const TextBuf s = fx_conf(16, 0x123456789ABCDEFULL); return parse_phrase(s.c_str(), s.size()).id; }()) == 0, "FB-B2 value: parse_phrase id of confirmation kind 16 id 123456789ABCDEF");
static_assert(([]{ const TextBuf s = fx_conf(16, 0x123456789ABCDEFULL); return parse_phrase(s.c_str()).kind; }()) == 0, "FB-B2 value: parse_phrase kind of confirmation kind 16 id 123456789ABCDEF (NUL-terminated)");
static_assert(([]{ const TextBuf s = fx_conf(16, 0x123456789ABCDEFULL); return phrase_equals(s.c_str(), s.size(), expected_phrase(1, 0x123456789ABCDEFULL)); }()) == 0, "FB-B2 value: phrase_equals confirmation kind 16 vs expected_phrase kind 1");
static_assert(([]{ const TextBuf s = fx_conf(16, 0x123456789ABCDEFULL); return phrase_equals(s.c_str(), expected_phrase(1, 0x123456789ABCDEFULL)); }()) == 0, "FB-B2 value: phrase_equals (NUL-terminated) confirmation kind 16 vs expected_phrase kind 1");
static_assert(([]{ const TextBuf s = fx_conf(16, 0x123456789ABCDEFULL); return phrase_equals(s.c_str(), s.size(), expected_phrase(2, 0x123456789ABCDEFULL)); }()) == 0, "FB-B2 value: phrase_equals confirmation kind 16 vs expected_phrase kind 2");
static_assert(([]{ const TextBuf s = fx_conf(16, 0x123456789ABCDEFULL); return phrase_equals(s.c_str(), expected_phrase(2, 0x123456789ABCDEFULL)); }()) == 0, "FB-B2 value: phrase_equals (NUL-terminated) confirmation kind 16 vs expected_phrase kind 2");
static_assert(([]{ const TextBuf s = fx_conf(16, 0x123456789ABCDEFULL); return phrase_equals(s.c_str(), s.size(), expected_phrase(3, 0x123456789ABCDEFULL)); }()) == 0, "FB-B2 value: phrase_equals confirmation kind 16 vs expected_phrase kind 3");
static_assert(([]{ const TextBuf s = fx_conf(16, 0x123456789ABCDEFULL); return phrase_equals(s.c_str(), expected_phrase(3, 0x123456789ABCDEFULL)); }()) == 0, "FB-B2 value: phrase_equals (NUL-terminated) confirmation kind 16 vs expected_phrase kind 3");
static_assert(([]{ const TextBuf s = fx_conf(17, 0x123456789ABCDEFULL); return parse_phrase(s.c_str(), s.size()).kind; }()) == 0, "FB-B2 value: parse_phrase kind of confirmation kind 17 id 123456789ABCDEF");
static_assert(([]{ const TextBuf s = fx_conf(17, 0x123456789ABCDEFULL); return parse_phrase(s.c_str(), s.size()).id; }()) == 0, "FB-B2 value: parse_phrase id of confirmation kind 17 id 123456789ABCDEF");
static_assert(([]{ const TextBuf s = fx_conf(17, 0x123456789ABCDEFULL); return parse_phrase(s.c_str()).kind; }()) == 0, "FB-B2 value: parse_phrase kind of confirmation kind 17 id 123456789ABCDEF (NUL-terminated)");
static_assert(([]{ const TextBuf s = fx_conf(17, 0x123456789ABCDEFULL); return phrase_equals(s.c_str(), s.size(), expected_phrase(1, 0x123456789ABCDEFULL)); }()) == 0, "FB-B2 value: phrase_equals confirmation kind 17 vs expected_phrase kind 1");
static_assert(([]{ const TextBuf s = fx_conf(17, 0x123456789ABCDEFULL); return phrase_equals(s.c_str(), expected_phrase(1, 0x123456789ABCDEFULL)); }()) == 0, "FB-B2 value: phrase_equals (NUL-terminated) confirmation kind 17 vs expected_phrase kind 1");
static_assert(([]{ const TextBuf s = fx_conf(17, 0x123456789ABCDEFULL); return phrase_equals(s.c_str(), s.size(), expected_phrase(2, 0x123456789ABCDEFULL)); }()) == 0, "FB-B2 value: phrase_equals confirmation kind 17 vs expected_phrase kind 2");
static_assert(([]{ const TextBuf s = fx_conf(17, 0x123456789ABCDEFULL); return phrase_equals(s.c_str(), expected_phrase(2, 0x123456789ABCDEFULL)); }()) == 0, "FB-B2 value: phrase_equals (NUL-terminated) confirmation kind 17 vs expected_phrase kind 2");
static_assert(([]{ const TextBuf s = fx_conf(17, 0x123456789ABCDEFULL); return phrase_equals(s.c_str(), s.size(), expected_phrase(3, 0x123456789ABCDEFULL)); }()) == 0, "FB-B2 value: phrase_equals confirmation kind 17 vs expected_phrase kind 3");
static_assert(([]{ const TextBuf s = fx_conf(17, 0x123456789ABCDEFULL); return phrase_equals(s.c_str(), expected_phrase(3, 0x123456789ABCDEFULL)); }()) == 0, "FB-B2 value: phrase_equals (NUL-terminated) confirmation kind 17 vs expected_phrase kind 3");
static_assert(([]{ const TextBuf s = fx_conf(18, 0x123456789ABCDEFULL); return parse_phrase(s.c_str(), s.size()).kind; }()) == 0, "FB-B2 value: parse_phrase kind of confirmation kind 18 id 123456789ABCDEF");
static_assert(([]{ const TextBuf s = fx_conf(18, 0x123456789ABCDEFULL); return parse_phrase(s.c_str(), s.size()).id; }()) == 0, "FB-B2 value: parse_phrase id of confirmation kind 18 id 123456789ABCDEF");
static_assert(([]{ const TextBuf s = fx_conf(18, 0x123456789ABCDEFULL); return parse_phrase(s.c_str()).kind; }()) == 0, "FB-B2 value: parse_phrase kind of confirmation kind 18 id 123456789ABCDEF (NUL-terminated)");
static_assert(([]{ const TextBuf s = fx_conf(18, 0x123456789ABCDEFULL); return phrase_equals(s.c_str(), s.size(), expected_phrase(1, 0x123456789ABCDEFULL)); }()) == 0, "FB-B2 value: phrase_equals confirmation kind 18 vs expected_phrase kind 1");
static_assert(([]{ const TextBuf s = fx_conf(18, 0x123456789ABCDEFULL); return phrase_equals(s.c_str(), expected_phrase(1, 0x123456789ABCDEFULL)); }()) == 0, "FB-B2 value: phrase_equals (NUL-terminated) confirmation kind 18 vs expected_phrase kind 1");
static_assert(([]{ const TextBuf s = fx_conf(18, 0x123456789ABCDEFULL); return phrase_equals(s.c_str(), s.size(), expected_phrase(2, 0x123456789ABCDEFULL)); }()) == 0, "FB-B2 value: phrase_equals confirmation kind 18 vs expected_phrase kind 2");
static_assert(([]{ const TextBuf s = fx_conf(18, 0x123456789ABCDEFULL); return phrase_equals(s.c_str(), expected_phrase(2, 0x123456789ABCDEFULL)); }()) == 0, "FB-B2 value: phrase_equals (NUL-terminated) confirmation kind 18 vs expected_phrase kind 2");
static_assert(([]{ const TextBuf s = fx_conf(18, 0x123456789ABCDEFULL); return phrase_equals(s.c_str(), s.size(), expected_phrase(3, 0x123456789ABCDEFULL)); }()) == 0, "FB-B2 value: phrase_equals confirmation kind 18 vs expected_phrase kind 3");
static_assert(([]{ const TextBuf s = fx_conf(18, 0x123456789ABCDEFULL); return phrase_equals(s.c_str(), expected_phrase(3, 0x123456789ABCDEFULL)); }()) == 0, "FB-B2 value: phrase_equals (NUL-terminated) confirmation kind 18 vs expected_phrase kind 3");
static_assert(([]{ const TextBuf s = fx_conf(19, 0x123456789ABCDEFULL); return parse_phrase(s.c_str(), s.size()).kind; }()) == 0, "FB-B2 value: parse_phrase kind of confirmation kind 19 id 123456789ABCDEF");
static_assert(([]{ const TextBuf s = fx_conf(19, 0x123456789ABCDEFULL); return parse_phrase(s.c_str(), s.size()).id; }()) == 0, "FB-B2 value: parse_phrase id of confirmation kind 19 id 123456789ABCDEF");
static_assert(([]{ const TextBuf s = fx_conf(19, 0x123456789ABCDEFULL); return parse_phrase(s.c_str()).kind; }()) == 0, "FB-B2 value: parse_phrase kind of confirmation kind 19 id 123456789ABCDEF (NUL-terminated)");
static_assert(([]{ const TextBuf s = fx_conf(19, 0x123456789ABCDEFULL); return phrase_equals(s.c_str(), s.size(), expected_phrase(1, 0x123456789ABCDEFULL)); }()) == 0, "FB-B2 value: phrase_equals confirmation kind 19 vs expected_phrase kind 1");
static_assert(([]{ const TextBuf s = fx_conf(19, 0x123456789ABCDEFULL); return phrase_equals(s.c_str(), expected_phrase(1, 0x123456789ABCDEFULL)); }()) == 0, "FB-B2 value: phrase_equals (NUL-terminated) confirmation kind 19 vs expected_phrase kind 1");
static_assert(([]{ const TextBuf s = fx_conf(19, 0x123456789ABCDEFULL); return phrase_equals(s.c_str(), s.size(), expected_phrase(2, 0x123456789ABCDEFULL)); }()) == 0, "FB-B2 value: phrase_equals confirmation kind 19 vs expected_phrase kind 2");
static_assert(([]{ const TextBuf s = fx_conf(19, 0x123456789ABCDEFULL); return phrase_equals(s.c_str(), expected_phrase(2, 0x123456789ABCDEFULL)); }()) == 0, "FB-B2 value: phrase_equals (NUL-terminated) confirmation kind 19 vs expected_phrase kind 2");
static_assert(([]{ const TextBuf s = fx_conf(19, 0x123456789ABCDEFULL); return phrase_equals(s.c_str(), s.size(), expected_phrase(3, 0x123456789ABCDEFULL)); }()) == 0, "FB-B2 value: phrase_equals confirmation kind 19 vs expected_phrase kind 3");
static_assert(([]{ const TextBuf s = fx_conf(19, 0x123456789ABCDEFULL); return phrase_equals(s.c_str(), expected_phrase(3, 0x123456789ABCDEFULL)); }()) == 0, "FB-B2 value: phrase_equals (NUL-terminated) confirmation kind 19 vs expected_phrase kind 3");
static_assert(([]{ const TextBuf s = fx_conf(20, 0x123456789ABCDEFULL); return parse_phrase(s.c_str(), s.size()).kind; }()) == 3, "FB-B2 value: parse_phrase kind of confirmation kind 20 id 123456789ABCDEF");
static_assert(([]{ const TextBuf s = fx_conf(20, 0x123456789ABCDEFULL); return parse_phrase(s.c_str(), s.size()).id; }()) == 0x123456789ABCDEEULL, "FB-B2 value: parse_phrase id of confirmation kind 20 id 123456789ABCDEF");
static_assert(([]{ const TextBuf s = fx_conf(20, 0x123456789ABCDEFULL); return parse_phrase(s.c_str()).kind; }()) == 3, "FB-B2 value: parse_phrase kind of confirmation kind 20 id 123456789ABCDEF (NUL-terminated)");
static_assert(([]{ const TextBuf s = fx_conf(20, 0x123456789ABCDEFULL); return phrase_equals(s.c_str(), s.size(), expected_phrase(1, 0x123456789ABCDEFULL)); }()) == 0, "FB-B2 value: phrase_equals confirmation kind 20 vs expected_phrase kind 1");
static_assert(([]{ const TextBuf s = fx_conf(20, 0x123456789ABCDEFULL); return phrase_equals(s.c_str(), expected_phrase(1, 0x123456789ABCDEFULL)); }()) == 0, "FB-B2 value: phrase_equals (NUL-terminated) confirmation kind 20 vs expected_phrase kind 1");
static_assert(([]{ const TextBuf s = fx_conf(20, 0x123456789ABCDEFULL); return phrase_equals(s.c_str(), s.size(), expected_phrase(2, 0x123456789ABCDEFULL)); }()) == 0, "FB-B2 value: phrase_equals confirmation kind 20 vs expected_phrase kind 2");
static_assert(([]{ const TextBuf s = fx_conf(20, 0x123456789ABCDEFULL); return phrase_equals(s.c_str(), expected_phrase(2, 0x123456789ABCDEFULL)); }()) == 0, "FB-B2 value: phrase_equals (NUL-terminated) confirmation kind 20 vs expected_phrase kind 2");
static_assert(([]{ const TextBuf s = fx_conf(20, 0x123456789ABCDEFULL); return phrase_equals(s.c_str(), s.size(), expected_phrase(3, 0x123456789ABCDEFULL)); }()) == 0, "FB-B2 value: phrase_equals confirmation kind 20 vs expected_phrase kind 3");
static_assert(([]{ const TextBuf s = fx_conf(20, 0x123456789ABCDEFULL); return phrase_equals(s.c_str(), expected_phrase(3, 0x123456789ABCDEFULL)); }()) == 0, "FB-B2 value: phrase_equals (NUL-terminated) confirmation kind 20 vs expected_phrase kind 3");
static_assert(([]{ const TextBuf s = fx_conf(21, 0x123456789ABCDEFULL); return parse_phrase(s.c_str(), s.size()).kind; }()) == 0, "FB-B2 value: parse_phrase kind of confirmation kind 21 id 123456789ABCDEF");
static_assert(([]{ const TextBuf s = fx_conf(21, 0x123456789ABCDEFULL); return parse_phrase(s.c_str(), s.size()).id; }()) == 0, "FB-B2 value: parse_phrase id of confirmation kind 21 id 123456789ABCDEF");
static_assert(([]{ const TextBuf s = fx_conf(21, 0x123456789ABCDEFULL); return parse_phrase(s.c_str()).kind; }()) == 1, "FB-B2 value: parse_phrase kind of confirmation kind 21 id 123456789ABCDEF (NUL-terminated)");
static_assert(([]{ const TextBuf s = fx_conf(21, 0x123456789ABCDEFULL); return phrase_equals(s.c_str(), s.size(), expected_phrase(1, 0x123456789ABCDEFULL)); }()) == 0, "FB-B2 value: phrase_equals confirmation kind 21 vs expected_phrase kind 1");
static_assert(([]{ const TextBuf s = fx_conf(21, 0x123456789ABCDEFULL); return phrase_equals(s.c_str(), expected_phrase(1, 0x123456789ABCDEFULL)); }()) == 1, "FB-B2 value: phrase_equals (NUL-terminated) confirmation kind 21 vs expected_phrase kind 1");
static_assert(([]{ const TextBuf s = fx_conf(21, 0x123456789ABCDEFULL); return phrase_equals(s.c_str(), s.size(), expected_phrase(2, 0x123456789ABCDEFULL)); }()) == 0, "FB-B2 value: phrase_equals confirmation kind 21 vs expected_phrase kind 2");
static_assert(([]{ const TextBuf s = fx_conf(21, 0x123456789ABCDEFULL); return phrase_equals(s.c_str(), expected_phrase(2, 0x123456789ABCDEFULL)); }()) == 0, "FB-B2 value: phrase_equals (NUL-terminated) confirmation kind 21 vs expected_phrase kind 2");
static_assert(([]{ const TextBuf s = fx_conf(21, 0x123456789ABCDEFULL); return phrase_equals(s.c_str(), s.size(), expected_phrase(3, 0x123456789ABCDEFULL)); }()) == 0, "FB-B2 value: phrase_equals confirmation kind 21 vs expected_phrase kind 3");
static_assert(([]{ const TextBuf s = fx_conf(21, 0x123456789ABCDEFULL); return phrase_equals(s.c_str(), expected_phrase(3, 0x123456789ABCDEFULL)); }()) == 0, "FB-B2 value: phrase_equals (NUL-terminated) confirmation kind 21 vs expected_phrase kind 3");
static_assert(([]{ const TextBuf s = fx_conf(22, 0x123456789ABCDEFULL); return parse_phrase(s.c_str(), s.size()).kind; }()) == 0, "FB-B2 value: parse_phrase kind of confirmation kind 22 id 123456789ABCDEF");
static_assert(([]{ const TextBuf s = fx_conf(22, 0x123456789ABCDEFULL); return parse_phrase(s.c_str(), s.size()).id; }()) == 0, "FB-B2 value: parse_phrase id of confirmation kind 22 id 123456789ABCDEF");
static_assert(([]{ const TextBuf s = fx_conf(22, 0x123456789ABCDEFULL); return parse_phrase(s.c_str()).kind; }()) == 1, "FB-B2 value: parse_phrase kind of confirmation kind 22 id 123456789ABCDEF (NUL-terminated)");
static_assert(([]{ const TextBuf s = fx_conf(22, 0x123456789ABCDEFULL); return phrase_equals(s.c_str(), s.size(), expected_phrase(1, 0x123456789ABCDEFULL)); }()) == 0, "FB-B2 value: phrase_equals confirmation kind 22 vs expected_phrase kind 1");
static_assert(([]{ const TextBuf s = fx_conf(22, 0x123456789ABCDEFULL); return phrase_equals(s.c_str(), expected_phrase(1, 0x123456789ABCDEFULL)); }()) == 1, "FB-B2 value: phrase_equals (NUL-terminated) confirmation kind 22 vs expected_phrase kind 1");
static_assert(([]{ const TextBuf s = fx_conf(22, 0x123456789ABCDEFULL); return phrase_equals(s.c_str(), s.size(), expected_phrase(2, 0x123456789ABCDEFULL)); }()) == 0, "FB-B2 value: phrase_equals confirmation kind 22 vs expected_phrase kind 2");
static_assert(([]{ const TextBuf s = fx_conf(22, 0x123456789ABCDEFULL); return phrase_equals(s.c_str(), expected_phrase(2, 0x123456789ABCDEFULL)); }()) == 0, "FB-B2 value: phrase_equals (NUL-terminated) confirmation kind 22 vs expected_phrase kind 2");
static_assert(([]{ const TextBuf s = fx_conf(22, 0x123456789ABCDEFULL); return phrase_equals(s.c_str(), s.size(), expected_phrase(3, 0x123456789ABCDEFULL)); }()) == 0, "FB-B2 value: phrase_equals confirmation kind 22 vs expected_phrase kind 3");
static_assert(([]{ const TextBuf s = fx_conf(22, 0x123456789ABCDEFULL); return phrase_equals(s.c_str(), expected_phrase(3, 0x123456789ABCDEFULL)); }()) == 0, "FB-B2 value: phrase_equals (NUL-terminated) confirmation kind 22 vs expected_phrase kind 3");
static_assert(([]{ const TextBuf s = fx_conf(23, 0x123456789ABCDEFULL); return parse_phrase(s.c_str(), s.size()).kind; }()) == 0, "FB-B2 value: parse_phrase kind of confirmation kind 23 id 123456789ABCDEF");
static_assert(([]{ const TextBuf s = fx_conf(23, 0x123456789ABCDEFULL); return parse_phrase(s.c_str(), s.size()).id; }()) == 0, "FB-B2 value: parse_phrase id of confirmation kind 23 id 123456789ABCDEF");
static_assert(([]{ const TextBuf s = fx_conf(23, 0x123456789ABCDEFULL); return parse_phrase(s.c_str()).kind; }()) == 3, "FB-B2 value: parse_phrase kind of confirmation kind 23 id 123456789ABCDEF (NUL-terminated)");
static_assert(([]{ const TextBuf s = fx_conf(23, 0x123456789ABCDEFULL); return phrase_equals(s.c_str(), s.size(), expected_phrase(1, 0x123456789ABCDEFULL)); }()) == 0, "FB-B2 value: phrase_equals confirmation kind 23 vs expected_phrase kind 1");
static_assert(([]{ const TextBuf s = fx_conf(23, 0x123456789ABCDEFULL); return phrase_equals(s.c_str(), expected_phrase(1, 0x123456789ABCDEFULL)); }()) == 0, "FB-B2 value: phrase_equals (NUL-terminated) confirmation kind 23 vs expected_phrase kind 1");
static_assert(([]{ const TextBuf s = fx_conf(23, 0x123456789ABCDEFULL); return phrase_equals(s.c_str(), s.size(), expected_phrase(2, 0x123456789ABCDEFULL)); }()) == 0, "FB-B2 value: phrase_equals confirmation kind 23 vs expected_phrase kind 2");
static_assert(([]{ const TextBuf s = fx_conf(23, 0x123456789ABCDEFULL); return phrase_equals(s.c_str(), expected_phrase(2, 0x123456789ABCDEFULL)); }()) == 0, "FB-B2 value: phrase_equals (NUL-terminated) confirmation kind 23 vs expected_phrase kind 2");
static_assert(([]{ const TextBuf s = fx_conf(23, 0x123456789ABCDEFULL); return phrase_equals(s.c_str(), s.size(), expected_phrase(3, 0x123456789ABCDEFULL)); }()) == 0, "FB-B2 value: phrase_equals confirmation kind 23 vs expected_phrase kind 3");
static_assert(([]{ const TextBuf s = fx_conf(23, 0x123456789ABCDEFULL); return phrase_equals(s.c_str(), expected_phrase(3, 0x123456789ABCDEFULL)); }()) == 1, "FB-B2 value: phrase_equals (NUL-terminated) confirmation kind 23 vs expected_phrase kind 3");
static_assert(([]{ const TextBuf s = fx_conf(24, 0x123456789ABCDEFULL); return parse_phrase(s.c_str(), s.size()).kind; }()) == 3, "FB-B2 value: parse_phrase kind of confirmation kind 24 id 123456789ABCDEF");
static_assert(([]{ const TextBuf s = fx_conf(24, 0x123456789ABCDEFULL); return parse_phrase(s.c_str(), s.size()).id; }()) == 0x8123456789ABCDEFULL, "FB-B2 value: parse_phrase id of confirmation kind 24 id 123456789ABCDEF");
static_assert(([]{ const TextBuf s = fx_conf(24, 0x123456789ABCDEFULL); return parse_phrase(s.c_str()).kind; }()) == 3, "FB-B2 value: parse_phrase kind of confirmation kind 24 id 123456789ABCDEF (NUL-terminated)");
static_assert(([]{ const TextBuf s = fx_conf(24, 0x123456789ABCDEFULL); return phrase_equals(s.c_str(), s.size(), expected_phrase(1, 0x123456789ABCDEFULL)); }()) == 0, "FB-B2 value: phrase_equals confirmation kind 24 vs expected_phrase kind 1");
static_assert(([]{ const TextBuf s = fx_conf(24, 0x123456789ABCDEFULL); return phrase_equals(s.c_str(), expected_phrase(1, 0x123456789ABCDEFULL)); }()) == 0, "FB-B2 value: phrase_equals (NUL-terminated) confirmation kind 24 vs expected_phrase kind 1");
static_assert(([]{ const TextBuf s = fx_conf(24, 0x123456789ABCDEFULL); return phrase_equals(s.c_str(), s.size(), expected_phrase(2, 0x123456789ABCDEFULL)); }()) == 0, "FB-B2 value: phrase_equals confirmation kind 24 vs expected_phrase kind 2");
static_assert(([]{ const TextBuf s = fx_conf(24, 0x123456789ABCDEFULL); return phrase_equals(s.c_str(), expected_phrase(2, 0x123456789ABCDEFULL)); }()) == 0, "FB-B2 value: phrase_equals (NUL-terminated) confirmation kind 24 vs expected_phrase kind 2");
static_assert(([]{ const TextBuf s = fx_conf(24, 0x123456789ABCDEFULL); return phrase_equals(s.c_str(), s.size(), expected_phrase(3, 0x123456789ABCDEFULL)); }()) == 0, "FB-B2 value: phrase_equals confirmation kind 24 vs expected_phrase kind 3");
static_assert(([]{ const TextBuf s = fx_conf(24, 0x123456789ABCDEFULL); return phrase_equals(s.c_str(), expected_phrase(3, 0x123456789ABCDEFULL)); }()) == 0, "FB-B2 value: phrase_equals (NUL-terminated) confirmation kind 24 vs expected_phrase kind 3");
static_assert(([]{ const TextBuf s = fx_conf(25, 0x123456789ABCDEFULL); return parse_phrase(s.c_str(), s.size()).kind; }()) == 3, "FB-B2 value: parse_phrase kind of confirmation kind 25 id 123456789ABCDEF");
static_assert(([]{ const TextBuf s = fx_conf(25, 0x123456789ABCDEFULL); return parse_phrase(s.c_str(), s.size()).id; }()) == 0x123456689ABCDEFULL, "FB-B2 value: parse_phrase id of confirmation kind 25 id 123456789ABCDEF");
static_assert(([]{ const TextBuf s = fx_conf(25, 0x123456789ABCDEFULL); return parse_phrase(s.c_str()).kind; }()) == 3, "FB-B2 value: parse_phrase kind of confirmation kind 25 id 123456789ABCDEF (NUL-terminated)");
static_assert(([]{ const TextBuf s = fx_conf(25, 0x123456789ABCDEFULL); return phrase_equals(s.c_str(), s.size(), expected_phrase(1, 0x123456789ABCDEFULL)); }()) == 0, "FB-B2 value: phrase_equals confirmation kind 25 vs expected_phrase kind 1");
static_assert(([]{ const TextBuf s = fx_conf(25, 0x123456789ABCDEFULL); return phrase_equals(s.c_str(), expected_phrase(1, 0x123456789ABCDEFULL)); }()) == 0, "FB-B2 value: phrase_equals (NUL-terminated) confirmation kind 25 vs expected_phrase kind 1");
static_assert(([]{ const TextBuf s = fx_conf(25, 0x123456789ABCDEFULL); return phrase_equals(s.c_str(), s.size(), expected_phrase(2, 0x123456789ABCDEFULL)); }()) == 0, "FB-B2 value: phrase_equals confirmation kind 25 vs expected_phrase kind 2");
static_assert(([]{ const TextBuf s = fx_conf(25, 0x123456789ABCDEFULL); return phrase_equals(s.c_str(), expected_phrase(2, 0x123456789ABCDEFULL)); }()) == 0, "FB-B2 value: phrase_equals (NUL-terminated) confirmation kind 25 vs expected_phrase kind 2");
static_assert(([]{ const TextBuf s = fx_conf(25, 0x123456789ABCDEFULL); return phrase_equals(s.c_str(), s.size(), expected_phrase(3, 0x123456789ABCDEFULL)); }()) == 0, "FB-B2 value: phrase_equals confirmation kind 25 vs expected_phrase kind 3");
static_assert(([]{ const TextBuf s = fx_conf(25, 0x123456789ABCDEFULL); return phrase_equals(s.c_str(), expected_phrase(3, 0x123456789ABCDEFULL)); }()) == 0, "FB-B2 value: phrase_equals (NUL-terminated) confirmation kind 25 vs expected_phrase kind 3");
static_assert(([]{ const TextBuf s = fx_conf(26, 0x123456789ABCDEFULL); return parse_phrase(s.c_str(), s.size()).kind; }()) == 3, "FB-B2 value: parse_phrase kind of confirmation kind 26 id 123456789ABCDEF");
static_assert(([]{ const TextBuf s = fx_conf(26, 0x123456789ABCDEFULL); return parse_phrase(s.c_str(), s.size()).id; }()) == 0xFEDCBA9889ABCDEFULL, "FB-B2 value: parse_phrase id of confirmation kind 26 id 123456789ABCDEF");
static_assert(([]{ const TextBuf s = fx_conf(26, 0x123456789ABCDEFULL); return parse_phrase(s.c_str()).kind; }()) == 3, "FB-B2 value: parse_phrase kind of confirmation kind 26 id 123456789ABCDEF (NUL-terminated)");
static_assert(([]{ const TextBuf s = fx_conf(26, 0x123456789ABCDEFULL); return phrase_equals(s.c_str(), s.size(), expected_phrase(1, 0x123456789ABCDEFULL)); }()) == 0, "FB-B2 value: phrase_equals confirmation kind 26 vs expected_phrase kind 1");
static_assert(([]{ const TextBuf s = fx_conf(26, 0x123456789ABCDEFULL); return phrase_equals(s.c_str(), expected_phrase(1, 0x123456789ABCDEFULL)); }()) == 0, "FB-B2 value: phrase_equals (NUL-terminated) confirmation kind 26 vs expected_phrase kind 1");
static_assert(([]{ const TextBuf s = fx_conf(26, 0x123456789ABCDEFULL); return phrase_equals(s.c_str(), s.size(), expected_phrase(2, 0x123456789ABCDEFULL)); }()) == 0, "FB-B2 value: phrase_equals confirmation kind 26 vs expected_phrase kind 2");
static_assert(([]{ const TextBuf s = fx_conf(26, 0x123456789ABCDEFULL); return phrase_equals(s.c_str(), expected_phrase(2, 0x123456789ABCDEFULL)); }()) == 0, "FB-B2 value: phrase_equals (NUL-terminated) confirmation kind 26 vs expected_phrase kind 2");
static_assert(([]{ const TextBuf s = fx_conf(26, 0x123456789ABCDEFULL); return phrase_equals(s.c_str(), s.size(), expected_phrase(3, 0x123456789ABCDEFULL)); }()) == 0, "FB-B2 value: phrase_equals confirmation kind 26 vs expected_phrase kind 3");
static_assert(([]{ const TextBuf s = fx_conf(26, 0x123456789ABCDEFULL); return phrase_equals(s.c_str(), expected_phrase(3, 0x123456789ABCDEFULL)); }()) == 0, "FB-B2 value: phrase_equals (NUL-terminated) confirmation kind 26 vs expected_phrase kind 3");
static_assert(([]{ const TextBuf s = fx_conf(27, 0x123456789ABCDEFULL); return parse_phrase(s.c_str(), s.size()).kind; }()) == 3, "FB-B2 value: parse_phrase kind of confirmation kind 27 id 123456789ABCDEF");
static_assert(([]{ const TextBuf s = fx_conf(27, 0x123456789ABCDEFULL); return parse_phrase(s.c_str(), s.size()).id; }()) == 0x123456776543210ULL, "FB-B2 value: parse_phrase id of confirmation kind 27 id 123456789ABCDEF");
static_assert(([]{ const TextBuf s = fx_conf(27, 0x123456789ABCDEFULL); return parse_phrase(s.c_str()).kind; }()) == 3, "FB-B2 value: parse_phrase kind of confirmation kind 27 id 123456789ABCDEF (NUL-terminated)");
static_assert(([]{ const TextBuf s = fx_conf(27, 0x123456789ABCDEFULL); return phrase_equals(s.c_str(), s.size(), expected_phrase(1, 0x123456789ABCDEFULL)); }()) == 0, "FB-B2 value: phrase_equals confirmation kind 27 vs expected_phrase kind 1");
static_assert(([]{ const TextBuf s = fx_conf(27, 0x123456789ABCDEFULL); return phrase_equals(s.c_str(), expected_phrase(1, 0x123456789ABCDEFULL)); }()) == 0, "FB-B2 value: phrase_equals (NUL-terminated) confirmation kind 27 vs expected_phrase kind 1");
static_assert(([]{ const TextBuf s = fx_conf(27, 0x123456789ABCDEFULL); return phrase_equals(s.c_str(), s.size(), expected_phrase(2, 0x123456789ABCDEFULL)); }()) == 0, "FB-B2 value: phrase_equals confirmation kind 27 vs expected_phrase kind 2");
static_assert(([]{ const TextBuf s = fx_conf(27, 0x123456789ABCDEFULL); return phrase_equals(s.c_str(), expected_phrase(2, 0x123456789ABCDEFULL)); }()) == 0, "FB-B2 value: phrase_equals (NUL-terminated) confirmation kind 27 vs expected_phrase kind 2");
static_assert(([]{ const TextBuf s = fx_conf(27, 0x123456789ABCDEFULL); return phrase_equals(s.c_str(), s.size(), expected_phrase(3, 0x123456789ABCDEFULL)); }()) == 0, "FB-B2 value: phrase_equals confirmation kind 27 vs expected_phrase kind 3");
static_assert(([]{ const TextBuf s = fx_conf(27, 0x123456789ABCDEFULL); return phrase_equals(s.c_str(), expected_phrase(3, 0x123456789ABCDEFULL)); }()) == 0, "FB-B2 value: phrase_equals (NUL-terminated) confirmation kind 27 vs expected_phrase kind 3");
static_assert(([]{ const TextBuf s = fx_conf(0, 0x0ULL); return parse_phrase(s.c_str(), s.size()).kind; }()) == 1, "FB-B2 value: parse_phrase kind of confirmation kind 0 id 0");
static_assert(([]{ const TextBuf s = fx_conf(0, 0x0ULL); return parse_phrase(s.c_str(), s.size()).id; }()) == 0, "FB-B2 value: parse_phrase id of confirmation kind 0 id 0");
static_assert(([]{ const TextBuf s = fx_conf(0, 0x0ULL); return parse_phrase(s.c_str()).kind; }()) == 1, "FB-B2 value: parse_phrase kind of confirmation kind 0 id 0 (NUL-terminated)");
static_assert(([]{ const TextBuf s = fx_conf(1, 0x0ULL); return parse_phrase(s.c_str(), s.size()).kind; }()) == 2, "FB-B2 value: parse_phrase kind of confirmation kind 1 id 0");
static_assert(([]{ const TextBuf s = fx_conf(1, 0x0ULL); return parse_phrase(s.c_str(), s.size()).id; }()) == 0, "FB-B2 value: parse_phrase id of confirmation kind 1 id 0");
static_assert(([]{ const TextBuf s = fx_conf(1, 0x0ULL); return parse_phrase(s.c_str()).kind; }()) == 2, "FB-B2 value: parse_phrase kind of confirmation kind 1 id 0 (NUL-terminated)");
static_assert(([]{ const TextBuf s = fx_conf(2, 0x0ULL); return parse_phrase(s.c_str(), s.size()).kind; }()) == 3, "FB-B2 value: parse_phrase kind of confirmation kind 2 id 0");
static_assert(([]{ const TextBuf s = fx_conf(2, 0x0ULL); return parse_phrase(s.c_str(), s.size()).id; }()) == 0, "FB-B2 value: parse_phrase id of confirmation kind 2 id 0");
static_assert(([]{ const TextBuf s = fx_conf(2, 0x0ULL); return parse_phrase(s.c_str()).kind; }()) == 3, "FB-B2 value: parse_phrase kind of confirmation kind 2 id 0 (NUL-terminated)");
static_assert(([]{ const TextBuf s = fx_conf(3, 0x0ULL); return parse_phrase(s.c_str(), s.size()).kind; }()) == 0, "FB-B2 value: parse_phrase kind of confirmation kind 3 id 0");
static_assert(([]{ const TextBuf s = fx_conf(3, 0x0ULL); return parse_phrase(s.c_str(), s.size()).id; }()) == 0, "FB-B2 value: parse_phrase id of confirmation kind 3 id 0");
static_assert(([]{ const TextBuf s = fx_conf(3, 0x0ULL); return parse_phrase(s.c_str()).kind; }()) == 0, "FB-B2 value: parse_phrase kind of confirmation kind 3 id 0 (NUL-terminated)");
static_assert(([]{ const TextBuf s = fx_conf(4, 0x0ULL); return parse_phrase(s.c_str(), s.size()).kind; }()) == 0, "FB-B2 value: parse_phrase kind of confirmation kind 4 id 0");
static_assert(([]{ const TextBuf s = fx_conf(4, 0x0ULL); return parse_phrase(s.c_str(), s.size()).id; }()) == 0, "FB-B2 value: parse_phrase id of confirmation kind 4 id 0");
static_assert(([]{ const TextBuf s = fx_conf(4, 0x0ULL); return parse_phrase(s.c_str()).kind; }()) == 0, "FB-B2 value: parse_phrase kind of confirmation kind 4 id 0 (NUL-terminated)");
static_assert(([]{ const TextBuf s = fx_conf(5, 0x0ULL); return parse_phrase(s.c_str(), s.size()).kind; }()) == 1, "FB-B2 value: parse_phrase kind of confirmation kind 5 id 0");
static_assert(([]{ const TextBuf s = fx_conf(5, 0x0ULL); return parse_phrase(s.c_str(), s.size()).id; }()) == 0, "FB-B2 value: parse_phrase id of confirmation kind 5 id 0");
static_assert(([]{ const TextBuf s = fx_conf(5, 0x0ULL); return parse_phrase(s.c_str()).kind; }()) == 1, "FB-B2 value: parse_phrase kind of confirmation kind 5 id 0 (NUL-terminated)");
static_assert(([]{ const TextBuf s = fx_conf(6, 0x0ULL); return parse_phrase(s.c_str(), s.size()).kind; }()) == 0, "FB-B2 value: parse_phrase kind of confirmation kind 6 id 0");
static_assert(([]{ const TextBuf s = fx_conf(6, 0x0ULL); return parse_phrase(s.c_str(), s.size()).id; }()) == 0, "FB-B2 value: parse_phrase id of confirmation kind 6 id 0");
static_assert(([]{ const TextBuf s = fx_conf(6, 0x0ULL); return parse_phrase(s.c_str()).kind; }()) == 0, "FB-B2 value: parse_phrase kind of confirmation kind 6 id 0 (NUL-terminated)");
static_assert(([]{ const TextBuf s = fx_conf(7, 0x0ULL); return parse_phrase(s.c_str(), s.size()).kind; }()) == 0, "FB-B2 value: parse_phrase kind of confirmation kind 7 id 0");
static_assert(([]{ const TextBuf s = fx_conf(7, 0x0ULL); return parse_phrase(s.c_str(), s.size()).id; }()) == 0, "FB-B2 value: parse_phrase id of confirmation kind 7 id 0");
static_assert(([]{ const TextBuf s = fx_conf(7, 0x0ULL); return parse_phrase(s.c_str()).kind; }()) == 0, "FB-B2 value: parse_phrase kind of confirmation kind 7 id 0 (NUL-terminated)");
static_assert(([]{ const TextBuf s = fx_conf(8, 0x0ULL); return parse_phrase(s.c_str(), s.size()).kind; }()) == 0, "FB-B2 value: parse_phrase kind of confirmation kind 8 id 0");
static_assert(([]{ const TextBuf s = fx_conf(8, 0x0ULL); return parse_phrase(s.c_str(), s.size()).id; }()) == 0, "FB-B2 value: parse_phrase id of confirmation kind 8 id 0");
static_assert(([]{ const TextBuf s = fx_conf(8, 0x0ULL); return parse_phrase(s.c_str()).kind; }()) == 0, "FB-B2 value: parse_phrase kind of confirmation kind 8 id 0 (NUL-terminated)");
static_assert(([]{ const TextBuf s = fx_conf(9, 0x0ULL); return parse_phrase(s.c_str(), s.size()).kind; }()) == 0, "FB-B2 value: parse_phrase kind of confirmation kind 9 id 0");
static_assert(([]{ const TextBuf s = fx_conf(9, 0x0ULL); return parse_phrase(s.c_str(), s.size()).id; }()) == 0, "FB-B2 value: parse_phrase id of confirmation kind 9 id 0");
static_assert(([]{ const TextBuf s = fx_conf(9, 0x0ULL); return parse_phrase(s.c_str()).kind; }()) == 0, "FB-B2 value: parse_phrase kind of confirmation kind 9 id 0 (NUL-terminated)");
static_assert(([]{ const TextBuf s = fx_conf(10, 0x0ULL); return parse_phrase(s.c_str(), s.size()).kind; }()) == 0, "FB-B2 value: parse_phrase kind of confirmation kind 10 id 0");
static_assert(([]{ const TextBuf s = fx_conf(10, 0x0ULL); return parse_phrase(s.c_str(), s.size()).id; }()) == 0, "FB-B2 value: parse_phrase id of confirmation kind 10 id 0");
static_assert(([]{ const TextBuf s = fx_conf(10, 0x0ULL); return parse_phrase(s.c_str()).kind; }()) == 0, "FB-B2 value: parse_phrase kind of confirmation kind 10 id 0 (NUL-terminated)");
static_assert(([]{ const TextBuf s = fx_conf(11, 0x0ULL); return parse_phrase(s.c_str(), s.size()).kind; }()) == 0, "FB-B2 value: parse_phrase kind of confirmation kind 11 id 0");
static_assert(([]{ const TextBuf s = fx_conf(11, 0x0ULL); return parse_phrase(s.c_str(), s.size()).id; }()) == 0, "FB-B2 value: parse_phrase id of confirmation kind 11 id 0");
static_assert(([]{ const TextBuf s = fx_conf(11, 0x0ULL); return parse_phrase(s.c_str()).kind; }()) == 0, "FB-B2 value: parse_phrase kind of confirmation kind 11 id 0 (NUL-terminated)");
static_assert(([]{ const TextBuf s = fx_conf(12, 0x0ULL); return parse_phrase(s.c_str(), s.size()).kind; }()) == 0, "FB-B2 value: parse_phrase kind of confirmation kind 12 id 0");
static_assert(([]{ const TextBuf s = fx_conf(12, 0x0ULL); return parse_phrase(s.c_str(), s.size()).id; }()) == 0, "FB-B2 value: parse_phrase id of confirmation kind 12 id 0");
static_assert(([]{ const TextBuf s = fx_conf(12, 0x0ULL); return parse_phrase(s.c_str()).kind; }()) == 0, "FB-B2 value: parse_phrase kind of confirmation kind 12 id 0 (NUL-terminated)");
static_assert(([]{ const TextBuf s = fx_conf(13, 0x0ULL); return parse_phrase(s.c_str(), s.size()).kind; }()) == 0, "FB-B2 value: parse_phrase kind of confirmation kind 13 id 0");
static_assert(([]{ const TextBuf s = fx_conf(13, 0x0ULL); return parse_phrase(s.c_str(), s.size()).id; }()) == 0, "FB-B2 value: parse_phrase id of confirmation kind 13 id 0");
static_assert(([]{ const TextBuf s = fx_conf(13, 0x0ULL); return parse_phrase(s.c_str()).kind; }()) == 0, "FB-B2 value: parse_phrase kind of confirmation kind 13 id 0 (NUL-terminated)");
static_assert(([]{ const TextBuf s = fx_conf(14, 0x0ULL); return parse_phrase(s.c_str(), s.size()).kind; }()) == 1, "FB-B2 value: parse_phrase kind of confirmation kind 14 id 0");
static_assert(([]{ const TextBuf s = fx_conf(14, 0x0ULL); return parse_phrase(s.c_str(), s.size()).id; }()) == 1, "FB-B2 value: parse_phrase id of confirmation kind 14 id 0");
static_assert(([]{ const TextBuf s = fx_conf(14, 0x0ULL); return parse_phrase(s.c_str()).kind; }()) == 1, "FB-B2 value: parse_phrase kind of confirmation kind 14 id 0 (NUL-terminated)");
static_assert(([]{ const TextBuf s = fx_conf(15, 0x0ULL); return parse_phrase(s.c_str(), s.size()).kind; }()) == 0, "FB-B2 value: parse_phrase kind of confirmation kind 15 id 0");
static_assert(([]{ const TextBuf s = fx_conf(15, 0x0ULL); return parse_phrase(s.c_str(), s.size()).id; }()) == 0, "FB-B2 value: parse_phrase id of confirmation kind 15 id 0");
static_assert(([]{ const TextBuf s = fx_conf(15, 0x0ULL); return parse_phrase(s.c_str()).kind; }()) == 0, "FB-B2 value: parse_phrase kind of confirmation kind 15 id 0 (NUL-terminated)");
static_assert(([]{ const TextBuf s = fx_conf(16, 0x0ULL); return parse_phrase(s.c_str(), s.size()).kind; }()) == 0, "FB-B2 value: parse_phrase kind of confirmation kind 16 id 0");
static_assert(([]{ const TextBuf s = fx_conf(16, 0x0ULL); return parse_phrase(s.c_str(), s.size()).id; }()) == 0, "FB-B2 value: parse_phrase id of confirmation kind 16 id 0");
static_assert(([]{ const TextBuf s = fx_conf(16, 0x0ULL); return parse_phrase(s.c_str()).kind; }()) == 0, "FB-B2 value: parse_phrase kind of confirmation kind 16 id 0 (NUL-terminated)");
static_assert(([]{ const TextBuf s = fx_conf(17, 0x0ULL); return parse_phrase(s.c_str(), s.size()).kind; }()) == 0, "FB-B2 value: parse_phrase kind of confirmation kind 17 id 0");
static_assert(([]{ const TextBuf s = fx_conf(17, 0x0ULL); return parse_phrase(s.c_str(), s.size()).id; }()) == 0, "FB-B2 value: parse_phrase id of confirmation kind 17 id 0");
static_assert(([]{ const TextBuf s = fx_conf(17, 0x0ULL); return parse_phrase(s.c_str()).kind; }()) == 0, "FB-B2 value: parse_phrase kind of confirmation kind 17 id 0 (NUL-terminated)");
static_assert(([]{ const TextBuf s = fx_conf(18, 0x0ULL); return parse_phrase(s.c_str(), s.size()).kind; }()) == 0, "FB-B2 value: parse_phrase kind of confirmation kind 18 id 0");
static_assert(([]{ const TextBuf s = fx_conf(18, 0x0ULL); return parse_phrase(s.c_str(), s.size()).id; }()) == 0, "FB-B2 value: parse_phrase id of confirmation kind 18 id 0");
static_assert(([]{ const TextBuf s = fx_conf(18, 0x0ULL); return parse_phrase(s.c_str()).kind; }()) == 0, "FB-B2 value: parse_phrase kind of confirmation kind 18 id 0 (NUL-terminated)");
static_assert(([]{ const TextBuf s = fx_conf(19, 0x0ULL); return parse_phrase(s.c_str(), s.size()).kind; }()) == 3, "FB-B2 value: parse_phrase kind of confirmation kind 19 id 0");
static_assert(([]{ const TextBuf s = fx_conf(19, 0x0ULL); return parse_phrase(s.c_str(), s.size()).id; }()) == 0, "FB-B2 value: parse_phrase id of confirmation kind 19 id 0");
static_assert(([]{ const TextBuf s = fx_conf(19, 0x0ULL); return parse_phrase(s.c_str()).kind; }()) == 3, "FB-B2 value: parse_phrase kind of confirmation kind 19 id 0 (NUL-terminated)");
static_assert(([]{ const TextBuf s = fx_conf(20, 0x0ULL); return parse_phrase(s.c_str(), s.size()).kind; }()) == 3, "FB-B2 value: parse_phrase kind of confirmation kind 20 id 0");
static_assert(([]{ const TextBuf s = fx_conf(20, 0x0ULL); return parse_phrase(s.c_str(), s.size()).id; }()) == 1, "FB-B2 value: parse_phrase id of confirmation kind 20 id 0");
static_assert(([]{ const TextBuf s = fx_conf(20, 0x0ULL); return parse_phrase(s.c_str()).kind; }()) == 3, "FB-B2 value: parse_phrase kind of confirmation kind 20 id 0 (NUL-terminated)");
static_assert(([]{ const TextBuf s = fx_conf(21, 0x0ULL); return parse_phrase(s.c_str(), s.size()).kind; }()) == 0, "FB-B2 value: parse_phrase kind of confirmation kind 21 id 0");
static_assert(([]{ const TextBuf s = fx_conf(21, 0x0ULL); return parse_phrase(s.c_str(), s.size()).id; }()) == 0, "FB-B2 value: parse_phrase id of confirmation kind 21 id 0");
static_assert(([]{ const TextBuf s = fx_conf(21, 0x0ULL); return parse_phrase(s.c_str()).kind; }()) == 1, "FB-B2 value: parse_phrase kind of confirmation kind 21 id 0 (NUL-terminated)");
static_assert(([]{ const TextBuf s = fx_conf(22, 0x0ULL); return parse_phrase(s.c_str(), s.size()).kind; }()) == 0, "FB-B2 value: parse_phrase kind of confirmation kind 22 id 0");
static_assert(([]{ const TextBuf s = fx_conf(22, 0x0ULL); return parse_phrase(s.c_str(), s.size()).id; }()) == 0, "FB-B2 value: parse_phrase id of confirmation kind 22 id 0");
static_assert(([]{ const TextBuf s = fx_conf(22, 0x0ULL); return parse_phrase(s.c_str()).kind; }()) == 1, "FB-B2 value: parse_phrase kind of confirmation kind 22 id 0 (NUL-terminated)");
static_assert(([]{ const TextBuf s = fx_conf(23, 0x0ULL); return parse_phrase(s.c_str(), s.size()).kind; }()) == 0, "FB-B2 value: parse_phrase kind of confirmation kind 23 id 0");
static_assert(([]{ const TextBuf s = fx_conf(23, 0x0ULL); return parse_phrase(s.c_str(), s.size()).id; }()) == 0, "FB-B2 value: parse_phrase id of confirmation kind 23 id 0");
static_assert(([]{ const TextBuf s = fx_conf(23, 0x0ULL); return parse_phrase(s.c_str()).kind; }()) == 3, "FB-B2 value: parse_phrase kind of confirmation kind 23 id 0 (NUL-terminated)");
static_assert(([]{ const TextBuf s = fx_conf(24, 0x0ULL); return parse_phrase(s.c_str(), s.size()).kind; }()) == 3, "FB-B2 value: parse_phrase kind of confirmation kind 24 id 0");
static_assert(([]{ const TextBuf s = fx_conf(24, 0x0ULL); return parse_phrase(s.c_str(), s.size()).id; }()) == 0x8000000000000000ULL, "FB-B2 value: parse_phrase id of confirmation kind 24 id 0");
static_assert(([]{ const TextBuf s = fx_conf(24, 0x0ULL); return parse_phrase(s.c_str()).kind; }()) == 3, "FB-B2 value: parse_phrase kind of confirmation kind 24 id 0 (NUL-terminated)");
static_assert(([]{ const TextBuf s = fx_conf(25, 0x0ULL); return parse_phrase(s.c_str(), s.size()).kind; }()) == 3, "FB-B2 value: parse_phrase kind of confirmation kind 25 id 0");
static_assert(([]{ const TextBuf s = fx_conf(25, 0x0ULL); return parse_phrase(s.c_str(), s.size()).id; }()) == 0x100000000ULL, "FB-B2 value: parse_phrase id of confirmation kind 25 id 0");
static_assert(([]{ const TextBuf s = fx_conf(25, 0x0ULL); return parse_phrase(s.c_str()).kind; }()) == 3, "FB-B2 value: parse_phrase kind of confirmation kind 25 id 0 (NUL-terminated)");
static_assert(([]{ const TextBuf s = fx_conf(26, 0x0ULL); return parse_phrase(s.c_str(), s.size()).kind; }()) == 3, "FB-B2 value: parse_phrase kind of confirmation kind 26 id 0");
static_assert(([]{ const TextBuf s = fx_conf(26, 0x0ULL); return parse_phrase(s.c_str(), s.size()).id; }()) == 0xFFFFFFFF00000000ULL, "FB-B2 value: parse_phrase id of confirmation kind 26 id 0");
static_assert(([]{ const TextBuf s = fx_conf(26, 0x0ULL); return parse_phrase(s.c_str()).kind; }()) == 3, "FB-B2 value: parse_phrase kind of confirmation kind 26 id 0 (NUL-terminated)");
static_assert(([]{ const TextBuf s = fx_conf(27, 0x0ULL); return parse_phrase(s.c_str(), s.size()).kind; }()) == 3, "FB-B2 value: parse_phrase kind of confirmation kind 27 id 0");
static_assert(([]{ const TextBuf s = fx_conf(27, 0x0ULL); return parse_phrase(s.c_str(), s.size()).id; }()) == 4294967295u, "FB-B2 value: parse_phrase id of confirmation kind 27 id 0");
static_assert(([]{ const TextBuf s = fx_conf(27, 0x0ULL); return parse_phrase(s.c_str()).kind; }()) == 3, "FB-B2 value: parse_phrase kind of confirmation kind 27 id 0 (NUL-terminated)");
static_assert(([]{ const TextBuf s = fx_conf(0, 0xFFFFFFFFFFFFFFFFULL); return parse_phrase(s.c_str(), s.size()).kind; }()) == 1, "FB-B2 value: parse_phrase kind of confirmation kind 0 id FFFFFFFFFFFFFFFF");
static_assert(([]{ const TextBuf s = fx_conf(0, 0xFFFFFFFFFFFFFFFFULL); return parse_phrase(s.c_str(), s.size()).id; }()) == 0xFFFFFFFFFFFFFFFFULL, "FB-B2 value: parse_phrase id of confirmation kind 0 id FFFFFFFFFFFFFFFF");
static_assert(([]{ const TextBuf s = fx_conf(0, 0xFFFFFFFFFFFFFFFFULL); return parse_phrase(s.c_str()).kind; }()) == 1, "FB-B2 value: parse_phrase kind of confirmation kind 0 id FFFFFFFFFFFFFFFF (NUL-terminated)");
static_assert(([]{ const TextBuf s = fx_conf(1, 0xFFFFFFFFFFFFFFFFULL); return parse_phrase(s.c_str(), s.size()).kind; }()) == 2, "FB-B2 value: parse_phrase kind of confirmation kind 1 id FFFFFFFFFFFFFFFF");
static_assert(([]{ const TextBuf s = fx_conf(1, 0xFFFFFFFFFFFFFFFFULL); return parse_phrase(s.c_str(), s.size()).id; }()) == 0xFFFFFFFFFFFFFFFFULL, "FB-B2 value: parse_phrase id of confirmation kind 1 id FFFFFFFFFFFFFFFF");
static_assert(([]{ const TextBuf s = fx_conf(1, 0xFFFFFFFFFFFFFFFFULL); return parse_phrase(s.c_str()).kind; }()) == 2, "FB-B2 value: parse_phrase kind of confirmation kind 1 id FFFFFFFFFFFFFFFF (NUL-terminated)");
static_assert(([]{ const TextBuf s = fx_conf(2, 0xFFFFFFFFFFFFFFFFULL); return parse_phrase(s.c_str(), s.size()).kind; }()) == 3, "FB-B2 value: parse_phrase kind of confirmation kind 2 id FFFFFFFFFFFFFFFF");
static_assert(([]{ const TextBuf s = fx_conf(2, 0xFFFFFFFFFFFFFFFFULL); return parse_phrase(s.c_str(), s.size()).id; }()) == 0xFFFFFFFFFFFFFFFFULL, "FB-B2 value: parse_phrase id of confirmation kind 2 id FFFFFFFFFFFFFFFF");
static_assert(([]{ const TextBuf s = fx_conf(2, 0xFFFFFFFFFFFFFFFFULL); return parse_phrase(s.c_str()).kind; }()) == 3, "FB-B2 value: parse_phrase kind of confirmation kind 2 id FFFFFFFFFFFFFFFF (NUL-terminated)");
static_assert(([]{ const TextBuf s = fx_conf(3, 0xFFFFFFFFFFFFFFFFULL); return parse_phrase(s.c_str(), s.size()).kind; }()) == 0, "FB-B2 value: parse_phrase kind of confirmation kind 3 id FFFFFFFFFFFFFFFF");
static_assert(([]{ const TextBuf s = fx_conf(3, 0xFFFFFFFFFFFFFFFFULL); return parse_phrase(s.c_str(), s.size()).id; }()) == 0, "FB-B2 value: parse_phrase id of confirmation kind 3 id FFFFFFFFFFFFFFFF");
static_assert(([]{ const TextBuf s = fx_conf(3, 0xFFFFFFFFFFFFFFFFULL); return parse_phrase(s.c_str()).kind; }()) == 0, "FB-B2 value: parse_phrase kind of confirmation kind 3 id FFFFFFFFFFFFFFFF (NUL-terminated)");
static_assert(([]{ const TextBuf s = fx_conf(4, 0xFFFFFFFFFFFFFFFFULL); return parse_phrase(s.c_str(), s.size()).kind; }()) == 0, "FB-B2 value: parse_phrase kind of confirmation kind 4 id FFFFFFFFFFFFFFFF");
static_assert(([]{ const TextBuf s = fx_conf(4, 0xFFFFFFFFFFFFFFFFULL); return parse_phrase(s.c_str(), s.size()).id; }()) == 0, "FB-B2 value: parse_phrase id of confirmation kind 4 id FFFFFFFFFFFFFFFF");
static_assert(([]{ const TextBuf s = fx_conf(4, 0xFFFFFFFFFFFFFFFFULL); return parse_phrase(s.c_str()).kind; }()) == 0, "FB-B2 value: parse_phrase kind of confirmation kind 4 id FFFFFFFFFFFFFFFF (NUL-terminated)");
static_assert(([]{ const TextBuf s = fx_conf(5, 0xFFFFFFFFFFFFFFFFULL); return parse_phrase(s.c_str(), s.size()).kind; }()) == 0, "FB-B2 value: parse_phrase kind of confirmation kind 5 id FFFFFFFFFFFFFFFF");
static_assert(([]{ const TextBuf s = fx_conf(5, 0xFFFFFFFFFFFFFFFFULL); return parse_phrase(s.c_str(), s.size()).id; }()) == 0, "FB-B2 value: parse_phrase id of confirmation kind 5 id FFFFFFFFFFFFFFFF");
static_assert(([]{ const TextBuf s = fx_conf(5, 0xFFFFFFFFFFFFFFFFULL); return parse_phrase(s.c_str()).kind; }()) == 0, "FB-B2 value: parse_phrase kind of confirmation kind 5 id FFFFFFFFFFFFFFFF (NUL-terminated)");
static_assert(([]{ const TextBuf s = fx_conf(6, 0xFFFFFFFFFFFFFFFFULL); return parse_phrase(s.c_str(), s.size()).kind; }()) == 0, "FB-B2 value: parse_phrase kind of confirmation kind 6 id FFFFFFFFFFFFFFFF");
static_assert(([]{ const TextBuf s = fx_conf(6, 0xFFFFFFFFFFFFFFFFULL); return parse_phrase(s.c_str(), s.size()).id; }()) == 0, "FB-B2 value: parse_phrase id of confirmation kind 6 id FFFFFFFFFFFFFFFF");
static_assert(([]{ const TextBuf s = fx_conf(6, 0xFFFFFFFFFFFFFFFFULL); return parse_phrase(s.c_str()).kind; }()) == 0, "FB-B2 value: parse_phrase kind of confirmation kind 6 id FFFFFFFFFFFFFFFF (NUL-terminated)");
static_assert(([]{ const TextBuf s = fx_conf(7, 0xFFFFFFFFFFFFFFFFULL); return parse_phrase(s.c_str(), s.size()).kind; }()) == 0, "FB-B2 value: parse_phrase kind of confirmation kind 7 id FFFFFFFFFFFFFFFF");
static_assert(([]{ const TextBuf s = fx_conf(7, 0xFFFFFFFFFFFFFFFFULL); return parse_phrase(s.c_str(), s.size()).id; }()) == 0, "FB-B2 value: parse_phrase id of confirmation kind 7 id FFFFFFFFFFFFFFFF");
static_assert(([]{ const TextBuf s = fx_conf(7, 0xFFFFFFFFFFFFFFFFULL); return parse_phrase(s.c_str()).kind; }()) == 0, "FB-B2 value: parse_phrase kind of confirmation kind 7 id FFFFFFFFFFFFFFFF (NUL-terminated)");
static_assert(([]{ const TextBuf s = fx_conf(8, 0xFFFFFFFFFFFFFFFFULL); return parse_phrase(s.c_str(), s.size()).kind; }()) == 0, "FB-B2 value: parse_phrase kind of confirmation kind 8 id FFFFFFFFFFFFFFFF");
static_assert(([]{ const TextBuf s = fx_conf(8, 0xFFFFFFFFFFFFFFFFULL); return parse_phrase(s.c_str(), s.size()).id; }()) == 0, "FB-B2 value: parse_phrase id of confirmation kind 8 id FFFFFFFFFFFFFFFF");
static_assert(([]{ const TextBuf s = fx_conf(8, 0xFFFFFFFFFFFFFFFFULL); return parse_phrase(s.c_str()).kind; }()) == 0, "FB-B2 value: parse_phrase kind of confirmation kind 8 id FFFFFFFFFFFFFFFF (NUL-terminated)");
static_assert(([]{ const TextBuf s = fx_conf(9, 0xFFFFFFFFFFFFFFFFULL); return parse_phrase(s.c_str(), s.size()).kind; }()) == 0, "FB-B2 value: parse_phrase kind of confirmation kind 9 id FFFFFFFFFFFFFFFF");
static_assert(([]{ const TextBuf s = fx_conf(9, 0xFFFFFFFFFFFFFFFFULL); return parse_phrase(s.c_str(), s.size()).id; }()) == 0, "FB-B2 value: parse_phrase id of confirmation kind 9 id FFFFFFFFFFFFFFFF");
static_assert(([]{ const TextBuf s = fx_conf(9, 0xFFFFFFFFFFFFFFFFULL); return parse_phrase(s.c_str()).kind; }()) == 0, "FB-B2 value: parse_phrase kind of confirmation kind 9 id FFFFFFFFFFFFFFFF (NUL-terminated)");
static_assert(([]{ const TextBuf s = fx_conf(10, 0xFFFFFFFFFFFFFFFFULL); return parse_phrase(s.c_str(), s.size()).kind; }()) == 0, "FB-B2 value: parse_phrase kind of confirmation kind 10 id FFFFFFFFFFFFFFFF");
static_assert(([]{ const TextBuf s = fx_conf(10, 0xFFFFFFFFFFFFFFFFULL); return parse_phrase(s.c_str(), s.size()).id; }()) == 0, "FB-B2 value: parse_phrase id of confirmation kind 10 id FFFFFFFFFFFFFFFF");
static_assert(([]{ const TextBuf s = fx_conf(10, 0xFFFFFFFFFFFFFFFFULL); return parse_phrase(s.c_str()).kind; }()) == 0, "FB-B2 value: parse_phrase kind of confirmation kind 10 id FFFFFFFFFFFFFFFF (NUL-terminated)");
static_assert(([]{ const TextBuf s = fx_conf(11, 0xFFFFFFFFFFFFFFFFULL); return parse_phrase(s.c_str(), s.size()).kind; }()) == 0, "FB-B2 value: parse_phrase kind of confirmation kind 11 id FFFFFFFFFFFFFFFF");
static_assert(([]{ const TextBuf s = fx_conf(11, 0xFFFFFFFFFFFFFFFFULL); return parse_phrase(s.c_str(), s.size()).id; }()) == 0, "FB-B2 value: parse_phrase id of confirmation kind 11 id FFFFFFFFFFFFFFFF");
static_assert(([]{ const TextBuf s = fx_conf(11, 0xFFFFFFFFFFFFFFFFULL); return parse_phrase(s.c_str()).kind; }()) == 0, "FB-B2 value: parse_phrase kind of confirmation kind 11 id FFFFFFFFFFFFFFFF (NUL-terminated)");
static_assert(([]{ const TextBuf s = fx_conf(12, 0xFFFFFFFFFFFFFFFFULL); return parse_phrase(s.c_str(), s.size()).kind; }()) == 0, "FB-B2 value: parse_phrase kind of confirmation kind 12 id FFFFFFFFFFFFFFFF");
static_assert(([]{ const TextBuf s = fx_conf(12, 0xFFFFFFFFFFFFFFFFULL); return parse_phrase(s.c_str(), s.size()).id; }()) == 0, "FB-B2 value: parse_phrase id of confirmation kind 12 id FFFFFFFFFFFFFFFF");
static_assert(([]{ const TextBuf s = fx_conf(12, 0xFFFFFFFFFFFFFFFFULL); return parse_phrase(s.c_str()).kind; }()) == 0, "FB-B2 value: parse_phrase kind of confirmation kind 12 id FFFFFFFFFFFFFFFF (NUL-terminated)");
static_assert(([]{ const TextBuf s = fx_conf(13, 0xFFFFFFFFFFFFFFFFULL); return parse_phrase(s.c_str(), s.size()).kind; }()) == 0, "FB-B2 value: parse_phrase kind of confirmation kind 13 id FFFFFFFFFFFFFFFF");
static_assert(([]{ const TextBuf s = fx_conf(13, 0xFFFFFFFFFFFFFFFFULL); return parse_phrase(s.c_str(), s.size()).id; }()) == 0, "FB-B2 value: parse_phrase id of confirmation kind 13 id FFFFFFFFFFFFFFFF");
static_assert(([]{ const TextBuf s = fx_conf(13, 0xFFFFFFFFFFFFFFFFULL); return parse_phrase(s.c_str()).kind; }()) == 0, "FB-B2 value: parse_phrase kind of confirmation kind 13 id FFFFFFFFFFFFFFFF (NUL-terminated)");
static_assert(([]{ const TextBuf s = fx_conf(14, 0xFFFFFFFFFFFFFFFFULL); return parse_phrase(s.c_str(), s.size()).kind; }()) == 1, "FB-B2 value: parse_phrase kind of confirmation kind 14 id FFFFFFFFFFFFFFFF");
static_assert(([]{ const TextBuf s = fx_conf(14, 0xFFFFFFFFFFFFFFFFULL); return parse_phrase(s.c_str(), s.size()).id; }()) == 0xFFFFFFFFFFFFFFFEULL, "FB-B2 value: parse_phrase id of confirmation kind 14 id FFFFFFFFFFFFFFFF");
static_assert(([]{ const TextBuf s = fx_conf(14, 0xFFFFFFFFFFFFFFFFULL); return parse_phrase(s.c_str()).kind; }()) == 1, "FB-B2 value: parse_phrase kind of confirmation kind 14 id FFFFFFFFFFFFFFFF (NUL-terminated)");
static_assert(([]{ const TextBuf s = fx_conf(15, 0xFFFFFFFFFFFFFFFFULL); return parse_phrase(s.c_str(), s.size()).kind; }()) == 0, "FB-B2 value: parse_phrase kind of confirmation kind 15 id FFFFFFFFFFFFFFFF");
static_assert(([]{ const TextBuf s = fx_conf(15, 0xFFFFFFFFFFFFFFFFULL); return parse_phrase(s.c_str(), s.size()).id; }()) == 0, "FB-B2 value: parse_phrase id of confirmation kind 15 id FFFFFFFFFFFFFFFF");
static_assert(([]{ const TextBuf s = fx_conf(15, 0xFFFFFFFFFFFFFFFFULL); return parse_phrase(s.c_str()).kind; }()) == 0, "FB-B2 value: parse_phrase kind of confirmation kind 15 id FFFFFFFFFFFFFFFF (NUL-terminated)");
static_assert(([]{ const TextBuf s = fx_conf(16, 0xFFFFFFFFFFFFFFFFULL); return parse_phrase(s.c_str(), s.size()).kind; }()) == 0, "FB-B2 value: parse_phrase kind of confirmation kind 16 id FFFFFFFFFFFFFFFF");
static_assert(([]{ const TextBuf s = fx_conf(16, 0xFFFFFFFFFFFFFFFFULL); return parse_phrase(s.c_str(), s.size()).id; }()) == 0, "FB-B2 value: parse_phrase id of confirmation kind 16 id FFFFFFFFFFFFFFFF");
static_assert(([]{ const TextBuf s = fx_conf(16, 0xFFFFFFFFFFFFFFFFULL); return parse_phrase(s.c_str()).kind; }()) == 0, "FB-B2 value: parse_phrase kind of confirmation kind 16 id FFFFFFFFFFFFFFFF (NUL-terminated)");
static_assert(([]{ const TextBuf s = fx_conf(17, 0xFFFFFFFFFFFFFFFFULL); return parse_phrase(s.c_str(), s.size()).kind; }()) == 0, "FB-B2 value: parse_phrase kind of confirmation kind 17 id FFFFFFFFFFFFFFFF");
static_assert(([]{ const TextBuf s = fx_conf(17, 0xFFFFFFFFFFFFFFFFULL); return parse_phrase(s.c_str(), s.size()).id; }()) == 0, "FB-B2 value: parse_phrase id of confirmation kind 17 id FFFFFFFFFFFFFFFF");
static_assert(([]{ const TextBuf s = fx_conf(17, 0xFFFFFFFFFFFFFFFFULL); return parse_phrase(s.c_str()).kind; }()) == 0, "FB-B2 value: parse_phrase kind of confirmation kind 17 id FFFFFFFFFFFFFFFF (NUL-terminated)");
static_assert(([]{ const TextBuf s = fx_conf(18, 0xFFFFFFFFFFFFFFFFULL); return parse_phrase(s.c_str(), s.size()).kind; }()) == 0, "FB-B2 value: parse_phrase kind of confirmation kind 18 id FFFFFFFFFFFFFFFF");
static_assert(([]{ const TextBuf s = fx_conf(18, 0xFFFFFFFFFFFFFFFFULL); return parse_phrase(s.c_str(), s.size()).id; }()) == 0, "FB-B2 value: parse_phrase id of confirmation kind 18 id FFFFFFFFFFFFFFFF");
static_assert(([]{ const TextBuf s = fx_conf(18, 0xFFFFFFFFFFFFFFFFULL); return parse_phrase(s.c_str()).kind; }()) == 0, "FB-B2 value: parse_phrase kind of confirmation kind 18 id FFFFFFFFFFFFFFFF (NUL-terminated)");
static_assert(([]{ const TextBuf s = fx_conf(19, 0xFFFFFFFFFFFFFFFFULL); return parse_phrase(s.c_str(), s.size()).kind; }()) == 0, "FB-B2 value: parse_phrase kind of confirmation kind 19 id FFFFFFFFFFFFFFFF");
static_assert(([]{ const TextBuf s = fx_conf(19, 0xFFFFFFFFFFFFFFFFULL); return parse_phrase(s.c_str(), s.size()).id; }()) == 0, "FB-B2 value: parse_phrase id of confirmation kind 19 id FFFFFFFFFFFFFFFF");
static_assert(([]{ const TextBuf s = fx_conf(19, 0xFFFFFFFFFFFFFFFFULL); return parse_phrase(s.c_str()).kind; }()) == 0, "FB-B2 value: parse_phrase kind of confirmation kind 19 id FFFFFFFFFFFFFFFF (NUL-terminated)");
static_assert(([]{ const TextBuf s = fx_conf(20, 0xFFFFFFFFFFFFFFFFULL); return parse_phrase(s.c_str(), s.size()).kind; }()) == 3, "FB-B2 value: parse_phrase kind of confirmation kind 20 id FFFFFFFFFFFFFFFF");
static_assert(([]{ const TextBuf s = fx_conf(20, 0xFFFFFFFFFFFFFFFFULL); return parse_phrase(s.c_str(), s.size()).id; }()) == 0xFFFFFFFFFFFFFFFEULL, "FB-B2 value: parse_phrase id of confirmation kind 20 id FFFFFFFFFFFFFFFF");
static_assert(([]{ const TextBuf s = fx_conf(20, 0xFFFFFFFFFFFFFFFFULL); return parse_phrase(s.c_str()).kind; }()) == 3, "FB-B2 value: parse_phrase kind of confirmation kind 20 id FFFFFFFFFFFFFFFF (NUL-terminated)");
static_assert(([]{ const TextBuf s = fx_conf(21, 0xFFFFFFFFFFFFFFFFULL); return parse_phrase(s.c_str(), s.size()).kind; }()) == 0, "FB-B2 value: parse_phrase kind of confirmation kind 21 id FFFFFFFFFFFFFFFF");
static_assert(([]{ const TextBuf s = fx_conf(21, 0xFFFFFFFFFFFFFFFFULL); return parse_phrase(s.c_str(), s.size()).id; }()) == 0, "FB-B2 value: parse_phrase id of confirmation kind 21 id FFFFFFFFFFFFFFFF");
static_assert(([]{ const TextBuf s = fx_conf(21, 0xFFFFFFFFFFFFFFFFULL); return parse_phrase(s.c_str()).kind; }()) == 1, "FB-B2 value: parse_phrase kind of confirmation kind 21 id FFFFFFFFFFFFFFFF (NUL-terminated)");
static_assert(([]{ const TextBuf s = fx_conf(22, 0xFFFFFFFFFFFFFFFFULL); return parse_phrase(s.c_str(), s.size()).kind; }()) == 0, "FB-B2 value: parse_phrase kind of confirmation kind 22 id FFFFFFFFFFFFFFFF");
static_assert(([]{ const TextBuf s = fx_conf(22, 0xFFFFFFFFFFFFFFFFULL); return parse_phrase(s.c_str(), s.size()).id; }()) == 0, "FB-B2 value: parse_phrase id of confirmation kind 22 id FFFFFFFFFFFFFFFF");
static_assert(([]{ const TextBuf s = fx_conf(22, 0xFFFFFFFFFFFFFFFFULL); return parse_phrase(s.c_str()).kind; }()) == 1, "FB-B2 value: parse_phrase kind of confirmation kind 22 id FFFFFFFFFFFFFFFF (NUL-terminated)");
static_assert(([]{ const TextBuf s = fx_conf(23, 0xFFFFFFFFFFFFFFFFULL); return parse_phrase(s.c_str(), s.size()).kind; }()) == 0, "FB-B2 value: parse_phrase kind of confirmation kind 23 id FFFFFFFFFFFFFFFF");
static_assert(([]{ const TextBuf s = fx_conf(23, 0xFFFFFFFFFFFFFFFFULL); return parse_phrase(s.c_str(), s.size()).id; }()) == 0, "FB-B2 value: parse_phrase id of confirmation kind 23 id FFFFFFFFFFFFFFFF");
static_assert(([]{ const TextBuf s = fx_conf(23, 0xFFFFFFFFFFFFFFFFULL); return parse_phrase(s.c_str()).kind; }()) == 3, "FB-B2 value: parse_phrase kind of confirmation kind 23 id FFFFFFFFFFFFFFFF (NUL-terminated)");
static_assert(([]{ const TextBuf s = fx_conf(24, 0xFFFFFFFFFFFFFFFFULL); return parse_phrase(s.c_str(), s.size()).kind; }()) == 3, "FB-B2 value: parse_phrase kind of confirmation kind 24 id FFFFFFFFFFFFFFFF");
static_assert(([]{ const TextBuf s = fx_conf(24, 0xFFFFFFFFFFFFFFFFULL); return parse_phrase(s.c_str(), s.size()).id; }()) == 0x7FFFFFFFFFFFFFFFULL, "FB-B2 value: parse_phrase id of confirmation kind 24 id FFFFFFFFFFFFFFFF");
static_assert(([]{ const TextBuf s = fx_conf(24, 0xFFFFFFFFFFFFFFFFULL); return parse_phrase(s.c_str()).kind; }()) == 3, "FB-B2 value: parse_phrase kind of confirmation kind 24 id FFFFFFFFFFFFFFFF (NUL-terminated)");
static_assert(([]{ const TextBuf s = fx_conf(25, 0xFFFFFFFFFFFFFFFFULL); return parse_phrase(s.c_str(), s.size()).kind; }()) == 3, "FB-B2 value: parse_phrase kind of confirmation kind 25 id FFFFFFFFFFFFFFFF");
static_assert(([]{ const TextBuf s = fx_conf(25, 0xFFFFFFFFFFFFFFFFULL); return parse_phrase(s.c_str(), s.size()).id; }()) == 0xFFFFFFFEFFFFFFFFULL, "FB-B2 value: parse_phrase id of confirmation kind 25 id FFFFFFFFFFFFFFFF");
static_assert(([]{ const TextBuf s = fx_conf(25, 0xFFFFFFFFFFFFFFFFULL); return parse_phrase(s.c_str()).kind; }()) == 3, "FB-B2 value: parse_phrase kind of confirmation kind 25 id FFFFFFFFFFFFFFFF (NUL-terminated)");
static_assert(([]{ const TextBuf s = fx_conf(26, 0xFFFFFFFFFFFFFFFFULL); return parse_phrase(s.c_str(), s.size()).kind; }()) == 3, "FB-B2 value: parse_phrase kind of confirmation kind 26 id FFFFFFFFFFFFFFFF");
static_assert(([]{ const TextBuf s = fx_conf(26, 0xFFFFFFFFFFFFFFFFULL); return parse_phrase(s.c_str(), s.size()).id; }()) == 4294967295u, "FB-B2 value: parse_phrase id of confirmation kind 26 id FFFFFFFFFFFFFFFF");
static_assert(([]{ const TextBuf s = fx_conf(26, 0xFFFFFFFFFFFFFFFFULL); return parse_phrase(s.c_str()).kind; }()) == 3, "FB-B2 value: parse_phrase kind of confirmation kind 26 id FFFFFFFFFFFFFFFF (NUL-terminated)");
static_assert(([]{ const TextBuf s = fx_conf(27, 0xFFFFFFFFFFFFFFFFULL); return parse_phrase(s.c_str(), s.size()).kind; }()) == 3, "FB-B2 value: parse_phrase kind of confirmation kind 27 id FFFFFFFFFFFFFFFF");
static_assert(([]{ const TextBuf s = fx_conf(27, 0xFFFFFFFFFFFFFFFFULL); return parse_phrase(s.c_str(), s.size()).id; }()) == 0xFFFFFFFF00000000ULL, "FB-B2 value: parse_phrase id of confirmation kind 27 id FFFFFFFFFFFFFFFF");
static_assert(([]{ const TextBuf s = fx_conf(27, 0xFFFFFFFFFFFFFFFFULL); return parse_phrase(s.c_str()).kind; }()) == 3, "FB-B2 value: parse_phrase kind of confirmation kind 27 id FFFFFFFFFFFFFFFF (NUL-terminated)");
static_assert(text_is("", expected_phrase(0, 0x123456789ABCDEFULL)), "FB-B2 text: expected_phrase kind 0 id 123456789ABCDEF");
static_assert(text_is("", expected_phrase(0, 0x0ULL)), "FB-B2 text: expected_phrase kind 0 id 0");
static_assert(text_is("", expected_phrase(0, 0xFFFFFFFFFFFFFFFFULL)), "FB-B2 text: expected_phrase kind 0 id FFFFFFFFFFFFFFFF");
static_assert(text_is("", expected_phrase(0, 0xABULL)), "FB-B2 text: expected_phrase kind 0 id AB");
static_assert(text_is("SAVE 0123456789ABCDEF", expected_phrase(1, 0x123456789ABCDEFULL)), "FB-B2 text: expected_phrase kind 1 id 123456789ABCDEF");
static_assert(text_is("SAVE 0000000000000000", expected_phrase(1, 0x0ULL)), "FB-B2 text: expected_phrase kind 1 id 0");
static_assert(text_is("SAVE FFFFFFFFFFFFFFFF", expected_phrase(1, 0xFFFFFFFFFFFFFFFFULL)), "FB-B2 text: expected_phrase kind 1 id FFFFFFFFFFFFFFFF");
static_assert(text_is("SAVE 00000000000000AB", expected_phrase(1, 0xABULL)), "FB-B2 text: expected_phrase kind 1 id AB");
static_assert(text_is("SAVE 0123456789ABCDEF REPLACE CORRUPT", expected_phrase(2, 0x123456789ABCDEFULL)), "FB-B2 text: expected_phrase kind 2 id 123456789ABCDEF");
static_assert(text_is("SAVE 0000000000000000 REPLACE CORRUPT", expected_phrase(2, 0x0ULL)), "FB-B2 text: expected_phrase kind 2 id 0");
static_assert(text_is("SAVE FFFFFFFFFFFFFFFF REPLACE CORRUPT", expected_phrase(2, 0xFFFFFFFFFFFFFFFFULL)), "FB-B2 text: expected_phrase kind 2 id FFFFFFFFFFFFFFFF");
static_assert(text_is("SAVE 00000000000000AB REPLACE CORRUPT", expected_phrase(2, 0xABULL)), "FB-B2 text: expected_phrase kind 2 id AB");
static_assert(text_is("INVALIDATE 0123456789ABCDEF", expected_phrase(3, 0x123456789ABCDEFULL)), "FB-B2 text: expected_phrase kind 3 id 123456789ABCDEF");
static_assert(text_is("INVALIDATE 0000000000000000", expected_phrase(3, 0x0ULL)), "FB-B2 text: expected_phrase kind 3 id 0");
static_assert(text_is("INVALIDATE FFFFFFFFFFFFFFFF", expected_phrase(3, 0xFFFFFFFFFFFFFFFFULL)), "FB-B2 text: expected_phrase kind 3 id FFFFFFFFFFFFFFFF");
static_assert(text_is("INVALIDATE 00000000000000AB", expected_phrase(3, 0xABULL)), "FB-B2 text: expected_phrase kind 3 id AB");
static_assert(text_is("", expected_phrase(4, 0x123456789ABCDEFULL)), "FB-B2 text: expected_phrase kind 4 id 123456789ABCDEF");
static_assert(text_is("", expected_phrase(4, 0x0ULL)), "FB-B2 text: expected_phrase kind 4 id 0");
static_assert(text_is("", expected_phrase(4, 0xFFFFFFFFFFFFFFFFULL)), "FB-B2 text: expected_phrase kind 4 id FFFFFFFFFFFFFFFF");
static_assert(text_is("", expected_phrase(4, 0xABULL)), "FB-B2 text: expected_phrase kind 4 id AB");
static_assert((phrase_equals("", 0, TextBuf{})) == 0, "FB-B2 value: phrase_equals: an empty expected phrase never matches");
static_assert((phrase_equals(nullptr, 21, expected_phrase(1, 1ULL))) == 0, "FB-B2 value: phrase_equals: a null confirmation");
static_assert((parse_phrase(nullptr, 21).kind) == 0, "FB-B2 value: parse_phrase: a null confirmation");
static_assert(text_is("REFUSED - unsupported action 'CAPTURE'", unsupported_action_text("CAPTURE")), "FB-B2 text: unsupported_action_text 'CAPTURE' (NUL-terminated)");
static_assert(text_is("REFUSED - unsupported action 'CAPTURE'", unsupported_action_text("CAPTURE", 7)), "FB-B2 text: unsupported_action_text 'CAPTURE' (explicit length)");
static_assert(text_is("REFUSED - unsupported action ''", unsupported_action_text("")), "FB-B2 text: unsupported_action_text '' (NUL-terminated)");
static_assert(text_is("REFUSED - unsupported action ''", unsupported_action_text("", 0)), "FB-B2 text: unsupported_action_text '' (explicit length)");
static_assert(text_is("REFUSED - unsupported action 'a\?b'", unsupported_action_text("a b")), "FB-B2 text: unsupported_action_text 'a b' (NUL-terminated)");
static_assert(text_is("REFUSED - unsupported action 'a\?b'", unsupported_action_text("a b", 3)), "FB-B2 text: unsupported_action_text 'a b' (explicit length)");
static_assert(text_is("REFUSED - unsupported action 'SAVE\?'", unsupported_action_text("SAVE\n")), "FB-B2 text: unsupported_action_text 'SAVE~0A' (NUL-terminated)");
static_assert(text_is("REFUSED - unsupported action 'SAVE\?'", unsupported_action_text("SAVE\n", 5)), "FB-B2 text: unsupported_action_text 'SAVE~0A' (explicit length)");
static_assert(text_is("REFUSED - unsupported action 'xxxxxxxxxxxxxxxxxxxxxxx'", unsupported_action_text("xxxxxxxxxxxxxxxxxxxxxxx")), "FB-B2 text: unsupported_action_text 'xxxxxxxxxxxxxxxxxxxxxxx' (NUL-terminated)");
static_assert(text_is("REFUSED - unsupported action 'xxxxxxxxxxxxxxxxxxxxxxx'", unsupported_action_text("xxxxxxxxxxxxxxxxxxxxxxx", 23)), "FB-B2 text: unsupported_action_text 'xxxxxxxxxxxxxxxxxxxxxxx' (explicit length)");
static_assert(text_is("REFUSED - unsupported action 'xxxxxxxxxxxxxxxxxxxxxxxx'", unsupported_action_text("xxxxxxxxxxxxxxxxxxxxxxxx")), "FB-B2 text: unsupported_action_text 'xxxxxxxxxxxxxxxxxxxxxxxx' (NUL-terminated)");
static_assert(text_is("REFUSED - unsupported action 'xxxxxxxxxxxxxxxxxxxxxxxx'", unsupported_action_text("xxxxxxxxxxxxxxxxxxxxxxxx", 24)), "FB-B2 text: unsupported_action_text 'xxxxxxxxxxxxxxxxxxxxxxxx' (explicit length)");
static_assert(text_is("REFUSED - unsupported action 'xxxxxxxxxxxxxxxxxxxxxxxx'", unsupported_action_text("xxxxxxxxxxxxxxxxxxxxxxxxx")), "FB-B2 text: unsupported_action_text 'xxxxxxxxxxxxxxxxxxxxxxxxx' (NUL-terminated)");
static_assert(text_is("REFUSED - unsupported action 'xxxxxxxxxxxxxxxxxxxxxxxx'", unsupported_action_text("xxxxxxxxxxxxxxxxxxxxxxxxx", 25)), "FB-B2 text: unsupported_action_text 'xxxxxxxxxxxxxxxxxxxxxxxxx' (explicit length)");
static_assert(text_is("REFUSED - unsupported action 'yyyyyyyyyyyyyyyyyyyyyyyy'", unsupported_action_text("yyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyy")), "FB-B2 text: unsupported_action_text 'yyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyy' (NUL-terminated)");
static_assert(text_is("REFUSED - unsupported action 'yyyyyyyyyyyyyyyyyyyyyyyy'", unsupported_action_text("yyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyy", 100)), "FB-B2 text: unsupported_action_text 'yyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyy' (explicit length)");
static_assert(text_is("REFUSED - unsupported action 'caf\?\?'", unsupported_action_text("caf\303\251")), "FB-B2 text: unsupported_action_text 'caf~C3~A9' (NUL-terminated)");
static_assert(text_is("REFUSED - unsupported action 'caf\?\?'", unsupported_action_text("caf\303\251", 5)), "FB-B2 text: unsupported_action_text 'caf~C3~A9' (explicit length)");
static_assert(text_is("REFUSED - unsupported action 'Rm\?\?rf\?\?'", unsupported_action_text("Rm -rf /")), "FB-B2 text: unsupported_action_text 'Rm -rf /' (NUL-terminated)");
static_assert(text_is("REFUSED - unsupported action 'Rm\?\?rf\?\?'", unsupported_action_text("Rm -rf /", 8)), "FB-B2 text: unsupported_action_text 'Rm -rf /' (explicit length)");
static_assert(text_is("REFUSED - unsupported action 'UPPER_lower_09'", unsupported_action_text("UPPER_lower_09")), "FB-B2 text: unsupported_action_text 'UPPER_lower_09' (NUL-terminated)");
static_assert(text_is("REFUSED - unsupported action 'UPPER_lower_09'", unsupported_action_text("UPPER_lower_09", 14)), "FB-B2 text: unsupported_action_text 'UPPER_lower_09' (explicit length)");
static_assert(text_is("REFUSED - unsupported action 'q\?uote'", unsupported_action_text("q'uote")), "FB-B2 text: unsupported_action_text 'q'uote' (NUL-terminated)");
static_assert(text_is("REFUSED - unsupported action 'q\?uote'", unsupported_action_text("q'uote", 6)), "FB-B2 text: unsupported_action_text 'q'uote' (explicit length)");
static_assert(text_is("REFUSED - unsupported action '\?dq\?'", unsupported_action_text("\"dq\"")), "FB-B2 text: unsupported_action_text '~22dq~22' (NUL-terminated)");
static_assert(text_is("REFUSED - unsupported action '\?dq\?'", unsupported_action_text("\"dq\"", 4)), "FB-B2 text: unsupported_action_text '~22dq~22' (explicit length)");
static_assert(text_is("REFUSED - unsupported action 'tab\?x'", unsupported_action_text("tab\011x")), "FB-B2 text: unsupported_action_text 'tab~09x' (NUL-terminated)");
static_assert(text_is("REFUSED - unsupported action 'tab\?x'", unsupported_action_text("tab\011x", 5)), "FB-B2 text: unsupported_action_text 'tab~09x' (explicit length)");
static_assert(text_is("REFUSED - unsupported action 'ACCEPT_LIVE'", unsupported_action_text("ACCEPT_LIVE")), "FB-B2 text: unsupported_action_text 'ACCEPT_LIVE' (NUL-terminated)");
static_assert(text_is("REFUSED - unsupported action 'ACCEPT_LIVE'", unsupported_action_text("ACCEPT_LIVE", 11)), "FB-B2 text: unsupported_action_text 'ACCEPT_LIVE' (explicit length)");
static_assert(text_is("REFUSED - unsupported action 'RETRY_APPLY'", unsupported_action_text("RETRY_APPLY")), "FB-B2 text: unsupported_action_text 'RETRY_APPLY' (NUL-terminated)");
static_assert(text_is("REFUSED - unsupported action 'RETRY_APPLY'", unsupported_action_text("RETRY_APPLY", 11)), "FB-B2 text: unsupported_action_text 'RETRY_APPLY' (explicit length)");
static_assert(text_is("REFUSED - unsupported action 'PROVISION'", unsupported_action_text("PROVISION")), "FB-B2 text: unsupported_action_text 'PROVISION' (NUL-terminated)");
static_assert(text_is("REFUSED - unsupported action 'PROVISION'", unsupported_action_text("PROVISION", 9)), "FB-B2 text: unsupported_action_text 'PROVISION' (explicit length)");
static_assert(text_is("REFUSED - unsupported action 'APPLY'", unsupported_action_text("APPLY")), "FB-B2 text: unsupported_action_text 'APPLY' (NUL-terminated)");
static_assert(text_is("REFUSED - unsupported action 'APPLY'", unsupported_action_text("APPLY", 5)), "FB-B2 text: unsupported_action_text 'APPLY' (explicit length)");
static_assert(text_is("REFUSED - unsupported action ''", unsupported_action_text(nullptr)), "FB-B2 text: unsupported_action_text: a null action");
static_assert(text_is("REFUSED - unsupported action 'AB\?CD'", unsupported_action_text("AB\000CD", 5)), "FB-B2 text: unsupported_action_text: an embedded NUL counts with an explicit length");
static_assert(text_is("REFUSED - unsupported action 'AB'", unsupported_action_text("AB\000CD")), "FB-B2 text: unsupported_action_text: an embedded NUL ends a NUL-terminated token");
static_assert(text_is("REFUSED - unsupported action 'RETRY_APPLY'", action_refusal_text(0, "RETRY_APPLY", 11)), "FB-B2 text: action_refusal_text token 0");
static_assert(text_is("REFUSED - unsupported action 'RETRY_APPLY'", action_refusal_text(1, "RETRY_APPLY", 11)), "FB-B2 text: action_refusal_text token 1");
static_assert(text_is("REFUSED - unsupported action 'RETRY_APPLY'", action_refusal_text(2, "RETRY_APPLY", 11)), "FB-B2 text: action_refusal_text token 2");
static_assert(text_is("RESTORE REFUSED - not implemented in this firmware", action_refusal_text(3, "RETRY_APPLY", 11)), "FB-B2 text: action_refusal_text token 3");
static_assert(text_is("ACKNOWLEDGE REFUSED - not implemented in this firmware", action_refusal_text(4, "RETRY_APPLY", 11)), "FB-B2 text: action_refusal_text token 4");
static_assert(text_is("REFUSED - unsupported action 'RETRY_APPLY'", action_refusal_text(5, "RETRY_APPLY", 11)), "FB-B2 text: action_refusal_text token 5");
static_assert(text_is("RESTORE REFUSED - not implemented in this firmware", action_refusal_text(ACT_RESTORE, "RESTORE", 7)), "FB-B2 text: action_refusal_text: RESTORE");
static_assert(text_is("ACKNOWLEDGE REFUSED - not implemented in this firmware", action_refusal_text(ACT_ACKNOWLEDGE, "ACKNOWLEDGE", 11)), "FB-B2 text: action_refusal_text: ACKNOWLEDGE");
static_assert(text_is("REFUSED - unsupported action '\?\?\?\?ed'", unsupported_action_text("f" "ailed")), "FB-B2 text: unsupported_action_text '~66ailed' (NUL-terminated)");
static_assert(text_is("REFUSED - unsupported action '\?\?\?\?ed'", unsupported_action_text("f" "ailed", 6)), "FB-B2 text: unsupported_action_text '~66ailed' (explicit length)");
static_assert(text_is("REFUSED - unsupported action '\?\?\?\?ed'", action_refusal_text(0, "f" "ailed", 6)), "FB-B2 text: action_refusal_text unsupported echo of '~66ailed'");
static_assert(text_is("REFUSED - unsupported action '\?\?\?\?ED'", unsupported_action_text("F" "AILED")), "FB-B2 text: unsupported_action_text '~46AILED' (NUL-terminated)");
static_assert(text_is("REFUSED - unsupported action '\?\?\?\?ED'", unsupported_action_text("F" "AILED", 6)), "FB-B2 text: unsupported_action_text '~46AILED' (explicit length)");
static_assert(text_is("REFUSED - unsupported action '\?\?\?\?ED'", action_refusal_text(0, "F" "AILED", 6)), "FB-B2 text: action_refusal_text unsupported echo of '~46AILED'");
static_assert(text_is("REFUSED - unsupported action '\?\?\?\?ed'", unsupported_action_text("F" "ailed")), "FB-B2 text: unsupported_action_text '~46ailed' (NUL-terminated)");
static_assert(text_is("REFUSED - unsupported action '\?\?\?\?ed'", unsupported_action_text("F" "ailed", 6)), "FB-B2 text: unsupported_action_text '~46ailed' (explicit length)");
static_assert(text_is("REFUSED - unsupported action '\?\?\?\?ed'", action_refusal_text(0, "F" "ailed", 6)), "FB-B2 text: action_refusal_text unsupported echo of '~46ailed'");
static_assert(text_is("REFUSED - unsupported action '\?\?\?\?eD'", unsupported_action_text("f" "AiLeD")), "FB-B2 text: unsupported_action_text '~66AiLeD' (NUL-terminated)");
static_assert(text_is("REFUSED - unsupported action '\?\?\?\?eD'", unsupported_action_text("f" "AiLeD", 6)), "FB-B2 text: unsupported_action_text '~66AiLeD' (explicit length)");
static_assert(text_is("REFUSED - unsupported action '\?\?\?\?eD'", action_refusal_text(0, "f" "AiLeD", 6)), "FB-B2 text: action_refusal_text unsupported echo of '~66AiLeD'");
static_assert(text_is("REFUSED - unsupported action '\?\?\?\?\?red'", unsupported_action_text("d" "eferred")), "FB-B2 text: unsupported_action_text '~64eferred' (NUL-terminated)");
static_assert(text_is("REFUSED - unsupported action '\?\?\?\?\?red'", unsupported_action_text("d" "eferred", 8)), "FB-B2 text: unsupported_action_text '~64eferred' (explicit length)");
static_assert(text_is("REFUSED - unsupported action '\?\?\?\?\?red'", action_refusal_text(0, "d" "eferred", 8)), "FB-B2 text: action_refusal_text unsupported echo of '~64eferred'");
static_assert(text_is("REFUSED - unsupported action '\?\?\?\?\?RED'", unsupported_action_text("D" "EFERRED")), "FB-B2 text: unsupported_action_text '~44EFERRED' (NUL-terminated)");
static_assert(text_is("REFUSED - unsupported action '\?\?\?\?\?RED'", unsupported_action_text("D" "EFERRED", 8)), "FB-B2 text: unsupported_action_text '~44EFERRED' (explicit length)");
static_assert(text_is("REFUSED - unsupported action '\?\?\?\?\?RED'", action_refusal_text(0, "D" "EFERRED", 8)), "FB-B2 text: action_refusal_text unsupported echo of '~44EFERRED'");
static_assert(text_is("REFUSED - unsupported action '\?\?\?\?\?red'", unsupported_action_text("D" "eferred")), "FB-B2 text: unsupported_action_text '~44eferred' (NUL-terminated)");
static_assert(text_is("REFUSED - unsupported action '\?\?\?\?\?red'", unsupported_action_text("D" "eferred", 8)), "FB-B2 text: unsupported_action_text '~44eferred' (explicit length)");
static_assert(text_is("REFUSED - unsupported action '\?\?\?\?\?red'", action_refusal_text(0, "D" "eferred", 8)), "FB-B2 text: action_refusal_text unsupported echo of '~44eferred'");
static_assert(text_is("REFUSED - unsupported action '\?\?\?\?\?ReD'", unsupported_action_text("d" "EfErReD")), "FB-B2 text: unsupported_action_text '~64EfErReD' (NUL-terminated)");
static_assert(text_is("REFUSED - unsupported action '\?\?\?\?\?ReD'", unsupported_action_text("d" "EfErReD", 8)), "FB-B2 text: unsupported_action_text '~64EfErReD' (explicit length)");
static_assert(text_is("REFUSED - unsupported action '\?\?\?\?\?ReD'", action_refusal_text(0, "d" "EfErReD", 8)), "FB-B2 text: action_refusal_text unsupported echo of '~64EfErReD'");
static_assert(text_is("REFUSED - unsupported action 'x\?\?\?\?\?rEdx'", unsupported_action_text("xD" "eFeRrEdx")), "FB-B2 text: unsupported_action_text 'x~44eFeRrEdx' (NUL-terminated)");
static_assert(text_is("REFUSED - unsupported action 'x\?\?\?\?\?rEdx'", unsupported_action_text("xD" "eFeRrEdx", 10)), "FB-B2 text: unsupported_action_text 'x~44eFeRrEdx' (explicit length)");
static_assert(text_is("REFUSED - unsupported action 'x\?\?\?\?\?rEdx'", action_refusal_text(0, "xD" "eFeRrEdx", 10)), "FB-B2 text: action_refusal_text unsupported echo of 'x~44eFeRrEdx'");
static_assert(text_is("REFUSED - unsupported action '\?\?\?\?'", unsupported_action_text("f" "ail")), "FB-B2 text: unsupported_action_text '~66ail' (NUL-terminated)");
static_assert(text_is("REFUSED - unsupported action '\?\?\?\?'", unsupported_action_text("f" "ail", 4)), "FB-B2 text: unsupported_action_text '~66ail' (explicit length)");
static_assert(text_is("REFUSED - unsupported action '\?\?\?\?'", action_refusal_text(0, "f" "ail", 4)), "FB-B2 text: action_refusal_text unsupported echo of '~66ail'");
static_assert(text_is("REFUSED - unsupported action '\?\?\?\?'", unsupported_action_text("F" "AIL")), "FB-B2 text: unsupported_action_text '~46AIL' (NUL-terminated)");
static_assert(text_is("REFUSED - unsupported action '\?\?\?\?'", unsupported_action_text("F" "AIL", 4)), "FB-B2 text: unsupported_action_text '~46AIL' (explicit length)");
static_assert(text_is("REFUSED - unsupported action '\?\?\?\?'", action_refusal_text(0, "F" "AIL", 4)), "FB-B2 text: action_refusal_text unsupported echo of '~46AIL'");
static_assert(text_is("REFUSED - unsupported action '\?\?\?\?\?'", unsupported_action_text("d" "efer")), "FB-B2 text: unsupported_action_text '~64efer' (NUL-terminated)");
static_assert(text_is("REFUSED - unsupported action '\?\?\?\?\?'", unsupported_action_text("d" "efer", 5)), "FB-B2 text: unsupported_action_text '~64efer' (explicit length)");
static_assert(text_is("REFUSED - unsupported action '\?\?\?\?\?'", action_refusal_text(0, "d" "efer", 5)), "FB-B2 text: action_refusal_text unsupported echo of '~64efer'");
static_assert(text_is("REFUSED - unsupported action '\?\?\?\?\?'", unsupported_action_text("D" "EFER")), "FB-B2 text: unsupported_action_text '~44EFER' (NUL-terminated)");
static_assert(text_is("REFUSED - unsupported action '\?\?\?\?\?'", unsupported_action_text("D" "EFER", 5)), "FB-B2 text: unsupported_action_text '~44EFER' (explicit length)");
static_assert(text_is("REFUSED - unsupported action '\?\?\?\?\?'", action_refusal_text(0, "D" "EFER", 5)), "FB-B2 text: action_refusal_text unsupported echo of '~44EFER'");
static_assert(text_is("REFUSED - unsupported action '\?\?\?\?ure'", unsupported_action_text("f" "ailure")), "FB-B2 text: unsupported_action_text '~66ailure' (NUL-terminated)");
static_assert(text_is("REFUSED - unsupported action '\?\?\?\?ure'", unsupported_action_text("f" "ailure", 7)), "FB-B2 text: unsupported_action_text '~66ailure' (explicit length)");
static_assert(text_is("REFUSED - unsupported action '\?\?\?\?ure'", action_refusal_text(0, "f" "ailure", 7)), "FB-B2 text: action_refusal_text unsupported echo of '~66ailure'");
static_assert(text_is("REFUSED - unsupported action '\?\?\?\?\?\?\?\?'", unsupported_action_text("f" "ailf" "ail")), "FB-B2 text: unsupported_action_text '~66ail~66ail' (NUL-terminated)");
static_assert(text_is("REFUSED - unsupported action '\?\?\?\?\?\?\?\?'", unsupported_action_text("f" "ailf" "ail", 8)), "FB-B2 text: unsupported_action_text '~66ail~66ail' (explicit length)");
static_assert(text_is("REFUSED - unsupported action '\?\?\?\?\?\?\?\?'", action_refusal_text(0, "f" "ailf" "ail", 8)), "FB-B2 text: action_refusal_text unsupported echo of '~66ail~66ail'");
static_assert(text_is("REFUSED - unsupported action '\?\?\?\?\?\?\?\?\?'", unsupported_action_text("f" "aild" "efer")), "FB-B2 text: unsupported_action_text '~66ail~64efer' (NUL-terminated)");
static_assert(text_is("REFUSED - unsupported action '\?\?\?\?\?\?\?\?\?'", unsupported_action_text("f" "aild" "efer", 9)), "FB-B2 text: unsupported_action_text '~66ail~64efer' (explicit length)");
static_assert(text_is("REFUSED - unsupported action '\?\?\?\?\?\?\?\?\?'", action_refusal_text(0, "f" "aild" "efer", 9)), "FB-B2 text: action_refusal_text unsupported echo of '~66ail~64efer'");
static_assert(text_is("REFUSED - unsupported action '\?\?\?\?\?\?\?\?\?'", unsupported_action_text("d" "eferf" "ail")), "FB-B2 text: unsupported_action_text '~64efer~66ail' (NUL-terminated)");
static_assert(text_is("REFUSED - unsupported action '\?\?\?\?\?\?\?\?\?'", unsupported_action_text("d" "eferf" "ail", 9)), "FB-B2 text: unsupported_action_text '~64efer~66ail' (explicit length)");
static_assert(text_is("REFUSED - unsupported action '\?\?\?\?\?\?\?\?\?'", action_refusal_text(0, "d" "eferf" "ail", 9)), "FB-B2 text: action_refusal_text unsupported echo of '~64efer~66ail'");
static_assert(text_is("REFUSED - unsupported action '\?\?\?\?ED_\?\?\?\?\?RED'", unsupported_action_text("F" "AILED_D" "EFERRED")), "FB-B2 text: unsupported_action_text '~46AILED_~44EFERRED' (NUL-terminated)");
static_assert(text_is("REFUSED - unsupported action '\?\?\?\?ED_\?\?\?\?\?RED'", unsupported_action_text("F" "AILED_D" "EFERRED", 15)), "FB-B2 text: unsupported_action_text '~46AILED_~44EFERRED' (explicit length)");
static_assert(text_is("REFUSED - unsupported action '\?\?\?\?ED_\?\?\?\?\?RED'", action_refusal_text(0, "F" "AILED_D" "EFERRED", 15)), "FB-B2 text: action_refusal_text unsupported echo of '~46AILED_~44EFERRED'");
static_assert(text_is("REFUSED - unsupported action 'x\?\?\?\?edx'", unsupported_action_text("xf" "ailedx")), "FB-B2 text: unsupported_action_text 'x~66ailedx' (NUL-terminated)");
static_assert(text_is("REFUSED - unsupported action 'x\?\?\?\?edx'", unsupported_action_text("xf" "ailedx", 8)), "FB-B2 text: unsupported_action_text 'x~66ailedx' (explicit length)");
static_assert(text_is("REFUSED - unsupported action 'x\?\?\?\?edx'", action_refusal_text(0, "xf" "ailedx", 8)), "FB-B2 text: action_refusal_text unsupported echo of 'x~66ailedx'");
static_assert(text_is("REFUSED - unsupported action 'a\?\?\?\?\?ed\?b'", unsupported_action_text("a f" "ailed b")), "FB-B2 text: unsupported_action_text 'a ~66ailed b' (NUL-terminated)");
static_assert(text_is("REFUSED - unsupported action 'a\?\?\?\?\?ed\?b'", unsupported_action_text("a f" "ailed b", 10)), "FB-B2 text: unsupported_action_text 'a ~66ailed b' (explicit length)");
static_assert(text_is("REFUSED - unsupported action 'a\?\?\?\?\?ed\?b'", action_refusal_text(0, "a f" "ailed b", 10)), "FB-B2 text: action_refusal_text unsupported echo of 'a ~66ailed b'");
static_assert(text_is("REFUSED - unsupported action 'fa\?il'", unsupported_action_text("fa il")), "FB-B2 text: unsupported_action_text 'fa il' (NUL-terminated)");
static_assert(text_is("REFUSED - unsupported action 'fa\?il'", unsupported_action_text("fa il", 5)), "FB-B2 text: unsupported_action_text 'fa il' (explicit length)");
static_assert(text_is("REFUSED - unsupported action 'fa\?il'", action_refusal_text(0, "fa il", 5)), "FB-B2 text: action_refusal_text unsupported echo of 'fa il'");
static_assert(text_is("REFUSED - unsupported action 'fai'", unsupported_action_text("fai")), "FB-B2 text: unsupported_action_text 'fai' (NUL-terminated)");
static_assert(text_is("REFUSED - unsupported action 'fai'", unsupported_action_text("fai", 3)), "FB-B2 text: unsupported_action_text 'fai' (explicit length)");
static_assert(text_is("REFUSED - unsupported action 'fai'", action_refusal_text(0, "fai", 3)), "FB-B2 text: action_refusal_text unsupported echo of 'fai'");
static_assert(text_is("REFUSED - unsupported action 'def'", unsupported_action_text("def")), "FB-B2 text: unsupported_action_text 'def' (NUL-terminated)");
static_assert(text_is("REFUSED - unsupported action 'def'", unsupported_action_text("def", 3)), "FB-B2 text: unsupported_action_text 'def' (explicit length)");
static_assert(text_is("REFUSED - unsupported action 'def'", action_refusal_text(0, "def", 3)), "FB-B2 text: action_refusal_text unsupported echo of 'def'");
static_assert(text_is("REFUSED - unsupported action 'efer'", unsupported_action_text("efer")), "FB-B2 text: unsupported_action_text 'efer' (NUL-terminated)");
static_assert(text_is("REFUSED - unsupported action 'efer'", unsupported_action_text("efer", 4)), "FB-B2 text: unsupported_action_text 'efer' (explicit length)");
static_assert(text_is("REFUSED - unsupported action 'efer'", action_refusal_text(0, "efer", 4)), "FB-B2 text: action_refusal_text unsupported echo of 'efer'");
static_assert(text_is("REFUSED - unsupported action 'ail'", unsupported_action_text("ail")), "FB-B2 text: unsupported_action_text 'ail' (NUL-terminated)");
static_assert(text_is("REFUSED - unsupported action 'ail'", unsupported_action_text("ail", 3)), "FB-B2 text: unsupported_action_text 'ail' (explicit length)");
static_assert(text_is("REFUSED - unsupported action 'ail'", action_refusal_text(0, "ail", 3)), "FB-B2 text: action_refusal_text unsupported echo of 'ail'");
static_assert(text_is("REFUSED - unsupported action '\?\?\?\?_'", unsupported_action_text("f" "ail_")), "FB-B2 text: unsupported_action_text '~66ail_' (NUL-terminated)");
static_assert(text_is("REFUSED - unsupported action '\?\?\?\?_'", unsupported_action_text("f" "ail_", 5)), "FB-B2 text: unsupported_action_text '~66ail_' (explicit length)");
static_assert(text_is("REFUSED - unsupported action '\?\?\?\?_'", action_refusal_text(0, "f" "ail_", 5)), "FB-B2 text: action_refusal_text unsupported echo of '~66ail_'");
static_assert(text_is("REFUSED - unsupported action '_\?\?\?\?'", unsupported_action_text("_f" "ail")), "FB-B2 text: unsupported_action_text '_~66ail' (NUL-terminated)");
static_assert(text_is("REFUSED - unsupported action '_\?\?\?\?'", unsupported_action_text("_f" "ail", 5)), "FB-B2 text: unsupported_action_text '_~66ail' (explicit length)");
static_assert(text_is("REFUSED - unsupported action '_\?\?\?\?'", action_refusal_text(0, "_f" "ail", 5)), "FB-B2 text: action_refusal_text unsupported echo of '_~66ail'");
static_assert(text_is("REFUSED - unsupported action 'fai\?\?\?\?'", unsupported_action_text("faif" "ail")), "FB-B2 text: unsupported_action_text 'fai~66ail' (NUL-terminated)");
static_assert(text_is("REFUSED - unsupported action 'fai\?\?\?\?'", unsupported_action_text("faif" "ail", 7)), "FB-B2 text: unsupported_action_text 'fai~66ail' (explicit length)");
static_assert(text_is("REFUSED - unsupported action 'fai\?\?\?\?'", action_refusal_text(0, "faif" "ail", 7)), "FB-B2 text: action_refusal_text unsupported echo of 'fai~66ail'");
static_assert(text_is("REFUSED - unsupported action 'def\?\?\?\?\?'", unsupported_action_text("defd" "efer")), "FB-B2 text: unsupported_action_text 'def~64efer' (NUL-terminated)");
static_assert(text_is("REFUSED - unsupported action 'def\?\?\?\?\?'", unsupported_action_text("defd" "efer", 8)), "FB-B2 text: unsupported_action_text 'def~64efer' (explicit length)");
static_assert(text_is("REFUSED - unsupported action 'def\?\?\?\?\?'", action_refusal_text(0, "defd" "efer", 8)), "FB-B2 text: action_refusal_text unsupported echo of 'def~64efer'");
static_assert(text_is("REFUSED - unsupported action '\?\?\?\?\?\?'", unsupported_action_text("f" "ail\303\251")), "FB-B2 text: unsupported_action_text '~66ail~C3~A9' (NUL-terminated)");
static_assert(text_is("REFUSED - unsupported action '\?\?\?\?\?\?'", unsupported_action_text("f" "ail\303\251", 6)), "FB-B2 text: unsupported_action_text '~66ail~C3~A9' (explicit length)");
static_assert(text_is("REFUSED - unsupported action '\?\?\?\?\?\?'", action_refusal_text(0, "f" "ail\303\251", 6)), "FB-B2 text: action_refusal_text unsupported echo of '~66ail~C3~A9'");
static_assert(text_is("REFUSED - unsupported action '\?\?\?\?'", unsupported_action_text("f" "ail\000f" "ailed")), "FB-B2 text: unsupported_action_text '~66ail~00~66ailed' (NUL-terminated)");
static_assert(text_is("REFUSED - unsupported action '\?\?\?\?\?\?\?\?\?ed'", unsupported_action_text("f" "ail\000f" "ailed", 11)), "FB-B2 text: unsupported_action_text '~66ail~00~66ailed' (explicit length)");
static_assert(text_is("REFUSED - unsupported action '\?\?\?\?\?\?\?\?\?ed'", action_refusal_text(0, "f" "ail\000f" "ailed", 11)), "FB-B2 text: action_refusal_text unsupported echo of '~66ail~00~66ailed'");
static_assert(text_is("REFUSED - unsupported action 'fa'", unsupported_action_text("fa\000il")), "FB-B2 text: unsupported_action_text 'fa~00il' (NUL-terminated)");
static_assert(text_is("REFUSED - unsupported action 'fa\?il'", unsupported_action_text("fa\000il", 5)), "FB-B2 text: unsupported_action_text 'fa~00il' (explicit length)");
static_assert(text_is("REFUSED - unsupported action 'fa\?il'", action_refusal_text(0, "fa\000il", 5)), "FB-B2 text: action_refusal_text unsupported echo of 'fa~00il'");
static_assert(text_is("REFUSED - unsupported action '\?\?\?\?\?'", unsupported_action_text("d" "efer\000d" "eferred")), "FB-B2 text: unsupported_action_text '~64efer~00~64eferred' (NUL-terminated)");
static_assert(text_is("REFUSED - unsupported action '\?\?\?\?\?\?\?\?\?\?\?red'", unsupported_action_text("d" "efer\000d" "eferred", 14)), "FB-B2 text: unsupported_action_text '~64efer~00~64eferred' (explicit length)");
static_assert(text_is("REFUSED - unsupported action '\?\?\?\?\?\?\?\?\?\?\?red'", action_refusal_text(0, "d" "efer\000d" "eferred", 14)), "FB-B2 text: action_refusal_text unsupported echo of '~64efer~00~64eferred'");
static_assert(text_is("REFUSED - unsupported action 'xxxxxxxxxxxxxxxxxx\?\?\?\?ed'", unsupported_action_text("xxxxxxxxxxxxxxxxxxf" "ailed")), "FB-B2 text: unsupported_action_text 'xxxxxxxxxxxxxxxxxx~66ailed' (NUL-terminated)");
static_assert(text_is("REFUSED - unsupported action 'xxxxxxxxxxxxxxxxxx\?\?\?\?ed'", unsupported_action_text("xxxxxxxxxxxxxxxxxxf" "ailed", 24)), "FB-B2 text: unsupported_action_text 'xxxxxxxxxxxxxxxxxx~66ailed' (explicit length)");
static_assert(text_is("REFUSED - unsupported action 'xxxxxxxxxxxxxxxxxx\?\?\?\?ed'", action_refusal_text(0, "xxxxxxxxxxxxxxxxxxf" "ailed", 24)), "FB-B2 text: action_refusal_text unsupported echo of 'xxxxxxxxxxxxxxxxxx~66ailed'");
static_assert(text_is("REFUSED - unsupported action 'xxxxxxxxxxxxxxxxxx\?\?\?\?ED'", unsupported_action_text("xxxxxxxxxxxxxxxxxxF" "AILED")), "FB-B2 text: unsupported_action_text 'xxxxxxxxxxxxxxxxxx~46AILED' (NUL-terminated)");
static_assert(text_is("REFUSED - unsupported action 'xxxxxxxxxxxxxxxxxx\?\?\?\?ED'", unsupported_action_text("xxxxxxxxxxxxxxxxxxF" "AILED", 24)), "FB-B2 text: unsupported_action_text 'xxxxxxxxxxxxxxxxxx~46AILED' (explicit length)");
static_assert(text_is("REFUSED - unsupported action 'xxxxxxxxxxxxxxxxxx\?\?\?\?ED'", action_refusal_text(0, "xxxxxxxxxxxxxxxxxxF" "AILED", 24)), "FB-B2 text: action_refusal_text unsupported echo of 'xxxxxxxxxxxxxxxxxx~46AILED'");
static_assert(text_is("REFUSED - unsupported action 'xxxxxxxxxxxxxxxxxx\?\?\?\?\?r'", unsupported_action_text("xxxxxxxxxxxxxxxxxxd" "eferred")), "FB-B2 text: unsupported_action_text 'xxxxxxxxxxxxxxxxxx~64eferred' (NUL-terminated)");
static_assert(text_is("REFUSED - unsupported action 'xxxxxxxxxxxxxxxxxx\?\?\?\?\?r'", unsupported_action_text("xxxxxxxxxxxxxxxxxxd" "eferred", 26)), "FB-B2 text: unsupported_action_text 'xxxxxxxxxxxxxxxxxx~64eferred' (explicit length)");
static_assert(text_is("REFUSED - unsupported action 'xxxxxxxxxxxxxxxxxx\?\?\?\?\?r'", action_refusal_text(0, "xxxxxxxxxxxxxxxxxxd" "eferred", 26)), "FB-B2 text: action_refusal_text unsupported echo of 'xxxxxxxxxxxxxxxxxx~64eferred'");
static_assert(text_is("REFUSED - unsupported action 'xxxxxxxxxxxxxxxxxx\?\?\?\?\?e'", unsupported_action_text("xxxxxxxxxxxxxxxxxxD" "eFeReD")), "FB-B2 text: unsupported_action_text 'xxxxxxxxxxxxxxxxxx~44eFeReD' (NUL-terminated)");
static_assert(text_is("REFUSED - unsupported action 'xxxxxxxxxxxxxxxxxx\?\?\?\?\?e'", unsupported_action_text("xxxxxxxxxxxxxxxxxxD" "eFeReD", 25)), "FB-B2 text: unsupported_action_text 'xxxxxxxxxxxxxxxxxx~44eFeReD' (explicit length)");
static_assert(text_is("REFUSED - unsupported action 'xxxxxxxxxxxxxxxxxx\?\?\?\?\?e'", action_refusal_text(0, "xxxxxxxxxxxxxxxxxxD" "eFeReD", 25)), "FB-B2 text: action_refusal_text unsupported echo of 'xxxxxxxxxxxxxxxxxx~44eFeReD'");
static_assert(text_is("REFUSED - unsupported action 'xxxxxxxxxxxxxxxxxxx\?\?\?\?e'", unsupported_action_text("xxxxxxxxxxxxxxxxxxxf" "ailed")), "FB-B2 text: unsupported_action_text 'xxxxxxxxxxxxxxxxxxx~66ailed' (NUL-terminated)");
static_assert(text_is("REFUSED - unsupported action 'xxxxxxxxxxxxxxxxxxx\?\?\?\?e'", unsupported_action_text("xxxxxxxxxxxxxxxxxxxf" "ailed", 25)), "FB-B2 text: unsupported_action_text 'xxxxxxxxxxxxxxxxxxx~66ailed' (explicit length)");
static_assert(text_is("REFUSED - unsupported action 'xxxxxxxxxxxxxxxxxxx\?\?\?\?e'", action_refusal_text(0, "xxxxxxxxxxxxxxxxxxxf" "ailed", 25)), "FB-B2 text: action_refusal_text unsupported echo of 'xxxxxxxxxxxxxxxxxxx~66ailed'");
static_assert(text_is("REFUSED - unsupported action 'xxxxxxxxxxxxxxxxxxx\?\?\?\?E'", unsupported_action_text("xxxxxxxxxxxxxxxxxxxF" "AILED")), "FB-B2 text: unsupported_action_text 'xxxxxxxxxxxxxxxxxxx~46AILED' (NUL-terminated)");
static_assert(text_is("REFUSED - unsupported action 'xxxxxxxxxxxxxxxxxxx\?\?\?\?E'", unsupported_action_text("xxxxxxxxxxxxxxxxxxxF" "AILED", 25)), "FB-B2 text: unsupported_action_text 'xxxxxxxxxxxxxxxxxxx~46AILED' (explicit length)");
static_assert(text_is("REFUSED - unsupported action 'xxxxxxxxxxxxxxxxxxx\?\?\?\?E'", action_refusal_text(0, "xxxxxxxxxxxxxxxxxxxF" "AILED", 25)), "FB-B2 text: action_refusal_text unsupported echo of 'xxxxxxxxxxxxxxxxxxx~46AILED'");
static_assert(text_is("REFUSED - unsupported action 'xxxxxxxxxxxxxxxxxxx\?\?\?\?\?'", unsupported_action_text("xxxxxxxxxxxxxxxxxxxd" "eferred")), "FB-B2 text: unsupported_action_text 'xxxxxxxxxxxxxxxxxxx~64eferred' (NUL-terminated)");
static_assert(text_is("REFUSED - unsupported action 'xxxxxxxxxxxxxxxxxxx\?\?\?\?\?'", unsupported_action_text("xxxxxxxxxxxxxxxxxxxd" "eferred", 27)), "FB-B2 text: unsupported_action_text 'xxxxxxxxxxxxxxxxxxx~64eferred' (explicit length)");
static_assert(text_is("REFUSED - unsupported action 'xxxxxxxxxxxxxxxxxxx\?\?\?\?\?'", action_refusal_text(0, "xxxxxxxxxxxxxxxxxxxd" "eferred", 27)), "FB-B2 text: action_refusal_text unsupported echo of 'xxxxxxxxxxxxxxxxxxx~64eferred'");
static_assert(text_is("REFUSED - unsupported action 'xxxxxxxxxxxxxxxxxxx\?\?\?\?\?'", unsupported_action_text("xxxxxxxxxxxxxxxxxxxD" "eFeReD")), "FB-B2 text: unsupported_action_text 'xxxxxxxxxxxxxxxxxxx~44eFeReD' (NUL-terminated)");
static_assert(text_is("REFUSED - unsupported action 'xxxxxxxxxxxxxxxxxxx\?\?\?\?\?'", unsupported_action_text("xxxxxxxxxxxxxxxxxxxD" "eFeReD", 26)), "FB-B2 text: unsupported_action_text 'xxxxxxxxxxxxxxxxxxx~44eFeReD' (explicit length)");
static_assert(text_is("REFUSED - unsupported action 'xxxxxxxxxxxxxxxxxxx\?\?\?\?\?'", action_refusal_text(0, "xxxxxxxxxxxxxxxxxxxD" "eFeReD", 26)), "FB-B2 text: action_refusal_text unsupported echo of 'xxxxxxxxxxxxxxxxxxx~44eFeReD'");
static_assert(text_is("REFUSED - unsupported action 'xxxxxxxxxxxxxxxxxxxx\?\?\?\?'", unsupported_action_text("xxxxxxxxxxxxxxxxxxxxf" "ailed")), "FB-B2 text: unsupported_action_text 'xxxxxxxxxxxxxxxxxxxx~66ailed' (NUL-terminated)");
static_assert(text_is("REFUSED - unsupported action 'xxxxxxxxxxxxxxxxxxxx\?\?\?\?'", unsupported_action_text("xxxxxxxxxxxxxxxxxxxxf" "ailed", 26)), "FB-B2 text: unsupported_action_text 'xxxxxxxxxxxxxxxxxxxx~66ailed' (explicit length)");
static_assert(text_is("REFUSED - unsupported action 'xxxxxxxxxxxxxxxxxxxx\?\?\?\?'", action_refusal_text(0, "xxxxxxxxxxxxxxxxxxxxf" "ailed", 26)), "FB-B2 text: action_refusal_text unsupported echo of 'xxxxxxxxxxxxxxxxxxxx~66ailed'");
static_assert(text_is("REFUSED - unsupported action 'xxxxxxxxxxxxxxxxxxxx\?\?\?\?'", unsupported_action_text("xxxxxxxxxxxxxxxxxxxxF" "AILED")), "FB-B2 text: unsupported_action_text 'xxxxxxxxxxxxxxxxxxxx~46AILED' (NUL-terminated)");
static_assert(text_is("REFUSED - unsupported action 'xxxxxxxxxxxxxxxxxxxx\?\?\?\?'", unsupported_action_text("xxxxxxxxxxxxxxxxxxxxF" "AILED", 26)), "FB-B2 text: unsupported_action_text 'xxxxxxxxxxxxxxxxxxxx~46AILED' (explicit length)");
static_assert(text_is("REFUSED - unsupported action 'xxxxxxxxxxxxxxxxxxxx\?\?\?\?'", action_refusal_text(0, "xxxxxxxxxxxxxxxxxxxxF" "AILED", 26)), "FB-B2 text: action_refusal_text unsupported echo of 'xxxxxxxxxxxxxxxxxxxx~46AILED'");
static_assert(text_is("REFUSED - unsupported action 'xxxxxxxxxxxxxxxxxxxx\?\?\?\?'", unsupported_action_text("xxxxxxxxxxxxxxxxxxxxd" "eferred")), "FB-B2 text: unsupported_action_text 'xxxxxxxxxxxxxxxxxxxx~64eferred' (NUL-terminated)");
static_assert(text_is("REFUSED - unsupported action 'xxxxxxxxxxxxxxxxxxxx\?\?\?\?'", unsupported_action_text("xxxxxxxxxxxxxxxxxxxxd" "eferred", 28)), "FB-B2 text: unsupported_action_text 'xxxxxxxxxxxxxxxxxxxx~64eferred' (explicit length)");
static_assert(text_is("REFUSED - unsupported action 'xxxxxxxxxxxxxxxxxxxx\?\?\?\?'", action_refusal_text(0, "xxxxxxxxxxxxxxxxxxxxd" "eferred", 28)), "FB-B2 text: action_refusal_text unsupported echo of 'xxxxxxxxxxxxxxxxxxxx~64eferred'");
static_assert(text_is("REFUSED - unsupported action 'xxxxxxxxxxxxxxxxxxxx\?\?\?\?'", unsupported_action_text("xxxxxxxxxxxxxxxxxxxxD" "eFeReD")), "FB-B2 text: unsupported_action_text 'xxxxxxxxxxxxxxxxxxxx~44eFeReD' (NUL-terminated)");
static_assert(text_is("REFUSED - unsupported action 'xxxxxxxxxxxxxxxxxxxx\?\?\?\?'", unsupported_action_text("xxxxxxxxxxxxxxxxxxxxD" "eFeReD", 27)), "FB-B2 text: unsupported_action_text 'xxxxxxxxxxxxxxxxxxxx~44eFeReD' (explicit length)");
static_assert(text_is("REFUSED - unsupported action 'xxxxxxxxxxxxxxxxxxxx\?\?\?\?'", action_refusal_text(0, "xxxxxxxxxxxxxxxxxxxxD" "eFeReD", 27)), "FB-B2 text: action_refusal_text unsupported echo of 'xxxxxxxxxxxxxxxxxxxx~44eFeReD'");
static_assert(text_is("REFUSED - unsupported action 'xxxxxxxxxxxxxxxxxxxxx\?\?\?'", unsupported_action_text("xxxxxxxxxxxxxxxxxxxxxf" "ailed")), "FB-B2 text: unsupported_action_text 'xxxxxxxxxxxxxxxxxxxxx~66ailed' (NUL-terminated)");
static_assert(text_is("REFUSED - unsupported action 'xxxxxxxxxxxxxxxxxxxxx\?\?\?'", unsupported_action_text("xxxxxxxxxxxxxxxxxxxxxf" "ailed", 27)), "FB-B2 text: unsupported_action_text 'xxxxxxxxxxxxxxxxxxxxx~66ailed' (explicit length)");
static_assert(text_is("REFUSED - unsupported action 'xxxxxxxxxxxxxxxxxxxxx\?\?\?'", action_refusal_text(0, "xxxxxxxxxxxxxxxxxxxxxf" "ailed", 27)), "FB-B2 text: action_refusal_text unsupported echo of 'xxxxxxxxxxxxxxxxxxxxx~66ailed'");
static_assert(text_is("REFUSED - unsupported action 'xxxxxxxxxxxxxxxxxxxxx\?\?\?'", unsupported_action_text("xxxxxxxxxxxxxxxxxxxxxF" "AILED")), "FB-B2 text: unsupported_action_text 'xxxxxxxxxxxxxxxxxxxxx~46AILED' (NUL-terminated)");
static_assert(text_is("REFUSED - unsupported action 'xxxxxxxxxxxxxxxxxxxxx\?\?\?'", unsupported_action_text("xxxxxxxxxxxxxxxxxxxxxF" "AILED", 27)), "FB-B2 text: unsupported_action_text 'xxxxxxxxxxxxxxxxxxxxx~46AILED' (explicit length)");
static_assert(text_is("REFUSED - unsupported action 'xxxxxxxxxxxxxxxxxxxxx\?\?\?'", action_refusal_text(0, "xxxxxxxxxxxxxxxxxxxxxF" "AILED", 27)), "FB-B2 text: action_refusal_text unsupported echo of 'xxxxxxxxxxxxxxxxxxxxx~46AILED'");
static_assert(text_is("REFUSED - unsupported action 'xxxxxxxxxxxxxxxxxxxxx\?\?\?'", unsupported_action_text("xxxxxxxxxxxxxxxxxxxxxd" "eferred")), "FB-B2 text: unsupported_action_text 'xxxxxxxxxxxxxxxxxxxxx~64eferred' (NUL-terminated)");
static_assert(text_is("REFUSED - unsupported action 'xxxxxxxxxxxxxxxxxxxxx\?\?\?'", unsupported_action_text("xxxxxxxxxxxxxxxxxxxxxd" "eferred", 29)), "FB-B2 text: unsupported_action_text 'xxxxxxxxxxxxxxxxxxxxx~64eferred' (explicit length)");
static_assert(text_is("REFUSED - unsupported action 'xxxxxxxxxxxxxxxxxxxxx\?\?\?'", action_refusal_text(0, "xxxxxxxxxxxxxxxxxxxxxd" "eferred", 29)), "FB-B2 text: action_refusal_text unsupported echo of 'xxxxxxxxxxxxxxxxxxxxx~64eferred'");
static_assert(text_is("REFUSED - unsupported action 'xxxxxxxxxxxxxxxxxxxxx\?\?\?'", unsupported_action_text("xxxxxxxxxxxxxxxxxxxxxD" "eFeReD")), "FB-B2 text: unsupported_action_text 'xxxxxxxxxxxxxxxxxxxxx~44eFeReD' (NUL-terminated)");
static_assert(text_is("REFUSED - unsupported action 'xxxxxxxxxxxxxxxxxxxxx\?\?\?'", unsupported_action_text("xxxxxxxxxxxxxxxxxxxxxD" "eFeReD", 28)), "FB-B2 text: unsupported_action_text 'xxxxxxxxxxxxxxxxxxxxx~44eFeReD' (explicit length)");
static_assert(text_is("REFUSED - unsupported action 'xxxxxxxxxxxxxxxxxxxxx\?\?\?'", action_refusal_text(0, "xxxxxxxxxxxxxxxxxxxxxD" "eFeReD", 28)), "FB-B2 text: action_refusal_text unsupported echo of 'xxxxxxxxxxxxxxxxxxxxx~44eFeReD'");
static_assert(text_is("REFUSED - unsupported action 'xxxxxxxxxxxxxxxxxxxxxx\?\?'", unsupported_action_text("xxxxxxxxxxxxxxxxxxxxxxf" "ailed")), "FB-B2 text: unsupported_action_text 'xxxxxxxxxxxxxxxxxxxxxx~66ailed' (NUL-terminated)");
static_assert(text_is("REFUSED - unsupported action 'xxxxxxxxxxxxxxxxxxxxxx\?\?'", unsupported_action_text("xxxxxxxxxxxxxxxxxxxxxxf" "ailed", 28)), "FB-B2 text: unsupported_action_text 'xxxxxxxxxxxxxxxxxxxxxx~66ailed' (explicit length)");
static_assert(text_is("REFUSED - unsupported action 'xxxxxxxxxxxxxxxxxxxxxx\?\?'", action_refusal_text(0, "xxxxxxxxxxxxxxxxxxxxxxf" "ailed", 28)), "FB-B2 text: action_refusal_text unsupported echo of 'xxxxxxxxxxxxxxxxxxxxxx~66ailed'");
static_assert(text_is("REFUSED - unsupported action 'xxxxxxxxxxxxxxxxxxxxxx\?\?'", unsupported_action_text("xxxxxxxxxxxxxxxxxxxxxxF" "AILED")), "FB-B2 text: unsupported_action_text 'xxxxxxxxxxxxxxxxxxxxxx~46AILED' (NUL-terminated)");
static_assert(text_is("REFUSED - unsupported action 'xxxxxxxxxxxxxxxxxxxxxx\?\?'", unsupported_action_text("xxxxxxxxxxxxxxxxxxxxxxF" "AILED", 28)), "FB-B2 text: unsupported_action_text 'xxxxxxxxxxxxxxxxxxxxxx~46AILED' (explicit length)");
static_assert(text_is("REFUSED - unsupported action 'xxxxxxxxxxxxxxxxxxxxxx\?\?'", action_refusal_text(0, "xxxxxxxxxxxxxxxxxxxxxxF" "AILED", 28)), "FB-B2 text: action_refusal_text unsupported echo of 'xxxxxxxxxxxxxxxxxxxxxx~46AILED'");
static_assert(text_is("REFUSED - unsupported action 'xxxxxxxxxxxxxxxxxxxxxx\?\?'", unsupported_action_text("xxxxxxxxxxxxxxxxxxxxxxd" "eferred")), "FB-B2 text: unsupported_action_text 'xxxxxxxxxxxxxxxxxxxxxx~64eferred' (NUL-terminated)");
static_assert(text_is("REFUSED - unsupported action 'xxxxxxxxxxxxxxxxxxxxxx\?\?'", unsupported_action_text("xxxxxxxxxxxxxxxxxxxxxxd" "eferred", 30)), "FB-B2 text: unsupported_action_text 'xxxxxxxxxxxxxxxxxxxxxx~64eferred' (explicit length)");
static_assert(text_is("REFUSED - unsupported action 'xxxxxxxxxxxxxxxxxxxxxx\?\?'", action_refusal_text(0, "xxxxxxxxxxxxxxxxxxxxxxd" "eferred", 30)), "FB-B2 text: action_refusal_text unsupported echo of 'xxxxxxxxxxxxxxxxxxxxxx~64eferred'");
static_assert(text_is("REFUSED - unsupported action 'xxxxxxxxxxxxxxxxxxxxxx\?\?'", unsupported_action_text("xxxxxxxxxxxxxxxxxxxxxxD" "eFeReD")), "FB-B2 text: unsupported_action_text 'xxxxxxxxxxxxxxxxxxxxxx~44eFeReD' (NUL-terminated)");
static_assert(text_is("REFUSED - unsupported action 'xxxxxxxxxxxxxxxxxxxxxx\?\?'", unsupported_action_text("xxxxxxxxxxxxxxxxxxxxxxD" "eFeReD", 29)), "FB-B2 text: unsupported_action_text 'xxxxxxxxxxxxxxxxxxxxxx~44eFeReD' (explicit length)");
static_assert(text_is("REFUSED - unsupported action 'xxxxxxxxxxxxxxxxxxxxxx\?\?'", action_refusal_text(0, "xxxxxxxxxxxxxxxxxxxxxxD" "eFeReD", 29)), "FB-B2 text: action_refusal_text unsupported echo of 'xxxxxxxxxxxxxxxxxxxxxx~44eFeReD'");
static_assert(text_is("REFUSED - unsupported action 'xxxxxxxxxxxxxxxxxxxxxxx\?'", unsupported_action_text("xxxxxxxxxxxxxxxxxxxxxxxf" "ailed")), "FB-B2 text: unsupported_action_text 'xxxxxxxxxxxxxxxxxxxxxxx~66ailed' (NUL-terminated)");
static_assert(text_is("REFUSED - unsupported action 'xxxxxxxxxxxxxxxxxxxxxxx\?'", unsupported_action_text("xxxxxxxxxxxxxxxxxxxxxxxf" "ailed", 29)), "FB-B2 text: unsupported_action_text 'xxxxxxxxxxxxxxxxxxxxxxx~66ailed' (explicit length)");
static_assert(text_is("REFUSED - unsupported action 'xxxxxxxxxxxxxxxxxxxxxxx\?'", action_refusal_text(0, "xxxxxxxxxxxxxxxxxxxxxxxf" "ailed", 29)), "FB-B2 text: action_refusal_text unsupported echo of 'xxxxxxxxxxxxxxxxxxxxxxx~66ailed'");
static_assert(text_is("REFUSED - unsupported action 'xxxxxxxxxxxxxxxxxxxxxxx\?'", unsupported_action_text("xxxxxxxxxxxxxxxxxxxxxxxF" "AILED")), "FB-B2 text: unsupported_action_text 'xxxxxxxxxxxxxxxxxxxxxxx~46AILED' (NUL-terminated)");
static_assert(text_is("REFUSED - unsupported action 'xxxxxxxxxxxxxxxxxxxxxxx\?'", unsupported_action_text("xxxxxxxxxxxxxxxxxxxxxxxF" "AILED", 29)), "FB-B2 text: unsupported_action_text 'xxxxxxxxxxxxxxxxxxxxxxx~46AILED' (explicit length)");
static_assert(text_is("REFUSED - unsupported action 'xxxxxxxxxxxxxxxxxxxxxxx\?'", action_refusal_text(0, "xxxxxxxxxxxxxxxxxxxxxxxF" "AILED", 29)), "FB-B2 text: action_refusal_text unsupported echo of 'xxxxxxxxxxxxxxxxxxxxxxx~46AILED'");
static_assert(text_is("REFUSED - unsupported action 'xxxxxxxxxxxxxxxxxxxxxxx\?'", unsupported_action_text("xxxxxxxxxxxxxxxxxxxxxxxd" "eferred")), "FB-B2 text: unsupported_action_text 'xxxxxxxxxxxxxxxxxxxxxxx~64eferred' (NUL-terminated)");
static_assert(text_is("REFUSED - unsupported action 'xxxxxxxxxxxxxxxxxxxxxxx\?'", unsupported_action_text("xxxxxxxxxxxxxxxxxxxxxxxd" "eferred", 31)), "FB-B2 text: unsupported_action_text 'xxxxxxxxxxxxxxxxxxxxxxx~64eferred' (explicit length)");
static_assert(text_is("REFUSED - unsupported action 'xxxxxxxxxxxxxxxxxxxxxxx\?'", action_refusal_text(0, "xxxxxxxxxxxxxxxxxxxxxxxd" "eferred", 31)), "FB-B2 text: action_refusal_text unsupported echo of 'xxxxxxxxxxxxxxxxxxxxxxx~64eferred'");
static_assert(text_is("REFUSED - unsupported action 'xxxxxxxxxxxxxxxxxxxxxxx\?'", unsupported_action_text("xxxxxxxxxxxxxxxxxxxxxxxD" "eFeReD")), "FB-B2 text: unsupported_action_text 'xxxxxxxxxxxxxxxxxxxxxxx~44eFeReD' (NUL-terminated)");
static_assert(text_is("REFUSED - unsupported action 'xxxxxxxxxxxxxxxxxxxxxxx\?'", unsupported_action_text("xxxxxxxxxxxxxxxxxxxxxxxD" "eFeReD", 30)), "FB-B2 text: unsupported_action_text 'xxxxxxxxxxxxxxxxxxxxxxx~44eFeReD' (explicit length)");
static_assert(text_is("REFUSED - unsupported action 'xxxxxxxxxxxxxxxxxxxxxxx\?'", action_refusal_text(0, "xxxxxxxxxxxxxxxxxxxxxxxD" "eFeReD", 30)), "FB-B2 text: action_refusal_text unsupported echo of 'xxxxxxxxxxxxxxxxxxxxxxx~44eFeReD'");
static_assert(text_is("REFUSED - unsupported action 'xxxxxxxxxxxxxxxxxxxxxxxx'", unsupported_action_text("xxxxxxxxxxxxxxxxxxxxxxxxf" "ailed")), "FB-B2 text: unsupported_action_text 'xxxxxxxxxxxxxxxxxxxxxxxx~66ailed' (NUL-terminated)");
static_assert(text_is("REFUSED - unsupported action 'xxxxxxxxxxxxxxxxxxxxxxxx'", unsupported_action_text("xxxxxxxxxxxxxxxxxxxxxxxxf" "ailed", 30)), "FB-B2 text: unsupported_action_text 'xxxxxxxxxxxxxxxxxxxxxxxx~66ailed' (explicit length)");
static_assert(text_is("REFUSED - unsupported action 'xxxxxxxxxxxxxxxxxxxxxxxx'", action_refusal_text(0, "xxxxxxxxxxxxxxxxxxxxxxxxf" "ailed", 30)), "FB-B2 text: action_refusal_text unsupported echo of 'xxxxxxxxxxxxxxxxxxxxxxxx~66ailed'");
static_assert(text_is("REFUSED - unsupported action 'xxxxxxxxxxxxxxxxxxxxxxxx'", unsupported_action_text("xxxxxxxxxxxxxxxxxxxxxxxxF" "AILED")), "FB-B2 text: unsupported_action_text 'xxxxxxxxxxxxxxxxxxxxxxxx~46AILED' (NUL-terminated)");
static_assert(text_is("REFUSED - unsupported action 'xxxxxxxxxxxxxxxxxxxxxxxx'", unsupported_action_text("xxxxxxxxxxxxxxxxxxxxxxxxF" "AILED", 30)), "FB-B2 text: unsupported_action_text 'xxxxxxxxxxxxxxxxxxxxxxxx~46AILED' (explicit length)");
static_assert(text_is("REFUSED - unsupported action 'xxxxxxxxxxxxxxxxxxxxxxxx'", action_refusal_text(0, "xxxxxxxxxxxxxxxxxxxxxxxxF" "AILED", 30)), "FB-B2 text: action_refusal_text unsupported echo of 'xxxxxxxxxxxxxxxxxxxxxxxx~46AILED'");
static_assert(text_is("REFUSED - unsupported action 'xxxxxxxxxxxxxxxxxxxxxxxx'", unsupported_action_text("xxxxxxxxxxxxxxxxxxxxxxxxd" "eferred")), "FB-B2 text: unsupported_action_text 'xxxxxxxxxxxxxxxxxxxxxxxx~64eferred' (NUL-terminated)");
static_assert(text_is("REFUSED - unsupported action 'xxxxxxxxxxxxxxxxxxxxxxxx'", unsupported_action_text("xxxxxxxxxxxxxxxxxxxxxxxxd" "eferred", 32)), "FB-B2 text: unsupported_action_text 'xxxxxxxxxxxxxxxxxxxxxxxx~64eferred' (explicit length)");
static_assert(text_is("REFUSED - unsupported action 'xxxxxxxxxxxxxxxxxxxxxxxx'", action_refusal_text(0, "xxxxxxxxxxxxxxxxxxxxxxxxd" "eferred", 32)), "FB-B2 text: action_refusal_text unsupported echo of 'xxxxxxxxxxxxxxxxxxxxxxxx~64eferred'");
static_assert(text_is("REFUSED - unsupported action 'xxxxxxxxxxxxxxxxxxxxxxxx'", unsupported_action_text("xxxxxxxxxxxxxxxxxxxxxxxxD" "eFeReD")), "FB-B2 text: unsupported_action_text 'xxxxxxxxxxxxxxxxxxxxxxxx~44eFeReD' (NUL-terminated)");
static_assert(text_is("REFUSED - unsupported action 'xxxxxxxxxxxxxxxxxxxxxxxx'", unsupported_action_text("xxxxxxxxxxxxxxxxxxxxxxxxD" "eFeReD", 31)), "FB-B2 text: unsupported_action_text 'xxxxxxxxxxxxxxxxxxxxxxxx~44eFeReD' (explicit length)");
static_assert(text_is("REFUSED - unsupported action 'xxxxxxxxxxxxxxxxxxxxxxxx'", action_refusal_text(0, "xxxxxxxxxxxxxxxxxxxxxxxxD" "eFeReD", 31)), "FB-B2 text: action_refusal_text unsupported echo of 'xxxxxxxxxxxxxxxxxxxxxxxx~44eFeReD'");
static_assert(text_is("REFUSED - unsupported action 'xxxxxxxxxxxxxxxxxxxxxxxx'", unsupported_action_text("xxxxxxxxxxxxxxxxxxxxxxxxxf" "ailed")), "FB-B2 text: unsupported_action_text 'xxxxxxxxxxxxxxxxxxxxxxxxx~66ailed' (NUL-terminated)");
static_assert(text_is("REFUSED - unsupported action 'xxxxxxxxxxxxxxxxxxxxxxxx'", unsupported_action_text("xxxxxxxxxxxxxxxxxxxxxxxxxf" "ailed", 31)), "FB-B2 text: unsupported_action_text 'xxxxxxxxxxxxxxxxxxxxxxxxx~66ailed' (explicit length)");
static_assert(text_is("REFUSED - unsupported action 'xxxxxxxxxxxxxxxxxxxxxxxx'", action_refusal_text(0, "xxxxxxxxxxxxxxxxxxxxxxxxxf" "ailed", 31)), "FB-B2 text: action_refusal_text unsupported echo of 'xxxxxxxxxxxxxxxxxxxxxxxxx~66ailed'");
static_assert(text_is("REFUSED - unsupported action 'xxxxxxxxxxxxxxxxxxxxxxxx'", unsupported_action_text("xxxxxxxxxxxxxxxxxxxxxxxxxF" "AILED")), "FB-B2 text: unsupported_action_text 'xxxxxxxxxxxxxxxxxxxxxxxxx~46AILED' (NUL-terminated)");
static_assert(text_is("REFUSED - unsupported action 'xxxxxxxxxxxxxxxxxxxxxxxx'", unsupported_action_text("xxxxxxxxxxxxxxxxxxxxxxxxxF" "AILED", 31)), "FB-B2 text: unsupported_action_text 'xxxxxxxxxxxxxxxxxxxxxxxxx~46AILED' (explicit length)");
static_assert(text_is("REFUSED - unsupported action 'xxxxxxxxxxxxxxxxxxxxxxxx'", action_refusal_text(0, "xxxxxxxxxxxxxxxxxxxxxxxxxF" "AILED", 31)), "FB-B2 text: action_refusal_text unsupported echo of 'xxxxxxxxxxxxxxxxxxxxxxxxx~46AILED'");
static_assert(text_is("REFUSED - unsupported action 'xxxxxxxxxxxxxxxxxxxxxxxx'", unsupported_action_text("xxxxxxxxxxxxxxxxxxxxxxxxxd" "eferred")), "FB-B2 text: unsupported_action_text 'xxxxxxxxxxxxxxxxxxxxxxxxx~64eferred' (NUL-terminated)");
static_assert(text_is("REFUSED - unsupported action 'xxxxxxxxxxxxxxxxxxxxxxxx'", unsupported_action_text("xxxxxxxxxxxxxxxxxxxxxxxxxd" "eferred", 33)), "FB-B2 text: unsupported_action_text 'xxxxxxxxxxxxxxxxxxxxxxxxx~64eferred' (explicit length)");
static_assert(text_is("REFUSED - unsupported action 'xxxxxxxxxxxxxxxxxxxxxxxx'", action_refusal_text(0, "xxxxxxxxxxxxxxxxxxxxxxxxxd" "eferred", 33)), "FB-B2 text: action_refusal_text unsupported echo of 'xxxxxxxxxxxxxxxxxxxxxxxxx~64eferred'");
static_assert(text_is("REFUSED - unsupported action 'xxxxxxxxxxxxxxxxxxxxxxxx'", unsupported_action_text("xxxxxxxxxxxxxxxxxxxxxxxxxD" "eFeReD")), "FB-B2 text: unsupported_action_text 'xxxxxxxxxxxxxxxxxxxxxxxxx~44eFeReD' (NUL-terminated)");
static_assert(text_is("REFUSED - unsupported action 'xxxxxxxxxxxxxxxxxxxxxxxx'", unsupported_action_text("xxxxxxxxxxxxxxxxxxxxxxxxxD" "eFeReD", 32)), "FB-B2 text: unsupported_action_text 'xxxxxxxxxxxxxxxxxxxxxxxxx~44eFeReD' (explicit length)");
static_assert(text_is("REFUSED - unsupported action 'xxxxxxxxxxxxxxxxxxxxxxxx'", action_refusal_text(0, "xxxxxxxxxxxxxxxxxxxxxxxxxD" "eFeReD", 32)), "FB-B2 text: action_refusal_text unsupported echo of 'xxxxxxxxxxxxxxxxxxxxxxxxx~44eFeReD'");
static_assert(text_is("REFUSED - unsupported action 'xxxxxxxxxxxxxxxxxxxxxxxf'", unsupported_action_text("xxxxxxxxxxxxxxxxxxxxxxxfox")), "FB-B2 text: unsupported_action_text 'xxxxxxxxxxxxxxxxxxxxxxxfox' (NUL-terminated)");
static_assert(text_is("REFUSED - unsupported action 'xxxxxxxxxxxxxxxxxxxxxxxf'", unsupported_action_text("xxxxxxxxxxxxxxxxxxxxxxxfox", 26)), "FB-B2 text: unsupported_action_text 'xxxxxxxxxxxxxxxxxxxxxxxfox' (explicit length)");
static_assert(text_is("REFUSED - unsupported action 'xxxxxxxxxxxxxxxxxxxxxxxf'", action_refusal_text(0, "xxxxxxxxxxxxxxxxxxxxxxxfox", 26)), "FB-B2 text: action_refusal_text unsupported echo of 'xxxxxxxxxxxxxxxxxxxxxxxfox'");
static_assert(text_is("REFUSED - unsupported action 'xxxxxxxxxxxxxxxxxxxxxxxd'", unsupported_action_text("xxxxxxxxxxxxxxxxxxxxxxxdex")), "FB-B2 text: unsupported_action_text 'xxxxxxxxxxxxxxxxxxxxxxxdex' (NUL-terminated)");
static_assert(text_is("REFUSED - unsupported action 'xxxxxxxxxxxxxxxxxxxxxxxd'", unsupported_action_text("xxxxxxxxxxxxxxxxxxxxxxxdex", 26)), "FB-B2 text: unsupported_action_text 'xxxxxxxxxxxxxxxxxxxxxxxdex' (explicit length)");
static_assert(text_is("REFUSED - unsupported action 'xxxxxxxxxxxxxxxxxxxxxxxd'", action_refusal_text(0, "xxxxxxxxxxxxxxxxxxxxxxxdex", 26)), "FB-B2 text: action_refusal_text unsupported echo of 'xxxxxxxxxxxxxxxxxxxxxxxdex'");
static_assert(text_is("REFUSED - unsupported action 'xxxxxxxxxxxxxxxxxxxxxxxf'", unsupported_action_text("xxxxxxxxxxxxxxxxxxxxxxxfa")), "FB-B2 text: unsupported_action_text 'xxxxxxxxxxxxxxxxxxxxxxxfa' (NUL-terminated)");
static_assert(text_is("REFUSED - unsupported action 'xxxxxxxxxxxxxxxxxxxxxxxf'", unsupported_action_text("xxxxxxxxxxxxxxxxxxxxxxxfa", 25)), "FB-B2 text: unsupported_action_text 'xxxxxxxxxxxxxxxxxxxxxxxfa' (explicit length)");
static_assert(text_is("REFUSED - unsupported action 'xxxxxxxxxxxxxxxxxxxxxxxf'", action_refusal_text(0, "xxxxxxxxxxxxxxxxxxxxxxxfa", 25)), "FB-B2 text: action_refusal_text unsupported echo of 'xxxxxxxxxxxxxxxxxxxxxxxfa'");
static_assert(text_is("REFUSED - unsupported action 'xxxxxxxxxxxxxxxxxxxxxxfa'", unsupported_action_text("xxxxxxxxxxxxxxxxxxxxxxfai")), "FB-B2 text: unsupported_action_text 'xxxxxxxxxxxxxxxxxxxxxxfai' (NUL-terminated)");
static_assert(text_is("REFUSED - unsupported action 'xxxxxxxxxxxxxxxxxxxxxxfa'", unsupported_action_text("xxxxxxxxxxxxxxxxxxxxxxfai", 25)), "FB-B2 text: unsupported_action_text 'xxxxxxxxxxxxxxxxxxxxxxfai' (explicit length)");
static_assert(text_is("REFUSED - unsupported action 'xxxxxxxxxxxxxxxxxxxxxxfa'", action_refusal_text(0, "xxxxxxxxxxxxxxxxxxxxxxfai", 25)), "FB-B2 text: action_refusal_text unsupported echo of 'xxxxxxxxxxxxxxxxxxxxxxfai'");
static_assert(text_is("REFUSED - unsupported action 'xxxxxxxxxxxxxxxxxxxxxxxd'", unsupported_action_text("xxxxxxxxxxxxxxxxxxxxxxxde")), "FB-B2 text: unsupported_action_text 'xxxxxxxxxxxxxxxxxxxxxxxde' (NUL-terminated)");
static_assert(text_is("REFUSED - unsupported action 'xxxxxxxxxxxxxxxxxxxxxxxd'", unsupported_action_text("xxxxxxxxxxxxxxxxxxxxxxxde", 25)), "FB-B2 text: unsupported_action_text 'xxxxxxxxxxxxxxxxxxxxxxxde' (explicit length)");
static_assert(text_is("REFUSED - unsupported action 'xxxxxxxxxxxxxxxxxxxxxxxd'", action_refusal_text(0, "xxxxxxxxxxxxxxxxxxxxxxxde", 25)), "FB-B2 text: action_refusal_text unsupported echo of 'xxxxxxxxxxxxxxxxxxxxxxxde'");
static_assert(text_is("REFUSED - unsupported action 'xxxxxxxxxxxxxxxxxxxxxxxx'", unsupported_action_text("xxxxxxxxxxxxxxxxxxxxxxxxf" "ail")), "FB-B2 text: unsupported_action_text 'xxxxxxxxxxxxxxxxxxxxxxxx~66ail' (NUL-terminated)");
static_assert(text_is("REFUSED - unsupported action 'xxxxxxxxxxxxxxxxxxxxxxxx'", unsupported_action_text("xxxxxxxxxxxxxxxxxxxxxxxxf" "ail", 28)), "FB-B2 text: unsupported_action_text 'xxxxxxxxxxxxxxxxxxxxxxxx~66ail' (explicit length)");
static_assert(text_is("REFUSED - unsupported action 'xxxxxxxxxxxxxxxxxxxxxxxx'", action_refusal_text(0, "xxxxxxxxxxxxxxxxxxxxxxxxf" "ail", 28)), "FB-B2 text: action_refusal_text unsupported echo of 'xxxxxxxxxxxxxxxxxxxxxxxx~66ail'");
static_assert(text_is("REFUSED - unsupported action 'xxxxxxxxxxxxxxxxxxxxxxxx'", unsupported_action_text("xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxf" "ailed")), "FB-B2 text: unsupported_action_text 'xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx~66ailed' (NUL-terminated)");
static_assert(text_is("REFUSED - unsupported action 'xxxxxxxxxxxxxxxxxxxxxxxx'", unsupported_action_text("xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxf" "ailed", 46)), "FB-B2 text: unsupported_action_text 'xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx~66ailed' (explicit length)");
static_assert(text_is("REFUSED - unsupported action 'xxxxxxxxxxxxxxxxxxxxxxxx'", action_refusal_text(0, "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxf" "ailed", 46)), "FB-B2 text: action_refusal_text unsupported echo of 'xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx~66ailed'");
static_assert(text_is("REFUSED - unsupported action 'yyyyyyyyyyyy\?\?\?\?\?\?\?\?\?\?\?\?'", unsupported_action_text("yyyyyyyyyyyyd" "eferd" "eferd" "efer")), "FB-B2 text: unsupported_action_text 'yyyyyyyyyyyy~64efer~64efer~64efer' (NUL-terminated)");
static_assert(text_is("REFUSED - unsupported action 'yyyyyyyyyyyy\?\?\?\?\?\?\?\?\?\?\?\?'", unsupported_action_text("yyyyyyyyyyyyd" "eferd" "eferd" "efer", 27)), "FB-B2 text: unsupported_action_text 'yyyyyyyyyyyy~64efer~64efer~64efer' (explicit length)");
static_assert(text_is("REFUSED - unsupported action 'yyyyyyyyyyyy\?\?\?\?\?\?\?\?\?\?\?\?'", action_refusal_text(0, "yyyyyyyyyyyyd" "eferd" "eferd" "efer", 27)), "FB-B2 text: action_refusal_text unsupported echo of 'yyyyyyyyyyyy~64efer~64efer~64efer'");
static_assert(text_is("REFUSED - unsupported action ''", unsupported_action_text("f" "ailed", 0)), "FB-B2 text: unsupported_action_text '~66ailed' cut to 0 bytes");
static_assert(text_is("REFUSED - unsupported action 'f'", unsupported_action_text("f" "ailed", 1)), "FB-B2 text: unsupported_action_text '~66ailed' cut to 1 bytes");
static_assert(text_is("REFUSED - unsupported action 'fai'", unsupported_action_text("f" "ailed", 3)), "FB-B2 text: unsupported_action_text '~66ailed' cut to 3 bytes");
static_assert(text_is("REFUSED - unsupported action '\?\?\?\?'", unsupported_action_text("f" "ailed", 4)), "FB-B2 text: unsupported_action_text '~66ailed' cut to 4 bytes");
static_assert(text_is("REFUSED - unsupported action '\?\?\?\?e'", unsupported_action_text("f" "ailed", 5)), "FB-B2 text: unsupported_action_text '~66ailed' cut to 5 bytes");
static_assert(text_is("REFUSED - unsupported action 'defe'", unsupported_action_text("d" "eferred", 4)), "FB-B2 text: unsupported_action_text '~64eferred' cut to 4 bytes");
static_assert(text_is("REFUSED - unsupported action '\?\?\?\?\?'", unsupported_action_text("d" "eferred", 5)), "FB-B2 text: unsupported_action_text '~64eferred' cut to 5 bytes");
static_assert(text_is("REFUSED - unsupported action '\?\?\?\?\?r'", unsupported_action_text("d" "eferred", 6)), "FB-B2 text: unsupported_action_text '~64eferred' cut to 6 bytes");
static_assert(text_is("REFUSED - unsupported action 'xxxfai'", unsupported_action_text("xxxf" "ailed", 6)), "FB-B2 text: unsupported_action_text 'xxx~66ailed' cut to 6 bytes");
static_assert(text_is("REFUSED - unsupported action 'xxx\?\?\?\?'", unsupported_action_text("xxxf" "ailed", 7)), "FB-B2 text: unsupported_action_text 'xxx~66ailed' cut to 7 bytes");
static_assert(text_is("REFUSED - unsupported action 'FAI'", unsupported_action_text("F" "AILED", 3)), "FB-B2 text: unsupported_action_text '~46AILED' cut to 3 bytes");
static_assert(text_is("REFUSED - unsupported action '\?\?\?\?'", unsupported_action_text("f" "ail\000f" "ailed", 4)), "FB-B2 text: unsupported_action_text '~66ail~00~66ailed' cut to 4 bytes");
static_assert(text_is("REFUSED - unsupported action '\?\?\?\?\?\?\?\?\?ed'", unsupported_action_text("f" "ail\000f" "ailed", 11)), "FB-B2 text: unsupported_action_text '~66ail~00~66ailed' cut to 11 bytes");
static_assert(text_is("REFUSED - unsupported action 'fa\?il'", unsupported_action_text("fa\000il", 5)), "FB-B2 text: unsupported_action_text 'fa~00il' cut to 5 bytes");
static_assert(text_is("REFUSED - unsupported action '\?\?\?\?\?'", unsupported_action_text("f" "ail\000", 5)), "FB-B2 text: unsupported_action_text '~66ail~00' cut to 5 bytes");
static_assert(text_is("REFUSED - unsupported action '\?\?\?\?\?'", unsupported_action_text("\000f" "ail", 5)), "FB-B2 text: unsupported_action_text '~00~66ail' cut to 5 bytes");
static_assert(text_is("REFUSED - unsupported action '\?\?\?\?\?\?\?\?\?\?\?red'", unsupported_action_text("d" "efer\000d" "eferred", 14)), "FB-B2 text: unsupported_action_text '~64efer~00~64eferred' cut to 14 bytes");
static_assert(text_is("REFUSED - unsupported action '\?\?\?\?\?\?'", unsupported_action_text("f" "ail\303\251", 6)), "FB-B2 text: unsupported_action_text '~66ail~C3~A9' cut to 6 bytes");
static_assert(text_is("REFUSED - unsupported action 'xxxxxxxxxxxxxxxxxxxxxxxd'", unsupported_action_text("xxxxxxxxxxxxxxxxxxxxxxxd" "eferred", 24)), "FB-B2 text: unsupported_action_text 'xxxxxxxxxxxxxxxxxxxxxxx~64eferred' cut to 24 bytes");
static_assert(text_is("REFUSED - unsupported action 'xxxxxxxxxxxxxxxxxxxxxxxd'", unsupported_action_text("xxxxxxxxxxxxxxxxxxxxxxxd" "eferred", 25)), "FB-B2 text: unsupported_action_text 'xxxxxxxxxxxxxxxxxxxxxxx~64eferred' cut to 25 bytes");
static_assert(text_is("REFUSED - unsupported action 'xxxxxxxxxxxxxxxxxxxxxxxd'", unsupported_action_text("xxxxxxxxxxxxxxxxxxxxxxxd" "eferred", 27)), "FB-B2 text: unsupported_action_text 'xxxxxxxxxxxxxxxxxxxxxxx~64eferred' cut to 27 bytes");
static_assert(text_is("REFUSED - unsupported action 'xxxxxxxxxxxxxxxxxxxxxxx\?'", unsupported_action_text("xxxxxxxxxxxxxxxxxxxxxxxd" "eferred", 28)), "FB-B2 text: unsupported_action_text 'xxxxxxxxxxxxxxxxxxxxxxx~64eferred' cut to 28 bytes");
static_assert(text_is("\?\?\?\?ed", []{ TextBuf t; put_sanitised(t, "f" "ailed", 6); return t; }()), "FB-B2 text: put_sanitised '~66ailed' (explicit length)");
static_assert(text_is("\?\?\?\?ed", []{ TextBuf t; put_sanitised(t, "f" "ailed"); return t; }()), "FB-B2 text: put_sanitised '~66ailed' (NUL-terminated)");
static_assert(text_is("\?\?\?\?ED", []{ TextBuf t; put_sanitised(t, "F" "AILED", 6); return t; }()), "FB-B2 text: put_sanitised '~46AILED' (explicit length)");
static_assert(text_is("\?\?\?\?ED", []{ TextBuf t; put_sanitised(t, "F" "AILED"); return t; }()), "FB-B2 text: put_sanitised '~46AILED' (NUL-terminated)");
static_assert(text_is("\?\?\?\?\?red", []{ TextBuf t; put_sanitised(t, "d" "eferred", 8); return t; }()), "FB-B2 text: put_sanitised '~64eferred' (explicit length)");
static_assert(text_is("\?\?\?\?\?red", []{ TextBuf t; put_sanitised(t, "d" "eferred"); return t; }()), "FB-B2 text: put_sanitised '~64eferred' (NUL-terminated)");
static_assert(text_is("x\?\?\?\?\?rEdx", []{ TextBuf t; put_sanitised(t, "xD" "eFeRrEdx", 10); return t; }()), "FB-B2 text: put_sanitised 'x~44eFeRrEdx' (explicit length)");
static_assert(text_is("x\?\?\?\?\?rEdx", []{ TextBuf t; put_sanitised(t, "xD" "eFeRrEdx"); return t; }()), "FB-B2 text: put_sanitised 'x~44eFeRrEdx' (NUL-terminated)");
static_assert(text_is("\?\?\?\?", []{ TextBuf t; put_sanitised(t, "f" "ail", 4); return t; }()), "FB-B2 text: put_sanitised '~66ail' (explicit length)");
static_assert(text_is("\?\?\?\?", []{ TextBuf t; put_sanitised(t, "f" "ail"); return t; }()), "FB-B2 text: put_sanitised '~66ail' (NUL-terminated)");
static_assert(text_is("\?\?\?\?\?", []{ TextBuf t; put_sanitised(t, "d" "efer", 5); return t; }()), "FB-B2 text: put_sanitised '~64efer' (explicit length)");
static_assert(text_is("\?\?\?\?\?", []{ TextBuf t; put_sanitised(t, "d" "efer"); return t; }()), "FB-B2 text: put_sanitised '~64efer' (NUL-terminated)");
static_assert(text_is("\?\?\?\?\?\?\?\?", []{ TextBuf t; put_sanitised(t, "f" "ailf" "ail", 8); return t; }()), "FB-B2 text: put_sanitised '~66ail~66ail' (explicit length)");
static_assert(text_is("\?\?\?\?\?\?\?\?", []{ TextBuf t; put_sanitised(t, "f" "ailf" "ail"); return t; }()), "FB-B2 text: put_sanitised '~66ail~66ail' (NUL-terminated)");
static_assert(text_is("\?\?\?\?\?\?\?\?\?", []{ TextBuf t; put_sanitised(t, "f" "aild" "efer", 9); return t; }()), "FB-B2 text: put_sanitised '~66ail~64efer' (explicit length)");
static_assert(text_is("\?\?\?\?\?\?\?\?\?", []{ TextBuf t; put_sanitised(t, "f" "aild" "efer"); return t; }()), "FB-B2 text: put_sanitised '~66ail~64efer' (NUL-terminated)");
static_assert(text_is("fai", []{ TextBuf t; put_sanitised(t, "fai", 3); return t; }()), "FB-B2 text: put_sanitised 'fai' (explicit length)");
static_assert(text_is("fai", []{ TextBuf t; put_sanitised(t, "fai"); return t; }()), "FB-B2 text: put_sanitised 'fai' (NUL-terminated)");
static_assert(text_is("a\?\?\?\?\?ed\?b", []{ TextBuf t; put_sanitised(t, "a f" "ailed b", 10); return t; }()), "FB-B2 text: put_sanitised 'a ~66ailed b' (explicit length)");
static_assert(text_is("a\?\?\?\?\?ed\?b", []{ TextBuf t; put_sanitised(t, "a f" "ailed b"); return t; }()), "FB-B2 text: put_sanitised 'a ~66ailed b' (NUL-terminated)");
static_assert(text_is("\?\?\?\?\?\?\?\?\?ed", []{ TextBuf t; put_sanitised(t, "f" "ail\000f" "ailed", 11); return t; }()), "FB-B2 text: put_sanitised '~66ail~00~66ailed' (explicit length)");
static_assert(text_is("\?\?\?\?", []{ TextBuf t; put_sanitised(t, "f" "ail\000f" "ailed"); return t; }()), "FB-B2 text: put_sanitised '~66ail~00~66ailed' (NUL-terminated)");
static_assert(text_is("xxxxxxxxxxxxxxxxxxxx\?\?\?\?", []{ TextBuf t; put_sanitised(t, "xxxxxxxxxxxxxxxxxxxxF" "AILED", 26); return t; }()), "FB-B2 text: put_sanitised 'xxxxxxxxxxxxxxxxxxxx~46AILED' (explicit length)");
static_assert(text_is("xxxxxxxxxxxxxxxxxxxx\?\?\?\?", []{ TextBuf t; put_sanitised(t, "xxxxxxxxxxxxxxxxxxxxF" "AILED"); return t; }()), "FB-B2 text: put_sanitised 'xxxxxxxxxxxxxxxxxxxx~46AILED' (NUL-terminated)");
static_assert(text_is("xxxxxxxxxxxxxxxxxxxxx\?\?\?", []{ TextBuf t; put_sanitised(t, "xxxxxxxxxxxxxxxxxxxxxf" "ailed", 27); return t; }()), "FB-B2 text: put_sanitised 'xxxxxxxxxxxxxxxxxxxxx~66ailed' (explicit length)");
static_assert(text_is("xxxxxxxxxxxxxxxxxxxxx\?\?\?", []{ TextBuf t; put_sanitised(t, "xxxxxxxxxxxxxxxxxxxxxf" "ailed"); return t; }()), "FB-B2 text: put_sanitised 'xxxxxxxxxxxxxxxxxxxxx~66ailed' (NUL-terminated)");
static_assert(text_is("xxxxxxxxxxxxxxxxxxxxxxx\?", []{ TextBuf t; put_sanitised(t, "xxxxxxxxxxxxxxxxxxxxxxxd" "eferred", 31); return t; }()), "FB-B2 text: put_sanitised 'xxxxxxxxxxxxxxxxxxxxxxx~64eferred' (explicit length)");
static_assert(text_is("xxxxxxxxxxxxxxxxxxxxxxx\?", []{ TextBuf t; put_sanitised(t, "xxxxxxxxxxxxxxxxxxxxxxxd" "eferred"); return t; }()), "FB-B2 text: put_sanitised 'xxxxxxxxxxxxxxxxxxxxxxx~64eferred' (NUL-terminated)");
static_assert(text_is("xxxxxxxxxxxxxxxxxxxxxxxx", []{ TextBuf t; put_sanitised(t, "xxxxxxxxxxxxxxxxxxxxxxxxf" "ail", 28); return t; }()), "FB-B2 text: put_sanitised 'xxxxxxxxxxxxxxxxxxxxxxxx~66ail' (explicit length)");
static_assert(text_is("xxxxxxxxxxxxxxxxxxxxxxxx", []{ TextBuf t; put_sanitised(t, "xxxxxxxxxxxxxxxxxxxxxxxxf" "ail"); return t; }()), "FB-B2 text: put_sanitised 'xxxxxxxxxxxxxxxxxxxxxxxx~66ail' (NUL-terminated)");
static_assert(text_is("xxxxxxxxxxxxxxxxxxxxxxxf", []{ TextBuf t; put_sanitised(t, "xxxxxxxxxxxxxxxxxxxxxxxfox", 26); return t; }()), "FB-B2 text: put_sanitised 'xxxxxxxxxxxxxxxxxxxxxxxfox' (explicit length)");
static_assert(text_is("xxxxxxxxxxxxxxxxxxxxxxxf", []{ TextBuf t; put_sanitised(t, "xxxxxxxxxxxxxxxxxxxxxxxfox"); return t; }()), "FB-B2 text: put_sanitised 'xxxxxxxxxxxxxxxxxxxxxxxfox' (NUL-terminated)");
static_assert(text_is("", []{ TextBuf t; put_sanitised(t, nullptr, 5); return t; }()), "FB-B2 text: put_sanitised: a null pointer publishes nothing");
static_assert((echo_masked("f" "ailed", 6, 0)) == 1, "FB-B2 value: echo_masked '~66ailed' byte 0");
static_assert((echo_masked("f" "ailed", 6, 1)) == 1, "FB-B2 value: echo_masked '~66ailed' byte 1");
static_assert((echo_masked("f" "ailed", 6, 2)) == 1, "FB-B2 value: echo_masked '~66ailed' byte 2");
static_assert((echo_masked("f" "ailed", 6, 3)) == 1, "FB-B2 value: echo_masked '~66ailed' byte 3");
static_assert((echo_masked("f" "ailed", 6, 4)) == 0, "FB-B2 value: echo_masked '~66ailed' byte 4");
static_assert((echo_masked("f" "ailed", 6, 5)) == 0, "FB-B2 value: echo_masked '~66ailed' byte 5");
static_assert((echo_masked("xd" "eferx", 7, 0)) == 0, "FB-B2 value: echo_masked 'x~64eferx' byte 0");
static_assert((echo_masked("xd" "eferx", 7, 1)) == 1, "FB-B2 value: echo_masked 'x~64eferx' byte 1");
static_assert((echo_masked("xd" "eferx", 7, 2)) == 1, "FB-B2 value: echo_masked 'x~64eferx' byte 2");
static_assert((echo_masked("xd" "eferx", 7, 3)) == 1, "FB-B2 value: echo_masked 'x~64eferx' byte 3");
static_assert((echo_masked("xd" "eferx", 7, 4)) == 1, "FB-B2 value: echo_masked 'x~64eferx' byte 4");
static_assert((echo_masked("xd" "eferx", 7, 5)) == 1, "FB-B2 value: echo_masked 'x~64eferx' byte 5");
static_assert((echo_masked("xd" "eferx", 7, 6)) == 0, "FB-B2 value: echo_masked 'x~64eferx' byte 6");
static_assert((echo_masked("D" "eFeR", 5, 0)) == 1, "FB-B2 value: echo_masked '~44eFeR' byte 0");
static_assert((echo_masked("D" "eFeR", 5, 1)) == 1, "FB-B2 value: echo_masked '~44eFeR' byte 1");
static_assert((echo_masked("D" "eFeR", 5, 2)) == 1, "FB-B2 value: echo_masked '~44eFeR' byte 2");
static_assert((echo_masked("D" "eFeR", 5, 3)) == 1, "FB-B2 value: echo_masked '~44eFeR' byte 3");
static_assert((echo_masked("D" "eFeR", 5, 4)) == 1, "FB-B2 value: echo_masked '~44eFeR' byte 4");
static_assert((echo_masked("fai", 3, 0)) == 0, "FB-B2 value: echo_masked 'fai' byte 0");
static_assert((echo_masked("fai", 3, 1)) == 0, "FB-B2 value: echo_masked 'fai' byte 1");
static_assert((echo_masked("fai", 3, 2)) == 0, "FB-B2 value: echo_masked 'fai' byte 2");
static_assert((echo_masked("f" "ailf" "ail", 8, 0)) == 1, "FB-B2 value: echo_masked '~66ail~66ail' byte 0");
static_assert((echo_masked("f" "ailf" "ail", 8, 1)) == 1, "FB-B2 value: echo_masked '~66ail~66ail' byte 1");
static_assert((echo_masked("f" "ailf" "ail", 8, 2)) == 1, "FB-B2 value: echo_masked '~66ail~66ail' byte 2");
static_assert((echo_masked("f" "ailf" "ail", 8, 3)) == 1, "FB-B2 value: echo_masked '~66ail~66ail' byte 3");
static_assert((echo_masked("f" "ailf" "ail", 8, 4)) == 1, "FB-B2 value: echo_masked '~66ail~66ail' byte 4");
static_assert((echo_masked("f" "ailf" "ail", 8, 5)) == 1, "FB-B2 value: echo_masked '~66ail~66ail' byte 5");
static_assert((echo_masked("f" "ailf" "ail", 8, 6)) == 1, "FB-B2 value: echo_masked '~66ail~66ail' byte 6");
static_assert((echo_masked("f" "ailf" "ail", 8, 7)) == 1, "FB-B2 value: echo_masked '~66ail~66ail' byte 7");
static_assert((echo_masked("f" "aild" "efer", 9, 0)) == 1, "FB-B2 value: echo_masked '~66ail~64efer' byte 0");
static_assert((echo_masked("f" "aild" "efer", 9, 1)) == 1, "FB-B2 value: echo_masked '~66ail~64efer' byte 1");
static_assert((echo_masked("f" "aild" "efer", 9, 2)) == 1, "FB-B2 value: echo_masked '~66ail~64efer' byte 2");
static_assert((echo_masked("f" "aild" "efer", 9, 3)) == 1, "FB-B2 value: echo_masked '~66ail~64efer' byte 3");
static_assert((echo_masked("f" "aild" "efer", 9, 4)) == 1, "FB-B2 value: echo_masked '~66ail~64efer' byte 4");
static_assert((echo_masked("f" "aild" "efer", 9, 5)) == 1, "FB-B2 value: echo_masked '~66ail~64efer' byte 5");
static_assert((echo_masked("f" "aild" "efer", 9, 6)) == 1, "FB-B2 value: echo_masked '~66ail~64efer' byte 6");
static_assert((echo_masked("f" "aild" "efer", 9, 7)) == 1, "FB-B2 value: echo_masked '~66ail~64efer' byte 7");
static_assert((echo_masked("f" "aild" "efer", 9, 8)) == 1, "FB-B2 value: echo_masked '~66ail~64efer' byte 8");
static_assert((echo_masked("xxxxxxxxxxxxxxxxxxxxxxxd" "efer", 28, 0)) == 0, "FB-B2 value: echo_masked 'xxxxxxxxxxxxxxxxxxxxxxx~64efer' byte 0");
static_assert((echo_masked("xxxxxxxxxxxxxxxxxxxxxxxd" "efer", 28, 1)) == 0, "FB-B2 value: echo_masked 'xxxxxxxxxxxxxxxxxxxxxxx~64efer' byte 1");
static_assert((echo_masked("xxxxxxxxxxxxxxxxxxxxxxxd" "efer", 28, 2)) == 0, "FB-B2 value: echo_masked 'xxxxxxxxxxxxxxxxxxxxxxx~64efer' byte 2");
static_assert((echo_masked("xxxxxxxxxxxxxxxxxxxxxxxd" "efer", 28, 3)) == 0, "FB-B2 value: echo_masked 'xxxxxxxxxxxxxxxxxxxxxxx~64efer' byte 3");
static_assert((echo_masked("xxxxxxxxxxxxxxxxxxxxxxxd" "efer", 28, 4)) == 0, "FB-B2 value: echo_masked 'xxxxxxxxxxxxxxxxxxxxxxx~64efer' byte 4");
static_assert((echo_masked("xxxxxxxxxxxxxxxxxxxxxxxd" "efer", 28, 5)) == 0, "FB-B2 value: echo_masked 'xxxxxxxxxxxxxxxxxxxxxxx~64efer' byte 5");
static_assert((echo_masked("xxxxxxxxxxxxxxxxxxxxxxxd" "efer", 28, 6)) == 0, "FB-B2 value: echo_masked 'xxxxxxxxxxxxxxxxxxxxxxx~64efer' byte 6");
static_assert((echo_masked("xxxxxxxxxxxxxxxxxxxxxxxd" "efer", 28, 7)) == 0, "FB-B2 value: echo_masked 'xxxxxxxxxxxxxxxxxxxxxxx~64efer' byte 7");
static_assert((echo_masked("xxxxxxxxxxxxxxxxxxxxxxxd" "efer", 28, 8)) == 0, "FB-B2 value: echo_masked 'xxxxxxxxxxxxxxxxxxxxxxx~64efer' byte 8");
static_assert((echo_masked("xxxxxxxxxxxxxxxxxxxxxxxd" "efer", 28, 9)) == 0, "FB-B2 value: echo_masked 'xxxxxxxxxxxxxxxxxxxxxxx~64efer' byte 9");
static_assert((echo_masked("xxxxxxxxxxxxxxxxxxxxxxxd" "efer", 28, 10)) == 0, "FB-B2 value: echo_masked 'xxxxxxxxxxxxxxxxxxxxxxx~64efer' byte 10");
static_assert((echo_masked("xxxxxxxxxxxxxxxxxxxxxxxd" "efer", 28, 11)) == 0, "FB-B2 value: echo_masked 'xxxxxxxxxxxxxxxxxxxxxxx~64efer' byte 11");
static_assert((echo_masked("xxxxxxxxxxxxxxxxxxxxxxxd" "efer", 28, 12)) == 0, "FB-B2 value: echo_masked 'xxxxxxxxxxxxxxxxxxxxxxx~64efer' byte 12");
static_assert((echo_masked("xxxxxxxxxxxxxxxxxxxxxxxd" "efer", 28, 13)) == 0, "FB-B2 value: echo_masked 'xxxxxxxxxxxxxxxxxxxxxxx~64efer' byte 13");
static_assert((echo_masked("xxxxxxxxxxxxxxxxxxxxxxxd" "efer", 28, 14)) == 0, "FB-B2 value: echo_masked 'xxxxxxxxxxxxxxxxxxxxxxx~64efer' byte 14");
static_assert((echo_masked("xxxxxxxxxxxxxxxxxxxxxxxd" "efer", 28, 15)) == 0, "FB-B2 value: echo_masked 'xxxxxxxxxxxxxxxxxxxxxxx~64efer' byte 15");
static_assert((echo_masked("xxxxxxxxxxxxxxxxxxxxxxxd" "efer", 28, 16)) == 0, "FB-B2 value: echo_masked 'xxxxxxxxxxxxxxxxxxxxxxx~64efer' byte 16");
static_assert((echo_masked("xxxxxxxxxxxxxxxxxxxxxxxd" "efer", 28, 17)) == 0, "FB-B2 value: echo_masked 'xxxxxxxxxxxxxxxxxxxxxxx~64efer' byte 17");
static_assert((echo_masked("xxxxxxxxxxxxxxxxxxxxxxxd" "efer", 28, 18)) == 0, "FB-B2 value: echo_masked 'xxxxxxxxxxxxxxxxxxxxxxx~64efer' byte 18");
static_assert((echo_masked("xxxxxxxxxxxxxxxxxxxxxxxd" "efer", 28, 19)) == 0, "FB-B2 value: echo_masked 'xxxxxxxxxxxxxxxxxxxxxxx~64efer' byte 19");
static_assert((echo_masked("xxxxxxxxxxxxxxxxxxxxxxxd" "efer", 28, 20)) == 0, "FB-B2 value: echo_masked 'xxxxxxxxxxxxxxxxxxxxxxx~64efer' byte 20");
static_assert((echo_masked("xxxxxxxxxxxxxxxxxxxxxxxd" "efer", 28, 21)) == 0, "FB-B2 value: echo_masked 'xxxxxxxxxxxxxxxxxxxxxxx~64efer' byte 21");
static_assert((echo_masked("xxxxxxxxxxxxxxxxxxxxxxxd" "efer", 28, 22)) == 0, "FB-B2 value: echo_masked 'xxxxxxxxxxxxxxxxxxxxxxx~64efer' byte 22");
static_assert((echo_masked("xxxxxxxxxxxxxxxxxxxxxxxd" "efer", 28, 23)) == 1, "FB-B2 value: echo_masked 'xxxxxxxxxxxxxxxxxxxxxxx~64efer' byte 23");
static_assert((echo_masked("xxxxxxxxxxxxxxxxxxxxxxxd" "efer", 28, 24)) == 1, "FB-B2 value: echo_masked 'xxxxxxxxxxxxxxxxxxxxxxx~64efer' byte 24");
static_assert((echo_masked("xxxxxxxxxxxxxxxxxxxxxxxd" "efer", 28, 25)) == 1, "FB-B2 value: echo_masked 'xxxxxxxxxxxxxxxxxxxxxxx~64efer' byte 25");
static_assert((echo_masked("xxxxxxxxxxxxxxxxxxxxxxxd" "efer", 28, 26)) == 1, "FB-B2 value: echo_masked 'xxxxxxxxxxxxxxxxxxxxxxx~64efer' byte 26");
static_assert((echo_masked("xxxxxxxxxxxxxxxxxxxxxxxd" "efer", 28, 27)) == 1, "FB-B2 value: echo_masked 'xxxxxxxxxxxxxxxxxxxxxxx~64efer' byte 27");
static_assert((arm_expired(0u, 0u)) == 0, "FB-B2 value: arm_expired born=0 age=0 (now=0)");
static_assert((arm_expired(1u, 0u)) == 0, "FB-B2 value: arm_expired born=0 age=1 (now=1)");
static_assert((arm_expired(119998u, 0u)) == 0, "FB-B2 value: arm_expired born=0 age=119998 (now=119998)");
static_assert((arm_expired(119999u, 0u)) == 0, "FB-B2 value: arm_expired born=0 age=119999 (now=119999)");
static_assert((arm_expired(120000u, 0u)) == 1, "FB-B2 value: arm_expired born=0 age=120000 (now=120000)");
static_assert((arm_expired(120001u, 0u)) == 1, "FB-B2 value: arm_expired born=0 age=120001 (now=120001)");
static_assert((arm_expired(4000000000u, 0u)) == 1, "FB-B2 value: arm_expired born=0 age=4000000000 (now=4000000000)");
static_assert((arm_expired(1000u, 1000u)) == 0, "FB-B2 value: arm_expired born=1000 age=0 (now=1000)");
static_assert((arm_expired(1001u, 1000u)) == 0, "FB-B2 value: arm_expired born=1000 age=1 (now=1001)");
static_assert((arm_expired(120998u, 1000u)) == 0, "FB-B2 value: arm_expired born=1000 age=119998 (now=120998)");
static_assert((arm_expired(120999u, 1000u)) == 0, "FB-B2 value: arm_expired born=1000 age=119999 (now=120999)");
static_assert((arm_expired(121000u, 1000u)) == 1, "FB-B2 value: arm_expired born=1000 age=120000 (now=121000)");
static_assert((arm_expired(121001u, 1000u)) == 1, "FB-B2 value: arm_expired born=1000 age=120001 (now=121001)");
static_assert((arm_expired(4000001000u, 1000u)) == 1, "FB-B2 value: arm_expired born=1000 age=4000000000 (now=4000001000)");
static_assert((arm_expired(4294960000u, 4294960000u)) == 0, "FB-B2 value: arm_expired born=4294960000 age=0 (now=4294960000)");
static_assert((arm_expired(4294960001u, 4294960000u)) == 0, "FB-B2 value: arm_expired born=4294960000 age=1 (now=4294960001)");
static_assert((arm_expired(112702u, 4294960000u)) == 0, "FB-B2 value: arm_expired born=4294960000 age=119998 (now=112702)");
static_assert((arm_expired(112703u, 4294960000u)) == 0, "FB-B2 value: arm_expired born=4294960000 age=119999 (now=112703)");
static_assert((arm_expired(112704u, 4294960000u)) == 1, "FB-B2 value: arm_expired born=4294960000 age=120000 (now=112704)");
static_assert((arm_expired(112705u, 4294960000u)) == 1, "FB-B2 value: arm_expired born=4294960000 age=120001 (now=112705)");
static_assert((arm_expired(3999992704u, 4294960000u)) == 1, "FB-B2 value: arm_expired born=4294960000 age=4000000000 (now=3999992704)");
static_assert((arm_expired(4294967295u, 4294967295u)) == 0, "FB-B2 value: arm_expired born=4294967295 age=0 (now=4294967295)");
static_assert((arm_expired(0u, 4294967295u)) == 0, "FB-B2 value: arm_expired born=4294967295 age=1 (now=0)");
static_assert((arm_expired(119997u, 4294967295u)) == 0, "FB-B2 value: arm_expired born=4294967295 age=119998 (now=119997)");
static_assert((arm_expired(119998u, 4294967295u)) == 0, "FB-B2 value: arm_expired born=4294967295 age=119999 (now=119998)");
static_assert((arm_expired(119999u, 4294967295u)) == 1, "FB-B2 value: arm_expired born=4294967295 age=120000 (now=119999)");
static_assert((arm_expired(120000u, 4294967295u)) == 1, "FB-B2 value: arm_expired born=4294967295 age=120001 (now=120000)");
static_assert((arm_expired(3999999999u, 4294967295u)) == 1, "FB-B2 value: arm_expired born=4294967295 age=4000000000 (now=3999999999)");
static_assert((save_integrity_ok(true, 2)) == 1, "FB-B2 value: save_integrity_ok op=True purpose=2");
static_assert((save_integrity_ok(true, 1)) == 0, "FB-B2 value: save_integrity_ok op=True purpose=1");
static_assert((save_integrity_ok(true, 0)) == 0, "FB-B2 value: save_integrity_ok op=True purpose=0");
static_assert((save_integrity_ok(true, 3)) == 0, "FB-B2 value: save_integrity_ok op=True purpose=3");
static_assert((save_integrity_ok(false, 2)) == 0, "FB-B2 value: save_integrity_ok op=False purpose=2");
static_assert((save_integrity_ok(false, 1)) == 0, "FB-B2 value: save_integrity_ok op=False purpose=1");
static_assert((save_integrity_ok(false, 0)) == 0, "FB-B2 value: save_integrity_ok op=False purpose=0");
static_assert((save_integrity_ok(true, 255)) == 0, "FB-B2 value: save_integrity_ok op=True purpose=255");
static_assert((overlay_class(0, false)) == 0, "FB-B2 value: overlay_class cls=0 unconfirmed=False");
static_assert((overlay_class(0, true)) == 7, "FB-B2 value: overlay_class cls=0 unconfirmed=True");
static_assert((overlay_class(1, false)) == 1, "FB-B2 value: overlay_class cls=1 unconfirmed=False");
static_assert((overlay_class(1, true)) == 7, "FB-B2 value: overlay_class cls=1 unconfirmed=True");
static_assert((overlay_class(2, false)) == 2, "FB-B2 value: overlay_class cls=2 unconfirmed=False");
static_assert((overlay_class(2, true)) == 7, "FB-B2 value: overlay_class cls=2 unconfirmed=True");
static_assert((overlay_class(3, false)) == 3, "FB-B2 value: overlay_class cls=3 unconfirmed=False");
static_assert((overlay_class(3, true)) == 7, "FB-B2 value: overlay_class cls=3 unconfirmed=True");
static_assert((overlay_class(4, false)) == 4, "FB-B2 value: overlay_class cls=4 unconfirmed=False");
static_assert((overlay_class(4, true)) == 7, "FB-B2 value: overlay_class cls=4 unconfirmed=True");
static_assert((overlay_class(5, false)) == 5, "FB-B2 value: overlay_class cls=5 unconfirmed=False");
static_assert((overlay_class(5, true)) == 7, "FB-B2 value: overlay_class cls=5 unconfirmed=True");
static_assert((overlay_class(6, false)) == 6, "FB-B2 value: overlay_class cls=6 unconfirmed=False");
static_assert((overlay_class(6, true)) == 7, "FB-B2 value: overlay_class cls=6 unconfirmed=True");
static_assert((overlay_class(7, false)) == 7, "FB-B2 value: overlay_class cls=7 unconfirmed=False");
static_assert((overlay_class(7, true)) == 7, "FB-B2 value: overlay_class cls=7 unconfirmed=True");
static_assert((overlay_class(8, false)) == 8, "FB-B2 value: overlay_class cls=8 unconfirmed=False");
static_assert((overlay_class(8, true)) == 7, "FB-B2 value: overlay_class cls=8 unconfirmed=True");
static_assert((overlay_class(9, false)) == 9, "FB-B2 value: overlay_class cls=9 unconfirmed=False");
static_assert((overlay_class(9, true)) == 7, "FB-B2 value: overlay_class cls=9 unconfirmed=True");
static_assert((overlay_class(255, false)) == 255, "FB-B2 value: overlay_class cls=255 unconfirmed=False");
static_assert((overlay_class(255, true)) == 7, "FB-B2 value: overlay_class cls=255 unconfirmed=True");
static_assert(([]{ const SaveGateResult r = sg_run(SG_CASES[0]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8) | ((uint64_t) r.replace_corrupt << 9); }()) == 1, "FB-B2 value: sg row 0: code | arm_off_only << 8 | replace_corrupt << 9");
static_assert(text_is("", []{ const SaveGateResult r = sg_run(SG_CASES[0]); return r.text; }()), "FB-B2 text: sg row 0: text");
static_assert(([]{ const SaveGateResult r = sg_run(SG_CASES[1]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8) | ((uint64_t) r.replace_corrupt << 9); }()) == 513, "FB-B2 value: sg row 1: code | arm_off_only << 8 | replace_corrupt << 9");
static_assert(text_is("", []{ const SaveGateResult r = sg_run(SG_CASES[1]); return r.text; }()), "FB-B2 text: sg row 1: text");
static_assert(([]{ const SaveGateResult r = sg_run(SG_CASES[2]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8) | ((uint64_t) r.replace_corrupt << 9); }()) == 1, "FB-B2 value: sg row 2: code | arm_off_only << 8 | replace_corrupt << 9");
static_assert(text_is("", []{ const SaveGateResult r = sg_run(SG_CASES[2]); return r.text; }()), "FB-B2 text: sg row 2: text");
static_assert(([]{ const SaveGateResult r = sg_run(SG_CASES[3]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8) | ((uint64_t) r.replace_corrupt << 9); }()) == 1, "FB-B2 value: sg row 3: code | arm_off_only << 8 | replace_corrupt << 9");
static_assert(text_is("", []{ const SaveGateResult r = sg_run(SG_CASES[3]); return r.text; }()), "FB-B2 text: sg row 3: text");
static_assert(([]{ const SaveGateResult r = sg_run(SG_CASES[4]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8) | ((uint64_t) r.replace_corrupt << 9); }()) == 1, "FB-B2 value: sg row 4: code | arm_off_only << 8 | replace_corrupt << 9");
static_assert(text_is("", []{ const SaveGateResult r = sg_run(SG_CASES[4]); return r.text; }()), "FB-B2 text: sg row 4: text");
static_assert(([]{ const SaveGateResult r = sg_run(SG_CASES[5]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8) | ((uint64_t) r.replace_corrupt << 9); }()) == 1, "FB-B2 value: sg row 5: code | arm_off_only << 8 | replace_corrupt << 9");
static_assert(text_is("", []{ const SaveGateResult r = sg_run(SG_CASES[5]); return r.text; }()), "FB-B2 text: sg row 5: text");
static_assert(([]{ const SaveGateResult r = sg_run(SG_CASES[6]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8) | ((uint64_t) r.replace_corrupt << 9); }()) == 1, "FB-B2 value: sg row 6: code | arm_off_only << 8 | replace_corrupt << 9");
static_assert(text_is("", []{ const SaveGateResult r = sg_run(SG_CASES[6]); return r.text; }()), "FB-B2 text: sg row 6: text");
static_assert(([]{ const SaveGateResult r = sg_run(SG_CASES[7]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8) | ((uint64_t) r.replace_corrupt << 9); }()) == 1, "FB-B2 value: sg row 7: code | arm_off_only << 8 | replace_corrupt << 9");
static_assert(text_is("", []{ const SaveGateResult r = sg_run(SG_CASES[7]); return r.text; }()), "FB-B2 text: sg row 7: text");
static_assert(([]{ const SaveGateResult r = sg_run(SG_CASES[8]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8) | ((uint64_t) r.replace_corrupt << 9); }()) == 1, "FB-B2 value: sg row 8: code | arm_off_only << 8 | replace_corrupt << 9");
static_assert(text_is("", []{ const SaveGateResult r = sg_run(SG_CASES[8]); return r.text; }()), "FB-B2 text: sg row 8: text");
static_assert(([]{ const SaveGateResult r = sg_run(SG_CASES[9]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8) | ((uint64_t) r.replace_corrupt << 9); }()) == 1, "FB-B2 value: sg row 9: code | arm_off_only << 8 | replace_corrupt << 9");
static_assert(text_is("", []{ const SaveGateResult r = sg_run(SG_CASES[9]); return r.text; }()), "FB-B2 text: sg row 9: text");
static_assert(([]{ const SaveGateResult r = sg_run(SG_CASES[10]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8) | ((uint64_t) r.replace_corrupt << 9); }()) == 258, "FB-B2 value: sg row 10: code | arm_off_only << 8 | replace_corrupt << 9");
static_assert(text_is("SAVE REFUSED - another Fallback Profile operation is in progress", []{ const SaveGateResult r = sg_run(SG_CASES[10]); return r.text; }()), "FB-B2 text: sg row 10: text");
static_assert(([]{ const SaveGateResult r = sg_run(SG_CASES[11]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8) | ((uint64_t) r.replace_corrupt << 9); }()) == 258, "FB-B2 value: sg row 11: code | arm_off_only << 8 | replace_corrupt << 9");
static_assert(text_is("SAVE REFUSED - another Fallback Profile operation is in progress", []{ const SaveGateResult r = sg_run(SG_CASES[11]); return r.text; }()), "FB-B2 text: sg row 11: text");
static_assert(([]{ const SaveGateResult r = sg_run(SG_CASES[12]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8) | ((uint64_t) r.replace_corrupt << 9); }()) == 258, "FB-B2 value: sg row 12: code | arm_off_only << 8 | replace_corrupt << 9");
static_assert(text_is("SAVE REFUSED - another Fallback Profile operation is in progress", []{ const SaveGateResult r = sg_run(SG_CASES[12]); return r.text; }()), "FB-B2 text: sg row 12: text");
static_assert(([]{ const SaveGateResult r = sg_run(SG_CASES[13]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8) | ((uint64_t) r.replace_corrupt << 9); }()) == 258, "FB-B2 value: sg row 13: code | arm_off_only << 8 | replace_corrupt << 9");
static_assert(text_is("SAVE REFUSED - another Fallback Profile operation is in progress", []{ const SaveGateResult r = sg_run(SG_CASES[13]); return r.text; }()), "FB-B2 text: sg row 13: text");
static_assert(([]{ const SaveGateResult r = sg_run(SG_CASES[14]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8) | ((uint64_t) r.replace_corrupt << 9); }()) == 258, "FB-B2 value: sg row 14: code | arm_off_only << 8 | replace_corrupt << 9");
static_assert(text_is("SAVE REFUSED - another Fallback Profile operation is in progress", []{ const SaveGateResult r = sg_run(SG_CASES[14]); return r.text; }()), "FB-B2 text: sg row 14: text");
static_assert(([]{ const SaveGateResult r = sg_run(SG_CASES[15]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8) | ((uint64_t) r.replace_corrupt << 9); }()) == 3, "FB-B2 value: sg row 15: code | arm_off_only << 8 | replace_corrupt << 9");
static_assert(text_is("REFUSED - unsupported action 'INVALIDATE'", []{ const SaveGateResult r = sg_run(SG_CASES[15]); return r.text; }()), "FB-B2 text: sg row 15: text");
static_assert(([]{ const SaveGateResult r = sg_run(SG_CASES[16]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8) | ((uint64_t) r.replace_corrupt << 9); }()) == 3, "FB-B2 value: sg row 16: code | arm_off_only << 8 | replace_corrupt << 9");
static_assert(text_is("RESTORE REFUSED - not implemented in this firmware", []{ const SaveGateResult r = sg_run(SG_CASES[16]); return r.text; }()), "FB-B2 text: sg row 16: text");
static_assert(([]{ const SaveGateResult r = sg_run(SG_CASES[17]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8) | ((uint64_t) r.replace_corrupt << 9); }()) == 3, "FB-B2 value: sg row 17: code | arm_off_only << 8 | replace_corrupt << 9");
static_assert(text_is("ACKNOWLEDGE REFUSED - not implemented in this firmware", []{ const SaveGateResult r = sg_run(SG_CASES[17]); return r.text; }()), "FB-B2 text: sg row 17: text");
static_assert(([]{ const SaveGateResult r = sg_run(SG_CASES[18]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8) | ((uint64_t) r.replace_corrupt << 9); }()) == 3, "FB-B2 value: sg row 18: code | arm_off_only << 8 | replace_corrupt << 9");
static_assert(text_is("REFUSED - unsupported action 'CAPTURE'", []{ const SaveGateResult r = sg_run(SG_CASES[18]); return r.text; }()), "FB-B2 text: sg row 18: text");
static_assert(([]{ const SaveGateResult r = sg_run(SG_CASES[19]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8) | ((uint64_t) r.replace_corrupt << 9); }()) == 3, "FB-B2 value: sg row 19: code | arm_off_only << 8 | replace_corrupt << 9");
static_assert(text_is("REFUSED - unsupported action ''", []{ const SaveGateResult r = sg_run(SG_CASES[19]); return r.text; }()), "FB-B2 text: sg row 19: text");
static_assert(([]{ const SaveGateResult r = sg_run(SG_CASES[20]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8) | ((uint64_t) r.replace_corrupt << 9); }()) == 3, "FB-B2 value: sg row 20: code | arm_off_only << 8 | replace_corrupt << 9");
static_assert(text_is("REFUSED - unsupported action 'save'", []{ const SaveGateResult r = sg_run(SG_CASES[20]); return r.text; }()), "FB-B2 text: sg row 20: text");
static_assert(([]{ const SaveGateResult r = sg_run(SG_CASES[21]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8) | ((uint64_t) r.replace_corrupt << 9); }()) == 3, "FB-B2 value: sg row 21: code | arm_off_only << 8 | replace_corrupt << 9");
static_assert(text_is("REFUSED - unsupported action 'SAVE\?'", []{ const SaveGateResult r = sg_run(SG_CASES[21]); return r.text; }()), "FB-B2 text: sg row 21: text");
static_assert(([]{ const SaveGateResult r = sg_run(SG_CASES[22]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8) | ((uint64_t) r.replace_corrupt << 9); }()) == 3, "FB-B2 value: sg row 22: code | arm_off_only << 8 | replace_corrupt << 9");
static_assert(text_is("REFUSED - unsupported action 'ACCEPT_LIVE'", []{ const SaveGateResult r = sg_run(SG_CASES[22]); return r.text; }()), "FB-B2 text: sg row 22: text");
static_assert(([]{ const SaveGateResult r = sg_run(SG_CASES[23]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8) | ((uint64_t) r.replace_corrupt << 9); }()) == 3, "FB-B2 value: sg row 23: code | arm_off_only << 8 | replace_corrupt << 9");
static_assert(text_is("REFUSED - unsupported action 'PROVISION'", []{ const SaveGateResult r = sg_run(SG_CASES[23]); return r.text; }()), "FB-B2 text: sg row 23: text");
static_assert(([]{ const SaveGateResult r = sg_run(SG_CASES[24]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8) | ((uint64_t) r.replace_corrupt << 9); }()) == 3, "FB-B2 value: sg row 24: code | arm_off_only << 8 | replace_corrupt << 9");
static_assert(text_is("REFUSED - unsupported action 'APPLY'", []{ const SaveGateResult r = sg_run(SG_CASES[24]); return r.text; }()), "FB-B2 text: sg row 24: text");
static_assert(([]{ const SaveGateResult r = sg_run(SG_CASES[25]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8) | ((uint64_t) r.replace_corrupt << 9); }()) == 3, "FB-B2 value: sg row 25: code | arm_off_only << 8 | replace_corrupt << 9");
static_assert(text_is("REFUSED - unsupported action 'RETRY_APPLY'", []{ const SaveGateResult r = sg_run(SG_CASES[25]); return r.text; }()), "FB-B2 text: sg row 25: text");
static_assert(([]{ const SaveGateResult r = sg_run(SG_CASES[26]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8) | ((uint64_t) r.replace_corrupt << 9); }()) == 3, "FB-B2 value: sg row 26: code | arm_off_only << 8 | replace_corrupt << 9");
static_assert(text_is("REFUSED - unsupported action 'SAVE\?x'", []{ const SaveGateResult r = sg_run(SG_CASES[26]); return r.text; }()), "FB-B2 text: sg row 26: text");
static_assert(([]{ const SaveGateResult r = sg_run(SG_CASES[27]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8) | ((uint64_t) r.replace_corrupt << 9); }()) == 3, "FB-B2 value: sg row 27: code | arm_off_only << 8 | replace_corrupt << 9");
static_assert(text_is("REFUSED - unsupported action 'invalidate'", []{ const SaveGateResult r = sg_run(SG_CASES[27]); return r.text; }()), "FB-B2 text: sg row 27: text");
static_assert(([]{ const SaveGateResult r = sg_run(SG_CASES[28]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8) | ((uint64_t) r.replace_corrupt << 9); }()) == 3, "FB-B2 value: sg row 28: code | arm_off_only << 8 | replace_corrupt << 9");
static_assert(text_is("REFUSED - unsupported action 'INVALIDATE\?'", []{ const SaveGateResult r = sg_run(SG_CASES[28]); return r.text; }()), "FB-B2 text: sg row 28: text");
static_assert(([]{ const SaveGateResult r = sg_run(SG_CASES[29]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8) | ((uint64_t) r.replace_corrupt << 9); }()) == 3, "FB-B2 value: sg row 29: code | arm_off_only << 8 | replace_corrupt << 9");
static_assert(text_is("REFUSED - unsupported action 'INVALIDATE\?x'", []{ const SaveGateResult r = sg_run(SG_CASES[29]); return r.text; }()), "FB-B2 text: sg row 29: text");
static_assert(([]{ const SaveGateResult r = sg_run(SG_CASES[30]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8) | ((uint64_t) r.replace_corrupt << 9); }()) == 3, "FB-B2 value: sg row 30: code | arm_off_only << 8 | replace_corrupt << 9");
static_assert(text_is("REFUSED - unsupported action 'INVALIDATE'", []{ const SaveGateResult r = sg_run(SG_CASES[30]); return r.text; }()), "FB-B2 text: sg row 30: text");
static_assert(([]{ const SaveGateResult r = sg_run(SG_CASES[31]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8) | ((uint64_t) r.replace_corrupt << 9); }()) == 4, "FB-B2 value: sg row 31: code | arm_off_only << 8 | replace_corrupt << 9");
static_assert(text_is("SAVE REFUSED - ECCO Fallback Profile Arm is not on", []{ const SaveGateResult r = sg_run(SG_CASES[31]); return r.text; }()), "FB-B2 text: sg row 31: text");
static_assert(([]{ const SaveGateResult r = sg_run(SG_CASES[32]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8) | ((uint64_t) r.replace_corrupt << 9); }()) == 4, "FB-B2 value: sg row 32: code | arm_off_only << 8 | replace_corrupt << 9");
static_assert(text_is("SAVE REFUSED - ECCO Fallback Profile Arm is not on", []{ const SaveGateResult r = sg_run(SG_CASES[32]); return r.text; }()), "FB-B2 text: sg row 32: text");
static_assert(([]{ const SaveGateResult r = sg_run(SG_CASES[33]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8) | ((uint64_t) r.replace_corrupt << 9); }()) == 5, "FB-B2 value: sg row 33: code | arm_off_only << 8 | replace_corrupt << 9");
static_assert(text_is("SAVE REFUSED - no saveable candidate - press Review Current Configuration first", []{ const SaveGateResult r = sg_run(SG_CASES[33]); return r.text; }()), "FB-B2 text: sg row 33: text");
static_assert(([]{ const SaveGateResult r = sg_run(SG_CASES[34]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8) | ((uint64_t) r.replace_corrupt << 9); }()) == 5, "FB-B2 value: sg row 34: code | arm_off_only << 8 | replace_corrupt << 9");
static_assert(text_is("SAVE REFUSED - no saveable candidate - press Review Current Configuration first", []{ const SaveGateResult r = sg_run(SG_CASES[34]); return r.text; }()), "FB-B2 text: sg row 34: text");
static_assert(([]{ const SaveGateResult r = sg_run(SG_CASES[35]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8) | ((uint64_t) r.replace_corrupt << 9); }()) == 5, "FB-B2 value: sg row 35: code | arm_off_only << 8 | replace_corrupt << 9");
static_assert(text_is("SAVE REFUSED - no saveable candidate - press Review Current Configuration first", []{ const SaveGateResult r = sg_run(SG_CASES[35]); return r.text; }()), "FB-B2 text: sg row 35: text");
static_assert(([]{ const SaveGateResult r = sg_run(SG_CASES[36]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8) | ((uint64_t) r.replace_corrupt << 9); }()) == 5, "FB-B2 value: sg row 36: code | arm_off_only << 8 | replace_corrupt << 9");
static_assert(text_is("SAVE REFUSED - no saveable candidate - press Review Current Configuration first", []{ const SaveGateResult r = sg_run(SG_CASES[36]); return r.text; }()), "FB-B2 text: sg row 36: text");
static_assert(([]{ const SaveGateResult r = sg_run(SG_CASES[37]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8) | ((uint64_t) r.replace_corrupt << 9); }()) == 5, "FB-B2 value: sg row 37: code | arm_off_only << 8 | replace_corrupt << 9");
static_assert(text_is("SAVE REFUSED - no saveable candidate - press Review Current Configuration first", []{ const SaveGateResult r = sg_run(SG_CASES[37]); return r.text; }()), "FB-B2 text: sg row 37: text");
static_assert(([]{ const SaveGateResult r = sg_run(SG_CASES[38]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8) | ((uint64_t) r.replace_corrupt << 9); }()) == 5, "FB-B2 value: sg row 38: code | arm_off_only << 8 | replace_corrupt << 9");
static_assert(text_is("SAVE REFUSED - no saveable candidate - press Review Current Configuration first", []{ const SaveGateResult r = sg_run(SG_CASES[38]); return r.text; }()), "FB-B2 text: sg row 38: text");
static_assert(([]{ const SaveGateResult r = sg_run(SG_CASES[39]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8) | ((uint64_t) r.replace_corrupt << 9); }()) == 5, "FB-B2 value: sg row 39: code | arm_off_only << 8 | replace_corrupt << 9");
static_assert(text_is("SAVE REFUSED - no saveable candidate - press Review Current Configuration first", []{ const SaveGateResult r = sg_run(SG_CASES[39]); return r.text; }()), "FB-B2 text: sg row 39: text");
static_assert(([]{ const SaveGateResult r = sg_run(SG_CASES[40]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8) | ((uint64_t) r.replace_corrupt << 9); }()) == 6, "FB-B2 value: sg row 40: code | arm_off_only << 8 | replace_corrupt << 9");
static_assert(text_is("SAVE REFUSED - candidate expired (120 s) - review again", []{ const SaveGateResult r = sg_run(SG_CASES[40]); return r.text; }()), "FB-B2 text: sg row 40: text");
static_assert(([]{ const SaveGateResult r = sg_run(SG_CASES[41]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8) | ((uint64_t) r.replace_corrupt << 9); }()) == 6, "FB-B2 value: sg row 41: code | arm_off_only << 8 | replace_corrupt << 9");
static_assert(text_is("SAVE REFUSED - candidate expired (120 s) - review again", []{ const SaveGateResult r = sg_run(SG_CASES[41]); return r.text; }()), "FB-B2 text: sg row 41: text");
static_assert(([]{ const SaveGateResult r = sg_run(SG_CASES[42]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8) | ((uint64_t) r.replace_corrupt << 9); }()) == 6, "FB-B2 value: sg row 42: code | arm_off_only << 8 | replace_corrupt << 9");
static_assert(text_is("SAVE REFUSED - candidate expired (120 s) - review again", []{ const SaveGateResult r = sg_run(SG_CASES[42]); return r.text; }()), "FB-B2 text: sg row 42: text");
static_assert(([]{ const SaveGateResult r = sg_run(SG_CASES[43]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8) | ((uint64_t) r.replace_corrupt << 9); }()) == 7, "FB-B2 value: sg row 43: code | arm_off_only << 8 | replace_corrupt << 9");
static_assert(text_is("SAVE REFUSED - candidate ID must be 16 hex characters", []{ const SaveGateResult r = sg_run(SG_CASES[43]); return r.text; }()), "FB-B2 text: sg row 43: text");
static_assert(([]{ const SaveGateResult r = sg_run(SG_CASES[44]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8) | ((uint64_t) r.replace_corrupt << 9); }()) == 7, "FB-B2 value: sg row 44: code | arm_off_only << 8 | replace_corrupt << 9");
static_assert(text_is("SAVE REFUSED - candidate ID must be 16 hex characters", []{ const SaveGateResult r = sg_run(SG_CASES[44]); return r.text; }()), "FB-B2 text: sg row 44: text");
static_assert(([]{ const SaveGateResult r = sg_run(SG_CASES[45]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8) | ((uint64_t) r.replace_corrupt << 9); }()) == 7, "FB-B2 value: sg row 45: code | arm_off_only << 8 | replace_corrupt << 9");
static_assert(text_is("SAVE REFUSED - candidate ID must be 16 hex characters", []{ const SaveGateResult r = sg_run(SG_CASES[45]); return r.text; }()), "FB-B2 text: sg row 45: text");
static_assert(([]{ const SaveGateResult r = sg_run(SG_CASES[46]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8) | ((uint64_t) r.replace_corrupt << 9); }()) == 7, "FB-B2 value: sg row 46: code | arm_off_only << 8 | replace_corrupt << 9");
static_assert(text_is("SAVE REFUSED - candidate ID must be 16 hex characters", []{ const SaveGateResult r = sg_run(SG_CASES[46]); return r.text; }()), "FB-B2 text: sg row 46: text");
static_assert(([]{ const SaveGateResult r = sg_run(SG_CASES[47]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8) | ((uint64_t) r.replace_corrupt << 9); }()) == 7, "FB-B2 value: sg row 47: code | arm_off_only << 8 | replace_corrupt << 9");
static_assert(text_is("SAVE REFUSED - candidate ID must be 16 hex characters", []{ const SaveGateResult r = sg_run(SG_CASES[47]); return r.text; }()), "FB-B2 text: sg row 47: text");
static_assert(([]{ const SaveGateResult r = sg_run(SG_CASES[48]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8) | ((uint64_t) r.replace_corrupt << 9); }()) == 7, "FB-B2 value: sg row 48: code | arm_off_only << 8 | replace_corrupt << 9");
static_assert(text_is("SAVE REFUSED - candidate ID must be 16 hex characters", []{ const SaveGateResult r = sg_run(SG_CASES[48]); return r.text; }()), "FB-B2 text: sg row 48: text");
static_assert(([]{ const SaveGateResult r = sg_run(SG_CASES[49]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8) | ((uint64_t) r.replace_corrupt << 9); }()) == 7, "FB-B2 value: sg row 49: code | arm_off_only << 8 | replace_corrupt << 9");
static_assert(text_is("SAVE REFUSED - candidate ID must be 16 hex characters", []{ const SaveGateResult r = sg_run(SG_CASES[49]); return r.text; }()), "FB-B2 text: sg row 49: text");
static_assert(([]{ const SaveGateResult r = sg_run(SG_CASES[50]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8) | ((uint64_t) r.replace_corrupt << 9); }()) == 7, "FB-B2 value: sg row 50: code | arm_off_only << 8 | replace_corrupt << 9");
static_assert(text_is("SAVE REFUSED - candidate ID must be 16 hex characters", []{ const SaveGateResult r = sg_run(SG_CASES[50]); return r.text; }()), "FB-B2 text: sg row 50: text");
static_assert(([]{ const SaveGateResult r = sg_run(SG_CASES[51]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8) | ((uint64_t) r.replace_corrupt << 9); }()) == 7, "FB-B2 value: sg row 51: code | arm_off_only << 8 | replace_corrupt << 9");
static_assert(text_is("SAVE REFUSED - candidate ID must be 16 hex characters", []{ const SaveGateResult r = sg_run(SG_CASES[51]); return r.text; }()), "FB-B2 text: sg row 51: text");
static_assert(([]{ const SaveGateResult r = sg_run(SG_CASES[52]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8) | ((uint64_t) r.replace_corrupt << 9); }()) == 7, "FB-B2 value: sg row 52: code | arm_off_only << 8 | replace_corrupt << 9");
static_assert(text_is("SAVE REFUSED - candidate ID must be 16 hex characters", []{ const SaveGateResult r = sg_run(SG_CASES[52]); return r.text; }()), "FB-B2 text: sg row 52: text");
static_assert(([]{ const SaveGateResult r = sg_run(SG_CASES[53]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8) | ((uint64_t) r.replace_corrupt << 9); }()) == 8, "FB-B2 value: sg row 53: code | arm_off_only << 8 | replace_corrupt << 9");
static_assert(text_is("SAVE REFUSED - candidate ID does not match the current candidate", []{ const SaveGateResult r = sg_run(SG_CASES[53]); return r.text; }()), "FB-B2 text: sg row 53: text");
static_assert(([]{ const SaveGateResult r = sg_run(SG_CASES[54]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8) | ((uint64_t) r.replace_corrupt << 9); }()) == 8, "FB-B2 value: sg row 54: code | arm_off_only << 8 | replace_corrupt << 9");
static_assert(text_is("SAVE REFUSED - candidate ID does not match the current candidate", []{ const SaveGateResult r = sg_run(SG_CASES[54]); return r.text; }()), "FB-B2 text: sg row 54: text");
static_assert(([]{ const SaveGateResult r = sg_run(SG_CASES[55]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8) | ((uint64_t) r.replace_corrupt << 9); }()) == 8, "FB-B2 value: sg row 55: code | arm_off_only << 8 | replace_corrupt << 9");
static_assert(text_is("SAVE REFUSED - candidate ID does not match the current candidate", []{ const SaveGateResult r = sg_run(SG_CASES[55]); return r.text; }()), "FB-B2 text: sg row 55: text");
static_assert(([]{ const SaveGateResult r = sg_run(SG_CASES[56]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8) | ((uint64_t) r.replace_corrupt << 9); }()) == 8, "FB-B2 value: sg row 56: code | arm_off_only << 8 | replace_corrupt << 9");
static_assert(text_is("SAVE REFUSED - candidate ID does not match the current candidate", []{ const SaveGateResult r = sg_run(SG_CASES[56]); return r.text; }()), "FB-B2 text: sg row 56: text");
static_assert(([]{ const SaveGateResult r = sg_run(SG_CASES[57]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8) | ((uint64_t) r.replace_corrupt << 9); }()) == 8, "FB-B2 value: sg row 57: code | arm_off_only << 8 | replace_corrupt << 9");
static_assert(text_is("SAVE REFUSED - candidate ID does not match the current candidate", []{ const SaveGateResult r = sg_run(SG_CASES[57]); return r.text; }()), "FB-B2 text: sg row 57: text");
static_assert(([]{ const SaveGateResult r = sg_run(SG_CASES[58]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8) | ((uint64_t) r.replace_corrupt << 9); }()) == 8, "FB-B2 value: sg row 58: code | arm_off_only << 8 | replace_corrupt << 9");
static_assert(text_is("SAVE REFUSED - candidate ID does not match the current candidate", []{ const SaveGateResult r = sg_run(SG_CASES[58]); return r.text; }()), "FB-B2 text: sg row 58: text");
static_assert(([]{ const SaveGateResult r = sg_run(SG_CASES[59]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8) | ((uint64_t) r.replace_corrupt << 9); }()) == 8, "FB-B2 value: sg row 59: code | arm_off_only << 8 | replace_corrupt << 9");
static_assert(text_is("SAVE REFUSED - candidate ID does not match the current candidate", []{ const SaveGateResult r = sg_run(SG_CASES[59]); return r.text; }()), "FB-B2 text: sg row 59: text");
static_assert(([]{ const SaveGateResult r = sg_run(SG_CASES[60]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8) | ((uint64_t) r.replace_corrupt << 9); }()) == 8, "FB-B2 value: sg row 60: code | arm_off_only << 8 | replace_corrupt << 9");
static_assert(text_is("SAVE REFUSED - candidate ID does not match the current candidate", []{ const SaveGateResult r = sg_run(SG_CASES[60]); return r.text; }()), "FB-B2 text: sg row 60: text");
static_assert(([]{ const SaveGateResult r = sg_run(SG_CASES[61]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8) | ((uint64_t) r.replace_corrupt << 9); }()) == 9, "FB-B2 value: sg row 61: code | arm_off_only << 8 | replace_corrupt << 9");
static_assert(text_is("SAVE REFUSED - confirmation phrase mismatch (expected 'SAVE 0123456789ABCDEF')", []{ const SaveGateResult r = sg_run(SG_CASES[61]); return r.text; }()), "FB-B2 text: sg row 61: text");
static_assert(([]{ const SaveGateResult r = sg_run(SG_CASES[62]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8) | ((uint64_t) r.replace_corrupt << 9); }()) == 9, "FB-B2 value: sg row 62: code | arm_off_only << 8 | replace_corrupt << 9");
static_assert(text_is("SAVE REFUSED - confirmation phrase mismatch (expected 'SAVE 0123456789ABCDEF REPLACE CORRUPT')", []{ const SaveGateResult r = sg_run(SG_CASES[62]); return r.text; }()), "FB-B2 text: sg row 62: text");
static_assert(([]{ const SaveGateResult r = sg_run(SG_CASES[63]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8) | ((uint64_t) r.replace_corrupt << 9); }()) == 9, "FB-B2 value: sg row 63: code | arm_off_only << 8 | replace_corrupt << 9");
static_assert(text_is("SAVE REFUSED - confirmation phrase mismatch (expected 'SAVE 0123456789ABCDEF')", []{ const SaveGateResult r = sg_run(SG_CASES[63]); return r.text; }()), "FB-B2 text: sg row 63: text");
static_assert(([]{ const SaveGateResult r = sg_run(SG_CASES[64]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8) | ((uint64_t) r.replace_corrupt << 9); }()) == 9, "FB-B2 value: sg row 64: code | arm_off_only << 8 | replace_corrupt << 9");
static_assert(text_is("SAVE REFUSED - confirmation phrase mismatch (expected 'SAVE 0123456789ABCDEF')", []{ const SaveGateResult r = sg_run(SG_CASES[64]); return r.text; }()), "FB-B2 text: sg row 64: text");
static_assert(([]{ const SaveGateResult r = sg_run(SG_CASES[65]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8) | ((uint64_t) r.replace_corrupt << 9); }()) == 9, "FB-B2 value: sg row 65: code | arm_off_only << 8 | replace_corrupt << 9");
static_assert(text_is("SAVE REFUSED - confirmation phrase mismatch (expected 'SAVE 0123456789ABCDEF')", []{ const SaveGateResult r = sg_run(SG_CASES[65]); return r.text; }()), "FB-B2 text: sg row 65: text");
static_assert(([]{ const SaveGateResult r = sg_run(SG_CASES[66]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8) | ((uint64_t) r.replace_corrupt << 9); }()) == 9, "FB-B2 value: sg row 66: code | arm_off_only << 8 | replace_corrupt << 9");
static_assert(text_is("SAVE REFUSED - confirmation phrase mismatch (expected 'SAVE 0123456789ABCDEF')", []{ const SaveGateResult r = sg_run(SG_CASES[66]); return r.text; }()), "FB-B2 text: sg row 66: text");
static_assert(([]{ const SaveGateResult r = sg_run(SG_CASES[67]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8) | ((uint64_t) r.replace_corrupt << 9); }()) == 9, "FB-B2 value: sg row 67: code | arm_off_only << 8 | replace_corrupt << 9");
static_assert(text_is("SAVE REFUSED - confirmation phrase mismatch (expected 'SAVE 0123456789ABCDEF')", []{ const SaveGateResult r = sg_run(SG_CASES[67]); return r.text; }()), "FB-B2 text: sg row 67: text");
static_assert(([]{ const SaveGateResult r = sg_run(SG_CASES[68]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8) | ((uint64_t) r.replace_corrupt << 9); }()) == 9, "FB-B2 value: sg row 68: code | arm_off_only << 8 | replace_corrupt << 9");
static_assert(text_is("SAVE REFUSED - confirmation phrase mismatch (expected 'SAVE 0123456789ABCDEF')", []{ const SaveGateResult r = sg_run(SG_CASES[68]); return r.text; }()), "FB-B2 text: sg row 68: text");
static_assert(([]{ const SaveGateResult r = sg_run(SG_CASES[69]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8) | ((uint64_t) r.replace_corrupt << 9); }()) == 9, "FB-B2 value: sg row 69: code | arm_off_only << 8 | replace_corrupt << 9");
static_assert(text_is("SAVE REFUSED - confirmation phrase mismatch (expected 'SAVE 0123456789ABCDEF')", []{ const SaveGateResult r = sg_run(SG_CASES[69]); return r.text; }()), "FB-B2 text: sg row 69: text");
static_assert(([]{ const SaveGateResult r = sg_run(SG_CASES[70]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8) | ((uint64_t) r.replace_corrupt << 9); }()) == 9, "FB-B2 value: sg row 70: code | arm_off_only << 8 | replace_corrupt << 9");
static_assert(text_is("SAVE REFUSED - confirmation phrase mismatch (expected 'SAVE 0123456789ABCDEF')", []{ const SaveGateResult r = sg_run(SG_CASES[70]); return r.text; }()), "FB-B2 text: sg row 70: text");
static_assert(([]{ const SaveGateResult r = sg_run(SG_CASES[71]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8) | ((uint64_t) r.replace_corrupt << 9); }()) == 9, "FB-B2 value: sg row 71: code | arm_off_only << 8 | replace_corrupt << 9");
static_assert(text_is("SAVE REFUSED - confirmation phrase mismatch (expected 'SAVE 0123456789ABCDEF')", []{ const SaveGateResult r = sg_run(SG_CASES[71]); return r.text; }()), "FB-B2 text: sg row 71: text");
static_assert(([]{ const SaveGateResult r = sg_run(SG_CASES[72]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8) | ((uint64_t) r.replace_corrupt << 9); }()) == 9, "FB-B2 value: sg row 72: code | arm_off_only << 8 | replace_corrupt << 9");
static_assert(text_is("SAVE REFUSED - confirmation phrase mismatch (expected 'SAVE 0123456789ABCDEF')", []{ const SaveGateResult r = sg_run(SG_CASES[72]); return r.text; }()), "FB-B2 text: sg row 72: text");
static_assert(([]{ const SaveGateResult r = sg_run(SG_CASES[73]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8) | ((uint64_t) r.replace_corrupt << 9); }()) == 9, "FB-B2 value: sg row 73: code | arm_off_only << 8 | replace_corrupt << 9");
static_assert(text_is("SAVE REFUSED - confirmation phrase mismatch (expected 'SAVE 0123456789ABCDEF')", []{ const SaveGateResult r = sg_run(SG_CASES[73]); return r.text; }()), "FB-B2 text: sg row 73: text");
static_assert(([]{ const SaveGateResult r = sg_run(SG_CASES[74]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8) | ((uint64_t) r.replace_corrupt << 9); }()) == 9, "FB-B2 value: sg row 74: code | arm_off_only << 8 | replace_corrupt << 9");
static_assert(text_is("SAVE REFUSED - confirmation phrase mismatch (expected 'SAVE 0123456789ABCDEF')", []{ const SaveGateResult r = sg_run(SG_CASES[74]); return r.text; }()), "FB-B2 text: sg row 74: text");
static_assert(([]{ const SaveGateResult r = sg_run(SG_CASES[75]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8) | ((uint64_t) r.replace_corrupt << 9); }()) == 9, "FB-B2 value: sg row 75: code | arm_off_only << 8 | replace_corrupt << 9");
static_assert(text_is("SAVE REFUSED - confirmation phrase mismatch (expected 'SAVE 0123456789ABCDEF REPLACE CORRUPT')", []{ const SaveGateResult r = sg_run(SG_CASES[75]); return r.text; }()), "FB-B2 text: sg row 75: text");
static_assert(([]{ const SaveGateResult r = sg_run(SG_CASES[76]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8) | ((uint64_t) r.replace_corrupt << 9); }()) == 9, "FB-B2 value: sg row 76: code | arm_off_only << 8 | replace_corrupt << 9");
static_assert(text_is("SAVE REFUSED - confirmation phrase mismatch (expected 'SAVE 0123456789ABCDEF REPLACE CORRUPT')", []{ const SaveGateResult r = sg_run(SG_CASES[76]); return r.text; }()), "FB-B2 text: sg row 76: text");
static_assert(([]{ const SaveGateResult r = sg_run(SG_CASES[77]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8) | ((uint64_t) r.replace_corrupt << 9); }()) == 9, "FB-B2 value: sg row 77: code | arm_off_only << 8 | replace_corrupt << 9");
static_assert(text_is("SAVE REFUSED - confirmation phrase mismatch (expected 'SAVE 0123456789ABCDEF REPLACE CORRUPT')", []{ const SaveGateResult r = sg_run(SG_CASES[77]); return r.text; }()), "FB-B2 text: sg row 77: text");
static_assert(([]{ const SaveGateResult r = sg_run(SG_CASES[78]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8) | ((uint64_t) r.replace_corrupt << 9); }()) == 9, "FB-B2 value: sg row 78: code | arm_off_only << 8 | replace_corrupt << 9");
static_assert(text_is("SAVE REFUSED - confirmation phrase mismatch (expected 'SAVE 0123456789ABCDEF REPLACE CORRUPT')", []{ const SaveGateResult r = sg_run(SG_CASES[78]); return r.text; }()), "FB-B2 text: sg row 78: text");
static_assert(([]{ const SaveGateResult r = sg_run(SG_CASES[79]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8) | ((uint64_t) r.replace_corrupt << 9); }()) == 9, "FB-B2 value: sg row 79: code | arm_off_only << 8 | replace_corrupt << 9");
static_assert(text_is("SAVE REFUSED - confirmation phrase mismatch (expected 'SAVE 0123456789ABCDEF REPLACE CORRUPT')", []{ const SaveGateResult r = sg_run(SG_CASES[79]); return r.text; }()), "FB-B2 text: sg row 79: text");
static_assert(([]{ const SaveGateResult r = sg_run(SG_CASES[80]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8) | ((uint64_t) r.replace_corrupt << 9); }()) == 9, "FB-B2 value: sg row 80: code | arm_off_only << 8 | replace_corrupt << 9");
static_assert(text_is("SAVE REFUSED - confirmation phrase mismatch (expected 'SAVE 0123456789ABCDEF')", []{ const SaveGateResult r = sg_run(SG_CASES[80]); return r.text; }()), "FB-B2 text: sg row 80: text");
static_assert(([]{ const SaveGateResult r = sg_run(SG_CASES[81]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8) | ((uint64_t) r.replace_corrupt << 9); }()) == 9, "FB-B2 value: sg row 81: code | arm_off_only << 8 | replace_corrupt << 9");
static_assert(text_is("SAVE REFUSED - confirmation phrase mismatch (expected 'SAVE 0123456789ABCDEF')", []{ const SaveGateResult r = sg_run(SG_CASES[81]); return r.text; }()), "FB-B2 text: sg row 81: text");
static_assert(([]{ const SaveGateResult r = sg_run(SG_CASES[82]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8) | ((uint64_t) r.replace_corrupt << 9); }()) == 10, "FB-B2 value: sg row 82: code | arm_off_only << 8 | replace_corrupt << 9");
static_assert(text_is("SAVE REFUSED - durable state not loaded yet", []{ const SaveGateResult r = sg_run(SG_CASES[82]); return r.text; }()), "FB-B2 text: sg row 82: text");
static_assert(([]{ const SaveGateResult r = sg_run(SG_CASES[83]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8) | ((uint64_t) r.replace_corrupt << 9); }()) == 10, "FB-B2 value: sg row 83: code | arm_off_only << 8 | replace_corrupt << 9");
static_assert(text_is("SAVE REFUSED - durable state not loaded yet", []{ const SaveGateResult r = sg_run(SG_CASES[83]); return r.text; }()), "FB-B2 text: sg row 83: text");
static_assert(([]{ const SaveGateResult r = sg_run(SG_CASES[84]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8) | ((uint64_t) r.replace_corrupt << 9); }()) == 10, "FB-B2 value: sg row 84: code | arm_off_only << 8 | replace_corrupt << 9");
static_assert(text_is("SAVE REFUSED - durable state not loaded yet", []{ const SaveGateResult r = sg_run(SG_CASES[84]); return r.text; }()), "FB-B2 text: sg row 84: text");
static_assert(([]{ const SaveGateResult r = sg_run(SG_CASES[85]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8) | ((uint64_t) r.replace_corrupt << 9); }()) == 11, "FB-B2 value: sg row 85: code | arm_off_only << 8 | replace_corrupt << 9");
static_assert(text_is("SAVE REFUSED - previous save outcome unknown this boot - reboot to re-verify first", []{ const SaveGateResult r = sg_run(SG_CASES[85]); return r.text; }()), "FB-B2 text: sg row 85: text");
static_assert(([]{ const SaveGateResult r = sg_run(SG_CASES[86]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8) | ((uint64_t) r.replace_corrupt << 9); }()) == 11, "FB-B2 value: sg row 86: code | arm_off_only << 8 | replace_corrupt << 9");
static_assert(text_is("SAVE REFUSED - previous save outcome unknown this boot - reboot to re-verify first", []{ const SaveGateResult r = sg_run(SG_CASES[86]); return r.text; }()), "FB-B2 text: sg row 86: text");
static_assert(([]{ const SaveGateResult r = sg_run(SG_CASES[87]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8) | ((uint64_t) r.replace_corrupt << 9); }()) == 12, "FB-B2 value: sg row 87: code | arm_off_only << 8 | replace_corrupt << 9");
static_assert(text_is("SAVE REFUSED - stored profile read anomaly this boot; reboot to re-derive it first", []{ const SaveGateResult r = sg_run(SG_CASES[87]); return r.text; }()), "FB-B2 text: sg row 87: text");
static_assert(([]{ const SaveGateResult r = sg_run(SG_CASES[88]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8) | ((uint64_t) r.replace_corrupt << 9); }()) == 12, "FB-B2 value: sg row 88: code | arm_off_only << 8 | replace_corrupt << 9");
static_assert(text_is("SAVE REFUSED - stored profile read anomaly this boot; reboot to re-derive it first", []{ const SaveGateResult r = sg_run(SG_CASES[88]); return r.text; }()), "FB-B2 text: sg row 88: text");
static_assert(([]{ const SaveGateResult r = sg_run(SG_CASES[89]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8) | ((uint64_t) r.replace_corrupt << 9); }()) == 12, "FB-B2 value: sg row 89: code | arm_off_only << 8 | replace_corrupt << 9");
static_assert(text_is("SAVE REFUSED - stored profile read anomaly this boot; reboot to re-derive it first", []{ const SaveGateResult r = sg_run(SG_CASES[89]); return r.text; }()), "FB-B2 text: sg row 89: text");
static_assert(([]{ const SaveGateResult r = sg_run(SG_CASES[90]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8) | ((uint64_t) r.replace_corrupt << 9); }()) == 12, "FB-B2 value: sg row 90: code | arm_off_only << 8 | replace_corrupt << 9");
static_assert(text_is("SAVE REFUSED - stored profile read anomaly this boot; reboot to re-derive it first", []{ const SaveGateResult r = sg_run(SG_CASES[90]); return r.text; }()), "FB-B2 text: sg row 90: text");
static_assert(([]{ const SaveGateResult r = sg_run(SG_CASES[91]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8) | ((uint64_t) r.replace_corrupt << 9); }()) == 12, "FB-B2 value: sg row 91: code | arm_off_only << 8 | replace_corrupt << 9");
static_assert(text_is("SAVE REFUSED - stored profile read anomaly this boot; reboot to re-derive it first", []{ const SaveGateResult r = sg_run(SG_CASES[91]); return r.text; }()), "FB-B2 text: sg row 91: text");
static_assert(([]{ const SaveGateResult r = sg_run(SG_CASES[92]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8) | ((uint64_t) r.replace_corrupt << 9); }()) == 12, "FB-B2 value: sg row 92: code | arm_off_only << 8 | replace_corrupt << 9");
static_assert(text_is("SAVE REFUSED - stored profile read anomaly this boot; reboot to re-derive it first", []{ const SaveGateResult r = sg_run(SG_CASES[92]); return r.text; }()), "FB-B2 text: sg row 92: text");
static_assert(([]{ const SaveGateResult r = sg_run(SG_CASES[93]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8) | ((uint64_t) r.replace_corrupt << 9); }()) == 13, "FB-B2 value: sg row 93: code | arm_off_only << 8 | replace_corrupt << 9");
static_assert(text_is("SAVE REFUSED - Home Assistant heartbeat is not stable; wait until the dashboard shows it healthy, then review and save again", []{ const SaveGateResult r = sg_run(SG_CASES[93]); return r.text; }()), "FB-B2 text: sg row 93: text");
static_assert(([]{ const SaveGateResult r = sg_run(SG_CASES[94]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8) | ((uint64_t) r.replace_corrupt << 9); }()) == 13, "FB-B2 value: sg row 94: code | arm_off_only << 8 | replace_corrupt << 9");
static_assert(text_is("SAVE REFUSED - Home Assistant heartbeat is not stable; wait until the dashboard shows it healthy, then review and save again", []{ const SaveGateResult r = sg_run(SG_CASES[94]); return r.text; }()), "FB-B2 text: sg row 94: text");
static_assert(([]{ const SaveGateResult r = sg_run(SG_CASES[95]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8) | ((uint64_t) r.replace_corrupt << 9); }()) == 14, "FB-B2 value: sg row 95: code | arm_off_only << 8 | replace_corrupt << 9");
static_assert(text_is("SAVE REFUSED - clock not NTP-synchronised this boot; the capture time would be untrusted", []{ const SaveGateResult r = sg_run(SG_CASES[95]); return r.text; }()), "FB-B2 text: sg row 95: text");
static_assert(([]{ const SaveGateResult r = sg_run(SG_CASES[96]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8) | ((uint64_t) r.replace_corrupt << 9); }()) == 14, "FB-B2 value: sg row 96: code | arm_off_only << 8 | replace_corrupt << 9");
static_assert(text_is("SAVE REFUSED - clock not NTP-synchronised this boot; the capture time would be untrusted", []{ const SaveGateResult r = sg_run(SG_CASES[96]); return r.text; }()), "FB-B2 text: sg row 96: text");
static_assert(([]{ const SaveGateResult r = sg_run(SG_CASES[97]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8) | ((uint64_t) r.replace_corrupt << 9); }()) == 15, "FB-B2 value: sg row 97: code | arm_off_only << 8 | replace_corrupt << 9");
static_assert(text_is("SAVE REFUSED - a Free Power / Dump to Grid / Manual Configuration write arm is on; finish or turn it off first", []{ const SaveGateResult r = sg_run(SG_CASES[97]); return r.text; }()), "FB-B2 text: sg row 97: text");
static_assert(([]{ const SaveGateResult r = sg_run(SG_CASES[98]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8) | ((uint64_t) r.replace_corrupt << 9); }()) == 15, "FB-B2 value: sg row 98: code | arm_off_only << 8 | replace_corrupt << 9");
static_assert(text_is("SAVE REFUSED - a Free Power / Dump to Grid / Manual Configuration write arm is on; finish or turn it off first", []{ const SaveGateResult r = sg_run(SG_CASES[98]); return r.text; }()), "FB-B2 text: sg row 98: text");
static_assert(([]{ const SaveGateResult r = sg_run(SG_CASES[99]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8) | ((uint64_t) r.replace_corrupt << 9); }()) == 15, "FB-B2 value: sg row 99: code | arm_off_only << 8 | replace_corrupt << 9");
static_assert(text_is("SAVE REFUSED - a Free Power / Dump to Grid / Manual Configuration write arm is on; finish or turn it off first", []{ const SaveGateResult r = sg_run(SG_CASES[99]); return r.text; }()), "FB-B2 text: sg row 99: text");
static_assert(([]{ const SaveGateResult r = sg_run(SG_CASES[100]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8) | ((uint64_t) r.replace_corrupt << 9); }()) == 15, "FB-B2 value: sg row 100: code | arm_off_only << 8 | replace_corrupt << 9");
static_assert(text_is("SAVE REFUSED - a Free Power / Dump to Grid / Manual Configuration write arm is on; finish or turn it off first", []{ const SaveGateResult r = sg_run(SG_CASES[100]); return r.text; }()), "FB-B2 text: sg row 100: text");
static_assert(([]{ const SaveGateResult r = sg_run(SG_CASES[101]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8) | ((uint64_t) r.replace_corrupt << 9); }()) == 15, "FB-B2 value: sg row 101: code | arm_off_only << 8 | replace_corrupt << 9");
static_assert(text_is("SAVE REFUSED - a Free Power / Dump to Grid / Manual Configuration write arm is on; finish or turn it off first", []{ const SaveGateResult r = sg_run(SG_CASES[101]); return r.text; }()), "FB-B2 text: sg row 101: text");
static_assert(([]{ const SaveGateResult r = sg_run(SG_CASES[102]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8) | ((uint64_t) r.replace_corrupt << 9); }()) == 16, "FB-B2 value: sg row 102: code | arm_off_only << 8 | replace_corrupt << 9");
static_assert(text_is("SAVE REFUSED - another ECCO inverter write started since Review - review again", []{ const SaveGateResult r = sg_run(SG_CASES[102]); return r.text; }()), "FB-B2 text: sg row 102: text");
static_assert(([]{ const SaveGateResult r = sg_run(SG_CASES[103]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8) | ((uint64_t) r.replace_corrupt << 9); }()) == 16, "FB-B2 value: sg row 103: code | arm_off_only << 8 | replace_corrupt << 9");
static_assert(text_is("SAVE REFUSED - another ECCO inverter write started since Review - review again", []{ const SaveGateResult r = sg_run(SG_CASES[103]); return r.text; }()), "FB-B2 text: sg row 103: text");
static_assert(([]{ const SaveGateResult r = sg_run(SG_CASES[104]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8) | ((uint64_t) r.replace_corrupt << 9); }()) == 16, "FB-B2 value: sg row 104: code | arm_off_only << 8 | replace_corrupt << 9");
static_assert(text_is("SAVE REFUSED - another ECCO inverter write started since Review - review again", []{ const SaveGateResult r = sg_run(SG_CASES[104]); return r.text; }()), "FB-B2 text: sg row 104: text");
static_assert(([]{ const SaveGateResult r = sg_run(SG_CASES[105]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8) | ((uint64_t) r.replace_corrupt << 9); }()) == 16, "FB-B2 value: sg row 105: code | arm_off_only << 8 | replace_corrupt << 9");
static_assert(text_is("SAVE REFUSED - another ECCO inverter write started since Review - review again", []{ const SaveGateResult r = sg_run(SG_CASES[105]); return r.text; }()), "FB-B2 text: sg row 105: text");
static_assert(([]{ const SaveGateResult r = sg_run(SG_CASES[106]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8) | ((uint64_t) r.replace_corrupt << 9); }()) == 16, "FB-B2 value: sg row 106: code | arm_off_only << 8 | replace_corrupt << 9");
static_assert(text_is("SAVE REFUSED - another ECCO inverter write started since Review - review again", []{ const SaveGateResult r = sg_run(SG_CASES[106]); return r.text; }()), "FB-B2 text: sg row 106: text");
static_assert(([]{ const SaveGateResult r = sg_run(SG_CASES[107]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8) | ((uint64_t) r.replace_corrupt << 9); }()) == 16, "FB-B2 value: sg row 107: code | arm_off_only << 8 | replace_corrupt << 9");
static_assert(text_is("SAVE REFUSED - another ECCO inverter write started since Review - review again", []{ const SaveGateResult r = sg_run(SG_CASES[107]); return r.text; }()), "FB-B2 text: sg row 107: text");
static_assert(([]{ const SaveGateResult r = sg_run(SG_CASES[108]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8) | ((uint64_t) r.replace_corrupt << 9); }()) == 16, "FB-B2 value: sg row 108: code | arm_off_only << 8 | replace_corrupt << 9");
static_assert(text_is("SAVE REFUSED - another ECCO inverter write started since Review - review again", []{ const SaveGateResult r = sg_run(SG_CASES[108]); return r.text; }()), "FB-B2 text: sg row 108: text");
static_assert(([]{ const SaveGateResult r = sg_run(SG_CASES[109]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8) | ((uint64_t) r.replace_corrupt << 9); }()) == 1, "FB-B2 value: sg row 109: code | arm_off_only << 8 | replace_corrupt << 9");
static_assert(text_is("", []{ const SaveGateResult r = sg_run(SG_CASES[109]); return r.text; }()), "FB-B2 text: sg row 109: text");
static_assert(([]{ const SaveGateResult r = sg_run(SG_CASES[110]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8) | ((uint64_t) r.replace_corrupt << 9); }()) == 1, "FB-B2 value: sg row 110: code | arm_off_only << 8 | replace_corrupt << 9");
static_assert(text_is("", []{ const SaveGateResult r = sg_run(SG_CASES[110]); return r.text; }()), "FB-B2 text: sg row 110: text");
static_assert(([]{ const SaveGateResult r = sg_run(SG_CASES[111]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8) | ((uint64_t) r.replace_corrupt << 9); }()) == 16, "FB-B2 value: sg row 111: code | arm_off_only << 8 | replace_corrupt << 9");
static_assert(text_is("SAVE REFUSED - another ECCO inverter write started since Review - review again", []{ const SaveGateResult r = sg_run(SG_CASES[111]); return r.text; }()), "FB-B2 text: sg row 111: text");
static_assert(([]{ const SaveGateResult r = sg_run(SG_CASES[112]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8) | ((uint64_t) r.replace_corrupt << 9); }()) == 16, "FB-B2 value: sg row 112: code | arm_off_only << 8 | replace_corrupt << 9");
static_assert(text_is("SAVE REFUSED - another ECCO inverter write started since Review - review again", []{ const SaveGateResult r = sg_run(SG_CASES[112]); return r.text; }()), "FB-B2 text: sg row 112: text");
static_assert(([]{ const SaveGateResult r = sg_run(SG_CASES[113]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8) | ((uint64_t) r.replace_corrupt << 9); }()) == 16, "FB-B2 value: sg row 113: code | arm_off_only << 8 | replace_corrupt << 9");
static_assert(text_is("SAVE REFUSED - another ECCO inverter write started since Review - review again", []{ const SaveGateResult r = sg_run(SG_CASES[113]); return r.text; }()), "FB-B2 text: sg row 113: text");
static_assert(([]{ const SaveGateResult r = sg_run(SG_CASES[114]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8) | ((uint64_t) r.replace_corrupt << 9); }()) == 15, "FB-B2 value: sg row 114: code | arm_off_only << 8 | replace_corrupt << 9");
static_assert(text_is("SAVE REFUSED - a Free Power / Dump to Grid / Manual Configuration write arm is on; finish or turn it off first", []{ const SaveGateResult r = sg_run(SG_CASES[114]); return r.text; }()), "FB-B2 text: sg row 114: text");
static_assert(([]{ const SaveGateResult r = sg_run(SG_CASES[115]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8) | ((uint64_t) r.replace_corrupt << 9); }()) == 17, "FB-B2 value: sg row 115: code | arm_off_only << 8 | replace_corrupt << 9");
static_assert(text_is("SAVE REFUSED - another inverter transaction is in progress (manual write); try again shortly", []{ const SaveGateResult r = sg_run(SG_CASES[115]); return r.text; }()), "FB-B2 text: sg row 115: text");
static_assert(([]{ const SaveGateResult r = sg_run(SG_CASES[116]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8) | ((uint64_t) r.replace_corrupt << 9); }()) == 17, "FB-B2 value: sg row 116: code | arm_off_only << 8 | replace_corrupt << 9");
static_assert(text_is("SAVE REFUSED - another inverter transaction is in progress (clock correction); try again shortly", []{ const SaveGateResult r = sg_run(SG_CASES[116]); return r.text; }()), "FB-B2 text: sg row 116: text");
static_assert(([]{ const SaveGateResult r = sg_run(SG_CASES[117]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8) | ((uint64_t) r.replace_corrupt << 9); }()) == 17, "FB-B2 value: sg row 117: code | arm_off_only << 8 | replace_corrupt << 9");
static_assert(text_is("SAVE REFUSED - inverter write lock held for 301 s (possible leak); a reboot may be required", []{ const SaveGateResult r = sg_run(SG_CASES[117]); return r.text; }()), "FB-B2 text: sg row 117: text");
static_assert(([]{ const SaveGateResult r = sg_run(SG_CASES[118]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8) | ((uint64_t) r.replace_corrupt << 9); }()) == 17, "FB-B2 value: sg row 118: code | arm_off_only << 8 | replace_corrupt << 9");
static_assert(text_is("SAVE REFUSED - another inverter transaction is in progress (clock verification); try again shortly", []{ const SaveGateResult r = sg_run(SG_CASES[118]); return r.text; }()), "FB-B2 text: sg row 118: text");
static_assert(([]{ const SaveGateResult r = sg_run(SG_CASES[119]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8) | ((uint64_t) r.replace_corrupt << 9); }()) == 17, "FB-B2 value: sg row 119: code | arm_off_only << 8 | replace_corrupt << 9");
static_assert(text_is("SAVE REFUSED - another inverter transaction is in progress (Register 244 test); try again shortly", []{ const SaveGateResult r = sg_run(SG_CASES[119]); return r.text; }()), "FB-B2 text: sg row 119: text");
static_assert(([]{ const SaveGateResult r = sg_run(SG_CASES[120]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8) | ((uint64_t) r.replace_corrupt << 9); }()) == 17, "FB-B2 value: sg row 120: code | arm_off_only << 8 | replace_corrupt << 9");
static_assert(text_is("SAVE REFUSED - another inverter transaction is in progress (Free Power); try again shortly", []{ const SaveGateResult r = sg_run(SG_CASES[120]); return r.text; }()), "FB-B2 text: sg row 120: text");
static_assert(([]{ const SaveGateResult r = sg_run(SG_CASES[121]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8) | ((uint64_t) r.replace_corrupt << 9); }()) == 17, "FB-B2 value: sg row 121: code | arm_off_only << 8 | replace_corrupt << 9");
static_assert(text_is("SAVE REFUSED - another inverter transaction is in progress (Dump to Grid); try again shortly", []{ const SaveGateResult r = sg_run(SG_CASES[121]); return r.text; }()), "FB-B2 text: sg row 121: text");
static_assert(([]{ const SaveGateResult r = sg_run(SG_CASES[122]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8) | ((uint64_t) r.replace_corrupt << 9); }()) == 17, "FB-B2 value: sg row 122: code | arm_off_only << 8 | replace_corrupt << 9");
static_assert(text_is("SAVE REFUSED - another inverter transaction is in progress (Free Power); try again shortly", []{ const SaveGateResult r = sg_run(SG_CASES[122]); return r.text; }()), "FB-B2 text: sg row 122: text");
static_assert(([]{ const SaveGateResult r = sg_run(SG_CASES[123]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8) | ((uint64_t) r.replace_corrupt << 9); }()) == 17, "FB-B2 value: sg row 123: code | arm_off_only << 8 | replace_corrupt << 9");
static_assert(text_is("SAVE REFUSED - another inverter transaction is in progress (manual write); try again shortly", []{ const SaveGateResult r = sg_run(SG_CASES[123]); return r.text; }()), "FB-B2 text: sg row 123: text");
static_assert(([]{ const SaveGateResult r = sg_run(SG_CASES[124]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8) | ((uint64_t) r.replace_corrupt << 9); }()) == 17, "FB-B2 value: sg row 124: code | arm_off_only << 8 | replace_corrupt << 9");
static_assert(text_is("SAVE REFUSED - another inverter transaction is in progress (Free Power); try again shortly", []{ const SaveGateResult r = sg_run(SG_CASES[124]); return r.text; }()), "FB-B2 text: sg row 124: text");
static_assert(([]{ const SaveGateResult r = sg_run(SG_CASES[125]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8) | ((uint64_t) r.replace_corrupt << 9); }()) == 17, "FB-B2 value: sg row 125: code | arm_off_only << 8 | replace_corrupt << 9");
static_assert(text_is("SAVE REFUSED - another inverter transaction is in progress (Dump to Grid); try again shortly", []{ const SaveGateResult r = sg_run(SG_CASES[125]); return r.text; }()), "FB-B2 text: sg row 125: text");
static_assert(([]{ const SaveGateResult r = sg_run(SG_CASES[126]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8) | ((uint64_t) r.replace_corrupt << 9); }()) == 18, "FB-B2 value: sg row 126: code | arm_off_only << 8 | replace_corrupt << 9");
static_assert(text_is("SAVE REFUSED - a failback episode record exists; only the firmware that created it can resolve it", []{ const SaveGateResult r = sg_run(SG_CASES[126]); return r.text; }()), "FB-B2 text: sg row 126: text");
static_assert(([]{ const SaveGateResult r = sg_run(SG_CASES[127]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8) | ((uint64_t) r.replace_corrupt << 9); }()) == 18, "FB-B2 value: sg row 127: code | arm_off_only << 8 | replace_corrupt << 9");
static_assert(text_is("SAVE REFUSED - Failback record recovery metadata is CORRUPT (hard lockout); Fallback never overwrites or proceeds past it; do not erase NVS", []{ const SaveGateResult r = sg_run(SG_CASES[127]); return r.text; }()), "FB-B2 text: sg row 127: text");
static_assert(([]{ const SaveGateResult r = sg_run(SG_CASES[128]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8) | ((uint64_t) r.replace_corrupt << 9); }()) == 18, "FB-B2 value: sg row 128: code | arm_off_only << 8 | replace_corrupt << 9");
static_assert(text_is("SAVE REFUSED - Failback record recovery state UNKNOWN since boot (marker unreadable); an obligation cannot be ruled out; Fallback never proceeds past it", []{ const SaveGateResult r = sg_run(SG_CASES[128]); return r.text; }()), "FB-B2 text: sg row 128: text");
static_assert(([]{ const SaveGateResult r = sg_run(SG_CASES[129]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8) | ((uint64_t) r.replace_corrupt << 9); }()) == 19, "FB-B2 value: sg row 129: code | arm_off_only << 8 | replace_corrupt << 9");
static_assert(text_is("SAVE REFUSED - Free Power is active; live settings are a temporary overlay - end it first", []{ const SaveGateResult r = sg_run(SG_CASES[129]); return r.text; }()), "FB-B2 text: sg row 129: text");
static_assert(([]{ const SaveGateResult r = sg_run(SG_CASES[130]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8) | ((uint64_t) r.replace_corrupt << 9); }()) == 20, "FB-B2 value: sg row 130: code | arm_off_only << 8 | replace_corrupt << 9");
static_assert(text_is("SAVE REFUSED - Dump to Grid needs an operator recovery action first", []{ const SaveGateResult r = sg_run(SG_CASES[130]); return r.text; }()), "FB-B2 text: sg row 130: text");
static_assert(([]{ const SaveGateResult r = sg_run(SG_CASES[131]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8) | ((uint64_t) r.replace_corrupt << 9); }()) == 21, "FB-B2 value: sg row 131: code | arm_off_only << 8 | replace_corrupt << 9");
static_assert(text_is("SAVE REFUSED - Register 244 test restore verified; durable clear still pending - press Restore Original (armed)", []{ const SaveGateResult r = sg_run(SG_CASES[131]); return r.text; }()), "FB-B2 text: sg row 131: text");
static_assert(([]{ const SaveGateResult r = sg_run(SG_CASES[132]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8) | ((uint64_t) r.replace_corrupt << 9); }()) == 19, "FB-B2 value: sg row 132: code | arm_off_only << 8 | replace_corrupt << 9");
static_assert(text_is("SAVE REFUSED - Free Power recovery marker became unreadable at runtime; saving blocked until reboot. After reboot it may read absent: verify live settings first; do not erase NVS", []{ const SaveGateResult r = sg_run(SG_CASES[132]); return r.text; }()), "FB-B2 text: sg row 132: text");
static_assert(([]{ const SaveGateResult r = sg_run(SG_CASES[133]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8) | ((uint64_t) r.replace_corrupt << 9); }()) == 19, "FB-B2 value: sg row 133: code | arm_off_only << 8 | replace_corrupt << 9");
static_assert(text_is("SAVE REFUSED - Free Power in-memory recovery state is inconsistent; a reboot must re-derive it before saving", []{ const SaveGateResult r = sg_run(SG_CASES[133]); return r.text; }()), "FB-B2 text: sg row 133: text");
static_assert(([]{ const SaveGateResult r = sg_run(SG_CASES[134]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8) | ((uint64_t) r.replace_corrupt << 9); }()) == 3, "FB-B2 value: sg row 134: code | arm_off_only << 8 | replace_corrupt << 9");
static_assert(text_is("REFUSED - unsupported action 'CAPTURE'", []{ const SaveGateResult r = sg_run(SG_CASES[134]); return r.text; }()), "FB-B2 text: sg row 134: text");
static_assert(([]{ const SaveGateResult r = sg_run(SG_CASES[135]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8) | ((uint64_t) r.replace_corrupt << 9); }()) == 4, "FB-B2 value: sg row 135: code | arm_off_only << 8 | replace_corrupt << 9");
static_assert(text_is("SAVE REFUSED - ECCO Fallback Profile Arm is not on", []{ const SaveGateResult r = sg_run(SG_CASES[135]); return r.text; }()), "FB-B2 text: sg row 135: text");
static_assert(([]{ const SaveGateResult r = sg_run(SG_CASES[136]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8) | ((uint64_t) r.replace_corrupt << 9); }()) == 5, "FB-B2 value: sg row 136: code | arm_off_only << 8 | replace_corrupt << 9");
static_assert(text_is("SAVE REFUSED - no saveable candidate - press Review Current Configuration first", []{ const SaveGateResult r = sg_run(SG_CASES[136]); return r.text; }()), "FB-B2 text: sg row 136: text");
static_assert(([]{ const SaveGateResult r = sg_run(SgRow{0, 1, 0, 0, 0, 0, 5, 1, 0, 0, 1, 1, 0, 0, SG_ACCEPT}); return r.code; }()) == 1, "FB-B2 value: sg base with gate scenario 0: code");
static_assert(text_is("FP:NP,DP:NP,R4:NP,MT:CN,FS:CA,BUS:OK", []{ const SaveGateResult r = sg_run(SgRow{0, 1, 0, 0, 0, 0, 5, 1, 0, 0, 1, 1, 0, 0, SG_ACCEPT}); return r.obl; }()), "FB-B2 text: sg base with gate scenario 0: obl");
static_assert(text_is("", []{ const SaveGateResult r = sg_run(SgRow{0, 1, 0, 0, 0, 0, 5, 1, 0, 0, 1, 1, 0, 0, SG_ACCEPT}); return r.text; }()), "FB-B2 text: sg base with gate scenario 0: text");
static_assert(([]{ const SaveGateResult r = sg_run(SgRow{0, 1, 0, 0, 0, 0, 5, 1, 0, 0, 1, 1, 0, 1, SG_ACCEPT}); return r.code; }()) == 2, "FB-B2 value: sg base with gate scenario 1: code");
static_assert(text_is("", []{ const SaveGateResult r = sg_run(SgRow{0, 1, 0, 0, 0, 0, 5, 1, 0, 0, 1, 1, 0, 1, SG_ACCEPT}); return r.obl; }()), "FB-B2 text: sg base with gate scenario 1: obl");
static_assert(text_is("SAVE REFUSED - another Fallback Profile operation is in progress", []{ const SaveGateResult r = sg_run(SgRow{0, 1, 0, 0, 0, 0, 5, 1, 0, 0, 1, 1, 0, 1, SG_ACCEPT}); return r.text; }()), "FB-B2 text: sg base with gate scenario 1: text");
static_assert(([]{ const SaveGateResult r = sg_run(SgRow{0, 1, 0, 0, 0, 0, 5, 1, 0, 0, 1, 1, 0, 2, SG_ACCEPT}); return r.code; }()) == 2, "FB-B2 value: sg base with gate scenario 2: code");
static_assert(text_is("", []{ const SaveGateResult r = sg_run(SgRow{0, 1, 0, 0, 0, 0, 5, 1, 0, 0, 1, 1, 0, 2, SG_ACCEPT}); return r.obl; }()), "FB-B2 text: sg base with gate scenario 2: obl");
static_assert(text_is("SAVE REFUSED - another Fallback Profile operation is in progress", []{ const SaveGateResult r = sg_run(SgRow{0, 1, 0, 0, 0, 0, 5, 1, 0, 0, 1, 1, 0, 2, SG_ACCEPT}); return r.text; }()), "FB-B2 text: sg base with gate scenario 2: text");
static_assert(([]{ const SaveGateResult r = sg_run(SgRow{0, 1, 0, 0, 0, 0, 5, 1, 0, 0, 1, 1, 0, 3, SG_ACCEPT}); return r.code; }()) == 10, "FB-B2 value: sg base with gate scenario 3: code");
static_assert(text_is("FP:BL,DP:BL,R4:BL,MT:BL,FS:BL,BUS:OK", []{ const SaveGateResult r = sg_run(SgRow{0, 1, 0, 0, 0, 0, 5, 1, 0, 0, 1, 1, 0, 3, SG_ACCEPT}); return r.obl; }()), "FB-B2 text: sg base with gate scenario 3: obl");
static_assert(text_is("SAVE REFUSED - durable state not loaded yet", []{ const SaveGateResult r = sg_run(SgRow{0, 1, 0, 0, 0, 0, 5, 1, 0, 0, 1, 1, 0, 3, SG_ACCEPT}); return r.text; }()), "FB-B2 text: sg base with gate scenario 3: text");
static_assert(([]{ const SaveGateResult r = sg_run(SgRow{0, 1, 0, 0, 0, 0, 5, 1, 0, 0, 1, 1, 0, 4, SG_ACCEPT}); return r.code; }()) == 15, "FB-B2 value: sg base with gate scenario 4: code");
static_assert(text_is("FP:NP,DP:NP,R4:NP,MT:CN,FS:CA,BUS:OK", []{ const SaveGateResult r = sg_run(SgRow{0, 1, 0, 0, 0, 0, 5, 1, 0, 0, 1, 1, 0, 4, SG_ACCEPT}); return r.obl; }()), "FB-B2 text: sg base with gate scenario 4: obl");
static_assert(text_is("SAVE REFUSED - a Free Power / Dump to Grid / Manual Configuration write arm is on; finish or turn it off first", []{ const SaveGateResult r = sg_run(SgRow{0, 1, 0, 0, 0, 0, 5, 1, 0, 0, 1, 1, 0, 4, SG_ACCEPT}); return r.text; }()), "FB-B2 text: sg base with gate scenario 4: text");
static_assert(([]{ const SaveGateResult r = sg_run(SgRow{0, 1, 0, 0, 0, 0, 5, 1, 0, 0, 1, 1, 0, 5, SG_ACCEPT}); return r.code; }()) == 15, "FB-B2 value: sg base with gate scenario 5: code");
static_assert(text_is("FP:NP,DP:NP,R4:NP,MT:CN,FS:CA,BUS:OK", []{ const SaveGateResult r = sg_run(SgRow{0, 1, 0, 0, 0, 0, 5, 1, 0, 0, 1, 1, 0, 5, SG_ACCEPT}); return r.obl; }()), "FB-B2 text: sg base with gate scenario 5: obl");
static_assert(text_is("SAVE REFUSED - a Free Power / Dump to Grid / Manual Configuration write arm is on; finish or turn it off first", []{ const SaveGateResult r = sg_run(SgRow{0, 1, 0, 0, 0, 0, 5, 1, 0, 0, 1, 1, 0, 5, SG_ACCEPT}); return r.text; }()), "FB-B2 text: sg base with gate scenario 5: text");
static_assert(([]{ const SaveGateResult r = sg_run(SgRow{0, 1, 0, 0, 0, 0, 5, 1, 0, 0, 1, 1, 0, 6, SG_ACCEPT}); return r.code; }()) == 15, "FB-B2 value: sg base with gate scenario 6: code");
static_assert(text_is("FP:NP,DP:NP,R4:NP,MT:CN,FS:CA,BUS:OK", []{ const SaveGateResult r = sg_run(SgRow{0, 1, 0, 0, 0, 0, 5, 1, 0, 0, 1, 1, 0, 6, SG_ACCEPT}); return r.obl; }()), "FB-B2 text: sg base with gate scenario 6: obl");
static_assert(text_is("SAVE REFUSED - a Free Power / Dump to Grid / Manual Configuration write arm is on; finish or turn it off first", []{ const SaveGateResult r = sg_run(SgRow{0, 1, 0, 0, 0, 0, 5, 1, 0, 0, 1, 1, 0, 6, SG_ACCEPT}); return r.text; }()), "FB-B2 text: sg base with gate scenario 6: text");
static_assert(([]{ const SaveGateResult r = sg_run(SgRow{0, 1, 0, 0, 0, 0, 5, 1, 0, 0, 1, 1, 0, 7, SG_ACCEPT}); return r.code; }()) == 17, "FB-B2 value: sg base with gate scenario 7: code");
static_assert(text_is("FP:NP,DP:NP,R4:NP,MT:NP,FS:CA,BUS:BY", []{ const SaveGateResult r = sg_run(SgRow{0, 1, 0, 0, 0, 0, 5, 1, 0, 0, 1, 1, 0, 7, SG_ACCEPT}); return r.obl; }()), "FB-B2 text: sg base with gate scenario 7: obl");
static_assert(text_is("SAVE REFUSED - another inverter transaction is in progress (manual write); try again shortly", []{ const SaveGateResult r = sg_run(SgRow{0, 1, 0, 0, 0, 0, 5, 1, 0, 0, 1, 1, 0, 7, SG_ACCEPT}); return r.text; }()), "FB-B2 text: sg base with gate scenario 7: text");
static_assert(([]{ const SaveGateResult r = sg_run(SgRow{0, 1, 0, 0, 0, 0, 5, 1, 0, 0, 1, 1, 0, 8, SG_ACCEPT}); return r.code; }()) == 17, "FB-B2 value: sg base with gate scenario 8: code");
static_assert(text_is("FP:NP,DP:NP,R4:NP,MT:NP,FS:CA,BUS:BY", []{ const SaveGateResult r = sg_run(SgRow{0, 1, 0, 0, 0, 0, 5, 1, 0, 0, 1, 1, 0, 8, SG_ACCEPT}); return r.obl; }()), "FB-B2 text: sg base with gate scenario 8: obl");
static_assert(text_is("SAVE REFUSED - another inverter transaction is in progress (clock correction); try again shortly", []{ const SaveGateResult r = sg_run(SgRow{0, 1, 0, 0, 0, 0, 5, 1, 0, 0, 1, 1, 0, 8, SG_ACCEPT}); return r.text; }()), "FB-B2 text: sg base with gate scenario 8: text");
static_assert(([]{ const SaveGateResult r = sg_run(SgRow{0, 1, 0, 0, 0, 0, 5, 1, 0, 0, 1, 1, 0, 9, SG_ACCEPT}); return r.code; }()) == 17, "FB-B2 value: sg base with gate scenario 9: code");
static_assert(text_is("FP:NP,DP:NP,R4:NP,MT:NP,FS:CA,BUS:LK", []{ const SaveGateResult r = sg_run(SgRow{0, 1, 0, 0, 0, 0, 5, 1, 0, 0, 1, 1, 0, 9, SG_ACCEPT}); return r.obl; }()), "FB-B2 text: sg base with gate scenario 9: obl");
static_assert(text_is("SAVE REFUSED - inverter write lock held for 301 s (possible leak); a reboot may be required", []{ const SaveGateResult r = sg_run(SgRow{0, 1, 0, 0, 0, 0, 5, 1, 0, 0, 1, 1, 0, 9, SG_ACCEPT}); return r.text; }()), "FB-B2 text: sg base with gate scenario 9: text");
static_assert(([]{ const SaveGateResult r = sg_run(SgRow{0, 1, 0, 0, 0, 0, 5, 1, 0, 0, 1, 1, 0, 10, SG_ACCEPT}); return r.code; }()) == 18, "FB-B2 value: sg base with gate scenario 10: code");
static_assert(text_is("FP:NP,DP:NP,R4:NP,MT:CN,FS:AC,BUS:OK", []{ const SaveGateResult r = sg_run(SgRow{0, 1, 0, 0, 0, 0, 5, 1, 0, 0, 1, 1, 0, 10, SG_ACCEPT}); return r.obl; }()), "FB-B2 text: sg base with gate scenario 10: obl");
static_assert(text_is("SAVE REFUSED - a failback episode record exists; only the firmware that created it can resolve it", []{ const SaveGateResult r = sg_run(SgRow{0, 1, 0, 0, 0, 0, 5, 1, 0, 0, 1, 1, 0, 10, SG_ACCEPT}); return r.text; }()), "FB-B2 text: sg base with gate scenario 10: text");
static_assert(([]{ const SaveGateResult r = sg_run(SgRow{0, 1, 0, 0, 0, 0, 5, 1, 0, 0, 1, 1, 0, 11, SG_ACCEPT}); return r.code; }()) == 18, "FB-B2 value: sg base with gate scenario 11: code");
static_assert(text_is("FP:NP,DP:NP,R4:NP,MT:CN,FS:MC,BUS:OK", []{ const SaveGateResult r = sg_run(SgRow{0, 1, 0, 0, 0, 0, 5, 1, 0, 0, 1, 1, 0, 11, SG_ACCEPT}); return r.obl; }()), "FB-B2 text: sg base with gate scenario 11: obl");
static_assert(text_is("SAVE REFUSED - Failback record recovery metadata is CORRUPT (hard lockout); Fallback never overwrites or proceeds past it; do not erase NVS", []{ const SaveGateResult r = sg_run(SgRow{0, 1, 0, 0, 0, 0, 5, 1, 0, 0, 1, 1, 0, 11, SG_ACCEPT}); return r.text; }()), "FB-B2 text: sg base with gate scenario 11: text");
static_assert(([]{ const SaveGateResult r = sg_run(SgRow{0, 1, 0, 0, 0, 0, 5, 1, 0, 0, 1, 1, 0, 12, SG_ACCEPT}); return r.code; }()) == 18, "FB-B2 value: sg base with gate scenario 12: code");
static_assert(text_is("FP:NP,DP:NP,R4:NP,MT:CN,FS:UR,BUS:OK", []{ const SaveGateResult r = sg_run(SgRow{0, 1, 0, 0, 0, 0, 5, 1, 0, 0, 1, 1, 0, 12, SG_ACCEPT}); return r.obl; }()), "FB-B2 text: sg base with gate scenario 12: obl");
static_assert(text_is("SAVE REFUSED - Failback record recovery state UNKNOWN since boot (marker unreadable); an obligation cannot be ruled out; Fallback never proceeds past it", []{ const SaveGateResult r = sg_run(SgRow{0, 1, 0, 0, 0, 0, 5, 1, 0, 0, 1, 1, 0, 12, SG_ACCEPT}); return r.text; }()), "FB-B2 text: sg base with gate scenario 12: text");
static_assert(([]{ const SaveGateResult r = sg_run(SgRow{0, 1, 0, 0, 0, 0, 5, 1, 0, 0, 1, 1, 0, 13, SG_ACCEPT}); return r.code; }()) == 19, "FB-B2 value: sg base with gate scenario 13: code");
static_assert(text_is("FP:AC,DP:NP,R4:NP,MT:CN,FS:CA,BUS:OK", []{ const SaveGateResult r = sg_run(SgRow{0, 1, 0, 0, 0, 0, 5, 1, 0, 0, 1, 1, 0, 13, SG_ACCEPT}); return r.obl; }()), "FB-B2 text: sg base with gate scenario 13: obl");
static_assert(text_is("SAVE REFUSED - Free Power is active; live settings are a temporary overlay - end it first", []{ const SaveGateResult r = sg_run(SgRow{0, 1, 0, 0, 0, 0, 5, 1, 0, 0, 1, 1, 0, 13, SG_ACCEPT}); return r.text; }()), "FB-B2 text: sg base with gate scenario 13: text");
static_assert(([]{ const SaveGateResult r = sg_run(SgRow{0, 1, 0, 0, 0, 0, 5, 1, 0, 0, 1, 1, 0, 14, SG_ACCEPT}); return r.code; }()) == 20, "FB-B2 value: sg base with gate scenario 14: code");
static_assert(text_is("FP:NP,DP:ON,R4:NP,MT:CN,FS:CA,BUS:OK", []{ const SaveGateResult r = sg_run(SgRow{0, 1, 0, 0, 0, 0, 5, 1, 0, 0, 1, 1, 0, 14, SG_ACCEPT}); return r.obl; }()), "FB-B2 text: sg base with gate scenario 14: obl");
static_assert(text_is("SAVE REFUSED - Dump to Grid needs an operator recovery action first", []{ const SaveGateResult r = sg_run(SgRow{0, 1, 0, 0, 0, 0, 5, 1, 0, 0, 1, 1, 0, 14, SG_ACCEPT}); return r.text; }()), "FB-B2 text: sg base with gate scenario 14: text");
static_assert(([]{ const SaveGateResult r = sg_run(SgRow{0, 1, 0, 0, 0, 0, 5, 1, 0, 0, 1, 1, 0, 15, SG_ACCEPT}); return r.code; }()) == 21, "FB-B2 value: sg base with gate scenario 15: code");
static_assert(text_is("FP:NP,DP:NP,R4:PC,MT:CN,FS:CA,BUS:OK", []{ const SaveGateResult r = sg_run(SgRow{0, 1, 0, 0, 0, 0, 5, 1, 0, 0, 1, 1, 0, 15, SG_ACCEPT}); return r.obl; }()), "FB-B2 text: sg base with gate scenario 15: obl");
static_assert(text_is("SAVE REFUSED - Register 244 test restore verified; durable clear still pending - press Restore Original (armed)", []{ const SaveGateResult r = sg_run(SgRow{0, 1, 0, 0, 0, 0, 5, 1, 0, 0, 1, 1, 0, 15, SG_ACCEPT}); return r.text; }()), "FB-B2 text: sg base with gate scenario 15: text");
static_assert(([]{ const SaveGateResult r = sg_run(SgRow{0, 1, 0, 0, 0, 0, 5, 1, 0, 0, 1, 1, 0, 16, SG_ACCEPT}); return r.code; }()) == 19, "FB-B2 value: sg base with gate scenario 16: code");
static_assert(text_is("FP:UR,DP:NP,R4:NP,MT:CN,FS:CA,BUS:OK", []{ const SaveGateResult r = sg_run(SgRow{0, 1, 0, 0, 0, 0, 5, 1, 0, 0, 1, 1, 0, 16, SG_ACCEPT}); return r.obl; }()), "FB-B2 text: sg base with gate scenario 16: obl");
static_assert(text_is("SAVE REFUSED - Free Power recovery marker became unreadable at runtime; saving blocked until reboot. After reboot it may read absent: verify live settings first; do not erase NVS", []{ const SaveGateResult r = sg_run(SgRow{0, 1, 0, 0, 0, 0, 5, 1, 0, 0, 1, 1, 0, 16, SG_ACCEPT}); return r.text; }()), "FB-B2 text: sg base with gate scenario 16: text");
static_assert(([]{ const SaveGateResult r = sg_run(SgRow{0, 1, 0, 0, 0, 0, 5, 1, 0, 0, 1, 1, 0, 17, SG_ACCEPT}); return r.code; }()) == 15, "FB-B2 value: sg base with gate scenario 17: code");
static_assert(text_is("FP:NP,DP:NP,R4:NP,MT:NP,FS:CA,BUS:BY", []{ const SaveGateResult r = sg_run(SgRow{0, 1, 0, 0, 0, 0, 5, 1, 0, 0, 1, 1, 0, 17, SG_ACCEPT}); return r.obl; }()), "FB-B2 text: sg base with gate scenario 17: obl");
static_assert(text_is("SAVE REFUSED - a Free Power / Dump to Grid / Manual Configuration write arm is on; finish or turn it off first", []{ const SaveGateResult r = sg_run(SgRow{0, 1, 0, 0, 0, 0, 5, 1, 0, 0, 1, 1, 0, 17, SG_ACCEPT}); return r.text; }()), "FB-B2 text: sg base with gate scenario 17: text");
static_assert(([]{ const SaveGateResult r = sg_run(SgRow{0, 1, 0, 0, 0, 0, 5, 1, 0, 0, 1, 1, 0, 18, SG_ACCEPT}); return r.code; }()) == 17, "FB-B2 value: sg base with gate scenario 18: code");
static_assert(text_is("FP:NP,DP:NP,R4:NP,MT:NP,FS:AC,BUS:BY", []{ const SaveGateResult r = sg_run(SgRow{0, 1, 0, 0, 0, 0, 5, 1, 0, 0, 1, 1, 0, 18, SG_ACCEPT}); return r.obl; }()), "FB-B2 text: sg base with gate scenario 18: obl");
static_assert(text_is("SAVE REFUSED - another inverter transaction is in progress (manual write); try again shortly", []{ const SaveGateResult r = sg_run(SgRow{0, 1, 0, 0, 0, 0, 5, 1, 0, 0, 1, 1, 0, 18, SG_ACCEPT}); return r.text; }()), "FB-B2 text: sg base with gate scenario 18: text");
static_assert(([]{ const SaveGateResult r = sg_run(SgRow{0, 1, 0, 0, 0, 0, 5, 1, 0, 0, 1, 1, 0, 19, SG_ACCEPT}); return r.code; }()) == 19, "FB-B2 value: sg base with gate scenario 19: code");
static_assert(text_is("FP:DV,DP:DV,R4:NP,MT:CN,FS:CA,BUS:OK", []{ const SaveGateResult r = sg_run(SgRow{0, 1, 0, 0, 0, 0, 5, 1, 0, 0, 1, 1, 0, 19, SG_ACCEPT}); return r.obl; }()), "FB-B2 text: sg base with gate scenario 19: obl");
static_assert(text_is("SAVE REFUSED - Free Power in-memory recovery state is inconsistent; a reboot must re-derive it before saving", []{ const SaveGateResult r = sg_run(SgRow{0, 1, 0, 0, 0, 0, 5, 1, 0, 0, 1, 1, 0, 19, SG_ACCEPT}); return r.text; }()), "FB-B2 text: sg base with gate scenario 19: text");
static_assert(([]{ const SaveGateResult r = sg_run(SgRow{0, 1, 0, 0, 0, 0, 5, 1, 0, 0, 1, 1, 0, 20, SG_ACCEPT}); return r.code; }()) == 17, "FB-B2 value: sg base with gate scenario 20: code");
static_assert(text_is("FP:NP,DP:NP,R4:NP,MT:NP,FS:CA,BUS:BY", []{ const SaveGateResult r = sg_run(SgRow{0, 1, 0, 0, 0, 0, 5, 1, 0, 0, 1, 1, 0, 20, SG_ACCEPT}); return r.obl; }()), "FB-B2 text: sg base with gate scenario 20: obl");
static_assert(text_is("SAVE REFUSED - another inverter transaction is in progress (clock verification); try again shortly", []{ const SaveGateResult r = sg_run(SgRow{0, 1, 0, 0, 0, 0, 5, 1, 0, 0, 1, 1, 0, 20, SG_ACCEPT}); return r.text; }()), "FB-B2 text: sg base with gate scenario 20: text");
static_assert(([]{ const SaveGateResult r = sg_run(SgRow{0, 1, 0, 0, 0, 0, 5, 1, 0, 0, 1, 1, 0, 21, SG_ACCEPT}); return r.code; }()) == 17, "FB-B2 value: sg base with gate scenario 21: code");
static_assert(text_is("FP:NP,DP:NP,R4:LK,MT:NP,FS:CA,BUS:BY", []{ const SaveGateResult r = sg_run(SgRow{0, 1, 0, 0, 0, 0, 5, 1, 0, 0, 1, 1, 0, 21, SG_ACCEPT}); return r.obl; }()), "FB-B2 text: sg base with gate scenario 21: obl");
static_assert(text_is("SAVE REFUSED - another inverter transaction is in progress (Register 244 test); try again shortly", []{ const SaveGateResult r = sg_run(SgRow{0, 1, 0, 0, 0, 0, 5, 1, 0, 0, 1, 1, 0, 21, SG_ACCEPT}); return r.text; }()), "FB-B2 text: sg base with gate scenario 21: text");
static_assert(([]{ const SaveGateResult r = sg_run(SgRow{0, 1, 0, 0, 0, 0, 5, 1, 0, 0, 1, 1, 0, 22, SG_ACCEPT}); return r.code; }()) == 17, "FB-B2 value: sg base with gate scenario 22: code");
static_assert(text_is("FP:LK,DP:NP,R4:NP,MT:NP,FS:CA,BUS:BY", []{ const SaveGateResult r = sg_run(SgRow{0, 1, 0, 0, 0, 0, 5, 1, 0, 0, 1, 1, 0, 22, SG_ACCEPT}); return r.obl; }()), "FB-B2 text: sg base with gate scenario 22: obl");
static_assert(text_is("SAVE REFUSED - another inverter transaction is in progress (Free Power); try again shortly", []{ const SaveGateResult r = sg_run(SgRow{0, 1, 0, 0, 0, 0, 5, 1, 0, 0, 1, 1, 0, 22, SG_ACCEPT}); return r.text; }()), "FB-B2 text: sg base with gate scenario 22: text");
static_assert(([]{ const SaveGateResult r = sg_run(SgRow{0, 1, 0, 0, 0, 0, 5, 1, 0, 0, 1, 1, 0, 23, SG_ACCEPT}); return r.code; }()) == 1, "FB-B2 value: sg base with gate scenario 23: code");
static_assert(text_is("FP:NP,DP:NP,R4:NP,MT:CN,FS:CM,BUS:OK", []{ const SaveGateResult r = sg_run(SgRow{0, 1, 0, 0, 0, 0, 5, 1, 0, 0, 1, 1, 0, 23, SG_ACCEPT}); return r.obl; }()), "FB-B2 text: sg base with gate scenario 23: obl");
static_assert(text_is("", []{ const SaveGateResult r = sg_run(SgRow{0, 1, 0, 0, 0, 0, 5, 1, 0, 0, 1, 1, 0, 23, SG_ACCEPT}); return r.text; }()), "FB-B2 text: sg base with gate scenario 23: text");
static_assert(([]{ const SaveGateResult r = sg_run(SgRow{0, 1, 0, 0, 0, 0, 5, 1, 0, 0, 1, 1, 0, 24, SG_ACCEPT}); return r.code; }()) == 17, "FB-B2 value: sg base with gate scenario 24: code");
static_assert(text_is("FP:NP,DP:LK,R4:NP,MT:NP,FS:CA,BUS:BY", []{ const SaveGateResult r = sg_run(SgRow{0, 1, 0, 0, 0, 0, 5, 1, 0, 0, 1, 1, 0, 24, SG_ACCEPT}); return r.obl; }()), "FB-B2 text: sg base with gate scenario 24: obl");
static_assert(text_is("SAVE REFUSED - another inverter transaction is in progress (Dump to Grid); try again shortly", []{ const SaveGateResult r = sg_run(SgRow{0, 1, 0, 0, 0, 0, 5, 1, 0, 0, 1, 1, 0, 24, SG_ACCEPT}); return r.text; }()), "FB-B2 text: sg base with gate scenario 24: text");
static_assert(([]{ const SaveGateResult r = sg_run(SgRow{0, 1, 0, 0, 0, 0, 5, 1, 0, 0, 1, 1, 0, 25, SG_ACCEPT}); return r.code; }()) == 17, "FB-B2 value: sg base with gate scenario 25: code");
static_assert(text_is("FP:EN,DP:NP,R4:NP,MT:NP,FS:CA,BUS:BY", []{ const SaveGateResult r = sg_run(SgRow{0, 1, 0, 0, 0, 0, 5, 1, 0, 0, 1, 1, 0, 25, SG_ACCEPT}); return r.obl; }()), "FB-B2 text: sg base with gate scenario 25: obl");
static_assert(text_is("SAVE REFUSED - another inverter transaction is in progress (Free Power); try again shortly", []{ const SaveGateResult r = sg_run(SgRow{0, 1, 0, 0, 0, 0, 5, 1, 0, 0, 1, 1, 0, 25, SG_ACCEPT}); return r.text; }()), "FB-B2 text: sg base with gate scenario 25: text");
static_assert(([]{ const SaveGateResult r = sg_run(SgRow{0, 1, 0, 0, 0, 0, 5, 1, 0, 0, 1, 1, 0, 26, SG_ACCEPT}); return r.code; }()) == 17, "FB-B2 value: sg base with gate scenario 26: code");
static_assert(text_is("FP:AC,DP:NP,R4:NP,MT:NP,FS:CA,BUS:BY", []{ const SaveGateResult r = sg_run(SgRow{0, 1, 0, 0, 0, 0, 5, 1, 0, 0, 1, 1, 0, 26, SG_ACCEPT}); return r.obl; }()), "FB-B2 text: sg base with gate scenario 26: obl");
static_assert(text_is("SAVE REFUSED - another inverter transaction is in progress (Free Power); try again shortly", []{ const SaveGateResult r = sg_run(SgRow{0, 1, 0, 0, 0, 0, 5, 1, 0, 0, 1, 1, 0, 26, SG_ACCEPT}); return r.text; }()), "FB-B2 text: sg base with gate scenario 26: text");
static_assert(([]{ const SaveGateResult r = sg_run(SgRow{0, 1, 0, 0, 0, 0, 5, 1, 0, 0, 1, 1, 0, 27, SG_ACCEPT}); return r.code; }()) == 17, "FB-B2 value: sg base with gate scenario 27: code");
static_assert(text_is("FP:NP,DP:AC,R4:NP,MT:NP,FS:CA,BUS:BY", []{ const SaveGateResult r = sg_run(SgRow{0, 1, 0, 0, 0, 0, 5, 1, 0, 0, 1, 1, 0, 27, SG_ACCEPT}); return r.obl; }()), "FB-B2 text: sg base with gate scenario 27: obl");
static_assert(text_is("SAVE REFUSED - another inverter transaction is in progress (Dump to Grid); try again shortly", []{ const SaveGateResult r = sg_run(SgRow{0, 1, 0, 0, 0, 0, 5, 1, 0, 0, 1, 1, 0, 27, SG_ACCEPT}); return r.text; }()), "FB-B2 text: sg base with gate scenario 27: text");
static_assert(([]{ const SaveGateInputs si = fx_sg(0, 0, 5, 1, 0, 0, 1, 1, 1, 0); const TextBuf act = fx_action(0); const TextBuf tgt = fx_target(0, FX_ID); const TextBuf cnf = fx_conf(0, FX_ID); ecco_fbcap::GateResult gr{}; gr.code = 0; const SaveGateResult r = save_gate_with_result(si, act.c_str(), act.size(), tgt.c_str(), tgt.size(), cnf.c_str(), cnf.size(), fx_gate(0), gr); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8); }()) == 0, "FB-B2 value: save_gate_with_result forged capture gate code 0: code | arm_off_only << 8");
static_assert(text_is("SAVE REFUSED - internal: gate state unavailable; nothing written", []{ const SaveGateInputs si = fx_sg(0, 0, 5, 1, 0, 0, 1, 1, 1, 0); const TextBuf act = fx_action(0); const TextBuf tgt = fx_target(0, FX_ID); const TextBuf cnf = fx_conf(0, FX_ID); ecco_fbcap::GateResult gr{}; gr.code = 0; const SaveGateResult r = save_gate_with_result(si, act.c_str(), act.size(), tgt.c_str(), tgt.size(), cnf.c_str(), cnf.size(), fx_gate(0), gr); return r.text; }()), "FB-B2 text: save_gate_with_result forged capture gate code 0: text");
static_assert(([]{ const SaveGateInputs si = fx_sg(0, 0, 5, 1, 0, 0, 1, 1, 1, 0); const TextBuf act = fx_action(0); const TextBuf tgt = fx_target(0, FX_ID); const TextBuf cnf = fx_conf(0, FX_ID); ecco_fbcap::GateResult gr{}; gr.code = 1; const SaveGateResult r = save_gate_with_result(si, act.c_str(), act.size(), tgt.c_str(), tgt.size(), cnf.c_str(), cnf.size(), fx_gate(0), gr); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8); }()) == 1, "FB-B2 value: save_gate_with_result forged capture gate code 1: code | arm_off_only << 8");
static_assert(text_is("", []{ const SaveGateInputs si = fx_sg(0, 0, 5, 1, 0, 0, 1, 1, 1, 0); const TextBuf act = fx_action(0); const TextBuf tgt = fx_target(0, FX_ID); const TextBuf cnf = fx_conf(0, FX_ID); ecco_fbcap::GateResult gr{}; gr.code = 1; const SaveGateResult r = save_gate_with_result(si, act.c_str(), act.size(), tgt.c_str(), tgt.size(), cnf.c_str(), cnf.size(), fx_gate(0), gr); return r.text; }()), "FB-B2 text: save_gate_with_result forged capture gate code 1: text");
static_assert(([]{ const SaveGateInputs si = fx_sg(0, 0, 5, 1, 0, 0, 1, 1, 1, 0); const TextBuf act = fx_action(0); const TextBuf tgt = fx_target(0, FX_ID); const TextBuf cnf = fx_conf(0, FX_ID); ecco_fbcap::GateResult gr{}; gr.code = 2; const SaveGateResult r = save_gate_with_result(si, act.c_str(), act.size(), tgt.c_str(), tgt.size(), cnf.c_str(), cnf.size(), fx_gate(0), gr); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8); }()) == 1, "FB-B2 value: save_gate_with_result forged capture gate code 2: code | arm_off_only << 8");
static_assert(text_is("", []{ const SaveGateInputs si = fx_sg(0, 0, 5, 1, 0, 0, 1, 1, 1, 0); const TextBuf act = fx_action(0); const TextBuf tgt = fx_target(0, FX_ID); const TextBuf cnf = fx_conf(0, FX_ID); ecco_fbcap::GateResult gr{}; gr.code = 2; const SaveGateResult r = save_gate_with_result(si, act.c_str(), act.size(), tgt.c_str(), tgt.size(), cnf.c_str(), cnf.size(), fx_gate(0), gr); return r.text; }()), "FB-B2 text: save_gate_with_result forged capture gate code 2: text");
static_assert(([]{ const SaveGateInputs si = fx_sg(0, 0, 5, 1, 0, 0, 1, 1, 1, 0); const TextBuf act = fx_action(0); const TextBuf tgt = fx_target(0, FX_ID); const TextBuf cnf = fx_conf(0, FX_ID); ecco_fbcap::GateResult gr{}; gr.code = 3; const SaveGateResult r = save_gate_with_result(si, act.c_str(), act.size(), tgt.c_str(), tgt.size(), cnf.c_str(), cnf.size(), fx_gate(0), gr); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8); }()) == 258, "FB-B2 value: save_gate_with_result forged capture gate code 3: code | arm_off_only << 8");
static_assert(text_is("SAVE REFUSED - another Fallback Profile operation is in progress", []{ const SaveGateInputs si = fx_sg(0, 0, 5, 1, 0, 0, 1, 1, 1, 0); const TextBuf act = fx_action(0); const TextBuf tgt = fx_target(0, FX_ID); const TextBuf cnf = fx_conf(0, FX_ID); ecco_fbcap::GateResult gr{}; gr.code = 3; const SaveGateResult r = save_gate_with_result(si, act.c_str(), act.size(), tgt.c_str(), tgt.size(), cnf.c_str(), cnf.size(), fx_gate(0), gr); return r.text; }()), "FB-B2 text: save_gate_with_result forged capture gate code 3: text");
static_assert(([]{ const SaveGateInputs si = fx_sg(0, 0, 5, 1, 0, 0, 1, 1, 1, 0); const TextBuf act = fx_action(0); const TextBuf tgt = fx_target(0, FX_ID); const TextBuf cnf = fx_conf(0, FX_ID); ecco_fbcap::GateResult gr{}; gr.code = 4; const SaveGateResult r = save_gate_with_result(si, act.c_str(), act.size(), tgt.c_str(), tgt.size(), cnf.c_str(), cnf.size(), fx_gate(0), gr); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8); }()) == 10, "FB-B2 value: save_gate_with_result forged capture gate code 4: code | arm_off_only << 8");
static_assert(text_is("SAVE REFUSED - durable state not loaded yet", []{ const SaveGateInputs si = fx_sg(0, 0, 5, 1, 0, 0, 1, 1, 1, 0); const TextBuf act = fx_action(0); const TextBuf tgt = fx_target(0, FX_ID); const TextBuf cnf = fx_conf(0, FX_ID); ecco_fbcap::GateResult gr{}; gr.code = 4; const SaveGateResult r = save_gate_with_result(si, act.c_str(), act.size(), tgt.c_str(), tgt.size(), cnf.c_str(), cnf.size(), fx_gate(0), gr); return r.text; }()), "FB-B2 text: save_gate_with_result forged capture gate code 4: text");
static_assert(([]{ const SaveGateInputs si = fx_sg(0, 0, 5, 1, 0, 0, 1, 1, 1, 0); const TextBuf act = fx_action(0); const TextBuf tgt = fx_target(0, FX_ID); const TextBuf cnf = fx_conf(0, FX_ID); ecco_fbcap::GateResult gr{}; gr.code = 5; const SaveGateResult r = save_gate_with_result(si, act.c_str(), act.size(), tgt.c_str(), tgt.size(), cnf.c_str(), cnf.size(), fx_gate(0), gr); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8); }()) == 15, "FB-B2 value: save_gate_with_result forged capture gate code 5: code | arm_off_only << 8");
static_assert(text_is("SAVE REFUSED - a Free Power / Dump to Grid / Manual Configuration write arm is on; finish or turn it off first", []{ const SaveGateInputs si = fx_sg(0, 0, 5, 1, 0, 0, 1, 1, 1, 0); const TextBuf act = fx_action(0); const TextBuf tgt = fx_target(0, FX_ID); const TextBuf cnf = fx_conf(0, FX_ID); ecco_fbcap::GateResult gr{}; gr.code = 5; const SaveGateResult r = save_gate_with_result(si, act.c_str(), act.size(), tgt.c_str(), tgt.size(), cnf.c_str(), cnf.size(), fx_gate(0), gr); return r.text; }()), "FB-B2 text: save_gate_with_result forged capture gate code 5: text");
static_assert(([]{ const SaveGateInputs si = fx_sg(0, 0, 5, 1, 0, 0, 1, 1, 1, 0); const TextBuf act = fx_action(0); const TextBuf tgt = fx_target(0, FX_ID); const TextBuf cnf = fx_conf(0, FX_ID); ecco_fbcap::GateResult gr{}; gr.code = 6; const SaveGateResult r = save_gate_with_result(si, act.c_str(), act.size(), tgt.c_str(), tgt.size(), cnf.c_str(), cnf.size(), fx_gate(0), gr); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8); }()) == 17, "FB-B2 value: save_gate_with_result forged capture gate code 6: code | arm_off_only << 8");
static_assert(text_is("SAVE REFUSED - another inverter transaction is in progress (none); try again shortly", []{ const SaveGateInputs si = fx_sg(0, 0, 5, 1, 0, 0, 1, 1, 1, 0); const TextBuf act = fx_action(0); const TextBuf tgt = fx_target(0, FX_ID); const TextBuf cnf = fx_conf(0, FX_ID); ecco_fbcap::GateResult gr{}; gr.code = 6; const SaveGateResult r = save_gate_with_result(si, act.c_str(), act.size(), tgt.c_str(), tgt.size(), cnf.c_str(), cnf.size(), fx_gate(0), gr); return r.text; }()), "FB-B2 text: save_gate_with_result forged capture gate code 6: text");
static_assert(([]{ const SaveGateInputs si = fx_sg(0, 0, 5, 1, 0, 0, 1, 1, 1, 0); const TextBuf act = fx_action(0); const TextBuf tgt = fx_target(0, FX_ID); const TextBuf cnf = fx_conf(0, FX_ID); ecco_fbcap::GateResult gr{}; gr.code = 7; const SaveGateResult r = save_gate_with_result(si, act.c_str(), act.size(), tgt.c_str(), tgt.size(), cnf.c_str(), cnf.size(), fx_gate(0), gr); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8); }()) == 18, "FB-B2 value: save_gate_with_result forged capture gate code 7: code | arm_off_only << 8");
static_assert(text_is("SAVE REFUSED - Failback record state does not permit saving", []{ const SaveGateInputs si = fx_sg(0, 0, 5, 1, 0, 0, 1, 1, 1, 0); const TextBuf act = fx_action(0); const TextBuf tgt = fx_target(0, FX_ID); const TextBuf cnf = fx_conf(0, FX_ID); ecco_fbcap::GateResult gr{}; gr.code = 7; const SaveGateResult r = save_gate_with_result(si, act.c_str(), act.size(), tgt.c_str(), tgt.size(), cnf.c_str(), cnf.size(), fx_gate(0), gr); return r.text; }()), "FB-B2 text: save_gate_with_result forged capture gate code 7: text");
static_assert(([]{ const SaveGateInputs si = fx_sg(0, 0, 5, 1, 0, 0, 1, 1, 1, 0); const TextBuf act = fx_action(0); const TextBuf tgt = fx_target(0, FX_ID); const TextBuf cnf = fx_conf(0, FX_ID); ecco_fbcap::GateResult gr{}; gr.code = 8; const SaveGateResult r = save_gate_with_result(si, act.c_str(), act.size(), tgt.c_str(), tgt.size(), cnf.c_str(), cnf.size(), fx_gate(0), gr); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8); }()) == 19, "FB-B2 value: save_gate_with_result forged capture gate code 8: code | arm_off_only << 8");
static_assert(text_is("SAVE REFUSED - Free Power state does not permit saving", []{ const SaveGateInputs si = fx_sg(0, 0, 5, 1, 0, 0, 1, 1, 1, 0); const TextBuf act = fx_action(0); const TextBuf tgt = fx_target(0, FX_ID); const TextBuf cnf = fx_conf(0, FX_ID); ecco_fbcap::GateResult gr{}; gr.code = 8; const SaveGateResult r = save_gate_with_result(si, act.c_str(), act.size(), tgt.c_str(), tgt.size(), cnf.c_str(), cnf.size(), fx_gate(0), gr); return r.text; }()), "FB-B2 text: save_gate_with_result forged capture gate code 8: text");
static_assert(([]{ const SaveGateInputs si = fx_sg(0, 0, 5, 1, 0, 0, 1, 1, 1, 0); const TextBuf act = fx_action(0); const TextBuf tgt = fx_target(0, FX_ID); const TextBuf cnf = fx_conf(0, FX_ID); ecco_fbcap::GateResult gr{}; gr.code = 9; const SaveGateResult r = save_gate_with_result(si, act.c_str(), act.size(), tgt.c_str(), tgt.size(), cnf.c_str(), cnf.size(), fx_gate(0), gr); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8); }()) == 20, "FB-B2 value: save_gate_with_result forged capture gate code 9: code | arm_off_only << 8");
static_assert(text_is("SAVE REFUSED - Dump to Grid state does not permit saving", []{ const SaveGateInputs si = fx_sg(0, 0, 5, 1, 0, 0, 1, 1, 1, 0); const TextBuf act = fx_action(0); const TextBuf tgt = fx_target(0, FX_ID); const TextBuf cnf = fx_conf(0, FX_ID); ecco_fbcap::GateResult gr{}; gr.code = 9; const SaveGateResult r = save_gate_with_result(si, act.c_str(), act.size(), tgt.c_str(), tgt.size(), cnf.c_str(), cnf.size(), fx_gate(0), gr); return r.text; }()), "FB-B2 text: save_gate_with_result forged capture gate code 9: text");
static_assert(([]{ const SaveGateInputs si = fx_sg(0, 0, 5, 1, 0, 0, 1, 1, 1, 0); const TextBuf act = fx_action(0); const TextBuf tgt = fx_target(0, FX_ID); const TextBuf cnf = fx_conf(0, FX_ID); ecco_fbcap::GateResult gr{}; gr.code = 10; const SaveGateResult r = save_gate_with_result(si, act.c_str(), act.size(), tgt.c_str(), tgt.size(), cnf.c_str(), cnf.size(), fx_gate(0), gr); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8); }()) == 21, "FB-B2 value: save_gate_with_result forged capture gate code 10: code | arm_off_only << 8");
static_assert(text_is("SAVE REFUSED - Register 244 test state does not permit saving", []{ const SaveGateInputs si = fx_sg(0, 0, 5, 1, 0, 0, 1, 1, 1, 0); const TextBuf act = fx_action(0); const TextBuf tgt = fx_target(0, FX_ID); const TextBuf cnf = fx_conf(0, FX_ID); ecco_fbcap::GateResult gr{}; gr.code = 10; const SaveGateResult r = save_gate_with_result(si, act.c_str(), act.size(), tgt.c_str(), tgt.size(), cnf.c_str(), cnf.size(), fx_gate(0), gr); return r.text; }()), "FB-B2 text: save_gate_with_result forged capture gate code 10: text");
static_assert(([]{ const SaveGateInputs si = fx_sg(0, 0, 5, 1, 0, 0, 1, 1, 1, 0); const TextBuf act = fx_action(0); const TextBuf tgt = fx_target(0, FX_ID); const TextBuf cnf = fx_conf(0, FX_ID); ecco_fbcap::GateResult gr{}; gr.code = 11; const SaveGateResult r = save_gate_with_result(si, act.c_str(), act.size(), tgt.c_str(), tgt.size(), cnf.c_str(), cnf.size(), fx_gate(0), gr); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8); }()) == 22, "FB-B2 value: save_gate_with_result forged capture gate code 11: code | arm_off_only << 8");
static_assert(text_is("SAVE REFUSED - Manual TOU state does not permit saving", []{ const SaveGateInputs si = fx_sg(0, 0, 5, 1, 0, 0, 1, 1, 1, 0); const TextBuf act = fx_action(0); const TextBuf tgt = fx_target(0, FX_ID); const TextBuf cnf = fx_conf(0, FX_ID); ecco_fbcap::GateResult gr{}; gr.code = 11; const SaveGateResult r = save_gate_with_result(si, act.c_str(), act.size(), tgt.c_str(), tgt.size(), cnf.c_str(), cnf.size(), fx_gate(0), gr); return r.text; }()), "FB-B2 text: save_gate_with_result forged capture gate code 11: text");
static_assert(([]{ const SaveGateInputs si = fx_sg(0, 0, 5, 1, 0, 0, 1, 1, 1, 0); const TextBuf act = fx_action(0); const TextBuf tgt = fx_target(0, FX_ID); const TextBuf cnf = fx_conf(0, FX_ID); ecco_fbcap::GateResult gr{}; gr.code = 12; const SaveGateResult r = save_gate_with_result(si, act.c_str(), act.size(), tgt.c_str(), tgt.size(), cnf.c_str(), cnf.size(), fx_gate(0), gr); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8); }()) == 0, "FB-B2 value: save_gate_with_result forged capture gate code 12: code | arm_off_only << 8");
static_assert(text_is("SAVE REFUSED - internal: gate state unavailable; nothing written", []{ const SaveGateInputs si = fx_sg(0, 0, 5, 1, 0, 0, 1, 1, 1, 0); const TextBuf act = fx_action(0); const TextBuf tgt = fx_target(0, FX_ID); const TextBuf cnf = fx_conf(0, FX_ID); ecco_fbcap::GateResult gr{}; gr.code = 12; const SaveGateResult r = save_gate_with_result(si, act.c_str(), act.size(), tgt.c_str(), tgt.size(), cnf.c_str(), cnf.size(), fx_gate(0), gr); return r.text; }()), "FB-B2 text: save_gate_with_result forged capture gate code 12: text");
static_assert(([]{ const SaveGateInputs si = fx_sg(0, 0, 5, 1, 0, 0, 1, 1, 1, 0); const TextBuf act = fx_action(0); const TextBuf tgt = fx_target(0, FX_ID); const TextBuf cnf = fx_conf(0, FX_ID); ecco_fbcap::GateResult gr{}; gr.code = 99; const SaveGateResult r = save_gate_with_result(si, act.c_str(), act.size(), tgt.c_str(), tgt.size(), cnf.c_str(), cnf.size(), fx_gate(0), gr); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8); }()) == 0, "FB-B2 value: save_gate_with_result forged capture gate code 99: code | arm_off_only << 8");
static_assert(text_is("SAVE REFUSED - internal: gate state unavailable; nothing written", []{ const SaveGateInputs si = fx_sg(0, 0, 5, 1, 0, 0, 1, 1, 1, 0); const TextBuf act = fx_action(0); const TextBuf tgt = fx_target(0, FX_ID); const TextBuf cnf = fx_conf(0, FX_ID); ecco_fbcap::GateResult gr{}; gr.code = 99; const SaveGateResult r = save_gate_with_result(si, act.c_str(), act.size(), tgt.c_str(), tgt.size(), cnf.c_str(), cnf.size(), fx_gate(0), gr); return r.text; }()), "FB-B2 text: save_gate_with_result forged capture gate code 99: text");
static_assert(([]{ const SaveGateInputs si = fx_sg(0, 0, 5, 1, 0, 0, 1, 1, 1, 0); const TextBuf act = fx_action(0); const TextBuf tgt = fx_target(0, FX_ID); const TextBuf cnf = fx_conf(0, FX_ID); ecco_fbcap::GateResult gr{}; gr.code = 255; const SaveGateResult r = save_gate_with_result(si, act.c_str(), act.size(), tgt.c_str(), tgt.size(), cnf.c_str(), cnf.size(), fx_gate(0), gr); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8); }()) == 0, "FB-B2 value: save_gate_with_result forged capture gate code 255: code | arm_off_only << 8");
static_assert(text_is("SAVE REFUSED - internal: gate state unavailable; nothing written", []{ const SaveGateInputs si = fx_sg(0, 0, 5, 1, 0, 0, 1, 1, 1, 0); const TextBuf act = fx_action(0); const TextBuf tgt = fx_target(0, FX_ID); const TextBuf cnf = fx_conf(0, FX_ID); ecco_fbcap::GateResult gr{}; gr.code = 255; const SaveGateResult r = save_gate_with_result(si, act.c_str(), act.size(), tgt.c_str(), tgt.size(), cnf.c_str(), cnf.size(), fx_gate(0), gr); return r.text; }()), "FB-B2 text: save_gate_with_result forged capture gate code 255: text");
static_assert(([]{ const SaveGateInputs si = fx_sg(0, 0, 5, 1, 0, 0, 1, 1, 1, 0); const TextBuf act = fx_action(0); const TextBuf tgt = fx_target(0, FX_ID); const TextBuf cnf = fx_conf(0, FX_ID); ecco_fbcap::GateResult gr{}; gr.code = ecco_fbcap::GATE_REFUSE_MTOU; gr.mtou = ecco_fbcap::SlotClass{ecco_fbcap::UNK_NOT_PROBED, ecco_fbcap::BASIS_NONE}; const SaveGateResult r = save_gate_with_result(si, act.c_str(), act.size(), tgt.c_str(), tgt.size(), cnf.c_str(), cnf.size(), fx_gate(0), gr); return r.code; }()) == 22, "FB-B2 value: save_gate_with_result: an MTOU slot refusal is SG_MTOU");
static_assert(text_is("SAVE REFUSED - Manual TOU state does not permit saving", []{ const SaveGateInputs si = fx_sg(0, 0, 5, 1, 0, 0, 1, 1, 1, 0); const TextBuf act = fx_action(0); const TextBuf tgt = fx_target(0, FX_ID); const TextBuf cnf = fx_conf(0, FX_ID); ecco_fbcap::GateResult gr{}; gr.code = ecco_fbcap::GATE_REFUSE_MTOU; gr.mtou = ecco_fbcap::SlotClass{ecco_fbcap::UNK_NOT_PROBED, ecco_fbcap::BASIS_NONE}; const SaveGateResult r = save_gate_with_result(si, act.c_str(), act.size(), tgt.c_str(), tgt.size(), cnf.c_str(), cnf.size(), fx_gate(0), gr); return r.text; }()), "FB-B2 text: save_gate_with_result: an MTOU slot refusal text");
static_assert(([]{ const SaveGateResult r = save_in_flight_gate(false, false); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8); }()) == 0, "FB-B2 value: save_in_flight_gate op=0 dispatch=0: code | arm_off_only << 8");
static_assert(text_is("", save_in_flight_gate(false, false).text), "FB-B2 text: save_in_flight_gate op=0 dispatch=0: text");
static_assert(([]{ const InvalidateGateResult r = invalidate_in_flight_gate(false, false); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8); }()) == 0, "FB-B2 value: invalidate_in_flight_gate op=0 dispatch=0: code | arm_off_only << 8");
static_assert(text_is("", invalidate_in_flight_gate(false, false).text), "FB-B2 text: invalidate_in_flight_gate op=0 dispatch=0: text");
static_assert(([]{ const SaveGateResult r = save_in_flight_gate(true, false); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8); }()) == 258, "FB-B2 value: save_in_flight_gate op=1 dispatch=0: code | arm_off_only << 8");
static_assert(text_is("SAVE REFUSED - another Fallback Profile operation is in progress", save_in_flight_gate(true, false).text), "FB-B2 text: save_in_flight_gate op=1 dispatch=0: text");
static_assert(([]{ const InvalidateGateResult r = invalidate_in_flight_gate(true, false); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8); }()) == 258, "FB-B2 value: invalidate_in_flight_gate op=1 dispatch=0: code | arm_off_only << 8");
static_assert(text_is("INVALIDATE REFUSED - another Fallback Profile operation is in progress", invalidate_in_flight_gate(true, false).text), "FB-B2 text: invalidate_in_flight_gate op=1 dispatch=0: text");
static_assert(([]{ const SaveGateResult r = save_in_flight_gate(false, true); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8); }()) == 258, "FB-B2 value: save_in_flight_gate op=0 dispatch=1: code | arm_off_only << 8");
static_assert(text_is("SAVE REFUSED - another Fallback Profile operation is in progress", save_in_flight_gate(false, true).text), "FB-B2 text: save_in_flight_gate op=0 dispatch=1: text");
static_assert(([]{ const InvalidateGateResult r = invalidate_in_flight_gate(false, true); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8); }()) == 258, "FB-B2 value: invalidate_in_flight_gate op=0 dispatch=1: code | arm_off_only << 8");
static_assert(text_is("INVALIDATE REFUSED - another Fallback Profile operation is in progress", invalidate_in_flight_gate(false, true).text), "FB-B2 text: invalidate_in_flight_gate op=0 dispatch=1: text");
static_assert(([]{ const SaveGateResult r = save_in_flight_gate(true, true); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8); }()) == 258, "FB-B2 value: save_in_flight_gate op=1 dispatch=1: code | arm_off_only << 8");
static_assert(text_is("SAVE REFUSED - another Fallback Profile operation is in progress", save_in_flight_gate(true, true).text), "FB-B2 text: save_in_flight_gate op=1 dispatch=1: text");
static_assert(([]{ const InvalidateGateResult r = invalidate_in_flight_gate(true, true); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8); }()) == 258, "FB-B2 value: invalidate_in_flight_gate op=1 dispatch=1: code | arm_off_only << 8");
static_assert(text_is("INVALIDATE REFUSED - another Fallback Profile operation is in progress", invalidate_in_flight_gate(true, true).text), "FB-B2 text: invalidate_in_flight_gate op=1 dispatch=1: text");
static_assert(((save_gate_decide(fx_sg(0, 0, 5, 1, 0, 0, 1, 1, 1, 0), "SAVE", 4, "0123456789ABCDEF", 16, "SAVE 0123456789ABCDEF", 21, fx_gate(0))).code) == 1, "FB-B2 value: save_gate_decide direct [accept]: code");
static_assert(text_is("", (save_gate_decide(fx_sg(0, 0, 5, 1, 0, 0, 1, 1, 1, 0), "SAVE", 4, "0123456789ABCDEF", 16, "SAVE 0123456789ABCDEF", 21, fx_gate(0))).text), "FB-B2 text: save_gate_decide direct [accept]: text");
static_assert(((save_gate_decide(fx_sg(0, 0, 5, 1, 0, 0, 1, 1, 1, 0), "save", 4, "0123456789ABCDEF", 16, "SAVE 0123456789ABCDEF", 21, fx_gate(0))).code) == 3, "FB-B2 value: save_gate_decide direct [a lower-case action]: code");
static_assert(text_is("REFUSED - unsupported action 'save'", (save_gate_decide(fx_sg(0, 0, 5, 1, 0, 0, 1, 1, 1, 0), "save", 4, "0123456789ABCDEF", 16, "SAVE 0123456789ABCDEF", 21, fx_gate(0))).text), "FB-B2 text: save_gate_decide direct [a lower-case action]: text");
static_assert(((save_gate_decide(fx_sg(0, 0, 5, 1, 0, 0, 1, 1, 1, 0), "SAVE", 4, "0123456789abcdef", 16, "SAVE 0123456789ABCDEF", 21, fx_gate(0))).code) == 7, "FB-B2 value: save_gate_decide direct [a lower-case target]: code");
static_assert(text_is("SAVE REFUSED - candidate ID must be 16 hex characters", (save_gate_decide(fx_sg(0, 0, 5, 1, 0, 0, 1, 1, 1, 0), "SAVE", 4, "0123456789abcdef", 16, "SAVE 0123456789ABCDEF", 21, fx_gate(0))).text), "FB-B2 text: save_gate_decide direct [a lower-case target]: text");
static_assert(((save_gate_decide(fx_sg(0, 0, 5, 1, 0, 0, 1, 1, 1, 0), "SAVE", 4, "0123456789ABCDEF", 16, "SAVE 0123456789ABCDE0", 21, fx_gate(0))).code) == 9, "FB-B2 value: save_gate_decide direct [a wrong phrase]: code");
static_assert(text_is("SAVE REFUSED - confirmation phrase mismatch (expected 'SAVE 0123456789ABCDEF')", (save_gate_decide(fx_sg(0, 0, 5, 1, 0, 0, 1, 1, 1, 0), "SAVE", 4, "0123456789ABCDEF", 16, "SAVE 0123456789ABCDE0", 21, fx_gate(0))).text), "FB-B2 text: save_gate_decide direct [a wrong phrase]: text");
static_assert(((save_gate_decide(fx_sg(0, 0, 5, 1, 0, 0, 1, 1, 1, 0), "SAVE", 4, "0123456789ABCDEF", 16, "SAVE 0123456789ABCDE", 20, fx_gate(0))).code) == 9, "FB-B2 value: save_gate_decide direct [a phrase cut short]: code");
static_assert(text_is("SAVE REFUSED - confirmation phrase mismatch (expected 'SAVE 0123456789ABCDEF')", (save_gate_decide(fx_sg(0, 0, 5, 1, 0, 0, 1, 1, 1, 0), "SAVE", 4, "0123456789ABCDEF", 16, "SAVE 0123456789ABCDE", 20, fx_gate(0))).text), "FB-B2 text: save_gate_decide direct [a phrase cut short]: text");
static_assert(((save_gate_decide(fx_sg(0, 0, 5, 1, 0, 0, 1, 1, 1, 0), "SAVE", 4, "0123456789ABCDEF", 16, "SAVE 0123456789ABCDEF\000", 22, fx_gate(0))).code) == 9, "FB-B2 value: save_gate_decide direct [a phrase with a trailing NUL]: code");
static_assert(text_is("SAVE REFUSED - confirmation phrase mismatch (expected 'SAVE 0123456789ABCDEF')", (save_gate_decide(fx_sg(0, 0, 5, 1, 0, 0, 1, 1, 1, 0), "SAVE", 4, "0123456789ABCDEF", 16, "SAVE 0123456789ABCDEF\000", 22, fx_gate(0))).text), "FB-B2 text: save_gate_decide direct [a phrase with a trailing NUL]: text");
static_assert(((save_gate_decide(fx_sg(0, 0, 5, 1, 0, 0, 1, 1, 1, 0), "RESTORE", 7, "0123456789ABCDEF", 16, "SAVE 0123456789ABCDEF", 21, fx_gate(0))).code) == 3, "FB-B2 value: save_gate_decide direct [RESTORE]: code");
static_assert(text_is("RESTORE REFUSED - not implemented in this firmware", (save_gate_decide(fx_sg(0, 0, 5, 1, 0, 0, 1, 1, 1, 0), "RESTORE", 7, "0123456789ABCDEF", 16, "SAVE 0123456789ABCDEF", 21, fx_gate(0))).text), "FB-B2 text: save_gate_decide direct [RESTORE]: text");
static_assert(((save_gate_decide(fx_sg(0, 0, 5, 1, 0, 0, 1, 1, 1, 0), "f" "ailed", 6, "0123456789ABCDEF", 16, "SAVE 0123456789ABCDEF", 21, fx_gate(0))).code) == 3, "FB-B2 value: save_gate_decide direct [a hazard action A]: code");
static_assert(text_is("REFUSED - unsupported action '\?\?\?\?ed'", (save_gate_decide(fx_sg(0, 0, 5, 1, 0, 0, 1, 1, 1, 0), "f" "ailed", 6, "0123456789ABCDEF", 16, "SAVE 0123456789ABCDEF", 21, fx_gate(0))).text), "FB-B2 text: save_gate_decide direct [a hazard action A]: text");
static_assert(((save_gate_decide(fx_sg(0, 0, 5, 1, 0, 0, 1, 1, 1, 0), "D" "EFERRED", 8, "0123456789ABCDEF", 16, "SAVE 0123456789ABCDEF", 21, fx_gate(0))).code) == 3, "FB-B2 value: save_gate_decide direct [a hazard action B]: code");
static_assert(text_is("REFUSED - unsupported action '\?\?\?\?\?RED'", (save_gate_decide(fx_sg(0, 0, 5, 1, 0, 0, 1, 1, 1, 0), "D" "EFERRED", 8, "0123456789ABCDEF", 16, "SAVE 0123456789ABCDEF", 21, fx_gate(0))).text), "FB-B2 text: save_gate_decide direct [a hazard action B]: text");
static_assert(((save_gate_decide(fx_sg(0, 0, 5, 1, 0, 0, 1, 1, 1, 0), "xF" "aIlD" "eFeRx", 11, "0123456789ABCDEF", 16, "SAVE 0123456789ABCDEF", 21, fx_gate(0))).code) == 3, "FB-B2 value: save_gate_decide direct [a hazard action C]: code");
static_assert(text_is("REFUSED - unsupported action 'x\?\?\?\?\?\?\?\?\?x'", (save_gate_decide(fx_sg(0, 0, 5, 1, 0, 0, 1, 1, 1, 0), "xF" "aIlD" "eFeRx", 11, "0123456789ABCDEF", 16, "SAVE 0123456789ABCDEF", 21, fx_gate(0))).text), "FB-B2 text: save_gate_decide direct [a hazard action C]: text");
static_assert(((save_gate_decide(fx_sg(0, 0, 5, 1, 0, 0, 1, 1, 1, 0), "xxxxxxxxxxxxxxxxxxxxxxxd" "eferred", 31, "0123456789ABCDEF", 16, "SAVE 0123456789ABCDEF", 21, fx_gate(0))).code) == 3, "FB-B2 value: save_gate_decide direct [a hazard action D (long, cut)]: code");
static_assert(text_is("REFUSED - unsupported action 'xxxxxxxxxxxxxxxxxxxxxxx\?'", (save_gate_decide(fx_sg(0, 0, 5, 1, 0, 0, 1, 1, 1, 0), "xxxxxxxxxxxxxxxxxxxxxxxd" "eferred", 31, "0123456789ABCDEF", 16, "SAVE 0123456789ABCDEF", 21, fx_gate(0))).text), "FB-B2 text: save_gate_decide direct [a hazard action D (long, cut)]: text");
static_assert(((invalidate_gate_decide(fx_ig(IG_CASES[0]), "INVALIDATE", 10, "D852A4FA2DF7DBA3", 16, "INVALIDATE D852A4FA2DF7DBA3", 27)).code) == 1, "FB-B2 value: invalidate_gate_decide direct [accept]: code");
static_assert(text_is("", (invalidate_gate_decide(fx_ig(IG_CASES[0]), "INVALIDATE", 10, "D852A4FA2DF7DBA3", 16, "INVALIDATE D852A4FA2DF7DBA3", 27)).text), "FB-B2 text: invalidate_gate_decide direct [accept]: text");
static_assert(((invalidate_gate_decide(fx_ig(IG_CASES[0]), "SAVE", 4, "D852A4FA2DF7DBA3", 16, "INVALIDATE D852A4FA2DF7DBA3", 27)).code) == 3, "FB-B2 value: invalidate_gate_decide direct [SAVE]: code");
static_assert(text_is("REFUSED - unsupported action 'SAVE'", (invalidate_gate_decide(fx_ig(IG_CASES[0]), "SAVE", 4, "D852A4FA2DF7DBA3", 16, "INVALIDATE D852A4FA2DF7DBA3", 27)).text), "FB-B2 text: invalidate_gate_decide direct [SAVE]: text");
static_assert(((invalidate_gate_decide(fx_ig(IG_CASES[0]), "INVALIDATE", 10, "D852A4FA2DF7DBA3", 16, "SAVE D852A4FA2DF7DBA3", 21)).code) == 6, "FB-B2 value: invalidate_gate_decide direct [the SAVE phrase]: code");
static_assert(text_is("INVALIDATE REFUSED - confirmation phrase mismatch (expected 'INVALIDATE D852A4FA2DF7DBA3')", (invalidate_gate_decide(fx_ig(IG_CASES[0]), "INVALIDATE", 10, "D852A4FA2DF7DBA3", 16, "SAVE D852A4FA2DF7DBA3", 21)).text), "FB-B2 text: invalidate_gate_decide direct [the SAVE phrase]: text");
static_assert(((invalidate_gate_decide(fx_ig(IG_CASES[0]), "INVALIDATE", 10, "d852a4fa2df7dba3", 16, "INVALIDATE d852a4fa2df7dba3", 27)).code) == 5, "FB-B2 value: invalidate_gate_decide direct [a lower-case target]: code");
static_assert(text_is("INVALIDATE REFUSED - profile ID must be 16 hex characters", (invalidate_gate_decide(fx_ig(IG_CASES[0]), "INVALIDATE", 10, "d852a4fa2df7dba3", 16, "INVALIDATE d852a4fa2df7dba3", 27)).text), "FB-B2 text: invalidate_gate_decide direct [a lower-case target]: text");
static_assert(((invalidate_gate_decide(fx_ig(IG_CASES[0]), "INVALIDATE", 10, "D852A4FA2DF7DBA3", 16, "INVALIDATE D852A4FA2DF7DBA3\000", 28)).code) == 6, "FB-B2 value: invalidate_gate_decide direct [a phrase with a trailing NUL]: code");
static_assert(text_is("INVALIDATE REFUSED - confirmation phrase mismatch (expected 'INVALIDATE D852A4FA2DF7DBA3')", (invalidate_gate_decide(fx_ig(IG_CASES[0]), "INVALIDATE", 10, "D852A4FA2DF7DBA3", 16, "INVALIDATE D852A4FA2DF7DBA3\000", 28)).text), "FB-B2 text: invalidate_gate_decide direct [a phrase with a trailing NUL]: text");
static_assert(((invalidate_gate_decide(fx_ig(IG_CASES[0]), "F" "AILED", 6, "D852A4FA2DF7DBA3", 16, "INVALIDATE D852A4FA2DF7DBA3", 27)).code) == 3, "FB-B2 value: invalidate_gate_decide direct [a hazard action A]: code");
static_assert(text_is("REFUSED - unsupported action '\?\?\?\?ED'", (invalidate_gate_decide(fx_ig(IG_CASES[0]), "F" "AILED", 6, "D852A4FA2DF7DBA3", 16, "INVALIDATE D852A4FA2DF7DBA3", 27)).text), "FB-B2 text: invalidate_gate_decide direct [a hazard action A]: text");
static_assert(((invalidate_gate_decide(fx_ig(IG_CASES[0]), "d" "eferred", 8, "D852A4FA2DF7DBA3", 16, "INVALIDATE D852A4FA2DF7DBA3", 27)).code) == 3, "FB-B2 value: invalidate_gate_decide direct [a hazard action B]: code");
static_assert(text_is("REFUSED - unsupported action '\?\?\?\?\?red'", (invalidate_gate_decide(fx_ig(IG_CASES[0]), "d" "eferred", 8, "D852A4FA2DF7DBA3", 16, "INVALIDATE D852A4FA2DF7DBA3", 27)).text), "FB-B2 text: invalidate_gate_decide direct [a hazard action B]: text");
static_assert(((invalidate_gate_decide(fx_ig(IG_CASES[0]), "xxxxxxxxxxxxxxxxxxxxxf" "ailed", 27, "D852A4FA2DF7DBA3", 16, "INVALIDATE D852A4FA2DF7DBA3", 27)).code) == 3, "FB-B2 value: invalidate_gate_decide direct [a hazard action C (long, cut)]: code");
static_assert(text_is("REFUSED - unsupported action 'xxxxxxxxxxxxxxxxxxxxx\?\?\?'", (invalidate_gate_decide(fx_ig(IG_CASES[0]), "xxxxxxxxxxxxxxxxxxxxxf" "ailed", 27, "D852A4FA2DF7DBA3", 16, "INVALIDATE D852A4FA2DF7DBA3", 27)).text), "FB-B2 text: invalidate_gate_decide direct [a hazard action C (long, cut)]: text");
static_assert(text_is("SAVE REFUSED - Register 244 test is active; live settings are a temporary overlay - end it first", save_slot_refusal_text(ecco_fbcap::SLOT_R244, ecco_fbcap::SlotClass{ecco_fbcap::OBL_ACTIVE, ecco_fbcap::BASIS_LEASE}, 0, "x", 0u)), "FB-B2 text: save_slot_refusal_text SLOT_R244 OBL_ACTIVE BASIS_LEASE");
static_assert(text_is("SAVE REFUSED - a failback episode record exists; only the firmware that created it can resolve it", save_slot_refusal_text(ecco_fbcap::SLOT_R244, ecco_fbcap::SlotClass{ecco_fbcap::OBL_ACTIVE, ecco_fbcap::BASIS_FBS_EPISODE}, 0, "x", 0u)), "FB-B2 text: save_slot_refusal_text SLOT_R244 OBL_ACTIVE BASIS_FBS_EPISODE");
static_assert(text_is("SAVE REFUSED - a Register 244 test start is in progress; live settings are about to become a temporary overlay", save_slot_refusal_text(ecco_fbcap::SLOT_R244, ecco_fbcap::SlotClass{ecco_fbcap::OBL_STARTING, ecco_fbcap::BASIS_PRE_COMMIT}, 0, "x", 0u)), "FB-B2 text: save_slot_refusal_text SLOT_R244 OBL_STARTING BASIS_PRE_COMMIT");
static_assert(text_is("SAVE REFUSED - a Register 244 test start is in progress; live settings are about to become a temporary overlay", save_slot_refusal_text(ecco_fbcap::SLOT_R244, ecco_fbcap::SlotClass{ecco_fbcap::OBL_STARTING, ecco_fbcap::BASIS_COMMITTED}, 0, "x", 0u)), "FB-B2 text: save_slot_refusal_text SLOT_R244 OBL_STARTING BASIS_COMMITTED");
static_assert(text_is("SAVE REFUSED - Register 244 test must restore original settings first", save_slot_refusal_text(ecco_fbcap::SLOT_R244, ecco_fbcap::SlotClass{ecco_fbcap::OBL_RESTORE_REQUIRED, ecco_fbcap::BASIS_NONE}, 0, "x", 0u)), "FB-B2 text: save_slot_refusal_text SLOT_R244 OBL_RESTORE_REQUIRED BASIS_NONE");
static_assert(text_is("SAVE REFUSED - Register 244 test restore verified; durable clear still pending - press Restore Original (armed)", save_slot_refusal_text(ecco_fbcap::SLOT_R244, ecco_fbcap::SlotClass{ecco_fbcap::OBL_PENDING_CLEAR, ecco_fbcap::BASIS_NONE}, 0, "x", 0u)), "FB-B2 text: save_slot_refusal_text SLOT_R244 OBL_PENDING_CLEAR BASIS_NONE");
static_assert(text_is("SAVE REFUSED - a Register 244 test restore or recovery action is running; try again when it finishes", save_slot_refusal_text(ecco_fbcap::SLOT_R244, ecco_fbcap::SlotClass{ecco_fbcap::OBL_ENDING, ecco_fbcap::BASIS_OPERATOR_ACTION_RUNNING}, 0, "x", 0u)), "FB-B2 text: save_slot_refusal_text SLOT_R244 OBL_ENDING BASIS_OPERATOR_ACTION_RUNNING");
static_assert(text_is("SAVE REFUSED - a Register 244 test restore or recovery action is running; try again when it finishes", save_slot_refusal_text(ecco_fbcap::SLOT_R244, ecco_fbcap::SlotClass{ecco_fbcap::OBL_ENDING, ecco_fbcap::BASIS_RESTORE_RUNNING}, 0, "x", 0u)), "FB-B2 text: save_slot_refusal_text SLOT_R244 OBL_ENDING BASIS_RESTORE_RUNNING");
static_assert(text_is("SAVE REFUSED - Register 244 test needs an operator recovery action first", save_slot_refusal_text(ecco_fbcap::SLOT_R244, ecco_fbcap::SlotClass{ecco_fbcap::OBL_OPERATOR_NEEDED, ecco_fbcap::BASIS_NONE}, 0, "x", 0u)), "FB-B2 text: save_slot_refusal_text SLOT_R244 OBL_OPERATOR_NEEDED BASIS_NONE");
static_assert(text_is("SAVE REFUSED - Register 244 test recovery state UNKNOWN since boot (marker unreadable); an obligation cannot be ruled out; Fallback never proceeds past it", save_slot_refusal_text(ecco_fbcap::SLOT_R244, ecco_fbcap::SlotClass{ecco_fbcap::UNK_DURABLE_UNREADABLE, ecco_fbcap::BASIS_BOOT_READ_ERROR}, 0, "x", 0u)), "FB-B2 text: save_slot_refusal_text SLOT_R244 UNK_DURABLE_UNREADABLE BASIS_BOOT_READ_ERROR");
static_assert(text_is("SAVE REFUSED - Register 244 test recovery marker became unreadable at runtime; saving blocked until reboot. After reboot it may read absent: verify live settings first; do not erase NVS", save_slot_refusal_text(ecco_fbcap::SLOT_R244, ecco_fbcap::SlotClass{ecco_fbcap::UNK_DURABLE_UNREADABLE, ecco_fbcap::BASIS_RUNTIME_PROBE}, 0, "x", 0u)), "FB-B2 text: save_slot_refusal_text SLOT_R244 UNK_DURABLE_UNREADABLE BASIS_RUNTIME_PROBE");
static_assert(text_is("SAVE REFUSED - Register 244 test recovery metadata is CORRUPT (hard lockout); Fallback never overwrites or proceeds past it; do not erase NVS", save_slot_refusal_text(ecco_fbcap::SLOT_R244, ecco_fbcap::SlotClass{ecco_fbcap::UNK_METADATA_CORRUPT, ecco_fbcap::BASIS_BOOT_LOCKOUT}, 0, "x", 0u)), "FB-B2 text: save_slot_refusal_text SLOT_R244 UNK_METADATA_CORRUPT BASIS_BOOT_LOCKOUT");
static_assert(text_is("SAVE REFUSED - Register 244 test recovery marker is malformed (found at runtime); saving blocked until reboot, which re-derives it as a hard lockout", save_slot_refusal_text(ecco_fbcap::SLOT_R244, ecco_fbcap::SlotClass{ecco_fbcap::UNK_METADATA_CORRUPT, ecco_fbcap::BASIS_RUNTIME_PROBE}, 0, "x", 0u)), "FB-B2 text: save_slot_refusal_text SLOT_R244 UNK_METADATA_CORRUPT BASIS_RUNTIME_PROBE");
static_assert(text_is("SAVE REFUSED - durable state not loaded yet", save_slot_refusal_text(ecco_fbcap::SLOT_R244, ecco_fbcap::SlotClass{ecco_fbcap::UNK_BOOT_NOT_LOADED, ecco_fbcap::BASIS_NONE}, 0, "x", 0u)), "FB-B2 text: save_slot_refusal_text SLOT_R244 UNK_BOOT_NOT_LOADED BASIS_NONE");
static_assert(text_is("SAVE REFUSED - Register 244 test stored marker says RESTORE_REQUIRED but memory says clear; saving blocked until reboot, which re-derives it (the domain may then restore its saved original)", save_slot_refusal_text(ecco_fbcap::SLOT_R244, ecco_fbcap::SlotClass{ecco_fbcap::UNK_DIVERGED, ecco_fbcap::BASIS_GHOST_RR}, 0, "x", 0u)), "FB-B2 text: save_slot_refusal_text SLOT_R244 UNK_DIVERGED BASIS_GHOST_RR");
static_assert(text_is("SAVE REFUSED - Register 244 test stored marker says PENDING_CLEAR but memory says clear; saving blocked until reboot, which re-derives it (the domain may then restore its saved original)", save_slot_refusal_text(ecco_fbcap::SLOT_R244, ecco_fbcap::SlotClass{ecco_fbcap::UNK_DIVERGED, ecco_fbcap::BASIS_GHOST_PC}, 0, "x", 0u)), "FB-B2 text: save_slot_refusal_text SLOT_R244 UNK_DIVERGED BASIS_GHOST_PC");
static_assert(text_is("SAVE REFUSED - Register 244 test in-memory recovery state is inconsistent; a reboot must re-derive it before saving", save_slot_refusal_text(ecco_fbcap::SLOT_R244, ecco_fbcap::SlotClass{ecco_fbcap::UNK_DIVERGED, ecco_fbcap::BASIS_RAM_INCONSISTENT}, 0, "x", 0u)), "FB-B2 text: save_slot_refusal_text SLOT_R244 UNK_DIVERGED BASIS_RAM_INCONSISTENT");
static_assert(text_is("SAVE REFUSED - Register 244 test in-progress flag is set with no running operation (possible leak); a reboot re-derives it", save_slot_refusal_text(ecco_fbcap::SLOT_R244, ecco_fbcap::SlotClass{ecco_fbcap::UNK_BUS_OR_LOCK_STUCK, ecco_fbcap::BASIS_OP_FLAG_UNATTRIBUTED}, 0, "x", 0u)), "FB-B2 text: save_slot_refusal_text SLOT_R244 UNK_BUS_OR_LOCK_STUCK BASIS_OP_FLAG_UNATTRIBUTED");
static_assert(text_is("SAVE REFUSED - Register 244 test state does not permit saving", save_slot_refusal_text(ecco_fbcap::SLOT_R244, ecco_fbcap::SlotClass{ecco_fbcap::UNK_NOT_PROBED, ecco_fbcap::BASIS_NONE}, 0, "x", 0u)), "FB-B2 text: save_slot_refusal_text SLOT_R244 UNK_NOT_PROBED BASIS_NONE");
static_assert(text_is("SAVE REFUSED - Register 244 test state does not permit saving", save_slot_refusal_text(ecco_fbcap::SLOT_R244, ecco_fbcap::SlotClass{ecco_fbcap::OBL_CLEAR_PROVEN, ecco_fbcap::BASIS_NONE}, 0, "x", 0u)), "FB-B2 text: save_slot_refusal_text SLOT_R244 OBL_CLEAR_PROVEN BASIS_NONE");
static_assert(text_is("SAVE REFUSED - Register 244 test state does not permit saving", save_slot_refusal_text(ecco_fbcap::SLOT_R244, ecco_fbcap::SlotClass{ecco_fbcap::OBL_UNSET, ecco_fbcap::BASIS_NONE}, 0, "x", 0u)), "FB-B2 text: save_slot_refusal_text SLOT_R244 OBL_UNSET BASIS_NONE");
static_assert(text_is("SAVE REFUSED - Free Power is active; live settings are a temporary overlay - end it first", save_slot_refusal_text(ecco_fbcap::SLOT_FP, ecco_fbcap::SlotClass{ecco_fbcap::OBL_ACTIVE, ecco_fbcap::BASIS_LEASE}, 0, "x", 0u)), "FB-B2 text: save_slot_refusal_text SLOT_FP OBL_ACTIVE BASIS_LEASE");
static_assert(text_is("SAVE REFUSED - a failback episode record exists; only the firmware that created it can resolve it", save_slot_refusal_text(ecco_fbcap::SLOT_FP, ecco_fbcap::SlotClass{ecco_fbcap::OBL_ACTIVE, ecco_fbcap::BASIS_FBS_EPISODE}, 0, "x", 0u)), "FB-B2 text: save_slot_refusal_text SLOT_FP OBL_ACTIVE BASIS_FBS_EPISODE");
static_assert(text_is("SAVE REFUSED - a Free Power start is in progress; live settings are about to become a temporary overlay", save_slot_refusal_text(ecco_fbcap::SLOT_FP, ecco_fbcap::SlotClass{ecco_fbcap::OBL_STARTING, ecco_fbcap::BASIS_PRE_COMMIT}, 0, "x", 0u)), "FB-B2 text: save_slot_refusal_text SLOT_FP OBL_STARTING BASIS_PRE_COMMIT");
static_assert(text_is("SAVE REFUSED - Free Power restore verified; durable clear still pending", save_slot_refusal_text(ecco_fbcap::SLOT_FP, ecco_fbcap::SlotClass{ecco_fbcap::OBL_PENDING_CLEAR, ecco_fbcap::BASIS_NONE}, 0, "x", 0u)), "FB-B2 text: save_slot_refusal_text SLOT_FP OBL_PENDING_CLEAR BASIS_NONE");
static_assert(text_is("SAVE REFUSED - Free Power recovery state UNKNOWN since boot (marker unreadable); an obligation cannot be ruled out; Fallback never proceeds past it", save_slot_refusal_text(ecco_fbcap::SLOT_FP, ecco_fbcap::SlotClass{ecco_fbcap::UNK_DURABLE_UNREADABLE, ecco_fbcap::BASIS_BOOT_READ_ERROR}, 0, "x", 0u)), "FB-B2 text: save_slot_refusal_text SLOT_FP UNK_DURABLE_UNREADABLE BASIS_BOOT_READ_ERROR");
static_assert(text_is("SAVE REFUSED - Free Power recovery metadata is CORRUPT (hard lockout); Fallback never overwrites or proceeds past it; do not erase NVS", save_slot_refusal_text(ecco_fbcap::SLOT_FP, ecco_fbcap::SlotClass{ecco_fbcap::UNK_METADATA_CORRUPT, ecco_fbcap::BASIS_BOOT_LOCKOUT}, 0, "x", 0u)), "FB-B2 text: save_slot_refusal_text SLOT_FP UNK_METADATA_CORRUPT BASIS_BOOT_LOCKOUT");
static_assert(text_is("SAVE REFUSED - durable state not loaded yet", save_slot_refusal_text(ecco_fbcap::SLOT_FP, ecco_fbcap::SlotClass{ecco_fbcap::UNK_BOOT_NOT_LOADED, ecco_fbcap::BASIS_NONE}, 0, "x", 0u)), "FB-B2 text: save_slot_refusal_text SLOT_FP UNK_BOOT_NOT_LOADED BASIS_NONE");
static_assert(text_is("SAVE REFUSED - Free Power state does not permit saving", save_slot_refusal_text(ecco_fbcap::SLOT_FP, ecco_fbcap::SlotClass{ecco_fbcap::OBL_UNSET, ecco_fbcap::BASIS_NONE}, 0, "x", 0u)), "FB-B2 text: save_slot_refusal_text SLOT_FP OBL_UNSET BASIS_NONE");
static_assert(text_is("SAVE REFUSED - Dump to Grid is active; live settings are a temporary overlay - end it first", save_slot_refusal_text(ecco_fbcap::SLOT_DUMP, ecco_fbcap::SlotClass{ecco_fbcap::OBL_ACTIVE, ecco_fbcap::BASIS_LEASE}, 0, "x", 0u)), "FB-B2 text: save_slot_refusal_text SLOT_DUMP OBL_ACTIVE BASIS_LEASE");
static_assert(text_is("SAVE REFUSED - a failback episode record exists; only the firmware that created it can resolve it", save_slot_refusal_text(ecco_fbcap::SLOT_DUMP, ecco_fbcap::SlotClass{ecco_fbcap::OBL_ACTIVE, ecco_fbcap::BASIS_FBS_EPISODE}, 0, "x", 0u)), "FB-B2 text: save_slot_refusal_text SLOT_DUMP OBL_ACTIVE BASIS_FBS_EPISODE");
static_assert(text_is("SAVE REFUSED - a Dump to Grid start is in progress; live settings are about to become a temporary overlay", save_slot_refusal_text(ecco_fbcap::SLOT_DUMP, ecco_fbcap::SlotClass{ecco_fbcap::OBL_STARTING, ecco_fbcap::BASIS_PRE_COMMIT}, 0, "x", 0u)), "FB-B2 text: save_slot_refusal_text SLOT_DUMP OBL_STARTING BASIS_PRE_COMMIT");
static_assert(text_is("SAVE REFUSED - a Dump to Grid start is in progress; live settings are about to become a temporary overlay", save_slot_refusal_text(ecco_fbcap::SLOT_DUMP, ecco_fbcap::SlotClass{ecco_fbcap::OBL_STARTING, ecco_fbcap::BASIS_COMMITTED}, 0, "x", 0u)), "FB-B2 text: save_slot_refusal_text SLOT_DUMP OBL_STARTING BASIS_COMMITTED");
static_assert(text_is("SAVE REFUSED - Dump to Grid must restore original settings first", save_slot_refusal_text(ecco_fbcap::SLOT_DUMP, ecco_fbcap::SlotClass{ecco_fbcap::OBL_RESTORE_REQUIRED, ecco_fbcap::BASIS_NONE}, 0, "x", 0u)), "FB-B2 text: save_slot_refusal_text SLOT_DUMP OBL_RESTORE_REQUIRED BASIS_NONE");
static_assert(text_is("SAVE REFUSED - Dump to Grid restore verified; durable clear still pending", save_slot_refusal_text(ecco_fbcap::SLOT_DUMP, ecco_fbcap::SlotClass{ecco_fbcap::OBL_PENDING_CLEAR, ecco_fbcap::BASIS_NONE}, 0, "x", 0u)), "FB-B2 text: save_slot_refusal_text SLOT_DUMP OBL_PENDING_CLEAR BASIS_NONE");
static_assert(text_is("SAVE REFUSED - a Dump to Grid restore or recovery action is running; try again when it finishes", save_slot_refusal_text(ecco_fbcap::SLOT_DUMP, ecco_fbcap::SlotClass{ecco_fbcap::OBL_ENDING, ecco_fbcap::BASIS_OPERATOR_ACTION_RUNNING}, 0, "x", 0u)), "FB-B2 text: save_slot_refusal_text SLOT_DUMP OBL_ENDING BASIS_OPERATOR_ACTION_RUNNING");
static_assert(text_is("SAVE REFUSED - a Dump to Grid restore or recovery action is running; try again when it finishes", save_slot_refusal_text(ecco_fbcap::SLOT_DUMP, ecco_fbcap::SlotClass{ecco_fbcap::OBL_ENDING, ecco_fbcap::BASIS_RESTORE_RUNNING}, 0, "x", 0u)), "FB-B2 text: save_slot_refusal_text SLOT_DUMP OBL_ENDING BASIS_RESTORE_RUNNING");
static_assert(text_is("SAVE REFUSED - Dump to Grid needs an operator recovery action first", save_slot_refusal_text(ecco_fbcap::SLOT_DUMP, ecco_fbcap::SlotClass{ecco_fbcap::OBL_OPERATOR_NEEDED, ecco_fbcap::BASIS_NONE}, 0, "x", 0u)), "FB-B2 text: save_slot_refusal_text SLOT_DUMP OBL_OPERATOR_NEEDED BASIS_NONE");
static_assert(text_is("SAVE REFUSED - Dump to Grid recovery state UNKNOWN since boot (marker unreadable); an obligation cannot be ruled out; Fallback never proceeds past it", save_slot_refusal_text(ecco_fbcap::SLOT_DUMP, ecco_fbcap::SlotClass{ecco_fbcap::UNK_DURABLE_UNREADABLE, ecco_fbcap::BASIS_BOOT_READ_ERROR}, 0, "x", 0u)), "FB-B2 text: save_slot_refusal_text SLOT_DUMP UNK_DURABLE_UNREADABLE BASIS_BOOT_READ_ERROR");
static_assert(text_is("SAVE REFUSED - Dump to Grid recovery marker became unreadable at runtime; saving blocked until reboot. After reboot it may read absent: verify live settings first; do not erase NVS", save_slot_refusal_text(ecco_fbcap::SLOT_DUMP, ecco_fbcap::SlotClass{ecco_fbcap::UNK_DURABLE_UNREADABLE, ecco_fbcap::BASIS_RUNTIME_PROBE}, 0, "x", 0u)), "FB-B2 text: save_slot_refusal_text SLOT_DUMP UNK_DURABLE_UNREADABLE BASIS_RUNTIME_PROBE");
static_assert(text_is("SAVE REFUSED - Dump to Grid recovery metadata is CORRUPT (hard lockout); Fallback never overwrites or proceeds past it; do not erase NVS", save_slot_refusal_text(ecco_fbcap::SLOT_DUMP, ecco_fbcap::SlotClass{ecco_fbcap::UNK_METADATA_CORRUPT, ecco_fbcap::BASIS_BOOT_LOCKOUT}, 0, "x", 0u)), "FB-B2 text: save_slot_refusal_text SLOT_DUMP UNK_METADATA_CORRUPT BASIS_BOOT_LOCKOUT");
static_assert(text_is("SAVE REFUSED - Dump to Grid recovery marker is malformed (found at runtime); saving blocked until reboot, which re-derives it as a hard lockout", save_slot_refusal_text(ecco_fbcap::SLOT_DUMP, ecco_fbcap::SlotClass{ecco_fbcap::UNK_METADATA_CORRUPT, ecco_fbcap::BASIS_RUNTIME_PROBE}, 0, "x", 0u)), "FB-B2 text: save_slot_refusal_text SLOT_DUMP UNK_METADATA_CORRUPT BASIS_RUNTIME_PROBE");
static_assert(text_is("SAVE REFUSED - durable state not loaded yet", save_slot_refusal_text(ecco_fbcap::SLOT_DUMP, ecco_fbcap::SlotClass{ecco_fbcap::UNK_BOOT_NOT_LOADED, ecco_fbcap::BASIS_NONE}, 0, "x", 0u)), "FB-B2 text: save_slot_refusal_text SLOT_DUMP UNK_BOOT_NOT_LOADED BASIS_NONE");
static_assert(text_is("SAVE REFUSED - Dump to Grid stored marker says RESTORE_REQUIRED but memory says clear; saving blocked until reboot, which re-derives it (the domain may then restore its saved original)", save_slot_refusal_text(ecco_fbcap::SLOT_DUMP, ecco_fbcap::SlotClass{ecco_fbcap::UNK_DIVERGED, ecco_fbcap::BASIS_GHOST_RR}, 0, "x", 0u)), "FB-B2 text: save_slot_refusal_text SLOT_DUMP UNK_DIVERGED BASIS_GHOST_RR");
static_assert(text_is("SAVE REFUSED - Dump to Grid stored marker says PENDING_CLEAR but memory says clear; saving blocked until reboot, which re-derives it (the domain may then restore its saved original)", save_slot_refusal_text(ecco_fbcap::SLOT_DUMP, ecco_fbcap::SlotClass{ecco_fbcap::UNK_DIVERGED, ecco_fbcap::BASIS_GHOST_PC}, 0, "x", 0u)), "FB-B2 text: save_slot_refusal_text SLOT_DUMP UNK_DIVERGED BASIS_GHOST_PC");
static_assert(text_is("SAVE REFUSED - Dump to Grid in-memory recovery state is inconsistent; a reboot must re-derive it before saving", save_slot_refusal_text(ecco_fbcap::SLOT_DUMP, ecco_fbcap::SlotClass{ecco_fbcap::UNK_DIVERGED, ecco_fbcap::BASIS_RAM_INCONSISTENT}, 0, "x", 0u)), "FB-B2 text: save_slot_refusal_text SLOT_DUMP UNK_DIVERGED BASIS_RAM_INCONSISTENT");
static_assert(text_is("SAVE REFUSED - Dump to Grid in-progress flag is set with no running operation (possible leak); a reboot re-derives it", save_slot_refusal_text(ecco_fbcap::SLOT_DUMP, ecco_fbcap::SlotClass{ecco_fbcap::UNK_BUS_OR_LOCK_STUCK, ecco_fbcap::BASIS_OP_FLAG_UNATTRIBUTED}, 0, "x", 0u)), "FB-B2 text: save_slot_refusal_text SLOT_DUMP UNK_BUS_OR_LOCK_STUCK BASIS_OP_FLAG_UNATTRIBUTED");
static_assert(text_is("SAVE REFUSED - Dump to Grid state does not permit saving", save_slot_refusal_text(ecco_fbcap::SLOT_DUMP, ecco_fbcap::SlotClass{ecco_fbcap::UNK_NOT_PROBED, ecco_fbcap::BASIS_NONE}, 0, "x", 0u)), "FB-B2 text: save_slot_refusal_text SLOT_DUMP UNK_NOT_PROBED BASIS_NONE");
static_assert(text_is("SAVE REFUSED - Dump to Grid state does not permit saving", save_slot_refusal_text(ecco_fbcap::SLOT_DUMP, ecco_fbcap::SlotClass{ecco_fbcap::OBL_CLEAR_PROVEN, ecco_fbcap::BASIS_NONE}, 0, "x", 0u)), "FB-B2 text: save_slot_refusal_text SLOT_DUMP OBL_CLEAR_PROVEN BASIS_NONE");
static_assert(text_is("SAVE REFUSED - Dump to Grid state does not permit saving", save_slot_refusal_text(ecco_fbcap::SLOT_DUMP, ecco_fbcap::SlotClass{ecco_fbcap::OBL_UNSET, ecco_fbcap::BASIS_NONE}, 0, "x", 0u)), "FB-B2 text: save_slot_refusal_text SLOT_DUMP OBL_UNSET BASIS_NONE");
static_assert(text_is("SAVE REFUSED - Failback record is active; live settings are a temporary overlay - end it first", save_slot_refusal_text(ecco_fbcap::SLOT_FBS, ecco_fbcap::SlotClass{ecco_fbcap::OBL_ACTIVE, ecco_fbcap::BASIS_LEASE}, 0, "x", 0u)), "FB-B2 text: save_slot_refusal_text SLOT_FBS OBL_ACTIVE BASIS_LEASE");
static_assert(text_is("SAVE REFUSED - a failback episode record exists; only the firmware that created it can resolve it", save_slot_refusal_text(ecco_fbcap::SLOT_FBS, ecco_fbcap::SlotClass{ecco_fbcap::OBL_ACTIVE, ecco_fbcap::BASIS_FBS_EPISODE}, 0, "x", 0u)), "FB-B2 text: save_slot_refusal_text SLOT_FBS OBL_ACTIVE BASIS_FBS_EPISODE");
static_assert(text_is("SAVE REFUSED - a Failback record start is in progress; live settings are about to become a temporary overlay", save_slot_refusal_text(ecco_fbcap::SLOT_FBS, ecco_fbcap::SlotClass{ecco_fbcap::OBL_STARTING, ecco_fbcap::BASIS_PRE_COMMIT}, 0, "x", 0u)), "FB-B2 text: save_slot_refusal_text SLOT_FBS OBL_STARTING BASIS_PRE_COMMIT");
static_assert(text_is("SAVE REFUSED - Failback record restore verified; durable clear still pending", save_slot_refusal_text(ecco_fbcap::SLOT_FBS, ecco_fbcap::SlotClass{ecco_fbcap::OBL_PENDING_CLEAR, ecco_fbcap::BASIS_NONE}, 0, "x", 0u)), "FB-B2 text: save_slot_refusal_text SLOT_FBS OBL_PENDING_CLEAR BASIS_NONE");
static_assert(text_is("SAVE REFUSED - Failback record recovery state UNKNOWN since boot (marker unreadable); an obligation cannot be ruled out; Fallback never proceeds past it", save_slot_refusal_text(ecco_fbcap::SLOT_FBS, ecco_fbcap::SlotClass{ecco_fbcap::UNK_DURABLE_UNREADABLE, ecco_fbcap::BASIS_BOOT_READ_ERROR}, 0, "x", 0u)), "FB-B2 text: save_slot_refusal_text SLOT_FBS UNK_DURABLE_UNREADABLE BASIS_BOOT_READ_ERROR");
static_assert(text_is("SAVE REFUSED - Failback record recovery metadata is CORRUPT (hard lockout); Fallback never overwrites or proceeds past it; do not erase NVS", save_slot_refusal_text(ecco_fbcap::SLOT_FBS, ecco_fbcap::SlotClass{ecco_fbcap::UNK_METADATA_CORRUPT, ecco_fbcap::BASIS_BOOT_LOCKOUT}, 0, "x", 0u)), "FB-B2 text: save_slot_refusal_text SLOT_FBS UNK_METADATA_CORRUPT BASIS_BOOT_LOCKOUT");
static_assert(text_is("SAVE REFUSED - durable state not loaded yet", save_slot_refusal_text(ecco_fbcap::SLOT_FBS, ecco_fbcap::SlotClass{ecco_fbcap::UNK_BOOT_NOT_LOADED, ecco_fbcap::BASIS_NONE}, 0, "x", 0u)), "FB-B2 text: save_slot_refusal_text SLOT_FBS UNK_BOOT_NOT_LOADED BASIS_NONE");
static_assert(text_is("SAVE REFUSED - Failback record state does not permit saving", save_slot_refusal_text(ecco_fbcap::SLOT_FBS, ecco_fbcap::SlotClass{ecco_fbcap::OBL_UNSET, ecco_fbcap::BASIS_NONE}, 0, "x", 0u)), "FB-B2 text: save_slot_refusal_text SLOT_FBS OBL_UNSET BASIS_NONE");
static_assert(text_is("SAVE REFUSED - Manual TOU is active; live settings are a temporary overlay - end it first", save_slot_refusal_text(ecco_fbcap::SLOT_MTOU, ecco_fbcap::SlotClass{ecco_fbcap::OBL_ACTIVE, ecco_fbcap::BASIS_LEASE}, 0, "x", 0u)), "FB-B2 text: save_slot_refusal_text SLOT_MTOU OBL_ACTIVE BASIS_LEASE");
static_assert(text_is("SAVE REFUSED - a failback episode record exists; only the firmware that created it can resolve it", save_slot_refusal_text(ecco_fbcap::SLOT_MTOU, ecco_fbcap::SlotClass{ecco_fbcap::OBL_ACTIVE, ecco_fbcap::BASIS_FBS_EPISODE}, 0, "x", 0u)), "FB-B2 text: save_slot_refusal_text SLOT_MTOU OBL_ACTIVE BASIS_FBS_EPISODE");
static_assert(text_is("SAVE REFUSED - a Manual TOU start is in progress; live settings are about to become a temporary overlay", save_slot_refusal_text(ecco_fbcap::SLOT_MTOU, ecco_fbcap::SlotClass{ecco_fbcap::OBL_STARTING, ecco_fbcap::BASIS_PRE_COMMIT}, 0, "x", 0u)), "FB-B2 text: save_slot_refusal_text SLOT_MTOU OBL_STARTING BASIS_PRE_COMMIT");
static_assert(text_is("SAVE REFUSED - Manual TOU restore verified; durable clear still pending", save_slot_refusal_text(ecco_fbcap::SLOT_MTOU, ecco_fbcap::SlotClass{ecco_fbcap::OBL_PENDING_CLEAR, ecco_fbcap::BASIS_NONE}, 0, "x", 0u)), "FB-B2 text: save_slot_refusal_text SLOT_MTOU OBL_PENDING_CLEAR BASIS_NONE");
static_assert(text_is("SAVE REFUSED - Manual TOU recovery state UNKNOWN since boot (marker unreadable); an obligation cannot be ruled out; Fallback never proceeds past it", save_slot_refusal_text(ecco_fbcap::SLOT_MTOU, ecco_fbcap::SlotClass{ecco_fbcap::UNK_DURABLE_UNREADABLE, ecco_fbcap::BASIS_BOOT_READ_ERROR}, 0, "x", 0u)), "FB-B2 text: save_slot_refusal_text SLOT_MTOU UNK_DURABLE_UNREADABLE BASIS_BOOT_READ_ERROR");
static_assert(text_is("SAVE REFUSED - Manual TOU recovery metadata is CORRUPT (hard lockout); Fallback never overwrites or proceeds past it; do not erase NVS", save_slot_refusal_text(ecco_fbcap::SLOT_MTOU, ecco_fbcap::SlotClass{ecco_fbcap::UNK_METADATA_CORRUPT, ecco_fbcap::BASIS_BOOT_LOCKOUT}, 0, "x", 0u)), "FB-B2 text: save_slot_refusal_text SLOT_MTOU UNK_METADATA_CORRUPT BASIS_BOOT_LOCKOUT");
static_assert(text_is("SAVE REFUSED - durable state not loaded yet", save_slot_refusal_text(ecco_fbcap::SLOT_MTOU, ecco_fbcap::SlotClass{ecco_fbcap::UNK_BOOT_NOT_LOADED, ecco_fbcap::BASIS_NONE}, 0, "x", 0u)), "FB-B2 text: save_slot_refusal_text SLOT_MTOU UNK_BOOT_NOT_LOADED BASIS_NONE");
static_assert(text_is("SAVE REFUSED - Manual TOU state does not permit saving", save_slot_refusal_text(ecco_fbcap::SLOT_MTOU, ecco_fbcap::SlotClass{ecco_fbcap::OBL_UNSET, ecco_fbcap::BASIS_NONE}, 0, "x", 0u)), "FB-B2 text: save_slot_refusal_text SLOT_MTOU OBL_UNSET BASIS_NONE");
static_assert(text_is("SAVE REFUSED - Dump to Grid recovery metadata is CORRUPT (hard lockout); Fallback never overwrites or proceeds past it; do not erase NVS; containment K=5", save_slot_refusal_text(ecco_fbcap::SLOT_DUMP, ecco_fbcap::SlotClass{ecco_fbcap::UNK_METADATA_CORRUPT, ecco_fbcap::BASIS_BOOT_LOCKOUT}, 5, "", 0u)), "FB-B2 text: save_slot_refusal_text SLOT_DUMP corrupt with containment K=5");
static_assert(text_is("SAVE REFUSED - Free Power recovery metadata is CORRUPT (hard lockout); Fallback never overwrites or proceeds past it; do not erase NVS", save_slot_refusal_text(ecco_fbcap::SLOT_FP, ecco_fbcap::SlotClass{ecco_fbcap::UNK_METADATA_CORRUPT, ecco_fbcap::BASIS_BOOT_LOCKOUT}, 5, "", 0u)), "FB-B2 text: save_slot_refusal_text SLOT_FP corrupt ignores the Dump K");
static_assert(text_is("SAVE REFUSED - another inverter transaction is in progress (Free Power); try again shortly", save_slot_refusal_text(ecco_fbcap::SLOT_BUS, ecco_fbcap::SlotClass{ecco_fbcap::BUS_BUSY, ecco_fbcap::BASIS_BUS_TXN}, 0, "Free Power", 0u)), "FB-B2 text: save_slot_refusal_text SLOT_BUS busy, owner Free Power");
static_assert(text_is("SAVE REFUSED - another inverter transaction is in progress (Register 244 test); try again shortly", save_slot_refusal_text(ecco_fbcap::SLOT_BUS, ecco_fbcap::SlotClass{ecco_fbcap::BUS_BUSY, ecco_fbcap::BASIS_BUS_TXN}, 0, "Register 244 test", 0u)), "FB-B2 text: save_slot_refusal_text SLOT_BUS busy, owner Register 244 test");
static_assert(text_is("SAVE REFUSED - another inverter transaction is in progress (Dump to Grid); try again shortly", save_slot_refusal_text(ecco_fbcap::SLOT_BUS, ecco_fbcap::SlotClass{ecco_fbcap::BUS_BUSY, ecco_fbcap::BASIS_BUS_TXN}, 0, "Dump to Grid", 0u)), "FB-B2 text: save_slot_refusal_text SLOT_BUS busy, owner Dump to Grid");
static_assert(text_is("SAVE REFUSED - another inverter transaction is in progress (Fallback Profile); try again shortly", save_slot_refusal_text(ecco_fbcap::SLOT_BUS, ecco_fbcap::SlotClass{ecco_fbcap::BUS_BUSY, ecco_fbcap::BASIS_BUS_TXN}, 0, "Fallback Profile", 0u)), "FB-B2 text: save_slot_refusal_text SLOT_BUS busy, owner Fallback Profile");
static_assert(text_is("SAVE REFUSED - another inverter transaction is in progress (clock correction); try again shortly", save_slot_refusal_text(ecco_fbcap::SLOT_BUS, ecco_fbcap::SlotClass{ecco_fbcap::BUS_BUSY, ecco_fbcap::BASIS_BUS_TXN}, 0, "clock correction", 0u)), "FB-B2 text: save_slot_refusal_text SLOT_BUS busy, owner clock correction");
static_assert(text_is("SAVE REFUSED - another inverter transaction is in progress (clock verification); try again shortly", save_slot_refusal_text(ecco_fbcap::SLOT_BUS, ecco_fbcap::SlotClass{ecco_fbcap::BUS_BUSY, ecco_fbcap::BASIS_BUS_TXN}, 0, "clock verification", 0u)), "FB-B2 text: save_slot_refusal_text SLOT_BUS busy, owner clock verification");
static_assert(text_is("SAVE REFUSED - another inverter transaction is in progress (manual write); try again shortly", save_slot_refusal_text(ecco_fbcap::SLOT_BUS, ecco_fbcap::SlotClass{ecco_fbcap::BUS_BUSY, ecco_fbcap::BASIS_BUS_TXN}, 0, "manual write", 0u)), "FB-B2 text: save_slot_refusal_text SLOT_BUS busy, owner manual write");
static_assert(text_is("SAVE REFUSED - inverter write lock held for 300 s (possible leak); a reboot may be required", save_slot_refusal_text(ecco_fbcap::SLOT_BUS, ecco_fbcap::SlotClass{ecco_fbcap::UNK_BUS_OR_LOCK_STUCK, ecco_fbcap::BASIS_LOCK_STUCK}, 0, "", 300u)), "FB-B2 text: save_slot_refusal_text SLOT_BUS stuck, 300 s");
static_assert(text_is("SAVE REFUSED - inverter write lock held for 4294967 s (possible leak); a reboot may be required", save_slot_refusal_text(ecco_fbcap::SLOT_BUS, ecco_fbcap::SlotClass{ecco_fbcap::UNK_BUS_OR_LOCK_STUCK, ecco_fbcap::BASIS_LOCK_STUCK}, 0, "", 4294967u)), "FB-B2 text: save_slot_refusal_text SLOT_BUS stuck, 4294967 s");
static_assert(text_is("SAVE REFUSED - another Fallback Profile operation is in progress", save_in_flight_text()), "FB-B2 text: save_in_flight_text");
static_assert(text_is("SAVE REFUSED - ECCO Fallback Profile Arm is not on", save_arm_off_text()), "FB-B2 text: save_arm_off_text");
static_assert(text_is("SAVE REFUSED - no saveable candidate - press Review Current Configuration first", save_no_candidate_text()), "FB-B2 text: save_no_candidate_text");
static_assert(text_is("SAVE REFUSED - candidate expired (120 s) - review again", save_expired_text()), "FB-B2 text: save_expired_text");
static_assert(text_is("SAVE REFUSED - candidate ID must be 16 hex characters", save_id_format_text()), "FB-B2 text: save_id_format_text");
static_assert(text_is("SAVE REFUSED - candidate ID does not match the current candidate", save_id_mismatch_text()), "FB-B2 text: save_id_mismatch_text");
static_assert(text_is("SAVE REFUSED - durable state not loaded yet", save_not_loaded_text()), "FB-B2 text: save_not_loaded_text");
static_assert(text_is("SAVE REFUSED - previous save outcome unknown this boot - reboot to re-verify first", save_prior_unknown_text()), "FB-B2 text: save_prior_unknown_text");
static_assert(text_is("SAVE REFUSED - stored profile read anomaly this boot; reboot to re-derive it first", save_anomaly_text()), "FB-B2 text: save_anomaly_text");
static_assert(text_is("SAVE REFUSED - Home Assistant heartbeat is not stable; wait until the dashboard shows it healthy, then review and save again", save_hb_text()), "FB-B2 text: save_hb_text");
static_assert(text_is("SAVE REFUSED - clock not NTP-synchronised this boot; the capture time would be untrusted", save_time_text()), "FB-B2 text: save_time_text");
static_assert(text_is("SAVE REFUSED - a Free Power / Dump to Grid / Manual Configuration write arm is on; finish or turn it off first", save_arms_text()), "FB-B2 text: save_arms_text");
static_assert(text_is("SAVE REFUSED - another ECCO inverter write started since Review - review again", save_writes_text()), "FB-B2 text: save_writes_text");
static_assert(text_is("SAVE REFUSED - internal: gate state unavailable; nothing written", save_internal_text()), "FB-B2 text: save_internal_text");
static_assert(text_is("save in progress - re-reading live configuration", save_in_progress_text()), "FB-B2 text: save_in_progress_text");
static_assert(text_is("SAVE REFUSED - inverter bus not quiet at commit; profile unchanged", save_bus_quiet_text()), "FB-B2 text: save_bus_quiet_text");
static_assert(text_is("SAVE REFUSED - stored profile changed since Review; profile unchanged", save_prior_changed_text()), "FB-B2 text: save_prior_changed_text");
static_assert(text_is("SAVE REFUSED - profile generation counter exhausted; profile unchanged", save_generation_text()), "FB-B2 text: save_generation_text");
static_assert(text_is("SAVE REFUSED - internal: built record did not validate; nothing written", save_internal_record_text()), "FB-B2 text: save_internal_record_text");
static_assert(text_is("INVALIDATE REFUSED - another Fallback Profile operation is in progress", invalidate_in_flight_text()), "FB-B2 text: invalidate_in_flight_text");
static_assert(text_is("INVALIDATE REFUSED - ECCO Fallback Profile Arm is not on", invalidate_arm_off_text()), "FB-B2 text: invalidate_arm_off_text");
static_assert(text_is("INVALIDATE REFUSED - profile ID must be 16 hex characters", invalidate_id_format_text()), "FB-B2 text: invalidate_id_format_text");
static_assert(text_is("INVALIDATE REFUSED - durable state not loaded yet (starting up)", invalidate_not_loaded_text()), "FB-B2 text: invalidate_not_loaded_text");
static_assert(text_is("INVALIDATE REFUSED - stored profile read anomaly this boot; reboot to re-derive first", invalidate_anomaly_text()), "FB-B2 text: invalidate_anomaly_text");
static_assert(text_is("INVALIDATE REFUSED - previous Fallback Profile write outcome unknown this boot - reboot to re-verify first", invalidate_prior_unknown_text()), "FB-B2 text: invalidate_prior_unknown_text");
static_assert(text_is("INVALIDATE REFUSED - profile ID does not match the stored VALID profile", invalidate_id_mismatch_text()), "FB-B2 text: invalidate_id_mismatch_text");
static_assert(text_is("INVALIDATE REFUSED - inverter busy; try again", invalidate_busy_text()), "FB-B2 text: invalidate_busy_text");
static_assert(text_is("INVALIDATE REFUSED - stored profile changed; nothing written", invalidate_changed_text()), "FB-B2 text: invalidate_changed_text");
static_assert(text_is("INVALIDATE REFUSED - internal: built record did not validate; nothing written", invalidate_internal_text()), "FB-B2 text: invalidate_internal_text");
static_assert(text_is("SAVE NOT COMMITTED - witness advanced; profile unchanged; stored profile is now out of step - review and save again", save_witness_advanced_text()), "FB-B2 text: save_witness_advanced_text");
static_assert(text_is("SAVE REFUSED - confirmation phrase mismatch (expected 'SAVE 0123456789ABCDEF')", save_phrase_text(expected_phrase(PHRASE_SAVE, FX_ID))), "FB-B2 text: save_phrase_text (plain)");
static_assert(text_is("SAVE REFUSED - confirmation phrase mismatch (expected 'SAVE 0123456789ABCDEF REPLACE CORRUPT')", save_phrase_text(expected_phrase(PHRASE_SAVE_REPLACE_CORRUPT, FX_ID))), "FB-B2 text: save_phrase_text (REPLACE CORRUPT)");
static_assert(text_is("INVALIDATE REFUSED - confirmation phrase mismatch (expected 'INVALIDATE 0123456789ABCDEF')", invalidate_phrase_text(expected_phrase(PHRASE_INVALIDATE, FX_ID))), "FB-B2 text: invalidate_phrase_text");
static_assert(text_is("INVALIDATE REFUSED - profile is UNREADABLE; only a VALID profile can be invalidated", invalidate_class_text(0)), "FB-B2 text: invalidate_class_text 0");
static_assert(text_is("INVALIDATE REFUSED - profile is now UNREADABLE; nothing written", invalidate_class_now_text(0)), "FB-B2 text: invalidate_class_now_text 0");
static_assert(text_is("SAVE REFUSED - stored profile UNREADABLE (-); reboot to re-derive it (it will then read VALID, LOST or NOT_CAPTURED)", save_class_text(0, 0)), "FB-B2 text: save_class_text cls 0 why 0");
static_assert(text_is("SAVE REFUSED - stored profile UNREADABLE (PRD); reboot to re-derive it (it will then read VALID, LOST or NOT_CAPTURED)", save_class_text(0, 8)), "FB-B2 text: save_class_text cls 0 why 8");
static_assert(text_is("SAVE REFUSED - stored profile UNREADABLE (WRD); reboot to re-derive it (it will then read VALID, LOST or NOT_CAPTURED)", save_class_text(0, 9)), "FB-B2 text: save_class_text cls 0 why 9");
static_assert(text_is("SAVE REFUSED - stored profile UNREADABLE (ANOM); reboot to re-derive it (it will then read VALID, LOST or NOT_CAPTURED)", save_class_text(0, 10)), "FB-B2 text: save_class_text cls 0 why 10");
static_assert(text_is("INVALIDATE REFUSED - profile is NOT_CAPTURED; only a VALID profile can be invalidated", invalidate_class_text(1)), "FB-B2 text: invalidate_class_text 1");
static_assert(text_is("INVALIDATE REFUSED - profile is now NOT_CAPTURED; nothing written", invalidate_class_now_text(1)), "FB-B2 text: invalidate_class_now_text 1");
static_assert(text_is("SAVE REFUSED - stored profile state does not permit saving", save_class_text(1, 0)), "FB-B2 text: save_class_text cls 1 why 0");
static_assert(text_is("SAVE REFUSED - stored profile state does not permit saving", save_class_text(1, 8)), "FB-B2 text: save_class_text cls 1 why 8");
static_assert(text_is("SAVE REFUSED - stored profile state does not permit saving", save_class_text(1, 9)), "FB-B2 text: save_class_text cls 1 why 9");
static_assert(text_is("SAVE REFUSED - stored profile state does not permit saving", save_class_text(1, 10)), "FB-B2 text: save_class_text cls 1 why 10");
static_assert(text_is("INVALIDATE REFUSED - profile is CORRUPT; only a VALID profile can be invalidated", invalidate_class_text(2)), "FB-B2 text: invalidate_class_text 2");
static_assert(text_is("INVALIDATE REFUSED - profile is now CORRUPT; nothing written", invalidate_class_now_text(2)), "FB-B2 text: invalidate_class_now_text 2");
static_assert(text_is("SAVE REFUSED - stored profile state does not permit saving", save_class_text(2, 0)), "FB-B2 text: save_class_text cls 2 why 0");
static_assert(text_is("SAVE REFUSED - stored profile state does not permit saving", save_class_text(2, 8)), "FB-B2 text: save_class_text cls 2 why 8");
static_assert(text_is("SAVE REFUSED - stored profile state does not permit saving", save_class_text(2, 9)), "FB-B2 text: save_class_text cls 2 why 9");
static_assert(text_is("SAVE REFUSED - stored profile state does not permit saving", save_class_text(2, 10)), "FB-B2 text: save_class_text cls 2 why 10");
static_assert(text_is("INVALIDATE REFUSED - profile is CORRUPT_DOMAIN; only a VALID profile can be invalidated", invalidate_class_text(3)), "FB-B2 text: invalidate_class_text 3");
static_assert(text_is("INVALIDATE REFUSED - profile is now CORRUPT_DOMAIN; nothing written", invalidate_class_now_text(3)), "FB-B2 text: invalidate_class_now_text 3");
static_assert(text_is("SAVE REFUSED - stored profile state does not permit saving", save_class_text(3, 0)), "FB-B2 text: save_class_text cls 3 why 0");
static_assert(text_is("SAVE REFUSED - stored profile state does not permit saving", save_class_text(3, 8)), "FB-B2 text: save_class_text cls 3 why 8");
static_assert(text_is("SAVE REFUSED - stored profile state does not permit saving", save_class_text(3, 9)), "FB-B2 text: save_class_text cls 3 why 9");
static_assert(text_is("SAVE REFUSED - stored profile state does not permit saving", save_class_text(3, 10)), "FB-B2 text: save_class_text cls 3 why 10");
static_assert(text_is("INVALIDATE REFUSED - profile is INVALIDATED; only a VALID profile can be invalidated", invalidate_class_text(4)), "FB-B2 text: invalidate_class_text 4");
static_assert(text_is("INVALIDATE REFUSED - profile is now INVALIDATED; nothing written", invalidate_class_now_text(4)), "FB-B2 text: invalidate_class_now_text 4");
static_assert(text_is("SAVE REFUSED - stored profile state does not permit saving", save_class_text(4, 0)), "FB-B2 text: save_class_text cls 4 why 0");
static_assert(text_is("SAVE REFUSED - stored profile state does not permit saving", save_class_text(4, 8)), "FB-B2 text: save_class_text cls 4 why 8");
static_assert(text_is("SAVE REFUSED - stored profile state does not permit saving", save_class_text(4, 9)), "FB-B2 text: save_class_text cls 4 why 9");
static_assert(text_is("SAVE REFUSED - stored profile state does not permit saving", save_class_text(4, 10)), "FB-B2 text: save_class_text cls 4 why 10");
static_assert(text_is("INVALIDATE REFUSED - profile is VALID; only a VALID profile can be invalidated", invalidate_class_text(5)), "FB-B2 text: invalidate_class_text 5");
static_assert(text_is("INVALIDATE REFUSED - profile is now VALID; nothing written", invalidate_class_now_text(5)), "FB-B2 text: invalidate_class_now_text 5");
static_assert(text_is("SAVE REFUSED - stored profile state does not permit saving", save_class_text(5, 0)), "FB-B2 text: save_class_text cls 5 why 0");
static_assert(text_is("SAVE REFUSED - stored profile state does not permit saving", save_class_text(5, 8)), "FB-B2 text: save_class_text cls 5 why 8");
static_assert(text_is("SAVE REFUSED - stored profile state does not permit saving", save_class_text(5, 9)), "FB-B2 text: save_class_text cls 5 why 9");
static_assert(text_is("SAVE REFUSED - stored profile state does not permit saving", save_class_text(5, 10)), "FB-B2 text: save_class_text cls 5 why 10");
static_assert(text_is("INVALIDATE REFUSED - profile is PROFILE_LOST; only a VALID profile can be invalidated", invalidate_class_text(6)), "FB-B2 text: invalidate_class_text 6");
static_assert(text_is("INVALIDATE REFUSED - profile is now PROFILE_LOST; nothing written", invalidate_class_now_text(6)), "FB-B2 text: invalidate_class_now_text 6");
static_assert(text_is("SAVE REFUSED - stored profile state does not permit saving", save_class_text(6, 0)), "FB-B2 text: save_class_text cls 6 why 0");
static_assert(text_is("SAVE REFUSED - stored profile state does not permit saving", save_class_text(6, 8)), "FB-B2 text: save_class_text cls 6 why 8");
static_assert(text_is("SAVE REFUSED - stored profile state does not permit saving", save_class_text(6, 9)), "FB-B2 text: save_class_text cls 6 why 9");
static_assert(text_is("SAVE REFUSED - stored profile state does not permit saving", save_class_text(6, 10)), "FB-B2 text: save_class_text cls 6 why 10");
static_assert(text_is("INVALIDATE REFUSED - profile is SAVE_UNCONFIRMED; only a VALID profile can be invalidated", invalidate_class_text(7)), "FB-B2 text: invalidate_class_text 7");
static_assert(text_is("INVALIDATE REFUSED - profile is now SAVE_UNCONFIRMED; nothing written", invalidate_class_now_text(7)), "FB-B2 text: invalidate_class_now_text 7");
static_assert(text_is("SAVE REFUSED - previous save outcome unknown this boot - reboot to re-verify first", save_class_text(7, 0)), "FB-B2 text: save_class_text cls 7 why 0");
static_assert(text_is("SAVE REFUSED - previous save outcome unknown this boot - reboot to re-verify first", save_class_text(7, 8)), "FB-B2 text: save_class_text cls 7 why 8");
static_assert(text_is("SAVE REFUSED - previous save outcome unknown this boot - reboot to re-verify first", save_class_text(7, 9)), "FB-B2 text: save_class_text cls 7 why 9");
static_assert(text_is("SAVE REFUSED - previous save outcome unknown this boot - reboot to re-verify first", save_class_text(7, 10)), "FB-B2 text: save_class_text cls 7 why 10");
static_assert(text_is("INVALIDATE REFUSED - profile is PROFILE_STALE; only a VALID profile can be invalidated", invalidate_class_text(8)), "FB-B2 text: invalidate_class_text 8");
static_assert(text_is("INVALIDATE REFUSED - profile is now PROFILE_STALE; nothing written", invalidate_class_now_text(8)), "FB-B2 text: invalidate_class_now_text 8");
static_assert(text_is("SAVE REFUSED - stored profile state does not permit saving", save_class_text(8, 0)), "FB-B2 text: save_class_text cls 8 why 0");
static_assert(text_is("SAVE REFUSED - stored profile state does not permit saving", save_class_text(8, 8)), "FB-B2 text: save_class_text cls 8 why 8");
static_assert(text_is("SAVE REFUSED - stored profile state does not permit saving", save_class_text(8, 9)), "FB-B2 text: save_class_text cls 8 why 9");
static_assert(text_is("SAVE REFUSED - stored profile state does not permit saving", save_class_text(8, 10)), "FB-B2 text: save_class_text cls 8 why 10");
static_assert(text_is("INVALIDATE REFUSED - profile is UNREADABLE; only a VALID profile can be invalidated", invalidate_class_text(9)), "FB-B2 text: invalidate_class_text 9");
static_assert(text_is("INVALIDATE REFUSED - profile is now UNREADABLE; nothing written", invalidate_class_now_text(9)), "FB-B2 text: invalidate_class_now_text 9");
static_assert(text_is("SAVE REFUSED - stored profile state does not permit saving", save_class_text(9, 0)), "FB-B2 text: save_class_text cls 9 why 0");
static_assert(text_is("SAVE REFUSED - stored profile state does not permit saving", save_class_text(9, 8)), "FB-B2 text: save_class_text cls 9 why 8");
static_assert(text_is("SAVE REFUSED - stored profile state does not permit saving", save_class_text(9, 9)), "FB-B2 text: save_class_text cls 9 why 9");
static_assert(text_is("SAVE REFUSED - stored profile state does not permit saving", save_class_text(9, 10)), "FB-B2 text: save_class_text cls 9 why 10");
static_assert(text_is("INVALIDATE REFUSED - profile is UNREADABLE; only a VALID profile can be invalidated", invalidate_class_text(255)), "FB-B2 text: invalidate_class_text 255");
static_assert(text_is("INVALIDATE REFUSED - profile is now UNREADABLE; nothing written", invalidate_class_now_text(255)), "FB-B2 text: invalidate_class_now_text 255");
static_assert(text_is("SAVE REFUSED - stored profile state does not permit saving", save_class_text(255, 0)), "FB-B2 text: save_class_text cls 255 why 0");
static_assert(text_is("SAVE REFUSED - stored profile state does not permit saving", save_class_text(255, 8)), "FB-B2 text: save_class_text cls 255 why 8");
static_assert(text_is("SAVE REFUSED - stored profile state does not permit saving", save_class_text(255, 9)), "FB-B2 text: save_class_text cls 255 why 9");
static_assert(text_is("SAVE REFUSED - stored profile state does not permit saving", save_class_text(255, 10)), "FB-B2 text: save_class_text cls 255 why 10");
static_assert(text_is("INVALIDATE REFUSED - generation counter exhausted", invalidate_generation_text(true)), "FB-B2 text: invalidate_generation_text exhausted=True");
static_assert(text_is("INVALIDATE REFUSED - profile generation is not ahead of this boot's generation high-water mark; reboot to re-verify", invalidate_generation_text(false)), "FB-B2 text: invalidate_generation_text exhausted=False");
static_assert(text_is("INVALIDATE REFUSED - Failback record recovery state UNKNOWN since boot (marker unreadable); an obligation cannot be ruled out; Fallback never proceeds past it", invalidate_fbs_text(ecco_fbcap::classify_fbs([]{ ecco_fbcap::GateInputs g{}; g.boot_loaded = true; g.fbs_slot = 0; return g; }()))), "FB-B2 text: invalidate_fbs_text of FBS slot 0");
static_assert(text_is("INVALIDATE REFUSED - Failback record state does not permit saving", invalidate_fbs_text(ecco_fbcap::classify_fbs([]{ ecco_fbcap::GateInputs g{}; g.boot_loaded = true; g.fbs_slot = 1; return g; }()))), "FB-B2 text: invalidate_fbs_text of FBS slot 1");
static_assert(text_is("INVALIDATE REFUSED - Failback record state does not permit saving", invalidate_fbs_text(ecco_fbcap::classify_fbs([]{ ecco_fbcap::GateInputs g{}; g.boot_loaded = true; g.fbs_slot = 2; return g; }()))), "FB-B2 text: invalidate_fbs_text of FBS slot 2");
static_assert(text_is("INVALIDATE REFUSED - a failback episode record exists; only the firmware that created it can resolve it", invalidate_fbs_text(ecco_fbcap::classify_fbs([]{ ecco_fbcap::GateInputs g{}; g.boot_loaded = true; g.fbs_slot = 3; return g; }()))), "FB-B2 text: invalidate_fbs_text of FBS slot 3");
static_assert(text_is("INVALIDATE REFUSED - Failback record recovery metadata is CORRUPT (hard lockout); Fallback never overwrites or proceeds past it; do not erase NVS", invalidate_fbs_text(ecco_fbcap::classify_fbs([]{ ecco_fbcap::GateInputs g{}; g.boot_loaded = true; g.fbs_slot = 4; return g; }()))), "FB-B2 text: invalidate_fbs_text of FBS slot 4");
static_assert(text_is("INVALIDATE REFUSED - durable state not loaded yet", invalidate_fbs_text(ecco_fbcap::SlotClass{ecco_fbcap::UNK_BOOT_NOT_LOADED, ecco_fbcap::BASIS_NONE})), "FB-B2 text: invalidate_fbs_text of an unloaded boot");
static_assert(text_is("SAVE REFUSED - read did not complete (unknown cause); profile unchanged", save_read_fail_text(0, 0, 0)), "FB-B2 text: save_read_fail_text code 0 step 0");
static_assert(text_is("SAVE REFUSED - read did not complete (unknown cause); profile unchanged", save_read_fail_text(0, 1, 0)), "FB-B2 text: save_read_fail_text code 0 step 1");
static_assert(text_is("SAVE REFUSED - read did not complete (unknown cause); profile unchanged", save_read_fail_text(0, 2, 0)), "FB-B2 text: save_read_fail_text code 0 step 2");
static_assert(text_is("SAVE REFUSED - read did not complete (unknown cause); profile unchanged", save_read_fail_text(0, 3, 0)), "FB-B2 text: save_read_fail_text code 0 step 3");
static_assert(text_is("SAVE REFUSED - read did not complete (unknown cause); profile unchanged", save_read_fail_text(0, 4, 0)), "FB-B2 text: save_read_fail_text code 0 step 4");
static_assert(text_is("SAVE REFUSED - read did not complete (unknown cause); profile unchanged", save_read_fail_text(0, 9, 0)), "FB-B2 text: save_read_fail_text code 0 step 9");
static_assert(text_is("SAVE REFUSED - no response reading registers \?; profile unchanged", save_read_fail_text(1, 0, 0)), "FB-B2 text: save_read_fail_text code 1 step 0");
static_assert(text_is("SAVE REFUSED - no response reading registers 230/3; profile unchanged", save_read_fail_text(1, 1, 0)), "FB-B2 text: save_read_fail_text code 1 step 1");
static_assert(text_is("SAVE REFUSED - no response reading registers 241/53; profile unchanged", save_read_fail_text(1, 2, 0)), "FB-B2 text: save_read_fail_text code 1 step 2");
static_assert(text_is("SAVE REFUSED - no response reading registers 230/3; profile unchanged", save_read_fail_text(1, 3, 0)), "FB-B2 text: save_read_fail_text code 1 step 3");
static_assert(text_is("SAVE REFUSED - no response reading registers 241/53; profile unchanged", save_read_fail_text(1, 4, 0)), "FB-B2 text: save_read_fail_text code 1 step 4");
static_assert(text_is("SAVE REFUSED - no response reading registers \?; profile unchanged", save_read_fail_text(1, 9, 0)), "FB-B2 text: save_read_fail_text code 1 step 9");
static_assert(text_is("SAVE REFUSED - inverter returned an exception on registers \?; profile unchanged", save_read_fail_text(2, 0, 0)), "FB-B2 text: save_read_fail_text code 2 step 0");
static_assert(text_is("SAVE REFUSED - inverter returned an exception on registers 230/3; profile unchanged", save_read_fail_text(2, 1, 0)), "FB-B2 text: save_read_fail_text code 2 step 1");
static_assert(text_is("SAVE REFUSED - inverter returned an exception on registers 241/53; profile unchanged", save_read_fail_text(2, 2, 0)), "FB-B2 text: save_read_fail_text code 2 step 2");
static_assert(text_is("SAVE REFUSED - inverter returned an exception on registers 230/3; profile unchanged", save_read_fail_text(2, 3, 0)), "FB-B2 text: save_read_fail_text code 2 step 3");
static_assert(text_is("SAVE REFUSED - inverter returned an exception on registers 241/53; profile unchanged", save_read_fail_text(2, 4, 0)), "FB-B2 text: save_read_fail_text code 2 step 4");
static_assert(text_is("SAVE REFUSED - inverter returned an exception on registers \?; profile unchanged", save_read_fail_text(2, 9, 0)), "FB-B2 text: save_read_fail_text code 2 step 9");
static_assert(text_is("SAVE REFUSED - read of registers \? could not be queued; profile unchanged", save_read_fail_text(3, 0, 0)), "FB-B2 text: save_read_fail_text code 3 step 0");
static_assert(text_is("SAVE REFUSED - read of registers 230/3 could not be queued; profile unchanged", save_read_fail_text(3, 1, 0)), "FB-B2 text: save_read_fail_text code 3 step 1");
static_assert(text_is("SAVE REFUSED - read of registers 241/53 could not be queued; profile unchanged", save_read_fail_text(3, 2, 0)), "FB-B2 text: save_read_fail_text code 3 step 2");
static_assert(text_is("SAVE REFUSED - read of registers 230/3 could not be queued; profile unchanged", save_read_fail_text(3, 3, 0)), "FB-B2 text: save_read_fail_text code 3 step 3");
static_assert(text_is("SAVE REFUSED - read of registers 241/53 could not be queued; profile unchanged", save_read_fail_text(3, 4, 0)), "FB-B2 text: save_read_fail_text code 3 step 4");
static_assert(text_is("SAVE REFUSED - read of registers \? could not be queued; profile unchanged", save_read_fail_text(3, 9, 0)), "FB-B2 text: save_read_fail_text code 3 step 9");
static_assert(text_is("SAVE REFUSED - non-standard reply reading registers \?; profile unchanged", save_read_fail_text(4, 0, 0)), "FB-B2 text: save_read_fail_text code 4 step 0");
static_assert(text_is("SAVE REFUSED - non-standard reply reading registers 230/3; profile unchanged", save_read_fail_text(4, 1, 0)), "FB-B2 text: save_read_fail_text code 4 step 1");
static_assert(text_is("SAVE REFUSED - non-standard reply reading registers 241/53; profile unchanged", save_read_fail_text(4, 2, 0)), "FB-B2 text: save_read_fail_text code 4 step 2");
static_assert(text_is("SAVE REFUSED - non-standard reply reading registers 230/3; profile unchanged", save_read_fail_text(4, 3, 0)), "FB-B2 text: save_read_fail_text code 4 step 3");
static_assert(text_is("SAVE REFUSED - non-standard reply reading registers 241/53; profile unchanged", save_read_fail_text(4, 4, 0)), "FB-B2 text: save_read_fail_text code 4 step 4");
static_assert(text_is("SAVE REFUSED - non-standard reply reading registers \?; profile unchanged", save_read_fail_text(4, 9, 0)), "FB-B2 text: save_read_fail_text code 4 step 9");
static_assert(text_is("SAVE REFUSED - short reply reading registers \?; profile unchanged", save_read_fail_text(5, 0, 0)), "FB-B2 text: save_read_fail_text code 5 step 0");
static_assert(text_is("SAVE REFUSED - short reply reading registers 230/3; profile unchanged", save_read_fail_text(5, 1, 0)), "FB-B2 text: save_read_fail_text code 5 step 1");
static_assert(text_is("SAVE REFUSED - short reply reading registers 241/53; profile unchanged", save_read_fail_text(5, 2, 0)), "FB-B2 text: save_read_fail_text code 5 step 2");
static_assert(text_is("SAVE REFUSED - short reply reading registers 230/3; profile unchanged", save_read_fail_text(5, 3, 0)), "FB-B2 text: save_read_fail_text code 5 step 3");
static_assert(text_is("SAVE REFUSED - short reply reading registers 241/53; profile unchanged", save_read_fail_text(5, 4, 0)), "FB-B2 text: save_read_fail_text code 5 step 4");
static_assert(text_is("SAVE REFUSED - short reply reading registers \?; profile unchanged", save_read_fail_text(5, 9, 0)), "FB-B2 text: save_read_fail_text code 5 step 9");
static_assert(text_is("SAVE REFUSED - read of registers \? did not complete within 3 s; profile unchanged", save_read_fail_text(6, 0, 0)), "FB-B2 text: save_read_fail_text code 6 step 0");
static_assert(text_is("SAVE REFUSED - read of registers 230/3 did not complete within 3 s; profile unchanged", save_read_fail_text(6, 1, 0)), "FB-B2 text: save_read_fail_text code 6 step 1");
static_assert(text_is("SAVE REFUSED - read of registers 241/53 did not complete within 3 s; profile unchanged", save_read_fail_text(6, 2, 0)), "FB-B2 text: save_read_fail_text code 6 step 2");
static_assert(text_is("SAVE REFUSED - read of registers 230/3 did not complete within 3 s; profile unchanged", save_read_fail_text(6, 3, 0)), "FB-B2 text: save_read_fail_text code 6 step 3");
static_assert(text_is("SAVE REFUSED - read of registers 241/53 did not complete within 3 s; profile unchanged", save_read_fail_text(6, 4, 0)), "FB-B2 text: save_read_fail_text code 6 step 4");
static_assert(text_is("SAVE REFUSED - read of registers \? did not complete within 3 s; profile unchanged", save_read_fail_text(6, 9, 0)), "FB-B2 text: save_read_fail_text code 6 step 9");
static_assert(text_is("SAVE REFUSED - inverter bus stayed busy for 7 s; profile unchanged; review again", save_read_fail_text(7, 0, 0)), "FB-B2 text: save_read_fail_text code 7 step 0");
static_assert(text_is("SAVE REFUSED - inverter bus stayed busy for 7 s; profile unchanged; review again", save_read_fail_text(7, 1, 0)), "FB-B2 text: save_read_fail_text code 7 step 1");
static_assert(text_is("SAVE REFUSED - inverter bus stayed busy for 7 s; profile unchanged; review again", save_read_fail_text(7, 2, 0)), "FB-B2 text: save_read_fail_text code 7 step 2");
static_assert(text_is("SAVE REFUSED - inverter bus stayed busy for 7 s; profile unchanged; review again", save_read_fail_text(7, 3, 0)), "FB-B2 text: save_read_fail_text code 7 step 3");
static_assert(text_is("SAVE REFUSED - inverter bus stayed busy for 7 s; profile unchanged; review again", save_read_fail_text(7, 4, 0)), "FB-B2 text: save_read_fail_text code 7 step 4");
static_assert(text_is("SAVE REFUSED - inverter bus stayed busy for 7 s; profile unchanged; review again", save_read_fail_text(7, 9, 0)), "FB-B2 text: save_read_fail_text code 7 step 9");
static_assert(text_is("SAVE REFUSED - read did not complete (unknown cause); profile unchanged", save_read_fail_text(8, 0, 0)), "FB-B2 text: save_read_fail_text code 8 step 0");
static_assert(text_is("SAVE REFUSED - read did not complete (unknown cause); profile unchanged", save_read_fail_text(8, 1, 0)), "FB-B2 text: save_read_fail_text code 8 step 1");
static_assert(text_is("SAVE REFUSED - read did not complete (unknown cause); profile unchanged", save_read_fail_text(8, 2, 0)), "FB-B2 text: save_read_fail_text code 8 step 2");
static_assert(text_is("SAVE REFUSED - read did not complete (unknown cause); profile unchanged", save_read_fail_text(8, 3, 0)), "FB-B2 text: save_read_fail_text code 8 step 3");
static_assert(text_is("SAVE REFUSED - read did not complete (unknown cause); profile unchanged", save_read_fail_text(8, 4, 0)), "FB-B2 text: save_read_fail_text code 8 step 4");
static_assert(text_is("SAVE REFUSED - read did not complete (unknown cause); profile unchanged", save_read_fail_text(8, 9, 0)), "FB-B2 text: save_read_fail_text code 8 step 9");
static_assert(text_is("SAVE REFUSED - inverter returned exception code 0x02 on registers 241/53; profile unchanged", save_read_fail_text(ecco_fbcap::READ_EXCEPTION, 2, 2)), "FB-B2 text: save_read_fail_text: exception code 0x02 on step 2");
static_assert(text_is("SAVE REFUSED - inverter returned exception code 0xFF on registers 230/3; profile unchanged", save_read_fail_text(ecco_fbcap::READ_EXCEPTION, 1, 255)), "FB-B2 text: save_read_fail_text: exception code 0xFF on step 1");
static_assert(text_is("SAVE REFUSED - inverter bus stayed busy for 7 s; profile unchanged; review again", save_read_fail_text(ecco_fbcap::READ_IDLE_TIMEOUT, 0, 0)), "FB-B2 text: save_read_fail_text: the idle timeout names the bus");
static_assert(text_is("SAVE REFUSED - live configuration changed during the read (register 244: 2 then 0); profile unchanged", save_changed_during_read_text(ecco_fbcap::GOLDEN_WORDS, ecco_fbcap::golden_words_with(ecco_fbcap::GOLDEN_WORDS, 0, 0u))), "FB-B2 text: save_changed_during_read_text: first difference is register 244");
static_assert(text_is("SAVE REFUSED - live configuration changed since Review (register 244: reviewed 2, now 0); profile unchanged; review again", save_changed_since_review_text(ecco_fbcap::GOLDEN_WORDS, ecco_fbcap::golden_words_with(ecco_fbcap::GOLDEN_WORDS, 0, 0u))), "FB-B2 text: save_changed_since_review_text: first difference is register 244");
static_assert(text_is("SAVE REFUSED - live configuration changed during the read (register 256: 8000 then 501); profile unchanged", save_changed_during_read_text(ecco_fbcap::GOLDEN_WORDS, ecco_fbcap::golden_words_with(ecco_fbcap::GOLDEN_WORDS, 1, 501u))), "FB-B2 text: save_changed_during_read_text: first is 256");
static_assert(text_is("SAVE REFUSED - live configuration changed since Review (register 256: reviewed 8000, now 501); profile unchanged; review again", save_changed_since_review_text(ecco_fbcap::GOLDEN_WORDS, ecco_fbcap::golden_words_with(ecco_fbcap::GOLDEN_WORDS, 1, 501u))), "FB-B2 text: save_changed_since_review_text: first is 256");
static_assert(text_is("SAVE REFUSED - live configuration changed during the read (register 274: 1 then 3); profile unchanged", save_changed_during_read_text(ecco_fbcap::GOLDEN_WORDS, ecco_fbcap::golden_words_with(ecco_fbcap::golden_words_with(ecco_fbcap::GOLDEN_WORDS, 13, 3u), 25, 1u))), "FB-B2 text: save_changed_during_read_text: first is 274 (index 13)");
static_assert(text_is("SAVE REFUSED - live configuration changed since Review (register 274: reviewed 1, now 3); profile unchanged; review again", save_changed_since_review_text(ecco_fbcap::GOLDEN_WORDS, ecco_fbcap::golden_words_with(ecco_fbcap::golden_words_with(ecco_fbcap::GOLDEN_WORDS, 13, 3u), 25, 1u))), "FB-B2 text: save_changed_since_review_text: first is 274 (index 13)");
static_assert(text_is("SAVE REFUSED - live configuration changed during the read (register 232: 17 then 19); profile unchanged", save_changed_during_read_text(ecco_fbcap::GOLDEN_WORDS, ecco_fbcap::golden_words_with(ecco_fbcap::GOLDEN_WORDS, 19, 19u))), "FB-B2 text: save_changed_during_read_text: 232 (index 19)");
static_assert(text_is("SAVE REFUSED - live configuration changed since Review (register 232: reviewed 17, now 19); profile unchanged; review again", save_changed_since_review_text(ecco_fbcap::GOLDEN_WORDS, ecco_fbcap::golden_words_with(ecco_fbcap::GOLDEN_WORDS, 19, 19u))), "FB-B2 text: save_changed_since_review_text: 232 (index 19)");
static_assert(text_is("SAVE REFUSED - live configuration changed during the read (register 247: 1 then 65535); profile unchanged", save_changed_during_read_text(ecco_fbcap::GOLDEN_WORDS, ecco_fbcap::golden_words_with(ecco_fbcap::GOLDEN_WORDS, 30, 65535u))), "FB-B2 text: save_changed_during_read_text: 247 (index 30)");
static_assert(text_is("SAVE REFUSED - live configuration changed since Review (register 247: reviewed 1, now 65535); profile unchanged; review again", save_changed_since_review_text(ecco_fbcap::GOLDEN_WORDS, ecco_fbcap::golden_words_with(ecco_fbcap::GOLDEN_WORDS, 30, 65535u))), "FB-B2 text: save_changed_since_review_text: 247 (index 30)");
static_assert(text_is("SAVE REFUSED - live configuration changed during the read (register 260: 2000 then 1); profile unchanged", save_changed_during_read_text(ecco_fbcap::GOLDEN_WORDS, ecco_fbcap::golden_words_with(ecco_fbcap::golden_words_with(ecco_fbcap::GOLDEN_WORDS, 20, 0u), 5, 1u))), "FB-B2 text: save_changed_during_read_text: both at 5 and 20: the lower index");
static_assert(text_is("SAVE REFUSED - live configuration changed since Review (register 260: reviewed 2000, now 1); profile unchanged; review again", save_changed_since_review_text(ecco_fbcap::GOLDEN_WORDS, ecco_fbcap::golden_words_with(ecco_fbcap::golden_words_with(ecco_fbcap::GOLDEN_WORDS, 20, 0u), 5, 1u))), "FB-B2 text: save_changed_since_review_text: both at 5 and 20: the lower index");
static_assert(text_is("SAVE REFUSED - live configuration changed during the read (register 0: 0 then 0); profile unchanged", save_changed_during_read_text(ecco_fbcap::GOLDEN_WORDS, ecco_fbcap::GOLDEN_WORDS)), "FB-B2 text: save_changed_during_read_text: the passes agree");
static_assert(text_is("SAVE REFUSED - live configuration changed since Review (register 0: reviewed 0, now 0); profile unchanged; review again", save_changed_since_review_text(ecco_fbcap::GOLDEN_WORDS, ecco_fbcap::GOLDEN_WORDS)), "FB-B2 text: save_changed_since_review_text: the passes agree");
static_assert(text_is("SAVE REFUSED - live configuration changed during the read (register 244: 65535 then 0); profile unchanged", save_changed_during_read_text(ecco_fbcap::golden_words_all(65535u), ecco_fbcap::golden_words_all(0u))), "FB-B2 text: save_changed_during_read_text: widest values");
static_assert(text_is("SAVE REFUSED - live configuration changed since Review (register 244: reviewed 65535, now 0); profile unchanged; review again", save_changed_since_review_text(ecco_fbcap::golden_words_all(65535u), ecco_fbcap::golden_words_all(0u))), "FB-B2 text: save_changed_since_review_text: widest values");
static_assert(text_is("SAVE REFUSED - 244=0 Allow Export - V1 can only save a Zero Export profile; profile unchanged", save_l2_text(ecco_fbcap::capture_refusals(ecco_fbcap::golden_words_with(ecco_fbcap::GOLDEN_WORDS, 0, 0u), 8000u), ecco_fbcap::golden_words_with(ecco_fbcap::GOLDEN_WORDS, 0, 0u))), "FB-B2 text: save_l2_text: one refusal");
static_assert(text_is("SAVE REFUSED - 244=0 Allow Export - V1 can only save a Zero Export profile; slot 1 power 499 W < 500 W (V1 minimum); profile unchanged", save_l2_text(ecco_fbcap::capture_refusals(ecco_fbcap::golden_words_with(ecco_fbcap::golden_words_with(ecco_fbcap::GOLDEN_WORDS, 0, 0u), 1, 499u), 8000u), ecco_fbcap::golden_words_with(ecco_fbcap::golden_words_with(ecco_fbcap::GOLDEN_WORDS, 0, 0u), 1, 499u))), "FB-B2 text: save_l2_text: two refusals");
static_assert(text_is("SAVE REFUSED - 244=0 Allow Export - V1 can only save a Zero Export profile; slot 1 power 499 W < 500 W (V1 minimum); +1 more; profile unchanged", save_l2_text(ecco_fbcap::capture_refusals(ecco_fbcap::golden_words_with(ecco_fbcap::golden_words_with(ecco_fbcap::golden_words_with(ecco_fbcap::GOLDEN_WORDS, 0, 0u), 1, 499u), 8, 101u), 8000u), ecco_fbcap::golden_words_with(ecco_fbcap::golden_words_with(ecco_fbcap::golden_words_with(ecco_fbcap::GOLDEN_WORDS, 0, 0u), 1, 499u), 8, 101u))), "FB-B2 text: save_l2_text: three refusals: +1 more");
static_assert(text_is("SAVE REFUSED - 244=65535 unrecognised; slot 1 power 65535 W > 8000 W; +36 more; profile unchanged", save_l2_text(ecco_fbcap::capture_refusals(ecco_fbcap::golden_words_all(65535u), 8000u), ecco_fbcap::golden_words_all(65535u))), "FB-B2 text: save_l2_text: every refusal");
static_assert(text_is("SAVE REFUSED - slot 3 source Generator / Grid+Generator unsupported in V1; slot 3 mode General/Backup/Charge unsupported in V1; +1 more; profile unchanged", save_l2_text(ecco_fbcap::capture_refusals(ecco_fbcap::golden_words_with(ecco_fbcap::GOLDEN_WORDS, 15, 39u), 8000u), ecco_fbcap::golden_words_with(ecco_fbcap::GOLDEN_WORDS, 15, 39u))), "FB-B2 text: save_l2_text: a source refusal");
static_assert(text_is("SAVE REFUSED - 243=7 is not a recognised energy-management mode (0 or 1); profile unchanged", save_l2_text(ecco_fbcap::capture_refusals(ecco_fbcap::golden_words_with(ecco_fbcap::GOLDEN_WORDS, 20, 7u), 8000u), ecco_fbcap::golden_words_with(ecco_fbcap::GOLDEN_WORDS, 20, 7u))), "FB-B2 text: save_l2_text: 243");
static_assert(text_is("SAVE REFUSED - reason unavailable; profile unchanged", save_l2_text(ecco_fbcap::capture_refusals(ecco_fbcap::GOLDEN_WORDS, 8000u), ecco_fbcap::GOLDEN_WORDS)), "FB-B2 text: save_l2_text: no refusal at all");
static_assert(([]{ const InvalidateGateResult r = ig_run(IG_CASES[0]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8); }()) == 1, "FB-B2 value: ig row 0: code | arm_off_only << 8");
static_assert(text_is("", []{ const InvalidateGateResult r = ig_run(IG_CASES[0]); return r.text; }()), "FB-B2 text: ig row 0: text");
static_assert(([]{ const InvalidateGateResult r = ig_run(IG_CASES[1]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8); }()) == 1, "FB-B2 value: ig row 1: code | arm_off_only << 8");
static_assert(text_is("", []{ const InvalidateGateResult r = ig_run(IG_CASES[1]); return r.text; }()), "FB-B2 text: ig row 1: text");
static_assert(([]{ const InvalidateGateResult r = ig_run(IG_CASES[2]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8); }()) == 1, "FB-B2 value: ig row 2: code | arm_off_only << 8");
static_assert(text_is("", []{ const InvalidateGateResult r = ig_run(IG_CASES[2]); return r.text; }()), "FB-B2 text: ig row 2: text");
static_assert(([]{ const InvalidateGateResult r = ig_run(IG_CASES[3]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8); }()) == 1, "FB-B2 value: ig row 3: code | arm_off_only << 8");
static_assert(text_is("", []{ const InvalidateGateResult r = ig_run(IG_CASES[3]); return r.text; }()), "FB-B2 text: ig row 3: text");
static_assert(([]{ const InvalidateGateResult r = ig_run(IG_CASES[4]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8); }()) == 1, "FB-B2 value: ig row 4: code | arm_off_only << 8");
static_assert(text_is("", []{ const InvalidateGateResult r = ig_run(IG_CASES[4]); return r.text; }()), "FB-B2 text: ig row 4: text");
static_assert(([]{ const InvalidateGateResult r = ig_run(IG_CASES[5]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8); }()) == 1, "FB-B2 value: ig row 5: code | arm_off_only << 8");
static_assert(text_is("", []{ const InvalidateGateResult r = ig_run(IG_CASES[5]); return r.text; }()), "FB-B2 text: ig row 5: text");
static_assert(([]{ const InvalidateGateResult r = ig_run(IG_CASES[6]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8); }()) == 1, "FB-B2 value: ig row 6: code | arm_off_only << 8");
static_assert(text_is("", []{ const InvalidateGateResult r = ig_run(IG_CASES[6]); return r.text; }()), "FB-B2 text: ig row 6: text");
static_assert(([]{ const InvalidateGateResult r = ig_run(IG_CASES[7]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8); }()) == 1, "FB-B2 value: ig row 7: code | arm_off_only << 8");
static_assert(text_is("", []{ const InvalidateGateResult r = ig_run(IG_CASES[7]); return r.text; }()), "FB-B2 text: ig row 7: text");
static_assert(([]{ const InvalidateGateResult r = ig_run(IG_CASES[8]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8); }()) == 1, "FB-B2 value: ig row 8: code | arm_off_only << 8");
static_assert(text_is("", []{ const InvalidateGateResult r = ig_run(IG_CASES[8]); return r.text; }()), "FB-B2 text: ig row 8: text");
static_assert(([]{ const InvalidateGateResult r = ig_run(IG_CASES[9]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8); }()) == 258, "FB-B2 value: ig row 9: code | arm_off_only << 8");
static_assert(text_is("INVALIDATE REFUSED - another Fallback Profile operation is in progress", []{ const InvalidateGateResult r = ig_run(IG_CASES[9]); return r.text; }()), "FB-B2 text: ig row 9: text");
static_assert(([]{ const InvalidateGateResult r = ig_run(IG_CASES[10]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8); }()) == 258, "FB-B2 value: ig row 10: code | arm_off_only << 8");
static_assert(text_is("INVALIDATE REFUSED - another Fallback Profile operation is in progress", []{ const InvalidateGateResult r = ig_run(IG_CASES[10]); return r.text; }()), "FB-B2 text: ig row 10: text");
static_assert(([]{ const InvalidateGateResult r = ig_run(IG_CASES[11]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8); }()) == 258, "FB-B2 value: ig row 11: code | arm_off_only << 8");
static_assert(text_is("INVALIDATE REFUSED - another Fallback Profile operation is in progress", []{ const InvalidateGateResult r = ig_run(IG_CASES[11]); return r.text; }()), "FB-B2 text: ig row 11: text");
static_assert(([]{ const InvalidateGateResult r = ig_run(IG_CASES[12]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8); }()) == 3, "FB-B2 value: ig row 12: code | arm_off_only << 8");
static_assert(text_is("REFUSED - unsupported action 'SAVE'", []{ const InvalidateGateResult r = ig_run(IG_CASES[12]); return r.text; }()), "FB-B2 text: ig row 12: text");
static_assert(([]{ const InvalidateGateResult r = ig_run(IG_CASES[13]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8); }()) == 3, "FB-B2 value: ig row 13: code | arm_off_only << 8");
static_assert(text_is("RESTORE REFUSED - not implemented in this firmware", []{ const InvalidateGateResult r = ig_run(IG_CASES[13]); return r.text; }()), "FB-B2 text: ig row 13: text");
static_assert(([]{ const InvalidateGateResult r = ig_run(IG_CASES[14]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8); }()) == 3, "FB-B2 value: ig row 14: code | arm_off_only << 8");
static_assert(text_is("ACKNOWLEDGE REFUSED - not implemented in this firmware", []{ const InvalidateGateResult r = ig_run(IG_CASES[14]); return r.text; }()), "FB-B2 text: ig row 14: text");
static_assert(([]{ const InvalidateGateResult r = ig_run(IG_CASES[15]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8); }()) == 3, "FB-B2 value: ig row 15: code | arm_off_only << 8");
static_assert(text_is("REFUSED - unsupported action 'CAPTURE'", []{ const InvalidateGateResult r = ig_run(IG_CASES[15]); return r.text; }()), "FB-B2 text: ig row 15: text");
static_assert(([]{ const InvalidateGateResult r = ig_run(IG_CASES[16]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8); }()) == 3, "FB-B2 value: ig row 16: code | arm_off_only << 8");
static_assert(text_is("REFUSED - unsupported action ''", []{ const InvalidateGateResult r = ig_run(IG_CASES[16]); return r.text; }()), "FB-B2 text: ig row 16: text");
static_assert(([]{ const InvalidateGateResult r = ig_run(IG_CASES[17]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8); }()) == 3, "FB-B2 value: ig row 17: code | arm_off_only << 8");
static_assert(text_is("REFUSED - unsupported action 'invalidate'", []{ const InvalidateGateResult r = ig_run(IG_CASES[17]); return r.text; }()), "FB-B2 text: ig row 17: text");
static_assert(([]{ const InvalidateGateResult r = ig_run(IG_CASES[18]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8); }()) == 3, "FB-B2 value: ig row 18: code | arm_off_only << 8");
static_assert(text_is("REFUSED - unsupported action 'INVALIDATE\?'", []{ const InvalidateGateResult r = ig_run(IG_CASES[18]); return r.text; }()), "FB-B2 text: ig row 18: text");
static_assert(([]{ const InvalidateGateResult r = ig_run(IG_CASES[19]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8); }()) == 3, "FB-B2 value: ig row 19: code | arm_off_only << 8");
static_assert(text_is("REFUSED - unsupported action 'INVALIDATE\?x'", []{ const InvalidateGateResult r = ig_run(IG_CASES[19]); return r.text; }()), "FB-B2 text: ig row 19: text");
static_assert(([]{ const InvalidateGateResult r = ig_run(IG_CASES[20]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8); }()) == 3, "FB-B2 value: ig row 20: code | arm_off_only << 8");
static_assert(text_is("REFUSED - unsupported action 'SAVE'", []{ const InvalidateGateResult r = ig_run(IG_CASES[20]); return r.text; }()), "FB-B2 text: ig row 20: text");
static_assert(([]{ const InvalidateGateResult r = ig_run(IG_CASES[21]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8); }()) == 4, "FB-B2 value: ig row 21: code | arm_off_only << 8");
static_assert(text_is("INVALIDATE REFUSED - ECCO Fallback Profile Arm is not on", []{ const InvalidateGateResult r = ig_run(IG_CASES[21]); return r.text; }()), "FB-B2 text: ig row 21: text");
static_assert(([]{ const InvalidateGateResult r = ig_run(IG_CASES[22]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8); }()) == 5, "FB-B2 value: ig row 22: code | arm_off_only << 8");
static_assert(text_is("INVALIDATE REFUSED - profile ID must be 16 hex characters", []{ const InvalidateGateResult r = ig_run(IG_CASES[22]); return r.text; }()), "FB-B2 text: ig row 22: text");
static_assert(([]{ const InvalidateGateResult r = ig_run(IG_CASES[23]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8); }()) == 5, "FB-B2 value: ig row 23: code | arm_off_only << 8");
static_assert(text_is("INVALIDATE REFUSED - profile ID must be 16 hex characters", []{ const InvalidateGateResult r = ig_run(IG_CASES[23]); return r.text; }()), "FB-B2 text: ig row 23: text");
static_assert(([]{ const InvalidateGateResult r = ig_run(IG_CASES[24]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8); }()) == 5, "FB-B2 value: ig row 24: code | arm_off_only << 8");
static_assert(text_is("INVALIDATE REFUSED - profile ID must be 16 hex characters", []{ const InvalidateGateResult r = ig_run(IG_CASES[24]); return r.text; }()), "FB-B2 text: ig row 24: text");
static_assert(([]{ const InvalidateGateResult r = ig_run(IG_CASES[25]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8); }()) == 5, "FB-B2 value: ig row 25: code | arm_off_only << 8");
static_assert(text_is("INVALIDATE REFUSED - profile ID must be 16 hex characters", []{ const InvalidateGateResult r = ig_run(IG_CASES[25]); return r.text; }()), "FB-B2 text: ig row 25: text");
static_assert(([]{ const InvalidateGateResult r = ig_run(IG_CASES[26]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8); }()) == 5, "FB-B2 value: ig row 26: code | arm_off_only << 8");
static_assert(text_is("INVALIDATE REFUSED - profile ID must be 16 hex characters", []{ const InvalidateGateResult r = ig_run(IG_CASES[26]); return r.text; }()), "FB-B2 text: ig row 26: text");
static_assert(([]{ const InvalidateGateResult r = ig_run(IG_CASES[27]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8); }()) == 5, "FB-B2 value: ig row 27: code | arm_off_only << 8");
static_assert(text_is("INVALIDATE REFUSED - profile ID must be 16 hex characters", []{ const InvalidateGateResult r = ig_run(IG_CASES[27]); return r.text; }()), "FB-B2 text: ig row 27: text");
static_assert(([]{ const InvalidateGateResult r = ig_run(IG_CASES[28]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8); }()) == 5, "FB-B2 value: ig row 28: code | arm_off_only << 8");
static_assert(text_is("INVALIDATE REFUSED - profile ID must be 16 hex characters", []{ const InvalidateGateResult r = ig_run(IG_CASES[28]); return r.text; }()), "FB-B2 text: ig row 28: text");
static_assert(([]{ const InvalidateGateResult r = ig_run(IG_CASES[29]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8); }()) == 5, "FB-B2 value: ig row 29: code | arm_off_only << 8");
static_assert(text_is("INVALIDATE REFUSED - profile ID must be 16 hex characters", []{ const InvalidateGateResult r = ig_run(IG_CASES[29]); return r.text; }()), "FB-B2 text: ig row 29: text");
static_assert(([]{ const InvalidateGateResult r = ig_run(IG_CASES[30]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8); }()) == 5, "FB-B2 value: ig row 30: code | arm_off_only << 8");
static_assert(text_is("INVALIDATE REFUSED - profile ID must be 16 hex characters", []{ const InvalidateGateResult r = ig_run(IG_CASES[30]); return r.text; }()), "FB-B2 text: ig row 30: text");
static_assert(([]{ const InvalidateGateResult r = ig_run(IG_CASES[31]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8); }()) == 5, "FB-B2 value: ig row 31: code | arm_off_only << 8");
static_assert(text_is("INVALIDATE REFUSED - profile ID must be 16 hex characters", []{ const InvalidateGateResult r = ig_run(IG_CASES[31]); return r.text; }()), "FB-B2 text: ig row 31: text");
static_assert(([]{ const InvalidateGateResult r = ig_run(IG_CASES[32]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8); }()) == 6, "FB-B2 value: ig row 32: code | arm_off_only << 8");
static_assert(text_is("INVALIDATE REFUSED - confirmation phrase mismatch (expected 'INVALIDATE D852A4FA2DF7DBA3')", []{ const InvalidateGateResult r = ig_run(IG_CASES[32]); return r.text; }()), "FB-B2 text: ig row 32: text");
static_assert(([]{ const InvalidateGateResult r = ig_run(IG_CASES[33]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8); }()) == 6, "FB-B2 value: ig row 33: code | arm_off_only << 8");
static_assert(text_is("INVALIDATE REFUSED - confirmation phrase mismatch (expected 'INVALIDATE D852A4FA2DF7DBA3')", []{ const InvalidateGateResult r = ig_run(IG_CASES[33]); return r.text; }()), "FB-B2 text: ig row 33: text");
static_assert(([]{ const InvalidateGateResult r = ig_run(IG_CASES[34]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8); }()) == 6, "FB-B2 value: ig row 34: code | arm_off_only << 8");
static_assert(text_is("INVALIDATE REFUSED - confirmation phrase mismatch (expected 'INVALIDATE D852A4FA2DF7DBA3')", []{ const InvalidateGateResult r = ig_run(IG_CASES[34]); return r.text; }()), "FB-B2 text: ig row 34: text");
static_assert(([]{ const InvalidateGateResult r = ig_run(IG_CASES[35]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8); }()) == 6, "FB-B2 value: ig row 35: code | arm_off_only << 8");
static_assert(text_is("INVALIDATE REFUSED - confirmation phrase mismatch (expected 'INVALIDATE D852A4FA2DF7DBA3')", []{ const InvalidateGateResult r = ig_run(IG_CASES[35]); return r.text; }()), "FB-B2 text: ig row 35: text");
static_assert(([]{ const InvalidateGateResult r = ig_run(IG_CASES[36]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8); }()) == 6, "FB-B2 value: ig row 36: code | arm_off_only << 8");
static_assert(text_is("INVALIDATE REFUSED - confirmation phrase mismatch (expected 'INVALIDATE D852A4FA2DF7DBA3')", []{ const InvalidateGateResult r = ig_run(IG_CASES[36]); return r.text; }()), "FB-B2 text: ig row 36: text");
static_assert(([]{ const InvalidateGateResult r = ig_run(IG_CASES[37]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8); }()) == 6, "FB-B2 value: ig row 37: code | arm_off_only << 8");
static_assert(text_is("INVALIDATE REFUSED - confirmation phrase mismatch (expected 'INVALIDATE D852A4FA2DF7DBA3')", []{ const InvalidateGateResult r = ig_run(IG_CASES[37]); return r.text; }()), "FB-B2 text: ig row 37: text");
static_assert(([]{ const InvalidateGateResult r = ig_run(IG_CASES[38]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8); }()) == 6, "FB-B2 value: ig row 38: code | arm_off_only << 8");
static_assert(text_is("INVALIDATE REFUSED - confirmation phrase mismatch (expected 'INVALIDATE D852A4FA2DF7DBA3')", []{ const InvalidateGateResult r = ig_run(IG_CASES[38]); return r.text; }()), "FB-B2 text: ig row 38: text");
static_assert(([]{ const InvalidateGateResult r = ig_run(IG_CASES[39]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8); }()) == 6, "FB-B2 value: ig row 39: code | arm_off_only << 8");
static_assert(text_is("INVALIDATE REFUSED - confirmation phrase mismatch (expected 'INVALIDATE D852A4FA2DF7DBA3')", []{ const InvalidateGateResult r = ig_run(IG_CASES[39]); return r.text; }()), "FB-B2 text: ig row 39: text");
static_assert(([]{ const InvalidateGateResult r = ig_run(IG_CASES[40]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8); }()) == 6, "FB-B2 value: ig row 40: code | arm_off_only << 8");
static_assert(text_is("INVALIDATE REFUSED - confirmation phrase mismatch (expected 'INVALIDATE D852A4FA2DF7DBA3')", []{ const InvalidateGateResult r = ig_run(IG_CASES[40]); return r.text; }()), "FB-B2 text: ig row 40: text");
static_assert(([]{ const InvalidateGateResult r = ig_run(IG_CASES[41]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8); }()) == 6, "FB-B2 value: ig row 41: code | arm_off_only << 8");
static_assert(text_is("INVALIDATE REFUSED - confirmation phrase mismatch (expected 'INVALIDATE D852A4FA2DF7DBA3')", []{ const InvalidateGateResult r = ig_run(IG_CASES[41]); return r.text; }()), "FB-B2 text: ig row 41: text");
static_assert(([]{ const InvalidateGateResult r = ig_run(IG_CASES[42]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8); }()) == 6, "FB-B2 value: ig row 42: code | arm_off_only << 8");
static_assert(text_is("INVALIDATE REFUSED - confirmation phrase mismatch (expected 'INVALIDATE D852A4FA2DF7DBA2')", []{ const InvalidateGateResult r = ig_run(IG_CASES[42]); return r.text; }()), "FB-B2 text: ig row 42: text");
static_assert(([]{ const InvalidateGateResult r = ig_run(IG_CASES[43]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8); }()) == 6, "FB-B2 value: ig row 43: code | arm_off_only << 8");
static_assert(text_is("INVALIDATE REFUSED - confirmation phrase mismatch (expected 'INVALIDATE D852A4FA2DF7DBA3')", []{ const InvalidateGateResult r = ig_run(IG_CASES[43]); return r.text; }()), "FB-B2 text: ig row 43: text");
static_assert(([]{ const InvalidateGateResult r = ig_run(IG_CASES[44]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8); }()) == 7, "FB-B2 value: ig row 44: code | arm_off_only << 8");
static_assert(text_is("INVALIDATE REFUSED - durable state not loaded yet (starting up)", []{ const InvalidateGateResult r = ig_run(IG_CASES[44]); return r.text; }()), "FB-B2 text: ig row 44: text");
static_assert(([]{ const InvalidateGateResult r = ig_run(IG_CASES[45]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8); }()) == 7, "FB-B2 value: ig row 45: code | arm_off_only << 8");
static_assert(text_is("INVALIDATE REFUSED - durable state not loaded yet (starting up)", []{ const InvalidateGateResult r = ig_run(IG_CASES[45]); return r.text; }()), "FB-B2 text: ig row 45: text");
static_assert(([]{ const InvalidateGateResult r = ig_run(IG_CASES[46]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8); }()) == 8, "FB-B2 value: ig row 46: code | arm_off_only << 8");
static_assert(text_is("INVALIDATE REFUSED - stored profile read anomaly this boot; reboot to re-derive first", []{ const InvalidateGateResult r = ig_run(IG_CASES[46]); return r.text; }()), "FB-B2 text: ig row 46: text");
static_assert(([]{ const InvalidateGateResult r = ig_run(IG_CASES[47]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8); }()) == 8, "FB-B2 value: ig row 47: code | arm_off_only << 8");
static_assert(text_is("INVALIDATE REFUSED - stored profile read anomaly this boot; reboot to re-derive first", []{ const InvalidateGateResult r = ig_run(IG_CASES[47]); return r.text; }()), "FB-B2 text: ig row 47: text");
static_assert(([]{ const InvalidateGateResult r = ig_run(IG_CASES[48]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8); }()) == 8, "FB-B2 value: ig row 48: code | arm_off_only << 8");
static_assert(text_is("INVALIDATE REFUSED - stored profile read anomaly this boot; reboot to re-derive first", []{ const InvalidateGateResult r = ig_run(IG_CASES[48]); return r.text; }()), "FB-B2 text: ig row 48: text");
static_assert(([]{ const InvalidateGateResult r = ig_run(IG_CASES[49]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8); }()) == 8, "FB-B2 value: ig row 49: code | arm_off_only << 8");
static_assert(text_is("INVALIDATE REFUSED - stored profile read anomaly this boot; reboot to re-derive first", []{ const InvalidateGateResult r = ig_run(IG_CASES[49]); return r.text; }()), "FB-B2 text: ig row 49: text");
static_assert(([]{ const InvalidateGateResult r = ig_run(IG_CASES[50]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8); }()) == 8, "FB-B2 value: ig row 50: code | arm_off_only << 8");
static_assert(text_is("INVALIDATE REFUSED - stored profile read anomaly this boot; reboot to re-derive first", []{ const InvalidateGateResult r = ig_run(IG_CASES[50]); return r.text; }()), "FB-B2 text: ig row 50: text");
static_assert(([]{ const InvalidateGateResult r = ig_run(IG_CASES[51]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8); }()) == 8, "FB-B2 value: ig row 51: code | arm_off_only << 8");
static_assert(text_is("INVALIDATE REFUSED - stored profile read anomaly this boot; reboot to re-derive first", []{ const InvalidateGateResult r = ig_run(IG_CASES[51]); return r.text; }()), "FB-B2 text: ig row 51: text");
static_assert(([]{ const InvalidateGateResult r = ig_run(IG_CASES[52]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8); }()) == 9, "FB-B2 value: ig row 52: code | arm_off_only << 8");
static_assert(text_is("INVALIDATE REFUSED - previous Fallback Profile write outcome unknown this boot - reboot to re-verify first", []{ const InvalidateGateResult r = ig_run(IG_CASES[52]); return r.text; }()), "FB-B2 text: ig row 52: text");
static_assert(([]{ const InvalidateGateResult r = ig_run(IG_CASES[53]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8); }()) == 9, "FB-B2 value: ig row 53: code | arm_off_only << 8");
static_assert(text_is("INVALIDATE REFUSED - previous Fallback Profile write outcome unknown this boot - reboot to re-verify first", []{ const InvalidateGateResult r = ig_run(IG_CASES[53]); return r.text; }()), "FB-B2 text: ig row 53: text");
static_assert(([]{ const InvalidateGateResult r = ig_run(IG_CASES[54]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8); }()) == 10, "FB-B2 value: ig row 54: code | arm_off_only << 8");
static_assert(text_is("INVALIDATE REFUSED - profile is INVALIDATED; only a VALID profile can be invalidated", []{ const InvalidateGateResult r = ig_run(IG_CASES[54]); return r.text; }()), "FB-B2 text: ig row 54: text");
static_assert(([]{ const InvalidateGateResult r = ig_run(IG_CASES[55]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8); }()) == 10, "FB-B2 value: ig row 55: code | arm_off_only << 8");
static_assert(text_is("INVALIDATE REFUSED - profile is CORRUPT_DOMAIN; only a VALID profile can be invalidated", []{ const InvalidateGateResult r = ig_run(IG_CASES[55]); return r.text; }()), "FB-B2 text: ig row 55: text");
static_assert(([]{ const InvalidateGateResult r = ig_run(IG_CASES[56]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8); }()) == 10, "FB-B2 value: ig row 56: code | arm_off_only << 8");
static_assert(text_is("INVALIDATE REFUSED - profile is CORRUPT; only a VALID profile can be invalidated", []{ const InvalidateGateResult r = ig_run(IG_CASES[56]); return r.text; }()), "FB-B2 text: ig row 56: text");
static_assert(([]{ const InvalidateGateResult r = ig_run(IG_CASES[57]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8); }()) == 10, "FB-B2 value: ig row 57: code | arm_off_only << 8");
static_assert(text_is("INVALIDATE REFUSED - profile is CORRUPT; only a VALID profile can be invalidated", []{ const InvalidateGateResult r = ig_run(IG_CASES[57]); return r.text; }()), "FB-B2 text: ig row 57: text");
static_assert(([]{ const InvalidateGateResult r = ig_run(IG_CASES[58]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8); }()) == 10, "FB-B2 value: ig row 58: code | arm_off_only << 8");
static_assert(text_is("INVALIDATE REFUSED - profile is UNREADABLE; only a VALID profile can be invalidated", []{ const InvalidateGateResult r = ig_run(IG_CASES[58]); return r.text; }()), "FB-B2 text: ig row 58: text");
static_assert(([]{ const InvalidateGateResult r = ig_run(IG_CASES[59]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8); }()) == 10, "FB-B2 value: ig row 59: code | arm_off_only << 8");
static_assert(text_is("INVALIDATE REFUSED - profile is UNREADABLE; only a VALID profile can be invalidated", []{ const InvalidateGateResult r = ig_run(IG_CASES[59]); return r.text; }()), "FB-B2 text: ig row 59: text");
static_assert(([]{ const InvalidateGateResult r = ig_run(IG_CASES[60]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8); }()) == 10, "FB-B2 value: ig row 60: code | arm_off_only << 8");
static_assert(text_is("INVALIDATE REFUSED - profile is NOT_CAPTURED; only a VALID profile can be invalidated", []{ const InvalidateGateResult r = ig_run(IG_CASES[60]); return r.text; }()), "FB-B2 text: ig row 60: text");
static_assert(([]{ const InvalidateGateResult r = ig_run(IG_CASES[61]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8); }()) == 10, "FB-B2 value: ig row 61: code | arm_off_only << 8");
static_assert(text_is("INVALIDATE REFUSED - profile is PROFILE_LOST; only a VALID profile can be invalidated", []{ const InvalidateGateResult r = ig_run(IG_CASES[61]); return r.text; }()), "FB-B2 text: ig row 61: text");
static_assert(([]{ const InvalidateGateResult r = ig_run(IG_CASES[62]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8); }()) == 10, "FB-B2 value: ig row 62: code | arm_off_only << 8");
static_assert(text_is("INVALIDATE REFUSED - profile is PROFILE_STALE; only a VALID profile can be invalidated", []{ const InvalidateGateResult r = ig_run(IG_CASES[62]); return r.text; }()), "FB-B2 text: ig row 62: text");
static_assert(([]{ const InvalidateGateResult r = ig_run(IG_CASES[63]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8); }()) == 10, "FB-B2 value: ig row 63: code | arm_off_only << 8");
static_assert(text_is("INVALIDATE REFUSED - profile is PROFILE_STALE; only a VALID profile can be invalidated", []{ const InvalidateGateResult r = ig_run(IG_CASES[63]); return r.text; }()), "FB-B2 text: ig row 63: text");
static_assert(([]{ const InvalidateGateResult r = ig_run(IG_CASES[64]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8); }()) == 10, "FB-B2 value: ig row 64: code | arm_off_only << 8");
static_assert(text_is("INVALIDATE REFUSED - profile is PROFILE_STALE; only a VALID profile can be invalidated", []{ const InvalidateGateResult r = ig_run(IG_CASES[64]); return r.text; }()), "FB-B2 text: ig row 64: text");
static_assert(([]{ const InvalidateGateResult r = ig_run(IG_CASES[65]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8); }()) == 10, "FB-B2 value: ig row 65: code | arm_off_only << 8");
static_assert(text_is("INVALIDATE REFUSED - profile is PROFILE_STALE; only a VALID profile can be invalidated", []{ const InvalidateGateResult r = ig_run(IG_CASES[65]); return r.text; }()), "FB-B2 text: ig row 65: text");
static_assert(([]{ const InvalidateGateResult r = ig_run(IG_CASES[66]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8); }()) == 10, "FB-B2 value: ig row 66: code | arm_off_only << 8");
static_assert(text_is("INVALIDATE REFUSED - profile is UNREADABLE; only a VALID profile can be invalidated", []{ const InvalidateGateResult r = ig_run(IG_CASES[66]); return r.text; }()), "FB-B2 text: ig row 66: text");
static_assert(([]{ const InvalidateGateResult r = ig_run(IG_CASES[67]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8); }()) == 10, "FB-B2 value: ig row 67: code | arm_off_only << 8");
static_assert(text_is("INVALIDATE REFUSED - profile is SAVE_UNCONFIRMED; only a VALID profile can be invalidated", []{ const InvalidateGateResult r = ig_run(IG_CASES[67]); return r.text; }()), "FB-B2 text: ig row 67: text");
static_assert(([]{ const InvalidateGateResult r = ig_run(IG_CASES[68]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8); }()) == 10, "FB-B2 value: ig row 68: code | arm_off_only << 8");
static_assert(text_is("INVALIDATE REFUSED - profile is UNREADABLE; only a VALID profile can be invalidated", []{ const InvalidateGateResult r = ig_run(IG_CASES[68]); return r.text; }()), "FB-B2 text: ig row 68: text");
static_assert(([]{ const InvalidateGateResult r = ig_run(IG_CASES[69]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8); }()) == 10, "FB-B2 value: ig row 69: code | arm_off_only << 8");
static_assert(text_is("INVALIDATE REFUSED - profile is INVALIDATED; only a VALID profile can be invalidated", []{ const InvalidateGateResult r = ig_run(IG_CASES[69]); return r.text; }()), "FB-B2 text: ig row 69: text");
static_assert(([]{ const InvalidateGateResult r = ig_run(IG_CASES[70]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8); }()) == 11, "FB-B2 value: ig row 70: code | arm_off_only << 8");
static_assert(text_is("INVALIDATE REFUSED - profile ID does not match the stored VALID profile", []{ const InvalidateGateResult r = ig_run(IG_CASES[70]); return r.text; }()), "FB-B2 text: ig row 70: text");
static_assert(([]{ const InvalidateGateResult r = ig_run(IG_CASES[71]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8); }()) == 11, "FB-B2 value: ig row 71: code | arm_off_only << 8");
static_assert(text_is("INVALIDATE REFUSED - profile ID does not match the stored VALID profile", []{ const InvalidateGateResult r = ig_run(IG_CASES[71]); return r.text; }()), "FB-B2 text: ig row 71: text");
static_assert(([]{ const InvalidateGateResult r = ig_run(IG_CASES[72]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8); }()) == 11, "FB-B2 value: ig row 72: code | arm_off_only << 8");
static_assert(text_is("INVALIDATE REFUSED - profile ID does not match the stored VALID profile", []{ const InvalidateGateResult r = ig_run(IG_CASES[72]); return r.text; }()), "FB-B2 text: ig row 72: text");
static_assert(([]{ const InvalidateGateResult r = ig_run(IG_CASES[73]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8); }()) == 11, "FB-B2 value: ig row 73: code | arm_off_only << 8");
static_assert(text_is("INVALIDATE REFUSED - profile ID does not match the stored VALID profile", []{ const InvalidateGateResult r = ig_run(IG_CASES[73]); return r.text; }()), "FB-B2 text: ig row 73: text");
static_assert(([]{ const InvalidateGateResult r = ig_run(IG_CASES[74]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8); }()) == 11, "FB-B2 value: ig row 74: code | arm_off_only << 8");
static_assert(text_is("INVALIDATE REFUSED - profile ID does not match the stored VALID profile", []{ const InvalidateGateResult r = ig_run(IG_CASES[74]); return r.text; }()), "FB-B2 text: ig row 74: text");
static_assert(([]{ const InvalidateGateResult r = ig_run(IG_CASES[75]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8); }()) == 11, "FB-B2 value: ig row 75: code | arm_off_only << 8");
static_assert(text_is("INVALIDATE REFUSED - profile ID does not match the stored VALID profile", []{ const InvalidateGateResult r = ig_run(IG_CASES[75]); return r.text; }()), "FB-B2 text: ig row 75: text");
static_assert(([]{ const InvalidateGateResult r = ig_run(IG_CASES[76]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8); }()) == 11, "FB-B2 value: ig row 76: code | arm_off_only << 8");
static_assert(text_is("INVALIDATE REFUSED - profile ID does not match the stored VALID profile", []{ const InvalidateGateResult r = ig_run(IG_CASES[76]); return r.text; }()), "FB-B2 text: ig row 76: text");
static_assert(([]{ const InvalidateGateResult r = ig_run(IG_CASES[77]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8); }()) == 12, "FB-B2 value: ig row 77: code | arm_off_only << 8");
static_assert(text_is("INVALIDATE REFUSED - profile generation is not ahead of this boot's generation high-water mark; reboot to re-verify", []{ const InvalidateGateResult r = ig_run(IG_CASES[77]); return r.text; }()), "FB-B2 text: ig row 77: text");
static_assert(([]{ const InvalidateGateResult r = ig_run(IG_CASES[78]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8); }()) == 1, "FB-B2 value: ig row 78: code | arm_off_only << 8");
static_assert(text_is("", []{ const InvalidateGateResult r = ig_run(IG_CASES[78]); return r.text; }()), "FB-B2 text: ig row 78: text");
static_assert(([]{ const InvalidateGateResult r = ig_run(IG_CASES[79]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8); }()) == 1, "FB-B2 value: ig row 79: code | arm_off_only << 8");
static_assert(text_is("", []{ const InvalidateGateResult r = ig_run(IG_CASES[79]); return r.text; }()), "FB-B2 text: ig row 79: text");
static_assert(([]{ const InvalidateGateResult r = ig_run(IG_CASES[80]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8); }()) == 1, "FB-B2 value: ig row 80: code | arm_off_only << 8");
static_assert(text_is("", []{ const InvalidateGateResult r = ig_run(IG_CASES[80]); return r.text; }()), "FB-B2 text: ig row 80: text");
static_assert(([]{ const InvalidateGateResult r = ig_run(IG_CASES[81]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8); }()) == 12, "FB-B2 value: ig row 81: code | arm_off_only << 8");
static_assert(text_is("INVALIDATE REFUSED - profile generation is not ahead of this boot's generation high-water mark; reboot to re-verify", []{ const InvalidateGateResult r = ig_run(IG_CASES[81]); return r.text; }()), "FB-B2 text: ig row 81: text");
static_assert(([]{ const InvalidateGateResult r = ig_run(IG_CASES[82]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8); }()) == 12, "FB-B2 value: ig row 82: code | arm_off_only << 8");
static_assert(text_is("INVALIDATE REFUSED - profile generation is not ahead of this boot's generation high-water mark; reboot to re-verify", []{ const InvalidateGateResult r = ig_run(IG_CASES[82]); return r.text; }()), "FB-B2 text: ig row 82: text");
static_assert(([]{ const InvalidateGateResult r = ig_run(IG_CASES[83]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8); }()) == 12, "FB-B2 value: ig row 83: code | arm_off_only << 8");
static_assert(text_is("INVALIDATE REFUSED - generation counter exhausted", []{ const InvalidateGateResult r = ig_run(IG_CASES[83]); return r.text; }()), "FB-B2 text: ig row 83: text");
static_assert(([]{ const InvalidateGateResult r = ig_run(IG_CASES[84]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8); }()) == 12, "FB-B2 value: ig row 84: code | arm_off_only << 8");
static_assert(text_is("INVALIDATE REFUSED - generation counter exhausted", []{ const InvalidateGateResult r = ig_run(IG_CASES[84]); return r.text; }()), "FB-B2 text: ig row 84: text");
static_assert(([]{ const InvalidateGateResult r = ig_run(IG_CASES[85]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8); }()) == 12, "FB-B2 value: ig row 85: code | arm_off_only << 8");
static_assert(text_is("INVALIDATE REFUSED - profile generation is not ahead of this boot's generation high-water mark; reboot to re-verify", []{ const InvalidateGateResult r = ig_run(IG_CASES[85]); return r.text; }()), "FB-B2 text: ig row 85: text");
static_assert(([]{ const InvalidateGateResult r = ig_run(IG_CASES[86]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8); }()) == 12, "FB-B2 value: ig row 86: code | arm_off_only << 8");
static_assert(text_is("INVALIDATE REFUSED - profile generation is not ahead of this boot's generation high-water mark; reboot to re-verify", []{ const InvalidateGateResult r = ig_run(IG_CASES[86]); return r.text; }()), "FB-B2 text: ig row 86: text");
static_assert(([]{ const InvalidateGateResult r = ig_run(IG_CASES[87]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8); }()) == 12, "FB-B2 value: ig row 87: code | arm_off_only << 8");
static_assert(text_is("INVALIDATE REFUSED - profile generation is not ahead of this boot's generation high-water mark; reboot to re-verify", []{ const InvalidateGateResult r = ig_run(IG_CASES[87]); return r.text; }()), "FB-B2 text: ig row 87: text");
static_assert(([]{ const InvalidateGateResult r = ig_run(IG_CASES[88]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8); }()) == 12, "FB-B2 value: ig row 88: code | arm_off_only << 8");
static_assert(text_is("INVALIDATE REFUSED - profile generation is not ahead of this boot's generation high-water mark; reboot to re-verify", []{ const InvalidateGateResult r = ig_run(IG_CASES[88]); return r.text; }()), "FB-B2 text: ig row 88: text");
static_assert(([]{ const InvalidateGateResult r = ig_run(IG_CASES[89]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8); }()) == 13, "FB-B2 value: ig row 89: code | arm_off_only << 8");
static_assert(text_is("INVALIDATE REFUSED - inverter busy; try again", []{ const InvalidateGateResult r = ig_run(IG_CASES[89]); return r.text; }()), "FB-B2 text: ig row 89: text");
static_assert(([]{ const InvalidateGateResult r = ig_run(IG_CASES[90]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8); }()) == 13, "FB-B2 value: ig row 90: code | arm_off_only << 8");
static_assert(text_is("INVALIDATE REFUSED - inverter busy; try again", []{ const InvalidateGateResult r = ig_run(IG_CASES[90]); return r.text; }()), "FB-B2 text: ig row 90: text");
static_assert(([]{ const InvalidateGateResult r = ig_run(IG_CASES[91]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8); }()) == 13, "FB-B2 value: ig row 91: code | arm_off_only << 8");
static_assert(text_is("INVALIDATE REFUSED - inverter busy; try again", []{ const InvalidateGateResult r = ig_run(IG_CASES[91]); return r.text; }()), "FB-B2 text: ig row 91: text");
static_assert(([]{ const InvalidateGateResult r = ig_run(IG_CASES[92]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8); }()) == 13, "FB-B2 value: ig row 92: code | arm_off_only << 8");
static_assert(text_is("INVALIDATE REFUSED - inverter busy; try again", []{ const InvalidateGateResult r = ig_run(IG_CASES[92]); return r.text; }()), "FB-B2 text: ig row 92: text");
static_assert(([]{ const InvalidateGateResult r = ig_run(IG_CASES[93]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8); }()) == 13, "FB-B2 value: ig row 93: code | arm_off_only << 8");
static_assert(text_is("INVALIDATE REFUSED - inverter busy; try again", []{ const InvalidateGateResult r = ig_run(IG_CASES[93]); return r.text; }()), "FB-B2 text: ig row 93: text");
static_assert(([]{ const InvalidateGateResult r = ig_run(IG_CASES[94]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8); }()) == 13, "FB-B2 value: ig row 94: code | arm_off_only << 8");
static_assert(text_is("INVALIDATE REFUSED - inverter busy; try again", []{ const InvalidateGateResult r = ig_run(IG_CASES[94]); return r.text; }()), "FB-B2 text: ig row 94: text");
static_assert(([]{ const InvalidateGateResult r = ig_run(IG_CASES[95]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8); }()) == 13, "FB-B2 value: ig row 95: code | arm_off_only << 8");
static_assert(text_is("INVALIDATE REFUSED - inverter busy; try again", []{ const InvalidateGateResult r = ig_run(IG_CASES[95]); return r.text; }()), "FB-B2 text: ig row 95: text");
static_assert(([]{ const InvalidateGateResult r = ig_run(IG_CASES[96]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8); }()) == 13, "FB-B2 value: ig row 96: code | arm_off_only << 8");
static_assert(text_is("INVALIDATE REFUSED - inverter busy; try again", []{ const InvalidateGateResult r = ig_run(IG_CASES[96]); return r.text; }()), "FB-B2 text: ig row 96: text");
static_assert(([]{ const InvalidateGateResult r = ig_run(IG_CASES[97]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8); }()) == 13, "FB-B2 value: ig row 97: code | arm_off_only << 8");
static_assert(text_is("INVALIDATE REFUSED - inverter busy; try again", []{ const InvalidateGateResult r = ig_run(IG_CASES[97]); return r.text; }()), "FB-B2 text: ig row 97: text");
static_assert(([]{ const InvalidateGateResult r = ig_run(IG_CASES[98]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8); }()) == 13, "FB-B2 value: ig row 98: code | arm_off_only << 8");
static_assert(text_is("INVALIDATE REFUSED - inverter busy; try again", []{ const InvalidateGateResult r = ig_run(IG_CASES[98]); return r.text; }()), "FB-B2 text: ig row 98: text");
static_assert(([]{ const InvalidateGateResult r = ig_run(IG_CASES[99]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8); }()) == 13, "FB-B2 value: ig row 99: code | arm_off_only << 8");
static_assert(text_is("INVALIDATE REFUSED - inverter busy; try again", []{ const InvalidateGateResult r = ig_run(IG_CASES[99]); return r.text; }()), "FB-B2 text: ig row 99: text");
static_assert(([]{ const InvalidateGateResult r = ig_run(IG_CASES[100]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8); }()) == 13, "FB-B2 value: ig row 100: code | arm_off_only << 8");
static_assert(text_is("INVALIDATE REFUSED - inverter busy; try again", []{ const InvalidateGateResult r = ig_run(IG_CASES[100]); return r.text; }()), "FB-B2 text: ig row 100: text");
static_assert(([]{ const InvalidateGateResult r = ig_run(IG_CASES[101]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8); }()) == 14, "FB-B2 value: ig row 101: code | arm_off_only << 8");
static_assert(text_is("INVALIDATE REFUSED - a failback episode record exists; only the firmware that created it can resolve it", []{ const InvalidateGateResult r = ig_run(IG_CASES[101]); return r.text; }()), "FB-B2 text: ig row 101: text");
static_assert(([]{ const InvalidateGateResult r = ig_run(IG_CASES[102]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8); }()) == 14, "FB-B2 value: ig row 102: code | arm_off_only << 8");
static_assert(text_is("INVALIDATE REFUSED - Failback record recovery metadata is CORRUPT (hard lockout); Fallback never overwrites or proceeds past it; do not erase NVS", []{ const InvalidateGateResult r = ig_run(IG_CASES[102]); return r.text; }()), "FB-B2 text: ig row 102: text");
static_assert(([]{ const InvalidateGateResult r = ig_run(IG_CASES[103]); return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8); }()) == 14, "FB-B2 value: ig row 103: code | arm_off_only << 8");
static_assert(text_is("INVALIDATE REFUSED - Failback record recovery state UNKNOWN since boot (marker unreadable); an obligation cannot be ruled out; Fallback never proceeds past it", []{ const InvalidateGateResult r = ig_run(IG_CASES[103]); return r.text; }()), "FB-B2 text: ig row 103: text");
static_assert(([]{ GateInputs g = fx_gate(0); g.bus.fallback_profile_op_in_progress = true; g.bus.fallback_profile_capture_dispatch_running = true; g.bus.manual_write_in_progress = true; const FinalGate r = final_gate_decide(g, ecco_fbcap::ProbeResults{}); return (uint64_t) r.gr.code | ((uint64_t) r.gr.slot << 8) | ((uint64_t) ((r.gr.probe_fp ? 4 : 0) + (r.gr.probe_dump ? 2 : 0) + (r.gr.probe_r244 ? 1 : 0)) << 16) | ((uint64_t) r.gr.latch << 24); }()) == 524034, "FB-B2 value: final_gate_decide [scenario 0 + own holds, probes none]: code | slot | probes | latch");
static_assert(text_is("", []{ GateInputs g = fx_gate(0); g.bus.fallback_profile_op_in_progress = true; g.bus.fallback_profile_capture_dispatch_running = true; g.bus.manual_write_in_progress = true; const FinalGate r = final_gate_decide(g, ecco_fbcap::ProbeResults{}); return r.text; }()), "FB-B2 text: final_gate_decide [scenario 0 + own holds, probes none]: text");
static_assert(text_is("FP:NP,DP:NP,R4:NP,MT:CN,FS:CA,BUS:OK", []{ GateInputs g = fx_gate(0); g.bus.fallback_profile_op_in_progress = true; g.bus.fallback_profile_capture_dispatch_running = true; g.bus.manual_write_in_progress = true; const FinalGate r = final_gate_decide(g, ecco_fbcap::ProbeResults{}); return r.gr.obl; }()), "FB-B2 text: final_gate_decide [scenario 0 + own holds, probes none]: obl");
static_assert(([]{ GateInputs g = fx_gate(0); g.bus.fallback_profile_op_in_progress = true; g.bus.fallback_profile_capture_dispatch_running = true; g.bus.manual_write_in_progress = true; const FinalGate r = final_gate_decide(g, ecco_fbcap::ProbeResults{ecco_fbcap::PROBE_ABSENT, ecco_fbcap::PROBE_CLEAR, ecco_fbcap::PROBE_ABSENT}); return (uint64_t) r.gr.code | ((uint64_t) r.gr.slot << 8) | ((uint64_t) ((r.gr.probe_fp ? 4 : 0) + (r.gr.probe_dump ? 2 : 0) + (r.gr.probe_r244 ? 1 : 0)) << 16) | ((uint64_t) r.gr.latch << 24); }()) == 65281, "FB-B2 value: final_gate_decide [scenario 0 + own holds, probes all clear]: code | slot | probes | latch");
static_assert(text_is("", []{ GateInputs g = fx_gate(0); g.bus.fallback_profile_op_in_progress = true; g.bus.fallback_profile_capture_dispatch_running = true; g.bus.manual_write_in_progress = true; const FinalGate r = final_gate_decide(g, ecco_fbcap::ProbeResults{ecco_fbcap::PROBE_ABSENT, ecco_fbcap::PROBE_CLEAR, ecco_fbcap::PROBE_ABSENT}); return r.text; }()), "FB-B2 text: final_gate_decide [scenario 0 + own holds, probes all clear]: text");
static_assert(text_is("FP:CA,DP:CM,R4:CA,MT:CN,FS:CA,BUS:OK", []{ GateInputs g = fx_gate(0); g.bus.fallback_profile_op_in_progress = true; g.bus.fallback_profile_capture_dispatch_running = true; g.bus.manual_write_in_progress = true; const FinalGate r = final_gate_decide(g, ecco_fbcap::ProbeResults{ecco_fbcap::PROBE_ABSENT, ecco_fbcap::PROBE_CLEAR, ecco_fbcap::PROBE_ABSENT}); return r.gr.obl; }()), "FB-B2 text: final_gate_decide [scenario 0 + own holds, probes all clear]: obl");
static_assert(([]{ GateInputs g = fx_gate(0); g.bus.fallback_profile_op_in_progress = true; g.bus.fallback_profile_capture_dispatch_running = true; g.bus.manual_write_in_progress = true; return ecco_fbcap::gate_decide(g, ecco_fbcap::ProbeResults{}).code; }()) == 3, "FB-B2 value: gate_decide WITHOUT the masking [scenario 0 + own holds]: code (the SAVE itself would be refused as in flight)");
static_assert(([]{ GateInputs g = fx_gate(1); g.bus.fallback_profile_op_in_progress = true; g.bus.fallback_profile_capture_dispatch_running = true; g.bus.manual_write_in_progress = true; const FinalGate r = final_gate_decide(g, ecco_fbcap::ProbeResults{}); return (uint64_t) r.gr.code | ((uint64_t) r.gr.slot << 8) | ((uint64_t) ((r.gr.probe_fp ? 4 : 0) + (r.gr.probe_dump ? 2 : 0) + (r.gr.probe_r244 ? 1 : 0)) << 16) | ((uint64_t) r.gr.latch << 24); }()) == 524034, "FB-B2 value: final_gate_decide [scenario 1 + own holds, probes none]: code | slot | probes | latch");
static_assert(text_is("", []{ GateInputs g = fx_gate(1); g.bus.fallback_profile_op_in_progress = true; g.bus.fallback_profile_capture_dispatch_running = true; g.bus.manual_write_in_progress = true; const FinalGate r = final_gate_decide(g, ecco_fbcap::ProbeResults{}); return r.text; }()), "FB-B2 text: final_gate_decide [scenario 1 + own holds, probes none]: text");
static_assert(text_is("FP:NP,DP:NP,R4:NP,MT:CN,FS:CA,BUS:OK", []{ GateInputs g = fx_gate(1); g.bus.fallback_profile_op_in_progress = true; g.bus.fallback_profile_capture_dispatch_running = true; g.bus.manual_write_in_progress = true; const FinalGate r = final_gate_decide(g, ecco_fbcap::ProbeResults{}); return r.gr.obl; }()), "FB-B2 text: final_gate_decide [scenario 1 + own holds, probes none]: obl");
static_assert(([]{ GateInputs g = fx_gate(1); g.bus.fallback_profile_op_in_progress = true; g.bus.fallback_profile_capture_dispatch_running = true; g.bus.manual_write_in_progress = true; const FinalGate r = final_gate_decide(g, ecco_fbcap::ProbeResults{ecco_fbcap::PROBE_ABSENT, ecco_fbcap::PROBE_CLEAR, ecco_fbcap::PROBE_ABSENT}); return (uint64_t) r.gr.code | ((uint64_t) r.gr.slot << 8) | ((uint64_t) ((r.gr.probe_fp ? 4 : 0) + (r.gr.probe_dump ? 2 : 0) + (r.gr.probe_r244 ? 1 : 0)) << 16) | ((uint64_t) r.gr.latch << 24); }()) == 65281, "FB-B2 value: final_gate_decide [scenario 1 + own holds, probes all clear]: code | slot | probes | latch");
static_assert(text_is("", []{ GateInputs g = fx_gate(1); g.bus.fallback_profile_op_in_progress = true; g.bus.fallback_profile_capture_dispatch_running = true; g.bus.manual_write_in_progress = true; const FinalGate r = final_gate_decide(g, ecco_fbcap::ProbeResults{ecco_fbcap::PROBE_ABSENT, ecco_fbcap::PROBE_CLEAR, ecco_fbcap::PROBE_ABSENT}); return r.text; }()), "FB-B2 text: final_gate_decide [scenario 1 + own holds, probes all clear]: text");
static_assert(text_is("FP:CA,DP:CM,R4:CA,MT:CN,FS:CA,BUS:OK", []{ GateInputs g = fx_gate(1); g.bus.fallback_profile_op_in_progress = true; g.bus.fallback_profile_capture_dispatch_running = true; g.bus.manual_write_in_progress = true; const FinalGate r = final_gate_decide(g, ecco_fbcap::ProbeResults{ecco_fbcap::PROBE_ABSENT, ecco_fbcap::PROBE_CLEAR, ecco_fbcap::PROBE_ABSENT}); return r.gr.obl; }()), "FB-B2 text: final_gate_decide [scenario 1 + own holds, probes all clear]: obl");
static_assert(([]{ GateInputs g = fx_gate(1); g.bus.fallback_profile_op_in_progress = true; g.bus.fallback_profile_capture_dispatch_running = true; g.bus.manual_write_in_progress = true; return ecco_fbcap::gate_decide(g, ecco_fbcap::ProbeResults{}).code; }()) == 3, "FB-B2 value: gate_decide WITHOUT the masking [scenario 1 + own holds]: code (the SAVE itself would be refused as in flight)");
static_assert(([]{ GateInputs g = fx_gate(2); g.bus.fallback_profile_op_in_progress = true; g.bus.fallback_profile_capture_dispatch_running = true; g.bus.manual_write_in_progress = true; const FinalGate r = final_gate_decide(g, ecco_fbcap::ProbeResults{}); return (uint64_t) r.gr.code | ((uint64_t) r.gr.slot << 8) | ((uint64_t) ((r.gr.probe_fp ? 4 : 0) + (r.gr.probe_dump ? 2 : 0) + (r.gr.probe_r244 ? 1 : 0)) << 16) | ((uint64_t) r.gr.latch << 24); }()) == 524034, "FB-B2 value: final_gate_decide [scenario 2 + own holds, probes none]: code | slot | probes | latch");
static_assert(text_is("", []{ GateInputs g = fx_gate(2); g.bus.fallback_profile_op_in_progress = true; g.bus.fallback_profile_capture_dispatch_running = true; g.bus.manual_write_in_progress = true; const FinalGate r = final_gate_decide(g, ecco_fbcap::ProbeResults{}); return r.text; }()), "FB-B2 text: final_gate_decide [scenario 2 + own holds, probes none]: text");
static_assert(text_is("FP:NP,DP:NP,R4:NP,MT:CN,FS:CA,BUS:OK", []{ GateInputs g = fx_gate(2); g.bus.fallback_profile_op_in_progress = true; g.bus.fallback_profile_capture_dispatch_running = true; g.bus.manual_write_in_progress = true; const FinalGate r = final_gate_decide(g, ecco_fbcap::ProbeResults{}); return r.gr.obl; }()), "FB-B2 text: final_gate_decide [scenario 2 + own holds, probes none]: obl");
static_assert(([]{ GateInputs g = fx_gate(2); g.bus.fallback_profile_op_in_progress = true; g.bus.fallback_profile_capture_dispatch_running = true; g.bus.manual_write_in_progress = true; const FinalGate r = final_gate_decide(g, ecco_fbcap::ProbeResults{ecco_fbcap::PROBE_ABSENT, ecco_fbcap::PROBE_CLEAR, ecco_fbcap::PROBE_ABSENT}); return (uint64_t) r.gr.code | ((uint64_t) r.gr.slot << 8) | ((uint64_t) ((r.gr.probe_fp ? 4 : 0) + (r.gr.probe_dump ? 2 : 0) + (r.gr.probe_r244 ? 1 : 0)) << 16) | ((uint64_t) r.gr.latch << 24); }()) == 65281, "FB-B2 value: final_gate_decide [scenario 2 + own holds, probes all clear]: code | slot | probes | latch");
static_assert(text_is("", []{ GateInputs g = fx_gate(2); g.bus.fallback_profile_op_in_progress = true; g.bus.fallback_profile_capture_dispatch_running = true; g.bus.manual_write_in_progress = true; const FinalGate r = final_gate_decide(g, ecco_fbcap::ProbeResults{ecco_fbcap::PROBE_ABSENT, ecco_fbcap::PROBE_CLEAR, ecco_fbcap::PROBE_ABSENT}); return r.text; }()), "FB-B2 text: final_gate_decide [scenario 2 + own holds, probes all clear]: text");
static_assert(text_is("FP:CA,DP:CM,R4:CA,MT:CN,FS:CA,BUS:OK", []{ GateInputs g = fx_gate(2); g.bus.fallback_profile_op_in_progress = true; g.bus.fallback_profile_capture_dispatch_running = true; g.bus.manual_write_in_progress = true; const FinalGate r = final_gate_decide(g, ecco_fbcap::ProbeResults{ecco_fbcap::PROBE_ABSENT, ecco_fbcap::PROBE_CLEAR, ecco_fbcap::PROBE_ABSENT}); return r.gr.obl; }()), "FB-B2 text: final_gate_decide [scenario 2 + own holds, probes all clear]: obl");
static_assert(([]{ GateInputs g = fx_gate(2); g.bus.fallback_profile_op_in_progress = true; g.bus.fallback_profile_capture_dispatch_running = true; g.bus.manual_write_in_progress = true; return ecco_fbcap::gate_decide(g, ecco_fbcap::ProbeResults{}).code; }()) == 3, "FB-B2 value: gate_decide WITHOUT the masking [scenario 2 + own holds]: code (the SAVE itself would be refused as in flight)");
static_assert(([]{ GateInputs g = fx_gate(3); g.bus.fallback_profile_op_in_progress = true; g.bus.fallback_profile_capture_dispatch_running = true; g.bus.manual_write_in_progress = true; const FinalGate r = final_gate_decide(g, ecco_fbcap::ProbeResults{}); return (uint64_t) r.gr.code | ((uint64_t) r.gr.slot << 8) | ((uint64_t) ((r.gr.probe_fp ? 4 : 0) + (r.gr.probe_dump ? 2 : 0) + (r.gr.probe_r244 ? 1 : 0)) << 16) | ((uint64_t) r.gr.latch << 24); }()) == 65284, "FB-B2 value: final_gate_decide [scenario 3 + own holds, probes none]: code | slot | probes | latch");
static_assert(text_is("SAVE REFUSED - durable state not loaded yet", []{ GateInputs g = fx_gate(3); g.bus.fallback_profile_op_in_progress = true; g.bus.fallback_profile_capture_dispatch_running = true; g.bus.manual_write_in_progress = true; const FinalGate r = final_gate_decide(g, ecco_fbcap::ProbeResults{}); return r.text; }()), "FB-B2 text: final_gate_decide [scenario 3 + own holds, probes none]: text");
static_assert(text_is("FP:BL,DP:BL,R4:BL,MT:BL,FS:BL,BUS:OK", []{ GateInputs g = fx_gate(3); g.bus.fallback_profile_op_in_progress = true; g.bus.fallback_profile_capture_dispatch_running = true; g.bus.manual_write_in_progress = true; const FinalGate r = final_gate_decide(g, ecco_fbcap::ProbeResults{}); return r.gr.obl; }()), "FB-B2 text: final_gate_decide [scenario 3 + own holds, probes none]: obl");
static_assert(([]{ GateInputs g = fx_gate(3); g.bus.fallback_profile_op_in_progress = true; g.bus.fallback_profile_capture_dispatch_running = true; g.bus.manual_write_in_progress = true; const FinalGate r = final_gate_decide(g, ecco_fbcap::ProbeResults{ecco_fbcap::PROBE_ABSENT, ecco_fbcap::PROBE_CLEAR, ecco_fbcap::PROBE_ABSENT}); return (uint64_t) r.gr.code | ((uint64_t) r.gr.slot << 8) | ((uint64_t) ((r.gr.probe_fp ? 4 : 0) + (r.gr.probe_dump ? 2 : 0) + (r.gr.probe_r244 ? 1 : 0)) << 16) | ((uint64_t) r.gr.latch << 24); }()) == 65284, "FB-B2 value: final_gate_decide [scenario 3 + own holds, probes all clear]: code | slot | probes | latch");
static_assert(text_is("SAVE REFUSED - durable state not loaded yet", []{ GateInputs g = fx_gate(3); g.bus.fallback_profile_op_in_progress = true; g.bus.fallback_profile_capture_dispatch_running = true; g.bus.manual_write_in_progress = true; const FinalGate r = final_gate_decide(g, ecco_fbcap::ProbeResults{ecco_fbcap::PROBE_ABSENT, ecco_fbcap::PROBE_CLEAR, ecco_fbcap::PROBE_ABSENT}); return r.text; }()), "FB-B2 text: final_gate_decide [scenario 3 + own holds, probes all clear]: text");
static_assert(text_is("FP:BL,DP:BL,R4:BL,MT:BL,FS:BL,BUS:OK", []{ GateInputs g = fx_gate(3); g.bus.fallback_profile_op_in_progress = true; g.bus.fallback_profile_capture_dispatch_running = true; g.bus.manual_write_in_progress = true; const FinalGate r = final_gate_decide(g, ecco_fbcap::ProbeResults{ecco_fbcap::PROBE_ABSENT, ecco_fbcap::PROBE_CLEAR, ecco_fbcap::PROBE_ABSENT}); return r.gr.obl; }()), "FB-B2 text: final_gate_decide [scenario 3 + own holds, probes all clear]: obl");
static_assert(([]{ GateInputs g = fx_gate(3); g.bus.fallback_profile_op_in_progress = true; g.bus.fallback_profile_capture_dispatch_running = true; g.bus.manual_write_in_progress = true; return ecco_fbcap::gate_decide(g, ecco_fbcap::ProbeResults{}).code; }()) == 3, "FB-B2 value: gate_decide WITHOUT the masking [scenario 3 + own holds]: code (the SAVE itself would be refused as in flight)");
static_assert(([]{ GateInputs g = fx_gate(4); g.bus.fallback_profile_op_in_progress = true; g.bus.fallback_profile_capture_dispatch_running = true; g.bus.manual_write_in_progress = true; const FinalGate r = final_gate_decide(g, ecco_fbcap::ProbeResults{}); return (uint64_t) r.gr.code | ((uint64_t) r.gr.slot << 8) | ((uint64_t) ((r.gr.probe_fp ? 4 : 0) + (r.gr.probe_dump ? 2 : 0) + (r.gr.probe_r244 ? 1 : 0)) << 16) | ((uint64_t) r.gr.latch << 24); }()) == 65285, "FB-B2 value: final_gate_decide [scenario 4 + own holds, probes none]: code | slot | probes | latch");
static_assert(text_is("SAVE REFUSED - a Free Power / Dump to Grid / Manual Configuration write arm is on; finish or turn it off first", []{ GateInputs g = fx_gate(4); g.bus.fallback_profile_op_in_progress = true; g.bus.fallback_profile_capture_dispatch_running = true; g.bus.manual_write_in_progress = true; const FinalGate r = final_gate_decide(g, ecco_fbcap::ProbeResults{}); return r.text; }()), "FB-B2 text: final_gate_decide [scenario 4 + own holds, probes none]: text");
static_assert(text_is("FP:NP,DP:NP,R4:NP,MT:CN,FS:CA,BUS:OK", []{ GateInputs g = fx_gate(4); g.bus.fallback_profile_op_in_progress = true; g.bus.fallback_profile_capture_dispatch_running = true; g.bus.manual_write_in_progress = true; const FinalGate r = final_gate_decide(g, ecco_fbcap::ProbeResults{}); return r.gr.obl; }()), "FB-B2 text: final_gate_decide [scenario 4 + own holds, probes none]: obl");
static_assert(([]{ GateInputs g = fx_gate(4); g.bus.fallback_profile_op_in_progress = true; g.bus.fallback_profile_capture_dispatch_running = true; g.bus.manual_write_in_progress = true; const FinalGate r = final_gate_decide(g, ecco_fbcap::ProbeResults{ecco_fbcap::PROBE_ABSENT, ecco_fbcap::PROBE_CLEAR, ecco_fbcap::PROBE_ABSENT}); return (uint64_t) r.gr.code | ((uint64_t) r.gr.slot << 8) | ((uint64_t) ((r.gr.probe_fp ? 4 : 0) + (r.gr.probe_dump ? 2 : 0) + (r.gr.probe_r244 ? 1 : 0)) << 16) | ((uint64_t) r.gr.latch << 24); }()) == 65285, "FB-B2 value: final_gate_decide [scenario 4 + own holds, probes all clear]: code | slot | probes | latch");
static_assert(text_is("SAVE REFUSED - a Free Power / Dump to Grid / Manual Configuration write arm is on; finish or turn it off first", []{ GateInputs g = fx_gate(4); g.bus.fallback_profile_op_in_progress = true; g.bus.fallback_profile_capture_dispatch_running = true; g.bus.manual_write_in_progress = true; const FinalGate r = final_gate_decide(g, ecco_fbcap::ProbeResults{ecco_fbcap::PROBE_ABSENT, ecco_fbcap::PROBE_CLEAR, ecco_fbcap::PROBE_ABSENT}); return r.text; }()), "FB-B2 text: final_gate_decide [scenario 4 + own holds, probes all clear]: text");
static_assert(text_is("FP:CA,DP:CM,R4:CA,MT:CN,FS:CA,BUS:OK", []{ GateInputs g = fx_gate(4); g.bus.fallback_profile_op_in_progress = true; g.bus.fallback_profile_capture_dispatch_running = true; g.bus.manual_write_in_progress = true; const FinalGate r = final_gate_decide(g, ecco_fbcap::ProbeResults{ecco_fbcap::PROBE_ABSENT, ecco_fbcap::PROBE_CLEAR, ecco_fbcap::PROBE_ABSENT}); return r.gr.obl; }()), "FB-B2 text: final_gate_decide [scenario 4 + own holds, probes all clear]: obl");
static_assert(([]{ GateInputs g = fx_gate(4); g.bus.fallback_profile_op_in_progress = true; g.bus.fallback_profile_capture_dispatch_running = true; g.bus.manual_write_in_progress = true; return ecco_fbcap::gate_decide(g, ecco_fbcap::ProbeResults{}).code; }()) == 3, "FB-B2 value: gate_decide WITHOUT the masking [scenario 4 + own holds]: code (the SAVE itself would be refused as in flight)");
static_assert(([]{ GateInputs g = fx_gate(5); g.bus.fallback_profile_op_in_progress = true; g.bus.fallback_profile_capture_dispatch_running = true; g.bus.manual_write_in_progress = true; const FinalGate r = final_gate_decide(g, ecco_fbcap::ProbeResults{}); return (uint64_t) r.gr.code | ((uint64_t) r.gr.slot << 8) | ((uint64_t) ((r.gr.probe_fp ? 4 : 0) + (r.gr.probe_dump ? 2 : 0) + (r.gr.probe_r244 ? 1 : 0)) << 16) | ((uint64_t) r.gr.latch << 24); }()) == 65285, "FB-B2 value: final_gate_decide [scenario 5 + own holds, probes none]: code | slot | probes | latch");
static_assert(text_is("SAVE REFUSED - a Free Power / Dump to Grid / Manual Configuration write arm is on; finish or turn it off first", []{ GateInputs g = fx_gate(5); g.bus.fallback_profile_op_in_progress = true; g.bus.fallback_profile_capture_dispatch_running = true; g.bus.manual_write_in_progress = true; const FinalGate r = final_gate_decide(g, ecco_fbcap::ProbeResults{}); return r.text; }()), "FB-B2 text: final_gate_decide [scenario 5 + own holds, probes none]: text");
static_assert(text_is("FP:NP,DP:NP,R4:NP,MT:CN,FS:CA,BUS:OK", []{ GateInputs g = fx_gate(5); g.bus.fallback_profile_op_in_progress = true; g.bus.fallback_profile_capture_dispatch_running = true; g.bus.manual_write_in_progress = true; const FinalGate r = final_gate_decide(g, ecco_fbcap::ProbeResults{}); return r.gr.obl; }()), "FB-B2 text: final_gate_decide [scenario 5 + own holds, probes none]: obl");
static_assert(([]{ GateInputs g = fx_gate(5); g.bus.fallback_profile_op_in_progress = true; g.bus.fallback_profile_capture_dispatch_running = true; g.bus.manual_write_in_progress = true; const FinalGate r = final_gate_decide(g, ecco_fbcap::ProbeResults{ecco_fbcap::PROBE_ABSENT, ecco_fbcap::PROBE_CLEAR, ecco_fbcap::PROBE_ABSENT}); return (uint64_t) r.gr.code | ((uint64_t) r.gr.slot << 8) | ((uint64_t) ((r.gr.probe_fp ? 4 : 0) + (r.gr.probe_dump ? 2 : 0) + (r.gr.probe_r244 ? 1 : 0)) << 16) | ((uint64_t) r.gr.latch << 24); }()) == 65285, "FB-B2 value: final_gate_decide [scenario 5 + own holds, probes all clear]: code | slot | probes | latch");
static_assert(text_is("SAVE REFUSED - a Free Power / Dump to Grid / Manual Configuration write arm is on; finish or turn it off first", []{ GateInputs g = fx_gate(5); g.bus.fallback_profile_op_in_progress = true; g.bus.fallback_profile_capture_dispatch_running = true; g.bus.manual_write_in_progress = true; const FinalGate r = final_gate_decide(g, ecco_fbcap::ProbeResults{ecco_fbcap::PROBE_ABSENT, ecco_fbcap::PROBE_CLEAR, ecco_fbcap::PROBE_ABSENT}); return r.text; }()), "FB-B2 text: final_gate_decide [scenario 5 + own holds, probes all clear]: text");
static_assert(text_is("FP:CA,DP:CM,R4:CA,MT:CN,FS:CA,BUS:OK", []{ GateInputs g = fx_gate(5); g.bus.fallback_profile_op_in_progress = true; g.bus.fallback_profile_capture_dispatch_running = true; g.bus.manual_write_in_progress = true; const FinalGate r = final_gate_decide(g, ecco_fbcap::ProbeResults{ecco_fbcap::PROBE_ABSENT, ecco_fbcap::PROBE_CLEAR, ecco_fbcap::PROBE_ABSENT}); return r.gr.obl; }()), "FB-B2 text: final_gate_decide [scenario 5 + own holds, probes all clear]: obl");
static_assert(([]{ GateInputs g = fx_gate(5); g.bus.fallback_profile_op_in_progress = true; g.bus.fallback_profile_capture_dispatch_running = true; g.bus.manual_write_in_progress = true; return ecco_fbcap::gate_decide(g, ecco_fbcap::ProbeResults{}).code; }()) == 3, "FB-B2 value: gate_decide WITHOUT the masking [scenario 5 + own holds]: code (the SAVE itself would be refused as in flight)");
static_assert(([]{ GateInputs g = fx_gate(6); g.bus.fallback_profile_op_in_progress = true; g.bus.fallback_profile_capture_dispatch_running = true; g.bus.manual_write_in_progress = true; const FinalGate r = final_gate_decide(g, ecco_fbcap::ProbeResults{}); return (uint64_t) r.gr.code | ((uint64_t) r.gr.slot << 8) | ((uint64_t) ((r.gr.probe_fp ? 4 : 0) + (r.gr.probe_dump ? 2 : 0) + (r.gr.probe_r244 ? 1 : 0)) << 16) | ((uint64_t) r.gr.latch << 24); }()) == 65285, "FB-B2 value: final_gate_decide [scenario 6 + own holds, probes none]: code | slot | probes | latch");
static_assert(text_is("SAVE REFUSED - a Free Power / Dump to Grid / Manual Configuration write arm is on; finish or turn it off first", []{ GateInputs g = fx_gate(6); g.bus.fallback_profile_op_in_progress = true; g.bus.fallback_profile_capture_dispatch_running = true; g.bus.manual_write_in_progress = true; const FinalGate r = final_gate_decide(g, ecco_fbcap::ProbeResults{}); return r.text; }()), "FB-B2 text: final_gate_decide [scenario 6 + own holds, probes none]: text");
static_assert(text_is("FP:NP,DP:NP,R4:NP,MT:CN,FS:CA,BUS:OK", []{ GateInputs g = fx_gate(6); g.bus.fallback_profile_op_in_progress = true; g.bus.fallback_profile_capture_dispatch_running = true; g.bus.manual_write_in_progress = true; const FinalGate r = final_gate_decide(g, ecco_fbcap::ProbeResults{}); return r.gr.obl; }()), "FB-B2 text: final_gate_decide [scenario 6 + own holds, probes none]: obl");
static_assert(([]{ GateInputs g = fx_gate(6); g.bus.fallback_profile_op_in_progress = true; g.bus.fallback_profile_capture_dispatch_running = true; g.bus.manual_write_in_progress = true; const FinalGate r = final_gate_decide(g, ecco_fbcap::ProbeResults{ecco_fbcap::PROBE_ABSENT, ecco_fbcap::PROBE_CLEAR, ecco_fbcap::PROBE_ABSENT}); return (uint64_t) r.gr.code | ((uint64_t) r.gr.slot << 8) | ((uint64_t) ((r.gr.probe_fp ? 4 : 0) + (r.gr.probe_dump ? 2 : 0) + (r.gr.probe_r244 ? 1 : 0)) << 16) | ((uint64_t) r.gr.latch << 24); }()) == 65285, "FB-B2 value: final_gate_decide [scenario 6 + own holds, probes all clear]: code | slot | probes | latch");
static_assert(text_is("SAVE REFUSED - a Free Power / Dump to Grid / Manual Configuration write arm is on; finish or turn it off first", []{ GateInputs g = fx_gate(6); g.bus.fallback_profile_op_in_progress = true; g.bus.fallback_profile_capture_dispatch_running = true; g.bus.manual_write_in_progress = true; const FinalGate r = final_gate_decide(g, ecco_fbcap::ProbeResults{ecco_fbcap::PROBE_ABSENT, ecco_fbcap::PROBE_CLEAR, ecco_fbcap::PROBE_ABSENT}); return r.text; }()), "FB-B2 text: final_gate_decide [scenario 6 + own holds, probes all clear]: text");
static_assert(text_is("FP:CA,DP:CM,R4:CA,MT:CN,FS:CA,BUS:OK", []{ GateInputs g = fx_gate(6); g.bus.fallback_profile_op_in_progress = true; g.bus.fallback_profile_capture_dispatch_running = true; g.bus.manual_write_in_progress = true; const FinalGate r = final_gate_decide(g, ecco_fbcap::ProbeResults{ecco_fbcap::PROBE_ABSENT, ecco_fbcap::PROBE_CLEAR, ecco_fbcap::PROBE_ABSENT}); return r.gr.obl; }()), "FB-B2 text: final_gate_decide [scenario 6 + own holds, probes all clear]: obl");
static_assert(([]{ GateInputs g = fx_gate(6); g.bus.fallback_profile_op_in_progress = true; g.bus.fallback_profile_capture_dispatch_running = true; g.bus.manual_write_in_progress = true; return ecco_fbcap::gate_decide(g, ecco_fbcap::ProbeResults{}).code; }()) == 3, "FB-B2 value: gate_decide WITHOUT the masking [scenario 6 + own holds]: code (the SAVE itself would be refused as in flight)");
static_assert(([]{ GateInputs g = fx_gate(7); g.bus.fallback_profile_op_in_progress = true; g.bus.fallback_profile_capture_dispatch_running = true; g.bus.manual_write_in_progress = true; const FinalGate r = final_gate_decide(g, ecco_fbcap::ProbeResults{}); return (uint64_t) r.gr.code | ((uint64_t) r.gr.slot << 8) | ((uint64_t) ((r.gr.probe_fp ? 4 : 0) + (r.gr.probe_dump ? 2 : 0) + (r.gr.probe_r244 ? 1 : 0)) << 16) | ((uint64_t) r.gr.latch << 24); }()) == 524034, "FB-B2 value: final_gate_decide [scenario 7 + own holds, probes none]: code | slot | probes | latch");
static_assert(text_is("", []{ GateInputs g = fx_gate(7); g.bus.fallback_profile_op_in_progress = true; g.bus.fallback_profile_capture_dispatch_running = true; g.bus.manual_write_in_progress = true; const FinalGate r = final_gate_decide(g, ecco_fbcap::ProbeResults{}); return r.text; }()), "FB-B2 text: final_gate_decide [scenario 7 + own holds, probes none]: text");
static_assert(text_is("FP:NP,DP:NP,R4:NP,MT:CN,FS:CA,BUS:OK", []{ GateInputs g = fx_gate(7); g.bus.fallback_profile_op_in_progress = true; g.bus.fallback_profile_capture_dispatch_running = true; g.bus.manual_write_in_progress = true; const FinalGate r = final_gate_decide(g, ecco_fbcap::ProbeResults{}); return r.gr.obl; }()), "FB-B2 text: final_gate_decide [scenario 7 + own holds, probes none]: obl");
static_assert(([]{ GateInputs g = fx_gate(7); g.bus.fallback_profile_op_in_progress = true; g.bus.fallback_profile_capture_dispatch_running = true; g.bus.manual_write_in_progress = true; const FinalGate r = final_gate_decide(g, ecco_fbcap::ProbeResults{ecco_fbcap::PROBE_ABSENT, ecco_fbcap::PROBE_CLEAR, ecco_fbcap::PROBE_ABSENT}); return (uint64_t) r.gr.code | ((uint64_t) r.gr.slot << 8) | ((uint64_t) ((r.gr.probe_fp ? 4 : 0) + (r.gr.probe_dump ? 2 : 0) + (r.gr.probe_r244 ? 1 : 0)) << 16) | ((uint64_t) r.gr.latch << 24); }()) == 65281, "FB-B2 value: final_gate_decide [scenario 7 + own holds, probes all clear]: code | slot | probes | latch");
static_assert(text_is("", []{ GateInputs g = fx_gate(7); g.bus.fallback_profile_op_in_progress = true; g.bus.fallback_profile_capture_dispatch_running = true; g.bus.manual_write_in_progress = true; const FinalGate r = final_gate_decide(g, ecco_fbcap::ProbeResults{ecco_fbcap::PROBE_ABSENT, ecco_fbcap::PROBE_CLEAR, ecco_fbcap::PROBE_ABSENT}); return r.text; }()), "FB-B2 text: final_gate_decide [scenario 7 + own holds, probes all clear]: text");
static_assert(text_is("FP:CA,DP:CM,R4:CA,MT:CN,FS:CA,BUS:OK", []{ GateInputs g = fx_gate(7); g.bus.fallback_profile_op_in_progress = true; g.bus.fallback_profile_capture_dispatch_running = true; g.bus.manual_write_in_progress = true; const FinalGate r = final_gate_decide(g, ecco_fbcap::ProbeResults{ecco_fbcap::PROBE_ABSENT, ecco_fbcap::PROBE_CLEAR, ecco_fbcap::PROBE_ABSENT}); return r.gr.obl; }()), "FB-B2 text: final_gate_decide [scenario 7 + own holds, probes all clear]: obl");
static_assert(([]{ GateInputs g = fx_gate(7); g.bus.fallback_profile_op_in_progress = true; g.bus.fallback_profile_capture_dispatch_running = true; g.bus.manual_write_in_progress = true; return ecco_fbcap::gate_decide(g, ecco_fbcap::ProbeResults{}).code; }()) == 3, "FB-B2 value: gate_decide WITHOUT the masking [scenario 7 + own holds]: code (the SAVE itself would be refused as in flight)");
static_assert(([]{ GateInputs g = fx_gate(8); g.bus.fallback_profile_op_in_progress = true; g.bus.fallback_profile_capture_dispatch_running = true; g.bus.manual_write_in_progress = true; const FinalGate r = final_gate_decide(g, ecco_fbcap::ProbeResults{}); return (uint64_t) r.gr.code | ((uint64_t) r.gr.slot << 8) | ((uint64_t) ((r.gr.probe_fp ? 4 : 0) + (r.gr.probe_dump ? 2 : 0) + (r.gr.probe_r244 ? 1 : 0)) << 16) | ((uint64_t) r.gr.latch << 24); }()) == 6, "FB-B2 value: final_gate_decide [scenario 8 + own holds, probes none]: code | slot | probes | latch");
static_assert(text_is("SAVE REFUSED - another inverter transaction is in progress (clock correction); try again shortly", []{ GateInputs g = fx_gate(8); g.bus.fallback_profile_op_in_progress = true; g.bus.fallback_profile_capture_dispatch_running = true; g.bus.manual_write_in_progress = true; const FinalGate r = final_gate_decide(g, ecco_fbcap::ProbeResults{}); return r.text; }()), "FB-B2 text: final_gate_decide [scenario 8 + own holds, probes none]: text");
static_assert(text_is("FP:NP,DP:NP,R4:NP,MT:NP,FS:CA,BUS:BY", []{ GateInputs g = fx_gate(8); g.bus.fallback_profile_op_in_progress = true; g.bus.fallback_profile_capture_dispatch_running = true; g.bus.manual_write_in_progress = true; const FinalGate r = final_gate_decide(g, ecco_fbcap::ProbeResults{}); return r.gr.obl; }()), "FB-B2 text: final_gate_decide [scenario 8 + own holds, probes none]: obl");
static_assert(([]{ GateInputs g = fx_gate(8); g.bus.fallback_profile_op_in_progress = true; g.bus.fallback_profile_capture_dispatch_running = true; g.bus.manual_write_in_progress = true; const FinalGate r = final_gate_decide(g, ecco_fbcap::ProbeResults{ecco_fbcap::PROBE_ABSENT, ecco_fbcap::PROBE_CLEAR, ecco_fbcap::PROBE_ABSENT}); return (uint64_t) r.gr.code | ((uint64_t) r.gr.slot << 8) | ((uint64_t) ((r.gr.probe_fp ? 4 : 0) + (r.gr.probe_dump ? 2 : 0) + (r.gr.probe_r244 ? 1 : 0)) << 16) | ((uint64_t) r.gr.latch << 24); }()) == 6, "FB-B2 value: final_gate_decide [scenario 8 + own holds, probes all clear]: code | slot | probes | latch");
static_assert(text_is("SAVE REFUSED - another inverter transaction is in progress (clock correction); try again shortly", []{ GateInputs g = fx_gate(8); g.bus.fallback_profile_op_in_progress = true; g.bus.fallback_profile_capture_dispatch_running = true; g.bus.manual_write_in_progress = true; const FinalGate r = final_gate_decide(g, ecco_fbcap::ProbeResults{ecco_fbcap::PROBE_ABSENT, ecco_fbcap::PROBE_CLEAR, ecco_fbcap::PROBE_ABSENT}); return r.text; }()), "FB-B2 text: final_gate_decide [scenario 8 + own holds, probes all clear]: text");
static_assert(text_is("FP:CA,DP:CM,R4:CA,MT:NP,FS:CA,BUS:BY", []{ GateInputs g = fx_gate(8); g.bus.fallback_profile_op_in_progress = true; g.bus.fallback_profile_capture_dispatch_running = true; g.bus.manual_write_in_progress = true; const FinalGate r = final_gate_decide(g, ecco_fbcap::ProbeResults{ecco_fbcap::PROBE_ABSENT, ecco_fbcap::PROBE_CLEAR, ecco_fbcap::PROBE_ABSENT}); return r.gr.obl; }()), "FB-B2 text: final_gate_decide [scenario 8 + own holds, probes all clear]: obl");
static_assert(([]{ GateInputs g = fx_gate(8); g.bus.fallback_profile_op_in_progress = true; g.bus.fallback_profile_capture_dispatch_running = true; g.bus.manual_write_in_progress = true; return ecco_fbcap::gate_decide(g, ecco_fbcap::ProbeResults{}).code; }()) == 3, "FB-B2 value: gate_decide WITHOUT the masking [scenario 8 + own holds]: code (the SAVE itself would be refused as in flight)");
static_assert(([]{ GateInputs g = fx_gate(9); g.bus.fallback_profile_op_in_progress = true; g.bus.fallback_profile_capture_dispatch_running = true; g.bus.manual_write_in_progress = true; const FinalGate r = final_gate_decide(g, ecco_fbcap::ProbeResults{}); return (uint64_t) r.gr.code | ((uint64_t) r.gr.slot << 8) | ((uint64_t) ((r.gr.probe_fp ? 4 : 0) + (r.gr.probe_dump ? 2 : 0) + (r.gr.probe_r244 ? 1 : 0)) << 16) | ((uint64_t) r.gr.latch << 24); }()) == 524034, "FB-B2 value: final_gate_decide [scenario 9 + own holds, probes none]: code | slot | probes | latch");
static_assert(text_is("", []{ GateInputs g = fx_gate(9); g.bus.fallback_profile_op_in_progress = true; g.bus.fallback_profile_capture_dispatch_running = true; g.bus.manual_write_in_progress = true; const FinalGate r = final_gate_decide(g, ecco_fbcap::ProbeResults{}); return r.text; }()), "FB-B2 text: final_gate_decide [scenario 9 + own holds, probes none]: text");
static_assert(text_is("FP:NP,DP:NP,R4:NP,MT:CN,FS:CA,BUS:OK", []{ GateInputs g = fx_gate(9); g.bus.fallback_profile_op_in_progress = true; g.bus.fallback_profile_capture_dispatch_running = true; g.bus.manual_write_in_progress = true; const FinalGate r = final_gate_decide(g, ecco_fbcap::ProbeResults{}); return r.gr.obl; }()), "FB-B2 text: final_gate_decide [scenario 9 + own holds, probes none]: obl");
static_assert(([]{ GateInputs g = fx_gate(9); g.bus.fallback_profile_op_in_progress = true; g.bus.fallback_profile_capture_dispatch_running = true; g.bus.manual_write_in_progress = true; const FinalGate r = final_gate_decide(g, ecco_fbcap::ProbeResults{ecco_fbcap::PROBE_ABSENT, ecco_fbcap::PROBE_CLEAR, ecco_fbcap::PROBE_ABSENT}); return (uint64_t) r.gr.code | ((uint64_t) r.gr.slot << 8) | ((uint64_t) ((r.gr.probe_fp ? 4 : 0) + (r.gr.probe_dump ? 2 : 0) + (r.gr.probe_r244 ? 1 : 0)) << 16) | ((uint64_t) r.gr.latch << 24); }()) == 65281, "FB-B2 value: final_gate_decide [scenario 9 + own holds, probes all clear]: code | slot | probes | latch");
static_assert(text_is("", []{ GateInputs g = fx_gate(9); g.bus.fallback_profile_op_in_progress = true; g.bus.fallback_profile_capture_dispatch_running = true; g.bus.manual_write_in_progress = true; const FinalGate r = final_gate_decide(g, ecco_fbcap::ProbeResults{ecco_fbcap::PROBE_ABSENT, ecco_fbcap::PROBE_CLEAR, ecco_fbcap::PROBE_ABSENT}); return r.text; }()), "FB-B2 text: final_gate_decide [scenario 9 + own holds, probes all clear]: text");
static_assert(text_is("FP:CA,DP:CM,R4:CA,MT:CN,FS:CA,BUS:OK", []{ GateInputs g = fx_gate(9); g.bus.fallback_profile_op_in_progress = true; g.bus.fallback_profile_capture_dispatch_running = true; g.bus.manual_write_in_progress = true; const FinalGate r = final_gate_decide(g, ecco_fbcap::ProbeResults{ecco_fbcap::PROBE_ABSENT, ecco_fbcap::PROBE_CLEAR, ecco_fbcap::PROBE_ABSENT}); return r.gr.obl; }()), "FB-B2 text: final_gate_decide [scenario 9 + own holds, probes all clear]: obl");
static_assert(([]{ GateInputs g = fx_gate(9); g.bus.fallback_profile_op_in_progress = true; g.bus.fallback_profile_capture_dispatch_running = true; g.bus.manual_write_in_progress = true; return ecco_fbcap::gate_decide(g, ecco_fbcap::ProbeResults{}).code; }()) == 3, "FB-B2 value: gate_decide WITHOUT the masking [scenario 9 + own holds]: code (the SAVE itself would be refused as in flight)");
static_assert(([]{ GateInputs g = fx_gate(10); g.bus.fallback_profile_op_in_progress = true; g.bus.fallback_profile_capture_dispatch_running = true; g.bus.manual_write_in_progress = true; const FinalGate r = final_gate_decide(g, ecco_fbcap::ProbeResults{}); return (uint64_t) r.gr.code | ((uint64_t) r.gr.slot << 8) | ((uint64_t) ((r.gr.probe_fp ? 4 : 0) + (r.gr.probe_dump ? 2 : 0) + (r.gr.probe_r244 ? 1 : 0)) << 16) | ((uint64_t) r.gr.latch << 24); }()) == 263, "FB-B2 value: final_gate_decide [scenario 10 + own holds, probes none]: code | slot | probes | latch");
static_assert(text_is("SAVE REFUSED - a failback episode record exists; only the firmware that created it can resolve it", []{ GateInputs g = fx_gate(10); g.bus.fallback_profile_op_in_progress = true; g.bus.fallback_profile_capture_dispatch_running = true; g.bus.manual_write_in_progress = true; const FinalGate r = final_gate_decide(g, ecco_fbcap::ProbeResults{}); return r.text; }()), "FB-B2 text: final_gate_decide [scenario 10 + own holds, probes none]: text");
static_assert(text_is("FP:NP,DP:NP,R4:NP,MT:CN,FS:AC,BUS:OK", []{ GateInputs g = fx_gate(10); g.bus.fallback_profile_op_in_progress = true; g.bus.fallback_profile_capture_dispatch_running = true; g.bus.manual_write_in_progress = true; const FinalGate r = final_gate_decide(g, ecco_fbcap::ProbeResults{}); return r.gr.obl; }()), "FB-B2 text: final_gate_decide [scenario 10 + own holds, probes none]: obl");
static_assert(([]{ GateInputs g = fx_gate(10); g.bus.fallback_profile_op_in_progress = true; g.bus.fallback_profile_capture_dispatch_running = true; g.bus.manual_write_in_progress = true; const FinalGate r = final_gate_decide(g, ecco_fbcap::ProbeResults{ecco_fbcap::PROBE_ABSENT, ecco_fbcap::PROBE_CLEAR, ecco_fbcap::PROBE_ABSENT}); return (uint64_t) r.gr.code | ((uint64_t) r.gr.slot << 8) | ((uint64_t) ((r.gr.probe_fp ? 4 : 0) + (r.gr.probe_dump ? 2 : 0) + (r.gr.probe_r244 ? 1 : 0)) << 16) | ((uint64_t) r.gr.latch << 24); }()) == 263, "FB-B2 value: final_gate_decide [scenario 10 + own holds, probes all clear]: code | slot | probes | latch");
static_assert(text_is("SAVE REFUSED - a failback episode record exists; only the firmware that created it can resolve it", []{ GateInputs g = fx_gate(10); g.bus.fallback_profile_op_in_progress = true; g.bus.fallback_profile_capture_dispatch_running = true; g.bus.manual_write_in_progress = true; const FinalGate r = final_gate_decide(g, ecco_fbcap::ProbeResults{ecco_fbcap::PROBE_ABSENT, ecco_fbcap::PROBE_CLEAR, ecco_fbcap::PROBE_ABSENT}); return r.text; }()), "FB-B2 text: final_gate_decide [scenario 10 + own holds, probes all clear]: text");
static_assert(text_is("FP:CA,DP:CM,R4:CA,MT:CN,FS:AC,BUS:OK", []{ GateInputs g = fx_gate(10); g.bus.fallback_profile_op_in_progress = true; g.bus.fallback_profile_capture_dispatch_running = true; g.bus.manual_write_in_progress = true; const FinalGate r = final_gate_decide(g, ecco_fbcap::ProbeResults{ecco_fbcap::PROBE_ABSENT, ecco_fbcap::PROBE_CLEAR, ecco_fbcap::PROBE_ABSENT}); return r.gr.obl; }()), "FB-B2 text: final_gate_decide [scenario 10 + own holds, probes all clear]: obl");
static_assert(([]{ GateInputs g = fx_gate(10); g.bus.fallback_profile_op_in_progress = true; g.bus.fallback_profile_capture_dispatch_running = true; g.bus.manual_write_in_progress = true; return ecco_fbcap::gate_decide(g, ecco_fbcap::ProbeResults{}).code; }()) == 3, "FB-B2 value: gate_decide WITHOUT the masking [scenario 10 + own holds]: code (the SAVE itself would be refused as in flight)");
static_assert(([]{ GateInputs g = fx_gate(11); g.bus.fallback_profile_op_in_progress = true; g.bus.fallback_profile_capture_dispatch_running = true; g.bus.manual_write_in_progress = true; const FinalGate r = final_gate_decide(g, ecco_fbcap::ProbeResults{}); return (uint64_t) r.gr.code | ((uint64_t) r.gr.slot << 8) | ((uint64_t) ((r.gr.probe_fp ? 4 : 0) + (r.gr.probe_dump ? 2 : 0) + (r.gr.probe_r244 ? 1 : 0)) << 16) | ((uint64_t) r.gr.latch << 24); }()) == 263, "FB-B2 value: final_gate_decide [scenario 11 + own holds, probes none]: code | slot | probes | latch");
static_assert(text_is("SAVE REFUSED - Failback record recovery metadata is CORRUPT (hard lockout); Fallback never overwrites or proceeds past it; do not erase NVS", []{ GateInputs g = fx_gate(11); g.bus.fallback_profile_op_in_progress = true; g.bus.fallback_profile_capture_dispatch_running = true; g.bus.manual_write_in_progress = true; const FinalGate r = final_gate_decide(g, ecco_fbcap::ProbeResults{}); return r.text; }()), "FB-B2 text: final_gate_decide [scenario 11 + own holds, probes none]: text");
static_assert(text_is("FP:NP,DP:NP,R4:NP,MT:CN,FS:MC,BUS:OK", []{ GateInputs g = fx_gate(11); g.bus.fallback_profile_op_in_progress = true; g.bus.fallback_profile_capture_dispatch_running = true; g.bus.manual_write_in_progress = true; const FinalGate r = final_gate_decide(g, ecco_fbcap::ProbeResults{}); return r.gr.obl; }()), "FB-B2 text: final_gate_decide [scenario 11 + own holds, probes none]: obl");
static_assert(([]{ GateInputs g = fx_gate(11); g.bus.fallback_profile_op_in_progress = true; g.bus.fallback_profile_capture_dispatch_running = true; g.bus.manual_write_in_progress = true; const FinalGate r = final_gate_decide(g, ecco_fbcap::ProbeResults{ecco_fbcap::PROBE_ABSENT, ecco_fbcap::PROBE_CLEAR, ecco_fbcap::PROBE_ABSENT}); return (uint64_t) r.gr.code | ((uint64_t) r.gr.slot << 8) | ((uint64_t) ((r.gr.probe_fp ? 4 : 0) + (r.gr.probe_dump ? 2 : 0) + (r.gr.probe_r244 ? 1 : 0)) << 16) | ((uint64_t) r.gr.latch << 24); }()) == 263, "FB-B2 value: final_gate_decide [scenario 11 + own holds, probes all clear]: code | slot | probes | latch");
static_assert(text_is("SAVE REFUSED - Failback record recovery metadata is CORRUPT (hard lockout); Fallback never overwrites or proceeds past it; do not erase NVS", []{ GateInputs g = fx_gate(11); g.bus.fallback_profile_op_in_progress = true; g.bus.fallback_profile_capture_dispatch_running = true; g.bus.manual_write_in_progress = true; const FinalGate r = final_gate_decide(g, ecco_fbcap::ProbeResults{ecco_fbcap::PROBE_ABSENT, ecco_fbcap::PROBE_CLEAR, ecco_fbcap::PROBE_ABSENT}); return r.text; }()), "FB-B2 text: final_gate_decide [scenario 11 + own holds, probes all clear]: text");
static_assert(text_is("FP:CA,DP:CM,R4:CA,MT:CN,FS:MC,BUS:OK", []{ GateInputs g = fx_gate(11); g.bus.fallback_profile_op_in_progress = true; g.bus.fallback_profile_capture_dispatch_running = true; g.bus.manual_write_in_progress = true; const FinalGate r = final_gate_decide(g, ecco_fbcap::ProbeResults{ecco_fbcap::PROBE_ABSENT, ecco_fbcap::PROBE_CLEAR, ecco_fbcap::PROBE_ABSENT}); return r.gr.obl; }()), "FB-B2 text: final_gate_decide [scenario 11 + own holds, probes all clear]: obl");
static_assert(([]{ GateInputs g = fx_gate(11); g.bus.fallback_profile_op_in_progress = true; g.bus.fallback_profile_capture_dispatch_running = true; g.bus.manual_write_in_progress = true; return ecco_fbcap::gate_decide(g, ecco_fbcap::ProbeResults{}).code; }()) == 3, "FB-B2 value: gate_decide WITHOUT the masking [scenario 11 + own holds]: code (the SAVE itself would be refused as in flight)");
static_assert(([]{ GateInputs g = fx_gate(12); g.bus.fallback_profile_op_in_progress = true; g.bus.fallback_profile_capture_dispatch_running = true; g.bus.manual_write_in_progress = true; const FinalGate r = final_gate_decide(g, ecco_fbcap::ProbeResults{}); return (uint64_t) r.gr.code | ((uint64_t) r.gr.slot << 8) | ((uint64_t) ((r.gr.probe_fp ? 4 : 0) + (r.gr.probe_dump ? 2 : 0) + (r.gr.probe_r244 ? 1 : 0)) << 16) | ((uint64_t) r.gr.latch << 24); }()) == 263, "FB-B2 value: final_gate_decide [scenario 12 + own holds, probes none]: code | slot | probes | latch");
static_assert(text_is("SAVE REFUSED - Failback record recovery state UNKNOWN since boot (marker unreadable); an obligation cannot be ruled out; Fallback never proceeds past it", []{ GateInputs g = fx_gate(12); g.bus.fallback_profile_op_in_progress = true; g.bus.fallback_profile_capture_dispatch_running = true; g.bus.manual_write_in_progress = true; const FinalGate r = final_gate_decide(g, ecco_fbcap::ProbeResults{}); return r.text; }()), "FB-B2 text: final_gate_decide [scenario 12 + own holds, probes none]: text");
static_assert(text_is("FP:NP,DP:NP,R4:NP,MT:CN,FS:UR,BUS:OK", []{ GateInputs g = fx_gate(12); g.bus.fallback_profile_op_in_progress = true; g.bus.fallback_profile_capture_dispatch_running = true; g.bus.manual_write_in_progress = true; const FinalGate r = final_gate_decide(g, ecco_fbcap::ProbeResults{}); return r.gr.obl; }()), "FB-B2 text: final_gate_decide [scenario 12 + own holds, probes none]: obl");
static_assert(([]{ GateInputs g = fx_gate(12); g.bus.fallback_profile_op_in_progress = true; g.bus.fallback_profile_capture_dispatch_running = true; g.bus.manual_write_in_progress = true; const FinalGate r = final_gate_decide(g, ecco_fbcap::ProbeResults{ecco_fbcap::PROBE_ABSENT, ecco_fbcap::PROBE_CLEAR, ecco_fbcap::PROBE_ABSENT}); return (uint64_t) r.gr.code | ((uint64_t) r.gr.slot << 8) | ((uint64_t) ((r.gr.probe_fp ? 4 : 0) + (r.gr.probe_dump ? 2 : 0) + (r.gr.probe_r244 ? 1 : 0)) << 16) | ((uint64_t) r.gr.latch << 24); }()) == 263, "FB-B2 value: final_gate_decide [scenario 12 + own holds, probes all clear]: code | slot | probes | latch");
static_assert(text_is("SAVE REFUSED - Failback record recovery state UNKNOWN since boot (marker unreadable); an obligation cannot be ruled out; Fallback never proceeds past it", []{ GateInputs g = fx_gate(12); g.bus.fallback_profile_op_in_progress = true; g.bus.fallback_profile_capture_dispatch_running = true; g.bus.manual_write_in_progress = true; const FinalGate r = final_gate_decide(g, ecco_fbcap::ProbeResults{ecco_fbcap::PROBE_ABSENT, ecco_fbcap::PROBE_CLEAR, ecco_fbcap::PROBE_ABSENT}); return r.text; }()), "FB-B2 text: final_gate_decide [scenario 12 + own holds, probes all clear]: text");
static_assert(text_is("FP:CA,DP:CM,R4:CA,MT:CN,FS:UR,BUS:OK", []{ GateInputs g = fx_gate(12); g.bus.fallback_profile_op_in_progress = true; g.bus.fallback_profile_capture_dispatch_running = true; g.bus.manual_write_in_progress = true; const FinalGate r = final_gate_decide(g, ecco_fbcap::ProbeResults{ecco_fbcap::PROBE_ABSENT, ecco_fbcap::PROBE_CLEAR, ecco_fbcap::PROBE_ABSENT}); return r.gr.obl; }()), "FB-B2 text: final_gate_decide [scenario 12 + own holds, probes all clear]: obl");
static_assert(([]{ GateInputs g = fx_gate(12); g.bus.fallback_profile_op_in_progress = true; g.bus.fallback_profile_capture_dispatch_running = true; g.bus.manual_write_in_progress = true; return ecco_fbcap::gate_decide(g, ecco_fbcap::ProbeResults{}).code; }()) == 3, "FB-B2 value: gate_decide WITHOUT the masking [scenario 12 + own holds]: code (the SAVE itself would be refused as in flight)");
static_assert(([]{ GateInputs g = fx_gate(13); g.bus.fallback_profile_op_in_progress = true; g.bus.fallback_profile_capture_dispatch_running = true; g.bus.manual_write_in_progress = true; const FinalGate r = final_gate_decide(g, ecco_fbcap::ProbeResults{}); return (uint64_t) r.gr.code | ((uint64_t) r.gr.slot << 8) | ((uint64_t) ((r.gr.probe_fp ? 4 : 0) + (r.gr.probe_dump ? 2 : 0) + (r.gr.probe_r244 ? 1 : 0)) << 16) | ((uint64_t) r.gr.latch << 24); }()) == 520, "FB-B2 value: final_gate_decide [scenario 13 + own holds, probes none]: code | slot | probes | latch");
static_assert(text_is("SAVE REFUSED - Free Power is active; live settings are a temporary overlay - end it first", []{ GateInputs g = fx_gate(13); g.bus.fallback_profile_op_in_progress = true; g.bus.fallback_profile_capture_dispatch_running = true; g.bus.manual_write_in_progress = true; const FinalGate r = final_gate_decide(g, ecco_fbcap::ProbeResults{}); return r.text; }()), "FB-B2 text: final_gate_decide [scenario 13 + own holds, probes none]: text");
static_assert(text_is("FP:AC,DP:NP,R4:NP,MT:CN,FS:CA,BUS:OK", []{ GateInputs g = fx_gate(13); g.bus.fallback_profile_op_in_progress = true; g.bus.fallback_profile_capture_dispatch_running = true; g.bus.manual_write_in_progress = true; const FinalGate r = final_gate_decide(g, ecco_fbcap::ProbeResults{}); return r.gr.obl; }()), "FB-B2 text: final_gate_decide [scenario 13 + own holds, probes none]: obl");
static_assert(([]{ GateInputs g = fx_gate(13); g.bus.fallback_profile_op_in_progress = true; g.bus.fallback_profile_capture_dispatch_running = true; g.bus.manual_write_in_progress = true; const FinalGate r = final_gate_decide(g, ecco_fbcap::ProbeResults{ecco_fbcap::PROBE_ABSENT, ecco_fbcap::PROBE_CLEAR, ecco_fbcap::PROBE_ABSENT}); return (uint64_t) r.gr.code | ((uint64_t) r.gr.slot << 8) | ((uint64_t) ((r.gr.probe_fp ? 4 : 0) + (r.gr.probe_dump ? 2 : 0) + (r.gr.probe_r244 ? 1 : 0)) << 16) | ((uint64_t) r.gr.latch << 24); }()) == 520, "FB-B2 value: final_gate_decide [scenario 13 + own holds, probes all clear]: code | slot | probes | latch");
static_assert(text_is("SAVE REFUSED - Free Power is active; live settings are a temporary overlay - end it first", []{ GateInputs g = fx_gate(13); g.bus.fallback_profile_op_in_progress = true; g.bus.fallback_profile_capture_dispatch_running = true; g.bus.manual_write_in_progress = true; const FinalGate r = final_gate_decide(g, ecco_fbcap::ProbeResults{ecco_fbcap::PROBE_ABSENT, ecco_fbcap::PROBE_CLEAR, ecco_fbcap::PROBE_ABSENT}); return r.text; }()), "FB-B2 text: final_gate_decide [scenario 13 + own holds, probes all clear]: text");
static_assert(text_is("FP:AC,DP:CM,R4:CA,MT:CN,FS:CA,BUS:OK", []{ GateInputs g = fx_gate(13); g.bus.fallback_profile_op_in_progress = true; g.bus.fallback_profile_capture_dispatch_running = true; g.bus.manual_write_in_progress = true; const FinalGate r = final_gate_decide(g, ecco_fbcap::ProbeResults{ecco_fbcap::PROBE_ABSENT, ecco_fbcap::PROBE_CLEAR, ecco_fbcap::PROBE_ABSENT}); return r.gr.obl; }()), "FB-B2 text: final_gate_decide [scenario 13 + own holds, probes all clear]: obl");
static_assert(([]{ GateInputs g = fx_gate(13); g.bus.fallback_profile_op_in_progress = true; g.bus.fallback_profile_capture_dispatch_running = true; g.bus.manual_write_in_progress = true; return ecco_fbcap::gate_decide(g, ecco_fbcap::ProbeResults{}).code; }()) == 3, "FB-B2 value: gate_decide WITHOUT the masking [scenario 13 + own holds]: code (the SAVE itself would be refused as in flight)");
static_assert(([]{ GateInputs g = fx_gate(14); g.bus.fallback_profile_op_in_progress = true; g.bus.fallback_profile_capture_dispatch_running = true; g.bus.manual_write_in_progress = true; const FinalGate r = final_gate_decide(g, ecco_fbcap::ProbeResults{}); return (uint64_t) r.gr.code | ((uint64_t) r.gr.slot << 8) | ((uint64_t) ((r.gr.probe_fp ? 4 : 0) + (r.gr.probe_dump ? 2 : 0) + (r.gr.probe_r244 ? 1 : 0)) << 16) | ((uint64_t) r.gr.latch << 24); }()) == 777, "FB-B2 value: final_gate_decide [scenario 14 + own holds, probes none]: code | slot | probes | latch");
static_assert(text_is("SAVE REFUSED - Dump to Grid needs an operator recovery action first", []{ GateInputs g = fx_gate(14); g.bus.fallback_profile_op_in_progress = true; g.bus.fallback_profile_capture_dispatch_running = true; g.bus.manual_write_in_progress = true; const FinalGate r = final_gate_decide(g, ecco_fbcap::ProbeResults{}); return r.text; }()), "FB-B2 text: final_gate_decide [scenario 14 + own holds, probes none]: text");
static_assert(text_is("FP:NP,DP:ON,R4:NP,MT:CN,FS:CA,BUS:OK", []{ GateInputs g = fx_gate(14); g.bus.fallback_profile_op_in_progress = true; g.bus.fallback_profile_capture_dispatch_running = true; g.bus.manual_write_in_progress = true; const FinalGate r = final_gate_decide(g, ecco_fbcap::ProbeResults{}); return r.gr.obl; }()), "FB-B2 text: final_gate_decide [scenario 14 + own holds, probes none]: obl");
static_assert(([]{ GateInputs g = fx_gate(14); g.bus.fallback_profile_op_in_progress = true; g.bus.fallback_profile_capture_dispatch_running = true; g.bus.manual_write_in_progress = true; const FinalGate r = final_gate_decide(g, ecco_fbcap::ProbeResults{ecco_fbcap::PROBE_ABSENT, ecco_fbcap::PROBE_CLEAR, ecco_fbcap::PROBE_ABSENT}); return (uint64_t) r.gr.code | ((uint64_t) r.gr.slot << 8) | ((uint64_t) ((r.gr.probe_fp ? 4 : 0) + (r.gr.probe_dump ? 2 : 0) + (r.gr.probe_r244 ? 1 : 0)) << 16) | ((uint64_t) r.gr.latch << 24); }()) == 777, "FB-B2 value: final_gate_decide [scenario 14 + own holds, probes all clear]: code | slot | probes | latch");
static_assert(text_is("SAVE REFUSED - Dump to Grid needs an operator recovery action first", []{ GateInputs g = fx_gate(14); g.bus.fallback_profile_op_in_progress = true; g.bus.fallback_profile_capture_dispatch_running = true; g.bus.manual_write_in_progress = true; const FinalGate r = final_gate_decide(g, ecco_fbcap::ProbeResults{ecco_fbcap::PROBE_ABSENT, ecco_fbcap::PROBE_CLEAR, ecco_fbcap::PROBE_ABSENT}); return r.text; }()), "FB-B2 text: final_gate_decide [scenario 14 + own holds, probes all clear]: text");
static_assert(text_is("FP:CA,DP:ON,R4:CA,MT:CN,FS:CA,BUS:OK", []{ GateInputs g = fx_gate(14); g.bus.fallback_profile_op_in_progress = true; g.bus.fallback_profile_capture_dispatch_running = true; g.bus.manual_write_in_progress = true; const FinalGate r = final_gate_decide(g, ecco_fbcap::ProbeResults{ecco_fbcap::PROBE_ABSENT, ecco_fbcap::PROBE_CLEAR, ecco_fbcap::PROBE_ABSENT}); return r.gr.obl; }()), "FB-B2 text: final_gate_decide [scenario 14 + own holds, probes all clear]: obl");
static_assert(([]{ GateInputs g = fx_gate(14); g.bus.fallback_profile_op_in_progress = true; g.bus.fallback_profile_capture_dispatch_running = true; g.bus.manual_write_in_progress = true; return ecco_fbcap::gate_decide(g, ecco_fbcap::ProbeResults{}).code; }()) == 3, "FB-B2 value: gate_decide WITHOUT the masking [scenario 14 + own holds]: code (the SAVE itself would be refused as in flight)");
static_assert(([]{ GateInputs g = fx_gate(15); g.bus.fallback_profile_op_in_progress = true; g.bus.fallback_profile_capture_dispatch_running = true; g.bus.manual_write_in_progress = true; const FinalGate r = final_gate_decide(g, ecco_fbcap::ProbeResults{}); return (uint64_t) r.gr.code | ((uint64_t) r.gr.slot << 8) | ((uint64_t) ((r.gr.probe_fp ? 4 : 0) + (r.gr.probe_dump ? 2 : 0) + (r.gr.probe_r244 ? 1 : 0)) << 16) | ((uint64_t) r.gr.latch << 24); }()) == 1034, "FB-B2 value: final_gate_decide [scenario 15 + own holds, probes none]: code | slot | probes | latch");
static_assert(text_is("SAVE REFUSED - Register 244 test restore verified; durable clear still pending - press Restore Original (armed)", []{ GateInputs g = fx_gate(15); g.bus.fallback_profile_op_in_progress = true; g.bus.fallback_profile_capture_dispatch_running = true; g.bus.manual_write_in_progress = true; const FinalGate r = final_gate_decide(g, ecco_fbcap::ProbeResults{}); return r.text; }()), "FB-B2 text: final_gate_decide [scenario 15 + own holds, probes none]: text");
static_assert(text_is("FP:NP,DP:NP,R4:PC,MT:CN,FS:CA,BUS:OK", []{ GateInputs g = fx_gate(15); g.bus.fallback_profile_op_in_progress = true; g.bus.fallback_profile_capture_dispatch_running = true; g.bus.manual_write_in_progress = true; const FinalGate r = final_gate_decide(g, ecco_fbcap::ProbeResults{}); return r.gr.obl; }()), "FB-B2 text: final_gate_decide [scenario 15 + own holds, probes none]: obl");
static_assert(([]{ GateInputs g = fx_gate(15); g.bus.fallback_profile_op_in_progress = true; g.bus.fallback_profile_capture_dispatch_running = true; g.bus.manual_write_in_progress = true; const FinalGate r = final_gate_decide(g, ecco_fbcap::ProbeResults{ecco_fbcap::PROBE_ABSENT, ecco_fbcap::PROBE_CLEAR, ecco_fbcap::PROBE_ABSENT}); return (uint64_t) r.gr.code | ((uint64_t) r.gr.slot << 8) | ((uint64_t) ((r.gr.probe_fp ? 4 : 0) + (r.gr.probe_dump ? 2 : 0) + (r.gr.probe_r244 ? 1 : 0)) << 16) | ((uint64_t) r.gr.latch << 24); }()) == 1034, "FB-B2 value: final_gate_decide [scenario 15 + own holds, probes all clear]: code | slot | probes | latch");
static_assert(text_is("SAVE REFUSED - Register 244 test restore verified; durable clear still pending - press Restore Original (armed)", []{ GateInputs g = fx_gate(15); g.bus.fallback_profile_op_in_progress = true; g.bus.fallback_profile_capture_dispatch_running = true; g.bus.manual_write_in_progress = true; const FinalGate r = final_gate_decide(g, ecco_fbcap::ProbeResults{ecco_fbcap::PROBE_ABSENT, ecco_fbcap::PROBE_CLEAR, ecco_fbcap::PROBE_ABSENT}); return r.text; }()), "FB-B2 text: final_gate_decide [scenario 15 + own holds, probes all clear]: text");
static_assert(text_is("FP:CA,DP:CM,R4:PC,MT:CN,FS:CA,BUS:OK", []{ GateInputs g = fx_gate(15); g.bus.fallback_profile_op_in_progress = true; g.bus.fallback_profile_capture_dispatch_running = true; g.bus.manual_write_in_progress = true; const FinalGate r = final_gate_decide(g, ecco_fbcap::ProbeResults{ecco_fbcap::PROBE_ABSENT, ecco_fbcap::PROBE_CLEAR, ecco_fbcap::PROBE_ABSENT}); return r.gr.obl; }()), "FB-B2 text: final_gate_decide [scenario 15 + own holds, probes all clear]: obl");
static_assert(([]{ GateInputs g = fx_gate(15); g.bus.fallback_profile_op_in_progress = true; g.bus.fallback_profile_capture_dispatch_running = true; g.bus.manual_write_in_progress = true; return ecco_fbcap::gate_decide(g, ecco_fbcap::ProbeResults{}).code; }()) == 3, "FB-B2 value: gate_decide WITHOUT the masking [scenario 15 + own holds]: code (the SAVE itself would be refused as in flight)");
static_assert(([]{ GateInputs g = fx_gate(16); g.bus.fallback_profile_op_in_progress = true; g.bus.fallback_profile_capture_dispatch_running = true; g.bus.manual_write_in_progress = true; const FinalGate r = final_gate_decide(g, ecco_fbcap::ProbeResults{}); return (uint64_t) r.gr.code | ((uint64_t) r.gr.slot << 8) | ((uint64_t) ((r.gr.probe_fp ? 4 : 0) + (r.gr.probe_dump ? 2 : 0) + (r.gr.probe_r244 ? 1 : 0)) << 16) | ((uint64_t) r.gr.latch << 24); }()) == 16777736, "FB-B2 value: final_gate_decide [scenario 16 + own holds, probes none]: code | slot | probes | latch");
static_assert(text_is("SAVE REFUSED - Free Power recovery marker became unreadable at runtime; saving blocked until reboot. After reboot it may read absent: verify live settings first; do not erase NVS", []{ GateInputs g = fx_gate(16); g.bus.fallback_profile_op_in_progress = true; g.bus.fallback_profile_capture_dispatch_running = true; g.bus.manual_write_in_progress = true; const FinalGate r = final_gate_decide(g, ecco_fbcap::ProbeResults{}); return r.text; }()), "FB-B2 text: final_gate_decide [scenario 16 + own holds, probes none]: text");
static_assert(text_is("FP:UR,DP:NP,R4:NP,MT:CN,FS:CA,BUS:OK", []{ GateInputs g = fx_gate(16); g.bus.fallback_profile_op_in_progress = true; g.bus.fallback_profile_capture_dispatch_running = true; g.bus.manual_write_in_progress = true; const FinalGate r = final_gate_decide(g, ecco_fbcap::ProbeResults{}); return r.gr.obl; }()), "FB-B2 text: final_gate_decide [scenario 16 + own holds, probes none]: obl");
static_assert(([]{ GateInputs g = fx_gate(16); g.bus.fallback_profile_op_in_progress = true; g.bus.fallback_profile_capture_dispatch_running = true; g.bus.manual_write_in_progress = true; const FinalGate r = final_gate_decide(g, ecco_fbcap::ProbeResults{ecco_fbcap::PROBE_ABSENT, ecco_fbcap::PROBE_CLEAR, ecco_fbcap::PROBE_ABSENT}); return (uint64_t) r.gr.code | ((uint64_t) r.gr.slot << 8) | ((uint64_t) ((r.gr.probe_fp ? 4 : 0) + (r.gr.probe_dump ? 2 : 0) + (r.gr.probe_r244 ? 1 : 0)) << 16) | ((uint64_t) r.gr.latch << 24); }()) == 16777736, "FB-B2 value: final_gate_decide [scenario 16 + own holds, probes all clear]: code | slot | probes | latch");
static_assert(text_is("SAVE REFUSED - Free Power recovery marker became unreadable at runtime; saving blocked until reboot. After reboot it may read absent: verify live settings first; do not erase NVS", []{ GateInputs g = fx_gate(16); g.bus.fallback_profile_op_in_progress = true; g.bus.fallback_profile_capture_dispatch_running = true; g.bus.manual_write_in_progress = true; const FinalGate r = final_gate_decide(g, ecco_fbcap::ProbeResults{ecco_fbcap::PROBE_ABSENT, ecco_fbcap::PROBE_CLEAR, ecco_fbcap::PROBE_ABSENT}); return r.text; }()), "FB-B2 text: final_gate_decide [scenario 16 + own holds, probes all clear]: text");
static_assert(text_is("FP:UR,DP:CM,R4:CA,MT:CN,FS:CA,BUS:OK", []{ GateInputs g = fx_gate(16); g.bus.fallback_profile_op_in_progress = true; g.bus.fallback_profile_capture_dispatch_running = true; g.bus.manual_write_in_progress = true; const FinalGate r = final_gate_decide(g, ecco_fbcap::ProbeResults{ecco_fbcap::PROBE_ABSENT, ecco_fbcap::PROBE_CLEAR, ecco_fbcap::PROBE_ABSENT}); return r.gr.obl; }()), "FB-B2 text: final_gate_decide [scenario 16 + own holds, probes all clear]: obl");
static_assert(([]{ GateInputs g = fx_gate(16); g.bus.fallback_profile_op_in_progress = true; g.bus.fallback_profile_capture_dispatch_running = true; g.bus.manual_write_in_progress = true; return ecco_fbcap::gate_decide(g, ecco_fbcap::ProbeResults{}).code; }()) == 3, "FB-B2 value: gate_decide WITHOUT the masking [scenario 16 + own holds]: code (the SAVE itself would be refused as in flight)");
static_assert(([]{ GateInputs g = fx_gate(17); g.bus.fallback_profile_op_in_progress = true; g.bus.fallback_profile_capture_dispatch_running = true; g.bus.manual_write_in_progress = true; const FinalGate r = final_gate_decide(g, ecco_fbcap::ProbeResults{}); return (uint64_t) r.gr.code | ((uint64_t) r.gr.slot << 8) | ((uint64_t) ((r.gr.probe_fp ? 4 : 0) + (r.gr.probe_dump ? 2 : 0) + (r.gr.probe_r244 ? 1 : 0)) << 16) | ((uint64_t) r.gr.latch << 24); }()) == 65285, "FB-B2 value: final_gate_decide [scenario 17 + own holds, probes none]: code | slot | probes | latch");
static_assert(text_is("SAVE REFUSED - a Free Power / Dump to Grid / Manual Configuration write arm is on; finish or turn it off first", []{ GateInputs g = fx_gate(17); g.bus.fallback_profile_op_in_progress = true; g.bus.fallback_profile_capture_dispatch_running = true; g.bus.manual_write_in_progress = true; const FinalGate r = final_gate_decide(g, ecco_fbcap::ProbeResults{}); return r.text; }()), "FB-B2 text: final_gate_decide [scenario 17 + own holds, probes none]: text");
static_assert(text_is("FP:NP,DP:NP,R4:NP,MT:CN,FS:CA,BUS:OK", []{ GateInputs g = fx_gate(17); g.bus.fallback_profile_op_in_progress = true; g.bus.fallback_profile_capture_dispatch_running = true; g.bus.manual_write_in_progress = true; const FinalGate r = final_gate_decide(g, ecco_fbcap::ProbeResults{}); return r.gr.obl; }()), "FB-B2 text: final_gate_decide [scenario 17 + own holds, probes none]: obl");
static_assert(([]{ GateInputs g = fx_gate(17); g.bus.fallback_profile_op_in_progress = true; g.bus.fallback_profile_capture_dispatch_running = true; g.bus.manual_write_in_progress = true; const FinalGate r = final_gate_decide(g, ecco_fbcap::ProbeResults{ecco_fbcap::PROBE_ABSENT, ecco_fbcap::PROBE_CLEAR, ecco_fbcap::PROBE_ABSENT}); return (uint64_t) r.gr.code | ((uint64_t) r.gr.slot << 8) | ((uint64_t) ((r.gr.probe_fp ? 4 : 0) + (r.gr.probe_dump ? 2 : 0) + (r.gr.probe_r244 ? 1 : 0)) << 16) | ((uint64_t) r.gr.latch << 24); }()) == 65285, "FB-B2 value: final_gate_decide [scenario 17 + own holds, probes all clear]: code | slot | probes | latch");
static_assert(text_is("SAVE REFUSED - a Free Power / Dump to Grid / Manual Configuration write arm is on; finish or turn it off first", []{ GateInputs g = fx_gate(17); g.bus.fallback_profile_op_in_progress = true; g.bus.fallback_profile_capture_dispatch_running = true; g.bus.manual_write_in_progress = true; const FinalGate r = final_gate_decide(g, ecco_fbcap::ProbeResults{ecco_fbcap::PROBE_ABSENT, ecco_fbcap::PROBE_CLEAR, ecco_fbcap::PROBE_ABSENT}); return r.text; }()), "FB-B2 text: final_gate_decide [scenario 17 + own holds, probes all clear]: text");
static_assert(text_is("FP:CA,DP:CM,R4:CA,MT:CN,FS:CA,BUS:OK", []{ GateInputs g = fx_gate(17); g.bus.fallback_profile_op_in_progress = true; g.bus.fallback_profile_capture_dispatch_running = true; g.bus.manual_write_in_progress = true; const FinalGate r = final_gate_decide(g, ecco_fbcap::ProbeResults{ecco_fbcap::PROBE_ABSENT, ecco_fbcap::PROBE_CLEAR, ecco_fbcap::PROBE_ABSENT}); return r.gr.obl; }()), "FB-B2 text: final_gate_decide [scenario 17 + own holds, probes all clear]: obl");
static_assert(([]{ GateInputs g = fx_gate(17); g.bus.fallback_profile_op_in_progress = true; g.bus.fallback_profile_capture_dispatch_running = true; g.bus.manual_write_in_progress = true; return ecco_fbcap::gate_decide(g, ecco_fbcap::ProbeResults{}).code; }()) == 3, "FB-B2 value: gate_decide WITHOUT the masking [scenario 17 + own holds]: code (the SAVE itself would be refused as in flight)");
static_assert(([]{ GateInputs g = fx_gate(18); g.bus.fallback_profile_op_in_progress = true; g.bus.fallback_profile_capture_dispatch_running = true; g.bus.manual_write_in_progress = true; const FinalGate r = final_gate_decide(g, ecco_fbcap::ProbeResults{}); return (uint64_t) r.gr.code | ((uint64_t) r.gr.slot << 8) | ((uint64_t) ((r.gr.probe_fp ? 4 : 0) + (r.gr.probe_dump ? 2 : 0) + (r.gr.probe_r244 ? 1 : 0)) << 16) | ((uint64_t) r.gr.latch << 24); }()) == 263, "FB-B2 value: final_gate_decide [scenario 18 + own holds, probes none]: code | slot | probes | latch");
static_assert(text_is("SAVE REFUSED - a failback episode record exists; only the firmware that created it can resolve it", []{ GateInputs g = fx_gate(18); g.bus.fallback_profile_op_in_progress = true; g.bus.fallback_profile_capture_dispatch_running = true; g.bus.manual_write_in_progress = true; const FinalGate r = final_gate_decide(g, ecco_fbcap::ProbeResults{}); return r.text; }()), "FB-B2 text: final_gate_decide [scenario 18 + own holds, probes none]: text");
static_assert(text_is("FP:NP,DP:NP,R4:NP,MT:CN,FS:AC,BUS:OK", []{ GateInputs g = fx_gate(18); g.bus.fallback_profile_op_in_progress = true; g.bus.fallback_profile_capture_dispatch_running = true; g.bus.manual_write_in_progress = true; const FinalGate r = final_gate_decide(g, ecco_fbcap::ProbeResults{}); return r.gr.obl; }()), "FB-B2 text: final_gate_decide [scenario 18 + own holds, probes none]: obl");
static_assert(([]{ GateInputs g = fx_gate(18); g.bus.fallback_profile_op_in_progress = true; g.bus.fallback_profile_capture_dispatch_running = true; g.bus.manual_write_in_progress = true; const FinalGate r = final_gate_decide(g, ecco_fbcap::ProbeResults{ecco_fbcap::PROBE_ABSENT, ecco_fbcap::PROBE_CLEAR, ecco_fbcap::PROBE_ABSENT}); return (uint64_t) r.gr.code | ((uint64_t) r.gr.slot << 8) | ((uint64_t) ((r.gr.probe_fp ? 4 : 0) + (r.gr.probe_dump ? 2 : 0) + (r.gr.probe_r244 ? 1 : 0)) << 16) | ((uint64_t) r.gr.latch << 24); }()) == 263, "FB-B2 value: final_gate_decide [scenario 18 + own holds, probes all clear]: code | slot | probes | latch");
static_assert(text_is("SAVE REFUSED - a failback episode record exists; only the firmware that created it can resolve it", []{ GateInputs g = fx_gate(18); g.bus.fallback_profile_op_in_progress = true; g.bus.fallback_profile_capture_dispatch_running = true; g.bus.manual_write_in_progress = true; const FinalGate r = final_gate_decide(g, ecco_fbcap::ProbeResults{ecco_fbcap::PROBE_ABSENT, ecco_fbcap::PROBE_CLEAR, ecco_fbcap::PROBE_ABSENT}); return r.text; }()), "FB-B2 text: final_gate_decide [scenario 18 + own holds, probes all clear]: text");
static_assert(text_is("FP:CA,DP:CM,R4:CA,MT:CN,FS:AC,BUS:OK", []{ GateInputs g = fx_gate(18); g.bus.fallback_profile_op_in_progress = true; g.bus.fallback_profile_capture_dispatch_running = true; g.bus.manual_write_in_progress = true; const FinalGate r = final_gate_decide(g, ecco_fbcap::ProbeResults{ecco_fbcap::PROBE_ABSENT, ecco_fbcap::PROBE_CLEAR, ecco_fbcap::PROBE_ABSENT}); return r.gr.obl; }()), "FB-B2 text: final_gate_decide [scenario 18 + own holds, probes all clear]: obl");
static_assert(([]{ GateInputs g = fx_gate(18); g.bus.fallback_profile_op_in_progress = true; g.bus.fallback_profile_capture_dispatch_running = true; g.bus.manual_write_in_progress = true; return ecco_fbcap::gate_decide(g, ecco_fbcap::ProbeResults{}).code; }()) == 3, "FB-B2 value: gate_decide WITHOUT the masking [scenario 18 + own holds]: code (the SAVE itself would be refused as in flight)");
static_assert(([]{ GateInputs g = fx_gate(19); g.bus.fallback_profile_op_in_progress = true; g.bus.fallback_profile_capture_dispatch_running = true; g.bus.manual_write_in_progress = true; const FinalGate r = final_gate_decide(g, ecco_fbcap::ProbeResults{}); return (uint64_t) r.gr.code | ((uint64_t) r.gr.slot << 8) | ((uint64_t) ((r.gr.probe_fp ? 4 : 0) + (r.gr.probe_dump ? 2 : 0) + (r.gr.probe_r244 ? 1 : 0)) << 16) | ((uint64_t) r.gr.latch << 24); }()) == 520, "FB-B2 value: final_gate_decide [scenario 19 + own holds, probes none]: code | slot | probes | latch");
static_assert(text_is("SAVE REFUSED - Free Power in-memory recovery state is inconsistent; a reboot must re-derive it before saving", []{ GateInputs g = fx_gate(19); g.bus.fallback_profile_op_in_progress = true; g.bus.fallback_profile_capture_dispatch_running = true; g.bus.manual_write_in_progress = true; const FinalGate r = final_gate_decide(g, ecco_fbcap::ProbeResults{}); return r.text; }()), "FB-B2 text: final_gate_decide [scenario 19 + own holds, probes none]: text");
static_assert(text_is("FP:DV,DP:DV,R4:NP,MT:CN,FS:CA,BUS:OK", []{ GateInputs g = fx_gate(19); g.bus.fallback_profile_op_in_progress = true; g.bus.fallback_profile_capture_dispatch_running = true; g.bus.manual_write_in_progress = true; const FinalGate r = final_gate_decide(g, ecco_fbcap::ProbeResults{}); return r.gr.obl; }()), "FB-B2 text: final_gate_decide [scenario 19 + own holds, probes none]: obl");
static_assert(([]{ GateInputs g = fx_gate(19); g.bus.fallback_profile_op_in_progress = true; g.bus.fallback_profile_capture_dispatch_running = true; g.bus.manual_write_in_progress = true; const FinalGate r = final_gate_decide(g, ecco_fbcap::ProbeResults{ecco_fbcap::PROBE_ABSENT, ecco_fbcap::PROBE_CLEAR, ecco_fbcap::PROBE_ABSENT}); return (uint64_t) r.gr.code | ((uint64_t) r.gr.slot << 8) | ((uint64_t) ((r.gr.probe_fp ? 4 : 0) + (r.gr.probe_dump ? 2 : 0) + (r.gr.probe_r244 ? 1 : 0)) << 16) | ((uint64_t) r.gr.latch << 24); }()) == 520, "FB-B2 value: final_gate_decide [scenario 19 + own holds, probes all clear]: code | slot | probes | latch");
static_assert(text_is("SAVE REFUSED - Free Power in-memory recovery state is inconsistent; a reboot must re-derive it before saving", []{ GateInputs g = fx_gate(19); g.bus.fallback_profile_op_in_progress = true; g.bus.fallback_profile_capture_dispatch_running = true; g.bus.manual_write_in_progress = true; const FinalGate r = final_gate_decide(g, ecco_fbcap::ProbeResults{ecco_fbcap::PROBE_ABSENT, ecco_fbcap::PROBE_CLEAR, ecco_fbcap::PROBE_ABSENT}); return r.text; }()), "FB-B2 text: final_gate_decide [scenario 19 + own holds, probes all clear]: text");
static_assert(text_is("FP:DV,DP:DV,R4:CA,MT:CN,FS:CA,BUS:OK", []{ GateInputs g = fx_gate(19); g.bus.fallback_profile_op_in_progress = true; g.bus.fallback_profile_capture_dispatch_running = true; g.bus.manual_write_in_progress = true; const FinalGate r = final_gate_decide(g, ecco_fbcap::ProbeResults{ecco_fbcap::PROBE_ABSENT, ecco_fbcap::PROBE_CLEAR, ecco_fbcap::PROBE_ABSENT}); return r.gr.obl; }()), "FB-B2 text: final_gate_decide [scenario 19 + own holds, probes all clear]: obl");
static_assert(([]{ GateInputs g = fx_gate(19); g.bus.fallback_profile_op_in_progress = true; g.bus.fallback_profile_capture_dispatch_running = true; g.bus.manual_write_in_progress = true; return ecco_fbcap::gate_decide(g, ecco_fbcap::ProbeResults{}).code; }()) == 3, "FB-B2 value: gate_decide WITHOUT the masking [scenario 19 + own holds]: code (the SAVE itself would be refused as in flight)");
static_assert(([]{ GateInputs g = fx_gate(20); g.bus.fallback_profile_op_in_progress = true; g.bus.fallback_profile_capture_dispatch_running = true; g.bus.manual_write_in_progress = true; const FinalGate r = final_gate_decide(g, ecco_fbcap::ProbeResults{}); return (uint64_t) r.gr.code | ((uint64_t) r.gr.slot << 8) | ((uint64_t) ((r.gr.probe_fp ? 4 : 0) + (r.gr.probe_dump ? 2 : 0) + (r.gr.probe_r244 ? 1 : 0)) << 16) | ((uint64_t) r.gr.latch << 24); }()) == 6, "FB-B2 value: final_gate_decide [scenario 20 + own holds, probes none]: code | slot | probes | latch");
static_assert(text_is("SAVE REFUSED - another inverter transaction is in progress (clock verification); try again shortly", []{ GateInputs g = fx_gate(20); g.bus.fallback_profile_op_in_progress = true; g.bus.fallback_profile_capture_dispatch_running = true; g.bus.manual_write_in_progress = true; const FinalGate r = final_gate_decide(g, ecco_fbcap::ProbeResults{}); return r.text; }()), "FB-B2 text: final_gate_decide [scenario 20 + own holds, probes none]: text");
static_assert(text_is("FP:NP,DP:NP,R4:NP,MT:NP,FS:CA,BUS:BY", []{ GateInputs g = fx_gate(20); g.bus.fallback_profile_op_in_progress = true; g.bus.fallback_profile_capture_dispatch_running = true; g.bus.manual_write_in_progress = true; const FinalGate r = final_gate_decide(g, ecco_fbcap::ProbeResults{}); return r.gr.obl; }()), "FB-B2 text: final_gate_decide [scenario 20 + own holds, probes none]: obl");
static_assert(([]{ GateInputs g = fx_gate(20); g.bus.fallback_profile_op_in_progress = true; g.bus.fallback_profile_capture_dispatch_running = true; g.bus.manual_write_in_progress = true; const FinalGate r = final_gate_decide(g, ecco_fbcap::ProbeResults{ecco_fbcap::PROBE_ABSENT, ecco_fbcap::PROBE_CLEAR, ecco_fbcap::PROBE_ABSENT}); return (uint64_t) r.gr.code | ((uint64_t) r.gr.slot << 8) | ((uint64_t) ((r.gr.probe_fp ? 4 : 0) + (r.gr.probe_dump ? 2 : 0) + (r.gr.probe_r244 ? 1 : 0)) << 16) | ((uint64_t) r.gr.latch << 24); }()) == 6, "FB-B2 value: final_gate_decide [scenario 20 + own holds, probes all clear]: code | slot | probes | latch");
static_assert(text_is("SAVE REFUSED - another inverter transaction is in progress (clock verification); try again shortly", []{ GateInputs g = fx_gate(20); g.bus.fallback_profile_op_in_progress = true; g.bus.fallback_profile_capture_dispatch_running = true; g.bus.manual_write_in_progress = true; const FinalGate r = final_gate_decide(g, ecco_fbcap::ProbeResults{ecco_fbcap::PROBE_ABSENT, ecco_fbcap::PROBE_CLEAR, ecco_fbcap::PROBE_ABSENT}); return r.text; }()), "FB-B2 text: final_gate_decide [scenario 20 + own holds, probes all clear]: text");
static_assert(text_is("FP:CA,DP:CM,R4:CA,MT:NP,FS:CA,BUS:BY", []{ GateInputs g = fx_gate(20); g.bus.fallback_profile_op_in_progress = true; g.bus.fallback_profile_capture_dispatch_running = true; g.bus.manual_write_in_progress = true; const FinalGate r = final_gate_decide(g, ecco_fbcap::ProbeResults{ecco_fbcap::PROBE_ABSENT, ecco_fbcap::PROBE_CLEAR, ecco_fbcap::PROBE_ABSENT}); return r.gr.obl; }()), "FB-B2 text: final_gate_decide [scenario 20 + own holds, probes all clear]: obl");
static_assert(([]{ GateInputs g = fx_gate(20); g.bus.fallback_profile_op_in_progress = true; g.bus.fallback_profile_capture_dispatch_running = true; g.bus.manual_write_in_progress = true; return ecco_fbcap::gate_decide(g, ecco_fbcap::ProbeResults{}).code; }()) == 3, "FB-B2 value: gate_decide WITHOUT the masking [scenario 20 + own holds]: code (the SAVE itself would be refused as in flight)");
static_assert(([]{ GateInputs g = fx_gate(21); g.bus.fallback_profile_op_in_progress = true; g.bus.fallback_profile_capture_dispatch_running = true; g.bus.manual_write_in_progress = true; const FinalGate r = final_gate_decide(g, ecco_fbcap::ProbeResults{}); return (uint64_t) r.gr.code | ((uint64_t) r.gr.slot << 8) | ((uint64_t) ((r.gr.probe_fp ? 4 : 0) + (r.gr.probe_dump ? 2 : 0) + (r.gr.probe_r244 ? 1 : 0)) << 16) | ((uint64_t) r.gr.latch << 24); }()) == 6, "FB-B2 value: final_gate_decide [scenario 21 + own holds, probes none]: code | slot | probes | latch");
static_assert(text_is("SAVE REFUSED - another inverter transaction is in progress (Register 244 test); try again shortly", []{ GateInputs g = fx_gate(21); g.bus.fallback_profile_op_in_progress = true; g.bus.fallback_profile_capture_dispatch_running = true; g.bus.manual_write_in_progress = true; const FinalGate r = final_gate_decide(g, ecco_fbcap::ProbeResults{}); return r.text; }()), "FB-B2 text: final_gate_decide [scenario 21 + own holds, probes none]: text");
static_assert(text_is("FP:NP,DP:NP,R4:LK,MT:NP,FS:CA,BUS:BY", []{ GateInputs g = fx_gate(21); g.bus.fallback_profile_op_in_progress = true; g.bus.fallback_profile_capture_dispatch_running = true; g.bus.manual_write_in_progress = true; const FinalGate r = final_gate_decide(g, ecco_fbcap::ProbeResults{}); return r.gr.obl; }()), "FB-B2 text: final_gate_decide [scenario 21 + own holds, probes none]: obl");
static_assert(([]{ GateInputs g = fx_gate(21); g.bus.fallback_profile_op_in_progress = true; g.bus.fallback_profile_capture_dispatch_running = true; g.bus.manual_write_in_progress = true; const FinalGate r = final_gate_decide(g, ecco_fbcap::ProbeResults{ecco_fbcap::PROBE_ABSENT, ecco_fbcap::PROBE_CLEAR, ecco_fbcap::PROBE_ABSENT}); return (uint64_t) r.gr.code | ((uint64_t) r.gr.slot << 8) | ((uint64_t) ((r.gr.probe_fp ? 4 : 0) + (r.gr.probe_dump ? 2 : 0) + (r.gr.probe_r244 ? 1 : 0)) << 16) | ((uint64_t) r.gr.latch << 24); }()) == 6, "FB-B2 value: final_gate_decide [scenario 21 + own holds, probes all clear]: code | slot | probes | latch");
static_assert(text_is("SAVE REFUSED - another inverter transaction is in progress (Register 244 test); try again shortly", []{ GateInputs g = fx_gate(21); g.bus.fallback_profile_op_in_progress = true; g.bus.fallback_profile_capture_dispatch_running = true; g.bus.manual_write_in_progress = true; const FinalGate r = final_gate_decide(g, ecco_fbcap::ProbeResults{ecco_fbcap::PROBE_ABSENT, ecco_fbcap::PROBE_CLEAR, ecco_fbcap::PROBE_ABSENT}); return r.text; }()), "FB-B2 text: final_gate_decide [scenario 21 + own holds, probes all clear]: text");
static_assert(text_is("FP:CA,DP:CM,R4:LK,MT:NP,FS:CA,BUS:BY", []{ GateInputs g = fx_gate(21); g.bus.fallback_profile_op_in_progress = true; g.bus.fallback_profile_capture_dispatch_running = true; g.bus.manual_write_in_progress = true; const FinalGate r = final_gate_decide(g, ecco_fbcap::ProbeResults{ecco_fbcap::PROBE_ABSENT, ecco_fbcap::PROBE_CLEAR, ecco_fbcap::PROBE_ABSENT}); return r.gr.obl; }()), "FB-B2 text: final_gate_decide [scenario 21 + own holds, probes all clear]: obl");
static_assert(([]{ GateInputs g = fx_gate(21); g.bus.fallback_profile_op_in_progress = true; g.bus.fallback_profile_capture_dispatch_running = true; g.bus.manual_write_in_progress = true; return ecco_fbcap::gate_decide(g, ecco_fbcap::ProbeResults{}).code; }()) == 3, "FB-B2 value: gate_decide WITHOUT the masking [scenario 21 + own holds]: code (the SAVE itself would be refused as in flight)");
static_assert(([]{ GateInputs g = fx_gate(22); g.bus.fallback_profile_op_in_progress = true; g.bus.fallback_profile_capture_dispatch_running = true; g.bus.manual_write_in_progress = true; const FinalGate r = final_gate_decide(g, ecco_fbcap::ProbeResults{}); return (uint64_t) r.gr.code | ((uint64_t) r.gr.slot << 8) | ((uint64_t) ((r.gr.probe_fp ? 4 : 0) + (r.gr.probe_dump ? 2 : 0) + (r.gr.probe_r244 ? 1 : 0)) << 16) | ((uint64_t) r.gr.latch << 24); }()) == 6, "FB-B2 value: final_gate_decide [scenario 22 + own holds, probes none]: code | slot | probes | latch");
static_assert(text_is("SAVE REFUSED - another inverter transaction is in progress (Free Power); try again shortly", []{ GateInputs g = fx_gate(22); g.bus.fallback_profile_op_in_progress = true; g.bus.fallback_profile_capture_dispatch_running = true; g.bus.manual_write_in_progress = true; const FinalGate r = final_gate_decide(g, ecco_fbcap::ProbeResults{}); return r.text; }()), "FB-B2 text: final_gate_decide [scenario 22 + own holds, probes none]: text");
static_assert(text_is("FP:LK,DP:NP,R4:NP,MT:NP,FS:CA,BUS:BY", []{ GateInputs g = fx_gate(22); g.bus.fallback_profile_op_in_progress = true; g.bus.fallback_profile_capture_dispatch_running = true; g.bus.manual_write_in_progress = true; const FinalGate r = final_gate_decide(g, ecco_fbcap::ProbeResults{}); return r.gr.obl; }()), "FB-B2 text: final_gate_decide [scenario 22 + own holds, probes none]: obl");
static_assert(([]{ GateInputs g = fx_gate(22); g.bus.fallback_profile_op_in_progress = true; g.bus.fallback_profile_capture_dispatch_running = true; g.bus.manual_write_in_progress = true; const FinalGate r = final_gate_decide(g, ecco_fbcap::ProbeResults{ecco_fbcap::PROBE_ABSENT, ecco_fbcap::PROBE_CLEAR, ecco_fbcap::PROBE_ABSENT}); return (uint64_t) r.gr.code | ((uint64_t) r.gr.slot << 8) | ((uint64_t) ((r.gr.probe_fp ? 4 : 0) + (r.gr.probe_dump ? 2 : 0) + (r.gr.probe_r244 ? 1 : 0)) << 16) | ((uint64_t) r.gr.latch << 24); }()) == 6, "FB-B2 value: final_gate_decide [scenario 22 + own holds, probes all clear]: code | slot | probes | latch");
static_assert(text_is("SAVE REFUSED - another inverter transaction is in progress (Free Power); try again shortly", []{ GateInputs g = fx_gate(22); g.bus.fallback_profile_op_in_progress = true; g.bus.fallback_profile_capture_dispatch_running = true; g.bus.manual_write_in_progress = true; const FinalGate r = final_gate_decide(g, ecco_fbcap::ProbeResults{ecco_fbcap::PROBE_ABSENT, ecco_fbcap::PROBE_CLEAR, ecco_fbcap::PROBE_ABSENT}); return r.text; }()), "FB-B2 text: final_gate_decide [scenario 22 + own holds, probes all clear]: text");
static_assert(text_is("FP:LK,DP:CM,R4:CA,MT:NP,FS:CA,BUS:BY", []{ GateInputs g = fx_gate(22); g.bus.fallback_profile_op_in_progress = true; g.bus.fallback_profile_capture_dispatch_running = true; g.bus.manual_write_in_progress = true; const FinalGate r = final_gate_decide(g, ecco_fbcap::ProbeResults{ecco_fbcap::PROBE_ABSENT, ecco_fbcap::PROBE_CLEAR, ecco_fbcap::PROBE_ABSENT}); return r.gr.obl; }()), "FB-B2 text: final_gate_decide [scenario 22 + own holds, probes all clear]: obl");
static_assert(([]{ GateInputs g = fx_gate(22); g.bus.fallback_profile_op_in_progress = true; g.bus.fallback_profile_capture_dispatch_running = true; g.bus.manual_write_in_progress = true; return ecco_fbcap::gate_decide(g, ecco_fbcap::ProbeResults{}).code; }()) == 3, "FB-B2 value: gate_decide WITHOUT the masking [scenario 22 + own holds]: code (the SAVE itself would be refused as in flight)");
static_assert(([]{ GateInputs g = fx_gate(23); g.bus.fallback_profile_op_in_progress = true; g.bus.fallback_profile_capture_dispatch_running = true; g.bus.manual_write_in_progress = true; const FinalGate r = final_gate_decide(g, ecco_fbcap::ProbeResults{}); return (uint64_t) r.gr.code | ((uint64_t) r.gr.slot << 8) | ((uint64_t) ((r.gr.probe_fp ? 4 : 0) + (r.gr.probe_dump ? 2 : 0) + (r.gr.probe_r244 ? 1 : 0)) << 16) | ((uint64_t) r.gr.latch << 24); }()) == 524034, "FB-B2 value: final_gate_decide [scenario 23 + own holds, probes none]: code | slot | probes | latch");
static_assert(text_is("", []{ GateInputs g = fx_gate(23); g.bus.fallback_profile_op_in_progress = true; g.bus.fallback_profile_capture_dispatch_running = true; g.bus.manual_write_in_progress = true; const FinalGate r = final_gate_decide(g, ecco_fbcap::ProbeResults{}); return r.text; }()), "FB-B2 text: final_gate_decide [scenario 23 + own holds, probes none]: text");
static_assert(text_is("FP:NP,DP:NP,R4:NP,MT:CN,FS:CM,BUS:OK", []{ GateInputs g = fx_gate(23); g.bus.fallback_profile_op_in_progress = true; g.bus.fallback_profile_capture_dispatch_running = true; g.bus.manual_write_in_progress = true; const FinalGate r = final_gate_decide(g, ecco_fbcap::ProbeResults{}); return r.gr.obl; }()), "FB-B2 text: final_gate_decide [scenario 23 + own holds, probes none]: obl");
static_assert(([]{ GateInputs g = fx_gate(23); g.bus.fallback_profile_op_in_progress = true; g.bus.fallback_profile_capture_dispatch_running = true; g.bus.manual_write_in_progress = true; const FinalGate r = final_gate_decide(g, ecco_fbcap::ProbeResults{ecco_fbcap::PROBE_ABSENT, ecco_fbcap::PROBE_CLEAR, ecco_fbcap::PROBE_ABSENT}); return (uint64_t) r.gr.code | ((uint64_t) r.gr.slot << 8) | ((uint64_t) ((r.gr.probe_fp ? 4 : 0) + (r.gr.probe_dump ? 2 : 0) + (r.gr.probe_r244 ? 1 : 0)) << 16) | ((uint64_t) r.gr.latch << 24); }()) == 65281, "FB-B2 value: final_gate_decide [scenario 23 + own holds, probes all clear]: code | slot | probes | latch");
static_assert(text_is("", []{ GateInputs g = fx_gate(23); g.bus.fallback_profile_op_in_progress = true; g.bus.fallback_profile_capture_dispatch_running = true; g.bus.manual_write_in_progress = true; const FinalGate r = final_gate_decide(g, ecco_fbcap::ProbeResults{ecco_fbcap::PROBE_ABSENT, ecco_fbcap::PROBE_CLEAR, ecco_fbcap::PROBE_ABSENT}); return r.text; }()), "FB-B2 text: final_gate_decide [scenario 23 + own holds, probes all clear]: text");
static_assert(text_is("FP:CA,DP:CM,R4:CA,MT:CN,FS:CM,BUS:OK", []{ GateInputs g = fx_gate(23); g.bus.fallback_profile_op_in_progress = true; g.bus.fallback_profile_capture_dispatch_running = true; g.bus.manual_write_in_progress = true; const FinalGate r = final_gate_decide(g, ecco_fbcap::ProbeResults{ecco_fbcap::PROBE_ABSENT, ecco_fbcap::PROBE_CLEAR, ecco_fbcap::PROBE_ABSENT}); return r.gr.obl; }()), "FB-B2 text: final_gate_decide [scenario 23 + own holds, probes all clear]: obl");
static_assert(([]{ GateInputs g = fx_gate(23); g.bus.fallback_profile_op_in_progress = true; g.bus.fallback_profile_capture_dispatch_running = true; g.bus.manual_write_in_progress = true; return ecco_fbcap::gate_decide(g, ecco_fbcap::ProbeResults{}).code; }()) == 3, "FB-B2 value: gate_decide WITHOUT the masking [scenario 23 + own holds]: code (the SAVE itself would be refused as in flight)");
static_assert(([]{ GateInputs g = fx_gate(24); g.bus.fallback_profile_op_in_progress = true; g.bus.fallback_profile_capture_dispatch_running = true; g.bus.manual_write_in_progress = true; const FinalGate r = final_gate_decide(g, ecco_fbcap::ProbeResults{}); return (uint64_t) r.gr.code | ((uint64_t) r.gr.slot << 8) | ((uint64_t) ((r.gr.probe_fp ? 4 : 0) + (r.gr.probe_dump ? 2 : 0) + (r.gr.probe_r244 ? 1 : 0)) << 16) | ((uint64_t) r.gr.latch << 24); }()) == 6, "FB-B2 value: final_gate_decide [scenario 24 + own holds, probes none]: code | slot | probes | latch");
static_assert(text_is("SAVE REFUSED - another inverter transaction is in progress (Dump to Grid); try again shortly", []{ GateInputs g = fx_gate(24); g.bus.fallback_profile_op_in_progress = true; g.bus.fallback_profile_capture_dispatch_running = true; g.bus.manual_write_in_progress = true; const FinalGate r = final_gate_decide(g, ecco_fbcap::ProbeResults{}); return r.text; }()), "FB-B2 text: final_gate_decide [scenario 24 + own holds, probes none]: text");
static_assert(text_is("FP:NP,DP:LK,R4:NP,MT:NP,FS:CA,BUS:BY", []{ GateInputs g = fx_gate(24); g.bus.fallback_profile_op_in_progress = true; g.bus.fallback_profile_capture_dispatch_running = true; g.bus.manual_write_in_progress = true; const FinalGate r = final_gate_decide(g, ecco_fbcap::ProbeResults{}); return r.gr.obl; }()), "FB-B2 text: final_gate_decide [scenario 24 + own holds, probes none]: obl");
static_assert(([]{ GateInputs g = fx_gate(24); g.bus.fallback_profile_op_in_progress = true; g.bus.fallback_profile_capture_dispatch_running = true; g.bus.manual_write_in_progress = true; const FinalGate r = final_gate_decide(g, ecco_fbcap::ProbeResults{ecco_fbcap::PROBE_ABSENT, ecco_fbcap::PROBE_CLEAR, ecco_fbcap::PROBE_ABSENT}); return (uint64_t) r.gr.code | ((uint64_t) r.gr.slot << 8) | ((uint64_t) ((r.gr.probe_fp ? 4 : 0) + (r.gr.probe_dump ? 2 : 0) + (r.gr.probe_r244 ? 1 : 0)) << 16) | ((uint64_t) r.gr.latch << 24); }()) == 6, "FB-B2 value: final_gate_decide [scenario 24 + own holds, probes all clear]: code | slot | probes | latch");
static_assert(text_is("SAVE REFUSED - another inverter transaction is in progress (Dump to Grid); try again shortly", []{ GateInputs g = fx_gate(24); g.bus.fallback_profile_op_in_progress = true; g.bus.fallback_profile_capture_dispatch_running = true; g.bus.manual_write_in_progress = true; const FinalGate r = final_gate_decide(g, ecco_fbcap::ProbeResults{ecco_fbcap::PROBE_ABSENT, ecco_fbcap::PROBE_CLEAR, ecco_fbcap::PROBE_ABSENT}); return r.text; }()), "FB-B2 text: final_gate_decide [scenario 24 + own holds, probes all clear]: text");
static_assert(text_is("FP:CA,DP:LK,R4:CA,MT:NP,FS:CA,BUS:BY", []{ GateInputs g = fx_gate(24); g.bus.fallback_profile_op_in_progress = true; g.bus.fallback_profile_capture_dispatch_running = true; g.bus.manual_write_in_progress = true; const FinalGate r = final_gate_decide(g, ecco_fbcap::ProbeResults{ecco_fbcap::PROBE_ABSENT, ecco_fbcap::PROBE_CLEAR, ecco_fbcap::PROBE_ABSENT}); return r.gr.obl; }()), "FB-B2 text: final_gate_decide [scenario 24 + own holds, probes all clear]: obl");
static_assert(([]{ GateInputs g = fx_gate(24); g.bus.fallback_profile_op_in_progress = true; g.bus.fallback_profile_capture_dispatch_running = true; g.bus.manual_write_in_progress = true; return ecco_fbcap::gate_decide(g, ecco_fbcap::ProbeResults{}).code; }()) == 3, "FB-B2 value: gate_decide WITHOUT the masking [scenario 24 + own holds]: code (the SAVE itself would be refused as in flight)");
static_assert(([]{ GateInputs g = fx_gate(25); g.bus.fallback_profile_op_in_progress = true; g.bus.fallback_profile_capture_dispatch_running = true; g.bus.manual_write_in_progress = true; const FinalGate r = final_gate_decide(g, ecco_fbcap::ProbeResults{}); return (uint64_t) r.gr.code | ((uint64_t) r.gr.slot << 8) | ((uint64_t) ((r.gr.probe_fp ? 4 : 0) + (r.gr.probe_dump ? 2 : 0) + (r.gr.probe_r244 ? 1 : 0)) << 16) | ((uint64_t) r.gr.latch << 24); }()) == 6, "FB-B2 value: final_gate_decide [scenario 25 + own holds, probes none]: code | slot | probes | latch");
static_assert(text_is("SAVE REFUSED - another inverter transaction is in progress (Free Power); try again shortly", []{ GateInputs g = fx_gate(25); g.bus.fallback_profile_op_in_progress = true; g.bus.fallback_profile_capture_dispatch_running = true; g.bus.manual_write_in_progress = true; const FinalGate r = final_gate_decide(g, ecco_fbcap::ProbeResults{}); return r.text; }()), "FB-B2 text: final_gate_decide [scenario 25 + own holds, probes none]: text");
static_assert(text_is("FP:EN,DP:NP,R4:NP,MT:NP,FS:CA,BUS:BY", []{ GateInputs g = fx_gate(25); g.bus.fallback_profile_op_in_progress = true; g.bus.fallback_profile_capture_dispatch_running = true; g.bus.manual_write_in_progress = true; const FinalGate r = final_gate_decide(g, ecco_fbcap::ProbeResults{}); return r.gr.obl; }()), "FB-B2 text: final_gate_decide [scenario 25 + own holds, probes none]: obl");
static_assert(([]{ GateInputs g = fx_gate(25); g.bus.fallback_profile_op_in_progress = true; g.bus.fallback_profile_capture_dispatch_running = true; g.bus.manual_write_in_progress = true; const FinalGate r = final_gate_decide(g, ecco_fbcap::ProbeResults{ecco_fbcap::PROBE_ABSENT, ecco_fbcap::PROBE_CLEAR, ecco_fbcap::PROBE_ABSENT}); return (uint64_t) r.gr.code | ((uint64_t) r.gr.slot << 8) | ((uint64_t) ((r.gr.probe_fp ? 4 : 0) + (r.gr.probe_dump ? 2 : 0) + (r.gr.probe_r244 ? 1 : 0)) << 16) | ((uint64_t) r.gr.latch << 24); }()) == 6, "FB-B2 value: final_gate_decide [scenario 25 + own holds, probes all clear]: code | slot | probes | latch");
static_assert(text_is("SAVE REFUSED - another inverter transaction is in progress (Free Power); try again shortly", []{ GateInputs g = fx_gate(25); g.bus.fallback_profile_op_in_progress = true; g.bus.fallback_profile_capture_dispatch_running = true; g.bus.manual_write_in_progress = true; const FinalGate r = final_gate_decide(g, ecco_fbcap::ProbeResults{ecco_fbcap::PROBE_ABSENT, ecco_fbcap::PROBE_CLEAR, ecco_fbcap::PROBE_ABSENT}); return r.text; }()), "FB-B2 text: final_gate_decide [scenario 25 + own holds, probes all clear]: text");
static_assert(text_is("FP:EN,DP:CM,R4:CA,MT:NP,FS:CA,BUS:BY", []{ GateInputs g = fx_gate(25); g.bus.fallback_profile_op_in_progress = true; g.bus.fallback_profile_capture_dispatch_running = true; g.bus.manual_write_in_progress = true; const FinalGate r = final_gate_decide(g, ecco_fbcap::ProbeResults{ecco_fbcap::PROBE_ABSENT, ecco_fbcap::PROBE_CLEAR, ecco_fbcap::PROBE_ABSENT}); return r.gr.obl; }()), "FB-B2 text: final_gate_decide [scenario 25 + own holds, probes all clear]: obl");
static_assert(([]{ GateInputs g = fx_gate(25); g.bus.fallback_profile_op_in_progress = true; g.bus.fallback_profile_capture_dispatch_running = true; g.bus.manual_write_in_progress = true; return ecco_fbcap::gate_decide(g, ecco_fbcap::ProbeResults{}).code; }()) == 3, "FB-B2 value: gate_decide WITHOUT the masking [scenario 25 + own holds]: code (the SAVE itself would be refused as in flight)");
static_assert(([]{ GateInputs g = fx_gate(26); g.bus.fallback_profile_op_in_progress = true; g.bus.fallback_profile_capture_dispatch_running = true; g.bus.manual_write_in_progress = true; const FinalGate r = final_gate_decide(g, ecco_fbcap::ProbeResults{}); return (uint64_t) r.gr.code | ((uint64_t) r.gr.slot << 8) | ((uint64_t) ((r.gr.probe_fp ? 4 : 0) + (r.gr.probe_dump ? 2 : 0) + (r.gr.probe_r244 ? 1 : 0)) << 16) | ((uint64_t) r.gr.latch << 24); }()) == 520, "FB-B2 value: final_gate_decide [scenario 26 + own holds, probes none]: code | slot | probes | latch");
static_assert(text_is("SAVE REFUSED - Free Power is active; live settings are a temporary overlay - end it first", []{ GateInputs g = fx_gate(26); g.bus.fallback_profile_op_in_progress = true; g.bus.fallback_profile_capture_dispatch_running = true; g.bus.manual_write_in_progress = true; const FinalGate r = final_gate_decide(g, ecco_fbcap::ProbeResults{}); return r.text; }()), "FB-B2 text: final_gate_decide [scenario 26 + own holds, probes none]: text");
static_assert(text_is("FP:AC,DP:NP,R4:NP,MT:CN,FS:CA,BUS:OK", []{ GateInputs g = fx_gate(26); g.bus.fallback_profile_op_in_progress = true; g.bus.fallback_profile_capture_dispatch_running = true; g.bus.manual_write_in_progress = true; const FinalGate r = final_gate_decide(g, ecco_fbcap::ProbeResults{}); return r.gr.obl; }()), "FB-B2 text: final_gate_decide [scenario 26 + own holds, probes none]: obl");
static_assert(([]{ GateInputs g = fx_gate(26); g.bus.fallback_profile_op_in_progress = true; g.bus.fallback_profile_capture_dispatch_running = true; g.bus.manual_write_in_progress = true; const FinalGate r = final_gate_decide(g, ecco_fbcap::ProbeResults{ecco_fbcap::PROBE_ABSENT, ecco_fbcap::PROBE_CLEAR, ecco_fbcap::PROBE_ABSENT}); return (uint64_t) r.gr.code | ((uint64_t) r.gr.slot << 8) | ((uint64_t) ((r.gr.probe_fp ? 4 : 0) + (r.gr.probe_dump ? 2 : 0) + (r.gr.probe_r244 ? 1 : 0)) << 16) | ((uint64_t) r.gr.latch << 24); }()) == 520, "FB-B2 value: final_gate_decide [scenario 26 + own holds, probes all clear]: code | slot | probes | latch");
static_assert(text_is("SAVE REFUSED - Free Power is active; live settings are a temporary overlay - end it first", []{ GateInputs g = fx_gate(26); g.bus.fallback_profile_op_in_progress = true; g.bus.fallback_profile_capture_dispatch_running = true; g.bus.manual_write_in_progress = true; const FinalGate r = final_gate_decide(g, ecco_fbcap::ProbeResults{ecco_fbcap::PROBE_ABSENT, ecco_fbcap::PROBE_CLEAR, ecco_fbcap::PROBE_ABSENT}); return r.text; }()), "FB-B2 text: final_gate_decide [scenario 26 + own holds, probes all clear]: text");
static_assert(text_is("FP:AC,DP:CM,R4:CA,MT:CN,FS:CA,BUS:OK", []{ GateInputs g = fx_gate(26); g.bus.fallback_profile_op_in_progress = true; g.bus.fallback_profile_capture_dispatch_running = true; g.bus.manual_write_in_progress = true; const FinalGate r = final_gate_decide(g, ecco_fbcap::ProbeResults{ecco_fbcap::PROBE_ABSENT, ecco_fbcap::PROBE_CLEAR, ecco_fbcap::PROBE_ABSENT}); return r.gr.obl; }()), "FB-B2 text: final_gate_decide [scenario 26 + own holds, probes all clear]: obl");
static_assert(([]{ GateInputs g = fx_gate(26); g.bus.fallback_profile_op_in_progress = true; g.bus.fallback_profile_capture_dispatch_running = true; g.bus.manual_write_in_progress = true; return ecco_fbcap::gate_decide(g, ecco_fbcap::ProbeResults{}).code; }()) == 3, "FB-B2 value: gate_decide WITHOUT the masking [scenario 26 + own holds]: code (the SAVE itself would be refused as in flight)");
static_assert(([]{ GateInputs g = fx_gate(27); g.bus.fallback_profile_op_in_progress = true; g.bus.fallback_profile_capture_dispatch_running = true; g.bus.manual_write_in_progress = true; const FinalGate r = final_gate_decide(g, ecco_fbcap::ProbeResults{}); return (uint64_t) r.gr.code | ((uint64_t) r.gr.slot << 8) | ((uint64_t) ((r.gr.probe_fp ? 4 : 0) + (r.gr.probe_dump ? 2 : 0) + (r.gr.probe_r244 ? 1 : 0)) << 16) | ((uint64_t) r.gr.latch << 24); }()) == 777, "FB-B2 value: final_gate_decide [scenario 27 + own holds, probes none]: code | slot | probes | latch");
static_assert(text_is("SAVE REFUSED - Dump to Grid is active; live settings are a temporary overlay - end it first", []{ GateInputs g = fx_gate(27); g.bus.fallback_profile_op_in_progress = true; g.bus.fallback_profile_capture_dispatch_running = true; g.bus.manual_write_in_progress = true; const FinalGate r = final_gate_decide(g, ecco_fbcap::ProbeResults{}); return r.text; }()), "FB-B2 text: final_gate_decide [scenario 27 + own holds, probes none]: text");
static_assert(text_is("FP:NP,DP:AC,R4:NP,MT:CN,FS:CA,BUS:OK", []{ GateInputs g = fx_gate(27); g.bus.fallback_profile_op_in_progress = true; g.bus.fallback_profile_capture_dispatch_running = true; g.bus.manual_write_in_progress = true; const FinalGate r = final_gate_decide(g, ecco_fbcap::ProbeResults{}); return r.gr.obl; }()), "FB-B2 text: final_gate_decide [scenario 27 + own holds, probes none]: obl");
static_assert(([]{ GateInputs g = fx_gate(27); g.bus.fallback_profile_op_in_progress = true; g.bus.fallback_profile_capture_dispatch_running = true; g.bus.manual_write_in_progress = true; const FinalGate r = final_gate_decide(g, ecco_fbcap::ProbeResults{ecco_fbcap::PROBE_ABSENT, ecco_fbcap::PROBE_CLEAR, ecco_fbcap::PROBE_ABSENT}); return (uint64_t) r.gr.code | ((uint64_t) r.gr.slot << 8) | ((uint64_t) ((r.gr.probe_fp ? 4 : 0) + (r.gr.probe_dump ? 2 : 0) + (r.gr.probe_r244 ? 1 : 0)) << 16) | ((uint64_t) r.gr.latch << 24); }()) == 777, "FB-B2 value: final_gate_decide [scenario 27 + own holds, probes all clear]: code | slot | probes | latch");
static_assert(text_is("SAVE REFUSED - Dump to Grid is active; live settings are a temporary overlay - end it first", []{ GateInputs g = fx_gate(27); g.bus.fallback_profile_op_in_progress = true; g.bus.fallback_profile_capture_dispatch_running = true; g.bus.manual_write_in_progress = true; const FinalGate r = final_gate_decide(g, ecco_fbcap::ProbeResults{ecco_fbcap::PROBE_ABSENT, ecco_fbcap::PROBE_CLEAR, ecco_fbcap::PROBE_ABSENT}); return r.text; }()), "FB-B2 text: final_gate_decide [scenario 27 + own holds, probes all clear]: text");
static_assert(text_is("FP:CA,DP:AC,R4:CA,MT:CN,FS:CA,BUS:OK", []{ GateInputs g = fx_gate(27); g.bus.fallback_profile_op_in_progress = true; g.bus.fallback_profile_capture_dispatch_running = true; g.bus.manual_write_in_progress = true; const FinalGate r = final_gate_decide(g, ecco_fbcap::ProbeResults{ecco_fbcap::PROBE_ABSENT, ecco_fbcap::PROBE_CLEAR, ecco_fbcap::PROBE_ABSENT}); return r.gr.obl; }()), "FB-B2 text: final_gate_decide [scenario 27 + own holds, probes all clear]: obl");
static_assert(([]{ GateInputs g = fx_gate(27); g.bus.fallback_profile_op_in_progress = true; g.bus.fallback_profile_capture_dispatch_running = true; g.bus.manual_write_in_progress = true; return ecco_fbcap::gate_decide(g, ecco_fbcap::ProbeResults{}).code; }()) == 3, "FB-B2 value: gate_decide WITHOUT the masking [scenario 27 + own holds]: code (the SAVE itself would be refused as in flight)");
static_assert(([]{ GateInputs g = fx_gate(0); g.bus.fallback_profile_op_in_progress = true; g.bus.fallback_profile_capture_dispatch_running = true; g.bus.manual_write_in_progress = true; const FinalGate r = final_gate_decide(g, ecco_fbcap::ProbeResults{ecco_fbcap::PROBE_UNREADABLE, ecco_fbcap::PROBE_CLEAR, ecco_fbcap::PROBE_ABSENT}); return (uint64_t) r.gr.code | ((uint64_t) r.gr.slot << 8) | ((uint64_t) ((r.gr.probe_fp ? 4 : 0) + (r.gr.probe_dump ? 2 : 0) + (r.gr.probe_r244 ? 1 : 0)) << 16) | ((uint64_t) r.gr.latch << 24); }()) == 16777736, "FB-B2 value: final_gate_decide [clear + own holds, probes FP unreadable]: code | slot | probes | latch");
static_assert(text_is("SAVE REFUSED - Free Power recovery marker became unreadable at runtime; saving blocked until reboot. After reboot it may read absent: verify live settings first; do not erase NVS", []{ GateInputs g = fx_gate(0); g.bus.fallback_profile_op_in_progress = true; g.bus.fallback_profile_capture_dispatch_running = true; g.bus.manual_write_in_progress = true; const FinalGate r = final_gate_decide(g, ecco_fbcap::ProbeResults{ecco_fbcap::PROBE_UNREADABLE, ecco_fbcap::PROBE_CLEAR, ecco_fbcap::PROBE_ABSENT}); return r.text; }()), "FB-B2 text: final_gate_decide [clear + own holds, probes FP unreadable]: text");
static_assert(([]{ GateInputs g = fx_gate(0); g.bus.fallback_profile_op_in_progress = true; g.bus.fallback_profile_capture_dispatch_running = true; g.bus.manual_write_in_progress = true; const FinalGate r = final_gate_decide(g, ecco_fbcap::ProbeResults{ecco_fbcap::PROBE_ABSENT, ecco_fbcap::PROBE_MALFORMED, ecco_fbcap::PROBE_ABSENT}); return (uint64_t) r.gr.code | ((uint64_t) r.gr.slot << 8) | ((uint64_t) ((r.gr.probe_fp ? 4 : 0) + (r.gr.probe_dump ? 2 : 0) + (r.gr.probe_r244 ? 1 : 0)) << 16) | ((uint64_t) r.gr.latch << 24); }()) == 536871689, "FB-B2 value: final_gate_decide [clear + own holds, probes Dump malformed]: code | slot | probes | latch");
static_assert(text_is("SAVE REFUSED - Dump to Grid recovery marker is malformed (found at runtime); saving blocked until reboot, which re-derives it as a hard lockout", []{ GateInputs g = fx_gate(0); g.bus.fallback_profile_op_in_progress = true; g.bus.fallback_profile_capture_dispatch_running = true; g.bus.manual_write_in_progress = true; const FinalGate r = final_gate_decide(g, ecco_fbcap::ProbeResults{ecco_fbcap::PROBE_ABSENT, ecco_fbcap::PROBE_MALFORMED, ecco_fbcap::PROBE_ABSENT}); return r.text; }()), "FB-B2 text: final_gate_decide [clear + own holds, probes Dump malformed]: text");
static_assert(([]{ GateInputs g = fx_gate(0); g.bus.fallback_profile_op_in_progress = true; g.bus.fallback_profile_capture_dispatch_running = true; g.bus.manual_write_in_progress = true; const FinalGate r = final_gate_decide(g, ecco_fbcap::ProbeResults{ecco_fbcap::PROBE_ABSENT, ecco_fbcap::PROBE_CLEAR, ecco_fbcap::PROBE_RESTORE_REQUIRED}); return (uint64_t) r.gr.code | ((uint64_t) r.gr.slot << 8) | ((uint64_t) ((r.gr.probe_fp ? 4 : 0) + (r.gr.probe_dump ? 2 : 0) + (r.gr.probe_r244 ? 1 : 0)) << 16) | ((uint64_t) r.gr.latch << 24); }()) == 0x30000040AULL, "FB-B2 value: final_gate_decide [clear + own holds, probes R244 ghost restore required]: code | slot | probes | latch");
static_assert(text_is("SAVE REFUSED - Register 244 test stored marker says RESTORE_REQUIRED but memory says clear; saving blocked until reboot, which re-derives it (the domain may then restore its saved original)", []{ GateInputs g = fx_gate(0); g.bus.fallback_profile_op_in_progress = true; g.bus.fallback_profile_capture_dispatch_running = true; g.bus.manual_write_in_progress = true; const FinalGate r = final_gate_decide(g, ecco_fbcap::ProbeResults{ecco_fbcap::PROBE_ABSENT, ecco_fbcap::PROBE_CLEAR, ecco_fbcap::PROBE_RESTORE_REQUIRED}); return r.text; }()), "FB-B2 text: final_gate_decide [clear + own holds, probes R244 ghost restore required]: text");
static_assert(([]{ GateInputs g = fx_gate(16); g.bus.fallback_profile_op_in_progress = true; g.bus.fallback_profile_capture_dispatch_running = true; g.bus.manual_write_in_progress = true; const FinalGate r = final_gate_decide(g, ecco_fbcap::ProbeResults{ecco_fbcap::PROBE_PENDING_CLEAR, ecco_fbcap::PROBE_CLEAR, ecco_fbcap::PROBE_CLEAR}); return r.gr.latch; }()) == 1, "FB-B2 value: final_gate_decide: a latched domain keeps its latch and is never rewritten");
static_assert(([]{ GateInputs g = fx_gate(0); g.bus.fallback_profile_op_in_progress = true; return final_gate_decide(g, ecco_fbcap::ProbeResults{}).gr.code; }()) == 2, "FB-B2 value: final_gate_decide: only fallback_profile_op_in_progress set -> code");
static_assert(([]{ GateInputs g = fx_gate(0); g.bus.fallback_profile_capture_dispatch_running = true; return final_gate_decide(g, ecco_fbcap::ProbeResults{}).gr.code; }()) == 2, "FB-B2 value: final_gate_decide: only fallback_profile_capture_dispatch_running set -> code");
static_assert(([]{ GateInputs g = fx_gate(0); g.bus.manual_write_in_progress = true; return final_gate_decide(g, ecco_fbcap::ProbeResults{}).gr.code; }()) == 2, "FB-B2 value: final_gate_decide: only manual_write_in_progress set -> code");
static_assert(([]{ GateInputs g = fx_gate(0); g.bus.correction_in_progress = true; return final_gate_decide(g, ecco_fbcap::ProbeResults{}).gr.code; }()) == 6, "FB-B2 value: final_gate_decide: only correction_in_progress set -> code");
static_assert(([]{ GateInputs g = fx_gate(0); g.bus.verification_pending = true; return final_gate_decide(g, ecco_fbcap::ProbeResults{}).gr.code; }()) == 6, "FB-B2 value: final_gate_decide: only verification_pending set -> code");
static_assert(([]{ GateInputs g = fx_gate(0); g.bus.verification_read_active = true; return final_gate_decide(g, ecco_fbcap::ProbeResults{}).gr.code; }()) == 6, "FB-B2 value: final_gate_decide: only verification_read_active set -> code");
static_assert(([]{ GateInputs g = fx_gate(0); g.bus.free_power_operation_in_progress = true; return final_gate_decide(g, ecco_fbcap::ProbeResults{}).gr.code; }()) == 6, "FB-B2 value: final_gate_decide: only free_power_operation_in_progress set -> code");
static_assert(([]{ GateInputs g = fx_gate(0); g.bus.free_power_recovery_force_in_progress = true; return final_gate_decide(g, ecco_fbcap::ProbeResults{}).gr.code; }()) == 6, "FB-B2 value: final_gate_decide: only free_power_recovery_force_in_progress set -> code");
static_assert(([]{ GateInputs g = fx_gate(0); g.bus.free_power_recovery_accept_in_progress = true; return final_gate_decide(g, ecco_fbcap::ProbeResults{}).gr.code; }()) == 6, "FB-B2 value: final_gate_decide: only free_power_recovery_accept_in_progress set -> code");
static_assert(([]{ GateInputs g = fx_gate(0); g.bus.reg244_apply_in_progress = true; return final_gate_decide(g, ecco_fbcap::ProbeResults{}).gr.code; }()) == 6, "FB-B2 value: final_gate_decide: only reg244_apply_in_progress set -> code");
static_assert(([]{ GateInputs g = fx_gate(0); g.bus.dump_operation_in_progress = true; return final_gate_decide(g, ecco_fbcap::ProbeResults{}).gr.code; }()) == 6, "FB-B2 value: final_gate_decide: only dump_operation_in_progress set -> code");
static_assert(([]{ GateInputs g = fx_gate(0); g.bus.diag_write_lock_held = true; return final_gate_decide(g, ecco_fbcap::ProbeResults{}).gr.code; }()) == 2, "FB-B2 value: final_gate_decide: only diag_write_lock_held set -> code");
static_assert(([]{ GateInputs g = fx_gate(0); g.bus.fallback_profile_op_in_progress = true; g.bus.fallback_profile_capture_dispatch_running = true; g.bus.manual_write_in_progress = true; g.free_power_write_enable = true; return final_gate_decide(g, ecco_fbcap::ProbeResults{}).gr.code; }()) == 5, "FB-B2 value: final_gate_decide: the write arm free_power_write_enable is not masked");
static_assert(([]{ GateInputs g = fx_gate(0); g.bus.fallback_profile_op_in_progress = true; g.bus.fallback_profile_capture_dispatch_running = true; g.bus.manual_write_in_progress = true; g.dump_write_enable = true; return final_gate_decide(g, ecco_fbcap::ProbeResults{}).gr.code; }()) == 5, "FB-B2 value: final_gate_decide: the write arm dump_write_enable is not masked");
static_assert(([]{ GateInputs g = fx_gate(0); g.bus.fallback_profile_op_in_progress = true; g.bus.fallback_profile_capture_dispatch_running = true; g.bus.manual_write_in_progress = true; g.manual_config_write_enable = true; return final_gate_decide(g, ecco_fbcap::ProbeResults{}).gr.code; }()) == 5, "FB-B2 value: final_gate_decide: the write arm manual_config_write_enable is not masked");
static_assert(([]{ GateInputs g = fx_gate(9); g.bus.fallback_profile_op_in_progress = true; g.bus.fallback_profile_capture_dispatch_running = true; g.bus.manual_write_in_progress = true; return final_gate_decide(g, ecco_fbcap::ProbeResults{}).gr.code; }()) == 2, "FB-B2 value: final_gate_decide: the stuck-lock diagnostic with the masked mutex is not a stuck lock (the lock is the SAVE's own)");
static_assert(([]{ GateInputs g = fx_gate(0); g.free_power_write_enable = true; g.fbs_slot = ecco_fbdurable::FBS_OBLIGATION; g.probe_latch = 0x0123; g.bus.correction_in_progress = true; g.bus.diag_write_lock_held = true; g.bus.diag_write_lock_since_ms = 77u; g.bus.now_ms = 99u; g.dump.dump_containment_state = 3; g.fp.run_start = true; g.r244.run_apply = true; g.bus.fallback_profile_op_in_progress = true; g.bus.fallback_profile_capture_dispatch_running = true; g.bus.manual_write_in_progress = true; const GateInputs m = final_phase_inputs(g); return fx_same_except_holds(m, g); }()) == 1, "FB-B2 value: final_phase_inputs: EXACTLY the three own holds are cleared (every other field of a fully populated input is untouched)");
static_assert((commit_bus_quiet(true, true, true, true, true)) == 0, "FB-B2 value: commit_bus_quiet op=True mutex=True correction=True tx_empty=True tx_blocked=True");
static_assert((commit_bus_quiet(true, true, true, true, false)) == 0, "FB-B2 value: commit_bus_quiet op=True mutex=True correction=True tx_empty=True tx_blocked=False");
static_assert((commit_bus_quiet(true, true, true, false, true)) == 0, "FB-B2 value: commit_bus_quiet op=True mutex=True correction=True tx_empty=False tx_blocked=True");
static_assert((commit_bus_quiet(true, true, true, false, false)) == 0, "FB-B2 value: commit_bus_quiet op=True mutex=True correction=True tx_empty=False tx_blocked=False");
static_assert((commit_bus_quiet(true, true, false, true, true)) == 0, "FB-B2 value: commit_bus_quiet op=True mutex=True correction=False tx_empty=True tx_blocked=True");
static_assert((commit_bus_quiet(true, true, false, true, false)) == 1, "FB-B2 value: commit_bus_quiet op=True mutex=True correction=False tx_empty=True tx_blocked=False");
static_assert((commit_bus_quiet(true, true, false, false, true)) == 0, "FB-B2 value: commit_bus_quiet op=True mutex=True correction=False tx_empty=False tx_blocked=True");
static_assert((commit_bus_quiet(true, true, false, false, false)) == 0, "FB-B2 value: commit_bus_quiet op=True mutex=True correction=False tx_empty=False tx_blocked=False");
static_assert((commit_bus_quiet(true, false, true, true, true)) == 0, "FB-B2 value: commit_bus_quiet op=True mutex=False correction=True tx_empty=True tx_blocked=True");
static_assert((commit_bus_quiet(true, false, true, true, false)) == 0, "FB-B2 value: commit_bus_quiet op=True mutex=False correction=True tx_empty=True tx_blocked=False");
static_assert((commit_bus_quiet(true, false, true, false, true)) == 0, "FB-B2 value: commit_bus_quiet op=True mutex=False correction=True tx_empty=False tx_blocked=True");
static_assert((commit_bus_quiet(true, false, true, false, false)) == 0, "FB-B2 value: commit_bus_quiet op=True mutex=False correction=True tx_empty=False tx_blocked=False");
static_assert((commit_bus_quiet(true, false, false, true, true)) == 0, "FB-B2 value: commit_bus_quiet op=True mutex=False correction=False tx_empty=True tx_blocked=True");
static_assert((commit_bus_quiet(true, false, false, true, false)) == 0, "FB-B2 value: commit_bus_quiet op=True mutex=False correction=False tx_empty=True tx_blocked=False");
static_assert((commit_bus_quiet(true, false, false, false, true)) == 0, "FB-B2 value: commit_bus_quiet op=True mutex=False correction=False tx_empty=False tx_blocked=True");
static_assert((commit_bus_quiet(true, false, false, false, false)) == 0, "FB-B2 value: commit_bus_quiet op=True mutex=False correction=False tx_empty=False tx_blocked=False");
static_assert((commit_bus_quiet(false, true, true, true, true)) == 0, "FB-B2 value: commit_bus_quiet op=False mutex=True correction=True tx_empty=True tx_blocked=True");
static_assert((commit_bus_quiet(false, true, true, true, false)) == 0, "FB-B2 value: commit_bus_quiet op=False mutex=True correction=True tx_empty=True tx_blocked=False");
static_assert((commit_bus_quiet(false, true, true, false, true)) == 0, "FB-B2 value: commit_bus_quiet op=False mutex=True correction=True tx_empty=False tx_blocked=True");
static_assert((commit_bus_quiet(false, true, true, false, false)) == 0, "FB-B2 value: commit_bus_quiet op=False mutex=True correction=True tx_empty=False tx_blocked=False");
static_assert((commit_bus_quiet(false, true, false, true, true)) == 0, "FB-B2 value: commit_bus_quiet op=False mutex=True correction=False tx_empty=True tx_blocked=True");
static_assert((commit_bus_quiet(false, true, false, true, false)) == 0, "FB-B2 value: commit_bus_quiet op=False mutex=True correction=False tx_empty=True tx_blocked=False");
static_assert((commit_bus_quiet(false, true, false, false, true)) == 0, "FB-B2 value: commit_bus_quiet op=False mutex=True correction=False tx_empty=False tx_blocked=True");
static_assert((commit_bus_quiet(false, true, false, false, false)) == 0, "FB-B2 value: commit_bus_quiet op=False mutex=True correction=False tx_empty=False tx_blocked=False");
static_assert((commit_bus_quiet(false, false, true, true, true)) == 0, "FB-B2 value: commit_bus_quiet op=False mutex=False correction=True tx_empty=True tx_blocked=True");
static_assert((commit_bus_quiet(false, false, true, true, false)) == 0, "FB-B2 value: commit_bus_quiet op=False mutex=False correction=True tx_empty=True tx_blocked=False");
static_assert((commit_bus_quiet(false, false, true, false, true)) == 0, "FB-B2 value: commit_bus_quiet op=False mutex=False correction=True tx_empty=False tx_blocked=True");
static_assert((commit_bus_quiet(false, false, true, false, false)) == 0, "FB-B2 value: commit_bus_quiet op=False mutex=False correction=True tx_empty=False tx_blocked=False");
static_assert((commit_bus_quiet(false, false, false, true, true)) == 0, "FB-B2 value: commit_bus_quiet op=False mutex=False correction=False tx_empty=True tx_blocked=True");
static_assert((commit_bus_quiet(false, false, false, true, false)) == 0, "FB-B2 value: commit_bus_quiet op=False mutex=False correction=False tx_empty=True tx_blocked=False");
static_assert((commit_bus_quiet(false, false, false, false, true)) == 0, "FB-B2 value: commit_bus_quiet op=False mutex=False correction=False tx_empty=False tx_blocked=True");
static_assert((commit_bus_quiet(false, false, false, false, false)) == 0, "FB-B2 value: commit_bus_quiet op=False mutex=False correction=False tx_empty=False tx_blocked=False");
static_assert((invalidate_bus_idle(fx_bus(0), true, false)) == 1, "FB-B2 value: invalidate_bus_idle bus scenario 0 tx 0");
static_assert((invalidate_bus_idle(fx_bus(0), false, false)) == 0, "FB-B2 value: invalidate_bus_idle bus scenario 0 tx 1");
static_assert((invalidate_bus_idle(fx_bus(0), true, true)) == 0, "FB-B2 value: invalidate_bus_idle bus scenario 0 tx 2");
static_assert((invalidate_bus_idle(fx_bus(1), true, false)) == 0, "FB-B2 value: invalidate_bus_idle bus scenario 1 tx 0");
static_assert((invalidate_bus_idle(fx_bus(1), false, false)) == 0, "FB-B2 value: invalidate_bus_idle bus scenario 1 tx 1");
static_assert((invalidate_bus_idle(fx_bus(1), true, true)) == 0, "FB-B2 value: invalidate_bus_idle bus scenario 1 tx 2");
static_assert((invalidate_bus_idle(fx_bus(2), true, false)) == 0, "FB-B2 value: invalidate_bus_idle bus scenario 2 tx 0");
static_assert((invalidate_bus_idle(fx_bus(2), false, false)) == 0, "FB-B2 value: invalidate_bus_idle bus scenario 2 tx 1");
static_assert((invalidate_bus_idle(fx_bus(2), true, true)) == 0, "FB-B2 value: invalidate_bus_idle bus scenario 2 tx 2");
static_assert((invalidate_bus_idle(fx_bus(3), true, false)) == 0, "FB-B2 value: invalidate_bus_idle bus scenario 3 tx 0");
static_assert((invalidate_bus_idle(fx_bus(3), false, false)) == 0, "FB-B2 value: invalidate_bus_idle bus scenario 3 tx 1");
static_assert((invalidate_bus_idle(fx_bus(3), true, true)) == 0, "FB-B2 value: invalidate_bus_idle bus scenario 3 tx 2");
static_assert((invalidate_bus_idle(fx_bus(4), true, false)) == 0, "FB-B2 value: invalidate_bus_idle bus scenario 4 tx 0");
static_assert((invalidate_bus_idle(fx_bus(4), false, false)) == 0, "FB-B2 value: invalidate_bus_idle bus scenario 4 tx 1");
static_assert((invalidate_bus_idle(fx_bus(4), true, true)) == 0, "FB-B2 value: invalidate_bus_idle bus scenario 4 tx 2");
static_assert((invalidate_bus_idle(fx_bus(5), true, false)) == 0, "FB-B2 value: invalidate_bus_idle bus scenario 5 tx 0");
static_assert((invalidate_bus_idle(fx_bus(5), false, false)) == 0, "FB-B2 value: invalidate_bus_idle bus scenario 5 tx 1");
static_assert((invalidate_bus_idle(fx_bus(5), true, true)) == 0, "FB-B2 value: invalidate_bus_idle bus scenario 5 tx 2");
static_assert((invalidate_bus_idle(fx_bus(6), true, false)) == 0, "FB-B2 value: invalidate_bus_idle bus scenario 6 tx 0");
static_assert((invalidate_bus_idle(fx_bus(6), false, false)) == 0, "FB-B2 value: invalidate_bus_idle bus scenario 6 tx 1");
static_assert((invalidate_bus_idle(fx_bus(6), true, true)) == 0, "FB-B2 value: invalidate_bus_idle bus scenario 6 tx 2");
static_assert((invalidate_bus_idle(fx_bus(7), true, false)) == 0, "FB-B2 value: invalidate_bus_idle bus scenario 7 tx 0");
static_assert((invalidate_bus_idle(fx_bus(7), false, false)) == 0, "FB-B2 value: invalidate_bus_idle bus scenario 7 tx 1");
static_assert((invalidate_bus_idle(fx_bus(7), true, true)) == 0, "FB-B2 value: invalidate_bus_idle bus scenario 7 tx 2");
static_assert((invalidate_bus_idle(fx_bus(8), true, false)) == 0, "FB-B2 value: invalidate_bus_idle bus scenario 8 tx 0");
static_assert((invalidate_bus_idle(fx_bus(8), false, false)) == 0, "FB-B2 value: invalidate_bus_idle bus scenario 8 tx 1");
static_assert((invalidate_bus_idle(fx_bus(8), true, true)) == 0, "FB-B2 value: invalidate_bus_idle bus scenario 8 tx 2");
static_assert((invalidate_bus_idle(fx_bus(9), true, false)) == 0, "FB-B2 value: invalidate_bus_idle bus scenario 9 tx 0");
static_assert((invalidate_bus_idle(fx_bus(9), false, false)) == 0, "FB-B2 value: invalidate_bus_idle bus scenario 9 tx 1");
static_assert((invalidate_bus_idle(fx_bus(9), true, true)) == 0, "FB-B2 value: invalidate_bus_idle bus scenario 9 tx 2");
static_assert((invalidate_bus_idle(fx_bus(10), true, false)) == 0, "FB-B2 value: invalidate_bus_idle bus scenario 10 tx 0");
static_assert((invalidate_bus_idle(fx_bus(10), false, false)) == 0, "FB-B2 value: invalidate_bus_idle bus scenario 10 tx 1");
static_assert((invalidate_bus_idle(fx_bus(10), true, true)) == 0, "FB-B2 value: invalidate_bus_idle bus scenario 10 tx 2");
static_assert((invalidate_bus_idle(fx_bus(11), true, false)) == 0, "FB-B2 value: invalidate_bus_idle bus scenario 11 tx 0");
static_assert((invalidate_bus_idle(fx_bus(11), false, false)) == 0, "FB-B2 value: invalidate_bus_idle bus scenario 11 tx 1");
static_assert((invalidate_bus_idle(fx_bus(11), true, true)) == 0, "FB-B2 value: invalidate_bus_idle bus scenario 11 tx 2");
static_assert((clock_trusted_for_save(true, 1790000000u)) == 1, "FB-B2 value: clock_trusted_for_save trusted=True epoch=1790000000");
static_assert((clock_trusted_for_save(true, 0u)) == 0, "FB-B2 value: clock_trusted_for_save trusted=True epoch=0");
static_assert((clock_trusted_for_save(false, 1790000000u)) == 0, "FB-B2 value: clock_trusted_for_save trusted=False epoch=1790000000");
static_assert((clock_trusted_for_save(false, 0u)) == 0, "FB-B2 value: clock_trusted_for_save trusted=False epoch=0");
static_assert((clock_trusted_for_save(true, 4294967295u)) == 1, "FB-B2 value: clock_trusted_for_save trusted=True epoch=4294967295");
static_assert((clock_trusted_for_save(true, 1u)) == 1, "FB-B2 value: clock_trusted_for_save trusted=True epoch=1");
static_assert(([]{ const Plan r = plan_save(sp_inputs(SP_CASES[0])); return (uint64_t) r.code | ((uint64_t) r.op << 8); }()) == 257, "FB-B2 value: sp row 0: code | op << 8");
static_assert(([]{ const Plan r = plan_save(sp_inputs(SP_CASES[0])); return r.generation; }()) == 1, "FB-B2 value: sp row 0: generation");
static_assert(([]{ const Plan r = plan_save(sp_inputs(SP_CASES[0])); return fx_digest(r); }()) == 0x68D497C78ABB34FCULL, "FB-B2 value: sp row 0: FNV digest of both records");
static_assert(text_is("", []{ const Plan r = plan_save(sp_inputs(SP_CASES[0])); return r.text; }()), "FB-B2 text: sp row 0: text");
static_assert(([]{ const Plan r = plan_save(sp_inputs(SP_CASES[1])); return (uint64_t) r.code | ((uint64_t) r.op << 8); }()) == 257, "FB-B2 value: sp row 1: code | op << 8");
static_assert(([]{ const Plan r = plan_save(sp_inputs(SP_CASES[1])); return r.generation; }()) == 6, "FB-B2 value: sp row 1: generation");
static_assert(([]{ const Plan r = plan_save(sp_inputs(SP_CASES[1])); return fx_digest(r); }()) == 0xE37C97D084F7FA5BULL, "FB-B2 value: sp row 1: FNV digest of both records");
static_assert(text_is("", []{ const Plan r = plan_save(sp_inputs(SP_CASES[1])); return r.text; }()), "FB-B2 text: sp row 1: text");
static_assert(([]{ const Plan r = plan_save(sp_inputs(SP_CASES[2])); return (uint64_t) r.code | ((uint64_t) r.op << 8); }()) == 257, "FB-B2 value: sp row 2: code | op << 8");
static_assert(([]{ const Plan r = plan_save(sp_inputs(SP_CASES[2])); return r.generation; }()) == 8, "FB-B2 value: sp row 2: generation");
static_assert(([]{ const Plan r = plan_save(sp_inputs(SP_CASES[2])); return fx_digest(r); }()) == 0x663BB825BF1E6FD8ULL, "FB-B2 value: sp row 2: FNV digest of both records");
static_assert(text_is("", []{ const Plan r = plan_save(sp_inputs(SP_CASES[2])); return r.text; }()), "FB-B2 text: sp row 2: text");
static_assert(([]{ const Plan r = plan_save(sp_inputs(SP_CASES[3])); return (uint64_t) r.code | ((uint64_t) r.op << 8); }()) == 257, "FB-B2 value: sp row 3: code | op << 8");
static_assert(([]{ const Plan r = plan_save(sp_inputs(SP_CASES[3])); return r.generation; }()) == 8, "FB-B2 value: sp row 3: generation");
static_assert(([]{ const Plan r = plan_save(sp_inputs(SP_CASES[3])); return fx_digest(r); }()) == 0x663BB825BF1E6FD8ULL, "FB-B2 value: sp row 3: FNV digest of both records");
static_assert(text_is("", []{ const Plan r = plan_save(sp_inputs(SP_CASES[3])); return r.text; }()), "FB-B2 text: sp row 3: text");
static_assert(([]{ const Plan r = plan_save(sp_inputs(SP_CASES[4])); return (uint64_t) r.code | ((uint64_t) r.op << 8); }()) == 257, "FB-B2 value: sp row 4: code | op << 8");
static_assert(([]{ const Plan r = plan_save(sp_inputs(SP_CASES[4])); return r.generation; }()) == 8, "FB-B2 value: sp row 4: generation");
static_assert(([]{ const Plan r = plan_save(sp_inputs(SP_CASES[4])); return fx_digest(r); }()) == 0x663BB825BF1E6FD8ULL, "FB-B2 value: sp row 4: FNV digest of both records");
static_assert(text_is("", []{ const Plan r = plan_save(sp_inputs(SP_CASES[4])); return r.text; }()), "FB-B2 text: sp row 4: text");
static_assert(([]{ const Plan r = plan_save(sp_inputs(SP_CASES[5])); return (uint64_t) r.code | ((uint64_t) r.op << 8); }()) == 257, "FB-B2 value: sp row 5: code | op << 8");
static_assert(([]{ const Plan r = plan_save(sp_inputs(SP_CASES[5])); return r.generation; }()) == 8, "FB-B2 value: sp row 5: generation");
static_assert(([]{ const Plan r = plan_save(sp_inputs(SP_CASES[5])); return fx_digest(r); }()) == 0x663BB825BF1E6FD8ULL, "FB-B2 value: sp row 5: FNV digest of both records");
static_assert(text_is("", []{ const Plan r = plan_save(sp_inputs(SP_CASES[5])); return r.text; }()), "FB-B2 text: sp row 5: text");
static_assert(([]{ const Plan r = plan_save(sp_inputs(SP_CASES[6])); return (uint64_t) r.code | ((uint64_t) r.op << 8); }()) == 257, "FB-B2 value: sp row 6: code | op << 8");
static_assert(([]{ const Plan r = plan_save(sp_inputs(SP_CASES[6])); return r.generation; }()) == 8, "FB-B2 value: sp row 6: generation");
static_assert(([]{ const Plan r = plan_save(sp_inputs(SP_CASES[6])); return fx_digest(r); }()) == 0x663BB825BF1E6FD8ULL, "FB-B2 value: sp row 6: FNV digest of both records");
static_assert(text_is("", []{ const Plan r = plan_save(sp_inputs(SP_CASES[6])); return r.text; }()), "FB-B2 text: sp row 6: text");
static_assert(([]{ const Plan r = plan_save(sp_inputs(SP_CASES[7])); return (uint64_t) r.code | ((uint64_t) r.op << 8); }()) == 257, "FB-B2 value: sp row 7: code | op << 8");
static_assert(([]{ const Plan r = plan_save(sp_inputs(SP_CASES[7])); return r.generation; }()) == 8, "FB-B2 value: sp row 7: generation");
static_assert(([]{ const Plan r = plan_save(sp_inputs(SP_CASES[7])); return fx_digest(r); }()) == 0x663BB825BF1E6FD8ULL, "FB-B2 value: sp row 7: FNV digest of both records");
static_assert(text_is("", []{ const Plan r = plan_save(sp_inputs(SP_CASES[7])); return r.text; }()), "FB-B2 text: sp row 7: text");
static_assert(([]{ const Plan r = plan_save(sp_inputs(SP_CASES[8])); return (uint64_t) r.code | ((uint64_t) r.op << 8); }()) == 257, "FB-B2 value: sp row 8: code | op << 8");
static_assert(([]{ const Plan r = plan_save(sp_inputs(SP_CASES[8])); return r.generation; }()) == 8, "FB-B2 value: sp row 8: generation");
static_assert(([]{ const Plan r = plan_save(sp_inputs(SP_CASES[8])); return fx_digest(r); }()) == 0x663BB825BF1E6FD8ULL, "FB-B2 value: sp row 8: FNV digest of both records");
static_assert(text_is("", []{ const Plan r = plan_save(sp_inputs(SP_CASES[8])); return r.text; }()), "FB-B2 text: sp row 8: text");
static_assert(([]{ const Plan r = plan_save(sp_inputs(SP_CASES[9])); return (uint64_t) r.code | ((uint64_t) r.op << 8); }()) == 257, "FB-B2 value: sp row 9: code | op << 8");
static_assert(([]{ const Plan r = plan_save(sp_inputs(SP_CASES[9])); return r.generation; }()) == 8, "FB-B2 value: sp row 9: generation");
static_assert(([]{ const Plan r = plan_save(sp_inputs(SP_CASES[9])); return fx_digest(r); }()) == 0x663BB825BF1E6FD8ULL, "FB-B2 value: sp row 9: FNV digest of both records");
static_assert(text_is("", []{ const Plan r = plan_save(sp_inputs(SP_CASES[9])); return r.text; }()), "FB-B2 text: sp row 9: text");
static_assert(([]{ const Plan r = plan_save(sp_inputs(SP_CASES[10])); return (uint64_t) r.code | ((uint64_t) r.op << 8); }()) == 5, "FB-B2 value: sp row 10: code | op << 8");
static_assert(([]{ const Plan r = plan_save(sp_inputs(SP_CASES[10])); return r.generation; }()) == 0, "FB-B2 value: sp row 10: generation");
static_assert(([]{ const Plan r = plan_save(sp_inputs(SP_CASES[10])); return fx_digest(r); }()) == 0xEC32669A74FCAE65ULL, "FB-B2 value: sp row 10: FNV digest of both records");
static_assert(text_is("SAVE REFUSED - stored profile UNREADABLE (WRD); reboot to re-derive it (it will then read VALID, LOST or NOT_CAPTURED)", []{ const Plan r = plan_save(sp_inputs(SP_CASES[10])); return r.text; }()), "FB-B2 text: sp row 10: text");
static_assert(([]{ const Plan r = plan_save(sp_inputs(SP_CASES[11])); return (uint64_t) r.code | ((uint64_t) r.op << 8); }()) == 257, "FB-B2 value: sp row 11: code | op << 8");
static_assert(([]{ const Plan r = plan_save(sp_inputs(SP_CASES[11])); return r.generation; }()) == 21, "FB-B2 value: sp row 11: generation");
static_assert(([]{ const Plan r = plan_save(sp_inputs(SP_CASES[11])); return fx_digest(r); }()) == 0xE3C4962BFDCC0BB6ULL, "FB-B2 value: sp row 11: FNV digest of both records");
static_assert(text_is("", []{ const Plan r = plan_save(sp_inputs(SP_CASES[11])); return r.text; }()), "FB-B2 text: sp row 11: text");
static_assert(([]{ const Plan r = plan_save(sp_inputs(SP_CASES[12])); return (uint64_t) r.code | ((uint64_t) r.op << 8); }()) == 257, "FB-B2 value: sp row 12: code | op << 8");
static_assert(([]{ const Plan r = plan_save(sp_inputs(SP_CASES[12])); return r.generation; }()) == 8, "FB-B2 value: sp row 12: generation");
static_assert(([]{ const Plan r = plan_save(sp_inputs(SP_CASES[12])); return fx_digest(r); }()) == 0x663BB825BF1E6FD8ULL, "FB-B2 value: sp row 12: FNV digest of both records");
static_assert(text_is("", []{ const Plan r = plan_save(sp_inputs(SP_CASES[12])); return r.text; }()), "FB-B2 text: sp row 12: text");
static_assert(([]{ const Plan r = plan_save(sp_inputs(SP_CASES[13])); return (uint64_t) r.code | ((uint64_t) r.op << 8); }()) == 8, "FB-B2 value: sp row 13: code | op << 8");
static_assert(([]{ const Plan r = plan_save(sp_inputs(SP_CASES[13])); return r.generation; }()) == 0, "FB-B2 value: sp row 13: generation");
static_assert(([]{ const Plan r = plan_save(sp_inputs(SP_CASES[13])); return fx_digest(r); }()) == 0xEC32669A74FCAE65ULL, "FB-B2 value: sp row 13: FNV digest of both records");
static_assert(text_is("SAVE REFUSED - profile generation counter exhausted; profile unchanged", []{ const Plan r = plan_save(sp_inputs(SP_CASES[13])); return r.text; }()), "FB-B2 text: sp row 13: text");
static_assert(([]{ const Plan r = plan_save(sp_inputs(SP_CASES[14])); return (uint64_t) r.code | ((uint64_t) r.op << 8); }()) == 8, "FB-B2 value: sp row 14: code | op << 8");
static_assert(([]{ const Plan r = plan_save(sp_inputs(SP_CASES[14])); return r.generation; }()) == 0, "FB-B2 value: sp row 14: generation");
static_assert(([]{ const Plan r = plan_save(sp_inputs(SP_CASES[14])); return fx_digest(r); }()) == 0xEC32669A74FCAE65ULL, "FB-B2 value: sp row 14: FNV digest of both records");
static_assert(text_is("SAVE REFUSED - profile generation counter exhausted; profile unchanged", []{ const Plan r = plan_save(sp_inputs(SP_CASES[14])); return r.text; }()), "FB-B2 text: sp row 14: text");
static_assert(([]{ const Plan r = plan_save(sp_inputs(SP_CASES[15])); return (uint64_t) r.code | ((uint64_t) r.op << 8); }()) == 8, "FB-B2 value: sp row 15: code | op << 8");
static_assert(([]{ const Plan r = plan_save(sp_inputs(SP_CASES[15])); return r.generation; }()) == 0, "FB-B2 value: sp row 15: generation");
static_assert(([]{ const Plan r = plan_save(sp_inputs(SP_CASES[15])); return fx_digest(r); }()) == 0xEC32669A74FCAE65ULL, "FB-B2 value: sp row 15: FNV digest of both records");
static_assert(text_is("SAVE REFUSED - profile generation counter exhausted; profile unchanged", []{ const Plan r = plan_save(sp_inputs(SP_CASES[15])); return r.text; }()), "FB-B2 text: sp row 15: text");
static_assert(([]{ const Plan r = plan_save(sp_inputs(SP_CASES[16])); return (uint64_t) r.code | ((uint64_t) r.op << 8); }()) == 257, "FB-B2 value: sp row 16: code | op << 8");
static_assert(([]{ const Plan r = plan_save(sp_inputs(SP_CASES[16])); return r.generation; }()) == 4294967295u, "FB-B2 value: sp row 16: generation");
static_assert(([]{ const Plan r = plan_save(sp_inputs(SP_CASES[16])); return fx_digest(r); }()) == 0xE077A061214B1196ULL, "FB-B2 value: sp row 16: FNV digest of both records");
static_assert(text_is("", []{ const Plan r = plan_save(sp_inputs(SP_CASES[16])); return r.text; }()), "FB-B2 text: sp row 16: text");
static_assert(([]{ const Plan r = plan_save(sp_inputs(SP_CASES[17])); return (uint64_t) r.code | ((uint64_t) r.op << 8); }()) == 257, "FB-B2 value: sp row 17: code | op << 8");
static_assert(([]{ const Plan r = plan_save(sp_inputs(SP_CASES[17])); return r.generation; }()) == 9, "FB-B2 value: sp row 17: generation");
static_assert(([]{ const Plan r = plan_save(sp_inputs(SP_CASES[17])); return fx_digest(r); }()) == 0x2D16B817777D5E2DULL, "FB-B2 value: sp row 17: FNV digest of both records");
static_assert(text_is("", []{ const Plan r = plan_save(sp_inputs(SP_CASES[17])); return r.text; }()), "FB-B2 text: sp row 17: text");
static_assert(([]{ const Plan r = plan_save(sp_inputs(SP_CASES[18])); return (uint64_t) r.code | ((uint64_t) r.op << 8); }()) == 257, "FB-B2 value: sp row 18: code | op << 8");
static_assert(([]{ const Plan r = plan_save(sp_inputs(SP_CASES[18])); return r.generation; }()) == 10, "FB-B2 value: sp row 18: generation");
static_assert(([]{ const Plan r = plan_save(sp_inputs(SP_CASES[18])); return fx_digest(r); }()) == 0x5CB3FAE6F2CE3538ULL, "FB-B2 value: sp row 18: FNV digest of both records");
static_assert(text_is("", []{ const Plan r = plan_save(sp_inputs(SP_CASES[18])); return r.text; }()), "FB-B2 text: sp row 18: text");
static_assert(([]{ const Plan r = plan_save(sp_inputs(SP_CASES[19])); return (uint64_t) r.code | ((uint64_t) r.op << 8); }()) == 257, "FB-B2 value: sp row 19: code | op << 8");
static_assert(([]{ const Plan r = plan_save(sp_inputs(SP_CASES[19])); return r.generation; }()) == 6, "FB-B2 value: sp row 19: generation");
static_assert(([]{ const Plan r = plan_save(sp_inputs(SP_CASES[19])); return fx_digest(r); }()) == 0xE37C97D084F7FA5BULL, "FB-B2 value: sp row 19: FNV digest of both records");
static_assert(text_is("", []{ const Plan r = plan_save(sp_inputs(SP_CASES[19])); return r.text; }()), "FB-B2 text: sp row 19: text");
static_assert(([]{ const Plan r = plan_save(sp_inputs(SP_CASES[20])); return (uint64_t) r.code | ((uint64_t) r.op << 8); }()) == 257, "FB-B2 value: sp row 20: code | op << 8");
static_assert(([]{ const Plan r = plan_save(sp_inputs(SP_CASES[20])); return r.generation; }()) == 2, "FB-B2 value: sp row 20: generation");
static_assert(([]{ const Plan r = plan_save(sp_inputs(SP_CASES[20])); return fx_digest(r); }()) == 0x6BD3502CCB905104ULL, "FB-B2 value: sp row 20: FNV digest of both records");
static_assert(text_is("", []{ const Plan r = plan_save(sp_inputs(SP_CASES[20])); return r.text; }()), "FB-B2 text: sp row 20: text");
static_assert(([]{ const Plan r = plan_save(sp_inputs(SP_CASES[21])); return (uint64_t) r.code | ((uint64_t) r.op << 8); }()) == 257, "FB-B2 value: sp row 21: code | op << 8");
static_assert(([]{ const Plan r = plan_save(sp_inputs(SP_CASES[21])); return r.generation; }()) == 1, "FB-B2 value: sp row 21: generation");
static_assert(([]{ const Plan r = plan_save(sp_inputs(SP_CASES[21])); return fx_digest(r); }()) == 0x68D497C78ABB34FCULL, "FB-B2 value: sp row 21: FNV digest of both records");
static_assert(text_is("", []{ const Plan r = plan_save(sp_inputs(SP_CASES[21])); return r.text; }()), "FB-B2 text: sp row 21: text");
static_assert(([]{ const Plan r = plan_save(sp_inputs(SP_CASES[22])); return (uint64_t) r.code | ((uint64_t) r.op << 8); }()) == 257, "FB-B2 value: sp row 22: code | op << 8");
static_assert(([]{ const Plan r = plan_save(sp_inputs(SP_CASES[22])); return r.generation; }()) == 4, "FB-B2 value: sp row 22: generation");
static_assert(([]{ const Plan r = plan_save(sp_inputs(SP_CASES[22])); return fx_digest(r); }()) == 0x260D36447EE3A28DULL, "FB-B2 value: sp row 22: FNV digest of both records");
static_assert(text_is("", []{ const Plan r = plan_save(sp_inputs(SP_CASES[22])); return r.text; }()), "FB-B2 text: sp row 22: text");
static_assert(([]{ const Plan r = plan_save(sp_inputs(SP_CASES[23])); return (uint64_t) r.code | ((uint64_t) r.op << 8); }()) == 257, "FB-B2 value: sp row 23: code | op << 8");
static_assert(([]{ const Plan r = plan_save(sp_inputs(SP_CASES[23])); return r.generation; }()) == 1, "FB-B2 value: sp row 23: generation");
static_assert(([]{ const Plan r = plan_save(sp_inputs(SP_CASES[23])); return fx_digest(r); }()) == 0x68D497C78ABB34FCULL, "FB-B2 value: sp row 23: FNV digest of both records");
static_assert(text_is("", []{ const Plan r = plan_save(sp_inputs(SP_CASES[23])); return r.text; }()), "FB-B2 text: sp row 23: text");
static_assert(([]{ const Plan r = plan_save(sp_inputs(SP_CASES[24])); return (uint64_t) r.code | ((uint64_t) r.op << 8); }()) == 257, "FB-B2 value: sp row 24: code | op << 8");
static_assert(([]{ const Plan r = plan_save(sp_inputs(SP_CASES[24])); return r.generation; }()) == 9, "FB-B2 value: sp row 24: generation");
static_assert(([]{ const Plan r = plan_save(sp_inputs(SP_CASES[24])); return fx_digest(r); }()) == 0xF5C8FBC0E85BCE27ULL, "FB-B2 value: sp row 24: FNV digest of both records");
static_assert(text_is("", []{ const Plan r = plan_save(sp_inputs(SP_CASES[24])); return r.text; }()), "FB-B2 text: sp row 24: text");
static_assert(([]{ const Plan r = plan_save(sp_inputs(SP_CASES[25])); return (uint64_t) r.code | ((uint64_t) r.op << 8); }()) == 257, "FB-B2 value: sp row 25: code | op << 8");
static_assert(([]{ const Plan r = plan_save(sp_inputs(SP_CASES[25])); return r.generation; }()) == 7, "FB-B2 value: sp row 25: generation");
static_assert(([]{ const Plan r = plan_save(sp_inputs(SP_CASES[25])); return fx_digest(r); }()) == 0xFACAC206E7DEF5C4ULL, "FB-B2 value: sp row 25: FNV digest of both records");
static_assert(text_is("", []{ const Plan r = plan_save(sp_inputs(SP_CASES[25])); return r.text; }()), "FB-B2 text: sp row 25: text");
static_assert(([]{ const Plan r = plan_save(sp_inputs(SP_CASES[26])); return (uint64_t) r.code | ((uint64_t) r.op << 8); }()) == 257, "FB-B2 value: sp row 26: code | op << 8");
static_assert(([]{ const Plan r = plan_save(sp_inputs(SP_CASES[26])); return r.generation; }()) == 8, "FB-B2 value: sp row 26: generation");
static_assert(([]{ const Plan r = plan_save(sp_inputs(SP_CASES[26])); return fx_digest(r); }()) == 0x663BB825BF1E6FD8ULL, "FB-B2 value: sp row 26: FNV digest of both records");
static_assert(text_is("", []{ const Plan r = plan_save(sp_inputs(SP_CASES[26])); return r.text; }()), "FB-B2 text: sp row 26: text");
static_assert(([]{ const Plan r = plan_save(sp_inputs(SP_CASES[27])); return (uint64_t) r.code | ((uint64_t) r.op << 8); }()) == 257, "FB-B2 value: sp row 27: code | op << 8");
static_assert(([]{ const Plan r = plan_save(sp_inputs(SP_CASES[27])); return r.generation; }()) == 8, "FB-B2 value: sp row 27: generation");
static_assert(([]{ const Plan r = plan_save(sp_inputs(SP_CASES[27])); return fx_digest(r); }()) == 0x663BB825BF1E6FD8ULL, "FB-B2 value: sp row 27: FNV digest of both records");
static_assert(text_is("", []{ const Plan r = plan_save(sp_inputs(SP_CASES[27])); return r.text; }()), "FB-B2 text: sp row 27: text");
static_assert(([]{ const Plan r = plan_save(sp_inputs(SP_CASES[28])); return (uint64_t) r.code | ((uint64_t) r.op << 8); }()) == 769, "FB-B2 value: sp row 28: code | op << 8");
static_assert(([]{ const Plan r = plan_save(sp_inputs(SP_CASES[28])); return r.generation; }()) == 12, "FB-B2 value: sp row 28: generation");
static_assert(([]{ const Plan r = plan_save(sp_inputs(SP_CASES[28])); return fx_digest(r); }()) == 0x6BC40916DAC35C12ULL, "FB-B2 value: sp row 28: FNV digest of both records");
static_assert(text_is("", []{ const Plan r = plan_save(sp_inputs(SP_CASES[28])); return r.text; }()), "FB-B2 text: sp row 28: text");
static_assert(([]{ const Plan r = plan_save(sp_inputs(SP_CASES[29])); return (uint64_t) r.code | ((uint64_t) r.op << 8); }()) == 769, "FB-B2 value: sp row 29: code | op << 8");
static_assert(([]{ const Plan r = plan_save(sp_inputs(SP_CASES[29])); return r.generation; }()) == 1, "FB-B2 value: sp row 29: generation");
static_assert(([]{ const Plan r = plan_save(sp_inputs(SP_CASES[29])); return fx_digest(r); }()) == 0x532E1E5AEE5AA863ULL, "FB-B2 value: sp row 29: FNV digest of both records");
static_assert(text_is("", []{ const Plan r = plan_save(sp_inputs(SP_CASES[29])); return r.text; }()), "FB-B2 text: sp row 29: text");
static_assert(([]{ const Plan r = plan_save(sp_inputs(SP_CASES[30])); return (uint64_t) r.code | ((uint64_t) r.op << 8); }()) == 769, "FB-B2 value: sp row 30: code | op << 8");
static_assert(([]{ const Plan r = plan_save(sp_inputs(SP_CASES[30])); return r.generation; }()) == 13, "FB-B2 value: sp row 30: generation");
static_assert(([]{ const Plan r = plan_save(sp_inputs(SP_CASES[30])); return fx_digest(r); }()) == 0x553F36A9FA57FD4BULL, "FB-B2 value: sp row 30: FNV digest of both records");
static_assert(text_is("", []{ const Plan r = plan_save(sp_inputs(SP_CASES[30])); return r.text; }()), "FB-B2 text: sp row 30: text");
static_assert(([]{ const Plan r = plan_save(sp_inputs(SP_CASES[31])); return (uint64_t) r.code | ((uint64_t) r.op << 8); }()) == 769, "FB-B2 value: sp row 31: code | op << 8");
static_assert(([]{ const Plan r = plan_save(sp_inputs(SP_CASES[31])); return r.generation; }()) == 1, "FB-B2 value: sp row 31: generation");
static_assert(([]{ const Plan r = plan_save(sp_inputs(SP_CASES[31])); return fx_digest(r); }()) == 0x532E1E5AEE5AA863ULL, "FB-B2 value: sp row 31: FNV digest of both records");
static_assert(text_is("", []{ const Plan r = plan_save(sp_inputs(SP_CASES[31])); return r.text; }()), "FB-B2 text: sp row 31: text");
static_assert(([]{ const Plan r = plan_save(sp_inputs(SP_CASES[32])); return (uint64_t) r.code | ((uint64_t) r.op << 8); }()) == 769, "FB-B2 value: sp row 32: code | op << 8");
static_assert(([]{ const Plan r = plan_save(sp_inputs(SP_CASES[32])); return r.generation; }()) == 10, "FB-B2 value: sp row 32: generation");
static_assert(([]{ const Plan r = plan_save(sp_inputs(SP_CASES[32])); return fx_digest(r); }()) == 0x8ED4FDDC5A1ED97EULL, "FB-B2 value: sp row 32: FNV digest of both records");
static_assert(text_is("", []{ const Plan r = plan_save(sp_inputs(SP_CASES[32])); return r.text; }()), "FB-B2 text: sp row 32: text");
static_assert(([]{ const Plan r = plan_save(sp_inputs(SP_CASES[33])); return (uint64_t) r.code | ((uint64_t) r.op << 8); }()) == 769, "FB-B2 value: sp row 33: code | op << 8");
static_assert(([]{ const Plan r = plan_save(sp_inputs(SP_CASES[33])); return r.generation; }()) == 1, "FB-B2 value: sp row 33: generation");
static_assert(([]{ const Plan r = plan_save(sp_inputs(SP_CASES[33])); return fx_digest(r); }()) == 0x532E1E5AEE5AA863ULL, "FB-B2 value: sp row 33: FNV digest of both records");
static_assert(text_is("", []{ const Plan r = plan_save(sp_inputs(SP_CASES[33])); return r.text; }()), "FB-B2 text: sp row 33: text");
static_assert(([]{ const Plan r = plan_save(sp_inputs(SP_CASES[34])); return (uint64_t) r.code | ((uint64_t) r.op << 8); }()) == 769, "FB-B2 value: sp row 34: code | op << 8");
static_assert(([]{ const Plan r = plan_save(sp_inputs(SP_CASES[34])); return r.generation; }()) == 1, "FB-B2 value: sp row 34: generation");
static_assert(([]{ const Plan r = plan_save(sp_inputs(SP_CASES[34])); return fx_digest(r); }()) == 0x532E1E5AEE5AA863ULL, "FB-B2 value: sp row 34: FNV digest of both records");
static_assert(text_is("", []{ const Plan r = plan_save(sp_inputs(SP_CASES[34])); return r.text; }()), "FB-B2 text: sp row 34: text");
static_assert(([]{ const Plan r = plan_save(sp_inputs(SP_CASES[35])); return (uint64_t) r.code | ((uint64_t) r.op << 8); }()) == 5, "FB-B2 value: sp row 35: code | op << 8");
static_assert(([]{ const Plan r = plan_save(sp_inputs(SP_CASES[35])); return r.generation; }()) == 0, "FB-B2 value: sp row 35: generation");
static_assert(([]{ const Plan r = plan_save(sp_inputs(SP_CASES[35])); return fx_digest(r); }()) == 0xEC32669A74FCAE65ULL, "FB-B2 value: sp row 35: FNV digest of both records");
static_assert(text_is("SAVE REFUSED - stored profile UNREADABLE (PRD); reboot to re-derive it (it will then read VALID, LOST or NOT_CAPTURED)", []{ const Plan r = plan_save(sp_inputs(SP_CASES[35])); return r.text; }()), "FB-B2 text: sp row 35: text");
static_assert(([]{ const Plan r = plan_save(sp_inputs(SP_CASES[36])); return (uint64_t) r.code | ((uint64_t) r.op << 8); }()) == 5, "FB-B2 value: sp row 36: code | op << 8");
static_assert(([]{ const Plan r = plan_save(sp_inputs(SP_CASES[36])); return r.generation; }()) == 0, "FB-B2 value: sp row 36: generation");
static_assert(([]{ const Plan r = plan_save(sp_inputs(SP_CASES[36])); return fx_digest(r); }()) == 0xEC32669A74FCAE65ULL, "FB-B2 value: sp row 36: FNV digest of both records");
static_assert(text_is("SAVE REFUSED - stored profile UNREADABLE (PRD); reboot to re-derive it (it will then read VALID, LOST or NOT_CAPTURED)", []{ const Plan r = plan_save(sp_inputs(SP_CASES[36])); return r.text; }()), "FB-B2 text: sp row 36: text");
static_assert(([]{ const Plan r = plan_save(sp_inputs(SP_CASES[37])); return (uint64_t) r.code | ((uint64_t) r.op << 8); }()) == 5, "FB-B2 value: sp row 37: code | op << 8");
static_assert(([]{ const Plan r = plan_save(sp_inputs(SP_CASES[37])); return r.generation; }()) == 0, "FB-B2 value: sp row 37: generation");
static_assert(([]{ const Plan r = plan_save(sp_inputs(SP_CASES[37])); return fx_digest(r); }()) == 0xEC32669A74FCAE65ULL, "FB-B2 value: sp row 37: FNV digest of both records");
static_assert(text_is("SAVE REFUSED - stored profile UNREADABLE (PRD); reboot to re-derive it (it will then read VALID, LOST or NOT_CAPTURED)", []{ const Plan r = plan_save(sp_inputs(SP_CASES[37])); return r.text; }()), "FB-B2 text: sp row 37: text");
static_assert(([]{ const Plan r = plan_save(sp_inputs(SP_CASES[38])); return (uint64_t) r.code | ((uint64_t) r.op << 8); }()) == 3, "FB-B2 value: sp row 38: code | op << 8");
static_assert(([]{ const Plan r = plan_save(sp_inputs(SP_CASES[38])); return r.generation; }()) == 0, "FB-B2 value: sp row 38: generation");
static_assert(([]{ const Plan r = plan_save(sp_inputs(SP_CASES[38])); return fx_digest(r); }()) == 0xEC32669A74FCAE65ULL, "FB-B2 value: sp row 38: FNV digest of both records");
static_assert(text_is("SAVE REFUSED - previous save outcome unknown this boot - reboot to re-verify first", []{ const Plan r = plan_save(sp_inputs(SP_CASES[38])); return r.text; }()), "FB-B2 text: sp row 38: text");
static_assert(([]{ const Plan r = plan_save(sp_inputs(SP_CASES[39])); return (uint64_t) r.code | ((uint64_t) r.op << 8); }()) == 4, "FB-B2 value: sp row 39: code | op << 8");
static_assert(([]{ const Plan r = plan_save(sp_inputs(SP_CASES[39])); return r.generation; }()) == 0, "FB-B2 value: sp row 39: generation");
static_assert(([]{ const Plan r = plan_save(sp_inputs(SP_CASES[39])); return fx_digest(r); }()) == 0xEC32669A74FCAE65ULL, "FB-B2 value: sp row 39: FNV digest of both records");
static_assert(text_is("SAVE REFUSED - stored profile read anomaly this boot; reboot to re-derive it first", []{ const Plan r = plan_save(sp_inputs(SP_CASES[39])); return r.text; }()), "FB-B2 text: sp row 39: text");
static_assert(([]{ const Plan r = plan_save(sp_inputs(SP_CASES[40])); return (uint64_t) r.code | ((uint64_t) r.op << 8); }()) == 6, "FB-B2 value: sp row 40: code | op << 8");
static_assert(([]{ const Plan r = plan_save(sp_inputs(SP_CASES[40])); return r.generation; }()) == 0, "FB-B2 value: sp row 40: generation");
static_assert(([]{ const Plan r = plan_save(sp_inputs(SP_CASES[40])); return fx_digest(r); }()) == 0xEC32669A74FCAE65ULL, "FB-B2 value: sp row 40: FNV digest of both records");
static_assert(text_is("INTERNAL - Fallback Profile dispatch context invalid; nothing written", []{ const Plan r = plan_save(sp_inputs(SP_CASES[40])); return r.text; }()), "FB-B2 text: sp row 40: text");
static_assert(([]{ const Plan r = plan_save(sp_inputs(SP_CASES[41])); return (uint64_t) r.code | ((uint64_t) r.op << 8); }()) == 6, "FB-B2 value: sp row 41: code | op << 8");
static_assert(([]{ const Plan r = plan_save(sp_inputs(SP_CASES[41])); return r.generation; }()) == 0, "FB-B2 value: sp row 41: generation");
static_assert(([]{ const Plan r = plan_save(sp_inputs(SP_CASES[41])); return fx_digest(r); }()) == 0xEC32669A74FCAE65ULL, "FB-B2 value: sp row 41: FNV digest of both records");
static_assert(text_is("INTERNAL - Fallback Profile dispatch context invalid; nothing written", []{ const Plan r = plan_save(sp_inputs(SP_CASES[41])); return r.text; }()), "FB-B2 text: sp row 41: text");
static_assert(([]{ const Plan r = plan_save(sp_inputs(SP_CASES[42])); return (uint64_t) r.code | ((uint64_t) r.op << 8); }()) == 7, "FB-B2 value: sp row 42: code | op << 8");
static_assert(([]{ const Plan r = plan_save(sp_inputs(SP_CASES[42])); return r.generation; }()) == 0, "FB-B2 value: sp row 42: generation");
static_assert(([]{ const Plan r = plan_save(sp_inputs(SP_CASES[42])); return fx_digest(r); }()) == 0xEC32669A74FCAE65ULL, "FB-B2 value: sp row 42: FNV digest of both records");
static_assert(text_is("SAVE REFUSED - clock not NTP-synchronised this boot; the capture time would be untrusted", []{ const Plan r = plan_save(sp_inputs(SP_CASES[42])); return r.text; }()), "FB-B2 text: sp row 42: text");
static_assert(([]{ const Plan r = plan_save(sp_inputs(SP_CASES[43])); return (uint64_t) r.code | ((uint64_t) r.op << 8); }()) == 5, "FB-B2 value: sp row 43: code | op << 8");
static_assert(([]{ const Plan r = plan_save(sp_inputs(SP_CASES[43])); return r.generation; }()) == 0, "FB-B2 value: sp row 43: generation");
static_assert(([]{ const Plan r = plan_save(sp_inputs(SP_CASES[43])); return fx_digest(r); }()) == 0xEC32669A74FCAE65ULL, "FB-B2 value: sp row 43: FNV digest of both records");
static_assert(text_is("SAVE REFUSED - previous save outcome unknown this boot - reboot to re-verify first", []{ const Plan r = plan_save(sp_inputs(SP_CASES[43])); return r.text; }()), "FB-B2 text: sp row 43: text");
static_assert(([]{ const Plan r = plan_save(sp_inputs(SP_CASES[44])); return (uint64_t) r.code | ((uint64_t) r.op << 8); }()) == 5, "FB-B2 value: sp row 44: code | op << 8");
static_assert(([]{ const Plan r = plan_save(sp_inputs(SP_CASES[44])); return r.generation; }()) == 0, "FB-B2 value: sp row 44: generation");
static_assert(([]{ const Plan r = plan_save(sp_inputs(SP_CASES[44])); return fx_digest(r); }()) == 0xEC32669A74FCAE65ULL, "FB-B2 value: sp row 44: FNV digest of both records");
static_assert(text_is("SAVE REFUSED - stored profile state does not permit saving", []{ const Plan r = plan_save(sp_inputs(SP_CASES[44])); return r.text; }()), "FB-B2 text: sp row 44: text");
static_assert(([]{ const Plan r = plan_save(sp_inputs(SP_CASES[45])); return (uint64_t) r.code | ((uint64_t) r.op << 8); }()) == 2, "FB-B2 value: sp row 45: code | op << 8");
static_assert(([]{ const Plan r = plan_save(sp_inputs(SP_CASES[45])); return r.generation; }()) == 0, "FB-B2 value: sp row 45: generation");
static_assert(([]{ const Plan r = plan_save(sp_inputs(SP_CASES[45])); return fx_digest(r); }()) == 0xEC32669A74FCAE65ULL, "FB-B2 value: sp row 45: FNV digest of both records");
static_assert(text_is("SAVE REFUSED - stored profile changed since Review; profile unchanged", []{ const Plan r = plan_save(sp_inputs(SP_CASES[45])); return r.text; }()), "FB-B2 text: sp row 45: text");
static_assert(([]{ const Plan r = plan_save(sp_inputs(SP_CASES[46])); return (uint64_t) r.code | ((uint64_t) r.op << 8); }()) == 2, "FB-B2 value: sp row 46: code | op << 8");
static_assert(([]{ const Plan r = plan_save(sp_inputs(SP_CASES[46])); return r.generation; }()) == 0, "FB-B2 value: sp row 46: generation");
static_assert(([]{ const Plan r = plan_save(sp_inputs(SP_CASES[46])); return fx_digest(r); }()) == 0xEC32669A74FCAE65ULL, "FB-B2 value: sp row 46: FNV digest of both records");
static_assert(text_is("SAVE REFUSED - stored profile changed since Review; profile unchanged", []{ const Plan r = plan_save(sp_inputs(SP_CASES[46])); return r.text; }()), "FB-B2 text: sp row 46: text");
static_assert(([]{ const Plan r = plan_save(sp_inputs(SP_CASES[47])); return (uint64_t) r.code | ((uint64_t) r.op << 8); }()) == 2, "FB-B2 value: sp row 47: code | op << 8");
static_assert(([]{ const Plan r = plan_save(sp_inputs(SP_CASES[47])); return r.generation; }()) == 0, "FB-B2 value: sp row 47: generation");
static_assert(([]{ const Plan r = plan_save(sp_inputs(SP_CASES[47])); return fx_digest(r); }()) == 0xEC32669A74FCAE65ULL, "FB-B2 value: sp row 47: FNV digest of both records");
static_assert(text_is("SAVE REFUSED - stored profile changed since Review; profile unchanged", []{ const Plan r = plan_save(sp_inputs(SP_CASES[47])); return r.text; }()), "FB-B2 text: sp row 47: text");
static_assert(([]{ const Plan r = plan_save(sp_inputs(SP_CASES[48])); return (uint64_t) r.code | ((uint64_t) r.op << 8); }()) == 2, "FB-B2 value: sp row 48: code | op << 8");
static_assert(([]{ const Plan r = plan_save(sp_inputs(SP_CASES[48])); return r.generation; }()) == 0, "FB-B2 value: sp row 48: generation");
static_assert(([]{ const Plan r = plan_save(sp_inputs(SP_CASES[48])); return fx_digest(r); }()) == 0xEC32669A74FCAE65ULL, "FB-B2 value: sp row 48: FNV digest of both records");
static_assert(text_is("SAVE REFUSED - stored profile changed since Review; profile unchanged", []{ const Plan r = plan_save(sp_inputs(SP_CASES[48])); return r.text; }()), "FB-B2 text: sp row 48: text");
static_assert(([]{ const Plan r = plan_save(sp_inputs(SP_CASES[49])); return (uint64_t) r.code | ((uint64_t) r.op << 8); }()) == 2, "FB-B2 value: sp row 49: code | op << 8");
static_assert(([]{ const Plan r = plan_save(sp_inputs(SP_CASES[49])); return r.generation; }()) == 0, "FB-B2 value: sp row 49: generation");
static_assert(([]{ const Plan r = plan_save(sp_inputs(SP_CASES[49])); return fx_digest(r); }()) == 0xEC32669A74FCAE65ULL, "FB-B2 value: sp row 49: FNV digest of both records");
static_assert(text_is("SAVE REFUSED - stored profile changed since Review; profile unchanged", []{ const Plan r = plan_save(sp_inputs(SP_CASES[49])); return r.text; }()), "FB-B2 text: sp row 49: text");
static_assert(([]{ const Plan r = plan_save(sp_inputs(SP_CASES[50])); return (uint64_t) r.code | ((uint64_t) r.op << 8); }()) == 2, "FB-B2 value: sp row 50: code | op << 8");
static_assert(([]{ const Plan r = plan_save(sp_inputs(SP_CASES[50])); return r.generation; }()) == 0, "FB-B2 value: sp row 50: generation");
static_assert(([]{ const Plan r = plan_save(sp_inputs(SP_CASES[50])); return fx_digest(r); }()) == 0xEC32669A74FCAE65ULL, "FB-B2 value: sp row 50: FNV digest of both records");
static_assert(text_is("SAVE REFUSED - stored profile changed since Review; profile unchanged", []{ const Plan r = plan_save(sp_inputs(SP_CASES[50])); return r.text; }()), "FB-B2 text: sp row 50: text");
static_assert(([]{ const Plan r = plan_save(sp_inputs(SP_CASES[51])); return (uint64_t) r.code | ((uint64_t) r.op << 8); }()) == 2, "FB-B2 value: sp row 51: code | op << 8");
static_assert(([]{ const Plan r = plan_save(sp_inputs(SP_CASES[51])); return r.generation; }()) == 0, "FB-B2 value: sp row 51: generation");
static_assert(([]{ const Plan r = plan_save(sp_inputs(SP_CASES[51])); return fx_digest(r); }()) == 0xEC32669A74FCAE65ULL, "FB-B2 value: sp row 51: FNV digest of both records");
static_assert(text_is("SAVE REFUSED - stored profile changed since Review; profile unchanged", []{ const Plan r = plan_save(sp_inputs(SP_CASES[51])); return r.text; }()), "FB-B2 text: sp row 51: text");
static_assert(([]{ const Plan r = plan_save(sp_inputs(SP_CASES[52])); return (uint64_t) r.code | ((uint64_t) r.op << 8); }()) == 2, "FB-B2 value: sp row 52: code | op << 8");
static_assert(([]{ const Plan r = plan_save(sp_inputs(SP_CASES[52])); return r.generation; }()) == 0, "FB-B2 value: sp row 52: generation");
static_assert(([]{ const Plan r = plan_save(sp_inputs(SP_CASES[52])); return fx_digest(r); }()) == 0xEC32669A74FCAE65ULL, "FB-B2 value: sp row 52: FNV digest of both records");
static_assert(text_is("SAVE REFUSED - stored profile changed since Review; profile unchanged", []{ const Plan r = plan_save(sp_inputs(SP_CASES[52])); return r.text; }()), "FB-B2 text: sp row 52: text");
static_assert(([]{ const Plan r = plan_save(sp_inputs(SP_CASES[53])); return (uint64_t) r.code | ((uint64_t) r.op << 8); }()) == 2, "FB-B2 value: sp row 53: code | op << 8");
static_assert(([]{ const Plan r = plan_save(sp_inputs(SP_CASES[53])); return r.generation; }()) == 0, "FB-B2 value: sp row 53: generation");
static_assert(([]{ const Plan r = plan_save(sp_inputs(SP_CASES[53])); return fx_digest(r); }()) == 0xEC32669A74FCAE65ULL, "FB-B2 value: sp row 53: FNV digest of both records");
static_assert(text_is("SAVE REFUSED - stored profile changed since Review; profile unchanged", []{ const Plan r = plan_save(sp_inputs(SP_CASES[53])); return r.text; }()), "FB-B2 text: sp row 53: text");
static_assert(([]{ const Plan r = plan_save(sp_inputs(SP_CASES[54])); return (uint64_t) r.code | ((uint64_t) r.op << 8); }()) == 2, "FB-B2 value: sp row 54: code | op << 8");
static_assert(([]{ const Plan r = plan_save(sp_inputs(SP_CASES[54])); return r.generation; }()) == 0, "FB-B2 value: sp row 54: generation");
static_assert(([]{ const Plan r = plan_save(sp_inputs(SP_CASES[54])); return fx_digest(r); }()) == 0xEC32669A74FCAE65ULL, "FB-B2 value: sp row 54: FNV digest of both records");
static_assert(text_is("SAVE REFUSED - stored profile changed since Review; profile unchanged", []{ const Plan r = plan_save(sp_inputs(SP_CASES[54])); return r.text; }()), "FB-B2 text: sp row 54: text");
static_assert(([]{ const Plan r = plan_save(sp_inputs(SP_CASES[55])); return (uint64_t) r.code | ((uint64_t) r.op << 8); }()) == 2, "FB-B2 value: sp row 55: code | op << 8");
static_assert(([]{ const Plan r = plan_save(sp_inputs(SP_CASES[55])); return r.generation; }()) == 0, "FB-B2 value: sp row 55: generation");
static_assert(([]{ const Plan r = plan_save(sp_inputs(SP_CASES[55])); return fx_digest(r); }()) == 0xEC32669A74FCAE65ULL, "FB-B2 value: sp row 55: FNV digest of both records");
static_assert(text_is("SAVE REFUSED - stored profile changed since Review; profile unchanged", []{ const Plan r = plan_save(sp_inputs(SP_CASES[55])); return r.text; }()), "FB-B2 text: sp row 55: text");
static_assert(([]{ const Plan r = plan_save(sp_inputs(SP_CASES[56])); return (uint64_t) r.code | ((uint64_t) r.op << 8); }()) == 2, "FB-B2 value: sp row 56: code | op << 8");
static_assert(([]{ const Plan r = plan_save(sp_inputs(SP_CASES[56])); return r.generation; }()) == 0, "FB-B2 value: sp row 56: generation");
static_assert(([]{ const Plan r = plan_save(sp_inputs(SP_CASES[56])); return fx_digest(r); }()) == 0xEC32669A74FCAE65ULL, "FB-B2 value: sp row 56: FNV digest of both records");
static_assert(text_is("SAVE REFUSED - stored profile changed since Review; profile unchanged", []{ const Plan r = plan_save(sp_inputs(SP_CASES[56])); return r.text; }()), "FB-B2 text: sp row 56: text");
static_assert(([]{ const Plan r = plan_save(sp_inputs(SP_CASES[57])); return (uint64_t) r.code | ((uint64_t) r.op << 8); }()) == 2, "FB-B2 value: sp row 57: code | op << 8");
static_assert(([]{ const Plan r = plan_save(sp_inputs(SP_CASES[57])); return r.generation; }()) == 0, "FB-B2 value: sp row 57: generation");
static_assert(([]{ const Plan r = plan_save(sp_inputs(SP_CASES[57])); return fx_digest(r); }()) == 0xEC32669A74FCAE65ULL, "FB-B2 value: sp row 57: FNV digest of both records");
static_assert(text_is("SAVE REFUSED - stored profile changed since Review; profile unchanged", []{ const Plan r = plan_save(sp_inputs(SP_CASES[57])); return r.text; }()), "FB-B2 text: sp row 57: text");
static_assert(([]{ const Plan r = plan_save(sp_inputs(SP_CASES[58])); return (uint64_t) r.code | ((uint64_t) r.op << 8); }()) == 2, "FB-B2 value: sp row 58: code | op << 8");
static_assert(([]{ const Plan r = plan_save(sp_inputs(SP_CASES[58])); return r.generation; }()) == 0, "FB-B2 value: sp row 58: generation");
static_assert(([]{ const Plan r = plan_save(sp_inputs(SP_CASES[58])); return fx_digest(r); }()) == 0xEC32669A74FCAE65ULL, "FB-B2 value: sp row 58: FNV digest of both records");
static_assert(text_is("SAVE REFUSED - stored profile changed since Review; profile unchanged", []{ const Plan r = plan_save(sp_inputs(SP_CASES[58])); return r.text; }()), "FB-B2 text: sp row 58: text");
static_assert(([]{ const Plan r = plan_save(sp_inputs(SP_CASES[59])); return (uint64_t) r.code | ((uint64_t) r.op << 8); }()) == 3, "FB-B2 value: sp row 59: code | op << 8");
static_assert(([]{ const Plan r = plan_save(sp_inputs(SP_CASES[59])); return r.generation; }()) == 0, "FB-B2 value: sp row 59: generation");
static_assert(([]{ const Plan r = plan_save(sp_inputs(SP_CASES[59])); return fx_digest(r); }()) == 0xEC32669A74FCAE65ULL, "FB-B2 value: sp row 59: FNV digest of both records");
static_assert(text_is("SAVE REFUSED - previous save outcome unknown this boot - reboot to re-verify first", []{ const Plan r = plan_save(sp_inputs(SP_CASES[59])); return r.text; }()), "FB-B2 text: sp row 59: text");
static_assert(([]{ const Plan r = plan_save(sp_inputs(SP_CASES[60])); return (uint64_t) r.code | ((uint64_t) r.op << 8); }()) == 4, "FB-B2 value: sp row 60: code | op << 8");
static_assert(([]{ const Plan r = plan_save(sp_inputs(SP_CASES[60])); return r.generation; }()) == 0, "FB-B2 value: sp row 60: generation");
static_assert(([]{ const Plan r = plan_save(sp_inputs(SP_CASES[60])); return fx_digest(r); }()) == 0xEC32669A74FCAE65ULL, "FB-B2 value: sp row 60: FNV digest of both records");
static_assert(text_is("SAVE REFUSED - stored profile read anomaly this boot; reboot to re-derive it first", []{ const Plan r = plan_save(sp_inputs(SP_CASES[60])); return r.text; }()), "FB-B2 text: sp row 60: text");
static_assert(([]{ const Plan r = plan_save(sp_inputs(SP_CASES[61])); return (uint64_t) r.code | ((uint64_t) r.op << 8); }()) == 6, "FB-B2 value: sp row 61: code | op << 8");
static_assert(([]{ const Plan r = plan_save(sp_inputs(SP_CASES[61])); return r.generation; }()) == 0, "FB-B2 value: sp row 61: generation");
static_assert(([]{ const Plan r = plan_save(sp_inputs(SP_CASES[61])); return fx_digest(r); }()) == 0xEC32669A74FCAE65ULL, "FB-B2 value: sp row 61: FNV digest of both records");
static_assert(text_is("INTERNAL - Fallback Profile dispatch context invalid; nothing written", []{ const Plan r = plan_save(sp_inputs(SP_CASES[61])); return r.text; }()), "FB-B2 text: sp row 61: text");
static_assert(([]{ const Plan r = plan_save(sp_inputs(SP_CASES[62])); return (uint64_t) r.code | ((uint64_t) r.op << 8); }()) == 7, "FB-B2 value: sp row 62: code | op << 8");
static_assert(([]{ const Plan r = plan_save(sp_inputs(SP_CASES[62])); return r.generation; }()) == 0, "FB-B2 value: sp row 62: generation");
static_assert(([]{ const Plan r = plan_save(sp_inputs(SP_CASES[62])); return fx_digest(r); }()) == 0xEC32669A74FCAE65ULL, "FB-B2 value: sp row 62: FNV digest of both records");
static_assert(text_is("SAVE REFUSED - clock not NTP-synchronised this boot; the capture time would be untrusted", []{ const Plan r = plan_save(sp_inputs(SP_CASES[62])); return r.text; }()), "FB-B2 text: sp row 62: text");
static_assert(([]{ const Plan r = plan_invalidate(ip_inputs(IP_CASES[0])); return (uint64_t) r.code | ((uint64_t) r.op << 8); }()) == 513, "FB-B2 value: ip row 0: code | op << 8");
static_assert(([]{ const Plan r = plan_invalidate(ip_inputs(IP_CASES[0])); return r.generation; }()) == 8, "FB-B2 value: ip row 0: generation");
static_assert(([]{ const Plan r = plan_invalidate(ip_inputs(IP_CASES[0])); return fx_digest(r); }()) == 0xC7349C5B0EF68642ULL, "FB-B2 value: ip row 0: FNV digest of both records");
static_assert(text_is("", []{ const Plan r = plan_invalidate(ip_inputs(IP_CASES[0])); return r.text; }()), "FB-B2 text: ip row 0: text");
static_assert(([]{ const Plan r = plan_invalidate(ip_inputs(IP_CASES[1])); return (uint64_t) r.code | ((uint64_t) r.op << 8); }()) == 513, "FB-B2 value: ip row 1: code | op << 8");
static_assert(([]{ const Plan r = plan_invalidate(ip_inputs(IP_CASES[1])); return r.generation; }()) == 8, "FB-B2 value: ip row 1: generation");
static_assert(([]{ const Plan r = plan_invalidate(ip_inputs(IP_CASES[1])); return fx_digest(r); }()) == 0xC7349C5B0EF68642ULL, "FB-B2 value: ip row 1: FNV digest of both records");
static_assert(text_is("", []{ const Plan r = plan_invalidate(ip_inputs(IP_CASES[1])); return r.text; }()), "FB-B2 text: ip row 1: text");
static_assert(([]{ const Plan r = plan_invalidate(ip_inputs(IP_CASES[2])); return (uint64_t) r.code | ((uint64_t) r.op << 8); }()) == 513, "FB-B2 value: ip row 2: code | op << 8");
static_assert(([]{ const Plan r = plan_invalidate(ip_inputs(IP_CASES[2])); return r.generation; }()) == 8, "FB-B2 value: ip row 2: generation");
static_assert(([]{ const Plan r = plan_invalidate(ip_inputs(IP_CASES[2])); return fx_digest(r); }()) == 0xC7349C5B0EF68642ULL, "FB-B2 value: ip row 2: FNV digest of both records");
static_assert(text_is("", []{ const Plan r = plan_invalidate(ip_inputs(IP_CASES[2])); return r.text; }()), "FB-B2 text: ip row 2: text");
static_assert(([]{ const Plan r = plan_invalidate(ip_inputs(IP_CASES[3])); return (uint64_t) r.code | ((uint64_t) r.op << 8); }()) == 513, "FB-B2 value: ip row 3: code | op << 8");
static_assert(([]{ const Plan r = plan_invalidate(ip_inputs(IP_CASES[3])); return r.generation; }()) == 8, "FB-B2 value: ip row 3: generation");
static_assert(([]{ const Plan r = plan_invalidate(ip_inputs(IP_CASES[3])); return fx_digest(r); }()) == 0xC7349C5B0EF68642ULL, "FB-B2 value: ip row 3: FNV digest of both records");
static_assert(text_is("", []{ const Plan r = plan_invalidate(ip_inputs(IP_CASES[3])); return r.text; }()), "FB-B2 text: ip row 3: text");
static_assert(([]{ const Plan r = plan_invalidate(ip_inputs(IP_CASES[4])); return (uint64_t) r.code | ((uint64_t) r.op << 8); }()) == 513, "FB-B2 value: ip row 4: code | op << 8");
static_assert(([]{ const Plan r = plan_invalidate(ip_inputs(IP_CASES[4])); return r.generation; }()) == 8, "FB-B2 value: ip row 4: generation");
static_assert(([]{ const Plan r = plan_invalidate(ip_inputs(IP_CASES[4])); return fx_digest(r); }()) == 0xC7349C5B0EF68642ULL, "FB-B2 value: ip row 4: FNV digest of both records");
static_assert(text_is("", []{ const Plan r = plan_invalidate(ip_inputs(IP_CASES[4])); return r.text; }()), "FB-B2 text: ip row 4: text");
static_assert(([]{ const Plan r = plan_invalidate(ip_inputs(IP_CASES[5])); return (uint64_t) r.code | ((uint64_t) r.op << 8); }()) == 513, "FB-B2 value: ip row 5: code | op << 8");
static_assert(([]{ const Plan r = plan_invalidate(ip_inputs(IP_CASES[5])); return r.generation; }()) == 8, "FB-B2 value: ip row 5: generation");
static_assert(([]{ const Plan r = plan_invalidate(ip_inputs(IP_CASES[5])); return fx_digest(r); }()) == 0xC7349C5B0EF68642ULL, "FB-B2 value: ip row 5: FNV digest of both records");
static_assert(text_is("", []{ const Plan r = plan_invalidate(ip_inputs(IP_CASES[5])); return r.text; }()), "FB-B2 text: ip row 5: text");
static_assert(([]{ const Plan r = plan_invalidate(ip_inputs(IP_CASES[6])); return (uint64_t) r.code | ((uint64_t) r.op << 8); }()) == 513, "FB-B2 value: ip row 6: code | op << 8");
static_assert(([]{ const Plan r = plan_invalidate(ip_inputs(IP_CASES[6])); return r.generation; }()) == 8, "FB-B2 value: ip row 6: generation");
static_assert(([]{ const Plan r = plan_invalidate(ip_inputs(IP_CASES[6])); return fx_digest(r); }()) == 0xC7349C5B0EF68642ULL, "FB-B2 value: ip row 6: FNV digest of both records");
static_assert(text_is("", []{ const Plan r = plan_invalidate(ip_inputs(IP_CASES[6])); return r.text; }()), "FB-B2 text: ip row 6: text");
static_assert(([]{ const Plan r = plan_invalidate(ip_inputs(IP_CASES[7])); return (uint64_t) r.code | ((uint64_t) r.op << 8); }()) == 513, "FB-B2 value: ip row 7: code | op << 8");
static_assert(([]{ const Plan r = plan_invalidate(ip_inputs(IP_CASES[7])); return r.generation; }()) == 8, "FB-B2 value: ip row 7: generation");
static_assert(([]{ const Plan r = plan_invalidate(ip_inputs(IP_CASES[7])); return fx_digest(r); }()) == 0xC7349C5B0EF68642ULL, "FB-B2 value: ip row 7: FNV digest of both records");
static_assert(text_is("", []{ const Plan r = plan_invalidate(ip_inputs(IP_CASES[7])); return r.text; }()), "FB-B2 text: ip row 7: text");
static_assert(([]{ const Plan r = plan_invalidate(ip_inputs(IP_CASES[8])); return (uint64_t) r.code | ((uint64_t) r.op << 8); }()) == 513, "FB-B2 value: ip row 8: code | op << 8");
static_assert(([]{ const Plan r = plan_invalidate(ip_inputs(IP_CASES[8])); return r.generation; }()) == 8, "FB-B2 value: ip row 8: generation");
static_assert(([]{ const Plan r = plan_invalidate(ip_inputs(IP_CASES[8])); return fx_digest(r); }()) == 0xC7349C5B0EF68642ULL, "FB-B2 value: ip row 8: FNV digest of both records");
static_assert(text_is("", []{ const Plan r = plan_invalidate(ip_inputs(IP_CASES[8])); return r.text; }()), "FB-B2 text: ip row 8: text");
static_assert(([]{ const Plan r = plan_invalidate(ip_inputs(IP_CASES[9])); return (uint64_t) r.code | ((uint64_t) r.op << 8); }()) == 513, "FB-B2 value: ip row 9: code | op << 8");
static_assert(([]{ const Plan r = plan_invalidate(ip_inputs(IP_CASES[9])); return r.generation; }()) == 8, "FB-B2 value: ip row 9: generation");
static_assert(([]{ const Plan r = plan_invalidate(ip_inputs(IP_CASES[9])); return fx_digest(r); }()) == 0xC7349C5B0EF68642ULL, "FB-B2 value: ip row 9: FNV digest of both records");
static_assert(text_is("", []{ const Plan r = plan_invalidate(ip_inputs(IP_CASES[9])); return r.text; }()), "FB-B2 text: ip row 9: text");
static_assert(([]{ const Plan r = plan_invalidate(ip_inputs(IP_CASES[10])); return (uint64_t) r.code | ((uint64_t) r.op << 8); }()) == 5, "FB-B2 value: ip row 10: code | op << 8");
static_assert(([]{ const Plan r = plan_invalidate(ip_inputs(IP_CASES[10])); return r.generation; }()) == 0, "FB-B2 value: ip row 10: generation");
static_assert(([]{ const Plan r = plan_invalidate(ip_inputs(IP_CASES[10])); return fx_digest(r); }()) == 0xEC32669A74FCAE65ULL, "FB-B2 value: ip row 10: FNV digest of both records");
static_assert(text_is("INVALIDATE REFUSED - profile is now INVALIDATED; nothing written", []{ const Plan r = plan_invalidate(ip_inputs(IP_CASES[10])); return r.text; }()), "FB-B2 text: ip row 10: text");
static_assert(([]{ const Plan r = plan_invalidate(ip_inputs(IP_CASES[11])); return (uint64_t) r.code | ((uint64_t) r.op << 8); }()) == 5, "FB-B2 value: ip row 11: code | op << 8");
static_assert(([]{ const Plan r = plan_invalidate(ip_inputs(IP_CASES[11])); return r.generation; }()) == 0, "FB-B2 value: ip row 11: generation");
static_assert(([]{ const Plan r = plan_invalidate(ip_inputs(IP_CASES[11])); return fx_digest(r); }()) == 0xEC32669A74FCAE65ULL, "FB-B2 value: ip row 11: FNV digest of both records");
static_assert(text_is("INVALIDATE REFUSED - profile is now CORRUPT_DOMAIN; nothing written", []{ const Plan r = plan_invalidate(ip_inputs(IP_CASES[11])); return r.text; }()), "FB-B2 text: ip row 11: text");
static_assert(([]{ const Plan r = plan_invalidate(ip_inputs(IP_CASES[12])); return (uint64_t) r.code | ((uint64_t) r.op << 8); }()) == 5, "FB-B2 value: ip row 12: code | op << 8");
static_assert(([]{ const Plan r = plan_invalidate(ip_inputs(IP_CASES[12])); return r.generation; }()) == 0, "FB-B2 value: ip row 12: generation");
static_assert(([]{ const Plan r = plan_invalidate(ip_inputs(IP_CASES[12])); return fx_digest(r); }()) == 0xEC32669A74FCAE65ULL, "FB-B2 value: ip row 12: FNV digest of both records");
static_assert(text_is("INVALIDATE REFUSED - profile is now CORRUPT; nothing written", []{ const Plan r = plan_invalidate(ip_inputs(IP_CASES[12])); return r.text; }()), "FB-B2 text: ip row 12: text");
static_assert(([]{ const Plan r = plan_invalidate(ip_inputs(IP_CASES[13])); return (uint64_t) r.code | ((uint64_t) r.op << 8); }()) == 5, "FB-B2 value: ip row 13: code | op << 8");
static_assert(([]{ const Plan r = plan_invalidate(ip_inputs(IP_CASES[13])); return r.generation; }()) == 0, "FB-B2 value: ip row 13: generation");
static_assert(([]{ const Plan r = plan_invalidate(ip_inputs(IP_CASES[13])); return fx_digest(r); }()) == 0xEC32669A74FCAE65ULL, "FB-B2 value: ip row 13: FNV digest of both records");
static_assert(text_is("INVALIDATE REFUSED - profile is now CORRUPT; nothing written", []{ const Plan r = plan_invalidate(ip_inputs(IP_CASES[13])); return r.text; }()), "FB-B2 text: ip row 13: text");
static_assert(([]{ const Plan r = plan_invalidate(ip_inputs(IP_CASES[14])); return (uint64_t) r.code | ((uint64_t) r.op << 8); }()) == 5, "FB-B2 value: ip row 14: code | op << 8");
static_assert(([]{ const Plan r = plan_invalidate(ip_inputs(IP_CASES[14])); return r.generation; }()) == 0, "FB-B2 value: ip row 14: generation");
static_assert(([]{ const Plan r = plan_invalidate(ip_inputs(IP_CASES[14])); return fx_digest(r); }()) == 0xEC32669A74FCAE65ULL, "FB-B2 value: ip row 14: FNV digest of both records");
static_assert(text_is("INVALIDATE REFUSED - profile is now NOT_CAPTURED; nothing written", []{ const Plan r = plan_invalidate(ip_inputs(IP_CASES[14])); return r.text; }()), "FB-B2 text: ip row 14: text");
static_assert(([]{ const Plan r = plan_invalidate(ip_inputs(IP_CASES[15])); return (uint64_t) r.code | ((uint64_t) r.op << 8); }()) == 5, "FB-B2 value: ip row 15: code | op << 8");
static_assert(([]{ const Plan r = plan_invalidate(ip_inputs(IP_CASES[15])); return r.generation; }()) == 0, "FB-B2 value: ip row 15: generation");
static_assert(([]{ const Plan r = plan_invalidate(ip_inputs(IP_CASES[15])); return fx_digest(r); }()) == 0xEC32669A74FCAE65ULL, "FB-B2 value: ip row 15: FNV digest of both records");
static_assert(text_is("INVALIDATE REFUSED - profile is now PROFILE_LOST; nothing written", []{ const Plan r = plan_invalidate(ip_inputs(IP_CASES[15])); return r.text; }()), "FB-B2 text: ip row 15: text");
static_assert(([]{ const Plan r = plan_invalidate(ip_inputs(IP_CASES[16])); return (uint64_t) r.code | ((uint64_t) r.op << 8); }()) == 5, "FB-B2 value: ip row 16: code | op << 8");
static_assert(([]{ const Plan r = plan_invalidate(ip_inputs(IP_CASES[16])); return r.generation; }()) == 0, "FB-B2 value: ip row 16: generation");
static_assert(([]{ const Plan r = plan_invalidate(ip_inputs(IP_CASES[16])); return fx_digest(r); }()) == 0xEC32669A74FCAE65ULL, "FB-B2 value: ip row 16: FNV digest of both records");
static_assert(text_is("INVALIDATE REFUSED - profile is now PROFILE_STALE; nothing written", []{ const Plan r = plan_invalidate(ip_inputs(IP_CASES[16])); return r.text; }()), "FB-B2 text: ip row 16: text");
static_assert(([]{ const Plan r = plan_invalidate(ip_inputs(IP_CASES[17])); return (uint64_t) r.code | ((uint64_t) r.op << 8); }()) == 5, "FB-B2 value: ip row 17: code | op << 8");
static_assert(([]{ const Plan r = plan_invalidate(ip_inputs(IP_CASES[17])); return r.generation; }()) == 0, "FB-B2 value: ip row 17: generation");
static_assert(([]{ const Plan r = plan_invalidate(ip_inputs(IP_CASES[17])); return fx_digest(r); }()) == 0xEC32669A74FCAE65ULL, "FB-B2 value: ip row 17: FNV digest of both records");
static_assert(text_is("INVALIDATE REFUSED - profile is now PROFILE_STALE; nothing written", []{ const Plan r = plan_invalidate(ip_inputs(IP_CASES[17])); return r.text; }()), "FB-B2 text: ip row 17: text");
static_assert(([]{ const Plan r = plan_invalidate(ip_inputs(IP_CASES[18])); return (uint64_t) r.code | ((uint64_t) r.op << 8); }()) == 5, "FB-B2 value: ip row 18: code | op << 8");
static_assert(([]{ const Plan r = plan_invalidate(ip_inputs(IP_CASES[18])); return r.generation; }()) == 0, "FB-B2 value: ip row 18: generation");
static_assert(([]{ const Plan r = plan_invalidate(ip_inputs(IP_CASES[18])); return fx_digest(r); }()) == 0xEC32669A74FCAE65ULL, "FB-B2 value: ip row 18: FNV digest of both records");
static_assert(text_is("INVALIDATE REFUSED - profile is now UNREADABLE; nothing written", []{ const Plan r = plan_invalidate(ip_inputs(IP_CASES[18])); return r.text; }()), "FB-B2 text: ip row 18: text");
static_assert(([]{ const Plan r = plan_invalidate(ip_inputs(IP_CASES[19])); return (uint64_t) r.code | ((uint64_t) r.op << 8); }()) == 5, "FB-B2 value: ip row 19: code | op << 8");
static_assert(([]{ const Plan r = plan_invalidate(ip_inputs(IP_CASES[19])); return r.generation; }()) == 0, "FB-B2 value: ip row 19: generation");
static_assert(([]{ const Plan r = plan_invalidate(ip_inputs(IP_CASES[19])); return fx_digest(r); }()) == 0xEC32669A74FCAE65ULL, "FB-B2 value: ip row 19: FNV digest of both records");
static_assert(text_is("INVALIDATE REFUSED - profile is now UNREADABLE; nothing written", []{ const Plan r = plan_invalidate(ip_inputs(IP_CASES[19])); return r.text; }()), "FB-B2 text: ip row 19: text");
static_assert(([]{ const Plan r = plan_invalidate(ip_inputs(IP_CASES[20])); return (uint64_t) r.code | ((uint64_t) r.op << 8); }()) == 3, "FB-B2 value: ip row 20: code | op << 8");
static_assert(([]{ const Plan r = plan_invalidate(ip_inputs(IP_CASES[20])); return r.generation; }()) == 0, "FB-B2 value: ip row 20: generation");
static_assert(([]{ const Plan r = plan_invalidate(ip_inputs(IP_CASES[20])); return fx_digest(r); }()) == 0xEC32669A74FCAE65ULL, "FB-B2 value: ip row 20: FNV digest of both records");
static_assert(text_is("INVALIDATE REFUSED - previous Fallback Profile write outcome unknown this boot - reboot to re-verify first", []{ const Plan r = plan_invalidate(ip_inputs(IP_CASES[20])); return r.text; }()), "FB-B2 text: ip row 20: text");
static_assert(([]{ const Plan r = plan_invalidate(ip_inputs(IP_CASES[21])); return (uint64_t) r.code | ((uint64_t) r.op << 8); }()) == 4, "FB-B2 value: ip row 21: code | op << 8");
static_assert(([]{ const Plan r = plan_invalidate(ip_inputs(IP_CASES[21])); return r.generation; }()) == 0, "FB-B2 value: ip row 21: generation");
static_assert(([]{ const Plan r = plan_invalidate(ip_inputs(IP_CASES[21])); return fx_digest(r); }()) == 0xEC32669A74FCAE65ULL, "FB-B2 value: ip row 21: FNV digest of both records");
static_assert(text_is("INVALIDATE REFUSED - stored profile read anomaly this boot; reboot to re-derive first", []{ const Plan r = plan_invalidate(ip_inputs(IP_CASES[21])); return r.text; }()), "FB-B2 text: ip row 21: text");
static_assert(([]{ const Plan r = plan_invalidate(ip_inputs(IP_CASES[22])); return (uint64_t) r.code | ((uint64_t) r.op << 8); }()) == 3, "FB-B2 value: ip row 22: code | op << 8");
static_assert(([]{ const Plan r = plan_invalidate(ip_inputs(IP_CASES[22])); return r.generation; }()) == 0, "FB-B2 value: ip row 22: generation");
static_assert(([]{ const Plan r = plan_invalidate(ip_inputs(IP_CASES[22])); return fx_digest(r); }()) == 0xEC32669A74FCAE65ULL, "FB-B2 value: ip row 22: FNV digest of both records");
static_assert(text_is("INVALIDATE REFUSED - previous Fallback Profile write outcome unknown this boot - reboot to re-verify first", []{ const Plan r = plan_invalidate(ip_inputs(IP_CASES[22])); return r.text; }()), "FB-B2 text: ip row 22: text");
static_assert(([]{ const Plan r = plan_invalidate(ip_inputs(IP_CASES[23])); return (uint64_t) r.code | ((uint64_t) r.op << 8); }()) == 10, "FB-B2 value: ip row 23: code | op << 8");
static_assert(([]{ const Plan r = plan_invalidate(ip_inputs(IP_CASES[23])); return r.generation; }()) == 0, "FB-B2 value: ip row 23: generation");
static_assert(([]{ const Plan r = plan_invalidate(ip_inputs(IP_CASES[23])); return fx_digest(r); }()) == 0xEC32669A74FCAE65ULL, "FB-B2 value: ip row 23: FNV digest of both records");
static_assert(text_is("INVALIDATE REFUSED - stored profile changed; nothing written", []{ const Plan r = plan_invalidate(ip_inputs(IP_CASES[23])); return r.text; }()), "FB-B2 text: ip row 23: text");
static_assert(([]{ const Plan r = plan_invalidate(ip_inputs(IP_CASES[24])); return (uint64_t) r.code | ((uint64_t) r.op << 8); }()) == 10, "FB-B2 value: ip row 24: code | op << 8");
static_assert(([]{ const Plan r = plan_invalidate(ip_inputs(IP_CASES[24])); return r.generation; }()) == 0, "FB-B2 value: ip row 24: generation");
static_assert(([]{ const Plan r = plan_invalidate(ip_inputs(IP_CASES[24])); return fx_digest(r); }()) == 0xEC32669A74FCAE65ULL, "FB-B2 value: ip row 24: FNV digest of both records");
static_assert(text_is("INVALIDATE REFUSED - stored profile changed; nothing written", []{ const Plan r = plan_invalidate(ip_inputs(IP_CASES[24])); return r.text; }()), "FB-B2 text: ip row 24: text");
static_assert(([]{ const Plan r = plan_invalidate(ip_inputs(IP_CASES[25])); return (uint64_t) r.code | ((uint64_t) r.op << 8); }()) == 10, "FB-B2 value: ip row 25: code | op << 8");
static_assert(([]{ const Plan r = plan_invalidate(ip_inputs(IP_CASES[25])); return r.generation; }()) == 0, "FB-B2 value: ip row 25: generation");
static_assert(([]{ const Plan r = plan_invalidate(ip_inputs(IP_CASES[25])); return fx_digest(r); }()) == 0xEC32669A74FCAE65ULL, "FB-B2 value: ip row 25: FNV digest of both records");
static_assert(text_is("INVALIDATE REFUSED - stored profile changed; nothing written", []{ const Plan r = plan_invalidate(ip_inputs(IP_CASES[25])); return r.text; }()), "FB-B2 text: ip row 25: text");
static_assert(([]{ const Plan r = plan_invalidate(ip_inputs(IP_CASES[26])); return (uint64_t) r.code | ((uint64_t) r.op << 8); }()) == 10, "FB-B2 value: ip row 26: code | op << 8");
static_assert(([]{ const Plan r = plan_invalidate(ip_inputs(IP_CASES[26])); return r.generation; }()) == 0, "FB-B2 value: ip row 26: generation");
static_assert(([]{ const Plan r = plan_invalidate(ip_inputs(IP_CASES[26])); return fx_digest(r); }()) == 0xEC32669A74FCAE65ULL, "FB-B2 value: ip row 26: FNV digest of both records");
static_assert(text_is("INVALIDATE REFUSED - stored profile changed; nothing written", []{ const Plan r = plan_invalidate(ip_inputs(IP_CASES[26])); return r.text; }()), "FB-B2 text: ip row 26: text");
static_assert(([]{ const Plan r = plan_invalidate(ip_inputs(IP_CASES[27])); return (uint64_t) r.code | ((uint64_t) r.op << 8); }()) == 10, "FB-B2 value: ip row 27: code | op << 8");
static_assert(([]{ const Plan r = plan_invalidate(ip_inputs(IP_CASES[27])); return r.generation; }()) == 0, "FB-B2 value: ip row 27: generation");
static_assert(([]{ const Plan r = plan_invalidate(ip_inputs(IP_CASES[27])); return fx_digest(r); }()) == 0xEC32669A74FCAE65ULL, "FB-B2 value: ip row 27: FNV digest of both records");
static_assert(text_is("INVALIDATE REFUSED - stored profile changed; nothing written", []{ const Plan r = plan_invalidate(ip_inputs(IP_CASES[27])); return r.text; }()), "FB-B2 text: ip row 27: text");
static_assert(([]{ const Plan r = plan_invalidate(ip_inputs(IP_CASES[28])); return (uint64_t) r.code | ((uint64_t) r.op << 8); }()) == 10, "FB-B2 value: ip row 28: code | op << 8");
static_assert(([]{ const Plan r = plan_invalidate(ip_inputs(IP_CASES[28])); return r.generation; }()) == 0, "FB-B2 value: ip row 28: generation");
static_assert(([]{ const Plan r = plan_invalidate(ip_inputs(IP_CASES[28])); return fx_digest(r); }()) == 0xEC32669A74FCAE65ULL, "FB-B2 value: ip row 28: FNV digest of both records");
static_assert(text_is("INVALIDATE REFUSED - stored profile changed; nothing written", []{ const Plan r = plan_invalidate(ip_inputs(IP_CASES[28])); return r.text; }()), "FB-B2 text: ip row 28: text");
static_assert(([]{ const Plan r = plan_invalidate(ip_inputs(IP_CASES[29])); return (uint64_t) r.code | ((uint64_t) r.op << 8); }()) == 8, "FB-B2 value: ip row 29: code | op << 8");
static_assert(([]{ const Plan r = plan_invalidate(ip_inputs(IP_CASES[29])); return r.generation; }()) == 0, "FB-B2 value: ip row 29: generation");
static_assert(([]{ const Plan r = plan_invalidate(ip_inputs(IP_CASES[29])); return fx_digest(r); }()) == 0xEC32669A74FCAE65ULL, "FB-B2 value: ip row 29: FNV digest of both records");
static_assert(text_is("INVALIDATE REFUSED - profile generation is not ahead of this boot's generation high-water mark; reboot to re-verify", []{ const Plan r = plan_invalidate(ip_inputs(IP_CASES[29])); return r.text; }()), "FB-B2 text: ip row 29: text");
static_assert(([]{ const Plan r = plan_invalidate(ip_inputs(IP_CASES[30])); return (uint64_t) r.code | ((uint64_t) r.op << 8); }()) == 8, "FB-B2 value: ip row 30: code | op << 8");
static_assert(([]{ const Plan r = plan_invalidate(ip_inputs(IP_CASES[30])); return r.generation; }()) == 0, "FB-B2 value: ip row 30: generation");
static_assert(([]{ const Plan r = plan_invalidate(ip_inputs(IP_CASES[30])); return fx_digest(r); }()) == 0xEC32669A74FCAE65ULL, "FB-B2 value: ip row 30: FNV digest of both records");
static_assert(text_is("INVALIDATE REFUSED - profile generation is not ahead of this boot's generation high-water mark; reboot to re-verify", []{ const Plan r = plan_invalidate(ip_inputs(IP_CASES[30])); return r.text; }()), "FB-B2 text: ip row 30: text");
static_assert(([]{ const Plan r = plan_invalidate(ip_inputs(IP_CASES[31])); return (uint64_t) r.code | ((uint64_t) r.op << 8); }()) == 8, "FB-B2 value: ip row 31: code | op << 8");
static_assert(([]{ const Plan r = plan_invalidate(ip_inputs(IP_CASES[31])); return r.generation; }()) == 0, "FB-B2 value: ip row 31: generation");
static_assert(([]{ const Plan r = plan_invalidate(ip_inputs(IP_CASES[31])); return fx_digest(r); }()) == 0xEC32669A74FCAE65ULL, "FB-B2 value: ip row 31: FNV digest of both records");
static_assert(text_is("INVALIDATE REFUSED - generation counter exhausted", []{ const Plan r = plan_invalidate(ip_inputs(IP_CASES[31])); return r.text; }()), "FB-B2 text: ip row 31: text");
static_assert(([]{ const Plan r = plan_invalidate(ip_inputs(IP_CASES[32])); return (uint64_t) r.code | ((uint64_t) r.op << 8); }()) == 8, "FB-B2 value: ip row 32: code | op << 8");
static_assert(([]{ const Plan r = plan_invalidate(ip_inputs(IP_CASES[32])); return r.generation; }()) == 0, "FB-B2 value: ip row 32: generation");
static_assert(([]{ const Plan r = plan_invalidate(ip_inputs(IP_CASES[32])); return fx_digest(r); }()) == 0xEC32669A74FCAE65ULL, "FB-B2 value: ip row 32: FNV digest of both records");
static_assert(text_is("INVALIDATE REFUSED - generation counter exhausted", []{ const Plan r = plan_invalidate(ip_inputs(IP_CASES[32])); return r.text; }()), "FB-B2 text: ip row 32: text");
static_assert(([]{ const Plan r = plan_invalidate(ip_inputs(IP_CASES[33])); return (uint64_t) r.code | ((uint64_t) r.op << 8); }()) == 8, "FB-B2 value: ip row 33: code | op << 8");
static_assert(([]{ const Plan r = plan_invalidate(ip_inputs(IP_CASES[33])); return r.generation; }()) == 0, "FB-B2 value: ip row 33: generation");
static_assert(([]{ const Plan r = plan_invalidate(ip_inputs(IP_CASES[33])); return fx_digest(r); }()) == 0xEC32669A74FCAE65ULL, "FB-B2 value: ip row 33: FNV digest of both records");
static_assert(text_is("INVALIDATE REFUSED - profile generation is not ahead of this boot's generation high-water mark; reboot to re-verify", []{ const Plan r = plan_invalidate(ip_inputs(IP_CASES[33])); return r.text; }()), "FB-B2 text: ip row 33: text");
static_assert(([]{ const Plan r = plan_invalidate(ip_inputs(IP_CASES[34])); return (uint64_t) r.code | ((uint64_t) r.op << 8); }()) == 8, "FB-B2 value: ip row 34: code | op << 8");
static_assert(([]{ const Plan r = plan_invalidate(ip_inputs(IP_CASES[34])); return r.generation; }()) == 0, "FB-B2 value: ip row 34: generation");
static_assert(([]{ const Plan r = plan_invalidate(ip_inputs(IP_CASES[34])); return fx_digest(r); }()) == 0xEC32669A74FCAE65ULL, "FB-B2 value: ip row 34: FNV digest of both records");
static_assert(text_is("INVALIDATE REFUSED - profile generation is not ahead of this boot's generation high-water mark; reboot to re-verify", []{ const Plan r = plan_invalidate(ip_inputs(IP_CASES[34])); return r.text; }()), "FB-B2 text: ip row 34: text");
static_assert(text_is("", []{ const FxP pr = fx_p(0); return replace_corrupt_log_text(pr.load, pr.p, pr.len, 0); }()), "FB-B2 text: replace_corrupt_log_text stored profile kind 0 part 0");
static_assert(text_is("", []{ const FxP pr = fx_p(0); return replace_corrupt_log_text(pr.load, pr.p, pr.len, 1); }()), "FB-B2 text: replace_corrupt_log_text stored profile kind 0 part 1");
static_assert(text_is("", []{ const FxP pr = fx_p(0); return replace_corrupt_log_text(pr.load, pr.p, pr.len, 2); }()), "FB-B2 text: replace_corrupt_log_text stored profile kind 0 part 2");
static_assert(text_is("REPLACE CORRUPT discards stored profile bytes 0-47: 504643450100600007000000803BB16A00000200401FF401A00FB80BD007E803640014000000320064001E0001000000", []{ const FxP pr = fx_p(1); return replace_corrupt_log_text(pr.load, pr.p, pr.len, 0); }()), "FB-B2 text: replace_corrupt_log_text stored profile kind 1 part 0");
static_assert(text_is("REPLACE CORRUPT discards stored profile bytes 48-95: 010000000000010011000100010000001202E803400634081A09B900401F01000000000000000000A3DBF72DFAA452D8", []{ const FxP pr = fx_p(1); return replace_corrupt_log_text(pr.load, pr.p, pr.len, 1); }()), "FB-B2 text: replace_corrupt_log_text stored profile kind 1 part 1");
static_assert(text_is("", []{ const FxP pr = fx_p(1); return replace_corrupt_log_text(pr.load, pr.p, pr.len, 2); }()), "FB-B2 text: replace_corrupt_log_text stored profile kind 1 part 2");
static_assert(text_is("REPLACE CORRUPT discards stored profile bytes 0-47: 50464345010060000B000000803BB16A00000200401FF401A00FB80BD007E803640014000000320064001E0001000000", []{ const FxP pr = fx_p(4); return replace_corrupt_log_text(pr.load, pr.p, pr.len, 0); }()), "FB-B2 text: replace_corrupt_log_text stored profile kind 4 part 0");
static_assert(text_is("REPLACE CORRUPT discards stored profile bytes 48-95: 010000000000010011000100010000001202E803400634081A09B900401F01000000000000000000AE9C3676069EC9CD", []{ const FxP pr = fx_p(4); return replace_corrupt_log_text(pr.load, pr.p, pr.len, 1); }()), "FB-B2 text: replace_corrupt_log_text stored profile kind 4 part 1");
static_assert(text_is("", []{ const FxP pr = fx_p(4); return replace_corrupt_log_text(pr.load, pr.p, pr.len, 2); }()), "FB-B2 text: replace_corrupt_log_text stored profile kind 4 part 2");
static_assert(text_is("REPLACE CORRUPT discards a stored profile of the wrong size, stored length 40", []{ const FxP pr = fx_p(5); return replace_corrupt_log_text(pr.load, pr.p, pr.len, 0); }()), "FB-B2 text: replace_corrupt_log_text stored profile kind 5 part 0");
static_assert(text_is("", []{ const FxP pr = fx_p(5); return replace_corrupt_log_text(pr.load, pr.p, pr.len, 1); }()), "FB-B2 text: replace_corrupt_log_text stored profile kind 5 part 1");
static_assert(text_is("", []{ const FxP pr = fx_p(5); return replace_corrupt_log_text(pr.load, pr.p, pr.len, 2); }()), "FB-B2 text: replace_corrupt_log_text stored profile kind 5 part 2");
static_assert(text_is("", []{ const FxP pr = fx_p(6); return replace_corrupt_log_text(pr.load, pr.p, pr.len, 0); }()), "FB-B2 text: replace_corrupt_log_text stored profile kind 6 part 0");
static_assert(text_is("", []{ const FxP pr = fx_p(6); return replace_corrupt_log_text(pr.load, pr.p, pr.len, 1); }()), "FB-B2 text: replace_corrupt_log_text stored profile kind 6 part 1");
static_assert(text_is("", []{ const FxP pr = fx_p(6); return replace_corrupt_log_text(pr.load, pr.p, pr.len, 2); }()), "FB-B2 text: replace_corrupt_log_text stored profile kind 6 part 2");
static_assert((replace_corrupt_log_text(ecco_fallback::LOAD_WRONG_SIZE, ecco_fallback::FallbackProfileV1{}, 4294967295u, 0).size()) == 85, "FB-B2 value: replace_corrupt_log_text: a wrong-size record of 4294967295 bytes");
static_assert((first_non_ok(0, 0)) == 0, "FB-B2 value: first_non_ok(0, 0)");
static_assert((first_non_ok(5, 0)) == 5, "FB-B2 value: first_non_ok(5, 0)");
static_assert((first_non_ok(0, 5)) == 5, "FB-B2 value: first_non_ok(0, 5)");
static_assert((first_non_ok(-1, 7)) == 4294967295u, "FB-B2 value: first_non_ok(-1, 7)");
static_assert((first_non_ok(4359, 4356)) == 4359, "FB-B2 value: first_non_ok(4359, 4356)");
static_assert((first_non_ok(-1, -1)) == 4294967295u, "FB-B2 value: first_non_ok(-1, -1)");
static_assert((first_non_ok(-2147483647, 0)) == 2147483649u, "FB-B2 value: first_non_ok(-2147483647, 0)");
static_assert((first_non_ok(0, -2147483647)) == 2147483649u, "FB-B2 value: first_non_ok(0, -2147483647)");
static_assert((total_us(0u, 0u)) == 0, "FB-B2 value: total_us(0u, 0u)");
static_assert((total_us(5u, 7u)) == 12, "FB-B2 value: total_us(5u, 7u)");
static_assert((total_us(4294967295u, 1u)) == 0, "FB-B2 value: total_us(4294967295u, 1u)");
static_assert((total_us(4294967295u, 4294967295u)) == 4294967294u, "FB-B2 value: total_us(4294967295u, 4294967295u)");
static_assert((total_us(2147483648u, 2147483648u)) == 0, "FB-B2 value: total_us(2147483648u, 2147483648u)");
static_assert((total_us(1u, 4294967295u)) == 0, "FB-B2 value: total_us(1u, 4294967295u)");
static_assert(text_is("SAVED - known-good profile generation 1 saved (verified this boot)", txn_outcome_text(1, 1, []{ ecco_fbdurable::TxnResult r{}; r.w.err = 0; r.w.rb_class = 0; r.w.outcome = 1; r.w.us = 0u; r.p.err = 0; r.p.rb_class = 0; r.p.outcome = 1; r.p.us = 0u; r.witness_advanced = 0; r.refusal = 0; return r; }(), 1u, 0u)), "FB-B2 text: txn_outcome_text cell 0 (op 1, outcome 1, w err 0 rb 0, p err 0 rb 0, adv 0, ref 0, g 1/0)");
static_assert(text_is("SAVED - known-good profile generation 7 saved (verified this boot)", txn_outcome_text(1, 1, []{ ecco_fbdurable::TxnResult r{}; r.w.err = 0; r.w.rb_class = 0; r.w.outcome = 1; r.w.us = 0u; r.p.err = 0; r.p.rb_class = 0; r.p.outcome = 1; r.p.us = 0u; r.witness_advanced = 0; r.refusal = 0; return r; }(), 7u, 6u)), "FB-B2 text: txn_outcome_text cell 1 (op 1, outcome 1, w err 0 rb 0, p err 0 rb 0, adv 0, ref 0, g 7/6)");
static_assert(text_is("SAVED - known-good profile generation 4294967295 saved (verified this boot)", txn_outcome_text(1, 1, []{ ecco_fbdurable::TxnResult r{}; r.w.err = 0; r.w.rb_class = 0; r.w.outcome = 1; r.w.us = 0u; r.p.err = 0; r.p.rb_class = 0; r.p.outcome = 1; r.p.us = 0u; r.witness_advanced = 0; r.refusal = 0; return r; }(), 4294967295u, 4294967294u)), "FB-B2 text: txn_outcome_text cell 2 (op 1, outcome 1, w err 0 rb 0, p err 0 rb 0, adv 0, ref 0, g 4294967295/4294967294)");
static_assert(text_is("SAVE NOT COMMITTED - storage refused the write (E1107); nothing changed", txn_outcome_text(1, 2, []{ ecco_fbdurable::TxnResult r{}; r.w.err = 4359; r.w.rb_class = 2; r.w.outcome = 2; r.w.us = 0u; r.p.err = 0; r.p.rb_class = 0; r.p.outcome = 3; r.p.us = 0u; r.witness_advanced = 0; r.refusal = 0; return r; }(), 0u, 7u)), "FB-B2 text: txn_outcome_text cell 3 (op 1, outcome 2, w err 4359 rb 2, p err 0 rb 0, adv 0, ref 0, g 0/7)");
static_assert(text_is("SAVE NOT COMMITTED - storage refused the write (E1104); nothing changed", txn_outcome_text(1, 2, []{ ecco_fbdurable::TxnResult r{}; r.w.err = 4356; r.w.rb_class = 2; r.w.outcome = 2; r.w.us = 0u; r.p.err = 0; r.p.rb_class = 0; r.p.outcome = 3; r.p.us = 0u; r.witness_advanced = 0; r.refusal = 0; return r; }(), 0u, 4294967295u)), "FB-B2 text: txn_outcome_text cell 4 (op 1, outcome 2, w err 4356 rb 2, p err 0 rb 0, adv 0, ref 0, g 0/4294967295)");
static_assert(text_is("SAVE NOT COMMITTED - storage refused the write (E1101); nothing changed", txn_outcome_text(1, 2, []{ ecco_fbdurable::TxnResult r{}; r.w.err = 4353; r.w.rb_class = 2; r.w.outcome = 2; r.w.us = 0u; r.p.err = 0; r.p.rb_class = 0; r.p.outcome = 3; r.p.us = 0u; r.witness_advanced = 0; r.refusal = 0; return r; }(), 0u, 1u)), "FB-B2 text: txn_outcome_text cell 5 (op 1, outcome 2, w err 4353 rb 2, p err 0 rb 0, adv 0, ref 0, g 0/1)");
static_assert(text_is("SAVE NOT COMMITTED - witness advanced; profile unchanged; stored profile is now out of step - review and save again", txn_outcome_text(1, 2, []{ ecco_fbdurable::TxnResult r{}; r.w.err = 0; r.w.rb_class = 0; r.w.outcome = 1; r.w.us = 0u; r.p.err = 4359; r.p.rb_class = 2; r.p.outcome = 2; r.p.us = 0u; r.witness_advanced = 1; r.refusal = 0; return r; }(), 8u, 7u)), "FB-B2 text: txn_outcome_text cell 6 (op 1, outcome 2, w err 0 rb 0, p err 4359 rb 2, adv 1, ref 0, g 8/7)");
static_assert(text_is("SAVE OUTCOME UNKNOWN - storage reported E1102/OTHER_BYTES; reboot the dongle (when no temporary operation is active) to re-verify; saving disabled until then", txn_outcome_text(1, 0, []{ ecco_fbdurable::TxnResult r{}; r.w.err = 4354; r.w.rb_class = 3; r.w.outcome = 0; r.w.us = 0u; r.p.err = 0; r.p.rb_class = 0; r.p.outcome = 3; r.p.us = 0u; r.witness_advanced = 0; r.refusal = 0; return r; }(), 8u, 7u)), "FB-B2 text: txn_outcome_text cell 7 (op 1, outcome 0, w err 4354 rb 3, p err 0 rb 0, adv 0, ref 0, g 8/7)");
static_assert(text_is("SAVE OUTCOME UNKNOWN - storage reported -/INTENDED; reboot the dongle (when no temporary operation is active) to re-verify; saving disabled until then", txn_outcome_text(1, 0, []{ ecco_fbdurable::TxnResult r{}; r.w.err = 0; r.w.rb_class = 1; r.w.outcome = 0; r.w.us = 0u; r.p.err = 0; r.p.rb_class = 0; r.p.outcome = 3; r.p.us = 0u; r.witness_advanced = 0; r.refusal = 0; return r; }(), 8u, 7u)), "FB-B2 text: txn_outcome_text cell 8 (op 1, outcome 0, w err 0 rb 1, p err 0 rb 0, adv 0, ref 0, g 8/7)");
static_assert(text_is("SAVE OUTCOME UNKNOWN - storage reported EFFFFFFFF/READ_ERROR; reboot the dongle (when no temporary operation is active) to re-verify; saving disabled until then", txn_outcome_text(1, 0, []{ ecco_fbdurable::TxnResult r{}; r.w.err = -1; r.w.rb_class = 6; r.w.outcome = 0; r.w.us = 0u; r.p.err = 0; r.p.rb_class = 0; r.p.outcome = 3; r.p.us = 0u; r.witness_advanced = 0; r.refusal = 0; return r; }(), 8u, 7u)), "FB-B2 text: txn_outcome_text cell 9 (op 1, outcome 0, w err -1 rb 6, p err 0 rb 0, adv 0, ref 0, g 8/7)");
static_assert(text_is("SAVE OUTCOME UNKNOWN - storage reported E103/UNAVAILABLE; reboot the dongle (when no temporary operation is active) to re-verify; saving disabled until then", txn_outcome_text(1, 0, []{ ecco_fbdurable::TxnResult r{}; r.w.err = 259; r.w.rb_class = 7; r.w.outcome = 0; r.w.us = 0u; r.p.err = 0; r.p.rb_class = 0; r.p.outcome = 3; r.p.us = 0u; r.witness_advanced = 0; r.refusal = 0; return r; }(), 8u, 7u)), "FB-B2 text: txn_outcome_text cell 10 (op 1, outcome 0, w err 259 rb 7, p err 0 rb 0, adv 0, ref 0, g 8/7)");
static_assert(text_is("SAVE OUTCOME UNKNOWN - storage reported E1105/WRONG_SIZE; reboot the dongle (when no temporary operation is active) to re-verify; saving disabled until then", txn_outcome_text(1, 0, []{ ecco_fbdurable::TxnResult r{}; r.w.err = 0; r.w.rb_class = 0; r.w.outcome = 1; r.w.us = 0u; r.p.err = 4357; r.p.rb_class = 5; r.p.outcome = 0; r.p.us = 0u; r.witness_advanced = 0; r.refusal = 0; return r; }(), 8u, 7u)), "FB-B2 text: txn_outcome_text cell 11 (op 1, outcome 0, w err 0 rb 0, p err 4357 rb 5, adv 0, ref 0, g 8/7)");
static_assert(text_is("SAVE OUTCOME UNKNOWN - storage reported -/ABSENT_UNEXPECTED; reboot the dongle (when no temporary operation is active) to re-verify; saving disabled until then", txn_outcome_text(1, 0, []{ ecco_fbdurable::TxnResult r{}; r.w.err = 0; r.w.rb_class = 0; r.w.outcome = 1; r.w.us = 0u; r.p.err = 0; r.p.rb_class = 4; r.p.outcome = 0; r.p.us = 0u; r.witness_advanced = 0; r.refusal = 0; return r; }(), 8u, 7u)), "FB-B2 text: txn_outcome_text cell 12 (op 1, outcome 0, w err 0 rb 0, p err 0 rb 4, adv 0, ref 0, g 8/7)");
static_assert(text_is("SAVE OUTCOME UNKNOWN - storage reported E1102/OTHER_BYTES; reboot the dongle (when no temporary operation is active) to re-verify; saving disabled until then", txn_outcome_text(1, 0, []{ ecco_fbdurable::TxnResult r{}; r.w.err = 4354; r.w.rb_class = 3; r.w.outcome = 0; r.w.us = 0u; r.p.err = 0; r.p.rb_class = 0; r.p.outcome = 3; r.p.us = 0u; r.witness_advanced = 1; r.refusal = 0; return r; }(), 8u, 7u)), "FB-B2 text: txn_outcome_text cell 13 (op 1, outcome 0, w err 4354 rb 3, p err 0 rb 0, adv 1, ref 0, g 8/7)");
static_assert(text_is("SAVE REFUSED - internal: write refused for an unknown reason; nothing written", txn_outcome_text(1, 3, []{ ecco_fbdurable::TxnResult r{}; r.w.err = 0; r.w.rb_class = 0; r.w.outcome = 0; r.w.us = 0u; r.p.err = 0; r.p.rb_class = 0; r.p.outcome = 3; r.p.us = 0u; r.witness_advanced = 0; r.refusal = 0; return r; }(), 8u, 7u)), "FB-B2 text: txn_outcome_text cell 14 (op 1, outcome 3, w err 0 rb 0, p err 0 rb 0, adv 0, ref 0, g 8/7)");
static_assert(text_is("SAVE REFUSED - internal: write refused for an unknown reason; nothing written", txn_outcome_text(1, 3, []{ ecco_fbdurable::TxnResult r{}; r.w.err = 0; r.w.rb_class = 0; r.w.outcome = 0; r.w.us = 0u; r.p.err = 0; r.p.rb_class = 0; r.p.outcome = 3; r.p.us = 0u; r.witness_advanced = 0; r.refusal = 1; return r; }(), 8u, 7u)), "FB-B2 text: txn_outcome_text cell 15 (op 1, outcome 3, w err 0 rb 0, p err 0 rb 0, adv 0, ref 1, g 8/7)");
static_assert(text_is("SAVE REFUSED - previous save outcome unknown this boot - reboot to re-verify first", txn_outcome_text(1, 3, []{ ecco_fbdurable::TxnResult r{}; r.w.err = 0; r.w.rb_class = 0; r.w.outcome = 0; r.w.us = 0u; r.p.err = 0; r.p.rb_class = 0; r.p.outcome = 3; r.p.us = 0u; r.witness_advanced = 0; r.refusal = 2; return r; }(), 8u, 7u)), "FB-B2 text: txn_outcome_text cell 16 (op 1, outcome 3, w err 0 rb 0, p err 0 rb 0, adv 0, ref 2, g 8/7)");
static_assert(text_is("SAVE REFUSED - internal: built record did not validate; nothing written", txn_outcome_text(1, 3, []{ ecco_fbdurable::TxnResult r{}; r.w.err = 0; r.w.rb_class = 0; r.w.outcome = 0; r.w.us = 0u; r.p.err = 0; r.p.rb_class = 0; r.p.outcome = 3; r.p.us = 0u; r.witness_advanced = 0; r.refusal = 3; return r; }(), 8u, 7u)), "FB-B2 text: txn_outcome_text cell 17 (op 1, outcome 3, w err 0 rb 0, p err 0 rb 0, adv 0, ref 3, g 8/7)");
static_assert(text_is("SAVE REFUSED - storage unavailable - nothing saved", txn_outcome_text(1, 3, []{ ecco_fbdurable::TxnResult r{}; r.w.err = 0; r.w.rb_class = 0; r.w.outcome = 0; r.w.us = 0u; r.p.err = 0; r.p.rb_class = 0; r.p.outcome = 3; r.p.us = 0u; r.witness_advanced = 0; r.refusal = 4; return r; }(), 8u, 7u)), "FB-B2 text: txn_outcome_text cell 18 (op 1, outcome 3, w err 0 rb 0, p err 0 rb 0, adv 0, ref 4, g 8/7)");
static_assert(text_is("SAVE REFUSED - storage not healthy - nothing saved", txn_outcome_text(1, 3, []{ ecco_fbdurable::TxnResult r{}; r.w.err = 0; r.w.rb_class = 0; r.w.outcome = 0; r.w.us = 0u; r.p.err = 0; r.p.rb_class = 0; r.p.outcome = 3; r.p.us = 0u; r.witness_advanced = 0; r.refusal = 5; return r; }(), 8u, 7u)), "FB-B2 text: txn_outcome_text cell 19 (op 1, outcome 3, w err 0 rb 0, p err 0 rb 0, adv 0, ref 5, g 8/7)");
static_assert(text_is("SAVE REFUSED - internal: write refused for an unknown reason; nothing written", txn_outcome_text(1, 3, []{ ecco_fbdurable::TxnResult r{}; r.w.err = 0; r.w.rb_class = 0; r.w.outcome = 0; r.w.us = 0u; r.p.err = 0; r.p.rb_class = 0; r.p.outcome = 3; r.p.us = 0u; r.witness_advanced = 0; r.refusal = 6; return r; }(), 8u, 7u)), "FB-B2 text: txn_outcome_text cell 20 (op 1, outcome 3, w err 0 rb 0, p err 0 rb 0, adv 0, ref 6, g 8/7)");
static_assert(text_is("SAVE OUTCOME UNKNOWN - storage reported -/NOT_READ; reboot the dongle (when no temporary operation is active) to re-verify; saving disabled until then", txn_outcome_text(1, 9, []{ ecco_fbdurable::TxnResult r{}; r.w.err = 0; r.w.rb_class = 0; r.w.outcome = 0; r.w.us = 0u; r.p.err = 0; r.p.rb_class = 0; r.p.outcome = 3; r.p.us = 0u; r.witness_advanced = 0; r.refusal = 0; return r; }(), 8u, 7u)), "FB-B2 text: txn_outcome_text cell 21 (op 1, outcome 9, w err 0 rb 0, p err 0 rb 0, adv 0, ref 0, g 8/7)");
static_assert(text_is("SAVED - known-good profile generation 1 saved (verified this boot)", txn_outcome_text(3, 1, []{ ecco_fbdurable::TxnResult r{}; r.w.err = 0; r.w.rb_class = 0; r.w.outcome = 1; r.w.us = 0u; r.p.err = 0; r.p.rb_class = 0; r.p.outcome = 1; r.p.us = 0u; r.witness_advanced = 0; r.refusal = 0; return r; }(), 1u, 0u)), "FB-B2 text: txn_outcome_text cell 22 (op 3, outcome 1, w err 0 rb 0, p err 0 rb 0, adv 0, ref 0, g 1/0)");
static_assert(text_is("SAVED - known-good profile generation 7 saved (verified this boot)", txn_outcome_text(3, 1, []{ ecco_fbdurable::TxnResult r{}; r.w.err = 0; r.w.rb_class = 0; r.w.outcome = 1; r.w.us = 0u; r.p.err = 0; r.p.rb_class = 0; r.p.outcome = 1; r.p.us = 0u; r.witness_advanced = 0; r.refusal = 0; return r; }(), 7u, 6u)), "FB-B2 text: txn_outcome_text cell 23 (op 3, outcome 1, w err 0 rb 0, p err 0 rb 0, adv 0, ref 0, g 7/6)");
static_assert(text_is("SAVED - known-good profile generation 4294967295 saved (verified this boot)", txn_outcome_text(3, 1, []{ ecco_fbdurable::TxnResult r{}; r.w.err = 0; r.w.rb_class = 0; r.w.outcome = 1; r.w.us = 0u; r.p.err = 0; r.p.rb_class = 0; r.p.outcome = 1; r.p.us = 0u; r.witness_advanced = 0; r.refusal = 0; return r; }(), 4294967295u, 4294967294u)), "FB-B2 text: txn_outcome_text cell 24 (op 3, outcome 1, w err 0 rb 0, p err 0 rb 0, adv 0, ref 0, g 4294967295/4294967294)");
static_assert(text_is("SAVE NOT COMMITTED - storage refused the write (E1107); nothing changed", txn_outcome_text(3, 2, []{ ecco_fbdurable::TxnResult r{}; r.w.err = 4359; r.w.rb_class = 2; r.w.outcome = 2; r.w.us = 0u; r.p.err = 0; r.p.rb_class = 0; r.p.outcome = 3; r.p.us = 0u; r.witness_advanced = 0; r.refusal = 0; return r; }(), 0u, 7u)), "FB-B2 text: txn_outcome_text cell 25 (op 3, outcome 2, w err 4359 rb 2, p err 0 rb 0, adv 0, ref 0, g 0/7)");
static_assert(text_is("SAVE NOT COMMITTED - storage refused the write (E1104); nothing changed", txn_outcome_text(3, 2, []{ ecco_fbdurable::TxnResult r{}; r.w.err = 4356; r.w.rb_class = 2; r.w.outcome = 2; r.w.us = 0u; r.p.err = 0; r.p.rb_class = 0; r.p.outcome = 3; r.p.us = 0u; r.witness_advanced = 0; r.refusal = 0; return r; }(), 0u, 4294967295u)), "FB-B2 text: txn_outcome_text cell 26 (op 3, outcome 2, w err 4356 rb 2, p err 0 rb 0, adv 0, ref 0, g 0/4294967295)");
static_assert(text_is("SAVE NOT COMMITTED - storage refused the write (E1101); nothing changed", txn_outcome_text(3, 2, []{ ecco_fbdurable::TxnResult r{}; r.w.err = 4353; r.w.rb_class = 2; r.w.outcome = 2; r.w.us = 0u; r.p.err = 0; r.p.rb_class = 0; r.p.outcome = 3; r.p.us = 0u; r.witness_advanced = 0; r.refusal = 0; return r; }(), 0u, 1u)), "FB-B2 text: txn_outcome_text cell 27 (op 3, outcome 2, w err 4353 rb 2, p err 0 rb 0, adv 0, ref 0, g 0/1)");
static_assert(text_is("SAVE NOT COMMITTED - witness advanced; profile unchanged; stored profile is now out of step - review and save again", txn_outcome_text(3, 2, []{ ecco_fbdurable::TxnResult r{}; r.w.err = 0; r.w.rb_class = 0; r.w.outcome = 1; r.w.us = 0u; r.p.err = 4359; r.p.rb_class = 2; r.p.outcome = 2; r.p.us = 0u; r.witness_advanced = 1; r.refusal = 0; return r; }(), 8u, 7u)), "FB-B2 text: txn_outcome_text cell 28 (op 3, outcome 2, w err 0 rb 0, p err 4359 rb 2, adv 1, ref 0, g 8/7)");
static_assert(text_is("SAVE OUTCOME UNKNOWN - storage reported E1102/OTHER_BYTES; reboot the dongle (when no temporary operation is active) to re-verify; saving disabled until then", txn_outcome_text(3, 0, []{ ecco_fbdurable::TxnResult r{}; r.w.err = 4354; r.w.rb_class = 3; r.w.outcome = 0; r.w.us = 0u; r.p.err = 0; r.p.rb_class = 0; r.p.outcome = 3; r.p.us = 0u; r.witness_advanced = 0; r.refusal = 0; return r; }(), 8u, 7u)), "FB-B2 text: txn_outcome_text cell 29 (op 3, outcome 0, w err 4354 rb 3, p err 0 rb 0, adv 0, ref 0, g 8/7)");
static_assert(text_is("SAVE OUTCOME UNKNOWN - storage reported -/INTENDED; reboot the dongle (when no temporary operation is active) to re-verify; saving disabled until then", txn_outcome_text(3, 0, []{ ecco_fbdurable::TxnResult r{}; r.w.err = 0; r.w.rb_class = 1; r.w.outcome = 0; r.w.us = 0u; r.p.err = 0; r.p.rb_class = 0; r.p.outcome = 3; r.p.us = 0u; r.witness_advanced = 0; r.refusal = 0; return r; }(), 8u, 7u)), "FB-B2 text: txn_outcome_text cell 30 (op 3, outcome 0, w err 0 rb 1, p err 0 rb 0, adv 0, ref 0, g 8/7)");
static_assert(text_is("SAVE OUTCOME UNKNOWN - storage reported EFFFFFFFF/READ_ERROR; reboot the dongle (when no temporary operation is active) to re-verify; saving disabled until then", txn_outcome_text(3, 0, []{ ecco_fbdurable::TxnResult r{}; r.w.err = -1; r.w.rb_class = 6; r.w.outcome = 0; r.w.us = 0u; r.p.err = 0; r.p.rb_class = 0; r.p.outcome = 3; r.p.us = 0u; r.witness_advanced = 0; r.refusal = 0; return r; }(), 8u, 7u)), "FB-B2 text: txn_outcome_text cell 31 (op 3, outcome 0, w err -1 rb 6, p err 0 rb 0, adv 0, ref 0, g 8/7)");
static_assert(text_is("SAVE OUTCOME UNKNOWN - storage reported E103/UNAVAILABLE; reboot the dongle (when no temporary operation is active) to re-verify; saving disabled until then", txn_outcome_text(3, 0, []{ ecco_fbdurable::TxnResult r{}; r.w.err = 259; r.w.rb_class = 7; r.w.outcome = 0; r.w.us = 0u; r.p.err = 0; r.p.rb_class = 0; r.p.outcome = 3; r.p.us = 0u; r.witness_advanced = 0; r.refusal = 0; return r; }(), 8u, 7u)), "FB-B2 text: txn_outcome_text cell 32 (op 3, outcome 0, w err 259 rb 7, p err 0 rb 0, adv 0, ref 0, g 8/7)");
static_assert(text_is("SAVE OUTCOME UNKNOWN - storage reported E1105/WRONG_SIZE; reboot the dongle (when no temporary operation is active) to re-verify; saving disabled until then", txn_outcome_text(3, 0, []{ ecco_fbdurable::TxnResult r{}; r.w.err = 0; r.w.rb_class = 0; r.w.outcome = 1; r.w.us = 0u; r.p.err = 4357; r.p.rb_class = 5; r.p.outcome = 0; r.p.us = 0u; r.witness_advanced = 0; r.refusal = 0; return r; }(), 8u, 7u)), "FB-B2 text: txn_outcome_text cell 33 (op 3, outcome 0, w err 0 rb 0, p err 4357 rb 5, adv 0, ref 0, g 8/7)");
static_assert(text_is("SAVE OUTCOME UNKNOWN - storage reported -/ABSENT_UNEXPECTED; reboot the dongle (when no temporary operation is active) to re-verify; saving disabled until then", txn_outcome_text(3, 0, []{ ecco_fbdurable::TxnResult r{}; r.w.err = 0; r.w.rb_class = 0; r.w.outcome = 1; r.w.us = 0u; r.p.err = 0; r.p.rb_class = 4; r.p.outcome = 0; r.p.us = 0u; r.witness_advanced = 0; r.refusal = 0; return r; }(), 8u, 7u)), "FB-B2 text: txn_outcome_text cell 34 (op 3, outcome 0, w err 0 rb 0, p err 0 rb 4, adv 0, ref 0, g 8/7)");
static_assert(text_is("SAVE OUTCOME UNKNOWN - storage reported E1102/OTHER_BYTES; reboot the dongle (when no temporary operation is active) to re-verify; saving disabled until then", txn_outcome_text(3, 0, []{ ecco_fbdurable::TxnResult r{}; r.w.err = 4354; r.w.rb_class = 3; r.w.outcome = 0; r.w.us = 0u; r.p.err = 0; r.p.rb_class = 0; r.p.outcome = 3; r.p.us = 0u; r.witness_advanced = 1; r.refusal = 0; return r; }(), 8u, 7u)), "FB-B2 text: txn_outcome_text cell 35 (op 3, outcome 0, w err 4354 rb 3, p err 0 rb 0, adv 1, ref 0, g 8/7)");
static_assert(text_is("SAVE REFUSED - internal: write refused for an unknown reason; nothing written", txn_outcome_text(3, 3, []{ ecco_fbdurable::TxnResult r{}; r.w.err = 0; r.w.rb_class = 0; r.w.outcome = 0; r.w.us = 0u; r.p.err = 0; r.p.rb_class = 0; r.p.outcome = 3; r.p.us = 0u; r.witness_advanced = 0; r.refusal = 0; return r; }(), 8u, 7u)), "FB-B2 text: txn_outcome_text cell 36 (op 3, outcome 3, w err 0 rb 0, p err 0 rb 0, adv 0, ref 0, g 8/7)");
static_assert(text_is("SAVE REFUSED - internal: write refused for an unknown reason; nothing written", txn_outcome_text(3, 3, []{ ecco_fbdurable::TxnResult r{}; r.w.err = 0; r.w.rb_class = 0; r.w.outcome = 0; r.w.us = 0u; r.p.err = 0; r.p.rb_class = 0; r.p.outcome = 3; r.p.us = 0u; r.witness_advanced = 0; r.refusal = 1; return r; }(), 8u, 7u)), "FB-B2 text: txn_outcome_text cell 37 (op 3, outcome 3, w err 0 rb 0, p err 0 rb 0, adv 0, ref 1, g 8/7)");
static_assert(text_is("SAVE REFUSED - previous save outcome unknown this boot - reboot to re-verify first", txn_outcome_text(3, 3, []{ ecco_fbdurable::TxnResult r{}; r.w.err = 0; r.w.rb_class = 0; r.w.outcome = 0; r.w.us = 0u; r.p.err = 0; r.p.rb_class = 0; r.p.outcome = 3; r.p.us = 0u; r.witness_advanced = 0; r.refusal = 2; return r; }(), 8u, 7u)), "FB-B2 text: txn_outcome_text cell 38 (op 3, outcome 3, w err 0 rb 0, p err 0 rb 0, adv 0, ref 2, g 8/7)");
static_assert(text_is("SAVE REFUSED - internal: built record did not validate; nothing written", txn_outcome_text(3, 3, []{ ecco_fbdurable::TxnResult r{}; r.w.err = 0; r.w.rb_class = 0; r.w.outcome = 0; r.w.us = 0u; r.p.err = 0; r.p.rb_class = 0; r.p.outcome = 3; r.p.us = 0u; r.witness_advanced = 0; r.refusal = 3; return r; }(), 8u, 7u)), "FB-B2 text: txn_outcome_text cell 39 (op 3, outcome 3, w err 0 rb 0, p err 0 rb 0, adv 0, ref 3, g 8/7)");
static_assert(text_is("SAVE REFUSED - storage unavailable - nothing saved", txn_outcome_text(3, 3, []{ ecco_fbdurable::TxnResult r{}; r.w.err = 0; r.w.rb_class = 0; r.w.outcome = 0; r.w.us = 0u; r.p.err = 0; r.p.rb_class = 0; r.p.outcome = 3; r.p.us = 0u; r.witness_advanced = 0; r.refusal = 4; return r; }(), 8u, 7u)), "FB-B2 text: txn_outcome_text cell 40 (op 3, outcome 3, w err 0 rb 0, p err 0 rb 0, adv 0, ref 4, g 8/7)");
static_assert(text_is("SAVE REFUSED - storage not healthy - nothing saved", txn_outcome_text(3, 3, []{ ecco_fbdurable::TxnResult r{}; r.w.err = 0; r.w.rb_class = 0; r.w.outcome = 0; r.w.us = 0u; r.p.err = 0; r.p.rb_class = 0; r.p.outcome = 3; r.p.us = 0u; r.witness_advanced = 0; r.refusal = 5; return r; }(), 8u, 7u)), "FB-B2 text: txn_outcome_text cell 41 (op 3, outcome 3, w err 0 rb 0, p err 0 rb 0, adv 0, ref 5, g 8/7)");
static_assert(text_is("SAVE REFUSED - internal: write refused for an unknown reason; nothing written", txn_outcome_text(3, 3, []{ ecco_fbdurable::TxnResult r{}; r.w.err = 0; r.w.rb_class = 0; r.w.outcome = 0; r.w.us = 0u; r.p.err = 0; r.p.rb_class = 0; r.p.outcome = 3; r.p.us = 0u; r.witness_advanced = 0; r.refusal = 6; return r; }(), 8u, 7u)), "FB-B2 text: txn_outcome_text cell 42 (op 3, outcome 3, w err 0 rb 0, p err 0 rb 0, adv 0, ref 6, g 8/7)");
static_assert(text_is("SAVE OUTCOME UNKNOWN - storage reported -/NOT_READ; reboot the dongle (when no temporary operation is active) to re-verify; saving disabled until then", txn_outcome_text(3, 9, []{ ecco_fbdurable::TxnResult r{}; r.w.err = 0; r.w.rb_class = 0; r.w.outcome = 0; r.w.us = 0u; r.p.err = 0; r.p.rb_class = 0; r.p.outcome = 3; r.p.us = 0u; r.witness_advanced = 0; r.refusal = 0; return r; }(), 8u, 7u)), "FB-B2 text: txn_outcome_text cell 43 (op 3, outcome 9, w err 0 rb 0, p err 0 rb 0, adv 0, ref 0, g 8/7)");
static_assert(text_is("INVALIDATED - profile generation 0 is no longer usable (now INVALIDATED g1); payload kept for reference; save a new profile to re-enable", txn_outcome_text(2, 1, []{ ecco_fbdurable::TxnResult r{}; r.w.err = 0; r.w.rb_class = 0; r.w.outcome = 1; r.w.us = 0u; r.p.err = 0; r.p.rb_class = 0; r.p.outcome = 1; r.p.us = 0u; r.witness_advanced = 0; r.refusal = 0; return r; }(), 1u, 0u)), "FB-B2 text: txn_outcome_text cell 44 (op 2, outcome 1, w err 0 rb 0, p err 0 rb 0, adv 0, ref 0, g 1/0)");
static_assert(text_is("INVALIDATED - profile generation 6 is no longer usable (now INVALIDATED g7); payload kept for reference; save a new profile to re-enable", txn_outcome_text(2, 1, []{ ecco_fbdurable::TxnResult r{}; r.w.err = 0; r.w.rb_class = 0; r.w.outcome = 1; r.w.us = 0u; r.p.err = 0; r.p.rb_class = 0; r.p.outcome = 1; r.p.us = 0u; r.witness_advanced = 0; r.refusal = 0; return r; }(), 7u, 6u)), "FB-B2 text: txn_outcome_text cell 45 (op 2, outcome 1, w err 0 rb 0, p err 0 rb 0, adv 0, ref 0, g 7/6)");
static_assert(text_is("INVALIDATED - profile generation 4294967294 is no longer usable (now INVALIDATED g4294967295); payload kept for reference; save a new profile to re-enable", txn_outcome_text(2, 1, []{ ecco_fbdurable::TxnResult r{}; r.w.err = 0; r.w.rb_class = 0; r.w.outcome = 1; r.w.us = 0u; r.p.err = 0; r.p.rb_class = 0; r.p.outcome = 1; r.p.us = 0u; r.witness_advanced = 0; r.refusal = 0; return r; }(), 4294967295u, 4294967294u)), "FB-B2 text: txn_outcome_text cell 46 (op 2, outcome 1, w err 0 rb 0, p err 0 rb 0, adv 0, ref 0, g 4294967295/4294967294)");
static_assert(text_is("INVALIDATE NOT COMMITTED - storage refused the write (E1107); profile still VALID g7", txn_outcome_text(2, 2, []{ ecco_fbdurable::TxnResult r{}; r.w.err = 4359; r.w.rb_class = 2; r.w.outcome = 2; r.w.us = 0u; r.p.err = 0; r.p.rb_class = 0; r.p.outcome = 3; r.p.us = 0u; r.witness_advanced = 0; r.refusal = 0; return r; }(), 0u, 7u)), "FB-B2 text: txn_outcome_text cell 47 (op 2, outcome 2, w err 4359 rb 2, p err 0 rb 0, adv 0, ref 0, g 0/7)");
static_assert(text_is("INVALIDATE NOT COMMITTED - storage refused the write (E1104); profile still VALID g4294967295", txn_outcome_text(2, 2, []{ ecco_fbdurable::TxnResult r{}; r.w.err = 4356; r.w.rb_class = 2; r.w.outcome = 2; r.w.us = 0u; r.p.err = 0; r.p.rb_class = 0; r.p.outcome = 3; r.p.us = 0u; r.witness_advanced = 0; r.refusal = 0; return r; }(), 0u, 4294967295u)), "FB-B2 text: txn_outcome_text cell 48 (op 2, outcome 2, w err 4356 rb 2, p err 0 rb 0, adv 0, ref 0, g 0/4294967295)");
static_assert(text_is("INVALIDATE NOT COMMITTED - storage refused the write (E1101); profile still VALID g1", txn_outcome_text(2, 2, []{ ecco_fbdurable::TxnResult r{}; r.w.err = 4353; r.w.rb_class = 2; r.w.outcome = 2; r.w.us = 0u; r.p.err = 0; r.p.rb_class = 0; r.p.outcome = 3; r.p.us = 0u; r.witness_advanced = 0; r.refusal = 0; return r; }(), 0u, 1u)), "FB-B2 text: txn_outcome_text cell 49 (op 2, outcome 2, w err 4353 rb 2, p err 0 rb 0, adv 0, ref 0, g 0/1)");
static_assert(text_is("INVALIDATE NOT COMMITTED for the profile record, but the generation record advanced: g7 is now STALE (unusable)", txn_outcome_text(2, 2, []{ ecco_fbdurable::TxnResult r{}; r.w.err = 0; r.w.rb_class = 0; r.w.outcome = 1; r.w.us = 0u; r.p.err = 4359; r.p.rb_class = 2; r.p.outcome = 2; r.p.us = 0u; r.witness_advanced = 1; r.refusal = 0; return r; }(), 8u, 7u)), "FB-B2 text: txn_outcome_text cell 50 (op 2, outcome 2, w err 0 rb 0, p err 4359 rb 2, adv 1, ref 0, g 8/7)");
static_assert(text_is("INVALIDATE OUTCOME UNKNOWN - E1102/OTHER_BYTES; treat the profile as unusable; reboot to re-verify (Fallback Profile writes locked until reboot)", txn_outcome_text(2, 0, []{ ecco_fbdurable::TxnResult r{}; r.w.err = 4354; r.w.rb_class = 3; r.w.outcome = 0; r.w.us = 0u; r.p.err = 0; r.p.rb_class = 0; r.p.outcome = 3; r.p.us = 0u; r.witness_advanced = 0; r.refusal = 0; return r; }(), 8u, 7u)), "FB-B2 text: txn_outcome_text cell 51 (op 2, outcome 0, w err 4354 rb 3, p err 0 rb 0, adv 0, ref 0, g 8/7)");
static_assert(text_is("INVALIDATE OUTCOME UNKNOWN - -/INTENDED; treat the profile as unusable; reboot to re-verify (Fallback Profile writes locked until reboot)", txn_outcome_text(2, 0, []{ ecco_fbdurable::TxnResult r{}; r.w.err = 0; r.w.rb_class = 1; r.w.outcome = 0; r.w.us = 0u; r.p.err = 0; r.p.rb_class = 0; r.p.outcome = 3; r.p.us = 0u; r.witness_advanced = 0; r.refusal = 0; return r; }(), 8u, 7u)), "FB-B2 text: txn_outcome_text cell 52 (op 2, outcome 0, w err 0 rb 1, p err 0 rb 0, adv 0, ref 0, g 8/7)");
static_assert(text_is("INVALIDATE OUTCOME UNKNOWN - EFFFFFFFF/READ_ERROR; treat the profile as unusable; reboot to re-verify (Fallback Profile writes locked until reboot)", txn_outcome_text(2, 0, []{ ecco_fbdurable::TxnResult r{}; r.w.err = -1; r.w.rb_class = 6; r.w.outcome = 0; r.w.us = 0u; r.p.err = 0; r.p.rb_class = 0; r.p.outcome = 3; r.p.us = 0u; r.witness_advanced = 0; r.refusal = 0; return r; }(), 8u, 7u)), "FB-B2 text: txn_outcome_text cell 53 (op 2, outcome 0, w err -1 rb 6, p err 0 rb 0, adv 0, ref 0, g 8/7)");
static_assert(text_is("INVALIDATE OUTCOME UNKNOWN - E103/UNAVAILABLE; treat the profile as unusable; reboot to re-verify (Fallback Profile writes locked until reboot)", txn_outcome_text(2, 0, []{ ecco_fbdurable::TxnResult r{}; r.w.err = 259; r.w.rb_class = 7; r.w.outcome = 0; r.w.us = 0u; r.p.err = 0; r.p.rb_class = 0; r.p.outcome = 3; r.p.us = 0u; r.witness_advanced = 0; r.refusal = 0; return r; }(), 8u, 7u)), "FB-B2 text: txn_outcome_text cell 54 (op 2, outcome 0, w err 259 rb 7, p err 0 rb 0, adv 0, ref 0, g 8/7)");
static_assert(text_is("INVALIDATE OUTCOME UNKNOWN - E1105/WRONG_SIZE; treat the profile as unusable; reboot to re-verify (Fallback Profile writes locked until reboot)", txn_outcome_text(2, 0, []{ ecco_fbdurable::TxnResult r{}; r.w.err = 0; r.w.rb_class = 0; r.w.outcome = 1; r.w.us = 0u; r.p.err = 4357; r.p.rb_class = 5; r.p.outcome = 0; r.p.us = 0u; r.witness_advanced = 0; r.refusal = 0; return r; }(), 8u, 7u)), "FB-B2 text: txn_outcome_text cell 55 (op 2, outcome 0, w err 0 rb 0, p err 4357 rb 5, adv 0, ref 0, g 8/7)");
static_assert(text_is("INVALIDATE OUTCOME UNKNOWN - -/ABSENT_UNEXPECTED; treat the profile as unusable; reboot to re-verify (Fallback Profile writes locked until reboot)", txn_outcome_text(2, 0, []{ ecco_fbdurable::TxnResult r{}; r.w.err = 0; r.w.rb_class = 0; r.w.outcome = 1; r.w.us = 0u; r.p.err = 0; r.p.rb_class = 4; r.p.outcome = 0; r.p.us = 0u; r.witness_advanced = 0; r.refusal = 0; return r; }(), 8u, 7u)), "FB-B2 text: txn_outcome_text cell 56 (op 2, outcome 0, w err 0 rb 0, p err 0 rb 4, adv 0, ref 0, g 8/7)");
static_assert(text_is("INVALIDATE OUTCOME UNKNOWN - E1102/OTHER_BYTES; treat the profile as unusable; reboot to re-verify (Fallback Profile writes locked until reboot)", txn_outcome_text(2, 0, []{ ecco_fbdurable::TxnResult r{}; r.w.err = 4354; r.w.rb_class = 3; r.w.outcome = 0; r.w.us = 0u; r.p.err = 0; r.p.rb_class = 0; r.p.outcome = 3; r.p.us = 0u; r.witness_advanced = 1; r.refusal = 0; return r; }(), 8u, 7u)), "FB-B2 text: txn_outcome_text cell 57 (op 2, outcome 0, w err 4354 rb 3, p err 0 rb 0, adv 1, ref 0, g 8/7)");
static_assert(text_is("INVALIDATE REFUSED - internal: write refused for an unknown reason; nothing written", txn_outcome_text(2, 3, []{ ecco_fbdurable::TxnResult r{}; r.w.err = 0; r.w.rb_class = 0; r.w.outcome = 0; r.w.us = 0u; r.p.err = 0; r.p.rb_class = 0; r.p.outcome = 3; r.p.us = 0u; r.witness_advanced = 0; r.refusal = 0; return r; }(), 8u, 7u)), "FB-B2 text: txn_outcome_text cell 58 (op 2, outcome 3, w err 0 rb 0, p err 0 rb 0, adv 0, ref 0, g 8/7)");
static_assert(text_is("INVALIDATE REFUSED - internal: write refused for an unknown reason; nothing written", txn_outcome_text(2, 3, []{ ecco_fbdurable::TxnResult r{}; r.w.err = 0; r.w.rb_class = 0; r.w.outcome = 0; r.w.us = 0u; r.p.err = 0; r.p.rb_class = 0; r.p.outcome = 3; r.p.us = 0u; r.witness_advanced = 0; r.refusal = 1; return r; }(), 8u, 7u)), "FB-B2 text: txn_outcome_text cell 59 (op 2, outcome 3, w err 0 rb 0, p err 0 rb 0, adv 0, ref 1, g 8/7)");
static_assert(text_is("INVALIDATE REFUSED - previous Fallback Profile write outcome unknown this boot - reboot to re-verify first", txn_outcome_text(2, 3, []{ ecco_fbdurable::TxnResult r{}; r.w.err = 0; r.w.rb_class = 0; r.w.outcome = 0; r.w.us = 0u; r.p.err = 0; r.p.rb_class = 0; r.p.outcome = 3; r.p.us = 0u; r.witness_advanced = 0; r.refusal = 2; return r; }(), 8u, 7u)), "FB-B2 text: txn_outcome_text cell 60 (op 2, outcome 3, w err 0 rb 0, p err 0 rb 0, adv 0, ref 2, g 8/7)");
static_assert(text_is("INVALIDATE REFUSED - internal: built record did not validate; nothing written", txn_outcome_text(2, 3, []{ ecco_fbdurable::TxnResult r{}; r.w.err = 0; r.w.rb_class = 0; r.w.outcome = 0; r.w.us = 0u; r.p.err = 0; r.p.rb_class = 0; r.p.outcome = 3; r.p.us = 0u; r.witness_advanced = 0; r.refusal = 3; return r; }(), 8u, 7u)), "FB-B2 text: txn_outcome_text cell 61 (op 2, outcome 3, w err 0 rb 0, p err 0 rb 0, adv 0, ref 3, g 8/7)");
static_assert(text_is("INVALIDATE REFUSED - storage unavailable - nothing written", txn_outcome_text(2, 3, []{ ecco_fbdurable::TxnResult r{}; r.w.err = 0; r.w.rb_class = 0; r.w.outcome = 0; r.w.us = 0u; r.p.err = 0; r.p.rb_class = 0; r.p.outcome = 3; r.p.us = 0u; r.witness_advanced = 0; r.refusal = 4; return r; }(), 8u, 7u)), "FB-B2 text: txn_outcome_text cell 62 (op 2, outcome 3, w err 0 rb 0, p err 0 rb 0, adv 0, ref 4, g 8/7)");
static_assert(text_is("INVALIDATE REFUSED - storage not healthy - nothing written", txn_outcome_text(2, 3, []{ ecco_fbdurable::TxnResult r{}; r.w.err = 0; r.w.rb_class = 0; r.w.outcome = 0; r.w.us = 0u; r.p.err = 0; r.p.rb_class = 0; r.p.outcome = 3; r.p.us = 0u; r.witness_advanced = 0; r.refusal = 5; return r; }(), 8u, 7u)), "FB-B2 text: txn_outcome_text cell 63 (op 2, outcome 3, w err 0 rb 0, p err 0 rb 0, adv 0, ref 5, g 8/7)");
static_assert(text_is("INVALIDATE REFUSED - internal: write refused for an unknown reason; nothing written", txn_outcome_text(2, 3, []{ ecco_fbdurable::TxnResult r{}; r.w.err = 0; r.w.rb_class = 0; r.w.outcome = 0; r.w.us = 0u; r.p.err = 0; r.p.rb_class = 0; r.p.outcome = 3; r.p.us = 0u; r.witness_advanced = 0; r.refusal = 6; return r; }(), 8u, 7u)), "FB-B2 text: txn_outcome_text cell 64 (op 2, outcome 3, w err 0 rb 0, p err 0 rb 0, adv 0, ref 6, g 8/7)");
static_assert(text_is("INVALIDATE OUTCOME UNKNOWN - -/NOT_READ; treat the profile as unusable; reboot to re-verify (Fallback Profile writes locked until reboot)", txn_outcome_text(2, 9, []{ ecco_fbdurable::TxnResult r{}; r.w.err = 0; r.w.rb_class = 0; r.w.outcome = 0; r.w.us = 0u; r.p.err = 0; r.p.rb_class = 0; r.p.outcome = 3; r.p.us = 0u; r.witness_advanced = 0; r.refusal = 0; return r; }(), 8u, 7u)), "FB-B2 text: txn_outcome_text cell 65 (op 2, outcome 9, w err 0 rb 0, p err 0 rb 0, adv 0, ref 0, g 8/7)");
static_assert(text_is("INTERNAL - Fallback Profile dispatch context invalid; nothing written", txn_outcome_text(0, 1, []{ ecco_fbdurable::TxnResult r{}; r.w.err = 0; r.w.rb_class = 0; r.w.outcome = 1; r.w.us = 0u; r.p.err = 0; r.p.rb_class = 0; r.p.outcome = 1; r.p.us = 0u; r.witness_advanced = 0; r.refusal = 0; return r; }(), 1u, 0u)), "FB-B2 text: txn_outcome_text cell 66 (op 0, outcome 1, w err 0 rb 0, p err 0 rb 0, adv 0, ref 0, g 1/0)");
static_assert(text_is("INTERNAL - Fallback Profile dispatch context invalid; nothing written", txn_outcome_text(0, 1, []{ ecco_fbdurable::TxnResult r{}; r.w.err = 0; r.w.rb_class = 0; r.w.outcome = 1; r.w.us = 0u; r.p.err = 0; r.p.rb_class = 0; r.p.outcome = 1; r.p.us = 0u; r.witness_advanced = 0; r.refusal = 0; return r; }(), 7u, 6u)), "FB-B2 text: txn_outcome_text cell 67 (op 0, outcome 1, w err 0 rb 0, p err 0 rb 0, adv 0, ref 0, g 7/6)");
static_assert(text_is("INTERNAL - Fallback Profile dispatch context invalid; nothing written", txn_outcome_text(0, 1, []{ ecco_fbdurable::TxnResult r{}; r.w.err = 0; r.w.rb_class = 0; r.w.outcome = 1; r.w.us = 0u; r.p.err = 0; r.p.rb_class = 0; r.p.outcome = 1; r.p.us = 0u; r.witness_advanced = 0; r.refusal = 0; return r; }(), 4294967295u, 4294967294u)), "FB-B2 text: txn_outcome_text cell 68 (op 0, outcome 1, w err 0 rb 0, p err 0 rb 0, adv 0, ref 0, g 4294967295/4294967294)");
static_assert(text_is("INTERNAL - Fallback Profile dispatch context invalid; nothing written", txn_outcome_text(0, 2, []{ ecco_fbdurable::TxnResult r{}; r.w.err = 4359; r.w.rb_class = 2; r.w.outcome = 2; r.w.us = 0u; r.p.err = 0; r.p.rb_class = 0; r.p.outcome = 3; r.p.us = 0u; r.witness_advanced = 0; r.refusal = 0; return r; }(), 0u, 7u)), "FB-B2 text: txn_outcome_text cell 69 (op 0, outcome 2, w err 4359 rb 2, p err 0 rb 0, adv 0, ref 0, g 0/7)");
static_assert(text_is("INTERNAL - Fallback Profile dispatch context invalid; nothing written", txn_outcome_text(0, 2, []{ ecco_fbdurable::TxnResult r{}; r.w.err = 4356; r.w.rb_class = 2; r.w.outcome = 2; r.w.us = 0u; r.p.err = 0; r.p.rb_class = 0; r.p.outcome = 3; r.p.us = 0u; r.witness_advanced = 0; r.refusal = 0; return r; }(), 0u, 4294967295u)), "FB-B2 text: txn_outcome_text cell 70 (op 0, outcome 2, w err 4356 rb 2, p err 0 rb 0, adv 0, ref 0, g 0/4294967295)");
static_assert(text_is("INTERNAL - Fallback Profile dispatch context invalid; nothing written", txn_outcome_text(0, 2, []{ ecco_fbdurable::TxnResult r{}; r.w.err = 4353; r.w.rb_class = 2; r.w.outcome = 2; r.w.us = 0u; r.p.err = 0; r.p.rb_class = 0; r.p.outcome = 3; r.p.us = 0u; r.witness_advanced = 0; r.refusal = 0; return r; }(), 0u, 1u)), "FB-B2 text: txn_outcome_text cell 71 (op 0, outcome 2, w err 4353 rb 2, p err 0 rb 0, adv 0, ref 0, g 0/1)");
static_assert(text_is("INTERNAL - Fallback Profile dispatch context invalid; nothing written", txn_outcome_text(0, 2, []{ ecco_fbdurable::TxnResult r{}; r.w.err = 0; r.w.rb_class = 0; r.w.outcome = 1; r.w.us = 0u; r.p.err = 4359; r.p.rb_class = 2; r.p.outcome = 2; r.p.us = 0u; r.witness_advanced = 1; r.refusal = 0; return r; }(), 8u, 7u)), "FB-B2 text: txn_outcome_text cell 72 (op 0, outcome 2, w err 0 rb 0, p err 4359 rb 2, adv 1, ref 0, g 8/7)");
static_assert(text_is("INTERNAL - Fallback Profile dispatch context invalid; nothing written", txn_outcome_text(0, 0, []{ ecco_fbdurable::TxnResult r{}; r.w.err = 4354; r.w.rb_class = 3; r.w.outcome = 0; r.w.us = 0u; r.p.err = 0; r.p.rb_class = 0; r.p.outcome = 3; r.p.us = 0u; r.witness_advanced = 0; r.refusal = 0; return r; }(), 8u, 7u)), "FB-B2 text: txn_outcome_text cell 73 (op 0, outcome 0, w err 4354 rb 3, p err 0 rb 0, adv 0, ref 0, g 8/7)");
static_assert(text_is("INTERNAL - Fallback Profile dispatch context invalid; nothing written", txn_outcome_text(0, 0, []{ ecco_fbdurable::TxnResult r{}; r.w.err = 0; r.w.rb_class = 1; r.w.outcome = 0; r.w.us = 0u; r.p.err = 0; r.p.rb_class = 0; r.p.outcome = 3; r.p.us = 0u; r.witness_advanced = 0; r.refusal = 0; return r; }(), 8u, 7u)), "FB-B2 text: txn_outcome_text cell 74 (op 0, outcome 0, w err 0 rb 1, p err 0 rb 0, adv 0, ref 0, g 8/7)");
static_assert(text_is("INTERNAL - Fallback Profile dispatch context invalid; nothing written", txn_outcome_text(0, 0, []{ ecco_fbdurable::TxnResult r{}; r.w.err = -1; r.w.rb_class = 6; r.w.outcome = 0; r.w.us = 0u; r.p.err = 0; r.p.rb_class = 0; r.p.outcome = 3; r.p.us = 0u; r.witness_advanced = 0; r.refusal = 0; return r; }(), 8u, 7u)), "FB-B2 text: txn_outcome_text cell 75 (op 0, outcome 0, w err -1 rb 6, p err 0 rb 0, adv 0, ref 0, g 8/7)");
static_assert(text_is("INTERNAL - Fallback Profile dispatch context invalid; nothing written", txn_outcome_text(0, 0, []{ ecco_fbdurable::TxnResult r{}; r.w.err = 259; r.w.rb_class = 7; r.w.outcome = 0; r.w.us = 0u; r.p.err = 0; r.p.rb_class = 0; r.p.outcome = 3; r.p.us = 0u; r.witness_advanced = 0; r.refusal = 0; return r; }(), 8u, 7u)), "FB-B2 text: txn_outcome_text cell 76 (op 0, outcome 0, w err 259 rb 7, p err 0 rb 0, adv 0, ref 0, g 8/7)");
static_assert(text_is("INTERNAL - Fallback Profile dispatch context invalid; nothing written", txn_outcome_text(0, 0, []{ ecco_fbdurable::TxnResult r{}; r.w.err = 0; r.w.rb_class = 0; r.w.outcome = 1; r.w.us = 0u; r.p.err = 4357; r.p.rb_class = 5; r.p.outcome = 0; r.p.us = 0u; r.witness_advanced = 0; r.refusal = 0; return r; }(), 8u, 7u)), "FB-B2 text: txn_outcome_text cell 77 (op 0, outcome 0, w err 0 rb 0, p err 4357 rb 5, adv 0, ref 0, g 8/7)");
static_assert(text_is("INTERNAL - Fallback Profile dispatch context invalid; nothing written", txn_outcome_text(0, 0, []{ ecco_fbdurable::TxnResult r{}; r.w.err = 0; r.w.rb_class = 0; r.w.outcome = 1; r.w.us = 0u; r.p.err = 0; r.p.rb_class = 4; r.p.outcome = 0; r.p.us = 0u; r.witness_advanced = 0; r.refusal = 0; return r; }(), 8u, 7u)), "FB-B2 text: txn_outcome_text cell 78 (op 0, outcome 0, w err 0 rb 0, p err 0 rb 4, adv 0, ref 0, g 8/7)");
static_assert(text_is("INTERNAL - Fallback Profile dispatch context invalid; nothing written", txn_outcome_text(0, 0, []{ ecco_fbdurable::TxnResult r{}; r.w.err = 4354; r.w.rb_class = 3; r.w.outcome = 0; r.w.us = 0u; r.p.err = 0; r.p.rb_class = 0; r.p.outcome = 3; r.p.us = 0u; r.witness_advanced = 1; r.refusal = 0; return r; }(), 8u, 7u)), "FB-B2 text: txn_outcome_text cell 79 (op 0, outcome 0, w err 4354 rb 3, p err 0 rb 0, adv 1, ref 0, g 8/7)");
static_assert(text_is("INTERNAL - Fallback Profile dispatch context invalid; nothing written", txn_outcome_text(0, 3, []{ ecco_fbdurable::TxnResult r{}; r.w.err = 0; r.w.rb_class = 0; r.w.outcome = 0; r.w.us = 0u; r.p.err = 0; r.p.rb_class = 0; r.p.outcome = 3; r.p.us = 0u; r.witness_advanced = 0; r.refusal = 0; return r; }(), 8u, 7u)), "FB-B2 text: txn_outcome_text cell 80 (op 0, outcome 3, w err 0 rb 0, p err 0 rb 0, adv 0, ref 0, g 8/7)");
static_assert(text_is("INTERNAL - Fallback Profile dispatch context invalid; nothing written", txn_outcome_text(0, 3, []{ ecco_fbdurable::TxnResult r{}; r.w.err = 0; r.w.rb_class = 0; r.w.outcome = 0; r.w.us = 0u; r.p.err = 0; r.p.rb_class = 0; r.p.outcome = 3; r.p.us = 0u; r.witness_advanced = 0; r.refusal = 1; return r; }(), 8u, 7u)), "FB-B2 text: txn_outcome_text cell 81 (op 0, outcome 3, w err 0 rb 0, p err 0 rb 0, adv 0, ref 1, g 8/7)");
static_assert(text_is("INTERNAL - Fallback Profile dispatch context invalid; nothing written", txn_outcome_text(0, 3, []{ ecco_fbdurable::TxnResult r{}; r.w.err = 0; r.w.rb_class = 0; r.w.outcome = 0; r.w.us = 0u; r.p.err = 0; r.p.rb_class = 0; r.p.outcome = 3; r.p.us = 0u; r.witness_advanced = 0; r.refusal = 2; return r; }(), 8u, 7u)), "FB-B2 text: txn_outcome_text cell 82 (op 0, outcome 3, w err 0 rb 0, p err 0 rb 0, adv 0, ref 2, g 8/7)");
static_assert(text_is("INTERNAL - Fallback Profile dispatch context invalid; nothing written", txn_outcome_text(0, 3, []{ ecco_fbdurable::TxnResult r{}; r.w.err = 0; r.w.rb_class = 0; r.w.outcome = 0; r.w.us = 0u; r.p.err = 0; r.p.rb_class = 0; r.p.outcome = 3; r.p.us = 0u; r.witness_advanced = 0; r.refusal = 3; return r; }(), 8u, 7u)), "FB-B2 text: txn_outcome_text cell 83 (op 0, outcome 3, w err 0 rb 0, p err 0 rb 0, adv 0, ref 3, g 8/7)");
static_assert(text_is("INTERNAL - Fallback Profile dispatch context invalid; nothing written", txn_outcome_text(0, 3, []{ ecco_fbdurable::TxnResult r{}; r.w.err = 0; r.w.rb_class = 0; r.w.outcome = 0; r.w.us = 0u; r.p.err = 0; r.p.rb_class = 0; r.p.outcome = 3; r.p.us = 0u; r.witness_advanced = 0; r.refusal = 4; return r; }(), 8u, 7u)), "FB-B2 text: txn_outcome_text cell 84 (op 0, outcome 3, w err 0 rb 0, p err 0 rb 0, adv 0, ref 4, g 8/7)");
static_assert(text_is("INTERNAL - Fallback Profile dispatch context invalid; nothing written", txn_outcome_text(0, 3, []{ ecco_fbdurable::TxnResult r{}; r.w.err = 0; r.w.rb_class = 0; r.w.outcome = 0; r.w.us = 0u; r.p.err = 0; r.p.rb_class = 0; r.p.outcome = 3; r.p.us = 0u; r.witness_advanced = 0; r.refusal = 5; return r; }(), 8u, 7u)), "FB-B2 text: txn_outcome_text cell 85 (op 0, outcome 3, w err 0 rb 0, p err 0 rb 0, adv 0, ref 5, g 8/7)");
static_assert(text_is("INTERNAL - Fallback Profile dispatch context invalid; nothing written", txn_outcome_text(0, 3, []{ ecco_fbdurable::TxnResult r{}; r.w.err = 0; r.w.rb_class = 0; r.w.outcome = 0; r.w.us = 0u; r.p.err = 0; r.p.rb_class = 0; r.p.outcome = 3; r.p.us = 0u; r.witness_advanced = 0; r.refusal = 6; return r; }(), 8u, 7u)), "FB-B2 text: txn_outcome_text cell 86 (op 0, outcome 3, w err 0 rb 0, p err 0 rb 0, adv 0, ref 6, g 8/7)");
static_assert(text_is("INTERNAL - Fallback Profile dispatch context invalid; nothing written", txn_outcome_text(0, 9, []{ ecco_fbdurable::TxnResult r{}; r.w.err = 0; r.w.rb_class = 0; r.w.outcome = 0; r.w.us = 0u; r.p.err = 0; r.p.rb_class = 0; r.p.outcome = 3; r.p.us = 0u; r.witness_advanced = 0; r.refusal = 0; return r; }(), 8u, 7u)), "FB-B2 text: txn_outcome_text cell 87 (op 0, outcome 9, w err 0 rb 0, p err 0 rb 0, adv 0, ref 0, g 8/7)");
static_assert(text_is("INTERNAL - Fallback Profile dispatch context invalid; nothing written", txn_outcome_text(7, 1, []{ ecco_fbdurable::TxnResult r{}; r.w.err = 0; r.w.rb_class = 0; r.w.outcome = 1; r.w.us = 0u; r.p.err = 0; r.p.rb_class = 0; r.p.outcome = 1; r.p.us = 0u; r.witness_advanced = 0; r.refusal = 0; return r; }(), 1u, 0u)), "FB-B2 text: txn_outcome_text cell 88 (op 7, outcome 1, w err 0 rb 0, p err 0 rb 0, adv 0, ref 0, g 1/0)");
static_assert(text_is("INTERNAL - Fallback Profile dispatch context invalid; nothing written", txn_outcome_text(7, 1, []{ ecco_fbdurable::TxnResult r{}; r.w.err = 0; r.w.rb_class = 0; r.w.outcome = 1; r.w.us = 0u; r.p.err = 0; r.p.rb_class = 0; r.p.outcome = 1; r.p.us = 0u; r.witness_advanced = 0; r.refusal = 0; return r; }(), 7u, 6u)), "FB-B2 text: txn_outcome_text cell 89 (op 7, outcome 1, w err 0 rb 0, p err 0 rb 0, adv 0, ref 0, g 7/6)");
static_assert(text_is("INTERNAL - Fallback Profile dispatch context invalid; nothing written", txn_outcome_text(7, 1, []{ ecco_fbdurable::TxnResult r{}; r.w.err = 0; r.w.rb_class = 0; r.w.outcome = 1; r.w.us = 0u; r.p.err = 0; r.p.rb_class = 0; r.p.outcome = 1; r.p.us = 0u; r.witness_advanced = 0; r.refusal = 0; return r; }(), 4294967295u, 4294967294u)), "FB-B2 text: txn_outcome_text cell 90 (op 7, outcome 1, w err 0 rb 0, p err 0 rb 0, adv 0, ref 0, g 4294967295/4294967294)");
static_assert(text_is("INTERNAL - Fallback Profile dispatch context invalid; nothing written", txn_outcome_text(7, 2, []{ ecco_fbdurable::TxnResult r{}; r.w.err = 4359; r.w.rb_class = 2; r.w.outcome = 2; r.w.us = 0u; r.p.err = 0; r.p.rb_class = 0; r.p.outcome = 3; r.p.us = 0u; r.witness_advanced = 0; r.refusal = 0; return r; }(), 0u, 7u)), "FB-B2 text: txn_outcome_text cell 91 (op 7, outcome 2, w err 4359 rb 2, p err 0 rb 0, adv 0, ref 0, g 0/7)");
static_assert(text_is("INTERNAL - Fallback Profile dispatch context invalid; nothing written", txn_outcome_text(7, 2, []{ ecco_fbdurable::TxnResult r{}; r.w.err = 4356; r.w.rb_class = 2; r.w.outcome = 2; r.w.us = 0u; r.p.err = 0; r.p.rb_class = 0; r.p.outcome = 3; r.p.us = 0u; r.witness_advanced = 0; r.refusal = 0; return r; }(), 0u, 4294967295u)), "FB-B2 text: txn_outcome_text cell 92 (op 7, outcome 2, w err 4356 rb 2, p err 0 rb 0, adv 0, ref 0, g 0/4294967295)");
static_assert(text_is("INTERNAL - Fallback Profile dispatch context invalid; nothing written", txn_outcome_text(7, 2, []{ ecco_fbdurable::TxnResult r{}; r.w.err = 4353; r.w.rb_class = 2; r.w.outcome = 2; r.w.us = 0u; r.p.err = 0; r.p.rb_class = 0; r.p.outcome = 3; r.p.us = 0u; r.witness_advanced = 0; r.refusal = 0; return r; }(), 0u, 1u)), "FB-B2 text: txn_outcome_text cell 93 (op 7, outcome 2, w err 4353 rb 2, p err 0 rb 0, adv 0, ref 0, g 0/1)");
static_assert(text_is("INTERNAL - Fallback Profile dispatch context invalid; nothing written", txn_outcome_text(7, 2, []{ ecco_fbdurable::TxnResult r{}; r.w.err = 0; r.w.rb_class = 0; r.w.outcome = 1; r.w.us = 0u; r.p.err = 4359; r.p.rb_class = 2; r.p.outcome = 2; r.p.us = 0u; r.witness_advanced = 1; r.refusal = 0; return r; }(), 8u, 7u)), "FB-B2 text: txn_outcome_text cell 94 (op 7, outcome 2, w err 0 rb 0, p err 4359 rb 2, adv 1, ref 0, g 8/7)");
static_assert(text_is("INTERNAL - Fallback Profile dispatch context invalid; nothing written", txn_outcome_text(7, 0, []{ ecco_fbdurable::TxnResult r{}; r.w.err = 4354; r.w.rb_class = 3; r.w.outcome = 0; r.w.us = 0u; r.p.err = 0; r.p.rb_class = 0; r.p.outcome = 3; r.p.us = 0u; r.witness_advanced = 0; r.refusal = 0; return r; }(), 8u, 7u)), "FB-B2 text: txn_outcome_text cell 95 (op 7, outcome 0, w err 4354 rb 3, p err 0 rb 0, adv 0, ref 0, g 8/7)");
static_assert(text_is("INTERNAL - Fallback Profile dispatch context invalid; nothing written", txn_outcome_text(7, 0, []{ ecco_fbdurable::TxnResult r{}; r.w.err = 0; r.w.rb_class = 1; r.w.outcome = 0; r.w.us = 0u; r.p.err = 0; r.p.rb_class = 0; r.p.outcome = 3; r.p.us = 0u; r.witness_advanced = 0; r.refusal = 0; return r; }(), 8u, 7u)), "FB-B2 text: txn_outcome_text cell 96 (op 7, outcome 0, w err 0 rb 1, p err 0 rb 0, adv 0, ref 0, g 8/7)");
static_assert(text_is("INTERNAL - Fallback Profile dispatch context invalid; nothing written", txn_outcome_text(7, 0, []{ ecco_fbdurable::TxnResult r{}; r.w.err = -1; r.w.rb_class = 6; r.w.outcome = 0; r.w.us = 0u; r.p.err = 0; r.p.rb_class = 0; r.p.outcome = 3; r.p.us = 0u; r.witness_advanced = 0; r.refusal = 0; return r; }(), 8u, 7u)), "FB-B2 text: txn_outcome_text cell 97 (op 7, outcome 0, w err -1 rb 6, p err 0 rb 0, adv 0, ref 0, g 8/7)");
static_assert(text_is("INTERNAL - Fallback Profile dispatch context invalid; nothing written", txn_outcome_text(7, 0, []{ ecco_fbdurable::TxnResult r{}; r.w.err = 259; r.w.rb_class = 7; r.w.outcome = 0; r.w.us = 0u; r.p.err = 0; r.p.rb_class = 0; r.p.outcome = 3; r.p.us = 0u; r.witness_advanced = 0; r.refusal = 0; return r; }(), 8u, 7u)), "FB-B2 text: txn_outcome_text cell 98 (op 7, outcome 0, w err 259 rb 7, p err 0 rb 0, adv 0, ref 0, g 8/7)");
static_assert(text_is("INTERNAL - Fallback Profile dispatch context invalid; nothing written", txn_outcome_text(7, 0, []{ ecco_fbdurable::TxnResult r{}; r.w.err = 0; r.w.rb_class = 0; r.w.outcome = 1; r.w.us = 0u; r.p.err = 4357; r.p.rb_class = 5; r.p.outcome = 0; r.p.us = 0u; r.witness_advanced = 0; r.refusal = 0; return r; }(), 8u, 7u)), "FB-B2 text: txn_outcome_text cell 99 (op 7, outcome 0, w err 0 rb 0, p err 4357 rb 5, adv 0, ref 0, g 8/7)");
static_assert(text_is("INTERNAL - Fallback Profile dispatch context invalid; nothing written", txn_outcome_text(7, 0, []{ ecco_fbdurable::TxnResult r{}; r.w.err = 0; r.w.rb_class = 0; r.w.outcome = 1; r.w.us = 0u; r.p.err = 0; r.p.rb_class = 4; r.p.outcome = 0; r.p.us = 0u; r.witness_advanced = 0; r.refusal = 0; return r; }(), 8u, 7u)), "FB-B2 text: txn_outcome_text cell 100 (op 7, outcome 0, w err 0 rb 0, p err 0 rb 4, adv 0, ref 0, g 8/7)");
static_assert(text_is("INTERNAL - Fallback Profile dispatch context invalid; nothing written", txn_outcome_text(7, 0, []{ ecco_fbdurable::TxnResult r{}; r.w.err = 4354; r.w.rb_class = 3; r.w.outcome = 0; r.w.us = 0u; r.p.err = 0; r.p.rb_class = 0; r.p.outcome = 3; r.p.us = 0u; r.witness_advanced = 1; r.refusal = 0; return r; }(), 8u, 7u)), "FB-B2 text: txn_outcome_text cell 101 (op 7, outcome 0, w err 4354 rb 3, p err 0 rb 0, adv 1, ref 0, g 8/7)");
static_assert(text_is("INTERNAL - Fallback Profile dispatch context invalid; nothing written", txn_outcome_text(7, 3, []{ ecco_fbdurable::TxnResult r{}; r.w.err = 0; r.w.rb_class = 0; r.w.outcome = 0; r.w.us = 0u; r.p.err = 0; r.p.rb_class = 0; r.p.outcome = 3; r.p.us = 0u; r.witness_advanced = 0; r.refusal = 0; return r; }(), 8u, 7u)), "FB-B2 text: txn_outcome_text cell 102 (op 7, outcome 3, w err 0 rb 0, p err 0 rb 0, adv 0, ref 0, g 8/7)");
static_assert(text_is("INTERNAL - Fallback Profile dispatch context invalid; nothing written", txn_outcome_text(7, 3, []{ ecco_fbdurable::TxnResult r{}; r.w.err = 0; r.w.rb_class = 0; r.w.outcome = 0; r.w.us = 0u; r.p.err = 0; r.p.rb_class = 0; r.p.outcome = 3; r.p.us = 0u; r.witness_advanced = 0; r.refusal = 1; return r; }(), 8u, 7u)), "FB-B2 text: txn_outcome_text cell 103 (op 7, outcome 3, w err 0 rb 0, p err 0 rb 0, adv 0, ref 1, g 8/7)");
static_assert(text_is("INTERNAL - Fallback Profile dispatch context invalid; nothing written", txn_outcome_text(7, 3, []{ ecco_fbdurable::TxnResult r{}; r.w.err = 0; r.w.rb_class = 0; r.w.outcome = 0; r.w.us = 0u; r.p.err = 0; r.p.rb_class = 0; r.p.outcome = 3; r.p.us = 0u; r.witness_advanced = 0; r.refusal = 2; return r; }(), 8u, 7u)), "FB-B2 text: txn_outcome_text cell 104 (op 7, outcome 3, w err 0 rb 0, p err 0 rb 0, adv 0, ref 2, g 8/7)");
static_assert(text_is("INTERNAL - Fallback Profile dispatch context invalid; nothing written", txn_outcome_text(7, 3, []{ ecco_fbdurable::TxnResult r{}; r.w.err = 0; r.w.rb_class = 0; r.w.outcome = 0; r.w.us = 0u; r.p.err = 0; r.p.rb_class = 0; r.p.outcome = 3; r.p.us = 0u; r.witness_advanced = 0; r.refusal = 3; return r; }(), 8u, 7u)), "FB-B2 text: txn_outcome_text cell 105 (op 7, outcome 3, w err 0 rb 0, p err 0 rb 0, adv 0, ref 3, g 8/7)");
static_assert(text_is("INTERNAL - Fallback Profile dispatch context invalid; nothing written", txn_outcome_text(7, 3, []{ ecco_fbdurable::TxnResult r{}; r.w.err = 0; r.w.rb_class = 0; r.w.outcome = 0; r.w.us = 0u; r.p.err = 0; r.p.rb_class = 0; r.p.outcome = 3; r.p.us = 0u; r.witness_advanced = 0; r.refusal = 4; return r; }(), 8u, 7u)), "FB-B2 text: txn_outcome_text cell 106 (op 7, outcome 3, w err 0 rb 0, p err 0 rb 0, adv 0, ref 4, g 8/7)");
static_assert(text_is("INTERNAL - Fallback Profile dispatch context invalid; nothing written", txn_outcome_text(7, 3, []{ ecco_fbdurable::TxnResult r{}; r.w.err = 0; r.w.rb_class = 0; r.w.outcome = 0; r.w.us = 0u; r.p.err = 0; r.p.rb_class = 0; r.p.outcome = 3; r.p.us = 0u; r.witness_advanced = 0; r.refusal = 5; return r; }(), 8u, 7u)), "FB-B2 text: txn_outcome_text cell 107 (op 7, outcome 3, w err 0 rb 0, p err 0 rb 0, adv 0, ref 5, g 8/7)");
static_assert(text_is("INTERNAL - Fallback Profile dispatch context invalid; nothing written", txn_outcome_text(7, 3, []{ ecco_fbdurable::TxnResult r{}; r.w.err = 0; r.w.rb_class = 0; r.w.outcome = 0; r.w.us = 0u; r.p.err = 0; r.p.rb_class = 0; r.p.outcome = 3; r.p.us = 0u; r.witness_advanced = 0; r.refusal = 6; return r; }(), 8u, 7u)), "FB-B2 text: txn_outcome_text cell 108 (op 7, outcome 3, w err 0 rb 0, p err 0 rb 0, adv 0, ref 6, g 8/7)");
static_assert(text_is("INTERNAL - Fallback Profile dispatch context invalid; nothing written", txn_outcome_text(7, 9, []{ ecco_fbdurable::TxnResult r{}; r.w.err = 0; r.w.rb_class = 0; r.w.outcome = 0; r.w.us = 0u; r.p.err = 0; r.p.rb_class = 0; r.p.outcome = 3; r.p.us = 0u; r.witness_advanced = 0; r.refusal = 0; return r; }(), 8u, 7u)), "FB-B2 text: txn_outcome_text cell 109 (op 7, outcome 9, w err 0 rb 0, p err 0 rb 0, adv 0, ref 0, g 8/7)");
static_assert(text_is("txn=SAVE gen=4294967295 w:err=- rb=NOT_READ out=UNKNOWN_REBOOT p:err=- rb=NOT_READ out=NOT_ATTEMPTED total_us=0 -> UNKNOWN_REBOOT", txn_log_text(1, 0, []{ ecco_fbdurable::TxnResult r{}; r.w.err = 0; r.w.rb_class = 0; r.w.outcome = 0; r.w.us = 0u; r.p.err = 0; r.p.rb_class = 0; r.p.outcome = 3; r.p.us = 0u; r.witness_advanced = 0; r.refusal = 0; return r; }(), 4294967295u)), "FB-B2 text: txn_log_text op 1 outcome 0 w 0/0/0/0 p 0/0/3/0");
static_assert(text_is("txn=SAVE gen=4294967295 w:err=E1107 rb=PRIOR out=NOT_COMMITTED p:err=- rb=NOT_READ out=NOT_ATTEMPTED total_us=1239 -> UNKNOWN_REBOOT", txn_log_text(1, 0, []{ ecco_fbdurable::TxnResult r{}; r.w.err = 4359; r.w.rb_class = 2; r.w.outcome = 2; r.w.us = 1234u; r.p.err = 0; r.p.rb_class = 0; r.p.outcome = 3; r.p.us = 5u; r.witness_advanced = 0; r.refusal = 0; return r; }(), 4294967295u)), "FB-B2 text: txn_log_text op 1 outcome 0 w 4359/2/2/1234 p 0/0/3/5");
static_assert(text_is("txn=SAVE gen=4294967295 w:err=- rb=NOT_READ out=COMMITTED p:err=- rb=NOT_READ out=COMMITTED total_us=150 -> UNKNOWN_REBOOT", txn_log_text(1, 0, []{ ecco_fbdurable::TxnResult r{}; r.w.err = 0; r.w.rb_class = 0; r.w.outcome = 1; r.w.us = 70u; r.p.err = 0; r.p.rb_class = 0; r.p.outcome = 1; r.p.us = 80u; r.witness_advanced = 0; r.refusal = 0; return r; }(), 4294967295u)), "FB-B2 text: txn_log_text op 1 outcome 0 w 0/0/1/70 p 0/0/1/80");
static_assert(text_is("txn=SAVE gen=4294967295 w:err=EFFFFFFFF rb=UNAVAILABLE out=UNKNOWN_REBOOT p:err=EFFFFFFFF rb=UNAVAILABLE out=NOT_COMMITTED total_us=4294967294 -> UNKNOWN_REBOOT", txn_log_text(1, 0, []{ ecco_fbdurable::TxnResult r{}; r.w.err = -1; r.w.rb_class = 7; r.w.outcome = 0; r.w.us = 4294967295u; r.p.err = -1; r.p.rb_class = 7; r.p.outcome = 2; r.p.us = 4294967295u; r.witness_advanced = 0; r.refusal = 0; return r; }(), 4294967295u)), "FB-B2 text: txn_log_text op 1 outcome 0 w -1/7/0/4294967295 p -1/7/2/4294967295");
static_assert(text_is("txn=SAVE gen=4294967295 w:err=- rb=NOT_READ out=UNKNOWN_REBOOT p:err=- rb=NOT_READ out=NOT_ATTEMPTED total_us=0 -> COMMITTED", txn_log_text(1, 1, []{ ecco_fbdurable::TxnResult r{}; r.w.err = 0; r.w.rb_class = 0; r.w.outcome = 0; r.w.us = 0u; r.p.err = 0; r.p.rb_class = 0; r.p.outcome = 3; r.p.us = 0u; r.witness_advanced = 0; r.refusal = 0; return r; }(), 4294967295u)), "FB-B2 text: txn_log_text op 1 outcome 1 w 0/0/0/0 p 0/0/3/0");
static_assert(text_is("txn=SAVE gen=4294967295 w:err=E1107 rb=PRIOR out=NOT_COMMITTED p:err=- rb=NOT_READ out=NOT_ATTEMPTED total_us=1239 -> COMMITTED", txn_log_text(1, 1, []{ ecco_fbdurable::TxnResult r{}; r.w.err = 4359; r.w.rb_class = 2; r.w.outcome = 2; r.w.us = 1234u; r.p.err = 0; r.p.rb_class = 0; r.p.outcome = 3; r.p.us = 5u; r.witness_advanced = 0; r.refusal = 0; return r; }(), 4294967295u)), "FB-B2 text: txn_log_text op 1 outcome 1 w 4359/2/2/1234 p 0/0/3/5");
static_assert(text_is("txn=SAVE gen=4294967295 w:err=- rb=NOT_READ out=COMMITTED p:err=- rb=NOT_READ out=COMMITTED total_us=150 -> COMMITTED", txn_log_text(1, 1, []{ ecco_fbdurable::TxnResult r{}; r.w.err = 0; r.w.rb_class = 0; r.w.outcome = 1; r.w.us = 70u; r.p.err = 0; r.p.rb_class = 0; r.p.outcome = 1; r.p.us = 80u; r.witness_advanced = 0; r.refusal = 0; return r; }(), 4294967295u)), "FB-B2 text: txn_log_text op 1 outcome 1 w 0/0/1/70 p 0/0/1/80");
static_assert(text_is("txn=SAVE gen=4294967295 w:err=EFFFFFFFF rb=UNAVAILABLE out=UNKNOWN_REBOOT p:err=EFFFFFFFF rb=UNAVAILABLE out=NOT_COMMITTED total_us=4294967294 -> COMMITTED", txn_log_text(1, 1, []{ ecco_fbdurable::TxnResult r{}; r.w.err = -1; r.w.rb_class = 7; r.w.outcome = 0; r.w.us = 4294967295u; r.p.err = -1; r.p.rb_class = 7; r.p.outcome = 2; r.p.us = 4294967295u; r.witness_advanced = 0; r.refusal = 0; return r; }(), 4294967295u)), "FB-B2 text: txn_log_text op 1 outcome 1 w -1/7/0/4294967295 p -1/7/2/4294967295");
static_assert(text_is("txn=SAVE gen=4294967295 w:err=- rb=NOT_READ out=UNKNOWN_REBOOT p:err=- rb=NOT_READ out=NOT_ATTEMPTED total_us=0 -> NOT_COMMITTED", txn_log_text(1, 2, []{ ecco_fbdurable::TxnResult r{}; r.w.err = 0; r.w.rb_class = 0; r.w.outcome = 0; r.w.us = 0u; r.p.err = 0; r.p.rb_class = 0; r.p.outcome = 3; r.p.us = 0u; r.witness_advanced = 0; r.refusal = 0; return r; }(), 4294967295u)), "FB-B2 text: txn_log_text op 1 outcome 2 w 0/0/0/0 p 0/0/3/0");
static_assert(text_is("txn=SAVE gen=4294967295 w:err=E1107 rb=PRIOR out=NOT_COMMITTED p:err=- rb=NOT_READ out=NOT_ATTEMPTED total_us=1239 -> NOT_COMMITTED", txn_log_text(1, 2, []{ ecco_fbdurable::TxnResult r{}; r.w.err = 4359; r.w.rb_class = 2; r.w.outcome = 2; r.w.us = 1234u; r.p.err = 0; r.p.rb_class = 0; r.p.outcome = 3; r.p.us = 5u; r.witness_advanced = 0; r.refusal = 0; return r; }(), 4294967295u)), "FB-B2 text: txn_log_text op 1 outcome 2 w 4359/2/2/1234 p 0/0/3/5");
static_assert(text_is("txn=SAVE gen=4294967295 w:err=- rb=NOT_READ out=COMMITTED p:err=- rb=NOT_READ out=COMMITTED total_us=150 -> NOT_COMMITTED", txn_log_text(1, 2, []{ ecco_fbdurable::TxnResult r{}; r.w.err = 0; r.w.rb_class = 0; r.w.outcome = 1; r.w.us = 70u; r.p.err = 0; r.p.rb_class = 0; r.p.outcome = 1; r.p.us = 80u; r.witness_advanced = 0; r.refusal = 0; return r; }(), 4294967295u)), "FB-B2 text: txn_log_text op 1 outcome 2 w 0/0/1/70 p 0/0/1/80");
static_assert(text_is("txn=SAVE gen=4294967295 w:err=EFFFFFFFF rb=UNAVAILABLE out=UNKNOWN_REBOOT p:err=EFFFFFFFF rb=UNAVAILABLE out=NOT_COMMITTED total_us=4294967294 -> NOT_COMMITTED", txn_log_text(1, 2, []{ ecco_fbdurable::TxnResult r{}; r.w.err = -1; r.w.rb_class = 7; r.w.outcome = 0; r.w.us = 4294967295u; r.p.err = -1; r.p.rb_class = 7; r.p.outcome = 2; r.p.us = 4294967295u; r.witness_advanced = 0; r.refusal = 0; return r; }(), 4294967295u)), "FB-B2 text: txn_log_text op 1 outcome 2 w -1/7/0/4294967295 p -1/7/2/4294967295");
static_assert(text_is("txn=SAVE gen=4294967295 w:err=- rb=NOT_READ out=UNKNOWN_REBOOT p:err=- rb=NOT_READ out=NOT_ATTEMPTED total_us=0 -> REFUSED_LATCHED", txn_log_text(1, 3, []{ ecco_fbdurable::TxnResult r{}; r.w.err = 0; r.w.rb_class = 0; r.w.outcome = 0; r.w.us = 0u; r.p.err = 0; r.p.rb_class = 0; r.p.outcome = 3; r.p.us = 0u; r.witness_advanced = 0; r.refusal = 0; return r; }(), 4294967295u)), "FB-B2 text: txn_log_text op 1 outcome 3 w 0/0/0/0 p 0/0/3/0");
static_assert(text_is("txn=SAVE gen=4294967295 w:err=E1107 rb=PRIOR out=NOT_COMMITTED p:err=- rb=NOT_READ out=NOT_ATTEMPTED total_us=1239 -> REFUSED_LATCHED", txn_log_text(1, 3, []{ ecco_fbdurable::TxnResult r{}; r.w.err = 4359; r.w.rb_class = 2; r.w.outcome = 2; r.w.us = 1234u; r.p.err = 0; r.p.rb_class = 0; r.p.outcome = 3; r.p.us = 5u; r.witness_advanced = 0; r.refusal = 0; return r; }(), 4294967295u)), "FB-B2 text: txn_log_text op 1 outcome 3 w 4359/2/2/1234 p 0/0/3/5");
static_assert(text_is("txn=SAVE gen=4294967295 w:err=- rb=NOT_READ out=COMMITTED p:err=- rb=NOT_READ out=COMMITTED total_us=150 -> REFUSED_LATCHED", txn_log_text(1, 3, []{ ecco_fbdurable::TxnResult r{}; r.w.err = 0; r.w.rb_class = 0; r.w.outcome = 1; r.w.us = 70u; r.p.err = 0; r.p.rb_class = 0; r.p.outcome = 1; r.p.us = 80u; r.witness_advanced = 0; r.refusal = 0; return r; }(), 4294967295u)), "FB-B2 text: txn_log_text op 1 outcome 3 w 0/0/1/70 p 0/0/1/80");
static_assert(text_is("txn=SAVE gen=4294967295 w:err=EFFFFFFFF rb=UNAVAILABLE out=UNKNOWN_REBOOT p:err=EFFFFFFFF rb=UNAVAILABLE out=NOT_COMMITTED total_us=4294967294 -> REFUSED_LATCHED", txn_log_text(1, 3, []{ ecco_fbdurable::TxnResult r{}; r.w.err = -1; r.w.rb_class = 7; r.w.outcome = 0; r.w.us = 4294967295u; r.p.err = -1; r.p.rb_class = 7; r.p.outcome = 2; r.p.us = 4294967295u; r.witness_advanced = 0; r.refusal = 0; return r; }(), 4294967295u)), "FB-B2 text: txn_log_text op 1 outcome 3 w -1/7/0/4294967295 p -1/7/2/4294967295");
static_assert(text_is("txn=INVALIDATE gen=4294967295 w:err=- rb=NOT_READ out=UNKNOWN_REBOOT p:err=- rb=NOT_READ out=NOT_ATTEMPTED total_us=0 -> UNKNOWN_REBOOT", txn_log_text(2, 0, []{ ecco_fbdurable::TxnResult r{}; r.w.err = 0; r.w.rb_class = 0; r.w.outcome = 0; r.w.us = 0u; r.p.err = 0; r.p.rb_class = 0; r.p.outcome = 3; r.p.us = 0u; r.witness_advanced = 0; r.refusal = 0; return r; }(), 4294967295u)), "FB-B2 text: txn_log_text op 2 outcome 0 w 0/0/0/0 p 0/0/3/0");
static_assert(text_is("txn=INVALIDATE gen=4294967295 w:err=E1107 rb=PRIOR out=NOT_COMMITTED p:err=- rb=NOT_READ out=NOT_ATTEMPTED total_us=1239 -> UNKNOWN_REBOOT", txn_log_text(2, 0, []{ ecco_fbdurable::TxnResult r{}; r.w.err = 4359; r.w.rb_class = 2; r.w.outcome = 2; r.w.us = 1234u; r.p.err = 0; r.p.rb_class = 0; r.p.outcome = 3; r.p.us = 5u; r.witness_advanced = 0; r.refusal = 0; return r; }(), 4294967295u)), "FB-B2 text: txn_log_text op 2 outcome 0 w 4359/2/2/1234 p 0/0/3/5");
static_assert(text_is("txn=INVALIDATE gen=4294967295 w:err=- rb=NOT_READ out=COMMITTED p:err=- rb=NOT_READ out=COMMITTED total_us=150 -> UNKNOWN_REBOOT", txn_log_text(2, 0, []{ ecco_fbdurable::TxnResult r{}; r.w.err = 0; r.w.rb_class = 0; r.w.outcome = 1; r.w.us = 70u; r.p.err = 0; r.p.rb_class = 0; r.p.outcome = 1; r.p.us = 80u; r.witness_advanced = 0; r.refusal = 0; return r; }(), 4294967295u)), "FB-B2 text: txn_log_text op 2 outcome 0 w 0/0/1/70 p 0/0/1/80");
static_assert(text_is("txn=INVALIDATE gen=4294967295 w:err=EFFFFFFFF rb=UNAVAILABLE out=UNKNOWN_REBOOT p:err=EFFFFFFFF rb=UNAVAILABLE out=NOT_COMMITTED total_us=4294967294 -> UNKNOWN_REBOOT", txn_log_text(2, 0, []{ ecco_fbdurable::TxnResult r{}; r.w.err = -1; r.w.rb_class = 7; r.w.outcome = 0; r.w.us = 4294967295u; r.p.err = -1; r.p.rb_class = 7; r.p.outcome = 2; r.p.us = 4294967295u; r.witness_advanced = 0; r.refusal = 0; return r; }(), 4294967295u)), "FB-B2 text: txn_log_text op 2 outcome 0 w -1/7/0/4294967295 p -1/7/2/4294967295");
static_assert(text_is("txn=INVALIDATE gen=4294967295 w:err=- rb=NOT_READ out=UNKNOWN_REBOOT p:err=- rb=NOT_READ out=NOT_ATTEMPTED total_us=0 -> COMMITTED", txn_log_text(2, 1, []{ ecco_fbdurable::TxnResult r{}; r.w.err = 0; r.w.rb_class = 0; r.w.outcome = 0; r.w.us = 0u; r.p.err = 0; r.p.rb_class = 0; r.p.outcome = 3; r.p.us = 0u; r.witness_advanced = 0; r.refusal = 0; return r; }(), 4294967295u)), "FB-B2 text: txn_log_text op 2 outcome 1 w 0/0/0/0 p 0/0/3/0");
static_assert(text_is("txn=INVALIDATE gen=4294967295 w:err=E1107 rb=PRIOR out=NOT_COMMITTED p:err=- rb=NOT_READ out=NOT_ATTEMPTED total_us=1239 -> COMMITTED", txn_log_text(2, 1, []{ ecco_fbdurable::TxnResult r{}; r.w.err = 4359; r.w.rb_class = 2; r.w.outcome = 2; r.w.us = 1234u; r.p.err = 0; r.p.rb_class = 0; r.p.outcome = 3; r.p.us = 5u; r.witness_advanced = 0; r.refusal = 0; return r; }(), 4294967295u)), "FB-B2 text: txn_log_text op 2 outcome 1 w 4359/2/2/1234 p 0/0/3/5");
static_assert(text_is("txn=INVALIDATE gen=4294967295 w:err=- rb=NOT_READ out=COMMITTED p:err=- rb=NOT_READ out=COMMITTED total_us=150 -> COMMITTED", txn_log_text(2, 1, []{ ecco_fbdurable::TxnResult r{}; r.w.err = 0; r.w.rb_class = 0; r.w.outcome = 1; r.w.us = 70u; r.p.err = 0; r.p.rb_class = 0; r.p.outcome = 1; r.p.us = 80u; r.witness_advanced = 0; r.refusal = 0; return r; }(), 4294967295u)), "FB-B2 text: txn_log_text op 2 outcome 1 w 0/0/1/70 p 0/0/1/80");
static_assert(text_is("txn=INVALIDATE gen=4294967295 w:err=EFFFFFFFF rb=UNAVAILABLE out=UNKNOWN_REBOOT p:err=EFFFFFFFF rb=UNAVAILABLE out=NOT_COMMITTED total_us=4294967294 -> COMMITTED", txn_log_text(2, 1, []{ ecco_fbdurable::TxnResult r{}; r.w.err = -1; r.w.rb_class = 7; r.w.outcome = 0; r.w.us = 4294967295u; r.p.err = -1; r.p.rb_class = 7; r.p.outcome = 2; r.p.us = 4294967295u; r.witness_advanced = 0; r.refusal = 0; return r; }(), 4294967295u)), "FB-B2 text: txn_log_text op 2 outcome 1 w -1/7/0/4294967295 p -1/7/2/4294967295");
static_assert(text_is("txn=INVALIDATE gen=4294967295 w:err=- rb=NOT_READ out=UNKNOWN_REBOOT p:err=- rb=NOT_READ out=NOT_ATTEMPTED total_us=0 -> NOT_COMMITTED", txn_log_text(2, 2, []{ ecco_fbdurable::TxnResult r{}; r.w.err = 0; r.w.rb_class = 0; r.w.outcome = 0; r.w.us = 0u; r.p.err = 0; r.p.rb_class = 0; r.p.outcome = 3; r.p.us = 0u; r.witness_advanced = 0; r.refusal = 0; return r; }(), 4294967295u)), "FB-B2 text: txn_log_text op 2 outcome 2 w 0/0/0/0 p 0/0/3/0");
static_assert(text_is("txn=INVALIDATE gen=4294967295 w:err=E1107 rb=PRIOR out=NOT_COMMITTED p:err=- rb=NOT_READ out=NOT_ATTEMPTED total_us=1239 -> NOT_COMMITTED", txn_log_text(2, 2, []{ ecco_fbdurable::TxnResult r{}; r.w.err = 4359; r.w.rb_class = 2; r.w.outcome = 2; r.w.us = 1234u; r.p.err = 0; r.p.rb_class = 0; r.p.outcome = 3; r.p.us = 5u; r.witness_advanced = 0; r.refusal = 0; return r; }(), 4294967295u)), "FB-B2 text: txn_log_text op 2 outcome 2 w 4359/2/2/1234 p 0/0/3/5");
static_assert(text_is("txn=INVALIDATE gen=4294967295 w:err=- rb=NOT_READ out=COMMITTED p:err=- rb=NOT_READ out=COMMITTED total_us=150 -> NOT_COMMITTED", txn_log_text(2, 2, []{ ecco_fbdurable::TxnResult r{}; r.w.err = 0; r.w.rb_class = 0; r.w.outcome = 1; r.w.us = 70u; r.p.err = 0; r.p.rb_class = 0; r.p.outcome = 1; r.p.us = 80u; r.witness_advanced = 0; r.refusal = 0; return r; }(), 4294967295u)), "FB-B2 text: txn_log_text op 2 outcome 2 w 0/0/1/70 p 0/0/1/80");
static_assert(text_is("txn=INVALIDATE gen=4294967295 w:err=EFFFFFFFF rb=UNAVAILABLE out=UNKNOWN_REBOOT p:err=EFFFFFFFF rb=UNAVAILABLE out=NOT_COMMITTED total_us=4294967294 -> NOT_COMMITTED", txn_log_text(2, 2, []{ ecco_fbdurable::TxnResult r{}; r.w.err = -1; r.w.rb_class = 7; r.w.outcome = 0; r.w.us = 4294967295u; r.p.err = -1; r.p.rb_class = 7; r.p.outcome = 2; r.p.us = 4294967295u; r.witness_advanced = 0; r.refusal = 0; return r; }(), 4294967295u)), "FB-B2 text: txn_log_text op 2 outcome 2 w -1/7/0/4294967295 p -1/7/2/4294967295");
static_assert(text_is("txn=INVALIDATE gen=4294967295 w:err=- rb=NOT_READ out=UNKNOWN_REBOOT p:err=- rb=NOT_READ out=NOT_ATTEMPTED total_us=0 -> REFUSED_LATCHED", txn_log_text(2, 3, []{ ecco_fbdurable::TxnResult r{}; r.w.err = 0; r.w.rb_class = 0; r.w.outcome = 0; r.w.us = 0u; r.p.err = 0; r.p.rb_class = 0; r.p.outcome = 3; r.p.us = 0u; r.witness_advanced = 0; r.refusal = 0; return r; }(), 4294967295u)), "FB-B2 text: txn_log_text op 2 outcome 3 w 0/0/0/0 p 0/0/3/0");
static_assert(text_is("txn=INVALIDATE gen=4294967295 w:err=E1107 rb=PRIOR out=NOT_COMMITTED p:err=- rb=NOT_READ out=NOT_ATTEMPTED total_us=1239 -> REFUSED_LATCHED", txn_log_text(2, 3, []{ ecco_fbdurable::TxnResult r{}; r.w.err = 4359; r.w.rb_class = 2; r.w.outcome = 2; r.w.us = 1234u; r.p.err = 0; r.p.rb_class = 0; r.p.outcome = 3; r.p.us = 5u; r.witness_advanced = 0; r.refusal = 0; return r; }(), 4294967295u)), "FB-B2 text: txn_log_text op 2 outcome 3 w 4359/2/2/1234 p 0/0/3/5");
static_assert(text_is("txn=INVALIDATE gen=4294967295 w:err=- rb=NOT_READ out=COMMITTED p:err=- rb=NOT_READ out=COMMITTED total_us=150 -> REFUSED_LATCHED", txn_log_text(2, 3, []{ ecco_fbdurable::TxnResult r{}; r.w.err = 0; r.w.rb_class = 0; r.w.outcome = 1; r.w.us = 70u; r.p.err = 0; r.p.rb_class = 0; r.p.outcome = 1; r.p.us = 80u; r.witness_advanced = 0; r.refusal = 0; return r; }(), 4294967295u)), "FB-B2 text: txn_log_text op 2 outcome 3 w 0/0/1/70 p 0/0/1/80");
static_assert(text_is("txn=INVALIDATE gen=4294967295 w:err=EFFFFFFFF rb=UNAVAILABLE out=UNKNOWN_REBOOT p:err=EFFFFFFFF rb=UNAVAILABLE out=NOT_COMMITTED total_us=4294967294 -> REFUSED_LATCHED", txn_log_text(2, 3, []{ ecco_fbdurable::TxnResult r{}; r.w.err = -1; r.w.rb_class = 7; r.w.outcome = 0; r.w.us = 4294967295u; r.p.err = -1; r.p.rb_class = 7; r.p.outcome = 2; r.p.us = 4294967295u; r.witness_advanced = 0; r.refusal = 0; return r; }(), 4294967295u)), "FB-B2 text: txn_log_text op 2 outcome 3 w -1/7/0/4294967295 p -1/7/2/4294967295");
static_assert(text_is("txn=REPLACE_CORRUPT gen=4294967295 w:err=- rb=NOT_READ out=UNKNOWN_REBOOT p:err=- rb=NOT_READ out=NOT_ATTEMPTED total_us=0 -> UNKNOWN_REBOOT", txn_log_text(3, 0, []{ ecco_fbdurable::TxnResult r{}; r.w.err = 0; r.w.rb_class = 0; r.w.outcome = 0; r.w.us = 0u; r.p.err = 0; r.p.rb_class = 0; r.p.outcome = 3; r.p.us = 0u; r.witness_advanced = 0; r.refusal = 0; return r; }(), 4294967295u)), "FB-B2 text: txn_log_text op 3 outcome 0 w 0/0/0/0 p 0/0/3/0");
static_assert(text_is("txn=REPLACE_CORRUPT gen=4294967295 w:err=E1107 rb=PRIOR out=NOT_COMMITTED p:err=- rb=NOT_READ out=NOT_ATTEMPTED total_us=1239 -> UNKNOWN_REBOOT", txn_log_text(3, 0, []{ ecco_fbdurable::TxnResult r{}; r.w.err = 4359; r.w.rb_class = 2; r.w.outcome = 2; r.w.us = 1234u; r.p.err = 0; r.p.rb_class = 0; r.p.outcome = 3; r.p.us = 5u; r.witness_advanced = 0; r.refusal = 0; return r; }(), 4294967295u)), "FB-B2 text: txn_log_text op 3 outcome 0 w 4359/2/2/1234 p 0/0/3/5");
static_assert(text_is("txn=REPLACE_CORRUPT gen=4294967295 w:err=- rb=NOT_READ out=COMMITTED p:err=- rb=NOT_READ out=COMMITTED total_us=150 -> UNKNOWN_REBOOT", txn_log_text(3, 0, []{ ecco_fbdurable::TxnResult r{}; r.w.err = 0; r.w.rb_class = 0; r.w.outcome = 1; r.w.us = 70u; r.p.err = 0; r.p.rb_class = 0; r.p.outcome = 1; r.p.us = 80u; r.witness_advanced = 0; r.refusal = 0; return r; }(), 4294967295u)), "FB-B2 text: txn_log_text op 3 outcome 0 w 0/0/1/70 p 0/0/1/80");
static_assert(text_is("txn=REPLACE_CORRUPT gen=4294967295 w:err=EFFFFFFFF rb=UNAVAILABLE out=UNKNOWN_REBOOT p:err=EFFFFFFFF rb=UNAVAILABLE out=NOT_COMMITTED total_us=4294967294 -> UNKNOWN_REBOOT", txn_log_text(3, 0, []{ ecco_fbdurable::TxnResult r{}; r.w.err = -1; r.w.rb_class = 7; r.w.outcome = 0; r.w.us = 4294967295u; r.p.err = -1; r.p.rb_class = 7; r.p.outcome = 2; r.p.us = 4294967295u; r.witness_advanced = 0; r.refusal = 0; return r; }(), 4294967295u)), "FB-B2 text: txn_log_text op 3 outcome 0 w -1/7/0/4294967295 p -1/7/2/4294967295");
static_assert(text_is("txn=REPLACE_CORRUPT gen=4294967295 w:err=- rb=NOT_READ out=UNKNOWN_REBOOT p:err=- rb=NOT_READ out=NOT_ATTEMPTED total_us=0 -> COMMITTED", txn_log_text(3, 1, []{ ecco_fbdurable::TxnResult r{}; r.w.err = 0; r.w.rb_class = 0; r.w.outcome = 0; r.w.us = 0u; r.p.err = 0; r.p.rb_class = 0; r.p.outcome = 3; r.p.us = 0u; r.witness_advanced = 0; r.refusal = 0; return r; }(), 4294967295u)), "FB-B2 text: txn_log_text op 3 outcome 1 w 0/0/0/0 p 0/0/3/0");
static_assert(text_is("txn=REPLACE_CORRUPT gen=4294967295 w:err=E1107 rb=PRIOR out=NOT_COMMITTED p:err=- rb=NOT_READ out=NOT_ATTEMPTED total_us=1239 -> COMMITTED", txn_log_text(3, 1, []{ ecco_fbdurable::TxnResult r{}; r.w.err = 4359; r.w.rb_class = 2; r.w.outcome = 2; r.w.us = 1234u; r.p.err = 0; r.p.rb_class = 0; r.p.outcome = 3; r.p.us = 5u; r.witness_advanced = 0; r.refusal = 0; return r; }(), 4294967295u)), "FB-B2 text: txn_log_text op 3 outcome 1 w 4359/2/2/1234 p 0/0/3/5");
static_assert(text_is("txn=REPLACE_CORRUPT gen=4294967295 w:err=- rb=NOT_READ out=COMMITTED p:err=- rb=NOT_READ out=COMMITTED total_us=150 -> COMMITTED", txn_log_text(3, 1, []{ ecco_fbdurable::TxnResult r{}; r.w.err = 0; r.w.rb_class = 0; r.w.outcome = 1; r.w.us = 70u; r.p.err = 0; r.p.rb_class = 0; r.p.outcome = 1; r.p.us = 80u; r.witness_advanced = 0; r.refusal = 0; return r; }(), 4294967295u)), "FB-B2 text: txn_log_text op 3 outcome 1 w 0/0/1/70 p 0/0/1/80");
static_assert(text_is("txn=REPLACE_CORRUPT gen=4294967295 w:err=EFFFFFFFF rb=UNAVAILABLE out=UNKNOWN_REBOOT p:err=EFFFFFFFF rb=UNAVAILABLE out=NOT_COMMITTED total_us=4294967294 -> COMMITTED", txn_log_text(3, 1, []{ ecco_fbdurable::TxnResult r{}; r.w.err = -1; r.w.rb_class = 7; r.w.outcome = 0; r.w.us = 4294967295u; r.p.err = -1; r.p.rb_class = 7; r.p.outcome = 2; r.p.us = 4294967295u; r.witness_advanced = 0; r.refusal = 0; return r; }(), 4294967295u)), "FB-B2 text: txn_log_text op 3 outcome 1 w -1/7/0/4294967295 p -1/7/2/4294967295");
static_assert(text_is("txn=REPLACE_CORRUPT gen=4294967295 w:err=- rb=NOT_READ out=UNKNOWN_REBOOT p:err=- rb=NOT_READ out=NOT_ATTEMPTED total_us=0 -> NOT_COMMITTED", txn_log_text(3, 2, []{ ecco_fbdurable::TxnResult r{}; r.w.err = 0; r.w.rb_class = 0; r.w.outcome = 0; r.w.us = 0u; r.p.err = 0; r.p.rb_class = 0; r.p.outcome = 3; r.p.us = 0u; r.witness_advanced = 0; r.refusal = 0; return r; }(), 4294967295u)), "FB-B2 text: txn_log_text op 3 outcome 2 w 0/0/0/0 p 0/0/3/0");
static_assert(text_is("txn=REPLACE_CORRUPT gen=4294967295 w:err=E1107 rb=PRIOR out=NOT_COMMITTED p:err=- rb=NOT_READ out=NOT_ATTEMPTED total_us=1239 -> NOT_COMMITTED", txn_log_text(3, 2, []{ ecco_fbdurable::TxnResult r{}; r.w.err = 4359; r.w.rb_class = 2; r.w.outcome = 2; r.w.us = 1234u; r.p.err = 0; r.p.rb_class = 0; r.p.outcome = 3; r.p.us = 5u; r.witness_advanced = 0; r.refusal = 0; return r; }(), 4294967295u)), "FB-B2 text: txn_log_text op 3 outcome 2 w 4359/2/2/1234 p 0/0/3/5");
static_assert(text_is("txn=REPLACE_CORRUPT gen=4294967295 w:err=- rb=NOT_READ out=COMMITTED p:err=- rb=NOT_READ out=COMMITTED total_us=150 -> NOT_COMMITTED", txn_log_text(3, 2, []{ ecco_fbdurable::TxnResult r{}; r.w.err = 0; r.w.rb_class = 0; r.w.outcome = 1; r.w.us = 70u; r.p.err = 0; r.p.rb_class = 0; r.p.outcome = 1; r.p.us = 80u; r.witness_advanced = 0; r.refusal = 0; return r; }(), 4294967295u)), "FB-B2 text: txn_log_text op 3 outcome 2 w 0/0/1/70 p 0/0/1/80");
static_assert(text_is("txn=REPLACE_CORRUPT gen=4294967295 w:err=EFFFFFFFF rb=UNAVAILABLE out=UNKNOWN_REBOOT p:err=EFFFFFFFF rb=UNAVAILABLE out=NOT_COMMITTED total_us=4294967294 -> NOT_COMMITTED", txn_log_text(3, 2, []{ ecco_fbdurable::TxnResult r{}; r.w.err = -1; r.w.rb_class = 7; r.w.outcome = 0; r.w.us = 4294967295u; r.p.err = -1; r.p.rb_class = 7; r.p.outcome = 2; r.p.us = 4294967295u; r.witness_advanced = 0; r.refusal = 0; return r; }(), 4294967295u)), "FB-B2 text: txn_log_text op 3 outcome 2 w -1/7/0/4294967295 p -1/7/2/4294967295");
static_assert(text_is("txn=REPLACE_CORRUPT gen=4294967295 w:err=- rb=NOT_READ out=UNKNOWN_REBOOT p:err=- rb=NOT_READ out=NOT_ATTEMPTED total_us=0 -> REFUSED_LATCHED", txn_log_text(3, 3, []{ ecco_fbdurable::TxnResult r{}; r.w.err = 0; r.w.rb_class = 0; r.w.outcome = 0; r.w.us = 0u; r.p.err = 0; r.p.rb_class = 0; r.p.outcome = 3; r.p.us = 0u; r.witness_advanced = 0; r.refusal = 0; return r; }(), 4294967295u)), "FB-B2 text: txn_log_text op 3 outcome 3 w 0/0/0/0 p 0/0/3/0");
static_assert(text_is("txn=REPLACE_CORRUPT gen=4294967295 w:err=E1107 rb=PRIOR out=NOT_COMMITTED p:err=- rb=NOT_READ out=NOT_ATTEMPTED total_us=1239 -> REFUSED_LATCHED", txn_log_text(3, 3, []{ ecco_fbdurable::TxnResult r{}; r.w.err = 4359; r.w.rb_class = 2; r.w.outcome = 2; r.w.us = 1234u; r.p.err = 0; r.p.rb_class = 0; r.p.outcome = 3; r.p.us = 5u; r.witness_advanced = 0; r.refusal = 0; return r; }(), 4294967295u)), "FB-B2 text: txn_log_text op 3 outcome 3 w 4359/2/2/1234 p 0/0/3/5");
static_assert(text_is("txn=REPLACE_CORRUPT gen=4294967295 w:err=- rb=NOT_READ out=COMMITTED p:err=- rb=NOT_READ out=COMMITTED total_us=150 -> REFUSED_LATCHED", txn_log_text(3, 3, []{ ecco_fbdurable::TxnResult r{}; r.w.err = 0; r.w.rb_class = 0; r.w.outcome = 1; r.w.us = 70u; r.p.err = 0; r.p.rb_class = 0; r.p.outcome = 1; r.p.us = 80u; r.witness_advanced = 0; r.refusal = 0; return r; }(), 4294967295u)), "FB-B2 text: txn_log_text op 3 outcome 3 w 0/0/1/70 p 0/0/1/80");
static_assert(text_is("txn=REPLACE_CORRUPT gen=4294967295 w:err=EFFFFFFFF rb=UNAVAILABLE out=UNKNOWN_REBOOT p:err=EFFFFFFFF rb=UNAVAILABLE out=NOT_COMMITTED total_us=4294967294 -> REFUSED_LATCHED", txn_log_text(3, 3, []{ ecco_fbdurable::TxnResult r{}; r.w.err = -1; r.w.rb_class = 7; r.w.outcome = 0; r.w.us = 4294967295u; r.p.err = -1; r.p.rb_class = 7; r.p.outcome = 2; r.p.us = 4294967295u; r.witness_advanced = 0; r.refusal = 0; return r; }(), 4294967295u)), "FB-B2 text: txn_log_text op 3 outcome 3 w -1/7/0/4294967295 p -1/7/2/4294967295");
static_assert(text_is("SAVE REFUSED - internal: write refused for an unknown reason; nothing written", txn_refusal_text(1, 0)), "FB-B2 text: txn_refusal_text op 1 refusal 0");
static_assert(text_is("INVALIDATE REFUSED - internal: write refused for an unknown reason; nothing written", txn_refusal_text(2, 0)), "FB-B2 text: txn_refusal_text op 2 refusal 0");
static_assert(text_is("SAVE REFUSED - internal: write refused for an unknown reason; nothing written", txn_refusal_text(1, 1)), "FB-B2 text: txn_refusal_text op 1 refusal 1");
static_assert(text_is("INVALIDATE REFUSED - internal: write refused for an unknown reason; nothing written", txn_refusal_text(2, 1)), "FB-B2 text: txn_refusal_text op 2 refusal 1");
static_assert(text_is("SAVE REFUSED - previous save outcome unknown this boot - reboot to re-verify first", txn_refusal_text(1, 2)), "FB-B2 text: txn_refusal_text op 1 refusal 2");
static_assert(text_is("INVALIDATE REFUSED - previous Fallback Profile write outcome unknown this boot - reboot to re-verify first", txn_refusal_text(2, 2)), "FB-B2 text: txn_refusal_text op 2 refusal 2");
static_assert(text_is("SAVE REFUSED - internal: built record did not validate; nothing written", txn_refusal_text(1, 3)), "FB-B2 text: txn_refusal_text op 1 refusal 3");
static_assert(text_is("INVALIDATE REFUSED - internal: built record did not validate; nothing written", txn_refusal_text(2, 3)), "FB-B2 text: txn_refusal_text op 2 refusal 3");
static_assert(text_is("SAVE REFUSED - storage unavailable - nothing saved", txn_refusal_text(1, 4)), "FB-B2 text: txn_refusal_text op 1 refusal 4");
static_assert(text_is("INVALIDATE REFUSED - storage unavailable - nothing written", txn_refusal_text(2, 4)), "FB-B2 text: txn_refusal_text op 2 refusal 4");
static_assert(text_is("SAVE REFUSED - storage not healthy - nothing saved", txn_refusal_text(1, 5)), "FB-B2 text: txn_refusal_text op 1 refusal 5");
static_assert(text_is("INVALIDATE REFUSED - storage not healthy - nothing written", txn_refusal_text(2, 5)), "FB-B2 text: txn_refusal_text op 2 refusal 5");
static_assert(text_is("SAVE REFUSED - internal: write refused for an unknown reason; nothing written", txn_refusal_text(1, 6)), "FB-B2 text: txn_refusal_text op 1 refusal 6");
static_assert(text_is("INVALIDATE REFUSED - internal: write refused for an unknown reason; nothing written", txn_refusal_text(2, 6)), "FB-B2 text: txn_refusal_text op 2 refusal 6");
static_assert(text_is("SAVED - known-good profile generation 0 saved (verified this boot)", saved_text(0u)), "FB-B2 text: saved_text 0");
static_assert(text_is("INVALIDATED - profile generation 0 is no longer usable (now INVALIDATED g1); payload kept for reference; save a new profile to re-enable", invalidated_text(0u, 1u)), "FB-B2 text: invalidated_text 0");
static_assert(text_is("INVALIDATE NOT COMMITTED - storage refused the write (EFFFFFFFF); profile still VALID g0", invalidate_not_committed_text(4294967295u, 0u)), "FB-B2 text: invalidate_not_committed_text g 0");
static_assert(text_is("INVALIDATE NOT COMMITTED for the profile record, but the generation record advanced: g0 is now STALE (unusable)", invalidate_witness_advanced_text(0u)), "FB-B2 text: invalidate_witness_advanced_text g 0");
static_assert(text_is("SAVED - known-good profile generation 1 saved (verified this boot)", saved_text(1u)), "FB-B2 text: saved_text 1");
static_assert(text_is("INVALIDATED - profile generation 1 is no longer usable (now INVALIDATED g2); payload kept for reference; save a new profile to re-enable", invalidated_text(1u, 2u)), "FB-B2 text: invalidated_text 1");
static_assert(text_is("INVALIDATE NOT COMMITTED - storage refused the write (EFFFFFFFF); profile still VALID g1", invalidate_not_committed_text(4294967295u, 1u)), "FB-B2 text: invalidate_not_committed_text g 1");
static_assert(text_is("INVALIDATE NOT COMMITTED for the profile record, but the generation record advanced: g1 is now STALE (unusable)", invalidate_witness_advanced_text(1u)), "FB-B2 text: invalidate_witness_advanced_text g 1");
static_assert(text_is("SAVED - known-good profile generation 7 saved (verified this boot)", saved_text(7u)), "FB-B2 text: saved_text 7");
static_assert(text_is("INVALIDATED - profile generation 7 is no longer usable (now INVALIDATED g8); payload kept for reference; save a new profile to re-enable", invalidated_text(7u, 8u)), "FB-B2 text: invalidated_text 7");
static_assert(text_is("INVALIDATE NOT COMMITTED - storage refused the write (EFFFFFFFF); profile still VALID g7", invalidate_not_committed_text(4294967295u, 7u)), "FB-B2 text: invalidate_not_committed_text g 7");
static_assert(text_is("INVALIDATE NOT COMMITTED for the profile record, but the generation record advanced: g7 is now STALE (unusable)", invalidate_witness_advanced_text(7u)), "FB-B2 text: invalidate_witness_advanced_text g 7");
static_assert(text_is("SAVED - known-good profile generation 4294967295 saved (verified this boot)", saved_text(4294967295u)), "FB-B2 text: saved_text 4294967295");
static_assert(text_is("INVALIDATED - profile generation 4294967295 is no longer usable (now INVALIDATED g0); payload kept for reference; save a new profile to re-enable", invalidated_text(4294967295u, 0u)), "FB-B2 text: invalidated_text 4294967295");
static_assert(text_is("INVALIDATE NOT COMMITTED - storage refused the write (EFFFFFFFF); profile still VALID g4294967295", invalidate_not_committed_text(4294967295u, 4294967295u)), "FB-B2 text: invalidate_not_committed_text g 4294967295");
static_assert(text_is("INVALIDATE NOT COMMITTED for the profile record, but the generation record advanced: g4294967295 is now STALE (unusable)", invalidate_witness_advanced_text(4294967295u)), "FB-B2 text: invalidate_witness_advanced_text g 4294967295");
static_assert(text_is("SAVE NOT COMMITTED - storage refused the write (-); nothing changed", save_not_committed_text(0u)), "FB-B2 text: save_not_committed_text err 0");
static_assert(text_is("SAVE OUTCOME UNKNOWN - storage reported -/OTHER_BYTES; reboot the dongle (when no temporary operation is active) to re-verify; saving disabled until then", save_unknown_text([]{ ecco_fbdurable::TxnResult r{}; r.w.err = 0; r.w.rb_class = 3; r.w.outcome = 0; r.w.us = 0u; r.p.err = 0; r.p.rb_class = 0; r.p.outcome = 3; r.p.us = 0u; r.witness_advanced = 0; r.refusal = 0; return r; }())), "FB-B2 text: save_unknown_text w err 0");
static_assert(text_is("INVALIDATE OUTCOME UNKNOWN - -/OTHER_BYTES; treat the profile as unusable; reboot to re-verify (Fallback Profile writes locked until reboot)", invalidate_unknown_text([]{ ecco_fbdurable::TxnResult r{}; r.w.err = 0; r.w.rb_class = 3; r.w.outcome = 0; r.w.us = 0u; r.p.err = 0; r.p.rb_class = 0; r.p.outcome = 3; r.p.us = 0u; r.witness_advanced = 0; r.refusal = 0; return r; }())), "FB-B2 text: invalidate_unknown_text w err 0");
static_assert(text_is("SAVE NOT COMMITTED - storage refused the write (E1107); nothing changed", save_not_committed_text(4359u)), "FB-B2 text: save_not_committed_text err 4359");
static_assert(text_is("SAVE OUTCOME UNKNOWN - storage reported E1107/OTHER_BYTES; reboot the dongle (when no temporary operation is active) to re-verify; saving disabled until then", save_unknown_text([]{ ecco_fbdurable::TxnResult r{}; r.w.err = 4359; r.w.rb_class = 3; r.w.outcome = 0; r.w.us = 0u; r.p.err = 0; r.p.rb_class = 0; r.p.outcome = 3; r.p.us = 0u; r.witness_advanced = 0; r.refusal = 0; return r; }())), "FB-B2 text: save_unknown_text w err 4359");
static_assert(text_is("INVALIDATE OUTCOME UNKNOWN - E1107/OTHER_BYTES; treat the profile as unusable; reboot to re-verify (Fallback Profile writes locked until reboot)", invalidate_unknown_text([]{ ecco_fbdurable::TxnResult r{}; r.w.err = 4359; r.w.rb_class = 3; r.w.outcome = 0; r.w.us = 0u; r.p.err = 0; r.p.rb_class = 0; r.p.outcome = 3; r.p.us = 0u; r.witness_advanced = 0; r.refusal = 0; return r; }())), "FB-B2 text: invalidate_unknown_text w err 4359");
static_assert(text_is("SAVE NOT COMMITTED - storage refused the write (EFFFFFFFF); nothing changed", save_not_committed_text(4294967295u)), "FB-B2 text: save_not_committed_text err 4294967295");
static_assert(text_is("SAVE OUTCOME UNKNOWN - storage reported EFFFFFFFF/OTHER_BYTES; reboot the dongle (when no temporary operation is active) to re-verify; saving disabled until then", save_unknown_text([]{ ecco_fbdurable::TxnResult r{}; r.w.err = -1; r.w.rb_class = 3; r.w.outcome = 0; r.w.us = 0u; r.p.err = 0; r.p.rb_class = 0; r.p.outcome = 3; r.p.us = 0u; r.witness_advanced = 0; r.refusal = 0; return r; }())), "FB-B2 text: save_unknown_text w err 4294967295");
static_assert(text_is("INVALIDATE OUTCOME UNKNOWN - EFFFFFFFF/OTHER_BYTES; treat the profile as unusable; reboot to re-verify (Fallback Profile writes locked until reboot)", invalidate_unknown_text([]{ ecco_fbdurable::TxnResult r{}; r.w.err = -1; r.w.rb_class = 3; r.w.outcome = 0; r.w.us = 0u; r.p.err = 0; r.p.rb_class = 0; r.p.outcome = 3; r.p.us = 0u; r.witness_advanced = 0; r.refusal = 0; return r; }())), "FB-B2 text: invalidate_unknown_text w err 4294967295");
static_assert(text_is("SAVE OUTCOME UNKNOWN - storage reported E1105/WRONG_SIZE; reboot the dongle (when no temporary operation is active) to re-verify; saving disabled until then", save_unknown_text([]{ ecco_fbdurable::TxnResult r{}; r.w.err = 0; r.w.rb_class = 1; r.w.outcome = 1; r.w.us = 0u; r.p.err = 4357; r.p.rb_class = 5; r.p.outcome = 0; r.p.us = 0u; r.witness_advanced = 0; r.refusal = 0; return r; }())), "FB-B2 text: save_unknown_text: the witness COMMITTED, the profile write is the unknown key");
static_assert(text_is("g=7;id=D852A4FA2DF7DBA3;at=1790000000;ld=OK;df=-;w=OK;hw=7;op=SAVE;why=-;werr=E1107;us=1200", ecco_fbcap::b2_text(0, ecco_fbcap::GOLDEN_PROFILE, 0, ecco_fbcap::GOLDEN_WITNESS, 0, first_non_ok(0x1107, 0), total_us(1200u, 0u))), "FB-B2 text: b2_text with werr / us derived from a refused witness write (first_non_ok, total_us)");
static_assert(text_is("st=SAVING;prior=-;exp=-;warn=-;obl=FP:CA,DP:CA,R4:CA,MT:CN,FS:CA,BUS:BY;latch=-;sv=-", ecco_fbcap::b3_text(ecco_fbcap::CAPTURE_SAVING, false, 0, 0, 0, "FP:CA,DP:CA,R4:CA,MT:CN,FS:CA,BUS:BY", 0u, "-")), "FB-B2 text: b3_text with the SAVING state (D8): the candidate is consumed, obl and latch persist");
static_assert(text_is("CANDIDATE READY - both read passes agree on all 31 registers; check the values, then arm and save within 120 s", ecco_fbcap::candidate_ready_text()), "FB-B2 text: candidate_ready_text (D8: the FB-B2 wording)");
static_assert(([]{ size_t m = 0; for (uint8_t s = 0; s < 6; s++) { for (uint8_t k = 0; k < 15; k++) { for (uint8_t b = 0; b < 20; b++) { const TextBuf t = save_slot_refusal_text(s, ecco_fbcap::SlotClass{k, b}, 255, "Register 244 test", 4294967u); if (t.overflow) return (size_t) 9999; if (t.size() > m) m = t.size(); } } } return m; }()) == 189, "FB-B2 value: length of the longest save_slot_refusal_text over every slot, kind and basis (never overflows; <= 200)");
static_assert(([]{ size_t m = 0; for (uint8_t op = 1; op <= 3; op++) { for (uint8_t o = 0; o < 4; o++) { for (uint8_t rb = 0; rb < 9; rb++) { for (uint8_t adv = 0; adv < 2; adv++) { for (uint8_t rf = 0; rf < 6; rf++) { ecco_fbdurable::TxnResult r{}; r.w.err = -1; r.w.rb_class = rb; r.w.outcome = 0; r.w.us = 4294967295u; r.p.err = -1; r.p.rb_class = rb; r.p.us = 4294967295u; r.witness_advanced = adv; r.refusal = rf; const TextBuf t = txn_outcome_text(op, o, r, 4294967295u, 4294967294u); if (t.overflow) return (size_t) 9999; if (t.size() > m) m = t.size(); const TextBuf l = txn_log_text(op, o, r, 4294967295u); if (l.overflow) return (size_t) 9999; if (l.size() > m) m = l.size(); } } } } } return m; }()) == 185, "FB-B2 value: length of the longest txn_outcome_text / txn_log_text over every op, outcome, readback class, witness_advanced and refusal (never overflows)");
static_assert((save_unknown_text([]{ ecco_fbdurable::TxnResult r{}; r.w.err = -1; r.w.rb_class = 4; r.w.outcome = 0; r.w.us = 0u; r.p.err = 0; r.p.rb_class = 0; r.p.outcome = 3; r.p.us = 0u; r.witness_advanced = 0; r.refusal = 0; return r; }()).size()) == 167, "FB-B2 value: length of the SAVE UNKNOWN text at its widest");
static_assert((invalidated_text(4294967294u, 4294967295u).size()) == 154, "FB-B2 value: length of the INVALIDATED text at its widest (both generations 10 digits)");
static_assert((invalidate_unknown_text([]{ ecco_fbdurable::TxnResult r{}; r.w.err = -1; r.w.rb_class = 4; r.w.outcome = 0; r.w.us = 0u; r.p.err = 0; r.p.rb_class = 0; r.p.outcome = 3; r.p.us = 0u; r.witness_advanced = 0; r.refusal = 0; return r; }()).size()) == 154, "FB-B2 value: length of the INVALIDATE UNKNOWN text at its widest");
static_assert((save_phrase_text(expected_phrase(PHRASE_SAVE_REPLACE_CORRUPT, 0xFFFFFFFFFFFFFFFFULL)).size() * 1000u + invalidate_phrase_text(expected_phrase(PHRASE_INVALIDATE, 0xFFFFFFFFFFFFFFFFULL)).size()) == 94090, "FB-B2 value: length of save_phrase_text / invalidate_phrase_text at their widest (id FFFFFFFFFFFFFFFF, REPLACE CORRUPT)");
static_assert((unsupported_action_text("yyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyy", 100).size()) == 55, "FB-B2 value: length of the longest unsupported_action_text (a 100-byte token is cut at 24)");
static_assert((save_read_fail_text(ecco_fbcap::READ_EXCEPTION, 2, 255).size()) == 91, "FB-B2 value: length of save_read_fail_text at its widest (exception code, longest block name)");
static_assert((save_changed_since_review_text(ecco_fbcap::golden_words_all(65535u), ecco_fbcap::golden_words_all(0u)).size() * 1000u + save_changed_during_read_text(ecco_fbcap::golden_words_all(65535u), ecco_fbcap::golden_words_all(0u)).size()) == 125105, "FB-B2 value: length of save_changed_since_review_text / save_changed_during_read_text at their widest (65535 words)");
static_assert((save_l2_text(ecco_fbcap::capture_refusals(ecco_fbcap::golden_words_all(65535u), 8000u), ecco_fbcap::golden_words_all(65535u)).size()) == 97, "FB-B2 value: length of save_l2_text at its widest (every register wrong)");
static_assert((replace_corrupt_log_text(ecco_fallback::LOAD_OK, ecco_fbcap::GOLDEN_PROFILE, 0u, 0).size() * 1000u + replace_corrupt_log_text(ecco_fallback::LOAD_OK, ecco_fbcap::GOLDEN_PROFILE, 0u, 1).size()) == 148149, "FB-B2 value: lengths of the two replace_corrupt_log_text parts (hex of 48 bytes each)");
static_assert(([]{ TextBuf t; for (size_t i = 0; i < 201; i++) put_char(t, 'x'); return t.overflow ? 1 : 0; }()) == 1, "FB-B2 value: an overflowing text would be flagged: the capture TextBuf at its cap reports overflow on the 201st character (the control of every no-overflow golden)");
static_assert(text_is("", []{ const GateInputs g = fx_gate(0); return save_gate_refusal_text(ecco_fbcap::gate_decide(g, ecco_fbcap::ProbeResults{}), g); }()), "FB-B2 text: save_gate_refusal_text of gate_decide over scenario 0");
static_assert(text_is("SAVE REFUSED - another Fallback Profile operation is in progress", []{ const GateInputs g = fx_gate(1); return save_gate_refusal_text(ecco_fbcap::gate_decide(g, ecco_fbcap::ProbeResults{}), g); }()), "FB-B2 text: save_gate_refusal_text of gate_decide over scenario 1");
static_assert(text_is("SAVE REFUSED - another Fallback Profile operation is in progress", []{ const GateInputs g = fx_gate(2); return save_gate_refusal_text(ecco_fbcap::gate_decide(g, ecco_fbcap::ProbeResults{}), g); }()), "FB-B2 text: save_gate_refusal_text of gate_decide over scenario 2");
static_assert(text_is("SAVE REFUSED - durable state not loaded yet", []{ const GateInputs g = fx_gate(3); return save_gate_refusal_text(ecco_fbcap::gate_decide(g, ecco_fbcap::ProbeResults{}), g); }()), "FB-B2 text: save_gate_refusal_text of gate_decide over scenario 3");
static_assert(text_is("SAVE REFUSED - a Free Power / Dump to Grid / Manual Configuration write arm is on; finish or turn it off first", []{ const GateInputs g = fx_gate(4); return save_gate_refusal_text(ecco_fbcap::gate_decide(g, ecco_fbcap::ProbeResults{}), g); }()), "FB-B2 text: save_gate_refusal_text of gate_decide over scenario 4");
static_assert(text_is("SAVE REFUSED - a Free Power / Dump to Grid / Manual Configuration write arm is on; finish or turn it off first", []{ const GateInputs g = fx_gate(5); return save_gate_refusal_text(ecco_fbcap::gate_decide(g, ecco_fbcap::ProbeResults{}), g); }()), "FB-B2 text: save_gate_refusal_text of gate_decide over scenario 5");
static_assert(text_is("SAVE REFUSED - a Free Power / Dump to Grid / Manual Configuration write arm is on; finish or turn it off first", []{ const GateInputs g = fx_gate(6); return save_gate_refusal_text(ecco_fbcap::gate_decide(g, ecco_fbcap::ProbeResults{}), g); }()), "FB-B2 text: save_gate_refusal_text of gate_decide over scenario 6");
static_assert(text_is("SAVE REFUSED - another inverter transaction is in progress (manual write); try again shortly", []{ const GateInputs g = fx_gate(7); return save_gate_refusal_text(ecco_fbcap::gate_decide(g, ecco_fbcap::ProbeResults{}), g); }()), "FB-B2 text: save_gate_refusal_text of gate_decide over scenario 7");
static_assert(text_is("SAVE REFUSED - another inverter transaction is in progress (clock correction); try again shortly", []{ const GateInputs g = fx_gate(8); return save_gate_refusal_text(ecco_fbcap::gate_decide(g, ecco_fbcap::ProbeResults{}), g); }()), "FB-B2 text: save_gate_refusal_text of gate_decide over scenario 8");
static_assert(text_is("SAVE REFUSED - inverter write lock held for 301 s (possible leak); a reboot may be required", []{ const GateInputs g = fx_gate(9); return save_gate_refusal_text(ecco_fbcap::gate_decide(g, ecco_fbcap::ProbeResults{}), g); }()), "FB-B2 text: save_gate_refusal_text of gate_decide over scenario 9");
static_assert(text_is("SAVE REFUSED - a failback episode record exists; only the firmware that created it can resolve it", []{ const GateInputs g = fx_gate(10); return save_gate_refusal_text(ecco_fbcap::gate_decide(g, ecco_fbcap::ProbeResults{}), g); }()), "FB-B2 text: save_gate_refusal_text of gate_decide over scenario 10");
static_assert(text_is("SAVE REFUSED - Failback record recovery metadata is CORRUPT (hard lockout); Fallback never overwrites or proceeds past it; do not erase NVS", []{ const GateInputs g = fx_gate(11); return save_gate_refusal_text(ecco_fbcap::gate_decide(g, ecco_fbcap::ProbeResults{}), g); }()), "FB-B2 text: save_gate_refusal_text of gate_decide over scenario 11");
static_assert(text_is("SAVE REFUSED - Failback record recovery state UNKNOWN since boot (marker unreadable); an obligation cannot be ruled out; Fallback never proceeds past it", []{ const GateInputs g = fx_gate(12); return save_gate_refusal_text(ecco_fbcap::gate_decide(g, ecco_fbcap::ProbeResults{}), g); }()), "FB-B2 text: save_gate_refusal_text of gate_decide over scenario 12");
static_assert(text_is("SAVE REFUSED - Free Power is active; live settings are a temporary overlay - end it first", []{ const GateInputs g = fx_gate(13); return save_gate_refusal_text(ecco_fbcap::gate_decide(g, ecco_fbcap::ProbeResults{}), g); }()), "FB-B2 text: save_gate_refusal_text of gate_decide over scenario 13");
static_assert(text_is("SAVE REFUSED - Dump to Grid needs an operator recovery action first", []{ const GateInputs g = fx_gate(14); return save_gate_refusal_text(ecco_fbcap::gate_decide(g, ecco_fbcap::ProbeResults{}), g); }()), "FB-B2 text: save_gate_refusal_text of gate_decide over scenario 14");
static_assert(text_is("SAVE REFUSED - Register 244 test restore verified; durable clear still pending - press Restore Original (armed)", []{ const GateInputs g = fx_gate(15); return save_gate_refusal_text(ecco_fbcap::gate_decide(g, ecco_fbcap::ProbeResults{}), g); }()), "FB-B2 text: save_gate_refusal_text of gate_decide over scenario 15");
static_assert(text_is("SAVE REFUSED - Free Power recovery marker became unreadable at runtime; saving blocked until reboot. After reboot it may read absent: verify live settings first; do not erase NVS", []{ const GateInputs g = fx_gate(16); return save_gate_refusal_text(ecco_fbcap::gate_decide(g, ecco_fbcap::ProbeResults{}), g); }()), "FB-B2 text: save_gate_refusal_text of gate_decide over scenario 16");
static_assert(text_is("SAVE REFUSED - a Free Power / Dump to Grid / Manual Configuration write arm is on; finish or turn it off first", []{ const GateInputs g = fx_gate(17); return save_gate_refusal_text(ecco_fbcap::gate_decide(g, ecco_fbcap::ProbeResults{}), g); }()), "FB-B2 text: save_gate_refusal_text of gate_decide over scenario 17");
static_assert(text_is("SAVE REFUSED - another inverter transaction is in progress (manual write); try again shortly", []{ const GateInputs g = fx_gate(18); return save_gate_refusal_text(ecco_fbcap::gate_decide(g, ecco_fbcap::ProbeResults{}), g); }()), "FB-B2 text: save_gate_refusal_text of gate_decide over scenario 18");
static_assert(text_is("SAVE REFUSED - Free Power in-memory recovery state is inconsistent; a reboot must re-derive it before saving", []{ const GateInputs g = fx_gate(19); return save_gate_refusal_text(ecco_fbcap::gate_decide(g, ecco_fbcap::ProbeResults{}), g); }()), "FB-B2 text: save_gate_refusal_text of gate_decide over scenario 19");
static_assert(text_is("SAVE REFUSED - another inverter transaction is in progress (clock verification); try again shortly", []{ const GateInputs g = fx_gate(20); return save_gate_refusal_text(ecco_fbcap::gate_decide(g, ecco_fbcap::ProbeResults{}), g); }()), "FB-B2 text: save_gate_refusal_text of gate_decide over scenario 20");
static_assert(text_is("SAVE REFUSED - another inverter transaction is in progress (Register 244 test); try again shortly", []{ const GateInputs g = fx_gate(21); return save_gate_refusal_text(ecco_fbcap::gate_decide(g, ecco_fbcap::ProbeResults{}), g); }()), "FB-B2 text: save_gate_refusal_text of gate_decide over scenario 21");
static_assert(text_is("SAVE REFUSED - another inverter transaction is in progress (Free Power); try again shortly", []{ const GateInputs g = fx_gate(22); return save_gate_refusal_text(ecco_fbcap::gate_decide(g, ecco_fbcap::ProbeResults{}), g); }()), "FB-B2 text: save_gate_refusal_text of gate_decide over scenario 22");
static_assert(text_is("", []{ const GateInputs g = fx_gate(23); return save_gate_refusal_text(ecco_fbcap::gate_decide(g, ecco_fbcap::ProbeResults{}), g); }()), "FB-B2 text: save_gate_refusal_text of gate_decide over scenario 23");
static_assert(text_is("SAVE REFUSED - another inverter transaction is in progress (Dump to Grid); try again shortly", []{ const GateInputs g = fx_gate(24); return save_gate_refusal_text(ecco_fbcap::gate_decide(g, ecco_fbcap::ProbeResults{}), g); }()), "FB-B2 text: save_gate_refusal_text of gate_decide over scenario 24");
static_assert(text_is("SAVE REFUSED - another inverter transaction is in progress (Free Power); try again shortly", []{ const GateInputs g = fx_gate(25); return save_gate_refusal_text(ecco_fbcap::gate_decide(g, ecco_fbcap::ProbeResults{}), g); }()), "FB-B2 text: save_gate_refusal_text of gate_decide over scenario 25");
static_assert(text_is("SAVE REFUSED - another inverter transaction is in progress (Free Power); try again shortly", []{ const GateInputs g = fx_gate(26); return save_gate_refusal_text(ecco_fbcap::gate_decide(g, ecco_fbcap::ProbeResults{}), g); }()), "FB-B2 text: save_gate_refusal_text of gate_decide over scenario 26");
static_assert(text_is("SAVE REFUSED - another inverter transaction is in progress (Dump to Grid); try again shortly", []{ const GateInputs g = fx_gate(27); return save_gate_refusal_text(ecco_fbcap::gate_decide(g, ecco_fbcap::ProbeResults{}), g); }()), "FB-B2 text: save_gate_refusal_text of gate_decide over scenario 27");
// ---- GENERATED-GOLDENS-END ----

}  // namespace ecco_fbsave
