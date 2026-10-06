"""FB-D1 (RTC / polling / liveness hardening) change scope: exactly what FB-D1 changes in
firmware/ecco_clock_dongle_stage3_4_free_power.yaml, and its exact inverse.

Same technique as _fbc2_scope.py / _fbb3_scope.py: the verbatim edits are held HERE as the single source of truth, as exact
(before, after) pairs, and a reverter raises unless every edit is present exactly once. The chain entry `fbd1`
(registry/tests/_scope_chain.py) carries `pre_fbd1_firmware`: the current firmware text with exactly these edits removed, which
reproduces the FB-C2 firmware byte-for-byte (BASE_FW_SHA = the chain's fbc2 checkpoint; FB-C3, the chain entry before fbd1, does not
touch the firmware).
The older suites are anchored at their own entries and revert fbd1 FIRST; none of them was re-hashed.

FB-D1 adds NO Modbus operation (64 reads / 52 writes unchanged), NO script, button, switch, number, select, sensor, text sensor
or api action, NO durable record and NO new authority. It edits the firmware in twelve places:

  includes       include/ecco_rtc_policy.h (the pure RTC policy / deadline header), appended last
  globals        the FB-D1 RAM state (every one `restore_value: no`)
  write_inverter_rtc   D1a: on_not_sent / on_custom_response on the FC16 22-24 write fail into the existing bounded retry path;
                 the NTP-abort branch releases the correction (it only logged and leaked correction_in_progress)
  poll_inverter_telemetry   D1b: on_custom_response / on_not_sent on both blocks; block 150-196 is queued only if the write
                 path is still unowned in the same loop pass (nested `if`, the block re-indented by 6)
  poll_inverter_configuration_dispatch   D1b / D1c: on_custom_response / on_not_sent on Blocks A / B with the unified
                 invalidation rule (the bodies of the existing on_error / on_no_response) and on Block C (display only:
                 failure count only); Block B (with the dispatch stamp)
                 and Block C are queued only if the write path is still unowned in the same loop pass (nested `if`s, the
                 blocks re-indented by 6 / 12); a yield before Block B stamps nothing, changes no cache flag and owes a poll
  read_inverter_clock   D1a: on_not_sent (attributed to the verification press by rtc_verify_dispatching) / on_custom_response;
                 the previous regular read is captured for the policy; the automatic queue is ecco_rtc::decide()
  sync_inverter_clock   the deadline clock is stamped where the manual correction takes the lock
  interval       a new 2 s configuration poll catch-up interval (after the 60 s configuration interval); the 1 s RTC interval
                 gains a first lambda (progress-flag invariant gate, the deadline breaker - it releases only when no RTC frame
                 can be outstanding -, the lock-release edge that owes two
                 configuration polls), dispatches a queued write only on a quiet bus, and marks / requires the lock for the
                 verification press

Nothing in the deployment manifest, the Home Assistant packages or the firmware's other YAML files changes.

This module imports no other scope module and not _scope_chain (the chain imports it). No I/O.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

# main FB-D1 is based on (FB-C3 merged as PR #65 on FB-C2 / PR #63 + PR #64); FB-C3 edits no firmware, so the firmware there is still
# the chain's fbc2 checkpoint.
BASE_COMMIT = "21238b5118ff6187b134a0d289259b5ee3ae86e9"
FIRMWARE_REL = "firmware/ecco_clock_dongle_stage3_4_free_power.yaml"
# sha256 (LF text, as Path.read_text returns it) of the firmware YAML at BASE_COMMIT: what pre_fbd1_firmware() must reproduce;
# equal to the chain's fbc2 checkpoint.
BASE_FW_SHA = "592c25a21095d63342b1ab08531af494db2ad04bb2df13c66f57f95bc45595d7"

_BANNED = re.compile(r"ecco_fallback|FALLBACK_PROFILE|FAILBACK_STATE|ecco_failback")

ADDED_FILES = frozenset({
    "docs/architecture/fallback/FB_D1_IMPLEMENTATION_NOTES.md",
    "firmware/include/ecco_rtc_policy.h",
    "registry/rtc_policy.py",
    "registry/tests/_fbd1_harness.py",
    "registry/tests/_fbd1_scope.py",
    "registry/tests/test_fbd1_liveness.py",
    "registry/tests/test_rtc_policy.py",
})

HEADER_REL = "firmware/include/ecco_rtc_policy.h"
INCLUDE_ENTRY = "include/ecco_rtc_policy.h"

# The FB-D1 RAM globals, in declaration order (single source of truth for the suites).
NEW_GLOBAL_SPECS = (
    # id, type, initial
    ("rtc_txn_since_ms", "uint32_t", "0"),
    ("rtc_verify_dispatching", "bool", "false"),
    ("rtc_lock_seen", "bool", "false"),
    ("rtc_prev_err_s", "int32_t", "0"),
    ("rtc_have_last_auto", "bool", "false"),
    ("rtc_last_auto_ms", "uint32_t", "0"),
    ("rtc_precision_served", "uint32_t", "0"),
    ("rtc_boot_aligned", "bool", "false"),
    ("rtc_policy_reason", "uint8_t", "0"),
    ("cfg_poll_owed", "uint8_t", "0"),
)
NEW_GLOBAL_IDS = tuple(s[0] for s in NEW_GLOBAL_SPECS)

# The ownership predicate every FB-D1 poll re-check uses: the configuration dispatch's existing entry guard, verbatim.
OWNER_FREE = "return !id(manual_write_in_progress) && !id(correction_in_progress);"


def _blk(s: str) -> str:
    """A raw triple-quoted literal that starts on the line after the opening quotes: drops that first newline."""
    assert s.startswith("\n") and s.endswith("\n") and "\r" not in s
    return s[1:]


def _indent(s: str, n: int) -> str:
    """Every non-empty line indented by n spaces (blank lines stay empty)."""
    return "".join((" " * n + line) if line.strip() else line for line in s.splitlines(keepends=True))


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ---- 1. includes -------------------------------------------------------------------------------------------------------------
INCLUDES_OLD = "    - include/ecco_failback_shadow.h\n\n  on_boot:\n"
INCLUDES_NEW = "    - include/ecco_failback_shadow.h\n    - " + INCLUDE_ENTRY + "\n\n  on_boot:\n"

# ---- 2. globals --------------------------------------------------------------------------------------------------------------
GLOBALS_OLD = _blk(r"""
  - id: configuration_block1_ok
    type: bool
    restore_value: no
    initial_value: 'false'

  # Stage 3.3 manual TOU control - raw cache and verification state
""")


def _globals_block() -> str:
    out = [_blk(r"""
  # ---------------------------------------------------------------------
  # FB-D1 RTC / poll liveness - RAM-only state (restore_value: no). No
  # durable record, no write basis, no new authority.
  #   rtc_txn_since_ms        millis() when the current RTC correction took
  #                           correction_in_progress (the deadline breaker clock)
  #   rtc_verify_dispatching  true only while the 1 s RTC tick presses Read
  #                           Inverter Clock for a verification read, so a
  #                           synchronous on_not_sent is attributed to it
  #   rtc_lock_seen           correction_in_progress as the 1 s RTC tick last saw it
  #   rtc_prev_err_s          the full error of the previous regular RTC read
  #                           (meaningful while have_rtc_baseline)
  #   rtc_have_last_auto / rtc_last_auto_ms   the last automatic correction queued
  #   rtc_precision_served    the TOU zone start a precision correction was last
  #                           queued for (ecco_rtc::precision_key)
  #   rtc_boot_aligned        the one post-boot alignment to the threshold is done
  #   rtc_policy_reason       the last ecco_rtc::decide() reason (diagnostic)
  #   cfg_poll_owed           configuration polls owed (0-2): 1 when a poll yielded
  #                           Block B to a write-path owner, 2 when an RTC correction
  #                           released its lock; run by the catch-up interval
  # ---------------------------------------------------------------------
