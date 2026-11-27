"""rrb1 (reserve floor read-back, reserve control and dongle-lost alert: THREE read-only or guarded Home Assistant packages, offline, nothing installed). ADDED: the three
packages, their three test models and three suites, and this module. CHAIN-PINNED edit: the deployment manifest (three stanzas with their comment blocks). ZERO firmware, registry
data, Intelligence, ecco_core or VERSION.yaml byte; ZERO Modbus operation; the only writes any of the three packages declares are the reserve control script's one write of
input_number.ecco_minimum_reserve_soc (a Home Assistant helper) and the notifications; nothing here writes an inverter, a dongle, a TOU slot or a register.

Same technique as the earlier post-export scope modules: the verbatim manifest edit is held HERE as an exact (before, after) pair, round-trip-checked, and the reverter raises
unless the edit is present exactly once. The post-export chain entry `rrb1` (registry/tests/_scope_chain.py POST_EXPORT_ENTRIES; registry/tests/_pex.py) carries it; its
fingerprint is sealed with _pex.sealed and must be sealed again (registry/tests/_scope_chain.py, the `fingerprint` literal of RRB1) if another entry merges first, and its manifest
checkpoint recomputed if that entry edits the manifest. The id is rrb1 and not rsv1: rsv1 is an older entry on main (the reserve helper's first-run value, _rsv1_scope.py).

This module imports no other scope module, not _scope_chain (the chain imports it) and not _pex. No I/O.
"""

from __future__ import annotations

ID = 'rrb1'

ADDED_FILES = frozenset({
    'home-assistant/packages/ecco_reserve_floor_status.yaml',
    'home-assistant/packages/ecco_reserve_control.yaml',
    'home-assistant/packages/ecco_dongle_lost_alert.yaml',
    'home-assistant/tests/_reserve_floor_status_sim.py',
    'home-assistant/tests/_reserve_control_sim.py',
    'home-assistant/tests/_dongle_lost_alert_sim.py',
    'home-assistant/tests/test_ecco_reserve_floor_status.py',
    'home-assistant/tests/test_ecco_reserve_control.py',
    'home-assistant/tests/test_ecco_dongle_lost_alert.py',
    'registry/tests/_rrb1_scope.py',
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


  # Reserve floor read-back - rrb1 (READ-ONLY; NOT installed, NOT LIVE-PROVEN). Reads back what the inverter's registers say about the battery reserve (the lowest target SOC of the non-charging TOU slots and the
  # shutdown SOC, from the dongle's configuration read) and compares it with the plan's effective reserve: MATCH, BELOW, ABOVE, PENDING or UNREADABLE, one binary sensor (on only for BELOW and UNREADABLE) and one opt-in
  # notification. A register is not behaviour: it makes no claim of enforcement, and it has no DRIFT state. It writes nothing but that notification. Needs the plan helper package and the TOU target SOC editor package.
  # Install = copy the file, check the configuration and RELOAD three domains (Developer tools, YAML): Template entities, Input booleans and Automations; no restart, which is why restart_required is false here.
  - source: home-assistant/packages/ecco_reserve_floor_status.yaml
    destination: /config/packages/ecco_reserve_floor_status.yaml
    method: ssh_file_copy
    restart_required: false

  # Reserve control - rrb1 (NOT installed, NOT LIVE-PROVEN). ONE guarded script (script.ecco_reserve_set) that sets the owner's battery reserve: it validates the value, asks for a confirmation to LOWER it, writes only
  # input_number.ecco_minimum_reserve_soc, reads it back and leaves a result text (one new input_text). It never writes an inverter, dongle, TOU, number, switch or button entity. Needs ecco_pro.yaml and ecco_plan_helpers.yaml.
  # Install = copy the file, check the configuration and RELOAD Input texts and Scripts (never while the script runs); no restart, which is why restart_required is false here.
  - source: home-assistant/packages/ecco_reserve_control.yaml
    destination: /config/packages/ecco_reserve_control.yaml
    method: ssh_file_copy
    restart_required: false

  # Dongle lost during a lease - rrb1 (READ-ONLY; NOT installed, NOT LIVE-PROVEN). Two automations: when a Free Power or Dump to Grid lease was reported active and the dongle's telemetry has then stayed offline for 5 minutes,
  # ONE persistent notification says that no firmware guard may be running and what the owner can do; it dismisses itself when telemetry returns. It presses and writes nothing. Install = copy the file, check the
  # configuration and RELOAD the Automations; no restart, which is why restart_required is false here.
  - source: home-assistant/packages/ecco_dongle_lost_alert.yaml
    destination: /config/packages/ecco_dongle_lost_alert.yaml
    method: ssh_file_copy
    restart_required: false

dashboard:
""")),
)


def pre_rrb1_manifest(text: str) -> str:
    """deployment/ha-manifest.yaml with exactly rrb1's edit undone (a reverter of chain entry rrb1, PEX): its text as of the entry before."""
    return _revert(text, MANIFEST_EDITS, MANIFEST_REL)


pre_rrb1_manifest.edits = MANIFEST_EDITS   # the PEX contract: a reverter exposes its exact (before, after) pairs


def add_rrb1_manifest(text: str) -> str:
    """Applies rrb1's edit to deployment/ha-manifest.yaml as of the entry before (the round trip)."""
    return _apply(text, MANIFEST_EDITS, MANIFEST_REL)


# The chain-pinned file this entry edits, with its reverter (the chain entry's reverts).
PINNED_REVERTERS = {
    MANIFEST_REL: pre_rrb1_manifest,
}
