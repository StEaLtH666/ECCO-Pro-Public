#!/usr/bin/env python3
"""Dump-to-Grid V2 ownership EVIDENCE (schema + write-ahead maintenance only).

What Dump V2 adds (firmware/include/ecco_durable_snapshot.h,
DumpToGridSnapshotData): one durable uint16 `reg_dump_power_pending` (P) next
to the existing `reg_dump_power_intended` (V), under a NEW data tag
`ecco_dump_to_grid_snapshot_data_v2`, so that after a reboot the durable
record contains every 256-261 ceiling Dump itself may have left live:
ORIGINAL[i], V and P. Plus a V1 rollback TOMBSTONE written at START.

What it deliberately does NOT add: any consumer of that evidence. Restore,
Force Restore Original, Accept Current State, SG-02 containment and R3 are
frozen; the ownership classifier exists only as a test-side reference model
(_dump_v2_evidence_model.py).

Every behavioural check EXECUTES the real firmware source through
registry/tests/_dump_sim.py. The pre-V2 firmware is rebuilt byte-for-byte from
the current file by _dump_v2_scope.pre_dump_v2_firmware() and run side by side
for the differential checks. Since the rebase onto main @ 37f9958 that is main
INCLUDING Manual TOU Phase 1 (PR #53); reverting Manual TOU Phase 1's own edits
(_mtou1_scope.py) on top of it still reproduces main @ 004040b exactly, which
keeps the original byte-for-byte pin.

  [1]  V2 layout / golden vectors (header static_asserts vs Python mirror)
  [2]  tag / version separation (V2 tag, V1 historical, marker tag unchanged)
  [3]  START: evidence initialisation, V1 tombstone, commit ordering
  [4]  controller: save-before-write ordering, R3 gate, verified/pending transitions
  [5]  power-cut sweep A..H over START and every controller write boundary,
       with a double-reboot + request_dump_end chain at every cut
  [6]  request_dump_end / on_boot preserve P (mid-write End, reboot)
  [7]  V2 boot rules (marker x data matrix) and legacy V1 obligations
  [8]  V1 tombstone vs the pre-V2 (main @ 004040b) loader
  [9]  frozen: restore / Accept / Force / containment / clear-only / R3 /
       watchdog - structural pins and base-vs-V2 differential runs
  [10] durable resource impact: commits per write, per lease, budget, physical
       vs logical writes, repeated request_dump_end
  [11] reference classifier: no false FOREIGN on Dump's own residue;
       test-only evidence plausibility
  [12] mutation tests (every addendum mutant)

No I/O beyond reading the repository, no hardware, no ESPHome toolchain.
"""

from __future__ import annotations

import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))

import _dump_sim as ds  # noqa: E402
import _dump_v2_evidence_model as dv2  # noqa: E402
import _dump_v2_scope as dv2s  # noqa: E402
import _free_power_action_sim as fpsim  # noqa: E402
import _mtou1_scope as mtou1  # noqa: E402 - Manual TOU Phase 1 (PR #53) landed on main after the Dump V2 base
import _scope_chain as chain  # noqa: E402 - FB-T0: the ABSOLUTE base pin in [8] is evaluated as of chain entry "dump_v2"

FAILURES: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  PASS  {name}")
    else:
        FAILURES.append(name)
        print(f"  FAIL  {name}" + (f" - {detail}" if detail else ""))


FW_PATH = ROOT / "firmware" / "ecco_clock_dongle_stage3_4_free_power.yaml"
HEADER_PATH = ROOT / "firmware" / "include" / "ecco_durable_snapshot.h"
FW_TEXT = FW_PATH.read_text(encoding="utf-8")
HEADER = HEADER_PATH.read_text(encoding="utf-8")
FW = ds.load_firmware_text(FW_TEXT)
BASE_TEXT = dv2s.pre_dump_v2_firmware(FW_TEXT)
BASE_FW = ds.load_firmware_text(BASE_TEXT)
BASE_HEADER = dv2s.pre_dump_v2_header(HEADER)

V1_TAG, V2_TAG, VALID_TAG = dv2.V1_TAG, dv2.V2_TAG, dv2.VALID_TAG
RETRY_TAG = "ecco_dump_to_grid_retry_state_v1"
ORIGINAL = {244: 2, 256: 8000, 257: 8000, 258: 7000, 259: 8000, 260: 8000, 261: 5000}
CEIL = tuple(range(256, 262))
RR, CLEAR, PENDING_CLEAR = 1, 0, 2
MAGIC = ds.Durable.VALID_MARKER_MAGIC
HEADER_TAGS = dv2.header_tags(HEADER)
BASE_HEADER_TAGS = dv2.header_tags(BASE_HEADER)


def mutant_fw(old: str, new: str) -> dict:
    if FW_TEXT.count(old) != 1:
        raise AssertionError(f"mutation anchor not unique/present ({FW_TEXT.count(old)}x): {old[:90]!r}")
    return ds.load_firmware_text(FW_TEXT.replace(old, new))


def apply_tags(sim: ds.Sim, tags: dict) -> ds.Sim:
    """Point the sim's ecco_durable tag constants at a (possibly mutated)
    header's resolved tags - the firmware only ever names the constants."""
    for name in ("DUMP_TO_GRID_DATA_TAG", "DUMP_TO_GRID_DATA_TAG_V1", "DUMP_TO_GRID_DATA_TAG_V2",
                 "DUMP_TO_GRID_VALID_TAG", "DUMP_TO_GRID_RETRY_TAG"):
        if name in tags:
            setattr(sim.D, name, tags[name])
    return sim


def new_sim(fw=None, tags=None) -> ds.Sim:
    fw = fw or FW
    sim = ds.Sim(fw)
    if tags is None:
        tags = BASE_HEADER_TAGS if fw is BASE_FW else HEADER_TAGS
    return apply_tags(sim, tags)


# ---------------------------------------------------------------------------
# Scenario helpers (same model as test_dump_to_grid_behaviour.py's fresh()/tick())
# ---------------------------------------------------------------------------
_WATCHDOGS: dict = {}


def watchdog_of(fw) -> list:
    key = fw["_text"]
    if key not in _WATCHDOGS:
        _WATCHDOGS[key] = ds.find_interval(fw, "dump_overpower_samples")
    return _WATCHDOGS[key]


def config_poll(sim: ds.Sim) -> None:
    sim.g["cfg_block_b_dispatch_seq"] += 1
    sim.g["manual_cfg_reg244_raw"] = sim.bank.get(244, 0)
    for r in CEIL:
        sim.g[f"manual_cfg_reg{r}_raw"] = sim.bank.get(r, 0)
    sim.g["cfg_block_b_seq"] += 1
    sim.g["cfg_block_b_ok_ms"] = sim.millis()
    sim.g["cfg_block_b_response_dispatch_seq"] = sim.g["cfg_block_b_dispatch_seq"]


def fresh(fw=None, tags=None, target=500, grid_w=2000.0, duration=90.0, original=None) -> ds.Sim:
    sim = new_sim(fw, tags)
    sim.bank.update(original or ORIGINAL)
    sim.ent("dump_export_power").set(float(target))
    sim.ent("dump_stop_soc").set(25.0)
    sim.ent("dump_duration_minutes").set(float(duration))
    sim.ent("dump_write_enable").state = True
    sim.ent("dump_recovery_arm").state = False
    sim.ent("configuration_online").state = True
    sim.ent("configuration_polling").state = True
    sim.ent("ecco_battery_voltage").set(52.0)
    sim.g["ntp_synced"] = True
    sim.hour, sim.minute = 14, 0
    for i, t in enumerate([0, 530, 800, 1600, 1900, 2330]):
        sim.g[f"manual_cfg_reg{250 + i}_raw"] = t
    for i, f in enumerate([1, 0, 0, 0, 0, 0]):
        sim.g[f"manual_cfg_reg{274 + i}_raw"] = f
    config_poll(sim)
    sim.ent("ecco_battery_soc").publish_state(70.0)
    sim.grid_w = float(grid_w)
    sim.ent("ecco_grid_ct_power").publish_state(sim.grid_w)
    return sim


def tick(sim: ds.Sim, grid_w=None, ms=15000) -> None:
    sim.advance(ms)
    sim.ent("ecco_battery_soc").publish_state(70.0)
    if grid_w is not None:
        sim.grid_w = grid_w
    sim.ent("ecco_grid_ct_power").publish_state(sim.grid_w)
    config_poll(sim)
    sim.run_actions(watchdog_of(sim.fw))


def marker_state(sim):
    rec = sim.nvs.get(VALID_TAG)
    return None if rec is None else rec.state


def data_key(sim) -> str:
    return sim.D.DUMP_TO_GRID_DATA_TAG


def evidence(rec) -> tuple:
    return int(rec.reg_dump_power_intended), int(rec.reg_dump_power_pending)


def controller_held(sim) -> bool:
    return bool(sim.g["manual_write_in_progress"]) and not sim.g["dump_operation_in_progress"]


# Grid samples that drive exactly three controller writes 500 -> 1500 -> 2300
# -> 2100 (target 500W export): tick 3, 6 and 9 of the lease.
GRID_SCHEDULE = [2000.0, 2000.0, 2000.0, 1000.0, 1000.0, 1000.0, -900.0, -900.0, -900.0]
CEILINGS = [500, 1500, 2300, 2100]


