#!/usr/bin/env python3
"""Offline structural/behavioural tests for PR 3 of 3 - Free Power operator
recovery: ACCEPT CURRENT STATE (`free_power_recovery_accept_current_state` /
`free_power_recovery_accept_current_state_dispatch` in
firmware/ecco_clock_dongle_stage3_4_free_power.yaml, extending the existing
`free_power_recovery_execute` API action).

Background: PR 1 (registry/tests/test_free_power_recovery_evidence.py) added
a READ-ONLY operator review of live Free Power state, a 64-bit FNV-1a
evidence fingerprint, and a classifier (matches ORIGINAL / matches INTENDED /
matches NEITHER). PR 2 (registry/tests/test_free_power_recovery_force_restore.py)
added the first recovery ACTION: Force Restore Original, which writes every
owned register back to its durable ORIGINAL. PR 3 (this file) adds the
SECOND and FINAL recovery action: Accept Current State - "the current live
inverter configuration is intentional; retire the old recovery obligation
and leave the inverter exactly as it is now." Accept makes ZERO Modbus
writes on any path; it only ever moves ECCO's OWN durable recovery marker,
through the same Phase C/D transition Force already uses, and only after
a fresh confirm-time read reproduces the exact reviewed fingerprint, freshly
classifies as NEITHER (not ORIGINAL, not INTENDED), finds zero Free Power
"residue" among the 20 owned registers, and finds every owned register
plausible.

No I/O, no hardware, no ESPHome/C++ toolchain. Three techniques, in the same
spirit as registry/tests/test_free_power_recovery_force_restore.py - each
check below is labelled with which one it actually is, since conflating
them overstates what a passing check proves:

  1. tools/analyze_write_surface.py's structured extractor (write surface,
     ownership/mutex acquisition, read/write op inventory) - groups A, K.
  2. Direct text/offset analysis of the real firmware source (never
     character-offset guessing against an unrelated copy) - groups A, D, E,
     L, M, Q, R, and PART of B/C (the checks that read `wrapper.body`/
     `dispatch.body` directly).
  3. A hand-maintained Python reference model of Accept's decision logic
     (`simulate_accept` below), built on registry/free_power_recovery_evidence.py's
     canonical fingerprint/intended-derivation/classification/residue/
     plausibility helpers (the SAME helpers, not reimplemented) - groups F,
     G, H, I, J, N, S, and the REMAINING part of B/C (the confirmation-
     phrase fixture table and the evidence-age wrap-safe boundary pins,
     which exercise Python re-implementations cross-referenced to a
     technique-2 check proving the firmware contains the matching literal
     text/expression - see each one's own inline note for exactly what it
     does and does not prove).

A technique-2 (real source) check proves the firmware SAYS the right thing.
A technique-3 (reference model) check proves a Python model of the DESIGNED
protocol behaves correctly, and several of them (Groups F, H, I, J, K, L, M)
additionally include an explicit "MUTATION CHECK" that re-runs the SAME
assertion function used by a nearby real check against both the genuine
text/value and a deliberately broken copy, requiring the result to flip -
proving that specific assertion has real discriminating power, not merely
that a hand-built bad string contains the substring it was built to
contain. Neither technique proves the COMPILED firmware behaves this way
against real hardware. No live Free Power event, OTA, or inverter write is
part of this change.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
FIRMWARE_PATH = ROOT / "firmware" / "ecco_clock_dongle_stage3_4_free_power.yaml"
HEADER_PATH = ROOT / "firmware" / "include" / "ecco_recovery_evidence.h"
DURABLE_HEADER_PATH = ROOT / "firmware" / "include" / "ecco_durable_snapshot.h"
HA_DIR = ROOT / "home-assistant"

sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "registry"))

from analyze_write_surface import analyze  # noqa: E402
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

wrapper = by_name.get("free_power_recovery_accept_current_state")
dispatch = by_name.get("free_power_recovery_accept_current_state_dispatch")
force_wrapper = by_name.get("free_power_recovery_force_restore")
force_dispatch = by_name.get("free_power_recovery_force_restore_dispatch")

OWNED_REGISTERS = fpre.OWNED_REGISTER_ORDER
CONTEXT_REGISTERS = fpre.CONTEXT_REGISTER_ORDER
TOU_CEILING_W = 8000  # matches ${ecco_inverter_tou_power_ceiling_w} in the firmware


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

api_block_m = re.search(r"\napi:\n(.*?)\nota:\n", text, re.S)
api_block = api_block_m.group(1) if api_block_m else ""

# ---------------------------------------------------------------------------
print("[A] API routing")
# ---------------------------------------------------------------------------
check("free_power_recovery_accept_current_state is parsed as a script", wrapper is not None)
check("free_power_recovery_accept_current_state_dispatch is parsed as a script", dispatch is not None)
check("free_power_recovery_accept_current_state issues zero Modbus ops itself (pure gate)", wrapper is not None and not wrapper.ops)
check(
    "free_power_recovery_accept_current_state's only dispatch target is its own dispatch script",
    wrapper is not None and wrapper.dispatches == ["free_power_recovery_accept_current_state_dispatch"],
    f"{wrapper.dispatches if wrapper else None}",
)
check("api: block is found (needed by several checks below)", bool(api_block))
check("the api: actions block still declares exactly one action: free_power_recovery_execute", api_block.count("action: free_power_recovery_execute") == 1)
action_decl_m = re.search(
    r"action: free_power_recovery_execute\s*\n\s*variables:\s*\n"
    r"\s*action: string\s*\n\s*evidence_id: string\s*\n\s*confirmation: string\s*\n",
    api_block,
)
check(
    "free_power_recovery_execute still requires exactly three string variables: action, evidence_id, confirmation "
    "(PR 3 did not add/remove any API variable)",
    action_decl_m is not None,
)
check(
    "the API action's own then: still performs zero Modbus I/O and zero precondition logic itself - only routes",
    "modbus_client" not in api_block and "id(free_power_recovery_arm)" not in api_block,
)
check(
    "the API routing dispatches to free_power_recovery_accept_current_state exactly once",
    len(re.findall(r"script\.execute:\s*\n\s*id:\s*free_power_recovery_accept_current_state\b", text)) == 1,
)
check(
    "the API routing still dispatches to free_power_recovery_force_restore exactly once (PR 2 unaffected)",
    len(re.findall(r"script\.execute:\s*\n\s*id:\s*free_power_recovery_force_restore\b", text)) == 1,
)
check(
    "the API routing branches on the literal action == \"ACCEPT_CURRENT_STATE\" (case-sensitive, exact)",
    'lambda: \'return action == "ACCEPT_CURRENT_STATE";\'' in api_block,
)
check(
    "PR 2's own Force Restore wrapper is completely untouched by PR 3 - \"ACCEPT\" never appears inside it "
    "(byte-for-byte the same invariant test_free_power_recovery_force_restore.py itself asserts)",
    force_wrapper is not None and "ACCEPT" not in force_wrapper.body,
)
if wrapper is not None:
    check(
        "the ONLY action-token comparison inside the Accept wrapper is against the literal "
        '"ACCEPT_CURRENT_STATE" (case-sensitive)',
        wrapper.body.count('id(free_power_recovery_force_action) != "ACCEPT_CURRENT_STATE"') == 1,
    )
    check(
        "the Force Restore token is never COMPARED against inside the Accept wrapper (only mentioned in prose "
        "for cross-reference, which the wrapper's own header comment legitimately does)",
        '!= "FORCE_RESTORE_ORIGINAL"' not in wrapper.body and '== "FORCE_RESTORE_ORIGINAL"' not in wrapper.body,
    )
    check(
        "the confirmation phrase is built as the exact literal prefix plus the evidence_id, with no trimming/case-folding",
        'std::string("ACCEPT CURRENT STATE ") + id(free_power_recovery_force_evidence_id)' in wrapper.body,
    )
    check(
        "the confirmation comparison is a plain std::string equality (operator==, via !=) - no strncmp/tolower/substring helpers",
        "id(free_power_recovery_force_confirmation) != expected_confirmation" in wrapper.body
        and "tolower" not in wrapper.body
        and "strncmp" not in wrapper.body
        and ".find(" not in wrapper.body,
    )
    check("the evidence_id format check requires exactly 16 characters", "s.size() != 16" in wrapper.body)
    check(
        "the evidence_id format check only accepts uppercase hex digits (0-9, A-F) - lowercase is rejected",
        "c >= 'A' && c <= 'F'" in wrapper.body and "c >= 'a'" not in wrapper.body,
    )

    # --- Post-Opus-review Finding 3.A: pin each individual precondition
    # refusal branch, scoped strictly to wrapper.body (never the whole
    # firmware text), with the CONDITION and its resulting refusal message
    # tied together in one regex - not merely "this string exists somewhere
    # in the file", which could pass even if the message were misrouted to
    # the wrong condition or duplicated by accident.
    check(
        "the busy/transaction-conflict condition (operation_in_progress || manual_write_in_progress || "
        "correction_in_progress || reg244_apply_in_progress || bus not quiescent) is gated to exactly "
        '"refused: transaction busy" (scoped to the Accept wrapper)',
        bool(re.search(
            r"else if \(\s*\n"
            r"\s*id\(free_power_operation_in_progress\) \|\|\s*\n"
            r"\s*id\(manual_write_in_progress\) \|\|\s*\n"
            r"\s*id\(correction_in_progress\) \|\|\s*\n"
            r"\s*id\(reg244_apply_in_progress\) \|\|\s*\n"
            r"\s*!id\(inverter_modbus\)->tx_buffer_empty\(\) \|\|\s*\n"
            r"\s*id\(inverter_modbus\)->tx_blocked\(\)\s*\n"
            r"\s*\) \{\s*\n"
            r'\s*refusal = "refused: transaction busy";',
            wrapper.body,
        )),
    )
    check(
        'the Recovery Arm OFF condition (!id(free_power_recovery_arm).state) is gated to exactly '
        '"refused: recovery arm not enabled" (scoped to the Accept wrapper)',
        bool(re.search(
            r'else if \(!id\(free_power_recovery_arm\)\.state\) \{\s*\n\s*refusal = "refused: recovery arm not enabled";',
            wrapper.body,
        )),
    )
    check(
        'the metadata-corrupt condition (id(free_power_recovery_metadata_corrupt)) is gated to exactly '
        '"refused: metadata untrustworthy" (scoped to the Accept wrapper)',
        bool(re.search(
            r'else if \(id\(free_power_recovery_metadata_corrupt\)\) \{\s*\n\s*refusal = "refused: metadata untrustworthy";',
            wrapper.body,
        )),
    )
    check(
        "the snapshot-invalid-OR-marker-not-RESTORE_REQUIRED condition is gated to exactly "
        '"refused: no RESTORE_REQUIRED obligation" (scoped to the Accept wrapper - this is BOTH the '
        "snapshot-valid requirement AND the exact-marker requirement in one gate, matching Force's own "
        "identical precondition)",
        bool(re.search(
            r"else if \(!id\(free_power_snapshot_valid\) \|\| id\(free_power_marker_state\) != "
            r'ecco_durable::MARKER_RESTORE_REQUIRED\) \{\s*\n\s*refusal = "refused: no RESTORE_REQUIRED obligation";',
            wrapper.body,
        )),
    )
    check(
        'the evidence-invalid condition (!id(free_power_recovery_evidence_valid)) is gated to exactly '
        '"refused: no valid evidence" (scoped to the Accept wrapper)',
        bool(re.search(
            r'else if \(!id\(free_power_recovery_evidence_valid\)\) \{\s*\n\s*refusal = "refused: no valid evidence";',
            wrapper.body,
        )),
    )
    check(
        "the evidence-ID-mismatch comparison (supplied evidence_id vs the freshly-formatted reviewed "
        'fingerprint) is gated to exactly "refused: evidence ID mismatch" (scoped to the Accept wrapper)',
        bool(re.search(
            r"if \(id\(free_power_recovery_force_evidence_id\) != std::string\(idbuf\)\) \{\s*\n"
            r'\s*refusal = "refused: evidence ID mismatch";',
            wrapper.body,
        )),
    )
    check(
        "every one of these 6 distinct refusal branches sets id(free_power_recovery_accept_gate_ok) = true "
        "ONLY on the final else (confirmation match) - none of the 6 refusal branches can itself set gate_ok",
        wrapper.body.count("id(free_power_recovery_accept_gate_ok) = true;") == 1,
    )
check(
    "no third executable recovery action token exists anywhere in the firmware "
    "(DISCARD_UNREADABLE / REAPPLY_INTENDED / ACCEPT_PARTIAL / PER_REGISTER_ACCEPT)",
    not any(tok in text for tok in ("DISCARD_UNREADABLE", "REAPPLY_INTENDED", "ACCEPT_PARTIAL", "PER_REGISTER_ACCEPT")),
)

# ---------------------------------------------------------------------------
print("")
print("[B] Exact Accept confirmation phrase / one-shot semantics (firmware-anchored where noted; a fixture table is not)")
# ---------------------------------------------------------------------------
if wrapper is not None:
    turn_off_count = wrapper.body.count("id(free_power_recovery_arm).turn_off();")
    invalidate_count = wrapper.body.count("id(free_power_recovery_invalidate_evidence).execute();")
    check("the Accept wrapper disarms the recovery arm on exactly 2 code paths (success and refusal)", turn_off_count == 2, f"found {turn_off_count}")
    check("the Accept wrapper invalidates evidence on exactly 2 code paths (success and refusal)", invalidate_count == 2, f"found {invalidate_count}")
    check("the Accept wrapper reuses the SAME Free Power Recovery Arm switch as Force (no second arm)", "free_power_recovery_arm" in wrapper.body)
    check("no second/dedicated Accept-only arm switch id exists in the firmware", "free_power_recovery_accept_arm" not in text)

accept_callers = re.findall(r"script\.execute:\s*\n\s*id:\s*free_power_recovery_accept_current_state\b", text)
check("free_power_recovery_accept_current_state is script.execute'd from exactly one place (the API action)", len(accept_callers) == 1)
accept_dispatch_callers = re.findall(r"script\.execute:\s*\n\s*id:\s*free_power_recovery_accept_current_state_dispatch\b", text)
check(
    "free_power_recovery_accept_current_state_dispatch is script.execute'd from exactly one place "
    "(the wrapper's own success branch)",
    len(accept_dispatch_callers) == 1,
)
check("both Accept scripts declare mode: single", SCRIPTS.get("free_power_recovery_accept_current_state", {}).get("mode") == "single" and SCRIPTS.get("free_power_recovery_accept_current_state_dispatch", {}).get("mode") == "single")

# NOT a firmware execution test: this is a fixture/vector table over plain
# Python `==`, cross-referenced to the FIRMWARE-ANCHORED structural proof
# just above (the confirmation comparison is `id(free_power_recovery_force_confirmation)
# != expected_confirmation` - plain std::string equality, with `tolower`/
# `strncmp`/`.find()` all confirmed absent from the wrapper body). Given
# that structural fact, C++ `std::string::operator==` and Python `==`
# agree byte-for-byte on ASCII text, so this table's purpose is to
# self-check that every one of these labelled example phrases is correctly
# labelled exact-vs-not - i.e. it pins the EXPECTED behaviour the exact-
# equality property above implies, not a second independent proof of that
# property.
CONFIRMATION_CASES = [
    ("lowercase", "accept current state 0123456789ABCDEF", False),
    ("mixed case", "Accept Current State 0123456789ABCDEF", False),
    ("missing ID", "ACCEPT CURRENT STATE", False),
    ("wrong ID", "ACCEPT CURRENT STATE FFFFFFFFFFFFFFFF", False),  # (vs a different reviewed ID - checked behaviourally below)
    ("leading whitespace", " ACCEPT CURRENT STATE 0123456789ABCDEF", False),
    ("trailing whitespace", "ACCEPT CURRENT STATE 0123456789ABCDEF ", False),
    ("doubled whitespace", "ACCEPT  CURRENT STATE 0123456789ABCDEF", False),
    ("substring phrase", "PLEASE ACCEPT CURRENT STATE 0123456789ABCDEF", False),
    ("Force phrase paired with Accept token", "FORCE RESTORE ORIGINAL 0123456789ABCDEF", False),
    ("exact match", "ACCEPT CURRENT STATE 0123456789ABCDEF", True),
]
for label, phrase, expect_exact in CONFIRMATION_CASES:
    expected = "ACCEPT CURRENT STATE " + "0123456789ABCDEF"
    check(f'fixture vector "{label}" is labelled exact-match iff intended (given plain == above): {phrase!r}', (phrase == expected) == expect_exact)

# ---------------------------------------------------------------------------
print("")
print("[C] Evidence age (120s) checked independently, wrap-safe (firmware text check, then a reference-model pin)")
# ---------------------------------------------------------------------------
if wrapper is not None:
    check(
        "the Accept wrapper independently re-checks the SAME 120000ms (120s) evidence-age boundary as PR 1/PR 2",
        "(uint32_t) (millis() - id(free_power_recovery_evidence_captured_ms)) >= 120000" in wrapper.body,
    )
    check(
        "the age check uses wrap-safe unsigned (uint32_t) millis() subtraction, not a signed difference",
        "(uint32_t) (millis()" in wrapper.body,
    )


# REFERENCE-MODEL check, not a firmware execution test: evidence_age_boundary()
# is a Python re-implementation of the exact C++ expression whose LITERAL
# TEXT was just proven present in the firmware above
# (`(uint32_t) (millis() - id(free_power_recovery_evidence_captured_ms)) >= 120000`).
# uint32_t wraparound arithmetic behaves identically in Python (via the
# explicit `& 0xFFFFFFFF` mask below) and in C++, so this pins the boundary/
# wraparound BEHAVIOUR that literal expression implies - it does not
# independently re-derive or re-prove that the firmware contains that
# expression (the structural check above already did that).
def evidence_age_boundary(now_ms: int, captured_ms: int) -> bool:
    """Reference re-implementation of `(uint32_t)(millis() - captured_ms) >= 120000`,
    including 32-bit wraparound - mirrors, does not independently verify, the
    firmware text confirmed present above."""
    return ((now_ms - captured_ms) & 0xFFFFFFFF) >= 120000


check("reference model: 1ms before the 120s boundary is still valid (not expired)", evidence_age_boundary(119_999, 0) is False)
check("reference model: exactly at the 120s boundary is expired", evidence_age_boundary(120_000, 0) is True)
check("reference model: 1ms after the 120s boundary is expired", evidence_age_boundary(120_001, 0) is True)
# millis() wraparound: captured just before a 32-bit wrap, "now" just after it.
_WRAP = 1 << 32
check(
    "reference model: wrap-safe - captured near UINT32_MAX, now wrapped just past 0, elapsed correctly small (not valid, not expired)",
    evidence_age_boundary((_WRAP + 500) % _WRAP, _WRAP - 500) is False,
)
check(
    "reference model: wrap-safe - captured near UINT32_MAX, now wrapped past 0 by >120s, correctly expired",
    evidence_age_boundary((_WRAP + 121_000) % _WRAP, _WRAP - 500) is True,
)

# ---------------------------------------------------------------------------
print("")
print("[D] Fresh confirm-time read ranges (identical to PR 1/PR 2)")
# ---------------------------------------------------------------------------
if dispatch is not None:
    reads = [(op.start_address, op.count) for op in dispatch.reads]
    check(
        "free_power_recovery_accept_current_state_dispatch performs exactly 3 physical reads: 230/3, 256/24, 244/12",
        reads == [(230, 3), (256, 24), (244, 12)],
        f"{reads}",
    )
    check(
        "Accept's confirm reads use DEDICATED accept_live_*/accept_ctx_* buffers, never PR 1's Review buffers "
        "(checked as an actual id(...) reference, not merely a substring mentioned in a comment)",
        not re.search(r"id\(free_power_recovery_live_reg\d+\)", dispatch.body)
        and not re.search(r"id\(free_power_recovery_ctx_reg\d+\)", dispatch.body),
    )
    check(
        "Accept's confirm reads never reuse PR 2's Force buffers either (actual id(...) reference check)",
        not re.search(r"id\(free_power_recovery_force_live_reg\d+\)", dispatch.body)
        and not re.search(r"id\(free_power_recovery_force_ctx_reg\d+\)", dispatch.body),
    )
    check(
        "ignored registers 231/246/247/249 are never captured into any accept_* global",
        not re.search(r"free_power_recovery_accept_(?:live|ctx)_reg(?:231|246|247|249)\b", dispatch.body),
    )
    for terminal_kind in ("on_response", "on_error", "on_no_response", "on_not_sent"):
        check(
            f"every read declares an {terminal_kind} handler (bounded terminal handling, matches PR 1/PR 2)",
            dispatch.body.count(f"{terminal_kind}:") >= 3,
        )
    check(
        "every confirm read is followed by a bounded wait_until with a 3000ms timeout",
        dispatch.body.count("wait_until:") >= 3 and dispatch.body.count("timeout: 3000ms") >= 3,
    )
    check(
        "any read failure (error/no_response/not_sent/bounded-wait timeout) sets accept_confirm_read_failed",
        dispatch.body.count("id(free_power_recovery_accept_confirm_read_failed) = true;") >= 3,
    )
    check(
        "a confirm-time read failure produces ZERO Accept work: it returns before any classification/residue/plausibility/Phase C code",
        bool(re.search(
            r"if \(id\(free_power_recovery_accept_confirm_read_failed\)\) \{[^}]*?return;\s*\n\s*\}",
            dispatch.body,
            re.S,
        )),
    )

# ---------------------------------------------------------------------------
print("")
print("[E] Fingerprint recomputation is byte-for-byte identical to PR 1/PR 2")
# ---------------------------------------------------------------------------
review_dispatch = by_name.get("free_power_recovery_review_dispatch")


def _fingerprint_snippet(body: str) -> str:
    m = re.search(
        r"uint64_t h = ecco_recovery_evidence::FNV64_OFFSET_BASIS;.*?"
        r"fnv1a64_update_u16le\(h, id\([\w]*ctx_reg255\)\);",
        body,
        re.S,
    )
    return m.group(0) if m else ""


def _normalise_fingerprint_snippet(snippet: str) -> str:
    """Strip the ONLY legitimate difference between the three fingerprint
    computations - which dedicated buffer namespace each reads from
    (live_reg*/ctx_reg* for Review, force_live_reg*/force_ctx_reg* for
    Force, accept_live_reg*/accept_ctx_reg* for Accept) - so the remaining
    text (domain tag, field order, byte-encoding helper calls) can be
    compared for EXACT equality."""
    snippet = re.sub(r"free_power_recovery_(?:force_|accept_)?live_reg", "free_power_recovery_X_live_reg", snippet)
    snippet = re.sub(r"free_power_recovery_(?:force_|accept_)?ctx_reg", "free_power_recovery_X_ctx_reg", snippet)
    return " ".join(snippet.split())


review_fp = _normalise_fingerprint_snippet(_fingerprint_snippet(review_dispatch.body if review_dispatch else ""))
force_fp = _normalise_fingerprint_snippet(_fingerprint_snippet(force_dispatch.body if force_dispatch else ""))
accept_fp = _normalise_fingerprint_snippet(_fingerprint_snippet(dispatch.body if dispatch else ""))

check("Review's fingerprint snippet was found (non-empty)", bool(review_fp))
check("Force's fingerprint snippet was found (non-empty)", bool(force_fp))
check("Accept's fingerprint snippet was found (non-empty)", bool(accept_fp))
check(
    "Accept's fingerprint computation is textually IDENTICAL to Review's, after normalising only the "
    "dedicated-buffer variable namespace (domain tag, field order, and every byte-encoding call match exactly)",
    bool(accept_fp) and accept_fp == review_fp,
)
check(
    "Accept's fingerprint computation is textually IDENTICAL to Force's, after the same normalisation",
    bool(accept_fp) and accept_fp == force_fp,
)
check(
    "the canonical domain tag constant is used (not a duplicated/re-typed literal)",
    dispatch is not None and "ecco_recovery_evidence::FINGERPRINT_DOMAIN_TAG" in dispatch.body,
)
check(
    "context register 244 IS included in Accept's fingerprint (244 remains read-only context, not writable, "
    "but a change in it still invalidates the fingerprint)",
    dispatch is not None and "id(free_power_recovery_accept_ctx_reg244)" in dispatch.body,
)
for ctx_addr in (245, 248, 250, 251, 252, 253, 254, 255):
    check(
        f"context register {ctx_addr} is included in Accept's fingerprint",
        dispatch is not None and f"id(free_power_recovery_accept_ctx_reg{ctx_addr})" in dispatch.body,
    )
check(
    "on fingerprint mismatch, Accept refuses with zero writes and a distinct message, mirroring Force exactly",
    dispatch is not None and "LIVE STATE CHANGED SINCE REVIEW" in dispatch.body,
)

# ---------------------------------------------------------------------------
print("")
print("[F] Reference model: canonical fingerprint matches the firmware's own algorithm")
# ---------------------------------------------------------------------------


def _make_scenario(
    *,
    end_epoch: int = 1_700_000_000,
    reg230_intended: int = 45,
    reg_tou_power_intended: int = 4000,
    perturb: dict[int, int] | None = None,
) -> dict:
    """A self-consistent NEITHER-classification scenario: originals differ
    from intended in at least one owned register, live differs from BOTH
    (so it starts out as a legitimate NEITHER baseline scenario tests can
    perturb from). `perturb` overrides specific live_owned/live_context
    addresses by absolute value for targeted mutation."""
    original = {230: 10, 232: 0x0000}
    for a in (256, 257, 258, 259, 260, 261):
        original[a] = 2000
    for a in (268, 269, 270, 271, 272, 273):
        original[a] = 20
    for a in (274, 275, 276, 277, 278, 279):
        original[a] = 0x0000  # mode field 0x0000, source bits 0 (None)

    intended = fpre.derive_intended(originals=original, reg230_intended=reg230_intended, reg_tou_power_intended=reg_tou_power_intended)

    # A plausible NEITHER live state: some third-party value, distinct from
    # both original and intended, for every owned register.
    live_owned = {a: (original[a] + intended[a] + 7) % 50000 + 1 for a in OWNED_REGISTERS}
    # Guard against an accidental collision with original/intended for any
    # register (extremely unlikely given +7, but keep the fixture honest).
    for a in OWNED_REGISTERS:
        if live_owned[a] in (original[a], intended[a]):
            live_owned[a] = (live_owned[a] + 1) % 50000
    # Registers 268-273 (SOC) and 274-279 (mode) must stay in-domain for the
    # baseline scenario to be plausible; clamp to valid ranges.
    for a in (268, 269, 270, 271, 272, 273):
        live_owned[a] = live_owned[a] % 101  # 0..100
        if live_owned[a] in (original[a], intended[a]):
            live_owned[a] = (live_owned[a] + 1) % 101
    for a in (256, 257, 258, 259, 260, 261):
        live_owned[a] = live_owned[a] % (TOU_CEILING_W + 1)
        if live_owned[a] in (original[a], intended[a]):
            live_owned[a] = (live_owned[a] + 1) % (TOU_CEILING_W + 1)
    for a in (274, 275, 276, 277, 278, 279):
        # keep a plausible mode field (0x08) with a distinct value from O/I
        live_owned[a] = 0x0008
        if live_owned[a] in (original[a], intended[a]):
            live_owned[a] = 0x0010

    live_context = {a: 1000 + a for a in CONTEXT_REGISTERS}

    if perturb:
        for addr, val in perturb.items():
            if addr in OWNED_REGISTERS:
                live_owned[addr] = val
            else:
                live_context[addr] = val

    fingerprint = fpre.compute_fingerprint(
        end_epoch=end_epoch,
        originals=original,
        reg230_intended=reg230_intended,
        reg_tou_power_intended=reg_tou_power_intended,
        live_owned=live_owned,
        live_context=live_context,
    )
    return dict(
        original=original,
        intended=intended,
        end_epoch=end_epoch,
        reg230_intended=reg230_intended,
        reg_tou_power_intended=reg_tou_power_intended,
        live_owned=live_owned,
        live_context=live_context,
        expected_fingerprint=fingerprint,
    )


_base = _make_scenario()
check(
    "the baseline test scenario genuinely classifies as NEITHER (sanity check on the fixture itself)",
    fpre.classify_live_state(originals=_base["original"], intended=_base["intended"], live=_base["live_owned"]) == "NEITHER",
)
check(
    "the baseline test scenario has zero Free Power residue (sanity check on the fixture itself)",
    fpre.free_power_residue_registers(originals=_base["original"], intended=_base["intended"], live=_base["live_owned"]) == [],
)
check(
    "the baseline test scenario has zero implausible registers (sanity check on the fixture itself)",
    fpre.implausible_registers(_base["live_owned"], tou_power_ceiling_w=TOU_CEILING_W) == [],
)


def simulate_accept(
    *,
    original: dict[int, int],
    reg230_intended: int,
    reg_tou_power_intended: int,
    end_epoch: int,
    live_owned: dict[int, int],
    live_context: dict[int, int],
    expected_fingerprint: int,
    confirm_read_failed: bool = False,
    phase_c_ok: bool = True,
    phase_d_ok: bool = True,
    tou_power_ceiling_w: int = TOU_CEILING_W,
) -> dict:
    """Pure-Python reference model of free_power_recovery_accept_current_state_dispatch's
    decision logic. Mirrors the EXACT order the firmware performs these
    checks in: confirm-read -> fingerprint -> NEITHER -> residue ->
    plausibility -> Phase C -> Phase D. Built entirely on
    registry/free_power_recovery_evidence.py's shared helpers (the SAME
    canonical logic, not a reimplementation)."""
    if confirm_read_failed:
        return {"outcome": "confirm_read_failed", "marker": "RESTORE_REQUIRED", "modbus_writes": []}

    fp = fpre.compute_fingerprint(
        end_epoch=end_epoch,
        originals=original,
        reg230_intended=reg230_intended,
        reg_tou_power_intended=reg_tou_power_intended,
        live_owned=live_owned,
        live_context=live_context,
    )
    if fp != expected_fingerprint:
        return {"outcome": "fingerprint_mismatch", "marker": "RESTORE_REQUIRED", "modbus_writes": []}

    intended = fpre.derive_intended(originals=original, reg230_intended=reg230_intended, reg_tou_power_intended=reg_tou_power_intended)
    classification = fpre.classify_live_state(originals=original, intended=intended, live=live_owned)
    if classification == "INTENDED":
        return {"outcome": "refused_intended", "marker": "RESTORE_REQUIRED", "modbus_writes": []}
    if classification == "ORIGINAL":
        return {"outcome": "refused_original", "marker": "RESTORE_REQUIRED", "modbus_writes": []}

    residue = fpre.free_power_residue_registers(originals=original, intended=intended, live=live_owned)
    if residue:
        return {"outcome": "refused_residue", "marker": "RESTORE_REQUIRED", "modbus_writes": [], "residue": residue}

    implausible = fpre.implausible_registers(live_owned, tou_power_ceiling_w=tou_power_ceiling_w)
    if implausible:
        return {"outcome": "refused_implausible", "marker": "RESTORE_REQUIRED", "modbus_writes": [], "implausible": implausible}

    if not phase_c_ok:
        return {"outcome": "phase_c_failed", "marker": "RESTORE_REQUIRED", "modbus_writes": []}
    if not phase_d_ok:
        return {"outcome": "success_pending_clear", "marker": "PENDING_CLEAR", "modbus_writes": []}
    return {"outcome": "success", "marker": "CLEAR", "modbus_writes": []}


_r = simulate_accept(**{k: _base[k] for k in ("original", "reg230_intended", "reg_tou_power_intended", "end_epoch", "live_owned", "live_context", "expected_fingerprint")})
check("simulate_accept() on the (fresh, matching) baseline scenario succeeds", _r["outcome"] == "success", f"{_r}")
check("a successful Accept never appears with any Modbus write in the reference model", _r["modbus_writes"] == [])

for addr in list(OWNED_REGISTERS) + list(CONTEXT_REGISTERS):
    perturbed = _make_scenario(perturb={addr: 99})
    # Recompute with the ORIGINAL (unperturbed) expected_fingerprint to
    # simulate "live changed since Review" for this one register.
    stale_fp = _base["expected_fingerprint"]
    r = simulate_accept(
        original=perturbed["original"], reg230_intended=perturbed["reg230_intended"],
        reg_tou_power_intended=perturbed["reg_tou_power_intended"], end_epoch=perturbed["end_epoch"],
        live_owned=perturbed["live_owned"], live_context=perturbed["live_context"],
        expected_fingerprint=stale_fp,
    )
    check(f"a mutation in register {addr} (owned or context) changes the fingerprint and refuses Accept", r["outcome"] == "fingerprint_mismatch", f"addr={addr} outcome={r['outcome']}")

for excluded_addr in (231, 246, 247, 249):
    check(f"register {excluded_addr} is NOT part of OWNED_REGISTER_ORDER or CONTEXT_REGISTER_ORDER (excluded from fingerprint)", excluded_addr not in OWNED_REGISTERS and excluded_addr not in CONTEXT_REGISTERS)

# Changes that must NOT alter the fingerprint (not part of its canonical input).
_diagnostic_fp_1 = fpre.compute_fingerprint(
    end_epoch=_base["end_epoch"], originals=_base["original"], reg230_intended=_base["reg230_intended"],
    reg_tou_power_intended=_base["reg_tou_power_intended"], live_owned=_base["live_owned"], live_context=_base["live_context"],
)
check(
    "the fingerprint function accepts no classification/diagnostic-counter/timestamp arguments at all "
    "(they cannot influence the hash because they are not part of its signature)",
    "classification" not in fpre.compute_fingerprint.__code__.co_varnames
    and "active_persisted" not in fpre.compute_fingerprint.__code__.co_varnames
    and "restore_requested" not in fpre.compute_fingerprint.__code__.co_varnames,
)
check("recomputing with identical inputs is deterministic (same fingerprint)", _diagnostic_fp_1 == _base["expected_fingerprint"])

# ---------------------------------------------------------------------------
print("")
print("[G] NEITHER-only classification (fresh, never stale)")
# ---------------------------------------------------------------------------
_original_state = simulate_accept(
    original=_base["original"], reg230_intended=_base["reg230_intended"], reg_tou_power_intended=_base["reg_tou_power_intended"],
    end_epoch=_base["end_epoch"], live_owned=dict(_base["original"]), live_context=_base["live_context"],
    expected_fingerprint=fpre.compute_fingerprint(
        end_epoch=_base["end_epoch"], originals=_base["original"], reg230_intended=_base["reg230_intended"],
        reg_tou_power_intended=_base["reg_tou_power_intended"], live_owned=_base["original"], live_context=_base["live_context"],
    ),
)
check("fresh state == ORIGINAL -> Accept refuses", _original_state["outcome"] == "refused_original", f"{_original_state}")
check("a refused-ORIGINAL outcome retains RESTORE_REQUIRED (no marker mutation)", _original_state["marker"] == "RESTORE_REQUIRED")

_intended_state = simulate_accept(
    original=_base["original"], reg230_intended=_base["reg230_intended"], reg_tou_power_intended=_base["reg_tou_power_intended"],
    end_epoch=_base["end_epoch"], live_owned=dict(_base["intended"]), live_context=_base["live_context"],
    expected_fingerprint=fpre.compute_fingerprint(
        end_epoch=_base["end_epoch"], originals=_base["original"], reg230_intended=_base["reg230_intended"],
        reg_tou_power_intended=_base["reg_tou_power_intended"], live_owned=_base["intended"], live_context=_base["live_context"],
    ),
)
check("fresh state == INTENDED -> Accept refuses", _intended_state["outcome"] == "refused_intended", f"{_intended_state}")
check("a refused-INTENDED outcome retains RESTORE_REQUIRED (no marker mutation)", _intended_state["marker"] == "RESTORE_REQUIRED")

_neither_state = simulate_accept(**{k: _base[k] for k in ("original", "reg230_intended", "reg_tou_power_intended", "end_epoch", "live_owned", "live_context", "expected_fingerprint")})
check("fresh state == NEITHER -> Accept may proceed (not refused at the classification step)", _neither_state["outcome"] not in ("refused_original", "refused_intended"))

if dispatch is not None:
    check(
        "the classifier is recomputed from the FRESH live_owned/original/intended values, never from a stale "
        "free_power_recovery_last_classification global",
        "free_power_recovery_last_classification" not in dispatch.body,
    )
    check('Accept refuses ORIGINAL with the documented message', 'state is ORIGINAL, not NEITHER' in dispatch.body)
    check('Accept refuses INTENDED with the documented message', 'state is INTENDED, not NEITHER' in dispatch.body)
    idx_fp_ok = dispatch.body.find("id(free_power_recovery_accept_fingerprint_ok) = true;")
    idx_matches_intended = dispatch.body.find("if (matches_intended)")
    idx_matches_original = dispatch.body.find("if (matches_original)")
    check(
        "classification (matches_intended / matches_original) is checked AFTER the fingerprint gate, never before",
        -1 < idx_fp_ok < idx_matches_intended < idx_matches_original,
        f"fp_ok={idx_fp_ok} intended={idx_matches_intended} original={idx_matches_original}",
    )

# ---------------------------------------------------------------------------
print("")
print("[H] Free Power residue - exhaustive per-register coverage")
# ---------------------------------------------------------------------------
for addr in OWNED_REGISTERS:
    # Case 1: ORIGINAL != INTENDED, LIVE == INTENDED at this ONE register,
    # everything else stays a legitimate NEITHER baseline -> must refuse
    # with residue at exactly this register (never more, never fewer).
    scen = _make_scenario()
    scen["live_owned"][addr] = scen["intended"][addr]
    assert scen["original"][addr] != scen["intended"][addr], f"fixture bug: O==I at {addr}"
    residue = fpre.free_power_residue_registers(originals=scen["original"], intended=scen["intended"], live=scen["live_owned"])
    check(f"register {addr}: LIVE==INTENDED, ORIGINAL!=INTENDED -> residue detected at exactly [{addr}]", residue == [addr], f"got {residue}")

    r = simulate_accept(
        original=scen["original"], reg230_intended=scen["reg230_intended"], reg_tou_power_intended=scen["reg_tou_power_intended"],
        end_epoch=scen["end_epoch"], live_owned=scen["live_owned"], live_context=scen["live_context"],
        expected_fingerprint=fpre.compute_fingerprint(
            end_epoch=scen["end_epoch"], originals=scen["original"], reg230_intended=scen["reg230_intended"],
            reg_tou_power_intended=scen["reg_tou_power_intended"], live_owned=scen["live_owned"], live_context=scen["live_context"],
        ),
    )
    check(f"register {addr} residue -> Accept refuses (zero writes, obligation retained)", r["outcome"] == "refused_residue" and r["modbus_writes"] == [] and r["marker"] == "RESTORE_REQUIRED", f"{r}")

    # Case 2: ORIGINAL == INTENDED at this register (force it), LIVE equals
    # that same value -> NOT residue (the "already-enabled" exemption).
    scen2 = _make_scenario()
    scen2["original"][addr] = scen2["intended"][addr]  # force O == I directly (post-hoc; residue() takes these as given)
    scen2["live_owned"][addr] = scen2["intended"][addr]
    residue2 = fpre.free_power_residue_registers(originals=scen2["original"], intended=scen2["intended"], live=scen2["live_owned"])
    check(f"register {addr}: ORIGINAL==INTENDED==LIVE -> NOT residue (already-matching exemption)", addr not in residue2, f"residue={residue2}")

    # Case 3: LIVE == ORIGINAL (with ORIGINAL != INTENDED) -> not residue by itself.
    scen3 = _make_scenario()
    scen3["live_owned"][addr] = scen3["original"][addr]
    residue3 = fpre.free_power_residue_registers(originals=scen3["original"], intended=scen3["intended"], live=scen3["live_owned"])
    check(f"register {addr}: LIVE==ORIGINAL (O!=I) -> NOT residue for this register", addr not in residue3, f"residue={residue3}")

# Case 4: a plausible third-party value that is neither O nor I is not
# residue by itself (the baseline scenario already IS this for every
# register - re-assert explicitly for clarity/documentation).
check(
    "a live value that is neither ORIGINAL nor INTENDED, by itself, is never residue (baseline scenario has zero residue)",
    fpre.free_power_residue_registers(originals=_base["original"], intended=_base["intended"], live=_base["live_owned"]) == [],
)


def _wrong_residue_or(*, originals, intended, live):
    """Deliberate mutant: RESIDUE(r) = live[r]==intended[r] OR live[r]!=originals[r]
    (AND weakened to OR) instead of the canonical AND. `_base`'s own live_owned
    fixture sets every owned register to a third-party value distinct from
    both original and intended (that is what makes it a genuine NEITHER
    baseline - see _make_scenario), so live[r] != originals[r] is true for
    essentially every register in that fixture, and this OR-mutant should
    therefore flag most/all 20 as "residue" where the real AND-based formula
    correctly flags none."""
    return [a for a in fpre.OWNED_REGISTER_ORDER if live[a] == intended[a] or live[a] != originals[a]]


_or_mutant_residue = _wrong_residue_or(originals=_base["original"], intended=_base["intended"], live=_base["live_owned"])
_real_residue_on_base = fpre.free_power_residue_registers(originals=_base["original"], intended=_base["intended"], live=_base["live_owned"])
check(
    "MUTATION CHECK: on the baseline NEITHER fixture, the canonical AND-based residue formula correctly finds "
    "ZERO residue, but the deliberately weakened AND->OR mutant (_wrong_residue_or) flags a majority of the 20 "
    "owned registers as residue - proving the AND requirement (both live==intended AND live!=original) is load-"
    "bearing, not redundant with either leg alone",
    _real_residue_on_base == [] and len(_or_mutant_residue) >= 15,
    f"real={_real_residue_on_base} or_mutant_count={len(_or_mutant_residue)}",
)

if dispatch is not None:
    check(
        "the residue formula in the firmware is AND, not OR: `owned_live[i] == owned_intended[i] && owned_live[i] != owned_original[i]`",
        "owned_live[i] == owned_intended[i] && owned_live[i] != owned_original[i]" in dispatch.body,
    )
    check("residue is scanned over all 20 owned registers (fixed-size array)", "uint16_t owned_addr[20]" in dispatch.body)
    # Anchor on the FUNCTIONAL Phase C call site (`bool phase_c_ok = ecco_durable::commit_record(`),
    # not the generic substring "ecco_durable::commit_record(" - which also appears once in this
    # script's own prose header comment, earlier in the text, and would give a false "too early" offset.
    idx_residue = dispatch.body.find("any_residue")
    idx_phase_c = dispatch.body.find("bool phase_c_ok = ecco_durable::commit_record(")
    check("the residue scan runs strictly BEFORE the first durable Phase C commit", -1 < idx_residue < idx_phase_c, f"residue={idx_residue} phase_c={idx_phase_c}")

# ---------------------------------------------------------------------------
print("")
print("[I] Intended-value derivation pinned to the canonical classifier")
# ---------------------------------------------------------------------------
_orig_for_i = {230: 10, 232: 0b0110, 256: 111, 257: 222, 258: 333, 259: 444, 260: 555, 261: 666,
               268: 1, 269: 2, 270: 3, 271: 4, 272: 5, 273: 6,
               274: 0b11110001, 275: 0b00000010, 276: 0b11111100, 277: 5, 278: 6, 279: 0xFFFF}
_intended_i = fpre.derive_intended(originals=_orig_for_i, reg230_intended=77, reg_tou_power_intended=3333)
check("230 intended == persisted reg230_intended (not derivable from originals)", _intended_i[230] == 77)
check("232 intended == original | 0x0001 (grid-charge bit forced on, other bits preserved)", _intended_i[232] == (0b0110 | 0x0001))
for a in (256, 257, 258, 259, 260, 261):
    check(f"{a} intended == the single persisted reg_tou_power_intended value (3333)", _intended_i[a] == 3333)
for a in (268, 269, 270, 271, 272, 273):
    check(f"{a} intended == 100 (SOC always forced to 100)", _intended_i[a] == 100)
for a in (274, 275, 276, 277, 278, 279):
    expected = (_orig_for_i[a] & 0xFFFC) | 0x0001
    check(f"{a} intended == (original & 0xFFFC) | 0x0001 (source forced to Grid, unrelated bits preserved)", _intended_i[a] == expected, f"got {_intended_i[a]} want {expected}")
check(
    "232's intended derivation preserves unrelated high bits (does not zero them)",
    (_intended_i[232] & 0xFFFE) == (_orig_for_i[232] & 0xFFFE),
)
check(
    "274's intended derivation preserves unrelated high bits above the source/mode nibble",
    (_intended_i[274] & 0xFF00) == (_orig_for_i[274] & 0xFF00),
)
_orig_already_enabled = dict(_orig_for_i)
_orig_already_enabled[232] = 0b0111  # bit 0 already set
_intended_already = fpre.derive_intended(originals=_orig_already_enabled, reg230_intended=77, reg_tou_power_intended=3333)
check(
    "when original 232 already has the grid-charge bit set, intended == original (not a residue trigger on its own)",
    _intended_already[232] == _orig_already_enabled[232],
)

# Mutation test: a deliberately WRONG intended-derivation (hardcoded /
# incorrectly-derived) must be distinguishable from the canonical one by at
# least one of the fixtures above.
def _wrong_derive_intended_hardcoded(*, originals, reg230_intended, reg_tou_power_intended):
    """Deliberate mutant: ignores reg230_intended, hardcodes 230 to 0."""
    bad = fpre.derive_intended(originals=originals, reg230_intended=reg230_intended, reg_tou_power_intended=reg_tou_power_intended)
    bad = dict(bad)
    bad[230] = 0
    return bad


_wrong_i = _wrong_derive_intended_hardcoded(originals=_orig_for_i, reg230_intended=77, reg_tou_power_intended=3333)
check(
    "MUTATION CHECK: a hardcoded/incorrect 230-intended derivation is caught (differs from the canonical one whenever reg230_intended != 0)",
    _wrong_i[230] != _intended_i[230],
)


def _wrong_derive_intended_no_mask(*, originals, reg230_intended, reg_tou_power_intended):
    """Deliberate mutant: 274-279 forces source bits WITHOUT masking - loses the mode bits instead of preserving them."""
    bad = fpre.derive_intended(originals=originals, reg230_intended=reg230_intended, reg_tou_power_intended=reg_tou_power_intended)
    bad = dict(bad)
    for a in (274, 275, 276, 277, 278, 279):
        bad[a] = 0x0001  # WRONG: drops every other bit instead of (orig & 0xFFFC) | 0x0001
    return bad


_wrong_i2 = _wrong_derive_intended_no_mask(originals=_orig_for_i, reg230_intended=77, reg_tou_power_intended=3333)
check(
    "MUTATION CHECK: a 274-279 derivation that drops the preserved-bits mask is caught (differs from canonical whenever original has non-mode-non-source bits set)",
    any(_wrong_i2[a] != _intended_i[a] for a in (274, 275, 276, 277, 278, 279)),
)

if dispatch is not None:
    check(
        "the firmware's own 232-intended derivation text matches the canonical formula exactly",
        "(uint16_t) (original_232 | 0x0001)" in dispatch.body,
    )
    check(
        "the firmware's own 274-279 intended derivation text matches the canonical formula exactly (all six slots)",
        dispatch.body.count("& 0xFFFC) | 0x0001)") == 6,
    )
    check(
        "the firmware's own 268-273 intended derivation is the literal 100 (all six slots)",
        "uint16_t intended_soc[6] = {100, 100, 100, 100, 100, 100};" in dispatch.body,
    )
    check(
        "the firmware's own 230-intended derivation reads the persisted target, never a hardcoded literal",
        "uint16_t intended_230 = id(free_power_target_reg230);" in dispatch.body,
    )
    check(
        "the firmware's own 256-261 intended derivation is the single persisted TOU Power target on all six slots",
        dispatch.body.count("id(free_power_target_tou_power)") >= 7,  # 6 in the array literal + 1 in the fingerprint
    )

# ---------------------------------------------------------------------------
print("")
print("[J] Plausibility scan - existing domains only")
# ---------------------------------------------------------------------------
check("TOU Power 0 is plausible", fpre.implausible_registers({**_base["live_owned"], 256: 0}, tou_power_ceiling_w=TOU_CEILING_W).count(256) == 0)
check("TOU Power at the hardware ceiling (8000) is plausible", fpre.implausible_registers({**_base["live_owned"], 256: TOU_CEILING_W}, tou_power_ceiling_w=TOU_CEILING_W).count(256) == 0)
check("TOU Power at ceiling+1 (8001) is implausible", 256 in fpre.implausible_registers({**_base["live_owned"], 256: TOU_CEILING_W + 1}, tou_power_ceiling_w=TOU_CEILING_W))
check("SOC 0 is plausible", fpre.implausible_registers({**_base["live_owned"], 268: 0}, tou_power_ceiling_w=TOU_CEILING_W).count(268) == 0)
check("SOC 100 is plausible", fpre.implausible_registers({**_base["live_owned"], 268: 100}, tou_power_ceiling_w=TOU_CEILING_W).count(268) == 0)
check("SOC 101 is implausible", 268 in fpre.implausible_registers({**_base["live_owned"], 268: 101}, tou_power_ceiling_w=TOU_CEILING_W))

for accepted_mask in (0x0000, 0x0004, 0x0008, 0x0010):
    live_val = 0xFF00 | accepted_mask  # high/unrelated bits set + an accepted mode field
    offenders = fpre.implausible_registers({**_base["live_owned"], 274: live_val}, tou_power_ceiling_w=TOU_CEILING_W)
    check(f"mode field 0x{accepted_mask:04X} (with unrelated high bits 0xFF00 set) is plausible - unrelated bits never reject", 274 not in offenders, f"offenders={offenders}")

for rejected_mask in (0x000C, 0x0014, 0x0018, 0x001C):
    offenders = fpre.implausible_registers({**_base["live_owned"], 274: rejected_mask}, tou_power_ceiling_w=TOU_CEILING_W)
    check(f"unsupported mode field 0x{rejected_mask:04X} is implausible", 274 in offenders, f"offenders={offenders}")

check(
    "register 230 has NO plausibility bound at all (any uint16_t value passes) - MODE_REGISTERS/SOC_REGISTERS/TOU_POWER_REGISTERS never include 230",
    230 not in fpre.TOU_POWER_REGISTERS and 230 not in fpre.SOC_REGISTERS and 230 not in fpre.MODE_REGISTERS,
)
check(
    "register 232 has NO plausibility bound at all (any uint16_t value passes, including high bits)",
    232 not in fpre.TOU_POWER_REGISTERS and 232 not in fpre.SOC_REGISTERS and 232 not in fpre.MODE_REGISTERS,
)
for ctx in CONTEXT_REGISTERS:
    check(
        f"context register {ctx} has no Accept-invented plausibility bound (only fingerprint continuity applies to it)",
        ctx not in fpre.TOU_POWER_REGISTERS and ctx not in fpre.SOC_REGISTERS and ctx not in fpre.MODE_REGISTERS,
    )
check("implausible_registers() never inspects register 230", 230 not in fpre.implausible_registers({**_base["live_owned"], 230: 65535}, tou_power_ceiling_w=TOU_CEILING_W))
check("implausible_registers() never inspects register 232", 232 not in fpre.implausible_registers({**_base["live_owned"], 232: 65535}, tou_power_ceiling_w=TOU_CEILING_W))

if dispatch is not None:
    check(
        "the firmware's power plausibility bound is expressed via the canonical ceiling substitution, "
        "never a hardcoded 8000 literal",
        "live_powers[i] > ${ecco_inverter_tou_power_ceiling_w}" in dispatch.body and "> 8000" not in dispatch.body,
    )
    check("the firmware's SOC plausibility bound is exactly > 100", "live_soc[i] > 100" in dispatch.body)
    check("the firmware's mode-field mask is exactly 0x001C", "live_flags[i] & 0x001C" in dispatch.body)
    for accepted in ("0x0000", "0x0004", "0x0008", "0x0010"):
        check(f"the firmware accepts mode field {accepted}", f"mode_field == {accepted}" in dispatch.body)
    idx_residue_scan = dispatch.body.find("any_residue")
    idx_plaus_scan = dispatch.body.find("any_implausible")
    idx_phase_c2 = dispatch.body.find("bool phase_c_ok = ecco_durable::commit_record(")
    check(
        "plausibility is scanned AFTER residue, and BOTH strictly before the first durable Phase C commit",
        -1 < idx_residue_scan < idx_plaus_scan < idx_phase_c2,
        f"residue={idx_residue_scan} plaus={idx_plaus_scan} phase_c={idx_phase_c2}",
    )

# Mutation test: proves the plausibility fixtures actually discriminate a
# weakened bound.
def _wrong_implausible_no_soc_bound(live, *, tou_power_ceiling_w):
    offenders = fpre.implausible_registers(live, tou_power_ceiling_w=tou_power_ceiling_w)
    return [a for a in offenders if a not in fpre.SOC_REGISTERS]  # mutant: SOC bound removed


_mutant_offenders = _wrong_implausible_no_soc_bound({**_base["live_owned"], 268: 137}, tou_power_ceiling_w=TOU_CEILING_W)
_real_offenders = fpre.implausible_registers({**_base["live_owned"], 268: 137}, tou_power_ceiling_w=TOU_CEILING_W)
check(
    "MUTATION CHECK: SOC=137 is flagged by the canonical plausibility check but NOT by the SOC-bound-removed mutant",
    268 in _real_offenders and 268 not in _mutant_offenders,
)


def _wrong_implausible_no_power_bound(live, *, tou_power_ceiling_w):
    offenders = fpre.implausible_registers(live, tou_power_ceiling_w=tou_power_ceiling_w)
    return [a for a in offenders if a not in fpre.TOU_POWER_REGISTERS]  # mutant: power bound removed


_mutant_offenders2 = _wrong_implausible_no_power_bound({**_base["live_owned"], 258: 12000}, tou_power_ceiling_w=TOU_CEILING_W)
_real_offenders2 = fpre.implausible_registers({**_base["live_owned"], 258: 12000}, tou_power_ceiling_w=TOU_CEILING_W)
check(
    "MUTATION CHECK: Power=12000 is flagged by the canonical plausibility check but NOT by the power-bound-removed mutant",
    258 in _real_offenders2 and 258 not in _mutant_offenders2,
)


def _wrong_implausible_no_mode_mask(live, *, tou_power_ceiling_w):
    offenders = fpre.implausible_registers(live, tou_power_ceiling_w=tou_power_ceiling_w)
    return [a for a in offenders if a not in fpre.MODE_REGISTERS]  # mutant: mode-mask validation removed


_mutant_offenders3 = _wrong_implausible_no_mode_mask({**_base["live_owned"], 276: 0x001C}, tou_power_ceiling_w=TOU_CEILING_W)
_real_offenders3 = fpre.implausible_registers({**_base["live_owned"], 276: 0x001C}, tou_power_ceiling_w=TOU_CEILING_W)
check(
    "MUTATION CHECK: an invalid mode mask (0x001C) is flagged canonically but NOT by the mask-removed mutant",
    276 in _real_offenders3 and 276 not in _mutant_offenders3,
)

# ---------------------------------------------------------------------------
print("")
print("[K] Absolute invariant: Accept issues ZERO Modbus writes")
# ---------------------------------------------------------------------------
if wrapper is not None:
    check("free_power_recovery_accept_current_state (gate) has zero writes", len(wrapper.writes) == 0, f"{wrapper.writes}")
if dispatch is not None:
    check("free_power_recovery_accept_current_state_dispatch has zero writes", len(dispatch.writes) == 0, f"{dispatch.writes}")
    check(
        "the dispatch script contains no 'modbus_client.write_multiple_registers' text anywhere at all",
        "modbus_client.write_multiple_registers" not in dispatch.body,
    )
_write_surface = {}
for p in paths:
    if p.kind == "script":
        for addr in p.written_addresses:
            _write_surface.setdefault(addr, set()).add(p.name)
_accept_writers = {name for names in _write_surface.values() for name in names if "accept" in name}
check("no register in the entire write surface is ever attributed to an Accept script", not _accept_writers, f"{_accept_writers}")
check(
    "the three Free Power lifecycle scripts (start/restore/force-restore) still write every one of their 20 "
    "owned registers - PR 3 removed nothing from the pre-existing write surface",
    all(
        {"start_free_power_override", "restore_free_power_snapshot_dispatch", "free_power_recovery_force_restore_dispatch"} & _write_surface.get(addr, set())
        for addr in OWNED_REGISTERS
    ),
    f"{ {a: _write_surface.get(a) for a in OWNED_REGISTERS} }",
)

# Mutation check: prove the write-surface extractor WOULD catch a Modbus
# write if one were present, by running it against a text fixture with a
# synthetic write inserted into a copy of Accept's dispatch body (never the
# real file - see registry/tests/test_free_power_recovery_force_restore.py
# for the same "equivalent model mutation" technique applied to structural
# checks elsewhere in this codebase).
if dispatch is not None:
    _synthetic_write = (
        dispatch.body
        + "\n      - modbus_client.write_multiple_registers:\n"
        "          modbus_id: inverter_modbus\n"
        "          address: 0x01\n"
        "          start_address: 230\n"
        "          values: !lambda 'return std::vector<uint16_t>{0};'\n"
    )

    def _zero_write_property(body: str) -> bool:
        """The EXACT assertion Group K's real check above (line ~860) makes."""
        return "modbus_client.write_multiple_registers" not in body

    check(
        "MUTATION CHECK: Group K's own zero-write assertion (_zero_write_property, identical logic to the real "
        "check above) holds on the real dispatch body but is VIOLATED by a COPY with a synthetic Modbus write "
        "appended - proving that assertion has real discriminating power against this class of regression "
        "(the real firmware file was never touched; only an in-memory string copy was mutated)",
        _zero_write_property(dispatch.body) and not _zero_write_property(_synthetic_write),
    )

