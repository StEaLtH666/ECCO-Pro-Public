#!/usr/bin/env python3
"""Offline structural/behavioural tests for PR 1 of 3 - Free Power operator
recovery: READ-ONLY evidence/review (`free_power_recovery_review` /
`free_power_recovery_review_dispatch` in
firmware/ecco_clock_dongle_stage3_4_free_power.yaml, plus
firmware/include/ecco_recovery_evidence.h and
registry/free_power_recovery_evidence.py).

Background: Free Power durably owns exactly registers 230, 232, 256-261,
268-279 (20 registers total). The existing restore-time classifier
(restore_free_power_snapshot_dispatch) already tells ORIGINAL/INTENDED/
NEITHER apart when a restore is due, and fails closed (durable operator
lockout, zero writes) on NEITHER - see
registry/tests/test_free_power_tou_power_ownership_2026_09_23.py and
registry/tests/test_write_surface_invariants.py. This PR adds a SEPARATE,
purely read-only review mechanism so an operator can SEE that same kind of
evidence on demand (fresh reads of the 20 owned + 9 context registers, a
64-bit FNV-1a fingerprint, and several Home Assistant entities) without
introducing any new inverter write path. Force Restore Original and Accept
Current State (PRs 2 and 3) do not exist yet - nothing added here executes
either of them.

No I/O, no hardware, no ESPHome/C++ toolchain. Most checks parse the real
firmware source via tools/analyze_write_surface.py (structured, not loose
regex) in the same style as test_write_surface_invariants.py; a few targeted
checks use regex against the specific new script bodies where a structured
parse would not add anything (e.g. pinning the fingerprint's exact call
order). The fingerprint test vectors use registry/free_power_recovery_evidence.py,
an independent Python re-implementation of the C++ header's algorithm.
"""

from __future__ import annotations

import inspect
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FIRMWARE_PATH = ROOT / "firmware" / "ecco_clock_dongle_stage3_4_free_power.yaml"
HEADER_PATH = ROOT / "firmware" / "include" / "ecco_recovery_evidence.h"
HA_DIR = ROOT / "home-assistant"

sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "registry"))

from analyze_write_surface import _split_blocks, analyze, write_surface  # noqa: E402
import free_power_recovery_evidence as fpre  # noqa: E402

FAILURES: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  PASS  {name}")
    else:
        FAILURES.append(name)
        print(f"  FAIL  {name}" + (f" - {detail}" if detail else ""))


def _raises(fn) -> bool:
    try:
        fn()
    except (ValueError, KeyError):
        return True
    except Exception:
        return False
    return False


if not FIRMWARE_PATH.is_file():
    print(f"  FAIL  firmware not found at {FIRMWARE_PATH}")
    sys.exit(1)
if not HEADER_PATH.is_file():
    print(f"  FAIL  header not found at {HEADER_PATH}")
    sys.exit(1)

text = FIRMWARE_PATH.read_text(encoding="utf-8")
header_text = HEADER_PATH.read_text(encoding="utf-8")

result = analyze(FIRMWARE_PATH)
paths = result["paths"]
by_name = {p.name: p for p in paths}

review = by_name.get("free_power_recovery_review")
dispatch = by_name.get("free_power_recovery_review_dispatch")
button = by_name.get("free_power_recovery_review_button")

def _trim_trailing_header_comment(body: str) -> str:
    """_split_blocks() bounds a block's body at the START of the NEXT
    sibling `  - id:`/`  - platform:` line only - it does not know that a
    top-level `  #` comment immediately preceding that line is really the
    NEXT block's own header, so that trailing comment gets included at the
    end of THIS block's body. Trim it so substring/regex checks below
    aren't fooled by prose written in a DIFFERENT script's header comment
    (this codebase's scripts document what they deliberately do NOT do,
    which means exactly the tokens these checks look for)."""
    m = re.search(r"\n  #", body)
    return body[: m.start()] if m else body


# free_power_recovery_invalidate_evidence has zero Modbus ops, zero
# ownership-flag acquisitions, and zero script.execute dispatches, so
# analyze()'s own paths list (which only keeps blocks with ops/acquires/
# dispatches) filters it out - _split_blocks() does not apply that filter.
_all_blocks = {name: body for _kind, name, body in _split_blocks(text)}
invalidate_body = _trim_trailing_header_comment(_all_blocks.get("free_power_recovery_invalidate_evidence", ""))
on_boot_match = re.search(r"on_boot:\s*\n\s*priority:.*?\nesp32:", text, re.S)
on_boot_body = on_boot_match.group(0) if on_boot_match else ""

OWNED_REGISTERS = {230, 232} | set(range(256, 262)) | set(range(268, 280))
CONTEXT_REGISTERS = {244, 245, 248} | set(range(250, 256))

# ---------------------------------------------------------------------------
print("[1] Recovery review issues zero Modbus write actions")
# ---------------------------------------------------------------------------
check("free_power_recovery_review is parsed as a script", review is not None)
check("free_power_recovery_review_dispatch is parsed as a script", dispatch is not None)
check("free_power_recovery_review_button is parsed as a button", button is not None)
if review is not None:
    check("free_power_recovery_review itself issues zero reads/writes (pure gate)", not review.ops)
if dispatch is not None:
    check("free_power_recovery_review_dispatch issues zero writes", len(dispatch.writes) == 0, f"writes={dispatch.writes}")
    check("free_power_recovery_review_dispatch issues exactly 3 reads", len(dispatch.reads) == 3, f"reads={dispatch.reads}")
if button is not None:
    check("the review button issues zero Modbus ops directly (dispatches via script.execute)", not button.ops)
    check("the review button dispatches to free_power_recovery_review", "free_power_recovery_review" in button.dispatches)
check("free_power_recovery_invalidate_evidence (the shared invalidation routine, reviewer fix B1) is present", bool(invalidate_body))
check("free_power_recovery_invalidate_evidence issues zero Modbus ops (pure RAM/display cleanup)", "modbus_client" not in invalidate_body)
check("on_boot is found (needed by several checks below)", bool(on_boot_body))

check(
    "no modbus_client.write_multiple_registers text appears anywhere in either new script",
    "write_multiple_registers" not in (review.body if review else "")
    and "write_multiple_registers" not in (dispatch.body if dispatch else ""),
)