""")]
    for gid, gtype, init in NEW_GLOBAL_SPECS:
        out.append(f"  - id: {gid}\n    type: {gtype}\n    restore_value: no\n    initial_value: '{init}'\n")
    return "".join(out)


GLOBALS_NEW = GLOBALS_OLD.split("\n  # Stage 3.3 manual TOU control", 1)[0] + "\n" + _globals_block() + \
    "\n  # Stage 3.3 manual TOU control - raw cache and verification state\n"

# ---- 3. write_inverter_rtc: write handlers and the NTP-abort release (D1a) ---------------------------------------------------
RTC_WRITE_OLD = _blk(r"""
                              ESP_LOGW("ecco", "No response to RTC write");
                              id(verification_pending) = false;
                              id(verification_read_active) = false;
                              id(comm_failure_pending) = true;
                              id(last_correction_result).publish_state("No response to write - processing retry");
                else:
                  - logger.log:
                      level: WARN
                      format: "RTC sync aborted - confirmed NTP time unavailable"
""")
RTC_WRITE_NEW = _blk(r"""
                              ESP_LOGW("ecco", "No response to RTC write");
                              id(verification_pending) = false;
                              id(verification_read_active) = false;
                              id(comm_failure_pending) = true;
                              id(last_correction_result).publish_state("No response to write - processing retry");
                      # FB-D1 (D1a): the two remaining terminal outcomes. A queue refusal fires on_not_sent synchronously inside
                      # this script; a non-standard echo is never an acknowledgement. Both fail into the existing bounded retry
                      # path (the 1 s tick: one retry, then FAILED + cooldown), exactly like on_error / on_no_response.
                      on_not_sent:
                        then:
                          - lambda: |-
                              ESP_LOGW("ecco", "RTC write was not queued - processing retry");
                              id(verification_pending) = false;
                              id(verification_read_active) = false;
                              id(comm_failure_pending) = true;
                              id(last_correction_result).publish_state("Write not sent - processing retry");
                      on_custom_response:
                        then:
                          - lambda: |-
                              ESP_LOGW("ecco", "Non-standard reply to RTC write (%u bytes) - processing retry", (unsigned) response.size());
                              id(verification_pending) = false;
                              id(verification_read_active) = false;
                              id(comm_failure_pending) = true;
                              id(last_correction_result).publish_state("Non-standard write reply - processing retry");
                else:
                  # FB-D1 (D1a): NTP is not confirmed at the final dispatch point - nothing is written, so this is the 1 s
                  # tick's CANCEL (no failure count, no cooldown). It used to only log and leaked correction_in_progress.
                  - lambda: |-
                      id(correction_in_progress) = false;
                      id(correction_is_manual) = false;
                      id(correction_attempt) = 0;
                      id(verification_pending) = false;
                      id(verification_read_active) = false;
                      id(auto_sync_pending) = false;
                      id(comm_failure_pending) = false;
                      id(last_correction_result).publish_state("Correction cancelled - confirmed NTP time unavailable");
                  - logger.log:
                      level: WARN
                      format: "RTC sync aborted - confirmed NTP time unavailable"
""")

# ---- 4. poll_inverter_telemetry (D1b) ----------------------------------------------------------------------------------------
TLM_OLD = _blk(r"""
                  ESP_LOGW("telemetry", "No response to telemetry block 59-116");

      - delay: 2500ms

      - modbus_client.read_holding_registers:
          modbus_id: inverter_modbus
          address: 0x01
          start_address: 150
          count: 47
          on_response:
            then:
              - lambda: |-
                  id(ecco_grid_voltage_l1).publish_state(values[0] * 0.1f);
                  id(ecco_grid_voltage_l2).publish_state(values[1] * 0.1f);
                  id(ecco_grid_voltage_l1_l2).publish_state(values[2] * 0.1f);
                  id(ecco_mid_relay_voltage).publish_state(values[3] * 0.1f);

                  id(ecco_inverter_voltage_l1).publish_state(values[4] * 0.1f);
                  id(ecco_inverter_voltage_l2).publish_state(values[5] * 0.1f);
                  id(ecco_inverter_voltage_l1_l2).publish_state(values[6] * 0.1f);

                  id(ecco_load_voltage_l1).publish_state(values[7] * 0.1f);
                  id(ecco_load_voltage_l2).publish_state(values[8] * 0.1f);

                  id(ecco_grid_current_l1).publish_state(static_cast<int16_t>(values[10]) * 0.01f);
                  id(ecco_grid_current_l2).publish_state(static_cast<int16_t>(values[11]) * 0.01f);
                  id(ecco_grid_external_current_l1).publish_state(static_cast<int16_t>(values[12]) * 0.01f);
                  id(ecco_grid_external_current_l2).publish_state(static_cast<int16_t>(values[13]) * 0.01f);

                  id(ecco_inverter_current_l1).publish_state(static_cast<int16_t>(values[14]) * 0.01f);
                  id(ecco_inverter_current_l2).publish_state(static_cast<int16_t>(values[15]) * 0.01f);

                  id(ecco_generator_power).publish_state(static_cast<int16_t>(values[16]));

                  id(ecco_grid_power_l1).publish_state(static_cast<int16_t>(values[17]));
                  id(ecco_grid_power_l2).publish_state(static_cast<int16_t>(values[18]));
                  id(ecco_grid_power).publish_state(static_cast<int16_t>(values[19]));

                  id(ecco_grid_ct_power_l1).publish_state(static_cast<int16_t>(values[20]));
                  id(ecco_grid_ct_power_l2).publish_state(static_cast<int16_t>(values[21]));
                  id(ecco_grid_ct_power).publish_state(static_cast<int16_t>(values[22]));

                  id(ecco_inverter_power_l1).publish_state(static_cast<int16_t>(values[23]));
                  id(ecco_inverter_power_l2).publish_state(static_cast<int16_t>(values[24]));
                  id(ecco_inverter_power).publish_state(static_cast<int16_t>(values[25]));

                  id(ecco_load_power_l1).publish_state(static_cast<int16_t>(values[26]));
                  id(ecco_load_power_l2).publish_state(static_cast<int16_t>(values[27]));
                  id(ecco_load_power).publish_state(static_cast<int16_t>(values[28]));

                  id(ecco_load_current_l1).publish_state(static_cast<int16_t>(values[29]) * 0.01f);
                  id(ecco_load_current_l2).publish_state(static_cast<int16_t>(values[30]) * 0.01f);

                  id(ecco_battery_temperature).publish_state(
                    (static_cast<int16_t>(values[32]) - 1000) * 0.1f
                  );
                  id(ecco_battery_voltage).publish_state(values[33] * 0.01f);
                  id(ecco_battery_soc).publish_state(values[34]);

                  float pv1 = static_cast<int16_t>(values[36]);
                  float pv2 = static_cast<int16_t>(values[37]);
                  float pv3 = static_cast<int16_t>(values[38]);
                  float pv4 = static_cast<int16_t>(values[39]);
                  id(ecco_pv1_power).publish_state(pv1);
                  id(ecco_pv2_power).publish_state(pv2);
                  id(ecco_pv3_power).publish_state(pv3);
                  id(ecco_pv4_power).publish_state(pv4);
                  id(ecco_pv_power).publish_state(pv1 + pv2 + pv3 + pv4);

                  id(ecco_battery_power).publish_state(static_cast<int16_t>(values[40]));
                  id(ecco_battery_current).publish_state(static_cast<int16_t>(values[41]) * 0.01f);

                  id(ecco_load_frequency).publish_state(values[42] * 0.01f);
                  id(ecco_inverter_frequency).publish_state(values[43] * 0.01f);

                  id(ecco_grid_connected).publish_state(values[44] != 0);
                  id(ecco_generator_connected).publish_state((values[45] & 0x000F) != 0);

                  id(telemetry_online).publish_state(true);
                  auto now = id(ntp_time).now();
                  if (now.is_valid()) {
                    id(last_telemetry_update).publish_state(now.strftime("%Y-%m-%d %H:%M:%S"));
                  }
          on_error:
            then:
              - lambda: |-
                  id(telemetry_failures)++;
                  id(telemetry_online).publish_state(false);
                  ESP_LOGW(
                    "telemetry",
                    "Telemetry block 150-196 Modbus exception: 0x%02X",
                    (uint8_t) exception_code
                  );
          on_no_response:
            then:
              - lambda: |-
                  id(telemetry_failures)++;
                  id(telemetry_online).publish_state(false);
                  ESP_LOGW("telemetry", "No response to telemetry block 150-196");
