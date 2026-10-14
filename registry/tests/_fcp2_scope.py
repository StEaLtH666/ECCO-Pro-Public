"""fcp2 (full-capability Dump-to-Grid, phase 2: safety hardening) change scope: exactly what fcp2 changes in
firmware/ecco_clock_dongle_stage3_4_free_power.yaml, and its exact inverse.

Same technique as _fcp1_scope.py: the verbatim edits are held HERE as the single source of truth, as exact (before, after) pairs,
and the reverter raises unless every edit is present exactly once. The post-export chain entry `fcp2` (registry/tests/_scope_chain.py
POST_EXPORT_ENTRIES, appended last after fcp1; registry/tests/_pex.py) carries `pre_fcp2_firmware`: the current firmware text with
exactly these edits removed, which reproduces the fcp1 firmware byte for byte (BASE_FW_SHA = the chain's fcp1 checkpoint).

WHAT fcp2 IS (owner decision 2026-10-13: the safety work that must be in the ONE eventual flash before any Dump power above 3000 W).
Every item below is offline-implemented and simulator-tested only.

  SG-40  no controller write after END. Once the write mutex is held, and again in the same synchronous step that issues the
         256-261 write, the controller re-checks that the lease is still live (active, no End/restore requested, no restore running,
         not corrupt, the obligation marker RESTORE_REQUIRED). If not, the write is CANCELLED: never issued, verified, recorded or
         published; the mutex is released and the lease's restore proceeds.
  R-1    windowed, efficiency-aware runaway guard. The consecutive-sample counters are unchanged (never looser than before); an
         8-sample history of VALID battery samples adds k-of-8 decisions against the ordinary threshold, the absolute backstop and
         a gross level, latched at the sample that completes them, so an alternating (50 % duty) overshoot trips. Above
         ecco_dump_runaway_backstop_floor_w (3000 W) the backstop's margin grows by the profile's DC-over-AC allowance
         (ecco_dump_runaway_dc_allowance_pct) of the command above that floor; at or below it the margin is unchanged.
  SG-08  ownership-checked restore (also SG-29c's duplicate restoration; reworked after the independent audit). restore_dump_to_grid_
         snapshot first fresh-reads 244-261 (one 18-register read) and classifies each register ORIGINAL / ECCO's own (244:
         Allow Export; 256-261: the verified or pending ceiling - Dump V2's evidence - or the containment value) / FOREIGN. 244 is
         restored FIRST (its completion flag reset before the write). If 244 is proven out of ECCO's Allow Export, ECCO's own
         256-261 slots return to ORIGINAL (the 6-register write when nothing is FOREIGN, else one register at a time); if NOT,
         every non-FOREIGN slot is CONTAINED at min(original, 500 W) and the attempt fails with its retries. A FOREIGN value is
         never written; the FOREIGN operator lockout (the existing retry record) follows only when everything ECCO attempted was
         written AND verified. A failed or timed-out pre-read writes nothing. Force Restore Original remains the operator's
         override.
  R1/R2/R3/R4/F1/F3/F4 (the independent audit): post-END supervision while 244 is unproven; the export guard without a start grace,
         latched (one far reading or two consecutive) and acted on within 1 s; START refuses measured export above the limit, a
         visible PV surplus above it and a target without headroom; both limits re-confirmed after INVALID; Accept refuses ECCO's
         raised residue; a windowed-mean runaway criterion; an idle battery is not frozen and a toggling SOC cannot reset the
         frozen-SOC count; no stale link-down stamp; the stuck-lock restart waits for a quiet bus.
  SG-15/43 frozen telemetry: during a settled lease, battery power repeating exactly for ecco_dump_frozen_samples reads, the grid
         CT repeating exactly that long while the battery moved more than ecco_dump_frozen_cross_w (or for
         ecco_dump_frozen_ct_long_samples reads regardless), or more than ecco_dump_soc_frozen_wh discharged with no SOC change,
         ends the lease (common restore path). SG-39: a restore that failed while the link was down is retried as soon as a
         telemetry read succeeds again (the backoff shortened to its first step), not up to 300 s later.
  SG-36/07/16 restart and flash safety: the raw reboot is internal; the "Restart" button is gated by ecco_safety_census (refused
         during any transaction or owed lease / restore / recovery decision; an owed obligation - never a transaction in flight -
         may be overridden with "Restart Override Arm"); ECCO Safe To Flash / Flash Readiness / Build Identity; explicit safe_mode
         (ESPHome's defaults).
  SG-14/42 a lock is never released by time: an inverter transaction lock held beyond ecco_write_lock_stuck_ms is STUCK - an
         active Dump lease is ended durably and, while anything is owed, the device restarts so the boot path completes it;
         nothing owed: reported only.

  ZERO new write domain and an unchanged set of written start addresses (register 245 untouched); six one-register restore writes
  of 256..261; ONE new read (the pre-read); no persisted global,
  durable record schema, tag or header change (every new global is RAM only; the one new commit site writes the existing retry
  record exactly as the mismatch lockout does).

This module imports no other scope module and not _scope_chain (the chain imports it). No I/O.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

# The accepted fcp1 candidate this change is based on (dev/full-capability-fcp1).
BASE_COMMIT = "db969cb5a7134b44f6791e69a7274aaa94ec9525"
FIRMWARE_REL = "firmware/ecco_clock_dongle_stage3_4_free_power.yaml"
# sha256 (LF) of the firmware YAML at BASE_COMMIT (= the chain's fcp1 checkpoint): what pre_fcp2_firmware() must reproduce.
BASE_FW_SHA = "3101b8a921c8ac72cf42c8f95ae5b260e65d698f17c087bb5df3cb4510e11003"

ADDED_FILES = frozenset({
    "docs/dev/dump-to-grid-safety-fcp2.md",
    "registry/tests/_fcp2_scope.py",
    "registry/tests/fixtures/dump_lease_residuals_fcp2.json",
    "registry/tests/test_dump_safety_fcp2.py",
})

# The substitutions fcp2 adds (key -> EXACT value).
SUBSTITUTIONS = {
    'ecco_dump_runaway_dc_allowance_pct': '12',
    'ecco_dump_runaway_window_k': '4',
    'ecco_dump_runaway_gross_k': '3',
    'ecco_dump_runaway_mean_margin_w': '300',
    'ecco_dump_frozen_samples': '6',
    'ecco_dump_frozen_cross_w': '150',
    'ecco_dump_frozen_ct_long_samples': '30',
    'ecco_dump_soc_frozen_wh': '1500',
    'ecco_dump_frozen_idle_w': '50',
    'ecco_dump_link_down_ms': '25000',
    'ecco_build_tag': 'unrecorded-build',
    'ecco_write_lock_stuck_ms': '180000',
    'ecco_dump_export_far_min_w': '500',
}

# Every global fcp2 adds (all RAM only: restore_value no).
NEW_GLOBAL_IDS = ('dump_runaway_win_ord', 'dump_runaway_win_abs', 'dump_runaway_win_gross', 'dump_runaway_trip', 'dump_runaway_trip_w', 'dump_runaway_trip_threshold_w', 'dump_runaway_trip_count', 'dump_ct_same_count', 'dump_ct_last_w', 'dump_ct_same_bmin', 'dump_ct_same_bmax', 'dump_bp_same_count', 'dump_bp_last_w', 'dump_bp_last_ms', 'dump_soc_frozen_wh_acc', 'dump_soc_last_value', 'dump_restore_failed_ms', 'ecco_unsafe_reason', 'ecco_unsafe_busy', 'ecco_restart_arm_ms', 'ecco_lock_since_ms', 'ecco_lock_stuck', 'ecco_lock_escalated', 'dump_export_trip', 'dump_start_surplus_refused', 'dump_start_surplus_w', 'dump_limits_reconfirm', 'dump_runaway_e0', 'dump_runaway_e1', 'dump_runaway_e2', 'dump_runaway_e3', 'dump_runaway_e4', 'dump_runaway_e5', 'dump_runaway_e6', 'dump_runaway_e7', 'dump_runaway_e_n', 'dump_controller_write_cancelled', 'dump_restore_244_action', 'dump_restore_owned_mask', 'dump_restore_foreign_mask', 'dump_restore_wmask', 'dump_restore_v0', 'dump_restore_v1', 'dump_restore_v2', 'dump_restore_v3', 'dump_restore_v4', 'dump_restore_v5', 'dump_restore_pre_ok', 'dump_restore_244_ok', 'dump_restore_contain', 'dump_restore_contained', 'dump_restore_block_failed', 'dump_restore_foreign_this_attempt', 'dump_restore_foreign_detail', 'dump_export_unverified')


def _blk(s: str) -> str:
    """A raw triple-quoted literal that starts on the line after the opening quotes: drops that first newline."""
    assert s.startswith("\n") and s.endswith("\n") and "\r" not in s
    return s[1:]


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class Edit:
    name: str
    before: str
    after: str


def _swap(text: str, find: str, put: str, what: str, state: str) -> str:
    n = text.count(find)
    if n != 1:
        raise AssertionError(f"fcp2 scope: {what} must be {state} exactly once, found {n}x: {find[:70]!r}")
    i = text.index(find)
    return text[:i] + put + text[i + len(find):]


# ---- dc_allowance_subst
DC_ALLOWANCE_SUBST_OLD = _blk(r"""
  ecco_dump_capability_w: "8000"
""")
DC_ALLOWANCE_SUBST_NEW = _blk(r"""
  ecco_dump_capability_w: "8000"
  # fcp2 (R-1): the profile's DC-over-AC allowance for the absolute runaway
  # backstop, in percent of the commanded TOU power. The TOU power registers
  # (256-261) limit the inverter's AC output, while register 190 measures
  # battery DC power including the conversion loss, so a healthy lease draws
  # MORE than its command: the recorded leases on the reference installation
  # show +228..+275 W at 2000 W and +271..+357 W at 3000 W (about 7-12 %).
  # Above ecco_dump_runaway_backstop_floor_w the backstop's margin grows by
  # this share of the command above that floor, so its headroom over a
  # residual of this size is the same at every operating level; at or below
  # the floor the margin is exactly the fixed one it always was. Chosen above
  # every recorded residual. 0..30 (compile-time check).
  ecco_dump_runaway_dc_allowance_pct: "12"
""")

# ---- window_subst
WINDOW_SUBST_OLD = _blk(r"""
  ecco_dump_runaway_backstop_floor_w: "3000"
""")
WINDOW_SUBST_NEW = _blk(r"""
  ecco_dump_runaway_backstop_floor_w: "3000"
  # fcp2 (R-1): WINDOWED runaway detection, IN ADDITION to the consecutive-
  # sample counters above (unchanged, so the guard is never looser than
  # before). Every valid battery-power sample (a published, non-NaN reading
  # after the lease-start grace) is recorded in an 8-sample history against
  # the ordinary threshold, the absolute backstop and a GROSS level (the
  # backstop plus one more absolute margin). The lease ends once
  # ecco_dump_runaway_window_k of the last 8 valid samples are above the
  # ordinary threshold or above the backstop - a sustained 50 %-duty
  # oscillation, which never forms a consecutive run, trips this - or
  # ecco_dump_runaway_gross_k of the last 8 are above the gross level (a
  # large excursion at a lower duty). Two isolated samples never trip it. The consecutive runs of the counters above are
  # read from the same history too. A skipped or NaN sample is never "below":
  # the history simply does not advance. The decision is LATCHED at the
  # sample that completes it, so the 15 s watchdog cannot miss it between two
  # samples; it is cleared only at the next lease START.
  ecco_dump_runaway_window_k: "4"
  ecco_dump_runaway_gross_k: "3"
  # fcp2 rework (F1): the WINDOWED MEAN (energy) criterion, alongside the windows
  # above. Each valid sample's excess over the EXPECTED battery draw - the command
  # times (1 + the profile's DC allowance) - is clipped to [-this, one backstop
  # margin], so a single glitch adds at most one margin and an under-run cannot hide
  # a later excess for long; once 8 valid samples exist, a mean excess above this
  # many W ends the lease (a sustained overshoot that is mostly UNDER the backstop).
  ecco_dump_runaway_mean_margin_w: "300"
""")

# ---- window_asserts
WINDOW_ASSERTS_OLD = _blk(r"""
          static_assert(${ecco_dump_runaway_backstop_floor_w} == (long) ${ecco_dump_runaway_backstop_floor_w}.0f &&
                            ${ecco_dump_controller_min_ceiling_w} < ${ecco_dump_runaway_backstop_floor_w},
                        "Dump runaway backstop floor: a plain decimal integer above the controller floor");
""")
WINDOW_ASSERTS_NEW = _blk(r"""
          static_assert(${ecco_dump_runaway_backstop_floor_w} == (long) ${ecco_dump_runaway_backstop_floor_w}.0f &&
                            ${ecco_dump_controller_min_ceiling_w} < ${ecco_dump_runaway_backstop_floor_w},
                        "Dump runaway backstop floor: a plain decimal integer above the controller floor");
          // fcp2 (R-1): the profile's DC allowance and the runaway windows. k <= 4 of
          // 8 so a sustained 50 %-duty oscillation always trips; gross k >= 3 so two
          // isolated samples never do.
          static_assert(${ecco_dump_runaway_dc_allowance_pct} >= 0 && ${ecco_dump_runaway_dc_allowance_pct} <= 30,
                        "Dump runaway DC allowance: 0 to 30 percent of the command");
          static_assert(${ecco_dump_runaway_window_k} >= 3 && ${ecco_dump_runaway_window_k} <= 4 &&
                            ${ecco_dump_runaway_gross_k} >= 3 && ${ecco_dump_runaway_gross_k} <= ${ecco_dump_runaway_window_k},
                        "Dump runaway windows: k of the last 8 valid samples");
          static_assert(${ecco_dump_runaway_samples} >= 2 && ${ecco_dump_runaway_samples} <= 8 &&
                            ${ecco_dump_runaway_absolute_samples} >= 2 && ${ecco_dump_runaway_absolute_samples} <= 8,
                        "Dump runaway consecutive runs must fit the 8-sample history");
          // fcp2 (SG-15 / SG-43): frozen-telemetry bounds.
          static_assert(${ecco_dump_frozen_samples} >= 4 && ${ecco_dump_frozen_samples} <= 16 &&
                            ${ecco_dump_frozen_ct_long_samples} > ${ecco_dump_frozen_samples} &&
                            ${ecco_dump_frozen_ct_long_samples} <= 60,
                        "Dump frozen telemetry: 4..16 repeats, the long CT window longer but at most 60 samples");
          static_assert(${ecco_dump_frozen_cross_w} >= 50 && ${ecco_dump_soc_frozen_wh} >= 300 && ${ecco_dump_soc_frozen_wh} <= 10000,
                        "Dump frozen telemetry: cross-check >= 50 W; frozen-SOC energy 300..10000 Wh");
          static_assert(${ecco_dump_link_down_ms}UL >= 15000UL && ${ecco_dump_link_down_ms}UL < ${ecco_dump_soc_stale_ms}UL,
                        "Dump restore backoff: the link-down age must exceed one missed poll and stay below the SOC staleness bound");
          static_assert(${ecco_write_lock_stuck_ms}UL >= 60000UL,
                        "Stuck-lock bound: at least 60 s (every transaction step is bounded by a 3 s wait)");
          static_assert(${ecco_dump_runaway_mean_margin_w} >= 150 && ${ecco_dump_runaway_mean_margin_w} <= ${ecco_dump_runaway_absolute_margin_w},
                        "Dump runaway mean criterion: 150 W up to the absolute margin");
""")

# ---- window_globals
WINDOW_GLOBALS_OLD = _blk(r"""
  - id: dump_absolute_overpower_samples
    type: int
    restore_value: no
    initial_value: '0'
