"""rsv1 (the first-run value of the battery reserve helper is 40 %, not 15 %) change scope: exactly what rsv1 changes in the file the
pub0 export froze, and its exact inverse.

Same technique as the earlier post-export scope modules: the one verbatim edit is held HERE as the single source of truth, as an exact
(before, after) pair generated from the real diff and round-trip-checked, and the reverter raises unless its edit is present exactly
once. The post-export chain entry `rsv1` (registry/tests/_scope_chain.py POST_EXPORT_ENTRIES, appended last; registry/tests/_pex.py)
carries one frozen reverter.

WHAT rsv1 IS. input_number.ecco_minimum_reserve_soc is the user's own, Home Assistant-editable battery reserve (0-80 %). The core
package (home-assistant/packages/ecco_pro.yaml, a pub0 target, FROZEN) gave it a first-run value of 15 % in its one-time defaults
automation (ecco_phase3a_initialize_defaults: triggered by the Home Assistant start event, gated on ecco_defaults_initialized being
off, and turning that flag on at its end). rsv1 changes that one number to 40 %, the owner's preferred starting value, and adds a
two-line comment saying what the number is: a starting value, not a limit. Nothing else changes:
  - the helper keeps NO `initial`, so Home Assistant restores the user's value across restarts and updates (a configured `initial`
    would overwrite it at every start); an installation that has been initialised keeps its value because the automation is gated
    on the flag, which Home Assistant restores too;
  - no runtime decision hard-codes 40 % (nothing in firmware, Free Power, Dump-to-Grid or the packages uses the helper as a limit;
    Intelligence takes it as a run-time input that can only raise its own reserve);
  - ZERO firmware, dashboard, registry, Intelligence, ecco_core, deployment or Modbus change.

NOT frozen (ordinary edits, nothing to declare): SAFETY.md, CHANGELOG.md, docs/BATTERY_TIME_TO_RESERVE.md and
docs/intelligence/DATA_INVENTORY.md. Added: home-assistant/tests/test_ecco_reserve_default.py (the first-installation, upgrade,
restart, restored-state, invalid-value and user-change suite) and this module.

This module imports no other scope module, not _scope_chain (the chain imports it) and not _pex. No I/O.
"""

from __future__ import annotations

import hashlib

# Public main the change is based on (FPS1, the Free Power scheduling reliability fix).
BASE_COMMIT = "fbe03aac62201cc1714866d079a8eb90cde08d0f"

ADDED_FILES = frozenset({
    "home-assistant/tests/test_ecco_reserve_default.py",
    "registry/tests/_rsv1_scope.py",
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
        raise AssertionError(f"rsv1 scope: {what} must be {state} exactly once, found {n}x: {find[:70]!r}")
    i = text.index(find)
    return text[:i] + put + text[i + len(find):]


def _revert(text: str, edits: tuple, what: str) -> str:
    out = text
    for k, (before, after) in reversed(list(enumerate(edits))):
        out = _swap(out, after, before, f"{what} edit {k}", "present")
    for k, (before, _after) in enumerate(edits):
        n = out.count(before)
        if n != 1:
            raise AssertionError(f"rsv1 scope: {what} anchor {k} must be unique once the edits are removed, found {n}x")
    return out


def _apply(text: str, edits: tuple, what: str) -> str:
    out = text
    for k, (before, after) in enumerate(edits):
        if after in out:
            raise AssertionError(f"rsv1 scope: {what} edit {k} is already present")
        out = _swap(out, before, after, f"{what} anchor {k}", "found")
    return out


# ---- (PEX frozen edit) home-assistant/packages/ecco_pro.yaml -------------------------------------------------------------------------
PACKAGE_REL = "home-assistant/packages/ecco_pro.yaml"
# The first-run value of the reserve helper: 15 -> 40, with a comment that says what the number is.
PACKAGE_0_OLD = _blk(r"""
      - action: input_number.set_value
        target: {entity_id: input_number.ecco_minimum_reserve_soc}
        data: {value: 15}
""")
PACKAGE_0_NEW = _blk(r"""
      # First-run STARTING value of the user's reserve, not a limit: this automation runs once (until ecco_defaults_initialized
      # is on) and the helper has no `initial`, so Home Assistant restores the user's own value across restarts and updates.
      - action: input_number.set_value
        target: {entity_id: input_number.ecco_minimum_reserve_soc}
        data: {value: 40}
""")
PACKAGE_EDITS = (
    (PACKAGE_0_OLD, PACKAGE_0_NEW),
)


def pre_rsv1_package(text: str) -> str:
    """home-assistant/packages/ecco_pro.yaml with exactly rsv1's edit undone (a frozen reverter of chain entry rsv1, PEX)."""
    return _revert(text, PACKAGE_EDITS, "home-assistant/packages/ecco_pro.yaml")


pre_rsv1_package.edits = PACKAGE_EDITS   # the PEX contract: a reverter exposes its exact (before, after) pairs


def add_rsv1_package(text: str) -> str:
    """Applies rsv1's home-assistant/packages/ecco_pro.yaml edit to the earlier text (the round trip)."""
    return _apply(text, PACKAGE_EDITS, "home-assistant/packages/ecco_pro.yaml")


# Every frozen file rsv1 edits, with its reverter (the chain entry's frozen_reverts).
FROZEN_REVERTERS = {
    PACKAGE_REL: pre_rsv1_package,
}
