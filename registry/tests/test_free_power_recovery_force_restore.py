#!/usr/bin/env python3
"""Offline structural/behavioural tests for PR 2 of 3 - Free Power operator
recovery: FORCE RESTORE ORIGINAL (`free_power_recovery_force_restore` /
`free_power_recovery_force_restore_dispatch` in
firmware/ecco_clock_dongle_stage3_4_free_power.yaml, the
`free_power_recovery_execute` API action, and the `Free Power Recovery Arm`
switch).

Background: PR 1 (registry/tests/test_free_power_recovery_evidence.py) added
a READ-ONLY operator review of live Free Power state (20 owned registers +
9 context registers), a 64-bit FNV-1a evidence fingerprint, and a
classifier (matches ORIGINAL / matches INTENDED / matches NEITHER). This PR
adds the first real recovery ACTION an operator can take on that evidence:
Force Restore Original - writing every owned register back to its exact
durable ORIGINAL snapshot value, reachable ONLY through the ESPHome API,
gated by a one-shot recovery arm, a fresh unexpired reviewed evidence ID,
an exact confirmation phrase, and a FRESH confirm-time re-read whose
fingerprint must exactly match the reviewed one before the first Modbus
write. PR 3 (Accept Current State) does not exist yet.

No I/O, no hardware, no ESPHome/C++ toolchain. This file combines three
techniques, in the same spirit as
registry/tests/test_free_power_tou_power_ownership_2026_09_23.py:

  1. tools/analyze_write_surface.py's structured extractor (write surface,
     ownership/mutex acquisition, read/write op inventory) - groups C, E.
  2. A real parse of the firmware YAML into its actual ESPHome action tree
     (unknown tags such as `!lambda` kept as plain scalars), walked to
     prove write ORDER and GATING on real `if:`/`then:`/`else:` structure,
     never on character offsets - group F.
  3. A hand-maintained Python reference model of the write/readback/verify
     protocol (`simulate_force_restore` below), exercised under many
     synthetic register-bank scenarios including "acknowledged but not
     applied" writes - groups H/I/J. This mirrors the DESIGNED protocol;
     groups C/E/F/G independently prove the real firmware source matches
     that design (write addresses, order, gating, and that every value
     written is the durable ORIGINAL, never a live/intended/hardcoded
     value), so the two cannot silently diverge unnoticed.

These prove the source (and the reference model) say what they should -
never that the compiled firmware behaves this way against real hardware.
No live Free Power event, OTA, or inverter write is part of this change.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
FIRMWARE_PATH = ROOT / "firmware" / "ecco_clock_dongle_stage3_4_free_power.yaml"
HEADER_PATH = ROOT / "firmware" / "include" / "ecco_recovery_evidence.h"
HA_DIR = ROOT / "home-assistant"

sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "registry"))

from analyze_write_surface import _split_blocks, analyze  # noqa: E402
import free_power_recovery_evidence as fpre  # noqa: E402

FAILURES: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  PASS  {name}")
    else:
        FAILURES.append(name)
        print(f"  FAIL  {name}" + (f" - {detail}" if detail else ""))


for _p in (FIRMWARE_PATH, HEADER_PATH):
    if not _p.is_file():
        print(f"  FAIL  required file not found: {_p}")
        sys.exit(1)

text = FIRMWARE_PATH.read_text(encoding="utf-8")

result = analyze(FIRMWARE_PATH)
paths = result["paths"]
by_name = {p.name: p for p in paths}

wrapper = by_name.get("free_power_recovery_force_restore")
dispatch = by_name.get("free_power_recovery_force_restore_dispatch")
review_dispatch = by_name.get("free_power_recovery_review_dispatch")

OWNED_REGISTERS = {230, 232} | set(range(256, 262)) | set(range(268, 280))
CONTEXT_REGISTERS = {244, 245, 248} | set(range(250, 256))


# ---------------------------------------------------------------------------
# Real ESPHome action-tree parse (not regex/offsets) - same technique as
# registry/tests/test_free_power_tou_power_ownership_2026_09_23.py. Unknown
# tags (`!lambda`, `!secret`) are kept as their plain scalar/text value so
# the tree still loads.
# ---------------------------------------------------------------------------
class _FirmwareLoader(yaml.SafeLoader):
    pass


def _tagged(loader, suffix, node):
    if isinstance(node, yaml.ScalarNode):
        return loader.construct_scalar(node)
    if isinstance(node, yaml.SequenceNode):
        return loader.construct_sequence(node)
    return loader.construct_mapping(node)


_FirmwareLoader.add_multi_constructor("!", _tagged)
fw_doc = yaml.load(text, Loader=_FirmwareLoader)
SCRIPTS = {s["id"]: s for s in fw_doc["script"]}

WRITE = "modbus_client.write_multiple_registers"
READ = "modbus_client.read_holding_registers"


def _norm(code: str) -> str:
    return " ".join(str(code).split())


def _cond_text(if_body: dict) -> str:
    cond = if_body.get("condition")
    if isinstance(cond, dict) and "lambda" in cond:
        return _norm(cond["lambda"])
    return _norm(repr(cond))


def _single(action: dict) -> tuple[str, object]:
    if not isinstance(action, dict) or len(action) != 1:
        raise AssertionError(f"not a single-key ESPHome action: {action!r}")
    return next(iter(action.items()))


def flatten(actions, gates=()):
    """Document-order list of (kind, gates, body). `gates` is the tuple of
    (normalised condition lambda, 'then'|'else') of every enclosing `if:`."""
    out = []
    for action in actions or []:
        kind, body = _single(action)
        out.append((kind, gates, body))
        if kind == "if":
            cond = _cond_text(body)
            out.extend(flatten(body.get("then"), gates + ((cond, "then"),)))
            out.extend(flatten(body.get("else"), gates + ((cond, "else"),)))
    return out


def writes_in(flat):
    return [(i, body["start_address"], gates) for i, (kind, gates, body) in enumerate(flat) if kind == WRITE]


def reads_in(flat):
    return [(i, body["start_address"], body.get("count"), gates) for i, (kind, gates, body) in enumerate(flat) if kind == READ]


wrapper_actions = SCRIPTS.get("free_power_recovery_force_restore", {}).get("then")
dispatch_actions = SCRIPTS.get("free_power_recovery_force_restore_dispatch", {}).get("then")
wrapper_flat = flatten(wrapper_actions) if wrapper_actions is not None else []
dispatch_flat = flatten(dispatch_actions) if dispatch_actions is not None else []

# ---------------------------------------------------------------------------
print("[A] API action / one-shot arm / confirmation phrase")
# ---------------------------------------------------------------------------
check("free_power_recovery_force_restore is parsed as a script", wrapper is not None)
check("free_power_recovery_force_restore_dispatch is parsed as a script", dispatch is not None)
check("free_power_recovery_force_restore issues zero Modbus ops itself (pure gate)", wrapper is not None and not wrapper.ops)
check(
    "free_power_recovery_force_restore's only dispatch target is the Force Restore dispatch script",
    wrapper is not None and wrapper.dispatches == ["free_power_recovery_force_restore_dispatch"],
    f"{wrapper.dispatches if wrapper else None}",
)

api_block_m = re.search(r"\napi:\n(.*?)\nota:\n", text, re.S)
api_block = api_block_m.group(1) if api_block_m else ""
check("api: block is found (needed by several checks below)", bool(api_block))
check("the api: actions block declares free_power_recovery_execute", "action: free_power_recovery_execute" in api_block)
action_decl_m = re.search(
    r"action: free_power_recovery_execute\s*\n\s*variables:\s*\n"
    r"\s*action: string\s*\n\s*evidence_id: string\s*\n\s*confirmation: string\s*\n",
    api_block,
)
check(
    "free_power_recovery_execute requires exactly three string variables: action, evidence_id, confirmation",
    action_decl_m is not None,
)
check(
    "the API action's own then: only copies arguments into RAM and dispatches - zero Modbus, zero precondition logic",
    "modbus_client" not in api_block and "id(free_power_recovery_arm)" not in api_block,
)
check(
    "the API action is the only thing that assigns id(free_power_recovery_force_action) from the raw `action` argument",
    len(re.findall(r"id\(free_power_recovery_force_action\)\s*=\s*action;", text)) == 1,
)

# Only FORCE_RESTORE_ORIGINAL is accepted; nothing here allow-lists or
# special-cases ACCEPT_CURRENT_STATE (PR 3) - the wrapper's else-if chain
# refuses anything that isn't exactly this one literal token.
if wrapper is not None:
    check(
        'the ONLY action-token comparison is against the literal "FORCE_RESTORE_ORIGINAL" (case-sensitive)',
        wrapper.body.count('id(free_power_recovery_force_action) != "FORCE_RESTORE_ORIGINAL"') == 1,
    )
    check("PR 3's Accept Current State token is not special-cased anywhere in the wrapper", "ACCEPT" not in wrapper.body)
    check(
        "the confirmation phrase is built as the exact literal prefix plus the evidence_id, with no trimming/case-folding",
        'std::string("FORCE RESTORE ORIGINAL ") + id(free_power_recovery_force_evidence_id)' in wrapper.body,
    )
    check(
        "the confirmation comparison is a plain std::string equality (operator==, via !=) - no strncmp/tolower/substring helpers",
        "id(free_power_recovery_force_confirmation) != expected_confirmation" in wrapper.body
        and "tolower" not in wrapper.body
        and "strncmp" not in wrapper.body
        and ".find(" not in wrapper.body,
    )
    check(
        "the evidence_id format check requires exactly 16 characters",
        "s.size() != 16" in wrapper.body,
    )
    check(
        "the evidence_id format check only accepts uppercase hex digits (0-9, A-F) - lowercase is rejected",
        "c >= 'A' && c <= 'F'" in wrapper.body and "c >= 'a'" not in wrapper.body,
    )

# Recovery Arm switch: default OFF, non-persistent, cannot itself write.
arm_switch_m = re.search(
    r'- platform: template\s*\n\s*name: "Free Power Recovery Arm"\s*\n\s*id: free_power_recovery_arm\s*\n'
    r"(.*?)\n\n",
    text,
    re.S,
)
arm_switch_body = arm_switch_m.group(1) if arm_switch_m else ""
check("the Free Power Recovery Arm switch exists", arm_switch_m is not None)
check("the arm defaults OFF and is never restored ON across reboot (restore_mode: ALWAYS_OFF)", "restore_mode: ALWAYS_OFF" in arm_switch_body)
check("the arm is a plain optimistic template switch with no on_turn_on Modbus action", "optimistic: true" in arm_switch_body and "modbus_client" not in arm_switch_body)

# Every execute attempt disarms and invalidates evidence - both branches of
# the wrapper's top-level if/else call turn_off()/invalidate_evidence().
if wrapper is not None:
    turn_off_count = wrapper.body.count("id(free_power_recovery_arm).turn_off();")
    invalidate_count = wrapper.body.count("id(free_power_recovery_invalidate_evidence).execute();")
    check("the wrapper disarms the recovery arm on exactly 2 code paths (success and refusal)", turn_off_count == 2, f"found {turn_off_count}")
    check("the wrapper invalidates evidence on exactly 2 code paths (success and refusal)", invalidate_count == 2, f"found {invalidate_count}")

# No firmware button, HA automation, or scheduler may call free_power_recovery_execute
# or free_power_recovery_force_restore directly - the ONLY caller of the
# dispatch is the wrapper, and the ONLY caller of the wrapper is the API action.
force_restore_callers = re.findall(r"script\.execute:\s*\n\s*id:\s*free_power_recovery_force_restore\b", text)
check(
    "free_power_recovery_force_restore is script.execute'd from exactly one place (the API action)",
    len(force_restore_callers) == 1,
    f"found {len(force_restore_callers)}",
)
force_dispatch_callers = re.findall(r"script\.execute:\s*\n\s*id:\s*free_power_recovery_force_restore_dispatch\b", text)
check(
    "free_power_recovery_force_restore_dispatch is script.execute'd from exactly one place (the wrapper's own success branch)",
    len(force_dispatch_callers) == 1,
    f"found {len(force_dispatch_callers)}",
)
check("no button: entry executes free_power_recovery_force_restore", not any(
    p.kind == "button" and "free_power_recovery_force_restore" in p.dispatches for p in paths
))
if HA_DIR.is_dir():
    ha_offenders = []
    for hap in HA_DIR.rglob("*"):
        if not hap.is_file():
            continue
        try:
            contents = hap.read_text(encoding="utf-8")
        except (UnicodeDecodeError, PermissionError):
            continue
        if "free_power_recovery_execute" in contents or "free_power_recovery_force_restore" in contents:
            ha_offenders.append(str(hap.relative_to(ROOT)))
    check("no Home Assistant package/automation file references the Force Restore action or scripts", not ha_offenders, f"{ha_offenders}")
else:
    check("home-assistant/ directory exists to scan (skipped - not found)", False, str(HA_DIR))

# ---------------------------------------------------------------------------
print("")
print("[B] Evidence age - independently re-checked with the same 120s boundary as PR 1, wrap-safe")
# ---------------------------------------------------------------------------
if wrapper is not None:
    expiry_m = re.search(
        r"\(uint32_t\)\s*\(millis\(\)\s*-\s*id\(free_power_recovery_evidence_captured_ms\)\)\s*>=\s*120000",
        wrapper.body,
    )
    check("the wrapper independently recomputes evidence age as (uint32_t)(millis() - captured_ms) >= 120000", expiry_m is not None)
    # PR 1's own periodic invalidator uses the same 120000ms boundary (see
    # test_free_power_recovery_evidence.py) - pin that the two never drift
    # apart by comparing the literal numeric boundary, not just presence.
    pr1_expiry_m = re.search(r"age_ms\s*<\s*(\d+)\)\s*return;", text)
    check(
        "PR 1's periodic expiry check and this independent recheck use the IDENTICAL numeric boundary",
        pr1_expiry_m is not None and pr1_expiry_m.group(1) == "120000",
        f"PR1 boundary: {pr1_expiry_m.group(1) if pr1_expiry_m else None}",
    )
    check(
        "the age computation is a raw unsigned subtraction (millis() - captured_ms), not a signed one - wrap-safe across millis() rollover",
        "(uint32_t) (millis() - id(free_power_recovery_evidence_captured_ms))" in wrapper.body,
    )

# ---------------------------------------------------------------------------
print("")
print("[C] Fresh confirm-time read: owned + context registers, ignoring 231/246/247/249")
# ---------------------------------------------------------------------------
if dispatch is not None:
    # 2026-09-24 hardening (PR-A, Part 11): one additional fresh register-244
    # read was added - AFTER the mid-sequence 256-261 positive readback and
    # BEFORE the 268-279 write - comparing live 244 against THIS attempt's
    # already-fingerprinted confirm-time value (free_power_recovery_force_ctx_reg244),
    # NOT the Free Power lease context. 6 reads -> 7.
    check("free_power_recovery_force_restore_dispatch issues exactly 7 Modbus reads", len(dispatch.reads) == 7, f"{[ (r.start_address, r.count) for r in dispatch.reads ]}")
    read_specs = sorted((r.start_address, r.count) for r in dispatch.reads)
    check(
        "the 7 reads are: two confirm reads (230/3, 256/24), one context confirm read (244/12), one mid-sequence "
        "power readback (256/6), one pre-268 register-244 context recheck (244/1), and two final-verify reads (230/3, 256/24)",
        read_specs == [(230, 3), (230, 3), (244, 1), (244, 12), (256, 6), (256, 24), (256, 24)],
        f"{read_specs}",
    )
    check(
        "the confirm-time read populates dedicated free_power_recovery_force_live_reg* globals, "
        "NEVER PR 1's own free_power_recovery_live_reg* (already-invalidated Review evidence)",
        "id(free_power_recovery_force_live_reg230) = values[0];" in dispatch.body
        and "id(free_power_recovery_live_reg230) = values[0];" not in dispatch.body,
    )
    for addr in (231, 246, 247, 249):
        check(
            f"register {addr} has no dedicated free_power_recovery_force_*_reg{addr}/ctx_reg{addr} capture global",
            f"free_power_recovery_force_live_reg{addr}" not in dispatch.body and f"free_power_recovery_force_ctx_reg{addr}" not in dispatch.body,
        )
    check(
        "the 230-232 confirm read captures values[0] and values[2] (230, 232)",
        "id(free_power_recovery_force_live_reg230) = values[0];" in dispatch.body
        and "id(free_power_recovery_force_live_reg232) = values[2];" in dispatch.body,
    )
    # Precise positional check mirrors PR 1's own context read: count-12
    # block at 244 captures offsets 0,1,4,6,7,8,9,10,11 (244,245,248,250-255)
    # and skips 2,3,5 (246,247,249).
    ctx_assign_m = re.search(
        r"id\(free_power_recovery_force_ctx_reg244\) = values\[0\];\s*\n\s*"
        r"id\(free_power_recovery_force_ctx_reg245\) = values\[1\];\s*\n\s*"
        r"id\(free_power_recovery_force_ctx_reg248\) = values\[4\];\s*\n\s*"
        r"id\(free_power_recovery_force_ctx_reg250\) = values\[6\];\s*\n\s*"
        r"id\(free_power_recovery_force_ctx_reg251\) = values\[7\];\s*\n\s*"
        r"id\(free_power_recovery_force_ctx_reg252\) = values\[8\];\s*\n\s*"
        r"id\(free_power_recovery_force_ctx_reg253\) = values\[9\];\s*\n\s*"
        r"id\(free_power_recovery_force_ctx_reg254\) = values\[10\];\s*\n\s*"
        r"id\(free_power_recovery_force_ctx_reg255\) = values\[11\];",
        dispatch.body,
    )
    check(
        "context read offsets exactly match PR 1's own mapping (244,245,248,250-255 captured; 246,247,249 skipped)",
        ctx_assign_m is not None,
    )
    check(
        "ANY read failure (error/no_response/not_sent/bounded-wait timeout) sets free_power_recovery_force_confirm_read_failed",
        dispatch.body.count("id(free_power_recovery_force_confirm_read_failed) = true;") >= 3,
        f"count={dispatch.body.count('id(free_power_recovery_force_confirm_read_failed) = true;')}",
    )
    check(
        "a confirm-time read failure produces ZERO Force writes - the fingerprint lambda returns immediately, before any write",
        bool(re.search(
            r"if \(id\(free_power_recovery_force_confirm_read_failed\)\) \{[^}]*?return;\s*\n\s*\}",
            dispatch.body,
            re.S,
        )),
    )
    check("no modbus_client.write_multiple_registers text appears before the fingerprint comparison", dispatch.body.index("modbus_client.write_multiple_registers") > dispatch.body.index("free_power_recovery_force_expected_fingerprint"))

# ---------------------------------------------------------------------------
print("")
print("[A2] All ten distinct refusal categories exist exactly once, each with its own message")
# ---------------------------------------------------------------------------
EXPECTED_REFUSALS = (
    "refused: unsupported action",
    "refused: transaction busy",
    "refused: recovery arm not enabled",
    "refused: metadata invalid",
    "refused: not RESTORE_REQUIRED",
    "refused: no valid evidence",
    "refused: evidence expired",
    "refused: invalid evidence ID format",
    "refused: evidence ID mismatch",
    "refused: confirmation phrase mismatch",
)
if wrapper is not None:
    for _msg in EXPECTED_REFUSALS:
        check(f"refusal message {_msg!r} appears exactly once", wrapper.body.count(f'"{_msg}"') == 1)
    _actual_refusals = set(re.findall(r'"(refused: [^"]+)"', wrapper.body))
    check(
        'no other distinct "refused: ..." message exists beyond these ten',
        _actual_refusals == set(EXPECTED_REFUSALS),
        f"{_actual_refusals}",
    )
    check(
        "the marker precondition requires MARKER_RESTORE_REQUIRED exactly - MARKER_RESTORE_VERIFIED_PENDING_CLEAR "
        "(hardware already verified, only the durable clear is outstanding) and MARKER_CLEAR (no obligation) both refuse",
        "id(free_power_marker_state) != ecco_durable::MARKER_RESTORE_REQUIRED" in wrapper.body,
    )
    check(
        "Force can run even while free_power_active_persisted is true (a genuine recovery lockout, not merely "
        "gated off it) - active_persisted is never referenced in the wrapper's precondition chain at all",
        "free_power_active_persisted" not in wrapper.body,
    )

# ---------------------------------------------------------------------------
print("")
print("[D] Fresh fingerprint recomputation is BYTE-FOR-BYTE the same canonical algorithm as PR 1's review")
# ---------------------------------------------------------------------------


def _extract_fingerprint_block(body: str) -> str | None:
    m = re.search(
        r"uint64_t h = ecco_recovery_evidence::FNV64_OFFSET_BASIS;.*?"
        r"fnv1a64_update_u16le\(h, id\(free_power_recovery_(?:force_ctx|ctx)_reg255\)\);",
        body,
        re.S,
    )
    return m.group(0) if m else None


review_fp_block = _extract_fingerprint_block(review_dispatch.body) if review_dispatch else None
force_fp_block = _extract_fingerprint_block(dispatch.body) if dispatch else None
check("PR 1's review fingerprint block is found (needed for the comparison below)", review_fp_block is not None)
check("Force Restore's fresh fingerprint block is found", force_fp_block is not None)
if review_fp_block is not None and force_fp_block is not None:
    # Force's block reads from its OWN dedicated confirm-time globals
    # (force_live_*/force_ctx_*) rather than PR 1's Review globals
    # (live_*/ctx_*) - normalise that one, EXPECTED naming difference away
    # and require BYTE-FOR-BYTE identical text otherwise: same domain tag,
    # same field order, same inclusion/exclusion set, same casts, same
    # variable names for originals/intended.
    normalised_force = (
        force_fp_block
        .replace("free_power_recovery_force_live_", "free_power_recovery_live_")
        .replace("free_power_recovery_force_ctx_", "free_power_recovery_ctx_")
    )
    check(
        "after renaming Force's dedicated live/ctx globals back to PR 1's own names, the two fingerprint "
        "computation blocks are BYTE-FOR-BYTE identical (domain tag, field order, casts, everything)",
        _norm(normalised_force) == _norm(review_fp_block),
    )
check(
    "Force Restore's fingerprint uses the SAME domain tag constant as PR 1 (ecco_recovery_evidence::FINGERPRINT_DOMAIN_TAG)",
    dispatch is not None and "ecco_recovery_evidence::fnv1a64_update_str(h, ecco_recovery_evidence::FINGERPRINT_DOMAIN_TAG);" in dispatch.body,
)
check(
    "on mismatch, Force Restore refuses with zero writes and a distinct 'review again' message - it never guesses or partially continues",
    dispatch is not None
    and "if (h != id(free_power_recovery_force_expected_fingerprint)) {" in dispatch.body
    and "LIVE STATE CHANGED SINCE REVIEW" in dispatch.body,
)

# Cross-check against the independent Python re-implementation
# (registry/free_power_recovery_evidence.py) already used by PR 1's own
# tests: a mutation to ANY included field must change the fingerprint;
# excluded fields must not.
_base_originals = {230: 100, 232: 0x0011, 256: 1000, 257: 1000, 258: 1000, 259: 1000, 260: 1000, 261: 1000,
                   268: 20, 269: 20, 270: 20, 271: 20, 272: 20, 273: 20,
                   274: 0x0001, 275: 0x0001, 276: 0x0001, 277: 0x0001, 278: 0x0001, 279: 0x0001}
_base_live = dict(_base_originals)
_base_ctx = {244: 0, 245: 8000, 248: 1, 250: 0, 251: 100, 252: 200, 253: 300, 254: 400, 255: 500}
_base_kwargs = dict(end_epoch=1_700_000_000, originals=_base_originals, reg230_intended=150, reg_tou_power_intended=8000,
                     live_owned=_base_live, live_context=_base_ctx)
_base_fp = fpre.compute_fingerprint(**_base_kwargs)


def _mutated_fp(**overrides) -> int:
    kwargs = {k: (dict(v) if isinstance(v, dict) else v) for k, v in _base_kwargs.items()}
    kwargs.update(overrides)
    return fpre.compute_fingerprint(**kwargs)


check("baseline fingerprint is deterministic (recomputing twice gives the same value)", fpre.compute_fingerprint(**_base_kwargs) == _base_fp)
check("mutating end_epoch changes the fingerprint", _mutated_fp(end_epoch=_base_kwargs["end_epoch"] + 1) != _base_fp)
check("mutating reg230_intended changes the fingerprint", _mutated_fp(reg230_intended=999) != _base_fp)
check("mutating reg_tou_power_intended changes the fingerprint", _mutated_fp(reg_tou_power_intended=1234) != _base_fp)
for addr in sorted(OWNED_REGISTERS):
    mutated_originals = dict(_base_originals)
    mutated_originals[addr] = (mutated_originals[addr] + 1) & 0xFFFF
    check(f"mutating durable original register {addr} changes the fingerprint", _mutated_fp(originals=mutated_originals) != _base_fp)
    mutated_live = dict(_base_live)
    mutated_live[addr] = (mutated_live[addr] + 1) & 0xFFFF
    check(f"mutating live owned register {addr} (post-Review drift) changes the fingerprint", _mutated_fp(live_owned=mutated_live) != _base_fp)
for addr in sorted(CONTEXT_REGISTERS):
    mutated_ctx = dict(_base_ctx)
    mutated_ctx[addr] = (mutated_ctx[addr] + 1) & 0xFFFF
    check(f"mutating context register {addr} (e.g. Load/Export mode, TOU times) changes the fingerprint", _mutated_fp(live_context=mutated_ctx) != _base_fp)
check(
    "the fingerprint function's own domain/order contract excludes 231/246/247/249 by construction "
    "(they are not accepted parameters at all - see registry/free_power_recovery_evidence.py)",
    set(fpre.OWNED_REGISTER_ORDER) == OWNED_REGISTERS and set(fpre.CONTEXT_REGISTER_ORDER) == CONTEXT_REGISTERS,
)

# ---------------------------------------------------------------------------
print("")
print("[E] Force Restore's write surface is exactly the 20 Free-Power-owned registers")
# ---------------------------------------------------------------------------
check(
    "free_power_recovery_force_restore_dispatch writes exactly the 20 owned registers, nothing else",
    dispatch is not None and dispatch.written_addresses == OWNED_REGISTERS,
    f"actual={sorted(dispatch.written_addresses) if dispatch else None}",
)
check("free_power_recovery_force_restore_dispatch never writes register 244 (Load/Export Mode)", dispatch is None or 244 not in dispatch.written_addresses)
check("free_power_recovery_force_restore_dispatch never writes register 245 (export ceiling)", dispatch is None or 245 not in dispatch.written_addresses)
check("free_power_recovery_force_restore_dispatch never writes register 248 (TOU master enable)", dispatch is None or 248 not in dispatch.written_addresses)
for addr in [211, 243, 247] + list(range(250, 256)):
    check(f"free_power_recovery_force_restore_dispatch never writes register {addr}", dispatch is None or addr not in dispatch.written_addresses)
check("free_power_recovery_force_restore (the wrapper) writes nothing at all", wrapper is None or not wrapper.written_addresses)

# ---------------------------------------------------------------------------
print("")
print("[F] Write ORDER: 232 -> 256-261 -> readback(256,6) -> [gated] 268-279 -> 230 -> final verify")
# ---------------------------------------------------------------------------
GATE_NO_WRITE_FAILED = "return !id(free_power_recovery_force_write_failed);"
GATE_POWER_CONFIRMED = "return !id(free_power_recovery_force_write_failed) && id(free_power_recovery_force_power_confirmed);"
GATE_FINGERPRINT_OK = "return id(free_power_recovery_force_fingerprint_ok);"

if dispatch is not None:
    dwrites = writes_in(dispatch_flat)
    dwrite_addrs = [addr for _, addr, _ in dwrites]
    check(
        "free_power_recovery_force_restore_dispatch issues exactly 4 writes, to 232, 256, 268 and 230 in that document order",
        dwrite_addrs == [232, 256, 268, 230],
        f"{dwrite_addrs}",
    )
    if dwrite_addrs == [232, 256, 268, 230]:
        widx = {addr: i for i, addr, _ in dwrites}
        wgates = {addr: g for _, addr, g in dwrites}
        check(
            "every write is nested inside the fingerprint-confirmed gate (id(free_power_recovery_force_fingerprint_ok))",
            all(any(GATE_FINGERPRINT_OK == c and b == "then" for c, b in wgates[a]) for a in (232, 256, 268, 230)),
            f"{wgates}",
        )
        check(
            "the 256-261 write is gated on the 232 write NOT having failed",
            any(GATE_NO_WRITE_FAILED == c and b == "then" for c, b in wgates[256]),
            f"{wgates[256]}",
        )
        check(
            "268-279 is gated on !write_failed AND the positive power-confirmed flag - never write_failed alone",
            any(GATE_POWER_CONFIRMED == c and b == "then" for c, b in wgates[268]),
            f"{wgates[268]}",
        )
        check(
            "230 is gated by EVERYTHING 268-279 is gated by, PLUS one more nested `!write_failed` check "
            "re-evaluated AFTER the 268-279 write - so a 268-279 write failure (error/no_response/not_sent/"
            "bounded-wait timeout) stops 230 from being written too, per the agreed transaction spec "
            "('if the 268-279 restore fails: STOP') - adversarial review fix, 2026-09-24: 230 previously "
            "shared the exact same gate as 268-279 with no re-check in between, so a 268-279 write failure "
            "did not stop 230 from still being written",
            wgates[230] == wgates[268] + ((GATE_NO_WRITE_FAILED, "then"),),
            f"268={wgates[268]} 230={wgates[230]}",
        )
        # The mandatory positive readback boundary: a fresh READ of 256-261
        # (count 6) strictly between the 256-261 WRITE and the 268-279 WRITE.
        rboundary = [
            (i, gates) for i, (kind, gates, body) in enumerate(dispatch_flat)
            if kind == READ and body["start_address"] == 256 and body.get("count") == 6
        ]
        check(
            "exactly one fresh readback of 256-261 (count 6) exists, positioned AFTER the 256-261 write and BEFORE the 268-279 write",
            len(rboundary) == 1 and widx[256] < rboundary[0][0] < widx[268],
            f"{[i for i, _ in rboundary]} vs writes {widx}",
        )
        if len(rboundary) == 1:
            check(
                "...gated on the 256-261 write not having failed (same GATE_NO_WRITE_FAILED)",
                any(GATE_NO_WRITE_FAILED == c and b == "then" for c, b in rboundary[0][1]),
                f"{rboundary[0][1]}",
            )
        # free_power_recovery_force_power_confirmed is ONLY ever set from
        # that one readback's own on_response - never guessed, never
        # defaulted true elsewhere.
        power_confirmed_other_true = re.findall(r"id\(free_power_recovery_force_power_confirmed\)\s*=\s*true;", dispatch.body)
        check(
            "free_power_recovery_force_power_confirmed is set to a literal `true` nowhere in the dispatch (only ever from the readback's own comparison)",
            not power_confirmed_other_true,
        )
        # Final full verification: the 230/3 and 256/24 final reads both
        # occur strictly AFTER every write, and the final 256/24 read is
        # the ONLY thing that may durably clear the obligation (Phase C/D).
        final_reads = [
            i for i, (kind, gates, body) in enumerate(dispatch_flat)
            if kind == READ and i > widx[230]
        ]
        check(
            "at least the two final-verification reads (230/3, 256/24) occur strictly after the last write (230)",
            len(final_reads) >= 2,
            f"{final_reads}",
        )
        commit_offsets = [m.start() for m in re.finditer(r"ecco_durable::commit_record\(", dispatch.body)]
        first_write_pos = dispatch.body.index("start_address: 232")
        check(
            "every ecco_durable::commit_record() call happens AFTER the first write - Force never durably commits anything before it has written the hardware",
            all(off > first_write_pos for off in commit_offsets),
        )
        check(
            "Phase C (MARKER_RESTORE_VERIFIED_PENDING_CLEAR) is committed exactly once, only inside the final read's on_response",
            dispatch.body.count("ecco_durable::MARKER_RESTORE_VERIFIED_PENDING_CLEAR") >= 1
            and dispatch.body.count("bool phase_c_ok = ecco_durable::commit_record(") == 1,
        )

# ---------------------------------------------------------------------------
print("")
print("[G] Every write value comes from the durable ORIGINAL snapshot - never intended/live/hardcoded/HA input")
# ---------------------------------------------------------------------------
if dispatch is not None:
    FORBIDDEN_VALUE_TOKENS = (
        "free_power_target_reg230",
        "free_power_target_tou_power",
        "_intended",
        "recovery_force_live_",  # a fresh confirm-time READ value, never a WRITE value
        "recovery_live_",  # PR 1's own (already-invalidated) Review evidence
        "8000",  # the hardcoded TOU power ceiling substitution - never a Force write value
        "ecco_inverter_tou_power_ceiling_w",
    )
    for op in dispatch.writes:
        expr = op.value_expr or ""
        check(f"write to register {op.start_address} carries a literal values: !lambda expression (parsed)", bool(expr), f"count={op.count}")
        for token in FORBIDDEN_VALUE_TOKENS:
            check(f"write to register {op.start_address}: value expression does not reference {token!r}", token not in expr)
        ids_used = set(re.findall(r"id\((\w+)\)", expr))
        check(
            f"write to register {op.start_address}: every id(...) referenced is a free_power_snapshot_regNNN durable original",
            ids_used and all(re.fullmatch(r"free_power_snapshot_reg\d+", i) for i in ids_used),
            f"ids_used={sorted(ids_used)}",
        )
    check(
        "the 232 write is exactly id(free_power_snapshot_reg232) (a single durable original, nothing else)",
        any(op.start_address == 232 and set(re.findall(r"id\((\w+)\)", op.value_expr or "")) == {"free_power_snapshot_reg232"} for op in dispatch.writes),
    )
    check(
        "the 256-261 write is exactly the six durable original TOU Power values, in address order, nothing else",
        any(
            op.start_address == 256
            and re.findall(r"id\((\w+)\)", op.value_expr or "")
            == [f"free_power_snapshot_reg{a}" for a in range(256, 262)]
            for op in dispatch.writes
        ),
    )
    check(
        "the 268-279 write is exactly the twelve durable original SOC/flag values, in address order, nothing else",
        any(
            op.start_address == 268
            and re.findall(r"id\((\w+)\)", op.value_expr or "")
            == [f"free_power_snapshot_reg{a}" for a in range(268, 280)]
            for op in dispatch.writes
        ),
    )
    check(
        "the 230 write is exactly id(free_power_snapshot_reg230), never free_power_target_reg230 (ECCO's own intended amp value)",
        any(op.start_address == 230 and set(re.findall(r"id\((\w+)\)", op.value_expr or "")) == {"free_power_snapshot_reg230"} for op in dispatch.writes),
    )

# ---------------------------------------------------------------------------
print("")
print("[H/I/J] Behavioural reference model: exhaustive fault injection over the write/readback/verify protocol")
# ---------------------------------------------------------------------------
# Hand-maintained Python mirror of free_power_recovery_force_restore_dispatch's
# PHASE 1-6 (see the firmware script's own header comment for the design
# this implements) - the same "reference model" pattern already used by
# registry/transaction_state_machine.py. Groups C/E/F/G above independently
# prove the REAL firmware source has this write order, these gates, and
# these exact-original write values; this model exercises the resulting
# PROTOCOL under many synthetic register-bank/fault scenarios so the two
# cannot silently diverge unnoticed.
#
# `bank` is the actual hardware register state, mutated in place only when
# a write is both acknowledged (Modbus transaction succeeded) AND applied
# (the hardware genuinely changed the register) - modelling "acknowledged
# but not applied" (Test Group I) as ack=True, applied=False.
OWNED_ORDER = (230, 232) + tuple(range(256, 262)) + tuple(range(268, 280))


def simulate_force_restore(
    *,
    snapshot: dict[int, int],
    bank: dict[int, int],
    confirm_read_failed: bool = False,
    fingerprint_mismatch: bool = False,
    ack: dict[str, bool] | None = None,
    applied: dict[str, bool] | None = None,
) -> dict:
    """Returns {success, marker, operator_needed, bank}. `ack` keys:
    w232/w256/w268/w230 (write acknowledged), r256 (mid-sequence readback
    acknowledged), rfinal (final-verify reads acknowledged). `applied`
    defaults to `ack` (the normal case: an acknowledged write really
    happened) - pass applied[key]=False with ack[key]=True to model a write
    that was ACKed but never actually took effect on hardware (Test Group I)."""
    ack = dict(ack or {})
    applied = dict(applied if applied is not None else ack)
    for k in ("w232", "w256", "w268", "w230", "r256", "rfinal"):
        ack.setdefault(k, True)
        applied.setdefault(k, ack[k])

    if confirm_read_failed:
        return {"success": False, "marker": "RESTORE_REQUIRED", "operator_needed": False, "bank": dict(bank)}
    if fingerprint_mismatch:
        return {"success": False, "marker": "RESTORE_REQUIRED", "operator_needed": False, "bank": dict(bank)}

    def do_write(addrs, key):
        if not ack[key]:
            return False
        if applied[key]:
            for a in addrs:
                bank[a] = snapshot[a]
        return True

    write_failed = False

    # PHASE 1: register 232.
    if not do_write((232,), "w232"):
        write_failed = True

    # PHASE 2: registers 256-261 - only attempted if phase 1 did not fail.
    power_confirmed = False
    if not write_failed:
        if not do_write(tuple(range(256, 262)), "w256"):
            write_failed = True
        else:
            # PHASE 3: mandatory positive readback of 256-261 from the
            # ACTUAL bank (never from the write's own ack) - this is what
            # catches an ack'd-but-not-applied 256-261 write.
            if not ack["r256"]:
                write_failed = True
            else:
                power_confirmed = all(bank[a] == snapshot[a] for a in range(256, 262))
                if not power_confirmed:
                    write_failed = True

    # PHASE 4/5: 268-279 then 230 - ONLY if the positive readback confirmed.
    if not write_failed and power_confirmed:
        if not do_write(tuple(range(268, 280)), "w268"):
            write_failed = True
        if not write_failed:
            if not do_write((230,), "w230"):
                write_failed = True

    # PHASE 6: final full verification - reads the ACTUAL bank, never
    # trusts any earlier ack. Skipped entirely if an earlier phase already
    # failed (matches the dispatch's own `if: !write_failed` gate).
    success = False
    if not write_failed:
        if not ack["rfinal"]:
            write_failed = True
        else:
            success = all(bank[a] == snapshot[a] for a in OWNED_ORDER)
            if not success:
                write_failed = True

    if success:
        return {"success": True, "marker": "CLEAR", "operator_needed": False, "bank": dict(bank)}
    return {"success": False, "marker": "RESTORE_REQUIRED", "operator_needed": True, "bank": dict(bank)}


def _mk_snapshot(**overrides) -> dict[int, int]:
    snap = {230: 40, 232: 0x0010}
    snap.update({a: 900 + i * 10 for i, a in enumerate(range(256, 262))})
    snap.update({a: 15 + i for i, a in enumerate(range(268, 274))})
    snap.update({i: (i & 0xFFFC) for i in range(274, 280)})
    snap.update(overrides)
    return snap


def _violations(bank: dict[int, int], snapshot: dict[int, int]) -> set[int]:
    """V = the set of TOU Power slots (256-261) whose live value is ABOVE
    the durable original while any SOC floor (268-273) is below 100 - the
    accepted power/SOC safety invariant (see docs/FREE_POWER_MANUAL_TRANSACTION_SPEC.md
    'Power / SOC safety invariant')."""
    any_floor_below_100 = any(bank[a] < 100 for a in range(268, 274))
    if not any_floor_below_100:
        return set()
    return {a for a in range(256, 262) if bank[a] > snapshot[a]}


print("  T1/T4: every completed Force write/success ends with all 20 owned registers exactly equal to the originals")
_scenarios_ran = 0
for power_variant in ("below", "equal", "above", "mixed"):
    for soc_variant in ("originals", "intended", "third_party", "floor_below_100"):
        snapshot = _mk_snapshot()
        bank = dict(snapshot)
        if power_variant == "below":
            for a in range(256, 262):
                bank[a] = snapshot[a] - 100
        elif power_variant == "above":
            for a in range(256, 262):
                bank[a] = snapshot[a] + 500
        elif power_variant == "mixed":
            for i, a in enumerate(range(256, 262)):
                bank[a] = snapshot[a] + (200 if i % 2 == 0 else -200)
        # "equal" leaves bank == snapshot for power slots.
        if soc_variant == "intended":
            for a in range(268, 274):
                bank[a] = 100
            for a in range(274, 280):
                bank[a] = (snapshot[a] & 0xFFFC) | 0x0001
        elif soc_variant == "third_party":
            for a in range(268, 274):
                bank[a] = 77
        elif soc_variant == "floor_below_100":
            bank[268] = 5
        # "originals" leaves bank == snapshot for SOC/flags.
        bank[230] = snapshot[230] + 5
        bank[232] = snapshot[232] & ~0x0001

        v_before = _violations(bank, snapshot)
        outcome = simulate_force_restore(snapshot=snapshot, bank=bank)
        _scenarios_ran += 1
        check(
            f"[power={power_variant} soc={soc_variant}] Force succeeds from a NEITHER live state when every ack/readback is positive",
            outcome["success"] and outcome["marker"] == "CLEAR" and not outcome["operator_needed"],
            f"{outcome}",
        )
        check(
            f"[power={power_variant} soc={soc_variant}] T1/T4: after success, all 20 owned registers exactly equal their durable originals",
            all(outcome["bank"][a] == snapshot[a] for a in OWNED_ORDER),
            f"bank={outcome['bank']} snapshot={snapshot}",
        )
        v_after = _violations(outcome["bank"], snapshot)
        check(
            f"[power={power_variant} soc={soc_variant}] T2: the power-above-original-while-SOC<100 violation set V never GROWS because of a Force write "
            f"(before={sorted(v_before)}, after={sorted(v_after)})",
            v_after <= v_before,
            f"before={sorted(v_before)} after={sorted(v_after)}",
        )
check(f"T1/T2/T4 scenario matrix executed ({_scenarios_ran} combinations, all power x SOC variants)", _scenarios_ran == 16)

print("")
print("  T3: 268-279 and 230 are written ONLY after 256-261 positively reads back as exact originals")
# Adversarial review fix (2026-09-24): the previous version of this test
# compared `outcome["bank"]` against the SAME `bank` dict object that
# simulate_force_restore() had just mutated in place, so the comparison was
# checking the post-call state against itself (always equal, regardless of
# whether anything was actually written) - and separately, 268/230 already
# equalled `snapshot` in that scenario, so even a genuine (incorrect) write
# would have been invisible. Fixed here by (a) always taking an explicit
# PRE-CALL deep copy before invoking the model, and (b) initialising
# 268-279/230 to values that DIFFER from snapshot, so any unintended write
# actually changes something observable.
def _mk_pre_call_bank(snapshot: dict[int, int], *, power_offset: int, soc_floor: int) -> dict[int, int]:
    """A live bank that differs from `snapshot` everywhere Force would
    write, so an unintended write is always observable (comparing the
    post-call bank against a saved PRE-CALL copy, never against itself)."""
    bank = dict(snapshot)
    for a in range(256, 262):
        bank[a] = snapshot[a] + power_offset
    for a in range(268, 274):
        bank[a] = soc_floor
    for a in range(274, 280):
        bank[a] = (snapshot[a] & 0xFFFC) | 0x0002  # a THIRD source/mode value, distinct from snapshot's
    bank[230] = snapshot[230] + 7
    bank[232] = snapshot[232] & ~0x0001
    return bank


snapshot = _mk_snapshot()
pre_call = _mk_pre_call_bank(snapshot, power_offset=300, soc_floor=55)  # third-party raised the ceiling
bank = dict(pre_call)
outcome = simulate_force_restore(snapshot=snapshot, bank=bank, ack={"w256": True}, applied={"w256": False})
check(
    "if the 256-261 write is ACKed but does not actually change the bank (still third-party values), the "
    "readback correctly reports NOT confirmed, Force fails, and the durable lockout is set",
    not outcome["success"] and outcome["operator_needed"],
    f"{outcome}",
)
check(
    "...and 268-279 are genuinely UNCHANGED from their PRE-CALL values (compared against the saved copy, not "
    "against the same dict the model just mutated) - never lowered around the un-restored ceiling",
    all(outcome["bank"][a] == pre_call[a] for a in range(268, 280)),
    f"pre_call={ {a: pre_call[a] for a in range(268, 280)} } post={ {a: outcome['bank'][a] for a in range(268, 280)} }",
)
check(
    "...and register 230 is genuinely UNCHANGED from its PRE-CALL value",
    outcome["bank"][230] == pre_call[230],
    f"pre_call={pre_call[230]} post={outcome['bank'][230]}",
)
check(
    "as a control: 268-279/230 in this scenario start OUT OF DATE with the durable original, so an incorrect "
    "write would in fact have changed them (the test can genuinely fail, unlike the version this replaces)",
    all(pre_call[a] != snapshot[a] for a in list(range(268, 280)) + [230]),
    f"pre_call={pre_call} snapshot={snapshot}",
)

print("")
print("  T3 (ack success, hardware silently rejects the readback query itself)")
pre_call2 = _mk_pre_call_bank(snapshot, power_offset=300, soc_floor=42)
bank2 = dict(pre_call2)
outcome2 = simulate_force_restore(snapshot=snapshot, bank=bank2, ack={"r256": False})
check(
    "if the mandatory 256-261 readback itself fails to reach a terminal state (comms error), Force fails and the durable lockout is set",
    not outcome2["success"] and outcome2["operator_needed"],
    f"{outcome2}",
)
check(
    "...and 268-279/230 are genuinely UNCHANGED from their pre-call values in this scenario too",
    all(outcome2["bank"][a] == pre_call2[a] for a in list(range(268, 280)) + [230]),
    f"pre_call={pre_call2} post={outcome2['bank']}",
)

print("")
print("  T3 (Fix 2 regression guard): a DEFINITE 268-279 write failure (any cause) must stop register 230 from being dispatched at all")
_phase4_fail_outcomes: list[dict] = []
for _cause in ("on_error", "on_no_response", "on_not_sent", "bounded_wait_timeout"):
    # All four real ESPHome failure paths collapse to the same observable
    # outcome at this model's level of abstraction: the 268-279 write never
    # reaches a positive terminal success, so free_power_recovery_force_write_failed
    # becomes true. See the structural checks immediately below, which
    # independently confirm the REAL firmware has a distinct on_error/
    # on_no_response/on_not_sent handler and a distinct bounded-wait timeout
    # check for this exact write, each setting that same flag.
    pre_call3 = _mk_pre_call_bank(snapshot, power_offset=0, soc_floor=33)  # 256-261 readback WOULD confirm here
    bank3 = dict(pre_call3)
    outcome3 = simulate_force_restore(snapshot=snapshot, bank=bank3, ack={"w268": False})
    _phase4_fail_outcomes.append(outcome3)
    check(
        f"[{_cause}] a 268-279 write that never acknowledges leaves register 230 completely untouched (Phase 5 never dispatched)",
        outcome3["bank"][230] == pre_call3[230] and not outcome3["success"] and outcome3["operator_needed"],
        f"{outcome3}",
    )
    check(
        f"[{_cause}] ...and 268-279 themselves are also untouched (the write that failed never applied anything)",
        all(outcome3["bank"][a] == pre_call3[a] for a in range(268, 280)),
        f"pre_call={pre_call3} post={outcome3['bank']}",
    )

# Structural proof that the REAL firmware's 268-279 write has all four of
# these distinct failure-handling paths (on_error/on_no_response/on_not_sent/
# bounded-wait timeout), each setting free_power_recovery_force_write_failed -
# the actual mechanism the four scenarios above model as a single boolean.
if dispatch is not None:
    _w268_m = re.search(
        r"start_address: 268\n.*?on_response:.*?on_error:\n(?P<err>.*?)on_no_response:\n(?P<nr>.*?)"
        r"on_not_sent:\n(?P<ns>.*?)\n\n\s*- wait_until:.*?timeout: 3000ms\n(?P<wait_check>\s*- lambda: \|-.*?)\n\n",
        dispatch.body,
        re.S,
    )
    check("the 268-279 write block (with on_error/on_no_response/on_not_sent and the following bounded-wait check) is found", _w268_m is not None)
    if _w268_m is not None:
        for _key, _label in (("err", "on_error"), ("nr", "on_no_response"), ("ns", "on_not_sent")):
            check(
                f"the 268-279 write's {_label} handler sets free_power_recovery_force_write_failed = true",
                "id(free_power_recovery_force_write_failed) = true;" in _w268_m.group(_key),
            )
        check(
            "the 268-279 write's bounded-wait timeout check ALSO sets free_power_recovery_force_write_failed = true "
            "when the terminal flag never became true (the fourth failure path - no positive terminal success)",
            "id(free_power_recovery_force_write_failed) = true;" in _w268_m.group("wait_check")
            and "op_terminal" in _w268_m.group("wait_check"),
        )

print("")
print("  Test Group I: an ACK alone is never treated as success - the readback/final verify must positively confirm")
for phase_key, addrs in (("w232", (232,)), ("w256", tuple(range(256, 262))), ("w268", tuple(range(268, 280))), ("w230", (230,))):
    snapshot = _mk_snapshot()
    bank = dict(snapshot)
    for a in addrs:
        bank[a] = snapshot[a] + 1  # wrong final value even though the write "succeeded" (ack=True)
    outcome = simulate_force_restore(snapshot=snapshot, bank=bank, ack={phase_key: True}, applied={phase_key: False})
    check(
        f"phase {phase_key} ACKed but NOT actually applied (final value still wrong) -> Force does not report success",
        not outcome["success"] and outcome["operator_needed"],
        f"{outcome}",
    )

print("")
print("  Test Group J: durable marker transitions - PENDING_CLEAR means hardware-verified, clear-only, zero further writes")
# The model's own marker/success coupling is never independent: every
# failure scenario collected above (T3's two refusal cases plus all four
# Phase-4-failure-cause scenarios) must agree that marker == "CLEAR" if and
# only if success is True - a model that ever reported CLEAR without a
# genuine 20-register match, or reported failure while still marking
# CLEAR, would be internally inconsistent and this fails immediately.
check(
    "every simulate_force_restore() failure outcome produced by this test file has marker == 'RESTORE_REQUIRED', never 'CLEAR'",
    all(
        (o["success"] and o["marker"] == "CLEAR") or (not o["success"] and o["marker"] == "RESTORE_REQUIRED")
        for o in [outcome, outcome2, *_phase4_fail_outcomes]
    ),
    f"{[outcome, outcome2, *_phase4_fail_outcomes]}",
)
check(
    "Phase D (final durable CLEAR) is only ever attempted after Phase C (PENDING_CLEAR) has ALREADY been durably committed",
    dispatch is not None and bool(re.search(
        r"bool phase_c_ok = ecco_durable::commit_record\([^;]+;\s*\n\s*if \(phase_c_ok\) \{[^}]*?"
        r"ecco_durable::ValidMarker cleared\{ecco_durable::VALID_MARKER_MAGIC, ecco_durable::MARKER_CLEAR\};",
        dispatch.body,
        re.S,
    )),
)
check(
    "if Phase C itself fails, the marker is left untouched at RESTORE_REQUIRED (a later retry safely redoes an "
    "already-matching write) - Force never pretends success without a durable record",
    dispatch is not None and "durable marker remains RESTORE_REQUIRED for a safe future retry" in dispatch.body,
)
check(
    "if Phase C succeeds but Phase D (the final CLEAR) fails, the marker stays PENDING_CLEAR and the message says so - "
    "no Modbus rewrite is implied for that state (restore_free_power_snapshot's own existing clear-only branch handles it)",
    dispatch is not None and "durable recovery-marker clear pending, will retry" in dispatch.body,
)

# ---------------------------------------------------------------------------
print("")
print("[K] Failure lockout: any write/readback/final-verify failure preserves the obligation and blocks automatic retries")
# ---------------------------------------------------------------------------
if dispatch is not None:
    lockout_count = dispatch.body.count(
        "return id(free_power_recovery_force_write_failed) && id(free_power_marker_state) == ecco_durable::MARKER_RESTORE_REQUIRED;"
    )
    check("a write/readback/verify failure (marker still RESTORE_REQUIRED) is checked exactly once, as a dedicated fail-closed branch", lockout_count == 1, f"count={lockout_count}")
    check(
        "that branch durably commits the SAME operator-needed lockout restore_free_power_snapshot_dispatch's own repeated-verify-mismatch path uses (ecco_durable::FreePowerRetryState) - not a second mechanism",
        "ecco_durable::FreePowerRetryState retry{};" in dispatch.body and "retry.operator_needed = 1;" in dispatch.body,
    )
    check(
        "the failure branch never clears free_power_snapshot_valid, the marker, or the durable data record - the obligation is retained",
        not re.search(r"if \(id\(free_power_recovery_force_write_failed\)[^{]*\{[^}]*free_power_snapshot_valid\) = false", dispatch.body, re.S),
    )
    check(
        "the dispatch script contains zero script.execute calls of its own (no chaining, no self-scheduled retry)",
        not dispatch.dispatches,
        f"dispatches={dispatch.dispatches}",
    )
    check(
        "both Force Restore scripts declare mode: single (a re-entrant call while one is already running is a "
        "no-op, never a queued repeat)",
        SCRIPTS["free_power_recovery_force_restore"].get("mode") == "single"
        and SCRIPTS["free_power_recovery_force_restore_dispatch"].get("mode") == "single",
    )
_on_boot_m = re.search(r"on_boot:\n(.*?)\nesp32:", text, re.S)
_on_boot_body = _on_boot_m.group(1) if _on_boot_m else ""
check("on_boot: block is found (needed by the check below)", bool(_on_boot_body))
check(
    "on_boot never invokes free_power_recovery_force_restore or its dispatch",
    "free_power_recovery_force_restore" not in _on_boot_body,
)
_interval_blocks = re.findall(r"- interval: \S+\s*\n\s*then:\n((?:(?!\n  - ).)*)", text, re.S)
# FB-C2: the read-only Failback Shadow tick reads `id(<script>).is_running()` of the Force Restore scripts (never executes them);
# a bare `.is_running()` read is not an invocation, so exactly that read form is ignored. Any other mention still fails.
_is_running_read = re.compile(r"id\(free_power_recovery_force_restore(?:_dispatch)?\)\.is_running\(\)")
check(
    "no interval: trigger anywhere in the firmware invokes free_power_recovery_force_restore or its dispatch",
    all("free_power_recovery_force_restore" not in _is_running_read.sub("", blk) for blk in _interval_blocks),
    f"{len(_interval_blocks)} interval blocks scanned",
)

# ---------------------------------------------------------------------------
print("")
print("[L] PR 3 (Accept Current State) has landed - this guard is superseded")
# ---------------------------------------------------------------------------
# Historical note: earlier (PR 2-era) revisions of this section asserted
# that ACCEPT_CURRENT_STATE/accept_current_state/AcceptCurrentState appeared
# NOWHERE in firmware/registry/home-assistant/docs, because PR 3 did not
# exist yet. PR 3 (feature/free-power-recovery-accept-current-state) has now
# implemented Accept Current State for real, so that "must not exist"
# assertion is obsolete BY DESIGN - it would fail on every legitimate PR 3
# file, including this one. The equivalent (and considerably stronger)
# safety property this guard was protecting - that Accept is reachable ONLY
# through the guarded free_power_recovery_execute API path and NEVER from
# an automatic caller (on_boot, an interval, a button, a Home Assistant
# automation, or a lambda-style id(<script>).execute()) - is now proved by
# registry/tests/test_free_power_recovery_accept_current_state.py Test
# Group Q, which scans both YAML `script.execute:` forms and C++/lambda
# `id(...).execute()` forms across firmware/home-assistant/packages, wider
# coverage than this section's plain string scan ever gave.
check(
    "PR 3 is implemented: ACCEPT_CURRENT_STATE now exists in the firmware, dispatched only from the guarded "
    "API action (see test_free_power_recovery_accept_current_state.py Test Group Q for the no-auto-caller proof)",
    "ACCEPT_CURRENT_STATE" in text,
)

# ---------------------------------------------------------------------------
# Exit status. This file used to end without one, so a FAIL above was
# printed but the process still exited 0 and CI stayed green (2026-09-28
# safety-gap audit). registry/tests/test_offline_suite_exit_codes.py now
# proves, for this file and every other offline suite, that a recorded
# failure makes the process exit non-zero.
# ---------------------------------------------------------------------------
print("")
if FAILURES:
    print(f"FAILED: {len(FAILURES)} check(s)")
    for f in FAILURES:
        print(f"  - {f}")
    sys.exit(1)
print("All Force Restore Original offline checks passed.")