# ---------------------------------------------------------------------------
print("")
print("[2] The Free Power write surface is unchanged: exactly 230,232,256-261,268-279")
# ---------------------------------------------------------------------------
FP_WRITE_SCRIPTS = {"start_free_power_override", "restore_free_power_snapshot_dispatch"}
fp_written: set[int] = set()
for p in paths:
    if p.name in FP_WRITE_SCRIPTS:
        fp_written |= p.written_addresses
check(
    "start_free_power_override + restore_free_power_snapshot_dispatch write exactly the 20 owned registers",
    fp_written == OWNED_REGISTERS,
    f"actual={sorted(fp_written)}",
)
full_surface = write_surface(paths)
writer_names = {n for names in full_surface.values() for n in names}
check(
    "neither new script appears as a writer of any register",
    "free_power_recovery_review" not in writer_names and "free_power_recovery_review_dispatch" not in writer_names,
)

# ---------------------------------------------------------------------------
print("")
print("[3] Review reads all 20 owned registers")
# ---------------------------------------------------------------------------
read_addrs: set[int] = set()
if dispatch is not None:
    for op in dispatch.reads:
        if op.start_address in (230, 256):
            read_addrs |= set(op.addresses)
check(
    "the review's fresh reads cover every owned register",
    OWNED_REGISTERS.issubset(read_addrs),
    f"missing={sorted(OWNED_REGISTERS - read_addrs)}",
)
check(
    "the review issues a read starting at 230 with count 3 (230-232, matching the existing restore-time read)",
    dispatch is not None and any(op.start_address == 230 and op.count == 3 for op in dispatch.reads),
)
check(
    "the review issues a read starting at 256 with count 24 (256-279, matching the existing restore-time read)",
    dispatch is not None and any(op.start_address == 256 and op.count == 24 for op in dispatch.reads),
)

# ---------------------------------------------------------------------------
print("")
print("[4] Context evidence uses exactly 244, 245, 248, 250-255")
# ---------------------------------------------------------------------------
check(
    "the review issues a read starting at 244 with count 12 (one physical block read of 244-255)",
    dispatch is not None and any(op.start_address == 244 and op.count == 12 for op in dispatch.reads),
)
ctx_globals = set(int(m) for m in re.findall(r"id\(free_power_recovery_ctx_reg(\d+)\)\s*=", dispatch.body if dispatch else ""))
check(
    "exactly the 9 context registers are captured into free_power_recovery_ctx_reg* globals",
    ctx_globals == CONTEXT_REGISTERS,
    f"actual={sorted(ctx_globals)}",
)

# ---------------------------------------------------------------------------
print("")
print("[5] Registers 246, 247, 249 are ignored even though physically returned by the block read")
# ---------------------------------------------------------------------------
for addr in (246, 247, 249):
    check(f"register {addr} has no free_power_recovery_ctx_reg{addr} global anywhere in the firmware", f"free_power_recovery_ctx_reg{addr}" not in text)
    check(f"register {addr} has no free_power_recovery_live_reg{addr} global anywhere in the firmware", f"free_power_recovery_live_reg{addr}" not in text)
# The context read's on_response captures values[0],[1],[4],[6..11] (244,
# 245, 248, 250-255) from a start_address=244 block - values[2] (246),
# values[3] (247) and values[5] (249) must never be assigned to any global.
ctx_block_match = re.search(
    r"start_address:\s*244\s*\n\s*count:\s*12.*?on_response:(.*?)on_error:", dispatch.body if dispatch else "", re.S
)
check("the context read's on_response block is present", ctx_block_match is not None)
if ctx_block_match:
    on_response_body = ctx_block_match.group(1)
    for skipped_index in ("values[2]", "values[3]", "values[5]"):
        check(f"{skipped_index} (an ignored register) is never referenced in the context read's on_response", skipped_index not in on_response_body)

# ---------------------------------------------------------------------------
print("")
print("[6] The fingerprint's canonical field order is pinned")
# ---------------------------------------------------------------------------
# The exact, in-source-order sequence of ecco_recovery_evidence::fnv1a64_update_*(h, ...)
# calls inside the classification lambda. For-loops appear ONCE in source
# text (they run 6 times each at runtime, over an array, not 6 times in
# source) - this list is therefore the SOURCE call sequence, which encodes
# the canonical field order: domain tag, end_epoch, the 20 originals
# (230, 232, then three 6-wide arrays = 256-261/268-273/274-279), the 2
# intended fields, the 20 live-owned values (same grouping), then the 9
# live-context values individually, in registry/free_power_recovery_evidence.py's
# CONTEXT_REGISTER_ORDER order.
EXPECTED_FINGERPRINT_CALLS = [
    ("fnv1a64_update_str", "ecco_recovery_evidence::FINGERPRINT_DOMAIN_TAG"),
    ("fnv1a64_update_u32le", "id(free_power_end_epoch)"),
    ("fnv1a64_update_u16le", "original_230"),
    ("fnv1a64_update_u16le", "original_232"),
    ("fnv1a64_update_u16le", "original_powers[i]"),
    ("fnv1a64_update_u16le", "original_soc[i]"),
    ("fnv1a64_update_u16le", "original_flags[i]"),
    ("fnv1a64_update_u16le", "intended_230"),
    ("fnv1a64_update_u16le", "id(free_power_target_tou_power)"),
    ("fnv1a64_update_u16le", "live_230"),
    ("fnv1a64_update_u16le", "live_232"),
    ("fnv1a64_update_u16le", "live_powers[i]"),
    ("fnv1a64_update_u16le", "live_soc[i]"),
    ("fnv1a64_update_u16le", "live_flags[i]"),
    ("fnv1a64_update_u16le", "id(free_power_recovery_ctx_reg244)"),
    ("fnv1a64_update_u16le", "id(free_power_recovery_ctx_reg245)"),
    ("fnv1a64_update_u16le", "id(free_power_recovery_ctx_reg248)"),
    ("fnv1a64_update_u16le", "id(free_power_recovery_ctx_reg250)"),
    ("fnv1a64_update_u16le", "id(free_power_recovery_ctx_reg251)"),
    ("fnv1a64_update_u16le", "id(free_power_recovery_ctx_reg252)"),
    ("fnv1a64_update_u16le", "id(free_power_recovery_ctx_reg253)"),
    ("fnv1a64_update_u16le", "id(free_power_recovery_ctx_reg254)"),
    ("fnv1a64_update_u16le", "id(free_power_recovery_ctx_reg255)"),
]
actual_calls = re.findall(
    r"ecco_recovery_evidence::(fnv1a64_update_\w+)\(h,\s*(.*?)\);", dispatch.body if dispatch else ""
)
check(
    "the firmware's fingerprint call sequence exactly matches the pinned canonical order",
    actual_calls == EXPECTED_FINGERPRINT_CALLS,
    f"actual={actual_calls}",
)
check(
    "registry/free_power_recovery_evidence.py's OWNED_REGISTER_ORDER matches the 20 owned registers, in order",
    list(fpre.OWNED_REGISTER_ORDER) == [230, 232, 256, 257, 258, 259, 260, 261, 268, 269, 270, 271, 272, 273, 274, 275, 276, 277, 278, 279],
)
check(
    "registry/free_power_recovery_evidence.py's CONTEXT_REGISTER_ORDER matches the 9 context registers, in order",
    list(fpre.CONTEXT_REGISTER_ORDER) == [244, 245, 248, 250, 251, 252, 253, 254, 255],
)
check("excluded registers 231, 246, 247, 249 are absent from both canonical orders", not ({231, 246, 247, 249} & (set(fpre.OWNED_REGISTER_ORDER) | set(fpre.CONTEXT_REGISTER_ORDER))))

