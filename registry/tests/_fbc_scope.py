"""FB-C1 (Failback Shadow instrumentation) change scope: exactly what FB-C1
adds to firmware/ecco_clock_dongle_stage3_4_free_power.yaml, and its exact
inverse.

Same technique as _mtou1_scope.py / _dump_v2_scope.py / _sg06_scope.py.
Earlier suites pin the firmware's intervals, globals, text sensors,
substitutions and script bodies byte-for-byte as change-scope proofs. FB-C1
necessarily ADDS to four of those regions (and touches no script, no on_boot
lambda, no header). Rather than re-pinning those suites to new hashes - which
would silently widen what they accept - they hash `pre_fbc1_text()` instead:
the current firmware text with exactly FB-C1's four blocks removed.

FB-C1 is a pure INSERTION of four contiguous blocks, each at a unique anchor:

  1. substitutions  - five `ecco_failback_shadow_*` constants
  2. globals        - 42 `failback_shadow_*` RAM globals (restore_value: no)
  3. text_sensor    - the five "ECCO Failback Shadow ..." diagnostic sensors
  4. interval       - ONE `interval: 1s` (static_asserts lambda + tick lambda),
                      inserted IMMEDIATELY BEFORE the PR-A supervision tick

registry/tests/test_failback_shadow_core.py pins that the revert reproduces
the FB-C1 base (BASE_FW_SHA) byte-for-byte, that every block occurs exactly
once, and checks the firmware against the constants below (single source of
truth). Every step raises AssertionError unless the block sits at its anchor
exactly once, so any OTHER change still breaks the pins that hash this
module's output.

FB-T0 REGISTRATION: `pre_fbc1_text` is the firmware reverter of chain entry
`fbc1` in registry/tests/_scope_chain.py (appended after dump_v2). The chain
records the post-FB-C1 checkpoint and FB-C1's exact declarations, and the
older suites - anchored at their own entries - revert it without being
edited. This module imports no other scope module (the chain imports it).

No I/O.
"""

from __future__ import annotations

import hashlib

# main FB-C1 is based on (FB-A #54, Manual TOU #53, Dump V2 #52 and FB-T0 #56
# merged). FB-T0 is test-only, so the firmware there is byte-identical to main
# @ ca7474e (chain entry dump_v2) and to b3fcdfc, where FB-C1 was prepared.
BASE_COMMIT = "be143cdac53d1d0ac971b6515662ce5385fd17ec"
# sha256 of firmware/ecco_clock_dongle_stage3_4_free_power.yaml at BASE_COMMIT
# (LF newlines, as read by Path.read_text) - what pre_fbc1_text() must
# reproduce; equal to the chain's dump_v2 checkpoint.
BASE_FW_SHA = "9d09152744250623ec2f4e3e206a928f1251fb0b1dcf7b3ae1a858c5ae4ec314"

# Files FB-C1 adds (declared as `added_files` of chain entry fbc1). FB-C1 also
# makes one additive edit to registry/tests/_dump_sim.py (millis_64()), which is
# not a chain-pinned artifact.
ADDED_FILES = frozenset({
    "registry/tests/_fbc_scope.py",
    "registry/tests/_fbc_harness.py",
    "registry/tests/test_failback_shadow_core.py",
})

# ---------------------------------------------------------------------------
# Names (single source of truth for the suite)
# ---------------------------------------------------------------------------
SUBSTITUTIONS = {
    "ecco_failback_shadow_episode_close_ms": "300000",
    "ecco_failback_shadow_start_max_ms": "30000",
    "ecco_failback_shadow_assumed_reboot_timeout_ms": "900000",
    "ecco_failback_shadow_publish_min_ms": "10000",
    "ecco_failback_shadow_soak_publish_min_ms": "60000",
}

