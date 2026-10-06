#!/usr/bin/env python3
"""Offline structural tests for the durable recovery-marker state machine
(ecco_durable::MarkerState) added to the Free Power and Register 244
snapshot/restore paths in the 2026-09-21 follow-up to the durability/
sequencing hotfix - see
docs/research/esphome-2026.9.0-durability-modbus-sequencing-audit-2026-09-21.md
and firmware/include/ecco_durable_snapshot.h.

Covers the two issues that follow-up review found in the first pass
(694d10d) of that hotfix:

1. A verified restore cleared its durable marker with a single
   best-effort commit - if that commit failed, the marker stayed valid,
   which could reconstruct a stale recovery obligation (and, for Free
   Power, trigger an unattended repeat restore) on a later reboot. Fixed
   with a two-step marker: RESTORE_VERIFIED_PENDING_CLEAR (Phase C,
   durably records the hardware restore succeeded) committed BEFORE an
   attempt to reach CLEAR (Phase D).

2. A valid RESTORE_REQUIRED marker whose snapshot data failed to load at
   boot silently became "no snapshot" - i.e. ECCO forgot it owed a
   recovery. Fixed with an explicit fail-closed lockout
   (*_recovery_metadata_corrupt) that blocks new writes in the affected
   domain instead.

No I/O, no hardware, no ESPHome/C++ toolchain - text/structure checks
against the real firmware source, in the same style as
registry/tests/test_reg244_proof_harness_logic.py and
registry/tests/test_write_surface_invariants.py. These prove the source
says what it should, not that the compiled firmware behaves this way on
hardware.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

FAILURES: list[str] = []
FIRMWARE_PATH = Path(__file__).resolve().parents[2] / "firmware" / "ecco_clock_dongle_stage3_4_free_power.yaml"


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  PASS  {name}")
    else:
        FAILURES.append(name)
        print(f"  FAIL  {name}" + (f" - {detail}" if detail else ""))


if not FIRMWARE_PATH.is_file():
    print(f"  FAIL  firmware file not found at {FIRMWARE_PATH}")
    sys.exit(1)

fw = FIRMWARE_PATH.read_text(encoding="utf-8")


def script_body(script_id: str) -> str:
    """Extract one `- id: <script_id>` script's body - see the identical
    helper in test_reg244_proof_harness_logic.py for the slicing rule."""
    marker = f"\n  - id: {script_id}\n"
    start = fw.index(marker)
    rest = fw[start + 1 :]
    m = re.search(r"\n  - id: (?!" + re.escape(script_id) + r"\b)\w+\n|\n[a-z_]+:\n", rest)
    end = m.start() if m else len(rest)
    return rest[:end]


def on_boot_body() -> str:
    m = re.search(r"  on_boot:\n.*?\nesp32:\n", fw, re.S)
    assert m, "could not locate the on_boot block"
    return m.group(0)


DOMAINS = {
    "free_power": {
        "data_tag": "FREE_POWER_DATA_TAG",
        "valid_tag": "FREE_POWER_VALID_TAG",
        "snapshot_valid": "free_power_snapshot_valid",
        "marker_state": "free_power_marker_state",
        "corrupt_flag": "free_power_recovery_metadata_corrupt",
        # 2026-09-22 Free Power firmware hardening split this into a thin
        # public wrapper (retry/backoff gate, target 5; durable END-request
        # commit, target 2) that keeps only the zero-Modbus PENDING_CLEAR
        # clear-only branch inline, plus a dispatch script that holds the
        # actual write/verify body and its Phase C/D commit. Both must be
        # checked - see restore_body() below - or this file would silently
        # stop covering the Phase C/D logic that moved into the dispatch
        # script while still reporting PASS against the (now much smaller)
        # wrapper alone.
        "restore_script": "restore_free_power_snapshot",
        "restore_script_extra": "restore_free_power_snapshot_dispatch",
        "start_script": "start_free_power_override",
    },
    "reg244": {
        "data_tag": "REG244_DATA_TAG",
        "valid_tag": "REG244_VALID_TAG",
        "snapshot_valid": "reg244_snapshot_valid",
        "marker_state": "reg244_marker_state",
        "corrupt_flag": "reg244_recovery_metadata_corrupt",
        "restore_script": "restore_reg244_snapshot",
        "start_script": "apply_reg244_settings",
    },
}


def restore_body(d: dict) -> str:
    """The full text of a domain's restore path, across every script it is
    now split over (see the "free_power" domain's restore_script_extra
    comment above) - callers must not use script_body(d["restore_script"])
    directly for restore-path checks, or a future split like this one could
    silently narrow what gets checked again."""
    body = script_body(d["restore_script"])
    extra = d.get("restore_script_extra")
    if extra:
        body += "\n" + script_body(extra)
    return body

boot = on_boot_body()

# ===========================================================================
# A. After a verified restore, RAM ownership/snapshot is NOT considered
#    fully clean before the durable CLEAR (Phase D) commit succeeds.
# ===========================================================================
print("[A] A verified restore only releases RAM ownership after Phase D (MARKER_CLEAR) durably succeeds")
for name, d in DOMAINS.items():
    body = restore_body(d)
    clears = [m.start() for m in re.finditer(rf"{d['snapshot_valid']}\) = false", body)]
    check(f"{name}: restore script clears {d['snapshot_valid']} at least once", len(clears) >= 1)
    phase_d_guard = (
        f"if (ecco_durable::commit_record(ecco_durable::key_for(ecco_durable::{d['valid_tag']}), cleared))"
    )
    for pos in clears:
        window = body[max(0, pos - 500) : pos]
        check(
            f"{name}: the clear at offset {pos} is gated on a successful Phase D commit, not merely on a verified hardware write",
            phase_d_guard in window,
        )
    # Every place the marker is set back to CLEAR in RAM is inside that
    # same successful-commit guard (never unconditionally).
    ram_clears = [m.start() for m in re.finditer(rf"{d['marker_state']}\) = ecco_durable::MARKER_CLEAR;", body)]
    check(f"{name}: {d['marker_state']} is set to MARKER_CLEAR at least once", len(ram_clears) >= 1)
    for pos in ram_clears:
        window = body[max(0, pos - 200) : pos]
        check(
            f"{name}: RAM marker_state=CLEAR at offset {pos} is inside the same successful Phase D guard",
            phase_d_guard in window,
        )

# ===========================================================================
# B. If Phase D (CLEAR) fails: no second inverter restore is triggered in
#    the same runtime; a clear-only retry path exists.
# ===========================================================================
print("")
print("[B] Phase D failure never re-triggers a hardware restore in the same runtime; a clear-only retry path exists")
for name, d in DOMAINS.items():
    body = restore_body(d)
    check(
        f"{name}: a MARKER_RESTORE_VERIFIED_PENDING_CLEAR branch exists (the clear-only retry path)",
        "ecco_durable::MARKER_RESTORE_VERIFIED_PENDING_CLEAR" in body,
    )
    # The clear-only branch is the `then:` of the marker_state check inside
    # the script; isolate it structurally by cutting from that condition to
    # the next `else:` at the SAME 16-space indent (the branch's own else).
    cond_idx = body.find(f"{d['marker_state']}) == ecco_durable::MARKER_RESTORE_VERIFIED_PENDING_CLEAR")
    check(f"{name}: found the marker_state branch condition", cond_idx != -1)
    if cond_idx != -1:
        else_m = re.search(r"\n +else:\n", body[cond_idx:])
        clear_only_branch = body[cond_idx : cond_idx + else_m.start()] if else_m else ""
        check(
            f"{name}: the clear-only branch performs ZERO Modbus activity (no modbus_client. calls)",
            "modbus_client." not in clear_only_branch,
            f"branch length {len(clear_only_branch)}",
        )
        check(
            f"{name}: the clear-only branch attempts the Phase D commit",
            "ecco_durable::key_for(ecco_durable::" + d["valid_tag"] + ")" in clear_only_branch
            and "ecco_durable::MARKER_CLEAR" in clear_only_branch,
        )
        check(
            f"{name}: the clear-only branch's failure path does not clear ownership into a state that would relaunch a hardware restore "
            f"(it stays snapshot_valid=true / marker=PENDING_CLEAR, so the SAME clear-only branch runs again next time)",
            f"{d['snapshot_valid']}) = false" not in clear_only_branch.split(
                f"if (ecco_durable::commit_record(ecco_durable::key_for(ecco_durable::{d['valid_tag']}), cleared))"
            )[0]
            if f"if (ecco_durable::commit_record(ecco_durable::key_for(ecco_durable::{d['valid_tag']}), cleared))" in clear_only_branch
            else True,
        )

# ===========================================================================
# C. Boot with RESTORE_VERIFIED_PENDING_CLEAR performs zero Modbus writes.
# ===========================================================================
print("")
print("[C] Boot with a durable RESTORE_VERIFIED_PENDING_CLEAR marker performs zero Modbus writes")
for name, d in DOMAINS.items():
    m = re.search(
        rf"ecco_durable::key_for\(ecco_durable::{d['valid_tag']}\), marker\);.*?"
        rf"else if \(state == ecco_durable::MARKER_RESTORE_VERIFIED_PENDING_CLEAR\) \{{(.*?)\}} else",
        boot,
        re.S,
    )
    check(f"{name}: on_boot has a MARKER_RESTORE_VERIFIED_PENDING_CLEAR branch", m is not None)
    if m:
        pending_clear_boot_branch = m.group(1)
        check(
            f"{name}: on_boot's PENDING_CLEAR branch performs zero Modbus activity",
            "modbus_client." not in pending_clear_boot_branch and "write_multiple_registers" not in pending_clear_boot_branch,
        )
        check(
            f"{name}: on_boot's PENDING_CLEAR branch does not attempt to clear the marker itself "
            f"(clearing is deferred to the restore script's own clear-only path, not boot)",
            "commit_record" not in pending_clear_boot_branch,
        )

# ===========================================================================
# D. Boot with RESTORE_REQUIRED + unreadable/invalid data: fail-closed
#    lockout, no zero/default values used, no write path proceeds.
# ===========================================================================
print("")
print("[D] Boot with RESTORE_REQUIRED + unreadable snapshot data enters a fail-closed lockout, never restores with default values")
for name, d in DOMAINS.items():
    m = re.search(
        r"\} else \{  // MARKER_RESTORE_REQUIRED\n(.*?)\n            \}\n          \}",
        boot[boot.find(d["valid_tag"]) :],
        re.S,
    )
    check(f"{name}: on_boot has a MARKER_RESTORE_REQUIRED branch", m is not None)
    if m:
        restore_required_branch = m.group(1)
        # 2026-09-24 (PR-A): the success branch now contains its own nested
        # if/else (decoding reg244_lease_context_plus1 - see
        # ecco_durable_snapshot.h), which is MORE indented than the
        # load_record if/else itself. A bare, indentation-blind "} else {"
        # search would match that inner else instead of the real one -
        # anchor both the opening "if (" and the matching "} else {"/final
        # "}" to the SAME leading indentation (backreference \1) so nested
        # if/else blocks inside either branch are correctly skipped over.
        load_if = re.search(
            r"( *)if \(ecco_durable::load_record\(.*?\{(.*?)\n\1\} else \{(.*?)\n\1\}",
            restore_required_branch, re.S,
        )
        check(f"{name}: the RESTORE_REQUIRED branch attempts to load the snapshot data record", load_if is not None)
        if load_if:
            load_ok_branch, load_fail_branch = load_if.group(2), load_if.group(3)
            check(
                f"{name}: on successful load, the snapshot fields are populated from the record (not left at zero/default)",
                f"id({d['snapshot_valid']}) = true;" in load_ok_branch,
            )
            check(
                f"{name}: on FAILED load, the corruption lockout flag is set",
                f"id({d['corrupt_flag']}) = true;" in load_fail_branch,
            )
            check(
                f"{name}: on FAILED load, no snapshot register/value field is populated with a default (fail closed, not fail with zeros)",
                "snapshot_reg" not in load_fail_branch and "snapshot_value) = " not in load_fail_branch,
            )
            check(
                f"{name}: on FAILED load, the durable marker is NOT cleared (the obligation is not silently discarded)",
                "commit_record" not in load_fail_branch,
            )
    # The lockout must actually be consulted as a write precondition.
    check(
        f"{name}: {d['start_script']}'s precondition checks !{d['corrupt_flag']}",
        f"!id({d['corrupt_flag']})" in script_body(d["start_script"]),
    )
    check(
        f"{name}: the restore path's precondition checks !{d['corrupt_flag']}",
        f"!id({d['corrupt_flag']})" in restore_body(d),
    )

print("")
print("[D2] The corruption lockouts also gate the six manual TOU slot appliers (registers overlap Free Power's write surface)")
for n in range(1, 7):
    body = script_body(f"apply_manual_slot{n}")
    check(
        f"apply_manual_slot{n}: checks !free_power_recovery_metadata_corrupt",
        "!id(free_power_recovery_metadata_corrupt)" in body,
    )
    check(
        f"apply_manual_slot{n}: checks !reg244_recovery_metadata_corrupt",
        "!id(reg244_recovery_metadata_corrupt)" in body,
    )

print("")
print("[D3] The Free Power 15s watchdog never auto-restores while the recovery lockout is set")
watchdog_m = re.search(r"interval: 15s\n.*?condition:\n *lambda: \|-\n(.*?)\n          then:", fw, re.S)
check("found the Free Power 15s watchdog condition", watchdog_m is not None)
if watchdog_m:
    watchdog_cond = watchdog_m.group(1)
    check(
        "the watchdog condition checks free_power_recovery_metadata_corrupt and returns false when set",
        bool(re.search(r"if \(id\(free_power_recovery_metadata_corrupt\)\) return false;", watchdog_cond)),
    )
    corrupt_idx = watchdog_cond.find("free_power_recovery_metadata_corrupt")
    restore_idx = watchdog_cond.find("!id(free_power_active_persisted)) return true;")
    check(
        "the corruption check occurs before the fail-safe auto-restore trigger",
        -1 not in (corrupt_idx, restore_idx) and corrupt_idx < restore_idx,
    )

# ===========================================================================
# D4. A marker RECORD that exists but is malformed (bad magic, or a state
#     value this firmware does not recognise) must be its own fail-closed
#     lockout - neither silently treated as CLEAR (which would drop a real
#     recovery obligation) nor guessed to be RESTORE_REQUIRED (which would
#     attempt a restore using data whose shape was never validated).
#     Genuine absence of a marker record (first boot / never used) is the
#     ONLY case that resolves to CLEAR.
# ===========================================================================
print("")
print("[D4] A malformed marker RECORD (bad magic, or an unrecognised state) is its own fail-closed lockout - never CLEAR, never guessed as RESTORE_REQUIRED")
fp_marker_start = boot.find("key_for(ecco_durable::FREE_POWER_VALID_TAG)")
reg_marker_start = boot.find("key_for(ecco_durable::REG244_VALID_TAG)")
status_start = boot.find("if (id(free_power_recovery_metadata_corrupt)) {")
DOMAIN_BOOT_BLOCKS = {
    "free_power": boot[fp_marker_start:reg_marker_start],
    "reg244": boot[reg_marker_start:status_start],
}
for name, d in DOMAINS.items():
    block = DOMAIN_BOOT_BLOCKS[name]

    print(f"  -- {name} --")
    # 1. Missing marker record alone must never be treated as malformed -
    #    marker_malformed's formula is gated on have_marker, so !have_marker
    #    always takes the "normal" else branch, where state defaults to
    #    MARKER_CLEAR. This is the ONLY route to CLEAR: there is no separate
    #    code path that treats "no record" as anything else.
    #    SG-06: have_marker is exactly LOAD_OK, and the only other malformed
    #    trigger is a record stored with the WRONG SIZE - still never a
    #    genuinely missing one (LOAD_ABSENT). An unreadable marker
    #    (LOAD_READ_ERROR) takes its own fail-closed branch first - see
    #    registry/tests/test_sg06_boot_durable_read_fail_closed.py.
    check(
        f"{name}: malformed-marker detection is gated on have_marker or a wrong-size stored record (a genuinely missing record can never be flagged malformed)",
        "bool have_marker = marker_load == ecco_durable::LOAD_OK;" in block
        and "bool marker_malformed = marker_load == ecco_durable::LOAD_WRONG_SIZE || (have_marker && (" in block,
    )
    check(
        f"{name}: the normal (non-malformed) branch defaults state to MARKER_CLEAR only when no record was found",
        "uint8_t state = have_marker ? marker.state : (uint8_t) ecco_durable::MARKER_CLEAR;" in block,
    )

    # 2. Wrong magic is one of the malformed conditions.
    check(
        f"{name}: a magic mismatch is treated as malformed",
        "marker.magic != ecco_durable::VALID_MARKER_MAGIC" in block,
    )

    # 3. Any state outside the three known values is malformed - NOT
    #    guessed as RESTORE_REQUIRED by a generic else.
    check(
        f"{name}: an unrecognised state value (anything other than the three known states) is treated as malformed",
        "marker.state != ecco_durable::MARKER_CLEAR &&" in block
        and "marker.state != ecco_durable::MARKER_RESTORE_REQUIRED &&" in block
        and "marker.state != ecco_durable::MARKER_RESTORE_VERIFIED_PENDING_CLEAR" in block,
    )

    # Isolate the malformed branch's own body to prove what it does NOT do.
    mm = re.search(r"if \(marker_malformed\) \{(.*?)\n            \} else \{", block, re.S)
    check(f"{name}: found the malformed-marker branch body", mm is not None)
    if mm:
        malformed_branch = mm.group(1)

        # 4. Neither malformed case reaches the RESTORE_REQUIRED
        #    data-load/restore path - the malformed branch never even
        #    attempts to load the snapshot DATA record.
        check(
            f"{name}: the malformed branch never attempts to load the snapshot DATA record (never proceeds to the RESTORE_REQUIRED path)",
            f"ecco_durable::key_for(ecco_durable::{d['data_tag']})" not in malformed_branch,
        )
        check(
            f"{name}: the malformed branch never populates any snapshot register/value field",
            "snapshot_reg" not in malformed_branch and "snapshot_value) = " not in malformed_branch,
        )

        # 5. Neither malformed case clears (or otherwise writes) the
        #    durable marker - it is left exactly as found.
        check(
            f"{name}: the malformed branch never calls commit_record (the malformed record is left untouched, not cleared or overwritten)",
            "commit_record" not in malformed_branch,
        )

        # 6. Write lockouts remain active: the corruption flag is set, and
        #    snapshot_valid stays true so every precondition that requires
        #    !snapshot_valid to start something new also stays blocked.
        check(
            f"{name}: the malformed branch sets {d['corrupt_flag']} = true",
            f"id({d['corrupt_flag']}) = true;" in malformed_branch,
        )
        check(
            f"{name}: the malformed branch sets {d['snapshot_valid']} = true",
            f"id({d['snapshot_valid']}) = true;" in malformed_branch,
        )

print("")
print("[D5] Write surface remains unchanged and register 245 stays absent (regression guard for this change)")
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from analyze_write_surface import DEFAULT_FIRMWARE, analyze, write_surface  # noqa: E402

_ws_result = analyze(DEFAULT_FIRMWARE)
_actual_registers = set(write_surface(_ws_result["paths"]))
_expected_registers = (
    {22, 23, 24} | {230, 232} | {244} | set(range(250, 262)) | set(range(268, 280))
)
check(
    "the write surface is exactly the documented register set (unchanged by the marker-state-machine work)",
    _actual_registers == _expected_registers,
    f"unexpected={sorted(_actual_registers - _expected_registers)} missing={sorted(_expected_registers - _actual_registers)}",
)
check("register 245 (Export Limit) is still never written", 245 not in _actual_registers)

# ===========================================================================
# E. RESTORE_REQUIRED + valid snapshot continues to reconstruct normal
#    recovery (regression guard: D's checks above cover the failure path;
#    this confirms the success path is still reachable and unconditional
#    on nothing extra).
# ===========================================================================
print("")
print("[E] RESTORE_REQUIRED + valid/loadable snapshot data still reconstructs the normal recovery state (regression guard)")
for name, d in DOMAINS.items():
    check(
        f"{name}: on_boot sets {d['snapshot_valid']} = true on a successful RESTORE_REQUIRED data load",
        f"id({d['snapshot_valid']}) = true;" in boot,
    )
    check(
        f"{name}: {d['corrupt_flag']} defaults to false (declared restore_value: no, initial_value: 'false')",
        bool(re.search(rf"- id: {d['corrupt_flag']}\n +type: bool\n +restore_value: no\n +initial_value: 'false'", fw)),
    )

print("")
if FAILURES:
    print(f"{len(FAILURES)} check(s) FAILED:")
    for name in FAILURES:
        print(f"  - {name}")
else:
    print("All recovery-marker state-machine offline tests PASSED.")

print("")
print("These prove the firmware SOURCE implements the two-phase marker-clear")
print("and fail-closed corruption lockout as designed. They do NOT prove the")
print("compiled firmware behaves this way against real hardware or a real")
print("power-loss event - that verification is out of scope for a static text")
print("check.")

if FAILURES:
    sys.exit(1)
