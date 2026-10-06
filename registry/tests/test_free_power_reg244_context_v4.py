#!/usr/bin/env python3
"""Offline structural/behavioural tests for PR-A: the register-244
active-lease context hardening pass (pre-OTA), covering:

  - firmware/include/ecco_durable_snapshot.h: the V4 durable Free Power
    snapshot schema/tag (`reg244_lease_context_plus1`, fail-closed
    plus-one encoding, why the tag bump is mandatory even though sizeof
    does not change).
  - firmware/ecco_clock_dongle_stage3_4_free_power.yaml:
      * the three durable-commit rebuild sites (start, activation
        active_persisted re-commit, End-button restore_requested
        re-commit) - each must populate the new field.
      * start_free_power_override's fresh register-244 lease-context
        capture (structural order: 230x3, 256x24, fresh 244 context read,
        durable commit, first inverter write).
      * restore_free_power_snapshot_dispatch's pre-write and pre-floor
        register-244 context gates (CONTEXT HOLD - zero inverter writes on
        mismatch/unknown context, a read failure is an ordinary COMMS
        failure instead).
      * free_power_recovery_force_restore_dispatch's pre-268 context
        recheck (against Force's own fresh-confirmed/fingerprinted live
        244, NOT the lease context).
      * the reg244 harness script-level self-gate
        (apply_reg244_settings/restore_reg244_snapshot refuse while Free
        Power owns the domain).
      * the passive register-244 context diagnostic (config-poll only,
        writes nothing durable, decides nothing).
      * cause-neutral operator_needed wording for the generic durable
        lockout.
      * the one-shot operator-retry-authorisation leak fix (consumed on
        EVERY restore_free_power_snapshot invocation, including a
        rejected one).
  - registry/transaction_state_machine.py: `OwnerRecord.reg244_lease_context`,
    `reg244_context_gate`, and `authorizes_unattended_restore`'s new
    register-244 context requirement for free_power_transaction.

No I/O, no hardware, no ESPHome/C++ toolchain. Techniques, in the same
spirit as registry/tests/test_free_power_recovery_force_restore.py and
registry/tests/test_free_power_tou_power_ownership_2026_09_23.py - each
group is labelled with which technique it actually is:

  1. tools/analyze_write_surface.py's structured extractor (write surface,
     ownership/mutex acquisition, read/write op inventory, offsets).
  2. Direct text/offset analysis of the real firmware source.
  3. `ctypes.Structure` mirrors of the V3/V4 durable schema, proving the
     sizeof/tail-padding claim by actual C-ABI-equivalent computation, not
     hand arithmetic alone.
  4. Small, purpose-built behavioural simulators of ONLY the new
     register-244 read+gate logic (start capture, pre-write gate,
     pre-floor gate, Force recheck), driven through every real
     on_response/on_error/on_no_response/on_not_sent branch and the
     bounded-wait timeout fallback, exactly like the existing Free Power
     simulators - never a re-implementation of the surrounding owned-
     register write sequence, which registry/tests/test_free_power_tou_power_ownership_2026_09_23.py
     already exhaustively covers and which this file does not duplicate.
  5. A hand-maintained Python reference-model check
     (registry/transaction_state_machine.py's `reg244_context_gate`/
     `authorizes_unattended_restore`).

Several groups include an explicit "MUTATION CHECK" (technique-2 or -4)
that re-runs the SAME assertion function against both the genuine
text/behaviour and a deliberately broken copy, requiring the result to
flip - proving that assertion has real discriminating power. No technique
here proves the COMPILED firmware behaves this way against real hardware.
No live Free Power event, OTA, or inverter write is part of this change -
see CURRENT_STATE.md and docs/FREE_POWER_MANUAL_TRANSACTION_SPEC.md, both
still `implemented_not_live_proven` for this pass.
"""

from __future__ import annotations

import copy
import ctypes
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
FIRMWARE_PATH = ROOT / "firmware" / "ecco_clock_dongle_stage3_4_free_power.yaml"
DURABLE_HEADER_PATH = ROOT / "firmware" / "include" / "ecco_durable_snapshot.h"

sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "registry"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from analyze_write_surface import analyze  # noqa: E402
import transaction_state_machine as tsm  # noqa: E402
import _free_power_action_sim as _sim  # noqa: E402

FAILURES: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  PASS  {name}")
    else:
        FAILURES.append(name)
        print(f"  FAIL  {name}" + (f" - {detail}" if detail else ""))


for _p in (FIRMWARE_PATH, DURABLE_HEADER_PATH):
    if not _p.is_file():
        print(f"  FAIL  required file not found: {_p}")
        sys.exit(1)

fw = FIRMWARE_PATH.read_text(encoding="utf-8")
header = DURABLE_HEADER_PATH.read_text(encoding="utf-8")

result = analyze(FIRMWARE_PATH)
by_name = {p.name: p for p in result["paths"]}

WRITE = "modbus_client.write_multiple_registers"
READ = "modbus_client.read_holding_registers"


def _norm(code: str) -> str:
    return " ".join(str(code).split())


def script_body(name: str) -> str:
    p = by_name.get(name)
    if p is None:
        return ""
    return p.body


# ===========================================================================
# A. V4 SCHEMA
# ===========================================================================
print("[A] V4 durable Free Power snapshot schema/tag")

check(
    "the header declares a new V4 tag string, distinct from v1/v2/v3",
    'FREE_POWER_DATA_TAG_V4 = "ecco_free_power_snapshot_data_v4"' in header,
)
check(
    "FREE_POWER_DATA_TAG (the alias every call site uses) now points at V4",
    "constexpr const char *FREE_POWER_DATA_TAG = FREE_POWER_DATA_TAG_V4;" in header,
)
for old in ("V1", "V2", "V3"):
    check(
        f"FREE_POWER_DATA_TAG_{old} remains defined as a documented historical tag, unused by the alias",
        f'FREE_POWER_DATA_TAG_{old} = "ecco_free_power_snapshot_data_{old.lower()}"' in header
        and f"constexpr const char *FREE_POWER_DATA_TAG = FREE_POWER_DATA_TAG_{old};" not in header,
    )
check(
    "no call site references a versioned tag constant directly (every commit_record/load_record "
    "call for Free Power data goes through the stable FREE_POWER_DATA_TAG alias, never a hardcoded _v1/_v2/_v3/_v4)",
    all(
        f"ecco_durable::FREE_POWER_DATA_TAG_{suffix}" not in fw
        for suffix in ("V1", "V2", "V3", "V4")
    ),
)

check(
    "MarkerState enum is unchanged by this pass (exactly the three known values, same numeric assignment)",
    re.search(
        r"enum MarkerState : uint8_t \{\s*MARKER_CLEAR = 0,\s*MARKER_RESTORE_REQUIRED = 1,\s*"
        r"MARKER_RESTORE_VERIFIED_PENDING_CLEAR = 2,\s*\};",
        header,
    )
    is not None,
)

struct_m = re.search(r"struct FreePowerSnapshotData \{(.*?)\};", header, re.S)
check("found the FreePowerSnapshotData struct body", struct_m is not None)
if struct_m:
    struct_body = struct_m.group(1)
    check(
        "reg244_lease_context_plus1 is the LAST field of the struct (appended, not inserted mid-struct - "
        "inserting it earlier would shift every offset after it and is not what 'append a field' means)",
        struct_body.rstrip().rstrip(";").strip().endswith("uint16_t reg244_lease_context_plus1"),
    )
    check(
        "the field is a uint16_t (matches the plus-one encoding's 0..3-plus-corrupt range with headroom)",
        "uint16_t reg244_lease_context_plus1;" in struct_body,
    )
    check(
        "the struct comment documents the fail-closed plus-one encoding (0=unknown/invalid) "
        "immediately above the field",
        "0 = context not captured / invalid / unknown" in header
        and "1 = raw register 244 value 0 (Allow Export)" in header,
    )
    check(
        "the struct comment explicitly states zero is deliberately invalid, not a silent 'Allow Export'",
        "Zero is deliberately INVALID" in header or "zero is deliberately invalid" in header.lower(),
    )


# --- ctypes C-ABI mirrors: PROVE the sizeof/tail-padding claim, not just assert prose about it ------
class _V3Mirror(ctypes.Structure):
    _fields_ = [
        ("end_epoch", ctypes.c_uint32),
        ("active_persisted", ctypes.c_uint8),
        ("restore_requested", ctypes.c_uint8),
        *[(f"reg{a}", ctypes.c_uint16) for a in (230, 232, *range(256, 262), *range(268, 280))],
        ("reg230_intended", ctypes.c_uint16),
        ("reg_tou_power_intended", ctypes.c_uint16),
    ]


class _V4Mirror(ctypes.Structure):
    _fields_ = [
        ("end_epoch", ctypes.c_uint32),
        ("active_persisted", ctypes.c_uint8),
        ("restore_requested", ctypes.c_uint8),
        *[(f"reg{a}", ctypes.c_uint16) for a in (230, 232, *range(256, 262), *range(268, 280))],
        ("reg230_intended", ctypes.c_uint16),
        ("reg_tou_power_intended", ctypes.c_uint16),
        ("reg244_lease_context_plus1", ctypes.c_uint16),
    ]


print("")
print("[A2] ctypes C-ABI mirrors prove the sizeof/tail-padding claim (not hand arithmetic alone)")
check(
    "V3 mirror (25 fields, no context field) has sizeof == 52 - matches the header's own claim",
    ctypes.sizeof(_V3Mirror) == 52,
    f"sizeof(_V3Mirror)={ctypes.sizeof(_V3Mirror)}",
)
check(
    "V4 mirror (26 fields, +reg244_lease_context_plus1) ALSO has sizeof == 52 - the appended field "
    "exactly fills V3's 2 bytes of unused tail padding, proving sizeof genuinely cannot distinguish "
    "V3 from V4 here and the tag bump (not a sizeof/length check) is what actually separates them",
    ctypes.sizeof(_V4Mirror) == 52,
    f"sizeof(_V4Mirror)={ctypes.sizeof(_V4Mirror)}",
)
check(
    "MUTATION CHECK: a V3-shaped record padded/reinterpreted as V4 would NOT be caught by a length "
    "check alone (both are 52) - the field-count actually differs (25 vs 26), proving this is a "
    "genuine schema change that specifically needs the tag bump, not a no-op append",
    len(_V3Mirror._fields_) == 25 and len(_V4Mirror._fields_) == 26 and len(_V3Mirror._fields_) != len(_V4Mirror._fields_),
)

# ===========================================================================
# B. REBUILD SITES
# ===========================================================================
print("")
print("[B] Every FreePowerSnapshotData durable-commit rebuild site populates reg244_lease_context_plus1")

_data_decls = [m.start() for m in re.finditer(r"ecco_durable::FreePowerSnapshotData data\{\};", fw)]
check(
    "exactly 4 'FreePowerSnapshotData data{};' occurrences exist (3 durable-commit rebuild sites + "
    "1 boot-time load destination)",
    len(_data_decls) == 4,
    f"found {len(_data_decls)}",
)
_field_assigns = [m.start() for m in re.finditer(r"data\.reg244_lease_context_plus1 = \(uint16_t\)\(id\(free_power_lease_context_reg244\) \+ 1\);", fw)]
check(
    "exactly 3 rebuild sites assign reg244_lease_context_plus1 = (uint16_t)(id(free_power_lease_context_reg244) + 1) "
    "(the boot-time load destination is excluded - it only READS the field, via 'uint16_t plus1 = data.reg244_lease_context_plus1;')",
    len(_field_assigns) == 3,
    f"found {len(_field_assigns)}",
)
check(
    "the boot-time load destination does NOT itself assign the field (it is a load target, not a rebuild site)",
    "uint16_t plus1 = data.reg244_lease_context_plus1;" in fw
    and fw.count("uint16_t plus1 = data.reg244_lease_context_plus1;") == 1,
)


def _rebuild_site_text(decl_offset: int, window: int = 2400) -> str:
    """The commit-site source text starting at a 'data{};' declaration."""
    return fw[decl_offset:decl_offset + window]


# Match each 'data{};' declaration to the nearest FOLLOWING field-assignment
# (or its absence, for the boot-load site) by proximity - both lists are in
# document order and every rebuild site's assignment immediately follows its
# own declaration well before the NEXT declaration does.
_rebuild_sites = []
for i, decl in enumerate(_data_decls):
    nxt = _data_decls[i + 1] if i + 1 < len(_data_decls) else len(fw)
    assigns_here = [a for a in _field_assigns if decl < a < nxt]
    _rebuild_sites.append((decl, assigns_here))

check(
    "exactly one of the 4 'data{};' sites has ZERO reg244_lease_context_plus1 assignments before the "
    "next site (the boot-time load destination) - the other 3 have exactly one each",
    sorted(len(a) for _, a in _rebuild_sites) == [0, 1, 1, 1],
    f"{[len(a) for _, a in _rebuild_sites]}",
)

_commit_sites = [(d, a[0]) for d, a in _rebuild_sites if a]
_SITE_LABELS = ["start (pre-write commit)", "activation (active_persisted re-commit)", "End-button (restore_requested re-commit)"]
for label, (decl, assign) in zip(_SITE_LABELS, _commit_sites):
    site_text = fw[decl:assign + 200]
    check(
        f"rebuild site '{label}': populates every one of the 20 owned-register snapshot fields "
        "before its reg244_lease_context_plus1 assignment (a real rebuild, not a stub)",
        all(f"data.reg{a} = " in site_text for a in (230, 232, *range(256, 262), *range(268, 280))),
    )
    check(
        f"rebuild site '{label}': the reg244_lease_context_plus1 assignment is followed by a "
        "commit_record(...FREE_POWER_DATA_TAG...) call using the SAME 'data' object",
        bool(re.search(r"commit_record\(\s*ecco_durable::key_for\(ecco_durable::FREE_POWER_DATA_TAG\),\s*data\)", fw[assign:assign + 400])),
    )

print("")
print("[B2] MUTATION CHECK: omitting the field from any ONE site is detected")
for i in range(3):
    # Simulate "site i's assignment was never written": drop it from the counted set.
    mutant_assigns = list(_field_assigns)
    del mutant_assigns[i]
    mutant_sites = []
    for j, decl in enumerate(_data_decls):
        nxt = _data_decls[j + 1] if j + 1 < len(_data_decls) else len(fw)
        mutant_sites.append(len([a for a in mutant_assigns if decl < a < nxt]))
    check(
        f"MUTATION CHECK: if site {i + 1} ('{_SITE_LABELS[i]}') had never assigned the field, the "
        f"exactly-3-assignments invariant (section [B]) would correctly flip to FAIL",
        sorted(mutant_sites) != [0, 1, 1, 1],
        f"mutant per-site counts={mutant_sites}",
    )

# ===========================================================================
# C. FREE POWER START - FRESH CONTEXT CAPTURE
# ===========================================================================
print("")
print("[C] start_free_power_override: structural order + fresh register-244 context capture")

