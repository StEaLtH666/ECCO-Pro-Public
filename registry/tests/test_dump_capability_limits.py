#!/usr/bin/env python3
"""fcp1: inverter capability profile + the persisted Dump operating limits (power ceiling, maximum net grid export).

Every behavioural check EXECUTES the real firmware source through registry/tests/_dump_sim.py (the number entities' set_action
lambdas, the on_boot validation, the START script, the controller, the sensor on_value hooks and the 15 s watchdog), against an
in-memory inverter. It proves the firmware SOURCE's control flow, not ESPHome timing, the compiled binary or the inverter.

  [0] profile        capability is a profile value (no global maximum), compile-time consistency, the profile registry
  [1] definitions    the four quantities and their units / ranges, as entities
  [2] factory        3000 W ceiling, export NOT CONFIGURED: every START refused, nothing written
  [3] settings       raises need the arm and idle; reductions always; invalid / NaN / off-step refused; the arm expires
  [4] manual entry   a configured site starts; the target must be within the export limit; the ceiling is latched
  [5] latch          a later raise never reaches a running lease; a reduction lowers it at once (verified step-down)
  [6] export guard   3 of the last 4 fresh CT samples over the limit end the lease; 2 do not; grace; a mid-lease reduction applies
  [7] reboot / NVS   persisted values survive; corrupt, mismatched and out-of-range values leave the limits INVALID (START refused);
                     the way back is a re-set; no durable record schema changes; preference keys stay distinct
  [8] HA outage      the limits are dongle state: no Home Assistant entity is read to enforce them
  [9] full capability every registry profile is self-consistent; a larger profile's capability is reachable, never more
  [10] write surface no new Modbus operation, register 245 never written
  [11] PEX           the fcp1 declaration
"""
from __future__ import annotations

import hashlib
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _dump_sim as ds  # noqa: E402

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
# fcp2: this suite proves fcp1's own firmware; the later firmware entry fcp2 (safety hardening) is undone exactly by the chain (PEX).
import _scope_chain as chain  # noqa: E402
FW_TEXT = chain.CHAIN.as_of(chain.FIRMWARE, "fcp1", FW_PATH.read_text(encoding="utf-8"))
FW = ds.load_firmware_text(FW_TEXT)
SUBS = FW["_substitutions"]
CAP = int(SUBS["ecco_dump_capability_w"])
FLOOR = int(SUBS["ecco_dump_controller_min_ceiling_w"])
DEFAULT = int(SUBS["ecco_dump_controller_max_ceiling_w"])
ORIGINAL = {244: 2, 256: 8000, 257: 8000, 258: 7000, 259: 8000, 260: 8000, 261: 5000}
WATCHDOG = ds.find_interval(FW, "dump_overpower_samples")
NUMBERS = {n["id"]: n for n in FW["number"]}
ARM_INTERVAL = next(i for i in FW["interval"] if "dump_limits_arm" in str(i))


# --- the same harness shape as test_dump_to_grid_behaviour.py (kept local: that suite runs on import) ---------------------------
def config_poll(sim):
    sim.g["cfg_block_b_dispatch_seq"] += 1
    sim.g["manual_cfg_reg244_raw"] = sim.bank.get(244, 0)
    for r in range(256, 262):
        sim.g[f"manual_cfg_reg{r}_raw"] = sim.bank.get(r, 0)
    sim.g["cfg_block_b_seq"] += 1
    sim.g["cfg_block_b_ok_ms"] = sim.millis()
    sim.g["cfg_block_b_response_dispatch_seq"] = sim.g["cfg_block_b_dispatch_seq"]


def fresh(limits="configured", target=1000, soc=70.0, grid_w=None, ceiling=None, max_export=None):
    sim = ds.Sim(FW, dump_limits=limits)
    if ceiling is not None or max_export is not None:
        sim.configure_dump_limits(DEFAULT if ceiling is None else ceiling, CAP if max_export is None else max_export)
    sim.bank.update(ORIGINAL)
    sim.ent("dump_export_power").set(float(target))
    sim.ent("dump_stop_soc").set(25.0)
    sim.ent("dump_duration_minutes").set(30.0)
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


