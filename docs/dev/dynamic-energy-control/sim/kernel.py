"""Shared dynamic-energy-control KERNEL: the reference model (L3 of the architecture reconciliation, item N4).

REFERENCE MODEL AND TEST BENCH. NOT PRODUCTION CODE. This file is not wired to Home Assistant, the dongle, the inverter or any
register; it imports nothing outside the standard library; every function is pure (values in, a value out, no clock, no file, no
network, no global state) and it writes nothing. A live controller that wants these rules must be re-implemented and independently
proven; nothing here authorises any live write (owner messages A, B and C of 25 Nov 2026 still apply).

What it is: ONE kernel that three thin policies share (Charge Fixed, Gentle, Export). The kernel owns telemetry freshness, progress
and feasibility ('unreachable' said early and honestly), the wanted-power decision with ONE reason code from a closed list, ramp
limiting and hysteresis inside the REAL budgets, the guard order and a plain-language explanation for every decision.

Where the numbers come from (test_sim.py parses the sources and fails on drift; see SIM_README.md, section "What is pinned"):
  * export budgets and guards : firmware/ecco_clock_dongle_stage3_4_free_power.yaml (substitutions, dump_controller_tick)
  * Gentle feasibility maths  : frontend/ecco-plan-core/src/gentleNight.ts (the pessimistic world, ported; golden vectors pinned)
  * charge actuator budgets   : the guarded charge-rate controller design (GRC SPEC revision 3, section 5; branch
                                dev/gentle-rate-controller, not in this tree, so pinned by value and by the planner's matching
                                defaults: 30 min dwell, at most 6 changes)
Everything else is a named ASSUMPTION (marked ASSUMED below) and is listed in SIM_README.md.

Units: seconds, watts, kWh, percent. Battery power in a Frame follows the firmware (register 190): positive = discharge. Grid follows
the CT (register 172): positive = import. Inverter AC power: positive = output, negative = input (charging).
"""

import math
from dataclasses import dataclass, replace
from typing import Optional

INF = math.inf
EPS = 1e-9

# ---------------------------------------------------------------------------------------------------------------------------
# 1. The closed lists: reasons, details, guard order
# ---------------------------------------------------------------------------------------------------------------------------
REASONS = ("increase", "reduce", "hold", "stop", "unreachable", "blocked")

# every (reason, detail) pair a decision may carry; EXPLAIN below must cover all of them (test_sim.py checks)
DETAILS = {
    "increase": ("start", "behind_plan", "feed_forward", "export_short"),
    "reduce": ("ahead_of_plan", "import_ceiling", "import_headroom", "power_ceiling", "export_over"),
    "hold": ("on_plan", "dwell", "budget", "deadband", "reversal", "settling", "past_knee", "fixed_rate", "tracking",
             "stale_short", "saturated_low", "saturated_high", "no_change_needed", "no_response"),
    "stop": ("target_reached", "grid_lost", "owner_end", "floor_reached", "reserve_rose", "stale_telemetry", "time_untrusted",
             "window_end", "deadline", "import_ceiling", "runaway", "write_budget", "response_failed", "target_guard",
             "plan_lost", "lease_end", "export_over_limit", "restart"),
    "unreachable": ("at_risk", "deadline", "import_headroom", "infeasible_high", "infeasible_low"),
    "blocked": ("stale_telemetry", "time_untrusted", "no_charge_running", "implausible_gain", "no_response", "grid_lost",
                "owner_hold", "authority_busy", "dongle_unavailable", "no_headroom"),
}

# REQ-B21: the guard order, common to every mode (ACTUATOR_PATHS.md section 4 point 4; the time guards follow GRC SPEC section 9).
# The first guard that fires decides; optimisation comes only after every guard has passed.
GUARD_ORDER = ("grid_lost", "owner_end", "time_untrusted", "stale", "floor", "ceiling", "runaway", "budget", "deadline",
               "target_guard")


def first_guard(flags):
    """The first guard of GUARD_ORDER whose flag is true, or None. An unknown name in `flags` is an error: a typo must not pass."""
    for name in flags:
        if name not in GUARD_ORDER:
            raise ValueError("unknown guard " + str(name))
    for name in GUARD_ORDER:
        if flags.get(name):
            return name
    return None


# ---------------------------------------------------------------------------------------------------------------------------
# 2. Constants. PINNED = a source file states it and test_sim.py compares; ASSUMED = no source, listed in the README.
# ---------------------------------------------------------------------------------------------------------------------------
# --- export: the Dump to Grid closed loop (firmware substitutions), the model of dump_controller_tick -------------- PINNED
GUARD_TICK_S = 15                 # the 15 s watchdog interval that runs dump_controller_tick
EXPORT_TRIP_TICK_S = 1            # the 1 s export-trip interval: acts on a far-over sample at once
EXPORT_SETTLE_S = 45              # ecco_dump_controller_settle_ms 45000: also the minimum interval between controller writes
EXPORT_DEADBAND_W = 150           # ecco_dump_controller_deadband_w
EXPORT_GAIN = 0.5                 # ecco_dump_controller_gain
EXPORT_MAX_STEP_W = 1000          # ecco_dump_controller_max_step_w
EXPORT_ROUND_W = 100              # ecco_dump_controller_round_w
EXPORT_MIN_CEILING_W = 500        # ecco_dump_controller_min_ceiling_w (nothing lower was ever live-characterised)
EXPORT_MAX_WRITES = 120           # ecco_dump_controller_max_writes_per_lease
EXPORT_FF_MAX_START_W = 2000      # ecco_dump_feedforward_max_start_ceiling_w
EXPORT_RESPONSE_SAMPLES = 3       # ecco_dump_controller_response_samples
EXPORT_RESPONSE_MARGIN_W = 100    # ecco_dump_controller_response_margin_w
EXPORT_WRONG_DIRECTION_W = 300    # ecco_dump_controller_wrong_direction_margin_w
EXPORT_RECOVERY_HOLD_S = 60       # ecco_dump_controller_recovery_hold_ms 60000
EXPORT_RECOVERY_ATTEMPTS = 1      # ecco_dump_controller_recovery_max_attempts
EXPORT_FEASIBILITY_CONFIRM = 2    # ecco_dump_feasibility_confirm_samples: an infeasible target is shown only after this many ticks in a row
GRID_STALE_S = 90                 # ecco_dump_grid_stale_ms: a fresh CT is needed, else the lease ends (fail closed)
SOC_STALE_S = 90                  # ecco_dump_soc_stale_ms: a fresh SOC is needed, else the lease ends (fail closed)
RUNAWAY_MARGIN_W = 750            # ecco_dump_runaway_margin_w
RUNAWAY_SAMPLES = 3               # ecco_dump_runaway_samples
RUNAWAY_GRACE_S = 30              # ecco_dump_runaway_grace_ms 30000: settling after a start or a write
RUNAWAY_ABS_MARGIN_W = 750        # ecco_dump_runaway_absolute_margin_w: the absolute backstop, never reset by a controller write
RUNAWAY_ABS_SAMPLES = 2           # ecco_dump_runaway_absolute_samples
RUNAWAY_BACKSTOP_FLOOR_W = 3000   # ecco_dump_runaway_backstop_floor_w: the backstop follows the command only above this
EXPORT_FAR_MIN_W = 500            # ecco_dump_export_far_min_w: one sample this far (or 25 %) over Max Grid Export ends the lease
EXPORT_MARGIN_MIN_W = 100         # ecco_dump_export_margin_min_w: two samples over limit + max(this, 3 %) end it
REBOOT_TIMEOUT_S = 900            # ecco_failback_shadow_assumed_reboot_timeout_ms 900000: no API client for this long = restart
# --- charge: the Gentle planner defaults (gentleNight.ts DEFAULT_NIGHT_PARAMS) and the GRC budgets ------------------- PINNED
CHARGE_STEP_W = 100               # planner stepW
CHARGE_MIN_W = 500                # planner minW = LIMITS.chargePowerMin
CHARGE_MAX_W = 8000               # LIMITS.chargePowerMax (a compile-time setpoint bound: NOT a rating, NOT a grid limit)
BUFFER_S = 3600                   # the finish-early buffer: planner default 60 min
CHARGE_DWELL_S = 1800             # planner dwellMin 30 = GRC dwell_ms: at least 30 min between ordinary changes
CHARGE_MAX_CHANGES = 6            # planner maxChanges = GRC max_changes
PLANNER_HYSTERESIS_W = 500        # planner hysteresisW: a decrease is planned only when it saves at least this much
PLANNER_SLACK_S = 900             # planner decreaseSlackMin 15: a decrease keeps this much slack to the deadline
EFF_PESSIMISTIC = 0.90            # planner chargeEffMin
CAPACITY_BAND_PCT = 6.0           # planner capacityBandPct
SOC_SCALE_ERR_PCT = 3.0           # planner socScaleErrPct
SOC_RESOLUTION_PCT = 1.0          # planner socResolutionPct
SOC_NOISE_PCT = 0.5               # planner socNoisePct
KNEE_PESSIMISTIC_PCT = 90.0       # planner kneeSocPct (the true knee measured at the top rate is 98: this is conservative)
TAIL_FRACTION = 0.125             # planner tailFraction
DROP_MIN = 5.0                    # planner dropMin (the pessimistic world falls in min(1, this) minutes)
DEMAND_MARGIN_PCT = 20.0          # planner demandMarginPct
CHARGE_NIGHT_WRITES = 10          # GRC night_write_ceiling: every write counts, restores included     (GRC SPEC section 5)
CHARGE_RESTORE_RESERVE = 4        # GRC: 3 lease restores + 1 owner restore are always reserved out of that ceiling
CHARGE_MAX_STEP_W = 2000          # GRC max_step_w: no single change moves the setpoint by more
CHARGE_HYST_W = 300               # GRC hyst_w: no change under this
CHARGE_REVERSAL_EXTRA_W = 300     # GRC reversal_extra_w: against the previous direction the change must be this much more
GRC_SETTLE_S = 45                 # GRC settle_ms
GRC_GAIN_MIN = 0.5                # GRC gain_min_pct 50 / gain_max_pct 150: measured realised / setpoint vs the assumed unit
GRC_GAIN_MAX = 1.5
GRC_RESPONSE_MIN = 0.3            # GRC response_min_pct 30: a change must show at least 30 % of the expected power change
GRC_MAX_INEFFECTIVE = 2           # GRC max_ineffective: the second weak response ends the lease
GRC_CHARGING_MIN_W = 1000         # GRC charging_min_w: START needs a running charge of at least this
PLAN_MAX_AGE_S = 1200             # GRC plan_max_age_ms 20 min: no plan hand-over for this long = plan lost, restore
END_MARGIN_S = 600                # GRC end_margin_s: a lease ends this long before the inverter's own slot end
GUARD_MARGIN_S = 900              # GRC guard_margin_s: the target guard's slack to the slot end
CLOCK_SKEW_MAX_S = 120            # GRC clock_skew_max_s: the inverter clock may be off by at most this
CHARGE_RUNAWAY_PCT = 15.0         # GRC runaway_pct 115 (expected * 1.15 + 500 W for 3 frames)
CHARGE_RUNAWAY_MARGIN_W = 500     # GRC runaway_margin_w
# --- ASSUMED (no source file; each is listed in SIM_README.md)
TELEMETRY_STALE_S = 90            # ASSUMED to equal GRID_STALE_S / SOC_STALE_S: one control bound for every input
STALE_HOLD_S = 45                 # ASSUMED: a frame older than this (but not stale) never drives an increase
IMPORT_MARGIN_PCT = 5.0           # ASSUMED: the planning headroom keeps this share of the import ceiling free
HOUSE_PEAK_WINDOW_S = 1800        # ASSUMED: the planning house peak is the largest 5 min mean of the last 30 min (one dwell)
HOUSE_MEAN_S = 300                # ASSUMED: the averaging span of that peak
NTP_AGE_MAX_S = 3600              # ASSUMED (N1 needs one firmware field): the dongle's NTP sync is trusted this long
STALL_READS_MAX = 4               # N1: the inverter clock stall flag counts only when it persists for this many reads
DEFAULT_REACT_S = 120             # ASSUMED: the declared reaction bound (tick + command + settle) used for floor margins
EFF_WINDOW_S = 1800               # ASSUMED: progress is judged over at least this long ...
EFF_MIN_POINTS = 8.0              # ASSUMED: ... and at least this many SOC points (a 1 point reading error is then at most 12 %)
EFF_FLAG_BELOW = 0.93             # ASSUMED: a progress more than 7 % worse than the pessimistic world is flagged 'behind the forecast'
EFF_SCALE_MIN = 0.6               # ASSUMED: the pessimistic efficiency is never scaled below this share
EXPORT_DISCHARGE_EFF = 0.90       # ASSUMED (pessimistic): AC delivered per DC drawn when sizing an export lease