""")
WINDOW_GLOBALS_NEW = _blk(r"""
  - id: dump_absolute_overpower_samples
    type: int
    restore_value: no
    initial_value: '0'
  # fcp2 (R-1): the windowed runaway history - bit 0 the newest VALID battery
  # sample, 8 samples - against the ordinary threshold, the absolute backstop
  # and the gross level (see ecco_dump_runaway_window_k). dump_runaway_trip is
  # the LATCHED decision (0 none, 1 ordinary, 2 backstop, 3 gross) with the
  # sample, the threshold and the window count that completed it. Cleared at
  # every lease START; RAM only.
  - id: dump_runaway_win_ord
    type: uint8_t
    restore_value: no
    initial_value: '0'
  - id: dump_runaway_win_abs
    type: uint8_t
    restore_value: no
    initial_value: '0'
  - id: dump_runaway_win_gross
    type: uint8_t
    restore_value: no
    initial_value: '0'
  - id: dump_runaway_trip
    type: uint8_t
    restore_value: no
    initial_value: '0'
  - id: dump_runaway_trip_w
    type: float
    restore_value: no
    initial_value: '0.0'
  - id: dump_runaway_trip_threshold_w
    type: float
    restore_value: no
    initial_value: '0.0'
  - id: dump_runaway_trip_count
    type: int
    restore_value: no
    initial_value: '0'
  # fcp2 (SG-15 / SG-43): frozen-telemetry evidence (see ecco_dump_frozen_samples).
  # RAM only; the counters and the energy count are reset at every START.
  - id: dump_ct_same_count
    type: int
    restore_value: no
    initial_value: '0'
  - id: dump_ct_last_w
    type: float
    restore_value: no
    initial_value: '0.0'
  - id: dump_ct_same_bmin
    type: float
    restore_value: no
    initial_value: '0.0'
  - id: dump_ct_same_bmax
    type: float
    restore_value: no
    initial_value: '0.0'
  - id: dump_bp_same_count
    type: int
    restore_value: no
    initial_value: '0'
  - id: dump_bp_last_w
    type: float
    restore_value: no
    initial_value: '0.0'
  - id: dump_bp_last_ms
    type: uint32_t
    restore_value: no
    initial_value: '0'
  - id: dump_soc_frozen_wh_acc
    type: float
    restore_value: no
    initial_value: '0.0'
  - id: dump_soc_last_value
    type: float
    restore_value: no
    initial_value: '-1.0'
  # fcp2 (SG-39): when the last restore attempt failed on comms WHILE THE LINK WAS
  # DOWN (0 = none, or a failure while telemetry was flowing).
  - id: dump_restore_failed_ms
    type: uint32_t
    restore_value: no
    initial_value: '0'
  # fcp2 (SG-07 / SG-36): the safety census (ecco_safety_census) - what a restart
  # or a flash would interrupt ("" = nothing) and whether it is a transaction in
  # flight; and when the restart override arm was turned on. RAM only.
  - id: ecco_unsafe_reason
    type: std::string
    restore_value: no
    initial_value: '"not yet assessed"'
  - id: ecco_unsafe_busy
    type: bool
    restore_value: no
    initial_value: 'true'
  - id: ecco_restart_arm_ms
    type: uint32_t
    restore_value: no
    initial_value: '0'
  # fcp2 (SG-14 / SG-42): lock age (0 = no inverter transaction lock held), STUCK
  # (held beyond ecco_write_lock_stuck_ms) and whether that episode was escalated.
  - id: ecco_lock_since_ms
    type: uint32_t
    restore_value: no
    initial_value: '0'
  - id: ecco_lock_stuck
    type: bool
    restore_value: no
    initial_value: 'false'
  - id: ecco_lock_escalated
    type: bool
    restore_value: no
    initial_value: 'false'
  # fcp2 rework (R2): the NET GRID EXPORT guard's LATCHED decision (0 none, 1 two consecutive
  # samples over, 2 one sample far over) - see ecco_grid_ct_power's on_value; and START's PV-surplus
  # refusal (see start_dump_to_grid_override). RAM only; cleared at every START.
  - id: dump_export_trip
    type: uint8_t
    restore_value: no
    initial_value: '0'
  - id: dump_start_surplus_refused
    type: bool
    restore_value: no
    initial_value: 'false'
  - id: dump_start_surplus_w
    type: float
    restore_value: no
    initial_value: '0.0'
  # fcp2 rework (R3): after INVALID, which limits have been confirmed again (bit 0 the power
  # ceiling, bit 1 the maximum grid export); VALID only once both are. RAM only.
  - id: dump_limits_reconfirm
    type: uint8_t
    restore_value: no
    initial_value: '0'
  - id: dump_runaway_e0
    type: float
    restore_value: no
    initial_value: '0.0'
  - id: dump_runaway_e1
    type: float
    restore_value: no
    initial_value: '0.0'
  - id: dump_runaway_e2
    type: float
    restore_value: no
    initial_value: '0.0'
  - id: dump_runaway_e3
    type: float
    restore_value: no
    initial_value: '0.0'
  - id: dump_runaway_e4
    type: float
    restore_value: no
    initial_value: '0.0'
  - id: dump_runaway_e5
    type: float
    restore_value: no
    initial_value: '0.0'
  - id: dump_runaway_e6
    type: float
    restore_value: no
    initial_value: '0.0'
  - id: dump_runaway_e7
    type: float
    restore_value: no
    initial_value: '0.0'
  - id: dump_runaway_e_n
    type: int
    restore_value: no
    initial_value: '0'
""")

# ---- abs_margin
ABS_MARGIN_OLD = _blk(r"""
            if (backstop_ref < backstop_floor) backstop_ref = backstop_floor;
            if (!std::isnan(x) && x > backstop_ref + ${ecco_dump_runaway_absolute_margin_w}.0f) {
""")
ABS_MARGIN_NEW = _blk(r"""
            if (backstop_ref < backstop_floor) backstop_ref = backstop_floor;
            // fcp2 (R-1): efficiency-aware absolute margin - see
            // ecco_dump_runaway_dc_allowance_pct. Exactly the fixed margin at or
            // below ecco_dump_runaway_backstop_floor_w.
            float abs_margin = ${ecco_dump_runaway_absolute_margin_w}.0f;
            if (backstop_ref > ${ecco_dump_runaway_backstop_floor_w}.0f) {
              abs_margin += (backstop_ref - ${ecco_dump_runaway_backstop_floor_w}.0f) * (float) ${ecco_dump_runaway_dc_allowance_pct} / 100.0f;
            }
            if (!std::isnan(x) && x > backstop_ref + abs_margin) {
""")

# ---- window_update
WINDOW_UPDATE_OLD = _blk(r"""
            if (!std::isnan(x) && x > requested + margin) {
              id(dump_overpower_samples)++;
              id(dump_overpower_last_w) = x;
            } else {
              id(dump_overpower_samples) = 0;
            }
""")
WINDOW_UPDATE_NEW = _blk(r"""
            if (!std::isnan(x) && x > requested + margin) {
              id(dump_overpower_samples)++;
              id(dump_overpower_last_w) = x;
            } else {
              id(dump_overpower_samples) = 0;
            }
            // fcp2 (R-1): WINDOWED runaway detection - see ecco_dump_runaway_window_k.
            // Only a valid sample advances the history (a NaN is neither above nor
            // below); the first complete decision is latched until the next START.
            if (!std::isnan(x)) {
              float abs_thr = backstop_ref + abs_margin;
              float gross_thr = abs_thr + abs_margin;
              id(dump_runaway_win_ord) = (uint8_t) (((uint32_t) id(dump_runaway_win_ord) << 1) | (x > requested + margin ? 1u : 0u));
              id(dump_runaway_win_abs) = (uint8_t) (((uint32_t) id(dump_runaway_win_abs) << 1) | (x > abs_thr ? 1u : 0u));
              id(dump_runaway_win_gross) = (uint8_t) (((uint32_t) id(dump_runaway_win_gross) << 1) | (x > gross_thr ? 1u : 0u));
              if (id(dump_runaway_trip) == 0) {
                int n_ord = 0;
                int n_abs = 0;
                int n_gross = 0;
                for (int i = 0; i < 8; i++) {
                  n_ord += (id(dump_runaway_win_ord) >> i) & 1;
                  n_abs += (id(dump_runaway_win_abs) >> i) & 1;
                  n_gross += (id(dump_runaway_win_gross) >> i) & 1;
                }
                uint32_t run_ord = (1u << ${ecco_dump_runaway_samples}) - 1u;
                uint32_t run_abs = (1u << ${ecco_dump_runaway_absolute_samples}) - 1u;
                if (n_gross >= ${ecco_dump_runaway_gross_k}) {
                  id(dump_runaway_trip) = 3;
                  id(dump_runaway_trip_threshold_w) = gross_thr;
                  id(dump_runaway_trip_count) = n_gross;
                } else if (n_abs >= ${ecco_dump_runaway_window_k} || ((uint32_t) id(dump_runaway_win_abs) & run_abs) == run_abs) {
                  id(dump_runaway_trip) = 2;
                  id(dump_runaway_trip_threshold_w) = abs_thr;
                  id(dump_runaway_trip_count) = n_abs;
                } else if (n_ord >= ${ecco_dump_runaway_window_k} || ((uint32_t) id(dump_runaway_win_ord) & run_ord) == run_ord) {
                  id(dump_runaway_trip) = 1;
                  id(dump_runaway_trip_threshold_w) = requested + margin;
                  id(dump_runaway_trip_count) = n_ord;
                }
                if (id(dump_runaway_trip) != 0) id(dump_runaway_trip_w) = x;
              }
              // fcp2 rework (F1): the WINDOWED MEAN criterion - see ecco_dump_runaway_mean_margin_w.
              float expected = requested * (1.0f + (float) ${ecco_dump_runaway_dc_allowance_pct} / 100.0f);
              float e = x - expected;
              if (e > abs_margin) e = abs_margin;
              if (e < -${ecco_dump_runaway_mean_margin_w}.0f) e = -${ecco_dump_runaway_mean_margin_w}.0f;
              id(dump_runaway_e7) = id(dump_runaway_e6);
              id(dump_runaway_e6) = id(dump_runaway_e5);
              id(dump_runaway_e5) = id(dump_runaway_e4);
              id(dump_runaway_e4) = id(dump_runaway_e3);
              id(dump_runaway_e3) = id(dump_runaway_e2);
              id(dump_runaway_e2) = id(dump_runaway_e1);
              id(dump_runaway_e1) = id(dump_runaway_e0);
              id(dump_runaway_e0) = e;
              if (id(dump_runaway_e_n) < 8) id(dump_runaway_e_n)++;
              if (id(dump_runaway_trip) == 0 && id(dump_runaway_e_n) >= 8) {
                float mean = (id(dump_runaway_e0) + id(dump_runaway_e1) + id(dump_runaway_e2) + id(dump_runaway_e3) +
                              id(dump_runaway_e4) + id(dump_runaway_e5) + id(dump_runaway_e6) + id(dump_runaway_e7)) / 8.0f;
                if (mean > ${ecco_dump_runaway_mean_margin_w}.0f) {
                  id(dump_runaway_trip) = 4;
                  id(dump_runaway_trip_threshold_w) = expected;
                  id(dump_runaway_trip_w) = mean;
                  id(dump_runaway_trip_count) = 8;
                }
              }
            }
""")

# ---- window_start_clear
WINDOW_START_CLEAR_OLD = _blk(r"""
                              id(dump_overpower_samples) = 0;
                              id(dump_absolute_overpower_samples) = 0;
                              // V1.1: the settle window for both the
""")
WINDOW_START_CLEAR_NEW = _blk(r"""
                              id(dump_overpower_samples) = 0;
                              id(dump_absolute_overpower_samples) = 0;
                              // fcp2 (R-1): a fresh runaway history, no latched decision.
                              id(dump_runaway_win_ord) = 0;
                              id(dump_runaway_win_abs) = 0;
                              id(dump_runaway_win_gross) = 0;
                              id(dump_runaway_trip) = 0;
                              // fcp2 (SG-15 / SG-43): fresh frozen-telemetry evidence.
                              id(dump_ct_same_count) = 0;
                              id(dump_bp_same_count) = 0;
                              id(dump_soc_frozen_wh_acc) = 0.0f;
                              // fcp2 rework (F1 / F3): a fresh mean window, and the frozen-SOC count
                              // starts from today's SOC.
                              id(dump_runaway_e_n) = 0;
                              id(dump_soc_last_value) = id(ecco_battery_soc).has_state() ? id(ecco_battery_soc).state : -1.0f;
                              // V1.1: the settle window for both the
""")

# ---- window_watchdog
WINDOW_WATCHDOG_OLD = _blk(r"""
                        return std::string(msg);
            # fcp1 (2026-10-13): NET GRID EXPORT guard - independent of the power
""")
WINDOW_WATCHDOG_NEW = _blk(r"""
                        return std::string(msg);
            # fcp2 (R-1): the WINDOWED runaway decision, latched by
            # ecco_battery_power's on_value at the sample that completed it (see
            # ecco_dump_runaway_window_k). Checked after the consecutive guards
            # above, so a lease they end in the same tick keeps their reason.
            - if:
                condition:
                  lambda: 'return id(dump_runaway_trip) != 0;'
                then:
                  - script.execute:
                      id: request_dump_end
                      reason: !lambda |-
                        char msg[200];
                        if (id(dump_runaway_trip) == 4) {
                          snprintf(msg, sizeof(msg), "SUSTAINED POWER EXCESS (windowed mean) - battery discharge averaged %.0fW above the expected %.0fW over the last 8 samples", id(dump_runaway_trip_w), id(dump_runaway_trip_threshold_w));
                        } else if (id(dump_runaway_trip) == 3) {
                          snprintf(msg, sizeof(msg), "GROSS POWER RUNAWAY (windowed) - battery discharge above the %.0fW gross level in %d of the last 8 samples (last %.0fW)", id(dump_runaway_trip_threshold_w), id(dump_runaway_trip_count), id(dump_runaway_trip_w));
                        } else if (id(dump_runaway_trip) == 2) {
                          snprintf(msg, sizeof(msg), "ABSOLUTE POWER RUNAWAY (windowed) - battery discharge above the %.0fW absolute backstop in %d of the last 8 samples (last %.0fW)", id(dump_runaway_trip_threshold_w), id(dump_runaway_trip_count), id(dump_runaway_trip_w));
                        } else {
                          snprintf(msg, sizeof(msg), "POWER RUNAWAY (windowed) - battery discharge above the %.0fW lease-ceiling threshold in %d of the last 8 samples (last %.0fW)", id(dump_runaway_trip_threshold_w), id(dump_runaway_trip_count), id(dump_runaway_trip_w));
                        }
                        return std::string(msg);
            # fcp2 (SG-15 / SG-43): FROZEN telemetry during a settled lease - readings
            # that keep arriving but never change are not evidence; see
            # ecco_dump_frozen_samples. Fail closed through the common restore path.
            - if:
                condition:
                  lambda: |-
                    if ((uint32_t) (millis() - id(dump_active_since_ms)) < ${ecco_dump_runaway_grace_ms}UL) return false;
                    bool ct_frozen = (id(dump_ct_same_count) >= ${ecco_dump_frozen_samples} - 1 &&
                                      id(dump_ct_same_bmax) - id(dump_ct_same_bmin) > ${ecco_dump_frozen_cross_w}.0f) ||
                                     id(dump_ct_same_count) >= ${ecco_dump_frozen_ct_long_samples} - 1;
                    return ct_frozen || id(dump_bp_same_count) >= ${ecco_dump_frozen_samples} - 1 ||
                           id(dump_soc_frozen_wh_acc) > ${ecco_dump_soc_frozen_wh}.0f;
                then:
                  - script.execute:
                      id: request_dump_end
                      reason: !lambda |-
                        char msg[200];
                        if (id(dump_bp_same_count) >= ${ecco_dump_frozen_samples} - 1) {
                          snprintf(msg, sizeof(msg), "BATTERY POWER TELEMETRY FROZEN - %d identical readings of %.0fW; the runaway guard cannot be trusted - failing closed", id(dump_bp_same_count) + 1, id(dump_bp_last_w));
                        } else if (id(dump_soc_frozen_wh_acc) > ${ecco_dump_soc_frozen_wh}.0f) {
                          snprintf(msg, sizeof(msg), "SOC TELEMETRY FROZEN - %.0fWh discharged with no SOC change (still %.0f%%); Stop SOC cannot be trusted - failing closed", id(dump_soc_frozen_wh_acc), id(dump_soc_last_value));
                        } else {
                          snprintf(msg, sizeof(msg), "GRID CT FROZEN - %d identical readings of %.0fW while the battery moved %.0fW; the controller and the export guard cannot be trusted - failing closed", id(dump_ct_same_count) + 1, id(dump_ct_last_w), id(dump_ct_same_bmax) - id(dump_ct_same_bmin));
                        }
                        return std::string(msg);
            # fcp1 (2026-10-13): NET GRID EXPORT guard - independent of the power
""")

# ---- sg40_global
SG40_GLOBAL_OLD = _blk(r"""
  - id: dump_controller_op_terminal
""")
SG40_GLOBAL_NEW = _blk(r"""
  # fcp2 (SG-40): set when the controller's write was CANCELLED because the
  # lease stopped being live (ended, an End/restore requested, a restore
  # running, corrupt) after the tick decided to write - checked once the write
  # mutex is held and again in the same step that issues the write. A
  # cancelled write is never issued, verified or recorded. Reset each time
  # the mutex is taken.
  - id: dump_controller_write_cancelled
    type: bool
    restore_value: no
    initial_value: 'false'
  - id: dump_controller_op_terminal
""")

# ---- sg40_reset
SG40_RESET_OLD = _blk(r"""
                      id(dump_controller_evidence_commit_failed) = false;
                      id(dump_controller_op_terminal) = false;
""")
SG40_RESET_NEW = _blk(r"""
                      id(dump_controller_evidence_commit_failed) = false;
                      id(dump_controller_write_cancelled) = false;
                      id(dump_controller_op_terminal) = false;
""")

# ---- sg40_after_mutex
SG40_AFTER_MUTEX_OLD = _blk(r"""
                  - lambda: |-
                      id(dump_evidence_pending_ceiling) = id(dump_controller_pending_ceiling);
                      bool evidence_ok = false;
""")
SG40_AFTER_MUTEX_NEW = _blk(r"""
                  - lambda: |-
                      // fcp2 (SG-40): re-check, now that the write mutex is held, that the
                      // lease is still live and nothing has asked to end it. If not: no
                      // evidence commit, no R3 read, no write - the controller never writes
                      // once a lease is ending, restoring or stopped.
                      if (!id(dump_active_persisted) || id(dump_restore_requested) || id(dump_operation_in_progress) ||
                          id(dump_recovery_metadata_corrupt) || !id(dump_snapshot_valid) ||
                          id(dump_marker_state) != ecco_durable::MARKER_RESTORE_REQUIRED) {
                        id(dump_controller_write_cancelled) = true;
                        return;
                      }
                      id(dump_evidence_pending_ceiling) = id(dump_controller_pending_ceiling);
                      bool evidence_ok = false;
""")

# ---- sg40_r3_gate
SG40_R3_GATE_OLD = _blk(r"""
                  # R3 runs only once the evidence commit above has succeeded.
                  # The R3 block itself is unchanged - only re-indented under
                  # this gate.
                  - if:
                      condition:
                        lambda: 'return !id(dump_controller_write_failed);'
""")
SG40_R3_GATE_NEW = _blk(r"""
                  # R3 runs only once the evidence commit above has succeeded.
                  # The R3 block itself is unchanged - only re-indented under
                  # this gate. fcp2 (SG-40): and never for a cancelled write.
                  - if:
                      condition:
                        lambda: 'return !id(dump_controller_write_failed) && !id(dump_controller_write_cancelled);'
""")

# ---- sg40_write_gate
SG40_WRITE_GATE_OLD = _blk(r"""
                              ESP_LOGE("dump_to_grid", "Ownership re-read of 256-261 did not reach a terminal state before the controller write");
                            }

                  - if:
                      condition:
                        lambda: 'return !id(dump_controller_write_failed);'
""")
SG40_WRITE_GATE_NEW = _blk(r"""
                              ESP_LOGE("dump_to_grid", "Ownership re-read of 256-261 did not reach a terminal state before the controller write");
                            }

                  # fcp2 (SG-40): the LAST check before the write, in the same synchronous
                  # step that issues it. An End/restore request - or any other end of the
                  # lease - that arrived while the R3 read was in flight cancels the write:
                  # once a lease is ending, the controller writes nothing.
                  - if:
                      condition:
                        lambda: |-
                          if (!id(dump_controller_write_failed) &&
                              (!id(dump_active_persisted) || id(dump_restore_requested) || id(dump_operation_in_progress) ||
                               id(dump_recovery_metadata_corrupt) || !id(dump_snapshot_valid) ||
                               id(dump_marker_state) != ecco_durable::MARKER_RESTORE_REQUIRED)) {
                            id(dump_controller_write_cancelled) = true;
                          }
                          return !id(dump_controller_write_failed) && !id(dump_controller_write_cancelled);
