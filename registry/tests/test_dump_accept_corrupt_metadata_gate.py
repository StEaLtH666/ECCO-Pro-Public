#!/usr/bin/env python3
"""Regression tests: Dump to Grid "Accept Current State" must refuse while
dump_recovery_metadata_corrupt is true (branch
`fix/dump-accept-corrupt-metadata-gate`).

Defect (reproduced by the SG-02 design review): the Dump block of on_boot
fails closed on a RESTORE_REQUIRED marker whose snapshot data record is
missing/unreadable (or a malformed marker, or an S4 / Free Power<->Dump
dual-obligation lockout) by setting BOTH dump_snapshot_valid = true and
dump_recovery_metadata_corrupt = true ("RECOVERY BLOCKED"). A stale durable
DumpToGridRetryState.operator_needed = 1 then also restores
dump_operator_needed = true (its only gate is dump_snapshot_valid).
dump_accept_current_state's admission gate checked operator_needed /
Recovery Arm / snapshot_valid / in-progress / residue - but never
dump_recovery_metadata_corrupt - so Accept proceeded: its residue gate
compared the live readback against dump_snapshot_reg244/256-261 values that
were never loaded (RAM defaults), then durably cleared the marker and the
obligation. That contradicts RECOVERY BLOCKED ("deliberate recovery
required") and destroys the only forensic evidence of the unresolved
obligation.

Required invariant: while dump_recovery_metadata_corrupt is true, Accept
refuses with zero Modbus I/O, zero durable commits, marker / snapshot_valid
/ corrupt flag unchanged, and a clear RECOVERY BLOCKED status.

Every scenario EXECUTES the real firmware source (the Dump block of the
on_boot lambda, the S4 and Free Power<->Dump boot arbitration blocks, and
the dump_accept_current_state / dump_force_restore_original action trees)
via registry/tests/_dump_sim.py. Section [M] proves sensitivity: removing
the corrupt guard makes the corrupt-case scenarios fail.

No I/O beyond reading the firmware file, no hardware, no ESPHome toolchain.
"""

from __future__ import annotations

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
VALID_TAG = "ecco_dump_to_grid_snapshot_valid_v1"
DATA_TAG = "ecco_dump_to_grid_snapshot_data_v2"  # Dump V2 ownership evidence tag bump
RETRY_TAG = "ecco_dump_to_grid_retry_state_v1"
MAGIC = ds.Durable.VALID_MARKER_MAGIC
REQUIRED = ds.Durable.MARKER_RESTORE_REQUIRED
ORIGINAL = {244: 2, 256: 8000, 257: 8000, 258: 7000, 259: 8000, 260: 8000, 261: 5000}
# A genuine, loadable snapshot record (restore_requested, not active).
GOOD_DATA = (0, 0, 1, 2, 8000, 8000, 7000, 8000, 8000, 5000, 1000)


def boot_lambda(fw) -> str:
    return fw["esphome"]["on_boot"]["then"][0]["lambda"]


def dump_boot_block(fw) -> str:
    boot = boot_lambda(fw)
    start = boot.index("// Manual Dump-to-Grid V1 (2026-09-26) - same fail-closed marker/")
    end_pub = boot.index('id(dump_status).publish_state("Inactive");', start)
    return boot[start:boot.index("}", end_pub) + 1]


def arbitration_block(fw, log_marker: str) -> str:
    """The `if (...) { ... }` boot arbitration block whose ESP_LOGE text
    contains `log_marker` (S4 or Free Power/Dump)."""
    boot = boot_lambda(fw)
    pos = boot.index(log_marker)
    start = boot.rindex("if (\n", 0, pos)
    close = 'id(dump_recovery_state).publish_state("LOCKED - durable recovery metadata unavailable");\n'
    end = boot.index(close, pos) + len(close)
    return boot[start:boot.index("}", end) + 1]