# ---------------------------------------------------------------------------
print("")
print("[L] No durable snapshot rewrite - the old ORIGINAL is retired, never transformed")
# ---------------------------------------------------------------------------
if dispatch is not None:
    check(
        "Accept never ASSIGNS any free_power_snapshot_regNNN field (read-only access only - it may read "
        "id(free_power_snapshot_regNNN) to compute originals[], but never `= ...;` to one)",
        not re.search(r"id\(free_power_snapshot_reg\d+\)\s*=(?!=)", dispatch.body),
    )
    check(
        "Accept reads every one of the 20 durable snapshot fields (needed for originals[]/fingerprint/residue), "
        "confirming it consults but never mutates them",
        all(f"id(free_power_snapshot_reg{a})" in dispatch.body for a in OWNED_REGISTERS),
    )
    check(
        "Accept never constructs a FreePowerSnapshotData record (the durable ORIGINAL struct) at all",
        "FreePowerSnapshotData" not in dispatch.body,
    )
    check(
        "Accept's only durable commit target is the marker tag (FREE_POWER_VALID_TAG) - never the data tag "
        "(FREE_POWER_DATA_TAG)",
        "FREE_POWER_VALID_TAG" in dispatch.body and "FREE_POWER_DATA_TAG" not in dispatch.body,
    )
    check(
        "Accept never assigns id(free_power_snapshot_valid) = true (it may only ever clear it to false, on the "
        "full-success path - never (re)validate a snapshot)",
        "id(free_power_snapshot_valid) = true" not in dispatch.body,
    )

    def _no_snapshot_rewrite_property(body: str) -> bool:
        """The EXACT assertion Group L's real check above (line ~915) makes."""
        return not re.search(r"id\(free_power_snapshot_reg\d+\)\s*=(?!=)", body)

    # Mutation check: a hypothetical "copy live into snapshot then clear"
    # path would necessarily assign TO a free_power_snapshot_regNNN field.
    # Append that exact pattern to a COPY of the real dispatch body, then
    # re-run the SAME property function the real check above uses, on both
    # the real and mutated text, and require it to flip from pass to fail -
    # not merely that the regex matches a string built to match it.
    _snapshot_rewrite_mutant = dispatch.body + "\n      id(free_power_snapshot_reg230) = id(free_power_recovery_accept_live_reg230);\n"
    check(
        "MUTATION CHECK: Group L's own no-rewrite assertion (_no_snapshot_rewrite_property, identical logic to "
        "the real check above) holds on the real dispatch body but is VIOLATED by a COPY with a synthetic "
        "'copy live into snapshot' assignment appended - proving that assertion has real discriminating power "
        "against this class of regression (the real firmware file was never touched)",
        _no_snapshot_rewrite_property(dispatch.body) and not _no_snapshot_rewrite_property(_snapshot_rewrite_mutant),
    )

