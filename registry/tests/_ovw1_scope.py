"""ovw1 (ECCO Overview V2: the Overview view rebuilt as nine sections) change scope: exactly what ovw1 changes in the files the pub0
export froze, and its exact inverse.

Same technique as the earlier post-export scope modules: every verbatim edit is held HERE as the single source of truth, as an exact
(before, after) pair generated from the real diff and round-trip-checked, and each reverter raises unless each of its edits is present
exactly once. The post-export chain entry `ovw1` (registry/tests/_scope_chain.py POST_EXPORT_ENTRIES, appended last after acfg1;
registry/tests/_pex.py) carries one frozen reverter per edited frozen file and no chain reverter (the manifest is untouched).

WHAT ovw1 IS. The dashboard's Overview view is rebuilt as nine `type: grid` sections (column spans 4, 4, 3, 1, 2, 2, 3, 1, 4): the
compact status banner (the hero, its JavaScript state machine, pills and vocabulary kept verbatim, now also reading the Dump to Grid
lease states), the Weather & Solar card's solar strip, the Energy Flow card beside a slim Grid Status / Current Plan / compact daily
forecast / Tariff column, the Energy Actions card in its new `layout: tabbed` presentation followed directly by the Known-Good Profile
bar, decision support (ECCO Today, battery estimate, scheduled sessions), the Power Flow chart beside an electrical detail list, and one
merged System Health card. The Energy Actions card gains the presentation-only `layout` option (src/trackSelection.ts, pure, no regex
literal, no runtime import; test/trackSelection.test.ts) and its bundle is rebuilt. Display only: ZERO firmware, Home Assistant package,
deployment, registry, Intelligence or ecco_core change; ZERO Modbus operation (64 reads / 52 writes unchanged); no new service call
(the card's callService sites and (domain, service) pairs are unchanged); no manifest stanza.

FROZEN edits (PEX).
  pub0 targets
    home-assistant/dashboards/ecco_pro.yaml                         the v7.20.0 header note; the whole Overview view block (one pair)
    home-assistant/tests/test_ecco_fallback_packages.py             [19] the folder pin skips the files a post-export entry added
    home-assistant/tests/test_ecco_shadow_check_ux.py               [7] the same
    registry/tests/test_fallback_recovery_dashboard.py              FB-B3: the same
  enrolled (owner decision O3; their pub0 state is their 883068d hash)
    VERSION.yaml                                                    dashboard 7.20.0, staged (tested_in_home_assistant stays false)
    frontend/ecco-energy-actions-card/dist/ecco-energy-actions-card.js   the rebuilt bundle (enrolled by esb1)
    frontend/ecco-energy-actions-card/src/ecco-energy-actions-card.ts    the tabbed layout (NEW enrolment, O3 amendment 2026-10-09)
    frontend/ecco-energy-actions-card/src/config.ts                 the `layout` config key (NEW enrolment)
    frontend/ecco-energy-actions-card/README.md                     the Layouts section (NEW enrolment)
  The three suites' pin VALUE (57c97982...) and lic0's FOLDER_PRE / FOLDER_POST are unchanged: every changed tracked card file is
  enrolled and read AS OF pub0, and the two added card files are skipped. Each suite edit is one pair: the two routing lines inserted
  after the folder loop's `for` line. No pair quotes the pin line's pub0 or lic0 call, so the hash-pinned PUB0 gate's private-view
  ledger and the lic0 PINNERS ledger are unaffected; the PEX ledger (test_pex_transition.py) declares the routing lines this module
  quotes.

NOT frozen (ordinary edits, nothing to declare): registry/tests/test_lic0_transition.py ([3] skips the added files the same way),
registry/tests/test_pex_transition.py (the O3 amendment and the ledger), registry/tests/_pex.py (ENROLLED), the Weather & Solar card
(frontend/ecco-weather-solar-card, not frozen) and its suite tools/tests/test_weather_solar_card.py, CHANGELOG.md and
docs/dev/post-export-edit-layer.md. Added: this module, registry/tests/test_ovw1_transition.py (the live successor pins),
frontend/ecco-energy-actions-card/src/trackSelection.ts and frontend/ecco-energy-actions-card/test/trackSelection.test.ts.

This module imports no other scope module, not _scope_chain (the chain imports it) and not _pex. No I/O.
"""

from __future__ import annotations

import hashlib

# Public main the change is based on (ACFG1 merged).
BASE_COMMIT = "42baa20a75b33bbc4e12ca1202eebbccc0257b50"

ADDED_FILES = frozenset({
    "registry/tests/_ovw1_scope.py",
    "registry/tests/test_ovw1_transition.py",
    "frontend/ecco-energy-actions-card/src/trackSelection.ts",
    "frontend/ecco-energy-actions-card/test/trackSelection.test.ts",
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
        raise AssertionError(f"ovw1 scope: {what} must be {state} exactly once, found {n}x: {find[:70]!r}")
    i = text.index(find)
    return text[:i] + put + text[i + len(find):]


def _revert(text: str, edits: tuple, what: str) -> str:
    out = text
    for k, (before, after) in reversed(list(enumerate(edits))):
        out = _swap(out, after, before, f"{what} edit {k}", "present")
    for k, (before, _after) in enumerate(edits):
        n = out.count(before)
        if n != 1:
            raise AssertionError(f"ovw1 scope: {what} anchor {k} must be unique once the edits are removed, found {n}x")
    return out


def _apply(text: str, edits: tuple, what: str) -> str:
    out = text
    for k, (before, after) in enumerate(edits):
        if after in out:
            raise AssertionError(f"ovw1 scope: {what} edit {k} is already present")
        out = _swap(out, before, after, f"{what} anchor {k}", "found")
    return out


# ---- (PEX frozen edit) home-assistant/dashboards/ecco_pro.yaml ---------------------------------------------------------------
DASHBOARD_REL = "home-assistant/dashboards/ecco_pro.yaml"
# The v7.20.0 header note, then the whole Overview view block (from its title line to the line before the Weather & Solar view).
DASHBOARD_0_OLD = _blk(r"""
# its own.
# Built for Home Assistant Sections view + Flexible Horseshoe Card + Sunsynk Power Flow Card (secondary/detail views) + ApexCharts + card-mod
""")
DASHBOARD_0_NEW = _blk(r"""
# its own.
# v7.20.0 (OVW1, STAGED / NOT LIVE-PROVEN) rebuilds the Overview as nine sections: a compact status banner (now also
# reading the Dump to Grid lease states), the Weather & Solar card's solar strip and compact daily layouts, the Energy
# Flow card beside a slim Grid Status / Current Plan / Tariff column, the Energy Actions card in its tabbed layout with
# the Known-Good Profile bar, decision support (ECCO Today, battery estimate, scheduled sessions), the Power Flow chart
# beside an electrical detail list, and one merged System Health card. Display only: no control, no firmware change.
# Built for Home Assistant Sections view + Flexible Horseshoe Card + Sunsynk Power Flow Card (secondary/detail views) + ApexCharts + card-mod
""")
DASHBOARD_1_OLD = _blk(r"""
  - title: Overview
    path: ecco-overview
    icon: mdi:view-dashboard
    type: sections
    max_columns: 4
    dense_section_placement: true
    sections:
      - type: grid
        column_span: 4
        cards:
          - type: heading
            heading: ECCO Pro • Overview
            heading_style: title
            icon: mdi:view-dashboard
            badges:
              - type: entity
                entity: binary_sensor.ecco_clock_dongle_telemetry_online
                name: Telemetry
                show_state: true
                color: green
              - type: entity
                entity: binary_sensor.ecco_clock_dongle_configuration_online
                name: Config
                show_state: true
                color: green
              - type: entity
                entity: binary_sensor.ecco_clock_dongle_ntp_synced
                name: NTP
                show_state: true
                color: green
            grid_options:
              columns: 48
              rows: auto

          # ---- ECCO STATUS HERO — READ-ONLY MONITORING ----
          # Visual summary only. This card is NOT a control-readiness gate and
          # does not call services or write any inverter setting.
          - type: custom:button-card
            section_mode: true
            name: ECCO Pro
            icon: mdi:home-lightning-bolt
            show_name: true
            show_icon: true
            show_state: false
            tap_action:
              action: none
            custom_fields:
              body: >
                [[[
                  const get = id => states[id]?.state ?? 'unknown';
                  const num = id => {
                    const v = Number(get(id));
                    return Number.isFinite(v) ? v : null;
                  };
                  const unknown = v => ['unknown','unavailable','none',''].includes(String(v).toLowerCase());
                  const comm = get('sensor.ecco_health_communications');
                  const runtime = get('sensor.ecco_health_runtime_configuration');
                  const telemetry = get('binary_sensor.ecco_clock_dongle_telemetry_online');
                  const configOnline = get('binary_sensor.ecco_clock_dongle_configuration_online');
                  const ntp = get('binary_sensor.ecco_clock_dongle_ntp_synced');
                  const cache = get('binary_sensor.ecco_clock_dongle_manual_configuration_raw_cache_valid');
                  const inverter = get('sensor.ecco_clock_dongle_ecco_inverter_system_state');
                  const warning = get('sensor.ecco_clock_dongle_ecco_inverter_warning');
                  const fault = get('sensor.ecco_clock_dongle_ecco_inverter_fault');
                  const manualState = get('binary_sensor.ecco_clock_dongle_manual_write_in_progress');
                  const rtcState = get('binary_sensor.ecco_clock_dongle_rtc_correction_in_progress');
                  const freeOpState = get('binary_sensor.ecco_clock_dongle_free_power_operation_in_progress');
                  const freeActiveState = get('binary_sensor.ecco_clock_dongle_free_power_active');
                  const manualBusy = manualState === 'on';
                  const rtcBusy = rtcState === 'on';
                  const freeBusy = freeOpState === 'on';
                  const freeActive = freeActiveState === 'on';
                  const snapshot = get('binary_sensor.ecco_clock_dongle_free_power_snapshot_valid');
                  const snapshotPending = snapshot === 'on' && !freeActive && !freeBusy;
                  // FB-B3: display words only (sensor.ecco_supervision_status / sensor.ecco_fallback_status).
                  // Deliberately NOT in `required` (a fallback Unknown must not turn the headline into
                  // STATUS PARTIAL) and only supervision Lost is hardAttention; fallback states are not.
                  const sup = get('sensor.ecco_supervision_status');
                  const fb = get('sensor.ecco_fallback_status');

                  const required = [comm,runtime,telemetry,configOnline,ntp,cache,inverter,warning,fault,manualState,rtcState,freeOpState,freeActiveState,snapshot];
                  const hasUnknown = required.some(unknown);
                  const hardAttention =
                    comm !== 'HEALTHY' ||
                    runtime !== 'HEALTHY' ||
                    telemetry !== 'on' ||
                    configOnline !== 'on' ||
                    ntp !== 'on' ||
                    cache !== 'on' ||
                    String(inverter).toLowerCase() !== 'normal' ||
                    warning !== '00000000' ||
                    fault !== '0000000000000000' ||
                    snapshotPending ||
                    sup === 'Lost';
                  const busy = manualBusy || rtcBusy || freeBusy || freeActive;

                  let headline, subline, colour, bg, border, icon;
                  if (hasUnknown) {
                    headline = 'STATUS PARTIAL';
                    subline = 'One or more monitoring inputs are unavailable';
                    colour = '#aab4c3';
                    bg = 'rgba(170,180,195,.08)';
                    border = 'rgba(170,180,195,.22)';
                    icon = 'mdi:help-circle-outline';
                  } else if (hardAttention) {
                    headline = 'ATTENTION';
                    subline = 'A monitored subsystem needs checking';
                    colour = '#ffbd3d';
                    bg = 'rgba(255,189,61,.10)';
                    border = 'rgba(255,189,61,.30)';
                    icon = 'mdi:alert-outline';
                  } else if (busy) {
                    headline = freeActive ? 'FREE POWER ACTIVE' : 'OPERATION IN PROGRESS';
                    subline = 'ECCO is healthy and a legitimate transaction is active';
                    colour = '#66b3ff';
                    bg = 'rgba(102,179,255,.10)';
                    border = 'rgba(102,179,255,.30)';
                    icon = freeActive ? 'mdi:flash' : 'mdi:progress-clock';
                  } else {
                    headline = 'SYSTEMS NOMINAL';
                    subline = 'Live monitoring inputs are healthy';
                    colour = '#55e58e';
                    bg = 'rgba(85,229,142,.08)';
                    border = 'rgba(85,229,142,.24)';
                    icon = 'mdi:shield-check';
                  }

                  const pill = (label, value, tone='good') => {
                    const tones = {
                      good: ['#55e58e','rgba(85,229,142,.08)','rgba(85,229,142,.20)'],
                      info: ['#66b3ff','rgba(102,179,255,.08)','rgba(102,179,255,.20)'],
                      warn: ['#ffbd3d','rgba(255,189,61,.08)','rgba(255,189,61,.22)'],
                      muted: ['#aab4c3','rgba(170,180,195,.06)','rgba(170,180,195,.15)']
                    };
                    const t = tones[tone] || tones.muted;
                    return `<div style="padding:8px 10px;border-radius:11px;background:${t[1]};border:1px solid ${t[2]};min-width:0;">
                      <div style="font-size:9px;letter-spacing:.55px;color:rgba(255,255,255,.46);font-weight:800;">${label}</div>
                      <div style="margin-top:2px;color:${t[0]};font-size:12px;font-weight:800;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">${value}</div>
                    </div>`;
                  };

                  const chipState = (ok, active=false, unknownState=false) =>
                    unknownState ? ['UNKNOWN','muted'] : active ? ['ACTIVE','info'] : ok ? ['HEALTHY','good'] : ['CHECK','warn'];

                  const commChip = chipState(comm === 'HEALTHY', false, unknown(comm));
                  const runtimeChip = chipState(runtime === 'HEALTHY', false, unknown(runtime));
                  const rtcChip = chipState(ntp === 'on', rtcBusy, unknown(ntp) || unknown(rtcState));
                  const invChip = chipState(String(inverter).toLowerCase() === 'normal' && warning === '00000000' && fault === '0000000000000000', false, unknown(inverter) || unknown(warning) || unknown(fault));
                  const txUnknown = unknown(manualState) || unknown(freeOpState) || unknown(freeActiveState);
                  const txChip = chipState(true, manualBusy || freeBusy || freeActive, txUnknown);
                  const recoveryChip = chipState(!snapshotPending, false, unknown(snapshot) || unknown(freeActiveState));
                  const supChips = {'Healthy': ['HEALTHY', 'good'], 'Recovering': ['RECOVERING', 'info'], 'Awaiting Heartbeat': ['AWAITING', 'muted'], 'Suspect': ['SUSPECT', 'warn'], 'Lost': ['LOST', 'warn']};
                  const supChip = supChips[sup] || ['UNKNOWN', 'muted'];
                  const fbChips = {'Ready': ['READY', 'good'], 'Drifted': ['DRIFTED', 'warn'], 'Not Captured': ['NOT SAVED', 'muted'], 'Invalidated': ['INVALIDATED', 'muted'], 'Blocked': ['BLOCKED', 'warn'], 'Shadow Recovery': ['SHADOW', 'warn']};
                  const fbChip = fbChips[fb] || ['UNKNOWN', 'muted'];

                  const soc = num('sensor.ecco_clock_dongle_ecco_battery_soc');
                  const pv = num('sensor.ecco_clock_dongle_ecco_pv_power');
                  const load = num('sensor.ecco_clock_dongle_ecco_load_power');
                  const grid = num('sensor.ecco_clock_dongle_ecco_grid_power_ct_clamp');
                  const kw = v => v === null ? '--' : (Math.abs(v)/1000).toFixed(2) + ' kW';
                  const gridText = grid === null ? '--' : Math.abs(grid) <= 40 ? 'Neutral' : grid > 0 ? `Import ${kw(grid)}` : `Export ${kw(grid)}`;

                  return `<div>
                    <div style="display:flex;align-items:center;justify-content:space-between;gap:14px;padding:14px 15px;border-radius:15px;background:${bg};border:1px solid ${border};">
                      <div style="display:flex;align-items:center;gap:12px;min-width:0;">
                        <ha-icon icon="${icon}" style="width:30px;height:30px;color:${colour};flex:0 0 auto;"></ha-icon>
                        <div style="min-width:0;">
                          <div style="font-size:26px;font-weight:900;letter-spacing:.25px;color:${colour};">${headline}</div>
                          <div style="font-size:12px;color:rgba(255,255,255,.62);margin-top:2px;">${subline}</div>
                        </div>
                      </div>
                      <div style="font-size:10px;font-weight:800;letter-spacing:.45px;color:rgba(255,255,255,.42);text-align:right;line-height:1.4;">
                        MONITORING ONLY<br>NOT A CONTROL GATE
                      </div>
                    </div>

                    <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(105px,1fr));gap:7px;margin-top:9px;">
                      ${pill('COMMS', commChip[0], commChip[1])}
                      ${pill('RUNTIME CONFIG', runtimeChip[0], runtimeChip[1])}
                      ${pill('RTC / NTP', rtcChip[0], rtcChip[1])}
                      ${pill('INVERTER', invChip[0], invChip[1])}
                      ${pill('TRANSACTIONS', txChip[0], txChip[1])}
                      ${pill('RECOVERY', recoveryChip[0], recoveryChip[1])}
                      ${pill('SUPERVISION', supChip[0], supChip[1])}
                      ${pill('FALLBACK', fbChip[0], fbChip[1])}
                    </div>

                    <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:7px;margin-top:9px;">
                      <div style="padding:9px 10px;border-radius:11px;background:rgba(255,255,255,.035);">
                        <div style="font-size:9px;color:rgba(255,255,255,.42);font-weight:800;letter-spacing:.5px;">BATTERY</div>
                        <div style="font-size:17px;color:#fff;font-weight:800;margin-top:2px;">${soc === null ? '--' : soc.toFixed(0) + '%'}</div>
                      </div>
                      <div style="padding:9px 10px;border-radius:11px;background:rgba(255,255,255,.035);">
                        <div style="font-size:9px;color:rgba(255,255,255,.42);font-weight:800;letter-spacing:.5px;">SOLAR</div>
                        <div style="font-size:17px;color:#fff;font-weight:800;margin-top:2px;">${kw(pv)}</div>
                      </div>
                      <div style="padding:9px 10px;border-radius:11px;background:rgba(255,255,255,.035);">
                        <div style="font-size:9px;color:rgba(255,255,255,.42);font-weight:800;letter-spacing:.5px;">HOUSE</div>
                        <div style="font-size:17px;color:#fff;font-weight:800;margin-top:2px;">${kw(load)}</div>
                      </div>
                      <div style="padding:9px 10px;border-radius:11px;background:rgba(255,255,255,.035);">
                        <div style="font-size:9px;color:rgba(255,255,255,.42);font-weight:800;letter-spacing:.5px;">GRID</div>
                        <div style="font-size:17px;color:#fff;font-weight:800;margin-top:2px;">${gridText}</div>
                      </div>
                    </div>
                  </div>`;
                ]]]
            styles:
              card:
                - border-radius: 22px
                - padding: 17px 18px
                - background: linear-gradient(145deg, rgba(20,28,45,0.99), rgba(10,15,27,0.99))
                - border: 1px solid rgba(255,255,255,0.08)
                - box-shadow: 0 14px 38px rgba(0,0,0,0.25)
              grid:
                - grid-template-areas: '"i n" "body body"'
                - grid-template-columns: 38px 1fr
                - grid-template-rows: min-content 1fr
                - row-gap: 10px
              icon:
                - width: 27px
                - color: '#8f7cff'
              name:
                - justify-self: start
                - align-self: center
                - font-size: 21px
                - font-weight: 800
                - color: rgba(255,255,255,0.94)
              custom_fields:
                body:
                  - justify-self: stretch
                  - align-self: start
                  - width: 100%
            grid_options:
              columns: 48
              rows: 5

          # ---- LIVE ENERGY FLOW — PRIMARY OVERVIEW ----
          - type: custom:ecco-energy-flow-card
            title: ECCO Energy Flow

            nodes:
              solar:
                - label: Array 1
                  power: sensor.ecco_clock_dongle_ecco_pv1_power
                - label: Array 2
                  power: sensor.ecco_clock_dongle_ecco_pv2_power
              solar_total: sensor.ecco_pv_power

              inverter:
                power: sensor.ecco_clock_dongle_ecco_inverter_output_power
                state: sensor.ecco_clock_dongle_ecco_inverter_system_state

              home:
                power: sensor.ecco_house_power

              battery:
                power: sensor.ecco_clock_dongle_ecco_battery_output_power
                soc: sensor.ecco_battery_soc
                power_sign: discharge_positive

              grid:
                power: sensor.ecco_grid_power
                power_sign: import_positive

            today:
              solar: sensor.ecco_clock_dongle_ecco_day_pv_energy
              load: sensor.ecco_clock_dongle_ecco_day_load_energy
              import: sensor.ecco_clock_dongle_ecco_day_grid_import
              export: sensor.ecco_clock_dongle_ecco_day_grid_export
              battery_charge: sensor.ecco_clock_dongle_ecco_day_battery_charge
              battery_discharge: sensor.ecco_clock_dongle_ecco_day_battery_discharge

            inverter_details:
              grid_voltage: sensor.ecco_clock_dongle_ecco_grid_voltage_l1
              ac_temperature: sensor.ecco_clock_dongle_ecco_temperature_ac_transformer
              dc_temperature: sensor.ecco_clock_dongle_ecco_temperature_dc_transformer
              grid_connected: binary_sensor.ecco_clock_dongle_ecco_grid_connected
              frequency: sensor.ecco_clock_dongle_ecco_grid_frequency

            features:
              self_sufficiency: false
              solar_contribution: true
              animate_flow: true
              compact_today: true
              show_details_panel: false

            format:
              precision: 2
              energy_precision: 1
              power_unit: auto

            grid_options:
              columns: 32
              rows: auto
            card_mod:
              style: |
                ha-card {
                  border: 1px solid rgba(255,255,255,0.08);
                  box-shadow: 0 12px 32px rgba(0,0,0,0.22);
                }


          # ---- GRID STATUS + CURRENT PLAN (right-hand stack) ----
          - type: vertical-stack
            grid_options:
              columns: 16
              rows: auto
            cards:
              # ---- GRID / OUTAGE STATUS ----
              - type: custom:button-card
                section_mode: true
                name: Grid Status
                icon: mdi:transmission-tower
                show_name: true
                show_icon: true
                show_state: false
                tap_action:
                  action: none
                custom_fields:
                  body: >
                    [[[
                      const on = states['binary_sensor.ecco_clock_dongle_ecco_grid_connected']?.state === 'on';
                      const n = id => {
                        const v = Number(states[id]?.state);
                        return Number.isFinite(v) ? v : null;
                      };
                      const voltage = n('sensor.ecco_clock_dongle_ecco_grid_voltage_l1');
                      const freq = n('sensor.ecco_clock_dongle_ecco_grid_frequency');
                      const grid = n('sensor.ecco_clock_dongle_ecco_grid_power_ct_clamp');
                      const battery = n('sensor.ecco_clock_dongle_ecco_battery_output_power');
                      const soc = n('sensor.ecco_clock_dongle_ecco_battery_soc');
                      const load = n('sensor.ecco_clock_dongle_ecco_load_power');
                      const fmt = (v,d=0) => v === null ? '--' : v.toFixed(d);
                      const absGrid = grid === null ? null : Math.abs(grid);
                      const absBatt = battery === null ? null : Math.abs(battery);
                      const gridNeutral = grid !== null && Math.abs(grid) <= 40;
                      const battDischarging = battery !== null && battery > 100;
                      const battCharging = battery !== null && battery < -100;

                      let flow, detail, colour, bg, border;
                      if (!on) {
                        flow = 'GRID OUTAGE';
                        detail = 'Mains supply lost';
                        colour = '#ff5f6d';
                        bg = 'rgba(255,95,109,.12)';
                        border = 'rgba(255,95,109,.40)';
                      } else if (grid === null) {
                        flow = 'GRID POWER UNKNOWN';
                        detail = 'No CT power reading';
                        colour = '#ffbd3d';
                        bg = 'rgba(255,189,61,.10)';
                        border = 'rgba(255,189,61,.30)';
                      } else if (grid < -40) {
                        flow = `EXPORTING ${(absGrid/1000).toFixed(2)} kW`;
                        detail = 'Sending surplus power to the grid';
                        colour = '#c07cff';
                        bg = 'rgba(192,124,255,.12)';
                        border = 'rgba(192,124,255,.42)';
                      } else if (grid > 40) {
                        flow = `IMPORTING ${(absGrid/1000).toFixed(2)} kW`;
                        detail = 'Drawing power from the grid';
                        colour = '#66b3ff';
                        bg = 'rgba(102,179,255,.11)';
                        border = 'rgba(102,179,255,.36)';
                      } else if (gridNeutral && battDischarging) {
                        flow = `BATTERY SUPPLYING HOUSE ${(absBatt/1000).toFixed(2)} kW`;
                        detail = `Grid near zero • ${fmt(grid)} W grid • battery carrying the load`;
                        colour = '#55e58e';
                        bg = 'rgba(85,229,142,.08)';
                        border = 'rgba(85,229,142,.24)';
                      } else if (gridNeutral && battCharging) {
                        flow = `BATTERY CHARGING ${(absBatt/1000).toFixed(2)} kW`;
                        detail = `Grid near zero • ${fmt(grid)} W grid • battery absorbing surplus`;
                        colour = '#42aaff';
                        bg = 'rgba(66,170,255,.10)';
                        border = 'rgba(66,170,255,.30)';
                      } else {
                        flow = 'GRID NEUTRAL';
                        detail = 'Import/export near zero • battery near idle';
                        colour = '#55e58e';
                        bg = 'rgba(85,229,142,.08)';
                        border = 'rgba(85,229,142,.24)';
                      }
                      return `<div>
                        <div style="padding:13px 14px;border-radius:12px;background:${bg};border:1px solid ${border};">
                          <div style="font-size:26px;font-weight:900;letter-spacing:.3px;color:${colour};">${flow}</div>
                          <div style="font-size:12px;color:rgba(255,255,255,.68);margin-top:4px;">${detail}</div>
                        </div>
                        <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-top:10px;">
                          <div style="padding:8px;border-radius:10px;background:rgba(255,255,255,.035);"><span style="font-size:10px;color:rgba(255,255,255,.48);">GRID STATUS</span><br><b>${on ? 'Connected' : 'Disconnected'} • ${fmt(voltage,1)} V • ${fmt(freq,2)} Hz</b></div>
                          <div style="padding:8px;border-radius:10px;background:rgba(255,255,255,.035);"><span style="font-size:10px;color:rgba(255,255,255,.48);">BATTERY / HOUSE</span><br><b>${fmt(soc)}% • ${fmt(load)} W load</b></div>
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
                    - grid-template-columns: 34px 1fr
                    - grid-template-rows: min-content 1fr
                    - row-gap: 10px
                  icon:
                    - width: 24px
                    - color: '#7ab8ff'
                  name:
                    - justify-self: start
                    - align-self: center
                    - font-size: 20px
                    - font-weight: 700
                    - color: rgba(255,255,255,0.92)
                  custom_fields:
                    body:
                      - justify-self: stretch
                      - width: 100%

              # ---- CURRENT TOU / OPERATING PLAN ----
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

              # ---- SYSTEM HEALTH (compact summary - see the full System
              # Health cards elsewhere in this dashboard for the older,
              # unrelated raw-sensor view; this one reads the five
              # dedicated Task 007 subsystem sensors directly) ----
              - type: custom:button-card
                section_mode: true
                name: System Health
                show_icon: false
                show_state: false
                tap_action:
                  action: none
                custom_fields:
                  health: >
                    [[[
                      const tone = s => s === 'HEALTHY' ? '#39d27a' : s === 'DEGRADED' ? '#66b3ff' : s === 'WARNING' ? '#ffbd3d' : s === 'FAILED' ? '#ff5f6d' : '#aab4c3';
                      const read = id => {
                        const s = states[id]?.state;
                        return ['HEALTHY', 'DEGRADED', 'WARNING', 'FAILED'].includes(s) ? s : 'UNKNOWN';
                      };
                      const rows = [
                        ['Manual Write', read('sensor.ecco_health_manual_write_system')],
                        ['RTC', read('sensor.ecco_health_rtc')],
                        ['Free Power', read('sensor.ecco_health_free_power')],
                        ['Configuration', read('sensor.ecco_health_configuration')],
                        ['Inverter Telemetry', read('sensor.ecco_health_inverter_telemetry')],
                        ['Supervision', read('sensor.ecco_health_supervision')],
                        ['Fallback', read('sensor.ecco_health_fallback')]
                      ];
                      return `<div style="display:grid;gap:6px;">
                        ${rows.map(r => `<div style="display:grid;grid-template-columns:8px 1fr auto;align-items:center;gap:7px;">
                          <span style="width:7px;height:7px;border-radius:50%;background:${tone(r[1])};"></span>
                          <span style="font-size:11px;color:rgba(255,255,255,.62);">${r[0]}</span>
                          <span style="font-size:11px;font-weight:700;color:${tone(r[1])};">${r[1]}</span>
                        </div>`).join('')}
                      </div>`;
                    ]]]
                styles:
                  card:
                    - border-radius: 14px
                    - padding: 10px 12px
                    - background: linear-gradient(145deg, rgba(20,28,45,0.98), rgba(10,15,27,0.98))
                    - border: 1px solid rgba(255,255,255,0.08)
                    - box-shadow: 0 8px 20px rgba(0,0,0,0.18)
                  grid:
                    - grid-template-areas: '"n" "health"'
                    - grid-template-columns: 1fr
                    - grid-template-rows: min-content min-content
                    - row-gap: 6px
                  name:
                    - justify-self: start
                    - font-size: 11px
                    - font-weight: 700
                    - text-transform: uppercase
                    - letter-spacing: 0.05em
                    - color: rgba(255,255,255,0.5)
                  custom_fields:
                    health:
                      - width: 100%


          # ---- ENERGY ACTIONS (v7.16.0) - supersedes BOTH the v7.14.0
          # compact Free Power control strip AND the v7.14.0 Scheduled Free
          # Power strip that used to sit beneath it. Free Power is a
          # single product feature (staged controls, two-step arm/start
          # safety model, all seven live hardware states, plus an integrated
          # NOW/LATER selector for the existing Scheduled Free Power
          # package) via the dedicated ecco-energy-actions-card. On branch
          # feature/manual-dump-to-grid-v1 (2026-09-26, NOT yet merged or
          # live-proven - see VERSION.yaml, still at 7.16.0/main), this card
          # config was additionally wired up for Manual Dump-to-Grid V1
          # (battery -> grid export sibling of Free Power) as a real,
          # interactive tile. See docs/DUMP_TO_GRID_V1.md and
          # frontend/ecco-energy-actions-card/README.md. Neither schedule
          # package's own entities/automations
          # (home-assistant/packages/ecco_free_power_schedule.yaml,
          # home-assistant/packages/ecco_dump_to_grid_schedule.yaml) are
          # duplicated here - this card only presents and drives them.
          - type: custom:ecco-energy-actions-card
            title: Energy Actions

            free_power:
              active: binary_sensor.ecco_clock_dongle_free_power_active
              operation_in_progress: binary_sensor.ecco_clock_dongle_free_power_operation_in_progress
              snapshot_valid: binary_sensor.ecco_clock_dongle_free_power_snapshot_valid
              status: sensor.ecco_clock_dongle_free_power_status
              ends_at: sensor.ecco_clock_dongle_free_power_ends_at
              failures: sensor.ecco_clock_dongle_free_power_failures_since_boot
              start_attempts: sensor.ecco_clock_dongle_free_power_start_attempts_since_boot
              start_successes: sensor.ecco_clock_dongle_free_power_start_successes_since_boot
              restore_successes: sensor.ecco_clock_dongle_free_power_restore_successes_since_boot
              write_enable: switch.ecco_clock_dongle_free_power_write_enable
              max_charge_power: number.ecco_clock_dongle_free_power_max_charge_power
              duration: number.ecco_clock_dongle_free_power_duration
              start: button.ecco_clock_dongle_start_free_power_charge_now
              end_restore: button.ecco_clock_dongle_end_free_power_restore_now

            schedule:
              armed: input_boolean.ecco_free_power_schedule_armed
              start: input_datetime.ecco_free_power_schedule_start
              duration: input_number.ecco_free_power_schedule_duration
              power: input_number.ecco_free_power_schedule_power
              last_result: input_text.ecco_free_power_schedule_last_result
              status: sensor.ecco_free_power_schedule_status
              cancel: script.ecco_free_power_cancel_schedule

            # Manual Dump-to-Grid V1 (2026-09-26) - NOT LIVE-PROVEN. Every
            # entity id below matches
            # firmware/ecco_clock_dongle_stage3_4_free_power.yaml's
            # Dump-to-Grid section; `schedule:` maps exactly the helpers
            # home-assistant/packages/ecco_dump_to_grid_schedule.yaml defines
            # (NOW/LATER selector, same pattern as Free Power).
            dump_to_grid:
              active: binary_sensor.ecco_clock_dongle_dump_to_grid_active
              operation_in_progress: binary_sensor.ecco_clock_dongle_dump_to_grid_operation_in_progress
              snapshot_valid: binary_sensor.ecco_clock_dongle_dump_to_grid_snapshot_valid
              status: sensor.ecco_clock_dongle_dump_to_grid_status
              ends_at: sensor.ecco_clock_dongle_dump_to_grid_ends_at
              battery_soc: sensor.ecco_clock_dongle_ecco_battery_soc
              failures: sensor.ecco_clock_dongle_dump_to_grid_failures_since_boot
              start_attempts: sensor.ecco_clock_dongle_dump_to_grid_start_attempts_since_boot
              start_successes: sensor.ecco_clock_dongle_dump_to_grid_start_successes_since_boot
              restore_successes: sensor.ecco_clock_dongle_dump_to_grid_restore_successes_since_boot
              write_enable: switch.ecco_clock_dongle_dump_to_grid_write_enable
              export_power: number.ecco_clock_dongle_dump_to_grid_export_power
              stop_soc: number.ecco_clock_dongle_dump_to_grid_stop_soc
              duration: number.ecco_clock_dongle_dump_to_grid_duration
              start: button.ecco_clock_dongle_start_dump_to_grid_now
              end_restore: button.ecco_clock_dongle_end_dump_to_grid_restore_now
              active_export_power: sensor.ecco_clock_dongle_dump_to_grid_active_export_power
              active_stop_soc: sensor.ecco_clock_dongle_dump_to_grid_active_stop_soc
              last_end_reason: sensor.ecco_clock_dongle_dump_to_grid_last_end_reason
              recovery_arm: switch.ecco_clock_dongle_dump_to_grid_recovery_arm
              recovery_force_restore: button.ecco_clock_dongle_dump_to_grid_force_restore_original
              recovery_accept: button.ecco_clock_dongle_dump_to_grid_accept_current_state
              recovery_state: sensor.ecco_clock_dongle_dump_to_grid_recovery_state
              schedule:
                armed: input_boolean.ecco_dump_to_grid_schedule_armed
                start: input_datetime.ecco_dump_to_grid_schedule_start
                duration: input_number.ecco_dump_to_grid_schedule_duration
                power: input_number.ecco_dump_to_grid_schedule_power
                stop_soc: input_number.ecco_dump_to_grid_schedule_stop_soc
                last_result: input_text.ecco_dump_to_grid_schedule_last_result
                status: sensor.ecco_dump_to_grid_schedule_status
                cancel: script.ecco_dump_to_grid_cancel_schedule

            grid_options:
              columns: 48
              rows: auto
            card_mod:
              style: |
                ha-card {
                  border: 1px solid rgba(255,255,255,0.08);
                  box-shadow: 0 12px 32px rgba(0,0,0,0.22);
                }

          # ---- KNOWN-GOOD PROFILE (FB-B3; READ-ONLY tile) ----
          # Display only: state word + subline of sensor.ecco_fallback_status and a one-line summary
          # of the saved profile. No write action here - tap opens the standard more-info dialog.
          # Saving, arming and invalidating live ONLY on the Safety view.
          - type: custom:button-card
            section_mode: true
            entity: sensor.ecco_fallback_status
            name: Known-Good Profile
            icon: mdi:shield-check-outline
            show_name: true
            show_icon: true
            show_state: false
            tap_action:
              action: more-info
            custom_fields:
              body: >
                [[[
                  const get = id => states[id]?.state ?? 'unknown';
                  const word = get('sensor.ecco_fallback_status');
                  const sub = states['sensor.ecco_fallback_status']?.attributes?.subline ?? '';
                  const b2 = ';' + get('sensor.ecco_clock_dongle_ecco_fallback_profile_summary') + ';';
                  const kv = k => { const i = b2.indexOf(';' + k + '='); return i < 0 ? '-' : b2.slice(i + k.length + 2).split(';')[0]; };
                  const g = kv('g'), id = kv('id'), at = kv('at');
                  const tones = {
                    'Ready': '#55e58e', 'Drifted': '#ffbd3d', 'Blocked': '#ffbd3d', 'Shadow Recovery': '#ffbd3d',
                    'Not Captured': '#aab4c3', 'Invalidated': '#aab4c3', 'Unknown': '#aab4c3'
                  };
                  const colour = tones[word] || '#aab4c3';
                  const when = at === '0' ? 'capture time unknown' : new Date(Number(at) * 1000).toLocaleString();
                  const saved = g === '-' ? 'No profile saved yet' : `Saved ${when} · generation ${g} · ID ${id.slice(0, 8)}`;
                  return `<div>
                    <div style="display:flex;align-items:center;justify-content:space-between;gap:10px;">
                      <div style="font-size:22px;font-weight:900;letter-spacing:.3px;color:${colour};">${String(word).toUpperCase()}</div>
                      <div style="font-size:10px;font-weight:800;letter-spacing:.45px;color:rgba(255,255,255,.42);">OPEN THE SAFETY TAB</div>
                    </div>
                    <div style="font-size:12px;color:rgba(255,255,255,.62);margin-top:4px;">${saved}</div>
                    <div style="font-size:12px;color:rgba(255,255,255,.62);margin-top:2px;">${sub}</div>
                  </div>`;
                ]]]
            styles:
              card:
                - border-radius: 18px
                - padding: 14px 16px
                - background: linear-gradient(145deg, rgba(20,28,45,0.98), rgba(10,15,27,0.98))
                - border: 1px solid rgba(255,255,255,0.08)
                - box-shadow: 0 10px 30px rgba(0,0,0,0.22)
              grid:
                - grid-template-areas: '"i n" "body body"'
                - grid-template-columns: 34px 1fr
                - grid-template-rows: min-content 1fr
                - row-gap: 8px
              icon:
                - width: 24px
                - color: '#8f7cff'
              name:
                - justify-self: start
                - align-self: center
                - font-size: 13px
                - font-weight: 700
                - text-transform: uppercase
                - letter-spacing: 0.05em
                - color: rgba(255,255,255,0.5)
              custom_fields:
                body:
                  - justify-self: stretch
                  - align-self: start
                  - width: 100%
            grid_options:
              columns: 48
              rows: 3

          # ---- ECCO BLENDED PV FORECAST HEADLINES ----
          - type: custom:button-card
            section_mode: true
            name: PV Forecast
            icon: mdi:weather-partly-cloudy
            show_name: true
            show_icon: true
            show_state: false
            tap_action:
              action: none
            custom_fields:
              body: >
                [[[
                  const val = (id) => {
                    const v = Number(states[id]?.state);
                    return Number.isFinite(v) ? v : null;
                  };
                  const attr = (id, name) => {
                    const v = Number(states[id]?.attributes?.[name]);
                    return Number.isFinite(v) ? v : null;
                  };
                  const fmt = (v) => v === null ? '--' : v.toFixed(1);

                  const todayId = 'sensor.ecco_solar_forecast_today';
                  const tomorrowId = 'sensor.ecco_solar_forecast_tomorrow';
                  const today = val(todayId);
                  const tomorrow = val(tomorrowId);
                  const todayFs = attr(todayId, 'forecast_solar_kwh');
                  const todaySc = attr(todayId, 'solcast_kwh');
                  const tomorrowFs = attr(tomorrowId, 'forecast_solar_kwh');
                  const tomorrowSc = attr(tomorrowId, 'solcast_kwh');

                  const panel = (label, value, fs, sc, icon) => `
                    <div style="flex:1;min-width:0;padding:10px 14px;border-radius:14px;
                      background:rgba(255,255,255,.035);border:1px solid rgba(255,255,255,.07);">
                      <div style="display:flex;align-items:center;gap:8px;color:rgba(255,255,255,.60);font-size:12px;font-weight:700;">
                        <ha-icon icon="${icon}" style="width:18px;color:#ffbd3d;"></ha-icon>${label}
                      </div>
                      <div style="margin-top:4px;font-size:25px;line-height:1.05;font-weight:800;color:#ffbd3d;">
                        ${fmt(value)} <span style="font-size:13px;color:rgba(255,255,255,.70);">kWh</span>
                      </div>
                      <div style="margin-top:5px;font-size:10px;color:rgba(255,255,255,.48);line-height:1.45;">
                        ECCO 50/50 blend
                        ${fs !== null || sc !== null ? `<br>Forecast.Solar ${fmt(fs)} • Solcast ${fmt(sc)}` : ''}
                      </div>
                    </div>`;

                  return `<div style="display:flex;gap:12px;width:100%;">
                    ${panel('Today', today, todayFs, todaySc, 'mdi:white-balance-sunny')}
                    ${panel('Tomorrow', tomorrow, tomorrowFs, tomorrowSc, 'mdi:weather-sunset-up')}
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
                - grid-template-columns: 34px 1fr
                - grid-template-rows: min-content 1fr
                - row-gap: 10px
              icon:
                - width: 24px
                - color: '#ffbd3d'
              name:
                - justify-self: start
                - align-self: center
                - font-size: 20px
                - font-weight: 700
                - color: rgba(255,255,255,0.92)
              custom_fields:
                body:
                  - justify-self: stretch
                  - width: 100%
            grid_options:
              columns: 48
              rows: 3

          - type: custom:flex-horseshoe-card
            entities:
              - entity: sensor.ecco_clock_dongle_ecco_battery_soc
                name: Battery
                decimals: 0
              - entity: sensor.ecco_clock_dongle_ecco_battery_voltage
                name: Voltage
                decimals: 1
              - entity: sensor.ecco_clock_dongle_ecco_battery_output_current
                name: Current
                decimals: 1
              - entity: sensor.ecco_clock_dongle_ecco_battery_output_power
                name: Power
                decimals: 0
            layout:
              names:
                - id: title
                  entity_index: 0
                  xpos: 50
                  ypos: 11
                  styles:
                    - font-size: 1.08em
                    - font-weight: 700
                    - text-transform: none
                    - fill: rgba(255,255,255,0.92)
                - id: voltage_name
                  entity_index: 1
                  xpos: 18
                  ypos: 89
                  styles:
                    - font-size: 0.72em
                    - font-weight: 500
                    - text-transform: none
                    - fill: rgba(255,255,255,0.60)
                - id: current_name
                  entity_index: 2
                  xpos: 50
                  ypos: 89
                  styles:
                    - font-size: 0.72em
                    - font-weight: 500
                    - text-transform: none
                    - fill: rgba(255,255,255,0.60)
                - id: power_name
                  entity_index: 3
                  xpos: 82
                  ypos: 89
                  styles:
                    - font-size: 0.72em
                    - font-weight: 500
                    - text-transform: none
                    - fill: rgba(255,255,255,0.60)
              states:
                - id: soc
                  entity_index: 0
                  xpos: 50
                  ypos: 50
                  styles:
                    - font-size: 2.5em
                    - font-weight: 800
                    - fill: '#55e58e'
                - id: voltage
                  entity_index: 1
                  xpos: 18
                  ypos: 80
                  styles:
                    - font-size: 0.95em
                    - fill: rgba(255,255,255,0.88)
                - id: current
                  entity_index: 2
                  xpos: 50
                  ypos: 80
                  styles:
                    - font-size: 0.95em
                    - fill: rgba(255,255,255,0.88)
                - id: power
                  entity_index: 3
                  xpos: 82
                  ypos: 80
                  styles:
                    - font-size: 0.95em
                    - fill: rgba(255,255,255,0.88)
              icons:
                - id: battery_icon
                  entity_index: 0
                  xpos: 50
                  ypos: 30
                  icon_size: 1.6
                  styles:
                    - fill: '#39d27a'
              horseshoes:
                - id: battery_gauge
                  entity_index: 0
                  xpos: 50
                  ypos: 50
                  radius: 34
                  arc_degrees: 255
                  horseshoe_scale:
                    min: 0
                    max: 100
                    styles:
                      - opacity: 0.24
                  horseshoe_state:
                    width: 8
                    styles:
                      - filter: drop-shadow(0 0 3px rgba(57,210,122,0.55))
                  show:
                    horseshoe_style: colorstopgradient
                  color_stops:
                    colors:
                      0: '#ff5f6d'
                      25: '#ffb347'
                      55: '#d7e75d'
                      75: '#55e58e'
                      100: '#29d979'
            grid_options:
              columns: 12
              rows: 7
            card_mod:
              style: |
                :host {
                  background: transparent !important;
                  background-color: transparent !important;
                }

                ha-card {
                  font-family: "Roboto", "Segoe UI", Arial, sans-serif !important;
                  --ha-card-background: #0d1728 !important;
                  --card-background-color: #0d1728 !important;
                  border-radius: 20px;
                  border: 1px solid rgba(255,255,255,0.08);
                  background: linear-gradient(145deg, rgba(20,28,45,0.98), rgba(10,15,27,0.98));
                  box-shadow: 0 12px 32px rgba(0,0,0,0.22);
                  overflow: hidden;
                }
                .card-header {
                  color: rgba(255,255,255,0.92) !important;
                  font-family: "Roboto", "Segoe UI", Arial, sans-serif !important;
                  font-size: 20px !important;
                  font-weight: 700 !important;
                  letter-spacing: 0 !important;
                  text-transform: none !important;
                }
                svg text {
                  font-family: "Roboto", "Segoe UI", Arial, sans-serif !important;
                  text-transform: none !important;
                  letter-spacing: 0 !important;
                }
          - type: custom:flex-horseshoe-card
            entities:
              - entity: sensor.ecco_clock_dongle_ecco_load_power
                name: House Load
                decimals: 0
              - entity: sensor.ecco_clock_dongle_ecco_load_voltage_l1
                name: Voltage
                decimals: 1
              - entity: sensor.ecco_clock_dongle_ecco_load_frequency
                name: Frequency
                decimals: 2
              - entity: sensor.ecco_clock_dongle_ecco_inverter_output_current_l1
                name: Current
                decimals: 1
            layout:
              names:
                - id: title
                  entity_index: 0
                  xpos: 50
                  ypos: 11
                  styles:
                    - font-size: 1.08em
                    - font-weight: 700
                    - text-transform: none
                    - fill: rgba(255,255,255,0.92)
                - id: voltage_name
                  entity_index: 1
                  xpos: 18
                  ypos: 89
                  styles:
                    - font-size: 0.72em
                    - font-weight: 500
                    - text-transform: none
                    - fill: rgba(255,255,255,0.60)
                - id: frequency_name
                  entity_index: 2
                  xpos: 50
                  ypos: 89
                  styles:
                    - font-size: 0.72em
                    - font-weight: 500
                    - text-transform: none
                    - fill: rgba(255,255,255,0.60)
                - id: current_name
                  entity_index: 3
                  xpos: 82
                  ypos: 89
                  styles:
                    - font-size: 0.72em
                    - font-weight: 500
                    - text-transform: none
                    - fill: rgba(255,255,255,0.60)
              states:
                - id: load
                  entity_index: 0
                  xpos: 50
                  ypos: 50
                  styles:
                    - font-size: 2.3em
                    - font-weight: 800
                    - fill: '#5bbcff'
                - id: voltage
                  entity_index: 1
                  xpos: 18
                  ypos: 80
                  styles:
                    - font-size: 0.95em
                    - fill: rgba(255,255,255,0.88)
                - id: frequency
                  entity_index: 2
                  xpos: 50
                  ypos: 80
                  styles:
                    - font-size: 0.95em
                    - fill: rgba(255,255,255,0.88)
                - id: current
                  entity_index: 3
                  xpos: 82
                  ypos: 80
                  styles:
                    - font-size: 0.95em
                    - fill: rgba(255,255,255,0.88)
              icons:
                - id: house_icon
                  entity_index: 0
                  xpos: 50
                  ypos: 30
                  icon_size: 1.6
                  styles:
                    - fill: '#42aaff'
              horseshoes:
                - id: house_gauge
                  entity_index: 0
                  xpos: 50
                  ypos: 50
                  radius: 34
                  arc_degrees: 255
                  horseshoe_scale:
                    min: 0
                    max: 8000
                    styles:
                      - opacity: 0.24
                  horseshoe_state:
                    width: 8
                    styles:
                      - filter: drop-shadow(0 0 3px rgba(66,170,255,0.5))
                  show:
                    horseshoe_style: colorstopgradient
                  color_stops:
                    colors:
                      0: '#42aaff'
                      3000: '#56c5ff'
                      5500: '#ffc857'
                      7000: '#ff7657'
                      8000: '#ff5263'
            grid_options:
              columns: 12
              rows: 7
            card_mod:
              style: |
                :host {
                  background: transparent !important;
                  background-color: transparent !important;
                }

                ha-card {
                  font-family: "Roboto", "Segoe UI", Arial, sans-serif !important;
                  --ha-card-background: #0d1728 !important;
                  --card-background-color: #0d1728 !important;
                  border-radius: 20px;
                  border: 1px solid rgba(255,255,255,0.08);
                  background: linear-gradient(145deg, rgba(20,28,45,0.98), rgba(10,15,27,0.98));
                  box-shadow: 0 12px 32px rgba(0,0,0,0.22);
                  overflow: hidden;
                }
                .card-header {
                  color: rgba(255,255,255,0.92) !important;
                  font-family: "Roboto", "Segoe UI", Arial, sans-serif !important;
                  font-size: 20px !important;
                  font-weight: 700 !important;
                  letter-spacing: 0 !important;
                  text-transform: none !important;
                }
                svg text {
                  font-family: "Roboto", "Segoe UI", Arial, sans-serif !important;
                  text-transform: none !important;
                  letter-spacing: 0 !important;
                }
          - type: custom:flex-horseshoe-card
            entities:
              - entity: sensor.ecco_clock_dongle_ecco_pv_power
                name: Solar PV
                decimals: 0
              - entity: sensor.ecco_clock_dongle_ecco_pv1_power
                name: PV1
                decimals: 0
              - entity: sensor.ecco_clock_dongle_ecco_pv2_power
                name: PV2
                decimals: 0
              - entity: sensor.ecco_clock_dongle_ecco_day_pv_energy
                name: Today
                decimals: 1
            layout:
              names:
                - id: title
                  entity_index: 0
                  xpos: 50
                  ypos: 11
                  styles:
                    - font-size: 1.08em
                    - font-weight: 700
                    - text-transform: none
                    - fill: rgba(255,255,255,0.92)
                - id: pv1_name
                  entity_index: 1
                  xpos: 18
                  ypos: 89
                  styles:
                    - font-size: 0.72em
                    - font-weight: 500
                    - text-transform: none
                    - fill: rgba(255,255,255,0.60)
                - id: pv2_name
                  entity_index: 2
                  xpos: 50
                  ypos: 89
                  styles:
                    - font-size: 0.72em
                    - font-weight: 500
                    - text-transform: none
                    - fill: rgba(255,255,255,0.60)
                - id: today_name
                  entity_index: 3
                  xpos: 82
                  ypos: 89
                  styles:
                    - font-size: 0.72em
                    - font-weight: 500
                    - text-transform: none
                    - fill: rgba(255,255,255,0.60)
              states:
                - id: pv_total
                  entity_index: 0
                  xpos: 50
                  ypos: 50
                  styles:
                    - font-size: 2.3em
                    - font-weight: 800
                    - fill: '#ffd05f'
                - id: pv1
                  entity_index: 1
                  xpos: 18
                  ypos: 80
                  styles:
                    - font-size: 0.95em
                    - fill: '#ffd05f'
                - id: pv2
                  entity_index: 2
                  xpos: 50
                  ypos: 80
                  styles:
                    - font-size: 0.95em
                    - fill: '#ffd05f'
                - id: today
                  entity_index: 3
                  xpos: 82
                  ypos: 80
                  styles:
                    - font-size: 0.95em
                    - fill: rgba(255,255,255,0.88)
              icons:
                - id: solar_icon
                  entity_index: 0
                  xpos: 50
                  ypos: 30
                  icon_size: 1.6
                  styles:
                    - fill: '#ffbd3d'
              horseshoes:
                - id: solar_gauge
                  entity_index: 0
                  xpos: 50
                  ypos: 50
                  radius: 34
                  arc_degrees: 255
                  horseshoe_scale:
                    min: 0
                    max: 9500
                    styles:
                      - opacity: 0.24
                  horseshoe_state:
                    width: 8
                    styles:
                      - filter: drop-shadow(0 0 3px rgba(255,189,61,0.52))
                  show:
                    horseshoe_style: colorstopgradient
                  color_stops:
                    colors:
                      0: '#9b7a2d'
                      1000: '#d89a2d'
                      3500: '#ffbd3d'
                      6500: '#ffd95c'
                      9500: '#fff18b'
            grid_options:
              columns: 12
              rows: 7
            card_mod:
              style: |
                :host {
                  background: transparent !important;
                  background-color: transparent !important;
                }

                ha-card {
                  font-family: "Roboto", "Segoe UI", Arial, sans-serif !important;
                  --ha-card-background: #0d1728 !important;
                  --card-background-color: #0d1728 !important;
                  border-radius: 20px;
                  border: 1px solid rgba(255,255,255,0.08);
                  background: linear-gradient(145deg, rgba(20,28,45,0.98), rgba(10,15,27,0.98));
                  box-shadow: 0 12px 32px rgba(0,0,0,0.22);
                  overflow: hidden;
                }
                .card-header {
                  color: rgba(255,255,255,0.92) !important;
                  font-family: "Roboto", "Segoe UI", Arial, sans-serif !important;
                  font-size: 20px !important;
                  font-weight: 700 !important;
                  letter-spacing: 0 !important;
                  text-transform: none !important;
                }
                svg text {
                  font-family: "Roboto", "Segoe UI", Arial, sans-serif !important;
                  text-transform: none !important;
                  letter-spacing: 0 !important;
                }
          - type: custom:flex-horseshoe-card
            entities:
              - entity: sensor.ecco_clock_dongle_ecco_inverter_output_power
                name: Inverter
                icon: mdi:solar-power-variant-outline
                decimals: 0
              - entity: sensor.ecco_clock_dongle_ecco_temperature_ac_transformer
                name: AC Temp
                decimals: 1
              - entity: sensor.ecco_clock_dongle_ecco_inverter_output_frequency
                name: Frequency
                decimals: 2
              - entity: sensor.ecco_clock_dongle_ecco_inverter_system_state
                name: Status
            layout:
              names:
                - id: title
                  entity_index: 0
                  xpos: 50
                  ypos: 11
                  styles:
                    - font-size: 1.08em
                    - font-weight: 700
                    - text-transform: none
                    - fill: rgba(255,255,255,0.92)
                - id: temp_name
                  entity_index: 1
                  xpos: 18
                  ypos: 89
                  styles:
                    - font-size: 0.72em
                    - font-weight: 500
                    - text-transform: none
                    - fill: rgba(255,255,255,0.60)
                - id: frequency_name
                  entity_index: 2
                  xpos: 50
                  ypos: 89
                  styles:
                    - font-size: 0.72em
                    - font-weight: 500
                    - text-transform: none
                    - fill: rgba(255,255,255,0.60)
                - id: status_name
                  entity_index: 3
                  xpos: 82
                  ypos: 89
                  styles:
                    - font-size: 0.72em
                    - font-weight: 500
                    - text-transform: none
                    - fill: rgba(255,255,255,0.60)
              states:
                - id: inverter_power
                  entity_index: 0
                  xpos: 50
                  ypos: 50
                  styles:
                    - font-size: 2.3em
                    - font-weight: 800
                    - fill: '#9c8cff'
                - id: temp
                  entity_index: 1
                  xpos: 18
                  ypos: 80
                  styles:
                    - font-size: 0.95em
                    - fill: rgba(255,255,255,0.88)
                - id: frequency
                  entity_index: 2
                  xpos: 50
                  ypos: 80
                  styles:
                    - font-size: 0.95em
                    - fill: rgba(255,255,255,0.88)
                - id: status
                  entity_index: 3
                  xpos: 82
                  ypos: 80
                  styles:
                    - font-size: 0.86em
                    - font-weight: 700
                    - fill: '#55e58e'
              icons:
                - id: inverter_icon
                  entity_index: 0
                  xpos: 50
                  ypos: 30
                  icon_size: 1.6
                  styles:
                    - fill: '#8f7cff'
              horseshoes:
                - id: inverter_gauge
                  entity_index: 0
                  xpos: 50
                  ypos: 50
                  radius: 34
                  arc_degrees: 255
                  horseshoe_scale:
                    min: 0
                    max: 8000
                    styles:
                      - opacity: 0.24
                  horseshoe_state:
                    width: 8
                    styles:
                      - filter: drop-shadow(0 0 3px rgba(143,124,255,0.5))
                  show:
                    horseshoe_style: colorstopgradient
                  color_stops:
                    colors:
                      0: '#7263d7'
                      3000: '#8f7cff'
                      6000: '#b29dff'
                      8000: '#d3c7ff'
            grid_options:
              columns: 12
              rows: 7
            card_mod:
              style: |
                :host {
                  background: transparent !important;
                  background-color: transparent !important;
                }

                ha-card {
                  font-family: "Roboto", "Segoe UI", Arial, sans-serif !important;
                  --ha-card-background: #0d1728 !important;
                  --card-background-color: #0d1728 !important;
                  border-radius: 20px;
                  border: 1px solid rgba(255,255,255,0.08);
                  background: linear-gradient(145deg, rgba(20,28,45,0.98), rgba(10,15,27,0.98));
                  box-shadow: 0 12px 32px rgba(0,0,0,0.22);
                  overflow: hidden;
                }
                .card-header {
                  color: rgba(255,255,255,0.92) !important;
                  font-family: "Roboto", "Segoe UI", Arial, sans-serif !important;
                  font-size: 20px !important;
                  font-weight: 700 !important;
                  letter-spacing: 0 !important;
                  text-transform: none !important;
                }
                svg text {
                  font-family: "Roboto", "Segoe UI", Arial, sans-serif !important;
                  text-transform: none !important;
                  letter-spacing: 0 !important;
                }


          # ---- ECCO TODAY / DECISION ENGINE ----
          # Dashboard-only modelling. It reads ECCO + Forecast.Solar + sun.sun.
          # No inverter setting writes are performed.
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
                  const batt = n('sensor.ecco_clock_dongle_ecco_battery_output_power');
                  const grid = n('sensor.ecco_clock_dongle_ecco_grid_power_ct_clamp');
                  const gen = n('sensor.ecco_clock_dongle_ecco_generator_port_power');

                  let label = 'System balanced';
                  let colour = '#7ab8ff';
                  if (gen > 100) {
                    label = 'Generator / AUX active'; colour = '#6ed6c5';
                  } else if (grid > 300 && batt < -250) {
                    label = 'Grid charging battery'; colour = '#b36cff';
                  } else if (pv > 300 && batt < -200) {
                    label = 'Solar charging battery'; colour = '#ffbd3d';
                  } else if (pv > load * 0.80 && grid < 150) {
                    label = 'Solar carrying the house'; colour = '#ffbd3d';
                  } else if (batt > 250 && grid < 150) {
                    label = 'Battery carrying the house'; colour = '#39d27a';
                  } else if (grid > 300) {
                    label = 'Grid supporting the house'; colour = '#7ab8ff';
                  } else if (pv > 150 && batt > 100) {
                    label = 'Solar + battery supplying house'; colour = '#55e58e';
                  } else if (pv < 50 && batt > 100) {
                    label = 'Battery supplying house'; colour = '#39d27a';
                  }

                  return `<span style="
                    display:inline-flex;align-items:center;gap:8px;padding:6px 11px;
                    border-radius:999px;background:${colour}1f;border:1px solid ${colour}55;
                    color:${colour};font-weight:700;font-size:13px;">
                    <span style="width:8px;height:8px;border-radius:50%;background:${colour};box-shadow:0 0 8px ${colour};"></span>
                    ${label}
                  </span>`;
                ]]]
              metrics: >
                [[[
                  const n = (id) => Number(states[id]?.state ?? 0);
                  const fmt = (v, d=1) => Number.isFinite(v) ? v.toFixed(d) : '--';
                  const pvToday = n('sensor.ecco_clock_dongle_ecco_day_pv_energy');
                  const loadToday = n('sensor.ecco_clock_dongle_ecco_day_load_energy');
                  const importToday = n('sensor.ecco_clock_dongle_ecco_day_grid_import');
                  const exportToday = n('sensor.ecco_clock_dongle_ecco_day_grid_export');
                  const battCharge = n('sensor.ecco_clock_dongle_ecco_day_battery_charge');
                  const battDischarge = n('sensor.ecco_clock_dongle_ecco_day_battery_discharge');
                  const soc = n('sensor.ecco_clock_dongle_ecco_battery_soc');
                  const netGrid = importToday - exportToday;
                  const throughput = battCharge + battDischarge;

                  const gridLabel = netGrid >= 0 ? 'Net Import' : 'Net Export';
                  const gridValue = `${fmt(Math.abs(netGrid))} kWh`;
                  const gridColour = netGrid >= 0 ? '#7ab8ff' : '#b36cff';

                  const boxes = [
                    ['PV Today', `${fmt(pvToday)} kWh`, '#ffbd3d'],
                    ['House Today', `${fmt(loadToday)} kWh`, '#42aaff'],
                    [gridLabel, gridValue, gridColour],
                    ['Battery SOC', `${fmt(soc,0)}%`, '#39d27a'],
                    ['Battery Throughput', `${fmt(throughput)} kWh`, '#55e58e']
                  ];

                  return `<div style="display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:10px;width:100%;">
                    ${boxes.map(([k,v,c]) => `
                      <div style="background:rgba(255,255,255,0.035);border:1px solid rgba(255,255,255,0.07);
                        border-radius:12px;padding:10px 12px;">
                        <div style="font-size:11px;color:rgba(255,255,255,0.58);font-weight:600;">${k}</div>
                        <div style="font-size:19px;color:${c};font-weight:800;margin-top:2px;">${v}</div>
                      </div>`).join('')}
                  </div>`;
                ]]]
              forecast: >
                [[[
                  const sensors = Object.values(states).filter(s => s.entity_id.startsWith('sensor.'));
                  const friendly = (s) => String(s?.attributes?.friendly_name ?? s?.entity_id ?? '').toLowerCase();
                  const find = (need, exclude=[]) => sensors.find(s => {
                    const name = friendly(s);
                    return need.every(x => name.includes(x)) && !exclude.some(x => name.includes(x));
                  });
                  const num = (s) => {
                    const v = Number(s?.state);
                    return Number.isFinite(v) ? v : null;
                  };

                  const today = num(states['sensor.ecco_solar_forecast_today']);
                  const remaining = num(states['sensor.ecco_solar_forecast_remaining']);
                  const tomorrow = num(states['sensor.ecco_solar_forecast_tomorrow']);
                  const forecastNow = num(states['sensor.ecco_solar_forecast_power_now']);
                  const actualNow = Number(states['sensor.ecco_clock_dongle_ecco_pv_power']?.state ?? 0);

                  if (today === null && remaining === null && forecastNow === null) {
                    return `<div style="padding:10px 12px;border-radius:12px;background:rgba(255,189,61,0.06);
                      border:1px solid rgba(255,189,61,0.18);color:rgba(255,255,255,0.70);font-size:12px;">
                      <b style="color:#ffbd3d;">Solar forecast not linked yet.</b>
                      ECCO is waiting for a valid solar forecast source.
                    </div>`;
                  }

                  let nowCompare = '';
                  if (forecastNow !== null && forecastNow > 0) {
                    const pct = Math.round((actualNow / forecastNow) * 100);
                    const diff = actualNow - forecastNow;
                    nowCompare = ` • actual now <b style="color:${diff >= 0 ? '#55e58e' : '#ffbd3d'}">${pct}%</b> of forecast`;
                  }

                  return `<div style="padding:10px 12px;border-radius:12px;background:rgba(255,189,61,0.055);
                    border:1px solid rgba(255,189,61,0.16);color:rgba(255,255,255,0.72);font-size:12px;line-height:1.55;">
                    <b style="color:#ffbd3d;">Solar model</b>
                    ${today !== null ? ` • <b>${today.toFixed(1)} kWh</b> today` : ''}
                    ${remaining !== null ? ` • <b>${remaining.toFixed(1)} kWh</b> remaining` : ''}
                    ${forecastNow !== null ? ` • <b>${Math.round(forecastNow)} W</b> forecast now` : ''}
                    ${nowCompare}
                    ${tomorrow !== null ? ` • next day <b>${tomorrow.toFixed(1)} kWh</b>` : ''}
                  </div>`;
                ]]]
              recommendation: >
                [[[
                  const n = (id) => Number(states[id]?.state ?? 0);
                  const clamp = (v,a,b) => Math.max(a,Math.min(b,v));
                  const pv = n('sensor.ecco_clock_dongle_ecco_pv_power');
                  const load = n('sensor.ecco_clock_dongle_ecco_load_power');
                  const soc = n('sensor.ecco_clock_dongle_ecco_battery_soc');
                  const loadToday = n('sensor.ecco_clock_dongle_ecco_day_load_energy');
                  const capAh = n('sensor.ecco_clock_dongle_ecco_battery_capacity_ah') || 620;
                  const capKwh = capAh * 51.2 / 1000;

                  const sensors = Object.values(states).filter(s => s.entity_id.startsWith('sensor.'));
                  const events = Object.values(states).filter(s => s.entity_id.startsWith('event.'));
                  const friendly = (s) => String(s?.attributes?.friendly_name ?? s?.entity_id ?? '').toLowerCase();
                  const find = (need, exclude=[]) => sensors.find(s => {
                    const x = friendly(s);
                    return need.every(v => x.includes(v)) && !exclude.some(v => x.includes(v));
                  });
                  const num = (s) => {
                    const v = Number(s?.state);
                    return Number.isFinite(v) ? v : null;
                  };
                  const isExport = (s) => s.entity_id.includes('export') || friendly(s).includes('export');

                  const forecastToday = num(states['sensor.ecco_solar_forecast_today']);
                  const remaining = num(states['sensor.ecco_solar_forecast_remaining']);
                  const forecastNow = num(states['sensor.ecco_solar_forecast_power_now']);
                  const actualToday = n('sensor.ecco_clock_dongle_ecco_day_pv_energy');

                  let liveRatio = null;
                  if (forecastNow !== null && forecastNow >= 250) {
                    liveRatio = clamp(pv / forecastNow, 0.15, 1.50);
                  }

                  let factor = liveRatio !== null
                    ? clamp(0.65 + 0.35 * liveRatio, 0.70, 1.10)
                    : 1.0;

                  let dailyRatio = null;
                  if (forecastToday !== null && remaining !== null) {
                    const expectedSoFar = Math.max(forecastToday - remaining, 0);
                    if (expectedSoFar >= 2.0 && actualToday >= 0.5) {
                      dailyRatio = clamp(actualToday / expectedSoFar, 0.35, 1.35);
                      factor = clamp(factor * 0.60 + dailyRatio * 0.40, 0.65, 1.10);
                    }
                  }

                  // Confidence now reflects both forecast signal strength and how closely
                  // real production is tracking it. 50% of forecast is deliberately LOW.
                  let accuracy = null;
                  if (liveRatio !== null) {
                    accuracy = clamp(1 - Math.abs(1 - liveRatio), 0, 1);
                  }
                  if (dailyRatio !== null) {
                    const dailyAccuracy = clamp(1 - Math.abs(1 - dailyRatio), 0, 1);
                    accuracy = accuracy === null ? dailyAccuracy : (accuracy * 0.65 + dailyAccuracy * 0.35);
                  }

                  let confidence = 'Low';
                  if (forecastNow !== null && forecastNow >= 700 && accuracy !== null && accuracy >= 0.80) {
                    confidence = 'High';
                  } else if (forecastNow !== null && forecastNow >= 250 && accuracy !== null && accuracy >= 0.62) {
                    confidence = 'Medium';
                  }

                  const correctedSolar = Number.isFinite(remaining) ? remaining * factor * 0.95 : null;
                  const conservativeSolar = Number.isFinite(remaining)
                    ? remaining * Math.max(0.60, factor - 0.15) * 0.95
                    : null;

                  const now = new Date();
                  const elapsed = Math.max(now.getHours() + now.getMinutes()/60, 1);
                  const avgSoFar = loadToday / elapsed;
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

                  const likelySoc = correctedSolar !== null
                    ? clamp(soc + ((correctedSolar-loadToCheap)/capKwh)*100, 0, 100)
                    : null;
                  const conservativeSoc = conservativeSolar !== null
                    ? clamp(soc + ((conservativeSolar-loadToCheap)/capKwh)*100, 0, 100)
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
                      detail = `Likely SOC at ${targetTime} is ${likelySoc.toFixed(0)}% and conservative SOC is ${conservativeSoc.toFixed(0)}%.`;
                      colour = '#55e58e';
                    } else if (likelySoc >= 20) {
                      headline = `Keep watch on reserve • ${confidence.toLowerCase()} confidence`;
                      detail = `Likely SOC at ${targetTime} is ${likelySoc.toFixed(0)}%, but conservative modelling falls to ${conservativeSoc.toFixed(0)}%.`;
                      colour = '#ffbd3d';
                    } else {
                      headline = `Cheap-rate support may be worthwhile • ${confidence.toLowerCase()} confidence`;
                      detail = `Likely SOC at ${targetTime} is only ${likelySoc.toFixed(0)}% with ${conservativeSoc.toFixed(0)}% on the conservative model.`;
                      colour = '#ff6376';
                    }
                  }

                  if (liveRatio !== null) {
                    detail += ` Live PV is ${Math.round(liveRatio*100)}% of Forecast.Solar right now.`;
                  }

                  if (dayCheapP !== null && dayPeakP !== null) {
                    const deliveredCheap = dayCheapP / 0.90;
                    const avoided = dayPeakP - deliveredCheap;
                    detail += ` Today's tariff spans ${dayCheapP.toFixed(1)}–${dayPeakP.toFixed(1)}p/kWh; cheap-rate energy is about ${deliveredCheap.toFixed(1)}p/kWh delivered after a 90% round-trip assumption.`;
                    if (avoided > 0) {
                      detail += ` That is worth about ${avoided.toFixed(1)}p/kWh versus buying at today's peak rate.`;
                    }
                  }
                  if (spread !== null) {
                    detail += ` Current import/export spread is ${spread.toFixed(1)}p/kWh.`;
                  }

                  return `<div style="padding-top:2px;">
                    <div style="font-size:15px;font-weight:800;color:${colour};">${headline}</div>
                    <div style="font-size:12px;line-height:1.5;color:rgba(255,255,255,0.64);margin-top:3px;">${detail}</div>
                  </div>`;
                ]]]
            styles:
              card:
                - border-radius: 20px
                - padding: 14px 16px
                - background: linear-gradient(145deg, rgba(20,28,45,0.98), rgba(10,15,27,0.98))
                - border: 1px solid rgba(255,255,255,0.08)
                - box-shadow: 0 12px 32px rgba(0,0,0,0.22)
                - overflow: hidden
              grid:
                - grid-template-areas: '"i n status" "metrics metrics metrics" "forecast forecast forecast" "recommendation recommendation recommendation"'
                - grid-template-columns: 34px 1fr auto
                - grid-template-rows: min-content min-content min-content min-content
                - row-gap: 8px
                - column-gap: 10px
              icon:
                - width: 25px
                - color: '#b8adff'
              name:
                - justify-self: start
                - align-self: center
                - font-size: 20px
                - font-weight: 700
                - color: rgba(255,255,255,0.92)
              custom_fields:
                status:
                  - justify-self: end
                  - align-self: center
                metrics:
                  - width: 100%
                forecast:
                  - width: 100%
                recommendation:
                  - width: 100%
                  - white-space: normal
                  - overflow: visible
                  - text-overflow: unset
                  - word-break: normal
                  - line-height: 1.45
            grid_options:
              columns: 48
              rows: 5

          # ---- MAIN POWER GRAPH ----
          - type: custom:apexcharts-card
            section_mode: true
            grid_options:
              columns: 32
              rows: 8
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
              - entity: sensor.ecco_clock_dongle_ecco_battery_soc
                name: SOC Model
                yaxis_id: soc
                type: line
                color: '#ffb347'
                stroke_width: 3
                opacity: 1
                extend_to: false
                show:
                  in_header: false
                data_generator: |
                  const n=(id)=>Number(hass.states[id]?.state??0);
                  const clamp=(v,a,b)=>Math.max(a,Math.min(b,v));
                  const sensors=Object.values(hass.states).filter(s=>s.entity_id.startsWith('sensor.'));
                  const friendly=(s)=>String(s?.attributes?.friendly_name??s?.entity_id??'').toLowerCase();
                  const find=(need,exclude=[])=>sensors.find(s=>{
                    const x=friendly(s);return need.every(v=>x.includes(v))&&!exclude.some(v=>x.includes(v));
                  });
                  const num=(s)=>{const v=Number(s?.state);return Number.isFinite(v)?v:null;};

                  const soc=n('sensor.ecco_clock_dongle_ecco_battery_soc');
                  const loadToday=n('sensor.ecco_clock_dongle_ecco_day_load_energy');
                  const loadW=n('sensor.ecco_clock_dongle_ecco_load_power');
                  const pvW=n('sensor.ecco_clock_dongle_ecco_pv_power');
                  const actualPV=n('sensor.ecco_clock_dongle_ecco_day_pv_energy');
                  const capAh=n('sensor.ecco_clock_dongle_ecco_battery_capacity_ah')||620;
                  const capKwh=capAh*51.2/1000;

                  const forecast=num(states['sensor.ecco_solar_forecast_today']);
                  const remaining=num(states['sensor.ecco_solar_forecast_remaining']);
                  const forecastNow=num(states['sensor.ecco_solar_forecast_power_now']);

                  let ratio=1;
                  if(forecastNow!==null&&forecastNow>=250)ratio=clamp(pvW/forecastNow,.15,1.5);
                  let factor=forecastNow!==null&&forecastNow>=250?clamp(.65+.35*ratio,.70,1.10):1;
                  const expectedSoFar=forecast!==null&&remaining!==null?Math.max(forecast-remaining,0):0;
                  if(expectedSoFar>=2&&actualPV>=.5){
                    const dailyRatio=clamp(actualPV/expectedSoFar,.35,1.35);
                    factor=clamp(factor*.60+dailyRatio*.40,.65,1.10);
                  }

                  const now=new Date();
                  const elapsed=Math.max(now.getHours()+now.getMinutes()/60,1);
                  const avgKw=loadToday/elapsed;
                  const liveKw=loadW/1000;
                  const loadKw=clamp(avgKw*.65+liveKw*.35,.15,5);

                  const sun=hass.states['sun.sun'];
                  const sunset=sun?.state==='above_horizon'?new Date(sun.attributes?.next_setting):now;
                  const hSun=Math.max((sunset-now)/3600000,0);
                  const solarKwh=remaining!==null?remaining*factor*.95:0;
                  const solarKw=hSun>0?solarKwh/hSun:0;

                  const modelEnd=new Date(now);
                  modelEnd.setHours(24,0,0,0);
                  const out=[[now.getTime(),soc]];
                  let model=soc;
                  let t=new Date(now);
                  while(t<modelEnd){
                    const next=new Date(Math.min(t.getTime()+30*60000,modelEnd.getTime()));
                    const dt=(next-t)/3600000;
                    const solar=next<=sunset?solarKw:0;
                    model=clamp(model+((solar-loadKw)*dt/capKwh)*100,0,100);
                    out.push([next.getTime(),model]);
                    t=next;
                  }
                  return out;
            now:
              show: true
              color: '#6d7b91'
              label: Now
            apex_config:
              chart:
                height: 365
                toolbar:
                  show: false
              dataLabels:
                enabled: false
              legend:
                position: top
                horizontalAlign: left
              stroke:
                curve: smooth
                dashArray: [0, 0, 0, 0, 0, 6]
              grid:
                borderColor: rgba(255,255,255,0.08)
              annotations:
                xaxis:
                  - x: "EVAL:(() => { const d = new Date(); d.setHours(0,35,0,0); return d.getTime(); })()"
                    x2: "EVAL:(() => { const d = new Date(); d.setHours(5,25,0,0); return d.getTime(); })()"
                    fillColor: '#8f7cff'
                    opacity: 0.08
                    borderColor: 'rgba(143,124,255,0.18)'
                    label:
                      text: TOU grid charge • 00:35–05:25
                      borderColor: 'rgba(143,124,255,0.18)'
                      style:
                        background: '#18213a'
                        color: '#b8adff'
                        fontSize: 10px
              tooltip:
                shared: true
                intersect: false
            card_mod:
              style: |
                :host {
                  background: transparent !important;
                  background-color: transparent !important;
                }

                ha-card {
                  font-family: "Roboto", "Segoe UI", Arial, sans-serif !important;
                  --ha-card-background: #0d1728 !important;
                  --card-background-color: #0d1728 !important;
                  border-radius: 18px;
                  border: 1px solid rgba(255,255,255,0.08);
                  background: linear-gradient(145deg, rgba(20,28,45,0.98), rgba(10,15,27,0.98));
                  box-shadow: 0 10px 30px rgba(0,0,0,0.22);
                  overflow: hidden;
                }
                .card-header {
                  color: rgba(255,255,255,0.92) !important;
                  font-family: "Roboto", "Segoe UI", Arial, sans-serif !important;
                  font-size: 20px !important;
                  font-weight: 700 !important;
                  letter-spacing: 0 !important;
                  text-transform: none !important;
                }
                #header {
                  padding: 12px 16px 0 16px !important;
                }
                #header__title {
                  color: rgba(255,255,255,0.92) !important;
                  font-family: "Roboto", "Segoe UI", Arial, sans-serif !important;
                  font-size: 20px !important;
                  font-weight: 700 !important;
                  line-height: 1.2 !important;
                  letter-spacing: 0 !important;
                  text-transform: none !important;
                  padding-bottom: 7px !important;
                }
                #state__name {
                  color: rgba(255,255,255,0.66) !important;
                  font-family: "Roboto", "Segoe UI", Arial, sans-serif !important;
                  font-weight: 500 !important;
                }
                #state__value > #state {
                  font-weight: 700 !important;
                }

          # ---- TIME OF USE TABLE ----
          - type: custom:button-card
            section_mode: true
            name: System Health
            show_icon: false
            show_state: false
            tap_action:
              action: none
            custom_fields:
              health: >
                [[[
                  const telemetry = states['binary_sensor.ecco_clock_dongle_telemetry_online']?.state === 'on';
                  const config = states['binary_sensor.ecco_clock_dongle_configuration_online']?.state === 'on';
                  const ntp = states['binary_sensor.ecco_clock_dongle_ntp_synced']?.state === 'on';
                  const stall = states['binary_sensor.ecco_clock_dongle_rtc_stall_detected']?.state === 'on';
                  const clock = Number(states['sensor.ecco_clock_dongle_clock_difference']?.state);
                  const wifi = Number(states['sensor.ecco_clock_dongle_wifi_signal']?.state);
                  const tf = Number(states['sensor.ecco_clock_dongle_telemetry_read_failures_since_boot']?.state);
                  const cf = Number(states['sensor.ecco_clock_dongle_configuration_read_failures_since_boot']?.state);
                  const rows = [
                    ['Telemetry', telemetry ? 'Connected' : 'Offline', telemetry],
                    ['Configuration', config ? 'Connected' : 'Offline', config],
                    ['NTP Sync', ntp ? 'Synced' : 'Not synced', ntp],
                    ['RTC Stall', stall ? 'Detected' : 'Clear', !stall],
                    ['Clock Error', Number.isFinite(clock) ? `${clock.toFixed(0)} s` : '--', Number.isFinite(clock) && Math.abs(clock) < 20],
                    ['Wi‑Fi', Number.isFinite(wifi) ? `${wifi.toFixed(0)} dBm` : '--', Number.isFinite(wifi) && wifi > -80],
                    ['Read Failures', `${Number.isFinite(tf) ? tf.toFixed(0) : '--'} / ${Number.isFinite(cf) ? cf.toFixed(0) : '--'}`, Number.isFinite(tf) && Number.isFinite(cf) && tf === 0 && cf === 0]
                  ];
                  return `<div style="display:grid;gap:13px;padding-top:8px;">
                    ${rows.map(r => `<div style="display:grid;grid-template-columns:18px 1fr auto;align-items:center;gap:8px;padding:4px 2px;border-bottom:1px solid rgba(255,255,255,.05);">
                      <span style="width:10px;height:10px;border-radius:50%;background:${r[2] ? '#39d27a' : '#ff6376'};box-shadow:0 0 10px ${r[2] ? 'rgba(57,210,122,.45)' : 'rgba(255,99,118,.45)'};"></span>
                      <span style="font-size:13px;color:rgba(255,255,255,.68);">${r[0]}</span>
                      <span style="font-size:13px;font-weight:700;color:${r[2] ? '#7ceaa6' : '#ff8b98'};">${r[1]}</span>
                    </div>`).join('')}
                  </div>`;
                ]]]
            styles:
              card:
                - border-radius: 18px
                - padding: 16px 18px 14px 18px
                - background: linear-gradient(145deg, rgba(20,28,45,0.98), rgba(10,15,27,0.98))
                - border: 1px solid rgba(255,255,255,0.08)
                - box-shadow: 0 10px 30px rgba(0,0,0,0.22)
              grid:
                - grid-template-areas: '"n" "health"'
                - grid-template-columns: 1fr
                - grid-template-rows: min-content 1fr
              name:
                - justify-self: start
                - font-size: 20px
                - font-weight: 700
                - color: rgba(255,255,255,0.92)
                - padding-bottom: 4px
              custom_fields:
                health:
                  - width: 100%
            grid_options:
              columns: 16
              rows: 8


          # ---- TEMPERATURE GRAPH ----
          - type: custom:button-card
            section_mode: true
            name: Daily Energy Totals
            show_icon: false
            show_state: false
            show_label: false
            tap_action:
              action: none
            custom_fields:
              bars: >
                [[[
                  const defs = [
                    ['PV', 'sensor.ecco_clock_dongle_ecco_day_pv_energy', '#ffbd3d', 'rgba(255,189,61,.28)'],
                    ['Load', 'sensor.ecco_clock_dongle_ecco_day_load_energy', '#42aaff', 'rgba(66,170,255,.28)'],
                    ['Import', 'sensor.ecco_clock_dongle_ecco_day_grid_import', '#ff6376', 'rgba(255,99,118,.25)'],
                    ['Export', 'sensor.ecco_clock_dongle_ecco_day_grid_export', '#b36cff', 'rgba(179,108,255,.25)'],
                    ['Batt<br>Charge', 'sensor.ecco_clock_dongle_ecco_day_battery_charge', '#39d27a', 'rgba(57,210,122,.25)'],
                    ['Batt<br>Discharge', 'sensor.ecco_clock_dongle_ecco_day_battery_discharge', '#65e39a', 'rgba(101,227,154,.25)']
                  ];
                  const vals = defs.map(d => {
                    const v = Number(states[d[1]]?.state);
                    return Number.isFinite(v) ? Math.max(v, 0) : 0;
                  });
                  const maxVal = Math.max(...vals, 1);
                  return `<div style="display:grid;grid-template-columns:repeat(6,minmax(0,1fr));gap:12px;align-items:end;height:195px;padding:4px 4px 0 4px;">
                    ${defs.map((d,i) => {
                      const v = vals[i];
                      const pct = v <= 0 ? 1 : Math.max(6, Math.round((v / maxVal) * 100));
                      const opacity = v <= 0 ? 0.25 : 1;
                      return `<div style="height:100%;display:flex;flex-direction:column;justify-content:flex-end;align-items:center;min-width:0;">
                        <div style="font-size:15px;font-weight:700;color:rgba(255,255,255,.92);margin-bottom:2px;">${v.toFixed(1)}</div>
                        <div style="font-size:10px;color:rgba(255,255,255,.52);margin-bottom:7px;">kWh</div>
                        <div style="width:62%;height:${pct}%;min-height:3px;max-height:128px;border-radius:9px 9px 3px 3px;background:${d[2]};opacity:${opacity};box-shadow:0 0 18px ${d[3]};"></div>
                        <div style="font-size:11px;font-weight:600;text-align:center;line-height:1.15;color:rgba(255,255,255,.68);margin-top:8px;min-height:27px;">${d[0]}</div>
                      </div>`;
                    }).join('')}
                  </div>`;
                ]]]
            styles:
              card:
                - border-radius: 18px
                - padding: 16px 18px 12px 18px
                - background: linear-gradient(145deg, rgba(20,28,45,0.98), rgba(10,15,27,0.98))
                - border: 1px solid rgba(255,255,255,0.08)
                - box-shadow: 0 10px 30px rgba(0,0,0,0.22)
              grid:
                - grid-template-areas: '"n" "bars"'
                - grid-template-columns: 1fr
                - grid-template-rows: min-content 1fr
              name:
                - justify-self: start
                - font-size: 20px
                - font-weight: 700
                - color: rgba(255,255,255,0.92)
                - padding-bottom: 4px
              custom_fields:
                bars:
                  - width: 100%
            grid_options:
              columns: 48
              rows: 4


""")
DASHBOARD_1_NEW = _blk(r"""
  - title: Overview
    path: ecco-overview
    icon: mdi:view-dashboard
    type: sections
    max_columns: 4
    dense_section_placement: true
    sections:
      # ================= S1 STATUS BANNER (span 4) =================
      - type: grid
        column_span: 4
        cards:
          # ---- ECCO STATUS HERO — READ-ONLY MONITORING ----
          # Visual summary only. This card is NOT a control-readiness gate and
          # does not call services or write any inverter setting.
          # OVW1: the same state machine, pills and vocabulary as before; compact (headline row + eight pills), the
          # live BATTERY / SOLAR / HOUSE / GRID tiles removed (the Energy Flow card shows them), and the Dump to Grid
          # lease states added to the inputs (D4) so an active or stuck Dump lease is visible at the top of the page.
          - type: custom:button-card
            section_mode: true
            name: ECCO Pro
            icon: mdi:home-lightning-bolt
            show_name: true
            show_icon: true
            show_state: false
            tap_action:
              action: none
            custom_fields:
              body: >
                [[[
                  const get = id => states[id]?.state ?? 'unknown';
                  const num = id => {
                    const v = Number(get(id));
                    return Number.isFinite(v) ? v : null;
                  };
                  const unknown = v => ['unknown','unavailable','none',''].includes(String(v).toLowerCase());
                  const comm = get('sensor.ecco_health_communications');
                  const runtime = get('sensor.ecco_health_runtime_configuration');
                  const telemetry = get('binary_sensor.ecco_clock_dongle_telemetry_online');
                  const configOnline = get('binary_sensor.ecco_clock_dongle_configuration_online');
                  const ntp = get('binary_sensor.ecco_clock_dongle_ntp_synced');
                  const cache = get('binary_sensor.ecco_clock_dongle_manual_configuration_raw_cache_valid');
                  const inverter = get('sensor.ecco_clock_dongle_ecco_inverter_system_state');
                  const warning = get('sensor.ecco_clock_dongle_ecco_inverter_warning');
                  const fault = get('sensor.ecco_clock_dongle_ecco_inverter_fault');
                  const manualState = get('binary_sensor.ecco_clock_dongle_manual_write_in_progress');
                  const rtcState = get('binary_sensor.ecco_clock_dongle_rtc_correction_in_progress');
                  const freeOpState = get('binary_sensor.ecco_clock_dongle_free_power_operation_in_progress');
                  const freeActiveState = get('binary_sensor.ecco_clock_dongle_free_power_active');
                  const dumpOpState = get('binary_sensor.ecco_clock_dongle_dump_to_grid_operation_in_progress');
                  const dumpActiveState = get('binary_sensor.ecco_clock_dongle_dump_to_grid_active');
                  const manualBusy = manualState === 'on';
                  const rtcBusy = rtcState === 'on';
                  const freeBusy = freeOpState === 'on';
                  const freeActive = freeActiveState === 'on';
                  const dumpBusy = dumpOpState === 'on';
                  const dumpActive = dumpActiveState === 'on';
                  const snapshot = get('binary_sensor.ecco_clock_dongle_free_power_snapshot_valid');
                  const snapshotPending = snapshot === 'on' && !freeActive && !freeBusy;
                  // OVW1 (D4): the Dump to Grid lease states join the same inputs (display only).
                  const dumpSnapshot = get('binary_sensor.ecco_clock_dongle_dump_to_grid_snapshot_valid');
                  const dumpSnapshotPending = dumpSnapshot === 'on' && !dumpActive && !dumpBusy;
                  // FB-B3: display words only (sensor.ecco_supervision_status / sensor.ecco_fallback_status).
                  // Deliberately NOT in `required` (a fallback Unknown must not turn the headline into
                  // STATUS PARTIAL) and only supervision Lost is hardAttention; fallback states are not.
                  const sup = get('sensor.ecco_supervision_status');
                  const fb = get('sensor.ecco_fallback_status');

                  const required = [comm,runtime,telemetry,configOnline,ntp,cache,inverter,warning,fault,manualState,rtcState,freeOpState,freeActiveState,snapshot,dumpOpState,dumpActiveState,dumpSnapshot];
                  const hasUnknown = required.some(unknown);
                  const hardAttention =
                    comm !== 'HEALTHY' ||
                    runtime !== 'HEALTHY' ||
                    telemetry !== 'on' ||
                    configOnline !== 'on' ||
                    ntp !== 'on' ||
                    cache !== 'on' ||
                    String(inverter).toLowerCase() !== 'normal' ||
                    warning !== '00000000' ||
                    fault !== '0000000000000000' ||
                    snapshotPending ||
                    dumpSnapshotPending ||
                    sup === 'Lost';
                  const busy = manualBusy || rtcBusy || freeBusy || freeActive || dumpBusy || dumpActive;

                  let headline, subline, colour, bg, border, icon;
                  if (hasUnknown) {
                    headline = 'STATUS PARTIAL';
                    subline = 'One or more monitoring inputs are unavailable';
                    colour = '#aab4c3';
                    bg = 'rgba(170,180,195,.08)';
                    border = 'rgba(170,180,195,.22)';
                    icon = 'mdi:help-circle-outline';
                  } else if (hardAttention) {
                    headline = 'ATTENTION';
                    subline = 'A monitored subsystem needs checking';
                    colour = '#ffbd3d';
                    bg = 'rgba(255,189,61,.10)';
                    border = 'rgba(255,189,61,.30)';
                    icon = 'mdi:alert-outline';
                  } else if (busy) {
                    headline = freeActive ? 'FREE POWER ACTIVE' : dumpActive ? 'DUMP TO GRID ACTIVE' : 'OPERATION IN PROGRESS';
                    subline = 'ECCO is healthy and a legitimate transaction is active';
                    colour = '#66b3ff';
                    bg = 'rgba(102,179,255,.10)';
                    border = 'rgba(102,179,255,.30)';
                    icon = freeActive ? 'mdi:flash' : 'mdi:progress-clock';
                  } else {
                    headline = 'SYSTEMS NOMINAL';
                    subline = 'Live monitoring inputs are healthy';
                    colour = '#55e58e';
                    bg = 'rgba(85,229,142,.08)';
                    border = 'rgba(85,229,142,.24)';
                    icon = 'mdi:shield-check';
                  }

                  const pill = (label, value, tone='good') => {
                    const tones = {
                      good: ['#55e58e','rgba(85,229,142,.08)','rgba(85,229,142,.20)'],
                      info: ['#66b3ff','rgba(102,179,255,.08)','rgba(102,179,255,.20)'],
                      warn: ['#ffbd3d','rgba(255,189,61,.08)','rgba(255,189,61,.22)'],
                      muted: ['#aab4c3','rgba(170,180,195,.06)','rgba(170,180,195,.15)']
                    };
                    const t = tones[tone] || tones.muted;
                    return `<div style="padding:8px 10px;border-radius:11px;background:${t[1]};border:1px solid ${t[2]};min-width:0;">
                      <div style="font-size:9px;letter-spacing:.55px;color:rgba(255,255,255,.46);font-weight:800;">${label}</div>
                      <div style="margin-top:2px;color:${t[0]};font-size:12px;font-weight:800;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">${value}</div>
                    </div>`;
                  };

                  const chipState = (ok, active=false, unknownState=false) =>
                    unknownState ? ['UNKNOWN','muted'] : active ? ['ACTIVE','info'] : ok ? ['HEALTHY','good'] : ['CHECK','warn'];

                  const commChip = chipState(comm === 'HEALTHY', false, unknown(comm));
                  const runtimeChip = chipState(runtime === 'HEALTHY', false, unknown(runtime));
                  const rtcChip = chipState(ntp === 'on', rtcBusy, unknown(ntp) || unknown(rtcState));
                  const invChip = chipState(String(inverter).toLowerCase() === 'normal' && warning === '00000000' && fault === '0000000000000000', false, unknown(inverter) || unknown(warning) || unknown(fault));
                  const txUnknown = unknown(manualState) || unknown(freeOpState) || unknown(freeActiveState) || unknown(dumpOpState) || unknown(dumpActiveState);
                  const txChip = chipState(true, manualBusy || freeBusy || freeActive || dumpBusy || dumpActive, txUnknown);
                  const recoveryChip = chipState(!snapshotPending && !dumpSnapshotPending, false, unknown(snapshot) || unknown(freeActiveState) || unknown(dumpSnapshot) || unknown(dumpActiveState));
                  const supChips = {'Healthy': ['HEALTHY', 'good'], 'Recovering': ['RECOVERING', 'info'], 'Awaiting Heartbeat': ['AWAITING', 'muted'], 'Suspect': ['SUSPECT', 'warn'], 'Lost': ['LOST', 'warn']};
                  const supChip = supChips[sup] || ['UNKNOWN', 'muted'];
                  const fbChips = {'Ready': ['READY', 'good'], 'Drifted': ['DRIFTED', 'warn'], 'Not Captured': ['NOT SAVED', 'muted'], 'Invalidated': ['INVALIDATED', 'muted'], 'Blocked': ['BLOCKED', 'warn'], 'Shadow Recovery': ['SHADOW', 'warn']};
                  const fbChip = fbChips[fb] || ['UNKNOWN', 'muted'];

                  return `<div>
                    <div style="display:flex;align-items:center;justify-content:space-between;gap:14px;padding:10px 12px;border-radius:12px;background:${bg};border:1px solid ${border};">
                      <div style="display:flex;align-items:center;gap:12px;min-width:0;">
                        <ha-icon icon="${icon}" style="width:26px;height:26px;color:${colour};flex:0 0 auto;"></ha-icon>
                        <div style="min-width:0;">
                          <div style="font-size:22px;font-weight:900;letter-spacing:.25px;color:${colour};">${headline}</div>
                          <div style="font-size:12px;color:rgba(255,255,255,.62);margin-top:2px;">${subline}</div>
                        </div>
                      </div>
                      <div style="font-size:10px;font-weight:800;letter-spacing:.45px;color:rgba(255,255,255,.42);text-align:right;line-height:1.4;flex:0 0 auto;">
                        MONITORING ONLY<br>NOT A CONTROL GATE
                      </div>
                    </div>

                    <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(105px,1fr));gap:6px;margin-top:8px;">
                      ${pill('COMMS', commChip[0], commChip[1])}
                      ${pill('RUNTIME CONFIG', runtimeChip[0], runtimeChip[1])}
                      ${pill('RTC / NTP', rtcChip[0], rtcChip[1])}
                      ${pill('INVERTER', invChip[0], invChip[1])}
                      ${pill('TRANSACTIONS', txChip[0], txChip[1])}
                      ${pill('RECOVERY', recoveryChip[0], recoveryChip[1])}
                      ${pill('SUPERVISION', supChip[0], supChip[1])}
                      ${pill('FALLBACK', fbChip[0], fbChip[1])}
                    </div>
                  </div>`;
                ]]]
            styles:
              card:
                - border-radius: 16px
                - padding: 12px 14px
                - background: linear-gradient(145deg, rgba(20,28,45,0.98), rgba(10,15,27,0.98))
                - border: 1px solid rgba(255,255,255,0.08)
                - box-shadow: 0 10px 30px rgba(0,0,0,0.22)
              grid:
                - grid-template-areas: '"i n" "body body"'
                - grid-template-columns: 30px 1fr
                - grid-template-rows: min-content 1fr
                - row-gap: 8px
              icon:
                - width: 22px
                - color: '#8f7cff'
              name:
                - justify-self: start
                - align-self: center
                - font-size: 15px
                - font-weight: 700
                - color: rgba(255,255,255,0.92)
              custom_fields:
                body:
                  - justify-self: stretch
                  - align-self: start
                  - width: 100%
            grid_options:
              columns: full
              rows: auto

      # ================= S2 PV FORECAST STRIP (span 4) =================
      # The read-only Weather & Solar card in its compact solar layout: the ECCO blend totals (today / remaining /
      # tomorrow with their Solcast and Forecast.Solar inputs), the hourly curve and the source freshness. It reads
      # the blend sensors exactly as the full card on the Weather & Solar view does and sends no command. Entity ids
      # are the card's own defaults.
      - type: grid
        column_span: 4
        cards:
          - type: custom:ecco-weather-solar-card
            layout: solar_strip
            grid_options:
              columns: full
              rows: auto

      # ================= S3 ENERGY FLOW (span 3) =================
      - type: grid
        column_span: 3
        cards:
          # ---- LIVE ENERGY FLOW — PRIMARY OVERVIEW ----
          - type: custom:ecco-energy-flow-card
            title: ECCO Energy Flow

            nodes:
              solar:
                - label: Array 1
                  power: sensor.ecco_clock_dongle_ecco_pv1_power
                - label: Array 2
                  power: sensor.ecco_clock_dongle_ecco_pv2_power
              solar_total: sensor.ecco_pv_power

              inverter:
                power: sensor.ecco_clock_dongle_ecco_inverter_output_power
                state: sensor.ecco_clock_dongle_ecco_inverter_system_state

              home:
                power: sensor.ecco_house_power

              battery:
                power: sensor.ecco_clock_dongle_ecco_battery_output_power
                soc: sensor.ecco_battery_soc
                power_sign: discharge_positive

              grid:
                power: sensor.ecco_grid_power
                power_sign: import_positive

            today:
              solar: sensor.ecco_clock_dongle_ecco_day_pv_energy
              load: sensor.ecco_clock_dongle_ecco_day_load_energy
              import: sensor.ecco_clock_dongle_ecco_day_grid_import
              export: sensor.ecco_clock_dongle_ecco_day_grid_export
              battery_charge: sensor.ecco_clock_dongle_ecco_day_battery_charge
              battery_discharge: sensor.ecco_clock_dongle_ecco_day_battery_discharge

            features:
              self_sufficiency: false
              solar_contribution: true
              animate_flow: true
              compact_today: true
              show_details_panel: false

            format:
              precision: 2
              energy_precision: 1
              power_unit: auto

            grid_options:
              columns: full
              rows: auto
            card_mod:
              style: |
                ha-card {
                  border: 1px solid rgba(255,255,255,0.08);
                  box-shadow: 0 12px 32px rgba(0,0,0,0.22);
                }


      # ================= S4 RIGHT COLUMN (span 1): grid status, current plan, next days, tariff =================
      - type: grid
        column_span: 1
        cards:
          # ---- GRID / OUTAGE STATUS (slim) ----
          - type: custom:button-card
            section_mode: true
            name: Grid Status
            icon: mdi:transmission-tower
            show_name: true
            show_icon: true
            show_state: false
            tap_action:
              action: none
            custom_fields:
              body: >
                [[[
                  const gridState = states['binary_sensor.ecco_clock_dongle_ecco_grid_connected']?.state;
                  const on = gridState === 'on';
                  const n = id => {
                    const v = Number(states[id]?.state);
                    return Number.isFinite(v) ? v : null;
                  };
                  const voltage = n('sensor.ecco_clock_dongle_ecco_grid_voltage_l1');
                  const freq = n('sensor.ecco_clock_dongle_ecco_grid_frequency');
                  const grid = n('sensor.ecco_clock_dongle_ecco_grid_power_ct_clamp');
                  const battery = n('sensor.ecco_clock_dongle_ecco_battery_output_power');
                  const fmt = (v,d=0) => v === null ? '--' : v.toFixed(d);
                  const absGrid = grid === null ? null : Math.abs(grid);
                  const absBatt = battery === null ? null : Math.abs(battery);
                  const gridNeutral = grid !== null && Math.abs(grid) <= 40;
                  const battDischarging = battery !== null && battery > 100;
                  const battCharging = battery !== null && battery < -100;

                  let flow, detail, colour, bg, border;
                  if (!on) {
                    flow = 'GRID OUTAGE';
                    detail = 'Mains supply lost';
                    colour = '#ff5f6d';
                    bg = 'rgba(255,95,109,.12)';
                    border = 'rgba(255,95,109,.40)';
                  } else if (grid === null) {
                    flow = 'GRID POWER UNKNOWN';
                    detail = 'No CT power reading';
                    colour = '#ffbd3d';
                    bg = 'rgba(255,189,61,.10)';
                    border = 'rgba(255,189,61,.30)';
                  } else if (grid < -40) {
                    flow = `EXPORTING ${(absGrid/1000).toFixed(2)} kW`;
                    detail = 'Sending surplus power to the grid';
                    colour = '#c07cff';
                    bg = 'rgba(192,124,255,.12)';
                    border = 'rgba(192,124,255,.42)';
                  } else if (grid > 40) {
                    flow = `IMPORTING ${(absGrid/1000).toFixed(2)} kW`;
                    detail = 'Drawing power from the grid';
                    colour = '#66b3ff';
                    bg = 'rgba(102,179,255,.11)';
                    border = 'rgba(102,179,255,.36)';
                  } else if (gridNeutral && battDischarging) {
                    flow = `BATTERY SUPPLYING HOUSE ${(absBatt/1000).toFixed(2)} kW`;
                    detail = `Grid near zero • ${fmt(grid)} W grid • battery carrying the load`;
                    colour = '#55e58e';
                    bg = 'rgba(85,229,142,.08)';
                    border = 'rgba(85,229,142,.24)';
                  } else if (gridNeutral && battCharging) {
                    flow = `BATTERY CHARGING ${(absBatt/1000).toFixed(2)} kW`;
                    detail = `Grid near zero • ${fmt(grid)} W grid • battery absorbing surplus`;
                    colour = '#42aaff';
                    bg = 'rgba(66,170,255,.10)';
                    border = 'rgba(66,170,255,.30)';
                  } else {
                    flow = 'GRID NEUTRAL';
                    detail = 'Import/export near zero • battery near idle';
                    colour = '#55e58e';
                    bg = 'rgba(85,229,142,.08)';
                    border = 'rgba(85,229,142,.24)';
                  }
                  const gridWord = on ? 'Grid connected' : gridState === 'off' ? 'Grid disconnected' : 'Unknown';
                  const gridTone = on ? ['#55e58e','rgba(85,229,142,.08)','rgba(85,229,142,.22)']
                    : gridState === 'off' ? ['#ff5f6d','rgba(255,95,109,.12)','rgba(255,95,109,.40)']
                    : ['#aab4c3','rgba(170,180,195,.06)','rgba(170,180,195,.15)'];
                  const chip = (text, t) => `<span style="display:inline-flex;align-items:center;padding:4px 9px;border-radius:999px;font-size:11px;font-weight:800;white-space:nowrap;color:${t[0]};background:${t[1]};border:1px solid ${t[2]};">${text}</span>`;
                  const muted = ['#aab4c3','rgba(170,180,195,.06)','rgba(170,180,195,.15)'];
                  return `<div>
                    <div style="padding:9px 11px;border-radius:11px;background:${bg};border:1px solid ${border};">
                      <div style="font-size:20px;font-weight:900;letter-spacing:.3px;color:${colour};">${flow}</div>
                      <div style="font-size:12px;color:rgba(255,255,255,.68);margin-top:2px;">${detail}</div>
                    </div>
                    <div style="display:flex;flex-wrap:wrap;gap:6px;margin-top:8px;">
                      ${chip(`${fmt(voltage,1)} V`, muted)}
                      ${chip(`${fmt(freq,2)} Hz`, muted)}
                      ${chip(gridWord, gridTone)}
                    </div>
                  </div>`;
                ]]]
            styles:
              card:
                - border-radius: 16px
                - padding: 12px 14px
                - background: linear-gradient(145deg, rgba(20,28,45,0.98), rgba(10,15,27,0.98))
                - border: 1px solid rgba(255,255,255,0.08)
                - box-shadow: 0 10px 30px rgba(0,0,0,0.22)
              grid:
                - grid-template-areas: '"i n" "body body"'
                - grid-template-columns: 30px 1fr
                - grid-template-rows: min-content 1fr
                - row-gap: 8px
              icon:
                - width: 20px
                - color: '#7ab8ff'
              name:
                - justify-self: start
                - align-self: center
                - font-size: 15px
                - font-weight: 700
                - color: rgba(255,255,255,0.92)
              custom_fields:
                body:
                  - justify-self: stretch
                  - width: 100%
            grid_options:
              columns: full
              rows: auto

          # ---- CURRENT TOU / OPERATING PLAN (slim) ----
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
                  const detailLine = [line1, line2].filter(Boolean).join(' • ');

                  return `<div>
                    <div style="display:flex;align-items:baseline;gap:8px;flex-wrap:wrap;">
                      <span style="font-size:20px;font-weight:800;color:#ffffff;">Slot ${s.i}</span>
                      <span style="font-size:14px;font-weight:700;color:#b8adff;">${s.startText}–${s.endText}</span>
                    </div>
                    <div style="font-size:12px;color:rgba(255,255,255,0.64);margin-top:2px;line-height:1.5;">${detailLine}</div>
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
                  return `<div style="padding:7px 10px;border-radius:10px;
                    background:rgba(255,255,255,0.035);border:1px solid rgba(255,255,255,0.07);
                    font-size:12px;color:rgba(255,255,255,0.67);">
                    Next transition <b style="color:#fff;">${best.t}</b> • ${left}
                  </div>`;
                ]]]
              access: >
                [[[
                  return `<div style="display:flex;align-items:center;gap:5px;text-align:right;line-height:1.25;
                    color:#55e58e;font-size:10px;font-weight:800;letter-spacing:.45px;text-transform:uppercase;">
                    <ha-icon icon="mdi:shield-check" style="width:14px;flex:none;"></ha-icon>
                    <span>Observe only<br>no setting writes</span>
                  </div>`;
                ]]]
            styles:
              card:
                - border-radius: 16px
                - padding: 12px 14px
                - background: linear-gradient(145deg, rgba(20,28,45,0.98), rgba(10,15,27,0.98))
                - border: 1px solid rgba(255,255,255,0.08)
                - box-shadow: 0 10px 30px rgba(0,0,0,0.22)
              grid:
                - grid-template-areas: '"i n mode" "slot slot slot" "next next access"'
                - grid-template-columns: 30px 1fr auto
                - grid-template-rows: min-content 1fr min-content
                - row-gap: 8px
                - column-gap: 8px
              icon:
                - width: 20px
                - color: '#b8adff'
              name:
                - justify-self: start
                - align-self: center
                - font-size: 15px
                - font-weight: 700
                - color: rgba(255,255,255,0.92)
              custom_fields:
                mode:
                  - justify-self: end
                  - align-self: center
                slot:
                  - justify-self: stretch
                next:
                  - justify-self: stretch
                access:
                  - justify-self: end
                  - align-self: center
            grid_options:
              columns: full
              rows: auto

          # ---- NEXT DAYS (the Weather & Solar card's compact daily layout; Met.no, read-only) ----
          - type: custom:ecco-weather-solar-card
            layout: daily_compact
            daily_days: 7
            grid_options:
              columns: full
              rows: auto

          # ---- TARIFF NOW (the ECCO tariff template sensors; display only) ----
          - type: custom:button-card
            section_mode: true
            name: Tariff now
            icon: mdi:cash-clock
            show_name: true
            show_icon: true
            show_state: false
            tap_action:
              action: none
            custom_fields:
              band: >
                [[[
                  const raw = states['sensor.ecco_tariff_band']?.state;
                  const unknown = raw === undefined || ['unknown','unavailable','none',''].includes(String(raw).toLowerCase());
                  const band = unknown ? '--' : String(raw);
                  const key = band.toLowerCase();
                  const t = key === 'peak' ? ['#ff5f6d','rgba(255,95,109,.12)','rgba(255,95,109,.40)']
                    : key === 'cheap' ? ['#55e58e','rgba(85,229,142,.08)','rgba(85,229,142,.22)']
                    : key === 'standard' ? ['#66b3ff','rgba(102,179,255,.08)','rgba(102,179,255,.22)']
                    : ['#aab4c3','rgba(170,180,195,.06)','rgba(170,180,195,.15)'];
                  return `<span style="display:inline-flex;align-items:center;padding:4px 9px;border-radius:999px;font-size:10px;font-weight:800;letter-spacing:.45px;white-space:nowrap;color:${t[0]};background:${t[1]};border:1px solid ${t[2]};">${band.toUpperCase()}</span>`;
                ]]]
              body: >
                [[[
                  const n = id => {
                    const v = Number(states[id]?.state);
                    return Number.isFinite(v) ? v : null;
                  };
                  const p = (v, d=1) => v === null ? '--' : v.toFixed(d);
                  const imp = n('sensor.ecco_import_rate');
                  const exp = n('sensor.ecco_export_rate');
                  const cheap = n('sensor.ecco_today_cheap_import_rate');
                  const peak = n('sensor.ecco_today_peak_import_rate');
                  const spread = n('sensor.ecco_import_export_spread');
                  const next = n('sensor.ecco_next_import_rate');
                  const tile = (label, value, colour) => `<div style="padding:8px 10px;border-radius:11px;background:rgba(255,255,255,.035);border:1px solid rgba(255,255,255,.07);min-width:0;">
                    <div style="font-size:10px;font-weight:700;letter-spacing:.45px;color:rgba(255,255,255,.46);">${label}</div>
                    <div style="font-size:17px;font-weight:800;color:${colour};margin-top:1px;">${value} <span style="font-size:11px;color:rgba(255,255,255,.62);font-weight:700;">p/kWh</span></div>
                  </div>`;
                  return `<div>
                    <div style="display:grid;grid-template-columns:1fr 1fr;gap:6px;">
                      ${tile('IMPORT', p(imp), '#7ab8ff')}
                      ${tile('EXPORT', p(exp), '#b36cff')}
                    </div>
                    <div style="font-size:12px;color:rgba(255,255,255,.62);margin-top:6px;">Today ${p(cheap)}–${p(peak)} p/kWh • spread ${p(spread)} p • next rate ${p(next)} p</div>
                  </div>`;
                ]]]
            styles:
              card:
                - border-radius: 16px
                - padding: 12px 14px
                - background: linear-gradient(145deg, rgba(20,28,45,0.98), rgba(10,15,27,0.98))
                - border: 1px solid rgba(255,255,255,0.08)
                - box-shadow: 0 10px 30px rgba(0,0,0,0.22)
              grid:
                - grid-template-areas: '"i n band" "body body body"'
                - grid-template-columns: 30px 1fr auto
                - grid-template-rows: min-content 1fr
                - row-gap: 8px
                - column-gap: 8px
              icon:
                - width: 20px
                - color: '#b36cff'
              name:
                - justify-self: start
                - align-self: center
                - font-size: 15px
                - font-weight: 700
                - color: rgba(255,255,255,0.92)
              custom_fields:
                band:
                  - justify-self: end
                  - align-self: center
                body:
                  - justify-self: stretch
                  - width: 100%
            grid_options:
              columns: full
              rows: auto

      # ================= S5 ENERGY ACTIONS (tabbed) + KNOWN-GOOD PROFILE (span 2) =================
      # OVW1: the Known-Good Profile tile (directly after the Energy Actions card, behind its FB-B3 marker) renders as
      # one slim bar: label · state word · subline and saved summary · OPEN THE SAFETY TAB.
      - type: grid
        column_span: 2
        cards:
          # ---- ENERGY ACTIONS (v7.16.0) - supersedes BOTH the v7.14.0
          # compact Free Power control strip AND the v7.14.0 Scheduled Free
          # Power strip that used to sit beneath it. Free Power is a
          # single product feature (staged controls, two-step arm/start
          # safety model, all seven live hardware states, plus an integrated
          # NOW/LATER selector for the existing Scheduled Free Power
          # package) via the dedicated ecco-energy-actions-card. On branch
          # feature/manual-dump-to-grid-v1 (2026-09-26, NOT yet merged or
          # live-proven - see VERSION.yaml, still at 7.16.0/main), this card
          # config was additionally wired up for Manual Dump-to-Grid V1
          # (battery -> grid export sibling of Free Power) as a real,
          # interactive tile. See docs/DUMP_TO_GRID_V1.md and
          # frontend/ecco-energy-actions-card/README.md. Neither schedule
          # package's own entities/automations
          # (home-assistant/packages/ecco_free_power_schedule.yaml,
          # home-assistant/packages/ecco_dump_to_grid_schedule.yaml) are
          # duplicated here - this card only presents and drives them.
          - type: custom:ecco-energy-actions-card
            title: Energy Actions
            layout: tabbed

            free_power:
              active: binary_sensor.ecco_clock_dongle_free_power_active
              operation_in_progress: binary_sensor.ecco_clock_dongle_free_power_operation_in_progress
              snapshot_valid: binary_sensor.ecco_clock_dongle_free_power_snapshot_valid
              status: sensor.ecco_clock_dongle_free_power_status
              ends_at: sensor.ecco_clock_dongle_free_power_ends_at
              failures: sensor.ecco_clock_dongle_free_power_failures_since_boot
              start_attempts: sensor.ecco_clock_dongle_free_power_start_attempts_since_boot
              start_successes: sensor.ecco_clock_dongle_free_power_start_successes_since_boot
              restore_successes: sensor.ecco_clock_dongle_free_power_restore_successes_since_boot
              write_enable: switch.ecco_clock_dongle_free_power_write_enable
              max_charge_power: number.ecco_clock_dongle_free_power_max_charge_power
              duration: number.ecco_clock_dongle_free_power_duration
              start: button.ecco_clock_dongle_start_free_power_charge_now
              end_restore: button.ecco_clock_dongle_end_free_power_restore_now

            schedule:
              armed: input_boolean.ecco_free_power_schedule_armed
              start: input_datetime.ecco_free_power_schedule_start
              duration: input_number.ecco_free_power_schedule_duration
              power: input_number.ecco_free_power_schedule_power
              last_result: input_text.ecco_free_power_schedule_last_result
              status: sensor.ecco_free_power_schedule_status
              cancel: script.ecco_free_power_cancel_schedule

            # Manual Dump-to-Grid V1 (2026-09-26) - NOT LIVE-PROVEN. Every
            # entity id below matches
            # firmware/ecco_clock_dongle_stage3_4_free_power.yaml's
            # Dump-to-Grid section; `schedule:` maps exactly the helpers
            # home-assistant/packages/ecco_dump_to_grid_schedule.yaml defines
            # (NOW/LATER selector, same pattern as Free Power).
            dump_to_grid:
              active: binary_sensor.ecco_clock_dongle_dump_to_grid_active
              operation_in_progress: binary_sensor.ecco_clock_dongle_dump_to_grid_operation_in_progress
              snapshot_valid: binary_sensor.ecco_clock_dongle_dump_to_grid_snapshot_valid
              status: sensor.ecco_clock_dongle_dump_to_grid_status
              ends_at: sensor.ecco_clock_dongle_dump_to_grid_ends_at
              battery_soc: sensor.ecco_clock_dongle_ecco_battery_soc
              failures: sensor.ecco_clock_dongle_dump_to_grid_failures_since_boot
              start_attempts: sensor.ecco_clock_dongle_dump_to_grid_start_attempts_since_boot
              start_successes: sensor.ecco_clock_dongle_dump_to_grid_start_successes_since_boot
              restore_successes: sensor.ecco_clock_dongle_dump_to_grid_restore_successes_since_boot
              write_enable: switch.ecco_clock_dongle_dump_to_grid_write_enable
              export_power: number.ecco_clock_dongle_dump_to_grid_export_power
              stop_soc: number.ecco_clock_dongle_dump_to_grid_stop_soc
              duration: number.ecco_clock_dongle_dump_to_grid_duration
              start: button.ecco_clock_dongle_start_dump_to_grid_now
              end_restore: button.ecco_clock_dongle_end_dump_to_grid_restore_now
              active_export_power: sensor.ecco_clock_dongle_dump_to_grid_active_export_power
              active_stop_soc: sensor.ecco_clock_dongle_dump_to_grid_active_stop_soc
              last_end_reason: sensor.ecco_clock_dongle_dump_to_grid_last_end_reason
              recovery_arm: switch.ecco_clock_dongle_dump_to_grid_recovery_arm
              recovery_force_restore: button.ecco_clock_dongle_dump_to_grid_force_restore_original
              recovery_accept: button.ecco_clock_dongle_dump_to_grid_accept_current_state
              recovery_state: sensor.ecco_clock_dongle_dump_to_grid_recovery_state
              schedule:
                armed: input_boolean.ecco_dump_to_grid_schedule_armed
                start: input_datetime.ecco_dump_to_grid_schedule_start
                duration: input_number.ecco_dump_to_grid_schedule_duration
                power: input_number.ecco_dump_to_grid_schedule_power
                stop_soc: input_number.ecco_dump_to_grid_schedule_stop_soc
                last_result: input_text.ecco_dump_to_grid_schedule_last_result
                status: sensor.ecco_dump_to_grid_schedule_status
                cancel: script.ecco_dump_to_grid_cancel_schedule

            grid_options:
              columns: full
              rows: auto
            card_mod:
              style: |
                ha-card {
                  border: 1px solid rgba(255,255,255,0.08);
                  box-shadow: 0 12px 32px rgba(0,0,0,0.22);
                }

          # ---- KNOWN-GOOD PROFILE (FB-B3; READ-ONLY tile) ----
          # Display only: state word + subline of sensor.ecco_fallback_status and a one-line summary
          # of the saved profile. No write action here - tap opens the standard more-info dialog.
          # Saving, arming and invalidating live ONLY on the Safety view.
          - type: custom:button-card
            section_mode: true
            entity: sensor.ecco_fallback_status
            name: Known-Good Profile
            icon: mdi:shield-check-outline
            show_name: true
            show_icon: true
            show_state: false
            tap_action:
              action: more-info
            custom_fields:
              body: >
                [[[
                  const get = id => states[id]?.state ?? 'unknown';
                  const word = get('sensor.ecco_fallback_status');
                  const sub = states['sensor.ecco_fallback_status']?.attributes?.subline ?? '';
                  const b2 = ';' + get('sensor.ecco_clock_dongle_ecco_fallback_profile_summary') + ';';
                  const kv = k => { const i = b2.indexOf(';' + k + '='); return i < 0 ? '-' : b2.slice(i + k.length + 2).split(';')[0]; };
                  const g = kv('g'), id = kv('id'), at = kv('at');
                  const tones = {
                    'Ready': '#55e58e', 'Drifted': '#ffbd3d', 'Blocked': '#ffbd3d', 'Shadow Recovery': '#ffbd3d',
                    'Not Captured': '#aab4c3', 'Invalidated': '#aab4c3', 'Unknown': '#aab4c3'
                  };
                  const colour = tones[word] || '#aab4c3';
                  const when = at === '0' ? 'capture time unknown' : new Date(Number(at) * 1000).toLocaleString();
                  const saved = g === '-' ? 'No profile saved yet' : `Saved ${when} · generation ${g} · ID ${id.slice(0, 8)}`;
                  const line = [sub, saved].filter(Boolean).join(' · ');
                  return `<div style="display:flex;align-items:center;gap:12px;flex-wrap:wrap;min-width:0;">
                    <div style="font-size:20px;font-weight:900;letter-spacing:.3px;color:${colour};white-space:nowrap;">${String(word).toUpperCase()}</div>
                    <div style="flex:1 1 220px;min-width:0;font-size:12px;color:rgba(255,255,255,.62);">${line}</div>
                    <div style="font-size:10px;font-weight:800;letter-spacing:.45px;color:rgba(255,255,255,.42);white-space:nowrap;">OPEN THE SAFETY TAB</div>
                  </div>`;
                ]]]
            styles:
              card:
                - border-radius: 16px
                - padding: 10px 14px
                - background: linear-gradient(145deg, rgba(20,28,45,0.98), rgba(10,15,27,0.98))
                - border: 1px solid rgba(255,255,255,0.08)
                - box-shadow: 0 10px 30px rgba(0,0,0,0.22)
              grid:
                - grid-template-areas: '"i n body"'
                - grid-template-columns: 22px auto 1fr
                - grid-template-rows: min-content
                - column-gap: 10px
              icon:
                - width: 18px
                - color: '#8f7cff'
              name:
                - justify-self: start
                - align-self: center
                - font-size: 11px
                - font-weight: 800
                - text-transform: uppercase
                - letter-spacing: 0.05em
                - color: rgba(255,255,255,0.5)
              custom_fields:
                body:
                  - justify-self: stretch
                  - align-self: center
                  - width: 100%
            grid_options:
              columns: full
              rows: auto

      # ================= S6 DECISION SUPPORT (span 2): ECCO Today, battery estimate, scheduled sessions =================
      - type: grid
        column_span: 2
        cards:
          # ---- ECCO TODAY / DECISION ENGINE ----
          # Dashboard-only modelling. It reads ECCO + Forecast.Solar + sun.sun.
          # No inverter setting writes are performed.
          # OVW1: the status chip and the recommendation stay as they were; the five metric boxes and the Solar model
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
                  const batt = n('sensor.ecco_clock_dongle_ecco_battery_output_power');
                  const grid = n('sensor.ecco_clock_dongle_ecco_grid_power_ct_clamp');
                  const gen = n('sensor.ecco_clock_dongle_ecco_generator_port_power');

                  let label = 'System balanced';
                  let colour = '#7ab8ff';
                  if (gen > 100) {
                    label = 'Generator / AUX active'; colour = '#6ed6c5';
                  } else if (grid > 300 && batt < -250) {
                    label = 'Grid charging battery'; colour = '#b36cff';
                  } else if (pv > 300 && batt < -200) {
                    label = 'Solar charging battery'; colour = '#ffbd3d';
                  } else if (pv > load * 0.80 && grid < 150) {
                    label = 'Solar carrying the house'; colour = '#ffbd3d';
                  } else if (batt > 250 && grid < 150) {
                    label = 'Battery carrying the house'; colour = '#39d27a';
                  } else if (grid > 300) {
                    label = 'Grid supporting the house'; colour = '#7ab8ff';
                  } else if (pv > 150 && batt > 100) {
                    label = 'Solar + battery supplying house'; colour = '#55e58e';
                  } else if (pv < 50 && batt > 100) {
                    label = 'Battery supplying house'; colour = '#39d27a';
                  }

                  return `<span style="
                    display:inline-flex;align-items:center;gap:8px;padding:6px 11px;
                    border-radius:999px;background:${colour}1f;border:1px solid ${colour}55;
                    color:${colour};font-weight:700;font-size:13px;">
                    <span style="width:8px;height:8px;border-radius:50%;background:${colour};box-shadow:0 0 8px ${colour};"></span>
                    ${label}
                  </span>`;
                ]]]
              recommendation: >
                [[[
                  const n = (id) => Number(states[id]?.state ?? 0);
                  const clamp = (v,a,b) => Math.max(a,Math.min(b,v));
                  const pv = n('sensor.ecco_clock_dongle_ecco_pv_power');
                  const load = n('sensor.ecco_clock_dongle_ecco_load_power');
                  const soc = n('sensor.ecco_clock_dongle_ecco_battery_soc');
                  const loadToday = n('sensor.ecco_clock_dongle_ecco_day_load_energy');
                  const capAh = n('sensor.ecco_clock_dongle_ecco_battery_capacity_ah') || 620;
                  const capKwh = capAh * 51.2 / 1000;

                  const sensors = Object.values(states).filter(s => s.entity_id.startsWith('sensor.'));
                  const events = Object.values(states).filter(s => s.entity_id.startsWith('event.'));
                  const friendly = (s) => String(s?.attributes?.friendly_name ?? s?.entity_id ?? '').toLowerCase();
                  const find = (need, exclude=[]) => sensors.find(s => {
                    const x = friendly(s);
                    return need.every(v => x.includes(v)) && !exclude.some(v => x.includes(v));
                  });
                  const num = (s) => {
                    const v = Number(s?.state);
                    return Number.isFinite(v) ? v : null;
                  };
                  const isExport = (s) => s.entity_id.includes('export') || friendly(s).includes('export');

                  const forecastToday = num(states['sensor.ecco_solar_forecast_today']);
                  const remaining = num(states['sensor.ecco_solar_forecast_remaining']);
                  const forecastNow = num(states['sensor.ecco_solar_forecast_power_now']);
                  const actualToday = n('sensor.ecco_clock_dongle_ecco_day_pv_energy');

                  let liveRatio = null;
                  if (forecastNow !== null && forecastNow >= 250) {
                    liveRatio = clamp(pv / forecastNow, 0.15, 1.50);
                  }

                  let factor = liveRatio !== null
                    ? clamp(0.65 + 0.35 * liveRatio, 0.70, 1.10)
                    : 1.0;

                  let dailyRatio = null;
                  if (forecastToday !== null && remaining !== null) {
                    const expectedSoFar = Math.max(forecastToday - remaining, 0);
                    if (expectedSoFar >= 2.0 && actualToday >= 0.5) {
                      dailyRatio = clamp(actualToday / expectedSoFar, 0.35, 1.35);
                      factor = clamp(factor * 0.60 + dailyRatio * 0.40, 0.65, 1.10);
                    }
                  }

                  // Confidence now reflects both forecast signal strength and how closely
                  // real production is tracking it. 50% of forecast is deliberately LOW.
                  let accuracy = null;
                  if (liveRatio !== null) {
                    accuracy = clamp(1 - Math.abs(1 - liveRatio), 0, 1);
                  }
                  if (dailyRatio !== null) {
                    const dailyAccuracy = clamp(1 - Math.abs(1 - dailyRatio), 0, 1);
                    accuracy = accuracy === null ? dailyAccuracy : (accuracy * 0.65 + dailyAccuracy * 0.35);
                  }

                  let confidence = 'Low';
                  if (forecastNow !== null && forecastNow >= 700 && accuracy !== null && accuracy >= 0.80) {
                    confidence = 'High';
                  } else if (forecastNow !== null && forecastNow >= 250 && accuracy !== null && accuracy >= 0.62) {
                    confidence = 'Medium';
                  }

                  const correctedSolar = Number.isFinite(remaining) ? remaining * factor * 0.95 : null;
                  const conservativeSolar = Number.isFinite(remaining)
                    ? remaining * Math.max(0.60, factor - 0.15) * 0.95
                    : null;

                  const now = new Date();
                  const elapsed = Math.max(now.getHours() + now.getMinutes()/60, 1);
                  const avgSoFar = loadToday / elapsed;
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

                  const likelySoc = correctedSolar !== null
                    ? clamp(soc + ((correctedSolar-loadToCheap)/capKwh)*100, 0, 100)
                    : null;
                  const conservativeSoc = conservativeSolar !== null
                    ? clamp(soc + ((conservativeSolar-loadToCheap)/capKwh)*100, 0, 100)
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
                      detail = `Likely SOC at ${targetTime} is ${likelySoc.toFixed(0)}% and conservative SOC is ${conservativeSoc.toFixed(0)}%.`;
                      colour = '#55e58e';
                    } else if (likelySoc >= 20) {
                      headline = `Keep watch on reserve • ${confidence.toLowerCase()} confidence`;
                      detail = `Likely SOC at ${targetTime} is ${likelySoc.toFixed(0)}%, but conservative modelling falls to ${conservativeSoc.toFixed(0)}%.`;
                      colour = '#ffbd3d';
                    } else {
                      headline = `Cheap-rate support may be worthwhile • ${confidence.toLowerCase()} confidence`;
                      detail = `Likely SOC at ${targetTime} is only ${likelySoc.toFixed(0)}% with ${conservativeSoc.toFixed(0)}% on the conservative model.`;
                      colour = '#ff6376';
                    }
                  }

                  if (liveRatio !== null) {
                    detail += ` Live PV is ${Math.round(liveRatio*100)}% of Forecast.Solar right now.`;
                  }

                  if (dayCheapP !== null && dayPeakP !== null) {
                    const deliveredCheap = dayCheapP / 0.90;
                    const avoided = dayPeakP - deliveredCheap;
                    detail += ` Today's tariff spans ${dayCheapP.toFixed(1)}–${dayPeakP.toFixed(1)}p/kWh; cheap-rate energy is about ${deliveredCheap.toFixed(1)}p/kWh delivered after a 90% round-trip assumption.`;
                    if (avoided > 0) {
                      detail += ` That is worth about ${avoided.toFixed(1)}p/kWh versus buying at today's peak rate.`;
                    }
                  }
                  if (spread !== null) {
                    detail += ` Current import/export spread is ${spread.toFixed(1)}p/kWh.`;
                  }

                  return `<div style="padding-top:2px;">
                    <div style="font-size:15px;font-weight:800;color:${colour};">${headline}</div>
                    <div style="font-size:12px;line-height:1.5;color:rgba(255,255,255,0.64);margin-top:3px;">${detail}</div>
                  </div>`;
                ]]]
            styles:
              card:
                - border-radius: 16px
                - padding: 12px 14px
                - background: linear-gradient(145deg, rgba(20,28,45,0.98), rgba(10,15,27,0.98))
                - border: 1px solid rgba(255,255,255,0.08)
                - box-shadow: 0 10px 30px rgba(0,0,0,0.22)
                - overflow: hidden
              grid:
                - grid-template-areas: '"i n status" "recommendation recommendation recommendation"'
                - grid-template-columns: 30px 1fr auto
                - grid-template-rows: min-content min-content
                - row-gap: 8px
                - column-gap: 10px
              icon:
                - width: 20px
                - color: '#b8adff'
              name:
                - justify-self: start
                - align-self: center
                - font-size: 15px
                - font-weight: 700
                - color: rgba(255,255,255,0.92)
              custom_fields:
                status:
                  - justify-self: end
                  - align-self: center
                recommendation:
                  - width: 100%
                  - white-space: normal
                  - overflow: visible
                  - text-overflow: unset
                  - word-break: normal
                  - line-height: 1.45
            grid_options:
              columns: full
              rows: auto

          # ---- BATTERY ESTIMATE (existing ECCO template sensors; display only) ----
          - type: custom:button-card
            section_mode: true
            name: Battery estimate
            show_icon: false
            show_state: false
            tap_action:
              action: none
            custom_fields:
              body: >
                [[[
                  const n = id => {
                    const v = Number(states[id]?.state);
                    return Number.isFinite(v) ? v : null;
                  };
                  const f = (v, d=1) => v === null ? '--' : v.toFixed(d);
                  const kwh = n('sensor.ecco_battery_energy_estimate');
                  const soc = n('sensor.ecco_battery_soc');
                  const cap = n('sensor.ecco_config_battery_capacity');
                  const reserve = n('sensor.ecco_config_minimum_reserve_soc');
                  const predicted = n('sensor.ecco_predicted_soc_plus_1_hour_baseline');
                  return `<div>
                    <div style="display:flex;align-items:baseline;gap:10px;flex-wrap:wrap;">
                      <span style="font-size:17px;font-weight:800;color:#39d27a;white-space:nowrap;">${f(kwh)} kWh</span>
                      <span style="font-size:12px;color:rgba(255,255,255,.62);">stored · ${f(soc,0)} % of ${f(cap)} kWh</span>
                    </div>
                    <div style="font-size:12px;color:rgba(255,255,255,.62);margin-top:4px;">Reserve floor <b style="color:#fff;">${f(reserve,0)} %</b> · predicted SOC +1 h <b style="color:#fff;">${f(predicted,1)} %</b></div>
                  </div>`;
                ]]]
            styles:
              card:
                - border-radius: 16px
                - padding: 12px 14px
                - background: linear-gradient(145deg, rgba(20,28,45,0.98), rgba(10,15,27,0.98))
                - border: 1px solid rgba(255,255,255,0.08)
                - box-shadow: 0 10px 30px rgba(0,0,0,0.22)
              grid:
                - grid-template-areas: '"n" "body"'
                - grid-template-columns: 1fr
                - grid-template-rows: min-content 1fr
                - row-gap: 6px
              name:
                - justify-self: start
                - align-self: center
                - font-size: 11px
                - font-weight: 800
                - text-transform: uppercase
                - letter-spacing: 0.05em
                - color: rgba(255,255,255,0.5)
              custom_fields:
                body:
                  - justify-self: stretch
                  - width: 100%
            grid_options:
              columns: 12
              rows: auto

          # ---- SCHEDULED SESSIONS (the two schedule packages' helpers; display only, no tap action, no service) ----
          # Arming and cancelling stay in the Energy Actions card above; this row only shows both schedules at once
          # because the tabbed card shows one mode at a time.
          - type: custom:button-card
            section_mode: true
            name: Scheduled sessions
            show_icon: false
            show_state: false
            tap_action:
              action: none
            custom_fields:
              body: >
                [[[
                  const st = id => states[id]?.state;
                  const unknown = v => v === undefined || ['unknown','unavailable','none',''].includes(String(v).toLowerCase());
                  const num = id => {
                    const v = Number(st(id));
                    return Number.isFinite(v) ? v : null;
                  };
                  const when = t => {
                    const s = String(t ?? '');
                    if (s.length === 19 && s[10] === ' ') return s.slice(0, 16);
                    if (s.length === 8 && s[2] === ':') return s.slice(0, 5);
                    return s;
                  };
                  const word = v => unknown(v) ? '--' : String(v);
                  const row = (label, armedId, startId, powerId, durationId, stopSocId, statusId) => {
                    const armedRaw = st(armedId);
                    const armed = armedRaw === 'on';
                    const start = st(startId), power = num(powerId), duration = num(durationId);
                    const stopSoc = stopSocId ? num(stopSocId) : null;
                    const status = st(statusId);
                    const last = states[statusId]?.attributes?.last_result;
                    const parts = armed
                      ? ['armed', unknown(start) ? '--' : when(start), power === null ? '--' : `${power.toFixed(0)} W`, duration === null ? '--' : `${duration.toFixed(0)} min`]
                      : [unknown(armedRaw) ? 'armed state unknown' : 'not armed'];
                    if (armed && stopSocId) parts.push(stopSoc === null ? 'stop SOC --' : `stop SOC ${stopSoc.toFixed(0)} %`);
                    const tone = armed ? '#c07cff' : unknown(armedRaw) ? '#aab4c3' : 'rgba(170,180,195,.6)';
                    return `<div style="display:grid;grid-template-columns:8px 1fr;align-items:start;gap:7px;padding:3px 0;border-bottom:1px solid rgba(255,255,255,.05);">
                      <span style="width:7px;height:7px;border-radius:50%;background:${tone};margin-top:5px;"></span>
                      <div style="min-width:0;">
                        <div style="font-size:12px;color:rgba(255,255,255,.86);"><b>${label}</b> · ${parts.join(' · ')} <span style="font-size:10px;font-weight:800;letter-spacing:.45px;color:rgba(255,255,255,.46);">${word(status).toUpperCase()}</span></div>
                        <div style="font-size:11px;color:rgba(255,255,255,.52);margin-top:1px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">Last result: ${unknown(last) ? '--' : String(last)}</div>
                      </div>
                    </div>`;
                  };
                  return `<div style="display:grid;gap:4px;">
                    ${row('Free Power', 'input_boolean.ecco_free_power_schedule_armed', 'input_datetime.ecco_free_power_schedule_start', 'input_number.ecco_free_power_schedule_power', 'input_number.ecco_free_power_schedule_duration', null, 'sensor.ecco_free_power_schedule_status')}
                    ${row('Dump to Grid', 'input_boolean.ecco_dump_to_grid_schedule_armed', 'input_datetime.ecco_dump_to_grid_schedule_start', 'input_number.ecco_dump_to_grid_schedule_power', 'input_number.ecco_dump_to_grid_schedule_duration', 'input_number.ecco_dump_to_grid_schedule_stop_soc', 'sensor.ecco_dump_to_grid_schedule_status')}
                  </div>`;
                ]]]
            styles:
              card:
                - border-radius: 16px
                - padding: 12px 14px
                - background: linear-gradient(145deg, rgba(20,28,45,0.98), rgba(10,15,27,0.98))
                - border: 1px solid rgba(255,255,255,0.08)
                - box-shadow: 0 10px 30px rgba(0,0,0,0.22)
              grid:
                - grid-template-areas: '"n" "body"'
                - grid-template-columns: 1fr
                - grid-template-rows: min-content 1fr
                - row-gap: 6px
              name:
                - justify-self: start
                - align-self: center
                - font-size: 11px
                - font-weight: 800
                - text-transform: uppercase
                - letter-spacing: 0.05em
                - color: rgba(255,255,255,0.5)
              custom_fields:
                body:
                  - justify-self: stretch
                  - width: 100%
            grid_options:
              columns: 12
              rows: auto

      # ================= S7 POWER FLOW TODAY (span 3) =================
      - type: grid
        column_span: 3
        cards:
          # ---- MAIN POWER GRAPH ----
          - type: custom:apexcharts-card
            section_mode: true
            grid_options:
              columns: full
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
              - entity: sensor.ecco_clock_dongle_ecco_battery_soc
                name: SOC Model
                yaxis_id: soc
                type: line
                color: '#ffb347'
                stroke_width: 3
                opacity: 1
                extend_to: false
                show:
                  in_header: false
                data_generator: |
                  const n=(id)=>Number(hass.states[id]?.state??0);
                  const clamp=(v,a,b)=>Math.max(a,Math.min(b,v));
                  const sensors=Object.values(hass.states).filter(s=>s.entity_id.startsWith('sensor.'));
                  const friendly=(s)=>String(s?.attributes?.friendly_name??s?.entity_id??'').toLowerCase();
                  const find=(need,exclude=[])=>sensors.find(s=>{
                    const x=friendly(s);return need.every(v=>x.includes(v))&&!exclude.some(v=>x.includes(v));
                  });
                  const num=(s)=>{const v=Number(s?.state);return Number.isFinite(v)?v:null;};

                  const soc=n('sensor.ecco_clock_dongle_ecco_battery_soc');
                  const loadToday=n('sensor.ecco_clock_dongle_ecco_day_load_energy');
                  const loadW=n('sensor.ecco_clock_dongle_ecco_load_power');
                  const pvW=n('sensor.ecco_clock_dongle_ecco_pv_power');
                  const actualPV=n('sensor.ecco_clock_dongle_ecco_day_pv_energy');
                  const capAh=n('sensor.ecco_clock_dongle_ecco_battery_capacity_ah')||620;
                  const capKwh=capAh*51.2/1000;

                  const forecast=num(states['sensor.ecco_solar_forecast_today']);
                  const remaining=num(states['sensor.ecco_solar_forecast_remaining']);
                  const forecastNow=num(states['sensor.ecco_solar_forecast_power_now']);

                  let ratio=1;
                  if(forecastNow!==null&&forecastNow>=250)ratio=clamp(pvW/forecastNow,.15,1.5);
                  let factor=forecastNow!==null&&forecastNow>=250?clamp(.65+.35*ratio,.70,1.10):1;
                  const expectedSoFar=forecast!==null&&remaining!==null?Math.max(forecast-remaining,0):0;
                  if(expectedSoFar>=2&&actualPV>=.5){
                    const dailyRatio=clamp(actualPV/expectedSoFar,.35,1.35);
                    factor=clamp(factor*.60+dailyRatio*.40,.65,1.10);
                  }

                  const now=new Date();
                  const elapsed=Math.max(now.getHours()+now.getMinutes()/60,1);
                  const avgKw=loadToday/elapsed;
                  const liveKw=loadW/1000;
                  const loadKw=clamp(avgKw*.65+liveKw*.35,.15,5);

                  const sun=hass.states['sun.sun'];
                  const sunset=sun?.state==='above_horizon'?new Date(sun.attributes?.next_setting):now;
                  const hSun=Math.max((sunset-now)/3600000,0);
                  const solarKwh=remaining!==null?remaining*factor*.95:0;
                  const solarKw=hSun>0?solarKwh/hSun:0;

                  const modelEnd=new Date(now);
                  modelEnd.setHours(24,0,0,0);
                  const out=[[now.getTime(),soc]];
                  let model=soc;
                  let t=new Date(now);
                  while(t<modelEnd){
                    const next=new Date(Math.min(t.getTime()+30*60000,modelEnd.getTime()));
                    const dt=(next-t)/3600000;
                    const solar=next<=sunset?solarKw:0;
                    model=clamp(model+((solar-loadKw)*dt/capKwh)*100,0,100);
                    out.push([next.getTime(),model]);
                    t=next;
                  }
                  return out;
            now:
              show: true
              color: '#6d7b91'
              label: Now
            apex_config:
              chart:
                height: 365
                toolbar:
                  show: false
              dataLabels:
                enabled: false
              legend:
                position: top
                horizontalAlign: left
              stroke:
                curve: smooth
                dashArray: [0, 0, 0, 0, 0, 6]
              grid:
                borderColor: rgba(255,255,255,0.08)
              annotations:
                xaxis:
                  - x: "EVAL:(() => { const d = new Date(); d.setHours(0,35,0,0); return d.getTime(); })()"
                    x2: "EVAL:(() => { const d = new Date(); d.setHours(5,25,0,0); return d.getTime(); })()"
                    fillColor: '#8f7cff'
                    opacity: 0.08
                    borderColor: 'rgba(143,124,255,0.18)'
                    label:
                      text: TOU grid charge • 00:35–05:25
                      borderColor: 'rgba(143,124,255,0.18)'
                      style:
                        background: '#18213a'
                        color: '#b8adff'
                        fontSize: 10px
              tooltip:
                shared: true
                intersect: false
            card_mod:
              style: |
                :host {
                  background: transparent !important;
                  background-color: transparent !important;
                }

                ha-card {
                  font-family: "Roboto", "Segoe UI", Arial, sans-serif !important;
                  --ha-card-background: #0d1728 !important;
                  --card-background-color: #0d1728 !important;
                  border-radius: 18px;
                  border: 1px solid rgba(255,255,255,0.08);
                  background: linear-gradient(145deg, rgba(20,28,45,0.98), rgba(10,15,27,0.98));
                  box-shadow: 0 10px 30px rgba(0,0,0,0.22);
                  overflow: hidden;
                }
                .card-header {
                  color: rgba(255,255,255,0.92) !important;
                  font-family: "Roboto", "Segoe UI", Arial, sans-serif !important;
                  font-size: 20px !important;
                  font-weight: 700 !important;
                  letter-spacing: 0 !important;
                  text-transform: none !important;
                }
                #header {
                  padding: 12px 16px 0 16px !important;
                }
                #header__title {
                  color: rgba(255,255,255,0.92) !important;
                  font-family: "Roboto", "Segoe UI", Arial, sans-serif !important;
                  font-size: 20px !important;
                  font-weight: 700 !important;
                  line-height: 1.2 !important;
                  letter-spacing: 0 !important;
                  text-transform: none !important;
                  padding-bottom: 7px !important;
                }
                #state__name {
                  color: rgba(255,255,255,0.66) !important;
                  font-family: "Roboto", "Segoe UI", Arial, sans-serif !important;
                  font-weight: 500 !important;
                }
                #state__value > #state {
                  font-weight: 700 !important;
                }

      # ================= S8 ELECTRICAL DETAIL (span 1) =================
      # OVW1 (D8): the readings the four horseshoe gauges used to show, as one list; every value is a dongle sensor.
      - type: grid
        column_span: 1
        cards:
          - type: custom:button-card
            section_mode: true
            name: Electrical detail
            icon: mdi:sine-wave
            show_name: true
            show_icon: true
            show_state: false
            tap_action:
              action: none
            custom_fields:
              body: >
                [[[
                  const n = id => {
                    const v = Number(states[id]?.state);
                    return Number.isFinite(v) ? v : null;
                  };
                  const s = id => {
                    const v = states[id]?.state;
                    return v === undefined || ['unknown','unavailable','none',''].includes(String(v).toLowerCase()) ? '--' : String(v);
                  };
                  const f = (v, d=0, unit='') => v === null ? '--' : `${v.toFixed(d)}${unit}`;
                  const battW = n('sensor.ecco_clock_dongle_ecco_battery_output_power');
                  const battWord = battW === null ? '--' : `${Math.abs(battW).toFixed(0)} W ${battW > 0 ? 'discharging' : battW < 0 ? 'charging' : 'idle'}`;
                  const rows = [
                    ['Battery voltage', f(n('sensor.ecco_clock_dongle_ecco_battery_voltage'), 1, ' V'), '#39d27a'],
                    ['Battery current', f(n('sensor.ecco_clock_dongle_ecco_battery_output_current'), 1, ' A'), '#39d27a'],
                    ['Battery power', battWord, '#39d27a'],
                    ['Load voltage L1 / frequency', `${f(n('sensor.ecco_clock_dongle_ecco_load_voltage_l1'), 1, ' V')} · ${f(n('sensor.ecco_clock_dongle_ecco_load_frequency'), 2, ' Hz')}`, '#42aaff'],
                    ['Inverter output current L1', f(n('sensor.ecco_clock_dongle_ecco_inverter_output_current_l1'), 1, ' A'), '#42aaff'],
                    ['PV1 / PV2', `${f(n('sensor.ecco_clock_dongle_ecco_pv1_power'), 0, ' W')} · ${f(n('sensor.ecco_clock_dongle_ecco_pv2_power'), 0, ' W')}`, '#ffbd3d'],
                    ['Inverter output / state', `${f(n('sensor.ecco_clock_dongle_ecco_inverter_output_power'), 0, ' W')} · ${s('sensor.ecco_clock_dongle_ecco_inverter_system_state')}`, '#66b3ff'],
                    ['Inverter output frequency', f(n('sensor.ecco_clock_dongle_ecco_inverter_output_frequency'), 2, ' Hz'), '#66b3ff'],
                    ['AC / DC transformer', `${f(n('sensor.ecco_clock_dongle_ecco_temperature_ac_transformer'), 1, ' °C')} · ${f(n('sensor.ecco_clock_dongle_ecco_temperature_dc_transformer'), 1, ' °C')}`, '#ffbd3d'],
                    ['Generator port', f(n('sensor.ecco_clock_dongle_ecco_generator_port_power'), 0, ' W'), '#aab4c3'],
                    ['Dongle Wi-Fi', f(n('sensor.ecco_clock_dongle_wifi_signal'), 0, ' dBm'), '#55e58e'],
                    ['Battery capacity', f(n('sensor.ecco_clock_dongle_ecco_battery_capacity_ah'), 0, ' Ah'), '#55e58e']
                  ];
                  return `<div style="display:grid;gap:3px;">
                    ${rows.map(r => `<div style="display:grid;grid-template-columns:8px 1fr auto;align-items:center;gap:7px;padding:4px 0;border-bottom:1px solid rgba(255,255,255,.05);">
                      <span style="width:7px;height:7px;border-radius:50%;background:${r[2]};"></span>
                      <span style="font-size:12px;color:rgba(255,255,255,.62);">${r[0]}</span>
                      <span style="font-size:12px;font-weight:700;color:rgba(255,255,255,.92);text-align:right;">${r[1]}</span>
                    </div>`).join('')}
                  </div>`;
                ]]]
            styles:
              card:
                - border-radius: 16px
                - padding: 12px 14px
                - background: linear-gradient(145deg, rgba(20,28,45,0.98), rgba(10,15,27,0.98))
                - border: 1px solid rgba(255,255,255,0.08)
                - box-shadow: 0 10px 30px rgba(0,0,0,0.22)
              grid:
                - grid-template-areas: '"i n" "body body"'
                - grid-template-columns: 30px 1fr
                - grid-template-rows: min-content 1fr
                - row-gap: 8px
              icon:
                - width: 20px
                - color: '#8f7cff'
              name:
                - justify-self: start
                - align-self: center
                - font-size: 15px
                - font-weight: 700
                - color: rgba(255,255,255,0.92)
              custom_fields:
                body:
                  - justify-self: stretch
                  - width: 100%
            grid_options:
              columns: full
              rows: auto

      # ================= S9 SYSTEM HEALTH (span 4) =================
      # OVW1: ONE System Health card. Column (a) is the former compact summary (the seven subsystem sensors, with the
      # reason codes of any row that is not HEALTHY); column (b) is the former raw diagnostics card (the dongle
      # entities) plus the correction-failures counter; column (c) holds the notes and the last update times.
      # Monitoring only: nothing here gates a control.
      - type: grid
        column_span: 4
        cards:
          - type: custom:button-card
            section_mode: true
            name: System Health
            show_icon: false
            show_state: false
            tap_action:
              action: none
            custom_fields:
              health: >
                [[[
                  const tone = s => s === 'HEALTHY' ? '#39d27a' : s === 'DEGRADED' ? '#66b3ff' : s === 'WARNING' ? '#ffbd3d' : s === 'FAILED' ? '#ff5f6d' : '#aab4c3';
                  const read = id => {
                    const s = states[id]?.state;
                    return ['HEALTHY', 'DEGRADED', 'WARNING', 'FAILED'].includes(s) ? s : 'UNKNOWN';
                  };
                  const rows = [
                    ['Manual Write', read('sensor.ecco_health_manual_write_system')],
                    ['RTC', read('sensor.ecco_health_rtc')],
                    ['Free Power', read('sensor.ecco_health_free_power')],
                    ['Configuration', read('sensor.ecco_health_configuration')],
                    ['Inverter Telemetry', read('sensor.ecco_health_inverter_telemetry')],
                    ['Supervision', read('sensor.ecco_health_supervision')],
                    ['Fallback', read('sensor.ecco_health_fallback')]
                  ];
                  const ids = ['sensor.ecco_health_manual_write_system', 'sensor.ecco_health_rtc', 'sensor.ecco_health_free_power', 'sensor.ecco_health_configuration', 'sensor.ecco_health_inverter_telemetry', 'sensor.ecco_health_supervision', 'sensor.ecco_health_fallback'];
                  const codes = id => {
                    const c = states[id]?.attributes?.reason_codes;
                    return Array.isArray(c) && c.length ? c.join(', ') : '';
                  };
                  const telemetry = states['binary_sensor.ecco_clock_dongle_telemetry_online']?.state === 'on';
                  const config = states['binary_sensor.ecco_clock_dongle_configuration_online']?.state === 'on';
                  const ntp = states['binary_sensor.ecco_clock_dongle_ntp_synced']?.state === 'on';
                  const stall = states['binary_sensor.ecco_clock_dongle_rtc_stall_detected']?.state === 'on';
                  const clock = Number(states['sensor.ecco_clock_dongle_clock_difference']?.state);
                  const wifi = Number(states['sensor.ecco_clock_dongle_wifi_signal']?.state);
                  const tf = Number(states['sensor.ecco_clock_dongle_telemetry_read_failures_since_boot']?.state);
                  const cf = Number(states['sensor.ecco_clock_dongle_configuration_read_failures_since_boot']?.state);
                  const fixes = Number(states['sensor.ecco_clock_dongle_failed_corrections_since_boot']?.state);
                  const diag = [
                    ['Telemetry', telemetry ? 'Connected' : 'Offline', telemetry],
                    ['Configuration', config ? 'Connected' : 'Offline', config],
                    ['NTP Sync', ntp ? 'Synced' : 'Not synced', ntp],
                    ['RTC Stall', stall ? 'Detected' : 'Clear', !stall],
                    ['Clock Error', Number.isFinite(clock) ? `${clock.toFixed(0)} s` : '--', Number.isFinite(clock) && Math.abs(clock) < 20],
                    ['Wi‑Fi', Number.isFinite(wifi) ? `${wifi.toFixed(0)} dBm` : '--', Number.isFinite(wifi) && wifi > -80],
                    ['Read Failures', `${Number.isFinite(tf) ? tf.toFixed(0) : '--'} / ${Number.isFinite(cf) ? cf.toFixed(0) : '--'}`, Number.isFinite(tf) && Number.isFinite(cf) && tf === 0 && cf === 0],
                    ['Correction Failures', Number.isFinite(fixes) ? fixes.toFixed(0) : '--', Number.isFinite(fixes) && fixes === 0]
                  ];
                  const text = id => {
                    const v = states[id]?.state;
                    return v === undefined || ['unknown','unavailable','none',''].includes(String(v).toLowerCase()) ? '--' : String(v);
                  };
                  const label = t => `<div style="font-size:11px;font-weight:800;letter-spacing:.05em;text-transform:uppercase;color:rgba(255,255,255,.5);margin-bottom:4px;">${t}</div>`;
                  const line = (dot, name, value, colour, why) => `<div style="display:grid;grid-template-columns:8px 1fr auto;align-items:center;gap:7px;padding:3px 0;border-bottom:1px solid rgba(255,255,255,.05);">
                    <span style="width:7px;height:7px;border-radius:50%;background:${dot};"></span>
                    <span style="font-size:12px;color:rgba(255,255,255,.62);min-width:0;">${name}${why ? ` <span style="font-size:10px;color:rgba(255,255,255,.46);">· ${why}</span>` : ''}</span>
                    <span style="font-size:12px;font-weight:700;color:${colour};text-align:right;">${value}</span>
                  </div>`;
                  return `<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:14px;">
                    <div>
                      ${label('Subsystems')}
                      ${rows.map((r, i) => line(tone(r[1]), r[0], r[1], tone(r[1]), r[1] === 'HEALTHY' ? '' : codes(ids[i]))).join('')}
                    </div>
                    <div>
                      ${label('Dongle diagnostics')}
                      ${diag.map(r => line(r[2] ? '#39d27a' : '#ff6376', r[0], r[1], r[2] ? '#7ceaa6' : '#ff8b98', '')).join('')}
                    </div>
                    <div>
                      ${label('Notes')}
                      <div style="font-size:10px;font-weight:800;letter-spacing:.45px;color:rgba(255,255,255,.42);">MONITORING ONLY · NOT A CONTROL GATE</div>
                      <div style="font-size:12px;color:rgba(255,255,255,.62);margin-top:6px;line-height:1.55;">Reason codes appear beside any subsystem row that is not HEALTHY. The subsystem rows are the ECCO health sensors; the diagnostics are the raw dongle entities.</div>
                      <div style="font-size:12px;color:rgba(255,255,255,.62);margin-top:6px;line-height:1.55;">Last telemetry update <b style="color:#fff;">${text('sensor.ecco_clock_dongle_last_telemetry_update')}</b><br>Last configuration update <b style="color:#fff;">${text('sensor.ecco_clock_dongle_last_configuration_update')}</b></div>
                    </div>
                  </div>`;
                ]]]
            styles:
              card:
                - border-radius: 16px
                - padding: 12px 14px
                - background: linear-gradient(145deg, rgba(20,28,45,0.98), rgba(10,15,27,0.98))
                - border: 1px solid rgba(255,255,255,0.08)
                - box-shadow: 0 10px 30px rgba(0,0,0,0.22)
              grid:
                - grid-template-areas: '"n" "health"'
                - grid-template-columns: 1fr
                - grid-template-rows: min-content 1fr
                - row-gap: 8px
              name:
                - justify-self: start
                - font-size: 15px
                - font-weight: 700
                - color: rgba(255,255,255,0.92)
              custom_fields:
                health:
                  - width: 100%
            grid_options:
              columns: full
              rows: auto


""")
DASHBOARD_EDITS = (
    (DASHBOARD_0_OLD, DASHBOARD_0_NEW),
    (DASHBOARD_1_OLD, DASHBOARD_1_NEW),
)


def pre_ovw1_dashboard(text: str) -> str:
    """home-assistant/dashboards/ecco_pro.yaml with exactly ovw1's edits undone (a frozen reverter of chain entry ovw1, PEX): its state as of acfg1."""
    return _revert(text, DASHBOARD_EDITS, "home-assistant/dashboards/ecco_pro.yaml")


pre_ovw1_dashboard.edits = DASHBOARD_EDITS   # the PEX contract: a frozen reverter exposes its exact (before, after) pairs


def add_ovw1_dashboard(text: str) -> str:
    """Applies ovw1's home-assistant/dashboards/ecco_pro.yaml edits to the earlier text (the round trip)."""
    return _apply(text, DASHBOARD_EDITS, "home-assistant/dashboards/ecco_pro.yaml")


# ---- (PEX frozen edit) VERSION.yaml ------------------------------------------------------------------------------------------
VERSION_REL = "VERSION.yaml"
# Dashboard 7.19.0 -> 7.20.0 (staged); the 7.19.0 record is kept below the new note.
VERSION_0_OLD = _blk(r"""
  dashboard:
    version: "7.19.0"
    path: home-assistant/dashboards/ecco_pro.yaml
    # v7.19.0 (ACFG1) adds the read-only Advanced / Experimental Configuration card as section 13 of the
""")
VERSION_0_NEW = _blk(r"""
  dashboard:
    version: "7.20.0"
    path: home-assistant/dashboards/ecco_pro.yaml
    # v7.20.0 (OVW1) rebuilds the Overview view as nine sections: a compact status banner that also reads the Dump to
    # Grid lease states, the Weather & Solar card's two compact layouts, the Energy Actions card in its tabbed layout
    # with the Known-Good Profile bar, decision-support cards from existing entities, an electrical detail list in
    # place of the four gauges and one merged System Health card. Display only: no control path, firmware, package or
    # automation changed. It is STAGED: tested_in_home_assistant stays false until the new Overview is exercised on
    # the reference installation. The 7.19.0 record follows.
    # v7.19.0 (ACFG1) adds the read-only Advanced / Experimental Configuration card as section 13 of the
""")
VERSION_EDITS = (
    (VERSION_0_OLD, VERSION_0_NEW),
)


def pre_ovw1_version(text: str) -> str:
    """VERSION.yaml with exactly ovw1's edits undone (a frozen reverter of chain entry ovw1, PEX): its state as of acfg1."""
    return _revert(text, VERSION_EDITS, "VERSION.yaml")


pre_ovw1_version.edits = VERSION_EDITS   # the PEX contract: a frozen reverter exposes its exact (before, after) pairs


def add_ovw1_version(text: str) -> str:
    """Applies ovw1's VERSION.yaml edits to the earlier text (the round trip)."""
    return _apply(text, VERSION_EDITS, "VERSION.yaml")


# ---- (PEX frozen edit) frontend/ecco-energy-actions-card/src/ecco-energy-actions-card.ts -------------------------------------
CARD_SRC_REL = "frontend/ecco-energy-actions-card/src/ecco-energy-actions-card.ts"
# The `layout: tabbed` presentation: the trackSelection import, the _track state, the one-time initial-track choice in willUpdate(), the
# render() branch, _trackSummary() / _selectTrack() / _renderTabbed(), and the tabbed CSS. No callService site is added.
CARD_SRC_0_OLD = _blk(r"""
import { isInterlocked, canActWhileInterlocked, interlockMessage } from "./interlock";
import {
""")
CARD_SRC_0_NEW = _blk(r"""
import { isInterlocked, canActWhileInterlocked, interlockMessage } from "./interlock";
import {
  canChooseTrack,
  initialTrack,
  hiddenTrackAlert,
  alertTone,
  trackName,
  hiddenTrackAlertText,
  type Track,
  type TrackSummary,
} from "./trackSelection";
import {
""")
CARD_SRC_1_OLD = _blk(r"""
  @state() private _mode: "now" | "later" = "now";

""")
CARD_SRC_1_NEW = _blk(r"""
  @state() private _mode: "now" | "later" = "now";
  /** `layout: tabbed` only - the visible track. null until willUpdate() picks it once from both tracks' states (see trackSelection.ts); after that only a tab click changes it. */
  @state() private _track: Track | null = null;

""")
CARD_SRC_2_OLD = _blk(r"""
      this._lastDumpVisualState = visualState;
    }
  }

""")
CARD_SRC_2_NEW = _blk(r"""
      this._lastDumpVisualState = visualState;
    }

    // `layout: tabbed` only: the visible track is chosen ONCE, on the first
    // update in which a track has a real state, by state priority
    // (trackSelection.ts) - after that only a tab click changes it, never a
    // state change. An all-"unavailable" snapshot (device offline, entities
    // not registered yet) is not a choice: _renderTabbed() shows Free Power
    // provisionally until a state arrives, so a Dump to Grid recovery that
    // surfaces when the device reconnects still wins the initial tab.
    if (this._config?.layout === "tabbed" && this._track === null && this.hass) {
      const tracks = this._trackSummary();
      if (canChooseTrack(tracks.fp.state, tracks.dump.state)) {
        this._track = initialTrack(tracks.fp.state, tracks.dump.state);
      }
    }
  }

""")
CARD_SRC_3_OLD = _blk(r"""
    const title = this._config.title ?? DEFAULT_TITLE;

""")
CARD_SRC_3_NEW = _blk(r"""
    const title = this._config.title ?? DEFAULT_TITLE;
    if (this._config.layout === "tabbed") return this._renderTabbed(title);

""")
CARD_SRC_4_OLD = _blk(r"""
          ${this._renderDumpToGridTile()}
        </div>
""")
CARD_SRC_4_NEW = _blk(r"""
          ${this._renderDumpToGridTile()}
        </div>
      </ha-card>
    `;
  }

  // ---------------------------------------------------------------------
  // `layout: tabbed` (OVW1) - presentation only. One track (Free Power or
  // Dump to Grid) is visible at a time, but BOTH tracks' display states are
  // still computed on every render with the tiles' own classifiers and
  // overlays, so the header chips, the initial tab and the cross-track alert
  // can never hide the other track's live state. The two tiles render
  // exactly as in the side-by-side layout; no service call, entity read or
  // handler is added or shared between them. See src/trackSelection.ts.
  // ---------------------------------------------------------------------

  /** Both tracks' display states, labels and firmware status text - the same resolveDisplayState / resolveDumpDisplayState + interlock chain the two tiles run, never short-circuited for the hidden track. */
  private _trackSummary(): { fp: TrackSummary; dump: TrackSummary } {
    const fpVisual = this._freePowerVisualStateForInterlock();
    const dumpVisual = this._dumpVisualStateForInterlock();

    let fp: TrackSummary = { state: "unavailable", pill: "unavailable", label: "Unavailable", statusText: undefined };
    const fpEntities = this._config?.free_power;
    if (fpVisual !== null && fpEntities) {
      const schedule = this._config?.schedule;
      const scheduled: FreePowerDisplayState = schedule
        ? resolveDisplayState(fpVisual, classifySchedule({ armed: toBoolean(this._entityState(schedule.armed)) }))
        : fpVisual;
      const state: FreePowerDisplayState = isInterlocked(fpVisual, dumpVisual) ? "interlocked" : scheduled;
      fp = { state, pill: state, label: this._labelFor(state), statusText: this._entityState(fpEntities.status) };
    }

    // the locked preview shell exactly when _renderDumpToGridTile() renders it: Dump not configured, or hass not arrived yet
    const dumpEntities = this._config?.dump_to_grid;
    let dump: TrackSummary = dumpEntities && this.hass
      ? { state: "unavailable", pill: "unavailable", label: "Unavailable", statusText: undefined }
      : { state: "unavailable", pill: "locked", label: "Coming Soon", statusText: undefined };
    if (dumpVisual !== null && dumpEntities) {
      const dumpSchedule = dumpEntities.schedule;
      const scheduled = resolveDumpDisplayState(dumpVisual, dumpSchedule ? toBoolean(this._entityState(dumpSchedule.armed)) : null);
      const state: DumpDisplayState = isInterlocked(dumpVisual, fpVisual) ? "interlocked" : scheduled;
      dump = { state, pill: state, label: dumpDisplayStateLabel(state), statusText: this._entityState(dumpEntities.status) };
    }
    return { fp, dump };
  }

  /** The tab click handler. Switching tracks cancels any pending two-tap End & Restore confirmation of BOTH modes, so a stale "tap again" can never apply to the other mode; NOW/LATER, staged values and every entity stay per-mode and untouched. */
  private _selectTrack(track: Track): void {
    if (this._confirmTimer) clearTimeout(this._confirmTimer);
    if (this._confirmDumpTimer) clearTimeout(this._confirmDumpTimer);
    this._confirmEndRestore = false;
    this._confirmEndDump = false;
    this._track = track;
  }

  private _renderTabbed(title: string): TemplateResult {
    const tracks = this._trackSummary();
    // _track is null until willUpdate() pins it on the first update with a real state - render the same choice provisionally meanwhile.
    const track: Track = this._track ?? initialTrack(tracks.fp.state, tracks.dump.state);
    const hiddenTrack: Track = track === "free_power" ? "dump_to_grid" : "free_power";
    const hidden = track === "free_power" ? tracks.dump : tracks.fp;
    const tone = alertTone(hiddenTrackAlert(hidden.state));
    const alertIcon = tone === "fault" ? "mdi:alert-circle-outline" : tone === "warning" ? "mdi:alert-outline" : "mdi:information-outline";

    return html`
      <ha-card>
        <div class="tabbed-header">
          <h1 class="card-title">${title}</h1>
          <div class="track-strip">
            <span class="state-pill state-${tracks.fp.pill}">Free Power · ${tracks.fp.label}</span>
            <span class="state-pill state-${tracks.dump.pill}">Dump to Grid · ${tracks.dump.label}</span>
          </div>
        </div>
        <div class="mode-selector track-selector" role="tablist">
          <button
            type="button"
            role="tab"
            class="mode-tab track-tab ${track === "free_power" ? "is-active" : ""}"
            aria-selected=${track === "free_power"}
            @click=${() => this._selectTrack("free_power")}
          >
            <ha-icon icon="mdi:flash"></ha-icon> Free Power
          </button>
          <button
            type="button"
            role="tab"
            class="mode-tab track-tab ${track === "dump_to_grid" ? "is-active" : ""}"
            aria-selected=${track === "dump_to_grid"}
            @click=${() => this._selectTrack("dump_to_grid")}
          >
            <ha-icon icon="mdi:transmission-tower-export"></ha-icon> Dump to Grid
          </button>
        </div>
        ${tone
          ? html`
              <div class="track-alert track-alert-${tone}" role="status">
                <ha-icon icon=${alertIcon}></ha-icon>
                <div class="track-alert-text">${hiddenTrackAlertText(trackName(hiddenTrack), hidden.label, hidden.statusText)}</div>
                <button type="button" class="track-alert-show" @click=${() => this._selectTrack(hiddenTrack)}>Show</button>
              </div>
            `
          : nothing}
        <div class="actions-grid is-tabbed">
          ${track === "free_power" ? this._renderFreePowerTile() : this._renderDumpToGridTile()}
        </div>
""")
CARD_SRC_5_OLD = _blk(r"""
    }
  `;
""")
CARD_SRC_5_NEW = _blk(r"""
    }

    /* ---- layout: tabbed (OVW1) - one track visible at a time. The track
       tabs reuse the NOW/LATER selector's look, the header chips reuse the
       state-pill tones, and the cross-track alert banner mirrors the
       schedule banner's shape in the hidden track's own tone. ---- */
    .tabbed-header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      flex-wrap: wrap;
      gap: 8px 12px;
      margin-bottom: 12px;
    }
    .tabbed-header .card-title {
      margin: 0;
    }
    .track-strip {
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
    }
    .track-selector {
      border-radius: 12px;
      margin-bottom: 10px;
    }
    .track-tab {
      min-height: 44px;
      border-radius: 9px;
      font-size: 13px;
      font-weight: 800;
    }
    .track-tab ha-icon {
      --mdc-icon-size: 17px;
    }
    .track-alert {
      --eaa-alert: var(--eaa-accent);
      display: flex;
      align-items: center;
      gap: 10px;
      padding: 9px 12px;
      border-radius: 12px;
      background: color-mix(in srgb, var(--eaa-alert) 14%, var(--eaa-surface));
      border: 1px solid color-mix(in srgb, var(--eaa-alert) 45%, var(--eaa-border));
      margin-bottom: 12px;
      font-size: 12px;
      font-weight: 700;
      line-height: 1.4;
    }
    .track-alert-warning {
      --eaa-alert: var(--eaa-warning);
    }
    .track-alert-fault {
      --eaa-alert: var(--eaa-fault);
    }
    .track-alert ha-icon {
      --mdc-icon-size: 19px;
      color: var(--eaa-alert);
      flex-shrink: 0;
    }
    .track-alert-text {
      min-width: 0;
      flex: 1 1 auto;
      word-break: break-word;
    }
    .track-alert-show {
      flex: 0 0 auto;
      min-height: 36px;
      padding: 7px 12px;
      font-size: 11px;
      background: transparent;
      color: var(--eaa-alert);
      border-color: color-mix(in srgb, var(--eaa-alert) 45%, var(--eaa-border));
    }
    .actions-grid.is-tabbed {
      /* minmax(0, 1fr), not 1fr: a bare 1fr track is min-content-sized and lets a long nowrap line (the armed
         schedule banner) push the single tile wider than the card on a phone. Scoped to the tabbed layout. */
      grid-template-columns: minmax(0, 1fr);
    }
    @container (max-width: 620px) {
      .tabbed-header {
        flex-direction: column;
        align-items: flex-start;
      }
      .track-tab {
        padding: 7px 8px;
        font-size: 12px;
      }
    }
  `;
""")
CARD_SRC_EDITS = (
    (CARD_SRC_0_OLD, CARD_SRC_0_NEW),
    (CARD_SRC_1_OLD, CARD_SRC_1_NEW),
    (CARD_SRC_2_OLD, CARD_SRC_2_NEW),
    (CARD_SRC_3_OLD, CARD_SRC_3_NEW),
    (CARD_SRC_4_OLD, CARD_SRC_4_NEW),
    (CARD_SRC_5_OLD, CARD_SRC_5_NEW),
)


def pre_ovw1_card_source(text: str) -> str:
    """frontend/ecco-energy-actions-card/src/ecco-energy-actions-card.ts with exactly ovw1's edits undone (a frozen reverter of chain entry ovw1, PEX): its state as of acfg1."""
    return _revert(text, CARD_SRC_EDITS, "frontend/ecco-energy-actions-card/src/ecco-energy-actions-card.ts")


pre_ovw1_card_source.edits = CARD_SRC_EDITS   # the PEX contract: a frozen reverter exposes its exact (before, after) pairs


def add_ovw1_card_source(text: str) -> str:
    """Applies ovw1's frontend/ecco-energy-actions-card/src/ecco-energy-actions-card.ts edits to the earlier text (the round trip)."""
    return _apply(text, CARD_SRC_EDITS, "frontend/ecco-energy-actions-card/src/ecco-energy-actions-card.ts")


# ---- (PEX frozen edit) frontend/ecco-energy-actions-card/src/config.ts -------------------------------------------------------
CARD_CONFIG_REL = "frontend/ecco-energy-actions-card/src/config.ts"
# The optional `layout` key of the card config.
CARD_CONFIG_0_OLD = _blk(r"""
  dump_to_grid?: DumpToGridEntities;
}
""")
CARD_CONFIG_0_NEW = _blk(r"""
  dump_to_grid?: DumpToGridEntities;
  /**
   * Presentation only. "side-by-side" (the default, and what any other value
   * falls back to) renders both tiles in one grid exactly as before;
   * "tabbed" shows one track at a time behind a Free Power / Dump to Grid
   * selector with a per-track state chip strip and a cross-track alert
   * banner (see README "Layouts"). No entity mapping or service call differs
   * between the two.
   */
  layout?: "side-by-side" | "tabbed";
}
""")
CARD_CONFIG_EDITS = (
    (CARD_CONFIG_0_OLD, CARD_CONFIG_0_NEW),
)


def pre_ovw1_card_config(text: str) -> str:
    """frontend/ecco-energy-actions-card/src/config.ts with exactly ovw1's edits undone (a frozen reverter of chain entry ovw1, PEX): its state as of acfg1."""
    return _revert(text, CARD_CONFIG_EDITS, "frontend/ecco-energy-actions-card/src/config.ts")


pre_ovw1_card_config.edits = CARD_CONFIG_EDITS   # the PEX contract: a frozen reverter exposes its exact (before, after) pairs


def add_ovw1_card_config(text: str) -> str:
    """Applies ovw1's frontend/ecco-energy-actions-card/src/config.ts edits to the earlier text (the round trip)."""
    return _apply(text, CARD_CONFIG_EDITS, "frontend/ecco-energy-actions-card/src/config.ts")


# ---- (PEX frozen edit) frontend/ecco-energy-actions-card/README.md -----------------------------------------------------------
CARD_README_REL = "frontend/ecco-energy-actions-card/README.md"
# The Layouts section of the card README.
CARD_README_0_OLD = _blk(r"""
installation's entity ids. No entity id is ever hard-coded in `src/`.

""")
CARD_README_0_NEW = _blk(r"""
installation's entity ids. No entity id is ever hard-coded in `src/`.

### Layouts

`layout:` is optional and presentation-only: it changes no entity mapping
and no service call.

```yaml
type: custom:ecco-energy-actions-card
layout: tabbed        # optional - side-by-side (default) | tabbed
```

- **`side-by-side`** (the default, and what any other value falls back to -
  the card does not reject unknown values) renders both tiles in one grid,
  exactly as before this option existed.
- **`tabbed`** (used by the ECCO Pro Overview) shows one mode at a time:
  - The title row carries a **track strip**: one chip per mode (`Free Power
    · Ready`, `Dump to Grid · Scheduled`, ...) in the same state tones as the
    tiles' own pills. Both chips are always visible, and both modes' display
    states are classified on every render exactly as the tiles do (hardware
    state, then the schedule overlay, then the sibling interlock) - the
    hidden mode is never short-circuited.
  - A **Free Power / Dump to Grid** selector (`role="tablist"`, 44 px
    targets, the NOW/LATER selector's look) picks which mode's full tile
    renders beneath it. The tile itself is unchanged: the same NOW/LATER
    panels, staged sliders, ARM / START / END & RESTORE, banners, recovery
    panel and firmware status line as in the side-by-side layout.
  - **Initial tab:** chosen once, on the first render in which at least
    one mode has a real state, by state priority `recovery_attention >
    deferred > busy > active > armed > scheduled > interlocked > ready >
    unavailable`; a tie goes to Free Power. While both modes are
    unavailable (device offline, entities not registered yet) Free Power
    shows provisionally and the choice waits, so a recovery that surfaces
    on reconnect still wins the first tab. After that only a tap on a tab
    changes it - the card never switches tabs by itself, even when the
    hidden mode's state changes (you may be mid-edit).
  - **Cross-mode alert banner** (not dismissible) directly under the
    selector whenever the hidden mode is **active** (accent), **busy** or
    **deferred** (amber) or in **recovery attention** (red): it names the
    mode, its state label and the firmware's literal status text, with a
    **Show** button that switches to that tab. A hidden mode that is armed,
    scheduled, interlocked, ready or unavailable is announced by its chip
    only. The rules live in `src/trackSelection.ts` (pure, no regex
    literal) and are pinned by `test/trackSelection.test.ts`.
  - **Nothing transfers between modes.** ARM toggles only the visible
    mode's own write-enable switch, START / END & RESTORE press only its
    own buttons, NOW/LATER and staged values stay per mode, and switching
    tabs cancels any pending two-tap End & Restore confirmation of *both*
    modes so a stale "tap again" can never apply to the other one. The
    firmware's own mutual-exclusion preconditions apply unchanged.

""")
CARD_README_EDITS = (
    (CARD_README_0_OLD, CARD_README_0_NEW),
)


def pre_ovw1_card_readme(text: str) -> str:
    """frontend/ecco-energy-actions-card/README.md with exactly ovw1's edits undone (a frozen reverter of chain entry ovw1, PEX): its state as of acfg1."""
    return _revert(text, CARD_README_EDITS, "frontend/ecco-energy-actions-card/README.md")


pre_ovw1_card_readme.edits = CARD_README_EDITS   # the PEX contract: a frozen reverter exposes its exact (before, after) pairs


def add_ovw1_card_readme(text: str) -> str:
    """Applies ovw1's frontend/ecco-energy-actions-card/README.md edits to the earlier text (the round trip)."""
    return _apply(text, CARD_README_EDITS, "frontend/ecco-energy-actions-card/README.md")


# ---- (PEX frozen edit) frontend/ecco-energy-actions-card/dist/ecco-energy-actions-card.js ------------------------------------
BUNDLE_REL = "frontend/ecco-energy-actions-card/dist/ecco-energy-actions-card.js"
# The rebuilt bundle (esbuild 0.28.1, deterministic): one pair, the whole file. Its pre-ovw1 state is the esb1 bundle.
BUNDLE_0_OLD = _blk(r"""
var _t=Object.defineProperty;var gt=Object.getOwnPropertyDescriptor;var v=(n,t,e,r)=>{for(var i=r>1?void 0:r?gt(t,e):t,a=n.length-1,s;a>=0;a--)(s=n[a])&&(i=(r?s(t,e,i):s(i))||i);return r&&i&&_t(t,e,i),i};var J=globalThis,Z=J.ShadowRoot&&(J.ShadyCSS===void 0||J.ShadyCSS.nativeShadow)&&"adoptedStyleSheets"in Document.prototype&&"replace"in CSSStyleSheet.prototype,ce=Symbol(),Oe=new WeakMap,B=class{constructor(t,e,r){if(this._$cssResult$=!0,r!==ce)throw Error("CSSResult is not constructable. Use `unsafeCSS` or `css` instead.");this.cssText=t,this.t=e}get styleSheet(){let t=this.o,e=this.t;if(Z&&t===void 0){let r=e!==void 0&&e.length===1;r&&(t=Oe.get(e)),t===void 0&&((this.o=t=new CSSStyleSheet).replaceSync(this.cssText),r&&Oe.set(e,t))}return t}toString(){return this.cssText}},Me=n=>new B(typeof n=="string"?n:n+"",void 0,ce),ue=(n,...t)=>{let e=n.length===1?n[0]:t.reduce((r,i,a)=>r+(s=>{if(s._$cssResult$===!0)return s.cssText;if(typeof s=="number")return s;throw Error("Value passed to 'css' function must be a 'css' function result: "+s+". Use 'unsafeCSS' to pass non-literal values, but take care to ensure page security.")})(i)+n[a+1],n[0]);return new B(e,n,ce)},Ie=(n,t)=>{if(Z)n.adoptedStyleSheets=t.map(e=>e instanceof CSSStyleSheet?e:e.styleSheet);else for(let e of t){let r=document.createElement("style"),i=J.litNonce;i!==void 0&&r.setAttribute("nonce",i),r.textContent=e.cssText,n.appendChild(r)}},pe=Z?n=>n:n=>n instanceof CSSStyleSheet?(t=>{let e="";for(let r of t.cssRules)e+=r.cssText;return Me(e)})(n):n;var{is:ft,defineProperty:bt,getOwnPropertyDescriptor:vt,getOwnPropertyNames:yt,getOwnPropertySymbols:wt,getPrototypeOf:St}=Object,X=globalThis,Fe=X.trustedTypes,xt=Fe?Fe.emptyScript:"",$t=X.reactiveElementPolyfillSupport,H=(n,t)=>n,z={toAttribute(n,t){switch(t){case Boolean:n=n?xt:null;break;case Object:case Array:n=n==null?n:JSON.stringify(n)}return n},fromAttribute(n,t){let e=n;switch(t){case Boolean:e=n!==null;break;case Number:e=n===null?null:Number(n);break;case Object:case Array:try{e=JSON.parse(n)}catch{e=null}}return e}},ee=(n,t)=>!ft(n,t),Ve={attribute:!0,type:String,converter:z,reflect:!1,useDefault:!1,hasChanged:ee};Symbol.metadata??=Symbol("metadata"),X.litPropertyMetadata??=new WeakMap;var k=class extends HTMLElement{static addInitializer(t){this._$Ei(),(this.l??=[]).push(t)}static get observedAttributes(){return this.finalize(),this._$Eh&&[...this._$Eh.keys()]}static createProperty(t,e=Ve){if(e.state&&(e.attribute=!1),this._$Ei(),this.prototype.hasOwnProperty(t)&&((e=Object.create(e)).wrapped=!0),this.elementProperties.set(t,e),!e.noAccessor){let r=Symbol(),i=this.getPropertyDescriptor(t,r,e);i!==void 0&&bt(this.prototype,t,i)}}static getPropertyDescriptor(t,e,r){let{get:i,set:a}=vt(this.prototype,t)??{get(){return this[e]},set(s){this[e]=s}};return{get:i,set(s){let o=i?.call(this);a?.call(this,s),this.requestUpdate(t,o,r)},configurable:!0,enumerable:!0}}static getPropertyOptions(t){return this.elementProperties.get(t)??Ve}static _$Ei(){if(this.hasOwnProperty(H("elementProperties")))return;let t=St(this);t.finalize(),t.l!==void 0&&(this.l=[...t.l]),this.elementProperties=new Map(t.elementProperties)}static finalize(){if(this.hasOwnProperty(H("finalized")))return;if(this.finalized=!0,this._$Ei(),this.hasOwnProperty(H("properties"))){let e=this.properties,r=[...yt(e),...wt(e)];for(let i of r)this.createProperty(i,e[i])}let t=this[Symbol.metadata];if(t!==null){let e=litPropertyMetadata.get(t);if(e!==void 0)for(let[r,i]of e)this.elementProperties.set(r,i)}this._$Eh=new Map;for(let[e,r]of this.elementProperties){let i=this._$Eu(e,r);i!==void 0&&this._$Eh.set(i,e)}this.elementStyles=this.finalizeStyles(this.styles)}static finalizeStyles(t){let e=[];if(Array.isArray(t)){let r=new Set(t.flat(1/0).reverse());for(let i of r)e.unshift(pe(i))}else t!==void 0&&e.push(pe(t));return e}static _$Eu(t,e){let r=e.attribute;return r===!1?void 0:typeof r=="string"?r:typeof t=="string"?t.toLowerCase():void 0}constructor(){super(),this._$Ep=void 0,this.isUpdatePending=!1,this.hasUpdated=!1,this._$Em=null,this._$Ev()}_$Ev(){this._$ES=new Promise(t=>this.enableUpdating=t),this._$AL=new Map,this._$E_(),this.requestUpdate(),this.constructor.l?.forEach(t=>t(this))}addController(t){(this._$EO??=new Set).add(t),this.renderRoot!==void 0&&this.isConnected&&t.hostConnected?.()}removeController(t){this._$EO?.delete(t)}_$E_(){let t=new Map,e=this.constructor.elementProperties;for(let r of e.keys())this.hasOwnProperty(r)&&(t.set(r,this[r]),delete this[r]);t.size>0&&(this._$Ep=t)}createRenderRoot(){let t=this.shadowRoot??this.attachShadow(this.constructor.shadowRootOptions);return Ie(t,this.constructor.elementStyles),t}connectedCallback(){this.renderRoot??=this.createRenderRoot(),this.enableUpdating(!0),this._$EO?.forEach(t=>t.hostConnected?.())}enableUpdating(t){}disconnectedCallback(){this._$EO?.forEach(t=>t.hostDisconnected?.())}attributeChangedCallback(t,e,r){this._$AK(t,r)}_$ET(t,e){let r=this.constructor.elementProperties.get(t),i=this.constructor._$Eu(t,r);if(i!==void 0&&r.reflect===!0){let a=(r.converter?.toAttribute!==void 0?r.converter:z).toAttribute(e,r.type);this._$Em=t,a==null?this.removeAttribute(i):this.setAttribute(i,a),this._$Em=null}}_$AK(t,e){let r=this.constructor,i=r._$Eh.get(t);if(i!==void 0&&this._$Em!==i){let a=r.getPropertyOptions(i),s=typeof a.converter=="function"?{fromAttribute:a.converter}:a.converter?.fromAttribute!==void 0?a.converter:z;this._$Em=i;let o=s.fromAttribute(e,a.type);this[i]=o??this._$Ej?.get(i)??o,this._$Em=null}}requestUpdate(t,e,r,i=!1,a){if(t!==void 0){let s=this.constructor;if(i===!1&&(a=this[t]),r??=s.getPropertyOptions(t),!((r.hasChanged??ee)(a,e)||r.useDefault&&r.reflect&&a===this._$Ej?.get(t)&&!this.hasAttribute(s._$Eu(t,r))))return;this.C(t,e,r)}this.isUpdatePending===!1&&(this._$ES=this._$EP())}C(t,e,{useDefault:r,reflect:i,wrapped:a},s){r&&!(this._$Ej??=new Map).has(t)&&(this._$Ej.set(t,s??e??this[t]),a!==!0||s!==void 0)||(this._$AL.has(t)||(this.hasUpdated||r||(e=void 0),this._$AL.set(t,e)),i===!0&&this._$Em!==t&&(this._$Eq??=new Set).add(t))}async _$EP(){this.isUpdatePending=!0;try{await this._$ES}catch(e){Promise.reject(e)}let t=this.scheduleUpdate();return t!=null&&await t,!this.isUpdatePending}scheduleUpdate(){return this.performUpdate()}performUpdate(){if(!this.isUpdatePending)return;if(!this.hasUpdated){if(this.renderRoot??=this.createRenderRoot(),this._$Ep){for(let[i,a]of this._$Ep)this[i]=a;this._$Ep=void 0}let r=this.constructor.elementProperties;if(r.size>0)for(let[i,a]of r){let{wrapped:s}=a,o=this[i];s!==!0||this._$AL.has(i)||o===void 0||this.C(i,void 0,a,o)}}let t=!1,e=this._$AL;try{t=this.shouldUpdate(e),t?(this.willUpdate(e),this._$EO?.forEach(r=>r.hostUpdate?.()),this.update(e)):this._$EM()}catch(r){throw t=!1,this._$EM(),r}t&&this._$AE(e)}willUpdate(t){}_$AE(t){this._$EO?.forEach(e=>e.hostUpdated?.()),this.hasUpdated||(this.hasUpdated=!0,this.firstUpdated(t)),this.updated(t)}_$EM(){this._$AL=new Map,this.isUpdatePending=!1}get updateComplete(){return this.getUpdateComplete()}getUpdateComplete(){return this._$ES}shouldUpdate(t){return!0}update(t){this._$Eq&&=this._$Eq.forEach(e=>this._$ET(e,this[e])),this._$EM()}updated(t){}firstUpdated(t){}};k.elementStyles=[],k.shadowRootOptions={mode:"open"},k[H("elementProperties")]=new Map,k[H("finalized")]=new Map,$t?.({ReactiveElement:k}),(X.reactiveElementVersions??=[]).push("2.1.2");var ve=globalThis,Le=n=>n,te=ve.trustedTypes,Ue=te?te.createPolicy("lit-html",{createHTML:n=>n}):void 0,Ge="$lit$",A=`lit$${Math.random().toFixed(9).slice(2)}$`,qe="?"+A,Et=`<${qe}>`,N=document,j=()=>N.createComment(""),G=n=>n===null||typeof n!="object"&&typeof n!="function",ye=Array.isArray,Dt=n=>ye(n)||typeof n?.[Symbol.iterator]=="function",he=`[ 	
\f\r]`,W=/<(?:(!--|\/[^a-zA-Z])|(\/?[a-zA-Z][^>\s]*)|(\/?$))/g,Be=/-->/g,He=/>/g,P=RegExp(`>|${he}(?:([^\\s"'>=/]+)(${he}*=${he}*(?:[^ 	
\f\r"'\`<>=]|("|')|))|$)`,"g"),ze=/'/g,We=/"/g,Ye=/^(?:script|style|textarea|title)$/i,we=n=>(t,...e)=>({_$litType$:n,strings:t,values:e}),c=we(1),lr=we(2),dr=we(3),O=Symbol.for("lit-noChange"),h=Symbol.for("lit-nothing"),je=new WeakMap,C=N.createTreeWalker(N,129);function Ke(n,t){if(!ye(n)||!n.hasOwnProperty("raw"))throw Error("invalid template strings array");return Ue!==void 0?Ue.createHTML(t):t}var kt=(n,t)=>{let e=n.length-1,r=[],i,a=t===2?"<svg>":t===3?"<math>":"",s=W;for(let o=0;o<e;o++){let l=n[o],d,p,u=-1,y=0;for(;y<l.length&&(s.lastIndex=y,p=s.exec(l),p!==null);)y=s.lastIndex,s===W?p[1]==="!--"?s=Be:p[1]!==void 0?s=He:p[2]!==void 0?(Ye.test(p[2])&&(i=RegExp("</"+p[2],"g")),s=P):p[3]!==void 0&&(s=P):s===P?p[0]===">"?(s=i??W,u=-1):p[1]===void 0?u=-2:(u=s.lastIndex-p[2].length,d=p[1],s=p[3]===void 0?P:p[3]==='"'?We:ze):s===We||s===ze?s=P:s===Be||s===He?s=W:(s=P,i=void 0);let g=s===P&&n[o+1].startsWith("/>")?" ":"";a+=s===W?l+Et:u>=0?(r.push(d),l.slice(0,u)+Ge+l.slice(u)+A+g):l+A+(u===-2?o:g)}return[Ke(n,a+(n[e]||"<?>")+(t===2?"</svg>":t===3?"</math>":"")),r]},q=class n{constructor({strings:t,_$litType$:e},r){let i;this.parts=[];let a=0,s=0,o=t.length-1,l=this.parts,[d,p]=kt(t,e);if(this.el=n.createElement(d,r),C.currentNode=this.el.content,e===2||e===3){let u=this.el.content.firstChild;u.replaceWith(...u.childNodes)}for(;(i=C.nextNode())!==null&&l.length<o;){if(i.nodeType===1){if(i.hasAttributes())for(let u of i.getAttributeNames())if(u.endsWith(Ge)){let y=p[s++],g=i.getAttribute(u).split(A),w=/([.?@])?(.*)/.exec(y);l.push({type:1,index:a,name:w[2],strings:g,ctor:w[1]==="."?_e:w[1]==="?"?ge:w[1]==="@"?fe:V}),i.removeAttribute(u)}else u.startsWith(A)&&(l.push({type:6,index:a}),i.removeAttribute(u));if(Ye.test(i.tagName)){let u=i.textContent.split(A),y=u.length-1;if(y>0){i.textContent=te?te.emptyScript:"";for(let g=0;g<y;g++)i.append(u[g],j()),C.nextNode(),l.push({type:2,index:++a});i.append(u[y],j())}}}else if(i.nodeType===8)if(i.data===qe)l.push({type:2,index:a});else{let u=-1;for(;(u=i.data.indexOf(A,u+1))!==-1;)l.push({type:7,index:a}),u+=A.length-1}a++}}static createElement(t,e){let r=N.createElement("template");return r.innerHTML=t,r}};function F(n,t,e=n,r){if(t===O)return t;let i=r!==void 0?e._$Co?.[r]:e._$Cl,a=G(t)?void 0:t._$litDirective$;return i?.constructor!==a&&(i?._$AO?.(!1),a===void 0?i=void 0:(i=new a(n),i._$AT(n,e,r)),r!==void 0?(e._$Co??=[])[r]=i:e._$Cl=i),i!==void 0&&(t=F(n,i._$AS(n,t.values),i,r)),t}var me=class{constructor(t,e){this._$AV=[],this._$AN=void 0,this._$AD=t,this._$AM=e}get parentNode(){return this._$AM.parentNode}get _$AU(){return this._$AM._$AU}u(t){let{el:{content:e},parts:r}=this._$AD,i=(t?.creationScope??N).importNode(e,!0);C.currentNode=i;let a=C.nextNode(),s=0,o=0,l=r[0];for(;l!==void 0;){if(s===l.index){let d;l.type===2?d=new Y(a,a.nextSibling,this,t):l.type===1?d=new l.ctor(a,l.name,l.strings,this,t):l.type===6&&(d=new be(a,this,t)),this._$AV.push(d),l=r[++o]}s!==l?.index&&(a=C.nextNode(),s++)}return C.currentNode=N,i}p(t){let e=0;for(let r of this._$AV)r!==void 0&&(r.strings!==void 0?(r._$AI(t,r,e),e+=r.strings.length-2):r._$AI(t[e])),e++}},Y=class n{get _$AU(){return this._$AM?._$AU??this._$Cv}constructor(t,e,r,i){this.type=2,this._$AH=h,this._$AN=void 0,this._$AA=t,this._$AB=e,this._$AM=r,this.options=i,this._$Cv=i?.isConnected??!0}get parentNode(){let t=this._$AA.parentNode,e=this._$AM;return e!==void 0&&t?.nodeType===11&&(t=e.parentNode),t}get startNode(){return this._$AA}get endNode(){return this._$AB}_$AI(t,e=this){t=F(this,t,e),G(t)?t===h||t==null||t===""?(this._$AH!==h&&this._$AR(),this._$AH=h):t!==this._$AH&&t!==O&&this._(t):t._$litType$!==void 0?this.$(t):t.nodeType!==void 0?this.T(t):Dt(t)?this.k(t):this._(t)}O(t){return this._$AA.parentNode.insertBefore(t,this._$AB)}T(t){this._$AH!==t&&(this._$AR(),this._$AH=this.O(t))}_(t){this._$AH!==h&&G(this._$AH)?this._$AA.nextSibling.data=t:this.T(N.createTextNode(t)),this._$AH=t}$(t){let{values:e,_$litType$:r}=t,i=typeof r=="number"?this._$AC(t):(r.el===void 0&&(r.el=q.createElement(Ke(r.h,r.h[0]),this.options)),r);if(this._$AH?._$AD===i)this._$AH.p(e);else{let a=new me(i,this),s=a.u(this.options);a.p(e),this.T(s),this._$AH=a}}_$AC(t){let e=je.get(t.strings);return e===void 0&&je.set(t.strings,e=new q(t)),e}k(t){ye(this._$AH)||(this._$AH=[],this._$AR());let e=this._$AH,r,i=0;for(let a of t)i===e.length?e.push(r=new n(this.O(j()),this.O(j()),this,this.options)):r=e[i],r._$AI(a),i++;i<e.length&&(this._$AR(r&&r._$AB.nextSibling,i),e.length=i)}_$AR(t=this._$AA.nextSibling,e){for(this._$AP?.(!1,!0,e);t!==this._$AB;){let r=Le(t).nextSibling;Le(t).remove(),t=r}}setConnected(t){this._$AM===void 0&&(this._$Cv=t,this._$AP?.(t))}},V=class{get tagName(){return this.element.tagName}get _$AU(){return this._$AM._$AU}constructor(t,e,r,i,a){this.type=1,this._$AH=h,this._$AN=void 0,this.element=t,this.name=e,this._$AM=i,this.options=a,r.length>2||r[0]!==""||r[1]!==""?(this._$AH=Array(r.length-1).fill(new String),this.strings=r):this._$AH=h}_$AI(t,e=this,r,i){let a=this.strings,s=!1;if(a===void 0)t=F(this,t,e,0),s=!G(t)||t!==this._$AH&&t!==O,s&&(this._$AH=t);else{let o=t,l,d;for(t=a[0],l=0;l<a.length-1;l++)d=F(this,o[r+l],e,l),d===O&&(d=this._$AH[l]),s||=!G(d)||d!==this._$AH[l],d===h?t=h:t!==h&&(t+=(d??"")+a[l+1]),this._$AH[l]=d}s&&!i&&this.j(t)}j(t){t===h?this.element.removeAttribute(this.name):this.element.setAttribute(this.name,t??"")}},_e=class extends V{constructor(){super(...arguments),this.type=3}j(t){this.element[this.name]=t===h?void 0:t}},ge=class extends V{constructor(){super(...arguments),this.type=4}j(t){this.element.toggleAttribute(this.name,!!t&&t!==h)}},fe=class extends V{constructor(t,e,r,i,a){super(t,e,r,i,a),this.type=5}_$AI(t,e=this){if((t=F(this,t,e,0)??h)===O)return;let r=this._$AH,i=t===h&&r!==h||t.capture!==r.capture||t.once!==r.once||t.passive!==r.passive,a=t!==h&&(r===h||i);i&&this.element.removeEventListener(this.name,this,r),a&&this.element.addEventListener(this.name,this,t),this._$AH=t}handleEvent(t){typeof this._$AH=="function"?this._$AH.call(this.options?.host??this.element,t):this._$AH.handleEvent(t)}},be=class{constructor(t,e,r){this.element=t,this.type=6,this._$AN=void 0,this._$AM=e,this.options=r}get _$AU(){return this._$AM._$AU}_$AI(t){F(this,t)}};var Tt=ve.litHtmlPolyfillSupport;Tt?.(q,Y),(ve.litHtmlVersions??=[]).push("3.3.3");var Qe=(n,t,e)=>{let r=e?.renderBefore??t,i=r._$litPart$;if(i===void 0){let a=e?.renderBefore??null;r._$litPart$=i=new Y(t.insertBefore(j(),a),a,void 0,e??{})}return i._$AI(n),i};var Se=globalThis,R=class extends k{constructor(){super(...arguments),this.renderOptions={host:this},this._$Do=void 0}createRenderRoot(){let t=super.createRenderRoot();return this.renderOptions.renderBefore??=t.firstChild,t}update(t){let e=this.render();this.hasUpdated||(this.renderOptions.isConnected=this.isConnected),super.update(t),this._$Do=Qe(e,this.renderRoot,this.renderOptions)}connectedCallback(){super.connectedCallback(),this._$Do?.setConnected(!0)}disconnectedCallback(){super.disconnectedCallback(),this._$Do?.setConnected(!1)}render(){return O}};R._$litElement$=!0,R.finalized=!0,Se.litElementHydrateSupport?.({LitElement:R});var At=Se.litElementPolyfillSupport;At?.({LitElement:R});(Se.litElementVersions??=[]).push("4.2.2");var Je=n=>(t,e)=>{e!==void 0?e.addInitializer(()=>{customElements.define(n,t)}):customElements.define(n,t)};var Rt={attribute:!0,type:String,converter:z,reflect:!1,hasChanged:ee},Pt=(n=Rt,t,e)=>{let{kind:r,metadata:i}=e,a=globalThis.litPropertyMetadata.get(i);if(a===void 0&&globalThis.litPropertyMetadata.set(i,a=new Map),r==="setter"&&((n=Object.create(n)).wrapped=!0),a.set(e.name,n),r==="accessor"){let{name:s}=e;return{set(o){let l=t.get.call(this);t.set.call(this,o),this.requestUpdate(s,l,n,!0,o)},init(o){return o!==void 0&&this.C(s,void 0,n,o),o}}}if(r==="setter"){let{name:s}=e;return function(o){let l=this[s];t.call(this,o),this.requestUpdate(s,l,n,!0,o)}}throw Error("Unsupported decorator location: "+r)};function re(n){return(t,e)=>typeof e=="object"?Pt(n,t,e):((r,i,a)=>{let s=i.hasOwnProperty(a);return i.constructor.createProperty(a,r),s?Object.getOwnPropertyDescriptor(i,a):void 0})(n,t,e)}function S(n){return re({...n,state:!0,attribute:!1})}var xe="Energy Actions";var Ct=/RECOVERY REQUIRED|OPERATOR DECISION REQUIRED|RESTORE BLOCKED|RECOVERY BLOCKED|\bFAILED\b|VERIFY ERROR|VERIFY TIMEOUT|VERIFY REFUSED/i,Nt=/DEFERRED/i,Ot=/^(RESTORING|STARTING|ACTIVATION VERIFY)/i;function ne(n){let{active:t,armed:e,operationInProgress:r,statusText:i}=n;return t===null||e===null||r===null?"unavailable":i&&Ct.test(i)?"recovery_attention":i&&Nt.test(i)?"deferred":i&&Ot.test(i)?"busy":t?"active":r?"busy":e?"armed":"ready"}function Ze(n){return n==="armed"}function $e(n){return n!=="busy"&&n!=="unavailable"}function Xe(n){return n==="ready"||n==="armed"}var Mt={unavailable:"Unavailable",recovery_attention:"Attention Needed",deferred:"Waiting For Inverter",busy:"Working",active:"Active",armed:"Armed",ready:"Ready"};function et(n){return Mt[n]}var It=/RECOVERY REQUIRED|OPERATOR DECISION REQUIRED|ACCEPT REFUSED|Recovery Arm first|RESTORE BLOCKED|RECOVERY BLOCKED|\bFAILED\b|VERIFY ERROR|VERIFY TIMEOUT|VERIFY REFUSED/i,Ft=/DEFERRED/i,Vt=/^(RESTORING|STARTING)/i;function ae(n){let{active:t,armed:e,operationInProgress:r,snapshotValid:i,statusText:a}=n;return t===null||e===null||r===null||i===null?"unavailable":a&&It.test(a)?"recovery_attention":a&&Ft.test(a)?"deferred":a&&Vt.test(a)?"busy":t?"active":r?"busy":i?"deferred":e?"armed":"ready"}function tt(n){return n==="armed"}function se(n){return n!=="busy"&&n!=="unavailable"}function rt(n){return n==="ready"||n==="armed"}var Lt={unavailable:"Unavailable",recovery_attention:"Attention Needed",deferred:"Waiting For Inverter",busy:"Working",active:"Active",armed:"Armed",ready:"Ready"};function Ut(n){return Lt[n]}function it(n,t){return n==="ready"&&t===!0?"scheduled":n}function nt(n){return n==="scheduled"?"Scheduled":n==="interlocked"?"Interlocked":Ut(n)}var Bt=/target (\d+)\s*W export/i,Ht=/Stop SOC (\d+)\s*%/i;function at(n,t){if(n!==null&&Number.isFinite(n))return n;let e=t?Bt.exec(t):null;return e?Number(e[1]):null}function st(n,t){if(n!==null&&Number.isFinite(n))return n;let e=t?Ht.exec(t):null;return e?Number(e[1]):null}var zt=/OPERATOR DECISION REQUIRED|ACCEPT REFUSED|Recovery Arm first/i;function ot(n,t){return t===!0&&!!n&&zt.test(n)}var Wt=/RECOVERY BLOCKED|inverter writes? (?:are |is )?locked|deliberate recovery required/i,jt=/START FAILED|ACTIVATION (?:VERIFY|WRITE) FAILED/i,Gt=/OPERATOR DECISION REQUIRED/i,qt=/press End Free Power|retry(?:ing)? restore/i,Yt=/\bRECOVERY REQUIRED\b/i,Kt=/snapshot retained/i,Qt=/RESTORE BLOCKED/i;function lt(n){let t=n.statusText??"",e=n.snapshotValid;return Wt.test(t)?{actionable:!1,actionLabel:null,secondary:!1,explanation:"Deliberate recovery is required - this will not clear on its own."}:jt.test(t)&&e===!1?{actionable:!1,actionLabel:null,secondary:!1,explanation:"No saved snapshot is held - there is nothing to restore."}:Gt.test(t)&&qt.test(t)&&e===!0?{actionable:!0,actionLabel:"Retry End & Restore",secondary:!1,explanation:null}:Yt.test(t)&&e===!0?{actionable:!0,actionLabel:"Restore Saved Settings",secondary:!1,explanation:null}:Kt.test(t)&&e===!0?{actionable:!0,actionLabel:"End & Restore Now",secondary:!0,explanation:null}:Qt.test(t)?e===!0?{actionable:!0,actionLabel:"Attempt Restore",secondary:!0,explanation:"Operator decision required - live inverter state matches neither the saved snapshot nor Free Power's intended state. Restoring is not guaranteed to resolve the mismatch."}:{actionable:!1,actionLabel:null,secondary:!1,explanation:"Operator decision required, and no confirmed snapshot is held to restore - review the inverter's live state directly."}:e===!0?{actionable:!0,actionLabel:"End & Restore Now",secondary:!1,explanation:null}:{actionable:!1,actionLabel:null,secondary:!1,explanation:"Unable to confirm a saved snapshot is held - review the firmware status directly before acting."}}var Jt=new Set(["active","busy","recovery_attention","deferred"]);function Zt(n){return n!==null&&Jt.has(n)}function Ee(n,t){return(n==="ready"||n==="armed")&&Zt(t)}function K(n,t){return n&&!t}function De(n,t){switch(t){case"busy":return`${n} is restoring inverter state.`;case"recovery_attention":case"deferred":return`${n} requires recovery before this can be used.`;default:return`${n} currently owns inverter control.`}}function dt(n){return n.armed===!0?"armed":"hidden"}function ke(n){return!!n&&/^REJECTED/i.test(n.trim())}function Te(n){return!!n&&/^BLOCKED/i.test(n.trim())}function Ae(n){return n===!0}function ct(n,t){return n==="ready"&&t==="armed"?"scheduled":n}function Re(n){return{domain:"input_boolean",service:"turn_on",data:{entity_id:n}}}function Pe(n){return{domain:"script",service:"turn_on",data:{entity_id:n}}}function ut(n,t){return{domain:"input_datetime",service:"set_datetime",data:{entity_id:n,datetime:t}}}function Ce(n,t){return{domain:"input_number",service:"set_value",data:{entity_id:n,value:t}}}function pt(n,t){return t===null||!Number.isFinite(t)||t<=0?n:Math.min(n,t)}var Xt=/^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2}):(\d{2})$/;function M(n){if(!n)return null;let t=Xt.exec(n.trim());if(!t)return null;let[,e,r,i,a,s,o]=t,l=new Date(Number(e),Number(r)-1,Number(i),Number(a),Number(s),Number(o));return Number.isNaN(l.getTime())?null:l}function ht(n){let t=e=>e.toString().padStart(2,"0");return`${n.getFullYear()}-${t(n.getMonth()+1)}-${t(n.getDate())} ${t(n.getHours())}:${t(n.getMinutes())}:${t(n.getSeconds())}`}var er=["Sun","Mon","Tue","Wed","Thu","Fri","Sat"],tr=["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];function Ne(n){let t=er[n.getDay()],e=n.getDate(),r=tr[n.getMonth()],i=n.getHours().toString().padStart(2,"0"),a=n.getMinutes().toString().padStart(2,"0");return`${t} ${e} ${r} \u2022 ${i}:${a}`}function Q(n,t){let e=n-t;if(e<=0)return null;let r=Math.floor(e/1e3),i=Math.floor(r/3600),a=Math.floor(r%3600/60),s=r%60;return i>0?`${i}h ${a}m`:a>0?`${a}m ${s.toString().padStart(2,"0")}s`:`${s}s`}function T(n){return n==null||Number.isNaN(n)?"--":Math.abs(n)>=1e3?`${(n/1e3).toFixed(2)} kW`:`${n.toFixed(0)} W`}function I(n){if(n==null||Number.isNaN(n))return"--";let t=Math.round(n);if(t<60)return`${t} min`;let e=Math.floor(t/60),r=t%60;return r===0?`${e}h`:`${e}h ${r}m`}function L(n){return n==null||Number.isNaN(n)?"--":`${Math.round(n)}%`}function m(n){if(n==null||n==="unknown"||n==="unavailable"||n==="")return null;let t=Number(n);return Number.isFinite(t)?t:null}function _(n){return n==null||n==="unknown"||n==="unavailable"||n===""?null:n==="on"}var oe=4e3,rr=1e3,f=class extends R{constructor(){super(...arguments);this._confirmEndRestore=!1;this._confirmEndDump=!1;this._dumpMode="now";this._nowMs=Date.now();this._mode="now"}static getStubConfig(){return{type:"custom:ecco-energy-actions-card",title:xe,free_power:{active:"binary_sensor.free_power_active",operation_in_progress:"binary_sensor.free_power_operation_in_progress",snapshot_valid:"binary_sensor.free_power_snapshot_valid",status:"sensor.free_power_status",ends_at:"sensor.free_power_ends_at",failures:"sensor.free_power_failures_since_boot",start_attempts:"sensor.free_power_start_attempts_since_boot",start_successes:"sensor.free_power_start_successes_since_boot",restore_successes:"sensor.free_power_restore_successes_since_boot",write_enable:"switch.free_power_write_enable",max_charge_power:"number.free_power_max_charge_power",duration:"number.free_power_duration",start:"button.start_free_power_charge_now",end_restore:"button.end_free_power_restore_now"},schedule:{armed:"input_boolean.ecco_free_power_schedule_armed",start:"input_datetime.ecco_free_power_schedule_start",duration:"input_number.ecco_free_power_schedule_duration",power:"input_number.ecco_free_power_schedule_power",last_result:"input_text.ecco_free_power_schedule_last_result",status:"sensor.ecco_free_power_schedule_status",cancel:"script.ecco_free_power_cancel_schedule"},dump_to_grid:{active:"binary_sensor.dump_to_grid_active",operation_in_progress:"binary_sensor.dump_to_grid_operation_in_progress",snapshot_valid:"binary_sensor.dump_to_grid_snapshot_valid",status:"sensor.dump_to_grid_status",ends_at:"sensor.dump_to_grid_ends_at",battery_soc:"sensor.ecco_battery_soc",failures:"sensor.dump_to_grid_failures_since_boot",start_attempts:"sensor.dump_to_grid_start_attempts_since_boot",start_successes:"sensor.dump_to_grid_start_successes_since_boot",restore_successes:"sensor.dump_to_grid_restore_successes_since_boot",write_enable:"switch.dump_to_grid_write_enable",export_power:"number.dump_to_grid_export_power",stop_soc:"number.dump_to_grid_stop_soc",duration:"number.dump_to_grid_duration",start:"button.start_dump_to_grid_now",end_restore:"button.end_dump_to_grid_restore_now",active_export_power:"sensor.dump_to_grid_active_export_power",active_stop_soc:"sensor.dump_to_grid_active_stop_soc",last_end_reason:"sensor.dump_to_grid_last_end_reason",recovery_arm:"switch.dump_to_grid_recovery_arm",recovery_force_restore:"button.dump_to_grid_force_restore_original",recovery_accept:"button.dump_to_grid_accept_current_state",recovery_state:"sensor.dump_to_grid_recovery_state",schedule:{armed:"input_boolean.ecco_dump_to_grid_schedule_armed",start:"input_datetime.ecco_dump_to_grid_schedule_start",duration:"input_number.ecco_dump_to_grid_schedule_duration",power:"input_number.ecco_dump_to_grid_schedule_power",stop_soc:"input_number.ecco_dump_to_grid_schedule_stop_soc",last_result:"input_text.ecco_dump_to_grid_schedule_last_result",status:"sensor.ecco_dump_to_grid_schedule_status",cancel:"script.ecco_dump_to_grid_cancel_schedule"}}}}setConfig(e){if(!e||typeof e!="object")throw new Error("ecco-energy-actions-card: invalid configuration");if(!e.free_power)throw new Error("ecco-energy-actions-card: `free_power:` entity mapping is required");this._config=e}getCardSize(){return this._config?.schedule||this._config?.dump_to_grid?.schedule?6:4}disconnectedCallback(){super.disconnectedCallback(),this._stopTicking(),this._confirmTimer&&clearTimeout(this._confirmTimer),this._confirmDumpTimer&&clearTimeout(this._confirmDumpTimer)}shouldUpdate(e){return!!this._config}willUpdate(){let e=this._config?.free_power;if(e){this._pendingPower!==void 0&&m(this._entityState(e.max_charge_power))===this._pendingPower&&(this._pendingPower=void 0),this._pendingDuration!==void 0&&m(this._entityState(e.duration))===this._pendingDuration&&(this._pendingDuration=void 0);let a=_(this._entityState(e.active)),s=_(this._entityState(e.write_enable)),o=_(this._entityState(e.operation_in_progress)),l=this._entityState(e.status),d=ne({active:a,armed:s,operationInProgress:o,statusText:l});this._lastVisualState!==void 0&&this._lastVisualState!==d&&this._confirmEndRestore&&(this._confirmEndRestore=!1,this._confirmTimer&&clearTimeout(this._confirmTimer)),this._lastVisualState=d}let r=this._config?.schedule;r&&(this._pendingSchedulePower!==void 0&&m(this._entityState(r.power))===this._pendingSchedulePower&&(this._pendingSchedulePower=void 0),this._pendingScheduleDuration!==void 0&&m(this._entityState(r.duration))===this._pendingScheduleDuration&&(this._pendingScheduleDuration=void 0));let i=this._config?.dump_to_grid;if(i){this._pendingDumpPower!==void 0&&m(this._entityState(i.export_power))===this._pendingDumpPower&&(this._pendingDumpPower=void 0),this._pendingDumpStopSoc!==void 0&&m(this._entityState(i.stop_soc))===this._pendingDumpStopSoc&&(this._pendingDumpStopSoc=void 0),this._pendingDumpDuration!==void 0&&m(this._entityState(i.duration))===this._pendingDumpDuration&&(this._pendingDumpDuration=void 0);let a=i.schedule;a&&(this._pendingDumpSchedulePower!==void 0&&m(this._entityState(a.power))===this._pendingDumpSchedulePower&&(this._pendingDumpSchedulePower=void 0),this._pendingDumpScheduleStopSoc!==void 0&&m(this._entityState(a.stop_soc))===this._pendingDumpScheduleStopSoc&&(this._pendingDumpScheduleStopSoc=void 0),this._pendingDumpScheduleDuration!==void 0&&m(this._entityState(a.duration))===this._pendingDumpScheduleDuration&&(this._pendingDumpScheduleDuration=void 0));let s=_(this._entityState(i.active)),o=_(this._entityState(i.write_enable)),l=_(this._entityState(i.operation_in_progress)),d=_(this._entityState(i.snapshot_valid)),p=this._entityState(i.status),u=ae({active:s,armed:o,operationInProgress:l,snapshotValid:d,statusText:p});this._lastDumpVisualState!==void 0&&this._lastDumpVisualState!==u&&this._confirmEndDump&&(this._confirmEndDump=!1,this._confirmDumpTimer&&clearTimeout(this._confirmDumpTimer)),this._lastDumpVisualState=u}}updated(){let e=this._active()||this._scheduleArmed()||this._dumpActive()||this._dumpScheduleArmed();e&&!this._tickTimer?this._tickTimer=setInterval(()=>{this._nowMs=Date.now()},rr):!e&&this._tickTimer&&this._stopTicking()}_stopTicking(){this._tickTimer&&(clearInterval(this._tickTimer),this._tickTimer=void 0)}_active(){let e=this._config?.free_power;return e?_(this._entityState(e.active))===!0:!1}_scheduleArmed(){let e=this._config?.schedule;return e?_(this._entityState(e.armed))===!0:!1}_dumpActive(){let e=this._config?.dump_to_grid;return e?_(this._entityState(e.active))===!0:!1}_dumpScheduleArmed(){let e=this._config?.dump_to_grid?.schedule;return e?_(this._entityState(e.armed))===!0:!1}_freePowerVisualStateForInterlock(){let e=this._config?.free_power;if(!e||!this.hass)return null;let r=_(this._entityState(e.active)),i=_(this._entityState(e.write_enable)),a=_(this._entityState(e.operation_in_progress)),s=this._entityState(e.status);return ne({active:r,armed:i,operationInProgress:a,statusText:s})}_dumpVisualStateForInterlock(){let e=this._config?.dump_to_grid;if(!e||!this.hass)return null;let r=_(this._entityState(e.active)),i=_(this._entityState(e.write_enable)),a=_(this._entityState(e.operation_in_progress)),s=_(this._entityState(e.snapshot_valid)),o=this._entityState(e.status);return ae({active:r,armed:i,operationInProgress:a,snapshotValid:s,statusText:o})}_entityState(e){if(!(!e||!this.hass))return this.hass.states[e]?.state}_entity(e){if(!(!e||!this.hass))return this.hass.states[e]}_moreInfo(e){e&&this.dispatchEvent(new CustomEvent("hass-more-info",{detail:{entityId:e},bubbles:!0,composed:!0}))}_callService(e,r,i){this.hass?.callService&&this.hass.callService(e,r,i)}_callServiceObj(e){this._callService(e.domain,e.service,e.data)}render(){if(!this._config)return c``;let e=this._config.title??xe;return c`
      <ha-card>
        <h1 class="card-title">${e}</h1>
        <div class="actions-grid">
          ${this._renderFreePowerTile()}
          ${this._renderDumpToGridTile()}
        </div>
      </ha-card>
    `}_renderFreePowerTile(){let e=this._config?.free_power;if(!e||!this.hass)return this._renderFreePowerUnavailable("Free Power is not configured on this card.");let r=_(this._entityState(e.active)),i=_(this._entityState(e.write_enable)),a=_(this._entityState(e.operation_in_progress)),s=_(this._entityState(e.snapshot_valid)),o=this._entityState(e.status),l=ne({active:r,armed:i,operationInProgress:a,statusText:o});if(l==="unavailable")return this._renderFreePowerUnavailable("Free Power entities are unavailable right now.");let d=this._config?.schedule,p=d?_(this._entityState(d.armed)):null,u=dt({armed:p}),y=d?ct(l,u):l,g=this._dumpVisualStateForInterlock(),w=Ee(l,g),$=w?"interlocked":y,E=w?De("Dump to Grid",g):void 0,D=this._entity(e.max_charge_power),b=this._entity(e.duration),U=this._pendingPower??m(D?.state),x=this._pendingDuration??m(b?.state),le=this._iconFor($),de=this._labelFor($);return c`
      <div class="tile free-power-tile state-${$}">
        <div class="tile-header">
          <div class="tile-heading">
            <ha-icon class="tile-icon" icon=${le}></ha-icon>
            <span class="tile-name">Free Power</span>
          </div>
          <span class="state-pill state-${$}">${de}</span>
        </div>

        <div class="free-power-body">
          ${d&&u==="armed"?this._renderScheduleBanner(d):h}
          ${w?this._renderInterlockBanner(E):h}

          ${this._renderFreePowerBody(l,{fp:e,schedule:d,statusText:o,snapshotValid:s,interlocked:w,stagedPowerW:U,stagedDurationMin:x,stagedPowerEntity:D,stagedDurationEntity:b})}
        </div>
      </div>
    `}_iconFor(e){if(e==="scheduled")return"mdi:calendar-clock";if(e==="interlocked")return"mdi:lock-outline";switch(e){case"active":return"mdi:flash";case"armed":return"mdi:shield-flash-outline";case"busy":return"mdi:autorenew";case"deferred":return"mdi:timer-sand";case"recovery_attention":return"mdi:alert-circle-outline";case"unavailable":return"mdi:flash-off-outline";default:return"mdi:flash-outline"}}_labelFor(e){return e==="scheduled"?"Scheduled":e==="interlocked"?"Interlocked":et(e)}_renderInterlockBanner(e){return c`
      <div class="interlock-banner">
        <ha-icon icon="mdi:lock-outline"></ha-icon>
        <div class="interlock-banner-text">${e}</div>
      </div>
    `}_renderFreePowerUnavailable(e){return c`
      <div class="tile free-power-tile state-unavailable">
        <div class="tile-header">
          <div class="tile-heading">
            <ha-icon class="tile-icon" icon="mdi:flash-off-outline"></ha-icon>
            <span class="tile-name">Free Power</span>
          </div>
          <span class="state-pill state-unavailable">Unavailable</span>
        </div>
        <p class="tile-description">${e}</p>
      </div>
    `}_renderFreePowerBody(e,r){switch(e){case"active":return this._renderActiveBody(r);case"busy":return this._renderBusyBody(r.statusText,r.fp.status);case"deferred":return this._renderDeferredBody(r.statusText,r.fp.status);case"recovery_attention":return this._renderAttentionBody(r);default:return this._renderReadyOrArmedBody(e,r)}}_renderReadyOrArmedBody(e,r){let i=!!r.schedule,a=i?this._mode:"now";return c`
      ${i?this._renderModeSelector():h}
      ${a==="later"&&r.schedule?this._renderLaterPanel(r.schedule):this._renderNowPanel(e,r)}
    `}_renderModeSelector(){let e=this._mode==="now";return c`
      <div class="mode-selector" role="tablist">
        <button
          type="button"
          role="tab"
          class="mode-tab ${e?"is-active":""}"
          aria-selected=${e}
          @click=${()=>this._mode="now"}
        >
          <ha-icon icon="mdi:flash"></ha-icon> Now
        </button>
        <button
          type="button"
          role="tab"
          class="mode-tab ${e?"":"is-active"}"
          aria-selected=${!e}
          @click=${()=>this._mode="later"}
        >
          <ha-icon icon="mdi:calendar-clock"></ha-icon> Later
        </button>
      </div>
    `}_renderNowPanel(e,r){let i=e==="armed",a=K(Ze(e),r.interlocked),s=K(Xe(e),r.interlocked);return c`
      <p class="tile-description">Charge the battery from free/zero-cost grid energy.</p>

      ${this._renderNumberControl({label:"Max Charge Power",icon:"mdi:flash",entity:r.stagedPowerEntity,value:r.stagedPowerW,fallbackMin:500,fallbackMax:8e3,fallbackStep:100,formatValue:T,disabled:r.interlocked,onPreview:o=>this._pendingPower=o,onCommit:o=>this._commitNumber("power",o,r.fp.max_charge_power)})}
      ${this._renderNumberControl({label:"Duration",icon:"mdi:timer-outline",entity:r.stagedDurationEntity,value:r.stagedDurationMin,fallbackMin:1,fallbackMax:240,fallbackStep:1,formatValue:I,disabled:r.interlocked,onPreview:o=>this._pendingDuration=o,onCommit:o=>this._commitNumber("duration",o,r.fp.duration)})}

      <div class="readiness-row">
        <ha-icon icon=${i?"mdi:shield-check":"mdi:shield-outline"}></ha-icon>
        <span>${i?"Armed - ready to start":"Safe - no inverter change made by staging values"}</span>
      </div>
      ${this._renderStatusLine(r.statusText,r.fp.status)}

      <div class="action-row">
        <button
          class="arm-toggle ${i?"is-armed":""}"
          ?disabled=${!s}
          @click=${()=>this._toggleArm(r.fp.write_enable,i)}
        >
          <ha-icon icon=${i?"mdi:shield-key":"mdi:shield-key-outline"}></ha-icon>
          ${i?"Disarm":"Arm Free Power"}
        </button>
        <button
          class="start-button"
          ?disabled=${!a}
          @click=${()=>this._callService("button","press",{entity_id:r.fp.start})}
        >
          <ha-icon icon="mdi:play-circle-outline"></ha-icon>
          Start Now
        </button>
      </div>
      <p class="arm-caption">Arm is single-use - it's consumed the moment you press Start, or if the attempt is rejected.</p>
    `}_renderLaterPanel(e){let r=_(this._entityState(e.armed)),i=Ae(r),a=this._entityState(e.start),s=M(a),o=this._entity(e.duration),l=this._entity(e.power),d=this._entity(e.status),p=this._entityState(e.last_result),u=this._pendingScheduleDuration??m(o?.state),y=this._pendingSchedulePower??m(l?.state),g=d?.attributes?.effective_power_limit_w,w=typeof g=="number"?g:m(typeof g=="string"?g:void 0),$=this._numericAttr(l?.attributes?.max,8e3),E=pt($,w),D=ke(p),b=Te(p),U=!i&&s!==null&&s.getTime()>this._nowMs;return c`
      <p class="tile-description">Stage a future Free Power session - Home Assistant arms and starts it automatically.</p>

      <div class="schedule-field">
        <label class="schedule-field-label"><ha-icon icon="mdi:calendar-clock"></ha-icon> Start</label>
        <input
          type="datetime-local"
          class="schedule-datetime-input"
          .value=${s?this._toDatetimeLocalValue(s):""}
          min=${this._toDatetimeLocalValue(new Date(this._nowMs))}
          ?disabled=${i}
          @change=${x=>this._handleScheduleStartChange(e.start,x.target.value)}
        />
      </div>

      ${this._renderNumberControl({label:"Scheduled Power",icon:"mdi:flash",entity:l,value:y,fallbackMin:500,fallbackMax:8e3,fallbackStep:100,maxOverride:E,formatValue:T,disabled:i||!l,onPreview:x=>this._pendingSchedulePower=x,onCommit:x=>this._commitScheduleNumber("power",x,e.power)})}
      ${this._renderNumberControl({label:"Scheduled Duration",icon:"mdi:timer-outline",entity:o,value:u,fallbackMin:1,fallbackMax:240,fallbackStep:1,formatValue:I,disabled:i||!o,onPreview:x=>this._pendingScheduleDuration=x,onCommit:x=>this._commitScheduleNumber("duration",x,e.duration)})}

      ${p?c`<p class="firmware-note ${D||b?"is-warning":""}">${p}</p>`:h}

      <div class="action-row">
        <button
          class="schedule-arm-toggle"
          ?disabled=${i||!U}
          @click=${()=>this._callServiceObj(Re(e.armed))}
        >
          <ha-icon icon="mdi:calendar-arrow-right"></ha-icon>
          Arm Schedule
        </button>
      </div>
      <p class="arm-caption">
        ${i?"Fields are locked while this schedule is armed - cancel it above to edit, then re-arm.":"Arm Schedule never touches the manual Free Power write-enable switch - Home Assistant arms and starts the inverter automatically when the time comes."}
      </p>
    `}_renderScheduleBanner(e){let r=this._entityState(e.start),i=M(r),a=m(this._entityState(e.duration)),s=m(this._entityState(e.power)),o=i?Q(i.getTime(),this._nowMs):null;return c`
      <div class="schedule-banner">
        <ha-icon icon="mdi:calendar-clock"></ha-icon>
        <div class="schedule-banner-text">
          <div class="schedule-banner-line">
            ${i?Ne(i):"--"} • ${T(s)} • ${I(a)}
          </div>
          <div class="schedule-banner-countdown">${o?`Starts in ${o}`:"Starting..."}</div>
        </div>
        <button
          type="button"
          class="schedule-cancel-button"
          @click=${()=>this._callServiceObj(Pe(e.cancel))}
        >
          Cancel
        </button>
      </div>
    `}_toDatetimeLocalValue(e){let r=i=>i.toString().padStart(2,"0");return`${e.getFullYear()}-${r(e.getMonth()+1)}-${r(e.getDate())}T${r(e.getHours())}:${r(e.getMinutes())}`}_handleScheduleStartChange(e,r){if(!r)return;let i=new Date(r);Number.isNaN(i.getTime())||this._callServiceObj(ut(e,ht(i)))}_commitScheduleNumber(e,r,i){e==="power"?this._pendingSchedulePower=r:this._pendingScheduleDuration=r,this._callServiceObj(Ce(i,r))}_renderActiveBody(e){let r=this._entityState(e.fp.ends_at),i=M(r),a=i?Q(i.getTime(),this._nowMs):null;return c`
      <div class="active-hero">
        <div class="active-hero-time">${a??"--:--"}</div>
        <div class="active-hero-label">time remaining</div>
      </div>
      <div class="active-secondary-line">
        ${T(e.stagedPowerW)} target • ends ${i?this._formatClock(i):r??"--"}
      </div>

      <div class="readiness-row">
        <ha-icon icon=${e.snapshotValid?"mdi:content-save-check-outline":"mdi:content-save-alert-outline"}></ha-icon>
        <span>${e.snapshotValid?"Original settings snapshot saved":"No snapshot recorded - check status"}</span>
      </div>

      ${this._renderStatusLine(e.statusText,e.fp.status,{alwaysShow:!0})}
      ${this._renderDiagnosticsDetails(e.fp)}
      ${this._renderEndRestoreButton(e.fp.end_restore,"End & Restore Now",!1,$e("active"))}
    `}_renderBusyBody(e,r){return c`
      <div class="transition-panel">
        <ha-icon class="spin" icon="mdi:autorenew"></ha-icon>
        <div class="transition-text">
          <div class="transition-headline">Working...</div>
          ${this._renderTransitionDetail(e??"Free Power is mid-transaction.",r)}
        </div>
      </div>
      <p class="transition-hint">Controls are disabled while a transaction is in flight - this clears on its own.</p>
    `}_renderDeferredBody(e,r){return c`
      <div class="transition-panel deferred">
        <ha-icon icon="mdi:timer-sand"></ha-icon>
        <div class="transition-text">
          <div class="transition-headline">Waiting for inverter bus</div>
          ${this._renderTransitionDetail(e??"Modbus bus busy - the watchdog will retry.",r)}
        </div>
      </div>
      <p class="transition-hint">This is expected occasionally - the watchdog retries automatically. No action needed.</p>
    `}_renderAttentionBody(e){let r=lt({statusText:e.statusText,snapshotValid:e.snapshotValid});return c`
      <div class="attention-panel">
        <ha-icon icon="mdi:alert-circle-outline"></ha-icon>
        <div class="transition-text">
          <div class="transition-headline">Attention needed</div>
          ${this._renderTransitionDetail(e.statusText??"Free Power requires operator attention.",e.fp.status)}
        </div>
      </div>
      <p class="transition-hint">
        ${r.explanation??"No automatic retry. Starting a new Free Power session is disabled until this clears."}
      </p>
      ${r.actionable?this._renderEndRestoreButton(e.fp.end_restore,r.actionLabel??"End & Restore Now",r.secondary,$e("recovery_attention")):h}
    `}_renderTransitionDetail(e,r){return c`
      <div
        class="transition-detail clickable"
        tabindex="0"
        role="button"
        @click=${()=>this._moreInfo(r)}
        @keydown=${i=>{(i.key==="Enter"||i.key===" ")&&(i.preventDefault(),this._moreInfo(r))}}
      >
        ${e}
      </div>
    `}_renderStatusLine(e,r,i){return!(i?.alwaysShow||!!e&&e!=="Inactive")||!e?h:c`
      <p
        class="firmware-note clickable"
        tabindex="0"
        role="button"
        @click=${()=>this._moreInfo(r)}
        @keydown=${s=>{(s.key==="Enter"||s.key===" ")&&(s.preventDefault(),this._moreInfo(r))}}
      >
        ${e}
      </p>
    `}_renderDiagnosticsDetails(e){let r=[],i=(a,s)=>{let o=m(this._entityState(s));o!==null&&r.push({label:a,value:o.toString()})};return i("Starts",e.start_attempts),i("Started OK",e.start_successes),i("Restored OK",e.restore_successes),i("Failures",e.failures),r.length===0?h:c`
      <details class="diagnostics-details">
        <summary>Details</summary>
        <div class="diagnostics-row">
          ${r.map(a=>c`<span class="diagnostic-chip">${a.label}: ${a.value}</span>`)}
        </div>
      </details>
    `}_renderEndRestoreButton(e,r,i,a){let s=this._confirmEndRestore;return c`
      <button
        class="end-restore-button ${i?"secondary":""} ${s?"confirming":""}"
        ?disabled=${!a}
        @click=${()=>this._handleEndRestoreClick(e)}
      >
        <ha-icon icon="mdi:backup-restore"></ha-icon>
        ${s?"Tap again to End & Restore":r}
        ${s?c`<span class="confirm-progress" style="animation-duration:${oe}ms"></span>`:h}
      </button>
    `}_handleEndRestoreClick(e){if(!this._confirmEndRestore){this._confirmEndRestore=!0,this._confirmTimer=setTimeout(()=>{this._confirmEndRestore=!1},oe);return}this._confirmTimer&&clearTimeout(this._confirmTimer),this._confirmEndRestore=!1,this._callService("button","press",{entity_id:e})}_toggleArm(e,r){this._callService("switch",r?"turn_off":"turn_on",{entity_id:e})}_commitNumber(e,r,i){e==="power"?this._pendingPower=r:this._pendingDuration=r,this._callService("number","set_value",{entity_id:i,value:r})}_commitDumpNumber(e,r,i){e==="power"?this._pendingDumpPower=r:e==="stop_soc"?this._pendingDumpStopSoc=r:this._pendingDumpDuration=r,this._callService("number","set_value",{entity_id:i,value:r})}_handleEndDumpClick(e){if(!this._confirmEndDump){this._confirmEndDump=!0,this._confirmDumpTimer=setTimeout(()=>{this._confirmEndDump=!1},oe);return}this._confirmDumpTimer&&clearTimeout(this._confirmDumpTimer),this._confirmEndDump=!1,this._callService("button","press",{entity_id:e})}_numericAttr(e,r){if(typeof e=="number"&&Number.isFinite(e))return e;if(typeof e=="string"){let i=m(e);if(i!==null)return i}return r}_formatClock(e){let r=e.getHours().toString().padStart(2,"0"),i=e.getMinutes().toString().padStart(2,"0");return`${r}:${i}`}_renderNumberControl(e){let r=e.entity?.attributes??{},i=this._numericAttr(r.min,e.fallbackMin),a=e.maxOverride??this._numericAttr(r.max,e.fallbackMax),s=this._numericAttr(r.step,e.fallbackStep),o=e.value??i,l=e.disabled??!e.entity,d=a>i?Math.max(0,Math.min(100,(o-i)/(a-i)*100)):0;return c`
      <div class="number-control">
        <div class="number-control-label">
          <ha-icon icon=${e.icon}></ha-icon>
          <span>${e.label}</span>
          <span class="number-control-value">${e.formatValue(o)}</span>
        </div>
        <input
          type="range"
          class="number-control-slider"
          style="--eaa-slider-fill:${d}%"
          min=${i}
          max=${a}
          step=${s}
          .value=${String(o)}
          ?disabled=${l}
          @input=${p=>{let u=Number(p.target.value);Number.isFinite(u)&&e.onPreview(u)}}
          @change=${p=>{let u=Number(p.target.value);Number.isFinite(u)&&e.onCommit(u)}}
        />
      </div>
    `}_renderDumpToGridTile(){let e=this._config?.dump_to_grid;if(!e||!this.hass)return this._renderDumpToGridLockedShell();let r=_(this._entityState(e.active)),i=_(this._entityState(e.write_enable)),a=_(this._entityState(e.operation_in_progress)),s=_(this._entityState(e.snapshot_valid)),o=this._entityState(e.status),l=ae({active:r,armed:i,operationInProgress:a,snapshotValid:s,statusText:o});if(l==="unavailable")return this._renderDumpUnavailable("Dump to Grid entities are unavailable right now.");let d=e.schedule,p=d?_(this._entityState(d.armed)):null,u=it(l,p),y=this._freePowerVisualStateForInterlock(),g=Ee(l,y),w=g?"interlocked":u,$=g?De("Free Power",y):void 0,E=this._entity(e.export_power),D=this._entity(e.stop_soc),b=this._entity(e.duration),U=this._pendingDumpPower??m(E?.state),x=this._pendingDumpStopSoc??m(D?.state),le=this._pendingDumpDuration??m(b?.state),de=this._dumpIconFor(w),mt=nt(w);return c`
      <div class="tile dump-to-grid-tile state-${w}">
        <div class="tile-header">
          <div class="tile-heading">
            <ha-icon class="tile-icon" icon=${de}></ha-icon>
            <span class="tile-name">Dump to Grid</span>
          </div>
          <span class="state-pill state-${w}">${mt}</span>
        </div>

        <div class="dump-to-grid-body">
          ${d&&p===!0?this._renderDumpScheduleBanner(d):h}
          ${g?this._renderInterlockBanner($):h}

          ${this._renderDumpBody(l,{dump:e,statusText:o,snapshotValid:s,interlocked:g,stagedPowerW:U,stagedStopSoc:x,stagedDurationMin:le,stagedPowerEntity:E,stagedStopSocEntity:D,stagedDurationEntity:b})}
        </div>
      </div>
    `}_renderDumpToGridLockedShell(){return c`
      <div class="tile dump-to-grid-tile locked">
        <div class="tile-header">
          <div class="tile-heading">
            <ha-icon class="tile-icon" icon="mdi:transmission-tower-export"></ha-icon>
            <span class="tile-name">Dump to Grid</span>
          </div>
          <span class="state-pill state-locked"><ha-icon icon="mdi:lock-outline"></ha-icon> Coming Soon</span>
        </div>
        <p class="tile-description">Export stored battery energy to the grid.</p>

        <div class="locked-preview">
          <div class="locked-row"><span>Export Power</span><span>--</span></div>
          <div class="locked-row"><span>Minimum SOC</span><span>--</span></div>
          <div class="locked-row"><span>Duration</span><span>--</span></div>
        </div>

        <p class="tile-footnote">
          Configure <code>dump_to_grid:</code> on this card to enable Manual Dump to Grid V1.
        </p>
      </div>
    `}_dumpIconFor(e){switch(e){case"scheduled":return"mdi:calendar-clock";case"interlocked":return"mdi:lock-outline";case"active":return"mdi:transmission-tower-export";case"armed":return"mdi:shield-flash-outline";case"busy":return"mdi:autorenew";case"deferred":return"mdi:timer-sand";case"recovery_attention":return"mdi:alert-circle-outline";case"unavailable":return"mdi:transmission-tower-off";default:return"mdi:transmission-tower-export"}}_renderDumpUnavailable(e){return c`
      <div class="tile dump-to-grid-tile state-unavailable">
        <div class="tile-header">
          <div class="tile-heading">
            <ha-icon class="tile-icon" icon="mdi:transmission-tower-off"></ha-icon>
            <span class="tile-name">Dump to Grid</span>
          </div>
          <span class="state-pill state-unavailable">Unavailable</span>
        </div>
        <p class="tile-description">${e}</p>
      </div>
    `}_renderDumpBody(e,r){switch(e){case"active":return this._renderDumpActiveBody(r);case"busy":return this._renderBusyBody(r.statusText??"Dump to Grid is mid-transaction.",r.dump.status);case"deferred":return this._renderDumpDeferredBody(r);case"recovery_attention":return this._renderDumpAttentionBody(r);default:return this._renderDumpReadyOrArmedBody(e,r)}}_renderDumpReadyOrArmedBody(e,r){let i=r.dump.schedule,a=i?this._dumpMode:"now";return c`
      ${i?this._renderDumpModeSelector():h}
      ${a==="later"&&i?this._renderDumpLaterPanel(i):this._renderDumpNowPanel(e,r)}
      ${this._renderDumpLastEndReason(r.dump)}
    `}_renderDumpModeSelector(){let e=this._dumpMode==="now";return c`
      <div class="mode-selector" role="tablist">
        <button
          type="button"
          role="tab"
          class="mode-tab ${e?"is-active":""}"
          aria-selected=${e}
          @click=${()=>this._dumpMode="now"}
        >
          <ha-icon icon="mdi:flash"></ha-icon> Now
        </button>
        <button
          type="button"
          role="tab"
          class="mode-tab ${e?"":"is-active"}"
          aria-selected=${!e}
          @click=${()=>this._dumpMode="later"}
        >
          <ha-icon icon="mdi:calendar-clock"></ha-icon> Later
        </button>
      </div>
    `}_renderDumpNowPanel(e,r){let i=e==="armed",a=K(tt(e),r.interlocked),s=K(rt(e),r.interlocked);return c`
      <p class="tile-description">Export stored battery energy to the grid down to a chosen floor.</p>

      ${this._renderNumberControl({label:"Export Power",icon:"mdi:transmission-tower-export",entity:r.stagedPowerEntity,value:r.stagedPowerW,fallbackMin:500,fallbackMax:8e3,fallbackStep:100,formatValue:T,disabled:r.interlocked,onPreview:o=>this._pendingDumpPower=o,onCommit:o=>this._commitDumpNumber("power",o,r.dump.export_power)})}
      ${this._renderNumberControl({label:"Stop SOC",icon:"mdi:battery-arrow-down",entity:r.stagedStopSocEntity,value:r.stagedStopSoc,fallbackMin:10,fallbackMax:90,fallbackStep:1,formatValue:L,disabled:r.interlocked,onPreview:o=>this._pendingDumpStopSoc=o,onCommit:o=>this._commitDumpNumber("stop_soc",o,r.dump.stop_soc)})}
      ${this._renderNumberControl({label:"Duration",icon:"mdi:timer-outline",entity:r.stagedDurationEntity,value:r.stagedDurationMin,fallbackMin:1,fallbackMax:240,fallbackStep:1,formatValue:I,disabled:r.interlocked,onPreview:o=>this._pendingDumpDuration=o,onCommit:o=>this._commitDumpNumber("duration",o,r.dump.duration)})}

      <div class="readiness-row">
        <ha-icon icon=${i?"mdi:shield-check":"mdi:shield-outline"}></ha-icon>
        <span>${i?"Armed - ready to start":"Safe - no inverter change made by staging values"}</span>
      </div>
      ${this._renderStatusLine(r.statusText,r.dump.status)}

      <div class="action-row">
        <button
          class="arm-toggle ${i?"is-armed":""}"
          ?disabled=${!s}
          @click=${()=>this._toggleArm(r.dump.write_enable,i)}
        >
          <ha-icon icon=${i?"mdi:shield-key":"mdi:shield-key-outline"}></ha-icon>
          ${i?"Disarm":"Arm Dump to Grid"}
        </button>
        <button
          class="start-button"
          ?disabled=${!a}
          @click=${()=>this._callService("button","press",{entity_id:r.dump.start})}
        >
          <ha-icon icon="mdi:play-circle-outline"></ha-icon>
          Start Now
        </button>
      </div>
      <p class="arm-caption">Arm is single-use - it's consumed the moment you press Start, or if the attempt is rejected.</p>
    `}_renderDumpLaterPanel(e){let r=_(this._entityState(e.armed)),i=Ae(r),a=this._entityState(e.start),s=M(a),o=this._entity(e.duration),l=this._entity(e.power),d=this._entity(e.stop_soc),p=this._entityState(e.last_result),u=this._pendingDumpScheduleDuration??m(o?.state),y=this._pendingDumpSchedulePower??m(l?.state),g=this._pendingDumpScheduleStopSoc??m(d?.state),w=ke(p)||!!p&&/^FAILED/i.test(p.trim()),$=Te(p),E=!!l&&!!o&&!!d&&r!==null,D=E&&!i&&s!==null&&s.getTime()>this._nowMs;return c`
      <p class="tile-description">Stage a future Dump to Grid session - Home Assistant arms and starts it automatically.</p>

      <div class="schedule-field">
        <label class="schedule-field-label"><ha-icon icon="mdi:calendar-clock"></ha-icon> Start</label>
        <input
          type="datetime-local"
          class="schedule-datetime-input"
          .value=${s?this._toDatetimeLocalValue(s):""}
          min=${this._toDatetimeLocalValue(new Date(this._nowMs))}
          ?disabled=${i}
          @change=${b=>this._handleScheduleStartChange(e.start,b.target.value)}
        />
      </div>

      ${this._renderNumberControl({label:"Scheduled Export Power",icon:"mdi:transmission-tower-export",entity:l,value:y,fallbackMin:500,fallbackMax:8e3,fallbackStep:100,formatValue:T,disabled:i||!l,onPreview:b=>this._pendingDumpSchedulePower=b,onCommit:b=>this._commitDumpScheduleNumber("power",b,e.power)})}
      ${this._renderNumberControl({label:"Scheduled Stop SOC",icon:"mdi:battery-arrow-down",entity:d,value:g,fallbackMin:10,fallbackMax:90,fallbackStep:1,formatValue:L,disabled:i||!d,onPreview:b=>this._pendingDumpScheduleStopSoc=b,onCommit:b=>this._commitDumpScheduleNumber("stop_soc",b,e.stop_soc)})}
      ${this._renderNumberControl({label:"Scheduled Duration",icon:"mdi:timer-outline",entity:o,value:u,fallbackMin:1,fallbackMax:240,fallbackStep:1,formatValue:I,disabled:i||!o,onPreview:b=>this._pendingDumpScheduleDuration=b,onCommit:b=>this._commitDumpScheduleNumber("duration",b,e.duration)})}

      ${E?h:c`<p class="firmware-note is-warning">
            Scheduled Dump to Grid helpers are unavailable - is ecco_dump_to_grid_schedule.yaml installed?
          </p>`}
      ${p?c`<p class="firmware-note ${w||$?"is-warning":""}">${p}</p>`:h}

      <div class="action-row">
        <button
          class="schedule-arm-toggle"
          ?disabled=${!D}
          @click=${()=>this._callServiceObj(Re(e.armed))}
        >
          <ha-icon icon="mdi:calendar-arrow-right"></ha-icon>
          Arm Schedule
        </button>
      </div>
      <p class="arm-caption">
        ${i?"Fields are locked while this schedule is armed - cancel it above to edit, then re-arm.":"Arm Schedule never touches the Dump to Grid write-enable switch. At the start time Home Assistant stages these values, arms and presses Start; the firmware re-checks Stop SOC, charging TOU slots and Free Power itself. Arming is refused if it overlaps an armed Free Power schedule or a charging TOU slot."}
      </p>
    `}_renderDumpScheduleBanner(e){let r=M(this._entityState(e.start)),i=m(this._entityState(e.duration)),a=m(this._entityState(e.power)),s=m(this._entityState(e.stop_soc)),o=r?Q(r.getTime(),this._nowMs):null;return c`
      <div class="schedule-banner">
        <ha-icon icon="mdi:calendar-clock"></ha-icon>
        <div class="schedule-banner-text">
          <div class="schedule-banner-line">
            ${r?Ne(r):"--"} • ${T(a)} • stop
            ${L(s)} • ${I(i)}
          </div>
          <div class="schedule-banner-countdown">${o?`Starts in ${o}`:"Starting..."}</div>
        </div>
        <button
          type="button"
          class="schedule-cancel-button"
          @click=${()=>this._callServiceObj(Pe(e.cancel))}
        >
          Cancel
        </button>
      </div>
    `}_commitDumpScheduleNumber(e,r,i){e==="power"?this._pendingDumpSchedulePower=r:e==="stop_soc"?this._pendingDumpScheduleStopSoc=r:this._pendingDumpScheduleDuration=r,this._callServiceObj(Ce(i,r))}_renderDumpLastEndReason(e){let r=this._entityState(e.last_end_reason);return!r||r==="unknown"||r==="unavailable"?h:c`<p class="firmware-note">Last lease ended: ${r}</p>`}_renderDumpActiveBody(e){let r=this._entityState(e.dump.ends_at),i=M(r),a=i?Q(i.getTime(),this._nowMs):null,s=m(this._entityState(e.dump.battery_soc)),o=at(m(this._entityState(e.dump.active_export_power)),e.statusText),l=st(m(this._entityState(e.dump.active_stop_soc)),e.statusText);return c`
      <div class="active-hero">
        <div class="active-hero-time">${a??"--:--"}</div>
        <div class="active-hero-label">time remaining</div>
      </div>
      <div class="active-secondary-line">
        Target ${T(o)} export • ends ${i?this._formatClock(i):r??"--"}
      </div>
      <div class="active-secondary-line">
        Battery: ${L(s)} • stops at ${L(l)}
      </div>

      <div class="readiness-row">
        <ha-icon icon=${e.snapshotValid?"mdi:content-save-check-outline":"mdi:content-save-alert-outline"}></ha-icon>
        <span>${e.snapshotValid?"Original settings snapshot saved":"No snapshot recorded - check status"}</span>
      </div>

      ${this._renderStatusLine(e.statusText,e.dump.status,{alwaysShow:!0})}
      ${this._renderDumpDiagnosticsDetails(e.dump)}
      ${this._renderEndDumpButton(e.dump.end_restore,"End & Restore Now",se("active"))}
    `}_renderDumpDeferredBody(e){return c`
      ${this._renderDeferredBody(e.statusText,e.dump.status)}
      ${e.snapshotValid===!0?this._renderEndDumpButton(e.dump.end_restore,"End & Restore Now",se("deferred")):h}
    `}_renderDumpAttentionBody(e){let i=!!e.dump.recovery_arm&&!!e.dump.recovery_force_restore&&!!e.dump.recovery_accept&&ot(e.statusText,e.snapshotValid);return c`
      <div class="attention-panel">
        <ha-icon icon="mdi:alert-circle-outline"></ha-icon>
        <div class="transition-text">
          <div class="transition-headline">Attention needed</div>
          ${this._renderTransitionDetail(e.statusText??"Dump to Grid requires operator attention.",e.dump.status)}
        </div>
      </div>
      <p class="transition-hint">
        ${i?"Automatic restore is stopped until you decide. Arm recovery, then Force Restore Original (writes only the saved original settings) or Accept Current State (writes nothing; refused while the inverter still shows Dump export).":"If the status above says the watchdog will retry, ECCO keeps retrying the restore automatically. Only OPERATOR DECISION REQUIRED stops automatic retries."}
      </p>
      ${i?this._renderDumpRecoveryPanel(e.dump):h}
      ${this._renderEndDumpButton(e.dump.end_restore,"End & Restore Now",se("recovery_attention"))}
    `}_renderDumpRecoveryPanel(e){let r=_(this._entityState(e.recovery_arm))===!0,i=this._entityState(e.recovery_state);return c`
      <div class="dump-recovery-panel">
        ${i&&i!=="unknown"&&i!=="unavailable"?c`<p class="firmware-note">${i}</p>`:h}
        <div class="action-row">
          <button
            class="arm-toggle ${r?"is-armed":""}"
            @click=${()=>this._toggleArm(e.recovery_arm,r)}
          >
            <ha-icon icon=${r?"mdi:shield-key":"mdi:shield-key-outline"}></ha-icon>
            ${r?"Disarm Recovery":"Arm Recovery"}
          </button>
        </div>
        <div class="action-row">
          <button
            class="start-button"
            ?disabled=${!r}
            @click=${()=>this._callService("button","press",{entity_id:e.recovery_force_restore})}
          >
            <ha-icon icon="mdi:backup-restore"></ha-icon>
            Force Restore Original
          </button>
          <button
            class="arm-toggle"
            ?disabled=${!r}
            @click=${()=>this._callService("button","press",{entity_id:e.recovery_accept})}
          >
            <ha-icon icon="mdi:check-circle-outline"></ha-icon>
            Accept Current State
          </button>
        </div>
      </div>
    `}_renderDumpDiagnosticsDetails(e){let r=[],i=(a,s)=>{let o=m(this._entityState(s));o!==null&&r.push({label:a,value:o.toString()})};return i("Starts",e.start_attempts),i("Started OK",e.start_successes),i("Restored OK",e.restore_successes),i("Failures",e.failures),r.length===0?h:c`
      <details class="diagnostics-details">
        <summary>Details</summary>
        <div class="diagnostics-row">
          ${r.map(a=>c`<span class="diagnostic-chip">${a.label}: ${a.value}</span>`)}
        </div>
      </details>
    `}_renderEndDumpButton(e,r,i){let a=this._confirmEndDump;return c`
      <button
        class="end-restore-button ${a?"confirming":""}"
        ?disabled=${!i}
        @click=${()=>this._handleEndDumpClick(e)}
      >
        <ha-icon icon="mdi:backup-restore"></ha-icon>
        ${a?"Tap again to End & Restore":r}
        ${a?c`<span class="confirm-progress" style="animation-duration:${oe}ms"></span>`:h}
      </button>
    `}};f.styles=ue`
    :host {
      /* Container query, not a viewport media query: this card is often
         docked in a narrow dashboard column on an otherwise-wide desktop
         browser (a sidebar/split-view layout), which a viewport-width
         media query would never see as "narrow" - the responsive rules
         below need to react to the CARD's own rendered width instead. */
      container-type: inline-size;

      --eaa-bg: var(--ecco-card-background, #141c2d);
      --eaa-surface: color-mix(in srgb, var(--eaa-bg) 82%, white 6%);
      --eaa-border: color-mix(in srgb, var(--eaa-bg) 70%, white 12%);
      --eaa-text: var(--primary-text-color, #eef2f7);
      --eaa-text-muted: var(--secondary-text-color, #9aa7b8);
      --eaa-accent: var(--primary-color, #4fd1ff);
      --eaa-ok: #38d996;
      --eaa-warning: #f4b942;
      --eaa-fault: #ff5c6c;
      --eaa-armed: #ffbd3d;
      --eaa-schedule: #c07cff;
      --eaa-glow: color-mix(in srgb, var(--eaa-accent) 45%, transparent);

      display: block;
    }

    ha-card {
      background: linear-gradient(160deg, var(--eaa-bg), color-mix(in srgb, var(--eaa-bg) 88%, black 8%));
      color: var(--eaa-text);
      border-radius: 20px;
      padding: 18px 18px 20px;
      overflow: hidden;
    }

    .card-title {
      margin: 0 0 14px;
      font-size: 18px;
      font-weight: 700;
      letter-spacing: 0.01em;
      color: var(--eaa-text);
    }

    .actions-grid {
      display: grid;
      /* 2026-09-26 sibling card polish: Free Power and Dump to Grid are
         equal first-class siblings, not a main feature plus a secondary
         column - both tracks get the same flexible 1fr share, each with the
         same 280px floor Dump to Grid alone used to have, so neither tile's
         controls (NOW/LATER selector, sliders, Arm/Start, banners) get
         squeezed. No max-width on the grid itself: a real wide dashboard
         card should use its full width - see .free-power-body/
         .dump-to-grid-body below for where the actual controls are capped
         instead, so sliders/buttons never stretch edge-to-edge even though
         each tile's own card border now does. */
      grid-template-columns: minmax(280px, 1fr) minmax(280px, 1fr);
      gap: 16px;
      /* 2026-09-26 equal-height polish: stretch (the grid default, made
         explicit here) rather than "start" - Dump to Grid's extra Stop SOC
         row and status/last-lease line make it naturally taller than Free
         Power, and the two should still finish on the same line rather than
         Free Power ending early with a visible gap beneath it. Only has an
         effect while both tiles share one grid row (the two-column desktop/
         tablet layout above) - the single-column stack below has exactly
         one tile per row, so this is a no-op there and each stacked card
         keeps its own natural content height (see .tile's comment below). */
      align-items: stretch;
    }

    @container (max-width: 620px) {
      .actions-grid {
        grid-template-columns: 1fr;
      }
    }

    /* Caps and centres the actual staging/control area within each tile -
       the tile's own border/background still spans the full flexible grid
       column (so the tile reads as deliberately sized, not glued to one
       side with empty space beside it), but the sliders, buttons and text
       inside stay a comfortable, non-absurd width. Centring (not
       left-alignment) is what keeps the extra space either side of the
       controls, once a tile is wider than this, from reading as a leftover
       void - has no effect at all once the tile itself is narrower than
       this, which is the common case on tablet/mobile and needs no
       separate breakpoint. Both tiles share the same cap so they read as
       the same product family.
       Also a flex column (2026-09-26 equal-height polish) so it can grow to
       fill whatever extra height .actions-grid's stretch gives the shorter
       tile - see .action-row's margin-top: auto below for where that spare
       height actually goes. */
    .free-power-body,
    .dump-to-grid-body {
      max-width: 680px;
      margin: 0 auto;
      flex: 1 1 auto;
      display: flex;
      flex-direction: column;
    }

    .tile {
      border-radius: 16px;
      background: var(--eaa-surface);
      border: 1px solid var(--eaa-border);
      padding: 14px 16px 16px;
      box-sizing: border-box;
      /* Flex column (2026-09-26 equal-height polish) purely so
         .free-power-body/.dump-to-grid-body above can flex:1 to fill
         whatever height .actions-grid's align-items: stretch gives this
         tile - visually identical to plain block stacking otherwise. */
      display: flex;
      flex-direction: column;
      transition:
        border-color 0.28s ease,
        background 0.28s ease,
        box-shadow 0.28s ease;
    }

    .tile-header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 8px;
      flex-wrap: wrap;
      margin-bottom: 6px;
    }

    .tile-heading {
      display: flex;
      align-items: center;
      gap: 8px;
      min-width: 0;
    }

    .tile-icon {
      --mdc-icon-size: 20px;
      color: var(--eaa-text-muted);
    }

    .tile-name {
      font-size: 15px;
      font-weight: 700;
      letter-spacing: 0.01em;
      /* Never truncated (e.g. "Dump to Grid" -> "Dump...") - if the header
         row gets tight, the pill wraps to its own line before the name
         would ever be squeezed (see .tile-header's flex-wrap above). */
      white-space: normal;
    }

    .tile-description {
      margin: 2px 0 12px;
      font-size: 12.5px;
      color: var(--eaa-text-muted);
      line-height: 1.4;
    }

    .state-pill {
      display: inline-flex;
      align-items: center;
      gap: 4px;
      font-size: 10.5px;
      font-weight: 800;
      letter-spacing: 0.04em;
      text-transform: uppercase;
      padding: 4px 9px;
      border-radius: 999px;
      background: color-mix(in srgb, var(--eaa-text-muted) 20%, transparent);
      color: var(--eaa-text-muted);
      white-space: nowrap;
    }
    .state-pill ha-icon {
      --mdc-icon-size: 12px;
    }
    .state-pill.state-ready {
      background: color-mix(in srgb, var(--eaa-accent) 20%, transparent);
      color: var(--eaa-accent);
    }
    .state-pill.state-armed {
      background: color-mix(in srgb, var(--eaa-armed) 24%, transparent);
      color: var(--eaa-armed);
    }
    .state-pill.state-scheduled {
      background: color-mix(in srgb, var(--eaa-schedule) 24%, transparent);
      color: var(--eaa-schedule);
    }
    .state-pill.state-active {
      background: color-mix(in srgb, var(--eaa-ok) 24%, transparent);
      color: var(--eaa-ok);
    }
    .state-pill.state-busy,
    .state-pill.state-deferred {
      background: color-mix(in srgb, var(--eaa-warning) 20%, transparent);
      color: var(--eaa-warning);
    }
    .state-pill.state-recovery_attention {
      background: color-mix(in srgb, var(--eaa-fault) 24%, transparent);
      color: var(--eaa-fault);
    }
    .state-pill.state-locked {
      background: color-mix(in srgb, var(--eaa-text-muted) 16%, transparent);
      color: var(--eaa-text-muted);
    }
    .state-pill.state-interlocked {
      background: color-mix(in srgb, var(--eaa-text-muted) 20%, transparent);
      color: var(--eaa-text-muted);
    }

    /* ---- Free Power tile state tints ---- */
    .free-power-tile.state-ready {
      border-color: var(--eaa-border);
    }
    .free-power-tile.state-armed {
      border-color: color-mix(in srgb, var(--eaa-armed) 55%, var(--eaa-border));
      background: color-mix(in srgb, var(--eaa-armed) 8%, var(--eaa-surface));
      box-shadow: 0 0 20px -8px color-mix(in srgb, var(--eaa-armed) 55%, transparent);
    }
    .free-power-tile.state-scheduled {
      border-color: color-mix(in srgb, var(--eaa-schedule) 45%, var(--eaa-border));
      background: color-mix(in srgb, var(--eaa-schedule) 7%, var(--eaa-surface));
      box-shadow: 0 0 18px -8px color-mix(in srgb, var(--eaa-schedule) 45%, transparent);
    }
    .free-power-tile.state-active {
      border-color: color-mix(in srgb, var(--eaa-ok) 60%, var(--eaa-border));
      background: color-mix(in srgb, var(--eaa-ok) 9%, var(--eaa-surface));
      box-shadow: 0 0 24px -6px color-mix(in srgb, var(--eaa-ok) 50%, transparent);
      animation: eaa-active-glow 3.4s ease-in-out infinite;
    }
    .free-power-tile.state-busy,
    .free-power-tile.state-deferred {
      border-color: color-mix(in srgb, var(--eaa-warning) 45%, var(--eaa-border));
      background: color-mix(in srgb, var(--eaa-warning) 6%, var(--eaa-surface));
    }
    .free-power-tile.state-recovery_attention {
      border-color: color-mix(in srgb, var(--eaa-fault) 55%, var(--eaa-border));
      background: color-mix(in srgb, var(--eaa-fault) 8%, var(--eaa-surface));
      box-shadow: 0 0 18px -6px color-mix(in srgb, var(--eaa-fault) 45%, transparent);
    }
    .free-power-tile.state-unavailable {
      opacity: 0.6;
    }
    /* Subdued, no glow/animation - a deliberately quieter tint than
       recovery_attention/busy (this feature is not at fault, its sibling
       currently owns the inverter, see interlock.ts). */
    .free-power-tile.state-interlocked {
      border-color: var(--eaa-border);
      background: color-mix(in srgb, var(--eaa-text-muted) 5%, var(--eaa-surface));
      opacity: 0.82;
    }

    /* ---- Dump to Grid tile state tints - same tokens as Free Power above ---- */
    .dump-to-grid-tile.state-ready {
      border-color: var(--eaa-border);
    }
    .dump-to-grid-tile.state-armed {
      border-color: color-mix(in srgb, var(--eaa-armed) 55%, var(--eaa-border));
      background: color-mix(in srgb, var(--eaa-armed) 8%, var(--eaa-surface));
      box-shadow: 0 0 20px -8px color-mix(in srgb, var(--eaa-armed) 55%, transparent);
    }
    .dump-to-grid-tile.state-active {
      border-color: color-mix(in srgb, var(--eaa-ok) 60%, var(--eaa-border));
      background: color-mix(in srgb, var(--eaa-ok) 9%, var(--eaa-surface));
      box-shadow: 0 0 24px -6px color-mix(in srgb, var(--eaa-ok) 50%, transparent);
      animation: eaa-active-glow 3.4s ease-in-out infinite;
    }
    .dump-to-grid-tile.state-scheduled {
      border-color: color-mix(in srgb, var(--eaa-schedule) 45%, var(--eaa-border));
      background: color-mix(in srgb, var(--eaa-schedule) 7%, var(--eaa-surface));
      box-shadow: 0 0 18px -8px color-mix(in srgb, var(--eaa-schedule) 45%, transparent);
    }
    .dump-recovery-panel {
      display: flex;
      flex-direction: column;
      gap: 8px;
      padding: 10px;
      border-radius: 12px;
      border: 1px dashed color-mix(in srgb, var(--eaa-fault) 45%, var(--eaa-border));
    }
    .dump-to-grid-tile.state-busy,
    .dump-to-grid-tile.state-deferred {
      border-color: color-mix(in srgb, var(--eaa-warning) 45%, var(--eaa-border));
      background: color-mix(in srgb, var(--eaa-warning) 6%, var(--eaa-surface));
    }
    .dump-to-grid-tile.state-recovery_attention {
      border-color: color-mix(in srgb, var(--eaa-fault) 55%, var(--eaa-border));
      background: color-mix(in srgb, var(--eaa-fault) 8%, var(--eaa-surface));
      box-shadow: 0 0 18px -6px color-mix(in srgb, var(--eaa-fault) 45%, transparent);
    }
    /* Subdued, no glow/animation - same rationale as
       .free-power-tile.state-interlocked above. */
    .dump-to-grid-tile.state-interlocked {
      border-color: var(--eaa-border);
      background: color-mix(in srgb, var(--eaa-text-muted) 5%, var(--eaa-surface));
      opacity: 0.82;
    }
    .dump-to-grid-tile.state-unavailable {
      opacity: 0.6;
    }

    @keyframes eaa-active-glow {
      0%,
      100% {
        box-shadow: 0 0 18px -8px color-mix(in srgb, var(--eaa-ok) 45%, transparent);
      }
      50% {
        box-shadow: 0 0 26px -4px color-mix(in srgb, var(--eaa-ok) 62%, transparent);
      }
    }
    @media (prefers-reduced-motion: reduce) {
      .free-power-tile.state-active,
      .dump-to-grid-tile.state-active {
        animation: none;
      }
      .spin {
        animation: none !important;
      }
      .confirm-progress {
        display: none;
      }
    }

    /* ---- NOW / LATER mode selector ---- */
    .mode-selector {
      display: flex;
      gap: 4px;
      padding: 3px;
      margin-bottom: 12px;
      border-radius: 10px;
      background: color-mix(in srgb, var(--eaa-bg) 60%, transparent);
      border: 1px solid var(--eaa-border);
    }
    .mode-tab {
      flex: 1 1 auto;
      border: none;
      background: transparent;
      color: var(--eaa-text-muted);
      padding: 7px 10px;
      font-size: 12px;
      font-weight: 700;
    }
    .mode-tab ha-icon {
      --mdc-icon-size: 15px;
    }
    .mode-tab.is-active {
      background: var(--eaa-surface);
      color: var(--eaa-text);
      box-shadow: 0 1px 4px rgba(0, 0, 0, 0.25);
    }

    /* ---- Schedule banner (shown in both Now and Later views while armed) ---- */
    .schedule-banner {
      display: flex;
      align-items: center;
      gap: 10px;
      padding: 9px 12px;
      border-radius: 12px;
      background: color-mix(in srgb, var(--eaa-schedule) 14%, var(--eaa-surface));
      border: 1px solid color-mix(in srgb, var(--eaa-schedule) 45%, var(--eaa-border));
      margin-bottom: 12px;
    }
    .schedule-banner ha-icon {
      --mdc-icon-size: 19px;
      color: var(--eaa-schedule);
      flex-shrink: 0;
    }
    .schedule-banner-text {
      min-width: 0;
      flex: 1 1 auto;
    }
    .schedule-banner-line {
      font-size: 12px;
      font-weight: 700;
      color: var(--eaa-text);
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .schedule-banner-countdown {
      font-size: 11px;
      color: var(--eaa-schedule);
      font-variant-numeric: tabular-nums;
    }
    .schedule-cancel-button {
      flex: 0 0 auto;
      padding: 7px 12px;
      font-size: 11px;
      min-height: 36px;
      border-color: color-mix(in srgb, var(--eaa-fault) 45%, var(--eaa-border));
      color: var(--eaa-fault);
      background: transparent;
    }

    /* ---- Interlock banner - deliberately muted/neutral, not warning-
       coloured like the schedule banner above: this feature isn't at
       fault, its sibling currently owns the inverter (see interlock.ts). */
    .interlock-banner {
      display: flex;
      align-items: center;
      gap: 10px;
      padding: 9px 12px;
      border-radius: 12px;
      background: color-mix(in srgb, var(--eaa-text-muted) 12%, var(--eaa-surface));
      border: 1px dashed color-mix(in srgb, var(--eaa-text-muted) 40%, var(--eaa-border));
      margin-bottom: 12px;
    }
    .interlock-banner ha-icon {
      --mdc-icon-size: 19px;
      color: var(--eaa-text-muted);
      flex-shrink: 0;
    }
    .interlock-banner-text {
      min-width: 0;
      flex: 1 1 auto;
      font-size: 12px;
      font-weight: 600;
      color: var(--eaa-text-muted);
      line-height: 1.4;
    }

    /* ---- Schedule (LATER) fields ---- */
    .schedule-field {
      margin-bottom: 12px;
    }
    .schedule-field-label {
      display: flex;
      align-items: center;
      gap: 6px;
      font-size: 11.5px;
      font-weight: 700;
      color: var(--eaa-text-muted);
      margin-bottom: 5px;
    }
    .schedule-field-label ha-icon {
      --mdc-icon-size: 14px;
    }
    .schedule-datetime-input {
      width: 100%;
      box-sizing: border-box;
      font: inherit;
      font-size: 13px;
      color: var(--eaa-text);
      background: color-mix(in srgb, var(--eaa-bg) 55%, transparent);
      border: 1px solid var(--eaa-border);
      border-radius: 8px;
      padding: 9px 10px;
      min-height: 40px;
      color-scheme: dark;
    }
    .schedule-datetime-input:disabled {
      opacity: 0.5;
    }
    .schedule-arm-toggle {
      border-color: color-mix(in srgb, var(--eaa-schedule) 55%, var(--eaa-border));
      color: var(--eaa-schedule);
      background: color-mix(in srgb, var(--eaa-schedule) 10%, var(--eaa-surface));
    }
    .schedule-arm-toggle:not(:disabled):hover {
      background: color-mix(in srgb, var(--eaa-schedule) 18%, var(--eaa-surface));
    }

    .arm-caption {
      font-size: 10.5px;
      color: var(--eaa-text-muted);
      line-height: 1.4;
      margin: 8px 0 0;
      opacity: 0.85;
    }

    /* ---- Number controls ---- */
    .number-control {
      margin-bottom: 12px;
    }
    .number-control-label {
      display: flex;
      align-items: center;
      gap: 6px;
      font-size: 11.5px;
      font-weight: 700;
      color: var(--eaa-text-muted);
      margin-bottom: 5px;
    }
    .number-control-label ha-icon {
      --mdc-icon-size: 14px;
    }
    .number-control-value {
      margin-left: auto;
      font-size: 13px;
      font-weight: 700;
      color: var(--eaa-text);
      font-variant-numeric: tabular-nums;
    }
    .number-control-slider {
      width: 100%;
      appearance: none;
      -webkit-appearance: none;
      height: 6px;
      border-radius: 999px;
      background: linear-gradient(
        to right,
        var(--eaa-accent) 0%,
        var(--eaa-accent) var(--eaa-slider-fill, 0%),
        color-mix(in srgb, var(--eaa-text-muted) 28%, transparent) var(--eaa-slider-fill, 0%)
      );
      outline: none;
      cursor: pointer;
    }
    .number-control-slider::-webkit-slider-thumb {
      appearance: none;
      -webkit-appearance: none;
      width: 20px;
      height: 20px;
      border-radius: 50%;
      background: var(--eaa-accent);
      border: 2px solid var(--eaa-bg);
      box-shadow: 0 0 0 1px color-mix(in srgb, var(--eaa-accent) 60%, transparent);
    }
    .number-control-slider::-moz-range-thumb {
      width: 18px;
      height: 18px;
      border-radius: 50%;
      background: var(--eaa-accent);
      border: 2px solid var(--eaa-bg);
    }
    .number-control-slider:disabled {
      opacity: 0.4;
      cursor: not-allowed;
    }
    .number-control-slider:focus-visible {
      box-shadow: 0 0 0 3px color-mix(in srgb, var(--eaa-accent) 40%, transparent);
    }

    .readiness-row {
      display: flex;
      align-items: center;
      gap: 6px;
      font-size: 11.5px;
      color: var(--eaa-text-muted);
      margin: 6px 0 10px;
    }
    .readiness-row ha-icon {
      --mdc-icon-size: 15px;
    }

    .firmware-note {
      /* Deliberately quiet - a plain status line, not a boxed/input-like
         control. The literal firmware text stays fully readable and
         tappable; it just no longer competes visually with the actual
         controls above it. .is-warning (below) is the one exception - a
         schedule REJECTED/BLOCKED outcome earns the extra weight. */
      font-size: 10.5px;
      color: var(--eaa-text-muted);
      opacity: 0.9;
      margin: 0 0 10px;
      line-height: 1.4;
      word-break: break-word;
    }
    .firmware-note.is-warning {
      background: color-mix(in srgb, var(--eaa-warning) 16%, transparent);
      color: color-mix(in srgb, var(--eaa-warning) 70%, var(--eaa-text));
      border-radius: 8px;
      padding: 6px 9px;
      opacity: 1;
    }
    .firmware-note.clickable,
    .transition-detail.clickable {
      cursor: pointer;
    }
    .firmware-note.clickable:hover {
      color: var(--eaa-text);
      opacity: 1;
    }
    .firmware-note:focus-visible,
    .transition-detail:focus-visible {
      outline: 2px solid var(--eaa-accent);
      outline-offset: 1px;
    }

    .action-row {
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
      /* 2026-09-26 equal-height polish: an auto top margin inside the now-
         flex-column .free-power-body/.dump-to-grid-body absorbs whatever
         spare height align-items: stretch gave the shorter tile, so the
         Arm/Start row (and the footer text right after it) settles at the
         bottom of the card instead of leaving a gap beneath it - every
         control above keeps its normal spacing untouched. Resolves to 0
         (today's exact layout) whenever there's no spare height to absorb -
         the taller tile, and every tile once stacked single-column. */
      margin-top: auto;
    }

    button {
      font: inherit;
      border: 1px solid var(--eaa-border);
      background: var(--eaa-surface);
      color: var(--eaa-text);
      border-radius: 10px;
      padding: 10px 14px;
      min-height: 44px;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      gap: 6px;
      font-size: 12.5px;
      font-weight: 700;
      cursor: pointer;
      transition:
        background 0.18s ease,
        border-color 0.18s ease,
        opacity 0.18s ease,
        transform 0.1s ease;
      flex: 1 1 auto;
    }
    button ha-icon {
      --mdc-icon-size: 16px;
    }
    button:disabled {
      opacity: 0.38;
      cursor: not-allowed;
    }
    button:not(:disabled):active {
      transform: scale(0.98);
    }
    button:focus-visible {
      outline: 2px solid var(--eaa-accent);
      outline-offset: 1px;
    }

    .arm-toggle {
      border-color: color-mix(in srgb, var(--eaa-armed) 45%, var(--eaa-border));
      color: var(--eaa-armed);
    }
    .arm-toggle.is-armed {
      background: color-mix(in srgb, var(--eaa-armed) 18%, var(--eaa-surface));
      border-color: color-mix(in srgb, var(--eaa-armed) 70%, var(--eaa-border));
    }

    .start-button {
      border-color: color-mix(in srgb, var(--eaa-ok) 55%, var(--eaa-border));
      color: var(--eaa-ok);
      background: color-mix(in srgb, var(--eaa-ok) 10%, var(--eaa-surface));
    }
    .start-button:not(:disabled):hover {
      background: color-mix(in srgb, var(--eaa-ok) 18%, var(--eaa-surface));
    }

    .end-restore-button {
      position: relative;
      overflow: hidden;
      width: 100%;
      border-color: color-mix(in srgb, var(--eaa-fault) 45%, var(--eaa-border));
      color: var(--eaa-fault);
      margin-top: 4px;
    }
    .end-restore-button.secondary {
      border-color: var(--eaa-border);
      color: var(--eaa-text-muted);
      background: transparent;
      font-weight: 600;
    }
    .end-restore-button.confirming {
      background: color-mix(in srgb, var(--eaa-fault) 22%, var(--eaa-surface));
      border-color: var(--eaa-fault);
    }
    .confirm-progress {
      position: absolute;
      left: 0;
      bottom: 0;
      height: 3px;
      background: currentColor;
      animation-name: eaa-confirm-shrink;
      animation-timing-function: linear;
      animation-fill-mode: forwards;
    }
    @keyframes eaa-confirm-shrink {
      from {
        width: 100%;
      }
      to {
        width: 0%;
      }
    }

    /* ---- Active hero ---- */
    .active-hero {
      text-align: center;
      padding: 6px 0 2px;
    }
    .active-hero-time {
      font-size: 34px;
      font-weight: 800;
      color: var(--eaa-ok);
      font-variant-numeric: tabular-nums;
      line-height: 1.1;
    }
    .active-hero-label {
      font-size: 10.5px;
      font-weight: 700;
      letter-spacing: 0.06em;
      text-transform: uppercase;
      color: var(--eaa-text-muted);
      margin-top: 2px;
    }
    .active-secondary-line {
      text-align: center;
      font-size: 12.5px;
      color: var(--eaa-text-muted);
      margin: 8px 0 12px;
    }

    .diagnostics-details {
      margin: 0 0 10px;
    }
    .diagnostics-details summary {
      cursor: pointer;
      font-size: 11px;
      font-weight: 700;
      color: var(--eaa-text-muted);
      list-style: none;
      user-select: none;
    }
    .diagnostics-details summary::-webkit-details-marker {
      display: none;
    }
    .diagnostics-details summary::before {
      content: "▸ ";
    }
    .diagnostics-details[open] summary::before {
      content: "▾ ";
    }
    .diagnostics-row {
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
      margin-top: 6px;
    }
    .diagnostic-chip {
      font-size: 9.5px;
      color: var(--eaa-text-muted);
      background: color-mix(in srgb, var(--eaa-text-muted) 12%, transparent);
      border-radius: 999px;
      padding: 3px 8px;
    }

    /* ---- Transition / attention panels ---- */
    .transition-panel,
    .attention-panel {
      display: flex;
      align-items: flex-start;
      gap: 10px;
      padding: 10px 12px;
      border-radius: 12px;
      background: color-mix(in srgb, var(--eaa-warning) 10%, transparent);
      margin-bottom: 8px;
    }
    .attention-panel {
      background: color-mix(in srgb, var(--eaa-fault) 12%, transparent);
    }
    .transition-panel ha-icon,
    .attention-panel ha-icon {
      --mdc-icon-size: 22px;
      color: var(--eaa-warning);
      flex-shrink: 0;
      margin-top: 1px;
    }
    .attention-panel ha-icon {
      color: var(--eaa-fault);
    }
    .transition-panel.deferred ha-icon {
      color: var(--eaa-warning);
    }
    .transition-text {
      min-width: 0;
    }
    .transition-headline {
      font-size: 13px;
      font-weight: 700;
      margin-bottom: 2px;
    }
    .transition-detail {
      font-size: 11.5px;
      color: var(--eaa-text-muted);
      line-height: 1.4;
      word-break: break-word;
    }
    .transition-hint {
      font-size: 11px;
      color: var(--eaa-text-muted);
      margin: 0 0 10px;
      line-height: 1.4;
    }

    .spin {
      animation: eaa-spin 1.6s linear infinite;
    }
    @keyframes eaa-spin {
      from {
        transform: rotate(0deg);
      }
      to {
        transform: rotate(360deg);
      }
    }

    /* ---- Dump to Grid (locked) tile ---- */
    .dump-to-grid-tile.locked {
      background: color-mix(in srgb, var(--eaa-bg) 92%, transparent);
      position: relative;
    }
    /* Scoped to .locked only - the dimmed icon is a "not available yet" cue
       for the static preview shell and must NOT bleed into the real
       interactive tile once dump_to_grid: is configured (V1). */
    .dump-to-grid-tile.locked .tile-icon {
      opacity: 0.6;
    }
    .locked-preview {
      display: flex;
      flex-direction: column;
      gap: 6px;
      margin-bottom: 10px;
      opacity: 0.55;
      pointer-events: none;
      user-select: none;
    }
    .locked-row {
      display: flex;
      justify-content: space-between;
      font-size: 12px;
      color: var(--eaa-text-muted);
      background: color-mix(in srgb, var(--eaa-text-muted) 8%, transparent);
      border-radius: 8px;
      padding: 7px 10px;
    }
    .tile-footnote {
      font-size: 10.5px;
      color: var(--eaa-text-muted);
      line-height: 1.4;
      margin: 0;
      opacity: 0.85;
    }

    /* Mobile: Dump to Grid collapses to a compact locked row - header +
       description + footnote only, dropping the dimmed preview rows. */
    /* Covers both the cramped-second-column case just above the 620px
       stacking point, and a typical stacked phone width below it - in
       both cases Dump to Grid has too little room to justify the three
       dimmed preview rows. */
    @container (max-width: 700px) {
      .dump-to-grid-tile .locked-preview {
        display: none;
      }
      .dump-to-grid-tile {
        padding: 12px 14px 14px;
      }
    }
  `,v([re({attribute:!1})],f.prototype,"hass",2),v([S()],f.prototype,"_config",2),v([S()],f.prototype,"_pendingPower",2),v([S()],f.prototype,"_pendingDuration",2),v([S()],f.prototype,"_pendingSchedulePower",2),v([S()],f.prototype,"_pendingScheduleDuration",2),v([S()],f.prototype,"_confirmEndRestore",2),v([S()],f.prototype,"_pendingDumpPower",2),v([S()],f.prototype,"_pendingDumpStopSoc",2),v([S()],f.prototype,"_pendingDumpDuration",2),v([S()],f.prototype,"_confirmEndDump",2),v([S()],f.prototype,"_dumpMode",2),v([S()],f.prototype,"_pendingDumpSchedulePower",2),v([S()],f.prototype,"_pendingDumpScheduleStopSoc",2),v([S()],f.prototype,"_pendingDumpScheduleDuration",2),v([S()],f.prototype,"_nowMs",2),v([S()],f.prototype,"_mode",2),f=v([Je("ecco-energy-actions-card")],f);window.customCards=[...window.customCards??[],{type:"ecco-energy-actions-card",name:"ECCO Energy Actions Card",description:"Free Power as a real product feature (staged controls, two-step arm/start safety, live firmware states, Now/Later scheduling) plus a locked Dump to Grid preview.",preview:!1}];export{f as EccoEnergyActionsCard};
/*! Bundled license information:

@lit/reactive-element/css-tag.js:
  (**
   * @license
   * Copyright 2019 Google LLC
   * SPDX-License-Identifier: BSD-3-Clause
   *)

@lit/reactive-element/reactive-element.js:
lit-html/lit-html.js:
lit-element/lit-element.js:
@lit/reactive-element/decorators/custom-element.js:
@lit/reactive-element/decorators/property.js:
@lit/reactive-element/decorators/state.js:
@lit/reactive-element/decorators/event-options.js:
@lit/reactive-element/decorators/base.js:
@lit/reactive-element/decorators/query.js:
@lit/reactive-element/decorators/query-all.js:
@lit/reactive-element/decorators/query-async.js:
@lit/reactive-element/decorators/query-assigned-nodes.js:
  (**
   * @license
   * Copyright 2017 Google LLC
   * SPDX-License-Identifier: BSD-3-Clause
   *)

lit-html/is-server.js:
  (**
   * @license
   * Copyright 2022 Google LLC
   * SPDX-License-Identifier: BSD-3-Clause
   *)

@lit/reactive-element/decorators/query-assigned-elements.js:
  (**
   * @license
   * Copyright 2021 Google LLC
   * SPDX-License-Identifier: BSD-3-Clause
   *)
*/
""")
BUNDLE_0_NEW = _blk(r"""
var St=Object.defineProperty;var kt=Object.getOwnPropertyDescriptor;var v=(a,r,e,t)=>{for(var i=t>1?void 0:t?kt(r,e):r,n=a.length-1,s;n>=0;n--)(s=a[n])&&(i=(t?s(r,e,i):s(i))||i);return t&&i&&St(r,e,i),i};var Z=globalThis,X=Z.ShadowRoot&&(Z.ShadyCSS===void 0||Z.ShadyCSS.nativeShadow)&&"adoptedStyleSheets"in Document.prototype&&"replace"in CSSStyleSheet.prototype,ue=Symbol(),Le=new WeakMap,B=class{constructor(r,e,t){if(this._$cssResult$=!0,t!==ue)throw Error("CSSResult is not constructable. Use `unsafeCSS` or `css` instead.");this.cssText=r,this.t=e}get styleSheet(){let r=this.o,e=this.t;if(X&&r===void 0){let t=e!==void 0&&e.length===1;t&&(r=Le.get(e)),r===void 0&&((this.o=r=new CSSStyleSheet).replaceSync(this.cssText),t&&Le.set(e,r))}return r}toString(){return this.cssText}},Ue=a=>new B(typeof a=="string"?a:a+"",void 0,ue),pe=(a,...r)=>{let e=a.length===1?a[0]:r.reduce((t,i,n)=>t+(s=>{if(s._$cssResult$===!0)return s.cssText;if(typeof s=="number")return s;throw Error("Value passed to 'css' function must be a 'css' function result: "+s+". Use 'unsafeCSS' to pass non-literal values, but take care to ensure page security.")})(i)+a[n+1],a[0]);return new B(e,a,ue)},Be=(a,r)=>{if(X)a.adoptedStyleSheets=r.map(e=>e instanceof CSSStyleSheet?e:e.styleSheet);else for(let e of r){let t=document.createElement("style"),i=Z.litNonce;i!==void 0&&t.setAttribute("nonce",i),t.textContent=e.cssText,a.appendChild(t)}},he=X?a=>a:a=>a instanceof CSSStyleSheet?(r=>{let e="";for(let t of r.cssRules)e+=t.cssText;return Ue(e)})(a):a;var{is:$t,defineProperty:Dt,getOwnPropertyDescriptor:Et,getOwnPropertyNames:Tt,getOwnPropertySymbols:At,getPrototypeOf:Rt}=Object,ee=globalThis,He=ee.trustedTypes,Pt=He?He.emptyScript:"",Ct=ee.reactiveElementPolyfillSupport,H=(a,r)=>a,z={toAttribute(a,r){switch(r){case Boolean:a=a?Pt:null;break;case Object:case Array:a=a==null?a:JSON.stringify(a)}return a},fromAttribute(a,r){let e=a;switch(r){case Boolean:e=a!==null;break;case Number:e=a===null?null:Number(a);break;case Object:case Array:try{e=JSON.parse(a)}catch{e=null}}return e}},te=(a,r)=>!$t(a,r),ze={attribute:!0,type:String,converter:z,reflect:!1,useDefault:!1,hasChanged:te};Symbol.metadata??=Symbol("metadata"),ee.litPropertyMetadata??=new WeakMap;var E=class extends HTMLElement{static addInitializer(r){this._$Ei(),(this.l??=[]).push(r)}static get observedAttributes(){return this.finalize(),this._$Eh&&[...this._$Eh.keys()]}static createProperty(r,e=ze){if(e.state&&(e.attribute=!1),this._$Ei(),this.prototype.hasOwnProperty(r)&&((e=Object.create(e)).wrapped=!0),this.elementProperties.set(r,e),!e.noAccessor){let t=Symbol(),i=this.getPropertyDescriptor(r,t,e);i!==void 0&&Dt(this.prototype,r,i)}}static getPropertyDescriptor(r,e,t){let{get:i,set:n}=Et(this.prototype,r)??{get(){return this[e]},set(s){this[e]=s}};return{get:i,set(s){let o=i?.call(this);n?.call(this,s),this.requestUpdate(r,o,t)},configurable:!0,enumerable:!0}}static getPropertyOptions(r){return this.elementProperties.get(r)??ze}static _$Ei(){if(this.hasOwnProperty(H("elementProperties")))return;let r=Rt(this);r.finalize(),r.l!==void 0&&(this.l=[...r.l]),this.elementProperties=new Map(r.elementProperties)}static finalize(){if(this.hasOwnProperty(H("finalized")))return;if(this.finalized=!0,this._$Ei(),this.hasOwnProperty(H("properties"))){let e=this.properties,t=[...Tt(e),...At(e)];for(let i of t)this.createProperty(i,e[i])}let r=this[Symbol.metadata];if(r!==null){let e=litPropertyMetadata.get(r);if(e!==void 0)for(let[t,i]of e)this.elementProperties.set(t,i)}this._$Eh=new Map;for(let[e,t]of this.elementProperties){let i=this._$Eu(e,t);i!==void 0&&this._$Eh.set(i,e)}this.elementStyles=this.finalizeStyles(this.styles)}static finalizeStyles(r){let e=[];if(Array.isArray(r)){let t=new Set(r.flat(1/0).reverse());for(let i of t)e.unshift(he(i))}else r!==void 0&&e.push(he(r));return e}static _$Eu(r,e){let t=e.attribute;return t===!1?void 0:typeof t=="string"?t:typeof r=="string"?r.toLowerCase():void 0}constructor(){super(),this._$Ep=void 0,this.isUpdatePending=!1,this.hasUpdated=!1,this._$Em=null,this._$Ev()}_$Ev(){this._$ES=new Promise(r=>this.enableUpdating=r),this._$AL=new Map,this._$E_(),this.requestUpdate(),this.constructor.l?.forEach(r=>r(this))}addController(r){(this._$EO??=new Set).add(r),this.renderRoot!==void 0&&this.isConnected&&r.hostConnected?.()}removeController(r){this._$EO?.delete(r)}_$E_(){let r=new Map,e=this.constructor.elementProperties;for(let t of e.keys())this.hasOwnProperty(t)&&(r.set(t,this[t]),delete this[t]);r.size>0&&(this._$Ep=r)}createRenderRoot(){let r=this.shadowRoot??this.attachShadow(this.constructor.shadowRootOptions);return Be(r,this.constructor.elementStyles),r}connectedCallback(){this.renderRoot??=this.createRenderRoot(),this.enableUpdating(!0),this._$EO?.forEach(r=>r.hostConnected?.())}enableUpdating(r){}disconnectedCallback(){this._$EO?.forEach(r=>r.hostDisconnected?.())}attributeChangedCallback(r,e,t){this._$AK(r,t)}_$ET(r,e){let t=this.constructor.elementProperties.get(r),i=this.constructor._$Eu(r,t);if(i!==void 0&&t.reflect===!0){let n=(t.converter?.toAttribute!==void 0?t.converter:z).toAttribute(e,t.type);this._$Em=r,n==null?this.removeAttribute(i):this.setAttribute(i,n),this._$Em=null}}_$AK(r,e){let t=this.constructor,i=t._$Eh.get(r);if(i!==void 0&&this._$Em!==i){let n=t.getPropertyOptions(i),s=typeof n.converter=="function"?{fromAttribute:n.converter}:n.converter?.fromAttribute!==void 0?n.converter:z;this._$Em=i;let o=s.fromAttribute(e,n.type);this[i]=o??this._$Ej?.get(i)??o,this._$Em=null}}requestUpdate(r,e,t,i=!1,n){if(r!==void 0){let s=this.constructor;if(i===!1&&(n=this[r]),t??=s.getPropertyOptions(r),!((t.hasChanged??te)(n,e)||t.useDefault&&t.reflect&&n===this._$Ej?.get(r)&&!this.hasAttribute(s._$Eu(r,t))))return;this.C(r,e,t)}this.isUpdatePending===!1&&(this._$ES=this._$EP())}C(r,e,{useDefault:t,reflect:i,wrapped:n},s){t&&!(this._$Ej??=new Map).has(r)&&(this._$Ej.set(r,s??e??this[r]),n!==!0||s!==void 0)||(this._$AL.has(r)||(this.hasUpdated||t||(e=void 0),this._$AL.set(r,e)),i===!0&&this._$Em!==r&&(this._$Eq??=new Set).add(r))}async _$EP(){this.isUpdatePending=!0;try{await this._$ES}catch(e){Promise.reject(e)}let r=this.scheduleUpdate();return r!=null&&await r,!this.isUpdatePending}scheduleUpdate(){return this.performUpdate()}performUpdate(){if(!this.isUpdatePending)return;if(!this.hasUpdated){if(this.renderRoot??=this.createRenderRoot(),this._$Ep){for(let[i,n]of this._$Ep)this[i]=n;this._$Ep=void 0}let t=this.constructor.elementProperties;if(t.size>0)for(let[i,n]of t){let{wrapped:s}=n,o=this[i];s!==!0||this._$AL.has(i)||o===void 0||this.C(i,void 0,n,o)}}let r=!1,e=this._$AL;try{r=this.shouldUpdate(e),r?(this.willUpdate(e),this._$EO?.forEach(t=>t.hostUpdate?.()),this.update(e)):this._$EM()}catch(t){throw r=!1,this._$EM(),t}r&&this._$AE(e)}willUpdate(r){}_$AE(r){this._$EO?.forEach(e=>e.hostUpdated?.()),this.hasUpdated||(this.hasUpdated=!0,this.firstUpdated(r)),this.updated(r)}_$EM(){this._$AL=new Map,this.isUpdatePending=!1}get updateComplete(){return this.getUpdateComplete()}getUpdateComplete(){return this._$ES}shouldUpdate(r){return!0}update(r){this._$Eq&&=this._$Eq.forEach(e=>this._$ET(e,this[e])),this._$EM()}updated(r){}firstUpdated(r){}};E.elementStyles=[],E.shadowRootOptions={mode:"open"},E[H("elementProperties")]=new Map,E[H("finalized")]=new Map,Ct?.({ReactiveElement:E}),(ee.reactiveElementVersions??=[]).push("2.1.2");var ye=globalThis,We=a=>a,re=ye.trustedTypes,Ge=re?re.createPolicy("lit-html",{createHTML:a=>a}):void 0,Je="$lit$",A=`lit$${Math.random().toFixed(9).slice(2)}$`,Ze="?"+A,Nt=`<${Ze}>`,N=document,G=()=>N.createComment(""),j=a=>a===null||typeof a!="object"&&typeof a!="function",we=Array.isArray,Ot=a=>we(a)||typeof a?.[Symbol.iterator]=="function",me=`[ 	
\f\r]`,W=/<(?:(!--|\/[^a-zA-Z])|(\/?[a-zA-Z][^>\s]*)|(\/?$))/g,je=/-->/g,qe=/>/g,P=RegExp(`>|${me}(?:([^\\s"'>=/]+)(${me}*=${me}*(?:[^ 	
\f\r"'\`<>=]|("|')|))|$)`,"g"),Ye=/'/g,Ke=/"/g,Xe=/^(?:script|style|textarea|title)$/i,xe=a=>(r,...e)=>({_$litType$:a,strings:r,values:e}),u=xe(1),_r=xe(2),gr=xe(3),O=Symbol.for("lit-noChange"),h=Symbol.for("lit-nothing"),Qe=new WeakMap,C=N.createTreeWalker(N,129);function et(a,r){if(!we(a)||!a.hasOwnProperty("raw"))throw Error("invalid template strings array");return Ge!==void 0?Ge.createHTML(r):r}var Mt=(a,r)=>{let e=a.length-1,t=[],i,n=r===2?"<svg>":r===3?"<math>":"",s=W;for(let o=0;o<e;o++){let l=a[o],d,c,p=-1,y=0;for(;y<l.length&&(s.lastIndex=y,c=s.exec(l),c!==null);)y=s.lastIndex,s===W?c[1]==="!--"?s=je:c[1]!==void 0?s=qe:c[2]!==void 0?(Xe.test(c[2])&&(i=RegExp("</"+c[2],"g")),s=P):c[3]!==void 0&&(s=P):s===P?c[0]===">"?(s=i??W,p=-1):c[1]===void 0?p=-2:(p=s.lastIndex-c[2].length,d=c[1],s=c[3]===void 0?P:c[3]==='"'?Ke:Ye):s===Ke||s===Ye?s=P:s===je||s===qe?s=W:(s=P,i=void 0);let _=s===P&&a[o+1].startsWith("/>")?" ":"";n+=s===W?l+Nt:p>=0?(t.push(d),l.slice(0,p)+Je+l.slice(p)+A+_):l+A+(p===-2?o:_)}return[et(a,n+(a[e]||"<?>")+(r===2?"</svg>":r===3?"</math>":"")),t]},q=class a{constructor({strings:r,_$litType$:e},t){let i;this.parts=[];let n=0,s=0,o=r.length-1,l=this.parts,[d,c]=Mt(r,e);if(this.el=a.createElement(d,t),C.currentNode=this.el.content,e===2||e===3){let p=this.el.content.firstChild;p.replaceWith(...p.childNodes)}for(;(i=C.nextNode())!==null&&l.length<o;){if(i.nodeType===1){if(i.hasAttributes())for(let p of i.getAttributeNames())if(p.endsWith(Je)){let y=c[s++],_=i.getAttribute(p).split(A),w=/([.?@])?(.*)/.exec(y);l.push({type:1,index:n,name:w[2],strings:_,ctor:w[1]==="."?_e:w[1]==="?"?ge:w[1]==="@"?be:V}),i.removeAttribute(p)}else p.startsWith(A)&&(l.push({type:6,index:n}),i.removeAttribute(p));if(Xe.test(i.tagName)){let p=i.textContent.split(A),y=p.length-1;if(y>0){i.textContent=re?re.emptyScript:"";for(let _=0;_<y;_++)i.append(p[_],G()),C.nextNode(),l.push({type:2,index:++n});i.append(p[y],G())}}}else if(i.nodeType===8)if(i.data===Ze)l.push({type:2,index:n});else{let p=-1;for(;(p=i.data.indexOf(A,p+1))!==-1;)l.push({type:7,index:n}),p+=A.length-1}n++}}static createElement(r,e){let t=N.createElement("template");return t.innerHTML=r,t}};function I(a,r,e=a,t){if(r===O)return r;let i=t!==void 0?e._$Co?.[t]:e._$Cl,n=j(r)?void 0:r._$litDirective$;return i?.constructor!==n&&(i?._$AO?.(!1),n===void 0?i=void 0:(i=new n(a),i._$AT(a,e,t)),t!==void 0?(e._$Co??=[])[t]=i:e._$Cl=i),i!==void 0&&(r=I(a,i._$AS(a,r.values),i,t)),r}var fe=class{constructor(r,e){this._$AV=[],this._$AN=void 0,this._$AD=r,this._$AM=e}get parentNode(){return this._$AM.parentNode}get _$AU(){return this._$AM._$AU}u(r){let{el:{content:e},parts:t}=this._$AD,i=(r?.creationScope??N).importNode(e,!0);C.currentNode=i;let n=C.nextNode(),s=0,o=0,l=t[0];for(;l!==void 0;){if(s===l.index){let d;l.type===2?d=new Y(n,n.nextSibling,this,r):l.type===1?d=new l.ctor(n,l.name,l.strings,this,r):l.type===6&&(d=new ve(n,this,r)),this._$AV.push(d),l=t[++o]}s!==l?.index&&(n=C.nextNode(),s++)}return C.currentNode=N,i}p(r){let e=0;for(let t of this._$AV)t!==void 0&&(t.strings!==void 0?(t._$AI(r,t,e),e+=t.strings.length-2):t._$AI(r[e])),e++}},Y=class a{get _$AU(){return this._$AM?._$AU??this._$Cv}constructor(r,e,t,i){this.type=2,this._$AH=h,this._$AN=void 0,this._$AA=r,this._$AB=e,this._$AM=t,this.options=i,this._$Cv=i?.isConnected??!0}get parentNode(){let r=this._$AA.parentNode,e=this._$AM;return e!==void 0&&r?.nodeType===11&&(r=e.parentNode),r}get startNode(){return this._$AA}get endNode(){return this._$AB}_$AI(r,e=this){r=I(this,r,e),j(r)?r===h||r==null||r===""?(this._$AH!==h&&this._$AR(),this._$AH=h):r!==this._$AH&&r!==O&&this._(r):r._$litType$!==void 0?this.$(r):r.nodeType!==void 0?this.T(r):Ot(r)?this.k(r):this._(r)}O(r){return this._$AA.parentNode.insertBefore(r,this._$AB)}T(r){this._$AH!==r&&(this._$AR(),this._$AH=this.O(r))}_(r){this._$AH!==h&&j(this._$AH)?this._$AA.nextSibling.data=r:this.T(N.createTextNode(r)),this._$AH=r}$(r){let{values:e,_$litType$:t}=r,i=typeof t=="number"?this._$AC(r):(t.el===void 0&&(t.el=q.createElement(et(t.h,t.h[0]),this.options)),t);if(this._$AH?._$AD===i)this._$AH.p(e);else{let n=new fe(i,this),s=n.u(this.options);n.p(e),this.T(s),this._$AH=n}}_$AC(r){let e=Qe.get(r.strings);return e===void 0&&Qe.set(r.strings,e=new q(r)),e}k(r){we(this._$AH)||(this._$AH=[],this._$AR());let e=this._$AH,t,i=0;for(let n of r)i===e.length?e.push(t=new a(this.O(G()),this.O(G()),this,this.options)):t=e[i],t._$AI(n),i++;i<e.length&&(this._$AR(t&&t._$AB.nextSibling,i),e.length=i)}_$AR(r=this._$AA.nextSibling,e){for(this._$AP?.(!1,!0,e);r!==this._$AB;){let t=We(r).nextSibling;We(r).remove(),r=t}}setConnected(r){this._$AM===void 0&&(this._$Cv=r,this._$AP?.(r))}},V=class{get tagName(){return this.element.tagName}get _$AU(){return this._$AM._$AU}constructor(r,e,t,i,n){this.type=1,this._$AH=h,this._$AN=void 0,this.element=r,this.name=e,this._$AM=i,this.options=n,t.length>2||t[0]!==""||t[1]!==""?(this._$AH=Array(t.length-1).fill(new String),this.strings=t):this._$AH=h}_$AI(r,e=this,t,i){let n=this.strings,s=!1;if(n===void 0)r=I(this,r,e,0),s=!j(r)||r!==this._$AH&&r!==O,s&&(this._$AH=r);else{let o=r,l,d;for(r=n[0],l=0;l<n.length-1;l++)d=I(this,o[t+l],e,l),d===O&&(d=this._$AH[l]),s||=!j(d)||d!==this._$AH[l],d===h?r=h:r!==h&&(r+=(d??"")+n[l+1]),this._$AH[l]=d}s&&!i&&this.j(r)}j(r){r===h?this.element.removeAttribute(this.name):this.element.setAttribute(this.name,r??"")}},_e=class extends V{constructor(){super(...arguments),this.type=3}j(r){this.element[this.name]=r===h?void 0:r}},ge=class extends V{constructor(){super(...arguments),this.type=4}j(r){this.element.toggleAttribute(this.name,!!r&&r!==h)}},be=class extends V{constructor(r,e,t,i,n){super(r,e,t,i,n),this.type=5}_$AI(r,e=this){if((r=I(this,r,e,0)??h)===O)return;let t=this._$AH,i=r===h&&t!==h||r.capture!==t.capture||r.once!==t.once||r.passive!==t.passive,n=r!==h&&(t===h||i);i&&this.element.removeEventListener(this.name,this,t),n&&this.element.addEventListener(this.name,this,r),this._$AH=r}handleEvent(r){typeof this._$AH=="function"?this._$AH.call(this.options?.host??this.element,r):this._$AH.handleEvent(r)}},ve=class{constructor(r,e,t){this.element=r,this.type=6,this._$AN=void 0,this._$AM=e,this.options=t}get _$AU(){return this._$AM._$AU}_$AI(r){I(this,r)}};var Ft=ye.litHtmlPolyfillSupport;Ft?.(q,Y),(ye.litHtmlVersions??=[]).push("3.3.3");var tt=(a,r,e)=>{let t=e?.renderBefore??r,i=t._$litPart$;if(i===void 0){let n=e?.renderBefore??null;t._$litPart$=i=new Y(r.insertBefore(G(),n),n,void 0,e??{})}return i._$AI(a),i};var Se=globalThis,R=class extends E{constructor(){super(...arguments),this.renderOptions={host:this},this._$Do=void 0}createRenderRoot(){let r=super.createRenderRoot();return this.renderOptions.renderBefore??=r.firstChild,r}update(r){let e=this.render();this.hasUpdated||(this.renderOptions.isConnected=this.isConnected),super.update(r),this._$Do=tt(e,this.renderRoot,this.renderOptions)}connectedCallback(){super.connectedCallback(),this._$Do?.setConnected(!0)}disconnectedCallback(){super.disconnectedCallback(),this._$Do?.setConnected(!1)}render(){return O}};R._$litElement$=!0,R.finalized=!0,Se.litElementHydrateSupport?.({LitElement:R});var It=Se.litElementPolyfillSupport;It?.({LitElement:R});(Se.litElementVersions??=[]).push("4.2.2");var rt=a=>(r,e)=>{e!==void 0?e.addInitializer(()=>{customElements.define(a,r)}):customElements.define(a,r)};var Vt={attribute:!0,type:String,converter:z,reflect:!1,hasChanged:te},Lt=(a=Vt,r,e)=>{let{kind:t,metadata:i}=e,n=globalThis.litPropertyMetadata.get(i);if(n===void 0&&globalThis.litPropertyMetadata.set(i,n=new Map),t==="setter"&&((a=Object.create(a)).wrapped=!0),n.set(e.name,a),t==="accessor"){let{name:s}=e;return{set(o){let l=r.get.call(this);r.set.call(this,o),this.requestUpdate(s,l,a,!0,o)},init(o){return o!==void 0&&this.C(s,void 0,a,o),o}}}if(t==="setter"){let{name:s}=e;return function(o){let l=this[s];r.call(this,o),this.requestUpdate(s,l,a,!0,o)}}throw Error("Unsupported decorator location: "+t)};function ie(a){return(r,e)=>typeof e=="object"?Lt(a,r,e):((t,i,n)=>{let s=i.hasOwnProperty(n);return i.constructor.createProperty(n,t),s?Object.getOwnPropertyDescriptor(i,n):void 0})(a,r,e)}function x(a){return ie({...a,state:!0,attribute:!1})}var ke="Energy Actions";var Ut=/RECOVERY REQUIRED|OPERATOR DECISION REQUIRED|RESTORE BLOCKED|RECOVERY BLOCKED|\bFAILED\b|VERIFY ERROR|VERIFY TIMEOUT|VERIFY REFUSED/i,Bt=/DEFERRED/i,Ht=/^(RESTORING|STARTING|ACTIVATION VERIFY)/i;function ne(a){let{active:r,armed:e,operationInProgress:t,statusText:i}=a;return r===null||e===null||t===null?"unavailable":i&&Ut.test(i)?"recovery_attention":i&&Bt.test(i)?"deferred":i&&Ht.test(i)?"busy":r?"active":t?"busy":e?"armed":"ready"}function it(a){return a==="armed"}function $e(a){return a!=="busy"&&a!=="unavailable"}function at(a){return a==="ready"||a==="armed"}var zt={unavailable:"Unavailable",recovery_attention:"Attention Needed",deferred:"Waiting For Inverter",busy:"Working",active:"Active",armed:"Armed",ready:"Ready"};function nt(a){return zt[a]}var Wt=/RECOVERY REQUIRED|OPERATOR DECISION REQUIRED|ACCEPT REFUSED|Recovery Arm first|RESTORE BLOCKED|RECOVERY BLOCKED|\bFAILED\b|VERIFY ERROR|VERIFY TIMEOUT|VERIFY REFUSED/i,Gt=/DEFERRED/i,jt=/^(RESTORING|STARTING)/i;function se(a){let{active:r,armed:e,operationInProgress:t,snapshotValid:i,statusText:n}=a;return r===null||e===null||t===null||i===null?"unavailable":n&&Wt.test(n)?"recovery_attention":n&&Gt.test(n)?"deferred":n&&jt.test(n)?"busy":r?"active":t?"busy":i?"deferred":e?"armed":"ready"}function st(a){return a==="armed"}function oe(a){return a!=="busy"&&a!=="unavailable"}function ot(a){return a==="ready"||a==="armed"}var qt={unavailable:"Unavailable",recovery_attention:"Attention Needed",deferred:"Waiting For Inverter",busy:"Working",active:"Active",armed:"Armed",ready:"Ready"};function Yt(a){return qt[a]}function De(a,r){return a==="ready"&&r===!0?"scheduled":a}function Ee(a){return a==="scheduled"?"Scheduled":a==="interlocked"?"Interlocked":Yt(a)}var Kt=/target (\d+)\s*W export/i,Qt=/Stop SOC (\d+)\s*%/i;function lt(a,r){if(a!==null&&Number.isFinite(a))return a;let e=r?Kt.exec(r):null;return e?Number(e[1]):null}function dt(a,r){if(a!==null&&Number.isFinite(a))return a;let e=r?Qt.exec(r):null;return e?Number(e[1]):null}var Jt=/OPERATOR DECISION REQUIRED|ACCEPT REFUSED|Recovery Arm first/i;function ct(a,r){return r===!0&&!!a&&Jt.test(a)}var Zt=/RECOVERY BLOCKED|inverter writes? (?:are |is )?locked|deliberate recovery required/i,Xt=/START FAILED|ACTIVATION (?:VERIFY|WRITE) FAILED/i,er=/OPERATOR DECISION REQUIRED/i,tr=/press End Free Power|retry(?:ing)? restore/i,rr=/\bRECOVERY REQUIRED\b/i,ir=/snapshot retained/i,ar=/RESTORE BLOCKED/i;function ut(a){let r=a.statusText??"",e=a.snapshotValid;return Zt.test(r)?{actionable:!1,actionLabel:null,secondary:!1,explanation:"Deliberate recovery is required - this will not clear on its own."}:Xt.test(r)&&e===!1?{actionable:!1,actionLabel:null,secondary:!1,explanation:"No saved snapshot is held - there is nothing to restore."}:er.test(r)&&tr.test(r)&&e===!0?{actionable:!0,actionLabel:"Retry End & Restore",secondary:!1,explanation:null}:rr.test(r)&&e===!0?{actionable:!0,actionLabel:"Restore Saved Settings",secondary:!1,explanation:null}:ir.test(r)&&e===!0?{actionable:!0,actionLabel:"End & Restore Now",secondary:!0,explanation:null}:ar.test(r)?e===!0?{actionable:!0,actionLabel:"Attempt Restore",secondary:!0,explanation:"Operator decision required - live inverter state matches neither the saved snapshot nor Free Power's intended state. Restoring is not guaranteed to resolve the mismatch."}:{actionable:!1,actionLabel:null,secondary:!1,explanation:"Operator decision required, and no confirmed snapshot is held to restore - review the inverter's live state directly."}:e===!0?{actionable:!0,actionLabel:"End & Restore Now",secondary:!1,explanation:null}:{actionable:!1,actionLabel:null,secondary:!1,explanation:"Unable to confirm a saved snapshot is held - review the firmware status directly before acting."}}var nr=new Set(["active","busy","recovery_attention","deferred"]);function sr(a){return a!==null&&nr.has(a)}function K(a,r){return(a==="ready"||a==="armed")&&sr(r)}function Q(a,r){return a&&!r}function Te(a,r){switch(r){case"busy":return`${a} is restoring inverter state.`;case"recovery_attention":case"deferred":return`${a} requires recovery before this can be used.`;default:return`${a} currently owns inverter control.`}}var pt=["recovery_attention","deferred","busy","active","armed","scheduled","interlocked","ready","unavailable"];function ht(a){let r=pt.indexOf(a);return r<0?pt.length:r}function mt(a,r){return a!=="unavailable"||r!=="unavailable"}function Ae(a,r){return ht(r)<ht(a)?"dump_to_grid":"free_power"}function ft(a){switch(a){case"recovery_attention":return"fault";case"busy":case"deferred":return"warning";case"active":return"info";default:return"none"}}function _t(a){switch(a){case"fault":return"fault";case"warning":return"warning";case"info":return"accent";default:return null}}function gt(a){return a==="dump_to_grid"?"Dump to Grid":"Free Power"}function bt(a,r,e){let t=e?.trim()??"";return t?`${a}: ${r} - ${t}`:`${a}: ${r}`}function Re(a){return a.armed===!0?"armed":"hidden"}function Pe(a){return!!a&&/^REJECTED/i.test(a.trim())}function Ce(a){return!!a&&/^BLOCKED/i.test(a.trim())}function Ne(a){return a===!0}function Oe(a,r){return a==="ready"&&r==="armed"?"scheduled":a}function Me(a){return{domain:"input_boolean",service:"turn_on",data:{entity_id:a}}}function Fe(a){return{domain:"script",service:"turn_on",data:{entity_id:a}}}function vt(a,r){return{domain:"input_datetime",service:"set_datetime",data:{entity_id:a,datetime:r}}}function Ie(a,r){return{domain:"input_number",service:"set_value",data:{entity_id:a,value:r}}}function yt(a,r){return r===null||!Number.isFinite(r)||r<=0?a:Math.min(a,r)}var or=/^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2}):(\d{2})$/;function M(a){if(!a)return null;let r=or.exec(a.trim());if(!r)return null;let[,e,t,i,n,s,o]=r,l=new Date(Number(e),Number(t)-1,Number(i),Number(n),Number(s),Number(o));return Number.isNaN(l.getTime())?null:l}function wt(a){let r=e=>e.toString().padStart(2,"0");return`${a.getFullYear()}-${r(a.getMonth()+1)}-${r(a.getDate())} ${r(a.getHours())}:${r(a.getMinutes())}:${r(a.getSeconds())}`}var lr=["Sun","Mon","Tue","Wed","Thu","Fri","Sat"],dr=["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];function Ve(a){let r=lr[a.getDay()],e=a.getDate(),t=dr[a.getMonth()],i=a.getHours().toString().padStart(2,"0"),n=a.getMinutes().toString().padStart(2,"0");return`${r} ${e} ${t} \u2022 ${i}:${n}`}function J(a,r){let e=a-r;if(e<=0)return null;let t=Math.floor(e/1e3),i=Math.floor(t/3600),n=Math.floor(t%3600/60),s=t%60;return i>0?`${i}h ${n}m`:n>0?`${n}m ${s.toString().padStart(2,"0")}s`:`${s}s`}function T(a){return a==null||Number.isNaN(a)?"--":Math.abs(a)>=1e3?`${(a/1e3).toFixed(2)} kW`:`${a.toFixed(0)} W`}function F(a){if(a==null||Number.isNaN(a))return"--";let r=Math.round(a);if(r<60)return`${r} min`;let e=Math.floor(r/60),t=r%60;return t===0?`${e}h`:`${e}h ${t}m`}function L(a){return a==null||Number.isNaN(a)?"--":`${Math.round(a)}%`}function f(a){if(a==null||a==="unknown"||a==="unavailable"||a==="")return null;let r=Number(a);return Number.isFinite(r)?r:null}function m(a){return a==null||a==="unknown"||a==="unavailable"||a===""?null:a==="on"}var le=4e3,cr=1e3,g=class extends R{constructor(){super(...arguments);this._confirmEndRestore=!1;this._confirmEndDump=!1;this._dumpMode="now";this._nowMs=Date.now();this._mode="now";this._track=null}static getStubConfig(){return{type:"custom:ecco-energy-actions-card",title:ke,free_power:{active:"binary_sensor.free_power_active",operation_in_progress:"binary_sensor.free_power_operation_in_progress",snapshot_valid:"binary_sensor.free_power_snapshot_valid",status:"sensor.free_power_status",ends_at:"sensor.free_power_ends_at",failures:"sensor.free_power_failures_since_boot",start_attempts:"sensor.free_power_start_attempts_since_boot",start_successes:"sensor.free_power_start_successes_since_boot",restore_successes:"sensor.free_power_restore_successes_since_boot",write_enable:"switch.free_power_write_enable",max_charge_power:"number.free_power_max_charge_power",duration:"number.free_power_duration",start:"button.start_free_power_charge_now",end_restore:"button.end_free_power_restore_now"},schedule:{armed:"input_boolean.ecco_free_power_schedule_armed",start:"input_datetime.ecco_free_power_schedule_start",duration:"input_number.ecco_free_power_schedule_duration",power:"input_number.ecco_free_power_schedule_power",last_result:"input_text.ecco_free_power_schedule_last_result",status:"sensor.ecco_free_power_schedule_status",cancel:"script.ecco_free_power_cancel_schedule"},dump_to_grid:{active:"binary_sensor.dump_to_grid_active",operation_in_progress:"binary_sensor.dump_to_grid_operation_in_progress",snapshot_valid:"binary_sensor.dump_to_grid_snapshot_valid",status:"sensor.dump_to_grid_status",ends_at:"sensor.dump_to_grid_ends_at",battery_soc:"sensor.ecco_battery_soc",failures:"sensor.dump_to_grid_failures_since_boot",start_attempts:"sensor.dump_to_grid_start_attempts_since_boot",start_successes:"sensor.dump_to_grid_start_successes_since_boot",restore_successes:"sensor.dump_to_grid_restore_successes_since_boot",write_enable:"switch.dump_to_grid_write_enable",export_power:"number.dump_to_grid_export_power",stop_soc:"number.dump_to_grid_stop_soc",duration:"number.dump_to_grid_duration",start:"button.start_dump_to_grid_now",end_restore:"button.end_dump_to_grid_restore_now",active_export_power:"sensor.dump_to_grid_active_export_power",active_stop_soc:"sensor.dump_to_grid_active_stop_soc",last_end_reason:"sensor.dump_to_grid_last_end_reason",recovery_arm:"switch.dump_to_grid_recovery_arm",recovery_force_restore:"button.dump_to_grid_force_restore_original",recovery_accept:"button.dump_to_grid_accept_current_state",recovery_state:"sensor.dump_to_grid_recovery_state",schedule:{armed:"input_boolean.ecco_dump_to_grid_schedule_armed",start:"input_datetime.ecco_dump_to_grid_schedule_start",duration:"input_number.ecco_dump_to_grid_schedule_duration",power:"input_number.ecco_dump_to_grid_schedule_power",stop_soc:"input_number.ecco_dump_to_grid_schedule_stop_soc",last_result:"input_text.ecco_dump_to_grid_schedule_last_result",status:"sensor.ecco_dump_to_grid_schedule_status",cancel:"script.ecco_dump_to_grid_cancel_schedule"}}}}setConfig(e){if(!e||typeof e!="object")throw new Error("ecco-energy-actions-card: invalid configuration");if(!e.free_power)throw new Error("ecco-energy-actions-card: `free_power:` entity mapping is required");this._config=e}getCardSize(){return this._config?.schedule||this._config?.dump_to_grid?.schedule?6:4}disconnectedCallback(){super.disconnectedCallback(),this._stopTicking(),this._confirmTimer&&clearTimeout(this._confirmTimer),this._confirmDumpTimer&&clearTimeout(this._confirmDumpTimer)}shouldUpdate(e){return!!this._config}willUpdate(){let e=this._config?.free_power;if(e){this._pendingPower!==void 0&&f(this._entityState(e.max_charge_power))===this._pendingPower&&(this._pendingPower=void 0),this._pendingDuration!==void 0&&f(this._entityState(e.duration))===this._pendingDuration&&(this._pendingDuration=void 0);let n=m(this._entityState(e.active)),s=m(this._entityState(e.write_enable)),o=m(this._entityState(e.operation_in_progress)),l=this._entityState(e.status),d=ne({active:n,armed:s,operationInProgress:o,statusText:l});this._lastVisualState!==void 0&&this._lastVisualState!==d&&this._confirmEndRestore&&(this._confirmEndRestore=!1,this._confirmTimer&&clearTimeout(this._confirmTimer)),this._lastVisualState=d}let t=this._config?.schedule;t&&(this._pendingSchedulePower!==void 0&&f(this._entityState(t.power))===this._pendingSchedulePower&&(this._pendingSchedulePower=void 0),this._pendingScheduleDuration!==void 0&&f(this._entityState(t.duration))===this._pendingScheduleDuration&&(this._pendingScheduleDuration=void 0));let i=this._config?.dump_to_grid;if(i){this._pendingDumpPower!==void 0&&f(this._entityState(i.export_power))===this._pendingDumpPower&&(this._pendingDumpPower=void 0),this._pendingDumpStopSoc!==void 0&&f(this._entityState(i.stop_soc))===this._pendingDumpStopSoc&&(this._pendingDumpStopSoc=void 0),this._pendingDumpDuration!==void 0&&f(this._entityState(i.duration))===this._pendingDumpDuration&&(this._pendingDumpDuration=void 0);let n=i.schedule;n&&(this._pendingDumpSchedulePower!==void 0&&f(this._entityState(n.power))===this._pendingDumpSchedulePower&&(this._pendingDumpSchedulePower=void 0),this._pendingDumpScheduleStopSoc!==void 0&&f(this._entityState(n.stop_soc))===this._pendingDumpScheduleStopSoc&&(this._pendingDumpScheduleStopSoc=void 0),this._pendingDumpScheduleDuration!==void 0&&f(this._entityState(n.duration))===this._pendingDumpScheduleDuration&&(this._pendingDumpScheduleDuration=void 0));let s=m(this._entityState(i.active)),o=m(this._entityState(i.write_enable)),l=m(this._entityState(i.operation_in_progress)),d=m(this._entityState(i.snapshot_valid)),c=this._entityState(i.status),p=se({active:s,armed:o,operationInProgress:l,snapshotValid:d,statusText:c});this._lastDumpVisualState!==void 0&&this._lastDumpVisualState!==p&&this._confirmEndDump&&(this._confirmEndDump=!1,this._confirmDumpTimer&&clearTimeout(this._confirmDumpTimer)),this._lastDumpVisualState=p}if(this._config?.layout==="tabbed"&&this._track===null&&this.hass){let n=this._trackSummary();mt(n.fp.state,n.dump.state)&&(this._track=Ae(n.fp.state,n.dump.state))}}updated(){let e=this._active()||this._scheduleArmed()||this._dumpActive()||this._dumpScheduleArmed();e&&!this._tickTimer?this._tickTimer=setInterval(()=>{this._nowMs=Date.now()},cr):!e&&this._tickTimer&&this._stopTicking()}_stopTicking(){this._tickTimer&&(clearInterval(this._tickTimer),this._tickTimer=void 0)}_active(){let e=this._config?.free_power;return e?m(this._entityState(e.active))===!0:!1}_scheduleArmed(){let e=this._config?.schedule;return e?m(this._entityState(e.armed))===!0:!1}_dumpActive(){let e=this._config?.dump_to_grid;return e?m(this._entityState(e.active))===!0:!1}_dumpScheduleArmed(){let e=this._config?.dump_to_grid?.schedule;return e?m(this._entityState(e.armed))===!0:!1}_freePowerVisualStateForInterlock(){let e=this._config?.free_power;if(!e||!this.hass)return null;let t=m(this._entityState(e.active)),i=m(this._entityState(e.write_enable)),n=m(this._entityState(e.operation_in_progress)),s=this._entityState(e.status);return ne({active:t,armed:i,operationInProgress:n,statusText:s})}_dumpVisualStateForInterlock(){let e=this._config?.dump_to_grid;if(!e||!this.hass)return null;let t=m(this._entityState(e.active)),i=m(this._entityState(e.write_enable)),n=m(this._entityState(e.operation_in_progress)),s=m(this._entityState(e.snapshot_valid)),o=this._entityState(e.status);return se({active:t,armed:i,operationInProgress:n,snapshotValid:s,statusText:o})}_entityState(e){if(!(!e||!this.hass))return this.hass.states[e]?.state}_entity(e){if(!(!e||!this.hass))return this.hass.states[e]}_moreInfo(e){e&&this.dispatchEvent(new CustomEvent("hass-more-info",{detail:{entityId:e},bubbles:!0,composed:!0}))}_callService(e,t,i){this.hass?.callService&&this.hass.callService(e,t,i)}_callServiceObj(e){this._callService(e.domain,e.service,e.data)}render(){if(!this._config)return u``;let e=this._config.title??ke;return this._config.layout==="tabbed"?this._renderTabbed(e):u`
      <ha-card>
        <h1 class="card-title">${e}</h1>
        <div class="actions-grid">
          ${this._renderFreePowerTile()}
          ${this._renderDumpToGridTile()}
        </div>
      </ha-card>
    `}_trackSummary(){let e=this._freePowerVisualStateForInterlock(),t=this._dumpVisualStateForInterlock(),i={state:"unavailable",pill:"unavailable",label:"Unavailable",statusText:void 0},n=this._config?.free_power;if(e!==null&&n){let l=this._config?.schedule,d=l?Oe(e,Re({armed:m(this._entityState(l.armed))})):e,c=K(e,t)?"interlocked":d;i={state:c,pill:c,label:this._labelFor(c),statusText:this._entityState(n.status)}}let s=this._config?.dump_to_grid,o=s&&this.hass?{state:"unavailable",pill:"unavailable",label:"Unavailable",statusText:void 0}:{state:"unavailable",pill:"locked",label:"Coming Soon",statusText:void 0};if(t!==null&&s){let l=s.schedule,d=De(t,l?m(this._entityState(l.armed)):null),c=K(t,e)?"interlocked":d;o={state:c,pill:c,label:Ee(c),statusText:this._entityState(s.status)}}return{fp:i,dump:o}}_selectTrack(e){this._confirmTimer&&clearTimeout(this._confirmTimer),this._confirmDumpTimer&&clearTimeout(this._confirmDumpTimer),this._confirmEndRestore=!1,this._confirmEndDump=!1,this._track=e}_renderTabbed(e){let t=this._trackSummary(),i=this._track??Ae(t.fp.state,t.dump.state),n=i==="free_power"?"dump_to_grid":"free_power",s=i==="free_power"?t.dump:t.fp,o=_t(ft(s.state)),l=o==="fault"?"mdi:alert-circle-outline":o==="warning"?"mdi:alert-outline":"mdi:information-outline";return u`
      <ha-card>
        <div class="tabbed-header">
          <h1 class="card-title">${e}</h1>
          <div class="track-strip">
            <span class="state-pill state-${t.fp.pill}">Free Power · ${t.fp.label}</span>
            <span class="state-pill state-${t.dump.pill}">Dump to Grid · ${t.dump.label}</span>
          </div>
        </div>
        <div class="mode-selector track-selector" role="tablist">
          <button
            type="button"
            role="tab"
            class="mode-tab track-tab ${i==="free_power"?"is-active":""}"
            aria-selected=${i==="free_power"}
            @click=${()=>this._selectTrack("free_power")}
          >
            <ha-icon icon="mdi:flash"></ha-icon> Free Power
          </button>
          <button
            type="button"
            role="tab"
            class="mode-tab track-tab ${i==="dump_to_grid"?"is-active":""}"
            aria-selected=${i==="dump_to_grid"}
            @click=${()=>this._selectTrack("dump_to_grid")}
          >
            <ha-icon icon="mdi:transmission-tower-export"></ha-icon> Dump to Grid
          </button>
        </div>
        ${o?u`
              <div class="track-alert track-alert-${o}" role="status">
                <ha-icon icon=${l}></ha-icon>
                <div class="track-alert-text">${bt(gt(n),s.label,s.statusText)}</div>
                <button type="button" class="track-alert-show" @click=${()=>this._selectTrack(n)}>Show</button>
              </div>
            `:h}
        <div class="actions-grid is-tabbed">
          ${i==="free_power"?this._renderFreePowerTile():this._renderDumpToGridTile()}
        </div>
      </ha-card>
    `}_renderFreePowerTile(){let e=this._config?.free_power;if(!e||!this.hass)return this._renderFreePowerUnavailable("Free Power is not configured on this card.");let t=m(this._entityState(e.active)),i=m(this._entityState(e.write_enable)),n=m(this._entityState(e.operation_in_progress)),s=m(this._entityState(e.snapshot_valid)),o=this._entityState(e.status),l=ne({active:t,armed:i,operationInProgress:n,statusText:o});if(l==="unavailable")return this._renderFreePowerUnavailable("Free Power entities are unavailable right now.");let d=this._config?.schedule,c=d?m(this._entityState(d.armed)):null,p=Re({armed:c}),y=d?Oe(l,p):l,_=this._dumpVisualStateForInterlock(),w=K(l,_),k=w?"interlocked":y,$=w?Te("Dump to Grid",_):void 0,D=this._entity(e.max_charge_power),b=this._entity(e.duration),U=this._pendingPower??f(D?.state),S=this._pendingDuration??f(b?.state),de=this._iconFor(k),ce=this._labelFor(k);return u`
      <div class="tile free-power-tile state-${k}">
        <div class="tile-header">
          <div class="tile-heading">
            <ha-icon class="tile-icon" icon=${de}></ha-icon>
            <span class="tile-name">Free Power</span>
          </div>
          <span class="state-pill state-${k}">${ce}</span>
        </div>

        <div class="free-power-body">
          ${d&&p==="armed"?this._renderScheduleBanner(d):h}
          ${w?this._renderInterlockBanner($):h}

          ${this._renderFreePowerBody(l,{fp:e,schedule:d,statusText:o,snapshotValid:s,interlocked:w,stagedPowerW:U,stagedDurationMin:S,stagedPowerEntity:D,stagedDurationEntity:b})}
        </div>
      </div>
    `}_iconFor(e){if(e==="scheduled")return"mdi:calendar-clock";if(e==="interlocked")return"mdi:lock-outline";switch(e){case"active":return"mdi:flash";case"armed":return"mdi:shield-flash-outline";case"busy":return"mdi:autorenew";case"deferred":return"mdi:timer-sand";case"recovery_attention":return"mdi:alert-circle-outline";case"unavailable":return"mdi:flash-off-outline";default:return"mdi:flash-outline"}}_labelFor(e){return e==="scheduled"?"Scheduled":e==="interlocked"?"Interlocked":nt(e)}_renderInterlockBanner(e){return u`
      <div class="interlock-banner">
        <ha-icon icon="mdi:lock-outline"></ha-icon>
        <div class="interlock-banner-text">${e}</div>
      </div>
    `}_renderFreePowerUnavailable(e){return u`
      <div class="tile free-power-tile state-unavailable">
        <div class="tile-header">
          <div class="tile-heading">
            <ha-icon class="tile-icon" icon="mdi:flash-off-outline"></ha-icon>
            <span class="tile-name">Free Power</span>
          </div>
          <span class="state-pill state-unavailable">Unavailable</span>
        </div>
        <p class="tile-description">${e}</p>
      </div>
    `}_renderFreePowerBody(e,t){switch(e){case"active":return this._renderActiveBody(t);case"busy":return this._renderBusyBody(t.statusText,t.fp.status);case"deferred":return this._renderDeferredBody(t.statusText,t.fp.status);case"recovery_attention":return this._renderAttentionBody(t);default:return this._renderReadyOrArmedBody(e,t)}}_renderReadyOrArmedBody(e,t){let i=!!t.schedule,n=i?this._mode:"now";return u`
      ${i?this._renderModeSelector():h}
      ${n==="later"&&t.schedule?this._renderLaterPanel(t.schedule):this._renderNowPanel(e,t)}
    `}_renderModeSelector(){let e=this._mode==="now";return u`
      <div class="mode-selector" role="tablist">
        <button
          type="button"
          role="tab"
          class="mode-tab ${e?"is-active":""}"
          aria-selected=${e}
          @click=${()=>this._mode="now"}
        >
          <ha-icon icon="mdi:flash"></ha-icon> Now
        </button>
        <button
          type="button"
          role="tab"
          class="mode-tab ${e?"":"is-active"}"
          aria-selected=${!e}
          @click=${()=>this._mode="later"}
        >
          <ha-icon icon="mdi:calendar-clock"></ha-icon> Later
        </button>
      </div>
    `}_renderNowPanel(e,t){let i=e==="armed",n=Q(it(e),t.interlocked),s=Q(at(e),t.interlocked);return u`
      <p class="tile-description">Charge the battery from free/zero-cost grid energy.</p>

      ${this._renderNumberControl({label:"Max Charge Power",icon:"mdi:flash",entity:t.stagedPowerEntity,value:t.stagedPowerW,fallbackMin:500,fallbackMax:8e3,fallbackStep:100,formatValue:T,disabled:t.interlocked,onPreview:o=>this._pendingPower=o,onCommit:o=>this._commitNumber("power",o,t.fp.max_charge_power)})}
      ${this._renderNumberControl({label:"Duration",icon:"mdi:timer-outline",entity:t.stagedDurationEntity,value:t.stagedDurationMin,fallbackMin:1,fallbackMax:240,fallbackStep:1,formatValue:F,disabled:t.interlocked,onPreview:o=>this._pendingDuration=o,onCommit:o=>this._commitNumber("duration",o,t.fp.duration)})}

      <div class="readiness-row">
        <ha-icon icon=${i?"mdi:shield-check":"mdi:shield-outline"}></ha-icon>
        <span>${i?"Armed - ready to start":"Safe - no inverter change made by staging values"}</span>
      </div>
      ${this._renderStatusLine(t.statusText,t.fp.status)}

      <div class="action-row">
        <button
          class="arm-toggle ${i?"is-armed":""}"
          ?disabled=${!s}
          @click=${()=>this._toggleArm(t.fp.write_enable,i)}
        >
          <ha-icon icon=${i?"mdi:shield-key":"mdi:shield-key-outline"}></ha-icon>
          ${i?"Disarm":"Arm Free Power"}
        </button>
        <button
          class="start-button"
          ?disabled=${!n}
          @click=${()=>this._callService("button","press",{entity_id:t.fp.start})}
        >
          <ha-icon icon="mdi:play-circle-outline"></ha-icon>
          Start Now
        </button>
      </div>
      <p class="arm-caption">Arm is single-use - it's consumed the moment you press Start, or if the attempt is rejected.</p>
    `}_renderLaterPanel(e){let t=m(this._entityState(e.armed)),i=Ne(t),n=this._entityState(e.start),s=M(n),o=this._entity(e.duration),l=this._entity(e.power),d=this._entity(e.status),c=this._entityState(e.last_result),p=this._pendingScheduleDuration??f(o?.state),y=this._pendingSchedulePower??f(l?.state),_=d?.attributes?.effective_power_limit_w,w=typeof _=="number"?_:f(typeof _=="string"?_:void 0),k=this._numericAttr(l?.attributes?.max,8e3),$=yt(k,w),D=Pe(c),b=Ce(c),U=!i&&s!==null&&s.getTime()>this._nowMs;return u`
      <p class="tile-description">Stage a future Free Power session - Home Assistant arms and starts it automatically.</p>

      <div class="schedule-field">
        <label class="schedule-field-label"><ha-icon icon="mdi:calendar-clock"></ha-icon> Start</label>
        <input
          type="datetime-local"
          class="schedule-datetime-input"
          .value=${s?this._toDatetimeLocalValue(s):""}
          min=${this._toDatetimeLocalValue(new Date(this._nowMs))}
          ?disabled=${i}
          @change=${S=>this._handleScheduleStartChange(e.start,S.target.value)}
        />
      </div>

      ${this._renderNumberControl({label:"Scheduled Power",icon:"mdi:flash",entity:l,value:y,fallbackMin:500,fallbackMax:8e3,fallbackStep:100,maxOverride:$,formatValue:T,disabled:i||!l,onPreview:S=>this._pendingSchedulePower=S,onCommit:S=>this._commitScheduleNumber("power",S,e.power)})}
      ${this._renderNumberControl({label:"Scheduled Duration",icon:"mdi:timer-outline",entity:o,value:p,fallbackMin:1,fallbackMax:240,fallbackStep:1,formatValue:F,disabled:i||!o,onPreview:S=>this._pendingScheduleDuration=S,onCommit:S=>this._commitScheduleNumber("duration",S,e.duration)})}

      ${c?u`<p class="firmware-note ${D||b?"is-warning":""}">${c}</p>`:h}

      <div class="action-row">
        <button
          class="schedule-arm-toggle"
          ?disabled=${i||!U}
          @click=${()=>this._callServiceObj(Me(e.armed))}
        >
          <ha-icon icon="mdi:calendar-arrow-right"></ha-icon>
          Arm Schedule
        </button>
      </div>
      <p class="arm-caption">
        ${i?"Fields are locked while this schedule is armed - cancel it above to edit, then re-arm.":"Arm Schedule never touches the manual Free Power write-enable switch - Home Assistant arms and starts the inverter automatically when the time comes."}
      </p>
    `}_renderScheduleBanner(e){let t=this._entityState(e.start),i=M(t),n=f(this._entityState(e.duration)),s=f(this._entityState(e.power)),o=i?J(i.getTime(),this._nowMs):null;return u`
      <div class="schedule-banner">
        <ha-icon icon="mdi:calendar-clock"></ha-icon>
        <div class="schedule-banner-text">
          <div class="schedule-banner-line">
            ${i?Ve(i):"--"} • ${T(s)} • ${F(n)}
          </div>
          <div class="schedule-banner-countdown">${o?`Starts in ${o}`:"Starting..."}</div>
        </div>
        <button
          type="button"
          class="schedule-cancel-button"
          @click=${()=>this._callServiceObj(Fe(e.cancel))}
        >
          Cancel
        </button>
      </div>
    `}_toDatetimeLocalValue(e){let t=i=>i.toString().padStart(2,"0");return`${e.getFullYear()}-${t(e.getMonth()+1)}-${t(e.getDate())}T${t(e.getHours())}:${t(e.getMinutes())}`}_handleScheduleStartChange(e,t){if(!t)return;let i=new Date(t);Number.isNaN(i.getTime())||this._callServiceObj(vt(e,wt(i)))}_commitScheduleNumber(e,t,i){e==="power"?this._pendingSchedulePower=t:this._pendingScheduleDuration=t,this._callServiceObj(Ie(i,t))}_renderActiveBody(e){let t=this._entityState(e.fp.ends_at),i=M(t),n=i?J(i.getTime(),this._nowMs):null;return u`
      <div class="active-hero">
        <div class="active-hero-time">${n??"--:--"}</div>
        <div class="active-hero-label">time remaining</div>
      </div>
      <div class="active-secondary-line">
        ${T(e.stagedPowerW)} target • ends ${i?this._formatClock(i):t??"--"}
      </div>

      <div class="readiness-row">
        <ha-icon icon=${e.snapshotValid?"mdi:content-save-check-outline":"mdi:content-save-alert-outline"}></ha-icon>
        <span>${e.snapshotValid?"Original settings snapshot saved":"No snapshot recorded - check status"}</span>
      </div>

      ${this._renderStatusLine(e.statusText,e.fp.status,{alwaysShow:!0})}
      ${this._renderDiagnosticsDetails(e.fp)}
      ${this._renderEndRestoreButton(e.fp.end_restore,"End & Restore Now",!1,$e("active"))}
    `}_renderBusyBody(e,t){return u`
      <div class="transition-panel">
        <ha-icon class="spin" icon="mdi:autorenew"></ha-icon>
        <div class="transition-text">
          <div class="transition-headline">Working...</div>
          ${this._renderTransitionDetail(e??"Free Power is mid-transaction.",t)}
        </div>
      </div>
      <p class="transition-hint">Controls are disabled while a transaction is in flight - this clears on its own.</p>
    `}_renderDeferredBody(e,t){return u`
      <div class="transition-panel deferred">
        <ha-icon icon="mdi:timer-sand"></ha-icon>
        <div class="transition-text">
          <div class="transition-headline">Waiting for inverter bus</div>
          ${this._renderTransitionDetail(e??"Modbus bus busy - the watchdog will retry.",t)}
        </div>
      </div>
      <p class="transition-hint">This is expected occasionally - the watchdog retries automatically. No action needed.</p>
    `}_renderAttentionBody(e){let t=ut({statusText:e.statusText,snapshotValid:e.snapshotValid});return u`
      <div class="attention-panel">
        <ha-icon icon="mdi:alert-circle-outline"></ha-icon>
        <div class="transition-text">
          <div class="transition-headline">Attention needed</div>
          ${this._renderTransitionDetail(e.statusText??"Free Power requires operator attention.",e.fp.status)}
        </div>
      </div>
      <p class="transition-hint">
        ${t.explanation??"No automatic retry. Starting a new Free Power session is disabled until this clears."}
      </p>
      ${t.actionable?this._renderEndRestoreButton(e.fp.end_restore,t.actionLabel??"End & Restore Now",t.secondary,$e("recovery_attention")):h}
    `}_renderTransitionDetail(e,t){return u`
      <div
        class="transition-detail clickable"
        tabindex="0"
        role="button"
        @click=${()=>this._moreInfo(t)}
        @keydown=${i=>{(i.key==="Enter"||i.key===" ")&&(i.preventDefault(),this._moreInfo(t))}}
      >
        ${e}
      </div>
    `}_renderStatusLine(e,t,i){return!(i?.alwaysShow||!!e&&e!=="Inactive")||!e?h:u`
      <p
        class="firmware-note clickable"
        tabindex="0"
        role="button"
        @click=${()=>this._moreInfo(t)}
        @keydown=${s=>{(s.key==="Enter"||s.key===" ")&&(s.preventDefault(),this._moreInfo(t))}}
      >
        ${e}
      </p>
    `}_renderDiagnosticsDetails(e){let t=[],i=(n,s)=>{let o=f(this._entityState(s));o!==null&&t.push({label:n,value:o.toString()})};return i("Starts",e.start_attempts),i("Started OK",e.start_successes),i("Restored OK",e.restore_successes),i("Failures",e.failures),t.length===0?h:u`
      <details class="diagnostics-details">
        <summary>Details</summary>
        <div class="diagnostics-row">
          ${t.map(n=>u`<span class="diagnostic-chip">${n.label}: ${n.value}</span>`)}
        </div>
      </details>
    `}_renderEndRestoreButton(e,t,i,n){let s=this._confirmEndRestore;return u`
      <button
        class="end-restore-button ${i?"secondary":""} ${s?"confirming":""}"
        ?disabled=${!n}
        @click=${()=>this._handleEndRestoreClick(e)}
      >
        <ha-icon icon="mdi:backup-restore"></ha-icon>
        ${s?"Tap again to End & Restore":t}
        ${s?u`<span class="confirm-progress" style="animation-duration:${le}ms"></span>`:h}
      </button>
    `}_handleEndRestoreClick(e){if(!this._confirmEndRestore){this._confirmEndRestore=!0,this._confirmTimer=setTimeout(()=>{this._confirmEndRestore=!1},le);return}this._confirmTimer&&clearTimeout(this._confirmTimer),this._confirmEndRestore=!1,this._callService("button","press",{entity_id:e})}_toggleArm(e,t){this._callService("switch",t?"turn_off":"turn_on",{entity_id:e})}_commitNumber(e,t,i){e==="power"?this._pendingPower=t:this._pendingDuration=t,this._callService("number","set_value",{entity_id:i,value:t})}_commitDumpNumber(e,t,i){e==="power"?this._pendingDumpPower=t:e==="stop_soc"?this._pendingDumpStopSoc=t:this._pendingDumpDuration=t,this._callService("number","set_value",{entity_id:i,value:t})}_handleEndDumpClick(e){if(!this._confirmEndDump){this._confirmEndDump=!0,this._confirmDumpTimer=setTimeout(()=>{this._confirmEndDump=!1},le);return}this._confirmDumpTimer&&clearTimeout(this._confirmDumpTimer),this._confirmEndDump=!1,this._callService("button","press",{entity_id:e})}_numericAttr(e,t){if(typeof e=="number"&&Number.isFinite(e))return e;if(typeof e=="string"){let i=f(e);if(i!==null)return i}return t}_formatClock(e){let t=e.getHours().toString().padStart(2,"0"),i=e.getMinutes().toString().padStart(2,"0");return`${t}:${i}`}_renderNumberControl(e){let t=e.entity?.attributes??{},i=this._numericAttr(t.min,e.fallbackMin),n=e.maxOverride??this._numericAttr(t.max,e.fallbackMax),s=this._numericAttr(t.step,e.fallbackStep),o=e.value??i,l=e.disabled??!e.entity,d=n>i?Math.max(0,Math.min(100,(o-i)/(n-i)*100)):0;return u`
      <div class="number-control">
        <div class="number-control-label">
          <ha-icon icon=${e.icon}></ha-icon>
          <span>${e.label}</span>
          <span class="number-control-value">${e.formatValue(o)}</span>
        </div>
        <input
          type="range"
          class="number-control-slider"
          style="--eaa-slider-fill:${d}%"
          min=${i}
          max=${n}
          step=${s}
          .value=${String(o)}
          ?disabled=${l}
          @input=${c=>{let p=Number(c.target.value);Number.isFinite(p)&&e.onPreview(p)}}
          @change=${c=>{let p=Number(c.target.value);Number.isFinite(p)&&e.onCommit(p)}}
        />
      </div>
    `}_renderDumpToGridTile(){let e=this._config?.dump_to_grid;if(!e||!this.hass)return this._renderDumpToGridLockedShell();let t=m(this._entityState(e.active)),i=m(this._entityState(e.write_enable)),n=m(this._entityState(e.operation_in_progress)),s=m(this._entityState(e.snapshot_valid)),o=this._entityState(e.status),l=se({active:t,armed:i,operationInProgress:n,snapshotValid:s,statusText:o});if(l==="unavailable")return this._renderDumpUnavailable("Dump to Grid entities are unavailable right now.");let d=e.schedule,c=d?m(this._entityState(d.armed)):null,p=De(l,c),y=this._freePowerVisualStateForInterlock(),_=K(l,y),w=_?"interlocked":p,k=_?Te("Free Power",y):void 0,$=this._entity(e.export_power),D=this._entity(e.stop_soc),b=this._entity(e.duration),U=this._pendingDumpPower??f($?.state),S=this._pendingDumpStopSoc??f(D?.state),de=this._pendingDumpDuration??f(b?.state),ce=this._dumpIconFor(w),xt=Ee(w);return u`
      <div class="tile dump-to-grid-tile state-${w}">
        <div class="tile-header">
          <div class="tile-heading">
            <ha-icon class="tile-icon" icon=${ce}></ha-icon>
            <span class="tile-name">Dump to Grid</span>
          </div>
          <span class="state-pill state-${w}">${xt}</span>
        </div>

        <div class="dump-to-grid-body">
          ${d&&c===!0?this._renderDumpScheduleBanner(d):h}
          ${_?this._renderInterlockBanner(k):h}

          ${this._renderDumpBody(l,{dump:e,statusText:o,snapshotValid:s,interlocked:_,stagedPowerW:U,stagedStopSoc:S,stagedDurationMin:de,stagedPowerEntity:$,stagedStopSocEntity:D,stagedDurationEntity:b})}
        </div>
      </div>
    `}_renderDumpToGridLockedShell(){return u`
      <div class="tile dump-to-grid-tile locked">
        <div class="tile-header">
          <div class="tile-heading">
            <ha-icon class="tile-icon" icon="mdi:transmission-tower-export"></ha-icon>
            <span class="tile-name">Dump to Grid</span>
          </div>
          <span class="state-pill state-locked"><ha-icon icon="mdi:lock-outline"></ha-icon> Coming Soon</span>
        </div>
        <p class="tile-description">Export stored battery energy to the grid.</p>

        <div class="locked-preview">
          <div class="locked-row"><span>Export Power</span><span>--</span></div>
          <div class="locked-row"><span>Minimum SOC</span><span>--</span></div>
          <div class="locked-row"><span>Duration</span><span>--</span></div>
        </div>

        <p class="tile-footnote">
          Configure <code>dump_to_grid:</code> on this card to enable Manual Dump to Grid V1.
        </p>
      </div>
    `}_dumpIconFor(e){switch(e){case"scheduled":return"mdi:calendar-clock";case"interlocked":return"mdi:lock-outline";case"active":return"mdi:transmission-tower-export";case"armed":return"mdi:shield-flash-outline";case"busy":return"mdi:autorenew";case"deferred":return"mdi:timer-sand";case"recovery_attention":return"mdi:alert-circle-outline";case"unavailable":return"mdi:transmission-tower-off";default:return"mdi:transmission-tower-export"}}_renderDumpUnavailable(e){return u`
      <div class="tile dump-to-grid-tile state-unavailable">
        <div class="tile-header">
          <div class="tile-heading">
            <ha-icon class="tile-icon" icon="mdi:transmission-tower-off"></ha-icon>
            <span class="tile-name">Dump to Grid</span>
          </div>
          <span class="state-pill state-unavailable">Unavailable</span>
        </div>
        <p class="tile-description">${e}</p>
      </div>
    `}_renderDumpBody(e,t){switch(e){case"active":return this._renderDumpActiveBody(t);case"busy":return this._renderBusyBody(t.statusText??"Dump to Grid is mid-transaction.",t.dump.status);case"deferred":return this._renderDumpDeferredBody(t);case"recovery_attention":return this._renderDumpAttentionBody(t);default:return this._renderDumpReadyOrArmedBody(e,t)}}_renderDumpReadyOrArmedBody(e,t){let i=t.dump.schedule,n=i?this._dumpMode:"now";return u`
      ${i?this._renderDumpModeSelector():h}
      ${n==="later"&&i?this._renderDumpLaterPanel(i):this._renderDumpNowPanel(e,t)}
      ${this._renderDumpLastEndReason(t.dump)}
    `}_renderDumpModeSelector(){let e=this._dumpMode==="now";return u`
      <div class="mode-selector" role="tablist">
        <button
          type="button"
          role="tab"
          class="mode-tab ${e?"is-active":""}"
          aria-selected=${e}
          @click=${()=>this._dumpMode="now"}
        >
          <ha-icon icon="mdi:flash"></ha-icon> Now
        </button>
        <button
          type="button"
          role="tab"
          class="mode-tab ${e?"":"is-active"}"
          aria-selected=${!e}
          @click=${()=>this._dumpMode="later"}
        >
          <ha-icon icon="mdi:calendar-clock"></ha-icon> Later
        </button>
      </div>
    `}_renderDumpNowPanel(e,t){let i=e==="armed",n=Q(st(e),t.interlocked),s=Q(ot(e),t.interlocked);return u`
      <p class="tile-description">Export stored battery energy to the grid down to a chosen floor.</p>

      ${this._renderNumberControl({label:"Export Power",icon:"mdi:transmission-tower-export",entity:t.stagedPowerEntity,value:t.stagedPowerW,fallbackMin:500,fallbackMax:8e3,fallbackStep:100,formatValue:T,disabled:t.interlocked,onPreview:o=>this._pendingDumpPower=o,onCommit:o=>this._commitDumpNumber("power",o,t.dump.export_power)})}
      ${this._renderNumberControl({label:"Stop SOC",icon:"mdi:battery-arrow-down",entity:t.stagedStopSocEntity,value:t.stagedStopSoc,fallbackMin:10,fallbackMax:90,fallbackStep:1,formatValue:L,disabled:t.interlocked,onPreview:o=>this._pendingDumpStopSoc=o,onCommit:o=>this._commitDumpNumber("stop_soc",o,t.dump.stop_soc)})}
      ${this._renderNumberControl({label:"Duration",icon:"mdi:timer-outline",entity:t.stagedDurationEntity,value:t.stagedDurationMin,fallbackMin:1,fallbackMax:240,fallbackStep:1,formatValue:F,disabled:t.interlocked,onPreview:o=>this._pendingDumpDuration=o,onCommit:o=>this._commitDumpNumber("duration",o,t.dump.duration)})}

      <div class="readiness-row">
        <ha-icon icon=${i?"mdi:shield-check":"mdi:shield-outline"}></ha-icon>
        <span>${i?"Armed - ready to start":"Safe - no inverter change made by staging values"}</span>
      </div>
      ${this._renderStatusLine(t.statusText,t.dump.status)}

      <div class="action-row">
        <button
          class="arm-toggle ${i?"is-armed":""}"
          ?disabled=${!s}
          @click=${()=>this._toggleArm(t.dump.write_enable,i)}
        >
          <ha-icon icon=${i?"mdi:shield-key":"mdi:shield-key-outline"}></ha-icon>
          ${i?"Disarm":"Arm Dump to Grid"}
        </button>
        <button
          class="start-button"
          ?disabled=${!n}
          @click=${()=>this._callService("button","press",{entity_id:t.dump.start})}
        >
          <ha-icon icon="mdi:play-circle-outline"></ha-icon>
          Start Now
        </button>
      </div>
      <p class="arm-caption">Arm is single-use - it's consumed the moment you press Start, or if the attempt is rejected.</p>
    `}_renderDumpLaterPanel(e){let t=m(this._entityState(e.armed)),i=Ne(t),n=this._entityState(e.start),s=M(n),o=this._entity(e.duration),l=this._entity(e.power),d=this._entity(e.stop_soc),c=this._entityState(e.last_result),p=this._pendingDumpScheduleDuration??f(o?.state),y=this._pendingDumpSchedulePower??f(l?.state),_=this._pendingDumpScheduleStopSoc??f(d?.state),w=Pe(c)||!!c&&/^FAILED/i.test(c.trim()),k=Ce(c),$=!!l&&!!o&&!!d&&t!==null,D=$&&!i&&s!==null&&s.getTime()>this._nowMs;return u`
      <p class="tile-description">Stage a future Dump to Grid session - Home Assistant arms and starts it automatically.</p>

      <div class="schedule-field">
        <label class="schedule-field-label"><ha-icon icon="mdi:calendar-clock"></ha-icon> Start</label>
        <input
          type="datetime-local"
          class="schedule-datetime-input"
          .value=${s?this._toDatetimeLocalValue(s):""}
          min=${this._toDatetimeLocalValue(new Date(this._nowMs))}
          ?disabled=${i}
          @change=${b=>this._handleScheduleStartChange(e.start,b.target.value)}
        />
      </div>

      ${this._renderNumberControl({label:"Scheduled Export Power",icon:"mdi:transmission-tower-export",entity:l,value:y,fallbackMin:500,fallbackMax:8e3,fallbackStep:100,formatValue:T,disabled:i||!l,onPreview:b=>this._pendingDumpSchedulePower=b,onCommit:b=>this._commitDumpScheduleNumber("power",b,e.power)})}
      ${this._renderNumberControl({label:"Scheduled Stop SOC",icon:"mdi:battery-arrow-down",entity:d,value:_,fallbackMin:10,fallbackMax:90,fallbackStep:1,formatValue:L,disabled:i||!d,onPreview:b=>this._pendingDumpScheduleStopSoc=b,onCommit:b=>this._commitDumpScheduleNumber("stop_soc",b,e.stop_soc)})}
      ${this._renderNumberControl({label:"Scheduled Duration",icon:"mdi:timer-outline",entity:o,value:p,fallbackMin:1,fallbackMax:240,fallbackStep:1,formatValue:F,disabled:i||!o,onPreview:b=>this._pendingDumpScheduleDuration=b,onCommit:b=>this._commitDumpScheduleNumber("duration",b,e.duration)})}

      ${$?h:u`<p class="firmware-note is-warning">
            Scheduled Dump to Grid helpers are unavailable - is ecco_dump_to_grid_schedule.yaml installed?
          </p>`}
      ${c?u`<p class="firmware-note ${w||k?"is-warning":""}">${c}</p>`:h}

      <div class="action-row">
        <button
          class="schedule-arm-toggle"
          ?disabled=${!D}
          @click=${()=>this._callServiceObj(Me(e.armed))}
        >
          <ha-icon icon="mdi:calendar-arrow-right"></ha-icon>
          Arm Schedule
        </button>
      </div>
      <p class="arm-caption">
        ${i?"Fields are locked while this schedule is armed - cancel it above to edit, then re-arm.":"Arm Schedule never touches the Dump to Grid write-enable switch. At the start time Home Assistant stages these values, arms and presses Start; the firmware re-checks Stop SOC, charging TOU slots and Free Power itself. Arming is refused if it overlaps an armed Free Power schedule or a charging TOU slot."}
      </p>
    `}_renderDumpScheduleBanner(e){let t=M(this._entityState(e.start)),i=f(this._entityState(e.duration)),n=f(this._entityState(e.power)),s=f(this._entityState(e.stop_soc)),o=t?J(t.getTime(),this._nowMs):null;return u`
      <div class="schedule-banner">
        <ha-icon icon="mdi:calendar-clock"></ha-icon>
        <div class="schedule-banner-text">
          <div class="schedule-banner-line">
            ${t?Ve(t):"--"} • ${T(n)} • stop
            ${L(s)} • ${F(i)}
          </div>
          <div class="schedule-banner-countdown">${o?`Starts in ${o}`:"Starting..."}</div>
        </div>
        <button
          type="button"
          class="schedule-cancel-button"
          @click=${()=>this._callServiceObj(Fe(e.cancel))}
        >
          Cancel
        </button>
      </div>
    `}_commitDumpScheduleNumber(e,t,i){e==="power"?this._pendingDumpSchedulePower=t:e==="stop_soc"?this._pendingDumpScheduleStopSoc=t:this._pendingDumpScheduleDuration=t,this._callServiceObj(Ie(i,t))}_renderDumpLastEndReason(e){let t=this._entityState(e.last_end_reason);return!t||t==="unknown"||t==="unavailable"?h:u`<p class="firmware-note">Last lease ended: ${t}</p>`}_renderDumpActiveBody(e){let t=this._entityState(e.dump.ends_at),i=M(t),n=i?J(i.getTime(),this._nowMs):null,s=f(this._entityState(e.dump.battery_soc)),o=lt(f(this._entityState(e.dump.active_export_power)),e.statusText),l=dt(f(this._entityState(e.dump.active_stop_soc)),e.statusText);return u`
      <div class="active-hero">
        <div class="active-hero-time">${n??"--:--"}</div>
        <div class="active-hero-label">time remaining</div>
      </div>
      <div class="active-secondary-line">
        Target ${T(o)} export • ends ${i?this._formatClock(i):t??"--"}
      </div>
      <div class="active-secondary-line">
        Battery: ${L(s)} • stops at ${L(l)}
      </div>

      <div class="readiness-row">
        <ha-icon icon=${e.snapshotValid?"mdi:content-save-check-outline":"mdi:content-save-alert-outline"}></ha-icon>
        <span>${e.snapshotValid?"Original settings snapshot saved":"No snapshot recorded - check status"}</span>
      </div>

      ${this._renderStatusLine(e.statusText,e.dump.status,{alwaysShow:!0})}
      ${this._renderDumpDiagnosticsDetails(e.dump)}
      ${this._renderEndDumpButton(e.dump.end_restore,"End & Restore Now",oe("active"))}
    `}_renderDumpDeferredBody(e){return u`
      ${this._renderDeferredBody(e.statusText,e.dump.status)}
      ${e.snapshotValid===!0?this._renderEndDumpButton(e.dump.end_restore,"End & Restore Now",oe("deferred")):h}
    `}_renderDumpAttentionBody(e){let i=!!e.dump.recovery_arm&&!!e.dump.recovery_force_restore&&!!e.dump.recovery_accept&&ct(e.statusText,e.snapshotValid);return u`
      <div class="attention-panel">
        <ha-icon icon="mdi:alert-circle-outline"></ha-icon>
        <div class="transition-text">
          <div class="transition-headline">Attention needed</div>
          ${this._renderTransitionDetail(e.statusText??"Dump to Grid requires operator attention.",e.dump.status)}
        </div>
      </div>
      <p class="transition-hint">
        ${i?"Automatic restore is stopped until you decide. Arm recovery, then Force Restore Original (writes only the saved original settings) or Accept Current State (writes nothing; refused while the inverter still shows Dump export).":"If the status above says the watchdog will retry, ECCO keeps retrying the restore automatically. Only OPERATOR DECISION REQUIRED stops automatic retries."}
      </p>
      ${i?this._renderDumpRecoveryPanel(e.dump):h}
      ${this._renderEndDumpButton(e.dump.end_restore,"End & Restore Now",oe("recovery_attention"))}
    `}_renderDumpRecoveryPanel(e){let t=m(this._entityState(e.recovery_arm))===!0,i=this._entityState(e.recovery_state);return u`
      <div class="dump-recovery-panel">
        ${i&&i!=="unknown"&&i!=="unavailable"?u`<p class="firmware-note">${i}</p>`:h}
        <div class="action-row">
          <button
            class="arm-toggle ${t?"is-armed":""}"
            @click=${()=>this._toggleArm(e.recovery_arm,t)}
          >
            <ha-icon icon=${t?"mdi:shield-key":"mdi:shield-key-outline"}></ha-icon>
            ${t?"Disarm Recovery":"Arm Recovery"}
          </button>
        </div>
        <div class="action-row">
          <button
            class="start-button"
            ?disabled=${!t}
            @click=${()=>this._callService("button","press",{entity_id:e.recovery_force_restore})}
          >
            <ha-icon icon="mdi:backup-restore"></ha-icon>
            Force Restore Original
          </button>
          <button
            class="arm-toggle"
            ?disabled=${!t}
            @click=${()=>this._callService("button","press",{entity_id:e.recovery_accept})}
          >
            <ha-icon icon="mdi:check-circle-outline"></ha-icon>
            Accept Current State
          </button>
        </div>
      </div>
    `}_renderDumpDiagnosticsDetails(e){let t=[],i=(n,s)=>{let o=f(this._entityState(s));o!==null&&t.push({label:n,value:o.toString()})};return i("Starts",e.start_attempts),i("Started OK",e.start_successes),i("Restored OK",e.restore_successes),i("Failures",e.failures),t.length===0?h:u`
      <details class="diagnostics-details">
        <summary>Details</summary>
        <div class="diagnostics-row">
          ${t.map(n=>u`<span class="diagnostic-chip">${n.label}: ${n.value}</span>`)}
        </div>
      </details>
    `}_renderEndDumpButton(e,t,i){let n=this._confirmEndDump;return u`
      <button
        class="end-restore-button ${n?"confirming":""}"
        ?disabled=${!i}
        @click=${()=>this._handleEndDumpClick(e)}
      >
        <ha-icon icon="mdi:backup-restore"></ha-icon>
        ${n?"Tap again to End & Restore":t}
        ${n?u`<span class="confirm-progress" style="animation-duration:${le}ms"></span>`:h}
      </button>
    `}};g.styles=pe`
    :host {
      /* Container query, not a viewport media query: this card is often
         docked in a narrow dashboard column on an otherwise-wide desktop
         browser (a sidebar/split-view layout), which a viewport-width
         media query would never see as "narrow" - the responsive rules
         below need to react to the CARD's own rendered width instead. */
      container-type: inline-size;

      --eaa-bg: var(--ecco-card-background, #141c2d);
      --eaa-surface: color-mix(in srgb, var(--eaa-bg) 82%, white 6%);
      --eaa-border: color-mix(in srgb, var(--eaa-bg) 70%, white 12%);
      --eaa-text: var(--primary-text-color, #eef2f7);
      --eaa-text-muted: var(--secondary-text-color, #9aa7b8);
      --eaa-accent: var(--primary-color, #4fd1ff);
      --eaa-ok: #38d996;
      --eaa-warning: #f4b942;
      --eaa-fault: #ff5c6c;
      --eaa-armed: #ffbd3d;
      --eaa-schedule: #c07cff;
      --eaa-glow: color-mix(in srgb, var(--eaa-accent) 45%, transparent);

      display: block;
    }

    ha-card {
      background: linear-gradient(160deg, var(--eaa-bg), color-mix(in srgb, var(--eaa-bg) 88%, black 8%));
      color: var(--eaa-text);
      border-radius: 20px;
      padding: 18px 18px 20px;
      overflow: hidden;
    }

    .card-title {
      margin: 0 0 14px;
      font-size: 18px;
      font-weight: 700;
      letter-spacing: 0.01em;
      color: var(--eaa-text);
    }

    .actions-grid {
      display: grid;
      /* 2026-09-26 sibling card polish: Free Power and Dump to Grid are
         equal first-class siblings, not a main feature plus a secondary
         column - both tracks get the same flexible 1fr share, each with the
         same 280px floor Dump to Grid alone used to have, so neither tile's
         controls (NOW/LATER selector, sliders, Arm/Start, banners) get
         squeezed. No max-width on the grid itself: a real wide dashboard
         card should use its full width - see .free-power-body/
         .dump-to-grid-body below for where the actual controls are capped
         instead, so sliders/buttons never stretch edge-to-edge even though
         each tile's own card border now does. */
      grid-template-columns: minmax(280px, 1fr) minmax(280px, 1fr);
      gap: 16px;
      /* 2026-09-26 equal-height polish: stretch (the grid default, made
         explicit here) rather than "start" - Dump to Grid's extra Stop SOC
         row and status/last-lease line make it naturally taller than Free
         Power, and the two should still finish on the same line rather than
         Free Power ending early with a visible gap beneath it. Only has an
         effect while both tiles share one grid row (the two-column desktop/
         tablet layout above) - the single-column stack below has exactly
         one tile per row, so this is a no-op there and each stacked card
         keeps its own natural content height (see .tile's comment below). */
      align-items: stretch;
    }

    @container (max-width: 620px) {
      .actions-grid {
        grid-template-columns: 1fr;
      }
    }

    /* Caps and centres the actual staging/control area within each tile -
       the tile's own border/background still spans the full flexible grid
       column (so the tile reads as deliberately sized, not glued to one
       side with empty space beside it), but the sliders, buttons and text
       inside stay a comfortable, non-absurd width. Centring (not
       left-alignment) is what keeps the extra space either side of the
       controls, once a tile is wider than this, from reading as a leftover
       void - has no effect at all once the tile itself is narrower than
       this, which is the common case on tablet/mobile and needs no
       separate breakpoint. Both tiles share the same cap so they read as
       the same product family.
       Also a flex column (2026-09-26 equal-height polish) so it can grow to
       fill whatever extra height .actions-grid's stretch gives the shorter
       tile - see .action-row's margin-top: auto below for where that spare
       height actually goes. */
    .free-power-body,
    .dump-to-grid-body {
      max-width: 680px;
      margin: 0 auto;
      flex: 1 1 auto;
      display: flex;
      flex-direction: column;
    }

    .tile {
      border-radius: 16px;
      background: var(--eaa-surface);
      border: 1px solid var(--eaa-border);
      padding: 14px 16px 16px;
      box-sizing: border-box;
      /* Flex column (2026-09-26 equal-height polish) purely so
         .free-power-body/.dump-to-grid-body above can flex:1 to fill
         whatever height .actions-grid's align-items: stretch gives this
         tile - visually identical to plain block stacking otherwise. */
      display: flex;
      flex-direction: column;
      transition:
        border-color 0.28s ease,
        background 0.28s ease,
        box-shadow 0.28s ease;
    }

    .tile-header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 8px;
      flex-wrap: wrap;
      margin-bottom: 6px;
    }

    .tile-heading {
      display: flex;
      align-items: center;
      gap: 8px;
      min-width: 0;
    }

    .tile-icon {
      --mdc-icon-size: 20px;
      color: var(--eaa-text-muted);
    }

    .tile-name {
      font-size: 15px;
      font-weight: 700;
      letter-spacing: 0.01em;
      /* Never truncated (e.g. "Dump to Grid" -> "Dump...") - if the header
         row gets tight, the pill wraps to its own line before the name
         would ever be squeezed (see .tile-header's flex-wrap above). */
      white-space: normal;
    }

    .tile-description {
      margin: 2px 0 12px;
      font-size: 12.5px;
      color: var(--eaa-text-muted);
      line-height: 1.4;
    }

    .state-pill {
      display: inline-flex;
      align-items: center;
      gap: 4px;
      font-size: 10.5px;
      font-weight: 800;
      letter-spacing: 0.04em;
      text-transform: uppercase;
      padding: 4px 9px;
      border-radius: 999px;
      background: color-mix(in srgb, var(--eaa-text-muted) 20%, transparent);
      color: var(--eaa-text-muted);
      white-space: nowrap;
    }
    .state-pill ha-icon {
      --mdc-icon-size: 12px;
    }
    .state-pill.state-ready {
      background: color-mix(in srgb, var(--eaa-accent) 20%, transparent);
      color: var(--eaa-accent);
    }
    .state-pill.state-armed {
      background: color-mix(in srgb, var(--eaa-armed) 24%, transparent);
      color: var(--eaa-armed);
    }
    .state-pill.state-scheduled {
      background: color-mix(in srgb, var(--eaa-schedule) 24%, transparent);
      color: var(--eaa-schedule);
    }
    .state-pill.state-active {
      background: color-mix(in srgb, var(--eaa-ok) 24%, transparent);
      color: var(--eaa-ok);
    }
    .state-pill.state-busy,
    .state-pill.state-deferred {
      background: color-mix(in srgb, var(--eaa-warning) 20%, transparent);
      color: var(--eaa-warning);
    }
    .state-pill.state-recovery_attention {
      background: color-mix(in srgb, var(--eaa-fault) 24%, transparent);
      color: var(--eaa-fault);
    }
    .state-pill.state-locked {
      background: color-mix(in srgb, var(--eaa-text-muted) 16%, transparent);
      color: var(--eaa-text-muted);
    }
    .state-pill.state-interlocked {
      background: color-mix(in srgb, var(--eaa-text-muted) 20%, transparent);
      color: var(--eaa-text-muted);
    }

    /* ---- Free Power tile state tints ---- */
    .free-power-tile.state-ready {
      border-color: var(--eaa-border);
    }
    .free-power-tile.state-armed {
      border-color: color-mix(in srgb, var(--eaa-armed) 55%, var(--eaa-border));
      background: color-mix(in srgb, var(--eaa-armed) 8%, var(--eaa-surface));
      box-shadow: 0 0 20px -8px color-mix(in srgb, var(--eaa-armed) 55%, transparent);
    }
    .free-power-tile.state-scheduled {
      border-color: color-mix(in srgb, var(--eaa-schedule) 45%, var(--eaa-border));
      background: color-mix(in srgb, var(--eaa-schedule) 7%, var(--eaa-surface));
      box-shadow: 0 0 18px -8px color-mix(in srgb, var(--eaa-schedule) 45%, transparent);
    }
    .free-power-tile.state-active {
      border-color: color-mix(in srgb, var(--eaa-ok) 60%, var(--eaa-border));
      background: color-mix(in srgb, var(--eaa-ok) 9%, var(--eaa-surface));
      box-shadow: 0 0 24px -6px color-mix(in srgb, var(--eaa-ok) 50%, transparent);
      animation: eaa-active-glow 3.4s ease-in-out infinite;
    }
    .free-power-tile.state-busy,
    .free-power-tile.state-deferred {
      border-color: color-mix(in srgb, var(--eaa-warning) 45%, var(--eaa-border));
      background: color-mix(in srgb, var(--eaa-warning) 6%, var(--eaa-surface));
    }
    .free-power-tile.state-recovery_attention {
      border-color: color-mix(in srgb, var(--eaa-fault) 55%, var(--eaa-border));
      background: color-mix(in srgb, var(--eaa-fault) 8%, var(--eaa-surface));
      box-shadow: 0 0 18px -6px color-mix(in srgb, var(--eaa-fault) 45%, transparent);
    }
    .free-power-tile.state-unavailable {
      opacity: 0.6;
    }
    /* Subdued, no glow/animation - a deliberately quieter tint than
       recovery_attention/busy (this feature is not at fault, its sibling
       currently owns the inverter, see interlock.ts). */
    .free-power-tile.state-interlocked {
      border-color: var(--eaa-border);
      background: color-mix(in srgb, var(--eaa-text-muted) 5%, var(--eaa-surface));
      opacity: 0.82;
    }

    /* ---- Dump to Grid tile state tints - same tokens as Free Power above ---- */
    .dump-to-grid-tile.state-ready {
      border-color: var(--eaa-border);
    }
    .dump-to-grid-tile.state-armed {
      border-color: color-mix(in srgb, var(--eaa-armed) 55%, var(--eaa-border));
      background: color-mix(in srgb, var(--eaa-armed) 8%, var(--eaa-surface));
      box-shadow: 0 0 20px -8px color-mix(in srgb, var(--eaa-armed) 55%, transparent);
    }
    .dump-to-grid-tile.state-active {
      border-color: color-mix(in srgb, var(--eaa-ok) 60%, var(--eaa-border));
      background: color-mix(in srgb, var(--eaa-ok) 9%, var(--eaa-surface));
      box-shadow: 0 0 24px -6px color-mix(in srgb, var(--eaa-ok) 50%, transparent);
      animation: eaa-active-glow 3.4s ease-in-out infinite;
    }
    .dump-to-grid-tile.state-scheduled {
      border-color: color-mix(in srgb, var(--eaa-schedule) 45%, var(--eaa-border));
      background: color-mix(in srgb, var(--eaa-schedule) 7%, var(--eaa-surface));
      box-shadow: 0 0 18px -8px color-mix(in srgb, var(--eaa-schedule) 45%, transparent);
    }
    .dump-recovery-panel {
      display: flex;
      flex-direction: column;
      gap: 8px;
      padding: 10px;
      border-radius: 12px;
      border: 1px dashed color-mix(in srgb, var(--eaa-fault) 45%, var(--eaa-border));
    }
    .dump-to-grid-tile.state-busy,
    .dump-to-grid-tile.state-deferred {
      border-color: color-mix(in srgb, var(--eaa-warning) 45%, var(--eaa-border));
      background: color-mix(in srgb, var(--eaa-warning) 6%, var(--eaa-surface));
    }
    .dump-to-grid-tile.state-recovery_attention {
      border-color: color-mix(in srgb, var(--eaa-fault) 55%, var(--eaa-border));
      background: color-mix(in srgb, var(--eaa-fault) 8%, var(--eaa-surface));
      box-shadow: 0 0 18px -6px color-mix(in srgb, var(--eaa-fault) 45%, transparent);
    }
    /* Subdued, no glow/animation - same rationale as
       .free-power-tile.state-interlocked above. */
    .dump-to-grid-tile.state-interlocked {
      border-color: var(--eaa-border);
      background: color-mix(in srgb, var(--eaa-text-muted) 5%, var(--eaa-surface));
      opacity: 0.82;
    }
    .dump-to-grid-tile.state-unavailable {
      opacity: 0.6;
    }

    @keyframes eaa-active-glow {
      0%,
      100% {
        box-shadow: 0 0 18px -8px color-mix(in srgb, var(--eaa-ok) 45%, transparent);
      }
      50% {
        box-shadow: 0 0 26px -4px color-mix(in srgb, var(--eaa-ok) 62%, transparent);
      }
    }
    @media (prefers-reduced-motion: reduce) {
      .free-power-tile.state-active,
      .dump-to-grid-tile.state-active {
        animation: none;
      }
      .spin {
        animation: none !important;
      }
      .confirm-progress {
        display: none;
      }
    }

    /* ---- NOW / LATER mode selector ---- */
    .mode-selector {
      display: flex;
      gap: 4px;
      padding: 3px;
      margin-bottom: 12px;
      border-radius: 10px;
      background: color-mix(in srgb, var(--eaa-bg) 60%, transparent);
      border: 1px solid var(--eaa-border);
    }
    .mode-tab {
      flex: 1 1 auto;
      border: none;
      background: transparent;
      color: var(--eaa-text-muted);
      padding: 7px 10px;
      font-size: 12px;
      font-weight: 700;
    }
    .mode-tab ha-icon {
      --mdc-icon-size: 15px;
    }
    .mode-tab.is-active {
      background: var(--eaa-surface);
      color: var(--eaa-text);
      box-shadow: 0 1px 4px rgba(0, 0, 0, 0.25);
    }

    /* ---- Schedule banner (shown in both Now and Later views while armed) ---- */
    .schedule-banner {
      display: flex;
      align-items: center;
      gap: 10px;
      padding: 9px 12px;
      border-radius: 12px;
      background: color-mix(in srgb, var(--eaa-schedule) 14%, var(--eaa-surface));
      border: 1px solid color-mix(in srgb, var(--eaa-schedule) 45%, var(--eaa-border));
      margin-bottom: 12px;
    }
    .schedule-banner ha-icon {
      --mdc-icon-size: 19px;
      color: var(--eaa-schedule);
      flex-shrink: 0;
    }
    .schedule-banner-text {
      min-width: 0;
      flex: 1 1 auto;
    }
    .schedule-banner-line {
      font-size: 12px;
      font-weight: 700;
      color: var(--eaa-text);
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .schedule-banner-countdown {
      font-size: 11px;
      color: var(--eaa-schedule);
      font-variant-numeric: tabular-nums;
    }
    .schedule-cancel-button {
      flex: 0 0 auto;
      padding: 7px 12px;
      font-size: 11px;
      min-height: 36px;
      border-color: color-mix(in srgb, var(--eaa-fault) 45%, var(--eaa-border));
      color: var(--eaa-fault);
      background: transparent;
    }

    /* ---- Interlock banner - deliberately muted/neutral, not warning-
       coloured like the schedule banner above: this feature isn't at
       fault, its sibling currently owns the inverter (see interlock.ts). */
    .interlock-banner {
      display: flex;
      align-items: center;
      gap: 10px;
      padding: 9px 12px;
      border-radius: 12px;
      background: color-mix(in srgb, var(--eaa-text-muted) 12%, var(--eaa-surface));
      border: 1px dashed color-mix(in srgb, var(--eaa-text-muted) 40%, var(--eaa-border));
      margin-bottom: 12px;
    }
    .interlock-banner ha-icon {
      --mdc-icon-size: 19px;
      color: var(--eaa-text-muted);
      flex-shrink: 0;
    }
    .interlock-banner-text {
      min-width: 0;
      flex: 1 1 auto;
      font-size: 12px;
      font-weight: 600;
      color: var(--eaa-text-muted);
      line-height: 1.4;
    }

    /* ---- Schedule (LATER) fields ---- */
    .schedule-field {
      margin-bottom: 12px;
    }
    .schedule-field-label {
      display: flex;
      align-items: center;
      gap: 6px;
      font-size: 11.5px;
      font-weight: 700;
      color: var(--eaa-text-muted);
      margin-bottom: 5px;
    }
    .schedule-field-label ha-icon {
      --mdc-icon-size: 14px;
    }
    .schedule-datetime-input {
      width: 100%;
      box-sizing: border-box;
      font: inherit;
      font-size: 13px;
      color: var(--eaa-text);
      background: color-mix(in srgb, var(--eaa-bg) 55%, transparent);
      border: 1px solid var(--eaa-border);
      border-radius: 8px;
      padding: 9px 10px;
      min-height: 40px;
      color-scheme: dark;
    }
    .schedule-datetime-input:disabled {
      opacity: 0.5;
    }
    .schedule-arm-toggle {
      border-color: color-mix(in srgb, var(--eaa-schedule) 55%, var(--eaa-border));
      color: var(--eaa-schedule);
      background: color-mix(in srgb, var(--eaa-schedule) 10%, var(--eaa-surface));
    }
    .schedule-arm-toggle:not(:disabled):hover {
      background: color-mix(in srgb, var(--eaa-schedule) 18%, var(--eaa-surface));
    }

    .arm-caption {
      font-size: 10.5px;
      color: var(--eaa-text-muted);
      line-height: 1.4;
      margin: 8px 0 0;
      opacity: 0.85;
    }

    /* ---- Number controls ---- */
    .number-control {
      margin-bottom: 12px;
    }
    .number-control-label {
      display: flex;
      align-items: center;
      gap: 6px;
      font-size: 11.5px;
      font-weight: 700;
      color: var(--eaa-text-muted);
      margin-bottom: 5px;
    }
    .number-control-label ha-icon {
      --mdc-icon-size: 14px;
    }
    .number-control-value {
      margin-left: auto;
      font-size: 13px;
      font-weight: 700;
      color: var(--eaa-text);
      font-variant-numeric: tabular-nums;
    }
    .number-control-slider {
      width: 100%;
      appearance: none;
      -webkit-appearance: none;
      height: 6px;
      border-radius: 999px;
      background: linear-gradient(
        to right,
        var(--eaa-accent) 0%,
        var(--eaa-accent) var(--eaa-slider-fill, 0%),
        color-mix(in srgb, var(--eaa-text-muted) 28%, transparent) var(--eaa-slider-fill, 0%)
      );
      outline: none;
      cursor: pointer;
    }
    .number-control-slider::-webkit-slider-thumb {
      appearance: none;
      -webkit-appearance: none;
      width: 20px;
      height: 20px;
      border-radius: 50%;
      background: var(--eaa-accent);
      border: 2px solid var(--eaa-bg);
      box-shadow: 0 0 0 1px color-mix(in srgb, var(--eaa-accent) 60%, transparent);
    }
    .number-control-slider::-moz-range-thumb {
      width: 18px;
      height: 18px;
      border-radius: 50%;
      background: var(--eaa-accent);
      border: 2px solid var(--eaa-bg);
    }
    .number-control-slider:disabled {
      opacity: 0.4;
      cursor: not-allowed;
    }
    .number-control-slider:focus-visible {
      box-shadow: 0 0 0 3px color-mix(in srgb, var(--eaa-accent) 40%, transparent);
    }

    .readiness-row {
      display: flex;
      align-items: center;
      gap: 6px;
      font-size: 11.5px;
      color: var(--eaa-text-muted);
      margin: 6px 0 10px;
    }
    .readiness-row ha-icon {
      --mdc-icon-size: 15px;
    }

    .firmware-note {
      /* Deliberately quiet - a plain status line, not a boxed/input-like
         control. The literal firmware text stays fully readable and
         tappable; it just no longer competes visually with the actual
         controls above it. .is-warning (below) is the one exception - a
         schedule REJECTED/BLOCKED outcome earns the extra weight. */
      font-size: 10.5px;
      color: var(--eaa-text-muted);
      opacity: 0.9;
      margin: 0 0 10px;
      line-height: 1.4;
      word-break: break-word;
    }
    .firmware-note.is-warning {
      background: color-mix(in srgb, var(--eaa-warning) 16%, transparent);
      color: color-mix(in srgb, var(--eaa-warning) 70%, var(--eaa-text));
      border-radius: 8px;
      padding: 6px 9px;
      opacity: 1;
    }
    .firmware-note.clickable,
    .transition-detail.clickable {
      cursor: pointer;
    }
    .firmware-note.clickable:hover {
      color: var(--eaa-text);
      opacity: 1;
    }
    .firmware-note:focus-visible,
    .transition-detail:focus-visible {
      outline: 2px solid var(--eaa-accent);
      outline-offset: 1px;
    }

    .action-row {
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
      /* 2026-09-26 equal-height polish: an auto top margin inside the now-
         flex-column .free-power-body/.dump-to-grid-body absorbs whatever
         spare height align-items: stretch gave the shorter tile, so the
         Arm/Start row (and the footer text right after it) settles at the
         bottom of the card instead of leaving a gap beneath it - every
         control above keeps its normal spacing untouched. Resolves to 0
         (today's exact layout) whenever there's no spare height to absorb -
         the taller tile, and every tile once stacked single-column. */
      margin-top: auto;
    }

    button {
      font: inherit;
      border: 1px solid var(--eaa-border);
      background: var(--eaa-surface);
      color: var(--eaa-text);
      border-radius: 10px;
      padding: 10px 14px;
      min-height: 44px;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      gap: 6px;
      font-size: 12.5px;
      font-weight: 700;
      cursor: pointer;
      transition:
        background 0.18s ease,
        border-color 0.18s ease,
        opacity 0.18s ease,
        transform 0.1s ease;
      flex: 1 1 auto;
    }
    button ha-icon {
      --mdc-icon-size: 16px;
    }
    button:disabled {
      opacity: 0.38;
      cursor: not-allowed;
    }
    button:not(:disabled):active {
      transform: scale(0.98);
    }
    button:focus-visible {
      outline: 2px solid var(--eaa-accent);
      outline-offset: 1px;
    }

    .arm-toggle {
      border-color: color-mix(in srgb, var(--eaa-armed) 45%, var(--eaa-border));
      color: var(--eaa-armed);
    }
    .arm-toggle.is-armed {
      background: color-mix(in srgb, var(--eaa-armed) 18%, var(--eaa-surface));
      border-color: color-mix(in srgb, var(--eaa-armed) 70%, var(--eaa-border));
    }

    .start-button {
      border-color: color-mix(in srgb, var(--eaa-ok) 55%, var(--eaa-border));
      color: var(--eaa-ok);
      background: color-mix(in srgb, var(--eaa-ok) 10%, var(--eaa-surface));
    }
    .start-button:not(:disabled):hover {
      background: color-mix(in srgb, var(--eaa-ok) 18%, var(--eaa-surface));
    }

    .end-restore-button {
      position: relative;
      overflow: hidden;
      width: 100%;
      border-color: color-mix(in srgb, var(--eaa-fault) 45%, var(--eaa-border));
      color: var(--eaa-fault);
      margin-top: 4px;
    }
    .end-restore-button.secondary {
      border-color: var(--eaa-border);
      color: var(--eaa-text-muted);
      background: transparent;
      font-weight: 600;
    }
    .end-restore-button.confirming {
      background: color-mix(in srgb, var(--eaa-fault) 22%, var(--eaa-surface));
      border-color: var(--eaa-fault);
    }
    .confirm-progress {
      position: absolute;
      left: 0;
      bottom: 0;
      height: 3px;
      background: currentColor;
      animation-name: eaa-confirm-shrink;
      animation-timing-function: linear;
      animation-fill-mode: forwards;
    }
    @keyframes eaa-confirm-shrink {
      from {
        width: 100%;
      }
      to {
        width: 0%;
      }
    }

    /* ---- Active hero ---- */
    .active-hero {
      text-align: center;
      padding: 6px 0 2px;
    }
    .active-hero-time {
      font-size: 34px;
      font-weight: 800;
      color: var(--eaa-ok);
      font-variant-numeric: tabular-nums;
      line-height: 1.1;
    }
    .active-hero-label {
      font-size: 10.5px;
      font-weight: 700;
      letter-spacing: 0.06em;
      text-transform: uppercase;
      color: var(--eaa-text-muted);
      margin-top: 2px;
    }
    .active-secondary-line {
      text-align: center;
      font-size: 12.5px;
      color: var(--eaa-text-muted);
      margin: 8px 0 12px;
    }

    .diagnostics-details {
      margin: 0 0 10px;
    }
    .diagnostics-details summary {
      cursor: pointer;
      font-size: 11px;
      font-weight: 700;
      color: var(--eaa-text-muted);
      list-style: none;
      user-select: none;
    }
    .diagnostics-details summary::-webkit-details-marker {
      display: none;
    }
    .diagnostics-details summary::before {
      content: "▸ ";
    }
    .diagnostics-details[open] summary::before {
      content: "▾ ";
    }
    .diagnostics-row {
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
      margin-top: 6px;
    }
    .diagnostic-chip {
      font-size: 9.5px;
      color: var(--eaa-text-muted);
      background: color-mix(in srgb, var(--eaa-text-muted) 12%, transparent);
      border-radius: 999px;
      padding: 3px 8px;
    }

    /* ---- Transition / attention panels ---- */
    .transition-panel,
    .attention-panel {
      display: flex;
      align-items: flex-start;
      gap: 10px;
      padding: 10px 12px;
      border-radius: 12px;
      background: color-mix(in srgb, var(--eaa-warning) 10%, transparent);
      margin-bottom: 8px;
    }
    .attention-panel {
      background: color-mix(in srgb, var(--eaa-fault) 12%, transparent);
    }
    .transition-panel ha-icon,
    .attention-panel ha-icon {
      --mdc-icon-size: 22px;
      color: var(--eaa-warning);
      flex-shrink: 0;
      margin-top: 1px;
    }
    .attention-panel ha-icon {
      color: var(--eaa-fault);
    }
    .transition-panel.deferred ha-icon {
      color: var(--eaa-warning);
    }
    .transition-text {
      min-width: 0;
    }
    .transition-headline {
      font-size: 13px;
      font-weight: 700;
      margin-bottom: 2px;
    }
    .transition-detail {
      font-size: 11.5px;
      color: var(--eaa-text-muted);
      line-height: 1.4;
      word-break: break-word;
    }
    .transition-hint {
      font-size: 11px;
      color: var(--eaa-text-muted);
      margin: 0 0 10px;
      line-height: 1.4;
    }

    .spin {
      animation: eaa-spin 1.6s linear infinite;
    }
    @keyframes eaa-spin {
      from {
        transform: rotate(0deg);
      }
      to {
        transform: rotate(360deg);
      }
    }

    /* ---- Dump to Grid (locked) tile ---- */
    .dump-to-grid-tile.locked {
      background: color-mix(in srgb, var(--eaa-bg) 92%, transparent);
      position: relative;
    }
    /* Scoped to .locked only - the dimmed icon is a "not available yet" cue
       for the static preview shell and must NOT bleed into the real
       interactive tile once dump_to_grid: is configured (V1). */
    .dump-to-grid-tile.locked .tile-icon {
      opacity: 0.6;
    }
    .locked-preview {
      display: flex;
      flex-direction: column;
      gap: 6px;
      margin-bottom: 10px;
      opacity: 0.55;
      pointer-events: none;
      user-select: none;
    }
    .locked-row {
      display: flex;
      justify-content: space-between;
      font-size: 12px;
      color: var(--eaa-text-muted);
      background: color-mix(in srgb, var(--eaa-text-muted) 8%, transparent);
      border-radius: 8px;
      padding: 7px 10px;
    }
    .tile-footnote {
      font-size: 10.5px;
      color: var(--eaa-text-muted);
      line-height: 1.4;
      margin: 0;
      opacity: 0.85;
    }

    /* Mobile: Dump to Grid collapses to a compact locked row - header +
       description + footnote only, dropping the dimmed preview rows. */
    /* Covers both the cramped-second-column case just above the 620px
       stacking point, and a typical stacked phone width below it - in
       both cases Dump to Grid has too little room to justify the three
       dimmed preview rows. */
    @container (max-width: 700px) {
      .dump-to-grid-tile .locked-preview {
        display: none;
      }
      .dump-to-grid-tile {
        padding: 12px 14px 14px;
      }
    }

    /* ---- layout: tabbed (OVW1) - one track visible at a time. The track
       tabs reuse the NOW/LATER selector's look, the header chips reuse the
       state-pill tones, and the cross-track alert banner mirrors the
       schedule banner's shape in the hidden track's own tone. ---- */
    .tabbed-header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      flex-wrap: wrap;
      gap: 8px 12px;
      margin-bottom: 12px;
    }
    .tabbed-header .card-title {
      margin: 0;
    }
    .track-strip {
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
    }
    .track-selector {
      border-radius: 12px;
      margin-bottom: 10px;
    }
    .track-tab {
      min-height: 44px;
      border-radius: 9px;
      font-size: 13px;
      font-weight: 800;
    }
    .track-tab ha-icon {
      --mdc-icon-size: 17px;
    }
    .track-alert {
      --eaa-alert: var(--eaa-accent);
      display: flex;
      align-items: center;
      gap: 10px;
      padding: 9px 12px;
      border-radius: 12px;
      background: color-mix(in srgb, var(--eaa-alert) 14%, var(--eaa-surface));
      border: 1px solid color-mix(in srgb, var(--eaa-alert) 45%, var(--eaa-border));
      margin-bottom: 12px;
      font-size: 12px;
      font-weight: 700;
      line-height: 1.4;
    }
    .track-alert-warning {
      --eaa-alert: var(--eaa-warning);
    }
    .track-alert-fault {
      --eaa-alert: var(--eaa-fault);
    }
    .track-alert ha-icon {
      --mdc-icon-size: 19px;
      color: var(--eaa-alert);
      flex-shrink: 0;
    }
    .track-alert-text {
      min-width: 0;
      flex: 1 1 auto;
      word-break: break-word;
    }
    .track-alert-show {
      flex: 0 0 auto;
      min-height: 36px;
      padding: 7px 12px;
      font-size: 11px;
      background: transparent;
      color: var(--eaa-alert);
      border-color: color-mix(in srgb, var(--eaa-alert) 45%, var(--eaa-border));
    }
    .actions-grid.is-tabbed {
      /* minmax(0, 1fr), not 1fr: a bare 1fr track is min-content-sized and lets a long nowrap line (the armed
         schedule banner) push the single tile wider than the card on a phone. Scoped to the tabbed layout. */
      grid-template-columns: minmax(0, 1fr);
    }
    @container (max-width: 620px) {
      .tabbed-header {
        flex-direction: column;
        align-items: flex-start;
      }
      .track-tab {
        padding: 7px 8px;
        font-size: 12px;
      }
    }
  `,v([ie({attribute:!1})],g.prototype,"hass",2),v([x()],g.prototype,"_config",2),v([x()],g.prototype,"_pendingPower",2),v([x()],g.prototype,"_pendingDuration",2),v([x()],g.prototype,"_pendingSchedulePower",2),v([x()],g.prototype,"_pendingScheduleDuration",2),v([x()],g.prototype,"_confirmEndRestore",2),v([x()],g.prototype,"_pendingDumpPower",2),v([x()],g.prototype,"_pendingDumpStopSoc",2),v([x()],g.prototype,"_pendingDumpDuration",2),v([x()],g.prototype,"_confirmEndDump",2),v([x()],g.prototype,"_dumpMode",2),v([x()],g.prototype,"_pendingDumpSchedulePower",2),v([x()],g.prototype,"_pendingDumpScheduleStopSoc",2),v([x()],g.prototype,"_pendingDumpScheduleDuration",2),v([x()],g.prototype,"_nowMs",2),v([x()],g.prototype,"_mode",2),v([x()],g.prototype,"_track",2),g=v([rt("ecco-energy-actions-card")],g);window.customCards=[...window.customCards??[],{type:"ecco-energy-actions-card",name:"ECCO Energy Actions Card",description:"Free Power as a real product feature (staged controls, two-step arm/start safety, live firmware states, Now/Later scheduling) plus a locked Dump to Grid preview.",preview:!1}];export{g as EccoEnergyActionsCard};
/*! Bundled license information:

@lit/reactive-element/css-tag.js:
  (**
   * @license
   * Copyright 2019 Google LLC
   * SPDX-License-Identifier: BSD-3-Clause
   *)

@lit/reactive-element/reactive-element.js:
lit-html/lit-html.js:
lit-element/lit-element.js:
@lit/reactive-element/decorators/custom-element.js:
@lit/reactive-element/decorators/property.js:
@lit/reactive-element/decorators/state.js:
@lit/reactive-element/decorators/event-options.js:
@lit/reactive-element/decorators/base.js:
@lit/reactive-element/decorators/query.js:
@lit/reactive-element/decorators/query-all.js:
@lit/reactive-element/decorators/query-async.js:
@lit/reactive-element/decorators/query-assigned-nodes.js:
  (**
   * @license
   * Copyright 2017 Google LLC
   * SPDX-License-Identifier: BSD-3-Clause
   *)

lit-html/is-server.js:
  (**
   * @license
   * Copyright 2022 Google LLC
   * SPDX-License-Identifier: BSD-3-Clause
   *)

@lit/reactive-element/decorators/query-assigned-elements.js:
  (**
   * @license
   * Copyright 2021 Google LLC
   * SPDX-License-Identifier: BSD-3-Clause
   *)
*/
""")
BUNDLE_EDITS = (
    (BUNDLE_0_OLD, BUNDLE_0_NEW),
)


def pre_ovw1_bundle(text: str) -> str:
    """frontend/ecco-energy-actions-card/dist/ecco-energy-actions-card.js with exactly ovw1's edits undone (a frozen reverter of chain entry ovw1, PEX): its state as of acfg1."""
    return _revert(text, BUNDLE_EDITS, "frontend/ecco-energy-actions-card/dist/ecco-energy-actions-card.js")


pre_ovw1_bundle.edits = BUNDLE_EDITS   # the PEX contract: a frozen reverter exposes its exact (before, after) pairs


def add_ovw1_bundle(text: str) -> str:
    """Applies ovw1's frontend/ecco-energy-actions-card/dist/ecco-energy-actions-card.js edits to the earlier text (the round trip)."""
    return _apply(text, BUNDLE_EDITS, "frontend/ecco-energy-actions-card/dist/ecco-energy-actions-card.js")


# ---- (PEX frozen edit) home-assistant/tests/test_ecco_fallback_packages.py ---------------------------------------------------
SUITE_FBP_REL = "home-assistant/tests/test_ecco_fallback_packages.py"
# [19] the folder pin skips the files a post-export entry added (one routing, quoted here as data).
SUITE_FBP_0_OLD = _blk(r"""
for rel in fe_tracked:
    fe_hash.update(rel.encode())                                   # repository-relative POSIX path
""")
SUITE_FBP_0_NEW = _blk(r"""
for rel in fe_tracked:
    if rel in _pex.post_export_added():   # PEX (ovw1): a file a post-export entry added is not in the pub0-era folder (the pin's file set)
        continue
    fe_hash.update(rel.encode())                                   # repository-relative POSIX path
""")
SUITE_FBP_EDITS = (
    (SUITE_FBP_0_OLD, SUITE_FBP_0_NEW),
)


def pre_ovw1_fallback_packages_suite(text: str) -> str:
    """home-assistant/tests/test_ecco_fallback_packages.py with exactly ovw1's edits undone (a frozen reverter of chain entry ovw1, PEX): its state as of acfg1."""
    return _revert(text, SUITE_FBP_EDITS, "home-assistant/tests/test_ecco_fallback_packages.py")


pre_ovw1_fallback_packages_suite.edits = SUITE_FBP_EDITS   # the PEX contract: a frozen reverter exposes its exact (before, after) pairs


def add_ovw1_fallback_packages_suite(text: str) -> str:
    """Applies ovw1's home-assistant/tests/test_ecco_fallback_packages.py edits to the earlier text (the round trip)."""
    return _apply(text, SUITE_FBP_EDITS, "home-assistant/tests/test_ecco_fallback_packages.py")


# ---- (PEX frozen edit) home-assistant/tests/test_ecco_shadow_check_ux.py -----------------------------------------------------
SUITE_SCU_REL = "home-assistant/tests/test_ecco_shadow_check_ux.py"
# [7] the same routing.
SUITE_SCU_0_OLD = _blk(r"""
for rel in fe_tracked:
    fe_hash.update(rel.encode())
""")
SUITE_SCU_0_NEW = _blk(r"""
for rel in fe_tracked:
    if rel in _pex.post_export_added():   # PEX (ovw1): a file a post-export entry added is not in the pub0-era folder (the pin's file set)
        continue
    fe_hash.update(rel.encode())
""")
SUITE_SCU_EDITS = (
    (SUITE_SCU_0_OLD, SUITE_SCU_0_NEW),
)


def pre_ovw1_shadow_check_ux_suite(text: str) -> str:
    """home-assistant/tests/test_ecco_shadow_check_ux.py with exactly ovw1's edits undone (a frozen reverter of chain entry ovw1, PEX): its state as of acfg1."""
    return _revert(text, SUITE_SCU_EDITS, "home-assistant/tests/test_ecco_shadow_check_ux.py")


pre_ovw1_shadow_check_ux_suite.edits = SUITE_SCU_EDITS   # the PEX contract: a frozen reverter exposes its exact (before, after) pairs


def add_ovw1_shadow_check_ux_suite(text: str) -> str:
    """Applies ovw1's home-assistant/tests/test_ecco_shadow_check_ux.py edits to the earlier text (the round trip)."""
    return _apply(text, SUITE_SCU_EDITS, "home-assistant/tests/test_ecco_shadow_check_ux.py")


# ---- (PEX frozen edit) registry/tests/test_fallback_recovery_dashboard.py ----------------------------------------------------
SUITE_FRD_REL = "registry/tests/test_fallback_recovery_dashboard.py"
# FB-B3: the same routing.
SUITE_FRD_0_OLD = _blk(r"""
    for rel in fe_tracked:
        fe.update(rel.encode())                                        # repository-relative POSIX path
""")
SUITE_FRD_0_NEW = _blk(r"""
    for rel in fe_tracked:
        if rel in _pex.post_export_added():   # PEX (ovw1): a file a post-export entry added is not in the pub0-era folder (the pin's file set)
            continue
        fe.update(rel.encode())                                        # repository-relative POSIX path
""")
SUITE_FRD_EDITS = (
    (SUITE_FRD_0_OLD, SUITE_FRD_0_NEW),
)


def pre_ovw1_fallback_recovery_dashboard_suite(text: str) -> str:
    """registry/tests/test_fallback_recovery_dashboard.py with exactly ovw1's edits undone (a frozen reverter of chain entry ovw1, PEX): its state as of acfg1."""
    return _revert(text, SUITE_FRD_EDITS, "registry/tests/test_fallback_recovery_dashboard.py")


pre_ovw1_fallback_recovery_dashboard_suite.edits = SUITE_FRD_EDITS   # the PEX contract: a frozen reverter exposes its exact (before, after) pairs


def add_ovw1_fallback_recovery_dashboard_suite(text: str) -> str:
    """Applies ovw1's registry/tests/test_fallback_recovery_dashboard.py edits to the earlier text (the round trip)."""
    return _apply(text, SUITE_FRD_EDITS, "registry/tests/test_fallback_recovery_dashboard.py")


# Every frozen file ovw1 edits, with its reverter (the chain entry's frozen_reverts). ovw1 edits no chain-pinned artifact.
FROZEN_REVERTERS = {
    DASHBOARD_REL: pre_ovw1_dashboard,
    VERSION_REL: pre_ovw1_version,
    CARD_SRC_REL: pre_ovw1_card_source,
    CARD_CONFIG_REL: pre_ovw1_card_config,
    CARD_README_REL: pre_ovw1_card_readme,
    BUNDLE_REL: pre_ovw1_bundle,
    SUITE_FBP_REL: pre_ovw1_fallback_packages_suite,
    SUITE_SCU_REL: pre_ovw1_shadow_check_ux_suite,
    SUITE_FRD_REL: pre_ovw1_fallback_recovery_dashboard_suite,
}