""")

# ---- sg40_verify_gate
SG40_VERIFY_GATE_OLD = _blk(r"""
                              ESP_LOGE("dump_to_grid", "Controller write to registers 256-261 did not reach a terminal state");
                            }

                  - if:
                      condition:
                        lambda: 'return !id(dump_controller_write_failed);'
""")
SG40_VERIFY_GATE_NEW = _blk(r"""
                              ESP_LOGE("dump_to_grid", "Controller write to registers 256-261 did not reach a terminal state");
                            }

                  - if:
                      condition:
                        lambda: 'return !id(dump_controller_write_failed) && !id(dump_controller_write_cancelled);'
""")

# ---- sg40_cancel_close
SG40_CANCEL_CLOSE_OLD = _blk(r"""
                        - lambda: |-
                            id(manual_write_in_progress) = false;
                            id(dump_target_power) = id(dump_controller_pending_ceiling);
""")
SG40_CANCEL_CLOSE_NEW = _blk(r"""
                        - lambda: |-
                            id(manual_write_in_progress) = false;
                            // fcp2 (SG-40): a cancelled write was never issued - nothing to
                            // record or publish. The lease is already ending; its restore runs
                            // on the next watchdog tick (the mutex is released above).
                            if (id(dump_controller_write_cancelled)) {
                              id(dump_controller_state) = "WRITE CANCELLED - LEASE ENDING";
                              ESP_LOGW("dump_to_grid", "Controller write cancelled - the lease is ending; nothing written");
                              return;
                            }
                            id(dump_target_power) = id(dump_controller_pending_ceiling);
""")

# ---- restore_globals
RESTORE_GLOBALS_OLD = _blk(r"""
  - id: dump_restore_mismatch_this_attempt
    type: bool
    restore_value: no
    initial_value: 'false'
""")
RESTORE_GLOBALS_NEW = _blk(r"""
  - id: dump_restore_mismatch_this_attempt
    type: bool
    restore_value: no
    initial_value: 'false'
  # fcp2 (SG-08 / SG-29c / SG-04): the restore's OWNERSHIP PRE-READ and plan - see
  # restore_dump_to_grid_snapshot. dump_restore_244_action: 0 = 244 already ORIGINAL,
  # 1 = ECCO's own Allow Export (restore it), 2 = FOREIGN (never written).
  # dump_restore_owned_mask / _foreign_mask: per 256-261 slot (bit 0 = 256), ECCO's own
  # value (the verified or pending ceiling, or the containment value) / an external one.
  # dump_restore_wmask and dump_restore_v0..v5: the slots this attempt writes and their
  # values. dump_restore_244_ok: 244 is proven not exporting by ECCO after this attempt;
  # if not, the plan CONTAINS (dump_restore_contain) instead of restoring.
  # dump_restore_contained: that containment was written AND verified. RAM only.
  - id: dump_restore_244_action
    type: uint8_t
    restore_value: no
    initial_value: '2'
  - id: dump_restore_owned_mask
    type: uint8_t
    restore_value: no
    initial_value: '0'
  - id: dump_restore_foreign_mask
    type: uint8_t
    restore_value: no
    initial_value: '0'
  - id: dump_restore_wmask
    type: uint8_t
    restore_value: no
    initial_value: '0'
  - id: dump_restore_v0
    type: uint16_t
    restore_value: no
    initial_value: '0'
  - id: dump_restore_v1
    type: uint16_t
    restore_value: no
    initial_value: '0'
  - id: dump_restore_v2
    type: uint16_t
    restore_value: no
    initial_value: '0'
  - id: dump_restore_v3
    type: uint16_t
    restore_value: no
    initial_value: '0'
  - id: dump_restore_v4
    type: uint16_t
    restore_value: no
    initial_value: '0'
  - id: dump_restore_v5
    type: uint16_t
    restore_value: no
    initial_value: '0'
  - id: dump_restore_pre_ok
    type: bool
    restore_value: no
    initial_value: 'false'
  - id: dump_restore_244_ok
    type: bool
    restore_value: no
    initial_value: 'false'
  - id: dump_restore_contain
    type: bool
    restore_value: no
    initial_value: 'false'
  - id: dump_restore_contained
    type: bool
    restore_value: no
    initial_value: 'false'
  - id: dump_restore_block_failed
    type: bool
    restore_value: no
    initial_value: 'false'
  # fcp2: set only when everything ECCO attempted this time was written AND verified and
  # a FOREIGN value remains: the operator decides (never after a failed step).
  - id: dump_restore_foreign_this_attempt
    type: bool
    restore_value: no
    initial_value: 'false'
  - id: dump_restore_foreign_detail
    type: std::string
    restore_value: no
    initial_value: '""'
  # fcp2 (R1 / SG-04): register 244 has NOT been proven out of ECCO's Allow Export since
  # the last START (or boot). Set at every START; cleared only by a pre-read or a
  # verified restore of 244. While a restore is owed and this is set, the watchdog keeps
  # supervising export and Stop SOC (see the Dump watchdog). RAM only; true at boot.
  - id: dump_export_unverified
    type: bool
    restore_value: no
    initial_value: 'true'
""")

# ---- restore_body
RESTORE_BODY_OLD = _blk(r"""
            - lambda: |-
                id(dump_operation_in_progress) = true;
                id(manual_write_in_progress) = true;
                id(dump_write_failed) = false;
                id(dump_restore_mismatch_this_attempt) = false;
                id(dump_op_terminal) = false;
                id(dump_status).publish_state("RESTORING - writing back original inverter settings");
                ESP_LOGW("dump_to_grid", "Restoring Dump to Grid snapshot");

            - modbus_client.write_multiple_registers:
                modbus_id: inverter_modbus
                address: 0x01
                start_address: 244
                values: !lambda 'return std::vector<uint16_t>{id(dump_snapshot_reg244)};'
                on_response:
                  then:
                    - lambda: 'id(dump_op_terminal) = true;'
                on_error:
                  then:
                    - lambda: |-
                        id(dump_op_terminal) = true;
                        if (id(dump_operation_in_progress)) id(dump_write_failed) = true;
                on_no_response:
                  then:
                    - lambda: |-
                        id(dump_op_terminal) = true;
                        if (id(dump_operation_in_progress)) id(dump_write_failed) = true;
                on_not_sent:
                  then:
                    - lambda: |-
                        id(dump_op_terminal) = true;
                        if (id(dump_operation_in_progress)) id(dump_write_failed) = true;

            - wait_until:
                condition:
                  lambda: 'return id(dump_op_terminal);'
                timeout: 3000ms
            - lambda: |-
                if (!id(dump_op_terminal)) {
                  id(dump_write_failed) = true;
                  ESP_LOGE("dump_to_grid", "Restore write to register 244 did not reach a terminal state");
                }

            - if:
                condition:
                  lambda: 'return !id(dump_write_failed);'
                then:
                  - lambda: 'id(dump_op_terminal) = false;'
                  - modbus_client.read_holding_registers:
                      modbus_id: inverter_modbus
                      address: 0x01
                      start_address: 244
                      count: 1
                      on_response:
                        then:
                          - lambda: |-
                              id(dump_op_terminal) = true;
                              if (!id(dump_operation_in_progress)) return;
                              uint16_t raw = values[0];
                              const char* names[3] = {"Allow Export", "Essentials", "Zero Export"};
                              if (raw <= 2) id(ecco_load_limit).publish_state(names[raw]);
                              if (raw != id(dump_snapshot_reg244)) {
                                id(dump_write_failed) = true;
                                id(dump_restore_mismatch_this_attempt) = true;
                                ESP_LOGE("dump_to_grid", "RESTORE VERIFY FAILED on register 244 (raw=%u expected=%u)", raw, id(dump_snapshot_reg244));
                              }
                      on_error:
                        then:
                          - lambda: |-
                              id(dump_op_terminal) = true;
                              if (id(dump_operation_in_progress)) id(dump_write_failed) = true;
                      on_no_response:
                        then:
                          - lambda: |-
                              id(dump_op_terminal) = true;
                              if (id(dump_operation_in_progress)) id(dump_write_failed) = true;
                      on_not_sent:
                        then:
                          - lambda: |-
                              id(dump_op_terminal) = true;
                              if (id(dump_operation_in_progress)) id(dump_write_failed) = true;

                  - wait_until:
                      condition:
                        lambda: 'return id(dump_op_terminal);'
                      timeout: 3000ms
                  - lambda: |-
                      if (!id(dump_op_terminal)) {
                        id(dump_write_failed) = true;
                        ESP_LOGE("dump_to_grid", "Restore verify reread of register 244 did not reach a terminal state");
                      }

            - if:
                condition:
                  lambda: 'return !id(dump_write_failed);'
                then:
                  - lambda: 'id(dump_op_terminal) = false;'
                  - modbus_client.write_multiple_registers:
                      modbus_id: inverter_modbus
                      address: 0x01
                      start_address: 256
                      values: !lambda |-
                        return std::vector<uint16_t>{
                          id(dump_snapshot_reg256), id(dump_snapshot_reg257), id(dump_snapshot_reg258),
                          id(dump_snapshot_reg259), id(dump_snapshot_reg260), id(dump_snapshot_reg261)
                        };
                      on_response:
                        then:
                          - lambda: 'id(dump_op_terminal) = true;'
                      on_error:
                        then:
                          - lambda: |-
                              id(dump_op_terminal) = true;
                              if (id(dump_operation_in_progress)) id(dump_write_failed) = true;
                      on_no_response:
                        then:
                          - lambda: |-
                              id(dump_op_terminal) = true;
                              if (id(dump_operation_in_progress)) id(dump_write_failed) = true;
                      on_not_sent:
                        then:
                          - lambda: |-
                              id(dump_op_terminal) = true;
                              if (id(dump_operation_in_progress)) id(dump_write_failed) = true;

                  - wait_until:
                      condition:
                        lambda: 'return id(dump_op_terminal);'
                      timeout: 3000ms
                  - lambda: |-
                      if (!id(dump_op_terminal)) {
                        id(dump_write_failed) = true;
                        ESP_LOGE("dump_to_grid", "Restore write to registers 256-261 did not reach a terminal state");
                      }

                  - if:
                      condition:
                        lambda: 'return !id(dump_write_failed);'
                      then:
                        - lambda: 'id(dump_op_terminal) = false;'
                        - modbus_client.read_holding_registers:
                            modbus_id: inverter_modbus
                            address: 0x01
                            start_address: 256
                            count: 6
                            on_response:
                              then:
                                - lambda: |-
                                    id(dump_op_terminal) = true;
                                    if (!id(dump_operation_in_progress)) return;
                                    bool ok = values[0] == id(dump_snapshot_reg256) && values[1] == id(dump_snapshot_reg257) &&
                                              values[2] == id(dump_snapshot_reg258) && values[3] == id(dump_snapshot_reg259) &&
                                              values[4] == id(dump_snapshot_reg260) && values[5] == id(dump_snapshot_reg261);
                                    if (!ok) {
                                      id(dump_write_failed) = true;
                                      id(dump_restore_mismatch_this_attempt) = true;
                                      ESP_LOGE("dump_to_grid", "RESTORE VERIFY FAILED on registers 256-261");
                                    }
                            on_error:
                              then:
                                - lambda: |-
                                    id(dump_op_terminal) = true;
                                    if (id(dump_operation_in_progress)) id(dump_write_failed) = true;
                            on_no_response:
                              then:
                                - lambda: |-
                                    id(dump_op_terminal) = true;
                                    if (id(dump_operation_in_progress)) id(dump_write_failed) = true;
                            on_not_sent:
                              then:
                                - lambda: |-
                                    id(dump_op_terminal) = true;
                                    if (id(dump_operation_in_progress)) id(dump_write_failed) = true;

                        - wait_until:
                            condition:
                              lambda: 'return id(dump_op_terminal);'
                            timeout: 3000ms
                        - lambda: |-
                            if (!id(dump_op_terminal)) {
                              id(dump_write_failed) = true;
                              ESP_LOGE("dump_to_grid", "Restore verify reread of 256-261 did not reach a terminal state");
                            }

            - if:
                condition:
                  lambda: 'return !id(dump_write_failed);'
                then:
                  - lambda: |-
                      ecco_durable::ValidMarker pending{};
                      pending.magic = ecco_durable::VALID_MARKER_MAGIC;
                      pending.state = ecco_durable::MARKER_RESTORE_VERIFIED_PENDING_CLEAR;
                      bool pending_ok = ecco_durable::commit_record(
                        ecco_durable::key_for(ecco_durable::DUMP_TO_GRID_VALID_TAG), pending);
                      if (pending_ok) id(dump_marker_state) = ecco_durable::MARKER_RESTORE_VERIFIED_PENDING_CLEAR;

                      ecco_durable::ValidMarker clear{};
                      clear.magic = ecco_durable::VALID_MARKER_MAGIC;
                      clear.state = ecco_durable::MARKER_CLEAR;
                      bool clear_ok = pending_ok && ecco_durable::commit_record(
                        ecco_durable::key_for(ecco_durable::DUMP_TO_GRID_VALID_TAG), clear);

                      if (clear_ok) {
                        id(dump_marker_state) = ecco_durable::MARKER_CLEAR;
                        id(dump_snapshot_valid) = false;
                        id(dump_active_persisted) = false;
                        id(dump_restore_requested) = false;
                        id(dump_operator_retry_pending) = false;
                        id(dump_comms_restore_attempts) = 0;
                        id(dump_restore_next_attempt_ms) = 0;
                        id(dump_verify_mismatch_count) = 0;
                        id(dump_restore_successes)++;
                        id(dump_controller_state) = "IDLE";
                        id(dump_controller_state_sensor).publish_state("IDLE");
                        // A verified clear resolves any prior lockout too -
                        // durably, not just in RAM, matching the durable set
                        // in the failure branch below.
                        if (id(dump_operator_needed)) {
                          ecco_durable::DumpToGridRetryState retry{};
                          retry.operator_needed = 0;
                          ecco_durable::commit_record(ecco_durable::key_for(ecco_durable::DUMP_TO_GRID_RETRY_TAG), retry);
                          id(dump_operator_needed) = false;
                        }
                        id(dump_status).publish_state("RESTORED OK - original inverter settings verified");
                        ESP_LOGW("dump_to_grid", "Dump to Grid RESTORED OK");
                      } else {
                        // Hardware IS confirmed restored (pending_ok's write
                        // happened before this branch, or the verify above
                        // already passed) but the durable CLEAR itself could
                        // not be committed. Leave the marker as whatever it
                        // durably reached - never invent CLEAR in RAM only.
                        id(dump_status).publish_state(
                          "RESTORE VERIFIED - durable clear pending; will retry automatically"
                        );
                        ESP_LOGE("dump_to_grid", "Hardware restored but durable clear commit failed - will retry");
                      }
                      id(dump_operation_in_progress) = false;
                      id(manual_write_in_progress) = false;
                else:
                  # 2026-09-26 independent review: cause-aware, mirroring
                  # restore_free_power_snapshot_dispatch. Only a VERIFY
                  # MISMATCH counts towards the durable operator lockout; a
                  # COMMS failure keeps retrying automatically under the
                  # bounded backoff (15s..300s), because the restore is the
                  # safe direction and a lockout here stops both the timed
                  # end and Stop SOC enforcement while export may still be
                  # enabled.
                  - lambda: |-
                      id(dump_failures)++;
                      id(dump_operation_in_progress) = false;
                      id(manual_write_in_progress) = false;
                      if (id(dump_restore_mismatch_this_attempt)) {
                        id(dump_verify_mismatch_count)++;
                        if (id(dump_verify_mismatch_count) >= 2) {
                          ecco_durable::DumpToGridRetryState retry{};
                          retry.operator_needed = 1;
                          if (!ecco_durable::commit_record(ecco_durable::key_for(ecco_durable::DUMP_TO_GRID_RETRY_TAG), retry)) {
                            // Same documented pacing-only fail-open as Free
                            // Power: enforced in RAM for this runtime even if
                            // the durable record could not be written.
                            ESP_LOGW("dump_to_grid", "Could not durably record operator-needed lockout - enforced for this runtime only");
                          }
                          id(dump_operator_needed) = true;
                          id(dump_recovery_last_classification) = 0;
                          id(dump_recovery_state).publish_state(
                            "NEITHER (fail-closed default) - repeated restore verify mismatch"
                          );
                          id(dump_status).publish_state(
                            "OPERATOR DECISION REQUIRED - repeated verify mismatch restoring Dump to Grid; use Force Restore Original or Accept Current State"
                          );
                          ESP_LOGE("dump_to_grid", "Second consecutive restore verify mismatch - automatic retries stopped, operator needed");
                        } else {
                          id(dump_status).publish_state(
                            "RESTORE VERIFY FAILED - snapshot retained; watchdog will retry once automatically"
                          );
                          ESP_LOGE("dump_to_grid", "Restore verify mismatch - watchdog will retry once");
                        }
                      } else {
                        id(dump_comms_restore_attempts)++;
                        id(dump_restore_next_attempt_ms) = millis() + ecco_durable::comms_backoff_ms(id(dump_comms_restore_attempts));
                        id(dump_status).publish_state(
                          "RESTORE WRITE FAILED - inverter did not respond or refused; snapshot retained; will retry automatically with backoff"
                        );
                        ESP_LOGW("dump_to_grid", "Restore attempt failed (comms) - watchdog will retry with backoff");
                      }
