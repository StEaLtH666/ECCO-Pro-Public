"""rrb1 (reserve floor read-back and dongle-lost alert: TWO read-only Home Assistant packages, offline, nothing installed). ADDED: the two packages, their two test models and two
suites, and this module. CHAIN-PINNED edit: the deployment manifest (two stanzas with their comment blocks). ZERO firmware, registry data, Intelligence, ecco_core or VERSION.yaml
byte; ZERO Modbus operation; the only writes either package declares are persistent notifications; nothing here writes an inverter, a dongle, a TOU slot, a register or a helper.
The guarded reserve set script (reserve control) was split out of this entry into its own change (entry rrs1) because it is a second writer of the reserve helper, which a pinned suite forbids.

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
    'home-assistant/packages/ecco_dongle_lost_alert.yaml',
    'home-assistant/tests/_reserve_floor_status_sim.py',
    'home-assistant/tests/_dongle_lost_alert_sim.py',
    'home-assistant/tests/test_ecco_reserve_floor_status.py',
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
  # shutdown SOC, from the dongle's configuration read) and compares it with the plan's effective reserve: MATCH, BELOW, ABOVE, PENDING or UNREADABLE, one binary sensor (binary_sensor.ecco_reserve_floor_registers_below_reserve,
  # on only for BELOW and UNREADABLE) and one opt-in notification. A register is not behaviour: it makes no claim of enforcement (the behavioural NOT HOLDING check is NOT built), it lists the charging slots' targets without judging
  # them, and it has no DRIFT state. Configuration Online off for more than 1800 s, or any one pending cause older than 6 hours, reads UNREADABLE. It writes nothing but that notification. Needs the plan helper package and the
  # TOU target SOC editor package. Install = copy the file, check the configuration and RELOAD three domains (Developer tools, YAML): Template entities, Input booleans and Automations; no restart, which is why restart_required is false here.
  - source: home-assistant/packages/ecco_reserve_floor_status.yaml
    destination: /config/packages/ecco_reserve_floor_status.yaml
    method: ssh_file_copy
    restart_required: false

  # Dongle lost during a lease - rrb1 (READ-ONLY; NOT installed, NOT LIVE-PROVEN). Two automations: when a Free Power or Dump to Grid lease (or the restore a start that failed half-way still owes: Snapshot Valid or Operation In Progress on with Active off) was reported and the dongle's telemetry has then stayed offline for 5 minutes,
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
