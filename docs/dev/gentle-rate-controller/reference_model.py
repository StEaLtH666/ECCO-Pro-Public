#!/usr/bin/env python3
"""Guarded charge-rate controller (GRC): the pure decision core, as an executable reference model.

Executable specification of docs/dev/gentle-rate-controller/SPEC.md (revision 3). The firmware form is
docs/dev/gentle-rate-controller/proposed/ecco_gentle_rate_core.h; registry/tests/test_gentle_rate_core_host.py proves
the header produces the same trace as this model on every vector of vectors.json and on a seeded random fuzz.

What it decides: whether a lease may start, which single slot-power value to write next (or none), when the lease
must end and be restored, and when to latch a fault. What it never does: I/O. The caller (the firmware integration)
performs the ownership read, the durable commit, the Modbus write, the readback and the restore classification, and
reports the outcome on a later tick as `op`, tagged with the sequence number and kind of the action it answers.

Arithmetic is integer only: power in W, SOC in tenths of a percent (0..1000), uptime in wrap-safe unsigned 32-bit ms,
wall clock in epoch seconds (0 = not valid). Every division has non-negative operands, so Python `//` and C++ `/`
agree. The controller is SUBTRACTIVE: it never writes above the value the slot held before the lease (`original`), and
the restore writes exactly `original`.
"""

from __future__ import annotations

import zlib
from dataclasses import dataclass, field

MASK32 = 0xFFFFFFFF
NEVER = 0xFFFFFFFF            # rx_age_ms: the inverter has not answered any read since this boot

# ---------------------------------------------------------------------------------------------------------------
# Enumerations (the numeric values are part of the contract with the header)
# ---------------------------------------------------------------------------------------------------------------
IDLE, ARMED, LEASED, ADJUSTING, SETTLING, RESTORING, FAULT = range(7)
STATE_NAMES = ["IDLE", "ARMED", "LEASED", "ADJUSTING", "SETTLING", "RESTORING", "FAULT"]

A_NONE, A_WRITE, A_RESTORE = range(3)
ACTION_NAMES = ["NONE", "WRITE", "RESTORE"]

# OK: done and read back equal. OK_NOWRITE: a restore found the original. FAIL: the inverter answered and it did not
# work: an exception response (to the fresh read or the write), a readback that differs, or a write sent whose
# readback went unanswered. FOREIGN: the fresh read found a value the lease does not own; nothing written. NO_ANSWER:
# the fresh read that precedes every write got NO reply at all (a timeout, never an exception); nothing written.
# DEFERRED: the operation was not run (bus not free, or the previous run still executing); nothing written.
OP_NONE, OP_OK, OP_OK_NOWRITE, OP_FAIL, OP_FOREIGN, OP_NO_ANSWER, OP_DEFERRED = range(7)
OP_NAMES = ["NONE", "OK", "OK_NOWRITE", "FAIL", "FOREIGN", "NO_ANSWER", "DEFERRED"]

# OTHER_INTERLOCK (32) is reserved for a future grid-loss interlock: none exists in the base firmware (SPEC section 12).
OTHER_FREE_POWER, OTHER_DUMP, OTHER_EDITOR, OTHER_REG244, OTHER_FALLBACK, OTHER_INTERLOCK = 1, 2, 4, 8, 16, 32

CLS_ALREADY, CLS_OWNED, CLS_FOREIGN = range(3)

# Reasons (u8). Refusals 1..39, lifecycle events 40..59, lease-end reasons 60..99, latched faults 100..
R_NONE = 0
R_REFUSE_NOT_ARMED = 1
R_REFUSE_NIGHT_USED = 2
R_REFUSE_CLOCK = 3
R_REFUSE_CLOCK_CHANGE = 4
R_REFUSE_INVERTER_CLOCK = 5
R_REFUSE_RTC = 6
R_REFUSE_OTHER = 7
R_REFUSE_FAULT = 8
R_REFUSE_TELEMETRY = 9
R_REFUSE_SOC = 10
R_REFUSE_PLAN_INVALID = 11
R_REFUSE_PLAN_STALE = 12
R_REFUSE_CONFIG_STALE = 13
R_REFUSE_SLOT = 14
R_REFUSE_SLOT_POWER = 15
R_REFUSE_TARGET_MET = 16
R_REFUSE_NOT_CHARGING = 17
R_REFUSE_IMPLAUSIBLE = 18
R_REFUSE_TOO_LATE = 19
R_REFUSE_TARGET_AT_RISK = 20
R_REFUSE_WRITE_BUDGET = 21
R_REFUSE_GRID = 22
R_REFUSE_RESTORE = 23
R_REFUSE_WEEK_BUDGET = 24
R_REFUSE_LIFE_BUDGET = 25
R_REFUSE_CONFIG = 26
R_ARMED = 40
R_DISARMED = 41
R_ARM_EXPIRED = 42
R_LEASE_STARTED = 43
R_WRITE_REQUESTED = 44
R_WRITE_VERIFIED = 45
R_RESPONSE_OK = 46
R_RESPONSE_WEAK = 47
R_BMS_LIMITED = 48
R_RESTORE_REQUESTED = 49
R_RESTORED = 50
R_RESTORE_RETRY = 51
R_ACKED = 52
R_STALE_RESULT = 53
R_RESTORE_DEFERRED = 54
R_RESTORE_UNANSWERED = 55
R_OWNER_RESTORE = 56
R_END = 60
R_CLOCK_INVALID = 61
R_CLOCK_CHANGE = 62
R_INVERTER_CLOCK = 63
R_DEADLINE = 64
R_WATCHDOG = 65
R_OTHER_ACTIVITY = 66
R_INVERTER_FAULT = 67
R_TELEMETRY_STALE = 68
R_SOC_INVALID = 69
R_PLAN_LOST = 70
R_PLAN_INVALID = 71
R_CONFIG_STALE = 72
R_CONFIG_DRIFT = 73
R_TARGET_REACHED = 74
R_TARGET_GUARD = 75
R_RUNAWAY = 76
R_CHARGE_STOPPED = 77
R_RTC_STUCK = 78
R_WRITE_FAILED = 79
R_OP_TIMEOUT = 80
R_WRONG_DIRECTION = 81
R_NO_RESPONSE = 82
R_IMPLAUSIBLE_GAIN = 83
R_BOOT_RECOVERY = 84
R_GRID_LOSS = 85
R_READBACK_MISMATCH = 86
R_PLAN_WINDOW = 87
R_WRITE_DEFERRED = 88
R_WRITE_UNANSWERED = 89
R_FOREIGN = 100
R_RESTORE_FAILED = 101
R_RECORD_CORRUPT = 102
R_NIGHT_CEILING = 103
R_RESTORE_STALLED = 104
REASONS = {k: v for k, v in globals().items() if k.startswith("R_") and isinstance(v, int)}
REASON_NAMES = {v: k for k, v in REASONS.items()}