# ---------------------------------------------------------------------------------------------------------------------------
# 3. Types
# ---------------------------------------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class Frame:
    """One telemetry reading as the kernel sees it. None = unavailable, and unavailable counts as stale."""
    soc_pct: Optional[float] = None
    age_s: float = INF
    batt_w: Optional[float] = None      # DC, positive = discharge (register 190)
    grid_w: Optional[float] = None      # positive = import (CT, register 172)
    pv_w: Optional[float] = None        # >= 0
    inv_ac_w: Optional[float] = None    # positive = output, negative = input (charging)


@dataclass(frozen=True)
class Inputs:
    now_s: float
    frame: Frame
    grid_ok: bool = True                # the inverter reports the grid connected
    time_ok: bool = True                # the clock this decision depends on is trusted (see time_trusted)
    hold: bool = False                  # the owner pressed Hold / End, or manual mode
    reserve_pct: float = 20.0           # the effective reserve (plan level)
    in_force_w: Optional[float] = None  # readback of the setpoint in force (None: not read)
    dongle_ok: bool = True              # the dongle answers (false: nothing it publishes can be trusted)


@dataclass(frozen=True)
class Limits:
    power_ceiling_w: float = 8000.0     # setpoint bound: the compile-time bound lowered by the owner's operating limit
    import_ceiling_w: Optional[float] = None   # the owner's grid import limit; None = none applied, and the plan says so
    max_export_w: Optional[float] = None       # Max Grid Export (dongle enforced)


@dataclass(frozen=True)
class ChargeObjective:
    target_soc_pct: float
    deadline_s: float                   # window end minus the finish-early buffer (dongle clock)
    window_end_s: float                 # the charge slot's own end (dongle clock)
    capacity_kwh: float                 # the trusted usable capacity (the pessimistic band is added by the kernel)


@dataclass(frozen=True)
class ExportObjective:
    target_export_w: float              # net grid export wanted
    stop_soc_pct: float                 # the owner's Stop SOC request (raise-only during a lease)
    end_s: float                        # planned lease end
    capacity_kwh: float
    lease_ceiling_w: float = 3000.0     # the latched Power Ceiling of the lease


@dataclass(frozen=True)
class State:
    """What the kernel remembers between calls. The bench updates it only through observe / note_start / note_write / note_export_write."""
    phase: str = "idle"                 # idle | active | ended
    v_w: Optional[float] = None         # the setpoint last verified in force
    original_w: Optional[float] = None  # the pre-session value (restored at the end, never exceeded)
    last_write_s: Optional[float] = None
    changes: int = 0                    # ordinary changes (not the start, not a forced reduction, not a restore)
    writes: int = 0                     # every write: start, changes, forced reductions, restores
    last_dir: int = 0
    gain: Optional[float] = None        # measured realised AC watts per setpoint watt (charge)
    gain0: float = 1.0                  # the unit the plan assumes (the planner treats a setpoint as grid-side watts)
    weak: int = 0                       # weak responses judged
    pending_judge: bool = False         # a verified change awaits its response judgement
    pre_ac_w: Optional[float] = None    # realised AC input just before the last change
    pre_v_w: Optional[float] = None     # the setpoint before the last change
    over_samples: int = 0               # consecutive samples over the runaway limit
    abs_over: int = 0                   # consecutive samples over the absolute backstop (export; a write never resets it)
    house_hist: tuple = ()              # ((t, house_w), ...) the last half hour
    eff_scale: float = 1.0              # planner memory: observed progress against the pessimistic world (only ever lowered)
    acc_t0: Optional[float] = None      # planner memory: start of the current progress window
    acc_soc0: float = 0.0
    acc_wh: float = 0.0                 # AC energy drawn in the window
    acc_last_t: Optional[float] = None
    acc_last_ac: float = 0.0
    # export loop (the model of dump_controller_tick)
    stop_soc_pct: Optional[float] = None
    last_update_s: Optional[float] = None
    pending_err_w: Optional[float] = None
    response_pending: bool = False
    ineffective: int = 0
    wrong_dir: int = 0
    no_resp_since_s: Optional[float] = None
    recoveries: int = 0
    low_streak: int = 0
    high_streak: int = 0
    export_over: bool = False


@dataclass(frozen=True)
class Decision:
    reason: str                         # one of REASONS
    detail: str                         # one of DETAILS[reason]
    wanted_w: Optional[float]           # the setpoint the policy wants in force (None: none, e.g. after a stop)
    write_w: Optional[float]            # the write to perform now (None: no write)
    explanation: str                    # plain language, never empty
    end: bool = False                   # True: end the session now (restore the pre-session values)
    unreachable: bool = False           # the objective cannot be met (reported alongside the reason)
    stop_soc_pct: Optional[float] = None  # export: the Stop SOC to stage (start) or to raise to (running); raise-only
    numbers: tuple = ()                 # ((name, value), ...) the numbers the explanation used