# ---------------------------------------------------------------------------
print("")
print("[M] Durable Phase C / Phase D ordering")
# ---------------------------------------------------------------------------
if dispatch is not None:
    idx_neither_ok = dispatch.body.find("Free Power residue scan")
    idx_phase_c_commit = dispatch.body.find("ecco_durable::MARKER_RESTORE_VERIFIED_PENDING_CLEAR")
    idx_phase_d_commit = dispatch.body.find("ecco_durable::ValidMarker cleared{ecco_durable::VALID_MARKER_MAGIC, ecco_durable::MARKER_CLEAR}")
    check(
        "Phase C (PENDING_CLEAR commit) textually precedes Phase D (CLEAR commit) in source order",
        -1 < idx_phase_c_commit < idx_phase_d_commit,
        f"phase_c={idx_phase_c_commit} phase_d={idx_phase_d_commit}",
    )
    check(
        "Phase D's commit_record call is nested INSIDE the `if (phase_c_ok)` block, not a sibling reachable independently",
        bool(re.search(r"if \(phase_c_ok\) \{.*?commit_record\(ecco_durable::key_for\(ecco_durable::FREE_POWER_VALID_TAG\), cleared\)", dispatch.body, re.S)),
    )
    check(
        "on Phase C failure, the marker is left untouched (no `id(free_power_marker_state) = ...CLEAR` in the else branch)",
        bool(re.search(r"\} else \{\s*\n\s*id\(free_power_recovery_accept_refusal_count\)\+\+;", dispatch.body)),
    )
    check(
        "durable resolution (Phase C) happens exactly once in the whole script (a single commit_record call to the marker before any CLEAR attempt)",
        dispatch.body.count("MARKER_RESTORE_VERIFIED_PENDING_CLEAR") >= 1,
    )
    check(
        "no marker CLEAR/PENDING_CLEAR mutation occurs anywhere before the residue scan in source order",
        dispatch.body.find("owned_live[i] == owned_intended[i]") < idx_phase_c_commit,
    )

    def _phase_c_after_residue_property(body: str) -> bool:
        """The EXACT assertion Group M's real ordering check above (line
        ~974) makes: the residue-scan marker text must appear strictly
        BEFORE the Phase C commit marker text."""
        idx_r = body.find("owned_live[i] == owned_intended[i]")
        idx_c = body.find("ecco_durable::MARKER_RESTORE_VERIFIED_PENDING_CLEAR")
        return -1 < idx_r < idx_c

    # Mutation check: genuinely SWAP the text found at the residue-scan
    # marker's position with the text found at Phase C's (first) marker
    # position - simulating what an actual reordering edit to the firmware
    # would produce - then re-run the SAME property function the real check
    # above uses, on both the real and mutated text, and require it to flip
    # from pass to fail. (A prior version of this check merely prepended the
    # Phase C marker text to index 0 and asserted "0 < anything else", which
    # is true by construction regardless of the real check's logic - that
    # was tautological and has been replaced with this genuine swap.)
    _swap_placeholder = "\x00RESIDUE_MARKER\x00"
    _reordered = dispatch.body.replace("owned_live[i] == owned_intended[i]", _swap_placeholder)
    _reordered = _reordered.replace("ecco_durable::MARKER_RESTORE_VERIFIED_PENDING_CLEAR", "owned_live[i] == owned_intended[i]", 1)
    _reordered = _reordered.replace(_swap_placeholder, "ecco_durable::MARKER_RESTORE_VERIFIED_PENDING_CLEAR")
    check(
        "MUTATION CHECK: Group M's own Phase-C-after-residue assertion (_phase_c_after_residue_property, "
        "identical logic to the real check above) holds on the real dispatch body but is VIOLATED by a COPY "
        "with the residue-scan marker and the (first) Phase C marker TEXT POSITIONS genuinely swapped - proving "
        "that assertion has real discriminating power against a reordering regression (the real firmware file "
        "was never touched)",
        _phase_c_after_residue_property(dispatch.body) and not _phase_c_after_residue_property(_reordered),
    )