""")
_TLM_T1_TAIL = '                  ESP_LOGW("telemetry", "No response to telemetry block 59-116");\n'
_TLM_DELAY = "\n      - delay: 2500ms\n\n"
assert TLM_OLD.startswith(_TLM_T1_TAIL + _TLM_DELAY)
_TLM_T2 = TLM_OLD[len(_TLM_T1_TAIL + _TLM_DELAY):]
assert _TLM_T2.startswith("      - modbus_client.read_holding_registers:\n          modbus_id: inverter_modbus\n          address: 0x01\n"
                          "          start_address: 150\n")

_TLM_T1_HANDLERS = _blk(r"""
          on_custom_response:
            then:
              - lambda: |-
                  id(telemetry_failures)++;
                  ESP_LOGW("telemetry", "Non-standard reply to telemetry block 59-116 (%u bytes)", (unsigned) response.size());
          on_not_sent:
            then:
              - lambda: |-
                  id(telemetry_failures)++;
                  ESP_LOGW("telemetry", "Telemetry block 59-116 was not sent");
""")
_TLM_T2_HANDLERS = _blk(r"""
          on_custom_response:
            then:
              - lambda: |-
                  id(telemetry_failures)++;
                  id(telemetry_online).publish_state(false);
                  ESP_LOGW("telemetry", "Non-standard reply to telemetry block 150-196 (%u bytes)", (unsigned) response.size());
          on_not_sent:
            then:
              - lambda: |-
                  id(telemetry_failures)++;
                  id(telemetry_online).publish_state(false);
                  ESP_LOGW("telemetry", "Telemetry block 150-196 was not sent");
""")
_TLM_GUARD_HEAD = _blk(r"""
      # FB-D1 (D1b): re-check write-path ownership in the same loop pass that queues block 150-196. An owner that took its
      # lock (or an RTC correction that started) during the delay above gets no telemetry frame inside its transaction; the
      # next 10 s poll reads again (no catch-up: SOC / grid stay well inside their 90 s staleness bounds).
      - if:
          condition:
            lambda: |-
              return !id(manual_write_in_progress) && !id(correction_in_progress);
          then:
""")
_TLM_GUARD_ELSE = _blk(r"""
          else:
            - lambda: |-
                ESP_LOGD("telemetry", "Telemetry block 150-196 skipped - inverter write path owned by another transaction");
