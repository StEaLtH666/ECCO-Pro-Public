#pragma once

// ECCO guarded charge-rate controller (GRC): the PURE decision core.
//
// WHAT IT IS. Header-only, dependency-free C++17 (standard integer headers only: no heap, no STL container, no
// printf family, no Arduino or ESPHome include, no static or global state). It is the firmware form of
// docs/dev/gentle-rate-controller/SPEC.md revision 3 and mirrors docs/dev/gentle-rate-controller/reference_model.py
// line for line; registry/tests/test_gentle_rate_core_host.py proves the two produce the same trace on every golden
// vector and on a seeded random fuzz, under -Wall -Wextra -Werror and the address / undefined-behaviour sanitizers.
//
// WHAT IT DOES. Decides whether a lease may start, which single slot-power value to write next (or none), when the
// lease must end and be restored, and when to latch a fault. It is SUBTRACTIVE: it never asks for more than the value
// the charge slot held before the lease (`original`), and the restore asks for exactly `original`.
//
// WHAT IT DOES NOT DO. It never performs a Modbus request, a storage access, a log line or a publish. The caller (the
// integration proposed in docs/dev/gentle-rate-controller/INTEGRATION_PROPOSAL.md) owns, for every action, and
// reports the outcome in a later In::op together with In::op_seq = Out::seq and In::op_kind = Out::action, always on
// the register 256 + Out::slot - 1:
//   (not run)         the bus was not free or the previous grc_execute still runs: OP_DEFERRED, nothing written.
//   A_WRITE(value):   persist record() FIRST when Out::commit (save before write); read the slot power register (no
//                     reply at all: OP_NO_ANSWER, nothing written; an exception reply: OP_FAIL) and require
//                     ownership_ok_for_write(live, core.v) (else OP_FOREIGN, nothing written); write ONE register;
//                     read it back; OP_OK only when the readback equals `value`, else OP_FAIL with op_value = the
//                     readback (-1 unanswered).
//   A_RESTORE(value): persist record(); read the register (no reply: OP_NO_ANSWER; an exception: OP_FAIL);
//                     classify_restore(live, original, v, p, q): CLS_ALREADY -> OP_OK_NOWRITE, CLS_FOREIGN ->
//                     OP_FOREIGN (write nothing), CLS_OWNED -> write `value`, read back, OP_OK or OP_FAIL with
//                     op_value = the readback.
// Every tick whose Out::commit is set persists record() before anything else, whether or not it carries an action.
// This header is NOT wired into any firmware YAML. It lives in docs/dev/gentle-rate-controller/proposed/, outside
// firmware/ (two suites pin what git tracks under firmware/: the FB-C3 tree hash of every .h / .yaml / .md and the
// FB-B2 header set of firmware/include/), until the integration moves it to firmware/include/ together with its
// scope-chain entry grc1.
//
// Time: uptime is millis()-style unsigned 32-bit arithmetic, compared only as elapsed intervals (wrap safe for any
// interval below 2^32 ms); the wall clock is epoch seconds (0 = not valid). Power in W, SOC in tenths of a percent.
// Every division has non-negative operands (identical to Python //).

#include <cstddef>
#include <cstdint>

