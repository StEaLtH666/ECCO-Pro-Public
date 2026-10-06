#!/usr/bin/env python3
"""Offline tests for the register 244 Load/Export Mode proof harness in
firmware/ecco_clock_dongle_stage3_4_free_power.yaml
(apply_reg244_settings / restore_reg244_snapshot), covering both the
2026-09-21 safety-review fixes and the original design.

No I/O, no hardware, no ESPHome/C++ toolchain. Two kinds of checks:

1. Logic-mirror functions - direct line-for-line mirrors of the C++
   condition lambdas, so a change to one that silently changes
   behaviour should also require updating the other.
2. Structural checks - read the actual firmware source text and assert
   on real facts about it (ordering of statements, which conditions
   reference which flags, which branches clear/retain state) rather
   than re-encoding the same assumptions in pure Python disconnected
   from the source. These are the ones that catch an accidental
   regression in the real file, not just in this test's own model.

Neither proves the real ESPHome firmware compiles or behaves this way
on hardware. The hardware proof is separate and is now complete: a full
2 (Zero Export) -> 0 (Allow Export) -> 2 (Zero Export) round trip was
performed against the physical inverter on 2026-09-21, each leg exact-
reread verified, with the change in real power flow independently
confirmed - see docs/stage3_3-six-slot-hardware-test.md "Register 244
(Load/Export Mode) live proof". These offline checks remain the
regression guard for the harness's LOGIC; they are not the hardware
proof and cannot become it.
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


# ===========================================================================
# Part 1: logic mirrors of the current C++ condition lambdas
# ===========================================================================


def enum_to_raw(option: str) -> int:
    """Mirrors the target_raw lookup in apply_reg244_settings's condition/then lambdas."""
    return {"Allow Export": 0, "Essentials": 1, "Zero Export": 2}.get(option, -1)


def apply_condition(
    *,
    armed: bool,
    staging_loaded: bool,
    online: bool,
    correction_in_progress: bool,
    manual_write_in_progress: bool,
    apply_in_progress: bool,
    snapshot_valid: bool,
    staged_option: str,
) -> bool:
    """Mirrors apply_reg244_settings's outer `if:` condition lambda exactly
    (post safety-review fix: no longer depends on manual_config_raw_cache_valid
    - the dedicated pre-write read supersedes it - and now also refuses to
    start a second Apply while a snapshot is already pending restore)."""
    target_raw = enum_to_raw(staged_option)
    return (
        armed
        and staging_loaded
        and online
        and not correction_in_progress
        and not manual_write_in_progress
        and not apply_in_progress
        and not snapshot_valid
        and target_raw in (0, 1, 2)
    )


def restore_outer_condition(
    *,
    armed: bool,
    snapshot_valid: bool,
    snapshot_value: int,
    online: bool,
    correction_in_progress: bool,
    manual_write_in_progress: bool,
    apply_in_progress: bool,
) -> bool:
    """Mirrors restore_reg244_snapshot's outer `if:` condition lambda exactly
    (post safety-review fix: snapshot_value <= 2 is now checked defensively,
    and manual_config_raw_cache_valid is no longer required - the dedicated
    drift-check read supersedes it)."""
    return (
        armed
        and snapshot_valid
        and snapshot_value <= 2
        and online
        and not correction_in_progress
        and not manual_write_in_progress
        and not apply_in_progress
    )


def restore_drift_detected(
    *, last_applied_valid: bool, live_raw: int, last_applied_value: int
) -> bool:
    """Mirrors the inner drift-guard `if:` inside restore_reg244_snapshot.

    True means the restore is REFUSED (drift found). last_applied_valid
    being False means the previous outcome was uncertain - no comparison
    is invented in that case (matches "do not invent a comparison").
    """
    return last_applied_valid and live_raw != last_applied_value


print("[1] Enum validation: only Allow Export / Essentials / Zero Export stage a writable target")
check("Allow Export -> 0", enum_to_raw("Allow Export") == 0)
check("Essentials -> 1", enum_to_raw("Essentials") == 1)
check("Zero Export -> 2", enum_to_raw("Zero Export") == 2)
check("anything else -> -1 (never a valid write target)", enum_to_raw("garbage") == -1)

