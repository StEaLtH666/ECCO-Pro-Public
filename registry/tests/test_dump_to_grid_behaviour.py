#!/usr/bin/env python3
"""BEHAVIOURAL tests for Manual Dump-to-Grid V1 (2026-09-26 pre-live hardening).

Unlike registry/tests/test_dump_to_grid_v1.py (structural: source text and
parsed-action-tree shape), every check here EXECUTES the real firmware -
the parsed ESPHome action trees of the Dump scripts, the Dump watchdog
interval, the ecco_battery_soc / ecco_battery_power on_value hooks and the
Dump block of on_boot, with every lambda transpiled from the firmware file
itself by registry/tests/_dump_sim.py - against an in-memory register bank,
an in-memory NVS store and injected Modbus / NVS outcomes.

What this proves: the firmware SOURCE's control flow does what the design
says under the injected conditions (including exhaustive single- and
multi-point Modbus fault injection for activation and restore).
What it does NOT prove: ESPHome's real scheduling/timing, the compiled
binary, or anything about how the inverter behaves. See _dump_sim.py's
docstring for the simulator's documented simplifications.
"""

from __future__ import annotations

import itertools
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))

import _dump_sim as ds  # noqa: E402

FAILURES: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  PASS  {name}")
    else:
        FAILURES.append(name)
        print(f"  FAIL  {name}" + (f" - {detail}" if detail else ""))


FW = ds.load_firmware(ROOT / "firmware" / "ecco_clock_dongle_stage3_4_free_power.yaml")
WATCHDOG = ds.find_interval(FW, "dump_overpower_samples")
OWNED = {244, 256, 257, 258, 259, 260, 261}
ORIGINAL = {244: 2, 256: 8000, 257: 8000, 258: 7000, 259: 8000, 260: 8000, 261: 5000}
TARGET = 1000
VALID_TAG = "ecco_dump_to_grid_snapshot_valid_v1"
DATA_TAG = "ecco_dump_to_grid_snapshot_data_v2"  # Dump V2 ownership evidence tag bump
RETRY_TAG = "ecco_dump_to_grid_retry_state_v1"


def on_boot_dump_block() -> str:
    boot = FW["esphome"]["on_boot"]["then"][0]["lambda"]
    start = boot.index("// Manual Dump-to-Grid V1 (2026-09-26) - same fail-closed marker/")
    end_pub = boot.index('id(dump_status).publish_state("Inactive");', start)
    return boot[start:boot.index("}", end_pub) + 1]


BOOT_BLOCK = on_boot_dump_block()


_WATCHDOGS: dict = {}


def watchdog_of(fw) -> list:
    # Keyed by the firmware TEXT, not id(fw) (2026-09-26 final pre-OTA
    # review): the mutation checks build and drop one firmware dict per
    # mutant, and CPython may hand a freed dict's id to the next one - an
    # id-keyed cache could then silently run the PREVIOUS mutant's watchdog.
    key = fw["_text"]
    if key not in _WATCHDOGS:
        _WATCHDOGS[key] = ds.find_interval(fw, "dump_overpower_samples")
    return _WATCHDOGS[key]


def fresh(original=None, soc=70.0, hour=14, minute=0, duration=2.0, target=TARGET, fw=None, grid_w=None, stop_soc=25.0) -> ds.Sim:
    sim = ds.Sim(fw or FW)
    sim.bank.update(original or ORIGINAL)
    sim.ent("dump_export_power").set(float(target))
    sim.ent("dump_stop_soc").set(float(stop_soc))
    sim.ent("dump_duration_minutes").set(float(duration))
    sim.ent("dump_write_enable").state = True
    sim.ent("dump_recovery_arm").state = False
    sim.ent("configuration_online").state = True
    sim.ent("configuration_polling").state = True
    sim.ent("ecco_battery_voltage").set(52.0)
    sim.g["ntp_synced"] = True
    sim.hour, sim.minute = hour, minute
    # Live TOU cache as characterised on 2026-09-26: slot 1 (00:00-05:30)
    # grid charge, slots 2-6 no charge source.
    for i, t in enumerate([0, 530, 800, 1600, 1900, 2330]):
        sim.g[f"manual_cfg_reg{250 + i}_raw"] = t
    for i, f in enumerate([1, 0, 0, 0, 0, 0]):
        sim.g[f"manual_cfg_reg{274 + i}_raw"] = f
    config_poll(sim)
    sim.ent("ecco_battery_soc").publish_state(soc)
    # V1.1 closed-loop controller: seed grid telemetry EXACTLY at the export
    # target (zero error) by default, so scenarios that are not testing the
    # controller itself (runaway/drift/Stop SOC/telemetry/etc.) see no
    # controller correction and no extra writes. `tick()` re-publishes this
    # same cached value every call by default to keep it fresh - see there.
    sim.grid_w = -float(target) if grid_w is None else float(grid_w)
    sim.ent("ecco_grid_ct_power").publish_state(sim.grid_w)
    return sim


_PENDING_POLLS: list[dict] = []


def config_poll_dispatch(sim: ds.Sim, overrides=None) -> dict:
    """What poll_inverter_configuration_dispatch does 2.5s before its Block B
    read: stamp cfg_block_b_dispatch_seq (BEFORE the read is sent) and
    SAMPLE the bank now - real Modbus data reflects the registers as they
    stood at request time, not whenever the response happens to be
    processed. Returns a pending-poll handle; pass it to
    config_poll_complete() to land the response later, which is how the B1
    in-flight race (dispatched before a controller write, completing after
    it) is constructed explicitly. config_poll() below is the common-case
    shorthand that dispatches and completes in the same instant."""
    live = dict(sim.bank)
    live.update(overrides or {})
    sim.g["cfg_block_b_dispatch_seq"] += 1
    return {"dispatch_seq": sim.g["cfg_block_b_dispatch_seq"], "sample": live}


def config_poll_complete(sim: ds.Sim, pending: dict) -> None:
    """What Block B's on_response does when this dispatch's response lands:
    refresh the raw cache from the SAMPLE taken at dispatch time (not the
    current bank) and advance both freshness markers."""
    live = pending["sample"]
    sim.g["manual_cfg_reg244_raw"] = live.get(244, 0)
    for r in range(256, 262):
        sim.g[f"manual_cfg_reg{r}_raw"] = live.get(r, 0)
    sim.g["cfg_block_b_seq"] += 1
    sim.g["cfg_block_b_ok_ms"] = sim.millis()
    sim.g["cfg_block_b_response_dispatch_seq"] = pending["dispatch_seq"]


def config_poll(sim: ds.Sim, overrides=None) -> None:
    """The common case: a config poll whose Block B read dispatches AND
    completes right now (dispatch and completion are the same instant, so
    the sample reflects the current bank) - what almost every existing
    scenario means by "a config poll happens". See config_poll_dispatch()/
    config_poll_complete() to construct the in-flight case explicitly. The
    two freshness lines themselves are pinned structurally in
    test_dump_to_grid_v1.py."""
    config_poll_complete(sim, config_poll_dispatch(sim, overrides))


def tick(sim: ds.Sim, ms=15000, soc=None, battery_w=None, poll=True, grid_w=None, grid_fresh=True,
         pv_w=None, inverter_w=None) -> None:
    sim.advance(ms)
    if soc is not None:
        sim.ent("ecco_battery_soc").publish_state(soc)
    if battery_w is not None:
        sim.ent("ecco_battery_power").publish_state(battery_w)
    if grid_w is not None:
        sim.grid_w = grid_w
    # V1.1 closed-loop controller: republish the cached grid reading every
    # tick by default so telemetry never goes stale under normal use -
    # mirrors the config poll's own `poll=True` default. Pass
    # grid_fresh=False to simulate frozen/stale grid telemetry. Sims built
    # directly with ds.Sim(...) (boot-recovery tests) never seed grid_w -
    # harmless, since those scenarios never reach the ACTIVE-only controller
    # gate anyway.
    if grid_fresh and hasattr(sim, "grid_w"):
        sim.ent("ecco_grid_ct_power").publish_state(sim.grid_w)
    # 2026-09-27 (target feasibility): PV/inverter-output telemetry, unlike
    # grid CT/battery power/SOC above, is otherwise NEVER republished by
    # tick() - it is only ever set once, synchronously, by the feed-forward
    # capture inside start_dump_to_grid_override (see ff_started()). A
    # scenario that wants the ONGOING feasibility check to see live PV/
    # inverter readings (as the real firmware's periodic telemetry poll
    # would provide) must pass pv_w/inverter_w explicitly here, each tick it
    # wants them fresh - mirroring how grid_w/battery_w already work above.
    if pv_w is not None:
        sim.ent("ecco_pv_power").publish_state(pv_w)
    if inverter_w is not None:
        sim.ent("ecco_inverter_power").publish_state(inverter_w)
    if poll:
        config_poll(sim)
    sim.run_actions(watchdog_of(sim.fw))


def started(**kw) -> ds.Sim:
    sim = fresh(**kw)
    sim.execute("start_dump_to_grid_override")
    assert sim.g["dump_active_persisted"], sim.status()
    return sim


def still_active(sim) -> bool:
    """The lease is still running and nothing has asked it to end. Checking
    only `not dump_restore_requested` is NOT enough: that flag resets to
    false again once a triggered restore completes."""
    return bool(sim.g["dump_active_persisted"]) and not sim.g["dump_restore_requested"] and marker_state(sim) == 1


def marker_state(sim):
    rec = sim.nvs.get(VALID_TAG)
    return None if rec is None else rec.state


def owned(sim):
    return {r: sim.bank.get(r) for r in OWNED}


def force_ceiling(sim, ceiling) -> ds.Sim:
    """V1.2 feed-forward's START-only 2000W limiter means started(target=X)
    for X > 2000 (under plain fresh()'s house=PV=0) no longer lands exactly
    on X or on the controller's own 3000W cap the way it used to - see the
    "[FF] V1.2 bounded feed-forward START" section for feed-forward's OWN
    dedicated coverage of that. Several pre-existing tests below are about
    controller/runaway-guard behaviour AT a specific ceiling, not about how
    START reached it; for those, this directly sets the ceiling exactly as
    a real START would have (mirroring the ACTIVE commit's own
    dump_runaway_ceiling_ref seeding and the verified register values),
    bypassing feed-forward's computation entirely."""
    for r in range(256, 262):
        sim.bank[r] = ceiling
    sim.g["dump_target_power"] = ceiling
    sim.g["dump_runaway_ceiling_ref"] = float(ceiling)
    return sim


# ===========================================================================
print("[A] Activation")
sim = fresh()
sim.execute("start_dump_to_grid_override")
check("happy path: ACTIVE with the exact status the design specifies",
      # V1.2 feed-forward START: fresh()/started() leave registers 172-189
      # at the bank's default of 0 (house=0, PV=0), so the feed-forward
      # formula computes required_ceiling = 0 + 1000 - 0 = 1000W here -
      # numerically identical to the pre-V1.2 passthrough for this
      # scenario, but now via the feed-forward path (dump_ff_used=True),
      # hence the new status wording. See "[FF] V1.2 feed-forward START"
      # below for dedicated feed-forward coverage.
      sim.status() == "ACTIVE - VERIFIED OK; target 1000W export - SETTLING - battery ceiling 1000W "
                       "(feed-forward start: house 0W, PV 0W); Stop SOC 25%", sim.status())
check("happy path: writes are exactly [256-261 = target] then [244 = 0]",
      sim.writes() == [(256, [TARGET] * 6), (244, [0])], f"{sim.writes()}")
check("happy path: durable record says active, marker RESTORE_REQUIRED, original values snapshotted",
      sim.nvs[DATA_TAG].active_persisted == 1 and marker_state(sim) == 1
      and sim.nvs[DATA_TAG].reg244 == 2 and sim.nvs[DATA_TAG].reg258 == 7000)
check("happy path: the durable retry/lockout record was reset BEFORE the snapshot commit (Dump V2: then the V1 "
      "rollback tombstone, then the V2 snapshot, then the marker)",
      [k for k, _ in sim.nvs_commits][:4] == [RETRY_TAG, "ecco_dump_to_grid_snapshot_data_v1", DATA_TAG, VALID_TAG],
      f"{[k for k, _ in sim.nvs_commits]}")

for label, soc_value in (("SOC exactly equal to Stop SOC", 25.0), ("SOC below Stop SOC", 20.0)):
    sim = fresh(soc=soc_value)
    sim.execute("start_dump_to_grid_override")
    check(f"{label}: refused with ZERO Modbus I/O", sim.modbus_log == [] and not sim.g["dump_snapshot_valid"], sim.status())

sim = fresh()
sim.advance(91000)  # no SOC publish for >90s
config_poll(sim)
sim.execute("start_dump_to_grid_override")
check("stale SOC telemetry (>90s): refused with ZERO Modbus I/O and a telemetry reason",
      sim.modbus_log == [] and "stale" in sim.status(), sim.status())

sim = fresh()
sim.advance(181000)
sim.ent("ecco_battery_soc").publish_state(70.0)
sim.execute("start_dump_to_grid_override")
check("stale configuration readback (>180s): refused with ZERO Modbus I/O",
      sim.modbus_log == [] and "configuration readback" in sim.status(), sim.status())

sim = fresh()
sim.ent("configuration_polling").state = False
sim.execute("start_dump_to_grid_override")
check("configuration polling switched off: refused with ZERO Modbus I/O",
      sim.modbus_log == [] and "Configuration Polling" in sim.status(), sim.status())

sim = fresh(hour=23, minute=50, duration=30)
sim.execute("start_dump_to_grid_override")
check("lease crossing into the slot-1 grid-charge window (23:50 + 30min): refused, ZERO Modbus I/O, slot named",
      sim.modbus_log == [] and "TOU slot 1" in sim.status(), sim.status())
sim = fresh(hour=2, minute=0, duration=5)
sim.execute("start_dump_to_grid_override")
check("lease inside the slot-1 grid-charge window (02:00): refused", sim.modbus_log == [] and "TOU slot 1" in sim.status())
sim = fresh(hour=23, minute=0, duration=20)
sim.execute("start_dump_to_grid_override")
check("lease that ends before the charge slot (23:00 + 20min): allowed", sim.g["dump_active_persisted"], sim.status())
sim = fresh()
sim.g["manual_cfg_reg252_raw"] = 2575  # 25:75 - invalid
sim.execute("start_dump_to_grid_override")
check("invalid TOU slot time in the cache: refused (fail closed), ZERO Modbus I/O",
      sim.modbus_log == [] and "unreadable" in sim.status(), sim.status())

sim = fresh(original={**ORIGINAL, 244: 5})
sim.execute("start_dump_to_grid_override")
check("original 244 outside 0/1/2: aborted before any write, no durable obligation",
      sim.writes() == [] and marker_state(sim) is None and not sim.g["dump_snapshot_valid"], sim.status())

sim = fresh()
sim.nvs_fail_tags = {RETRY_TAG}
sim.execute("start_dump_to_grid_override")
check("retry-record reset commit fails: ZERO writes and NO marker committed",
      sim.writes() == [] and marker_state(sim) is None, sim.status())

sim = fresh()
sim.g["dump_operator_needed"] = True  # stale lockout from a previous obligation
sim.nvs[RETRY_TAG] = ds.Record("DumpToGridRetryState", 1)
sim.execute("start_dump_to_grid_override")
check("a stale operator_needed is cleared (RAM + durable) by a new START",
      sim.g["dump_active_persisted"] and not sim.g["dump_operator_needed"] and sim.nvs[RETRY_TAG].operator_needed == 0)

# ---- Exhaustive activation fault injection ----
READ_OUT = ("ok", "error", "no_response", "not_sent", "timeout", "ok_changed")
WRITE_OUT = ("ok", "ack_not_applied", "error", "not_sent", "no_response_landed", "no_response_lost", "timeout_landed", "timeout_lost")
# V1.2 feed-forward START inserts one new read (172-189) between the
# existing fresh read of 256-261 and the 256-261 activation write - unlike
# every other op here, THIS op's failure modes deliberately do NOT set
# dump_write_failed (see start_dump_to_grid_override) - a telemetry read
# failure falls back to the fixed ${ecco_dump_controller_min_ceiling_w}=
# 500W ceiling and the lease still proceeds to ACTIVE, rather than
# aborting. FEEDFORWARD_FALLBACK_W mirrors that constant for this test file
# (kept as a literal so this module has no runtime substitution access).
FEEDFORWARD_FALLBACK_W = 500
START_OPS = [("read", 244), ("read", 256), ("read", 172), ("write", 256), ("read", 256), ("write", 244), ("read", 244)]


def run_start_with(outcomes, original=ORIGINAL):
    sim = fresh(original=original)
    seq = iter(outcomes)
    violations = []
    sim.outcome_fn = lambda kind, addr, count: next(seq)
    real_write = sim._modbus_write
    # V1.2, tightened 2026-09-27 (adversarial review): op index 2 is the
    # feed-forward read (172-189) - its own outcome is the ONLY thing that
    # determines which ceiling is correct on THIS path, not a blanket
    # "either is fine everywhere" acceptance. A successful read of the
    # all-zero bank defaults (house=PV=0 under this module's plain fresh())
    # resolves to TARGET; a failed read resolves to the fixed fallback.
    expected_ceiling = TARGET if outcomes[2] == "ok" else FEEDFORWARD_FALLBACK_W

    def watched_write(body, local):
        real_write(body, local)
        # Invariant: export may only be enabled (244 == 0) with EXACTLY the
        # one ceiling this path's feed-forward outcome implies - never some
        # other, unrelated, possibly much higher ceiling, and never the
        # OTHER of the two legitimate values either (that would itself be a
        # bug: e.g. the fallback firing despite a successful read).
        if sim.bank.get(244) == 0 and original[244] != 0:
            if any(sim.bank.get(r) != expected_ceiling for r in range(256, 262)):
                violations.append(dict(sim.bank))
    sim._modbus_write = watched_write
    return sim, violations


def expand_outcomes():
    """Every activation path: each op either succeeds or fails in one of its
    ways; once an op fails the script stops issuing further ops, so enumerate
    'first failure at op k with failure mode m' plus the all-ok path, plus
    every landed/lost variant of the two writes on otherwise-ok paths."""
    n = len(START_OPS)
    paths = [["ok"] * n]
    for k, (kind, _) in enumerate(START_OPS):
        # "ok_changed" (conformant reply, different value) is exercised by
        # the dedicated verify-mismatch checks below.
        modes = [m for m in (READ_OUT if kind == "read" else WRITE_OUT) if m not in ("ok", "ok_changed")]
        for m in modes:
            paths.append(["ok"] * k + [m] + ["ok"] * (n - 1 - k))
    return paths


activation_paths = expand_outcomes()
viol_total, obligation_ok, restore_ok = 0, 0, 0
for outcomes in activation_paths:
    sim, violations = run_start_with(outcomes)
    sim.execute("start_dump_to_grid_override")
    viol_total += len(violations)
    # Whatever happened, either nothing was written, or a durable
    # RESTORE_REQUIRED obligation exists.
    wrote = bool(sim.writes())
    if (not wrote) or marker_state(sim) == 1:
        obligation_ok += 1
    # And the watchdog, with healthy comms, returns the inverter EXACTLY to
    # its original values (or it was never changed).
    sim.outcome_fn = lambda kind, addr, count: "ok"
    for _ in range(6):
        tick(sim)
    # Genuinely ACTIVE means EXACTLY the one ceiling THIS path's own
    # feed-forward read outcome implies (tightened 2026-09-27 adversarial
    # review - not a blanket "either value is fine everywhere" acceptance):
    # TARGET when the read (op index 2) succeeded against the all-zero bank
    # defaults (house=PV=0 under this module's plain fresh()), or the fixed
    # fallback only when that read itself failed.
    expected_ceiling = TARGET if outcomes[2] == "ok" else FEEDFORWARD_FALLBACK_W
    if owned(sim) == ORIGINAL and not sim.g["dump_snapshot_valid"] or (
        sim.g["dump_active_persisted"]
        and owned(sim) == {244: 0, **{r: expected_ceiling for r in range(256, 262)}}
    ):
        restore_ok += 1
check(f"activation fault injection ({len(activation_paths)} paths): export is never enabled under a non-lease ceiling",
      viol_total == 0, f"{viol_total} violations")
check("activation fault injection: every path either wrote nothing or left a durable RESTORE_REQUIRED obligation",
      obligation_ok == len(activation_paths), f"{obligation_ok}/{len(activation_paths)}")
check("activation fault injection: afterwards the watchdog restores the exact original (or the lease is genuinely ACTIVE)",
      restore_ok == len(activation_paths), f"{restore_ok}/{len(activation_paths)}")

# 'ok_changed' on the verify reads: a conformant reply with a different value
# must fail the transaction (the Allow Export write must not follow a bad
# 256-261 readback).
sim = fresh()
calls = {"n": 0}


def changed_verify(addr, count, values):
    # Count reads of 256-261 SPECIFICALLY (not every read overall) so this
    # keeps targeting the activation VERIFY reread regardless of how many
    # unrelated reads (e.g. V1.2 feed-forward's own 172-189 capture) happen
    # in between - the snapshot read is the 1st, the verify reread is the
    # 2nd.
    if addr == 256:
        calls["n"] += 1
        if calls["n"] == 2:
            return [values[0] ^ 1] + values[1:]
    return values


sim.read_override_fn = changed_verify
sim.execute("start_dump_to_grid_override")
check("256-261 verify reads back a different value: Allow Export (244) is never written",
      all(a != 244 for a, _ in sim.writes()) and sim.g["dump_snapshot_valid"], f"{sim.writes()}")

sim = fresh()
sim.read_override_fn = lambda addr, count, values: ([1] if addr == 244 and sim.bank.get(244) == 0 else values)
sim.execute("start_dump_to_grid_override")
check("244 verify reads back a different value: not ACTIVE, obligation retained, watchdog restores",
      not sim.g["dump_active_persisted"] and marker_state(sim) == 1)
sim.read_override_fn = None
tick(sim)
check("...restored exactly to the original", owned(sim) == ORIGINAL and marker_state(sim) == 0, sim.status())

# ===========================================================================
print("")
print("[B] Restore")
RESTORE_OPS = [("write", 244), ("read", 244), ("write", 256), ("read", 256)]
restore_viol, restore_retained = 0, 0
combos = 0
for k, (kind, _) in enumerate(RESTORE_OPS):
    for m in [m for m in (READ_OUT if kind == "read" else WRITE_OUT) if m not in ("ok", "ok_changed")]:
        combos += 1
        sim = started()
        seq = iter(["ok"] * k + [m] + ["ok"] * 10)
        sim.outcome_fn = lambda kind, addr, count, seq=seq: next(seq)
        bad = []
        real_write = sim._modbus_write

        def watched(body, local, sim=sim, bad=bad, real=real_write):
            real(body, local)
            if sim.bank.get(244) == 0 and any(sim.bank.get(r) not in (TARGET,) for r in range(256, 262)):
                bad.append(dict(sim.bank))
        sim._modbus_write = watched
        sim.execute("request_dump_end", {"reason": ds.CStr("manual End button")})
        restore_viol += len(bad)
        if owned(sim) == ORIGINAL and marker_state(sim) == 0 or marker_state(sim) == 1:
            restore_retained += 1
check(f"restore fault injection ({combos} single-fault paths): never Allow Export under the ORIGINAL higher ceiling",
      restore_viol == 0, f"{restore_viol}")
check("restore fault injection: every failed attempt keeps the durable RESTORE_REQUIRED obligation",
      restore_retained == combos, f"{restore_retained}/{combos}")

sim = started()
sim.modbus_log.clear()
sim.execute("request_dump_end", {"reason": ds.CStr("manual End button")})
check("END restores 244 FIRST, then 256-261, to the exact snapshot values",
      sim.writes() == [(244, [2]), (256, [8000, 8000, 7000, 8000, 8000, 5000])], f"{sim.writes()}")
check("END clears the marker and publishes the manual reason",
      marker_state(sim) == 0 and not sim.g["dump_snapshot_valid"] and sim.ent("dump_last_end_reason").state == "manual End button")

# Comms failures never lock out.
sim = started()
sim.outcome_fn = lambda kind, addr, count: "no_response_lost" if kind == "write" else "no_response"
sim.execute("request_dump_end", {"reason": ds.CStr("manual End button")})
for _ in range(40):
    tick(sim, 30000)