# (id, C type, initial_value). Order is the order in the firmware.
GLOBALS = [
    ("failback_shadow_ready", "bool", "false"),
    ("failback_shadow_phase", "uint8_t", "0"),
    ("failback_shadow_ep", "uint16_t", "0"),
    ("failback_shadow_ep_trigger", "uint8_t", "0"),
    ("failback_shadow_ep_edge_ms", "uint32_t", "0"),
    ("failback_shadow_ep_last_edge_ms", "uint32_t", "0"),
    ("failback_shadow_ep_edge_uptime_s", "uint32_t", "0"),
    ("failback_shadow_ep_edge_epoch", "uint32_t", "0"),
    ("failback_shadow_ep_client_at_edge", "bool", "false"),
    ("failback_shadow_ep_reboot_margin_s", "int32_t", "0"),
    ("failback_shadow_ep_return_s", "uint32_t", "0"),
    ("failback_shadow_ep_return_gap_ms", "uint32_t", "0"),
    ("failback_shadow_ep_relost", "uint16_t", "0"),
    ("failback_shadow_ep_close_s", "uint32_t", "0"),
    ("failback_shadow_ep_fbf", "uint8_t", "0"),
    ("failback_shadow_seen_svc", "uint32_t", "0"),
    ("failback_shadow_seen_lost", "uint32_t", "0"),
    ("failback_shadow_seen_last_valid_ms", "uint32_t", "0"),
    ("failback_shadow_stable_prev", "bool", "false"),
    ("failback_shadow_stable_since_ms", "uint32_t", "0"),
    ("failback_shadow_gap_b0", "uint16_t", "0"),
    ("failback_shadow_gap_b1", "uint16_t", "0"),
    ("failback_shadow_gap_b2", "uint16_t", "0"),
    ("failback_shadow_gap_b3", "uint16_t", "0"),
    ("failback_shadow_gap_b4", "uint16_t", "0"),
    ("failback_shadow_gap_b5", "uint16_t", "0"),
    ("failback_shadow_gap_max_ms", "uint32_t", "0"),
    ("failback_shadow_gap_last_long_ms", "uint32_t", "0"),
    ("failback_shadow_gaps_missed", "uint16_t", "0"),
    ("failback_shadow_client_seen", "bool", "false"),
    ("failback_shadow_noclient_since_ms", "uint32_t", "0"),
    ("failback_shadow_nc", "uint16_t", "0"),
    ("failback_shadow_ncm_ms", "uint32_t", "0"),
    ("failback_shadow_busy_fp", "bool", "false"),
    ("failback_shadow_busy_dump", "bool", "false"),
    ("failback_shadow_busy_r244", "bool", "false"),
    ("failback_shadow_prev_would_refuse", "bool", "false"),
    ("failback_shadow_wr_fp", "uint16_t", "0"),
    ("failback_shadow_wr_dump", "uint16_t", "0"),
    ("failback_shadow_wr_r244", "uint16_t", "0"),
    ("failback_shadow_last_pub_episode_ms", "uint32_t", "0"),
    ("failback_shadow_last_pub_soak_ms", "uint32_t", "0"),
]
NEW_GLOBAL_IDS = tuple(g[0] for g in GLOBALS)

# (name, id). update_interval: never, entity_category: diagnostic, no lambda,
# no filters, no on_value.
TEXT_SENSORS = [
    ("ECCO Failback Shadow State", "failback_shadow_state_text"),
    ("ECCO Failback Shadow Episode", "failback_shadow_episode_text"),
    ("ECCO Failback Shadow Soak", "failback_shadow_soak_text"),
    ("ECCO Failback Shadow Verdict", "failback_shadow_verdict_text"),
    ("ECCO Failback Shadow Inputs", "failback_shadow_inputs_text"),
]
TEXT_IDS = tuple(t[1] for t in TEXT_SENSORS)

# Episode phase values and the FB-C1-local numeric codes (the simulator's
# transpiler has no char <-> integer model, so triggers / the close outcome
# are small integers here and rendered to their letters by the formatter).
PH_NONE, PH_OPEN, PH_HA_BACK, PH_CLOSED = 0, 1, 2, 3
TRIG_NONE, TRIG_H, TRIG_S = 0, 1, 2
FBF_NONE = 0  # '-' (FB-C1 never models the would-be FB-F latch; FB-C2 adds A/P)
NONE_U32 = 0xFFFFFFFF

