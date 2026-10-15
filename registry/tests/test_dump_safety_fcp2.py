#!/usr/bin/env python3
"""fcp2: full-capability Dump-to-Grid, phase 2 - safety hardening.

Every behavioural check EXECUTES the real firmware source through registry/tests/_dump_sim.py (the START script, the controller
tick, the restore worker, the battery-power on_value hook and the 15 s watchdog) against an in-memory inverter, and most compare the
fcp2 firmware with the fcp1 firmware it is built on (the chain's exact revert, PEX), so each fix is shown to change the outcome.
It proves the firmware SOURCE's control flow, not ESPHome timing, the compiled binary or the inverter.

  [A] SG-40   no controller write once a lease is ending: End during the pre-write ownership read cancels the write (a raise and a
              ceiling reduction); the re-check after taking the write mutex; nothing written by the controller after END
  [L]         late Modbus callbacks: a reply that arrives after its own timeout never causes a write and never changes a later
              transaction's outcome; no controller or restore transaction starts while the bus is busy
  [R] R-1     the windowed, efficiency-aware runaway guard: never looser than before at or below 3000 W (fixed margin, randomised
              equivalence), the recorded leases replay with no trip, healthy leases at 3-8 kW do not trip, synthetic runaways and
              oscillating faults at 3-8 kW trip within a bound, skipped samples are not "below", latching, grace, transitions,
              a 12 kW profile
  [O] SG-08   the ownership-checked restore: a fresh pre-read of 244-261 before any restore write; ORIGINAL left alone, ECCO's own
              values restored, a FOREIGN value never overwritten (obligation kept, operator decides); no repeat rewrite after a
              verified restore; reboot, comms failure, Force Restore Original
  [T] SG-15/43 frozen telemetry: a CT that repeats exactly while the battery moves (fast) or for 5 minutes (a stuck saturated
      SG-39   reading), battery power that repeats exactly, a SOC that does not move while kWh are discharged - each ends a
              settled lease; healthy noisy leases and the recorded data never trip it; the restore backoff is shortened after a
              genuine link recovery, and only then
  [S] SG-36/07 gated restart (refused during any transaction or owed obligation; override only for an obligation), the
      SG-16   safety census behind ECCO Safe To Flash, build identity, explicit safe mode
  [K] SG-14/42 a lock is never released by time: a STUCK lock (held beyond any transaction's bound) ends an active lease
              durably and, while anything is owed, restarts so the boot path completes it; nothing owed: reported only
  [W]         the independent audit's reproductions as permanent regressions: B1/O2 (FOREIGN + failed 244), R1/S4
              (containment and post-END supervision), R2/D1/D2 (export guard cadence, START export checks), R3/L1 (both limits
              re-confirmed), R4/A1 (Accept residue), F1/R3 (the 800 s oscillating overshoot, no nuisance trips), F3 (idle
              battery, toggling SOC), F4 (stale timer), the quiet-bus restart, and AT1 (the restore under an ASYNCHRONOUS hub)
  [X]         the FINAL rework (Window 7's re-audit of 5178e0f): RF1 (stuck-zero battery telemetry - the grid cross-check, genuine
              idle without nuisance, stale CT, mixed failures, reboot), F5 (immediate, checked persistence of the power limits:
              every flush prefix, failure, flash wear), the Stop SOC across a restart (persisted, bound, fail-closed), R2b
              (alternating export readings), the naming of uncontained FOREIGN settings, and HB1 (every Dump status / recovery
              state within Home Assistant's 255 characters, worst case, every lockout branch)
  [C]         write surface and NVS: no new write, exactly one new read (the pre-read), register 245 never written, every new
              global RAM only except the final rework's one persisted Stop SOC record
  [P]         the post-export declaration (PEX entry fcp2)
"""
from __future__ import annotations

import json
import random
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _dump_sim as ds  # noqa: E402
import _scope_chain as chain  # noqa: E402
import _pex  # noqa: E402

FAILURES: list[str] = []
PASSES = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global PASSES
    if ok:
        PASSES += 1
        print(f"  PASS  {name}")
    else:
        FAILURES.append(name)
        print(f"  FAIL  {name}" + (f" - {detail}" if detail else ""))


FW_PATH = ROOT / "firmware" / "ecco_clock_dongle_stage3_4_free_power.yaml"
FW_TEXT = FW_PATH.read_text(encoding="utf-8")
FW = ds.load_firmware_text(FW_TEXT)
OLD_TEXT = chain.CHAIN.as_of(chain.FIRMWARE, "fcp1", FW_TEXT)    # PEX: fcp2 undone exactly - the fcp1 firmware
OLD = ds.load_firmware_text(OLD_TEXT)
SUBS = FW["_substitutions"]
CAP = int(SUBS["ecco_dump_capability_w"])
FLOOR_W = int(SUBS["ecco_dump_runaway_backstop_floor_w"])
ABS_MARGIN = int(SUBS["ecco_dump_runaway_absolute_margin_w"])
PCT = int(SUBS["ecco_dump_runaway_dc_allowance_pct"])
ORIGINAL = {244: 2, 256: 8000, 257: 8000, 258: 7000, 259: 8000, 260: 8000, 261: 5000}
_WD: dict = {}


def watchdog(fw) -> list:
    if fw["_text"] not in _WD:
        _WD[fw["_text"]] = ds.find_interval(fw, "dump_overpower_samples")
    return _WD[fw["_text"]]


# --- harness (the shape of test_dump_capability_limits.py; kept local - that suite runs on import) ----------------------------------
def config_poll(sim):
    sim.g["cfg_block_b_dispatch_seq"] += 1
    sim.g["manual_cfg_reg244_raw"] = sim.bank.get(244, 0)
    for r in range(256, 262):
        sim.g[f"manual_cfg_reg{r}_raw"] = sim.bank.get(r, 0)
    sim.g["cfg_block_b_seq"] += 1
    sim.g["cfg_block_b_ok_ms"] = sim.millis()
    sim.g["cfg_block_b_response_dispatch_seq"] = sim.g["cfg_block_b_dispatch_seq"]


def fresh(fw=None, target=1000, soc=70.0, grid_w=None, ceiling=None, duration=90.0):
    sim = ds.Sim(fw or FW)
    sim.configure_dump_limits(ceiling if ceiling is not None else int(SUBS["ecco_dump_controller_max_ceiling_w"]), CAP)
    sim.bank.update(ORIGINAL)
    sim.ent("dump_export_power").set(float(target))
    sim.ent("dump_stop_soc").set(25.0)
    sim.ent("dump_duration_minutes").set(float(duration))
    sim.ent("dump_write_enable").state = True
    sim.ent("dump_recovery_arm").state = False
    sim.ent("dump_limits_arm").state = False
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
    sim.ent("ecco_battery_soc").publish_state(soc)
    sim.grid_w = -float(target) if grid_w is None else float(grid_w)
    sim.ent("ecco_grid_ct_power").publish_state(sim.grid_w)
    return sim


def meter(sim):
    """The grid CT as a real meter reports it: 1 W of noise, inside the controller's deadband (a CT that repeats EXACTLY while the
    battery moves is a FROZEN CT - section [T])."""
    sim._meter_n = getattr(sim, "_meter_n", 0) + 1
    return sim.grid_w - (sim._meter_n % 2)


def tick(sim, ms=15000, soc=70.0, battery_w=None):
    """One 15 s watchdog tick with fresh SOC, grid and configuration readback."""
    sim.advance(ms)
    sim.ent("ecco_battery_soc").publish_state(soc)
    if battery_w is not None:
        sim.ent("ecco_battery_power").publish_state(float(battery_w))
    sim.ent("ecco_grid_ct_power").publish_state(meter(sim))
    config_poll(sim)
    sim.run_actions(watchdog(sim.fw))


def started(fw=None, **kw):
    sim = fresh(fw, **kw)
    sim.execute("start_dump_to_grid_override")
    assert sim.g["dump_active_persisted"], sim.status()
    return sim


def force_ceiling(sim, c):
    """The lease commanding exactly c W, as a verified START or controller write leaves it (bank, command, runaway reference)."""
    for r in range(256, 262):
        sim.bank[r] = c
    sim.g["dump_target_power"] = c
    sim.g["dump_runaway_ceiling_ref"] = float(c)
    return sim


def end_reasons(sim):
    return [str(p.get("reason", "")) for i, p in sim.executed if i == "request_dump_end"]


def first_end(sim):
    r = end_reasons(sim)
    return r[0] if r else ""


def owned(sim):
    return {r: sim.bank.get(r) for r in ORIGINAL}


def controller_writes(sim, since=0):
    """256-261 writes that are not the restore's (the restore writes the snapshot's original values)."""
    return [(a, v) for a, v in sim.writes()[since:] if a == 256 and v != [ORIGINAL[r] for r in range(256, 262)]]


# ==================================================================================================================================
print("[A] SG-40: no controller write once a lease is ending")
# ==================================================================================================================================


def end_during_r3(fw, kind="raise"):
    """A lease at 500 W whose controller decides to RAISE the ceiling (grid importing 2000 W against a 500 W export target), or
    (kind="reduce") to step it DOWN because the power ceiling was lowered mid-lease. A manual End arrives while the controller's
    pre-write ownership read (R3) of 256-261 is in flight - modelled by firing request_dump_end at the instant that read is
    dispatched, which is when the End handler can run on the ESP (the controller script is suspended in wait_until)."""
    sim = started(fw, target=500, grid_w=2000.0 if kind == "raise" else -500.0, ceiling=3000)
    if kind == "reduce":
        force_ceiling(sim, 2500)
        sim.g["dump_op_ceiling_w"] = 2000
        sim.g["dump_lease_ceiling_w"] = 2000
    if kind == "raise":
        tick(sim)
        tick(sim)
    real = sim.outcome_fn
    fired = {"n": 0, "writes_before": None}

    def outcome(k, addr, count):
        if k == "read" and addr == 256 and count == 6 and sim.g["dump_active_persisted"] and not fired["n"] \
                and not sim.g["dump_operation_in_progress"]:
            fired["n"] = 1
            fired["writes_before"] = len(sim.writes())
            sim.execute("request_dump_end", {"reason": ds.CStr("manual End button")})
        return real(k, addr, count)
    sim.outcome_fn = outcome
    tick(sim)       # the controller decides to write (raise: the settle window has elapsed; reduce: at once); End arrives during R3
    return sim, fired


sim, fired = end_during_r3(FW)
after_end = sim.writes()[fired["writes_before"]:] if fired["writes_before"] is not None else None
check("End during the pre-write ownership read of a RAISE: the raise is CANCELLED - no 256-261 write after the End request",
      fired["n"] == 1 and after_end == [] and sim.g["dump_target_power"] == 500 and sim.bank[256] == 500,
      f"fired={fired} after_end={after_end} target={sim.g['dump_target_power']}")
check("...the mutex is released, the controller says why, and the status stays the restore's END DEFERRED (never ACTIVE)",
      not sim.g["manual_write_in_progress"] and sim.g["dump_controller_state"] == "WRITE CANCELLED - LEASE ENDING"
      and "END DEFERRED" in sim.status() and "ACTIVE" not in sim.status(), f"{sim.g['dump_controller_state']} | {sim.status()}")
check("...the save-before-write evidence (committed BEFORE the ownership read) still names the cancelled 1500 W as possibly "
      "landed - an over-cover by design (Dump V2); the verified command stays 500 W",
      sim.g["dump_evidence_pending_ceiling"] == 1500 and sim.g["dump_target_power"] == 500
      and sim.nvs["ecco_dump_to_grid_snapshot_data_v2"].reg_dump_power_pending == 1500, str(sim.g["dump_evidence_pending_ceiling"]))
tick(sim)
check("...the next watchdog tick restores the ORIGINAL settings and clears the obligation", owned(sim) == ORIGINAL
      and not sim.g["dump_snapshot_valid"] and "RESTORED OK" in sim.status(), sim.status())
osim, ofired = end_during_r3(OLD)
check("the same race on the fcp1 firmware WRITES the raise after End was requested (SG-40 reproduced; fixed above)",
      ofired["n"] == 1 and any(a == 256 and v[0] > 500 for a, v in osim.writes()[ofired["writes_before"]:]),
      str(osim.writes()[ofired["writes_before"]:]))

sim, fired = end_during_r3(FW, kind="reduce")
after_end = sim.writes()[fired["writes_before"]:] if fired["writes_before"] is not None else None
check("End during the ownership read of a mid-lease CEILING REDUCTION: also cancelled (the restore, not the controller, writes)",
      fired["n"] == 1 and after_end == [] and sim.g["dump_controller_state"] == "WRITE CANCELLED - LEASE ENDING",
      f"{fired} {after_end} {sim.g['dump_controller_state']}")
tick(sim)
check("...and the restore returns the ORIGINAL settings", owned(sim) == ORIGINAL, str(owned(sim)))

# The re-check right after the mutex is taken: run the tick's write branch directly with each "not live" condition.
TICK = FW["script"][[s["id"] for s in FW["script"]].index("dump_controller_tick")]["then"]
WRITE_BRANCH = next(a for a in TICK if "if" in a and "dump_controller_needs_write" in a["if"]["condition"]["lambda"]
                    and "!id(dump_controller_fail_closed)" in a["if"]["condition"]["lambda"])
for label, setup in (("End requested", {"dump_restore_requested": True}),
                     ("lease no longer active", {"dump_active_persisted": False}),
                     ("a restore running", {"dump_operation_in_progress": True}),
                     ("recovery metadata corrupt", {"dump_recovery_metadata_corrupt": True}),
                     ("obligation marker not RESTORE_REQUIRED", {"dump_marker_state": 2})):
    s = started(target=500)
    force_ceiling(s, 500)
    tick(s)
    n_w, n_r, n_c = len(s.writes()), len([m for m in s.modbus_log if m[0] == "read"]), len(s.nvs_commits)
    s.g.update(setup)
    s.g["dump_controller_needs_write"] = True
    s.g["dump_controller_fail_closed"] = False
    s.g["dump_controller_pending_ceiling"] = 1500
    s.run_actions([WRITE_BRANCH])
    check(f"write mutex taken, then '{label}' is seen: no evidence commit, no read, no write; mutex released",
          len(s.writes()) == n_w and len([m for m in s.modbus_log if m[0] == "read"]) == n_r and len(s.nvs_commits) == n_c
          and not s.g["manual_write_in_progress"] and s.g["dump_controller_write_cancelled"],
          f"w {len(s.writes()) - n_w} r {len([m for m in s.modbus_log if m[0] == 'read']) - n_r} c {len(s.nvs_commits) - n_c}")

# After END, with the restore deferred by a busy bus for many ticks and a large grid error, the controller writes nothing.
sim = started(target=500, grid_w=2500.0)
tick(sim)
sim.execute("request_dump_end", {"reason": ds.CStr("manual End button")})
n0 = len(sim.writes())
for _ in range(3):
    sim.g["manual_write_in_progress"] = True        # another writer holds the bus: the restore keeps deferring
    tick(sim)
    sim.g["manual_write_in_progress"] = False
    sim.bus_idle = False
    tick(sim)
    sim.bus_idle = True
check("after END, 6 deferred ticks with a 3 kW grid error: ZERO controller writes; then the restore completes",
      controller_writes(sim, n0) == [] and sim.g["dump_target_power"] == 500, str(sim.writes()[n0:]))
tick(sim)
check("...restored to ORIGINAL once the bus is free", owned(sim) == ORIGINAL and "RESTORED OK" in sim.status(), sim.status())

# ==================================================================================================================================
print("\n[L] late Modbus callbacks")
# ==================================================================================================================================