def tick(sim, ms=15000, battery_w=None, grid_w=None):
    sim.advance(ms)
    if battery_w is not None:
        sim.ent("ecco_battery_power").publish_state(battery_w)
    if grid_w is not None:
        sim.grid_w = grid_w
    sim.ent("ecco_grid_ct_power").publish_state(sim.grid_w)
    config_poll(sim)
    sim.run_actions(WATCHDOG)


def set_number(sim, number_id, value):
    sim.run_actions(NUMBERS[number_id]["set_action"], {"x": float(value)})


def arm(sim):
    sim.ent("dump_limits_arm").state = True
    sim.g["dump_limits_arm_ms"] = sim.millis()


def status(sim):
    return str(sim.ent("dump_limits_status").state)


def writes(sim):
    return [op for op in sim.modbus_log if op[0] == "write"]


def start(sim):
    sim.execute("start_dump_to_grid_override")
    return bool(sim.g["dump_active_persisted"])


def dump_status(sim):
    return str(sim.ent("dump_status").state)


# ==================================================================================================================================
print("[0] the inverter capability profile")
# ==================================================================================================================================
check("the profile is named and its capability is a profile substitution (8000 W for the reference profile)",
      SUBS["ecco_inverter_profile_id"] == "deye_1ph_lv_8kw" and CAP == 8000
      and int(SUBS["ecco_inverter_tou_power_ceiling_w"]) == 8000)
check("no global 8000 W maximum remains: the DTGP1 'architectural maximum' assertion is gone and no '<= 8000' bound is compiled",
      "8000 W is the architectural maximum" not in FW_TEXT and not re.search(r"<=\s*8000\b", FW_TEXT))
boot_checks = next(it["lambda"] for it in FW["esphome"]["on_boot"]["then"]
                   if isinstance(it, dict) and "ecco_dump_capability_w" in str(it.get("lambda", "")) and "static_assert" in it["lambda"])
for needle in ("${ecco_dump_controller_max_ceiling_w} <= ${ecco_dump_capability_w}",
               "${ecco_dump_capability_w} <= ${ecco_inverter_tou_power_ceiling_w}",
               "${ecco_inverter_tou_power_ceiling_w} <= 65535",
               "${ecco_dump_limits_default_check} ==\n"):
    check(f"compile-time profile check present: {needle.strip()!r}", needle in boot_checks)
check("the factory integrity value is the integrity value of the factory limits",
      int(SUBS["ecco_dump_limits_default_check"]) == DEFAULT + 3 * 0 + 7 * CAP + 12345)
REG = yaml.safe_load((ROOT / "registry" / "inverter_profiles.yaml").read_text(encoding="utf-8"))
ref = next(p for p in REG["profiles"] if p["id"] == SUBS["ecco_inverter_profile_id"])
# fcp2 adds a later profile key (the runaway DC allowance), checked against the live firmware by test_dump_safety_fcp2.py.
check("the firmware's reference profile is exactly the registry's entry for it (no drift)",
      all(str(ref["substitutions"][k]) == SUBS[k] for k in ref["substitutions"] if k != "ecco_dump_runaway_dc_allowance_pct"),
      str(ref["substitutions"]))


def profile_ok(s):
    cap, tou, rnd, flo, dflt = (int(s[k]) for k in ("ecco_dump_capability_w", "ecco_inverter_tou_power_ceiling_w",
                                                     "ecco_dump_controller_round_w", "ecco_dump_controller_min_ceiling_w",
                                                     "ecco_dump_controller_max_ceiling_w"))
    return dflt <= cap and cap % rnd == 0 and flo < cap and cap <= tou and tou <= 65535


base = {k: SUBS[k] for k in ("ecco_dump_controller_round_w", "ecco_dump_controller_min_ceiling_w", "ecco_dump_controller_max_ceiling_w")}
for p in REG["profiles"]:
    check(f"registry profile {p['id']}: self-consistent under the firmware's own compile-time rules",
          profile_ok({**SUBS, **base, **{k: str(v) for k, v in p["substitutions"].items()}}))