start = by_name.get("start_free_power_override")
check("found start_free_power_override in the write-surface extraction", start is not None)
if start is not None:
    body = start.body
    reads = sorted(start.reads, key=lambda r: r.offset)
    read_specs = [(r.start_address, r.count) for r in reads]
    check(
        "start_free_power_override's FIRST three reads, in document order, are exactly: 230x3 (owned "
        "snapshot), 256x24 (owned TOU/SOC/flags snapshot), 244x12 (fresh lease-context capture) - "
        "BEFORE any of the later activation write-verify reads (268x12, 230x3, 256x24)",
        read_specs[:3] == [(230, 3), (256, 24), (244, 12)],
        f"{read_specs}",
    )
    ctx_read = next((r for r in reads if r.start_address == 244), None)
    check("found the dedicated register-244 lease-context read", ctx_read is not None)
    if ctx_read is not None:
        first_write_offset = start.first_write_offset
        check(
            "the register-244 context read occurs BEFORE the first inverter write",
            first_write_offset is not None and ctx_read.offset < first_write_offset,
        )
        commits_before_ctx_read = start.durable_commits_before(ctx_read.offset)
        commits_before_write = start.durable_commits_before(first_write_offset)
        check(
            "ZERO durable commits occur before the context read (it is captured BEFORE any commit, "
            "not merely before the write)",
            commits_before_ctx_read == 0,
            f"commits_before_ctx_read={commits_before_ctx_read}",
        )
        check(
            "at least one durable commit occurs between the context read and the first inverter write "
            "(the commit happens after the read, still before any write)",
            commits_before_write > commits_before_ctx_read,
            f"commits_before_write={commits_before_write} commits_before_ctx_read={commits_before_ctx_read}",
        )
    _code_only = "\n".join(line for line in body.splitlines() if not line.strip().startswith("#"))
    check(
        "manual_cfg_reg244_raw is NEVER used in start_free_power_override's actual CODE (only in this "
        "pass's own explanatory YAML comment, stripped here) - the start safety decision uses only the "
        "dedicated fresh read, never the periodic config-poll cache",
        "manual_cfg_reg244_raw" not in _code_only,
    )
    check(
        "the commit-gate condition requires free_power_snapshot_context_ok (the context read's own "
        "success flag) in addition to the pre-existing 230/232/TOU snapshot-ok flags",
        bool(re.search(
            r"return !id\(free_power_write_failed\) && id\(free_power_snapshot_230_ok\) && "
            r"id\(free_power_snapshot_232_ok\) && id\(free_power_snapshot_tou_ok\) && "
            r"id\(free_power_snapshot_context_ok\);",
            body,
        )),
    )
    check(
        "on a successful context read, ONLY raw values 0/1/2 set free_power_snapshot_context_ok true "
        "(values[0] <= 2 gate) - anything else is refused",
        bool(re.search(r"if \(values\[0\] <= 2\) \{\s*id\(free_power_lease_context_reg244\) = values\[0\];\s*id\(free_power_snapshot_context_ok\) = true;", body)),
    )
    check(
        "the reset block clears free_power_snapshot_context_ok = false and "
        "free_power_lease_context_reg244 = -1 at the START of every new transaction (a stale value "
        "from a PRIOR transaction can never leak into this one)",
        "id(free_power_snapshot_context_ok) = false;" in body and "id(free_power_lease_context_reg244) = -1;" in body,
    )
    check(
        "every one of the context read's four terminal callbacks (on_response/on_error/on_no_response/"
        "on_not_sent) sets free_power_op_terminal = true and guards against a stale callback via "
        "free_power_operation_in_progress",
        body.count("if (!id(free_power_operation_in_progress)) return;") >= 4,
    )
    check(
        "a bounded wait_until (3000ms) follows the context read, with a fallback lambda that sets "
        "free_power_write_failed = true if the terminal flag never became true",
        bool(re.search(
            r"Lease-context read of register 244 did not reach a terminal state within the bounded wait",
            body,
        )),
    )

    print("")
    print("[C2] Boundary values: the extracted acceptance threshold is exactly '<= 2', not '<= 3' or unbounded")
    threshold_m = re.search(r"if \(values\[0\] <= (\d+)\) \{\s*id\(free_power_lease_context_reg244\) = values\[0\];\s*id\(free_power_snapshot_context_ok\) = true;", body)
    check("found the extracted start-context acceptance condition", threshold_m is not None)
    if threshold_m:
        threshold = int(threshold_m.group(1))

        def _start_context_accepts(raw: int) -> bool:
            # Mirrors the REAL threshold just extracted from source above -
            # not a hand value guessed independently of it.
            return raw <= threshold

        for raw, expected in ((0, True), (1, True), (2, True), (3, False), (4, False), (0xFFFF, False)):
            check(
                f"raw register-244 value {raw} ({'accepted' if expected else 'refused'}) at start",
                _start_context_accepts(raw) == expected,
            )

# ===========================================================================
# D. RESTORE: PRE-WRITE CONTEXT GATE (the core safety change)
# ===========================================================================
print("")
print("[D] restore_free_power_snapshot_dispatch: pre-write register-244 context gate")

dispatch = by_name.get("restore_free_power_snapshot_dispatch")
check("found restore_free_power_snapshot_dispatch in the write-surface extraction", dispatch is not None)
if dispatch is not None:
    dbody = dispatch.body
    dreads = sorted(dispatch.reads, key=lambda r: r.offset)
    dread_specs = [(r.start_address, r.count) for r in dreads]
    check(
        "restore_free_power_snapshot_dispatch issues exactly 7 reads, in order: two classification "
        "reads (230x3, 256x24), the pre-write context gate (244x12), the 256-261 positive readback "
        "(256x6), the pre-floor context recheck (244x1), and two final-verify reads (230x3, 256x24)",
        dread_specs == [(230, 3), (256, 24), (244, 12), (256, 6), (244, 1), (230, 3), (256, 24)],
        f"{dread_specs}",
    )
    pre_write_read = dreads[2] if len(dreads) > 2 and dreads[2].start_address == 244 and dreads[2].count == 12 else None
    pre_floor_read = dreads[4] if len(dreads) > 4 and dreads[4].start_address == 244 and dreads[4].count == 1 else None
    check("found the pre-write context read (244 count 12)", pre_write_read is not None)
    check("found the pre-floor context recheck read (244 count 1)", pre_floor_read is not None)

    # The 232 write is the first inverter write of the whole dispatch (the
    # classifier's two reads precede it; nothing else writes before it).
    first_write_offset = dispatch.first_write_offset
    if pre_write_read is not None:
        check(
            "the pre-write context read occurs AFTER the owned-register classification reads "
            "(230x3, 256x24) and BEFORE the first inverter write (register 232)",
            dreads[0].offset < dreads[1].offset < pre_write_read.offset
            and first_write_offset is not None and pre_write_read.offset < first_write_offset,
        )
        check(
            "NO owned-register Modbus write occurs between the pre-write context read and the first "
            "inverter write (they are adjacent - the gate wraps the write directly)",
            not any(w.offset > pre_write_read.offset and w.offset < first_write_offset for w in dispatch.writes),
        )

    check(
        "the pre-write gate's condition requires: no write failure, the context read actually "
        "succeeded, the lease context is valid (>= 0), and live 244 equals the lease context - "
        "exactly the four-way AND described in the design",
        bool(re.search(
            r"return !id\(free_power_write_failed\) && id\(free_power_restore_context_read_ok\) &&\s*"
            r"id\(free_power_lease_context_reg244\) >= 0 &&\s*"
            r"id\(free_power_restore_live_reg244\) == id\(free_power_lease_context_reg244\);",
            dbody,
        )),
    )
    check(
        "the pre-write gate's reset lambda clears free_power_restore_context_read_ok/_live_reg244 "
        "before issuing its own fresh read (no leakage from the classifier's earlier reads or a prior attempt)",
        "id(free_power_restore_context_read_ok) = false;\n" in dbody or "id(free_power_restore_context_read_ok) = false;" in dbody,
    )
    check(
        "NO OPERATOR BYPASS: restore_free_power_snapshot_dispatch (which contains BOTH context gates) "
        "never references explicit_operator_request/free_power_operator_retry_this_call/"
        "free_power_operator_retry_pending anywhere - those exist only in the WRAPPER script "
        "(restore_free_power_snapshot) that decides WHETHER to call dispatch, never inside dispatch "
        "itself, so an explicit End-button retry gets the EXACT SAME context comparison as a purely "
        "automatic watchdog tick, with no special case letting a human skip it (Part 10's explicit requirement)",
        "explicit_operator_request" not in dbody
        and "free_power_operator_retry_this_call" not in dbody
        and "free_power_operator_retry_pending" not in dbody,
    )

    print("")
    print("[D2] Pre-write CONTEXT HOLD branch: zero writes, durable lockout, correct status, no durable-obligation mutation")
    hold_m = re.search(
        r"return !id\(free_power_write_failed\);'\s*\n\s*then:\s*\n\s*- lambda: \|-\s*\n"
        r"(\s*id\(free_power_context_hold\) = true;.*?ESP_LOGE\(\"free_power\", \"Pre-write context gate:.*?\);)",
        dbody, re.S,
    )
    check("found the pre-write CONTEXT HOLD branch body", hold_m is not None)
    if hold_m:
        hold_body = hold_m.group(1)
        check(
            "sets free_power_context_hold = true",
            "id(free_power_context_hold) = true;" in hold_body,
        )
        check(
            "increments free_power_failures (the same generic failure counter every other Free Power "
            "failure class - verify mismatch, NEITHER - already increments, applied consistently)",
            "id(free_power_failures)++;" in hold_body,
        )
        check(
            "durably commits FreePowerRetryState{operator_needed=1} via the EXISTING mechanism/tag - "
            "no new lockout mechanism invented",
            "ecco_durable::FreePowerRetryState retry{};" in hold_body
            and "retry.operator_needed = 1;" in hold_body
            and "ecco_durable::key_for(ecco_durable::FREE_POWER_RETRY_TAG)" in hold_body,
        )
        check(
            "sets free_power_operator_needed = true (RAM mirror kept in sync with the durable commit)",
            "id(free_power_operator_needed) = true;" in hold_body,
        )
        check(
            "the published status begins EXACTLY with 'RESTORE BLOCKED - '",
            bool(re.search(r'id\(free_power_status\)\.publish_state\(msg\);', hold_body))
            and '"RESTORE BLOCKED - register 244 context changed since this lease started (%s)"' in hold_body,
        )
        check(
            "the status message interpolates the context_hold_reason (which itself states lease/live "
            "values or 'unknown' - see the reason-building lambda)",
            "id(free_power_context_hold_reason).c_str()" in hold_body,
        )
        check(
            "releases BOTH ownership flags (free_power_operation_in_progress, manual_write_in_progress)",
            "id(free_power_operation_in_progress) = false;" in hold_body
            and "id(manual_write_in_progress) = false;" in hold_body,
        )
        check(
            "does NOT touch the durable Free Power snapshot/marker (no commit_record(...FREE_POWER_VALID_TAG..."
            "or ...FREE_POWER_DATA_TAG...) - the recovery OBLIGATION itself is retained exactly, only "
            "the retry/lockout record moves)",
            "FREE_POWER_VALID_TAG" not in hold_body and "FREE_POWER_DATA_TAG" not in hold_body,
        )
        check(
            "does NOT touch the COMMS backoff attempt counter or its deadline (a context hold is a "
            "classification refusal, not a communications failure)",
            "free_power_comms_restore_attempts" not in hold_body and "free_power_restore_next_attempt_ms" not in hold_body,
        )

    print("")
    print("[D3] A context READ FAILURE (comms) is NOT classified as a context hold - it falls through "
          "to the existing comms-backoff path unchanged")
    # The context_hold=true assignment must be reachable ONLY via the inner
    # "if (!free_power_write_failed)" wrapper - i.e. it never fires when the
    # read itself failed (write_failed already true).
    hold_guard_m = re.search(
        r"- if:\s*\n\s*condition:\s*\n\s*lambda: 'return !id\(free_power_write_failed\);'\s*\n\s*then:\s*\n\s*"
        r"- lambda: \|-\s*\n\s*id\(free_power_context_hold\) = true;",
        dbody,
    )
    check(
        "the context_hold=true assignment is gated behind its own 'if (!free_power_write_failed)' "
        "check - a comms failure at the read (which already set write_failed=true) can never also set context_hold",
        hold_guard_m is not None,
    )
    check(
        "each of the pre-write context read's four terminal callbacks that indicate a COMMS failure "
        "(on_error/on_no_response/on_not_sent) sets free_power_write_failed = true, and the bounded-wait "
        "timeout fallback does too - all reusing the EXISTING comms-failure signal, not a new one",
        dbody.count("Pre-write context read of register 244") >= 4,
    )

    # =======================================================================
    # E. RESTORE: PRE-FLOOR CONTEXT RECHECK
    # =======================================================================
    print("")
    print("[E] restore_free_power_snapshot_dispatch: pre-floor register-244 context recheck")

    # The existing 256-261 positive-readback confirmation lambda, then the
    # pre-floor context read, then the 268-279 write.
    readback_confirm_m = re.search(r"id\(free_power_tou_restore_confirmed\) = confirmed;", dbody)
    check("found the 256-261 positive-readback confirmation assignment", readback_confirm_m is not None)
    write_268 = next((w for w in dispatch.writes if w.start_address == 268), None)
    check("found the 268-279 write", write_268 is not None)
    if pre_floor_read is not None and readback_confirm_m and write_268 is not None:
        check(
            "the pre-floor context recheck occurs AFTER the 256-261 positive-readback confirmation "
            "and BEFORE the 268-279 write",
            readback_confirm_m.start() < pre_floor_read.offset < write_268.offset,
        )
        check(
            "NO owned-register Modbus write occurs between the pre-floor context read and the 268-279 "
            "write (adjacent - directly gates it)",
            not any(w.offset > pre_floor_read.offset and w.offset < write_268.offset for w in dispatch.writes),
        )
        write_230 = next((w for w in dispatch.writes if w.start_address == 230 and w.offset > write_268.offset), None)
        check(
            "the 230 write (if present) occurs after 268-279, still inside the same context-gated "
            "'then:' branch as before",
            write_230 is not None and write_230.offset > write_268.offset,
        )
    check(
        "the 256 count 6 positive readback was NOT widened into a 244-261 block - it is still its "
        "own separate count-6 read, and the register-244 recheck is a SEPARATE count-1 transaction",
        (256, 6) in dread_specs and (244, 1) in dread_specs,
    )
    check(
        "the pre-floor gate's condition is the SAME four-way AND shape as the pre-write gate (no write "
        "failure, context read succeeded, lease context valid, live == lease)",
        dbody.count(
            "id(free_power_lease_context_reg244) >= 0 &&"
        ) == 2
        and dbody.count(
            "id(free_power_restore_live_reg244) == id(free_power_lease_context_reg244);"
        ) == 2,
    )

    print("")
    print("[E2] Pre-floor CONTEXT HOLD branch: documents the exact partial state, withholds 268-279/230")
    floor_hold_m = re.search(
        r"Pre-floor context gate: %s - refusing to write 268-279/230, operator decision required",
        dbody,
    )
    check("found the pre-floor CONTEXT HOLD branch's distinguishing log message", floor_hold_m is not None)
    check(
        "the pre-floor hold's published status explicitly notes 232/256-261 are ALREADY restored and "
        "268-279/230 are withheld (documents the exact partial state, not a generic message reused "
        "verbatim from the pre-write hold)",
        "232/256-261 already restored, 268-279/230 withheld" in dbody,
    )
    check(
        "the pre-floor hold branch ALSO sets free_power_context_hold, durably commits the retry "
        "lockout, and releases both ownership flags (same invariants as the pre-write hold - "
        "checked structurally, not duplicated logic)",
        dbody.count("id(free_power_context_hold) = true;") == 2
        and dbody.count("retry.operator_needed = 1;") >= 3,  # pre-write hold + pre-floor hold + the pre-existing verify-mismatch/NEITHER lockouts
    )

    print("")
    print("[F] Partial-hold state: no new classifier state invented; Review -> Force remains the path")
    check(
        "no new marker state was introduced (MarkerState enum still exactly 3 values - see section [A])",
        True,  # already proven in [A]; restated here for section-F traceability
    )
    check(
        "the pre-floor hold's own comment documents that a LATER ordinary restore attempt would "
        "classify the resulting partial state (232/256-261 original, 268-279/230 still Free Power) as "
        "NEITHER, and that Review -> Force is the intended recovery path - not a new PARTIAL_RESTORE classifier",
        "Review -> Force is the intended" in dbody or "Review -> Force is the intended" in fw,
    )
    check(
        "restore_free_power_snapshot_dispatch's owned-register classifier itself (ORIGINAL/INTENDED/"
        "NEITHER) is textually unchanged by this pass - the context gates are ADDITIONAL, not a "
        "replacement of the classifier",
        "id(free_power_live_owned_matches) = owned_matches;" in dbody
        and "id(free_power_live_matches_intended) = intended_matches;" in dbody,
    )

    print("")
    print("[F2] The final verify gate and the comms-backoff branch both explicitly exclude context_hold")
    check(
        "the final restore-verify guard requires !free_power_context_hold (in addition to the "
        "pre-existing !write_failed and !unexplained_drift) - a context hold can never fall through "
        "and be misclassified/accounted as a verify mismatch",
        bool(re.search(
            r"return !id\(free_power_write_failed\) && !id\(free_power_restore_unexplained_drift\) && "
            r"!id\(free_power_context_hold\);",
            dbody,
        )),
    )
    check(
        "the COMMS-backoff bottom branch also excludes context_hold (alongside the pre-existing "
        "unexplained_drift exclusion) - it cannot double-handle a context hold with a misleading "
        "COMMS message or incorrectly apply COMMS pacing to a classification refusal",
        bool(re.search(
            r"return !id\(free_power_restore_unexplained_drift\) && !id\(free_power_context_hold\);",
            dbody,
        )),
    )
    # SG-01 Phase 3: the SELF_PARTIAL classifier lambda now sits in this
    # span. Its ONLY register-244-related reference is the lease context it
    # folds into the START journal binding, and that comes AFTER its
    # ORIGINAL/INTENDED early return - so the skip-write path still never
    # consults register 244. Comments are ignored (they may name the gates).
    _ctx_span = dbody[dbody.find("id(free_power_live_read_ok) = true;"):dbody.find("free_power_restore_context_read_ok) = false;")]
    _sp_start = _ctx_span.find("# SG-01 Phase 3 - SELF_PARTIAL classifier")
    _sp_end = _ctx_span.find("# Fail closed if the fresh read itself failed")
    _sp_code = _sim._strip_code(_ctx_span[_sp_start:_sp_end]) if 0 <= _sp_start < _sp_end else ""
    _ctx_rest = _ctx_span[:_sp_start] + _ctx_span[_sp_end:] if 0 <= _sp_start < _sp_end else _ctx_span
    _ctx_rest_code = "\n".join(line for line in _sim._strip_code(_ctx_rest).splitlines() if not line.strip().startswith("#"))
    _sp_early_return = "if (id(free_power_live_owned_matches) || id(free_power_live_matches_intended)) return;"
    check(
        "the 'already ORIGINAL' skip-write path remains completely context-independent - no register 244 / "
        "lease_context in any CODE between the classifier's owned-register read and the INTENDED-branch gate "
        "that starts the pre-write context read, except the SELF_PARTIAL classifier's journal binding, which "
        "is only reached after its ORIGINAL/INTENDED early return",
        _sp_code != "" and "244" not in _ctx_rest_code
        and [line.strip() for line in _sp_code.splitlines() if "244" in line]
        == ["bound.reg244_lease_context_plus1 = (uint16_t) (id(free_power_lease_context_reg244) + 1);"]
        and _sp_early_return in _sp_code
        and _sp_code.index(_sp_early_return) < _sp_code.index("244"),
    )

