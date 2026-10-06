"""FB-B2 INVALIDATE mutants (t-invalidate): broken copies of the thing under test, each killed by NAMED scenarios.

Three kinds, all built by exact-count text edits (a mutant can never be a silent no-op):

  yaml    a mutated copy of the REAL firmware text (only the fallback_profile_invalidate script, or the api action router, is edited);
          run through the strict harness (Driver(text=...))
  mirror  a mutated copy of registry/fallback_save.py (the Python mirror of the ecco_fbsave header the INVALIDATE lambda calls); run
          with the REAL firmware text (Driver(fbsave=module))
  writer  a mutated FB-B0 transaction writer (the model the lambda's commit_transition_t call executes in the harness), patched in
          for the duration of the scenarios only

A mutant is KILLED when at least one of the detectors named for it reports a violation. Before any mutant runs, every named detector
must be green on the unmutated firmware (the suite checks that first). A detector that raises (the harness cannot execute the mutant)
counts as an ERROR, not as a kill.
"""

from __future__ import annotations

import contextlib
import sys
from dataclasses import dataclass
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
import _fbb2_drive as D  # noqa: E402
import _fbb2_invalidate_kit as K  # noqa: E402
import _fbb2_invalidate_scn as S  # noqa: E402
import fallback_durable as fd  # noqa: E402
from _fbb2_invalidate_kit import Errs, edit_inv  # noqa: E402

LIVE_TEXT = D.FW_PATH.read_text(encoding="utf-8")
LIVE_MIRROR = K.SAVE_MIRROR_PATH.read_text(encoding="utf-8")
ROWS = {r.name: r for r in S.refusal_rows()}
_HAND = {label: (faults, h) for label, faults, *h in S.HAND_TABLE}
MISSING_SEED = S.SEEDS_CLEAN["VALID/B14 witness missing"]


def rows_named(*names):
    miss = [n for n in names if n not in ROWS]
    if miss:
        raise D.DriverError(f"unknown refusal rows {miss}")
    return [ROWS[n] for n in names]


def run_rows(mk, *names) -> Errs:
    e = Errs()
    for r in rows_named(*names):
        for m in S.scn_refusal(mk, r):
            e.append(f"[{r.name}] {m}")
    return e


def run_rows_cand(mk, *names) -> Errs:
    """The refusal rows again with a REVIEW candidate (any kind) pending when the call arrives."""
    e = Errs()
    for r in rows_named(*names):
        for m_ in S.scn_refusal_with_candidate(mk, r):
            e.append(f"[{r.name}] {m_}")
    return e


def run_fresh(mk, *names) -> Errs:
    e = Errs()
    for r in rows_named(*names):
        for m in S.scn_fresh_followup(mk, r):
            e.append(f"[{r.name}] {m}")
    return e


def run_fault(mk, label, seed="valid", **kw) -> Errs:
    faults, h = _HAND[label]
    return S.scn_fault_row(mk, seed, faults, label, hand=tuple(h) if seed == "valid" else None, **kw)


# --------------------------------------------------------------------------- detectors
R_ARM = ("arm not on", "arm expired (130 s, housekeeping TTL)", "arm turned on, then the dongle rebooted (ALWAYS_OFF)")
R_ID = ("id format: lowercase hex", "id format: short 8-hex id (display id)", "id format: trailing newline",
        "wrong id: last digit flipped", "wrong id: only the first 8 digits right", "wrong id: only the last 8 digits right",
        "wrong id: the id the profile would have after INVALIDATE")
R_PHRASE = ("phrase: lowercase", "phrase: the id of another profile", "phrase: SAVE phrase", "phrase: trailing newline")
R_CLASS = ("class INVALIDATED (repeat)", "class PROFILE_STALE", "class PROFILE_STALE (witness binding mismatch)", "class CORRUPT (garbage record)",
           "class NOT_CAPTURED (nothing stored)", "class PROFILE_LOST (profile gone, witness remains)",
           "class INVALIDATED (repeat) with the invalidated record's own id")
R_BUS = ("bus busy: manual_write_in_progress", "bus busy: correction_in_progress", "bus busy: verification_pending",
         "bus busy: tx buffer not empty", "bus busy: tx blocked (a frame is on the wire)")
R_BUS_ALL = tuple(n for n in ROWS if n.startswith("bus busy: "))
R_SEEN = ("g+1 == seen_hw_gen (injected 8)", "g+1 < seen_hw_gen (injected 9)")
R_FBS = ("FBS record: a failback episode exists", "FBS record: corrupt", "FBS record: unreadable at boot")
R_FRESH_CLASS = ("fresh read: the class the fresh read composes is not VALID (RAM class forced VALID over a B11 mismatch pair)",
                 "fresh read: foreign witness tag (B9 SUPERSEDED), RAM class forced VALID")
R_CAND = ("with a pending candidate: arm off", "with a pending candidate: wrong phrase", "with a pending candidate: busy",
          "with a pending candidate: class INVALIDATED")