""")
TLM_NEW = (_TLM_T1_TAIL + _TLM_T1_HANDLERS + _TLM_DELAY + _TLM_GUARD_HEAD + _indent(_TLM_T2 + _TLM_T2_HANDLERS, 6)
           + _TLM_GUARD_ELSE)

# ---- 5. poll_inverter_configuration_dispatch (D1b / D1c) ---------------------------------------------------------------------
CFG_OLD = _blk(r"""
                        ESP_LOGW("config", "No response to configuration block 200-240");

            - delay: 2500ms

            # 2026-09-26 adversarial review (B1): stamp the dispatch
            # generation immediately before Block B is sent - see
            # cfg_block_b_dispatch_seq's own comment.
            - lambda: 'id(cfg_block_b_dispatch_seq)++;'

            # Block B: energy management / TOU / grid protection
            # Registers 241-293 inclusive
            - modbus_client.read_holding_registers:
                modbus_id: inverter_modbus
                address: 0x01
                start_address: 241
                count: 53
                on_response:
                  then:
                    - lambda: |-
                        id(ecco_cfg_smart_load_power).publish_state(values[0]);

                        // Register 242 - Gen_Grid_Signal_On flags.
                        // Bit0 = grid signal, bit1 = generator signal.
                        uint16_t signal_flags = values[1];
                        id(ecco_cfg_gen_grid_signal_raw).publish_state(signal_flags);
                        id(ecco_grid_signal).publish_state(
                          (signal_flags & 0x0001) ? "Enable" : "Disable"
                        );
                        id(ecco_generator_signal).publish_state(
                          (signal_flags & 0x0002) ? "Enable" : "Disable"
                        );

                        switch (values[2]) {
                          case 0: id(ecco_energy_management_model).publish_state("Battery First Mode"); break;
                          case 1: id(ecco_energy_management_model).publish_state("Load First Mode"); break;
                          default: {
                            char b[32]; snprintf(b, sizeof(b), "Unknown (%u)", values[2]);
                            id(ecco_energy_management_model).publish_state(b);
                            break;
                          }
                        }

                        switch (values[3]) {
                          case 0: id(ecco_load_limit).publish_state("Allow Export"); break;
                          case 1: id(ecco_load_limit).publish_state("Essentials"); break;
                          case 2: id(ecco_load_limit).publish_state("Zero Export"); break;
                          default: {
                            char b[32]; snprintf(b, sizeof(b), "Unknown (%u)", values[3]);
                            id(ecco_load_limit).publish_state(b);
                            break;
                          }
                        }
                        id(manual_cfg_reg244_raw) = values[3];

                        // 2026-09-24 hardening (PR-A, Part 14): PASSIVE
                        // diagnostic only - compares this poll's live
                        // register 244 reading against the durable/RAM Free
                        // Power lease context and publishes a
                        // human-readable text sensor. DISPLAY/LOG ONLY: it
                        // writes no Modbus, commits no flash record, and
                        // never sets restore_requested/operator_needed/
                        // context_hold or touches the marker or starts a
                        // restore - no safety decision may depend on it.
                        // This poll can be disabled (Read-Only Configuration
                        // Polling switch) or delayed without affecting any
                        // Free Power safety gate - those all perform their
                        // own dedicated fresh reads (see
                        // restore_free_power_snapshot_dispatch).
                        if (!id(free_power_snapshot_valid)) {
                          id(free_power_reg244_context_diagnostic).publish_state("NONE");
                        } else if (id(free_power_lease_context_reg244) < 0) {
                          id(free_power_reg244_context_diagnostic).publish_state("LEASE CONTEXT UNKNOWN");
                        } else if ((int) values[3] == id(free_power_lease_context_reg244)) {
                          id(free_power_reg244_context_diagnostic).publish_state("MATCHES LEASE");
                        } else {
                          id(free_power_reg244_context_diagnostic).publish_state("DIFFERS FROM LEASE");
                          ESP_LOGW("free_power", "Passive diagnostic: live register 244 (%u) differs from the Free Power lease context (%d) - config-poll diagnostic only, not a safety check", values[3], id(free_power_lease_context_reg244));
                        }

                        id(ecco_cfg_export_limit).publish_state(values[4]);
                        id(ecco_export_solar_enabled).publish_state((values[6] & 0x0001) != 0);
                        id(ecco_time_of_use_enabled).publish_state((values[7] & 0x0001) != 0);

                        auto format_time = [](uint16_t raw) -> std::string {
                          int hh = raw / 100;
                          int mm = raw % 100;
                          char t[8];
                          if (hh > 23 || mm > 59) {
                            snprintf(t, sizeof(t), "?%u", raw);
                          } else {
                            snprintf(t, sizeof(t), "%02d:%02d", hh, mm);
                          }
                          return std::string(t);
                        };

                        id(ecco_tou1_time).publish_state(format_time(values[9]));
                        id(ecco_tou2_time).publish_state(format_time(values[10]));
                        id(ecco_tou3_time).publish_state(format_time(values[11]));
                        id(ecco_tou4_time).publish_state(format_time(values[12]));
                        id(ecco_tou5_time).publish_state(format_time(values[13]));
                        id(ecco_tou6_time).publish_state(format_time(values[14]));

                        id(ecco_tou1_power).publish_state(values[15]);
                        id(ecco_tou2_power).publish_state(values[16]);
                        id(ecco_tou3_power).publish_state(values[17]);
                        id(ecco_tou4_power).publish_state(values[18]);
                        id(ecco_tou5_power).publish_state(values[19]);
                        id(ecco_tou6_power).publish_state(values[20]);

                        id(ecco_tou1_voltage).publish_state(values[21] * 0.01f);
                        id(ecco_tou2_voltage).publish_state(values[22] * 0.01f);
                        id(ecco_tou3_voltage).publish_state(values[23] * 0.01f);
                        id(ecco_tou4_voltage).publish_state(values[24] * 0.01f);
                        id(ecco_tou5_voltage).publish_state(values[25] * 0.01f);
                        id(ecco_tou6_voltage).publish_state(values[26] * 0.01f);

                        id(ecco_tou1_soc).publish_state(values[27]);
                        id(ecco_tou2_soc).publish_state(values[28]);
                        id(ecco_tou3_soc).publish_state(values[29]);
                        id(ecco_tou4_soc).publish_state(values[30]);
                        id(ecco_tou5_soc).publish_state(values[31]);
                        id(ecco_tou6_soc).publish_state(values[32]);

                        auto charge_source = [](uint16_t raw) -> std::string {
                          switch (raw & 0x0003) {
                            case 0: return std::string("None");
                            case 1: return std::string("Grid");
                            case 2: return std::string("Generator");
                            case 3: return std::string("Grid + Generator");
                          }
                          return std::string("Unknown");
                        };

                        auto tou_mode = [](uint16_t raw) -> std::string {
                          switch (raw & 0x001C) {
                            case 0x00: return std::string("None");
                            case 0x04: return std::string("General");
                            case 0x08: return std::string("Backup");
                            case 0x10: return std::string("Charge");
                            default: {
                              char b[24];
                              snprintf(b, sizeof(b), "Unknown 0x%02X", raw & 0x001C);
                              return std::string(b);
                            }
                          }
                        };

                        id(ecco_tou1_charge).publish_state(charge_source(values[33]));
                        id(ecco_tou2_charge).publish_state(charge_source(values[34]));
                        id(ecco_tou3_charge).publish_state(charge_source(values[35]));
                        id(ecco_tou4_charge).publish_state(charge_source(values[36]));
                        id(ecco_tou5_charge).publish_state(charge_source(values[37]));
                        id(ecco_tou6_charge).publish_state(charge_source(values[38]));

                        id(ecco_tou1_mode).publish_state(tou_mode(values[33]));
                        id(ecco_tou2_mode).publish_state(tou_mode(values[34]));
                        id(ecco_tou3_mode).publish_state(tou_mode(values[35]));
                        id(ecco_tou4_mode).publish_state(tou_mode(values[36]));
                        id(ecco_tou5_mode).publish_state(tou_mode(values[37]));
                        id(ecco_tou6_mode).publish_state(tou_mode(values[38]));

                        // Cache the complete six-slot TOU write surface for Stage 3.3.
                        id(manual_cfg_reg250_raw) = values[9];
                        id(manual_cfg_reg251_raw) = values[10];
                        id(manual_cfg_reg252_raw) = values[11];
                        id(manual_cfg_reg253_raw) = values[12];
                        id(manual_cfg_reg254_raw) = values[13];
                        id(manual_cfg_reg255_raw) = values[14];
                        id(manual_cfg_reg256_raw) = values[15];
                        id(manual_cfg_reg257_raw) = values[16];
                        id(manual_cfg_reg258_raw) = values[17];
                        id(manual_cfg_reg259_raw) = values[18];
                        id(manual_cfg_reg260_raw) = values[19];
                        id(manual_cfg_reg261_raw) = values[20];
                        id(manual_cfg_reg268_raw) = values[27];
                        id(manual_cfg_reg269_raw) = values[28];
                        id(manual_cfg_reg270_raw) = values[29];
                        id(manual_cfg_reg271_raw) = values[30];
                        id(manual_cfg_reg272_raw) = values[31];
                        id(manual_cfg_reg273_raw) = values[32];
                        id(manual_cfg_reg274_raw) = values[33];
                        id(manual_cfg_reg275_raw) = values[34];
                        id(manual_cfg_reg276_raw) = values[35];
                        id(manual_cfg_reg277_raw) = values[36];
                        id(manual_cfg_reg278_raw) = values[37];
                        id(manual_cfg_reg279_raw) = values[38];
                        // FB-B3 RAW_CACHE_EXT: registers 243 / 245 / 247 / 248 (values[2] / [4] / [6] / [7], already decoded
                        // below) - RAM only, read by nothing but the Live Match tick. No new Modbus read.
                        id(fbc_raw_243) = values[2];
                        id(fbc_raw_245) = values[4];
                        id(fbc_raw_247) = values[6];
                        id(fbc_raw_248) = values[7];

                        // Diagnostic-only: publish the complete raw TOU flag words so
                        // higher bits (beyond the decoded Charge/Mode fields above) are
                        // visible for observation. No new Modbus reads - reuses values[]
                        // from this same block.
                        id(ecco_tou1_raw_flags).publish_state(values[33]);
                        id(ecco_tou2_raw_flags).publish_state(values[34]);
                        id(ecco_tou3_raw_flags).publish_state(values[35]);
                        id(ecco_tou4_raw_flags).publish_state(values[36]);
                        id(ecco_tou5_raw_flags).publish_state(values[37]);
                        id(ecco_tou6_raw_flags).publish_state(values[38]);

                        id(manual_config_raw_cache_valid) = id(configuration_block1_ok);
                        // FB-B3: RAW_CACHE_EXT is usable only after a poll in which Block A and Block B both succeeded.
                        id(fbc_raw_filled) = id(fbc_raw_filled) || id(configuration_block1_ok);

                        // 2026-09-26 (Dump-to-Grid pre-live hardening):
                        // RAM-only freshness marker for the 244/256-261
                        // raw values cached just above - see
                        // cfg_block_b_seq. Adds no Modbus I/O.
                        id(cfg_block_b_seq)++;
                        id(cfg_block_b_ok_ms) = millis();
                        // 2026-09-26 adversarial review (B1): record which
                        // dispatch generation produced the values just
                        // cached above - see cfg_block_b_dispatch_seq.
                        id(cfg_block_b_response_dispatch_seq) = id(cfg_block_b_dispatch_seq);

                        uint16_t system_bits = values[39]; // register 280
                        id(ecco_generator_peak_shaving).publish_state((system_bits & 0x00F0) == 0x0010);
                        id(ecco_grid_peak_shaving).publish_state((system_bits & 0x0F00) == 0x0100);
                        id(ecco_on_grid_always_on).publish_state((system_bits & 0x1000) != 0);

                        id(ecco_cfg_grid_max_voltage).publish_state(values[46] * 0.1f);
                        id(ecco_cfg_grid_min_voltage).publish_state(values[47] * 0.1f);
                        id(ecco_cfg_grid_max_frequency).publish_state(values[48] * 0.01f);
                        id(ecco_cfg_grid_min_frequency).publish_state(values[49] * 0.01f);
                        id(ecco_cfg_generator_peak_shaving_power).publish_state(values[51]);
                        id(ecco_cfg_grid_peak_shaving_power).publish_state(values[52]);

                        bool ok = id(configuration_block1_ok);
                        id(configuration_online).publish_state(ok);

                        auto now = id(ntp_time).now();
                        if (now.is_valid()) {
                          id(last_configuration_update).publish_state(
                            now.strftime("%Y-%m-%d %H:%M:%S")
                          );
                        }

                        ESP_LOGI(
                          "config",
                          "Config B: export %uW, TOU %s, slot1 %s %uW %u%%, signal raw=0x%04X",
                          values[4],
                          (values[7] & 0x0001) ? "ON" : "OFF",
                          format_time(values[9]).c_str(),
                          values[15],
                          values[27],
                          signal_flags
                        );
                on_error:
                  then:
                    - lambda: |-
                        id(configuration_failures)++;
                        id(manual_config_raw_cache_valid) = false;
                        id(configuration_online).publish_state(false);
                        ESP_LOGW(
                          "config",
                          "Configuration block 241-293 Modbus exception: 0x%02X",
                          (uint8_t) exception_code
                        );
                on_no_response:
                  then:
                    - lambda: |-
                        id(configuration_failures)++;
                        id(manual_config_raw_cache_valid) = false;
                        id(configuration_online).publish_state(false);
                        ESP_LOGW("config", "No response to configuration block 241-293");

            - delay: 2500ms

            # Block C: communication-board basic-setting flags.
            # Register 330 packs Time Sync in bits 0-1 and Beep in bits 2-3.
            # Pair value 2 = Disable, 3 = Enable; 0/1 are no-action/reserved states.
            - modbus_client.read_holding_registers:
                modbus_id: inverter_modbus
                address: 0x01
                start_address: 330
                count: 1
                on_response:
                  then:
                    - lambda: |-
                        uint16_t basic = values[0];
                        id(ecco_cfg_basic_settings_raw).publish_state(basic);

                        auto decode_basic_pair = [](uint16_t pair) -> std::string {
                          switch (pair & 0x0003) {
                            case 2: return std::string("Disable");
                            case 3: return std::string("Enable");
                            case 0: return std::string("No action (0)");
                            case 1: return std::string("No action (1)");
                          }
                          return std::string("Unknown");
                        };

                        id(ecco_basic_sync_clock).publish_state(
                          decode_basic_pair(basic & 0x0003)
                        );
                        id(ecco_basic_beep).publish_state(
                          decode_basic_pair((basic >> 2) & 0x0003)
                        );

                        ESP_LOGI(
                          "config",
                          "Config C: basic raw=0x%04X, Sync Clock=%s, Beep=%s",
                          basic,
                          decode_basic_pair(basic & 0x0003).c_str(),
                          decode_basic_pair((basic >> 2) & 0x0003).c_str()
                        );
                on_error:
                  then:
                    - lambda: |-
                        id(configuration_failures)++;
                        id(configuration_online).publish_state(false);
                        ESP_LOGW(
                          "config",
                          "Configuration register 330 Modbus exception: 0x%02X",
                          (uint8_t) exception_code
                        );
                on_no_response:
                  then:
                    - lambda: |-
                        id(configuration_failures)++;
                        id(configuration_online).publish_state(false);
                        ESP_LOGW("config", "No response to configuration register 330");