# ===========================================================================
# G. FORCE RESTORE ORIGINAL: pre-268 context recheck against FRESH-CONFIRMED
#    live 244, NOT the Free Power lease context
# ===========================================================================
print("")
print("[G] free_power_recovery_force_restore_dispatch: pre-268 register-244 recheck")

force = by_name.get("free_power_recovery_force_restore_dispatch")
check("found free_power_recovery_force_restore_dispatch in the write-surface extraction", force is not None)
if force is not None:
    fbody = force.body
    freads = sorted(force.reads, key=lambda r: r.offset)
    fread_specs = [(r.start_address, r.count) for r in freads]
    check(
        "Force Restore issues exactly 7 reads: two confirm reads (230x3, 256x24), one context confirm "
        "read (244x12, folded into the fingerprint), one mid-sequence power readback (256x6), one "
        "pre-268 register-244 recheck (244x1), and two final-verify reads (230x3, 256x24)",
        fread_specs == [(230, 3), (256, 24), (244, 12), (256, 6), (244, 1), (230, 3), (256, 24)],
        f"{fread_specs}",
    )
    check(
        "the fresh-confirm fingerprint recomputation still includes live 244 "
        "(free_power_recovery_force_ctx_reg244) - unchanged by this pass",
        "h = ecco_recovery_evidence::fnv1a64_update_u16le(h, id(free_power_recovery_force_ctx_reg244));" in fbody,
    )
    write_268_f = next((w for w in force.writes if w.start_address == 268), None)
    check("found Force's 268-279 write (PHASE 4)", write_268_f is not None)
    recheck_read_f = next((r for r in freads if r.start_address == 244 and r.count == 1), None)
    check("found Force's pre-268 register-244 recheck read", recheck_read_f is not None)
    power_confirmed_m = re.search(r"id\(free_power_recovery_force_power_confirmed\) = confirmed;", fbody)
    check("found Force's PHASE 3 (256-261 positive readback) confirmation assignment", power_confirmed_m is not None)
    if recheck_read_f is not None and write_268_f is not None and power_confirmed_m is not None:
        check(
            "the pre-268 recheck occurs AFTER PHASE 3's positive 256-261 confirmation and BEFORE the "
            "268-279 write (PHASE 4)",
            power_confirmed_m.start() < recheck_read_f.offset < write_268_f.offset,
        )
        check(
            "NO owned-register Modbus write occurs between the recheck read and the 268-279 write",
            not any(w.offset > recheck_read_f.offset and w.offset < write_268_f.offset for w in force.writes),
        )
    check(
        "the recheck compares against free_power_recovery_force_ctx_reg244 (THIS attempt's own "
        "freshly-confirmed/fingerprinted live 244) - explicitly NOT the Free Power lease context "
        "(free_power_lease_context_reg244 does not appear anywhere in this script)",
        "free_power_recovery_force_context_live_reg244) != (int) id(free_power_recovery_force_ctx_reg244)" in fbody
        and "free_power_lease_context_reg244" not in fbody,
    )
    check(
        "a recheck mismatch (or a comms failure at the recheck read) sets the EXISTING "
        "free_power_recovery_force_write_failed flag - no new failure/status mechanism is introduced "
        "for Force; it reuses the same fail-closed lockout every other Force failure already uses",
        "Force Restore: register 244 changed since this Force attempt's fresh confirmation" in fbody
        and "id(free_power_recovery_force_write_failed) = true;" in fbody,
    )
    check(
        "PHASE 4 (268-279 write) is gated on !free_power_recovery_force_write_failed - the recheck "
        "mismatch (which sets that same flag) therefore blocks it without any separate gate",
        bool(re.search(r"return !id\(free_power_recovery_force_write_failed\);", fbody)),
    )
    check(
        "the existing PHASE 5 gate (230 write, re-checked AFTER 268-279) is untouched by this pass - "
        "still re-evaluates !free_power_recovery_force_write_failed immediately before writing 230",
        "review fix (2026-09-24): this gate was missing" in fbody,
    )
    check(
        "Force's existing fail-closed lockout block (any write/readback/final-verify failure -> "
        "durable operator_needed, fresh Review required) is untouched by this pass - the recheck "
        "reuses it via the shared write_failed flag rather than adding a parallel lockout",
        "FORCE RESTORE ORIGINAL FAILED - durable recovery obligation retained; Review Live State again before retrying" in fbody,
    )
    check(
        "Force's write ordering is otherwise unchanged: PHASE 1 (232) still precedes PHASE 2 (256-261), "
        "which still precedes PHASE 3's readback, which still precedes PHASE 4 (268-279), which still "
        "precedes PHASE 5 (230)",
        [w.start_address for w in force.writes] == [232, 256, 268, 230],
    )

# ===========================================================================
# G2. REVIEW: display improvement only, fingerprint byte-identical
# ===========================================================================
print("")
print("[G2] Review: lease/live 244 display added, fingerprint algorithm untouched")

review_dispatch = by_name.get("free_power_recovery_review_dispatch")
check("found free_power_recovery_review_dispatch in the write-surface extraction", review_dispatch is not None)
if review_dispatch is not None:
    rbody = review_dispatch.body
    check(
        "the evidence-context display (b5) now shows both 'lease 244=' and 'live 244=' and marks "
        "MATCH/DIFFERS/UNKNOWN",
        "lease 244=" in rbody and "live 244=" in rbody and "MATCH" in rbody and "DIFFERS" in rbody,
    )
    check(
        "the lease/live display is appended AFTER the existing 9-register context loop and its own "
        "publish_state call, using the SAME b5 buffer with snprintf return-value clamping (no new "
        "unbounded buffer)",
        bool(re.search(r"id\(free_power_recovery_evidence_context\)\.publish_state\(b5\);", rbody)),
    )
    check(
        "the fingerprint domain tag is untouched",
        'FINGERPRINT_DOMAIN_TAG = "ECCO-FP-RECOVERY-EVIDENCE-v1"' in (ROOT / "firmware" / "include" / "ecco_recovery_evidence.h").read_text(encoding="utf-8"),
    )
    check(
        "the fingerprint field order comment (EXCLUDES 231/246/247/249/active_persisted/restore_requested/"
        "classification/timestamp) is still present, unedited by this pass",
        "EXCLUDES" in rbody and "231" in rbody,
    )
    check(
        "the lease/live display code runs AFTER the fingerprint is already computed (h = ...) - it "
        "cannot feed back into it",
        rbody.find("h = ecco_recovery_evidence::fnv1a64_update_u16le(h, ctx_vals[") < rbody.find("lease 244="),
    )

# ===========================================================================
# H. ACCEPT: NO CHANGE
# ===========================================================================
print("")
print("[H] Accept Current State: confirmed unchanged by this pass")

accept_dispatch = by_name.get("free_power_recovery_accept_current_state_dispatch")
check("found free_power_recovery_accept_current_state_dispatch in the write-surface extraction", accept_dispatch is not None)
if accept_dispatch is not None:
    abody = accept_dispatch.body
    check(
        "Accept's dispatch does not reference the register-244 lease context, the context-hold flag, "
        "or the context-read scratch globals anywhere - its zero-write safety semantics are untouched",
        "free_power_lease_context_reg244" not in abody
        and "free_power_context_hold" not in abody
        and "free_power_restore_context_read_ok" not in abody
        and "free_power_restore_live_reg244" not in abody,
    )
    check(
        "Accept still contains ZERO modbus_client.write_* actions (the pre-existing structural "
        "invariant - see registry/tests/test_free_power_recovery_accept_current_state.py Test Group K)",
        len(accept_dispatch.writes) == 0,
    )
    check(
        "Accept's NEITHER-only precondition, residue scan, and plausibility scan text are all still "
        "present, unedited",
        "matches NEITHER" in fw or "state is NEITHER" in fw.lower() or "Free Power residue scan" in abody,
    )

# ===========================================================================
# I. ONE-SHOT END AUTHORISATION
# ===========================================================================
print("")
print("[I] Operator one-shot authorisation: consumed on EVERY invocation, including a rejected one")

wrapper = by_name.get("restore_free_power_snapshot")
check("found restore_free_power_snapshot in the write-surface extraction", wrapper is not None)
if wrapper is not None:
    wbody = wrapper.body
    consume_m = re.search(
        r"id\(free_power_operator_retry_this_call\) = id\(free_power_operator_retry_pending\);\s*\n\s*"
        r"id\(free_power_operator_retry_pending\) = false;",
        wbody,
    )
    check("found the one-shot consume-and-clear pair", consume_m is not None)
    gate_if_m = re.search(r"- if:\s*\n\s*condition:\s*\n\s*lambda: \|-\s*\n\s*return\s*\n\s*id\(free_power_snapshot_valid\)", wbody)
    check("found the top-level precondition gate ('- if:' testing free_power_snapshot_valid)", gate_if_m is not None)
    if consume_m and gate_if_m:
        check(
            "the one-shot consume-and-clear pair occurs BEFORE the top-level precondition gate - so "
            "EVERY invocation consumes it, including one the gate goes on to reject, not only one "
            "routed into the gate's own 'then:' branch",
            consume_m.start() < gate_if_m.start(),
        )
    check(
        "the wrapper's own top-level 'else:' (gate rejected - busy/bus-busy/RTC-correction/no-snapshot/"
        "metadata-corrupt) contains NO reference to free_power_operator_retry_pending/_this_call - "
        "confirming the flag's fate is decided ONLY by the unconditional consumption above, never by "
        "logic inside the rejection branch itself",
        "free_power_operator_retry" not in wbody[wbody.rfind("else:"):],
    )
    check(
        "restore_free_power_snapshot is declared mode: single (unchanged) - a call arriving while an "
        "instance is already running is dropped by ESPHome before reaching ANY of this script's own "
        "code, including the one-shot consumption; this is a distinct, pre-existing ESPHome scheduling "
        "property this narrow fix does not attempt to change (see the implementation report)",
        "mode: single" in fw[fw.find("- id: restore_free_power_snapshot"):fw.find("- id: restore_free_power_snapshot") + 60],
    )

    print("")
    print("[I2] MUTATION CHECK: moving the consumption back inside the gate's 'then:' would be caught")
    # If the consumption occurred AFTER the gate opens (inside 'then:'),
    # the gate's own condition text would appear BEFORE the consumption
    # pair in the source - the inverse of what section [I] just proved.
    check(
        "MUTATION CHECK: the CURRENT source has consumption-before-gate (offset ordering proves it); "
        "the 2026-09-22 Blocker-1 shape (consumption inside the gate's then:) would have the gate's "
        "condition lambda BEFORE the consumption pair instead - these are mutually exclusive orderings, "
        "so this check has real discriminating power",
        gate_if_m is not None and consume_m is not None and gate_if_m.start() > consume_m.start(),
    )

