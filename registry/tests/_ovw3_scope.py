"""ovw3 (the ECCO 3D Energy Flow card on the Overview) change scope: exactly what ovw3 changes in the files the pub0 export froze, and its
exact inverse.

Same technique as the earlier post-export scope modules: every verbatim edit is held HERE as the single source of truth, as an exact
(before, after) pair generated from the real diff and round-trip-checked, and each reverter raises unless each of its edits is present
exactly once. The post-export chain entry `ovw3` (registry/tests/_scope_chain.py POST_EXPORT_ENTRIES, appended last after acs1x;
registry/tests/_pex.py) carries one frozen reverter per edited frozen file and no chain reverter.

WHAT ovw3 IS. Section S3 of the Overview view shows the read-only ECCO 3D Energy Flow card (frontend/ecco-flow-3d-card, V2, merged as
it is; its sources and bundle are unchanged) in place of the 2D Energy Flow card. The card's configuration is the one the ECCO 3D Preview
dashboard serves, in the dashboard's generic entity naming (the site renderer renders it for a site): the 2D card's nodes, today, format
and grid layout settings are kept (its card_mod style is not: the 3D card styles its own ha-card), its grid voltage, connection and
frequency move to nodes.grid (where the 3D card reads them; its inverter_details keep the two transformer temperatures and add the
battery temperature), and the 3D card's ECCO status block, scene pack and freshness settings are added. The configuration is therefore
the card's own example plus grid_options. The card reads states only and opens Home Assistant's more-info dialogue; it calls no service and
writes nothing (its own suites pin that). Its Lovelace resource and bundle file are the ones the preview already loads, so this entry
adds no manifest stanza and no deployment step other than the dashboard file.
  - home-assistant/dashboards/ecco_pro.yaml (pub0 target, FROZEN): the v7.23.0 header note, and the card of section S3 of the Overview
    view (the section's heading comment, span and layout are unchanged);
  - VERSION.yaml (enrolled, FROZEN): dashboard 7.23.0, staged (tested_in_home_assistant stays false); the 7.22.0 record is kept.
ZERO firmware, Home Assistant package, deployment manifest, registry, Intelligence or ecco_core change; ZERO Modbus operation; no new
service call. Every other section and view of the dashboard is byte-identical.

NOT frozen (ordinary edits, nothing to declare): the deploy preflight's card map and its suite, the 3D card's CI wrapper suite, its
parity test's production-Overview check and its sensor-mapping corpus, the FE-1 suite's wiring check (a commented PEX read), the Stage 1
suite's chain-position check (acs1x is followed by ovw3), the PEX ledger, CHANGELOG.md and docs. Added: this module.

This module imports no other scope module, not _scope_chain (the chain imports it) and not _pex. No I/O.
"""

from __future__ import annotations

import hashlib

# Public main the change is based on.
BASE_COMMIT = "24506e36200ec1fd9347564cc9581cc16f46c1b0"