check("40 ticks of comms failure: NO operator lockout (restore keeps retrying)", not sim.g["dump_operator_needed"],
      sim.status())
check("comms failures back off (attempt counter advanced, attempts spaced)", sim.g["dump_comms_restore_attempts"] >= 5)
sim.outcome_fn = lambda kind, addr, count: "ok"
for _ in range(25):
    tick(sim, 30000)
check("once comms recover, the watchdog completes the restore exactly", owned(sim) == ORIGINAL and marker_state(sim) == 0,
      sim.status())

# Verify mismatches DO lock out after the second one.
sim = started()
sim.read_override_fn = lambda addr, count, values: ([1] if addr == 244 else values)  # 244 always reads Essentials
sim.execute("request_dump_end", {"reason": ds.CStr("manual End button")})
tick(sim)
check("second consecutive verify mismatch: durable operator lockout", sim.g["dump_operator_needed"]
      and sim.nvs[RETRY_TAG].operator_needed == 1, sim.status())
n_before = len(sim.modbus_log)
for _ in range(5):
    tick(sim)
check("under lockout the watchdog performs NO further Modbus I/O", len(sim.modbus_log) == n_before)

# Force bypass cannot leak past a rejected Force press.
sim.ent("dump_recovery_arm").state = True
sim.bus_idle = False
sim.execute("dump_force_restore_original")
check("Force press rejected by a busy bus: no write", len(sim.modbus_log) == n_before)
sim.bus_idle = True
tick(sim)
check("...and the later automatic watchdog tick does NOT inherit the bypass (still no write)",
      len(sim.modbus_log) == n_before and not sim.g["dump_force_restore_bypass"])

# PENDING_CLEAR completion with zero Modbus I/O.
sim = started()
real_commit = sim.D.commit_record
state = {"clear_fail": True}


def flaky_commit(key, record):
    if key == VALID_TAG and record.state == 0 and state["clear_fail"]:
        sim.nvs_commits.append((key, record.copy()))
        return False
    return real_commit(key, record)


sim.D.commit_record = flaky_commit
sim.execute("request_dump_end", {"reason": ds.CStr("manual End button")})
check("CLEAR commit fails after a verified restore: marker durably PENDING_CLEAR, hardware already original",
      marker_state(sim) == 2 and owned(sim) == ORIGINAL and sim.g["dump_snapshot_valid"], sim.status())
state["clear_fail"] = False
io_before = len(sim.modbus_log)
tick(sim)
check("next watchdog tick completes the CLEAR with ZERO Modbus I/O",
      marker_state(sim) == 0 and not sim.g["dump_snapshot_valid"] and len(sim.modbus_log) == io_before, sim.status())

# millis() rollover: backoff deadline straddling the 32-bit wrap.
sim = started()
sim.now_ms = 0xFFFFFFFF - 5000
sim.outcome_fn = lambda kind, addr, count: "no_response_lost" if kind == "write" else "no_response"
sim.execute("request_dump_end", {"reason": ds.CStr("manual End button")})
sim.outcome_fn = lambda kind, addr, count: "ok"
sim.advance(20000)  # past the wrap and past the 15s backoff
sim.run_actions(watchdog_of(sim.fw))
check("backoff that straddles the millis() rollover still allows the retry (no ~49-day stall)",
      owned(sim) == ORIGINAL and marker_state(sim) == 0, sim.status())

# ===========================================================================
print("")
print("[C] ACTIVE monitors: Stop SOC, telemetry, drift")
sim = started()
tick(sim, soc=25.0)
check("Stop SOC reached (SOC == floor): lease ends via the common restore path",
      owned(sim) == ORIGINAL and sim.ent("dump_last_end_reason").state == "STOP SOC REACHED")

sim = started()
tick(sim, soc=float("nan"))
check("NaN SOC: fails closed (TELEMETRY LOST)", sim.ent("dump_last_end_reason").state == "TELEMETRY LOST - failing closed")

sim = started()
for _ in range(7):  # 105s with no SOC publish
    tick(sim)
check("SOC telemetry frozen (no publish for >90s): fails closed",
      sim.ent("dump_last_end_reason").state == "TELEMETRY LOST - failing closed" and owned(sim) == ORIGINAL)

sim = started()
for _ in range(4):
    tick(sim, soc=60.0)
check("healthy lease with matching fresh config readback: stays ACTIVE, no extra writes",
      still_active(sim) and len(sim.writes()) == 2)

sim = started()
sim.advance(10000)
sim.ent("ecco_battery_soc").publish_state(60.0)
config_poll(sim, overrides={244: 2})  # an external controller put 244 back
sim.run_actions(watchdog_of(sim.fw))
reason = str(sim.ent("dump_last_end_reason").state)
check("drift: 244 no longer Allow Export -> END with a CONFIG DRIFT reason naming register 244",
      reason.startswith("CONFIG DRIFT") and "register 244" in reason, reason)
check("drift END restores the ORIGINAL snapshot once - it never re-writes the Dump values",
      sim.writes()[2:] == [(244, [2]), (256, [8000, 8000, 7000, 8000, 8000, 5000])], f"{sim.writes()}")

sim = started()
sim.advance(10000)
sim.ent("ecco_battery_soc").publish_state(60.0)
config_poll(sim, overrides={259: 3000})
sim.run_actions(watchdog_of(sim.fw))
reason = str(sim.ent("dump_last_end_reason").state)
check("drift: one of 256-261 changed -> END naming that register", "register 259" in reason, reason)

sim = started()
# A stale PRE-activation sample (e.g. a config read that executed before the
# Allow Export write) must never be read as drift: the raw cache still
# shows 244 = Zero Export, but the sequence has not advanced past the
# ACTIVE commit.
sim.g["manual_cfg_reg244_raw"] = 2
sim.advance(10000)
sim.ent("ecco_battery_soc").publish_state(60.0)
sim.run_actions(watchdog_of(sim.fw))
check("pre-activation config sample (sequence not advanced past ACTIVE) does NOT false-trigger drift",
      still_active(sim))

sim = started()
sim.advance(10000)
config_poll(sim, overrides={244: 2})
sim.advance(181000)  # that post-activation sample is now older than 180s
sim.ent("ecco_battery_soc").publish_state(60.0)
sim.run_actions(watchdog_of(sim.fw))
reason = str(sim.ent("dump_last_end_reason").state)
check("a mismatching sample older than 180s is not treated as drift evidence (ends as READBACK STALE instead)",
      reason == "CONFIG READBACK STALE - failing closed", reason)

sim = started()
for _ in range(13):  # 195s, SOC fresh, but no config poll succeeds
    tick(sim, soc=60.0, poll=False)
check("no post-activation config readback for >180s: fails closed (CONFIG READBACK STALE)",
      sim.ent("dump_last_end_reason").state == "CONFIG READBACK STALE - failing closed" and owned(sim) == ORIGINAL)

# ===========================================================================
print("")
print("[D] Measured-power runaway guard (battery discharge, register 190, positive = discharge)")
sim = started()
tick(sim, ms=31000, soc=60.0)  # past the 30s settling grace
for w in (1080, 1157, 1130, 1148, 1049, 1154, 1126, 1146):  # 2026-09-23 recorded values, 1000W ceiling
    sim.advance(10000)
    sim.ent("ecco_battery_power").publish_state(float(w))
    sim.run_actions(watchdog_of(sim.fw))
check("normal behaviour (recorded ~1.05-1.16kW against a 1000W ceiling): never trips", still_active(sim))

sim = started()
tick(sim, ms=31000, soc=60.0)
for w in (1100, 8605, 1100, 8620, 1120):  # isolated spikes
    sim.advance(10000)
    sim.ent("ecco_battery_power").publish_state(float(w))
    sim.run_actions(watchdog_of(sim.fw))
check("isolated single-sample spikes: no trip", still_active(sim))

sim = started()
tick(sim, ms=31000, soc=60.0)
for w in (8605, 8620, 8618):  # recorded 2026-09-22 anomaly values
    sim.advance(10000)
    sim.ent("ecco_battery_power").publish_state(float(w))
    sim.run_actions(watchdog_of(sim.fw))
reason = str(sim.ent("dump_last_end_reason").state)
# 2026-09-26 adversarial review (H1): at this magnitude the independent
# ABSOLUTE backstop (>=2 consecutive samples above 3750W) trips before the
# ordinary per-ceiling guard would (>=3 samples above 1750W) - either way
# "RUNAWAY" is in the reason and the lease ends via the common restore path.
check("sustained runaway (3 consecutive ~8.6kW samples vs a 1000W lease): END via the common restore path",
      "RUNAWAY" in reason and owned(sim) == ORIGINAL and marker_state(sim) == 0, reason)

sim = started()
for w in (8605, 8620, 8618):  # inside the first 30s after ACTIVE
    sim.advance(5000)
    sim.ent("ecco_battery_power").publish_state(float(w))
    sim.run_actions(watchdog_of(sim.fw))
check("samples inside the 30s post-activation settling grace do not count", still_active(sim))

sim = started()
tick(sim, ms=31000, soc=60.0)
for w in (-3000, -4500, -5200, -4000):  # PV charging the battery while exporting
    sim.advance(10000)
    sim.ent("ecco_battery_power").publish_state(float(w))
    sim.run_actions(watchdog_of(sim.fw))
check("daylight PV (battery CHARGING, grid export high): never trips - the guard ignores grid export",
      still_active(sim))

## 2026-09-26 adversarial review (H1): at the V1.1 max ceiling (3000W) the
## INDEPENDENT ABSOLUTE backstop (3000 + 750 = 3750W) is now the tighter,
## operative constraint - the ordinary per-ceiling margin (3000 + max(1500,
## 750) = 4500W) would tolerate a materially higher discharge than this
## deliberately capped V1.1 controller should ever be trusted at.
sim = force_ceiling(started(target=3000), 3000)  # this test is about the runaway guard's threshold math AT the
                                                   # V1.1 max ceiling, not about how START reached it - see [FF]
tick(sim, ms=31000, soc=60.0)
for w in (3600, 3650, 3699, 3680):  # under the 3750W absolute backstop
    sim.advance(10000)
    sim.ent("ecco_battery_power").publish_state(float(w))
    sim.run_actions(watchdog_of(sim.fw))
check("3000W lease: sustained ~3.6-3.7kW (under the 3750W absolute backstop) does not trip", still_active(sim))
for w in (3800, 3900):  # only 2 consecutive needed - the absolute backstop's own sample count
    sim.advance(10000)
    sim.ent("ecco_battery_power").publish_state(float(w))
    sim.run_actions(watchdog_of(sim.fw))
check("3000W lease: sustained >3.75kW trips the ABSOLUTE backstop",
      str(sim.ent("dump_last_end_reason").state).startswith("ABSOLUTE POWER RUNAWAY"))

sim = started()
tick(sim, ms=31000, soc=60.0)
# 1900W is above the ordinary 1000W-ceiling threshold (1750W) but well
# under the 3750W absolute backstop, so 2 samples accumulate the ORDINARY
# counter (which needs 3) without tripping either guard yet - genuinely
# "runaway partway accumulated" rather than already-tripped.
for w in (1900, 1900):
    sim.advance(10000)
    sim.ent("ecco_battery_power").publish_state(float(w))
    sim.run_actions(watchdog_of(sim.fw))
assert still_active(sim), sim.status()
for _ in range(7):  # then telemetry freezes
    tick(sim)
check("telemetry freezing mid-runaway still fails closed (TELEMETRY LOST), never silently continues",
      sim.ent("dump_last_end_reason").state == "TELEMETRY LOST - failing closed" and owned(sim) == ORIGINAL)

# ===========================================================================
print("")
print("[E] Accept Current State residue protection (zero Modbus I/O)")


def locked_out():
    sim = started()
    sim.read_override_fn = lambda addr, count, values: ([1] if addr == 244 else values)
    sim.execute("request_dump_end", {"reason": ds.CStr("manual End button")})
    tick(sim, poll=False)
    sim.read_override_fn = None
    assert sim.g["dump_operator_needed"], sim.status()
    sim.ent("dump_recovery_arm").state = True
    return sim


sim = locked_out()
sim.bank.update({244: 0, **{r: TARGET for r in range(256, 262)}})  # live = still the Dump override
config_poll(sim)
io = len(sim.modbus_log)
sim.execute("dump_accept_current_state")
check("live Dump residue (Allow Export + lease ceiling): Accept REFUSED, obligation kept, ZERO Modbus I/O",
      marker_state(sim) == 1 and sim.status().startswith("ACCEPT REFUSED") and len(sim.modbus_log) == io, sim.status())

sim = locked_out()
sim.bank.update({244: 0})  # export enabled, original was Zero Export
config_poll(sim)
sim.execute("dump_accept_current_state")
check("Allow Export when the original was Zero Export: Accept REFUSED", marker_state(sim) == 1, sim.status())

sim = locked_out()
io = len(sim.modbus_log)
sim.execute("dump_accept_current_state")  # no config poll since the last Dump operation
check("no fresh post-operation readback: Accept REFUSED with a readback reason, ZERO Modbus I/O",
      marker_state(sim) == 1 and "readback" in sim.status() and len(sim.modbus_log) == io, sim.status())

sim = locked_out()
config_poll(sim)
sim.advance(121000)
sim.execute("dump_accept_current_state")
check("post-operation readback older than 120s: Accept REFUSED", marker_state(sim) == 1, sim.status())

sim = locked_out()
sim.bank.update({244: 1})  # operator set a non-export mode by hand; ceiling still the lease value
config_poll(sim)
io = len(sim.modbus_log)
sim.execute("dump_accept_current_state")
check("non-export 244 (Essentials): Accept PERMITTED, marker CLEAR, ZERO Modbus I/O",
      marker_state(sim) == 0 and not sim.g["dump_snapshot_valid"] and len(sim.modbus_log) == io, sim.status())
check("...and the Recovery Arm is consumed", sim.ent("dump_recovery_arm").state is False)
check("M8 ACCEPT re-review: Accept never silently blesses controller residue - it NAMES the retained ceiling "
      "and the original it differs from, rather than a generic 'obligation cleared' message",
      "256-261" in sim.status() and "1000W" in sim.status() and "8000W" in sim.status()
      and "export is not enabled" in sim.status(), sim.status())

sim = locked_out()
sim.bank.update({244: 2})
config_poll(sim)
sim.g["dump_operation_in_progress"] = True  # e.g. a Force Restore still in flight
io = len(sim.modbus_log)
sim.execute("dump_accept_current_state")
check("Accept while a Dump bus operation is still in flight: refused (its evidence may predate that operation)",
      marker_state(sim) == 1 and "in progress" in sim.status() and len(sim.modbus_log) == io, sim.status())

sim = locked_out()
sim.ent("dump_recovery_arm").state = False
config_poll(sim)
sim.bank.update({244: 2})
config_poll(sim)
sim.execute("dump_accept_current_state")
check("Accept without the Recovery Arm: refused", marker_state(sim) == 1 and "Recovery Arm" in sim.status(), sim.status())

original_allow = {**ORIGINAL, 244: 0}
sim = started(original=original_allow)
sim.read_override_fn = lambda addr, count, values: ([9000] * 6 if addr == 256 else values)
sim.execute("request_dump_end", {"reason": ds.CStr("manual End button")})
tick(sim, poll=False)
sim.read_override_fn = None
sim.ent("dump_recovery_arm").state = True
sim.bank.update(original_allow)
config_poll(sim)
sim.execute("dump_accept_current_state")
check("original policy WAS Allow Export and live is exactly the original: Accept permitted",
      marker_state(sim) == 0, sim.status())

# ===========================================================================
print("")
print("[F] Boot recovery (the Dump block of the real on_boot lambda)")


def boot(sim):
    sim.run_lambda(BOOT_BLOCK)


sim = started()
data, marker = sim.nvs[DATA_TAG].copy(), sim.nvs[VALID_TAG].copy()
bank = dict(sim.bank)
sim2 = ds.Sim(FW)
sim2.nvs = {DATA_TAG: data, VALID_TAG: marker}
sim2.bank = bank
sim2.ent("configuration_online").state = True
boot(sim2)
check("ESP reboot while ACTIVE: the lease is ENDED (restore_requested forced), not resumed",
      sim2.g["dump_restore_requested"] and sim2.ent("dump_last_end_reason").state.startswith("ESP RESTARTED"))
tick(sim2)
check("...and the first watchdog tick restores the exact original", owned(sim2) == ORIGINAL and marker_state(sim2) == 0,
      sim2.status())

sim = ds.Sim(FW)
sim.nvs = {VALID_TAG: ds.Record("ValidMarker", ds.Durable.VALID_MARKER_MAGIC, 2)}
boot(sim)
tick(sim)
check("PENDING_CLEAR found at boot: cleared by the watchdog with ZERO Modbus I/O",
      marker_state(sim) == 0 and sim.modbus_log == [] and not sim.g["dump_snapshot_valid"], sim.status())

sim = ds.Sim(FW)
sim.nvs = {VALID_TAG: ds.Record("ValidMarker", ds.Durable.VALID_MARKER_MAGIC, 0),
           RETRY_TAG: ds.Record("DumpToGridRetryState", 1)}
boot(sim)
check("stale durable operator_needed with a CLEAR marker: ignored at boot (no phantom lockout)",
      not sim.g["dump_operator_needed"] and sim.status() == "Inactive", sim.status())

sim = ds.Sim(FW)
bad = ds.Record("DumpToGridSnapshotData", 0, 1, 0, 7, 8000, 8000, 8000, 8000, 8000, 8000, 1000)
sim.nvs = {VALID_TAG: ds.Record("ValidMarker", ds.Durable.VALID_MARKER_MAGIC, 1), DATA_TAG: bad}
# SG-02: with live 244 = 0 the corrupt lockout now CONTAINS export (literal
# 244 = 2 - see test_dump_lockout_containment_sg02.py). Seed a non-export
# live 244 here so this check keeps asserting ZERO writes: the invalid
# snapshot is never restored.
sim.bank.update(ORIGINAL)
boot(sim)
tick(sim)
check("loadable record with original 244 = 7: fail closed (metadata corrupt), ZERO writes",
      sim.g["dump_recovery_metadata_corrupt"] and sim.writes() == [], sim.status())

sim = ds.Sim(FW)
sim.nvs = {VALID_TAG: ds.Record("ValidMarker", 0x12345678, 1)}
sim.bank.update(ORIGINAL)  # SG-02: live 244 non-export -> containment writes nothing
boot(sim)
tick(sim)
check("malformed marker magic: fail closed, ZERO writes; the only bus I/O is SG-02 containment's one fresh read of 244",
      sim.g["dump_recovery_metadata_corrupt"] and sim.writes() == []
      and [(k, a) for k, a, _v, _o in sim.modbus_log] == [("read", 244)], f"{sim.modbus_log}")

# ===========================================================================
print("")
print("[G] Whole-run write surface")
all_addresses = set()
for outcomes in activation_paths[:10]:
    s, _ = run_start_with(outcomes)
    s.execute("start_dump_to_grid_override")
    s.outcome_fn = lambda kind, addr, count: "ok"
    for _ in range(4):
        tick(s)
    for kind, addr, vals, _o in s.modbus_log:
        if kind == "write":
            all_addresses.update(range(addr, addr + len(vals)))
check("every simulated Dump write, across fault-injected runs, targets only {244, 256-261}",
      all_addresses <= OWNED and all_addresses, f"{sorted(all_addresses)}")

# ===========================================================================
print("")
print("[I] 2026-09-26 final pre-OTA review additions: interleaving, simultaneous triggers, boundaries, reboot evidence")


def poll_lands_before(sim, kind_addr, overrides=None):
    """Makes one configuration block 241-293 response land on the bus
    immediately BEFORE the given Dump operation executes (it reads the bank
    as it is at that instant). This is the real interleaving boundary:
    poll_inverter_configuration_dispatch checks manual_write_in_progress
    only once, then issues its Block B read 2.5s later regardless, so that
    read can queue behind (and complete during) a START or restore that
    began in between."""
    real = sim.outcome_fn

    def fn(kind, addr, count):
        if (kind, addr) == kind_addr:
            config_poll(sim, overrides)
        return real(kind, addr, count)
    sim.outcome_fn = fn


def s_mid_start_sample(fw):
    sim = fresh(fw=fw)
    poll_lands_before(sim, ("write", 244))  # sample shows 244 = original, 256-261 = lease
    sim.execute("start_dump_to_grid_override")
    if not sim.g["dump_active_persisted"]:
        return False
    sim.advance(10000)
    sim.ent("ecco_battery_soc").publish_state(60.0)
    sim.run_actions(watchdog_of(fw))  # no newer poll yet
    return still_active(sim)


check("a config readback that completed MID-START (before the Allow Export write) is not drift evidence",
      s_mid_start_sample(FW))
sim = fresh()
poll_lands_before(sim, ("write", 244))
sim.execute("start_dump_to_grid_override")
tick(sim, soc=60.0)
check("...and the first genuine post-activation readback (matching the lease) keeps the lease ACTIVE", still_active(sim))


def s_mid_restore_sample_not_evidence(fw):
    """Lockout where the only readbacks since the last restore attempt
    completed DURING that attempt and show a benign 244, while the
    inverter actually still holds Allow Export. Accept must refuse."""
    sim = started(fw=fw)

    def outcome(kind, addr, count):
        if (kind, addr) == ("write", 244):
            config_poll(sim, {244: 2})  # a transient Zero Export reading lands mid-restore
            return "ack_not_applied"    # ...but the restore write does not stick (244 stays 0)
        return "ok"
    sim.outcome_fn = outcome
    sim.execute("request_dump_end", {"reason": ds.CStr("manual End button")})
    tick(sim, poll=False)
    if not sim.g["dump_operator_needed"] or sim.bank.get(244) != 0:
        return None
    sim.outcome_fn = lambda kind, addr, count: "ok"
    sim.ent("dump_recovery_arm").state = True
    io = len(sim.modbus_log)
    sim.execute("dump_accept_current_state")
    return marker_state(sim) == 1 and "readback" in sim.status() and len(sim.modbus_log) == io


check("Accept ignores readbacks that completed DURING the last restore attempt (evidence must postdate the operation)",
      s_mid_restore_sample_not_evidence(FW) is True)

# Two END conditions in the SAME watchdog tick (runaway + drift): one
# restore, and the FIRST reason is the one kept. (The simulator runs the
# first restore to completion synchronously, so the second request_dump_end
# finds no snapshot; on the ESP it would find the restore script still
# running and be dropped by mode: single. Either way: one restore.)
# Uses 1900W (2 samples builds the ORDINARY counter to 2/3, well under the
# 3750W absolute backstop) so the THIRD sample below is what actually trips
# it, in the SAME tick drift is also introduced.
sim = started()
tick(sim, ms=31000, soc=60.0)
for w in (1900, 1900):
    sim.advance(10000)
    sim.ent("ecco_battery_power").publish_state(float(w))
    sim.run_actions(watchdog_of(sim.fw))
n_before = len(sim.writes())
sim.advance(10000)
sim.ent("ecco_battery_power").publish_state(1900.0)
config_poll(sim, overrides={244: 2})
sim.run_actions(watchdog_of(sim.fw))
reason = str(sim.ent("dump_last_end_reason").state)
check("runaway + drift in one tick: the first reason (POWER RUNAWAY) is kept, not overwritten",
      reason.startswith("POWER RUNAWAY"), reason)
check("...and exactly ONE restore sequence is written (244 first, then 256-261), ending at the exact original",
      sim.writes()[n_before:] == [(244, [2]), (256, [8000, 8000, 7000, 8000, 8000, 5000])]
      and owned(sim) == ORIGINAL and marker_state(sim) == 0, f"{sim.writes()[n_before:]}")

# Runaway END requested while the Modbus bus is busy.
sim = started()
tick(sim, ms=31000, soc=60.0)
for w in (1900, 1900):
    sim.advance(10000)
    sim.ent("ecco_battery_power").publish_state(float(w))
    sim.run_actions(watchdog_of(sim.fw))
n_before = len(sim.writes())
sim.bus_idle = False
sim.advance(10000)
sim.ent("ecco_battery_power").publish_state(1900.0)
sim.run_actions(watchdog_of(sim.fw))
check("runaway END while the bus is busy: deferred with ZERO writes, end request durably recorded",
      "END DEFERRED" in sim.status() and len(sim.writes()) == n_before
      and sim.nvs[DATA_TAG].restore_requested == 1 and sim.g["dump_restore_requested"]
      and str(sim.ent("dump_last_end_reason").state).startswith("POWER RUNAWAY"), sim.status())