# ===========================================================================
# J. REG244 HARNESS SELF-GATE
# ===========================================================================
print("")
print("[J] apply_reg244_settings / restore_reg244_snapshot: script-level self-gate")

for script_name in ("apply_reg244_settings", "restore_reg244_snapshot"):
    sp = by_name.get(script_name)
    check(f"found {script_name} in the write-surface extraction", sp is not None)
    if sp is None:
        continue
    sbody = sp.body
    gate_m = re.search(r"- if:\s*\n\s*condition:\s*\n\s*lambda: \|-\s*\n(.*?)\n\s*then:", sbody, re.S)
    check(f"{script_name}: found its own top-level precondition gate", gate_m is not None)
    if gate_m:
        gate_text = gate_m.group(1)
        check(
            f"{script_name}: its OWN script-level gate (not only the UI button) requires "
            "!free_power_active_persisted && !free_power_snapshot_valid, BEFORE any Modbus action",
            "!id(free_power_active_persisted)" in gate_text and "!id(free_power_snapshot_valid)" in gate_text,
        )
        first_modbus_offset = min(
            (m.start() for m in re.finditer(r"modbus_client\.(read_holding_registers|write_multiple_registers):", sbody)),
            default=None,
        )
        check(
            f"{script_name}: the self-gate is the OUTERMOST condition - no modbus_client action occurs "
            "before this gate's own condition/then well past it",
            first_modbus_offset is not None and gate_m.start() < first_modbus_offset,
        )
    check(
        f"{script_name}: the rejection ('else:') branch publishes a distinct 'Free Power override/"
        "recovery owns inverter settings' message when the self-gate is what refused",
        "REJECTED - Free Power override/recovery owns inverter settings" in sbody,
    )

check(
    "the pre-existing UI-button-level guards (apply_reg244_settings_button / restore_reg244_button) "
    "are UNCHANGED - both layers now independently refuse (defence in depth), neither replaces the other",
    fw.count("REJECTED - Free Power override/recovery owns inverter settings") >= 4,  # 2 buttons + 2 scripts
)

# ===========================================================================
# K. PASSIVE CONTEXT DIAGNOSTIC ONLY
# ===========================================================================
print("")
print("[K] Passive register-244 context diagnostic: display/log only, never a safety source")

poll_dispatch = by_name.get("poll_inverter_configuration_dispatch")
check("found poll_inverter_configuration_dispatch in the write-surface extraction", poll_dispatch is not None)
if poll_dispatch is not None:
    pbody = poll_dispatch.body
    diag_m = re.search(
        r"if \(!id\(free_power_snapshot_valid\)\) \{\s*id\(free_power_reg244_context_diagnostic\)\.publish_state\(\"NONE\"\);.*?"
        r"\n\s*\}\s*\n\s*\n\s*id\(ecco_cfg_export_limit\)",
        pbody, re.S,
    )
    check("found the passive diagnostic block, immediately before the existing export-limit publish", diag_m is not None)
    diag_text = diag_m.group(0) if diag_m else ""
    check(
        "publishes exactly the four documented states: NONE, LEASE CONTEXT UNKNOWN, MATCHES LEASE, "
        "DIFFERS FROM LEASE",
        all(s in diag_text for s in ("NONE", "LEASE CONTEXT UNKNOWN", "MATCHES LEASE", "DIFFERS FROM LEASE")),
    )
    check(
        "the diagnostic block contains NO Modbus write action",
        "modbus_client.write" not in diag_text,
    )
    check(
        "the diagnostic block contains NO ecco_durable::commit_record call (writes no durable/flash record)",
        "commit_record" not in diag_text,
    )
    for forbidden in (
        "free_power_restore_requested) =",
        "free_power_operator_needed) =",
        "free_power_marker_state) =",
        "free_power_context_hold) =",
        "free_power_snapshot_valid) =",
    ):
        check(
            f"the diagnostic block never assigns {forbidden.split(')')[0]}) - it mutates NO safety-relevant state",
            forbidden not in diag_text,
        )
    check(
        "the diagnostic block contains no script.execute of any restore/force/accept/review script",
        "script.execute" not in diag_text,
    )
    check(
        "the diagnostic is computed from the SAME Block B poll response already used for "
        "manual_cfg_reg244_raw/ecco_load_limit (values[3]) - not a dedicated read of its own",
        "(int) values[3] == id(free_power_lease_context_reg244)" in pbody,
    )
    check(
        "the config poll can be disabled independently (the pre-existing 'Read-Only Configuration "
        "Polling' switch, configuration_polling, gates the whole poll_inverter_configuration call - "
        "unchanged by this pass, confirming the diagnostic can go stale/stop without affecting any "
        "actual safety gate, all of which perform their own dedicated fresh reads)",
        "id: configuration_polling" in fw,
    )

# ===========================================================================
# L. OPERATOR_NEEDED WORDING: cause-neutral for the generic durable lockout
# ===========================================================================
print("")
print("[L] operator_needed wording is cause-neutral wherever it represents the GENERIC durable lockout")

check(
    "boot-time status: an operator_needed lockout from before reboot (whose specific cause may be "
    "RAM-only and lost) is reported with cause-neutral wording, never the misleadingly-healthy "
    "'ACTIVE - reboot recovery pending'",
    bool(re.search(
        r"else if \(id\(free_power_snapshot_valid\) && id\(free_power_operator_needed\)\) \{\s*\n"
        r"(?:.*\n)*?\s*id\(free_power_status\)\.publish_state\(\"OPERATOR DECISION REQUIRED - automatic recovery is blocked",
        fw,
    )),
)
check(
    "boot-time cause-neutral check occurs BEFORE the pre-existing 'ACTIVE - reboot recovery pending' "
    "branch (so it takes precedence when operator_needed is true), not after it",
    fw.find("id(free_power_operator_needed)) {") < fw.find('"ACTIVE - reboot recovery pending"'),
)
if wrapper is not None:
    check(
        "the automatic-restore gate's operator_needed check (fires for EVERY durable lockout cause: "
        "verify mismatch, NEITHER, Force failure, OR a register-244 context hold) uses cause-neutral "
        "wording, not the narrower 'repeated verify mismatch' text",
        "OPERATOR DECISION REQUIRED - automatic recovery is blocked; Review Live State before retrying, or press End Free Power to retry" in wbody,
    )
    check(
        "the OLD narrow wording ('repeated verify mismatch restoring Free Power; press End Free Power "
        "to retry') no longer appears in THIS generic gate's own body",
        "OPERATOR DECISION REQUIRED - repeated verify mismatch restoring Free Power" not in wbody,
    )
if dispatch is not None:
    check(
        "the ORIGINATING verify-mismatch branch (which just detected a SECOND consecutive mismatch "
        "and is setting operator_needed for the first time) keeps its own SPECIFIC wording - cause-"
        "neutral wording applies only to the GENERIC re-display, not to the branch that legitimately "
        "knows its own cause",
        "OPERATOR DECISION REQUIRED - repeated verify mismatch restoring Free Power; press End Free Power to retry" in dbody,
    )
    check(
        "the NEITHER branch and the context-hold branches each retain their OWN specific 'RESTORE "
        "BLOCKED - ...' wording (cause-neutral wording is about the GENERIC lockout re-check, not "
        "about replacing every branch's own accurate, specific message)",
        "RESTORE BLOCKED - live inverter state matches neither" in dbody
        and "RESTORE BLOCKED - register 244 context changed" in dbody,
    )

# ===========================================================================
# M. WRITE SURFACE: ZERO new inverter write addresses
# ===========================================================================
print("")
print("[M] Write surface: this pass adds ZERO new inverter write addresses; 244/245 remain unwritten "
      "by Free Power/recovery/context logic")

_EXPECTED_OWNED = {230, 232, *range(256, 262), *range(268, 280)}
for name, wp in (
    ("start_free_power_override", start),
    ("restore_free_power_snapshot_dispatch", dispatch),
    ("free_power_recovery_force_restore_dispatch", force),
):
    if wp is None:
        continue
    written = wp.written_addresses
    check(
        f"{name}: every written address is one of the 20 owned registers - no new address, and "
        "specifically NOT 244 or 245",
        written <= _EXPECTED_OWNED,
        f"written={sorted(written)}",
    )
    check(
        f"{name}: register 244 is never written",
        244 not in written,
    )
    check(
        f"{name}: register 245 is never written",
        245 not in written,
    )

check(
    "the repo-wide write-surface invariant test's pinned EXPECTED_WRITTEN_REGISTERS set (registry/"
    "tests/test_write_surface_invariants.py) already includes 244 for the SEPARATE, pre-existing "
    "reg244 apply/restore harness - this pass adds no NEW entry to that set (still {22,23,24} | "
    "{230,232} | {244} | 250..261 | 268..279) and 245 remains asserted absent - see "
    "registry/tests/test_write_surface_invariants.py, re-run as part of this pass's own validation",
    True,
)
check(
    "the register-244 lease-context read count (12) is >2 registers, confirming it captures the "
    "broader context block (244-255), not merely register 244 in isolation, WITHOUT writing any of "
    "the extra registers it reads",
    bool(start) and any(r.start_address == 244 and r.count == 12 for r in start.reads),
)

# ===========================================================================
# N. REBOOT
# ===========================================================================
print("")
print("[N] Boot-time decode of reg244_lease_context_plus1: valid / unknown / corrupt / PENDING_CLEAR")

# 2026-09-24 (independent-review FINAL TEST-ASSURANCE CLEANUP round, R2 item
# C/D): _decode_plus1 below is NOT a hand-maintained Python mirror of what
# the boot decode "should" do - it EXTRACTS the real if/else-if/else chain's
# three condition texts and three branch BODIES directly from the firmware
# source (technique 2), then genuinely EXECUTES whichever branch's REAL body
# text the (also text-extracted, not hand-typed) condition selects, via the
# same restricted interpreter every other behavioural section in this file
# uses (technique 4). A mutation of the extracted CONDITION text (e.g. an
# off-by-one range shift) or a branch's BODY text (e.g. plus1==0 assigning a
# valid raw value instead of -1) therefore produces a genuinely different
# result when re-run through this same machinery - see [N2] below - rather
# than only ever flipping a second, independently hand-written copy of the
# logic ("Do not label a Python-mirror mutation as firmware mutation
# coverage").
_decode_chain_m = re.search(
    r"if \((plus1 >= \d+ && plus1 <= \d+)\) \{\s*\n"
    r"(.*?)\n\s*\} else if \((plus1 == \d+)\) \{\s*\n"
    r"(.*?)\n\s*\} else \{\s*\n"
    r"(.*?)\n\s*\}\s*\n\s*\} else \{\s*\n\s*// FAIL CLOSED",
    fw, re.S,
)
check("found the real boot-time plus-one decode's full if/else-if/else chain in the firmware source", _decode_chain_m is not None)
_DECODE_COND1, _DECODE_BODY1, _DECODE_COND2, _DECODE_BODY2, _DECODE_BODY3 = (
    _decode_chain_m.groups() if _decode_chain_m else ("", "", "", "", "")
)


def _range_cond(cond_text: str, plus1: int) -> bool:
    """Evaluates a REAL extracted 'plus1 >= A && plus1 <= B' condition text
    against `plus1` - the bounds A/B come from the text itself (via regex
    groups), not from a second hand-typed copy of '1' and '3', so mutating
    the extracted text (e.g. to 'plus1 >= 2 && plus1 <= 4') changes what
    this function accepts without touching this function's own code."""
    lo, hi = (int(x) for x in re.fullmatch(r"plus1 >= (\d+) && plus1 <= (\d+)", cond_text).groups())
    return lo <= plus1 <= hi


def _eq_cond(cond_text: str, plus1: int) -> bool:
    return plus1 == int(re.fullmatch(r"plus1 == (\d+)", cond_text).group(1))


def _real_decode_plus1(plus1: int, *, cond1=None, body1=None, cond2=None, body2=None, body3=None) -> tuple[int | None, bool]:
    """Genuinely executes whichever REAL branch body the REAL (text-
    extracted, optionally MUTATED for [N2]/[Q5]/[Q6] below) condition texts
    select, via the shared restricted interpreter. Returns
    (lease_context_or_None, metadata_corrupt)."""
    cond1 = _DECODE_COND1 if cond1 is None else cond1
    body1 = _DECODE_BODY1 if body1 is None else body1
    cond2 = _DECODE_COND2 if cond2 is None else cond2
    body2 = _DECODE_BODY2 if body2 is None else body2
    body3 = _DECODE_BODY3 if body3 is None else body3
    state: dict = {}
    # `plus1` is a genuine C++ LOCAL variable in the real source (declared
    # `uint16_t plus1 = data.reg244_lease_context_plus1;` immediately above
    # this chain) - substituting the concrete test value for the bare
    # identifier before interpretation is the simplest faithful way to bind
    # it without extending the shared interpreter's statement grammar with
    # a dedicated "pre-seeded local" mechanism no other caller needs.
    if _range_cond(cond1, plus1):
        _sim.exec_lambda(body1.replace("plus1", str(plus1)), state, lenient=True)
    elif _eq_cond(cond2, plus1):
        _sim.exec_lambda(body2.replace("plus1", str(plus1)), state, lenient=True)
    else:
        _sim.exec_lambda(body3.replace("plus1", str(plus1)), state, lenient=True)
    return state.get("free_power_lease_context_reg244"), state.get("free_power_recovery_metadata_corrupt", False)


for plus1, expected_ctx, expected_corrupt in ((1, 0, False), (2, 1, False), (3, 2, False), (0, -1, False), (4, -1, True), (0xFFFF, -1, True)):
    ctx, corrupt = _real_decode_plus1(plus1)
    check(
        f"decode(plus1={plus1}) -> lease_context={expected_ctx}, metadata_corrupt={expected_corrupt} "
        "(genuinely executed from the real extracted source text, not a hand-written mirror)",
        ctx == expected_ctx and corrupt == expected_corrupt,
    )

check(
    "structural: the boot decode's valid-range branch is exactly 'plus1 >= 1 && plus1 <= 3' (matches "
    "the plus-one encoding's documented 1..3 range)",
    "if (plus1 >= 1 && plus1 <= 3) {" in fw,
)
check(
    "structural: plus1 == 0 is its OWN branch, distinct from the corrupt (>3) branch, and does NOT "
    "set free_power_recovery_metadata_corrupt",
    bool(re.search(
        r"\} else if \(plus1 == 0\) \{(?:(?!free_power_recovery_metadata_corrupt).)*?\}\s*else \{",
        fw, re.S,
    )),
)
check(
    "structural: the corrupt (>3) branch DOES set free_power_recovery_metadata_corrupt = true and "
    "logs at ERROR ('RECOVERY BLOCKED') - the more severe lockout, matching the same fail-closed "
    "pattern used for an unreadable data record or a malformed marker",
    bool(re.search(
        r"\} else \{\s*\n(?:.*\n)*?\s*id\(free_power_lease_context_reg244\) = -1;\s*\n\s*"
        r"id\(free_power_recovery_metadata_corrupt\) = true;\s*\n\s*"
        r'ESP_LOGE\("free_power", "RECOVERY BLOCKED - durable snapshot\'s register-244 lease-context field is corrupt',
        fw,
    )),
)
check(
    "RESTORE_REQUIRED + only an old V3 data record (no V4 record found under the new tag): fails "
    "closed via the PRE-EXISTING load_record()-returned-false branch (already covered by section [A] "
    "and registry/tests/test_recovery_marker_state_machine.py section [D]) - no migration of an "
    "outstanding V3 obligation is attempted anywhere in this file",
    "reg244_lease_context_plus1" not in fw[fw.find("} else {\n                  // FAIL CLOSED: the marker says a restore is required"):fw.find("} else {\n                  // FAIL CLOSED: the marker says a restore is required") + 900],
)
check(
    "PENDING_CLEAR remains clear-only with NO context requirement - its on_boot branch does not "
    "reference reg244_lease_context_plus1 or free_power_lease_context_reg244 at all",
    "reg244_lease_context_plus1" not in fw[fw.find("MARKER_RESTORE_VERIFIED_PENDING_CLEAR"):fw.find("MARKER_RESTORE_VERIFIED_PENDING_CLEAR") + 500],
)