# ---------------------------------------------------------------------------------------------------------------
# Configuration (firmware substitutions; defaults are the proposed production values, except capacity_floor_wh: it
# has NO usable default and must be set by the site, SPEC section 5)
# ---------------------------------------------------------------------------------------------------------------
@dataclass
class Config:
    floor_w: int = 500                 # lowest value ever written (the Dump B2 floor)
    round_w: int = 100                 # every written value is a multiple of this
    fw_bound_w: int = 8000             # ecco_inverter_tou_power_ceiling_w
    max_step_w: int = 2000             # largest change per write (rate-of-change cap), the owner ceiling included
    hyst_w: int = 300                  # no change smaller than this
    reversal_extra_w: int = 300        # a change against the previous direction needs hyst + this
    dwell_ms: int = 1_800_000          # 30 min between changes
    settle_ms: int = 45_000            # the Dump settle time before a response is judged
    judge_samples: int = 4             # fresh telemetry samples averaged to judge a response
    max_changes: int = 6               # change writes per lease (the START write included)
    max_restore_attempts: int = 3      # ANSWERED restore failures per lease (an unanswered one is not counted)
    owner_restore_reserve: int = 1     # writes of the night kept for the owner's Restore original
    night_write_ceiling: int = 10      # every write of the night: changes + restores + the owner's reserve
    week_write_ceiling: int = 42       # every write of the last 7 nights (flash wear NOT ESTABLISHED)
    life_write_ceiling: int = 4000     # every write since the record exists (flash wear NOT ESTABLISHED)
    restore_free_max: int = 10         # unanswered or deferred restores per night (they spend no attempt)
    restore_stall_ms: int = 600_000    # a restore owed this long while the inverter answers: FAULT RESTORE_STALLED
    restore_backoff_ms: int = 30_000
    op_timeout_ms: int = 15_000        # an operation without any result is a failure
    plan_max_age_ms: int = 1_200_000   # 20 min without a plan hand-over = Home Assistant lost
    telemetry_stale_ms: int = 90_000   # the Dump SOC staleness bound
    config_stale_ms: int = 180_000     # the Dump configuration-block staleness bound
    rtc_busy_max_ms: int = 300_000
    clock_skew_max_s: int = 120        # the TOU editor's inverter-clock bound
    end_margin_s: int = 600            # the lease ends at least this long before the SLOT's own end
    min_lease_s: int = 3600
    arm_window_ms: int = 43_200_000    # a one-shot arm expires after 12 h
    charging_min_w: int = 1000         # START needs a running grid charge
    response_min_pct: int = 30         # a response must show this share of the expected change
    wrong_dir_w: int = 300
    max_ineffective: int = 2
    gain_min_pct: int = 50             # realised / setpoint, in percent: outside = implausible
    gain_max_pct: int = 150
    runaway_pct: int = 115             # realised above p0 * this / 100 + margin = runaway
    runaway_margin_w: int = 500
    runaway_samples: int = 3
    stop_w: int = 100
    stop_samples: int = 3
    stop_soc_gap: int = 20             # tenths of a percent below the target
    soc_jump_max: int = 50             # tenths of a percent between two samples
    soc_drop_max: int = 20             # tenths of a percent below the lease maximum
    guard_margin_s: int = 900
    guard_derate_pct: int = 85         # the plateau at today's rate, derated
    guard_tail_pct: int = 25           # the tail above the taper knee, as a share of today's rate (taper NOT ESTABLISHED)
    watchdog_extra_ms: int = 600_000
    rx_fresh_ms: int = 30_000          # a restore is emitted only when the inverter answered a read this recently
    window_match_s: int = 120          # the plan's window end must lie this close to the slot's own end
    capacity_floor_wh: int = 0         # SITE SUBSTITUTION, no usable default: at least the usable capacity (SPEC 5)
    taper_max_pct: int = 95            # the highest taper knee the target guard accepts from a plan
    script_steps: int = 3              # Modbus steps of one grc_execute run (fresh read, write, readback)
    script_step_ms: int = 3_000        # each bounded by the existing 3 s wait_until
    script_queue_ms: int = 3_000       # the bus queue ahead of the first step


def config_ok(c: Config) -> bool:
    """Structural validity of a configuration (the integration static_asserts the production values). The default
    Config is NOT valid: capacity_floor_wh must be set by the site (no usable default)."""
    return (c.round_w > 0 and c.floor_w > 0 and c.floor_w % c.round_w == 0 and c.fw_bound_w % c.round_w == 0
            and c.fw_bound_w >= c.floor_w + c.hyst_w and c.fw_bound_w <= 8000
            and 0 < c.hyst_w and c.max_step_w >= c.hyst_w and c.max_step_w % c.round_w == 0
            and c.settle_ms < c.dwell_ms and c.judge_samples >= 1 and c.max_changes >= 1
            and c.max_restore_attempts >= 1 and c.owner_restore_reserve >= 1
            and c.night_write_ceiling >= c.max_changes + c.max_restore_attempts + c.owner_restore_reserve
            and c.night_write_ceiling <= 255 and c.week_write_ceiling >= c.night_write_ceiling
            and c.life_write_ceiling >= c.week_write_ceiling and c.life_write_ceiling <= 1_000_000
            and 1 <= c.restore_free_max <= 255
            and c.restore_stall_ms >= 2 * (c.restore_backoff_ms + c.op_timeout_ms) and c.restore_stall_ms <= 3_600_000
            and c.gain_min_pct < c.gain_max_pct and c.response_min_pct > 0
            and c.plan_max_age_ms < c.arm_window_ms and c.op_timeout_ms > 0 and c.restore_backoff_ms > 0
            and 0 < c.guard_tail_pct <= c.guard_derate_pct <= 100
            and c.charging_min_w >= 2 * c.round_w
            and c.script_steps >= 1 and c.script_step_ms > 0
            and c.op_timeout_ms > c.script_steps * c.script_step_ms + c.script_queue_ms
            and c.end_margin_s > c.clock_skew_max_s + 60 and 60 < c.window_match_s <= 600
            and 1000 <= c.capacity_floor_wh <= 100000 and 50 <= c.taper_max_pct <= 100
            and 0 < c.rx_fresh_ms < c.restore_stall_ms)


@dataclass
class Plan:
    valid: bool = False
    age_ms: int = 0
    slot: int = 0               # 1..6, the grid-charge slot whose power the lease shapes
    target: int = 0             # % ; must equal that slot's own SOC target
    deadline: int = 0           # epoch s: window end minus the owner's finish-early buffer
    window_end: int = 0         # epoch s: the slot's end; must match the slot's configured end (window_match_s)
    ceiling_w: int = 0          # owner limit, setpoint units; approached by at most max_step_w per change
    capacity_wh: int = 0        # pessimistic usable capacity; the guard uses max(this, capacity_floor_wh)
    taper: int = 0              # % ; above it a weak response is the BMS taper, not a fault
    n: int = 0
    t: list = field(default_factory=lambda: [0] * 8)   # epoch s, strictly increasing
    p: list = field(default_factory=lambda: [0] * 8)   # wanted REALISED battery charge power, W (DC side)