namespace ecco_grc {

enum State : uint8_t { IDLE = 0, ARMED = 1, LEASED = 2, ADJUSTING = 3, SETTLING = 4, RESTORING = 5, FAULT = 6 };
enum Action : uint8_t { A_NONE = 0, A_WRITE = 1, A_RESTORE = 2 };
enum OpResult : uint8_t {
  OP_NONE = 0, OP_OK = 1, OP_OK_NOWRITE = 2, OP_FAIL = 3, OP_FOREIGN = 4, OP_NO_ANSWER = 5, OP_DEFERRED = 6
};
// OTHER_INTERLOCK (32) is reserved for a future grid-loss interlock: none exists in the base firmware (SPEC 12).
enum OtherActivity : uint8_t {
  OTHER_FREE_POWER = 1, OTHER_DUMP = 2, OTHER_EDITOR = 4, OTHER_REG244 = 8, OTHER_FALLBACK = 16, OTHER_INTERLOCK = 32
};
enum Classification : uint8_t { CLS_ALREADY = 0, CLS_OWNED = 1, CLS_FOREIGN = 2 };

enum Reason : uint8_t {
  R_NONE = 0,
  // START refusals
  R_REFUSE_NOT_ARMED = 1, R_REFUSE_NIGHT_USED = 2, R_REFUSE_CLOCK = 3, R_REFUSE_CLOCK_CHANGE = 4,
  R_REFUSE_INVERTER_CLOCK = 5, R_REFUSE_RTC = 6, R_REFUSE_OTHER = 7, R_REFUSE_FAULT = 8, R_REFUSE_TELEMETRY = 9,
  R_REFUSE_SOC = 10, R_REFUSE_PLAN_INVALID = 11, R_REFUSE_PLAN_STALE = 12, R_REFUSE_CONFIG_STALE = 13,
  R_REFUSE_SLOT = 14, R_REFUSE_SLOT_POWER = 15, R_REFUSE_TARGET_MET = 16, R_REFUSE_NOT_CHARGING = 17,
  R_REFUSE_IMPLAUSIBLE = 18, R_REFUSE_TOO_LATE = 19, R_REFUSE_TARGET_AT_RISK = 20, R_REFUSE_WRITE_BUDGET = 21,
  R_REFUSE_GRID = 22, R_REFUSE_RESTORE = 23, R_REFUSE_WEEK_BUDGET = 24, R_REFUSE_LIFE_BUDGET = 25,
  R_REFUSE_CONFIG = 26,
  // lifecycle events
  R_ARMED = 40, R_DISARMED = 41, R_ARM_EXPIRED = 42, R_LEASE_STARTED = 43, R_WRITE_REQUESTED = 44,
  R_WRITE_VERIFIED = 45, R_RESPONSE_OK = 46, R_RESPONSE_WEAK = 47, R_BMS_LIMITED = 48, R_RESTORE_REQUESTED = 49,
  R_RESTORED = 50, R_RESTORE_RETRY = 51, R_ACKED = 52, R_STALE_RESULT = 53, R_RESTORE_DEFERRED = 54,
  R_RESTORE_UNANSWERED = 55, R_OWNER_RESTORE = 56,
  // reasons a lease ends (a restore follows)
  R_END = 60, R_CLOCK_INVALID = 61, R_CLOCK_CHANGE = 62, R_INVERTER_CLOCK = 63, R_DEADLINE = 64, R_WATCHDOG = 65,
  R_OTHER_ACTIVITY = 66, R_INVERTER_FAULT = 67, R_TELEMETRY_STALE = 68, R_SOC_INVALID = 69, R_PLAN_LOST = 70,
  R_PLAN_INVALID = 71, R_CONFIG_STALE = 72, R_CONFIG_DRIFT = 73, R_TARGET_REACHED = 74, R_TARGET_GUARD = 75,
  R_RUNAWAY = 76, R_CHARGE_STOPPED = 77, R_RTC_STUCK = 78, R_WRITE_FAILED = 79, R_OP_TIMEOUT = 80,
  R_WRONG_DIRECTION = 81, R_NO_RESPONSE = 82, R_IMPLAUSIBLE_GAIN = 83, R_BOOT_RECOVERY = 84, R_GRID_LOSS = 85,
  R_READBACK_MISMATCH = 86, R_PLAN_WINDOW = 87, R_WRITE_DEFERRED = 88, R_WRITE_UNANSWERED = 89,
  // latched faults (no automatic write; owner review)
  R_FOREIGN = 100, R_RESTORE_FAILED = 101, R_RECORD_CORRUPT = 102, R_NIGHT_CEILING = 103, R_RESTORE_STALLED = 104
};

enum DecodeStatus : uint8_t {
  DEC_OK = 0, DEC_ABSENT = 1, DEC_BAD_SIZE = 2, DEC_BAD_CRC = 3, DEC_BAD_MAGIC = 4, DEC_BAD_VERSION = 5,
  DEC_BAD_VALUE = 6
};

constexpr uint32_t NEVER = 0xFFFFFFFFu;  // In::rx_age_ms: the inverter has not answered any read since this boot

// Firmware substitutions; the defaults are the proposed production values (SPEC section 5), EXCEPT capacity_floor_wh:
// it has NO usable default (0 fails config_ok, so START refuses with R_REFUSE_CONFIG). The integration builds its
// Config with site_config(${grc_capacity_floor_wh}) and static_asserts that it is at least the usable capacity.
struct Config {
  int32_t floor_w = 500;
  int32_t round_w = 100;
  int32_t fw_bound_w = 8000;
  int32_t max_step_w = 2000;
  int32_t hyst_w = 300;
  int32_t reversal_extra_w = 300;
  uint32_t dwell_ms = 1800000;
  uint32_t settle_ms = 45000;
  int32_t judge_samples = 4;
  int32_t max_changes = 6;
  int32_t max_restore_attempts = 3;
  int32_t owner_restore_reserve = 1;
  int32_t night_write_ceiling = 10;
  int32_t week_write_ceiling = 42;
  int32_t life_write_ceiling = 4000;
  int32_t restore_free_max = 10;
  uint32_t restore_stall_ms = 600000;
  uint32_t restore_backoff_ms = 30000;
  uint32_t op_timeout_ms = 15000;
  uint32_t plan_max_age_ms = 1200000;
  uint32_t telemetry_stale_ms = 90000;
  uint32_t config_stale_ms = 180000;
  uint32_t rtc_busy_max_ms = 300000;
  int32_t clock_skew_max_s = 120;
  int32_t end_margin_s = 600;
  int32_t min_lease_s = 3600;
  uint32_t arm_window_ms = 43200000;
  int32_t charging_min_w = 1000;
  int32_t response_min_pct = 30;
  int32_t wrong_dir_w = 300;
  int32_t max_ineffective = 2;
  int32_t gain_min_pct = 50;
  int32_t gain_max_pct = 150;
  int32_t runaway_pct = 115;
  int32_t runaway_margin_w = 500;
  int32_t runaway_samples = 3;
  int32_t stop_w = 100;
  int32_t stop_samples = 3;
  int32_t stop_soc_gap = 20;
  int32_t soc_jump_max = 50;
  int32_t soc_drop_max = 20;
  int32_t guard_margin_s = 900;
  int32_t guard_derate_pct = 85;
  int32_t guard_tail_pct = 25;
  uint32_t watchdog_extra_ms = 600000;
  uint32_t rx_fresh_ms = 30000;
  int32_t window_match_s = 120;
  int32_t capacity_floor_wh = 0;
  int32_t taper_max_pct = 95;
  int32_t script_steps = 3;
  uint32_t script_step_ms = 3000;
  uint32_t script_queue_ms = 3000;
};

constexpr bool config_ok(const Config &c) {
  return c.round_w > 0 && c.floor_w > 0 && c.floor_w % c.round_w == 0 && c.fw_bound_w % c.round_w == 0 &&
         c.fw_bound_w >= c.floor_w + c.hyst_w && c.fw_bound_w <= 8000 && 0 < c.hyst_w && c.max_step_w >= c.hyst_w &&
         c.max_step_w % c.round_w == 0 && c.settle_ms < c.dwell_ms && c.judge_samples >= 1 && c.max_changes >= 1 &&
         c.max_restore_attempts >= 1 && c.owner_restore_reserve >= 1 &&
         c.night_write_ceiling >= c.max_changes + c.max_restore_attempts + c.owner_restore_reserve &&
         c.night_write_ceiling <= 255 && c.week_write_ceiling >= c.night_write_ceiling &&
         c.life_write_ceiling >= c.week_write_ceiling && c.life_write_ceiling <= 1000000 &&
         1 <= c.restore_free_max && c.restore_free_max <= 255 &&
         (uint64_t) c.restore_stall_ms >= 2 * ((uint64_t) c.restore_backoff_ms + c.op_timeout_ms) &&
         c.restore_stall_ms <= 3600000 && c.gain_min_pct < c.gain_max_pct && c.response_min_pct > 0 &&
         c.plan_max_age_ms < c.arm_window_ms && c.op_timeout_ms > 0 && c.restore_backoff_ms > 0 &&
         0 < c.guard_tail_pct && c.guard_tail_pct <= c.guard_derate_pct && c.guard_derate_pct <= 100 &&
         c.charging_min_w >= 2 * c.round_w && c.script_steps >= 1 && c.script_step_ms > 0 &&
         (uint64_t) c.op_timeout_ms > (uint64_t) c.script_steps * c.script_step_ms + c.script_queue_ms &&
         c.end_margin_s > c.clock_skew_max_s + 60 && 60 < c.window_match_s && c.window_match_s <= 600 &&
         1000 <= c.capacity_floor_wh && c.capacity_floor_wh <= 100000 && 50 <= c.taper_max_pct &&
         c.taper_max_pct <= 100 && 0 < c.rx_fresh_ms && c.rx_fresh_ms < c.restore_stall_ms;
}

// The site's configuration: the proposed defaults with the site's capacity floor (SPEC section 5).
constexpr Config site_config(int32_t capacity_floor_wh) {
  Config c{};
  c.capacity_floor_wh = capacity_floor_wh;
  return c;
}
static_assert(!config_ok(Config{}), "the default GRC configuration has no site capacity floor and must be unusable");
static_assert(config_ok(site_config(1000)) && config_ok(site_config(100000)),
              "the defaults with any plausible site capacity floor are valid");
// An operation the core times out must really be over: grc_execute's bounded worst case (every Modbus step at its
// wait_until bound, behind the bus queue) is shorter than op_timeout_ms, so a late result can only be a stale one.
static_assert((uint64_t) Config{}.op_timeout_ms >
                  (uint64_t) Config{}.script_steps * Config{}.script_step_ms + Config{}.script_queue_ms,
              "op_timeout_ms must exceed the grc_execute worst case");

constexpr int PLAN_POINTS = 8;

// The plan Home Assistant hands over (SPEC section 4). p[] is the wanted REALISED battery charge power (DC side, W).
struct Plan {
  bool valid = false;
  uint32_t age_ms = 0;
  int32_t slot = 0;
  int32_t target = 0;
  int64_t deadline = 0;
  int64_t window_end = 0;
  int32_t ceiling_w = 0;
  int32_t capacity_wh = 0;
  int32_t taper = 0;
  int32_t n = 0;
  int64_t t[PLAN_POINTS] = {};
  int32_t p[PLAN_POINTS] = {};
};

struct In {
  uint32_t now_ms = 0;
  int64_t epoch = 0;
  int32_t local_min = -1;
  uint32_t night_id = 0;    // local DAY NUMBER of the window's start (rolls at local noon), 0 = unknown
  bool clock_change_night = false;
  int32_t inv_skew_s = -1;
  bool rtc_busy = false;
  bool mutex_busy = false;  // the shared write mutex, the bus, OR the GRC's own grc_execute still running
  uint32_t other = 0;
  bool fault = false;
  bool arm = false;
  bool start = false;
  bool end = false;
  bool ack = false;
  uint8_t op = OP_NONE;
  int32_t soc = -1;
  int32_t batt_w = 0;
  bool tel_ok = false;
  uint32_t tel_age_ms = 0;
  uint32_t sample_seq = 0;
  uint32_t cfg_age_ms = 0;
  int32_t cfg_slot = 0;        // the slot the configuration fields below describe (core.slot during a lease)
  int32_t live_sp = -1;
  int32_t slot_start_min = 0;
  int32_t slot_end_min = 0;
  bool slot_grid = false;
  int32_t slot_target = 0;
  uint32_t op_seq = 0;         // the Out::seq the result answers
  uint8_t op_kind = A_NONE;    // the Out::action the result answers
  int32_t op_value = -1;       // the value the operation read last (the readback); -1 none
  uint32_t rx_age_ms = NEVER;  // since the inverter last answered any read; NEVER = not since this boot
  bool grid_ok = false;        // the inverter reports the grid connected, grid frequency in band
  bool restore_req = false;    // the owner's Restore original pulse
  Plan plan;
};

struct Out {
  uint8_t action = A_NONE;
  int32_t value = 0;
  uint32_t seq = 0;   // with an action: its sequence number, echoed back with the result
  int32_t slot = 0;   // with an action: the slot (1..6) whose power register (256 + slot - 1) it targets
  bool disarm = false;
  bool commit = false;
  uint8_t event = R_NONE;
};

// ------------------------------------------------------------------------------------------------- pure helpers
// Wrap-safe uptime difference (exact for any interval below 2^32 ms, 49.7 days).
constexpr uint32_t elapsed(uint32_t now, uint32_t then) { return (uint32_t) (now - then); }
constexpr int64_t imin(int64_t a, int64_t b) { return a < b ? a : b; }
constexpr int64_t imax(int64_t a, int64_t b) { return a > b ? a : b; }
constexpr int64_t iabs(int64_t a) { return a < 0 ? -a : a; }
constexpr int32_t mod1440(int32_t x) { return ((x % 1440) + 1440) % 1440; }
constexpr int64_t round_up(int64_t x, int64_t step) { return (imax(0, x) + step - 1) / step * step; }

constexpr bool in_slot(int32_t m, int32_t start, int32_t end) {
  if (m < 0 || m >= 1440) return false;
  if (start < end) return start <= m && m < end;
  if (start > end) return m >= start || m < end;
  return false;
}

// The slot's own end on the dongle clock, never later than the real end: the whole minutes to the slot's end from the
// present local minute (wrapping midnight), less the up to 60 s already gone in that minute.
constexpr int64_t slot_end_epoch(int64_t epoch, int32_t local_min, int32_t slot_end_min) {
  return epoch + (int64_t) mod1440(slot_end_min - local_min) * 60 - 60;
}

constexpr bool plan_ok(const Plan &pl, const Config &c) {
  if (!pl.valid || pl.slot < 1 || pl.slot > 6 || pl.target < 10 || pl.target > 100) return false;
  if (pl.ceiling_w < c.floor_w || pl.ceiling_w > c.fw_bound_w || pl.ceiling_w % c.round_w != 0) return false;
  if (pl.capacity_wh < 1000 || pl.capacity_wh > 100000 || pl.taper < 50 || pl.taper > 100) return false;
  if (pl.deadline <= 0 || pl.window_end <= pl.deadline || pl.n < 1 || pl.n > PLAN_POINTS) return false;
  int64_t prev = 0;
  for (int k = 0; k < pl.n; k++) {
    if (pl.t[k] <= prev || pl.p[k] < 0 || pl.p[k] > 10000) return false;
    prev = pl.t[k];
  }
  return true;
}

constexpr int32_t plan_power(const Plan &pl, int64_t epoch) {
  int32_t val = pl.p[0];
  for (int k = 0; k < pl.n && k < PLAN_POINTS; k++) {
    if (pl.t[k] <= epoch) val = pl.p[k];
  }
  return val;
}

// q: a value read back under the GRC's own lock after its own write (-1 none); the lease caused it, so it is owned.
constexpr uint8_t classify_restore(int32_t live, int32_t original, int32_t v, int32_t p, int32_t q) {
  if (live == original) return CLS_ALREADY;
  if (live == v || live == p || (q >= 0 && live == q)) return CLS_OWNED;
  return CLS_FOREIGN;
}

constexpr bool ownership_ok_for_write(int32_t live, int32_t v) { return live == v; }

// At a boot with NO record: bit k-1 set for each slot k whose live power is below the OWNER's value for it, a lowered
// value a lost record may have left. `table` is a durable owner copy (the saved fallback profile's six slot powers,
// FB-B2), never the editor's staging numbers (manual_slotN_power: restore_value false, initial 8000). A warning only;
// nothing is written on it. -1 = unknown (no saved profile), never a warning.
constexpr uint32_t lost_lease_slots(const int32_t live[6], const int32_t table[6]) {
  uint32_t mask = 0;
  for (int k = 0; k < 6; k++) {
    if (live[k] >= 0 && table[k] >= 0 && live[k] < table[k]) mask |= (uint32_t) 1u << k;
  }
  return mask;
}

// ------------------------------------------------------------------------------------------------- the record
constexpr size_t REC_SIZE = 48;
constexpr uint16_t REC_MAGIC = 0x5247;
constexpr uint8_t REC_VERSION = 3;
constexpr uint8_t F_ACTIVE = 1, F_FAULT = 2, F_NIGHT_USED = 4, F_READBACK = 8, F_NIGHT_UNKNOWN = 16;

struct Record {
  uint8_t flags = 0;
  uint8_t slot = 0;
  uint8_t reason = 0;
  uint16_t original = 0;
  uint16_t v = 0;
  uint16_t p = 0;
  uint32_t night_id = 0;
  uint8_t writes_night = 0;
  uint8_t changes = 0;
  uint8_t restore_attempts = 0;
  uint8_t free_night = 0;   // unanswered or deferred restores this night
  uint32_t lease_end = 0;
  uint16_t q = 0;           // the owned readback, meaningful only with F_READBACK
  uint8_t hist[6] = {};     // writes of the nights night_id - 1 .. night_id - 6
  uint32_t life_writes = 0;
};

struct RecordBytes {
  uint8_t b[REC_SIZE] = {};
};

constexpr uint32_t crc32(const uint8_t *d, size_t n) {
  uint32_t c = 0xFFFFFFFFu;
  for (size_t i = 0; i < n; i++) {
    c ^= d[i];
    for (int k = 0; k < 8; k++) c = (c & 1u) ? (c >> 1) ^ 0xEDB88320u : (c >> 1);
  }
  return c ^ 0xFFFFFFFFu;
}

constexpr void put16(uint8_t *d, uint32_t v) { d[0] = (uint8_t) (v & 0xFF); d[1] = (uint8_t) ((v >> 8) & 0xFF); }
constexpr void put32(uint8_t *d, uint32_t v) {
  for (int k = 0; k < 4; k++) d[k] = (uint8_t) ((v >> (8 * k)) & 0xFF);
}
constexpr uint32_t get16(const uint8_t *d) { return (uint32_t) d[0] | ((uint32_t) d[1] << 8); }
constexpr uint32_t get32(const uint8_t *d) {
  return (uint32_t) d[0] | ((uint32_t) d[1] << 8) | ((uint32_t) d[2] << 16) | ((uint32_t) d[3] << 24);
}

constexpr RecordBytes encode_record(const Record &r) {
  RecordBytes o{};
  put16(o.b + 0, REC_MAGIC);
  o.b[2] = REC_VERSION;
  o.b[3] = r.flags;
  o.b[4] = r.slot;
  o.b[5] = r.reason;
  put16(o.b + 6, r.original);
  put16(o.b + 8, r.v);
  put16(o.b + 10, r.p);
  put32(o.b + 12, r.night_id);
  o.b[16] = r.writes_night;
  o.b[17] = r.changes;
  o.b[18] = r.restore_attempts;
  o.b[19] = r.free_night;
  put32(o.b + 20, r.lease_end);
  put16(o.b + 24, r.q);
  for (int k = 0; k < 6; k++) o.b[26 + k] = r.hist[k];
  put32(o.b + 32, r.life_writes);
  put32(o.b + 44, crc32(o.b, 44));
  return o;
}

struct Decoded {
  uint8_t status = DEC_ABSENT;
  Record rec{};
};

// `d == nullptr` means no record was found (DEC_ABSENT). Fail closed: anything but a valid, plausible record is an
// error status and an empty Record.
constexpr Decoded decode_record(const uint8_t *d, size_t n, const Config &c) {
  Decoded o{};
  if (d == nullptr) { o.status = DEC_ABSENT; return o; }
  if (n != REC_SIZE) { o.status = DEC_BAD_SIZE; return o; }
  if (get32(d + 44) != crc32(d, 44)) { o.status = DEC_BAD_CRC; return o; }
  if (get16(d) != REC_MAGIC) { o.status = DEC_BAD_MAGIC; return o; }
  if (d[2] != REC_VERSION) { o.status = DEC_BAD_VERSION; return o; }
  Record r{};
  r.flags = d[3];
  r.slot = d[4];
  r.reason = d[5];
  r.original = (uint16_t) get16(d + 6);
  r.v = (uint16_t) get16(d + 8);
  r.p = (uint16_t) get16(d + 10);
  r.night_id = get32(d + 12);
  r.writes_night = d[16];
  r.changes = d[17];
  r.restore_attempts = d[18];
  r.free_night = d[19];
  r.lease_end = get32(d + 20);
  r.q = (uint16_t) get16(d + 24);
  for (int k = 0; k < 6; k++) r.hist[k] = d[26 + k];
  r.life_writes = get32(d + 32);
  bool ok = (r.flags & ~31u) == 0 && r.writes_night <= c.night_write_ceiling;
  for (int k = 36; k < 44; k++) ok = ok && d[k] == 0;
  for (int k = 0; k < 6; k++) ok = ok && r.hist[k] <= c.night_write_ceiling;
  ok = ok && r.free_night <= c.restore_free_max;
  if (!(r.flags & F_READBACK)) ok = ok && r.q == 0;
  if (r.flags & F_NIGHT_UNKNOWN) ok = ok && r.night_id == 0 && !(r.flags & F_ACTIVE);
  if (r.flags & F_ACTIVE) {
    ok = ok && r.slot >= 1 && r.slot <= 6 && r.original >= c.floor_w + c.hyst_w && r.original <= c.fw_bound_w;
    ok = ok && r.v >= c.floor_w && r.v <= r.original && r.p >= c.floor_w && r.p <= r.original;
    ok = ok && r.changes <= c.max_changes && r.restore_attempts <= c.max_restore_attempts && r.lease_end != 0;
  } else {
    ok = ok && r.slot == 0 && r.original == 0 && r.v == 0 && r.p == 0 && r.changes == 0 &&
         r.restore_attempts == 0 && r.lease_end == 0 && !(r.flags & F_READBACK);
  }
  if (!ok) { o.status = DEC_BAD_VALUE; return o; }
  o.status = DEC_OK;
  o.rec = r;
  return o;
}

// ------------------------------------------------------------------------------------------------- the core
class Core {
 public:
  Config c{};
  uint8_t state = IDLE;
  uint32_t armed_ms = 0;
  bool arm_latch = false;
  uint32_t night_id = 0;
  bool night_used = false;
  bool night_unknown = false;
  int32_t writes_night = 0;
  int32_t free_night = 0;
  int32_t hist[6] = {};
  uint32_t life_writes = 0;
  uint8_t last_reason = R_NONE;
  bool seen = false;
  uint32_t last_seq = 0;
  uint32_t seq = 0;
  // the lease
  int32_t slot = 0, original = 0, v = 0, p = 0, q = -1, prev_v = 0, last_dir = 0;
  int32_t target = 0, taper = 0, capacity_wh = 0;
  uint32_t lease_start_ms = 0;
  int64_t lease_end = 0;
  uint32_t watchdog_ms = 0;
  int32_t changes = 0;
  uint32_t last_change_ms = 0;
  bool op_pending = false;
  uint8_t op_kind = A_NONE;
  uint32_t op_seq = 0;
  uint32_t op_start_ms = 0;
  uint32_t late_seq = 0;
  uint8_t late_kind = A_NONE;
  bool end_pending = false;
  bool grid_pending = false;
  int32_t restore_attempts = 0;
  bool restore_hold = false;
  uint32_t restore_from_ms = 0;
  uint32_t stall_ms = 0;
  uint32_t stall_mark_ms = 0;
  int32_t p0 = 0, p_ref = 0, gain_pct = 0, ineffective = 0;
  bool bms_limited = false;
  int32_t runaway_n = 0, stop_n = 0, judge_n = 0;
  int64_t judge_sum = 0;
  bool rtc_on = false;
  uint32_t rtc_since_ms = 0;
  int32_t last_soc = -1, soc_max = -1;