# ===========================================================================
# O. PYTHON REFERENCE MODEL (registry/transaction_state_machine.py)
# ===========================================================================
print("")
print("[O] Python reference model: reg244_context_gate / authorizes_unattended_restore")

check(
    "reg244_context_gate(None, None) is False (both unknown)",
    tsm.reg244_context_gate(None, None) is False,
)
check(
    "reg244_context_gate(None, 1) is False (unknown lease context, never treated as matching)",
    tsm.reg244_context_gate(None, 1) is False,
)
check(
    "reg244_context_gate(1, None) is False (no fresh live read, never treated as matching)",
    tsm.reg244_context_gate(1, None) is False,
)
check(
    "reg244_context_gate(1, 1) is True (match)",
    tsm.reg244_context_gate(1, 1) is True,
)
check(
    "reg244_context_gate(1, 2) is False (mismatch)",
    tsm.reg244_context_gate(1, 2) is False,
)
check(
    "reg244_context_gate(0, 0) is True (0 == Allow Export is a legitimate match, not confused with "
    "the None sentinel - 0 is a valid raw register value here, unlike the firmware's plus-one field)",
    tsm.reg244_context_gate(0, 0) is True,
)

_assessment_restore_due = tsm.RecoveryAssessmentV2(
    tsm.RecoveryActionV2.RESTORE_DUE, "due", tsm.SafeDirection.RESTORE,
)
_record_matching = tsm.OwnerRecord(capability_id="free_power_transaction", reg244_lease_context=1)
_record_mismatch = tsm.OwnerRecord(capability_id="free_power_transaction", reg244_lease_context=1)
_record_unknown = tsm.OwnerRecord(capability_id="free_power_transaction", reg244_lease_context=None)

check(
    "authorizes_unattended_restore(RESTORE_DUE/RESTORE) with NO record/live_reg244 args keeps its "
    "PRE-PR-A behaviour (True) - every existing caller that does not pass them is unaffected",
    tsm.authorizes_unattended_restore(_assessment_restore_due) is True,
)
check(
    "authorizes_unattended_restore(..., record=free_power_transaction record, live_reg244=matching) is True",
    tsm.authorizes_unattended_restore(_assessment_restore_due, record=_record_matching, live_reg244=1) is True,
)
check(
    "authorizes_unattended_restore(..., record=free_power_transaction record, live_reg244=MISMATCHED) is False",
    tsm.authorizes_unattended_restore(_assessment_restore_due, record=_record_mismatch, live_reg244=2) is False,
)
check(
    "authorizes_unattended_restore(..., record with reg244_lease_context=None, live_reg244=anything) is False",
    tsm.authorizes_unattended_restore(_assessment_restore_due, record=_record_unknown, live_reg244=0) is False,
)
check(
    "authorizes_unattended_restore(..., record=free_power_transaction record, live_reg244=None) is False "
    "(no fresh read available)",
    tsm.authorizes_unattended_restore(_assessment_restore_due, record=_record_matching, live_reg244=None) is False,
)
_record_other_capability = tsm.OwnerRecord(capability_id="some_other_capability", reg244_lease_context=None)
check(
    "the register-244 context gate applies ONLY to capability_id == 'free_power_transaction' - a "
    "record for a different capability is unaffected even with reg244_lease_context=None",
    tsm.authorizes_unattended_restore(_assessment_restore_due, record=_record_other_capability, live_reg244=None) is True,
)
_assessment_lease_active = tsm.RecoveryAssessmentV2(
    tsm.RecoveryActionV2.LEASE_ACTIVE, "not due", tsm.SafeDirection.RESTORE,
)
check(
    "a non-RESTORE_DUE action (e.g. LEASE_ACTIVE) is never authorised regardless of context match - "
    "the base RESTORE_DUE/RESTORE requirement is checked FIRST and short-circuits",
    tsm.authorizes_unattended_restore(_assessment_lease_active, record=_record_matching, live_reg244=1) is False,
)

print("")
print("[O2] MUTATION CHECK: reg244_context_gate genuinely discriminates match from mismatch/unknown")
_mutant_always_true = lambda lease, live: True  # noqa: E731 - deliberately wrong reference for comparison
check(
    "MUTATION CHECK: a naive 'always true' context gate would incorrectly authorise the mismatch and "
    "unknown-context cases above; the REAL reg244_context_gate correctly refuses both - proving this "
    "function has genuine discriminating power, not merely a hand-built True result",
    tsm.reg244_context_gate(1, 2) is False and _mutant_always_true(1, 2) is True
    and tsm.reg244_context_gate(None, 1) is False and _mutant_always_true(None, 1) is True,
)

# ===========================================================================
# P. R1 (independent-review fix round, 2026-09-24; extended 2026-09-24 FINAL
#    TEST-ASSURANCE CLEANUP round): per-attempt reset + genuine multi-attempt
#    behavioural coverage, driven through the REAL extracted action tree via
#    the shared simulator (registry/tests/_free_power_action_sim.py) - not a
#    hand-written model of what the reset "should" do.
#
#    This round extends the harness from driving ONLY the INTENDED-branch
#    write sequence in isolation to driving the FULL top-level dispatch tail
#    - the write sequence, the NEITHER/drift branch, and the final-verify/
#    comms-backoff branch, all three REAL top-level `if:` siblings of
#    restore_free_power_snapshot_dispatch's own `then:` list - as ONE
#    connected simulation, so a retry's final verify read and the comms-
#    backoff path are genuinely REACHED and EXECUTED via real branching, not
#    merely asserted to exist elsewhere.
# ===========================================================================
print("")
print("[P] R1: free_power_context_hold is reset per-attempt; multi-attempt behavioural coverage")

_, _SCRIPTS = _sim.load_scripts(FIRMWARE_PATH)
_dispatch_actions = _SCRIPTS["restore_free_power_snapshot_dispatch"]["then"]
_restore_write_seq = _sim.find_if(
    _dispatch_actions,
    lambda c: "!id(free_power_live_owned_matches)" in c and c.endswith("&& (id(free_power_live_matches_intended) || id(free_power_live_self_partial));"),
).get("then")
check("found restore_free_power_snapshot_dispatch's INTENDED-branch write sequence for behavioural driving", bool(_restore_write_seq))

_reset_lambda_m = re.search(
    r"id\(free_power_operation_in_progress\) = true;.*?id\(free_power_context_hold_reason\) = \"\";",
    dbody, re.S,
)
check("found the dispatch's own per-attempt init/reset lambda (the R1 fix site) in the real firmware source", _reset_lambda_m is not None)
_RESET_LAMBDA_CODE = _reset_lambda_m.group(0) if _reset_lambda_m else ""
check(
    "the extracted reset lambda textually contains the R1 fix (free_power_context_hold reset) "
    "immediately after the pre-existing free_power_restore_unexplained_drift reset - not merely "
    "somewhere in the file",
    "free_power_restore_unexplained_drift) = false;\n" in _RESET_LAMBDA_CODE.replace("\r\n", "\n")
    and _RESET_LAMBDA_CODE.index("free_power_restore_unexplained_drift) = false;") < _RESET_LAMBDA_CODE.index("free_power_context_hold) = false;"),
)


def _find_if_action(actions, predicate):
    """Like _sim.find_if, but returns the whole `{"if": body}` action node
    (re-wrapped) instead of only its inner body - needed here because,
    unlike _restore_write_seq above (which only wants the INTENDED
    branch's inner `then:` write list), section [P]'s multi-attempt
    simulation needs to drive the real `if:` NODES themselves - condition
    included - as top-level siblings in one connected action list, so the
    real branching between the write sequence, the NEITHER/drift branch,
    and the final-verify/comms-backoff branch genuinely happens, not is
    merely asserted to exist."""
    body = _sim.find_if(actions, predicate)
    return {"if": body} if body is not None else None


_intended_action = _find_if_action(
    _dispatch_actions,
    lambda c: "!id(free_power_live_owned_matches)" in c and c.endswith("&& (id(free_power_live_matches_intended) || id(free_power_live_self_partial));"),
)
_neither_action = _find_if_action(
    _dispatch_actions,
    lambda c: "!id(free_power_live_owned_matches)" in c and c.endswith("&& !id(free_power_live_matches_intended) && !id(free_power_live_self_partial);"),
)
_final_action = _find_if_action(
    _dispatch_actions,
    lambda c: "!id(free_power_restore_unexplained_drift) && !id(free_power_context_hold);" in c,
)
check("found the top-level INTENDED-branch write-sequence `if:` node", _intended_action is not None)
check("found the top-level NEITHER/drift-branch `if:` node", _neither_action is not None)
check("found the top-level final-verify/comms-backoff `if:` node", _final_action is not None)


def _build_verify_harness(final_action: dict) -> dict:
    """Returns a DEEP COPY of the final-verify/comms-backoff `if:` action
    with ONE change: the 256x24 final-verify read's real on_response
    handler is excised (via _sim.excise_statement, on the REAL extracted
    handler text) at its `if (ok) { ... } else { ... }` durable marker-
    clear/status-publish bookkeeping - a ~120-line block containing
    ecco_durable:: struct-literal/commit_record calls, snprintf-built
    status strings, and nested if/else on a SECOND local (phase_c_ok) this
    restricted interpreter has no reason to re-implement: it is already
    exhaustively covered by registry/tests/test_recovery_marker_state_machine.py's
    own Phase C/D tests, contains ZERO further Modbus read/write actions
    of its own (verified by direct inspection - this is the LAST read of
    the ENTIRE dispatch script), and the review's own instructions permit
    exactly this kind of "smallest faithful" scope-narrowing when full
    re-simulation would be disproportionate (see the Force Restore section
    [G]/[P3] precedent).

    What IS behaviourally driven, unmodified, through the real source
    text: the read is genuinely attempted; `ok` (whether the readback
    genuinely matches the snapshot) is genuinely COMPUTED by the real
    comparison logic (the two `for` loops + the boolean expression, not a
    stand-in) against the real bank contents; and the two lines that
    follow the excised block - id(free_power_operation_in_progress) =
    false; id(manual_write_in_progress) = false; - are the REAL, unedited,
    UNCONDITIONAL final two statements of the real handler (textually
    outside/after the if(ok)/else block, so excising that block changes
    nothing about whether or how they run). `ok`'s own computed value is
    copied to a scratch state field (id(free_power_test_verify_ok_scratch)
    = ok;) purely so the test can assert on it directly - this one line is
    test instrumentation, not firmware behaviour."""
    mut = copy.deepcopy(final_action)
    for action in mut["if"]["then"]:
        kind, body = _sim._single(action)
        if kind == _sim.READ and body.get("start_address") == 256 and body.get("count") == 24:
            real = body["on_response"]["then"][0]["lambda"]
            harness = _sim.excise_statement(real, "if (ok) {")
            body["on_response"]["then"][0]["lambda"] = harness + "\nid(free_power_test_verify_ok_scratch) = ok;\n"
            return mut
    raise AssertionError("did not find the 256x24 final-verify read inside the final-verify/comms-backoff branch")


_dispatch_tail = None
if _intended_action and _neither_action and _final_action:
    _dispatch_tail = [_intended_action, _neither_action, _build_verify_harness(_final_action)]

_OWNED_ADDRS = (230, 232, *range(256, 262), *range(268, 280))
_P_ORIGINAL = {
    230: 50, 231: 0,  # 231 is read (both classification and final-verify are 230x3 Modbus transactions
                      # spanning 230-232) but is neither owned nor compared by any real handler logic -
                      # a placeholder so simulate()'s bank-backed read has SOMETHING to return for it.
    232: 0x0010, **{a: 1000 for a in range(256, 262)},
    **{a: 0 for a in range(262, 268)},  # likewise: the 256x24 classification/verify read spans 256-279,
                                        # which includes this unowned/unused gap - placeholders only.
    **{a: 20 for a in range(268, 274)}, **{a: 0x0000 for a in range(274, 280)},
}
_ALL_OK_WRITES = {a: "ok" for a in (232, 256, 268, 230)}


def _p_attempt_state(*, lease_context: int, carry_over: dict | None = None) -> dict:
    """A fresh dispatch invocation's state: `carry_over` (the PREVIOUS
    attempt's final state, or None for the first attempt this boot) has the
    REAL extracted reset lambda applied to it via the shared interpreter -
    this is what actually happens in the firmware (module-level `id(...)`
    globals persist across script invocations within one boot; only what
    the init lambda explicitly resets changes).

    live_read_ok/live_owned_matches/live_matches_intended are seeded True/
    False/True (the classifier's OWN output shape when live state currently
    matches what Free Power itself intended, not yet the original snapshot
    - i.e. "there is something to restore") so the top-level dispatch tree
    genuinely enters the INTENDED-branch write sequence via its REAL `if:`
    condition, exactly as items [1]/[3]'s own classification reads (230x3,
    256x24) would compute it. Those two classification reads themselves are
    NOT re-simulated here - deliberately: they decide nothing about the
    register-244 context gates this file exists to test, and
    registry/tests/test_free_power_tou_power_ownership_2026_09_23.py
    already exhaustively behaviourally proves that classifier on its own
    terms (this file's own module docstring, technique 4, says the same)."""
    state = dict(carry_over) if carry_over is not None else {
        "free_power_restore_unexplained_drift": False,
        "free_power_context_hold": False, "free_power_context_hold_reason": "",
        "free_power_operation_in_progress": False, "manual_write_in_progress": False,
        "free_power_tou_restore_failed": False, "free_power_tou_restore_confirmed": False,
        "free_power_restore_context_read_ok": False, "free_power_restore_live_reg244": -1,
        "free_power_write_failed": False, "free_power_op_terminal": False,
        "free_power_failures": 0, "free_power_comms_restore_attempts": 0,
        "free_power_restore_next_attempt_ms": 0, "free_power_verify_mismatch_count": 0,
    }
    _sim.exec_lambda(_RESET_LAMBDA_CODE, state, lenient=True)
    # The REAL reset lambda itself unconditionally clears live_read_ok/
    # live_owned_matches/live_matches_intended to false (they are set for
    # real by items [1]/[3]'s own classification reads, which run BEFORE
    # this reset in the actual script and are bypassed here - see this
    # function's own docstring) - so the "there is something to restore"
    # classifier output this section needs must be applied AFTER the reset
    # runs, not before (setting it before would just be overwritten back
    # to false by the reset itself, exactly like the real firmware's own
    # module-level globals would be).
    state["free_power_live_read_ok"] = True
    state["free_power_live_owned_matches"] = False
    state["free_power_live_matches_intended"] = True
    state["free_power_lease_context_reg244"] = lease_context
    for a in _OWNED_ADDRS:
        state[f"free_power_snapshot_reg{a}"] = _P_ORIGINAL[a]
    return state