""")
_CFG_A_TAIL = '                        ESP_LOGW("config", "No response to configuration block 200-240");\n'
_CFG_DELAY = "\n            - delay: 2500ms\n\n"
_CFG_B1_COMMENT = ("            # 2026-09-26 adversarial review (B1): stamp the dispatch\n"
                   "            # generation immediately before Block B is sent - see\n"
                   "            # cfg_block_b_dispatch_seq's own comment.\n")
_CFG_STAMP_OLD = "            - lambda: 'id(cfg_block_b_dispatch_seq)++;'\n\n"
_CFG_B_COMMENT = ("            # Block B: energy management / TOU / grid protection\n"
                  "            # Registers 241-293 inclusive\n")
_CFG_B_END = '                        ESP_LOGW("config", "No response to configuration block 241-293");\n'
_CFG_C_COMMENT = ("            # Block C: communication-board basic-setting flags.\n"
                  "            # Register 330 packs Time Sync in bits 0-1 and Beep in bits 2-3.\n"
                  "            # Pair value 2 = Disable, 3 = Enable; 0/1 are no-action/reserved states.\n")
_head = _CFG_A_TAIL + _CFG_DELAY + _CFG_B1_COMMENT + _CFG_STAMP_OLD + _CFG_B_COMMENT
assert CFG_OLD.startswith(_head)
_rest = CFG_OLD[len(_head):]
assert _rest.count(_CFG_B_END) == 1
_CFG_B = _rest[:_rest.index(_CFG_B_END) + len(_CFG_B_END)]
_rest = _rest[len(_CFG_B):]
assert _rest.startswith(_CFG_DELAY + _CFG_C_COMMENT)
_CFG_C = _rest[len(_CFG_DELAY + _CFG_C_COMMENT):]
assert _CFG_B.startswith("            - modbus_client.read_holding_registers:\n                modbus_id: inverter_modbus\n"
                         "                address: 0x01\n                start_address: 241\n")
assert _CFG_C.startswith("            - modbus_client.read_holding_registers:\n                modbus_id: inverter_modbus\n"
                         "                address: 0x01\n                start_address: 330\n")


def _cfg_handlers(what: str, block1: bool, cache: bool, online: bool = True) -> str:
    """on_custom_response / on_not_sent at the original handler indentation: Blocks A / B follow the unified invalidation rule
    (the existing on_error / on_no_response bodies of that block); Block C (register 330, display only) only counts, so the new
    handlers add no input that could end a Dump lease or refuse a start (online=False)."""
    body = "                        id(configuration_failures)++;\n"
    if block1:
        body += "                        id(configuration_block1_ok) = false;\n"
    if cache:
        body += "                        id(manual_config_raw_cache_valid) = false;\n"
    if online:
        body += "                        id(configuration_online).publish_state(false);\n"
    return ("                on_custom_response:\n                  then:\n                    - lambda: |-\n" + body
            + f'                        ESP_LOGW("config", "Non-standard reply to configuration {what} (%u bytes)", (unsigned) response.size());\n'
            + "                on_not_sent:\n                  then:\n                    - lambda: |-\n" + body
            + f'                        ESP_LOGW("config", "Configuration {what} was not sent");\n')


_CFG_D1_COMMENT = _blk(r"""
            # FB-D1 (D1b): re-check write-path ownership in the SAME loop pass that stamps the dispatch generation and queues
            # Block B, so the check cannot go stale before the frame is queued. An owner that took its lock (or an RTC
            # correction that started) during the delay above gets no Block B / Block C frame inside its transaction. A
            # yield stamps nothing and changes no cache flag (a skipped read is not a failure) and owes a catch-up poll,
            # which the catch-up interval runs once no owner holds the write path and the bus is quiet. The dispatch
            # generation is stamped only when Block B is actually queued, and each stamp pays one owed poll.
