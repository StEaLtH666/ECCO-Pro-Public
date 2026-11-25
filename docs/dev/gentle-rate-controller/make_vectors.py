#!/usr/bin/env python3
"""Writes vectors.json: the GRC golden vectors. Every expectation below is HAND-COMPUTED from SPEC.md (the arithmetic
is noted beside the less obvious ones); nothing here runs the model. test_reference_model.py checks that the model
meets every expectation and that vectors.json is exactly what this script writes.

Frame (vector_runner.py): E0 = 00:35 local, the slot runs 00:30-05:30 (grid, target 100 %), the plan deadline is 04:30
(E0 + 14100), the window end 05:30 (E0 + 17700), capacity 30000 Wh, taper 90 %, one plan point of 6000 W realised.
Every number is a synthetic test frame, not a site reading.
Target guard at SOC 40.0 %: plateau 500 * 30000 // 1000 = 15000 Wh at 8200*85//100 = 6970 W -> 7747 s, tail 3000 Wh at
8200*25//100 = 2050 W -> 5268 s; it trips once epoch + 13015 + 900 >= E0 + 17100, i.e. from E0 + 3185.
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
def prefix(batt: int = 6150, judge: dict | None = None) -> list:
    j = {"state": "LEASED", "event": "R_RESPONSE_OK", "gain_pct": 102, "p_ref": 6150} if judge is None else judge
    return [
        dict(ARM),
        {"dt": 1000, "sample": True, "pulse": {"start": True},
         "expect": {"state": "ADJUSTING", "action": "WRITE", "value": 6000, "disarm": True, "commit": True,
                    "event": "R_LEASE_STARTED", "changes": 1, "writes_night": 1, "gain_pct": 102, "v": 8000, "p": 6000,
                    "lease_end": E0 + 14100}},
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
    # soc 19.0 %: plateau 710*30000//1000 = 21300 Wh -> 11001 s, tail 5268 s; E0+1+16269+900 >= E0+17100
    ("V43", "the target is at risk even at today's rate", "R_REFUSE_TARGET_AT_RISK", {"set": {"soc": 190}}),
]
for vid, title, reason, extra in R:
    vec(vid, "START refused: " + title, refuse(reason, extra))
# soc 20.0 %: plateau 21000 Wh -> 10846 s, tail 5268 s: E0+1+16114+900 < E0+17100
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
vec("V56", "the owner ceiling wins over the step cap (a larger step, downward only)",
    [dict(ARM), {"dt": 1000, "sample": True, "pulse": {"start": True},
                 "expect": {"action": "WRITE", "value": 5000}}], base_plan={"ceiling_w": 5000})
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
# guard from epoch E0 + 3185 (see the frame note): tick 52 after the prefix (E0 + 83 + 60k)
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

# ------------------------------------------------------------------------------------------------- unit vectors
UNITS = {
    "classify": [[8000, 8000, 6000, 4900, "CLS_ALREADY"], [6000, 8000, 6000, 4900, "CLS_OWNED"],
                 [4900, 8000, 6000, 4900, "CLS_OWNED"], [7000, 8000, 6000, 4900, "CLS_FOREIGN"],
                 [0, 8000, 6000, 6000, "CLS_FOREIGN"], [8000, 8000, 8000, 8000, "CLS_ALREADY"]],
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
        {"fields": {"flags": 4, "night_id": NIGHT0, "writes_night": 10}, "status": "DEC_BAD_VALUE"},
        {"fields": {"flags": 5, "slot": 1, "original": 8000, "v": 6000, "p": 6000, "night_id": NIGHT0,
                    "writes_night": 2, "changes": 7, "lease_end": E0}, "status": "DEC_BAD_VALUE"},
    ],
}

if __name__ == "__main__":
    doc = {"spec": "docs/dev/gentle-rate-controller/SPEC.md revision 1", "frame": {"E0": E0, "NOW0": NOW0,
                                                                                  "NIGHT0": NIGHT0},
           "vectors": V, "units": UNITS}
    out = HERE / "vectors.json"
    out.write_text(json.dumps(doc, indent=1, sort_keys=False) + "\n", encoding="utf-8", newline="\n")
    print(f"wrote {out.name}: {len(V)} vectors")