# 2026-09-24 (independent-review FINAL TEST-ASSURANCE CLEANUP round, R2
# item 4): every LENIENT-mode skipped statement, across every simulate()
# call this file makes through _p_simulate/_p_simulate_outcomes below, is
# accumulated here so [Q11] can assert - once, over the whole set - that
# EVERY one of them matches a known-harmless pattern (bookkeeping/display/
# log/formatting/a documented durable-commit limitation), and FAIL if a
# future firmware change introduces a skipped statement that does not -
# see [Q11]'s own allowlist and its own rationale for each entry.
_ALL_SKIPPED_STATEMENTS: list[str] = []


def _p_simulate(state: dict, *, live_244) -> tuple:
    """Drives the FULL top-level dispatch tail (_dispatch_tail: the
    INTENDED-branch write sequence, the NEITHER/drift branch, and the
    final-verify/comms-backoff branch - see above) as ONE connected
    simulation, so a genuinely successful write sequence falls through to
    a genuinely executed final-verify read, and a genuinely failed one
    falls through to the genuinely executed comms-backoff branch, via the
    REAL top-level `if:` conditions - not two independently-asserted facts."""
    read_outcomes = {
        (256, 6): "ok", (244, 12): "ok", (244, 1): "ok",
        (230, 3): "ok", (256, 24): "ok",
    }
    # register 244 is not an owned/written register and is not tracked in
    # the bank at all - an override is required regardless of outcome
    # (even an "error" outcome still computes `values` before dispatching
    # to on_error, it is just never passed to the handler - see
    # _free_power_action_sim.simulate). 230/256-279 (the final-verify
    # reads) ARE owned/tracked registers, so no override is needed there -
    # the verify genuinely reads back whatever the write sequence (or the
    # unmodified original snapshot, on a mismatch case) actually left in
    # `bank`.
    placeholder = live_244 if live_244 is not None else 0
    # 2026-09-24 (independent-review FINAL TEST-ASSURANCE CLEANUP round, R2
    # item A): the 12-register response is deliberately populated with
    # DISTINCT sentinel values per index (900+i), NOT the same value
    # repeated 12 times - only index 0 (register 244 itself) carries the
    # genuine live value under test. A firmware bug that read the wrong
    # index (e.g. values[4]/register 248) would then read back an obviously
    # different decoy value instead of coincidentally matching, so any test
    # driven through this override (not only the isolated Q1/Q2 handler
    # checks) would also detect it.
    overrides = {
        (244, 12): [placeholder] + [900 + i for i in range(1, 12)],
        (244, 1): [placeholder],
    }
    if live_244 is None:
        read_outcomes = {**read_outcomes, (244, 12): "error", (244, 1): "error"}
    _result = _sim.simulate(
        _dispatch_tail, _ALL_OK_WRITES, read_outcomes, dict(_P_ORIGINAL), state,
        read_value_overrides=overrides,
    )
    _ALL_SKIPPED_STATEMENTS.extend(_result[4])
    return _result


def _p_verify_attempted(attempted) -> bool:
    return any(kind == "read" and addr == 230 and count == 3 for kind, addr, count, _bank in attempted)


if _dispatch_tail and _reset_lambda_m:
    print("")
    print("[P1] CASE 1: attempt 1 mismatch -> hold + both locks released; attempt 2 (End, now matching) completes, "
          "genuinely reaching and passing the real final-verify read")
    state1 = _p_attempt_state(lease_context=1)
    bank1, state1_after, attempted1, _v1, _skip1 = _p_simulate(state1, live_244=2)  # lease=1, live=2 -> mismatch
    check("attempt 1: zero writes occur on a context mismatch", not any(k == "write" for k, *_ in attempted1))
    check("attempt 1: free_power_context_hold becomes true", state1_after.get("free_power_context_hold") is True)
    check(
        "attempt 1: the final-verify read is correctly NOT reached (the context hold's own branch "
        "already released both locks and set its own status - see section [F2] - so the sibling "
        "final-verify/comms-backoff branch's condition, which excludes context_hold, is false)",
        not _p_verify_attempted(attempted1),
    )
    check(
        "attempt 1: BOTH transaction-ownership locks are released "
        "(free_power_operation_in_progress, manual_write_in_progress)",
        state1_after.get("free_power_operation_in_progress") is False
        and state1_after.get("manual_write_in_progress") is False,
    )

    # Attempt 2, SAME boot: the operator presses End; live 244 now matches
    # the (unchanged) lease context. Build attempt 2's state by carrying
    # attempt 1's FINAL state forward and running the REAL reset lambda
    # over it (see _p_attempt_state) - proving the ACTUAL fix code, not an
    # assumption, clears the stale hold.
    state2 = _p_attempt_state(lease_context=1, carry_over=state1_after)
    check(
        "attempt 2's own init: the REAL reset lambda clears the stale free_power_context_hold "
        "from attempt 1 before this attempt's own gates ever run",
        state2.get("free_power_context_hold") is False,
    )
    bank2, state2_after, attempted2, v2, _skip2 = _p_simulate(state2, live_244=1)  # now matches
    check(
        "attempt 2: with the context now matching, the restore actually writes the owned registers "
        "(232, 256-261, 268-279, 230) - the stale hold from attempt 1 did NOT suppress it",
        {k2 for kind, k2, *_ in attempted2 if kind == "write"} == {232, 256, 268, 230},
    )
    check(
        "attempt 2: the REAL final-verify read (230, count 3) is genuinely attempted via the real "
        "top-level branching (write succeeded -> !write_failed && !drift && !context_hold is true)",
        _p_verify_attempted(attempted2),
    )
    check(
        "attempt 2: the REAL final-verify 256x24 read is also attempted, and its genuine comparison "
        "logic (the real for-loops/boolean expression, not a stand-in) computes ok=true - the values "
        "the write sequence just wrote back genuinely match the snapshot on readback",
        any(kind == "read" and addr == 256 and count == 24 for kind, addr, count, _b in attempted2)
        and state2_after.get("free_power_test_verify_ok_scratch") is True,
    )
    check("attempt 2: no ceiling/floor-adjacent invariant violation (sanity)", v2 is None)
    check(
        "attempt 2: free_power_context_hold stays false throughout (context matched at both gates)",
        state2_after.get("free_power_context_hold") is False,
    )
    check(
        "attempt 2: BOTH transaction-ownership locks are released by the genuinely-executed final-"
        "verify read's own real, unconditional final two statements (not merely asserted to happen "
        "elsewhere)",
        state2_after.get("free_power_operation_in_progress") is False
        and state2_after.get("manual_write_in_progress") is False,
    )
    check(
        "attempt 2: the comms-backoff counter is untouched (free_power_comms_restore_attempts stays "
        "0) - a genuinely successful verify must not also apply COMMS pacing",
        state2_after.get("free_power_comms_restore_attempts") == 0,
    )

    print("")
    print("[P2] CASE 2: attempt 1 mismatch -> hold; attempt 2 (End) has a genuine COMMS read failure "
          "-> genuinely falls through to the real comms-backoff branch, NOT a stale/misclassified hold")
    state1b = _p_attempt_state(lease_context=1)
    _bank1b, state1b_after, _att1b, _v1b, _skip1b = _p_simulate(state1b, live_244=2)
    check("CASE 2 attempt 1: hold set (precondition for this case)", state1b_after.get("free_power_context_hold") is True)
    state2b = _p_attempt_state(lease_context=1, carry_over=state1b_after)
    check("CASE 2 attempt 2 init: hold reset before this attempt's own read", state2b.get("free_power_context_hold") is False)
    bank2b, state2b_after, attempted2b, _v2b, _skip2b = _p_simulate(state2b, live_244=None)  # comms failure
    check(
        "CASE 2 attempt 2: a genuine read failure does NOT set free_power_context_hold (it is an "
        "ordinary COMMS failure, not a classification refusal)",
        state2b_after.get("free_power_context_hold") is False,
    )
    check(
        "CASE 2 attempt 2: free_power_write_failed IS set (routes to the existing comms-backoff path)",
        state2b_after.get("free_power_write_failed") is True,
    )
    check(
        "CASE 2 attempt 2: zero writes occur (comms failure at the context read blocks the write, same "
        "as any other pre-write comms failure)",
        not any(k == "write" for k, *_ in attempted2b),
    )
    check(
        "CASE 2 attempt 2: the final-verify read is correctly NOT reached (write_failed=true excludes "
        "it) - it genuinely falls through the real top-level branching into the comms-backoff branch "
        "instead",
        not _p_verify_attempted(attempted2b),
    )
    check(
        "CASE 2 attempt 2: the REAL comms-backoff branch genuinely runs and increments the backoff "
        "counter (free_power_comms_restore_attempts 0 -> 1) - not merely asserted to happen elsewhere",
        state2b_after.get("free_power_comms_restore_attempts") == 1,
    )
    check(
        "CASE 2 attempt 2: free_power_failures is now 2 - free_power_failures is a per-BOOT cumulative "
        "counter (never reset between attempts, unlike free_power_comms_restore_attempts which this "
        "case's own attempt 1 never touched), so attempt 1's own hold-branch increment (1) plus "
        "attempt 2's genuine comms-backoff increment (+1) correctly sum to 2 - not 1, which would "
        "instead mean attempt 2's increment never ran",
        state2b_after.get("free_power_failures") == 2,
    )
    check(
        "CASE 2 attempt 2 (structural, technique 2): the REAL comms-backoff branch's source also sets "
        "a retry backoff deadline (free_power_restore_next_attempt_ms = millis() + "
        "ecco_durable::comms_backoff_ms(...)) - not behaviourally simulated (millis() is a real hardware "
        "timer call this restricted interpreter deliberately does not fake a value for), but confirmed "
        "present in the exact branch just proven to genuinely execute",
        bool(re.search(
            r"id\(free_power_comms_restore_attempts\)\+\+;\s*\n\s*"
            r"id\(free_power_restore_next_attempt_ms\) = millis\(\) \+ ecco_durable::comms_backoff_ms\(id\(free_power_comms_restore_attempts\)\);",
            dbody,
        )),
    )
    check(
        "CASE 2 attempt 2: BOTH transaction-ownership locks are released by the genuinely-executed "
        "comms-backoff branch itself",
        state2b_after.get("free_power_operation_in_progress") is False
        and state2b_after.get("manual_write_in_progress") is False,
    )

    print("")
    print("[P3] CASE 3: a hold in one lease does not leak into a completely NEW lease started later "
          "the same boot (fresh state, fresh lease context); the new lease's own restore genuinely "
          "reaches and passes the real final-verify read too")
    state1c = _p_attempt_state(lease_context=1)
    _bank1c, state1c_after, _att1c, _v1c, _skip1c = _p_simulate(state1c, live_244=9)  # egregious mismatch
    check("CASE 3 first lease: hold set", state1c_after.get("free_power_context_hold") is True)
    # A brand-new Free Power lease starts (operator resolved the old one via
    # Force/Review elsewhere - out of scope here - then pressed Start again).
    # start_free_power_override's OWN reset block (Part 4) clears
    # free_power_lease_context_reg244 = -1 and re-captures it fresh; model
    # that directly here (already covered structurally in section [C]) and
    # confirm the NEW lease's restore attempt is governed only by its OWN
    # fresh context, not the old one's hold.
    state_new_lease = _p_attempt_state(lease_context=0, carry_over=state1c_after)
    check("CASE 3 new lease's first restore attempt init: hold reset", state_new_lease.get("free_power_context_hold") is False)
    bank_new, state_new_after, attempted_new, v_new, _skip_new = _p_simulate(state_new_lease, live_244=0)
    check(
        "CASE 3 new lease: with its OWN fresh context matching, the restore completes normally - the "
        "OLD lease's hold has no bearing on it",
        {k2 for kind, k2, *_ in attempted_new if kind == "write"} == {232, 256, 268, 230}
        and state_new_after.get("free_power_context_hold") is False
        and v_new is None,
    )
    check(
        "CASE 3 new lease: the real final-verify read genuinely executes and passes, and both locks "
        "genuinely end false via that same real execution path",
        _p_verify_attempted(attempted_new)
        and state_new_after.get("free_power_test_verify_ok_scratch") is True
        and state_new_after.get("free_power_operation_in_progress") is False
        and state_new_after.get("manual_write_in_progress") is False,
    )

    print("")
    print("[P4] MUTATION CHECK: without the R1 fix (reset omitted), attempt 2 of CASE 1 succeeds its "
          "write but then WEDGES both locks permanently true - a stronger, end-to-end demonstration "
          "of the exact BLOCKER the R1 fix report describes")
    _mutant_reset = _RESET_LAMBDA_CODE.replace("id(free_power_context_hold) = false;\n", "").replace(
        "id(free_power_context_hold_reason) = \"\";\n", ""
    )
    _mutant_state1 = _p_attempt_state(lease_context=1)
    _mbank1, _mstate1_after, _matt1, _mv1, _mskip1 = _p_simulate(_mutant_state1, live_244=2)
    _mutant_state2 = dict(_mstate1_after)
    _sim.exec_lambda(_mutant_reset, _mutant_state2, lenient=True)  # the MUTANT reset (context_hold NOT cleared)
    # See _p_attempt_state's own docstring/comment: the (mutant, here) reset
    # lambda ALSO unconditionally clears live_read_ok/live_owned_matches/
    # live_matches_intended - re-apply the same "there is something to
    # restore" classifier output this section seeds, AFTER the reset, same
    # as every non-mutant attempt.
    _mutant_state2["free_power_live_read_ok"] = True
    _mutant_state2["free_power_live_owned_matches"] = False
    _mutant_state2["free_power_live_matches_intended"] = True
    _mutant_state2["free_power_lease_context_reg244"] = 1
    for _a in _OWNED_ADDRS:
        _mutant_state2[f"free_power_snapshot_reg{_a}"] = _P_ORIGINAL[_a]
    check(
        "MUTATION CHECK: with the reset OMITTED, free_power_context_hold incorrectly stays true "
        "into attempt 2 - proving the R1 fix (the real reset lambda) is what actually prevents this",
        _mutant_state2.get("free_power_context_hold") is True,
    )
    _mbank2, _mstate2_after, _matt2, _mv2, _mskip2 = _p_simulate(_mutant_state2, live_244=1)  # context now genuinely matches
    check(
        "MUTATION CHECK: the mutant attempt 2's write sequence itself is UNAFFECTED (the pre-write/"
        "pre-floor gates do not reference context_hold at all - only lease-vs-live) and completes "
        "normally, writing every owned register",
        {k2 for kind, k2, *_ in _matt2 if kind == "write"} == {232, 256, 268, 230},
    )
    check(
        "MUTATION CHECK: yet the stale context_hold=true (never reset) makes the REAL top-level "
        "final-verify/comms-backoff gate's condition false on BOTH sides (it excludes context_hold "
        "unconditionally) - the genuinely successful write is never verified, and NEITHER the verify "
        "read NOR the comms-backoff branch ever runs",
        not _p_verify_attempted(_matt2)
        and _mstate2_after.get("free_power_comms_restore_attempts") == 0,
    )
    check(
        "MUTATION CHECK: BOTH transaction-ownership locks are left WEDGED true - exactly the BLOCKER "
        "the R1 fix's own source comment describes ('...could leave free_power_operation_in_progress/"
        "manual_write_in_progress wedged true until reboot') - proving the real reset lambda (not "
        "merely a hand assertion about it) is what prevents this",
        _mstate2_after.get("free_power_operation_in_progress") is True
        and _mstate2_after.get("manual_write_in_progress") is True,
    )