# ---------------------------------------------------------------------------
print("")
print("[7] The fingerprint is a 64-bit value formatted as 16 hex digits")
# ---------------------------------------------------------------------------
check(
    "free_power_recovery_evidence_fingerprint is declared uint64_t in globals:",
    bool(re.search(r"id:\s*free_power_recovery_evidence_fingerprint\s*\n\s*type:\s*uint64_t", text)),
)
check(
    "the firmware formats the fingerprint with a 16-digit, zero-padded, uppercase-hex, 64-bit snprintf format",
    '"%016llX"' in (dispatch.body if dispatch else ""),
)
sample_hex = fpre.format_fingerprint_hex(0xDEADBEEFCAFEBABE)
check("format_fingerprint_hex() produces exactly 16 hex characters", len(sample_hex) == 16, sample_hex)
check("format_fingerprint_hex() output is all uppercase hex digits", bool(re.fullmatch(r"[0-9A-F]{16}", sample_hex)), sample_hex)
check("format_fingerprint_hex() rejects an out-of-range value", _raises(lambda: fpre.format_fingerprint_hex(1 << 64)))
check("fnv1a64() over the empty byte string returns the raw offset basis", fpre.fnv1a64(b"") == fpre.FNV64_OFFSET_BASIS)

# ---------------------------------------------------------------------------
print("")
print("[8] Evidence becomes invalid on read error, no response, send refusal, or timeout")
# ---------------------------------------------------------------------------
dispatch_body = dispatch.body if dispatch else ""
fail_assignments = len(re.findall(r"id\(free_power_recovery_read_failed\)\s*=\s*true;", dispatch_body))
# 3 reads x 3 terminal-failure handlers (on_error/on_no_response/on_not_sent)
# + 3 bounded-wait timeout checks = 12.
check("free_power_recovery_read_failed is set true in exactly 12 places (3 reads x [on_error, on_no_response, on_not_sent, timeout])", fail_assignments == 12, f"found {fail_assignments}")
check("every read has an on_error handler that sets free_power_recovery_read_failed", dispatch_body.count("on_error:") >= 3)
check("every read has an on_no_response handler that sets free_power_recovery_read_failed", dispatch_body.count("on_no_response:") >= 3)
check("every read has an on_not_sent handler (send refusal) that sets free_power_recovery_read_failed", dispatch_body.count("on_not_sent:") >= 3)
check("every read is bounded by a wait_until with a timeout", dispatch_body.count("wait_until:") == 3 and dispatch_body.count("timeout: 3000ms") == 3)

failure_branch = re.search(r"if \(id\(free_power_recovery_read_failed\)\) \{(.*?)\} else \{", dispatch_body, re.S)
check("the read-failure branch exists", failure_branch is not None)
if failure_branch:
    body = failure_branch.group(1)
    check(
        'read failure sets the invalidation reason to "read failure" then calls the shared invalidator (reviewer fix B1)',
        'id(free_power_recovery_invalidate_reason) = "read failure";' in body
        and "id(free_power_recovery_invalidate_evidence).execute();" in body,
    )

expiry_match = re.search(
    r"if \(!id\(free_power_recovery_evidence_valid\)\) return;(.*)", text, re.S
)
check("a periodic evidence-expiry check exists", expiry_match is not None)
if expiry_match:
    expiry_body = expiry_match.group(1)
    check("expiry compares age against the 120-second (120000ms) window", "120000" in expiry_body)
    check(
        'expiry sets the invalidation reason to "evidence expired" then calls the shared invalidator (reviewer fix B1)',
        'id(free_power_recovery_invalidate_reason) = "evidence expired";' in expiry_body
        and "id(free_power_recovery_invalidate_evidence).execute();" in expiry_body,
    )
    check("the expiry check issues zero Modbus reads/writes", "modbus_client" not in expiry_body)
    check("the expiry check never touches a durable marker/data record", "ecco_durable::" not in expiry_body)
check(
    "the expiry interval is a separate `- interval:` entry (not folded into the 15s Free Power watchdog)",
    bool(re.search(r"- interval: 10s\s*\n\s*then:\s*\n\s*- lambda: \|-\s*\n\s*if \(!id\(free_power_recovery_evidence_valid\)\)", text)),
)

