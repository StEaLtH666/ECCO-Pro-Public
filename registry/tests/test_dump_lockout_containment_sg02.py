#!/usr/bin/env python3
"""SG-02 - Dump-to-Grid corrupt-lockout export CONTAINMENT (branch
`fix/sg02-dump-lockout-containment`).

Problem (SG-02): after an ESP reboot a Dump durable obligation can exist
while its recovery metadata is corrupt or disputed (unreadable/invalid data
record, malformed marker, the S4 Dump/reg244 dual obligation, or the
Free Power/Dump 256-261 dual obligation). The firmware correctly refuses a
full automatic restore - the ORIGINAL values cannot be trusted - but the
inverter can still hold register 244 = 0 (Allow Export) from the previous
Dump lease, and nothing ever turns that off while the ESP stays online.

Fix under test: a Dump-only CONTAINMENT action - NOT a restore. It
fresh-reads register 244 and, only if it reads 0 (Allow Export), writes the
LITERAL value 2 (Zero Export) and exact-reread-verifies it. It never writes
256-261 or any Free Power register, never touches a durable marker/record,
never clears dump_recovery_metadata_corrupt / dump_snapshot_valid /
dump_operator_needed, never infers an ORIGINAL value and never claims a
restore. Its outcome is RAM-only and reported on the Dump status (keeping
the fail-closed "RECOVERY BLOCKED" prefix) and a diagnostic sensor.

Also under test: the latent active-lease monitor hazard - the Stop SOC /
runaway / drift / telemetry monitor gate no longer suppresses itself on
dump_recovery_metadata_corrupt (the controller tick keeps its own corrupt
guard, so normal regulation stays blocked).

Every behavioural check EXECUTES the real firmware source through
registry/tests/_dump_sim.py (the Dump block of on_boot, the S4 and
Free Power/Dump arbitration blocks of on_boot, the Dump 15s watchdog
interval and the Dump scripts), against an in-memory register bank and an
in-memory NVS store. Test-first: the T01/T09/T10/T20/T26 checks were run
against main @ 15ee7d2 before the firmware change and FAILED there (export
left enabled / monitor suppressed) - see the commit message.

Simplifications (stated, not hidden): the reg244 proof harness and
Free Power boot blocks are NOT executed (the simulator does not model their
durable record types); the S4 / Free Power<->Dump arbitration inputs they
produce (reg244_marker_state, free_power_marker_state, ...) are set directly
as the globals those blocks would have produced, and the real arbitration
code in on_boot is then executed as-is.
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


FIRMWARE_PATH = ROOT / "firmware" / "ecco_clock_dongle_stage3_4_free_power.yaml"
FW = ds.load_firmware(FIRMWARE_PATH)

VALID_TAG = "ecco_dump_to_grid_snapshot_valid_v1"
DATA_TAG = "ecco_dump_to_grid_snapshot_data_v2"  # Dump V2 ownership evidence tag bump
RETRY_TAG = "ecco_dump_to_grid_retry_state_v1"
REQUIRED, PENDING_CLEAR = 1, 2
MAGIC = ds.Durable.VALID_MARKER_MAGIC

ORIGINAL = {244: 2, 256: 8000, 257: 8000, 258: 7000, 259: 8000, 260: 8000, 261: 5000}
# What an interrupted Dump lease leaves on the inverter: Allow Export plus
# the lease's battery ceiling on 256-261.
DUMP_RESIDUE = {244: 0, 256: 1000, 257: 1000, 258: 1000, 259: 1000, 260: 1000, 261: 1000}
FREE_POWER_REGS = {230, 232} | set(range(268, 280))
CEILING_REGS = set(range(256, 262))


# ---------------------------------------------------------------------------
# Boot-lambda segments (the REAL firmware text)
# ---------------------------------------------------------------------------
def _boot_text(fw) -> str:
    return fw["esphome"]["on_boot"]["then"][0]["lambda"]


def dump_boot_block(fw) -> str:
    boot = _boot_text(fw)
    start = boot.index("// Manual Dump-to-Grid V1 (2026-09-26) - same fail-closed marker/")
    end_pub = boot.index('id(dump_status).publish_state("Inactive");', start)
    return boot[start:boot.index("}", end_pub) + 1]


def arbitration_block(fw) -> str:
    """The S4 (Dump/reg244) and Free Power/Dump (256-261) dual-obligation
    checks, plus anything the firmware places after them and before the
    Free Power status publish (the SG-02 containment-state initialisation
    lives there after the fix)."""
    boot = _boot_text(fw)
    start = boot.index("// S4 fix (2026-09-27")
    end = boot.index("if (id(free_power_recovery_metadata_corrupt)) {", start)
    return boot[start:end]


_WATCHDOGS: dict = {}


def watchdog_of(fw) -> list:
    key = fw["_text"]
    if key not in _WATCHDOGS:
        _WATCHDOGS[key] = ds.find_interval(fw, "dump_overpower_samples")
    return _WATCHDOGS[key]


# ---------------------------------------------------------------------------
# Scenario helpers
# ---------------------------------------------------------------------------
def data_record(original=ORIGINAL, active=1, requested=0, intended=1000):
    return ds.Record("DumpToGridSnapshotData", 0, active, requested, original[244], original[256], original[257],
                     original[258], original[259], original[260], original[261], intended)


def nvs_fingerprint(sim) -> dict:
    return {k: (v._kind, tuple(getattr(v, f) for f in ds._RECORD_FIELDS[v._kind])) for k, v in sim.nvs.items()}


def env(sim) -> None:
    sim.ent("configuration_online").state = True
    sim.ent("configuration_polling").state = True
    sim.ent("dump_write_enable").state = False
    sim.ent("dump_recovery_arm").state = False


def booted(nvs: dict, bank: dict, fw=None, reg244_marker=0, free_power_marker=0) -> ds.Sim:
    """A fresh ESP boot: new RAM, the given durable store and inverter bank.
    Runs the real Dump boot block, then the real arbitration block with the
    OTHER domains' marker states as the (unsimulated) reg244 / Free Power
    boot blocks would have derived them."""
    sim = ds.Sim(fw or FW)
    env(sim)
    sim.nvs = {k: v.copy() for k, v in nvs.items()}
    sim.bank = dict(bank)
    sim.run_lambda(dump_boot_block(sim.fw))
    sim.g["reg244_marker_state"] = reg244_marker
    sim.g["reg244_snapshot_valid"] = reg244_marker != 0
    sim.g["free_power_marker_state"] = free_power_marker
    sim.g["free_power_snapshot_valid"] = free_power_marker != 0
    sim.run_lambda(arbitration_block(sim.fw))
    return sim


def tick(sim, ms=15000, n=1) -> None:
    for _ in range(n):
        sim.advance(ms)
        sim.run_actions(watchdog_of(sim.fw))


def writes(sim):
    return sim.writes()


def written_regs(sim) -> set:
    return {a + i for a, v in sim.writes() for i in range(len(v))}


def containment_state(sim) -> str:
    ent = sim.entities.get("dump_containment_state_sensor")
    return "" if ent is None or not ent.has_state() else str(ent.state)


def unreadable_nvs():
    """RESTORE_REQUIRED marker whose data record is missing/unreadable."""
    return {VALID_TAG: ds.Record("ValidMarker", MAGIC, REQUIRED)}


def invalid_data_nvs():
    bad = ds.Record("DumpToGridSnapshotData", 0, 1, 0, 7, 8000, 8000, 8000, 8000, 8000, 8000, 1000)
    return {VALID_TAG: ds.Record("ValidMarker", MAGIC, REQUIRED), DATA_TAG: bad}


def malformed_marker_nvs():
    return {VALID_TAG: ds.Record("ValidMarker", 0x12345678, REQUIRED), DATA_TAG: data_record()}


def trusted_nvs(original=ORIGINAL):
    return {VALID_TAG: ds.Record("ValidMarker", MAGIC, REQUIRED), DATA_TAG: data_record(original)}


def invariants(label, sim, nvs_before, allow_244_write=True) -> None:
    """The containment-is-not-restoration contract, checked after every
    scenario."""
    check(f"{label}: ZERO NVS commits (no durable/NVS state written)", sim.nvs_commits == [], f"{sim.nvs_commits}")
    check(f"{label}: durable markers/records byte-identical", nvs_fingerprint(sim) == nvs_before)
    check(f"{label}: dump_recovery_metadata_corrupt remains set", sim.g["dump_recovery_metadata_corrupt"] is True)
    check(f"{label}: dump_snapshot_valid remains set", sim.g["dump_snapshot_valid"] is True)
    check(f"{label}: no write to 256-261", not (written_regs(sim) & CEILING_REGS), f"{writes(sim)}")
    check(f"{label}: no Free Power register write", not (written_regs(sim) & FREE_POWER_REGS), f"{writes(sim)}")
    only = [w for w in writes(sim) if w != (244, [2])]
    check(f"{label}: every write (if any) is exactly the literal 244 = [2]", only == [] and (allow_244_write or not writes(sim)),
          f"{writes(sim)}")
    status = sim.status()
    check(f"{label}: Dump status keeps the fail-closed RECOVERY BLOCKED wording", "RECOVERY BLOCKED" in status, status)
    check(f"{label}: Dump status never claims a restore/resolution",
          "restored" not in status.lower() and "resolved" not in status.lower(), status)


# ===========================================================================
print("[T01] Dump obligation + unreadable/corrupt metadata + live 244=0 -> contained with literal 244=2")
for label, nvs_factory in (("T01 unreadable data record", unreadable_nvs),
                           ("T01 invalid data record (orig 244=7)", invalid_data_nvs),
                           ("T01 malformed marker", malformed_marker_nvs)):
    nvs = nvs_factory()
    sim = booted(nvs, DUMP_RESIDUE)
    before = nvs_fingerprint(sim)
    check(f"{label}: setup - corrupt lockout active at boot",
          sim.g["dump_recovery_metadata_corrupt"] and sim.g["dump_snapshot_valid"])
    tick(sim, n=4)
    check(f"{label}: register 244 is contained to Zero Export (2)", sim.bank.get(244) == 2, f"244={sim.bank.get(244)}")
    check(f"{label}: exactly one write, literal 244 = [2]", writes(sim) == [(244, [2])], f"{writes(sim)}")
    check(f"{label}: 256-261 left exactly as found (no containment write there)",
          all(sim.bank[r] == DUMP_RESIDUE[r] for r in CEILING_REGS))
    check(f"{label}: containment reports CONTAINED", containment_state(sim).startswith("CONTAINED"), containment_state(sim))
    check(f"{label}: Dump status names the containment", "CONTAIN" in sim.status(), sim.status())
    invariants(label, sim, before)
    reads = [(a, o) for k, a, v, o in sim.modbus_log if k == "read"]
    check(f"{label}: the write was preceded by a fresh read of 244 and followed by an exact reread",
          bool(sim.modbus_log) and sim.modbus_log[0][:2] == ("read", 244) and sim.modbus_log[-1][:2] == ("read", 244)
          and len(reads) == 2,
          f"{sim.modbus_log}")
    check(f"{label}: watchdog restore still refused (restore never attempted - 256-261 untouched)",
          sim.g["dump_restore_successes"] == 0)

# ===========================================================================
print("")
print("[T09] S4 dual obligation (Dump + reg244 both RESTORE_REQUIRED) + live 244=0")
nvs = trusted_nvs()
sim = booted(nvs, DUMP_RESIDUE, reg244_marker=REQUIRED)
before = nvs_fingerprint(sim)
check("T09: setup - S4 arbitration locks both domains",
      sim.g["dump_recovery_metadata_corrupt"] and sim.g["reg244_recovery_metadata_corrupt"])
tick(sim, n=4)
check("T09: 244 contained to 2 with exactly one literal write", sim.bank[244] == 2 and writes(sim) == [(244, [2])],
      f"{writes(sim)}")
check("T09: reg244 lockout untouched", sim.g["reg244_recovery_metadata_corrupt"] is True)
check("T09: status keeps S4-compatible RECOVERY BLOCKED wording", sim.status().startswith("RECOVERY BLOCKED"), sim.status())
invariants("T09", sim, before)

# ===========================================================================
print("")
print("[T10] Free Power/Dump dual obligation (256-261) + live 244=0 -> only 244 may be written")
nvs = trusted_nvs()
sim = booted(nvs, DUMP_RESIDUE, free_power_marker=REQUIRED)
before = nvs_fingerprint(sim)
check("T10: setup - Free Power/Dump arbitration locks both domains",
      sim.g["dump_recovery_metadata_corrupt"] and sim.g["free_power_recovery_metadata_corrupt"])
tick(sim, n=4)
check("T10: 244 contained to 2", sim.bank[244] == 2, f"{writes(sim)}")
check("T10: NEVER any write to 256-261", not (written_regs(sim) & CEILING_REGS), f"{writes(sim)}")
check("T10: 256-261 still hold exactly what was found", all(sim.bank[r] == 1000 for r in CEILING_REGS))
check("T10: Free Power lockout untouched", sim.g["free_power_recovery_metadata_corrupt"] is True)
invariants("T10", sim, before)

# ===========================================================================
print("")
print("[T20] Repeated reboots: containment is once-per-boot, never clears anything, never fights")
nvs = unreadable_nvs()
bank = dict(DUMP_RESIDUE)
per_boot = []
first_before = None
for boot_no in range(6):
    if boot_no == 3:
        bank[244] = 0  # an external actor re-enables export while the ESP is down
    sim = booted(nvs, bank)
    if first_before is None:
        first_before = nvs_fingerprint(sim)
    tick(sim, n=5)
    per_boot.append(list(writes(sim)))
    check(f"T20 boot #{boot_no + 1}: durable store byte-identical to the very first boot",
          nvs_fingerprint(sim) == first_before and sim.nvs_commits == [])
    check(f"T20 boot #{boot_no + 1}: lockout still in force (corrupt + snapshot_valid)",
          sim.g["dump_recovery_metadata_corrupt"] and sim.g["dump_snapshot_valid"])
    check(f"T20 boot #{boot_no + 1}: 244 is Zero Export at the end of the boot", sim.bank[244] == 2)
    bank = dict(sim.bank)
    nvs = {k: v.copy() for k, v in sim.nvs.items()}
check("T20: boot #1 contains once; boots #2-#3 find 244 already 2 and write nothing",
      per_boot[0] == [(244, [2])] and per_boot[1] == [] and per_boot[2] == [], f"{per_boot}")
check("T20: boot #4 (export re-enabled while down) contains exactly once again; #5-#6 write nothing",
      per_boot[3] == [(244, [2])] and per_boot[4] == [] and per_boot[5] == [], f"{per_boot}")

# ===========================================================================
print("")
print("[T26] Injected ACTIVE + corrupt + Stop SOC crossed: monitor still ends, controller stays blocked")


def config_poll(sim) -> None:
    sim.g["cfg_block_b_dispatch_seq"] += 1
    sim.g["manual_cfg_reg244_raw"] = sim.bank.get(244, 0)
    for r in range(256, 262):
        sim.g[f"manual_cfg_reg{r}_raw"] = sim.bank.get(r, 0)
    sim.g["cfg_block_b_seq"] += 1
    sim.g["cfg_block_b_ok_ms"] = sim.millis()
    sim.g["cfg_block_b_response_dispatch_seq"] = sim.g["cfg_block_b_dispatch_seq"]


def started_lease(fw=None, target=1000) -> ds.Sim:
    sim = ds.Sim(fw or FW)
    sim.bank.update(ORIGINAL)
    sim.ent("dump_export_power").set(float(target))
    sim.ent("dump_stop_soc").set(25.0)
    sim.ent("dump_duration_minutes").set(30.0)
    sim.ent("dump_write_enable").state = True
    sim.ent("dump_recovery_arm").state = False
    sim.ent("configuration_online").state = True
    sim.ent("configuration_polling").state = True
    sim.ent("ecco_battery_voltage").set(52.0)
    sim.g["ntp_synced"] = True
    for i, t in enumerate([0, 530, 800, 1600, 1900, 2330]):
        sim.g[f"manual_cfg_reg{250 + i}_raw"] = t
    for i, f in enumerate([1, 0, 0, 0, 0, 0]):
        sim.g[f"manual_cfg_reg{274 + i}_raw"] = f
    config_poll(sim)
    sim.ent("ecco_battery_soc").publish_state(70.0)
    sim.ent("ecco_grid_ct_power").publish_state(-float(target))
    sim.execute("start_dump_to_grid_override")
    assert sim.g["dump_active_persisted"], sim.status()
    return sim


def live_tick(sim, soc, grid_w, ms=15000) -> None:
    sim.advance(ms)
    sim.ent("ecco_battery_soc").publish_state(soc)
    sim.ent("ecco_grid_ct_power").publish_state(grid_w)
    config_poll(sim)
    sim.run_actions(watchdog_of(sim.fw))


def t26_scenario(fw=None):
    sim = started_lease(fw)
    base_writes = len(sim.writes())
    commits_before = len(sim.nvs_commits)
    nvs_before = nvs_fingerprint(sim)
    sim.g["dump_recovery_metadata_corrupt"] = True  # injected runtime corruption (latent-hazard case)
    live_tick(sim, soc=20.0, grid_w=-1000.0)  # Stop SOC (25%) crossed
    new_writes = sim.writes()[base_writes:]
    return sim, new_writes, commits_before, nvs_before


sim, new_writes, commits_before, nvs_before = t26_scenario()
check("T26: the safety monitor requested the end (STOP SOC REACHED recorded)",
      str(sim.ent("dump_last_end_reason").state) == "STOP SOC REACHED", str(sim.ent("dump_last_end_reason").state))
check("T26: dump_restore_requested latched in RAM", sim.g["dump_restore_requested"] is True)
check("T26: no controller / restore write to 256-261 while corrupt", not any(a == 256 for a, _ in new_writes),
      f"{new_writes}")
check("T26: no NVS commit after the corruption was injected (end request is RAM-only while corrupt)",
      len(sim.nvs_commits) == commits_before and nvs_fingerprint(sim) == nvs_before)
check("T26: export contained by the literal 244=2 write (the only new write)", new_writes == [(244, [2])], f"{new_writes}")
check("T26: corrupt and snapshot_valid still set", sim.g["dump_recovery_metadata_corrupt"] and sim.g["dump_snapshot_valid"])

# Controller stays blocked even when the monitor does NOT end the lease and
# the grid error would otherwise demand a correction.
sim = started_lease()
base_writes = len(sim.writes())
sim.bank[244] = 2  # isolate the controller: nothing for containment to do
sim.g["dump_recovery_metadata_corrupt"] = True
sim.advance(15000)
sim.ent("ecco_battery_soc").publish_state(70.0)
sim.ent("ecco_grid_ct_power").publish_state(-100.0)  # 900 W short of target
sim.execute("dump_controller_tick")
check("T26b: dump_controller_tick's own corrupt guard still blocks regulation (zero writes)",
      sim.writes()[base_writes:] == [], f"{sim.writes()[base_writes:]}")

# ===========================================================================
print("")
print("[B] Live 244 already non-export / D5 original-state exemption")
for live, label in ((1, "Essentials"), (2, "Zero Export")):
    bank = dict(DUMP_RESIDUE)
    bank[244] = live
    nvs = unreadable_nvs()
    sim = booted(nvs, bank)
    before = nvs_fingerprint(sim)
    tick(sim, n=5)
    check(f"live 244={live} ({label}): NO write at all", writes(sim) == [], f"{writes(sim)}")
    check(f"live 244={live}: exactly one fresh read of 244, then containment stops for this boot",
          [(k, a) for k, a, v, o in sim.modbus_log] == [("read", 244)], f"{sim.modbus_log}")
    check(f"live 244={live}: containment reports NOT_NEEDED", containment_state(sim).startswith("NOT_NEEDED"),
          containment_state(sim))
    invariants(f"live 244={live}", sim, before, allow_244_write=False)

ORIGINAL_ALLOW = dict(ORIGINAL)
ORIGINAL_ALLOW[244] = 0  # the user's own pre-Dump policy WAS Allow Export
nvs = trusted_nvs(ORIGINAL_ALLOW)
sim = booted(nvs, ORIGINAL_ALLOW, reg244_marker=REQUIRED)
before = nvs_fingerprint(sim)
tick(sim, n=4)
check("D5: trusted record + live 244/256-261 exactly equal the ORIGINAL snapshot -> no write",
      writes(sim) == [] and sim.bank[244] == 0, f"{writes(sim)}")
check("D5: reported NOT_NEEDED (original state), not CONTAINED", containment_state(sim).startswith("NOT_NEEDED"),
      containment_state(sim))
check("D5: the exemption used fresh reads of 244 and 256-261 only",
      [(k, a) for k, a, v, o in sim.modbus_log] == [("read", 244), ("read", 256)], f"{sim.modbus_log}")
invariants("D5", sim, before, allow_244_write=False)

bank = dict(ORIGINAL_ALLOW)
bank[258] = 1000  # 256-261 NOT the original -> Dump residue
sim = booted(trusted_nvs(ORIGINAL_ALLOW), bank, reg244_marker=REQUIRED)
tick(sim, n=4)
check("D5 negative: 244=0 but 256-261 differ from ORIGINAL -> contained", writes(sim) == [(244, [2])], f"{writes(sim)}")

sim = booted(unreadable_nvs(), ORIGINAL_ALLOW)
tick(sim, n=4)
check("D5 negative: untrusted (unreadable) record never gets the exemption -> contained",
      writes(sim) == [(244, [2])], f"{writes(sim)}")

sim = booted(trusted_nvs(ORIGINAL_ALLOW), ORIGINAL_ALLOW, reg244_marker=REQUIRED)
sim.outcome_fn = lambda kind, addr, count: "error" if (kind, addr) == ("read", 256) else "ok"
tick(sim, n=1)
check("D5: a failed 256-261 read writes NOTHING (retry later, never guess)", writes(sim) == [], f"{writes(sim)}")

# ===========================================================================
print("")
print("[C] Fault handling: read failure, write failure, verify mismatch (bounded)")
nvs = unreadable_nvs()
sim = booted(nvs, DUMP_RESIDUE)
before = nvs_fingerprint(sim)
fail = {"n": 2}


def read_fails_twice(kind, addr, count):
    if kind == "read" and addr == 244 and fail["n"] > 0:
        fail["n"] -= 1
        return "error"
    return "ok"


sim.outcome_fn = read_fails_twice
tick(sim, n=1)
check("read failure: NO write", writes(sim) == [], f"{writes(sim)}")
check("read failure: reported RETRYING", containment_state(sim).startswith("RETRYING"), containment_state(sim))
log_len = len(sim.modbus_log)
tick(sim, ms=1000, n=5)
check("read failure: backoff respected (no bus I/O inside the backoff window)", len(sim.modbus_log) == log_len)
tick(sim, n=4)
check("read failure: retried after backoff, then contained with one literal write",
      writes(sim) == [(244, [2])] and sim.bank[244] == 2, f"{writes(sim)}")
invariants("read failure", sim, before)

nvs = unreadable_nvs()
sim = booted(nvs, DUMP_RESIDUE)
before = nvs_fingerprint(sim)
wfail = {"n": 1}


def write_fails_once(kind, addr, count):
    if kind == "write" and wfail["n"] > 0:
        wfail["n"] -= 1
        return "error"
    return "ok"


sim.outcome_fn = write_fails_once
tick(sim, n=1)
check("write failure: reported RETRYING, 244 still 0", containment_state(sim).startswith("RETRYING") and sim.bank[244] == 0,
      containment_state(sim))
tick(sim, n=4)
check("write failure: retried (fresh read first) and contained; every write literal [2]",
      writes(sim) == [(244, [2]), (244, [2])] and sim.bank[244] == 2, f"{writes(sim)}")
invariants("write failure", sim, before)

nvs = unreadable_nvs()
sim = booted(nvs, DUMP_RESIDUE)
before = nvs_fingerprint(sim)
sim.outcome_fn = lambda kind, addr, count: "no_response_landed" if kind == "write" else "ok"
tick(sim, n=4)
check("write landed but response lost: next attempt reads 2 and reports CONTAINED without a second write",
      writes(sim) == [(244, [2])] and containment_state(sim).startswith("CONTAINED"),
      f"{writes(sim)} {containment_state(sim)}")
invariants("lost write response", sim, before)

nvs = unreadable_nvs()
sim = booted(nvs, DUMP_RESIDUE)
before = nvs_fingerprint(sim)
sim.outcome_fn = lambda kind, addr, count: "ack_not_applied" if kind == "write" else "ok"
tick(sim, n=12)
n_writes = len(writes(sim))
check("verify mismatch (inverter acks but keeps 0): bounded - at most 2 writes, then stops",
      1 <= n_writes <= 2 and all(w == (244, [2]) for w in writes(sim)), f"{writes(sim)}")
check("verify mismatch: reported REFUSED_BY_INVERTER", containment_state(sim).startswith("REFUSED_BY_INVERTER"),
      containment_state(sim))
check("verify mismatch: status says export may still be enabled, keeps RECOVERY BLOCKED",
      sim.status().startswith("RECOVERY BLOCKED") and "REFUSED" in sim.status(), sim.status())
log_len = len(sim.modbus_log)
tick(sim, n=10)
check("verify mismatch: no further bus I/O at all for the rest of this boot", len(sim.modbus_log) == log_len)
invariants("verify mismatch", sim, before)

nvs = unreadable_nvs()
sim = booted(nvs, DUMP_RESIDUE)
sim.outcome_fn = lambda kind, addr, count: "error" if kind == "write" else "ok"
tick(sim, n=40)
check("persistent write failure: total write attempts per boot are bounded (<= 3)",
      1 <= len(writes(sim)) <= 3, f"{len(writes(sim))} writes")
check("persistent write failure: every attempt was the literal 244=[2]", all(w == (244, [2]) for w in writes(sim)))

# ===========================================================================
print("")
print("[D] External re-enable after containment: reported, NOT reasserted")
nvs = unreadable_nvs()
sim = booted(nvs, DUMP_RESIDUE)
tick(sim, n=2)
check("setup: contained", sim.bank[244] == 2 and containment_state(sim).startswith("CONTAINED"))
sim.bank[244] = 0  # external actor re-enables export
config_poll(sim)
tick(sim, n=6)
check("re-enable: reported EXPORT_REENABLED_EXTERNALLY", containment_state(sim).startswith("EXPORT_REENABLED_EXTERNALLY"),
      containment_state(sim))
check("re-enable: 244 NOT reasserted (still exactly one write this boot)", writes(sim) == [(244, [2])], f"{writes(sim)}")
check("re-enable: status keeps RECOVERY BLOCKED", sim.status().startswith("RECOVERY BLOCKED"), sim.status())

# ===========================================================================
print("")
print("[E] Operator paths, START, and conflicting operations stay blocked / respected")
nvs = unreadable_nvs()
nvs[RETRY_TAG] = ds.Record("DumpToGridRetryState", 1)
sim = booted(nvs, DUMP_RESIDUE)
before = nvs_fingerprint(sim)
tick(sim, n=2)
w_before = list(writes(sim))
sim.ent("dump_recovery_arm").state = True
sim.execute("dump_force_restore_original")
check("Force Restore Original still performs NO restore write while corrupt", writes(sim) == w_before, f"{writes(sim)}")
check("...and the durable store is untouched", nvs_fingerprint(sim) == before and sim.nvs_commits == [])
sim.ent("dump_write_enable").state = True
sim.ent("dump_export_power").set(1000.0)
sim.ent("dump_stop_soc").set(25.0)
sim.ent("dump_duration_minutes").set(30.0)
sim.ent("ecco_battery_voltage").set(52.0)
sim.ent("ecco_battery_soc").publish_state(70.0)
sim.execute("start_dump_to_grid_override")
check("START still refused while corrupt (no new write, no NVS)", writes(sim) == w_before and sim.nvs_commits == [],
      sim.status())
check("START refusal keeps RECOVERY BLOCKED wording", "RECOVERY BLOCKED" in sim.status(), sim.status())
check("operator_needed still set (untouched by containment)", sim.g["dump_operator_needed"] is True)

for flag in ("manual_write_in_progress", "correction_in_progress", "free_power_operation_in_progress",
             "reg244_apply_in_progress", "dump_operation_in_progress"):
    sim = booted(unreadable_nvs(), DUMP_RESIDUE)
    sim.g[flag] = True
    tick(sim, n=3)
    check(f"conflicting {flag}: containment performs ZERO bus I/O", sim.modbus_log == [], f"{sim.modbus_log}")
sim = booted(unreadable_nvs(), DUMP_RESIDUE)
sim.bus_idle = False
tick(sim, n=3)
check("Modbus bus busy: containment performs ZERO bus I/O", sim.modbus_log == [])
sim.bus_idle = True
tick(sim, n=1)
check("...and proceeds once the bus is idle", writes(sim) == [(244, [2])], f"{writes(sim)}")
check("locks released after containment", not sim.g["manual_write_in_progress"] and not sim.g["dump_operation_in_progress"])

# ===========================================================================
print("")
print("[F] Healthy / non-corrupt paths are unchanged")
sim = booted({VALID_TAG: ds.Record("ValidMarker", MAGIC, 0)}, DUMP_RESIDUE)
tick(sim, n=6)
check("healthy CLEAR boot (even with live 244=0): ZERO containment bus activity", sim.modbus_log == [], f"{sim.modbus_log}")
check("healthy boot: containment NOT_APPLICABLE", containment_state(sim) in ("", "NOT_APPLICABLE") or
      containment_state(sim).startswith("NOT_APPLICABLE"), containment_state(sim))

sim = booted({}, DUMP_RESIDUE)
tick(sim, n=6)
check("fresh device (no durable records at all): ZERO bus activity", sim.modbus_log == [])

sim = booted({VALID_TAG: ds.Record("ValidMarker", MAGIC, PENDING_CLEAR)}, DUMP_RESIDUE)
tick(sim, n=2)
check("PENDING_CLEAR semantics unchanged: cleared with ZERO Modbus I/O",
      sim.modbus_log == [] and sim.nvs[VALID_TAG].state == 0 and not sim.g["dump_snapshot_valid"], sim.status())

sim = booted(trusted_nvs(), DUMP_RESIDUE)
tick(sim, n=2)
check("trusted, non-disputed obligation: normal full restore unchanged (244 then 256-261 from the snapshot)",
      writes(sim) == [(244, [2]), (256, [8000, 8000, 7000, 8000, 8000, 5000])] and sim.nvs[VALID_TAG].state == 0,
      f"{writes(sim)}")
check("trusted restore: RESTORED OK status (containment never engaged)", sim.status().startswith("RESTORED OK"),
      sim.status())

# ===========================================================================
print("")
print("[G] Structural: the containment script's write surface and non-durability")
text = FW["_text"]
has_script = "- id: dump_lockout_containment" in text
check("a dedicated dump_lockout_containment script exists", has_script)
if has_script:
    script = next(s for s in FW["script"] if s["id"] == "dump_lockout_containment")
    import yaml  # noqa: E402
    body = yaml.dump(script)
    import re  # noqa: E402
    starts = re.findall(r"start_address: (\d+)", body)
    check("containment script: every Modbus op targets 244 or (read-only D5 evidence) 256",
          set(starts) <= {"244", "256"}, f"{starts}")
    write_ops = []

    def walk(node):
        if isinstance(node, dict):
            for k, v in node.items():
                if k == ds.WRITE:
                    write_ops.append(v)
                walk(v)
        elif isinstance(node, list):
            for x in node:
                walk(x)

    walk(script["then"])
    check("containment script: exactly one write action", len(write_ops) == 1, f"{len(write_ops)}")
    check("containment script: the write is 244 with the LITERAL vector {2}",
          len(write_ops) == 1 and int(write_ops[0]["start_address"]) == 244
          and write_ops[0]["values"].replace(" ", "") == "returnstd::vector<uint16_t>{2};",
          f"{write_ops[0]['values'] if write_ops else None}")
    check("containment script: never calls commit_record / touches durable tags",
          "commit_record" not in body and "_TAG" not in body)
    for flag in ("dump_recovery_metadata_corrupt", "dump_snapshot_valid", "dump_operator_needed",
                 "dump_marker_state", "dump_restore_requested", "dump_active_persisted"):
        check(f"containment script: never assigns {flag}", f"id({flag}) =" not in body)
    check("containment script: never writes from snapshot fields", "dump_snapshot_reg244)}" not in body)

monitor_gate = "return id(dump_active_persisted) && !id(dump_restore_requested) &&\n                     !id(dump_operation_in_progress);"
check("active-lease monitor gate no longer suppresses itself on dump_recovery_metadata_corrupt",
      monitor_gate in text)
check("dump_controller_tick keeps its own corrupt guard",
      "id(dump_operation_in_progress) || id(dump_recovery_metadata_corrupt)) {\n            return;" in text)

# ===========================================================================
print("")
print("[H] Mutation (sensitivity) checks: each safeguard's removal is detected")


def mutant(old: str, new: str) -> dict:
    t = FW["_text"]
    if t.count(old) != 1:
        raise AssertionError(f"mutation anchor not unique/present: {old!r}")
    return ds.load_firmware_text(t.replace(old, new))


def s_t01_contained(fw) -> bool:
    sim = booted(unreadable_nvs(), DUMP_RESIDUE, fw=fw)
    tick(sim, n=4)
    return sim.bank[244] == 2 and writes(sim) == [(244, [2])]


def s_only_244_literal(fw) -> bool:
    sim = booted(trusted_nvs(), DUMP_RESIDUE, fw=fw, free_power_marker=REQUIRED)
    tick(sim, n=4)
    return writes(sim) == [(244, [2])] and not (written_regs(sim) & CEILING_REGS)


def s_no_nvs(fw) -> bool:
    sim = booted(unreadable_nvs(), DUMP_RESIDUE, fw=fw)
    before = nvs_fingerprint(sim)
    tick(sim, n=4)
    return sim.nvs_commits == [] and nvs_fingerprint(sim) == before


def s_flags_kept(fw) -> bool:
    sim = booted(unreadable_nvs(), DUMP_RESIDUE, fw=fw)
    tick(sim, n=4)
    return (sim.g["dump_recovery_metadata_corrupt"] is True and sim.g["dump_snapshot_valid"] is True
            and sim.bank[244] == 2)


def s_t26(fw) -> bool:
    sim, new_writes, _c, _n = t26_scenario(fw)
    return (str(sim.ent("dump_last_end_reason").state) == "STOP SOC REACHED"
            and not any(a == 256 for a, _ in new_writes))


def s_bounded(fw) -> bool:
    sim = booted(unreadable_nvs(), DUMP_RESIDUE, fw=fw)
    sim.outcome_fn = lambda kind, addr, count: "ack_not_applied" if kind == "write" else "ok"
    tick(sim, n=20)
    return 1 <= len(writes(sim)) <= 2


def s_no_write_when_nonzero(fw) -> bool:
    bank = dict(DUMP_RESIDUE)
    bank[244] = 1
    sim = booted(unreadable_nvs(), bank, fw=fw)
    tick(sim, n=4)
    return writes(sim) == []


def s_d5(fw) -> bool:
    sim = booted(trusted_nvs(ORIGINAL_ALLOW), ORIGINAL_ALLOW, fw=fw, reg244_marker=REQUIRED)
    tick(sim, n=4)
    return writes(sim) == []


MUTATIONS = [
    ("removing the containment trigger from the Dump watchdog", s_t01_contained,
     "            - script.execute: dump_lockout_containment\n", ""),
    ("writing the snapshot's 244 instead of literal 2", s_t01_contained,
     "values: !lambda 'return std::vector<uint16_t>{2};'",
     "values: !lambda 'return std::vector<uint16_t>{id(dump_snapshot_reg244)};'"),
    ("writing literal 1 (Essentials) instead of 2", s_t01_contained,
     "values: !lambda 'return std::vector<uint16_t>{2};'", "values: !lambda 'return std::vector<uint16_t>{1};'"),
    ("widening the containment write to 244-261", s_only_244_literal,
     "values: !lambda 'return std::vector<uint16_t>{2};'",
     "values: !lambda 'return std::vector<uint16_t>{2, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1000, 1000, 1000, 1000, 1000, 1000};'"),
    ("adding a durable commit to the containment outcome", s_no_nvs,
     "                // SG-02 outcome classification (RAM only)\n",
     "                // SG-02 outcome classification (RAM only)\n"
     "                { ecco_durable::DumpToGridRetryState r{}; r.operator_needed = 0;"
     " ecco_durable::commit_record(ecco_durable::key_for(ecco_durable::DUMP_TO_GRID_RETRY_TAG), r); }\n"),
    ("clearing dump_recovery_metadata_corrupt on CONTAINED", s_flags_kept,
     "                // SG-02 outcome classification (RAM only)\n",
     "                // SG-02 outcome classification (RAM only)\n                id(dump_recovery_metadata_corrupt) = false;\n"),
    ("clearing dump_snapshot_valid on CONTAINED", s_flags_kept,
     "                // SG-02 outcome classification (RAM only)\n",
     "                // SG-02 outcome classification (RAM only)\n                id(dump_snapshot_valid) = false;\n"),
    ("restoring the active-monitor corrupt suppression", s_t26,
     "return id(dump_active_persisted) && !id(dump_restore_requested) &&\n                     !id(dump_operation_in_progress);",
     "return id(dump_active_persisted) && !id(dump_restore_requested) &&\n                     !id(dump_operation_in_progress) && !id(dump_recovery_metadata_corrupt);"),
    ("removing the verify-mismatch bound", s_bounded,
     "if (id(dump_containment_mismatch_count) >= ${ecco_dump_containment_max_mismatches} ||",
     "if (false ||"),
    ("writing even when live 244 is not Allow Export", s_no_write_when_nonzero,
     "id(dump_containment_live244) == 0 &&\n                           !id(dump_containment_live_is_original);",
     "true &&\n                           !id(dump_containment_live_is_original);"),
    ("dropping the D5 original-state exemption", s_d5,
     "!id(dump_containment_live_is_original);",
     "true;"),
]

if not has_script:
    check("mutation checks require the containment implementation (absent on this firmware)", False)
else:
    for label, scenario, old, new in MUTATIONS:
        real_ok = scenario(FW)
        try:
            mutant_ok = scenario(mutant(old, new))
        except ds.Unsupported as e:
            mutant_ok = f"unsupported: {e}"
        check(f"'{label}': safe on the real firmware, detected on the mutant",
              real_ok is True and mutant_ok is False, f"real={real_ok} mutant={mutant_ok}")

print("")
if FAILURES:
    print(f"{len(FAILURES)} check(s) FAILED:")
    for name in FAILURES:
        print(f"  - {name}")
else:
    print("All SG-02 Dump lockout containment tests PASSED.")
print("")
print("These checks execute the real firmware SOURCE in the offline simulator; they")
print("prove control flow, not ESPHome scheduling, the compiled binary, or inverter")
print("behaviour. Nothing here touches hardware.")

if FAILURES:
    sys.exit(1)