@dataclass
class In:
    now_ms: int = 0
    epoch: int = 0
    local_min: int = -1
    night_id: int = 0           # local DAY NUMBER of the window's start (rolls at local noon), 0 = unknown
    clock_change_night: bool = False
    inv_skew_s: int = -1
    rtc_busy: bool = False
    mutex_busy: bool = False    # the shared write mutex, the bus, OR the GRC's own grc_execute still running
    other: int = 0
    fault: bool = False
    arm: bool = False
    start: bool = False
    end: bool = False
    ack: bool = False
    op: int = OP_NONE
    soc: int = -1
    batt_w: int = 0
    tel_ok: bool = False
    tel_age_ms: int = 0
    sample_seq: int = 0
    cfg_age_ms: int = 0
    cfg_slot: int = 0           # the slot the configuration fields below describe (core.slot during a lease)
    live_sp: int = -1
    slot_start_min: int = 0
    slot_end_min: int = 0
    slot_grid: bool = False
    slot_target: int = 0
    op_seq: int = 0             # the Out.seq the result answers
    op_kind: int = A_NONE       # the Out.action the result answers
    op_value: int = -1          # the value the operation read last (the readback); -1 none
    rx_age_ms: int = NEVER      # since the inverter last answered any read; NEVER = not since this boot
    grid_ok: bool = False       # the inverter reports the grid connected, grid frequency in band
    restore_req: bool = False   # the owner's Restore original pulse
    plan: Plan = field(default_factory=Plan)


@dataclass
class Out:
    action: int = A_NONE
    value: int = 0
    seq: int = 0                # with an action: its sequence number, echoed back with the result
    slot: int = 0               # with an action: the slot (1..6) whose power register (256 + slot - 1) it targets
    disarm: bool = False
    commit: bool = False
    event: int = R_NONE


# ---------------------------------------------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------------------------------------------
def elapsed(now: int, then: int) -> int:
    """Wrap-safe uptime difference (exact for any interval below 2^32 ms, 49.7 days)."""
    return (now - then) & MASK32


def mod1440(x: int) -> int:
    return x % 1440


def in_slot(m: int, start: int, end: int) -> bool:
    """[start, end) in minutes of the day, wrapping midnight when start > end; start == end covers nothing."""
    if m < 0 or m >= 1440:
        return False
    if start < end:
        return start <= m < end
    if start > end:
        return m >= start or m < end
    return False


def slot_end_epoch(epoch: int, local_min: int, slot_end_min: int) -> int:
    """The slot's own end on the dongle clock, never later than the real end: the whole minutes to the slot's end
    from the present local minute (wrapping midnight), less the up to 60 s already gone in that minute."""
    return epoch + mod1440(slot_end_min - local_min) * 60 - 60


def round_up(x: int, step: int) -> int:
    return (max(0, x) + step - 1) // step * step


def plan_ok(pl: Plan, c: Config) -> bool:
    if not pl.valid or not 1 <= pl.slot <= 6 or not 10 <= pl.target <= 100:
        return False
    if not c.floor_w <= pl.ceiling_w <= c.fw_bound_w or pl.ceiling_w % c.round_w != 0:
        return False
    if not 1000 <= pl.capacity_wh <= 100000 or not 50 <= pl.taper <= 100:
        return False
    if pl.deadline <= 0 or pl.window_end <= pl.deadline or not 1 <= pl.n <= 8:
        return False
    prev = 0
    for k in range(pl.n):
        if pl.t[k] <= prev or not 0 <= pl.p[k] <= 10000:
            return False
        prev = pl.t[k]
    return True


def plan_power(pl: Plan, epoch: int) -> int:
    """Piecewise constant: the last point at or before `epoch`; before the first point, the first point."""
    val = pl.p[0]
    for k in range(pl.n):
        if pl.t[k] <= epoch:
            val = pl.p[k]
    return val


def classify_restore(live: int, original: int, v: int, p: int, q: int) -> int:
    """What a restore may do with the live slot power: nothing (already the original), write the original (a value
    the lease itself left: the last verified V, the pending P, or Q, a value read back under the GRC's own lock after
    its own write; q = -1 none), or nothing at all (FOREIGN: someone else wrote it)."""
    if live == original:
        return CLS_ALREADY
    if live == v or live == p or (q >= 0 and live == q):
        return CLS_OWNED
    return CLS_FOREIGN


def ownership_ok_for_write(live: int, v: int) -> bool:
    """The pre-write ownership read: the live slot power must still be the last verified value."""
    return live == v


def lost_lease_slots(live: list, table: list) -> int:
    """At a boot with NO record: bit k-1 set for each slot k whose live power is below the OWNER's value for it, a
    lowered value a lost record may have left. `table` is a durable owner copy (the saved fallback profile's six slot
    powers, FB-B2), never the editor's staging numbers (manual_slotN_power: restore_value false, initial 8000). A
    warning only; nothing is written on it. -1 = unknown (no saved profile), never a warning."""
    mask = 0
    for k in range(6):
        if live[k] >= 0 and table[k] >= 0 and live[k] < table[k]:
            mask |= 1 << k
    return mask


# ---------------------------------------------------------------------------------------------------------------
# The durable record (48 bytes, little endian, CRC-32 over bytes 0..43)
# ---------------------------------------------------------------------------------------------------------------
REC_SIZE = 48
REC_MAGIC = 0x5247
REC_VERSION = 3
F_ACTIVE, F_FAULT, F_NIGHT_USED, F_READBACK, F_NIGHT_UNKNOWN = 1, 2, 4, 8, 16
DEC_OK, DEC_ABSENT, DEC_BAD_SIZE, DEC_BAD_CRC, DEC_BAD_MAGIC, DEC_BAD_VERSION, DEC_BAD_VALUE = range(7)


@dataclass
class Record:
    flags: int = 0
    slot: int = 0
    reason: int = 0
    original: int = 0
    v: int = 0
    p: int = 0
    night_id: int = 0
    writes_night: int = 0
    changes: int = 0
    restore_attempts: int = 0
    free_night: int = 0         # unanswered or deferred restores this night
    lease_end: int = 0
    q: int = 0                  # the owned readback, meaningful only with F_READBACK
    hist: list = field(default_factory=lambda: [0] * 6)   # writes of the nights night_id - 1 .. night_id - 6
    life_writes: int = 0