# ---------------------------------------------------------------------------
# The four inserted blocks (raw firmware text, LF newlines)
# ---------------------------------------------------------------------------
SUBSTITUTIONS_BLOCK = """\
  # Failback Shadow (FB-C1) - RAM-only, zero-authority observer of the HA
  # supervision state (docs/architecture/fallback/FINAL_FBB_FBC_ARCHITECTURE.md
  # section 6). PROVISIONAL, like the supervision constants above: the LP-C1
  # soak decides T_lost; nothing here gates, writes or persists anything.
  # Continuous stable supervision required after HA returns before a shadow
  # episode closes (hysteresis: must not be shorter than ecco_supervision_lost_ms).
  ecco_failback_shadow_episode_close_ms: "300000"
  # A managed START that began just before SUSPECT must finish before LOST.
  ecco_failback_shadow_start_max_ms: "30000"
  # Assumed no-API-client restart window (ESPHome's default for api and wifi,
  # neither of which sets its own timeout here); see the coupling test in
  # registry/tests/test_failback_shadow_core.py.
  ecco_failback_shadow_assumed_reboot_timeout_ms: "900000"
  # Minimum spacing of Episode publishes (State publishes on change) and of Soak.
  ecco_failback_shadow_publish_min_ms: "10000"
  ecco_failback_shadow_soak_publish_min_ms: "60000"
"""

_GLOBALS_HEAD = """\
  # ---------------------------------------------------------------------
  # Failback Shadow (FB-C1) - RAM-only, zero-authority observer state
  # (docs/architecture/fallback/FINAL_FBB_FBC_ARCHITECTURE.md section 6).
  # Every global below is restore_value: no and is written ONLY by the
  # Failback Shadow 1s interval; nothing else reads or writes it (so the
  # shadow can never become a gate).
  # ---------------------------------------------------------------------
"""
GLOBALS_BLOCK = _GLOBALS_HEAD + "".join(
    f"  - id: {gid}\n    type: {ctype}\n    restore_value: no\n    initial_value: '{init}'\n"
    for gid, ctype, init in GLOBALS
)

TEXT_SENSORS_BLOCK = """\

  # Failback Shadow (FB-C1) - five read-only diagnostic strings, published only
  # by the Failback Shadow interval (update_interval: never). Verdict and
  # Inputs are NOT_EVALUATED until the evaluator (FB-C2) exists.
""" + "".join(
    f"""\
  - platform: template
    name: "{name}"
    id: {tid}
    entity_category: diagnostic
    update_interval: never
"""
    for name, tid in TEXT_SENSORS
)

