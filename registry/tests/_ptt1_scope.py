"""ptt1 (the Power Flow Today chart's tooltip stays inside the card and the viewport) change scope: exactly what ptt1 changes in the
files the pub0 export froze, and its exact inverse.

Same technique as the earlier post-export scope modules: every verbatim edit is held HERE as the single source of truth, as an exact
(before, after) pair generated from the real diff and round-trip-checked, and each reverter raises unless each of its edits is present
exactly once. The post-export chain entry `ptt1` (registry/tests/_scope_chain.py POST_EXPORT_ENTRIES, appended last after isp1;
registry/tests/_pex.py) carries one frozen reverter for the one frozen file it edits and no chain reverter.

WHAT ptt1 IS. The `Power Flow Today` chart (custom:apexcharts-card; three identical copies, in the Overview, Intelligence and System
views, which differ only in chart height and grid_options) shows a shared tooltip with five readings (Solar, House, Battery, Grid, SOC).
ApexCharts places that tooltip from the plot grid only; it is absolutely positioned inside the chart and the card's ha-card clips it
(`overflow: hidden`, the card's own style and the card_mod style). On the Overview chart (card height 7 rows) the tooltip regularly ends
below the card and the last reading, SOC, is cut off. ptt1 adds ONE key to each of the three charts, apex_config.chart.events.mounted,
an EVAL string (apexcharts-card evaluates every apex_config string that starts with EVAL: as JavaScript, as the chart's existing TOU
annotation already does) whose code keeps the tooltip inside the card and the viewport: a MutationObserver sees ApexCharts position the
tooltip and moves it the shortest way inside (a pure function, `fit`; the tooltip is put beside the pointer instead only when that move
would put it under the pointer); it changes only the tooltip's style.left and style.top. No series, colour, value, legend, axis,
annotation, grid, stroke, tooltip option or card_mod change, no tooltip content change, no card source change, no service call, no
entity, no network access.
  - home-assistant/dashboards/ecco_pro.yaml (pub0 target, FROZEN): three insertions, one per chart.
The dashboard version is NOT bumped (VERSION.yaml and the header notes are untouched: the same precedent as wsc1, which changed the
dashboard "without a version bump of its own"; the v7.23.0 pins stay as they are). ZERO firmware, Home Assistant package, deployment
manifest, registry, Intelligence or ecco_core change; ZERO Modbus operation. Every other section and view of the dashboard is
byte-identical.

NOT frozen (ordinary edits, nothing to declare): the new suite home-assistant/tests/test_ecco_power_chart_tooltip.py, CHANGELOG.md and
docs. Added: this module and that suite.

This module imports no other scope module, not _scope_chain (the chain imports it) and not _pex. No I/O.
"""

from __future__ import annotations

import hashlib

# Public main the change is based on.
BASE_COMMIT = "c6e5a588a62aad03597d1233d119eefb895990cc"