check("the compile-time rules refuse an inconsistent profile (capability above its TOU bound; capability below the default)",
      not profile_ok({**SUBS, "ecco_dump_capability_w": "9000"}) and not profile_ok({**SUBS, "ecco_dump_capability_w": "2000"}))

# ==================================================================================================================================
print("\n[1] definitions: four quantities, four separate enforcements")
# ==================================================================================================================================
names = {e.get("name"): e for sec in ("sensor", "number", "switch", "text_sensor") for e in FW[sec] if isinstance(e, dict)}
pc, mx = NUMBERS["dump_op_ceiling_number"], NUMBERS["dump_max_export_number"]
check("Dump to Grid Power Ceiling: W, 500 .. the profile capability, 100 W steps (the TOU battery-discharge power the controller may command)",
      pc["name"] == "Dump to Grid Power Ceiling" and pc["unit_of_measurement"] == "W" and ds.substitute(str(pc["min_value"]), SUBS) == str(FLOOR)
      and ds.substitute(str(pc["max_value"]), SUBS) == str(CAP) and ds.substitute(str(pc["step"]), SUBS) == "100")
check("Dump to Grid Max Grid Export: W, 0 (not configured) .. capability, 10 W steps (NET export at the grid CT)",
      mx["name"] == "Dump to Grid Max Grid Export" and mx["unit_of_measurement"] == "W" and str(mx["min_value"]) == "0"
      and ds.substitute(str(mx["max_value"]), SUBS) == str(CAP) and str(mx["step"]) == "10")
check("the capability, the lease ceiling and the profile identity are separate read-only entities",
      {"Dump to Grid Capability", "Dump to Grid Lease Ceiling", "Inverter Capability Profile", "Dump Power Limits Status",
       "Dump Power Limits Write Enable"} <= set(names))
sim = ds.Sim(FW)
check("capability sensor reads the profile capability; lease ceiling unavailable when idle",
      sim.run_lambda(names["Dump to Grid Capability"]["lambda"]) == CAP
      and sim.run_lambda(names["Dump to Grid Lease Ceiling"]["lambda"]) != sim.run_lambda(names["Dump to Grid Lease Ceiling"]["lambda"]))
check("battery discharge stays a MEASURED quantity guarded relative to the command (the runaway guards read dump_target_power, "
      "bounded by the lease ceiling) and net export a measured CT quantity guarded against the export limit: independent paths",
      "id(dump_target_power)" in str(FW["sensor"]) and "dump_export_window" in str(next(s for s in FW["sensor"] if s.get("id") == "ecco_grid_ct_power")))

# ==================================================================================================================================
print("\n[2] factory state: ceiling 3000 W, export NOT CONFIGURED")
# ==================================================================================================================================
sim = fresh("factory")
check("factory limits are VALID with the 3000 W ceiling and the maximum grid export NOT CONFIGURED",
      sim.g["dump_limits_valid"] and sim.g["dump_op_ceiling_w"] == DEFAULT == 3000 and sim.g["dump_max_export_w"] == 0
      and "NOT CONFIGURED" in status(sim), status(sim))
ok = start(sim)
check("a manual START is refused: maximum grid export not configured; nothing written; write enable off; no attempt counted",
      not ok and dump_status(sim).startswith("REJECTED - maximum grid export not configured") and writes(sim) == []
      and sim.ent("dump_write_enable").state is False and sim.g["dump_start_attempts"] == 0, dump_status(sim))

# ==================================================================================================================================
print("\n[3] changing the limits from Home Assistant (the number entities' own validated set_actions)")
# ==================================================================================================================================
sim = fresh("factory")
set_number(sim, "dump_max_export_number", 3680)
check("a RAISE without the arm is refused and changes nothing", sim.g["dump_max_export_w"] == 0 and status(sim).startswith("REFUSED")
      and "arm" in status(sim), status(sim))
arm(sim)
set_number(sim, "dump_max_export_number", 3680)
check("with the arm, while idle: accepted, persisted value and integrity value updated, arm used up",
      sim.g["dump_max_export_w"] == 3680 and sim.g["dump_limits_check"] == 3000 + 3 * 3680 + 7 * CAP + 12345
      and sim.ent("dump_limits_arm").state is False and status(sim).startswith("VALID"), status(sim))