  Core() = default;
  explicit Core(const Config &cfg) : c(cfg) {}

  void clear_lease() {
    slot = original = v = p = prev_v = last_dir = 0;
    q = -1;
    target = taper = capacity_wh = 0;
    lease_start_ms = 0;
    lease_end = 0;
    watchdog_ms = 0;
    changes = 0;
    last_change_ms = 0;
    op_pending = false;
    op_kind = A_NONE;
    op_seq = 0;
    op_start_ms = 0;
    late_seq = 0;
    late_kind = A_NONE;
    end_pending = false;
    grid_pending = false;
    restore_attempts = 0;
    restore_hold = false;
    restore_from_ms = 0;
    stall_ms = 0;
    stall_mark_ms = 0;
    p0 = p_ref = gain_pct = ineffective = 0;
    bms_limited = false;
    runaway_n = stop_n = judge_n = 0;
    judge_sum = 0;
    rtc_on = false;
    rtc_since_ms = 0;
    last_soc = soc_max = -1;
  }

  // Every write of this night and the six before it (the rolling 7-day window).
  int32_t week_writes() const {
    int32_t s = writes_night;
    for (int k = 0; k < 6; k++) s += hist[k];
    return s;
  }

  Record record() const {
    bool lease = state == LEASED || state == ADJUSTING || state == SETTLING || state == RESTORING ||
                 (state == FAULT && original != 0);
    bool rb = lease && q >= 0;
    Record r{};
    r.flags = (uint8_t) ((lease ? F_ACTIVE : 0) | (state == FAULT ? F_FAULT : 0) | (night_used ? F_NIGHT_USED : 0) |
                         (rb ? F_READBACK : 0) | (night_unknown ? F_NIGHT_UNKNOWN : 0));
    r.reason = last_reason;
    r.night_id = night_id;
    r.writes_night = (uint8_t) writes_night;
    r.free_night = (uint8_t) free_night;
    for (int k = 0; k < 6; k++) r.hist[k] = (uint8_t) hist[k];
    r.life_writes = life_writes;
    if (lease) {
      r.slot = (uint8_t) slot;
      r.original = (uint16_t) original;
      r.v = (uint16_t) v;
      r.p = (uint16_t) p;
      r.changes = (uint8_t) changes;
      r.restore_attempts = (uint8_t) restore_attempts;
      r.lease_end = (uint32_t) lease_end;
    }
    if (rb) r.q = (uint16_t) q;
    return r;
  }