# ---------------------------------------------------------------------------------------------------------------------------
# 4. Explanations: one plain sentence per (reason, detail); every pair of DETAILS must appear here
# ---------------------------------------------------------------------------------------------------------------------------
EXPLAIN = {
    ("increase", "start"): "Starting at {want_w} W: the lowest rate that still reaches {target}% by the deadline in the pessimistic projection.",
    ("increase", "behind_plan"): "Raised the setpoint from {v_w} W to {want_w} W: at {v_w} W the pessimistic projection misses the deadline by at least {late_min} min; {want_w} W is the lowest step that recovers it.",
    ("increase", "feed_forward"): "Starting the export at {want_w} W: house {house_w} W plus the {target_w} W export target minus {pv_w} W of measured solar.",
    ("increase", "export_short"): "Raised the battery ceiling from {v_w} W to {want_w} W: the net export of {export_w} W is below the {target_w} W target.",
    ("reduce", "export_over"): "Lowered the battery ceiling from {v_w} W to {want_w} W: the net export of {export_w} W is above the {target_w} W target.",
    ("hold", "no_response"): "Holding {v_w} W: the last ceiling changes did not move the export; waiting before one bounded retry.",
    ("reduce", "ahead_of_plan"): "Reduced the setpoint from {v_w} W to {want_w} W: the battery is ahead of the pessimistic plan and {want_w} W still makes the deadline with the slack kept.",
    ("reduce", "import_ceiling"): "Reduced the setpoint from {v_w} W to {want_w} W at once: grid import {import_w} W is above the owner's import ceiling of {ceiling_w} W (a safety action, ahead of the deadline).",
    ("reduce", "import_headroom"): "Reduced the setpoint from {v_w} W to {want_w} W: with the house load planned at {house_w} W the import ceiling of {ceiling_w} W leaves only {headroom_w} W for the charge.",
    ("reduce", "power_ceiling"): "Reduced the setpoint from {v_w} W to {want_w} W: it was above the power ceiling of {ceiling_w} W.",
    ("hold", "on_plan"): "Holding {v_w} W: the plan still makes the deadline with {margin_min} min to spare and a lower rate would not save enough to change.",
    ("hold", "dwell"): "Holding {v_w} W: a change is wanted but the last one was {since_min} min ago and the minimum between changes is {dwell_min} min.",
    ("hold", "budget"): "Holding {v_w} W: the change or write budget of this session is used up ({writes} writes, {changes} changes).",
    ("hold", "deadband"): "Holding {v_w} W: the wanted {want_w} W is inside the {band_w} W deadband, so a write would only chase noise.",
    ("hold", "reversal"): "Holding {v_w} W: the wanted {want_w} W is against the last direction and smaller than the {need_w} W a reversal needs.",
    ("hold", "settling"): "Holding {v_w} W: the last write was {since_s} s ago and the plant needs {settle_s} s to settle before it is judged again.",
    ("hold", "past_knee"): "Holding {v_w} W: the battery is at or near the point where the BMS sets the power; a change here could only slow the charge.",
    ("hold", "fixed_rate"): "Holding {v_w} W: this session runs at one fixed rate and can only be ended, not changed.",
    ("hold", "tracking"): "Holding {v_w} W: the net export is {export_w} W against the {target_w} W target, inside the {band_w} W deadband.",
    ("hold", "stale_short"): "Holding {v_w} W: the latest reading is {age_s} s old; a reading that old never drives an increase.",
    ("hold", "saturated_low"): "Holding {v_w} W at the {floor_w} W floor: solar alone already exports more than the {target_w} W target; the battery is never charged to absorb it.",
    ("hold", "saturated_high"): "Holding {v_w} W at the ceiling: the export target needs more than the {ceiling_w} W the ceiling allows.",
    ("hold", "no_change_needed"): "Holding {v_w} W: the wanted value rounds to the one in force.",
    ("stop", "target_reached"): "Stopping: the battery is at {soc}%, the target is {target}%.",
    ("stop", "grid_lost"): "Stopping at once: the grid is lost; the pre-session setpoint is restored first because a lowered slot power may cap the battery's supply to the house.",
    ("stop", "owner_end"): "Stopping: the owner pressed Hold or End (manual mode); the pre-session values are restored.",
    ("stop", "floor_reached"): "Stopping: the battery is at {soc}%, at or below the {floor}% floor (the larger of the Stop SOC and the effective reserve, plus the reaction margin).",
    ("stop", "reserve_rose"): "Stopping: the effective reserve rose to {reserve}% and the battery at {soc}% is at or below the new floor of {floor}%.",
    ("stop", "stale_telemetry"): "Stopping: the telemetry is {age_s} s old, beyond the {limit_s} s bound; with no fresh reading nothing is safe to steer.",
    ("stop", "time_untrusted"): "Stopping: the clock this plan depends on is not trusted (inverter clock skew or no recent NTP sync); the pre-session values are restored.",
    ("stop", "window_end"): "Not starting: the window ends in {left_min} min, inside the {margin_min} min margin kept before the inverter's own slot end.",
    ("stop", "deadline"): "Stopping: the lease deadline has passed; the pre-session rate takes over.",
    ("stop", "import_ceiling"): "Stopping: grid import {import_w} W is above the import ceiling of {ceiling_w} W and no lower setpoint is allowed.",
    ("stop", "runaway"): "Stopping: the measured power {measured_w} W is far above what the setpoint should give ({expected_w} W) for {samples} samples.",
    ("stop", "write_budget"): "Stopping: the write budget of this session is used up; the session ends through the restore.",
    ("stop", "response_failed"): "Stopping: the plant did not respond to the setpoint as a setpoint should; control is not safe.",
    ("stop", "target_guard"): "Stopping: finishing at the pre-session rate would no longer leave the safety margin before the slot end, so the charge is handed back to it; the target is at risk and is reported, not lowered.",
    ("stop", "plan_lost"): "Stopping: no plan hand-over for {age_s} s (limit {limit_s} s); the pre-session values are restored.",
    ("stop", "lease_end"): "Stopping: the planned end of the session has come.",
    ("stop", "export_over_limit"): "Stopping: net export {export_w} W is above the Max Grid Export limit of {limit_w} W.",
    ("stop", "restart"): "Stopping: the dongle restarted; any open session is ended and the pre-session values restored, never resumed.",
    ("unreachable", "at_risk"): "Target at risk: the pessimistic projection at the rate in force misses the deadline by at least {late_min} min; the highest allowed rate still has a chance. The target is not lowered.",
    ("unreachable", "deadline"): "Target unreachable: even the highest allowed rate ({ceiling_w} W) does not reach {target}% by the deadline in the pessimistic projection. Best effort continues; the target is not lowered.",
    ("unreachable", "import_headroom"): "Target unreachable: the grid import ceiling leaves only {ceiling_w} W of charge power, not enough for {target}% by the deadline. The target is not lowered.",
    ("unreachable", "infeasible_high"): "Export target infeasible: house {house_w} W plus {target_w} W of export minus {pv_w} W of solar needs {required_w} W, above the {ceiling_w} W ceiling.",
    ("unreachable", "infeasible_low"): "Export target infeasible: solar alone ({pv_w} W) already exports more than the {target_w} W target by {excess_w} W; the battery is not charged to absorb it.",
    ("blocked", "stale_telemetry"): "Blocked: the telemetry is unavailable or {age_s} s old (limit {limit_s} s); nothing is started or raised on stale data.",
    ("blocked", "time_untrusted"): "Blocked: the clock this plan depends on is not trusted; nothing time-dependent is started or raised.",
    ("blocked", "no_charge_running"): "Blocked: no charge of at least {min_w} W is running, so the setpoint's effect cannot be measured; nothing is started.",
    ("blocked", "implausible_gain"): "Blocked: the measured power is {gain} times the setpoint, outside {gain_min} to {gain_max} times the assumed unit; the setpoint does not mean what was assumed.",
    ("blocked", "no_response"): "Blocked: the plant did not follow the last setpoint changes; the setpoint is not controlling the power.",
    ("blocked", "grid_lost"): "Blocked: the grid is not connected; nothing is started.",
    ("blocked", "owner_hold"): "Blocked: the owner's Hold or manual mode is on; nothing is started.",
    ("blocked", "authority_busy"): "Blocked: another controller already owns the setpoint ({owner}); one writer per setting.",
    ("blocked", "dongle_unavailable"): "Blocked: the dongle is not answering; no firmware guard can run, so nothing is started and the owner is alerted.",
    ("blocked", "no_headroom"): "Blocked: nothing can be started now (no headroom, or the session window has passed).",
}


def _fmt(x):
    if x is None:
        return "n/a"
    if isinstance(x, float):
        if math.isinf(x) or math.isnan(x):
            return "n/a"
        if abs(x) >= 100 or abs(x - round(x)) < 0.05:
            return str(int(round(x)))
        return "%.1f" % x
    return str(x)


class _Safe(dict):
    def __missing__(self, key):
        return "?"


def explain(reason, detail, numbers):
    """The plain-language sentence for (reason, detail) with the numbers filled in; never empty, never raises."""
    template = EXPLAIN.get((reason, detail))
    if template is None:
        return "No explanation is defined for " + str(reason) + "/" + str(detail) + "."
    return template.format_map(_Safe({k: _fmt(v) for k, v in numbers}))


def make(reason, detail, wanted_w=None, write_w=None, end=False, unreachable=False, stop_soc_pct=None, **numbers):
    """Build a Decision; the explanation is generated here, so no decision exists without one."""
    pairs = tuple(sorted(numbers.items()))
    return Decision(reason=reason, detail=detail, wanted_w=wanted_w, write_w=write_w, explanation=explain(reason, detail, pairs),
                    end=end, unreachable=unreachable, stop_soc_pct=stop_soc_pct, numbers=pairs)


# ---------------------------------------------------------------------------------------------------------------------------
# 5. Freshness and trust
# ---------------------------------------------------------------------------------------------------------------------------
def is_fresh(value, age_s, max_age_s):
    """A reading is usable only when it exists, is a finite number and is not older than the bound. Unavailable = stale."""
    if value is None:
        return False
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return False
    if age_s is None or math.isnan(age_s):
        return False
    return age_s <= max_age_s


def frame_fresh(frame, need, max_age_s=TELEMETRY_STALE_S):
    """True when every named input of the frame is fresh. Names: soc, grid, pv, ac, batt."""
    fields = {"soc": frame.soc_pct, "grid": frame.grid_w, "pv": frame.pv_w, "ac": frame.inv_ac_w, "batt": frame.batt_w}
    for name in need:
        if not is_fresh(fields[name], frame.age_s, max_age_s):
            return False
    return True


def house_w(frame):
    """House load derived from the grid CT and the inverter AC power, never from the native load register (REQ-D6)."""
    if frame.inv_ac_w is None or frame.grid_w is None:
        return None
    return max(0.0, frame.inv_ac_w + frame.grid_w)


def time_trusted(inverter_skew_s, ntp_age_s, stall_reads):
    """N1 in one place: the inverter clock may be off by at most CLOCK_SKEW_MAX_S, the dongle's NTP sync must be recent and the clock
    stall flag must not persist. Unknown (None) is untrusted."""
    if inverter_skew_s is None or ntp_age_s is None or stall_reads is None:
        return False
    if abs(inverter_skew_s) > CLOCK_SKEW_MAX_S:
        return False
    if ntp_age_s > NTP_AGE_MAX_S:
        return False
    if stall_reads >= STALL_READS_MAX:
        return False
    return True


def stop_soc_with_margin(reserve_pct, stop_request_pct, ceiling_w, capacity_kwh, react_s=DEFAULT_REACT_S):
    """The Stop SOC to stage: the larger of the owner's request and the effective reserve, plus the SOC reading's resolution and what
    the largest ceiling can draw during the reaction time (the dongle acts on a reading that may be one point stale)."""
    floor = max(reserve_pct, stop_request_pct)
    drawn_kwh = ceiling_w * react_s / 3600.0 / 1000.0
    overshoot_pct = drawn_kwh / capacity_kwh * 100.0
    return min(100.0, floor + SOC_RESOLUTION_PCT + overshoot_pct)


# ---------------------------------------------------------------------------------------------------------------------------
# 6. The pessimistic battery world (ported from gentleNight.ts: advance, startOf, pastStart, fallIntegral, lowestFeasible)
# ---------------------------------------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class World:
    pct_kwh: float      # kWh per percent of the reading scale
    eff: float
    knee: float
    tail: float
    drop_min: float
    offset: float       # the world's true position relative to the displayed reading


class _Sim:
    __slots__ = ("t", "soc", "knee_at", "knee_w")

    def __init__(self, t, soc, knee_at=None, knee_w=None):
        self.t, self.soc, self.knee_at, self.knee_w = t, soc, knee_at, knee_w


def pessimistic_world(capacity_kwh, eff=EFF_PESSIMISTIC, knee=KNEE_PESSIMISTIC_PCT):
    band = CAPACITY_BAND_PCT / 100.0
    scale = SOC_SCALE_ERR_PCT / 100.0
    return World(pct_kwh=capacity_kwh * (1.0 + band) / (1.0 - scale) / 100.0, eff=eff, knee=knee, tail=TAIL_FRACTION,
                 drop_min=min(1.0, DROP_MIN), offset=-(SOC_RESOLUTION_PCT / 2.0 + SOC_NOISE_PCT))


def fall_integral(a, b, tr, drop):
    """Integral of the fall factor over the time since the knee from a to b (minutes): 1 on the plateau side, `tr` after the fall."""
    if drop <= 0:
        return tr * (b - a)
    a1 = min(max(a, 0.0), drop)
    b1 = min(max(b, 0.0), drop)
    ramp = (b1 - a1) - ((1.0 - tr) * (b1 * b1 - a1 * a1)) / (2.0 * drop)
    rest = tr * (b - max(a, drop))
    return ramp + max(0.0, rest)


