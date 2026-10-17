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
  # Consistency: the value is recomputed only when a complete poll has landed (a new poll text, seen on its OWN trigger -
  # a reading's write never counts as a poll, even with no memory), at start, or - with no per-poll text - on the 10 s tick
  # and on the online flag (the dongle writes all three readings before it), never on a single reading's write.
  # Credible native: a finite reading 0..30000 W. A negative native is not credible (as in the firmware): inverter + grid.
  # The model's state is constant (no logbook entries). With the per-poll text its memory changes only on a new poll, a new
  # value or a freshness change, so an idle tick writes nothing; without it, each tick recomputes and writes.
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
        state: "model"
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
            {%- set new_poll = poll_valid and tid != 'input' and poll_text != pm.get('poll_text') -%}
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
            {%- set recompute = new_poll or tid == 'start' or (not poll_valid and tid in ['tick', 'liveness'])
                               or (pm.get('computed_at') is not number and tid != 'input') -%}
            {%- set r = namespace(v=pm.get('value_w'), src=pm.get('source', 'none'), why=pm.get('reason', ''),
                                  n=pm.get('native_w'), i=pm.get('inverter_w'), g=pm.get('grid_w'), d=pm.get('derived_w'),
                                  at=pm.get('computed_at'), at_iso=pm.get('computed_iso')) -%}
            {%- if recompute -%}
              {%- set n = states(e_native) | float(none) -%}
              {%- set n_ok = n is number and n == n and n >= 0 and n <= 30000 -%}
              {%- set i = states(e_inv) | float(none) -%}
              {%- set g = states(e_grid) | float(none) -%}
              {%- set d_ok = i is number and i == i and (i | abs) <= 30000 and g is number and g == g and (g | abs) <= 30000 -%}
              {%- set d = ([0, i + g] | max) if d_ok else none -%}
              {%- set r.n = (n | round(1)) if n_ok else none -%}
              {%- set r.i = (i | round(1)) if d_ok else none -%}
              {%- set r.g = (g | round(1)) if d_ok else none -%}
              {%- set r.d = (d | round(1)) if d_ok else none -%}
              {%- set r.at = now_ts -%}
              {%- set r.at_iso = now().isoformat() -%}
              {%- if not n_ok and d_ok -%}
                {%- set r.v = d | round(1) -%}{%- set r.src = 'derived' -%}{%- set r.why = 'native load unavailable or not credible' -%}
              {%- elif not n_ok -%}
                {%- set r.v = none -%}{%- set r.src = 'none' -%}{%- set r.why = 'no usable load, inverter or grid reading' -%}
              {%- elif n == 0 and d_ok and d > 150 -%}
                {%- set r.v = d | round(1) -%}{%- set r.src = 'derived' -%}{%- set r.why = 'native load reads 0 W while inverter + grid shows consumption' -%}
              {%- elif n == 0 and d_ok -%}
                {%- set r.v = 0.0 -%}{%- set r.src = 'native' -%}{%- set r.why = 'native 0 W confirmed by inverter + grid' -%}
              {%- elif n == 0 -%}
                {%- set r.v = none -%}{%- set r.src = 'none' -%}{%- set r.why = 'native 0 W cannot be confirmed (inverter or grid reading unavailable)' -%}
              {%- else -%}
                {%- set r.v = n | round(1) -%}{%- set r.src = 'native' -%}{%- set r.why = '' -%}
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
                  'seen_at': (seen.ts | max) if seen.ts | count > 0 else none,
                  'poll_text': poll_text if (poll_valid and tid != 'input') else pm.get('poll_text'),
                  'poll_seen_at': poll_seen_at,
                  'computed_at': r.at,
                  'computed_iso': r.at_iso
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
          {{ m is mapping and m.get('fresh') is sameas true and m.get('value_w') is number and m.get('seen_at') is number
             and (as_timestamp(now()) - m.get('seen_at')) <= 70 }}
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
            {{ ((as_timestamp(now()) - m.get('seen_at')) | round(1)) if m is mapping and m.get('seen_at') is number else none }}
          refreshed_at: >-
            {%- set m = state_attr('sensor.ecco_house_power_model', 'model') -%}
            {{ m.get('computed_iso') if m is mapping else none }}
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
DASHBOARD_16_OLD = _blk(r"""
                  const liveKw = load / 1000;
                  const blendedKw = clamp(avgSoFar * 0.65 + liveKw * 0.35, 0.15, 5);

                  const targetTimeRaw = states['sensor.ecco_config_charge_start_time']?.state;
                  const targetMatch = String(targetTimeRaw ?? '').match(/^(\d{1,2}):(\d{2})$/);
                  const targetHour = targetMatch ? Number(targetMatch[1]) : 0;
                  const targetMinute = targetMatch ? Number(targetMatch[2]) : 30;
                  const targetTime = `${String(targetHour).padStart(2,'0')}:${String(targetMinute).padStart(2,'0')}`;
                  const nextCheapStart = new Date(now);
                  nextCheapStart.setHours(targetHour,targetMinute,0,0);
                  if (nextCheapStart <= now) nextCheapStart.setDate(nextCheapStart.getDate()+1);
                  const hoursToCheap = Math.max((nextCheapStart-now)/3600000, 0);
                  const loadToCheap = blendedKw * hoursToCheap;
                  // V2.1 (ovw2): the solar forecast is for the rest of the CURRENT calendar day. Only the part that can still arrive BEFORE
                  // the target time may lift the SOC AT the target. The credit is therefore the share of today's remaining daylight that ends
                  // before the target: 0 before sunrise or once today's daylight is over, 1 when the target is after sunset, and an approximate
                  // time-proportional share when the target falls inside the daylight window. Without sun times no projection is made.
                  const sunEntity = states['sun.sun'];
                  const solarWindow = (() => {
                    const set = sunEntity?.attributes?.next_setting ? new Date(sunEntity.attributes.next_setting) : null;
                    const rise = sunEntity?.attributes?.next_rising ? new Date(sunEntity.attributes.next_rising) : null;
                    if (!set || Number.isNaN(set.getTime())) return { known: false, share: null, partial: false };
                    let from = null;
                    if (sunEntity.state === 'above_horizon') from = now;
                    else if (rise && !Number.isNaN(rise.getTime()) && rise.toDateString() === now.toDateString()) from = rise;
                    if (from === null) return { known: true, share: 0, partial: false };
                    if (nextCheapStart >= set) return { known: true, share: 1, partial: false };
                    if (nextCheapStart <= from) return { known: true, share: 0, partial: false };
                    return { known: true, share: (nextCheapStart - from) / (set - from), partial: true };
                  })();
                  const solarShare = solarWindow.share;
                  if (solarWindow.partial) confidence = 'Low';
                  const minsToTarget = Math.round(hoursToCheap * 60);
                  const untilText = minsToTarget < 90 ? `in ${minsToTarget} min` : `in ${Math.round(hoursToCheap)} h`;
                  const targetLabel = `${targetTime} ${nextCheapStart.toDateString() === now.toDateString() ? 'today' : 'tomorrow'} (${untilText})`;

                  const likelySoc = correctedSolar !== null && solarShare !== null
                    ? clamp(soc + ((correctedSolar*solarShare-loadToCheap)/capKwh)*100, 0, 100)
                    : null;
                  const conservativeSoc = conservativeSolar !== null && solarShare !== null
                    ? clamp(soc + ((conservativeSolar*solarShare-loadToCheap)/capKwh)*100, 0, 100)
                    : null;

                  const currentRateSensors = sensors.filter(s =>
                    s.entity_id.includes('octopus_energy_electricity') &&
                    s.entity_id.includes('current_rate')
                  );
                  const imp = currentRateSensors.find(s => !isExport(s));
                  const exp = currentRateSensors.find(s => isExport(s));
                  const importP = num(imp) !== null ? num(imp)*100 : null;
                  const exportP = num(exp) !== null ? num(exp)*100 : null;

                  // Use ALL of today's rates for cheap/peak reference, not just rates still ahead.
                  const todayEvents = events.filter(s =>
                    s.entity_id.includes('octopus_energy_electricity') &&
                    s.entity_id.includes('current_day_rates') &&
                    !isExport(s)
                  );
                  let dayRates = [];
                  todayEvents.forEach(e => {
                    if (Array.isArray(e.attributes?.rates)) dayRates.push(...e.attributes.rates);
                  });
                  dayRates = dayRates.map(r => Number(r.value_inc_vat)*100).filter(Number.isFinite);

                  const dayCheapP = dayRates.length
                    ? Math.min(...dayRates)
                    : (imp?.attributes?.current_day_min_rate != null ? Number(imp.attributes.current_day_min_rate)*100 : null);
                  const dayPeakP = dayRates.length
                    ? Math.max(...dayRates)
                    : (imp?.attributes?.current_day_max_rate != null ? Number(imp.attributes.current_day_max_rate)*100 : importP);

                  const spread = importP !== null && exportP !== null ? importP-exportP : null;

                  let headline = 'Live monitoring';
                  let detail = `SOC ${soc.toFixed(0)}% • adaptive solar factor ${(factor*100).toFixed(0)}% • ${confidence.toLowerCase()} confidence`;
                  let colour = '#7ab8ff';

                  if (likelySoc !== null && conservativeSoc !== null) {
                    if (conservativeSoc >= 25) {
                      headline = `No additional grid charge indicated • ${confidence.toLowerCase()} confidence`;
                      detail = `Likely SOC at ${targetLabel} is ${likelySoc.toFixed(0)}% and conservative SOC is ${conservativeSoc.toFixed(0)}%.`;
                      colour = '#55e58e';
                    } else if (likelySoc >= 20) {
                      headline = `Keep watch on reserve • ${confidence.toLowerCase()} confidence`;
                      detail = `Likely SOC at ${targetLabel} is ${likelySoc.toFixed(0)}%, but conservative modelling falls to ${conservativeSoc.toFixed(0)}%.`;
                      colour = '#ffbd3d';
                    } else {
                      headline = `Cheap-rate support may be worthwhile • ${confidence.toLowerCase()} confidence`;
                      detail = `Likely SOC at ${targetLabel} is only ${likelySoc.toFixed(0)}% with ${conservativeSoc.toFixed(0)}% on the conservative model.`;
                      colour = '#ff6376';
                    }
                  }

                  if (likelySoc !== null && conservativeSoc !== null) {
                    if (solarShare === 0 && Number.isFinite(remaining) && remaining > 0.05) {
                      detail += ' No solar can arrive before then.';
                    } else if (solarWindow.partial) {
                      detail += ` About ${Math.round(solarShare * 100)}% of the remaining solar arrives before then (approximate).`;
                    }
                  } else if (!solarWindow.known) {
                    headline = 'Projection unavailable';
                    detail = `Sun times are unavailable, so ECCO cannot tell how much of the solar forecast arrives before ${targetLabel}. SOC is ${soc.toFixed(0)}%.`;
                    colour = '#aab4c3';
                  }

                  // V2.1: say which average house load the projection assumes (the model is unchanged: 65% of today's average load plus
                  // 35% of the load right now), so a short spike of load right now is visible as the reason for a low figure.
                  if (likelySoc !== null && conservativeSoc !== null) {
                    detail += ` Assumes about ${blendedKw.toFixed(1)} kW average house load until then (65% today's average, 35% the load right now).`;
                  }
                  if (liveRatio !== null) {
                    detail += ` Live PV is ${Math.round(liveRatio*100)}% of Forecast.Solar right now.`;
                  }

                  // V2.1: the tariff range and the import/export spread are shown by the Tariff now card in the right-hand column;
""")
DASHBOARD_16_NEW = _blk(r"""
                  const liveKw = Number.isFinite(load) ? load / 1000 : avgSoFar;   // hd1: house load unavailable -> the average alone
                  const blendedKw = clamp(avgSoFar * 0.65 + liveKw * 0.35, 0.15, 5);

                  const targetTimeRaw = states['sensor.ecco_config_charge_start_time']?.state;
                  const targetMatch = String(targetTimeRaw ?? '').match(/^(\d{1,2}):(\d{2})$/);
                  const targetHour = targetMatch ? Number(targetMatch[1]) : 0;
                  const targetMinute = targetMatch ? Number(targetMatch[2]) : 30;
                  const targetTime = `${String(targetHour).padStart(2,'0')}:${String(targetMinute).padStart(2,'0')}`;
                  const nextCheapStart = new Date(now);
                  nextCheapStart.setHours(targetHour,targetMinute,0,0);
                  if (nextCheapStart <= now) nextCheapStart.setDate(nextCheapStart.getDate()+1);
                  const hoursToCheap = Math.max((nextCheapStart-now)/3600000, 0);
                  const loadToCheap = blendedKw * hoursToCheap;
                  // V2.1 (ovw2): the solar forecast is for the rest of the CURRENT calendar day. Only the part that can still arrive BEFORE
                  // the target time may lift the SOC AT the target. The credit is therefore the share of today's remaining daylight that ends
                  // before the target: 0 before sunrise or once today's daylight is over, 1 when the target is after sunset, and an approximate
                  // time-proportional share when the target falls inside the daylight window. Without sun times no projection is made.
                  const sunEntity = states['sun.sun'];
                  const solarWindow = (() => {
                    const set = sunEntity?.attributes?.next_setting ? new Date(sunEntity.attributes.next_setting) : null;
                    const rise = sunEntity?.attributes?.next_rising ? new Date(sunEntity.attributes.next_rising) : null;
                    if (!set || Number.isNaN(set.getTime())) return { known: false, share: null, partial: false };
                    let from = null;
                    if (sunEntity.state === 'above_horizon') from = now;
                    else if (rise && !Number.isNaN(rise.getTime()) && rise.toDateString() === now.toDateString()) from = rise;
                    if (from === null) return { known: true, share: 0, partial: false };
                    if (nextCheapStart >= set) return { known: true, share: 1, partial: false };
                    if (nextCheapStart <= from) return { known: true, share: 0, partial: false };
                    return { known: true, share: (nextCheapStart - from) / (set - from), partial: true };
                  })();
                  const solarShare = solarWindow.share;
                  if (solarWindow.partial) confidence = 'Low';
                  const minsToTarget = Math.round(hoursToCheap * 60);
                  const untilText = minsToTarget < 90 ? `in ${minsToTarget} min` : `in ${Math.round(hoursToCheap)} h`;
                  const targetLabel = `${targetTime} ${nextCheapStart.toDateString() === now.toDateString() ? 'today' : 'tomorrow'} (${untilText})`;

                  const likelySoc = correctedSolar !== null && solarShare !== null
                    ? clamp(soc + ((correctedSolar*solarShare-loadToCheap)/capKwh)*100, 0, 100)
                    : null;
                  const conservativeSoc = conservativeSolar !== null && solarShare !== null
                    ? clamp(soc + ((conservativeSolar*solarShare-loadToCheap)/capKwh)*100, 0, 100)
                    : null;

                  const currentRateSensors = sensors.filter(s =>
                    s.entity_id.includes('octopus_energy_electricity') &&
                    s.entity_id.includes('current_rate')
                  );
                  const imp = currentRateSensors.find(s => !isExport(s));
                  const exp = currentRateSensors.find(s => isExport(s));
                  const importP = num(imp) !== null ? num(imp)*100 : null;
                  const exportP = num(exp) !== null ? num(exp)*100 : null;

                  // Use ALL of today's rates for cheap/peak reference, not just rates still ahead.
                  const todayEvents = events.filter(s =>
                    s.entity_id.includes('octopus_energy_electricity') &&
                    s.entity_id.includes('current_day_rates') &&
                    !isExport(s)
                  );
                  let dayRates = [];
                  todayEvents.forEach(e => {
                    if (Array.isArray(e.attributes?.rates)) dayRates.push(...e.attributes.rates);
                  });
                  dayRates = dayRates.map(r => Number(r.value_inc_vat)*100).filter(Number.isFinite);

                  const dayCheapP = dayRates.length
                    ? Math.min(...dayRates)
                    : (imp?.attributes?.current_day_min_rate != null ? Number(imp.attributes.current_day_min_rate)*100 : null);
                  const dayPeakP = dayRates.length
                    ? Math.max(...dayRates)
                    : (imp?.attributes?.current_day_max_rate != null ? Number(imp.attributes.current_day_max_rate)*100 : importP);

                  const spread = importP !== null && exportP !== null ? importP-exportP : null;

                  let headline = 'Live monitoring';
                  let detail = `SOC ${soc.toFixed(0)}% • adaptive solar factor ${(factor*100).toFixed(0)}% • ${confidence.toLowerCase()} confidence`;
                  let colour = '#7ab8ff';

                  if (likelySoc !== null && conservativeSoc !== null) {
                    if (conservativeSoc >= 25) {
                      headline = `No additional grid charge indicated • ${confidence.toLowerCase()} confidence`;
                      detail = `Likely SOC at ${targetLabel} is ${likelySoc.toFixed(0)}% and conservative SOC is ${conservativeSoc.toFixed(0)}%.`;
                      colour = '#55e58e';
                    } else if (likelySoc >= 20) {
                      headline = `Keep watch on reserve • ${confidence.toLowerCase()} confidence`;
                      detail = `Likely SOC at ${targetLabel} is ${likelySoc.toFixed(0)}%, but conservative modelling falls to ${conservativeSoc.toFixed(0)}%.`;
                      colour = '#ffbd3d';
                    } else {
                      headline = `Cheap-rate support may be worthwhile • ${confidence.toLowerCase()} confidence`;
                      detail = `Likely SOC at ${targetLabel} is only ${likelySoc.toFixed(0)}% with ${conservativeSoc.toFixed(0)}% on the conservative model.`;
                      colour = '#ff6376';
                    }
                  }

                  if (likelySoc !== null && conservativeSoc !== null) {
                    if (solarShare === 0 && Number.isFinite(remaining) && remaining > 0.05) {
                      detail += ' No solar can arrive before then.';
                    } else if (solarWindow.partial) {
                      detail += ` About ${Math.round(solarShare * 100)}% of the remaining solar arrives before then (approximate).`;
                    }
                  } else if (!solarWindow.known) {
                    headline = 'Projection unavailable';
                    detail = `Sun times are unavailable, so ECCO cannot tell how much of the solar forecast arrives before ${targetLabel}. SOC is ${soc.toFixed(0)}%.`;
                    colour = '#aab4c3';
                  }

                  // V2.1: say which average house load the projection assumes (the model is unchanged: 65% of today's average load plus
                  // 35% of the load right now), so a short spike of load right now is visible as the reason for a low figure.
                  if (likelySoc !== null && conservativeSoc !== null) {
                    detail += ` Assumes about ${blendedKw.toFixed(1)} kW average house load until then (65% today's average, 35% the load right now).`;
                  }
                  if (liveRatio !== null) {
                    detail += ` Live PV is ${Math.round(liveRatio*100)}% of Forecast.Solar right now.`;
                  }

                  // V2.1: the tariff range and the import/export spread are shown by the Tariff now card in the right-hand column;
""")
DASHBOARD_17_OLD = _blk(r"""
                  const liveKw = load / 1000;
                  const blendedKw = clamp(avgSoFar * 0.65 + liveKw * 0.35, 0.15, 5);

                  const targetTimeRaw = states['sensor.ecco_config_charge_start_time']?.state;
                  const targetMatch = String(targetTimeRaw ?? '').match(/^(\d{1,2}):(\d{2})$/);
                  const targetHour = targetMatch ? Number(targetMatch[1]) : 0;
                  const targetMinute = targetMatch ? Number(targetMatch[2]) : 30;
                  const targetTime = `${String(targetHour).padStart(2,'0')}:${String(targetMinute).padStart(2,'0')}`;
                  const nextCheapStart = new Date(now);
                  nextCheapStart.setHours(targetHour,targetMinute,0,0);
                  if (nextCheapStart <= now) nextCheapStart.setDate(nextCheapStart.getDate()+1);
                  const hoursToCheap = Math.max((nextCheapStart-now)/3600000, 0);
                  const loadToCheap = blendedKw * hoursToCheap;
                  // V2.1 (ovw2): the solar forecast is for the rest of the CURRENT calendar day. Only the part that can still arrive BEFORE
                  // the target time may lift the SOC AT the target. The credit is therefore the share of today's remaining daylight that ends
                  // before the target: 0 before sunrise or once today's daylight is over, 1 when the target is after sunset, and an approximate
                  // time-proportional share when the target falls inside the daylight window. Without sun times no projection is made.
                  const sunEntity = states['sun.sun'];
                  const solarWindow = (() => {
                    const set = sunEntity?.attributes?.next_setting ? new Date(sunEntity.attributes.next_setting) : null;
                    const rise = sunEntity?.attributes?.next_rising ? new Date(sunEntity.attributes.next_rising) : null;
                    if (!set || Number.isNaN(set.getTime())) return { known: false, share: null, partial: false };
                    let from = null;
                    if (sunEntity.state === 'above_horizon') from = now;
                    else if (rise && !Number.isNaN(rise.getTime()) && rise.toDateString() === now.toDateString()) from = rise;
                    if (from === null) return { known: true, share: 0, partial: false };
                    if (nextCheapStart >= set) return { known: true, share: 1, partial: false };
                    if (nextCheapStart <= from) return { known: true, share: 0, partial: false };
                    return { known: true, share: (nextCheapStart - from) / (set - from), partial: true };
                  })();
                  const solarShare = solarWindow.share;
                  if (solarWindow.partial) confidence = 'Low';
                  const minsToTarget = Math.round(hoursToCheap * 60);
                  const untilText = minsToTarget < 90 ? `in ${minsToTarget} min` : `in ${Math.round(hoursToCheap)} h`;
                  const targetLabel = `${targetTime} ${nextCheapStart.toDateString() === now.toDateString() ? 'today' : 'tomorrow'} (${untilText})`;

                  const likelySoc = correctedSolar !== null && solarShare !== null
                    ? clamp(soc + ((correctedSolar*solarShare-loadToCheap)/capKwh)*100, 0, 100)
                    : null;
                  const conservativeSoc = conservativeSolar !== null && solarShare !== null
                    ? clamp(soc + ((conservativeSolar*solarShare-loadToCheap)/capKwh)*100, 0, 100)
                    : null;

                  const currentRateSensors = sensors.filter(s =>
                    s.entity_id.includes('octopus_energy_electricity') &&
                    s.entity_id.includes('current_rate')
                  );
                  const imp = currentRateSensors.find(s => !isExport(s));
                  const exp = currentRateSensors.find(s => isExport(s));
                  const importP = num(imp) !== null ? num(imp)*100 : null;
                  const exportP = num(exp) !== null ? num(exp)*100 : null;

                  // Use ALL of today's rates for cheap/peak reference, not just rates still ahead.
                  const todayEvents = events.filter(s =>
                    s.entity_id.includes('octopus_energy_electricity') &&
                    s.entity_id.includes('current_day_rates') &&
                    !isExport(s)
                  );
                  let dayRates = [];
                  todayEvents.forEach(e => {
                    if (Array.isArray(e.attributes?.rates)) dayRates.push(...e.attributes.rates);
                  });
                  dayRates = dayRates.map(r => Number(r.value_inc_vat)*100).filter(Number.isFinite);

                  const dayCheapP = dayRates.length
                    ? Math.min(...dayRates)
                    : (imp?.attributes?.current_day_min_rate != null ? Number(imp.attributes.current_day_min_rate)*100 : null);
                  const dayPeakP = dayRates.length
                    ? Math.max(...dayRates)
                    : (imp?.attributes?.current_day_max_rate != null ? Number(imp.attributes.current_day_max_rate)*100 : importP);

                  const spread = importP !== null && exportP !== null ? importP-exportP : null;

                  let headline = 'Live monitoring';
                  let detail = `SOC ${soc.toFixed(0)}% • adaptive solar factor ${(factor*100).toFixed(0)}% • ${confidence.toLowerCase()} confidence`;
                  let colour = '#7ab8ff';

                  if (likelySoc !== null && conservativeSoc !== null) {
                    if (conservativeSoc >= 25) {
                      headline = `No additional grid charge indicated • ${confidence.toLowerCase()} confidence`;
                      detail = `Likely SOC at ${targetLabel} is ${likelySoc.toFixed(0)}% and conservative SOC is ${conservativeSoc.toFixed(0)}%.`;
                      colour = '#55e58e';
                    } else if (likelySoc >= 20) {
                      headline = `Keep watch on reserve • ${confidence.toLowerCase()} confidence`;
                      detail = `Likely SOC at ${targetLabel} is ${likelySoc.toFixed(0)}%, but conservative modelling falls to ${conservativeSoc.toFixed(0)}%.`;
                      colour = '#ffbd3d';
                    } else {
                      headline = `Cheap-rate support may be worthwhile • ${confidence.toLowerCase()} confidence`;
                      detail = `Likely SOC at ${targetLabel} is only ${likelySoc.toFixed(0)}% with ${conservativeSoc.toFixed(0)}% on the conservative model.`;
                      colour = '#ff6376';
                    }
                  }

                  if (likelySoc !== null && conservativeSoc !== null) {
                    if (solarShare === 0 && Number.isFinite(remaining) && remaining > 0.05) {
                      detail += ' No solar can arrive before then.';
                    } else if (solarWindow.partial) {
                      detail += ` About ${Math.round(solarShare * 100)}% of the remaining solar arrives before then (approximate).`;
                    }
                  } else if (!solarWindow.known) {
                    headline = 'Projection unavailable';
                    detail = `Sun times are unavailable, so ECCO cannot tell how much of the solar forecast arrives before ${targetLabel}. SOC is ${soc.toFixed(0)}%.`;
                    colour = '#aab4c3';
                  }

                  // V2.1: say which average house load the projection assumes (the model is unchanged: 65% of today's average load plus
                  // 35% of the load right now), so a short spike of load right now is visible as the reason for a low figure.
                  if (likelySoc !== null && conservativeSoc !== null) {
                    detail += ` Assumes about ${blendedKw.toFixed(1)} kW average house load until then (65% today's average, 35% the load right now).`;
                  }
                  if (liveRatio !== null) {
                    detail += ` Live PV is ${Math.round(liveRatio*100)}% of Forecast.Solar right now.`;
                  }

                  if (dayCheapP !== null && dayPeakP !== null) {
""")
DASHBOARD_17_NEW = _blk(r"""
                  const liveKw = Number.isFinite(load) ? load / 1000 : avgSoFar;   // hd1: house load unavailable -> the average alone
                  const blendedKw = clamp(avgSoFar * 0.65 + liveKw * 0.35, 0.15, 5);

                  const targetTimeRaw = states['sensor.ecco_config_charge_start_time']?.state;
                  const targetMatch = String(targetTimeRaw ?? '').match(/^(\d{1,2}):(\d{2})$/);
                  const targetHour = targetMatch ? Number(targetMatch[1]) : 0;
                  const targetMinute = targetMatch ? Number(targetMatch[2]) : 30;
                  const targetTime = `${String(targetHour).padStart(2,'0')}:${String(targetMinute).padStart(2,'0')}`;
                  const nextCheapStart = new Date(now);
                  nextCheapStart.setHours(targetHour,targetMinute,0,0);
                  if (nextCheapStart <= now) nextCheapStart.setDate(nextCheapStart.getDate()+1);
                  const hoursToCheap = Math.max((nextCheapStart-now)/3600000, 0);
                  const loadToCheap = blendedKw * hoursToCheap;
                  // V2.1 (ovw2): the solar forecast is for the rest of the CURRENT calendar day. Only the part that can still arrive BEFORE
                  // the target time may lift the SOC AT the target. The credit is therefore the share of today's remaining daylight that ends
                  // before the target: 0 before sunrise or once today's daylight is over, 1 when the target is after sunset, and an approximate
                  // time-proportional share when the target falls inside the daylight window. Without sun times no projection is made.
                  const sunEntity = states['sun.sun'];
                  const solarWindow = (() => {
                    const set = sunEntity?.attributes?.next_setting ? new Date(sunEntity.attributes.next_setting) : null;
                    const rise = sunEntity?.attributes?.next_rising ? new Date(sunEntity.attributes.next_rising) : null;
                    if (!set || Number.isNaN(set.getTime())) return { known: false, share: null, partial: false };
                    let from = null;
                    if (sunEntity.state === 'above_horizon') from = now;
                    else if (rise && !Number.isNaN(rise.getTime()) && rise.toDateString() === now.toDateString()) from = rise;
                    if (from === null) return { known: true, share: 0, partial: false };
                    if (nextCheapStart >= set) return { known: true, share: 1, partial: false };
                    if (nextCheapStart <= from) return { known: true, share: 0, partial: false };
                    return { known: true, share: (nextCheapStart - from) / (set - from), partial: true };
                  })();
                  const solarShare = solarWindow.share;
                  if (solarWindow.partial) confidence = 'Low';
                  const minsToTarget = Math.round(hoursToCheap * 60);
                  const untilText = minsToTarget < 90 ? `in ${minsToTarget} min` : `in ${Math.round(hoursToCheap)} h`;
                  const targetLabel = `${targetTime} ${nextCheapStart.toDateString() === now.toDateString() ? 'today' : 'tomorrow'} (${untilText})`;

                  const likelySoc = correctedSolar !== null && solarShare !== null
                    ? clamp(soc + ((correctedSolar*solarShare-loadToCheap)/capKwh)*100, 0, 100)
                    : null;
                  const conservativeSoc = conservativeSolar !== null && solarShare !== null
                    ? clamp(soc + ((conservativeSolar*solarShare-loadToCheap)/capKwh)*100, 0, 100)
                    : null;

                  const currentRateSensors = sensors.filter(s =>
                    s.entity_id.includes('octopus_energy_electricity') &&
                    s.entity_id.includes('current_rate')
                  );
                  const imp = currentRateSensors.find(s => !isExport(s));
                  const exp = currentRateSensors.find(s => isExport(s));
                  const importP = num(imp) !== null ? num(imp)*100 : null;
                  const exportP = num(exp) !== null ? num(exp)*100 : null;

                  // Use ALL of today's rates for cheap/peak reference, not just rates still ahead.
                  const todayEvents = events.filter(s =>
                    s.entity_id.includes('octopus_energy_electricity') &&
                    s.entity_id.includes('current_day_rates') &&
                    !isExport(s)
                  );
                  let dayRates = [];
                  todayEvents.forEach(e => {
                    if (Array.isArray(e.attributes?.rates)) dayRates.push(...e.attributes.rates);
                  });
                  dayRates = dayRates.map(r => Number(r.value_inc_vat)*100).filter(Number.isFinite);

                  const dayCheapP = dayRates.length
                    ? Math.min(...dayRates)
                    : (imp?.attributes?.current_day_min_rate != null ? Number(imp.attributes.current_day_min_rate)*100 : null);
                  const dayPeakP = dayRates.length
                    ? Math.max(...dayRates)
                    : (imp?.attributes?.current_day_max_rate != null ? Number(imp.attributes.current_day_max_rate)*100 : importP);

                  const spread = importP !== null && exportP !== null ? importP-exportP : null;

                  let headline = 'Live monitoring';
                  let detail = `SOC ${soc.toFixed(0)}% • adaptive solar factor ${(factor*100).toFixed(0)}% • ${confidence.toLowerCase()} confidence`;
                  let colour = '#7ab8ff';

                  if (likelySoc !== null && conservativeSoc !== null) {
                    if (conservativeSoc >= 25) {
                      headline = `No additional grid charge indicated • ${confidence.toLowerCase()} confidence`;
                      detail = `Likely SOC at ${targetLabel} is ${likelySoc.toFixed(0)}% and conservative SOC is ${conservativeSoc.toFixed(0)}%.`;
                      colour = '#55e58e';
                    } else if (likelySoc >= 20) {
                      headline = `Keep watch on reserve • ${confidence.toLowerCase()} confidence`;
                      detail = `Likely SOC at ${targetLabel} is ${likelySoc.toFixed(0)}%, but conservative modelling falls to ${conservativeSoc.toFixed(0)}%.`;
                      colour = '#ffbd3d';
                    } else {
                      headline = `Cheap-rate support may be worthwhile • ${confidence.toLowerCase()} confidence`;
                      detail = `Likely SOC at ${targetLabel} is only ${likelySoc.toFixed(0)}% with ${conservativeSoc.toFixed(0)}% on the conservative model.`;
                      colour = '#ff6376';
                    }
                  }

                  if (likelySoc !== null && conservativeSoc !== null) {
                    if (solarShare === 0 && Number.isFinite(remaining) && remaining > 0.05) {
                      detail += ' No solar can arrive before then.';
                    } else if (solarWindow.partial) {
                      detail += ` About ${Math.round(solarShare * 100)}% of the remaining solar arrives before then (approximate).`;
                    }
                  } else if (!solarWindow.known) {
                    headline = 'Projection unavailable';
                    detail = `Sun times are unavailable, so ECCO cannot tell how much of the solar forecast arrives before ${targetLabel}. SOC is ${soc.toFixed(0)}%.`;
                    colour = '#aab4c3';
                  }

                  // V2.1: say which average house load the projection assumes (the model is unchanged: 65% of today's average load plus
                  // 35% of the load right now), so a short spike of load right now is visible as the reason for a low figure.
                  if (likelySoc !== null && conservativeSoc !== null) {
                    detail += ` Assumes about ${blendedKw.toFixed(1)} kW average house load until then (65% today's average, 35% the load right now).`;
                  }
                  if (liveRatio !== null) {
                    detail += ` Live PV is ${Math.round(liveRatio*100)}% of Forecast.Solar right now.`;
                  }

                  if (dayCheapP !== null && dayPeakP !== null) {
""")
DASHBOARD_18_OLD = _blk(r"""
                  const liveKw=loadW/1000;
                  const runKw=clamp(avgKw*.65+liveKw*.35,.15,5);
                  const loadRemaining=runKw*hoursLeft;
""")
DASHBOARD_18_NEW = _blk(r"""
                  const liveKw=Number.isFinite(loadW)?loadW/1000:avgKw;   // hd1: house load unavailable -> the average alone
                  const runKw=clamp(avgKw*.65+liveKw*.35,.15,5);
                  const loadRemaining=runKw*hoursLeft;
""")
DASHBOARD_19_OLD = _blk(r"""
                  const liveKw=loadW/1000;
                  const runKw=clamp(avgKw*.65+liveKw*.35,.15,5);
                  const projectedDaily=clamp(runKw*24,6,60);

                  const adjustedTomorrow=tomorrow!==null?tomorrow*factor*.95:null;
                  const morningBridge=runKw*4.5;
                  const reserveKwh=capKwh*.10;
                  const dailyDeficit=adjustedTomorrow!==null?Math.max(projectedDaily-adjustedTomorrow,0):0;
                  const requiredEnergy=clamp(morningBridge+reserveKwh+dailyDeficit,capKwh*.20,capKwh);
                  const minimumReserveTarget=clamp(requiredEnergy/capKwh*100,20,100);

                  const configuredTarget=Number(states['sensor.ecco_clock_dongle_ecco_timezone1_soc']?.state??100);

                  const rateSensors=sensors.filter(s=>
                    s.entity_id.includes('octopus_energy_electricity')&&
                    s.entity_id.includes('current_rate')
                  );
                  const imp=rateSensors.find(s=>!isExport(s));

                  const parseEvent=(needle)=>{
                    const ev=events.find(s=>
                      s.entity_id.includes('octopus_energy_electricity')&&
                      s.entity_id.includes(needle)&&!isExport(s)
                    );
                    const rs=Array.isArray(ev?.attributes?.rates)?ev.attributes.rates:[];
                    return rs.map(r=>({
                      start:new Date(r.start),end:new Date(r.end),
                      p:Number(r.value_inc_vat)*100
                    })).filter(r=>Number.isFinite(r.p)&&!isNaN(r.start)&&!isNaN(r.end))
                      .sort((a,b)=>a.start-b.start);
                  };

                  const todayRates=parseEvent('current_day_rates');
                  const nextRates=parseEvent('next_day_rates');
                  const nextRateCoverageHours=nextRates.reduce((sum,r)=>sum+Math.max((r.end-r.start)/3600000,0),0);
                  const nextRatesReady=nextRates.length>=6 && nextRateCoverageHours>=3;
                  const todayMin=todayRates.length?Math.min(...todayRates.map(r=>r.p)):
                    (imp?.attributes?.current_day_min_rate!=null?Number(imp.attributes.current_day_min_rate)*100:null);
                  const todayMax=todayRates.length?Math.max(...todayRates.map(r=>r.p)):
                    (imp?.attributes?.current_day_max_rate!=null?Number(imp.attributes.current_day_max_rate)*100:null);

                  const eps=.35;
                  const windowFor=(rates,target,after)=>{
                    if(!rates.length||target===null)return null;
                    const hits=rates.filter(r=>r.end>after&&Math.abs(r.p-target)<=eps);
                    if(!hits.length)return null;
                    const first=hits[0];
                    let end=first.end;
                    for(const r of hits.slice(1)){
                      if(Math.abs(r.start-end)<60000)end=r.end;else break;
                    }
                    return {start:first.start,end,p:target};
                  };

                  let nextCheap= todayMin!==null ? windowFor(todayRates,todayMin,now) : null;
                  if(!nextCheap&&nextRatesReady){
                    const nm=Math.min(...nextRates.map(r=>r.p));
                    nextCheap=windowFor(nextRates,nm,now);
                  }

                  // Battery level expected at the live configured charge-slot start.
                  const targetTimeRaw=states['sensor.ecco_config_charge_start_time']?.state;
                  const targetMatch=String(targetTimeRaw??'').match(/^(\d{1,2}):(\d{2})$/);
                  const targetHour=targetMatch?Number(targetMatch[1]):0;
                  const targetMinute=targetMatch?Number(targetMatch[2]):30;
                  const targetTime=`${String(targetHour).padStart(2,'0')}:${String(targetMinute).padStart(2,'0')}`;
                  const cheapStart=new Date(now);
                  cheapStart.setHours(targetHour,targetMinute,0,0);
                  if(cheapStart<=now)cheapStart.setDate(cheapStart.getDate()+1);
                  const hCheap=Math.max((cheapStart-now)/3600000,0);

                  // V2.1 (ovw2): never show a reserve projection or top-up advice from a battery reading that is not a number.
                  const socRaw=states['sensor.ecco_clock_dongle_ecco_battery_soc']?.state;
                  if(socRaw===undefined||['unknown','unavailable','none',''].includes(String(socRaw).toLowerCase())||!Number.isFinite(Number(socRaw))){
                    return `<div style="font-size:16px;font-weight:800;color:#aab4c3;">Battery data unavailable</div><div style="margin-top:6px;font-size:11px;line-height:1.5;color:rgba(255,255,255,.55);">No reserve projection or top-up advice is shown until the battery SOC reports again.</div>`;
                  }

                  // V2.1 (ovw2): the solar forecast is for the rest of the CURRENT calendar day; only the share that can arrive BEFORE the
                  // target may lift the SOC at the target (same rule as the ECCO Today card). Unknown sun times credit no solar at all.
                  const sunEntity=states['sun.sun'];
                  const solarShare=(()=>{
                    const set=sunEntity?.attributes?.next_setting?new Date(sunEntity.attributes.next_setting):null;
                    const rise=sunEntity?.attributes?.next_rising?new Date(sunEntity.attributes.next_rising):null;
                    if(!set||Number.isNaN(set.getTime()))return 0;
                    let from=null;
                    if(sunEntity.state==='above_horizon')from=now;
                    else if(rise&&!Number.isNaN(rise.getTime())&&rise.toDateString()===now.toDateString())from=rise;
                    if(from===null)return 0;
                    if(cheapStart>=set)return 1;
                    if(cheapStart<=from)return 0;
                    return (cheapStart-from)/(set-from);
                  })();
                  const targetDay=cheapStart.toDateString()===now.toDateString()?'today':'tomorrow';
                  const likelySolar=remaining!==null?remaining*factor*.95:0;
                  const predictedAt0035=remaining!==null
                    ? clamp(soc+((likelySolar*solarShare-runKw*hCheap)/capKwh)*100,0,100)
                    : soc;

                  // This is the extra energy needed for reserve/security only.
                  const batteryNeeded=Math.max(0,(minimumReserveTarget-predictedAt0035)/100*capKwh);
                  const gridNeeded=batteryNeeded/.94;

                  const nextCheapRate=nextCheap?.p ?? null;
                  const costRate=nextCheapRate ?? todayMin;
                  const costIsReference=nextCheapRate===null&&todayMin!==null;
                  const chargeCost=costRate!==null?gridNeeded*(costRate/100):null;
                  const avoidedValue=todayMax!==null?batteryNeeded*(todayMax/100):null;
                  const saving=chargeCost!==null&&avoidedValue!==null?avoidedValue-chargeCost:null;

                  const surplusPct=predictedAt0035-minimumReserveTarget;

                  let headline='Energy-reserve model says no top-up is needed';
                  let colour='#55e58e';
                  if(gridNeeded>0.2){
                    headline='Energy-reserve model recommends a cheap-rate top-up';
                    colour='#ffbd3d';
                  }else if(configuredTarget>minimumReserveTarget+15){
                    headline='Configured target is well above the modelled reserve need';
                    colour='#7ab8ff';
                  }

                  return `<div>
                    <div style="font-size:16px;font-weight:800;color:${colour};">${headline}</div>

                    <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:9px;margin-top:12px;">
                      <div style="text-align:center;padding:9px;border-radius:10px;background:rgba(255,255,255,.035);border:1px solid rgba(255,255,255,.06);">
                        <div style="font-size:10px;color:rgba(255,255,255,.48);">Configured TOU target</div>
                        <div style="font-size:22px;font-weight:800;color:#b8adff;">${Number.isFinite(configuredTarget)?configuredTarget.toFixed(0):'--'}%</div>
                      </div>
                      <div style="text-align:center;padding:9px;border-radius:10px;background:rgba(255,255,255,.035);border:1px solid rgba(255,255,255,.06);">
                        <div style="font-size:10px;color:rgba(255,255,255,.48);">Modelled reserve need</div>
                        <div style="font-size:22px;font-weight:800;color:#55e58e;">${minimumReserveTarget.toFixed(0)}%</div>
                      </div>
                      <div style="text-align:center;padding:9px;border-radius:10px;background:rgba(255,255,255,.035);border:1px solid rgba(255,255,255,.06);">
                        <div style="font-size:10px;color:rgba(255,255,255,.48);">Expected at ${targetTime} ${targetDay}</div>
                        <div style="font-size:22px;font-weight:800;color:#ffbd3d;">${predictedAt0035.toFixed(0)}%</div>
                      </div>
                    </div>

                    <div style="margin-top:11px;font-size:11px;line-height:1.55;color:rgba(255,255,255,.60);">
                      Reserve margin at ${targetTime} <b style="color:${surplusPct>=0?'#55e58e':'#ff6376'}">${surplusPct>=0?'+':''}${surplusPct.toFixed(0)} points</b>
                      • next-day load model <b style="color:#fff">${projectedDaily.toFixed(1)} kWh</b>
                      ${adjustedTomorrow!==null?` • adaptive solar <b style="color:#ffbd3d">${adjustedTomorrow.toFixed(1)} kWh</b>`:''}
                      • reserve-only charge need <b style="color:#fff">${gridNeeded.toFixed(1)} kWh</b>
                      ${chargeCost!==null?` • estimated cost <b style="color:#fff">£${chargeCost.toFixed(2)}</b>${costIsReference?' using today’s cheap rate as a reference':''}`:''}
                      ${saving!==null&&saving>0&&gridNeeded>0.1?` • avoided peak-import value <b style="color:#55e58e">£${saving.toFixed(2)}</b>`:''}.
                    </div>

                    <div style="margin-top:9px;font-size:10px;line-height:1.45;color:rgba(255,255,255,.42);">
                      The modelled reserve need is an energy-security estimate, not the ECCO reserve setting and not a proposed TOU setting.
                      ${nextCheap?` Next published cheap window: ${nextCheap.start.toLocaleTimeString([],{hour:'2-digit',minute:'2-digit'})}–${nextCheap.end.toLocaleTimeString([],{hour:'2-digit',minute:'2-digit'})} at ${nextCheap.p.toFixed(2)}p/kWh.`:' Next-day cheap rates are not published yet.'}
                      Export arbitrage and battery degradation are still excluded.
                    </div>
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
                - grid-template-areas: '"i n" "body body"'
                - grid-template-columns: 32px 1fr
                - grid-template-rows: min-content 1fr
                - row-gap: 12px
              icon:
                - width: 24px
                - color: '#55e58e'
              name:
                - justify-self: start
                - font-size: 20px
                - font-weight: 700
                - color: rgba(255,255,255,0.92)
              custom_fields:
                body:
                  - width: 100%
                  - white-space: normal
                  - overflow: visible
                  - text-overflow: unset
                  - word-break: normal
                  - line-height: 1.45
            grid_options:
              columns: 24
              rows: 6

          # ---- OCTOPUS RATE GRAPH ----
          - type: custom:button-card
""")
DASHBOARD_19_NEW = _blk(r"""
                  const liveKw=Number.isFinite(loadW)?loadW/1000:avgKw;   // hd1: house load unavailable -> the average alone
                  const runKw=clamp(avgKw*.65+liveKw*.35,.15,5);
                  const projectedDaily=clamp(runKw*24,6,60);

                  const adjustedTomorrow=tomorrow!==null?tomorrow*factor*.95:null;
                  const morningBridge=runKw*4.5;
                  const reserveKwh=capKwh*.10;
                  const dailyDeficit=adjustedTomorrow!==null?Math.max(projectedDaily-adjustedTomorrow,0):0;
                  const requiredEnergy=clamp(morningBridge+reserveKwh+dailyDeficit,capKwh*.20,capKwh);
                  const minimumReserveTarget=clamp(requiredEnergy/capKwh*100,20,100);

                  const configuredTarget=Number(states['sensor.ecco_clock_dongle_ecco_timezone1_soc']?.state??100);

                  const rateSensors=sensors.filter(s=>
                    s.entity_id.includes('octopus_energy_electricity')&&
                    s.entity_id.includes('current_rate')
                  );
                  const imp=rateSensors.find(s=>!isExport(s));

                  const parseEvent=(needle)=>{
                    const ev=events.find(s=>
                      s.entity_id.includes('octopus_energy_electricity')&&
                      s.entity_id.includes(needle)&&!isExport(s)
                    );
                    const rs=Array.isArray(ev?.attributes?.rates)?ev.attributes.rates:[];
                    return rs.map(r=>({
                      start:new Date(r.start),end:new Date(r.end),
                      p:Number(r.value_inc_vat)*100
                    })).filter(r=>Number.isFinite(r.p)&&!isNaN(r.start)&&!isNaN(r.end))
                      .sort((a,b)=>a.start-b.start);
                  };

                  const todayRates=parseEvent('current_day_rates');
                  const nextRates=parseEvent('next_day_rates');
                  const nextRateCoverageHours=nextRates.reduce((sum,r)=>sum+Math.max((r.end-r.start)/3600000,0),0);
                  const nextRatesReady=nextRates.length>=6 && nextRateCoverageHours>=3;
                  const todayMin=todayRates.length?Math.min(...todayRates.map(r=>r.p)):
                    (imp?.attributes?.current_day_min_rate!=null?Number(imp.attributes.current_day_min_rate)*100:null);
                  const todayMax=todayRates.length?Math.max(...todayRates.map(r=>r.p)):
                    (imp?.attributes?.current_day_max_rate!=null?Number(imp.attributes.current_day_max_rate)*100:null);

                  const eps=.35;
                  const windowFor=(rates,target,after)=>{
                    if(!rates.length||target===null)return null;
                    const hits=rates.filter(r=>r.end>after&&Math.abs(r.p-target)<=eps);
                    if(!hits.length)return null;
                    const first=hits[0];
                    let end=first.end;
                    for(const r of hits.slice(1)){
                      if(Math.abs(r.start-end)<60000)end=r.end;else break;
                    }
                    return {start:first.start,end,p:target};
                  };

                  let nextCheap= todayMin!==null ? windowFor(todayRates,todayMin,now) : null;
                  if(!nextCheap&&nextRatesReady){
                    const nm=Math.min(...nextRates.map(r=>r.p));
                    nextCheap=windowFor(nextRates,nm,now);
                  }

                  // Battery level expected at the live configured charge-slot start.
                  const targetTimeRaw=states['sensor.ecco_config_charge_start_time']?.state;
                  const targetMatch=String(targetTimeRaw??'').match(/^(\d{1,2}):(\d{2})$/);
                  const targetHour=targetMatch?Number(targetMatch[1]):0;
                  const targetMinute=targetMatch?Number(targetMatch[2]):30;
                  const targetTime=`${String(targetHour).padStart(2,'0')}:${String(targetMinute).padStart(2,'0')}`;
                  const cheapStart=new Date(now);
                  cheapStart.setHours(targetHour,targetMinute,0,0);
                  if(cheapStart<=now)cheapStart.setDate(cheapStart.getDate()+1);
                  const hCheap=Math.max((cheapStart-now)/3600000,0);

                  // V2.1 (ovw2): never show a reserve projection or top-up advice from a battery reading that is not a number.
                  const socRaw=states['sensor.ecco_clock_dongle_ecco_battery_soc']?.state;
                  if(socRaw===undefined||['unknown','unavailable','none',''].includes(String(socRaw).toLowerCase())||!Number.isFinite(Number(socRaw))){
                    return `<div style="font-size:16px;font-weight:800;color:#aab4c3;">Battery data unavailable</div><div style="margin-top:6px;font-size:11px;line-height:1.5;color:rgba(255,255,255,.55);">No reserve projection or top-up advice is shown until the battery SOC reports again.</div>`;
                  }

                  // V2.1 (ovw2): the solar forecast is for the rest of the CURRENT calendar day; only the share that can arrive BEFORE the
                  // target may lift the SOC at the target (same rule as the ECCO Today card). Unknown sun times credit no solar at all.
                  const sunEntity=states['sun.sun'];
                  const solarShare=(()=>{
                    const set=sunEntity?.attributes?.next_setting?new Date(sunEntity.attributes.next_setting):null;
                    const rise=sunEntity?.attributes?.next_rising?new Date(sunEntity.attributes.next_rising):null;
                    if(!set||Number.isNaN(set.getTime()))return 0;
                    let from=null;
                    if(sunEntity.state==='above_horizon')from=now;
                    else if(rise&&!Number.isNaN(rise.getTime())&&rise.toDateString()===now.toDateString())from=rise;
                    if(from===null)return 0;
                    if(cheapStart>=set)return 1;
                    if(cheapStart<=from)return 0;
                    return (cheapStart-from)/(set-from);
                  })();
                  const targetDay=cheapStart.toDateString()===now.toDateString()?'today':'tomorrow';
                  const likelySolar=remaining!==null?remaining*factor*.95:0;
                  const predictedAt0035=remaining!==null
                    ? clamp(soc+((likelySolar*solarShare-runKw*hCheap)/capKwh)*100,0,100)
                    : soc;

                  // This is the extra energy needed for reserve/security only.
                  const batteryNeeded=Math.max(0,(minimumReserveTarget-predictedAt0035)/100*capKwh);
                  const gridNeeded=batteryNeeded/.94;

                  const nextCheapRate=nextCheap?.p ?? null;
                  const costRate=nextCheapRate ?? todayMin;
                  const costIsReference=nextCheapRate===null&&todayMin!==null;
                  const chargeCost=costRate!==null?gridNeeded*(costRate/100):null;
                  const avoidedValue=todayMax!==null?batteryNeeded*(todayMax/100):null;
                  const saving=chargeCost!==null&&avoidedValue!==null?avoidedValue-chargeCost:null;

                  const surplusPct=predictedAt0035-minimumReserveTarget;

                  let headline='Energy-reserve model says no top-up is needed';
                  let colour='#55e58e';
                  if(gridNeeded>0.2){
                    headline='Energy-reserve model recommends a cheap-rate top-up';
                    colour='#ffbd3d';
                  }else if(configuredTarget>minimumReserveTarget+15){
                    headline='Configured target is well above the modelled reserve need';
                    colour='#7ab8ff';
                  }

                  return `<div>
                    <div style="font-size:16px;font-weight:800;color:${colour};">${headline}</div>

                    <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:9px;margin-top:12px;">
                      <div style="text-align:center;padding:9px;border-radius:10px;background:rgba(255,255,255,.035);border:1px solid rgba(255,255,255,.06);">
                        <div style="font-size:10px;color:rgba(255,255,255,.48);">Configured TOU target</div>
                        <div style="font-size:22px;font-weight:800;color:#b8adff;">${Number.isFinite(configuredTarget)?configuredTarget.toFixed(0):'--'}%</div>
                      </div>
                      <div style="text-align:center;padding:9px;border-radius:10px;background:rgba(255,255,255,.035);border:1px solid rgba(255,255,255,.06);">
                        <div style="font-size:10px;color:rgba(255,255,255,.48);">Modelled reserve need</div>
                        <div style="font-size:22px;font-weight:800;color:#55e58e;">${minimumReserveTarget.toFixed(0)}%</div>
                      </div>
                      <div style="text-align:center;padding:9px;border-radius:10px;background:rgba(255,255,255,.035);border:1px solid rgba(255,255,255,.06);">
                        <div style="font-size:10px;color:rgba(255,255,255,.48);">Expected at ${targetTime} ${targetDay}</div>
                        <div style="font-size:22px;font-weight:800;color:#ffbd3d;">${predictedAt0035.toFixed(0)}%</div>
                      </div>
                    </div>

                    <div style="margin-top:11px;font-size:11px;line-height:1.55;color:rgba(255,255,255,.60);">
                      Reserve margin at ${targetTime} <b style="color:${surplusPct>=0?'#55e58e':'#ff6376'}">${surplusPct>=0?'+':''}${surplusPct.toFixed(0)} points</b>
                      • next-day load model <b style="color:#fff">${projectedDaily.toFixed(1)} kWh</b>
                      ${adjustedTomorrow!==null?` • adaptive solar <b style="color:#ffbd3d">${adjustedTomorrow.toFixed(1)} kWh</b>`:''}
                      • reserve-only charge need <b style="color:#fff">${gridNeeded.toFixed(1)} kWh</b>
                      ${chargeCost!==null?` • estimated cost <b style="color:#fff">£${chargeCost.toFixed(2)}</b>${costIsReference?' using today’s cheap rate as a reference':''}`:''}
                      ${saving!==null&&saving>0&&gridNeeded>0.1?` • avoided peak-import value <b style="color:#55e58e">£${saving.toFixed(2)}</b>`:''}.
                    </div>

                    <div style="margin-top:9px;font-size:10px;line-height:1.45;color:rgba(255,255,255,.42);">
                      The modelled reserve need is an energy-security estimate, not the ECCO reserve setting and not a proposed TOU setting.
                      ${nextCheap?` Next published cheap window: ${nextCheap.start.toLocaleTimeString([],{hour:'2-digit',minute:'2-digit'})}–${nextCheap.end.toLocaleTimeString([],{hour:'2-digit',minute:'2-digit'})} at ${nextCheap.p.toFixed(2)}p/kWh.`:' Next-day cheap rates are not published yet.'}
                      Export arbitrage and battery degradation are still excluded.
                    </div>
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
                - grid-template-areas: '"i n" "body body"'
                - grid-template-columns: 32px 1fr
                - grid-template-rows: min-content 1fr
                - row-gap: 12px
              icon:
                - width: 24px
                - color: '#55e58e'
              name:
                - justify-self: start
                - font-size: 20px
                - font-weight: 700
                - color: rgba(255,255,255,0.92)
              custom_fields:
                body:
                  - width: 100%
                  - white-space: normal
                  - overflow: visible
                  - text-overflow: unset
                  - word-break: normal
                  - line-height: 1.45
            grid_options:
              columns: 24
              rows: 6

          # ---- OCTOPUS RATE GRAPH ----
          - type: custom:button-card
""")
DASHBOARD_20_OLD = _blk(r"""
                  const liveKw=loadW/1000;
                  const runKw=clamp(avgKw*.65+liveKw*.35,.15,5);
                  const projectedDaily=clamp(runKw*24,6,60);

                  const adjustedTomorrow=tomorrow!==null?tomorrow*factor*.95:null;
                  const morningBridge=runKw*4.5;
                  const reserveKwh=capKwh*.10;
                  const dailyDeficit=adjustedTomorrow!==null?Math.max(projectedDaily-adjustedTomorrow,0):0;
                  const requiredEnergy=clamp(morningBridge+reserveKwh+dailyDeficit,capKwh*.20,capKwh);
                  const minimumReserveTarget=clamp(requiredEnergy/capKwh*100,20,100);

                  const configuredTarget=Number(states['sensor.ecco_clock_dongle_ecco_timezone1_soc']?.state??100);

                  const rateSensors=sensors.filter(s=>
                    s.entity_id.includes('octopus_energy_electricity')&&
                    s.entity_id.includes('current_rate')
                  );
                  const imp=rateSensors.find(s=>!isExport(s));

                  const parseEvent=(needle)=>{
                    const ev=events.find(s=>
                      s.entity_id.includes('octopus_energy_electricity')&&
                      s.entity_id.includes(needle)&&!isExport(s)
                    );
                    const rs=Array.isArray(ev?.attributes?.rates)?ev.attributes.rates:[];
                    return rs.map(r=>({
                      start:new Date(r.start),end:new Date(r.end),
                      p:Number(r.value_inc_vat)*100
                    })).filter(r=>Number.isFinite(r.p)&&!isNaN(r.start)&&!isNaN(r.end))
                      .sort((a,b)=>a.start-b.start);
                  };

                  const todayRates=parseEvent('current_day_rates');
                  const nextRates=parseEvent('next_day_rates');
                  const nextRateCoverageHours=nextRates.reduce((sum,r)=>sum+Math.max((r.end-r.start)/3600000,0),0);
                  const nextRatesReady=nextRates.length>=6 && nextRateCoverageHours>=3;
                  const todayMin=todayRates.length?Math.min(...todayRates.map(r=>r.p)):
                    (imp?.attributes?.current_day_min_rate!=null?Number(imp.attributes.current_day_min_rate)*100:null);
                  const todayMax=todayRates.length?Math.max(...todayRates.map(r=>r.p)):
                    (imp?.attributes?.current_day_max_rate!=null?Number(imp.attributes.current_day_max_rate)*100:null);

                  const eps=.35;
                  const windowFor=(rates,target,after)=>{
                    if(!rates.length||target===null)return null;
                    const hits=rates.filter(r=>r.end>after&&Math.abs(r.p-target)<=eps);
                    if(!hits.length)return null;
                    const first=hits[0];
                    let end=first.end;
                    for(const r of hits.slice(1)){
                      if(Math.abs(r.start-end)<60000)end=r.end;else break;
                    }
                    return {start:first.start,end,p:target};
                  };

                  let nextCheap= todayMin!==null ? windowFor(todayRates,todayMin,now) : null;
                  if(!nextCheap&&nextRatesReady){
                    const nm=Math.min(...nextRates.map(r=>r.p));
                    nextCheap=windowFor(nextRates,nm,now);
                  }

                  // Battery level expected at the live configured charge-slot start.
                  const targetTimeRaw=states['sensor.ecco_config_charge_start_time']?.state;
                  const targetMatch=String(targetTimeRaw??'').match(/^(\d{1,2}):(\d{2})$/);
                  const targetHour=targetMatch?Number(targetMatch[1]):0;
                  const targetMinute=targetMatch?Number(targetMatch[2]):30;
                  const targetTime=`${String(targetHour).padStart(2,'0')}:${String(targetMinute).padStart(2,'0')}`;
                  const cheapStart=new Date(now);
                  cheapStart.setHours(targetHour,targetMinute,0,0);
                  if(cheapStart<=now)cheapStart.setDate(cheapStart.getDate()+1);
                  const hCheap=Math.max((cheapStart-now)/3600000,0);

                  // V2.1 (ovw2): never show a reserve projection or top-up advice from a battery reading that is not a number.
                  const socRaw=states['sensor.ecco_clock_dongle_ecco_battery_soc']?.state;
                  if(socRaw===undefined||['unknown','unavailable','none',''].includes(String(socRaw).toLowerCase())||!Number.isFinite(Number(socRaw))){
                    return `<div style="font-size:16px;font-weight:800;color:#aab4c3;">Battery data unavailable</div><div style="margin-top:6px;font-size:11px;line-height:1.5;color:rgba(255,255,255,.55);">No reserve projection or top-up advice is shown until the battery SOC reports again.</div>`;
                  }

                  // V2.1 (ovw2): the solar forecast is for the rest of the CURRENT calendar day; only the share that can arrive BEFORE the
                  // target may lift the SOC at the target (same rule as the ECCO Today card). Unknown sun times credit no solar at all.
                  const sunEntity=states['sun.sun'];
                  const solarShare=(()=>{
                    const set=sunEntity?.attributes?.next_setting?new Date(sunEntity.attributes.next_setting):null;
                    const rise=sunEntity?.attributes?.next_rising?new Date(sunEntity.attributes.next_rising):null;
                    if(!set||Number.isNaN(set.getTime()))return 0;
                    let from=null;
                    if(sunEntity.state==='above_horizon')from=now;
                    else if(rise&&!Number.isNaN(rise.getTime())&&rise.toDateString()===now.toDateString())from=rise;
                    if(from===null)return 0;
                    if(cheapStart>=set)return 1;
                    if(cheapStart<=from)return 0;
                    return (cheapStart-from)/(set-from);
                  })();
                  const targetDay=cheapStart.toDateString()===now.toDateString()?'today':'tomorrow';
                  const likelySolar=remaining!==null?remaining*factor*.95:0;
                  const predictedAt0035=remaining!==null
                    ? clamp(soc+((likelySolar*solarShare-runKw*hCheap)/capKwh)*100,0,100)
                    : soc;

                  // This is the extra energy needed for reserve/security only.
                  const batteryNeeded=Math.max(0,(minimumReserveTarget-predictedAt0035)/100*capKwh);
                  const gridNeeded=batteryNeeded/.94;

                  const nextCheapRate=nextCheap?.p ?? null;
                  const costRate=nextCheapRate ?? todayMin;
                  const costIsReference=nextCheapRate===null&&todayMin!==null;
                  const chargeCost=costRate!==null?gridNeeded*(costRate/100):null;
                  const avoidedValue=todayMax!==null?batteryNeeded*(todayMax/100):null;
                  const saving=chargeCost!==null&&avoidedValue!==null?avoidedValue-chargeCost:null;

                  const surplusPct=predictedAt0035-minimumReserveTarget;

                  let headline='Energy-reserve model says no top-up is needed';
                  let colour='#55e58e';
                  if(gridNeeded>0.2){
                    headline='Energy-reserve model recommends a cheap-rate top-up';
                    colour='#ffbd3d';
                  }else if(configuredTarget>minimumReserveTarget+15){
                    headline='Configured target is well above the modelled reserve need';
                    colour='#7ab8ff';
                  }

                  return `<div>
                    <div style="font-size:16px;font-weight:800;color:${colour};">${headline}</div>

                    <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:9px;margin-top:12px;">
                      <div style="text-align:center;padding:9px;border-radius:10px;background:rgba(255,255,255,.035);border:1px solid rgba(255,255,255,.06);">
                        <div style="font-size:10px;color:rgba(255,255,255,.48);">Configured TOU target</div>
                        <div style="font-size:22px;font-weight:800;color:#b8adff;">${Number.isFinite(configuredTarget)?configuredTarget.toFixed(0):'--'}%</div>
                      </div>
                      <div style="text-align:center;padding:9px;border-radius:10px;background:rgba(255,255,255,.035);border:1px solid rgba(255,255,255,.06);">
                        <div style="font-size:10px;color:rgba(255,255,255,.48);">Modelled reserve need</div>
                        <div style="font-size:22px;font-weight:800;color:#55e58e;">${minimumReserveTarget.toFixed(0)}%</div>
                      </div>
                      <div style="text-align:center;padding:9px;border-radius:10px;background:rgba(255,255,255,.035);border:1px solid rgba(255,255,255,.06);">
                        <div style="font-size:10px;color:rgba(255,255,255,.48);">Expected at ${targetTime} ${targetDay}</div>
                        <div style="font-size:22px;font-weight:800;color:#ffbd3d;">${predictedAt0035.toFixed(0)}%</div>
                      </div>
                    </div>

                    <div style="margin-top:11px;font-size:11px;line-height:1.55;color:rgba(255,255,255,.60);">
                      Reserve margin at ${targetTime} <b style="color:${surplusPct>=0?'#55e58e':'#ff6376'}">${surplusPct>=0?'+':''}${surplusPct.toFixed(0)} points</b>
                      • next-day load model <b style="color:#fff">${projectedDaily.toFixed(1)} kWh</b>
                      ${adjustedTomorrow!==null?` • adaptive solar <b style="color:#ffbd3d">${adjustedTomorrow.toFixed(1)} kWh</b>`:''}
                      • reserve-only charge need <b style="color:#fff">${gridNeeded.toFixed(1)} kWh</b>
                      ${chargeCost!==null?` • estimated cost <b style="color:#fff">£${chargeCost.toFixed(2)}</b>${costIsReference?' using today’s cheap rate as a reference':''}`:''}
                      ${saving!==null&&saving>0&&gridNeeded>0.1?` • avoided peak-import value <b style="color:#55e58e">£${saving.toFixed(2)}</b>`:''}.
                    </div>

                    <div style="margin-top:9px;font-size:10px;line-height:1.45;color:rgba(255,255,255,.42);">
                      The modelled reserve need is an energy-security estimate, not the ECCO reserve setting and not a proposed TOU setting.
                      ${nextCheap?` Next published cheap window: ${nextCheap.start.toLocaleTimeString([],{hour:'2-digit',minute:'2-digit'})}–${nextCheap.end.toLocaleTimeString([],{hour:'2-digit',minute:'2-digit'})} at ${nextCheap.p.toFixed(2)}p/kWh.`:' Next-day cheap rates are not published yet.'}
                      Export arbitrage and battery degradation are still excluded.
                    </div>
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
                - grid-template-areas: '"i n" "body body"'
                - grid-template-columns: 32px 1fr
                - grid-template-rows: min-content 1fr
                - row-gap: 12px
              icon:
                - width: 24px
                - color: '#55e58e'
              name:
                - justify-self: start
                - font-size: 20px
                - font-weight: 700
                - color: rgba(255,255,255,0.92)
              custom_fields:
                body:
                  - width: 100%
                  - white-space: normal
                  - overflow: visible
                  - text-overflow: unset
                  - word-break: normal
                  - line-height: 1.45
            grid_options:
              columns: 24
              rows: 6

          # ---- OCTOPUS RATE GRAPH ----
          - type: custom:apexcharts-card
""")
DASHBOARD_20_NEW = _blk(r"""
                  const liveKw=Number.isFinite(loadW)?loadW/1000:avgKw;   // hd1: house load unavailable -> the average alone
                  const runKw=clamp(avgKw*.65+liveKw*.35,.15,5);
                  const projectedDaily=clamp(runKw*24,6,60);

                  const adjustedTomorrow=tomorrow!==null?tomorrow*factor*.95:null;
                  const morningBridge=runKw*4.5;
                  const reserveKwh=capKwh*.10;
                  const dailyDeficit=adjustedTomorrow!==null?Math.max(projectedDaily-adjustedTomorrow,0):0;
                  const requiredEnergy=clamp(morningBridge+reserveKwh+dailyDeficit,capKwh*.20,capKwh);
                  const minimumReserveTarget=clamp(requiredEnergy/capKwh*100,20,100);

                  const configuredTarget=Number(states['sensor.ecco_clock_dongle_ecco_timezone1_soc']?.state??100);

                  const rateSensors=sensors.filter(s=>
                    s.entity_id.includes('octopus_energy_electricity')&&
                    s.entity_id.includes('current_rate')
                  );
                  const imp=rateSensors.find(s=>!isExport(s));

                  const parseEvent=(needle)=>{
                    const ev=events.find(s=>
                      s.entity_id.includes('octopus_energy_electricity')&&
                      s.entity_id.includes(needle)&&!isExport(s)
                    );
                    const rs=Array.isArray(ev?.attributes?.rates)?ev.attributes.rates:[];
                    return rs.map(r=>({
                      start:new Date(r.start),end:new Date(r.end),
                      p:Number(r.value_inc_vat)*100
                    })).filter(r=>Number.isFinite(r.p)&&!isNaN(r.start)&&!isNaN(r.end))
                      .sort((a,b)=>a.start-b.start);
                  };

                  const todayRates=parseEvent('current_day_rates');
                  const nextRates=parseEvent('next_day_rates');
                  const nextRateCoverageHours=nextRates.reduce((sum,r)=>sum+Math.max((r.end-r.start)/3600000,0),0);
                  const nextRatesReady=nextRates.length>=6 && nextRateCoverageHours>=3;
                  const todayMin=todayRates.length?Math.min(...todayRates.map(r=>r.p)):
                    (imp?.attributes?.current_day_min_rate!=null?Number(imp.attributes.current_day_min_rate)*100:null);
                  const todayMax=todayRates.length?Math.max(...todayRates.map(r=>r.p)):
                    (imp?.attributes?.current_day_max_rate!=null?Number(imp.attributes.current_day_max_rate)*100:null);

                  const eps=.35;
                  const windowFor=(rates,target,after)=>{
                    if(!rates.length||target===null)return null;
                    const hits=rates.filter(r=>r.end>after&&Math.abs(r.p-target)<=eps);
                    if(!hits.length)return null;
                    const first=hits[0];
                    let end=first.end;
                    for(const r of hits.slice(1)){
                      if(Math.abs(r.start-end)<60000)end=r.end;else break;
                    }
                    return {start:first.start,end,p:target};
                  };

                  let nextCheap= todayMin!==null ? windowFor(todayRates,todayMin,now) : null;
                  if(!nextCheap&&nextRatesReady){
                    const nm=Math.min(...nextRates.map(r=>r.p));
                    nextCheap=windowFor(nextRates,nm,now);
                  }

                  // Battery level expected at the live configured charge-slot start.
                  const targetTimeRaw=states['sensor.ecco_config_charge_start_time']?.state;
                  const targetMatch=String(targetTimeRaw??'').match(/^(\d{1,2}):(\d{2})$/);
                  const targetHour=targetMatch?Number(targetMatch[1]):0;
                  const targetMinute=targetMatch?Number(targetMatch[2]):30;
                  const targetTime=`${String(targetHour).padStart(2,'0')}:${String(targetMinute).padStart(2,'0')}`;
                  const cheapStart=new Date(now);
                  cheapStart.setHours(targetHour,targetMinute,0,0);
                  if(cheapStart<=now)cheapStart.setDate(cheapStart.getDate()+1);
                  const hCheap=Math.max((cheapStart-now)/3600000,0);

                  // V2.1 (ovw2): never show a reserve projection or top-up advice from a battery reading that is not a number.
                  const socRaw=states['sensor.ecco_clock_dongle_ecco_battery_soc']?.state;
                  if(socRaw===undefined||['unknown','unavailable','none',''].includes(String(socRaw).toLowerCase())||!Number.isFinite(Number(socRaw))){
                    return `<div style="font-size:16px;font-weight:800;color:#aab4c3;">Battery data unavailable</div><div style="margin-top:6px;font-size:11px;line-height:1.5;color:rgba(255,255,255,.55);">No reserve projection or top-up advice is shown until the battery SOC reports again.</div>`;
                  }

                  // V2.1 (ovw2): the solar forecast is for the rest of the CURRENT calendar day; only the share that can arrive BEFORE the
                  // target may lift the SOC at the target (same rule as the ECCO Today card). Unknown sun times credit no solar at all.
                  const sunEntity=states['sun.sun'];
                  const solarShare=(()=>{
                    const set=sunEntity?.attributes?.next_setting?new Date(sunEntity.attributes.next_setting):null;
                    const rise=sunEntity?.attributes?.next_rising?new Date(sunEntity.attributes.next_rising):null;
                    if(!set||Number.isNaN(set.getTime()))return 0;
                    let from=null;
                    if(sunEntity.state==='above_horizon')from=now;
                    else if(rise&&!Number.isNaN(rise.getTime())&&rise.toDateString()===now.toDateString())from=rise;
                    if(from===null)return 0;
                    if(cheapStart>=set)return 1;
                    if(cheapStart<=from)return 0;
                    return (cheapStart-from)/(set-from);
                  })();
                  const targetDay=cheapStart.toDateString()===now.toDateString()?'today':'tomorrow';
                  const likelySolar=remaining!==null?remaining*factor*.95:0;
                  const predictedAt0035=remaining!==null
                    ? clamp(soc+((likelySolar*solarShare-runKw*hCheap)/capKwh)*100,0,100)
                    : soc;

                  // This is the extra energy needed for reserve/security only.
                  const batteryNeeded=Math.max(0,(minimumReserveTarget-predictedAt0035)/100*capKwh);
                  const gridNeeded=batteryNeeded/.94;

                  const nextCheapRate=nextCheap?.p ?? null;
                  const costRate=nextCheapRate ?? todayMin;
                  const costIsReference=nextCheapRate===null&&todayMin!==null;
                  const chargeCost=costRate!==null?gridNeeded*(costRate/100):null;
                  const avoidedValue=todayMax!==null?batteryNeeded*(todayMax/100):null;
                  const saving=chargeCost!==null&&avoidedValue!==null?avoidedValue-chargeCost:null;

                  const surplusPct=predictedAt0035-minimumReserveTarget;

                  let headline='Energy-reserve model says no top-up is needed';
                  let colour='#55e58e';
                  if(gridNeeded>0.2){
                    headline='Energy-reserve model recommends a cheap-rate top-up';
                    colour='#ffbd3d';
                  }else if(configuredTarget>minimumReserveTarget+15){
                    headline='Configured target is well above the modelled reserve need';
                    colour='#7ab8ff';
                  }

                  return `<div>
                    <div style="font-size:16px;font-weight:800;color:${colour};">${headline}</div>

                    <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:9px;margin-top:12px;">
                      <div style="text-align:center;padding:9px;border-radius:10px;background:rgba(255,255,255,.035);border:1px solid rgba(255,255,255,.06);">
                        <div style="font-size:10px;color:rgba(255,255,255,.48);">Configured TOU target</div>
                        <div style="font-size:22px;font-weight:800;color:#b8adff;">${Number.isFinite(configuredTarget)?configuredTarget.toFixed(0):'--'}%</div>
                      </div>
                      <div style="text-align:center;padding:9px;border-radius:10px;background:rgba(255,255,255,.035);border:1px solid rgba(255,255,255,.06);">
                        <div style="font-size:10px;color:rgba(255,255,255,.48);">Modelled reserve need</div>
                        <div style="font-size:22px;font-weight:800;color:#55e58e;">${minimumReserveTarget.toFixed(0)}%</div>
                      </div>
                      <div style="text-align:center;padding:9px;border-radius:10px;background:rgba(255,255,255,.035);border:1px solid rgba(255,255,255,.06);">
                        <div style="font-size:10px;color:rgba(255,255,255,.48);">Expected at ${targetTime} ${targetDay}</div>
                        <div style="font-size:22px;font-weight:800;color:#ffbd3d;">${predictedAt0035.toFixed(0)}%</div>
                      </div>
                    </div>

                    <div style="margin-top:11px;font-size:11px;line-height:1.55;color:rgba(255,255,255,.60);">
                      Reserve margin at ${targetTime} <b style="color:${surplusPct>=0?'#55e58e':'#ff6376'}">${surplusPct>=0?'+':''}${surplusPct.toFixed(0)} points</b>
                      • next-day load model <b style="color:#fff">${projectedDaily.toFixed(1)} kWh</b>
                      ${adjustedTomorrow!==null?` • adaptive solar <b style="color:#ffbd3d">${adjustedTomorrow.toFixed(1)} kWh</b>`:''}
                      • reserve-only charge need <b style="color:#fff">${gridNeeded.toFixed(1)} kWh</b>
                      ${chargeCost!==null?` • estimated cost <b style="color:#fff">£${chargeCost.toFixed(2)}</b>${costIsReference?' using today’s cheap rate as a reference':''}`:''}
                      ${saving!==null&&saving>0&&gridNeeded>0.1?` • avoided peak-import value <b style="color:#55e58e">£${saving.toFixed(2)}</b>`:''}.
                    </div>

                    <div style="margin-top:9px;font-size:10px;line-height:1.45;color:rgba(255,255,255,.42);">
                      The modelled reserve need is an energy-security estimate, not the ECCO reserve setting and not a proposed TOU setting.
                      ${nextCheap?` Next published cheap window: ${nextCheap.start.toLocaleTimeString([],{hour:'2-digit',minute:'2-digit'})}–${nextCheap.end.toLocaleTimeString([],{hour:'2-digit',minute:'2-digit'})} at ${nextCheap.p.toFixed(2)}p/kWh.`:' Next-day cheap rates are not published yet.'}
                      Export arbitrage and battery degradation are still excluded.
                    </div>
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
                - grid-template-areas: '"i n" "body body"'
                - grid-template-columns: 32px 1fr
                - grid-template-rows: min-content 1fr
                - row-gap: 12px
              icon:
                - width: 24px
                - color: '#55e58e'
              name:
                - justify-self: start
                - font-size: 20px
                - font-weight: 700
                - color: rgba(255,255,255,0.92)
              custom_fields:
                body:
                  - width: 100%
                  - white-space: normal
                  - overflow: visible
                  - text-overflow: unset
                  - word-break: normal
                  - line-height: 1.45
            grid_options:
              columns: 24
              rows: 6

          # ---- OCTOPUS RATE GRAPH ----
          - type: custom:apexcharts-card
""")
DASHBOARD_21_OLD = _blk(r"""
                  const liveKw=loadW/1000;
                  const runKw=clamp(avgKw*.65+liveKw*.35,.15,5);
                  const projectedDaily=clamp(runKw*24,6,60);

                  const adjustedTomorrow=tomorrow!==null?tomorrow*factor*.95:null;
                  const morningBridge=runKw*4.5;
                  const reserveKwh=capKwh*.10;
                  const dailyDeficit=adjustedTomorrow!==null?Math.max(projectedDaily-adjustedTomorrow,0):0;
                  const requiredEnergy=clamp(morningBridge+reserveKwh+dailyDeficit,capKwh*.20,capKwh);
                  const minimumReserveTarget=clamp(requiredEnergy/capKwh*100,20,100);

                  const configuredTarget=Number(states['sensor.ecco_clock_dongle_ecco_timezone1_soc']?.state??100);

                  const rateSensors=sensors.filter(s=>
                    s.entity_id.includes('octopus_energy_electricity')&&
                    s.entity_id.includes('current_rate')
                  );
                  const imp=rateSensors.find(s=>!isExport(s));

                  const parseEvent=(needle)=>{
                    const ev=events.find(s=>
                      s.entity_id.includes('octopus_energy_electricity')&&
                      s.entity_id.includes(needle)&&!isExport(s)
                    );
                    const rs=Array.isArray(ev?.attributes?.rates)?ev.attributes.rates:[];
                    return rs.map(r=>({
                      start:new Date(r.start),end:new Date(r.end),
                      p:Number(r.value_inc_vat)*100
                    })).filter(r=>Number.isFinite(r.p)&&!isNaN(r.start)&&!isNaN(r.end))
                      .sort((a,b)=>a.start-b.start);
                  };

                  const todayRates=parseEvent('current_day_rates');
                  const nextRates=parseEvent('next_day_rates');
                  const nextRateCoverageHours=nextRates.reduce((sum,r)=>sum+Math.max((r.end-r.start)/3600000,0),0);
                  const nextRatesReady=nextRates.length>=6 && nextRateCoverageHours>=3;
                  const todayMin=todayRates.length?Math.min(...todayRates.map(r=>r.p)):
                    (imp?.attributes?.current_day_min_rate!=null?Number(imp.attributes.current_day_min_rate)*100:null);
                  const todayMax=todayRates.length?Math.max(...todayRates.map(r=>r.p)):
                    (imp?.attributes?.current_day_max_rate!=null?Number(imp.attributes.current_day_max_rate)*100:null);

                  const eps=.35;
                  const windowFor=(rates,target,after)=>{
                    if(!rates.length||target===null)return null;
                    const hits=rates.filter(r=>r.end>after&&Math.abs(r.p-target)<=eps);
                    if(!hits.length)return null;
                    const first=hits[0];
                    let end=first.end;
                    for(const r of hits.slice(1)){
                      if(Math.abs(r.start-end)<60000)end=r.end;else break;
                    }
                    return {start:first.start,end,p:target};
                  };

                  let nextCheap= todayMin!==null ? windowFor(todayRates,todayMin,now) : null;
                  if(!nextCheap&&nextRatesReady){
                    const nm=Math.min(...nextRates.map(r=>r.p));
                    nextCheap=windowFor(nextRates,nm,now);
                  }

                  // Battery level expected at the live configured charge-slot start.
                  const targetTimeRaw=states['sensor.ecco_config_charge_start_time']?.state;
                  const targetMatch=String(targetTimeRaw??'').match(/^(\d{1,2}):(\d{2})$/);
                  const targetHour=targetMatch?Number(targetMatch[1]):0;
                  const targetMinute=targetMatch?Number(targetMatch[2]):30;
                  const targetTime=`${String(targetHour).padStart(2,'0')}:${String(targetMinute).padStart(2,'0')}`;
                  const cheapStart=new Date(now);
                  cheapStart.setHours(targetHour,targetMinute,0,0);
                  if(cheapStart<=now)cheapStart.setDate(cheapStart.getDate()+1);
                  const hCheap=Math.max((cheapStart-now)/3600000,0);

                  // V2.1 (ovw2): never show a reserve projection or top-up advice from a battery reading that is not a number.
                  const socRaw=states['sensor.ecco_clock_dongle_ecco_battery_soc']?.state;
                  if(socRaw===undefined||['unknown','unavailable','none',''].includes(String(socRaw).toLowerCase())||!Number.isFinite(Number(socRaw))){
                    return `<div style="font-size:16px;font-weight:800;color:#aab4c3;">Battery data unavailable</div><div style="margin-top:6px;font-size:11px;line-height:1.5;color:rgba(255,255,255,.55);">No reserve projection or top-up advice is shown until the battery SOC reports again.</div>`;
                  }

                  // V2.1 (ovw2): the solar forecast is for the rest of the CURRENT calendar day; only the share that can arrive BEFORE the
                  // target may lift the SOC at the target (same rule as the ECCO Today card). Unknown sun times credit no solar at all.
                  const sunEntity=states['sun.sun'];
                  const solarShare=(()=>{
                    const set=sunEntity?.attributes?.next_setting?new Date(sunEntity.attributes.next_setting):null;
                    const rise=sunEntity?.attributes?.next_rising?new Date(sunEntity.attributes.next_rising):null;
                    if(!set||Number.isNaN(set.getTime()))return 0;
                    let from=null;
                    if(sunEntity.state==='above_horizon')from=now;
                    else if(rise&&!Number.isNaN(rise.getTime())&&rise.toDateString()===now.toDateString())from=rise;
                    if(from===null)return 0;
                    if(cheapStart>=set)return 1;
                    if(cheapStart<=from)return 0;
                    return (cheapStart-from)/(set-from);
                  })();
                  const targetDay=cheapStart.toDateString()===now.toDateString()?'today':'tomorrow';
                  const likelySolar=remaining!==null?remaining*factor*.95:0;
                  const predictedAt0035=remaining!==null
                    ? clamp(soc+((likelySolar*solarShare-runKw*hCheap)/capKwh)*100,0,100)
                    : soc;

                  // This is the extra energy needed for reserve/security only.
                  const batteryNeeded=Math.max(0,(minimumReserveTarget-predictedAt0035)/100*capKwh);
                  const gridNeeded=batteryNeeded/.94;

                  const nextCheapRate=nextCheap?.p ?? null;
                  const costRate=nextCheapRate ?? todayMin;
                  const costIsReference=nextCheapRate===null&&todayMin!==null;
                  const chargeCost=costRate!==null?gridNeeded*(costRate/100):null;
                  const avoidedValue=todayMax!==null?batteryNeeded*(todayMax/100):null;
                  const saving=chargeCost!==null&&avoidedValue!==null?avoidedValue-chargeCost:null;

                  const surplusPct=predictedAt0035-minimumReserveTarget;

                  let headline='Energy-reserve model says no top-up is needed';
                  let colour='#55e58e';
                  if(gridNeeded>0.2){
                    headline='Energy-reserve model recommends a cheap-rate top-up';
                    colour='#ffbd3d';
                  }else if(configuredTarget>minimumReserveTarget+15){
                    headline='Configured target is well above the modelled reserve need';
                    colour='#7ab8ff';
                  }

                  return `<div>
                    <div style="font-size:16px;font-weight:800;color:${colour};">${headline}</div>

                    <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:9px;margin-top:12px;">
                      <div style="text-align:center;padding:9px;border-radius:10px;background:rgba(255,255,255,.035);border:1px solid rgba(255,255,255,.06);">
                        <div style="font-size:10px;color:rgba(255,255,255,.48);">Configured TOU target</div>
                        <div style="font-size:22px;font-weight:800;color:#b8adff;">${Number.isFinite(configuredTarget)?configuredTarget.toFixed(0):'--'}%</div>
                      </div>
                      <div style="text-align:center;padding:9px;border-radius:10px;background:rgba(255,255,255,.035);border:1px solid rgba(255,255,255,.06);">
                        <div style="font-size:10px;color:rgba(255,255,255,.48);">Modelled reserve need</div>
                        <div style="font-size:22px;font-weight:800;color:#55e58e;">${minimumReserveTarget.toFixed(0)}%</div>
                      </div>
                      <div style="text-align:center;padding:9px;border-radius:10px;background:rgba(255,255,255,.035);border:1px solid rgba(255,255,255,.06);">
                        <div style="font-size:10px;color:rgba(255,255,255,.48);">Expected at ${targetTime} ${targetDay}</div>
                        <div style="font-size:22px;font-weight:800;color:#ffbd3d;">${predictedAt0035.toFixed(0)}%</div>
                      </div>
                    </div>

                    <div style="margin-top:11px;font-size:11px;line-height:1.55;color:rgba(255,255,255,.60);">
                      Reserve margin at ${targetTime} <b style="color:${surplusPct>=0?'#55e58e':'#ff6376'}">${surplusPct>=0?'+':''}${surplusPct.toFixed(0)} points</b>
                      • next-day load model <b style="color:#fff">${projectedDaily.toFixed(1)} kWh</b>
                      ${adjustedTomorrow!==null?` • adaptive solar <b style="color:#ffbd3d">${adjustedTomorrow.toFixed(1)} kWh</b>`:''}
                      • reserve-only charge need <b style="color:#fff">${gridNeeded.toFixed(1)} kWh</b>
                      ${chargeCost!==null?` • estimated cost <b style="color:#fff">£${chargeCost.toFixed(2)}</b>${costIsReference?' using today’s cheap rate as a reference':''}`:''}
                      ${saving!==null&&saving>0&&gridNeeded>0.1?` • avoided peak-import value <b style="color:#55e58e">£${saving.toFixed(2)}</b>`:''}.
                    </div>

                    <div style="margin-top:9px;font-size:10px;line-height:1.45;color:rgba(255,255,255,.42);">
                      The modelled reserve need is an energy-security estimate, not the ECCO reserve setting and not a proposed TOU setting.
                      ${nextCheap?` Next published cheap window: ${nextCheap.start.toLocaleTimeString([],{hour:'2-digit',minute:'2-digit'})}–${nextCheap.end.toLocaleTimeString([],{hour:'2-digit',minute:'2-digit'})} at ${nextCheap.p.toFixed(2)}p/kWh.`:' Next-day cheap rates are not published yet.'}
                      Export arbitrage and battery degradation are still excluded.
                    </div>
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
                - grid-template-areas: '"i n" "body body"'
                - grid-template-columns: 32px 1fr
                - grid-template-rows: min-content 1fr
                - row-gap: 12px
              icon:
                - width: 24px
                - color: '#55e58e'
              name:
                - justify-self: start
                - font-size: 20px
                - font-weight: 700
                - color: rgba(255,255,255,0.92)
              custom_fields:
                body:
                  - width: 100%
                  - white-space: normal
                  - overflow: visible
                  - text-overflow: unset
                  - word-break: normal
                  - line-height: 1.45
            grid_options:
              columns: 32
              rows: 6

          # ---- OCTOPUS RATE GRAPH ----

  - title: Recommended
""")
DASHBOARD_21_NEW = _blk(r"""
                  const liveKw=Number.isFinite(loadW)?loadW/1000:avgKw;   // hd1: house load unavailable -> the average alone
                  const runKw=clamp(avgKw*.65+liveKw*.35,.15,5);
                  const projectedDaily=clamp(runKw*24,6,60);

                  const adjustedTomorrow=tomorrow!==null?tomorrow*factor*.95:null;
                  const morningBridge=runKw*4.5;
                  const reserveKwh=capKwh*.10;
                  const dailyDeficit=adjustedTomorrow!==null?Math.max(projectedDaily-adjustedTomorrow,0):0;
                  const requiredEnergy=clamp(morningBridge+reserveKwh+dailyDeficit,capKwh*.20,capKwh);
                  const minimumReserveTarget=clamp(requiredEnergy/capKwh*100,20,100);

                  const configuredTarget=Number(states['sensor.ecco_clock_dongle_ecco_timezone1_soc']?.state??100);

                  const rateSensors=sensors.filter(s=>
                    s.entity_id.includes('octopus_energy_electricity')&&
                    s.entity_id.includes('current_rate')
                  );
                  const imp=rateSensors.find(s=>!isExport(s));

                  const parseEvent=(needle)=>{
                    const ev=events.find(s=>
                      s.entity_id.includes('octopus_energy_electricity')&&
                      s.entity_id.includes(needle)&&!isExport(s)
                    );
                    const rs=Array.isArray(ev?.attributes?.rates)?ev.attributes.rates:[];
                    return rs.map(r=>({
                      start:new Date(r.start),end:new Date(r.end),
                      p:Number(r.value_inc_vat)*100
                    })).filter(r=>Number.isFinite(r.p)&&!isNaN(r.start)&&!isNaN(r.end))
                      .sort((a,b)=>a.start-b.start);
                  };

                  const todayRates=parseEvent('current_day_rates');
                  const nextRates=parseEvent('next_day_rates');
                  const nextRateCoverageHours=nextRates.reduce((sum,r)=>sum+Math.max((r.end-r.start)/3600000,0),0);
                  const nextRatesReady=nextRates.length>=6 && nextRateCoverageHours>=3;
                  const todayMin=todayRates.length?Math.min(...todayRates.map(r=>r.p)):
                    (imp?.attributes?.current_day_min_rate!=null?Number(imp.attributes.current_day_min_rate)*100:null);
                  const todayMax=todayRates.length?Math.max(...todayRates.map(r=>r.p)):
                    (imp?.attributes?.current_day_max_rate!=null?Number(imp.attributes.current_day_max_rate)*100:null);

                  const eps=.35;
                  const windowFor=(rates,target,after)=>{
                    if(!rates.length||target===null)return null;
                    const hits=rates.filter(r=>r.end>after&&Math.abs(r.p-target)<=eps);
                    if(!hits.length)return null;
                    const first=hits[0];
                    let end=first.end;
                    for(const r of hits.slice(1)){
                      if(Math.abs(r.start-end)<60000)end=r.end;else break;
                    }
                    return {start:first.start,end,p:target};
                  };

                  let nextCheap= todayMin!==null ? windowFor(todayRates,todayMin,now) : null;
                  if(!nextCheap&&nextRatesReady){
                    const nm=Math.min(...nextRates.map(r=>r.p));
                    nextCheap=windowFor(nextRates,nm,now);
                  }

                  // Battery level expected at the live configured charge-slot start.
                  const targetTimeRaw=states['sensor.ecco_config_charge_start_time']?.state;
                  const targetMatch=String(targetTimeRaw??'').match(/^(\d{1,2}):(\d{2})$/);
                  const targetHour=targetMatch?Number(targetMatch[1]):0;
                  const targetMinute=targetMatch?Number(targetMatch[2]):30;
                  const targetTime=`${String(targetHour).padStart(2,'0')}:${String(targetMinute).padStart(2,'0')}`;
                  const cheapStart=new Date(now);
                  cheapStart.setHours(targetHour,targetMinute,0,0);
                  if(cheapStart<=now)cheapStart.setDate(cheapStart.getDate()+1);
                  const hCheap=Math.max((cheapStart-now)/3600000,0);

                  // V2.1 (ovw2): never show a reserve projection or top-up advice from a battery reading that is not a number.
                  const socRaw=states['sensor.ecco_clock_dongle_ecco_battery_soc']?.state;
                  if(socRaw===undefined||['unknown','unavailable','none',''].includes(String(socRaw).toLowerCase())||!Number.isFinite(Number(socRaw))){
                    return `<div style="font-size:16px;font-weight:800;color:#aab4c3;">Battery data unavailable</div><div style="margin-top:6px;font-size:11px;line-height:1.5;color:rgba(255,255,255,.55);">No reserve projection or top-up advice is shown until the battery SOC reports again.</div>`;
                  }

                  // V2.1 (ovw2): the solar forecast is for the rest of the CURRENT calendar day; only the share that can arrive BEFORE the
                  // target may lift the SOC at the target (same rule as the ECCO Today card). Unknown sun times credit no solar at all.
                  const sunEntity=states['sun.sun'];
                  const solarShare=(()=>{
                    const set=sunEntity?.attributes?.next_setting?new Date(sunEntity.attributes.next_setting):null;
                    const rise=sunEntity?.attributes?.next_rising?new Date(sunEntity.attributes.next_rising):null;
                    if(!set||Number.isNaN(set.getTime()))return 0;
                    let from=null;
                    if(sunEntity.state==='above_horizon')from=now;
                    else if(rise&&!Number.isNaN(rise.getTime())&&rise.toDateString()===now.toDateString())from=rise;
                    if(from===null)return 0;
                    if(cheapStart>=set)return 1;
                    if(cheapStart<=from)return 0;
                    return (cheapStart-from)/(set-from);
                  })();
                  const targetDay=cheapStart.toDateString()===now.toDateString()?'today':'tomorrow';
                  const likelySolar=remaining!==null?remaining*factor*.95:0;
                  const predictedAt0035=remaining!==null
                    ? clamp(soc+((likelySolar*solarShare-runKw*hCheap)/capKwh)*100,0,100)
                    : soc;

                  // This is the extra energy needed for reserve/security only.
                  const batteryNeeded=Math.max(0,(minimumReserveTarget-predictedAt0035)/100*capKwh);
                  const gridNeeded=batteryNeeded/.94;

                  const nextCheapRate=nextCheap?.p ?? null;
                  const costRate=nextCheapRate ?? todayMin;
                  const costIsReference=nextCheapRate===null&&todayMin!==null;
                  const chargeCost=costRate!==null?gridNeeded*(costRate/100):null;
                  const avoidedValue=todayMax!==null?batteryNeeded*(todayMax/100):null;
                  const saving=chargeCost!==null&&avoidedValue!==null?avoidedValue-chargeCost:null;

                  const surplusPct=predictedAt0035-minimumReserveTarget;

                  let headline='Energy-reserve model says no top-up is needed';
                  let colour='#55e58e';
                  if(gridNeeded>0.2){
                    headline='Energy-reserve model recommends a cheap-rate top-up';
                    colour='#ffbd3d';
                  }else if(configuredTarget>minimumReserveTarget+15){
                    headline='Configured target is well above the modelled reserve need';
                    colour='#7ab8ff';
                  }

                  return `<div>
                    <div style="font-size:16px;font-weight:800;color:${colour};">${headline}</div>

                    <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:9px;margin-top:12px;">
                      <div style="text-align:center;padding:9px;border-radius:10px;background:rgba(255,255,255,.035);border:1px solid rgba(255,255,255,.06);">
                        <div style="font-size:10px;color:rgba(255,255,255,.48);">Configured TOU target</div>
                        <div style="font-size:22px;font-weight:800;color:#b8adff;">${Number.isFinite(configuredTarget)?configuredTarget.toFixed(0):'--'}%</div>
                      </div>
                      <div style="text-align:center;padding:9px;border-radius:10px;background:rgba(255,255,255,.035);border:1px solid rgba(255,255,255,.06);">
                        <div style="font-size:10px;color:rgba(255,255,255,.48);">Modelled reserve need</div>
                        <div style="font-size:22px;font-weight:800;color:#55e58e;">${minimumReserveTarget.toFixed(0)}%</div>
                      </div>
                      <div style="text-align:center;padding:9px;border-radius:10px;background:rgba(255,255,255,.035);border:1px solid rgba(255,255,255,.06);">
                        <div style="font-size:10px;color:rgba(255,255,255,.48);">Expected at ${targetTime} ${targetDay}</div>
                        <div style="font-size:22px;font-weight:800;color:#ffbd3d;">${predictedAt0035.toFixed(0)}%</div>
                      </div>
                    </div>

                    <div style="margin-top:11px;font-size:11px;line-height:1.55;color:rgba(255,255,255,.60);">
                      Reserve margin at ${targetTime} <b style="color:${surplusPct>=0?'#55e58e':'#ff6376'}">${surplusPct>=0?'+':''}${surplusPct.toFixed(0)} points</b>
                      • next-day load model <b style="color:#fff">${projectedDaily.toFixed(1)} kWh</b>
                      ${adjustedTomorrow!==null?` • adaptive solar <b style="color:#ffbd3d">${adjustedTomorrow.toFixed(1)} kWh</b>`:''}
                      • reserve-only charge need <b style="color:#fff">${gridNeeded.toFixed(1)} kWh</b>
                      ${chargeCost!==null?` • estimated cost <b style="color:#fff">£${chargeCost.toFixed(2)}</b>${costIsReference?' using today’s cheap rate as a reference':''}`:''}
                      ${saving!==null&&saving>0&&gridNeeded>0.1?` • avoided peak-import value <b style="color:#55e58e">£${saving.toFixed(2)}</b>`:''}.
                    </div>

                    <div style="margin-top:9px;font-size:10px;line-height:1.45;color:rgba(255,255,255,.42);">
                      The modelled reserve need is an energy-security estimate, not the ECCO reserve setting and not a proposed TOU setting.
                      ${nextCheap?` Next published cheap window: ${nextCheap.start.toLocaleTimeString([],{hour:'2-digit',minute:'2-digit'})}–${nextCheap.end.toLocaleTimeString([],{hour:'2-digit',minute:'2-digit'})} at ${nextCheap.p.toFixed(2)}p/kWh.`:' Next-day cheap rates are not published yet.'}
                      Export arbitrage and battery degradation are still excluded.
                    </div>
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
                - grid-template-areas: '"i n" "body body"'
                - grid-template-columns: 32px 1fr
                - grid-template-rows: min-content 1fr
                - row-gap: 12px
              icon:
                - width: 24px
                - color: '#55e58e'
              name:
                - justify-self: start
                - font-size: 20px
                - font-weight: 700
                - color: rgba(255,255,255,0.92)
              custom_fields:
                body:
                  - width: 100%
                  - white-space: normal
                  - overflow: visible
                  - text-overflow: unset
                  - word-break: normal
                  - line-height: 1.45
            grid_options:
              columns: 32
              rows: 6

          # ---- OCTOPUS RATE GRAPH ----

  - title: Recommended
""")
DASHBOARD_22_OLD = _blk(r"""
                  const liveKw=loadW/1000;
                  const runKw=clamp(avgKw*.65+liveKw*.35,.15,5);
                  const projectedDaily=clamp(runKw*24,6,60);

                  const adjustedTomorrow=tomorrow!==null?tomorrow*factor*.95:null;
                  const morningBridge=runKw*4.5;
                  const reserveKwh=capKwh*.10;
                  const dailyDeficit=adjustedTomorrow!==null?Math.max(projectedDaily-adjustedTomorrow,0):0;
                  const requiredEnergy=clamp(morningBridge+reserveKwh+dailyDeficit,capKwh*.20,capKwh);
                  const minimumReserveTarget=clamp(requiredEnergy/capKwh*100,20,100);

                  const configuredTarget=Number(states['sensor.ecco_clock_dongle_ecco_timezone1_soc']?.state??100);

                  const rateSensors=sensors.filter(s=>
                    s.entity_id.includes('octopus_energy_electricity')&&
                    s.entity_id.includes('current_rate')
                  );
                  const imp=rateSensors.find(s=>!isExport(s));

                  const parseEvent=(needle)=>{
                    const ev=events.find(s=>
                      s.entity_id.includes('octopus_energy_electricity')&&
                      s.entity_id.includes(needle)&&!isExport(s)
                    );
                    const rs=Array.isArray(ev?.attributes?.rates)?ev.attributes.rates:[];
                    return rs.map(r=>({
                      start:new Date(r.start),end:new Date(r.end),
                      p:Number(r.value_inc_vat)*100
                    })).filter(r=>Number.isFinite(r.p)&&!isNaN(r.start)&&!isNaN(r.end))
                      .sort((a,b)=>a.start-b.start);
                  };

                  const todayRates=parseEvent('current_day_rates');
                  const nextRates=parseEvent('next_day_rates');
                  const nextRateCoverageHours=nextRates.reduce((sum,r)=>sum+Math.max((r.end-r.start)/3600000,0),0);
                  const nextRatesReady=nextRates.length>=6 && nextRateCoverageHours>=3;
                  const todayMin=todayRates.length?Math.min(...todayRates.map(r=>r.p)):
                    (imp?.attributes?.current_day_min_rate!=null?Number(imp.attributes.current_day_min_rate)*100:null);
                  const todayMax=todayRates.length?Math.max(...todayRates.map(r=>r.p)):
                    (imp?.attributes?.current_day_max_rate!=null?Number(imp.attributes.current_day_max_rate)*100:null);

                  const eps=.35;
                  const windowFor=(rates,target,after)=>{
                    if(!rates.length||target===null)return null;
                    const hits=rates.filter(r=>r.end>after&&Math.abs(r.p-target)<=eps);
                    if(!hits.length)return null;
                    const first=hits[0];
                    let end=first.end;
                    for(const r of hits.slice(1)){
                      if(Math.abs(r.start-end)<60000)end=r.end;else break;
                    }
                    return {start:first.start,end,p:target};
                  };

                  let nextCheap= todayMin!==null ? windowFor(todayRates,todayMin,now) : null;
                  if(!nextCheap&&nextRatesReady){
                    const nm=Math.min(...nextRates.map(r=>r.p));
                    nextCheap=windowFor(nextRates,nm,now);
                  }

                  // Battery level expected at the live configured charge-slot start.
                  const targetTimeRaw=states['sensor.ecco_config_charge_start_time']?.state;
                  const targetMatch=String(targetTimeRaw??'').match(/^(\d{1,2}):(\d{2})$/);
                  const targetHour=targetMatch?Number(targetMatch[1]):0;
                  const targetMinute=targetMatch?Number(targetMatch[2]):30;
                  const targetTime=`${String(targetHour).padStart(2,'0')}:${String(targetMinute).padStart(2,'0')}`;
                  const cheapStart=new Date(now);
                  cheapStart.setHours(targetHour,targetMinute,0,0);
                  if(cheapStart<=now)cheapStart.setDate(cheapStart.getDate()+1);
                  const hCheap=Math.max((cheapStart-now)/3600000,0);

                  // V2.1 (ovw2): never show a reserve projection or top-up advice from a battery reading that is not a number.
                  const socRaw=states['sensor.ecco_clock_dongle_ecco_battery_soc']?.state;
                  if(socRaw===undefined||['unknown','unavailable','none',''].includes(String(socRaw).toLowerCase())||!Number.isFinite(Number(socRaw))){
                    return `<div style="font-size:16px;font-weight:800;color:#aab4c3;">Battery data unavailable</div><div style="margin-top:6px;font-size:11px;line-height:1.5;color:rgba(255,255,255,.55);">No reserve projection or top-up advice is shown until the battery SOC reports again.</div>`;
                  }

                  // V2.1 (ovw2): the solar forecast is for the rest of the CURRENT calendar day; only the share that can arrive BEFORE the
                  // target may lift the SOC at the target (same rule as the ECCO Today card). Unknown sun times credit no solar at all.
                  const sunEntity=states['sun.sun'];
                  const solarShare=(()=>{
                    const set=sunEntity?.attributes?.next_setting?new Date(sunEntity.attributes.next_setting):null;
                    const rise=sunEntity?.attributes?.next_rising?new Date(sunEntity.attributes.next_rising):null;
                    if(!set||Number.isNaN(set.getTime()))return 0;
                    let from=null;
                    if(sunEntity.state==='above_horizon')from=now;
                    else if(rise&&!Number.isNaN(rise.getTime())&&rise.toDateString()===now.toDateString())from=rise;
                    if(from===null)return 0;
                    if(cheapStart>=set)return 1;
                    if(cheapStart<=from)return 0;
                    return (cheapStart-from)/(set-from);
                  })();
                  const targetDay=cheapStart.toDateString()===now.toDateString()?'today':'tomorrow';
                  const likelySolar=remaining!==null?remaining*factor*.95:0;
                  const predictedAt0035=remaining!==null
                    ? clamp(soc+((likelySolar*solarShare-runKw*hCheap)/capKwh)*100,0,100)
                    : soc;

                  // This is the extra energy needed for reserve/security only.
                  const batteryNeeded=Math.max(0,(minimumReserveTarget-predictedAt0035)/100*capKwh);
                  const gridNeeded=batteryNeeded/.94;

                  const nextCheapRate=nextCheap?.p ?? null;
                  const costRate=nextCheapRate ?? todayMin;
                  const costIsReference=nextCheapRate===null&&todayMin!==null;
                  const chargeCost=costRate!==null?gridNeeded*(costRate/100):null;
                  const avoidedValue=todayMax!==null?batteryNeeded*(todayMax/100):null;
                  const saving=chargeCost!==null&&avoidedValue!==null?avoidedValue-chargeCost:null;

                  const surplusPct=predictedAt0035-minimumReserveTarget;

                  let headline='Energy-reserve model says no top-up is needed';
                  let colour='#55e58e';
                  if(gridNeeded>0.2){
                    headline='Energy-reserve model recommends a cheap-rate top-up';
                    colour='#ffbd3d';
                  }else if(configuredTarget>minimumReserveTarget+15){
                    headline='Configured target is well above the modelled reserve need';
                    colour='#7ab8ff';
                  }

                  return `<div>
                    <div style="font-size:16px;font-weight:800;color:${colour};">${headline}</div>

                    <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:9px;margin-top:12px;">
                      <div style="text-align:center;padding:9px;border-radius:10px;background:rgba(255,255,255,.035);border:1px solid rgba(255,255,255,.06);">
                        <div style="font-size:10px;color:rgba(255,255,255,.48);">Configured TOU target</div>
                        <div style="font-size:22px;font-weight:800;color:#b8adff;">${Number.isFinite(configuredTarget)?configuredTarget.toFixed(0):'--'}%</div>
                      </div>
                      <div style="text-align:center;padding:9px;border-radius:10px;background:rgba(255,255,255,.035);border:1px solid rgba(255,255,255,.06);">
                        <div style="font-size:10px;color:rgba(255,255,255,.48);">Modelled reserve need</div>
                        <div style="font-size:22px;font-weight:800;color:#55e58e;">${minimumReserveTarget.toFixed(0)}%</div>
                      </div>
                      <div style="text-align:center;padding:9px;border-radius:10px;background:rgba(255,255,255,.035);border:1px solid rgba(255,255,255,.06);">
                        <div style="font-size:10px;color:rgba(255,255,255,.48);">Expected at ${targetTime} ${targetDay}</div>
                        <div style="font-size:22px;font-weight:800;color:#ffbd3d;">${predictedAt0035.toFixed(0)}%</div>
                      </div>
                    </div>

                    <div style="margin-top:11px;font-size:11px;line-height:1.55;color:rgba(255,255,255,.60);">
                      Reserve margin at ${targetTime} <b style="color:${surplusPct>=0?'#55e58e':'#ff6376'}">${surplusPct>=0?'+':''}${surplusPct.toFixed(0)} points</b>
                      • next-day load model <b style="color:#fff">${projectedDaily.toFixed(1)} kWh</b>
                      ${adjustedTomorrow!==null?` • adaptive solar <b style="color:#ffbd3d">${adjustedTomorrow.toFixed(1)} kWh</b>`:''}
                      • reserve-only charge need <b style="color:#fff">${gridNeeded.toFixed(1)} kWh</b>
                      ${chargeCost!==null?` • estimated cost <b style="color:#fff">£${chargeCost.toFixed(2)}</b>${costIsReference?' using today’s cheap rate as a reference':''}`:''}
                      ${saving!==null&&saving>0&&gridNeeded>0.1?` • avoided peak-import value <b style="color:#55e58e">£${saving.toFixed(2)}</b>`:''}.
                    </div>

                    <div style="margin-top:9px;font-size:10px;line-height:1.45;color:rgba(255,255,255,.42);">
                      The modelled reserve need is an energy-security estimate, not the ECCO reserve setting and not a proposed TOU setting.
                      ${nextCheap?` Next published cheap window: ${nextCheap.start.toLocaleTimeString([],{hour:'2-digit',minute:'2-digit'})}–${nextCheap.end.toLocaleTimeString([],{hour:'2-digit',minute:'2-digit'})} at ${nextCheap.p.toFixed(2)}p/kWh.`:' Next-day cheap rates are not published yet.'}
                      Export arbitrage and battery degradation are still excluded.
                    </div>
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
                - grid-template-areas: '"i n" "body body"'
                - grid-template-columns: 32px 1fr
                - grid-template-rows: min-content 1fr
                - row-gap: 12px
              icon:
                - width: 24px
                - color: '#55e58e'
              name:
                - justify-self: start
                - font-size: 20px
                - font-weight: 700
                - color: rgba(255,255,255,0.92)
              custom_fields:
                body:
                  - width: 100%
                  - white-space: normal
                  - overflow: visible
                  - text-overflow: unset
                  - word-break: normal
                  - line-height: 1.45
            grid_options:
              columns: 32
              rows: 6

          # ---- OCTOPUS RATE GRAPH ----

  - title: System
""")
DASHBOARD_22_NEW = _blk(r"""
                  const liveKw=Number.isFinite(loadW)?loadW/1000:avgKw;   // hd1: house load unavailable -> the average alone
                  const runKw=clamp(avgKw*.65+liveKw*.35,.15,5);
                  const projectedDaily=clamp(runKw*24,6,60);

                  const adjustedTomorrow=tomorrow!==null?tomorrow*factor*.95:null;
                  const morningBridge=runKw*4.5;
                  const reserveKwh=capKwh*.10;
                  const dailyDeficit=adjustedTomorrow!==null?Math.max(projectedDaily-adjustedTomorrow,0):0;
                  const requiredEnergy=clamp(morningBridge+reserveKwh+dailyDeficit,capKwh*.20,capKwh);
                  const minimumReserveTarget=clamp(requiredEnergy/capKwh*100,20,100);

                  const configuredTarget=Number(states['sensor.ecco_clock_dongle_ecco_timezone1_soc']?.state??100);

                  const rateSensors=sensors.filter(s=>
                    s.entity_id.includes('octopus_energy_electricity')&&
                    s.entity_id.includes('current_rate')
                  );
                  const imp=rateSensors.find(s=>!isExport(s));

                  const parseEvent=(needle)=>{
                    const ev=events.find(s=>
                      s.entity_id.includes('octopus_energy_electricity')&&
                      s.entity_id.includes(needle)&&!isExport(s)
                    );
                    const rs=Array.isArray(ev?.attributes?.rates)?ev.attributes.rates:[];
                    return rs.map(r=>({
                      start:new Date(r.start),end:new Date(r.end),
                      p:Number(r.value_inc_vat)*100
                    })).filter(r=>Number.isFinite(r.p)&&!isNaN(r.start)&&!isNaN(r.end))
                      .sort((a,b)=>a.start-b.start);
                  };

                  const todayRates=parseEvent('current_day_rates');
                  const nextRates=parseEvent('next_day_rates');
                  const nextRateCoverageHours=nextRates.reduce((sum,r)=>sum+Math.max((r.end-r.start)/3600000,0),0);
                  const nextRatesReady=nextRates.length>=6 && nextRateCoverageHours>=3;
                  const todayMin=todayRates.length?Math.min(...todayRates.map(r=>r.p)):
                    (imp?.attributes?.current_day_min_rate!=null?Number(imp.attributes.current_day_min_rate)*100:null);
                  const todayMax=todayRates.length?Math.max(...todayRates.map(r=>r.p)):
                    (imp?.attributes?.current_day_max_rate!=null?Number(imp.attributes.current_day_max_rate)*100:null);

                  const eps=.35;
                  const windowFor=(rates,target,after)=>{
                    if(!rates.length||target===null)return null;
                    const hits=rates.filter(r=>r.end>after&&Math.abs(r.p-target)<=eps);
                    if(!hits.length)return null;
                    const first=hits[0];
                    let end=first.end;
                    for(const r of hits.slice(1)){
                      if(Math.abs(r.start-end)<60000)end=r.end;else break;
                    }
                    return {start:first.start,end,p:target};
                  };

                  let nextCheap= todayMin!==null ? windowFor(todayRates,todayMin,now) : null;
                  if(!nextCheap&&nextRatesReady){
                    const nm=Math.min(...nextRates.map(r=>r.p));
                    nextCheap=windowFor(nextRates,nm,now);
                  }

                  // Battery level expected at the live configured charge-slot start.
                  const targetTimeRaw=states['sensor.ecco_config_charge_start_time']?.state;
                  const targetMatch=String(targetTimeRaw??'').match(/^(\d{1,2}):(\d{2})$/);
                  const targetHour=targetMatch?Number(targetMatch[1]):0;
                  const targetMinute=targetMatch?Number(targetMatch[2]):30;
                  const targetTime=`${String(targetHour).padStart(2,'0')}:${String(targetMinute).padStart(2,'0')}`;
                  const cheapStart=new Date(now);
                  cheapStart.setHours(targetHour,targetMinute,0,0);
                  if(cheapStart<=now)cheapStart.setDate(cheapStart.getDate()+1);
                  const hCheap=Math.max((cheapStart-now)/3600000,0);

                  // V2.1 (ovw2): never show a reserve projection or top-up advice from a battery reading that is not a number.
                  const socRaw=states['sensor.ecco_clock_dongle_ecco_battery_soc']?.state;
                  if(socRaw===undefined||['unknown','unavailable','none',''].includes(String(socRaw).toLowerCase())||!Number.isFinite(Number(socRaw))){
                    return `<div style="font-size:16px;font-weight:800;color:#aab4c3;">Battery data unavailable</div><div style="margin-top:6px;font-size:11px;line-height:1.5;color:rgba(255,255,255,.55);">No reserve projection or top-up advice is shown until the battery SOC reports again.</div>`;
                  }

                  // V2.1 (ovw2): the solar forecast is for the rest of the CURRENT calendar day; only the share that can arrive BEFORE the
                  // target may lift the SOC at the target (same rule as the ECCO Today card). Unknown sun times credit no solar at all.
                  const sunEntity=states['sun.sun'];
                  const solarShare=(()=>{
                    const set=sunEntity?.attributes?.next_setting?new Date(sunEntity.attributes.next_setting):null;
                    const rise=sunEntity?.attributes?.next_rising?new Date(sunEntity.attributes.next_rising):null;
                    if(!set||Number.isNaN(set.getTime()))return 0;
                    let from=null;
                    if(sunEntity.state==='above_horizon')from=now;
                    else if(rise&&!Number.isNaN(rise.getTime())&&rise.toDateString()===now.toDateString())from=rise;
                    if(from===null)return 0;
                    if(cheapStart>=set)return 1;
                    if(cheapStart<=from)return 0;
                    return (cheapStart-from)/(set-from);
                  })();
                  const targetDay=cheapStart.toDateString()===now.toDateString()?'today':'tomorrow';
                  const likelySolar=remaining!==null?remaining*factor*.95:0;
                  const predictedAt0035=remaining!==null
                    ? clamp(soc+((likelySolar*solarShare-runKw*hCheap)/capKwh)*100,0,100)
                    : soc;

                  // This is the extra energy needed for reserve/security only.
                  const batteryNeeded=Math.max(0,(minimumReserveTarget-predictedAt0035)/100*capKwh);
                  const gridNeeded=batteryNeeded/.94;

                  const nextCheapRate=nextCheap?.p ?? null;
                  const costRate=nextCheapRate ?? todayMin;
                  const costIsReference=nextCheapRate===null&&todayMin!==null;
                  const chargeCost=costRate!==null?gridNeeded*(costRate/100):null;
                  const avoidedValue=todayMax!==null?batteryNeeded*(todayMax/100):null;
                  const saving=chargeCost!==null&&avoidedValue!==null?avoidedValue-chargeCost:null;

                  const surplusPct=predictedAt0035-minimumReserveTarget;

                  let headline='Energy-reserve model says no top-up is needed';
                  let colour='#55e58e';
                  if(gridNeeded>0.2){
                    headline='Energy-reserve model recommends a cheap-rate top-up';
                    colour='#ffbd3d';
                  }else if(configuredTarget>minimumReserveTarget+15){
                    headline='Configured target is well above the modelled reserve need';
                    colour='#7ab8ff';
                  }

                  return `<div>
                    <div style="font-size:16px;font-weight:800;color:${colour};">${headline}</div>

                    <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:9px;margin-top:12px;">
                      <div style="text-align:center;padding:9px;border-radius:10px;background:rgba(255,255,255,.035);border:1px solid rgba(255,255,255,.06);">
                        <div style="font-size:10px;color:rgba(255,255,255,.48);">Configured TOU target</div>
                        <div style="font-size:22px;font-weight:800;color:#b8adff;">${Number.isFinite(configuredTarget)?configuredTarget.toFixed(0):'--'}%</div>
                      </div>
                      <div style="text-align:center;padding:9px;border-radius:10px;background:rgba(255,255,255,.035);border:1px solid rgba(255,255,255,.06);">
                        <div style="font-size:10px;color:rgba(255,255,255,.48);">Modelled reserve need</div>
                        <div style="font-size:22px;font-weight:800;color:#55e58e;">${minimumReserveTarget.toFixed(0)}%</div>
                      </div>
                      <div style="text-align:center;padding:9px;border-radius:10px;background:rgba(255,255,255,.035);border:1px solid rgba(255,255,255,.06);">
                        <div style="font-size:10px;color:rgba(255,255,255,.48);">Expected at ${targetTime} ${targetDay}</div>
                        <div style="font-size:22px;font-weight:800;color:#ffbd3d;">${predictedAt0035.toFixed(0)}%</div>
                      </div>
                    </div>

                    <div style="margin-top:11px;font-size:11px;line-height:1.55;color:rgba(255,255,255,.60);">
                      Reserve margin at ${targetTime} <b style="color:${surplusPct>=0?'#55e58e':'#ff6376'}">${surplusPct>=0?'+':''}${surplusPct.toFixed(0)} points</b>
                      • next-day load model <b style="color:#fff">${projectedDaily.toFixed(1)} kWh</b>
                      ${adjustedTomorrow!==null?` • adaptive solar <b style="color:#ffbd3d">${adjustedTomorrow.toFixed(1)} kWh</b>`:''}
                      • reserve-only charge need <b style="color:#fff">${gridNeeded.toFixed(1)} kWh</b>
                      ${chargeCost!==null?` • estimated cost <b style="color:#fff">£${chargeCost.toFixed(2)}</b>${costIsReference?' using today’s cheap rate as a reference':''}`:''}
                      ${saving!==null&&saving>0&&gridNeeded>0.1?` • avoided peak-import value <b style="color:#55e58e">£${saving.toFixed(2)}</b>`:''}.
                    </div>

                    <div style="margin-top:9px;font-size:10px;line-height:1.45;color:rgba(255,255,255,.42);">
                      The modelled reserve need is an energy-security estimate, not the ECCO reserve setting and not a proposed TOU setting.
                      ${nextCheap?` Next published cheap window: ${nextCheap.start.toLocaleTimeString([],{hour:'2-digit',minute:'2-digit'})}–${nextCheap.end.toLocaleTimeString([],{hour:'2-digit',minute:'2-digit'})} at ${nextCheap.p.toFixed(2)}p/kWh.`:' Next-day cheap rates are not published yet.'}
                      Export arbitrage and battery degradation are still excluded.
                    </div>
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
                - grid-template-areas: '"i n" "body body"'
                - grid-template-columns: 32px 1fr
                - grid-template-rows: min-content 1fr
                - row-gap: 12px
              icon:
                - width: 24px
                - color: '#55e58e'
              name:
                - justify-self: start
                - font-size: 20px
                - font-weight: 700
                - color: rgba(255,255,255,0.92)
              custom_fields:
                body:
                  - width: 100%
                  - white-space: normal
                  - overflow: visible
                  - text-overflow: unset
                  - word-break: normal
                  - line-height: 1.45
            grid_options:
              columns: 32
              rows: 6

          # ---- OCTOPUS RATE GRAPH ----

  - title: System
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
    (DASHBOARD_16_OLD, DASHBOARD_16_NEW),
    (DASHBOARD_17_OLD, DASHBOARD_17_NEW),
    (DASHBOARD_18_OLD, DASHBOARD_18_NEW),
    (DASHBOARD_19_OLD, DASHBOARD_19_NEW),
    (DASHBOARD_20_OLD, DASHBOARD_20_NEW),
    (DASHBOARD_21_OLD, DASHBOARD_21_NEW),
    (DASHBOARD_22_OLD, DASHBOARD_22_NEW),
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