def config_poll(sim: ds.Sim) -> None:
    """A Block B configuration readback landing now (same shape as
    test_dump_to_grid_behaviour.py's config_poll)."""
    sim.g["cfg_block_b_dispatch_seq"] += 1
    sim.g["manual_cfg_reg244_raw"] = sim.bank.get(244, 0)
    for r in range(256, 262):
        sim.g[f"manual_cfg_reg{r}_raw"] = sim.bank.get(r, 0)
    sim.g["cfg_block_b_seq"] += 1
    sim.g["cfg_block_b_ok_ms"] = sim.millis()
    sim.g["cfg_block_b_response_dispatch_seq"] = sim.g["cfg_block_b_dispatch_seq"]


def booted(nvs: dict, bank: dict, fw=FW) -> ds.Sim:
    sim = ds.Sim(fw)
    sim.nvs = {k: v.copy() for k, v in nvs.items()}
    sim.bank = dict(bank)
    sim.ent("configuration_online").state = True
    sim.ent("configuration_polling").state = True
    sim.run_lambda(dump_boot_block(fw))
    return sim


def snapshot(sim: ds.Sim) -> dict:
    """Everything Accept must leave untouched when it refuses."""
    return {
        "nvs": {k: tuple(getattr(v, f) for f in ds._RECORD_FIELDS[v._kind]) for k, v in sim.nvs.items()},
        "snapshot_valid": sim.g["dump_snapshot_valid"],
        "corrupt": sim.g["dump_recovery_metadata_corrupt"],
        "operator_needed": sim.g["dump_operator_needed"],
        "marker_state": sim.g["dump_marker_state"],
    }


def accept(sim: ds.Sim) -> dict:
    """Arms recovery, lands a fresh readback, runs Accept; returns the
    observable side effects."""
    sim.advance(60000)
    config_poll(sim)
    sim.ent("dump_recovery_arm").state = True
    before = snapshot(sim)
    io, commits = len(sim.modbus_log), len(sim.nvs_commits)
    sim.execute("dump_accept_current_state")
    return {
        "before": before,
        "after": snapshot(sim),
        "modbus": sim.modbus_log[io:],
        "commits": sim.nvs_commits[commits:],
        "status": sim.status(),
        "arm": sim.ent("dump_recovery_arm").state,
    }


def refused_intact(r: dict) -> bool:
    return (r["modbus"] == [] and r["commits"] == [] and r["before"] == r["after"]
            and r["after"]["corrupt"] is True and r["after"]["snapshot_valid"] is True
            and "RECOVERY BLOCKED" in r["status"])


# ---------------------------------------------------------------------------
# Scenarios (each takes a firmware dict so [M] can re-run it on a mutant).
# ---------------------------------------------------------------------------
def s_missing_data_stale_operator_needed(fw, live244=1):
    """[1]/[2] The SG-02 reproduction: RESTORE_REQUIRED marker, NO data
    record, stale durable operator_needed = 1."""
    nvs = {VALID_TAG: ds.Record("ValidMarker", MAGIC, REQUIRED),
           RETRY_TAG: ds.Record("DumpToGridRetryState", 1)}
    sim = booted(nvs, {**ORIGINAL, 244: live244}, fw)
    return sim, accept(sim)


def s_unreadable_data(fw):
    """[2] A data record that exists but cannot be trusted (original 244
    outside 0/1/2 - treated exactly like an unreadable record at boot)."""
    bad = ds.Record("DumpToGridSnapshotData", 0, 0, 1, 7, 8000, 8000, 8000, 8000, 8000, 8000, 1000)
    nvs = {VALID_TAG: ds.Record("ValidMarker", MAGIC, REQUIRED), DATA_TAG: bad,
           RETRY_TAG: ds.Record("DumpToGridRetryState", 1)}
    sim = booted(nvs, {**ORIGINAL, 244: 1}, fw)
    return sim, accept(sim)


def s_malformed_marker(fw):
    nvs = {VALID_TAG: ds.Record("ValidMarker", 0x12345678, REQUIRED),
           DATA_TAG: ds.Record("DumpToGridSnapshotData", *GOOD_DATA),
           RETRY_TAG: ds.Record("DumpToGridRetryState", 1)}
    sim = booted(nvs, {**ORIGINAL, 244: 1}, fw)
    return sim, accept(sim)