  // A restart. The restore an open lease owes is emitted only once the inverter has answered a read since this boot
  // (the caller reports rx_age_ms = NEVER until then), so a dongle and inverter booting together spend no attempt.
  void boot(uint8_t status, const Record &rec, uint32_t now_ms) {
    Config keep = c;
    *this = Core(keep);
    arm_latch = true;
    if (status == DEC_ABSENT) return;
    if (status != DEC_OK) {
      // original is unknown, and so are the night's counts: the boot's night is taken as used with every count of the
      // 7-day window full (START refused until they age out); adopted on the first tick with a night
      state = FAULT;
      last_reason = R_RECORD_CORRUPT;
      night_unknown = true;
      night_used = true;
      writes_night = c.night_write_ceiling;
      free_night = c.restore_free_max;
      for (int k = 0; k < 6; k++) hist[k] = c.night_write_ceiling;
      return;
    }
    night_id = rec.night_id;
    writes_night = rec.writes_night;
    free_night = rec.free_night;
    for (int k = 0; k < 6; k++) hist[k] = rec.hist[k];
    life_writes = rec.life_writes;
    night_used = (rec.flags & F_NIGHT_USED) != 0;
    night_unknown = (rec.flags & F_NIGHT_UNKNOWN) != 0;
    last_reason = rec.reason;
    if (rec.flags & F_ACTIVE) {
      slot = rec.slot; original = rec.original; v = rec.v; p = rec.p;
      q = (rec.flags & F_READBACK) ? (int32_t) rec.q : -1;
      changes = rec.changes; restore_attempts = rec.restore_attempts; lease_end = rec.lease_end;
    }
    if (rec.flags & F_FAULT) { state = FAULT; return; }
    if (rec.flags & F_ACTIVE) {
      if (restore_attempts >= c.max_restore_attempts) { state = FAULT; last_reason = R_RESTORE_FAILED; return; }
      state = RESTORING;
      last_reason = R_BOOT_RECOVERY;
      stall_mark_ms = now_ms;
    }
  }

