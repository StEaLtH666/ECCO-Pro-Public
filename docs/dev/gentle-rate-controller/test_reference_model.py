#!/usr/bin/env python3
"""Proof suite of the GRC reference model (docs/dev/gentle-rate-controller/reference_model.py). Offline, no I/O beyond
reading this folder.

  [1] golden vectors: every hand-computed expectation of vectors.json holds; vectors.json is exactly what
      make_vectors.py writes (no hand edit, no drift)
  [2] unit vectors: the restore classifier (with the owned readback), the lost-lease warning, the durable record
      (decode statuses, round trip, EVERY single-byte corruption of a valid record is rejected, every truncation is
      rejected), config_ok
  [3] properties on a seeded fuzz (FUZZ_SEQUENCES sequences): bounds, rounding, the step cap without exception (the
      owner ceiling included), no action on a busy bus or with an operation outstanding (a stale result is no result),
      no restore while the inverter is silent, no write while the grid is lost, an unanswered or deferred restore
      never spends an attempt, a fresh sequence number per action, budgets, one-shot arm, no write once a lease is
      ending, FAULT emits nothing but the owner's Restore original, records always decodable
  [4] closed loop against the INDEPENDENT truth battery (simulator.py): 80 normal nights and 29 fault nights (Modbus
      down 2, 5 and 10 min at a guard and at a restart, an inverter that rounds or clamps the value, a grid outage,
      ...), every property of the simulator, no target missed that today's fixed rate reaches, gentler on average,
      and the designed outcome of each fault night
  [5] mutation: MUTANTS faults injected into a copy of the model source; each must make [1]-[4] fail

Run: python -I -B -X utf8 docs/dev/gentle-rate-controller/test_reference_model.py
"""

from __future__ import annotations

import importlib.util
import json
import random
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import vector_runner as VR  # noqa: E402
import simulator as S  # noqa: E402

FAILURES: list[str] = []
FUZZ_SEQUENCES = 300
FUZZ_SEED = 20261125


def check(name: str, ok: bool, detail: str = "") -> None:
    if ok:
        print(f"  PASS  {name}")
    else:
        FAILURES.append(name)
        print(f"  FAIL  {name}" + (f" - {detail}" if detail else ""))


def load_model(source: str | None = None, name: str = "grc_reference_model"):
    if source is None:
        source = (HERE / "reference_model.py").read_text(encoding="utf-8")
    spec = importlib.util.spec_from_loader(name, loader=None)
    mod = importlib.util.module_from_spec(spec)
    mod.__file__ = str(HERE / "reference_model.py")
    sys.modules[name] = mod
    exec(compile(source, str(HERE / "reference_model.py"), "exec"), mod.__dict__)
    return mod


# ===========================================================================================================
# The batteries (each returns a list of problems; [] = pass). Mutants run the same functions.
# ===========================================================================================================
def battery_vectors(M) -> list[str]:
    bad = []
    for v in VR.load_vectors():
        _, fails, _, _ = VR.run(v, M)
        bad += fails
    return bad


def battery_units(M) -> list[str]:
    bad = []
    units = json.loads((HERE / "vectors.json").read_text(encoding="utf-8"))["units"]
    for live, orig, v, p, q, want in units["classify"]:
        got = M.classify_restore(live, orig, v, p, q)
        if got != getattr(M, want):
            bad.append(f"classify({live},{orig},{v},{p},{q}) = {got}, want {want}")
    for live, table, want in units["lost_lease"]:
        got = M.lost_lease_slots(live, table)
        if got != want:
            bad.append(f"lost_lease_slots({live}, {table}) = {got}, want {want}")
    cfg = M.Config()
    for r in units["records"]:
        b = M.encode_record(M.Record(**r["fields"]))
        st, rec = M.decode_record(b, cfg)
        if st != getattr(M, r["status"]):
            bad.append(f"record {r['fields']}: status {st}, want {r['status']}")
        if st == M.DEC_OK and M.encode_record(rec) != b:
            bad.append(f"record {r['fields']}: round trip differs")
    good = M.encode_record(M.Record(**units["records"][0]["fields"]))
    for k in range(len(good)):
        for mask in (0x01, 0x80, 0xFF):
            b = good[:k] + bytes([good[k] ^ mask]) + good[k + 1:]
            if M.decode_record(b, cfg)[0] == M.DEC_OK:
                bad.append(f"byte {k} ^ {mask:#x} decodes as OK")
    for n in range(len(good)):
        if M.decode_record(good[:n], cfg)[0] != M.DEC_BAD_SIZE:
            bad.append(f"truncated to {n} bytes not BAD_SIZE")
    if M.decode_record(None, cfg)[0] != M.DEC_ABSENT:
        bad.append("absent record not DEC_ABSENT")
    if not M.config_ok(M.Config()):
        bad.append("default config rejected")
    for field, value in (("night_write_ceiling", 8), ("settle_ms", 1_800_000), ("floor_w", 450), ("fw_bound_w", 8100),
                         ("max_step_w", 200), ("guard_tail_pct", 0), ("hyst_w", 0), ("op_timeout_ms", 12_000),
                         ("script_queue_ms", 6_000), ("end_margin_s", 180), ("window_match_s", 60),
                         ("capacity_floor_wh", 999), ("taper_max_pct", 49), ("rx_fresh_ms", 0)):
        c = M.Config()
        setattr(c, field, value)
        if M.config_ok(c):
            bad.append(f"config_ok accepts {field}={value}")
    return bad