def healthy_locked_nvs() -> dict:
    return {VALID_TAG: ds.Record("ValidMarker", MAGIC, REQUIRED),
            DATA_TAG: ds.Record("DumpToGridSnapshotData", *GOOD_DATA),
            RETRY_TAG: ds.Record("DumpToGridRetryState", 1)}


def s_s4_lockout(fw):
    """[3] S4: Dump and the reg244 harness both hold RESTORE_REQUIRED - the
    real S4 boot arbitration block sets dump_recovery_metadata_corrupt over
    an otherwise fully-loaded, operator-locked Dump snapshot."""
    sim = booted(healthy_locked_nvs(), {**ORIGINAL, 244: 1}, fw)
    sim.g["reg244_marker_state"] = REQUIRED
    sim.run_lambda(arbitration_block(fw, "DUAL DURABLE OBLIGATION (S4)"))
    assert sim.g["dump_recovery_metadata_corrupt"] and sim.g["dump_operator_needed"], sim.status()
    return sim, accept(sim)


def s_free_power_dump_lockout(fw):
    """[4] Free Power<->Dump dual obligation over 256-261."""
    sim = booted(healthy_locked_nvs(), {**ORIGINAL, 244: 1}, fw)
    sim.g["free_power_marker_state"] = REQUIRED
    sim.run_lambda(arbitration_block(fw, "DUAL DURABLE OBLIGATION (Free Power/Dump, 256-261)"))
    assert sim.g["dump_recovery_metadata_corrupt"] and sim.g["free_power_recovery_metadata_corrupt"], sim.status()
    return sim, accept(sim)


def refused(scenario):
    def run(fw):
        _sim, r = scenario(fw)
        return refused_intact(r)
    return run


# ===========================================================================
print("[0] Boot really produces the reported RECOVERY BLOCKED state")
sim0 = booted({VALID_TAG: ds.Record("ValidMarker", MAGIC, REQUIRED),
               RETRY_TAG: ds.Record("DumpToGridRetryState", 1)}, ORIGINAL)
check("RESTORE_REQUIRED + missing data + stale operator_needed boots as corrupt AND operator_needed AND snapshot_valid",
      sim0.g["dump_recovery_metadata_corrupt"] and sim0.g["dump_operator_needed"] and sim0.g["dump_snapshot_valid"]
      and sim0.status().startswith("RECOVERY BLOCKED"), sim0.status())
check("...and the Dump snapshot registers were never loaded (RAM defaults, not genuine originals)",
      all(sim0.g[f"dump_snapshot_reg{r}"] == 0 for r in (244, 256, 257, 258, 259, 260, 261)))

# ===========================================================================
print("")
print("[1] corrupt metadata + RESTORE_REQUIRED + stale operator_needed => Accept REFUSES")
for live244, label in ((1, "non-export 244 (residue gate would pass)"),
                       (0, "Allow Export 244 matching the never-loaded zero snapshot")):
    bank_override = {244: live244} if live244 else {244: 0, **{r: 0 for r in range(256, 262)}}
    nvs = {VALID_TAG: ds.Record("ValidMarker", MAGIC, REQUIRED), RETRY_TAG: ds.Record("DumpToGridRetryState", 1)}
    sim = booted(nvs, {**ORIGINAL, **bank_override})
    r = accept(sim)
    check(f"{label}: Accept refused with RECOVERY BLOCKED status", "RECOVERY BLOCKED" in r["status"], r["status"])
    check(f"{label}: ZERO Modbus I/O", r["modbus"] == [], f"{r['modbus']}")
    check(f"{label}: ZERO durable commits (marker not cleared, retry record not rewritten)",
          r["commits"] == [], f"{[(k, vars(v)) for k, v in r['commits']]}")
    check(f"{label}: marker still RESTORE_REQUIRED in NVS", sim.nvs[VALID_TAG].state == REQUIRED)
    check(f"{label}: snapshot_valid / corrupt / operator_needed / marker_state unchanged",
          r["before"] == r["after"], f"{r['before']} -> {r['after']}")
    check(f"{label}: Recovery Arm consumed", r["arm"] is False)

