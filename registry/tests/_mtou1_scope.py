"""Manual TOU Phase 1 change scope: exactly what the Phase 1 ownership-gate
PR added to firmware/ecco_clock_dongle_stage3_4_free_power.yaml, and its
exact inverse.

Earlier suites pin script bodies, intervals and globals byte-for-byte as
change-scope proofs (SG-01 Phase 3/4/5, SG-06: "nothing outside our change
sites moved"). Phase 1 necessarily edits the six apply_manual_slotN scripts,
the seven Manual TOU Load buttons, adds two RAM globals and one RAM-only
interval. Rather than re-pinning those suites to new hashes - which would
silently widen what they accept - they hash `pre_mtou1_text()` instead: the
current firmware text with exactly this PR's edits reverted.
registry/tests/test_manual_tou_phase1_ownership_gates.py pins that the revert
reproduces main @ 004040b (the Phase 1 base) byte-for-byte, so any OTHER
change still breaks those pins, and every revert step below asserts it
matched exactly as often as Phase 1 applied it.

The constants here are also the single source of truth the Phase 1 suite
checks the firmware against. No I/O.
"""

from __future__ import annotations

import hashlib

# sha256 of firmware/ecco_clock_dongle_stage3_4_free_power.yaml on main @
# 004040b (LF line endings, as read by Path.read_text) - what
# pre_mtou1_text() must reproduce.
BASE_FW_SHA = "934ba7ddd6806592b64d7cc63795aa0ee372238d2eaa314612565e2639cdd4d5"

SLOTS = range(1, 7)
APPLY_SCRIPTS = [f"apply_manual_slot{n}" for n in SLOTS]
LOAD_BUTTONS = [f"load_manual_slot{n}_staging" for n in SLOTS] + ["load_all_manual_tou_staging"]
STAGING_FLAGS = [f"manual_slot{n}_staging_loaded" for n in SLOTS]

# Free Power / Dump to Grid ownership of the TOU registers: any one set means
# the live TOU values may be (or may be about to become) a temporary overlay.
# The SG-06 UNKNOWN lockout and the malformed-marker lockout manifest through
# *_snapshot_valid + *_recovery_metadata_corrupt, so they are covered here.
FP_DUMP_OWNERSHIP_FLAGS = (
    "free_power_active_persisted", "free_power_snapshot_valid", "free_power_operation_in_progress",
    "dump_active_persisted", "dump_snapshot_valid", "dump_operation_in_progress",
    "dump_recovery_metadata_corrupt",
)

GATE_COMMENT = [
    "// Manual TOU Phase 1 (2026-09-29): script-level ownership gate.",
    "// The Apply button's own guard is not enough - whatever reaches",
    "// this script must be refused while Free Power or Dump to Grid",
    "// owns, or may own, the TOU registers (active lease, restore",
    "// owed, transaction in flight, and the SG-06 UNKNOWN / corrupt",
    "// lockouts, which set snapshot_valid + metadata_corrupt), while",
    "// the register 244 proof transaction is in flight, and while",
    "// anything else is still outstanding on the shared Modbus bus.",
]
# The terms Phase 1 added to every apply_manual_slotN admission gate.
APPLY_ADDED_TERMS = [f"!id({f})" for f in FP_DUMP_OWNERSHIP_FLAGS] + [
    "!id(reg244_apply_in_progress)",
    "id(inverter_modbus)->tx_buffer_empty()",
    "!id(inverter_modbus)->tx_blocked()",
]
# Ownership terms every apply gate must carry (Phase 1's plus the ones it
# already had), as whitespace-free top-level conjuncts.
APPLY_REQUIRED_TERMS = APPLY_ADDED_TERMS + [
    "!id(manual_write_in_progress)",
    "!id(correction_in_progress)",
    "!id(reg244_snapshot_valid)",
    "!id(free_power_recovery_metadata_corrupt)",
    "!id(reg244_recovery_metadata_corrupt)",
    "id(manual_config_write_enable).state",
]