""")
_CFG_B_GUARD_HEAD = _blk(r"""
            - if:
                condition:
                  lambda: |-
                    return !id(manual_write_in_progress) && !id(correction_in_progress);
                then:
                  - lambda: |-
                      id(cfg_block_b_dispatch_seq)++;
                      if (id(cfg_poll_owed) > 0) id(cfg_poll_owed)--;

""")
_CFG_C_GUARD_HEAD = _blk(r"""
                  # FB-D1 (D1b): re-check again before Block C (register 330 is display-only; a skipped read is not a failure).
                  - if:
                      condition:
                        lambda: |-
                          return !id(manual_write_in_progress) && !id(correction_in_progress);
                      then:
""")
_CFG_C_GUARD_ELSE = _blk(r"""
                      else:
                        - lambda: |-
                            ESP_LOGI("config", "Configuration register 330 read skipped - inverter write path owned by another transaction");
""")
_CFG_B_GUARD_ELSE = _blk(r"""
                else:
                  - lambda: |-
                      if (id(cfg_poll_owed) < 1) id(cfg_poll_owed) = 1;
                      ESP_LOGI("config", "Configuration poll yielded before Block B - inverter write path owned by another transaction; nothing stamped, catch-up owed");
""")
CFG_NEW = (_CFG_A_TAIL + _cfg_handlers("block 200-240", True, True) + _CFG_DELAY + _CFG_B1_COMMENT + _CFG_D1_COMMENT
           + _CFG_B_GUARD_HEAD + _indent(_CFG_B_COMMENT + _CFG_B + _cfg_handlers("block 241-293", False, True), 6)
           + _indent(_CFG_DELAY + _CFG_C_COMMENT, 6) + _CFG_C_GUARD_HEAD
           + _indent(_CFG_C + _cfg_handlers("register 330", False, False, online=False), 12) + _CFG_C_GUARD_ELSE + _CFG_B_GUARD_ELSE)

# ---- 6. read_inverter_clock: the previous read for the policy (D1) -----------------------------------------------------------
RTC_PREV_OLD = _blk(r"""
                  if (id(have_rtc_baseline)) {
                    int ntp_elapsed = ntp_seconds - id(previous_ntp_sod);
""")
RTC_PREV_NEW = _blk(r"""
                  // FB-D1: the previous regular read, captured before the stall detector below replaces it (the policy's
                  // confirmation needs it).
                  const bool rtc_had_prev = id(have_rtc_baseline);
                  const int rtc_prev_inv_sod = id(previous_inverter_sod);
                  const int rtc_prev_ntp_sod = id(previous_ntp_sod);

""") + RTC_PREV_OLD

# ---- 7. read_inverter_clock: the automatic queue is the pure policy (D1) -----------------------------------------------------
RTC_QUEUE_OLD = _blk(r"""
                  bool cooldown_active =
                    id(cooldown_until_ms) != 0 &&
                    (int32_t)(millis() - id(cooldown_until_ms)) < 0;

                  if (
                    id(automatic_clock_sync).state &&
                    !id(correction_in_progress) &&
                    !cooldown_active &&
                    (date_mismatch || abs_difference >= threshold)
                  ) {
                    id(correction_in_progress) = true;
                    id(correction_is_manual) = false;
                    id(correction_attempt) = 1;
                    id(auto_sync_pending) = true;

                    char result[96];
                    snprintf(
                      result,
                      sizeof(result),
                      "Automatic correction queued - error %d s",
                      difference
                    );
                    id(last_correction_result).publish_state(result);
                    ESP_LOGW(
                      "ecco",
                      "RTC correction queued - clock difference: %d seconds",
                      difference
                    );
                  }
""")
_RTC_COOLDOWN = _blk(r"""
                  bool cooldown_active =
                    id(cooldown_until_ms) != 0 &&
                    (int32_t)(millis() - id(cooldown_until_ms)) < 0;

""")
assert RTC_QUEUE_OLD.startswith(_RTC_COOLDOWN)
RTC_QUEUE_NEW = _RTC_COOLDOWN + _blk(r"""
                  // FB-D1: WHEN an automatic correction may be queued is the pure policy ecco_rtc::decide()
                  // (include/ecco_rtc_policy.h, offline mirror registry/rtc_policy.py). It never starts one in the minute
                  // before or after a half hour or a TOU zone start, nor while an energy transaction is active (unless the
                  // error is large). Right before each TOU zone start one read over half the threshold corrects
                  // (precision); elsewhere the error must exceed the threshold (once after boot) or the background floor on
                  // two confirming reads (a stale or frozen register image never confirms). The correction itself (write
                  // 22-24 from NTP, verified readback, one retry, cooldown) is unchanged.
                  ecco_rtc::Inputs rp{};
                  rp.auto_sync = id(automatic_clock_sync).state;
                  rp.lock_held = id(correction_in_progress);
                  rp.cooldown_active = cooldown_active;
                  rp.lease_active = id(free_power_active_persisted) || id(free_power_restore_requested) ||
                                    id(free_power_operation_in_progress) || id(dump_active_persisted) ||
                                    id(dump_restore_requested) || id(dump_operation_in_progress) ||
                                    id(reg244_apply_in_progress);
                  rp.boot_aligned = id(rtc_boot_aligned);
                  rp.err_s = ecco_rtc::full_error_s(year, month, day, inverter_seconds, now.year, now.month,
                                                    now.day_of_month, ntp_seconds);
                  rp.prev_valid = rtc_had_prev;
                  rp.prev_err_s = id(rtc_prev_err_s);
                  rp.ntp_elapsed_s = ecco_rtc::elapsed_s(ntp_seconds, rtc_prev_ntp_sod);
                  rp.inv_elapsed_s = ecco_rtc::elapsed_s(inverter_seconds, rtc_prev_inv_sod);
                  rp.tod_s = (uint32_t) ntp_seconds;
                  rp.day = ecco_rtc::days_from_civil(now.year, now.month, now.day_of_month);
                  rp.threshold_s = threshold;
                  rp.have_last_auto = id(rtc_have_last_auto);
                  rp.since_last_auto_ms = millis() - id(rtc_last_auto_ms);
                  rp.precision_served = id(rtc_precision_served);
                  rp.tou_raw[0] = id(manual_cfg_reg250_raw);
                  rp.tou_raw[1] = id(manual_cfg_reg251_raw);
                  rp.tou_raw[2] = id(manual_cfg_reg252_raw);
                  rp.tou_raw[3] = id(manual_cfg_reg253_raw);
                  rp.tou_raw[4] = id(manual_cfg_reg254_raw);
                  rp.tou_raw[5] = id(manual_cfg_reg255_raw);
                  const ecco_rtc::Decision dec = ecco_rtc::decide(rp);
                  id(rtc_policy_reason) = dec.reason;
                  id(rtc_prev_err_s) = rp.err_s;
                  if (dec.boot_settled) {
                    id(rtc_boot_aligned) = true;
                  }

                  if (dec.action == ecco_rtc::ACT_CORRECT) {
                    id(correction_in_progress) = true;
                    id(correction_is_manual) = false;
                    id(correction_attempt) = 1;
                    id(auto_sync_pending) = true;
                    id(rtc_txn_since_ms) = millis();
                    id(rtc_have_last_auto) = true;
                    id(rtc_last_auto_ms) = millis();
                    if (dec.precision_key != 0) {
                      id(rtc_precision_served) = dec.precision_key;
                    }
                    // the correction re-bases the drift context: two fresh regular reads confirm the next one
                    id(have_rtc_baseline) = false;

                    char result[96];
                    snprintf(
                      result,
                      sizeof(result),
                      "Automatic correction queued (%s) - error %d s",
                      ecco_rtc::reason_name(dec.reason),
                      difference
                    );
                    id(last_correction_result).publish_state(result);
                    ESP_LOGW(
                      "ecco",
                      "RTC correction queued - clock difference: %d seconds",
                      difference
                    );
                    ESP_LOGI("ecco", "RTC policy: %s (threshold %d s, full error %d s)", ecco_rtc::reason_name(dec.reason),
                             (int) dec.threshold_s, (int) rp.err_s);
                  } else if (dec.reason != ecco_rtc::R_WITHIN && dec.reason != ecco_rtc::R_AUTO_OFF &&
                             dec.reason != ecco_rtc::R_BUSY) {
                    ESP_LOGI("ecco", "RTC correction held (%s) - full error %d s, threshold %d s", ecco_rtc::reason_name(dec.reason),
                             (int) rp.err_s, (int) dec.threshold_s);
                  }
""")

# ---- 8. read_inverter_clock: the two remaining read terminals (D1a) ----------------------------------------------------------
RTC_READ_TAIL_OLD = _blk(r"""
                    id(last_correction_result).publish_state(
                      "Verification read timed out - processing retry"
                    );
                  }

  - platform: template
    name: "Sync Inverter Clock"
