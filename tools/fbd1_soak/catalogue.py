"""The firmware diagnostics the FB-D1 soak analyser understands, and how their Home Assistant entity ids are recognised.

Every entry names the firmware entity (`name:` in firmware/ecco_clock_dongle_stage3_4_free_power.yaml) and the HA object-id
suffix the ESPHome integration derives from it (`<domain>.<device slug>_<slugified name>`). The device slug is
`ecco_clock_dongle`; an installation may prefix it with an area (`<area>_ecco_clock_dongle_...`), so an id matches when its
object id ENDS WITH `ecco_clock_dongle_<suffix>` (anchored on both sides, so `last_correction` never matches
`last_correction_result`). `--entity KEY=entity_id` overrides any mapping.

kind:
  counter   monotonic within one boot (a "since boot" counter): a decrease is a restart signal
  maxboot   a "maximum since boot" value: also monotonic within one boot
  numeric   a plain measurement
  text      a text sensor (state strings)
  binary    on / off
  setting   an operator setting (number / switch / select)
"""

from __future__ import annotations

import re
from dataclasses import dataclass

DEVICE_SLUG = "ecco_clock_dongle"


@dataclass(frozen=True)
class Entity:
    key: str
    suffix: str
    domains: tuple
    kind: str
    firmware_name: str
    area: str
    witness_s: int = 0  # > 0: the entity normally produces a new HA row at least this often (an evidence-liveness witness)


def _e(key, suffix, domains, kind, name, area, witness_s=0):
    return Entity(key, suffix, tuple(domains.split()), kind, name, area, witness_s)


S, B, N, SW = "sensor", "binary_sensor", "number", "switch"