def capture_lost(sim, kind, addr, count):
    """Make the next matching operation get NO callback (its wait times out) and keep its node, so the test can deliver the reply
    LATE, at any later moment, exactly as the hub would."""
    store = []
    orig_r, orig_w, orig_out = sim._modbus_read, sim._modbus_write, sim.outcome_fn
    armed = {"on": True}

    def out(k, a, c):
        if armed["on"] and k == kind and a == addr and c == count:
            armed["on"] = False
            return "lost" if k == "read" else "timeout_landed"
        return orig_out(k, a, c)

    def rd(body, local):
        if armed["on"] and kind == "read" and int(body["start_address"]) == addr:
            store.append((body, dict(local or {})))
        orig_r(body, local)

    def wr(body, local):
        if armed["on"] and kind == "write" and int(body["start_address"]) == addr:
            store.append((body, dict(local or {})))
        orig_w(body, local)
    sim.outcome_fn, sim._modbus_read, sim._modbus_write = out, rd, wr
    return store


sim = started(target=500, grid_w=2000.0)
tick(sim)
tick(sim)
lost = capture_lost(sim, "read", 256, 6)
n0 = len(sim.writes())
tick(sim)                                   # R3 gets no reply: timeout
check("the ownership read times out (no reply): no controller write; the lease ends 'OWNERSHIP RE-READ FAILED'",
      len(lost) == 1 and controller_writes(sim, n0) == [] and first_end(sim).startswith("CONTROLLER OWNERSHIP RE-READ FAILED"),
      f"{len(lost)} {sim.writes()[n0:]} {first_end(sim)}")
state = (dict(sim.bank), sim.g["dump_target_power"], sim.g["dump_snapshot_valid"], sim.status())
body, local = lost[0]
sim._handler(body, "on_response", local, [500] * 6)       # the reply arrives late, after the restore
check("...its reply delivered LATE changes nothing: no write, same bank, same command, same obligation state and status",
      controller_writes(sim, n0) == [] and (dict(sim.bank), sim.g["dump_target_power"], sim.g["dump_snapshot_valid"], sim.status()) == state)

sim = started(target=500, grid_w=2000.0)
tick(sim)
tick(sim)
lost = capture_lost(sim, "write", 256, 6)
tick(sim)                                   # the controller's write lands but its reply never comes: timeout, END, restore
check("a controller write whose reply never comes ends the lease and the restore returns the ORIGINAL settings",
      len(lost) == 1 and owned(sim) == ORIGINAL and first_end(sim).startswith("CONTROLLER WRITE VERIFY MISMATCH")
      and "RESTORED OK" in sim.status(), f"{first_end(sim)} | {sim.status()} | {owned(sim)}")
body, local = lost[0]
sim._handler(body, "on_response", local)
check("...its ACK delivered late changes nothing (no write, ORIGINAL kept, obligation still clear)",
      owned(sim) == ORIGINAL and not sim.g["dump_snapshot_valid"] and "RESTORED OK" in sim.status())

# A late controller ACK arriving INSIDE the restore's own transaction does not complete or corrupt the restore's waits (it has its own
# terminal flag): deliver it while the restore's 244 write is in flight.
sim = started(target=500, grid_w=2000.0)
tick(sim)
tick(sim)
lost = capture_lost(sim, "write", 256, 6)
real = sim.outcome_fn
injected = {"n": 0}


def late_into_restore(k, a, c):
    if k == "write" and a == 244 and lost and not injected["n"]:
        injected["n"] = 1
        b, l = lost[0]
        sim._handler(b, "on_response", l)
    return real(k, a, c)


sim.outcome_fn = late_into_restore
tick(sim)
check("a late controller ACK delivered during the restore's own 244 write: the restore still completes and VERIFIES normally",
      injected["n"] == 1 and owned(sim) == ORIGINAL and "RESTORED OK" in sim.status(), sim.status())

for label, setup in (("the hub has a command queued", {"bus_idle": False}),):
    s = started(target=500, grid_w=2000.0)
    tick(s)
    tick(s)
    n0 = len(s.modbus_log)
    s.bus_idle = False
    tick(s)
    check(f"while {label}, the controller starts no transaction (so no reply can cross into one): deferred, no Modbus op",
          len(s.modbus_log) == n0, str(s.modbus_log[n0:]))
    s.execute("request_dump_end", {"reason": ds.CStr("manual End button")})
    check(f"...and the restore starts none either: END DEFERRED", len(s.modbus_log) == n0 and "END DEFERRED" in s.status(), s.status())

# ==================================================================================================================================
print("\n[R] R-1: windowed, efficiency-aware runaway guard")
# ==================================================================================================================================


def at_level(c, fw=None):
    """A lease configured for the full profile capability, commanding exactly c W, past the 30 s lease-start grace."""
    s = started(fw, target=1000, ceiling=CAP)
    force_ceiling(s, c)
    tick(s, ms=31000)
    return s


def feed(s, samples, period_ms=10000, wd_ms=15000):
    """Battery samples every period_ms and the watchdog every wd_ms on one clock (the real 10 s poll and 15 s watchdog), with fresh
    SOC/grid/config at each watchdog tick. None = a SKIPPED poll (no publish). Returns the time, in seconds from the first
    sample, of the watchdog tick that first ended the lease for a runaway, or None."""
    t, next_s, next_w, i = 0, period_ms, wd_ms, 0
    while i < len(samples):
        if next_s <= next_w:
            s.advance(next_s - t)
            t = next_s
            if samples[i] is not None:
                s.ent("ecco_battery_power").publish_state(float(samples[i]))
            i += 1
            next_s += period_ms
        else:
            s.advance(next_w - t)
            t = next_w
            n = len(end_reasons(s))
            s.ent("ecco_battery_soc").publish_state(70.0)
            s.ent("ecco_grid_ct_power").publish_state(meter(s))
            config_poll(s)
            s.run_actions(watchdog(s.fw))
            if len(end_reasons(s)) > n and "RUNAWAY" in end_reasons(s)[n]:
                return (t - period_ms) / 1000.0
            next_w += wd_ms
    for _ in range(2):                       # let the watchdog see the last samples
        s.advance(wd_ms)
        t += wd_ms
        n = len(end_reasons(s))
        s.ent("ecco_battery_soc").publish_state(70.0)
        s.ent("ecco_grid_ct_power").publish_state(meter(s))
        config_poll(s)
        s.run_actions(watchdog(s.fw))
        if len(end_reasons(s)) > n and "RUNAWAY" in end_reasons(s)[n]:
            return (t - period_ms) / 1000.0
    return None


def abs_thr(c):
    ref = max(c, min(CAP, FLOOR_W))
    return ref + ABS_MARGIN + max(0, ref - FLOOR_W) * PCT / 100.0


check(f"the backstop margin is EXACTLY the fixed {ABS_MARGIN} W at every command up to {FLOOR_W} W (never looser than before)",
      all(abs_thr(c) == max(c, FLOOR_W) + ABS_MARGIN for c in range(500, FLOOR_W + 1, 100)))
check(f"above {FLOOR_W} W it grows by the profile's {PCT} % DC allowance of the command above it: 8000 W -> {abs_thr(8000):.0f} W",
      abs_thr(8000) == 8000 + ABS_MARGIN + 0.12 * 5000)
for c in (3000, 4000, 8000):
    s = at_level(c)
    thr = abs_thr(c)
    feed(s, [thr - 1, thr - 1, thr - 1, thr - 1])
    a = first_end(s) == ""
    s = at_level(c)
    feed(s, [thr + 1, thr + 1])
    check(f"{c} W: sustained exactly at the backstop ({thr:.0f} W) never trips; 1 W above it twice in a row trips",
          a and "ABSOLUTE POWER RUNAWAY" in first_end(s), first_end(s))

import yaml  # noqa: E402
REG = yaml.safe_load((ROOT / "registry" / "inverter_profiles.yaml").read_text(encoding="utf-8"))
ref = next(p for p in REG["profiles"] if p["id"] == SUBS["ecco_inverter_profile_id"])
check("the DC allowance is a PROFILE value: the registry's reference entry carries it and matches the firmware; every registry "
      "profile's value is within the compile-time 0-30 % range",
      str(ref["substitutions"]["ecco_dump_runaway_dc_allowance_pct"]) == SUBS["ecco_dump_runaway_dc_allowance_pct"]
      and all(0 <= int(p["substitutions"].get("ecco_dump_runaway_dc_allowance_pct", 0)) <= 30 for p in REG["profiles"]))

# Randomised equivalence: on any sample sequence the fcp1 firmware trips on, fcp2 trips at the same sample or earlier (<= 3000 W).
rng = random.Random(20261013)
worse = []
for trial in range(120):
    c = rng.choice((500, 1000, 2000, 3000))
    lo, hi = c * 0.9, max(c, FLOOR_W) + ABS_MARGIN * 2.2 + c * 0.6
    seq = [rng.choice((rng.uniform(lo, c * 1.15), rng.uniform(lo, hi), rng.uniform(lo, hi))) for _ in range(10)]
    old_i = feed(at_level(c, OLD), seq, wd_ms=10000)
    new_i = feed(at_level(c), seq, wd_ms=10000)
    if old_i is not None and (new_i is None or new_i > old_i):
        worse.append((c, [round(x) for x in seq], old_i, new_i))
check("120 random sequences at 500-3000 W: wherever the fcp1 guard trips, fcp2 trips at the same tick or earlier", worse == [],
      str(worse[:2]))

# Replay of the three recorded healthy leases (sanitised fixture).
FIX = json.loads((ROOT / "registry/tests/fixtures/dump_lease_residuals_fcp2.json").read_text(encoding="utf-8"))


def replay(fw, lease, scale_to=None):
    """Replay one recorded lease: its battery samples against its own commands (a verified controller write at each command change),
    or (scale_to=c) the 3000 W part scaled so the command is c and the residual grows in proportion (the DC/AC loss model)."""
    s = started(fw, target=1000, ceiling=CAP)
    rows = lease["samples"]
    if scale_to:
        rows = [(t, scale_to, scale_to + (b - c_w) * scale_to / c_w) for t, c_w, b in rows if c_w == 3000]
    force_ceiling(s, int(rows[0][1]))
    tick(s, ms=31000)
    seq = []
    prev = rows[0][1]
    for t, c, b in rows:
        if c != prev:
            s.g["dump_runaway_ceiling_ref"] = float(max(prev, c))
            s.g["dump_target_power"] = int(c)
            s.g["dump_last_controller_update_ms"] = s.millis()
            for r in range(256, 262):
                s.bank[r] = int(c)
            prev = c
        seq.append(b)
        if feed(s, [b], wd_ms=15000) is not None:
            return s, True
    return s, False


trips = [lease["lease"] for lease in FIX["leases"] if replay(FW, lease)[1]]
check(f"the {len(FIX['leases'])} recorded leases ({sum(len(x['samples']) for x in FIX['leases'])} samples at 2000-3000 W, residual "
      "+228..+357 W) replay with NO runaway trip", trips == [], str(trips))
res3000 = [b - c for lease in FIX["leases"] for t, c, b in lease["samples"] if c == 3000]
for c in (3000, 4000, 5000, 6000, 7000, 8000):
    new_trip = [x["lease"] for x in FIX["leases"] if replay(FW, x, scale_to=c)[1]]
    old_trip = [x["lease"] for x in FIX["leases"] if replay(OLD, x, scale_to=c)[1]]
    worst = c + max(res3000) * c / 3000
    check(f"healthy at {c} W (recorded 3000 W residuals scaled in proportion, worst {worst:.0f} W vs backstop {abs_thr(c):.0f} W): "
          f"no trip" + (f" - the fcp1 fixed margin WOULD nuisance-trip (leases {old_trip})" if old_trip else ""),
          new_trip == [], str(new_trip))
for c in (3000, 4000, 5000, 6000, 7000, 8000):
    pess = [c * (1 + PCT / 100.0) + 100.0 + (8 if i % 2 else -8) for i in range(10)]
    check(f"healthy at {c} W under a pessimistic loss model ({PCT} % + 100 W, +/-8 W noise): no trip",
          feed(at_level(c), pess) is None)

# Synthetic runaways and oscillating faults at every operating level.
for c in (3000, 4000, 5000, 6000, 7000, 8000):
    thr = abs_thr(c)
    healthy = c * 1.10
    gross = thr + ABS_MARGIN + max(0, c - FLOOR_W) * PCT / 100.0          # the backstop plus one more (scaled) margin
    old_nuisance = feed(at_level(c, OLD), [healthy] * 8) is not None
    i_step = feed(at_level(c), [thr + 200] * 6)
    cross = next(k for k in range(40) if healthy + 300 * k > thr)
    i_ramp = feed(at_level(c), [healthy + 300 * k for k in range(20)])
    osc = [thr + 100 if k % 2 == 0 else healthy for k in range(20)]
    i_osc_new, i_osc_old = feed(at_level(c), osc), feed(at_level(c, OLD), osc)
    big = [gross + 500 if k % 3 == 0 else healthy for k in range(20)]
    i_big_new, i_big_old = feed(at_level(c), big), feed(at_level(c, OLD), big)
    old_txt = ("fcp1 trips on the HEALTHY samples already" if old_nuisance else
               "fcp1: never" if i_osc_old is None and i_big_old is None else "fcp1 trips too")
    check(f"{c} W: a step runaway to {thr + 200:.0f} W ends the lease at the first watchdog tick after its 2nd sample (<= 35 s)",
          i_step is not None and i_step <= 35, str(i_step))
    check(f"{c} W: a ramp (+300 W per 10 s sample from {healthy:.0f} W) ends within 35 s of crossing the backstop",
          i_ramp is not None and i_ramp <= cross * 10 + 35, f"{i_ramp} cross {cross * 10}")
    check(f"{c} W: 50 % duty oscillation just above the backstop ends the lease within 95 s ({old_txt})",
          i_osc_new is not None and i_osc_new <= 95 and (old_nuisance or i_osc_old is None), f"new {i_osc_new} old {i_osc_old}")
    check(f"{c} W: 1-in-3 duty excursions above the gross level ({gross + 500:.0f} W) end the lease within 95 s ({old_txt})",
          i_big_new is not None and i_big_new <= 95 and (old_nuisance or i_big_old is None), f"new {i_big_new} old {i_big_old}")

c = 3000
thr = abs_thr(c)
check("documented tolerance: a 1-in-4 duty overshoot less than one margin above the backstop does not trip (bounded: below "
      "half duty and below the gross level)", feed(at_level(c), [thr + 100 if k % 4 == 0 else c * 1.1 for k in range(24)]) is None)
check("two isolated gross spikes in 8 samples do not trip (a single glitch pair is tolerated; a third trips)",
      feed(at_level(c), [8600, 3300, 3300, 8600, 3300, 3300, 3300, 3300]) is None
      and feed(at_level(c), [8600, 3300, 8600, 3300, 8600]) is not None)

# Skipped / NaN samples are not "below".
seq = [thr + 100, None, None, thr + 100]
check("a SKIPPED poll between two backstop samples does not reset the run: trips (the history does not advance)",
      feed(at_level(c), seq) is not None)
seq = [thr + 100, float("nan"), thr + 100]
check("a NaN reading between two backstop samples is not 'below': fcp2 trips; the fcp1 counter reset on it and did not",
      feed(at_level(c), seq) is not None and feed(at_level(c, OLD), seq) is None)

# Latching: two backstop samples between watchdog ticks, then a normal one before the tick.
def between_ticks(fw):
    s = at_level(c, fw)
    for dt, w in ((2000, thr + 100), (6000, thr + 100), (4000, 3300)):
        s.advance(dt)
        s.ent("ecco_battery_power").publish_state(float(w))
    s.advance(3000)
    s.ent("ecco_battery_soc").publish_state(70.0)
    s.ent("ecco_grid_ct_power").publish_state(meter(s))
    config_poll(s)
    s.run_actions(watchdog(s.fw))
    return first_end(s)


check("two backstop samples complete a run BETWEEN two watchdog ticks and a normal sample follows: fcp2's latched decision ends "
      "the lease; the fcp1 counter had already reset and missed it",
      "ABSOLUTE POWER RUNAWAY (windowed)" in between_ticks(FW) and between_ticks(OLD) == "", f"{between_ticks(FW)!r}")