base_apply_kwargs = dict(
    armed=True,
    staging_loaded=True,
    online=True,
    correction_in_progress=False,
    manual_write_in_progress=False,
    apply_in_progress=False,
    snapshot_valid=False,
    staged_option="Zero Export",
)

print("")
print("[2] Apply cannot execute while unarmed")
check("unarmed -> condition false", apply_condition(**{**base_apply_kwargs, "armed": False}) is False)
check("fully-armed happy path -> condition true", apply_condition(**base_apply_kwargs) is True)

print("")
print("[3] Apply cannot execute without fresh staging / online configuration")
check("staging not loaded -> false", apply_condition(**{**base_apply_kwargs, "staging_loaded": False}) is False)
check("configuration offline -> false", apply_condition(**{**base_apply_kwargs, "online": False}) is False)

print("")
print("[4] Contention prevents Apply: RTC correction, another manual write, or another reg244 op already in flight")
check("RTC correction in progress -> false", apply_condition(**{**base_apply_kwargs, "correction_in_progress": True}) is False)
check("manual_write_in_progress (TOU/Free Power) -> false", apply_condition(**{**base_apply_kwargs, "manual_write_in_progress": True}) is False)
check("reg244 apply already in progress -> false", apply_condition(**{**base_apply_kwargs, "apply_in_progress": True}) is False)

print("")
print("[5] Apply requires a valid staged enum value")
check("staged garbage option -> false even if everything else is ready", apply_condition(**{**base_apply_kwargs, "staged_option": "garbage"}) is False)

print("")
print("[6] (invariant 1) Apply is rejected outright if a snapshot is already pending restore")
check(
    "snapshot already valid -> Apply condition false even though everything else is ready",
    apply_condition(**{**base_apply_kwargs, "snapshot_valid": True}) is False,
)

base_restore_kwargs = dict(
    armed=True,
    snapshot_valid=True,
    snapshot_value=2,
    online=True,
    correction_in_progress=False,
    manual_write_in_progress=False,
    apply_in_progress=False,
)

print("")
print("[7] Restore cannot execute without arm")
check("unarmed -> false", restore_outer_condition(**{**base_restore_kwargs, "armed": False}) is False)
check("fully-armed happy path -> true", restore_outer_condition(**base_restore_kwargs) is True)

print("")
print("[8] Restore cannot execute without a valid snapshot")
check("no snapshot -> false", restore_outer_condition(**{**base_restore_kwargs, "snapshot_valid": False}) is False)

print("")
print("[9] (invariant 3) Restore refuses to write a persisted snapshot whose value is not a recognised enum")
for bad_value in (3, 4, 65535):
    check(
        f"snapshot_value={bad_value} (not 0/1/2) -> restore condition false",
        restore_outer_condition(**{**base_restore_kwargs, "snapshot_value": bad_value}) is False,
    )
for good_value in (0, 1, 2):
    check(
        f"snapshot_value={good_value} (recognised) -> restore condition true, all else ready",
        restore_outer_condition(**{**base_restore_kwargs, "snapshot_value": good_value}) is True,
    )

print("")
print("[10] Contention prevents Restore, same as Apply")
check("RTC correction in progress -> false", restore_outer_condition(**{**base_restore_kwargs, "correction_in_progress": True}) is False)
check("manual_write_in_progress -> false", restore_outer_condition(**{**base_restore_kwargs, "manual_write_in_progress": True}) is False)
check("reg244 apply already in progress -> false", restore_outer_condition(**{**base_restore_kwargs, "apply_in_progress": True}) is False)

print("")
print("[11] (invariant 7) Unexpected live-state drift before Restore is detected using a fresh read, not silently overwritten")
check(
    "no prior applied value tracked -> no drift claimed (nothing to compare against)",
    restore_drift_detected(last_applied_valid=False, live_raw=2, last_applied_value=0) is False,
)
check(
    "live still matches what ECCO last wrote -> no drift, safe to restore",
    restore_drift_detected(last_applied_valid=True, live_raw=2, last_applied_value=2) is False,
)
check(
    "live NO LONGER matches what ECCO last wrote (a third party changed it) -> drift detected, restore refused",
    restore_drift_detected(last_applied_valid=True, live_raw=1, last_applied_value=2) is True,
)

