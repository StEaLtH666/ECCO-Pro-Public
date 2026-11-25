#!/usr/bin/env python3
"""Expands the compact GRC vectors (vectors.json) into full per-tick inputs and runs them through a core.

Shared by test_reference_model.py (the model's own proof) and registry/tests/test_gentle_rate_core_host.py (which
serialises the same expanded inputs for the C++ header harness). No I/O except reading vectors.json on request.

Compact tick keys: dt (ms advanced before the tick; default 1000, 0 allowed), set {In field: value} persistent,
plan {Plan field: value} persistent and resets the plan age, refresh (plan age 0), sample (new telemetry frame),
cfg (new configuration read), keep (sample + cfg + refresh), pulse {start, end, ack, op} for this tick only,
epoch_hold (the wall clock does not advance), repeat n, reboot {"corrupt": byte index or -1, "absent": bool}
before the tick, expect {...} on the last expanded tick, expect_all {...} on every expanded tick.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent

E0 = 1_795_000_000            # 00:35 local in the vectors' frame
E_MID = E0 - 35 * 60          # that night's local midnight
NOW0 = 1_000_000
NIGHT0 = 20261125

IN_FIELDS = ["now_ms", "epoch", "local_min", "night_id", "clock_change_night", "inv_skew_s", "rtc_busy", "mutex_busy",
             "other", "fault", "arm", "start", "end", "ack", "op", "soc", "batt_w", "tel_ok", "tel_age_ms", "sample_seq",
             "cfg_age_ms", "live_sp", "slot_start_min", "slot_end_min", "slot_grid", "slot_target"]
PLAN_FIELDS = ["valid", "age_ms", "slot", "target", "deadline", "window_end", "ceiling_w", "capacity_wh", "taper", "n"]
CONFIG_FIELDS = ["floor_w", "round_w", "fw_bound_w", "max_step_w", "hyst_w", "reversal_extra_w", "dwell_ms", "settle_ms",
                 "judge_samples", "max_changes", "max_restore_attempts", "night_write_ceiling", "restore_backoff_ms",
                 "op_timeout_ms", "plan_max_age_ms", "telemetry_stale_ms", "config_stale_ms", "rtc_busy_max_ms",
                 "clock_skew_max_s", "end_margin_s", "min_lease_s", "arm_window_ms", "charging_min_w",
                 "response_min_pct", "wrong_dir_w", "max_ineffective", "gain_min_pct", "gain_max_pct", "runaway_pct",
                 "runaway_margin_w", "runaway_samples", "stop_w", "stop_samples", "stop_soc_gap", "soc_jump_max",
                 "soc_drop_max", "guard_margin_s", "guard_derate_pct", "guard_tail_pct", "watchdog_extra_ms"]

BASE_IN = {"now_ms": NOW0, "night_id": NIGHT0, "clock_change_night": False, "inv_skew_s": 5, "rtc_busy": False,
           "mutex_busy": False, "other": 0, "fault": False, "arm": False, "soc": 400, "batt_w": 8200, "tel_ok": True,
           "sample_seq": 1, "live_sp": 8000, "slot_start_min": 30, "slot_end_min": 330, "slot_grid": True,
           "slot_target": 100}
BASE_PLAN = {"valid": True, "slot": 1, "target": 100, "deadline": E_MID + 270 * 60, "window_end": E_MID + 330 * 60,
             "ceiling_w": 8000, "capacity_wh": 31700, "taper": 90, "t": [E0 - 60], "p": [6000]}


def load_vectors(path: Path = HERE / "vectors.json") -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))["vectors"]


def expand(vec: dict, M) -> list[tuple]:
    """-> [(In, meta)], meta = {"expect": {...} | None, "reboot": {...} | None}."""
    cur = dict(BASE_IN)
    cur.update(vec.get("base_set", {}))
    plan = copy.deepcopy(BASE_PLAN)
    plan.update(copy.deepcopy(vec.get("base_plan", {})))
    pinned: dict = {}
    for k in ("epoch", "local_min"):
        if k in vec.get("base_set", {}):
            pinned[k] = vec["base_set"][k]
            cur.pop(k, None)
    epoch_real = E0
    now = cur.pop("now_ms")
    tel_age = cfg_age = plan_age = 0
    seq = cur.pop("sample_seq")
    out = []
    first = True
    for entry in vec["ticks"]:
        reps = entry.get("repeat", 1)
        for r in range(reps):
            dt = entry.get("dt", 0 if first else 1000)
            first = False
            now = (now + dt) & 0xFFFFFFFF
            if not entry.get("epoch_hold"):
                epoch_real += dt // 1000
            tel_age += dt
            cfg_age += dt
            plan_age += dt
            for k, v in entry.get("set", {}).items():
                if k in ("epoch", "local_min"):
                    if v is None:
                        pinned.pop(k, None)
                    else:
                        pinned[k] = v
                else:
                    cur[k] = v
            if "plan" in entry and r == 0:
                plan.update(copy.deepcopy(entry["plan"]))
                plan_age = 0
            keep = entry.get("keep", False)
            if entry.get("refresh") or keep:
                plan_age = 0
            if entry.get("sample") or keep:
                seq += 1
                tel_age = 0
            if entry.get("cfg") or keep:
                cfg_age = 0
            i = M.In()
            for k, v in cur.items():
                setattr(i, k, v)
            i.now_ms = now
            i.epoch = pinned.get("epoch", epoch_real)
            if "local_min" in pinned:
                i.local_min = pinned["local_min"]
            else:
                i.local_min = ((i.epoch - E_MID) // 60) % 1440 if i.epoch > 0 else -1
            i.tel_age_ms, i.cfg_age_ms, i.sample_seq = tel_age, cfg_age, seq
            pulse = entry.get("pulse", {}) if r == reps - 1 or entry.get("pulse_all") else {}
            for k, v in pulse.items():
                setattr(i, k, M.OP_NAMES.index(v) if k == "op" else v)
            pl = M.Plan()
            for k, v in plan.items():
                if k not in ("t", "p"):
                    setattr(pl, k, v)
            pl.n = plan.get("n", len(plan["t"]))
            pl.t = (list(plan["t"]) + [0] * 8)[:8]
            pl.p = (list(plan["p"]) + [0] * 8)[:8]
            pl.age_ms = plan_age
            i.plan = pl
            meta = {"expect_all": entry.get("expect_all"),
                    "expect": entry.get("expect") if r == reps - 1 else None,
                    "reboot": entry.get("reboot") if r == 0 else None}
            out.append((i, meta))
    return out


def make_core(vec: dict, M):
    cfg = M.Config()
    for k, v in vec.get("config", {}).items():
        setattr(cfg, k, v)
    return M.Core(cfg), cfg


def reboot(core, cfg, spec: dict, now_ms: int, M):
    """A restart: the record the core would have committed, optionally corrupted or absent, decoded and booted."""
    b = M.encode_record(core.record())
    if spec.get("absent"):
        b = None
    elif spec.get("corrupt", -1) >= 0:
        k = spec["corrupt"]
        b = b[:k] + bytes([b[k] ^ 0x5A]) + b[k + 1:]
    status, rec = M.decode_record(b, cfg)
    nc = M.Core(cfg)
    nc.boot(status, rec, now_ms)
    return nc


def run(vec: dict, M) -> tuple[list[str], list[str], object]:
    """-> (trace lines, expectation failures, final core)."""
    core, cfg = make_core(vec, M)
    lines, fails = [], []
    if vec.get("boot") is not None:
        status, rec = M.decode_record(M.encode_record(M.Record(**vec["boot"])), cfg)
        core.boot(status, rec, NOW0)
        lines.append("BOOT " + trace_state(core))
    for n, (i, meta) in enumerate(expand(vec, M)):
        if meta["reboot"] is not None:
            core = reboot(core, cfg, meta["reboot"], i.now_ms, M)
            lines.append("BOOT " + trace_state(core))
        o = core.step(i)
        lines.append(M.trace_line(core, o))
        for key in ("expect_all", "expect"):
            exp = meta[key]
            if exp:
                bad = check_expect(exp, core, o, M)
                if bad:
                    fails.append(f"{vec['id']} tick {n} ({key}): {bad}")
    lines.append("REC " + M.encode_record(core.record()).hex())
    if vec.get("final"):
        bad = check_expect(vec["final"], core, None, M)
        if bad:
            fails.append(f"{vec['id']} final: {bad}")
    return lines, fails, core


def trace_state(core) -> str:
    return " ".join(str(x) for x in (core.state, core.v, core.p, core.changes, core.writes_night, core.restore_attempts,
                                     core.last_reason))


def check_expect(exp: dict, core, o, M) -> str:
    got = {}
    for k, want in exp.items():
        if k == "state":
            g = M.STATE_NAMES[core.state]
        elif k == "action":
            g = M.ACTION_NAMES[o.action] if o else None
        elif k in ("value", "disarm", "commit"):
            g = getattr(o, k) if o else None
            if k != "value":
                g = bool(g)
        elif k == "event":
            g = M.REASON_NAMES.get(o.event) if o else None
        elif k == "last_reason":
            g = M.REASON_NAMES.get(core.last_reason)
        elif k == "record_flags":
            g = core.record().flags
        else:
            g = getattr(core, k)
            if isinstance(g, bool):
                g = bool(g)
        if g != want:
            got[k] = (want, g)
    return "" if not got else ", ".join(f"{k}: want {w!r} got {g!r}" for k, (w, g) in got.items())


def serialise_in(i) -> str:
    vals = [int(getattr(i, k)) for k in IN_FIELDS]
    pl = i.plan
    vals += [int(getattr(pl, k)) for k in PLAN_FIELDS]
    vals += [int(x) for x in pl.t] + [int(x) for x in pl.p]
    return "T " + " ".join(str(v) for v in vals)


def serialise_config(cfg) -> str:
    return "C " + " ".join(str(int(getattr(cfg, k))) for k in CONFIG_FIELDS)


# ---------------------------------------------------------------------------------------------------------------
# Seeded random fuzz: a noisy glue drives a core (usually honest results, sometimes failures, foreign values,
# restarts, stale data, busy bus, bad plans) and records every input, so the SAME items can be replayed through the
# header. `check` (optional) is called as check(core_before_dict, i, o, core_after) for property tests.
# ---------------------------------------------------------------------------------------------------------------
def fuzz_items(seed: int, M, n: int = 300, check=None):
    import random
    rng = random.Random(seed)
    cfg = M.Config()
    if rng.random() < 0.7:
        cfg.dwell_ms = rng.choice([60_000, 120_000, 600_000])
        cfg.settle_ms = rng.choice([5_000, 20_000, 45_000])
        cfg.judge_samples = rng.choice([1, 2, 4])
    core = M.Core(cfg)
    reg = 8000
    cur = dict(BASE_IN)
    plan = copy.deepcopy(BASE_PLAN)
    now = cur.pop("now_ms") if rng.random() < 0.6 else 0xFFFFFFFF - 200_000
    cur.pop("sample_seq")
    epoch, seq = E0, 1
    tel_age = cfg_age = plan_age = 0
    soc, batt, live = 400, 8200, 8000
    pending = None
    items = []
    for _ in range(n):
        if items and rng.random() < 0.012:
            corrupt = rng.choice([-1, -1, -1, 5, 13])
            items.append(("R", corrupt))
            core = reboot(core, cfg, {"corrupt": corrupt}, now, M)
            pending = None
        dt = rng.choice([0, 1, 1000, 5000, 10_000, 10_000, 10_000, 30_000, 60_000, 60_000, 120_000, 400_000])
        now = (now + dt) & 0xFFFFFFFF
        if rng.random() > 0.02:
            epoch += dt // 1000
        tel_age += dt
        cfg_age += dt
        plan_age += dt
        op = M.OP_NONE
        if pending is not None:
            r = rng.random()
            kind, value = pending
            if r < 0.75:
                op = M.OP_OK
                reg = value
            elif r < 0.83:
                op = M.OP_FAIL
            elif r < 0.87:
                op = M.OP_FOREIGN
            elif r < 0.92:
                op = M.OP_OK_NOWRITE
            if op != M.OP_NONE:
                pending = None
        if rng.random() < 0.85:
            seq += 1
            tel_age = 0
            r = rng.random()
            soc = max(0, min(1000, soc + (rng.choice([0, 0, 10, 10, 20]) if r < 0.95 else rng.choice([-60, 70, 600]))))
            batt = int(reg * rng.uniform(0.98, 1.06)) if rng.random() < 0.85 else rng.choice([0, 50, 2000, 9000, 12000])
        if rng.random() < 0.6:
            live, cfg_age = reg, 0
        if rng.random() < 0.01:
            reg = rng.choice([7000, 6950, 500])
        if rng.random() < 0.75:
            plan_age = 0
        if rng.random() < 0.12:
            plan["p"] = [rng.choice([0, 500, 3000, 5000, 6000, 7000, 8000, 10000])]
            plan["t"] = [epoch - 60]
            plan_age = 0
            if rng.random() < 0.15:
                plan["deadline"] = epoch + rng.choice([-10, 100, 3000, 14000])
                plan["window_end"] = max(plan["deadline"] + 1, plan["window_end"])
            if rng.random() < 0.05:
                plan["valid"] = not plan["valid"] if rng.random() < 0.5 else True
            if rng.random() < 0.03:
                plan["target"] = rng.choice([90, 100])
        if soc >= 990 and rng.random() < 0.3:
            soc = rng.choice([300, 400])
            cur["night_id"] = cur["night_id"] + 1
            epoch = E0
            plan = copy.deepcopy(BASE_PLAN)
        cur["arm"] = cur["arm"] if rng.random() < 0.8 else not cur["arm"]
        cur["rtc_busy"] = rng.random() < 0.05
        cur["mutex_busy"] = rng.random() < 0.05
        cur["other"] = rng.choice([1, 2, 4]) if rng.random() < 0.015 else 0
        cur["fault"] = rng.random() < 0.01
        cur["clock_change_night"] = rng.random() < 0.004
        cur["inv_skew_s"] = rng.choice([-1, 200]) if rng.random() < 0.01 else 5
        cur["slot_target"] = plan["target"] if rng.random() < 0.99 else 90
        cur["tel_ok"] = rng.random() > 0.01
        i = M.In()
        for k, v in cur.items():
            setattr(i, k, v)
        i.now_ms, i.epoch = now, (epoch if rng.random() > 0.005 else 0)
        i.local_min = ((i.epoch - E_MID) // 60) % 1440 if i.epoch > 0 else -1
        i.start = rng.random() < 0.12
        i.end = rng.random() < 0.015
        i.ack = rng.random() < 0.03
        i.op = op
        i.soc, i.batt_w, i.live_sp = soc, batt, live
        i.tel_age_ms, i.cfg_age_ms, i.sample_seq = tel_age, cfg_age, seq
        pl = M.Plan()
        for k, v in plan.items():
            if k not in ("t", "p"):
                setattr(pl, k, v)
        pl.n = plan.get("n", len(plan["t"]))
        pl.t = (list(plan["t"]) + [0] * 8)[:8]
        pl.p = (list(plan["p"]) + [0] * 8)[:8]
        pl.age_ms = plan_age
        i.plan = pl
        before = {"state": core.state, "op_pending": core.op_pending, "op_start_ms": core.op_start_ms, "v": core.v,
                  "original": core.original}
        o = core.step(i)
        if check is not None:
            check(before, i, o, core)
        if o.action != M.A_NONE:
            pending = (o.action, o.value)
        items.append(("T", i))
    return cfg, items


def run_items(cfg, items, M) -> list[str]:
    core = M.Core(cfg)
    lines = []
    last_now = 0
    for kind, x in items:
        if kind == "R":
            core = reboot(core, cfg, {"corrupt": x}, last_now, M)
            lines.append("BOOT " + trace_state(core))
            continue
        last_now = x.now_ms
        o = core.step(x)
        lines.append(M.trace_line(core, o))
    lines.append("REC " + M.encode_record(core.record()).hex())
    return lines