INTERVAL_BLOCK = """\
  # Failback Shadow (FB-C1) - RAM-only, zero-authority evaluator. The first
  # read-only consumer of the HA supervision state: it only observes and
  # publishes five diagnostic strings. No Modbus, no NVS, no RTC memory, no
  # script, no control, and nothing else may ever read its state.
  # It runs IMMEDIATELY BEFORE the PR-A supervision tick. ESPHome gives every
  # interval a random initial offset, so the relative order of the two 1s
  # ticks is random per boot; everything here is therefore derived from
  # PR-A's edge counters and re-checks the heartbeat age itself.
  # Lambda 0 holds only the static_asserts (kept out of on_boot on purpose);
  # lambda 1 is the tick.
  - interval: 1s
    then:
      - lambda: |-
          static_assert(${ecco_supervision_suspect_ms}UL + ${ecco_failback_shadow_start_max_ms}UL < ${ecco_supervision_lost_ms}UL,
                        "failback shadow: T_suspect + T_start_max must be below T_lost");
          static_assert(${ecco_supervision_lost_ms}UL < ${ecco_failback_shadow_assumed_reboot_timeout_ms}UL,
                        "failback shadow: T_lost must be below the assumed no-client reboot timeout");
          static_assert(${ecco_failback_shadow_episode_close_ms}UL >= ${ecco_supervision_lost_ms}UL,
                        "failback shadow: episode close hysteresis must be at least T_lost");
          static_assert(${ecco_failback_shadow_episode_close_ms}UL >= ${ecco_supervision_stable_min_span_ms}UL,
                        "failback shadow: close window must be at least the stable span");
          static_assert(${ecco_failback_shadow_publish_min_ms}UL <= 30000UL,
                        "failback shadow: publish debounce must be at most one heartbeat period");
      - lambda: |-
          const uint32_t now = millis();
          if (id(supervision_generation) == 0) return;
          const bool first = !id(failback_shadow_ready);
          if (first) {
            id(failback_shadow_ready) = true;
            // Obligations loaded at boot are not STARTs: seed the busy flags.
            id(failback_shadow_busy_fp) = id(free_power_operation_in_progress) || id(free_power_snapshot_valid);
            id(failback_shadow_busy_dump) = id(dump_operation_in_progress) || id(dump_snapshot_valid);
            id(failback_shadow_busy_r244) = id(reg244_apply_in_progress) || id(reg244_snapshot_valid);
            id(failback_shadow_client_seen) = id(api_client_connected_sensor).state;
            id(failback_shadow_noclient_since_ms) = 0;
            ESP_LOGI("failback_shadow", "boot %08X shadow ready", (unsigned) id(supervision_boot_nonce));
          }

          // 1. Supervision sample (read-only). P_STABLE re-checks the heartbeat
          // age so it is correct whichever tick runs first in a pass.
          const uint8_t st = id(supervision_state);
          const uint32_t svc = id(supervision_valid_count);
          const uint32_t le = id(supervision_lost_events);
          const uint32_t lv = id(supervision_last_valid_ms);
          const uint32_t age = (svc > 0) ? (uint32_t) (now - lv) : 0xFFFFFFFFUL;
          const bool stable = (st == 1) && id(supervision_stable) && (svc > 0) &&
                              (age <= ${ecco_supervision_stable_max_gap_ms}UL);
          if (stable && !id(failback_shadow_stable_prev)) {
            id(failback_shadow_stable_since_ms) = lv;
          }
          id(failback_shadow_stable_prev) = stable;
          const uint32_t stable_for = stable ? (uint32_t) (now - id(failback_shadow_stable_since_ms)) : 0;

          // 2. API client presence (read-only entity state).
          const bool cli = id(api_client_connected_sensor).state;
          if (id(failback_shadow_client_seen) && !cli) {
            id(failback_shadow_noclient_since_ms) = now;
            if (id(failback_shadow_nc) < 65535) id(failback_shadow_nc) += 1;
          }
          if (!id(failback_shadow_client_seen) && cli) {
            const uint32_t zc = (uint32_t) (now - id(failback_shadow_noclient_since_ms));
            if (zc > id(failback_shadow_ncm_ms)) id(failback_shadow_ncm_ms) = zc;
          }
          id(failback_shadow_client_seen) = cli;

          // 3. Closed heartbeat gaps. The most recent gap is exact; any others
          // closed inside the same tick are only counted. Bucket edges are
          // deliberately literal and fixed so soak data stays comparable.
          bool soak_now = false;
          const uint32_t seen_svc = id(failback_shadow_seen_svc);
          const bool beat = (svc != seen_svc);
          if (beat) {
            const uint32_t closed = (svc - seen_svc) - ((seen_svc == 0) ? 1 : 0);
            if (closed >= 1) {
              const uint32_t g = id(supervision_last_gap_ms);
              if (g <= 35000UL) {
                if (id(failback_shadow_gap_b0) < 65535) id(failback_shadow_gap_b0) += 1;
              } else if (g <= 45000UL) {
                if (id(failback_shadow_gap_b1) < 65535) id(failback_shadow_gap_b1) += 1;
              } else if (g <= 90000UL) {
                if (id(failback_shadow_gap_b2) < 65535) id(failback_shadow_gap_b2) += 1;
              } else if (g <= 300000UL) {
                if (id(failback_shadow_gap_b3) < 65535) id(failback_shadow_gap_b3) += 1;
              } else if (g <= 900000UL) {
                if (id(failback_shadow_gap_b4) < 65535) id(failback_shadow_gap_b4) += 1;
              } else {
                if (id(failback_shadow_gap_b5) < 65535) id(failback_shadow_gap_b5) += 1;
              }
              if (g > id(failback_shadow_gap_max_ms)) id(failback_shadow_gap_max_ms) = g;
              if (g > 45000UL) {
                id(failback_shadow_gap_last_long_ms) = g;
                ESP_LOGI("failback_shadow", "closed heartbeat gap %u ms", (unsigned) g);
                soak_now = true;
              }
              const uint32_t gm_new = (uint32_t) id(failback_shadow_gaps_missed) + (closed - 1);
              id(failback_shadow_gaps_missed) = gm_new > 65535UL ? 65535UL : gm_new;
            }
          }

          // 4. Managed-action evidence: START attempts (idle -> busy edges of
          // the operation flag or the snapshot flag) seen while a future
          // FB-D/FB-F would refuse them. Counted only; nothing is refused here.
          const bool wref_prev = id(failback_shadow_prev_would_refuse);
          const bool busy_fp = id(free_power_operation_in_progress) || id(free_power_snapshot_valid);
          const bool busy_dump = id(dump_operation_in_progress) || id(dump_snapshot_valid);
          const bool busy_r244 = id(reg244_apply_in_progress) || id(reg244_snapshot_valid);
          if (busy_fp && !id(failback_shadow_busy_fp) && wref_prev) {
            if (id(failback_shadow_wr_fp) < 65535) id(failback_shadow_wr_fp) += 1;
            soak_now = true;
            ESP_LOGI("failback_shadow", "FP START observed while FB-D/FB-F would refuse");
          }
          if (busy_dump && !id(failback_shadow_busy_dump) && wref_prev) {
            if (id(failback_shadow_wr_dump) < 65535) id(failback_shadow_wr_dump) += 1;
            soak_now = true;
            ESP_LOGI("failback_shadow", "DUMP START observed while FB-D/FB-F would refuse");
          }
          if (busy_r244 && !id(failback_shadow_busy_r244) && wref_prev) {
            if (id(failback_shadow_wr_r244) < 65535) id(failback_shadow_wr_r244) += 1;
            soak_now = true;
            ESP_LOGI("failback_shadow", "R244 START observed while FB-D/FB-F would refuse");
          }
          id(failback_shadow_busy_fp) = busy_fp;
          id(failback_shadow_busy_dump) = busy_dump;
          id(failback_shadow_busy_r244) = busy_r244;

          // 5. Episode machine: NONE -> OPEN -> HA_BACK -> CLOSED. Edges come
          // from PR-A's counters, never from sampling the state.
          bool ep_event = false;
          const uint32_t dle = le - id(failback_shadow_seen_lost);
          uint8_t ph = id(failback_shadow_phase);
          if (dle != 0) {
            if (ph == 0 || ph == 3) {
              const bool trig_s = (seen_svc == 0);
              const uint32_t t_edge = trig_s ? ${ecco_supervision_lost_ms}UL
                                             : id(failback_shadow_seen_last_valid_ms) + ${ecco_supervision_lost_ms}UL;
              if (id(failback_shadow_ep) < 65535) id(failback_shadow_ep) += 1;
              id(failback_shadow_ep_trigger) = trig_s ? 2 : 1;
              id(failback_shadow_ep_edge_ms) = t_edge;
              id(failback_shadow_ep_last_edge_ms) = t_edge;
              id(failback_shadow_ep_edge_uptime_s) = (uint32_t) ((millis_64() - (uint64_t) (uint32_t) (now - t_edge)) / 1000ULL);
              uint32_t e0 = 0;
              auto wall = id(ntp_time).now();
              if (id(ntp_synced) && wall.is_valid()) {
                e0 = (uint32_t) wall.timestamp - (uint32_t) (now - t_edge) / 1000;
              }
              id(failback_shadow_ep_edge_epoch) = e0;
              id(failback_shadow_ep_client_at_edge) = cli;
              const int32_t rb_ms = (int32_t) (id(failback_shadow_noclient_since_ms) + ${ecco_failback_shadow_assumed_reboot_timeout_ms}UL - t_edge);
              id(failback_shadow_ep_reboot_margin_s) = cli ? -1 : (rb_ms > 0 ? rb_ms / 1000 : 0);
              id(failback_shadow_ep_relost) = dle - 1;
              id(failback_shadow_ep_return_s) = 0xFFFFFFFFUL;
              id(failback_shadow_ep_return_gap_ms) = 0xFFFFFFFFUL;
              id(failback_shadow_ep_close_s) = 0xFFFFFFFFUL;
              id(failback_shadow_ep_fbf) = 0;
              ph = 1;
              ep_event = true;
              ESP_LOGW("failback_shadow", "episode %08X-%u OPEN k=N tr=%s cli=%u rb=%d",
                       (unsigned) id(supervision_boot_nonce), (unsigned) id(failback_shadow_ep),
                       trig_s ? "S" : "H", (unsigned) cli, (int) id(failback_shadow_ep_reboot_margin_s));
            } else {
              const uint32_t rl_new = (uint32_t) id(failback_shadow_ep_relost) + dle;
              id(failback_shadow_ep_relost) = rl_new > 65535UL ? 65535UL : rl_new;
              id(failback_shadow_ep_last_edge_ms) = id(failback_shadow_seen_last_valid_ms) + ${ecco_supervision_lost_ms}UL;
              ph = 1;
              ep_event = true;
              ESP_LOGW("failback_shadow", "episode %08X-%u re-LOST rl=%u (HA return did not cancel)",
                       (unsigned) id(supervision_boot_nonce), (unsigned) id(failback_shadow_ep),
                       (unsigned) id(failback_shadow_ep_relost));
            }
          }
          if (beat && ph == 1 && (uint32_t) (lv - id(failback_shadow_ep_last_edge_ms)) < 0x80000000UL) {
            if (id(failback_shadow_ep_return_s) == 0xFFFFFFFFUL) {
              id(failback_shadow_ep_return_s) = (uint32_t) (lv - id(failback_shadow_ep_edge_ms)) / 1000;
              id(failback_shadow_ep_return_gap_ms) = (id(failback_shadow_ep_trigger) == 1)
                                                         ? id(supervision_last_gap_ms) : id(supervision_first_valid_ms);
            }
            ph = 2;
            ep_event = true;
            ESP_LOGI("failback_shadow", "episode %08X-%u HA_BACK ret=%us gap=%.1fs (episode continues)",
                     (unsigned) id(supervision_boot_nonce), (unsigned) id(failback_shadow_ep),
                     (unsigned) id(failback_shadow_ep_return_s),
                     (double) id(failback_shadow_ep_return_gap_ms) / 1000.0);
          }
          if (ph == 2 && stable && stable_for >= ${ecco_failback_shadow_episode_close_ms}UL) {
            id(failback_shadow_ep_close_s) = (uint32_t) (now - id(failback_shadow_ep_edge_ms)) / 1000;
            id(failback_shadow_ep_fbf) = 0;
            ph = 3;
            ep_event = true;
            ESP_LOGI("failback_shadow", "episode %08X-%u CLOSED after %us; no evaluator (FB-C1)",
                     (unsigned) id(supervision_boot_nonce), (unsigned) id(failback_shadow_ep),
                     (unsigned) id(failback_shadow_ep_close_s));
          }
          id(failback_shadow_phase) = ph;

          // 6. Bookkeeping for the next tick.
          id(failback_shadow_seen_svc) = svc;
          id(failback_shadow_seen_lost) = le;
          id(failback_shadow_seen_last_valid_ms) = lv;
          id(failback_shadow_prev_would_refuse) = !stable || ph == 1 || ph == 2;

          // 7. Publish. Each string is formatted and published only if it
          // differs from the entity's stored state.
          const char *state_s = (ph == 1) ? "SHADOW_EPISODE"
                                : (ph == 2) ? "SHADOW_EPISODE_HA_BACK"
                                : stable ? "SHADOW_IDLE" : "SHADOW_WATCH";
          if (id(failback_shadow_state_text).state != state_s) {
            id(failback_shadow_state_text).publish_state(state_s);
          }
          if (first) {
            id(failback_shadow_verdict_text).publish_state("NOT_EVALUATED");
            id(failback_shadow_inputs_text).publish_state("NOT_EVALUATED");
          }

          char ep_s[201];
          if (ph == 0) {
            snprintf(ep_s, sizeof(ep_s),
                     "id=%08X-%u;ph=N;k=-;tr=-;u0=-;e0=-;cli=-;rb=-;v0=-;vu=-;f0=-;dm=-;pre=-;blk=-;d=-;ret=-;gap=-;rl=-;vch=-;cl=-;fbf=-",
                     (unsigned) id(supervision_boot_nonce), (unsigned) id(failback_shadow_ep));
          } else {
            char rb_s[12];
            char ret_s[12];
            char gap_s[14];
            char cl_s[12];
            const int32_t rb_v = id(failback_shadow_ep_reboot_margin_s);
            if (rb_v < 0) {
              snprintf(rb_s, sizeof(rb_s), "-");
            } else {
              snprintf(rb_s, sizeof(rb_s), "%u", (unsigned) (rb_v > 999999 ? 999999 : rb_v));
            }
            const uint32_t ret_v = id(failback_shadow_ep_return_s);
            if (ret_v == 0xFFFFFFFFUL) {
              snprintf(ret_s, sizeof(ret_s), "-");
            } else {
              snprintf(ret_s, sizeof(ret_s), "%u", (unsigned) (ret_v > 999999UL ? 999999UL : ret_v));
            }
            const uint32_t gap_v = id(failback_shadow_ep_return_gap_ms);
            if (gap_v == 0xFFFFFFFFUL) {
              snprintf(gap_s, sizeof(gap_s), "-");
            } else {
              snprintf(gap_s, sizeof(gap_s), "%.1f", (double) (gap_v > 99999900UL ? 99999900UL : gap_v) / 1000.0);
            }
            const uint32_t cl_v = id(failback_shadow_ep_close_s);
            if (cl_v == 0xFFFFFFFFUL) {
              snprintf(cl_s, sizeof(cl_s), "-");
            } else {
              snprintf(cl_s, sizeof(cl_s), "%u", (unsigned) (cl_v > 999999UL ? 999999UL : cl_v));
            }
            snprintf(ep_s, sizeof(ep_s),
                     "id=%08X-%u;ph=%s;k=N;tr=%s;u0=%u;e0=%u;cli=%u;rb=%s;v0=-;vu=-;f0=-;dm=-;pre=-;blk=-;d=-;ret=%s;gap=%s;rl=%u;vch=-;cl=%s;fbf=%s",
                     (unsigned) id(supervision_boot_nonce), (unsigned) id(failback_shadow_ep),
                     (ph == 1) ? "O" : (ph == 2) ? "B" : "C",
                     (id(failback_shadow_ep_trigger) == 2) ? "S" : "H",
                     (unsigned) id(failback_shadow_ep_edge_uptime_s), (unsigned) id(failback_shadow_ep_edge_epoch),
                     (unsigned) id(failback_shadow_ep_client_at_edge), rb_s, ret_s, gap_s,
                     (unsigned) id(failback_shadow_ep_relost), cl_s,
                     (id(failback_shadow_ep_fbf) == 1) ? "A" : (id(failback_shadow_ep_fbf) == 2) ? "P" : "-");
          }
          if (id(failback_shadow_episode_text).state != ep_s &&
              (first || ep_event ||
               (uint32_t) (now - id(failback_shadow_last_pub_episode_ms)) >= ${ecco_failback_shadow_publish_min_ms}UL)) {
            id(failback_shadow_episode_text).publish_state(ep_s);
            id(failback_shadow_last_pub_episode_ms) = now;
          }

          char mx_s[14];
          char lg_s[14];
          const uint32_t mx_v = id(failback_shadow_gap_max_ms);
          if (mx_v == 0) {
            snprintf(mx_s, sizeof(mx_s), "-");
          } else {
            snprintf(mx_s, sizeof(mx_s), "%.1f", (double) (mx_v > 99999900UL ? 99999900UL : mx_v) / 1000.0);
          }
          const uint32_t lg_v = id(failback_shadow_gap_last_long_ms);
          if (lg_v == 0) {
            snprintf(lg_s, sizeof(lg_s), "-");
          } else {
            snprintf(lg_s, sizeof(lg_s), "%.1f", (double) (lg_v > 99999900UL ? 99999900UL : lg_v) / 1000.0);
          }
          const uint32_t ncm_v = (uint32_t) id(failback_shadow_ncm_ms) / 1000;
          char soak_s[201];
          snprintf(soak_s, sizeof(soak_s),
                   "b=%08X;h=%u/%u/%u/%u/%u/%u;mx=%s;lg=%s;gm=%u;lx=%u;wr=%u/%u/%u/0;nc=%u;ncm=%u",
                   (unsigned) id(supervision_boot_nonce),
                   (unsigned) id(failback_shadow_gap_b0), (unsigned) id(failback_shadow_gap_b1),
                   (unsigned) id(failback_shadow_gap_b2), (unsigned) id(failback_shadow_gap_b3),
                   (unsigned) id(failback_shadow_gap_b4), (unsigned) id(failback_shadow_gap_b5),
                   mx_s, lg_s, (unsigned) id(failback_shadow_gaps_missed), (unsigned) id(failback_shadow_ep),
                   (unsigned) id(failback_shadow_wr_fp), (unsigned) id(failback_shadow_wr_dump),
                   (unsigned) id(failback_shadow_wr_r244), (unsigned) id(failback_shadow_nc),
                   (unsigned) (ncm_v > 999999UL ? 999999UL : ncm_v));
          if (id(failback_shadow_soak_text).state != soak_s &&
              (first || soak_now ||
               (uint32_t) (now - id(failback_shadow_last_pub_soak_ms)) >= ${ecco_failback_shadow_soak_publish_min_ms}UL)) {
            id(failback_shadow_soak_text).publish_state(soak_s);
            id(failback_shadow_last_pub_soak_ms) = now;
          }

"""