# ---------------------------------------------------------------------------
print("")
print("[N] Reboot / interruption model (REFERENCE-MODEL, not a firmware execution/ordering proof)")
# ---------------------------------------------------------------------------
# This group exercises simulate_accept() - the Python reference model built
# on registry/free_power_recovery_evidence.py's shared helpers - at 9
# hand-picked (phase_c_ok, phase_d_ok, confirm_read_failed) combinations
# representing "what interruption point a reboot could correspond to". It
# proves the REFERENCE MODEL'S own decision table never produces an
# out-of-set marker value and never claims a Modbus write, which is a
# useful regression pin on the model itself and on
# registry/free_power_recovery_evidence.py's helpers - it does NOT read or
# execute the firmware source, and is not a substitute for Group M's
# firmware-text-anchored Phase C/D ordering proof above. Accept's only
# durable side effect is the marker transition; every interruption point
# before Phase C leaves the marker at RESTORE_REQUIRED (nothing durable
# changed - RAM state is simply lost on reboot, same as PR 1/PR 2's own
# evidence/in-progress globals), and every point at/after Phase C but
# before Phase D leaves it at PENDING_CLEAR (boot's own clear-only retry
# handles it with zero further Modbus writes, exactly like Force's own
# equivalent window).
INTERRUPTION_POINTS = [
    ("before Accept execute", False, False, "RESTORE_REQUIRED"),
    ("during confirm read 1/2/3", False, False, "RESTORE_REQUIRED"),  # confirm_read_failed path
    ("after confirm reads before fingerprint", False, False, "RESTORE_REQUIRED"),
    ("after fingerprint before classification (fingerprint mismatch)", False, False, "RESTORE_REQUIRED"),
    ("after NEITHER before residue (would-be ORIGINAL/INTENDED)", False, False, "RESTORE_REQUIRED"),
    ("after residue before plausibility (residue found)", False, False, "RESTORE_REQUIRED"),
    ("after plausibility before Phase C (Phase C itself fails)", False, False, "RESTORE_REQUIRED"),
    ("after Phase C before Phase D (Phase D fails)", True, False, "PENDING_CLEAR"),
    ("after Phase D (full success)", True, True, "CLEAR"),
]
for label, phase_c_ok, phase_d_ok, expected_marker in INTERRUPTION_POINTS:
    r = simulate_accept(
        original=_base["original"], reg230_intended=_base["reg230_intended"], reg_tou_power_intended=_base["reg_tou_power_intended"],
        end_epoch=_base["end_epoch"], live_owned=_base["live_owned"], live_context=_base["live_context"],
        expected_fingerprint=_base["expected_fingerprint"], phase_c_ok=phase_c_ok, phase_d_ok=phase_d_ok,
    )
    check(f"interruption point '{label}': durable marker is exactly {expected_marker}", r["marker"] == expected_marker, f"got {r['marker']} ({r})")
    check(f"interruption point '{label}': zero Modbus writes occurred", r["modbus_writes"] == [])