def encode_record(r: Record) -> bytes:
    b = bytearray(REC_SIZE)
    b[0:2] = REC_MAGIC.to_bytes(2, "little")
    b[2] = REC_VERSION
    b[3] = r.flags & 0xFF
    b[4] = r.slot & 0xFF
    b[5] = r.reason & 0xFF
    b[6:8] = (r.original & 0xFFFF).to_bytes(2, "little")
    b[8:10] = (r.v & 0xFFFF).to_bytes(2, "little")
    b[10:12] = (r.p & 0xFFFF).to_bytes(2, "little")
    b[12:16] = (r.night_id & MASK32).to_bytes(4, "little")
    b[16] = r.writes_night & 0xFF
    b[17] = r.changes & 0xFF
    b[18] = r.restore_attempts & 0xFF
    b[19] = r.free_night & 0xFF
    b[20:24] = (r.lease_end & MASK32).to_bytes(4, "little")
    b[24:26] = (r.q & 0xFFFF).to_bytes(2, "little")
    for k in range(6):
        b[26 + k] = r.hist[k] & 0xFF
    b[32:36] = (r.life_writes & MASK32).to_bytes(4, "little")
    b[44:48] = (zlib.crc32(bytes(b[0:44])) & MASK32).to_bytes(4, "little")
    return bytes(b)


def decode_record(b: bytes | None, c: Config) -> tuple[int, Record]:
    r = Record()
    if b is None:
        return DEC_ABSENT, r
    if len(b) != REC_SIZE:
        return DEC_BAD_SIZE, r
    if int.from_bytes(b[44:48], "little") != (zlib.crc32(bytes(b[0:44])) & MASK32):
        return DEC_BAD_CRC, r
    if int.from_bytes(b[0:2], "little") != REC_MAGIC:
        return DEC_BAD_MAGIC, r
    if b[2] != REC_VERSION:
        return DEC_BAD_VERSION, r
    r.flags, r.slot, r.reason = b[3], b[4], b[5]
    r.original = int.from_bytes(b[6:8], "little")
    r.v = int.from_bytes(b[8:10], "little")
    r.p = int.from_bytes(b[10:12], "little")
    r.night_id = int.from_bytes(b[12:16], "little")
    r.writes_night, r.changes, r.restore_attempts, r.free_night = b[16], b[17], b[18], b[19]
    r.lease_end = int.from_bytes(b[20:24], "little")
    r.q = int.from_bytes(b[24:26], "little")
    r.hist = [b[26 + k] for k in range(6)]
    r.life_writes = int.from_bytes(b[32:36], "little")
    ok = (r.flags & ~31) == 0 and all(x == 0 for x in b[36:44]) and r.writes_night <= c.night_write_ceiling
    ok = ok and all(h <= c.night_write_ceiling for h in r.hist) and r.free_night <= c.restore_free_max
    if not r.flags & F_READBACK:
        ok = ok and r.q == 0
    if r.flags & F_NIGHT_UNKNOWN:
        ok = ok and r.night_id == 0 and not r.flags & F_ACTIVE
    if r.flags & F_ACTIVE:
        ok = ok and 1 <= r.slot <= 6 and c.floor_w + c.hyst_w <= r.original <= c.fw_bound_w
        ok = ok and c.floor_w <= r.v <= r.original and c.floor_w <= r.p <= r.original
        ok = ok and r.changes <= c.max_changes and r.restore_attempts <= c.max_restore_attempts and r.lease_end != 0
    else:
        ok = ok and r.slot == 0 and r.original == 0 and r.v == 0 and r.p == 0 and r.changes == 0
        ok = ok and r.restore_attempts == 0 and r.lease_end == 0 and not r.flags & F_READBACK
    if not ok:
        return DEC_BAD_VALUE, Record()
    return DEC_OK, r