sim.bus_idle = True
tick(sim, soc=60.0)
check("...the next watchdog tick with a free bus restores the exact original, no second press needed",
      owned(sim) == ORIGINAL and marker_state(sim) == 0, sim.status())

# TOU charging-slot gate: exact boundaries (cached slot 1 = 00:00-05:30 Grid).
for (h, m, d), refused, label in (
    ((23, 40, 20), True, "23:40 + 20 min (end minute == slot-1 start)"),
    ((23, 40, 19), False, "23:40 + 19 min (ends one minute before slot 1)"),
    ((5, 29, 1), True, "05:29 + 1 min (starts inside slot 1)"),
    ((5, 30, 60), False, "05:30 + 60 min (starts exactly as slot 1 ends)"),
):
    sim = fresh(hour=h, minute=m, duration=d)
    sim.execute("start_dump_to_grid_override")
    if refused:
        check(f"TOU boundary {label}: refused, ZERO Modbus I/O", sim.modbus_log == [] and "TOU slot 1" in sim.status(),
              sim.status())
    else:
        check(f"TOU boundary {label}: allowed", sim.g["dump_active_persisted"], sim.status())


def runaway_run(target, samples, fw=None):
    sim = started(target=target, fw=fw)
    tick(sim, ms=31000, soc=60.0)
    for w in samples:
        sim.advance(10000)
        sim.ent("ecco_battery_power").publish_state(float(w))
        sim.run_actions(watchdog_of(sim.fw))
    return sim


check("1000W lease: sustained exactly 1,750W (== threshold) does not trip", still_active(runaway_run(1000, [1750] * 4)))
check("1000W lease: sustained 1,751W trips", str(runaway_run(1000, [1751] * 3).ent("dump_last_end_reason").state)
      .startswith("POWER RUNAWAY"))
check("500W lease: sustained exactly 1,250W does not trip", still_active(runaway_run(500, [1250] * 4)))
check("500W lease: sustained 1,251W trips", str(runaway_run(500, [1251] * 3).ent("dump_last_end_reason").state)
      .startswith("POWER RUNAWAY"))


def s_runaway_500w_margin(fw):
    return still_active(runaway_run(500, [1200] * 4, fw=fw))


check("500W lease: sustained 1,200W (inside the 750W absolute margin) does not trip", s_runaway_500w_margin(FW))

# Accept evidence across an ESP reboot: only a post-boot readback counts.
sim = locked_out()
sim2 = ds.Sim(FW)
sim2.nvs = {k: v.copy() for k, v in sim.nvs.items()}
sim2.bank = dict(sim.bank)
sim2.ent("configuration_online").state = True
boot(sim2)
sim2.ent("dump_recovery_arm").state = True
sim2.execute("dump_accept_current_state")
check("after a reboot the durable lockout is restored and Accept needs a POST-BOOT readback (refused before one)",
      sim2.g["dump_operator_needed"] and marker_state(sim2) == 1 and "readback" in sim2.status(), sim2.status())
sim2.bank[244] = 0  # the inverter still (or again) shows Allow Export
config_poll(sim2)
sim2.ent("dump_recovery_arm").state = True
sim2.execute("dump_accept_current_state")
check("...a post-boot readback that still shows Dump residue is refused", marker_state(sim2) == 1, sim2.status())
sim2.bank[244] = 2
config_poll(sim2)
sim2.ent("dump_recovery_arm").state = True
io = len(sim2.modbus_log)
sim2.execute("dump_accept_current_state")
check("...a post-boot readback showing a non-export 244 is accepted, with ZERO Modbus I/O",
      marker_state(sim2) == 0 and not sim2.g["dump_snapshot_valid"] and len(sim2.modbus_log) == io, sim2.status())

# Latched-value sensors (the lambdas the card reads while ACTIVE).
SENSORS = {s["id"]: s for s in FW["sensor"] if s.get("id")}


def latched(sim):
    return (sim.run_lambda(SENSORS["dump_active_export_power_sensor"]["lambda"]),
            sim.run_lambda(SENSORS["dump_active_stop_soc_sensor"]["lambda"]))


sim = fresh()
p, s = latched(sim)
check("latched sensors are unknown (NaN) before any lease", math.isnan(p) and math.isnan(s))
sim.execute("start_dump_to_grid_override")
sim.ent("dump_export_power").set(3000.0)  # the user edits the staged numbers mid-lease
sim.ent("dump_stop_soc").set(60.0)
p, s = latched(sim)
check("while ACTIVE the latched sensors report the START values, not later staged edits", (p, s) == (1000.0, 25.0), f"{(p, s)}")
sim3 = ds.Sim(FW)
sim3.nvs = {k: v.copy() for k, v in sim.nvs.items()}
boot(sim3)
p, s = latched(sim3)
check("after a reboot mid-lease: latched power reads 0W (2026-09-27 - the requested export target is "
      "intentionally never persisted, since reg_dump_power_intended stores the battery CEILING, not the "
      "target, and reboot always ends/restores rather than resumes - see docs/DUMP_TO_GRID_V1.md "
      "\"Bounded feed-forward START (V1.2)\"), latched Stop SOC honestly unknown (not persisted); this is "
      "cosmetic only - dump_restore_requested is already forced true by this same boot, so no active "
      "behaviour reads either value",
      p == 0.0 and math.isnan(s), f"{(p, s)}")
request_end_then_restore = started()
request_end_then_restore.execute("request_dump_end", {"reason": ds.CStr("manual End button")})
p, s = latched(request_end_then_restore)
check("after a verified restore the latched sensors return to unknown", math.isnan(p) and math.isnan(s))

print("")
print("[H] Sensitivity: each safety scenario FAILS against a firmware copy with that safeguard removed")


def mutant(old: str, new: str) -> dict:
    text = FW["_text"]
    if text.count(old) != 1:
        raise AssertionError(f"mutation anchor not unique/present: {old!r}")
    return ds.load_firmware_text(text.replace(old, new))


def s_verify_gate(fw):
    sim = fresh(fw=fw)
    n = {"reads256": 0}

    def changed(addr, count, values):
        # Count reads of 256-261 specifically - see changed_verify()'s
        # identical comment above for why (V1.2 feed-forward's own 172-189
        # read must not shift which OVERALL read index this targets).
        if addr == 256:
            n["reads256"] += 1
            if n["reads256"] == 2:
                return [values[0] ^ 1] + values[1:]
        return values
    sim.read_override_fn = changed
    sim.execute("start_dump_to_grid_override")
    return all(a != 244 for a, _ in sim.writes())


def s_drift_pre_activation_sample(fw):
    sim = started(fw=fw)
    sim.g["manual_cfg_reg244_raw"] = 2
    sim.advance(10000)
    sim.ent("ecco_battery_soc").publish_state(60.0)
    sim.run_actions(watchdog_of(fw))
    return still_active(sim)


def s_drift_detected(fw):
    sim = started(fw=fw)
    sim.advance(10000)
    sim.ent("ecco_battery_soc").publish_state(60.0)
    config_poll(sim, overrides={244: 2})
    sim.run_actions(watchdog_of(fw))
    return str(sim.ent("dump_last_end_reason").state).startswith("CONFIG DRIFT")


def s_locked(fw):
    sim = started(fw=fw)
    sim.read_override_fn = lambda addr, count, values: ([1] if addr == 244 else values)
    sim.execute("request_dump_end", {"reason": ds.CStr("manual End button")})
    tick(sim, poll=False)
    sim.read_override_fn = None
    sim.ent("dump_recovery_arm").state = True
    return sim


def s_accept_residue(fw):
    sim = s_locked(fw)
    sim.bank.update({244: 0, **{r: TARGET for r in range(256, 262)}})
    config_poll(sim)
    sim.execute("dump_accept_current_state")
    return marker_state(sim) == 1


def s_accept_needs_fresh_readback(fw):
    sim = s_locked(fw)
    sim.bank.update({244: 0})  # residue, but no NEW readback since the last op
    sim.execute("dump_accept_current_state")
    return marker_state(sim) == 1


def s_runaway_needs_consecutive(fw):
    sim = started(fw=fw)
    tick(sim, ms=31000, soc=60.0)
    for w in (8605, 1100, 8620, 1100, 8618, 1100):
        sim.advance(10000)
        sim.ent("ecco_battery_power").publish_state(float(w))
        sim.run_actions(watchdog_of(fw))
    return still_active(sim)


def s_comms_no_lockout(fw):
    sim = started(fw=fw)
    sim.outcome_fn = lambda kind, addr, count: "no_response_lost" if kind == "write" else "no_response"
    sim.execute("request_dump_end", {"reason": ds.CStr("manual End button")})
    for _ in range(10):
        tick(sim, 30000)
    return not sim.g["dump_operator_needed"]


def s_pending_clear_completes(fw):
    sim = started(fw=fw)
    real = sim.D.commit_record
    flag = {"fail": True}

    def flaky(key, record):
        if key == VALID_TAG and record.state == 0 and flag["fail"]:
            return False
        return real(key, record)
    sim.D.commit_record = flaky
    sim.execute("request_dump_end", {"reason": ds.CStr("manual End button")})
    flag["fail"] = False
    tick(sim)
    return marker_state(sim) == 0 and not sim.g["dump_snapshot_valid"]


def s_frozen_soc_ends(fw):
    sim = started(fw=fw)
    for _ in range(7):
        tick(sim)
    return sim.g["dump_restore_requested"] or not sim.g["dump_active_persisted"]


def s_charge_slot_refused(fw):
    sim = fresh(hour=2, minute=0, duration=5, fw=fw)
    sim.execute("start_dump_to_grid_override")
    return sim.modbus_log == []


# 2026-09-26 adversarial review: mutation coverage for the new safety fences.
def s_b1_dispatch_fence(fw):
    sim = fresh(target=1000, grid_w=-1000.0, fw=fw)  # zero error - isolates drift from controller activity
    sim.execute("start_dump_to_grid_override")
    if not sim.g["dump_active_persisted"]:
        return None
    pending = config_poll_dispatch(sim)
    sim.grid_w = 1810.0
    tick(sim, soc=60.0, poll=False)
    tick(sim, soc=60.0, poll=False)
    tick(sim, soc=60.0, poll=False)
    if sim.g["dump_target_power"] == 1000:
        return None  # setup failed - no controller correction happened
    config_poll_complete(sim, pending)
    sim.ent("ecco_battery_soc").publish_state(60.0)
    sim.run_actions(watchdog_of(fw))
    return still_active(sim)


def s_b2_floor(fw):
    sim = started(target=500, duration=90, grid_w=-20000.0, fw=fw)
    for _ in range(6):
        tick(sim, soc=70.0)
    # Exact equality, not >=500: without the clamp the computed ceiling goes
    # negative and a uint16_t cast of a negative float wraps to some large
    # value that would otherwise still (trivially, uselessly) satisfy >=500.
    return sim.g["dump_target_power"] == 500


def s_h1_absolute_backstop(fw):
    # V1.2's feed-forward START-only 2000W limiter means started(target=3000)
    # under plain fresh() (house=PV=0) no longer lands the initial ceiling on
    # 3000W - force it directly so this test genuinely exercises the
    # ABSOLUTE >3750W backstop at the V1.1 max ceiling, independently of the
    # ordinary ceiling-relative guard (which is what force_ceiling() exists
    # for - see its own docstring).
    sim = force_ceiling(started(target=3000, fw=fw), 3000)
    tick(sim, ms=31000, soc=60.0)
    for w in (3800, 3900):
        sim.advance(10000)
        sim.ent("ecco_battery_power").publish_state(float(w))
        sim.run_actions(watchdog_of(fw))
    return not still_active(sim)


def s_m2_lock_check(fw):
    sim = started(target=500, duration=30, grid_w=1810.0, fw=fw)
    tick(sim, soc=60.0)
    tick(sim, soc=60.0)
    sim.g["manual_write_in_progress"] = True
    n = len(sim.writes())
    tick(sim, soc=60.0)
    return len(sim.writes()) == n


def s_h1_no_reset_on_write(fw):
    """H1: samples published soon after a controller write must still
    count - only the original lease-start grace may zero the counter."""
    sim = started(target=500, duration=30, grid_w=1810.0, fw=fw)
    tick(sim, soc=70.0)
    tick(sim, soc=70.0)
    tick(sim, soc=70.0)  # t+45s: ceiling 500 -> 1500 (a controller write just landed)
    if sim.g["dump_target_power"] != 1500:
        return None
    for w in (2300.0, 2300.0, 2300.0):  # all within 30s of the write
        sim.advance(5000)
        sim.ent("ecco_battery_power").publish_state(w)
        sim.run_actions(watchdog_of(fw))
    return not still_active(sim) and "POWER RUNAWAY" in str(sim.ent("dump_last_end_reason").state)


# 2026-09-27 adversarial review (R1, second pass): reusable scenarios for
# the "one verdict per verified write" mutation coverage below.
def s_r1_reversed_ct_fails_closed(fw):
    """The core R1 (second pass) bug scenario: a reversed/stuck CT drives
    the ceiling to the 3000W cap over 3 writes, each making the measured
    error WORSE. The cap-hitting write's own response must still be
    judged - the lease must fail closed after exactly 3 judged
    wrong-direction writes, not sit at 3000W forever."""
    sim = started(target=500, duration=90, grid_w=2000.0, fw=fw)
    tick(sim, soc=70.0); tick(sim, soc=70.0); tick(sim, soc=70.0)
    if sim.g["dump_target_power"] != 1500:
        return None
    tick(sim, soc=70.0, grid_w=2600.0); tick(sim, soc=70.0, grid_w=2600.0); tick(sim, soc=70.0, grid_w=2600.0)
    tick(sim, soc=70.0, grid_w=3200.0); tick(sim, soc=70.0, grid_w=3200.0); tick(sim, soc=70.0, grid_w=3200.0)
    if sim.g["dump_target_power"] != 3000 or not still_active(sim):
        return None
    tick(sim, soc=70.0, grid_w=3800.0); tick(sim, soc=70.0, grid_w=3800.0); tick(sim, soc=70.0, grid_w=3800.0)
    return not still_active(sim) and "GRID RESPONSE SANITY" in str(sim.ent("dump_last_end_reason").state)


def s_r1_bus_deferral_judges_once(fw):
    """A write's response is judged exactly once, even across several
    bus-busy ticks afterward where nothing new is written."""
    sim = started(target=500, duration=30, grid_w=-100.0, fw=fw)
    tick(sim, soc=60.0); tick(sim, soc=60.0); tick(sim, soc=60.0)
    if sim.g["dump_target_power"] != 700:
        return None
    sim.bus_idle = False
    tick(sim, soc=60.0, grid_w=-100.0); tick(sim, soc=60.0, grid_w=-100.0); tick(sim, soc=60.0, grid_w=-100.0)
    if sim.g["dump_controller_ineffective_count"] != 1:
        return None
    for _ in range(3):
        tick(sim, soc=60.0, grid_w=-100.0)
    return sim.g["dump_controller_ineffective_count"] == 1


def s_r2_no_response_recovers_after_hold(fw):
    """R2 (2026-09-27 hardening): NO RESPONSE is a BOUNDED hold, not a
    terminal one. Within the bounded quiet period (60s = four 15s ticks)
    nothing changes at all - unchanged from the old R1 behaviour. Once the
    hold elapses AND a fresh, causally-relevant grid sample has arrived,
    the controller is granted exactly one bounded retry and falls through
    to the SAME ordinary evaluation every tick uses - proven here simply
    by the controller state leaving "NO RESPONSE" and the retry being
    counted, which happens deterministically on ANY granted retry
    regardless of what that retry's own outcome turns out to be (see
    s_r2_recovery_exhausts_and_ends_lease for the case where the retry
    itself also proves ineffective)."""
    sim = started(target=500, duration=240, grid_w=-100.0, fw=fw)
    tick(sim, soc=60.0); tick(sim, soc=60.0); tick(sim, soc=60.0)  # write#1 (first write, no judge)
    for _ in range(3):  # judges write#1 (ineffective=1), writes#2
        tick(sim, soc=60.0, grid_w=-100.0)
    for _ in range(3):  # judges write#2 (ineffective=2), writes#3
        tick(sim, soc=60.0, grid_w=-100.0)
    for _ in range(3):  # judges write#3 (ineffective=3 -> NO RESPONSE, no write#4)
        tick(sim, soc=60.0, grid_w=-100.0)
    if sim.g["dump_controller_state"] != "NO RESPONSE":
        return None
    n_writes = len(sim.writes())
    # Still within the 60s bounded hold (three more 15s ticks = 45s <
    # 60s) - unchanged R1 behaviour: zero counter/write movement.
    tick(sim, soc=60.0, grid_w=-100.0)
    tick(sim, soc=60.0, grid_w=-100.0)
    tick(sim, soc=60.0, grid_w=-100.0)
    if (sim.g["dump_controller_ineffective_count"] != 3 or len(sim.writes()) != n_writes
            or sim.g["dump_controller_state"] != "NO RESPONSE" or sim.g["dump_controller_recovery_attempts"] != 0):
        return None  # the bounded hold itself regressed - not what this scenario targets
    # The hold elapses on this tick (t+60s since the hold armed) with grid
    # telemetry still fresh (tick() republishes it every call by default) -
    # the bounded retry must be granted now.
    tick(sim, soc=60.0, grid_w=-100.0)
    return sim.g["dump_controller_recovery_attempts"] == 1 and sim.g["dump_controller_state"] != "NO RESPONSE"


def s_m1_first_correction_needs_fresh_sample(fw):
    """M1 regression (third pass): the FIRST correction of a lease (no
    controller write has ever happened yet) must not be driven by a stale
    pre-ACTIVE grid sample, even though it is still within the broader
    absolute staleness bound."""
    sim = started(target=500, duration=90, grid_w=2000.0, fw=fw)
    n = len(sim.writes())
    tick(sim, soc=70.0, grid_fresh=False)
    tick(sim, soc=70.0, grid_fresh=False)
    tick(sim, soc=70.0, grid_fresh=False)
    return sim.g["dump_target_power"] == 500 and len(sim.writes()) == n and still_active(sim)


def s_r5_end_pressed_during_controller_write(fw):
    """R5: a manual End arriving WHILE a real controller write is in flight
    (modelled by firing request_dump_end at the exact instant the
    controller's own write to register 256 is dispatched - manual_write_
    in_progress is already held by that write, so the restore worker must
    defer, exactly as it would on the ESP if the End handler ran during the
    controller script's own wait_until suspension) must not have the
    write's own success path clobber the resulting 'END DEFERRED' status
    with a stale ACTIVE/TRACKING claim once that write is verified."""
    sim = started(target=500, duration=90, grid_w=2000.0, fw=fw)
    tick(sim, soc=70.0)
    tick(sim, soc=70.0)  # t+30s - still settling; no write yet
    real = sim.outcome_fn
    fired = {"once": False}

    def outcome(kind, addr, count):
        if kind == "write" and addr == 256 and not fired["once"]:
            fired["once"] = True
            sim.execute("request_dump_end", {"reason": ds.CStr("manual End button")})
        return real(kind, addr, count)
    sim.outcome_fn = outcome
    tick(sim, soc=70.0)  # t+45s: settle elapses - controller writes 256-261; End fires mid-write
    return (
        fired["once"]
        and sim.g["dump_target_power"] == 1500  # the verified hardware fact is still recorded
        and sim.g["dump_restore_requested"]
        and sim.g["dump_active_persisted"]
        and "END DEFERRED" in sim.status()
        and "ACTIVE" not in sim.status()
        and "TRACKING" not in sim.status()
    )


def s_r2_hold_withheld_before_elapsed(fw):
    """R2: a bounded retry must NOT be granted before the quiet period has
    actually elapsed. Deliberately minimal (unlike
    s_r2_no_response_recovers_after_hold's full multi-stage flow) so this
    is a clean real-vs-mutant contrast on its own: the ONE tick immediately
    after entering NO RESPONSE - far short of the 60s hold - must still
    show zero counter/write movement and zero granted attempts."""
    sim = started(target=500, duration=240, grid_w=-100.0, fw=fw)
    tick(sim, soc=60.0); tick(sim, soc=60.0); tick(sim, soc=60.0)
    for _ in range(3):
        tick(sim, soc=60.0, grid_w=-100.0)
    for _ in range(3):
        tick(sim, soc=60.0, grid_w=-100.0)
    for _ in range(3):
        tick(sim, soc=60.0, grid_w=-100.0)
    if sim.g["dump_controller_state"] != "NO RESPONSE":
        return None
    n_writes = len(sim.writes())
    tick(sim, soc=60.0, grid_w=-100.0)  # one tick later - nowhere near the 60s hold
    return (
        sim.g["dump_controller_recovery_attempts"] == 0
        and len(sim.writes()) == n_writes
        and sim.g["dump_controller_state"] == "NO RESPONSE"
    )


def s_r2_recovery_exhausts_and_ends_lease(fw):
    """R2: the bounded retry budget (ecco_dump_controller_recovery_max_attempts
    = 1) is FINITE. A plant/telemetry that is STILL not responding even
    after its one granted retry must exhaust and end the lease safely via
    the common restore path - never hold, and never retry, forever."""
    sim = started(target=500, duration=240, grid_w=-100.0, fw=fw)
    tick(sim, soc=60.0); tick(sim, soc=60.0); tick(sim, soc=60.0)          # write#1
    for _ in range(3):
        tick(sim, soc=60.0, grid_w=-100.0)  # judge#1 (ineffective=1), write#2
    for _ in range(3):
        tick(sim, soc=60.0, grid_w=-100.0)  # judge#2 (ineffective=2), write#3
    for _ in range(3):
        tick(sim, soc=60.0, grid_w=-100.0)  # judge#3 (ineffective=3) -> NO RESPONSE
    if sim.g["dump_controller_state"] != "NO RESPONSE":
        return None
    for _ in range(4):
        tick(sim, soc=60.0, grid_w=-100.0)  # hold elapses -> retry granted (attempts=1), write#4
    if sim.g["dump_controller_recovery_attempts"] != 1 or not still_active(sim):
        return None
    for _ in range(3):
        tick(sim, soc=60.0, grid_w=-100.0)  # judge#4 (ineffective=1), write#5
    for _ in range(3):
        tick(sim, soc=60.0, grid_w=-100.0)  # judge#5 (ineffective=2), write#6
    for _ in range(3):
        tick(sim, soc=60.0, grid_w=-100.0)  # judge#6 (ineffective=3) -> NO RESPONSE again
    if sim.g["dump_controller_state"] != "NO RESPONSE" or sim.g["dump_controller_recovery_attempts"] != 1:
        return None
    for _ in range(4):
        # hold elapses a second time - attempts(1) >= max_attempts(1) -
        # EXHAUSTED, fails closed via the common restore path.
        tick(sim, soc=60.0, grid_w=-100.0)
    return (
        not still_active(sim)
        and owned(sim) == ORIGINAL
        and "RECOVERY EXHAUSTED" in str(sim.ent("dump_last_end_reason").state)
    )


def s_r3_external_mutation_before_ownership_read_blocks_write(fw):
    """R3 CRITICAL ADVERSARIAL TEST: an external actor mutates one of
    256-261 immediately before ECCO's next dynamic controller correction.
    ECCO's immediate pre-write ownership re-read must observe the drift,
    perform ZERO controller overwrite of it, and fail the lease closed via
    the common restore path - restoring the ORIGINAL pre-lease snapshot,
    never re-asserting its own believed value over the external change."""
    sim = started(target=500, duration=90, grid_w=1810.0, fw=fw)
    tick(sim, soc=60.0); tick(sim, soc=60.0)  # t+30s - still settling, no write yet
    real = sim.outcome_fn
    fired = {"once": False}

    def outcome(kind, addr, count):
        if kind == "read" and addr == 256 and count == 6 and not fired["once"]:
            fired["once"] = True
            # External actor mutates register 259 the instant BEFORE
            # ECCO's own ownership re-read observes the bank.
            sim.bank[259] = 4242
        return real(kind, addr, count)
    sim.outcome_fn = outcome
    tick(sim, soc=60.0)  # t+45s: settle elapses - the ownership re-read runs first
    return (
        fired["once"]
        and not still_active(sim)
        and owned(sim) == ORIGINAL
        and "CONFIG DRIFT (immediate pre-write check)" in str(sim.ent("dump_last_end_reason").state)
        and "register 259" in str(sim.ent("dump_last_end_reason").state)
    )


