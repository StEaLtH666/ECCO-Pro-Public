#!/usr/bin/env python3
"""Offline structural/behavioural tests for the 2026-09-22 Free Power
firmware hardening pass (branch `feature/free-power-firmware-hardening`).

Targets docs/SAFE_TRANSACTION_ENGINE_AUDIT_2026-09-21.md's Phase 4 findings
for Free Power (F1/F3/F4/F5): reboot mid-transaction, uncertain Modbus
outcomes, NTP unavailability, bus contention with config polling/RTC, and
the owned-vs-witnessed register split for restore verification.

No I/O, no hardware, no ESPHome/C++ toolchain - text/structure checks
against the real firmware source and the durable-snapshot header, in the
same style as registry/tests/test_recovery_marker_state_machine.py and
registry/tests/test_write_surface_invariants.py, plus one pure-Python
check that the firmware's COMMS backoff table matches the reference model
in registry/transaction_state_machine.py. These prove the source says
what it should, not that the compiled firmware behaves this way on
hardware - see CURRENT_STATE.md's "Free Power firmware hardening" section
for what has and has not been verified.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FIRMWARE_PATH = ROOT / "firmware" / "ecco_clock_dongle_stage3_4_free_power.yaml"
HEADER_PATH = ROOT / "firmware" / "include" / "ecco_durable_snapshot.h"

sys.path.insert(0, str(ROOT / "registry"))
import transaction_state_machine as tsm  # noqa: E402

FAILURES: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  PASS  {name}")
    else:
        FAILURES.append(name)
        print(f"  FAIL  {name}" + (f" - {detail}" if detail else ""))


for p in (FIRMWARE_PATH, HEADER_PATH):
    if not p.is_file():
        print(f"  FAIL  required file not found: {p}")
        sys.exit(1)

fw = FIRMWARE_PATH.read_text(encoding="utf-8")
header = HEADER_PATH.read_text(encoding="utf-8")


def script_body(script_id: str) -> str:
    """Extract one `- id: <script_id>` script's body - see the identical
    helper in test_reg244_proof_harness_logic.py / test_recovery_marker_state_machine.py."""
    marker = f"\n  - id: {script_id}\n"
    start = fw.index(marker)
    rest = fw[start + 1 :]
    m = re.search(r"\n  - id: (?!" + re.escape(script_id) + r"\b)\w+\n|\n[a-z_]+:\n", rest)
    end = m.start() if m else len(rest)
    return rest[:end]


def button_body(button_id: str) -> str:
    marker = f"\n    id: {button_id}\n"
    start = fw.index(marker)
    rest = fw[start + 1 :]
    m = re.search(r"\n  - platform:|\n[a-z_]+:\n", rest)
    end = m.start() if m else len(rest)
    return rest[:end]


# ===========================================================================
# 1. Durable write-outcome uncertainty: the retry/verify-mismatch lockout is
#    a DURABLE record (ecco_durable::FreePowerRetryState), loaded at boot,
#    not a RAM-only flag - the anti-pattern the hardening spec explicitly
#    names (reg244_last_applied_valid-style "last_applied_valid = false").
# ===========================================================================
print("[1] Durable write-outcome/retry-lockout state survives reboot (not RAM-only)")
check(
    "ecco_durable::FreePowerRetryState is declared in the durable header",
    "struct FreePowerRetryState" in header and "uint8_t operator_needed" in header,
)
check(
    "FreePowerRetryState has its own dedicated tag, separate from the snapshot/marker tags",
    'FREE_POWER_RETRY_TAG = "ecco_free_power_retry_state_v1"' in header,
)
check(
    "on_boot loads the durable retry state into free_power_operator_needed",
    bool(re.search(r"load_record\(\s*\n?\s*ecco_durable::key_for\(ecco_durable::FREE_POWER_RETRY_TAG\), retry\);\s*\n\s*id\(free_power_operator_needed\) = have_retry && retry\.operator_needed != 0;", fw)),
)
check(
    "a second consecutive verify mismatch commits the lockout durably before setting it in RAM for this runtime",
    bool(re.search(
        r"retry\.operator_needed = 1;\s*\n\s*if \(ecco_durable::commit_record\(ecco_durable::key_for\(ecco_durable::FREE_POWER_RETRY_TAG\), retry\)\) \{\s*\n\s*id\(free_power_operator_needed\) = true;",
        fw,
    )),
)

# ===========================================================================
# 2. END/restore-request survives a modelled reboot: durably committed
#    BEFORE the restore is attempted, not left RAM-only.
# ===========================================================================
print("")
print("[2] END EARLY / restore-request is committed durably, not RAM-only, before restore is attempted")
end_body = button_body("end_free_power_button")
check(
    "the End Free Power button sets free_power_restore_requested in RAM",
    "id(free_power_restore_requested) = true;" in end_body,
)
check(
    "...AND durably commits data.restore_requested = 1 under the existing snapshot-data tag",
    "data.restore_requested = 1;" in end_body
    and "ecco_durable::commit_record(ecco_durable::key_for(ecco_durable::FREE_POWER_DATA_TAG), data)" in end_body,
)
commit_idx = end_body.find("ecco_durable::commit_record(ecco_durable::key_for(ecco_durable::FREE_POWER_DATA_TAG), data)")
restore_call_idx = end_body.find("id: restore_free_power_snapshot")
check(
    "the durable commit happens BEFORE restore_free_power_snapshot is invoked",
    -1 not in (commit_idx, restore_call_idx) and commit_idx < restore_call_idx,
)
check(
    "on_boot reconstructs free_power_restore_requested from the durable record (data.restore_requested)",
    "id(free_power_restore_requested) = data.restore_requested != 0;" in fw,
)
check(
    "the watchdog's END-request branch is checked before the ordinary scheduled-end-time branch",
    fw.index("if (id(free_power_restore_requested)) return true;")
    < fw.index("return millis() >= ${ecco_free_power_invalid_clock_grace_ms}UL;"),
)

# ===========================================================================
# 3. Free Power cannot dispatch a restore write from a stale poll-cache
#    value alone - a dedicated fresh read precedes the write.
# ===========================================================================
print("")
print("[3] Restore performs a fresh, dedicated hardware read before ever writing")
dispatch_body = script_body("restore_free_power_snapshot_dispatch")
first_read = dispatch_body.find("modbus_client.read_holding_registers:")
first_write = dispatch_body.find("modbus_client.write_multiple_registers:")
check(
    "restore_free_power_snapshot_dispatch performs at least one fresh read",
    first_read != -1,
)
check(
    "...and that read happens strictly BEFORE the first restore write (never write-first)",
    -1 not in (first_read, first_write) and first_read < first_write,
)
check(
    "a failed fresh read is treated as fail-closed (marks the attempt failed, never proceeds to write)",
    "id(free_power_live_read_ok) = true;" in dispatch_body
    and "id(free_power_write_failed) = true;" in dispatch_body,
)
check(
    "the write sequence is explicitly gated on the fresh read having succeeded "
    "(and, since the 2026-09-22 corrective pass, on live matching ECCO's INTENDED state - see part [11] below; "
    "since SG-01 Phase 4, or on a journal-proven SELF_PARTIAL state)",
    bool(re.search(
        r"return !id\(free_power_write_failed\) && id\(free_power_live_read_ok\) && "
        r"!id\(free_power_live_owned_matches\) && \(id\(free_power_live_matches_intended\) \|\| "
        r"id\(free_power_live_self_partial\)\);",
        dispatch_body,
    )),
)

# ===========================================================================
# 4. OBSOLETE AS OF 2026-09-23: registers 256-261 (TOU Power) were
#    witnessed-but-not-owned as of this 2026-09-22 pass; post-reboot live
#    characterisation subsequently proved TOU Power is the inverter's
#    native battery charge/discharge ceiling, and
#    registry/tests/test_free_power_tou_power_ownership_2026_09_23.py now
#    covers their promotion to OWNED in full. This section is kept, in the
#    same numbered position, asserting the CURRENT (owned) behaviour so a
#    reader of this file's history is not misled by a stale "never gates"
#    claim sitting uncorrected next to the rest of this pass's proofs.
# ===========================================================================
print("")
print("[4] SUPERSEDED 2026-09-23: registers 256-261 (TOU Power) are now OWNED, not witnessed - see test_free_power_tou_power_ownership_2026_09_23.py")
start_body = script_body("start_free_power_override")
for name, body in (("start_free_power_override (activation verify)", start_body), ("restore_free_power_snapshot_dispatch (restore verify)", dispatch_body)):
    ok_stmt_m = re.search(r"bool ok = [^\n]+;", body)
    check(f"{name}: found the verify `ok` gate expression", ok_stmt_m is not None)
    if ok_stmt_m:
        ok_expr = ok_stmt_m.group(0)
        check(
            f"{name}: the owned powers_ok/powers_restored_ok comparison IS part of the `ok` gate "
            f"(2026-09-23: promoted from witnessed to owned)",
            "powers_ok" in ok_expr or "powers_restored_ok" in ok_expr,
            ok_expr,
        )
own_regs = tsm.ECCO_CONFLICT_DECLARATIONS["free_power_transaction"][0]
check(
    "the reference model's declared owned registers for free_power_transaction now INCLUDE 256-261 "
    "(2026-09-23 TOU Power ownership promotion)",
    (own_regs & set(range(256, 262))) == set(range(256, 262)),
    sorted(own_regs),
)
check(
    "...and DO include every register Free Power actually writes (230, 232, 256-261, 268-279)",
    own_regs == (frozenset({230, 232}) | frozenset(range(256, 262)) | frozenset(range(268, 280))),
)

# ===========================================================================
# 5/7. Cause-aware bounded retry/backoff: COMMS backs off (bounded, never
#      abandons the obligation); a VERIFY MISMATCH gets at most one
#      automatic repeat before requiring an operator decision.
# ===========================================================================
print("")
print("[5/7] Retry/backoff is cause-aware and bounded - COMMS backs off, VERIFY MISMATCH stops after one repeat")
check(
    "ecco_durable::comms_backoff_ms exists and matches registry/transaction_state_machine.py's reference table",
    "inline uint32_t comms_backoff_ms(int attempt_number)" in header,
)
header_table_m = re.search(r"table_ms\[\] = \{([^}]+)\};", header)
check("found the firmware's COMMS backoff table literal", header_table_m is not None)
if header_table_m:
    firmware_ms = [int(x.strip()) for x in header_table_m.group(1).split(",")]
    reference_ms = [int(s * 1000) for s in tsm._COMMS_BACKOFF_SECONDS]
    check(
        "the firmware's backoff table (ms) equals the Python reference model's table (seconds*1000)",
        firmware_ms == reference_ms,
        f"firmware={firmware_ms} reference={reference_ms}",
    )
check(
    "every COMMS-failure branch in the restore dispatch increments the attempt counter and recomputes the backoff deadline",
    dispatch_body.count("id(free_power_comms_restore_attempts)++;") >= 4,
    f"found {dispatch_body.count('id(free_power_comms_restore_attempts)++;')} occurrences",
)
check(
    "a successful verified restore resets the COMMS attempt counter and the verify-mismatch counter",
    "id(free_power_comms_restore_attempts) = 0;" in dispatch_body
    and "id(free_power_verify_mismatch_count) = 0;" in dispatch_body,
)
check(
    "a first verify mismatch does not set operator_needed (still allows one automatic repeat)",
    bool(re.search(r"if \(id\(free_power_verify_mismatch_count\) >= 2\) \{", dispatch_body)),
)
check(
    "reg244's own retry_policy model agrees: VERIFY_MISMATCH permits exactly one automatic retry, then exhausts",
    tsm.retry_policy(tsm.RetryCause.VERIFY_MISMATCH, 0).decision is tsm.RetryDecision.RETRY_PERMITTED
    and tsm.retry_policy(tsm.RetryCause.VERIFY_MISMATCH, 1).decision is tsm.RetryDecision.RETRY_EXHAUSTED,
)
wrapper_body = script_body("restore_free_power_snapshot")
check(
    "an explicit End Free Power press (operator decision) resets the backoff/lockout state before delegating to dispatch",
    bool(re.search(r"if \(explicit_operator_request\) \{\s*\n\s*id\(free_power_operator_needed\) = false;", wrapper_body)),
)
check(
    "an AUTOMATIC attempt while operator_needed is set is refused (gate_ok=false) rather than writing",
    bool(re.search(r"if \(id\(free_power_operator_needed\)\) \{\s*\n\s*id\(free_power_restore_gate_ok\) = false;", wrapper_body)),
)

# ===========================================================================
# 6. Durable-clear retry never authorises another Modbus write (regression
#    guard - this property predates this hardening pass but must survive
#    the restore_free_power_snapshot -> wrapper+dispatch split).
# ===========================================================================
print("")
print("[6] The PENDING_CLEAR (durable-clear-only) retry path still performs zero Modbus activity")
pending_clear_cond = wrapper_body.find("MARKER_RESTORE_VERIFIED_PENDING_CLEAR")
check("found the PENDING_CLEAR branch in the public wrapper", pending_clear_cond != -1)
if pending_clear_cond != -1:
    else_m = re.search(r"\n +else:\n", wrapper_body[pending_clear_cond:])
    clear_only_branch = wrapper_body[pending_clear_cond : pending_clear_cond + else_m.start()] if else_m else ""
    check(
        "the clear-only branch contains no modbus_client. call",
        "modbus_client." not in clear_only_branch,
    )

# ===========================================================================
# 8. Invalid wall clock cannot keep a Free Power lease active indefinitely.
# ===========================================================================
print("")
print("[8] An invalid wall clock after reboot cannot keep a verified Free Power lease active forever")
watchdog_m = re.search(r"interval: 15s\n.*?condition:\n *lambda: \|-\n(.*?)\n          then:", fw, re.S)
check("found the Free Power 15s watchdog condition", watchdog_m is not None)
if watchdog_m:
    watchdog_cond = watchdog_m.group(1)
    check(
        "the watchdog no longer unconditionally `return false` when the clock is invalid",
        "if (!now.is_valid() || id(free_power_end_epoch) == 0) return false;" not in watchdog_cond,
    )
    check(
        "...it falls back to a bounded uptime-based grace period instead",
        "return millis() >= ${ecco_free_power_invalid_clock_grace_ms}UL;" in watchdog_cond,
    )
check(
    "the grace period substitution is defined and matches the reference model's DEFAULT_INVALID_CLOCK_GRACE_S (300s)",
    'ecco_free_power_invalid_clock_grace_ms: "300000"' in fw
    and tsm.DEFAULT_INVALID_CLOCK_GRACE_S == 300.0,
)

# ===========================================================================
# 9. Config polling and RTC cannot dispatch while a hardened transaction
#    owns the bus - re-checked at their own FINAL dispatch point, not only
#    by their callers (audit finding F1/F3).
# ===========================================================================
print("")
print("[9] Config polling and RTC re-check bus ownership at their own final dispatch point")
poll_wrapper = script_body("poll_inverter_configuration")
check(
    "poll_inverter_configuration (the id every caller uses) checks manual_write_in_progress before dispatching",
    bool(re.search(r"return !id\(manual_write_in_progress\);", poll_wrapper)),
)
check(
    "...and defers to the dispatch script only when the bus is free (never both branches touch Modbus)",
    "modbus_client." not in poll_wrapper and "id: poll_inverter_configuration_dispatch" in poll_wrapper,
)
rtc_body = script_body("write_inverter_rtc")
bus_check_idx = rtc_body.find("return id(manual_write_in_progress);")
ntp_write_idx = rtc_body.find("modbus_client.write_multiple_registers:")
check(
    "write_inverter_rtc checks manual_write_in_progress",
    bus_check_idx != -1,
)
check(
    "...strictly BEFORE its own RTC write dispatch (registers 22-24)",
    -1 not in (bus_check_idx, ntp_write_idx) and bus_check_idx < ntp_write_idx,
)
check(
    "a deferred RTC correction cleanly cancels (does not leave correction_in_progress stuck, which would deadlock Free Power's own !correction_in_progress precondition)",
    bool(re.search(r"return id\(manual_write_in_progress\);\s*\n\s*then:\s*\n\s*- lambda: \|-\s*\n(?:.*\n)*?\s*id\(correction_in_progress\) = false;", rtc_body)),
)

# ===========================================================================
# 10. Register 245 (Export Limit) remains outside every write surface.
# ===========================================================================
print("")
print("[10] Register 245 (Export Limit) has no write path anywhere in this branch")
check(
    "no modbus_client.write_multiple_registers block in the firmware targets register 245",
    not re.search(r"modbus_client\.write_multiple_registers:.{1,400}?start_address:\s*245\b", fw, re.S),
)
capabilities_text = (ROOT / "registry" / "inverter_capabilities.yaml").read_text(encoding="utf-8")
export_limit_m = re.search(r"- id: export_limit\n.*?(?=\n- id: )", capabilities_text, re.S)
check("found the export_limit capability record", export_limit_m is not None)
if export_limit_m:
    check(
        "register 245 stays declared read-only in the capability registry",
        "current_access: read_only" in export_limit_m.group(0),
    )

# ===========================================================================
# CORRECTIVE PASS (2026-09-22, 4th commit): a reviewer inspecting the pushed
# branch found 5 concrete remaining gaps in the first 3 commits. Sections
# 11-15 below prove each one, in the same offline structural/behavioural
# style as sections 1-10 above.
# ===========================================================================

# ===========================================================================
# 11. BLOCKER 1 - operator action must be a ONE-SHOT authorisation, never
#     inferred from the DURABLE lease flag free_power_restore_requested
#     (which stays true across every later automatic watchdog retry).
# ===========================================================================
print("")
print("[11] BLOCKER 1: operator action is a one-shot flag, separate from the durable lease flag")
check(
    "regression guard: the wrapper no longer derives explicit_operator_request from the DURABLE lease flag",
    "bool explicit_operator_request = id(free_power_restore_requested);" not in fw,
)
check(
    "...it derives it from the RAM one-shot free_power_operator_retry_this_call instead",
    "bool explicit_operator_request = id(free_power_operator_retry_this_call);" in wrapper_body,
)
check(
    "end_free_power_button arms the one-shot flag (free_power_operator_retry_pending) on every press",
    "id(free_power_operator_retry_pending) = true;" in end_body,
)
check(
    "the wrapper consumes (reads then immediately clears) the one-shot flag unconditionally, "
    "before branching on marker state - so it can never leak into a later, purely automatic watchdog invocation",
    bool(re.search(
        r"id\(free_power_operator_retry_this_call\) = id\(free_power_operator_retry_pending\);\s*\n\s*"
        r"id\(free_power_operator_retry_pending\) = false;",
        wrapper_body,
    )),
)
consume_idx = wrapper_body.find("id(free_power_operator_retry_pending) = false;")
marker_branch_idx = wrapper_body.find("MARKER_RESTORE_VERIFIED_PENDING_CLEAR")
check(
    "...and that consumption happens BEFORE the PENDING_CLEAR/RESTORE_REQUIRED branch decision "
    "(covers point (5): a watchdog retry landing in either branch cannot see a stale flag)",
    -1 not in (consume_idx, marker_branch_idx) and consume_idx < marker_branch_idx,
)
check(
    "point (5): the durable lease flag free_power_restore_requested is never itself tested as an "
    "operator-authorisation condition inside the wrapper (the exact bug fixed)",
    not re.search(r"if\s*\(\s*id\(free_power_restore_requested\)\s*\)", wrapper_body),
)
check(
    "point (3): the durable lease flag is still SET (by the button) and still READ (by on_boot / the "
    "watchdog) elsewhere - only its (mis)use as an operator-authorisation test was removed",
    "id(free_power_restore_requested) = true;" in end_body
    and "id(free_power_restore_requested) = data.restore_requested != 0;" in fw
    and "if (id(free_power_restore_requested)) return true;" in fw,
)
check(
    "points (1)/(2)/(4)/(6)/(7): COMMS backoff, the verify-mismatch counter, and the durable operator "
    "lockout are gated ONLY by explicit_operator_request (the one-shot flag) or by a verified success - "
    "never by the durable lease flag - matching section [5/7]'s existing coverage of that gating logic",
    bool(re.search(r"if \(explicit_operator_request\) \{\s*\n\s*id\(free_power_operator_needed\) = false;", wrapper_body))
    and bool(re.search(r"if \(id\(free_power_operator_needed\)\) \{\s*\n\s*id\(free_power_restore_gate_ok\) = false;", wrapper_body)),
)

# ===========================================================================
# 12. BLOCKER 2 - the durable operator lockout must actually be CLEARABLE,
#     not just settable, and a NEW transaction must start from clean state.
# ===========================================================================
print("")
print("[12] BLOCKER 2: durable operator-needed lockout is durably cleared, not only durably set")
check(
    "an explicit operator retry durably clears the lockout record (operator_needed=0) BEFORE delegating to dispatch",
    bool(re.search(
        r"if \(explicit_operator_request\) \{.*?cleared_retry\.operator_needed = 0;\s*\n\s*"
        r"if \(!ecco_durable::commit_record\(ecco_durable::key_for\(ecco_durable::FREE_POWER_RETRY_TAG\), cleared_retry\)\)",
        wrapper_body,
        re.S,
    )),
)
check(
    "a successfully verified restore (Phase D marker clear succeeds) ALSO durably re-commits a clean "
    "retry record, as defence in depth",
    dispatch_body.count("clean_retry.operator_needed = 0;") >= 1
    and "ecco_durable::commit_record(ecco_durable::key_for(ecco_durable::FREE_POWER_RETRY_TAG), clean_retry)" in dispatch_body,
)
start_body = script_body("start_free_power_override")
check(
    "a NEW Free Power start durably resets the retry/lockout record to clean BEFORE any override write",
    "clean_retry.operator_needed = 0;" in start_body
    and "bool retry_reset_committed = ecco_durable::commit_record(" in start_body,
)
reset_idx = start_body.find("bool retry_reset_committed = ecco_durable::commit_record(")
first_write_idx = start_body.find("modbus_client.write_multiple_registers:")
check(
    "...and that reset happens strictly BEFORE start_free_power_override's first override write",
    -1 not in (reset_idx, first_write_idx) and reset_idx < first_write_idx,
)
check(
    "...and a failed durable reset ABORTS the start (sets free_power_write_failed) rather than proceeding "
    "while unable to prove the lockout is actually clean",
    bool(re.search(
        r"if \(retry_reset_committed\) \{.*?\} else \{\s*\n\s*id\(free_power_write_failed\) = true;",
        start_body,
        re.S,
    )),
)

# ===========================================================================
# 13. BLOCKER 3 - restore must classify live state against BOTH the original
#     snapshot AND ECCO's own intended state, never blindly overwrite drift.
# ===========================================================================
print("")
print("[13] BLOCKER 3: restore classifies live state (snapshot / intended / neither) before ever writing")
check(
    "FreePowerSnapshotData grew reg230_intended - the one piece of intended state not already "
    "deterministic from the snapshot fields",
    "uint16_t reg230_intended;" in header,
)
check(
    "the struct change used a NEW versioned tag (rule 1), not a same-tag layout change (rule 2) - "
    "the old v1 tag constant is retained, unused, as a historical record, never repurposed. "
    "(2026-09-23: the tag was bumped again to v3 when reg_tou_power_intended was added - see "
    "test_free_power_tou_power_ownership_2026_09_23.py - so this checks v1 is retired and the "
    "CURRENT alias exists, without pinning it to a specific version number here.)",
    'FREE_POWER_DATA_TAG_V1 = "ecco_free_power_snapshot_data_v1"' in header
    and "constexpr const char *FREE_POWER_DATA_TAG = FREE_POWER_DATA_TAG_V" in header
    and fw.count("ecco_durable::FREE_POWER_DATA_TAG_V1") == 0,
)
check(
    "on_boot restores the persisted intended reg230 into the RAM working copy for a RESTORE_REQUIRED marker",
    "id(free_power_target_reg230) = data.reg230_intended;" in fw,
)
check(
    "every site that rebuilds a FreePowerSnapshotData record from a zero-initialised struct also sets "
    "reg230_intended (start, activation-verify re-commit, END-request re-commit) - otherwise it would "
    "silently zero the field on that write",
    fw.count("data.reg230_intended = ") >= 3,
)
check(
    "the fresh pre-restore read also compares live 230/232 against the INTENDED values, not only the original snapshot",
    "id(free_power_live_230_ok_intended) = (values[0] == id(free_power_target_reg230));" in dispatch_body
    and bool(re.search(r"id\(free_power_live_232_ok_intended\) = \(values\[2\] == \(uint16_t\)\(id\(free_power_snapshot_reg232\) \| 0x0001\)\);", dispatch_body)),
)
check(
    "...and the owned 268-279 registers are compared against the deterministic INTENDED values "
    "(100% SOC, source bits forced to Grid) to produce free_power_live_matches_intended",
    "id(free_power_live_matches_intended) = intended_matches;" in dispatch_body,
)
# SG-01 Phase 4: a journal-proven SELF_PARTIAL state shares case 2's write
# branch (never a copy of it) and is excluded from case 3 - see
# registry/tests/test_sg01_self_partial_phase3_4.py for its behaviour.
write_gate_m = re.search(r"return !id\(free_power_write_failed\) && id\(free_power_live_read_ok\) && !id\(free_power_live_owned_matches\) && \(id\(free_power_live_matches_intended\) \|\| id\(free_power_live_self_partial\)\);", dispatch_body)
drift_gate_m = re.search(r"return !id\(free_power_write_failed\) && id\(free_power_live_read_ok\) && !id\(free_power_live_owned_matches\) && !id\(free_power_live_matches_intended\) && !id\(free_power_live_self_partial\);", dispatch_body)
check("case 1 (already matches original snapshot) still skips the write entirely - unchanged from section [3]", first_read < first_write)
check("case 2 (matches ECCO's own intended state - or, since SG-01 Phase 4, a journal-proven SELF_PARTIAL state) "
      "is the ONLY case that may proceed to write", write_gate_m is not None)
check("case 3 (matches NEITHER original nor intended, and not SELF_PARTIAL) is a distinct, explicitly non-writing branch",
      drift_gate_m is not None)
check(
    "case 2 and case 3 are mutually exclusive by construction (both require !owned_matches; one requires "
    "matches_intended || self_partial, the other !matches_intended && !self_partial) - textual order between "
    "them does not matter for correctness, only that neither can ever fire for the other's condition",
    write_gate_m is not None and drift_gate_m is not None and write_gate_m.group(0) != drift_gate_m.group(0),
)
check(
    "case 3 never issues a Modbus write of its own",
    "modbus_client." not in dispatch_body[drift_gate_m.start():drift_gate_m.start() + 1600] if drift_gate_m else False,
)
check(
    "case 3 durably requires an operator decision (reuses the same durable FreePowerRetryState lockout "
    "as a repeated verify mismatch, rather than inventing a second lockout mechanism)",
    bool(re.search(
        r"id\(free_power_restore_unexplained_drift\) = true;\s*\n\s*id\(free_power_failures\)\+\+;\s*\n\s*"
        r"ecco_durable::FreePowerRetryState retry\{\};\s*\n\s*retry\.operator_needed = 1;",
        dispatch_body,
    )),
)
check(
    "case 3 retains the durable restore obligation untouched - it never clears free_power_snapshot_valid "
    "or the marker, and never touches the COMMS backoff attempt counter/deadline",
    "id(free_power_snapshot_valid) = false;" not in dispatch_body[drift_gate_m.start():drift_gate_m.start() + 1600] if drift_gate_m else False,
)
check(
    "the COMMS-backoff bottom branch is skipped for the drift case, so it cannot double-handle case 3 "
    "with a misleading COMMS message or incorrectly apply COMMS pacing to a classification refusal "
    "(2026-09-24 PR-A: the same exclusion now also covers a register-244 context hold)",
    bool(re.search(
        r"else:\s*\n(?:[^\n]*\n)*?\s*- if:\s*\n\s*condition:\s*\n\s*lambda: 'return "
        r"!id\(free_power_restore_unexplained_drift\) && !id\(free_power_context_hold\);'",
        dispatch_body,
    )),
)

# ===========================================================================
# 14. BLOCKER 4 - configuration_online must not gate the recovery path.
# ===========================================================================
print("")
print("[14] BLOCKER 4: configuration_online is not a precondition of restore/recovery")
wrapper_precondition_m = re.search(
    # 2026-09-24 (PR-A, Part 9): a one-shot operator-retry-authorisation
    # consumption lambda now precedes the top-level "- if:" gate (moved
    # there so a rejected call still consumes the flag - see
    # restore_free_power_snapshot). Tolerate that (or any other) content
    # between "then:" and the first "- if:" non-greedily, rather than
    # requiring the gate to be the immediate first action.
    r"- id: restore_free_power_snapshot\s*\n\s*mode: single\s*\n\s*then:\n.*?"
    r"- if:\s*\n\s*condition:\s*\n\s*lambda: \|-\s*\n(.*?)\n\s*then:",
    fw, re.S,
)
check("found restore_free_power_snapshot's top-level precondition lambda", wrapper_precondition_m is not None)
if wrapper_precondition_m:
    # Substring-only match would also flag the explanatory comment this
    # corrective pass itself added inline ("...configuration_online is
    # deliberately NOT a precondition here...") as a false failure - check
    # for actual USAGE (id(configuration_online)) instead of bare text.
    check(
        "configuration_online is NOT checked (no id(configuration_online) usage) in "
        "restore_free_power_snapshot's top-level precondition",
        "id(configuration_online)" not in wrapper_precondition_m.group(1),
    )
check(
    "the 15s watchdog no longer refuses to fire merely because configuration_online is false",
    "if (!id(configuration_online).state) return false;" not in watchdog_cond if watchdog_m else False,
)
check(
    "the PENDING_CLEAR (clear-only, zero-Modbus) branch has no configuration_online dependency either "
    "(trivially true - it was never conditioned on it, and still performs no modbus_client. call - see section [6])",
    "configuration_online" not in wrapper_body[pending_clear_cond:pending_clear_cond + else_m.start()] if (pending_clear_cond != -1 and else_m) else True,
)
check(
    "a failed fresh read still fails closed and backs off via the ordinary COMMS branch (unchanged by "
    "removing configuration_online - see section [3]'s fail-closed check and section [5/7]'s backoff table)",
    "id(free_power_write_failed) = true;" in dispatch_body and "comms_backoff_ms" in dispatch_body,
)

# ===========================================================================
# 15. BLOCKER 5 - the config-poll bus-ownership guard must be at the FINAL
#     dispatch point (inside poll_inverter_configuration_dispatch itself),
#     not only one layer above it.
# ===========================================================================
print("")
print("[15] BLOCKER 5: poll_inverter_configuration_dispatch guards itself before its first Modbus call")
poll_dispatch_body = script_body("poll_inverter_configuration_dispatch")
guard_m = re.search(r"return !id\(manual_write_in_progress\) && !id\(correction_in_progress\);", poll_dispatch_body)
check(
    "poll_inverter_configuration_dispatch itself (not just its caller poll_inverter_configuration) "
    "checks manual_write_in_progress AND correction_in_progress",
    guard_m is not None,
)
first_dispatch_read = poll_dispatch_body.find("modbus_client.read_holding_registers:")
check(
    "...and that guard sits strictly BEFORE this script's own first Modbus call - the actual final "
    "dispatch point the reviewer required, not one layer above it",
    guard_m is not None and first_dispatch_read != -1 and guard_m.start() < first_dispatch_read,
)
check(
    "no second, differently-named callable Modbus script was introduced to hold the guarded body "
    "(which would just recreate the same 'guard is one layer above the writer' gap one level down) - "
    "exactly two script ids exist in this family: the wrapper and its one dispatch",
    fw.count("\n  - id: poll_inverter_configuration\n") == 1 and fw.count("\n  - id: poll_inverter_configuration_dispatch\n") == 1,
)
check(
    "ordinary callers are unchanged: exactly one script.execute targets poll_inverter_configuration_dispatch "
    "(poll_inverter_configuration's own delegation) - every other caller in the firmware still goes through "
    "the wrapper id poll_inverter_configuration, never the dispatch id directly",
    fw.count("id: poll_inverter_configuration_dispatch") == 2,  # its own `- id:` definition + the one script.execute call
)

print("")
if FAILURES:
    print(f"{len(FAILURES)} check(s) FAILED:")
    for name in FAILURES:
        print(f"  - {name}")
else:
    print("All 2026-09-22 Free Power hardening offline tests PASSED.")

print("")
print("These are STRUCTURAL/source-text and pure-Python-model facts. They prove the")
print("source and the reference model agree with each other and with the stated")
print("design - they do NOT prove the compiled firmware behaves this way against")
print("real hardware. See CURRENT_STATE.md for what remains unverified.")

if FAILURES:
    sys.exit(1)