class Runner:
    """Runs START + the three-write lease with per-attempt injections:
    plans[k] (k = 1-based controller write ATTEMPT, counted at its evidence
    commit) may set: evidence_fail, r3 ('ok'|'error'|'no_response'|
    'not_sent'|'timeout'|'third_party_P'), write (any ds WRITE outcome, or
    'partial_N' = the first N registers land, response lost), verify ('ok'|
    'error'|'no_response'|'timeout'|'mismatch'), end_mid (request_dump_end
    fires as the FC16 is dispatched). start_write sets START's own 256-261
    FC16 outcome. `on_event(sim, event, label)` sees every durable/Modbus
    event at the instant it took effect (a power-cut point)."""

    def __init__(self, fw=None, tags=None, plans=None, start_write="ok", on_event=None, ticks=9):
        self.plans = plans or {}
        self.attempt = 0
        self.phase = None
        self.on_event = on_event
        self.labels = Counter()
        sim = self.sim = fresh(fw, tags)
        self._real_w, self._real_r = sim._modbus_write, sim._modbus_read
        self._real_c = sim.D.commit_record
        sim._modbus_write = self._write
        sim._modbus_read = self._read
        sim.D.commit_record = self._commit
        sim.event_hook = self._event
        self.start_write = start_write
        sim.execute("start_dump_to_grid_override")
        self.started = bool(sim.g["dump_active_persisted"])
        for i in range(ticks if self.started else 0):
            self.capture("A/H tick start")
            tick(sim, GRID_SCHEDULE[i] if i < len(GRID_SCHEDULE) else None)
            self.capture("G tick end")

    # -- injection --
    def plan(self) -> dict:
        return self.plans.get(self.attempt, {})

    def _commit(self, key, record):
        sim = self.sim
        if key == data_key(sim) and controller_held(sim):
            self.attempt += 1
            self.phase = "r3"
            if self.plan().get("evidence_fail"):
                sim.nvs_commits.append((key, record.copy()))
                sim._log_event(("commit", key, record.copy(), False))
                return False
        return self._real_c(key, record)

    def _with_outcome(self, fn, outcome, body, local):
        sim = self.sim
        saved = sim.outcome_fn
        sim.outcome_fn = lambda kind, addr, count: outcome
        try:
            fn(body, local)
        finally:
            sim.outcome_fn = saved

    def _write(self, body, local):
        sim = self.sim
        addr = int(body["start_address"])
        if addr == 256 and sim.g["dump_operation_in_progress"] and not sim.g["dump_active_persisted"] \
                and not sim.g["dump_restore_requested"] and self.start_write != "ok":
            outcome, self.start_write = self.start_write, "ok"
            return self._apply_write(body, local, outcome)
        if addr == 256 and controller_held(sim):
            p = self.plan()
            self.phase = "verify"
            if p.get("end_mid"):
                sim.execute("request_dump_end", {"reason": ds.CStr("manual End button")})
            return self._apply_write(body, local, p.get("write", "ok"))
        return self._real_w(body, local)

    def _apply_write(self, body, local, outcome):
        sim = self.sim
        if outcome.startswith("partial_"):
            n = int(outcome.split("_")[1])
            addr = int(body["start_address"])
            vals = sim.run_lambda(body["values"], local, params=tuple((local or {}).keys()))
            sim.modbus_log.append(("write", addr, list(vals), outcome))
            for i, v in enumerate(vals[:n]):
                sim.bank[addr + i] = v
            sim._log_event(("write", addr, list(vals), outcome))
            sim._handler(body, "on_no_response", local)
            return None
        return self._with_outcome(self._real_w, outcome, body, local)

    def _read(self, body, local):
        sim = self.sim
        addr = int(body["start_address"])
        if addr == 256 and controller_held(sim):
            if self.phase not in ("r3", "verify"):
                # A controller critical section with no evidence commit
                # before its R3 read: the pre-V2 base firmware (differential
                # runs) - the attempt starts here instead.
                self.attempt += 1
                self.phase = "r3"
            p = self.plan()
            if self.phase == "r3":
                self.phase = "write"
                o = p.get("r3", "ok")
                if o == "third_party_P":
                    for r in CEIL:
                        sim.bank[r] = sim.g["dump_controller_pending_ceiling"]
                    o = "ok"
                return self._with_outcome(self._real_r, o, body, local)
            o = p.get("verify", "ok")
            self.phase = None
            if o == "mismatch":
                saved = sim.read_override_fn
                sim.read_override_fn = lambda a, c, v: [v[0], v[1], (v[2] + 100) & 0xFFFF] + list(v[3:])
                try:
                    return self._with_outcome(self._real_r, "ok", body, local)
                finally:
                    sim.read_override_fn = saved
            return self._with_outcome(self._real_r, o, body, local)
        return self._real_r(body, local)

    # -- power-cut capture --
    def _event(self, event):
        sim = self.sim
        kind = event[0]
        label = "other"
        if controller_held(sim):
            if kind == "commit" and event[1] == data_key(sim):
                label = "B evidence commit" if event[3] else "B' evidence commit FAILED"
            elif kind == "read" and event[1] == 256:
                label = "R3 read" if self.phase == "write" else "F verify read (before V advances)"
            elif kind == "write" and event[1] == 256:
                o = event[3]
                label = {"ack_not_applied": "C ack, not applied", "no_response_landed": "D applied, response lost",
                         "timeout_landed": "D applied, response lost", "ok": "E applied, before verify",
                         }.get(o, "D partial landing" if str(o).startswith("partial_") else "write not landed")
        elif sim.g["dump_operation_in_progress"] and not sim.g["dump_active_persisted"] and not sim.g["dump_restore_requested"]:
            label = "START " + kind
        self.capture(label)

    def capture(self, label):
        self.labels[label] += 1
        if self.on_event:
            self.on_event(self.sim, label)


# ---------------------------------------------------------------------------
# Boot helpers (Dump boot block + the arbitration/containment seed block)
# ---------------------------------------------------------------------------
def _boot_text(fw) -> str:
    return fw["esphome"]["on_boot"]["then"][0]["lambda"]


def dump_boot_block(fw) -> str:
    boot = _boot_text(fw)
    start = boot.index("// Manual Dump-to-Grid V1 (2026-09-26) - same fail-closed marker/")
    end_pub = boot.index('id(dump_status).publish_state("Inactive");', start)
    return boot[start:boot.index("}", end_pub) + 1]


def arbitration_block(fw) -> str:
    boot = _boot_text(fw)
    start = boot.index("// S4 fix (2026-09-27")
    return boot[start:boot.index("if (id(free_power_recovery_metadata_corrupt)) {", start)]


def reset_ram(sim: ds.Sim) -> None:
    """A power cycle for a REUSED sim (keeps its compiled-lambda cache):
    every global back to its initial value, no entities, no logs."""
    for g in sim.fw["globals"]:
        sim.g[g["id"]] = ds.Sim._initial(g["type"], g.get("initial_value"))
    sim.entities = {"ntp_time": ds.Clock(sim, "ntp_time")}
    sim.reset_durable()
    sim.modbus_log, sim.running, sim.executed = [], set(), []
    sim.outcome_fn = lambda kind, addr, count: "ok"
    sim.read_override_fn, sim.event_hook, sim.bus_idle = None, None, True
    sim.ent("configuration_online").state = True
    sim.ent("configuration_polling").state = True
    sim.ent("dump_write_enable").state = False
    sim.ent("dump_recovery_arm").state = False


def boot_into(sim: ds.Sim, nvs: dict, bank: dict, fail_load=()) -> ds.Sim:
    reset_ram(sim)
    sim.nvs = {k: v.copy() for k, v in nvs.items()}
    sim.bank = dict(bank)
    sim.nvs_fail_load_tags = set(fail_load)
    sim.run_lambda(dump_boot_block(sim.fw))
    sim.run_lambda(arbitration_block(sim.fw))
    return sim


def booted(nvs: dict, bank=None, fw=None, tags=None, fail_load=()) -> ds.Sim:
    return boot_into(new_sim(fw, tags), nvs, dict(ORIGINAL if bank is None else bank), fail_load)


def nvs_copy(sim) -> dict:
    return {k: v.copy() for k, v in sim.nvs.items()}


def fingerprint(nvs: dict) -> tuple:
    return tuple(sorted((k, v._kind, tuple(getattr(v, f) for f in ds._RECORD_FIELDS[v._kind])) for k, v in nvs.items()))


def v2_record(active=1, requested=0, intended=1000, pending=1000, original=None, end_epoch=0):
    o = original or ORIGINAL
    return ds.Record(dv2.V2_KIND, end_epoch, active, requested, o[244], *[o[r] for r in CEIL], intended, pending)


def v1_record(intended=1000, original=None, reg244=None):
    o = original or ORIGINAL
    return ds.Record(dv2.V1_KIND, 0, 1, 0, o[244] if reg244 is None else reg244, *[o[r] for r in CEIL], intended)


def tombstone():
    return ds.Record(dv2.V1_KIND, 0, 0, 0, dv2.V1_TOMBSTONE_REG244, 0, 0, 0, 0, 0, 0, 0)


def marker(state):
    return ds.Record("ValidMarker", MAGIC, state)


# ---------------------------------------------------------------------------
# The evidence property, checked at every power-cut point
# ---------------------------------------------------------------------------
class Sweep:
    """Collects every power-cut state (durable store + live bank) and checks:
      1. marker RESTORE_REQUIRED => a V2 record exists, the V1 key holds the
         tombstone, and the V2 evidence set contains every live 256-261 value
         (the reference classifier finds NO FOREIGN register);
      2. neither evidence field is ever 0 (no "none" sentinel);
      3. reboot: on_boot trusts it and loads V into dump_target_power and P
         into dump_evidence_pending_ceiling; request_dump_end's rebuild
         (restore deferred - bus busy) keeps V and P; a SECOND reboot of that
         rebuilt store still covers the bank and the (blind) restore puts
         back exactly ORIGINAL."""

    def __init__(self, fw=None, tags=None, reboot=True):
        self.fw, self.tags, self.reboot = fw or FW, tags, reboot
        self.bad: list = []
        self.seen: set = set()
        self.checked = Counter()
        self.evidence_seen: set = set()
        self._rsim = None

    def rsim(self) -> ds.Sim:
        if self._rsim is None:
            self._rsim = new_sim(self.fw, self.tags)
        return self._rsim

    def __call__(self, sim, label):
        self.observe(nvs_copy(sim), dict(sim.bank), label, sim.D.DUMP_TO_GRID_DATA_TAG,
                     sim.D.DUMP_TO_GRID_DATA_TAG_V1)

    def fail(self, label, why):
        if len(self.bad) < 12:
            self.bad.append(f"{label}: {why}")

    def observe(self, nvs, bank, label, dkey, v1key):
        m = nvs.get(VALID_TAG)
        if m is None or m.state != RR:
            return
        key = (fingerprint(nvs), tuple(sorted(bank.items())))
        self.checked[label] += 1
        if key in self.seen:
            return
        self.seen.add(key)
        rec = nvs.get(dkey)
        if rec is None or rec._kind != dv2.V2_KIND:
            return self.fail(label, "RESTORE_REQUIRED without a V2 record")
        t = nvs.get(v1key)
        if t is None or int(t.reg244) != dv2.V1_TOMBSTONE_REG244:
            return self.fail(label, f"RESTORE_REQUIRED but the V1 key is not the tombstone ({t and t.reg244})")
        self.evidence_seen.add(evidence(rec))
        if 0 in evidence(rec):
            return self.fail(label, f"evidence field is 0: {evidence(rec)}")
        un = dv2.uncovered(rec, bank)
        if un:
            return self.fail(label, f"live {un} not in evidence {{ORIGINAL, V, P}} = {evidence(rec)}")
        if any(c == dv2.FOREIGN for c in dv2.classify_bank(rec, bank).values()):
            return self.fail(label, "reference classifier calls Dump's own residue FOREIGN")
        if not self.reboot:
            return None
        r = boot_into(self.rsim(), nvs, bank)
        if not (r.g["dump_snapshot_valid"] and not r.g["dump_recovery_metadata_corrupt"]):
            return self.fail(label, "reboot did not trust the V2 obligation")
        if (r.g["dump_target_power"], r.g["dump_evidence_pending_ceiling"]) != evidence(rec):
            return self.fail(label, f"reboot mirrors {(r.g['dump_target_power'], r.g['dump_evidence_pending_ceiling'])} != {evidence(rec)}")
        r.bus_idle = False
        r.execute("request_dump_end", {"reason": ds.CStr("watchdog - restore retry")})
        rec2 = r.nvs.get(dkey)
        if rec2 is None or evidence(rec2) != evidence(rec) or dv2.uncovered(rec2, bank):
            return self.fail(label, f"request_dump_end rebuild changed evidence {evidence(rec)} -> {rec2 and evidence(rec2)}")
        r2 = boot_into(self.rsim(), nvs_copy(r), bank)
        if (r2.g["dump_target_power"], r2.g["dump_evidence_pending_ceiling"]) != evidence(rec):
            return self.fail(label, "second reboot lost the evidence")
        r2.execute("request_dump_end", {"reason": ds.CStr("watchdog - restore retry")})
        if {x: r2.bank.get(x) for x in ORIGINAL} != ORIGINAL or marker_state(r2) != CLEAR:
            return self.fail(label, f"blind restore after reboot did not restore ORIGINAL: {r2.status()}")
        if [(a, v) for k, a, v, o in r2.modbus_log if k == "write"] != [(244, [ORIGINAL[244]]), (256, [ORIGINAL[r] for r in CEIL])]:
            return self.fail(label, f"restore writes changed: {r2.modbus_log}")
        return None