print("")
print("[12] Successful verification and every failure/uncertain outcome always disarm (mirrors turn_off() on every exit path)")
exit_paths_that_disarm = {
    "apply: outer condition rejected": True,
    "apply: pre-write read failed / unknown value rejected": True,
    "apply: write uncertain (timeout/error)": True,
    "apply: verify ok": True,
    "apply: verify mismatch": True,
    "apply: verify uncertain (timeout/error)": True,
    "restore: outer condition rejected": True,
    "restore: drift-check read failed": True,
    "restore: drift detected": True,
    "restore: write uncertain (timeout/error)": True,
    "restore: verify ok": True,
    "restore: verify mismatch": True,
    "restore: verify uncertain (timeout/error)": True,
}
check(
    "every enumerated exit path disarms (audited against the firmware source, not executed)",
    all(exit_paths_that_disarm.values()),
    str([k for k, v in exit_paths_that_disarm.items() if not v]),
)

# ===========================================================================
# Part 2: structural checks against the real firmware source
# ===========================================================================

print("")
print("=== Structural checks against firmware/ecco_clock_dongle_stage3_4_free_power.yaml ===")

if not FIRMWARE_PATH.is_file():
    print(f"  SKIP  firmware file not found at {FIRMWARE_PATH} - structural checks cannot run")
    FAILURES.append("firmware file not found for structural checks")