def _finish_plateau(st, per_min, target):
    at = st.t + (max(0.0, (target - st.soc) / per_min) if per_min > 0 else 0.0)
    st.t = at
    st.soc = target
    return at


def _finish_linear(st, offset, span, gain, target):
    at = st.t + offset + ((span * (target - st.soc)) / gain if gain > 0 else span)
    st.t = at
    st.soc = target
    return at


def advance(w, st, rate_w, until, target):
    """Advance the state with a constant AC rate until `until` (minutes) or until the target is reached; return the minute the target
    is reached, or None. Same 1 minute stepping as the planner; whole plain minutes in the middle of a plateau (or of the tail) are
    skipped in one jump, which is exact because each skipped step has no knee, no target and no end inside it."""
    if st.soc >= target - EPS:
        return st.t
    if not (rate_w > 0):
        if st.t < until:
            st.t = until
        return None
    per_min = rate_w * w.eff / 1000.0 / 60.0 / w.pct_kwh
    while st.t < until - EPS:
        if st.knee_at is None:
            room = min((w.knee - st.soc) / per_min, (target - st.soc) / per_min, until - st.t)
            skip = int(math.floor(room - 1e-6)) - 1
            if skip > 0:
                st.soc += per_min * skip
                st.t += skip
        else:
            kw = st.knee_w if st.knee_w is not None else rate_w
            tr0 = min(1.0, w.tail * kw / rate_w)
            if st.t - st.knee_at >= w.drop_min + 1.0 and per_min * tr0 > 0:
                room = min((target - st.soc) / (per_min * tr0), until - st.t)
                skip = int(math.floor(room - 1e-6)) - 1
                if skip > 0:
                    st.soc += per_min * tr0 * skip
                    st.t += skip
        if not (st.t < until - EPS):
            break
        dt = min(1.0, until - st.t)
        if st.knee_at is None:
            if st.soc + per_min * dt >= w.knee - EPS and w.knee < 100:
                used = max(0.0, (w.knee - st.soc) / per_min) if per_min > 0 else 0.0
                if target <= w.knee + EPS and st.soc + per_min * used >= target - EPS:
                    return _finish_plateau(st, per_min, target)
                st.soc = w.knee
                st.knee_at = st.t + used
                st.knee_w = rate_w
                rest = dt - used
                tr = min(1.0, w.tail * st.knee_w / rate_w)
                gain = per_min * fall_integral(0.0, rest, tr, w.drop_min)
                if st.soc + gain >= target - EPS:
                    return _finish_linear(st, used, rest, gain, target)
                st.soc += gain
                st.t += dt
                continue
            if st.soc + per_min * dt >= target - EPS:
                return _finish_plateau(st, per_min, target)
            st.soc += per_min * dt
            st.t += dt
            continue
        if st.knee_w is None:
            st.knee_w = rate_w
        tr = min(1.0, w.tail * st.knee_w / rate_w)
        gain = per_min * fall_integral(st.t - st.knee_at, st.t + dt - st.knee_at, tr, w.drop_min)
        if st.soc + gain >= target - EPS:
            return _finish_linear(st, 0.0, dt, gain, target)
        st.soc += gain
        st.t += dt
    return None


def _start_of(w, t, reading, charging, anchor_w, rate_w):
    soc = min(100.0, max(0.0, reading + w.offset))
    if soc < w.knee - EPS:
        return _Sim(t, soc)
    if charging and anchor_w is not None:
        return _Sim(t, soc, t - w.drop_min - 1.0, anchor_w)
    return _Sim(t, soc, t, rate_w)


def _past_start(w, t, reading, anchor_w):
    return _Sim(t, min(100.0, max(w.knee, reading + w.offset)), t - w.drop_min - 1.0, anchor_w)


def pess_finish(w, target, t, reading, in_force_w, rate_w, until, charging, past):
    """The PESSIMISTIC finish minute at a constant AC `rate_w` from minute `t`; None when the target is not reached by `until`. When the
    knee may already be passed (`past`) the later of the two consistent starts is returned (the tail anchored at the lower rate)."""
    anchor = None if in_force_w is None else min(in_force_w, rate_w)
    plain = advance(w, _start_of(w, t, reading, charging, anchor, rate_w), rate_w, until, target)
    if not past or anchor is None:
        return plain
    tail = advance(w, _past_start(w, t, reading, anchor), rate_w, until, target)
    if plain is None or tail is None:
        return None
    return max(plain, tail)


def candidates(min_w, ceiling_w, step_w=CHARGE_STEP_W):
    out = []
    s = min_w
    while s <= ceiling_w + EPS:
        out.append(s)
        s += step_w
    return out


def lowest_feasible(w, target, t, reading, in_force_w, cands, deadline_min, charging, past):
    """The lowest candidate whose constant-rate pessimistic simulation reaches the target by the deadline; when none does, the top
    candidate and feasible False (binary search, as in the planner)."""
    def reaches(s):
        f = pess_finish(w, target, t, reading, in_force_w, s, deadline_min, charging, past)
        return f is not None and f <= deadline_min + EPS
    hi = len(cands) - 1
    if hi < 0:
        return None, False
    if not reaches(cands[hi]):
        return cands[hi], False
    lo = 0
    while lo < hi:
        mid = (lo + hi) // 2
        if reaches(cands[mid]):
            hi = mid
        else:
            lo = mid + 1
    return cands[lo], True


def knee_may_be_passed(w, target, opt_pos):
    return target > w.knee + EPS and opt_pos >= w.knee - EPS


def _ceil_step(x, step):
    return math.ceil(x / step - 1e-9) * step


def _floor_step(x, step):
    return math.floor(x / step + 1e-9) * step


def _round_half_away(x):
    return math.floor(x + 0.5) if x >= 0 else -math.floor(-x + 0.5)


# ---------------------------------------------------------------------------------------------------------------------------
# 7. State updates (the only place the kernel's memory changes)
# ---------------------------------------------------------------------------------------------------------------------------
def observe(st, inp, obj=None):
    """Fold one frame into the planner's memory: the last half hour of house load (for the planning peak) and, for a charge (`obj` given),
    the progress tracker. Pure: returns a new state."""
    h = house_w(inp.frame)
    hist = st.house_hist
    if h is not None and is_fresh(h, inp.frame.age_s, TELEMETRY_STALE_S):
        hist = tuple(x for x in hist if x[0] > inp.now_s - HOUSE_PEAK_WINDOW_S) + ((inp.now_s, h),)
    st = replace(st, house_hist=hist)
    if obj is not None:
        st = _track_progress(st, inp, obj)
    return st


def _track_progress(st, inp, obj):
    """REQ-A3: detect that the SOC is not rising as the pessimistic world says it should for the AC energy drawn. Over a window of at
    least EFF_WINDOW_S and EFF_MIN_POINTS the observed SOC points per AC kWh are compared with the pessimistic world's; a progress more
    than 7 % worse lowers eff_scale (never raised: a better progress is not credited). Below the knee only, while a charge runs."""
    f = inp.frame
    ac = ac_in_w(f)
    fresh = is_fresh(f.soc_pct, f.age_s, TELEMETRY_STALE_S) and ac is not None
    if not fresh or ac < GRC_CHARGING_MIN_W or f.soc_pct >= KNEE_PESSIMISTIC_PCT - 2.0:
        return replace(st, acc_t0=None, acc_wh=0.0, acc_last_t=None)
    if st.acc_t0 is None or st.acc_last_t is None:
        return replace(st, acc_t0=inp.now_s, acc_soc0=f.soc_pct, acc_wh=0.0, acc_last_t=inp.now_s, acc_last_ac=ac)
    wh = st.acc_wh + 0.5 * (st.acc_last_ac + ac) * (inp.now_s - st.acc_last_t) / 3600.0
    st = replace(st, acc_wh=wh, acc_last_t=inp.now_s, acc_last_ac=ac)
    points = f.soc_pct - st.acc_soc0
    if inp.now_s - st.acc_t0 >= EFF_WINDOW_S and points >= EFF_MIN_POINTS and wh > 0:
        w = pessimistic_world(obj.capacity_kwh)
        k = (points / (wh / 1000.0)) / (w.eff / w.pct_kwh)
        scale = min(st.eff_scale, max(EFF_SCALE_MIN, k)) if k < EFF_FLAG_BELOW else st.eff_scale
        return replace(st, eff_scale=scale, acc_t0=inp.now_s, acc_soc0=f.soc_pct, acc_wh=0.0, acc_last_t=inp.now_s, acc_last_ac=ac)
    return st


def carry_memory(lease_st, memory_st):
    """The planner's memory (house history, progress tracker) belongs to Home Assistant, the lease state to the dongle: join them."""
    return replace(lease_st, house_hist=memory_st.house_hist, eff_scale=memory_st.eff_scale, acc_t0=memory_st.acc_t0, acc_soc0=memory_st.acc_soc0,
                   acc_wh=memory_st.acc_wh, acc_last_t=memory_st.acc_last_t, acc_last_ac=memory_st.acc_last_ac)


def house_peak_w(st, now_s):
    """The largest HOUSE_MEAN_S mean of the last HOUSE_PEAK_WINDOW_S: a spike of a few minutes is diluted, a sustained load is not."""
    pts = [x for x in st.house_hist if x[0] > now_s - HOUSE_PEAK_WINDOW_S]
    if not pts:
        return None
    best = 0.0
    for i, (t, _) in enumerate(pts):
        win = [v for (tt, v) in pts[i:] if tt < t + HOUSE_MEAN_S]
        best = max(best, sum(win) / len(win))
    return best


def note_start(st, now_s, original_w, gain, v_w, pre_ac_w=None):
    """A charge session starts: the pre-session value is kept, the measured gain is kept; `v_w` is the setpoint now in force."""
    return replace(st, phase="active", original_w=original_w, gain=gain, v_w=v_w, last_write_s=now_s, writes=1 if v_w != original_w else 0,
                   changes=0, last_dir=0, weak=0, pending_judge=v_w != original_w, pre_ac_w=pre_ac_w, pre_v_w=original_w, over_samples=0)


def note_write(st, now_s, value_w, kind, pre_ac_w=None):
    """A write was verified in force. kind: change, forced, restore. The budgets are counted here, in one place."""
    ordinary = kind == "change"
    direction = 0
    if ordinary and st.v_w is not None:
        direction = 1 if value_w > st.v_w else -1
    return replace(st, v_w=value_w, last_write_s=now_s, writes=st.writes + 1, changes=st.changes + (1 if ordinary else 0),
                   last_dir=direction if ordinary else st.last_dir, pending_judge=kind != "restore", pre_ac_w=pre_ac_w,
                   pre_v_w=st.v_w, phase="ended" if kind == "restore" else st.phase, over_samples=0)