  Out step(const In &i) {
    Out o{};
    bool fresh = i.tel_ok && (!seen || i.sample_seq != last_seq);
    if (i.tel_ok) { seen = true; last_seq = i.sample_seq; }
    if (!i.arm) arm_latch = false;
    if (night_unknown && i.night_id != 0) { night_id = i.night_id; night_unknown = false; }
    uint8_t st = state;
    if ((st == IDLE || st == ARMED || st == FAULT) && !night_unknown && i.night_id > night_id) roll_night(i.night_id);
    uint8_t res = result(i, o);
    if (st == FAULT) { faulted(i, o, res); return o; }
    if (st == IDLE) {
      if (i.start) { o.event = R_REFUSE_NOT_ARMED; last_reason = R_REFUSE_NOT_ARMED; }
      if (i.arm && !arm_latch) {
        state = ARMED;
        armed_ms = i.now_ms;
        if (o.event == R_NONE || o.event == R_STALE_RESULT) o.event = R_ARMED;
      }
      return o;
    }
    if (st == ARMED) { armed(i, o); return o; }
    if (i.end) end_pending = true;
    if (!i.grid_ok) grid_pending = true;
    if (st == ADJUSTING) { adjusting(i, o, res); return o; }
    if (st == LEASED || st == SETTLING) {
      uint8_t r = guard(i, fresh);
      if (r == R_FOREIGN) { fault(o, r); return o; }
      if (r != R_NONE) begin_restore(i, o, r);
      else if (st == SETTLING) settle(i, o, fresh);
      else lease(i, o, fresh);
    }
    if (state == RESTORING) restoring(i, o, res);
    return o;
  }

 private:
  // The result reported for the OUTSTANDING operation, else OP_NONE. A result for any other sequence or kind (a late
  // result of an abandoned operation, a duplicate) is stale: ignored, never taken as this one's outcome. The late
  // result of the operation this lease abandoned at its timeout still carries the register's newest value
  // (operations run one at a time), so its readback is owned (never its outcome).
  uint8_t result(const In &i, Out &o) {
    if (i.op == OP_NONE) return OP_NONE;
    if (op_pending && i.op_seq == op_seq && i.op_kind == op_kind) return i.op;
    o.event = R_STALE_RESULT;
    if (late_seq != 0 && i.op_seq == late_seq && i.op_kind == late_kind) {
      late_seq = 0;
      late_kind = A_NONE;
      if (i.op == OP_FAIL) own_readback(i, o);
    }
    return OP_NONE;
  }

  // A new night: the closing night's writes join the 7-day window (hist[j] = night nid - 1 - j), every night without
  // a record counts 0, the night's counters restart.
  void roll_night(uint32_t nid) {
    int64_t k = night_id != 0 ? (int64_t) nid - (int64_t) night_id : 7;
    int32_t nw[6] = {};
    for (int j = 0; j < 6; j++) {
      int64_t age = j + 1;
      if (age == k) nw[j] = writes_night;
      else if (age > k) nw[j] = hist[age - k - 1];
    }
    for (int j = 0; j < 6; j++) hist[j] = nw[j];
    night_id = nid;
    night_used = false;
    writes_night = 0;
    free_night = 0;
  }

  // R_NONE when n more change writes fit every write ceiling with the restores and the owner's restore still
  // reserved; else the refusal. A restore is never refused by these ceilings.
  uint8_t budget(int32_t n) const {
    int64_t reserve = (int64_t) c.max_restore_attempts + c.owner_restore_reserve;
    if ((int64_t) writes_night + n > c.night_write_ceiling - reserve) return R_REFUSE_WRITE_BUDGET;
    if ((int64_t) week_writes() + n > c.week_write_ceiling - reserve) return R_REFUSE_WEEK_BUDGET;
    if ((int64_t) life_writes + n > c.life_write_ceiling - reserve) return R_REFUSE_LIFE_BUDGET;
    return R_NONE;
  }