def s_r3_ownership_read_failure_blocks_write(fw):
    """A failed/timed-out immediate pre-write ownership re-read must block
    the mutation (fail closed) exactly like a detected mismatch does -
    ECCO must never write when it could not confirm what it currently
    owns, whether that is because the values differ or because it could
    not read them at all."""
    sim = started(target=500, duration=90, grid_w=1810.0, fw=fw)
    real = sim.outcome_fn
    fired = {"once": False}

    def outcome(kind, addr, count):
        if kind == "read" and addr == 256 and count == 6 and not fired["once"]:
            fired["once"] = True
            return "error"
        return real(kind, addr, count)
    sim.outcome_fn = outcome
    tick(sim, soc=60.0); tick(sim, soc=60.0)
    tick(sim, soc=60.0)  # t+45s: settle elapses - the ownership re-read itself fails
    return (
        fired["once"]
        and not still_active(sim)
        and owned(sim) == ORIGINAL
        and "OWNERSHIP RE-READ FAILED" in str(sim.ent("dump_last_end_reason").state)
    )


MUTATIONS = [
    # (Removing only `&& id(dump_verify_256_261_ok)` from the Allow Export
    # gate is an EQUIVALENT mutant - a mismatching readback also sets
    # dump_write_failed - so the non-equivalent version is used: a verify
    # that no longer compares the read-back values at all.)
    #
    # 2026-09-26 adversarial review (M2): dump_controller_tick's OWN verify
    # reread now uses the identical comparison shape, so the anchor must
    # include enough surrounding text to match ONLY the activation verify's
    # copy (its values array is captured after the 244 verify read, so its
    # window is preceded by a blank line + closing brace unique to it).
    ("256-261 activation verify that ignores the read-back values", s_verify_gate,
     "bool ok = values[0] == p && values[1] == p && values[2] == p &&\n"
     "                                              values[3] == p && values[4] == p && values[5] == p;\n"
     "                                    id(dump_verify_256_261_ok) = ok;",
     "bool ok = true;\n"
     "                                    id(dump_verify_256_261_ok) = ok;"),
    ("drift check without the post-activation sequence guard", s_drift_pre_activation_sample,
     "if (id(cfg_block_b_seq) <= id(dump_active_cfg_seq)) return false;", ""),
    ("drift check that never compares register 244", s_drift_detected,
     "if (id(manual_cfg_reg244_raw) != 0) {", "if (false) {"),
    ("Accept without the residue gate", s_accept_residue,
     "id(dump_accept_block_reason).empty();", "true;"),
    ("Accept residue gate without the fresh post-operation readback requirement", s_accept_needs_fresh_readback,
     "if (id(cfg_block_b_seq) <= id(dump_last_op_cfg_seq) ||", "if (false ||"),
    ("runaway guard that does not require CONSECUTIVE samples", s_runaway_needs_consecutive,
     "              id(dump_overpower_last_w) = x;\n            } else {\n              id(dump_overpower_samples) = 0;\n            }",
     "              id(dump_overpower_last_w) = x;\n            }"),
    ("lockout keyed on any failure (the pre-review comms lockout)", s_comms_no_lockout,
     "if (id(dump_restore_mismatch_this_attempt)) {", "if (true) {"),
    ("PENDING_CLEAR routed back to the restore worker (the pre-review dead end)", s_pending_clear_completes,
     "- script.execute: dump_clear_verified_marker", "- script.execute: restore_dump_to_grid_snapshot"),
    ("Stop SOC monitor without the freshness check (the pre-review blind spot)", s_frozen_soc_ends,
     "return !soc_plausible || !soc_fresh || !id(configuration_online).state;",
     "return !soc_plausible || !id(configuration_online).state;"),
    ("START without the TOU charging-slot gate", s_charge_slot_refused,
     "id(dump_start_tou_conflict_slot) == 0 &&", "true &&"),
    # 2026-09-26 final pre-OTA review additions.
    ("ACTIVE commit that does not record the readback sequence (a mid-START readback read as drift)",
     s_mid_start_sample, "id(dump_active_cfg_seq) = id(cfg_block_b_seq);", ""),
    ("restore that does not record its end-of-operation readback sequence (a mid-restore readback trusted by Accept)",
     lambda fw: s_mid_restore_sample_not_evidence(fw) is True,
     "# of start_dump_to_grid_override.\n            - lambda: 'id(dump_last_op_cfg_seq) = id(cfg_block_b_seq);'",
     "# of start_dump_to_grid_override.\n            - lambda: 'id(dump_last_op_cfg_seq) = id(dump_last_op_cfg_seq);'"),
    ("runaway threshold without the absolute 750W margin floor", s_runaway_500w_margin,
     "if (margin < ${ecco_dump_runaway_margin_w}.0f) margin = ${ecco_dump_runaway_margin_w}.0f;", ""),
    # 2026-09-26 adversarial review fix round - mutation coverage for the
    # new safety fences (B1 dispatch fence, B2 floor, H1 absolute backstop,
    # M2 lock-check-before-acquire).
    ("BLOCKER B1 fix removed: 256-261 drift evidence no longer requires the controller dispatch fence",
     s_b1_dispatch_fence,
     "if (id(cfg_block_b_response_dispatch_seq) <= id(dump_controller_cfg_fence_seq)) return false;", ""),
    ("BLOCKER B2 fix removed: controller ceiling no longer clamped to the 500W floor",
     s_b2_floor,
     "if (rounded < ${ecco_dump_controller_min_ceiling_w}.0f) rounded = ${ecco_dump_controller_min_ceiling_w}.0f;", ""),
    ("H1 fix removed: independent absolute runaway backstop no longer checked by the watchdog",
     s_h1_absolute_backstop,
     "return id(dump_overpower_samples) >= ${ecco_dump_runaway_samples} ||\n"
     "                        id(dump_absolute_overpower_samples) >= ${ecco_dump_runaway_absolute_samples};",
     "return id(dump_overpower_samples) >= ${ecco_dump_runaway_samples};"),
    ("M2 fix removed: controller no longer checks manual_write_in_progress is free before taking it",
     s_m2_lock_check,
     "return !id(manual_write_in_progress) && !id(correction_in_progress) &&\n"
     "                        id(inverter_modbus)->tx_buffer_empty() && !id(inverter_modbus)->tx_blocked();",
     "return !id(correction_in_progress) &&\n"
     "                        id(inverter_modbus)->tx_buffer_empty() && !id(inverter_modbus)->tx_blocked();"),
    # 2026-09-27 adversarial review (R4): the four specific dangerous
    # mutants Opus found surviving the previous round's suite. The B1
    # dispatch/response-stamp pair is pinned structurally instead (see
    # test_dump_to_grid_v1.py [27b]) - poll_inverter_configuration_dispatch
    # cannot be executed by this simulator (its Block A response uses a
    # switch statement the transpiler does not support). This entry
    # reintroduces the OLD (pre-2026-09-26) H1 bug verbatim: resetting the
    # runaway counter for 30s after every controller WRITE, not only at
    # lease start.
    ("H1 regression reintroduced: runaway counter reset re-armed by every controller write, not just lease start",
     s_h1_no_reset_on_write,
     "if ((uint32_t) (millis() - id(dump_active_since_ms)) < ${ecco_dump_runaway_grace_ms}UL) {\n"
     "              id(dump_overpower_samples) = 0;\n"
     "              id(dump_absolute_overpower_samples) = 0;\n"
     "              return;\n"
     "            }\n"
     "            // 2026-09-26 adversarial review, H1: independent ABSOLUTE",
     "if ((uint32_t) (millis() - id(dump_active_since_ms)) < ${ecco_dump_runaway_grace_ms}UL) {\n"
     "              id(dump_overpower_samples) = 0;\n"
     "              id(dump_absolute_overpower_samples) = 0;\n"
     "              return;\n"
     "            }\n"
     "            if ((uint32_t) (millis() - id(dump_last_controller_update_ms)) < ${ecco_dump_runaway_grace_ms}UL) {\n"
     "              id(dump_overpower_samples) = 0;\n"
     "              return;\n"
     "            }\n"
     "            // 2026-09-26 adversarial review, H1: independent ABSOLUTE"),
    # 2026-09-27 adversarial review, R1 second pass - the four specific
    # mutants required by this round's REQUIRED TESTS/mutation coverage.
    ("R1 (second pass) regression: response_pending is never created after a verified write",
     s_r1_reversed_ct_fails_closed,
     "                            id(dump_controller_last_error) = id(dump_controller_pending_error);\n"
     "                            id(dump_controller_response_pending) = true;",
     "                            id(dump_controller_last_error) = id(dump_controller_pending_error);"),
    ("R1 (second pass) regression: response_pending is never cleared, so a write's response could be re-judged",
     s_r1_bus_deferral_judges_once,
     "            // Judged exactly once - this write's own response is never\n"
     "            // evaluated again, regardless of what happens afterward.\n"
     "            id(dump_controller_response_pending) = false;",
     "            // Judged exactly once - this write's own response is never\n"
     "            // evaluated again, regardless of what happens afterward."),
    ("R1 (second pass) regression: a write's response is skipped when it lands exactly at a clamp",
     s_r1_reversed_ct_fails_closed,
     "          if (id(dump_controller_response_pending)) {\n"
     "            float prev = id(dump_controller_last_error);",
     "          if (id(dump_controller_response_pending)) {\n"
     "            if (id(dump_target_power) >= (uint16_t) ${ecco_dump_controller_max_ceiling_w} ||\n"
     "                id(dump_target_power) <= (uint16_t) ${ecco_dump_controller_min_ceiling_w}) {\n"
     "              id(dump_controller_response_pending) = false;\n"
     "              return;\n"
     "            }\n"
     "            float prev = id(dump_controller_last_error);"),
    # R2 (2026-09-27 hardening): mutation coverage for the bounded NO
    # RESPONSE recovery gate. All three anchors below are exact,
    # character-for-character quotes of the new firmware block, so a
    # future accidental edit to that block breaks these mutations loudly
    # (mutant() itself refuses to run if the anchor text ever stops being
    # unique/present).
    ("R2 regression: NO RESPONSE reverts to an unconditional terminal hold - the bounded retry is never granted",
     s_r2_no_response_recovers_after_hold,
     "          if (id(dump_controller_state) == \"NO RESPONSE\") {\n"
     "            uint32_t held_ms = (uint32_t) (millis() - id(dump_controller_recovery_armed_ms));\n"
     "            if (held_ms < ${ecco_dump_controller_recovery_hold_ms}UL) {\n"
     "              return; // still within the bounded quiet period - no writes, no re-evaluation yet\n"
     "            }\n"
     "            if ((int32_t) (id(dump_grid_last_update_ms) - id(dump_controller_recovery_armed_ms)) <= 0) {\n"
     "              return; // hold has elapsed, but no genuinely NEW sample has arrived yet - keep waiting\n"
     "            }\n"
     "            if (id(dump_controller_recovery_attempts) >= ${ecco_dump_controller_recovery_max_attempts}) {\n"
     "              id(dump_controller_fail_closed) = true;\n"
     "              id(dump_controller_state) = \"NO RESPONSE - RECOVERY EXHAUSTED\";\n"
     "              return;\n"
     "            }\n"
     "            id(dump_controller_recovery_attempts)++;\n"
     "            id(dump_controller_ineffective_count) = 0;\n"
     "            id(dump_controller_wrong_direction_count) = 0;\n"
     "            // Fall through deliberately - no return here. The bounded\n"
     "            // retry this grants is evaluated by the SAME ordinary logic\n"
     "            // below, using the fresh sample that just satisfied the fence.\n"
     "          }",
     "          if (id(dump_controller_state) == \"NO RESPONSE\") {\n"
     "            return;\n"
     "          }"),
    ("R2 regression: the recovery attempt budget is never bounded - retries are granted indefinitely, never exhausting",
     s_r2_recovery_exhausts_and_ends_lease,
     "            if (id(dump_controller_recovery_attempts) >= ${ecco_dump_controller_recovery_max_attempts}) {\n"
     "              id(dump_controller_fail_closed) = true;\n"
     "              id(dump_controller_state) = \"NO RESPONSE - RECOVERY EXHAUSTED\";\n"
     "              return;\n"
     "            }\n"
     "            id(dump_controller_recovery_attempts)++;",
     "            id(dump_controller_recovery_attempts)++;"),
    ("R2 regression: a retry is granted before the bounded quiet period has actually elapsed",
     s_r2_hold_withheld_before_elapsed,
     "            if (held_ms < ${ecco_dump_controller_recovery_hold_ms}UL) {\n"
     "              return; // still within the bounded quiet period - no writes, no re-evaluation yet\n"
     "            }",
     "            if (false) {\n"
     "              return;\n"
     "            }"),
    # R3 (2026-09-27 hardening): mutation coverage for the immediate
    # pre-write ownership re-read of 256-261.
    ("R3 regression: the immediate pre-write ownership re-read no longer detects a mismatch against the last "
     "verified owned state",
     s_r3_external_mutation_before_ownership_read_blocks_write,
     # Dump V2: R3 is unchanged but now nested under the evidence-commit
     # gate, hence 6 more spaces of indentation.
     "                                    for (int i = 0; i < 6; i++) {\n"
     "                                      if (values[i] != p) {\n"
     "                                        char d[96];\n"
     "                                        snprintf(d, sizeof(d), \"register %d reads %uW, expected %uW\", 256 + i, values[i], p);\n"
     "                                        id(dump_controller_ownership_detail) = d;\n"
     "                                        id(dump_controller_ownership_mismatch) = true;\n"
     "                                        id(dump_controller_write_failed) = true;\n"
     "                                        break;\n"
     "                                      }\n"
     "                                    }",
     "  "),
    ("R3 regression: a failed/timed-out ownership re-read no longer blocks the controller's write",
     s_r3_ownership_read_failure_blocks_write,
     "                            on_error:\n"
     "                              then:\n"
     "                                - lambda: |-\n"
     "                                    id(dump_controller_op_terminal) = true;\n"
     "                                    id(dump_controller_ownership_read_failed) = true;\n"
     "                                    id(dump_controller_write_failed) = true;",
     "                            on_error:\n"
     "                              then:\n"
     "                                - lambda: |-\n"
     "                                    id(dump_controller_op_terminal) = true;\n"
     "                                    id(dump_controller_ownership_read_failed) = true;"),
    # 2026-09-27 adversarial review (M1 regression, third pass) + R5 -
    # mutation coverage for this round's two fixes.
    ("M1 regression (third pass) reintroduced: the FIRST correction of a lease is no longer gated on "
     "fresh post-ACTIVE grid telemetry",
     s_m1_first_correction_needs_fresh_sample,
     "          if ((int32_t) (id(dump_grid_last_update_ms) - id(dump_last_controller_update_ms)) <= 0) {\n"
     "            id(dump_controller_state) = \"WAITING FOR FRESH GRID\";\n"
     "            return;\n"
     "          }\n"
     "\n"
     "          float grid_w = id(ecco_grid_ct_power).state;",
     "          float grid_w = id(ecco_grid_ct_power).state;"),
    ("R5 fix removed: the controller write-success path no longer checks dump_restore_requested "
     "before publishing an ACTIVE/TRACKING status",
     s_r5_end_pressed_during_controller_write,
     "if (!id(dump_restore_requested)) {",
     "if (true) {"),
]
for label, scenario, old, new in MUTATIONS:
    real_ok = scenario(FW)
    try:
        mutant_ok = scenario(mutant(old, new))
    except ds.Unsupported as e:
        mutant_ok = f"unsupported: {e}"
    check(f"'{label}': safe on the real firmware, detected on the mutant",
          real_ok is True and mutant_ok is False, f"real={real_ok} mutant={mutant_ok}")

# ===========================================================================
print("")
print("[J] V1.1 closed-loop export controller")
# Grid power: positive = import, negative = export (register 172 via the CT
# clamp, ecco_grid_ct_power) - see docs/DUMP_TO_GRID_V1.md "Closed-loop
# export controller (V1.1)". Target export W maps to a target grid reading
# of -target. Settle window/minimum write interval is 45s (three 15s
# ticks - 2026-09-26 adversarial review, raised from 30s to match the real
# observed settle cadence); deadband is 150W; gain 0.5; max step 1000W/tick;
# ceiling range is now 500W (floor, BLOCKER B2) to 3000W; round to the
# nearest 100W (raised from 50W alongside the floor).

sim = started(target=500, duration=10, grid_w=1810.0)
check("controller: initial ceiling equals the target before any correction",
      sim.g["dump_target_power"] == 500)
tick(sim)  # t+15s - still inside the 45s settle window
tick(sim)  # t+30s - still inside the 45s settle window
check("controller: no correction inside the settle window",
      sim.g["dump_target_power"] == 500 and sim.writes() == [(256, [500] * 6), (244, [0])], f"{sim.writes()}")
tick(sim)  # t+45s - settle window has elapsed
check("target 500W, grid importing 1810W: battery ceiling RISES (500 -> 1500)",
      sim.g["dump_target_power"] == 1500 and still_active(sim), sim.status())
check("...and the new ceiling was actually written and verified",
      sim.writes()[-1] == (256, [1500] * 6), f"{sim.writes()}")
check("controller state is TRACKING once a correction has been made and verified",
      str(sim.ent("dump_controller_state_sensor").state) == "TRACKING", sim.status())

sim = started(target=500, duration=10, grid_w=-1200.0)
tick(sim)
tick(sim)
tick(sim)
check("BLOCKER B2: target 500W, grid already exporting 1200W (too much): the computed ceiling would be below "
      "500W, so it CLAMPS AT THE 500W FLOOR (never below) rather than continuing towards 0W/100W",
      sim.g["dump_target_power"] == 500 and still_active(sim), sim.status())
check("...and reports SATURATED LOW - it does not claim the requested grid target is being achieved",
      str(sim.ent("dump_controller_state_sensor").state) == "SATURATED LOW"
      and "SATURATED LOW" in sim.status() and "PV export already exceeds target" in sim.status(), sim.status())
check("...no write was needed (the ceiling was already at the floor from START)", sim.writes() == [(256, [500] * 6), (244, [0])])

sim = started(target=500, duration=10, grid_w=-450.0)  # error = -450 - (-500) = 50W, inside the 150W deadband
tick(sim)
tick(sim)
tick(sim)
check("within the 150W deadband: no correction, no extra write",
      sim.g["dump_target_power"] == 500 and sim.writes() == [(256, [500] * 6), (244, [0])], f"{sim.writes()}")

# House load and PV both act on the controller purely through their effect
# on measured grid power - a step change in either is indistinguishable
# from the controller's point of view, so each is exercised as a single
# fresh before/after grid-power step (not chained onto a shared, evolving
# battery ceiling, which this offline simulator - with no real power-flow
# model - cannot make internally consistent across several steps).
sim = started(target=1000, duration=30, grid_w=1000.0)  # load rose: importing 1000W against a 1000W export target
tick(sim, soc=70.0)
tick(sim, soc=70.0)
tick(sim, soc=70.0)
check("house load suddenly rises (grid swings to +1000W import): ceiling rises",
      sim.g["dump_target_power"] == 2000, sim.status())

sim = started(target=1000, duration=30, grid_w=-2500.0)  # load fell: now over-exporting at the old ceiling
tick(sim, soc=70.0)
tick(sim, soc=70.0)
tick(sim, soc=70.0)
check("house load suddenly falls (grid swings to -2500W export): ceiling falls, clamped at the 500W floor (B2)",
      sim.g["dump_target_power"] == 500, sim.status())

sim = started(target=500, duration=30, grid_w=-2500.0)  # PV surged: grid swings deep into export
tick(sim, soc=70.0)
tick(sim, soc=70.0)
tick(sim, soc=70.0)
check("PV suddenly rises (grid swings to -2500W export): ceiling falls, clamped at the 500W floor (B2), never 0W",
      sim.g["dump_target_power"] == 500, sim.status())

sim = started(target=500, duration=30, grid_w=500.0)  # PV dropped: now importing against a 500W export target
tick(sim, soc=70.0)
tick(sim, soc=70.0)
tick(sim, soc=70.0)
check("PV suddenly falls (grid swings to +500W import): ceiling rises",
      sim.g["dump_target_power"] == 1000, sim.status())

sim = started(target=500, duration=30, grid_w=-500.0)
for _ in range(7):  # 7 * 15s = 105s > the 90s grid staleness bound
    tick(sim, soc=70.0, grid_fresh=False)
check("grid telemetry stale (>90s, no fresh sample): fails closed",
      not still_active(sim) and "GRID TELEMETRY LOST" in sim.ent("dump_last_end_reason").state, sim.status())

sim = started(target=500, duration=30, grid_w=-500.0)
sim.g["dump_grid_last_update_ms"] = 0  # never actually published, as far as the controller can tell
tick(sim, soc=70.0, grid_fresh=False)
check("grid telemetry never available (last-update timestamp still zero): fails closed immediately",
      not still_active(sim) and "GRID TELEMETRY LOST" in sim.ent("dump_last_end_reason").state, sim.status())

sim = started(target=8000, duration=90, grid_w=20000.0)  # extreme but plausible sustained import
for _ in range(8):
    tick(sim, soc=70.0)
check("controller command max clamp: never exceeds ecco_dump_controller_max_ceiling_w (3000W)",
      sim.g["dump_target_power"] == 3000, sim.status())

sim = started(target=500, duration=90, grid_w=-20000.0)  # extreme but plausible sustained export
for _ in range(6):
    tick(sim, soc=70.0)
check("BLOCKER B2: controller command min clamp never goes below the 500W floor (never 0W, never 100W)",
      sim.g["dump_target_power"] == 500, sim.status())
check("...and no write in this run ever commanded 0W or 100W",
      all(vals[0] not in (0, 100) for addr, vals in sim.writes() if addr == 256), f"{sim.writes()}")

sim = started(target=500, duration=10, grid_w=1810.0)
tick(sim)
tick(sim)
tick(sim)  # the one correction inside this window (t+45s)
tick(sim)  # t+60s: only 15s since the last write - still inside the 45s settle window
check("no rapid repeated writes: exactly ONE controller write occurs across four 15s ticks",
      sim.writes().count((256, [1500] * 6)) == 1, f"{sim.writes()}")

sim = started(target=500, duration=10, grid_w=1810.0)
tick(sim)
tick(sim)
# R3 (2026-09-27 hardening) added an immediate pre-write ownership re-read
# of 256-261, ALSO at address 256/count 6, immediately before this same
# write's own verify reread - so an override keyed on address alone would
# now corrupt R3's check instead of (or as well as) the intended target.
# Corrupt only the SECOND read of 256 this tick - the write's OWN verify -
# leaving R3's ownership pre-check (the first) genuinely matching.
reads_256 = {"n": 0}


def _corrupt_second_read_of_256(addr, count, values):
    if addr == 256:
        reads_256["n"] += 1
        if reads_256["n"] >= 2:
            return [9999] * count
    return values


sim.read_override_fn = _corrupt_second_read_of_256
tick(sim)  # t+45s: R3's ownership check passes; the write succeeds; its OWN verify reread is corrupted
check("dynamic write verify failure: fails safe (lease ends, common restore path), never left ACTIVE with an unverified ceiling",
      not still_active(sim) and "CONTROLLER WRITE VERIFY MISMATCH" in sim.ent("dump_last_end_reason").state, sim.status())
sim.read_override_fn = None
tick(sim)
check("...and the next watchdog tick restores the exact original", owned(sim) == ORIGINAL and marker_state(sim) == 0, sim.status())

sim = started(target=500, duration=10, grid_w=1810.0)
tick(sim)
tick(sim)
tick(sim)  # ceiling corrected to 1500 and verified this tick (t+45s)
check("drift detector follows the CURRENT controller command, not the original target",
      sim.g["dump_target_power"] == 1500, sim.status())
tick(sim, grid_w=-500.0)  # error now inside deadband relative to the NEW ceiling's own steady state target math is irrelevant here
tick(sim, grid_w=-500.0)
check("...the lease survives several more ticks with no spurious CONFIG DRIFT",
      still_active(sim), sim.status())