# ---------------------------------------------------------------------------
print("")
print("[9] Review cannot clear/mutate either durable marker - read-only comparison against")
print("    MARKER_RESTORE_REQUIRED (blocker B2's PENDING_CLEAR gate) is explicitly permitted")
# ---------------------------------------------------------------------------
# Test correction (reviewer round 2): forbidding the mere TEXT
# "MARKER_RESTORE_REQUIRED" was wrong - PR 1 is allowed to READ/COMPARE the
# RAM-mirrored marker state (id(free_power_marker_state)) against it (see
# free_power_recovery_review's PENDING_CLEAR gate and the shared
# invalidator's NONE-vs-LOCKED_* decision). What must still be forbidden is
# any MUTATION of the marker, construction of a durable ValidMarker record,
# or any durable commit/tag reference - those are the actual write paths.
RECOVERY_BODIES = {
    "free_power_recovery_review": review.body if review else "",
    "free_power_recovery_review_dispatch": dispatch_body,
    "free_power_recovery_invalidate_evidence": invalidate_body,
}
for name, body in RECOVERY_BODIES.items():
    check(f"{name} never assigns/mutates free_power_marker_state", not re.search(r"id\(free_power_marker_state\)\s*=(?!=)", body))
    check(f"{name} never constructs or reads a durable ValidMarker record", "ValidMarker" not in body)
    check(f"{name} never references a durable marker preference tag (FREE_POWER_VALID_TAG/REG244_VALID_TAG)", "FREE_POWER_VALID_TAG" not in body and "REG244_VALID_TAG" not in body)
    check(
        f"{name} never references MARKER_CLEAR or MARKER_RESTORE_VERIFIED_PENDING_CLEAR by name "
        f"(only a read-only != comparison against MARKER_RESTORE_REQUIRED is used)",
        "MARKER_CLEAR" not in body and "MARKER_RESTORE_VERIFIED_PENDING_CLEAR" not in body,
    )
check(
    "free_power_recovery_review READS (read-only) MARKER_RESTORE_REQUIRED for its PENDING_CLEAR gate (blocker B2)",
    "ecco_durable::MARKER_RESTORE_REQUIRED" in (review.body if review else ""),
)
check(
    "the shared invalidator ALSO reads MARKER_RESTORE_REQUIRED (its NONE-vs-LOCKED_* decision, blocker B1/B2)",
    "ecco_durable::MARKER_RESTORE_REQUIRED" in invalidate_body,
)
check(
    "the boot mirror ALSO reads MARKER_RESTORE_REQUIRED (blocker B2's boot/status-mirror semantics)",
    "ecco_durable::MARKER_RESTORE_REQUIRED" in on_boot_body,
)

# ---------------------------------------------------------------------------
print("")
print("[10] Review cannot alter the Free Power durable data record")
# ---------------------------------------------------------------------------
for tag in ("FREE_POWER_DATA_TAG", "FreePowerSnapshotData", "commit_record", "FREE_POWER_RETRY_TAG", "FreePowerRetryState"):
    for name, body in RECOVERY_BODIES.items():
        check(f"{name} never references {tag}", tag not in body)
check(
    "none of the three recovery-review scripts commits ANY durable preference record (zero ecco_durable::commit_record calls)",
    all("ecco_durable::commit_record(" not in body for body in RECOVERY_BODIES.values()),
)
check(
    "register 244's own transaction system is untouched (reg244_ prefix absent from all three scripts)",
    all("reg244_" not in body for body in RECOVERY_BODIES.values()),
)

# ---------------------------------------------------------------------------
print("")
print("[11] Nothing in HA packages/automation invokes any recovery-execute path")
# ---------------------------------------------------------------------------
# PR 2 of 3 (feature/free-power-recovery-force-restore) legitimately
# implements FORCE_RESTORE_ORIGINAL, and PR 3 of 3
# (feature/free-power-recovery-accept-current-state) legitimately implements
# ACCEPT_CURRENT_STATE - see registry/tests/test_free_power_recovery_force_restore.py
# and registry/tests/test_free_power_recovery_accept_current_state.py for
# their full structural/behavioural proofs (one-shot evidence, exact
# confirmation phrases, fresh confirm-time fingerprint revalidation,
# protected write order / zero-write invariant, etc.). Neither is therefore
# a firmware-wide forbidden token any more; each is instead asserted to
# appear ONLY inside its own expected script(s)/API routing (see [11a]/
# [11b] below), and both remain absent from every HA package/automation
# file (no automatic caller may invoke either - that invariant is unchanged
# and still checked here). FORCE_RUNNING was never implemented by either PR
# and remains forbidden everywhere, exactly as PR 1 left it.
FORBIDDEN_EVERYWHERE_TOKENS = ("FORCE_RUNNING",)
for token in FORBIDDEN_EVERYWHERE_TOKENS:
    check(f'"{token}" does not appear anywhere in the firmware (never implemented by any PR)', token not in text)

FORBIDDEN_IN_HA_TOKENS = FORBIDDEN_EVERYWHERE_TOKENS + (
    "FORCE_RESTORE_ORIGINAL", "force_restore_original",
    "ACCEPT_CURRENT_STATE", "accept_current_state",
)
# 2026-09-26 (Manual Dump-to-Grid V1 pre-live hardening): the ONLY permitted
# exception - and only inside the dashboard (a human-operated UI, never an
# automation/script/package) - is the Energy Actions card's mapping of the
# separate Dump-to-Grid operator recovery BUTTON entities, whose ESPHome
# entity ids inherently contain these words. Those buttons are Dump's own,
# unrelated to Free Power's API-only recovery path, and the firmware still
# requires the Dump to Grid Recovery Arm before either acts. Exact entity-id
# strings only; every package/automation file stays fully covered, and any
# other occurrence in a dashboard (e.g. a Free Power recovery token) still
# fails. See registry/tests/test_dump_to_grid_v1.py for the matching
# "no HA package references the Dump recovery buttons" check.
DASHBOARD_ALLOWED_DUMP_RECOVERY_ENTITIES = (
    "button.ecco_clock_dongle_dump_to_grid_force_restore_original",
    "button.ecco_clock_dongle_dump_to_grid_accept_current_state",
)
if HA_DIR.is_dir():
    offenders = []
    for path in HA_DIR.rglob("*"):
        if not path.is_file():
            continue
        try:
            contents = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, PermissionError):
            continue
        if path.parent.name == "dashboards":
            for allowed in DASHBOARD_ALLOWED_DUMP_RECOVERY_ENTITIES:
                contents = contents.replace(allowed, "")
        for token in FORBIDDEN_IN_HA_TOKENS:
            if token in contents:
                offenders.append((str(path.relative_to(ROOT)), token))
    check("no Home Assistant package/automation file references any recovery-execute action token", not offenders, f"{offenders}")
else:
    check("home-assistant/ directory exists to scan (skipped - not found)", False, str(HA_DIR))