ENTITIES = (
    # RTC
    _e("clock_difference", "clock_difference", S, "numeric", "Clock Difference", "rtc"),
    _e("inverter_time", "inverter_time", S, "text", "Inverter Time", "rtc", 60),
    _e("ntp_time", "ntp_time", S, "text", "NTP Time", "continuity", 60),
    _e("ntp_synced", "ntp_synced", B, "binary", "NTP Synced", "rtc"),
    _e("verified_corrections", "verified_corrections_since_boot", S, "counter", "Verified Corrections Since Boot", "rtc"),
    _e("rtc_write_attempts", "rtc_write_attempts_since_boot", S, "counter", "RTC Write Attempts Since Boot", "safety"),
    _e("failed_corrections", "failed_corrections_since_boot", S, "counter", "Failed Corrections Since Boot", "rtc"),
    _e("rtc_stall_count", "rtc_stall_count", S, "counter", "RTC Stall Count", "rtc"),
    _e("max_clock_error", "maximum_clock_error_since_boot", S, "maxboot", "Maximum Clock Error Since Boot", "rtc"),
    _e("rtc_stall_detected", "rtc_stall_detected", B, "binary", "RTC Stall Detected", "rtc"),
    _e("rtc_correction_in_progress", "rtc_correction_in_progress", B, "binary", "RTC Correction In Progress", "rtc"),
    _e("last_correction", "last_correction", S, "text", "Last Correction", "rtc"),
    _e("last_correction_result", "last_correction_result", S, "text", "Last Correction Result", "rtc"),
    _e("correction_lock_age", "ecco_rtc_correction_lock_age", S, "numeric", "ECCO RTC Correction Lock Age", "rtc"),
    _e("correction_lock_max", "ecco_rtc_correction_lock_max_age_since_boot", S, "maxboot",
       "ECCO RTC Correction Lock Max Age Since Boot", "rtc"),
    _e("correction_threshold", "clock_correction_threshold", N, "setting", "Clock Correction Threshold", "rtc"),
    _e("automatic_clock_sync", "automatic_clock_sync", SW, "setting", "Automatic Clock Sync", "rtc"),
    # Modbus / polling
    _e("telemetry_failures", "telemetry_read_failures_since_boot", S, "counter", "Telemetry Read Failures Since Boot", "polling"),
    _e("configuration_failures", "configuration_read_failures_since_boot", S, "counter",
       "Configuration Read Failures Since Boot", "polling"),
    _e("telemetry_online", "telemetry_online", B, "binary", "Telemetry Online", "polling"),
    _e("configuration_online", "configuration_online", B, "binary", "Configuration Online", "polling"),
    _e("last_telemetry_update", "last_telemetry_update", S, "text", "Last Telemetry Update", "polling", 10),
    _e("last_configuration_update", "last_configuration_update", S, "text", "Last Configuration Update", "polling", 60),
    _e("configuration_polling", "read_only_configuration_polling", SW, "setting", "Read-Only Configuration Polling", "polling"),
    _e("write_lock_age", "ecco_modbus_write_lock_age", S, "numeric", "ECCO Modbus Write Lock Age", "safety"),
    _e("write_lock_max", "ecco_modbus_write_lock_max_age_since_boot", S, "maxboot",
       "ECCO Modbus Write Lock Max Age Since Boot", "safety"),
    # B10
    _e("b10", "ecco_fallback_profile_live_match", S, "text", "ECCO Fallback Profile Live Match", "b10"),
    _e("profile_state", "ecco_fallback_profile_state", S, "text", "ECCO Fallback Profile State", "supervision"),
    # supervision / continuity
    _e("supervision_state", "ecco_supervision_state", S, "text", "ECCO Supervision State", "supervision"),
    _e("supervision_stable", "ecco_supervision_stable", B, "binary", "ECCO Supervision Stable", "supervision"),
    _e("supervision_challenge", "ecco_supervision_challenge", S, "text", "ECCO Supervision Challenge", "continuity"),
    _e("valid_heartbeats", "ecco_supervision_valid_heartbeat_count", S, "counter", "ECCO Supervision Valid Heartbeat Count",
       "continuity", 60),
    _e("invalid_heartbeats", "ecco_supervision_invalid_heartbeat_count", S, "counter",
       "ECCO Supervision Invalid Heartbeat Count", "supervision"),
    _e("suspect_events", "ecco_supervision_suspect_events", S, "counter", "ECCO Supervision Suspect Events", "supervision"),
    _e("lost_events", "ecco_supervision_lost_events", S, "counter", "ECCO Supervision Lost Events", "supervision"),
    _e("heartbeat_age", "ecco_supervision_heartbeat_age", S, "numeric", "ECCO Supervision Heartbeat Age", "continuity", 60),
    _e("reset_reason", "ecco_reset_reason", S, "text", "ECCO Reset Reason", "continuity"),
    _e("wifi_signal", "wifi_signal", S, "numeric", "WiFi Signal", "continuity", 120),
    _e("shadow_state", "ecco_failback_shadow_state", S, "text", "ECCO Failback Shadow State", "supervision"),
    _e("inverter_warning", "ecco_inverter_warning", S, "text", "ECCO Inverter Warning", "supervision"),
    _e("inverter_fault", "ecco_inverter_fault", S, "text", "ECCO Inverter Fault", "supervision"),
    # safety / write authority
    _e("manual_write_attempts", "manual_configuration_write_attempts_since_boot", S, "counter",
       "Manual Configuration Write Attempts Since Boot", "safety"),
    _e("manual_write_successes", "manual_configuration_write_successes_since_boot", S, "counter",
       "Manual Configuration Write Successes Since Boot", "safety"),
    _e("manual_write_failures", "manual_configuration_write_failures_since_boot", S, "counter",
       "Manual Configuration Write Failures Since Boot", "safety"),
    _e("fp_start_attempts", "free_power_start_attempts_since_boot", S, "counter", "Free Power Start Attempts Since Boot", "safety"),
    _e("fp_start_successes", "free_power_start_successes_since_boot", S, "counter", "Free Power Start Successes Since Boot",
       "safety"),
    _e("fp_restore_successes", "free_power_restore_successes_since_boot", S, "counter",
       "Free Power Restore Successes Since Boot", "safety"),
    _e("fp_failures", "free_power_failures_since_boot", S, "counter", "Free Power Failures Since Boot", "safety"),
    _e("dtg_start_attempts", "dump_to_grid_start_attempts_since_boot", S, "counter", "Dump to Grid Start Attempts Since Boot",
       "safety"),
    _e("dtg_start_successes", "dump_to_grid_start_successes_since_boot", S, "counter",
       "Dump to Grid Start Successes Since Boot", "safety"),
    _e("dtg_restore_successes", "dump_to_grid_restore_successes_since_boot", S, "counter",
       "Dump to Grid Restore Successes Since Boot", "safety"),
    _e("dtg_failures", "dump_to_grid_failures_since_boot", S, "counter", "Dump to Grid Failures Since Boot", "safety"),
    _e("free_power_active", "free_power_active", B, "binary", "Free Power Active", "safety"),
    _e("dump_active", "dump_to_grid_active", B, "binary", "Dump to Grid Active", "safety"),
    _e("free_power_op", "free_power_operation_in_progress", B, "binary", "Free Power Operation In Progress", "safety"),
    _e("dump_op", "dump_to_grid_operation_in_progress", B, "binary", "Dump to Grid Operation In Progress", "safety"),
    _e("manual_write_in_progress", "manual_write_in_progress", B, "binary", "Manual Write In Progress", "safety"),
    _e("manual_write_enable", "manual_configuration_write_enable", SW, "setting", "Manual Configuration Write Enable", "safety"),
    _e("free_power_write_enable", "free_power_write_enable", SW, "setting", "Free Power Write Enable", "safety"),
    _e("dump_write_enable", "dump_to_grid_write_enable", SW, "setting", "Dump to Grid Write Enable", "safety"),
    # protected inverter control state (read back by the configuration poll)
    _e("tou_enabled", "ecco_time_of_use_enabled", B, "binary", "ECCO Time Of Use Enabled", "safety"),
    _e("grid_charge_enabled", "ecco_battery_grid_charge_enabled", B, "binary", "ECCO Battery Grid Charge Enabled", "safety"),
    _e("export_solar_enabled", "ecco_export_solar_enabled", B, "binary", "ECCO Export Solar Enabled", "safety"),
    _e("tou1_time", "ecco_timezone1_time", S, "text", "ECCO Timezone1 Time", "safety"),
    _e("tou2_time", "ecco_timezone2_time", S, "text", "ECCO Timezone2 Time", "safety"),
    _e("tou3_time", "ecco_timezone3_time", S, "text", "ECCO Timezone3 Time", "safety"),
    _e("tou4_time", "ecco_timezone4_time", S, "text", "ECCO Timezone4 Time", "safety"),
    _e("tou5_time", "ecco_timezone5_time", S, "text", "ECCO Timezone5 Time", "safety"),
    _e("tou6_time", "ecco_timezone6_time", S, "text", "ECCO Timezone6 Time", "safety"),
    # context
    _e("pv_power", "ecco_pv_power", S, "numeric", "ECCO PV Power", "rtc"),
)

