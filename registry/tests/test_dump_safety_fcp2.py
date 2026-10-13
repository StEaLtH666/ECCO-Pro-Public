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
  [C]         write surface and NVS: no new write, exactly one new read (the pre-read), register 245 never written, every new
              global RAM only
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


def tick(sim, ms=15000, soc=70.0, battery_w=None):
    """One 15 s watchdog tick with fresh SOC, grid and configuration readback."""
    sim.advance(ms)
    sim.ent("ecco_battery_soc").publish_state(soc)
    if battery_w is not None:
        sim.ent("ecco_battery_power").publish_state(float(battery_w))
    sim.ent("ecco_grid_ct_power").publish_state(sim.grid_w)
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
            s.ent("ecco_grid_ct_power").publish_state(s.grid_w)
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
        s.ent("ecco_grid_ct_power").publish_state(s.grid_w)
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
    s.ent("ecco_grid_ct_power").publish_state(s.grid_w)
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
        check("an EXTERNAL change to 258 during the lease: the drift END turns export off (244 was ECCO's) but 258's 6500 W is "
              "KEPT, the block is not written, the obligation is kept and the operator is asked (durably)",
              s.bank[258] == 6500 and s.bank[244] == ORIGINAL[244] and s.bank[256] == 1000 and marker(s) == 1
              and s.g["dump_operator_needed"] and s.nvs[RETRY].operator_needed == 1
              and s.status().startswith("OPERATOR DECISION REQUIRED - an external change was found and NOT overwritten")
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
print("\n[C] write surface and NVS")
# ==================================================================================================================================
OPS = ("write_multiple_registers", "write_single_register", "read_input_registers")
check("no new Modbus WRITE operation (counts equal to the fcp1 firmware)", all(FW_TEXT.count(o) == OLD_TEXT.count(o) for o in OPS))
check("exactly ONE new read: the restore's ownership pre-read of 244-261 (18 registers)",
      FW_TEXT.count("read_holding_registers") == OLD_TEXT.count("read_holding_registers") + 1
      and FW_TEXT.count("start_address: 244\n                count: 18") == 1)
w_new = sorted({int(m) for m in re.findall(r"write_multiple_registers:\s*\n\s*modbus_id: \w+\s*\n\s*address: 0x01\s*\n\s*start_address: (\d+)", FW_TEXT)})
check("register 245 is never written; the written start addresses are unchanged", 245 not in w_new and w_new == sorted(
    {int(m) for m in re.findall(r"write_multiple_registers:\s*\n\s*modbus_id: \w+\s*\n\s*address: 0x01\s*\n\s*start_address: (\d+)", OLD_TEXT)}))
import _fcp2_scope as F  # noqa: E402
gl = {g["id"]: g for g in FW["globals"]}
check(f"every global fcp2 adds ({len(F.NEW_GLOBAL_IDS)}) is RAM only (restore_value no): no NVS key added or changed",
      all(str(gl[g].get("restore_value")).lower() in ("no", "false") for g in F.NEW_GLOBAL_IDS)
      and {g["id"] for g in FW["globals"] if str(g.get("restore_value")).lower() in ("yes", "true")}
      == {g["id"] for g in OLD["globals"] if str(g.get("restore_value")).lower() in ("yes", "true")})
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