s = started(target=1000, ceiling=CAP)
force_ceiling(s, 3000)
feed(s, [9000, 9000])            # inside the 30 s lease-start grace
check("lease-start grace: samples in the first 30 s are not recorded", first_end(s) == "" and s.g["dump_runaway_win_abs"] == 0)

s = at_level(5000)
s.g["dump_runaway_ceiling_ref"] = 5000.0
s.g["dump_target_power"] = 3000
s.g["dump_last_controller_update_ms"] = s.millis()
for r in range(256, 262):
    s.bank[r] = 3000
check("a verified step-down 5000 -> 3000 W: the battery still near the old command for 20 s is judged against the old one "
      "(no trip)", feed(s, [5600, 5600]) is None)

s = started(target=1000, ceiling=CAP)
force_ceiling(s, 3000)
tick(s, ms=31000)
feed(s, [thr + 100] * 2)
s2 = started(target=1000, ceiling=CAP)
check("a new lease starts with a clear history and no latched decision",
      s2.g["dump_runaway_trip"] == 0 and s2.g["dump_runaway_win_abs"] == 0)

big_text = FW_TEXT.replace('ecco_inverter_tou_power_ceiling_w: "8000"', 'ecco_inverter_tou_power_ceiling_w: "12000"', 1) \
                  .replace('ecco_dump_capability_w: "8000"', 'ecco_dump_capability_w: "12000"', 1)
BIG = ds.load_firmware_text(big_text)
big_thr = 12000 + ABS_MARGIN + (12000 - FLOOR_W) * PCT / 100.0


def big_level(samples):
    b = ds.Sim(BIG)
    b.configure_dump_limits(12000, 12000)
    b.bank.update(ORIGINAL)
    for k, v in (("dump_export_power", 1000.0), ("dump_stop_soc", 25.0), ("dump_duration_minutes", 90.0), ("ecco_battery_voltage", 52.0)):
        b.ent(k).set(v)
    b.ent("dump_write_enable").state = True
    b.ent("dump_recovery_arm").state = False
    b.ent("configuration_online").state = True
    b.ent("configuration_polling").state = True
    b.g["ntp_synced"] = True
    for i, t in enumerate([0, 530, 800, 1600, 1900, 2330]):
        b.g[f"manual_cfg_reg{250 + i}_raw"] = t
    for i, f in enumerate([1, 0, 0, 0, 0, 0]):
        b.g[f"manual_cfg_reg{274 + i}_raw"] = f
    config_poll(b)
    b.ent("ecco_battery_soc").publish_state(70.0)
    b.grid_w = -1000.0
    b.ent("ecco_grid_ct_power").publish_state(b.grid_w)
    b.execute("start_dump_to_grid_override")
    force_ceiling(b, 12000)
    tick(b, ms=31000)
    return feed(b, samples)


check(f"a 12 kW profile: the backstop scales with it ({big_thr:.0f} W at 12000 W; no hidden 8000 W cap) - healthy "
      f"{12000 * 1.12 + 100:.0f} W does not trip, {big_thr + 200:.0f} W does",
      big_level([12000 * 1.12 + 100] * 6) is None and big_level([big_thr + 200] * 3) is not None)

# ==================================================================================================================================
print("\n[O] SG-08 / SG-29c: the ownership-checked restore")
# ==================================================================================================================================
VALID = "ecco_dump_to_grid_snapshot_valid_v1"
RETRY = "ecco_dump_to_grid_retry_state_v1"


def marker(sim):
    rec = sim.nvs.get(VALID)
    return None if rec is None else rec.state


def end(sim, reason="manual End button"):
    n = len(sim.modbus_log)
    sim.execute("request_dump_end", {"reason": ds.CStr(reason)})
    return sim.modbus_log[n:]


def restore_ops(log):
    return [(k, a, (len(v) if k == "read" else v)) for k, a, v, o in log]


sim = started(target=1000)
ops = restore_ops(end(sim))
check("a normal End: the restore READS 244-261 first (one 18-register read), then writes 244 and 256-261 back, verified",
      ops[0] == ("read", 244, 18)
      and [o for o in ops if o[0] == "write"] == [("write", 244, [2]), ("write", 256, [8000, 8000, 7000, 8000, 8000, 5000])]
      and owned(sim) == ORIGINAL and marker(sim) == 0 and "RESTORED OK" in sim.status(), f"{ops} | {sim.status()}")
oops = restore_ops(end(started(OLD, target=1000)))
check("...the fcp1 restore wrote blind (no pre-read)", oops[0][0] == "write", str(oops[:2]))

sim = started(target=1000)
sim.bank.update(ORIGINAL)
ops = restore_ops(end(sim))
check("everything already ORIGINAL (e.g. reverted by hand): the restore writes NOTHING and clears the obligation",
      [o for o in ops if o[0] == "write"] == [] and marker(sim) == 0 and "RESTORED OK" in sim.status(), f"{ops} {sim.status()}")

sim = started(target=1000)
sim.bank.update({256: 8000, 257: 8000})      # two registers already back at their ORIGINAL, four still at ECCO's ceiling
ops = restore_ops(end(sim))
check("a mix of ORIGINAL and ECCO's own ceiling (no foreign value): the block is written back, verified", owned(sim) == ORIGINAL
      and marker(sim) == 0 and any(o[1] == 256 and o[0] == "write" for o in ops), sim.status())

for label, fw in (("fcp2", FW), ("fcp1", OLD)):
    s = started(fw, target=1000)
    s.bank[258] = 6500                         # an external change during the lease (the app, the front panel, another master)
    config_poll(s)
    tick(s)                                    # the passive drift check ends the lease; the restore runs
    if label == "fcp2":
        check("an EXTERNAL change to 258 during the lease: the drift END turns export off (244 was ECCO's), ECCO's OWN five slots "
              "are restored one register at a time, 258's 6500 W is KEPT, the obligation is kept and the operator is asked (durably)",
              s.bank[258] == 6500 and s.bank[244] == ORIGINAL[244] and s.bank[256] == ORIGINAL[256] and s.bank[261] == ORIGINAL[261]
              and marker(s) == 1 and s.g["dump_operator_needed"] and s.nvs[RETRY].operator_needed == 1
              and s.status().startswith("OPERATOR DECISION REQUIRED - ECCO's own settings restored and verified; external "
                                        "change NOT overwritten")
              and "register 258 reads 6500W" in s.status()
              and str(s.ent("dump_recovery_state").state).startswith("FOREIGN (not overwritten)"), s.status())
        n = len(s.modbus_log)
        for _ in range(4):
            tick(s)
        check("...and no further automatic Modbus I/O while the operator decides", len(s.modbus_log) == n)
        s.ent("dump_recovery_arm").state = True
        s.execute("dump_force_restore_original")
        check("Force Restore Original (armed operator decision) then writes the ORIGINAL snapshot over it and clears",
              owned(s) == ORIGINAL and marker(s) == 0, s.status())
    else:
        check("...the fcp1 restore OVERWROTE the external 6500 W with the stale snapshot (SG-08 reproduced)", s.bank[258] == 7000)

s = started(target=1000)
s.bank[244] = 1                                # 244 changed externally to Essentials (not exporting)
end(s)
check("244 changed externally (Essentials): left as is; ECCO's own 256-261 ceiling IS restored; operator asked",
      s.bank[244] == 1 and all(s.bank[r] == ORIGINAL[r] for r in range(256, 262)) and marker(s) == 1 and s.g["dump_operator_needed"]
      and "register 244 reads 1" in s.status(), s.status())

s = started(target=1000)
s.g["dump_evidence_pending_ceiling"] = 1500    # a write that may have landed (an over-covered cancelled write, a power cut)
s.bank.update({r: 1500 for r in range(256, 262)})
end(s)
check("the possibly-landed PENDING ceiling is ECCO's own (Dump V2 evidence): restored, not treated as foreign",
      owned(s) == ORIGINAL and marker(s) == 0, s.status())

# Duplicate restoration: a verified restore whose durable completion failed is retried with ZERO writes; a change made after it is kept.
for label, fw in (("fcp2", FW), ("fcp1", OLD)):
    s = started(fw, target=1000)
    s.nvs_fail_next[VALID] = 1                 # the PENDING_CLEAR commit after the verified restore fails
    end(s)
    first_ok = owned(s) == ORIGINAL and marker(s) == 1
    n = len(s.writes())
    tick(s)
    retry_writes = s.writes()[n:]
    s2 = started(fw, target=1000)
    s2.nvs_fail_next[VALID] = 1
    end(s2)
    s2.bank[259] = 6000                       # the owner adjusts 259 after the (verified) restore
    tick(s2)
    if label == "fcp2":
        check("a verified restore whose durable clear failed: the retry re-reads, finds ORIGINAL and writes NOTHING, then clears",
              first_ok and retry_writes == [] and marker(s) == 0 and "RESTORED OK" in s.status(), f"{retry_writes} {s.status()}")
        check("...and a change the owner made in between is KEPT (foreign: not overwritten, operator asked)",
              s2.bank[259] == 6000 and marker(s2) == 1 and s2.g["dump_operator_needed"], s2.status())
    else:
        check("...the fcp1 retry REWROTE 244 and 256-261 blind and overwrote the owner's later change (duplicate restoration)",
              first_ok and len(retry_writes) == 2 and s2.bank[259] == 8000, str(retry_writes))

# The pre-read failing: nothing is written, the obligation stays, the comms backoff applies, and it completes once comms return.
for outcome, label in (("error", "an error reply"), ("lost", "no reply (timeout)")):
    s = started(target=1000)
    real = s.outcome_fn
    s.outcome_fn = lambda k, a, c, real=real, outcome=outcome: outcome if (k == "read" and a == 244 and c == 18) else real(k, a, c)
    ops = restore_ops(end(s))
    check(f"the pre-read gets {label}: ZERO writes, obligation kept, retried with comms backoff",
          [o for o in ops if o[0] == "write"] == [] and marker(s) == 1 and not s.g["dump_operator_needed"]
          and s.g["dump_comms_restore_attempts"] == 1 and "RESTORE WRITE FAILED" in s.status(), f"{ops} {s.status()}")
    s.outcome_fn = real
    for _ in range(3):
        tick(s, ms=30000)
    check("...once comms return, the restore completes", owned(s) == ORIGINAL and marker(s) == 0, s.status())


# Reboot mid-lease: the boot path ends the lease and the same ownership-checked restore runs.
def _boot_text(fw):
    return fw["esphome"]["on_boot"]["then"][0]["lambda"]


def reboot(sim, bank_update=None):
    """A power cut now, then a fresh boot of the same firmware: new RAM, the same durable store and inverter, the real Dump boot block
    and arbitration block, then the 15 s watchdog."""
    b = ds.Sim(sim.fw)
    b.configure_dump_limits(int(SUBS["ecco_dump_controller_max_ceiling_w"]), CAP)
    b.ent("configuration_online").state = True
    b.ent("configuration_polling").state = True
    b.ent("dump_write_enable").state = False
    b.ent("dump_recovery_arm").state = False
    b.nvs = {k: v.copy() for k, v in sim.nvs.items()}
    b.bank = dict(sim.bank)
    b.bank.update(bank_update or {})
    boot = _boot_text(b.fw)
    s0 = boot.index("// Manual Dump-to-Grid V1 (2026-09-26) - same fail-closed marker/")
    e0 = boot.index('id(dump_status).publish_state("Inactive");', s0)
    b.run_lambda(boot[s0:boot.index("}", e0) + 1])
    s1 = boot.index("// S4 fix (2026-09-27")
    b.run_lambda(boot[s1:boot.index("if (id(free_power_recovery_metadata_corrupt)) {", s1)])
    b.grid_w = 0.0
    return b


s = started(target=1000)
b = reboot(s)
tick(b)
check("a power cut mid-lease, then boot: the forced end runs the ownership-checked restore - ECCO's ceiling and Allow Export are "
      "restored, verified, obligation cleared", owned(b) == ORIGINAL and marker(b) == 0, b.status())
s = started(target=1000)
b = reboot(s, {257: 4321})
tick(b)
check("...and a value changed while the dongle was down is KEPT (no blind boot restore): operator asked, obligation kept",
      b.bank[257] == 4321 and b.bank[244] == ORIGINAL[244] and marker(b) == 1 and b.g["dump_operator_needed"], b.status())

# ==================================================================================================================================
print("\n[T] SG-15 / SG-43 / SG-39: frozen telemetry and the restore backoff after a genuine recovery")
# ==================================================================================================================================
N_FROZEN = int(SUBS["ecco_dump_frozen_samples"])
N_LONG = int(SUBS["ecco_dump_frozen_ct_long_samples"])
SOC_WH = int(SUBS["ecco_dump_soc_frozen_wh"])


def run_lease(fw, samples, soc_fn=None, c=1000):
    """A settled lease commanding c W (default 1000) fed one telemetry read every 10 s - (grid_w, battery_w) per read, SOC from soc_fn(i) (default a fresh,
    unchanged 70 %) - with the 15 s watchdog on the same clock. Returns (read index at the first end, its reason) or (None, "")."""
    s = started(fw, target=1000, ceiling=max(c, 1000))
    force_ceiling(s, c)
    tick(s, ms=31000)
    t, next_w, n_end = 0, 15000, len(end_reasons(s))
    for i, (g, b) in enumerate(samples):
        t_s = (i + 1) * 10000
        while next_w <= t_s:
            s.advance(next_w - t)
            t = next_w
            config_poll(s)
            s.run_actions(watchdog(s.fw))
            if len(end_reasons(s)) > n_end:
                return i, end_reasons(s)[n_end]
            next_w += 15000
        s.advance(t_s - t)
        t = t_s
        s.ent("ecco_grid_ct_power").publish_state(float(g))       # the read's publish order: CT, SOC, battery
        s.ent("ecco_battery_soc").publish_state(soc_fn(i) if soc_fn else 70.0)
        s.ent("ecco_battery_power").publish_state(float(b))
    for _ in range(2):
        s.advance(15000)
        config_poll(s)
        s.run_actions(watchdog(s.fw))
        if len(end_reasons(s)) > n_end:
            return len(samples), end_reasons(s)[n_end]
    return None, ""


noisy = [(-1000.0 - (i % 3), 1100.0 + 7 * (i % 4)) for i in range(60)]
i, why = run_lease(FW, noisy)
check("a healthy 10-minute lease (meter noise of a few W on the CT and the battery): no frozen-telemetry end", i is None, why)
FIXB = [b for lease in FIX["leases"] for t_, c_, b in lease["samples"]]
runs, cur = [], 1
for a_, b_ in zip(FIXB, FIXB[1:]):
    cur = cur + 1 if a_ == b_ else 1
    runs.append(cur)
check(f"the recorded leases never repeat a battery reading {N_FROZEN} times in a row (longest run {max(runs)})", max(runs) < N_FROZEN)

cross = [(-1000.0, 1050.0 + 50 * (i % 5)) for i in range(20)]               # the battery moves 200 W; the CT never changes
i_new, why_new = run_lease(FW, cross)
i_old, why_old = run_lease(OLD, cross)
check(f"the CT repeats exactly while the battery moves (200 W, within every runaway threshold): GRID CT FROZEN after {N_FROZEN} identical reads "
      f"(fcp1: {'never' if i_old is None else why_old})",
      i_new is not None and i_new <= N_FROZEN + 1 and why_new.startswith("GRID CT FROZEN") and i_old is None, f"{i_new} {why_new}")
steady = [(-1000.0, 1100.0 + 7 * (i % 4)) for i in range(N_LONG + 6)]       # the CT repeats; the battery is steady (cross < 150 W)
i_new, why_new = run_lease(FW, steady)
check(f"the CT repeats exactly with a steady battery (a CT stuck at a saturated ceiling): GRID CT FROZEN after {N_LONG} reads, "
      "not before", i_new is not None and N_LONG - 2 <= i_new <= N_LONG + 1 and why_new.startswith("GRID CT FROZEN"), f"{i_new} {why_new}")
