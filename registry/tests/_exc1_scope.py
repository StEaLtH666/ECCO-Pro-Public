"""exc1 (the EXPORT COORDINATOR v0, a READ-ONLY SHADOW proposal for Export to Grid; item N3 of the architecture reconciliation; offline, nothing installed). ADDED: the package, its suite and the
test support module of that suite. CHAIN-PINNED edit: the deployment manifest (one stanza with its comment block). ZERO firmware, registry data, Intelligence, ecco_core or VERSION.yaml byte; ZERO Modbus
operation; the package is template entities only (no automation, helper, script, trigger, action or service call) and writes nothing; no existing package, card or dashboard is edited. ONE existing suite,
home-assistant/tests/test_ecco_start_gate.py, is edited so that its two pins on sgt1's own state are read as of sgt1 (every later entry's manifest edit undone first): every assertion is kept, only "sgt1
is the newest entry" is dropped, which no later entry can satisfy.

Same technique as the earlier post-export scope modules: the verbatim manifest edit is held HERE as an exact (before, after) pair, round-trip-checked, and the reverter raises
unless the edit is present exactly once. The post-export chain entry `exc1` (registry/tests/_scope_chain.py POST_EXPORT_ENTRIES; registry/tests/_pex.py) carries it; its
fingerprint is sealed with _pex.sealed and must be sealed again if another entry merges first (and its manifest checkpoint recomputed if that entry edits the manifest).

This module imports no other scope module, not _scope_chain (the chain imports it) and not _pex. No I/O.
"""

from __future__ import annotations

ID = 'exc1'

ADDED_FILES = frozenset({
    'home-assistant/packages/ecco_export_coordinator.yaml',
    'home-assistant/tests/_export_coordinator_sim.py',
    'home-assistant/tests/test_ecco_export_coordinator.py',
    'registry/tests/_exc1_scope.py',
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


  # Export coordinator - exc1 (READ-ONLY SHADOW; NOT installed, NOT LIVE-PROVEN). Item N3 of the architecture reconciliation. Nine template sensors and nothing else: from MEASURED values (no forecast entity is read)
  # a proposal for an Export to Grid start on the schedule path (the Stop SOC floor, the usable energy above it, the expected battery power, the net export target and the duration, bounded by the schedule's own window (a running lease gets no time past the end of the window it runs in), with a
  # state VALID / INVALID / UNVERIFIED / HOLD and every blocking cause named), a re-target shadow (would a change be allowed now: an END plus a guarded re-START, at most one per 30 minutes, only reported, only for a lease the
  # schedule started, whose END it can only keep or shorten; END NOW is the lease guard's rule) and a comparison with that lease's latched values. No automation, script, helper, trigger or service call; only the control state read model (a display) reads the sensors. THE GATES ARE SOFT: the
  # dongle's own Start button bypasses them. Slice S-A2: it reads the Export start gate (a VALID proposal the gate does not allow is NOT ALLOWED with the gate's own codes, and `actionable` needs the gate open for 60 s) and the leases consumer of the
  # time trust package (a re-target is ALLOWED only while it has read on for 60 s, else WAIT with TIME_NOT_TRUSTED), only as far as the two pinned reader lists allow (widened deliberately, design decision D-PIN); the model carries no time of its
  # evaluation, so with unchanged inputs it writes no row (D-C04a, route a).
  # Install = copy the file, check the configuration and reload the template entities (Developer tools, YAML): no restart, which is why restart_required is false; it needs the owner's go, and ONLY with NO Dump to Grid or
  # Free Power lease running and outside any armed scheduled Export or charge run (from its start to its window end plus 10 minutes): the reload re-creates every template entity, the plan's hold and effective reserve
  # sensors included, which the Export schedule's press-time recheck reads. The recorder exclusion of the model sensor AND of the lookups (the proposal, its power, its duration, the re-target and the shadow comparison) is MANDATORY (it takes effect at the next Core restart, so until then the row rate applies: the published powers move in steps of 500 W and the durations in steps of 5 minutes, which lowers the typical rate (99 rows an hour for the model in a realistic house, 191 when the load hovers at a step boundary, 10 s polls) but is NOT a worst-case bound: the worst case is about one row per poll for each of the five entities, 360 an hour each (1800 for the five), and up to about 500 each (2500 for the five) while a lease runs; batch 2 stops and looks if one entity or the five together pass those figures). It needs ecco_plan_helpers.yaml, ecco_dump_limits.yaml, ecco_dump_to_grid_schedule.yaml,
  # ecco_canonical_telemetry.yaml, ecco_battery_runtime.yaml, ecco_start_gate.yaml and ecco_time_trust.yaml (the gate and the consumer it reads). Delete the file and reload to remove it.
  - source: home-assistant/packages/ecco_export_coordinator.yaml
    destination: /config/packages/ecco_export_coordinator.yaml
    method: ssh_file_copy
    restart_required: false

dashboard:
""")),
)


def pre_exc1_manifest(text: str) -> str:
    """deployment/ha-manifest.yaml with exactly exc1's edit undone (a reverter of chain entry exc1, PEX): its text as of the entry before."""
    return _revert(text, MANIFEST_EDITS, MANIFEST_REL)


pre_exc1_manifest.edits = MANIFEST_EDITS   # the PEX contract: a reverter exposes its exact (before, after) pairs


def add_exc1_manifest(text: str) -> str:
    """Applies exc1's edit to deployment/ha-manifest.yaml as of the entry before (the round trip)."""
    return _apply(text, MANIFEST_EDITS, MANIFEST_REL)


# The chain-pinned file this entry edits, with its reverter (the chain entry's reverts).
PINNED_REVERTERS = {
    MANIFEST_REL: pre_exc1_manifest,
}