DETECTORS = {
    "clean": lambda mk: S.scn_clean(mk, "valid", reboot=False),
    "clean+reboot": lambda mk: S.scn_clean(mk, "valid", reboot=True),
    "clean+save": lambda mk: S.scn_clean(mk, "valid", tail_save=True),
    "clean-missing-witness": lambda mk: S.scn_clean(mk, MISSING_SEED, reboot=False),
    "clean-lagging": lambda mk: S.scn_clean(mk, "lag", reboot=False),
    "clean-candidate": lambda mk: S.scn_clean(mk, "valid", candidate=True, reboot=False),
    "clean-bare": lambda mk: S.scn_clean(mk, "valid", **S.CLEAN_CONDITIONS["no supervision, no NTP (fresh boot)"], reboot=False),
    "clean-write-arms": lambda mk: S.scn_clean(mk, "valid", **S.CLEAN_CONDITIONS["all three write arms on"], reboot=False),
    "clean-lease": lambda mk: S.scn_clean(mk, "valid", **S.CLEAN_CONDITIONS["active Free Power + Dump leases"], reboot=False),
    "clean-deferred-bus": S.scn_clean_deferred_bus,
    "refuse-arm": lambda mk: run_rows(mk, *R_ARM),
    "arm-one-shot": S.scn_arm_is_one_shot,
    "refuse-id": lambda mk: run_rows(mk, *R_ID),
    "refuse-phrase": lambda mk: run_rows(mk, *R_PHRASE),
    "refuse-class": lambda mk: run_rows(mk, *R_CLASS),
    "refuse-not-loaded": lambda mk: run_rows(mk, "boot never ran (durable state not loaded yet)", "not loaded flag cleared on a loaded profile"),
    "refuse-anomaly": lambda mk: run_rows(mk, "read anomaly bit 1 injected", "read anomaly bit 4 (unhealthy) injected",
                                          "read anomaly: boot read of FBP failed (unreadable seed)"),
    "refuse-unconfirmed": lambda mk: run_rows(mk, "SAVE_UNCONFIRMED injected", "SAVE_UNCONFIRMED: a previous write outcome is unknown (real flow)"),
    "refuse-seen": lambda mk: run_rows(mk, *R_SEEN),
    "refuse-exhausted": lambda mk: run_rows(mk, "generation exhausted (g = 0xFFFFFFFF)"),
    "refuse-fbs": lambda mk: run_rows(mk, *R_FBS),
    "refuse-bus": lambda mk: run_rows(mk, *R_BUS),
    "refuse-bus-all": lambda mk: run_rows(mk, *R_BUS_ALL),
    "refuse-candidate": lambda mk: run_rows(mk, *R_CAND),
    "refuse-order": lambda mk: run_rows(mk, "arm not on + wrong id + wrong phrase: the arm refusal comes first",
                                        "class check comes before the bus check", "bus busy comes before the FBS check",
                                        "generation check comes before the bus check"),
    "fresh-class": lambda mk: run_rows(mk, *R_FRESH_CLASS),
    "fresh-anomaly": lambda mk: run_rows(mk, "fresh read: FBP replaced by another valid record behind the mirror -> same-boot divergence",
                                         "fresh read: FBW erased behind the mirror"),
    "fresh-unhealthy": lambda mk: run_rows(mk, "fresh read: storage unhealthy (INVALID page) -> F-H1, nothing written"),
    "fresh-followup": lambda mk: run_fresh(mk, "fresh read: FBP replaced by another valid record behind the mirror -> same-boot divergence",
                                           "fresh read: FBP erased behind the mirror"),
    "inconsistent-class": S.scn_inconsistent_class_over_invalidated,
    "inflight": lambda mk: S.scn_inflight_injected(mk, "op_in_progress") + S.scn_inflight_injected(mk, "dispatch"),
    "inflight-save": S.scn_inflight_save,
    "inflight-review": S.scn_inflight_review,
    "bus-race-mutex": lambda mk: S.scn_bus_race(mk, "manual_write_in_progress"),
    "bus-race-correction": lambda mk: S.scn_bus_race(mk, "correction_in_progress"),
    "bus-race-tx-blocked": lambda mk: S.scn_bus_race(mk, "tx_blocked"),
    "bus-race-tx-nonempty": lambda mk: S.scn_bus_race(mk, "tx_nonempty"),
    "bus-race-op": lambda mk: S.scn_bus_race(mk, "fallback_profile_op_in_progress"),
    "bus-retry": lambda mk: S.scn_busy_then_retry(mk, "manual_write_in_progress"),
    "writer-refusal-handle": lambda mk: S.scn_writer_refusal(mk, "handle"),
    "writer-refusal-unhealthy": lambda mk: S.scn_writer_refusal(mk, "unhealthy"),
    "unknown-F2": lambda mk: run_fault(mk, "F2 FBW NO_MEM (raw), landed nowhere"),
    "unknown-F5": lambda mk: run_fault(mk, "F5 FBP raw error, readback == intended"),
    "unknown-F8": lambda mk: run_fault(mk, "F8 FBP OK, readback read error"),
    "unknown-FH2": lambda mk: run_fault(mk, "F-H2 an INVALID page appears after the FBW write"),
    "unknown-FH2b": lambda mk: run_fault(mk, "F-H2b an INVALID page appears after the FBP write"),
    "unknown-residual": S.scn_unknown_residual_valid_reboot,
    "not-committed-F1": lambda mk: run_fault(mk, "F1 FBW pre-write code, readback == prior"),
    "not-committed-F4": lambda mk: run_fault(mk, "F4 FBW committed, FBP pre-write code"),
    "missing-witness-F1": lambda mk: run_fault(mk, "F1 FBW pre-write code, readback == prior", seed=MISSING_SEED, aftermath=False),
    "cut-sweep": lambda mk: S.scn_cut_sweep(mk, "valid")[0],
    "sequence": S.scn_seq_inv_save_inv,
    "tokens": S.scn_wrong_tokens,
    "router-save": lambda mk: S.scn_router_save(mk),
    "writer-usable": S.scn_writer_usable,
    "boundary": S.scn_boundary_generation,
    "seen-boundary": S.scn_seen_floor_boundary,
    "candidate-expiry": S.scn_arm_survives_candidate_expiry,
    "idle-stability": lambda mk: S.scn_idle_stability(mk, "unknown"),
    "save-unknown": S.scn_save_unknown_blocks_invalidate,
    "tail": S.scn_tail_garbage,
    "refuse-pload": lambda mk: run_rows(mk, "class forced VALID over an absent profile: the id 0000000000000000 never matches an ABSENT record"),
    "bus-race-dispatch": lambda mk: S.scn_bus_race(mk, "dispatch_running"),
    "candidate-notsaveable": lambda mk: run_rows_cand(mk, "read anomaly: boot read of FBP failed (unreadable seed)"),
    "candidate-any-gate": lambda mk: run_rows_cand(mk, "id format: lowercase hex", "phrase: lowercase", "class INVALIDATED (repeat)",
                                                   "bus busy: correction_in_progress", "SAVE_UNCONFIRMED injected"),
}
# one detector per plan-stage injection, per bus flag of the gate (rows) and per bus flag of the last check (races)
for _k in S.PLAN_KINDS:
    DETECTORS[f"plan-{_k}"] = (lambda mk, k=_k: S.scn_plan_stage(mk, k))
GATE_FLAGS = ("manual_write_in_progress", "correction_in_progress", "verification_pending", "verification_read_active",
              "free_power_operation_in_progress", "free_power_recovery_force_in_progress", "free_power_recovery_accept_in_progress",
              "reg244_apply_in_progress", "dump_operation_in_progress")
for _f in GATE_FLAGS:
    DETECTORS[f"gate-{_f}"] = (lambda mk, f=_f: run_rows(mk, f"bus busy: {f}"))
for _f in S.RACES:
    DETECTORS[f"race-{_f}"] = (lambda mk, f=_f: S.scn_bus_race(mk, f))
FINAL_FLAGS = GATE_FLAGS + ("fallback_profile_op_in_progress",)


# --------------------------------------------------------------------------- the mutants
@dataclass
class Mutant:
    mid: str
    desc: str
    kind: str                    # yaml | mirror | writer
    detectors: tuple
    text: str | None = None      # yaml: the mutated firmware text
    mirror_text: str | None = None
    patch: object = None         # writer: contextmanager factory
    static: bool = False         # also killed by the static pin if it reports anything


def y(mid, desc, edits, detectors, static=False, global_edits=()):
    """A YAML mutant: `edits` = [(old, new)] applied inside the INVALIDATE script (each exactly once), `global_edits` = [(old, new)]
    applied to the whole firmware text (each exactly once)."""
    t = LIVE_TEXT
    for old, new in edits:
        t = edit_inv(t, old, new)
    for old, new in global_edits:
        t = D.mutate(t, old, new)
    return Mutant(mid, desc, "yaml", tuple(detectors), text=t, static=static)


def m(mid, desc, edits, detectors):
    """A mirror mutant: `edits` = [(old, new, count)] on registry/fallback_save.py."""
    t = LIVE_MIRROR
    for old, new, cnt in edits:
        t = K.mutate_mirror(t, old, new, cnt)
    return Mutant(mid, desc, "mirror", tuple(detectors), mirror_text=t)


