"""sgt1 (the shared START GATE for Charge Battery and Export to Grid, a GUARDED FREE POWER START and the IN-LEASE END GUARDS; offline, nothing installed, the gate is SOFT). ADDED: the four packages (the gate and three lease
guards, one file each), their suite and the test support module of that suite. CHAIN-PINNED edit: the deployment manifest (four stanzas with their comment blocks). ZERO firmware, registry data, Intelligence, ecco_core or VERSION.yaml byte; ZERO Modbus operation of its own
(the guarded start stages and presses the dongle's existing Free Power start button as the scheduled start and the card do; the guards only press the two existing END buttons); no existing package, card or dashboard is edited.

Same technique as the earlier post-export scope modules: the verbatim manifest edit is held HERE as an exact (before, after) pair, round-trip-checked, and the reverter raises
unless the edit is present exactly once. The post-export chain entry `sgt1` (registry/tests/_scope_chain.py POST_EXPORT_ENTRIES; registry/tests/_pex.py) carries it; its
fingerprint is sealed with _pex.sealed and must be sealed again if another entry merges first (and its manifest checkpoint recomputed if that entry edits the manifest).

This module imports no other scope module, not _scope_chain (the chain imports it) and not _pex. No I/O.
"""

from __future__ import annotations

ID = 'sgt1'

ADDED_FILES = frozenset({
    'home-assistant/packages/ecco_lease_guard_dump.yaml',
    'home-assistant/packages/ecco_lease_guard_free_power_import.yaml',
    'home-assistant/packages/ecco_lease_guard_free_power_time.yaml',
    'home-assistant/packages/ecco_start_gate.yaml',
    'home-assistant/tests/_start_gate_sim.py',
    'home-assistant/tests/test_ecco_start_gate.py',
    'registry/tests/_sgt1_scope.py',
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


  # Start gate - sgt1 (NOT installed, NOT LIVE-PROVEN). Item N2 of the architecture reconciliation. Two template binary sensors, binary_sensor.ecco_charge_start_allowed and binary_sensor.ecco_export_start_allowed:
  # ONE shared start gate for Charge Battery (Free Power) and Export to Grid (Dump to Grid), built only from facts ECCO already has (time trust, telemetry, no open recovery obligation, the other function not running;
  # for Export the Stage 3 hold, reserve, Stop SOC and plan revision; for Charge a grid-import headroom check that is OFF until the owner sets input_number.ecco_grid_import_ceiling_w, a helper with no initial value:
  # only a readable 0 means none configured, a ceiling that cannot be read closes the gate). Every missing, unavailable or unknown input closes the gate and is named in its reasons. Also
  # script.ecco_free_power_start_guarded: a guarded Free Power start bound to the gate (a NEW start path; the Energy Actions card is NOT changed in this step and still presses the dongle's start button directly, and
  # the start bypass detector would record a start of it as a bypass; a refused explicit request puts the staged values it replaced back). THE GATE IS SOFT: the dongle's own Start button bypasses it until a firmware gate
  # exists. Nothing calls the script and nothing writes to the inverter. Install = copy the file, check the configuration, then reload the input_number helpers first, then the template entities, then the scripts,
  # one at a time (never "reload all"): no restart, which is why restart_required is false. It needs ecco_time_trust.yaml, ecco_plan_helpers.yaml and the two schedule packages. Delete the file and reload the
  # same three to remove it.
  - source: home-assistant/packages/ecco_start_gate.yaml
    destination: /config/packages/ecco_start_gate.yaml
    method: ssh_file_copy
    restart_required: false
  # Lease guard, Dump to Grid - sgt1 (NOT installed, NOT LIVE-PROVEN). THIS GUARD NEEDS THE OWNER'S SEPARATE INSTALL AUTHORISATION. One automation that only ever presses END DUMP TO GRID - RESTORE NOW: it ends a Dump
  # to Grid lease when a Hold battery, Skip tonight or Prepare for power cut turns on, or the effective reserve rises above the Stop SOC the lease latched. The Dump End is not an operator retry in the firmware (it clears
  # no lockout and resets no backoff), so the guard needs no precondition beyond an active lease. It starts, arms and writes nothing, acts only on a change from a reading (never at a Home Assistant start, a reload or a
  # reconnect) and is SOFT (it runs in Home Assistant). Install = copy the file, check the configuration, reload the automations: no restart. Delete the file and reload to remove it.
  - source: home-assistant/packages/ecco_lease_guard_dump.yaml
    destination: /config/packages/ecco_lease_guard_dump.yaml
    method: ssh_file_copy
    restart_required: false
  # Lease guard, Free Power time trust - sgt1 (NOT installed, NOT LIVE-PROVEN). THIS GUARD NEEDS THE OWNER'S SEPARATE INSTALL AUTHORISATION. One automation that only ever presses END FREE POWER - RESTORE NOW, when
  # binary_sensor.ecco_time_trusted_for_leases has not read on for 5 minutes. THAT PRESS IS THE OPERATOR'S END (in the firmware the press that retries a restore and clears the operator-decision lockout), so it is made only
  # for a lease verified running normally (status ACTIVE - VERIFIED OK, no start or restore in progress, an end time in the future) and at most once per lease, and it says why when it declines. It starts, arms and writes
  # nothing, acts only on a change from a reading (never at a Home Assistant start, a reload or a reconnect) and is SOFT (it runs in Home Assistant). It reads ecco_time_trust.yaml (it is on that package's READERS
  # allow-list). Install = copy the file, check the configuration, reload the automations: no restart. Delete the file and reload to remove it.
  - source: home-assistant/packages/ecco_lease_guard_free_power_time.yaml
    destination: /config/packages/ecco_lease_guard_free_power_time.yaml
    method: ssh_file_copy
    restart_required: false
  # Lease guard, Free Power grid import - sgt1 (NOT installed, NOT LIVE-PROVEN). THIS GUARD NEEDS THE OWNER'S SEPARATE INSTALL AUTHORISATION. One automation that only ever presses END FREE POWER - RESTORE NOW, when the
  # measured grid import stays above the configured ceiling (input_number.ecco_grid_import_ceiling_w, of the start gate) for 30 seconds. THAT PRESS IS THE OPERATOR'S END, so it is made only for a lease verified running
  # normally and at most once per lease, and it says why when it declines. A second small automation in the same file only raises a notification, and never presses, when the ceiling cannot be read (the guard is then
  # inert). They start, arm and write nothing and are SOFT (they run in Home Assistant). Install = copy the file, check the configuration, reload the automations: no restart. Delete the file and reload to remove it.
  - source: home-assistant/packages/ecco_lease_guard_free_power_import.yaml
    destination: /config/packages/ecco_lease_guard_free_power_import.yaml
    method: ssh_file_copy
    restart_required: false

dashboard:
""")),
)


def pre_sgt1_manifest(text: str) -> str:
    """deployment/ha-manifest.yaml with exactly sgt1's edit undone (a reverter of chain entry sgt1, PEX): its text as of the entry before."""
    return _revert(text, MANIFEST_EDITS, MANIFEST_REL)


pre_sgt1_manifest.edits = MANIFEST_EDITS   # the PEX contract: a reverter exposes its exact (before, after) pairs


def add_sgt1_manifest(text: str) -> str:
    """Applies sgt1's edit to deployment/ha-manifest.yaml as of the entry before (the round trip)."""
    return _apply(text, MANIFEST_EDITS, MANIFEST_REL)


# The chain-pinned file this entry edits, with its reverter (the chain entry's reverts).
PINNED_REVERTERS = {
    MANIFEST_REL: pre_sgt1_manifest,
}
