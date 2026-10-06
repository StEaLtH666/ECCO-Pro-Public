"""FB-B2 t-gates: the mutant table.

Every mutant is a deliberately broken copy of the thing under test:
  * "yaml"    an exact-count text edit of a COPY of the firmware YAML (anchored in one script, in the api action, in the interval, ...);
  * "save"    an exact-count edit of a copy of registry/fallback_save.py (the Python mirror of ecco_fallback_save.h that the harness runs
              the YAML's ecco_fbsave:: calls through);
  * "capture" an exact-count edit of a copy of registry/fallback_capture.py (candidate_expired, ...: the FB-B1 mirror both the YAML and the
              save mirror call);
  * "combo"   several of the above (a mutant whose effect needs two coordinated breakages).
The mutant runs the scenarios named in `killers` on the mutated firmware: it is KILLED iff EVERY named scenario reports at least one failing
row on it (the same scenarios pass on the real firmware - checked first). An exception inside a scenario is an ERROR, never a kill.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import _fbb2_gates_lib as L
from _fbb2_gates_lib import Mk, edit_script, edit_text, live_text, mirror_mutant

SAVE = "fallback_profile_save"
DISP = "fallback_profile_capture_dispatch"
REVIEW = "fallback_profile_review"
# the G4 / G5 / G6 blocks of registry/fallback_save.py::save_gate_with_result (for the reorder mutant)
G4_BLOCK = "    if cap.candidate_expired(inp.now_ms, inp.cand_ms):  # G4\n        return save_refuse(r, SG_EXPIRED, save_expired_text())\n"
G5_BLOCK = "    if not is_hex16(target_id, target_len):  # G5\n        return save_refuse(r, SG_ID_FORMAT, save_id_format_text())\n"
G6_BLOCK = ("    if parse_hex16(target_id, target_len) != inp.cand_id:  # G6\n"
            "        return save_refuse(r, SG_ID_MISMATCH, save_id_mismatch_text())\n")
# the pre-commit drain's wait_until (condition + 3000 ms timeout), as it stands in the dispatch
DRAIN_OLD = DISP
DRAIN_OLD_T = ("                condition:\n                  lambda: 'return !id(poll_inverter_configuration_dispatch).is_running() && "
               "!id(poll_inverter_telemetry).is_running() && id(inverter_modbus)->tx_buffer_empty() && !id(inverter_modbus)->tx_blocked();'\n"
               "                timeout: 3000ms")


@dataclass
class Mutant:
    mid: str
    desc: str
    killers: list
    yaml: list = field(default_factory=list)       # [("script", id, old, new[, count]) | ("text", old, new[, count])]
    save: tuple | None = None                      # (old, new[, count]) on registry/fallback_save.py
    capture: tuple | None = None                   # (old, new[, count]) on registry/fallback_capture.py

    def build(self) -> Mk:
        text = None
        if self.yaml:
            text = live_text()
            for e in self.yaml:
                if e[0] == "script":
                    text = edit_script(text, e[1], e[2], e[3], e[4] if len(e) > 4 else 1)
                else:
                    text = edit_text(text, e[1], e[2], e[3] if len(e) > 3 else 1)
        fbsave = fbcap = None
        if self.capture is not None:
            fbsave, fbcap = mirror_mutant(self.capture[0], self.capture[1], self.capture[2] if len(self.capture) > 2 else 1, which="capture")
        if self.save is not None:
            if self.capture is not None:
                raise AssertionError("a mutant edits one mirror")
            fbsave, fbcap = mirror_mutant(self.save[0], self.save[1], self.save[2] if len(self.save) > 2 else 1, which="save")
        return Mk(self.mid, text=text, fbsave=fbsave, fbcap=fbcap)


def S(sid, old, new, count=1):
    return ("script", sid, old, new, count)


def T(old, new, count=1):
    return ("text", old, new, count)


MUTANTS: list = [
    # ------------------------------------------------------------------ the one-shot preamble / arm
    Mutant("Y01", "drop the arm check: the gate treats the arm as always on (G2)", ["rf_arm", "rc_model_based_sequences"],
           yaml=[S(SAVE, "si.arm_was_on = armed;", "si.arm_was_on = true;")]),
    Mutant("Y02", "skip IE2: the SAVE call does not consume the candidate", ["rf_arm", "rf_tokens"],
           yaml=[S(SAVE, "            id(fallback_profile_invalidate_candidate).execute();\n", "")]),
    Mutant("Y03", "IE2 BEFORE the candidate copy: the gate decides on a consumed candidate", ["ss_first_save", "os_candidate_copy_before_ie2"],
           yaml=[S(SAVE, "          const bool c_valid = id(fallback_profile_cand_valid);\n",
                   "          id(fallback_profile_invalidate_reason) = ecco_fbcap::REASON_SUPERSEDED;\n"
                   "          id(fallback_profile_invalidate_candidate).execute();\n"
                   "          const bool c_valid = id(fallback_profile_cand_valid);\n")]),
    Mutant("Y04", "one-shot preamble (IE2) BEFORE the in-flight check", ["rf_inflight"],
           yaml=[S(SAVE, "          // G1: another Fallback Profile operation is in flight - touch nothing but the arm and the result text.\n",
                   "          id(fallback_profile_invalidate_reason) = ecco_fbcap::REASON_SUPERSEDED;\n"
                   "          id(fallback_profile_invalidate_candidate).execute();\n"
                   "          // G1: another Fallback Profile operation is in flight - touch nothing but the arm and the result text.\n")]),
    Mutant("Y05", "the G1 refusal also consumes the candidate", ["rf_inflight"],
           yaml=[S(SAVE, "              id(fallback_profile_arm).turn_off();\n              if (id(fallback_profile_last_result_text).state != g1.text.c_str())",
                   "              id(fallback_profile_arm).turn_off();\n              id(fallback_profile_cand_valid) = false;\n"
                   "              if (id(fallback_profile_last_result_text).state != g1.text.c_str())")]),
    Mutant("Y06", "the G1 refusal does not turn the arm off", ["rf_inflight"],
           yaml=[S(SAVE, "              id(fallback_profile_arm).turn_off();\n              if (id(fallback_profile_last_result_text).state != g1.text.c_str())",
                   "              if (id(fallback_profile_last_result_text).state != g1.text.c_str())")]),
    Mutant("Y07", "the in-flight check ignores the running dispatch (only the op flag)", ["rf_inflight"],
           yaml=[S(SAVE, "id(fallback_profile_op_in_progress), id(fallback_profile_capture_dispatch).is_running());",
                   "id(fallback_profile_op_in_progress), false);")]),
    Mutant("Y08", "the SAVE preamble never turns the arm off (accepted and refused calls leave it on)", ["rf_tokens", "ss_first_save"],
           yaml=[S(SAVE, "          const bool armed = id(fallback_profile_arm).state;\n          id(fallback_profile_arm).turn_off();\n",
                   "          const bool armed = id(fallback_profile_arm).state;\n")]),
    Mutant("Y09", "the arm is read AFTER the turn-off (always seen as off)", ["ss_first_save"],
           yaml=[S(SAVE, "          const bool armed = id(fallback_profile_arm).state;\n          id(fallback_profile_arm).turn_off();\n",
                   "          id(fallback_profile_arm).turn_off();\n          const bool armed = id(fallback_profile_arm).state;\n")]),
    Mutant("Y10", "arm not turned off in the Review gate (a Review press leaves the arm on)", ["os_arm_review"],
           yaml=[S(REVIEW, "          id(fallback_profile_arm).turn_off();\n", "")]),
    Mutant("Y11", "arm not turned off in REVIEW_FINAL (an arm turned on during READING survives)", ["os_arm_review"],
           yaml=[S(DISP, "            id(fallback_profile_arm).turn_off();\n", "")]),
    Mutant("Y12", "arm lifetime tick removed (the arm never expires)", ["rf_arm_ttl"],
           yaml=[T("if (id(fallback_profile_arm).state && ecco_fbsave::arm_expired(millis(), id(fallback_profile_arm_on_ms))) {", "if (false) {")]),
    Mutant("S01", "arm TTL off by one (> instead of >=)", ["rf_arm_ttl"],
           save=("return ((now_ms - on_ms) & U32) >= ARM_TTL_MS", "return ((now_ms - on_ms) & U32) > ARM_TTL_MS")),
    Mutant("S02", "arm TTL not wrap-safe", ["rf_arm_ttl"],
           save=("return ((now_ms - on_ms) & U32) >= ARM_TTL_MS", "return (now_ms - on_ms) >= ARM_TTL_MS")),
    # ------------------------------------------------------------------ gates G0..G16
    Mutant("S03", "G3 without the id != 0 clause", ["rf_candidate"],
           save=("if not inp.cand_valid or not inp.cand_saveable or inp.cand_id == 0:  # G3", "if not inp.cand_valid or not inp.cand_saveable:  # G3")),
    Mutant("S04", "G3 lets a NOT-SAVEABLE preview through (checks only that a candidate exists)", ["rf_candidate"],
           save=("if not inp.cand_valid or not inp.cand_saveable or inp.cand_id == 0:  # G3", "if not inp.cand_valid:  # G3")),
    Mutant("S05", "accept an expired candidate (G4 removed)", ["rf_expiry"],
           save=("if cap.candidate_expired(inp.now_ms, inp.cand_ms):  # G4", "if False:  # G4")),
    Mutant("C01", "candidate TTL off by one (> instead of >=)", ["rf_expiry"],
           capture=("return ((now_ms - born_ms) & U32) >= CANDIDATE_TTL_MS", "return ((now_ms - born_ms) & U32) > CANDIDATE_TTL_MS")),
    Mutant("C02", "candidate TTL not wrap-safe (near 2^32)", ["rf_expiry"],
           capture=("return ((now_ms - born_ms) & U32) >= CANDIDATE_TTL_MS", "return (now_ms - born_ms) >= CANDIDATE_TTL_MS")),
    Mutant("Y13", "the candidate age is taken from NOW (the copied birth time is replaced)", ["rf_expiry"],
           yaml=[S(SAVE, "const uint32_t c_ms = id(fallback_profile_cand_ms);", "const uint32_t c_ms = millis();")]),
    Mutant("S06", "G6 removed (any well-formed id is accepted)", ["rf_ids"],
           save=("if parse_hex16(target_id, target_len) != inp.cand_id:  # G6", "if False:  # G6")),
    Mutant("S07", "G7 accepts the plain phrase for a CORRUPT prior (MB36)", ["rf_phrase", "ss_recapture_over_priors"],
           save=("replace_ = fd.save_requires_replace_phrase(inp.cand_prior_class)\n    expected", "replace_ = False\n    expected")),
    Mutant("S08", "gate order: G10 (heartbeat) and G11 (clock) swapped", ["rf_order_adjacent", "rf_order_suffixes"],
           save=("    if not inp.hb_ok:  # G10\n        return save_refuse(r, SG_HB, save_hb_text())\n"
                 "    if not inp.time_trusted:  # G11\n        return save_refuse(r, SG_TIME, save_time_text())\n",
                 "    if not inp.time_trusted:  # G11\n        return save_refuse(r, SG_TIME, save_time_text())\n"
                 "    if not inp.hb_ok:  # G10\n        return save_refuse(r, SG_HB, save_hb_text())\n")),
    Mutant("S09", "gate order: G2 (arm) and G3 (candidate) swapped", ["rf_order_adjacent"],
           save=("    if not inp.arm_was_on:  # G2\n        return save_refuse(r, SG_ARM_OFF, save_arm_off_text())\n"
                 "    if not inp.cand_valid or not inp.cand_saveable or inp.cand_id == 0:  # G3\n        return save_refuse(r, SG_NO_CANDIDATE, save_no_candidate_text())\n",
                 "    if not inp.cand_valid or not inp.cand_saveable or inp.cand_id == 0:  # G3\n        return save_refuse(r, SG_NO_CANDIDATE, save_no_candidate_text())\n"
                 "    if not inp.arm_was_on:  # G2\n        return save_refuse(r, SG_ARM_OFF, save_arm_off_text())\n")),
    Mutant("S10", "gate order: G12 (write arms) and G13 (writes fingerprint) swapped", ["rf_order_adjacent"],
           save=("    if gr.code == cap.GATE_REFUSE_ARMS:  # G12\n        return save_refuse(r, SG_ARMS, save_arms_text())\n"
                 "    if (inp.writes_fp_now & U32) != (inp.cand_writes_fp & U32):  # G13\n        return save_refuse(r, SG_WRITES, save_writes_text())\n",
                 "    if (inp.writes_fp_now & U32) != (inp.cand_writes_fp & U32):  # G13\n        return save_refuse(r, SG_WRITES, save_writes_text())\n"
                 "    if gr.code == cap.GATE_REFUSE_ARMS:  # G12\n        return save_refuse(r, SG_ARMS, save_arms_text())\n")),
    Mutant("Y14", "G8 input forced true (boot loaded): G8 is skipped, the order changes", ["rf_order_adjacent"],
           yaml=[S(SAVE, "si.boot_loaded = id(fallback_profile_boot_loaded);", "si.boot_loaded = true;")]),
    Mutant("Y15", "G9 input forced false (a previous unknown outcome is ignored by the gate)", ["rf_state_flags"],
           yaml=[S(SAVE, "si.unconfirmed = id(fallback_profile_save_unconfirmed);", "si.unconfirmed = false;")]),
    Mutant("Y16", "G9a input forced 0 (a read anomaly is ignored by the gate)", ["rf_state_flags"],
           yaml=[S(SAVE, "si.read_anomaly = id(fallback_profile_read_anomaly);", "si.read_anomaly = 0;")]),
    Mutant("Y17", "G13 skipped (the writes fingerprint compared with itself)", ["rf_writes_fingerprint"],
           yaml=[S(SAVE, "          si.boot_loaded = id(fallback_profile_boot_loaded);\n",
                   "          si.writes_fp_now = si.cand_writes_fp;\n          si.boot_loaded = id(fallback_profile_boot_loaded);\n")]),
    Mutant("Y18", "heartbeat snapshot always true in the api action", ["rf_hb", "rc_model_based_sequences"],
           yaml=[T("id(fallback_profile_exec_hb_ok) = (id(supervision_state) == 1) && id(supervision_stable);", "id(fallback_profile_exec_hb_ok) = true;")]),
    Mutant("Y19", "heartbeat snapshot without the Stable flag", ["rf_hb"],
           yaml=[T("id(fallback_profile_exec_hb_ok) = (id(supervision_state) == 1) && id(supervision_stable);", "id(fallback_profile_exec_hb_ok) = (id(supervision_state) == 1);")]),
    # FB-B2 hardening: the heartbeat is re-checked right before the durable commit (SAVE_FINAL part 2).
    Mutant("Y20", "the commit-time heartbeat re-check removed (back to a pure snapshot at execute)", ["rc_heartbeat_rechecked_before_commit"],
           yaml=[T("if (!((id(supervision_state) == 1) && id(supervision_stable))) {", "if (false) {")]),
    Mutant("Y20b", "the commit-time heartbeat re-check ignores the Stable flag", ["rc_heartbeat_rechecked_before_commit"],
           yaml=[T("if (!((id(supervision_state) == 1) && id(supervision_stable))) {", "if (!(id(supervision_state) == 1)) {")]),
    Mutant("Y20c", "the commit-time heartbeat re-check ignores the supervision state (Stable flag only)", ["rc_heartbeat_rechecked_before_commit"],
           yaml=[T("if (!((id(supervision_state) == 1) && id(supervision_stable))) {", "if (!id(supervision_stable)) {")]),
    Mutant("Y20d", "the commit-time heartbeat check runs only as a refusal text (the writer is still called)", ["rc_heartbeat_rechecked_before_commit"],
           yaml=[T("                res = ecco_fbsave::save_hb_text();\n                go = false;\n              } else if (!ecco_fbsave::commit_bus_quiet(",
                   "                res = ecco_fbsave::save_hb_text();\n                go = false;\n              }\n              if (!ecco_fbsave::commit_bus_quiet(")]),
    Mutant("Y21", "the heartbeat read inside the SAVE gate script instead of the api lambda snapshot", ["st_no_supervision_in_fb_code"],
           yaml=[S(SAVE, "si.hb_ok = id(fallback_profile_exec_hb_ok);", "si.hb_ok = (id(supervision_state) == 1) && id(supervision_stable);")]),
    Mutant("Y22", "NTP trust forced true at the gate", ["rf_time", "rc_model_based_sequences"],
           yaml=[S(SAVE, "si.time_trusted = id(ntp_synced) && id(ntp_time).now().is_valid();", "si.time_trusted = true;")]),
    Mutant("Y23", "NTP trust without the validity check of now()", ["rf_time"],
           yaml=[S(SAVE, "si.time_trusted = id(ntp_synced) && id(ntp_time).now().is_valid();", "si.time_trusted = id(ntp_synced);")]),
    Mutant("Y24", "NTP trust without the ntp_synced flag", ["rf_time"],
           yaml=[S(SAVE, "si.time_trusted = id(ntp_synced) && id(ntp_time).now().is_valid();", "si.time_trusted = id(ntp_time).now().is_valid();")]),
    Mutant("Y25", "the Manual Configuration write arm is not looked at", ["rf_write_arms"],
           yaml=[S(SAVE, "gi.manual_config_write_enable = id(manual_config_write_enable).state;", "gi.manual_config_write_enable = false;")]),
    Mutant("Y26", "the Free Power write arm is not looked at", ["rf_write_arms"],
           yaml=[S(SAVE, "gi.free_power_write_enable = id(free_power_write_enable).state;", "gi.free_power_write_enable = false;")]),
    Mutant("Y27", "the Dump to Grid write arm is not looked at", ["rf_write_arms"],
           yaml=[S(SAVE, "gi.dump_write_enable = id(dump_write_enable).state;", "gi.dump_write_enable = false;")]),
    Mutant("Y28", "the write mutex flag is not part of the BUS slot input", ["rf_bus"],
           yaml=[S(SAVE, "gi.bus.manual_write_in_progress = id(manual_write_in_progress);", "gi.bus.manual_write_in_progress = false;")]),
    Mutant("Y29", "the RTC verification-pending flag is not part of the BUS slot input", ["rf_bus"],
           yaml=[S(SAVE, "gi.bus.verification_pending = id(verification_pending);", "gi.bus.verification_pending = false;")]),
    Mutant("Y30", "the failback record slot is not part of the gate input", ["rf_fbs"],
           yaml=[S(SAVE, "gi.fbs_slot = id(fallback_profile_fbs_slot);", "gi.fbs_slot = 1;")]),
    Mutant("Y31", "the Dump marker state is not part of the gate input", ["rf_leases"],
           yaml=[S(SAVE, "gi.dump.dump_marker_state = id(dump_marker_state);", "gi.dump.dump_marker_state = 0;")]),
    Mutant("Y32", "the runtime probe latch is not part of the gate input", ["rf_probe_latch"],
           yaml=[S(SAVE, "gi.probe_latch = id(fallback_profile_probe_latch);", "gi.probe_latch = 0;")]),
    # ------------------------------------------------------------------ the accept branch / the dispatch
    # FB-B2 (final review F4): also killed BEHAVIOURALLY by the colliding-writer scenario (T-CAP-17, SAVE side)
    Mutant("Y33", "the accept branch does not take the write mutex", ["ss_saving_state_deferred_bus", "rc_collision_writers_during_save"],
           yaml=[S(SAVE, "            id(manual_write_in_progress) = true;\n", "")]),
    Mutant("Y34", "the accept branch sets the REVIEW purpose instead of SAVE", ["ss_first_save"],
           yaml=[S(SAVE, "id(fallback_profile_op_purpose) = ecco_fbsave::PURPOSE_SAVE;", "id(fallback_profile_op_purpose) = ecco_fbcap::PURPOSE_REVIEW;")]),
    Mutant("Y35", "the SAVING state is never published", ["ss_saving_state_deferred_bus"],
           yaml=[S(SAVE, "id(fallback_profile_capture_state) = ecco_fbcap::CAPTURE_SAVING;", "id(fallback_profile_capture_state) = ecco_fbcap::CAPTURE_IDLE;")]),
    Mutant("Y36", "the in-progress line is not published on acceptance", ["ss_saving_state_deferred_bus"],
           yaml=[S(SAVE, "ecco_fbcap::TextBuf t = ecco_fbsave::save_in_progress_text();", "ecco_fbcap::TextBuf t = ecco_fbcap::candidate_ready_text();")]),
    Mutant("Y37", "the candidate id is not copied into the save context", ["ss_first_save"],
           yaml=[S(SAVE, "id(fallback_profile_save_ctx_id) = c_id;", "id(fallback_profile_save_ctx_id) = 0;")]),
    Mutant("Y38", "the REPLACE CORRUPT flag is not copied into the save context", ["ss_recapture_over_priors"],
           yaml=[S(SAVE, "id(fallback_profile_save_ctx_replace_corrupt) = sr.replace_corrupt;", "id(fallback_profile_save_ctx_replace_corrupt) = false;")]),
    Mutant("Y39", "REVIEW_FINAL is not guarded by the purpose (it runs for a SAVE dispatch)", ["ss_first_save", "ss_saving_state_deferred_bus"],
           yaml=[S(DISP, "          if (id(fallback_profile_op_purpose) == ecco_fbsave::PURPOSE_SAVE) return;\n", "")]),
    Mutant("Y40", "the SAVE final part 1 runs for every purpose (no purpose guard)", ["ss_first_save"],
           yaml=[S(DISP, "          if (id(fallback_profile_op_purpose) != ecco_fbsave::PURPOSE_SAVE) return;\n", "")]),
    Mutant("Y41", "the pre-commit drain is removed (never waits for the bus after the last read)", ["rf_dispatch_bus"],
           yaml=[S(DISP, "lambda: 'return id(fallback_profile_op_purpose) == ecco_fbsave::PURPOSE_SAVE && !id(fallback_profile_read_failed);'",
                   "lambda: 'return false;'")]),
    Mutant("Y42", "release not reached on a read failure (the mutex stays held)", ["rf_read_failures"],
           yaml=[S(DISP, "          id(fallback_profile_op_in_progress) = false;\n          id(manual_write_in_progress) = false;\n          id(fallback_profile_step) = 0;",
                   "          id(fallback_profile_op_in_progress) = false;\n          id(manual_write_in_progress) = id(fallback_profile_read_failed);\n          id(fallback_profile_step) = 0;")]),
    Mutant("Y43", "the release does not clear the save context", ["ss_first_save"],
           yaml=[S(DISP, "          id(fallback_profile_save_ctx_valid) = false;\n", "")]),
    Mutant("Y44", "the leak breaker assigns the shared write mutex", ["rc_tick_during_saving"],
           yaml=[T("            id(fallback_profile_step) = 0;\n            // FB-B2: the save context taken at the SAVE gate is cleared here too (the write mutex is not touched).\n",
                   "            id(fallback_profile_step) = 0;\n            id(manual_write_in_progress) = false;\n"
                   "            // FB-B2: the save context taken at the SAVE gate is cleared here too (the write mutex is not touched).\n")]),
    Mutant("Y45", "the leak breaker does not clear the save context", ["rc_tick_during_saving"],
           yaml=[T("            // FB-B2: the save context taken at the SAVE gate is cleared here too (the write mutex is not touched).\n            id(fallback_profile_save_ctx_valid) = false;\n",
                   "            // FB-B2: the save context taken at the SAVE gate is cleared here too (the write mutex is not touched).\n")]),
    # ------------------------------------------------------------------ SAVE final
    Mutant("Y46", "skip pass1 == pass2 (the two passes are not compared)", ["rc_word_differs_between_passes", "rc_deferred_bank_sweep"],
           yaml=[S(DISP, "if (go && ecco_fbcap::first_diff(id(fallback_profile_pass1), id(fallback_profile_pass2)) >= 0) {", "if (false) {")]),
    Mutant("Y47", "skip pass2 == candidate (the live words are not compared with the reviewed words)", ["rc_word_changed_since_review", "rc_deferred_bank_sweep"],
           yaml=[S(DISP, "if (go && ecco_fbcap::first_diff(id(fallback_profile_save_ctx_words), id(fallback_profile_pass2)) >= 0) {", "if (false) {")]),
    Mutant("Y48", "commit the candidate words instead of pass 2", ["rc_clobbered_candidate_and_call", "st_final_lambdas"],
           yaml=[S(DISP, "pi.words = id(fallback_profile_pass2);", "pi.words = id(fallback_profile_cand_words);")]),
    Mutant("Y49", "skip the stored-prior check (the candidate's bound prior is replaced by the fresh read)", ["rc_stored_profile_changed"],
           yaml=[S(DISP, "            pi.cand_prior_class = id(fallback_profile_save_ctx_prior_class);\n"
                   "            pi.cand_prior_gen = id(fallback_profile_save_ctx_prior_gen);\n"
                   "            pi.cand_prior_binding = id(fallback_profile_save_ctx_prior_binding);\n",
                   "            const ecco_fbcap::PriorFingerprint fresh_pf = ecco_fbcap::prior_fingerprint(lp, p, dp.stored_len);\n"
                   "            pi.cand_prior_class = pi.cls;\n            pi.cand_prior_gen = fresh_pf.generation;\n            pi.cand_prior_binding = fresh_pf.binding;\n")]),
    Mutant("S11", "plan_save skips the stored-prior check", ["rc_stored_profile_changed"],
           save=("    if inp.cls != inp.cand_prior_class or f.generation != inp.cand_prior_gen or f.binding != inp.cand_prior_binding:\n        return plan_refuse(r, PLAN_PRIOR_CHANGED",
                 "    if False:\n        return plan_refuse(r, PLAN_PRIOR_CHANGED")),
    Mutant("Y50", "skip the final obligation re-vector (no RAM-leg / marker check in the final lambda)", ["rc_temporary_operation_mid_dispatch", "rf_final_probes"],
           yaml=[S(DISP, "          if (go) {\n            ecco_fbcap::GateInputs gi{};", "          if (false) {\n            ecco_fbcap::GateInputs gi{};")]),
    Mutant("Y51", "the final obligation re-vector ignores the write arms", ["rc_temporary_operation_mid_dispatch"],
           yaml=[S(DISP, "gi.free_power_write_enable = id(free_power_write_enable).state;", "gi.free_power_write_enable = false;")]),
    Mutant("Y52", "the probe latch is not written back (the runtime probe result is not sticky)", ["rf_final_probes"],
           yaml=[S(DISP, "            id(fallback_profile_probe_latch) = fg.gr.latch;\n", "")]),
    Mutant("S12", "final_phase_inputs does not mask the SAVE's own holds", ["ss_first_save"],
           save=("    bus = replace(g.bus, fallback_profile_op_in_progress=False, fallback_profile_capture_dispatch_running=False,\n                  manual_write_in_progress=False)",
                 "    bus = replace(g.bus)")),
    Mutant("Y53", "skip the NTP re-check and sample the epoch without trust", ["rc_clock_lost_before_commit"],
           yaml=[S(DISP, "epoch = time_ok ? (uint32_t) id(ntp_time).now().timestamp : 0u;", "epoch = (uint32_t) id(ntp_time).now().timestamp;"),
                 S(DISP, "if (!ecco_fbsave::clock_trusted_for_save(time_ok, epoch)) {", "if (false) {")]),
    Mutant("Y54", "store captured_epoch = 0 (NTP re-check, epoch sampling and the plan's epoch guard all removed)", ["rc_clock_lost_before_commit", "ss_first_save"],
           yaml=[S(DISP, "epoch = time_ok ? (uint32_t) id(ntp_time).now().timestamp : 0u;", "epoch = 0u;"),
                 S(DISP, "if (!ecco_fbsave::clock_trusted_for_save(time_ok, epoch)) {", "if (false) {")],
           save=("    if (inp.captured_epoch & U32) == 0:\n        return plan_refuse(r, PLAN_CLOCK, save_time_text())\n", "")),
    Mutant("Y55", "skip the bus-quiet check before the commit", ["rf_dispatch_bus", "rc_temporary_operation_mid_dispatch"],
           yaml=[S(DISP, "              } else if (!ecco_fbsave::commit_bus_quiet(", "              } else if (false && !ecco_fbsave::commit_bus_quiet(")]),  # FB-B2 hardening: re-anchored (else-if after the heartbeat re-check)
    Mutant("S13", "commit_bus_quiet ignores tx_blocked", ["rf_dispatch_bus"],
           save=("return bool(op_in_progress and mutex_held and not correction_in_progress and tx_buffer_empty and not tx_blocked)",
                 "return bool(op_in_progress and mutex_held and not correction_in_progress and tx_buffer_empty)")),
    Mutant("Y56", "B9 outcome published BEFORE the mirror update", ["ss_publish_order"],
           yaml=[S(DISP, "                const ecco_fbdurable::MirrorRecords m = ecco_fbdurable::mirror_after(o, r, p, lp, w, lw);\n",
                   "                {\n                  ecco_fbcap::TextBuf t0 = ecco_fbsave::txn_outcome_text(plan.op, o, r, plan.generation, p.generation);\n"
                   "                  if (id(fallback_profile_last_result_text).state != t0.c_str()) id(fallback_profile_last_result_text).publish_state(t0.c_str());\n                }\n"
                   "                const ecco_fbdurable::MirrorRecords m = ecco_fbdurable::mirror_after(o, r, p, lp, w, lw);\n")]),
    Mutant("Y57", "the high-water mark is not raised after the commit", ["ss_first_save"],
           yaml=[S(DISP, "id(fallback_profile_seen_hw_gen) = ecco_fbdurable::next_seen_hw_gen(", "const uint32_t ignored_gen = ecco_fbdurable::next_seen_hw_gen(")]),
    Mutant("Y58", "the fresh read does not update the class mirror (the latest authoritative read must win)", ["rc_stored_profile_changed"],
           yaml=[S(DISP, "              id(fallback_profile_seen_hw_gen) = e.seen_hw_gen;\n              id(fallback_profile_class) = e.cls;\n",
                   "              id(fallback_profile_seen_hw_gen) = e.seen_hw_gen;\n")]),
    Mutant("Y59", "B2 microseconds not recorded", ["ss_first_save"],
           yaml=[S(DISP, "id(fallback_durable_last_us) = ecco_fbsave::total_us(r.w.us, r.p.us);", "id(fallback_durable_last_us) = 0;")]),
    Mutant("Y60", "the integrity check of the final lambda removed", ["rc_context_integrity"],
           yaml=[S(DISP, "          if (!ecco_fbsave::save_integrity_ok(id(fallback_profile_op_in_progress), id(fallback_profile_op_purpose)) ||\n"
                   "              !id(fallback_profile_save_ctx_valid) || id(fallback_profile_save_ctx_id) == 0) {", "          if (false) {")]),
    # ------------------------------------------------------------------ the api action
    Mutant("Y61", "the api action copies the target id with c_str() (not NUL-terminated)", ["ss_first_save"],
           yaml=[T("id(fallback_profile_exec_target_id) = target_id.str();", "id(fallback_profile_exec_target_id) = std::string(target_id.c_str());")]),
    Mutant("Y62", "the api action routes INVALIDATE to the SAVE gate", ["rf_inflight"],
           yaml=[T("lambda: 'return ecco_fbsave::is_invalidate_action(id(fallback_profile_exec_action).c_str(), id(fallback_profile_exec_action).size());'",
                   "lambda: 'return false;'")]),
    Mutant("Y63", "IE2 publishes its own B9 line (the one-shot consumption overwrites the outcome the operator waits for)", ["rf_arm"],
           yaml=[S(SAVE, "id(fallback_profile_invalidate_reason) = ecco_fbcap::REASON_SUPERSEDED;", 'id(fallback_profile_invalidate_reason) = "candidate cleared";')]),
    Mutant("Y64", "the in-flight check ignores the operation flag (only the running dispatch)", ["rf_inflight"],
           yaml=[S(SAVE, "id(fallback_profile_op_in_progress), id(fallback_profile_capture_dispatch).is_running());",
                   "false, id(fallback_profile_capture_dispatch).is_running());")]),
    Mutant("Y65", "the pre-commit drain times out after 300 ms instead of 3 s", ["rf_dispatch_bus"],
           yaml=[S(DRAIN_OLD, DRAIN_OLD_T, DRAIN_OLD_T.replace("3000ms", "300ms"))]),
    Mutant("Y66", "the idle wait before the reads times out after 70 ms instead of 7 s", ["rf_dispatch_bus"],
           yaml=[S(DISP, "          timeout: 7000ms", "          timeout: 70ms")]),
    Mutant("Y67", "a read failure is not looked at by the SAVE final lambda", ["rf_read_failures"],
           yaml=[S(DISP, "          if (go && id(fallback_profile_read_failed)) {\n            res = ecco_fbsave::save_read_fail_text(",
                   "          if (false) {\n            res = ecco_fbsave::save_read_fail_text(")]),
    Mutant("Y68", "captured_epoch taken from the uptime instead of the wall clock", ["ss_first_save", "ss_time_flows_epoch"],
           yaml=[S(DISP, "epoch = time_ok ? (uint32_t) id(ntp_time).now().timestamp : 0u;", "epoch = time_ok ? (uint32_t) (millis() / 1000u) + 1u : 0u;")]),
    Mutant("S15", "G5 accepts lower-case hex digits", ["rf_ids"],
           save=("    return 48 <= c <= 57 or 65 <= c <= 70", "    return 48 <= c <= 57 or 65 <= c <= 70 or 97 <= c <= 102")),
    Mutant("S16", "G7 accepts a phrase with trailing characters (prefix match)", ["rf_phrase"],
           save=('    if b is None or len(expected) == 0 or n != len(expected):\n        return False\n    return b[:n] == str(expected).encode("utf-8")',
                 '    if b is None or len(expected) == 0 or n < len(expected):\n        return False\n    return b[:len(expected)] == str(expected).encode("utf-8")')),
    Mutant("S17", "the unsupported-token echo is not truncated to 24 characters", ["rf_tokens"],
           save=("for i in range(m)), ECHO_MAX)", "for i in range(m)), m)")),  # FB-B2: re-anchored after the F2 echo mask
    Mutant("S18", "the unsupported-token echo lets ';' through (sanitiser)", ["rf_tokens"],
           save=("or 48 <= c <= 57 or c == 95", "or 48 <= c <= 57 or c == 95 or c == 59")),
    Mutant("Y69", "IE8 removed: an unknown outcome / read anomaly no longer consumes a pending candidate", ["rf_tick_invalidation"],
           yaml=[T("(id(fallback_profile_save_unconfirmed) || id(fallback_profile_read_anomaly) != 0)) {", "false) {")]),
    Mutant("S19", "gate order: G6 (id mismatch) evaluated BEFORE G4 (expiry) - a non-adjacent reorder only the full pair sweep can see", ["rf_order_pairs"],
           save=(G4_BLOCK + G5_BLOCK + G6_BLOCK, G5_BLOCK + G6_BLOCK + G4_BLOCK)),
    Mutant("C03", "the candidate lifetime is 100 s instead of 120 s", ["rf_expiry", "rc_model_based_sequences"],
           capture=("CANDIDATE_TTL_MS = 120000", "CANDIDATE_TTL_MS = 100000")),
    Mutant("S20", "the arm lifetime constant is 60 s instead of 120 s", ["rf_arm_ttl"],
           save=("ARM_TTL_MS = 120000", "ARM_TTL_MS = 60000")),
    Mutant("S14", "the router never selects INVALIDATE", ["rf_inflight"],
           save=("def is_invalidate_action(action, n=None) -> bool:\n    return action_token(action, n) == ACT_INVALIDATE",
                 "def is_invalidate_action(action, n=None) -> bool:\n    return False")),
]


# ---------------------------------------------------------------------------------------------------------------------------------------
# FB-B2 final review (gates-extra): F3 requirement 9 through the real YAML, F4 the SAVE side of T-CAP-17, F5 every obligation input of
# the final re-check, F6 the commit-time tx_buffer_empty term, F7 the profile never updates itself, N14 the final vector's B3 text.
# ---------------------------------------------------------------------------------------------------------------------------------------
# the second housekeeping lambda's last statement (the IE8 block): the anchor the F7 mutants append to
HK_TAIL = ("              (id(fallback_profile_save_unconfirmed) || id(fallback_profile_read_anomaly) != 0)) {\n"
           "            id(fallback_profile_invalidate_reason) = ecco_fbcap::REASON_SUPERSEDED;\n"
           "            id(fallback_profile_invalidate_candidate).execute();\n"
           "          }\n")
HK_WRITE = "          { ecco_fbdurable::EspNvs nvsw; nvsw.set_blob(ecco_fbdurable::FAILBACK_PROVISION_KEY, id(fallback_witness_bytes)); }\n"
FBC1_HEAD = "          if (id(supervision_generation) == 0) return;\n"

MUTANTS += [
    # ------------------------------------------------------------------ F3: all profile values still pass validation
    Mutant("Y70", "SAVE final part 1: the capture checks are not run again on pass 2 (the L2 re-check, step 4, removed)", ["rc_l2_defence_in_depth"],
           yaml=[S(DISP, "if (l2.count > 0) {", "if (false) {")]),
    # (plan_save's PO14 pre-validation is a pre-flight of the FB-B0 writer's own transition validation, which refuses the same record with the
    # same text and no NVS operation: removing PO14 alone is an equivalent mutant, so the text of that refusal is what is mutated)
    Mutant("S21", "the 'built record did not validate' refusal loses its 'nothing written' promise", ["rc_l2_defence_in_depth"],
           save=('return save_refused("internal: built record did not validate; nothing written")', 'return save_refused("internal: built record did not validate")')),
    Mutant("S22", "the L2 refusal text loses its 'profile unchanged' suffix", ["rc_l2_defence_in_depth"],
           save=('return save_refused(reasons + "; profile unchanged")', "return save_refused(reasons)")),
    # ------------------------------------------------------------------ F6: the commit-time tx_buffer_empty term of the bus-quiet predicate
    Mutant("Y71", "the commit's bus-quiet check ignores tx_buffer_empty (a frame queued on the hub and never sent)", ["rf_dispatch_bus"],
           yaml=[S(DISP, "id(correction_in_progress), id(inverter_modbus)->tx_buffer_empty(),", "id(correction_in_progress), true,")]),
    Mutant("S23", "commit_bus_quiet ignores tx_buffer_empty", ["rf_dispatch_bus"],
           save=("return bool(op_in_progress and mutex_held and not correction_in_progress and tx_buffer_empty and not tx_blocked)",
                 "return bool(op_in_progress and mutex_held and not correction_in_progress and not tx_blocked)")),
    # ------------------------------------------------------------------ F7: the profile never updates itself (a writer in an interval)
    Mutant("Y72", "the second housekeeping lambda writes the RAM mirror of the witness to its durable key (an interval writer; a refused commit_transition_t "
                  "would touch nothing, so a real write is the mutant)", ["os_no_autowrite_idle"],
           yaml=[T(HK_TAIL, HK_TAIL + HK_WRITE)]),
    Mutant("Y73", "the FB-C1 shadow tick writes the RAM mirror of the profile to the durable key (an FB-C writer)", ["os_no_autowrite_idle"],
           yaml=[T(FBC1_HEAD, FBC1_HEAD + "          { ecco_fbdurable::EspNvs nvsw; nvsw.set_blob(ecco_fbdurable::FALLBACK_PROFILE_KEY, id(fallback_profile_bytes)); }\n")]),
    Mutant("Y74", "the housekeeping tick moves the RAM high-water mark of the stored profile (a mirror write)", ["os_no_autowrite_idle"],
           yaml=[T(HK_TAIL, HK_TAIL + "          id(fallback_profile_seen_hw_gen) = id(fallback_profile_seen_hw_gen) + 1;\n")]),
    # ------------------------------------------------------------------ N14: the final vector is what B3 shows after a part-1 refusal
    Mutant("Y96", "the SAVE final part 1 does not publish the obligation vector of its refusal (B3 keeps the earlier one)",
           ["rc_final_revector_inputs", "rc_temporary_operation_mid_dispatch"],
           yaml=[S(DISP, "            id(fallback_profile_obl_text) = fg.gr.obl.c_str();\n", "")]),
]

# F5: each obligation input the final re-check samples, replaced by its clear value: killed by the row of rc_final_revector_inputs that
# turns exactly that input on after reply 2.
_REVEC = [
    ("Y75", "the Dump to Grid write arm", "gi.dump_write_enable = id(dump_write_enable).state;", "gi.dump_write_enable = false;"),
    ("Y76", "the Manual Configuration write arm (a Manual TOU apply armed before the commit)",
     "gi.manual_config_write_enable = id(manual_config_write_enable).state;", "gi.manual_config_write_enable = false;"),
    ("Y77", "the Free Power recovery accept-in-progress flag",
     "gi.bus.free_power_recovery_accept_in_progress = id(free_power_recovery_accept_in_progress);", "gi.bus.free_power_recovery_accept_in_progress = false;"),
    ("Y78", "the Free Power restore-requested flag", "gi.fp.free_power_restore_requested = id(free_power_restore_requested);",
     "gi.fp.free_power_restore_requested = false;"),
    ("Y79", "the Dump to Grid restore-requested flag", "gi.dump.dump_restore_requested = id(dump_restore_requested);",
     "gi.dump.dump_restore_requested = false;"),
    ("Y80", "the Dump to Grid metadata-corrupt flag", "gi.dump.dump_recovery_metadata_corrupt = id(dump_recovery_metadata_corrupt);",
     "gi.dump.dump_recovery_metadata_corrupt = false;"),
    ("Y81", "the Dump to Grid containment state", "gi.dump.dump_containment_state = id(dump_containment_state);", "gi.dump.dump_containment_state = 0;"),
    ("Y82", "a running Free Power start script", "gi.fp.run_start = id(start_free_power_override).is_running();", "gi.fp.run_start = false;"),
    ("Y83", "a running restore_free_power_snapshot", "id(restore_free_power_snapshot).is_running() ||\n", "false ||\n"),
    ("Y84", "a running restore_free_power_snapshot_dispatch", "id(restore_free_power_snapshot_dispatch).is_running();", "false;"),
    ("Y85", "a running free_power_recovery_review", "id(free_power_recovery_review).is_running()", "false"),
    ("Y86", "a running free_power_recovery_review_dispatch", "id(free_power_recovery_review_dispatch).is_running()", "false"),
    ("Y87", "a running free_power_recovery_force_restore", "id(free_power_recovery_force_restore).is_running()", "false"),
    ("Y88", "a running free_power_recovery_force_restore_dispatch", "id(free_power_recovery_force_restore_dispatch).is_running()", "false"),
    ("Y89", "a running free_power_recovery_accept_current_state", "id(free_power_recovery_accept_current_state).is_running()", "false"),
    ("Y90", "a running free_power_recovery_accept_current_state_dispatch", "id(free_power_recovery_accept_current_state_dispatch).is_running()", "false"),
    ("Y91", "a running Dump to Grid start script", "gi.dump.run_start = id(start_dump_to_grid_override).is_running();", "gi.dump.run_start = false;"),
    ("Y92", "a running Dump to Grid restore script", "gi.dump.run_restore = id(restore_dump_to_grid_snapshot).is_running();", "gi.dump.run_restore = false;"),
    ("Y93", "a running Register 244 apply script", "gi.r244.run_apply = id(apply_reg244_settings).is_running();", "gi.r244.run_apply = false;"),
    ("Y94", "a running Register 244 restore script", "gi.r244.run_restore = id(restore_reg244_snapshot).is_running();", "gi.r244.run_restore = false;"),
]
MUTANTS += [Mutant(mid, f"the final obligation re-check does not look at {what}", ["rc_final_revector_inputs"], yaml=[S(DISP, old, new)])
            for mid, what, old, new in _REVEC]