  void armed(const In &i, Out &o) {
    if (!i.arm) { state = IDLE; o.event = R_DISARMED; return; }
    if (elapsed(i.now_ms, armed_ms) >= c.arm_window_ms) {
      state = IDLE; arm_latch = true; o.disarm = true; o.event = R_ARM_EXPIRED; return;
    }
    if (!i.start) return;
    o.disarm = true;
    arm_latch = true;
    uint8_t r = start_check(i);
    if (r != R_NONE) { state = IDLE; o.event = r; last_reason = r; return; }
    begin_lease(i, o);
  }

  uint8_t start_check(const In &i) {
    const Plan &pl = i.plan;
    if (!config_ok(c)) return R_REFUSE_CONFIG;
    if (i.night_id == 0 || i.epoch == 0 || i.local_min < 0 || i.night_id < night_id) return R_REFUSE_CLOCK;
    if (i.night_id != night_id) roll_night(i.night_id);
    if (night_used) return R_REFUSE_NIGHT_USED;
    if (i.clock_change_night) return R_REFUSE_CLOCK_CHANGE;
    if (i.inv_skew_s < 0 || i.inv_skew_s > c.clock_skew_max_s) return R_REFUSE_INVERTER_CLOCK;
    if (i.rtc_busy) return R_REFUSE_RTC;
    if (i.other != 0 || i.mutex_busy) return R_REFUSE_OTHER;
    if (i.fault) return R_REFUSE_FAULT;
    if (!i.grid_ok) return R_REFUSE_GRID;
    if (!i.tel_ok || i.tel_age_ms > c.telemetry_stale_ms) return R_REFUSE_TELEMETRY;
    if (i.soc < 0 || i.soc > 1000) return R_REFUSE_SOC;
    if (!plan_ok(pl, c)) return R_REFUSE_PLAN_INVALID;
    if (pl.age_ms > c.plan_max_age_ms) return R_REFUSE_PLAN_STALE;
    if (i.cfg_age_ms > c.config_stale_ms) return R_REFUSE_CONFIG_STALE;
    if (i.cfg_slot != pl.slot || !i.slot_grid || i.slot_target != pl.target ||
        !in_slot(i.local_min, i.slot_start_min, i.slot_end_min))
      return R_REFUSE_SLOT;
    int64_t slot_end = slot_end_epoch(i.epoch, i.local_min, i.slot_end_min);
    if (iabs(pl.window_end - slot_end) > c.window_match_s) return R_REFUSE_SLOT;
    int64_t le = imin(pl.deadline, slot_end - c.end_margin_s);
    if (i.live_sp < c.floor_w + c.hyst_w || i.live_sp > c.fw_bound_w) return R_REFUSE_SLOT_POWER;
    if (i.soc >= pl.target * 10) return R_REFUSE_TARGET_MET;
    if (i.batt_w < c.charging_min_w) return R_REFUSE_NOT_CHARGING;
    int64_t g = (int64_t) i.batt_w * 100 / i.live_sp;
    if (g < c.gain_min_pct || g > c.gain_max_pct) return R_REFUSE_IMPLAUSIBLE;
    if (le - i.epoch < c.min_lease_s) return R_REFUSE_TOO_LATE;
    if (guard_trips(i.epoch, i.soc, pl.target, (int32_t) imax(pl.capacity_wh, c.capacity_floor_wh), i.batt_w, slot_end,
                    pl.taper))
      return R_REFUSE_TARGET_AT_RISK;
    return budget(1);
  }

  void begin_lease(const In &i, Out &o) {
    const Plan &pl = i.plan;
    clear_lease();
    slot = pl.slot;
    original = i.live_sp;
    v = p = prev_v = i.live_sp;
    target = pl.target; taper = pl.taper;
    capacity_wh = (int32_t) imax(pl.capacity_wh, c.capacity_floor_wh);
    lease_start_ms = last_change_ms = i.now_ms;
    lease_end = imin(pl.deadline, slot_end_epoch(i.epoch, i.local_min, i.slot_end_min) - c.end_margin_s);
    watchdog_ms = (uint32_t) ((lease_end - i.epoch) * 1000 + (int64_t) c.watchdog_extra_ms);
    p0 = p_ref = i.batt_w;
    gain_pct = (int32_t) ((int64_t) i.batt_w * 100 / i.live_sp);
    last_soc = soc_max = i.soc;
    night_used = true;
    state = LEASED;
    o.event = R_LEASE_STARTED;
    o.commit = true;
    int32_t d = desired(i);
    if (iabs((int64_t) d - v) >= c.hyst_w) emit_write(i, o, d);
  }

  void adjusting(const In &i, Out &o, uint8_t res) {
    if (res == OP_OK) {
      op_pending = false;
      last_dir = p > v ? 1 : -1;
      prev_v = v;
      v = p;
      last_change_ms = i.now_ms;
      judge_n = 0;
      judge_sum = 0;
      if (grid_pending) { begin_restore(i, o, R_GRID_LOSS); restoring(i, o, OP_NONE); return; }
      state = SETTLING;
      o.event = R_WRITE_VERIFIED;
      return;
    }
    if (res == OP_FOREIGN) { op_pending = false; fault(o, R_FOREIGN); return; }
    if (res == OP_FAIL && i.op_value >= 0 && i.op_value != v && i.op_value != p) {
      set_q(i.op_value, o);
      begin_restore(i, o, R_READBACK_MISMATCH);
    } else if (res == OP_FAIL) {
      begin_restore(i, o, R_WRITE_FAILED);
    } else if (res == OP_OK_NOWRITE) {
      begin_restore(i, o, R_WRITE_FAILED);
    } else if (res == OP_NO_ANSWER) {
      begin_restore(i, o, R_WRITE_UNANSWERED);
    } else if (res == OP_DEFERRED) {
      begin_restore(i, o, R_WRITE_DEFERRED);
    } else if (elapsed(i.now_ms, op_start_ms) >= c.op_timeout_ms) {
      late_seq = op_seq;
      late_kind = op_kind;
      begin_restore(i, o, R_OP_TIMEOUT);
    } else {
      return;
    }
    restoring(i, o, OP_NONE);
  }