arm(sim)
sim.advance(61_000)
set_number(sim, "dump_op_ceiling_number", 4000)
check("an arm older than its 60 s window no longer authorises a raise", sim.g["dump_op_ceiling_w"] == 3000, status(sim))
sim.ent("dump_limits_arm").state = True
sim.g["dump_limits_arm_ms"] = sim.millis() - 61_000
sim.run_actions(ARM_INTERVAL["then"])
check("...and the arm interval turns an expired arm off", sim.ent("dump_limits_arm").state is False)
for bad in (4050, 499, CAP + 100, float("nan")):
    arm(sim)
    set_number(sim, "dump_op_ceiling_number", bad)
    check(f"an invalid power ceiling request ({bad}) is refused even when armed", sim.g["dump_op_ceiling_w"] == 3000
          and status(sim).startswith("REFUSED"), status(sim))
arm(sim)
set_number(sim, "dump_max_export_number", 3685)
check("an off-step export request (3685 W) is refused", sim.g["dump_max_export_w"] == 3680)
sim.ent("dump_limits_arm").state = False
set_number(sim, "dump_op_ceiling_number", 2000)
set_number(sim, "dump_max_export_number", 2500)
check("REDUCTIONS need no arm and are accepted", sim.g["dump_op_ceiling_w"] == 2000 and sim.g["dump_max_export_w"] == 2500,
      status(sim))
arm(sim)
set_number(sim, "dump_op_ceiling_number", CAP)
check("the full profile capability is a reachable setting (armed, idle)", sim.g["dump_op_ceiling_w"] == CAP)

# ==================================================================================================================================
print("\n[4] manual entry on a configured site; the export target must be within the export limit")
# ==================================================================================================================================
sim = fresh(ceiling=3000, max_export=900, target=1000)
check("a target above the configured maximum grid export is refused, nothing written",
      not start(sim) and dump_status(sim).startswith("REJECTED - requested export is above the configured maximum grid export")
      and writes(sim) == [], dump_status(sim))
sim = fresh(ceiling=4000, max_export=3680, target=1000)
ok = start(sim)
check("a configured site starts (manual entry): ACTIVE, verified writes", ok and writes(sim) != [], dump_status(sim))
check("the lease ceiling is LATCHED at START from the persisted setting", sim.g["dump_lease_ceiling_w"] == 4000)

# ==================================================================================================================================
print("\n[5] the latch: a raise never reaches a running lease; a reduction lowers it at once")
# ==================================================================================================================================
arm(sim)
set_number(sim, "dump_op_ceiling_number", 6000)
check("a raise during a lease is refused (raises only while idle), the lease ceiling unchanged",
      sim.g["dump_op_ceiling_w"] == 4000 and sim.g["dump_lease_ceiling_w"] == 4000 and "idle" in status(sim), status(sim))
sim.g["dump_op_ceiling_w"] = 6000          # even if the stored setting were higher, the lease never reads it again
for _ in range(6):
    tick(sim, grid_w=-200.0, battery_w=float(sim.g["dump_target_power"]))
check("the controller never commands above the LATCHED ceiling even with a higher stored setting",
      sim.g["dump_target_power"] <= 4000 and sim.g["dump_lease_ceiling_w"] == 4000, str(sim.g["dump_target_power"]))
sim = fresh(ceiling=4000, max_export=3680, target=1000)
start(sim)
sim.g["dump_target_power"] = 3500
sim.bank.update({r: 3500 for r in range(256, 262)})
sim.g["dump_last_controller_update_ms"] = sim.millis()
n_before = len(writes(sim))
set_number(sim, "dump_op_ceiling_number", 2000)
check("a mid-lease REDUCTION is accepted without the arm and lowers the lease ceiling at once",
      sim.g["dump_op_ceiling_w"] == 2000 and sim.g["dump_lease_ceiling_w"] == 2000, status(sim))
tick(sim, ms=1000, battery_w=3500.0)
new_writes = writes(sim)[n_before:]
check("the next watchdog tick steps the command down to the reduced ceiling with a verified write, without waiting for the settle "
      "time or a grid error", sim.g["dump_target_power"] == 2000 and any(op[1] == 256 and op[2][0] == 2000 for op in new_writes),
      f"{sim.g['dump_target_power']} {new_writes}")
