"""hd1 (derived house load) change scope: exactly what hd1 changes in the files the pub0 export froze, and its exact inverse.

WHAT hd1 IS. The inverter's native load (register 178, sensor.ecco_clock_dongle_ecco_load_power) reads 0 W in some states,
notably during export, although the house still draws power. The Energy Flow card (resolveHomeW) and the firmware's Dump
feed-forward already resolve it; Home Assistant did not. hd1 makes the canonical sensor.ecco_house_power DERIVED by the same
rule (native when credible; inverter AC output + grid CT, import positive, clamped at 0, when the native load is unavailable or
reads exactly 0 W while inverter + grid exceeds 150 W), never a guessed zero (unconfirmable 0 W or non-fresh telemetry =
unavailable), through a new model entity sensor.ecco_house_power_model in the same package. Its consumers follow:
  - home-assistant/packages/ecco_canonical_telemetry.yaml (FROZEN): the header note and the house block (model + presentation);
  - home-assistant/packages/ecco_pro.yaml (FROZEN): the House Load Snapshot and the Model Inputs Ready gate read the canonical;
  - home-assistant/dashboards/ecco_pro.yaml (FROZEN): 16 house-load reads move from the native load to the canonical (the
    Inverter / Advanced register table keeps showing register 178 itself);
  - influxdb/tasks/ecco_battery_outlook_5m.flux (FROZEN): the load-profile learning excludes 0 W samples (no history rewrite);
  - registry/system_health_checks.yaml (FROZEN): the designed canonical-vs-raw check records the hd1 exception.
ZERO firmware, inverter write, write surface, manifest (no new package file), FE-1 or Energy Flow card change.

Same technique as the earlier post-export scope modules: every verbatim edit is held HERE as an exact (before, after) pair,
generated from the real diff and round-trip-checked; each reverter raises unless each of its edits is present exactly once.

This module imports no other scope module, not _scope_chain (the chain imports it) and not _pex. No I/O.
"""

from __future__ import annotations

import hashlib

# Public main the change is based on.
BASE_COMMIT = "f7f1d572369d82033105449e98e31acd123a3e35"