R3_OUT = ("ok", "error", "no_response", "not_sent", "timeout")
WRITE_OUT = ("ok", "ack_not_applied", "error", "not_sent", "no_response_landed", "no_response_lost",
             "timeout_landed", "timeout_lost", "partial_1", "partial_3", "partial_5")
VERIFY_OUT = ("ok", "error", "no_response", "not_sent", "timeout", "mismatch")


def plan_space(attempts=(1, 2, 3)):
    """Every single-point injection at every controller write attempt."""
    yield "baseline", {}, "ok"
    for k in attempts:
        yield f"w{k} evidence commit fails", {k: {"evidence_fail": True}}, "ok"
        for o in R3_OUT[1:]:
            yield f"w{k} R3 {o}", {k: {"r3": o}}, "ok"
        for o in WRITE_OUT:
            yield f"w{k} FC16 {o}", {k: {"write": o}}, "ok"
            yield f"w{k} FC16 {o} + End mid-write", {k: {"write": o, "end_mid": True}}, "ok"
        for o in VERIFY_OUT[1:]:
            yield f"w{k} verify {o}", {k: {"verify": o}}, "ok"
    for o in WRITE_OUT[1:]:
        yield f"START FC16 {o}", {}, o


def run_sweep(fw=None, tags=None, attempts=(1, 2, 3), reboot=True, space=None):
    sw = Sweep(fw, tags, reboot)
    labels = Counter()
    for name, plans, start_write in (space or plan_space(attempts)):
        r = Runner(fw, tags, plans, start_write, on_event=sw)
        labels.update(r.labels)
    return sw, labels


def mini_space():
    """A compact injection set for the mutation checks (each mutant must be
    caught by at least one of these)."""
    yield "baseline", {}, "ok"
    for k in (1, 2):
        for o in ("ack_not_applied", "no_response_landed", "partial_3"):
            yield f"w{k} {o}", {k: {"write": o}}, "ok"
            yield f"w{k} {o} + End", {k: {"write": o, "end_mid": True}}, "ok"
        yield f"w{k} verify error", {k: {"verify": "error"}}, "ok"
        yield f"w{k} verify mismatch", {k: {"verify": "mismatch"}}, "ok"
        yield f"w{k} End mid ok", {k: {"end_mid": True}}, "ok"


def sweep_safe(fw=None, tags=None, reboot=True) -> bool:
    sw, _ = run_sweep(fw, tags, reboot=reboot, space=mini_space())
    return not sw.bad


# ===========================================================================
print("[1] V2 layout / golden vectors")
# ===========================================================================
hdr_v2 = re.search(r"struct DumpToGridSnapshotData \{(.*?)\n\};", HEADER, re.S).group(1)
hdr_v1 = re.search(r"struct DumpToGridSnapshotDataV1 \{(.*?)\n\};", HEADER, re.S).group(1)
field_re = r"\buint(?:8|16|32)_t (\w+);"
check("header V2 struct fields == model V2_FIELDS == simulator record fields (V1 + reg_dump_power_pending last)",
      re.findall(field_re, hdr_v2) == dv2.V2_FIELDS == ds._RECORD_FIELDS[dv2.V2_KIND]
      and dv2.V2_FIELDS[:-1] == dv2.V1_FIELDS and dv2.V2_FIELDS[-1] == "reg_dump_power_pending")
check("header V1 layout == model V1_FIELDS == simulator V1 kind, and == the base (main @ 004040b) struct",
      re.findall(field_re, hdr_v1) == dv2.V1_FIELDS == ds._RECORD_FIELDS[dv2.V1_KIND]
      and re.findall(field_re, re.search(r"struct DumpToGridSnapshotData \{(.*?)\n\};", BASE_HEADER, re.S).group(1))
      == dv2.V1_FIELDS)
offs = dict(re.findall(r"offsetof\(DumpToGridSnapshotData, (\w+)\) == (\d+)", HEADER))
check("header static_assert offsets == model offsets == ctypes native layout (V2)",
      {k: int(v) for k, v in offs.items()} == dv2.V2_OFFSETS
      and all(getattr(dv2.V2C, f).offset == o for f, o in dv2.V2_OFFSETS.items()), str(offs))
check("sizeof: V1 == V2 == 24 (header static_asserts, struct model, ctypes); V1 carries 2 tail padding bytes",
      "static_assert(sizeof(DumpToGridSnapshotData) == 24" in HEADER
      and "static_assert(sizeof(DumpToGridSnapshotDataV1) == 24" in HEADER
      and "sizeof(DumpToGridSnapshotData) == sizeof(DumpToGridSnapshotDataV1)" in HEADER
      and __import__("ctypes").sizeof(dv2.V1C) == __import__("ctypes").sizeof(dv2.V2C) == dv2.RECORD_SIZE == 24
      and dv2.V1C.reg_dump_power_intended.offset + 2 == 22)
GOLDEN = {"end_epoch": 1790003600, "active_persisted": 1, "restore_requested": 0, "reg244": 2, "reg256": 8000,
          "reg257": 8000, "reg258": 7000, "reg259": 8000, "reg260": 8000, "reg261": 5000,
          "reg_dump_power_intended": 1500, "reg_dump_power_pending": 2300}
V2_GOLDEN_HEX = "9049b16a01000200401f401f581b401f401f8813dc05fc08"
V1_GOLDEN_HEX = "9049b16a01000200401f401f581b401f401f8813dc050000"
check("V2 golden vector (little-endian, 24 bytes)", dv2.pack_v2(GOLDEN).hex() == V2_GOLDEN_HEX, dv2.pack_v2(GOLDEN).hex())
check("V1 golden vector: identical first 22 bytes, zero tail padding",
      dv2.pack_v1(GOLDEN).hex() == V1_GOLDEN_HEX and V1_GOLDEN_HEX[:44] == V2_GOLDEN_HEX[:44])
check("round trips: unpack(pack(x)) == x for V1 and V2",
      dv2.unpack_v2(dv2.pack_v2(GOLDEN)) == GOLDEN
      and dv2.unpack_v1(dv2.pack_v1(GOLDEN)) == {k: GOLDEN[k] for k in dv2.V1_FIELDS})
check("THE HAZARD the tag bump exists for: V1 bytes parse as a V2 record of the same size, with P taken from "
      "V1's padding (0 when zero-initialised, anything otherwise)",
      dv2.unpack_v2(dv2.pack_v1(GOLDEN))["reg_dump_power_pending"] == 0
      and dv2.unpack_v2(dv2.pack_v1(GOLDEN, b"\x34\x12"))["reg_dump_power_pending"] == 0x1234)
check("tombstone constant: header 0xFFFF == model == simulator, and the header asserts it fails reg244 <= 2",
      "constexpr uint16_t DUMP_V1_TOMBSTONE_REG244 = 0xFFFF;" in HEADER
      and "static_assert(DUMP_V1_TOMBSTONE_REG244 > 2" in HEADER
      and dv2.V1_TOMBSTONE_REG244 == ds.Durable.DUMP_V1_TOMBSTONE_REG244 == 0xFFFF)

# ===========================================================================
print("")
print("[2] tag / version separation")
# ===========================================================================
check("DUMP_TO_GRID_DATA_TAG resolves to ecco_dump_to_grid_snapshot_data_v2; _V1 keeps the historical v1 string",
      HEADER_TAGS["DUMP_TO_GRID_DATA_TAG"] == V2_TAG == "ecco_dump_to_grid_snapshot_data_v2"
      and HEADER_TAGS["DUMP_TO_GRID_DATA_TAG_V1"] == V1_TAG == "ecco_dump_to_grid_snapshot_data_v1"
      and HEADER_TAGS["DUMP_TO_GRID_DATA_TAG_V2"] == V2_TAG)
check("the marker tag is NOT bumped: identical to main @ 004040b (older firmware still sees the obligation)",
      HEADER_TAGS["DUMP_TO_GRID_VALID_TAG"] == BASE_HEADER_TAGS["DUMP_TO_GRID_VALID_TAG"] == VALID_TAG
      == "ecco_dump_to_grid_snapshot_valid_v1")
check("the base firmware's data tag was the v1 string (what the tombstone key must be)",
      BASE_HEADER_TAGS["DUMP_TO_GRID_DATA_TAG"] == V1_TAG)
check("the simulator's tag constants equal the header's",
      all(getattr(ds.Durable, n) == HEADER_TAGS[n] for n in ("DUMP_TO_GRID_DATA_TAG", "DUMP_TO_GRID_DATA_TAG_V1",
                                                              "DUMP_TO_GRID_DATA_TAG_V2", "DUMP_TO_GRID_VALID_TAG")))