APPLY_ELSE_ADDED = [
    "if (id(free_power_active_persisted) || id(free_power_snapshot_valid) || id(free_power_operation_in_progress) ||",
    "    id(dump_active_persisted) || id(dump_snapshot_valid) || id(dump_operation_in_progress) ||",
    "    id(dump_recovery_metadata_corrupt)) {",
    "  id(manual_config_last_result).publish_state(\"REJECTED - Free Power or Dump to Grid override/recovery owns TOU settings\");",
    "} else if (id(reg244_apply_in_progress)) {",
    "  id(manual_config_last_result).publish_state(\"REJECTED - Register 244 proof transaction in progress\");",
    "} else if (!id(inverter_modbus)->tx_buffer_empty() || id(inverter_modbus)->tx_blocked()) {",
    "  id(manual_config_last_result).publish_state(\"REJECTED - Modbus bus busy with another transaction; try again shortly\");",
    "}",
]

FAIL_FAST_COMMENT = [
    "# Manual TOU Phase 1: fail fast - once an earlier write of this",
    "# apply has failed (a queue refusal via on_not_sent included), no",
    "# further register is written; the write-phase check below then",
    "# fails the apply before any verification read.",
]
FAIL_FAST_COND = "lambda: 'return !id(manual_write_failed);'"

LOAD_COND_OLD = "return id(manual_config_raw_cache_valid) && !id(manual_write_in_progress);"
LOAD_COND_NEW = [
    "return id(manual_config_raw_cache_valid) &&",
    "       !id(manual_write_in_progress) &&",
    "       // Manual TOU Phase 1: no Load while Free Power / Dump to",
    "       // Grid owns (or may own) the TOU registers - the cached live",
    "       // values may be a temporary overlay - nor while the register",
    "       // 244 proof transaction owns inverter settings.",
    "       !id(free_power_active_persisted) &&",
    "       !id(free_power_snapshot_valid) &&",
    "       !id(free_power_operation_in_progress) &&",
    "       !id(free_power_recovery_metadata_corrupt) &&",
    "       !id(dump_active_persisted) &&",
    "       !id(dump_snapshot_valid) &&",
    "       !id(dump_operation_in_progress) &&",
    "       !id(dump_recovery_metadata_corrupt) &&",
    "       !id(reg244_apply_in_progress) &&",
    "       !id(reg244_snapshot_valid) &&",
    "       !id(reg244_recovery_metadata_corrupt) &&",
    "       // ...and not until the staging invalidation interval has seen",
    "       // that ownership end AND the configuration cache has been",
    "       // refreshed by reads sent after it ended (see",
    "       // manual_tou_staging_min_cfg_seq).",
    "       !id(manual_tou_owner_seen) &&",
    "       id(cfg_block_b_response_dispatch_seq) >= id(manual_tou_staging_min_cfg_seq);",
]
LOAD_REQUIRED_TERMS = [
    "id(manual_config_raw_cache_valid)", "!id(manual_write_in_progress)",
    *[f"!id({f})" for f in FP_DUMP_OWNERSHIP_FLAGS], "!id(free_power_recovery_metadata_corrupt)",
    "!id(reg244_apply_in_progress)", "!id(reg244_snapshot_valid)", "!id(reg244_recovery_metadata_corrupt)",
    "!id(manual_tou_owner_seen)", "id(cfg_block_b_response_dispatch_seq)>=id(manual_tou_staging_min_cfg_seq)",
]

# The Load buttons' pre-Phase-1 else: bodies (indent 16), verbatim.
LOAD_ELSE_OLD = {
    1: ['id(manual_config_last_result).publish_state(',
        '  "Cannot load staging - refresh configuration first"',
        ');'],
    **{n: [f'id(manual_config_last_result).publish_state("Cannot load Slot {n} staging - refresh configuration first");']
       for n in range(2, 7)},
    None: ['id(manual_config_last_result).publish_state("Cannot load all TOU staging - refresh configuration first");'],
}