def note_end(st):
    return replace(st, phase="ended", pending_judge=False)


# ---------------------------------------------------------------------------------------------------------------------------
# 8. Ramp limiting and hysteresis: the real budgets
# ---------------------------------------------------------------------------------------------------------------------------
def writes_left_for_changes(st):
    """GRC: the night ceiling minus the reserved restores minus what was already written. A restore never needs this room."""
    return CHARGE_NIGHT_WRITES - CHARGE_RESTORE_RESERVE - st.writes


def ramp_charge(st, now_s, want_w, ceiling_w, forced=False):
    """What may be written for a wanted setpoint, inside the GRC budgets. Returns (write_w or None, hold detail or None).
    forced = a safety reduction: it ignores the dwell, the deadband and the change count, but never the step size, the floor or the
    write ceiling (one write is always left for the restore)."""
    v = st.v_w
    if v is None or want_w is None:
        return None, "no_change_needed"
    cap_w = min(ceiling_w, st.original_w if st.original_w is not None else ceiling_w)
    goal = max(CHARGE_MIN_W, min(cap_w, want_w))
    if abs(goal - v) < EPS:
        return None, "no_change_needed"
    if forced:
        if CHARGE_NIGHT_WRITES - st.writes <= 1:
            return None, "budget"
    else:
        if writes_left_for_changes(st) <= 0:
            return None, "budget"
        if st.last_write_s is not None and now_s - st.last_write_s < CHARGE_DWELL_S - EPS:
            return None, "dwell"
        if st.changes >= CHARGE_MAX_CHANGES:
            return None, "budget"
        delta = goal - v
        if abs(delta) < CHARGE_HYST_W - EPS:
            return None, "deadband"
        direction = 1 if delta > 0 else -1
        if st.last_dir != 0 and direction != st.last_dir and abs(delta) < CHARGE_HYST_W + CHARGE_REVERSAL_EXTRA_W - EPS:
            return None, "reversal"
    step = max(-CHARGE_MAX_STEP_W, min(CHARGE_MAX_STEP_W, goal - v))
    new_v = v + step
    new_v = _ceil_step(new_v, CHARGE_STEP_W) if step > 0 else _floor_step(new_v, CHARGE_STEP_W)
    new_v = max(CHARGE_MIN_W, min(cap_w, new_v))
    if abs(new_v - v) < EPS:
        return None, "no_change_needed"
    return new_v, None


def export_step(st, now_s, grid_w, grid_age_s, target_export_w, v_w, lease_ceiling_w, house_w_est=None, pv_w=None):
    """One tick of the export closed loop: the model of dump_controller_tick (same order of checks, same numbers).
    Returns (new_ceiling_w or None, label, fail_closed_detail or None, new_state). `v_w` is the ceiling in force; after a verified
    write the caller records it with note_export_write."""
    if not is_fresh(grid_w, grid_age_s, GRID_STALE_S) or grid_w <= -30000.0 or grid_w >= 30000.0:
        return None, "WAITING FOR FRESH GRID", "stale_telemetry", st
    low, high = st.low_streak, st.high_streak
    if house_w_est is not None and pv_w is not None:
        required = house_w_est + target_export_w - pv_w
        if required < -EXPORT_DEADBAND_W:
            low, high = low + 1, 0
        elif required > lease_ceiling_w:
            low, high = 0, high + 1
        else:
            low, high = 0, 0
    st = replace(st, low_streak=low, high_streak=high)
    if st.last_update_s is not None and now_s - st.last_update_s < EXPORT_SETTLE_S:
        return None, "SETTLING", None, st
    error = grid_w - (-target_export_w)
    if st.response_pending:
        prev = st.pending_err_w if st.pending_err_w is not None else 0.0
        same_dir = (prev > EXPORT_DEADBAND_W and error > 0.0) or (prev < -EXPORT_DEADBAND_W and error < 0.0)
        ineffective, wrong = st.ineffective, st.wrong_dir
        if same_dir:
            improvement = abs(prev) - abs(error)
            if improvement <= -EXPORT_WRONG_DIRECTION_W:
                wrong += 1
                ineffective += 1
            elif improvement < EXPORT_RESPONSE_MARGIN_W:
                ineffective += 1
                wrong = 0
            else:
                ineffective, wrong = 0, 0
        else:
            ineffective, wrong = 0, 0
        st = replace(st, response_pending=False, ineffective=ineffective, wrong_dir=wrong)
        if wrong >= EXPORT_RESPONSE_SAMPLES:
            return None, "GRID RESPONSE SANITY FAILED", "response_failed", st
        if ineffective >= EXPORT_RESPONSE_SAMPLES:
            return None, "NO RESPONSE", None, replace(st, no_resp_since_s=now_s)
    if st.no_resp_since_s is not None:
        if now_s - st.no_resp_since_s < EXPORT_RECOVERY_HOLD_S:
            return None, "NO RESPONSE", None, st
        if st.recoveries >= EXPORT_RECOVERY_ATTEMPTS:
            return None, "NO RESPONSE - RECOVERY EXHAUSTED", "response_failed", st
        st = replace(st, recoveries=st.recoveries + 1, ineffective=0, wrong_dir=0, no_resp_since_s=None)
    if -EXPORT_DEADBAND_W <= error <= EXPORT_DEADBAND_W:
        return None, "TRACKING", None, st
    if st.writes >= EXPORT_MAX_WRITES:
        return None, "WRITE BUDGET EXHAUSTED", "write_budget", st
    step = max(-EXPORT_MAX_STEP_W, min(EXPORT_MAX_STEP_W, error * EXPORT_GAIN))
    rounded = _round_half_away((v_w + step) / EXPORT_ROUND_W) * EXPORT_ROUND_W
    rounded = max(EXPORT_MIN_CEILING_W, min(lease_ceiling_w, rounded))
    if rounded <= EXPORT_MIN_CEILING_W and error < 0:
        label = "SATURATED LOW"
    elif rounded >= lease_ceiling_w and error > 0:
        label = "SATURATED HIGH"
    else:
        label = "TRACKING"
    if rounded == v_w:
        return None, label, None, st
    return rounded, label, None, replace(st, pending_err_w=error)


def note_export_write(st, now_s, value_w):
    """A controller write was verified in force: the settle clock restarts and the response of this write is judged once."""
    return replace(st, v_w=value_w, last_update_s=now_s, writes=st.writes + 1, response_pending=True)


def runaway_check(st, measured_w, expected_w, kind):
    """The measured-power guard (REQ-D3): measured power must not exceed the expected one by the margin for RUNAWAY_SAMPLES samples in
    a row. 'export': requested + max(requested / 2, 750 W) (firmware). 'charge': expected * 1.15 + 500 W (GRC). Returns (state, tripped)."""
    if measured_w is None or expected_w is None:
        return st, False
    if kind == "export":
        limit = expected_w + max(expected_w / 2.0, RUNAWAY_MARGIN_W)
    else:
        limit = expected_w * (1.0 + CHARGE_RUNAWAY_PCT / 100.0) + CHARGE_RUNAWAY_MARGIN_W
    over = st.over_samples + 1 if measured_w > limit else 0
    return replace(st, over_samples=over), over >= RUNAWAY_SAMPLES


def export_over_limit(grid_w, max_export_w, previous_over):
    """The Max Grid Export trip: one sample far over (more than max(500 W, 25 %) above the limit), or two consecutive samples over the
    limit plus max(100 W, 3 %). Returns (trip, over_flag_for_the_next_call)."""
    if max_export_w is None or grid_w is None:
        return False, False
    export = -grid_w
    far = max(EXPORT_FAR_MIN_W, 0.25 * max_export_w)
    margin = max(EXPORT_MARGIN_MIN_W, 0.03 * max_export_w)
    if export > max_export_w + far:
        return True, True
    over = export > max_export_w + margin
    return (over and previous_over), over


# ---------------------------------------------------------------------------------------------------------------------------
# 9. Charge: shared progress, guards and the two charge policies
# ---------------------------------------------------------------------------------------------------------------------------
def ac_in_w(frame):
    """Realised inverter AC input power while charging (>= 0); None when unavailable."""
    return None if frame.inv_ac_w is None else max(0.0, -frame.inv_ac_w)


def lease_end_s(obj):
    """A charge session ends at the deadline, and never later than END_MARGIN_S before the inverter's own slot end."""
    return min(obj.deadline_s, obj.window_end_s - END_MARGIN_S)


def planning_house_w(st, inp):
    """The house load a charge plan must leave room for: the sustained peak of the last half hour, or the load now if that is larger."""
    peak = house_peak_w(st, inp.now_s)
    h = house_w(inp.frame)
    return max([x for x in (peak, h) if x is not None] or [0.0])


def import_headroom_w(st, inp, lim):
    """The AC charge power the import ceiling leaves, planned on the sustained house peak plus the planner's demand margin and the
    ceiling's own margin. None when no import ceiling is applied (and the plan says so)."""
    if lim.import_ceiling_w is None:
        return None
    return lim.import_ceiling_w * (1.0 - IMPORT_MARGIN_PCT / 100.0) - planning_house_w(st, inp) * (1.0 + DEMAND_MARGIN_PCT / 100.0)