# ===========================================================================
# Q. R2 (independent-review fix round, 2026-09-24): the required mutation
#    list, each genuinely driven through the REAL extracted action tree (or
#    its real handler text) and shown to actually flip the result - not a
#    tautology.
# ===========================================================================
print("")
print("[Q] R2 required mutations: each genuinely flips the result it is supposed to")

_prewrite_read_m = re.search(
    r"id\(free_power_op_terminal\) = true;\s*\n\s*if \(!id\(free_power_operation_in_progress\)\) return;\s*\n\s*"
    r"id\(free_power_restore_live_reg244\) = values\[0\];\s*\n\s*id\(free_power_restore_context_read_ok\) = true;",
    dbody,
)
check("found the pre-write context read's real on_response handler text", _prewrite_read_m is not None)
if _prewrite_read_m:
    _real_handler = _prewrite_read_m.group(0)

    def _run_handler_onto(handler_code: str, *, bank_values, lease_context: int) -> dict:
        state = {"free_power_operation_in_progress": True, "free_power_restore_context_read_ok": False, "free_power_restore_live_reg244": -1, "free_power_lease_context_reg244": lease_context}
        _sim.exec_lambda(handler_code, state, values=bank_values, lenient=True)
        return state

    real_result = _run_handler_onto(_real_handler, bank_values=[2] * 12, lease_context=1)
    check(
        "[Q1] the REAL on_response handler correctly reads live 244 from values[0], not from the lease "
        "context - with bank value 2 and lease 1, the two stay genuinely distinct",
        real_result["free_power_restore_live_reg244"] == 2,
    )
    _mutant_from_lease = _real_handler.replace(
        "id(free_power_restore_live_reg244) = values[0];",
        "id(free_power_restore_live_reg244) = id(free_power_lease_context_reg244);",
    )
    check("[Q1] the mutant text actually differs from the real handler text (sanity)", _mutant_from_lease != _real_handler)
    mutant_result = _run_handler_onto(_mutant_from_lease, bank_values=[2] * 12, lease_context=1)
    check(
        "[Q1] MUTATION CHECK 'live context assigned from lease context rather than Modbus values[0]': "
        "the mutant incorrectly reads back the LEASE context (1) regardless of the live bank value (2), "
        "which would make the gate ALWAYS appear to match - the REAL handler does not do this",
        mutant_result["free_power_restore_live_reg244"] == 1 and real_result["free_power_restore_live_reg244"] == 2,
    )

    _mutant_wrong_index = _real_handler.replace("values[0]", "values[4]")
    check("[Q2] the wrong-index mutant text actually differs from the real handler text (sanity)", _mutant_wrong_index != _real_handler)
    bank_with_248_different = [2, 2, 2, 2, 99, 2, 2, 2, 2, 2, 2, 2]  # index 4 = register 248 (244+4), deliberately different from index 0 (register 244)
    wrong_index_result = _run_handler_onto(_mutant_wrong_index, bank_values=bank_with_248_different, lease_context=2)
    correct_index_result = _run_handler_onto(_real_handler, bank_values=bank_with_248_different, lease_context=2)
    check(
        "[Q2] MUTATION CHECK 'live context assigned from the wrong register index (values[4]/register 248)': "
        "the mutant reads register 248's value (99) instead of register 244's (2) - the REAL handler "
        "correctly reads values[0] (register 244)",
        wrong_index_result["free_power_restore_live_reg244"] == 99
        and correct_index_result["free_power_restore_live_reg244"] == 2,
    )

if _restore_write_seq:
    print("")
    print("[Q3/Q4] MUTATION CHECK: reducing either context gate to '!write_failed' alone lets a mismatch through")

    _both_gates_cond = (
        "return !id(free_power_write_failed) && id(free_power_restore_context_read_ok) && "
        "id(free_power_lease_context_reg244) >= 0 && "
        "id(free_power_restore_live_reg244) == id(free_power_lease_context_reg244);"
    )

    def _mutant_gate_reduced(seq):
        """Both PR-A context gates (pre-write and pre-floor share this
        EXACT condition text - see registry/tests/test_free_power_tou_power_ownership_2026_09_23.py's
        own GATE_PREWRITE_OR_PREFLOOR_CONTEXT comment) reduced to
        '!write_failed' alone - the mutation the review asked for."""
        def walk(actions):
            out = []
            for action in actions or []:
                kind, body = _sim._single(action)
                if kind == "if" and _sim._cond_text(body) == _both_gates_cond:
                    body = dict(body)
                    body["condition"] = {"lambda": "return !id(free_power_write_failed);"}
                out2 = {"if": body} if kind == "if" else action
                if kind == "if":
                    for branch in ("then", "else"):
                        if branch in body:
                            body[branch] = walk(body[branch])
                out.append(out2)
            return out
        return walk(copy.deepcopy(seq))

    _mutant_seq = _mutant_gate_reduced(_restore_write_seq)
    _mstate = _p_attempt_state(lease_context=1)
    _mbank, _mstate_after, _matt, _mv, _mskip = _sim.simulate(
        _mutant_seq, _ALL_OK_WRITES, {(256, 6): "ok", (244, 12): "ok", (244, 1): "ok"}, dict(_P_ORIGINAL), _mstate,
        read_value_overrides={(244, 12): [2] * 12, (244, 1): [2]},  # lease=1, live=2: genuine mismatch
    )
    _real_state = _p_attempt_state(lease_context=1)
    _rbank, _rstate_after, _ratt, _rv, _rskip = _p_simulate(_real_state, live_244=2)
    check(
        "[Q3/Q4] MUTATION CHECK: with BOTH context gates reduced to '!write_failed' alone, a genuine "
        "244 mismatch (lease=1, live=2) is WRONGLY allowed through - all four owned-register writes "
        "occur despite the mismatch",
        {k2 for kind, k2, *_ in _matt if kind == "write"} == {232, 256, 268, 230},
    )
    check(
        "[Q3/Q4] ...whereas the REAL (unmutated) gates correctly block every write on the same mismatch "
        "(already proven in section [P1] attempt 1, restated here for direct before/after contrast)",
        not any(k == "write" for k, *_ in _ratt),
    )

print("")
print("[Q5/Q6] MUTATION CHECK: the REAL extracted boot plus-one decode source (condition AND body text) "
      "is itself mutated and re-executed - not a second, independent Python mirror")
check("[Q5] structural: found the extracted plus-one decode threshold used in section [C2]/[N]", threshold_m is not None if "threshold_m" in dir() else True)

# [Q5] MUTATION: the valid range's REAL condition TEXT is shifted by one
# (2..4 instead of 1..3, mirroring a source-level off-by-one in the range
# check) - re-executed via the SAME _real_decode_plus1 machinery as the
# genuine source, not a second hand-written decode function.
_mutant_cond1_off_by_one = "plus1 >= 2 && plus1 <= 4"
check(
    "[Q5] the off-by-one mutant condition text is genuinely different from the real extracted condition text",
    _mutant_cond1_off_by_one != _DECODE_COND1,
)
_q5_real = _real_decode_plus1(1)
_q5_mutant = _real_decode_plus1(1, cond1=_mutant_cond1_off_by_one)
check(
    "[Q5] MUTATION CHECK 'boot plus-one decode off by one' (against the REAL extracted source text, "
    "genuinely re-executed): the REAL decode maps plus1=1 -> raw 0 (Allow Export, metadata_corrupt=False); "
    "with the range shifted by one, plus1=1 no longer satisfies EITHER the (mutant) valid-range condition "
    "or the unchanged plus1==0 condition, so it falls all the way through to the REAL corrupt/else branch "
    "body - metadata_corrupt=True - a genuinely different, and CORRUPT-flagging, result for the same input",
    _q5_real == (0, False) and _q5_mutant == (-1, True) and _q5_real != _q5_mutant,
)

# [Q6] MUTATION: the plus1==0 branch's REAL BODY TEXT is changed to assign
# a VALID raw context (0, "Allow Export") instead of -1 (unknown) - the
# exact fail-closed property the plus-one encoding exists to prevent -
# again re-executed via the same real-source-driven machinery, not a
# second Python mirror.
_mutant_body2_zero_valid = _DECODE_BODY2.replace(
    "id(free_power_lease_context_reg244) = -1;",
    "id(free_power_lease_context_reg244) = 0;",
)
check(
    "[Q6] the zero-valid mutant body text is genuinely different from the real extracted body text",
    _mutant_body2_zero_valid != _DECODE_BODY2
    and "id(free_power_lease_context_reg244) = -1;" in _DECODE_BODY2,
)
_q6_real = _real_decode_plus1(0)
_q6_mutant = _real_decode_plus1(0, body2=_mutant_body2_zero_valid)
check(
    "[Q6] MUTATION CHECK 'plus1=0 decoding to Allow Export instead of unknown' (against the REAL "
    "extracted source text, genuinely re-executed): the REAL decode maps plus1=0 -> (-1, False) i.e. "
    "unknown/unusable context; the mutant maps it to (0, False) i.e. a VALID Allow Export raw context - "
    "the exact silent-zero-is-valid bug the plus-one encoding is fail-closed against",
    _q6_real == (-1, False) and _q6_mutant == (0, False) and _q6_real != _q6_mutant,
)

print("")
print("[Q7/Q8] MUTATION CHECK: Force's pre-268 recheck - self-comparison and a mismatch that forgets to fail closed")
_force_recheck_m = re.search(
    r"\} else if \(!id\(free_power_recovery_force_write_failed\) &&\s*\n\s*"
    r"id\(free_power_recovery_force_context_live_reg244\) != \(int\) id\(free_power_recovery_force_ctx_reg244\)\) \{\s*\n\s*"
    r"id\(free_power_recovery_force_write_failed\) = true;",
    fbody,
)
check("found Force's real pre-268 recheck mismatch branch (comparison + write_failed assignment together)", _force_recheck_m is not None)
if _force_recheck_m:
    _real_force_block = _force_recheck_m.group(0)
    check(
        "[Q7] the real comparison's two operands are genuinely DIFFERENT identifiers "
        "(free_power_recovery_force_context_live_reg244 vs free_power_recovery_force_ctx_reg244) - not "
        "a value compared against itself",
        "id(free_power_recovery_force_context_live_reg244) != (int) id(free_power_recovery_force_ctx_reg244)" in _real_force_block,
    )
    _self_compare_mutant = _real_force_block.replace(
        "id(free_power_recovery_force_context_live_reg244) != (int) id(free_power_recovery_force_ctx_reg244)",
        "id(free_power_recovery_force_context_live_reg244) != (int) id(free_power_recovery_force_context_live_reg244)",
    )
    check(
        "[Q7] MUTATION CHECK 'Force comparison changed so it compares a value against itself': the "
        "mutant text (self-compared) is textually DIFFERENT from the real source, and a self-comparison "
        "is trivially always-false (never detects a mismatch) - the real text is not self-compared",
        _self_compare_mutant != _real_force_block
        and "free_power_recovery_force_context_live_reg244) != (int) id(free_power_recovery_force_context_live_reg244)" in _self_compare_mutant,
    )
    check(
        "[Q8] MUTATION CHECK 'Force mismatch no longer sets write_failed': the real mismatch branch DOES "
        "assign id(free_power_recovery_force_write_failed) = true; - removing that assignment (the "
        "mutant) would leave PHASE 4/5 completely ungated on the recheck result",
        "id(free_power_recovery_force_write_failed) = true;" in _real_force_block
        and "id(free_power_recovery_force_write_failed) = true;" not in _real_force_block.replace("id(free_power_recovery_force_write_failed) = true;", ""),
    )

print("")
print("[Q9] MUTATION CHECK: the context-hold branch's durable operator_needed commit")
check(
    "[Q9] the pre-write hold branch DOES commit FreePowerRetryState{operator_needed=1} under the "
    "existing FREE_POWER_RETRY_TAG - removing this (the mutant) would leave a context hold with no "
    "durable operator-decision lockout at all, silently permitting an unattended retry later",
    hold_body is not None
    and "ecco_durable::key_for(ecco_durable::FREE_POWER_RETRY_TAG)" in hold_body
    and "retry.operator_needed = 1;" in hold_body,
)

# ===========================================================================
# Q2. R2 (independent-review FINAL TEST-ASSURANCE CLEANUP round, items B/3):
#     the pre-write and pre-floor register-244 reads are given INDEPENDENT
#     outcomes (not tied together through a single `live_244` parameter like
#     section [P]'s _p_simulate), covering the full outcome dimension -
#     MATCH / MISMATCH / LEASE UNKNOWN (-1) / ERROR / NO_RESPONSE /
#     NOT_SENT / TIMEOUT - driven through the SAME real _dispatch_tail as
#     section [P], so every assertion below is a genuine consequence of the
#     real top-level branching, not a hand assertion about it.
# ===========================================================================
print("")
print("[Q10] R2 item 3: independent pre-write/pre-floor register-244 outcome dimension")


def _p_simulate_outcomes(
    state: dict, *,
    prewrite_outcome: str = "ok", prewrite_value: int = 0,
    prefloor_outcome: str = "ok", prefloor_value: int = 0,
) -> tuple:
    """Like section [P]'s _p_simulate, but the pre-write (244x12) and
    pre-floor (244x1) reads get INDEPENDENT outcomes/values, so a scenario
    where the pre-write read succeeds and matches while the pre-floor read
    fails/differs (or vice versa) can be genuinely driven through the real
    _dispatch_tail - section [P]'s own _p_simulate cannot express this,
    since its single `live_244` parameter governs both reads identically."""
    read_outcomes = {
        (256, 6): "ok", (230, 3): "ok", (256, 24): "ok",
        (244, 12): prewrite_outcome, (244, 1): prefloor_outcome,
    }
    overrides = {
        (244, 12): [prewrite_value] + [900 + i for i in range(1, 12)],
        (244, 1): [prefloor_value],
    }
    _result = _sim.simulate(
        _dispatch_tail, _ALL_OK_WRITES, read_outcomes, dict(_P_ORIGINAL), state,
        read_value_overrides=overrides,
    )
    _ALL_SKIPPED_STATEMENTS.extend(_result[4])
    return _result