def load_else_new(n: int | None) -> list[str]:
    what = f"Slot {n}" if n else "all TOU"
    old = LOAD_ELSE_OLD[n]
    msg = (old[1].strip().strip('"') if len(old) == 3 else old[0].split('publish_state("', 1)[1].rsplit('");', 1)[0])
    out = [f"id(manual_slot{n}_staging_loaded) = false;"] if n else []
    return out + [
        "if (id(free_power_active_persisted) || id(free_power_snapshot_valid) || id(free_power_operation_in_progress) ||",
        "    id(free_power_recovery_metadata_corrupt) ||",
        "    id(dump_active_persisted) || id(dump_snapshot_valid) || id(dump_operation_in_progress) ||",
        "    id(dump_recovery_metadata_corrupt)) {",
        f"  id(manual_config_last_result).publish_state(\"REJECTED - cannot load {what} staging while Free Power or Dump to Grid owns TOU settings (live values may be a temporary overlay)\");",
        "} else if (id(reg244_apply_in_progress) || id(reg244_snapshot_valid) || id(reg244_recovery_metadata_corrupt)) {",
        f"  id(manual_config_last_result).publish_state(\"REJECTED - cannot load {what} staging while the register 244 proof transaction owns inverter settings\");",
        "} else if (id(manual_tou_owner_seen) || id(cfg_block_b_response_dispatch_seq) < id(manual_tou_staging_min_cfg_seq)) {",
        f"  id(manual_config_last_result).publish_state(\"Cannot load {what} staging yet - waiting for a configuration refresh read after Free Power / Dump to Grid released TOU settings\");",
        "} else {",
        f"  id(manual_config_last_result).publish_state(\"{msg}\");",
        "}",
    ]


NEW_GLOBALS = [
    "  # Manual TOU Phase 1 (2026-09-29) - RAM only, never persisted. Maintained",
    "  # ONLY by the staging-invalidation interval (see there): true while it has",
    "  # seen Free Power / Dump to Grid own (or possibly own) the TOU registers",
    "  # and has not yet processed that ownership ending. Load refuses while set.",
    "  - id: manual_tou_owner_seen",
    "    type: bool",
    "    restore_value: no",
    "    initial_value: 'false'",
    "  # Manual TOU Phase 1 - RAM only. The lowest cfg_block_b_response_dispatch_seq",
    "  # a Load may use: set to cfg_block_b_dispatch_seq + 2 whenever staging is",
    "  # invalidated, so the cached TOU values (Block B) AND register 232 (Block A,",
    "  # read ~2.5s before Block B in the same poll) must both come from a",
    "  # configuration poll that STARTED after the invalidation - never from a",
    "  # cache still holding a Free Power / Dump overlay. Free Power's and Dump's",
    "  # restores do not refresh the manual_cfg_* cache themselves.",
    "  - id: manual_tou_staging_min_cfg_seq",
    "    type: uint32_t",
    "    restore_value: no",
    "    initial_value: '0'",
]
NEW_GLOBAL_IDS = ("manual_tou_owner_seen", "manual_tou_staging_min_cfg_seq")