def battery_fuzz(M, sequences: int = FUZZ_SEQUENCES) -> list[str]:
    bad: list[str] = []

    def chk(before, i, o, core):
        c = core.c
        tag = f"fuzz state {before['state']}->{core.state} action {o.action}"
        valid = i.op != M.OP_NONE and before["op_pending"] and i.op_seq == before["op_seq"] and \
            i.op_kind == before["op_kind"]
        if o.action == M.A_WRITE:
            v0 = before["v"] if before["state"] != M.ARMED else i.live_sp
            hard = min(core.original, c.fw_bound_w) // c.round_w * c.round_w
            owner = max(i.plan.ceiling_w, (max(0, v0 - c.max_step_w) + c.round_w - 1) // c.round_w * c.round_w)
            if core.state != M.ADJUSTING or o.value % c.round_w or not c.floor_w <= o.value <= min(hard, owner):
                bad.append(f"{tag}: WRITE {o.value} outside the bounds (hard {hard}, owner step {owner})")
            if abs(o.value - v0) < c.hyst_w:
                bad.append(f"{tag}: WRITE {o.value} within the hysteresis of {v0}")
            if abs(o.value - v0) > c.max_step_w:
                bad.append(f"{tag}: WRITE {o.value} steps more than {c.max_step_w} from {v0}")
            if before["state"] in (M.RESTORING, M.FAULT, M.IDLE):
                bad.append(f"{tag}: WRITE from state {before['state']}")
            if not i.grid_ok:
                bad.append(f"{tag}: WRITE while the grid is lost")
        if o.action == M.A_RESTORE and (o.value != core.original or core.original == 0 or
                                        core.state not in (M.RESTORING, M.FAULT)):
            bad.append(f"{tag}: RESTORE {o.value} != original {core.original}")
        if o.action == M.A_RESTORE and i.rx_age_ms > c.rx_fresh_ms:
            bad.append(f"{tag}: RESTORE while the inverter has not answered for {i.rx_age_ms} ms")
        if o.action != M.A_NONE and (i.rtc_busy or i.mutex_busy):
            bad.append(f"{tag}: action on a busy bus")
        if o.action != M.A_NONE and (o.seq == 0 or o.seq == before["seq"] or o.seq != core.op_seq):
            bad.append(f"{tag}: action without a fresh sequence number ({before['seq']} -> {o.seq})")
        if before["op_pending"] and not valid and o.action != M.A_NONE and \
                M.elapsed(i.now_ms, before["op_start_ms"]) < c.op_timeout_ms:
            bad.append(f"{tag}: action with an operation outstanding")
        if valid and i.op in (M.OP_NO_ANSWER, M.OP_DEFERRED) and before["state"] == M.RESTORING and (
                core.state == M.FAULT or core.restore_attempts >= before["restore_attempts"]):
            bad.append(f"{tag}: an unanswered or deferred restore spent an attempt or latched FAULT")
        if core.changes > c.max_changes or core.writes_night > c.night_write_ceiling or \
                core.restore_attempts > c.max_restore_attempts:
            bad.append(f"{tag}: budget exceeded {core.changes}/{core.writes_night}/{core.restore_attempts}")
        if before["state"] == M.ARMED and i.arm and i.start and not o.disarm:
            bad.append(f"{tag}: START did not consume the arm")
        if before["state"] in (M.IDLE, M.ARMED, M.FAULT) and o.action != M.A_NONE and not (
                (before["state"] == M.ARMED and o.action == M.A_WRITE) or
                (before["state"] == M.FAULT and o.action == M.A_RESTORE and i.restore_req and not i.ack and
                 before["original"] != 0)):
            bad.append(f"{tag}: action from state {before['state']}")
        st, _ = M.decode_record(M.encode_record(core.record()), c)
        if st != M.DEC_OK:
            bad.append(f"{tag}: the core's own record does not decode ({st})")

    states_seen = set()
    for k in range(sequences):
        _, items = VR.fuzz_items(FUZZ_SEED + k, M, check=chk)
        if len(bad) > 20:
            break
    for k in range(min(sequences, 40)):
        cfg, items = VR.fuzz_items(FUZZ_SEED + k, M)
        for line in VR.run_items(cfg, items, M):
            if not line.startswith(("REC", "BOOT")):
                states_seen.add(int(line.split()[0]))
    if sequences >= 100 and states_seen != set(range(7)):
        bad.append(f"fuzz reached only states {sorted(states_seen)}")
    return bad


EXPECTED_FAULT_OUTCOME = {
    "ha_outage": "R_PLAN_LOST", "telemetry_freeze": "R_TELEMETRY_STALE", "foreign_write": "R_FOREIGN",
    "reboot_mid_lease": "R_BOOT_RECOVERY", "reboot_twice": "R_BOOT_RECOVERY", "write_fail": "R_WRITE_FAILED",
    "restore_fail_twice": "R_END", "restore_fail_always": "R_RESTORE_FAILED", "commit_fail": "R_WRITE_FAILED",
    "rtc_busy_long": "R_RTC_STUCK", "slot_not_binding": "R_NO_RESPONSE", "wrong_direction": "R_WRONG_DIRECTION",
    "planner_too_low": "R_TARGET_GUARD", "owner_end": "R_END",
    "modbus_down_2min_guard": "R_TELEMETRY_STALE", "modbus_down_5min_guard": "R_TELEMETRY_STALE",
    "modbus_down_10min_guard": "R_TELEMETRY_STALE", "modbus_down_2min_boot": "R_BOOT_RECOVERY",
    "modbus_down_5min_boot": "R_BOOT_RECOVERY", "modbus_down_10min_boot": "R_BOOT_RECOVERY",
    "inverter_rounds": "R_READBACK_MISMATCH", "inverter_clamps": "R_READBACK_MISMATCH", "grid_outage": "R_GRID_LOSS",
}
# the nights after which the slot power must be the original again (the simulator checks it; these may not end in
# FAULT, and must spend at most one restore attempt)
MUST_RESTORE = ("modbus_down_2min_guard", "modbus_down_5min_guard", "modbus_down_10min_guard", "modbus_down_2min_boot",
                "modbus_down_5min_boot", "modbus_down_10min_boot", "inverter_rounds", "inverter_clamps", "grid_outage")


def battery_sim(M, normal: int = 80, report: bool = False) -> list[str]:
    bad: list[str] = []
    leased = worse = 0
    ratios = []
    for sc in S.normal_scenarios(normal, 1000):
        r, b = S.run_night(sc, M), S.baseline(sc)
        bad += [f"normal seed {sc.seed}: {x}" for x in r["viol"][:3]]
        if r["leased_at"] >= 0:
            leased += 1
            ratios.append(r["mean_lease_w"] / max(1.0, b["peak_w"]))
            if 0 <= b["reached_s"] <= 300 * 60 and not 0 <= r["reached_s"] <= 300 * 60:
                worse += 1
                bad.append(f"normal seed {sc.seed}: target reached today at {b['reached_s']} s, missed with the GRC")
    if normal >= 40:
        if leased < normal * 3 // 4:
            bad.append(f"only {leased} of {normal} normal nights leased")
        if ratios and sum(ratios) / len(ratios) > 0.8:
            bad.append(f"not gentler: mean lease power {sum(ratios) / len(ratios):.2f} of today's peak")
    outcomes = {}
    for sc in S.fault_scenarios(500):
        r = S.run_night(sc, M)
        outcomes[sc.name] = r["last_reason"]
        bad += [f"{sc.name}: {x}" for x in r["viol"][:3]]
        want = EXPECTED_FAULT_OUTCOME.get(sc.name)
        if want and r["last_reason"] != want:
            bad.append(f"{sc.name}: ended {r['last_reason']}, designed {want}")
        if sc.name in MUST_RESTORE and (r["final_state"] != "IDLE" or r["final_reg"] != sc.original_sp):
            bad.append(f"{sc.name}: ended {r['final_state']} with the slot power at {r['final_reg']}")
        if not want and r["last_reason"] not in ("R_TARGET_REACHED", "R_DEADLINE", "R_TARGET_GUARD"):
            bad.append(f"{sc.name}: ended {r['last_reason']}")
    if report:
        print(f"        normal nights: {leased}/{normal} leased, {worse} worse than today, mean lease power "
              f"{(sum(ratios) / len(ratios) if ratios else 0):.2f} of today's peak")
        print("        fault nights: " + ", ".join(f"{k}={v}" for k, v in outcomes.items()))
    return bad


# ===========================================================================================================
# Mutants: (name, exact text in reference_model.py (must occur once), replacement)
# ===========================================================================================================
MUTANTS = [
    ("floor clamp removed", "return max(c.floor_w, min(ceiling, r))", "return min(ceiling, r)"),
    ("ceiling ignores the pre-lease value", "hard = min(self.original, c.fw_bound_w) // c.round_w * c.round_w",
     "hard = c.fw_bound_w // c.round_w * c.round_w"),
    ("ceiling ignores the owner limit", "ceiling = min(hard, owner)", "ceiling = hard"),
    ("ceiling not rounded down", "hard = min(self.original, c.fw_bound_w) // c.round_w * c.round_w",
     "hard = min(self.original, c.fw_bound_w)"),
    ("no step cap", "raw = max(self.v - c.max_step_w, min(self.v + c.max_step_w, raw))", "raw = raw"),
    ("rounding floors", "r = (raw + c.round_w // 2) // c.round_w * c.round_w", "r = raw // c.round_w * c.round_w"),
    ("no hysteresis in the lease", "        if abs(delta) < c.hyst_w:\n", "        if abs(delta) < 0:\n"),
    ("START ignores the hysteresis", "if abs(d - self.v) >= c.hyst_w:", "if abs(d - self.v) > 0:"),
    ("no reversal rule", "and abs(delta) < c.hyst_w + c.reversal_extra_w:", "and abs(delta) < c.hyst_w:"),
    ("dwell is the settle time", "if elapsed(i.now_ms, self.last_change_ms) < c.dwell_ms:",
     "if elapsed(i.now_ms, self.last_change_ms) < c.settle_ms:"),
    ("max changes off by one", "if self.bms_limited or self.changes >= c.max_changes:",
     "if self.bms_limited or self.changes > c.max_changes:"),
    ("no restore reservation in the lease",
     "        if self.writes_night + 1 > c.night_write_ceiling - c.max_restore_attempts:\n            return\n",
     "        if self.writes_night + 1 > c.night_write_ceiling:\n            return\n"),
    ("no restore reservation at START",
     "if self.writes_night + 1 > c.night_write_ceiling - c.max_restore_attempts:\n            return R_REFUSE_WRITE_BUDGET",
     "if self.writes_night + 1 > c.night_write_ceiling:\n            return R_REFUSE_WRITE_BUDGET"),
    ("END lost while a write is in flight",
     "        if i.end:\n            self.end_pending = True\n        if not i.grid_ok:\n            self.grid_pending = True\n"
     "        if st == ADJUSTING:\n            self._adjusting(i, o, res)\n            return o\n",
     "        if not i.grid_ok:\n            self.grid_pending = True\n        if st == ADJUSTING:\n"
     "            self._adjusting(i, o, res)\n            return o\n        if i.end:\n            self.end_pending = True\n"),
    ("lost wall clock ignored", "if i.epoch == 0 or i.local_min < 0:\n            return R_CLOCK_INVALID",
     "if False:\n            return R_CLOCK_INVALID"),
    ("clock change ignored in a lease", "if i.clock_change_night:\n            return R_CLOCK_CHANGE\n",
     "if False:\n            return R_CLOCK_CHANGE\n"),
    ("clock change night accepted at START", "if i.clock_change_night:\n            return R_REFUSE_CLOCK_CHANGE",
     "if False:\n            return R_REFUSE_CLOCK_CHANGE"),
    ("unknown inverter clock accepted in a lease",
     "if i.inv_skew_s < 0 or i.inv_skew_s > c.clock_skew_max_s:\n            return R_INVERTER_CLOCK",
     "if i.inv_skew_s > c.clock_skew_max_s:\n            return R_INVERTER_CLOCK"),
    ("deadline exclusive", "if i.epoch >= self.lease_end:", "if i.epoch > self.lease_end:"),
    ("no uptime watchdog", "if elapsed(i.now_ms, self.lease_start_ms) >= self.watchdog_ms:", "if False:"),
    ("other leases ignored", "if i.other != 0:\n            return R_OTHER_ACTIVITY", "if False:\n            return R_OTHER_ACTIVITY"),
    ("inverter fault ignored", "if i.fault:\n            return R_INVERTER_FAULT", "if False:\n            return R_INVERTER_FAULT"),
    ("telemetry age ignored in a lease",
     "if not i.tel_ok or i.tel_age_ms > c.telemetry_stale_ms:\n            return R_TELEMETRY_STALE",
     "if not i.tel_ok:\n            return R_TELEMETRY_STALE"),
    ("SOC jump unchecked", "if abs(i.soc - self.last_soc) > c.soc_jump_max or i.soc < self.soc_max - c.soc_drop_max:",
     "if i.soc < self.soc_max - c.soc_drop_max:"),
    ("SOC drop unchecked", "if abs(i.soc - self.last_soc) > c.soc_jump_max or i.soc < self.soc_max - c.soc_drop_max:",
     "if abs(i.soc - self.last_soc) > c.soc_jump_max:"),
    ("SOC above 100 % accepted in a lease", "if i.soc < 0 or i.soc > 1000:\n            return R_SOC_INVALID",
     "if i.soc < 0:\n            return R_SOC_INVALID"),
    ("plan age ignored", "if pl.age_ms > c.plan_max_age_ms:\n            return R_PLAN_LOST", "if False:\n            return R_PLAN_LOST"),
    ("plan target change ignored", "if pl.slot != self.slot or pl.target != self.target:", "if pl.slot != self.slot:"),
    ("deadline may move later", "if cand < self.lease_end:", "if cand != self.lease_end:"),
    ("configuration age ignored", "if i.cfg_age_ms > c.config_stale_ms:\n            return R_CONFIG_STALE",
     "if False:\n            return R_CONFIG_STALE"),
    ("slot drift ignored",
     "if not i.slot_grid or i.slot_target != self.target or not in_slot(i.local_min, i.slot_start_min, i.slot_end_min):\n"
     "            return R_CONFIG_DRIFT", "if False:\n            return R_CONFIG_DRIFT"),
    ("a foreign value is restored over", "                return R_FOREIGN\n        if i.soc >= self.target * 10:",
     "                return R_CONFIG_DRIFT\n        if i.soc >= self.target * 10:"),
    ("no ownership fence", "if elapsed(i.now_ms, self.last_change_ms) > i.cfg_age_ms:", "if True:"),
    ("target reached ignored", "if i.soc >= self.target * 10:\n            return R_TARGET_REACHED",
     "if False:\n            return R_TARGET_REACHED"),
    ("no target guard in a lease",
     "if self._guard_trips(i.epoch, i.soc, self.target, self.capacity_wh, self.p0, slot_end, self.taper):",
     "if False:"),
    ("target guard ignores the taper tail", "e_tail = (tgt - max(soc, knee)) * capacity_wh // 1000", "e_tail = 0"),
    ("target guard without its margin", "return epoch + t_need + c.guard_margin_s >= window_end - c.end_margin_s",
     "return epoch + t_need >= window_end - c.end_margin_s"),
    ("no runaway guard", "if self.runaway_n >= c.runaway_samples:", "if False:"),
    ("runaway threshold inclusive", "if s > self.p0 * c.runaway_pct // 100 + c.runaway_margin_w else 0",
     "if s >= self.p0 * c.runaway_pct // 100 + c.runaway_margin_w else 0"),
    ("no charge-stopped guard", "if self.stop_n >= c.stop_samples:", "if False:"),
    ("an RTC correction does not defer a change",
     "        if i.rtc_busy or i.mutex_busy:\n            return\n        d = self._desired(i)",
     "        if i.mutex_busy:\n            return\n        d = self._desired(i)"),
    ("a busy mutex does not defer a change",
     "        if i.rtc_busy or i.mutex_busy:\n            return\n        d = self._desired(i)",
     "        if i.rtc_busy:\n            return\n        d = self._desired(i)"),
    ("the restore ignores a busy bus", "if not due(i.now_ms, self.restore_next_ms) or i.rtc_busy or i.mutex_busy:",
     "if not due(i.now_ms, self.restore_next_ms):"),
    ("restore attempts unbounded",
     "if self.restore_attempts >= c.max_restore_attempts:\n                    self._fault(o, R_RESTORE_FAILED)",
     "if False:\n                    self._fault(o, R_RESTORE_FAILED)"),
    ("a FOREIGN restore result counts as restored",
     "                self._fault(o, R_FOREIGN)\n            elif res in (OP_NO_ANSWER, OP_DEFERRED):",
     "                self._clear_lease()\n                self.state = IDLE\n            elif res in (OP_NO_ANSWER, OP_DEFERRED):"),
    ("no restore backoff",
     "self.restore_next_ms = (i.now_ms + c.restore_backoff_ms) & MASK32\n                    o.event = R_RESTORE_RETRY",
     "self.restore_next_ms = i.now_ms\n                    o.event = R_RESTORE_RETRY"),
    ("wrong direction unchecked", "if dirn * act < 0 and abs(act) > c.wrong_dir_w:", "if False:"),
    ("weak responses never counted", "            self.ineffective += 1\n", "            self.ineffective += 0\n"),
    ("response gain unchecked",
     "if g < c.gain_min_pct or g > c.gain_max_pct:\n                self._begin_restore(i, o, R_IMPLAUSIBLE_GAIN)",
     "if False:\n                self._begin_restore(i, o, R_IMPLAUSIBLE_GAIN)"),
    ("the taper never recognised", "elif i.soc >= self.taper * 10:", "elif False:"),
    ("two leases a night", "if self.night_used:\n            return R_REFUSE_NIGHT_USED", "if False:\n            return R_REFUSE_NIGHT_USED"),
    ("the arm is not one-shot", "        o.disarm = True\n        self.arm_latch = True\n", "        o.disarm = True\n"),
    ("START without a running charge", "if i.batt_w < c.charging_min_w:\n            return R_REFUSE_NOT_CHARGING",
     "if False:\n            return R_REFUSE_NOT_CHARGING"),
    ("START too late accepted", "if lease_end - i.epoch < c.min_lease_s:", "if False:"),
    ("START with an implausible gain",
     "if g < c.gain_min_pct or g > c.gain_max_pct:\n            return R_REFUSE_IMPLAUSIBLE",
     "if False:\n            return R_REFUSE_IMPLAUSIBLE"),
    ("the arm never expires", "if elapsed(i.now_ms, self.armed_ms) >= c.arm_window_ms:", "if False:"),
    ("the pending value is not owned", "if live == v or live == p or (q >= 0 and live == q):",
     "if live == v or (q >= 0 and live == q):"),
    ("the record CRC is not checked",
     "if int.from_bytes(b[28:32], \"little\") != (zlib.crc32(bytes(b[0:28])) & MASK32):\n        return DEC_BAD_CRC, r",
     "if False:\n        return DEC_BAD_CRC, r"),
    ("an active record boots idle",
     "        if rec.flags & F_ACTIVE:\n            if self.restore_attempts >= self.c.max_restore_attempts:",
     "        if False:\n            if self.restore_attempts >= self.c.max_restore_attempts:"),
    ("the lease may outlast the slot (no window check at START)",
     "if abs(pl.window_end - slot_end) > c.window_match_s:\n            return R_REFUSE_SLOT",
     "if False:\n            return R_REFUSE_SLOT"),
    ("START ignores the slot's own target",
     "if not i.slot_grid or i.slot_target != pl.target or not in_slot(i.local_min, i.slot_start_min, i.slot_end_min):\n"
     "            return R_REFUSE_SLOT", "if not i.slot_grid:\n            return R_REFUSE_SLOT"),
    ("no operation timeout",
     "        elif elapsed(i.now_ms, self.op_start_ms) >= c.op_timeout_ms:\n            self._begin_restore(i, o, R_OP_TIMEOUT)",
     "        elif False:\n            self._begin_restore(i, o, R_OP_TIMEOUT)"),
    ("OK_NOWRITE accepted for a change", "        elif res == OP_OK_NOWRITE:\n            self._begin_restore(i, o, R_WRITE_FAILED)\n",
     ""),
    ("ACK without a fresh configuration read", "if i.ack and i.cfg_age_ms <= c.config_stale_ms:", "if i.ack:"),
    ("relative step ignores the realised power", "raw = self.v * plan_power(i.plan, i.epoch) // self.p_ref",
     "raw = plan_power(i.plan, i.epoch)"),
    ("plan points ignored after the first", "        if pl.t[k] <= epoch:\n            val = pl.p[k]",
     "        if pl.t[k] <= epoch:\n            val = pl.p[0]"),
    # ---- revision 2 (the review findings). B1: only answered restore failures count; the restore waits for the
    # inverter; the readback under the GRC's own lock is owned; the owner's Restore original in FAULT
    ("an unanswered restore spends an attempt", "self.restore_attempts = max(0, self.restore_attempts - 1)",
     "self.restore_attempts = self.restore_attempts"),
    ("an unanswered restore keeps its write",
     "                self.writes_night = max(0, self.writes_night - 1)\n                self.restore_next_ms",
     "                self.restore_next_ms"),
    ("an unanswered restore is retried without a backoff",
     "self.restore_next_ms = (i.now_ms + c.restore_backoff_ms) & MASK32\n                o.event = R_RESTORE_UNANSWERED",
     "self.restore_next_ms = i.now_ms\n                o.event = R_RESTORE_UNANSWERED"),
    ("an unanswered restore is a failure", "            elif res in (OP_NO_ANSWER, OP_DEFERRED):\n                # nothing was",
     "            elif False:\n                # nothing was"),
    ("the restore does not wait for the inverter to answer",
     "if i.rx_age_ms > c.rx_fresh_ms:\n            return\n        if self.writes_night + 1 > c.night_write_ceiling:",
     "if False:\n            return\n        if self.writes_night + 1 > c.night_write_ceiling:"),
    ("a clamped readback is not owned (revision 1: R_WRITE_FAILED, then FOREIGN)",
     "            self.q = i.op_value\n            self._begin_restore(i, o, R_READBACK_MISMATCH)",
     "            self._begin_restore(i, o, R_WRITE_FAILED)"),
    ("the classifier ignores the owned readback", "if live == v or live == p or (q >= 0 and live == q):",
     "if live == v or live == p:"),
    ("the restore's own readback is not owned",
     "                if res == OP_FAIL:\n                    self._own_readback(i)\n                if self.restore_attempts",
     "                if self.restore_attempts"),
    ("the owned readback is not persisted", "        if rb:\n            r.q = self.q\n", ""),
    ("the boot forgets the owned readback", "self.q = rec.q if rec.flags & F_READBACK else -1", "self.q = -1"),
    ("Restore original without a known original", "if self.original == 0 or busy or", "if busy or"),
    ("Restore original on a busy bus", "busy = i.rtc_busy or i.mutex_busy or i.rx_age_ms > c.rx_fresh_ms",
     "busy = i.rx_age_ms > c.rx_fresh_ms"),
    ("Restore original on a silent inverter", "busy = i.rtc_busy or i.mutex_busy or i.rx_age_ms > c.rx_fresh_ms",
     "busy = i.rtc_busy or i.mutex_busy"),
    ("Restore original beyond the night's write ceiling",
     "if self.original == 0 or busy or self.writes_night + 1 > c.night_write_ceiling:",
     "if self.original == 0 or busy:"),
    ("FAULT restores without the owner's pulse", "        if i.restore_req:\n            busy =",
     "        if True:\n            busy ="),
    ("an unanswered Restore original keeps its write",
     "                self.writes_night = max(0, self.writes_night - 1)\n                o.event = R_RESTORE_UNANSWERED",
     "                o.event = R_RESTORE_UNANSWERED"),
    # M2: results are tagged with the action's sequence number and kind
    ("a result is taken whatever its sequence",
     "if self.op_pending and i.op_seq == self.op_seq and i.op_kind == self.op_kind:",
     "if self.op_pending and i.op_kind == self.op_kind:"),
    ("a result is taken whatever its kind",
     "if self.op_pending and i.op_seq == self.op_seq and i.op_kind == self.op_kind:",
     "if self.op_pending and i.op_seq == self.op_seq:"),
    ("a result is taken without an outstanding operation",
     "if self.op_pending and i.op_seq == self.op_seq and i.op_kind == self.op_kind:",
     "if i.op_seq == self.op_seq and i.op_kind == self.op_kind:"),
    ("the sequence number does not advance", "self.seq = (self.seq + 1) & MASK32", "self.seq = self.seq & MASK32"),
    ("a deferred change does not end the lease", "        elif res == OP_DEFERRED:\n            self._begin_restore",
     "        elif False:\n            self._begin_restore"),
    ("an unanswered change does not end the lease", "        elif res == OP_NO_ANSWER:\n            self._begin_restore",
     "        elif False:\n            self._begin_restore"),
    # M3: the plan is cross-checked against the firmware's own bounds
    ("the revision 1 slot check: the plan's window end trusted",
     "        slot_end = slot_end_epoch(i.epoch, i.local_min, i.slot_end_min)\n"
     "        if abs(pl.window_end - slot_end) > c.window_match_s:\n            return R_REFUSE_SLOT\n"
     "        lease_end = min(pl.deadline, slot_end - c.end_margin_s)\n",
     "        slot_end = pl.window_end\n        lease_end = min(pl.deadline, pl.window_end - c.end_margin_s)\n"
     "        if lease_end - i.epoch > mod1440(i.slot_end_min - i.local_min) * 60 - 60:\n            return R_REFUSE_SLOT\n"),
    ("the plan's window end is not checked in a lease",
     "if abs(pl.window_end - slot_end) > c.window_match_s:\n            return R_PLAN_WINDOW",
     "if False:\n            return R_PLAN_WINDOW"),
    ("the target guard uses the plan's window end",
     "if self._guard_trips(i.epoch, i.soc, self.target, self.capacity_wh, self.p0, slot_end, self.taper):",
     "if self._guard_trips(i.epoch, i.soc, self.target, self.capacity_wh, self.p0, pl.window_end, self.taper):"),
    ("the lease end ignores the slot's own end",
     "self.lease_end = min(pl.deadline, slot_end_epoch(i.epoch, i.local_min, i.slot_end_min) - c.end_margin_s)",
     "self.lease_end = min(pl.deadline, pl.window_end - c.end_margin_s)"),
    ("the lease end stops following the slot's own end", "cand = min(pl.deadline, slot_end - c.end_margin_s)",
     "cand = min(pl.deadline, pl.window_end - c.end_margin_s)"),
    ("the slot end does not wrap midnight", "return epoch + mod1440(slot_end_min - local_min) * 60 - 60",
     "return epoch + (slot_end_min - local_min) * 60 - 60"),
    ("the in_slot wrap branch is never true", "    if start > end:\n        return m >= start or m < end",
     "    if start > end:\n        return False"),
    ("no capacity floor at START",
     "if self._guard_trips(i.epoch, i.soc, pl.target, max(pl.capacity_wh, c.capacity_floor_wh), i.batt_w, slot_end,",
     "if self._guard_trips(i.epoch, i.soc, pl.target, pl.capacity_wh, i.batt_w, slot_end,"),
    ("no capacity floor in the lease", "self.capacity_wh = max(pl.capacity_wh, c.capacity_floor_wh)",
     "self.capacity_wh = pl.capacity_wh"),
    ("a later plan may lower the guard's capacity", "if cap > self.capacity_wh:", "if cap != self.capacity_wh:"),
    ("the guard accepts any taper knee", "knee = min(tgt, min(taper, c.taper_max_pct) * 10)", "knee = min(tgt, taper * 10)"),
    ("the owner ceiling bypasses the step cap (revision 1)",
     "owner = max(i.plan.ceiling_w, (max(0, self.v - c.max_step_w) + c.round_w - 1) // c.round_w * c.round_w)",
     "owner = i.plan.ceiling_w"),
    # M4: a direct grid-loss input
    ("grid loss ignored in a lease", "if self.grid_pending:\n            return R_GRID_LOSS",
     "if False:\n            return R_GRID_LOSS"),
    ("START with the grid lost", "if not i.grid_ok:\n            return R_REFUSE_GRID", "if False:\n            return R_REFUSE_GRID"),
    ("grid loss not latched while a write is in flight",
     "        if not i.grid_ok:\n            self.grid_pending = True\n        if st == ADJUSTING:\n"
     "            self._adjusting(i, o, res)\n            return o\n",
     "        if st == ADJUSTING:\n            self._adjusting(i, o, res)\n            return o\n"
     "        if not i.grid_ok:\n            self.grid_pending = True\n"),
    ("grid loss not acted on at the verified write", "            if self.grid_pending:\n                self._begin_restore",
     "            if False:\n                self._begin_restore"),
    ("END outranks grid loss",
     "        if self.grid_pending:\n            return R_GRID_LOSS\n        if self.end_pending:\n            return R_END\n",
     "        if self.end_pending:\n            return R_END\n        if self.grid_pending:\n            return R_GRID_LOSS\n"),
    # M5: the restore operation timeout (it survived every battery in revision 1)
    ("no restore operation timeout",
     "            elif res == OP_FAIL or elapsed(i.now_ms, self.op_start_ms) >= c.op_timeout_ms:\n"
     "                self.op_pending = False\n                if res == OP_FAIL:\n                    self._own_readback(i)\n"
     "                if self.restore_attempts",
     "            elif res == OP_FAIL:\n"
     "                self.op_pending = False\n                if res == OP_FAIL:\n                    self._own_readback(i)\n"
     "                if self.restore_attempts"),
]


def run_batteries(M, quick: bool) -> list[str]:
    for fn in (battery_vectors, battery_units):
        bad = fn(M)
        if bad:
            return bad
    bad = battery_fuzz(M, 60 if quick else FUZZ_SEQUENCES)
    if bad:
        return bad
    return battery_sim(M, 24 if quick else 80)


def main() -> int:
    M = load_model()
    print("[1] golden vectors")
    bad = battery_vectors(M)
    n = len(VR.load_vectors())
    check(f"all {n} vectors meet their hand-computed expectations", not bad, "; ".join(bad[:5]))
    import subprocess
    gen = subprocess.run([sys.executable, "-I", "-B", "-X", "utf8", "-c",
                          "import sys, json; sys.path.insert(0, sys.argv[1]); import make_vectors as m; "
                          "print(json.dumps({'vectors': m.V, 'units': m.UNITS}, sort_keys=True))", str(HERE)],
                         capture_output=True, text=True)
    doc = json.loads((HERE / "vectors.json").read_text(encoding="utf-8"))
    fresh = gen.returncode == 0 and json.loads(gen.stdout) == {"vectors": doc["vectors"], "units": doc["units"]}
    check("vectors.json is exactly what make_vectors.py writes", fresh, gen.stderr[-300:])
    check("at least 100 vectors", n >= 100, str(n))

    print("[2] unit vectors: classifier, record, configuration")
    bad = battery_units(M)
    check("classifier, decode statuses, round trip, every corruption and truncation rejected, config_ok", not bad,
          "; ".join(bad[:5]))

    print(f"[3] properties on {FUZZ_SEQUENCES} seeded fuzz sequences (seed {FUZZ_SEED})")
    bad = battery_fuzz(M)
    check("no property violated, all seven states reached", not bad, "; ".join(bad[:5]))

    print("[4] closed loop against the independent truth battery (simulator.py)")
    bad = battery_sim(M, 80, report=True)
    check(f"80 normal + {len(S.fault_scenarios(500))} fault nights: no violation, never worse than today, gentler, "
          "designed fault outcomes",
          not bad, "; ".join(bad[:5]))

    print(f"[5] mutation ({len(MUTANTS)} mutants)")
    src = (HERE / "reference_model.py").read_text(encoding="utf-8")
    survivors = []
    for k, (name, old, new) in enumerate(MUTANTS):
        if src.count(old) != 1:
            check(f"mutant '{name}' applies exactly once", False, f"found {src.count(old)} times")
            continue
        Mm = load_model(src.replace(old, new), f"grc_mutant_{k}")
        try:
            bad = run_batteries(Mm, quick=True)
        except Exception as e:  # a crash is a kill too
            bad = [f"crash {type(e).__name__}: {e}"]
        if not bad:
            survivors.append(name)
        print(f"        {'killed' if bad else 'SURVIVED'}: {name}" + (f"  <- {bad[0][:90]}" if bad else ""))
    check(f"every one of {len(MUTANTS)} mutants is killed (at least 100)", not survivors and len(MUTANTS) >= 100,
          ", ".join(survivors))
    sys.modules["grc_reference_model"] = M

    print("")
    if FAILURES:
        print(f"FAILED: {len(FAILURES)} check(s): " + "; ".join(FAILURES))
        return 1
    print("ALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