lit = dict(re.findall(r'constexpr const char \*(\w+)\s*=\s*"([^"]+)";', HEADER))
keys = {n: dv2.esphome_fnv1_hash(t) for n, t in lit.items()}
check("every tag string is unique and so is every NVS key (esphome::fnv1_hash) - V1 and V2 cannot collide",
      len(set(lit.values())) == len(lit) and len(set(keys.values())) == len(keys)
      and keys["DUMP_TO_GRID_DATA_TAG_V1"] != keys["DUMP_TO_GRID_DATA_TAG_V2"], str(keys))
fw_code = fpsim._strip_code(FW_TEXT)
check("firmware names the V2 snapshot only through the DUMP_TO_GRID_DATA_TAG alias (never _V2 directly)",
      "DUMP_TO_GRID_DATA_TAG_V2" not in fw_code)
v1_uses = re.findall(r"ecco_durable::(commit_record|load_record)\(\s*ecco_durable::key_for\(ecco_durable::DUMP_TO_GRID_DATA_TAG_V1\)",
                     FW_TEXT)
start_body = fpsim.script_body(FW_TEXT, "start_dump_to_grid_override")
boot_code = _boot_text(FW)
check("the V1 key is touched at exactly two sites: ONE commit (START's tombstone) and ONE read-only load (on_boot's "
      "legacy diagnostic probe); boot never commits anything",
      sorted(v1_uses) == ["commit_record", "load_record"]
      and "DUMP_TO_GRID_DATA_TAG_V1), v1_tombstone)" in start_body
      and "DUMP_TO_GRID_DATA_TAG_V1), legacy_v1)" in boot_code
      and "commit_record" not in fpsim._strip_code(boot_code), str(v1_uses))
check("preference cache: one new (type, key) pair (DumpToGridSnapshotDataV1 x V1 tag) - 10 one-time objects "
      "instead of 9; the V2 record reuses the alias's single DumpToGridSnapshotData slot",
      len(set(re.findall(r"ecco_durable::(?:commit_record|load_record(?:_status)?)\(\s*ecco_durable::key_for\(ecco_durable::(\w+)\)",
                         FW_TEXT))) == 10)

# ===========================================================================
print("")
print("[3] START: evidence initialisation, V1 tombstone, commit ordering")
# ===========================================================================
run = Runner(ticks=0)
sim = run.sim
seq = [(e[1], e[2]) for e in sim.events if e[0] == "commit"]
c0 = CEILINGS[0]
check("START is ACTIVE on the happy path", run.started, sim.status())
check("START commit order: retry reset -> V1 tombstone -> V2 snapshot -> marker RESTORE_REQUIRED -> (writes) -> "
      "V2 ACTIVE commit",
      [k for k, _ in seq] == [RETRY_TAG, V1_TAG, V2_TAG, VALID_TAG, V2_TAG], str([k for k, _ in seq]))
first_write = next(i for i, e in enumerate(sim.events) if e[0] == "write")
marker_i = next(i for i, e in enumerate(sim.events) if e[0] == "commit" and e[1] == VALID_TAG)
tomb_i = next(i for i, e in enumerate(sim.events) if e[0] == "commit" and e[1] == V1_TAG)
check("the tombstone is committed BEFORE the marker, and both BEFORE the first inverter write",
      tomb_i < marker_i < first_write)
pre = seq[2][1]
check("START's pre-write V2 record: V = P = the START ceiling (never 0), ORIGINAL 244/256-261 snapshotted",
      evidence(pre) == (c0, c0) and c0 != 0 and pre.reg244 == ORIGINAL[244]
      and [getattr(pre, f"reg{r}") for r in CEIL] == [ORIGINAL[r] for r in CEIL])
check("START's ACTIVE commit keeps V = P = the START ceiling and the RAM mirrors agree",
      evidence(sim.nvs[V2_TAG]) == (c0, c0) and sim.nvs[V2_TAG].active_persisted == 1
      and (sim.g["dump_target_power"], sim.g["dump_evidence_pending_ceiling"]) == (c0, c0))
check("the tombstone is a value-initialised V1-shaped record with reg244 = 0xFFFF",
      sim.nvs[V1_TAG]._kind == dv2.V1_KIND and dv2.pack_v1(sim.nvs[V1_TAG]) == dv2.pack_v1(tombstone()))
for failing in (V1_TAG, V2_TAG, VALID_TAG):
    s = fresh()
    s.nvs_fail_tags = {failing}
    s.execute("start_dump_to_grid_override")
    later = {V1_TAG: (V2_TAG, VALID_TAG), V2_TAG: (VALID_TAG,), VALID_TAG: ()}[failing]
    check(f"START with the {failing} commit failing: ZERO inverter writes, no marker, no later commit attempted",
          s.writes() == [] and marker_state(s) is None and not s.g["dump_snapshot_valid"]
          and all(k not in [c for c, _ in s.nvs_commits] for k in later), f"{s.writes()} {[c for c, _ in s.nvs_commits]}")
s = fresh()
s.nvs[V1_TAG] = v1_record(intended=4321)
s.execute("start_dump_to_grid_override")
check("a stale real V1 record (from an old, CLEARED lease) is overwritten by the tombstone at the next START",
      int(s.nvs[V1_TAG].reg244) == 0xFFFF and s.g["dump_active_persisted"])

# ===========================================================================
print("")
print("[4] controller: save-before-write ordering, R3 gate, verified/pending transitions")
# ===========================================================================
run = Runner()
sim = run.sim
check("the three-write schedule produces ceilings 500 -> 1500 -> 2300 -> 2100",
      [v[0] for k, a, v, o in sim.modbus_log if k == "write" and a == 256] == CEILINGS
      and sim.g["dump_target_power"] == CEILINGS[-1], str(sim.writes()))
ctrl = []
state = None
for e in sim.events:
    if e[0] == "commit" and e[1] == V2_TAG and e[2].active_persisted == 1 and e[2].reg_dump_power_pending != e[2].reg_dump_power_intended:
        state = [("commit", evidence(e[2]))]
        ctrl.append(state)
    elif state is not None and e[0] in ("read", "write") and e[1] == 256:
        state.append((e[0], e[2] if e[0] == "write" else None))
check("each controller write is EXACTLY: evidence commit {V, P} -> R3 read -> FC16 write of P -> exact readback",
      [[x[0] for x in c] for c in ctrl] == [["commit", "read", "write", "read"]] * 3, str(ctrl))
check("...and each evidence commit carries V = the verified ceiling, P = the ceiling about to be written",
      [c[0][1] for c in ctrl] == list(zip(CEILINGS[:-1], CEILINGS[1:]))
      and [c[2][1][0] for c in ctrl] == CEILINGS[1:], str([c[0][1] for c in ctrl]))
v2_commits = [r for k, r in sim.nvs_commits if k == V2_TAG]
check("exactly ONE durable commit per controller write: 2 (START) + 3 (controller), nothing after verify",
      len(v2_commits) == 5, str([evidence(r) for r in v2_commits]))
check("after the verified writes: RAM V = P = the last ceiling, durable record still {previous V, P} (lazy advance - "
      "it already contains the live value)",
      (sim.g["dump_target_power"], sim.g["dump_evidence_pending_ceiling"]) == (2100, 2100)
      and evidence(sim.nvs[V2_TAG]) == (2300, 2100) and not dv2.uncovered(sim.nvs[V2_TAG], sim.bank))

# Evidence commit failure: no R3 read, no write, lease ends through request_dump_end.
run = Runner(plans={1: {"evidence_fail": True}}, ticks=3)
sim = run.sim
ctrl_ops = [(k, a) for k, a, v, o in sim.modbus_log if a == 256][2:3]
reason = str(sim.ent("dump_last_end_reason").state)
check("evidence commit fails: NO R3 read and NO controller write; the lease ends through request_dump_end with the "
      "evidence reason and the (blind) restore puts ORIGINAL back",
      [(k, a, v) for k, a, v, o in sim.modbus_log if k == "write"] == [("write", 256, [500] * 6), ("write", 244, [0]),
                                                                       ("write", 244, [2]),
                                                                       ("write", 256, [ORIGINAL[r] for r in CEIL])]
      and sum(1 for k, a, v, o in sim.modbus_log if k == "read" and a == 256) == 1 + 1 + 1
      and reason.startswith("CONTROLLER EVIDENCE COMMIT FAILED") and marker_state(sim) == CLEAR,
      f"{sim.modbus_log} / {reason}")
check("...the RAM pending mirror was already P (set BEFORE the commit), so request_dump_end's rebuild over-covers "
      "(V, P) rather than shrinking",
      [evidence(r) for k, r in sim.nvs_commits if k == V2_TAG][-1] == (500, 1500))

# R3 unchanged: a mismatch (even to exactly P) ends the lease without writing.
run = Runner(plans={1: {"r3": "third_party_P"}}, ticks=3)
reason = str(run.sim.ent("dump_last_end_reason").state)
check("R3 is NOT relaxed: live 256-261 already at P (not V) is a CONFIG DRIFT - no controller write",
      reason.startswith("CONFIG DRIFT (immediate pre-write check)")
      and [v for k, a, v, o in run.sim.modbus_log if k == "write" and a == 256][1:] == [[ORIGINAL[r] for r in CEIL]],
      reason)
# Verified advances only after exact readback.
for o in ("ack_not_applied", "no_response_landed", "partial_3"):
    run = Runner(plans={1: {"write": o}}, ticks=3)
    recs = [evidence(r) for k, r in run.sim.nvs_commits if k == V2_TAG]
    check(f"FC16 {o}: V never advanced to P (no verified readback); every later rebuild keeps P = 1500",
          all(p == 1500 for v, p in recs[2:]) and all(v == 500 for v, p in recs[2:]), str(recs))

# ===========================================================================
print("")
print("[5] power-cut sweep over START and every controller write boundary (A..H), double reboot at every cut")
# ===========================================================================
SW, LABELS = run_sweep()
space_n = sum(1 for _ in plan_space())
check(f"{space_n} injected scenarios x every durable/Modbus event: the durable evidence set ALWAYS contains every "
      f"live 256-261 value while an obligation exists, and survives reboot + request_dump_end + reboot + blind restore "
      f"({len(SW.seen)} distinct cut states)", not SW.bad, "\n      ".join(SW.bad))