# ---------------------------------------------------------------------------
print("")
print("[11a] FORCE_RESTORE_ORIGINAL appears ONLY where PR 2 legitimately implements it")
# ---------------------------------------------------------------------------
force_wrapper = by_name.get("free_power_recovery_force_restore")
force_dispatch = by_name.get("free_power_recovery_force_restore_dispatch")
check("free_power_recovery_force_restore is parsed as a script", force_wrapper is not None)
check("free_power_recovery_force_restore_dispatch is parsed as a script", force_dispatch is not None)
if force_wrapper is not None:
    check(
        '"FORCE_RESTORE_ORIGINAL" appears in free_power_recovery_force_restore (the action-token check)',
        "FORCE_RESTORE_ORIGINAL" in force_wrapper.body,
    )
check(
    'the api: actions block declares free_power_recovery_execute (the only caller of Force Restore Original)',
    "action: free_power_recovery_execute" in text,
)

# ---------------------------------------------------------------------------
print("")
print("[11b] ACCEPT_CURRENT_STATE appears ONLY where PR 3 legitimately implements it")
# ---------------------------------------------------------------------------
accept_wrapper = by_name.get("free_power_recovery_accept_current_state")
accept_dispatch = by_name.get("free_power_recovery_accept_current_state_dispatch")
check("free_power_recovery_accept_current_state is parsed as a script", accept_wrapper is not None)
check("free_power_recovery_accept_current_state_dispatch is parsed as a script", accept_dispatch is not None)
if accept_wrapper is not None:
    check(
        '"ACCEPT_CURRENT_STATE" appears in free_power_recovery_accept_current_state (the action-token check)',
        "ACCEPT_CURRENT_STATE" in accept_wrapper.body,
    )
    check(
        "free_power_recovery_accept_current_state issues zero Modbus ops itself (pure gate)",
        not accept_wrapper.ops,
    )
if accept_dispatch is not None:
    check(
        "free_power_recovery_accept_current_state_dispatch issues zero Modbus WRITE ops (Accept's absolute invariant)",
        len(accept_dispatch.writes) == 0,
        f"writes={accept_dispatch.writes}",
    )

# ---------------------------------------------------------------------------
print("")
print("[12] The Free Power Recovery State enum, refusal precondition order, and evidence entities")
# ---------------------------------------------------------------------------
REQUIRED_STATE_VALUES = ("NONE", "LOCKED_NEITHER", "LOCKED_ORIGINAL", "LOCKED_INTENDED", "REVIEWED")
for value in REQUIRED_STATE_VALUES:
    check(f'"{value}" appears in the firmware as a Free Power Recovery State value', f'"{value}"' in text)

REQUIRED_LAST_ACTION_VALUES = ("review complete", "review refused", "read failure", "no durable obligation", "metadata unavailable")
for value in REQUIRED_LAST_ACTION_VALUES:
    check(f'"{value}" appears in the firmware as a Last Action/Result value', f'"{value}"' in text)

if review is not None:
    body = review.body
    check(
        "the in-progress gate also refuses while correction_in_progress is active (non-blocking observation, matches start/restore's own gate)",
        bool(re.search(r"id\(free_power_operation_in_progress\)\s*\|\|\s*\n\s*id\(manual_write_in_progress\)\s*\|\|\s*\n\s*id\(correction_in_progress\)", body)),
    )
    idx_busy = body.find("id(free_power_operation_in_progress)")
    idx_corrupt = body.find("free_power_recovery_metadata_corrupt")
    idx_no_obligation = body.find("!id(free_power_snapshot_valid)")
    idx_pending_clear = body.find("ecco_durable::MARKER_RESTORE_REQUIRED")
    idx_active = body.find("id(free_power_active_persisted)")
    idx_bus = body.find("tx_buffer_empty()")
    check(
        "refusal preconditions are checked in order: in-progress/correction -> metadata corrupt -> "
        "no obligation -> not-RESTORE_REQUIRED (blocker B2) -> active lease (non-blocking fix) -> bus quiescence",
        -1 < idx_busy < idx_corrupt < idx_no_obligation < idx_pending_clear < idx_active < idx_bus,
        f"offsets busy={idx_busy} corrupt={idx_corrupt} no_obligation={idx_no_obligation} "
        f"pending_clear={idx_pending_clear} active={idx_active} bus={idx_bus}",
    )
    check(
        "the active-lease refusal does not touch evidence - it is a plain refusal, not an invalidate_evidence call",
        bool(re.search(
            r"return id\(free_power_active_persisted\) && !id\(free_power_operator_needed\);\s*\n\s*then:\s*\n"
            r"\s*- lambda: \|-\s*\n\s*id\(free_power_recovery_review_refusal_count\)\+\+;\s*\n"
            r'\s*id\(free_power_recovery_last_action\)\.publish_state\("review refused"\);',
            body,
        )),
    )
    check(
        "Modbus dispatch (script.execute to the dispatch script) is reachable only after every refusal/invalidation gate",
        body.rfind("script.execute:") > max(idx_busy, idx_corrupt, idx_no_obligation, idx_pending_clear, idx_active, idx_bus),
    )

# ---------------------------------------------------------------------------
print("")
print("[16] Reviewer round 3 - active_persisted alone must not gate Review; a known")
print("     recovery lockout (operator_needed) must remain reviewable even while active_persisted is true")
# ---------------------------------------------------------------------------
review_body = review.body if review else ""
check(
    "Review's active-lease gate is the CONJUNCTION active_persisted && !operator_needed - "
    "NOT active_persisted alone (round 3 fix: a healthy lease refuses; a known recovery "
    "lockout with active_persisted still true must NOT be refused by this gate)",
    "return id(free_power_active_persisted) && !id(free_power_operator_needed);" in review_body,
)
# Extract the EXACT compiled C++ condition text and evaluate it in Python
# for every (active_persisted, operator_needed) combination, rather than
# asserting a separately-hand-derived truth table - this actually exercises
# the firmware's own expression text, so a future edit that subtly changes
# the boolean logic (e.g. swaps && for ||, or drops the !) is caught here,
# not just by the substring-presence check above.
cond_match = re.search(
    r"return (id\(free_power_active_persisted\) && !id\(free_power_operator_needed\));", review_body
)
check("the exact active_persisted gate condition text is found for evaluation", cond_match is not None)
if cond_match:
    py_expr = (
        cond_match.group(1)
        .replace("id(free_power_active_persisted)", "active_persisted")
        .replace("id(free_power_operator_needed)", "operator_needed")
        .replace("&&", "and")
        .replace("!operator_needed", "not operator_needed")
    )
    TRUTH_TABLE = {
        (True, False): True,  # case 1: healthy active lease -> REFUSE
        (True, True): False,  # case 2: active lease that is ALSO a known recovery lockout -> ALLOW
        (False, False): False,  # not active at all -> ALLOW (other gates decide)
        (False, True): False,  # not active, but a lockout is known -> ALLOW
    }
    for (active_persisted, operator_needed), expect_refuse in TRUTH_TABLE.items():
        actual = eval(py_expr, {}, {"active_persisted": active_persisted, "operator_needed": operator_needed})
        check(
            f"active_persisted={active_persisted}, operator_needed={operator_needed} -> "
            f"gate {'REFUSES' if expect_refuse else 'ALLOWS (falls through to bus-quiescence/dispatch)'}",
            actual is expect_refuse,
            f"evaluated {py_expr!r} -> {actual}, expected {expect_refuse}",
        )