_STAGE = [f"id({f})" for f in STAGING_FLAGS]
NEW_INTERVAL = [
    "",
    "  # Manual TOU Phase 1 (2026-09-29): Manual TOU staging invalidation on",
    "  # temporary TOU ownership. RAM only - no Modbus, no NVS, no",
    "  # script.execute, and it touches no Free Power / Dump transaction state",
    "  # (it only READS their ownership flags), so it adds no dependency from",
    "  # those transactions to Manual TOU.",
    "  #",
    "  # While Free Power or Dump to Grid owns, or may own, the TOU registers,",
    "  # every Manual TOU staging flag is cleared on every tick - a staging",
    "  # loaded before the lease can never be applied after it - and when that",
    "  # ownership ends they are cleared once more and Load is fenced until the",
    "  # configuration cache has been refreshed by reads sent after the end",
    "  # (manual_tou_staging_min_cfg_seq). Load and every apply_manual_slotN",
    "  # refuse during the ownership itself on their own. A TOU-changing lease",
    "  # holds its flags continuously from its first TOU write until its",
    "  # verified restore - at least three Modbus transactions spaced by the",
    "  # hub's 600ms turnaround (ESPHome default, not overridden) - so a 1s",
    "  # tick cannot miss it.",
    "  - interval: 1s",
    "    then:",
    "      - lambda: |-",
    "          bool owned =",
    "            id(free_power_active_persisted) || id(free_power_snapshot_valid) || id(free_power_operation_in_progress) ||",
    "            id(dump_active_persisted) || id(dump_snapshot_valid) || id(dump_operation_in_progress) ||",
    "            id(dump_recovery_metadata_corrupt);",
    "          if (!owned && !id(manual_tou_owner_seen)) return;",
    "          bool had_staging =",
    "            " + " || ".join(_STAGE[:3]) + " ||",
    "            " + " || ".join(_STAGE[3:]) + ";",
    *[f"          {s} = false;" for s in _STAGE],
    "          id(manual_tou_staging_min_cfg_seq) = id(cfg_block_b_dispatch_seq) + 2;",
    "          if (owned) {",
    "            if (!id(manual_tou_owner_seen)) {",
    "              ESP_LOGW(\"manual_config\", \"Free Power / Dump to Grid owns TOU settings - Manual TOU staging invalidated, Load refused\");",
    "            }",
    "            id(manual_tou_owner_seen) = true;",
    "            if (had_staging) {",
    "              id(manual_config_last_result).publish_state(\"Manual TOU staging CLEARED - Free Power / Dump to Grid took temporary ownership of TOU settings; Load again after it ends\");",
    "            }",
    "          } else {",
    "            id(manual_tou_owner_seen) = false;",
    "            id(manual_config_last_result).publish_state(\"Manual TOU staging invalidated - Free Power / Dump to Grid released TOU settings; Load is available again after the next configuration refresh\");",
    "            ESP_LOGI(\"manual_config\", \"TOU ownership ended - Manual TOU staging invalidated; Load fenced until a post-release configuration refresh\");",
    "          }",
]
INTERVAL_MARKER = "Manual TOU Phase 1 (2026-09-29): Manual TOU staging invalidation"


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _indent(s: str) -> int:
    return len(s) - len(s.lstrip(" "))


def _find_seq(lines: list[str], seq: list[str], start: int = 0, end: int | None = None) -> list[int]:
    """Start indices where `seq` matches lines[i:i+len(seq)] after stripping each side."""
    end = len(lines) if end is None else end
    want = [s.strip() for s in seq]
    return [i for i in range(start, end - len(seq) + 1)
            if [x.strip() for x in lines[i:i + len(seq)]] == want]


def _script_range(lines: list[str], sid: str) -> tuple[int, int]:
    start = lines.index(f"  - id: {sid}")
    end = start + 1
    while end < len(lines) and not (lines[end].startswith("  - id: ") or (lines[end][:1].isalpha())):
        end += 1
    return start, end


def _expect(found: int, want: int, what: str) -> None:
    if found != want:
        raise AssertionError(f"Manual TOU Phase 1 revert: {what} found {found}x (expected exactly {want})")