  uint8_t guard(const In &i, bool fresh) {
    const Plan &pl = i.plan;
    if (grid_pending) return R_GRID_LOSS;
    if (end_pending) return R_END;
    if (i.epoch == 0 || i.local_min < 0) return R_CLOCK_INVALID;
    if (i.clock_change_night) return R_CLOCK_CHANGE;
    if (i.inv_skew_s < 0 || i.inv_skew_s > c.clock_skew_max_s) return R_INVERTER_CLOCK;
    if (i.epoch >= lease_end) return R_DEADLINE;
    if (elapsed(i.now_ms, lease_start_ms) >= watchdog_ms) return R_WATCHDOG;
    if (i.other != 0) return R_OTHER_ACTIVITY;
    if (i.fault) return R_INVERTER_FAULT;
    if (!i.tel_ok || i.tel_age_ms > c.telemetry_stale_ms) return R_TELEMETRY_STALE;
    if (i.soc < 0 || i.soc > 1000) return R_SOC_INVALID;
    if (fresh) {
      if (iabs((int64_t) i.soc - last_soc) > c.soc_jump_max || i.soc < soc_max - c.soc_drop_max) return R_SOC_INVALID;
    }
    if (!plan_ok(pl, c)) return R_PLAN_INVALID;
    if (pl.age_ms > c.plan_max_age_ms) return R_PLAN_LOST;
    if (pl.slot != slot || pl.target != target) return R_PLAN_INVALID;
    if (i.cfg_age_ms > c.config_stale_ms) return R_CONFIG_STALE;
    if (i.cfg_slot != slot || !i.slot_grid || i.slot_target != target ||
        !in_slot(i.local_min, i.slot_start_min, i.slot_end_min))
      return R_CONFIG_DRIFT;
    int64_t slot_end = slot_end_epoch(i.epoch, i.local_min, i.slot_end_min);
    if (iabs(pl.window_end - slot_end) > c.window_match_s) return R_PLAN_WINDOW;
    if (elapsed(i.now_ms, last_change_ms) > i.cfg_age_ms) {
      if (i.live_sp != v && i.live_sp != p) return R_FOREIGN;
    }
    if (i.soc >= target * 10) return R_TARGET_REACHED;
    if (guard_trips(i.epoch, i.soc, target, capacity_wh, p0, slot_end, taper)) return R_TARGET_GUARD;
    if (fresh) {
      int32_t s = i.batt_w;
      runaway_n = ((int64_t) s > (int64_t) p0 * c.runaway_pct / 100 + c.runaway_margin_w) ? runaway_n + 1 : 0;
      if (runaway_n >= c.runaway_samples) return R_RUNAWAY;
      bool stopped = s < c.stop_w && i.soc < target * 10 - c.stop_soc_gap && i.soc < taper * 10;
      stop_n = stopped ? stop_n + 1 : 0;
      if (stop_n >= c.stop_samples) return R_CHARGE_STOPPED;
      last_soc = i.soc;
      if (i.soc > soc_max) soc_max = i.soc;
    }
    if (i.rtc_busy) {
      if (!rtc_on) { rtc_on = true; rtc_since_ms = i.now_ms; }
      else if (elapsed(i.now_ms, rtc_since_ms) >= c.rtc_busy_max_ms) return R_RTC_STUCK;
    } else {
      rtc_on = false;
    }
    int64_t cand = imin(pl.deadline, slot_end - c.end_margin_s);
    if (cand < lease_end) lease_end = cand;
    int32_t cap = (int32_t) imax(pl.capacity_wh, c.capacity_floor_wh);
    if (cap > capacity_wh) capacity_wh = cap;
    return R_NONE;
  }

  // True when finishing at the pre-lease rate would no longer leave the margin before the SLOT's own end: the plateau
  // up to the taper knee (the plan's, at most taper_max_pct) at today's rate derated, everything above the knee at a
  // small tail share of it (the real taper is NOT ESTABLISHED), the capacity at least the firmware floor.
  bool guard_trips(int64_t epoch, int32_t soc, int32_t tgt_pct, int32_t cap_wh, int32_t p_top, int64_t wend,
                   int32_t taper_pct) const {
    int64_t tgt = (int64_t) tgt_pct * 10;
    if (tgt - soc <= 0) return false;
    int64_t knee = imin(tgt, imin(taper_pct, c.taper_max_pct) * 10);
    int64_t e_plat = imax(0, knee - soc) * cap_wh / 1000;
    int64_t e_tail = (tgt - imax(soc, knee)) * cap_wh / 1000;
    int64_t p_full = (int64_t) p_top * c.guard_derate_pct / 100;
    int64_t p_tail = (int64_t) p_top * c.guard_tail_pct / 100;
    if (p_full <= 0 || p_tail <= 0) return true;
    int64_t t_need = e_plat * 3600 / p_full + e_tail * 3600 / p_tail;
    return epoch + t_need + c.guard_margin_s >= wend - c.end_margin_s;
  }

  void settle(const In &i, Out &o, bool fresh) {
    if (elapsed(i.now_ms, last_change_ms) < c.settle_ms) return;
    if (fresh) { judge_n++; judge_sum += (int64_t) imax(0, i.batt_w); }
    if (judge_n < c.judge_samples) return;
    int64_t pa = judge_sum / judge_n;
    int64_t dsp = (int64_t) v - prev_v;
    int64_t exp_mag = (int64_t) gain_pct * iabs(dsp) / 100;
    int64_t act = pa - p_ref;
    int64_t dirn = dsp > 0 ? 1 : -1;
    state = LEASED;
    if (dirn * act < 0 && iabs(act) > c.wrong_dir_w) { begin_restore(i, o, R_WRONG_DIRECTION); return; }
    if (dirn * act * 100 >= (int64_t) c.response_min_pct * exp_mag) {
      int64_t g = pa * 100 / v;
      if (g < c.gain_min_pct || g > c.gain_max_pct) { begin_restore(i, o, R_IMPLAUSIBLE_GAIN); return; }
      ineffective = 0;
      gain_pct = (int32_t) g;
      o.event = R_RESPONSE_OK;
    } else if (i.soc >= taper * 10) {
      bms_limited = true;
      o.event = R_BMS_LIMITED;
    } else {
      ineffective++;
      if (ineffective >= c.max_ineffective) { begin_restore(i, o, R_NO_RESPONSE); return; }
      o.event = R_RESPONSE_WEAK;
    }
    p_ref = (int32_t) pa;
  }

  void lease(const In &i, Out &o, bool fresh) {
    if (fresh) p_ref = (int32_t) ((3 * (int64_t) p_ref + imax(0, i.batt_w)) / 4);
    if (bms_limited || changes >= c.max_changes) return;
    if (budget(1) != R_NONE) return;
    if (elapsed(i.now_ms, last_change_ms) < c.dwell_ms) return;
    if (i.rtc_busy || i.mutex_busy) return;
    int32_t d = desired(i);
    int64_t delta = (int64_t) d - v;
    if (iabs(delta) < c.hyst_w) return;
    if (last_dir != 0 && (delta > 0 ? 1 : -1) != last_dir && iabs(delta) < c.hyst_w + c.reversal_extra_w) return;
    emit_write(i, o, d);
  }

  // The next setpoint: a RELATIVE step from the present one scaled by wanted over realised power (robust to the
  // unknown setpoint unit), rounded to the grid, then held within one step of the present value by grid bounds
  // (ceil(v - step), floor(v + step): never more than max_step_w even from a value off the grid), inside [floor,
  // min(original, bound, owner)]: the hard ceiling min(original, bound) rounded down to the grid, the owner ceiling
  // approached by at most one step per change. p_ref <= 0 cannot reach the division (config_ok keeps
  // charging_min_w / 2 >= round_w > 0); the test stays as defence in depth.
  int32_t desired(const In &i) const {
    if (p_ref <= 0 || p_ref < c.charging_min_w / 2) return v;
    int64_t raw = (int64_t) v * plan_power(i.plan, i.epoch) / p_ref;
    int64_t r = (imax(0, raw) + c.round_w / 2) / c.round_w * c.round_w;
    int64_t lo = round_up((int64_t) v - c.max_step_w, c.round_w);
    int64_t hi = ((int64_t) v + c.max_step_w) / c.round_w * c.round_w;
    r = imax(lo, imin(hi, r));
    int64_t hard = imin(original, c.fw_bound_w) / c.round_w * c.round_w;
    int64_t ceiling = imin(hard, imax(i.plan.ceiling_w, lo));
    return (int32_t) imax(c.floor_w, imin(ceiling, r));
  }