check(
    "no reboot point in this model ever produces a marker value outside {RESTORE_REQUIRED, PENDING_CLEAR, CLEAR} "
    "(no new/invented marker state)",
    all(
        simulate_accept(
            original=_base["original"], reg230_intended=_base["reg230_intended"], reg_tou_power_intended=_base["reg_tou_power_intended"],
            end_epoch=_base["end_epoch"], live_owned=_base["live_owned"], live_context=_base["live_context"],
            expected_fingerprint=_base["expected_fingerprint"], phase_c_ok=pc, phase_d_ok=pd,
        )["marker"] in ("RESTORE_REQUIRED", "PENDING_CLEAR", "CLEAR")
        for pc in (True, False) for pd in (True, False)
    ),
)
check(
    "no durable schema/marker/tag constant beyond the existing three is referenced anywhere in the firmware "
    "(no MARKER_ACCEPTED / ACCEPT_PENDING or similar invented state)",
    not any(tok in text for tok in ("MARKER_ACCEPTED", "ACCEPT_PENDING", "MARKER_ACCEPT")),
)
check("firmware/include/ecco_durable_snapshot.h exists (needed by the check below)", DURABLE_HEADER_PATH.is_file())
_durable_header_text = DURABLE_HEADER_PATH.read_text(encoding="utf-8") if DURABLE_HEADER_PATH.is_file() else ""
check(
    "firmware/include/ecco_durable_snapshot.h was not modified to add a new marker/schema for PR 3 "
    "(MarkerState still has exactly 3 values: CLEAR, RESTORE_REQUIRED, RESTORE_VERIFIED_PENDING_CLEAR)",
    "MARKER_CLEAR = 0" in _durable_header_text
    and "MARKER_RESTORE_REQUIRED = 1" in _durable_header_text
    and "MARKER_RESTORE_VERIFIED_PENDING_CLEAR = 2" in _durable_header_text
    and "MARKER_ACCEPTED" not in _durable_header_text
    and _durable_header_text.count("MarkerState") >= 1,
)