def _revert_apply(lines: list[str], n: int) -> None:
    s, e = _script_range(lines, f"apply_manual_slot{n}")
    body = lines[s:e]
    modbus_actions = sum(1 for l in body if l.strip() in ("- modbus_client.write_multiple_registers:",
                                                          "- modbus_client.read_holding_registers:"))
    writes = sum(1 for l in body if l.strip() == "- modbus_client.write_multiple_registers:")
    # 1. the on_not_sent / on_custom_response handlers (the base had none in these scripts)
    removed, i = 0, 0
    while i < len(body):
        if body[i].strip() in ("on_not_sent:", "on_custom_response:"):
            k, j = _indent(body[i]), i + 1
            while j < len(body) and body[j].strip() and _indent(body[j]) > k:
                j += 1
            del body[i:j]
            removed += 1
            continue
        i += 1
    _expect(removed, 2 * modbus_actions, f"slot {n} on_not_sent/on_custom_response handlers")
    # 2. the fail-fast wrappers around writes 2..N (and their one comment)
    unwrapped, i = 0, 0
    while i < len(body):
        ind = _indent(body[i])
        if (body[i].strip() == "- if:" and i + 4 < len(body)
                and [x.strip() for x in body[i + 1:i + 4]] == ["condition:", FAIL_FAST_COND, "then:"]
                and body[i + 4].strip() == "- modbus_client.write_multiple_registers:"):
            j = i + 4
            while j < len(body) and body[j].strip() and _indent(body[j]) > ind:
                if _indent(body[j]) < ind + 6:
                    raise AssertionError(f"slot {n}: fail-fast block not indented by 6")
                body[j] = body[j][6:]
                j += 1
            del body[i:i + 4]
            unwrapped += 1
            continue
        i += 1
    _expect(unwrapped, writes - 1, f"slot {n} fail-fast write wrappers")
    hits = _find_seq(body, FAIL_FAST_COMMENT)
    _expect(len(hits), 1, f"slot {n} fail-fast comment")
    del body[hits[0]:hits[0] + len(FAIL_FAST_COMMENT)]
    # 3. the gate terms
    added = GATE_COMMENT + [t + " &&" for t in APPLY_ADDED_TERMS]
    hits = _find_seq(body, added)
    _expect(len(hits), 1, f"slot {n} gate terms")
    del body[hits[0]:hits[0] + len(added)]
    # 4. the ownership-first rejection reasons
    hits = _find_seq(body, APPLY_ELSE_ADDED)
    _expect(len(hits), 1, f"slot {n} rejection reasons")
    k = hits[0]
    del body[k:k + len(APPLY_ELSE_ADDED)]
    old = "else if (!id(manual_config_raw_cache_valid))"
    _expect(int(body[k].lstrip().startswith(old)), 1, f"slot {n} rejection chain continuation")
    body[k] = body[k].replace(old, "if (!id(manual_config_raw_cache_valid))", 1)
    lines[s:e] = body


def _revert_load(lines: list[str], n: int | None) -> None:
    bid = f"load_manual_slot{n}_staging" if n else "load_all_manual_tou_staging"
    bi = lines.index(f"    id: {bid}")
    end = bi + 1
    while end < len(lines) and not lines[end].startswith("  - platform:"):
        end += 1
    hits = _find_seq(lines, LOAD_COND_NEW, bi, end)
    _expect(len(hits), 1, f"{bid} condition")
    k = hits[0]
    lines[k:k + len(LOAD_COND_NEW)] = [" " * _indent(lines[k]) + LOAD_COND_OLD]
    end -= len(LOAD_COND_NEW) - 1
    new_else = load_else_new(n)
    hits = [h for h in _find_seq(lines, new_else, bi, end) if _indent(lines[h]) == 16]
    _expect(len(hits), 1, f"{bid} else body")
    k = hits[0]
    lines[k:k + len(new_else)] = [" " * 16 + x for x in LOAD_ELSE_OLD[n]]


def pre_mtou1_text(text: str) -> str:
    """`text` with exactly Manual TOU Phase 1's firmware edits reverted."""
    lines = text.split("\n")
    # the invalidation interval (appended as the last interval)
    hits = [h for h in _find_seq(lines, NEW_INTERVAL) if lines[h] == ""]
    _expect(len(hits), 1, "staging invalidation interval")
    del lines[hits[0]:hits[0] + len(NEW_INTERVAL)]
    # the two RAM globals
    hits = _find_seq(lines, NEW_GLOBALS)
    _expect(len(hits), 1, "Phase 1 globals")
    del lines[hits[0]:hits[0] + len(NEW_GLOBALS)]
    for n in SLOTS:
        _revert_apply(lines, n)
    for n in list(SLOTS) + [None]:
        _revert_load(lines, n)
    return "\n".join(lines)