COMMIT = "          const ecco_fbdurable::TxnOutcome o = ecco_fbdurable::commit_transition_t(\n"
LAST_ERR = "          id(fallback_durable_last_err) = ecco_fbsave::first_non_ok(r.w.err, r.p.err);\n"
ARM_PRE = "          const bool armed = id(fallback_profile_arm).state;\n          id(fallback_profile_arm).turn_off();\n"
INFLIGHT_ARM = ("              id(fallback_profile_arm).turn_off();\n"
                "              if (id(fallback_profile_last_result_text).state != i1.text.c_str()) id(fallback_profile_last_result_text).publish_state(i1.text.c_str());\n")
IE2 = ("          if (id(fallback_profile_cand_valid)) {\n"
       "            id(fallback_profile_invalidate_reason) = ecco_fbcap::REASON_SUPERSEDED;\n"
       "            id(fallback_profile_invalidate_candidate).execute();\n"
       "          }\n")
SEEN_STMT = ("          id(fallback_profile_seen_hw_gen) = ecco_fbdurable::next_seen_hw_gen(\n"
             "              id(fallback_profile_seen_hw_gen), ecco_fallback::classify_profile(m.p_load, m.p), m.p.generation,\n"
             "              ecco_fbdurable::classify_witness(m.w_load, m.w), m.w.hw_generation);\n")
COMMIT_STMT_END = "              ecco_fbdurable::PriorDesc{lp, dp.stored_len}, r);\n"
TAIL_LOG = ("              ESP_LOGW(\"fbdurable\", \"%s\", lg.c_str());\n"
            "            }\n"
            "          }\n")
ROUTER = ("return ecco_fbsave::is_invalidate_action(id(fallback_profile_exec_action).c_str(), "
          "id(fallback_profile_exec_action).size());")
MUTEX_TAKE = "          id(manual_write_in_progress) = true;\n"
MUTEX_FREE = "          id(manual_write_in_progress) = false;\n"
OP_TAKE = "          id(fallback_profile_op_in_progress) = true;\n"
OP_FREE = "          id(fallback_profile_op_in_progress) = false;\n"