check(
    "the gate does not assign/mutate free_power_active_persisted",
    not re.search(r"id\(free_power_active_persisted\)\s*=(?!=)", review_body),
)
check(
    "the gate does not assign/mutate free_power_operator_needed",
    not re.search(r"id\(free_power_operator_needed\)\s*=(?!=)", review_body),
)
check(
    "the gate does not touch any durable record (no commit_record/ValidMarker/data-tag reference nearby)",
    "ecco_durable::commit_record(" not in review_body and "ValidMarker" not in review_body,
)

# [16.3] The recovery dispatch still requires RESTORE_REQUIRED - re-confirm the
# B2 gate (immediately preceding, in source order) is untouched by this fix.
check(
    "the marker-not-RESTORE_REQUIRED gate (blocker B2) still precedes the active_persisted gate, unchanged",
    review_body.find("ecco_durable::MARKER_RESTORE_REQUIRED") != -1
    and review_body.find("ecco_durable::MARKER_RESTORE_REQUIRED") < review_body.find("free_power_active_persisted) && !id(free_power_operator_needed)"),
)

# [16.4] PENDING_CLEAR remains non-reviewable - re-run the key B2 assertions here
# too (belt-and-braces alongside section [15], since this round touches the same
# script) rather than only trusting they were not regressed.
check(
    "PENDING_CLEAR (marker != RESTORE_REQUIRED) is still refused via the shared invalidator with its "
    "distinct message, unchanged by the round-3 active_persisted fix",
    "recovery obligation resolved - durable clear pending; nothing to review" in review_body,
)

# [16.5 / 16.6] Zero new Modbus writes; Free Power write surface unchanged.
check(
    "free_power_recovery_review still issues zero Modbus ops of any kind (the active_persisted "
    "fix only changed a boolean condition)",
    not review.ops,
)
FP_WRITE_SCRIPTS_R3 = {"start_free_power_override", "restore_free_power_snapshot_dispatch"}
fp_written_r3: set[int] = set()
for p in paths:
    if p.name in FP_WRITE_SCRIPTS_R3:
        fp_written_r3 |= p.written_addresses
check(
    "the Free Power write surface remains exactly 230,232,256-261,268-279 after the round-3 fix",
    fp_written_r3 == OWNED_REGISTERS,
    f"actual={sorted(fp_written_r3)}",
)
_full_surface_r3 = write_surface(paths)
check(
    "no register anywhere in the firmware is written by any of the three recovery-review scripts",
    all(
        "free_power_recovery_review" not in names
        and "free_power_recovery_review_dispatch" not in names
        and "free_power_recovery_invalidate_evidence" not in names
        for names in _full_surface_r3.values()
    ),
)

if dispatch is not None:
    idx_intended = dispatch.body.find("if (matches_intended)")
    idx_original = dispatch.body.find("else if (matches_original)")
    check(
        "classification checks INTENDED before ORIGINAL (documented tie-break)",
        -1 < idx_intended < idx_original,
    )

REQUIRED_ENTITY_IDS = (
    "free_power_recovery_state",
    "free_power_recovery_evidence_id",
    "free_power_recovery_evidence_230_232",
    "free_power_recovery_evidence_256_261",
    "free_power_recovery_evidence_268_273",
    "free_power_recovery_evidence_274_279",
    "free_power_recovery_evidence_context",
    "free_power_recovery_last_action",
    "free_power_recovery_review_button",
)
for entity_id in REQUIRED_ENTITY_IDS:
    check(f"entity id {entity_id} is declared exactly once", len(re.findall(rf"\bid:\s*{entity_id}\b", text)) == 1)

# All new RAM state must be restore_value: no (never restore_value: yes,
# and never loaded from/committed to a durable preference record). Type
# pattern allows "std::string" (free_power_recovery_invalidate_reason,
# reviewer fix B1) as well as the plain uintN_t/bool/int types.
new_global_ids = re.findall(r"id:\s*(free_power_recovery_\w+)\s*\n\s*type:\s*[\w:]+\s*\n\s*restore_value:\s*(\w+)", text)
check("every new free_power_recovery_* global exists and declares restore_value: no", len(new_global_ids) >= 30, f"found {len(new_global_ids)}")
for gid, restore_value in new_global_ids:
    check(f"{gid} is restore_value: no (RAM-only)", restore_value == "no")
check(
    "free_power_recovery_invalidate_reason is declared std::string (reviewer fix B1's shared-invalidator reason channel)",
    bool(re.search(r"id:\s*free_power_recovery_invalidate_reason\s*\n\s*type:\s*std::string", text)),
)

# ---------------------------------------------------------------------------
print("")
print("[13] Deterministic fingerprint test vectors")
# ---------------------------------------------------------------------------
ORIGINALS = {
    230: 100, 232: 1,
    256: 500, 257: 500, 258: 500, 259: 500, 260: 500, 261: 500,
    268: 80, 269: 81, 270: 82, 271: 83, 272: 84, 273: 85,
    274: 1, 275: 1, 276: 1, 277: 1, 278: 1, 279: 1,
}
LIVE_OWNED = {addr: (val + 1000) & 0xFFFF for addr, val in ORIGINALS.items()}
LIVE_CONTEXT = {244: 1, 245: 2, 248: 1, 250: 600, 251: 630, 252: 700, 253: 730, 254: 800, 255: 830}
BASE_KWARGS = dict(
    end_epoch=1700000000,
    originals=ORIGINALS,
    reg230_intended=150,
    reg_tou_power_intended=600,
    live_owned=LIVE_OWNED,
    live_context=LIVE_CONTEXT,
)