  void emit(const In &i, Out &o, uint8_t kind, int32_t value) {
    seq = seq + 1;
    if (seq == 0) seq = 1;
    op_pending = true;
    op_kind = kind;
    op_seq = seq;
    op_start_ms = i.now_ms;
    o.action = kind;
    o.value = value;
    o.seq = seq;
    o.slot = slot;
    o.commit = true;
  }

  void count_write() {
    writes_night++;
    if (life_writes < 0xFFFFFFFFu) life_writes++;
  }

  // An operation that wrote nothing (NO_ANSWER, DEFERRED) returns its write to every count.
  void give_back() {
    writes_night = (int32_t) imax(0, writes_night - 1);
    if (life_writes > 0) life_writes--;
  }

  void emit_write(const In &i, Out &o, int32_t d) {
    p = d;
    changes++;
    count_write();
    emit(i, o, A_WRITE, d);
    state = ADJUSTING;
    if (o.event == R_NONE) o.event = R_WRITE_REQUESTED;
  }

  void begin_restore(const In &i, Out &o, uint8_t reason) {
    state = RESTORING;
    last_reason = reason;
    op_pending = false;
    restore_hold = false;
    stall_ms = 0;
    stall_mark_ms = i.now_ms;
    if (o.event == R_NONE || o.event == R_STALE_RESULT) o.event = reason;
  }

  // A new owned readback is committed at once, whatever else the tick does (an emitted restore, a busy bus).
  void set_q(int32_t value, Out &o) {
    if (value != q) {
      q = value;
      o.commit = true;
    }
  }

  // A readback taken under the GRC's own lock right after its own write is a value the lease caused: owned. A
  // readback that went unanswered (-1) never erases it.
  void own_readback(const In &i, Out &o) {
    if (i.op_value >= 0 && i.op_value != original && i.op_value != v && i.op_value != p) set_q(i.op_value, o);
  }

  void hold(const In &i) {
    restore_hold = true;
    restore_from_ms = i.now_ms;
  }

  // The restore-owed time while the inverter answers: each tick adds the time since the previous one (at most
  // rx_fresh_ms), only when the inverter answered within rx_fresh_ms. A silent inverter adds nothing.
  void stall_tick(const In &i) {
    uint32_t d = elapsed(i.now_ms, stall_mark_ms);
    stall_mark_ms = i.now_ms;
    if (i.rx_age_ms <= c.rx_fresh_ms) {
      uint64_t s = (uint64_t) stall_ms + (d < c.rx_fresh_ms ? d : c.rx_fresh_ms);
      stall_ms = s > c.restore_stall_ms ? c.restore_stall_ms : (uint32_t) s;
    }
  }

  void restoring(const In &i, Out &o, uint8_t res) {
    stall_tick(i);
    if (op_pending) {
      if (res == OP_OK || res == OP_OK_NOWRITE) {
        op_pending = false;
        clear_lease();
        state = IDLE;
        o.event = R_RESTORED;
        o.commit = true;
      } else if (res == OP_FOREIGN) {
        op_pending = false;
        fault(o, R_FOREIGN);
      } else if (res == OP_NO_ANSWER || res == OP_DEFERRED) {
        // nothing was written: the attempt and the write are given back; the restore stays owed (a free retry, at
        // most restore_free_max a night)
        op_pending = false;
        restore_attempts = (int32_t) imax(0, restore_attempts - 1);
        give_back();
        free_night++;
        o.event = res == OP_NO_ANSWER ? R_RESTORE_UNANSWERED : R_RESTORE_DEFERRED;
        o.commit = true;
        if (free_night >= c.restore_free_max) {
          fault(o, R_RESTORE_STALLED);
        } else {
          hold(i);
        }
      } else if (res == OP_FAIL || elapsed(i.now_ms, op_start_ms) >= c.op_timeout_ms) {
        op_pending = false;
        if (res == OP_FAIL) {
          own_readback(i, o);
        } else {
          late_seq = op_seq;
          late_kind = op_kind;
        }
        if (restore_attempts >= c.max_restore_attempts) {
          fault(o, R_RESTORE_FAILED);
        } else {
          hold(i);
          o.event = R_RESTORE_RETRY;
        }
      }
      return;
    }
    if (restore_hold && elapsed(i.now_ms, restore_from_ms) >= c.restore_backoff_ms) restore_hold = false;
    if (stall_ms >= c.restore_stall_ms) { fault(o, R_RESTORE_STALLED); return; }
    if (restore_hold || i.rtc_busy || i.mutex_busy) return;
    if (i.rx_age_ms > c.rx_fresh_ms) return;
    if (writes_night + 1 > c.night_write_ceiling - c.owner_restore_reserve) { fault(o, R_NIGHT_CEILING); return; }
    restore_attempts++;
    count_write();
    emit(i, o, A_RESTORE, original);
    if (o.event == R_NONE || o.event == R_STALE_RESULT) o.event = R_RESTORE_REQUESTED;
  }

  // FAULT writes nothing on its own. The owner may accept the current state (ACK, with a fresh configuration read; the
  // night's counts are kept) or ask for one classified restore of the original (Restore original), which the night's
  // write ceiling bounds (one write is always reserved for it) and whose failure leaves the FAULT latched.
  void faulted(const In &i, Out &o, uint8_t res) {
    if (op_pending) {
      if (res == OP_OK || res == OP_OK_NOWRITE) {
        op_pending = false;
        clear_lease();
        state = IDLE;
        last_reason = R_OWNER_RESTORE;
        o.event = R_RESTORED;
        o.commit = true;
      } else if (res == OP_FOREIGN) {
        op_pending = false;
        last_reason = R_FOREIGN;
        o.event = R_FOREIGN;
        o.commit = true;
      } else if (res == OP_NO_ANSWER || res == OP_DEFERRED) {
        op_pending = false;
        if (free_night < c.restore_free_max) {
          give_back();
          free_night++;
        }
        o.event = res == OP_NO_ANSWER ? R_RESTORE_UNANSWERED : R_RESTORE_DEFERRED;
        o.commit = true;
      } else if (res == OP_FAIL || elapsed(i.now_ms, op_start_ms) >= c.op_timeout_ms) {
        op_pending = false;
        if (res == OP_FAIL) {
          own_readback(i, o);
        } else {
          late_seq = op_seq;
          late_kind = op_kind;
        }
        last_reason = R_RESTORE_FAILED;
        o.event = R_RESTORE_FAILED;
        o.commit = true;
      }
      return;
    }
    if (i.ack && i.cfg_age_ms <= c.config_stale_ms) {
      clear_lease();
      state = IDLE;
      last_reason = R_ACKED;
      o.event = R_ACKED;
      o.commit = true;
      return;
    }
    if (i.restore_req) {
      bool busy = i.rtc_busy || i.mutex_busy || i.rx_age_ms > c.rx_fresh_ms;
      if (original == 0 || busy || writes_night + 1 > c.night_write_ceiling) {
        o.event = R_REFUSE_RESTORE;
        return;
      }
      count_write();
      emit(i, o, A_RESTORE, original);
      o.event = R_OWNER_RESTORE;
    }
  }

  void fault(Out &o, uint8_t reason) {
    state = FAULT;
    last_reason = reason;
    op_pending = false;
    o.event = reason;
    o.commit = true;
  }
};

}  // namespace ecco_grc