def yaml_mutants() -> list:
    out = []
    A = out.append
    # --- synchronous, no mutex, no wait (D1 / D2, MB33)
    A(y("Y01", "INVALIDATE takes manual_write_in_progress around the commit", [(COMMIT, MUTEX_TAKE + COMMIT), (LAST_ERR, MUTEX_FREE + LAST_ERR)],
        ["clean"], static=True))
    A(y("Y02", "INVALIDATE takes op_in_progress around the commit", [(COMMIT, OP_TAKE + COMMIT), (LAST_ERR, OP_FREE + LAST_ERR)],
        ["clean"], static=True))
    A(y("Y03", "INVALIDATE waits (a 50 ms delay action after the lambda)", [(TAIL_LOG, TAIL_LOG + "      - delay: 50ms\n")],
        ["clean", "clean-deferred-bus"], static=True))
    A(y("Y04", "INVALIDATE waits for the bus (wait_until manual_write_in_progress clears, 3 s) before the gate",
        [("    mode: single\n    then:\n      - lambda: |-\n          // I1:",
          "    mode: single\n    then:\n      - wait_until:\n          condition:\n            lambda: 'return !id(manual_write_in_progress);'\n"
          "          timeout: 3s\n      - lambda: |-\n          // I1:")],
        ["refuse-bus"], static=True))
    A(y("Y05", "INVALIDATE starts another script (script.execute after the lambda)",
        [(TAIL_LOG, TAIL_LOG + "      - script.execute:\n          id: fallback_profile_invalidate_candidate\n")], ["clean"], static=True))
    # --- gate
    A(y("Y06", "the arm check is skipped (arm_was_on = true)", [("            ii.arm_was_on = armed;\n", "            ii.arm_was_on = true;\n")],
        ["refuse-arm"]))
    A(y("Y07", "no one-shot arm turn_off in the preamble", [(ARM_PRE, "          const bool armed = id(fallback_profile_arm).state;\n")],
        ["clean", "arm-one-shot"], static=True))
    A(y("Y08", "the in-flight branch does not turn the arm off", [(INFLIGHT_ARM, INFLIGHT_ARM.split("\n", 1)[1])],
        ["inflight"], static=True))
    A(y("Y09", "the in-flight pre-check never fires (false, false): the candidate is consumed by an in-flight call",
        [("                id(fallback_profile_op_in_progress), id(fallback_profile_capture_dispatch).is_running());\n            if (i1.code",
          "                false, false);\n            if (i1.code")], ["inflight"]))
    A(y("Y10", "the pending candidate is not consumed (IE2 removed)", [(IE2, "")], ["clean-candidate", "refuse-candidate"]))
    A(y("Y11", "the candidate consumption publishes its own B9 line (a non-superseded reason)",
        [("ecco_fbcap::REASON_SUPERSEDED", '"REVIEW CLEARED - operator action"')], ["clean-candidate"]))
    A(y("Y12", "the whole gate is bypassed (if (false))", [("            if (ir.code != ecco_fbsave::IG_ACCEPT) {\n", "            if (false) {\n")],
        ["refuse-arm", "refuse-id"]))
    A(y("Y13", "boot_loaded forced true at the gate", [("            ii.boot_loaded = id(fallback_profile_boot_loaded);\n", "            ii.boot_loaded = true;\n")],
        ["refuse-not-loaded"]))
    A(y("Y14", "read_anomaly forced 0 at the gate (the gate no longer refuses cheaply)",
        [("            ii.read_anomaly = id(fallback_profile_read_anomaly);\n", "            ii.read_anomaly = 0;\n")], ["refuse-anomaly"]))
    A(y("Y15", "the SAVE_UNCONFIRMED overlay is ignored at the gate",
        [("            ii.unconfirmed = id(fallback_profile_save_unconfirmed);\n", "            ii.unconfirmed = false;\n")],
        ["refuse-unconfirmed"]))
    A(y("Y16", "any class is accepted (gate and plan see VALID)",
        [("            ii.cls = id(fallback_profile_class);\n", "            ii.cls = ecco_fbdurable::EPC_VALID;\n"),
         ("            pj.cls = e.cls;\n", "            pj.cls = ecco_fbdurable::EPC_VALID;\n")], ["refuse-class"]))
    A(y("Y17", "the FBS slot is ignored (always clear)",
        [("            ii.fbs_slot = id(fallback_profile_fbs_slot);\n", "            ii.fbs_slot = ecco_fbdurable::FBS_CLEAR_ABSENT;\n")],
        ["refuse-fbs"]))
    A(y("Y18", "the gate ignores manual_write_in_progress",
        [("            ii.bus.manual_write_in_progress = id(manual_write_in_progress);\n", "            ii.bus.manual_write_in_progress = false;\n")],
        ["refuse-bus"]))
    A(y("Y19", "the gate ignores tx_blocked", [("            ii.tx_blocked = id(inverter_modbus)->tx_blocked();\n", "            ii.tx_blocked = false;\n")],
        ["refuse-bus"]))
    A(y("Y20", "the gate ignores tx_buffer_empty",
        [("            ii.tx_buffer_empty = id(inverter_modbus)->tx_buffer_empty();\n", "            ii.tx_buffer_empty = true;\n")], ["refuse-bus"]))
    A(y("Y21", "the gate ignores seen_hw_gen",
        [("            ii.seen_hw_gen = id(fallback_profile_seen_hw_gen);\n", "            ii.seen_hw_gen = 0;\n")], ["refuse-seen"]))
    # --- added requirements INVALIDATE must NOT have (supervision / NTP / arms / obligations)
    A(y("Y22", "INVALIDATE requires the Home Assistant heartbeat", [("            ii.arm_was_on = armed;\n",
                                                                    "            ii.arm_was_on = armed && id(fallback_profile_exec_hb_ok);\n")],
        ["clean-bare"]))
    A(y("Y23", "INVALIDATE requires NTP time", [("            ii.arm_was_on = armed;\n", "            ii.arm_was_on = armed && id(ntp_synced);\n")],
        ["clean-bare"]))
    A(y("Y24", "INVALIDATE requires the write arms off",
        [("            ii.arm_was_on = armed;\n", "            ii.arm_was_on = armed && !id(free_power_write_enable).state && !id(dump_write_enable).state "
                                                  "&& !id(manual_config_write_enable).state;\n")], ["clean-write-arms"]))
    A(y("Y25", "INVALIDATE requires clear lease obligations",
        [("            ii.arm_was_on = armed;\n", "            ii.arm_was_on = armed && !id(free_power_snapshot_valid) && !id(dump_snapshot_valid);\n")],
        ["clean-lease"]))
    # --- fresh read, plan, final bus check
    A(y("Y26", "the plan result is ignored (if (false))", [("          if (plan.code != ecco_fbsave::PLAN_OK) {\n", "          if (false) {\n")],
        ["fresh-class"]))
    A(y("Y27", "nvs_healthy() is not consulted (healthy = true)",
        [("          const bool healthy = ecco_fbdurable::nvs_healthy();\n", "          const bool healthy = true;\n")], ["fresh-unhealthy"]))
    A(y("Y28", "the last bus check is removed (if (false))",
        [("          if (!ecco_fbsave::invalidate_bus_idle(bn, id(inverter_modbus)->tx_buffer_empty(), id(inverter_modbus)->tx_blocked())) {\n",
          "          if (false) {\n")], ["bus-race-mutex", "bus-race-op"]))
    A(y("Y29", "the last bus check uses a stale mutex flag (false)",
        [("          bn.manual_write_in_progress = id(manual_write_in_progress);\n", "          bn.manual_write_in_progress = false;\n")],
        ["bus-race-mutex"]))
    A(y("Y30", "the last bus check ignores tx_blocked",
        [("id(inverter_modbus)->tx_buffer_empty(), id(inverter_modbus)->tx_blocked())) {\n            ecco_fbcap::TextBuf busy",
          "id(inverter_modbus)->tx_buffer_empty(), false)) {\n            ecco_fbcap::TextBuf busy")], ["bus-race-tx-blocked"]))
    A(y("Y31", "the last bus check ignores tx_buffer_empty",
        [("invalidate_bus_idle(bn, id(inverter_modbus)->tx_buffer_empty(), id(inverter_modbus)->tx_blocked())",
          "invalidate_bus_idle(bn, true, id(inverter_modbus)->tx_blocked())")], ["bus-race-tx-nonempty"]))
    # --- the writer call and what follows it
    A(y("Y32", "the mirror is built from the INTENDED records, not the readbacks",
        [("          const ecco_fbdurable::MirrorRecords m = ecco_fbdurable::mirror_after(o, r, p, lp, w, lw);\n",
          "          ecco_fbdurable::MirrorRecords m{};\n          m.p = plan.p_new;\n          m.w = plan.w_new;\n          m.p_load = lp;\n          m.w_load = lw;\n")],
        ["not-committed-F4", "unknown-F2"]))
    A(y("Y33", "no SAVE_UNCONFIRMED overlay flag on UNKNOWN", [("            id(fallback_profile_save_unconfirmed) = true;\n", "")],
        ["unknown-F2", "save-unknown"]))
    A(y("Y34", "B1 published without the overlay after the commit",
        [("overlay_class(e2.cls, id(fallback_profile_save_unconfirmed)));", "overlay_class(e2.cls, false));")], ["unknown-F5"]))
    A(y("Y35", "a retry: a second commit_transition_t call after an UNKNOWN outcome",
        [(COMMIT, COMMIT.replace("const ecco_fbdurable::TxnOutcome o", "ecco_fbdurable::TxnOutcome o")),
         (COMMIT_STMT_END, COMMIT_STMT_END + "          if (o == ecco_fbdurable::TXN_UNKNOWN_REBOOT) {\n"
                                              "            o = ecco_fbdurable::commit_transition_t(\n"
                                              "                nvs, plan.w_new, w, ecco_fbdurable::PriorDesc{lw, dw.stored_len}, plan.p_new, p,\n"
                                              "                ecco_fbdurable::PriorDesc{lp, dp.stored_len}, r);\n          }\n")],
        ["unknown-F2", "unknown-F5"], static=True))
    A(y("Y36", "the success text is published whatever the verdict (TXN_COMMITTED passed to the text builder)",
        [("ecco_fbsave::txn_outcome_text(plan.op, o, r, plan.generation, p.generation)",
          "ecco_fbsave::txn_outcome_text(plan.op, ecco_fbdurable::TXN_COMMITTED, r, plan.generation, p.generation)")],
        ["not-committed-F1", "not-committed-F4", "unknown-F2"]))
    A(y("Y37", "the prior and new generations are swapped in the success text",
        [("ecco_fbsave::txn_outcome_text(plan.op, o, r, plan.generation, p.generation)",
          "ecco_fbsave::txn_outcome_text(plan.op, o, r, p.generation, plan.generation)")], ["clean"]))
    A(y("Y38", "B2 werr takes only the profile key's error",
        [(LAST_ERR, "          id(fallback_durable_last_err) = ecco_fbsave::first_non_ok(r.p.err, r.p.err);\n")], ["not-committed-F1"]))
    A(y("Y39", "B2 us takes only the witness time",
        [("          id(fallback_durable_last_us) = ecco_fbsave::total_us(r.w.us, r.p.us);\n",
          "          id(fallback_durable_last_us) = ecco_fbsave::total_us(r.w.us, 0);\n")], ["clean"]))
    A(y("Y40", "seen_hw_gen is not raised by the commit", [(SEEN_STMT, "")], ["clean"]))
    A(y("Y41", "the witness key is not noted as committed (present_seen)",
        [("            if (r.w.outcome == ecco_fbdurable::KEY_COMMITTED) lat = ecco_fbdurable::note_committed(lat, ecco_fbdurable::KEY_BIT_WITNESS);\n", "")],
        ["clean-missing-witness"]))
    A(y("Y42", "the class global is not recomputed after the commit",
        [("          id(fallback_profile_class) = e2.cls;\n", "          id(fallback_profile_class) = ecco_fbdurable::EPC_VALID;\n")], ["clean"]))
    A(y("Y43", "B1 is not republished after the commit",
        [("overlay_class(e2.cls, id(fallback_profile_save_unconfirmed)));\n            if (id(fallback_profile_state_text).state != cls_name) "
          "id(fallback_profile_state_text).publish_state(cls_name);",
          "overlay_class(e2.cls, id(fallback_profile_save_unconfirmed)));\n            if (false) id(fallback_profile_state_text).publish_state(cls_name);")],
        ["clean"]))
    A(y("Y44", "B7 shows the prior profile after the commit",
        [("ecco_fbcap::b7_text(m.p_load, m.p, e2.cls)", "ecco_fbcap::b7_text(lp, p, e2.cls)")], ["clean"]))
    A(y("Y45", "B8 shows the prior profile after the commit",
        [("ecco_fbcap::b8_text(m.p_load, m.p, e2.cls)", "ecco_fbcap::b8_text(lp, p, e2.cls)")], ["clean"]))
    A(y("Y46", "the writer is told the witness prior load is the profile's load",
        [("nvs, plan.w_new, w, ecco_fbdurable::PriorDesc{lw, dw.stored_len}, plan.p_new, p,",
          "nvs, plan.w_new, w, ecco_fbdurable::PriorDesc{lp, dw.stored_len}, plan.p_new, p,")], ["missing-witness-F1"]))
    A(y("Y47", "the writer is told the profile prior load is the witness's load",
        [("ecco_fbdurable::PriorDesc{lp, dp.stored_len}, r);\n          // Everything below", "ecco_fbdurable::PriorDesc{lw, dp.stored_len}, r);\n          // Everything below")],
        ["missing-witness-F1", "clean-missing-witness", "unknown-F5"]))
    A(y("Y53", "the lambda calls invalidate_profile directly, unguarded (BLK-51)",
        [("plan.p_new, p,\n              ecco_fbdurable::PriorDesc{lp, dp.stored_len}, r);",
          "ecco_fallback::invalidate_profile(p), p,\n              ecco_fbdurable::PriorDesc{lp, dp.stored_len}, r);")],
        ["clean"], static=True))
    # --- the api action router (global text)
    A(y("Y49", "the router never routes INVALIDATE (return false)", [], ["clean"], global_edits=[(ROUTER, "return false;")]))
    A(y("Y50", "the router routes every token to INVALIDATE (return true)", [], ["router-save", "tokens"], global_edits=[(ROUTER, "return true;")]))
    A(y("Y51", "the api action copies the id from the wrong variable", [], ["refuse-id", "clean"],
        global_edits=[("id(fallback_profile_exec_target_id) = target_id.str();", "id(fallback_profile_exec_target_id) = action.str();")]))
    A(y("Y52", "the api action copies the phrase from the id variable", [], ["clean"],
        global_edits=[("id(fallback_profile_exec_confirmation) = confirmation.str();", "id(fallback_profile_exec_confirmation) = target_id.str();")]))
    # --- the plan layer (over the FRESH read) on its own: only visible when the change happens between the gate and the plan
    A(y("Y54", "the plan's binding check is vacuous (target id := the fresh profile's binding)",
        [("          pj.target_id = ecco_fbsave::parse_hex16(id(fallback_profile_exec_target_id).c_str(), id(fallback_profile_exec_target_id).size());\n",
          "          pj.target_id = p.binding;\n")], ["plan-binding_changed"]))
    A(y("Y55", "the plan ignores seen_hw_gen (0)", [("            pj.seen_hw_gen = e.seen_hw_gen;\n", "            pj.seen_hw_gen = 0;\n")],
        ["plan-seen_raised"]))
    A(y("Y56", "the plan ignores the SAVE_UNCONFIRMED overlay (false)",
        [("          pj.unconfirmed = id(fallback_profile_save_unconfirmed);\n", "          pj.unconfirmed = false;\n")], ["plan-unconfirmed_raised"]))
    A(y("Y57", "the plan ignores the read anomaly (0)", [("            pj.read_anomaly = e.latch.read_anomaly;\n", "            pj.read_anomaly = 0;\n")],
        ["fresh-anomaly"]))
    A(y("Y58", "the plan sees class VALID whatever the fresh read composed",
        [("            pj.cls = e.cls;\n", "            pj.cls = ecco_fbdurable::EPC_VALID;\n")], ["fresh-class"]))
    # --- what the call leaves behind
    A(y("Y59", "the unconfirmed op is recorded as SAVE",
        [("            id(fallback_profile_save_unconfirmed_op) = plan.op;\n",
          "            id(fallback_profile_save_unconfirmed_op) = ecco_fbdurable::PROV_OP_SAVE;\n")], ["unknown-F2"]))
    A(y("Y60", "the unconfirmed generation is the prior generation",
        [("            id(fallback_profile_save_unconfirmed_gen) = plan.generation;\n",
          "            id(fallback_profile_save_unconfirmed_gen) = p.generation;\n")], ["unknown-F2"]))
    A(y("Y61", "the stale reason is not recomputed after the commit (why := 0)",
        [("          id(fallback_profile_why) = e2.why;\n", "          id(fallback_profile_why) = 0;\n")], ["not-committed-F4"]))
    A(y("Y62", "the witness load of the mirror is not updated after the commit",
        [("          id(fallback_witness_load) = m.w_load;\n", "")], ["clean-missing-witness"]))
    A(y("Y63", "the witness mirror keeps the PRIOR witness bytes after the commit",
        [("          id(fallback_witness_bytes) = ecco_fbdurable::encode_provision(m.w);\n",
          "          id(fallback_witness_bytes) = ecco_fbdurable::encode_provision(w);\n")], ["clean"]))
    A(y("Y64", "the profile mirror keeps the PRIOR profile bytes after the commit",
        [("          id(fallback_profile_bytes) = ecco_fallback::encode_profile(m.p);\n",
          "          id(fallback_profile_bytes) = ecco_fallback::encode_profile(p);\n")], ["clean"]))
    A(y("Y65", "the overlay is set on every non-COMMITTED outcome (not only UNKNOWN)",
        [("          if (o == ecco_fbdurable::TXN_UNKNOWN_REBOOT) {\n", "          if (o != ecco_fbdurable::TXN_COMMITTED) {\n")],
        ["not-committed-F1"], static=True))
    A(y("Y66", "the in-flight pre-check ignores the dispatch script",
        [("                id(fallback_profile_op_in_progress), id(fallback_profile_capture_dispatch).is_running());\n            if (i1.code",
          "                id(fallback_profile_op_in_progress), false);\n            if (i1.code")], ["inflight"]))
    A(y("Y67", "the in-flight pre-check ignores op_in_progress",
        [("                id(fallback_profile_op_in_progress), id(fallback_profile_capture_dispatch).is_running());\n            if (i1.code",
          "                false, id(fallback_profile_capture_dispatch).is_running());\n            if (i1.code")], ["inflight"]))
    A(y("Y68", "the one-shot preamble turns the arm off BEFORE reading it",
        [(ARM_PRE, "          id(fallback_profile_arm).turn_off();\n          const bool armed = id(fallback_profile_arm).state;\n")],
        ["clean"], static=True))
    A(y("Y70", "only a SAVEABLE candidate is consumed (a not-saveable preview survives a refused INVALIDATE)",
        [("          if (id(fallback_profile_cand_valid)) {\n", "          if (id(fallback_profile_cand_valid) && id(fallback_profile_cand_saveable)) {\n")],
        ["candidate-notsaveable"]))
    A(y("Y71", "the candidate is consumed only when the arm was on (a refused call with the arm off leaves it)",
        [("          if (id(fallback_profile_cand_valid)) {\n", "          if (id(fallback_profile_cand_valid) && armed) {\n")],
        ["candidate-any-gate", "refuse-candidate"]))
    A(y("Y69", "the gate believes the profile loaded fine (p_load := LOAD_OK)",
        [("            ii.p_load = id(fallback_profile_load);\n", "            ii.p_load = ecco_fallback::LOAD_OK;\n")], ["refuse-pload"]))
    # --- every bus flag is wired into BOTH bus checks: the gate (over the RAM flags) and the last statement before the writer
    for i, flag in enumerate(GATE_FLAGS[1:], start=1):
        A(y(f"YG{i:02d}", f"the gate ignores {flag}",
            [(f"            ii.bus.{flag} = id({flag});\n", f"            ii.bus.{flag} = false;\n")], [f"gate-{flag}"]))
    for i, flag in enumerate(FINAL_FLAGS[1:], start=1):
        A(y(f"YB{i:02d}", f"the last bus check (just before the writer) ignores {flag}",
            [(f"          bn.{flag} = id({flag});\n", f"          bn.{flag} = false;\n")], [f"race-{flag}"]))
    A(y(f"YB{len(FINAL_FLAGS):02d}", "the last bus check ignores the dispatch script",
        [("          bn.fallback_profile_capture_dispatch_running = id(fallback_profile_capture_dispatch).is_running();\n",
          "          bn.fallback_profile_capture_dispatch_running = false;\n")], ["bus-race-dispatch"]))
    return out