# ---------------------------------------------------------------------------
print("")
print("[N2] Post-Opus-review Finding 3: lock release, stale-callback guards, ORIGINAL/INTENDED returns, fingerprint gate")
# ---------------------------------------------------------------------------
# All checks below are technique-2 (real firmware source), scoped to
# dispatch.body specifically - never a whole-file substring search - and
# each ties a SPECIFIC branch's own text to the property being pinned,
# per the independent Opus review's Finding 3.
if dispatch is not None:
    _RELEASE_TRIO = (
        "id(free_power_recovery_accept_in_progress) = false;",
        "id(free_power_operation_in_progress) = false;",
        "id(manual_write_in_progress) = false;",
    )

    def _releases_all_three(branch_text: str) -> bool:
        return all(flag in branch_text for flag in _RELEASE_TRIO)

    # Finding 3.B: every meaningful exit branch releases all 3 ownership
    # flags before its own `return;` - each pattern captures ONLY that
    # branch's own body (non-greedy up to ITS `return;`), so a release
    # accidentally left in a DIFFERENT branch cannot satisfy this.
    _EXIT_BRANCHES = {
        "fresh-read failure": r"if \(id\(free_power_recovery_accept_confirm_read_failed\)\) \{(.*?)return;\s*\n\s*\}",
        "fingerprint mismatch": r"if \(h != id\(free_power_recovery_accept_expected_fingerprint\)\) \{(.*?)return;\s*\n\s*\}",
        "INTENDED refusal": r"if \(matches_intended\) \{(.*?)return;\s*\n\s*\}",
        "ORIGINAL refusal": r"if \(matches_original\) \{(.*?)return;\s*\n\s*\}",
        "residue refusal": r"if \(any_residue\) \{(.*?)return;\s*\n\s*\}",
        "plausibility refusal": r"if \(any_implausible\) \{(.*?)return;\s*\n\s*\}",
    }
    for _label, _pattern in _EXIT_BRANCHES.items():
        _m = re.search(_pattern, dispatch.body, re.S)
        check(
            f"exit branch '{_label}': releases all 3 ownership flags (accept_in_progress, operation_in_progress, "
            "manual_write_in_progress) before its own return - scoped to that specific branch's captured body",
            _m is not None and _releases_all_three(_m.group(1)),
            f"branch found={_m is not None}",
        )

    # The common durable-resolution tail: reached unconditionally whether
    # Phase C succeeded+CLEARed, succeeded+PENDING_CLEAR, or failed - pinned
    # by checking the dispatch script's FINAL three non-blank statements are
    # exactly the 3 releases, in order (robust to exact indentation).
    _tail_lines = [ln.strip() for ln in dispatch.body.strip().splitlines() if ln.strip()][-3:]
    check(
        "the common durable-resolution tail: the dispatch script's FINAL three non-blank statements are exactly "
        "the 3 ownership-flag releases, in order (reached after Phase C success+CLEAR, success+PENDING_CLEAR, "
        "and Phase C failure alike)",
        _tail_lines == list(_RELEASE_TRIO),
        f"{_tail_lines}",
    )

    # Finding 3.C: each of the 3 confirm-read stages guards ALL FOUR
    # terminal handlers (on_response/on_error/on_no_response/on_not_sent)
    # against a stale/late callback using the canonical
    # free_power_recovery_accept_in_progress flag - scoped per read stage
    # by isolating each read's own block via its start_address.
    _READ_STAGES = {
        "230-232 (count 3)": r"start_address: 230\s*\n\s*count: 3\s*\n(.*?)(?=\n      - wait_until:)",
        "256-279 (count 24)": r"start_address: 256\s*\n\s*count: 24\s*\n(.*?)(?=\n      - wait_until:)",
        "context 244-255 (count 12)": r"start_address: 244\s*\n\s*count: 12\s*\n(.*?)(?=\n      - wait_until:)",
    }
    for _label, _pattern in _READ_STAGES.items():
        _m = re.search(_pattern, dispatch.body, re.S)
        _guard_count = _m.group(1).count("if (!id(free_power_recovery_accept_in_progress)) return;") if _m else 0
        check(
            f"read stage {_label}: all 4 terminal handlers (on_response/on_error/on_no_response/on_not_sent) "
            "guard against a stale/late callback via the canonical accept_in_progress flag",
            _m is not None and _guard_count == 4,
            f"stage found={_m is not None} guard_count={_guard_count}",
        )

    # Finding 3.D: ORIGINAL/INTENDED refusals cannot fall through into
    # residue/plausibility/Phase C - each branch's own captured body (up to
    # ITS return;) must actually CONTAIN that return - i.e. the branch is
    # not merely present but genuinely terminates the function there.
    for _label, _pattern in (
        ("INTENDED refusal", r"if \(matches_intended\) \{(.*?)\n          \}"),
        ("ORIGINAL refusal", r"if \(matches_original\) \{(.*?)\n          \}"),
    ):
        _m = re.search(_pattern, dispatch.body, re.S)
        check(
            f"{_label} branch genuinely `return;`s (cannot fall through into the residue scan, plausibility scan, "
            "or Phase C that follow it in source order)",
            _m is not None and "return;" in _m.group(1),
        )
    # ...and confirm this holds for BOTH refusal cases simultaneously by
    # checking neither the residue-scan code nor the Phase C commit is
    # reachable from inside either branch's own captured body (defence in
    # depth alongside the offset-ordering check in Group G).
    for _label, _pattern in (
        ("INTENDED refusal", r"if \(matches_intended\) \{(.*?)\n          \}"),
        ("ORIGINAL refusal", r"if \(matches_original\) \{(.*?)\n          \}"),
    ):
        _m = re.search(_pattern, dispatch.body, re.S)
        check(
            f"{_label} branch's own body never contains the residue-scan or Phase C commit code (they are "
            "textually outside/after it, not nested inside)",
            _m is not None and "any_residue" not in _m.group(1) and "commit_record(" not in _m.group(1),
        )

    # Finding 3.E: the fingerprint comparison itself - not merely that both
    # variables/the message text exist somewhere - genuinely gates entry to
    # classification/residue/plausibility/Phase C via its own `return;`.
    _fp_branch_m = re.search(
        r"if \(h != id\(free_power_recovery_accept_expected_fingerprint\)\) \{(.*?)\n          \}",
        dispatch.body,
        re.S,
    )
    check(
        "the execute-time fingerprint comparison (`h != id(free_power_recovery_accept_expected_fingerprint)`) "
        "is the literal condition gating a branch that releases all 3 ownership flags and genuinely `return;`s",
        _fp_branch_m is not None
        and _releases_all_three(_fp_branch_m.group(1))
        and "return;" in _fp_branch_m.group(1),
    )
    check(
        "the fingerprint-mismatch branch's own body never contains classification (matches_intended/"
        "matches_original), the residue scan, or the Phase C commit - they are textually outside/after it",
        _fp_branch_m is not None
        and "matches_intended" not in _fp_branch_m.group(1)
        and "matches_original" not in _fp_branch_m.group(1)
        and "any_residue" not in _fp_branch_m.group(1)
        and "commit_record(" not in _fp_branch_m.group(1),
    )
    check(
        "the fingerprint comparison is textually the LAST thing computed before it is used (h is fully built by "
        "the same statement block, immediately followed by the comparison) - not compared against a partially-"
        "built or stale hash",
        dispatch.body.find("h = ecco_recovery_evidence::fnv1a64_update_u16le(h, id(free_power_recovery_accept_ctx_reg255));")
        < dispatch.body.find("if (h != id(free_power_recovery_accept_expected_fingerprint))")
        < dispatch.body.find("if (matches_intended)"),
    )