ADDED_FILES = frozenset({
    "docs/HOUSE_LOAD_HD1.md",
    "home-assistant/tests/test_ecco_house_power_hd1.py",
    "registry/tests/_hd1_scope.py",
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
        raise AssertionError(f"hd1 scope: {what} must be {state} exactly once, found {n}x: {find[:70]!r}")
    i = text.index(find)
    return text[:i] + put + text[i + len(find):]


def _revert(text: str, edits: tuple, what: str) -> str:
    out = text
    for k, (before, after) in reversed(list(enumerate(edits))):
        out = _swap(out, after, before, f"{what} edit {k}", "present")
    for k, (before, _after) in enumerate(edits):
        n = out.count(before)
        if n != 1:
            raise AssertionError(f"hd1 scope: {what} anchor {k} must be unique once the edits are removed, found {n}x")
    return out


def _apply(text: str, edits: tuple, what: str) -> str:
    out = text
    for k, (before, after) in enumerate(edits):
        if after in out:
            raise AssertionError(f"hd1 scope: {what} edit {k} is already present")
        out = _swap(out, before, after, f"{what} anchor {k}", "found")
    return out


# ---- (PEX frozen edit) home-assistant/packages/ecco_canonical_telemetry.yaml --------------------------------------------
CANONICAL_REL = "home-assistant/packages/ecco_canonical_telemetry.yaml"
CANONICAL_0_OLD = _blk(r"""
# not as a replacement for them. Those are untouched by this file.

template:
""")
CANONICAL_0_NEW = _blk(r"""
# not as a replacement for them. Those are untouched by this file.
#
# Exception (hd1): ECCO House Power is DERIVED, not a plain alias - the native load, or inverter + grid CT when the
# native load is unavailable or falsely reads 0 W (see its block below and docs/HOUSE_LOAD_HD1.md).

template:
""")
CANONICAL_1_OLD = _blk(r"""
  - triggers:
      - trigger: homeassistant
        event: start
      - trigger: state
        entity_id: sensor.ecco_clock_dongle_ecco_load_power
    sensor:
      - name: ECCO House Power
        unique_id: ecco_house_power
        unit_of_measurement: W
        device_class: power
        state_class: measurement
        availability: >-
          {{ states('sensor.ecco_clock_dongle_ecco_load_power') not in ['unknown','unavailable','none',''] }}
        state: >-
          {{ states('sensor.ecco_clock_dongle_ecco_load_power') | float(0) | round(1) }}
        attributes:
          source_entity: sensor.ecco_clock_dongle_ecco_load_power
          note: "Whole-house consumption. Always non-negative in current usage."
          refreshed_at: "{{ now().isoformat() }}"

""")
CANONICAL_1_NEW = _blk(r"""
  # hd1 - ECCO House Power is DERIVED, not a plain alias (docs/HOUSE_LOAD_HD1.md). The inverter's native load (register 178,
  # sensor.ecco_clock_dongle_ecco_load_power) reads 0 W in some states, notably while the system exports, although the house
  # still draws power. The same rule the Energy Flow card (resolveHomeW) and the firmware's Dump feed-forward already use:
  #   house = the native load when it is a credible reading; inverter AC output + grid CT (import positive, clamped at 0)
  #           when the native load is unavailable, or reads exactly 0 W while inverter + grid shows more than 150 W.
  # Inverter AC output (register 175) is positive when it supplies AC and negative when it charges from AC, so inverter + grid
  # is the house both while exporting and while charging from the grid. Battery and PV need no term of their own.
  # Never a guessed zero: a native 0 W that inverter + grid cannot confirm, or telemetry that is not fresh, is UNAVAILABLE.
  #
  # The model below holds the resolution and its liveness memory (it is always available, so the memory survives a reload or a
  # restart); ECCO House Power presents it and is unavailable unless the evidence is fresh.
  # Liveness: the dongle's sensor.ecco_clock_dongle_last_telemetry_update text, published only after a COMPLETE poll, as a
  # CHANGE seen by this model within the last 60 s (a reconnect that replays an old text does not count). Before the dongle
  # has NTP time that text is not published: the newest report of the three inputs is the fallback.
  # Consistency: the value is recomputed only when a complete poll has landed (a new poll text), at start, or - with no
  # per-poll text - on any input, so one value never mixes readings of two polls.
  - triggers:
      - trigger: state
        entity_id: sensor.ecco_clock_dongle_last_telemetry_update
        id: poll
      - trigger: state
        entity_id:
          - sensor.ecco_clock_dongle_ecco_load_power
          - sensor.ecco_clock_dongle_ecco_inverter_output_power
          - sensor.ecco_clock_dongle_ecco_grid_power_ct_clamp
        id: input
      - trigger: state
        entity_id: binary_sensor.ecco_clock_dongle_telemetry_online
        id: liveness
      - trigger: time_pattern
        seconds: "/10"
        id: tick
      - trigger: homeassistant
        event: start
        id: start
    sensor:
      - name: ECCO House Power Model
        unique_id: ecco_house_power_model
        icon: mdi:home-lightning-bolt-outline
        device_class: timestamp
        state: "{{ now().isoformat() }}"
        attributes:
          model: >-
            {%- set e_native = 'sensor.ecco_clock_dongle_ecco_load_power' -%}
            {%- set e_inv = 'sensor.ecco_clock_dongle_ecco_inverter_output_power' -%}
            {%- set e_grid = 'sensor.ecco_clock_dongle_ecco_grid_power_ct_clamp' -%}
            {%- set e_online = 'binary_sensor.ecco_clock_dongle_telemetry_online' -%}
            {%- set e_polled = 'sensor.ecco_clock_dongle_last_telemetry_update' -%}
            {%- set prev = this.attributes.get('model') if this is defined and this.attributes is defined else none -%}
            {%- set pm = prev if prev is mapping else {} -%}
            {%- set t = trigger if trigger is defined else none -%}
            {%- set tid = t.id if t is not none and t.id is defined else 'start' -%}
            {%- set now_ts = as_timestamp(now()) -%}
            {%- set online = is_state(e_online, 'on') -%}
            {%- set poll_text = states(e_polled) -%}
            {%- set poll_valid = poll_text not in ['unknown', 'unavailable', 'none', '', 'Waiting'] -%}
            {%- set prev_poll_at = pm.get('poll_seen_at') if pm.get('poll_seen_at') is number else none -%}
            {%- set new_poll = poll_valid and poll_text != pm.get('poll_text') -%}
            {%- set poll_seen_at = now_ts if new_poll else prev_poll_at -%}
            {%- set seen = namespace(ts=[]) -%}
            {%- if poll_valid -%}
              {%- if poll_seen_at is number -%}{%- set seen.ts = [poll_seen_at] -%}{%- endif -%}
            {%- else -%}
              {%- for e in [e_native, e_inv, e_grid] -%}
                {%- set so = states[e] -%}
                {%- if so is not none and so.state not in ['unknown', 'unavailable', 'none', ''] -%}
                  {%- set seen.ts = seen.ts + [as_timestamp(so.last_reported if so.last_reported is defined and so.last_reported is not none else so.last_updated, 0)] -%}
                {%- endif -%}
              {%- endfor -%}
            {%- endif -%}
            {%- set age = (now_ts - (seen.ts | max)) if seen.ts | count > 0 else none -%}
            {%- set fresh = online and age is not none and age >= -5 and age <= 60 -%}
            {%- set recompute = new_poll or tid == 'start' or not poll_valid or pm.get('computed_at') is not number -%}
            {%- set r = namespace(v=pm.get('value_w'), src=pm.get('source', 'none'), why=pm.get('reason', ''),
                                  n=pm.get('native_w'), i=pm.get('inverter_w'), g=pm.get('grid_w'), d=pm.get('derived_w'),
                                  at=pm.get('computed_at')) -%}
            {%- if recompute -%}
              {%- set n = states(e_native) | float(none) -%}
              {%- set n_ok = n is number and n == n and (n | abs) <= 30000 -%}
              {%- set i = states(e_inv) | float(none) -%}
              {%- set g = states(e_grid) | float(none) -%}
              {%- set d_ok = i is number and i == i and (i | abs) <= 30000 and g is number and g == g and (g | abs) <= 30000 -%}
              {%- set d = ([0, i + g] | max) if d_ok else none -%}
              {%- set r.n = (n | round(1)) if n_ok else none -%}
              {%- set r.i = (i | round(1)) if d_ok else none -%}
              {%- set r.g = (g | round(1)) if d_ok else none -%}
              {%- set r.d = (d | round(1)) if d_ok else none -%}
              {%- set r.at = now_ts -%}
              {%- if not n_ok and d_ok -%}
                {%- set r.v = d | round(1) -%}{%- set r.src = 'derived' -%}{%- set r.why = 'native load unavailable' -%}
              {%- elif not n_ok -%}
                {%- set r.v = none -%}{%- set r.src = 'none' -%}{%- set r.why = 'no usable load, inverter or grid reading' -%}
              {%- elif n == 0 and d_ok and d > 150 -%}
                {%- set r.v = d | round(1) -%}{%- set r.src = 'derived' -%}{%- set r.why = 'native load reads 0 W while inverter + grid shows consumption' -%}
              {%- elif n == 0 and d_ok -%}
                {%- set r.v = 0.0 -%}{%- set r.src = 'native' -%}{%- set r.why = 'native 0 W confirmed by inverter + grid' -%}
              {%- elif n == 0 -%}
                {%- set r.v = none -%}{%- set r.src = 'none' -%}{%- set r.why = 'native 0 W cannot be confirmed (inverter or grid reading unavailable)' -%}
              {%- else -%}
                {%- set r.v = ([0, n] | max) | round(1) -%}{%- set r.src = 'native' -%}{%- set r.why = '' -%}
              {%- endif -%}
            {%- endif -%}
            {%- set model = {
                  'value_w': r.v,
                  'source': r.src,
                  'reason': r.why,
                  'native_w': r.n,
                  'inverter_w': r.i,
                  'grid_w': r.g,
                  'derived_w': r.d,
                  'fresh': fresh,
                  'telemetry_age_s': (age | round(1)) if age is not none else none,
                  'poll_text': poll_text if poll_valid else pm.get('poll_text'),
                  'poll_seen_at': poll_seen_at,
                  'computed_at': r.at,
                  'evaluated_at': now().isoformat()
                } -%}
            {{ model }}

  # The canonical house load, for dashboards, the Energy Flow card and the Battery Outlook learning. Lookups only: every value
  # comes from the model above. Unavailable (never 0 W) unless the evidence is fresh and the model is updating.
  - sensor:
      - name: ECCO House Power
        unique_id: ecco_house_power
        unit_of_measurement: W
        device_class: power
        state_class: measurement
        availability: >-
          {%- set m = state_attr('sensor.ecco_house_power_model', 'model') -%}
          {{ m is mapping and m.get('fresh') is sameas true and m.get('value_w') is number
             and (as_timestamp(now()) - as_timestamp(m.get('evaluated_at'), 0)) <= 60 }}
        state: >-
          {%- set m = state_attr('sensor.ecco_house_power_model', 'model') -%}
          {{ m.get('value_w') if m is mapping and m.get('value_w') is number else none }}
        attributes:
          source: >-
            {%- set m = state_attr('sensor.ecco_house_power_model', 'model') -%}
            {{ m.get('source') if m is mapping else 'none' }}
          reason: >-
            {%- set m = state_attr('sensor.ecco_house_power_model', 'model') -%}
            {{ m.get('reason') if m is mapping else 'model not available' }}
          native_w: >-
            {%- set m = state_attr('sensor.ecco_house_power_model', 'model') -%}
            {{ m.get('native_w') if m is mapping else none }}
          derived_w: >-
            {%- set m = state_attr('sensor.ecco_house_power_model', 'model') -%}
            {{ m.get('derived_w') if m is mapping else none }}
          inverter_w: >-
            {%- set m = state_attr('sensor.ecco_house_power_model', 'model') -%}
            {{ m.get('inverter_w') if m is mapping else none }}
          grid_w: >-
            {%- set m = state_attr('sensor.ecco_house_power_model', 'model') -%}
            {{ m.get('grid_w') if m is mapping else none }}
          telemetry_age_s: >-
            {%- set m = state_attr('sensor.ecco_house_power_model', 'model') -%}
            {{ m.get('telemetry_age_s') if m is mapping else none }}
          refreshed_at: >-
            {%- set m = state_attr('sensor.ecco_house_power_model', 'model') -%}
            {{ m.get('evaluated_at') if m is mapping else none }}
          source_entity: sensor.ecco_house_power_model
          note: "Whole-house consumption (hd1): the native load, or inverter + grid CT when the native load is unavailable or falsely 0 W. Never negative; unavailable, never 0 W, when not fresh."
          sign_convention: "Grid CT positive = import; inverter AC output positive = supplying AC"

""")
CANONICAL_EDITS = (
    (CANONICAL_0_OLD, CANONICAL_0_NEW),
    (CANONICAL_1_OLD, CANONICAL_1_NEW),
)


def pre_hd1_canonical(text: str) -> str:
    """home-assistant/packages/ecco_canonical_telemetry.yaml with exactly hd1's edits undone (a frozen reverter of chain entry hd1, PEX)."""
    return _revert(text, CANONICAL_EDITS, "home-assistant/packages/ecco_canonical_telemetry.yaml")


pre_hd1_canonical.edits = CANONICAL_EDITS   # the PEX contract: a reverter exposes its exact (before, after) pairs


def add_hd1_canonical(text: str) -> str:
    """Applies hd1's home-assistant/packages/ecco_canonical_telemetry.yaml edits to the earlier text (the round trip)."""
    return _apply(text, CANONICAL_EDITS, "home-assistant/packages/ecco_canonical_telemetry.yaml")


# ---- (PEX frozen edit) home-assistant/packages/ecco_pro.yaml ------------------------------------------------------------
CORE_REL = "home-assistant/packages/ecco_pro.yaml"
CORE_0_OLD = _blk(r"""
      - name: ECCO House Load Snapshot
        unique_id: ecco_house_load_snapshot
        availability: >
          {{ states('sensor.ecco_clock_dongle_ecco_load_power') not in ['unknown','unavailable','none',''] }}
        unit_of_measurement: W
        device_class: power
        state_class: measurement
        state: "{{ states('sensor.ecco_clock_dongle_ecco_load_power') | float(0) | round(1) }}"
""")
CORE_0_NEW = _blk(r"""
      # hd1: the house load is the derived canonical sensor (never the native load's false 0 W during export)
      - name: ECCO House Load Snapshot
        unique_id: ecco_house_load_snapshot
        availability: >
          {{ states('sensor.ecco_house_power') not in ['unknown','unavailable','none',''] }}
        unit_of_measurement: W
        device_class: power
        state_class: measurement
        state: "{{ states('sensor.ecco_house_power') | float(0) | round(1) }}"
""")
CORE_1_OLD = _blk(r"""
             and states('sensor.ecco_clock_dongle_ecco_load_power') not in ['unknown','unavailable','none','']
             and states('sensor.ecco_clock_dongle_ecco_pv_power') not in ['unknown','unavailable','none','']
""")
CORE_1_NEW = _blk(r"""
             and states('sensor.ecco_house_power') not in ['unknown','unavailable','none','']
             and states('sensor.ecco_clock_dongle_ecco_pv_power') not in ['unknown','unavailable','none','']
""")
CORE_EDITS = (
    (CORE_0_OLD, CORE_0_NEW),
    (CORE_1_OLD, CORE_1_NEW),
)


def pre_hd1_core(text: str) -> str:
    """home-assistant/packages/ecco_pro.yaml with exactly hd1's edits undone (a frozen reverter of chain entry hd1, PEX)."""
    return _revert(text, CORE_EDITS, "home-assistant/packages/ecco_pro.yaml")


pre_hd1_core.edits = CORE_EDITS   # the PEX contract: a reverter exposes its exact (before, after) pairs


def add_hd1_core(text: str) -> str:
    """Applies hd1's home-assistant/packages/ecco_pro.yaml edits to the earlier text (the round trip)."""
    return _apply(text, CORE_EDITS, "home-assistant/packages/ecco_pro.yaml")


# ---- (PEX frozen edit) home-assistant/dashboards/ecco_pro.yaml ----------------------------------------------------------
DASHBOARD_REL = "home-assistant/dashboards/ecco_pro.yaml"
DASHBOARD_0_OLD = _blk(r"""
          # line are gone (the Energy Flow card and the PV forecast strip show those values).
          - type: custom:button-card
            section_mode: true
            name: ECCO Today
            icon: mdi:brain
            show_name: true
            show_icon: true
            show_state: false
            tap_action:
              action: none
            custom_fields:
              status: >
                [[[
                  const n = (id) => Number(states[id]?.state ?? 0);
                  const pv = n('sensor.ecco_clock_dongle_ecco_pv_power');
                  const load = n('sensor.ecco_clock_dongle_ecco_load_power');
""")
DASHBOARD_0_NEW = _blk(r"""
          # line are gone (the Energy Flow card and the PV forecast strip show those values).
          - type: custom:button-card
            section_mode: true
            name: ECCO Today
            icon: mdi:brain
            show_name: true
            show_icon: true
            show_state: false
            tap_action:
              action: none
            custom_fields:
              status: >
                [[[
                  const n = (id) => Number(states[id]?.state ?? 0);
                  const pv = n('sensor.ecco_clock_dongle_ecco_pv_power');
                  const load = n('sensor.ecco_house_power');
""")
DASHBOARD_1_OLD = _blk(r"""
                  </span>`;
                ]]]
              recommendation: >
                [[[
                  const n = (id) => Number(states[id]?.state ?? 0);
                  const clamp = (v,a,b) => Math.max(a,Math.min(b,v));
                  const pv = n('sensor.ecco_clock_dongle_ecco_pv_power');
                  const load = n('sensor.ecco_clock_dongle_ecco_load_power');
""")
DASHBOARD_1_NEW = _blk(r"""
                  </span>`;
                ]]]
              recommendation: >
                [[[
                  const n = (id) => Number(states[id]?.state ?? 0);
                  const clamp = (v,a,b) => Math.max(a,Math.min(b,v));
                  const pv = n('sensor.ecco_clock_dongle_ecco_pv_power');
                  const load = n('sensor.ecco_house_power');
""")
DASHBOARD_2_OLD = _blk(r"""
        cards:
          # ---- CHART DATA STATUS (V2.1): tells a quiet new day apart from a sensor that is not reporting ----
          # Shown only when it has something to say; display only.
          - type: custom:button-card
            section_mode: true
            show_name: false
            show_icon: false
            show_state: false
            tap_action:
              action: none
            variables:
              msg: >
                [[[
                  const ids = [['Solar', 'sensor.ecco_clock_dongle_ecco_pv_power'], ['House', 'sensor.ecco_clock_dongle_ecco_load_power'], ['Battery', 'sensor.ecco_clock_dongle_ecco_battery_output_power'], ['Grid', 'sensor.ecco_clock_dongle_ecco_grid_power_ct_clamp'], ['SOC', 'sensor.ecco_clock_dongle_ecco_battery_soc']];
""")
DASHBOARD_2_NEW = _blk(r"""
        cards:
          # ---- CHART DATA STATUS (V2.1): tells a quiet new day apart from a sensor that is not reporting ----
          # Shown only when it has something to say; display only.
          - type: custom:button-card
            section_mode: true
            show_name: false
            show_icon: false
            show_state: false
            tap_action:
              action: none
            variables:
              msg: >
                [[[
                  const ids = [['Solar', 'sensor.ecco_clock_dongle_ecco_pv_power'], ['House', 'sensor.ecco_house_power'], ['Battery', 'sensor.ecco_clock_dongle_ecco_battery_output_power'], ['Grid', 'sensor.ecco_clock_dongle_ecco_grid_power_ct_clamp'], ['SOC', 'sensor.ecco_clock_dongle_ecco_battery_soc']];
""")
DASHBOARD_3_OLD = _blk(r"""
              rows: 7
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
              - entity: sensor.ecco_clock_dongle_ecco_load_power
""")
DASHBOARD_3_NEW = _blk(r"""
              rows: 7
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
""")
DASHBOARD_4_OLD = _blk(r"""
              rows: auto
          - type: custom:button-card
            section_mode: true
            name: ECCO Today
            icon: mdi:brain
            show_name: true
            show_icon: true
            show_state: false
            tap_action:
              action: none
            custom_fields:
              status: >
                [[[
                  const n = (id) => Number(states[id]?.state ?? 0);
                  const pv = n('sensor.ecco_clock_dongle_ecco_pv_power');
                  const load = n('sensor.ecco_clock_dongle_ecco_load_power');
""")
DASHBOARD_4_NEW = _blk(r"""
              rows: auto
          - type: custom:button-card
            section_mode: true
            name: ECCO Today
            icon: mdi:brain
            show_name: true
            show_icon: true
            show_state: false
            tap_action:
              action: none
            custom_fields:
              status: >
                [[[
                  const n = (id) => Number(states[id]?.state ?? 0);
                  const pv = n('sensor.ecco_clock_dongle_ecco_pv_power');
                  const load = n('sensor.ecco_house_power');
""")
DASHBOARD_5_OLD = _blk(r"""
                  </div>`;
                ]]]
              recommendation: >
                [[[
                  const n = (id) => Number(states[id]?.state ?? 0);
                  const clamp = (v,a,b) => Math.max(a,Math.min(b,v));
                  const pv = n('sensor.ecco_clock_dongle_ecco_pv_power');
                  const load = n('sensor.ecco_clock_dongle_ecco_load_power');
""")
DASHBOARD_5_NEW = _blk(r"""
                  </div>`;
                ]]]
              recommendation: >
                [[[
                  const n = (id) => Number(states[id]?.state ?? 0);
                  const clamp = (v,a,b) => Math.max(a,Math.min(b,v));
                  const pv = n('sensor.ecco_clock_dongle_ecco_pv_power');
                  const load = n('sensor.ecco_house_power');
""")
DASHBOARD_6_OLD = _blk(r"""
                  const clamp=(v,a,b)=>Math.max(a,Math.min(b,v));
                  const loadToday=n('sensor.ecco_clock_dongle_ecco_day_load_energy');
                  const loadW=n('sensor.ecco_clock_dongle_ecco_load_power');
""")
DASHBOARD_6_NEW = _blk(r"""
                  const clamp=(v,a,b)=>Math.max(a,Math.min(b,v));
                  const loadToday=n('sensor.ecco_clock_dongle_ecco_day_load_energy');
                  const loadW=n('sensor.ecco_house_power');
""")
DASHBOARD_7_OLD = _blk(r"""
          # ---- OCTOPUS TARIFF INTELLIGENCE ----
          - type: custom:button-card
            section_mode: true
            name: Smart Charge Strategy
            icon: mdi:battery-charging-medium
            show_name: true
            show_icon: true
            show_state: false
            tap_action:
              action: none
            custom_fields:
              body: >
                [[[
                  const n=(id)=>Number(states[id]?.state??0);
                  const clamp=(v,a,b)=>Math.max(a,Math.min(b,v));
                  const sensors=Object.values(states).filter(s=>s.entity_id.startsWith('sensor.'));
                  const events=Object.values(states).filter(s=>s.entity_id.startsWith('event.'));
                  const friendly=(s)=>String(s?.attributes?.friendly_name??s?.entity_id??'').toLowerCase();
                  const find=(need,exclude=[])=>sensors.find(s=>{
                    const x=friendly(s);return need.every(v=>x.includes(v))&&!exclude.some(v=>x.includes(v));
                  });
                  const num=(s)=>{const v=Number(s?.state);return Number.isFinite(v)?v:null;};
                  const isExport=(s)=>s.entity_id.includes('export')||friendly(s).includes('export');

                  const soc=n('sensor.ecco_clock_dongle_ecco_battery_soc');
                  const capAh=n('sensor.ecco_clock_dongle_ecco_battery_capacity_ah')||620;
                  const capKwh=capAh*51.2/1000;
                  const loadToday=n('sensor.ecco_clock_dongle_ecco_day_load_energy');
                  const loadW=n('sensor.ecco_clock_dongle_ecco_load_power');
""")
DASHBOARD_7_NEW = _blk(r"""
          # ---- OCTOPUS TARIFF INTELLIGENCE ----
          - type: custom:button-card
            section_mode: true
            name: Smart Charge Strategy
            icon: mdi:battery-charging-medium
            show_name: true
            show_icon: true
            show_state: false
            tap_action:
              action: none
            custom_fields:
              body: >
                [[[
                  const n=(id)=>Number(states[id]?.state??0);
                  const clamp=(v,a,b)=>Math.max(a,Math.min(b,v));
                  const sensors=Object.values(states).filter(s=>s.entity_id.startsWith('sensor.'));
                  const events=Object.values(states).filter(s=>s.entity_id.startsWith('event.'));
                  const friendly=(s)=>String(s?.attributes?.friendly_name??s?.entity_id??'').toLowerCase();
                  const find=(need,exclude=[])=>sensors.find(s=>{
                    const x=friendly(s);return need.every(v=>x.includes(v))&&!exclude.some(v=>x.includes(v));
                  });
                  const num=(s)=>{const v=Number(s?.state);return Number.isFinite(v)?v:null;};
                  const isExport=(s)=>s.entity_id.includes('export')||friendly(s).includes('export');

                  const soc=n('sensor.ecco_clock_dongle_ecco_battery_soc');
                  const capAh=n('sensor.ecco_clock_dongle_ecco_battery_capacity_ah')||620;
                  const capKwh=capAh*51.2/1000;
                  const loadToday=n('sensor.ecco_clock_dongle_ecco_day_load_energy');
                  const loadW=n('sensor.ecco_house_power');
""")
DASHBOARD_8_OLD = _blk(r"""
              rows: 6

          # ---- CHART DATA STATUS (V2.1): tells a quiet new day apart from a sensor that is not reporting ----
          # Shown only when it has something to say; display only.
          - type: custom:button-card
            section_mode: true
            show_name: false
            show_icon: false
            show_state: false
            tap_action:
              action: none
            variables:
              msg: >
                [[[
                  const ids = [['Solar', 'sensor.ecco_clock_dongle_ecco_pv_power'], ['House', 'sensor.ecco_clock_dongle_ecco_load_power'], ['Battery', 'sensor.ecco_clock_dongle_ecco_battery_output_power'], ['Grid', 'sensor.ecco_clock_dongle_ecco_grid_power_ct_clamp'], ['SOC', 'sensor.ecco_clock_dongle_ecco_battery_soc']];
""")
DASHBOARD_8_NEW = _blk(r"""
              rows: 6

          # ---- CHART DATA STATUS (V2.1): tells a quiet new day apart from a sensor that is not reporting ----
          # Shown only when it has something to say; display only.
          - type: custom:button-card
            section_mode: true
            show_name: false
            show_icon: false
            show_state: false
            tap_action:
              action: none
            variables:
              msg: >
                [[[
                  const ids = [['Solar', 'sensor.ecco_clock_dongle_ecco_pv_power'], ['House', 'sensor.ecco_house_power'], ['Battery', 'sensor.ecco_clock_dongle_ecco_battery_output_power'], ['Grid', 'sensor.ecco_clock_dongle_ecco_grid_power_ct_clamp'], ['SOC', 'sensor.ecco_clock_dongle_ecco_battery_soc']];
""")
DASHBOARD_9_OLD = _blk(r"""
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
              - entity: sensor.ecco_clock_dongle_ecco_load_power
""")
DASHBOARD_9_NEW = _blk(r"""
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
""")
DASHBOARD_10_OLD = _blk(r"""
          # ---- TARIFF-AWARE NEXT-CHEAP STRATEGY ----
          - type: custom:button-card
            section_mode: true
            name: Smart Charge Strategy
            icon: mdi:battery-charging-medium
            show_name: true
            show_icon: true
            show_state: false
            tap_action:
              action: none
            custom_fields:
              body: >
                [[[
                  const n=(id)=>Number(states[id]?.state??0);
                  const clamp=(v,a,b)=>Math.max(a,Math.min(b,v));
                  const sensors=Object.values(states).filter(s=>s.entity_id.startsWith('sensor.'));
                  const events=Object.values(states).filter(s=>s.entity_id.startsWith('event.'));
                  const friendly=(s)=>String(s?.attributes?.friendly_name??s?.entity_id??'').toLowerCase();
                  const find=(need,exclude=[])=>sensors.find(s=>{
                    const x=friendly(s);return need.every(v=>x.includes(v))&&!exclude.some(v=>x.includes(v));
                  });
                  const num=(s)=>{const v=Number(s?.state);return Number.isFinite(v)?v:null;};
                  const isExport=(s)=>s.entity_id.includes('export')||friendly(s).includes('export');

                  const soc=n('sensor.ecco_clock_dongle_ecco_battery_soc');
                  const capAh=n('sensor.ecco_clock_dongle_ecco_battery_capacity_ah')||620;
                  const capKwh=capAh*51.2/1000;
                  const loadToday=n('sensor.ecco_clock_dongle_ecco_day_load_energy');
                  const loadW=n('sensor.ecco_clock_dongle_ecco_load_power');
""")
DASHBOARD_10_NEW = _blk(r"""
          # ---- TARIFF-AWARE NEXT-CHEAP STRATEGY ----
          - type: custom:button-card
            section_mode: true
            name: Smart Charge Strategy
            icon: mdi:battery-charging-medium
            show_name: true
            show_icon: true
            show_state: false
            tap_action:
              action: none
            custom_fields:
              body: >
                [[[
                  const n=(id)=>Number(states[id]?.state??0);
                  const clamp=(v,a,b)=>Math.max(a,Math.min(b,v));
                  const sensors=Object.values(states).filter(s=>s.entity_id.startsWith('sensor.'));
                  const events=Object.values(states).filter(s=>s.entity_id.startsWith('event.'));
                  const friendly=(s)=>String(s?.attributes?.friendly_name??s?.entity_id??'').toLowerCase();
                  const find=(need,exclude=[])=>sensors.find(s=>{
                    const x=friendly(s);return need.every(v=>x.includes(v))&&!exclude.some(v=>x.includes(v));
                  });
                  const num=(s)=>{const v=Number(s?.state);return Number.isFinite(v)?v:null;};
                  const isExport=(s)=>s.entity_id.includes('export')||friendly(s).includes('export');

                  const soc=n('sensor.ecco_clock_dongle_ecco_battery_soc');
                  const capAh=n('sensor.ecco_clock_dongle_ecco_battery_capacity_ah')||620;
                  const capKwh=capAh*51.2/1000;
                  const loadToday=n('sensor.ecco_clock_dongle_ecco_day_load_energy');
                  const loadW=n('sensor.ecco_house_power');
""")
DASHBOARD_11_OLD = _blk(r"""
              rows: 5
          - type: custom:button-card
            section_mode: true
            name: Current Plan
            icon: mdi:calendar-clock
            show_name: true
            show_icon: true
            show_state: false
            tap_action:
              action: none
            custom_fields:
              mode: >
                [[[
                  const em = states['sensor.ecco_clock_dongle_ecco_energy_management_model']?.state ?? 'Unknown';
                  const tou = states['binary_sensor.ecco_clock_dongle_ecco_time_of_use_enabled']?.state === 'on';
                  return `<span style="display:inline-block;padding:5px 10px;border-radius:999px;
                    background:rgba(143,124,255,0.12);border:1px solid rgba(143,124,255,0.28);
                    color:#b8adff;font-size:12px;font-weight:700;">
                    ${em}${tou ? ' • TOU active' : ' • TOU off'}
                  </span>`;
                ]]]
              slot: >
                [[[
                  const read = (i, type) => states[`sensor.ecco_clock_dongle_ecco_timezone${i}_${type}`]?.state ?? '--';
                  const toMin = (t) => {
                    const m = String(t).match(/^(\d{1,2}):(\d{2})$/);
                    return m ? Number(m[1]) * 60 + Number(m[2]) : null;
                  };
                  const now = new Date();
                  const cur = now.getHours()*60 + now.getMinutes();
                  const slots = [];

                  for (let i=1; i<=6; i++) {
                    const next = i === 6 ? 1 : i + 1;
                    const startText = read(i,'time');
                    const endText = read(next,'time');
                    const start = toMin(startText);
                    const end = toMin(endText);
                    if (start === null || end === null) continue;
                    const active = end > start ? (cur >= start && cur < end) : (cur >= start || cur < end);
                    slots.push({
                      i, active, startText, endText,
                      power: Number(read(i,'power')),
                      soc: Number(read(i,'soc')),
                      charge: read(i,'charge')
                    });
                  }

                  const s = slots.find(x => x.active) ?? slots[0];
                  if (!s) return 'TOU schedule unavailable';

                  const power = Number.isFinite(s.power) ? `${(s.power/1000).toFixed(1)} kW ceiling` : '';
                  const charging = s.charge !== 'None';
                  const line1 = charging ? `${s.charge} charge enabled` : 'No forced charge';
                  const line2 = charging && Number.isFinite(s.soc)
                    ? `${s.soc.toFixed(0)}% charge target${power ? ` • ${power}` : ''}`
                    : power;

                  return `<div>
                    <div style="font-size:26px;font-weight:800;color:#ffffff;">Slot ${s.i}</div>
                    <div style="font-size:14px;font-weight:700;color:#b8adff;margin-top:2px;">${s.startText}–${s.endText}</div>
                    <div style="font-size:12px;color:rgba(255,255,255,0.64);margin-top:7px;line-height:1.5;">
                      ${line1}<br>${line2}
                    </div>
                  </div>`;
                ]]]
              next: >
                [[[
                  const read = (i, type) => states[`sensor.ecco_clock_dongle_ecco_timezone${i}_${type}`]?.state ?? '--';
                  const toMin = (t) => {
                    const m = String(t).match(/^(\d{1,2}):(\d{2})$/);
                    return m ? Number(m[1])*60 + Number(m[2]) : null;
                  };
                  const now = new Date();
                  const cur = now.getHours()*60 + now.getMinutes();
                  let best = null;
                  for (let i=1; i<=6; i++) {
                    const t = read(i,'time');
                    const mins = toMin(t);
                    if (mins === null) continue;
                    let delta = mins-cur;
                    if (delta <= 0) delta += 1440;
                    if (!best || delta < best.delta) best = {i,t,delta};
                  }
                  if (!best) return '';
                  const h = Math.floor(best.delta/60), m = best.delta%60;
                  const left = h ? `${h}h ${m}m` : `${m}m`;
                  return `<div style="margin-top:10px;padding:9px 11px;border-radius:11px;
                    background:rgba(255,255,255,0.035);border:1px solid rgba(255,255,255,0.07);
                    font-size:12px;color:rgba(255,255,255,0.67);">
                    Next transition <b style="color:#fff;">${best.t}</b> • ${left}
                  </div>`;
                ]]]
              access: >
                [[[
                  return `<div style="display:flex;align-items:center;gap:7px;margin-top:9px;
                    color:#55e58e;font-size:11px;font-weight:700;">
                    <ha-icon icon="mdi:shield-check" style="width:16px;"></ha-icon>
                    Observe only • no setting writes
                  </div>`;
                ]]]
            styles:
              card:
                - border-radius: 20px
                - padding: 16px 18px
                - background: linear-gradient(145deg, rgba(20,28,45,0.98), rgba(10,15,27,0.98))
                - border: 1px solid rgba(255,255,255,0.08)
                - box-shadow: 0 12px 32px rgba(0,0,0,0.22)
              grid:
                - grid-template-areas: '"i n" "mode mode" "slot slot" "next next" "access access"'
                - grid-template-columns: 34px 1fr
                - grid-template-rows: min-content min-content 1fr min-content min-content
                - row-gap: 8px
              icon:
                - width: 24px
                - color: '#b8adff'
              name:
                - justify-self: start
                - align-self: center
                - font-size: 20px
                - font-weight: 700
                - color: rgba(255,255,255,0.92)
              custom_fields:
                mode:
                  - justify-self: start
                slot:
                  - justify-self: stretch
                next:
                  - justify-self: stretch
                access:
                  - justify-self: stretch
            grid_options:
              columns: 16
              rows: 5

          # ---- SOLAR FORECAST ----
          - type: custom:button-card
            section_mode: true
            name: Smart Charge Strategy
            icon: mdi:battery-charging-medium
            show_name: true
            show_icon: true
            show_state: false
            tap_action:
              action: none
            custom_fields:
              body: >
                [[[
                  const n=(id)=>Number(states[id]?.state??0);
                  const clamp=(v,a,b)=>Math.max(a,Math.min(b,v));
                  const sensors=Object.values(states).filter(s=>s.entity_id.startsWith('sensor.'));
                  const events=Object.values(states).filter(s=>s.entity_id.startsWith('event.'));
                  const friendly=(s)=>String(s?.attributes?.friendly_name??s?.entity_id??'').toLowerCase();
                  const find=(need,exclude=[])=>sensors.find(s=>{
                    const x=friendly(s);return need.every(v=>x.includes(v))&&!exclude.some(v=>x.includes(v));
                  });
                  const num=(s)=>{const v=Number(s?.state);return Number.isFinite(v)?v:null;};
                  const isExport=(s)=>s.entity_id.includes('export')||friendly(s).includes('export');

                  const soc=n('sensor.ecco_clock_dongle_ecco_battery_soc');
                  const capAh=n('sensor.ecco_clock_dongle_ecco_battery_capacity_ah')||620;
                  const capKwh=capAh*51.2/1000;
                  const loadToday=n('sensor.ecco_clock_dongle_ecco_day_load_energy');
                  const loadW=n('sensor.ecco_clock_dongle_ecco_load_power');
""")
DASHBOARD_11_NEW = _blk(r"""
              rows: 5
          - type: custom:button-card
            section_mode: true
            name: Current Plan
            icon: mdi:calendar-clock
            show_name: true
            show_icon: true
            show_state: false
            tap_action:
              action: none
            custom_fields:
              mode: >
                [[[
                  const em = states['sensor.ecco_clock_dongle_ecco_energy_management_model']?.state ?? 'Unknown';
                  const tou = states['binary_sensor.ecco_clock_dongle_ecco_time_of_use_enabled']?.state === 'on';
                  return `<span style="display:inline-block;padding:5px 10px;border-radius:999px;
                    background:rgba(143,124,255,0.12);border:1px solid rgba(143,124,255,0.28);
                    color:#b8adff;font-size:12px;font-weight:700;">
                    ${em}${tou ? ' • TOU active' : ' • TOU off'}
                  </span>`;
                ]]]
              slot: >
                [[[
                  const read = (i, type) => states[`sensor.ecco_clock_dongle_ecco_timezone${i}_${type}`]?.state ?? '--';
                  const toMin = (t) => {
                    const m = String(t).match(/^(\d{1,2}):(\d{2})$/);
                    return m ? Number(m[1]) * 60 + Number(m[2]) : null;
                  };
                  const now = new Date();
                  const cur = now.getHours()*60 + now.getMinutes();
                  const slots = [];

                  for (let i=1; i<=6; i++) {
                    const next = i === 6 ? 1 : i + 1;
                    const startText = read(i,'time');
                    const endText = read(next,'time');
                    const start = toMin(startText);
                    const end = toMin(endText);
                    if (start === null || end === null) continue;
                    const active = end > start ? (cur >= start && cur < end) : (cur >= start || cur < end);
                    slots.push({
                      i, active, startText, endText,
                      power: Number(read(i,'power')),
                      soc: Number(read(i,'soc')),
                      charge: read(i,'charge')
                    });
                  }

                  const s = slots.find(x => x.active) ?? slots[0];
                  if (!s) return 'TOU schedule unavailable';

                  const power = Number.isFinite(s.power) ? `${(s.power/1000).toFixed(1)} kW ceiling` : '';
                  const charging = s.charge !== 'None';
                  const line1 = charging ? `${s.charge} charge enabled` : 'No forced charge';
                  const line2 = charging && Number.isFinite(s.soc)
                    ? `${s.soc.toFixed(0)}% charge target${power ? ` • ${power}` : ''}`
                    : power;

                  return `<div>
                    <div style="font-size:26px;font-weight:800;color:#ffffff;">Slot ${s.i}</div>
                    <div style="font-size:14px;font-weight:700;color:#b8adff;margin-top:2px;">${s.startText}–${s.endText}</div>
                    <div style="font-size:12px;color:rgba(255,255,255,0.64);margin-top:7px;line-height:1.5;">
                      ${line1}<br>${line2}
                    </div>
                  </div>`;
                ]]]
              next: >
                [[[
                  const read = (i, type) => states[`sensor.ecco_clock_dongle_ecco_timezone${i}_${type}`]?.state ?? '--';
                  const toMin = (t) => {
                    const m = String(t).match(/^(\d{1,2}):(\d{2})$/);
                    return m ? Number(m[1])*60 + Number(m[2]) : null;
                  };
                  const now = new Date();
                  const cur = now.getHours()*60 + now.getMinutes();
                  let best = null;
                  for (let i=1; i<=6; i++) {
                    const t = read(i,'time');
                    const mins = toMin(t);
                    if (mins === null) continue;
                    let delta = mins-cur;
                    if (delta <= 0) delta += 1440;
                    if (!best || delta < best.delta) best = {i,t,delta};
                  }
                  if (!best) return '';
                  const h = Math.floor(best.delta/60), m = best.delta%60;
                  const left = h ? `${h}h ${m}m` : `${m}m`;
                  return `<div style="margin-top:10px;padding:9px 11px;border-radius:11px;
                    background:rgba(255,255,255,0.035);border:1px solid rgba(255,255,255,0.07);
                    font-size:12px;color:rgba(255,255,255,0.67);">
                    Next transition <b style="color:#fff;">${best.t}</b> • ${left}
                  </div>`;
                ]]]
              access: >
                [[[
                  return `<div style="display:flex;align-items:center;gap:7px;margin-top:9px;
                    color:#55e58e;font-size:11px;font-weight:700;">
                    <ha-icon icon="mdi:shield-check" style="width:16px;"></ha-icon>
                    Observe only • no setting writes
                  </div>`;
                ]]]
            styles:
              card:
                - border-radius: 20px
                - padding: 16px 18px
                - background: linear-gradient(145deg, rgba(20,28,45,0.98), rgba(10,15,27,0.98))
                - border: 1px solid rgba(255,255,255,0.08)
                - box-shadow: 0 12px 32px rgba(0,0,0,0.22)
              grid:
                - grid-template-areas: '"i n" "mode mode" "slot slot" "next next" "access access"'
                - grid-template-columns: 34px 1fr
                - grid-template-rows: min-content min-content 1fr min-content min-content
                - row-gap: 8px
              icon:
                - width: 24px
                - color: '#b8adff'
              name:
                - justify-self: start
                - align-self: center
                - font-size: 20px
                - font-weight: 700
                - color: rgba(255,255,255,0.92)
              custom_fields:
                mode:
                  - justify-self: start
                slot:
                  - justify-self: stretch
                next:
                  - justify-self: stretch
                access:
                  - justify-self: stretch
            grid_options:
              columns: 16
              rows: 5

          # ---- SOLAR FORECAST ----
          - type: custom:button-card
            section_mode: true
            name: Smart Charge Strategy
            icon: mdi:battery-charging-medium
            show_name: true
            show_icon: true
            show_state: false
            tap_action:
              action: none
            custom_fields:
              body: >
                [[[
                  const n=(id)=>Number(states[id]?.state??0);
                  const clamp=(v,a,b)=>Math.max(a,Math.min(b,v));
                  const sensors=Object.values(states).filter(s=>s.entity_id.startsWith('sensor.'));
                  const events=Object.values(states).filter(s=>s.entity_id.startsWith('event.'));
                  const friendly=(s)=>String(s?.attributes?.friendly_name??s?.entity_id??'').toLowerCase();
                  const find=(need,exclude=[])=>sensors.find(s=>{
                    const x=friendly(s);return need.every(v=>x.includes(v))&&!exclude.some(v=>x.includes(v));
                  });
                  const num=(s)=>{const v=Number(s?.state);return Number.isFinite(v)?v:null;};
                  const isExport=(s)=>s.entity_id.includes('export')||friendly(s).includes('export');

                  const soc=n('sensor.ecco_clock_dongle_ecco_battery_soc');
                  const capAh=n('sensor.ecco_clock_dongle_ecco_battery_capacity_ah')||620;
                  const capKwh=capAh*51.2/1000;
                  const loadToday=n('sensor.ecco_clock_dongle_ecco_day_load_energy');
                  const loadW=n('sensor.ecco_house_power');
""")
DASHBOARD_12_OLD = _blk(r"""
              rows: 4

          - type: custom:button-card
            section_mode: true
            name: Current Plan
            icon: mdi:calendar-clock
            show_name: true
            show_icon: true
            show_state: false
            tap_action:
              action: none
            custom_fields:
              mode: >
                [[[
                  const em = states['sensor.ecco_clock_dongle_ecco_energy_management_model']?.state ?? 'Unknown';
                  const tou = states['binary_sensor.ecco_clock_dongle_ecco_time_of_use_enabled']?.state === 'on';
                  return `<span style="display:inline-block;padding:5px 10px;border-radius:999px;
                    background:rgba(143,124,255,0.12);border:1px solid rgba(143,124,255,0.28);
                    color:#b8adff;font-size:12px;font-weight:700;">
                    ${em}${tou ? ' • TOU active' : ' • TOU off'}
                  </span>`;
                ]]]
              slot: >
                [[[
                  const read = (i, type) => states[`sensor.ecco_clock_dongle_ecco_timezone${i}_${type}`]?.state ?? '--';
                  const toMin = (t) => {
                    const m = String(t).match(/^(\d{1,2}):(\d{2})$/);
                    return m ? Number(m[1]) * 60 + Number(m[2]) : null;
                  };
                  const now = new Date();
                  const cur = now.getHours()*60 + now.getMinutes();
                  const slots = [];

                  for (let i=1; i<=6; i++) {
                    const next = i === 6 ? 1 : i + 1;
                    const startText = read(i,'time');
                    const endText = read(next,'time');
                    const start = toMin(startText);
                    const end = toMin(endText);
                    if (start === null || end === null) continue;
                    const active = end > start ? (cur >= start && cur < end) : (cur >= start || cur < end);
                    slots.push({
                      i, active, startText, endText,
                      power: Number(read(i,'power')),
                      soc: Number(read(i,'soc')),
                      charge: read(i,'charge')
                    });
                  }

                  const s = slots.find(x => x.active) ?? slots[0];
                  if (!s) return 'TOU schedule unavailable';

                  const power = Number.isFinite(s.power) ? `${(s.power/1000).toFixed(1)} kW ceiling` : '';
                  const charging = s.charge !== 'None';
                  const line1 = charging ? `${s.charge} charge enabled` : 'No forced charge';
                  const line2 = charging && Number.isFinite(s.soc)
                    ? `${s.soc.toFixed(0)}% charge target${power ? ` • ${power}` : ''}`
                    : power;

                  return `<div>
                    <div style="font-size:26px;font-weight:800;color:#ffffff;">Slot ${s.i}</div>
                    <div style="font-size:14px;font-weight:700;color:#b8adff;margin-top:2px;">${s.startText}–${s.endText}</div>
                    <div style="font-size:12px;color:rgba(255,255,255,0.64);margin-top:7px;line-height:1.5;">
                      ${line1}<br>${line2}
                    </div>
                  </div>`;
                ]]]
              next: >
                [[[
                  const read = (i, type) => states[`sensor.ecco_clock_dongle_ecco_timezone${i}_${type}`]?.state ?? '--';
                  const toMin = (t) => {
                    const m = String(t).match(/^(\d{1,2}):(\d{2})$/);
                    return m ? Number(m[1])*60 + Number(m[2]) : null;
                  };
                  const now = new Date();
                  const cur = now.getHours()*60 + now.getMinutes();
                  let best = null;
                  for (let i=1; i<=6; i++) {
                    const t = read(i,'time');
                    const mins = toMin(t);
                    if (mins === null) continue;
                    let delta = mins-cur;
                    if (delta <= 0) delta += 1440;
                    if (!best || delta < best.delta) best = {i,t,delta};
                  }
                  if (!best) return '';
                  const h = Math.floor(best.delta/60), m = best.delta%60;
                  const left = h ? `${h}h ${m}m` : `${m}m`;
                  return `<div style="margin-top:10px;padding:9px 11px;border-radius:11px;
                    background:rgba(255,255,255,0.035);border:1px solid rgba(255,255,255,0.07);
                    font-size:12px;color:rgba(255,255,255,0.67);">
                    Next transition <b style="color:#fff;">${best.t}</b> • ${left}
                  </div>`;
                ]]]
              access: >
                [[[
                  return `<div style="display:flex;align-items:center;gap:7px;margin-top:9px;
                    color:#55e58e;font-size:11px;font-weight:700;">
                    <ha-icon icon="mdi:shield-check" style="width:16px;"></ha-icon>
                    Observe only • no setting writes
                  </div>`;
                ]]]
            styles:
              card:
                - border-radius: 20px
                - padding: 16px 18px
                - background: linear-gradient(145deg, rgba(20,28,45,0.98), rgba(10,15,27,0.98))
                - border: 1px solid rgba(255,255,255,0.08)
                - box-shadow: 0 12px 32px rgba(0,0,0,0.22)
              grid:
                - grid-template-areas: '"i n" "mode mode" "slot slot" "next next" "access access"'
                - grid-template-columns: 34px 1fr
                - grid-template-rows: min-content min-content 1fr min-content min-content
                - row-gap: 8px
              icon:
                - width: 24px
                - color: '#b8adff'
              name:
                - justify-self: start
                - align-self: center
                - font-size: 20px
                - font-weight: 700
                - color: rgba(255,255,255,0.92)
              custom_fields:
                mode:
                  - justify-self: start
                slot:
                  - justify-self: stretch
                next:
                  - justify-self: stretch
                access:
                  - justify-self: stretch
            grid_options:
              columns: 16
              rows: 5

          # ---- SOLAR FORECAST ----
          - type: custom:button-card
            section_mode: true
            name: Smart Charge Strategy
            icon: mdi:battery-charging-medium
            show_name: true
            show_icon: true
            show_state: false
            tap_action:
              action: none
            custom_fields:
              body: >
                [[[
                  const n=(id)=>Number(states[id]?.state??0);
                  const clamp=(v,a,b)=>Math.max(a,Math.min(b,v));
                  const sensors=Object.values(states).filter(s=>s.entity_id.startsWith('sensor.'));
                  const events=Object.values(states).filter(s=>s.entity_id.startsWith('event.'));
                  const friendly=(s)=>String(s?.attributes?.friendly_name??s?.entity_id??'').toLowerCase();
                  const find=(need,exclude=[])=>sensors.find(s=>{
                    const x=friendly(s);return need.every(v=>x.includes(v))&&!exclude.some(v=>x.includes(v));
                  });
                  const num=(s)=>{const v=Number(s?.state);return Number.isFinite(v)?v:null;};
                  const isExport=(s)=>s.entity_id.includes('export')||friendly(s).includes('export');

                  const soc=n('sensor.ecco_clock_dongle_ecco_battery_soc');
                  const capAh=n('sensor.ecco_clock_dongle_ecco_battery_capacity_ah')||620;
                  const capKwh=capAh*51.2/1000;
                  const loadToday=n('sensor.ecco_clock_dongle_ecco_day_load_energy');
                  const loadW=n('sensor.ecco_clock_dongle_ecco_load_power');
""")
DASHBOARD_12_NEW = _blk(r"""
              rows: 4

          - type: custom:button-card
            section_mode: true
            name: Current Plan
            icon: mdi:calendar-clock
            show_name: true
            show_icon: true
            show_state: false
            tap_action:
              action: none
            custom_fields:
              mode: >
                [[[
                  const em = states['sensor.ecco_clock_dongle_ecco_energy_management_model']?.state ?? 'Unknown';
                  const tou = states['binary_sensor.ecco_clock_dongle_ecco_time_of_use_enabled']?.state === 'on';
                  return `<span style="display:inline-block;padding:5px 10px;border-radius:999px;
                    background:rgba(143,124,255,0.12);border:1px solid rgba(143,124,255,0.28);
                    color:#b8adff;font-size:12px;font-weight:700;">
                    ${em}${tou ? ' • TOU active' : ' • TOU off'}
                  </span>`;
                ]]]
              slot: >
                [[[
                  const read = (i, type) => states[`sensor.ecco_clock_dongle_ecco_timezone${i}_${type}`]?.state ?? '--';
                  const toMin = (t) => {
                    const m = String(t).match(/^(\d{1,2}):(\d{2})$/);
                    return m ? Number(m[1]) * 60 + Number(m[2]) : null;
                  };
                  const now = new Date();
                  const cur = now.getHours()*60 + now.getMinutes();
                  const slots = [];

                  for (let i=1; i<=6; i++) {
                    const next = i === 6 ? 1 : i + 1;
                    const startText = read(i,'time');
                    const endText = read(next,'time');
                    const start = toMin(startText);
                    const end = toMin(endText);
                    if (start === null || end === null) continue;
                    const active = end > start ? (cur >= start && cur < end) : (cur >= start || cur < end);
                    slots.push({
                      i, active, startText, endText,
                      power: Number(read(i,'power')),
                      soc: Number(read(i,'soc')),
                      charge: read(i,'charge')
                    });
                  }

                  const s = slots.find(x => x.active) ?? slots[0];
                  if (!s) return 'TOU schedule unavailable';

                  const power = Number.isFinite(s.power) ? `${(s.power/1000).toFixed(1)} kW ceiling` : '';
                  const charging = s.charge !== 'None';
                  const line1 = charging ? `${s.charge} charge enabled` : 'No forced charge';
                  const line2 = charging && Number.isFinite(s.soc)
                    ? `${s.soc.toFixed(0)}% charge target${power ? ` • ${power}` : ''}`
                    : power;

                  return `<div>
                    <div style="font-size:26px;font-weight:800;color:#ffffff;">Slot ${s.i}</div>
                    <div style="font-size:14px;font-weight:700;color:#b8adff;margin-top:2px;">${s.startText}–${s.endText}</div>
                    <div style="font-size:12px;color:rgba(255,255,255,0.64);margin-top:7px;line-height:1.5;">
                      ${line1}<br>${line2}
                    </div>
                  </div>`;
                ]]]
              next: >
                [[[
                  const read = (i, type) => states[`sensor.ecco_clock_dongle_ecco_timezone${i}_${type}`]?.state ?? '--';
                  const toMin = (t) => {
                    const m = String(t).match(/^(\d{1,2}):(\d{2})$/);
                    return m ? Number(m[1])*60 + Number(m[2]) : null;
                  };
                  const now = new Date();
                  const cur = now.getHours()*60 + now.getMinutes();
                  let best = null;
                  for (let i=1; i<=6; i++) {
                    const t = read(i,'time');
                    const mins = toMin(t);
                    if (mins === null) continue;
                    let delta = mins-cur;
                    if (delta <= 0) delta += 1440;
                    if (!best || delta < best.delta) best = {i,t,delta};
                  }
                  if (!best) return '';
                  const h = Math.floor(best.delta/60), m = best.delta%60;
                  const left = h ? `${h}h ${m}m` : `${m}m`;
                  return `<div style="margin-top:10px;padding:9px 11px;border-radius:11px;
                    background:rgba(255,255,255,0.035);border:1px solid rgba(255,255,255,0.07);
                    font-size:12px;color:rgba(255,255,255,0.67);">
                    Next transition <b style="color:#fff;">${best.t}</b> • ${left}
                  </div>`;
                ]]]
              access: >
                [[[
                  return `<div style="display:flex;align-items:center;gap:7px;margin-top:9px;
                    color:#55e58e;font-size:11px;font-weight:700;">
                    <ha-icon icon="mdi:shield-check" style="width:16px;"></ha-icon>
                    Observe only • no setting writes
                  </div>`;
                ]]]
            styles:
              card:
                - border-radius: 20px
                - padding: 16px 18px
                - background: linear-gradient(145deg, rgba(20,28,45,0.98), rgba(10,15,27,0.98))
                - border: 1px solid rgba(255,255,255,0.08)
                - box-shadow: 0 12px 32px rgba(0,0,0,0.22)
              grid:
                - grid-template-areas: '"i n" "mode mode" "slot slot" "next next" "access access"'
                - grid-template-columns: 34px 1fr
                - grid-template-rows: min-content min-content 1fr min-content min-content
                - row-gap: 8px
              icon:
                - width: 24px
                - color: '#b8adff'
              name:
                - justify-self: start
                - align-self: center
                - font-size: 20px
                - font-weight: 700
                - color: rgba(255,255,255,0.92)
              custom_fields:
                mode:
                  - justify-self: start
                slot:
                  - justify-self: stretch
                next:
                  - justify-self: stretch
                access:
                  - justify-self: stretch
            grid_options:
              columns: 16
              rows: 5

          # ---- SOLAR FORECAST ----
          - type: custom:button-card
            section_mode: true
            name: Smart Charge Strategy
            icon: mdi:battery-charging-medium
            show_name: true
            show_icon: true
            show_state: false
            tap_action:
              action: none
            custom_fields:
              body: >
                [[[
                  const n=(id)=>Number(states[id]?.state??0);
                  const clamp=(v,a,b)=>Math.max(a,Math.min(b,v));
                  const sensors=Object.values(states).filter(s=>s.entity_id.startsWith('sensor.'));
                  const events=Object.values(states).filter(s=>s.entity_id.startsWith('event.'));
                  const friendly=(s)=>String(s?.attributes?.friendly_name??s?.entity_id??'').toLowerCase();
                  const find=(need,exclude=[])=>sensors.find(s=>{
                    const x=friendly(s);return need.every(v=>x.includes(v))&&!exclude.some(v=>x.includes(v));
                  });
                  const num=(s)=>{const v=Number(s?.state);return Number.isFinite(v)?v:null;};
                  const isExport=(s)=>s.entity_id.includes('export')||friendly(s).includes('export');

                  const soc=n('sensor.ecco_clock_dongle_ecco_battery_soc');
                  const capAh=n('sensor.ecco_clock_dongle_ecco_battery_capacity_ah')||620;
                  const capKwh=capAh*51.2/1000;
                  const loadToday=n('sensor.ecco_clock_dongle_ecco_day_load_energy');
                  const loadW=n('sensor.ecco_house_power');
""")
DASHBOARD_13_OLD = _blk(r"""
              essential_power: sensor.ecco_clock_dongle_ecco_load_power
""")
DASHBOARD_13_NEW = _blk(r"""
              essential_power: sensor.ecco_house_power
""")
DASHBOARD_14_OLD = _blk(r"""
                }


          # ---- CHART DATA STATUS (V2.1): tells a quiet new day apart from a sensor that is not reporting ----
          # Shown only when it has something to say; display only.
          - type: custom:button-card
            section_mode: true
            show_name: false
            show_icon: false
            show_state: false
            tap_action:
              action: none
            variables:
              msg: >
                [[[
                  const ids = [['Solar', 'sensor.ecco_clock_dongle_ecco_pv_power'], ['House', 'sensor.ecco_clock_dongle_ecco_load_power'], ['Battery', 'sensor.ecco_clock_dongle_ecco_battery_output_power'], ['Grid', 'sensor.ecco_clock_dongle_ecco_grid_power_ct_clamp'], ['SOC', 'sensor.ecco_clock_dongle_ecco_battery_soc']];
""")
DASHBOARD_14_NEW = _blk(r"""
                }


          # ---- CHART DATA STATUS (V2.1): tells a quiet new day apart from a sensor that is not reporting ----
          # Shown only when it has something to say; display only.
          - type: custom:button-card
            section_mode: true
            show_name: false
            show_icon: false
            show_state: false
            tap_action:
              action: none
            variables:
              msg: >
                [[[
                  const ids = [['Solar', 'sensor.ecco_clock_dongle_ecco_pv_power'], ['House', 'sensor.ecco_house_power'], ['Battery', 'sensor.ecco_clock_dongle_ecco_battery_output_power'], ['Grid', 'sensor.ecco_clock_dongle_ecco_grid_power_ct_clamp'], ['SOC', 'sensor.ecco_clock_dongle_ecco_battery_soc']];
""")
DASHBOARD_15_OLD = _blk(r"""
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
              - entity: sensor.ecco_clock_dongle_ecco_load_power
""")
DASHBOARD_15_NEW = _blk(r"""
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
""")
DASHBOARD_EDITS = (
    (DASHBOARD_0_OLD, DASHBOARD_0_NEW),
    (DASHBOARD_1_OLD, DASHBOARD_1_NEW),
    (DASHBOARD_2_OLD, DASHBOARD_2_NEW),
    (DASHBOARD_3_OLD, DASHBOARD_3_NEW),
    (DASHBOARD_4_OLD, DASHBOARD_4_NEW),
    (DASHBOARD_5_OLD, DASHBOARD_5_NEW),
    (DASHBOARD_6_OLD, DASHBOARD_6_NEW),
    (DASHBOARD_7_OLD, DASHBOARD_7_NEW),
    (DASHBOARD_8_OLD, DASHBOARD_8_NEW),
    (DASHBOARD_9_OLD, DASHBOARD_9_NEW),
    (DASHBOARD_10_OLD, DASHBOARD_10_NEW),
    (DASHBOARD_11_OLD, DASHBOARD_11_NEW),
    (DASHBOARD_12_OLD, DASHBOARD_12_NEW),
    (DASHBOARD_13_OLD, DASHBOARD_13_NEW),
    (DASHBOARD_14_OLD, DASHBOARD_14_NEW),
    (DASHBOARD_15_OLD, DASHBOARD_15_NEW),
)


def pre_hd1_dashboard(text: str) -> str:
    """home-assistant/dashboards/ecco_pro.yaml with exactly hd1's edits undone (a frozen reverter of chain entry hd1, PEX)."""
    return _revert(text, DASHBOARD_EDITS, "home-assistant/dashboards/ecco_pro.yaml")


pre_hd1_dashboard.edits = DASHBOARD_EDITS   # the PEX contract: a reverter exposes its exact (before, after) pairs


def add_hd1_dashboard(text: str) -> str:
    """Applies hd1's home-assistant/dashboards/ecco_pro.yaml edits to the earlier text (the round trip)."""
    return _apply(text, DASHBOARD_EDITS, "home-assistant/dashboards/ecco_pro.yaml")


# ---- (PEX frozen edit) influxdb/tasks/ecco_battery_outlook_5m.flux ------------------------------------------------------
OUTLOOK_REL = "influxdb/tasks/ecco_battery_outlook_5m.flux"
OUTLOOK_0_OLD = _blk(r"""
loadHistory =
  readEccoTelemetryHistory(
    bucket: "ecco_5m",
    canonicalMeasurement: "sensor.ecco_house_power",
    legacyMeasurement: "sensor.ecco_clock_dongle_ecco_load_power",
    field: "value",
    rangeStart: -30d,
  )
""")
OUTLOOK_0_NEW = _blk(r"""
//
// hd1: a 5-minute house-load sample of 0 W or less is not consumption. Before hd1 the inverter's native load read 0 W
// whenever the system exported, and up to 30 days of such samples are still in the history (canonical and legacy alike).
// They are left untouched in the bucket - no history is rewritten - and only excluded here. Since hd1 the canonical
// sensor reports the derived house load during export and is unavailable (no sample), never 0 W, when it is not fresh.
loadHistory =
  readEccoTelemetryHistory(
    bucket: "ecco_5m",
    canonicalMeasurement: "sensor.ecco_house_power",
    legacyMeasurement: "sensor.ecco_clock_dongle_ecco_load_power",
    field: "value",
    rangeStart: -30d,
  )
    |> filter(fn: (r) => r._value > 0.0)
""")
OUTLOOK_EDITS = (
    (OUTLOOK_0_OLD, OUTLOOK_0_NEW),
)


def pre_hd1_outlook(text: str) -> str:
    """influxdb/tasks/ecco_battery_outlook_5m.flux with exactly hd1's edits undone (a frozen reverter of chain entry hd1, PEX)."""
    return _revert(text, OUTLOOK_EDITS, "influxdb/tasks/ecco_battery_outlook_5m.flux")


pre_hd1_outlook.edits = OUTLOOK_EDITS   # the PEX contract: a reverter exposes its exact (before, after) pairs


def add_hd1_outlook(text: str) -> str:
    """Applies hd1's influxdb/tasks/ecco_battery_outlook_5m.flux edits to the earlier text (the round trip)."""
    return _apply(text, OUTLOOK_EDITS, "influxdb/tasks/ecco_battery_outlook_5m.flux")


# ---- (PEX frozen edit) registry/system_health_checks.yaml ---------------------------------------------------------------
HEALTH_REL = "registry/system_health_checks.yaml"
HEALTH_0_OLD = _blk(r"""
    sensors (ecco_battery_soc, ecco_house_power, ecco_pv_power, ecco_grid_power), each structurally identical.
    Canonical state is a direct float/round of the raw value with no unit conversion, so this should be
    exactly 0 normally.
""")
HEALTH_0_NEW = _blk(r"""
    sensors (ecco_battery_soc, ecco_house_power, ecco_pv_power, ecco_grid_power), each structurally identical.
    Canonical state is a direct float/round of the raw value with no unit conversion, so this should be
    exactly 0 normally. Exception since hd1 - ecco_house_power is derived (the native load, or inverter +
    grid CT while the native load is unavailable or falsely 0 W during export), so for it the raw comparison
    is its model's source attribute, not register 178 alone (docs/HOUSE_LOAD_HD1.md).
""")
HEALTH_EDITS = (
    (HEALTH_0_OLD, HEALTH_0_NEW),
)


def pre_hd1_health(text: str) -> str:
    """registry/system_health_checks.yaml with exactly hd1's edits undone (a frozen reverter of chain entry hd1, PEX)."""
    return _revert(text, HEALTH_EDITS, "registry/system_health_checks.yaml")


pre_hd1_health.edits = HEALTH_EDITS   # the PEX contract: a reverter exposes its exact (before, after) pairs


def add_hd1_health(text: str) -> str:
    """Applies hd1's registry/system_health_checks.yaml edits to the earlier text (the round trip)."""
    return _apply(text, HEALTH_EDITS, "registry/system_health_checks.yaml")


# Every frozen file hd1 edits, with its reverter (the chain entry's frozen_reverts).
FROZEN_REVERTERS = {
    CANONICAL_REL: pre_hd1_canonical,
    CORE_REL: pre_hd1_core,
    DASHBOARD_REL: pre_hd1_dashboard,
    OUTLOOK_REL: pre_hd1_outlook,
    HEALTH_REL: pre_hd1_health,
}
# hd1 edits no chain-pinned artifact (no manifest stanza: the canonical package is already deployed).
PINNED_REVERTERS: dict = {}
