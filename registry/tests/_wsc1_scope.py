"""wsc1 (the ECCO Weather & Solar card on the dashboard) change scope: exactly what wsc1 changes in a file the pub0 export froze, and
its exact inverse.

Same technique as the earlier post-export scope modules: the verbatim edit is held HERE as the single source of truth, as an exact
(before, after) pair, and the reverter raises unless the edit is present exactly once. The post-export chain entry `wsc1`
(registry/tests/_scope_chain.py POST_EXPORT_ENTRIES, appended last after esb1; registry/tests/_pex.py) carries
`pre_wsc1_dashboard` as its one frozen reverter.

WHAT wsc1 IS. One new dashboard view, "Weather & Solar", placed immediately after Overview, holding the read-only
custom:ecco-weather-solar-card (frontend/ecco-weather-solar-card, added earlier as new files) with its default entities. The card
sends no command (two read-only websocket messages, pinned by its suites). ZERO firmware, Home Assistant package, deployment,
registry, Intelligence or ecco_core change; ZERO Modbus operation (64 reads / 52 writes unchanged); no manifest stanza (the card is
deployed like the flow card, as a manual Lovelace resource); VERSION.yaml unchanged (tested_in_home_assistant stays false).

FROZEN edit (PEX). home-assistant/dashboards/ecco_pro.yaml: one inserted view block before the Intelligence view. pre_wsc1_dashboard
undoes it exactly, so the dashboard as of the previous entry is its declared checkpoint, and as of pub0 it is the export.

This module imports no other scope module, not _scope_chain (the chain imports it) and not _pex. No I/O.
"""

from __future__ import annotations

import hashlib

DASHBOARD_REL = "home-assistant/dashboards/ecco_pro.yaml"

ADDED_FILES = frozenset({
    "registry/tests/_wsc1_scope.py",
})


def _blk(s: str) -> str:
    """A raw triple-quoted literal that starts on the line after the opening quotes: drops that first newline."""
    assert s.startswith("\n") and s.endswith("\n") and "\r" not in s
    return s[1:]


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ---- (PEX frozen edit) the dashboard: the Weather & Solar view, inserted right after Overview -----------------------------------
DASHBOARD_VIEW_OLD = _blk(r"""
  - title: Intelligence
    path: ecco-intelligence
""")
DASHBOARD_VIEW_NEW = _blk(r"""
  - title: Weather & Solar
    path: ecco-weather-solar
    icon: mdi:weather-partly-cloudy
    type: sections
    max_columns: 4
    dense_section_placement: true
    sections:
      # ================= WEATHER & SOLAR (read-only) =================
      # One read-only custom card (frontend/ecco-weather-solar-card, registered as a manual Lovelace
      # resource): Met.no weather and forecast, sun times, the ECCO blended solar forecast with its
      # Solcast and Forecast.Solar inputs, an hourly solar chart and the existing accuracy scorecard.
      # It sends no command. Entity ids are the card's own defaults (see its README).
      - type: grid
        column_span: 4
        cards:
          - type: custom:ecco-weather-solar-card
            grid_options:
              columns: full


  - title: Intelligence
    path: ecco-intelligence
""")
DASHBOARD_EDITS = ((DASHBOARD_VIEW_OLD, DASHBOARD_VIEW_NEW),)


def _swap(text: str, find: str, put: str, what: str, state: str) -> str:
    n = text.count(find)
    if n != 1:
        raise AssertionError(f"wsc1 scope: {what} must be {state} exactly once, found {n}x: {find[:70]!r}")
    i = text.index(find)
    return text[:i] + put + text[i + len(find):]


def pre_wsc1_dashboard(text: str) -> str:
    """The dashboard with exactly wsc1's one edit undone (the frozen reverter of chain entry wsc1, PEX). The edited block must occur
    exactly once, else AssertionError; after the revert the anchor must again be unique."""
    out = text
    for before, after in reversed(DASHBOARD_EDITS):
        out = _swap(out, after, before, "dashboard Weather & Solar view", "present")
    for before, _after in DASHBOARD_EDITS:
        if out.count(before) != 1:
            raise AssertionError("wsc1 scope: the dashboard anchor must be unique once the edit is removed")
    return out


pre_wsc1_dashboard.edits = DASHBOARD_EDITS   # the PEX contract: a frozen reverter exposes its exact (before, after) pairs


def add_wsc1_dashboard(text: str) -> str:
    """Applies wsc1's dashboard edit to the previous state (the round trip). The anchor must occur exactly once."""
    out = text
    for before, after in DASHBOARD_EDITS:
        if after in out:
            raise AssertionError("wsc1 scope: the dashboard Weather & Solar view is already present")
        out = _swap(out, before, after, "dashboard Intelligence-view anchor", "found")
    return out