ADDED_FILES = frozenset({
    'registry/tests/_ovw3_scope.py',
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
        raise AssertionError(f"ovw3 scope: {what} must be {state} exactly once, found {n}x: {find[:70]!r}")
    i = text.index(find)
    return text[:i] + put + text[i + len(find):]


def _revert(text: str, edits: tuple, what: str) -> str:
    out = text
    for k, (before, after) in reversed(list(enumerate(edits))):
        out = _swap(out, after, before, f"{what} edit {k}", "present")
    for k, (before, _after) in enumerate(edits):
        n = out.count(before)
        if n != 1:
            raise AssertionError(f"ovw3 scope: {what} anchor {k} must be unique once the edits are removed, found {n}x")
    return out


def _apply(text: str, edits: tuple, what: str) -> str:
    out = text
    for k, (before, after) in enumerate(edits):
        if after in out:
            raise AssertionError(f"ovw3 scope: {what} edit {k} is already present")
        out = _swap(out, before, after, f"{what} anchor {k}", "found")
    return out


# ---- (PEX frozen edit) home-assistant/dashboards/ecco_pro.yaml -----------------------------------------------------------------------
DASHBOARD_REL = "home-assistant/dashboards/ecco_pro.yaml"
# The v7.23.0 header note (after the v7.22.0 note), then the card of Overview section S3: the 2D card (type line to its last card_mod
# line) becomes the OVW3 comment and the 3D card (type line to its grid_options); the shared opening comment line is outside the pair.
DASHBOARD_0_OLD = _blk(r"""
# stay display-only (the site's layout wraps midnight, L1). The heading of section 7 and every other section are unchanged.
""")
DASHBOARD_0_NEW = _blk(r"""
# stay display-only (the site's layout wraps midnight, L1). The heading of section 7 and every other section are unchanged.
# v7.23.0 (OVW3, STAGED / NOT LIVE-PROVEN) puts the read-only ECCO 3D Energy Flow card (frontend/ecco-flow-3d-card, V2) on the
# Overview: section S3 shows it in place of the 2D Energy Flow card, with the same nodes, today, format and layout settings (the
# 2D card's grid voltage, connection and frequency move to nodes.grid, where the 3D card reads them) and the ECCO status, scene
# and freshness settings of the owner-accepted ECCO 3D Preview. The card reads states only and opens Home Assistant's more-info
# dialogue; it calls no service. It loads through the Lovelace resource the preview already registered (no new resource, no new
# bundle copy). Every other section and view is unchanged. Display only: no control, firmware, package or automation change.
""")
DASHBOARD_1_OLD = _blk(r"""
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
                time_to_reserve: sensor.ecco_battery_time_to_reserve

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
              columns: full
              rows: auto
            card_mod:
              style: |
                ha-card {
                  border: 1px solid rgba(255,255,255,0.08);
                  box-shadow: 0 12px 32px rgba(0,0,0,0.22);
                }
""")
DASHBOARD_1_NEW = _blk(r"""
          # OVW3: the read-only ECCO 3D Energy Flow card (frontend/ecco-flow-3d-card, V2) in place of the 2D Energy Flow card. It
          # reads states and opens Home Assistant's more-info dialogue only: no service call, no write. Its Lovelace resource is the
          # one the ECCO 3D Preview dashboard already loads; the scene pack is the local /local/ecco/scenes/ folder. The 2D card's
          # nodes, today, format and grid layout settings are kept (its card_mod style is not: this card styles its own ha-card); its
          # grid voltage, connection and frequency are read from nodes.grid.
          - type: custom:ecco-flow-3d-card
            title: Energy Flow
            subtitle: Live power overview

            scene:
              pack: /local/ecco/scenes/
              crossfade_ms: 900

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
                time_to_reserve: sensor.ecco_battery_time_to_reserve

              grid:
                power: sensor.ecco_grid_power
                power_sign: import_positive
                connected: binary_sensor.ecco_clock_dongle_ecco_grid_connected
                voltage: sensor.ecco_clock_dongle_ecco_grid_voltage_l1
                frequency: sensor.ecco_clock_dongle_ecco_grid_frequency

            ecco:
              telemetry_online: binary_sensor.ecco_clock_dongle_telemetry_online
              sun: sun.sun
              weather: weather.forecast_home
              free_power:
                active: binary_sensor.ecco_clock_dongle_free_power_active
                status: sensor.ecco_clock_dongle_free_power_status
                ends_at: sensor.ecco_clock_dongle_free_power_ends_at
                schedule_status: sensor.ecco_free_power_schedule_status
              dump_to_grid:
                active: binary_sensor.ecco_clock_dongle_dump_to_grid_active
                status: sensor.ecco_clock_dongle_dump_to_grid_status
                ends_at: sensor.ecco_clock_dongle_dump_to_grid_ends_at
                schedule_status: sensor.ecco_dump_to_grid_schedule_status
                export_power: sensor.ecco_clock_dongle_dump_to_grid_active_export_power
                stop_soc: sensor.ecco_clock_dongle_dump_to_grid_active_stop_soc
              tou:
                slot_start_minutes:
                  - sensor.ecco_tou_slot_1_start_minute
                  - sensor.ecco_tou_slot_2_start_minute
                  - sensor.ecco_tou_slot_3_start_minute
                  - sensor.ecco_tou_slot_4_start_minute
                  - sensor.ecco_tou_slot_5_start_minute
                  - sensor.ecco_tou_slot_6_start_minute
                slot_target_soc:
                  - sensor.ecco_clock_dongle_ecco_timezone1_soc
                  - sensor.ecco_clock_dongle_ecco_timezone2_soc
                  - sensor.ecco_clock_dongle_ecco_timezone3_soc
                  - sensor.ecco_clock_dongle_ecco_timezone4_soc
                  - sensor.ecco_clock_dongle_ecco_timezone5_soc
                  - sensor.ecco_clock_dongle_ecco_timezone6_soc
                slot_charge_source:
                  - sensor.ecco_clock_dongle_ecco_timezone1_charge
                  - sensor.ecco_clock_dongle_ecco_timezone2_charge
                  - sensor.ecco_clock_dongle_ecco_timezone3_charge
                  - sensor.ecco_clock_dongle_ecco_timezone4_charge
                  - sensor.ecco_clock_dongle_ecco_timezone5_charge
                  - sensor.ecco_clock_dongle_ecco_timezone6_charge
                slot_power:
                  - sensor.ecco_clock_dongle_ecco_timezone1_power
                  - sensor.ecco_clock_dongle_ecco_timezone2_power
                  - sensor.ecco_clock_dongle_ecco_timezone3_power
                  - sensor.ecco_clock_dongle_ecco_timezone4_power
                  - sensor.ecco_clock_dongle_ecco_timezone5_power
                  - sensor.ecco_clock_dongle_ecco_timezone6_power
                valid: binary_sensor.ecco_tou_schedule_valid
              forecast:
                today: sensor.ecco_solar_forecast_today
                remaining: sensor.ecco_solar_forecast_remaining
                tomorrow: sensor.ecco_solar_forecast_tomorrow
              health:
                sensors:
                  - sensor.ecco_health_communications
                  - sensor.ecco_health_inverter_telemetry
                  - sensor.ecco_health_runtime_configuration
                  - sensor.ecco_health_configuration
                  - sensor.ecco_health_manual_write_system
                  - sensor.ecco_health_rtc
                  - sensor.ecco_health_free_power
                  - sensor.ecco_health_start_failures
                  - sensor.ecco_health_supervision
                  - sensor.ecco_health_fallback
                attention:
                  - binary_sensor.ecco_dump_limits_attention

            today:
              solar: sensor.ecco_clock_dongle_ecco_day_pv_energy
              load: sensor.ecco_clock_dongle_ecco_day_load_energy
              import: sensor.ecco_clock_dongle_ecco_day_grid_import
              export: sensor.ecco_clock_dongle_ecco_day_grid_export
              battery_charge: sensor.ecco_clock_dongle_ecco_day_battery_charge
              battery_discharge: sensor.ecco_clock_dongle_ecco_day_battery_discharge

            inverter_details:
              ac_temperature: sensor.ecco_clock_dongle_ecco_temperature_ac_transformer
              dc_temperature: sensor.ecco_clock_dongle_ecco_temperature_dc_transformer
              battery_temperature: sensor.ecco_clock_dongle_ecco_battery_temperature

            features:
              animate_flow: true
              show_status_panel: true
              show_details_panel: true
              stale_after_s: 180

            format:
              precision: 2
              energy_precision: 1
              power_unit: auto

            grid_options:
              columns: full
              rows: auto
""")
DASHBOARD_EDITS = (
    (DASHBOARD_0_OLD, DASHBOARD_0_NEW),
    (DASHBOARD_1_OLD, DASHBOARD_1_NEW),
)


def pre_ovw3_dashboard(text: str) -> str:
    """home-assistant/dashboards/ecco_pro.yaml with exactly ovw3's edits undone (a frozen reverter of chain entry ovw3, PEX)."""
    return _revert(text, DASHBOARD_EDITS, "home-assistant/dashboards/ecco_pro.yaml")


pre_ovw3_dashboard.edits = DASHBOARD_EDITS   # the PEX contract: a reverter exposes its exact (before, after) pairs


def add_ovw3_dashboard(text: str) -> str:
    """Applies ovw3's home-assistant/dashboards/ecco_pro.yaml edits to the earlier text (the round trip)."""
    return _apply(text, DASHBOARD_EDITS, "home-assistant/dashboards/ecco_pro.yaml")

# ---- (PEX frozen edit) VERSION.yaml --------------------------------------------------------------------------------------------------
VERSION_REL = "VERSION.yaml"
# Dashboard 7.22.0 -> 7.23.0 (staged); the 7.22.0 record is kept below the new note.
VERSION_0_OLD = _blk(r"""
    version: "7.22.0"
    path: home-assistant/dashboards/ecco_pro.yaml
""")
VERSION_0_NEW = _blk(r"""
    version: "7.23.0"
    path: home-assistant/dashboards/ecco_pro.yaml
    # v7.23.0 (OVW3) puts the read-only ECCO 3D Energy Flow card (V2) on the Overview in place of the 2D Energy Flow card,
    # with the same nodes, today, format and layout settings and the ECCO status, scene and freshness settings of the
    # owner-accepted ECCO 3D Preview. The card reads states only and calls no service; it loads through the Lovelace
    # resource the preview already registered (no new resource, no new bundle copy). It is STAGED:
    # tested_in_home_assistant stays false until the card is exercised on the production dashboard. The 7.22.0 record
    # follows.
""")
VERSION_EDITS = (
    (VERSION_0_OLD, VERSION_0_NEW),
)


def pre_ovw3_version(text: str) -> str:
    """VERSION.yaml with exactly ovw3's edits undone (a frozen reverter of chain entry ovw3, PEX)."""
    return _revert(text, VERSION_EDITS, "VERSION.yaml")


pre_ovw3_version.edits = VERSION_EDITS   # the PEX contract: a reverter exposes its exact (before, after) pairs


def add_ovw3_version(text: str) -> str:
    """Applies ovw3's VERSION.yaml edits to the earlier text (the round trip)."""
    return _apply(text, VERSION_EDITS, "VERSION.yaml")


# Every frozen file ovw3 edits, with its reverter (the chain entry's frozen_reverts).
FROZEN_REVERTERS = {
    DASHBOARD_REL: pre_ovw3_dashboard,
    VERSION_REL: pre_ovw3_version,
}