i_new, _ = run_lease(FW, steady[:N_LONG - 3])
check(f"...{N_LONG - 3} identical CT reads with a steady battery do not end the lease", i_new is None)

bat = [(-1000.0 - (i % 3), 1180.0) for i in range(12)]                      # the battery repeats exactly; the CT is noisy
i_new, why_new = run_lease(FW, bat)
i_old, _ = run_lease(OLD, bat)
check(f"battery power repeats exactly ({N_FROZEN} identical reads): BATTERY POWER TELEMETRY FROZEN (fcp1: never)",
      i_new is not None and i_new <= N_FROZEN + 1 and why_new.startswith("BATTERY POWER TELEMETRY FROZEN") and i_old is None,
      f"{i_new} {why_new}")
i_new, _ = run_lease(FW, bat[:N_FROZEN - 1] + [(-1001.0, 1181.0)] * 1 + bat[:N_FROZEN - 1])
check(f"{N_FROZEN - 1} identical battery reads, a change, then {N_FROZEN - 1} more: no end (exact repeats only, reset by a change)",
      i_new is None)

reads_to_soc = int(SOC_WH / 3000.0 * 360) + 1                               # 3 kW for SOC_WH Wh, one read every 10 s
soc_frozen = [(-1000.0 - (i % 3), 3000.0 + 5 * (i % 2)) for i in range(reads_to_soc + 10)]
i_new, why_new = run_lease(FW, soc_frozen, c=3000)
i_old, _ = run_lease(OLD, soc_frozen, c=3000)
check(f"3 kW of discharge with the SOC never changing: SOC TELEMETRY FROZEN once {SOC_WH} Wh are discharged (~{reads_to_soc * 10 // 60} "
      f"min; fcp1: never)", i_new is not None and abs(i_new - reads_to_soc) <= 3 and why_new.startswith("SOC TELEMETRY FROZEN")
      and i_old is None, f"{i_new} vs {reads_to_soc} {why_new}")