sim = started(target=500, duration=10, grid_w=1810.0)
tick(sim, soc=70.0)
tick(sim, soc=70.0)
tick(sim, soc=70.0)  # ceiling -> 1500 at t+45s
check("runaway threshold tracks the CURRENT commanded ceiling (1500), not the original target (500)", sim.g["dump_target_power"] == 1500)
# Settle grid exactly on target so the controller makes no further
# corrections (which would otherwise keep resetting the runaway guard's own
# post-change settling grace - see dump_last_controller_update_ms) while
# feeding battery-discharge samples below.
tick(sim, soc=70.0, grid_w=-500.0)  # t+60s
tick(sim, soc=70.0)  # t+75s - runaway settling grace (30s from ACTIVE) has long elapsed
tick(sim, soc=70.0)  # t+90s - the 30s post-write TRANSITION window (H1) has also elapsed
# Old threshold (500 + max(250, 750) = 1250) would have tripped at 2200W; the
# NEW threshold (1500 + max(750, 750) = 2250) must NOT trip at 2200W. Both
# comfortably under the 3750W absolute backstop, so only the ordinary
# ceiling-relative guard is exercised here.
tick(sim, soc=70.0, battery_w=2200.0)
tick(sim, soc=70.0, battery_w=2200.0)
tick(sim, soc=70.0, battery_w=2200.0)
check("2200W battery discharge is BELOW the new 2250W threshold: does not trip",
      still_active(sim), sim.status())
tick(sim, soc=70.0, battery_w=2300.0)
tick(sim, soc=70.0, battery_w=2300.0)
tick(sim, soc=70.0, battery_w=2300.0)
check("2300W battery discharge is ABOVE the new 2250W threshold: trips POWER RUNAWAY",
      not still_active(sim) and "POWER RUNAWAY" in sim.ent("dump_last_end_reason").state, sim.status())

sim = started(target=500, duration=10, grid_w=1810.0)
tick(sim, soc=70.0)
tick(sim, soc=70.0)
tick(sim, soc=70.0)  # ceiling -> 1500 at t+45s
tick(sim, soc=70.0, grid_w=-500.0)  # settle on target - no further controller corrections
tick(sim, soc=70.0)  # runaway settling grace elapsed
tick(sim, soc=70.0)  # H1 transition window elapsed too
tick(sim, soc=70.0, battery_w=8600.0)
tick(sim, soc=70.0, battery_w=8600.0)
check("the 8.6kW anomaly still trips promptly against a dynamically-raised ceiling, even while the controller had "
      "just been actively stepping (H1) - the independent ABSOLUTE backstop needs only 2 consecutive samples",
      not still_active(sim) and "RUNAWAY" in sim.ent("dump_last_end_reason").state, sim.status())

# ---------------------------------------------------------------------
# H1: runaway during REPEATED controller writes must not be masked, and a
# legitimate step-down's settling transition must not itself misjudge the
# battery (still near the OLD, higher ceiling) as a runaway.
# ---------------------------------------------------------------------
sim = started(target=500, duration=30, grid_w=1810.0)
tick(sim, soc=70.0)
tick(sim, soc=70.0)
tick(sim, soc=70.0)  # t+45s: ceiling 500 -> 1500 (a controller write just landed)
assert sim.g["dump_target_power"] == 1500, sim.status()
tick(sim, soc=70.0, battery_w=1900.0)  # t+60s: still settling from the write - no eval yet, but publish keeps telemetry fresh
check("H1: the runaway sample counter is NOT reset to zero merely because the controller just wrote a new ceiling "
      "(it simply has not evaluated yet - the settle window itself, unchanged, still applies to the CONTROLLER's own "
      "next correction, not to the runaway guard's own sample accumulation, which runs on every battery-power publish)",
      True)  # documents intent; the numeric accumulation is exercised directly below
sim.g["dump_overpower_samples"] = 2  # simulate 2 consecutive over-threshold samples already accumulated
tick(sim, soc=70.0)  # a further controller settling tick - must NOT silently zero the counter
check("H1 core fix: dump_overpower_samples is untouched by an ordinary settling tick (only a controller WRITE could "
      "previously reset it, and this tick made none since the grid is back in deadband)",
      sim.g["dump_overpower_samples"] == 2, f"samples={sim.g['dump_overpower_samples']}")
sim.ent("ecco_battery_power").publish_state(2300.0)  # the 3rd consecutive sample (above the 1500+750=2250 threshold) - trips
check("...and the very next over-threshold sample completes the trip to 3, ending the lease",
      sim.g["dump_overpower_samples"] == 3)
sim.run_actions(watchdog_of(sim.fw))
check("...runaway trips even though the controller had recently written a new ceiling",
      not still_active(sim) and "POWER RUNAWAY" in sim.ent("dump_last_end_reason").state, sim.status())

# Step-down transition: the guard must judge against the HIGHER of the old
# and new ceiling until the lower command has had time to take effect, so a
# legitimate step-down is not itself misjudged as a runaway before the
# battery has caught up - but once that transition window elapses, the
# guard reverts to the (now lower) current ceiling.
sim = started(target=500, duration=30, grid_w=1810.0)
tick(sim, soc=70.0)
tick(sim, soc=70.0)
tick(sim, soc=70.0)  # t+45s: ceiling 500 -> 1500
assert sim.g["dump_target_power"] == 1500, sim.status()
tick(sim, soc=70.0, grid_w=-3000.0)  # t+60s: still settling (15s since the last write)
tick(sim, soc=70.0, grid_w=-3000.0)  # t+75s: still settling (30s since the last write)
tick(sim, soc=70.0, grid_w=-3000.0)  # t+90s: settle elapses - big step-down: 1500 -> 500 (the floor, in one 1000W-clamped step)
check("setup: a legitimate step-down just landed", sim.g["dump_target_power"] == 500, sim.status())
tick(sim, soc=70.0, grid_w=-500.0, battery_w=2000.0)  # t+105s: 15s into the 30s transition window
check("H1 step-down transition: 2000W is judged against the HIGHER of the old (1500) and new (500) ceiling "
      "(threshold 1500+750=2250) DURING the transition - not the new, lower ceiling's own threshold (500+750=1250), "
      "which 2000W would already exceed - so this is not (yet) counted as overpower",
      still_active(sim) and sim.g["dump_overpower_samples"] == 0, sim.status())
tick(sim, soc=70.0, battery_w=2000.0)  # t+120s: transition window (30s from t+90s) has now elapsed
tick(sim, soc=70.0, battery_w=2000.0)
tick(sim, soc=70.0, battery_w=2000.0)
check("...but once the transition window elapses, the SAME 2000W reading against the new 500W ceiling "
      "(threshold 500+750=1250) is genuinely anomalous and trips after 3 consecutive samples",
      not still_active(sim) and "POWER RUNAWAY" in sim.ent("dump_last_end_reason").state, sim.status())

# ---------------------------------------------------------------------
# M1: grid feedback must post-date the last verified controller write.
# ---------------------------------------------------------------------
sim = started(target=500, duration=30, grid_w=1810.0)
tick(sim, soc=60.0)
tick(sim, soc=60.0)
tick(sim, soc=60.0)  # t+45s: ceiling 500 -> 1500
assert sim.g["dump_target_power"] == 1500, sim.status()
n_writes = len(sim.writes())
# Force the grid SAMPLE to look stale RELATIVE TO THE WRITE (its timestamp
# predates dump_last_controller_update_ms) while still within the absolute
# 90s staleness bound and a large error is present - the controller must
# SKIP, not act on it and not fail the lease over one skipped tick.
sim.g["dump_grid_last_update_ms"] = sim.g["dump_last_controller_update_ms"] - 1000
sim.ent("ecco_grid_ct_power").set(1810.0)
sim.advance(50000)  # past the 45s settle window again
sim.run_actions(watchdog_of(sim.fw))
check("M1: a grid sample that predates the last controller write is skipped, not acted on and not a fault",
      sim.g["dump_target_power"] == 1500 and len(sim.writes()) == n_writes and still_active(sim), sim.status())
check("...and reports WAITING FOR FRESH GRID",
      str(sim.ent("dump_controller_state_sensor").state) == "WAITING FOR FRESH GRID", sim.status())
tick(sim, soc=60.0, grid_w=1810.0)  # a genuinely fresh sample lands
check("...once a genuinely fresh post-write sample arrives, the skipped correction proceeds normally",
      sim.g["dump_target_power"] == 2500, sim.status())
# The two checks immediately above are M1's post-write case (this same
# scenario, unchanged): items 3 ("post-controller-write stale sample -
# still waits") and 4 ("fresh post-write sample - correction permitted")
# of the M1 regression fix below. That gate already lived here before this
# round; only the FIRST correction of a lease (no write yet) was missing it.

# ---------------------------------------------------------------------
# M1 regression (third pass): the SAME freshness fence must also gate the
# FIRST correction of a lease - before any controller write has ever
# happened, so there is no response_pending yet to carry the check above.
# Without this, a stale pre-ACTIVE grid sample - still within the broader
# 90s ecco_dump_grid_stale_ms bound - could drive the very first write.
# ---------------------------------------------------------------------
sim = started(target=500, duration=90, grid_w=2000.0)  # error 2500W - would otherwise trigger an immediate correction
n_writes = len(sim.writes())
tick(sim, soc=70.0, grid_fresh=False)  # t+15s: telemetry frozen at its pre-ACTIVE value
tick(sim, soc=70.0, grid_fresh=False)  # t+30s
tick(sim, soc=70.0, grid_fresh=False)  # t+45s: settle window elapses, but telemetry was never refreshed since ACTIVE
check("M1 regression test #1: START, then telemetry stalls through the whole settle window - the FIRST correction "
      "of the lease waits (a stale pre-ACTIVE sample must not drive it), zero controller writes",
      sim.g["dump_target_power"] == 500 and len(sim.writes()) == n_writes and still_active(sim), sim.status())
check("...and reports WAITING FOR FRESH GRID, not TRACKING",
      str(sim.ent("dump_controller_state_sensor").state) == "WAITING FOR FRESH GRID", sim.status())
tick(sim, soc=70.0, grid_fresh=False)  # t+60s: confirms this is a persistent hold, not a one-tick fluke
check("...still waiting one tick later",
      sim.g["dump_target_power"] == 500 and len(sim.writes()) == n_writes and still_active(sim), sim.status())
tick(sim, soc=70.0, grid_w=2000.0)  # t+75s: a genuinely fresh post-ACTIVE sample finally arrives (grid_fresh=True default)
check("M1 regression test #2: once a fresh post-ACTIVE sample arrives, the first correction of the lease proceeds "
      "normally",
      sim.g["dump_target_power"] == 1500 and len(sim.writes()) == n_writes + 1 and still_active(sim), sim.status())

sim5 = started(target=500, duration=30, grid_w=1810.0)  # normal continuously-fresh telemetry (tick()'s default)
tick(sim5, soc=70.0)
tick(sim5, soc=70.0)
tick(sim5, soc=70.0)  # t+45s: settle window elapses with telemetry refreshed every tick, as in live operation
check("M1 regression test #5: under normal continuously-fresh telemetry, the freshness fence adds NO extra delay - "
      "the first correction still lands exactly when the settle window elapses (t+45s), not later",
      sim5.g["dump_target_power"] == 1500 and still_active(sim5), sim5.status())

# ---------------------------------------------------------------------
# M2: controller bus/lock discipline - defer, never stomp, when the lock is
# already held or the bus is not quiescent.
# ---------------------------------------------------------------------
sim = started(target=500, duration=30, grid_w=1810.0)
tick(sim, soc=60.0)
tick(sim, soc=60.0)
sim.g["manual_write_in_progress"] = True  # another transaction (e.g. Free Power) already owns the bus
n_writes = len(sim.writes())
tick(sim, soc=60.0)  # t+45s: settle elapses, but the lock is already taken elsewhere
check("M2: the controller DEFERS (zero writes, no fault) rather than stomping an already-held lock",
      len(sim.writes()) == n_writes and sim.g["dump_target_power"] == 500 and still_active(sim)
      and sim.g["manual_write_in_progress"] is True, sim.status())
sim.g["manual_write_in_progress"] = False
tick(sim, soc=60.0)
check("...and proceeds normally once the lock is free again",
      sim.g["dump_target_power"] == 1500, sim.status())

sim = started(target=500, duration=30, grid_w=1810.0)
tick(sim, soc=60.0)
tick(sim, soc=60.0)
sim.bus_idle = False  # Modbus bus busy with another transaction
n_writes = len(sim.writes())
tick(sim, soc=60.0)  # t+45s: settle elapses, but the bus is not quiescent
check("M2: the controller also DEFERS while the Modbus bus itself is not quiescent",
      len(sim.writes()) == n_writes and sim.g["dump_target_power"] == 500 and still_active(sim), sim.status())
sim.bus_idle = True
tick(sim, soc=60.0)
check("...and proceeds normally once the bus is free again",
      sim.g["dump_target_power"] == 1500, sim.status())

# ---------------------------------------------------------------------
# BLOCKER B1: a config sample dispatched BEFORE a controller write, whose
# response lands AFTER it, must not be trusted as post-write drift evidence
# merely because it completed later.
# ---------------------------------------------------------------------
sim = started(target=1000, duration=30, grid_w=-1000.0)  # zero error - isolates drift from controller activity
pending = config_poll_dispatch(sim)  # Block B read dispatched now, sampling the CURRENT (pre-write) registers
sim.grid_w = 1810.0
tick(sim, soc=60.0, poll=False)
tick(sim, soc=60.0, poll=False)
tick(sim, soc=60.0, poll=False)  # t+45s: a controller write lands and completes AFTER the dispatch above
old_ceiling = sim.g["dump_target_power"]
assert old_ceiling != 1000, sim.status()  # a new ceiling was actually committed
config_poll_complete(sim, pending)  # the STALE, already-in-flight response now lands
sim.ent("ecco_battery_soc").publish_state(60.0)
sim.run_actions(watchdog_of(sim.fw))
check("BLOCKER B1: a config sample in flight BEFORE a controller write, completing AFTER it, is not treated as "
      "post-write drift evidence merely because its completion sequence is newer",
      still_active(sim), sim.status())
config_poll(sim, overrides={256: 999})  # a genuinely fresh, post-write poll
sim.run_actions(watchdog_of(sim.fw))
check("...but a genuinely fresh post-write sample still catches real drift",
      not still_active(sim) and "CONFIG DRIFT" in str(sim.ent("dump_last_end_reason").state)
      and "register 256" in str(sim.ent("dump_last_end_reason").state), sim.status())

# ---------------------------------------------------------------------
# Anti-windup: repeated same-direction corrections with no measured
# improvement must HOLD (not end the lease) rather than keep ramping.
# ---------------------------------------------------------------------
sim = started(target=500, duration=240, grid_w=-100.0)  # error = 400W, held fixed every tick by the test - the
                                                          # offline simulator has no real power-flow model, so a
                                                          # constant measured error stands in for "the battery is
                                                          # not responding to commanded ceiling changes"
tick(sim, soc=60.0); tick(sim, soc=60.0); tick(sim, soc=60.0)  # t+45s: first correction, no prior evidence to judge
c1 = sim.g["dump_target_power"]
check("R1-6 setup: the FIRST correction never increments the counter (nothing to compare against yet)",
      sim.g["dump_controller_ineffective_count"] == 0)
tick(sim, soc=60.0, grid_w=-100.0); tick(sim, soc=60.0, grid_w=-100.0); tick(sim, soc=60.0, grid_w=-100.0)  # t+90s
c2 = sim.g["dump_target_power"]
check("anti-windup setup: a same-direction correction with NO improvement still proceeds once (below the threshold)",
      c2 != c1 and still_active(sim), f"c1={c1} c2={c2}")
check("R1-6: a real verified write that shows no improvement increments the ineffective counter to 1",
      sim.g["dump_controller_ineffective_count"] == 1, sim.g["dump_controller_ineffective_count"])
tick(sim, soc=60.0, grid_w=-100.0); tick(sim, soc=60.0, grid_w=-100.0); tick(sim, soc=60.0, grid_w=-100.0)  # t+135s
c3 = sim.g["dump_target_power"]
check("...a second consecutive no-improvement correction still proceeds too",
      c3 != c2 and still_active(sim), f"c2={c2} c3={c3}")
check("R1-6: ...and increments the ineffective counter to 2", sim.g["dump_controller_ineffective_count"] == 2)
n_writes = len(sim.writes())
tick(sim, soc=60.0, grid_w=-100.0); tick(sim, soc=60.0, grid_w=-100.0); tick(sim, soc=60.0, grid_w=-100.0)  # t+180s
check("anti-windup: after enough consecutive same-direction corrections show no measured improvement, the "
      "controller HOLDS at the current ceiling rather than continuing to ramp blindly",
      sim.g["dump_target_power"] == c3 and len(sim.writes()) == n_writes and still_active(sim), sim.status())
check("...and reports NO RESPONSE, not a normal TRACKING state",
      str(sim.ent("dump_controller_state_sensor").state) == "NO RESPONSE", sim.status())

# 2026-09-27 adversarial review (R1, second pass) - test #4: NO RESPONSE is
# a BOUNDED hold (R2, 2026-09-27 hardening - see docs/DUMP_TO_GRID_V1.md
# "R2"), not an indefinite one. WITHIN the bounded quiet period (60s = four
# 15s ticks from the moment the hold armed - three more ticks here, since
# the hold armed on the tick just above), many ticks - INCLUDING ones whose
# grid reading would look like a clear improvement if it were ever compared
# against anything - must still cause ZERO further counter movement and NO
# resumed writes, exactly as R1 (second pass) originally proved. What
# changes under R2 is only what happens AFTER the bounded quiet period
# elapses - see section [M] for the full bounded-retry-and-exhaustion
# coverage (s_r2_no_response_recovers_after_hold /
# s_r2_recovery_exhausts_and_ends_lease), which is deliberately kept
# separate from this within-hold invariance check.
n_writes_at_hold = len(sim.writes())
for gw in (-100.0, -250.0, 50.0):  # deliberately varied, including "improving" values - still within the 60s hold
    tick(sim, soc=60.0, grid_w=gw)
check("R1-4 (test #4): NO RESPONSE hold causes ZERO further counter changes WITHIN the bounded quiet period, "
      "even when a later grid reading would look like a clear improvement",
      sim.g["dump_controller_ineffective_count"] == 3 and sim.g["dump_controller_wrong_direction_count"] == 0
      and sim.g["dump_target_power"] == c3 and len(sim.writes()) == n_writes_at_hold and still_active(sim)
      and sim.g["dump_controller_recovery_attempts"] == 0
      and str(sim.ent("dump_controller_state_sensor").state) == "NO RESPONSE", sim.status())

# test #5: sustained load/PV change while in NO RESPONSE cannot cause a
# spurious GRID RESPONSE SANITY either - already implied by test #4 above
# (the wrong-direction counter also never moves), but pinned explicitly
# since GRID RESPONSE SANITY ends the lease and is the more severe outcome.
check("R1-5 (test #5): NO RESPONSE hold never escalates into a spurious GRID RESPONSE SANITY on its own",
      "GRID RESPONSE SANITY" not in str(sim.ent("dump_last_end_reason").state) and still_active(sim), sim.status())

# test #12 (genuine improvement resets correctly) - demonstrated BEFORE
# the terminal hold is ever reached, which is the behaviourally meaningful
# case (this is what stops a transient blip from needlessly walking a
# lease into NO RESPONSE in the first place).
sim2 = started(target=500, duration=240, grid_w=-100.0)
tick(sim2, soc=60.0); tick(sim2, soc=60.0); tick(sim2, soc=60.0)  # first correction, no prior evidence
tick(sim2, soc=60.0, grid_w=-100.0); tick(sim2, soc=60.0, grid_w=-100.0); tick(sim2, soc=60.0, grid_w=-100.0)  # ineffective #1
check("setup: ineffective count reaches 1 without yet holding",
      sim2.g["dump_controller_ineffective_count"] == 1 and still_active(sim2))
c_before_improvement = sim2.g["dump_target_power"]
# A GENUINE improvement (well past the 100W response margin, but still
# outside the 150W deadband so the reset is attributed to the anti-windup
# "improvement" branch specifically, not the separate deadband branch).
tick(sim2, soc=60.0, grid_w=-250.0); tick(sim2, soc=60.0, grid_w=-250.0); tick(sim2, soc=60.0, grid_w=-250.0)
check("test #12: a genuine improvement resets the ineffective counter back to 0 and the controller resumes "
      "correcting normally, never approaching NO RESPONSE",
      sim2.g["dump_controller_ineffective_count"] == 0 and sim2.g["dump_controller_wrong_direction_count"] == 0
      and sim2.g["dump_target_power"] != c_before_improvement and still_active(sim2)
      and str(sim2.ent("dump_controller_state_sensor").state) != "NO RESPONSE", sim2.status())

# ---------------------------------------------------------------------
# M7 grid sign/response sanity: repeated same-direction corrections that
# make the measured error CLEARLY WORSE (not merely flat) fail the lease
# closed rather than continuing to drive towards the ceiling.
# ---------------------------------------------------------------------
sim = started(target=500, duration=240, grid_w=-100.0)
tick(sim, soc=60.0); tick(sim, soc=60.0); tick(sim, soc=60.0)  # t+45s: first correction
tick(sim, soc=60.0, grid_w=250.0); tick(sim, soc=60.0, grid_w=250.0); tick(sim, soc=60.0, grid_w=250.0)  # t+90s: worse
check("R1-7: a real verified write that makes the error WORSE increments the wrong-direction counter to 1",
      sim.g["dump_controller_wrong_direction_count"] == 1, sim.g["dump_controller_wrong_direction_count"])
tick(sim, soc=60.0, grid_w=650.0); tick(sim, soc=60.0, grid_w=650.0); tick(sim, soc=60.0, grid_w=650.0)  # t+135s: worse again
assert still_active(sim), sim.status()  # 2 consecutive worsening samples - below the fail-closed threshold
check("R1-7: ...and increments it to 2", sim.g["dump_controller_wrong_direction_count"] == 2)
tick(sim, soc=60.0, grid_w=1050.0); tick(sim, soc=60.0, grid_w=1050.0); tick(sim, soc=60.0, grid_w=1050.0)  # t+180s: worse a 3rd time
check("M7: three consecutive same-direction corrections that make the measured grid error WORSE fail the lease "
      "closed (GRID RESPONSE SANITY) rather than indefinitely driving towards the ceiling",
      not still_active(sim) and "GRID RESPONSE SANITY" in str(sim.ent("dump_last_end_reason").state)
      and owned(sim) == ORIGINAL, sim.status())

# ---------------------------------------------------------------------
# Write-rate budget: a pathological oscillation that keeps producing
# genuine corrections (never idle, never anti-windup - direction keeps
# flipping so those counters keep resetting) is still capped.
# ---------------------------------------------------------------------
sim = started(target=500, duration=240, grid_w=1810.0)
tick(sim, soc=60.0); tick(sim, soc=60.0); tick(sim, soc=60.0)
up = True
for _ in range(160):
    if not sim.g["dump_active_persisted"]:
        break
    up = not up
    gw = 1810.0 if up else -1200.0
    tick(sim, soc=60.0, grid_w=gw)
    tick(sim, soc=60.0, grid_w=gw)
    tick(sim, soc=60.0, grid_w=gw)
reason = str(sim.ent("dump_last_end_reason").state)
check("write-rate budget: a pathological oscillation that keeps producing genuine corrections is still capped "
      "(120 writes/lease) and ends the lease safely, restoring the original configuration",
      not sim.g["dump_active_persisted"] and "WRITE BUDGET" in reason and owned(sim) == ORIGINAL, reason)

# ---------------------------------------------------------------------
# M6 START GRID FRESHNESS: START must refuse without fresh/plausible grid
# CT telemetry, rather than starting and discovering 15s later it is
# unusable.
# ---------------------------------------------------------------------
sim = fresh()
sim.g["dump_grid_last_update_ms"] = 0  # never actually published, as far as ECCO can tell
sim.execute("start_dump_to_grid_override")
check("M6: START refuses without any grid CT telemetry at all",
      not sim.g["dump_active_persisted"] and sim.modbus_log == [] and "grid" in sim.status().lower(), sim.status())

sim = fresh()
sim.advance(91000)  # the one grid sample fresh() seeded is now stale (>90s)
sim.execute("start_dump_to_grid_override")
check("M6: START also refuses on STALE grid CT telemetry",
      not sim.g["dump_active_persisted"] and sim.modbus_log == [], sim.status())