""")
RTC_READ_TAIL_NEW = _blk(r"""
                    id(last_correction_result).publish_state(
                      "Verification read timed out - processing retry"
                    );
                  }
          # FB-D1 (D1a): the two remaining terminal outcomes of this shared read action. A refused request fires
          # on_not_sent synchronously inside the press: only the 1 s tick's verification press (rtc_verify_dispatching) is
          # attributable to the correction - an HA or periodic press that was refused leaves it alone. A non-standard reply
          # (for example a late or wrong-length FC03 frame) is never evidence: while a verification read is outstanding it
          # fails into the existing bounded retry path.
          on_not_sent:
            then:
              - lambda: |-
                  if (id(rtc_verify_dispatching) && id(verification_read_active)) {
                    ESP_LOGW("ecco", "RTC verification read was not queued - processing retry");
                    id(verification_read_active) = false;
                    id(comm_failure_pending) = true;
                    id(last_correction_result).publish_state("Verification read not sent - processing retry");
                  } else {
                    ESP_LOGW("ecco", "RTC read request not queued (not a verification read)");
                  }
          on_custom_response:
            then:
              - lambda: |-
                  ESP_LOGW("ecco", "Non-standard reply while reading inverter RTC (%u bytes)", (unsigned) response.size());
                  if (id(verification_read_active)) {
                    id(verification_read_active) = false;
                    id(comm_failure_pending) = true;
                    id(last_correction_result).publish_state("Verification read got a non-standard reply - processing retry");
                  }

  - platform: template
    name: "Sync Inverter Clock"
""")

# ---- 9. sync_inverter_clock: stamp the deadline clock (D1a) ------------------------------------------------------------------
SYNC_OLD = _blk(r"""
                id(correction_attempt) = 1;
                id(last_correction_result).publish_state("Manual correction started");
""")
SYNC_NEW = _blk(r"""
                id(correction_attempt) = 1;
                id(rtc_txn_since_ms) = millis();
                id(last_correction_result).publish_state("Manual correction started");
""")

# ---- 10. the catch-up interval and the 1 s RTC tick's first lambda (D1a / D1b / D1c) -----------------------------------------
IV_OLD = _blk(r"""
                id: poll_inverter_configuration

  - interval: 1s
    startup_delay: 5s
    then:
      - if:
          condition:
            lambda: |-
              return id(comm_failure_pending);
""")
IV_NEW = _blk(r"""
                id: poll_inverter_configuration

  # FB-D1 (D1b / D1c): configuration poll catch-up. cfg_poll_owed is set when a poll yielded Block B to a write-path owner
  # (1) or when an RTC correction released its lock (2). This runs the ordinary configuration poll (through its wrapper,
  # which re-checks ownership) only when no owner holds the write path or the RTC lock, no configuration poll is running
  # and the bus is quiet: it never waits inside the dispatch (FB-B's capture drain needs the dispatch to end) and an owner
  # that is phase-locked to the 60 s poll cannot starve Block B. Read-only: no new Modbus operation.
  - interval: 2s
    startup_delay: 30s
    then:
      - if:
          condition:
            lambda: |-
              return id(cfg_poll_owed) > 0 && id(configuration_polling).state &&
                     !id(manual_write_in_progress) && !id(correction_in_progress) &&
                     !id(poll_inverter_configuration_dispatch).is_running() &&
                     id(inverter_modbus)->tx_buffer_empty() && !id(inverter_modbus)->tx_blocked();
          then:
            - script.execute:
                id: poll_inverter_configuration

  - interval: 1s
    startup_delay: 5s
    then:
      # FB-D1 (D1a / D1c): runs FIRST every second, before the retry, dispatch and verification steps below.
      # (a) auto_sync_pending / verification_pending / verification_read_active / comm_failure_pending mean nothing without
      #     correction_in_progress: a stray one (only a late callback after (b) could leave one) is cleared, so it can never
      #     start a verification read or a write.
      # (b) Deadline breaker: no RTC correction holds correction_in_progress longer than ecco_rtc::kTxnDeadlineMs (90 s; the
      #     legitimate worst case is about 49 s). It releases ONLY RTC-owned state (never manual_write_in_progress or another
      #     domain's flag) and only when no RTC frame can be outstanding (ecco_rtc::no_rtc_frame_outstanding): a quiet bus (no
      #     frame READY or WAITING), or the correction is between frames (queued for dispatch, waiting for its verification,
      #     or after a failure terminal) - so no RTC callback can arrive afterwards. Only a write or verification read that
      #     is outstanding on a bus that never quiets holds it; every other writer is then held off by its own bus-quiet gate.
      # (c) When the lock is released (by any path) two configuration polls are owed, so the unchanged Live Match / shadow
      #     write fence clears as soon as two post-correction Block B reads complete instead of after two 60 s periods.
      - lambda: |-
          if (!id(correction_in_progress)) {
            if (id(verification_pending) || id(verification_read_active) || id(auto_sync_pending) || id(comm_failure_pending)) {
              ESP_LOGW("ecco", "RTC progress flags set without the correction lock - cleared");
              id(verification_pending) = false;
              id(verification_read_active) = false;
              id(auto_sync_pending) = false;
              id(comm_failure_pending) = false;
            }
          } else if (ecco_rtc::breaker_due(millis(), id(rtc_txn_since_ms),
                                           ecco_rtc::no_rtc_frame_outstanding(
                                             id(inverter_modbus)->tx_buffer_empty() && !id(inverter_modbus)->tx_blocked(),
                                             id(auto_sync_pending), id(verification_pending), id(comm_failure_pending)))) {
            const uint32_t held_s = (millis() - id(rtc_txn_since_ms)) / 1000;
            id(failed_corrections)++;
            id(correction_in_progress) = false;
            id(correction_is_manual) = false;
            id(correction_attempt) = 0;
            id(verification_pending) = false;
            id(verification_read_active) = false;
            id(auto_sync_pending) = false;
            id(comm_failure_pending) = false;
            id(have_rtc_baseline) = false;
            id(cooldown_until_ms) = millis() + 300000;
            id(last_correction_result).publish_state("ABORTED - correction exceeded its deadline - 5 min cooldown");
            ESP_LOGE("ecco", "RTC correction held its lock %u s - deadline breaker released RTC state only (5 min cooldown)",
                     (unsigned) held_s);
          }
          const bool lock_now = id(correction_in_progress);
          if (id(rtc_lock_seen) && !lock_now) {
            id(cfg_poll_owed) = 2;
          }
          id(rtc_lock_seen) = lock_now;
      - if:
          condition:
            lambda: |-
              return id(comm_failure_pending);
