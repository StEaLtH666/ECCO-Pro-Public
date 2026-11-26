"""ovw4 (the Overview's Energy Actions card carries the Stage 3 plan options) change scope: exactly what ovw4 changes in the files the
pub0 export froze, and its exact inverse.

Same technique as ptt1: every verbatim edit is held HERE as the single source of truth, as an exact (before, after) pair, and each
reverter raises unless each of its edits is present exactly once. The post-export chain entry `ovw4` (registry/tests/_scope_chain.py
POST_EXPORT_ENTRIES, appended after ptt1; registry/tests/_pex.py) carries one frozen reverter for the one frozen file it edits and no
chain reverter.

WHAT ovw4 IS. Stage 3 (PR 59) added three optional settings to the Energy Actions card (frontend/ecco-energy-actions-card): `show_plan`
(the Plan section), `plan` (`entity_prefix`: the six TOU slot entities, the same generic prefix the TOU Settings card uses; `reserve`:
the owner's reserve helper) and `dump_to_grid.guarded_start` (the guarded Dump to Grid start script). The repository's dashboard never
set them, so a production Overview that uses them differed from a render of this repository. ovw4 sets them on the ONE Energy Actions
card of the Overview view, in the dashboard's generic naming (`ecco_clock_dongle`, which tools/ecco_site_render.py renders to the
site's device slug exactly as it does for the TOU Settings cards). Two insertions:
  - home-assistant/dashboards/ecco_pro.yaml (pub0 target, FROZEN): the card's `show_plan` and `plan` block, and `guarded_start`.
The dashboard version is NOT bumped (the precedent of wsc1 and ptt1). The protected layer of the site policy (the Overview's flow
card) is not touched. ZERO firmware, Home Assistant package, deployment manifest, registry, Intelligence or ecco_core change; ZERO
Modbus operation; no service call of its own (the card calls the guarded start only when the owner presses Start).

This module imports no other scope module, not _scope_chain (the chain imports it) and not _pex. No I/O.
"""

from __future__ import annotations

import hashlib

# Public main the change is based on (the state it was rehearsed on is recorded in the private merge-sequence report).
BASE_COMMIT = "c6e5a588a62aad03597d1233d119eefb895990cc"

ADDED_FILES = frozenset({
    'registry/tests/_ovw4_scope.py',
    'home-assistant/tests/test_ecco_energy_actions_plan_options.py',
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
        raise AssertionError(f"ovw4 scope: {what} must be {state} exactly once, found {n}x: {find[:70]!r}")
    i = text.index(find)
    return text[:i] + put + text[i + len(find):]


def _revert(text: str, edits: tuple, what: str) -> str:
    out = text
    for k, (before, after) in reversed(list(enumerate(edits))):
        out = _swap(out, after, before, f"{what} edit {k}", "present")
    for k, (before, _after) in enumerate(edits):
        n = out.count(before)
        if n != 1:
            raise AssertionError(f"ovw4 scope: {what} anchor {k} must be unique once the edits are removed, found {n}x")
    return out


def _apply(text: str, edits: tuple, what: str) -> str:
    out = text
    for k, (before, after) in enumerate(edits):
        if after in out:
            raise AssertionError(f"ovw4 scope: {what} edit {k} is already present")
        out = _swap(out, before, after, f"{what} anchor {k}", "found")
    return out


# ---- (PEX frozen edit) home-assistant/dashboards/ecco_pro.yaml -----------------------------------------------------------------------
DASHBOARD_REL = "home-assistant/dashboards/ecco_pro.yaml"
# 1. The card head (whole lines; the only Energy Actions card of the dashboard): show_plan and the plan block after `layout: tabbed`.
ANCHOR_CARD = _blk(r"""
          - type: custom:ecco-energy-actions-card
            title: Energy Actions
            layout: tabbed
""")
PLAN_BLOCK = _blk(r"""
            show_plan: true
            plan:
              entity_prefix: "ecco_clock_dongle"
              reserve: input_number.ecco_minimum_reserve_soc
""")
# 2. The Dump to Grid schedule's last line: guarded_start is a sibling of `schedule:` under dump_to_grid.
ANCHOR_SCHEDULE = _blk(r"""
                cancel: script.ecco_dump_to_grid_cancel_schedule
""")
GUARDED_LINE = _blk(r"""
              guarded_start: script.ecco_dump_to_grid_start_guarded
""")
DASHBOARD_EDITS = (
    (ANCHOR_CARD, ANCHOR_CARD + PLAN_BLOCK),
    (ANCHOR_SCHEDULE, ANCHOR_SCHEDULE + GUARDED_LINE),
)


def pre_ovw4_dashboard(text: str) -> str:
    """home-assistant/dashboards/ecco_pro.yaml with exactly ovw4's edits undone (a frozen reverter of chain entry ovw4, PEX)."""
    return _revert(text, DASHBOARD_EDITS, "home-assistant/dashboards/ecco_pro.yaml")


pre_ovw4_dashboard.edits = DASHBOARD_EDITS   # the PEX contract: a reverter exposes its exact (before, after) pairs


def add_ovw4_dashboard(text: str) -> str:
    """Applies ovw4's home-assistant/dashboards/ecco_pro.yaml edits to the earlier text (the round trip)."""
    return _apply(text, DASHBOARD_EDITS, "home-assistant/dashboards/ecco_pro.yaml")


# Every frozen file ovw4 edits, with its reverter (the chain entry's frozen_reverts).
FROZEN_REVERTERS = {
    DASHBOARD_REL: pre_ovw4_dashboard,
}