need = {"A/H tick start": "A before evidence commit / H next controller cycle",
        "B evidence commit": "B after evidence commit, before the FC16",
        "C ack, not applied": "C write acknowledged but not applied",
        "D applied, response lost": "D write applied, response lost",
        "D partial landing": "D' per-register partial landing",
        "E applied, before verify": "E write applied, verify not yet performed",
        "F verify read (before V advances)": "F verify done, before V advances",
        "G tick end": "G after V advanced (RAM) / next cycle",
        "B' evidence commit FAILED": "B' evidence commit failed",
        "START write": "START write boundaries"}
check("every boundary class was actually exercised: " + "; ".join(need.values()),
      all(SW.checked.get(k, 0) > 0 for k in need), str({k: SW.checked.get(k, 0) for k in need}))

# ===========================================================================
print("")
print("[6] request_dump_end and on_boot preserve P")
# ===========================================================================
for o in ("ok", "ack_not_applied", "no_response_landed", "partial_1", "timeout_landed"):
    seen = []
    run = Runner(plans={2: {"write": o, "end_mid": True}}, ticks=6,
                 on_event=lambda s, lab: seen.append((lab, nvs_copy(s), s.g["dump_controller_pending_ceiling"])))
    mid = [evidence(n[V2_TAG]) for lab, n, pend in seen if lab.startswith(("C", "D", "E")) and pend == 2300]
    check(f"End pressed WHILE controller write 2 is in flight ({o}): request_dump_end's rebuild keeps P = 2300 "
          f"(evidence {mid[:1]}), never collapses it to V",
          mid and all(e == (1500, 2300) for e in mid), str(mid))
nv = {VALID_TAG: marker(RR), V1_TAG: tombstone(), V2_TAG: v2_record(intended=1500, pending=2300)}
bank = {**ORIGINAL, 256: 2300, 257: 2300, 258: 1500, 259: 1500, 260: 1500, 261: 1500}
b = booted(nv, bank)
check("on_boot loads V into dump_target_power and P into dump_evidence_pending_ceiling (trusted V2 obligation)",
      (b.g["dump_target_power"], b.g["dump_evidence_pending_ceiling"]) == (1500, 2300)
      and b.g["dump_snapshot_valid"] and not b.g["dump_recovery_metadata_corrupt"] and b.g["dump_restore_requested"])
b.bus_idle = False
b.execute("request_dump_end", {"reason": ds.CStr("watchdog - restore retry")})
check("...so the first request_dump_end after that boot rebuilds {V=1500, P=2300} (mixed partial bank still covered)",
      evidence(b.nvs[V2_TAG]) == (1500, 2300) and not dv2.uncovered(b.nvs[V2_TAG], bank))
for _ in range(3):
    b.execute("request_dump_end", {"reason": ds.CStr("watchdog - restore retry")})
check("repeated request_dump_end rebuilds are byte-identical (P preserved every time; NVS change detection skips "
      "the physical write)", len({dv2.pack_v2(r) for k, r in b.nvs_commits if k == V2_TAG}) == 1)
def find_evidence_lambda(fw):
    """The controller's evidence-commit lambda (the one lambda that sets the
    pending mirror from dump_controller_pending_ceiling), wherever it sits."""
    found = []

    def walk(node):
        if isinstance(node, dict):
            lam = node.get("lambda")
            if isinstance(lam, str) and "id(dump_evidence_pending_ceiling) = id(dump_controller_pending_ceiling);" in lam \
                    and "commit_record" in lam:
                found.append(lam)
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk({s["id"]: s for s in fw["script"]}["dump_controller_tick"]["then"])
    return found[0] if len(found) == 1 else None


EVIDENCE_LAMBDA = find_evidence_lambda(FW)


def evidence_lambda_record(fw_lambda: str, restore_requested: bool, active: bool = True):
    s = new_sim()
    s.g.update({"dump_snapshot_valid": True, "dump_marker_state": RR, "dump_recovery_metadata_corrupt": False,
                "dump_active_persisted": active, "dump_restore_requested": restore_requested,
                "dump_target_power": 1500, "dump_controller_pending_ceiling": 2300, "dump_end_epoch": 1790003600,
                "dump_snapshot_reg244": 2})
    for r in CEIL:
        s.g[f"dump_snapshot_reg{r}"] = ORIGINAL[r]
    s.run_lambda(fw_lambda)
    return s.nvs.get(V2_TAG), s


check("located the controller's evidence-commit lambda", EVIDENCE_LAMBDA is not None)
rec_t, _ = evidence_lambda_record(EVIDENCE_LAMBDA, True)
rec_f, s_f = evidence_lambda_record(EVIDENCE_LAMBDA, False)
check("the evidence commit rebuilds EVERY field from RAM like request_dump_end (restore_requested / active_persisted "
      "copied, never hard-coded), V from dump_target_power, P from the mirror it just set",
      rec_t.restore_requested == 1 and rec_f.restore_requested == 0 and rec_t.active_persisted == 1
      and evidence(rec_f) == (1500, 2300) and s_f.g["dump_evidence_pending_ceiling"] == 2300)

# ===========================================================================
print("")
print("[7] V2 boot rules (marker x data) and legacy V1 obligations")
# ===========================================================================
V2OK = v2_record(intended=1500, pending=2300)


def boot_case(nv, fail_load=(), fw=None, tags=None, bank=None):
    s = booted(nv, bank, fw, tags, fail_load)
    return s


s = boot_case({VALID_TAG: marker(RR), V1_TAG: tombstone(), V2_TAG: V2OK}, fail_load={VALID_TAG})
check("marker READ_ERROR: SG-06 UNKNOWN - locked, containment state 8, and the V2 data is NOT even loaded",
      s.g["dump_snapshot_valid"] and s.g["dump_recovery_metadata_corrupt"] and s.g["dump_containment_state"] == 8
      and V2_TAG not in s.nvs_loads and not s.g["dump_snapshot_data_loaded"], str(s.nvs_loads))
for mstate, name in ((CLEAR, "CLEAR"), (None, "absent")):
    nv = {V1_TAG: v1_record(), V2_TAG: V2OK}
    if mstate is not None:
        nv[VALID_TAG] = marker(mstate)
    s = boot_case(nv)
    check(f"marker {name}: stale V1/V2 data is ignored - no obligation, Inactive",
          not s.g["dump_snapshot_valid"] and not s.g["dump_recovery_metadata_corrupt"]
          and str(s.ent("dump_status").state) == "Inactive")
s = boot_case({VALID_TAG: marker(PENDING_CLEAR), V1_TAG: tombstone(), V2_TAG: V2OK})
s.execute("request_dump_end", {"reason": ds.CStr("watchdog - restore retry")})
check("marker PENDING_CLEAR: existing clear-only completion, ZERO Modbus I/O",
      marker_state(s) == CLEAR and s.modbus_log == [] and not s.g["dump_snapshot_valid"])
s = boot_case({VALID_TAG: marker(RR), V1_TAG: tombstone(), V2_TAG: V2OK})
check("marker RESTORE_REQUIRED + V2 OK: trusted V2 obligation (lease ended, not resumed; restore allowed)",
      s.g["dump_snapshot_valid"] and not s.g["dump_recovery_metadata_corrupt"] and s.g["dump_snapshot_data_loaded"]
      and s.g["dump_restore_requested"])
for label, nv, fail in (
        ("V2 READ_ERROR", {VALID_TAG: marker(RR), V1_TAG: tombstone(), V2_TAG: V2OK}, {V2_TAG}),
        ("V2 WRONG_SIZE", {VALID_TAG: marker(RR), V1_TAG: tombstone(), V2_TAG: ds.Record("Reg244SnapshotData", 2)}, ()),
        ("V2 ABSENT (legacy V1 obligation)", {VALID_TAG: marker(RR), V1_TAG: v1_record()}, ()),
        ("V2 ABSENT, nothing under V1 either", {VALID_TAG: marker(RR)}, ()),
        ("V2 ABSENT + legacy V1 READ_ERROR", {VALID_TAG: marker(RR), V1_TAG: v1_record()}, {V1_TAG})):
    for live244 in (2, 0):
        bank = {**ORIGINAL, 244: live244}
        s = boot_case(nv, fail, bank=bank)
        before = fingerprint(s.nvs)
        loads_boot = list(s.nvs_loads)
        for _ in range(3):
            s.advance(15000)
            s.run_actions(watchdog_of(s.fw))
        s.execute("request_dump_end", {"reason": ds.CStr("manual End button")})
        writes = s.writes()
        check(f"marker RESTORE_REQUIRED + {label}, live 244={live244}: KNOWN obligation with bad data - locked "
              f"(never CLEAR), containment ARMED (not SG-06's state 8), nothing durable changed, never falls back to "
              f"reading V1 as the snapshot, 256-261 never written",
              s.g["dump_snapshot_valid"] and s.g["dump_recovery_metadata_corrupt"]
              and s.g["dump_containment_state"] not in (0, 8) and fingerprint(s.nvs) == before
              and not s.g["dump_snapshot_data_loaded"] and all(a == 244 for a, _v in writes)
              and (writes == [] if live244 == 2 else writes == [(244, [2])]),
              f"state={s.g['dump_containment_state']} writes={writes} loads={loads_boot}")
s = boot_case({VALID_TAG: marker(RR), V1_TAG: v1_record()})
s.ent("dump_recovery_arm").state = True
s.g["dump_operator_needed"] = True
s.execute("dump_accept_current_state")
check("legacy V1 obligation: Accept Current State refuses (metadata-corrupt gate) - the obligation is never cleared "
      "by an upgrade", marker_state(s) == RR and s.nvs[V1_TAG].reg244 == ORIGINAL[244])

# ===========================================================================
print("")
print("[8] V1 tombstone vs the pre-V2 loader (main @ 004040b rebuilt byte-for-byte)")
# ===========================================================================
# FB-T0: the absolute pin rebuilds main @ 004040b from the firmware AS OF chain entry "dump_v2" (main @ ca7474e): every
# LATER chain entry is undone by its exact-match reverter first (registry/tests/_scope_chain.py), then Dump V2's and Manual
# TOU's own reverters run exactly as before - a later PR's declared edits never re-hash it, an undeclared edit still
# breaks it. The differential tests keep running the LIVE firmware against BASE_FW (= LIVE minus Dump V2's edits).
SCOPE_FW_TEXT = chain.CHAIN.as_of(chain.FIRMWARE, "dump_v2", FW_TEXT)
SCOPE_BASE_TEXT = dv2s.pre_dump_v2_firmware(SCOPE_FW_TEXT)
check("the rebuilt base firmware, with Manual TOU Phase 1's own edits (PR #53) also reverted, is main @ 004040b byte-for-byte",
      dv2s.sha(mtou1.pre_mtou1_text(SCOPE_BASE_TEXT)) == dv2s.BASE_FIRMWARE_SHA)