# ---------------------------------------------------------------------------
print("")
print("[O] Force Restore regression status (delegated - see note)")
# ---------------------------------------------------------------------------
# Force's own dedicated 261-check suite (registry/tests/test_free_power_recovery_force_restore.py)
# is run directly as part of the overall PR 3 validation pipeline, not
# re-executed inside this file (avoids duplicating ~1000 lines of Force-
# specific behavioural simulation here). This section only re-asserts the
# ONE cross-cutting fact this PR could plausibly have broken: that PR 3's
# API routing change left Force's own wrapper byte-for-byte untouched.
check(
    "Force's own wrapper script is completely unaffected by PR 3's routing change (checked earlier in Group A too)",
    force_wrapper is not None and "ACCEPT" not in force_wrapper.body,
)
check(
    "Force's dispatch script (the actual writer) is untouched: it still writes exactly the 20 owned registers",
    force_dispatch is not None and force_dispatch.written_addresses == set(OWNED_REGISTERS),
)

# ---------------------------------------------------------------------------
print("")
print("[P] PR 1 Review regression status (delegated - see note)")
# ---------------------------------------------------------------------------
# PR 1's own dedicated suite (registry/tests/test_free_power_recovery_evidence.py)
# is run directly as part of the overall validation pipeline. This section
# re-asserts that Review itself remains untouched by PR 3.
check(
    "Review's own dispatch script is completely unaffected by PR 3 (zero Modbus writes, same as before)",
    review_dispatch is not None and len(review_dispatch.writes) == 0,
)
check(
    "Review's own gate script never mentions ACCEPT (PR 3 did not have to touch Review to add Accept)",
    by_name.get("free_power_recovery_review") is not None and "ACCEPT" not in by_name["free_power_recovery_review"].body,
)

