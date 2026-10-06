"""FB-D1: the pure inverter RTC correction policy and RTC lock deadline (firmware/include/ecco_rtc_policy.h, namespace ecco_rtc) and
its C++-exact Python mirror (registry/rtc_policy.py).

[1] decision table: every hold and every correct reason, the thresholds, the quiet / precision windows (every half hour, every
    TOU zone start, day wrap), confirmation (stale / frozen image, sign flip, age window), energy transactions, the large-error
    override, the background gap, boot alignment, fail-closed defaults, threshold clamping
[2] time arithmetic: days_from_civil, full_error_s (midnight, month / year / leap-day wraps, saturation), elapsed_s, TOU words
[3] behaviour over synthetic days (a drifting inverter clock read through a stale / freezing register image): zero no-op writes
    at night, bounded writes at the worst observed drift, precision corrections land before TOU zone starts, never a write
    that starts in a quiet window, background corrections at least 5 min apart
[4] C++ == Python: a real C++ compiler evaluates the header over a seeded random case list and a full-day grid (constexpr digests
    in static_asserts, so any compiler - native or the ESP32 cross compiler - proves it) and the header's own goldens; mutants
    of the header must break the parity compile
[5] static: the header is pure (standard headers only, no static / inline / id() / millis), the mirror and the header define the
    same names, every ecco_rtc:: name the firmware uses exists in both, the deadline constant's bounds

Offline only: no device, no Home Assistant. These prove the policy logic and its two implementations agree; they prove nothing
about the inverter (see docs/architecture/fallback/FB_D1_IMPLEMENTATION_NOTES.md for what is live-proven).
"""

from __future__ import annotations

import copy
import math
import os
import random
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "registry"))
import rtc_policy as rp  # noqa: E402

HEADER_PATH = ROOT / "firmware" / "include" / "ecco_rtc_policy.h"
FW_PATH = ROOT / "firmware" / "ecco_clock_dongle_stage3_4_free_power.yaml"
HEADER_TEXT = HEADER_PATH.read_text(encoding="utf-8")
MIRROR_TEXT = (ROOT / "registry" / "rtc_policy.py").read_text(encoding="utf-8")
FW_TEXT = FW_PATH.read_text(encoding="utf-8")

FAILURES: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  PASS  {name}")
    else:
        FAILURES.append(name)
        print(f"  FAIL  {name}" + (f" - {detail}" if detail else ""))


D = rp.decide
G = rp.golden_err
A = rp.golden_at
TOU = [25, 30, 530, 1200, 1635, 2200]  # this site's zone starts (00:25 00:30 05:30 12:00 16:35 22:00)
BG = rp.kBackgroundFloorS  # the background threshold at P = 20 s


def hms(h: int, m: int, s: int = 0) -> int:
    return h * 3600 + m * 60 + s


def at(tod: int, now: int, prev: int, **kw) -> rp.Inputs:
    i = A(tod, now, prev)
    for k, v in kw.items():
        setattr(i, k, v)
    return i