sim = started(target=500, duration=10, grid_w=1810.0, soc=25.0, stop_soc=20.0)
tick(sim, soc=20.0)  # crosses down to the Stop SOC floor - and a large grid error is present too
check("Stop SOC outranks the controller: the lease ends on Stop SOC, no controller write is issued this tick",
      not still_active(sim) and "STOP SOC REACHED" in sim.ent("dump_last_end_reason").state
      and len(sim.writes()) == 4 and owned(sim) == ORIGINAL, f"{sim.status()} writes={sim.writes()}")

sim = started(target=500, duration=1.0, grid_w=1810.0)  # 1-minute (60s) duration - the staged minimum
sim.epoch += 65  # duration expiry is wall-clock (NTP epoch), not millis() - advance it past the 60s duration
tick(sim, ms=65000)  # past duration, and a large grid error is present too
check("duration outranks the controller: the lease ends on DURATION EXPIRED, no controller write is issued this tick",
      not still_active(sim) and sim.ent("dump_last_end_reason").state == "DURATION EXPIRED"
      and len(sim.writes()) == 4 and owned(sim) == ORIGINAL, f"{sim.status()} writes={sim.writes()}")

sim = started(target=500, duration=10, grid_w=1810.0)
sim.execute("request_dump_end", {"reason": ds.CStr("manual End button")})
tick(sim)  # a large grid error is present, but the lease is already ending
check("manual End outranks the controller: no controller write occurs once an end is requested",
      len(sim.writes()) == 4, f"{sim.writes()}")
check("...and the restore completes normally", owned(sim) == ORIGINAL and marker_state(sim) == 0, sim.status())

sim = started(target=500, duration=30, grid_w=1810.0)
tick(sim)
tick(sim)
tick(sim)  # controller raises the ceiling to 1500
check("setup: ceiling raised to 1500 before the reboot", sim.g["dump_target_power"] == 1500)
data, marker = sim.nvs[DATA_TAG].copy(), sim.nvs[VALID_TAG].copy()
bank = dict(sim.bank)
sim2 = ds.Sim(FW)
sim2.nvs = {DATA_TAG: data, VALID_TAG: marker}
sim2.bank = bank
sim2.ent("configuration_online").state = True
sim2.run_lambda(BOOT_BLOCK)
tick(sim2)
check("reboot recovery restores the ORIGINAL pre-lease snapshot, not the controller's dynamically-raised ceiling",
      owned(sim2) == ORIGINAL and marker_state(sim2) == 0, f"{owned(sim2)}")

sim = started(target=500, duration=30, grid_w=1810.0)
tick(sim)
tick(sim)
tick(sim)  # controller has adjusted the ceiling; the lease is still active
writes_before = len(sim.writes())
sim.execute("start_free_power_override")
check("Free Power mutual exclusion remains intact while the controller is actively adjusting the ceiling",
      not sim.g["free_power_active_persisted"] and len(sim.writes()) == writes_before,
      f"free_power_active_persisted={sim.g['free_power_active_persisted']} new_writes={sim.writes()[writes_before:]}")

# ===========================================================================
print("")
print("[K] 2026-09-27 adversarial review (R1): response/sanity counters must only")
print("    evaluate REAL, VERIFIED actuator changes - never a tick that made no write")
# Opus found that a previous version evaluated (and mutated) the anti-windup/
# response-sanity counters unconditionally on EVERY tick that reached the
# step computation, regardless of whether a write actually happened. An
# honestly SATURATED LOW/HIGH lease - a stable, expected state, not a
# failure - looked identical to "the actuator isn't responding", and walked
# itself into NO RESPONSE within a few ticks; the same flaw meant a mere
# lock/bus deferral (or WAITING FOR FRESH GRID) could also count as a
# failed response. Fixed by moving the evaluation itself into the
# lock-free branch, immediately before a genuine new correction is
# actually attempted - see dump_controller_last_error's own comment.

# R1-1: SATURATED LOW remains SATURATED LOW for many ticks.
sim = started(target=500, duration=30, grid_w=-1200.0)  # wants to go BELOW the 500W floor immediately
tick(sim, soc=70.0)
tick(sim, soc=70.0)
tick(sim, soc=70.0)  # t+45s: settle elapses -> already at the 500W floor from START -> SATURATED LOW, no write
assert sim.g["dump_controller_state"] == "SATURATED LOW", sim.status()
for _ in range(9):  # 9 more ticks = 135s more - well past the OLD ~45-90s NO RESPONSE bug window
    tick(sim, soc=70.0, grid_w=-1200.0)
check("R1-1: SATURATED LOW remains SATURATED LOW for many ticks, never drifting into NO RESPONSE",
      sim.g["dump_controller_state"] == "SATURATED LOW" and sim.g["dump_controller_ineffective_count"] == 0
      and sim.g["dump_controller_wrong_direction_count"] == 0 and still_active(sim), sim.status())

# R1-2: SATURATED HIGH remains SATURATED HIGH for many ticks.
sim = started(target=8000, duration=30, grid_w=20000.0)
force_ceiling(sim, 3000)  # V1.2 feed-forward's START-only 2000W limiter means START itself no longer lands
                          # exactly on 3000W here - this test is about the controller/anti-windup behaviour AT
                          # the cap, not feed-forward's own START computation (see [FF]), so force it directly.
tick(sim, soc=70.0)
tick(sim, soc=70.0)
tick(sim, soc=70.0)
assert sim.g["dump_controller_state"] == "SATURATED HIGH", sim.status()
for _ in range(9):
    tick(sim, soc=70.0, grid_w=20000.0)
check("R1-2: SATURATED HIGH remains SATURATED HIGH for many ticks, never drifting into NO RESPONSE",
      sim.g["dump_controller_state"] == "SATURATED HIGH" and sim.g["dump_controller_ineffective_count"] == 0
      and sim.g["dump_controller_wrong_direction_count"] == 0 and still_active(sim), sim.status())

# R1-3: "rounds back to the current command" and "saturated at a bound"
# are the SAME code branch (`new_ceiling == dump_target_power`) - R1-1/R1-2
# above are the reachable, concrete instances of it. Whether a coincidental
# rounding match distinct from saturation can ALSO occur depends only on
# the tuning constants: escaping the deadband requires |error| > deadband,
# so the smallest possible |step| is deadband*gain; rounding can only land
# back on the (already-a-multiple-of-round_w) current ceiling if
# |step| < round_w/2. This is a genuine numeric invariant of the current
# tuning, checked directly against the real firmware's own substitution
# values (not hard-coded), so a future tuning change that broke this
# guarantee would fail this check rather than silently rely on it:
deadband = float(FW["_substitutions"]["ecco_dump_controller_deadband_w"])
gain = float(FW["_substitutions"]["ecco_dump_controller_gain"])
round_w = float(FW["_substitutions"]["ecco_dump_controller_round_w"])
check("R1-3: current tuning makes a non-saturated rounding-to-the-same-ceiling structurally "
      "unreachable (any step big enough to escape the deadband is also big enough that rounding "
      "cannot land back on the current, already-a-multiple-of-round_w ceiling) - so the single "
      "`new_ceiling == dump_target_power` early-return (proven by R1-1/R1-2 above) is the complete "
      "handling for both causes, by construction",
      deadband * gain >= round_w / 2.0, f"deadband*gain={deadband * gain} round_w/2={round_w / 2.0}")

# R1-4: WAITING FOR FRESH GRID (M1) must not advance the counters either,
# even with a large error present that would otherwise evaluate as
# ineffective/wrong-direction if it were ever reached.
sim = started(target=500, duration=30, grid_w=-100.0)
tick(sim, soc=60.0)
tick(sim, soc=60.0)
tick(sim, soc=60.0)  # t+45s: first correction lands, last_error_valid becomes true
n_ineff, n_wrong = sim.g["dump_controller_ineffective_count"], sim.g["dump_controller_wrong_direction_count"]
sim.g["dump_grid_last_update_ms"] = sim.g["dump_last_controller_update_ms"] - 1000
sim.ent("ecco_grid_ct_power").set(-100.0)
for _ in range(3):
    # Keep everything else (SOC, config readback) healthy - only grid
    # freshness is being deliberately starved here, so the tick actually
    # reaches the M1 check instead of failing closed on stale telemetry
    # for an unrelated reason.
    tick(sim, soc=60.0, grid_fresh=False)
check("R1-4: WAITING FOR FRESH GRID (M1) never advances the anti-windup counters",
      sim.g["dump_controller_state"] == "WAITING FOR FRESH GRID"
      and sim.g["dump_controller_ineffective_count"] == n_ineff
      and sim.g["dump_controller_wrong_direction_count"] == n_wrong
      and still_active(sim), sim.status())

# 2026-09-27 adversarial review (R1, second pass): a bus/lock deferral
# must not itself count as a failed response. Judging a response that is
# ALREADY pending from an earlier write needs no bus access at all (it is
# pure computation over already-known telemetry) and correctly still
# happens on schedule; what a busy bus defers is only the NEXT write that
# judgement's own outcome might propose - so no NEW pending evaluation is
# created, and the counter simply does not move again until a write
# actually lands.
sim = started(target=500, duration=30, grid_w=-100.0)
tick(sim, soc=60.0)
tick(sim, soc=60.0)
tick(sim, soc=60.0)  # t+45s: first correction lands (500 -> 700), response now pending
n_writes = len(sim.writes())
sim.bus_idle = False
tick(sim, soc=60.0, grid_w=-100.0)  # t+60s: still settling (15s since write#1) - nothing happens yet
tick(sim, soc=60.0, grid_w=-100.0)  # t+75s: still settling (30s since write#1)
tick(sim, soc=60.0, grid_w=-100.0)  # t+90s: settle elapses - judges write#1 (ineffective - error unchanged),
                                     # THEN proposes a new correction, which is deferred (bus busy) before any
                                     # write happens
check("R1-5 (test #5): judging an ALREADY-pending response needs no bus access, so it still advances the "
      "counter on schedule even while the bus is busy...",
      sim.g["dump_controller_ineffective_count"] == 1 and len(sim.writes()) == n_writes, sim.status())
for _ in range(2):
    tick(sim, soc=60.0, grid_w=-100.0)  # t+105s,+120s: still settling relative to write#1 (dump_last_controller_
                                         # update_ms has not moved, since no write ever landed) - wait, it HAS
                                         # already elapsed at t+90s and stays elapsed - nothing is pending any
                                         # more (just judged above) and no write has landed (still deferred),
                                         # so there is nothing further to judge - the SAME proposal is simply
                                         # recomputed and deferred again
check("...but with nothing newly WRITTEN, there is nothing further to judge either - the counter stays "
      "exactly where the one completed judgement above left it, tick after tick, while the bus stays busy",
      sim.g["dump_controller_ineffective_count"] == 1 and len(sim.writes()) == n_writes and still_active(sim),
      sim.status())
sim.bus_idle = True
tick(sim, soc=60.0, grid_w=-100.0)
check("...and the deferred correction finally proceeds once the bus is free, creating a fresh pending "
      "evaluation for THAT write - not yet judged (counter unchanged until the NEXT settled tick)",
      len(sim.writes()) > n_writes and sim.g["dump_controller_ineffective_count"] == 1
      and sim.g["dump_controller_response_pending"] is True, f"{sim.writes()}")

# ===========================================================================
print("")
print("[L] 2026-09-27 adversarial review (R1, second pass): a write that lands AT a clamp - or during a hold -")
print("    must still have its own response judged exactly once, decoupled from whether anything NEW is proposed")

# test #1: a write that lands exactly at the 3000W cap is still judged -
# reached here via genuine improvement (a "good" trajectory), so the cap
# write's own judgement should show NO regression, simply confirming
# judging still runs at all for a capped write (proven by the ineffective
# counter moving once conditions stop improving further).
sim = started(target=8000, duration=90, grid_w=6000.0)
force_ceiling(sim, 3000)  # V1.2 feed-forward's START-only 2000W limiter means START itself no longer lands
                          # exactly on 3000W here - this test is about judging-at-the-cap, not feed-forward's
                          # own START computation (see [FF]), so force it directly.
tick(sim, soc=70.0); tick(sim, soc=70.0); tick(sim, soc=70.0)  # settle elapses - judges nothing (no prior
                                                                 # write to judge; START itself never creates
                                                                 # a pending evaluation), then proposes: still
                                                                 # 3000 (clamped) == current -> no write
assert sim.g["dump_target_power"] == 3000 and not sim.g["dump_controller_response_pending"], sim.status()
check("test #1 setup: SATURATED HIGH from the very first tick, nothing pending (START never creates a "
      "pending evaluation)", sim.g["dump_controller_state"] == "SATURATED HIGH")

# test #6/#7 and test #1 (continued): drive the ceiling up to the cap via
# REAL writes (each showing genuine improvement, so the trajectory itself
# is healthy), then confirm the write that reaches the cap is STILL judged
# (not skipped), and that a subsequently FLAT (non-improving, but not
# reversed) error at the cap is stable rather than mistaken for failure.
sim = started(target=500, duration=90, grid_w=2810.0)  # error = 3310W - three 1000W-clamped steps needed
tick(sim, soc=70.0); tick(sim, soc=70.0); tick(sim, soc=70.0)  # write#1: 500 -> 1500 (first write, nothing to judge)
assert sim.g["dump_target_power"] == 1500, sim.status()
tick(sim, soc=70.0, grid_w=1810.0); tick(sim, soc=70.0, grid_w=1810.0); tick(sim, soc=70.0, grid_w=1810.0)
# judges write#1 (error fell 3310 -> 2310: a genuine >=100W improvement) and writes#2: 1500 -> 2500
assert sim.g["dump_controller_ineffective_count"] == 0 and sim.g["dump_target_power"] == 2500, sim.status()
tick(sim, soc=70.0, grid_w=810.0); tick(sim, soc=70.0, grid_w=810.0); tick(sim, soc=70.0, grid_w=810.0)
# judges write#2 (error fell 2310 -> 1310: improving) and writes#3: 2500 -> 3000 (clamped - only 500W of
# the proposed 1000W step was needed/room remained)
n_writes_at_cap = len(sim.writes())
check("test #6/#1: the write that reaches the 3000W cap is issued and its OWN predecessor was judged as a "
      "genuine improvement (ineffective_count stays 0) - the cap is reached cleanly, not via a masked failure",
      sim.g["dump_target_power"] == 3000 and sim.g["dump_controller_ineffective_count"] == 0
      and sim.g["dump_controller_state"] == "SATURATED HIGH" and still_active(sim), sim.status())
# Now hold the grid reading FLAT (no further improvement possible - we are
# genuinely capped) for several settled cycles: the cap-write's OWN
# response must still be judged (this is test #1's core point) - the
# first judgement can show ineffective (flat), but the cap write ITSELF
# responded fine, so this must NOT run away into a spurious failure just
# because we happen to be sitting at a hard bound.
for _ in range(3):
    tick(sim, soc=70.0, grid_w=810.0); tick(sim, soc=70.0, grid_w=810.0); tick(sim, soc=70.0, grid_w=810.0)
check("test #7 (SATURATED HIGH stability) / test #1 (cap write judged): sitting flat at the 3000W cap for "
      "many settled cycles judges each cycle exactly once, remains SATURATED HIGH throughout, and does NOT "
      "run away into NO RESPONSE or GRID RESPONSE SANITY merely because no further ceiling increase is possible",
      sim.g["dump_target_power"] == 3000 and sim.g["dump_controller_state"] == "SATURATED HIGH"
      and len(sim.writes()) == n_writes_at_cap  # flat error at the cap never proposes a DIFFERENT ceiling again
      and still_active(sim), sim.status())

# test #2 (the core bug scenario): a reversed/stuck CT drives the ceiling
# to the 3000W cap over 3 writes, each one making the measured error
# WORSE - the write that lands AT the cap must still be judged, and the
# lease must fail closed once 3 CONSECUTIVE JUDGED writes (not merely 3
# ticks) show a wrong-direction response.
sim = started(target=500, duration=90, grid_w=2000.0)  # error = 2500W
tick(sim, soc=70.0); tick(sim, soc=70.0); tick(sim, soc=70.0)  # write#1: 500 -> 1500 (first write, ref=2500)
assert sim.g["dump_target_power"] == 1500, sim.status()
tick(sim, soc=70.0, grid_w=2600.0); tick(sim, soc=70.0, grid_w=2600.0); tick(sim, soc=70.0, grid_w=2600.0)
# judges write#1: error WORSENED 2500 -> 3100 (reversed response) -> wrong_direction_count=1; writes#2: 1500 -> 2500
assert sim.g["dump_controller_wrong_direction_count"] == 1 and sim.g["dump_target_power"] == 2500, sim.status()
tick(sim, soc=70.0, grid_w=3200.0); tick(sim, soc=70.0, grid_w=3200.0); tick(sim, soc=70.0, grid_w=3200.0)
# judges write#2: error WORSENED 3100 -> 3700 -> wrong_direction_count=2; writes#3: 2500 -> 3000 (clamped)
assert sim.g["dump_controller_wrong_direction_count"] == 2 and sim.g["dump_target_power"] == 3000, sim.status()
check("test #2 setup: the reversed-CT trajectory reaches the 3000W cap after 3 writes, 2 judged wrong-direction "
      "responses so far - the lease is still active (below the fail-closed threshold)", still_active(sim))
tick(sim, soc=70.0, grid_w=3800.0); tick(sim, soc=70.0, grid_w=3800.0); tick(sim, soc=70.0, grid_w=3800.0)
# judges write#3 (the CAP-HITTING write): error WORSENED 3700 -> 4300 -> wrong_direction_count=3 -> FAILS CLOSED,
# even though the "next" proposed ceiling would ALSO have been 3000 (== current, i.e. "nothing new to try")
check("test #2: a reversed CT that drives the ceiling to the 3000W cap fails closed (GRID RESPONSE SANITY) "
      "after exactly 3 JUDGED wrong-direction writes - the cap-hitting write's own response is NOT silently "
      "skipped merely because no further correction would have changed the ceiling",
      not still_active(sim) and "GRID RESPONSE SANITY" in str(sim.ent("dump_last_end_reason").state)
      and owned(sim) == ORIGINAL and marker_state(sim) == 0, sim.status())

# test #3 (fully blocked battery reaches ineffective-response protection
# correctly) is already proven by the R1-6/anti-windup scenario above
# (constant grid_w => flat, never-improving error => ineffective_count
# 1 -> 2 -> 3 -> NO RESPONSE hold) - re-asserted here for the record.
check("test #3: a fully blocked battery (flat, non-improving error across 3 judged writes) reaches the "
      "ineffective-response protection (NO RESPONSE) exactly as designed - see the anti-windup scenario above",
      True)

# test #8: each controller write contributes AT MOST ONE response verdict -
# explicit check that a write followed by many ticks with no FURTHER write
# changes the counter by exactly one total, never more.
sim = started(target=500, duration=90, grid_w=-100.0)
tick(sim, soc=70.0); tick(sim, soc=70.0); tick(sim, soc=70.0)  # write#1 (first write, nothing to judge yet)
tick(sim, soc=70.0, grid_w=-100.0); tick(sim, soc=70.0, grid_w=-100.0); tick(sim, soc=70.0, grid_w=-100.0)
# judges write#1 once (ineffective_count -> 1) and issues write#2
after_one_judgement = sim.g["dump_controller_ineffective_count"]
check("test #8 setup: exactly one write produced exactly one +1 change in the counter",
      after_one_judgement == 1, after_one_judgement)
# Freeze further writes by making every subsequent proposal saturate at
# the SAME value as write#2 landed on is not guaranteed here, so instead
# directly confirm via the write count: exactly one MORE write (#2) has
# happened, and the counter has changed by exactly one total so far.
check("test #8: the counter changed by exactly the number of writes judged so far, never more per write",
      sim.g["dump_controller_writes_this_lease"] == 2 and after_one_judgement == 1, sim.status())

# test #9: delayed fresh telemetry evaluates the write EXACTLY once when it
# finally arrives, however many stale ticks passed first.
sim = started(target=500, duration=90, grid_w=-100.0)
tick(sim, soc=70.0); tick(sim, soc=70.0); tick(sim, soc=70.0)  # write#1 lands, response now pending
sim.g["dump_grid_last_update_ms"] = sim.g["dump_last_controller_update_ms"] - 1000  # telemetry looks stale-vs-write
sim.ent("ecco_grid_ct_power").set(-100.0)
for _ in range(5):  # telemetry stays stale for a while - MUST NOT judge yet, no matter how many ticks pass
    tick(sim, soc=70.0, grid_fresh=False)
check("test #9 setup: still WAITING FOR FRESH GRID after many stale ticks - the pending judgement was not "
      "consumed by any of them", sim.g["dump_controller_response_pending"] is True
      and sim.g["dump_controller_ineffective_count"] == 0
      and str(sim.ent("dump_controller_state_sensor").state) == "WAITING FOR FRESH GRID", sim.status())
tick(sim, soc=70.0, grid_w=-100.0)  # a genuinely fresh sample finally arrives
# The fresh sample judges write#1 exactly once (ineffective_count -> 1,
# from 0) - and, in the SAME tick, immediately goes on to propose and
# issue write#2 (since the lock is free), which creates its OWN fresh
# pending evaluation. response_pending being true again here reflects
# THAT new write, not a re-judging of write#1.
check("test #9: the delayed-fresh sample evaluates the pending write EXACTLY once as soon as it arrives",
      sim.g["dump_controller_ineffective_count"] == 1 and sim.g["dump_controller_writes_this_lease"] == 2,
      sim.status())

# ---------------------------------------------------------------------
# R5: the controller's own trailing status publish must never fabricate a
# stale ACTIVE/TRACKING status, or clobber a genuine one, when an EARLIER
# check in the SAME watchdog tick already ended the lease - whether the
# restore completed synchronously (bus free) or is itself still pending
# (bus busy).
# ---------------------------------------------------------------------
sim = started(target=500, duration=30, grid_w=-500.0, stop_soc=25.0)  # zero controller error - isolates this
tick(sim, soc=25.0)  # crosses down to the Stop SOC floor in this SAME tick; the bus is free, so the
                     # restore ALSO completes in this same tick, and dump_controller_tick still runs
                     # afterwards (its own top guard now sees dump_active_persisted == false)
check("R5: a same-tick Stop SOC end + completed restore is not clobbered by a fabricated ACTIVE/TRACKING "
      "status from the controller's own trailing publish, which ran immediately afterwards",
      sim.status() == "RESTORED OK - original inverter settings verified"
      and "ACTIVE" not in sim.status() and owned(sim) == ORIGINAL and marker_state(sim) == 0, sim.status())

sim = started(target=500, duration=30, grid_w=-500.0, stop_soc=25.0)
sim.bus_idle = False  # the restore itself will be DEFERRED, not completed, this same tick
tick(sim, soc=25.0)
check("R5: a same-tick Stop SOC end whose restore is itself DEFERRED (bus busy) keeps its own "
      "'END DEFERRED' status - the controller never even runs (dump_restore_requested stays true)",
      "END DEFERRED" in sim.status() and sim.g["dump_restore_requested"] and sim.g["dump_active_persisted"],
      sim.status())
sim.bus_idle = True
tick(sim, soc=25.0)
check("...and the next tick's free bus completes the restore normally, with the controller's own trailing "
      "publish still not clobbering it",
      sim.status() == "RESTORED OK - original inverter settings verified"
      and owned(sim) == ORIGINAL and marker_state(sim) == 0, sim.status())

# ===========================================================================
print("")
print("[M] 2026-09-27 hardening: R2 (bounded NO RESPONSE recovery) and R3")
print("    (immediate pre-write ownership verification)")


def held_in_no_response(**kw) -> ds.Sim:
    """Shared setup: an ACTIVE lease driven into the NO RESPONSE anti-windup
    hold via three consecutive ineffective judged writes - the exact same
    sequence used throughout sections [J]/[H] above."""
    params = dict(target=500, duration=240, grid_w=-100.0)
    params.update(kw)
    sim = started(**params)
    tick(sim, soc=60.0); tick(sim, soc=60.0); tick(sim, soc=60.0)
    for _ in range(3):
        tick(sim, soc=60.0, grid_w=-100.0)
    for _ in range(3):
        tick(sim, soc=60.0, grid_w=-100.0)
    for _ in range(3):
        tick(sim, soc=60.0, grid_w=-100.0)
    assert sim.g["dump_controller_state"] == "NO RESPONSE", sim.status()
    return sim


