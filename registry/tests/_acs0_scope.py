"""acs0 (Advanced Configuration Stage 0: a guarded owner edit of ONE TOU slot's target SOC) change scope: exactly what acs0 changes
in the chain-pinned deployment manifest, and its exact inverse, plus the files it adds.

WHAT acs0 IS. A Home Assistant package (home-assistant/packages/ecco_tou_target_soc_edit.yaml: three helpers, one lock, three
scripts; no automation) that lets the owner change ONE TOU slot's target SOC (register 267+N) through the EXISTING, verified
manual TOU firmware path (Load Current Slot N To Manual Staging -> Manual Configuration Write Enable -> Apply Manual Slot N
Settings): Review (writes nothing) -> a typed confirmation with a one-time review code -> Apply, with a fresh configuration read,
the Manual Controls helper sync at a fixed point, only the SOC staged, every other staged value proven equal to the live slot,
one Apply, and success only on the firmware's VERIFIED OK plus an independent later read of every written register. Fail-closed
refusal in every unsafe state; an uncertain outcome locks further edits until acknowledged. ZERO firmware byte, ZERO new
register (the write surface is unchanged); no frozen file edited.

CHAIN-PINNED edit: deployment/ha-manifest.yaml, one home_assistant_packages stanza.
NOT frozen (ordinary edits): home-assistant/tests/_ha_script_sim.py (fps1's simulator: lists of packages, helper initial
states, state triggers on lists, queued mode, condition / stop / repeat for_each, input_number / input_datetime services),
registry/tests/test_pex_transition.py (the PEX ledger), CHANGELOG.md.

This module imports no other scope module, not _scope_chain (the chain imports it) and not _pex. No I/O.
"""

from __future__ import annotations

# Public main the change is based on (FSW1 merged).
BASE_COMMIT = "2afe6c3ffdec51ec808cb03a84a8471e503677d5"

ADDED_FILES = frozenset({
    "docs/dev/advanced-config-write-assessment.md",
    "docs/dev/advanced-config/conflict-map.md",
    "docs/dev/advanced-config/ha-surface.md",
    "docs/dev/advanced-config/register-evidence.md",
    "docs/dev/advanced-config/s3-tou-slot1-soc-writes-2026-10.md",
    "docs/dev/advanced-config/settings-map.md",
    "docs/dev/advanced-config/stage0-live-proof-procedure.md",
    "docs/dev/advanced-config/stage0-safety-case.md",
    "docs/dev/advanced-config/stage0b-card-plan.md",
    "docs/dev/advanced-config/write-surface.md",
    "docs/dev/dump-to-grid-restore-conflict-investigation.md",
    "home-assistant/packages/ecco_tou_target_soc_edit.yaml",
    "home-assistant/tests/_manual_tou_sim.py",
    "home-assistant/tests/test_ecco_tou_target_soc_edit.py",
    "registry/tests/_acs0_scope.py",
})


def _blk(s: str) -> str:
    assert s.startswith("\n") and s.endswith("\n") and "\r" not in s
    return s[1:]


def _swap(text: str, find: str, put: str, what: str, state: str) -> str:
    n = text.count(find)
    if n != 1:
        raise AssertionError(f"acs0 scope: {what} must be {state} exactly once, found {n}x: {find[:70]!r}")
    i = text.index(find)
    return text[:i] + put + text[i + len(find):]


MANIFEST_REL = "deployment/ha-manifest.yaml"
MANIFEST_0_OLD = _blk(r"""
    destination: /config/packages/ecco_battery_runtime.yaml
""")
MANIFEST_0_NEW = _blk(r"""
    destination: /config/packages/ecco_battery_runtime.yaml
    method: ssh_file_copy
    restart_required: true

  # Advanced Configuration Stage 0 - ACS0 (owner edit of ONE TOU slot's target SOC through the existing, verified manual
  # TOU firmware path; review + typed confirmation; NOT live-proven - see docs/dev/advanced-config/stage0-live-proof-procedure.md).
  - source: home-assistant/packages/ecco_tou_target_soc_edit.yaml
    destination: /config/packages/ecco_tou_target_soc_edit.yaml
""")
MANIFEST_EDITS = ((MANIFEST_0_OLD, MANIFEST_0_NEW),)


def pre_acs0_manifest(text: str) -> str:
    """deployment/ha-manifest.yaml with exactly acs0's edit undone (the chain reverter of entry acs0): its text as of fsw1."""
    out = _swap(text, MANIFEST_0_NEW, MANIFEST_0_OLD, "deployment/ha-manifest.yaml edit 0", "present")
    if out.count(MANIFEST_0_OLD) != 1:
        raise AssertionError("acs0 scope: manifest anchor must be unique once the edit is removed")
    return out


pre_acs0_manifest.edits = MANIFEST_EDITS   # the PEX contract: a reverter exposes its exact (before, after) pairs


def add_acs0_manifest(text: str) -> str:
    """Applies acs0's manifest edit to the text as of fsw1 (the round trip)."""
    if MANIFEST_0_NEW in text:
        raise AssertionError("acs0 scope: the manifest edit is already present")
    return _swap(text, MANIFEST_0_OLD, MANIFEST_0_NEW, "deployment/ha-manifest.yaml anchor 0", "found")


# acs0 edits no frozen file.
FROZEN_REVERTERS: dict = {}
# The chain-pinned file acs0 edits, with its reverter (the chain entry's reverts).
PINNED_REVERTERS = {
    MANIFEST_REL: pre_acs0_manifest,
}