set_number(sim, "dump_op_ceiling_number", 3000)
check("raising it back during the same lease is refused; the lease stays at the reduced ceiling",
      sim.g["dump_lease_ceiling_w"] == 2000 and sim.g["dump_op_ceiling_w"] == 2000)

# ==================================================================================================================================
print("\n[6] the net grid export guard (independent of the power ceiling and the runaway guards)")
# ==================================================================================================================================


def settled(max_export=3000, target=3000):
    s = fresh(ceiling=3000, max_export=max_export, target=target)
    start(s)
    s.advance(60_000)
    return s


def export_ended(s):
    """The lease was ended by the export guard (its own end reason), not by any other guard."""
    return any("MAXIMUM GRID EXPORT EXCEEDED" in str(p.get("reason", "")) for i, p in s.executed if i == "request_dump_end")


s = settled(3000)
for g in (-3200.0, -3200.0, -1000.0):
    tick(s, ms=10_000, grid_w=g)
check("2 of the last 4 samples over the limit (3000 W + 100 W margin): the export guard does not end the lease",
      not export_ended(s) and bin(s.g["dump_export_window"]).count("1") == 2, bin(s.g["dump_export_window"]))
tick(s, ms=10_000, grid_w=-3200.0)
check("3 of the last 4 over: the watchdog ends the lease with MAXIMUM GRID EXPORT EXCEEDED (its own reason)",
      export_ended(s) and (s.g["dump_restore_requested"] or not s.g["dump_active_persisted"]),
      str([p for i, p in s.executed if i == "request_dump_end"][:1]))
s = settled(3000)
for g in (-3090.0,) * 4:
    tick(s, ms=10_000, grid_w=g)
check("export within the margin (3090 W against 3000 W + 100 W) never trips the export guard", not export_ended(s)
      and s.g["dump_export_window"] == 0)
s = fresh(ceiling=3000, max_export=3000, target=3000)
start(s)
for g in (-5000.0,) * 2:
    tick(s, ms=10_000, grid_w=g)
check("during the lease-start grace samples are not counted", s.g["dump_active_persisted"] and s.g["dump_export_window"] == 0)
s = settled(3000)
set_number(s, "dump_max_export_number", 1500)
for g in (-1800.0,) * 3:
    tick(s, ms=10_000, grid_w=g)
check("a mid-lease REDUCTION of the export limit takes effect on the guard at once", export_ended(s))

# ==================================================================================================================================
print("\n[7] reboot, persistence, corrupt and mismatched settings, NVS compatibility")
# ==================================================================================================================================
PERSISTED = [g["id"] for g in FW["globals"] if str(g.get("restore_value")).lower() in ("true", "yes")]
NEW_PERSISTED = ["dump_op_ceiling_w", "dump_max_export_w", "dump_limits_cap_w", "dump_limits_check"]


def reboot(sim, **override):
    """A reboot: RAM globals back to their initial values, restore_value globals keep what was stored, on_boot validates."""
    stored = {k: sim.g[k] for k in PERSISTED}
    stored.update(override)
    new = fresh("factory")      # the rest of the site as fresh() sets it up, so a START reaches the limits gate
    for k, v in stored.items():
        new.g[k] = v
    new.run_dump_limits_boot()
    return new


a = fresh("factory")
arm(a)
set_number(a, "dump_max_export_number", 3680)
arm(a)
set_number(a, "dump_op_ceiling_number", 5000)
b = reboot(a)
check("the persisted limits survive a reboot and validate", b.g["dump_limits_valid"] and b.g["dump_op_ceiling_w"] == 5000
      and b.g["dump_max_export_w"] == 3680, status(b))