""")
RESTORE_BODY_NEW = _blk(r"""
            - lambda: |-
                id(dump_operation_in_progress) = true;
                id(manual_write_in_progress) = true;
                id(dump_write_failed) = false;
                id(dump_restore_mismatch_this_attempt) = false;
                id(dump_op_terminal) = false;
                id(dump_status).publish_state("RESTORING - writing back original inverter settings");
                ESP_LOGW("dump_to_grid", "Restoring Dump to Grid snapshot");

            # fcp2 (SG-08 / SG-29c / SG-04, reworked after the independent audit): OWNERSHIP
            # PRE-READ - fresh-read 244-261 inside this same critical section (the mutex and
            # dump_operation_in_progress are held) BEFORE writing anything. Each register is
            # ORIGINAL (left alone), ECCO's own (written back) or FOREIGN (an external change:
            # the app, the front panel, another Modbus master, an inverter reset - NEVER
            # written). 244 is restored FIRST. If 244 is then NOT proven out of ECCO's Allow
            # Export, the 256-261 step CONTAINS instead of restoring: every non-FOREIGN slot to
            # min(original, the controller floor), so an export ECCO cannot switch off is
            # bounded; the attempt still fails and keeps its retries and its obligation. A
            # FOREIGN value ends in the operator lockout ONLY when everything ECCO attempted was
            # written AND verified. A failed or timed-out pre-read writes nothing (comms
            # backoff). A repeat run after a verified restore finds ORIGINAL and writes nothing.
            # Force Restore Original (the operator's deliberate override) still needs the read,
            # then writes the whole ORIGINAL snapshot.
            - lambda: |-
                id(dump_op_terminal) = false;
                id(dump_restore_pre_ok) = false;
                id(dump_restore_244_action) = 2;
                id(dump_restore_owned_mask) = 0;
                id(dump_restore_foreign_mask) = 0;
                id(dump_restore_wmask) = 0;
                id(dump_restore_244_ok) = false;
                id(dump_restore_contain) = false;
                id(dump_restore_contained) = false;
                id(dump_restore_block_failed) = false;
                id(dump_restore_foreign_this_attempt) = false;
                id(dump_restore_foreign_detail) = "";
            - modbus_client.read_holding_registers:
                modbus_id: inverter_modbus
                address: 0x01
                start_address: 244
                count: 18
                on_response:
                  then:
                    - lambda: |-
                        id(dump_op_terminal) = true;
                        if (!id(dump_operation_in_progress)) return;
                        char d[160];
                        uint16_t v244 = values[0];
                        if (v244 == id(dump_snapshot_reg244)) {
                          id(dump_restore_244_action) = 0;
                        } else if (v244 == 0) {
                          id(dump_restore_244_action) = 1;
                        } else {
                          id(dump_restore_244_action) = 2;
                          snprintf(d, sizeof(d), "register 244 reads %u (original %u; ECCO writes only 0)", v244, id(dump_snapshot_reg244));
                          id(dump_restore_foreign_detail) = d;
                        }
                        // 244 is proven out of ECCO's Allow Export unless it still reads 0 over a non-0 original.
                        id(dump_export_unverified) = v244 == 0 && id(dump_snapshot_reg244) != 0;
                        uint16_t orig[6] = {
                          id(dump_snapshot_reg256), id(dump_snapshot_reg257), id(dump_snapshot_reg258),
                          id(dump_snapshot_reg259), id(dump_snapshot_reg260), id(dump_snapshot_reg261)
                        };
                        uint8_t owned = 0;
                        uint8_t foreign = 0;
                        for (int i = 0; i < 6; i++) {
                          uint16_t live = values[12 + i];
                          uint16_t floor_v = orig[i] < ${ecco_dump_controller_min_ceiling_w} ? orig[i] : (uint16_t) ${ecco_dump_controller_min_ceiling_w};
                          bool ecco_value = live == id(dump_target_power) || live == id(dump_evidence_pending_ceiling) || live == floor_v;
                          if (live != orig[i] && ecco_value) {
                            owned = (uint8_t) (owned | (1 << i));
                          } else if (live != orig[i]) {
                            if (foreign == 0 && id(dump_restore_244_action) != 2) {
                              snprintf(d, sizeof(d), "register %d reads %uW (original %uW; ECCO's ceiling %uW, pending %uW)", 256 + i, live, orig[i], (unsigned) id(dump_target_power), (unsigned) id(dump_evidence_pending_ceiling));
                              id(dump_restore_foreign_detail) = d;
                            }
                            foreign = (uint8_t) (foreign | (1 << i));
                          }
                        }
                        id(dump_restore_owned_mask) = owned;
                        id(dump_restore_foreign_mask) = foreign;
                        id(dump_restore_pre_ok) = true;
                on_error:
                  then:
                    - lambda: |-
                        id(dump_op_terminal) = true;
                        if (id(dump_operation_in_progress)) id(dump_write_failed) = true;
                on_no_response:
                  then:
                    - lambda: |-
                        id(dump_op_terminal) = true;
                        if (id(dump_operation_in_progress)) id(dump_write_failed) = true;
                on_not_sent:
                  then:
                    - lambda: |-
                        id(dump_op_terminal) = true;
                        if (id(dump_operation_in_progress)) id(dump_write_failed) = true;

            - wait_until:
                condition:
                  lambda: 'return id(dump_op_terminal);'
                timeout: 3000ms
            - lambda: |-
                if (!id(dump_op_terminal)) {
                  id(dump_write_failed) = true;
                  ESP_LOGE("dump_to_grid", "Restore ownership pre-read of 244-261 did not reach a terminal state");
                }
                if (id(dump_write_failed)) id(dump_restore_pre_ok) = false;
                if (id(dump_restore_pre_ok) && id(dump_force_restore_this_call)) {
                  // The operator's deliberate Force Restore Original: the whole ORIGINAL snapshot.
                  id(dump_restore_244_action) = 1;
                  id(dump_restore_owned_mask) = 0x3F;
                  id(dump_restore_foreign_mask) = 0;
                }
                if (id(dump_restore_pre_ok)) {
                  ESP_LOGI("dump_to_grid", "Restore pre-read: 244 %s, 256-261 owned 0x%02X foreign 0x%02X",
                           id(dump_restore_244_action) == 0 ? "ORIGINAL" : (id(dump_restore_244_action) == 1 ? "ECCO-owned" : "FOREIGN"),
                           (unsigned) id(dump_restore_owned_mask), (unsigned) id(dump_restore_foreign_mask));
                }

            # A - register 244 (the export enable) FIRST, only when it still holds ECCO's own
            # Allow Export. fcp2 rework: its completion flag is reset HERE - the pre-read's reply
            # set it, and without this reset every later wait would be satisfied by the previous
            # command's reply on the real (asynchronous) Modbus hub.
            - if:
                condition:
                  lambda: 'return id(dump_restore_pre_ok) && id(dump_restore_244_action) == 1;'
                then:
                - lambda: 'id(dump_op_terminal) = false;'
                - modbus_client.write_multiple_registers:
                    modbus_id: inverter_modbus
                    address: 0x01
                    start_address: 244
                    values: !lambda 'return std::vector<uint16_t>{id(dump_snapshot_reg244)};'
                    on_response:
                      then:
                        - lambda: 'id(dump_op_terminal) = true;'
                    on_error:
                      then:
                        - lambda: |-
                            id(dump_op_terminal) = true;
                            if (id(dump_operation_in_progress)) id(dump_write_failed) = true;
                    on_no_response:
                      then:
                        - lambda: |-
                            id(dump_op_terminal) = true;
                            if (id(dump_operation_in_progress)) id(dump_write_failed) = true;
                    on_not_sent:
                      then:
                        - lambda: |-
                            id(dump_op_terminal) = true;
                            if (id(dump_operation_in_progress)) id(dump_write_failed) = true;

                - wait_until:
                    condition:
                      lambda: 'return id(dump_op_terminal);'
                    timeout: 3000ms
                - lambda: |-
                    if (!id(dump_op_terminal)) {
                      id(dump_write_failed) = true;
                      ESP_LOGE("dump_to_grid", "Restore write to register 244 did not reach a terminal state");
                    }

                - if:
                    condition:
                      lambda: 'return !id(dump_write_failed);'
                    then:
                      - lambda: 'id(dump_op_terminal) = false;'
                      - modbus_client.read_holding_registers:
                          modbus_id: inverter_modbus
                          address: 0x01
                          start_address: 244
                          count: 1
                          on_response:
                            then:
                              - lambda: |-
                                  id(dump_op_terminal) = true;
                                  if (!id(dump_operation_in_progress)) return;
                                  uint16_t raw = values[0];
                                  const char* names[3] = {"Allow Export", "Essentials", "Zero Export"};
                                  if (raw <= 2) id(ecco_load_limit).publish_state(names[raw]);
                                  if (raw != id(dump_snapshot_reg244)) {
                                    id(dump_write_failed) = true;
                                    id(dump_restore_mismatch_this_attempt) = true;
                                    ESP_LOGE("dump_to_grid", "RESTORE VERIFY FAILED on register 244 (raw=%u expected=%u)", raw, id(dump_snapshot_reg244));
                                  } else {
                                    id(dump_export_unverified) = false;   // fcp2: 244 proven back to its original
                                  }
                          on_error:
                            then:
                              - lambda: |-
                                  id(dump_op_terminal) = true;
                                  if (id(dump_operation_in_progress)) id(dump_write_failed) = true;
                          on_no_response:
                            then:
                              - lambda: |-
                                  id(dump_op_terminal) = true;
                                  if (id(dump_operation_in_progress)) id(dump_write_failed) = true;
                          on_not_sent:
                            then:
                              - lambda: |-
                                  id(dump_op_terminal) = true;
                                  if (id(dump_operation_in_progress)) id(dump_write_failed) = true;

                      - wait_until:
                          condition:
                            lambda: 'return id(dump_op_terminal);'
                          timeout: 3000ms
                      - lambda: |-
                          if (!id(dump_op_terminal)) {
                            id(dump_write_failed) = true;
                            ESP_LOGE("dump_to_grid", "Restore verify reread of register 244 did not reach a terminal state");
                          }


            # B - the 256-261 plan (see the header comment of this section).
            - lambda: |-
                if (!id(dump_restore_pre_ok)) return;
                id(dump_restore_244_ok) = id(dump_restore_244_action) != 1 || !id(dump_write_failed);
                bool contain = !id(dump_restore_244_ok);
                uint16_t orig[6] = {
                  id(dump_snapshot_reg256), id(dump_snapshot_reg257), id(dump_snapshot_reg258),
                  id(dump_snapshot_reg259), id(dump_snapshot_reg260), id(dump_snapshot_reg261)
                };
                uint16_t v[6] = {0, 0, 0, 0, 0, 0};
                uint8_t m = 0;
                for (int i = 0; i < 6; i++) {
                  uint16_t floor_v = orig[i] < ${ecco_dump_controller_min_ceiling_w} ? orig[i] : (uint16_t) ${ecco_dump_controller_min_ceiling_w};
                  v[i] = contain ? floor_v : orig[i];
                  bool is_foreign = ((id(dump_restore_foreign_mask) >> i) & 1) != 0;     // a FOREIGN slot is never written
                  if (!is_foreign && (contain || ((id(dump_restore_owned_mask) >> i) & 1) != 0)) m = (uint8_t) (m | (1 << i));
                }
                // The full 6-register write when every slot is to be written (nothing FOREIGN, any
                // owned): ORIGINAL slots receive their own value again - the pre-fcp2 restore write.
                if (!contain && id(dump_restore_foreign_mask) == 0 && m != 0) m = 0x3F;
                id(dump_restore_v0) = v[0];
                id(dump_restore_v1) = v[1];
                id(dump_restore_v2) = v[2];
                id(dump_restore_v3) = v[3];
                id(dump_restore_v4) = v[4];
                id(dump_restore_v5) = v[5];
                id(dump_restore_wmask) = m;
                id(dump_restore_contain) = contain && m != 0;
                if (contain) ESP_LOGW("dump_to_grid", "244 NOT proven out of Allow Export - containing ECCO's TOU power registers at the floor (mask 0x%02X)", (unsigned) m);
            - if:
                condition:
                  lambda: 'return id(dump_restore_wmask) == 0x3F;'
                then:
                  - lambda: 'id(dump_op_terminal) = false;'
                  - modbus_client.write_multiple_registers:
                      modbus_id: inverter_modbus
                      address: 0x01
                      start_address: 256
                      values: !lambda |-
                        return std::vector<uint16_t>{
                          id(dump_restore_v0), id(dump_restore_v1), id(dump_restore_v2),
                          id(dump_restore_v3), id(dump_restore_v4), id(dump_restore_v5)
                        };
                      on_response:
                        then:
                          - lambda: 'id(dump_op_terminal) = true;'
                      on_error:
                        then:
                          - lambda: |-
                              id(dump_op_terminal) = true;
                              if (id(dump_operation_in_progress)) { id(dump_restore_block_failed) = true; id(dump_write_failed) = true; }
                      on_no_response:
                        then:
                          - lambda: |-
                              id(dump_op_terminal) = true;
                              if (id(dump_operation_in_progress)) { id(dump_restore_block_failed) = true; id(dump_write_failed) = true; }
                      on_not_sent:
                        then:
                          - lambda: |-
                              id(dump_op_terminal) = true;
                              if (id(dump_operation_in_progress)) { id(dump_restore_block_failed) = true; id(dump_write_failed) = true; }

                  - wait_until:
                      condition:
                        lambda: 'return id(dump_op_terminal);'
                      timeout: 3000ms
                  - lambda: |-
                      if (!id(dump_op_terminal)) {
                        id(dump_restore_block_failed) = true; id(dump_write_failed) = true;
                        ESP_LOGE("dump_to_grid", "Restore write to registers 256-261 did not reach a terminal state");
                      }
            - if:
                condition:
                  lambda: 'return id(dump_restore_wmask) != 0x3F && ((id(dump_restore_wmask) >> 0) & 1) != 0 && !id(dump_restore_block_failed);'
                then:
                  - lambda: 'id(dump_op_terminal) = false;'
                  - modbus_client.write_multiple_registers:
                      modbus_id: inverter_modbus
                      address: 0x01
                      start_address: 256
                      values: !lambda 'return std::vector<uint16_t>{id(dump_restore_v0)};'
                      on_response:
                        then:
                          - lambda: 'id(dump_op_terminal) = true;'
                      on_error:
                        then:
                          - lambda: |-
                              id(dump_op_terminal) = true;
                              if (id(dump_operation_in_progress)) { id(dump_restore_block_failed) = true; id(dump_write_failed) = true; }
                      on_no_response:
                        then:
                          - lambda: |-
                              id(dump_op_terminal) = true;
                              if (id(dump_operation_in_progress)) { id(dump_restore_block_failed) = true; id(dump_write_failed) = true; }
                      on_not_sent:
                        then:
                          - lambda: |-
                              id(dump_op_terminal) = true;
                              if (id(dump_operation_in_progress)) { id(dump_restore_block_failed) = true; id(dump_write_failed) = true; }

                  - wait_until:
                      condition:
                        lambda: 'return id(dump_op_terminal);'
                      timeout: 3000ms
                  - lambda: |-
                      if (!id(dump_op_terminal)) {
                        id(dump_restore_block_failed) = true; id(dump_write_failed) = true;
                        ESP_LOGE("dump_to_grid", "Restore write to register 256 did not reach a terminal state");
                      }
            - if:
                condition:
                  lambda: 'return id(dump_restore_wmask) != 0x3F && ((id(dump_restore_wmask) >> 1) & 1) != 0 && !id(dump_restore_block_failed);'
                then:
                  - lambda: 'id(dump_op_terminal) = false;'
                  - modbus_client.write_multiple_registers:
                      modbus_id: inverter_modbus
                      address: 0x01
                      start_address: 257
                      values: !lambda 'return std::vector<uint16_t>{id(dump_restore_v1)};'
                      on_response:
                        then:
                          - lambda: 'id(dump_op_terminal) = true;'
                      on_error:
                        then:
                          - lambda: |-
                              id(dump_op_terminal) = true;
                              if (id(dump_operation_in_progress)) { id(dump_restore_block_failed) = true; id(dump_write_failed) = true; }
                      on_no_response:
                        then:
                          - lambda: |-
                              id(dump_op_terminal) = true;
                              if (id(dump_operation_in_progress)) { id(dump_restore_block_failed) = true; id(dump_write_failed) = true; }
                      on_not_sent:
                        then:
                          - lambda: |-
                              id(dump_op_terminal) = true;
                              if (id(dump_operation_in_progress)) { id(dump_restore_block_failed) = true; id(dump_write_failed) = true; }

                  - wait_until:
                      condition:
                        lambda: 'return id(dump_op_terminal);'
                      timeout: 3000ms
                  - lambda: |-
                      if (!id(dump_op_terminal)) {
                        id(dump_restore_block_failed) = true; id(dump_write_failed) = true;
                        ESP_LOGE("dump_to_grid", "Restore write to register 257 did not reach a terminal state");
                      }
            - if:
                condition:
                  lambda: 'return id(dump_restore_wmask) != 0x3F && ((id(dump_restore_wmask) >> 2) & 1) != 0 && !id(dump_restore_block_failed);'
                then:
                  - lambda: 'id(dump_op_terminal) = false;'
                  - modbus_client.write_multiple_registers:
                      modbus_id: inverter_modbus
                      address: 0x01
                      start_address: 258
                      values: !lambda 'return std::vector<uint16_t>{id(dump_restore_v2)};'
                      on_response:
                        then:
                          - lambda: 'id(dump_op_terminal) = true;'
                      on_error:
                        then:
                          - lambda: |-
                              id(dump_op_terminal) = true;
                              if (id(dump_operation_in_progress)) { id(dump_restore_block_failed) = true; id(dump_write_failed) = true; }
                      on_no_response:
                        then:
                          - lambda: |-
                              id(dump_op_terminal) = true;
                              if (id(dump_operation_in_progress)) { id(dump_restore_block_failed) = true; id(dump_write_failed) = true; }
                      on_not_sent:
                        then:
                          - lambda: |-
                              id(dump_op_terminal) = true;
                              if (id(dump_operation_in_progress)) { id(dump_restore_block_failed) = true; id(dump_write_failed) = true; }

                  - wait_until:
                      condition:
                        lambda: 'return id(dump_op_terminal);'
                      timeout: 3000ms
                  - lambda: |-
                      if (!id(dump_op_terminal)) {
                        id(dump_restore_block_failed) = true; id(dump_write_failed) = true;
                        ESP_LOGE("dump_to_grid", "Restore write to register 258 did not reach a terminal state");
                      }
            - if:
                condition:
                  lambda: 'return id(dump_restore_wmask) != 0x3F && ((id(dump_restore_wmask) >> 3) & 1) != 0 && !id(dump_restore_block_failed);'
                then:
                  - lambda: 'id(dump_op_terminal) = false;'
                  - modbus_client.write_multiple_registers:
                      modbus_id: inverter_modbus
                      address: 0x01
                      start_address: 259
                      values: !lambda 'return std::vector<uint16_t>{id(dump_restore_v3)};'
                      on_response:
                        then:
                          - lambda: 'id(dump_op_terminal) = true;'
                      on_error:
                        then:
                          - lambda: |-
                              id(dump_op_terminal) = true;
                              if (id(dump_operation_in_progress)) { id(dump_restore_block_failed) = true; id(dump_write_failed) = true; }
                      on_no_response:
                        then:
                          - lambda: |-
                              id(dump_op_terminal) = true;
                              if (id(dump_operation_in_progress)) { id(dump_restore_block_failed) = true; id(dump_write_failed) = true; }
                      on_not_sent:
                        then:
                          - lambda: |-
                              id(dump_op_terminal) = true;
                              if (id(dump_operation_in_progress)) { id(dump_restore_block_failed) = true; id(dump_write_failed) = true; }

                  - wait_until:
                      condition:
                        lambda: 'return id(dump_op_terminal);'
                      timeout: 3000ms
                  - lambda: |-
                      if (!id(dump_op_terminal)) {
                        id(dump_restore_block_failed) = true; id(dump_write_failed) = true;
                        ESP_LOGE("dump_to_grid", "Restore write to register 259 did not reach a terminal state");
                      }
            - if:
                condition:
                  lambda: 'return id(dump_restore_wmask) != 0x3F && ((id(dump_restore_wmask) >> 4) & 1) != 0 && !id(dump_restore_block_failed);'
                then:
                  - lambda: 'id(dump_op_terminal) = false;'
                  - modbus_client.write_multiple_registers:
                      modbus_id: inverter_modbus
                      address: 0x01
                      start_address: 260
                      values: !lambda 'return std::vector<uint16_t>{id(dump_restore_v4)};'
                      on_response:
                        then:
                          - lambda: 'id(dump_op_terminal) = true;'
                      on_error:
                        then:
                          - lambda: |-
                              id(dump_op_terminal) = true;
                              if (id(dump_operation_in_progress)) { id(dump_restore_block_failed) = true; id(dump_write_failed) = true; }
                      on_no_response:
                        then:
                          - lambda: |-
                              id(dump_op_terminal) = true;
                              if (id(dump_operation_in_progress)) { id(dump_restore_block_failed) = true; id(dump_write_failed) = true; }
                      on_not_sent:
                        then:
                          - lambda: |-
                              id(dump_op_terminal) = true;
                              if (id(dump_operation_in_progress)) { id(dump_restore_block_failed) = true; id(dump_write_failed) = true; }

                  - wait_until:
                      condition:
                        lambda: 'return id(dump_op_terminal);'
                      timeout: 3000ms
                  - lambda: |-
                      if (!id(dump_op_terminal)) {
                        id(dump_restore_block_failed) = true; id(dump_write_failed) = true;
                        ESP_LOGE("dump_to_grid", "Restore write to register 260 did not reach a terminal state");
                      }
            - if:
                condition:
                  lambda: 'return id(dump_restore_wmask) != 0x3F && ((id(dump_restore_wmask) >> 5) & 1) != 0 && !id(dump_restore_block_failed);'
                then:
                  - lambda: 'id(dump_op_terminal) = false;'
                  - modbus_client.write_multiple_registers:
                      modbus_id: inverter_modbus
                      address: 0x01
                      start_address: 261
                      values: !lambda 'return std::vector<uint16_t>{id(dump_restore_v5)};'
                      on_response:
                        then:
                          - lambda: 'id(dump_op_terminal) = true;'
                      on_error:
                        then:
                          - lambda: |-
                              id(dump_op_terminal) = true;
                              if (id(dump_operation_in_progress)) { id(dump_restore_block_failed) = true; id(dump_write_failed) = true; }
                      on_no_response:
                        then:
                          - lambda: |-
                              id(dump_op_terminal) = true;
                              if (id(dump_operation_in_progress)) { id(dump_restore_block_failed) = true; id(dump_write_failed) = true; }
                      on_not_sent:
                        then:
                          - lambda: |-
                              id(dump_op_terminal) = true;
                              if (id(dump_operation_in_progress)) { id(dump_restore_block_failed) = true; id(dump_write_failed) = true; }

                  - wait_until:
                      condition:
                        lambda: 'return id(dump_op_terminal);'
                      timeout: 3000ms
                  - lambda: |-
                      if (!id(dump_op_terminal)) {
                        id(dump_restore_block_failed) = true; id(dump_write_failed) = true;
                        ESP_LOGE("dump_to_grid", "Restore write to register 261 did not reach a terminal state");
                      }
            # V - readback of every slot written this attempt.
            - if:
                condition:
                  lambda: 'return id(dump_restore_wmask) != 0 && !id(dump_restore_block_failed);'
                then:
                  - lambda: 'id(dump_op_terminal) = false;'
                  - modbus_client.read_holding_registers:
                      modbus_id: inverter_modbus
                      address: 0x01
                      start_address: 256
                      count: 6
                      on_response:
                        then:
                          - lambda: |-
                              id(dump_op_terminal) = true;
                              if (!id(dump_operation_in_progress)) return;
                              uint16_t v[6] = {
                                id(dump_restore_v0), id(dump_restore_v1), id(dump_restore_v2),
                                id(dump_restore_v3), id(dump_restore_v4), id(dump_restore_v5)
                              };
                              for (int i = 0; i < 6; i++) {
                                if (((id(dump_restore_wmask) >> i) & 1) && values[i] != v[i]) {
                                  id(dump_restore_block_failed) = true;
                                  id(dump_write_failed) = true;
                                  id(dump_restore_mismatch_this_attempt) = true;
                                  ESP_LOGE("dump_to_grid", "RESTORE VERIFY FAILED on register %d (raw=%u expected=%u)", 256 + i, values[i], v[i]);
                                }
                              }
                      on_error:
                        then:
                          - lambda: |-
                              id(dump_op_terminal) = true;
                              if (id(dump_operation_in_progress)) { id(dump_restore_block_failed) = true; id(dump_write_failed) = true; }
                      on_no_response:
                        then:
                          - lambda: |-
                              id(dump_op_terminal) = true;
                              if (id(dump_operation_in_progress)) { id(dump_restore_block_failed) = true; id(dump_write_failed) = true; }
                      on_not_sent:
                        then:
                          - lambda: |-
                              id(dump_op_terminal) = true;
                              if (id(dump_operation_in_progress)) { id(dump_restore_block_failed) = true; id(dump_write_failed) = true; }

                  - wait_until:
                      condition:
                        lambda: 'return id(dump_op_terminal);'
                      timeout: 3000ms
                  - lambda: |-
                      if (!id(dump_op_terminal)) {
                        id(dump_restore_block_failed) = true; id(dump_write_failed) = true;
                        ESP_LOGE("dump_to_grid", "Restore verify reread of 256-261 did not reach a terminal state");
                      }

            # R - the outcome. Success only when everything ECCO attempted was written AND
            # verified and nothing is FOREIGN; the FOREIGN lockout only in that same case.
            - lambda: |-
                if (id(dump_restore_contain) && !id(dump_restore_block_failed)) id(dump_restore_contained) = true;
                if (id(dump_restore_pre_ok) && !id(dump_write_failed) &&
                    (id(dump_restore_foreign_mask) != 0 || id(dump_restore_244_action) == 2)) {
                  id(dump_restore_foreign_this_attempt) = true;
                  id(dump_write_failed) = true;
                }
            - if:
                condition:
                  lambda: 'return !id(dump_write_failed);'
                then:
                  - lambda: |-
                      ecco_durable::ValidMarker pending{};
                      pending.magic = ecco_durable::VALID_MARKER_MAGIC;
                      pending.state = ecco_durable::MARKER_RESTORE_VERIFIED_PENDING_CLEAR;
                      bool pending_ok = ecco_durable::commit_record(
                        ecco_durable::key_for(ecco_durable::DUMP_TO_GRID_VALID_TAG), pending);
                      if (pending_ok) id(dump_marker_state) = ecco_durable::MARKER_RESTORE_VERIFIED_PENDING_CLEAR;

                      ecco_durable::ValidMarker clear{};
                      clear.magic = ecco_durable::VALID_MARKER_MAGIC;
                      clear.state = ecco_durable::MARKER_CLEAR;
                      bool clear_ok = pending_ok && ecco_durable::commit_record(
                        ecco_durable::key_for(ecco_durable::DUMP_TO_GRID_VALID_TAG), clear);

                      if (clear_ok) {
                        id(dump_marker_state) = ecco_durable::MARKER_CLEAR;
                        id(dump_snapshot_valid) = false;
                        id(dump_active_persisted) = false;
                        id(dump_restore_requested) = false;
                        id(dump_operator_retry_pending) = false;
                        id(dump_comms_restore_attempts) = 0;
                        id(dump_restore_next_attempt_ms) = 0;
                        id(dump_restore_failed_ms) = 0;        // fcp2 (F4): no stale link-down stamp survives a success
                        id(dump_export_unverified) = false;
                        id(dump_verify_mismatch_count) = 0;
                        id(dump_restore_successes)++;
                        id(dump_controller_state) = "IDLE";
                        id(dump_controller_state_sensor).publish_state("IDLE");
                        // A verified clear resolves any prior lockout too -
                        // durably, not just in RAM, matching the durable set
                        // in the failure branch below.
                        if (id(dump_operator_needed)) {
                          ecco_durable::DumpToGridRetryState retry{};
                          retry.operator_needed = 0;
                          ecco_durable::commit_record(ecco_durable::key_for(ecco_durable::DUMP_TO_GRID_RETRY_TAG), retry);
                          id(dump_operator_needed) = false;
                        }
                        id(dump_status).publish_state("RESTORED OK - original inverter settings verified");
                        ESP_LOGW("dump_to_grid", "Dump to Grid RESTORED OK");
                      } else {
                        // Hardware IS confirmed restored (pending_ok's write
                        // happened before this branch, or the verify above
                        // already passed) but the durable CLEAR itself could
                        // not be committed. Leave the marker as whatever it
                        // durably reached - never invent CLEAR in RAM only.
                        id(dump_status).publish_state(
                          "RESTORE VERIFIED - durable clear pending; will retry automatically"
                        );
                        ESP_LOGE("dump_to_grid", "Hardware restored but durable clear commit failed - will retry");
                      }
                      id(dump_operation_in_progress) = false;
                      id(manual_write_in_progress) = false;
                else:
                  # 2026-09-26 independent review: cause-aware, mirroring
                  # restore_free_power_snapshot_dispatch. Only a VERIFY
                  # MISMATCH counts towards the durable operator lockout; a
                  # COMMS failure keeps retrying automatically under the
                  # bounded backoff (15s..300s), because the restore is the
                  # safe direction and a lockout here stops both the timed
                  # end and Stop SOC enforcement while export may still be
                  # enabled.
                  - lambda: |-
                      id(dump_failures)++;
                      id(dump_operation_in_progress) = false;
                      id(manual_write_in_progress) = false;
                      // fcp2 (SG-04): name a containment, so no status ever implies export is off when 244 is not proven.
                      std::string contained = "";
                      if (id(dump_export_unverified) && id(dump_restore_contained)) {
                        contained = "; register 244 is NOT proven out of Allow Export - every ECCO-controlled TOU power register is held at the 500 W floor";
                      } else if (id(dump_export_unverified)) {
                        contained = "; register 244 is NOT proven out of Allow Export - export may continue";
                      }
                      if (id(dump_restore_foreign_this_attempt)) {
                        // fcp2 (SG-08 / B1): reached ONLY when everything ECCO attempted this time
                        // (244 first, then its own 256-261 slots) was written AND verified and an
                        // external value remains. The obligation stays (marker unchanged) and
                        // automatic retries stop: the operator decides. Never after a failed step -
                        // those take the mismatch / comms paths below, with their retries.
                        ecco_durable::DumpToGridRetryState retry{};
                        retry.operator_needed = 1;
                        if (!ecco_durable::commit_record(ecco_durable::key_for(ecco_durable::DUMP_TO_GRID_RETRY_TAG), retry)) {
                          ESP_LOGW("dump_to_grid", "Could not durably record operator-needed lockout - enforced for this runtime only");
                        }
                        id(dump_operator_needed) = true;
                        id(dump_recovery_last_classification) = 0;
                        id(dump_recovery_state).publish_state(
                          std::string("FOREIGN (not overwritten) - ") + id(dump_restore_foreign_detail)
                        );
                        id(dump_status).publish_state(
                          std::string("OPERATOR DECISION REQUIRED - ECCO's own settings were restored and verified, but an external change was found and NOT overwritten (") +
                          id(dump_restore_foreign_detail) +
                          "); use Force Restore Original or Accept Current State"
                        );
                        ESP_LOGE("dump_to_grid", "Restore found a FOREIGN value - not overwritten, operator needed: %s", id(dump_restore_foreign_detail).c_str());
                      } else if (id(dump_restore_mismatch_this_attempt)) {
                        id(dump_verify_mismatch_count)++;
                        if (id(dump_verify_mismatch_count) >= 2) {
                          ecco_durable::DumpToGridRetryState retry{};
                          retry.operator_needed = 1;
                          if (!ecco_durable::commit_record(ecco_durable::key_for(ecco_durable::DUMP_TO_GRID_RETRY_TAG), retry)) {
                            // Same documented pacing-only fail-open as Free
                            // Power: enforced in RAM for this runtime even if
                            // the durable record could not be written.
                            ESP_LOGW("dump_to_grid", "Could not durably record operator-needed lockout - enforced for this runtime only");
                          }
                          id(dump_operator_needed) = true;
                          id(dump_recovery_last_classification) = 0;
                          id(dump_recovery_state).publish_state(
                            "NEITHER (fail-closed default) - repeated restore verify mismatch"
                          );
                          id(dump_status).publish_state(
                            std::string("OPERATOR DECISION REQUIRED - repeated verify mismatch restoring Dump to Grid; use Force Restore Original or Accept Current State") + contained
                          );
                          ESP_LOGE("dump_to_grid", "Second consecutive restore verify mismatch - automatic retries stopped, operator needed");
                        } else {
                          id(dump_status).publish_state(
                            std::string("RESTORE VERIFY FAILED - snapshot retained; watchdog will retry once automatically") + contained
                          );
                          ESP_LOGE("dump_to_grid", "Restore verify mismatch - watchdog will retry once");
                        }
                      } else {
                        id(dump_comms_restore_attempts)++;
                        id(dump_restore_next_attempt_ms) = millis() + ecco_durable::comms_backoff_ms(id(dump_comms_restore_attempts));
                        // fcp2 (SG-39): remember a failure made while the LINK was down (no telemetry
                        // read for ecco_dump_link_down_ms) - see the restore gate. 0 = an ordinary failure.
                        id(dump_restore_failed_ms) =
                          (id(dump_soc_last_update_ms) == 0 ||
                           (uint32_t) (millis() - id(dump_soc_last_update_ms)) > ${ecco_dump_link_down_ms}UL) ? millis() : 0;
                        id(dump_status).publish_state(
                          std::string("RESTORE WRITE FAILED - inverter did not respond or refused; snapshot retained; will retry automatically with backoff") + contained
                        );
                        ESP_LOGW("dump_to_grid", "Restore attempt failed (comms) - watchdog will retry with backoff");
                      }