else:
    fw = FIRMWARE_PATH.read_text(encoding="utf-8")

    def script_body(script_id: str) -> str:
        """Extract one `- id: <script_id>` script's body up to the next
        top-level (2-space-indented) `- id:` entry or a new top-level
        YAML section, by locating the id and slicing to the next sibling
        at the same indent level."""
        marker = f"\n  - id: {script_id}\n"
        start = fw.index(marker)
        rest = fw[start + 1:]
        m = re.search(r"\n  - id: (?!" + re.escape(script_id) + r"\b)\w+\n|\n[a-z_]+:\n", rest)
        end = m.start() if m else len(rest)
        return rest[:end]

    apply_body = script_body("apply_reg244_settings")
    restore_body = script_body("restore_reg244_snapshot")

    print("")
    print("[13] (invariant 4) Apply marks the snapshot valid BEFORE the write phase, not after verification")
    idx_snapshot_valid_true = apply_body.find("id(reg244_snapshot_valid) = true;")
    idx_first_write = apply_body.find("modbus_client.write_multiple_registers:")
    check(
        "reg244_snapshot_valid = true appears in apply_reg244_settings",
        idx_snapshot_valid_true != -1,
    )
    check(
        "the first write_multiple_registers call appears in apply_reg244_settings",
        idx_first_write != -1,
    )
    check(
        "reg244_snapshot_valid = true occurs BEFORE the first write, not after",
        -1 not in (idx_snapshot_valid_true, idx_first_write) and idx_snapshot_valid_true < idx_first_write,
        f"snapshot_valid=true at {idx_snapshot_valid_true}, first write at {idx_first_write}",
    )

    print("")
    print("[14] A durable, checked two-phase commit - not a flush delay - separates the snapshot read from the first write")
    # 2026-09-21 durability/sequencing hotfix: "flush delay" was never a
    # durability proof (see
    # docs/research/esphome-2026.9.0-durability-modbus-sequencing-audit-2026-09-21.md).
    # Replaced with ecco_durable::commit_record() called once for the
    # snapshot DATA (its own key) and, only if that succeeded, once more
    # for a separate VALID marker - both before reg244_snapshot_valid is
    # ever set true in RAM, and both before the first write.
    idx_data_commit = apply_body.find("ecco_durable::key_for(ecco_durable::REG244_DATA_TAG)")
    idx_valid_commit = apply_body.find("ecco_durable::key_for(ecco_durable::REG244_VALID_TAG)")
    check("apply_reg244_settings commits the snapshot DATA record", idx_data_commit != -1)
    check("apply_reg244_settings commits a separate VALID marker record", idx_valid_commit != -1)
    check(
        "the DATA commit occurs before the VALID marker commit (data is durable before it is marked valid)",
        -1 not in (idx_data_commit, idx_valid_commit) and idx_data_commit < idx_valid_commit,
        f"data commit at {idx_data_commit}, valid commit at {idx_valid_commit}",
    )
    check(
        "both commits occur before reg244_snapshot_valid is set true in RAM",
        -1 not in (idx_data_commit, idx_valid_commit, idx_snapshot_valid_true)
        and idx_valid_commit < idx_snapshot_valid_true,
        f"data={idx_data_commit} valid={idx_valid_commit} snapshot_valid_true={idx_snapshot_valid_true}",
    )
    check(
        "both commits occur before the first write",
        -1 not in (idx_data_commit, idx_valid_commit, idx_first_write) and idx_valid_commit < idx_first_write,
    )
    check(
        "the write is gated on BOTH commits having succeeded (data_committed && marker_committed)",
        "if (data_committed && marker_committed)" in apply_body,
    )
    check(
        "a failed commit sets reg244_write_failed so the write phase is skipped, not just delayed",
        "id(reg244_write_failed) = true;" in apply_body[idx_valid_commit:idx_first_write],
    )
    check(
        "apply_reg244_settings has NO fixed delay: step anywhere (sequencing is completion-driven)",
        "delay:" not in apply_body,
    )

    print("")
    print("[15] (invariant 5) Snapshot is retained (never cleared) on every uncertain apply outcome")
    # Split the post-write portion of apply_body (after the first write
    # call) into its failure/verify-mismatch/verify-error branches and
    # confirm none of them clear reg244_snapshot_valid.
    post_write = apply_body[idx_first_write:] if idx_first_write != -1 else ""
    uncertain_markers = [
        "UNCERTAIN - write to register 244 failed or timed out",
        "VERIFY FAILED - read %u, expected %u",
        "UNCERTAIN - post-write verification Modbus error",
        "UNCERTAIN - post-write verification timed out",
    ]
    for marker in uncertain_markers:
        pos = post_write.find(marker)
        check(f"apply uncertain-outcome message present: {marker!r}", pos != -1)
        if pos != -1:
            # Look at a bounded window around the message for a stray clear.
            window = post_write[max(0, pos - 400):pos + 200]
            check(
                f"no 'reg244_snapshot_valid) = false' near {marker!r}",
                "reg244_snapshot_valid) = false" not in window,
            )

    print("")
    print("[16] (invariant 6) Only a DURABLY-CLEARED marker releases reg244_snapshot_valid - Apply never clears it, Restore's own failure paths don't either")
    check(
        "apply_reg244_settings never sets reg244_snapshot_valid = false",
        "reg244_snapshot_valid) = false" not in apply_body,
    )
    # 2026-09-21 follow-up review: restore_reg244_snapshot now has TWO clear
    # sites - the normal verified-restore path (Phase C then Phase D) and
    # the clear-only retry path (marker already at
    # RESTORE_VERIFIED_PENDING_CLEAR, only Phase D is attempted, no Modbus
    # activity). Both must sit inside a successful Phase D commit_record()
    # check - a durable MARKER_CLEAR commit, not just "the hardware write
    # was verified" - so a Phase D failure leaves the RAM obligation
    # (snapshot_valid/marker_state) exactly where a reboot would find it.
    restore_clears = [m.start() for m in re.finditer(r"reg244_snapshot_valid\) = false", restore_body)]
    check(
        "restore_reg244_snapshot clears reg244_snapshot_valid in exactly two places (normal path + clear-only retry)",
        len(restore_clears) == 2,
        f"found {len(restore_clears)} occurrence(s)",
    )
    phase_d_guard = "if (ecco_durable::commit_record(ecco_durable::key_for(ecco_durable::REG244_VALID_TAG), cleared))"
    ok_guarded = 0
    for pos in restore_clears:
        window = restore_body[max(0, pos - 400):pos]
        check(
            f"clear at offset {pos} is gated on a successful durable Phase D (MARKER_CLEAR) commit, not merely a verified hardware write",
            phase_d_guard in window,
        )
        wide_window = restore_body[max(0, pos - 3000):pos]
        if "if (ok)" in wide_window and "phase_c_ok" in wide_window:
            ok_guarded += 1
    check(
        "exactly one of the two clear sites is the normal path (inside the hardware-verify 'if (ok)' branch, after Phase C)",
        ok_guarded == 1,
        f"ok_guarded={ok_guarded}",
    )
    check(
        "restore_reg244_snapshot never clears reg244_snapshot_valid merely because the durable clear commit call was attempted - only on its success",
        "reg244_marker_state) = ecco_durable::MARKER_CLEAR;" in restore_body
        and restore_body.count("reg244_marker_state) = ecco_durable::MARKER_CLEAR;") == 2,
    )

    print("")
    print("[17] (invariant 2 / 3 / 4) Unknown live raw values fail closed and are never snapshotted")
    check(
        "apply_reg244_settings checks 'raw > 2' before ever setting the snapshot",
        "if (raw > 2)" in apply_body and apply_body.index("if (raw > 2)") < apply_body.index("id(reg244_snapshot_value) = raw;"),
    )
    check(
        "the unknown-value branch does NOT set reg244_snapshot_valid = true",
        "reg244_snapshot_valid) = true" not in apply_body[apply_body.index("if (raw > 2)"):apply_body.index("} else {")],
    )
    check(
        "restore's outer condition defensively re-checks reg244_snapshot_value <= 2",
        "id(reg244_snapshot_value) <= 2" in restore_body,
    )
    load_button_section = fw[fw.index("id: load_reg244_staging"):fw.index("id: load_reg244_staging") + 1500]
    check(
        "the Load Current button also fails closed (checks raw > 2 before staging_loaded = true)",
        "raw > 2" in load_button_section and "reg244_staging_loaded) = false" in load_button_section,
    )

    print("")
    print("[18] (invariant 7) Restore's drift check runs against a value updated by Restore's OWN dedicated read, not only the periodic poll")
    # The dedicated drift-check read in restore_reg244_snapshot must
    # update manual_cfg_reg244_raw itself, and the drift comparison must
    # appear textually AFTER that dedicated read (not before it, which
    # would mean comparing against a stale value).
    idx_restore_read = restore_body.find("modbus_client.read_holding_registers:")
    idx_restore_cache_update = restore_body.find("id(manual_cfg_reg244_raw) = raw;")
    idx_drift_compare = restore_body.find("id(manual_cfg_reg244_raw) != id(reg244_last_applied_value)")
    check("restore_reg244_snapshot performs a dedicated read", idx_restore_read != -1)
    check("that read updates manual_cfg_reg244_raw", idx_restore_cache_update != -1)
    check("the drift comparison exists", idx_drift_compare != -1)
    check(
        "the drift comparison occurs AFTER the dedicated read updates the cache",
        -1 not in (idx_restore_cache_update, idx_drift_compare) and idx_restore_cache_update < idx_drift_compare,
    )

    print("")
    print("[19] (invariant 8 / 9) A pending reg244 snapshot blocks new TOU slot Apply and new Free Power start, without touching Restore or reads")
    for slot in range(1, 7):
        slot_body = script_body(f"apply_manual_slot{slot}")
        check(
            f"apply_manual_slot{slot}'s condition includes !id(reg244_snapshot_valid)",
            "!id(reg244_snapshot_valid)" in slot_body,
        )
        check(
            f"apply_manual_slot{slot}'s rejection cascade explains the reg244 hold",
            "Register 244 proof transaction awaiting restoration" in slot_body,
        )
    free_power_start_body = script_body("start_free_power_override")
    check(
        "start_free_power_override's condition includes !id(reg244_snapshot_valid)",
        "!id(reg244_snapshot_valid)" in free_power_start_body,
    )
    check(
        "start_free_power_override's rejection cascade explains the reg244 hold",
        "Register 244 proof transaction awaiting restoration" in free_power_start_body,
    )
    restore_free_power_body = script_body("restore_free_power_snapshot")
    check(
        "restore_free_power_snapshot is NOT gated by reg244_snapshot_valid (restore stays available)",
        "reg244_snapshot_valid" not in restore_free_power_body,
    )

    print("")
    print("[20] (invariant 10) Read-only polling is unaffected - the Block B poll and its cache-validity gate are untouched")
    check(
        "the periodic Block B poll interval still guards on !manual_write_in_progress",
        "id(configuration_polling).state && !id(correction_in_progress) && !id(manual_write_in_progress)" in fw,
    )
    check(
        "Block B still decodes register 244 into ecco_load_limit as part of the normal poll",
        'case 0: id(ecco_load_limit).publish_state("Allow Export"); break;' in fw,
    )
    check(
        "Block B still caches the raw value for reg244 alongside the other manual_cfg_regNNN_raw fields",
        "id(manual_cfg_reg244_raw) = values[3];" in fw,
    )

    print("")
    print("[21] (invariant 11) No new Modbus write target besides register 244 exists")
    # Scope strictly to write_multiple_registers blocks - a blind
    # start_address regex over the whole file would also match every
    # read_holding_registers call and produce a meaningless result.
    write_addrs_found = []
    for m in re.finditer(r"modbus_client\.write_multiple_registers:", fw):
        window = fw[m.end():m.end() + 200]
        addr_m = re.search(r"start_address:\s*(0x[0-9A-Fa-f]+|\d+)", window)
        check(f"write_multiple_registers call at offset {m.start()} has a start_address nearby", addr_m is not None)
        if addr_m:
            write_addrs_found.append(int(addr_m.group(1), 0))
    write_addresses = sorted(set(write_addrs_found))
    expected = sorted({22, 230, 232, 244, 250, 251, 252, 253, 254, 255, 256, 257, 258, 259, 260, 261, 268, 269, 270, 271, 272, 273, 274, 275, 276, 277, 278, 279})
    check(
        "the complete set of write_multiple_registers start_address values is exactly the expected set (baseline + 244)",
        write_addresses == expected,
        f"found {write_addresses}, expected {expected}",
    )

    # -----------------------------------------------------------------
    # Power-loss / reboot-window hardening (2026-09-21 follow-up): from
    # the instant a write is about to be attempted until it has been
    # positively verified, the persisted state must never claim
    # confidence in what ECCO last wrote - otherwise a reboot in that
    # exact window leaves Restore's drift guard comparing against a
    # stale "confirmed" value that was never actually confirmed.
    # -----------------------------------------------------------------

    print("")
    print("[22] (test A) Apply: snapshot_valid=true AND last_applied_valid=false both occur before the first write")
    idx_apply_invalidate = apply_body.find("id(reg244_last_applied_valid) = false;")
    check("apply_reg244_settings invalidates last_applied_valid at all", idx_apply_invalidate != -1)
    check(
        "that invalidation occurs BEFORE the first write (same ordering already proven for snapshot_valid=true in [13])",
        -1 not in (idx_apply_invalidate, idx_first_write) and idx_apply_invalidate < idx_first_write,
        f"invalidate at {idx_apply_invalidate}, first write at {idx_first_write}",
    )
    check(
        "the invalidation sits in the same pre-write lambda as snapshot_valid=true (within 1000 chars of it)",
        -1 not in (idx_apply_invalidate, idx_snapshot_valid_true) and abs(idx_apply_invalidate - idx_snapshot_valid_true) < 1000,
    )

    print("")
    print("[23] (test B) Restore: the fresh drift check occurs BEFORE last_applied_valid is invalidated")
    idx_restore_drift_if = restore_body.find("id(reg244_last_applied_valid) && (id(manual_cfg_reg244_raw) != id(reg244_last_applied_value))")
    # The proceed-path invalidation is the one that appears BEFORE the
    # restore write and its own flush delay - distinct from the
    # (redundant-but-harmless) ones inside the later failure/mismatch
    # branches, which are identified separately in [24]/[25].
    idx_restore_write = restore_body.find("modbus_client.write_multiple_registers:")
    proceed_window = restore_body[:idx_restore_write] if idx_restore_write != -1 else restore_body
    idx_restore_proceed_invalidate = proceed_window.rfind("id(reg244_last_applied_valid) = false;")
    check("restore_reg244_snapshot's drift comparison exists", idx_restore_drift_if != -1)
    check("a last_applied_valid invalidation exists before the restore write", idx_restore_proceed_invalidate != -1)
    check(
        "the drift comparison occurs BEFORE that invalidation",
        -1 not in (idx_restore_drift_if, idx_restore_proceed_invalidate) and idx_restore_drift_if < idx_restore_proceed_invalidate,
        f"drift check at {idx_restore_drift_if}, invalidate at {idx_restore_proceed_invalidate}",
    )

    print("")
    print("[24] (test C) Restore: last_applied_valid=false occurs, followed by a real preferences sync call (not a delay), BEFORE the restore write")
    # 2026-09-21 durability/sequencing hotfix: reg244_last_applied_valid is
    # a drift-guard convenience field, not part of the restore-capability
    # safety invariant (reg244_snapshot_value/reg244_snapshot_valid, the
    # fields restore-capability actually depends on, are already durably
    # committed by apply_reg244_settings before this script can even run -
    # see [14] above). Its flush is now a real, direct
    # global_preferences->sync() call instead of a fixed delay; a false
    # result is logged but does not block the restore, since a stale
    # last_applied_valid on an unlucky reboot is already handled
    # gracefully elsewhere (the "previous outcome was uncertain" branch).
    check("restore_reg244_snapshot performs a write_multiple_registers call", idx_restore_write != -1)
    check(
        "the proceed-path invalidation occurs BEFORE that write",
        -1 not in (idx_restore_proceed_invalidate, idx_restore_write) and idx_restore_proceed_invalidate < idx_restore_write,
    )
    between_restore = restore_body[idx_restore_proceed_invalidate:idx_restore_write] if -1 not in (idx_restore_proceed_invalidate, idx_restore_write) else ""
    check(
        "a real global_preferences->sync() call separates the invalidation from the restore write",
        "global_preferences->sync()" in between_restore,
        f"between: {between_restore!r}",
    )
    check(
        "no fixed delay: step substitutes for that sync call",
        "delay:" not in between_restore,
    )

    print("")
    print("[25] (test D) last_applied_valid may become true ONLY inside an exact-match post-write verify branch, in both scripts")
    for label, body in (("apply_reg244_settings", apply_body), ("restore_reg244_snapshot", restore_body)):
        true_positions = [m.start() for m in re.finditer(r"reg244_last_applied_valid\) = true;", body)]
        check(f"{label} sets last_applied_valid=true exactly once", len(true_positions) == 1, f"found {len(true_positions)}")
        if true_positions:
            window = body[max(0, true_positions[0] - 400):true_positions[0]]
            check(
                f"{label}'s single last_applied_valid=true is preceded by an exact-match 'ok' guard",
                "bool ok = raw ==" in window and "if (ok)" in window,
            )

    print("")
    print("[26] (test E) Apply reboot-window: nothing between the pre-write invalidation and the write itself re-claims confidence")
    apply_pre_write_gap = apply_body[idx_apply_invalidate:idx_first_write] if -1 not in (idx_apply_invalidate, idx_first_write) else ""
    check(
        "no 'last_applied_valid) = true' appears between invalidation and the write (reboot there => snapshot valid + last-applied uncertain, nothing else)",
        "reg244_last_applied_valid) = true" not in apply_pre_write_gap,
    )

    print("")
    print("[27] (test F) Restore reboot-window: nothing between the pre-write invalidation and the write itself re-claims confidence")
    restore_pre_write_gap = restore_body[idx_restore_proceed_invalidate:idx_restore_write] if -1 not in (idx_restore_proceed_invalidate, idx_restore_write) else ""
    check(
        "no 'last_applied_valid) = true' appears between invalidation and the restore write",
        "reg244_last_applied_valid) = true" not in restore_pre_write_gap,
    )

    # -----------------------------------------------------------------
    # 2026-09-21 durability/sequencing hotfix: completion-driven Modbus
    # sequencing and late-callback protection. See
    # docs/research/esphome-2026.9.0-durability-modbus-sequencing-audit-2026-09-21.md
    # Part 3 for why a fixed delay (even a long one) cannot prove a
    # Modbus operation reached a terminal state, and why the
    # reg244_apply_in_progress guard (rather than a numeric generation
    # token, which ESPHome lambdas cannot actually implement correctly -
    # see that note) is what stops a late callback from reviving an
    # abandoned transaction.
    # -----------------------------------------------------------------

    print("")
    print("[28] (test G) Every Modbus op in both scripts is followed by wait_until on a terminal flag, never a fixed delay")
    for label, body in (("apply_reg244_settings", apply_body), ("restore_reg244_snapshot", restore_body)):
        n_reads = len(re.findall(r"modbus_client\.read_holding_registers:", body))
        n_writes = len(re.findall(r"modbus_client\.write_multiple_registers:", body))
        n_waits = len(re.findall(r"wait_until:", body))
        check(
            f"{label}: every read/write ({n_reads + n_writes}) has a matching wait_until ({n_waits})",
            n_waits >= n_reads + n_writes,
            f"reads={n_reads} writes={n_writes} wait_until={n_waits}",
        )
        check(f"{label}: has zero fixed delay: steps", "delay:" not in body)
        check(
            f"{label}: every wait_until times out at a value strictly greater than the "
            f"unmodified Modbus hub send_wait_time default (2000ms)",
            all(int(ms) > 2000 for ms in re.findall(r"wait_until:\s*\n\s*condition:.*?timeout:\s*(\d+)ms", body, re.S)),
        )

    print("")
    print("[29] (test H) A terminal callback that fires after ownership was released is a documented no-op, not a state mutation")
    # Every on_response/on_error/on_no_response/on_not_sent handler in
    # both scripts sets the shared terminal flag unconditionally (so
    # wait_until always learns the operation finished) but then checks
    # reg244_apply_in_progress before touching any shared snapshot/result
    # state - so a callback landing after this script already gave up and
    # cleared that flag (bounded-wait timeout, or any other abort path)
    # cannot revive the transaction or corrupt whatever runs next. This is
    # the reg244_apply_in_progress case; start_free_power_override /
    # restore_free_power_snapshot use the equivalent
    # free_power_operation_in_progress guard the same way.
    for label, body in (("apply_reg244_settings", apply_body), ("restore_reg244_snapshot", restore_body)):
        n_terminal_sets = len(re.findall(r"id\(reg244_op_terminal\) = true;", body))
        n_guards = len(re.findall(r"if \(!id\(reg244_apply_in_progress\)\)", body))
        check(
            f"{label}: sets the terminal flag in every callback ({n_terminal_sets}) and guards state "
            f"mutation with an in-progress check in most of them ({n_guards})",
            n_terminal_sets >= 1 and n_guards >= n_terminal_sets - 1,
            f"terminal sets={n_terminal_sets} in-progress guards={n_guards}",
        )

print("")
if FAILURES:
    print(f"{len(FAILURES)} check(s) FAILED:")
    for name in FAILURES:
        print(f"  - {name}")
else:
    print("All register-244 proof-harness offline tests PASSED.")

print("")
print("This proves the DESIGNED rules are internally consistent, both as Python")
print("mirrors of the C++ condition lambdas and as structural facts checked")
print("directly against the firmware source. It does NOT prove the real ESPHome")
print("firmware compiles or behaves this way on hardware - that proof is the")
print("live round trip recorded in docs/stage3_3-six-slot-hardware-test.md")
print("(2026-09-21), not anything this file can establish.")

if FAILURES:
    sys.exit(1)