def charge_progress(inp, obj, lim, st):
    """Progress and feasibility, shared by both charge policies. Returns a dict: need_w (lowest feasible AC rate), feasible, margin_min
    (deadline minus the pessimistic finish at the rate in force; None when it does not finish), top_ok (the highest allowed rate reaches
    the target by the window end), past (the knee may already be passed), and the ceiling in AC watts with its name."""
    w = pessimistic_world(obj.capacity_kwh, eff=EFF_PESSIMISTIC * st.eff_scale)
    reading = inp.frame.soc_pct
    dl_min = (obj.deadline_s - inp.now_s) / 60.0
    we_min = (obj.window_end_s - inp.now_s) / 60.0
    gain = st.gain if st.gain is not None else st.gain0
    ceiling_sp = lim.power_ceiling_w
    if st.original_w is not None:
        ceiling_sp = min(ceiling_sp, st.original_w)       # a lease is subtractive: it never asks for more than the pre-session value
    ceiling_name = "power"
    headroom = import_headroom_w(st, inp, lim)
    if headroom is not None:
        head_sp = _floor_step(max(0.0, headroom) / gain, CHARGE_STEP_W)
        if head_sp < ceiling_sp:
            ceiling_sp = head_sp
            ceiling_name = "import"
    ceiling_ac = ceiling_sp * gain
    min_ac = _ceil_step(CHARGE_MIN_W * gain, CHARGE_STEP_W)
    cands = candidates(min_ac, ceiling_ac) if ceiling_ac >= min_ac else []
    if cands and cands[-1] < ceiling_ac - EPS:
        cands.append(ceiling_ac)
    in_force_ac = None if st.v_w is None or st.phase != "active" else st.v_w * gain
    charging = in_force_ac is not None
    past = charging and knee_may_be_passed(w, obj.target_soc_pct, reading + SOC_RESOLUTION_PCT / 2.0 + SOC_NOISE_PCT)
    out = {"cands": cands, "ceiling_ac": ceiling_ac, "ceiling_sp": ceiling_sp, "ceiling_name": ceiling_name, "min_ac": min_ac, "world": w, "reading": reading,
           "dl_min": dl_min, "we_min": we_min, "gain": gain, "past": past, "charging": charging, "in_force_ac": in_force_ac}
    if not cands:
        out.update(need_w=None, feasible=False, margin_min=None, top_ok=False, late_min=0.0, house_plan_w=planning_house_w(st, inp))
        return out
    need, feasible = lowest_feasible(w, obj.target_soc_pct, 0.0, reading, in_force_ac, cands, dl_min, charging, past)
    held = None
    if in_force_ac is not None:
        held = pess_finish(w, obj.target_soc_pct, 0.0, reading, in_force_ac, min(in_force_ac, ceiling_ac), dl_min, charging, past)
    top = pess_finish(w, obj.target_soc_pct, 0.0, reading, in_force_ac, ceiling_ac, we_min, charging, past)
    rate_now = min(in_force_ac, ceiling_ac) if in_force_ac is not None else ceiling_ac
    fin_we = pess_finish(w, obj.target_soc_pct, 0.0, reading, in_force_ac, rate_now, we_min, charging, past)
    late = max(0.0, fin_we - dl_min) if fin_we is not None else max(0.0, we_min - dl_min)
    out.update(need_w=need, feasible=feasible, margin_min=None if held is None else dl_min - held, late_min=late,
               top_ok=top is not None and top <= we_min + EPS, house_plan_w=planning_house_w(st, inp))
    return out


def target_guard_trips(inp, obj, lim, st):
    """GRC section 9: the charge is handed back to the pre-session rate as soon as finishing at that rate would no longer leave
    GUARD_MARGIN_S before the end margin of the slot (never worse than today). Pessimistic world, the pre-session rate measured.
    Never when handing back would put the import over the owner's ceiling: a hard ceiling outranks 'never worse than today'."""
    if st.original_w is None or st.gain is None:
        return False
    if inp.frame.soc_pct is not None and inp.frame.soc_pct >= obj.target_soc_pct:
        return False        # the reading is at the target: nothing is at risk (the pessimistic start sits below the reading, which must not trip a false report)
    headroom = import_headroom_w(st, inp, lim)
    if headroom is not None and st.original_w * st.gain > headroom:
        return False
    w = pessimistic_world(obj.capacity_kwh, eff=EFF_PESSIMISTIC * st.eff_scale)
    until = (obj.window_end_s - END_MARGIN_S - GUARD_MARGIN_S - inp.now_s) / 60.0
    if until <= 0:
        return inp.frame.soc_pct < obj.target_soc_pct
    rate = st.original_w * st.gain
    in_force_ac = None if st.v_w is None else st.v_w * st.gain
    past = knee_may_be_passed(w, obj.target_soc_pct, inp.frame.soc_pct + SOC_RESOLUTION_PCT / 2.0 + SOC_NOISE_PCT)
    fin = pess_finish(w, obj.target_soc_pct, 0.0, inp.frame.soc_pct, in_force_ac, rate, until, in_force_ac is not None, past)
    return fin is None


def charge_guards(inp, obj, lim, st, kind):
    """The kernel's guard chain for a charge session, in GUARD_ORDER. Returns the Decision of the first guard that fires (a stop, a
    block, or a forced reduction), else None. `kind` is 'gentle' or 'charge_fixed'. Called by the dongle model every guard tick and
    by the planning step every plan tick."""
    f = inp.frame
    active = st.phase == "active"
    fresh = frame_fresh(f, ("soc", "grid", "ac")) and inp.dongle_ok
    import_w = f.grid_w if is_fresh(f.grid_w, f.age_s, TELEMETRY_STALE_S) else None
    flags = {
        "grid_lost": not inp.grid_ok,
        "owner_end": inp.hold,
        "time_untrusted": not inp.time_ok,
        "stale": not fresh,
        "ceiling": active and lim.import_ceiling_w is not None and import_w is not None and import_w > lim.import_ceiling_w,
        "deadline": inp.now_s >= lease_end_s(obj) - EPS,
        "target_guard": active and kind == "gentle" and fresh and target_guard_trips(inp, obj, lim, st),
    }
    g = first_guard(flags)
    ages = dict(age_s=f.age_s, limit_s=TELEMETRY_STALE_S)
    if g == "grid_lost":
        return make("stop", "grid_lost", end=True) if active else make("blocked", "grid_lost")
    if g == "owner_end":
        return make("stop", "owner_end", end=True) if active else make("blocked", "owner_hold")
    if g == "time_untrusted":
        return make("stop", "time_untrusted", end=True) if active else make("blocked", "time_untrusted")
    if g == "stale":
        if not inp.dongle_ok:
            return make("blocked", "dongle_unavailable")
        return make("stop", "stale_telemetry", end=True, **ages) if active else make("blocked", "stale_telemetry", **ages)
    if g == "ceiling":
        return _import_breach(inp, lim, st, kind, import_w)
    if g == "deadline":
        if active:
            return make("stop", "deadline", end=True)
        return make("stop", "window_end", left_min=(obj.window_end_s - inp.now_s) / 60.0, margin_min=END_MARGIN_S / 60.0)
    if g == "target_guard":
        # the hand-back trips exactly when finishing at today's rate is at risk: the target is REPORTED at risk with it (REQ-A9, F02 of the
        # N4 review: a stop that said nothing left a missed night unreported, because the night's lease was over)
        return make("stop", "target_guard", end=True, unreachable=True)
    if f.soc_pct >= obj.target_soc_pct:
        return make("stop", "target_reached", end=active, soc=f.soc_pct, target=obj.target_soc_pct)
    return None


def _import_breach(inp, lim, st, kind, import_w):
    """The measured import is above the owner's ceiling. Charge Fixed can only end (its rate is fixed). Gentle lowers the setpoint by
    what the breach needs (a forced reduction, at most one step), and ends when even the floor setpoint would not fit."""
    if kind == "charge_fixed" or st.v_w is None:
        return make("stop", "import_ceiling", end=True, import_w=import_w, ceiling_w=lim.import_ceiling_w)
    gain = st.gain if st.gain is not None else st.gain0
    excess_ac = import_w - lim.import_ceiling_w * (1.0 - IMPORT_MARGIN_PCT / 100.0)
    want = _floor_step(st.v_w - excess_ac / gain, CHARGE_STEP_W)
    if want < CHARGE_MIN_W:
        return make("stop", "import_ceiling", end=True, import_w=import_w, ceiling_w=lim.import_ceiling_w)
    write, _why = ramp_charge(st, inp.now_s, want, lim.power_ceiling_w, forced=True)
    if write is None:
        return make("stop", "write_budget", end=True)
    return make("reduce", "import_ceiling", wanted_w=want, write_w=write, v_w=st.v_w, want_w=write, import_w=import_w,
                ceiling_w=lim.import_ceiling_w)


def measure_gain(inp, st):
    """Before the first write, the realised AC power over the setpoint in force gives the plan's gain: relative steps need it, an
    assumed unit never stands in for it (REQ-B18). Returns (gain or None, detail or None); detail names why not."""
    ac = ac_in_w(inp.frame)
    v = inp.in_force_w
    if ac is None or v is None or v <= 0 or ac < GRC_CHARGING_MIN_W:
        return None, "no_charge_running"
    gain = ac / v
    if gain < GRC_GAIN_MIN * st.gain0 or gain > GRC_GAIN_MAX * st.gain0:
        return gain, "implausible_gain"
    return gain, None


def judge_response(inp, st):
    """GRC section 10: after a verified change (and the settle) judge the realised AC power. Returns (state, verdict); verdict is one of
    none, pending, ok, weak, wrong, implausible. The realised power must move by at least 30 % of what the measured gain expects; the
    gain is re-measured from the settled power and must stay inside 50 to 150 % of the assumed unit."""
    if not st.pending_judge or st.last_write_s is None or st.v_w is None or st.pre_v_w is None:
        return st, "none"
    if inp.now_s - st.last_write_s < GRC_SETTLE_S or inp.frame.age_s > GUARD_TICK_S * 2:
        return st, "pending"
    ac = ac_in_w(inp.frame)
    if ac is None or st.pre_ac_w is None:
        return replace(st, pending_judge=False), "none"
    gain = st.gain if st.gain is not None else st.gain0
    dsp = st.v_w - st.pre_v_w
    expected = gain * abs(dsp)
    moved = (ac - st.pre_ac_w) * (1 if dsp > 0 else -1)
    new_gain = ac / st.v_w if st.v_w > 0 else st.gain
    st = replace(st, pending_judge=False, gain=new_gain)
    if new_gain is not None and not (GRC_GAIN_MIN * st.gain0 <= new_gain <= GRC_GAIN_MAX * st.gain0):
        return st, "implausible"
    if expected < CHARGE_HYST_W * gain:
        return st, "ok"
    if moved < -EXPORT_WRONG_DIRECTION_W:
        return st, "wrong"
    if moved < GRC_RESPONSE_MIN * expected:
        return replace(st, weak=st.weak + 1), "weak"
    return replace(st, weak=0), "ok"


