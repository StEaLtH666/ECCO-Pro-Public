#pragma once

// FB-D1: inverter RTC correction POLICY and the RTC lock deadline - PURE MODEL.
//
// WHEN the dongle may exercise its one existing inverter write capability that is not part of an energy transaction: the
// RTC correction (FC16 to registers 22-24 from NTP, followed by a verified readback). This header adds NO authority and NO
// new write: it only decides whether an automatic correction may be QUEUED after a regular RTC read, and when the RTC
// correction lock has been held for so long that the 1 s RTC tick must release it. There is no bus access, no storage,
// no entity and no clock here (time is always a parameter): every namespace-scope object is constexpr, there is no
// `static` object and no state, so identical inputs give identical outputs (the static_asserts at the end pin golden vectors).
//
// Offline mirror: registry/rtc_policy.py (same names, same behaviour). Design and evidence:
// docs/architecture/fallback/FB_D1_IMPLEMENTATION_NOTES.md (OBSERVED: the inverter clock runs at a PV-dependent rate,
// about -7 s/min at >= 2 kW PV, +1..+4.5 s/min at 20-1500 W, 0 at night; its Modbus time registers are an image that is
// normally 0-10 s stale and sometimes frozen for 20-60 s, so a single read can show a large negative error that is not real).
//
// THE POLICY (decide), evaluated once per regular (non-verification) RTC read:
//   holds    automatic sync off; correction lock held; cooldown after a failed correction; quiet window
//            [b - 60 s, b + 60 s) around every half hour and every inverter TOU zone start b (scheduled starts, their HA
//            retry and zone switches are never fought); a positive error below kLargeErrorS while a half hour or a TOU zone
//            start lies between NTP time and the inverter's time (the inverter already passed a boundary real time has not
//            reached: a correction would step it back across its own zone switch); an active Free Power / Dump / register 244
//            transaction (unless the error is >= kLargeErrorS); a background correction within kMinGapMs of the previous
//            automatic correction of any kind.
//   precision  in the window [b - 120 s, b - 60 s) right before each TOU zone start b (registers 250-255; once per
//            boundary) ONE read with precision_threshold(P) = max(P / 2, 5 s) <= |error| < kLargeErrorS corrects: the zone
//            start is
//            what the inverter acts on, a correction 60-120 s before it leaves only that much drift, and a single
//            stale read there costs at most one write per boundary (P = correction_threshold, the HA number, 10..120 s).
//   thresholds  elsewhere: P until the first evaluation after boot, then the background threshold max(P, kBackgroundFloorS).
//   confirmation  a boot / background / large correction needs two regular reads 20-150 s apart that BOTH exceed the
//            threshold with the same sign, and the inverter must have advanced by more than (NTP elapsed - 15 s) between
//            them (a frozen / stale register image never confirms; an error >= kLargeErrorS on both reads confirms even
//            then, so a truly stopped clock stays bounded).

#include <array>
#include <cstdint>

