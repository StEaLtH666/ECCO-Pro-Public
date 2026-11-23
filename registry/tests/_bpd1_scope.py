"""bpd1 (the start bypass detector: DETECT AND ALERT ONLY, option O2 of the R9 / Stage 3 integration plan; offline, nothing installed). ADDED: the detector package and its
suite. CHAIN-PINNED edit: the deployment manifest (one stanza with its comment block). ZERO firmware, registry data, Intelligence, ecco_core or VERSION.yaml byte; ZERO Modbus
operation; the package calls only persistent_notification.create and the setters of its own helpers (input_text, input_number, input_datetime), never a dongle, inverter,
TOU or ECCO control service.

Same technique as the earlier post-export scope modules: the verbatim manifest edit is held HERE as an exact (before, after) pair, round-trip-checked, and the reverter raises
unless the edit is present exactly once. The post-export chain entry `bpd1` (registry/tests/_scope_chain.py POST_EXPORT_ENTRIES; registry/tests/_pex.py) carries it; its
fingerprint is sealed with _pex.sealed and must be sealed again if another entry merges first.

This module imports no other scope module, not _scope_chain (the chain imports it) and not _pex. No I/O.
"""

from __future__ import annotations

ID = 'bpd1'

ADDED_FILES = frozenset({
    'home-assistant/packages/ecco_start_bypass_detector.yaml',
    'home-assistant/tests/test_ecco_start_bypass_detector.py',
    'registry/tests/_bpd1_scope.py',
})

import hashlib


def _blk(s: str) -> str:
    """A raw triple-quoted literal that starts on the line after the opening quotes: drops that first newline."""
    assert s.startswith("\n") and s.endswith("\n") and "\r" not in s
    return s[1:]


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _swap(text: str, find: str, put: str, what: str, state: str) -> str:
    n = text.count(find)
    if n != 1:
        raise AssertionError(f"{ID} scope: {what} must be {state} exactly once, found {n}x: {find[:70]!r}")
    i = text.index(find)
    return text[:i] + put + text[i + len(find):]


def _revert(text: str, edits: tuple, what: str) -> str:
    out = text
    for k, (before, after) in reversed(list(enumerate(edits))):
        out = _swap(out, after, before, f"{what} edit {k}", "present")
    for k, (before, _after) in enumerate(edits):
        n = out.count(before)
        if n != 1:
            raise AssertionError(f"{ID} scope: {what} anchor {k} must be unique once the edits are removed, found {n}x")
    return out


def _apply(text: str, edits: tuple, what: str) -> str:
    out = text
    for k, (before, after) in enumerate(edits):
        if after in out:
            raise AssertionError(f"{ID} scope: {what} edit {k} is already present")
        out = _swap(out, before, after, f"{what} anchor {k}", "found")
    return out


# ---- (chain-pinned edit) deployment/ha-manifest.yaml -------------------------------------------------------------
MANIFEST_REL = 'deployment/ha-manifest.yaml'
MANIFEST_EDITS = (
    (_blk(r"""


dashboard:
"""),
     _blk(r"""


  # Start bypass detector - bpd1 (detect and alert only; NOT installed, NOT live-proven). Notices a Dump to Grid or Charge Battery session that turned active
  # without ECCO's own record of the start (the scheduled run's STARTED OK, or the guarded start), raises one persistent notification and records an incident in
  # its own helpers. It writes nothing but those helpers and the notification (no dongle, inverter, TOU or ECCO control), PREVENTS NOTHING and is blind while
  # Home Assistant is down. It reads the plan sensors, the two schedule packages' result texts and the guarded start script: install it in the SAME deployment as,
  # or after, ecco_plan_helpers.yaml, ecco_dump_to_grid_guarded_start.yaml and the two schedule packages (the ONE full Home Assistant restart covers it; installed
  # alone later it needs no restart: reload the four helper domains and automations, never "reload all").
  - source: home-assistant/packages/ecco_start_bypass_detector.yaml
    destination: /config/packages/ecco_start_bypass_detector.yaml
    method: ssh_file_copy
    restart_required: true

dashboard:
""")),
)


def pre_bpd1_manifest(text: str) -> str:
    """deployment/ha-manifest.yaml with exactly bpd1's edit undone (a reverter of chain entry bpd1, PEX): its text as of the entry before."""
    return _revert(text, MANIFEST_EDITS, MANIFEST_REL)


pre_bpd1_manifest.edits = MANIFEST_EDITS   # the PEX contract: a reverter exposes its exact (before, after) pairs


def add_bpd1_manifest(text: str) -> str:
    """Applies bpd1's edit to deployment/ha-manifest.yaml as of the entry before (the round trip)."""
    return _apply(text, MANIFEST_EDITS, MANIFEST_REL)


# The chain-pinned file this entry edits, with its reverter (the chain entry's reverts).
PINNED_REVERTERS = {
    MANIFEST_REL: pre_bpd1_manifest,
}
