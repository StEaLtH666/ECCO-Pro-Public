#!/usr/bin/env python3
"""Closed-loop night simulator for the GRC: an INDEPENDENT truth battery and inverter, a Home Assistant planner and
the firmware glue (ownership read, durable record, write, readback, restore classifier) around a GRC core.

The truth model is deliberately not the core's arithmetic: real-valued SOC and power, a first-order charger lag, an
unknown setpoint-to-battery gain `k` (the setpoint unit is NOT ESTABLISHED, so it varies by scenario), a BMS taper
above a knee, a grid-charge-current cap, telemetry noise and 1 % SOC resolution. The core under test is passed in as a
module (the reference model, or a mutant of it), so the same nights also kill mutants.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field

MASK32 = 0xFFFFFFFF
E_WIN = 1_795_000_000 - 5 * 60   # 00:30 local, the window start, in the vector frame (E0 = 00:35)
E_MID = E_WIN - 30 * 60
NOW_BASE = 3_000_000_000         # uptime at the window start (the night crosses the 32-bit wrap)
NIGHT = 20261125
TICK_S = 10


@dataclass
class Scenario:
    name: str = "normal"
    seed: int = 0
    capacity_wh: float = 31700.0
    plan_capacity_factor: float = 1.06
    k: float = 1.025
    soc0: float = 30.0
    target: int = 100
    knee: float = 97.5
    tail_w: float = 1500.0
    original_sp: int = 8000
    owner_ceiling: int = 8000
    gcc_cap_w: float = 9600.0
    plan_scale: float = 1.0
    ha_outage_at_s: int = -1
    tel_freeze_at_s: int = -1
    foreign_at_s: int = -1
    foreign_value: int = 7000
    reboot_at_s: list = field(default_factory=list)
    write_fail_from_s: int = -1
    restore_fail_count: int = 0
    commit_fail_from_s: int = -1
    rtc_busy: tuple = (-1, -1)
    mutex_busy_prob: float = 0.0
    wrong_direction: bool = False
    end_at_s: int = -1
    start_at_s: int = 300
    plan_taper: int = 90


def plan_power_w(soc_x10: int, now_epoch: int, deadline: int, cap_wh: float, target: int) -> int:
    """Home Assistant's planner (independent of the core): the realised power that finishes by the deadline minus a
    taper reserve, with a 5 % margin."""
    reserve = 1800 if target >= 95 else 600
    t_left = deadline - now_epoch - reserve
    e_need = max(0.0, target - soc_x10 / 10.0) / 100.0 * cap_wh
    if t_left <= 600:
        return 10000
    return int(min(10000.0, max(0.0, e_need * 3600.0 / t_left * 1.05)))


class Plant:
    def __init__(self, sc: Scenario, rng: random.Random) -> None:
        self.sc, self.rng = sc, rng
        self.soc = sc.soc0
        self.p = 0.0

    def step(self, dt: float, sp: int) -> None:
        sc = self.sc
        if self.soc >= sc.target:
            cmd = 0.0
        else:
            eff_sp = (2 * sc.original_sp - sp) if (sc.wrong_direction and sp < sc.original_sp) else sp
            cmd = min(max(0.0, eff_sp * sc.k), sc.gcc_cap_w)
            if self.soc >= sc.knee:
                cmd = min(cmd, sc.tail_w)
        self.p += (cmd - self.p) * (1.0 - math.exp(-dt / 15.0))
        self.soc = min(100.0, self.soc + self.p * dt / 3600.0 / sc.capacity_wh * 100.0)

    def telemetry(self) -> tuple[int, int]:
        return int(self.soc) * 10, int(round(self.p + self.rng.gauss(0.0, 30.0)))


def baseline(sc: Scenario) -> dict:
    """Today's behaviour: the slot power stays at the original value all night."""
    pl = Plant(sc, random.Random(sc.seed))
    t, reached, peak, energy_lease = 0, -1, 0.0, 0.0
    while t < 5 * 3600:
        pl.step(TICK_S, sc.original_sp)
        t += TICK_S
        peak = max(peak, pl.p)
        if reached < 0 and pl.soc >= sc.target:
            reached = t
    return {"reached_s": reached, "peak_w": peak}