ADDED_FILES = frozenset({
    'registry/tests/_ptt1_scope.py',
    'home-assistant/tests/test_ecco_power_chart_tooltip.py',
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
        raise AssertionError(f"ptt1 scope: {what} must be {state} exactly once, found {n}x: {find[:70]!r}")
    i = text.index(find)
    return text[:i] + put + text[i + len(find):]


def _revert(text: str, edits: tuple, what: str) -> str:
    out = text
    for k, (before, after) in reversed(list(enumerate(edits))):
        out = _swap(out, after, before, f"{what} edit {k}", "present")
    for k, (before, _after) in enumerate(edits):
        n = out.count(before)
        if n != 1:
            raise AssertionError(f"ptt1 scope: {what} anchor {k} must be unique once the edits are removed, found {n}x")
    return out


def _apply(text: str, edits: tuple, what: str) -> str:
    out = text
    for k, (before, after) in enumerate(edits):
        if after in out:
            raise AssertionError(f"ptt1 scope: {what} edit {k} is already present")
        out = _swap(out, before, after, f"{what} anchor {k}", "found")
    return out


# ---- (PEX frozen edit) home-assistant/dashboards/ecco_pro.yaml -----------------------------------------------------------------------
DASHBOARD_REL = "home-assistant/dashboards/ecco_pro.yaml"
# The block inserted after `toolbar: show: false` of each chart's apex_config.chart (the same text three times; indentation as in the file).
TOOLTIP_BLOCK = _blk(r"""
                events:
                  mounted: |
                    EVAL:(() => {
                      /* Power Flow tooltip containment. ApexCharts places the shared tooltip from the plot grid only, so with five
                         rows it can end below the card, where ha-card (overflow hidden) cuts the last row (SOC). After every move
                         the tooltip is moved the shortest way into the card and the viewport; if that move would put it under the
                         pointer it is put beside (or above / below) the pointer instead.
                         fit() is pure. r = tooltip rect {x,y,w,h} where ApexCharts put it, p = pointer {x,y} or null,
                         b = bounds {l,t,r,b}, g = gap to the pointer. A box larger than the bounds is aligned to their top left. */
                      const fit = (r, p, b, g) => {
                        const lim = (v, n, lo, hi) => Math.max(lo, Math.min(v, hi - n));
                        const hit = (x, y) => p && p.x >= x && p.x <= x + r.w && p.y >= y && p.y <= y + r.h;
                        let x = lim(r.x, r.w, b.l, b.r), y = lim(r.y, r.h, b.t, b.b);
                        if (hit(x, y) && !hit(r.x, r.y)) {
                          const side = [p.x - g - r.w, p.x + g].filter((v) => v >= b.l && v + r.w <= b.r);
                          const lift = [p.y - g - r.h, p.y + g].filter((v) => v >= b.t && v + r.h <= b.b);
                          if (x !== r.x && side.length) x = side[side.length > 1 && r.x > p.x ? 1 : 0];
                          else if (y !== r.y && lift.length) y = lift[lift.length > 1 && r.y > p.y ? 1 : 0];
                        }
                        return { x, y };
                      };
                      const mounted = (chart) => {
                        const el = chart.el, drop = chart.destroy, ac = new AbortController();
                        const on = { signal: ac.signal, capture: true, passive: true };
                        let p = null;
                        if (el.__eccoTip) el.__eccoTip.abort();
                        el.__eccoTip = ac;
                        const aim = (e) => { const t = e.touches ? e.touches[0] : e; if (t) p = { x: t.clientX, y: t.clientY }; };
                        const place = () => {
                          const t = el.querySelector('.apexcharts-tooltip'), card = t && t.closest('ha-card'), host = t && t.offsetParent;
                          if (!card || !host || !t.classList.contains('apexcharts-active')) return;
                          const v = window.visualViewport || { offsetLeft: 0, offsetTop: 0, width: innerWidth, height: innerHeight };
                          const k = card.getBoundingClientRect(), h = host.getBoundingClientRect(), s = t.getBoundingClientRect(), m = 4;
                          const ox = h.left + host.clientLeft, oy = h.top + host.clientTop;
                          const r = { x: ox + parseFloat(t.style.left), y: oy + parseFloat(t.style.top), w: s.width, h: s.height };
                          const q = fit(r, p, {
                            l: Math.max(k.left, v.offsetLeft) + m, t: Math.max(k.top, v.offsetTop) + m,
                            r: Math.min(k.right, v.offsetLeft + v.width) - m, b: Math.min(k.bottom, v.offsetTop + v.height) - m
                          }, 12);
                          if (isFinite(q.x) && isFinite(q.y) && (Math.abs(q.x - r.x) > 0.5 || Math.abs(q.y - r.y) > 0.5)) {
                            t.style.left = q.x - ox + 'px';
                            t.style.top = q.y - oy + 'px';
                          }
                        };
                        const win = () => { if (el.isConnected) place(); else off(); };
                        const off = () => { window.removeEventListener('scroll', win, true); window.removeEventListener('resize', win, true); };
                        const seen = new MutationObserver(place);
                        ['mousemove', 'touchstart', 'touchmove'].forEach((n) => el.addEventListener(n, aim, on));
                        seen.observe(el, { subtree: true, childList: true, attributes: true, attributeFilter: ['style', 'class'] });
                        window.addEventListener('scroll', win, true);
                        window.addEventListener('resize', win, true);
                        ac.signal.addEventListener('abort', () => { seen.disconnect(); off(); });
                        chart.destroy = function () { ac.abort(); return drop.apply(this, arguments); };
                      };
                      mounted.fit = fit;
                      return mounted;
                    })()
""")
# The three anchors: whole lines of the chart's apex_config.chart ending at the insertion point, each unique in the 7.23.0 dashboard.
# Overview chart (height 365, grid_options columns full / rows 7): its chart height line is unique.
ANCHOR_OVERVIEW = _blk(r"""
                height: 365
                toolbar:
                  show: false
""")
# Intelligence chart (height 490, columns 48 / rows 10) and System chart (height 490, columns 28 / rows 11): the three charts are the same
# text except the chart height and the grid_options, so these two anchors reach back to the grid_options.
ANCHOR_INTELLIGENCE = _blk(r"""
              rows: 10
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
              - entity: sensor.ecco_clock_dongle_ecco_pv_power
                name: Solar
                yaxis_id: power
                type: area
                color: '#ffbd3d'
                opacity: 0.22
              - entity: sensor.ecco_house_power
                name: House
                yaxis_id: power
                type: line
                color: '#42aaff'
                stroke_width: 3
              - entity: sensor.ecco_clock_dongle_ecco_battery_output_power
                name: Battery
                yaxis_id: power
                type: area
                color: '#39d27a'
                opacity: 0.14
              - entity: sensor.ecco_clock_dongle_ecco_grid_power_ct_clamp
                name: Grid
                yaxis_id: power
                type: line
                color: '#b36cff'
                stroke_width: 2
              - entity: sensor.ecco_clock_dongle_ecco_battery_soc
                name: SOC
                yaxis_id: soc
                type: line
                color: '#ff6376'
                stroke_width: 2
                opacity: 0.95
                group_by:
                  func: last
                  duration: 5min
                  fill: last
            now:
              show: true
              color: '#6d7b91'
              label: Now
            apex_config:
              chart:
                height: 490
                toolbar:
                  show: false
""")
ANCHOR_SYSTEM = _blk(r"""
              rows: 11
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
              - entity: sensor.ecco_clock_dongle_ecco_pv_power
                name: Solar
                yaxis_id: power
                type: area
                color: '#ffbd3d'
                opacity: 0.22
              - entity: sensor.ecco_house_power
                name: House
                yaxis_id: power
                type: line
                color: '#42aaff'
                stroke_width: 3
              - entity: sensor.ecco_clock_dongle_ecco_battery_output_power
                name: Battery
                yaxis_id: power
                type: area
                color: '#39d27a'
                opacity: 0.14
              - entity: sensor.ecco_clock_dongle_ecco_grid_power_ct_clamp
                name: Grid
                yaxis_id: power
                type: line
                color: '#b36cff'
                stroke_width: 2
              - entity: sensor.ecco_clock_dongle_ecco_battery_soc
                name: SOC
                yaxis_id: soc
                type: line
                color: '#ff6376'
                stroke_width: 2
                opacity: 0.95
                group_by:
                  func: last
                  duration: 5min
                  fill: last
            now:
              show: true
              color: '#6d7b91'
              label: Now
            apex_config:
              chart:
                height: 490
                toolbar:
                  show: false
""")
DASHBOARD_EDITS = (
    (ANCHOR_OVERVIEW, ANCHOR_OVERVIEW + TOOLTIP_BLOCK),
    (ANCHOR_INTELLIGENCE, ANCHOR_INTELLIGENCE + TOOLTIP_BLOCK),
    (ANCHOR_SYSTEM, ANCHOR_SYSTEM + TOOLTIP_BLOCK),
)


def pre_ptt1_dashboard(text: str) -> str:
    """home-assistant/dashboards/ecco_pro.yaml with exactly ptt1's edits undone (a frozen reverter of chain entry ptt1, PEX)."""
    return _revert(text, DASHBOARD_EDITS, "home-assistant/dashboards/ecco_pro.yaml")


pre_ptt1_dashboard.edits = DASHBOARD_EDITS   # the PEX contract: a reverter exposes its exact (before, after) pairs


def add_ptt1_dashboard(text: str) -> str:
    """Applies ptt1's home-assistant/dashboards/ecco_pro.yaml edits to the earlier text (the round trip)."""
    return _apply(text, DASHBOARD_EDITS, "home-assistant/dashboards/ecco_pro.yaml")


# Every frozen file ptt1 edits, with its reverter (the chain entry's frozen_reverts).
FROZEN_REVERTERS = {
    DASHBOARD_REL: pre_ptt1_dashboard,
}