i_new, why_new = run_lease(FW, soc_frozen, soc_fn=lambda i: 70.0 - i // 36, c=3000)  # 1 % every 6 minutes at 3 kW (the recorded rate)
check("the same discharge with the SOC falling 1 % every 6 minutes (the recorded rate): no frozen-SOC end", i_new is None, why_new)

s = started(target=1000)
force_ceiling(s, 1000)
for k in range(3):
    s.advance(9000)
    s.ent("ecco_grid_ct_power").publish_state(-1000.0)
    s.ent("ecco_battery_power").publish_state(1100.0 + 400 * k)
check("lease-start grace: frozen readings in the first 30 s are not judged", first_end(s) == "")

# SG-39: the restore's comms backoff after a GENUINE recovery.
def backoff_case(fw, link_down):
    s = started(fw, target=1000)
    real = s.outcome_fn
    s.outcome_fn = lambda k, a, c: "no_response" if k == "read" else "no_response_lost"
    if link_down:
        s.advance(30000)                         # no telemetry read for 30 s: the link is down
    end(s)
    for _ in range(4):                           # four more failed attempts, the link still down: the backoff reaches 300 s
        s.advance(int(s.g["dump_restore_next_attempt_ms"]) - s.millis() + 1)
        if not link_down:
            s.ent("ecco_battery_soc").publish_state(70.0)
        s.run_actions(watchdog(s.fw))
    attempts, wait = s.g["dump_comms_restore_attempts"], int(s.g["dump_restore_next_attempt_ms"]) - s.millis()
    s.outcome_fn = real                          # the inverter answers again
    s.advance(5000)
    s.ent("ecco_battery_soc").publish_state(70.0)     # a telemetry read succeeds: the link is proven up
    t0 = s.millis()
    for _ in range(25):
        if owned(s) == ORIGINAL and marker(s) == 0:
            break
        s.advance(15000)
        s.ent("ecco_battery_soc").publish_state(70.0)
        s.run_actions(watchdog(s.fw))
    return attempts, wait, (s.millis() - t0) / 1000.0, owned(s) == ORIGINAL and marker(s) == 0


a_new, w_new, t_new, ok_new = backoff_case(FW, link_down=True)
a_old, w_old, t_old, ok_old = backoff_case(OLD, link_down=True)
check(f"restore failures while the link is DOWN back off to {w_new // 1000} s; once a telemetry read succeeds again the restore "
      f"completes within {t_new:.0f} s (fcp1: {t_old:.0f} s - the rest of the backoff, unmonitored)",
      a_new == 5 and w_new > 200000 and ok_new and t_new <= 30 and ok_old and t_old > 200, f"{a_new} {w_new} {t_new} {t_old}")
a_new, w_new, t_new, ok_new = backoff_case(FW, link_down=False)
check(f"restore failures while telemetry kept FLOWING (the inverter, not the link, failed): the ordinary backoff is kept "
      f"({t_new:.0f} s)", ok_new and t_new > 200, f"{a_new} {w_new} {t_new}")

# ==================================================================================================================================
print("\n[S] SG-36 / SG-07 / SG-16: gated restart, safe to flash, build identity, explicit safe mode")
# ==================================================================================================================================
BUTTONS = FW["button"]
raw = [b for b in BUTTONS if b.get("platform") == "restart"]
gated = next(b for b in BUTTONS if b.get("name") == "Restart")
check("the raw reboot primitive is INTERNAL (Home Assistant cannot press it); the 'Restart' entity is the gated template button",
      len(raw) == 1 and raw[0].get("internal") is True and raw[0].get("id") == "ecco_restart_internal"
      and gated.get("platform") == "template" and gated["on_press"] == [{"script.execute": "ecco_restart_request"}])
PRESSERS = sorted(s["id"] for s in FW["script"] if "'button.press': 'ecco_restart_internal'" in str(s))
check("only two scripts press the raw primitive: the gated Restart (ecco_restart_request) and the STUCK-lock escalation",
      FW_TEXT.count("button.press: ecco_restart_internal") == 2 and PRESSERS == ["ecco_lock_escalation", "ecco_restart_request"],
      str(PRESSERS))
ARM_IV = next(i for i in FW["interval"] if "dump_limits_arm" in str(i))


def idle_sim():
    s = fresh(target=1000)
    s.ent("ecco_restart_arm").state = False
    return s


def restart(s, armed=False):
    if armed:
        s.ent("ecco_restart_arm").state = True
        s.g["ecco_restart_arm_ms"] = s.millis()
    n = len(s.pressed)
    s.execute("ecco_restart_request")
    return len(s.pressed) > n, str(s.ent("ecco_restart_status").state)


s = idle_sim()
check("before the first census, the device does not claim to be safe to flash", s.g["ecco_unsafe_reason"] != "")
s.run_actions(ARM_IV["then"])
check("idle with every marker CLEAR: SAFE TO FLASH; Restart restarts", s.g["ecco_unsafe_reason"] == "" and restart(s)[0], restart(s)[1])
CENSUS = (
    ("dump_operation_in_progress", True, "a Dump to Grid transaction is in progress", True),
    ("free_power_operation_in_progress", True, "a Free Power transaction is in progress", True),
    ("free_power_recovery_force_in_progress", True, "a Free Power transaction is in progress", True),
    ("reg244_apply_in_progress", True, "a register 244 change is in progress", True),
    ("manual_write_in_progress", True, "an inverter write is in progress", True),
    ("correction_in_progress", True, "an RTC correction is in progress", True),
    ("fallback_profile_op_in_progress", True, "a fallback profile operation is in progress", True),
    ("dump_marker_state", 1, "a Dump to Grid restore is owed", False),
    ("dump_operator_needed", True, "a Dump to Grid recovery decision is outstanding", False),
    ("dump_recovery_metadata_corrupt", True, "a Dump to Grid recovery decision is outstanding", False),
    ("free_power_snapshot_valid", True, "a Free Power lease or restore is owed", False),
    ("free_power_marker_state", 2, "a Free Power lease or restore is owed", False),
    ("free_power_operator_needed", True, "a Free Power recovery decision is outstanding", False),
    ("reg244_snapshot_valid", True, "a register 244 restore is owed", False),
    ("reg244_marker_state", 1, "a register 244 restore is owed", False),
)
for gid, val, why, busy in CENSUS:
    s = idle_sim()
    s.g[gid] = val
    did, st = restart(s)
    check(f"{gid} set: NOT safe to flash ('{why}'); a routine Restart is REFUSED and says why",
          s.g["ecco_unsafe_reason"] == why and s.g["ecco_unsafe_busy"] is busy and not did and st.startswith("REFUSED - " + why), st)
    did, st = restart(s, armed=True)
    if busy:
        check(f"...{gid}: a transaction in flight is NEVER overridable, even armed", not did and "never overridable" in st, st)
    else:
        check(f"...{gid}: an owed obligation may be overridden with the arm (the boot path re-opens it)",
              did and st.startswith("RESTARTING (override)"), st)
    check(f"...{gid}: the arm is consumed by the press", s.ent("ecco_restart_arm").state is False)

s = started(target=1000)
s.ent("ecco_restart_arm").state = False
did, st = restart(s)
check("during an ACTIVE Dump lease: Restart REFUSED ('a Dump to Grid lease is active')",
      not did and st.startswith("REFUSED - a Dump to Grid lease is active"), st)
s = idle_sim()
s.ent("ecco_restart_arm").state = True
s.g["ecco_restart_arm_ms"] = s.millis()
s.g["dump_marker_state"] = 1
s.advance(61000)
s.run_actions(ARM_IV["then"])
check("the override arm expires after 60 s (the 5 s interval turns it off)", s.ent("ecco_restart_arm").state is False)
s.ent("ecco_restart_arm").state = True
s.g["ecco_restart_arm_ms"] = s.millis() - 61000
did, st = restart(s)
check("...and an arm older than 60 s does not authorise an override", not did and st.startswith("REFUSED"), st)

names = {e.get("name"): e for sec in ("text_sensor", "binary_sensor", "switch") for e in FW[sec] if isinstance(e, dict)}
ident = names["ECCO Build Identity"]["lambda"]
check("ECCO Build Identity publishes the build tag, the capability profile, the ESPHome version and the config hash",
      all(tok in ident for tok in ("${ecco_build_tag}", "${ecco_inverter_profile_id}", "ESPHOME_VERSION", "App.get_config_hash()"))
      and SUBS["ecco_build_tag"] == "unrecorded-build")
check("ECCO Safe To Flash is exactly 'the census found nothing'; ECCO Flash Readiness names the reason",
      names["ECCO Safe To Flash"]["lambda"] == "return id(ecco_unsafe_reason).empty();"
      and "NOT SAFE - " in names["ECCO Flash Readiness"]["lambda"])
check("the safe-mode block is explicit, with ESPHome's own defaults (no behaviour change: 10 attempts, 5 min, good after 1 min)",
      FW.get("safe_mode") == {"num_attempts": 10, "reboot_timeout": "5min", "boot_is_good_after": "1min"}, str(FW.get("safe_mode")))
check("the census performs no Modbus I/O and no durable access (RAM reads only)",
      not any(tok in str(next(x for x in FW["script"] if x["id"] == "ecco_safety_census"))
              for tok in ("modbus_client", "commit_record", "load_record")))

# ==================================================================================================================================
print("\n[K] SG-14 / SG-42: a lock is never released by time - a STUCK lock escalates")
# ==================================================================================================================================
STUCK_MS = int(SUBS["ecco_write_lock_stuck_ms"])


def five_s(s, seconds):
    """Run the real 5 s interval for `seconds` of simulated time."""
    for _ in range(seconds // 5):
        s.advance(5000)
        s.run_actions(ARM_IV["then"])


s = started(target=1000)
s.ent("ecco_restart_arm").state = False
s.g["manual_write_in_progress"] = True            # a leaked write lock during an ACTIVE lease (no script holds it)
five_s(s, STUCK_MS // 1000 - 10)
check("a lock held for less than the bound is a transaction in flight: not STUCK, nothing escalated, never overridable",
      not s.g["ecco_lock_stuck"] and s.pressed == [] and s.g["ecco_unsafe_busy"] is True)
five_s(s, 20)
check(f"held beyond {STUCK_MS // 1000} s during an ACTIVE lease: the lease is ended DURABLY (restore_requested committed, reason "
      "WRITE LOCK STUCK) and the device restarts through the internal primitive so the boot path completes the restore",
      s.g["ecco_lock_stuck"] and s.g["dump_restore_requested"] and s.nvs["ecco_dump_to_grid_snapshot_data_v2"].restore_requested == 1
      and str(s.ent("dump_last_end_reason").state).startswith("WRITE LOCK STUCK") and s.pressed == ["ecco_restart_internal"]
      and str(s.ent("ecco_restart_status").state).startswith("RESTARTING (stuck lock)"), str(s.ent("ecco_restart_status").state))
check("...the lock itself was NOT released by any of it (manual_write_in_progress still held)", s.g["manual_write_in_progress"] is True)
five_s(s, 60)
check("...and the episode is escalated once (no repeated presses while the same lock stays held)", s.pressed == ["ecco_restart_internal"])
b = reboot(s)
tick(b)
check("...after the restart the boot path completes the owed restore (ownership-checked) with fresh RAM",
      owned(b) == ORIGINAL and marker(b) == 0, b.status())

s = idle_sim()
s.g["manual_write_in_progress"] = True            # a leaked lock with NOTHING owed
five_s(s, STUCK_MS // 1000 + 15)
check("a STUCK lock with nothing owed: reported, NO automatic restart, the lock not released",
      s.g["ecco_lock_stuck"] and s.pressed == [] and s.g["manual_write_in_progress"] is True
      and str(s.ent("ecco_restart_status").state).startswith("STUCK LOCK"), str(s.ent("ecco_restart_status").state))
did, st = restart(s)
check("...a routine Restart is refused, naming the STUCK lock", not did and "STUCK" in st, st)
did, st = restart(s, armed=True)
check("...but a STUCK lock is not a transaction in flight: Restart with the override arm restarts (the recovery)",
      did and st.startswith("RESTARTING (override)"), st)

s = idle_sim()
s.g["manual_write_in_progress"] = True
five_s(s, STUCK_MS // 1000 - 30)
s.g["manual_write_in_progress"] = False           # released by its own transaction
five_s(s, 5)
s.g["manual_write_in_progress"] = True
five_s(s, STUCK_MS // 1000 - 30)
check("a lock released by its transaction resets the age: two long-but-bounded holds never count as STUCK",
      not s.g["ecco_lock_stuck"] and s.pressed == [])

LOCKS = ("manual_write_in_progress", "dump_operation_in_progress", "free_power_operation_in_progress", "reg244_apply_in_progress",
         "correction_in_progress")
lock_code = str(next(i for i in FW["interval"] if "dump_limits_arm" in str(i))) + str(next(x for x in FW["script"] if x["id"] == "ecco_lock_escalation"))
check("the lock-age monitor and the escalation never assign a lock: no timeout releases one",
      not any(f"id({k}) = false" in lock_code for k in LOCKS))
rtc_old = next(i for i in OLD["interval"] if "breaker_due" in str(i))
rtc_new = next(i for i in FW["interval"] if "breaker_due" in str(i))
check("the FB-D1 RTC deadline breaker is unchanged (it needs its deadline AND proof that no RTC frame is outstanding, releases "
      "RTC-owned state only, never the shared write lock, and ends ABORTED with a cooldown)", rtc_old == rtc_new
      and "no_rtc_frame_outstanding" in str(rtc_new) and "id(manual_write_in_progress) = false" not in str(rtc_new))

# ==================================================================================================================================
print("\n[W] the independent audit (Window 7) and the async-hub defect: permanent regressions")
# ==================================================================================================================================
NUMBERS = {n["id"]: n for n in FW["number"]}
FAST = next(i for i in FW["interval"] if "id(dump_export_trip) != 0 && id(dump_active_persisted)" in str(i))


def set_number(sim, number_id, value):
    sim.run_actions(NUMBERS[number_id]["set_action"], {"x": float(value)})


def limits_arm(sim):
    sim.ent("dump_limits_arm").state = True
    sim.g["dump_limits_arm_ms"] = sim.millis()


def lease_at(c, fw=None, target=1000, max_export=None, originals=None, settle=True):
    """A lease whose controller has walked every slot to c W (ECCO's verified and pending ceiling)."""
    s = ds.Sim(fw or FW)
    s.configure_dump_limits(max(c, 3000), CAP if max_export is None else max_export)
    s.bank.update(originals or ORIGINAL)
    for k, v in (("dump_export_power", float(target)), ("dump_stop_soc", 25.0), ("dump_duration_minutes", 90.0),
                 ("ecco_battery_voltage", 52.0)):
        s.ent(k).set(v)
    for k, v in (("dump_write_enable", True), ("dump_recovery_arm", False), ("dump_limits_arm", False),
                 ("configuration_online", True), ("configuration_polling", True), ("ecco_restart_arm", False)):
        s.ent(k).state = v
    s.g["ntp_synced"] = True
    for i, t in enumerate([0, 530, 800, 1600, 1900, 2330]):
        s.g[f"manual_cfg_reg{250 + i}_raw"] = t
    for i, f in enumerate([1, 0, 0, 0, 0, 0]):
        s.g[f"manual_cfg_reg{274 + i}_raw"] = f
    config_poll(s)
    s.ent("ecco_battery_soc").publish_state(70.0)
    s.grid_w = -float(target)
    s.ent("ecco_grid_ct_power").publish_state(s.grid_w)
    s.execute("start_dump_to_grid_override")
    assert s.g["dump_active_persisted"], s.status()
    for r in range(256, 262):
        s.bank[r] = c
    s.g["dump_target_power"] = c
    s.g["dump_evidence_pending_ceiling"] = c
    s.g["dump_runaway_ceiling_ref"] = float(c)
    if settle:
        s.advance(40000)
    return s


def retries(s, n, outcome_244=None):
    """n watchdog ticks with the backoff skipped (the attempts happen in this window) and fresh telemetry."""
    w244 = 0
    for _ in range(n):
        s.advance(15000)
        s.ent("ecco_battery_soc").publish_state(70.0)
        config_poll(s)
        s.g["dump_restore_next_attempt_ms"] = 0
        before = len([e for e in s.modbus_log if e[0] == "write" and e[1] == 244])
        s.run_actions(watchdog(s.fw))
        w244 += len([e for e in s.modbus_log if e[0] == "write" and e[1] == 244]) - before
    return w244


# --- B1 / O2: a FOREIGN slot plus a failed 244 restore is NOT an operator lockout after one attempt ----------------------------
for mode in ("error", "ack_not_applied"):
    for label, fw in (("fcp2 rework", FW), ("fcp1", OLD)):
        s = lease_at(6000, fw, target=5500)
        s.bank[258] = 1234                                    # one FOREIGN slot
        s.outcome_fn = (lambda m: (lambda k, a, c: m if (k == "write" and a == 244) else "ok"))(mode)
        s.execute("request_dump_end", {"reason": ds.CStr("TEST END")})
        first_locked = s.g["dump_operator_needed"]
        w = retries(s, 8)
        block = [s.bank[r] for r in range(256, 262)]
        if label == "fcp2 rework" and mode == "error":
            check("B1/O2 (244 write ERRORS, one FOREIGN slot): no lockout after one attempt - the comms path keeps retrying with "
                  "the obligation kept, and every attempt CONTAINS ECCO's own slots at the 500 W floor (the FOREIGN one untouched)",
                  not first_locked and not s.g["dump_operator_needed"] and w >= 4 and s.g["dump_snapshot_valid"]
                  and block == [500, 500, 1234, 500, 500, 500] and s.bank[244] == 0
                  and "244 NOT proven off; ECCO's own at 500 W; NOT CONTAINED: 258=1234W" in s.status(),
                  f"w={w} block={block} {s.status()}")
        elif label == "fcp2 rework":
            check("B1/O2 (244 write ACKed but NOT applied, one FOREIGN slot): the mismatch path's retry, not an immediate FOREIGN "
                  "lockout; ECCO's slots CONTAINED at 500 W and verified; the eventual operator lockout says 244 is not proven",
                  not first_locked and w >= 1 and block == [500, 500, 1234, 500, 500, 500] and s.g["dump_operator_needed"]
                  and "244 NOT proven off; ECCO's own at 500 W; NOT CONTAINED: 258=1234W" in s.status()
                  and "FOREIGN (not overwritten)" not in str(s.ent("dump_recovery_state").state), f"w={w} block={block} {s.status()}")
        elif mode == "error":
            check("...the FCP1 base retried the same comms error without a lockout (the B1 regression was FCP2's)",
                  not s.g["dump_operator_needed"] and w >= 4)
s = lease_at(6000, target=5500)
s.bank[258] = 1234
s.execute("request_dump_end", {"reason": ds.CStr("TEST END")})
check("...and with 244 restoring normally, the FOREIGN lockout comes only AFTER ECCO's own 244 and slots were written AND "
      "verified, and says so", s.bank[244] == 2 and [s.bank[r] for r in (256, 257, 259, 260, 261)] == [8000, 8000, 8000, 8000, 5000]
      and s.bank[258] == 1234 and s.g["dump_operator_needed"]
      and s.status().startswith("OPERATOR DECISION REQUIRED - ECCO's own settings restored and verified"), s.status())

# --- R1 / S4: 244 refused at high power - containment, and supervision while the restore is owed -----------------------------
s = lease_at(6000, target=5500)
s.outcome_fn = lambda k, a, c: "ack_not_applied" if (k == "write" and a == 244) else "ok"
s.execute("request_dump_end", {"reason": ds.CStr("TEST END")})
retries(s, 6)
block = [s.bank[r] for r in range(256, 262)]
check("R1/S4 (6000 W lease, 244 restore ACKed but not applied): every ECCO TOU power slot is CONTAINED at the 500 W floor and "
      "verified - never left at the 6000 W lease ceiling (FCP2 d9f11ea left 6000 W on all six)",
      s.bank[244] == 0 and block == [500] * 6 and s.g["dump_restore_contained"] and s.g["dump_export_unverified"], str(block))
o = lease_at(6000, OLD, target=5500)
o.outcome_fn = lambda k, a, c: "ack_not_applied" if (k == "write" and a == 244) else "ok"
o.execute("request_dump_end", {"reason": ds.CStr("TEST END")})
retries(o, 6)
check("...(the FCP1 base left all six at 6000 W with Allow Export live)", [o.bank[r] for r in range(256, 262)] == [6000] * 6)
# supervision: while the restore is OWED and 244 unproven, export over the limit makes the retry immediate (not backed off)
s = lease_at(3000, target=1000, max_export=3680)
s.outcome_fn = lambda k, a, c: "no_response" if k == "read" and a == 244 and c == 18 else "ok"
s.execute("request_dump_end", {"reason": ds.CStr("TEST END")})
s.advance(2000)
s.g["dump_restore_next_attempt_ms"] = s.millis() + 280000                     # a long backoff is in force
s.ent("ecco_grid_ct_power").publish_state(-6000.0)                             # export far over 3680 W after End
n0 = len([e for e in s.modbus_log if e[0] == "read" and e[1] == 244 and len(e[2]) == 18])
s.outcome_fn = lambda k, a, c: "ok"
s.advance(13000)
s.ent("ecco_battery_soc").publish_state(70.0)
config_poll(s)
s.run_actions(watchdog(s.fw))
n1 = len([e for e in s.modbus_log if e[0] == "read" and e[1] == 244 and len(e[2]) == 18])
check("R1 supervision: after End, with 244 not yet proven and export FAR over the limit, the owed restore is retried at the "
      "next watchdog tick despite a 280 s backoff (and completes)", n1 == n0 + 1 and owned(s) == ORIGINAL and marker(s) == 0,
      f"{n0}->{n1} {s.status()}")
s = lease_at(6000, target=5500)
s.outcome_fn = lambda k, a, c: "ack_not_applied" if (k == "write" and a == 244) else "ok"
s.execute("request_dump_end", {"reason": ds.CStr("TEST END")})
retries(s, 3)
s.g["dump_target_stop_soc"] = 25
s.ent("ecco_battery_soc").publish_state(20.0)                                   # Stop SOC passed while locked out
s.advance(15000)
config_poll(s)
s.run_actions(watchdog(s.fw))
check("R1 supervision under the operator lockout: Stop SOC passed with 244 unproven raises a CRITICAL recovery state "
      "(no write: the operator decides)", s.g["dump_operator_needed"]
      and str(s.ent("dump_recovery_state").state).startswith("CRITICAL - restore OWED, register 244 not proven out of Allow Export: "
                                                              "Stop SOC reached - operator action now: Force Restore Original"),
      str(s.ent("dump_recovery_state").state))

# --- R2 / D1, D2: export safety -----------------------------------------------------------------------------------------------
def d1(export_w, fw=FW, fast=True):
    """CT and battery every 10 s and the watchdog every 15 s from the moment START enabled export; the 1 s interval runs too."""
    s = lease_at(3000, fw, target=3000, max_export=3680, settle=False)
    t0 = s.millis()
    for step in range(1, 61):
        s.advance(1000)
        t = s.millis() - t0
        if t % 10000 == 0:
            s.ent("ecco_battery_soc").publish_state(70.0)
            s.ent("ecco_battery_power").publish_state(2000.0 + (step % 3))
            s.ent("ecco_grid_ct_power").publish_state(-export_w - (step % 2))
            config_poll(s)
        if fast:
            s.run_actions(FAST["then"])
        if t % 15000 == 0:
            s.run_actions(watchdog(s.fw))
        if first_end(s):
            return t / 1000.0, first_end(s)
    return None, ""


t_far, why = d1(7000.0)
check(f"R2/D1: 7000 W of export against a 3680 W limit from START ends the lease at the first meter reading + <=1 s "
      f"({t_far} s; FCP2 d9f11ea: 60 s - its 30 s grace and 3-of-4 rule)", t_far is not None and t_far <= 11
      and "one reading far over it" in why, f"{t_far} {why}")
t_mod, why = d1(3900.0)
check(f"R2: a MARGINAL excess (3900 W vs 3680 + 110 W margin) ends it on the SECOND reading over + <=1 s ({t_mod} s)",
      t_mod is not None and t_mod <= 21 and "two of the last three readings over it" in why, f"{t_mod} {why}")
t_ok, _ = d1(3600.0)
check("R2: export within the limit never trips the guard", t_ok is None)
s = fresh(target=3000, grid_w=-5000.0, ceiling=3000)
s.configure_dump_limits(3000, 3680)
s.execute("start_dump_to_grid_override")
check("R2/D2: START is REFUSED while the meter already shows 5000 W export against a 3680 W limit; nothing written",
      not s.g["dump_active_persisted"] and s.status() == "REJECTED - the grid meter already shows export above the configured maximum grid export"
      and s.writes() == [], s.status())
s = fresh(target=3680, ceiling=3000)
s.configure_dump_limits(3000, 3680)
s.execute("start_dump_to_grid_override")
check("R2/F7: a target AT the limit is refused (no headroom for the guard's own margin)",
      not s.g["dump_active_persisted"] and "no headroom" in s.status(), s.status())
check("R2: START refuses BEFORE any write when its own feed-forward read shows a natural PV surplus above the limit",
      "dump_start_surplus_refused) = true" in FW_TEXT and "natural PV export surplus" in FW_TEXT
      and "if (trustworthy && pv_power - house_load > (float) id(dump_max_export_w))" in FW_TEXT)
# Executed: the feed-forward reply shows PV 6000 W against a 500 W house - a 5500 W visible surplus.
s2 = fresh(target=3000, ceiling=3000)
s2.configure_dump_limits(3000, 3680)
_real_read = s2._modbus_read


def read_with_surplus(body, local):
    _real_read(body, local)
    if int(body["start_address"]) == 172:
        s2.g["dump_ff_read_ok"] = True
        s2.g["dump_ff_grid_w"] = 0.0
        s2.g["dump_ff_inverter_w"] = 500.0
        s2.g["dump_ff_house_w"] = 500.0
        s2.g["dump_ff_pv_w"] = 6000.0


s2._modbus_read = read_with_surplus
s2.execute("start_dump_to_grid_override")
check("...executed: a 5500 W visible surplus against 3680 W - REJECTED, nothing written, no obligation created",
      not s2.g["dump_active_persisted"] and not s2.g["dump_snapshot_valid"] and s2.writes() == []
      and s2.status().startswith("REJECTED - natural PV export surplus ~5500W"), s2.status())

# --- R3 / L1: invalid limits need BOTH re-confirmed --------------------------------------------------------------------------
s = fresh(target=1000, ceiling=3000)
s.configure_dump_limits(3000, 3680)
s.g["dump_max_export_w"] = 6000                                 # an incomplete save: export changed, integrity value not
s.run_dump_limits_boot()
invalid = not s.g["dump_limits_valid"]
limits_arm(s)
set_number(s, "dump_op_ceiling_number", 3000)
still_invalid = not s.g["dump_limits_valid"]
s.ent("dump_export_power").set(5500.0)
s.execute("start_dump_to_grid_override")
check("R3/L1: INVALID at boot; re-setting ONLY the ceiling keeps the limits INVALID (the stale 6000 W export is never "
      "re-validated); START refused", invalid and still_invalid and not s.g["dump_active_persisted"]
      and "the maximum grid export must also be set again" in str(s.ent("dump_limits_status").state),
      str(s.ent("dump_limits_status").state))
check("...and the integrity value was NOT recomputed, so a reboot now is still INVALID",
      (s.run_dump_limits_boot() or True) and not s.g["dump_limits_valid"])
limits_arm(s)
set_number(s, "dump_max_export_number", 3680)
check("...confirming the maximum grid export as well (armed): VALID with the owner's 3680 W, and it survives a reboot",
      s.g["dump_limits_valid"] and s.g["dump_max_export_w"] == 3680
      and (s.run_dump_limits_boot() or True) and s.g["dump_limits_valid"], str(s.ent("dump_limits_status").state))

# --- R4 / A1: Accept never retires a raised ECCO residue ------------------------------------------------------------------------
LOW = {244: 2, 256: 2500, 257: 2500, 258: 2500, 259: 2500, 260: 2500, 261: 2500}
s = lease_at(6000, target=5500, originals=LOW)
s.bank[258] = 1234
s.execute("request_dump_end", {"reason": ds.CStr("TEST END")})
s.advance(5000)
config_poll(s)
check("R4/A1 (originals 2500 W, lease 6000 W, one FOREIGN slot): ECCO's own five slots are RESTORED to 2500 W by the "
      "restore itself - no 6000 W residue left (FCP2 d9f11ea left 6000 W on five slots)",
      [s.bank[r] for r in range(256, 262)] == [2500, 2500, 1234, 2500, 2500, 2500], str([s.bank[r] for r in range(256, 262)]))
s.ent("dump_recovery_arm").state = True
s.execute("dump_accept_current_state")
check("...Accept then may retire it, keeping the FOREIGN 1234 W (the external owner's)", marker(s) == 0 and s.bank[258] == 1234,
      s.status())
s = lease_at(6000, target=5500, originals=LOW)
s.outcome_fn = lambda k, a, c: "error" if (k == "write" and a >= 256) else "ok"   # the slot writes fail: ECCO's 6000 W stays
s.execute("request_dump_end", {"reason": ds.CStr("TEST END")})
s.g["dump_operator_needed"] = True                              # e.g. after a later lockout
s.advance(5000)
config_poll(s)
s.ent("dump_recovery_arm").state = True
s.execute("dump_accept_current_state")
check("R4: with ECCO's 6000 W still on a slot above its 2500 W original, Accept is REFUSED (zero writes, obligation kept)",
      marker(s) == 1 and s.status().startswith("ACCEPT REFUSED - register 256 still holds ECCO's 6000W, above its original 2500W"),
      s.status())

# --- F1 / R3-runaway: the 800 s oscillating overshoot ----------------------------------------------------------------------
def r3(fw):
    s = lease_at(6000, fw, target=6000)
    thr = abs_thr(6000)
    pattern = [thr + 900, thr - 200, thr - 200, thr + 900, thr - 200, thr - 200, thr + 900, thr - 200]
    for i in range(80):
        s.advance(10000)
        s.ent("ecco_battery_soc").publish_state(70.0 - i * 0.05)
        s.ent("ecco_battery_power").publish_state(float(pattern[i % 8] + (i % 3)))
        s.ent("ecco_grid_ct_power").publish_state(-5900.0 - (i % 5))
        config_poll(s)
        if i % 3 == 2:
            s.run_actions(watchdog(s.fw))
        if first_end(s):
            return i, first_end(s)
    return None, ""


i_new, why = r3(FW)
i_old, _ = r3(OLD)
check(f"F1/R3: the audit's 800 s oscillating overshoot (3 of 8 samples to backstop+900 W, 5 just under it; mean +1323 W above "
      f"a 6000 W command) now ends the lease (SUSTAINED POWER EXCESS, sample {i_new}); FCP2 d9f11ea's windows alone let it run "
      f"800 s (independent audit R3). (The FCP1 base trips it only through its fixed 750 W backstop - sample {i_old} - the "
      f"same backstop that nuisance-trips a healthy 7-8 kW lease, see [R].)",
      i_new is not None and i_new <= 12 and why.startswith("SUSTAINED POWER EXCESS (windowed mean)"), f"{i_new} {why}")
for c in (500, 1000, 2000, 3000, 4000, 5000, 6000, 7000, 8000):
    noisy_ok = feed(at_level(c), [c * 1.12 + 100.0 + (8 if k % 2 else -8) for k in range(40)])
    check(f"F1 no nuisance: {c} W under the pessimistic loss model (12 % + 100 W) for 400 s - the mean criterion never trips",
          noisy_ok is None, str(noisy_ok))
check("F1 no nuisance: the recorded leases replay with the mean criterion active - no trip",
      [lease["lease"] for lease in FIX["leases"] if replay(FW, lease)[1]] == [])
check("F1: two isolated gross spikes still do not trip (each sample adds at most one backstop margin to the mean)",
      feed(at_level(3000), [8600, 3300, 3300, 8600, 3300, 3300, 3300, 3300, 3300, 3300]) is None)

# --- F3: an idle battery at exactly 0 W is not frozen; a toggling SOC cannot defeat the frozen-SOC count ----------------------
i_f1, why = run_lease(FW, [(300.0 + (k % 3), 0.0) for k in range(12)])
check("F3/F1: a battery legitimately idle at exactly 0 W for 12 reads (the grid agrees: the house imports ~300 W, no export) "
      "does NOT end the lease as frozen (FCP2 d9f11ea did)", i_f1 is None, why)
i_tog, why = run_lease(FW, [(-1000.0 - (k % 3), 3000.0 + 5 * (k % 2)) for k in range(reads_to_soc + 10)],
                       soc_fn=lambda k: 70.0 + (k % 2), c=3000)
check("F3: a SOC toggling between 70 and 71 % while kWh are discharged still trips SOC TELEMETRY FROZEN",
      i_tog is not None and why.startswith("SOC TELEMETRY FROZEN"), f"{i_tog} {why}")

# --- F4: no stale link-down stamp survives into a new lease --------------------------------------------------------------------
s = started(target=1000)
s.g["dump_restore_failed_ms"] = 12345
s.execute("request_dump_end", {"reason": ds.CStr("TEST END")})
s3 = fresh(target=1000)
s3.g["dump_restore_failed_ms"] = 999
s3.execute("start_dump_to_grid_override")
check("F4: a restore SUCCESS clears dump_restore_failed_ms, and every START clears it",
      marker(s) == 0 and s.g["dump_restore_failed_ms"] == 0 and s3.g["dump_active_persisted"] and s3.g["dump_restore_failed_ms"] == 0)

# --- the stuck-lock restart waits for a quiet bus ------------------------------------------------------------------------------
s = started(target=1000)
s.ent("ecco_restart_arm").state = False
s.g["manual_write_in_progress"] = True
s.bus_idle = False
five_s(s, STUCK_MS // 1000 + 30)
p_busy = list(s.pressed)
s.bus_idle = True
five_s(s, 5)
check("the STUCK-lock escalation never restarts while a Modbus frame is queued or awaited (it waits for a quiet bus, "
      "re-checked every 5 s), then escalates", p_busy == [] and s.pressed == ["ecco_restart_internal"], f"{p_busy} {s.pressed}")


# --- AT1: the restore under an ASYNCHRONOUS Modbus hub (the d9f11ea completion-flag defect) ------------------------------------
class AsyncSim(ds.Sim):
    """The real hub: a command's reply arrives LATER, in order; wait_until returns at once if its flag is already set. Replies
    are queued and delivered FIFO only while a wait_until condition is false."""

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.pending = []
        self.async_on = False

    def _handler(self, body, name, local, values=None, exception_code=None):
        if not self.async_on:
            return super()._handler(body, name, local, values, exception_code)
        self.pending.append((body, name, dict(local or {}), values, exception_code))

    def run_actions(self, actions, local=None):
        for action in actions or []:
            (kind, body), = action.items()
            if kind == "wait_until" and self.async_on:
                cond = body["condition"]["lambda"]
                while not self.run_lambda(cond, local, params=tuple((local or {}).keys())) and self.pending:
                    b, n, l, v, e = self.pending.pop(0)
                    ds.Sim._handler(self, b, n, l, v, e)
                continue
            super().run_actions([action], local)


def async_restore(fw, case):
    s = AsyncSim(fw)
    s.configure_dump_limits(3000, CAP)
    s.bank.update(ORIGINAL)
    for k, v in (("dump_export_power", 1000.0), ("dump_stop_soc", 25.0), ("dump_duration_minutes", 90.0), ("ecco_battery_voltage", 52.0)):
        s.ent(k).set(v)
    for k in ("configuration_online", "configuration_polling", "dump_write_enable"):
        s.ent(k).state = True
    s.ent("dump_recovery_arm").state = False
    s.g["ntp_synced"] = True
    for i, t in enumerate([0, 530, 800, 1600, 1900, 2330]):
        s.g[f"manual_cfg_reg{250 + i}_raw"] = t
    for i, f in enumerate([1, 0, 0, 0, 0, 0]):
        s.g[f"manual_cfg_reg{274 + i}_raw"] = f
    config_poll(s)
    s.ent("ecco_battery_soc").publish_state(70.0)
    s.ent("ecco_grid_ct_power").publish_state(-1000.0)
    s.execute("start_dump_to_grid_override")
    s.async_on = True
    if case:
        s.outcome_fn = lambda k, a, c: "ack_not_applied" if (k == "write" and a == case) else "ok"
    s.execute("request_dump_end", {"reason": ds.CStr("manual End button")})
    while s.pending:
        b, n, l, v, e = s.pending.pop(0)
        ds.Sim._handler(s, b, n, l, v, e)
    return s


s = async_restore(FW, None)
check("AT1: under an asynchronous hub a normal restore still completes and verifies", owned(s) == ORIGINAL and marker(s) == 0, s.status())
s = async_restore(FW, 256)
check("AT1: a 256-261 write ACKed but NOT applied is caught by the readback, obligation kept (d9f11ea declared RESTORED OK and "
      "cleared the obligation with ECCO's ceiling still live - its 244 write reused the pre-read's completion flag)",
      marker(s) == 1 and "VERIFY FAILED" in s.status(), s.status())
s = async_restore(FW, 244)
check("AT1: a 244 write ACKed but NOT applied: the 256-261 step CONTAINS (500 W) instead of restoring the originals, and the "
      "attempt fails", marker(s) == 1 and [s.bank[r] for r in range(256, 262)] == [500] * 6, str([s.bank[r] for r in range(256, 262)]))
RESTORE_TEXT = FW_TEXT[FW_TEXT.index("  - id: restore_dump_to_grid_snapshot\n"):FW_TEXT.index("  - id: request_dump_end\n")]
ops = [m.start() for m in re.finditer(r"- modbus_client\.(?:read_holding_registers|write_multiple_registers):", RESTORE_TEXT)]
waits = [m.start() for m in re.finditer(r"- wait_until:", RESTORE_TEXT)]
missing = []
for k, op in enumerate(ops):
    prev_wait = max([w for w in waits if w < op], default=0)
    if "id(dump_op_terminal) = false;" not in RESTORE_TEXT[prev_wait:op]:
        missing.append(k)
check(f"AT1 static: every one of the restore's {len(ops)} Modbus commands is preceded by its own completion-flag reset since the "
      "previous wait", missing == [], str(missing))

# ==================================================================================================================================
print("\n[X] the FINAL rework (Window 7's re-audit of 5178e0f): RF1, F5, Stop SOC after a restart, R2b, uncontained naming")
# ==================================================================================================================================
def frame(s, ct, batt, soc, pv=None):
    """One telemetry frame in the firmware's own publish order (block 150-196): grid CT (172), SOC (184), PV, battery (190).
    None = that register's value is not published (a stale reading)."""
    if ct is not None:
        s.ent("ecco_grid_ct_power").publish_state(float(ct))
    if soc is not None:
        s.ent("ecco_battery_soc").publish_state(float(soc))
    if pv is not None:
        s.ent("ecco_pv_power").publish_state(float(pv))
    if batt is not None:
        s.ent("ecco_battery_power").publish_state(float(batt))


def run_frames(s, fn, seconds):
    """A telemetry frame every 10 s (fn(i) -> (ct, battery, soc, pv)), the 1 s export interval after each frame and the 15 s
    watchdog, on one clock, for `seconds`. Returns (seconds at the first end, its reason) or (None, "")."""
    n0 = len(end_reasons(s))
    t, i = 0, 0
    while t < seconds:
        t += 5
        s.advance(5000)
        if t % 10 == 0:
            frame(s, *fn(i))
            i += 1
            config_poll(s)
            s.run_actions(FAST["then"])
        if t % 15 == 0:
            s.run_actions(watchdog(s.fw))
        if len(end_reasons(s)) > n0:
            return t, end_reasons(s)[n0]
    return None, ""


def telemetry_ends(s):
    return [r for r in end_reasons(s) if "FROZEN" in r or "CONTRADICTED" in r]


# --- RF1: stuck-zero battery telemetry ---------------------------------------------------------------------------------------
t_x, why = run_frames(lease_at(6000, target=5500), lambda i: (-5500.0 - (i % 7), 0.0, 60.0, None), 3600)
check(f"RF1 (Window 7's reproduction, in the real frame order): a 6000 W lease, register 190 STUCK at 0 W, SOC STUCK at 60 %, the "
      f"meter showing ~5.5 kW of export - the GRID CROSS-CHECK ends it at {t_x} s (5178e0f: nothing within 60 minutes - its idle "
      f"exemption hid the stuck 0 W and the frozen-SOC count integrated only the stuck reading)",
      t_x is not None and t_x <= 90 and why.startswith("BATTERY POWER CONTRADICTED BY GRID - reads 0W but export minus PV proves"),
      f"{t_x} {why}")
t_x2, why2 = run_frames(lease_at(6000, target=5500), lambda i: (-5500.0 - (i % 7), 0.0, 60.0 - i * 0.18, None), 3600)
check(f"RF1: the same with the SOC still falling ends it on the cross-check too ({t_x2} s - 5178e0f only at Stop SOC, 1890 s)",
      t_x2 is not None and t_x2 <= 90 and why2.startswith("BATTERY POWER CONTRADICTED BY GRID"), f"{t_x2} {why2}")
s = lease_at(6000, target=5500)
t_n, why_n = run_frames(s, lambda i: (300.0 + (i % 5), 0.0, 40.0, 0.0), 3600)
check("RF1 no nuisance: a battery GENUINELY idle at exactly 0 W for 60 minutes (the house importing ~300 W, no PV, SOC unchanged) "
      "is never judged frozen or contradicted, and the frozen-SOC count does not grow", telemetry_ends(s) == []
      and s.g["dump_soc_frozen_wh_acc"] == 0.0, f"{t_n} {why_n} acc={s.g['dump_soc_frozen_wh_acc']}")
s = lease_at(6000, target=5500)
t_p, why_p = run_frames(s, lambda i: (-2500.0 - (i % 9), 0.0, 55.0, 3000.0 + 13 * (i % 4)), 3600)
check("RF1 no nuisance: a battery idle at 0 W while PV covers the export (PV ~3 kW, export ~2.5 kW) for 60 minutes: never frozen "
      "or contradicted", telemetry_ends(s) == [], f"{t_p} {why_p}")
s = lease_at(6000, target=5500)
t_h, why_h = run_frames(s, lambda i: (-5500.0 - (i % 7), 6100.0 + 9 * (i % 5), 60.0 - i * 0.18, 0.0), 1800)
check("RF1 no nuisance: a HEALTHY 6 kW discharge (battery = export + house load, the relation every recorded lease shows) for 30 "
      "minutes: never contradicted", telemetry_ends(s) == [], f"{t_h} {why_h}")
s = lease_at(6000, target=5500)
t_d, why_d = run_frames(s, lambda i: (-4500.0 - (i % 7), 2000.0 + 9 * (i % 5), 60.0 - i * 0.06, 3000.0 + 11 * (i % 3)), 1800)
check("RF1 no nuisance: daytime - battery 2 kW, PV 3 kW, export 4.5 kW (export - PV = 1.5 kW <= the battery): never contradicted",
      telemetry_ends(s) == [], f"{t_d} {why_d}")
# stale CT: the frames keep coming but register 172 is never published again
s = lease_at(6000, target=5500)
t_s, why_s = run_frames(s, lambda i: (None, 0.0, 60.0, None), 600)
check(f"RF1 + STALE CT: battery stuck at 0 W, SOC stuck and NO fresh grid reading - an idle reading the grid cannot confirm is a "
      f"repeat like any other: the lease ends ({t_s} s: {why_s[:60]})", t_s is not None and t_s <= 120, f"{t_s} {why_s}")
# mixed telemetry failures
cases = [
    ("the CT ALSO frozen at exactly -5500 W", lambda i: (-5500.0, 0.0, 60.0, None), 90),
    ("PV STUCK at exactly 6000 W (it would excuse the export): untrusted after ecco_dump_frozen_ct_long_samples frames",
     lambda i: (-5500.0 - (i % 7), 0.0, 60.0, 6000.0), 400),
    ("battery jittering 0..30 W (never an exact repeat)", lambda i: (-5500.0 - (i % 7), float((i * 7) % 31), 60.0, None), 90),
    ("battery UNDER-reading (a gain fault: 2.2 kW against 5.5 kW export)", lambda i: (-5500.0 - (i % 7), 2200.0 + (i % 3), 60.0, 0.0), 90),
]
for label, fn, bound in cases:
    t_m, why_m = run_frames(lease_at(6000, target=5500), fn, 3600)
    check(f"RF1 mixed failures - {label}, SOC stuck: the lease ends within {bound} s ({t_m} s)",
          t_m is not None and t_m <= bound and ("CONTRADICTED" in why_m or "FROZEN" in why_m), f"{t_m} {why_m}")
s = started(target=1000)                                                        # START's own verified ceiling
run_frames(s, lambda i: (-1000.0 - (i % 7), 0.0, 60.0, None), 20)
b = reboot(s)
tick(b)
check("RF1 + reboot: a power cut during a stuck-zero lease - the boot's forced End runs the ownership-checked restore (the lease "
      "never resumes) and the cross-check history starts empty", owned(b) == ORIGINAL and marker(b) == 0
      and not b.g["dump_bp_xcheck_trip"] and b.g["dump_bp_xcheck_count"] == 0, b.status())
s = lease_at(6000, target=5500)
s.g["dump_bp_xcheck_trip"] = True
s.g["dump_bp_xcheck_window"] = 255
s.execute("request_dump_end", {"reason": ds.CStr("TEST END")})
s2 = lease_at(6000, target=5500)
check("RF1: the cross-check decision is LATCHED for its lease and cleared at the next START",
      s2.g["dump_bp_xcheck_trip"] is False and s2.g["dump_bp_xcheck_window"] == 0)

# --- F5: immediate, checked persistence of the Dump power limits ------------------------------------------------------------
def set_number(sim, number_id, value):                                          # the SIM's own firmware's set_action
    sim.run_actions(next(n for n in sim.fw["number"] if n["id"] == number_id)["set_action"], {"x": float(value)})


def limits_site(fw, ceiling=6000, max_export=6000):
    s = ds.Sim(fw)
    s.configure_dump_limits(ceiling, max_export)
    s.pref_baseline()
    return s


def boot_from_flash(sim):
    """A power cut NOW: a fresh boot whose restore_value globals are exactly what reached flash."""
    b = ds.Sim(sim.fw)
    for k, v in sim.pref_flushed.items():
        b.g[k] = v
    b.run_dump_limits_boot()
    return b


for number, field, new, label in (("dump_op_ceiling_number", "dump_op_ceiling_w", 3000, "power-ceiling"),
                                  ("dump_max_export_number", "dump_max_export_w", 3680, "maximum-grid-export")):
    got = {}
    for name, fw_ in (("final", FW), ("fcp1", OLD)):
        s = limits_site(fw_)
        set_number(s, number, new)
        b = boot_from_flash(s)
        got[name] = (s.g[field], b.g[field], b.g["dump_limits_valid"])
    check(f"F5: a {label} REDUCTION 6000 -> {new} W followed AT ONCE by a power cut boots VALID at {new} W (flushed before it is "
          f"reported); the FCP1 set_action (unchanged up to 5178e0f) left it to the 1 s poll - the same cut booted VALID at the old "
          f"6000 W", got["final"] == (new, new, True) and got["fcp1"] == (new, 6000, True), str(got))
    outcomes = []
    for k in range(0, 4):
        s = limits_site(FW)
        s.pref_cut_after = k
        set_number(s, number, new)
        b = boot_from_flash(s)
        outcomes.append((k, b.g[field], b.g["dump_limits_valid"]))
    check(f"F5: a power cut after EVERY prefix of the {label} flush (k = 1.. writes reached flash) boots INVALID or VALID at the "
          f"NEW {new} W - never VALID at the old 6000 W; k = 0 (cut before the first flash write, i.e. before the change was "
          f"reported) is the old consistent pair", all(v is False or f == new for kk, f, v in outcomes if kk >= 1)
          and outcomes[0][1:] == (6000, True) and any(v is False for kk, f, v in outcomes if kk >= 1), str(outcomes))
s = limits_site(FW)
s.pref_cut_after = 1
limits_arm(s)
set_number(s, "dump_op_ceiling_number", 7000)
b = boot_from_flash(s)
check("F5: a RAISE cut after its first flash write boots INVALID (never VALID at a value the owner did not confirm)",
      not b.g["dump_limits_valid"], str((b.g["dump_op_ceiling_w"], b.g["dump_limits_valid"])))
s = limits_site(FW)
s.pref_sync_fail = True
set_number(s, "dump_op_ceiling_number", 3000)
check("F5: a FAILED flush (NVS refuses) makes the limits INVALID at once - START refused until both are confirmed again - and the "
      "status says the value could not be saved", not s.g["dump_limits_valid"] and s.g["dump_limits_reconfirm"] == 0
      and str(s.ent("dump_limits_status").state).startswith("INVALID - power ceiling 3000 W could NOT be saved to flash"),
      str(s.ent("dump_limits_status").state))
s = limits_site(FW)
set_number(s, "dump_op_ceiling_number", 6000)
check("F5 flash wear: re-setting an UNCHANGED value writes nothing to flash", s.pref_writes == [], str(s.pref_writes))
s = limits_site(FW)
set_number(s, "dump_op_ceiling_number", 3000)
check("F5 flash wear: a reduction writes exactly the changed value and its integrity value, the integrity value LAST",
      [n for n, v in s.pref_writes] == ["dump_op_ceiling_w", "dump_limits_check"], str(s.pref_writes))
s = limits_site(FW, 3000, 3680)
s.g["dump_max_export_w"] = 6000                                                 # a corrupt stored value
s.pref_baseline()
s.run_dump_limits_boot()
limits_arm(s)
set_number(s, "dump_op_ceiling_number", 3000)
mid = boot_from_flash(s)
limits_arm(s)
set_number(s, "dump_max_export_number", 3680)
end_b = boot_from_flash(s)
check("F5 + R3: after INVALID, each re-confirmation is flushed at once; a power cut between the two boots INVALID, after both "
      "VALID at the confirmed pair", not mid.g["dump_limits_valid"] and end_b.g["dump_limits_valid"]
      and (end_b.g["dump_op_ceiling_w"], end_b.g["dump_max_export_w"]) == (3000, 3680))

# --- Priority 3: the post-END supervision keeps this obligation's Stop SOC across a restart --------------------------------
ACK_244 = lambda k, a, c: "ack_not_applied" if (k == "write" and a == 244) else "ok"


def locked_out_then_reboot(rec=None):
    """A 6000 W lease (Stop SOC 25 %) ended with register 244 refusing to leave Allow Export (acknowledged, not applied): ECCO's
    slots contained, the operator lockout reached - then a POWER CUT and a fresh boot (RAM lost; flash, NVS, inverter kept)."""
    s = lease_at(6000, target=5500)
    s.outcome_fn = ACK_244
    s.execute("request_dump_end", {"reason": ds.CStr("TEST END")})
    retries(s, 3)
    assert s.g["dump_operator_needed"], s.status()
    b = reboot(s)
    for k, v in s.pref_flushed.items():
        b.g[k] = v
    if rec is not None:
        b.g["dump_owed_stop_soc_rec"] = rec
    b.outcome_fn = ACK_244
    b.ent("dump_stop_soc").set(25.0)
    return s, b


def supervise(b, soc, advance=15000):
    b.advance(advance)
    if soc is not None:
        b.ent("ecco_battery_soc").publish_state(float(soc))
    config_poll(b)
    b.run_actions(watchdog(b.fw))
    return str(b.ent("dump_recovery_state").state)


s, b = locked_out_then_reboot()
check("P3: START persisted the obligation's Stop SOC with it, bound to its end time (flushed by the START's own durable commit)",
      s.pref_flushed.get("dump_owed_stop_soc_rec") == (((s.g["dump_end_epoch"] & 0xFFFFFF) << 8) | 25), str(s.pref_flushed))
st_hi = supervise(b, 30.0)
st = supervise(b, 20.0)
check("P3 (Window 7 C8): AFTER A RESTART, an owed restore with 244 unproven and the operator lockout - SOC 30 % (above the lease's "
      "25 %): no alarm; SOC 20 %: CRITICAL 'Stop SOC reached' (5178e0f: its RAM-only Stop SOC was gone, no supervision)",
      b.g["dump_target_stop_soc"] < 0 and not st_hi.startswith("CRITICAL")
      and st.startswith("CRITICAL - restore OWED, register 244 not proven out of Allow Export: Stop SOC reached"), f"{st_hi} | {st}")
_, b = locked_out_then_reboot(rec=0)
st = supervise(b, 70.0)
check("P3: the persisted Stop SOC MISSING (an obligation from firmware that never wrote it) is not trusted - CRITICAL at once, "
      "even at 70 % (fail closed)", st.startswith("CRITICAL - restore OWED, register 244 not proven out of Allow Export: Stop SOC "
                                                  "unknown after a restart (fail closed)"), st)
_, b = locked_out_then_reboot()
b.g["dump_owed_stop_soc_rec"] = ((((b.g["dump_end_epoch"] + 600) & 0xFFFFFF) << 8) | 25)
st = supervise(b, 70.0)
check("P3: a persisted Stop SOC bound to ANOTHER obligation (a different end time) is not trusted - CRITICAL (fail closed)",
      "Stop SOC unknown after a restart" in st, st)
_, b = locked_out_then_reboot()
supervise(b, 70.0)
st = supervise(b, None, advance=100000)
check("P3: no fresh SOC for longer than ecco_dump_soc_stale_ms while the restore is owed counts as reached - CRITICAL",
      "no fresh SOC reading (fail closed)" in st, st)
s = lease_at(6000, target=5500)
s.outcome_fn = lambda k, a, c: "error" if (k == "write" and a == 244) else "ok"          # comms path: retries, no lockout
s.execute("request_dump_end", {"reason": ds.CStr("TEST END")})
b = reboot(s)
for k, v in s.pref_flushed.items():
    b.g[k] = v
b.outcome_fn = s.outcome_fn
b.ent("dump_stop_soc").set(25.0)
tick(b)
waited = b.g["dump_restore_next_attempt_ms"] = b.millis() + 300000                    # a long backoff is pending
b.ent("ecco_battery_soc").publish_state(20.0)
b.advance(2000)
sup = next(i for i in FW["interval"] if "restore OWED, register 244 not proven" in str(i))
b.run_actions(sup["then"][:1])                                                          # the supervision lambda alone
check("P3: after a restart WITHOUT the operator lockout (244 write errors, comms retries), SOC below the persisted Stop SOC "
      "cancels a pending 300 s backoff - the owed restore is retried at once", not b.g["dump_operator_needed"]
      and b.g["dump_target_stop_soc"] < 0 and b.g["dump_restore_next_attempt_ms"] == 0,
      f"{b.g['dump_restore_next_attempt_ms']} {b.status()}")
_, b = locked_out_then_reboot()
b.ent("dump_stop_soc").set(50.0)
st = supervise(b, 45.0)
check("P3: a configured Stop SOC raised above the lease's (50 % vs 25 %) also applies - CRITICAL at 45 %",
      "Stop SOC reached" in st, st)

# --- R2b: export readings alternating around the threshold --------------------------------------------------------------------
def alternating(seq, seconds=600):
    s = lease_at(3000, target=3000, max_export=3680, settle=False)

    def fn(i):
        # the battery follows its command (the controller's), PV makes up the rest of the export over a 400 W house load
        e = seq[i % len(seq)] + (i % 2)
        b = float(s.g["dump_target_power"]) + (i % 3)
        return (-e, b, 70.0, e - b + 400.0)
    return run_frames(s, fn, seconds)


t_a, why_a = alternating([3850.0, 3600.0])
check(f"R2b (Window 7): export alternating 3850 / 3600 W around a 3680 W limit (+110 W margin) ends the lease ({t_a} s) - two of "
      f"the last three readings over (5178e0f: never - it needed two CONSECUTIVE)", t_a is not None and t_a <= 31
      and "two of the last three readings over it" in why_a, f"{t_a} {why_a}")
t_b, why_b = alternating([3780.0, 3640.0])
check(f"R2b: alternating 3780 / 3640 W - no reading ever over limit + margin, but an AVERAGE above the limit - ends it ({t_b} s)",
      t_b is not None and t_b <= 61 and "averaging" in why_b, f"{t_b} {why_b}")
t_c, why_c = alternating([3700.0, 3650.0])
check(f"R2b no nuisance: alternating 3700 / 3650 W (mean of four 3675.5 W, just below the limit, never over the margin): the export "
      f"guard never trips (the harness's export ignores the command, so the controller's own NO RESPONSE ends it at {t_c} s)",
      "MAXIMUM GRID EXPORT" not in why_c and (t_c is None or t_c >= 300), f"{t_c} {why_c}")
t_d, why_d = alternating([3570.0 + 40.0, 3570.0 - 40.0, 3570.0])
check(f"R2b no nuisance: export held at the START headroom limit (3570 W) with +-40 W of noise: the export guard never trips "
      f"(ended at {t_d} s: {why_d[:40]})", "MAXIMUM GRID EXPORT" not in why_d and (t_d is None or t_d >= 300), f"{t_d} {why_d}")

# --- C1 / SG-04: FOREIGN slots are never written, so never contained - the alarms name them ---------------------------------
s = lease_at(6000, target=5500)
s.bank[258] = 7777
s.bank[260] = 6500
s.outcome_fn = ACK_244
s.execute("request_dump_end", {"reason": ds.CStr("TEST END")})
retries(s, 3)
block = [s.bank[r] for r in range(256, 262)]
st = s.status()
check("C1 (Window 7): two FOREIGN slots while 244 cannot be proven off - ECCO's own four contained at 500 W, the FOREIGN two never "
      "written - and the status NAMES them as NOT CONTAINED (5178e0f said only that every ECCO-controlled register was held at "
      "500 W)", block == [500, 500, 7777, 500, 6500, 500]
      and "244 NOT proven off; ECCO's own at 500 W; NOT CONTAINED: 258=7777W 260=6500W" in st and len(st) <= 240, st)
s.g["dump_target_stop_soc"] = 25
st = supervise(s, 20.0)
check("C1: the CRITICAL alarm names the uncontained settings too (within Home Assistant's 255 characters)",
      st.startswith("CRITICAL - restore OWED") and st.endswith("; NOT CONTAINED: 258=7777W 260=6500W") and len(st) <= 240, st)
s = lease_at(6000, target=5500)
for r in range(256, 262):
    s.bank[r] = 9001 + r - 256                                                  # every slot FOREIGN, 4-digit values
s.outcome_fn = ACK_244
s.execute("request_dump_end", {"reason": ds.CStr("TEST END")})
retries(s, 3)
lens = [len(s.status())]
s.g["dump_target_stop_soc"] = 25
lens.append(len(supervise(s, 20.0)))
s.g["dump_owed_stop_soc_rec"] = 0
s.g["dump_target_stop_soc"] = -1
lens.append(len(supervise(s, 20.0)))
check("C1: the worst case - all six slots FOREIGN - keeps the status and the CRITICAL alarm within 255 characters "
      f"(lengths {lens})", max(lens) <= 240 and "NOT CONTAINED: 256 257 258 259 260 261" in s.status(), s.status())
# --- HB1 (Window 7's audit of ebdce15): EVERY Dump status / recovery state within Home Assistant's 255 characters ------------
# Home Assistant rejects a state longer than 255 characters (the alarm would vanish). Every publication of dump_status and
# dump_recovery_state is recorded across each operator-lockout / failure branch, with all six slots FOREIGN and maximum
# (5-digit, 65535) register values; each must stay within HB1_MAX (a 15-character margin) and keep, in priority order, the
# critical state, the operator action, register 244's unproven state, ECCO's own containment and the FOREIGN registers.
HB1_MAX = 240
HB1_LONGEST = []


def hb1_watch(sim):
    for eid in ("dump_status", "dump_recovery_state"):
        e = sim.ent(eid)
        orig = e.publish_state

        def pub(v, _orig=orig, _eid=eid):
            HB1_LONGEST.append((len(str(v)), _eid, str(v)))
            return _orig(v)
        e.publish_state = pub
    return sim


def hb1_lease(originals, foreign, outcome_244):
    """A 6000 W lease (originals given), the FOREIGN values placed, 244 failing as given, End and three retries."""
    s = hb1_watch(lease_at(6000, target=5500, originals={244: 2, **{256 + i: v for i, v in enumerate(originals)}}))
    for r, v in foreign.items():
        s.bank[r] = v
    s.outcome_fn = (lambda m: (lambda k, a, c: m if (k == "write" and a == 244) else "ok"))(outcome_244)
    s.execute("request_dump_end", {"reason": ds.CStr("TEST END")})
    return s


def hb1_states(s):
    return str(s.ent("dump_status").state), str(s.ent("dump_recovery_state").state)


SIX_MAX = {256 + i: 65529 + i for i in range(6)}                                 # all six FOREIGN (none = its 65535 original)
ORIG_MAX = [65535] * 6
hb1 = {}
# (a) the verify-mismatch lockout (244 acknowledged, not applied), all six FOREIGN, maximum values
_i0 = len(HB1_LONGEST)
s = hb1_lease(ORIG_MAX, SIX_MAX, "ack_not_applied")
retries(s, 3)
hb1["a"] = (next(v for n, e, v in HB1_LONGEST[_i0:] if e == "dump_status"
                 and v.startswith("OPERATOR DECISION REQUIRED - repeated verify mismatch")), "")
check("HB1 (Window 7: 257 characters) the verify-mismatch operator lockout, all six slots FOREIGN at 5-digit values: within "
      f"{HB1_MAX} characters ({len(hb1['a'][0])}) - lockout, operator action, 244 unproven, the FOREIGN registers (numbers: their "
      "values do not fit and are logged)", s.g["dump_operator_needed"] and len(hb1["a"][0]) <= HB1_MAX
      and hb1["a"][0].startswith("OPERATOR DECISION REQUIRED - repeated verify mismatch")
      and "Force Restore Original" in hb1["a"][0] and "244 NOT proven off" in hb1["a"][0]
      and hb1["a"][0].endswith("NOT CONTAINED: 256 257 258 259 260 261"), hb1["a"][0])
# (b) the same with ONE FOREIGN slot: ECCO's other five contained, the slot named with its value
_i0 = len(HB1_LONGEST)
s = hb1_lease(ORIG_MAX, {258: 65534}, "ack_not_applied")
retries(s, 3)
hb1["b"] = (next(v for n, e, v in HB1_LONGEST[_i0:] if e == "dump_status"
                 and v.startswith("OPERATOR DECISION REQUIRED - repeated verify mismatch")), "")
check(f"HB1: the mismatch lockout with one FOREIGN 5-digit slot ({len(hb1['b'][0])}) keeps all five parts in priority order",
      len(hb1["b"][0]) <= HB1_MAX and hb1["b"][0].endswith("; 244 NOT proven off; ECCO's own at 500 W; NOT CONTAINED: 258=65534W")
      and "Force Restore Original" in hb1["b"][0], hb1["b"][0])
# (c) the comms path (244 write errors): RESTORE WRITE FAILED with the suffix, all six FOREIGN
s = hb1_lease(ORIG_MAX, SIX_MAX, "error")
retries(s, 2)
hb1["c"] = hb1_states(s)
check(f"HB1: the comms-failure status, all six FOREIGN ({len(hb1['c'][0])})", len(hb1["c"][0]) <= HB1_MAX
      and hb1["c"][0].startswith("RESTORE WRITE FAILED") and "244 NOT proven off" in hb1["c"][0], hb1["c"][0])
# (d) the first mismatch (one automatic retry left), all six FOREIGN
s = hb1_lease(ORIG_MAX, SIX_MAX, "ack_not_applied")
hb1["d"] = hb1_states(s)
check(f"HB1: the first verify mismatch ({len(hb1['d'][0])})", len(hb1["d"][0]) <= HB1_MAX
      and hb1["d"][0].startswith("RESTORE VERIFY FAILED") and "244 NOT proven off" in hb1["d"][0], hb1["d"][0])
# (e) the waiting operator status (the restore gate under the lockout), all six FOREIGN
s = hb1_lease(ORIG_MAX, SIX_MAX, "ack_not_applied")
retries(s, 3)
s.advance(15000)
config_poll(s)
s.run_actions(watchdog(s.fw))
hb1["e"] = hb1_states(s)
check(f"HB1: the waiting OPERATOR DECISION REQUIRED status under the lockout ({len(hb1['e'][0])})", len(hb1["e"][0]) <= HB1_MAX
      and hb1["e"][0].startswith("OPERATOR DECISION REQUIRED - use Force Restore Original or Accept Current State")
      and "244 NOT proven off" in hb1["e"][0], hb1["e"][0])
# (f) the CRITICAL alarm - the longest reason (Stop SOC unknown after a restart), all six FOREIGN
s.g["dump_target_stop_soc"] = -1
s.g["dump_owed_stop_soc_rec"] = 0
st = supervise(s, 20.0)
hb1["f"] = (str(s.ent("dump_status").state), st)
check(f"HB1: the CRITICAL alarm with the longest reason and all six FOREIGN ({len(st)}): critical state, operator action, 244, "
      "the FOREIGN registers", len(st) <= HB1_MAX and st.startswith("CRITICAL - restore OWED, register 244 not proven")
      and "operator action now: Force Restore Original" in st and st.endswith("; NOT CONTAINED: 256 257 258 259 260 261"), st)
# (g) the FOREIGN lockout (244 PROVEN out of Allow Export), ONE slot, maximum values (Window 7: 262 characters)
s = hb1_lease(ORIG_MAX, {258: 65534}, "ok")
hb1["g"] = hb1_states(s)
check(f"HB1 (Window 7: 262 characters) the FOREIGN operator lockout with one 5-digit slot ({len(hb1['g'][0])} / recovery state "
      f"{len(hb1['g'][1])}): the decision, what was found, the operator action", s.g["dump_operator_needed"]
      and len(hb1["g"][0]) <= HB1_MAX and len(hb1["g"][1]) <= HB1_MAX
      and hb1["g"][0].startswith("OPERATOR DECISION REQUIRED - ECCO's own settings restored and verified; external change NOT "
                                 "overwritten (register 258 reads 65534W (original 65535W")
      and hb1["g"][0].endswith("; use Force Restore Original or Accept Current State"), hb1["g"][0])
# (h) a FOREIGN 244 (5-digit) - the lockout names register 244
s = hb1_lease(ORIG_MAX, {244: 65535}, "ok")
hb1["h"] = hb1_states(s)
check(f"HB1: the FOREIGN-244 operator lockout ({len(hb1['h'][0])})", len(hb1["h"][0]) <= HB1_MAX
      and "register 244 reads 65535" in hb1["h"][0], hb1["h"][0])
# (i) containment NOT verified (the 256-261 writes also fail) with FOREIGN slots: "export may continue" + the registers
s = hb1_lease(ORIG_MAX, SIX_MAX, "ack_not_applied")
s.outcome_fn = lambda k, a, c: "ack_not_applied" if k == "write" else "ok"
retries(s, 3)
hb1["i"] = hb1_states(s)
check(f"HB1: containment not verified, all six FOREIGN ({len(hb1['i'][0])})", len(hb1["i"][0]) <= HB1_MAX
      and "244 NOT proven off; export may continue; NOT CONTAINED: 256 257 258 259 260 261" in hb1["i"][0], hb1["i"][0])
# (j) no FOREIGN slot, containment verified, the longest head
s = hb1_lease(ORIG_MAX, {}, "ack_not_applied")
retries(s, 3)
hb1["j"] = hb1_states(s)
check(f"HB1: no FOREIGN slot, ECCO's own contained, the mismatch lockout ({len(hb1['j'][0])})", len(hb1["j"][0]) <= HB1_MAX
      and hb1["j"][0].endswith("; register 244 NOT proven out of Allow Export - ECCO's TOU power registers held at the 500 W floor"),
      hb1["j"][0])
worst = max(HB1_LONGEST)
check(f"HB1: EVERY dump_status / dump_recovery_state published in these branches ({len(HB1_LONGEST)} publications) is within "
      f"{HB1_MAX} characters (longest {worst[0]}: {worst[1]})", worst[0] <= HB1_MAX, worst[2])
# Static: the dynamic (concatenated) status publications are exactly the audited ones; every snprintf status buffer is bounded.
_dyn = re.findall(r"id\((dump_status|dump_recovery_state)\)\.publish_state\(\s*std::string\(\"([^\"]{0,40})", FW_TEXT)
check("HB1 static: the concatenated dump_status / dump_recovery_state publications are exactly the eight audited here (no "
      "unaudited dynamic status)", sorted(h for _e, h in _dyn) == sorted(x[:40] for x in [
          "FOREIGN (not overwritten) - ", "OPERATOR DECISION REQUIRED - ECCO's own settings restored and verified",
          "OPERATOR DECISION REQUIRED - repeated verify mismatch", "RESTORE VERIFY FAILED - snapshot retained",
          "RESTORE WRITE FAILED - inverter did not respond", "OPERATOR DECISION REQUIRED - use Force Restore Original",
          "ACCEPTED CURRENT STATE - ", "ACCEPT REFUSED - "]), str(sorted(h for _e, h in _dyn)))
# The two Accept concatenations: "ACCEPT REFUSED - " + the block reason (its longest fixed reason, or the elevated-residue text
# at 5-digit values) and "ACCEPTED CURRENT STATE - " + the residue note + its tail, at their worst case.
_acc = FW_TEXT[FW_TEXT.index("  - id: dump_accept_current_state\n"):]
_acc = _acc[:_acc.index("\n  - id: ", 10)]
_why = [len(x) for x in re.findall(r'why = "((?:[^"\\]|\\.)*)";', _acc)]
_fmt = re.findall(r'snprintf\((e|b), sizeof\((?:e|b)\), "((?:[^"\\]|\\.)*)"', _acc)
_worst_fmt = {w: [len(f.replace("%d", "256").replace("%u", "65535")) for b_, f in _fmt if b_ == w] for w in "eb"}
_refused = len("ACCEPT REFUSED - ") + max(_why + _worst_fmt["e"])
_accepted = len("ACCEPTED CURRENT STATE - ") + max(_worst_fmt["b"]) + len("; export is not enabled; no inverter write performed")
check(f"HB1 static: the Accept texts at their worst case are within {HB1_MAX} characters (refused {_refused}, accepted "
      f"{_accepted})", bool(_why) and bool(_fmt) and _refused <= HB1_MAX and _accepted <= HB1_MAX, f"{_why} {_worst_fmt}")
_lits = [m for m in re.findall(r"id\((?:dump_status|dump_recovery_state)\)\.publish_state\(\s*\"((?:[^\"\\]|\\.)*)\"", FW_TEXT)]
check(f"HB1 static: every fixed dump_status / dump_recovery_state text is within {HB1_MAX} characters (longest "
      f"{max(len(x) for x in _lits)}, {len(_lits)} texts)", max(len(x) for x in _lits) <= HB1_MAX)

check("the final rework adds no Modbus write and no read: the restore's six one-register writes and its one pre-read are still "
      "the only additions, register 245 is never written",
      FW_TEXT.count("write_multiple_registers") == OLD_TEXT.count("write_multiple_registers") + 6
      and FW_TEXT.count("read_holding_registers") == OLD_TEXT.count("read_holding_registers") + 1
      and "start_address: 245" not in FW_TEXT)


# ==================================================================================================================================
print("\n[C] write surface and NVS")
# ==================================================================================================================================
OPS = ("write_single_register", "read_input_registers")
check("no new FC06 write or input-register read (counts equal to the fcp1 firmware)", all(FW_TEXT.count(o) == OLD_TEXT.count(o) for o in OPS))
check("fcp2 rework: exactly SIX new writes - the restore's one-register writes of 256..261, so a FOREIGN slot is never written "
      "(registers already in the write surface; no new register)",
      FW_TEXT.count("write_multiple_registers") == OLD_TEXT.count("write_multiple_registers") + 6
      and all(FW_TEXT.count(f"start_address: {r}\n                      values: !lambda 'return std::vector<uint16_t>{{id(dump_restore_v{r - 256})}};'") == 1
              for r in range(256, 262)))
check("exactly ONE new read: the restore's ownership pre-read of 244-261 (18 registers)",
      FW_TEXT.count("read_holding_registers") == OLD_TEXT.count("read_holding_registers") + 1
      and FW_TEXT.count("start_address: 244\n                count: 18") == 1)
w_new = sorted({int(m) for m in re.findall(r"write_multiple_registers:\s*\n\s*modbus_id: \w+\s*\n\s*address: 0x01\s*\n\s*start_address: (\d+)", FW_TEXT)})
w_old = sorted({int(m) for m in re.findall(r"write_multiple_registers:\s*\n\s*modbus_id: \w+\s*\n\s*address: 0x01\s*\n\s*start_address: (\d+)", OLD_TEXT)})
check("register 245 is never written; the set of written start addresses is UNCHANGED (257..261 are already written one slot at "
      "a time by Manual TOU)", 245 not in w_new and w_new == w_old, str(sorted(set(w_new) ^ set(w_old))))
import _fcp2_scope as F  # noqa: E402
gl = {g["id"]: g for g in FW["globals"]}
PERSISTED_NEW = {g["id"] for g in FW["globals"] if str(g.get("restore_value")).lower() in ("yes", "true")} - \
    {g["id"] for g in OLD["globals"] if str(g.get("restore_value")).lower() in ("yes", "true")}
check(f"every global fcp2 adds ({len(F.NEW_GLOBAL_IDS)}) is RAM only (restore_value no) EXCEPT the final rework's ONE persisted "
      "dump_owed_stop_soc_rec (a NEW key - firmware without it ignores it; no existing NVS key is changed)",
      all(str(gl[g].get("restore_value")).lower() in ("no", "false") for g in F.NEW_GLOBAL_IDS if g != "dump_owed_stop_soc_rec")
      and PERSISTED_NEW == {"dump_owed_stop_soc_rec"}
      and {g["id"] for g in OLD["globals"] if str(g.get("restore_value")).lower() in ("yes", "true")}
      <= {g["id"] for g in FW["globals"] if str(g.get("restore_value")).lower() in ("yes", "true")}, str(PERSISTED_NEW))
check("no durable load site, tag or schema is touched; ONE new commit site - the operator-needed retry record of the FOREIGN "
      "lockout, an existing record written exactly as the mismatch lockout writes it",
      all(FW_TEXT.count(tok) == OLD_TEXT.count(tok) for tok in ("load_record(", "load_record_status("))
      and FW_TEXT.count("commit_record(") == OLD_TEXT.count("commit_record(") + 1
      and FW_TEXT.count("ecco_durable::DUMP_TO_GRID_RETRY_TAG") == OLD_TEXT.count("ecco_durable::DUMP_TO_GRID_RETRY_TAG") + 1)

# ==================================================================================================================================
print("\n[P] the post-export declaration (PEX entry fcp2)")
# ==================================================================================================================================
E = chain.CHAIN.entry("fcp2")
ids = [e.id for e in chain.POST_EXPORT_ENTRIES]
check("fcp2 is appended right after fcp1", ids[-1] == "fcp2" and chain.CHAIN.prev_id("fcp2") == "fcp1", str(ids))
check("fcp2's reverter reproduces the fcp1 firmware byte for byte, and its checkpoint is the live firmware",
      F.sha(F.pre_fcp2_firmware(FW_TEXT)) == F.BASE_FW_SHA == chain.CHAIN.entry("fcp1").checkpoints[chain.FIRMWARE]
      and E.checkpoints == {chain.FIRMWARE: F.sha(FW_TEXT)})
check("fcp2's fingerprint is sealed and linked to fcp1's", E.fingerprint == _pex.fingerprint(E)   # PEX: hash link
      and _pex.record(E)["parent"] == chain.CHAIN.entry("fcp1").fingerprint)
check("fcp2 declares its added files and each exists", E.added_files == F.ADDED_FILES and all((ROOT / f).is_file() for f in F.ADDED_FILES))

print("")
if FAILURES:
    print(f"{len(FAILURES)} FAILED, {PASSES} passed")
    sys.exit(1)
print(f"All {PASSES} fcp2 safety-hardening checks passed.")
print("They execute the firmware source offline; they prove nothing about ESPHome timing, the compiled binary or the inverter.")