# ===========================================================================
# [1] decision table
# ===========================================================================
def section_table() -> None:
    print("\n[1] decision table")
    d0 = D(rp.Inputs())
    check("fail-closed defaults: a default Inputs never corrects (auto sync off)", d0.action == rp.ACT_NONE and d0.reason == rp.R_AUTO_OFF)
    i = rp.Inputs()
    i.auto_sync = True
    check("fail-closed defaults: auto on but every other field default -> held (lock assumed held)", D(i).reason == rp.R_BUSY)
    i = G(-400, -400)
    i.auto_sync = False
    check("automatic sync off holds even a large error", D(i).action == rp.ACT_NONE and D(i).reason == rp.R_AUTO_OFF)
    i = G(-400, -400)
    i.lock_held = True
    check("a held correction lock holds everything (no second correction)", D(i).reason == rp.R_BUSY)
    # thresholds
    check(f"background threshold is max(P, {BG}): -{BG - 1} within, -{BG} corrects (P = 20)",
          D(G(-(BG - 1), -(BG + 6))).reason == rp.R_WITHIN and D(G(-BG, -(BG + 6))).reason == rp.R_BACKGROUND)
    check(f"background threshold is symmetric: +{BG - 1} within, +{BG} corrects", D(G(BG - 1, BG + 6)).reason == rp.R_WITHIN and
          D(G(BG, BG + 6)).reason == rp.R_BACKGROUND)
    for p in (10, 20, BG - 1, BG, BG + 1, 90, 120):
        bg = max(p, BG)
        i = G(-(bg - 1), -(bg + 5))
        i.threshold_s = p
        j = G(-bg, -(bg + 5))
        j.threshold_s = p
        check(f"P = {p}: background threshold {bg} (T-1 within, T corrects)", D(i).reason == rp.R_WITHIN and D(j).action == rp.ACT_CORRECT,
              f"{D(i)} {D(j)}")
    for raw, clamped in ((0, 10), (5, 10), (-50, 10), (121, 120), (500, 120)):
        check(f"threshold {raw} is clamped to {clamped}", rp.clamp_threshold(raw) == clamped)
    # confirmation
    check("a single over-threshold read never confirms (previous read below the threshold)",
          D(G(-(BG + 45), -(BG - 1))).reason == rp.R_UNCONFIRMED)
    i = G(-90, -90)
    i.prev_valid = False
    check("no previous read never confirms", D(i).reason == rp.R_UNCONFIRMED)
    check("a sign flip never confirms", D(G(90, -90)).reason == rp.R_UNCONFIRMED and D(G(-90, 90)).reason == rp.R_UNCONFIRMED)
    for el, ok in ((19, False), (20, True), (150, True), (151, False)):
        i = G(-90, -80)
        i.ntp_elapsed_s = el
        i.inv_elapsed_s = el
        check(f"previous read {el} s older {'confirms' if ok else 'does not confirm'} (window 20-150 s)",
              (D(i).action == rp.ACT_CORRECT) == ok)
    i = G(-90, -80)
    i.inv_elapsed_s = 44  # 60 - 15 = 45: advanced less than NTP - 15 s -> frozen
    j = G(-90, -80)
    j.inv_elapsed_s = 45
    check("a frozen register image (inverter advanced < NTP - 15 s) never confirms; exactly NTP - 15 s does",
          D(i).reason == rp.R_UNCONFIRMED and D(j).action == rp.ACT_CORRECT)
    i = G(-299, -350)
    i.inv_elapsed_s = 0
    j = G(-300, -300)
    j.inv_elapsed_s = 0
    check("frozen: a large error on both reads still confirms (a stopped clock stays bounded); 299 s does not",
          D(i).reason == rp.R_UNCONFIRMED and D(j).reason == rp.R_LARGE)
    # holds and their order
    i = G(-90, -90)
    i.cooldown_active = True
    check("cooldown holds a background error", D(i).reason == rp.R_COOLDOWN)
    i = G(-400, -400)
    i.cooldown_active = True
    check("cooldown holds even a large error (a failing inverter is not hammered)", D(i).reason == rp.R_COOLDOWN)
    i = G(-90, -90)
    i.lease_active = True
    check("an active energy transaction holds a background error", D(i).reason == rp.R_LEASE)
    i = G(-300, -300)
    i.lease_active = True
    check("an active energy transaction does not hold an error >= 300 s (bounded clock error even under a stuck lease)",
          D(i).reason == rp.R_LARGE)
    i = G(-90, -90)
    i.have_last_auto = True
    i.since_last_auto_ms = 299999
    j = copy.deepcopy(i)
    j.since_last_auto_ms = 300000
    check("background corrections at least 5 min apart (299999 ms held, 300000 ms corrects)",
          D(i).reason == rp.R_MIN_GAP and D(j).reason == rp.R_BACKGROUND)
    i = G(-400, -400)
    i.have_last_auto = True
    i.since_last_auto_ms = 1000
    check("the 5 min gap does not hold a large error", D(i).reason == rp.R_LARGE)
    # boot
    i = G(-25, -21)
    i.boot_aligned = False
    check("boot: the first evaluation applies P (20 s): -25 / -21 corrects (reason boot)", D(i).reason == rp.R_BOOT and D(i).boot_settled)
    i = G(-15, -21)
    i.boot_aligned = False
    check("boot: within P settles the alignment without a write", D(i).reason == rp.R_WITHIN and D(i).boot_settled)
    i = G(-25, -21)
    i.boot_aligned = False
    i.tod_s = hms(12, 0, 30)
    check("boot: a held evaluation (quiet window) does not settle the alignment", D(i).reason == rp.R_QUIET and not D(i).boot_settled)
    i = G(-25, -21)
    i.boot_aligned = False
    i.have_last_auto = True
    i.since_last_auto_ms = 0
    check("boot: the 5 min gap does not hold the boot alignment", D(i).reason == rp.R_BOOT)
    check("after boot P applies only at boot / boundaries: -25 / -21 at 10:15 is within", D(G(-25, -21)).reason == rp.R_WITHIN)
    # every half hour: quiet [b-60, b+60)
    bad = []
    for b in range(0, 86400, 1800):
        for off, quiet in ((-61, False), (-60, True), (-1, True), (0, True), (59, True), (60, False)):
            tod = (b + off) % 86400
            i = at(tod, -90, -90)
            i.tou_raw = [0xFFFF] * 6  # no TOU words: half hours only
            if (D(i).reason == rp.R_QUIET) != quiet:
                bad.append((b, off))
    check("quiet window [b-60 s, b+60 s) around every one of the 48 half hours (edges, midnight wrap)", not bad, str(bad[:6]))
    # every TOU zone start of the site: quiet + precision windows
    bad = []
    for w in TOU:
        b = rp.tou_second_of_day(w)
        for off, kind in ((-121, "bg"), (-120, "prec"), (-61, "prec"), (-60, "quiet"), (-1, "quiet"), (0, "quiet"), (59, "quiet")):
            tod = (b + off) % 86400
            # a quiet window shows only for an error above the applicable threshold
            i = at(tod, -90, -88) if kind == "quiet" else at(tod, -12, 0)
            d = D(i)
            hh = tod % 1800
            if hh < 60 or hh >= 1740:  # a half-hour quiet window overlaps: quiet wins
                continue
            if kind == "quiet" and d.reason != rp.R_QUIET:
                bad.append((w, off, d.reason))
            if kind == "prec" and not (d.reason == rp.R_PRECISION and d.precision_key == (20730 + (1 if b < tod else 0)) * 1440 + b // 60 + 1):
                bad.append((w, off, d.reason, d.precision_key))
            if kind == "bg" and d.reason not in (rp.R_WITHIN, rp.R_QUIET):
                bad.append((w, off, d.reason))
    check("TOU zone starts: precision window [b-120 s, b-60 s) corrects on ONE read >= P / 2 with the boundary key, quiet "
          "[b-60 s, b+60 s)", not bad, str(bad[:6]))
    i = at(hms(16, 33, 30), -12, 0)
    i.prev_valid = False
    check("a precision correction needs no previous read (works right after a background correction cleared the baseline)",
          D(i).reason == rp.R_PRECISION)
    i = at(hms(16, 33, 30), -12, 0)
    i.inv_elapsed_s = 0
    check("a precision correction is not stopped by a frozen image (one write per boundary at most)", D(i).reason == rp.R_PRECISION)
    check("precision threshold max(P / 2, 5): 9 s within, 10 s corrects at P = 20",
          D(at(hms(16, 33, 30), -9, 0)).reason == rp.R_WITHIN and D(at(hms(16, 33, 30), 10, 0)).reason == rp.R_PRECISION)
    for p_, pt in ((10, 5), (11, 5), (20, 10), (31, 15), (120, 60)):
        check(f"precision threshold at P = {p_} is {pt}", rp.precision_threshold(p_) == pt)
    i = at(hms(16, 33, 30), -12, 0)
    i.have_last_auto = True
    i.since_last_auto_ms = 1000
    check("the 5 min background gap does not hold a precision correction", D(i).reason == rp.R_PRECISION)
    i = at(hms(16, 33, 30), -12, 0)
    i.lease_active = True
    check("an active energy transaction holds a precision correction", D(i).reason == rp.R_LEASE)
    i = at(hms(16, 33, 30), -12, 0)
    key = D(i).precision_key
    i.precision_served = key
    check("one precision correction per boundary (served key -> the background threshold applies)", D(i).reason == rp.R_WITHIN)
    i = at(hms(16, 33, 30), -12, 0)
    i.tou_raw = [1635, 0xFFFF, 2400, 1299, 9999, 0x8000]
    check("invalid TOU words (hh > 23, mm > 59) are ignored, a valid one still counts",
          D(i).reason == rp.R_PRECISION and not rp.tou_valid(2400) and not rp.tou_valid(1299))
    i = at(hms(23, 58, 30), -12, 0)
    i.tou_raw = [0, 0xFFFF, 0xFFFF, 0xFFFF, 0xFFFF, 0xFFFF]  # zone start 00:00: precision window 23:58:00-23:59:00 the day before
    d = D(i)
    check("a precision window before a midnight zone start keys the NEXT day's boundary",
          d.reason == rp.R_PRECISION and d.precision_key == (20730 + 1) * 1440 + 0 + 1, str(d))
    i = at(hms(0, 3, 30), -12, 0)
    i.tou_raw = [5, 0xFFFF, 0xFFFF, 0xFFFF, 0xFFFF, 0xFFFF]
    d = D(i)
    check("a precision window right after midnight keys the same day's boundary", d.reason == rp.R_PRECISION and
          d.precision_key == 20730 * 1440 + 5 + 1, str(d))
    i = at(hms(23, 59, 30), -12, 0)
    i.tou_raw = [1, 0xFFFF, 0xFFFF, 0xFFFF, 0xFFFF, 0xFFFF]  # zone start 00:01: its precision window lies inside midnight's quiet window
    check("a precision window inside a half-hour quiet window is held (quiet wins)", D(i).reason == rp.R_QUIET)
    # review M1: a large error is never a one-read precision correction - it always needs two reads (and only it passes a lease)
    i = at(hms(16, 33, 30), -400, 0)
    i.prev_valid = False
    j = at(hms(16, 33, 30), -400, 0)
    j.lease_active = True
    j.inv_elapsed_s = 0
    k = at(hms(16, 33, 30), -400, -390)
    k.lease_active = True
    check("a large error in a precision window needs two reads (no previous read / a small previous read: unconfirmed, even "
          "frozen or under a lease); two large reads correct (reason large) even under a lease",
          D(i).reason == rp.R_UNCONFIRMED and D(j).reason == rp.R_UNCONFIRMED and D(k).reason == rp.R_LARGE and
          D(k).precision_key == 0, f"{D(i)} {D(j)} {D(k)}")
    # review L3: never step a fast inverter back across a boundary it already passed
    bad = []
    for e in (61, 90, 119, 120, 121, 200, 299):
        for tod_ in (hms(14, 30) - 121, hms(14, 30) - 61):  # outside the quiet window, before a plain half hour
            i = at(tod_, e, e - 3)
            i.tou_raw = [0xFFFF] * 6
            crosses = (hms(14, 30) - tod_) <= e
            want = rp.R_ZONE_CROSS if crosses else (rp.R_LARGE if e >= 300 else rp.R_BACKGROUND)
            if D(i).reason != want:
                bad.append((tod_, e, D(i).reason, want))
            i = at(tod_, -e, -(e - 3))  # a slow inverter may be moved forward across its late zone switch
            i.tou_raw = [0xFFFF] * 6
            if D(i).reason != rp.R_BACKGROUND:
                bad.append((tod_, -e, D(i).reason))
    check("a positive error < 300 s with a half hour in (t, t + err] is held (zone-cross); a negative one is not", not bad, str(bad[:6]))
    i = at(hms(16, 35) - 200, 230, 225)  # 16:31:40 + 230 s passes the 16:35 zone start (and no half hour)
    check("zone-cross also holds for an inverter TOU zone start the inverter already passed", D(i).reason == rp.R_ZONE_CROSS)
    i = at(hms(14, 28), 300, 300)
    i.tou_raw = [0xFFFF] * 6
    check("a large positive error (>= 300 s) is not held by zone-cross (it would otherwise never be corrected)",
          D(i).reason == rp.R_LARGE)
    check("would_step_back_across: (t, t + err] semantics at the edge (boundary exactly at t is not passed)",
          not rp.would_step_back_across(at(hms(14, 30), 61, 60)) and rp.would_step_back_across(at(hms(14, 29) - 1, 61, 60)))
    # an action never comes with a hold reason and a hold never with an action
    rnd = random.Random(1)
    mismatched = 0
    for _ in range(20000):
        d = D(random_inputs(rnd))
        if (d.action == rp.ACT_CORRECT) != (d.reason in rp.CORRECT_REASONS):
            mismatched += 1
        if d.action != rp.ACT_CORRECT and d.precision_key != 0:
            mismatched += 1
    check("20000 random inputs: CORRECT <=> a correct reason, and a precision key only with CORRECT", mismatched == 0, str(mismatched))


def random_inputs(rnd: random.Random) -> rp.Inputs:
    i = rp.Inputs()
    i.auto_sync = rnd.random() < 0.9
    i.lock_held = rnd.random() < 0.1
    i.cooldown_active = rnd.random() < 0.1
    i.lease_active = rnd.random() < 0.15
    i.boot_aligned = rnd.random() < 0.8
    mag = rnd.choice((5, 15, 25, 45, 65, 120, 299, 300, 400, 3600, 86400, 2000000000))
    i.err_s = rnd.randint(-mag, mag)
    i.prev_valid = rnd.random() < 0.85
    i.prev_err_s = i.err_s + rnd.randint(-15, 15) if rnd.random() < 0.8 else rnd.randint(-mag, mag)
    i.ntp_elapsed_s = rnd.choice((rnd.randint(0, 200), 60, 61, 59, 120))
    i.inv_elapsed_s = max(0, i.ntp_elapsed_s + rnd.randint(-25, 12))
    i.tod_s = rnd.randrange(86400)
    i.day = rnd.randint(18000, 30000)
    i.threshold_s = rnd.randint(0, 200)
    i.have_last_auto = rnd.random() < 0.5
    i.since_last_auto_ms = rnd.choice((rnd.randrange(1 << 32), rnd.randint(0, 600000)))
    i.precision_served = rnd.choice((0, rnd.randrange(1 << 32), i.day * 1440 + rnd.randrange(1440) + 1))
    i.tou_raw = [rnd.choice((rnd.randrange(1 << 16), rnd.randint(0, 23) * 100 + rnd.randint(0, 59))) for _ in range(6)]
    return i


# ===========================================================================
# [2] time arithmetic
# ===========================================================================
def section_time() -> None:
    print("\n[2] time arithmetic")
    import datetime as dt
    bad = [(y, m, d) for y in range(1970, 2101) for m in range(1, 13) for d in (1, 15, 28)
           if rp.days_from_civil(y, m, d) != (dt.date(y, m, d) - dt.date(1970, 1, 1)).days]
    check("days_from_civil == datetime.date ordinal for 1970-2100 (every month, three days)", not bad, str(bad[:3]))
    check("leap days: 2024-02-29 and 2100-03-01 (2100 is not a leap year)",
          rp.days_from_civil(2024, 3, 1) - rp.days_from_civil(2024, 2, 28) == 2 and
          rp.days_from_civil(2100, 3, 1) - rp.days_from_civil(2100, 2, 28) == 1)
    check("full_error_s across midnight: inverter 23:59:59 vs NTP 00:00:01 next day is -2 s (not a date error)",
          rp.full_error_s(2026, 10, 4, 86399, 2026, 10, 5, 1) == -2 and rp.full_error_s(2026, 10, 5, 1, 2026, 10, 4, 86399) == 2)
    check("full_error_s across month / year ends and a leap day", rp.full_error_s(2026, 4, 30, 86399, 2026, 5, 1, 0) == -1 and
          rp.full_error_s(2026, 12, 31, 86399, 2027, 1, 1, 0) == -1 and rp.full_error_s(2028, 2, 29, 0, 2028, 3, 1, 0) == -86400)
    check("full_error_s: a wrong date is a large error (one day = 86400 s)", rp.full_error_s(2026, 10, 3, 3600, 2026, 10, 4, 3600) == -86400)
    check("full_error_s saturates at +-2e9 (inverter years 2020-2099)", rp.full_error_s(2099, 12, 31, 0, 2020, 1, 1, 0) == rp.kErrorClampS and
          rp.full_error_s(2020, 1, 1, 0, 2099, 12, 31, 0) == -rp.kErrorClampS)
    check("elapsed_s wraps at midnight and is always in [0, 86400)",
          rp.elapsed_s(5, 86395) == 10 and rp.elapsed_s(86395, 5) == 86390 and rp.elapsed_s(100, 100) == 0 and
          all(0 <= rp.elapsed_s(a, b) < 86400 for a in range(0, 86400, 7919) for b in range(0, 86400, 6007)))
    check("TOU words: HHMM decimal, hh <= 23 and mm <= 59 only",
          rp.tou_valid(0) and rp.tou_valid(2359) and not rp.tou_valid(2360) and not rp.tou_valid(2400) and not rp.tou_valid(0xFFFF) and
          rp.tou_second_of_day(1635) == hms(16, 35) and rp.tou_second_of_day(25) == hms(0, 25))
    check("no_rtc_frame_outstanding: a quiet bus, or a correction between frames (queued / waiting for its verification / after a "
          "failure terminal); never while a write or verification read may be outstanding on a busy bus",
          all(rp.no_rtc_frame_outstanding(q, a, v, c) == (q or a or v or c)
              for q in (False, True) for a in (False, True) for v in (False, True) for c in (False, True)))
    check("breaker_due: 90 s exactly, only on a quiet bus, wrap-safe",
          rp.breaker_due(91000, 1000, True) and not rp.breaker_due(90999, 1000, True) and not rp.breaker_due(10 ** 6, 0, False) and
          rp.breaker_due(89999, (1 << 32) - 2, True) and not rp.breaker_due(5000, (1 << 32) - 2, True))


# ===========================================================================
# [3] behaviour over synthetic days
# ===========================================================================
class Inverter:
    """A drifting inverter clock read through the Modbus register image W4 measured: refreshed in ~10 s steps (0-10 s stale) and
    occasionally frozen for 20-60 s. rate(t) in s/min."""

    def __init__(self, rnd: random.Random, rate_fn, offset: float = 0.0, freeze_per_hour: float = 4.0):
        self.rnd = rnd
        self.rate_fn = rate_fn
        self.offset = offset            # true inverter minus NTP, seconds
        self.phase = rnd.random() * 10  # image refresh phase
        self.freeze_until = -1.0
        self.frozen_value = 0.0
        self.freeze_per_hour = freeze_per_hour

    def advance(self, t: float, dt_s: float) -> None:
        self.offset += self.rate_fn(t) / 60.0 * dt_s
        if self.freeze_until < t and self.rnd.random() < self.freeze_per_hour / 3600.0 * dt_s:
            self.freeze_until = t + self.rnd.uniform(20, 60)
            self.frozen_value = self.image(t)

    def image(self, t: float) -> float:
        """The inverter time as the registers show it at NTP time t (seconds of the run): a 10 s quantised, stale copy."""
        true_inv = t + self.offset
        stale = (t - self.phase) % 10.0
        return true_inv - stale

    def read(self, t: float) -> float:
        return self.frozen_value if t < self.freeze_until else self.image(t)

    def write(self, t: float) -> None:
        self.offset = -2.5  # W4: about -2.5 s true error right after a write (floor + set loss)
        self.freeze_until = -1.0


def run_day(rate_fn, hours: float, seed: int, tou=TOU, start_tod: int = 0, threshold: int = 20, lease=None, start_offset: float = 0.0,
            freeze_per_hour: float = 4.0, boot_aligned: bool = True):
    """Drives the mirror like the firmware: a regular read every 60 s (phase 13 s), the policy, a correction that lands at once
    with W4's post-write error and occupies the lock 12 s. Returns (writes[(t, reason, true_err_before)], max |true error|,
    errors at boundary instants {tod: [true err]})."""
    rnd = random.Random(seed)
    inv = Inverter(rnd, rate_fn, start_offset, freeze_per_hour)
    st = dict(prev_valid=False, prev_err=0, prev_inv=0.0, prev_ntp=0.0, boot=boot_aligned, have_last=False, last_ms=0, served=0,
              lock_until=-1.0)
    writes = []
    worst = 0.0
    at_boundary = {}
    bset = {rp.tou_second_of_day(w) for w in tou if rp.tou_valid(w)}
    t = 0.0
    end = hours * 3600
    dt_s = 1.0
    while t < end:
        inv.advance(t, dt_s)
        tod = int(start_tod + t) % 86400
        worst = max(worst, abs(inv.offset))
        if tod in bset:
            at_boundary.setdefault(tod, []).append(inv.offset)
        if (int(t) - 13) % 60 == 0 and t >= 13 and t >= st["lock_until"]:
            reading = math.floor(inv.read(t))  # the registers hold whole seconds
            err = reading - math.floor(t)          # both sides whole seconds, like the firmware
            i = rp.Inputs()
            i.auto_sync = True
            i.lock_held = False
            i.cooldown_active = False
            i.lease_active = bool(lease and lease(tod))
            i.boot_aligned = st["boot"]
            i.err_s = err
            i.prev_valid = st["prev_valid"]
            i.prev_err_s = st["prev_err"]
            i.ntp_elapsed_s = int(t - st["prev_ntp"])
            i.inv_elapsed_s = int(reading - st["prev_inv"])
            i.tod_s = tod
            i.day = 20730 + int((start_tod + t) // 86400)
            i.threshold_s = threshold
            i.have_last_auto = st["have_last"]
            i.since_last_auto_ms = int(t * 1000 - st["last_ms"]) & 0xFFFFFFFF
            i.precision_served = st["served"]
            i.tou_raw = list(tou) + [0xFFFF] * (6 - len(tou))
            d = rp.decide(i)
            st["prev_valid"], st["prev_err"], st["prev_inv"], st["prev_ntp"] = True, err, reading, t
            if d.boot_settled:
                st["boot"] = True
            if d.action == rp.ACT_CORRECT:
                writes.append((t, d.reason, inv.offset, tod))
                st["have_last"], st["last_ms"] = True, int(t * 1000)
                if d.precision_key:
                    st["served"] = d.precision_key
                st["prev_valid"] = False
                inv.write(t)
                st["lock_until"] = t + 12
        t += dt_s
    return writes, worst, at_boundary


def section_behaviour() -> None:
    print("\n[3] behaviour over synthetic days (model: W4's measured rates and register-image staleness / freezes)")
    # night: zero drift, stale image with freezes -> W4 observed ~67 no-op writes per night under the old policy
    night_tou = [hms(22, 0), hms(0, 25), hms(0, 30), hms(5, 30)]
    w, worst, _ = run_day(lambda t: 0.0, 10, seed=3, start_tod=hms(20, 0), freeze_per_hour=6.0)
    check("night (0 s/min drift, stale / freezing register image, 10 h, TOU starts 22:00 00:25 00:30 05:30): no background write; "
          "at most one precision write per zone start (the old policy wrote ~6 times an hour on stale reads)",
          all(x[1] == rp.R_PRECISION for x in w) and len(w) <= len(night_tou), str([(x[1], x[3]) for x in w]))
    w, worst, bnd = run_day(lambda t: 0.0, 10, seed=4, start_tod=hms(20, 0), start_offset=-45.0, freeze_per_hour=6.0)
    later = [x for x in w[1:] if x[1] != rp.R_PRECISION]
    b22 = bnd.get(hms(22, 0), [None])[0]
    check(f"night with a -45 s clock: one correction before 22:00, afterwards at most a precision write per zone start; the 22:00 zone "
          f"start within 5 s ({b22})", len(w) >= 1 and w[0][3] < hms(22, 0) and not later and b22 is not None and abs(b22) <= 5,
          str([(x[1], x[3]) for x in w]))
    # the worst sustained high-PV rate W4 measured (-8.8 s/min) for 6 h through midday (a stress case: real days mix regimes)
    w, worst, bnd = run_day(lambda t: -8.8, 6, seed=5, start_tod=hms(10, 0))
    n_bg = len([x for x in w if x[1] == rp.R_BACKGROUND])
    n_prec = len([x for x in w if x[1] == rp.R_PRECISION])
    check(f"-8.8 s/min for 6 h (10:00-16:00): {len(w)} writes ({len(w) / 6:.1f}/h; the old policy ~28/h at -7 s/min): background "
          f"corrections at most 12/h ({n_bg}) and at most one precision write per zone start ({n_prec}, zone start 12:00)",
          n_bg <= 72 and n_prec <= 1 and len(w) == n_bg + n_prec, str([(x[1], x[3]) for x in w if x[1] not in (rp.R_BACKGROUND,)]))
    check(f"-8.8 s/min: the true clock error stays below 90 s ({worst:.0f} s max)", worst < 90, f"{worst:.0f}")
    b12 = bnd.get(hms(12, 0), [None])[0]
    check(f"-8.8 s/min: the 12:00 zone start within 25 s ({b12}) - a precision correction lands 60-120 s before it",
          b12 is not None and abs(b12) <= 25, str(b12))
    starts_in_quiet = [x for x in w if rp.in_quiet_window(at(x[3], 0, 0))]
    check("no correction ever starts in a quiet window", not starts_in_quiet, str(starts_in_quiet[:3]))
    bg = [x[0] for x in w if x[1] == rp.R_BACKGROUND]
    gaps = [b - a for a, b in zip(bg, bg[1:])]
    check("background corrections are at least 5 min apart", all(g >= 300 for g in gaps), str(min(gaps) if gaps else None))
    # the fast regime (+4.5 s/min) through the 16:35 zone start
    # (a positive error is never inflated by the stale image, it is understated by up to 10 s; with two confirming reads the true
    #  error reaches about the floor + 10 + 2 x 4.5 s before a background correction)
    # (cadence ~ (floor + ~5 s mean staleness + 2.5 s set error) / 4.5 s/min + one confirming read ~ every 9-10 min at floor 30)
    w, worst, bnd = run_day(lambda t: 4.5, 3, seed=6, start_tod=hms(15, 0))
    b1635 = bnd.get(hms(16, 35), [None])[0]
    check(f"+4.5 s/min (15:00-18:00, the top of the fast regime): {len(w)} writes (<= 7/h), true error <= floor + 25 s ({worst:.0f}), "
          f"the 16:35 zone start within 20 s ({b1635})", len(w) <= 21 and worst <= BG + 25 and b1635 is not None and abs(b1635) <= 20,
          str([(x[1], x[3]) for x in w]))
    # an energy transaction 13:00-14:00 holds routine corrections; a large error still corrects
    lease = lambda tod: hms(13, 0) <= tod < hms(14, 0)  # noqa: E731
    w, worst, _ = run_day(lambda t: -7.0, 3, seed=7, start_tod=hms(12, 30), lease=lease)
    inside = [x for x in w if hms(13, 0) <= x[3] < hms(14, 0)]
    check("an active energy transaction holds every routine correction; only errors >= 300 s correct inside it",
          all(x[1] == rp.R_LARGE for x in inside), str([(x[1], x[3], round(x[2])) for x in inside]))
    # boot alignment
    w, _, _ = run_day(lambda t: 0.0, 0.2, seed=8, start_tod=hms(9, 0), start_offset=-30.0, boot_aligned=False)
    check("after boot a -30 s clock (inside the background band) is aligned once (reason boot)", [x[1] for x in w] == [rp.R_BOOT], str(w))


# ===========================================================================
# [4] C++ == Python
# ===========================================================================
FNV_OFFSET = 0xCBF29CE484222325
FNV_PRIME = 0x100000001B3
M64 = (1 << 64) - 1


def fnv(h: int, v: int, width: int) -> int:
    for k in range(width):
        h ^= (v >> (8 * k)) & 0xFF
        h = (h * FNV_PRIME) & M64
    return h


def dec_digest(h: int, d: rp.Decision) -> int:
    h = fnv(h, d.action, 1)
    h = fnv(h, d.reason, 1)
    h = fnv(h, d.threshold_s & 0xFFFFFFFF, 4)
    h = fnv(h, d.precision_key & 0xFFFFFFFF, 4)
    return fnv(h, int(d.boot_settled), 1)


CXX_PRELUDE = r"""#include "ecco_rtc_policy.h"
namespace t {
using namespace ecco_rtc;
constexpr uint64_t fnv(uint64_t h, uint64_t v, int width) {
  for (int k = 0; k < width; k++) {
    h ^= (v >> (8 * k)) & 0xFFu;
    h *= 0x100000001B3ull;
  }
  return h;
}
constexpr uint64_t dd(uint64_t h, const Decision &d) {
  h = fnv(h, d.action, 1);
  h = fnv(h, d.reason, 1);
  h = fnv(h, (uint32_t) d.threshold_s, 4);
  h = fnv(h, d.precision_key, 4);
  return fnv(h, d.boot_settled ? 1u : 0u, 1);
}
"""


def emit_case(n: int, i: rp.Inputs) -> str:
    tou = ", ".join(str(x & 0xFFFF) for x in i.tou_raw)
    return (f"constexpr Inputs c{n}() {{ Inputs in{{}}; in.auto_sync = {str(i.auto_sync).lower()}; in.lock_held = {str(i.lock_held).lower()}; "
            f"in.cooldown_active = {str(i.cooldown_active).lower()}; in.lease_active = {str(i.lease_active).lower()}; "
            f"in.boot_aligned = {str(i.boot_aligned).lower()}; in.err_s = {i.err_s}; in.prev_valid = {str(i.prev_valid).lower()}; "
            f"in.prev_err_s = {i.prev_err_s}; in.ntp_elapsed_s = {i.ntp_elapsed_s}; in.inv_elapsed_s = {i.inv_elapsed_s}; "
            f"in.tod_s = {i.tod_s}u; in.day = {i.day}; in.threshold_s = {i.threshold_s}; in.have_last_auto = {str(i.have_last_auto).lower()}; "
            f"in.since_last_auto_ms = {i.since_last_auto_ms & 0xFFFFFFFF}u; in.precision_served = {i.precision_served & 0xFFFFFFFF}u; "
            f"const uint16_t w[6] = {{{tou}}}; for (int k = 0; k < 6; k++) in.tou_raw[k] = w[k]; return in; }}\n"
            f"static_assert(dd(0xCBF29CE484222325ull, decide(c{n}())) == {dec_digest(FNV_OFFSET, rp.decide(i))}ull, \"case {n}\");\n")


GRID_ERRS = (-400, -300, -299, -90, -61, -60, -59, -25, -21, -20, -19, -5, 0, 5, 19, 20, 21, 25, 59, 60, 61, 90, 299, 300, 400)


def grid_digest_py(step: int) -> int:
    h = FNV_OFFSET
    for tod in range(0, 86400, step):
        for k, e in enumerate(GRID_ERRS):
            i = rp.golden_base()
            i.tod_s = tod
            i.err_s = e
            i.prev_err_s = e + (3 if e >= 0 else -3)
            i.boot_aligned = (k % 5) != 0
            i.lease_active = (k % 7) == 3
            i.precision_served = 0 if k % 2 else (20730 * 1440 + 995 + 1)
            h = dec_digest(h, rp.decide(i))
            h = fnv(h, int(rp.in_quiet_window(i)), 1)
            h = fnv(h, rp.precision_key(i), 4)
    return h


def cxx_grid(step: int) -> str:
    errs = ", ".join(str(e) for e in GRID_ERRS)
    return (f"constexpr int32_t kErrs[{len(GRID_ERRS)}] = {{{errs}}};\n"
            "constexpr uint64_t grid() {\n"
            "  uint64_t h = 0xCBF29CE484222325ull;\n"
            f"  for (uint32_t tod = 0; tod < 86400u; tod += {step}u) {{\n"
            f"    for (int k = 0; k < {len(GRID_ERRS)}; k++) {{\n"
            "      Inputs in = golden_base();\n"
            "      in.tod_s = tod;\n"
            "      in.err_s = kErrs[k];\n"
            "      in.prev_err_s = kErrs[k] + (kErrs[k] >= 0 ? 3 : -3);\n"
            "      in.boot_aligned = (k % 5) != 0;\n"
            "      in.lease_active = (k % 7) == 3;\n"
            "      in.precision_served = (k % 2) ? 0u : (20730u * 1440u + 995u + 1u);\n"
            "      h = dd(h, decide(in));\n"
            "      h = fnv(h, in_quiet_window(in) ? 1u : 0u, 1);\n"
            "      h = fnv(h, precision_key(in), 4);\n"
            "    }\n"
            "  }\n"
            "  return h;\n"
            "}\n"
            f"static_assert(grid() == {grid_digest_py(step)}ull, \"full-day grid\");\n")


def cxx_arith(rnd: random.Random) -> str:
    out = []
    for n in range(300):
        iy, ny = rnd.randint(2020, 2099), rnd.randint(2020, 2099)
        im, nm = rnd.randint(1, 12), rnd.randint(1, 12)
        idd, nd = rnd.randint(1, 28), rnd.randint(1, 28)
        isod, nsod = rnd.randrange(86400), rnd.randrange(86400)
        out.append(f"static_assert(full_error_s({iy}, {im}, {idd}, {isod}, {ny}, {nm}, {nd}, {nsod}) == "
                   f"{rp.full_error_s(iy, im, idd, isod, ny, nm, nd, nsod)}, \"full_error_s {n}\");\n")
        a, b = rnd.randrange(86400), rnd.randrange(86400)
        out.append(f"static_assert(elapsed_s({a}, {b}) == {rp.elapsed_s(a, b)}, \"elapsed_s {n}\");\n")
        w = rnd.randrange(1 << 16) if n % 2 else rnd.randint(0, 23) * 100 + rnd.randint(0, 59)
        out.append(f"static_assert(tou_valid({w}) == {str(rp.tou_valid(w)).lower()} && tou_second_of_day({w}) == "
                   f"{rp.tou_second_of_day(w)}u, \"tou {n}\");\n")
        now, since = rnd.randrange(1 << 32), rnd.randrange(1 << 32)
        q = rnd.random() < 0.5
        out.append(f"static_assert(breaker_due({now}u, {since}u, {str(q).lower()}) == {str(rp.breaker_due(now, since, q)).lower()}, "
                   f"\"breaker {n}\");\n")
    for q in (0, 1):
        for a_ in (0, 1):
            for v in (0, 1):
                for c in (0, 1):
                    out.append(f"static_assert(no_rtc_frame_outstanding({str(bool(q)).lower()}, {str(bool(a_)).lower()}, "
                               f"{str(bool(v)).lower()}, {str(bool(c)).lower()}) == "
                               f"{str(rp.no_rtc_frame_outstanding(bool(q), bool(a_), bool(v), bool(c))).lower()}, \"idle {q}{a_}{v}{c}\");\n")
    for r in range(0, 14):
        out.append(f"static_assert(__builtin_strcmp(reason_name({r}), \"{rp.reason_name(r)}\") == 0, \"reason_name {r}\");\n")
    return "".join(out)


def strip_goldens(text: str) -> str:
    """The header with every golden-vector static_assert (the block after the golden helpers) removed; the helpers stay."""
    start = text.index("static_assert(days_from_civil(1970, 1, 1)")
    end = text.index("}  // namespace ecco_rtc")
    return text[:start] + text[end:]


def find_compiler() -> str | None:
    env = os.environ.get("ECCO_CXX")
    if env:
        return env
    for name in ("g++", "c++", "clang++"):
        found = shutil.which(name)
        if found:
            return found
    return None


def compile_tu(src: str, header_text: str | None = None, std: str = "gnu++17") -> tuple[int, str]:
    cxx = find_compiler()
    if cxx is None:
        return 127, "no C++ compiler found (this check fails rather than skips; set ECCO_CXX)"
    with tempfile.TemporaryDirectory(prefix="fbd1_cpp_") as d:
        tmp = Path(d)
        (tmp / "tu.cpp").write_text(src, encoding="utf-8", newline="\n")
        (tmp / "ecco_rtc_policy.h").write_text(header_text if header_text is not None else HEADER_TEXT, encoding="utf-8", newline="\n")
        cmd = [cxx, f"-std={std}", "-fsyntax-only", "-Wall", "-Wextra", "-Werror", "-fconstexpr-ops-limit=400000000",
               "-fconstexpr-loop-limit=4000000", "-I", str(tmp), str(tmp / "tu.cpp")]
        p = subprocess.run(cmd, capture_output=True, text=True)
        return p.returncode, (p.stdout + p.stderr)[-3000:]


def section_parity() -> None:
    print("\n[4] C++ == Python (a real compiler evaluates the header)")
    cxx = find_compiler()
    check("a C++ compiler is available (this check fails rather than skips)", cxx is not None, "set ECCO_CXX")
    if cxx is None:
        return
    rnd = random.Random(20261004)
    cases = [random_inputs(rnd) for _ in range(400)]
    # the goldens and the hand-picked edge cases ride along
    cases += [G(-60, -66), G(-59, -66), G(-90, -45), G(90, -90), A(hms(16, 31, 30), -22, -21), A(hms(11, 59), -70, -65)]
    for tod, word in ((hms(23, 58, 30), 0), (hms(23, 59, 30), 1), (hms(23, 59, 59), 2359), (hms(0, 0, 0), 0), (hms(0, 3, 30), 5)):
        c = at(tod, -12, 0)
        c.tou_raw = [word, 0xFFFF, 0xFFFF, 0xFFFF, 0xFFFF, 0xFFFF]  # zone starts at / across midnight
        cases.append(c)
    for ntp_el, inv_el in ((60, 45), (60, 44), (61, 46), (61, 45), (20, 5), (150, 135), (150, 134)):
        c = G(-90, -80)
        c.ntp_elapsed_s, c.inv_elapsed_s = ntp_el, inv_el  # the frozen-image boundary
        cases.append(c)
    for w in TOU:
        b = rp.tou_second_of_day(w)
        for e in (61, 119, 120, 121, 299, 300):  # zone-cross edges before every zone start
            cases.append(at((b - 120) % 86400, e, e - 2))
            cases.append(at((b - 61) % 86400, e, e - 2))
        for off in (-121, -120, -90, -61, -60, -1, 0, 59, 60):
            cases.append(at((b + off) % 86400, -90, -88))  # quiet-window edges of every zone start
            cases.append(at((b + off) % 86400, -12, 0))    # precision-window edges (one read, no previous read)
            cases.append(at((b + off) % 86400, 15, 14))   # between P / 2 and P
    body = "".join(emit_case(n, c) for n, c in enumerate(cases)) + cxx_arith(random.Random(7))
    src = CXX_PRELUDE + body + cxx_grid(30) + "}\nint main() { return 0; }\n"
    for std in ("gnu++17", "gnu++20"):
        rc, out = compile_tu(src, std=std)
        check(f"{std}: {len(cases)} decide() cases, 1200 arithmetic / TOU / breaker asserts, reason names and a full-day grid "
              f"(every 30 s x {len(GRID_ERRS)} errors, decide + quiet window + precision key) are identical in C++ and Python",
              rc == 0, out[-800:])
    # The mutants are judged by the PARITY asserts alone: the header's own golden static_asserts are stripped first (else a mutant
    # could be "killed" by a golden rather than by the C++ == Python comparison). The stripped, unmutated header must still pass.
    mut_src = CXX_PRELUDE + body + cxx_grid(60) + "}\nint main() { return 0; }\n"
    stripped = strip_goldens(HEADER_TEXT)
    rc, out = compile_tu(mut_src, stripped, std="gnu++17")
    check("control: the header without its golden static_asserts passes the mutant parity TU (so a failing mutant is a parity "
          "mismatch, not a golden)", rc == 0 and "static_assert(decide(" not in stripped, out[-600:])
    # mutants of the header must break the parity compile (proves the parity checks bite)
    mutants = (
        ("background floor 30 -> 31", "constexpr int32_t kBackgroundFloorS = 30;", "constexpr int32_t kBackgroundFloorS = 31;"),
        ("quiet window before 60 -> 30", "constexpr uint32_t kQuietBeforeS = 60u;", "constexpr uint32_t kQuietBeforeS = 30u;"),
        ("precision window lead 120 -> 180", "constexpr uint32_t kPrecisionLeadS = 120u;", "constexpr uint32_t kPrecisionLeadS = 180u;"),
        ("a precision correction needs two reads", "if (!precision_due && !confirmed(in, thr)) {", "if (!confirmed(in, thr)) {"),
        ("precision threshold P instead of P / 2", "precision_due ? precision_threshold(p) :", "precision_due ? p :"),
        ("frozen rule < -> <=", "const bool frozen = in.inv_elapsed_s < in.ntp_elapsed_s - kFrozenSlackS;",
         "const bool frozen = in.inv_elapsed_s <= in.ntp_elapsed_s - kFrozenSlackS;"),
        ("sign check removed", "if (a < thr || pa < thr || (in.err_s < 0) != (in.prev_err_s < 0))", "if (a < thr || pa < thr)"),
        ("lease no longer exempts large errors", "if (in.lease_active && !large) {", "if (in.lease_active) {"),
        ("TOU zone starts dropped from the quiet window", "    if ((until >= 1u && until <= kQuietBeforeS) || since < kQuietAfterS)\n      return true;",
         "    if (false && ((until >= 1u && until <= kQuietBeforeS) || since < kQuietAfterS))\n      return true;"),
        ("precision key ignores the next-day wrap", "const int32_t bday = in.day + (b < t ? 1 : 0);", "const int32_t bday = in.day;"),
        ("breaker ignores the idle (no RTC frame outstanding) term", "return idle && (uint32_t) (now_ms - since_ms) >= kTxnDeadlineMs;",
         "return (uint32_t) (now_ms - since_ms) >= kTxnDeadlineMs;"),
        ("the idle term forgets a verification in flight / waiting", "return bus_quiet || auto_sync_pending || verification_pending || comm_failure_pending;",
         "return bus_quiet || auto_sync_pending || comm_failure_pending;"),
        ("boot alignment threshold uses the background", "(boot_due ? p : bg);", "(boot_due ? bg : bg);"),
        ("full_error_s day factor 86400 -> 86399", "* 86400 +", "* 86399 +"),
        ("a large error may take the one-read precision path (review M1)", "pkey != in.precision_served && !large;",
         "pkey != in.precision_served;"),
        ("zone-cross hold dropped (review L3)", "  if (would_step_back_across(in)) {", "  if (false && would_step_back_across(in)) {"),
        ("zone-cross also holds negative errors", "  if (in.err_s <= 0 || in.err_s >= kLargeErrorS)\n    return false;\n  const uint32_t t",
         "  if (in.err_s == 0 || in.err_s >= kLargeErrorS)\n    return false;\n  const uint32_t t"),
        ("zone-cross ignores TOU zone starts", "    if (until >= 1u && until <= e)\n      return true;",
         "    if (false && until >= 1u && until <= e)\n      return true;"),
    )
    for what, old, new in mutants:
        assert stripped.count(old) == 1, what
        rc, _ = compile_tu(mut_src, stripped.replace(old, new), std="gnu++17")
        check(f"header mutant is caught by the C++ == Python parity asserts: {what}", rc != 0)
    rc, out = compile_tu('#include "ecco_rtc_policy.h"\nint main() { return 0; }\n', std="c++17")
    check("the header alone compiles strictly (-std=c++17 -Wall -Wextra -Werror) and its own golden static_asserts hold", rc == 0, out[-600:])


# ===========================================================================
# [5] static
# ===========================================================================
def section_static() -> None:
    print("\n[5] static: purity and naming")
    code = re.sub(r"//[^\n]*", "", HEADER_TEXT)
    includes = re.findall(r"^#include\s+(\S+)", HEADER_TEXT, re.M)
    check("the header includes only standard headers (<array>, <cstdint>)", sorted(includes) == ["<array>", "<cstdint>"], str(includes))
    check("the header has one namespace (ecco_rtc), no static / inline / state, no id(), millis(), ESP_LOG, esphome symbol",
          re.findall(r"^namespace\s+(\w+)", code, re.M) == ["ecco_rtc"] and not re.search(r"^\s*(static|inline)\s+(?!_assert)", code, re.M)
          and not re.search(r"\bid\(|millis\(|ESP_LOG|esphome|modbus|App\.", code))
    hdr_funcs = set(re.findall(r"^constexpr\s+[^=;(]*?\b(\w+)\s*\(", code, re.M))
    hdr_consts = set(re.findall(r"^constexpr\s+(?:u?int\d+_t|bool)\s+(k\w+)\s*=", code, re.M))
    hdr_enums = set(re.findall(r"\b((?:ACT|R)_[A-Z_]+)\s*=", code))
    golden_helpers = {"golden_base", "golden_err", "golden_at"}
    missing = sorted(n for n in (hdr_funcs | hdr_consts | hdr_enums) if not hasattr(rp, n))
    check("every header function / constant / enumerator exists in the mirror under the same name", not missing, str(missing))
    py_funcs = {n for n, v in vars(rp).items() if callable(v) and not n.startswith("_") and not isinstance(v, type)}
    extra = sorted(py_funcs - hdr_funcs - {"field", "dataclass"} - set())
    check("the mirror defines no public function the header lacks", not extra, str(extra))
    for struct, cls in (("Inputs", rp.Inputs), ("Decision", rp.Decision)):
        body = re.search(r"struct\s+" + struct + r"\s*\{(.*?)\n\};", code, re.S).group(1)
        cf = re.findall(r"^\s*[\w:<>, ]+?\s+(\w+)(?:\{\})?\s*(?:=[^;]*)?;", body, re.M)
        pf = [f.name for f in __import__("dataclasses").fields(cls)]
        check(f"struct {struct}: the same fields in the same order in C++ and Python", cf == pf, f"{cf} vs {pf}")
    defaults_c = re.search(r"struct\s+Inputs\s*\{(.*?)\n\};", code, re.S).group(1)
    check("Inputs defaults are fail-closed on both sides (lock held, cooldown, lease, auto off, no previous read)",
          "bool lock_held = true;" in defaults_c and "bool cooldown_active = true;" in defaults_c and "bool lease_active = true;" in defaults_c
          and "bool auto_sync = false;" in defaults_c and rp.Inputs().lock_held and rp.Inputs().cooldown_active and rp.Inputs().lease_active
          and not rp.Inputs().auto_sync and not rp.Inputs().prev_valid)
    used = set(re.findall(r"ecco_rtc::(\w+)", FW_TEXT))
    check("every ecco_rtc:: name the firmware uses exists in the header and the mirror",
          bool(used) and all(n in (hdr_funcs | hdr_consts | hdr_enums | {"Inputs", "Decision"}) and hasattr(rp, n) for n in used), str(sorted(used)))
    check("the firmware includes the header (esphome includes)", "    - include/ecco_rtc_policy.h\n" in FW_TEXT)
    check("deadline: 60 s (FB-C RS_RTC_LOCK_STUCK) < kTxnDeadlineMs = 90 s < 180 s (HA RTC_CORRECTION_STUCK), above the ~49 s worst "
          "legitimate lock hold", rp.kTxnDeadlineMs == 90000 and "constexpr uint32_t kTxnDeadlineMs = 90000u;" in HEADER_TEXT)
    check("the header's golden helpers are mirrored", all(hasattr(rp, n) for n in golden_helpers))


def main() -> int:
    section_table()
    section_time()
    section_behaviour()
    section_parity()
    section_static()
    print()
    if FAILURES:
        print(f"{len(FAILURES)} check(s) FAILED:")
        for f in FAILURES:
            print(f"  - {f}")
        return 1
    print("All FB-D1 RTC policy checks passed.")
    print("These prove the policy logic and its C++ / Python agreement offline; they prove nothing about the inverter or the live device.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
