"""rrs1 (reserve control: ONE guarded Home Assistant script that sets the owner's battery reserve; offline, nothing installed). ADDED: the package, its test model and suite, and this
module. CHAIN-PINNED edit: the deployment manifest (one stanza with its comment block). ZERO firmware, registry data, Intelligence, ecco_core or VERSION.yaml byte; ZERO Modbus operation;
the only write the package declares is input_number.ecco_minimum_reserve_soc (a Home Assistant helper), its result text and notifications; nothing here writes an inverter, a dongle, a TOU
slot or a register.

The package is a SECOND writer of the reserve helper (the first is the first-run seed automation of ecco_pro.yaml). The existing suite home-assistant/tests/test_ecco_reserve_default.py pins
"exactly one writer" and fails on it; widening a pinned rule is an OWNER DECISION, so that one-line widening is NOT part of this entry's declarations: it is ONE LAST SEPARATE COMMIT of the
branch (first line "OWNER DECISION REQUIRED"), an ordinary edit of a test file that changes no declaration of this entry (the file was ADDED by rsv1 and is not hashed or pinned).

Same technique as the earlier post-export scope modules: the verbatim manifest edit is held HERE as an exact (before, after) pair, round-trip-checked, and the reverter raises unless the edit is
present exactly once. The post-export chain entry `rrs1` (registry/tests/_scope_chain.py POST_EXPORT_ENTRIES; registry/tests/_pex.py) carries it; its fingerprint is sealed with _pex.sealed and
must be sealed again (registry/tests/_scope_chain.py, the `fingerprint` literal of RRS1) if another entry merges first, and its manifest checkpoint recomputed if that entry edits the manifest. Its
parent is rrb1 (the reserve read-back and dongle-lost alert); the id is rrs1 and not rsv1 (an older entry on main).

This module imports no other scope module, not _scope_chain (the chain imports it) and not _pex. No I/O.
"""

from __future__ import annotations

ID = 'rrs1'

ADDED_FILES = frozenset({
    'home-assistant/packages/ecco_reserve_control.yaml',
    'home-assistant/tests/_reserve_control_sim.py',
    'home-assistant/tests/test_ecco_reserve_control.py',
    'registry/tests/_rrs1_scope.py',
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


  # Reserve control - rrs1 (NOT installed, NOT LIVE-PROVEN). ONE guarded script (script.ecco_reserve_set) that sets the owner's battery reserve: it validates the value (0 to 80, and inside the helper's own min and max), asks for a
  # confirmation when the value is below the reserve the plan uses or below the owner's own (a real lowering, or a raise that stays below the plan reserve while a Prepare for power cut reserve runs), writes only
  # input_number.ecco_minimum_reserve_soc after a stamped WRITING text, reads it back and leaves a result text (one new input_text). It never writes an inverter, dongle, TOU, number, switch or button entity. It is a SECOND
  # writer of the reserve helper: the existing suite test_ecco_reserve_default.py pins one writer and fails on it until the OWNER-DECISION pin widening (the last, separate commit of its branch) is approved. Needs ecco_pro.yaml and
  # ecco_plan_helpers.yaml. Install = copy the file, check the configuration and RELOAD Input texts and Scripts (never while the script runs); no restart, which is why restart_required is false here.
  - source: home-assistant/packages/ecco_reserve_control.yaml
    destination: /config/packages/ecco_reserve_control.yaml
    method: ssh_file_copy
    restart_required: false

dashboard:
""")),
)


def pre_rrs1_manifest(text: str) -> str:
    """deployment/ha-manifest.yaml with exactly rrs1's edit undone (a reverter of chain entry rrs1, PEX): its text as of the entry before."""
    return _revert(text, MANIFEST_EDITS, MANIFEST_REL)


pre_rrs1_manifest.edits = MANIFEST_EDITS   # the PEX contract: a reverter exposes its exact (before, after) pairs


def add_rrs1_manifest(text: str) -> str:
    """Applies rrs1's edit to deployment/ha-manifest.yaml as of the entry before (the round trip)."""
    return _apply(text, MANIFEST_EDITS, MANIFEST_REL)


# The chain-pinned file this entry edits, with its reverter (the chain entry's reverts).
PINNED_REVERTERS = {
    MANIFEST_REL: pre_rrs1_manifest,
}