for label, override in (("an incomplete or corrupt save (integrity mismatch)", {"dump_op_ceiling_w": 8000}),
                        ("values stored for a different capability profile", {"dump_limits_cap_w": 6000}),
                        ("an out-of-range stored ceiling", {"dump_op_ceiling_w": 9000, "dump_limits_check": 9000 + 3 * 3680 + 7 * CAP + 12345}),
                        ("an off-step stored ceiling", {"dump_op_ceiling_w": 5050, "dump_limits_check": 5050 + 3 * 3680 + 7 * CAP + 12345}),
                        ("a negative stored export", {"dump_max_export_w": -10, "dump_limits_check": 5000 - 30 + 7 * CAP + 12345})):
    c = reboot(a, **override)
    check(f"{label}: limits INVALID (never adopted), the status says why", not c.g["dump_limits_valid"]
          and status(c).startswith("INVALID"), status(c))
    ok = start(c)
    check(f"...and a START is refused as invalid, nothing written", not ok and writes(c) == []
          and dump_status(c).startswith("REJECTED - Dump power limits are invalid"), dump_status(c))
c = reboot(a, dump_limits_cap_w=6000)
set_number(c, "dump_op_ceiling_number", 3000)
check("leaving INVALID needs the arm (a reduction alone is not enough)", not c.g["dump_limits_valid"], status(c))
arm(c)
set_number(c, "dump_op_ceiling_number", 3000)
check("...armed and idle, re-setting the ceiling rewrites the stored capability and integrity: VALID again",
      c.g["dump_limits_valid"] and c.g["dump_limits_cap_w"] == CAP, status(c))
# NVS compatibility with the rollback firmware (the dtgp1 / live firmware): every existing persisted global keeps its id, type and
# initial value; the new keys are new ids only; the durable record headers are untouched.
import _scope_chain as chain  # noqa: E402
import _pex  # noqa: E402  (PEX: the firmware as of dtgp1 - the rollback firmware's source)
OLD = ds.load_firmware_text(chain.CHAIN.as_of(chain.FIRMWARE, "dtgp1", FW_TEXT))   # PEX: fcp1 undone exactly
old_persist = {g["id"]: (g["type"], str(g.get("initial_value"))) for g in OLD["globals"]
               if str(g.get("restore_value")).lower() in ("true", "yes")}
new_persist = {g["id"]: (g["type"], str(g.get("initial_value"))) for g in FW["globals"]
               if str(g.get("restore_value")).lower() in ("true", "yes")}
check(f"every one of the {len(old_persist)} persisted globals of the rollback firmware is unchanged (id, type, initial value)",
      all(new_persist.get(k) == v for k, v in old_persist.items()), str([k for k, v in old_persist.items() if new_persist.get(k) != v]))
check("fcp1 adds exactly four persisted ids, none reusing an old id", sorted(set(new_persist) - set(old_persist)) == sorted(NEW_PERSISTED))
check("fcp1 edits ONLY the main firmware YAML (no header, include or other firmware file: the durable record headers are the "
      "rollback firmware's, pinned file by file by test_failback_shadow_ha_contract.py)",
      set(chain.CHAIN.entry("fcp1").reverts) == {chain.FIRMWARE} and not chain.CHAIN.entry("fcp1").includes_added)
check("no durable commit / load site, tag or schema is touched by fcp1",
      all(FW_TEXT.count(tok) == OLD["_text"].count(tok) for tok in ("commit_record(", "load_record(", "load_record_status(", "_TAG")))

# ==================================================================================================================================
print("\n[8] Home Assistant outage: the limits are dongle state")
# ==================================================================================================================================
limit_code = "\n".join([str(NUMBERS[n]["set_action"]) for n in ("dump_op_ceiling_number", "dump_max_export_number")]
                       + [str(it) for it in FW["esphome"]["on_boot"]["then"] if "dump_limits_valid" in str(it)])
ha_ids = {s.get("id") for sec in ("sensor", "binary_sensor", "text_sensor") for s in FW[sec] if isinstance(s, dict)
          and s.get("platform") == "homeassistant"}
check("no Home Assistant-sourced entity is read by the limits' validation, the START gate or the guards",
      not any(f"id({h})" in limit_code + str(FW["script"]) + str(WATCHDOG) for h in ha_ids if h), str(sorted(h for h in ha_ids if h)))
s = settled(3000)
for g in (-3300.0,) * 3:
    tick(s, ms=10_000, grid_w=g)        # no Home Assistant anywhere in this sim