namespace ecco_rtc {

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------
constexpr int32_t kBackgroundFloorS = 30;      // background threshold floor (P below it applies only at boot)
constexpr int32_t kPrecisionMinS = 5;          // precision threshold floor: max(P / 2, 5 s)
constexpr int32_t kLargeErrorS = 300;          // >= this is never deferred by a lease or the background gap
constexpr uint32_t kQuietBeforeS = 60u;        // no automatic correction starts in [b - 60 s, b) ...
constexpr uint32_t kQuietAfterS = 60u;         // ... or in [b, b + 60 s)
constexpr uint32_t kPrecisionLeadS = 120u;     // precision window [b - 120 s, b - 60 s) before a TOU zone start b
constexpr uint32_t kMinGapMs = 300000u;        // background corrections at least 5 min apart
constexpr int32_t kConfirmMinS = 20;           // the previous read must be 20..150 s (NTP) older than this one
constexpr int32_t kConfirmMaxS = 150;
constexpr int32_t kFrozenSlackS = 15;          // the stall detector's rule: frozen iff inverter advanced < NTP advanced - 15 s
constexpr uint32_t kTxnDeadlineMs = 90000u;    // the 1 s tick releases the RTC correction lock after this (no RTC frame outstanding)
constexpr int32_t kThresholdMinS = 10;         // the correction_threshold number's range
constexpr int32_t kThresholdMaxS = 120;
constexpr uint32_t kDayS = 86400u;
constexpr uint32_t kHalfHourS = 1800u;
constexpr int32_t kErrorClampS = 2000000000;   // full_error_s saturates here (inverter years 2020-2099)

static_assert(kTxnDeadlineMs > 60000u, "the RTC deadline must exceed FB-C's 60 s RS_RTC_LOCK_STUCK observation threshold");
static_assert(kTxnDeadlineMs >= 90000u, "the RTC deadline must stay well above the ~49 s legitimate worst-case lock hold (two attempts)");
static_assert(kTxnDeadlineMs < 180000u, "the RTC deadline must release before HA's 180 s RTC_CORRECTION_STUCK alert");
static_assert(kPrecisionLeadS > kQuietBeforeS, "the precision window ends where the quiet window starts");

enum Action : uint8_t { ACT_NONE = 0, ACT_CORRECT = 1 };

// Decision reasons (numeric values frozen from FB-D1 on).
enum Reason : uint8_t {
  R_WITHIN = 0,        // |error| below the applicable threshold
  R_AUTO_OFF = 1,      // Automatic Clock Sync is off
  R_BUSY = 2,          // the correction lock is held (a correction is already running)
  R_COOLDOWN = 3,      // the 5 min cooldown after a failed correction
  R_QUIET = 4,         // inside a quiet window around a half hour or a TOU zone start
  R_LEASE = 5,         // a Free Power / Dump / register 244 transaction is active
  R_MIN_GAP = 6,       // a background correction too soon after the previous automatic one
  R_UNCONFIRMED = 7,   // the previous read does not confirm the error (stale / frozen image, sign flip, too old)
  R_LARGE = 8,         // CORRECT: |error| >= kLargeErrorS on two reads
  R_BOOT = 9,          // CORRECT: the one alignment to P after boot
  R_PRECISION = 10,    // CORRECT: precision window before a TOU zone start (one read)
  R_BACKGROUND = 11,   // CORRECT: background threshold
  R_ZONE_CROSS = 12,   // a correction would step a fast inverter clock back across a boundary it already passed
};

// ---------------------------------------------------------------------------
// Inputs / output (the RTC read handler gathers plain values, calls decide(), applies the decision)
// ---------------------------------------------------------------------------
struct Inputs {  // fail-closed defaults: a forgotten field holds the correction
  bool auto_sync = false;           // automatic_clock_sync
  bool lock_held = true;            // correction_in_progress
  bool cooldown_active = true;      // cooldown_until_ms not yet reached
  bool lease_active = true;         // Free Power / Dump active, restore requested or operation running; register 244 apply
  bool boot_aligned = false;        // rtc_boot_aligned
  int32_t err_s = 0;                // full_error_s(): inverter minus NTP local time, day-aware
  bool prev_valid = false;          // have_rtc_baseline before this read replaced it
  int32_t prev_err_s = 0;           // rtc_prev_err_s
  int32_t ntp_elapsed_s = 0;        // elapsed_s(NTP seconds of day, previous NTP seconds of day)
  int32_t inv_elapsed_s = 0;        // elapsed_s(inverter seconds of day, previous inverter seconds of day)
  uint32_t tod_s = 0;               // NTP local seconds of day
  int32_t day = 0;                  // days_from_civil(NTP local date)
  int32_t threshold_s = 20;         // correction_threshold (clamped here)
  bool have_last_auto = false;      // rtc_have_last_auto
  uint32_t since_last_auto_ms = 0;  // millis() - rtc_last_auto_ms
  uint32_t precision_served = 0;    // rtc_precision_served (the last boundary key a precision correction was queued for)
  std::array<uint16_t, 6> tou_raw{};  // registers 250-255 (HHMM); an invalid word is ignored
};

struct Decision {
  uint8_t action = ACT_NONE;
  uint8_t reason = R_WITHIN;
  int32_t threshold_s = 0;          // the threshold this read was judged against
  uint32_t precision_key = 0;       // != 0: the boundary a precision correction is queued for (store in rtc_precision_served)
  bool boot_settled = false;        // the boot alignment is done (store rtc_boot_aligned = true)
};

// ---------------------------------------------------------------------------
// Time arithmetic
// ---------------------------------------------------------------------------
constexpr int32_t abs32(int32_t v) { return v < 0 ? (v == INT32_MIN ? INT32_MAX : -v) : v; }

// Days since 1970-01-01 of a proleptic Gregorian date (H. Hinnant's days_from_civil).
constexpr int32_t days_from_civil(int32_t y, int32_t m, int32_t d) {
  y -= m <= 2 ? 1 : 0;
  const int32_t era = (y >= 0 ? y : y - 399) / 400;
  const int32_t yoe = y - era * 400;
  const int32_t mp = (m + 9) % 12;
  const int32_t doy = (153 * mp + 2) / 5 + d - 1;
  const int32_t doe = yoe * 365 + yoe / 4 - yoe / 100 + doy;
  return era * 146097 + doe - 719468;
}

// Inverter minus NTP local time in seconds, across dates (a date error is a large error; inverter 23:59:59 against NTP
// 00:00:01 the next day is -2 s, not a date mismatch). Saturates at +-kErrorClampS.
constexpr int32_t full_error_s(int32_t iy, int32_t im, int32_t iday, int32_t isod, int32_t ny, int32_t nm, int32_t nday,
                               int32_t nsod) {
  const int64_t e = ((int64_t) days_from_civil(iy, im, iday) - (int64_t) days_from_civil(ny, nm, nday)) * 86400 +
                    ((int64_t) isod - (int64_t) nsod);
  return e > kErrorClampS ? kErrorClampS : (e < -kErrorClampS ? -kErrorClampS : (int32_t) e);
}

// Seconds from a previous second-of-day to a later one, wrapped to [0, 86400).
constexpr int32_t elapsed_s(int32_t now_sod, int32_t prev_sod) {
  const int32_t d = (now_sod - prev_sod) % (int32_t) kDayS;
  return d < 0 ? d + (int32_t) kDayS : d;
}

constexpr int32_t clamp_threshold(int32_t t) { return t < kThresholdMinS ? kThresholdMinS : (t > kThresholdMaxS ? kThresholdMaxS : t); }
// The precision threshold for a (clamped) P: half of it, never below kPrecisionMinS (P = 20 s -> 10 s).
constexpr int32_t precision_threshold(int32_t p) { return p / 2 < kPrecisionMinS ? kPrecisionMinS : p / 2; }

// A TOU zone start word (registers 250-255) is HHMM in decimal; anything else is ignored.
constexpr bool tou_valid(uint16_t raw) { return raw / 100u <= 23u && raw % 100u <= 59u; }
constexpr uint32_t tou_second_of_day(uint16_t raw) { return (uint32_t) (raw / 100u) * 3600u + (uint32_t) (raw % 100u) * 60u; }

// ---------------------------------------------------------------------------
// The policy
// ---------------------------------------------------------------------------
// Quiet window: [b - 60 s, b + 60 s) for every half hour b and every valid TOU zone start b.
constexpr bool in_quiet_window(const Inputs &in) {
  const uint32_t t = in.tod_s % kDayS;
  const uint32_t since_hh = t % kHalfHourS;
  if (since_hh < kQuietAfterS || since_hh >= kHalfHourS - kQuietBeforeS)
    return true;
  for (uint8_t i = 0; i < 6; i++) {
    if (!tou_valid(in.tou_raw[i]))
      continue;
    const uint32_t b = tou_second_of_day(in.tou_raw[i]);
    const uint32_t until = (b + kDayS - t) % kDayS;
    const uint32_t since = (t + kDayS - b) % kDayS;
    if ((until >= 1u && until <= kQuietBeforeS) || since < kQuietAfterS)
      return true;
  }
  return false;
}

// L3: true when a positive error below kLargeErrorS means the inverter has already passed a half hour or a valid TOU zone
// start b that NTP time has not reached (b in (t, t + err]): writing NTP time would step the inverter back across its own zone
// switch (a zone flap). A negative error moves the inverter forward across a boundary it is late for, which is what is wanted.
constexpr bool would_step_back_across(const Inputs &in) {
  if (in.err_s <= 0 || in.err_s >= kLargeErrorS)
    return false;
  const uint32_t t = in.tod_s % kDayS;
  const uint32_t e = (uint32_t) in.err_s;
  if (kHalfHourS - t % kHalfHourS <= e)
    return true;
  for (uint8_t i = 0; i < 6; i++) {
    if (!tou_valid(in.tou_raw[i]))
      continue;
    const uint32_t until = (tou_second_of_day(in.tou_raw[i]) + kDayS - t) % kDayS;
    if (until >= 1u && until <= e)
      return true;
  }
  return false;
}

// The key (day * 1440 + minute + 1, never 0) of the nearest TOU zone start whose precision window [b - 120 s, b - 60 s)
// contains this read, else 0.
constexpr uint32_t precision_key(const Inputs &in) {
  const uint32_t t = in.tod_s % kDayS;
  uint32_t best_until = 0xFFFFFFFFu;
  uint32_t key = 0;
  for (uint8_t i = 0; i < 6; i++) {
    if (!tou_valid(in.tou_raw[i]))
      continue;
    const uint32_t b = tou_second_of_day(in.tou_raw[i]);
    const uint32_t until = (b + kDayS - t) % kDayS;
    if (until > kQuietBeforeS && until <= kPrecisionLeadS && until < best_until) {
      best_until = until;
      const int32_t bday = in.day + (b < t ? 1 : 0);
      key = (uint32_t) bday * 1440u + b / 60u + 1u;
    }
  }
  return key;
}

// Two regular reads agree that the error is real (see the header comment).
constexpr bool confirmed(const Inputs &in, int32_t thr) {
  if (!in.prev_valid || in.ntp_elapsed_s < kConfirmMinS || in.ntp_elapsed_s > kConfirmMaxS)
    return false;
  const int32_t a = abs32(in.err_s);
  const int32_t pa = abs32(in.prev_err_s);
  if (a < thr || pa < thr || (in.err_s < 0) != (in.prev_err_s < 0))
    return false;
  const bool frozen = in.inv_elapsed_s < in.ntp_elapsed_s - kFrozenSlackS;
  return !frozen || (a >= kLargeErrorS && pa >= kLargeErrorS);
}

constexpr Decision decide(const Inputs &in) {
  Decision d{};
  if (!in.auto_sync) {
    d.reason = R_AUTO_OFF;
    return d;
  }
  if (in.lock_held) {
    d.reason = R_BUSY;
    return d;
  }
  const int32_t p = clamp_threshold(in.threshold_s);
  const int32_t bg = p > kBackgroundFloorS ? p : kBackgroundFloorS;
  const int32_t a = abs32(in.err_s);
  const bool large = a >= kLargeErrorS;
  const uint32_t pkey = precision_key(in);
  // a large error is never a precision correction: it always needs two confirming reads
  const bool precision_due = pkey != 0u && pkey != in.precision_served && !large;
  const bool boot_due = !in.boot_aligned;
  const int32_t thr = precision_due ? precision_threshold(p) : (boot_due ? p : bg);
  d.threshold_s = thr;
  if (a < thr) {
    d.reason = R_WITHIN;
    d.boot_settled = boot_due;
    return d;
  }
  if (in.cooldown_active) {
    d.reason = R_COOLDOWN;
    return d;
  }
  if (in_quiet_window(in)) {
    d.reason = R_QUIET;
    return d;
  }
  if (would_step_back_across(in)) {
    d.reason = R_ZONE_CROSS;
    return d;
  }
  if (in.lease_active && !large) {
    d.reason = R_LEASE;
    return d;
  }
  if (in.have_last_auto && in.since_last_auto_ms < kMinGapMs && !(large || precision_due || boot_due)) {
    d.reason = R_MIN_GAP;
    return d;
  }
  if (!precision_due && !confirmed(in, thr)) {
    d.reason = R_UNCONFIRMED;
    return d;
  }
  d.action = ACT_CORRECT;
  d.reason = precision_due ? R_PRECISION : (large ? R_LARGE : (boot_due ? R_BOOT : R_BACKGROUND));
  d.precision_key = precision_due ? pkey : 0u;
  d.boot_settled = true;
  return d;
}

// The deadline breaker (D1a): the 1 s RTC tick releases the RTC-owned state when the lock has been held for
// kTxnDeadlineMs AND no RTC frame can still be outstanding (`idle`, see no_rtc_frame_outstanding), so no RTC callback can
// arrive after the release.
constexpr bool breaker_due(uint32_t now_ms, uint32_t since_ms, bool idle) {
  return idle && (uint32_t) (now_ms - since_ms) >= kTxnDeadlineMs;
}

// No RTC frame can be outstanding when the bus is quiet (no frame READY or WAITING), OR when the correction is between frames:
// queued for dispatch (auto_sync_pending: the write is not queued yet), waiting for its verification (verification_pending:
// the write's acknowledgement was delivered, the read is not pressed yet) or after a failure terminal (comm_failure_pending).
// A queued write (S1) waits for a quiet bus, so without the second term a bus that never quiets would hold the lock forever.
constexpr bool no_rtc_frame_outstanding(bool bus_quiet, bool auto_sync_pending, bool verification_pending,
                                        bool comm_failure_pending) {
  return bus_quiet || auto_sync_pending || verification_pending || comm_failure_pending;
}

constexpr const char *reason_name(uint8_t r) {
  return r == R_WITHIN ? "within" : r == R_AUTO_OFF ? "auto-off" : r == R_BUSY ? "busy" : r == R_COOLDOWN ? "cooldown"
       : r == R_QUIET ? "quiet-window" : r == R_LEASE ? "energy-transaction" : r == R_MIN_GAP ? "min-gap"
       : r == R_UNCONFIRMED ? "unconfirmed" : r == R_LARGE ? "large" : r == R_BOOT ? "boot" : r == R_PRECISION ? "precision"
       : r == R_BACKGROUND ? "background" : r == R_ZONE_CROSS ? "zone-cross" : "?";
}

// ---------------------------------------------------------------------------
// Golden vectors (a compiler evaluates them; registry/tests/test_rtc_policy.py holds the mirror to the same values)
// ---------------------------------------------------------------------------
constexpr Inputs golden_base() {
  Inputs in{};
  in.auto_sync = true;
  in.lock_held = false;
  in.cooldown_active = false;
  in.lease_active = false;
  in.boot_aligned = true;
  in.prev_valid = true;
  in.ntp_elapsed_s = 60;
  in.inv_elapsed_s = 53;
  in.tod_s = 10u * 3600u + 15u * 60u;  // 10:15:00, no boundary nearby
  in.day = 20730;
  in.threshold_s = 20;
  in.tou_raw[0] = 25;    // 00:25
  in.tou_raw[1] = 30;    // 00:30
  in.tou_raw[2] = 530;   // 05:30
  in.tou_raw[3] = 1200;  // 12:00
  in.tou_raw[4] = 1635;  // 16:35
  in.tou_raw[5] = 2200;  // 22:00
  return in;
}
constexpr Inputs golden_err(int32_t now, int32_t prev) {
  Inputs in = golden_base();
  in.err_s = now;
  in.prev_err_s = prev;
  return in;
}
constexpr Inputs golden_at(uint32_t tod, int32_t now, int32_t prev) {
  Inputs in = golden_err(now, prev);
  in.tod_s = tod;
  return in;
}

static_assert(days_from_civil(1970, 1, 1) == 0 && days_from_civil(2000, 3, 1) == 11017 && days_from_civil(2026, 10, 4) == 20730,
              "FB-D1 golden: days_from_civil");
static_assert(full_error_s(2026, 10, 4, 86399, 2026, 10, 5, 1) == -2 && full_error_s(2026, 12, 31, 0, 2027, 1, 1, 0) == -86400 &&
              full_error_s(2099, 12, 31, 0, 2026, 1, 1, 0) == kErrorClampS, "FB-D1 golden: full_error_s");
static_assert(elapsed_s(5, 86395) == 10 && elapsed_s(100, 40) == 60, "FB-D1 golden: elapsed_s wraps");
static_assert(tou_valid(2359) && !tou_valid(2400) && !tou_valid(1260) && tou_second_of_day(1635) == 59700u, "FB-D1 golden: TOU words");
constexpr int32_t golden_bg = kBackgroundFloorS;  // the background threshold at P = 20 s
static_assert(decide(golden_err(-(golden_bg - 1), -(golden_bg + 5))).reason == R_WITHIN && decide(golden_err(-golden_bg, -(golden_bg + 5))).action == ACT_CORRECT &&
              decide(golden_err(-golden_bg, -(golden_bg + 5))).reason == R_BACKGROUND, "FB-D1 golden: background threshold max(P, floor) (P = 20)");
static_assert(decide(golden_err(-(golden_bg + 25), -(golden_bg - 1))).reason == R_UNCONFIRMED,
              "FB-D1 golden: a previous read below the threshold never confirms");
static_assert(decide(golden_err(golden_bg + 25, -(golden_bg + 25))).reason == R_UNCONFIRMED, "FB-D1 golden: a sign flip never confirms");
static_assert([] { Inputs in = golden_err(-(golden_bg + 30), -(golden_bg + 20)); in.inv_elapsed_s = 44; return decide(in).reason; }() == R_UNCONFIRMED,
              "FB-D1 golden: a frozen register image never confirms");
static_assert([] { Inputs in = golden_err(-400, -340); in.inv_elapsed_s = 0; return decide(in).reason; }() == R_LARGE,
              "FB-D1 golden: a large error confirms even when frozen");
static_assert(decide(golden_at(11u * 3600u + 58u * 60u + 59u, -(golden_bg + 25), -(golden_bg + 20))).reason == R_PRECISION &&
              decide(golden_at(11u * 3600u + 59u * 60u, -(golden_bg + 25), -(golden_bg + 20))).reason == R_QUIET &&
              decide(golden_at(12u * 3600u + 0u * 60u + 59u, -(golden_bg + 25), -(golden_bg + 20))).reason == R_QUIET &&
              decide(golden_at(12u * 3600u + 1u * 60u, -(golden_bg + 25), -(golden_bg + 20))).reason == R_BACKGROUND,
              "FB-D1 golden: precision window then quiet window [b - 60 s, b + 60 s) around the 12:00 zone start");
static_assert(decide(golden_at(14u * 3600u + 29u * 60u, -(golden_bg + 25), -(golden_bg + 20))).reason == R_QUIET &&
              decide(golden_at(14u * 3600u + 28u * 60u + 59u, -(golden_bg + 25), -(golden_bg + 20))).reason == R_BACKGROUND,
              "FB-D1 golden: quiet window [b - 60 s, b + 60 s) around a plain half hour");
static_assert(decide(golden_at(16u * 3600u + 34u * 60u, -(golden_bg + 25), -(golden_bg + 20))).reason == R_QUIET,
              "FB-D1 golden: quiet in the last minute before the 16:35 zone start");
static_assert(decide(golden_at(16u * 3600u + 33u * 60u + 30u, -12, 0)).reason == R_PRECISION &&
              decide(golden_at(16u * 3600u + 33u * 60u + 30u, -12, 0)).precision_key == 20730u * 1440u + 995u + 1u &&
              decide(golden_at(16u * 3600u + 33u * 60u + 30u, -9, 0)).reason == R_WITHIN,
              "FB-D1 golden: one read >= P / 2 = 10 s corrects in the precision window before the 16:35 zone start");
static_assert([] { Inputs in = golden_at(16u * 3600u + 33u * 60u + 30u, -12, 0); in.prev_valid = false; return decide(in).reason; }() ==
              R_PRECISION, "FB-D1 golden: a precision correction needs no previous read (a background correction just before it)");
static_assert([] { Inputs in = golden_at(16u * 3600u + 33u * 60u + 30u, -12, 0); in.precision_served = 20730u * 1440u + 996u;
                   return decide(in).reason; }() == R_WITHIN, "FB-D1 golden: one precision correction per boundary");
static_assert(precision_threshold(20) == 10 && precision_threshold(10) == 5 && precision_threshold(11) == 5 && precision_threshold(120) == 60,
              "FB-D1 golden: precision threshold max(P / 2, 5)");
static_assert([] { Inputs in = golden_err(-(golden_bg + 25), -(golden_bg + 20)); in.lease_active = true; return decide(in).reason; }() == R_LEASE &&
              [] { Inputs in = golden_err(-300, -290); in.lease_active = true; return decide(in).reason; }() == R_LARGE &&
              [] { Inputs in = golden_err(-300, -(golden_bg - 1)); in.lease_active = true; return decide(in).reason; }() == R_UNCONFIRMED,
              "FB-D1 golden: an active energy transaction holds all but a large error, which still needs two reads");
static_assert([] { Inputs in = golden_at(16u * 3600u + 33u * 60u + 30u, -12, 0); in.lease_active = true; return decide(in).reason; }() ==
              R_LEASE, "FB-D1 golden: an active energy transaction holds a precision correction too");
static_assert([] { Inputs in = golden_err(-(golden_bg + 25), -(golden_bg + 20)); in.have_last_auto = true; in.since_last_auto_ms = 299999u;
                   return decide(in).reason; }() == R_MIN_GAP, "FB-D1 golden: background corrections at least 5 min apart");
static_assert([] { Inputs in = golden_err(-25, -21); in.boot_aligned = false; return decide(in).reason; }() == R_BOOT &&
              [] { Inputs in = golden_err(-15, -21); in.boot_aligned = false; return decide(in).boot_settled; }(),
              "FB-D1 golden: one alignment to P after boot");
static_assert(decide(golden_err(-25, -21)).reason == R_WITHIN, "FB-D1 golden: P applies only at boot (P / 2 in precision windows)");
static_assert([] { Inputs in = golden_at(16u * 3600u + 33u * 60u + 30u, -400, 0); in.lease_active = true; in.prev_valid = false;
                   return decide(in).reason; }() == R_UNCONFIRMED &&
              [] { Inputs in = golden_at(16u * 3600u + 33u * 60u + 30u, -400, -400); in.lease_active = true; return decide(in).reason; }() ==
              R_LARGE, "FB-D1 golden: a large error in a precision window still needs two reads (never a one-read precision correction)");
static_assert(decide(golden_at(14u * 3600u + 28u * 60u, golden_bg + 100, golden_bg + 95)).reason == R_ZONE_CROSS &&
              decide(golden_at(14u * 3600u + 28u * 60u, -(golden_bg + 100), -(golden_bg + 95))).reason == R_BACKGROUND &&
              decide(golden_at(14u * 3600u + 27u * 60u, golden_bg + 100, golden_bg + 95)).reason == R_BACKGROUND,
              "FB-D1 golden: never step a fast inverter back across a half hour it already passed (a slow one may cross forward)");
static_assert(no_rtc_frame_outstanding(true, false, false, false) && no_rtc_frame_outstanding(false, true, false, false) &&
              no_rtc_frame_outstanding(false, false, true, false) && no_rtc_frame_outstanding(false, false, false, true) &&
              !no_rtc_frame_outstanding(false, false, false, false), "FB-D1 golden: no_rtc_frame_outstanding");
static_assert(breaker_due(91000u, 1000u, true) && !breaker_due(90999u, 1000u, true) && !breaker_due(500000u, 1000u, false) &&
              breaker_due(89999u, 4294967295u - 1u, true), "FB-D1 golden: breaker_due (wrap-safe, quiet bus only)");

}  // namespace ecco_rtc
