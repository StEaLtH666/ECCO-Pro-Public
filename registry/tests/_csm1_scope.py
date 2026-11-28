"""csm1 (the CONTROL STATE read model: one display for Charge Battery and Export to Grid, slice S-A1 of the shared control integration; offline, nothing installed). ADDED: the package, its suite and the
test support module of that suite. CHAIN-PINNED edit: the deployment manifest (one stanza with its comment block). ZERO firmware, registry data, Intelligence, ecco_core or VERSION.yaml byte; ZERO Modbus
operation; the package is three template sensors only (no automation, helper, script, trigger, action or service call) and writes nothing; no existing package, card or dashboard is edited. TWO existing
suites are edited, each only to widen a pinned list of the packages that may read a fact, DELIBERATELY and exactly as the design (decision D-PIN) names it: home-assistant/tests/test_ecco_start_gate.py (the
no-other-package-mentions-the-gate check becomes a READERS list: the export gate may be read by the export coordinator and by the control state package, the charge gate by the control state package) and
home-assistant/tests/test_ecco_time_trust.py (READERS and PINNED_READERS, two copies, add the export coordinator and the control state package for the LEASES consumer only). Each widening is pinned by mutants:
a further reader, a wider entry or a dropped entry fails.

Same technique as the earlier post-export scope modules: the verbatim manifest edit is held HERE as an exact (before, after) pair, round-trip-checked, and the reverter raises
unless the edit is present exactly once. The post-export chain entry `csm1` (registry/tests/_scope_chain.py POST_EXPORT_ENTRIES; registry/tests/_pex.py) carries it; its
fingerprint is sealed with _pex.sealed and must be sealed again if another entry merges first (and its manifest checkpoint recomputed if that entry edits the manifest). The entries must be
re-sealed in merge order when main's chain moves: 70, 72, 74, this one, then the reserve branch.

This module imports no other scope module, not _scope_chain (the chain imports it) and not _pex. No I/O.
"""

from __future__ import annotations

ID = 'csm1'

ADDED_FILES = frozenset({
    'home-assistant/packages/ecco_control_state.yaml',
    'home-assistant/tests/_control_state_sim.py',
    'home-assistant/tests/test_ecco_control_state.py',
    'registry/tests/_csm1_scope.py',
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


  # Control state - csm1 (READ-ONLY DISPLAY; NOT installed, NOT LIVE-PROVEN). Slice S-A1 of the shared control integration. Three template sensors and nothing else: sensor.ecco_charge_control_state and
  # sensor.ecco_export_control_state (a lifecycle state IDLE / PLANNED / ARMED / ASSISTED / RUNNING / ENDING / FAULT / UNKNOWN, why, the next action, what blocks a start and what the lease holds, all in fixed sentences) and
  # sensor.ecco_control_owner (who holds the inverter settings), read from the two start gates, the leases consumer of the time trust package, the dongle's lease flags and status texts, the plan's hold and reserve, the
  # schedules and, when it is installed, the export coordinator (optional: while it is absent the proposal reads NOT_INSTALLED). A display, never a gate: no automation, script, helper, trigger or service call, nothing may read them
  # (the suites pin it), no measurement and no moving time in an attribute, so it writes no row without a real change. THE GATES ARE SOFT: the dongle's own Start button bypasses them. OWNER DECISION (a): with the lease flag on, a refused press (a REJECTED text, which overwrites the status of the dongle and cannot tell a healthy
  # lease from a lockout) reads FAULT with the code STATUS_HIDDEN_BY_REFUSED_PRESS, never RUNNING; a firmware recovery-state signal, if ever read (a new reader and its own review), could restore RUNNING. Install = copy the file, check the
  # configuration and reload the template entities (Developer tools, YAML): no restart, which is why restart_required is false; it needs the owner's go, and ONLY with NO Dump to Grid or Free Power lease running and outside any
  # armed scheduled Export or charge run (from its start to its window end plus 10 minutes): the reload re-creates every template entity, the plan's hold and effective reserve sensors included, which the Export schedule's
  # press-time recheck reads. It needs ecco_time_trust.yaml, ecco_start_gate.yaml, ecco_plan_helpers.yaml and both schedule packages. Delete the file and reload to remove it.
  - source: home-assistant/packages/ecco_control_state.yaml
    destination: /config/packages/ecco_control_state.yaml
    method: ssh_file_copy
    restart_required: false

dashboard:
""")),
)


def pre_csm1_manifest(text: str) -> str:
    """deployment/ha-manifest.yaml with exactly csm1's edit undone (a reverter of chain entry csm1, PEX): its text as of the entry before."""
    return _revert(text, MANIFEST_EDITS, MANIFEST_REL)


pre_csm1_manifest.edits = MANIFEST_EDITS   # the PEX contract: a reverter exposes its exact (before, after) pairs


def add_csm1_manifest(text: str) -> str:
    """Applies csm1's edit to deployment/ha-manifest.yaml as of the entry before (the round trip)."""
    return _apply(text, MANIFEST_EDITS, MANIFEST_REL)


# The chain-pinned file this entry edits, with its reverter (the chain entry's reverts).
PINNED_REVERTERS = {
    MANIFEST_REL: pre_csm1_manifest,
}