def mirror_mutants() -> list:
    out = []
    A = out.append
    A(m("H01", "I8 class check skipped in the gate", [("    if not fd.invalidate_class_permitted(inp.cls):  # I8", "    if False:  # I8", 1)], ["refuse-class"]))
    A(m("H02", "INVALIDATED accepted as invalidatable (gate + plan)",
        [("    if not fd.invalidate_class_permitted(inp.cls):  # I8", "    if inp.cls not in (fd.EPC_VALID, fd.EPC_INVALIDATED):  # I8", 1),
         ("    if not fd.invalidate_class_permitted(cls):", "    if cls not in (fd.EPC_VALID, fd.EPC_INVALIDATED):", 1)], ["refuse-class", "arm-one-shot"]))
    A(m("H03", "PROFILE_STALE accepted as invalidatable (gate + plan)",
        [("    if not fd.invalidate_class_permitted(inp.cls):  # I8", "    if inp.cls not in (fd.EPC_VALID, fd.EPC_PROFILE_STALE):  # I8", 1),
         ("    if not fd.invalidate_class_permitted(cls):", "    if cls not in (fd.EPC_VALID, fd.EPC_PROFILE_STALE):", 1)], ["refuse-class"]))
    A(m("H04", "invalidate_generation_permitted skipped (gate + plan)",
        [("fd.invalidate_generation_permitted(", "_always_true(", 2), ("\n\ndef invalidate_in_flight_gate(", "\n\ndef _always_true(*a):\n    return True\n\n\ndef invalidate_in_flight_gate(", 1)],
        ["refuse-seen", "refuse-exhausted"]))
    A(m("H05", "profile_invalidate_permitted AND the generation guard skipped: invalidate_profile unguarded at g = 0xFFFFFFFF",
        [("fp.profile_invalidate_permitted(p)", "True", 2), ("fd.invalidate_generation_permitted(", "_always_true(", 2),
         ("\n\ndef invalidate_in_flight_gate(", "\n\ndef _always_true(*a):\n    return True\n\n\ndef invalidate_in_flight_gate(", 1)], ["refuse-exhausted"]))
    A(m("H25", "profile_invalidate_permitted skipped (gate + plan)", [("fp.profile_invalidate_permitted(p)", "True", 2)], ["inconsistent-class"]))
    A(m("H06", "the id compare is short (first 8 hex digits)",
        [('p["binding"] != id_:  # I9', '(p["binding"] >> 32) != (id_ >> 32):  # I9', 1),
         ('p["binding"] != (inp.target_id & U64)', '(p["binding"] >> 32) != ((inp.target_id & U64) >> 32)', 1)], ["refuse-id"]))
    A(m("H07", "I11 bus check skipped in the gate", [("    if not invalidate_bus_idle(inp.bus, inp.tx_buffer_empty, inp.tx_blocked):  # I11", "    if False:  # I11", 1)],
        ["refuse-bus"]))
    A(m("H08", "invalidate_bus_idle ignores tx_blocked", [("(not cap.bus_busy(b)) and tx_buffer_empty and not tx_blocked)", "(not cap.bus_busy(b)) and tx_buffer_empty)", 1)], ["refuse-bus", "bus-race-tx-blocked"]))
    A(m("H09", "invalidate_bus_idle looks only at manual_write_in_progress",
        [("(not cap.bus_busy(b)) and tx_buffer_empty", "(not b.manual_write_in_progress) and tx_buffer_empty", 1)], ["refuse-bus-all", "bus-race-correction"]))
    A(m("H10", "I2 arm check skipped", [("    if not inp.arm_was_on:  # I2", "    if False:  # I2", 1)], ["refuse-arm"]))
    A(m("H11", "the witness prior fields are swapped",
        [('fd.make_provision(pn["generation"], pn["binding"], p["generation"], p["binding"], fd.FALLBACK_PROFILE_KEY,\n                           fp.PROFILE_SCHEMA, fd.PROV_OP_INVALIDATE)',
          'fd.make_provision(pn["generation"], pn["binding"], p["binding"] & 0xFFFFFFFF, p["generation"], fd.FALLBACK_PROFILE_KEY,\n                           fp.PROFILE_SCHEMA, fd.PROV_OP_INVALIDATE)', 1)],
        ["clean"]))
    A(m("H12", "the witness op is SAVE instead of INVALIDATE",
        [("fp.PROFILE_SCHEMA, fd.PROV_OP_INVALIDATE)\n    if not invalidate_pair_valid", "fp.PROFILE_SCHEMA, fd.PROV_OP_SAVE)\n    if not invalidate_pair_valid", 1)], ["clean"]))
    A(m("H13", "captured_epoch changed by the INVALIDATE",
        [("    pn = fd.invalidate_profile_cxx(p)\n", '    pn = fp.seal_profile({**fd.invalidate_profile_cxx(p), "captured_epoch": 1})\n', 1)], ["clean"]))
    A(m("H14", "a payload register altered by the INVALIDATE",
        [("    pn = fd.invalidate_profile_cxx(p)\n", '    pn = fp.seal_profile({**fd.invalidate_profile_cxx(p), "reg245": p["reg245"] ^ 1})\n', 1)], ["clean"]))
    A(m("H15", "the invalidated record is not re-sealed",
        [("    pn = fd.invalidate_profile_cxx(p)\n", '    pn = {**fd.invalidate_profile_cxx(p), "binding": p["binding"]}\n', 1)], ["clean"]))
    A(m("H16", "the generation advances by two", [("    pn = fd.invalidate_profile_cxx(p)\n", '    pn = fp.seal_profile({**fd.invalidate_profile_cxx(p), "generation": p["generation"] + 2})\n', 1)],
        ["clean"]))
    A(m("H17", "overlay_class never overlays", [("    return fd.EPC_SAVE_UNCONFIRMED if unconfirmed else cls", "    return cls", 1)], ["unknown-F2", "unknown-F5"]))
    A(m("H18", "a witness-advanced INVALIDATE is reported with the plain not-committed text",
        [("return invalidate_witness_advanced_text(prior_generation) if inv else save_witness_advanced_text()",
          "return invalidate_not_committed_text(r.w.err, prior_generation) if inv else save_witness_advanced_text()", 1)], ["not-committed-F4"]))
    A(m("H19", "the UNKNOWN text always describes the witness key", [("    k = r.w if r.w.outcome == fd.KEY_UNKNOWN_REBOOT else r.p", "    k = r.w", 1)],
        ["unknown-F5"]))
    A(m("H20", "the INVALIDATE phrase check is case-insensitive",
        [("    if not phrase_equals(confirmation, confirmation_len, expected):  # I4", "    if not phrase_equals(_upper(confirmation), confirmation_len, expected):  # I4", 1),
         ("\n\ndef invalidate_in_flight_gate(", "\n\ndef _upper(c):\n    return c.upper() if isinstance(c, (str, bytes)) else c\n\n\ndef invalidate_in_flight_gate(", 1)],
        ["refuse-phrase"]))
    A(m("H21", "lowercase hex accepted as a 16-hex id", [("    return 48 <= c <= 57 or 65 <= c <= 70", "    return 48 <= c <= 57 or 65 <= c <= 70 or 97 <= c <= 102", 1)],
        ["refuse-id"]))
    A(m("H22", "the INVALIDATED success text names the new generation twice", [('f"g{generation & U32}); payload kept for reference; save a new profile to re-enable")',
                                                                               'f"g{prior_generation & U32}); payload kept for reference; save a new profile to re-enable")', 1)], ["clean"]))
    A(m("H23", "plan_invalidate ignores the fresh-read class", [("    if not fd.invalidate_class_permitted(cls):\n        return plan_refuse(r, PLAN_CLASS, invalidate_class_now_text(cls))",
                                                                  "    if False:\n        return plan_refuse(r, PLAN_CLASS, invalidate_class_now_text(cls))", 1)], ["fresh-class"]))
    A(m("H24", "plan_invalidate ignores the read anomaly", [("    if inp.read_anomaly != 0:\n        return plan_refuse(r, PLAN_ANOMALY, invalidate_anomaly_text())",
                                                              "    if False:\n        return plan_refuse(r, PLAN_ANOMALY, invalidate_anomaly_text())", 1)], ["fresh-anomaly"]))
    # --- each layer on its own: the plan over the FRESH read (visible only through an injection between the gate and the plan) ...
    A(m("H26", "plan_invalidate skips the binding check (the typed id is not compared with the FRESH profile)",
        [('    if inp.p_load != fp.LOAD_OK or p["binding"] != (inp.target_id & U64):\n        return plan_refuse(r, PLAN_BINDING_CHANGED',
          '    if False:\n        return plan_refuse(r, PLAN_BINDING_CHANGED', 1)], ["plan-binding_changed"]))
    A(m("H27", "plan_invalidate ignores the SAVE_UNCONFIRMED overlay",
        [("    if inp.unconfirmed:\n        return plan_refuse(r, PLAN_UNCONFIRMED, invalidate_prior_unknown_text())",
          "    if False:\n        return plan_refuse(r, PLAN_UNCONFIRMED, invalidate_prior_unknown_text())", 1)], ["plan-unconfirmed_raised"]))
    A(m("H28", "plan_invalidate skips the generation guard (profile_invalidate_permitted + invalidate_generation_permitted)",
        [("    if not fp.profile_invalidate_permitted(p) or not fd.invalidate_generation_permitted(\n"
          "            p[\"generation\"], wc, w[\"hw_generation\"], inp.seen_hw_gen):\n        return plan_refuse(r, PLAN_GENERATION",
          "    if False:\n        return plan_refuse(r, PLAN_GENERATION", 1)], ["plan-seen_raised"]))
    # ... and the gate over the RAM mirror (a refusal there must cost no storage access: the plan alone would refuse later with the same text)
    A(m("H29", "the gate skips the generation guard I10 (the plan would still refuse, after a storage read)",
        [("    if not fp.profile_invalidate_permitted(p) or not fd.invalidate_generation_permitted(\n"
          "            p[\"generation\"], wc, w[\"hw_generation\"], inp.seen_hw_gen):  # I10",
          "    if False:  # I10", 1)], ["refuse-seen", "refuse-exhausted"]))
    A(m("H30", "the gate skips I7 (SAVE_UNCONFIRMED)", [("    if inp.unconfirmed:  # I7", "    if False:  # I7", 1)], ["refuse-unconfirmed"]))
    A(m("H31", "the gate skips I6 (read anomaly)", [("    if inp.read_anomaly != 0:  # I6", "    if False:  # I6", 1)], ["refuse-anomaly"]))
    A(m("H32", "the gate skips I5 (boot_loaded)", [("    if not inp.boot_loaded:  # I5", "    if False:  # I5", 1)], ["refuse-not-loaded"]))
    A(m("H33", "the gate skips I9 (id vs the mirror's binding; the plan would refuse later with another text)",
        [('    if inp.p_load != fp.LOAD_OK or p["binding"] != id_:  # I9', "    if False:  # I9", 1)], ["refuse-id"]))
    A(m("H34", "the gate skips I3 (id format)", [("    if not is_hex16(target_id, target_len):  # I3", "    if False:  # I3", 1)], ["refuse-id"]))
    A(m("H35", "the gate skips I4 (confirmation phrase)", [("    if not phrase_equals(confirmation, confirmation_len, expected):  # I4", "    if False:  # I4", 1)],
        ["refuse-phrase"]))
    A(m("H36", "the gate skips I12 (FBS slot)", [("    if not fd.fbs_slot_clear(inp.fbs_slot):  # I12", "    if False:  # I12", 1)], ["refuse-fbs"]))
    A(m("H37", "I9 forgets the load status (only the binding is compared: an ABSENT record has binding 0)",
        [('    if inp.p_load != fp.LOAD_OK or p["binding"] != id_:  # I9', '    if p["binding"] != id_:  # I9', 1)], ["refuse-pload"]))
    return out


