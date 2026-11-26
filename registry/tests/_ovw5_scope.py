"""ovw5 (the Solar series of each Power Flow Today chart carries its own group_by with fill last) change scope: exactly what ovw5
changes in the files the pub0 export froze, and its exact inverse.

Same technique as ptt1 and ovw4: every verbatim edit is held HERE as the single source of truth, as an exact (before, after) pair, and
the reverter raises unless each of its edits is present exactly once. The post-export chain entry `ovw5` (registry/tests/_scope_chain.py
POST_EXPORT_ENTRIES, appended after ovw4; registry/tests/_pex.py) carries one frozen reverter for the one frozen file it edits and no
chain reverter.

WHAT ovw5 IS. The `Power Flow Today` chart (custom:apexcharts-card; three copies, in the Overview, Intelligence and System views, the same
text but for the chart height and the grid_options) draws five series (Solar, House, Battery, Grid, SOC). `all_series_config.group_by`
averages every series per 5 minutes and turns an empty bucket into a null point (`fill: 'null'`); the SOC series already has its own
`group_by` with `fill: last`. apexcharts-card (the installed 2.2.3, read from its source; it is third-party and not part of this repository)
drops the trailing buckets of a series that hold no value (empty, or a single null point), and it shows the shared tooltip with every series
only while all series have the same time points: when one series has fewer it falls back to the one series nearest the cursor. Whenever the PV reading did not change within the newest 5-minute
bucket (evening and night) the Solar series ended one bucket before the others and the tooltip listed Solar alone. ovw5 gives the Solar
series of each chart its own `group_by` (`func: avg`, `duration: 5min`, `fill: last`, four lines): an empty bucket takes the last known
value, so Solar ends with the other series. The change was applied to the production Overview first (25 Nov 2026, the owner's report of a
one-series tooltip); this entry records it in the repository, so that a whole-file dashboard deployment of a render of this repository
cannot put the old text back. Nothing is added to the card's own options, nothing else of the chart changes.
  - home-assistant/dashboards/ecco_pro.yaml (pub0 target, FROZEN): ONE exact (before, after) pair, found and made exactly three times
    (once per chart; SOLAR_PAIR below), declared to the post-export layer as three hunks (see DASHBOARD_EDITS).
THE TRADE-OFF (recorded in docs/dev/post-export-edit-layer.md and pinned by home-assistant/tests/test_ecco_power_flow_solar_fill.py):
`fill: last` has no age limit (the card offers only `last`, `zero` and `null`). A reading that keeps its last value (held, stale) is drawn
flat, exactly as a steady reading would be. An entity that goes `unavailable` still draws a gap: the card turns a state that is not a number
into a null point, so its bucket is not empty and is not filled. A freshness limit (a template sensor that is `unavailable` unless the
dongle's telemetry is live, used as the Solar series entity) is NOT built.
The dashboard version is NOT bumped (the precedent of wsc1, ptt1 and ovw4). The site policy's protected layer (the Overview's flow card)
is not touched. ZERO firmware, Home Assistant package, deployment manifest, registry, Intelligence or ecco_core change; ZERO Modbus
operation; no service call, no entity, no network access.

NOT frozen (ordinary edits, nothing to declare): the new suite home-assistant/tests/test_ecco_power_flow_solar_fill.py, CHANGELOG.md and
docs. Added: this module and that suite.

This module imports no other scope module, not _scope_chain (the chain imports it) and not _pex. No I/O.
"""

from __future__ import annotations

import hashlib

# Public main the change is based on (the state it was rehearsed on is recorded in the private merge-sequence report).
BASE_COMMIT = "c6e5a588a62aad03597d1233d119eefb895990cc"

ADDED_FILES = frozenset({
    'registry/tests/_ovw5_scope.py',
    'home-assistant/tests/test_ecco_power_flow_solar_fill.py',
})

CHARTS = 3   # the Power Flow Today charts of the dashboard: the Overview, Intelligence and System views


def _blk(s: str) -> str:
    """A raw triple-quoted literal that starts on the line after the opening quotes: drops that first newline."""
    assert s.startswith("\n") and s.endswith("\n") and "\r" not in s
    return s[1:]


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _swap(text: str, find: str, put: str, what: str, state: str) -> str:
    n = text.count(find)
    if n != 1:
        raise AssertionError(f"ovw5 scope: {what} must be {state} exactly once, found {n}x: {find[:70]!r}")
    i = text.index(find)
    return text[:i] + put + text[i + len(find):]


def _count(text: str, find: str, want: int, what: str) -> None:
    n = text.count(find)
    if n != want:
        raise AssertionError(f"ovw5 scope: {what} must occur exactly {want}x, found {n}x: {find[:70]!r}")