check("...and the rebuilt base firmware itself still contains Manual TOU Phase 1 (it is main after PR #53, not the older base)",
      dv2s.sha(BASE_TEXT) != dv2s.BASE_FIRMWARE_SHA and mtou1.INTERVAL_MARKER in BASE_TEXT)
run = Runner(ticks=6)
nv, bank = nvs_copy(run.sim), dict(run.sim.bank)
old = booted(nv, bank, fw=BASE_FW, tags=BASE_HEADER_TAGS)
check("rollback to pre-V2 firmware while a V2 obligation is open: the old loader sees the (unchanged) marker, "
      "reads the tombstone under its own v1 data tag and FAILS CLOSED (RECOVERY BLOCKED)",
      old.g["dump_snapshot_valid"] and old.g["dump_recovery_metadata_corrupt"] and not old.g["dump_snapshot_data_loaded"])
before = fingerprint(old.nvs)
for _ in range(4):
    old.advance(15000)
    old.run_actions(watchdog_of(old.fw))
check("...its SG-02 containment then handles the known corrupt obligation: live Allow Export is contained (244 := 2), "
      "256-261 are NEVER written from a stale snapshot, nothing durable changes",
      old.writes() == [(244, [2])] and fingerprint(old.nvs) == before and old.bank[256] == bank[256], str(old.writes()))
stale = dict(nv)
stale[V1_TAG] = v1_record(intended=999, original={**ORIGINAL, 256: 1234})
old2 = booted(stale, bank, fw=BASE_FW, tags=BASE_HEADER_TAGS)
check("counter-check: WITHOUT the tombstone the old loader would trust a stale V1 snapshot from an earlier lease "
      "(the hazard the tombstone removes)",
      old2.g["dump_snapshot_data_loaded"] and not old2.g["dump_recovery_metadata_corrupt"]
      and old2.g["dump_snapshot_reg256"] == 1234)

# ===========================================================================
print("")
print("[9] frozen: restore / Accept / Force / containment / clear-only / R3 / watchdog")
# ===========================================================================
SCRIPTS = {s["id"]: s for s in FW["script"]}
BASE_SCRIPTS = {s["id"]: s for s in BASE_FW["script"]}
for sid in ("restore_dump_to_grid_snapshot", "dump_accept_current_state", "dump_force_restore_original",
            "dump_lockout_containment", "dump_clear_verified_marker"):
    check(f"{sid}: raw text AND parsed action tree identical to main @ 004040b",
          fpsim.script_body(FW_TEXT, sid) == fpsim.script_body(BASE_TEXT, sid) and SCRIPTS[sid] == BASE_SCRIPTS[sid])
check("no frozen script mentions the evidence (V/P fields or mirrors)",
      not any(re.search(r"reg_dump_power_(pending|intended)|dump_evidence_pending_ceiling", fpsim.script_body(FW_TEXT, sid))
              for sid in ("restore_dump_to_grid_snapshot", "dump_accept_current_state", "dump_force_restore_original",
                          "dump_lockout_containment", "dump_clear_verified_marker")))
check("every watchdog/interval (incl. passive drift check and containment) identical to main @ 004040b",
      FW["interval"] == BASE_FW["interval"])
new_b = SCRIPTS["dump_controller_tick"]["then"][2]["if"]["then"][0]["if"]["then"]
old_b = BASE_SCRIPTS["dump_controller_tick"]["then"][2]["if"]["then"][0]["if"]["then"]
check("controller critical section: lock lambda (+ one flag reset), R3 block (read + wait + timeout), FC16 write block and readback block "
      "are the parsed main @ 004040b trees; only the evidence lambda + the R3 gate are new",
      new_b[0]["lambda"] == old_b[0]["lambda"].replace(
          "id(dump_controller_ownership_read_failed) = false;\n",
          "id(dump_controller_ownership_read_failed) = false;\nid(dump_controller_evidence_commit_failed) = false;\n")
      and new_b[2]["if"]["then"] == old_b[1:4]
      and new_b[2]["if"]["condition"] == {"lambda": "return !id(dump_controller_write_failed);"}
      and new_b[3] == old_b[4] and new_b[4] == old_b[5] and len(new_b) == len(old_b) - 1)
check("R3 still compares the live six-register vector against dump_target_power only",
      "uint16_t p = id(dump_target_power);" in new_b[2]["if"]["then"][0][ds.READ]["on_response"]["then"][0]["lambda"]
      and "pending" not in new_b[2]["if"]["then"][0][ds.READ]["on_response"]["then"][0]["lambda"])
top_new, top_old = SCRIPTS["dump_controller_tick"]["then"], BASE_SCRIPTS["dump_controller_tick"]["then"]
check("the controller's decision lambda and fail-closed branch are unchanged (no new policy)",
      top_new[0] == top_old[0] and top_new[1] == top_old[1] and top_new[3] == top_old[3])


def differential(plans=None, drift=None, ticks=9):
    """The same injected lease on the base and the V2 firmware."""
    out = []
    for fw in (BASE_FW, FW):
        r = Runner(fw, None, plans or {}, ticks=0)
        s = r.sim
        for i in range(ticks):
            if drift is not None and i == drift[0]:
                s.bank[drift[1]] = drift[2]
            tick(s, GRID_SCHEDULE[i] if i < len(GRID_SCHEDULE) else None)
        s.execute("request_dump_end", {"reason": ds.CStr("manual End button")})
        out.append(s)
    return out


for label, plans, drift in (("clean lease + manual End", {}, None),
                            ("controller write lands, response lost", {2: {"write": "no_response_landed"}}, None),
                            ("per-register partial landing", {2: {"write": "partial_3"}}, None),
                            ("verify mismatch", {1: {"verify": "mismatch"}}, None),
                            ("third-party change of 258 mid-lease", {}, (4, 258, 4321)),
                            ("End mid-write", {3: {"end_mid": True}}, None)):
    b_sim, n_sim = differential(plans, drift)
    check(f"differential [{label}]: every Modbus operation (reads, writes, values, order) and every restore is "
          f"IDENTICAL to main @ 004040b - restore still blind",
          b_sim.modbus_log == n_sim.modbus_log and b_sim.bank == n_sim.bank
          and marker_state(b_sim) == marker_state(n_sim), f"\n base={b_sim.modbus_log}\n  new={n_sim.modbus_log}")

# ===========================================================================
print("")
print("[10] durable resource impact")
# ===========================================================================
b_sim, n_sim = differential()
ctrl_writes = sum(1 for k, a, v, o in n_sim.modbus_log if k == "write" and a == 256) - 2
dc = lambda s, key: sum(1 for k, _ in s.nvs_commits if k == key)  # noqa: E731
b_data = dc(b_sim, V1_TAG)
n_data, n_v1 = dc(n_sim, V2_TAG), dc(n_sim, V1_TAG)
check(f"per lease vs main @ 004040b: +{ctrl_writes} data commits for {ctrl_writes} controller writes (exactly one per "
      f"write) + 1 V1 tombstone; marker and retry commit sequences unchanged",
      n_data - b_data == ctrl_writes == 3 and n_v1 == 1
      and [r.state for k, r in b_sim.nvs_commits if k == VALID_TAG] == [r.state for k, r in n_sim.nvs_commits if k == VALID_TAG]
      and dc(b_sim, RETRY_TAG) == dc(n_sim, RETRY_TAG), f"base={b_data} new={n_data} v1={n_v1}")
# Write budget: 120 verified writes, then exhausted - exactly 120 evidence commits.
s = fresh(target=500, grid_w=1810.0, duration=240)
s.execute("start_dump_to_grid_override")
tick(s); tick(s); tick(s)
up = True
for _ in range(160):
    if not s.g["dump_active_persisted"]:
        break
    up = not up
    for _ in range(3):
        tick(s, 1810.0 if up else -1200.0)
reason = str(s.ent("dump_last_end_reason").state)
ev = [r for k, r in s.nvs_commits if k == V2_TAG and r.reg_dump_power_pending != r.reg_dump_power_intended]
ctrl_w = sum(1 for k, a, v, o in s.modbus_log if k == "write" and a == 256) - 2
data_total = dc(s, V2_TAG)
check(f"write budget: {ctrl_w} controller writes, {len(ev)} evidence commits, lease ended WRITE BUDGET EXHAUSTED - "
      f"no evidence commit beyond the budget; {data_total} data commits for the whole lease "
      f"(2 START + 120 evidence + request_dump_end rebuilds)",
      ctrl_w == len(ev) == 120 and "WRITE BUDGET" in reason and data_total - 120 - 2 <= 2, f"{reason} {data_total}")


def physical(commits) -> int:
    """Commits ESPHome's ESP32Preferences::sync() would actually write
    (is_changed_(): skipped when the stored bytes are identical)."""
    last, n = {}, 0
    for k, r in commits:
        fp = (r._kind, tuple(getattr(r, f) for f in ds._RECORD_FIELDS[r._kind]))
        if last.get(k) != fp:
            n += 1
        last[k] = fp
    return n


lock = boot_case({VALID_TAG: marker(RR), V1_TAG: tombstone(), V2_TAG: V2OK, RETRY_TAG: ds.Record("DumpToGridRetryState", 1)})
for _ in range(240):  # one hour of 15s watchdog ticks under an operator lockout
    lock.advance(15000)
    lock.run_actions(watchdog_of(lock.fw))
logical = [(k, r) for k, r in lock.nvs_commits if k == V2_TAG]
check(f"operator lockout for 1h: request_dump_end still rebuilds every 15s ({len(logical)} logical commits - kept, it "
      f"also retries a failed restore_requested commit) but only {physical(logical)} physical NVS write; P preserved",
      len(logical) >= 200 and physical(logical) == 1 and all(evidence(r) == (1500, 2300) for _, r in logical))
print("  INFO  durable impact: V1 = 24 B, V2 = 24 B (same size - P fills V1's tail padding); NVS keys: +1 (the v2 data "
      "key; the v1 key already existed and now holds the tombstone); commits: +1 per controller write attempt, +1 "
      "tombstone per START; worst case per lease = 120 extra (write budget) + 1 tombstone.")