# ===========================================================================
print("")
print("[2] unreadable / missing Dump record => Accept cannot clear the obligation")
_s, r = s_missing_data_stale_operator_needed(FW)
check("missing data record: obligation retained (retry record still operator_needed=1, marker REQUIRED)",
      refused_intact(r) and _s.nvs[RETRY_TAG].operator_needed == 1 and _s.nvs[VALID_TAG].state == REQUIRED,
      r["status"])
check("missing data record: no data record fabricated", DATA_TAG not in _s.nvs)
_s, r = s_unreadable_data(FW)
check("invalid (244=7) data record: refused, record preserved byte-for-byte as forensic evidence",
      refused_intact(r) and _s.nvs[DATA_TAG].reg244 == 7, r["status"])
_s, r = s_malformed_marker(FW)
check("malformed marker magic: refused, malformed marker preserved", refused_intact(r)
      and _s.nvs[VALID_TAG].magic == 0x12345678, r["status"])

# ===========================================================================
print("")
print("[3] S4 arbitration lockout => Accept REFUSES")
_s, r = s_s4_lockout(FW)
check("S4 lockout (genuine loaded snapshot, operator_needed): Accept refused, zero I/O, zero commits, state intact",
      refused_intact(r), r["status"])

# ===========================================================================
print("")
print("[4] Free Power/Dump dual-obligation lockout => Accept REFUSES")
_s, r = s_free_power_dump_lockout(FW)
check("Free Power/Dump lockout: Accept refused, zero I/O, zero commits, state intact", refused_intact(r), r["status"])
check("...Free Power's own corrupt flag is not touched by Dump Accept", _s.g["free_power_recovery_metadata_corrupt"])

# ===========================================================================
print("")
print("[5] healthy, valid operator-needed recovery => existing Accept semantics unchanged")
sim = booted(healthy_locked_nvs(), {**ORIGINAL, 244: 1})
check("healthy boot: operator_needed, snapshot loaded, NOT corrupt",
      sim.g["dump_operator_needed"] and not sim.g["dump_recovery_metadata_corrupt"]
      and sim.g["dump_snapshot_reg256"] == 8000)
r = accept(sim)
check("healthy: Accept PERMITTED - marker CLEAR, retry record cleared, obligation gone",
      sim.nvs[VALID_TAG].state == ds.Durable.MARKER_CLEAR and sim.nvs[RETRY_TAG].operator_needed == 0
      and not sim.g["dump_snapshot_valid"] and not sim.g["dump_operator_needed"], r["status"])
check("healthy: ZERO Modbus I/O", r["modbus"] == [])
check("healthy: status is the unchanged ACCEPTED CURRENT STATE text", r["status"].startswith("ACCEPTED CURRENT STATE"),
      r["status"])
sim = booted(healthy_locked_nvs(), {**ORIGINAL, 244: 0, **{x: 1000 for x in range(256, 262)}})
r = accept(sim)
check("healthy: Dump residue (Allow Export, lease ceiling) still refused by the residue gate (ACCEPT REFUSED)",
      r["status"].startswith("ACCEPT REFUSED") and r["commits"] == [] and sim.nvs[VALID_TAG].state == REQUIRED,
      r["status"])
sim = booted({VALID_TAG: ds.Record("ValidMarker", MAGIC, 0)}, ORIGINAL)
r = accept(sim)
check("no obligation: unchanged 'only available while an operator decision is required' refusal",
      "only available while an operator decision is required" in r["status"], r["status"])

# ===========================================================================
print("")
print("[6] Force Restore Original behaviour unchanged")
sim = booted({VALID_TAG: ds.Record("ValidMarker", MAGIC, REQUIRED),
              RETRY_TAG: ds.Record("DumpToGridRetryState", 1)}, {**ORIGINAL, 244: 1})