@contextlib.contextmanager
def writer_fbp_first():
    """MB22: a writer that commits FBP BEFORE FBW (the model's order swapped)."""
    orig = fd.commit_transition

    def swapped(nvs, latch, w_new, w_prior, w_pd, p_new, p_prior, p_pd):
        r = fd.TxnResult()
        r.w.outcome = fd.KEY_NOT_ATTEMPTED
        r.p.outcome = fd.KEY_NOT_ATTEMPTED
        if latch.write_latched:
            r.refusal = fd.REFUSAL_LATCHED
            return fd.TXN_REFUSED_LATCHED, r
        if not fd.validate_transition(w_new, w_prior, w_pd, p_new, p_prior, p_pd):
            r.refusal = fd.REFUSAL_INVALID_TRANSITION
            return fd.TXN_REFUSED_LATCHED, r
        if nvs.handle() == 0:
            r.refusal = fd.REFUSAL_STORAGE_UNAVAILABLE
            return fd.TXN_REFUSED_LATCHED, r
        if not fd.storage_healthy(nvs):
            r.refusal = fd.REFUSAL_STORAGE_UNHEALTHY
            return fd.TXN_REFUSED_LATCHED, r
        r.refusal = fd.REFUSAL_NONE
        op, r.p_rb = fd.write_one(nvs, latch, fd.FALLBACK_PROFILE_KEY, fd._pbytes(p_new), fd._pbytes(p_prior), p_pd[0], p_pd[1], r.p)
        if op != fd.KEY_COMMITTED:
            return fd.TXN_UNKNOWN_REBOOT, r
        ow, r.w_rb = fd.write_one(nvs, latch, fd.FAILBACK_PROVISION_KEY, fd._wbytes(w_new), fd._wbytes(w_prior), w_pd[0], w_pd[1], r.w)
        return (fd.TXN_COMMITTED if ow == fd.KEY_COMMITTED else fd.TXN_UNKNOWN_REBOOT), r
    fd.commit_transition = swapped
    try:
        yield
    finally:
        fd.commit_transition = orig