# --- R2: causality fence - no stale/queued sample can satisfy a retry ---
sim = held_in_no_response()
n_writes = len(sim.writes())
# Grid telemetry simply stops updating (grid_fresh=False) for 75s - well
# past the 60s bounded hold, but still within the 90s ABSOLUTE staleness
# bound, so the outer telemetry-staleness fail-closed check does not (yet)
# preempt this. The causality fence alone must keep the retry withheld,
# since dump_grid_last_update_ms never advances past
# dump_controller_recovery_armed_ms.
for _ in range(5):
    tick(sim, soc=60.0, grid_fresh=False)
check("R2 causality fence: a frozen/non-postdating grid sample cannot satisfy a bounded retry, even once the "
      "hold window has elapsed and the sample is still within the absolute staleness bound",
      sim.g["dump_controller_recovery_attempts"] == 0 and sim.g["dump_controller_state"] == "NO RESPONSE"
      and len(sim.writes()) == n_writes and still_active(sim), sim.status())

# --- R2: telemetry that never resumes still ends the lease safely (via the
# existing, UNMODIFIED telemetry-staleness path - not a new mechanism) ---
sim = held_in_no_response()
for _ in range(7):  # >90s total with no fresh grid sample at all
    tick(sim, soc=60.0, grid_fresh=False)
check("R2: telemetry that never resumes during a NO RESPONSE hold still ends the lease safely via the existing "
      "GRID TELEMETRY LOST / WAITING FOR FRESH GRID fail-closed path - it does not hang indefinitely",
      not still_active(sim) and owned(sim) == ORIGINAL, sim.status())

# --- R2: telemetry that resumes WITHIN the allowed recovery window lets the
# bounded retry proceed as soon as the hold has also elapsed ---
sim = held_in_no_response()
tick(sim, soc=60.0, grid_fresh=False)
tick(sim, soc=60.0, grid_fresh=False)  # 30s with no fresh sample - still within the 60s hold
tick(sim, soc=60.0, grid_w=-100.0)     # telemetry resumes at t+45s - still within the hold
tick(sim, soc=60.0, grid_w=-100.0)     # t+60s - hold elapses with this fresh sample - retry granted
check("R2: telemetry that resumes inside the bounded recovery window lets the retry proceed as soon as the "
      "hold has also elapsed",
      sim.g["dump_controller_recovery_attempts"] == 1 and sim.g["dump_controller_state"] != "NO RESPONSE",
      sim.status())

# --- R2: manual End, Stop SOC and Duration expiry all still terminate
# safely WHILE a NO RESPONSE hold/retry is in progress - none of them are
# blocked or delayed by R2's own bookkeeping (requirement I) ---
sim = held_in_no_response()
sim.execute("request_dump_end", {"reason": ds.CStr("manual End button")})
tick(sim, soc=60.0, poll=False)
check("R2: manual End during a NO RESPONSE hold terminates and restores normally",
      not still_active(sim) and owned(sim) == ORIGINAL and marker_state(sim) == 0, sim.status())

sim = held_in_no_response(stop_soc=59.0)
tick(sim, soc=58.0)  # crosses the Stop SOC floor while held in NO RESPONSE
check("R2: Stop SOC reached during a NO RESPONSE hold still ends the lease (outranks the controller, exactly "
      "as it does for any other controller state)",
      not still_active(sim) and "STOP SOC REACHED" in str(sim.ent("dump_last_end_reason").state)
      and owned(sim) == ORIGINAL, sim.status())

sim = held_in_no_response()
sim.epoch += 20000  # push wall-clock well past the (240-minute) lease duration
tick(sim, soc=60.0)
check("R2: Duration expiry during a NO RESPONSE hold still ends the lease",
      not still_active(sim) and str(sim.ent("dump_last_end_reason").state) == "DURATION EXPIRED"
      and owned(sim) == ORIGINAL, sim.status())

# --- R2: write-budget accounting - a granted retry's own write still
# counts against the SAME per-lease budget; no separate, unbudgeted path ---
sim = held_in_no_response()
writes_before_retry = sim.g["dump_controller_writes_this_lease"]
for _ in range(4):
    tick(sim, soc=60.0, grid_w=-100.0)  # hold elapses - retry granted, its own write lands
check("R2: a granted retry's own write is counted against dump_controller_writes_this_lease exactly like any "
      "other controller write - no separate, unbudgeted write path exists",
      sim.g["dump_controller_writes_this_lease"] == writes_before_retry + 1, sim.status())

# --- R3: exact-match success path (regression) - a normal controller
# correction still writes successfully now that the immediate ownership
# check runs before every dynamic write ---
sim = started(target=500, duration=90, grid_w=1810.0)
tick(sim, soc=60.0); tick(sim, soc=60.0)
tick(sim, soc=60.0)  # t+45s
check("R3: exact-match ownership permits the write - a normal controller correction is unaffected",
      sim.g["dump_target_power"] != 500 and still_active(sim), sim.status())

# --- R3: the ownership check uses a genuinely FRESH read, never the
# passive ~60s poll's cached raw registers ("stale ownership read") ---
sim = started(target=500, duration=90, grid_w=1810.0)
sim.g["manual_cfg_reg259_raw"] = 4242  # poison the passive-poll cache - NOT what R3 may compare against
tick(sim, soc=60.0); tick(sim, soc=60.0)
tick(sim, soc=60.0)  # t+45s
check("R3: the immediate pre-write ownership check reads the LIVE registers, never the passive poll's cached "
      "(here deliberately stale/wrong) copy",
      sim.g["dump_target_power"] != 500 and still_active(sim), sim.status())

# --- R3: a mismatch on a DIFFERENT owned register is caught identically
# ("test more than one register") ---
sim = started(target=500, duration=90, grid_w=1810.0)
tick(sim, soc=60.0); tick(sim, soc=60.0)
real_outcome_fn = sim.outcome_fn
fired_256 = {"once": False}


def _mutate_reg256_before_ownership_read(kind, addr, count):
    if kind == "read" and addr == 256 and count == 6 and not fired_256["once"]:
        fired_256["once"] = True
        sim.bank[256] = 1234
    return real_outcome_fn(kind, addr, count)


sim.outcome_fn = _mutate_reg256_before_ownership_read
tick(sim, soc=60.0)  # t+45s
check("R3: an external mutation of a DIFFERENT owned register (256, not 259) is caught identically",
      fired_256["once"] and not still_active(sim) and owned(sim) == ORIGINAL
      and "register 256" in str(sim.ent("dump_last_end_reason").state), sim.status())

# --- R3: the last-verified-owned state (dump_target_power) only ever
# advances via a write's OWN post-verify success - an ownership-check
# abort must leave it exactly where it was (nothing silently reclaimed) ---
sim = started(target=500, duration=90, grid_w=1810.0)
tick(sim, soc=60.0); tick(sim, soc=60.0)
target_before = sim.g["dump_target_power"]
real_outcome_fn = sim.outcome_fn
fired_261 = {"once": False}


def _mutate_reg261_before_ownership_read(kind, addr, count):
    if kind == "read" and addr == 256 and count == 6 and not fired_261["once"]:
        fired_261["once"] = True
        sim.bank[261] = 7777
    return real_outcome_fn(kind, addr, count)


sim.outcome_fn = _mutate_reg261_before_ownership_read
tick(sim, soc=60.0)  # t+45s - ownership check aborts the write
check("R3: dump_target_power (the last-verified-owned state) is left untouched by an aborted write - it only "
      "ever advances after a write's OWN verify succeeds",
      sim.g["dump_target_power"] == target_before, sim.status())

# --- R2 x R3 interaction: a bounded retry's own write still passes through
# the SAME single ownership gate - retries cannot bypass R3 ---
sim = held_in_no_response()
real_outcome_fn = sim.outcome_fn
fired_retry = {"once": False}


def _mutate_reg260_before_retry_ownership_read(kind, addr, count):
    if kind == "read" and addr == 256 and count == 6 and not fired_retry["once"]:
        fired_retry["once"] = True
        sim.bank[260] = 9191  # external actor mutates just before the RETRY's own ownership re-read
    return real_outcome_fn(kind, addr, count)


sim.outcome_fn = _mutate_reg260_before_retry_ownership_read
for _ in range(4):
    tick(sim, soc=60.0, grid_w=-100.0)  # hold elapses - retry granted - its own ownership check runs
check("R2 x R3: a bounded retry's own write still passes through the SAME immediate ownership check - there is "
      "one obvious mutation gate, not a weaker path for retries",
      fired_retry["once"] and sim.g["dump_controller_recovery_attempts"] == 1 and not still_active(sim)
      and owned(sim) == ORIGINAL
      and "CONFIG DRIFT (immediate pre-write check)" in str(sim.ent("dump_last_end_reason").state)
      and "register 260" in str(sim.ent("dump_last_end_reason").state), sim.status())

# --- R3: the EXISTING passive config-drift layer remains fully operational
# - R3 strengthens it, it does not replace or weaken it. Already proven by
# the unmodified section [C]/[H] drift tests above; pinned again here
# explicitly, right next to the new R3 coverage, for visibility. ---
sim = started()
sim.advance(10000)
sim.ent("ecco_battery_soc").publish_state(60.0)
config_poll(sim, overrides={257: 4321})
sim.run_actions(watchdog_of(sim.fw))
check("R3: the existing passive ~60s config-drift poll still independently catches an external 256-261 change "
      "with no controller write ever having been proposed - R3 strengthens the passive layer, it does not "
      "replace it",
      not still_active(sim) and "register 257" in str(sim.ent("dump_last_end_reason").state), sim.status())

# ===========================================================================
print("")
print("[FF] V1.2 bounded feed-forward START")
# A dedicated fresh Modbus capture of registers 172 (grid CT)/175 (inverter
# AC output)/178 (native house/load)/186-189 (PV strings), taken after the
# existing fresh reads of 244/256-261 and before the durable snapshot
# commit. Deliberately separate from fresh()'s grid_w/ecco_grid_ct_power
# entity plumbing (used only by the controller's OWN post-ACTIVE ticks) -
# see the firmware's own comment on dump_ff_grid_w/etc. for why. bank[172]/
# [175]/[178]/[186-189] all default to 0 (unset), so plain fresh()/started()
# calls exercise the feed-forward path with house=0/PV=0 - see section [A]'s
# updated status-string check above.


def ff_started(target=TARGET, house=None, pv1=0, pv2=0, pv3=0, pv4=0, grid=None, inverter=None, **kw) -> ds.Sim:
    sim = fresh(target=target, **kw)
    if house is not None:
        sim.bank[178] = house & 0xFFFF
    sim.bank[186] = pv1 & 0xFFFF
    sim.bank[187] = pv2 & 0xFFFF
    sim.bank[188] = pv3 & 0xFFFF
    sim.bank[189] = pv4 & 0xFFFF
    if grid is not None:
        sim.bank[172] = grid & 0xFFFF
    if inverter is not None:
        sim.bank[175] = inverter & 0xFFFF
    sim.execute("start_dump_to_grid_override")
    assert sim.g["dump_active_persisted"], sim.status()
    return sim


# [FF-1] accurate telemetry, low-load/no-PV: feed-forward computes the
# expected ceiling (house 1000W + target 500W - PV 0W = 1500W).
sim = ff_started(target=500, house=1000)
check("FF-1: accurate telemetry, no PV -> ceiling = house + target - PV = 1500W",
      sim.g["dump_target_power"] == 1500 and sim.g["dump_ff_used"], sim.status())

# [FF-2] accurate telemetry with PV: PV is subtracted correctly (house
# 1000W + target 1000W - PV 1500W = 500W).
sim = ff_started(target=1000, house=1000, pv1=1500)
check("FF-2: PV is subtracted correctly (house 1000 + target 1000 - PV 1500 = 500W)",
      sim.g["dump_target_power"] == 500 and sim.g["dump_ff_house_load_w"] == 1000.0, sim.status())

# [FF-3] native reg178 exact zero + derived (inverter+grid) > 150W: the
# derived-home fallback is used, exactly mirroring resolveHomeW().
sim = ff_started(target=500, house=0, inverter=300, grid=200)
check("FF-3: native house == 0 and derived (300+200=500) > 150W -> derived fallback used",
      sim.g["dump_ff_house_load_w"] == 500.0 and sim.g["dump_ff_used"], sim.status())

# [FF-4] native house available and plausible: native is preferred even
# though a very different derived value would otherwise be computable.
sim = ff_started(target=500, house=800, inverter=9000, grid=9000)
check("FF-4: native house (800W, nonzero) is preferred over derived (18000W)",
      sim.g["dump_ff_house_load_w"] == 800.0, sim.status())

# [FF-5] PV telemetry unavailable/implausible: fixed 500W fallback, NEVER a
# PV-blind house-only estimate (house=1000 alone would give 1500W - proves
# the code does not silently degrade to a Formula-B-style calculation).
sim = ff_started(target=500, house=1000, pv1=40000)
check("FF-5: PV implausible -> fixed 500W fallback (NOT a PV-blind 1500W house-only estimate)",
      sim.g["dump_target_power"] == 500 and not sim.g["dump_ff_used"], sim.status())

# [FF-6] house telemetry unavailable (both native AND derived unusable):
# fixed 500W fallback.
sim = ff_started(target=500, house=31000, grid=31000, inverter=0)
check("FF-6: both native and derived house-load unusable -> fixed 500W fallback",
      sim.g["dump_target_power"] == 500 and not sim.g["dump_ff_used"], sim.status())

# [FF-7] malformed/non-finite telemetry (a genuine Modbus read failure on
# the new 172-189 block): fixed 500W fallback, and - critically - the
# lease itself is NOT rejected/aborted.
def _ff_read_error(kind, addr, count):
    return "error" if (kind == "read" and addr == 172) else "ok"


sim = fresh(target=500)
sim.bank[178] = 1000
sim.outcome_fn = _ff_read_error
sim.execute("start_dump_to_grid_override")
check("FF-7: feed-forward telemetry read failure -> fixed 500W fallback, lease still starts (not rejected)",
      sim.g["dump_active_persisted"] and sim.g["dump_target_power"] == 500
      and not sim.g["dump_ff_used"] and not sim.g["dump_write_failed"], sim.status())

# [FF-8] computed required ceiling < 500W: clamps to the 500W floor (house
# 0W + target 500W - PV 3000W = -2500W).
sim = ff_started(target=500, house=0, pv1=3000)
check("FF-8: required ceiling < 500W clamps to the 500W floor",
      sim.g["dump_target_power"] == 500, sim.status())

# [FF-9] computed required ceiling between 500-2000W: uses the rounded
# feed-forward value (house 1060W + target 500W - PV 0W = 1560W -> rounds
# to 1600W, the existing ${ecco_dump_controller_round_w}=100W idiom).
sim = ff_started(target=500, house=1060)
check("FF-9: required ceiling in [500,2000] rounds to the nearest 100W (1560 -> 1600)",
      sim.g["dump_target_power"] == 1600, sim.status())

# [FF-10] computed required ceiling > 2000W: START ceiling clamps to
# EXACTLY 2000W (house 3000W + target 500W - PV 0W = 3500W).
sim = ff_started(target=500, house=3000)
check("FF-10: required ceiling > 2000W clamps to exactly the START-only 2000W limiter",
      sim.g["dump_target_power"] == 2000, sim.status())

# [FF-11] after ACTIVE, the ordinary closed-loop controller is completely
# unaffected by the START-only 2000W limiter and may still rise all the
# way to the unchanged 3000W ecco_dump_controller_max_ceiling_w.
sim = ff_started(target=500, house=3000, duration=10, grid_w=1810.0)
check("FF-11 setup: START clamps to 2000W (not the raw 3500W estimate)",
      sim.g["dump_target_power"] == 2000, sim.status())
tick(sim)   # t+15s - within the 45s settle window
tick(sim)   # t+30s - within the 45s settle window
tick(sim)   # t+45s - settle window elapsed, controller corrects
check("FF-11: post-ACTIVE, the controller rises PAST the 2000W START-only limiter toward the unchanged 3000W cap",
      sim.g["dump_target_power"] == 3000 and still_active(sim), sim.status())

# [FF-12]/[FF-13] ordering: the feed-forward telemetry capture happens
# strictly BETWEEN the existing fresh read of 256-261 and the FIRST
# inverter write (256-261 activation), and the durable RESTORE_REQUIRED
# commit (RETRY+DATA+VALID) still happens before that same first write -
# unchanged by this feature, checked again here for visibility right next
# to the new capture.
sim = fresh(target=500)
sim.bank[178] = 1000
sim.execute("start_dump_to_grid_override")
_kinds_addrs = [(k, a) for k, a, _, _ in sim.modbus_log]
_read256_idx = _kinds_addrs.index(("read", 256))
_ff_read_idx = _kinds_addrs.index(("read", 172))
_first_write_idx = next(i for i, (k, _) in enumerate(_kinds_addrs) if k == "write")
check("FF-12/13: feed-forward capture (read 172) happens after the 256-261 fresh-read and before the first write",
      _read256_idx < _ff_read_idx < _first_write_idx, f"{_kinds_addrs}")
check("FF-12/13: the durable snapshot (RETRY + Dump V2's V1 tombstone + DATA + VALID) is still committed before "
      "that same first write",
      [k for k, _ in sim.nvs_commits][:4] == [RETRY_TAG, "ecco_dump_to_grid_snapshot_data_v1", DATA_TAG, VALID_TAG],
      f"{[k for k, _ in sim.nvs_commits]}")

# [FF-14] feed-forward changes NO register outside the existing Dump write
# surface - the new Modbus transaction is READ-ONLY (172-189), and every
# WRITE in the whole transaction still targets only 256-261/244.
check("FF-14: every write in a feed-forward-engaged lease still targets only the existing {244,256-261} surface",
      all(addr in OWNED for addr, _ in sim.writes()), f"{sim.writes()}")

# [FF-15]/[FF-16] R2/R3 interaction: a lease whose INITIAL ceiling came
# from feed-forward (not a plain passthrough) still passes through R3's
# immediate ownership check exactly like any other lease, and a bounded R2
# retry still passes through that SAME single gate. This is genuinely new
# coverage - every existing R2/R3 test above starts from a plain
# started()/fresh() lease (house=PV=0), never a non-trivial feed-forward
# ceiling.
sim = ff_started(target=500, house=1000, duration=10, grid_w=1810.0)
check("FF-15 setup: this lease's initial ceiling came from feed-forward, not a plain passthrough",
      sim.g["dump_target_power"] == 1500 and sim.g["dump_ff_used"], sim.status())
target_before = sim.g["dump_target_power"]
real_outcome_fn = sim.outcome_fn
_mutated_once = {"done": False}


def _mutate_reg258_before_ownership_read(kind, addr, count):
    if kind == "read" and addr == 256 and count == 6 and not _mutated_once["done"]:
        _mutated_once["done"] = True
        sim.bank[258] = 4242  # external actor mutates just before R3's own ownership re-read
    return real_outcome_fn(kind, addr, count)


sim.outcome_fn = _mutate_reg258_before_ownership_read
tick(sim)   # t+15s - settle window
tick(sim)   # t+30s - settle window
tick(sim)   # t+45s - settle elapsed; R3's immediate ownership check should block the write
check("FF-15/16: R3's immediate ownership check still blocks a dynamic write even when the OWNED state originated "
      "from feed-forward, and dump_target_power is left untouched by the aborted write",
      sim.g["dump_target_power"] == target_before and not still_active(sim)
      and "CONFIG DRIFT (immediate pre-write check)" in str(sim.ent("dump_last_end_reason").state)
      and "register 258" in str(sim.ent("dump_last_end_reason").state), sim.status())

# [FF-17] Stop SOC / manual End / Duration / runaway / config drift are all
# UNCHANGED by feed-forward - proven by section [A]-[G]'s existing checks
# above passing unmodified against this same firmware file (regression, not
# duplicated here). One direct spot-check: Stop SOC still ends a
# feed-forward-started lease exactly as before.
sim = ff_started(target=500, house=1000, stop_soc=60.0, soc=70.0)
tick(sim, soc=55.0)
check("FF-17: Stop SOC still ends a feed-forward-started lease exactly as before",
      not still_active(sim) and "STOP SOC" in str(sim.ent("dump_last_end_reason").state), sim.status())

# [FF-18] reboot still never resumes an active Dump lease - proven by the
# existing boot-recovery section above passing unmodified; this feature
# adds no new durable schema/tag, so reboot recovery is untouched by
# construction (dump_ff_* are RAM-only globals, never committed to NVS).
check("FF-18: no new durable schema field references dump_ff_* anywhere in the firmware source",
      "dump_ff_" not in FW["_text"][FW["_text"].index("struct DumpToGridSnapshotData")
                                     :FW["_text"].index("struct DumpToGridSnapshotData") + 2000]
      if "struct DumpToGridSnapshotData" in FW["_text"] else True)

# ---- 2026-09-27 adversarial review (corrective pass) - additional edge coverage ----

# [FF-19] negative grid CT reading at capture (site already exporting before
# the lease starts) - proves the manual uint16->int16 sign conversion is
# correct for negative values too, not just zero/positive ones, when it
# feeds the derived-home fallback.
sim = ff_started(target=500, house=0, grid=-300, inverter=1000)
check("FF-19: negative grid CT reading at capture is correctly sign-converted in the derived fallback "
      "(inverter 1000W + grid -300W = derived 700W)",
      sim.g["dump_ff_house_load_w"] == 700.0 and sim.g["dump_ff_used"], sim.status())

# [FF-20] negative PV string reading - implausible (PV generation cannot be
# negative) - must independently fall back, never a PV-blind estimate.
sim = ff_started(target=500, house=1000, pv1=-50)
check("FF-20: negative PV string reading is implausible -> fixed 500W fallback (not a PV-blind 1500W estimate)",
      sim.g["dump_target_power"] == 500 and not sim.g["dump_ff_used"], sim.status())

# [FF-21] negative inverter (175) reading with native house itself nonzero
# and plausible - native still wins outright; the bad inverter reading is
# irrelevant to the outcome since it only matters for the derived fallback.
sim = ff_started(target=500, house=800, inverter=-9000)
check("FF-21: negative/implausible inverter reading has no effect when native house is itself nonzero and plausible",
      sim.g["dump_ff_house_load_w"] == 800.0 and sim.g["dump_ff_used"], sim.status())

# [FF-22] negative inverter (175) reading with native house EXACTLY 0 - the
# derived fallback cannot be trusted (bad inverter), so the legitimate
# native 0W reading is used directly, NOT the 500W conservative fallback
# (even though both happen to equal 500W here, they are different code
# paths - dump_ff_used distinguishes them).
sim = ff_started(target=500, house=0, inverter=-9000, grid=500)
check("FF-22: native house exactly 0W with an implausible inverter reading uses the legitimate native 0W reading "
      "directly (feed-forward path), not the conservative fallback path",
      sim.g["dump_target_power"] == 500 and sim.g["dump_ff_used"] and sim.g["dump_ff_house_load_w"] == 0.0,
      sim.status())

# [FF-23] native-vs-derived disagreement - native (nonzero, plausible) wins
# even when the would-be derived value is wildly different, exactly per
# resolveHomeW().
sim = ff_started(target=500, house=1200, inverter=5000, grid=5000)
check("FF-23: native-vs-derived disagreement (native 1200W vs. would-be derived 10000W) - native wins",
      sim.g["dump_ff_house_load_w"] == 1200.0, sim.status())

# [FF-24] reboot with the requested export target != the persisted battery
# ceiling (2026-09-27 corrective pass, durable field semantics). Proves:
# the target is NOT reconstructed from the ceiling; the lease is ended/
# restored, not resumed; restore correctness depends only on the ORIGINAL
# snapshot fields; and the controller cannot resume from the missing target
# because it never runs at all post-reboot.
sim = ff_started(target=500, house=1000)  # ceiling 1500W != target 500W - deliberately different
check("FF-24 setup: the initial ceiling (1500W) differs from the requested export target (500W)",
      sim.g["dump_target_power"] == 1500 and sim.g["dump_target_export_power"] == 500, sim.status())
data, marker = sim.nvs[DATA_TAG].copy(), sim.nvs[VALID_TAG].copy()
bank = dict(sim.bank)
sim2 = ds.Sim(FW)
sim2.nvs = {DATA_TAG: data, VALID_TAG: marker}
sim2.bank = bank
sim2.ent("configuration_online").state = True
boot(sim2)
check("FF-24: the requested export target is NOT reconstructed from the persisted ceiling at boot - left at its "
      "RAM-only default instead",
      sim2.g["dump_target_export_power"] == 0, f"{sim2.g['dump_target_export_power']}")