# ===========================================================================
print("")
print("[11] reference classifier (test-side only) and evidence plausibility")
# ===========================================================================
rec = v2_record(intended=1500, pending=2300)
check("reference classifier: ORIGINAL / V / P per register are ORIGINAL / DUMP_OWNED / DUMP_OWNED; anything else is "
      "FOREIGN; a third-party value that happens to equal V or P is (conservatively) DUMP_OWNED",
      dv2.classify_bank(rec, {**ORIGINAL, 256: 1500, 257: 2300, 258: 4321})
      == {256: dv2.DUMP_OWNED, 257: dv2.DUMP_OWNED, 258: dv2.FOREIGN, 259: dv2.ORIGINAL, 260: dv2.ORIGINAL, 261: dv2.ORIGINAL})
check("per-register (not all-or-nothing): a mixed partial landing {P,P,P,V,V,V} is fully Dump-owned",
      set(dv2.classify_bank(rec, {256: 2300, 257: 2300, 258: 2300, 259: 1500, 260: 1500, 261: 1500}).values())
      == {dv2.DUMP_OWNED})
EVIDENCE_LINES = sorted({ln.strip() for ln in fpsim._strip_code(FW_TEXT).splitlines()
                         if re.search(r"reg_dump_power_pending|dump_evidence_pending_ceiling", ln)
                         and not ln.strip().startswith(("#", "- id:"))})
check("the reference classifier is NOT in firmware: the ONLY code lines touching P are these five pure assignments "
      "(boot load, START init x2, rebuild from the mirror, controller mirror set) - no condition ever reads it",
      EVIDENCE_LINES == sorted({"id(dump_evidence_pending_ceiling) = data.reg_dump_power_pending;",
                                "data.reg_dump_power_pending = id(dump_target_power);",
                                "id(dump_evidence_pending_ceiling) = id(dump_target_power);",
                                "data.reg_dump_power_pending = id(dump_evidence_pending_ceiling);",
                                "id(dump_evidence_pending_ceiling) = id(dump_controller_pending_ceiling);"}),
      str(EVIDENCE_LINES))
nv_ok = {VALID_TAG: marker(RR), V1_TAG: tombstone(), V2_TAG: v2_record(intended=1500, pending=2300)}
nv_bad = {VALID_TAG: marker(RR), V1_TAG: tombstone(), V2_TAG: v2_record(intended=0, pending=65535)}
a, b = booted(nv_ok), booted(nv_bad)
keys_diff = {k for k in a.g if a.g[k] != b.g[k]}
check("no new lockout from the V/P domain: an implausible V=0 / P=65535 boots exactly like a plausible record "
      "(only the two evidence mirrors differ)",
      keys_diff == {"dump_target_power", "dump_evidence_pending_ceiling"}, str(keys_diff))


def evidence_plausible(r) -> bool:
    """TEST-ONLY classification for the future ownership PR: both fields are
    real controller ceilings (500..3000W, 100W steps)."""
    return all(500 <= v <= 3000 and v % 100 == 0 for v in evidence(r))


check(f"test-only plausibility: all {len(SW.evidence_seen)} distinct (V, P) pairs the [5] sweep observed are "
      f"plausible; the corrupt one is not",
      SW.evidence_seen and all(evidence_plausible(ds.Record(dv2.V2_KIND, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, v, p_))
                               for v, p_ in SW.evidence_seen) and not evidence_plausible(nv_bad[V2_TAG]),
      str(sorted(SW.evidence_seen)))

# ===========================================================================
print("")
print("[12] mutation tests")
# ===========================================================================
EVI = "                          ecco_durable::key_for(ecco_durable::DUMP_TO_GRID_DATA_TAG), data);\n"
EV_COMMIT = "                        evidence_ok = ecco_durable::commit_record(\n" + EVI
EV_MIRROR = "                      id(dump_evidence_pending_ceiling) = id(dump_controller_pending_ceiling);\n"
EV_V = "                        data.reg_dump_power_intended = id(dump_target_power);\n                        data.reg_dump_power_pending = id(dump_evidence_pending_ceiling);\n"
WRITE_WAIT = ('                              ESP_LOGE("dump_to_grid", "Controller write to registers 256-261 did not reach a terminal state");\n'
              '                            }\n')
SUCCESS = "                            id(dump_target_power) = id(dump_controller_pending_ceiling);\n"
RDE_P = ("\n            data.reg_dump_power_pending = id(dump_evidence_pending_ceiling);\n"
         "            ecco_durable::commit_record(ecco_durable::key_for(ecco_durable::DUMP_TO_GRID_DATA_TAG), data);\n")
BOOT_P = "                  id(dump_evidence_pending_ceiling) = data.reg_dump_power_pending;\n"
START_P = ("                      data.reg_dump_power_pending = id(dump_target_power);\n"
           "                      id(dump_evidence_pending_ceiling) = id(dump_target_power);\n")
EV_BLOCK_START = FW_TEXT.index("                  - lambda: |-\n" + EV_MIRROR)
EV_BLOCK_END = FW_TEXT.index("                  # R3 runs only once the evidence commit above has succeeded.")
EV_BLOCK = FW_TEXT[EV_BLOCK_START:EV_BLOCK_END]


def moved_after_fc16() -> dict:
    moved = "".join(("      " + ln if ln.strip() else ln) for ln in EV_BLOCK.splitlines(keepends=True))
    text = FW_TEXT.replace(EV_BLOCK, "", 1)
    assert text.count(WRITE_WAIT) == 1
    return ds.load_firmware_text(text.replace(WRITE_WAIT, WRITE_WAIT + "\n" + moved.rstrip("\n") + "\n", 1))


def s_sweep(fw=None, tags=None):
    return sweep_safe(fw, tags)


def s_isolated_restore_requested(fw):
    lam = find_evidence_lambda(fw)
    if lam is None:
        return None
    r, _ = evidence_lambda_record(lam, True)
    return r is not None and r.restore_requested == 1


def s_commit_fail_no_write(fw):
    """Evidence commit fails at attempt 1: no controller R3 read and no
    controller FC16 - the only 256-261 operations are START's fresh read,
    START's write + readback, and the restore's write + readback."""
    r = Runner(fw, None, {1: {"evidence_fail": True}}, ticks=3)
    return [v for k, a, v, o in r.sim.modbus_log if k == "write" and a == 256] == [[500] * 6, [ORIGINAL[x] for x in CEIL]] \
        and sum(1 for k, a, v, o in r.sim.modbus_log if k == "read" and a == 256) == 3


def s_legacy_blocked(fw=None, tags=None, fail=()):
    tags = tags or HEADER_TAGS
    nv = {VALID_TAG: marker(RR), tags["DUMP_TO_GRID_DATA_TAG_V1"]: v1_record(), V2_TAG: v2_record()} if fail else \
        {VALID_TAG: marker(RR), tags["DUMP_TO_GRID_DATA_TAG_V1"]: v1_record()}
    s = booted(nv, fw=fw, tags=tags, fail_load=fail)
    before = fingerprint(s.nvs)
    return (s.g["dump_snapshot_valid"] and s.g["dump_recovery_metadata_corrupt"] and not s.g["dump_snapshot_data_loaded"]
            and fingerprint(s.nvs) == before and marker_state(s) == RR and s.nvs_commits == []
            and s.g["dump_containment_state"] not in (0, 8))


def s_unknown_no_data(fw):
    s = booted({VALID_TAG: marker(RR), V1_TAG: tombstone(), V2_TAG: V2OK}, fw=fw, fail_load={VALID_TAG})
    return s.g["dump_containment_state"] == 8 and V2_TAG not in s.nvs_loads and not s.g["dump_snapshot_data_loaded"]


def s_clear_ignores_data(fw):
    s = booted({VALID_TAG: marker(CLEAR), V1_TAG: tombstone(), V2_TAG: V2OK}, fw=fw)
    return not s.g["dump_snapshot_valid"]


def s_start_order(fw=None, tags=None):
    r = Runner(fw, tags, ticks=0)
    order = [e[1] for e in r.sim.events if e[0] == "commit"]
    t = (tags or HEADER_TAGS)
    return order[:4] == [RETRY_TAG, t["DUMP_TO_GRID_DATA_TAG_V1"], t["DUMP_TO_GRID_DATA_TAG"], VALID_TAG] \
        and t["DUMP_TO_GRID_DATA_TAG_V1"] != t["DUMP_TO_GRID_DATA_TAG"]


def s_r3_not_relaxed(fw):
    r = Runner(fw, None, {1: {"r3": "third_party_P"}}, ticks=3)
    return str(r.sim.ent("dump_last_end_reason").state).startswith("CONFIG DRIFT (immediate pre-write check)")


def s_restore_frozen(fw):
    return {s["id"]: s for s in fw["script"]}["restore_dump_to_grid_snapshot"] == BASE_SCRIPTS["restore_dump_to_grid_snapshot"] \
        and all(differential_fw(fw))


def differential_fw(fw):
    for plans in ({}, {2: {"write": "partial_3"}}):
        out = []
        for f in (BASE_FW, fw):
            r = Runner(f, None, plans, ticks=6)
            r.sim.execute("request_dump_end", {"reason": ds.CStr("manual End button")})
            out.append(r.sim.modbus_log)
        yield out[0] == out[1]


def s_old_firmware_sees_obligation(fw=None, tags=None):
    r = Runner(fw, tags, ticks=3)
    old = booted(nvs_copy(r.sim), dict(r.sim.bank), fw=BASE_FW, tags=BASE_HEADER_TAGS)
    return old.g["dump_snapshot_valid"] and (tags or HEADER_TAGS)["DUMP_TO_GRID_VALID_TAG"] == VALID_TAG


def s_no_zero_sentinel(fw):
    r = Runner(fw, None, ticks=0)
    return all(0 not in evidence(rec) for k, rec in r.sim.nvs_commits if k == V2_TAG)


def header_mutant(old, new) -> dict:
    assert HEADER.count(old) == 1, old
    return dv2.header_tags(HEADER.replace(old, new))


BOOT_ELSE = ("                  id(dump_snapshot_valid) = true;\n                  id(dump_recovery_metadata_corrupt) = true;\n"
             "                  // Dump V2: the marker proves an obligation exists, so a\n")
V2_LOAD = "                if (ecco_durable::load_record(ecco_durable::key_for(ecco_durable::DUMP_TO_GRID_DATA_TAG), data) &&\n"
UNKNOWN = "              id(dump_containment_state) = 8;\n"
CLEAR_BR = "              if (state == ecco_durable::MARKER_CLEAR) {\n                id(dump_snapshot_valid) = false;\n"
TOMB = ("                      bool tombstone_committed = retry_reset_committed && ecco_durable::commit_record(\n"
        "                        ecco_durable::key_for(ecco_durable::DUMP_TO_GRID_DATA_TAG_V1), v1_tombstone);\n")