@contextlib.contextmanager
def writer_no_health_check():
    """MB25: the writer skips its post-write health check (an INVALID page after a write goes unseen)."""
    orig = fd.storage_healthy
    calls = [0]

    def patched(nvs):
        # the model calls storage_healthy once before and once after every write; report healthy after the writes only
        calls[0] += 1
        ok = orig(nvs)
        return True if (calls[0] > 1 and not ok) else ok
    fd.storage_healthy = patched
    try:
        yield
    finally:
        fd.storage_healthy = orig


@contextlib.contextmanager
def writer_prewrite_is_committed():
    """MB23 flavour: a raw (non pre-write) error is treated as NOT_COMMITTED."""
    orig = fd.classify_write_err

    def patched(e):
        return fd.WERR_PRE_WRITE if e != fd.IDF_OK else fd.WERR_OK
    fd.classify_write_err = patched
    try:
        yield
    finally:
        fd.classify_write_err = orig


@contextlib.contextmanager
def writer_readback_not_checked():
    """MB24: ESP_OK is trusted without a readback (COMMITTED whatever reads back)."""
    orig = fd.classify_key_outcome

    def patched(e, r, healthy_after):
        if e == fd.WERR_OK and healthy_after:
            return fd.KEY_COMMITTED
        return orig(e, r, healthy_after)
    fd.classify_key_outcome = patched
    try:
        yield
    finally:
        fd.classify_key_outcome = orig