check("with no Home Assistant at all, a running lease is still bounded by the export guard and ended by the dongle",
      export_ended(s))

# ==================================================================================================================================
print("\n[9] full-capability profiles")
# ==================================================================================================================================
big = FW_TEXT.replace('ecco_inverter_tou_power_ceiling_w: "8000"', 'ecco_inverter_tou_power_ceiling_w: "12000"', 1) \
             .replace('ecco_dump_capability_w: "8000"', 'ecco_dump_capability_w: "12000"', 1)
BIG = ds.load_firmware_text(big)
bs = ds.Sim(BIG, dump_limits="factory")
bs.ent("dump_limits_arm").state = True
bs.g["dump_limits_arm_ms"] = bs.millis()
bs.run_actions(next(n for n in BIG["number"] if n["id"] == "dump_op_ceiling_number")["set_action"], {"x": 12000.0})
check("a 12 kW profile build accepts a 12000 W ceiling (no hidden 8000 W cap)", bs.g["dump_op_ceiling_w"] == 12000, str(bs.ent("dump_limits_status").state))
bs.ent("dump_limits_arm").state = True
bs.g["dump_limits_arm_ms"] = bs.millis()
bs.run_actions(next(n for n in BIG["number"] if n["id"] == "dump_op_ceiling_number")["set_action"], {"x": 12100.0})
check("...but never more than that profile's capability", bs.g["dump_op_ceiling_w"] == 12000)
s = fresh(ceiling=CAP, max_export=CAP, target=1000)
start(s)
check("on this profile the lease ceiling reaches the full 8000 W capability when configured so", s.g["dump_lease_ceiling_w"] == CAP)

# ==================================================================================================================================
print("\n[10] write surface")
# ==================================================================================================================================
w_new = sorted({int(m) for m in re.findall(r"write_multiple_registers:\s*\n\s*modbus_id: \w+\s*\n\s*address: 0x01\s*\n\s*start_address: (\d+)", FW_TEXT)})
w_old = sorted({int(m) for m in re.findall(r"write_multiple_registers:\s*\n\s*modbus_id: \w+\s*\n\s*address: 0x01\s*\n\s*start_address: (\d+)", OLD["_text"])})
check("the set of written start addresses is unchanged; register 245 is never written",
      w_new == w_old and 245 not in w_new and FW_TEXT.count("write_multiple_registers") == OLD["_text"].count("write_multiple_registers")
      and FW_TEXT.count("read_holding_registers") == OLD["_text"].count("read_holding_registers"), f"{w_new}")

# ==================================================================================================================================
print("\n[11] the post-export declaration (PEX entry fcp1)")
# ==================================================================================================================================
import _fcp1_scope as F  # noqa: E402
E = chain.CHAIN.entry("fcp1")
ids = [e.id for e in chain.POST_EXPORT_ENTRIES]
check("fcp1 is appended right after ovw2 (re-chained on public main aafa03e5)", "fcp1" in ids and chain.CHAIN.prev_id("fcp1") == "ovw2", str(ids))
check("fcp1's reverter reproduces the dtgp1 firmware byte for byte, and its checkpoint is the live firmware",
      F.sha(F.pre_fcp1_firmware(FW_TEXT)) == F.BASE_FW_SHA == chain.CHAIN.entry("dtgp1").checkpoints[chain.FIRMWARE]
      and E.checkpoints == {chain.FIRMWARE: F.sha(FW_TEXT)})
check("fcp1's fingerprint is sealed and linked to ovw2's", E.fingerprint == _pex.fingerprint(E)   # PEX: hash link
      and _pex.record(E)["parent"] == chain.CHAIN.entry("ovw2").fingerprint)
check("fcp1 declares its four added files and each exists", E.added_files == F.ADDED_FILES and all((ROOT / f).is_file() for f in F.ADDED_FILES))

print("")
if FAILURES:
    print(f"{len(FAILURES)} FAILED, {PASSES} passed")
    sys.exit(1)
print(f"All {PASSES} fcp1 capability-profile / operating-limit checks passed.")
print("They execute the firmware source offline; they prove nothing about ESPHome timing, the compiled binary or the inverter.")