""")

# ---- frozen_subst
FROZEN_SUBST_OLD = _blk(r"""
  ecco_dump_soc_stale_ms: "90000"
""")
FROZEN_SUBST_NEW = _blk(r"""
  ecco_dump_soc_stale_ms: "90000"
  # fcp2 (SG-15 / SG-43): FROZEN telemetry. A reading that keeps arriving on
  # time but never changes is not evidence; the grid CT (register 172), the
  # battery power (190) and the SOC (184) come from the same telemetry read,
  # so a missing read is already caught (Stop SOC's freshness check ends the
  # lease, and the controller never decides on a stale grid sample). During a
  # settled lease, the lease ends when:
  #  - battery power repeats EXACTLY for ecco_dump_frozen_samples valid samples
  #    (recorded leases: never more than 2 identical in a row);
  #  - the grid CT repeats exactly for ecco_dump_frozen_samples samples while
  #    the battery power moved by more than ecco_dump_frozen_cross_w (the plant
  #    changed, the meter did not), or for ecco_dump_frozen_ct_long_samples
  #    samples whatever the battery did (a CT stuck at a saturated ceiling);
  #  - the battery discharged more than ecco_dump_soc_frozen_wh (DC energy,
  #    integrated from register 190) without any SOC change (SOC moves in 1 %
  #    steps; this is about 5 % of the reference installation's ~30 kWh
  #    battery - SITE-DEPENDENT: a smaller battery needs a smaller value).
  ecco_dump_frozen_samples: "6"
  ecco_dump_frozen_cross_w: "150"
  ecco_dump_frozen_ct_long_samples: "30"
  ecco_dump_soc_frozen_wh: "1500"
  # fcp2 rework (F3): battery power within this many W of zero is IDLE, never
  # judged frozen (a battery that cannot discharge further reads exactly 0).
  ecco_dump_frozen_idle_w: "50"
  # fcp2 (SG-39): a restore attempt that failed while NO telemetry read had
  # succeeded for this long (two missed 10 s polls: the link itself was down)
  # is retried as soon as the link is proven to work again - see the restore
  # gate - instead of sitting out the rest of a backoff of up to 300 s. A
  # failure while telemetry was flowing (the inverter refused the write) keeps
  # the ordinary backoff.
  ecco_dump_link_down_ms: "25000"