def plan_gentle(inp, obj, lim, st):
    """Gentle: the lowest practical rate that still reaches the target by the deadline in the pessimistic projection, re-planned from the
    measured SOC every tick, never above the ceiling, and 'unreachable' said as soon as the projection says so. One Decision."""
    g = charge_guards(inp, obj, lim, st, "gentle")
    if g is not None:
        return g
    f = inp.frame
    if st.phase != "active":
        gain, why = measure_gain(inp, st)
        if why == "no_charge_running":
            return make("blocked", "no_charge_running", min_w=GRC_CHARGING_MIN_W)
        if why == "implausible_gain":
            return make("blocked", "implausible_gain", gain=gain, gain_min=GRC_GAIN_MIN * st.gain0, gain_max=GRC_GAIN_MAX * st.gain0)
        st = replace(st, gain=gain, original_w=inp.in_force_w, v_w=inp.in_force_w)
        if lim.import_ceiling_w is not None and is_fresh(f.grid_w, f.age_s, TELEMETRY_STALE_S) and f.grid_w > lim.import_ceiling_w:
            # REQ-D2: the owner's own table is charging at today's rate and the import is over the ceiling: a session may start ONLY to lower it
            return _import_breach(inp, lim, st, "gentle", f.grid_w)
        return _gentle_decision(inp, obj, lim, st, charge_progress(inp, obj, lim, st), starting=True)
    if f.age_s > STALE_HOLD_S:
        return make("hold", "stale_short", wanted_w=st.v_w, v_w=st.v_w, age_s=f.age_s)
    return _gentle_decision(inp, obj, lim, st, charge_progress(inp, obj, lim, st), starting=False)


def unreachable_detail(prog):
    """The detail of an 'unreachable' report for a charge, from charge_progress: None when the highest allowed rate reaches the target by
    the deadline in the pessimistic projection (nothing to report). 'import_headroom': the import ceiling is what limits the rate and even
    the window end is missed; 'at_risk': the deadline is missed but the highest rate still reaches by the window end (or the rate in force
    still does); 'deadline': not even the window end is reached. One definition for the lease, the start and the watch after a lease."""
    if prog["feasible"]:
        return None
    margin = prog["margin_min"]
    if prog["ceiling_name"] == "import" and not prog["top_ok"]:
        return "import_headroom"
    if prog["top_ok"] or (margin is not None and margin > -EPS):
        return "at_risk"
    return "deadline"


def plan_watch(inp, obj, lim, st):
    """REQ-A9 after a Gentle lease has ended, for ANY reason (F02 of the N4 review): the owner's own rate is back in force and the plan can
    no longer write it, but it keeps WATCHING: a report-only feasibility check on the rate in force, so a night that is going to miss
    the target is still said so early. It never writes and never ends anything (`write_w` None, `end` False). `st` is the planner's memory
    (house history, progress tracker) of Home Assistant; the lease state is gone. One Decision: a guard decision (blocked or stop) as for a
    start, 'blocked' when no charge runs, 'hold/on_plan' when the rate in force reaches the deadline, else 'unreachable'."""
    g = charge_guards(inp, obj, lim, st, "gentle")
    if g is not None:
        return g
    gain, why = measure_gain(inp, st)
    if why == "no_charge_running":
        return make("blocked", "no_charge_running", min_w=GRC_CHARGING_MIN_W)
    if why == "implausible_gain":
        return make("blocked", "implausible_gain", gain=gain, gain_min=GRC_GAIN_MIN * st.gain0, gain_max=GRC_GAIN_MAX * st.gain0)
    run = replace(st, phase="active", gain=gain, original_w=inp.in_force_w, v_w=inp.in_force_w)
    prog = charge_progress(inp, obj, lim, run)
    if prog["need_w"] is None:
        return make("blocked", "no_headroom")
    unreach = unreachable_detail(prog)
    if unreach is None:
        return make("hold", "on_plan", wanted_w=run.v_w, v_w=run.v_w, margin_min=prog["margin_min"])
    return make("unreachable", unreach, unreachable=True, want_w=run.v_w, target=obj.target_soc_pct, ceiling_w=prog["ceiling_ac"],
                late_min=prog["late_min"])


def _hold(st, inp, why, v, want):
    since = 0.0 if st.last_write_s is None else (inp.now_s - st.last_write_s)
    return make("hold", why or "no_change_needed", wanted_w=want, v_w=v, want_w=want, since_min=since / 60.0,
                dwell_min=CHARGE_DWELL_S / 60.0, writes=st.writes, changes=st.changes, band_w=CHARGE_HYST_W,
                need_w=CHARGE_HYST_W + CHARGE_REVERSAL_EXTRA_W)


def _gentle_decision(inp, obj, lim, st, prog, starting):
    """The planner's `choose`: START at the lowest feasible rate; afterwards raise when the rate in force misses the deadline and lower
    when a lower rate still makes it with slack and saves enough; then the ramp budgets decide what may be written."""
    gain = prog["gain"]
    if prog["need_w"] is None:
        return make("blocked", "no_headroom")
    ceiling_ac = prog["ceiling_ac"]
    ceiling_sp = prog["ceiling_sp"]
    need_sp = min(ceiling_sp, _ceil_step(prog["need_w"] / gain, CHARGE_STEP_W))
    margin = prog["margin_min"]
    unreach = unreachable_detail(prog)
    if starting:
        goal = max(CHARGE_MIN_W, min(need_sp, st.original_w))
        write = None if abs(goal - st.original_w) < EPS else goal
        if unreach is not None:
            return make("unreachable", unreach, wanted_w=goal, write_w=write, unreachable=True, want_w=goal, target=obj.target_soc_pct,
                        ceiling_w=ceiling_ac, late_min=prog["late_min"])
        return make("increase", "start", wanted_w=goal, write_w=write, want_w=goal, target=obj.target_soc_pct)
    v = st.v_w
    late = prog["late_min"]
    if v > ceiling_sp + EPS:
        if prog["ceiling_name"] == "power":
            write, _why = ramp_charge(st, inp.now_s, ceiling_sp, lim.power_ceiling_w, forced=True)
            return make("reduce", "power_ceiling", wanted_w=ceiling_sp, write_w=write, v_w=v, want_w=ceiling_sp, ceiling_w=ceiling_sp)
        write, why = ramp_charge(st, inp.now_s, ceiling_sp, lim.power_ceiling_w)
        if write is not None:
            return make("reduce", "import_headroom", wanted_w=ceiling_sp, write_w=write, v_w=v, want_w=write, ceiling_w=lim.import_ceiling_w,
                        house_w=prog["house_plan_w"], headroom_w=prog["ceiling_ac"])
        return _hold(st, inp, why, v, ceiling_sp)
    if margin is None or margin < -EPS:
        raise_to = min(ceiling_sp, max(need_sp, v + CHARGE_HYST_W))
        write, why = ramp_charge(st, inp.now_s, raise_to, lim.power_ceiling_w)
        if unreach is not None:
            return make("unreachable", unreach, wanted_w=raise_to, write_w=write, unreachable=True, v_w=v, want_w=raise_to,
                        target=obj.target_soc_pct, ceiling_w=ceiling_ac, late_min=late)
        if write is not None:
            return make("increase", "behind_plan", wanted_w=raise_to, write_w=write, v_w=v, want_w=write, late_min=late)
        return _hold(st, inp, why, v, raise_to)
    if prog["past"]:
        return make("hold", "past_knee", wanted_w=v, v_w=v)
    low_ac, low_ok = lowest_feasible(prog["world"], obj.target_soc_pct, 0.0, prog["reading"], prog["in_force_ac"], prog["cands"],
                                     prog["dl_min"] - PLANNER_SLACK_S / 60.0, prog["charging"], prog["past"])
    if low_ok and low_ac is not None:
        low_sp = _ceil_step(low_ac / gain, CHARGE_STEP_W)
        if v - low_sp >= PLANNER_HYSTERESIS_W - EPS and low_sp >= CHARGE_MIN_W:
            write, why = ramp_charge(st, inp.now_s, low_sp, lim.power_ceiling_w)
            if write is not None:
                return make("reduce", "ahead_of_plan", wanted_w=low_sp, write_w=write, v_w=v, want_w=write)
            return _hold(st, inp, why, v, low_sp)
    return make("hold", "on_plan", wanted_w=v, v_w=v, margin_min=margin)


def plan_charge_fixed(inp, obj, lim, st, owner_rate_w=None):
    """Charge Fixed: reach the target by the deadline at ONE fixed rate chosen at the start (the owner's request, never above the ceiling
    or the import headroom) and end early at the target; the plan says at the start whether that rate can make it. Once running it
    can only be ended (the guards end it); it never changes the rate."""
    g = charge_guards(inp, obj, lim, st, "charge_fixed")
    if g is not None:
        return g
    if st.phase == "active":
        return make("hold", "fixed_rate", wanted_w=st.v_w, v_w=st.v_w)
    prog = charge_progress(inp, obj, lim, replace(st, v_w=None))
    cap = prog["ceiling_sp"]
    if cap < CHARGE_MIN_W:
        return make("blocked", "no_headroom")
    rate = cap if owner_rate_w is None else max(CHARGE_MIN_W, min(cap, owner_rate_w))
    w = prog["world"]
    fin = pess_finish(w, obj.target_soc_pct, 0.0, prog["reading"], None, rate * prog["gain"], prog["dl_min"], False, False)
    if fin is None or fin > prog["dl_min"] + EPS:
        top = pess_finish(w, obj.target_soc_pct, 0.0, prog["reading"], None, rate * prog["gain"], prog["we_min"], False, False)
        detail = "at_risk" if (top is not None and top <= prog["we_min"] + EPS) else "deadline"
        return make("unreachable", detail, wanted_w=rate, write_w=rate, unreachable=True, want_w=rate, target=obj.target_soc_pct,
                    ceiling_w=rate * prog["gain"], late_min=0.0)
    return make("increase", "start", wanted_w=rate, write_w=rate, want_w=rate, target=obj.target_soc_pct)


# ---------------------------------------------------------------------------------------------------------------------------
# 10. Export
# ---------------------------------------------------------------------------------------------------------------------------
def export_floor_pct(obj, reserve_pct):
    """The floor the export may never go below: the larger of the Stop SOC request and the effective reserve, with the reaction margin."""
    return stop_soc_with_margin(reserve_pct, obj.stop_soc_pct, obj.lease_ceiling_w, obj.capacity_kwh)


def export_required_w(frame, target_export_w):
    """Battery AC power the target needs now: house + export target - MEASURED solar (never a forecast). None when an input is missing."""
    h = house_w(frame)
    if h is None or frame.pv_w is None:
        return None
    return h + target_export_w - frame.pv_w


def export_energy_kwh(soc_pct, floor_pct, capacity_kwh):
    """Usable battery energy above the floor, pessimistic: the capacity band is taken off."""
    return max(0.0, (soc_pct - floor_pct) / 100.0 * capacity_kwh * (1.0 - CAPACITY_BAND_PCT / 100.0))


def export_duration_s(soc_pct, floor_pct, capacity_kwh, power_ac_w):
    """How long the energy above the floor lasts at `power_ac_w` of AC output (pessimistic discharge efficiency)."""
    if power_ac_w <= 0:
        return INF
    return export_energy_kwh(soc_pct, floor_pct, capacity_kwh) * EXPORT_DISCHARGE_EFF * 1000.0 / power_ac_w * 3600.0


