"""smr1 (restore the owner's manual Dump to Grid / Free Power request values after a SCHEDULED start; FCC1 A10 finding F3)
change scope: exactly what smr1 changes in the chain-pinned deployment manifest, and its exact inverse.

Same technique as the earlier post-export scope modules: every verbatim edit is held HERE as the single source of truth, as an exact
(before, after) pair, and the reverter raises unless each of its edits is present exactly once. The post-export chain entry `smr1`
(registry/tests/_scope_chain.py POST_EXPORT_ENTRIES, appended last after fcc1; registry/tests/_pex.py) carries one chain-pinned
reverter for the manifest.

WHAT smr1 IS. A scheduled start (DGS1 / FPS1) stages the schedule's values into the dongle's single set of request numbers per
function (Dump to Grid: export power, Stop SOC, duration; Free Power: max charge power, duration), which the owner's manual
controls share, and nothing put the owner's values back. New files (ADDED_FILES):
  home-assistant/packages/ecco_schedule_manual_restore.yaml   helpers (saved / written per number, a state text per function),
                                                              two template sensors (what blocks a restore; the obligation), and
                                                              per function a TRACK automation (saves the owner's value the first
                                                              time a running scheduled start replaces it) and a RESTORE automation
                                                              (one verified attempt once nothing owns control, only for a valid
                                                              saved value whose number still holds the schedule's value)
  home-assistant/tests/test_ecco_schedule_manual_restore.py   its offline proofs; docs/dev/schedule-manual-restore.md; this module.
ZERO firmware, registry, Intelligence or ecco_core byte; the two schedule packages are NOT changed; no Modbus operation; no
switch / button / script / esphome action: the package writes only its own helpers and the five request numbers (staging values
the firmware reads at START), never while a lease, transaction, snapshot, recovery, write enable, manual write or scheduled start
owns control.

CHAIN-PINNED edit.
  deployment/ha-manifest.yaml               one home_assistant_packages stanza for the new package

NOT frozen (ordinary edits, nothing to declare): registry/tests/test_pex_transition.py (the PEX ledger), CHANGELOG.md,
home-assistant/tests/_ha_script_sim.py (fps1's simulator: event triggers, fired only through HA.fire_event) and
home-assistant/tests/test_ecco_dump_limits.py (it no longer requires fcc1 to be the newest entry, and reads the manifest as of fcc1,
since smr1 edits it later).

This module imports no other scope module, not _scope_chain (the chain imports it) and not _pex. No I/O.
"""

from __future__ import annotations

import hashlib

# Public main the change is based on (acs0r1 merged as PR #32).
BASE_COMMIT = "a298e5636dfe366e452b434afacce985cc0e156d"

PACKAGE_REL = "home-assistant/packages/ecco_schedule_manual_restore.yaml"
ADDED_FILES = frozenset({
    "docs/dev/schedule-manual-restore.md",
    PACKAGE_REL,
    "home-assistant/tests/test_ecco_schedule_manual_restore.py",
    "registry/tests/_smr1_scope.py",
})


def _blk(s: str) -> str:
    """A raw triple-quoted literal that starts on the line after the opening quotes: drops that first newline."""
    assert s.startswith("\n") and s.endswith("\n") and "\r" not in s
    return s[1:]


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _swap(text: str, find: str, put: str, what: str, state: str) -> str:
    n = text.count(find)
    if n != 1:
        raise AssertionError(f"smr1 scope: {what} must be {state} exactly once, found {n}x: {find[:70]!r}")
    i = text.index(find)
    return text[:i] + put + text[i + len(find):]


def _revert(text: str, edits: tuple, what: str) -> str:
    out = text
    for k, (before, after) in reversed(list(enumerate(edits))):
        out = _swap(out, after, before, f"{what} edit {k}", "present")
    for k, (before, _after) in enumerate(edits):
        n = out.count(before)
        if n != 1:
            raise AssertionError(f"smr1 scope: {what} anchor {k} must be unique once the edits are removed, found {n}x")
    return out


def _apply(text: str, edits: tuple, what: str) -> str:
    out = text
    for k, (before, after) in enumerate(edits):
        if after in out:
            raise AssertionError(f"smr1 scope: {what} edit {k} is already present")
        out = _swap(out, before, after, f"{what} anchor {k}", "found")
    return out


# ---- (chain-pinned edit) deployment/ha-manifest.yaml --------------------------------------------------------------------------
MANIFEST_REL = "deployment/ha-manifest.yaml"
MANIFEST_0_OLD = _blk(r"""
    destination: /config/packages/ecco_dump_limits.yaml
    method: ssh_file_copy
    restart_required: true
""")
MANIFEST_0_NEW = _blk(r"""
    destination: /config/packages/ecco_dump_limits.yaml
    method: ssh_file_copy
    restart_required: true

  # Restore the owner's manual Dump to Grid / Free Power request values after a scheduled start - SMR1 (saves each value a
  # scheduled start replaces; one verified restore once nothing owns control; writes only its helpers and the five request
  # numbers, never the inverter). Deploy with or after the two schedule packages.
  - source: home-assistant/packages/ecco_schedule_manual_restore.yaml
    destination: /config/packages/ecco_schedule_manual_restore.yaml
    method: ssh_file_copy
    restart_required: true
""")
MANIFEST_EDITS = (
    (MANIFEST_0_OLD, MANIFEST_0_NEW),
)


def pre_smr1_manifest(text: str) -> str:
    """deployment/ha-manifest.yaml with exactly smr1's edits undone (the chain reverter of entry smr1): its text as of fcc1."""
    return _revert(text, MANIFEST_EDITS, "deployment/ha-manifest.yaml")


pre_smr1_manifest.edits = MANIFEST_EDITS   # the PEX contract: a reverter exposes its exact (before, after) pairs


def add_smr1_manifest(text: str) -> str:
    """Applies smr1's deployment/ha-manifest.yaml edits to the text as of fcc1 (the round trip)."""
    return _apply(text, MANIFEST_EDITS, "deployment/ha-manifest.yaml")


# smr1 edits no frozen file.
FROZEN_REVERTERS: dict = {}
# The chain-pinned file smr1 edits, with its reverter (the chain entry's reverts).
PINNED_REVERTERS = {
    MANIFEST_REL: pre_smr1_manifest,
}
