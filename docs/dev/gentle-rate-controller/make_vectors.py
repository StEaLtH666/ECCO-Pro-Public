#!/usr/bin/env python3
"""Writes vectors.json: the GRC golden vectors. Every expectation below is HAND-COMPUTED from SPEC.md (the arithmetic
is noted beside the less obvious ones); nothing here runs the model. test_reference_model.py checks that the model
meets every expectation and that vectors.json is exactly what this script writes.

Frame (vector_runner.py): E0 = 00:35 local, the slot runs 00:30-05:30 (grid, target 100 %), the plan deadline is 04:30
(E0 + 14100), the window end 05:30 (E0 + 17700), capacity 30000 Wh, taper 90 %, one plan point of 6000 W realised.
Every number is a synthetic test frame, not a site reading. The vectors' configuration sets capacity_floor_wh =
20000 (vector_runner.FRAME_CONFIG: the floor has no usable default since revision 3; 20 kWh is below the plan's 30 kWh on
purpose, so that V156/V157 can show the floor and the only-rising rule).
The slot's own end (SPEC revision 2) is taken from the configured slot end and the dongle clock, never later than the
real end: slot_end = epoch + minutes-to-end * 60 - 60 = E0 + 17640 + (x % 60) at epoch E0 + x. The lease end is
min(deadline, slot_end - 600); the target guard compares against slot_end - 600 = E0 + 17040 + (x % 60).
Target guard at SOC 40.0 %: plateau 500 * 30000 // 1000 = 15000 Wh at 8200*85//100 = 6970 W -> 7747 s, tail 3000 Wh at
8200*25//100 = 2050 W -> 5268 s; it trips once x + 13015 + 900 >= 17040 + x % 60, i.e. x - x % 60 >= 3125: from E0+3180.
Before the lease the slot power is 8000 and the battery takes 8200 W (gain 102 %).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from vector_runner import E0, NIGHT0, NOW0  # noqa: E402

V: list[dict] = []


def vec(vid: str, title: str, ticks: list, **kw) -> None:
    assert all(x["id"] != vid for x in V), vid
    d = {"id": vid, "title": title}
    d.update(kw)
    d["ticks"] = ticks
    V.append(d)


ARM = {"dt": 0, "set": {"arm": True}, "expect": {"state": "ARMED", "event": "R_ARMED", "action": "NONE"}}
# after a restart the arm must be seen OFF once before it arms (the dongle switch restores OFF)
IDLE0 = {"dt": 0, "expect": {"state": "IDLE", "action": "NONE"}}


def refuse(reason: str, start_extra: dict | None = None) -> list:
    t = {"dt": 1000, "sample": True, "pulse": {"start": True},
         "expect": {"state": "IDLE", "event": reason, "action": "NONE", "disarm": True, "last_reason": reason}}
    if start_extra:
        for k, v in start_extra.items():
            t[k] = v
    return [dict(ARM), t]


# The standard lease start (11 ticks): START writes 6000 (8000*6000//8200 = 5853, capped at 8000-2000 = 6000), the
# write is verified, 4 samples after the 45 s settle judge the response (6150 W: act -2050, expected 2040, gain 102).
def prefix(batt: int = 6150, judge: dict | None = None, lease_end: int = E0 + 14100) -> list:
    j = {"state": "LEASED", "event": "R_RESPONSE_OK", "gain_pct": 102, "p_ref": 6150} if judge is None else judge
    return [
        dict(ARM),
        {"dt": 1000, "sample": True, "pulse": {"start": True},
         "expect": {"state": "ADJUSTING", "action": "WRITE", "value": 6000, "seq": 1, "disarm": True, "commit": True,
                    "event": "R_LEASE_STARTED", "changes": 1, "writes_night": 1, "gain_pct": 102, "v": 8000, "p": 6000,
                    "lease_end": lease_end}},
        {"dt": 2000, "set": {"arm": False}, "pulse": {"op": "OK"},
         "expect": {"state": "SETTLING", "event": "R_WRITE_VERIFIED", "v": 6000, "action": "NONE"}},
        {"repeat": 4, "dt": 10000, "keep": True, "set": {"batt_w": batt, "live_sp": 6000},
         "expect_all": {"state": "SETTLING", "action": "NONE", "event": "R_NONE"}},
        {"repeat": 3, "dt": 10000, "keep": True, "expect_all": {"state": "SETTLING", "action": "NONE"}},
        {"dt": 10000, "keep": True, "expect": j},
    ]


def restore_ok(reason: str, writes: int) -> list:
    return [{"dt": 1000, "pulse": {"op": "OK"},
             "expect": {"state": "IDLE", "event": "R_RESTORED", "last_reason": reason, "writes_night": writes,
                        "commit": True}}]


def lease_end_with(reason: str, step: dict, writes: int = 2) -> list:
    s = dict(step)
    s["expect"] = {"state": "RESTORING", "action": "RESTORE", "value": 8000, "event": reason, "restore_attempts": 1,
                   "writes_night": writes, "commit": True}
    return prefix() + [s] + restore_ok(reason, writes)


# ------------------------------------------------------------------------------------------------- IDLE / ARMED
vec("V01", "START without an arm is refused and changes nothing",
    [{"dt": 0, "pulse": {"start": True},
      "expect": {"state": "IDLE", "event": "R_REFUSE_NOT_ARMED", "action": "NONE", "disarm": False}}])
vec("V02", "the owner turns the arm off before START",
    [dict(ARM), {"dt": 1000, "set": {"arm": False}, "expect": {"state": "IDLE", "event": "R_DISARMED"}}])
vec("V03", "the one-shot arm expires after 12 h and must be cycled before it arms again",
    [dict(ARM),
     {"dt": 43_200_000, "expect": {"state": "IDLE", "event": "R_ARM_EXPIRED", "disarm": True}},
     {"dt": 1000, "expect": {"state": "IDLE", "event": "R_NONE"}},
     {"dt": 1000, "set": {"arm": False}, "expect": {"state": "IDLE"}},
     {"dt": 1000, "set": {"arm": True}, "expect": {"state": "ARMED", "event": "R_ARMED"}}])
vec("V04", "a refused START consumes the arm: the arm input still on does not re-arm",
    refuse("R_REFUSE_FAULT", {"set": {"fault": True}})
    + [{"dt": 1000, "set": {"fault": False}, "expect": {"state": "IDLE", "event": "R_NONE"}},
       {"dt": 1000, "pulse": {"start": True}, "expect": {"state": "IDLE", "event": "R_REFUSE_NOT_ARMED"}}])
vec("V05", "START and arm in the same IDLE tick: refused (not yet armed), then armed",
    [{"dt": 0, "set": {"arm": True}, "pulse": {"start": True},
      "expect": {"state": "ARMED", "event": "R_REFUSE_NOT_ARMED", "action": "NONE"}}])

# ------------------------------------------------------------------------------------------------- START refusals
R = [
    ("V10", "wall clock not valid", "R_REFUSE_CLOCK", {"set": {"epoch": 0}}),
    ("V11", "night unknown", "R_REFUSE_CLOCK", {"set": {"night_id": 0}}),
    ("V12", "clock-change night", "R_REFUSE_CLOCK_CHANGE", {"set": {"clock_change_night": True}}),
    ("V13", "inverter clock 121 s off", "R_REFUSE_INVERTER_CLOCK", {"set": {"inv_skew_s": 121}}),
    ("V14", "inverter clock unknown", "R_REFUSE_INVERTER_CLOCK", {"set": {"inv_skew_s": -1}}),
    ("V15", "RTC correction in progress", "R_REFUSE_RTC", {"set": {"rtc_busy": True}}),
    ("V16", "a Free Power lease or restore is owed", "R_REFUSE_OTHER", {"set": {"other": 1}}),
    ("V17", "the TOU editor is in flight", "R_REFUSE_OTHER", {"set": {"other": 4}}),
    ("V18", "the shared write mutex is held", "R_REFUSE_OTHER", {"set": {"mutex_busy": True}}),
    ("V19", "inverter or BMS fault flags", "R_REFUSE_FAULT", {"set": {"fault": True}}),
    ("V20", "telemetry not valid", "R_REFUSE_TELEMETRY", {"set": {"tel_ok": False}}),
    ("V21", "SOC unknown", "R_REFUSE_SOC", {"set": {"soc": -1}}),
    ("V22", "SOC above 100 %", "R_REFUSE_SOC", {"set": {"soc": 1001}}),
    ("V23", "plan not valid", "R_REFUSE_PLAN_INVALID", {"plan": {"valid": False}}),
    ("V24", "plan with no points", "R_REFUSE_PLAN_INVALID", {"plan": {"n": 0}}),
    ("V25", "plan ceiling below the floor", "R_REFUSE_PLAN_INVALID", {"plan": {"ceiling_w": 400}}),
    ("V26", "plan ceiling not a multiple of 100", "R_REFUSE_PLAN_INVALID", {"plan": {"ceiling_w": 6050}}),
    ("V27", "plan times not increasing", "R_REFUSE_PLAN_INVALID", {"plan": {"t": [E0, E0], "p": [6000, 5000]}}),
    ("V28", "plan power above 10 kW", "R_REFUSE_PLAN_INVALID", {"plan": {"p": [10001]}}),
    ("V29", "plan window end not after the deadline", "R_REFUSE_PLAN_INVALID", {"plan": {"window_end": E0 + 14100}}),
    ("V30", "plan slot 7", "R_REFUSE_PLAN_INVALID", {"plan": {"slot": 7}}),
    ("V31", "plan capacity implausible", "R_REFUSE_PLAN_INVALID", {"plan": {"capacity_wh": 500}}),
    ("V32", "slot carries no grid charge", "R_REFUSE_SLOT", {"set": {"slot_grid": False}}),
    ("V33", "plan target differs from the slot's own SOC target", "R_REFUSE_SLOT", {"set": {"slot_target": 90}}),
    ("V34", "now is outside the slot", "R_REFUSE_SLOT", {"set": {"slot_start_min": 60}}),
    ("V35", "the lease would outlast the slot (slot ends 03:20: 9840 s left, lease 14099 s)", "R_REFUSE_SLOT",
     {"set": {"slot_end_min": 200}}),
    ("V36", "slot power below floor + hysteresis", "R_REFUSE_SLOT_POWER", {"set": {"live_sp": 700}}),
    ("V37", "slot power above the firmware bound", "R_REFUSE_SLOT_POWER", {"set": {"live_sp": 8100}}),
    ("V38", "SOC already at the target", "R_REFUSE_TARGET_MET", {"set": {"soc": 1000}}),
    ("V39", "no grid charge running (900 W)", "R_REFUSE_NOT_CHARGING", {"set": {"batt_w": 900}}),
    ("V40", "realised 3900 W at 8000: gain 48 % (the slot power is not what limits the charge)",
     "R_REFUSE_IMPLAUSIBLE", {"set": {"batt_w": 3900}}),
    ("V41", "realised 12100 W at 8000: gain 151 %", "R_REFUSE_IMPLAUSIBLE", {"set": {"batt_w": 12100}}),
    ("V42", "deadline 2999 s away", "R_REFUSE_TOO_LATE", {"plan": {"deadline": E0 + 3000}}),
    # soc 19.0 %: plateau 710*30000//1000 = 21300 Wh -> 11001 s, tail 5268 s; E0+1+16269+900 >= E0+17041
    ("V43", "the target is at risk even at today's rate", "R_REFUSE_TARGET_AT_RISK", {"set": {"soc": 190}}),
]
for vid, title, reason, extra in R:
    vec(vid, "START refused: " + title, refuse(reason, extra))
# soc 20.0 %: plateau 21000 Wh -> 10846 s, tail 5268 s: E0+1+16114+900 = E0+17015 < E0+17041
vec("V43b", "START accepted just inside the target guard (SOC 20 %)",
    [dict(ARM), {"dt": 1000, "sample": True, "pulse": {"start": True}, "set": {"soc": 200},
                 "expect": {"state": "ADJUSTING", "action": "WRITE", "value": 6000}}])
vec("V44", "START refused: telemetry 91 s old",
    [dict(ARM), {"dt": 91000, "cfg": True, "refresh": True, "pulse": {"start": True},
                 "expect": {"state": "IDLE", "event": "R_REFUSE_TELEMETRY", "disarm": True}}])
vec("V45", "START refused: plan 1200.001 s old",
    [dict(ARM), {"dt": 1_200_001, "sample": True, "cfg": True, "pulse": {"start": True},
                 "expect": {"state": "IDLE", "event": "R_REFUSE_PLAN_STALE"}}])
vec("V46", "START refused: configuration read 180.001 s old",
    [dict(ARM), {"dt": 180_001, "sample": True, "refresh": True, "pulse": {"start": True},
                 "expect": {"state": "IDLE", "event": "R_REFUSE_CONFIG_STALE"}}])
BOOT_W6 = {"flags": 0, "night_id": NIGHT0, "writes_night": 6}
vec("V47", "START refused: 6 writes already this night leave no change budget once 3 restores are reserved",
    [IDLE0] + refuse("R_REFUSE_WRITE_BUDGET"), boot=BOOT_W6)
vec("V48", "the same counter on a NEW night is reset and START is accepted",
    [IDLE0, dict(ARM), {"dt": 1000, "sample": True, "pulse": {"start": True}, "set": {"night_id": NIGHT0 + 1},
                 "expect": {"state": "ADJUSTING", "action": "WRITE", "value": 6000, "writes_night": 1}}],
    boot=BOOT_W6)

# ------------------------------------------------------------------------------------------------- the lease
vec("V50", "standard lease start: one bounded write, verified, response judged", prefix(),
    final={"state": "LEASED", "v": 6000, "changes": 1, "writes_night": 1, "record_flags": 5})
vec("V51", "the same lease across the 32-bit uptime wrap", prefix(), base_set={"now_ms": 4294967295 - 30000},
    final={"state": "LEASED", "v": 6000})
# p 5000: 6000*5000//6150 = 4878 -> 4900; dwell from the verified write at NOW0+3000 ends at NOW0+1803000 = tick 29
vec("V52", "dwell: a new plan waits 30 min after the last verified change",
    prefix() + [{"repeat": 28, "dt": 60000, "keep": True, "plan": {"p": [5000]},
                 "expect_all": {"action": "NONE", "state": "LEASED"}},
                {"dt": 60000, "keep": True,
                 "expect": {"action": "WRITE", "value": 4900, "state": "ADJUSTING", "changes": 2, "writes_night": 2,
                            "commit": True, "event": "R_WRITE_REQUESTED"}}])
# p 6300: 6000*6300//6150 = 6146 -> 6100: +100 < 300
vec("V53", "hysteresis: a change smaller than 300 W is never written",
    prefix() + [{"repeat": 31, "dt": 60000, "keep": True, "plan": {"p": [6300]},
                 "expect_all": {"action": "NONE", "state": "LEASED"}}])
# p 6600 -> 6439 -> 6400: +400 against the last (downward) change needs 600; p 6800 -> 6634 -> 6600: +600 written
vec("V54", "reversal: a change against the previous direction needs 600 W",
    prefix() + [{"repeat": 30, "dt": 60000, "keep": True, "plan": {"p": [6600]}, "expect_all": {"action": "NONE"}},
                {"dt": 60000, "keep": True, "plan": {"p": [6800]}, "expect": {"action": "WRITE", "value": 6600}}])
# original 7000: START 7000*6000//8200 = 5121 -> 5100; judge 5300 (act -2900, exp 117*1900//100 = 2223), gain 103;
# p 10000: 5100*10000//5300 = 9622, step cap 7100, ceiling min(7000, 8000, 8000) = 7000
vec("V55", "subtractive: never above the pre-lease value although the plan and the step cap allow more",
    [dict(ARM),
     {"dt": 1000, "sample": True, "pulse": {"start": True},
      "expect": {"action": "WRITE", "value": 5100, "gain_pct": 117}},
     {"dt": 2000, "set": {"arm": False}, "pulse": {"op": "OK"}},
     {"repeat": 7, "dt": 10000, "keep": True, "set": {"batt_w": 5300, "live_sp": 5100}},
     {"dt": 10000, "keep": True, "expect": {"event": "R_RESPONSE_OK", "gain_pct": 103, "p_ref": 5300}},
     {"repeat": 28, "dt": 60000, "keep": True, "plan": {"p": [10000]}, "expect_all": {"action": "NONE"}},
     {"dt": 60000, "keep": True, "expect": {"action": "WRITE", "value": 7000}}],
    base_set={"live_sp": 7000})
# revision 2 (stricter): the owner ceiling is approached by at most one 2000 W step per change. START: 8000*6000//8200
# = 5853 is capped at 6000, the owner ceiling 5000 is a step below 8000 - 2000 = 6000 so 6000 is written (revision 1
# wrote 5000 at once: the killed mutant "the owner ceiling bypasses the step cap"); after the dwell the ceiling binds:
# 6000*6000//6150 = 5853 -> 5900, ceiling max(5000, 4000) = 5000
vec("V56", "the owner ceiling is approached by at most one 2000 W step per change",
    prefix() + [{"repeat": 28, "dt": 60000, "keep": True, "expect_all": {"action": "NONE", "state": "LEASED"}},
                {"dt": 60000, "keep": True, "expect": {"action": "WRITE", "value": 5000, "changes": 2}}],
    base_plan={"ceiling_w": 5000})
# p 1000 at START: 8000*1000//8200 = 975, capped at 6000
vec("V57", "the step cap bounds the START write", [dict(ARM), {"dt": 1000, "sample": True, "pulse": {"start": True},
                                                            "expect": {"action": "WRITE", "value": 6000}}],
    base_plan={"p": [1000]})
# p 7900 at START: 8000*7900//8200 = 7707 -> 7700: -300 is written; p 8000 -> 7804 -> 7800: -200 is not
vec("V58", "START at the hysteresis edge writes", [dict(ARM), {"dt": 1000, "sample": True, "pulse": {"start": True},
                                                              "expect": {"action": "WRITE", "value": 7700}}],
    base_plan={"p": [7900]})
vec("V59", "START with nothing to change holds the lease without a write",
    [dict(ARM), {"dt": 1000, "sample": True, "pulse": {"start": True},
                 "expect": {"state": "LEASED", "action": "NONE", "event": "R_LEASE_STARTED", "commit": True,
                            "writes_night": 0, "changes": 0}}], base_plan={"p": [8000]})
vec("V60", "a later plan point applies at its time (piecewise constant)",
    prefix() + [{"repeat": 28, "dt": 60000, "keep": True, "expect_all": {"action": "NONE"}},
                {"dt": 60000, "keep": True, "expect": {"action": "WRITE", "value": 4900}}],
    base_plan={"t": [E0 - 60, E0 + 1800], "p": [6000, 5000]})  # tick 29: epoch E0+1823 and the dwell both pass

# six changes with a short dwell (config): 6000, 4900, 3900, 2900, 2000, 1500, then the budget holds
CFG_FAST = {"dwell_ms": 60000, "settle_ms": 5000, "judge_samples": 1}


def fast_changes(n_changes_expected: int, writes_before: int) -> list:
    t = [dict(ARM),
         {"dt": 1000, "sample": True, "pulse": {"start": True},
          "expect": {"action": "WRITE", "value": 6000, "writes_night": writes_before + 1}},
         {"dt": 2000, "set": {"arm": False}, "pulse": {"op": "OK"}},
         {"dt": 10000, "keep": True, "set": {"batt_w": 6150, "live_sp": 6000}, "expect": {"event": "R_RESPONSE_OK"}}]
    steps = [(5000, 4900, 5030), (4000, 3900, 4000), (3000, 2900, 2970), (2000, 2000, 2050), (1500, 1500, 1540)]
    for k, (plan_p, value, batt) in enumerate(steps):
        if k + 2 > n_changes_expected:
            t.append({"dt": 50000, "keep": True, "plan": {"p": [plan_p]},
                      "expect": {"action": "NONE", "state": "LEASED"}})
            t.append({"dt": 60000, "keep": True, "expect": {"action": "NONE", "state": "LEASED"}})
            return t
        t.append({"dt": 50000, "keep": True, "plan": {"p": [plan_p]},
                  "expect": {"action": "WRITE", "value": value, "changes": k + 2}})
        t.append({"dt": 1000, "pulse": {"op": "OK"}, "expect": {"state": "SETTLING"}})
        t.append({"dt": 10000, "keep": True, "set": {"batt_w": batt, "live_sp": value},
                  "expect": {"event": "R_RESPONSE_OK"}})
    t.append({"dt": 50000, "keep": True, "plan": {"p": [1000]}, "expect": {"action": "NONE", "changes": 6}})
    t.append({"dt": 60000, "keep": True, "expect": {"action": "NONE", "changes": 6, "writes_night": 6}})
    return t


vec("V61", "at most 6 changes per lease (a night ceiling of 12 so that the change budget is what binds)",
    fast_changes(6, 0), config=dict(CFG_FAST, night_write_ceiling=12))
# plan 0 W: 6000 -> 4000 -> 2000 (step cap) -> 0 clamps to the 500 W floor; then nothing below it
vec("V61b", "the floor: never below 500 W however low the plan", [
    dict(ARM), {"dt": 1000, "sample": True, "pulse": {"start": True}, "expect": {"action": "WRITE", "value": 6000}},
    {"dt": 2000, "set": {"arm": False}, "pulse": {"op": "OK"}},
    {"dt": 10000, "keep": True, "set": {"batt_w": 6150, "live_sp": 6000}, "expect": {"event": "R_RESPONSE_OK"}},
    {"dt": 50000, "keep": True, "plan": {"p": [0]}, "expect": {"action": "WRITE", "value": 4000}},
    {"dt": 1000, "pulse": {"op": "OK"}},
    {"dt": 10000, "keep": True, "set": {"batt_w": 4100, "live_sp": 4000}, "expect": {"event": "R_RESPONSE_OK"}},
    {"dt": 50000, "keep": True, "expect": {"action": "WRITE", "value": 2000}},
    {"dt": 1000, "pulse": {"op": "OK"}},
    {"dt": 10000, "keep": True, "set": {"batt_w": 2050, "live_sp": 2000}, "expect": {"event": "R_RESPONSE_OK"}},
    {"dt": 50000, "keep": True, "expect": {"action": "WRITE", "value": 500}},
    {"dt": 1000, "pulse": {"op": "OK"}},
    {"dt": 10000, "keep": True, "set": {"batt_w": 520, "live_sp": 500},
     "expect": {"event": "R_RESPONSE_OK", "gain_pct": 104}},
    {"dt": 50000, "keep": True, "expect": {"action": "NONE", "v": 500}},
    {"dt": 60000, "keep": True, "expect": {"action": "NONE", "v": 500}}], config=CFG_FAST)
# pre-lease 6950 (off the 100 W grid): START 6950*6000//8200 = 5085 -> 5100; plan 10000 -> 5100*10000//5300 = 9622,
# step cap 7100, ceiling 6950 rounded down to 6900
vec("V61c", "a pre-lease value off the 100 W grid: changes stay on the grid, the restore writes it exactly", [
    dict(ARM), {"dt": 1000, "sample": True, "pulse": {"start": True}, "expect": {"action": "WRITE", "value": 5100}},
    {"dt": 2000, "set": {"arm": False}, "pulse": {"op": "OK"}},
    {"dt": 10000, "keep": True, "set": {"batt_w": 5300, "live_sp": 5100}, "expect": {"event": "R_RESPONSE_OK"}},
    {"dt": 50000, "keep": True, "plan": {"p": [10000]}, "expect": {"action": "WRITE", "value": 6900}},
    {"dt": 1000, "pulse": {"op": "OK"}},
    {"dt": 1000, "keep": True, "set": {"live_sp": 6900}, "pulse": {"end": True},
     "expect": {"action": "RESTORE", "value": 6950}}], config=CFG_FAST, base_set={"live_sp": 6950})
vec("V62", "the night write ceiling reserves 3 restores: with 3 writes earlier tonight only 3 changes",
    [IDLE0] + fast_changes(3, 3), config=CFG_FAST, boot={"flags": 0, "night_id": NIGHT0, "writes_night": 3})

# ------------------------------------------------------------------------------------------------- lease ends
vec("V63", "END while the write is in flight is latched and acted on after the verified write",
    [dict(ARM),
     {"dt": 1000, "sample": True, "pulse": {"start": True}, "expect": {"action": "WRITE"}},
     {"dt": 1000, "set": {"arm": False}, "pulse": {"end": True}, "expect": {"state": "ADJUSTING", "action": "NONE"}},
     {"dt": 1000, "pulse": {"op": "OK"}, "expect": {"state": "SETTLING", "event": "R_WRITE_VERIFIED"}},
     {"dt": 1000, "expect": {"state": "RESTORING", "action": "RESTORE", "value": 8000, "event": "R_END",
                             "writes_night": 2, "restore_attempts": 1}}] + restore_ok("R_END", 2),
    final={"state": "IDLE", "record_flags": 4, "v": 0, "changes": 0})
vec("V64", "the deadline moves earlier with a new plan, never later; the lease ends there",
    prefix() + [{"dt": 60000, "keep": True, "plan": {"deadline": E0 + 16000},
                 "expect": {"lease_end": E0 + 14100, "action": "NONE"}},
                {"dt": 60000, "keep": True, "plan": {"deadline": E0 + 260},
                 "expect": {"lease_end": E0 + 260, "action": "NONE"}},
                {"dt": 60000, "keep": True,
                 "expect": {"action": "RESTORE", "event": "R_DEADLINE", "value": 8000}}] + restore_ok("R_DEADLINE", 2))
vec("V64b", "the deadline is inclusive: a tick exactly at the deadline ends the lease",
    prefix() + [{"dt": 60000, "keep": True, "plan": {"deadline": E0 + 203}, "expect": {"lease_end": E0 + 203}},
                {"dt": 60000, "keep": True, "expect": {"action": "RESTORE", "event": "R_DEADLINE"}}])
vec("V70b", "SOC above 100 % without a new frame ends the lease as invalid, not as target reached",
    prefix() + [{"dt": 1000, "cfg": True, "refresh": True, "set": {"soc": 1001},
                 "expect": {"action": "RESTORE", "event": "R_SOC_INVALID"}}])
vec("V80b", "inverter clock unknown", lease_end_with("R_INVERTER_CLOCK", {"dt": 1000, "keep": True,
                                                                         "set": {"inv_skew_s": -1}}))
vec("V88b", "a change answered 'nothing written' is a failed write", [
    dict(ARM), {"dt": 1000, "sample": True, "pulse": {"start": True}},
    {"dt": 2000, "set": {"arm": False}, "pulse": {"op": "OK_NOWRITE"},
     "expect": {"action": "RESTORE", "event": "R_WRITE_FAILED"}}])
# the prefix's last tick handed the plan over (age 0); without a hand-over it is lost at 21 min (age > 20 min)
vec("V65", "Home Assistant outage: no plan hand-over for 20 min ends the lease",
    prefix() + [{"repeat": 20, "dt": 60000, "sample": True, "cfg": True, "expect_all": {"action": "NONE"}},
                {"dt": 60000, "sample": True, "cfg": True,
                 "expect": {"action": "RESTORE", "event": "R_PLAN_LOST", "state": "RESTORING"}}])
vec("V66", "telemetry 91 s old ends the lease", lease_end_with("R_TELEMETRY_STALE", {"dt": 91000, "cfg": True,
                                                                                     "refresh": True}))
vec("V67", "telemetry invalid ends the lease", lease_end_with("R_TELEMETRY_STALE",
                                                              {"dt": 1000, "keep": True, "set": {"tel_ok": False}}))
vec("V68", "an SOC jump of 6 % ends the lease", lease_end_with("R_SOC_INVALID",
                                                               {"dt": 10000, "keep": True, "set": {"soc": 460}}))
vec("V69", "SOC falling 2.5 % below the lease maximum ends the lease",
    prefix() + [{"dt": 10000, "keep": True, "set": {"soc": 430}, "expect": {"action": "NONE"}},
                {"dt": 10000, "keep": True, "set": {"soc": 405},
                 "expect": {"action": "RESTORE", "event": "R_SOC_INVALID"}}])
vec("V70", "SOC unknown ends the lease", lease_end_with("R_SOC_INVALID", {"dt": 1000, "keep": True,
                                                                         "set": {"soc": -1}}))
vec("V71", "a plan that changes the target ends the lease", lease_end_with("R_PLAN_INVALID",
                                                                          {"dt": 1000, "keep": True,
                                                                           "plan": {"target": 90}}))
vec("V72", "an invalid plan ends the lease", lease_end_with("R_PLAN_INVALID", {"dt": 1000, "keep": True,
                                                                              "plan": {"valid": False}}))
vec("V73", "a configuration read 181 s old ends the lease", lease_end_with("R_CONFIG_STALE",
                                                                          {"dt": 181000, "sample": True,
                                                                           "refresh": True}))
vec("V74", "the slot no longer charges from the grid", lease_end_with("R_CONFIG_DRIFT", {"dt": 1000, "keep": True,
                                                                                       "set": {"slot_grid": False}}))
vec("V75", "the slot's SOC target changed", lease_end_with("R_CONFIG_DRIFT", {"dt": 1000, "keep": True,
                                                                             "set": {"slot_target": 90}}))
vec("V76", "Dump to Grid became active", lease_end_with("R_OTHER_ACTIVITY", {"dt": 1000, "keep": True,
                                                                            "set": {"other": 2}}))
vec("V77", "inverter or BMS fault", lease_end_with("R_INVERTER_FAULT", {"dt": 1000, "keep": True,
                                                                       "set": {"fault": True}}))
vec("V78", "clock-change night detected", lease_end_with("R_CLOCK_CHANGE", {"dt": 1000, "keep": True,
                                                                           "set": {"clock_change_night": True}}))
vec("V79", "wall clock lost", lease_end_with("R_CLOCK_INVALID", {"dt": 1000, "keep": True, "set": {"epoch": 0}}))
vec("V80", "inverter clock 200 s off", lease_end_with("R_INVERTER_CLOCK", {"dt": 1000, "keep": True,
                                                                          "set": {"inv_skew_s": 200}}))
vec("V81", "the owner ends it (END)", lease_end_with("R_END", {"dt": 1000, "keep": True, "pulse": {"end": True}}))
vec("V82", "a foreign slot power in a fresh read latches FAULT and writes nothing; ACK with a fresh read clears it",
    prefix() + [{"dt": 10000, "keep": True, "set": {"live_sp": 7000},
                 "expect": {"state": "FAULT", "event": "R_FOREIGN", "action": "NONE", "commit": True}},
                {"dt": 200000, "pulse": {"ack": True}, "expect": {"state": "FAULT", "event": "R_NONE"}},
                {"dt": 1000, "cfg": True, "pulse": {"ack": True}, "expect": {"state": "IDLE", "event": "R_ACKED"}}],
    final={"record_flags": 4})
vec("V83", "a configuration read OLDER than the verified write may show the old value (fence); a newer one may not",
    [dict(ARM),
     {"dt": 1000, "sample": True, "cfg": True, "pulse": {"start": True}, "expect": {"action": "WRITE"}},
     {"dt": 2000, "set": {"arm": False}, "pulse": {"op": "OK"}},
     {"dt": 10000, "sample": True, "expect": {"state": "SETTLING", "event": "R_NONE"}},
     {"dt": 10000, "sample": True, "cfg": True, "expect": {"state": "FAULT", "event": "R_FOREIGN"}}])
vec("V84", "the original value reappearing after a verified change is foreign too",
    prefix() + [{"dt": 10000, "keep": True, "set": {"live_sp": 8000}, "expect": {"state": "FAULT",
                                                                               "event": "R_FOREIGN"}}])
vec("V85", "target reached ends the lease", prefix() + [
    {"dt": 10000, "keep": True, "set": {"soc": 450}, "expect": {"action": "NONE"}},
    {"dt": 10000, "keep": True, "set": {"soc": 500},
     "expect": {"action": "RESTORE", "event": "R_TARGET_REACHED"}}] + restore_ok("R_TARGET_REACHED", 2),
    base_plan={"target": 50}, base_set={"slot_target": 50})
# guard from epoch E0 + 3180 (see the frame note): tick 52 after the prefix (E0 + 83 + 60k: k = 51 is x 3143, 3120 <
# 3125; k = 52 is x 3203, 3180 >= 3125)
vec("V86", "target guard: behind on time, the charge goes back to today's rate",
    prefix() + [{"repeat": 51, "dt": 60000, "keep": True, "expect_all": {"action": "NONE", "state": "LEASED"}},
                {"dt": 60000, "keep": True, "expect": {"action": "RESTORE", "event": "R_TARGET_GUARD"}}])
# watchdog = (E0+14100 - (E0+1)) * 1000 + 600000 = 14699000 ms from NOW0+1000: tick 244 after the prefix
vec("V87", "uptime watchdog: a frozen wall clock cannot hold the lease open",
    prefix() + [{"repeat": 243, "dt": 60000, "keep": True, "epoch_hold": True, "expect_all": {"action": "NONE"}},
                {"dt": 60000, "keep": True, "epoch_hold": True,
                 "expect": {"action": "RESTORE", "event": "R_WATCHDOG"}}])
vec("V88", "write failed: restore at once", [dict(ARM),
                                             {"dt": 1000, "sample": True, "pulse": {"start": True}},
                                             {"dt": 2000, "set": {"arm": False}, "pulse": {"op": "FAIL"},
                                              "expect": {"action": "RESTORE", "value": 8000,
                                                         "event": "R_WRITE_FAILED", "writes_night": 2}}]
    + restore_ok("R_WRITE_FAILED", 2))
vec("V89", "an operation without a result for 15 s is a failure", [
    dict(ARM), {"dt": 1000, "sample": True, "pulse": {"start": True}},
    {"dt": 14999, "set": {"arm": False}, "expect": {"action": "NONE", "state": "ADJUSTING"}},
    {"dt": 1, "expect": {"action": "RESTORE", "event": "R_OP_TIMEOUT"}},
    {"dt": 1000, "pulse": {"op": "OK_NOWRITE"}, "expect": {"state": "IDLE", "event": "R_RESTORED"}}])
vec("V90", "restore failing three times latches FAULT; the 30 s backoff is respected", [
    dict(ARM), {"dt": 1000, "sample": True, "pulse": {"start": True}},
    {"dt": 2000, "set": {"arm": False}, "pulse": {"op": "FAIL"}, "expect": {"action": "RESTORE", "restore_attempts": 1}},
    {"dt": 1000, "pulse": {"op": "FAIL"}, "expect": {"action": "NONE", "event": "R_RESTORE_RETRY"}},
    {"dt": 29999, "expect": {"action": "NONE"}},
    {"dt": 1, "expect": {"action": "RESTORE", "restore_attempts": 2, "writes_night": 3}},
    {"dt": 1000, "pulse": {"op": "FAIL"}, "expect": {"event": "R_RESTORE_RETRY"}},
    {"dt": 30000, "expect": {"action": "RESTORE", "restore_attempts": 3, "writes_night": 4}},
    {"dt": 1000, "pulse": {"op": "FAIL"}, "expect": {"state": "FAULT", "event": "R_RESTORE_FAILED", "commit": True}},
    {"dt": 60000, "expect": {"state": "FAULT", "action": "NONE"}}],
    final={"record_flags": 7, "last_reason": "R_RESTORE_FAILED"})
vec("V91", "the restore finds a foreign value: FAULT, nothing written", [
    dict(ARM), {"dt": 1000, "sample": True, "pulse": {"start": True}},
    {"dt": 2000, "set": {"arm": False}, "pulse": {"op": "FAIL"}, "expect": {"action": "RESTORE"}},
    {"dt": 1000, "pulse": {"op": "FOREIGN"}, "expect": {"state": "FAULT", "event": "R_FOREIGN"}}])
vec("V92", "the pre-write ownership read finds a foreign value: FAULT, nothing written", [
    dict(ARM), {"dt": 1000, "sample": True, "pulse": {"start": True}},
    {"dt": 2000, "pulse": {"op": "FOREIGN"}, "expect": {"state": "FAULT", "event": "R_FOREIGN", "action": "NONE"}}])
vec("V93", "an RTC correction defers a due change; the change follows when it ends",
    prefix() + [{"repeat": 28, "dt": 60000, "keep": True, "plan": {"p": [5000]}},
                {"dt": 60000, "keep": True, "set": {"rtc_busy": True}, "expect": {"action": "NONE"}},
                {"dt": 60000, "keep": True, "set": {"rtc_busy": False}, "expect": {"action": "WRITE", "value": 4900}}])
vec("V94", "an RTC correction for 5 min ends the lease; the restore waits for the bus",
    prefix() + [{"repeat": 5, "dt": 60000, "keep": True, "set": {"rtc_busy": True},
                 "expect_all": {"state": "LEASED", "action": "NONE"}},
                {"dt": 60000, "keep": True, "expect": {"state": "RESTORING", "event": "R_RTC_STUCK",
                                                       "action": "NONE"}},
                {"dt": 1000, "set": {"rtc_busy": False}, "expect": {"action": "RESTORE", "value": 8000}}])
vec("V95", "a busy write mutex defers the restore",
    prefix() + [{"dt": 1000, "keep": True, "set": {"mutex_busy": True}, "pulse": {"end": True},
                 "expect": {"state": "RESTORING", "event": "R_END", "action": "NONE"}},
                {"dt": 1000, "keep": True, "expect": {"action": "NONE"}},
                {"dt": 1000, "keep": True, "set": {"mutex_busy": False}, "expect": {"action": "RESTORE"}}])
vec("V96", "a busy write mutex defers a due change",
    prefix() + [{"repeat": 28, "dt": 60000, "keep": True, "plan": {"p": [5000]}},
                {"dt": 60000, "keep": True, "set": {"mutex_busy": True}, "expect": {"action": "NONE"}},
                {"dt": 1000, "keep": True, "set": {"mutex_busy": False}, "expect": {"action": "WRITE"}}])

# ------------------------------------------------------------------------------------------------- the response
vec("V97", "wrong direction: the charge rose 500 W after a step down",
    prefix(8700, {"event": "R_WRONG_DIRECTION", "action": "RESTORE", "value": 8000, "state": "RESTORING"}))
# 8150 W after the step: act -50, needs 30 % of 2040 -> weak (1); after the dwell 6000*6000//8150 = 4417 -> 4400;
# still 8150: act 0, weak (2) -> NO RESPONSE
vec("V98", "no response twice below the taper ends the lease",
    prefix(8150, {"event": "R_RESPONSE_WEAK", "ineffective": 1, "state": "LEASED", "p_ref": 8150, "gain_pct": 102})
    + [{"repeat": 28, "dt": 60000, "keep": True, "expect_all": {"action": "NONE"}},
       {"dt": 60000, "keep": True, "expect": {"action": "WRITE", "value": 4400}},
       {"dt": 1000, "pulse": {"op": "OK"}},
       {"repeat": 7, "dt": 10000, "keep": True, "set": {"live_sp": 4400}},
       {"dt": 10000, "keep": True, "expect": {"event": "R_NO_RESPONSE", "action": "RESTORE", "value": 8000}}])
vec("V99", "above the taper a weak response is the BMS: hold, no further changes",
    prefix(8150, {"event": "R_BMS_LIMITED", "bms_limited": True, "state": "LEASED", "ineffective": 0})
    + [{"repeat": 31, "dt": 60000, "keep": True, "expect_all": {"action": "NONE", "state": "LEASED"}}],
    base_set={"soc": 900})
vec("V100", "implausible gain: 2000 W at a 6000 setpoint (33 %)",
    prefix(2000, {"event": "R_IMPLAUSIBLE_GAIN", "action": "RESTORE", "state": "RESTORING"}))
vec("V101", "runaway: three samples above 8200*115//100 + 500 = 9930 W",
    [dict(ARM), {"dt": 1000, "sample": True, "pulse": {"start": True}},
     {"dt": 2000, "set": {"arm": False}, "pulse": {"op": "OK"}},
     {"repeat": 2, "dt": 10000, "keep": True, "set": {"batt_w": 9931, "live_sp": 6000},
      "expect_all": {"action": "NONE", "state": "SETTLING"}},
     {"dt": 10000, "keep": True, "expect": {"event": "R_RUNAWAY", "action": "RESTORE"}}])
vec("V102", "9930 W exactly is not a runaway sample",
    [dict(ARM), {"dt": 1000, "sample": True, "pulse": {"start": True}},
     {"dt": 2000, "set": {"arm": False}, "pulse": {"op": "OK"}},
     {"repeat": 4, "dt": 10000, "keep": True, "set": {"batt_w": 9930, "live_sp": 6000},
      "expect_all": {"action": "NONE", "state": "SETTLING"}}])
vec("V103", "the charge stopped (three samples under 100 W below the taper)",
    [dict(ARM), {"dt": 1000, "sample": True, "pulse": {"start": True}},
     {"dt": 2000, "set": {"arm": False}, "pulse": {"op": "OK"}},
     {"repeat": 2, "dt": 10000, "keep": True, "set": {"batt_w": 50, "live_sp": 6000},
      "expect_all": {"action": "NONE"}},
     {"dt": 10000, "keep": True, "expect": {"event": "R_CHARGE_STOPPED", "action": "RESTORE"}}])
vec("V104", "a repeated telemetry frame (same sequence) is not a new sample",
    [dict(ARM), {"dt": 1000, "sample": True, "pulse": {"start": True}},
     {"dt": 2000, "set": {"arm": False}, "pulse": {"op": "OK"}},
     {"dt": 10000, "keep": True, "set": {"batt_w": 9931, "live_sp": 6000}},
     {"repeat": 5, "dt": 1000, "cfg": True, "refresh": True, "expect_all": {"action": "NONE", "state": "SETTLING"}}])

# ------------------------------------------------------------------------------------------------- restarts and records
vec("V105", "restart during the lease: the boot restores the pre-lease value",
    prefix() + [{"dt": 1000, "keep": True, "reboot": {"corrupt": -1},
                 "expect": {"state": "RESTORING", "action": "RESTORE", "value": 8000, "event": "R_RESTORE_REQUESTED",
                            "writes_night": 2, "restore_attempts": 1, "last_reason": "R_BOOT_RECOVERY"}},
                {"dt": 1000, "pulse": {"op": "OK_NOWRITE"}, "expect": {"state": "IDLE", "event": "R_RESTORED"}}],
    final={"record_flags": 4})
vec("V106", "restart while the START write is in flight", [
    dict(ARM), {"dt": 1000, "sample": True, "pulse": {"start": True}, "expect": {"action": "WRITE"}},
    {"dt": 1000, "set": {"arm": False}, "reboot": {"corrupt": -1},
     "expect": {"action": "RESTORE", "value": 8000, "p": 6000, "v": 8000}}])
vec("V107", "a corrupt record at boot latches FAULT (no automatic write)",
    prefix() + [{"dt": 1000, "keep": True, "reboot": {"corrupt": 7},
                 "expect": {"state": "FAULT", "action": "NONE", "last_reason": "R_RECORD_CORRUPT"}},
                {"dt": 1000, "cfg": True, "pulse": {"ack": True}, "expect": {"state": "IDLE", "event": "R_ACKED"}}])
vec("V108", "a record whose restores are exhausted boots into FAULT",
    [{"dt": 0, "expect": {"state": "FAULT", "action": "NONE", "last_reason": "R_RESTORE_FAILED"}}],
    boot={"flags": 5, "slot": 1, "original": 8000, "v": 6000, "p": 6000, "night_id": NIGHT0, "writes_night": 4,
          "changes": 1, "restore_attempts": 3, "lease_end": E0 + 14100, "reason": 79})
vec("V109", "a fault record boots into FAULT with its reason",
    [{"dt": 0, "expect": {"state": "FAULT", "last_reason": "R_FOREIGN"}},
     {"dt": 1000, "set": {"arm": True}, "pulse": {"start": True}, "expect": {"state": "FAULT", "action": "NONE"}}],
    boot={"flags": 7, "slot": 1, "original": 8000, "v": 6000, "p": 6000, "night_id": NIGHT0, "writes_night": 2,
          "changes": 1, "restore_attempts": 0, "lease_end": E0 + 14100, "reason": 100})
vec("V110", "one lease per night; the next night may lease again",
    lease_end_with("R_END", {"dt": 1000, "keep": True, "pulse": {"end": True}})
    + [{"dt": 1000, "set": {"arm": True}, "expect": {"state": "ARMED"}},
       {"dt": 1000, "keep": True, "set": {"batt_w": 8200, "live_sp": 8000}, "pulse": {"start": True},
        "expect": {"state": "IDLE", "event": "R_REFUSE_NIGHT_USED"}},
       {"dt": 1000, "set": {"arm": False}},
       {"dt": 1000, "set": {"arm": True}, "expect": {"state": "ARMED"}},
       {"dt": 1000, "keep": True, "set": {"night_id": NIGHT0 + 1}, "pulse": {"start": True},
        "expect": {"state": "ADJUSTING", "action": "WRITE", "writes_night": 1}}])


# ================================================================================ revision 2 (review findings)
# ---- B1: the restore budget counts only ANSWERED failures; the restore waits for the inverter to answer
def silent_for(total_ms: int, step_ms: int = 10000) -> list:
    """The inverter answers nothing for total_ms (no frame, no configuration read), in ticks of step_ms."""
    out, left = [], total_ms
    while left > 0:
        d = min(step_ms, left)
        out.append({"dt": d, "silent": True, "expect": {"state": "RESTORING", "action": "NONE", "restore_attempts": 0}})
        left -= d
    return out


# END -> RESTORE (seq 2); NO_ANSWER gives back the attempt and the write; 30 s backoff; four unanswered restores in a row
# (revision 1 latched FAULT RESTORE_FAILED after three), then the inverter answers and the restore lands.
t = prefix() + [{"dt": 1000, "keep": True, "pulse": {"end": True},
                 "expect": {"state": "RESTORING", "action": "RESTORE", "value": 8000, "seq": 2, "event": "R_END",
                            "restore_attempts": 1, "writes_night": 2}},
                {"dt": 1000, "pulse": {"op": "NO_ANSWER"},
                 "expect": {"state": "RESTORING", "action": "NONE", "event": "R_RESTORE_UNANSWERED",
                            "restore_attempts": 0, "writes_night": 1, "commit": True}},
                {"dt": 29999, "expect": {"action": "NONE"}},
                {"dt": 1, "expect": {"action": "RESTORE", "seq": 3, "restore_attempts": 1, "writes_night": 2}}]
for k in (4, 5, 6):
    t += [{"dt": 1000, "pulse": {"op": "NO_ANSWER"}, "expect": {"event": "R_RESTORE_UNANSWERED", "restore_attempts": 0,
                                                               "state": "RESTORING"}},
          {"dt": 30000, "expect": {"action": "RESTORE", "seq": k, "restore_attempts": 1, "writes_night": 2}}]
t += [{"dt": 1000, "pulse": {"op": "OK"}, "expect": {"state": "IDLE", "event": "R_RESTORED", "writes_night": 2}}]
vec("V120", "an unanswered restore uses no attempt: retried after the backoff for as long as it takes, then restored",
    t, final={"state": "IDLE", "record_flags": 4})

# Modbus down when a guard ends the lease: 91 s without a frame -> TELEMETRY_STALE; no restore is emitted while the
# inverter has not answered within 30 s (revision 1 emitted at once and spent its attempts on the outage).
for vid, mins in (("V121", 2), ("V122", 5), ("V123", 10)):
    t = prefix() + [{"dt": 91000, "silent": True,
                     "expect": {"state": "RESTORING", "event": "R_TELEMETRY_STALE", "action": "NONE",
                                "restore_attempts": 0}}]
    t += silent_for(mins * 60000 - 91000)
    t += [{"dt": 1000, "keep": True, "expect": {"action": "RESTORE", "value": 8000, "seq": 2, "restore_attempts": 1,
                                                "writes_night": 2}},
          {"dt": 1000, "pulse": {"op": "OK"}, "expect": {"state": "IDLE", "event": "R_RESTORED"}}]
    vec(vid, f"Modbus down {mins} min at a guard: the restore waits for the inverter, no attempt is spent", t,
        final={"state": "IDLE", "record_flags": 4})

# dongle and inverter boot together: the boot restore waits for the first answered read since this boot
for vid, mins in (("V124", 2), ("V125", 5), ("V126", 10)):
    t = prefix() + [{"dt": 1000, "silent": True, "reboot": {"corrupt": -1, "rx_never": True},
                     "expect": {"state": "RESTORING", "action": "NONE", "last_reason": "R_BOOT_RECOVERY",
                                "restore_attempts": 0, "writes_night": 1}}]
    t += silent_for(mins * 60000 - 1000)
    t += [{"dt": 1000, "keep": True, "expect": {"action": "RESTORE", "value": 8000, "seq": 1, "restore_attempts": 1,
                                                "writes_night": 2}},
          {"dt": 1000, "pulse": {"op": "OK_NOWRITE"}, "expect": {"state": "IDLE", "event": "R_RESTORED"}}]
    vec(vid, f"dongle and inverter boot together, the inverter answers after {mins} min: the boot restore waits", t,
        final={"state": "IDLE", "record_flags": 4})

# the inverter clamps the START write (6000 read back as 5000): the readback under the GRC's own lock is owned (q),
# committed before the restore (record flags ACTIVE | NIGHT_USED | READBACK = 13) and restored over
vec("V127", "the inverter clamps a write: the readback is owned, recorded and restored over (no FOREIGN fault)", [
    dict(ARM), {"dt": 1000, "sample": True, "pulse": {"start": True}, "expect": {"action": "WRITE", "value": 6000}},
    {"dt": 2000, "set": {"arm": False}, "pulse": {"op": "FAIL", "op_value": 5000},
     "expect": {"state": "RESTORING", "action": "RESTORE", "value": 8000, "seq": 2, "event": "R_READBACK_MISMATCH",
                "q": 5000, "restore_attempts": 1, "writes_night": 2, "record_flags": 13, "commit": True}},
    {"dt": 1000, "pulse": {"op": "OK"}, "expect": {"state": "IDLE", "event": "R_RESTORED", "q": -1}}],
    final={"record_flags": 4})
vec("V128", "a clamped write, then a restart before the restore: the boot keeps the owned readback", [
    dict(ARM), {"dt": 1000, "sample": True, "pulse": {"start": True}},
    {"dt": 2000, "set": {"arm": False}, "pulse": {"op": "FAIL", "op_value": 5000},
     "expect": {"action": "RESTORE", "q": 5000}},
    {"dt": 1000, "reboot": {"corrupt": -1},
     "expect": {"state": "RESTORING", "action": "RESTORE", "value": 8000, "seq": 1, "q": 5000, "restore_attempts": 2,
                "writes_night": 3, "last_reason": "R_BOOT_RECOVERY"}},
    {"dt": 1000, "pulse": {"op": "OK"}, "expect": {"state": "IDLE", "event": "R_RESTORED"}}])
vec("V129", "the restore's own readback differs: owned too, the restore is retried and lands", prefix() + [
    {"dt": 1000, "keep": True, "pulse": {"end": True}, "expect": {"action": "RESTORE", "restore_attempts": 1}},
    {"dt": 1000, "pulse": {"op": "FAIL", "op_value": 7500},
     "expect": {"state": "RESTORING", "event": "R_RESTORE_RETRY", "q": 7500, "restore_attempts": 1}},
    {"dt": 30000, "expect": {"action": "RESTORE", "seq": 3, "restore_attempts": 2, "writes_night": 3}},
    {"dt": 1000, "pulse": {"op": "OK"}, "expect": {"state": "IDLE", "event": "R_RESTORED"}}])
# V90's three answered failures, then the owner's Restore original: one classified restore (writes 4 -> 5), then IDLE
vec("V130", "Restore original after three answered restore failures: one classified restore, then IDLE", [
    dict(ARM), {"dt": 1000, "sample": True, "pulse": {"start": True}},
    {"dt": 2000, "set": {"arm": False}, "pulse": {"op": "FAIL"}, "expect": {"action": "RESTORE", "restore_attempts": 1}},
    {"dt": 1000, "pulse": {"op": "FAIL"}, "expect": {"event": "R_RESTORE_RETRY"}},
    {"dt": 30000, "expect": {"action": "RESTORE", "restore_attempts": 2}},
    {"dt": 1000, "pulse": {"op": "FAIL"}, "expect": {"event": "R_RESTORE_RETRY"}},
    {"dt": 30000, "expect": {"action": "RESTORE", "restore_attempts": 3, "writes_night": 4}},
    {"dt": 1000, "pulse": {"op": "FAIL"}, "expect": {"state": "FAULT", "event": "R_RESTORE_FAILED"}},
    {"dt": 60000, "expect": {"state": "FAULT", "action": "NONE", "record_flags": 7}},
    {"dt": 1000, "pulse": {"restore_req": True},
     "expect": {"state": "FAULT", "action": "RESTORE", "value": 8000, "seq": 5, "event": "R_OWNER_RESTORE",
                "writes_night": 5, "commit": True}},
    {"dt": 1000, "pulse": {"op": "OK"},
     "expect": {"state": "IDLE", "event": "R_RESTORED", "last_reason": "R_OWNER_RESTORE", "commit": True}}],
    final={"state": "IDLE", "record_flags": 4, "v": 0})
vec("V131", "Restore original is refused when the original is not known (a corrupt record)", prefix() + [
    {"dt": 1000, "keep": True, "reboot": {"corrupt": 7}, "expect": {"state": "FAULT", "last_reason": "R_RECORD_CORRUPT"}},
    {"dt": 1000, "keep": True, "pulse": {"restore_req": True},
     "expect": {"state": "FAULT", "action": "NONE", "event": "R_REFUSE_RESTORE"}}])
vec("V132", "Restore original on a foreign value writes nothing: FAULT stays", prefix() + [
    {"dt": 10000, "keep": True, "set": {"live_sp": 7000}, "expect": {"state": "FAULT", "event": "R_FOREIGN"}},
    {"dt": 1000, "keep": True, "pulse": {"restore_req": True}, "expect": {"action": "RESTORE", "value": 8000}},
    {"dt": 1000, "pulse": {"op": "FOREIGN"},
     "expect": {"state": "FAULT", "event": "R_FOREIGN", "last_reason": "R_FOREIGN", "action": "NONE"}}],
    final={"record_flags": 7})
# a FAULT record with 9 writes tonight: refused while the inverter is silent or the bus busy; an unanswered owner
# restore gives its write back (a free retry); an answered failure keeps the FAULT; the tenth write (the owner's
# reserved one, revision 3: ceiling 10 = 6 changes + 3 restores + 1 owner restore) is the last one the night allows
BOOT_F9 = {"flags": 7, "slot": 1, "original": 8000, "v": 6000, "p": 6000, "night_id": NIGHT0, "writes_night": 9,
           "changes": 6, "restore_attempts": 3, "lease_end": E0 + 14100, "reason": 101}
vec("V133", "Restore original: refused on a silent inverter or a busy bus, bounded by the night's write ceiling", [
    {"dt": 0, "expect": {"state": "FAULT", "last_reason": "R_RESTORE_FAILED"}},
    {"dt": 31000, "silent": True, "pulse": {"restore_req": True}, "expect": {"action": "NONE",
                                                                            "event": "R_REFUSE_RESTORE"}},
    {"dt": 1000, "set": {"mutex_busy": True}, "pulse": {"restore_req": True},
     "expect": {"action": "NONE", "event": "R_REFUSE_RESTORE"}},
    {"dt": 1000, "set": {"mutex_busy": False}, "pulse": {"restore_req": True},
     "expect": {"action": "RESTORE", "value": 8000, "seq": 1, "out_slot": 1, "writes_night": 10}},
    {"dt": 1000, "pulse": {"op": "NO_ANSWER"}, "expect": {"state": "FAULT", "event": "R_RESTORE_UNANSWERED",
                                                        "writes_night": 9, "free_night": 1}},
    {"dt": 1000, "pulse": {"restore_req": True}, "expect": {"action": "RESTORE", "seq": 2, "writes_night": 10}},
    {"dt": 1000, "pulse": {"op": "FAIL", "op_value": 6000},
     "expect": {"state": "FAULT", "event": "R_RESTORE_FAILED", "q": -1, "writes_night": 10}},
    {"dt": 1000, "pulse": {"restore_req": True}, "expect": {"action": "NONE", "event": "R_REFUSE_RESTORE"}}],
    boot=BOOT_F9)

# ---- M2: results are tagged with the action's sequence number and kind
# the review's race: the WRITE (seq 1) times out, the RESTORE (seq 2) is emitted, the integration could not run it
# (DEFERRED: no attempt), then the WRITE's late OK arrives: stale, never taken as the restore's success
vec("V140", "a late WRITE result after its timeout is never taken as the restore's (sequence and kind)", [
    dict(ARM), {"dt": 1000, "sample": True, "pulse": {"start": True}, "expect": {"action": "WRITE", "seq": 1}},
    {"dt": 15000, "set": {"arm": False},
     "expect": {"state": "RESTORING", "action": "RESTORE", "seq": 2, "event": "R_OP_TIMEOUT", "restore_attempts": 1,
                "writes_night": 2}},
    {"dt": 1000, "pulse": {"op": "DEFERRED"},
     "expect": {"state": "RESTORING", "event": "R_RESTORE_DEFERRED", "restore_attempts": 0, "writes_night": 1}},
    {"dt": 1000, "pulse": {"op": "OK", "op_seq": 1, "op_kind": "WRITE"},
     "expect": {"state": "RESTORING", "event": "R_STALE_RESULT", "action": "NONE"}},
    {"dt": 1000, "pulse": {"op": "DEFERRED", "op_seq": 2, "op_kind": "RESTORE"},
     "expect": {"state": "RESTORING", "event": "R_STALE_RESULT", "action": "NONE", "restore_attempts": 0}},
    {"dt": 27000, "expect": {"action": "NONE", "state": "RESTORING"}},
    {"dt": 1000, "expect": {"action": "RESTORE", "seq": 3, "restore_attempts": 1}},
    {"dt": 1000, "pulse": {"op": "OK"}, "expect": {"state": "IDLE", "event": "R_RESTORED"}}])
# the same race when the integration drops the RESTORE without a word: the WRITE's late OK (seq 1, kind WRITE) arrives
# while the RESTORE (seq 2) is outstanding and is not its result; the RESTORE's own result is
vec("V144", "a late WRITE result while the restore is outstanding is not the restore's result", [
    dict(ARM), {"dt": 1000, "sample": True, "pulse": {"start": True}},
    {"dt": 15000, "set": {"arm": False}, "expect": {"action": "RESTORE", "seq": 2, "event": "R_OP_TIMEOUT"}},
    {"dt": 1000, "pulse": {"op": "OK", "op_seq": 1, "op_kind": "WRITE"},
     "expect": {"state": "RESTORING", "event": "R_STALE_RESULT", "action": "NONE", "restore_attempts": 1}},
    {"dt": 1000, "pulse": {"op": "OK_NOWRITE"}, "expect": {"state": "IDLE", "event": "R_RESTORED"}}])
vec("V141", "a result with the wrong sequence or the wrong kind is ignored", [
    dict(ARM), {"dt": 1000, "sample": True, "pulse": {"start": True}, "expect": {"action": "WRITE", "seq": 1}},
    {"dt": 1000, "set": {"arm": False}, "pulse": {"op": "OK", "op_seq": 7},
     "expect": {"state": "ADJUSTING", "event": "R_STALE_RESULT", "action": "NONE", "v": 8000}},
    {"dt": 1000, "pulse": {"op": "OK", "op_kind": "RESTORE"},
     "expect": {"state": "ADJUSTING", "event": "R_STALE_RESULT", "v": 8000}},
    {"dt": 1000, "pulse": {"op": "OK"}, "expect": {"state": "SETTLING", "event": "R_WRITE_VERIFIED", "v": 6000}}])
vec("V142", "a change the integration could not run (DEFERRED) ends the lease; nothing was written", [
    dict(ARM), {"dt": 1000, "sample": True, "pulse": {"start": True}},
    {"dt": 1000, "set": {"arm": False}, "pulse": {"op": "DEFERRED"},
     "expect": {"state": "RESTORING", "action": "RESTORE", "seq": 2, "event": "R_WRITE_DEFERRED"}},
    {"dt": 1000, "pulse": {"op": "OK_NOWRITE"}, "expect": {"state": "IDLE", "event": "R_RESTORED"}}])
vec("V143", "a change the inverter did not answer ends the lease", [
    dict(ARM), {"dt": 1000, "sample": True, "pulse": {"start": True}},
    {"dt": 1000, "set": {"arm": False}, "pulse": {"op": "NO_ANSWER"},
     "expect": {"state": "RESTORING", "action": "RESTORE", "event": "R_WRITE_UNANSWERED"}}])

# ---- M3: the firmware no longer trusts the plan beyond its own bounds
# the slot's own end at START (x = 1) is E0 + 17641; the plan's window end must lie within 120 s of it
vec("V150", "START refused: the plan's window end is 5 min later than the slot's own end",
    refuse("R_REFUSE_SLOT", {"plan": {"window_end": E0 + 18000}}))
vec("V151", "START refused: the review's bad plan (p 0, capacity 1 kWh, taper 100, window end a day late)",
    refuse("R_REFUSE_SLOT", {"plan": {"p": [0], "capacity_wh": 1000, "taper": 100, "window_end": E0 + 17700 + 86400}}))
vec("V152", "START accepted: the plan's window end 119 s after the slot's own end",
    [dict(ARM), {"dt": 1000, "sample": True, "pulse": {"start": True}, "plan": {"window_end": E0 + 17760},
                 "expect": {"state": "ADJUSTING", "action": "WRITE", "value": 6000}}])
vec("V153", "START refused: the plan's window end 121 s before the slot's own end",
    refuse("R_REFUSE_SLOT", {"plan": {"window_end": E0 + 17520}}))
vec("V154", "a plan whose window end moves a day ends the lease", lease_end_with(
    "R_PLAN_WINDOW", {"dt": 1000, "keep": True, "plan": {"window_end": E0 + 17700 + 86400}}))
# the guard uses the slot's own end even when the plan claims 119 s more: it trips at tick 52 as in V86 (with the
# plan's window end it would wait until x + 13915 >= 17160, tick 53)
vec("V155", "the target guard uses the slot's own end, not the plan's window end",
    prefix() + [{"repeat": 51, "dt": 60000, "keep": True, "expect_all": {"action": "NONE", "state": "LEASED"}},
                {"dt": 60000, "keep": True, "expect": {"action": "RESTORE", "event": "R_TARGET_GUARD"}}],
    base_plan={"window_end": E0 + 17760})
# a later plan claiming 20 kWh never lowers the guard's 30 kWh: still tick 52 (with 20 kWh: t_need 8676 s, x >= 7500)
vec("V156", "a lower capacity in a later plan never lowers the guard's capacity",
    prefix() + [{"dt": 60000, "keep": True, "plan": {"capacity_wh": 20000}, "expect": {"action": "NONE"}},
                {"repeat": 50, "dt": 60000, "keep": True, "expect_all": {"action": "NONE", "state": "LEASED"}},
                {"dt": 60000, "keep": True, "expect": {"action": "RESTORE", "event": "R_TARGET_GUARD",
                                                       "capacity_wh": 30000}}])
# a plan claiming 1 kWh is guarded as the firmware floor 20 kWh: plateau 10000 Wh -> 5164 s, tail 2000 Wh -> 3512 s,
# t_need 8676: trips once x - x % 60 >= 7464: k = 123 is x 7463 (7440, no), k = 124 is x 7523 (7500, trips)
vec("V157", "the firmware capacity floor: a plan claiming 1 kWh is guarded as 20 kWh",
    prefix() + [{"repeat": 123, "dt": 60000, "keep": True, "expect_all": {"action": "NONE", "state": "LEASED",
                                                                         "capacity_wh": 20000}},
                {"dt": 60000, "keep": True, "expect": {"action": "RESTORE", "event": "R_TARGET_GUARD"}}],
    base_plan={"capacity_wh": 1000})
# START at 4000 W slot power (4100 W realised): with the 20 kWh floor at SOC 40 %: plateau 10000 Wh at 3485 W -> 10329 s,
# tail 2000 Wh at 1025 W -> 7024 s; 1 + 17353 + 900 >= 17041: refused (with 1 kWh it would start)
vec("V157b", "START refused: the capacity floor applies to a plan claiming 1 kWh",
    refuse("R_REFUSE_TARGET_AT_RISK", {"set": {"live_sp": 4000, "batt_w": 4100}, "plan": {"capacity_wh": 1000}}))
# SOC 46.1 % at 4100 W: plateau 439*20 = 8780 Wh -> 9069 s, tail 7024 s, t_need 16093: START (x = 1): 16994 < 17041;
# one minute later (x = 60): 17053 >= 17040, the very first guard tick of the lease trips (it must already use 20 kWh)
vec("V157c", "the capacity floor holds from the lease's first tick", [
    dict(ARM),
    {"dt": 1000, "sample": True, "pulse": {"start": True}, "set": {"soc": 461, "live_sp": 4000, "batt_w": 4100},
     "plan": {"capacity_wh": 1000}, "expect": {"state": "LEASED", "action": "NONE", "capacity_wh": 20000}},
    {"dt": 59000, "keep": True, "expect": {"action": "RESTORE", "value": 4000, "event": "R_TARGET_GUARD"}}])
# a plan taper of 100 is guarded with the 95 % knee: plateau 550*30 = 16500 Wh -> 8522 s, tail 1500 Wh -> 2634 s,
# t_need 11156: trips once x - x % 60 >= 4984: k = 82 is x 5003 (4980, no), k = 83 is x 5063 (5040, trips); with
# the plan's 100 % knee it would wait until x - x % 60 >= 6844
vec("V158", "the target guard caps the plan's taper knee at 95 %",
    prefix() + [{"repeat": 82, "dt": 60000, "keep": True, "expect_all": {"action": "NONE", "state": "LEASED"}},
                {"dt": 60000, "keep": True, "expect": {"action": "RESTORE", "event": "R_TARGET_GUARD"}}],
    base_plan={"taper": 100})
# the plan drops the owner ceiling to 500 W: after the dwell 6000 -> 4000 (one step), not 500
vec("V159", "an owner ceiling far below the present value is approached in 2000 W steps",
    prefix() + [{"dt": 60000, "keep": True, "plan": {"ceiling_w": 500}, "expect": {"action": "NONE"}},
                {"repeat": 27, "dt": 60000, "keep": True, "expect_all": {"action": "NONE"}},
                {"dt": 60000, "keep": True, "expect": {"action": "WRITE", "value": 4000, "changes": 2}}])

# ---- M4: a direct grid-loss input ends the lease and restores at once
vec("V160", "START refused: the grid is not connected", refuse("R_REFUSE_GRID", {"set": {"grid_ok": False}}))
vec("V161", "grid lost during the lease: the restore is emitted in the same tick",
    lease_end_with("R_GRID_LOSS", {"dt": 1000, "keep": True, "set": {"grid_ok": False}}))
vec("V162", "grid lost while a write is in flight: latched, acted on at the verified result, no settle", [
    dict(ARM), {"dt": 1000, "sample": True, "pulse": {"start": True}},
    {"dt": 1000, "set": {"arm": False, "grid_ok": False}, "expect": {"state": "ADJUSTING", "action": "NONE"}},
    {"dt": 1000, "set": {"grid_ok": True}, "pulse": {"op": "OK"},
     "expect": {"state": "RESTORING", "action": "RESTORE", "value": 8000, "seq": 2, "event": "R_GRID_LOSS",
                "v": 6000}},
    {"dt": 1000, "pulse": {"op": "OK"}, "expect": {"state": "IDLE", "event": "R_RESTORED",
                                                  "last_reason": "R_GRID_LOSS"}}])
vec("V163", "grid loss outranks END", prefix() + [
    {"dt": 1000, "keep": True, "set": {"grid_ok": False}, "pulse": {"end": True},
     "expect": {"action": "RESTORE", "event": "R_GRID_LOSS"}}])

# ---- M5: the restore operation timeout and a slot across midnight
vec("V170", "a restore without any result: timed out, retried after the backoff, the third timeout latches FAULT",
    prefix() + [{"dt": 1000, "keep": True, "pulse": {"end": True}, "expect": {"action": "RESTORE", "seq": 2,
                                                                           "restore_attempts": 1, "writes_night": 2}},
                {"dt": 14999, "expect": {"state": "RESTORING", "action": "NONE", "event": "R_NONE"}},
                {"dt": 1, "expect": {"state": "RESTORING", "action": "NONE", "event": "R_RESTORE_RETRY",
                                     "restore_attempts": 1}},
                {"dt": 29999, "expect": {"action": "NONE"}},
                {"dt": 1, "expect": {"action": "RESTORE", "seq": 3, "restore_attempts": 2, "writes_night": 3}},
                {"dt": 15000, "expect": {"event": "R_RESTORE_RETRY"}},
                {"dt": 30000, "expect": {"action": "RESTORE", "seq": 4, "restore_attempts": 3, "writes_night": 4}},
                {"dt": 15000, "expect": {"state": "FAULT", "event": "R_RESTORE_FAILED", "commit": True}}],
    final={"record_flags": 7, "last_reason": "R_RESTORE_FAILED"})
# slot 23:30-05:30, START at 23:35 (E0 - 3600 + 1, local 1415): slot end = epoch + mod1440(330 - 1415) * 60 - 60 =
# E0 - 3599 + 355 * 60 - 60 = E0 + 17641; deadline E0 + 17400, so the lease end comes from the slot: E0 + 17041. The
# prefix ticks have x % 60 >= 3 and the later ones x % 60 = 23, so it never moves. Midnight passes at tick 24 after
# the prefix (x = 83 + 60k >= 1500); the dwell change at tick 29 is V52's 4900.
vec("V171", "a slot across midnight: START at 23:35, guards past 00:00, the lease end from the slot's own end",
    prefix(lease_end=E0 + 17041)
    + [{"repeat": 28, "dt": 60000, "keep": True, "plan": {"p": [5000]},
        "expect_all": {"action": "NONE", "state": "LEASED", "lease_end": E0 + 17041}},
       {"dt": 60000, "keep": True, "expect": {"action": "WRITE", "value": 4900, "state": "ADJUSTING",
                                              "lease_end": E0 + 17041}},
       {"dt": 1000, "pulse": {"op": "OK"}, "expect": {"state": "SETTLING"}},
       {"dt": 1000, "keep": True, "pulse": {"end": True}, "expect": {"action": "RESTORE", "value": 8000,
                                                                     "event": "R_END"}}],
    epoch_offset=-3600, base_set={"slot_start_min": 1410}, base_plan={"deadline": E0 + 17400, "t": [E0 - 3660]})
# START at x = 59 (slot end E0 + 17699, lease end E0 + 17099); a minute later x = 60 gives E0 + 17640 - 600 = E0 + 17040
vec("V172", "the lease end follows the slot's own end on every tick, earlier only", [
    dict(ARM),
    {"dt": 59000, "sample": True, "pulse": {"start": True},
     "expect": {"state": "LEASED", "action": "NONE", "lease_end": E0 + 17099}},
    {"dt": 1000, "keep": True, "expect": {"state": "LEASED", "lease_end": E0 + 17040}}],
    base_plan={"p": [8000], "deadline": E0 + 17400})

# ================================================================================ revision 3 (confirmation review)
# ---- MAJOR 1: RESTORING is bounded without spending the 3 answered attempts: at most restore_free_max (10) unanswered
# or deferred restores a night, and at most restore_stall_ms (10 min) of restore-owed time while the inverter answers
# (each tick adds the time since the previous one, at most rx_fresh_ms = 30 s); then FAULT RESTORE_STALLED (alert,
# editor never blocked, Restore original available)
t = prefix() + [{"dt": 1000, "keep": True, "pulse": {"end": True},
                 "expect": {"state": "RESTORING", "action": "RESTORE", "value": 8000, "seq": 2, "out_slot": 1,
                            "event": "R_END", "restore_attempts": 1, "writes_night": 2}}]
for k in range(1, 10):
    t += [{"dt": 1000, "pulse": {"op": "DEFERRED"},
           "expect": {"state": "RESTORING", "action": "NONE", "event": "R_RESTORE_DEFERRED", "restore_attempts": 0,
                      "writes_night": 1, "free_night": k, "commit": True}},
          {"dt": 30000, "expect": {"action": "RESTORE", "seq": k + 2, "restore_attempts": 1, "writes_night": 2}}]
t += [{"dt": 1000, "pulse": {"op": "DEFERRED"},
       "expect": {"state": "FAULT", "action": "NONE", "event": "R_RESTORE_STALLED", "restore_attempts": 0,
                  "writes_night": 1, "free_night": 10, "commit": True, "record_flags": 7}},
      {"dt": 1000, "pulse": {"restore_req": True},
       "expect": {"state": "FAULT", "action": "RESTORE", "value": 8000, "seq": 12, "out_slot": 1,
                  "event": "R_OWNER_RESTORE", "writes_night": 2}},
      {"dt": 1000, "pulse": {"op": "OK"},
       "expect": {"state": "IDLE", "event": "R_RESTORED", "last_reason": "R_OWNER_RESTORE"}}]
vec("V200", "a restore deferred ten times while the inverter answers: FAULT RESTORE_STALLED, no attempt spent; "
    "Restore original lands", t, final={"state": "IDLE", "record_flags": 4})
vec("V201", "a restore the inverter never answers while its telemetry answers: the night's free retries bound it",
    prefix() + [{"dt": 1000, "keep": True, "pulse": {"end": True}, "expect": {"action": "RESTORE", "seq": 2}},
                {"dt": 1000, "pulse": {"op": "NO_ANSWER"},
                 "expect": {"state": "RESTORING", "event": "R_RESTORE_UNANSWERED", "free_night": 1,
                            "writes_night": 1, "life_writes": 1}},
                {"dt": 30000, "expect": {"action": "RESTORE", "seq": 3}},
                {"dt": 1000, "pulse": {"op": "NO_ANSWER"}, "expect": {"state": "RESTORING", "free_night": 2}},
                {"dt": 30000, "expect": {"action": "RESTORE", "seq": 4}},
                {"dt": 1000, "pulse": {"op": "NO_ANSWER"},
                 "expect": {"state": "FAULT", "event": "R_RESTORE_STALLED", "free_night": 3, "restore_attempts": 0,
                            "writes_night": 1, "commit": True}},
                {"dt": 1000, "cfg": True, "pulse": {"ack": True},
                 "expect": {"state": "IDLE", "event": "R_ACKED", "writes_night": 1, "free_night": 3,
                            "night_used": True}}],
    config={"restore_free_max": 3}, final={"state": "IDLE", "record_flags": 4})
vec("V202", "an RTC correction that never ends after the lease: FAULT RESTORE_STALLED after 10 min of answered time",
    prefix() + [{"dt": 1000, "keep": True, "set": {"rtc_busy": True}, "pulse": {"end": True},
                 "expect": {"state": "RESTORING", "event": "R_END", "action": "NONE", "stall_ms": 0}},
                {"repeat": 39, "dt": 15000, "keep": True, "expect_all": {"state": "RESTORING", "action": "NONE"}},
                {"dt": 15000, "keep": True,
                 "expect": {"state": "FAULT", "event": "R_RESTORE_STALLED", "action": "NONE", "commit": True,
                            "stall_ms": 600000, "restore_attempts": 0, "writes_night": 1}},
                {"dt": 1000, "keep": True, "set": {"rtc_busy": False}, "pulse": {"restore_req": True},
                 "expect": {"action": "RESTORE", "value": 8000, "event": "R_OWNER_RESTORE", "writes_night": 2}},
                {"dt": 1000, "pulse": {"op": "OK"}, "expect": {"state": "IDLE", "event": "R_RESTORED"}}])
# the TELEMETRY_STALE guard of V121; then an hour of silence: none of it counts (rx stale), the restore lands at once
vec("V203", "an hour with a silent inverter adds nothing to the stall bound: no FAULT, the restore lands when it answers",
    prefix() + [{"dt": 91000, "silent": True,
                 "expect": {"state": "RESTORING", "event": "R_TELEMETRY_STALE", "action": "NONE", "stall_ms": 0}},
                {"repeat": 60, "dt": 60000, "silent": True,
                 "expect_all": {"state": "RESTORING", "action": "NONE", "stall_ms": 0}},
                {"dt": 1000, "keep": True,
                 "expect": {"action": "RESTORE", "seq": 2, "stall_ms": 1000, "restore_attempts": 1}},
                {"dt": 1000, "pulse": {"op": "OK"}, "expect": {"state": "IDLE", "event": "R_RESTORED"}}],
    final={"state": "IDLE", "record_flags": 4})
vec("V204", "the shared mutex held after the lease (a stuck lock): FAULT RESTORE_STALLED after 10 min",
    prefix() + [{"dt": 1000, "keep": True, "set": {"mutex_busy": True}, "pulse": {"end": True},
                 "expect": {"state": "RESTORING", "event": "R_END", "action": "NONE"}},
                {"repeat": 19, "dt": 30000, "keep": True, "expect_all": {"state": "RESTORING", "action": "NONE"}},
                {"dt": 30000, "keep": True,
                 "expect": {"state": "FAULT", "event": "R_RESTORE_STALLED", "stall_ms": 600000}},
                {"dt": 1000, "cfg": True, "pulse": {"ack": True}, "expect": {"state": "IDLE", "event": "R_ACKED"}}])
vec("V205", "a tick adds at most 30 s to the stall bound: 60 s ticks need 20 of them",
    prefix() + [{"dt": 1000, "keep": True, "set": {"rtc_busy": True}, "pulse": {"end": True},
                 "expect": {"state": "RESTORING", "action": "NONE"}},
                {"repeat": 19, "dt": 60000, "keep": True, "expect_all": {"state": "RESTORING", "action": "NONE"}},
                {"dt": 60000, "keep": True,
                 "expect": {"state": "FAULT", "event": "R_RESTORE_STALLED", "stall_ms": 600000}}])
# the night's free retries are persisted: a restart does not reset them (a boot loop cannot multiply them)
vec("V206", "the night's free retries survive a restart", prefix() + [
    {"dt": 1000, "keep": True, "pulse": {"end": True}, "expect": {"action": "RESTORE", "seq": 2}},
    {"dt": 1000, "pulse": {"op": "DEFERRED"}, "expect": {"free_night": 1}},
    {"dt": 30000, "expect": {"action": "RESTORE", "seq": 3}},
    {"dt": 1000, "pulse": {"op": "DEFERRED"}, "expect": {"free_night": 2, "commit": True, "nvs_free_night": 2}},
    {"dt": 1000, "keep": True, "reboot": {"corrupt": -1},
     "expect": {"state": "RESTORING", "action": "RESTORE", "seq": 1, "free_night": 2, "restore_attempts": 1,
                "last_reason": "R_BOOT_RECOVERY"}},
    {"dt": 1000, "pulse": {"op": "DEFERRED"},
     "expect": {"state": "FAULT", "event": "R_RESTORE_STALLED", "free_night": 3}}], config={"restore_free_max": 3})
# the restore path's night ceiling: unreachable from a lease (it reserves its restores and the owner's), reachable
# only from a record a different build wrote; the owner's reserved write still restores
vec("V207", "a record whose night ceiling leaves no lease restore: FAULT NIGHT_CEILING; the owner's reserved write "
    "restores", [
        {"dt": 0, "expect": {"state": "FAULT", "event": "R_NIGHT_CEILING", "action": "NONE", "commit": True}},
        {"dt": 1000, "pulse": {"restore_req": True},
         "expect": {"action": "RESTORE", "value": 8000, "seq": 1, "writes_night": 10, "event": "R_OWNER_RESTORE"}},
        {"dt": 1000, "pulse": {"op": "OK"}, "expect": {"state": "IDLE", "event": "R_RESTORED"}}],
    boot={"flags": 5, "slot": 1, "original": 8000, "v": 6000, "p": 6000, "night_id": NIGHT0, "writes_night": 9,
          "changes": 1, "restore_attempts": 0, "lease_end": E0 + 14100, "reason": 60})
# the review's worst case (S7): six changes and three answered restore failures use 9 writes; the owner's reserved
# tenth write restores the same night; after a failed one the next night rolls the counts in FAULT
vec("V208", "Restore original after six changes and three answered failures: the owner's reserved write, then the "
    "next night", fast_changes(6, 0) + [
        {"dt": 1000, "keep": True, "pulse": {"end": True},
         "expect": {"action": "RESTORE", "restore_attempts": 1, "writes_night": 7}},
        {"dt": 1000, "pulse": {"op": "FAIL"}, "expect": {"event": "R_RESTORE_RETRY"}},
        {"dt": 30000, "expect": {"action": "RESTORE", "restore_attempts": 2, "writes_night": 8}},
        {"dt": 1000, "pulse": {"op": "FAIL"}, "expect": {"event": "R_RESTORE_RETRY"}},
        {"dt": 30000, "expect": {"action": "RESTORE", "restore_attempts": 3, "writes_night": 9}},
        {"dt": 1000, "pulse": {"op": "FAIL"}, "expect": {"state": "FAULT", "event": "R_RESTORE_FAILED"}},
        {"dt": 1000, "pulse": {"restore_req": True},
         "expect": {"action": "RESTORE", "value": 8000, "writes_night": 10, "event": "R_OWNER_RESTORE"}},
        {"dt": 1000, "pulse": {"op": "FAIL"}, "expect": {"state": "FAULT", "event": "R_RESTORE_FAILED",
                                                       "writes_night": 10}},
        {"dt": 1000, "pulse": {"restore_req": True}, "expect": {"action": "NONE", "event": "R_REFUSE_RESTORE"}},
        {"dt": 1000, "set": {"night_id": NIGHT0 + 1}, "pulse": {"restore_req": True},
         "expect": {"action": "RESTORE", "writes_night": 1, "week_writes": 11, "night_id": NIGHT0 + 1}},
        {"dt": 1000, "pulse": {"op": "OK"}, "expect": {"state": "IDLE", "event": "R_RESTORED"}}], config=CFG_FAST)
# ---- MINOR: ACK after a corrupt record keeps the night (and a corrupt record's unknown 7-day window counts as full)
vec("V209", "a corrupt record: the boot's night is used and its counts unknown (full); ACK keeps them; the 7-day "
    "window lets START through once the full nights age out",
    lease_end_with("R_END", {"dt": 1000, "keep": True, "pulse": {"end": True}}) + [
        {"dt": 1000, "keep": True, "reboot": {"corrupt": 7},
         "expect": {"state": "FAULT", "last_reason": "R_RECORD_CORRUPT", "action": "NONE", "night_id": NIGHT0,
                    "night_unknown": False, "writes_night": 10, "week_writes": 70}},
        {"dt": 1000, "cfg": True, "pulse": {"ack": True},
         "expect": {"state": "IDLE", "event": "R_ACKED", "night_used": True, "writes_night": 10,
                    "nvs_night_id": NIGHT0, "nvs_writes_night": 10, "nvs_flags": 4}},
        {"dt": 1000, "set": {"arm": True, "batt_w": 8200, "live_sp": 8000}, "expect": {"state": "ARMED"}},
        {"dt": 1000, "keep": True, "pulse": {"start": True},
         "expect": {"state": "IDLE", "event": "R_REFUSE_NIGHT_USED"}},
        {"dt": 1000, "set": {"arm": False}},
        {"dt": 1000, "set": {"arm": True, "night_id": NIGHT0 + 1}, "expect": {"state": "ARMED", "week_writes": 60}},
        {"dt": 1000, "keep": True, "pulse": {"start": True},
         "expect": {"state": "IDLE", "event": "R_REFUSE_WEEK_BUDGET"}},
        {"dt": 1000, "set": {"arm": False}},
        {"dt": 1000, "set": {"arm": True, "night_id": NIGHT0 + 4}, "expect": {"state": "ARMED", "week_writes": 30}},
        {"dt": 1000, "keep": True, "pulse": {"start": True},
         "expect": {"state": "ADJUSTING", "action": "WRITE", "value": 6000, "writes_night": 1, "week_writes": 31}}])
# ---- MINOR: the rolling 7-day and lifetime write ceilings (persisted, published, never refusing a restore)
vec("V210", "the 7-day write window: the last six nights count, a night ages out after seven", [
    {"dt": 0, "set": {"night_id": NIGHT0 + 1}, "expect": {"state": "IDLE", "week_writes": 39}},
    {"dt": 1000, "set": {"arm": True}, "expect": {"state": "ARMED"}},
    {"dt": 1000, "sample": True, "pulse": {"start": True},
     "expect": {"state": "IDLE", "event": "R_REFUSE_WEEK_BUDGET", "disarm": True}},
    {"dt": 1000, "set": {"arm": False}},
    {"dt": 1000, "set": {"arm": True, "night_id": NIGHT0 + 2}, "expect": {"state": "ARMED", "week_writes": 39}},
    {"dt": 1000, "sample": True, "pulse": {"start": True}, "expect": {"event": "R_REFUSE_WEEK_BUDGET"}},
    {"dt": 1000, "set": {"arm": False}},
    {"dt": 1000, "set": {"arm": True, "night_id": NIGHT0 + 3}, "expect": {"state": "ARMED", "week_writes": 36}},
    {"dt": 1000, "sample": True, "pulse": {"start": True},
     "expect": {"state": "ADJUSTING", "action": "WRITE", "writes_night": 1, "week_writes": 37}}],
    boot={"flags": 0, "night_id": NIGHT0, "writes_night": 9, "hist": [9, 9, 9, 3, 0, 0]})
vec("V211", "the lifetime write ceiling: the last change it allows, no change after it, the restore still lands", [
    IDLE0, dict(ARM),
    {"dt": 1000, "sample": True, "pulse": {"start": True},
     "expect": {"state": "ADJUSTING", "action": "WRITE", "value": 6000, "life_writes": 3996}},
    {"dt": 2000, "set": {"arm": False}, "pulse": {"op": "OK"}, "expect": {"state": "SETTLING"}},
    {"dt": 10000, "keep": True, "set": {"batt_w": 6150, "live_sp": 6000}, "expect": {"event": "R_RESPONSE_OK"}},
    {"dt": 50000, "keep": True, "plan": {"p": [4000]}, "expect": {"state": "LEASED", "action": "NONE"}},
    {"dt": 1000, "keep": True, "pulse": {"end": True},
     "expect": {"action": "RESTORE", "value": 8000, "life_writes": 3997}},
    {"dt": 1000, "pulse": {"op": "OK"}, "expect": {"state": "IDLE", "life_writes": 3997}}],
    config=CFG_FAST, boot={"flags": 0, "night_id": NIGHT0 - 1, "life_writes": 3995})
vec("V211b", "START refused: the lifetime write ceiling leaves no change with the restores reserved",
    [IDLE0] + refuse("R_REFUSE_LIFE_BUDGET"), boot={"flags": 0, "night_id": NIGHT0, "life_writes": 3996})
vec("V212", "START refused: the night number went backwards (the clock)",
    [IDLE0] + refuse("R_REFUSE_CLOCK"), boot={"flags": 0, "night_id": NIGHT0 + 5})
vec("V213", "START refused: no site capacity floor (the configuration has no usable default)",
    refuse("R_REFUSE_CONFIG"), config={"capacity_floor_wh": 0})

# the boot night N - 1 (5 writes) joins the window at N: [5, 4, 4, 4, 4, 4] = 25; the lease's START write is committed
# with the window and the lifetime count, and a restart keeps both (26 and 3001, then the boot restore makes 3002)
vec("V214", "the 7-day window and the lifetime count are committed and survive a restart", [
    {"dt": 0, "expect": {"state": "IDLE", "week_writes": 25, "life_writes": 3000}},
    dict(ARM),
    {"dt": 1000, "sample": True, "pulse": {"start": True},
     "expect": {"action": "WRITE", "week_writes": 26, "life_writes": 3001, "nvs_life_writes": 3001,
                "nvs_hist": [5, 4, 4, 4, 4, 4]}},
    {"dt": 1000, "set": {"arm": False}, "reboot": {"corrupt": -1},
     "expect": {"state": "RESTORING", "action": "RESTORE", "week_writes": 27, "life_writes": 3002}}],
    boot={"flags": 0, "night_id": NIGHT0 - 1, "writes_night": 5, "hist": [4, 4, 4, 4, 4, 0], "life_writes": 3000})

# ---- MAJOR 2: an owned readback is committed the tick it is learnt, whether or not that tick can emit
vec("V220", "a clamped write whose result tick has the bus busy (the tick inside grc_execute): the owned readback is "
    "committed at once; a restart then restores the exact original", [
        dict(ARM),
        {"dt": 1000, "sample": True, "pulse": {"start": True}, "expect": {"action": "WRITE", "value": 6000, "seq": 1}},
        {"dt": 2000, "set": {"arm": False, "mutex_busy": True}, "pulse": {"op": "FAIL", "op_value": 5000},
         "expect": {"state": "RESTORING", "event": "R_READBACK_MISMATCH", "action": "NONE", "commit": True, "q": 5000,
                    "nvs_q": 5000, "nvs_flags": 13}},
        {"dt": 1000, "set": {"mutex_busy": False}, "reboot": {"corrupt": -1},
         "expect": {"state": "RESTORING", "action": "RESTORE", "value": 8000, "seq": 1, "out_slot": 1, "q": 5000,
                    "last_reason": "R_BOOT_RECOVERY"}},
        {"dt": 1000, "pulse": {"op": "OK"}, "expect": {"state": "IDLE", "event": "R_RESTORED"}}],
    final={"state": "IDLE", "record_flags": 4})
vec("V221", "a clamped write whose result tick has an RTC correction running: committed at once; a restart restores",
    [dict(ARM),
     {"dt": 1000, "sample": True, "pulse": {"start": True}, "expect": {"action": "WRITE", "value": 6000}},
     {"dt": 2000, "set": {"arm": False, "rtc_busy": True}, "pulse": {"op": "FAIL", "op_value": 5000},
      "expect": {"state": "RESTORING", "action": "NONE", "commit": True, "q": 5000, "nvs_q": 5000}},
     {"dt": 1000, "set": {"rtc_busy": False}, "reboot": {"corrupt": -1},
      "expect": {"state": "RESTORING", "action": "RESTORE", "value": 8000, "q": 5000}},
     {"dt": 1000, "pulse": {"op": "OK"}, "expect": {"state": "IDLE", "event": "R_RESTORED"}}],
    final={"state": "IDLE", "record_flags": 4})
vec("V222", "a restore whose readback differs (7500), then a restart inside the 30 s backoff: the owned readback was "
    "committed, the boot restores over it", prefix() + [
        {"dt": 1000, "keep": True, "pulse": {"end": True}, "expect": {"action": "RESTORE", "seq": 2,
                                                                      "restore_attempts": 1, "writes_night": 2}},
        {"dt": 1000, "pulse": {"op": "FAIL", "op_value": 7500},
         "expect": {"state": "RESTORING", "event": "R_RESTORE_RETRY", "q": 7500, "commit": True, "nvs_q": 7500}},
        {"dt": 5000, "keep": True, "reboot": {"corrupt": -1},
         "expect": {"state": "RESTORING", "action": "RESTORE", "value": 8000, "seq": 1, "q": 7500,
                    "restore_attempts": 2, "writes_night": 3}},
        {"dt": 1000, "pulse": {"op": "OK"}, "expect": {"state": "IDLE", "event": "R_RESTORED"}}],
    final={"state": "IDLE", "record_flags": 4})
# the write outlives its 15 s timeout (grc_execute still running, so mutex_busy); its late FAIL carries the clamped
# 5000: never taken as an outcome, but owned (the restore must not classify 5000 FOREIGN); a duplicate owns nothing
vec("V223", "the late result of a timed-out write: its clamped readback is owned, never its outcome", [
    dict(ARM), {"dt": 1000, "sample": True, "pulse": {"start": True}, "expect": {"action": "WRITE", "seq": 1}},
    {"dt": 1000, "set": {"arm": False, "mutex_busy": True}, "expect": {"state": "ADJUSTING"}},
    {"dt": 14000, "expect": {"state": "RESTORING", "event": "R_OP_TIMEOUT", "action": "NONE"}},
    {"dt": 1000, "set": {"mutex_busy": False}, "pulse": {"op": "FAIL", "op_value": 5000, "op_seq": 1, "op_kind": "WRITE"},
     "expect": {"state": "RESTORING", "action": "RESTORE", "seq": 2, "q": 5000, "commit": True,
                "event": "R_RESTORE_REQUESTED", "restore_attempts": 1}},
    {"dt": 1000, "pulse": {"op": "FAIL", "op_value": 4000, "op_seq": 1, "op_kind": "WRITE"},
     "expect": {"state": "RESTORING", "event": "R_STALE_RESULT", "q": 5000, "action": "NONE"}},
    {"dt": 1000, "pulse": {"op": "OK"}, "expect": {"state": "IDLE", "event": "R_RESTORED"}}])
vec("V224", "a later unanswered readback (-1) never erases the owned readback", [
    dict(ARM), {"dt": 1000, "sample": True, "pulse": {"start": True}},
    {"dt": 2000, "set": {"arm": False}, "pulse": {"op": "FAIL", "op_value": 5000},
     "expect": {"action": "RESTORE", "q": 5000, "seq": 2}},
    {"dt": 1000, "pulse": {"op": "FAIL", "op_value": -1}, "expect": {"event": "R_RESTORE_RETRY", "q": 5000}},
    {"dt": 30000, "expect": {"action": "RESTORE", "seq": 3, "restore_attempts": 2, "q": 5000}},
    {"dt": 1000, "pulse": {"op": "OK"}, "expect": {"state": "IDLE", "event": "R_RESTORED"}}])
vec("V225", "a readback of 0 W after the GRC's own write is owned too", [
    dict(ARM), {"dt": 1000, "sample": True, "pulse": {"start": True}},
    {"dt": 2000, "set": {"arm": False}, "pulse": {"op": "FAIL", "op_value": 0},
     "expect": {"state": "RESTORING", "event": "R_READBACK_MISMATCH", "q": 0, "commit": True, "action": "RESTORE"}}])
BOOT_FR = {"flags": 7, "slot": 1, "original": 8000, "v": 6000, "p": 6000, "night_id": NIGHT0, "writes_night": 4,
           "changes": 1, "restore_attempts": 3, "lease_end": E0 + 14100, "reason": 101}
vec("V226", "the owner's Restore original: its own differing readback is owned and committed, the next one lands", [
    {"dt": 0, "expect": {"state": "FAULT"}},
    {"dt": 1000, "pulse": {"restore_req": True}, "expect": {"action": "RESTORE", "seq": 1, "writes_night": 5}},
    {"dt": 1000, "pulse": {"op": "FAIL", "op_value": 7600},
     "expect": {"state": "FAULT", "event": "R_RESTORE_FAILED", "q": 7600, "commit": True, "nvs_q": 7600,
                "record_flags": 15}},
    {"dt": 1000, "pulse": {"restore_req": True}, "expect": {"action": "RESTORE", "seq": 2, "writes_night": 6}},
    {"dt": 1000, "pulse": {"op": "OK"}, "expect": {"state": "IDLE", "event": "R_RESTORED"}}], boot=BOOT_FR)
vec("V227", "the owner's Restore original without a result for 15 s: timed out, FAULT stays, ACK still works", [
    {"dt": 0, "expect": {"state": "FAULT"}},
    {"dt": 1000, "pulse": {"restore_req": True}, "expect": {"action": "RESTORE", "seq": 1}},
    {"dt": 14999, "expect": {"state": "FAULT", "action": "NONE", "event": "R_NONE"}},
    {"dt": 1, "expect": {"state": "FAULT", "event": "R_RESTORE_FAILED", "commit": True}},
    {"dt": 1000, "cfg": True, "pulse": {"ack": True}, "expect": {"state": "IDLE", "event": "R_ACKED"}}],
    boot=BOOT_FR)
vec("V228", "the restore is emitted when the inverter answered 30 s ago, not 30.001 s", prefix() + [
    {"dt": 1000, "keep": True, "rx": {"age": 30001}, "pulse": {"end": True},
     "expect": {"state": "RESTORING", "action": "NONE", "event": "R_END"}},
    {"dt": 1000, "keep": True, "rx": {"age": 30000}, "expect": {"action": "RESTORE", "seq": 2}}])
vec("V229", "grid lost while SETTLING: the lease ends and the restore is emitted in the same tick", [
    dict(ARM), {"dt": 1000, "sample": True, "pulse": {"start": True}},
    {"dt": 2000, "set": {"arm": False}, "pulse": {"op": "OK"}, "expect": {"state": "SETTLING"}},
    {"dt": 10000, "keep": True, "set": {"grid_ok": False, "batt_w": 6150, "live_sp": 6000},
     "expect": {"state": "RESTORING", "action": "RESTORE", "value": 8000, "seq": 2, "event": "R_GRID_LOSS"}}])
vec("V230", "END and a grid loss both latched while the write is in flight: the grid loss acts at the verified write", [
    dict(ARM), {"dt": 1000, "sample": True, "pulse": {"start": True}},
    {"dt": 1000, "set": {"arm": False, "grid_ok": False}, "pulse": {"end": True},
     "expect": {"state": "ADJUSTING", "action": "NONE"}},
    {"dt": 1000, "set": {"grid_ok": True}, "pulse": {"op": "OK"},
     "expect": {"state": "RESTORING", "action": "RESTORE", "value": 8000, "event": "R_GRID_LOSS", "v": 6000}}])
# mid-lease the slot's own end is E0 + 17640 + x % 60 (x = 84, 85, 86 after the prefix): 120 s either side holds
vec("V231", "the plan's window end mid-lease: 120 s either side holds, 121 s early ends the lease", prefix() + [
    {"dt": 1000, "keep": True, "plan": {"window_end": E0 + 17784}, "expect": {"state": "LEASED", "action": "NONE"}},
    {"dt": 1000, "keep": True, "plan": {"window_end": E0 + 17545}, "expect": {"state": "LEASED", "action": "NONE"}},
    {"dt": 1000, "keep": True, "plan": {"window_end": E0 + 17545},
     "expect": {"action": "RESTORE", "event": "R_PLAN_WINDOW"}}])
vec("V232", "the plan's window end mid-lease 121 s late ends the lease", prefix() + [
    {"dt": 1000, "keep": True, "plan": {"window_end": E0 + 17785},
     "expect": {"action": "RESTORE", "event": "R_PLAN_WINDOW"}}])
# pre-lease 6949 W (off the grid), 7000 W realised, plan 1000 W: 6949*1000//7000 = 992 -> 1000, held at ceil100(4949)
# = 5000, a 1949 W step (revision 2 wrote 4900, a 2049 W step)
vec("V233", "a pre-lease value off the 100 W grid: the START step stays within 2000 W", [
    dict(ARM), {"dt": 1000, "sample": True, "pulse": {"start": True},
                "expect": {"state": "ADJUSTING", "action": "WRITE", "value": 5000}}],
    base_set={"live_sp": 6949, "batt_w": 7000}, base_plan={"p": [1000]})
# from 2000 W the plan asks 10 kW: 2000*10000//2050 = 9756 -> 9800, held at floor100(2000 + 2000) = 4000 (one step up;
# against the last direction 2000 >= 600)
vec("V239", "the step cap upwards: from 2000 W a plan of 10 kW gets one 2000 W step", [
    dict(ARM), {"dt": 1000, "sample": True, "pulse": {"start": True}, "expect": {"action": "WRITE", "value": 6000}},
    {"dt": 2000, "set": {"arm": False}, "pulse": {"op": "OK"}},
    {"dt": 10000, "keep": True, "set": {"batt_w": 6150, "live_sp": 6000}, "expect": {"event": "R_RESPONSE_OK"}},
    {"dt": 50000, "keep": True, "plan": {"p": [0]}, "expect": {"action": "WRITE", "value": 4000}},
    {"dt": 1000, "pulse": {"op": "OK"}},
    {"dt": 10000, "keep": True, "set": {"batt_w": 4100, "live_sp": 4000}, "expect": {"event": "R_RESPONSE_OK"}},
    {"dt": 50000, "keep": True, "expect": {"action": "WRITE", "value": 2000}},
    {"dt": 1000, "pulse": {"op": "OK"}},
    {"dt": 10000, "keep": True, "set": {"batt_w": 2050, "live_sp": 2000}, "expect": {"event": "R_RESPONSE_OK"}},
    {"dt": 50000, "keep": True, "plan": {"p": [10000]}, "expect": {"action": "WRITE", "value": 4000}}],
    config=CFG_FAST)
vec("V234", "START refused: the configuration fields describe another slot", refuse("R_REFUSE_SLOT", {"set": {"cfg_slot": 2}}))
vec("V235", "the configuration fields stop describing the lease's slot: the lease ends",
    lease_end_with("R_CONFIG_DRIFT", {"dt": 1000, "keep": True, "set": {"cfg_slot": 2}}))
vec("V236", "every action names its slot: a slot 3 lease writes and restores register 258", [
    dict(ARM),
    {"dt": 1000, "sample": True, "pulse": {"start": True},
     "expect": {"action": "WRITE", "value": 6000, "out_slot": 3, "slot": 3}},
    {"dt": 2000, "set": {"arm": False}, "pulse": {"op": "OK"}, "expect": {"state": "SETTLING"}},
    {"dt": 1000, "keep": True, "set": {"live_sp": 6000}, "pulse": {"end": True},
     "expect": {"action": "RESTORE", "value": 8000, "out_slot": 3}},
    {"dt": 1000, "pulse": {"op": "OK"}, "expect": {"state": "IDLE"}}],
    base_set={"cfg_slot": 3}, base_plan={"slot": 3})
# ---- MINOR: the 24.8-day wrap: a 31-bit comparison of absolute times stopped the restore after 2^31 ms
vec("V237", "a boot restore owed through 25 days of silence is emitted at once when the inverter answers", prefix() + [
    {"dt": 1000, "silent": True, "reboot": {"corrupt": -1, "rx_never": True},
     "expect": {"state": "RESTORING", "action": "NONE"}},
    {"repeat": 600, "dt": 3_600_000, "silent": True, "expect_all": {"state": "RESTORING", "action": "NONE"}},
    {"dt": 1000, "keep": True, "expect": {"action": "RESTORE", "value": 8000, "seq": 1}},
    {"dt": 1000, "pulse": {"op": "OK"}, "expect": {"state": "IDLE", "event": "R_RESTORED"}}])
vec("V238", "a restore backoff through 25 days of silence: emitted at once when the inverter answers", prefix() + [
    {"dt": 1000, "keep": True, "pulse": {"end": True}, "expect": {"action": "RESTORE", "seq": 2}},
    {"dt": 1000, "pulse": {"op": "NO_ANSWER"}, "expect": {"state": "RESTORING", "event": "R_RESTORE_UNANSWERED"}},
    {"repeat": 600, "dt": 3_600_000, "silent": True, "expect_all": {"state": "RESTORING", "action": "NONE"}},
    {"dt": 1000, "keep": True, "expect": {"action": "RESTORE", "seq": 3}},
    {"dt": 1000, "pulse": {"op": "OK"}, "expect": {"state": "IDLE", "event": "R_RESTORED"}}])

# ------------------------------------------------------------------------------------------------- unit vectors
UNITS = {
    "classify": [[8000, 8000, 6000, 4900, -1, "CLS_ALREADY"], [6000, 8000, 6000, 4900, -1, "CLS_OWNED"],
                 [4900, 8000, 6000, 4900, -1, "CLS_OWNED"], [7000, 8000, 6000, 4900, -1, "CLS_FOREIGN"],
                 [0, 8000, 6000, 6000, -1, "CLS_FOREIGN"], [8000, 8000, 8000, 8000, -1, "CLS_ALREADY"],
                 [5000, 8000, 8000, 6000, 5000, "CLS_OWNED"], [0, 8000, 6000, 6000, 0, "CLS_OWNED"],
                 [5000, 8000, 6000, 6000, 4000, "CLS_FOREIGN"], [8000, 8000, 6000, 6000, 5000, "CLS_ALREADY"],
                 [-1, 8000, 6000, 6000, -1, "CLS_FOREIGN"]],
    "lost_lease": [[[8000, 8000, 8000, 8000, 8000, 8000], [8000, 8000, 8000, 8000, 8000, 8000], 0],
                   [[6000, 8000, 8000, 8000, 8000, 8000], [8000, 8000, 8000, 8000, 8000, 8000], 1],
                   [[8000, 8000, 500, 8000, 8000, 6900], [8000, 8000, 8000, 8000, 8000, 7000], 36],
                   [[-1, 8000, 8000, 8000, 8000, 8000], [8000, 8000, 8000, 8000, 8000, 8000], 0],
                   [[6000, 8000, 8000, 8000, 8000, 8000], [-1, 8000, 8000, 8000, 8000, 8000], 0],
                   [[8000, 8000, 8000, 8000, 8000, 8000], [6000, 6000, 6000, 6000, 6000, 6000], 0],
                   [[0, 0, 0, 0, 0, 0], [1, 1, 1, 1, 1, 1], 63]],
    "records": [
        {"fields": {"flags": 5, "slot": 1, "original": 8000, "v": 6000, "p": 4900, "night_id": NIGHT0,
                    "writes_night": 2, "changes": 2, "restore_attempts": 0, "lease_end": E0 + 14100, "reason": 44},
         "status": "DEC_OK"},
        {"fields": {"flags": 4, "night_id": NIGHT0, "writes_night": 3, "reason": 50}, "status": "DEC_OK"},
        {"fields": {"flags": 5, "slot": 1, "original": 8000, "v": 8100, "p": 6000, "night_id": NIGHT0,
                    "writes_night": 2, "changes": 1, "lease_end": E0}, "status": "DEC_BAD_VALUE"},
        {"fields": {"flags": 5, "slot": 0, "original": 8000, "v": 6000, "p": 6000, "night_id": NIGHT0,
                    "writes_night": 2, "changes": 1, "lease_end": E0}, "status": "DEC_BAD_VALUE"},
        {"fields": {"flags": 4, "slot": 1, "night_id": NIGHT0}, "status": "DEC_BAD_VALUE"},
        {"fields": {"flags": 8, "night_id": NIGHT0}, "status": "DEC_BAD_VALUE"},
        {"fields": {"flags": 4, "night_id": NIGHT0, "writes_night": 11}, "status": "DEC_BAD_VALUE"},
        {"fields": {"flags": 5, "slot": 1, "original": 8000, "v": 6000, "p": 6000, "night_id": NIGHT0,
                    "writes_night": 2, "changes": 7, "lease_end": E0}, "status": "DEC_BAD_VALUE"},
        {"fields": {"flags": 13, "slot": 1, "original": 8000, "v": 8000, "p": 6000, "q": 5000, "night_id": NIGHT0,
                    "writes_night": 2, "changes": 1, "restore_attempts": 1, "lease_end": E0 + 14100, "reason": 86},
         "status": "DEC_OK"},
        {"fields": {"flags": 15, "slot": 1, "original": 8000, "v": 6000, "p": 6000, "q": 0, "night_id": NIGHT0,
                    "writes_night": 4, "changes": 1, "restore_attempts": 3, "lease_end": E0 + 14100, "reason": 101},
         "status": "DEC_OK"},
        {"fields": {"flags": 12, "q": 5000, "night_id": NIGHT0}, "status": "DEC_BAD_VALUE"},
        {"fields": {"flags": 5, "slot": 1, "original": 8000, "v": 6000, "p": 6000, "q": 5000, "night_id": NIGHT0,
                    "writes_night": 2, "changes": 1, "lease_end": E0}, "status": "DEC_BAD_VALUE"},
        {"fields": {"flags": 32, "night_id": NIGHT0}, "status": "DEC_BAD_VALUE"},
        # revision 3: the 7-day window, the night's free retries, the lifetime count, the unknown night
        {"fields": {"flags": 4, "night_id": NIGHT0, "writes_night": 3, "free_night": 2, "hist": [10, 0, 2, 0, 0, 1],
                    "life_writes": 123456, "reason": 50}, "status": "DEC_OK"},
        {"fields": {"flags": 4, "night_id": NIGHT0, "hist": [0, 0, 11, 0, 0, 0]}, "status": "DEC_BAD_VALUE"},
        {"fields": {"flags": 4, "night_id": NIGHT0, "free_night": 11}, "status": "DEC_BAD_VALUE"},
        {"fields": {"flags": 20, "night_id": 0, "writes_night": 10, "free_night": 10, "hist": [10] * 6, "reason": 52},
         "status": "DEC_OK"},
        {"fields": {"flags": 20, "night_id": NIGHT0}, "status": "DEC_BAD_VALUE"},
        {"fields": {"flags": 21, "slot": 1, "original": 8000, "v": 6000, "p": 6000, "night_id": 0, "writes_night": 2,
                    "changes": 1, "lease_end": E0 + 14100}, "status": "DEC_BAD_VALUE"},
        {"fields": {"flags": 7, "slot": 1, "original": 8000, "v": 6000, "p": 6000, "night_id": NIGHT0,
                    "writes_night": 10, "changes": 6, "restore_attempts": 3, "free_night": 10, "lease_end": E0 + 14100,
                    "hist": [4, 4, 4, 4, 4, 4], "life_writes": 3999, "reason": 104}, "status": "DEC_OK"},
    ],
    # revision 3: records whose CRC is valid but whose reserved bytes 36..43 or version are wrong (built below)
    "raw": [],
}


def _raw_records() -> list:
    """Hand-built 48-byte records with a VALID CRC that must still be rejected: a reserved byte set, an old version.
    Built with zlib only (not the model): the expectation is the spec's, the bytes are plain."""
    import zlib
    base = bytearray(48)
    base[0:2] = (0x5247).to_bytes(2, "little")
    base[2] = 3
    base[3] = 4
    base[12:16] = NIGHT0.to_bytes(4, "little")
    out = []
    for k, ver, want in ((36, 3, "DEC_BAD_VALUE"), (43, 3, "DEC_BAD_VALUE"), (-1, 2, "DEC_BAD_VERSION"),
                         (-1, 3, "DEC_OK")):
        b = bytearray(base)
        b[2] = ver
        if k >= 0:
            b[k] = 1
        b[44:48] = (zlib.crc32(bytes(b[0:44])) & 0xFFFFFFFF).to_bytes(4, "little")
        out.append([bytes(b).hex(), want])
    return out


UNITS["raw"] = _raw_records()

if __name__ == "__main__":
    doc = {"spec": "docs/dev/gentle-rate-controller/SPEC.md revision 3", "frame": {"E0": E0, "NOW0": NOW0,
                                                                                  "NIGHT0": NIGHT0},
           "vectors": V, "units": UNITS}
    out = HERE / "vectors.json"
    out.write_text(json.dumps(doc, indent=1, sort_keys=False) + "\n", encoding="utf-8", newline="\n")
    print(f"wrote {out.name}: {len(V)} vectors")