# ---------------------------------------------------------------------------
# Anchors: (block, where, anchor). `where` is "after" or "before" the anchor.
# Every anchor must occur exactly once in the firmware WITHOUT the blocks.
# ---------------------------------------------------------------------------
_SUBS_ANCHOR = '  ecco_supervision_stable_min_span_ms: "55000"\n'
_GLOBALS_ANCHOR = (
    "  - id: diag_correction_lock_max_ms\n"
    "    type: uint32_t\n"
    "    restore_value: no\n"
    "    initial_value: '0'\n"
)
_TEXT_ANCHOR = (
    "  - platform: template\n"
    '    name: "Reg244 Test Last Result"\n'
    "    id: reg244_last_result\n"
    "    update_interval: never\n"
    '    icon: "mdi:clipboard-check-outline"\n'
)
_INTERVAL_ANCHOR = "  # HA supervision heartbeat - PR A, OBSERVE-ONLY evaluation tick. RAM only:\n"

EDITS = [
    ("substitutions", SUBSTITUTIONS_BLOCK, "after", _SUBS_ANCHOR),
    ("globals", GLOBALS_BLOCK, "after", _GLOBALS_ANCHOR),
    ("text_sensor", TEXT_SENSORS_BLOCK, "after", _TEXT_ANCHOR),
    ("interval", INTERVAL_BLOCK, "before", _INTERVAL_ANCHOR),
]

