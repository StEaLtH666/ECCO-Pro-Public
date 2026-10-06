"""Python mirror of the FB-D1 pure RTC correction policy (C++-exact).

firmware/include/ecco_rtc_policy.h (namespace ecco_rtc) is the C++ side. It decides only WHEN the dongle may queue an
automatic inverter RTC correction after a regular RTC read, and when the 1 s RTC tick must release a correction lock that
has been held too long. There is no authority in this module either: no bus, no storage, no clock, no entity. This module
is the independent mirror the offline suites hold the header to:
  - registry/tests/test_rtc_policy.py exercises every function here (decision table, boundary / wrap / DST-free
    seconds-of-day cases, exhaustive sweeps, goldens) and makes a real C++ compiler evaluate the header over the same
    scenarios, requiring C++ == Python;
  - registry/tests/_fbb_harness.py adapts this module generically as the namespace `ecco_rtc` when it simulates the
    firmware lambdas.

NAMING. Every function, constant and struct field has the SAME name as the C++ one. Structs are dataclasses; the
std::array field is a plain list. Integer fields are plain ints; the functions apply the C++ widths (uint32 wrap,
int32 saturation) themselves.

Pure: stdlib only, no I/O.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# Constants (ecco_rtc_policy.h)
# ---------------------------------------------------------------------------
kBackgroundFloorS = 30
kPrecisionMinS = 5
kLargeErrorS = 300
kQuietBeforeS = 60
kQuietAfterS = 60
kPrecisionLeadS = 120
kMinGapMs = 300000
kConfirmMinS = 20
kConfirmMaxS = 150
kFrozenSlackS = 15
kTxnDeadlineMs = 90000
kThresholdMinS = 10
kThresholdMaxS = 120
kDayS = 86400
kHalfHourS = 1800
kErrorClampS = 2000000000

ACT_NONE, ACT_CORRECT = 0, 1

R_WITHIN = 0
R_AUTO_OFF = 1
R_BUSY = 2
R_COOLDOWN = 3
R_QUIET = 4
R_LEASE = 5
R_MIN_GAP = 6
R_UNCONFIRMED = 7
R_LARGE = 8
R_BOOT = 9
R_PRECISION = 10
R_BACKGROUND = 11
R_ZONE_CROSS = 12

CORRECT_REASONS = (R_LARGE, R_BOOT, R_PRECISION, R_BACKGROUND)
HOLD_REASONS = (R_WITHIN, R_AUTO_OFF, R_BUSY, R_COOLDOWN, R_QUIET, R_LEASE, R_MIN_GAP, R_UNCONFIRMED, R_ZONE_CROSS)

_U32 = 0xFFFFFFFF
_INT32_MIN, _INT32_MAX = -(2 ** 31), 2 ** 31 - 1


def _u32(v: int) -> int:
    return v & _U32


def _cdiv(a: int, b: int) -> int:
    """C/C++ integer division (truncates toward zero)."""
    q = abs(a) // abs(b)
    return q if (a >= 0) == (b > 0) else -q


def _cmod(a: int, b: int) -> int:
    """C/C++ % (the sign follows the dividend)."""
    return a - _cdiv(a, b) * b


# ---------------------------------------------------------------------------
# Inputs / output
# ---------------------------------------------------------------------------
@dataclass
class Inputs:  # fail-closed defaults: a forgotten field holds the correction
    auto_sync: bool = False
    lock_held: bool = True
    cooldown_active: bool = True
    lease_active: bool = True
    boot_aligned: bool = False
    err_s: int = 0
    prev_valid: bool = False
    prev_err_s: int = 0
    ntp_elapsed_s: int = 0
    inv_elapsed_s: int = 0
    tod_s: int = 0
    day: int = 0
    threshold_s: int = 20
    have_last_auto: bool = False
    since_last_auto_ms: int = 0
    precision_served: int = 0
    tou_raw: list = field(default_factory=lambda: [0] * 6)


@dataclass
class Decision:
    action: int = ACT_NONE
    reason: int = R_WITHIN
    threshold_s: int = 0
    precision_key: int = 0
    boot_settled: bool = False


HARNESS_SIZEOF = {}


# ---------------------------------------------------------------------------
# Time arithmetic
# ---------------------------------------------------------------------------
def abs32(v: int) -> int:
    if v < 0:
        return _INT32_MAX if v == _INT32_MIN else -v
    return v


def days_from_civil(y: int, m: int, d: int) -> int:
    y -= 1 if m <= 2 else 0
    era = _cdiv(y if y >= 0 else y - 399, 400)
    yoe = y - era * 400
    mp = _cmod(m + 9, 12)
    doy = _cdiv(153 * mp + 2, 5) + d - 1
    doe = yoe * 365 + _cdiv(yoe, 4) - _cdiv(yoe, 100) + doy
    return era * 146097 + doe - 719468


def full_error_s(iy: int, im: int, iday: int, isod: int, ny: int, nm: int, nday: int, nsod: int) -> int:
    e = (days_from_civil(iy, im, iday) - days_from_civil(ny, nm, nday)) * 86400 + (isod - nsod)
    return kErrorClampS if e > kErrorClampS else (-kErrorClampS if e < -kErrorClampS else e)


def elapsed_s(now_sod: int, prev_sod: int) -> int:
    d = _cmod(now_sod - prev_sod, kDayS)
    return d + kDayS if d < 0 else d


def clamp_threshold(t: int) -> int:
    return kThresholdMinS if t < kThresholdMinS else (kThresholdMaxS if t > kThresholdMaxS else t)


def precision_threshold(p: int) -> int:
    h = _cdiv(p, 2)
    return kPrecisionMinS if h < kPrecisionMinS else h


def tou_valid(raw: int) -> bool:
    raw &= 0xFFFF
    return raw // 100 <= 23 and raw % 100 <= 59


def tou_second_of_day(raw: int) -> int:
    raw &= 0xFFFF
    return _u32((raw // 100) * 3600 + (raw % 100) * 60)


# ---------------------------------------------------------------------------
# The policy
# ---------------------------------------------------------------------------
def in_quiet_window(inp: Inputs) -> bool:
    t = _u32(inp.tod_s) % kDayS
    since_hh = t % kHalfHourS
    if since_hh < kQuietAfterS or since_hh >= kHalfHourS - kQuietBeforeS:
        return True
    for raw in inp.tou_raw[:6]:
        if not tou_valid(raw):
            continue
        b = tou_second_of_day(raw)
        until = (b + kDayS - t) % kDayS
        since = (t + kDayS - b) % kDayS
        if 1 <= until <= kQuietBeforeS or since < kQuietAfterS:
            return True
    return False


def would_step_back_across(inp: Inputs) -> bool:
    if inp.err_s <= 0 or inp.err_s >= kLargeErrorS:
        return False
    t = _u32(inp.tod_s) % kDayS
    e = inp.err_s
    if kHalfHourS - t % kHalfHourS <= e:
        return True
    for raw in inp.tou_raw[:6]:
        if not tou_valid(raw):
            continue
        until = (tou_second_of_day(raw) + kDayS - t) % kDayS
        if 1 <= until <= e:
            return True
    return False


def precision_key(inp: Inputs) -> int:
    t = _u32(inp.tod_s) % kDayS
    best_until = _U32
    key = 0
    for raw in inp.tou_raw[:6]:
        if not tou_valid(raw):
            continue
        b = tou_second_of_day(raw)
        until = (b + kDayS - t) % kDayS
        if kQuietBeforeS < until <= kPrecisionLeadS and until < best_until:
            best_until = until
            bday = inp.day + (1 if b < t else 0)
            key = _u32(_u32(bday) * 1440 + b // 60 + 1)
    return key


def confirmed(inp: Inputs, thr: int) -> bool:
    if not inp.prev_valid or inp.ntp_elapsed_s < kConfirmMinS or inp.ntp_elapsed_s > kConfirmMaxS:
        return False
    a = abs32(inp.err_s)
    pa = abs32(inp.prev_err_s)
    if a < thr or pa < thr or (inp.err_s < 0) != (inp.prev_err_s < 0):
        return False
    frozen = inp.inv_elapsed_s < inp.ntp_elapsed_s - kFrozenSlackS
    return (not frozen) or (a >= kLargeErrorS and pa >= kLargeErrorS)


def decide(inp: Inputs) -> Decision:
    d = Decision()
    if not inp.auto_sync:
        d.reason = R_AUTO_OFF
        return d
    if inp.lock_held:
        d.reason = R_BUSY
        return d
    p = clamp_threshold(inp.threshold_s)
    bg = p if p > kBackgroundFloorS else kBackgroundFloorS
    a = abs32(inp.err_s)
    large = a >= kLargeErrorS
    pkey = precision_key(inp)
    precision_due = pkey != 0 and pkey != _u32(inp.precision_served) and not large
    boot_due = not inp.boot_aligned
    thr = precision_threshold(p) if precision_due else (p if boot_due else bg)
    d.threshold_s = thr
    if a < thr:
        d.reason = R_WITHIN
        d.boot_settled = boot_due
        return d
    if inp.cooldown_active:
        d.reason = R_COOLDOWN
        return d
    if in_quiet_window(inp):
        d.reason = R_QUIET
        return d
    if would_step_back_across(inp):
        d.reason = R_ZONE_CROSS
        return d
    if inp.lease_active and not large:
        d.reason = R_LEASE
        return d
    if inp.have_last_auto and _u32(inp.since_last_auto_ms) < kMinGapMs and not (large or precision_due or boot_due):
        d.reason = R_MIN_GAP
        return d
    if not precision_due and not confirmed(inp, thr):
        d.reason = R_UNCONFIRMED
        return d
    d.action = ACT_CORRECT
    d.reason = R_PRECISION if precision_due else (R_LARGE if large else (R_BOOT if boot_due else R_BACKGROUND))
    d.precision_key = pkey if precision_due else 0
    d.boot_settled = True
    return d


def breaker_due(now_ms: int, since_ms: int, idle: bool) -> bool:
    return bool(idle) and _u32(now_ms - since_ms) >= kTxnDeadlineMs


def no_rtc_frame_outstanding(bus_quiet: bool, auto_sync_pending: bool, verification_pending: bool,
                             comm_failure_pending: bool) -> bool:
    return bool(bus_quiet or auto_sync_pending or verification_pending or comm_failure_pending)


_REASON_NAMES = {
    R_WITHIN: "within", R_AUTO_OFF: "auto-off", R_BUSY: "busy", R_COOLDOWN: "cooldown", R_QUIET: "quiet-window",
    R_LEASE: "energy-transaction", R_MIN_GAP: "min-gap", R_UNCONFIRMED: "unconfirmed", R_LARGE: "large", R_BOOT: "boot",
    R_PRECISION: "precision", R_BACKGROUND: "background", R_ZONE_CROSS: "zone-cross",
}


def reason_name(r: int) -> str:
    return _REASON_NAMES.get(r, "?")


# ---------------------------------------------------------------------------
# Golden vectors (the same as the header's static_asserts)
# ---------------------------------------------------------------------------
def golden_base() -> Inputs:
    inp = Inputs()
    inp.auto_sync = True
    inp.lock_held = False
    inp.cooldown_active = False
    inp.lease_active = False
    inp.boot_aligned = True
    inp.prev_valid = True
    inp.ntp_elapsed_s = 60
    inp.inv_elapsed_s = 53
    inp.tod_s = 10 * 3600 + 15 * 60
    inp.day = 20730
    inp.threshold_s = 20
    inp.tou_raw = [25, 30, 530, 1200, 1635, 2200]
    return inp


def golden_err(now: int, prev: int) -> Inputs:
    inp = golden_base()
    inp.err_s = now
    inp.prev_err_s = prev
    return inp


def golden_at(tod: int, now: int, prev: int) -> Inputs:
    inp = golden_err(now, prev)
    inp.tod_s = tod
    return inp