@contextlib.contextmanager
def writer_fbp_after_refused_w():
    """MB26: witness-first broken - a NOT_COMMITTED witness does not stop the profile write."""
    orig = fd.commit_transition

    def patched(nvs, latch, w_new, w_prior, w_pd, p_new, p_prior, p_pd):
        o, r = orig(nvs, latch, w_new, w_prior, w_pd, p_new, p_prior, p_pd)
        if o == fd.TXN_NOT_COMMITTED and r.p.outcome == fd.KEY_NOT_ATTEMPTED and not latch.write_latched:
            op, r.p_rb = fd.write_one(nvs, latch, fd.FALLBACK_PROFILE_KEY, fd._pbytes(p_new), fd._pbytes(p_prior), p_pd[0], p_pd[1], r.p)
            if op == fd.KEY_COMMITTED:
                r.witness_advanced = False
                return fd.TXN_COMMITTED, r
        return o, r
    fd.commit_transition = patched
    try:
        yield
    finally:
        fd.commit_transition = orig


@contextlib.contextmanager
def writer_no_latch():
    """MB27: an UNKNOWN key outcome does not latch the writer for the boot."""
    orig = fd.write_one

    def patched(nvs, latch, *a):
        return orig(nvs, fd.WriteLatch(False), *a)
    fd.write_one = patched
    try:
        yield
    finally:
        fd.write_one = orig


@contextlib.contextmanager
def writer_witness_advanced_lost():
    """MB28: a witness-advanced NOT_COMMITTED is reported as an ordinary NOT_COMMITTED (the stale-profile consequence is hidden)."""
    orig = fd.commit_transition

    def patched(*a):
        o, r = orig(*a)
        r.witness_advanced = False
        return o, r
    fd.commit_transition = patched
    try:
        yield
    finally:
        fd.commit_transition = orig


def writer_mutants() -> list:
    return [
        Mutant("W01", "MB22: the writer commits FBP before FBW", "writer", ("clean", "cut-sweep"), patch=writer_fbp_first),
        Mutant("W02", "MB25: the writer's post-write health check is skipped", "writer", ("unknown-FH2", "unknown-FH2b"), patch=writer_no_health_check),
        Mutant("W03", "MB23: a raw write error is treated as a pre-write refusal (NOT_COMMITTED)", "writer", ("unknown-F2", "unknown-F5"),
               patch=writer_prewrite_is_committed),
        Mutant("W04", "MB24: ESP_OK is trusted without comparing the readback", "writer", ("unknown-F8",), patch=writer_readback_not_checked),
        Mutant("W05", "MB26: a NOT_COMMITTED witness does not stop the profile write (witness-first broken)", "writer",
               ("not-committed-F1", "cut-sweep"), patch=writer_fbp_after_refused_w),
        Mutant("W06", "MB27: an UNKNOWN key outcome does not latch the writer", "writer", ("unknown-F2", "unknown-F5"), patch=writer_no_latch),
        Mutant("W07", "MB28: the witness-advanced flag is dropped (a half-landed INVALIDATE looks like a plain refusal)", "writer",
               ("not-committed-F4",), patch=writer_witness_advanced_lost),
    ]


def make_factory(mu: Mutant):
    """(mk, context) for a mutant: mk(**kw) builds a Driver on the mutated artifact; the context manager applies a writer patch."""
    if mu.kind == "yaml":
        return (lambda **kw: D.Driver(text=mu.text, **kw)), contextlib.nullcontext()
    if mu.kind == "mirror":
        mod = K.load_mirror_text(mu.mirror_text, f"fallback_save_{mu.mid.lower()}")
        return (lambda **kw: D.Driver(fbsave=mod, **kw)), contextlib.nullcontext()
    return (lambda **kw: D.Driver(**kw)), mu.patch()