# FB-A's reserved tokens (`ecco_failback` et al., _scope_chain.BANNED) that
# FB-C1 adds to the firmware YAML, per block: the five substitution keys and
# the nine ${ecco_failback_shadow_*} references in the interval. Chain entry
# fbc1 declares the total (banned_fw_added=14); the suite measures the split.
BANNED_FW_BY_BLOCK = {"substitutions": 5, "globals": 0, "text_sensor": 0, "interval": 9}


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _once(text: str, needle: str, what: str) -> int:
    n = text.count(needle)
    if n != 1:
        raise AssertionError(f"FB-C1 scope: {what} must occur exactly once, found {n}")
    return text.index(needle)


def pre_fbc1_text(text: str) -> str:
    """The firmware text with exactly FB-C1's four blocks removed (the
    exact-match reverter of chain entry fbc1). Every block must occur exactly
    once, directly after / before its anchor, else AssertionError."""
    out = text
    for name, block, where, anchor in EDITS:
        _once(out, block, f"{name} block")
        placed = anchor + block if where == "after" else block + anchor
        pos = _once(out, placed, f"{name} block at its anchor")
        out = out[:pos] + anchor + out[pos + len(placed):]
        # After removal the anchor must again be unique (nothing else matches it).
        _once(out, anchor, f"{name} anchor")
    return out


def add_fbc1_text(text: str) -> str:
    """Applies FB-C1 to a firmware text that has none of it (used to generate
    the change and by the suite's round trip). Every anchor must be unique and
    no block may already be present."""
    out = text
    for name, block, where, anchor in EDITS:
        if block in out:
            raise AssertionError(f"FB-C1 scope: {name} block already present")
        pos = _once(out, anchor, f"{name} anchor")
        pos = pos + len(anchor) if where == "after" else pos
        out = out[:pos] + block + out[pos:]
    return out