def _revert(text: str, edits: tuple, what: str) -> str:
    out = text
    for k, (before, after) in reversed(list(enumerate(edits))):
        out = _swap(out, after, before, f"{what} edit {k}", "present")
    for k, (before, _after) in enumerate(edits):
        n = out.count(before)
        if n != 1:
            raise AssertionError(f"ovw5 scope: {what} anchor {k} must be unique once the edits are removed, found {n}x")
    return out


def _apply(text: str, edits: tuple, what: str) -> str:
    out = text
    for k, (before, after) in enumerate(edits):
        if after in out:
            raise AssertionError(f"ovw5 scope: {what} edit {k} is already present")
        out = _swap(out, before, after, f"{what} anchor {k}", "found")
    return out


# ---- (PEX frozen edit) home-assistant/dashboards/ecco_pro.yaml -----------------------------------------------------------------------
DASHBOARD_REL = "home-assistant/dashboards/ecco_pro.yaml"
# THE ONE PAIR. The Solar series of a Power Flow Today chart (whole lines, the same text in the three charts) and the same text with the
# series' own group_by after its last key (indentation as in the file): four inserted lines per chart. Both sides occur exactly CHARTS times.
SOLAR_SERIES = _blk(r"""
              - entity: sensor.ecco_clock_dongle_ecco_pv_power
                name: Solar
                yaxis_id: power
                type: area
                color: '#ffbd3d'
                opacity: 0.22
""")
SOLAR_GROUP_BY = _blk(r"""
                group_by:
                  func: avg
                  duration: 5min
                  fill: last
""")
SOLAR_BEFORE = SOLAR_SERIES
SOLAR_AFTER = SOLAR_SERIES + SOLAR_GROUP_BY
SOLAR_PAIR = (SOLAR_BEFORE, SOLAR_AFTER)

# The post-export layer requires every declared hunk to occur exactly once (registry/tests/_pex0_scope.py applies the pairs one by one), so
# the one pair is declared three times, each time reaching back through its own chart: the chart's grid_options (the only text that tells the
# Intelligence and the System chart apart) and the lines down to the series list, which carry the chart's own title. The three charts are
# the same text from `header:` to the end of the Solar series; every hunk is therefore the Solar series of a Power Flow Today chart.
CHART_HEAD = _blk(r"""
            header:
              show: true
              title: Power Flow Today • 00:00–24:00
              show_states: true
              colorize_states: true
            graph_span: 24h
            span:
              start: day
            yaxis:
              - id: power
                decimals: 0
                min: '|-500|'
                max: '|+500|'
                apex_config:
                  tickAmount: 6
                  title:
                    text: Power (W)
              - id: soc
                opposite: true
                min: 0
                max: 100
                decimals: 0
                apex_config:
                  tickAmount: 5
                  title:
                    text: SOC (%)
            all_series_config:
              stroke_width: 2
              extend_to: now
              group_by:
                func: avg
                duration: 5min
                fill: 'null'
            series:
""")
GRID_OPTIONS = (   # Overview (card height 7 rows), Intelligence (columns 48 / rows 10), System (columns 28 / rows 11)
    _blk(r"""
              columns: full
              rows: 7
"""),
    _blk(r"""
              columns: 48
              rows: 10
"""),
    _blk(r"""
              columns: 28
              rows: 11
"""),
)
DASHBOARD_EDITS = tuple((grid + CHART_HEAD + SOLAR_BEFORE, grid + CHART_HEAD + SOLAR_AFTER) for grid in GRID_OPTIONS)


def pre_ovw5_dashboard(text: str) -> str:
    """home-assistant/dashboards/ecco_pro.yaml with exactly ovw5's edits undone (a frozen reverter of chain entry ovw5, PEX)."""
    _count(text, SOLAR_AFTER, CHARTS, "the Solar series with its own group_by (the one pair, after)")
    out = _revert(text, DASHBOARD_EDITS, "home-assistant/dashboards/ecco_pro.yaml")
    _count(out, SOLAR_BEFORE, CHARTS, "the Solar series (the one pair, before)")
    _count(out, SOLAR_AFTER, 0, "the Solar series with its own group_by (the one pair, after) once the edits are removed")
    return out


pre_ovw5_dashboard.edits = DASHBOARD_EDITS   # the PEX contract: a reverter exposes its exact (before, after) pairs as .edits


def add_ovw5_dashboard(text: str) -> str:
    """Applies ovw5's home-assistant/dashboards/ecco_pro.yaml edits to the earlier text (the round trip)."""
    _count(text, SOLAR_BEFORE, CHARTS, "the Solar series (the one pair, before)")
    out = _apply(text, DASHBOARD_EDITS, "home-assistant/dashboards/ecco_pro.yaml")
    _count(out, SOLAR_AFTER, CHARTS, "the Solar series with its own group_by (the one pair, after)")
    return out


# Every frozen file ovw5 edits, with its reverter (the chain entry's frozen_reverts).
FROZEN_REVERTERS = {
    DASHBOARD_REL: pre_ovw5_dashboard,
}