""")

# ---- 11. the queued write is dispatched only on a quiet bus (D1) -------------------------------------------------------------
ASP_OLD = _blk(r"""
      - if:
          condition:
            lambda: |-
              return id(auto_sync_pending);
          then:
""")
ASP_NEW = _blk(r"""
      # FB-D1: a queued correction is dispatched only on a quiet bus (no frame READY or WAITING), so the FC16 frame - whose
      # values are taken from NTP when it is queued - goes out at once instead of behind another frame, and never inside
      # another request's turnaround. The polls yield while the correction holds its lock, so the bus quiets within one
      # frame; the deadline breaker bounds the wait.
      - if:
          condition:
            lambda: |-
              return id(auto_sync_pending) &&
                     id(inverter_modbus)->tx_buffer_empty() && !id(inverter_modbus)->tx_blocked();
          then:
""")

# ---- 12. the verification press: requires the lock, marked for on_not_sent attribution (D1a) ---------------------------------
VERIFY_OLD = _blk(r"""
              return
                id(verification_pending) &&
                !id(verification_read_active) &&
                (int32_t)(millis() - id(verification_due_ms)) >= 0;
          then:
            - lambda: |-
                id(verification_pending) = false;
                id(verification_read_active) = true;
                ESP_LOGI("ecco", "Performing post-write RTC verification");
            - button.press:
                id: read_inverter_clock
""")
VERIFY_NEW = _blk(r"""
              return
                id(correction_in_progress) &&
                id(verification_pending) &&
                !id(verification_read_active) &&
                (int32_t)(millis() - id(verification_due_ms)) >= 0;
          then:
            - lambda: |-
                id(verification_pending) = false;
                id(verification_read_active) = true;
                id(rtc_verify_dispatching) = true;
                ESP_LOGI("ecco", "Performing post-write RTC verification");
            - button.press:
                id: read_inverter_clock
            - lambda: |-
                id(rtc_verify_dispatching) = false;
""")


@dataclass(frozen=True)
class Edit:
    name: str
    region: str
    before: str
    after: str


EDITS = (
    Edit("includes", "esphome: includes (appended last)", INCLUDES_OLD, INCLUDES_NEW),
    Edit("globals", "globals (after configuration_block1_ok, before the Stage 3.3 cache)", GLOBALS_OLD, GLOBALS_NEW),
    Edit("rtc_write", "write_inverter_rtc: on_not_sent / on_custom_response and the NTP-abort release", RTC_WRITE_OLD,
         RTC_WRITE_NEW),
    Edit("telemetry", "poll_inverter_telemetry: handlers and the block 150-196 re-check", TLM_OLD, TLM_NEW),
    Edit("config", "poll_inverter_configuration_dispatch: handlers, the Block B / Block C re-checks and the yield", CFG_OLD,
         CFG_NEW),
    Edit("rtc_prev", "read_inverter_clock: capture the previous regular read", RTC_PREV_OLD, RTC_PREV_NEW),
    Edit("rtc_queue", "read_inverter_clock: the automatic queue is ecco_rtc::decide()", RTC_QUEUE_OLD, RTC_QUEUE_NEW),
    Edit("rtc_read", "read_inverter_clock: on_not_sent / on_custom_response", RTC_READ_TAIL_OLD, RTC_READ_TAIL_NEW),
    Edit("sync", "sync_inverter_clock: stamp the deadline clock", SYNC_OLD, SYNC_NEW),
    Edit("intervals", "interval: the configuration catch-up interval and the 1 s RTC tick's first lambda", IV_OLD, IV_NEW),
    Edit("rtc_dispatch", "interval (1 s RTC): dispatch a queued write only on a quiet bus", ASP_OLD, ASP_NEW),
    Edit("rtc_verify", "interval (1 s RTC): the verification press requires the lock and is marked", VERIFY_OLD, VERIFY_NEW),
)
EDIT_NAMES = tuple(e.name for e in EDITS)
assert len(set(EDIT_NAMES)) == len(EDITS) == 12

# The FB-A reserved tokens this change adds to the firmware YAML (expected 0: FB-D1 names none of them).
BANNED_FW_ADDED = sum(len(_BANNED.findall(e.after)) - len(_BANNED.findall(e.before)) for e in EDITS)


def edit(name: str) -> Edit:
    return EDITS[EDIT_NAMES.index(name)]


def _swap(text: str, find: str, put: str, what: str, state: str) -> str:
    n = text.count(find)
    if n != 1:
        raise AssertionError(f"FB-D1 scope: {what} must be {state} exactly once, found {n}x: {find[:70]!r}")
    i = text.index(find)
    return text[:i] + put + text[i + len(find):]


def add_fbd1_text(text: str) -> str:
    """Applies FB-D1 to a firmware text that has none of it (generates the change; the suite's round trip). Every `before` must be
    unique and no `after` may already be present."""
    out = text
    for e in EDITS:
        if e.after in out:
            raise AssertionError(f"FB-D1 scope: {e.name} edit already present")
        out = _swap(out, e.before, e.after, f"{e.name} anchor", "found")
    return out


def pre_fbd1_firmware(text: str) -> str:
    """The firmware text with exactly FB-D1's edits undone (the exact-match reverter of chain entry fbd1). Every edit must occur
    exactly once, in place, else AssertionError; after the revert every base anchor must again be unique. Reproduces the FB-C2
    firmware (main @ BASE_COMMIT) byte for byte (BASE_FW_SHA)."""
    out = text
    for e in reversed(EDITS):
        out = _swap(out, e.after, e.before, f"{e.name} edit", "present")
    for e in EDITS:
        n = out.count(e.before)
        if n != 1:
            raise AssertionError(f"FB-D1 scope: the {e.name} anchor must be unique once the edit is removed, found {n}x")
    return out