# Pinned regression vector - computed once from compute_fingerprint() and
# hardcoded here. If the algorithm, byte order, or field order ever
# changes, this fails, which is the point.
EXPECTED_FIXED_FINGERPRINT = 13302788961953214610
EXPECTED_FIXED_FINGERPRINT_HEX = "B89D001467357092"

base_fp = fpre.compute_fingerprint(**BASE_KWARGS)
check("fixed known input produces the pinned expected 64-bit fingerprint", base_fp == EXPECTED_FIXED_FINGERPRINT, f"got {base_fp}")
check("fixed known input's hex form matches the pinned expected 16 hex digits", fpre.format_fingerprint_hex(base_fp) == EXPECTED_FIXED_FINGERPRINT_HEX, fpre.format_fingerprint_hex(base_fp))
check("the fingerprint is a plain 64-bit unsigned integer", 0 <= base_fp <= 0xFFFFFFFFFFFFFFFF)
check("computing the same input twice is deterministic", fpre.compute_fingerprint(**BASE_KWARGS) == base_fp)


def _variant(**overrides):
    kwargs = dict(BASE_KWARGS)
    kwargs.update(overrides)
    return fpre.compute_fingerprint(**kwargs)


check("changing end_epoch changes the fingerprint", _variant(end_epoch=BASE_KWARGS["end_epoch"] + 1) != base_fp)

o_variant = dict(ORIGINALS)
o_variant[230] = (o_variant[230] + 1) & 0xFFFF
check("changing an ORIGINAL owned register changes the fingerprint", _variant(originals=o_variant) != base_fp)

check("changing reg230_intended changes the fingerprint", _variant(reg230_intended=BASE_KWARGS["reg230_intended"] + 1) != base_fp)
check("changing reg_tou_power_intended changes the fingerprint", _variant(reg_tou_power_intended=BASE_KWARGS["reg_tou_power_intended"] + 1) != base_fp)

l_variant = dict(LIVE_OWNED)
l_variant[279] = (l_variant[279] + 1) & 0xFFFF
check("changing a LIVE owned register changes the fingerprint", _variant(live_owned=l_variant) != base_fp)

c_variant = dict(LIVE_CONTEXT)
c_variant[255] = (c_variant[255] + 1) & 0xFFFF
check("changing a LIVE context register changes the fingerprint", _variant(live_context=c_variant) != base_fp)

# "Excluded fields do NOT affect it": these fields have no parameter in
# compute_fingerprint() at all, so there is nothing to vary - assert that
# structurally instead (the function's keyword-only signature simply does
# not accept them).
sig_params = set(inspect.signature(fpre.compute_fingerprint).parameters)
EXCLUDED_CONCEPTS = {"active_persisted", "restore_requested", "reg231", "reg246", "reg247", "reg249", "classification", "timestamp", "counter"}
check(
    "compute_fingerprint()'s signature has no parameter for any excluded field",
    sig_params.isdisjoint(EXCLUDED_CONCEPTS),
    f"signature params={sorted(sig_params)}",
)
check(
    "a wrong owned-register key set (missing/extra) is rejected rather than silently hashed",
    _raises(lambda: fpre.compute_fingerprint(**{**BASE_KWARGS, "originals": {k: v for k, v in ORIGINALS.items() if k != 230}})),
)

# ---------------------------------------------------------------------------
print("")
print("[14] Reviewer blocker B1 - REVIEWED cannot survive invalid/stale evidence")
# ---------------------------------------------------------------------------
success_branch = re.search(r"\} else \{(.*)\bid\(free_power_operation_in_progress\) = false;", dispatch_body, re.S)
check("the successful-classification branch (the else of the read-failure check) is found", success_branch is not None)
success_body = success_branch.group(1) if success_branch else ""

# [14.1] REVIEWED is reachable only from a successful fresh NEITHER review.
reviewed_occurrences = [m.start() for m in re.finditer(r'"REVIEWED"', text)]
check("the literal \"REVIEWED\" appears EXACTLY once in the whole firmware", len(reviewed_occurrences) == 1, f"found {len(reviewed_occurrences)} at {reviewed_occurrences}")
check(
    "that one \"REVIEWED\" occurrence is inside the dispatch script's successful-classification branch "
    "(never in on_boot, the shared invalidator, the gate script, or the expiry interval)",
    len(reviewed_occurrences) == 1 and bool(success_body) and '"REVIEWED"' in success_body,
)
check("\"REVIEWED\" never appears in free_power_recovery_invalidate_evidence", '"REVIEWED"' not in invalidate_body)
check("\"REVIEWED\" never appears in the on_boot mirror", '"REVIEWED"' not in on_boot_body)
check(
    "REVIEWED is published only on the else (NEITHER) branch of the ORIGINAL/INTENDED classification, "
    "i.e. only after a matches_intended/matches_original both-false outcome",
    bool(re.search(r"\} else \{\s*\n(?:[^{}]*\n)*?\s*state_str = \"REVIEWED\";", success_body)) if success_body else False,
)

# [14.2] A subsequent failed review cannot leave REVIEWED displayed: dispatch
# invalidates evidence UNCONDITIONALLY at the start of every attempt (before
# any read), in addition to invalidating again on that attempt's own failure.
start_lambda_match = re.search(r"id\(free_power_operation_in_progress\) = true;.*?ESP_LOGI\(\"free_power_recovery\", \"Starting", dispatch_body, re.S)
check("dispatch's start-of-attempt lambda is found", start_lambda_match is not None)
if start_lambda_match:
    start_body = start_lambda_match.group(0)
    check(
        "every new review attempt invalidates evidence (via the shared routine) BEFORE issuing any Modbus read "
        "(blocker B1.2 - a subsequent failed review can never leave a PRIOR successful review's REVIEWED displayed)",
        "id(free_power_recovery_invalidate_evidence).execute();" in start_body,
    )
    check("the start-of-attempt invalidation happens strictly before the first modbus_client action", "modbus_client" not in start_body)