sim.ent("dump_recovery_arm").state = True
sim.execute("dump_force_restore_original")
check("corrupt: Force Restore still performs ZERO Modbus I/O and ZERO durable commits (restore worker's own corrupt gate)",
      sim.modbus_log == [] and sim.nvs_commits == [] and sim.nvs[VALID_TAG].state == REQUIRED
      and sim.g["dump_recovery_metadata_corrupt"], sim.status())
check("corrupt: Force Restore status is the restore worker's unchanged RECOVERY BLOCKED text",
      "RECOVERY BLOCKED" in sim.status(), sim.status())
sim = booted(healthy_locked_nvs(), {**ORIGINAL, 244: 0, **{x: 1000 for x in range(256, 262)}})
sim.ent("dump_recovery_arm").state = True
sim.execute("dump_force_restore_original")
check("healthy: Force Restore still writes the exact original back and clears the marker",
      {x: sim.bank[x] for x in ORIGINAL} == ORIGINAL and sim.nvs[VALID_TAG].state == ds.Durable.MARKER_CLEAR,
      sim.status())

# ===========================================================================
print("")
print("[7] No new Modbus writes; Accept still has no Modbus action at all")
accept_text = ds.yaml.dump(FW["script"][[s["id"] for s in FW["script"]].index("dump_accept_current_state")])
check("dump_accept_current_state contains no modbus_controller/modbus_client action", "modbus" not in accept_text)

# ===========================================================================
print("")
print("[8] No marker clear in any corrupt case")
for label, scen in (("missing data", s_missing_data_stale_operator_needed), ("invalid data", s_unreadable_data),
                    ("malformed marker", s_malformed_marker), ("S4", s_s4_lockout),
                    ("Free Power/Dump", s_free_power_dump_lockout)):
    _s, r = scen(FW)
    check(f"{label}: no ValidMarker commit of any kind", not any(k == VALID_TAG for k, _ in r["commits"]))

# ===========================================================================
print("")
print("[M] Sensitivity: removing the corrupt guard makes the corrupt-case scenarios FAIL")
GUARD_OLD = "return id(dump_operator_needed) && !id(dump_recovery_metadata_corrupt) && id(dump_recovery_arm).state &&"
GUARD_NEW = "return id(dump_operator_needed) && id(dump_recovery_arm).state &&"


def mutant() -> dict:
    text = FW["_text"]
    if text.count(GUARD_OLD) != 1:
        raise AssertionError(f"mutation anchor not unique/present: {GUARD_OLD!r}")
    return ds.load_firmware_text(text.replace(GUARD_OLD, GUARD_NEW))


try:
    MUT = mutant()
except AssertionError as e:
    MUT = None
    check("corrupt guard mutation anchor present exactly once", False, str(e))
if MUT is not None:
    for label, scen in (("missing data + stale operator_needed", refused(s_missing_data_stale_operator_needed)),
                        ("invalid data record", refused(s_unreadable_data)),
                        ("S4 lockout", refused(s_s4_lockout)),
                        ("Free Power/Dump lockout", refused(s_free_power_dump_lockout))):
        real_ok = scen(FW)
        mutant_ok = scen(MUT)
        check(f"'{label}': refused on the real firmware, Accept clears the obligation on the guard-less mutant",
              real_ok is True and mutant_ok is False, f"real={real_ok} mutant={mutant_ok}")

# ===========================================================================
print("")
if FAILURES:
    print(f"{len(FAILURES)} check(s) FAILED:")
    for name in FAILURES:
        print(f"  - {name}")
else:
    print("All Dump Accept corrupt-metadata gate tests PASSED.")
print("")
print("These execute the firmware SOURCE under registry/tests/_dump_sim.py. No live Dump-to-Grid event,")
print("OTA, or inverter write has been performed.")
if FAILURES:
    sys.exit(1)