BY_KEY = {e.key: e for e in ENTITIES}
TOU_KEYS = tuple(f"tou{i}_time" for i in range(1, 7))
PROTECTED_KEYS = ("tou_enabled", "grid_charge_enabled", "export_solar_enabled") + TOU_KEYS
SETTING_KEYS = tuple(e.key for e in ENTITIES if e.kind == "setting")
MONOTONIC_KEYS = tuple(e.key for e in ENTITIES if e.kind in ("counter", "maxboot"))
WITNESS_KEYS = tuple(e.key for e in ENTITIES if e.witness_s > 0)

_ENTITY_ID = re.compile(r"^([a-z_]+)\.([a-z0-9_]+)$")
_MATCHERS = tuple(
    (e, re.compile(r"^(?:[a-z0-9_]*_)?" + DEVICE_SLUG + "_" + re.escape(e.suffix) + r"$")) for e in ENTITIES)


def slugify(name: str) -> str:
    """Home Assistant's object-id slug of an entity name (lower case, every non-alphanumeric run -> one underscore)."""
    return re.sub(r"_+", "_", re.sub(r"[^a-z0-9]", "_", name.lower())).strip("_")


def match(entity_id: str, overrides: dict | None = None) -> str | None:
    """The catalogue key of a Home Assistant entity id, or None when it is not an FB-D1 diagnostic this analyser reads."""
    if overrides:
        for key, eid in overrides.items():
            if eid == entity_id:
                return key
    m = _ENTITY_ID.match(entity_id or "")
    if not m:
        return None
    domain, obj = m.groups()
    for e, rx in _MATCHERS:
        if domain in e.domains and rx.match(obj):
            if overrides and e.key in overrides:
                return None  # the operator mapped this key to another entity id explicitly
            return e.key
    return None