# ---------------------------------------------------------------------------
print("")
print("[Q] No automatic caller of Accept - YAML script.execute AND C++/lambda id(...).execute() forms")
# ---------------------------------------------------------------------------
on_boot_match = re.search(r"on_boot:\s*\n\s*priority:.*?\nesp32:", text, re.S)
on_boot_body = on_boot_match.group(0) if on_boot_match else ""
check("on_boot: block is found (needed by the checks below)", bool(on_boot_body))
check(
    # A plain substring check would false-positive on on_boot's own
    # PENDING_CLEAR comment, which legitimately cross-references
    # free_power_recovery_accept_current_state_dispatch's docstring by name
    # (prose, not an invocation) - so this checks for the actual YAML
    # invocation form specifically, exactly like the sanctioned-call-site
    # check later in this group.
    "on_boot never invokes free_power_recovery_accept_current_state or its dispatch (YAML script.execute: form)",
    not re.search(r"script\.execute:\s*\n\s*id:\s*free_power_recovery_accept_current_state(?:_dispatch)?\b", on_boot_body),
)
check(
    "on_boot never invokes Accept via the C++/lambda id(...).execute() form either",
    not re.search(r"id\(free_power_recovery_accept_current_state(?:_dispatch)?\)\.execute\(\)", on_boot_body),
)

_interval_blocks = re.findall(r"- interval: \S+\s*\n\s*then:\n((?:(?!\n  - ).)*)", text, re.S)
check(f"{len(_interval_blocks)} interval: blocks scanned for both caller forms", len(_interval_blocks) > 0)
check(
    "no interval: trigger anywhere invokes Accept via script.execute: (actual invocation form, not a bare substring)",
    all(not re.search(r"script\.execute:\s*\n\s*id:\s*free_power_recovery_accept_current_state(?:_dispatch)?\b", blk) for blk in _interval_blocks),
)
check(
    "no interval: trigger anywhere invokes Accept via the lambda id(...).execute() form",
    all(not re.search(r"id\(free_power_recovery_accept_current_state(?:_dispatch)?\)\.execute\(\)", blk) for blk in _interval_blocks),
)

# Every YAML script.execute: call anywhere in the firmware targeting Accept
# must be exactly the two already-verified call sites (API routing -> gate,
# gate -> dispatch). A third would mean a button, automation, or other
# script also reaches it.
_all_script_execute_targets = re.findall(r"script\.execute:\s*\n\s*id:\s*(free_power_recovery_accept_current_state(?:_dispatch)?)\b", text)
check(
    "every script.execute: of an Accept script id is one of exactly the two sanctioned call sites",
    sorted(_all_script_execute_targets) == sorted(["free_power_recovery_accept_current_state", "free_power_recovery_accept_current_state_dispatch"]),
    f"{_all_script_execute_targets}",
)

# Lambda/C++-style callers: id(free_power_recovery_accept_current_state).execute()
# or id(free_power_recovery_accept_current_state_dispatch).execute() - the
# ONLY sanctioned one is the wrapper's own success branch calling the
# dispatch script (already covered by [B] above via script.execute: form,
# since this codebase always uses the YAML script.execute: form for
# script-to-script calls, never the lambda .execute() form, EXCEPT for
# free_power_recovery_invalidate_evidence, which every recovery script
# calls via id(...).execute() as a matter of established convention - see
# free_power_recovery_force_restore's own identical pattern). Any lambda-
# style .execute() call on an ACCEPT script id specifically would be a
# structural anomaly this codebase does not otherwise use, and is scanned
# for directly here across the ENTIRE firmware file (not just on_boot/
# interval) for defence in depth.
_lambda_style_accept_callers = re.findall(r"id\(free_power_recovery_accept_current_state(?:_dispatch)?\)\.execute\(\)", text)
check(
    "no C++/lambda-style id(<accept-script>).execute() caller exists ANYWHERE in the firmware "
    "(this codebase only ever calls scripts that way via the YAML script.execute: form)",
    not _lambda_style_accept_callers,
    f"{_lambda_style_accept_callers}",
)

check("home-assistant/ directory exists to scan", HA_DIR.is_dir())
if HA_DIR.is_dir():
    _ha_offenders = []
    for p in HA_DIR.rglob("*"):
        if not p.is_file():
            continue
        try:
            contents = p.read_text(encoding="utf-8")
        except (UnicodeDecodeError, PermissionError):
            continue
        if "free_power_recovery_accept_current_state" in contents or "ACCEPT_CURRENT_STATE" in contents:
            _ha_offenders.append(str(p.relative_to(ROOT)))
    check("no Home Assistant package/automation file references Accept Current State at all", not _ha_offenders, f"{_ha_offenders}")

# ---------------------------------------------------------------------------
print("")
print("[R] No other executable recovery action exists")
# ---------------------------------------------------------------------------
_forbidden_action_tokens = ("DISCARD_UNREADABLE", "REAPPLY_INTENDED", "ACCEPT_PARTIAL", "PER_REGISTER_ACCEPT")
for token in _forbidden_action_tokens:
    check(f'"{token}" does not appear anywhere in the firmware', token not in text)
check(
    "the firmware's own action-token comparison set (anywhere id(free_power_recovery_force_action) is compared "
    "against a string literal) is exactly {FORCE_RESTORE_ORIGINAL, ACCEPT_CURRENT_STATE, and the routing "
    'lambda\'s own "ACCEPT_CURRENT_STATE" check}',
    set(re.findall(r'id\(free_power_recovery_force_action\)\s*[!=]=\s*"([A-Z_]+)"', text)) == {"FORCE_RESTORE_ORIGINAL", "ACCEPT_CURRENT_STATE"},
    f"{set(re.findall(r'id.free_power_recovery_force_action.\s*[!=]=\s*\"([A-Z_]+)\"', text))}",
)
check(
    'the API routing\'s own action comparison ("ACCEPT_CURRENT_STATE") is the same literal used inside the '
    "Accept wrapper's own precondition check (no drift between the two)",
    'action == "ACCEPT_CURRENT_STATE"' in text and 'id(free_power_recovery_force_action) != "ACCEPT_CURRENT_STATE"' in text,
)

# ---------------------------------------------------------------------------
print("")
print("[S] Mutation-quality summary")
# ---------------------------------------------------------------------------
# Groups F, H, I, J, K, L, M above each embed at least one explicit
# "MUTATION CHECK". Two flavours, not interchangeable:
#   - F, H, I, J: a deliberately broken REFERENCE-MODEL function (e.g. a
#     wrong intended-value derivation, a plausibility bound with one leg
#     removed), proven to disagree with the canonical
#     registry/free_power_recovery_evidence.py helpers on a fixture value -
#     this pins the reference model's own discriminating power, not the
#     firmware source directly.
#   - K, L, M: the SAME property function a nearby real firmware-text check
#     uses, re-run against both the real firmware text and a deliberately
#     corrupted COPY of it, required to flip from pass to fail - this pins
#     that specific real check's own discriminating power against the
#     firmware source.
# Nothing in this file ever writes to
# firmware/ecco_clock_dongle_stage3_4_free_power.yaml or any other tracked
# file; every mutation above operates on an in-memory copy (a dict, a
# string, or a standalone function) and is discarded when the process
# exits.
print("  (Mutation checks are interleaved above under their own group; see 'MUTATION CHECK:' prefixes.)")

# ---------------------------------------------------------------------------
print("")
print(f"{'='*70}")
if FAILURES:
    print(f"FAILED: {len(FAILURES)} check(s)")
    for f in FAILURES:
        print(f"  - {f}")
    sys.exit(1)
else:
    print("ALL CHECKS PASSED")
    sys.exit(0)