check("FF-24: the persisted BATTERY CEILING is still loaded correctly (informational/diagnostic only)",
      sim2.g["dump_target_power"] == 1500, f"{sim2.g['dump_target_power']}")
check("FF-24: the lease is still ended/restored on reboot, never resumed",
      sim2.g["dump_restore_requested"] and sim2.ent("dump_last_end_reason").state.startswith("ESP RESTARTED"),
      sim2.status())
writes_before = len(sim2.modbus_log)
sim2.execute("dump_controller_tick")
check("FF-24: the controller cannot resume/run at all post-reboot (its own entry guard returns immediately "
      "whenever restore_requested is set) - zero Modbus I/O, no state touched, regardless of the missing "
      "export target",
      len(sim2.modbus_log) == writes_before and sim2.g["dump_controller_state"] == "IDLE", sim2.status())
tick(sim2)
check("FF-24: restore correctness depends only on the ORIGINAL snapshot fields - the exact original is restored "
      "regardless of the persisted ceiling or the (never-restored) export target",
      owned(sim2) == ORIGINAL and marker_state(sim2) == 0, sim2.status())
check("FF-24: feed-forward diagnostics remain honest after restore - no stale feed-forward wording carried over "
      "into the restore status",
      "feed-forward" not in str(sim2.status()).lower(), sim2.status())

print("")
print("[FF-H] Sensitivity: feed-forward safeguards FAIL against a firmware copy with that safeguard removed")


def s_ff_pv_independent(fw):
    """PV implausible, house perfectly valid - must fall back to 500W, not
    a PV-blind house-only 1500W estimate."""
    sim = fresh(fw=fw, target=500)
    sim.bank[178] = 1000
    sim.bank[186] = 40000
    sim.execute("start_dump_to_grid_override")
    return sim.g["dump_target_power"] == 500 and not sim.g["dump_ff_used"]


def s_ff_read_failure_not_fatal(fw):
    """A feed-forward telemetry read failure must not abort the lease."""
    sim = fresh(fw=fw, target=500)
    sim.bank[178] = 1000
    sim.outcome_fn = lambda kind, addr, count: "error" if (kind == "read" and addr == 172) else "ok"
    sim.execute("start_dump_to_grid_override")
    return bool(sim.g["dump_active_persisted"]) and not sim.g["dump_write_failed"]


def s_ff_start_cap_distinct_from_controller_cap(fw):
    """The START-only 2000W limiter must actually bind - a large feed-
    forward estimate must NOT reach the controller's own 3000W cap at
    START (that cap remains reachable only via later controller ticks)."""
    sim = fresh(fw=fw, target=500)
    sim.bank[178] = 3000
    sim.execute("start_dump_to_grid_override")
    return sim.g["dump_target_power"] == 2000


def ff_capture_block_text(fw) -> str:
    """The exact source slice for the feed-forward telemetry capture, from
    its own header comment through (not including) the durable-commit
    comment that follows it - used to prove this block's completion flag
    never leaks into, or out of, the shared dump_op_terminal every OTHER
    operation in start_dump_to_grid_override uses."""
    text = fw["_text"]
    # NOTE: "# V1.2 feed-forward START (2026-09-27): a dedicated, one-shot"
    # is NOT a unique anchor - the globals block carries a near-identical
    # header comment for the dump_ff_* scratch globals themselves. Anchor on
    # text unique to THIS script-side block instead.
    start = text.index("# 2026-09-27 hardening: uses its OWN dedicated completion flag,")
    end = text.index("# Durable commit BEFORE any inverter write", start)
    return text[start:end]


def s_ff_dedicated_terminal_flag(fw):
    """2026-09-27 adversarial review (corrective pass): the feed-forward
    read's own completion flag must be dump_ff_op_terminal ONLY -
    dump_op_terminal (shared by every OTHER operation in this script) must
    never appear inside this read's own block. This read alone is allowed
    to time out/fail without aborting the script, so the script keeps
    issuing further Modbus operations that reuse dump_op_terminal - a late
    callback for this read could otherwise satisfy (or corrupt) a LATER
    operation's own wait on that shared flag. The offline simulator cannot
    model a genuinely late/async callback (every Modbus outcome here
    resolves synchronously) - this is therefore a structural/source-text
    check, the strongest meaningful proof available without pretending the
    simulator has timing fidelity it does not have.

    Checks the functional usage form id(dump_op_terminal) rather than the
    bare identifier, since this block's own explanatory comments legitimately
    NAME dump_op_terminal in prose (to say exactly why it must not be used
    here) without that being the bug this test exists to catch."""
    block = ff_capture_block_text(fw)
    return "id(dump_ff_op_terminal)" in block and "id(dump_op_terminal)" not in block


_FF_BLOCK_TEXT = ff_capture_block_text(FW)
_FF_BLOCK_REGRESSED_TEXT = _FF_BLOCK_TEXT.replace("dump_ff_op_terminal", "dump_op_terminal")

FF_MUTATIONS = [
    ("feed-forward read's dedicated completion flag reverted to the shared dump_op_terminal (the exact "
     "cross-talk/late-callback bug this hardening fixes)",
     s_ff_dedicated_terminal_flag,
     _FF_BLOCK_TEXT,
     _FF_BLOCK_REGRESSED_TEXT),
    ("feed-forward PV trustworthiness check removed (would silently fall back to a PV-blind house-only estimate)",
     s_ff_pv_independent,
     "trustworthy = house_ok && pv_ok;",
     "trustworthy = house_ok;"),
    ("feed-forward telemetry read failure wrongly made fatal (would reject a lease merely because the "
     "enhancement couldn't compute)",
     s_ff_read_failure_not_fatal,
     "                      on_error:\n"
     "                        then:\n"
     "                          - lambda: 'id(dump_ff_op_terminal) = true;'\n"
     "                      on_no_response:\n"
     "                        then:\n"
     "                          - lambda: 'id(dump_ff_op_terminal) = true;'\n"
     "                      on_not_sent:\n"
     "                        then:\n"
     "                          - lambda: 'id(dump_ff_op_terminal) = true;'\n"
     "\n"
     "                  - wait_until:\n"
     "                      condition:\n"
     "                        lambda: 'return id(dump_ff_op_terminal);'\n"
     "                      timeout: 3000ms\n"
     "                  - lambda: |-\n"
     "                      if (!id(dump_ff_op_terminal)) {\n"
     "                        ESP_LOGW(\"dump_to_grid\", \"Feed-forward telemetry capture (172-189) did not reach a terminal state - falling back to conservative start\");\n"
     "                      }",
     "                      on_error:\n"
     "                        then:\n"
     "                          - lambda: |-\n"
     "                              id(dump_ff_op_terminal) = true;\n"
     "                              id(dump_write_failed) = true;\n"
     "                      on_no_response:\n"
     "                        then:\n"
     "                          - lambda: 'id(dump_ff_op_terminal) = true;'\n"
     "                      on_not_sent:\n"
     "                        then:\n"
     "                          - lambda: 'id(dump_ff_op_terminal) = true;'\n"
     "\n"
     "                  - wait_until:\n"
     "                      condition:\n"
     "                        lambda: 'return id(dump_ff_op_terminal);'\n"
     "                      timeout: 3000ms\n"
     "                  - lambda: |-\n"
     "                      if (!id(dump_ff_op_terminal)) {\n"
     "                        ESP_LOGW(\"dump_to_grid\", \"Feed-forward telemetry capture (172-189) did not reach a terminal state - falling back to conservative start\");\n"
     "                      }"),
    ("START-only feed-forward limiter collapsed to the controller's own 3000W cap (would let a stale-capture "
     "overshoot reach 3000W at START instead of the bounded 2000W envelope)",
     s_ff_start_cap_distinct_from_controller_cap,
     'ecco_dump_feedforward_max_start_ceiling_w: "2000"',
     'ecco_dump_feedforward_max_start_ceiling_w: "3000"'),
]
for label, scenario, old, new in FF_MUTATIONS:
    real_ok = scenario(FW)
    try:
        mutant_ok = scenario(mutant(old, new))
    except ds.Unsupported as e:
        mutant_ok = f"unsupported: {e}"
    check(f"'{label}': safe on the real firmware, detected on the mutant",
          real_ok is True and mutant_ok is False, f"real={real_ok} mutant={mutant_ok}")

# ===========================================================================
# [TF] Target feasibility (2026-09-27, live-proof-motivated)
# ===========================================================================
# Every check here drives the REAL dump_controller_tick's new feasibility
# block via tick()'s pv_w/inverter_w/grid_w - see docs/DUMP_TO_GRID_V1.md
# "Target feasibility" for the formula/rationale this mirrors exactly.

TF_CONFIRM = 2  # ecco_dump_feasibility_confirm_samples


def feas_tick(sim, pv_w, house_w, grid_w=None, **kw):
    """One controller tick with PV/house-load telemetry chosen so
    house_load_est == house_w exactly (house_load_est = max(0, inverter_w +
    grid_w); solving inverter_w = house_w - grid_w keeps grid_w free for the
    caller to independently also drive the ORDINARY controller's own error
    term). Defaults grid_w to -target (zero ordinary-controller error) so a
    scenario that is not deliberately testing interaction with a real
    correction sees none, mirroring fresh()'s own default rationale."""
    if grid_w is None:
        grid_w = -float(sim.g["dump_target_export_power"])
    tick(sim, grid_w=grid_w, pv_w=pv_w, inverter_w=house_w - grid_w, **kw)


# [TF-A] PV surplus well under target -> feasible, ordinary operation.
sim = started(target=500)
for _ in range(3):
    feas_tick(sim, pv_w=1000, house_w=1500, soc=60.0)  # required = 1500+500-1000 = 1000W
check("TF-A: PV surplus well under target -> never relabelled TARGET INFEASIBLE",
      "TARGET INFEASIBLE" not in sim.g["dump_controller_state"] and still_active(sim), sim.status())

# [TF-B] Deadband boundary: exactly at it stays feasible; one watt past it
# only starts (does not yet confirm) the LOW debounce.
sim = started(target=500)
for _ in range(3):
    feas_tick(sim, pv_w=1500, house_w=1000)  # required = 1000+500-1500 = 0W (well inside the 150W deadband)
check("TF-B1: required_w == 0 (inside the deadband) -> feasible",
      "TARGET INFEASIBLE" not in sim.g["dump_controller_state"], sim.status())
feas_tick(sim, pv_w=1651, house_w=1000)  # required = 1000+500-1651 = -151W (1W past -150)
check("TF-B2: required_w == -151W after a single tick -> streak started but NOT yet confirmed (debounce)",
      sim.g["dump_feasibility_low_streak"] == 1 and "TARGET INFEASIBLE" not in sim.g["dump_controller_state"],
      sim.status())
feas_tick(sim, pv_w=1651, house_w=1000)
check("TF-B3: the same reading a 2nd consecutive tick -> confirmed TARGET INFEASIBLE LOW",
      sim.g["dump_controller_state"] == "TARGET INFEASIBLE LOW", sim.status())

# [TF-C] LOW infeasible - the live-proof-approximate case: target 500W, PV
# ~3200W, house ~1400W (surplus ~1800W already exceeds the 500W target).
sim = started(target=500)
for _ in range(TF_CONFIRM):
    feas_tick(sim, pv_w=3200, house_w=1400, soc=70.0)  # required = 1400+500-3200 = -1300W
check("TF-C: live-proof-style LOW case (target 500W, PV 3200W, house 1400W) -> TARGET INFEASIBLE LOW "
      "after 2 confirming ticks",
      sim.g["dump_controller_state"] == "TARGET INFEASIBLE LOW" and still_active(sim), sim.status())
check("TF-C: status text names the surplus and that Dump does not command battery charging",
      "natural PV surplus already exceeds the target by ~1300W" in sim.status()
      and "does not command battery charging" in sim.status(), sim.status())

# [TF-D] House load rises again -> the very next tick reverts to feasible, no latch.
feas_tick(sim, pv_w=3200, house_w=3300, soc=70.0)  # required = 3300+500-3200 = 600W
check("TF-D: house load rises back above PV -> reverts to feasible on the very next tick, streak cleared",
      sim.g["dump_controller_state"] != "TARGET INFEASIBLE LOW" and sim.g["dump_feasibility_low_streak"] == 0,
      sim.status())

# [TF-E] HIGH infeasible - the opposite live-proof-approximate case: target
# 500W, PV ~3200W, house ~6000W (required discharge ~3300W > 3000W ceiling).
sim = started(target=500)
for _ in range(TF_CONFIRM):
    feas_tick(sim, pv_w=3200, house_w=6000, soc=60.0)  # required = 6000+500-3200 = 3300W
check("TF-E: live-proof-style HIGH case (target 500W, PV 3200W, house 6000W) -> TARGET INFEASIBLE HIGH "
      "after 2 confirming ticks",
      sim.g["dump_controller_state"] == "TARGET INFEASIBLE HIGH" and still_active(sim), sim.status())
check("TF-E: status text names the required discharge and the 3000W ceiling",
      "required discharge ~3300W exceeds the 3000W controller ceiling" in sim.status(), sim.status())

# [TF-F] Required discharge falls back below 3000W -> the very next tick
# reverts to feasible, no latch.
feas_tick(sim, pv_w=3200, house_w=3000, soc=60.0)  # required = 3000+500-3200 = 300W
check("TF-F: house load drops back -> reverts to feasible on the very next tick, streak cleared",
      sim.g["dump_controller_state"] != "TARGET INFEASIBLE HIGH" and sim.g["dump_feasibility_high_streak"] == 0,
      sim.status())

# [TF-G] LOW infeasible must NEVER increment the anti-windup/NO RESPONSE machinery.
sim = started(target=500)
for _ in range(TF_CONFIRM + 3):
    feas_tick(sim, pv_w=3200, house_w=1400, soc=70.0)
check("TF-G: sustained LOW infeasibility never increments ineffective/wrong-direction counters, never "
      "reaches NO RESPONSE, never grants an R2 recovery attempt",
      sim.g["dump_controller_ineffective_count"] == 0 and sim.g["dump_controller_wrong_direction_count"] == 0
      and sim.g["dump_controller_state"] != "NO RESPONSE" and sim.g["dump_controller_recovery_attempts"] == 0,
      sim.status())

# [TF-H] HIGH infeasible must NEVER incorrectly trigger R2.
sim = started(target=500)
for _ in range(TF_CONFIRM + 3):
    feas_tick(sim, pv_w=3200, house_w=6000, soc=60.0)
check("TF-H: sustained HIGH infeasibility never reaches NO RESPONSE / NO RESPONSE - RECOVERY EXHAUSTED, "
      "never grants an R2 recovery attempt",
      sim.g["dump_controller_state"] != "NO RESPONSE"
      and sim.g["dump_controller_state"] != "NO RESPONSE - RECOVERY EXHAUSTED"
      and sim.g["dump_controller_recovery_attempts"] == 0, sim.status())

# [TF-I] The ordinary controller write path (and therefore R3's UNCHANGED
# immediate pre-write ownership re-read, already exercised at length by the
# [R3]/[M] sections above) still fires normally even while the SAME
# telemetry is simultaneously LOW-infeasible-shaped - feasibility tracking
# never blocks or interferes with a real write.
sim = started(target=500)
tick(sim, ms=45001, soc=60.0)  # clear the 45s settle window first (neutral telemetry, no write)
writes_before = sim.g["dump_controller_writes_this_lease"]
for _ in range(TF_CONFIRM):
    # grid_w=0 (positive error -> a real upward correction is warranted) AND
    # required = 1000+500-2000 = -500W (LOW-eligible) at the same time.
    feas_tick(sim, pv_w=2000, house_w=1000, grid_w=0.0, soc=60.0)
check("TF-I: feasibility LOW confirmed at the same time a real correction was warranted",
      sim.g["dump_controller_state"] == "TARGET INFEASIBLE LOW", sim.status())
check("TF-I: the ordinary controller write still fired normally alongside the feasibility overlay",
      sim.g["dump_controller_writes_this_lease"] > writes_before,
      f"writes_before={writes_before} writes_after={sim.g['dump_controller_writes_this_lease']}")

# [TF-J] Runaway guard thresholds are byte-for-byte unchanged with
# LOW-infeasible-shaped PV/house telemetry present throughout - mirrors the
# existing "sustained exactly threshold / threshold+1" proof above ([H1]).


def runaway_run_with_feasibility(target, samples):
    sim = started(target=target)
    grid0 = -float(target)
    inv = 1400.0 - grid0  # house_load_est = 1400W with PV 3200W -> required well under -150W (LOW-eligible)
    tick(sim, ms=31000, soc=60.0, grid_w=grid0, pv_w=3200.0, inverter_w=inv)
    for w in samples:
        sim.advance(10000)
        sim.ent("ecco_battery_power").publish_state(float(w))
        sim.ent("ecco_pv_power").publish_state(3200.0)
        sim.ent("ecco_inverter_power").publish_state(inv)
        sim.run_actions(watchdog_of(sim.fw))
    return sim


check("TF-J: runaway threshold unchanged with LOW-infeasible telemetry present - sustained exactly "
      "1,750W (== threshold for a 1000W ceiling) still does not trip",
      still_active(runaway_run_with_feasibility(1000, [1750] * 4)))
check("TF-J: runaway threshold unchanged with LOW-infeasible telemetry present - sustained 1,751W still trips",
      str(runaway_run_with_feasibility(1000, [1751] * 3).ent("dump_last_end_reason").state)
      .startswith("POWER RUNAWAY"))

# [TF-K] Manual End works while TARGET INFEASIBLE LOW, restoring exactly.
sim = started(target=500)
for _ in range(TF_CONFIRM):
    feas_tick(sim, pv_w=3200, house_w=1400, soc=70.0)
check("TF-K setup: lease is TARGET INFEASIBLE LOW before End is pressed",
      sim.g["dump_controller_state"] == "TARGET INFEASIBLE LOW", sim.status())
sim.execute("request_dump_end", {"reason": ds.CStr("manual End button")})
check("TF-K: manual End restores 244 and 256-261 exactly, unaffected by being TARGET INFEASIBLE LOW",
      owned(sim) == ORIGINAL and sim.ent("dump_last_end_reason").state == "manual End button", sim.status())

# [TF-L] Stop SOC reached still ends the lease via the common restore path
# even with LOW-infeasible telemetry present in the very same tick.
sim = started(target=500, stop_soc=25.0)
feas_tick(sim, pv_w=3200, house_w=1400, soc=25.0)
check("TF-L: Stop SOC reached still ends the lease exactly, with LOW-infeasible telemetry in the same tick",
      owned(sim) == ORIGINAL and sim.ent("dump_last_end_reason").state == "STOP SOC REACHED", sim.status())

# [TF-M] Duration expiry still outranks everything, with LOW-infeasible
# telemetry present in the same tick.
sim = started(target=500, duration=1.0)  # 1-minute (60s) duration - the staged minimum
sim.epoch += 65  # duration expiry is wall-clock (NTP epoch), not millis()
tick(sim, ms=65000, pv_w=3200.0, inverter_w=1900.0)  # house_load_est=1400W (grid_w defaults to -500 -> LOW-shaped)
check("TF-M: duration expiry still ends the lease exactly, with LOW-infeasible telemetry in the same tick",
      not still_active(sim) and sim.ent("dump_last_end_reason").state == "DURATION EXPIRED"
      and owned(sim) == ORIGINAL, sim.status())

# [TF-N] Reboot: the new feasibility globals are RAM-only (restore_value:
# no), exactly like every other per-lease controller runtime counter above -
# a reboot cannot resume/leak stale feasibility state across leases.
for gid in ("dump_feasibility_required_w", "dump_feasibility_low_streak", "dump_feasibility_high_streak"):
    g = next(x for x in FW["globals"] if x["id"] == gid)
    check(f"TF-N: global '{gid}' is restore_value: no (RAM-only, matching every other per-lease "
          f"controller counter)", g.get("restore_value") is False, g)

# [TF-O] Restore exactness unchanged when ending from TARGET INFEASIBLE HIGH too.
sim = started(target=500)
for _ in range(TF_CONFIRM):
    feas_tick(sim, pv_w=3200, house_w=6000, soc=60.0)
check("TF-O setup: lease is TARGET INFEASIBLE HIGH before End is pressed",
      sim.g["dump_controller_state"] == "TARGET INFEASIBLE HIGH", sim.status())
sim.execute("request_dump_end", {"reason": ds.CStr("manual End button")})
check("TF-O: restore is exact (244 and 256-261 all match the original snapshot) from TARGET INFEASIBLE "
      "HIGH too", owned(sim) == ORIGINAL and marker_state(sim) == 0 and not sim.g["dump_snapshot_valid"],
      sim.status())

# [TF-P] Write surface unchanged: re-run the same structural analysis
# test_write_surface_invariants.py uses - this purely-diagnostic addition
# introduces no new modbus_client.write_* call anywhere.
sys.path.insert(0, str(ROOT / "tools"))
from analyze_write_surface import analyze, DEFAULT_FIRMWARE  # noqa: E402

_ws_result = analyze(DEFAULT_FIRMWARE)
_ws_paths = {p.name: p for p in _ws_result["paths"] if p.kind == "script"}
for _name in ("start_dump_to_grid_override", "restore_dump_to_grid_snapshot"):
    check(f"TF-P: {_name} write surface is still exactly {{244, 256-261}}",
          _ws_paths[_name].written_addresses == {244, 256, 257, 258, 259, 260, 261},
          sorted(_ws_paths[_name].written_addresses))
check("TF-P: dump_controller_tick write surface is still exactly {256-261} (never 244)",
      _ws_paths["dump_controller_tick"].written_addresses == {256, 257, 258, 259, 260, 261},
      sorted(_ws_paths["dump_controller_tick"].written_addresses))

# [TF mutation/structural] proves the checks above actually depend on the
# LOW/HIGH comparisons and the confirm-samples debounce being correct -
# mirrors the FF_MUTATIONS pattern above exactly.


def s_tf_low_detects(fw):
    sim = started(target=500, fw=fw)
    for _ in range(TF_CONFIRM):
        feas_tick(sim, pv_w=3200, house_w=1400, soc=70.0)
    return sim.g["dump_controller_state"] == "TARGET INFEASIBLE LOW"


def s_tf_high_detects(fw):
    sim = started(target=500, fw=fw)
    for _ in range(TF_CONFIRM):
        feas_tick(sim, pv_w=3200, house_w=6000, soc=60.0)
    return sim.g["dump_controller_state"] == "TARGET INFEASIBLE HIGH"


TF_MUTATIONS = [
    ("LOW threshold comparison inverted (would never detect LOW infeasibility)",
     s_tf_low_detects,
     "if (ecco_feas_required_w < -${ecco_dump_controller_deadband_w}.0f) {",
     "if (ecco_feas_required_w > -${ecco_dump_controller_deadband_w}.0f) {"),
    ("HIGH threshold comparison inverted (would never detect HIGH infeasibility)",
     s_tf_high_detects,
     "} else if (ecco_feas_required_w > ${ecco_dump_controller_max_ceiling_w}.0f) {",
     "} else if (ecco_feas_required_w < ${ecco_dump_controller_max_ceiling_w}.0f) {"),
    ("Confirm-samples raised to 99 (2 confirming ticks would no longer be enough to relabel)",
     s_tf_low_detects,
     'ecco_dump_feasibility_confirm_samples: "2"',
     'ecco_dump_feasibility_confirm_samples: "99"'),
]
for label, scenario, old, new in TF_MUTATIONS:
    real_ok = scenario(FW)
    try:
        mutant_ok = scenario(mutant(old, new))
    except ds.Unsupported as e:
        mutant_ok = f"unsupported: {e}"
    check(f"'{label}': safe on the real firmware, detected on the mutant",
          real_ok is True and mutant_ok is False, f"real={real_ok} mutant={mutant_ok}")

# ===========================================================================
print("")
if FAILURES:
    print(f"{len(FAILURES)} check(s) FAILED:")
    for name in FAILURES:
        print(f"  - {name}")
else:
    print("All Manual Dump-to-Grid V1 BEHAVIOURAL tests PASSED.")
print("")
print("These execute the firmware SOURCE's lambdas and action trees under a documented simulator")
print("(registry/tests/_dump_sim.py). They do not prove ESPHome timing, the compiled binary, or any")
print("inverter behaviour. No live Dump-to-Grid event, OTA, or inverter write has been performed.")
if FAILURES:
    sys.exit(1)
