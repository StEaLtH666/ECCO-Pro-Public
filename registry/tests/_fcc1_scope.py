"""fcc1 (full-capability controls: the owner's view of the fcp1 / fcp2 Dump to Grid limits and the firmware readiness states)
change scope: exactly what fcc1 changes in the chain-pinned deployment manifest, and its exact inverse.

Same technique as the earlier post-export scope modules: every verbatim edit is held HERE as the single source of truth, as an exact
(before, after) pair, and the reverter raises unless each of its edits is present exactly once. The post-export chain entry `fcc1`
(registry/tests/_scope_chain.py POST_EXPORT_ENTRIES, appended last after fcp2; registry/tests/_pex.py) carries one chain-pinned
reverter for the manifest.

WHAT fcc1 IS. The Home Assistant side of the merged fcp1 / fcp2 firmware, which already validates, stores and enforces the limits
on the dongle; none of its 13 new entities was used by Home Assistant. New files (ADDED_FILES):
  home-assistant/packages/ecco_dump_limits.yaml       template entities that DESCRIBE the dongle's limits state (VALID / NOT
                                                      CONFIGURED / INVALID / AWAITING CONFIRMATION / UNKNOWN / UNAVAILABLE), the
                                                      ceiling against the owner's supervised proven level (a helper record,
                                                      first run 3000 W), the not-configured export and an attention flag; one
                                                      automation that only creates / dismisses a persistent notification
  home-assistant/dashboards/ecco_full_capability.yaml a separate admin-only dashboard (built-in cards only) showing the limits,
                                                      the firmware's own two number boxes and arm, and the restore /
                                                      containment / lockout / readiness states; no service call
  home-assistant/tests/test_ecco_dump_limits.py       its offline proofs; docs/dev/full-capability-controls.md; this module.
ZERO firmware, registry, Intelligence or ecco_core byte; ZERO Modbus operation; no new firmware entity; the package and the
dashboard write nothing to the dongle (no number / switch / button / script / esphome action).

CHAIN-PINNED edit.
  deployment/ha-manifest.yaml               one home_assistant_packages stanza for the new package

NOT frozen (ordinary edits, nothing to declare): registry/tests/test_pex_transition.py (the PEX ledger), CHANGELOG.md,
registry/tests/test_dump_safety_fcp2.py (it no longer requires fcp2 to be the newest entry; its position is still pinned) and
home-assistant/tests/test_ecco_tou_target_soc_edit.py (it reads the manifest as of acs0, since fcc1 edits it later).

This module imports no other scope module, not _scope_chain (the chain imports it) and not _pex. No I/O.
"""

from __future__ import annotations

import hashlib

# Public main the change is based on (fcp2 merged as PR #28).
BASE_COMMIT = "ef8c3177cb9bb5075af0a888f7bfce1ad45f218b"

PACKAGE_REL = "home-assistant/packages/ecco_dump_limits.yaml"
DASHBOARD_REL = "home-assistant/dashboards/ecco_full_capability.yaml"
ADDED_FILES = frozenset({
    "docs/dev/full-capability-controls.md",
    DASHBOARD_REL,
    PACKAGE_REL,
    "home-assistant/tests/test_ecco_dump_limits.py",
    "registry/tests/_fcc1_scope.py",
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
        raise AssertionError(f"fcc1 scope: {what} must be {state} exactly once, found {n}x: {find[:70]!r}")
    i = text.index(find)
    return text[:i] + put + text[i + len(find):]


def _revert(text: str, edits: tuple, what: str) -> str:
    out = text
    for k, (before, after) in reversed(list(enumerate(edits))):
        out = _swap(out, after, before, f"{what} edit {k}", "present")
    for k, (before, _after) in enumerate(edits):
        n = out.count(before)
        if n != 1:
            raise AssertionError(f"fcc1 scope: {what} anchor {k} must be unique once the edits are removed, found {n}x")
    return out


def _apply(text: str, edits: tuple, what: str) -> str:
    out = text
    for k, (before, after) in enumerate(edits):
        if after in out:
            raise AssertionError(f"fcc1 scope: {what} edit {k} is already present")
        out = _swap(out, before, after, f"{what} anchor {k}", "found")
    return out


# ---- (chain-pinned edit) deployment/ha-manifest.yaml --------------------------------------------------------------------------
MANIFEST_REL = "deployment/ha-manifest.yaml"
MANIFEST_0_OLD = _blk(r"""
    destination: /config/packages/ecco_tou_target_soc_edit.yaml
    method: ssh_file_copy
    restart_required: true
""")
MANIFEST_0_NEW = _blk(r"""
    destination: /config/packages/ecco_tou_target_soc_edit.yaml
    method: ssh_file_copy
    restart_required: true

  # Dump to Grid operating limits, owner view - FCC1 (describes the fcp1 / fcp2 firmware's limits state; template entities, one
  # notification-only automation; writes nothing to the dongle). Deploy only with or after the fcp2 firmware.
  - source: home-assistant/packages/ecco_dump_limits.yaml
    destination: /config/packages/ecco_dump_limits.yaml
    method: ssh_file_copy
    restart_required: true
""")
MANIFEST_EDITS = (
    (MANIFEST_0_OLD, MANIFEST_0_NEW),
)


def pre_fcc1_manifest(text: str) -> str:
    """deployment/ha-manifest.yaml with exactly fcc1's edits undone (the chain reverter of entry fcc1): its text as of fcp2."""
    return _revert(text, MANIFEST_EDITS, "deployment/ha-manifest.yaml")


pre_fcc1_manifest.edits = MANIFEST_EDITS   # the PEX contract: a reverter exposes its exact (before, after) pairs


def add_fcc1_manifest(text: str) -> str:
    """Applies fcc1's deployment/ha-manifest.yaml edits to the text as of fcp2 (the round trip)."""
    return _apply(text, MANIFEST_EDITS, "deployment/ha-manifest.yaml")


# fcc1 edits no frozen file.
FROZEN_REVERTERS: dict = {}
# The chain-pinned file fcc1 edits, with its reverter (the chain entry's reverts).
PINNED_REVERTERS = {
    MANIFEST_REL: pre_fcc1_manifest,
}