MARKER_C = ("                      bool marker_committed = data_committed && ecco_durable::commit_record(\n"
            "                        ecco_durable::key_for(ecco_durable::DUMP_TO_GRID_VALID_TAG), marker);\n")
R3_CMP = "                                      if (values[i] != p) {\n"
RESTORE_FIRST = ("            - modbus_client.write_multiple_registers:\n                modbus_id: inverter_modbus\n"
                 "                address: 0x01\n                start_address: 244\n"
                 "                values: !lambda 'return std::vector<uint16_t>{id(dump_snapshot_reg244)};'\n")
RESTORE_PRE_READ = ("            - modbus_client.read_holding_registers:\n                modbus_id: inverter_modbus\n"
                    "                address: 0x01\n                start_address: 256\n                count: 6\n")

MUTANTS = [
    ("evidence commit moved after FC16", s_sweep, lambda: moved_after_fc16()),
    ("pending not updated (mirror never set; commit writes the stale P)", s_sweep,
     lambda: mutant_fw(EV_MIRROR, "")),
    ("verified advanced before readback (V := P as soon as the FC16 is acknowledged)", s_sweep,
     lambda: mutant_fw("                                - lambda: 'id(dump_controller_op_terminal) = true;'\n                            on_error:\n"
                       "                              then:\n                                - lambda: |-\n                                    id(dump_controller_op_terminal) = true;\n"
                       "                                    id(dump_controller_write_failed) = true;\n                            on_no_response:",
                       "                                - lambda: 'id(dump_controller_op_terminal) = true; id(dump_target_power) = id(dump_controller_pending_ceiling);'\n                            on_error:\n"
                       "                              then:\n                                - lambda: |-\n                                    id(dump_controller_op_terminal) = true;\n"
                       "                                    id(dump_controller_write_failed) = true;\n                            on_no_response:")),
    ("pending collapsed to V before the exact readback", s_sweep,
     lambda: mutant_fw(WRITE_WAIT, WRITE_WAIT.replace("                            }\n",
                                                      "                            }\n                            id(dump_evidence_pending_ceiling) = id(dump_target_power);\n"))),
    ("pre-write V taken from the stale durable record instead of RAM", s_sweep,
     lambda: mutant_fw(EV_V, "                        ecco_durable::DumpToGridSnapshotData prev{};\n"
                             "                        ecco_durable::load_record(ecco_durable::key_for(ecco_durable::DUMP_TO_GRID_DATA_TAG), prev);\n"
                             "                        data.reg_dump_power_intended = prev.reg_dump_power_intended;\n"
                             "                        data.reg_dump_power_pending = id(dump_evidence_pending_ceiling);\n")),
    ("request_dump_end writes P = V", s_sweep,
     lambda: mutant_fw(RDE_P, RDE_P.replace("id(dump_evidence_pending_ceiling)", "id(dump_target_power)"))),
    ("on_boot fails to load the P mirror", s_sweep, lambda: mutant_fw(BOOT_P, "")),
    ("RAM pending mirror only updated after write success", s_sweep,
     lambda: ds.load_firmware_text(
         FW_TEXT.replace(EV_MIRROR, "", 1)
         .replace(EV_V, EV_V.replace("id(dump_evidence_pending_ceiling);", "id(dump_controller_pending_ceiling);"), 1)
         .replace(SUCCESS, SUCCESS + "                            id(dump_evidence_pending_ceiling) = id(dump_controller_pending_ceiling);\n", 1))),
    ("controller commit hard-codes restore_requested = 0", s_isolated_restore_requested,
     lambda: mutant_fw("                        data.restore_requested = id(dump_restore_requested) ? 1 : 0;\n                        data.reg244",
                       "                        data.restore_requested = 0;\n                        data.reg244")),
    ("failed evidence commit still permits R3 + the write", s_commit_fail_no_write,
     lambda: mutant_fw("                        id(dump_controller_evidence_commit_failed) = true;\n                        id(dump_controller_write_failed) = true;\n",
                       "                        id(dump_controller_evidence_commit_failed) = true;\n")),
    ("zero used as the START pending sentinel", s_no_zero_sentinel,
     lambda: mutant_fw(START_P, "                      data.reg_dump_power_pending = 0;\n"
                                "                      id(dump_evidence_pending_ceiling) = 0;\n")),
    ("V2 ABSENT + RESTORE_REQUIRED treated as CLEAR", s_legacy_blocked,
     lambda: mutant_fw(BOOT_ELSE, BOOT_ELSE.replace("id(dump_snapshot_valid) = true;", "id(dump_snapshot_valid) = false;")
                       .replace("id(dump_recovery_metadata_corrupt) = true;", "id(dump_recovery_metadata_corrupt) = false;"))),
    ("V2 READ_ERROR falls back to reading V1 as the snapshot", lambda fw: s_legacy_blocked(fw, None, fail={V2_TAG}),
     lambda: mutant_fw(V2_LOAD, "                if ((ecco_durable::load_record(ecco_durable::key_for(ecco_durable::DUMP_TO_GRID_DATA_TAG), data) ||\n"
                                "                     ecco_durable::load_record(ecco_durable::key_for(ecco_durable::DUMP_TO_GRID_DATA_TAG_V1), data)) &&\n")),
    ("SG-06 UNKNOWN loads the V2 data", s_unknown_no_data,
     lambda: mutant_fw(UNKNOWN, UNKNOWN + "              { ecco_durable::DumpToGridSnapshotData d{};\n"
                                "                if (ecco_durable::load_record(ecco_durable::key_for(ecco_durable::DUMP_TO_GRID_DATA_TAG), d)) { id(dump_snapshot_data_loaded) = true; } }\n")),
    ("V2 data error mapped to containment state 8", s_legacy_blocked,
     lambda: mutant_fw(BOOT_ELSE, BOOT_ELSE.replace("                  // Dump V2", "                  id(dump_containment_state) = 8;\n                  // Dump V2"))),
    ("V2 data alone treated as an obligation while the marker is CLEAR", s_clear_ignores_data,
     lambda: mutant_fw(CLEAR_BR, "              if (state == ecco_durable::MARKER_CLEAR) {\n"
                                 "                ecco_durable::DumpToGridSnapshotData stale{};\n"
                                 "                id(dump_snapshot_valid) = ecco_durable::load_record(ecco_durable::key_for(ecco_durable::DUMP_TO_GRID_DATA_TAG), stale);\n")),
    ("open V1 obligation's marker cleared during the upgrade boot", s_legacy_blocked,
     lambda: mutant_fw(BOOT_ELSE, BOOT_ELSE.replace("                  // Dump V2",
                                                    "                  { ecco_durable::ValidMarker m0{}; m0.magic = ecco_durable::VALID_MARKER_MAGIC; m0.state = ecco_durable::MARKER_CLEAR;\n"
                                                    "                    ecco_durable::commit_record(ecco_durable::key_for(ecco_durable::DUMP_TO_GRID_VALID_TAG), m0); }\n"
                                                    "                  // Dump V2"))),
    ("tombstone written after the marker", s_start_order,
     lambda: ds.load_firmware_text(FW_TEXT.replace(TOMB, "                      bool tombstone_committed = retry_reset_committed;\n", 1)
                                   .replace(MARKER_C, MARKER_C + "                      if (marker_committed) ecco_durable::commit_record(\n"
                                            "                        ecco_durable::key_for(ecco_durable::DUMP_TO_GRID_DATA_TAG_V1), v1_tombstone);\n", 1))),
    ("R3 relaxed to accept the pending ceiling", s_r3_not_relaxed,
     lambda: mutant_fw(R3_CMP, "                                      if (values[i] != p && values[i] != id(dump_controller_pending_ceiling)) {\n")),
    ("restore gains an ownership pre-read", s_restore_frozen,
     lambda: mutant_fw(RESTORE_FIRST, RESTORE_PRE_READ + RESTORE_FIRST)),
]
HEADER_MUTANTS = [
    ("V1 tag reused for V2 (_V2 literal = the v1 string)",
     header_mutant('DUMP_TO_GRID_DATA_TAG_V2 = "ecco_dump_to_grid_snapshot_data_v2"', 'DUMP_TO_GRID_DATA_TAG_V2 = "ecco_dump_to_grid_snapshot_data_v1"'),
     lambda tags: s_legacy_blocked(None, tags) and s_start_order(None, tags)),
    ("V1 bytes accepted as V2 (alias points back at V1)",
     header_mutant("DUMP_TO_GRID_DATA_TAG = DUMP_TO_GRID_DATA_TAG_V2;", "DUMP_TO_GRID_DATA_TAG = DUMP_TO_GRID_DATA_TAG_V1;"),
     lambda tags: s_legacy_blocked(None, tags)),
    ("marker tag bumped",
     header_mutant('DUMP_TO_GRID_VALID_TAG = "ecco_dump_to_grid_snapshot_valid_v1"', 'DUMP_TO_GRID_VALID_TAG = "ecco_dump_to_grid_snapshot_valid_v2"'),
     lambda tags: s_old_firmware_sees_obligation(None, tags)),
]


def verdict(fn, *args):
    try:
        return fn(*args)
    except ds.Unsupported as e:
        return f"unsupported: {e}"


for label, scenario, build in MUTANTS:
    real = verdict(scenario, FW)
    mutant = verdict(scenario, build())
    check(f"mutant killed - '{label}': safe on the real firmware, detected on the mutant",
          real is True and mutant is False, f"real={real} mutant={mutant}")
for label, tags, scenario in HEADER_MUTANTS:
    real = verdict(scenario, HEADER_TAGS)
    mutant = verdict(scenario, tags)
    check(f"mutant killed - '{label}': safe on the real header, detected on the mutant",
          real is True and mutant is False, f"real={real} mutant={mutant}")
print("  INFO  structural pins also kill: 'R3 relaxed' ([9] R3 tree), 'restore gains ownership pre-read' ([9] frozen "
      "restore tree), 'marker tag bumped' ([2]), 'V1 tag reused' ([2] unique keys).")

# ===========================================================================
print("")
if FAILURES:
    print(f"{len(FAILURES)} check(s) FAILED:")
    for name in FAILURES:
        print(f"  - {name}")
else:
    print("All Dump V2 ownership-evidence tests PASSED.")
print("")
print("These execute the firmware SOURCE under registry/tests/_dump_sim.py. They do not prove ESPHome timing, the")
print("compiled binary, or inverter behaviour. Nothing here consumes the evidence: restore is still blind.")
if FAILURES:
    sys.exit(1)