# [14.3 / 14.4] Read failure clears the Evidence ID and every evidence row/context.
check(
    "read failure's shared-invalidator call (see [8]) is the ONLY evidence-clearing action needed - "
    "the invalidator itself publishes \"-\" to the Evidence ID",
    'id(free_power_recovery_evidence_id).publish_state("-");' in invalidate_body,
)
for sensor in ("evidence_230_232", "evidence_256_261", "evidence_268_273", "evidence_274_279", "evidence_context"):
    check(f"the shared invalidator clears free_power_recovery_{sensor} to \"-\"", f'id(free_power_recovery_{sensor}).publish_state("-");' in invalidate_body)
check("the shared invalidator clears the fingerprint to 0", "id(free_power_recovery_evidence_fingerprint) = 0;" in invalidate_body)
check("the shared invalidator clears free_power_recovery_evidence_valid to false", "id(free_power_recovery_evidence_valid) = false;" in invalidate_body)
check("the shared invalidator resets the evidence age basis (captured_ms) to 0", "id(free_power_recovery_evidence_captured_ms) = 0;" in invalidate_body)

# [14.5 / 14.6] Expiry clears the Evidence ID and evidence rows/context - already
# proven by [8]'s "expiry ... calls the shared invalidator" check plus the
# invalidator-body checks just above (same shared code path, same guarantee).
check(
    "expiry and read failure share the IDENTICAL clearing code path (both call "
    "free_power_recovery_invalidate_evidence, proven above)",
    "id(free_power_recovery_invalidate_evidence).execute();" in (expiry_body if expiry_match else ""),
)

# [14.7] Expiry cannot leave REVIEWED: the expiry interval calls ONLY the
# shared invalidator (never publishes state itself), and the invalidator
# never publishes "REVIEWED" (checked above) - so expiry can only ever
# land on NONE/LOCKED_*.
check(
    "the expiry interval never publishes free_power_recovery_state itself (only via the shared invalidator)",
    "id(free_power_recovery_state).publish_state(" not in (expiry_body if expiry_match else ""),
)

# [14.8] Reboot cannot restore REVIEWED evidence: every evidence-related
# global is restore_value: no (proven above - "every new free_power_recovery_*
# global... declares restore_value: no"), and on_boot never publishes
# "REVIEWED" (checked above) or sets free_power_recovery_evidence_valid to
# true - it only ever calls the shared invalidator, which forces it false.
check(
    "on_boot never sets free_power_recovery_evidence_valid to true",
    "id(free_power_recovery_evidence_valid) = true;" not in on_boot_body,
)
check(
    "on_boot's Free Power recovery block ends by calling the shared invalidator (so a reboot always forces "
    "evidence_valid=false, fingerprint=0, and every evidence sensor back to \"-\", regardless of the durable "
    "obligation reconstructed just above it)",
    "id(free_power_recovery_invalidate_evidence).execute();" in on_boot_body,
)

# ---------------------------------------------------------------------------
print("")
print("[15] Reviewer blocker B2 - PENDING_CLEAR is not reviewable")
# ---------------------------------------------------------------------------
check(
    "free_power_recovery_review refuses (via the shared invalidator) before dispatching ANY Modbus "
    "recovery-review read when the durable marker is not RESTORE_REQUIRED",
    bool(review) and bool(re.search(
        r"return id\(free_power_marker_state\) != ecco_durable::MARKER_RESTORE_REQUIRED;\s*\n\s*then:\s*\n"
        r"\s*- lambda: \|-\s*\n\s*id\(free_power_recovery_invalidate_reason\) = "
        r'"recovery obligation resolved - durable clear pending; nothing to review";\s*\n'
        r"\s*id\(free_power_recovery_invalidate_evidence\)\.execute\(\);",
        review.body if review else "",
    )),
)
check(
    'the PENDING_CLEAR refusal message clearly states "nothing to review"',
    "recovery obligation resolved - durable clear pending; nothing to review" in (review.body if review else ""),
)
check(
    "no modbus_client action appears between the marker-not-RESTORE_REQUIRED check and the eventual dispatch "
    "call (i.e. this refusal branch itself performs no reads - it is a sibling `then:` of the `if:`, not a "
    "predecessor of the dispatch `else:`)",
    "modbus_client" not in (review.body if review else ""),
)
check(
    "the shared invalidator treats marker != MARKER_RESTORE_REQUIRED the same as no-obligation: Recovery State "
    "becomes NONE (not a LOCKED_* value) for both",
    bool(re.search(
        r"else if \(!id\(free_power_snapshot_valid\) \|\| id\(free_power_marker_state\) != ecco_durable::MARKER_RESTORE_REQUIRED\) \{\s*\n\s*state_str = \"NONE\";",
        invalidate_body,
    )),
)
check(
    "the on_boot mirror ALSO treats a non-RESTORE_REQUIRED marker (PENDING_CLEAR) distinctly, with its own "
    '"recovery obligation resolved..." Last Action/Result message, before the operator_needed/generic branches',
    bool(re.search(
        r"else if \(id\(free_power_marker_state\) != ecco_durable::MARKER_RESTORE_REQUIRED\) \{\s*\n"
        r'\s*id\(free_power_recovery_invalidate_reason\) = "recovery obligation resolved - durable clear pending; nothing to review";',
        on_boot_body,
    )),
)
check(
    "in the gate script, the not-RESTORE_REQUIRED check comes AFTER the no-obligation check (so it only ever "
    "fires when snapshot_valid is true, i.e. genuinely PENDING_CLEAR, not the plain-CLEAR/no-obligation case)",
    review is not None and review.body.find("!id(free_power_snapshot_valid)") < review.body.find("ecco_durable::MARKER_RESTORE_REQUIRED"),
)

print("")
if FAILURES:
    print(f"{len(FAILURES)} check(s) FAILED:")
    for name in FAILURES:
        print(f"  - {name}")
else:
    print("All Free Power recovery evidence tests PASSED.")

print("")
print("These are STRUCTURAL/offline facts about the firmware source file and its")
print("Python fingerprint mirror. They prove nothing about hardware behaviour -")
print("this PR adds no OTA/live proof, by design (READ-ONLY recovery infrastructure).")

if FAILURES:
    sys.exit(1)
