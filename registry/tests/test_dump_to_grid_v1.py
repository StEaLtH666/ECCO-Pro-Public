#!/usr/bin/env python3
"""Offline structural/logic tests for Manual Dump-to-Grid V1.

No I/O, no hardware, no ESPHome toolchain, no Home Assistant. Uses
tools/analyze_write_surface.py to parse the firmware into a structured
model (same tool registry/tests/test_write_surface_invariants.py uses),
plus direct text-based checks against the firmware source and
firmware/include/ecco_durable_snapshot.h for facts that tool does not
model (write-value literals, C++ struct fields, exact operation ordering
within a script).

What this proves
-----------------
That the FIRMWARE SOURCE matches the design documented in
docs/DUMP_TO_GRID_V1.md: the write surface is exactly {244, 256-261},
registers 243/245/248/250-255 are never touched by this feature, the
activation/restore ordering is what the design claims, the durable
snapshot schema is what it claims to be, mutual exclusion with Free Power
and the register 244 standalone harness is bidirectional, and Accept
Current State performs zero Modbus I/O.

What this does NOT prove
-------------------------
That the firmware compiles, that ESPHome schedules these actions in the
order the source implies, or that the inverter does anything in
particular. See registry/tests/test_write_surface_invariants.py's own
docstring for the same disclaimer - it applies here unchanged. No live
Dump-to-Grid event, OTA, or inverter write has been performed as part of
this feature.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

from analyze_write_surface import DEFAULT_FIRMWARE, analyze, _split_blocks  # noqa: E402

FAILURES: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  PASS  {name}")
    else:
        FAILURES.append(name)
        print(f"  FAIL  {name}" + (f" - {detail}" if detail else ""))


FIRMWARE_TEXT = DEFAULT_FIRMWARE.read_text(encoding="utf-8")
DURABLE_HEADER = (ROOT / "firmware" / "include" / "ecco_durable_snapshot.h").read_text(encoding="utf-8")

result = analyze(DEFAULT_FIRMWARE)
paths = result["paths"]
by_name = {p.name: p for p in paths}
scripts = {name: p.body for name, p in by_name.items() if p.kind == "script"}
buttons = {name: p.body for name, p in by_name.items() if p.kind == "button"}


# tools/analyze_write_surface.py's analyze() filters out any block with no
# Modbus ops, no ownership-flag acquisition and no detected script.execute
# dispatch (see its own `if ops or wp.acquires or wp.dispatches:` guard) -
# request_dump_end, dump_force_restore_original and dump_accept_current_state
# all legitimately have none of those (they use the single-line
# `script.execute: <id>` shorthand rather than the `script.execute:\n  id:`
# mapping form its dispatch regex matches), so they never reach `paths`.
# Pull every block unfiltered instead, purely for locating their bodies -
# this does not change what analyze()/write_surface() consider write paths.
ALL_BLOCKS = {name: body for kind, name, body in _split_blocks(FIRMWARE_TEXT) if kind == "script"}
scripts.update({k: v for k, v in ALL_BLOCKS.items() if k not in scripts})


def script_body(name: str) -> str:
    if name not in scripts:
        FAILURES.append(f"script '{name}' not found in the firmware source")
        print(f"  FAIL  script '{name}' not found in the firmware source")
        return ""
    return scripts[name]


start = script_body("start_dump_to_grid_override")
restore = script_body("restore_dump_to_grid_snapshot")
request_end = script_body("request_dump_end")
force_restore = script_body("dump_force_restore_original")
accept_current = script_body("dump_accept_current_state")

print("[1] Both Dump-to-Grid write scripts exist and are discovered by the write-surface analyzer")
check("start_dump_to_grid_override exists", bool(start))
check("restore_dump_to_grid_snapshot exists", bool(restore))
check("request_dump_end exists", bool(request_end))
check("dump_force_restore_original exists", bool(force_restore))
check("dump_accept_current_state exists", bool(accept_current))

print("")
print("[2] Write surface is exactly {244, 256-261} - see test_write_surface_invariants.py [2b] for the pinned check")
for name in ("start_dump_to_grid_override", "restore_dump_to_grid_snapshot"):
    p = by_name[name]
    check(f"{name}: writes exactly {{244, 256-261}}", p.written_addresses == {244, 256, 257, 258, 259, 260, 261})

print("")
print("[3] Forbidden registers 243, 245, 248, 250-255 never appear as a write target anywhere in this feature")
FORBIDDEN = {243, 245, 248, 250, 251, 252, 253, 254, 255}
for name in ("start_dump_to_grid_override", "restore_dump_to_grid_snapshot", "request_dump_end", "dump_force_restore_original", "dump_accept_current_state"):
    p = by_name.get(name)
    if p is None:
        continue
    check(f"{name}: touches none of the forbidden registers", not (p.written_addresses & FORBIDDEN))

print("")
print("[4] Accept Current State performs ZERO Modbus I/O")
check(
    "dump_accept_current_state issues no modbus_client call of any kind",
    "modbus_client." not in accept_current,
)
check(
    "dump_accept_current_state's write surface (per the analyzer) is empty",
    "dump_accept_current_state" not in by_name or not by_name["dump_accept_current_state"].ops,
)

print("")
print("[5] Force Restore Original requires operator_needed + recovery arm + a valid snapshot, and always disarms")
check(
    "dump_force_restore_original's precondition checks dump_operator_needed",
    "id(dump_operator_needed)" in force_restore,
)
check(
    "dump_force_restore_original's precondition checks dump_recovery_arm.state",
    "id(dump_recovery_arm).state" in force_restore,
)
check(
    "dump_force_restore_original's precondition checks dump_snapshot_valid",
    "id(dump_snapshot_valid)" in force_restore,
)
check(
    "dump_force_restore_original always turns dump_recovery_arm back off (one-shot, present as its own final step)",
    "- lambda: 'id(dump_recovery_arm).turn_off();'" in force_restore,
)
check(
    "dump_accept_current_state also requires the same three preconditions and disarms",
    "id(dump_operator_needed)" in accept_current
    and "id(dump_recovery_arm).state" in accept_current
    and "id(dump_snapshot_valid)" in accept_current
    and "- lambda: 'id(dump_recovery_arm).turn_off();'" in accept_current,
)

print("")
print("[6] Activation write ordering: 256-261 (the ceiling) before 244 (the enable) - see docs/DUMP_TO_GRID_V1.md")
start_256_offsets = [op.offset for op in by_name["start_dump_to_grid_override"].writes if op.start_address == 256]
start_244_offsets = [op.offset for op in by_name["start_dump_to_grid_override"].writes if op.start_address == 244]
check(
    "start_dump_to_grid_override writes 256-261 exactly once and 244 exactly once",
    len(start_256_offsets) == 1 and len(start_244_offsets) == 1,
    f"256-offsets={start_256_offsets} 244-offsets={start_244_offsets}",
)
if start_256_offsets and start_244_offsets:
    check(
        "the 256-261 write happens BEFORE the 244 write on activation",
        start_256_offsets[0] < start_244_offsets[0],
    )

print("")
print("[7] Restore write ordering: 244 (disable export) before 256-261 (the ceiling) - the reverse of activation")
restore_256_offsets = [op.offset for op in by_name["restore_dump_to_grid_snapshot"].writes if op.start_address == 256]
restore_244_offsets = [op.offset for op in by_name["restore_dump_to_grid_snapshot"].writes if op.start_address == 244]
check(
    "restore_dump_to_grid_snapshot writes 244 exactly once and 256-261 exactly once",
    len(restore_244_offsets) == 1 and len(restore_256_offsets) == 1,
    f"244-offsets={restore_244_offsets} 256-offsets={restore_256_offsets}",
)
if restore_244_offsets and restore_256_offsets:
    check(
        "the 244 write happens BEFORE the 256-261 write on restore",
        restore_244_offsets[0] < restore_256_offsets[0],
    )

print("")
print("[8] Activation writes 244 to exactly 0 (Allow Export), never a staged/derived value")
m = re.search(
    r"start_address:\s*244\s*\n\s*values:\s*!lambda\s*'return std::vector<uint16_t>\{\(uint16_t\)\s*0\};'",
    start,
)
check("the literal write value for register 244 on activation is the constant 0", m is not None)

print("")
print("[9] Durable snapshot is committed before ANY inverter write (activation)")
first_write_offset = by_name["start_dump_to_grid_override"].first_write_offset
durable_commits_before = by_name["start_dump_to_grid_override"].durable_commits_before(first_write_offset)
check(
    "start_dump_to_grid_override commits a durable record at least twice (data + valid marker) before its first write",
    durable_commits_before >= 2,
    f"durable commits before first write: {durable_commits_before}",
)
check(
    "dump_snapshot_valid is set true before the first write",
    start.find("id(dump_snapshot_valid) = true") != -1
    and first_write_offset is not None
    and start.find("id(dump_snapshot_valid) = true") < first_write_offset,
)

print("")
print("[10] Stop SOC validation: START refuses when the battery is already at or below the requested floor")
check(
    "start_dump_to_grid_override's precondition compares live battery SOC against the requested Stop SOC",
    "id(ecco_battery_soc).state > id(dump_stop_soc).state" in start,
)
check(
    "start_dump_to_grid_override's precondition requires the battery SOC sensor to have a plausible 0-100 value",
    "id(ecco_battery_soc).has_state()" in start
    and "id(ecco_battery_soc).state >= 0.0f" in start
    and "id(ecco_battery_soc).state <= 100.0f" in start,
)

print("")
print("[11] Stop SOC is never written to the inverter and never appears in the durable snapshot struct")
check(
    "no script assigns dump_stop_soc/dump_target_stop_soc to any Modbus write value expression",
    all("dump_target_stop_soc" not in (op.value_expr or "") and "dump_stop_soc" not in (op.value_expr or "") for op in by_name["start_dump_to_grid_override"].writes + by_name["restore_dump_to_grid_snapshot"].writes),
)
m = re.search(r"struct DumpToGridSnapshotData\s*\{(.*?)\};", DURABLE_HEADER, re.S)
check("DumpToGridSnapshotData struct is found in the durable header", m is not None)
if m:
    struct_body = m.group(1)
    check("DumpToGridSnapshotData has no stop_soc field", "stop_soc" not in struct_body.lower())
    for field in ("end_epoch", "active_persisted", "restore_requested", "reg244", "reg256", "reg257", "reg258", "reg259", "reg260", "reg261", "reg_dump_power_intended", "reg_dump_power_pending"):
        check(f"DumpToGridSnapshotData has a '{field}' field", field in struct_body)

print("")
print("[12] Durable tags are distinct from every Free Power / register 244 tag (no accidental key collision)")
tag_literals = re.findall(r'constexpr const char \*\w+_TAG\w*\s*=\s*"([^"]+)"', DURABLE_HEADER)
check("at least 8 durable tag string literals are declared", len(tag_literals) >= 8, f"found {len(tag_literals)}")
check("every durable tag string literal is unique", len(tag_literals) == len(set(tag_literals)), f"{tag_literals}")
check(
    "the Dump-to-Grid data/valid/retry tags are all present and distinct (Dump V2: data tag bumped to _v2, "
    "_v1 kept as a retired historical literal, the alias points at V2)",
    "ecco_dump_to_grid_snapshot_data_v2" in tag_literals
    and "ecco_dump_to_grid_snapshot_data_v1" in tag_literals
    and "constexpr const char *DUMP_TO_GRID_DATA_TAG = DUMP_TO_GRID_DATA_TAG_V2;" in DURABLE_HEADER
    and "ecco_dump_to_grid_snapshot_valid_v1" in tag_literals
    and "ecco_dump_to_grid_retry_state_v1" in tag_literals,
)

print("")
print("[13] Bidirectional mutual exclusion with Free Power is present in the firmware source")
check(
    "start_dump_to_grid_override refuses while Free Power is active, snapshotted, or mid-operation",
    "id(free_power_active_persisted)" in start and "id(free_power_snapshot_valid)" in start and "id(free_power_operation_in_progress)" in start,
)
check(
    "start_free_power_override refuses while Dump-to-Grid is active or snapshotted (reciprocal check)",
    "id(dump_active_persisted)" in scripts.get("start_free_power_override", "")
    and "id(dump_snapshot_valid)" in scripts.get("start_free_power_override", ""),
)

print("")
print("[14] Bidirectional mutual exclusion with the register 244 standalone proof harness")
check(
    "start_dump_to_grid_override refuses while a reg244 snapshot/apply is outstanding",
    "id(reg244_snapshot_valid)" in start and "id(reg244_apply_in_progress)" in start,
)
check(
    "apply_reg244_settings refuses while Dump-to-Grid is active or snapshotted (reciprocal check)",
    "id(dump_active_persisted)" in scripts.get("apply_reg244_settings", "")
    and "id(dump_snapshot_valid)" in scripts.get("apply_reg244_settings", ""),
)
check(
    "restore_reg244_snapshot refuses while Dump-to-Grid is active or snapshotted (reciprocal check)",
    "id(dump_active_persisted)" in scripts.get("restore_reg244_snapshot", "")
    and "id(dump_snapshot_valid)" in scripts.get("restore_reg244_snapshot", ""),
)

print("")
print("[15] Manual TOU slot writers (which also own 256-261) refuse while Dump-to-Grid is active or snapshotted")
for n in range(1, 7):
    button_name = f"apply_manual_slot{n}_button"
    body = buttons.get(button_name, "")
    check(
        f"{button_name}: guard includes dump_active_persisted and dump_snapshot_valid",
        "id(dump_active_persisted)" in body and "id(dump_snapshot_valid)" in body,
        f"button body not found or missing checks (found={button_name in buttons})",
    )

print("")
print("[16] Manual END, timeout END, Stop-SOC END and telemetry-loss END all converge on request_dump_end")
check(
    "the manual End button calls request_dump_end (not restore_dump_to_grid_snapshot directly)",
    "id: end_dump_to_grid_button" in FIRMWARE_TEXT
    and re.search(r"end_dump_to_grid_button.*?id:\s*request_dump_end", FIRMWARE_TEXT, re.S) is not None,
)
watchdog_section_match = re.search(r"# Dump-to-Grid V1 watchdog.*?(?=\n  - interval: 60s)", FIRMWARE_TEXT, re.S)
check("the Dump-to-Grid watchdog interval block is found", watchdog_section_match is not None)
if watchdog_section_match:
    watchdog_body = watchdog_section_match.group(0)
    check(
        "the duration-expiry/restore-due trigger calls request_dump_end",
        watchdog_body.count("id: request_dump_end") >= 1,
    )
    check(
        "the Stop SOC trigger calls request_dump_end with reason 'STOP SOC REACHED'",
        '"STOP SOC REACHED"' in watchdog_body,
    )
    check(
        "the telemetry-loss trigger calls request_dump_end with reason 'TELEMETRY LOST - failing closed'",
        '"TELEMETRY LOST - failing closed"' in watchdog_body,
    )
    check(
        "the Stop SOC / telemetry monitor is gated on dump_active_persisted (only meaningful while ACTIVE)",
        "id(dump_active_persisted) && !id(dump_restore_requested)" in watchdog_body,
    )
check(
    "request_dump_end always delegates to restore_dump_to_grid_snapshot - the single shared restore worker",
    "- script.execute: restore_dump_to_grid_snapshot" in request_end,
)

print("")
print("[17] restore_dump_to_grid_snapshot never clears dump_snapshot_valid before a verified restore")
false_count = len(re.findall(r"id\(dump_snapshot_valid\)\s*=\s*false", FIRMWARE_TEXT))
check(
    "dump_snapshot_valid is only ever cleared in exactly four places - on_boot loading an already-CLEAR "
    "durable marker, the verified-restore success branch, the zero-I/O PENDING_CLEAR clear-only step "
    "(2026-09-26 review fix), and Accept Current State's zero-write clear",
    false_count == 4,
    f"found {false_count} occurrences",
)
check(
    "the restore-path clear happens inside restore_dump_to_grid_snapshot's own verified-success branch, "
    "not anywhere else in that script",
    restore.count("id(dump_snapshot_valid) = false") == 1,
)

print("")
print("[18] Reboot fail-closed behaviour: an ACTIVE lease at last shutdown ends rather than resuming Stop SOC enforcement blind")
check(
    "on_boot forces dump_restore_requested true when the loaded record shows active_persisted",
    "if (id(dump_active_persisted)) {" in FIRMWARE_TEXT
    and "id(dump_restore_requested) = true;" in FIRMWARE_TEXT,
)

print("")
print("[19] Comms backoff pacing is applied to the Dump-to-Grid restore worker, same table as Free Power/register 244")
check(
    "restore_dump_to_grid_snapshot's precondition checks the backoff timer with WRAP-SAFE unsigned "
    "millis() arithmetic (2026-09-26 review fix - a plain `millis() >= next` compare could block every "
    "restore for ~49.7 days across the 32-bit millis() rollover)",
    "(int32_t) (millis() - id(dump_restore_next_attempt_ms)) >= 0" in restore
    and "millis() >= id(dump_restore_next_attempt_ms)" not in restore,
)
check(
    "a failed COMMS restore attempt schedules the next attempt via ecco_durable::comms_backoff_ms",
    "ecco_durable::comms_backoff_ms(id(dump_comms_restore_attempts))" in restore,
)
# 2026-09-26 independent review: the lockout is cause-aware, exactly like
# restore_free_power_snapshot_dispatch - only a second VERIFY MISMATCH
# locks out; COMMS failures only back off and keep retrying (restore is the
# safe direction, and a lockout would stop the timed end / Stop SOC restore
# while export may still be enabled).
failure_branch = restore[restore.find("if (id(dump_restore_mismatch_this_attempt)) {"):]
mismatch_branch, _, comms_branch = failure_branch.partition("} else {\n                        id(dump_comms_restore_attempts)++;")
check(
    "the restore failure branch splits on dump_restore_mismatch_this_attempt",
    bool(failure_branch) and bool(comms_branch),
)
check(
    "only the verify-MISMATCH branch can durably set the operator-needed lockout (after a second mismatch)",
    "id(dump_verify_mismatch_count) >= 2" in mismatch_branch and "retry.operator_needed = 1;" in mismatch_branch,
)
check(
    "the COMMS-failure branch never sets the operator-needed lockout",
    "operator_needed = 1" not in comms_branch and "id(dump_operator_needed) = true" not in comms_branch,
)
check(
    "the lockout is NOT keyed on the comms-attempt counter any more",
    "id(dump_comms_restore_attempts) >= 2" not in FIRMWARE_TEXT,
)
check(
    "both restore verify handlers flag a mismatch (244 and 256-261), and the flag is reset per attempt",
    restore.count("id(dump_restore_mismatch_this_attempt) = true;") == 2
    and "id(dump_restore_mismatch_this_attempt) = false;" in restore,
)

print("")
print("[20] Bus quiescence gate is present on both the start and restore preconditions")
for name, body in (("start_dump_to_grid_override", start), ("restore_dump_to_grid_snapshot", restore)):
    check(
        f"{name}: refuses while the Modbus bus is not quiescent",
        "id(inverter_modbus)->tx_buffer_empty()" in body and "id(inverter_modbus)->tx_blocked()" in body,
    )

print("")
print("[21] 2026-09-26 review fix: RESTORE_VERIFIED_PENDING_CLEAR has a zero-I/O clear-only completion path")
# Before this fix restore_dump_to_grid_snapshot only accepted
# RESTORE_REQUIRED, so a PENDING_CLEAR marker (power lost / CLEAR commit
# failed after a verified restore) was a permanent dead end that also
# blocked Free Power, register 244 and manual TOU writes.
from _free_power_action_sim import READ, WRITE, flatten, load_scripts  # noqa: E402

_, SCRIPT_TREES = load_scripts(DEFAULT_FIRMWARE)
clear_only = script_body("dump_clear_verified_marker")
check("dump_clear_verified_marker exists", bool(clear_only))
check("dump_clear_verified_marker issues no modbus_client call of any kind", "modbus_client." not in clear_only)
check(
    "dump_clear_verified_marker only acts on a PENDING_CLEAR marker and commits MARKER_CLEAR",
    "id(dump_marker_state) != ecco_durable::MARKER_RESTORE_VERIFIED_PENDING_CLEAR" in clear_only
    and "ecco_durable::MARKER_CLEAR" in clear_only
    and "ecco_durable::DUMP_TO_GRID_VALID_TAG" in clear_only,
)
end_tree = SCRIPT_TREES["request_dump_end"]["then"]
end_if = [a["if"] for a in end_tree if isinstance(a, dict) and "if" in a]
check(
    "request_dump_end routes PENDING_CLEAR to the clear-only script and everything else to the restore worker",
    len(end_if) == 1
    and "MARKER_RESTORE_VERIFIED_PENDING_CLEAR" in end_if[0]["condition"]["lambda"]
    and end_if[0]["then"] == [{"script.execute": "dump_clear_verified_marker"}]
    and end_if[0]["else"] == [{"script.execute": "restore_dump_to_grid_snapshot"}],
)

print("")
print("[22] 2026-09-26 review fix: the Force Restore bypass is consumed before the restore gate, every invocation")
restore_tree = SCRIPT_TREES["restore_dump_to_grid_snapshot"]["then"]
first = restore_tree[0] if restore_tree else {}
check(
    "the FIRST action of restore_dump_to_grid_snapshot copies the bypass into a per-call flag and clears it",
    isinstance(first, dict)
    and "lambda" in first
    and "id(dump_force_restore_this_call) = id(dump_force_restore_bypass);" in first["lambda"]
    and "id(dump_force_restore_bypass) = false;" in first["lambda"],
)
gate = restore_tree[1]["if"]["condition"]["lambda"] if len(restore_tree) > 1 and "if" in restore_tree[1] else ""
check(
    "the restore gate reads only the per-call flag, never the raw bypass",
    "id(dump_force_restore_this_call)" in gate and "dump_force_restore_bypass" not in gate,
)

print("")
print("[23] Restore ordering on the PARSED action tree: 244 write -> 244 verify read -> 256-261 write -> verify read")
restore_flat = flatten(restore_tree)
ops = [(i, kind, body.get("start_address"), gates) for i, (kind, gates, body) in enumerate(restore_flat) if kind in (READ, WRITE)]
seq = [(kind == WRITE and "W" or "R", addr) for _, kind, addr, _ in ops]
check(
    "restore issues exactly W244, R244, W256, R256 in that order",
    seq == [("W", 244), ("R", 244), ("W", 256), ("R", 256)],
    f"{seq}",
)
if len(ops) == 4:
    w256_gates = [c for c, branch in ops[2][3] if branch == "then"]
    check(
        "the 256-261 restore write is gated on !dump_write_failed (i.e. only after 244 was written AND verified)",
        "return !id(dump_write_failed);" in w256_gates,
        f"{w256_gates}",
    )
    r244_body = restore_flat[ops[1][0]][2]
    r244_handler = r244_body["on_response"]["then"][0]["lambda"]
    check(
        "the 244 verify read's on_response fails the attempt when live 244 != the snapshot value",
        "raw != id(dump_snapshot_reg244)" in r244_handler and "id(dump_write_failed) = true;" in r244_handler,
    )

print("")
print("[24] Activation ordering on the PARSED action tree: Allow Export only after the ceiling is positively re-read")
start_flat = flatten(SCRIPT_TREES["start_dump_to_grid_override"]["then"])
sops = [(kind == WRITE and "W" or "R", body.get("start_address"), gates) for kind, gates, body in start_flat if kind in (READ, WRITE)]
check(
    "start issues exactly R244, R256, R172 (V1.2 feed-forward telemetry), W256, R256, W244, R244 in that order",
    [(k, a) for k, a, _ in sops] == [("R", 244), ("R", 256), ("R", 172), ("W", 256), ("R", 256), ("W", 244), ("R", 244)],
    f"{[(k, a) for k, a, _ in sops]}",
)
if len(sops) == 7:
    w244_gates = [c for c, branch in sops[5][2] if branch == "then"]
    check(
        "the Allow Export (244) write is gated on the POSITIVE 256-261 readback flag, not just an FC16 ack",
        any("id(dump_verify_256_261_ok)" in c and "!id(dump_write_failed)" in c for c in w244_gates),
        f"{w244_gates}",
    )
check(
    "2026-09-26 review fix: START refuses (zero writes) when the ORIGINAL 244 reads outside 0/1/2",
    "if (values[0] > 2) {" in start,
)

print("")
print("[25] 2026-09-26 review fix: a new lease resets the durable retry/lockout record BEFORE its snapshot and first write")
retry_off = start.find("ecco_durable::key_for(ecco_durable::DUMP_TO_GRID_RETRY_TAG), clean_retry)")
data_off = start.find("ecco_durable::key_for(ecco_durable::DUMP_TO_GRID_DATA_TAG), data)")
marker_off = start.find("ecco_durable::key_for(ecco_durable::DUMP_TO_GRID_VALID_TAG), marker)")
check(
    "retry-record reset commit precedes the data commit, which precedes the marker commit, which precedes the first write",
    -1 not in (retry_off, data_off, marker_off)
    and first_write_offset is not None
    and retry_off < data_off < marker_off < first_write_offset,
    f"retry={retry_off} data={data_off} marker={marker_off} first_write={first_write_offset}",
)
check(
    "the data commit is conditional on the retry reset having committed (Dump V2: via the V1 rollback "
    "tombstone commit, itself conditional on the retry reset)",
    "bool tombstone_committed = retry_reset_committed && ecco_durable::commit_record(" in start
    and "bool data_committed = tombstone_committed && ecco_durable::commit_record(" in start,
)
check(
    "on_boot treats a loadable Dump record whose original 244 is outside 0/1/2 as untrusted (fail closed), "
    "never as a restorable snapshot",
    re.search(
        r"load_record\(ecco_durable::key_for\(ecco_durable::DUMP_TO_GRID_DATA_TAG\), data\) &&\s*\n\s*data\.reg244 <= 2\)",
        FIRMWARE_TEXT,
    ) is not None,
)
check(
    "on_boot only honours a durable operator_needed while a recovery obligation actually exists",
    "id(dump_operator_needed) = have_retry && retry.operator_needed != 0 && id(dump_snapshot_valid);" in FIRMWARE_TEXT,
)

print("")
print("[26] 2026-09-26 review fix: Stop SOC fails closed on STALE or NaN telemetry, not only on a missing value")
check(
    "ecco_battery_soc records a freshness timestamp on every publish (on_value, RAM only)",
    re.search(r"id: ecco_battery_soc\n(?:    .*\n)*?    on_value:\n      then:\n        - lambda: 'id\(dump_soc_last_update_ms\) = millis\(\);'", FIRMWARE_TEXT) is not None,
)
check(
    "START requires a fresh SOC sample",
    "id(dump_soc_last_update_ms) != 0 &&" in start
    and "(uint32_t) (millis() - id(dump_soc_last_update_ms)) <= ${ecco_dump_soc_stale_ms}UL" in start,
)
if watchdog_section_match:
    check(
        "the ACTIVE telemetry monitor ends the lease on stale OR implausible (incl. NaN) SOC",
        "bool soc_fresh" in watchdog_body
        and "return !soc_plausible || !soc_fresh || !id(configuration_online).state;" in watchdog_body
        and "id(ecco_battery_soc).state < 0.0f || id(ecco_battery_soc).state > 100.0f" not in watchdog_body,
    )

print("")
print("[27] 2026-09-26 pre-live hardening: configuration readback freshness markers (RAM-only, no new Modbus I/O)")
poll_dispatch = script_body("poll_inverter_configuration_dispatch")
seq_off = poll_dispatch.find("id(cfg_block_b_seq)++;")
cache_off = poll_dispatch.find("id(manual_cfg_reg261_raw) = values[20];")
check("config block 241-293's response increments cfg_block_b_seq and stamps cfg_block_b_ok_ms",
      seq_off != -1 and "id(cfg_block_b_ok_ms) = millis();" in poll_dispatch)
check("...AFTER the 244/256-261 raw cache has been refreshed from that same response",
      cache_off != -1 and seq_off > cache_off and poll_dispatch.find("id(manual_cfg_reg244_raw) = values[3];") < seq_off)
check("the configuration poll gained no Modbus operation (still exactly three block reads)",
      poll_dispatch.count("modbus_client.read_holding_registers") == 3 and "write_multiple_registers" not in poll_dispatch)
check("the ACTIVE commit records the lease-start readback sequence and time",
      "id(dump_active_cfg_seq) = id(cfg_block_b_seq);" in start and "id(dump_active_since_ms) = millis();" in start)
for name, body in (("start_dump_to_grid_override", start), ("restore_dump_to_grid_snapshot", restore)):
    check(f"{name} records dump_last_op_cfg_seq when its bus operation finishes",
          "- lambda: 'id(dump_last_op_cfg_seq) = id(cfg_block_b_seq);'" in body)

print("")
print("[27b] 2026-09-27 adversarial review (R4/R1): structural coverage for the B1 dispatch-generation fence and")
print("      M2's own completion flag - the behavioural simulator cannot execute poll_inverter_configuration_dispatch")
print("      itself (its Block A response uses a switch statement the simulator's transpiler does not support), so")
print("      these safety-load-bearing lines are pinned directly against the firmware SOURCE instead: deleting or")
print("      renaming any of them fails these checks immediately, without needing to re-run a mutant scenario.")
dispatch_stamp_off = poll_dispatch.find("id(cfg_block_b_dispatch_seq)++;")
block_b_read_off = poll_dispatch.find("start_address: 241")
delay_off = poll_dispatch.find("delay: 2500ms")
check("BLOCKER B1: poll_inverter_configuration_dispatch stamps cfg_block_b_dispatch_seq immediately before "
      "Block B's read is sent - never on completion (see cfg_block_b_dispatch_seq's own comment for why this, "
      "not the completion counter alone, is what proves a sample was DISPATCHED after a given fence)",
      dispatch_stamp_off != -1 and delay_off != -1 and block_b_read_off != -1
      and delay_off < dispatch_stamp_off < block_b_read_off,
      f"delay_off={delay_off} dispatch_stamp_off={dispatch_stamp_off} block_b_read_off={block_b_read_off}")
response_stamp_off = poll_dispatch.find("id(cfg_block_b_response_dispatch_seq) = id(cfg_block_b_dispatch_seq);")
check("BLOCKER B1: Block B's own on_response records WHICH dispatch generation produced the values it just "
      "cached, alongside (and after) the existing cfg_block_b_seq/cfg_block_b_ok_ms freshness stamps",
      response_stamp_off != -1 and seq_off != -1 and response_stamp_off > seq_off)

watchdog_drift_fence = "if (id(cfg_block_b_response_dispatch_seq) <= id(dump_controller_cfg_fence_seq)) return false;"
controller = script_body("dump_controller_tick")
check("BLOCKER B1: the ACTIVE-lease drift check additionally requires 256-261 evidence to postdate the "
      "controller's own dispatch fence (dump_controller_cfg_fence_seq), on top of the ACTIVE fence/staleness "
      "checks that alone were proven insufficient",
      watchdog_section_match and watchdog_drift_fence in watchdog_body)
check("BLOCKER B1: the controller updates its own dispatch fence from cfg_block_b_dispatch_seq (never from the "
      "completion counter cfg_block_b_seq) immediately after each verified write",
      "id(dump_controller_cfg_fence_seq) = id(cfg_block_b_dispatch_seq);" in controller)
check("BLOCKER B1: the ACTIVE commit also seeds the controller's dispatch fence, so the very first post-ACTIVE "
      "poll (before any controller write) is judged consistently",
      "id(dump_controller_cfg_fence_seq) = id(cfg_block_b_dispatch_seq);" in start)

check("M2: the controller's write and verify-reread use their OWN completion flag "
      "(dump_controller_op_terminal) - the shared dump_op_terminal name does not appear anywhere in this "
      "script, so a future edit cannot silently reintroduce the race between the controller and START/restore",
      "dump_controller_op_terminal" in controller and "id(dump_op_terminal)" not in controller
      and "return id(dump_op_terminal)" not in controller)

print("")
print("[28] 2026-09-26 pre-live hardening: ACTIVE monitors end the lease only through request_dump_end")
if watchdog_section_match:
    for reason_fragment in ('"CONFIG READBACK STALE - failing closed"', 'std::string("CONFIG DRIFT - ")', '"POWER RUNAWAY - battery discharge'):
        check(f"watchdog routes {reason_fragment} through request_dump_end", reason_fragment in watchdog_body)
    check("drift check only trusts a sample NEWER than the ACTIVE commit and no older than the stale bound",
          "if (id(cfg_block_b_seq) <= id(dump_active_cfg_seq)) return false;" in watchdog_body
          and "if ((uint32_t) (millis() - id(cfg_block_b_ok_ms)) > ${ecco_dump_cfg_stale_ms}UL) return false;" in watchdog_body)
    check("the watchdog issues no Modbus operation of its own", "modbus_client." not in watchdog_body)
    check("the runaway trigger compares the consecutive-sample counter with the configured sample count",
          "id(dump_overpower_samples) >= ${ecco_dump_runaway_samples}" in watchdog_body)
    check("2026-09-26 adversarial review (H1): the runaway trigger ALSO checks the independent absolute backstop counter",
          "id(dump_absolute_overpower_samples) >= ${ecco_dump_runaway_absolute_samples}" in watchdog_body)
batt = re.search(r"id: ecco_battery_power\n(?:    .*\n|\n)*?    on_value:\n((?:      .*\n|\n)*)", FIRMWARE_TEXT)
check("ecco_battery_power's on_value maintains the runaway counter (RAM only, no Modbus I/O)",
      batt is not None and "id(dump_overpower_samples)++;" in batt.group(1) and "modbus_client" not in batt.group(1))
check("runaway threshold is requested + max(requested/2, margin) on battery DISCHARGE (x > ...), never grid export",
      batt is not None and "float margin = requested / 2.0f;" in batt.group(1)
      and "x > requested + margin" in batt.group(1) and "grid" not in batt.group(1).split("on_value")[-1].lower().replace("grid export", ""))

print("")
print("[29] 2026-09-26 pre-live hardening: Accept residue gate, TOU slot gate, latched-value entities")
accept_tree = SCRIPT_TREES["dump_accept_current_state"]["then"]
check("Accept's FIRST action is the zero-I/O residue evaluation",
      isinstance(accept_tree[0], dict) and "lambda" in accept_tree[0] and "dump_accept_block_reason" in accept_tree[0]["lambda"])
check("Accept's gate requires the residue evaluation to have passed",
      "id(dump_accept_block_reason).empty()" in accept_tree[1]["if"]["condition"]["lambda"])
check("Accept trusts only a post-operation readback within the evidence bound",
      "id(cfg_block_b_seq) <= id(dump_last_op_cfg_seq)" in accept_current
      and "${ecco_dump_accept_evidence_ms}UL" in accept_current)
start_tree = SCRIPT_TREES["start_dump_to_grid_override"]["then"]
check("START's FIRST action is the zero-I/O TOU slot conflict computation",
      "lambda" in start_tree[0] and "id(dump_start_tou_conflict_slot) = conflict;" in start_tree[0]["lambda"]
      and "modbus_client" not in start_tree[0]["lambda"])
check("START's gate requires no slot conflict, config polling on and a fresh readback",
      all(t in start_tree[1]["if"]["condition"]["lambda"] for t in (
          "id(dump_start_tou_conflict_slot) == 0", "id(configuration_polling).state",
          "(uint32_t) (millis() - id(cfg_block_b_ok_ms)) <= ${ecco_dump_cfg_stale_ms}UL")))
check("slot check reads only the cached 250-255 times and 274-279 charge-source bits (never 268-273 or any write)",
      "(flags[i] & 0x0003) != 0" in start_tree[0]["lambda"] and "reg268" not in start_tree[0]["lambda"])
for entity in ("Dump to Grid Active Export Power", "Dump to Grid Active Stop SOC", "Dump to Grid Last End Reason"):
    check(f'"{entity}" entity exists', f'name: "{entity}"' in FIRMWARE_TEXT)

print("")
print("[30] Deployment manifest installs the Dump schedule package")
manifest_text = (ROOT / "deployment" / "ha-manifest.yaml").read_text(encoding="utf-8")
check("deployment/ha-manifest.yaml lists home-assistant/packages/ecco_dump_to_grid_schedule.yaml",
      "source: home-assistant/packages/ecco_dump_to_grid_schedule.yaml" in manifest_text)

print("")
print("[31] 2026-09-26 recorder/idle-state hardening: on_boot publishes an explicit Dump to Grid Recovery State")
boot_marker_start = FIRMWARE_TEXT.find("// 2026-09-26 (recorder/idle-state hardening): mirror the DURABLE")
_boot_end_marker = 'id(dump_recovery_state).publish_state("NONE");\n          }'
_boot_end_marker_off = FIRMWARE_TEXT.find(_boot_end_marker, boot_marker_start)
boot_recovery_block_end = _boot_end_marker_off + len(_boot_end_marker) if _boot_end_marker_off != -1 else -1
boot_recovery_block = (
    FIRMWARE_TEXT[boot_marker_start:boot_recovery_block_end] if boot_marker_start != -1 and boot_recovery_block_end != -1 else ""
)
operator_needed_assignment_off = FIRMWARE_TEXT.find(
    "id(dump_operator_needed) = have_retry && retry.operator_needed != 0 && id(dump_snapshot_valid);"
)
check(
    "the boot mirror exists and runs strictly AFTER the durable operator-needed/snapshot-valid computation "
    "(boot recovery logic wins over the cosmetic publish, never the reverse)",
    boot_marker_start != -1
    and operator_needed_assignment_off != -1
    and operator_needed_assignment_off < boot_marker_start,
    f"operator_needed_off={operator_needed_assignment_off} boot_marker_off={boot_marker_start}",
)
check(
    "the mirror covers all four already-computed obligation states (corrupt / operator-needed / pending-restore / none)",
    all(
        s in boot_recovery_block
        for s in (
            'id(dump_recovery_state).publish_state("LOCKED - durable recovery metadata unavailable");',
            'id(dump_recovery_state).publish_state("LOCKED - operator decision required");',
            'id(dump_recovery_state).publish_state("PENDING - outstanding snapshot found at boot; automatic restore expected");',
            'id(dump_recovery_state).publish_state("NONE");',
        )
    ),
)
check(
    "the healthy-idle NONE case is gated behind the SAME three conditions dump_status already uses just above - "
    "it can never be published while dump_recovery_metadata_corrupt, dump_operator_needed or dump_snapshot_valid holds",
    re.search(
        r"if \(id\(dump_recovery_metadata_corrupt\)\) \{\s*\n"
        r"\s*id\(dump_recovery_state\)\.publish_state\(\"LOCKED - durable recovery metadata unavailable\"\);\s*\n"
        r"\s*\} else if \(id\(dump_operator_needed\)\) \{\s*\n"
        r"\s*id\(dump_recovery_state\)\.publish_state\(\"LOCKED - operator decision required\"\);\s*\n"
        r"\s*\} else if \(id\(dump_snapshot_valid\)\) \{\s*\n"
        r"\s*id\(dump_recovery_state\)\.publish_state\(\"PENDING - outstanding snapshot found at boot; automatic restore expected\"\);\s*\n"
        r"\s*\} else \{\s*\n"
        r"\s*id\(dump_recovery_state\)\.publish_state\(\"NONE\"\);\s*\n"
        r"\s*\}",
        FIRMWARE_TEXT,
    )
    is not None,
)
check(
    "the boot mirror performs zero Modbus I/O and touches no durable-marker/write-surface API - it is a pure "
    "publish_state mirror of already-computed RAM booleans",
    boot_recovery_block != ""
    and "modbus_client" not in boot_recovery_block
    and "commit_record" not in boot_recovery_block
    and "load_record" not in boot_recovery_block,
)
check(
    '"Dump to Grid Recovery State" template sensor still has update_interval: never (only ever published by explicit '
    "code, never polled) - the boot mirror is additive, not a change to the sensor's own update model",
    re.search(r'name: "Dump to Grid Recovery State"\n\s*id: dump_recovery_state\n\s*update_interval: never', FIRMWARE_TEXT)
    is not None,
)

print("")
if FAILURES:
    print(f"{len(FAILURES)} check(s) FAILED:")
    for name in FAILURES:
        print(f"  - {name}")
else:
    print("All Manual Dump-to-Grid V1 offline tests PASSED.")

print("")
print("These are STRUCTURAL/source-text facts about the firmware source file. They prove the")
print("source matches docs/DUMP_TO_GRID_V1.md's design - they do NOT prove the compiled firmware")
print("behaves this way against real hardware. No live Dump-to-Grid event, OTA, or inverter write")
print("has been performed as part of this feature.")

if FAILURES:
    sys.exit(1)