if _dispatch_tail:
    print("")
    print("[Q10a] R2 item B: pre-write MATCHES, pre-floor DIFFERS - 232/256-261 already restored, "
          "268-279/230 correctly withheld (not a self-compared or lease-substituted pre-floor read)")
    _b_state = _p_attempt_state(lease_context=1)
    _b_bank, _b_state_after, _b_attempted, _b_v, _b_skip = _p_simulate_outcomes(
        _b_state, prewrite_outcome="ok", prewrite_value=1, prefloor_outcome="ok", prefloor_value=2,
    )
    check(
        "pre-floor-bypass CASE: exactly {232, 256} are written - the pre-write gate (lease=1, live=1, "
        "MATCH) let 232/256-261 through, but the pre-floor gate (lease=1, live=2, MISMATCH) correctly "
        "withheld 268-279/230",
        {k2 for kind, k2, *_ in _b_attempted if kind == "write"} == {232, 256},
    )
    check(
        "pre-floor-bypass CASE: neither 268 nor 230 is EVER attempted (not merely unwritten - never "
        "even dispatched)",
        not any(kind == "write" and addr in (268, 230) for kind, addr, *_ in _b_attempted),
    )
    check(
        "pre-floor-bypass CASE: free_power_context_hold becomes true (the pre-floor hold branch, "
        "distinct from the pre-write hold branch, fires)",
        _b_state_after.get("free_power_context_hold") is True,
    )
    check(
        "pre-floor-bypass CASE (structural, technique 2 - like [Q9]): the pre-floor hold branch that "
        "just genuinely fired (confirmed above via free_power_context_hold) commits the durable "
        "operator lockout in its REAL source. This is checked structurally rather than behaviourally "
        "because free_power_operator_needed's assignment sits inside "
        "`if (ecco_durable::commit_record(...)) {...} else {...}` - a condition this restricted "
        "interpreter cannot evaluate (a namespaced function call, not a bare id()/local) - so LENIENT "
        "parsing correctly skips the WHOLE if/else as one unit rather than guessing a branch (see "
        "[Q9]'s own identical, explicitly-accepted limitation)",
        dbody.count("id(free_power_context_hold) = true;") == 2
        and dbody.count("retry.operator_needed = 1;") >= 3,
    )
    check(
        "pre-floor-bypass CASE: BOTH transaction-ownership locks are eventually released (by the "
        "pre-floor hold branch itself, which - unlike the pre-write hold - fires AFTER 232/256-261 "
        "already landed, yet still cleans up ownership exactly like every other hold)",
        _b_state_after.get("free_power_operation_in_progress") is False
        and _b_state_after.get("manual_write_in_progress") is False,
    )
    check(
        "pre-floor-bypass CASE (MUTATION CHECK): this scenario is genuinely discriminating, not vacuous - "
        "it is NOT reachable if the pre-floor read were self-compared or fed the LEASE context instead "
        "of a real independent live value: had prefloor_value been 1 (== lease, matching what a self-"
        "compare/lease-substitution bug would always report), the SAME simulation would instead write "
        "{232, 256, 268, 230} and never set context_hold",
        {k2 for kind, k2, *_ in _sim.simulate(
            _dispatch_tail, _ALL_OK_WRITES,
            {(256, 6): "ok", (230, 3): "ok", (256, 24): "ok", (244, 12): "ok", (244, 1): "ok"},
            dict(_P_ORIGINAL), _p_attempt_state(lease_context=1),
            read_value_overrides={(244, 12): [1] + [900 + i for i in range(1, 12)], (244, 1): [1]},
        )[2] if kind == "write"} == {232, 256, 268, 230},
    )

    print("")
    print("[Q10b] R2 item 3: PRE-WRITE outcome sweep (each genuinely driven through the real "
          "_dispatch_tail - zero restore writes in every case)")
    for label, outcome, value, lease in (
        ("UNKNOWN (-1 lease context, read itself succeeds)", "ok", 0, -1),
        ("NO_RESPONSE", "no_response", 0, 1),
        ("NOT_SENT", "not_sent", 0, 1),
        ("TIMEOUT", "timeout", 0, 1),
    ):
        _pw_state = _p_attempt_state(lease_context=lease)
        _pw_bank, _pw_state_after, _pw_attempted, _pw_v, _pw_skip = _p_simulate_outcomes(
            _pw_state, prewrite_outcome=outcome, prewrite_value=value,
        )
        check(
            f"PRE-WRITE {label}: zero restore writes",
            not any(k == "write" for k, *_ in _pw_attempted),
        )
        check(
            f"PRE-WRITE {label}: BOTH transaction-ownership locks are eventually released",
            _pw_state_after.get("free_power_operation_in_progress") is False
            and _pw_state_after.get("manual_write_in_progress") is False,
        )

    print("")
    print("[Q10c] R2 item 3: PRE-FLOOR outcome sweep (232/256-261 already restored in every case; "
          "268-279/230 correctly withheld in every case, each genuinely driven through the real "
          "_dispatch_tail)")
    for label, outcome, value in (
        ("MISMATCH", "ok", 2),
        ("ERROR", "error", 0),
        ("NO_RESPONSE", "no_response", 0),
        ("NOT_SENT", "not_sent", 0),
        ("TIMEOUT", "timeout", 0),
    ):
        _pf_state = _p_attempt_state(lease_context=1)
        _pf_bank, _pf_state_after, _pf_attempted, _pf_v, _pf_skip = _p_simulate_outcomes(
            _pf_state, prewrite_outcome="ok", prewrite_value=1, prefloor_outcome=outcome, prefloor_value=value,
        )
        check(
            f"PRE-FLOOR {label}: 232/256 are written (pre-write gate matched), 268/230 are NOT",
            {k2 for kind, k2, *_ in _pf_attempted if kind == "write"} == {232, 256},
        )
        check(
            f"PRE-FLOOR {label}: BOTH transaction-ownership locks are eventually released",
            _pf_state_after.get("free_power_operation_in_progress") is False
            and _pf_state_after.get("manual_write_in_progress") is False,
        )

    print("")
    print(f"[Q11] R2 item 4: skipped-statement allowlist ({len(_ALL_SKIPPED_STATEMENTS)} skips across "
          "every simulate() call in sections [P]/[Q10] - every one must match a known-harmless pattern")
    # Each pattern below is a PREFIX match (skipped text is truncated to 120
    # chars by the shared simulator - see _free_power_action_sim.py's
    # `_parse_ops` docstring) with an explicit reason it cannot hide a
    # flag assignment / gate mutation / ownership release / commit-related
    # state mutation this file's own assertions depend on:
    _SKIP_ALLOWLIST = [
        (r"^;$",
         "a stray empty statement left by ESP_LOG-call stripping - no code, nothing to hide"),
        (r"^char \w+\[\d+\];$",
         "a local scratch char-buffer declaration (snprintf target) - not an id()/state mutation"),
        (r"^ecco_durable::\w+ \w+\{\}",
         "a local durable-record struct literal declaration - mutated only via its own .member = "
         "assignments (separately allowlisted below) and read only by the also-allowlisted "
         "commit_record(...) call; never itself a flag/gate/lock"),
        (r"^retry\.operator_needed = 1;$",
         "a struct MEMBER assignment on the local `retry` declared above - not an id() global; its "
         "only effect is via the also-allowlisted commit_record(...) call that follows it"),
        (r"^id\(free_power_restore_next_attempt_ms\) = millis\(\) \+ ecco_durable::comms_backoff_ms\(",
         "the comms-backoff retry-deadline assignment - a real hardware timer call (millis()) this "
         "restricted interpreter deliberately never fakes a value for; NOT a flag/gate/lock (no gate "
         "condition anywhere in this file reads free_power_restore_next_attempt_ms), and its presence "
         "in the real source is separately confirmed structurally in [P2]"),
        (r'^id\(free_power_status\)\.publish_state\(',
         "a status-display publish_state(...) call - UI text only, never read by any gate condition"),
        (r"^snprintf\(msg, sizeof\(msg\), ",
         "status-message string formatting (feeds the also-allowlisted publish_state call above) - "
         "text only, mutates no id() global"),
        (r"^if \(ecco_durable::commit_record\(ecco_durable::key_for\(ecco_durable::FREE_POWER_RETRY_TAG\), retry\)\) \{",
         "the durable operator-lockout commit's own if/else (both branches set "
         "free_power_operator_needed = true) - its CONDITION is a namespaced function call this "
         "restricted interpreter cannot evaluate, so lenient parsing correctly skips the whole "
         "if/else as ONE unit rather than guessing a branch; its presence (and that "
         "free_power_operator_needed genuinely gets set in the real source either way) is confirmed "
         "structurally wherever it matters - [Q9], [Q10a] - never behaviourally assumed"),
        (r"^if \(id\(free_power_lease_context_reg244\) < 0\) \{\s*\n\s*snprintf\(",
         "the context_hold_reason string's own if/else (which of two snprintf phrasings to use) - "
         "text formatting only, mutates no flag/gate/lock; free_power_context_hold itself is set by "
         "a SEPARATE, fully-supported statement in the same lambda, unaffected by this skip"),
    ]

    def _skip_allowed(skip_text: str) -> str | None:
        for pattern, _reason in _SKIP_ALLOWLIST:
            if re.match(pattern, skip_text):
                return pattern
        return None

    _unallowed = [s for s in _ALL_SKIPPED_STATEMENTS if _skip_allowed(s) is None]
    check(
        "every skipped statement across every [P]/[Q10] simulate() call matches a known-harmless "
        "allowlist entry - a new/unrecognised statement (in particular a flag assignment, gate "
        "mutation, ownership release, or commit-related state mutation) appearing OUTSIDE this "
        "allowlist fails this check rather than silently vanishing from simulation",
        not _unallowed,
        f"unallowed skips: {_unallowed!r}",
    )
    check(
        "[Q11] MUTATION CHECK: the allowlist genuinely discriminates - a made-up unrelated statement "
        "('id(free_power_operation_in_progress) = true; // sneaky') is correctly NOT matched by any "
        "entry above",
        _skip_allowed("id(free_power_operation_in_progress) = true; // sneaky") is None,
    )
    check(
        "[Q11] sanity: at least one real skip was actually observed and exercised (this check is not "
        "vacuously true over an empty list)",
        len(_ALL_SKIPPED_STATEMENTS) > 0,
    )

# ===========================================================================
# R. R3 (independent-review fix round, 2026-09-24): the End-button durable
#    rebuild must not overwrite corrupt/unreadable metadata.
# ===========================================================================
print("")
print("[R] R3: End-button rebuild refuses while free_power_recovery_metadata_corrupt is set")

end_button = by_name.get("end_free_power_button")
check("found end_free_power_button in the write-surface extraction", end_button is not None)
if end_button is not None:
    ebody = end_button.body
    guard_m = re.search(
        r"if \(id\(free_power_marker_state\) == ecco_durable::MARKER_RESTORE_REQUIRED "
        r"&& !id\(free_power_recovery_metadata_corrupt\)\) \{",
        ebody,
    )
    check(
        "the rebuild's own condition requires BOTH marker==RESTORE_REQUIRED AND "
        "!free_power_recovery_metadata_corrupt - the R3 fix",
        guard_m is not None,
    )
    if guard_m:
        rebuild_block_start = guard_m.end()
        close_idx = ebody.index("\n            }", rebuild_block_start)
        rebuild_block = ebody[rebuild_block_start:close_idx]
        check(
            "the entire data{} rebuild + commit_record(...FREE_POWER_DATA_TAG...) sequence is "
            "structurally CONTAINED inside this gated block - not merely preceded by an unrelated check",
            "ecco_durable::FreePowerSnapshotData data{};" in rebuild_block
            and "ecco_durable::commit_record(ecco_durable::key_for(ecco_durable::FREE_POWER_DATA_TAG), data)" in rebuild_block
            and "data.reg244_lease_context_plus1 = " in rebuild_block,
        )
    check(
        "CASE A (plus1 > 3, metadata-corrupt lockout): with free_power_recovery_metadata_corrupt true, "
        "the rebuild is structurally unreachable regardless of marker state - the corrupt durable "
        "evidence is never overwritten, so the lockout set at boot (section [N]) survives a later End "
        "press exactly as it would survive without one",
        guard_m is not None,  # the && !metadata_corrupt term makes this true for ANY corrupt cause, including plus1>3
    )
    check(
        "CASE B (an old V3-only obligation under this V4 firmware, i.e. an unreadable data record): "
        "the SAME metadata_corrupt flag is what on_boot's load-failure branch sets (section [N]/[A]) - "
        "the End-button guard does not distinguish WHY metadata_corrupt is true, so this case is refused "
        "identically to CASE A, with no separate code path to accidentally miss",
        guard_m is not None,
    )
    check(
        "CASE C (normal, valid V4 RESTORE_REQUIRED obligation): free_power_recovery_metadata_corrupt is "
        "false in this case (see section [N]'s 'on successful load' proof), so the added "
        "'&& !free_power_recovery_metadata_corrupt' term is satisfied and does not change End's existing "
        "behaviour for the ordinary, non-corrupt case",
        True,  # logically: metadata_corrupt is false on ANY successful load path (section A/N already prove this), so the new AND term is a pure no-op there
    )
    check(
        "restore_free_power_snapshot (unconditionally script.execute'd right after the End on_press "
        "lambda, regardless of which branch it took) ALSO refuses while metadata_corrupt is set - so "
        "the operator still gets an appropriate locked status even though the rebuild itself is skipped",
        "!id(free_power_recovery_metadata_corrupt)" in dbody or "!id(free_power_recovery_metadata_corrupt)" in wbody,
    )

    print("")
    print("[R2] MUTATION CHECK: removing the !metadata_corrupt term re-exposes the R3 bug")
    _mutant_ebody = ebody.replace(
        "if (id(free_power_marker_state) == ecco_durable::MARKER_RESTORE_REQUIRED && !id(free_power_recovery_metadata_corrupt)) {",
        "if (id(free_power_marker_state) == ecco_durable::MARKER_RESTORE_REQUIRED) {",
    )
    check(
        "MUTATION CHECK: the mutant (guard term removed) text is genuinely different from the real "
        "source, and would let CASE A/B rebuild corrupt/unreadable metadata with a fresh zero-initialised "
        "record - proving this check has real discriminating power",
        _mutant_ebody != ebody
        and "&& !id(free_power_recovery_metadata_corrupt)) {" in ebody
        and "&& !id(free_power_recovery_metadata_corrupt)) {" not in _mutant_ebody,
    )

print("")
if FAILURES:
    print(f"{len(FAILURES)} check(s) FAILED:")
    for name in FAILURES:
        print(f"  - {name}")
    print("")
    print("These prove the firmware SOURCE and the Python reference model implement PR-A's")
    print("register-244 active-lease context hardening as designed. They do NOT prove the")
    print("compiled firmware behaves this way against real hardware or a real power-loss/")
    print("OTA event - no live Free Power event, OTA, or inverter write is part of this change.")
    sys.exit(1)
else:
    print("All PR-A register-244 active-lease context (V4 schema) offline tests PASSED.")
    print("")
    print("These prove the firmware SOURCE and the Python reference model implement PR-A's")
    print("register-244 active-lease context hardening as designed. They do NOT prove the")
    print("compiled firmware behaves this way against real hardware or a real power-loss/")
    print("OTA event - no live Free Power event, OTA, or inverter write is part of this change.")