""")

# ---- frozen_bp_track
FROZEN_BP_TRACK_OLD = _blk(r"""
        - lambda: |-
            if (!id(dump_active_persisted) || id(dump_restore_requested) || id(dump_operation_in_progress)) {
              id(dump_overpower_samples) = 0;
""")
FROZEN_BP_TRACK_NEW = _blk(r"""
        - lambda: |-
            // fcp2 (SG-43): FROZEN battery power and the frozen-SOC energy count (see
            // ecco_dump_frozen_samples / ecco_dump_soc_frozen_wh). Every valid sample:
            // exact repeats are counted, and the DC energy discharged since the last SOC
            // change is integrated (each gap capped at 60 s). Both are reset at START.
            if (!std::isnan(x)) {
              uint32_t bp_now = millis();
              if (id(dump_bp_last_ms) != 0 && x > 0.0f) {
                uint32_t bp_dt = bp_now - id(dump_bp_last_ms);
                if (bp_dt > 60000UL) bp_dt = 60000UL;
                id(dump_soc_frozen_wh_acc) += x * (float) bp_dt / 3600000.0f;
              }
              // fcp2 rework (F3): a battery legitimately idle (|x| below ecco_dump_frozen_idle_w, e.g.
              // it cannot discharge further) is not "frozen".
              if (x == id(dump_bp_last_w) && std::fabs(x) >= ${ecco_dump_frozen_idle_w}.0f) id(dump_bp_same_count)++;
              else id(dump_bp_same_count) = 0;
              id(dump_bp_last_w) = x;
              id(dump_bp_last_ms) = bp_now;
            }
            if (!id(dump_active_persisted) || id(dump_restore_requested) || id(dump_operation_in_progress)) {
              id(dump_overpower_samples) = 0;
""")

# ---- frozen_soc_reset
FROZEN_SOC_RESET_OLD = _blk(r"""
        - lambda: 'id(dump_soc_last_update_ms) = millis();'
""")
FROZEN_SOC_RESET_NEW = _blk(r"""
        - lambda: |-
            id(dump_soc_last_update_ms) = millis();
            // fcp2 (SG-43; rework F3): only a SOC DROP below the lowest value since the last restart of
            // the count restarts it - a SOC toggling between two values cannot defeat the detector.
            if (!std::isnan(x) && (x < id(dump_soc_last_value) || id(dump_soc_last_value) < 0.0f)) {
              id(dump_soc_last_value) = x;
              id(dump_soc_frozen_wh_acc) = 0.0f;
            }
""")

# ---- backoff_gate
BACKOFF_GATE_OLD = _blk(r"""
                (id(dump_force_restore_this_call) ||
                 id(dump_restore_next_attempt_ms) == 0 ||
                 (int32_t) (millis() - id(dump_restore_next_attempt_ms)) >= 0) &&
""")
BACKOFF_GATE_NEW = _blk(r"""
                (id(dump_force_restore_this_call) ||
                 id(dump_restore_next_attempt_ms) == 0 ||
                 (int32_t) (millis() - id(dump_restore_next_attempt_ms)) >= 0 ||
                 // fcp2 (SG-39): a GENUINE recovery - the last attempt failed while the link
                 // was down (dump_restore_failed_ms, see ecco_dump_link_down_ms) and a
                 // telemetry read has succeeded since (it stamps dump_soc_last_update_ms) -
                 // shortens whatever backoff remains to its first step: the restore is
                 // retried as soon as the link is proven to work again, not up to 300 s later.
                 (id(dump_restore_failed_ms) != 0 &&
                  (int32_t) (id(dump_soc_last_update_ms) - id(dump_restore_failed_ms)) > 0 &&
                  (int32_t) (millis() - (id(dump_restore_failed_ms) + ecco_durable::comms_backoff_ms(1))) >= 0)) &&
""")

# ---- build_tag_subst
BUILD_TAG_SUBST_OLD = _blk(r"""
  ecco_inverter_profile_name: "8 kW single-phase low-voltage Deye-family hybrid (reference installation H-001)"
""")
BUILD_TAG_SUBST_NEW = _blk(r"""
  ecco_inverter_profile_name: "8 kW single-phase low-voltage Deye-family hybrid (reference installation H-001)"
  # fcp2 (SG-07): what this build IS, published by "ECCO Build Identity" with the
  # profile, the ESPHome version and the configuration hash. A release build
  # sets it to the source it was built from (`esphome -s ecco_build_tag
  # <tree or commit> compile ...`) and records it in the build record.
  ecco_build_tag: "unrecorded-build"
""")

# ---- safe_mode_block
SAFE_MODE_BLOCK_OLD = _blk(r"""
ota:
  - platform: esphome
    password: !secret ecco_ota_password
""")
SAFE_MODE_BLOCK_NEW = _blk(r"""
ota:
  - platform: esphome
    password: !secret ecco_ota_password

# fcp2 (SG-16): ESPHome's safe mode, stated explicitly (these are its defaults -
# no behaviour change). After 10 boots in a row that do not stay up for one
# minute, the device boots into safe mode: Wi-Fi, API and OTA only, and NONE of
# this firmware's components - no lease supervision and no restore runs there.
# The inverter then keeps whatever it holds; every ECCO lease or restore
# obligation is durable and is re-opened, with the ownership-checked restore, on
# the first normal boot after a fix or a re-flash. "ECCO Safe To Flash" says
# whether flashing now would interrupt anything.
safe_mode:
  num_attempts: 10
  reboot_timeout: 5min
  boot_is_good_after: 1min
""")

# ---- restart_arm_switch
RESTART_ARM_SWITCH_OLD = _blk(r"""
    turn_on_action:
      - lambda: 'id(dump_limits_arm_ms) = millis();'
""")
RESTART_ARM_SWITCH_NEW = _blk(r"""
    turn_on_action:
      - lambda: 'id(dump_limits_arm_ms) = millis();'

  # fcp2 (SG-36): the deliberate override for the gated "Restart" button - one
  # press within 60 s, and only while nothing is IN PROGRESS (an owed lease or
  # restore may be overridden: the boot path re-opens it from the durable
  # markers; a transaction in flight may not). Writes nothing to the inverter.
  - platform: template
    name: "Restart Override Arm"
    id: ecco_restart_arm
    optimistic: true
    restore_mode: ALWAYS_OFF
    icon: "mdi:restart-alert"
    turn_on_action:
      - lambda: 'id(ecco_restart_arm_ms) = millis();'
""")

# ---- identity_text_sensors
IDENTITY_TEXT_SENSORS_OLD = _blk(r"""
    name: "Dump Power Limits Status"
    id: dump_limits_status
    update_interval: never
    icon: "mdi:shield-check-outline"
""")
IDENTITY_TEXT_SENSORS_NEW = _blk(r"""
    name: "Dump Power Limits Status"
    id: dump_limits_status
    update_interval: never
    icon: "mdi:shield-check-outline"

  # fcp2 (SG-07): what this build is - the build tag, the capability profile, the
  # ESPHome version and the configuration hash (the value Home Assistant shows as
  # the device's config hash), so the device itself says which image it runs.
  - platform: template
    name: "ECCO Build Identity"
    id: ecco_build_identity
    entity_category: diagnostic
    update_interval: 60s
    icon: "mdi:identifier"
    lambda: |-
      char b[200];
      snprintf(b, sizeof(b), "%s; profile %s; ESPHome %s; config 0x%08x", "${ecco_build_tag}", "${ecco_inverter_profile_id}",
               ESPHOME_VERSION, (unsigned) App.get_config_hash());
      return std::string(b);

  # fcp2 (SG-07 / SG-36): the in-firmware half of the pre-flash checklist - see
  # ecco_safety_census. SAFE only when no lease, restore, recovery decision or
  # transaction exists in any domain and every durable marker is CLEAR.
  - platform: template
    name: "ECCO Flash Readiness"
    id: ecco_flash_readiness
    entity_category: diagnostic
    update_interval: 10s
    icon: "mdi:shield-sync-outline"
    lambda: |-
      if (id(ecco_unsafe_reason).empty()) {
        return std::string("SAFE - no lease, restore, recovery decision or transaction; every durable marker CLEAR");
      }
      return std::string("NOT SAFE - ") + id(ecco_unsafe_reason);

  # fcp2 (SG-36): the last gated Restart decision (refused / restarting, and why).
  - platform: template
    name: "Restart Status"
    id: ecco_restart_status
    update_interval: never
    icon: "mdi:restart-alert"
""")

# ---- safe_to_flash_binary
SAFE_TO_FLASH_BINARY_OLD = _blk(r"""
binary_sensor:
  - platform: template
    name: "NTP Synced"
""")
SAFE_TO_FLASH_BINARY_NEW = _blk(r"""
binary_sensor:
  # fcp2 (SG-07): true only when ecco_safety_census finds nothing owed or in
  # progress (see "ECCO Flash Readiness" for the reason when false).
  - platform: template
    name: "ECCO Safe To Flash"
    id: ecco_safe_to_flash
    entity_category: diagnostic
    icon: "mdi:shield-check"
    lambda: 'return id(ecco_unsafe_reason).empty();'

  - platform: template
    name: "NTP Synced"
""")

# ---- restart_button
RESTART_BUTTON_OLD = _blk(r"""
button:
  - platform: restart
    name: "Restart"
""")
RESTART_BUTTON_NEW = _blk(r"""
button:
  - platform: restart
    # fcp2 (SG-36): the raw reboot primitive is INTERNAL - nothing outside this
    # firmware can press it; the "Restart" button below is the gated restart.
    id: ecco_restart_internal
    internal: true
    name: "Restart (internal)"

  # fcp2 (SG-36): GATED restart. A routine restart is REFUSED while any
  # transaction is in progress or any lease, restore or recovery decision is
  # owed, in any domain (Dump to Grid, Free Power, register 244, an inverter
  # write, an RTC correction, a fallback profile operation) - see
  # ecco_safety_census and "Restart Status". An owed obligation (never a
  # transaction in flight) may be overridden with "Restart Override Arm": the
  # boot path re-opens it from the durable markers and runs the ownership-
  # checked restore. Over-the-air updates are not gated by firmware: "ECCO Safe
  # To Flash" is the indication the pre-flash checklist requires.
  - platform: template
    name: "Restart"
    id: ecco_restart_button
    icon: "mdi:restart"
    on_press:
      - script.execute: ecco_restart_request
""")

# ---- census_scripts
CENSUS_SCRIPTS_OLD = _blk(r"""
  - id: dump_clear_verified_marker
    mode: single
""")
CENSUS_SCRIPTS_NEW = _blk(r"""
  # fcp2 (SG-07 / SG-36): the SAFETY CENSUS - what a restart or a flash would
  # interrupt right now. RAM reads only (no Modbus, no durable access); sets
  # ecco_unsafe_reason ("" = nothing) and ecco_unsafe_busy (a transaction is in
  # flight - never overridable). Run every 5 s and immediately before a restart.
  - id: ecco_safety_census
    mode: queued
    then:
      - lambda: |-
          std::string r = "";
          bool busy = true;
          if (id(ecco_lock_stuck)) {
            // A leaked lock is not a transaction in flight: overridable (a restart is the recovery).
            r = "an inverter transaction lock is STUCK (held beyond any transaction's bound); a restart is the recovery";
            busy = false;
          } else if (id(dump_operation_in_progress)) {
            r = "a Dump to Grid transaction is in progress";
          } else if (id(free_power_operation_in_progress) || id(free_power_recovery_force_in_progress) ||
                     id(free_power_recovery_accept_in_progress)) {
            r = "a Free Power transaction is in progress";
          } else if (id(reg244_apply_in_progress)) {
            r = "a register 244 change is in progress";
          } else if (id(manual_write_in_progress)) {
            r = "an inverter write is in progress";
          } else if (id(correction_in_progress)) {
            r = "an RTC correction is in progress";
          } else if (id(fallback_profile_op_in_progress)) {
            r = "a fallback profile operation is in progress";
          } else {
            busy = false;
            if (id(dump_snapshot_valid) || id(dump_marker_state) != ecco_durable::MARKER_CLEAR) {
              r = (id(dump_active_persisted) && !id(dump_restore_requested)) ? "a Dump to Grid lease is active" : "a Dump to Grid restore is owed";
            } else if (id(dump_operator_needed) || id(dump_recovery_metadata_corrupt)) {
              r = "a Dump to Grid recovery decision is outstanding";
            } else if (id(free_power_snapshot_valid) || id(free_power_marker_state) != ecco_durable::MARKER_CLEAR) {
              r = "a Free Power lease or restore is owed";
            } else if (id(free_power_operator_needed) || id(free_power_recovery_metadata_corrupt)) {
              r = "a Free Power recovery decision is outstanding";
            } else if (id(reg244_snapshot_valid) || id(reg244_marker_state) != ecco_durable::MARKER_CLEAR) {
              r = "a register 244 restore is owed";
            }
          }
          id(ecco_unsafe_reason) = r;
          id(ecco_unsafe_busy) = busy;

  # fcp2 (SG-36): the gated "Restart" button's decision - see that button.
  - id: ecco_restart_request
    mode: single
    then:
      - script.execute: ecco_safety_census
      - if:
          condition:
            lambda: |-
              bool armed = id(ecco_restart_arm).state &&
                  (uint32_t) (millis() - id(ecco_restart_arm_ms)) <= 60000UL;
              if (id(ecco_restart_arm).state) id(ecco_restart_arm).turn_off();
              if (id(ecco_unsafe_reason).empty()) {
                id(ecco_restart_status).publish_state("RESTARTING - nothing owed or in progress");
                return true;
              }
              if (armed && !id(ecco_unsafe_busy)) {
                id(ecco_restart_status).publish_state(std::string("RESTARTING (override) - ") + id(ecco_unsafe_reason) +
                    "; the boot path re-opens it from the durable markers");
                return true;
              }
              if (id(ecco_unsafe_busy)) {
                id(ecco_restart_status).publish_state(std::string("REFUSED - ") + id(ecco_unsafe_reason) +
                    " (never overridable); try again when it has finished");
              } else {
                id(ecco_restart_status).publish_state(std::string("REFUSED - ") + id(ecco_unsafe_reason) +
                    "; wait for it to finish, or turn on Restart Override Arm and press Restart within 60 s");
              }
              ESP_LOGW("ecco_restart", "Restart refused: %s", id(ecco_unsafe_reason).c_str());
              return false;
          then:
            - button.press: ecco_restart_internal

  # fcp2 (SG-14 / SG-42): the escalation of a STUCK lock - see
  # ecco_write_lock_stuck_ms. The lock itself is never released here. An active
  # Dump lease is ended DURABLY first (request_dump_end commits restore_requested
  # without the bus; its restore stays deferred behind the stuck lock); then, while
  # any lease or restore is owed in any domain, the device restarts through the
  # internal primitive so the boot path completes it. With nothing owed: report only.
  - id: ecco_lock_escalation
    mode: single
    then:
      - lambda: |-
          ESP_LOGE("ecco_lock", "An inverter transaction lock has been held beyond %u s - STUCK; escalating (never released by time)",
                   (unsigned) (${ecco_write_lock_stuck_ms}UL / 1000UL));
      - if:
          condition:
            lambda: |-
              return id(dump_snapshot_valid) && id(dump_marker_state) == ecco_durable::MARKER_RESTORE_REQUIRED &&
                     !id(dump_recovery_metadata_corrupt) && !id(dump_restore_requested);
          then:
            - script.execute:
                id: request_dump_end
                reason: "WRITE LOCK STUCK - an inverter transaction lock was held beyond any transaction's bound; lease ended durably, restarting so the boot path completes the restore"
      - if:
          condition:
            lambda: |-
              return id(dump_snapshot_valid) || id(dump_marker_state) != ecco_durable::MARKER_CLEAR ||
                     id(free_power_snapshot_valid) || id(free_power_marker_state) != ecco_durable::MARKER_CLEAR ||
                     id(reg244_snapshot_valid) || id(reg244_marker_state) != ecco_durable::MARKER_CLEAR;
          then:
            - lambda: |-
                id(ecco_restart_status).publish_state("RESTARTING (stuck lock) - an inverter transaction lock was held beyond any transaction's bound while a lease or restore is owed; the lock is NOT released - the boot path completes the owed restore");
            - button.press: ecco_restart_internal
          else:
            - lambda: |-
                id(ecco_restart_status).publish_state("STUCK LOCK - an inverter transaction lock was held beyond any transaction's bound; nothing is owed, so no automatic restart - inverter writes stay blocked until Restart (Restart Override Arm)");

  - id: dump_clear_verified_marker
    mode: single
""")

# ---- census_interval
CENSUS_INTERVAL_OLD = _blk(r"""
          if (id(dump_limits_arm).state &&
              (uint32_t) (millis() - id(dump_limits_arm_ms)) > ${ecco_dump_limits_arm_window_ms}UL) {
            id(dump_limits_arm).turn_off();
          }
""")
CENSUS_INTERVAL_NEW = _blk(r"""
          if (id(dump_limits_arm).state &&
              (uint32_t) (millis() - id(dump_limits_arm_ms)) > ${ecco_dump_limits_arm_window_ms}UL) {
            id(dump_limits_arm).turn_off();
          }
          // fcp2 (SG-36): the restart override arm also expires after 60 s.
          if (id(ecco_restart_arm).state && (uint32_t) (millis() - id(ecco_restart_arm_ms)) > 60000UL) {
            id(ecco_restart_arm).turn_off();
          }
      # fcp2 (SG-07): refresh the safety census behind ECCO Safe To Flash.
      - script.execute: ecco_safety_census
      # fcp2 (SG-14 / SG-42): LOCK AGE - see ecco_write_lock_stuck_ms. Measures how long
      # an inverter transaction lock has been held continuously; NEVER releases it.
      - lambda: |-
          bool held = id(manual_write_in_progress) || id(dump_operation_in_progress) ||
                      id(free_power_operation_in_progress) || id(reg244_apply_in_progress);
          if (!held) {
            id(ecco_lock_since_ms) = 0;
            id(ecco_lock_stuck) = false;
            id(ecco_lock_escalated) = false;
          } else {
            if (id(ecco_lock_since_ms) == 0) id(ecco_lock_since_ms) = millis();
            if ((uint32_t) (millis() - id(ecco_lock_since_ms)) > ${ecco_write_lock_stuck_ms}UL) id(ecco_lock_stuck) = true;
          }
      - if:
          condition:
            # fcp2 rework: escalate (and possibly restart) only on a QUIET bus - no frame queued or awaiting
            # a reply - so the restart can never cut a Modbus exchange in half; re-checked every 5 s.
            lambda: |-
              return id(ecco_lock_stuck) && !id(ecco_lock_escalated) &&
                     id(inverter_modbus)->tx_buffer_empty() && !id(inverter_modbus)->tx_blocked();
          then:
            - lambda: 'id(ecco_lock_escalated) = true;'
            - script.execute: ecco_safety_census
            - script.execute: ecco_lock_escalation
  # fcp2 rework (R2): act on a LATCHED net grid export trip within one second (see ecco_grid_ct_power's
  # on_value) instead of waiting for the 15 s watchdog. RAM checks, then the common end path.
  - interval: 1s
    then:
      - if:
          condition:
            lambda: |-
              return id(dump_export_trip) != 0 && id(dump_active_persisted) && !id(dump_restore_requested) &&
                     !id(dump_operation_in_progress) && id(dump_snapshot_valid);
          then:
            - script.execute:
                id: request_dump_end
                reason: !lambda |-
                  char msg[200];
                  if (id(dump_export_trip) == 2) {
                    snprintf(msg, sizeof(msg), "MAXIMUM GRID EXPORT EXCEEDED - net export %.0fW above the configured %dW limit (one reading far over it)", id(dump_export_last_w), id(dump_max_export_w));
                  } else {
                    snprintf(msg, sizeof(msg), "MAXIMUM GRID EXPORT EXCEEDED - net export %.0fW above the configured %dW limit (two consecutive readings over it)", id(dump_export_last_w), id(dump_max_export_w));
                  }
                  return std::string(msg);
""")

# ---- lock_subst
LOCK_SUBST_OLD = _blk(r"""
  ecco_dump_limits_arm_window_ms: "60000"
""")
LOCK_SUBST_NEW = _blk(r"""
  ecco_dump_limits_arm_window_ms: "60000"
  # fcp2 (SG-14 / SG-42): the bound past which an inverter transaction lock (the
  # shared write mutex or a domain's operation flag) is STUCK. Every Modbus step
  # of every transaction is bounded by a 3 s wait, so no transaction can hold a
  # lock anywhere near this long; a lock held longer is a leak. A STUCK lock is
  # NEVER released by time: the lease (if any) is ended durably and, while any
  # lease or restore is owed, the device restarts so the boot path - the designed
  # recovery path, with the ownership-checked restore - completes it. With
  # nothing owed it is reported only (writes stay blocked until a restart).
  ecco_write_lock_stuck_ms: "180000"
""")

# ---- export_subst
EXPORT_SUBST_OLD = _blk(r"""
  ecco_dump_export_guard_samples: "3"
""")
EXPORT_SUBST_NEW = _blk(r"""
  ecco_dump_export_guard_samples: "3"
  # fcp2 rework (R2): the guard no longer uses the 3-of-4 rule above (kept for the
  # record): ONE sample more than max(this many W, 25 %) over the limit, or TWO
  # consecutive samples over limit + margin, end the lease - acted on within 1 s.
  ecco_dump_export_far_min_w: "500"
""")

# ---- export_hook
EXPORT_HOOK_OLD = _blk(r"""
        # fcp1 (2026-10-13): the in-lease NET GRID EXPORT guard's sample window.
        # Export = -register 172. A fresh sample is "over" when export exceeds
        # the configured maximum grid export plus max(ecco_dump_export_margin_min_w,
        # 3 %). Outside a settled lease the window is cleared. The 15 s watchdog
        # ends the lease once ecco_dump_export_guard_samples of the last four
        # samples are over. RAM only, no Modbus I/O.
        - lambda: |-
            if (!id(dump_active_persisted) || id(dump_restore_requested) || id(dump_operation_in_progress) ||
                (uint32_t) (millis() - id(dump_active_since_ms)) < ${ecco_dump_runaway_grace_ms}UL) {
              id(dump_export_window) = 0;
              return;
            }
            float limit = (float) id(dump_max_export_w);
            float margin = limit * 0.03f;
            if (margin < ${ecco_dump_export_margin_min_w}.0f) margin = ${ecco_dump_export_margin_min_w}.0f;
            bool over = !std::isnan(x) && -x > limit + margin;
            id(dump_export_window) = (uint8_t) (((id(dump_export_window) << 1) | (over ? 1 : 0)) & 15);
            if (over) id(dump_export_last_w) = -x;
""")
EXPORT_HOOK_NEW = _blk(r"""
        # fcp1 + fcp2 rework (R2): the NET GRID EXPORT guard's samples. Export = -register 172. A
        # sample is OVER when export exceeds the configured maximum plus max(ecco_dump_export_margin_min_w,
        # 3 %), and FAR OVER when it exceeds it by max(ecco_dump_export_far_min_w, 25 %). Counted from the
        # moment the lease is ACTIVE - NO start grace - and, after an End, for as long as a restore is owed
        # and register 244 is not proven out of ECCO's Allow Export (the watchdog's post-END supervision).
        # One FAR OVER sample, or two consecutive OVER samples, LATCH dump_export_trip; a 1 s interval acts
        # on it in a lease. A lease-ending SECONDARY protection on ECCO's own CT reading at the telemetry
        # cadence - NOT a DNO-compliant export limitation scheme (that is the inverter's own export limit,
        # register 245, which ECCO never writes). RAM only, no Modbus I/O.
        - lambda: |-
            bool in_lease = id(dump_active_persisted) && !id(dump_restore_requested) && !id(dump_operation_in_progress);
            bool owed = id(dump_snapshot_valid) && id(dump_restore_requested) && id(dump_export_unverified) &&
                        !id(dump_operation_in_progress);
            if (!in_lease && !owed) {
              id(dump_export_window) = 0;
              id(dump_ct_same_count) = 0;
              id(dump_ct_last_w) = x;
              return;
            }
            float limit = (float) id(dump_max_export_w);
            float margin = limit * 0.03f;
            if (margin < ${ecco_dump_export_margin_min_w}.0f) margin = ${ecco_dump_export_margin_min_w}.0f;
            float far = limit * 0.25f;
            if (far < ${ecco_dump_export_far_min_w}.0f) far = ${ecco_dump_export_far_min_w}.0f;
            bool over = !std::isnan(x) && -x > limit + margin;
            bool far_over = !std::isnan(x) && -x > limit + far;
            id(dump_export_window) = (uint8_t) (((id(dump_export_window) << 1) | (over ? 1 : 0)) & 15);
            if (over) id(dump_export_last_w) = -x;
            if (id(dump_export_trip) == 0 && (far_over || (id(dump_export_window) & 3) == 3)) {
              id(dump_export_trip) = far_over ? 2 : 1;
            }
            // the frozen-CT evidence starts after the lease-start grace (the export guard above has none)
            if (!in_lease || (uint32_t) (millis() - id(dump_active_since_ms)) < ${ecco_dump_runaway_grace_ms}UL) return;
            // fcp2 (SG-15): a FROZEN grid CT - see ecco_dump_frozen_samples. Counts exact
            // repeats of a valid reading, and the range the battery power (the previous
            // read's value) covered meanwhile.
            if (!std::isnan(x)) {
              bool b_ok = id(ecco_battery_power).has_state() && !std::isnan(id(ecco_battery_power).state);
              float b = b_ok ? id(ecco_battery_power).state : 0.0f;
              if (x == id(dump_ct_last_w)) {
                id(dump_ct_same_count)++;
                if (b_ok && b < id(dump_ct_same_bmin)) id(dump_ct_same_bmin) = b;
                if (b_ok && b > id(dump_ct_same_bmax)) id(dump_ct_same_bmax) = b;
              } else {
                // a range seeded empty when there is no battery reading yet (never "moved")
                id(dump_ct_same_count) = 0;
                id(dump_ct_same_bmin) = b_ok ? b : 1000000000.0f;
                id(dump_ct_same_bmax) = b_ok ? b : -1000000000.0f;
              }
              id(dump_ct_last_w) = x;
            }
""")

# ---- export_watchdog
EXPORT_WATCHDOG_OLD = _blk(r"""
                    uint8_t w = id(dump_export_window);
                    int over = (w & 1) + ((w >> 1) & 1) + ((w >> 2) & 1) + ((w >> 3) & 1);
                    return over >= ${ecco_dump_export_guard_samples};
""")
EXPORT_WATCHDOG_NEW = _blk(r"""
                    // fcp2 rework (R2): the latched decision (see ecco_grid_ct_power's on_value);
                    // normally already acted on by the 1 s interval - this is the backstop.
                    return id(dump_export_trip) != 0;
""")

# ---- start_flags
START_FLAGS_OLD = _blk(r"""
                id(dump_write_enable).turn_off();
                id(dump_operation_in_progress) = true;
""")
START_FLAGS_NEW = _blk(r"""
                id(dump_write_enable).turn_off();
                // fcp2 rework (R1 / F4 / R2): a NEW transaction - 244 is not proven out of ECCO's
                // Allow Export until a restore proves it, no stale link-down stamp may shorten a later
                // backoff, and no export decision or PV-surplus refusal carries over.
                id(dump_export_unverified) = true;
                id(dump_restore_failed_ms) = 0;
                id(dump_export_trip) = 0;
                id(dump_start_surplus_refused) = false;
                id(dump_operation_in_progress) = true;
""")

# ---- start_gate_export
START_GATE_EXPORT_OLD = _blk(r"""
                id(dump_export_power).state <= (float) id(dump_max_export_w) &&
""")
START_GATE_EXPORT_NEW = _blk(r"""
                id(dump_export_power).state <= (float) id(dump_max_export_w) &&
                // fcp2 rework (R2 / F7): fail closed on export - the target needs headroom below the
                // limit (at least the guard's own margin, max(min margin, 3 %)), and the export the
                // grid CT ALREADY measures (required fresh above) must be within the limit.
                id(dump_export_power).state <= (float) id(dump_max_export_w) -
                  std::max(${ecco_dump_export_margin_min_w}.0f, 0.03f * (float) id(dump_max_export_w)) &&
                -id(ecco_grid_ct_power).state <= (float) id(dump_max_export_w) &&
""")

# ---- start_refusal_texts
START_REFUSAL_TEXTS_OLD = _blk(r"""
                else if (id(dump_export_power).state > (float) id(dump_max_export_w)) id(dump_status).publish_state("REJECTED - requested export is above the configured maximum grid export");
""")
START_REFUSAL_TEXTS_NEW = _blk(r"""
                else if (id(dump_export_power).state > (float) id(dump_max_export_w)) id(dump_status).publish_state("REJECTED - requested export is above the configured maximum grid export");
                else if (id(dump_export_power).state > (float) id(dump_max_export_w) - std::max(${ecco_dump_export_margin_min_w}.0f, 0.03f * (float) id(dump_max_export_w))) id(dump_status).publish_state("REJECTED - requested export leaves no headroom below the maximum grid export (keep it at least max(${ecco_dump_export_margin_min_w} W, 3 %) below)");
                else if (-id(ecco_grid_ct_power).state > (float) id(dump_max_export_w)) id(dump_status).publish_state("REJECTED - the grid meter already shows export above the configured maximum grid export");
""")

# ---- start_surplus_check
START_SURPLUS_CHECK_OLD = _blk(r"""
                      if (trustworthy) {
                        // required_ceiling = house_load + requested_export -
""")
START_SURPLUS_CHECK_NEW = _blk(r"""
                      // fcp2 rework (R2): fail closed on a natural PV export surplus the fresh START read
                      // already shows above the maximum grid export - Dump does not command battery charging,
                      // so it could never bring that export back under the limit. Refused BEFORE the durable
                      // commit: nothing is written. (Under Zero Export the inverter throttles PV, so this sees
                      // only the surplus it shows; the in-lease guard covers the rest.)
                      if (trustworthy && pv_power - house_load > (float) id(dump_max_export_w)) {
                        id(dump_start_surplus_refused) = true;
                        id(dump_start_surplus_w) = pv_power - house_load;
                        id(dump_write_failed) = true;
                      }
                      if (trustworthy) {
                        // required_ceiling = house_load + requested_export -
""")

# ---- start_surplus_text
START_SURPLUS_TEXT_OLD = _blk(r"""
                      id(dump_status).publish_state("START FAILED - could not capture/durably commit inverter snapshot; nothing written");
""")
START_SURPLUS_TEXT_NEW = _blk(r"""
                      if (id(dump_start_surplus_refused)) {
                        char msg[200];
                        snprintf(msg, sizeof(msg), "REJECTED - natural PV export surplus ~%.0fW already exceeds the configured %dW maximum grid export; nothing written", id(dump_start_surplus_w), id(dump_max_export_w));
                        id(dump_status).publish_state(msg);
                      } else {
                        id(dump_status).publish_state("START FAILED - could not capture/durably commit inverter snapshot; nothing written");
                      }
""")

# ---- post_end_supervision
POST_END_SUPERVISION_OLD = _blk(r"""
  - interval: 15s
    startup_delay: 15s
    then:
      - if:
          condition:
            lambda: |-
              if (!id(dump_snapshot_valid)) return false;
""")
POST_END_SUPERVISION_NEW = _blk(r"""
  - interval: 15s
    startup_delay: 15s
    then:
      # fcp2 rework (R1 / SG-04): SUPERVISION WHILE A RESTORE IS OWED and register 244 is not
      # proven out of ECCO's Allow Export (dump_export_unverified). The lease's own monitors stop at
      # End, but export may still be enabled: Stop SOC reached, or a NET GRID EXPORT trip (its
      # samples keep counting in this state), makes the restore retry AT ONCE - the retry contains
      # ECCO's TOU power registers at the floor while 244 is still not proven - never after a
      # backoff. Under the operator lockout it can only alarm. RAM only, no Modbus I/O here.
      - lambda: |-
          if (!id(dump_snapshot_valid) || !id(dump_restore_requested) || !id(dump_export_unverified) ||
              id(dump_recovery_metadata_corrupt)) return;
          bool soc_low = id(ecco_battery_soc).has_state() && id(dump_target_stop_soc) > 0 &&
                         (float) id(dump_target_stop_soc) >= id(ecco_battery_soc).state;
          bool export_over = id(dump_export_trip) != 0;
          if (!soc_low && !export_over) return;
          id(dump_export_trip) = 0;
          char msg[220];
          snprintf(msg, sizeof(msg), "%s - a restore is OWED and register 244 is not proven out of Allow Export: %s",
                   id(dump_operator_needed) ? "CRITICAL" : "SUPERVISION",
                   export_over ? "net export over the configured maximum" : "Stop SOC reached");
          if (!id(dump_operator_needed)) {
            id(dump_restore_next_attempt_ms) = 0;
          } else {
            id(dump_recovery_state).publish_state(std::string(msg) + " - operator action required now (Force Restore Original)");
          }
          ESP_LOGE("dump_to_grid", "%s", msg);
      - if:
          condition:
            lambda: |-
              if (!id(dump_snapshot_valid)) return false;
""")

# ---- limits_ceiling_reconfirm
LIMITS_CEILING_RECONFIRM_OLD = _blk(r"""
          int ex = id(dump_max_export_w);
          id(dump_op_ceiling_w) = req;
          id(dump_limits_cap_w) = ${ecco_dump_capability_w};
          id(dump_limits_check) = (uint32_t) req + 3u * (uint32_t) ex + 7u * (uint32_t) ${ecco_dump_capability_w} + 12345u;
          id(dump_limits_valid) = ex >= 0 && ex <= ${ecco_dump_capability_w} && ex % 10 == 0;
          // A reduction during a lease lowers that lease's latched ceiling at once; nothing ever raises it.
          if (id(dump_active_persisted) && id(dump_lease_ceiling_w) > req) id(dump_lease_ceiling_w) = req;
          if (req > cur || !id(dump_limits_valid)) id(dump_limits_arm).turn_off();
          snprintf(msg, sizeof(msg), "%s - power ceiling %d W (was %d W); maximum grid export %d W%s",
                   id(dump_limits_valid) ? "VALID" : "INVALID", req, cur, ex, ex == 0 ? " (NOT CONFIGURED)" : "");
""")
LIMITS_CEILING_RECONFIRM_NEW = _blk(r"""
          int ex = id(dump_max_export_w);
          bool was_valid = id(dump_limits_valid);
          id(dump_op_ceiling_w) = req;
          // fcp2 rework (R3): leaving INVALID needs BOTH limits confirmed again (each armed, idle) -
          // re-setting one never re-validates the other, unconfirmed stored value. Until both are
          // confirmed the integrity value is NOT recomputed, so a reboot stays INVALID too.
          if (!was_valid) id(dump_limits_reconfirm) = (uint8_t) (id(dump_limits_reconfirm) | 1);
          if (was_valid || id(dump_limits_reconfirm) == 3) {
            id(dump_limits_cap_w) = ${ecco_dump_capability_w};
            id(dump_limits_check) = (uint32_t) req + 3u * (uint32_t) ex + 7u * (uint32_t) ${ecco_dump_capability_w} + 12345u;
            id(dump_limits_valid) = ex >= 0 && ex <= ${ecco_dump_capability_w} && ex % 10 == 0;
          }
          // A reduction during a lease lowers that lease's latched ceiling at once; nothing ever raises it.
          if (id(dump_active_persisted) && id(dump_lease_ceiling_w) > req) id(dump_lease_ceiling_w) = req;
          if (req > cur || !was_valid) id(dump_limits_arm).turn_off();
          if (!id(dump_limits_valid)) {
            snprintf(msg, sizeof(msg), "INVALID - power ceiling %d W confirmed; the maximum grid export must also be set again (after INVALID both limits are re-confirmed)", req);
          } else {
            snprintf(msg, sizeof(msg), "%s - power ceiling %d W (was %d W); maximum grid export %d W%s",
                     "VALID", req, cur, ex, ex == 0 ? " (NOT CONFIGURED)" : "");
          }
""")

# ---- limits_export_reconfirm
LIMITS_EXPORT_RECONFIRM_OLD = _blk(r"""
          int op = id(dump_op_ceiling_w);
          id(dump_max_export_w) = req;
          id(dump_limits_cap_w) = ${ecco_dump_capability_w};
          id(dump_limits_check) = (uint32_t) op + 3u * (uint32_t) req + 7u * (uint32_t) ${ecco_dump_capability_w} + 12345u;
          id(dump_limits_valid) = op >= ${ecco_dump_controller_min_ceiling_w} && op <= ${ecco_dump_capability_w} &&
                                  op % ${ecco_dump_controller_round_w} == 0;
          if (req > cur || !id(dump_limits_valid)) id(dump_limits_arm).turn_off();
          snprintf(msg, sizeof(msg), "%s - power ceiling %d W; maximum grid export %d W (was %d W)%s",
                   id(dump_limits_valid) ? "VALID" : "INVALID", op, req, cur, req == 0 ? " (NOT CONFIGURED)" : "");
""")
LIMITS_EXPORT_RECONFIRM_NEW = _blk(r"""
          int op = id(dump_op_ceiling_w);
          bool was_valid = id(dump_limits_valid);
          id(dump_max_export_w) = req;
          // fcp2 rework (R3): see the power ceiling's set_action - both limits after INVALID.
          if (!was_valid) id(dump_limits_reconfirm) = (uint8_t) (id(dump_limits_reconfirm) | 2);
          if (was_valid || id(dump_limits_reconfirm) == 3) {
            id(dump_limits_cap_w) = ${ecco_dump_capability_w};
            id(dump_limits_check) = (uint32_t) op + 3u * (uint32_t) req + 7u * (uint32_t) ${ecco_dump_capability_w} + 12345u;
            id(dump_limits_valid) = op >= ${ecco_dump_controller_min_ceiling_w} && op <= ${ecco_dump_capability_w} &&
                                    op % ${ecco_dump_controller_round_w} == 0;
          }
          if (req > cur || !was_valid) id(dump_limits_arm).turn_off();
          if (!id(dump_limits_valid)) {
            snprintf(msg, sizeof(msg), "INVALID - maximum grid export %d W confirmed; the power ceiling must also be set again (after INVALID both limits are re-confirmed)", req);
          } else {
            snprintf(msg, sizeof(msg), "%s - power ceiling %d W; maximum grid export %d W (was %d W)%s",
                     "VALID", op, req, cur, req == 0 ? " (NOT CONFIGURED)" : "");
          }
""")

# ---- accept_elevated_calc
ACCEPT_ELEVATED_CALC_OLD = _blk(r"""
            bool live_is_original = live244 == id(dump_snapshot_reg244) && ceiling_matches_original;
""")
ACCEPT_ELEVATED_CALC_NEW = _blk(r"""
            bool live_is_original = live244 == id(dump_snapshot_reg244) && ceiling_matches_original;
            // fcp2 rework (R4 / SG-29c): a slot still holding ECCO's OWN ceiling (the verified or the
            // pending one) ABOVE its original is never accepted - a raised TOU power setting would
            // outlive the obligation. FOREIGN values (anything else) stay acceptable: ECCO does not
            // own them. ECCO residue at or below the original (e.g. the 500 W containment) only limits.
            int elevated = -1;
            for (int i = 0; i < 6; i++) {
              bool ecco_value = live256[i] == id(dump_target_power) || live256[i] == id(dump_evidence_pending_ceiling);
              if (elevated < 0 && live256[i] != snap256[i] && ecco_value && live256[i] > snap256[i]) elevated = i;
            }
""")

# ---- accept_elevated_refuse
ACCEPT_ELEVATED_REFUSE_OLD = _blk(r"""
            } else if (!ceiling_matches_original) {
""")
ACCEPT_ELEVATED_REFUSE_NEW = _blk(r"""
            } else if (elevated >= 0) {
              char e[200];
              snprintf(e, sizeof(e), "register %d still holds ECCO's %uW, above its original %uW - a raised TOU power setting is never accepted; use Force Restore Original or let the restore finish", 256 + elevated, live256[elevated], snap256[elevated]);
              why = e;
            } else if (!ceiling_matches_original) {
""")

# ---- gate_else_operator_text
GATE_ELSE_OPERATOR_TEXT_OLD = _blk(r"""
                } else if (id(dump_operator_needed) && !id(dump_force_restore_this_call)) {
                  id(dump_status).publish_state(
                    "OPERATOR DECISION REQUIRED - use Force Restore Original or Accept Current State"
                  );
""")
GATE_ELSE_OPERATOR_TEXT_NEW = _blk(r"""
                } else if (id(dump_operator_needed) && !id(dump_force_restore_this_call)) {
                  // fcp2 rework (SG-04): the waiting status never hides an unproven register 244.
                  std::string unproven = "";
                  if (id(dump_export_unverified) && id(dump_restore_contained)) {
                    unproven = "; register 244 is NOT proven out of Allow Export - every ECCO-controlled TOU power register is held at the 500 W floor";
                  } else if (id(dump_export_unverified)) {
                    unproven = "; register 244 is NOT proven out of Allow Export - export may continue";
                  }
                  id(dump_status).publish_state(
                    std::string("OPERATOR DECISION REQUIRED - use Force Restore Original or Accept Current State") + unproven
                  );
""")

EDITS = (
    Edit('dc_allowance_subst', DC_ALLOWANCE_SUBST_OLD, DC_ALLOWANCE_SUBST_NEW),
    Edit('window_subst', WINDOW_SUBST_OLD, WINDOW_SUBST_NEW),
    Edit('window_asserts', WINDOW_ASSERTS_OLD, WINDOW_ASSERTS_NEW),
    Edit('window_globals', WINDOW_GLOBALS_OLD, WINDOW_GLOBALS_NEW),
    Edit('abs_margin', ABS_MARGIN_OLD, ABS_MARGIN_NEW),
    Edit('window_update', WINDOW_UPDATE_OLD, WINDOW_UPDATE_NEW),
    Edit('window_start_clear', WINDOW_START_CLEAR_OLD, WINDOW_START_CLEAR_NEW),
    Edit('window_watchdog', WINDOW_WATCHDOG_OLD, WINDOW_WATCHDOG_NEW),
    Edit('sg40_global', SG40_GLOBAL_OLD, SG40_GLOBAL_NEW),
    Edit('sg40_reset', SG40_RESET_OLD, SG40_RESET_NEW),
    Edit('sg40_after_mutex', SG40_AFTER_MUTEX_OLD, SG40_AFTER_MUTEX_NEW),
    Edit('sg40_r3_gate', SG40_R3_GATE_OLD, SG40_R3_GATE_NEW),
    Edit('sg40_write_gate', SG40_WRITE_GATE_OLD, SG40_WRITE_GATE_NEW),
    Edit('sg40_verify_gate', SG40_VERIFY_GATE_OLD, SG40_VERIFY_GATE_NEW),
    Edit('sg40_cancel_close', SG40_CANCEL_CLOSE_OLD, SG40_CANCEL_CLOSE_NEW),
    Edit('restore_globals', RESTORE_GLOBALS_OLD, RESTORE_GLOBALS_NEW),
    Edit('restore_body', RESTORE_BODY_OLD, RESTORE_BODY_NEW),
    Edit('frozen_subst', FROZEN_SUBST_OLD, FROZEN_SUBST_NEW),
    Edit('frozen_bp_track', FROZEN_BP_TRACK_OLD, FROZEN_BP_TRACK_NEW),
    Edit('frozen_soc_reset', FROZEN_SOC_RESET_OLD, FROZEN_SOC_RESET_NEW),
    Edit('backoff_gate', BACKOFF_GATE_OLD, BACKOFF_GATE_NEW),
    Edit('build_tag_subst', BUILD_TAG_SUBST_OLD, BUILD_TAG_SUBST_NEW),
    Edit('safe_mode_block', SAFE_MODE_BLOCK_OLD, SAFE_MODE_BLOCK_NEW),
    Edit('restart_arm_switch', RESTART_ARM_SWITCH_OLD, RESTART_ARM_SWITCH_NEW),
    Edit('identity_text_sensors', IDENTITY_TEXT_SENSORS_OLD, IDENTITY_TEXT_SENSORS_NEW),
    Edit('safe_to_flash_binary', SAFE_TO_FLASH_BINARY_OLD, SAFE_TO_FLASH_BINARY_NEW),
    Edit('restart_button', RESTART_BUTTON_OLD, RESTART_BUTTON_NEW),
    Edit('census_scripts', CENSUS_SCRIPTS_OLD, CENSUS_SCRIPTS_NEW),
    Edit('census_interval', CENSUS_INTERVAL_OLD, CENSUS_INTERVAL_NEW),
    Edit('lock_subst', LOCK_SUBST_OLD, LOCK_SUBST_NEW),
    Edit('export_subst', EXPORT_SUBST_OLD, EXPORT_SUBST_NEW),
    Edit('export_hook', EXPORT_HOOK_OLD, EXPORT_HOOK_NEW),
    Edit('export_watchdog', EXPORT_WATCHDOG_OLD, EXPORT_WATCHDOG_NEW),
    Edit('start_flags', START_FLAGS_OLD, START_FLAGS_NEW),
    Edit('start_gate_export', START_GATE_EXPORT_OLD, START_GATE_EXPORT_NEW),
    Edit('start_refusal_texts', START_REFUSAL_TEXTS_OLD, START_REFUSAL_TEXTS_NEW),
    Edit('start_surplus_check', START_SURPLUS_CHECK_OLD, START_SURPLUS_CHECK_NEW),
    Edit('start_surplus_text', START_SURPLUS_TEXT_OLD, START_SURPLUS_TEXT_NEW),
    Edit('post_end_supervision', POST_END_SUPERVISION_OLD, POST_END_SUPERVISION_NEW),
    Edit('limits_ceiling_reconfirm', LIMITS_CEILING_RECONFIRM_OLD, LIMITS_CEILING_RECONFIRM_NEW),
    Edit('limits_export_reconfirm', LIMITS_EXPORT_RECONFIRM_OLD, LIMITS_EXPORT_RECONFIRM_NEW),
    Edit('accept_elevated_calc', ACCEPT_ELEVATED_CALC_OLD, ACCEPT_ELEVATED_CALC_NEW),
    Edit('accept_elevated_refuse', ACCEPT_ELEVATED_REFUSE_OLD, ACCEPT_ELEVATED_REFUSE_NEW),
    Edit('gate_else_operator_text', GATE_ELSE_OPERATOR_TEXT_OLD, GATE_ELSE_OPERATOR_TEXT_NEW),
)
EDIT_NAMES = tuple(e.name for e in EDITS)


def pre_fcp2_firmware(text: str) -> str:
    """The firmware text with exactly fcp2's edits undone (the exact-match reverter of chain entry fcp2). Every edit must occur
    exactly once, in place, else AssertionError; after the revert every base anchor must again be unique. Reproduces the fcp1
    firmware byte for byte (BASE_FW_SHA)."""
    out = text
    for e in reversed(EDITS):
        out = _swap(out, e.after, e.before, f"{e.name} edit", "present")
    for e in EDITS:
        n = out.count(e.before)
        if n != 1:
            raise AssertionError(f"fcp2 scope: the {e.name} anchor must be unique once the edit is removed, found {n}x")
    return out


def add_fcp2_firmware(text: str) -> str:
    """Applies fcp2's edits, in order, to the fcp1 firmware (the round trip)."""
    out = text
    for e in EDITS:
        if e.after in out:
            raise AssertionError(f"fcp2 scope: {e.name} edit already present")
        out = _swap(out, e.before, e.after, f"{e.name} anchor", "found")
    return out


# fcp2 edits no frozen file.
FROZEN_REVERTERS: dict = {}