def run_night(sc: Scenario, M, cfg=None) -> dict:
    """One night 00:30-05:40 with the core in the loop. Returns the trace facts and the list of violated properties."""
    rng = random.Random(sc.seed * 7919 + 17)
    c = cfg or M.Config()
    core = M.Core(c)
    plant = Plant(sc, random.Random(sc.seed))
    reg = sc.original_sp
    nvs = None
    pending = M.OP_NONE
    arm = False
    seq, tel_age, cfg_age, plan_age = 0, 0, 0, 0
    live_seen = reg
    soc_x10, batt = plant.telemetry()
    deadline, window_end = E_WIN + 240 * 60, E_WIN + 300 * 60
    plan = M.Plan(valid=True, slot=1, target=sc.target, deadline=deadline, window_end=window_end,
                  ceiling_w=sc.owner_ceiling, capacity_wh=int(sc.capacity_wh * sc.plan_capacity_factor),
                  taper=sc.plan_taper, n=1)
    viol: list[str] = []
    writes = []          # (t, value)
    reg_writes = 0
    restore_fails_left = sc.restore_fail_count
    leased_at, restoring_seen, reached, peak, lease_energy, lease_s = -1, False, -1, 0.0, 0.0, 0
    events = []
    lease_at_foreign = False
    t = 0
    while t <= 310 * 60:
        now_ms = (NOW_BASE + t * 1000) & MASK32
        epoch = E_WIN + t
        if t in sc.reboot_at_s:
            status, rec = M.decode_record(nvs, c)
            core = M.Core(c)
            core.boot(status, rec, now_ms)
            pending = M.OP_NONE
            events.append((t, "REBOOT"))
        if t == sc.foreign_at_s:
            reg = sc.foreign_value
            lease_at_foreign = core.state in (M.LEASED, M.ADJUSTING, M.SETTLING)
        frozen = sc.tel_freeze_at_s >= 0 and t >= sc.tel_freeze_at_s
        if not frozen:
            soc_x10, batt = plant.telemetry()
            seq += 1
            tel_age = 0
        if t % 60 == 0:
            live_seen, cfg_age = reg, 0
        outage = sc.ha_outage_at_s >= 0 and t >= sc.ha_outage_at_s
        if not outage and t % 300 == 0:
            plan_age = 0
            if t % 900 == 0 or t == sc.start_at_s:
                plan.t[0] = epoch - 60
                plan.p[0] = int(plan_power_w(soc_x10, epoch, deadline, sc.capacity_wh * sc.plan_capacity_factor,
                                             sc.target) * sc.plan_scale)
                plan.p[0] = min(10000, max(0, plan.p[0]))
        if t == sc.start_at_s - 60:
            arm = True
        rtc = sc.rtc_busy[0] <= t < sc.rtc_busy[1]
        mutex = rng.random() < sc.mutex_busy_prob
        i = M.In(now_ms=now_ms, epoch=epoch, local_min=((epoch - E_MID) // 60) % 1440, night_id=NIGHT,
                 clock_change_night=False, inv_skew_s=4, rtc_busy=rtc, mutex_busy=mutex, other=0, fault=False,
                 arm=arm, start=(t == sc.start_at_s), end=(t == sc.end_at_s), ack=False, op=pending, soc=soc_x10,
                 batt_w=batt, tel_ok=True, tel_age_ms=tel_age, sample_seq=seq, cfg_age_ms=cfg_age, live_sp=live_seen,
                 slot_start_min=30, slot_end_min=330, slot_grid=True, slot_target=sc.target, plan=plan)
        plan.age_ms = plan_age
        pending = M.OP_NONE
        state_before = core.state
        o = core.step(i)
        if o.disarm:
            arm = False
        commit_ok = not (sc.commit_fail_from_s >= 0 and t >= sc.commit_fail_from_s)
        if o.commit and commit_ok:
            nvs = M.encode_record(core.record())
        if o.action != M.A_NONE and (rtc or mutex):
            viol.append(f"t={t}: action while the bus was busy")
        if o.action == M.A_WRITE:
            if state_before == M.RESTORING or restoring_seen:
                viol.append(f"t={t}: WRITE after the lease began to end")
            if not (c.floor_w <= o.value <= min(core.original, sc.owner_ceiling, c.fw_bound_w)) or o.value % c.round_w:
                viol.append(f"t={t}: WRITE {o.value} outside [floor, min(original, ceiling)] or not rounded")
            if writes and t - writes[-1][0] < c.dwell_ms // 1000:
                viol.append(f"t={t}: WRITE {t - writes[-1][0]} s after the previous one")
            writes.append((t, o.value))
            events.append((t, "WRITE", o.value))
            if not commit_ok:
                pending = M.OP_FAIL
            elif not M.ownership_ok_for_write(reg, core.v):
                pending = M.OP_FOREIGN
            elif sc.write_fail_from_s >= 0 and t >= sc.write_fail_from_s:
                pending = M.OP_FAIL
            else:
                reg, reg_writes, pending = o.value, reg_writes + 1, M.OP_OK
        elif o.action == M.A_RESTORE:
            restoring_seen = True
            if o.value != core.original:
                viol.append(f"t={t}: RESTORE {o.value} is not the original {core.original}")
            cls = M.classify_restore(reg, core.original, core.v, core.p)
            events.append((t, "RESTORE", cls))
            if cls == M.CLS_ALREADY:
                pending = M.OP_OK_NOWRITE
            elif cls == M.CLS_FOREIGN:
                pending = M.OP_FOREIGN
            elif restore_fails_left > 0:
                restore_fails_left -= 1
                reg_writes += 1
                pending = M.OP_FAIL
            else:
                reg, reg_writes, pending = o.value, reg_writes + 1, M.OP_OK
        if core.state in (M.LEASED, M.ADJUSTING, M.SETTLING):
            if leased_at < 0:
                leased_at = t
            lease_energy += plant.p * TICK_S
            lease_s += TICK_S
            peak = max(peak, plant.p)
        if core.state == M.RESTORING:
            restoring_seen = True
        if core.state == M.IDLE:
            restoring_seen = False
        if core.changes > c.max_changes or core.writes_night > c.night_write_ceiling:
            viol.append(f"t={t}: budget exceeded ({core.changes} changes, {core.writes_night} writes)")
        if reg > sc.original_sp and not (sc.foreign_at_s >= 0 and t >= sc.foreign_at_s):
            viol.append(f"t={t}: slot power {reg} above the original")
        plant.step(TICK_S, reg)
        if reached < 0 and plant.soc >= sc.target:
            reached = t
        if t > 0 and t % TICK_S == 0:
            tel_age += TICK_S * 1000
            cfg_age += TICK_S * 1000
            plan_age += TICK_S * 1000
        t += TICK_S
    if sc.foreign_at_s >= 0:
        final_ok = reg == sc.foreign_value and (lease_at_foreign is False or (
            core.state == M.FAULT and core.last_reason == M.R_FOREIGN))
    else:
        final_ok = reg == sc.original_sp or (core.state == M.FAULT and core.last_reason in (
            M.R_RESTORE_FAILED, M.R_RECORD_CORRUPT, M.R_NIGHT_CEILING))
    if not final_ok:
        viol.append(f"end: slot power {reg}, state {M.STATE_NAMES[core.state]}, last {M.REASON_NAMES.get(core.last_reason)}")
    if core.state == M.FAULT and core.last_reason == M.R_FOREIGN and sc.foreign_at_s < 0:
        viol.append("end: FOREIGN fault without any foreign write")
    if reg_writes > c.night_write_ceiling:
        viol.append(f"end: {reg_writes} register writes in one night")
    return {"viol": viol, "reached_s": reached, "peak_w": peak, "writes": writes, "reg_writes": reg_writes,
            "final_state": M.STATE_NAMES[core.state], "last_reason": M.REASON_NAMES.get(core.last_reason),
            "leased_at": leased_at, "mean_lease_w": (lease_energy / lease_s if lease_s else 0.0), "events": events,
            "final_reg": reg}


def normal_scenarios(n: int, seed0: int) -> list[Scenario]:
    out = []
    rng = random.Random(seed0)
    for k in range(n):
        out.append(Scenario(name="normal", seed=seed0 + k, capacity_wh=rng.uniform(26000, 34000),
                            plan_capacity_factor=rng.uniform(1.0, 1.1), k=rng.uniform(0.96, 1.06),
                            soc0=rng.uniform(10, 60), target=rng.choice([80, 90, 100]), knee=rng.uniform(96.5, 98.5),
                            tail_w=rng.uniform(1200, 2700), mutex_busy_prob=rng.choice([0.0, 0.02]),
                            plan_taper=rng.choice([90, 97])))
    return out


def fault_scenarios(seed0: int) -> list[Scenario]:
    s = seed0
    return [
        Scenario(name="ha_outage", seed=s + 1, soc0=25, target=90, ha_outage_at_s=3000),
        Scenario(name="telemetry_freeze", seed=s + 2, soc0=25, target=90, tel_freeze_at_s=4000),
        Scenario(name="foreign_write", seed=s + 3, soc0=25, target=90, foreign_at_s=5000, foreign_value=6950),
        Scenario(name="reboot_mid_lease", seed=s + 4, soc0=25, target=90, reboot_at_s=[2400]),
        Scenario(name="reboot_twice", seed=s + 5, soc0=25, target=90, reboot_at_s=[310, 2400]),
        Scenario(name="write_fail", seed=s + 6, soc0=25, target=90, write_fail_from_s=2000),
        Scenario(name="restore_fail_twice", seed=s + 7, soc0=25, target=90, end_at_s=3000, restore_fail_count=2),
        Scenario(name="restore_fail_always", seed=s + 8, soc0=25, target=90, end_at_s=3000, restore_fail_count=9),
        Scenario(name="commit_fail", seed=s + 9, soc0=25, target=90, commit_fail_from_s=2000),
        Scenario(name="rtc_busy_long", seed=s + 10, soc0=25, target=90, rtc_busy=(2500, 3000)),
        Scenario(name="rtc_busy_short", seed=s + 11, soc0=25, target=90, rtc_busy=(2300, 2400)),
        Scenario(name="slot_not_binding", seed=s + 12, soc0=40, target=90, gcc_cap_w=5200.0),
        Scenario(name="wrong_direction", seed=s + 13, soc0=25, target=90, wrong_direction=True),
        Scenario(name="planner_too_low", seed=s + 14, soc0=20, target=90, plan_scale=0.3),
        Scenario(name="planner_too_high", seed=s + 15, soc0=40, target=90, plan_scale=3.0),
        Scenario(name="owner_end", seed=s + 16, soc0=25, target=90, end_at_s=1500),
        Scenario(name="owner_ceiling", seed=s + 17, soc0=25, target=90, owner_ceiling=5000),
        Scenario(name="busy_bus", seed=s + 18, soc0=25, target=90, mutex_busy_prob=0.3),
        Scenario(name="small_battery", seed=s + 19, soc0=50, target=90, capacity_wh=15000, plan_capacity_factor=1.06),
        Scenario(name="low_gain", seed=s + 20, soc0=40, target=90, k=0.8),
    ]