# ---------------------------------------------------------------------------------------------------------------
# The core
# ---------------------------------------------------------------------------------------------------------------
class Core:
    def __init__(self, cfg: Config | None = None) -> None:
        self.c = cfg or Config()
        self.state = IDLE
        self.armed_ms = 0
        self.arm_latch = False
        self.night_id = 0
        self.night_used = False
        self.night_unknown = False
        self.writes_night = 0
        self.free_night = 0
        self.hist = [0] * 6
        self.life_writes = 0
        self.last_reason = R_NONE
        self.seen = False
        self.last_seq = 0
        self.seq = 0
        self._clear_lease()

    def _clear_lease(self) -> None:
        self.slot = 0
        self.original = 0
        self.v = 0
        self.p = 0
        self.q = -1
        self.prev_v = 0
        self.last_dir = 0
        self.target = 0
        self.taper = 0
        self.capacity_wh = 0
        self.lease_start_ms = 0
        self.lease_end = 0
        self.watchdog_ms = 0
        self.changes = 0
        self.last_change_ms = 0
        self.op_pending = False
        self.op_kind = A_NONE
        self.op_seq = 0
        self.op_start_ms = 0
        self.late_seq = 0
        self.late_kind = A_NONE
        self.end_pending = False
        self.grid_pending = False
        self.restore_attempts = 0
        self.restore_hold = False
        self.restore_from_ms = 0
        self.stall_ms = 0
        self.stall_mark_ms = 0
        self.p0 = 0
        self.p_ref = 0
        self.gain_pct = 0
        self.ineffective = 0
        self.bms_limited = False
        self.runaway_n = 0
        self.stop_n = 0
        self.judge_n = 0
        self.judge_sum = 0
        self.rtc_on = False
        self.rtc_since_ms = 0
        self.last_soc = -1
        self.soc_max = -1

    def week_writes(self) -> int:
        """Every write of this night and the six before it (the rolling 7-day window)."""
        return self.writes_night + sum(self.hist)

    # ---- the durable record of this core ------------------------------------------------------------------
    def record(self) -> Record:
        lease = self.state in (LEASED, ADJUSTING, SETTLING, RESTORING) or (self.state == FAULT and self.original != 0)
        rb = lease and self.q >= 0
        flags = ((F_ACTIVE if lease else 0) | (F_FAULT if self.state == FAULT else 0)
                 | (F_NIGHT_USED if self.night_used else 0) | (F_READBACK if rb else 0)
                 | (F_NIGHT_UNKNOWN if self.night_unknown else 0))
        r = Record(flags=flags, reason=self.last_reason, night_id=self.night_id, writes_night=self.writes_night,
                   free_night=self.free_night, hist=list(self.hist), life_writes=self.life_writes)
        if lease:
            r.slot, r.original, r.v, r.p = self.slot, self.original, self.v, self.p
            r.changes, r.restore_attempts, r.lease_end = self.changes, self.restore_attempts, self.lease_end
        if rb:
            r.q = self.q
        return r

    def boot(self, status: int, rec: Record, now_ms: int) -> None:
        """A restart. The restore an open lease owes is emitted only once the inverter has answered a read since
        this boot (the caller reports rx_age_ms = NEVER until then), so a dongle and inverter booting together, or an
        inverter that is down, spends no attempt."""
        self.__init__(self.c)
        self.arm_latch = True
        if status == DEC_ABSENT:
            return
        if status != DEC_OK:
            # original is unknown, and so are the night's counts: the boot's night is taken as used with every count
            # of the 7-day window full (START refused until they age out); adopted on the first tick with a night
            self.state, self.last_reason = FAULT, R_RECORD_CORRUPT
            self.night_unknown, self.night_used = True, True
            self.writes_night, self.free_night = self.c.night_write_ceiling, self.c.restore_free_max
            self.hist = [self.c.night_write_ceiling] * 6
            return
        self.night_id, self.writes_night, self.free_night = rec.night_id, rec.writes_night, rec.free_night
        self.hist, self.life_writes = list(rec.hist), rec.life_writes
        self.night_used = bool(rec.flags & F_NIGHT_USED)
        self.night_unknown = bool(rec.flags & F_NIGHT_UNKNOWN)
        self.last_reason = rec.reason
        if rec.flags & F_ACTIVE:
            self.slot, self.original, self.v, self.p = rec.slot, rec.original, rec.v, rec.p
            self.q = rec.q if rec.flags & F_READBACK else -1
            self.changes, self.restore_attempts, self.lease_end = rec.changes, rec.restore_attempts, rec.lease_end
        if rec.flags & F_FAULT:
            self.state = FAULT
            return
        if rec.flags & F_ACTIVE:
            if self.restore_attempts >= self.c.max_restore_attempts:
                self.state, self.last_reason = FAULT, R_RESTORE_FAILED
                return
            self.state, self.last_reason = RESTORING, R_BOOT_RECOVERY
            self.stall_mark_ms = now_ms & MASK32

    # ---- one tick ----------------------------------------------------------------------------------------
    def step(self, i: In) -> Out:
        o = Out()
        new = i.tel_ok and (not self.seen or i.sample_seq != self.last_seq)
        if i.tel_ok:
            self.seen, self.last_seq = True, i.sample_seq
        if not i.arm:
            self.arm_latch = False
        if self.night_unknown and i.night_id != 0:
            self.night_id, self.night_unknown = i.night_id, False
        st = self.state
        if st in (IDLE, ARMED, FAULT) and not self.night_unknown and i.night_id > self.night_id:
            self._roll_night(i.night_id)
        res = self._result(i, o)
        if st == FAULT:
            self._faulted(i, o, res)
            return o
        if st == IDLE:
            if i.start:
                o.event = self.last_reason = R_REFUSE_NOT_ARMED
            if i.arm and not self.arm_latch:
                self.state, self.armed_ms = ARMED, i.now_ms
                if o.event in (R_NONE, R_STALE_RESULT):
                    o.event = R_ARMED
            return o
        if st == ARMED:
            self._armed(i, o)
            return o
        if i.end:
            self.end_pending = True
        if not i.grid_ok:
            self.grid_pending = True
        if st == ADJUSTING:
            self._adjusting(i, o, res)
            return o
        if st in (LEASED, SETTLING):
            r = self._guard(i, new)
            if r == R_FOREIGN:
                self._fault(o, r)
                return o
            if r != R_NONE:
                self._begin_restore(i, o, r)
            elif st == SETTLING:
                self._settle(i, o, new)
            else:
                self._lease(i, o, new)
        if self.state == RESTORING:
            self._restoring(i, o, res)
        return o

    def _result(self, i: In, o: Out) -> int:
        """The result reported for the OUTSTANDING operation, else OP_NONE. A result for any other sequence or kind (a
        late result of an abandoned operation, a duplicate) is stale: ignored, never taken as this one's outcome. The
        late result of the operation this lease abandoned at its timeout still carries the register's newest value
        (operations run one at a time), so its readback is owned (never its outcome)."""
        if i.op == OP_NONE:
            return OP_NONE
        if self.op_pending and i.op_seq == self.op_seq and i.op_kind == self.op_kind:
            return i.op
        o.event = R_STALE_RESULT
        if self.late_seq != 0 and i.op_seq == self.late_seq and i.op_kind == self.late_kind:
            self.late_seq, self.late_kind = 0, A_NONE
            if i.op == OP_FAIL:
                self._own_readback(i, o)
        return OP_NONE

    def _roll_night(self, nid: int) -> None:
        """A new night: the closing night's writes join the 7-day window (hist[j] = night nid - 1 - j), every night
        without a record counts 0, the night's counters restart."""
        k = nid - self.night_id if self.night_id != 0 else 7
        new = [0] * 6
        for j in range(6):
            age = j + 1
            if age == k:
                new[j] = self.writes_night
            elif age > k:
                new[j] = self.hist[age - k - 1]
        self.hist = new
        self.night_id, self.night_used, self.writes_night, self.free_night = nid, False, 0, 0

    def _budget(self, n: int) -> int:
        """R_NONE when n more change writes fit every write ceiling with the restores and the owner's restore still
        reserved; else the refusal. A restore is never refused by these ceilings."""
        c = self.c
        reserve = c.max_restore_attempts + c.owner_restore_reserve
        if self.writes_night + n > c.night_write_ceiling - reserve:
            return R_REFUSE_WRITE_BUDGET
        if self.week_writes() + n > c.week_write_ceiling - reserve:
            return R_REFUSE_WEEK_BUDGET
        if self.life_writes + n > c.life_write_ceiling - reserve:
            return R_REFUSE_LIFE_BUDGET
        return R_NONE

    # ---- states ------------------------------------------------------------------------------------------
    def _armed(self, i: In, o: Out) -> None:
        c = self.c
        if not i.arm:
            self.state = IDLE
            o.event = R_DISARMED
            return
        if elapsed(i.now_ms, self.armed_ms) >= c.arm_window_ms:
            self.state, self.arm_latch = IDLE, True
            o.disarm, o.event = True, R_ARM_EXPIRED
            return
        if not i.start:
            return
        o.disarm = True
        self.arm_latch = True
        r = self._start_check(i)
        if r != R_NONE:
            self.state = IDLE
            o.event = self.last_reason = r
            return
        self._begin_lease(i, o)

    def _start_check(self, i: In) -> int:
        c, pl = self.c, i.plan
        if not config_ok(c):
            return R_REFUSE_CONFIG
        if i.night_id == 0 or i.epoch == 0 or i.local_min < 0 or i.night_id < self.night_id:
            return R_REFUSE_CLOCK
        if i.night_id != self.night_id:
            self._roll_night(i.night_id)
        if self.night_used:
            return R_REFUSE_NIGHT_USED
        if i.clock_change_night:
            return R_REFUSE_CLOCK_CHANGE
        if i.inv_skew_s < 0 or i.inv_skew_s > c.clock_skew_max_s:
            return R_REFUSE_INVERTER_CLOCK
        if i.rtc_busy:
            return R_REFUSE_RTC
        if i.other != 0 or i.mutex_busy:
            return R_REFUSE_OTHER
        if i.fault:
            return R_REFUSE_FAULT
        if not i.grid_ok:
            return R_REFUSE_GRID
        if not i.tel_ok or i.tel_age_ms > c.telemetry_stale_ms:
            return R_REFUSE_TELEMETRY
        if i.soc < 0 or i.soc > 1000:
            return R_REFUSE_SOC
        if not plan_ok(pl, c):
            return R_REFUSE_PLAN_INVALID
        if pl.age_ms > c.plan_max_age_ms:
            return R_REFUSE_PLAN_STALE
        if i.cfg_age_ms > c.config_stale_ms:
            return R_REFUSE_CONFIG_STALE
        if i.cfg_slot != pl.slot or not i.slot_grid or i.slot_target != pl.target or \
                not in_slot(i.local_min, i.slot_start_min, i.slot_end_min):
            return R_REFUSE_SLOT
        slot_end = slot_end_epoch(i.epoch, i.local_min, i.slot_end_min)
        if abs(pl.window_end - slot_end) > c.window_match_s:
            return R_REFUSE_SLOT
        lease_end = min(pl.deadline, slot_end - c.end_margin_s)
        if i.live_sp < c.floor_w + c.hyst_w or i.live_sp > c.fw_bound_w:
            return R_REFUSE_SLOT_POWER
        if i.soc >= pl.target * 10:
            return R_REFUSE_TARGET_MET
        if i.batt_w < c.charging_min_w:
            return R_REFUSE_NOT_CHARGING
        g = i.batt_w * 100 // i.live_sp
        if g < c.gain_min_pct or g > c.gain_max_pct:
            return R_REFUSE_IMPLAUSIBLE
        if lease_end - i.epoch < c.min_lease_s:
            return R_REFUSE_TOO_LATE
        if self._guard_trips(i.epoch, i.soc, pl.target, max(pl.capacity_wh, c.capacity_floor_wh), i.batt_w, slot_end,
                             pl.taper):
            return R_REFUSE_TARGET_AT_RISK
        return self._budget(1)

    def _begin_lease(self, i: In, o: Out) -> None:
        c, pl = self.c, i.plan
        self._clear_lease()
        self.slot, self.original = pl.slot, i.live_sp
        self.v = self.p = self.prev_v = i.live_sp
        self.target, self.taper = pl.target, pl.taper
        self.capacity_wh = max(pl.capacity_wh, c.capacity_floor_wh)
        self.lease_start_ms = self.last_change_ms = i.now_ms
        self.lease_end = min(pl.deadline, slot_end_epoch(i.epoch, i.local_min, i.slot_end_min) - c.end_margin_s)
        self.watchdog_ms = (self.lease_end - i.epoch) * 1000 + c.watchdog_extra_ms
        self.p0 = self.p_ref = i.batt_w
        self.gain_pct = i.batt_w * 100 // i.live_sp
        self.last_soc = self.soc_max = i.soc
        self.night_used = True
        self.state = LEASED
        o.event, o.commit = R_LEASE_STARTED, True
        d = self._desired(i)
        if abs(d - self.v) >= c.hyst_w:
            self._emit_write(i, o, d)

    def _adjusting(self, i: In, o: Out, res: int) -> None:
        c = self.c
        if res == OP_OK:
            self.op_pending = False
            self.last_dir = 1 if self.p > self.v else -1
            self.prev_v, self.v = self.v, self.p
            self.last_change_ms = i.now_ms
            self.judge_n = self.judge_sum = 0
            if self.grid_pending:
                self._begin_restore(i, o, R_GRID_LOSS)
                self._restoring(i, o, OP_NONE)
                return
            self.state = SETTLING
            o.event = R_WRITE_VERIFIED
            return
        if res == OP_FOREIGN:
            self.op_pending = False
            self._fault(o, R_FOREIGN)
            return
        if res == OP_FAIL and i.op_value >= 0 and i.op_value != self.v and i.op_value != self.p:
            self._set_q(i.op_value, o)
            self._begin_restore(i, o, R_READBACK_MISMATCH)
        elif res == OP_FAIL:
            self._begin_restore(i, o, R_WRITE_FAILED)
        elif res == OP_OK_NOWRITE:
            self._begin_restore(i, o, R_WRITE_FAILED)
        elif res == OP_NO_ANSWER:
            self._begin_restore(i, o, R_WRITE_UNANSWERED)
        elif res == OP_DEFERRED:
            self._begin_restore(i, o, R_WRITE_DEFERRED)
        elif elapsed(i.now_ms, self.op_start_ms) >= c.op_timeout_ms:
            self.late_seq, self.late_kind = self.op_seq, self.op_kind
            self._begin_restore(i, o, R_OP_TIMEOUT)
        else:
            return
        self._restoring(i, o, OP_NONE)

    def _guard(self, i: In, new: bool) -> int:
        c, pl = self.c, i.plan
        if self.grid_pending:
            return R_GRID_LOSS
        if self.end_pending:
            return R_END
        if i.epoch == 0 or i.local_min < 0:
            return R_CLOCK_INVALID
        if i.clock_change_night:
            return R_CLOCK_CHANGE
        if i.inv_skew_s < 0 or i.inv_skew_s > c.clock_skew_max_s:
            return R_INVERTER_CLOCK
        if i.epoch >= self.lease_end:
            return R_DEADLINE
        if elapsed(i.now_ms, self.lease_start_ms) >= self.watchdog_ms:
            return R_WATCHDOG
        if i.other != 0:
            return R_OTHER_ACTIVITY
        if i.fault:
            return R_INVERTER_FAULT
        if not i.tel_ok or i.tel_age_ms > c.telemetry_stale_ms:
            return R_TELEMETRY_STALE
        if i.soc < 0 or i.soc > 1000:
            return R_SOC_INVALID
        if new:
            if abs(i.soc - self.last_soc) > c.soc_jump_max or i.soc < self.soc_max - c.soc_drop_max:
                return R_SOC_INVALID
        if not plan_ok(pl, c):
            return R_PLAN_INVALID
        if pl.age_ms > c.plan_max_age_ms:
            return R_PLAN_LOST
        if pl.slot != self.slot or pl.target != self.target:
            return R_PLAN_INVALID
        if i.cfg_age_ms > c.config_stale_ms:
            return R_CONFIG_STALE
        if i.cfg_slot != self.slot or not i.slot_grid or i.slot_target != self.target or \
                not in_slot(i.local_min, i.slot_start_min, i.slot_end_min):
            return R_CONFIG_DRIFT
        slot_end = slot_end_epoch(i.epoch, i.local_min, i.slot_end_min)
        if abs(pl.window_end - slot_end) > c.window_match_s:
            return R_PLAN_WINDOW
        if elapsed(i.now_ms, self.last_change_ms) > i.cfg_age_ms:
            if i.live_sp != self.v and i.live_sp != self.p:
                return R_FOREIGN
        if i.soc >= self.target * 10:
            return R_TARGET_REACHED
        if self._guard_trips(i.epoch, i.soc, self.target, self.capacity_wh, self.p0, slot_end, self.taper):
            return R_TARGET_GUARD
        if new:
            s = i.batt_w
            self.runaway_n = self.runaway_n + 1 if s > self.p0 * c.runaway_pct // 100 + c.runaway_margin_w else 0
            if self.runaway_n >= c.runaway_samples:
                return R_RUNAWAY
            stopped = s < c.stop_w and i.soc < self.target * 10 - c.stop_soc_gap and i.soc < self.taper * 10
            self.stop_n = self.stop_n + 1 if stopped else 0
            if self.stop_n >= c.stop_samples:
                return R_CHARGE_STOPPED
            self.last_soc = i.soc
            self.soc_max = max(self.soc_max, i.soc)
        if i.rtc_busy:
            if not self.rtc_on:
                self.rtc_on, self.rtc_since_ms = True, i.now_ms
            elif elapsed(i.now_ms, self.rtc_since_ms) >= c.rtc_busy_max_ms:
                return R_RTC_STUCK
        else:
            self.rtc_on = False
        cand = min(pl.deadline, slot_end - c.end_margin_s)
        if cand < self.lease_end:
            self.lease_end = cand
        cap = max(pl.capacity_wh, c.capacity_floor_wh)
        if cap > self.capacity_wh:
            self.capacity_wh = cap
        return R_NONE

    def _guard_trips(self, epoch: int, soc: int, target: int, capacity_wh: int, p_top: int, window_end: int,
                     taper: int) -> bool:
        """True when finishing at the pre-lease rate would no longer leave the margin before the SLOT's own end: the
        lease must give the charge back to today's fixed rate now. Pessimistic: the plateau up to the taper knee (the
        plan's, at most taper_max_pct) at today's rate derated, everything above the knee at a small tail share of it
        (the real taper is NOT ESTABLISHED), the capacity at least the firmware floor."""
        c = self.c
        tgt = target * 10
        if tgt - soc <= 0:
            return False
        knee = min(tgt, min(taper, c.taper_max_pct) * 10)
        e_plat = max(0, knee - soc) * capacity_wh // 1000
        e_tail = (tgt - max(soc, knee)) * capacity_wh // 1000
        p_full = p_top * c.guard_derate_pct // 100
        p_tail = p_top * c.guard_tail_pct // 100
        if p_full <= 0 or p_tail <= 0:
            return True
        t_need = e_plat * 3600 // p_full + e_tail * 3600 // p_tail
        return epoch + t_need + c.guard_margin_s >= window_end - c.end_margin_s

    def _settle(self, i: In, o: Out, new: bool) -> None:
        c = self.c
        if elapsed(i.now_ms, self.last_change_ms) < c.settle_ms:
            return
        if new:
            self.judge_n += 1
            self.judge_sum += max(0, i.batt_w)
        if self.judge_n < c.judge_samples:
            return
        pa = self.judge_sum // self.judge_n
        dsp = self.v - self.prev_v
        exp_mag = self.gain_pct * abs(dsp) // 100
        act = pa - self.p_ref
        dirn = 1 if dsp > 0 else -1
        self.state = LEASED
        if dirn * act < 0 and abs(act) > c.wrong_dir_w:
            self._begin_restore(i, o, R_WRONG_DIRECTION)
            return
        if dirn * act * 100 >= c.response_min_pct * exp_mag:
            g = pa * 100 // self.v
            if g < c.gain_min_pct or g > c.gain_max_pct:
                self._begin_restore(i, o, R_IMPLAUSIBLE_GAIN)
                return
            self.ineffective = 0
            self.gain_pct = g
            o.event = R_RESPONSE_OK
        elif i.soc >= self.taper * 10:
            self.bms_limited = True
            o.event = R_BMS_LIMITED
        else:
            self.ineffective += 1
            if self.ineffective >= c.max_ineffective:
                self._begin_restore(i, o, R_NO_RESPONSE)
                return
            o.event = R_RESPONSE_WEAK
        self.p_ref = pa

    def _lease(self, i: In, o: Out, new: bool) -> None:
        c = self.c
        if new:
            self.p_ref = (3 * self.p_ref + max(0, i.batt_w)) // 4
        if self.bms_limited or self.changes >= c.max_changes:
            return
        if self._budget(1) != R_NONE:
            return
        if elapsed(i.now_ms, self.last_change_ms) < c.dwell_ms:
            return
        if i.rtc_busy or i.mutex_busy:
            return
        d = self._desired(i)
        delta = d - self.v
        if abs(delta) < c.hyst_w:
            return
        if self.last_dir != 0 and (1 if delta > 0 else -1) != self.last_dir and abs(delta) < c.hyst_w + c.reversal_extra_w:
            return
        self._emit_write(i, o, d)

    def _desired(self, i: In) -> int:
        """The next setpoint: a RELATIVE step from the present one, scaled by wanted over realised power (robust to
        the unknown setpoint unit), rounded to the grid, then held within one step of the present value by grid
        bounds (ceil(v - step), floor(v + step): never more than max_step_w even from a value off the grid), inside
        [floor, min(original, bound, owner)]. The hard ceiling min(original, bound) is rounded DOWN to the grid (a
        pre-lease value off the grid is only ever written back by the restore); the owner ceiling from the plan is
        approached by at most one step per change."""
        c = self.c
        if self.p_ref <= 0 or self.p_ref < c.charging_min_w // 2:
            return self.v
        raw = self.v * plan_power(i.plan, i.epoch) // self.p_ref
        r = (max(0, raw) + c.round_w // 2) // c.round_w * c.round_w
        lo = round_up(self.v - c.max_step_w, c.round_w)
        hi = (self.v + c.max_step_w) // c.round_w * c.round_w
        r = max(lo, min(hi, r))
        hard = min(self.original, c.fw_bound_w) // c.round_w * c.round_w
        ceiling = min(hard, max(i.plan.ceiling_w, lo))
        return max(c.floor_w, min(ceiling, r))

    def _emit(self, i: In, o: Out, kind: int, value: int) -> None:
        self.seq = (self.seq + 1) & MASK32
        if self.seq == 0:
            self.seq = 1
        self.op_pending, self.op_kind, self.op_seq, self.op_start_ms = True, kind, self.seq, i.now_ms
        o.action, o.value, o.seq, o.slot, o.commit = kind, value, self.seq, self.slot, True

    def _count_write(self) -> None:
        self.writes_night += 1
        self.life_writes = min(self.life_writes + 1, MASK32)

    def _give_back(self) -> None:
        """An operation that wrote nothing (NO_ANSWER, DEFERRED) returns its write to every count."""
        self.writes_night = max(0, self.writes_night - 1)
        self.life_writes = max(0, self.life_writes - 1)

    def _emit_write(self, i: In, o: Out, d: int) -> None:
        self.p = d
        self.changes += 1
        self._count_write()
        self._emit(i, o, A_WRITE, d)
        self.state = ADJUSTING
        if o.event == R_NONE:
            o.event = R_WRITE_REQUESTED

    def _begin_restore(self, i: In, o: Out, reason: int) -> None:
        self.state = RESTORING
        self.last_reason = reason
        self.op_pending = False
        self.restore_hold = False
        self.stall_ms, self.stall_mark_ms = 0, i.now_ms
        if o.event in (R_NONE, R_STALE_RESULT):
            o.event = reason

    def _set_q(self, value: int, o: Out) -> None:
        """A new owned readback is committed at once, whatever else the tick does (an emitted restore, a busy bus)."""
        if value != self.q:
            self.q = value
            o.commit = True

    def _own_readback(self, i: In, o: Out) -> None:
        """A readback taken under the GRC's own lock right after its own write is a value the lease caused: owned.
        A readback that went unanswered (-1) never erases it."""
        if i.op_value >= 0 and i.op_value != self.original and i.op_value != self.v and i.op_value != self.p:
            self._set_q(i.op_value, o)

    def _hold(self, i: In) -> None:
        self.restore_hold, self.restore_from_ms = True, i.now_ms

    def _stall_tick(self, i: In) -> None:
        """The restore-owed time while the inverter answers: each tick adds the time since the previous one (at most
        rx_fresh_ms), only when the inverter answered within rx_fresh_ms. A silent inverter adds nothing."""
        c = self.c
        d = elapsed(i.now_ms, self.stall_mark_ms)
        self.stall_mark_ms = i.now_ms
        if i.rx_age_ms <= c.rx_fresh_ms:
            self.stall_ms = min(c.restore_stall_ms, self.stall_ms + min(d, c.rx_fresh_ms))

    def _restoring(self, i: In, o: Out, res: int) -> None:
        c = self.c
        self._stall_tick(i)
        if self.op_pending:
            if res in (OP_OK, OP_OK_NOWRITE):
                self.op_pending = False
                self._clear_lease()
                self.state = IDLE
                o.event, o.commit = R_RESTORED, True
            elif res == OP_FOREIGN:
                self.op_pending = False
                self._fault(o, R_FOREIGN)
            elif res in (OP_NO_ANSWER, OP_DEFERRED):
                # nothing was written: the attempt and the write are given back; the restore stays owed (a free
                # retry, at most restore_free_max a night)
                self.op_pending = False
                self.restore_attempts = max(0, self.restore_attempts - 1)
                self._give_back()
                self.free_night += 1
                o.event = R_RESTORE_UNANSWERED if res == OP_NO_ANSWER else R_RESTORE_DEFERRED
                o.commit = True
                if self.free_night >= c.restore_free_max:
                    self._fault(o, R_RESTORE_STALLED)
                else:
                    self._hold(i)
            elif res == OP_FAIL or elapsed(i.now_ms, self.op_start_ms) >= c.op_timeout_ms:
                self.op_pending = False
                if res == OP_FAIL:
                    self._own_readback(i, o)
                else:
                    self.late_seq, self.late_kind = self.op_seq, self.op_kind
                if self.restore_attempts >= c.max_restore_attempts:
                    self._fault(o, R_RESTORE_FAILED)
                else:
                    self._hold(i)
                    o.event = R_RESTORE_RETRY
            return
        if self.restore_hold and elapsed(i.now_ms, self.restore_from_ms) >= c.restore_backoff_ms:
            self.restore_hold = False
        if self.stall_ms >= c.restore_stall_ms:
            self._fault(o, R_RESTORE_STALLED)
            return
        if self.restore_hold or i.rtc_busy or i.mutex_busy:
            return
        if i.rx_age_ms > c.rx_fresh_ms:
            return
        if self.writes_night + 1 > c.night_write_ceiling - c.owner_restore_reserve:
            self._fault(o, R_NIGHT_CEILING)
            return
        self.restore_attempts += 1
        self._count_write()
        self._emit(i, o, A_RESTORE, self.original)
        if o.event in (R_NONE, R_STALE_RESULT):
            o.event = R_RESTORE_REQUESTED

    def _faulted(self, i: In, o: Out, res: int) -> None:
        """FAULT writes nothing on its own. The owner may accept the current state (ACK, with a fresh configuration
        read; the night's counts are kept) or ask for one classified restore of the original (Restore original),
        which the night's write ceiling bounds (one write is always reserved for it) and whose failure leaves the
        FAULT latched."""
        c = self.c
        if self.op_pending:
            if res in (OP_OK, OP_OK_NOWRITE):
                self.op_pending = False
                self._clear_lease()
                self.state, self.last_reason = IDLE, R_OWNER_RESTORE
                o.event, o.commit = R_RESTORED, True
            elif res == OP_FOREIGN:
                self.op_pending = False
                self.last_reason = R_FOREIGN
                o.event, o.commit = R_FOREIGN, True
            elif res in (OP_NO_ANSWER, OP_DEFERRED):
                self.op_pending = False
                if self.free_night < c.restore_free_max:
                    self._give_back()
                    self.free_night += 1
                o.event = R_RESTORE_UNANSWERED if res == OP_NO_ANSWER else R_RESTORE_DEFERRED
                o.commit = True
            elif res == OP_FAIL or elapsed(i.now_ms, self.op_start_ms) >= c.op_timeout_ms:
                self.op_pending = False
                if res == OP_FAIL:
                    self._own_readback(i, o)
                else:
                    self.late_seq, self.late_kind = self.op_seq, self.op_kind
                self.last_reason = R_RESTORE_FAILED
                o.event, o.commit = R_RESTORE_FAILED, True
            return
        if i.ack and i.cfg_age_ms <= c.config_stale_ms:
            self._clear_lease()
            self.state, self.last_reason = IDLE, R_ACKED
            o.event, o.commit = R_ACKED, True
            return
        if i.restore_req:
            busy = i.rtc_busy or i.mutex_busy or i.rx_age_ms > c.rx_fresh_ms
            if self.original == 0 or busy or self.writes_night + 1 > c.night_write_ceiling:
                o.event = R_REFUSE_RESTORE
                return
            self._count_write()
            self._emit(i, o, A_RESTORE, self.original)
            o.event = R_OWNER_RESTORE

    def _fault(self, o: Out, reason: int) -> None:
        self.state = FAULT
        self.last_reason = reason
        self.op_pending = False
        o.event, o.commit = reason, True


def trace_line(core: Core, o: Out) -> str:
    """The canonical per-tick text both the model and the header harness print."""
    return " ".join(str(x) for x in (
        core.state, o.action, o.value, o.seq, o.slot, int(o.disarm), int(o.commit), o.event, core.v, core.p, core.q,
        core.changes, core.writes_night, core.restore_attempts, core.gain_pct, core.p_ref, core.last_reason,
        int(core.bms_limited), core.ineffective, core.lease_end, core.free_night, core.week_writes(), core.life_writes,
        core.stall_ms, int(core.restore_hold), int(core.night_unknown), core.night_id))