def export_guards(inp, obj, lim, st, over_trip=False, runaway_trip=False):
    """The guard chain of a RUNNING export session (the dongle's 15 s tick), in GUARD_ORDER. Returns a Decision for the first guard that
    fires, else None. The Stop SOC in force is st.stop_soc_pct (latched at the start, raise-only)."""
    f = inp.frame
    fresh = frame_fresh(f, ("soc", "grid")) and inp.dongle_ok
    stop = st.stop_soc_pct if st.stop_soc_pct is not None else export_floor_pct(obj, inp.reserve_pct)
    flags = {
        "grid_lost": not inp.grid_ok,
        "owner_end": inp.hold,
        "time_untrusted": not inp.time_ok,
        "stale": not fresh,
        "floor": fresh and f.soc_pct <= stop,
        "ceiling": fresh and over_trip,
        "runaway": runaway_trip,
        "deadline": inp.now_s >= obj.end_s - EPS,
    }
    g = first_guard(flags)
    ages = dict(age_s=f.age_s, limit_s=GRID_STALE_S)
    if g == "grid_lost":
        return make("stop", "grid_lost", end=True)
    if g == "owner_end":
        return make("stop", "owner_end", end=True)
    if g == "time_untrusted":
        return make("stop", "time_untrusted", end=True)
    if g == "stale":
        return make("stop", "stale_telemetry", end=True, **ages)
    if g == "floor":
        return make("stop", "floor_reached", end=True, soc=f.soc_pct, floor=stop)
    if g == "ceiling":
        return make("stop", "export_over_limit", end=True, export_w=-(f.grid_w or 0.0), limit_w=lim.max_export_w)
    if g == "runaway":
        return make("stop", "runaway", end=True, measured_w=f.batt_w, expected_w=st.v_w, samples=RUNAWAY_SAMPLES)
    if g == "deadline":
        return make("stop", "lease_end", end=True)
    return None


def export_tick(inp, obj, lim, st):
    """One tick of a RUNNING export session (the dongle's 15 s guard tick): the guards in GUARD_ORDER, then the closed loop (the model
    of dump_controller_tick). Returns (Decision, state). A Decision with write_w is a ceiling write for the caller to verify; with end
    the session is to be restored. The measured-power guard waits RUNAWAY_GRACE_S after a start or a write."""
    f = inp.frame
    over_trip, over_flag = export_over_limit(f.grid_w, lim.max_export_w, st.export_over)
    st = replace(st, export_over=over_flag)
    tripped = False
    since = inp.now_s - (st.last_update_s if st.last_update_s is not None else inp.now_s)
    if since >= RUNAWAY_GRACE_S and frame_fresh(f, ("batt",)):
        st, tripped = runaway_check(st, f.batt_w, st.v_w, "export")
    elif since < RUNAWAY_GRACE_S:
        st = replace(st, over_samples=0)
    abs_limit = max(st.v_w, min(obj.lease_ceiling_w, RUNAWAY_BACKSTOP_FLOOR_W)) + RUNAWAY_ABS_MARGIN_W
    abs_over = st.abs_over + 1 if (frame_fresh(f, ("batt",)) and f.batt_w > abs_limit) else 0
    st = replace(st, abs_over=abs_over)
    tripped = tripped or abs_over >= RUNAWAY_ABS_SAMPLES
    g = export_guards(inp, obj, lim, st, over_trip=over_trip, runaway_trip=tripped)
    if g is not None:
        return g, st
    house_est = house_w(f)
    new, label, fail, st = export_step(st, inp.now_s, f.grid_w, f.age_s, obj.target_export_w, st.v_w, obj.lease_ceiling_w, house_est, f.pv_w)
    ages = dict(age_s=f.age_s, limit_s=GRID_STALE_S)
    if fail == "stale_telemetry":
        return make("stop", "stale_telemetry", end=True, **ages), st
    if fail == "write_budget":
        return make("stop", "write_budget", end=True), st
    if fail == "response_failed":
        return make("stop", "response_failed", end=True), st
    export_w = -(f.grid_w if f.grid_w is not None else 0.0)
    nums = dict(v_w=st.v_w, export_w=export_w, target_w=obj.target_export_w, band_w=EXPORT_DEADBAND_W)
    if st.low_streak >= EXPORT_FEASIBILITY_CONFIRM:
        return make("unreachable", "infeasible_low", wanted_w=st.v_w, write_w=new, unreachable=True, pv_w=f.pv_w,
                    target_w=obj.target_export_w, excess_w=-(export_required_w(f, obj.target_export_w) or 0.0)), st
    if st.high_streak >= EXPORT_FEASIBILITY_CONFIRM:
        return make("unreachable", "infeasible_high", wanted_w=obj.lease_ceiling_w if new is None else new, write_w=new, unreachable=True,
                    house_w=house_est, target_w=obj.target_export_w, pv_w=f.pv_w, required_w=export_required_w(f, obj.target_export_w),
                    ceiling_w=obj.lease_ceiling_w), st
    if new is not None:
        if new > st.v_w:
            return make("increase", "export_short", wanted_w=new, write_w=new, want_w=new, **nums), st
        return make("reduce", "export_over", wanted_w=new, write_w=new, want_w=new, **nums), st
    if label == "SETTLING":
        since_s = inp.now_s - (st.last_update_s if st.last_update_s is not None else inp.now_s)
        return make("hold", "settling", wanted_w=st.v_w, v_w=st.v_w, since_s=since_s, settle_s=EXPORT_SETTLE_S), st
    if label == "SATURATED LOW":
        return make("hold", "saturated_low", wanted_w=st.v_w, v_w=st.v_w, floor_w=EXPORT_MIN_CEILING_W, target_w=obj.target_export_w), st
    if label == "SATURATED HIGH":
        return make("hold", "saturated_high", wanted_w=st.v_w, v_w=st.v_w, ceiling_w=obj.lease_ceiling_w), st
    if label.startswith("NO RESPONSE"):
        return make("hold", "no_response", wanted_w=st.v_w, v_w=st.v_w), st
    return make("hold", "tracking", wanted_w=st.v_w, **nums), st


def plan_export(inp, obj, lim, st, authority_free=True):
    """Export, the planning step (Home Assistant, a few minutes apart): the battery power that nets the target (house + target - measured
    solar), the floor (never below the effective reserve, with the reaction margin), the duration from the energy above the floor, and
    the guards. At the start it gives the feed-forward ceiling and the Stop SOC to stage; while the lease runs it supervises: it asks
    for a RAISE of the Stop SOC when the reserve rises, ends the session when the floor is reached, and reports a target that cannot be
    met. The proportional loop itself is export_step (the firmware). One Decision."""
    f = inp.frame
    active = st.phase == "active"
    floor = export_floor_pct(obj, inp.reserve_pct)
    if active:
        g = export_guards(inp, obj, lim, st)
        if g is not None:
            if g.detail == "floor_reached" and st.stop_soc_pct is not None and floor > st.stop_soc_pct + EPS:
                return make("stop", "reserve_rose", end=True, reserve=inp.reserve_pct, soc=f.soc_pct, floor=floor)
            return g
    else:
        flags = {"grid_lost": not inp.grid_ok, "owner_end": inp.hold, "time_untrusted": not inp.time_ok,
                 "stale": not (frame_fresh(f, ("soc", "grid")) and inp.dongle_ok),
                 "floor": frame_fresh(f, ("soc",)) and f.soc_pct <= floor, "deadline": inp.now_s >= obj.end_s - EPS}
        g = first_guard(flags)
        if g == "grid_lost":
            return make("blocked", "grid_lost")
        if g == "owner_end":
            return make("blocked", "owner_hold")
        if g == "time_untrusted":
            return make("blocked", "time_untrusted")
        if g == "stale":
            if not inp.dongle_ok:
                return make("blocked", "dongle_unavailable")
            return make("blocked", "stale_telemetry", age_s=f.age_s, limit_s=GRID_STALE_S)
        if g in ("floor", "deadline"):
            return make("blocked", "no_headroom")
        if not authority_free:
            return make("blocked", "authority_busy", owner="another controller")
    required = export_required_w(f, obj.target_export_w)
    if required is None:
        if active:
            return make("hold", "stale_short", wanted_w=st.v_w, v_w=st.v_w, age_s=f.age_s)
        return make("blocked", "stale_telemetry", age_s=f.age_s, limit_s=GRID_STALE_S)
    raise_to = floor if (active and st.stop_soc_pct is not None and floor > st.stop_soc_pct + EPS) else None
    if raise_to is not None and f.soc_pct <= floor:
        # the reserve rose to or above the battery's own SOC: there is no usable energy left above it, end now (do not wait for the raise to land)
        return make("stop", "reserve_rose", end=True, reserve=inp.reserve_pct, soc=f.soc_pct, floor=floor)
    if required < -EXPORT_DEADBAND_W:
        return make("unreachable", "infeasible_low", wanted_w=EXPORT_MIN_CEILING_W, write_w=None, unreachable=True,
                    stop_soc_pct=None if not active else raise_to, pv_w=f.pv_w, target_w=obj.target_export_w, excess_w=-required)
    if required > obj.lease_ceiling_w:
        wanted = obj.lease_ceiling_w if active else min(EXPORT_FF_MAX_START_W, obj.lease_ceiling_w)
        return make("unreachable", "infeasible_high", wanted_w=wanted, write_w=None if active else wanted, unreachable=True,
                    stop_soc_pct=floor if not active else raise_to, house_w=house_w(f), target_w=obj.target_export_w, pv_w=f.pv_w,
                    required_w=required, ceiling_w=obj.lease_ceiling_w)
    if active:
        return make("hold", "tracking", wanted_w=st.v_w, v_w=st.v_w, stop_soc_pct=raise_to, export_w=-(f.grid_w or 0.0),
                    target_w=obj.target_export_w, band_w=EXPORT_DEADBAND_W)
    start_cap = min(EXPORT_FF_MAX_START_W, obj.lease_ceiling_w)
    ff = max(EXPORT_MIN_CEILING_W, min(start_cap, _round_half_away(required / EXPORT_ROUND_W) * EXPORT_ROUND_W))
    return make("increase", "feed_forward", wanted_w=ff, write_w=ff, stop_soc_pct=floor, want_w=ff, house_w=house_w(f),
                target_w=obj.target_export_w, pv_w=f.pv_w)


POLICIES = {"charge_fixed": plan_charge_fixed, "gentle": plan_gentle, "export": plan_export}
