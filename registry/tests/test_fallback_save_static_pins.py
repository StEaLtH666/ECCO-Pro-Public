#!/usr/bin/env python3
"""Offline STATIC pins for FB-B2 - "Save / Replace-Corrupt / Invalidate of the durable Fallback Profile".

FB-B2 adds the first and only durable WRITE path of the Fallback Profile on ESP NVS: an api action
(`fallback_profile_execute`), an arm switch (`fallback_profile_arm`), two scripts (`fallback_profile_save`: one synchronous gate lambda
that starts the existing four-read dispatch; `fallback_profile_invalidate`: ONE synchronous lambda), the SAVE_FINAL pair of lambdas in the
dispatch, 18 RAM-only globals and the header ecco_fallback_save.h. This suite proves, by TEXT and PARSED-YAML analysis of the real
firmware (never by running it), that the write authority is exactly the two `commit_transition_t` call sites and nothing else.

SECTIONS
  [0] inventory   the base (git 65e4be5, accepted only if its sha256 is the chain's pinned fbb1 checkpoint; the chain reverter as the git-less
                  fallback), the firmware context, the helper self-tests (a pin helper that is wrong would make every pin vacuous)
  [S] static pins each a detector `fn(ctx) -> violations` over the live firmware (X1-X4 exclusivity, the INVALIDATE / SAVE_FINAL structure,
                  the one-shot preamble order, the api action / arm switch / supervision / reboot pins, globals / context / release,
                  literals / logging / B9 sources, field-assignment completeness of every input POD, the zero-write structural proof)
  [M] mutation    deliberately broken copies of the firmware text (and of the headers / the Python mirror): every mutant's anchor must occur
                  EXACTLY as many times as declared (a mutant can never be a silent no-op) and EVERY detector named for it must flag it;
                  every detector must be the named killer of at least one mutant

Anchored on the firmware AS FB-B2 LEFT IT: the on-disk text with any LATER chain entry reverted (an identity while fbb2 is the newest entry, or
before the entry exists). The base is the pre-FB-B2 firmware, hash-verified against the FB-T0 chain's fbb1 checkpoint, so every delta is measured,
never typed twice. The suite reads firmware/secrets.yaml NEVER and writes nothing outside a TemporaryDirectory (the write-surface analyzer copy).

NOT proven here: what the lambdas DO at run time (the scenario suites test_fallback_save_gates / _durable / test_fallback_invalidate do),
the C++ semantics of the headers (host-compile suites), the compiled binary and ESPHome's glue (esphome compile), real NVS / flash behaviour,
hardware. A static pin is a necessary condition, never a sufficient one.
"""

from __future__ import annotations

import re
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(ROOT / "tools"))
import _fbb2_static_lib as L  # noqa: E402
import _fbb2_static_pins as P  # noqa: E402

FAILURES: list[str] = []
NCHECKS = [0]
T0 = time.time()


def check(name: str, condition: bool, detail: str = "") -> None:
    NCHECKS[0] += 1
    if condition:
        print(f"  PASS  {name}")
    else:
        FAILURES.append(name)
        print(f"  FAIL  {name}" + (f" - {detail}" if detail else ""))


def _raises(fn, exc=AssertionError) -> bool:
    try:
        fn()
    except exc:
        return True
    return False


# ===========================================================================
# Mutation machinery. A mutant is (id, description, fn(live_text) -> text | (text, {repo path: replacement text}), [detectors]).
# ===========================================================================
def sp_script(sid):
    return lambda t: L.raw_script_span(t, sid)


SP_SAVE, SP_INV, SP_REVIEW, SP_DISP = (sp_script("fallback_profile_save"), sp_script("fallback_profile_invalidate"),
                                       sp_script("fallback_profile_review"), sp_script("fallback_profile_capture_dispatch"))


def sp_p1(t):
    return L.region(t, "          // SAVE final step, part 1 of 2 (FB-B2): VERIFICATION.", "          // SAVE final step, part 2 of 2")


def sp_p2(t):
    return L.region(t, "          // SAVE final step, part 2 of 2 (FB-B2): COMMIT.", "          // The single release point")


def sp_rel(t):
    return L.region(t, "          // The single release point", "\n  # Candidate reset (RAM only).")


def sp_rf(t):
    return L.region(t, "          // REVIEW final step: integrity check first", "          // SAVE final step, part 1 of 2")


def sp_tick(t):
    return L.region(t, "          const uint32_t now = millis();\n          // 1. Leak breaker", "  # Failback Shadow (FB-C1)")


def sp_boot(t):
    return L.region(t, "          ecco_fallback::FailbackStateV1 s{};\n", "\nesp32:\n")


def sp_api(t):
    a = t.index("    - action: fallback_profile_execute\n")
    return a, t.index("\nota:\n", a)


def sp_glob(t):
    return L.region(t, "  # Fallback Profile SAVE / INVALIDATE (FB-B2) - RAM-only state of the", "\nnumber:\n")


def sp_sw(t):
    return L.region(t, "  # Fallback Profile arm (FB-B2):", "\nselect:\n")


def sp_all(t):
    return 0, len(t)


def sub(sp, old, new, count=1):
    return lambda t: L.mutate_in(t, sp(t), old, new, count)


def ins_before(sp, anchor, stmt, ind=10):
    return lambda t: L.mutate_in(t, sp(t), anchor, stmt + "\n" + " " * ind + anchor)


def ins_after(sp, anchor, stmt, ind=10):
    return lambda t: L.mutate_in(t, sp(t), anchor, anchor + "\n" + " " * ind + stmt)


def glob_(old, new, count=1):
    return lambda t: L.mutate(t, old, new, count)


def append_to_script(sid, action_text):
    def fn(t):
        a, b = L.raw_script_span(t, sid)
        seg = t[a:b].rstrip("\n")
        return t[:a] + seg + "\n" + action_text.rstrip("\n") + "\n\n" + t[b:]
    return fn


def read_rel(rel):
    return (ROOT / rel).read_text(encoding="utf-8")


def hdr(rel, old, new, count=1):
    """A header / mirror text mutant: the YAML stays as it is, the file `rel` is replaced by its mutated copy."""
    return lambda t: (t, {rel: L.mutate(read_rel(rel), old, new, count)})


SAVE_H = "firmware/include/ecco_fallback_save.h"
CAP_H = "firmware/include/ecco_fallback_capture.h"
DUR_H = "firmware/include/ecco_fallback_durable.h"
MODEL_H = "firmware/include/ecco_fallback_durable_model.h"
MIRROR = "registry/fallback_save.py"

COMMIT_STMT = ("ecco_fbdurable::PriorDesc{lp, dp.stored_len}, r);")
BODY_IND = 10
SETS_WAIT = "      - wait_until:\n          condition:\n            lambda: 'return true;'\n          timeout: 10ms\n"
INV_PLAN = "  const ecco_fallback::FallbackProfileV1 pn = ecco_fallback::invalidate_profile(in.p);"
PLAN_ANCHOR = ("invalidate_changed_text());\n  const uint8_t wc = ecco_fbdurable::classify_witness(in.w_load, in.w);\n"
               "  if (!ecco_fallback::profile_invalidate_permitted(in.p) ||")


def _swap_p2_and_release(t):
    a = t.index("      - lambda: |-\n          // SAVE final step, part 2 of 2 (FB-B2): COMMIT.")
    b = t.index("      - lambda: |-\n          // The single release point")
    c = t.index("\n  # Candidate reset (RAM only).")
    return t[:a] + t[b:c] + t[a:b] + t[c:]


def _move_arm_read_after_ie2(t):
    s, e = SP_INV(t)
    seg = t[s:e]
    a = "          const bool armed = id(fallback_profile_arm).state;\n          id(fallback_profile_arm).turn_off();\n"
    anchor = "          // I2..I12 over the RAM mirror (cheap first: a refusal never costs a storage read).\n"
    if seg.count(a) != 1 or seg.count(anchor) != 1:
        raise AssertionError("anchor count (move arm read)")
    seg = seg.replace(a, "").replace(anchor, a + anchor)
    return t[:s] + seg + t[e:]


def _move_candidate_copy_after_ie2(t):
    s, e = SP_SAVE(t)
    seg = t[s:e]
    a = "          const std::array<uint16_t, 31> c_words = id(fallback_profile_cand_words);\n"
    anchor = "          // Gather the RAM inputs of G0..G16 (no storage access here).\n"
    if seg.count(a) != 1 or seg.count(anchor) != 1:
        raise AssertionError("anchor count (move candidate copy)")
    seg = seg.replace(a, "").replace(anchor, anchor + a)
    return t[:s] + seg + t[e:]


def _prepend_api_action(t):
    raw = L.raw_api_action(t, "fallback_profile_execute")
    if t.count(raw) != 1:
        raise AssertionError("raw api action not unique")
    t = t.replace(raw, "")
    head = "    - action: free_power_recovery_execute\n"
    # the free_power action has its own comment block above it: keep the new action directly above the `- action:` line
    if t.count(head) != 1:
        raise AssertionError("free_power_recovery_execute head")
    return t.replace(head, raw.rstrip("\n") + "\n" + head)


def _extra_switch(t):
    anchor = "          id(fallback_profile_arm_on_ms) = millis();\n\nselect:\n"
    new = ("          id(fallback_profile_arm_on_ms) = millis();\n\n  - platform: template\n    name: \"ECCO Fallback Profile Arm 2\"\n"
           "    id: fallback_profile_arm_2\n    optimistic: true\n    restore_mode: ALWAYS_OFF\n\nselect:\n")
    return L.mutate(t, anchor, new)


MODBUS_READ_NODE = ("      - modbus_client.read_holding_registers:\n          modbus_id: inverter_modbus\n          address: 0x01\n"
                    "          start_address: 230\n          count: 3\n          on_response:\n            then:\n              - lambda: |-\n"
                    "                  id(fallback_profile_step_terminal) = true;\n")
MODBUS_WRITE_NODE = ("      - modbus_client.write_multiple_registers:\n          modbus_id: inverter_modbus\n          address: 0x01\n"
                     "          start_address: 244\n          values: !lambda |-\n            return std::vector<uint16_t>{1};\n")
EXTRA_INTERVAL = "  - interval: 10s\n    then:\n      - lambda: |-\n          id(fallback_profile_op_purpose) = 0;\n\n"

MUTANTS: list = []


def M(mid: str, desc: str, fn, dets) -> None:
    MUTANTS.append((mid, desc, fn, list(dets)))


# ---- A. the writer is called in exactly two lambdas, once each, never retried (X1-X4) -----------------------------------------------
M("M001", "a SECOND commit_transition_t call in SAVE_FINAL part 2", sub(sp_p2, COMMIT_STMT, COMMIT_STMT + "\n                (void) ecco_fbdurable::commit_transition_t(nvs, plan.w_new, w, ecco_fbdurable::PriorDesc{lw, dw.stored_len}, plan.p_new, p, ecco_fbdurable::PriorDesc{lp, dp.stored_len}, r);"), ["X4a", "X4b"])
M("M002", "a second commit_transition_t call in the INVALIDATE lambda (retry after a refusal)", sub(SP_INV, COMMIT_STMT, COMMIT_STMT + "\n          (void) ecco_fbdurable::commit_transition_t(nvs, plan.w_new, w, ecco_fbdurable::PriorDesc{lw, dw.stored_len}, plan.p_new, p, ecco_fbdurable::PriorDesc{lp, dp.stored_len}, r);"), ["X4a", "X4b"])
M("M003", "a commit in REVIEW_FINAL", ins_before(sp_rf, "id(fallback_profile_cand_words) = id(fallback_profile_pass2);", "(void) ecco_fbdurable::commit_transition_t(nvs, wn, w, pd, pn, p, pd, rr);"), ["X4a", "X4c"])
M("M004", "a commit in the FB-B1 boot lambda", ins_before(sp_boot, "          id(fallback_profile_boot_loaded) = true;\n", "          (void) ecco_fbdurable::commit_transition_t(nvs, wn, w, pd, pn, p, pd, rr);", 0), ["X4a", "X4c"])
M("M005", "a commit in the housekeeping tick", ins_after(sp_tick, "id(fallback_profile_arm).turn_off();", "(void) ecco_fbdurable::commit_transition_t(nvs, wn, w, pd, pn, p, pd, rr);"), ["X4a", "X4c", "S-INTERVAL"])
M("M006", "a commit in the SAVE gate script", ins_after(SP_SAVE, "const bool armed = id(fallback_profile_arm).state;", "(void) ecco_fbdurable::commit_transition_t(nvs, wn, w, pd, pn, p, pd, rr);"), ["X4a", "X4c"])
M("M007", "a commit in SAVE_FINAL part 1 (the verification lambda)", ins_after(sp_p1, "id(fallback_profile_save_verified) = false;", "(void) ecco_fbdurable::commit_transition_t(nvs, wn, w, pd, pn, p, pd, rr);"), ["X4a", "X4c"])
M("M008", "a commit in the api action lambda", ins_after(sp_api, "id(fallback_profile_exec_hb_ok) = (id(supervision_state) == 1) && id(supervision_stable);", "(void) ecco_fbdurable::commit_transition_t(nvs, wn, w, pd, pn, p, pd, rr);", 12), ["X4a", "X4c", "S-API"])
M("M009", "a commit in on_boot lambda[0] (an old lambda, not FB code)", glob_("          id(ntp_synced_sensor).publish_state(false);\n", "          id(ntp_synced_sensor).publish_state(false);\n          (void) ecco_fbdurable::commit_transition_t(nvs, wn, w, pd, pn, p, pd, rr);\n"), ["X4a", "X4c"])
M("M010", "a raw nvs_set_blob call in a lambda", ins_after(sp_p1, "id(fallback_profile_save_verified) = false;", "nvs_set_blob(h, \"k\", &rec, sizeof(rec));"), ["X1"])
M("M011", "a raw nvs.set_blob member call in the INVALIDATE lambda", ins_before(SP_INV, "ecco_fbdurable::TxnResult r{};", "(void) nvs.set_blob(k, &p, sizeof(p));"), ["X1"])
M("M012", "commit_record on an FB key in the boot lambda (MB28)", ins_before(sp_boot, "          id(fallback_profile_boot_loaded) = true;\n", "          ecco_durable::commit_record(ecco_fbdurable::FALLBACK_PROFILE_KEY, rec);", 0), ["X3", "S-WRITE"])
M("M013", "an FBS write: write_one_<FailbackStateV1, FAILBACK_STATE_KEY> in SAVE_FINAL part 2", ins_before(sp_p2, "ecco_fbdurable::TxnResult r{};", "(void) ecco_fbdurable::write_one_<ecco_fbdurable::FailbackStateV1, ecco_fbdurable::FAILBACK_STATE_KEY>(nvs, s, s, pd, s, r.p);", 14), ["X2"])
M("M014", "an esphome preference object for an FB key (make_preference on 1609458070) in the tick", ins_after(sp_tick, "id(fallback_profile_arm).turn_off();", "auto pref = global_preferences->make_preference<uint8_t>(1609458070u);"), ["X3", "S-AUTH"])
M("M015", "invalidate_profile( called directly (unguarded) from the INVALIDATE lambda", ins_before(SP_INV, "ecco_fbdurable::TxnResult r{};", "const auto np0 = ecco_fallback::invalidate_profile(p);"), ["X4d", "X4b"])
M("M016", "the plan is edited after plan_save built it", ins_before(sp_p2, "ecco_fbdurable::TxnResult r{};", "plan.p_new.generation = 0;", 14), ["X4b"])
M("M017", "commit arguments swapped: the profile record first (MB22 order)", sub(SP_INV, "nvs, plan.w_new, w, ecco_fbdurable::PriorDesc{lw, dw.stored_len}, plan.p_new, p,", "nvs, plan.p_new, p, ecco_fbdurable::PriorDesc{lp, dp.stored_len}, plan.w_new, w,"), ["X4b"])
M("M018", "the YAML builds a record itself (make_provision) before the writer", ins_before(sp_p2, "ecco_fbdurable::TxnResult r{};", "const auto wx = ecco_fbdurable::make_provision(1, 1, 0, 0, ecco_fbdurable::FALLBACK_PROFILE_KEY, 1, ecco_fbdurable::PROV_OP_SAVE);", 14), ["X4b"])
M("M019", "a retry loop around the SAVE commit", sub(sp_p2, "const ecco_fbdurable::TxnOutcome o = ecco_fbdurable::commit_transition_t(", "ecco_fbdurable::TxnOutcome o = ecco_fbdurable::TXN_NOT_COMMITTED;\n                for (int attempt = 0; attempt < 2 && o != ecco_fbdurable::TXN_COMMITTED; attempt++) o = ecco_fbdurable::commit_transition_t("), ["X4b"])
M("M020", "a retry loop around the INVALIDATE commit", sub(SP_INV, "const ecco_fbdurable::TxnOutcome o = ecco_fbdurable::commit_transition_t(", "ecco_fbdurable::TxnOutcome o = ecco_fbdurable::TXN_NOT_COMMITTED;\n          for (int attempt = 0; attempt < 2 && o != ecco_fbdurable::TXN_COMMITTED; attempt++) o = ecco_fbdurable::commit_transition_t("), ["X4b"])
M("M021", "an EspNvs object in the SAVE gate script", ins_after(SP_SAVE, "const bool armed = id(fallback_profile_arm).state;", "ecco_fbdurable::EspNvs nvs;"), ["X4c"])
M("M022", "a write-side type (TxnResult) in REVIEW_FINAL", ins_before(sp_rf, "id(fallback_profile_cand_words) = id(fallback_profile_pass2);", "ecco_fbdurable::TxnResult rx{};"), ["X4c"])
M("M023", "an ecco_fbsave symbol in the REVIEW gate", ins_after(SP_REVIEW, "id(fallback_profile_arm).turn_off();", "(void) ecco_fbsave::arm_expired(0, 0);"), ["X4c"])
M("M024", "a second nvs_set_blob call site in the FB-B0 adapter header", hdr(DUR_H, "    return nvs_get_blob(this->handle(), k, out, len);", "    (void) nvs_set_blob(this->handle(), k, out, *len);\n    return nvs_get_blob(this->handle(), k, out, len);"), ["X1"])
M("M025", "an nvs_erase_all in the FB-B0 model header", hdr(MODEL_H, "inline bool write_latched() { return s_write_latched; }", "inline bool write_latched() { return s_write_latched; }\ninline void wipe(uint32_t h) { nvs_erase_all(h); }"), ["X1"])
M("M026", "a THIRD write_one_ instantiation (FBS) in the model header", hdr(MODEL_H, "  if (op == KEY_COMMITTED)\n    return TXN_COMMITTED;", "  (void) write_one_<FailbackStateV1, FAILBACK_STATE_KEY>(nvs, s, s, p_pd, s, r.p);\n  if (op == KEY_COMMITTED)\n    return TXN_COMMITTED;"), ["X2"])
M("M027", "an FBS WriteTarget specialisation in the model header", hdr(MODEL_H, "template<> struct WriteTarget<FallbackProfileV1, FALLBACK_PROFILE_KEY> {", "template<> struct WriteTarget<FailbackStateV1, FAILBACK_STATE_KEY> {\n  static constexpr bool allowed = true;\n};\ntemplate<> struct WriteTarget<FallbackProfileV1, FALLBACK_PROFILE_KEY> {"), ["X2"])
M("M028", "the FB-B2 header calls the writer", hdr(SAVE_H, "constexpr uint32_t total_us(uint32_t w_us, uint32_t p_us) { return (uint32_t) (w_us + p_us); }", "constexpr uint32_t total_us(uint32_t w_us, uint32_t p_us) { return (uint32_t) (w_us + p_us); }\nconstexpr void zz() { ecco_fbdurable::commit_transition_t(a, b); }"), ["X4d", "X4a"])
M("M029", "header: invalidate_profile( moved in front of the generation / permission refusal (BLK-51)", hdr(SAVE_H, PLAN_ANCHOR, "invalidate_changed_text());\n  const ecco_fallback::FallbackProfileV1 pn0 = ecco_fallback::invalidate_profile(in.p);\n  const uint8_t wc = ecco_fbdurable::classify_witness(in.w_load, in.w);\n  if (!ecco_fallback::profile_invalidate_permitted(in.p) ||"), ["X4d"])
M("M030", "header: the two invalidate guards AND-ed instead of OR-ed", hdr(SAVE_H, PLAN_ANCHOR, PLAN_ANCHOR[:-2] + "&&"), ["X4d"])

# ---- B. INVALIDATE: one synchronous lambda, no lock, no wait, bus-idle last (D1 / D2) -----------------------------------------------
M("M040", "INVALIDATE gets a wait_until action", append_to_script("fallback_profile_invalidate", SETS_WAIT), ["S-INV", "S-REBOOT"])
M("M041", "INVALIDATE calls delay()", ins_after(SP_INV, "const bool armed = id(fallback_profile_arm).state;", "delay(10);"), ["S-INV"])
M("M042", "INVALIDATE takes the write mutex (D2)", ins_after(SP_INV, "const bool armed = id(fallback_profile_arm).state;", "id(manual_write_in_progress) = true;"), ["S-INV", "S-CTX", "S-AUTH"])
M("M043", "INVALIDATE takes the operation flag (D2)", ins_after(SP_INV, "const bool armed = id(fallback_profile_arm).state;", "id(fallback_profile_op_in_progress) = true;"), ["S-INV", "S-CTX"])
M("M044", "INVALIDATE starts the dispatch (script.execute)", append_to_script("fallback_profile_invalidate", "      - script.execute:\n          id: fallback_profile_capture_dispatch\n"), ["S-INV", "S-AUTH", "I-WS"])
M("M045", "a statement between the bus-idle check and the writer (the check is no longer the last)", ins_before(SP_INV, "const ecco_fbdurable::TxnOutcome o = ecco_fbdurable::commit_transition_t(", "id(fallback_profile_seen_hw_gen) += 0;"), ["S-INV"])
M("M046", "the INVALIDATE bus-idle check removed", sub(SP_INV, "if (!ecco_fbsave::invalidate_bus_idle(bn, id(inverter_modbus)->tx_buffer_empty(), id(inverter_modbus)->tx_blocked())) {", "if (false) {"), ["S-INV", "S-PREAMBLE"])
M("M047", "INVALIDATE preamble reordered: the candidate is invalidated before the arm is read", _move_arm_read_after_ie2, ["S-PREAMBLE"])
M("M048", "the INVALIDATE in-flight gate dropped", sub(SP_INV, "if (i1.code != ecco_fbsave::IG_UNSET) {", "if (false) {"), ["S-PREAMBLE"])
M("M049", "the I1 refusal also consumes the candidate", sub(SP_INV, "publish_state(i1.text.c_str());\n              return;", "publish_state(i1.text.c_str());\n              id(fallback_profile_cand_valid) = false;\n              return;"), ["S-PREAMBLE", "S-INV"])
M("M050", "the SAVE G1 refusal also touches the capture state", sub(SP_SAVE, "publish_state(g1.text.c_str());\n              return;", "publish_state(g1.text.c_str());\n              id(fallback_profile_capture_state) = ecco_fbcap::CAPTURE_IDLE;\n              return;"), ["S-PREAMBLE"])
M("M051", "the SAVE gate turns the arm off BEFORE the in-flight check", sub(SP_SAVE, "          // G1: another Fallback Profile operation is in flight - touch nothing but the arm and the result text.\n", "          // G1: another Fallback Profile operation is in flight - touch nothing but the arm and the result text.\n          id(fallback_profile_arm).turn_off();\n"), ["S-PREAMBLE", "S-ARM"])
M("M052", "the SAVE gate copies the candidate words AFTER invalidating the candidate", _move_candidate_copy_after_ie2, ["S-PREAMBLE"])
M("M053", "the SAVE gate reads exec_* after the gate decision", ins_after(SP_SAVE, "if (sr.obl.size() > 0) id(fallback_profile_obl_text) = sr.obl.c_str();", "const size_t xl = id(fallback_profile_exec_target_id).size();"), ["S-PREAMBLE"])
M("M054", "the SAVE gate script reads supervision_stable", ins_after(SP_SAVE, "const bool armed = id(fallback_profile_arm).state;", "const bool sup = id(supervision_stable);"), ["S-SUP", "S-AUTH"])
M("M055", "the word 'supervision' in a comment of the SAVE gate", ins_after(SP_SAVE, "const bool armed = id(fallback_profile_arm).state;", "// supervision is not read here"), ["S-SUP"])
M("M056", "the word 'supervision' in the arm switch comment", sub(sp_sw, "  # turn_on_action only stamps the time the lifetime counts from.", "  # supervision: turn_on_action only stamps the time the lifetime counts from."), ["S-SUP", "S-ARM"])
M("M057", "the word 'supervision' in the FB-B2 globals comment", sub(sp_glob, "  # operator write flow. Every global below is restore_value: no and has a", "  # operator write flow (supervision aside). Every global below is restore_value: no and has a"), ["S-SUP"])
M("M058", "a second supervision read in the api action lambda", sub(sp_api, "id(fallback_profile_exec_hb_ok) = (id(supervision_state) == 1) && id(supervision_stable);", "id(fallback_profile_exec_hb_ok) = (id(supervision_state) == 1) && id(supervision_stable) && id(supervision_have_valid);"), ["S-SUP", "S-API"])
M("M059", "the heartbeat snapshot dropped (hb_ok always true)", sub(sp_api, "id(fallback_profile_exec_hb_ok) = (id(supervision_state) == 1) && id(supervision_stable);", "id(fallback_profile_exec_hb_ok) = true;"), ["S-API", "S-SUP"])
# FB-B2 hardening: the commit-time heartbeat re-check (SAVE_FINAL part 2)
M("M059a", "the commit-time heartbeat re-check removed from SAVE_FINAL part 2", sub(sp_p2, "if (!((id(supervision_state) == 1) && id(supervision_stable))) {", "if (false) {"), ["S-SUP"])
M("M059b", "a second commit-time heartbeat read in SAVE_FINAL part 2", sub(sp_p2, "if (!((id(supervision_state) == 1) && id(supervision_stable))) {", "if (!((id(supervision_state) == 1) && id(supervision_stable) && id(supervision_have_valid))) {"), ["S-SUP"])
M("M059c", "the heartbeat re-check refusal text removed (res unchanged)", sub(sp_p2, "res = ecco_fbsave::save_hb_text();", "res = ecco_fbsave::save_bus_quiet_text();"), ["S-SUP"])
M("M059d", "the heartbeat read moved into SAVE_FINAL part 1 (not at the commit)", ins_after(sp_p1, "id(fallback_profile_save_verified) = false;", "const bool hbx = id(supervision_stable);"), ["S-SUP", "S-IDS", "S-AUTH"])
M("M060", "random_uint32 in the FB boot lambda", ins_before(sp_boot, "          id(fallback_profile_boot_loaded) = true;\n", "          id(fallback_profile_boot_salt) = random_uint32() | 1u;", 0), ["S-NTP"])
M("M061", "esp_restart() in SAVE_FINAL part 2 (BLK-64)", ins_before(sp_p2, "ecco_fbdurable::TxnResult r{};", "esp_restart();", 14), ["S-REBOOT", "S-AUTH"])
M("M062", "App.reboot() in the INVALIDATE lambda", ins_before(SP_INV, "ecco_fbdurable::TxnResult r{};", "App.reboot();"), ["S-REBOOT", "S-AUTH"])
M("M063", "a restart button press from a lambda in the SAVE gate", ins_after(SP_SAVE, "const bool armed = id(fallback_profile_arm).state;", "id(restart_button).press();"), ["S-REBOOT"])
M("M064", "a button.press action in the SAVE script", append_to_script("fallback_profile_save", "      - button.press: restart_button\n"), ["S-REBOOT"])

# ---- C. the arm (B12) --------------------------------------------------------------------------------------------------------------
M("M070", "arm.turn_on() in the SAVE gate lambda", ins_after(SP_SAVE, "const bool armed = id(fallback_profile_arm).state;", "id(fallback_profile_arm).turn_on();"), ["S-ARM"])
M("M071", "a switch.turn_on action naming the arm in the SAVE script", append_to_script("fallback_profile_save", "      - switch.turn_on: fallback_profile_arm\n"), ["S-ARM", "S-REBOOT"])
M("M072", "the arm TTL statement removed from the housekeeping lambda", sub(sp_tick, "if (id(fallback_profile_arm).state && ecco_fbsave::arm_expired(millis(), id(fallback_profile_arm_on_ms))) {", "if (false) {"), ["S-ARM"])
M("M073", "the arm TTL computed with a literal instead of arm_expired", sub(sp_tick, "ecco_fbsave::arm_expired(millis(), id(fallback_profile_arm_on_ms))", "(uint32_t) (millis() - id(fallback_profile_arm_on_ms)) >= 120000u"), ["S-ARM"])
M("M074", "arm.turn_off() dropped from REVIEW_FINAL", sub(sp_rf, "id(fallback_profile_arm).turn_off();", "(void) 0;"), ["S-ARM", "I-EDITS"])
M("M075", "arm.turn_off() dropped from the REVIEW gate preamble", sub(SP_REVIEW, "id(fallback_profile_arm).turn_off();", "(void) 0;"), ["S-ARM", "I-EDITS"])
M("M076", "arm.turn_off() dropped from the INVALIDATE preamble", sub(SP_INV, "const bool armed = id(fallback_profile_arm).state;\n          id(fallback_profile_arm).turn_off();", "const bool armed = id(fallback_profile_arm).state;"), ["S-ARM", "S-PREAMBLE"])
M("M077", "arm.turn_off() dropped from the SAVE preamble", sub(SP_SAVE, "const bool armed = id(fallback_profile_arm).state;\n          id(fallback_profile_arm).turn_off();", "const bool armed = id(fallback_profile_arm).state;"), ["S-ARM", "S-PREAMBLE"])
M("M078", "turn_on_action stamps 0 instead of millis()", sub(sp_sw, "id(fallback_profile_arm_on_ms) = millis();", "id(fallback_profile_arm_on_ms) = 0;"), ["S-ARM"])
M("M079", "turn_on_action does more than stamp the time", sub(sp_sw, "id(fallback_profile_arm_on_ms) = millis();", "id(fallback_profile_arm_on_ms) = millis();\n          id(fallback_profile_op_purpose) = 2;"), ["S-ARM"])
M("M080", "an extra switch", _extra_switch, ["I-DELTA"])
M("M081", "arm restore_mode RESTORE_DEFAULT_OFF", sub(sp_sw, "restore_mode: ALWAYS_OFF", "restore_mode: RESTORE_DEFAULT_OFF"), ["S-ARM"])
M("M082", "arm not optimistic", sub(sp_sw, "optimistic: true", "optimistic: false"), ["S-ARM"])
M("M083", "arm_on_ms stamped from the SAVE gate as well", ins_after(SP_SAVE, "const bool armed = id(fallback_profile_arm).state;", "id(fallback_profile_arm_on_ms) = millis();"), ["S-ARM"])
M("M084", "the arm gets a turn_off_action", sub(sp_sw, "          id(fallback_profile_arm_on_ms) = millis();\n", "          id(fallback_profile_arm_on_ms) = millis();\n    turn_off_action:\n      - lambda: |-\n          id(fallback_profile_arm_on_ms) = 0;\n"), ["S-ARM"])

# ---- D. dispatch / SAVE_FINAL --------------------------------------------------------------------------------------------------------
M("M090", "REVIEW_FINAL is not guarded against the SAVE purpose", sub(sp_rf, "if (id(fallback_profile_op_purpose) == ecco_fbsave::PURPOSE_SAVE) return;", ""), ["S-FIN", "I-EDITS"])
M("M091", "SAVE_FINAL part 1 loses its purpose guard", sub(sp_p1, "if (id(fallback_profile_op_purpose) != ecco_fbsave::PURPOSE_SAVE) return;", ""), ["S-FIN"])
M("M092", "SAVE_FINAL part 2 loses the verified hand-over guard", sub(sp_p2, "if (!id(fallback_profile_save_verified)) return;", ""), ["S-FIN"])
M("M093", "the G3 candidate-id integrity term dropped from SAVE_FINAL part 1", sub(sp_p1, " || id(fallback_profile_save_ctx_id) == 0", ""), ["S-FIN"])
M("M094", "a wait_until action between SAVE_FINAL part 1 and part 2", glob_("      - lambda: |-\n          // SAVE final step, part 2 of 2", SETS_WAIT + "      - lambda: |-\n          // SAVE final step, part 2 of 2"), ["S-FIN", "S-DISPATCH"])
M("M095", "delay() inside SAVE_FINAL part 2", ins_before(sp_p2, "ecco_fbdurable::TxnResult r{};", "delay(1);", 14), ["S-FIN"])
M("M096", ".execute() inside SAVE_FINAL part 1", ins_after(sp_p1, "id(fallback_profile_save_verified) = false;", "id(fallback_profile_review).execute();"), ["S-FIN", "S-AUTH"])
M("M097", "a script.execute action between SAVE_FINAL part 1 and part 2", glob_("      - lambda: |-\n          // SAVE final step, part 2 of 2", "      - script.execute: fallback_profile_invalidate_candidate\n      - lambda: |-\n          // SAVE final step, part 2 of 2"), ["S-FIN", "S-DISPATCH", "S-AUTH"])
M("M098", "the committed words come from the candidate (cand_words)", sub(sp_p2, "pi.words = id(fallback_profile_pass2);", "pi.words = id(fallback_profile_cand_words);"), ["S-IDS", "S-POD"])
M("M099", "the committed words come from the save context words", sub(sp_p2, "pi.words = id(fallback_profile_pass2);", "pi.words = id(fallback_profile_save_ctx_words);"), ["S-IDS", "S-POD"])
M("M100", "SAVE_FINAL part 1 reads an exec_* global", ins_after(sp_p1, "id(fallback_profile_save_verified) = false;", "const size_t xt = id(fallback_profile_exec_target_id).size();"), ["S-IDS", "S-SUP"])
M("M101", "SAVE_FINAL part 2 reads a manual-configuration staging global", ins_before(sp_p2, "ecco_fbdurable::TxnResult r{};", "const auto mc = id(manual_slot1_start_hour);", 14), ["S-IDS"])
M("M102", "pi.cand_prior_class taken from the candidate instead of the save context", sub(sp_p2, "pi.cand_prior_class = id(fallback_profile_save_ctx_prior_class);", "pi.cand_prior_class = id(fallback_profile_cand_prior_class);"), ["S-POD", "S-IDS"])
M("M103", "a SAVE context global assigned outside the accept branch", sub(SP_SAVE, "            id(fallback_profile_capture_state) = ecco_fbcap::CAPTURE_IDLE;", "            id(fallback_profile_capture_state) = ecco_fbcap::CAPTURE_IDLE;\n            id(fallback_profile_save_ctx_id) = c_id;"), ["S-CTX"])
M("M104", "purpose SAVE set on the refusal path as well", sub(SP_SAVE, "            id(fallback_profile_capture_state) = ecco_fbcap::CAPTURE_IDLE;", "            id(fallback_profile_capture_state) = ecco_fbcap::CAPTURE_IDLE;\n            id(fallback_profile_op_purpose) = ecco_fbsave::PURPOSE_SAVE;"), ["S-CTX"])
M("M105", "the accept branch does not set the purpose", sub(SP_SAVE, "id(fallback_profile_op_purpose) = ecco_fbsave::PURPOSE_SAVE;", "(void) 0;"), ["S-CTX"])
M("M106", "the accept branch does not take the write mutex", sub(SP_SAVE, "id(manual_write_in_progress) = true;", "(void) 0;"), ["S-CTX"])
M("M107", "the gate hand-over flag is never reset", sub(SP_SAVE, "id(fallback_profile_gate_accepted) = false;", "(void) 0;"), ["S-CTX"])
M("M108", "RELEASE does not clear the context valid flag", sub(sp_rel, "id(fallback_profile_save_ctx_valid) = false;", "(void) 0;"), ["S-RELEASE", "S-CTX", "I-EDITS"])
M("M109", "RELEASE does not clear the verified hand-over", sub(sp_rel, "id(fallback_profile_save_verified) = false;", "(void) 0;"), ["S-RELEASE", "S-CTX", "I-EDITS"])
M("M110", "the breaker does not clear the verified hand-over", sub(sp_tick, "id(fallback_profile_save_verified) = false;", "(void) 0;"), ["S-RELEASE", "S-CTX", "I-EDITS"])
M("M111", "the breaker assigns the write mutex", ins_after(sp_tick, "const bool lock_held = id(manual_write_in_progress);", "id(manual_write_in_progress) = false;", 12), ["S-RELEASE", "S-CTX", "S-AUTH"])
M("M112", "RELEASE is no longer the last dispatch action (swapped with SAVE_FINAL part 2)", _swap_p2_and_release, ["S-RELEASE", "S-DISPATCH", "S-FIN"])
M("M113", "RELEASE also clears the SAVE_UNCONFIRMED overlay", ins_after(sp_rel, "id(fallback_profile_save_ctx_valid) = false;", "id(fallback_profile_save_unconfirmed) = false;"), ["S-UNCONF", "S-RELEASE"])
M("M114", "the boot lambda assigns the SAVE_UNCONFIRMED overlay", ins_before(sp_boot, "          id(fallback_profile_boot_loaded) = true;\n", "          id(fallback_profile_save_unconfirmed) = false;", 0), ["S-UNCONF"])
M("M115", "UNKNOWN_REBOOT no longer sets the overlay", sub(sp_p2, "id(fallback_profile_save_unconfirmed) = true;", "id(fallback_profile_save_unconfirmed) = false;"), ["S-UNCONF"])
M("M116", "REVIEW_FINAL assigns the retained werr", ins_before(sp_rf, "id(fallback_profile_arm).turn_off();", "id(fallback_durable_last_err) = 0;"), ["S-UNCONF"])
M("M117", "REVIEW_FINAL publishes B1 without the overlay", sub(sp_rf, "const char *cls_name = ecco_fbcap::epc_name(eff_cls);", "const char *cls_name = ecco_fbcap::epc_name(e.cls);"), ["S-OVERLAY", "I-EDITS"])
M("M118", "REVIEW_FINAL ri.cls ignores the overlay", sub(sp_rf, "ri.cls = eff_cls;", "ri.cls = e.cls;"), ["S-OVERLAY", "I-EDITS", "S-POD"])
M("M119", "SAVE_FINAL part 2 passes 0, 0 to b2_text (loses the retained werr / us)", sub(sp_p2, "b2_text(lp, p, lw, w, e.why, id(fallback_durable_last_err), id(fallback_durable_last_us))", "b2_text(lp, p, lw, w, e.why, 0, 0)"), ["S-OVERLAY"])
M("M120", "the boot lambda goes back to b2_text(..., 0, 0)", sub(sp_boot, "id(fallback_durable_last_err), id(fallback_durable_last_us)", "0, 0"), ["S-OVERLAY", "I-EDITS"])
M("M121", "INVALIDATE publishes B1 without the overlay", sub(SP_INV, "epc_name(ecco_fbsave::overlay_class(e2.cls, id(fallback_profile_save_unconfirmed)))", "epc_name(e2.cls)"), ["S-OVERLAY"])
M("M122", "the RAM mirror is encoded from the INTENDED profile (MB26)", sub(sp_p2, "id(fallback_profile_bytes) = ecco_fallback::encode_profile(m.p);", "id(fallback_profile_bytes) = ecco_fallback::encode_profile(plan.p_new);"), ["S-MIRROR"])
M("M123", "INVALIDATE encodes the witness mirror from the intended record", sub(SP_INV, "id(fallback_witness_bytes) = ecco_fbdurable::encode_provision(m.w);", "id(fallback_witness_bytes) = ecco_fbdurable::encode_provision(plan.w_new);"), ["S-MIRROR"])
M("M124", "SAVE_FINAL part 2 skips nvs_healthy() (MB25)", sub(sp_p2, "const bool healthy = ecco_fbdurable::nvs_healthy();", "const bool healthy = true;"), ["S-MIRROR", "S-FIN"])
M("M125", "INVALIDATE skips nvs_healthy()", sub(SP_INV, "const bool healthy = ecco_fbdurable::nvs_healthy();", "const bool healthy = true;"), ["S-MIRROR", "S-PREAMBLE"])
M("M126", "seen_hw_gen is not raised after the commit (MB34)", sub(sp_p2, "id(fallback_profile_seen_hw_gen) = ecco_fbdurable::next_seen_hw_gen(", "id(fallback_profile_seen_hw_gen) = std::max<uint32_t>("), ["S-MIRROR", "S-FIN"])
M("M127", "mirror_after is fed the intended records", sub(sp_p2, "ecco_fbdurable::mirror_after(o, r, p, lp, w, lw)", "ecco_fbdurable::mirror_after(o, r, plan.p_new, lp, plan.w_new, lw)"), ["S-MIRROR", "S-FIN"])
M("M128", "the witness latch note no longer waits for the key to be COMMITTED", sub(sp_p2, "if (r.w.outcome == ecco_fbdurable::KEY_COMMITTED) lat = ecco_fbdurable::note_committed(lat, ecco_fbdurable::KEY_BIT_WITNESS);", "lat = ecco_fbdurable::note_committed(lat, ecco_fbdurable::KEY_BIT_WITNESS);"), ["S-MIRROR"])
M("M129", "the SAVE bus-quiet check removed", sub(sp_p2, "if (!ecco_fbsave::commit_bus_quiet(id(fallback_profile_op_in_progress), id(manual_write_in_progress),", "if (false && !ecco_fbsave::commit_bus_quiet(id(fallback_profile_op_in_progress), id(manual_write_in_progress),"), ["S-FIN"])
M("M130", "a statement between the SAVE bus-quiet check and the writer", sub(sp_p2, "const ecco_fbdurable::TxnOutcome o = ecco_fbdurable::commit_transition_t(", "id(fallback_profile_seen_hw_gen) += 0;\n                const ecco_fbdurable::TxnOutcome o = ecco_fbdurable::commit_transition_t("), ["S-FIN"])
M("M131", "the REPLACE CORRUPT forensic WARN line dropped", sub(sp_p2, "if (rc0.size() > 0) ESP_LOGW(\"fbdurable\", \"%s\", rc0.c_str());", ""), ["S-FIN", "S-LIT"])
M("M132", "the transaction log is WARN even when committed", sub(sp_p2, "ESP_LOGI(\"fbdurable\", \"%s\", lg.c_str());", "ESP_LOGW(\"fbdurable\", \"%s\", lg.c_str());"), ["S-FIN", "S-LIT"])
M("M133", "an eager lease-marker probe before the RAM-leg decision", ins_before(sp_p1, "const ecco_fbsave::FinalGate f0 = ecco_fbsave::final_gate_decide(gi, pr);", "(void) ecco_fbdurable::read_direct_t(nvs, ecco_durable::key_for(ecco_durable::FREE_POWER_VALID_TAG), m0, d0);", 14), ["S-FIN"])
M("M134", "the probe latch is reset to 0 in SAVE_FINAL part 1", ins_after(sp_p1, "id(fallback_profile_probe_latch) = fg.gr.latch;", "id(fallback_profile_probe_latch) = 0;", 12), ["S-FIN"])
M("M135", "SAVE_FINAL part 1 uses the REVIEW-worded gate_decide", ins_before(sp_p1, "const ecco_fbsave::FinalGate fg = ecco_fbsave::final_gate_decide(gi, pr);", "const auto gr0 = ecco_fbcap::gate_decide(gi, pr);", 12), ["S-FIN"])
M("M136", "the L2 re-check dropped from SAVE_FINAL part 1", sub(sp_p1, "if (l2.count > 0) {", "if (false) {"), ["S-FIN"])
M("M137", "pass2 == candidate dropped from SAVE_FINAL part 1", sub(sp_p1, "if (go && ecco_fbcap::first_diff(id(fallback_profile_save_ctx_words), id(fallback_profile_pass2)) >= 0) {", "if (false) {"), ["S-FIN"])
M("M138", "pass1 == pass2 dropped from SAVE_FINAL part 1", sub(sp_p1, "if (go && ecco_fbcap::first_diff(id(fallback_profile_pass1), id(fallback_profile_pass2)) >= 0) {", "if (false) {"), ["S-FIN"])
M("M139", "the NTP re-check dropped from SAVE_FINAL part 2", sub(sp_p2, "if (!ecco_fbsave::clock_trusted_for_save(time_ok, epoch)) {", "if (false) {"), ["S-FIN"])
M("M140", "an untrusted clock stores epoch 0 / the raw timestamp", sub(sp_p2, "epoch = time_ok ? (uint32_t) id(ntp_time).now().timestamp : 0u;", "epoch = (uint32_t) id(ntp_time).now().timestamp;"), ["S-FIN"])
M("M141", "pi.captured_epoch never assigned", sub(sp_p2, "pi.captured_epoch = epoch;", "(void) 0;"), ["S-POD", "S-FIN"])
M("M142", "pi.captured_epoch = 0", sub(sp_p2, "pi.captured_epoch = epoch;", "pi.captured_epoch = 0;"), ["S-POD"])
M("M143", "the drain timeout 3000 ms -> 5000 ms", glob_("                timeout: 3000ms\n      - lambda: |-\n          // REVIEW final step", "                timeout: 5000ms\n      - lambda: |-\n          // REVIEW final step"), ["S-DRAIN"])
M("M144", "the drain guard is never true", sub(SP_DISP, "return id(fallback_profile_op_purpose) == ecco_fbsave::PURPOSE_SAVE && !id(fallback_profile_read_failed);", "return false;"), ["S-DRAIN"])
M("M145", "the drain guard ignores a failed read", sub(SP_DISP, "return id(fallback_profile_op_purpose) == ecco_fbsave::PURPOSE_SAVE && !id(fallback_profile_read_failed);", "return id(fallback_profile_op_purpose) == ecco_fbsave::PURPOSE_SAVE;"), ["S-DRAIN"])
M("M146", "header PRECOMMIT_WAIT_MS 3000 -> 2000 (the YAML timeout no longer equals it)", hdr(SAVE_H, "constexpr uint32_t PRECOMMIT_WAIT_MS = 3000u;", "constexpr uint32_t PRECOMMIT_WAIT_MS = 2000u;"), ["S-DRAIN", "S-HDRCONST"])
M("M147", "mirror ARM_TTL_MS 120000 -> 100000", hdr(MIRROR, "ARM_TTL_MS = 120000", "ARM_TTL_MS = 100000"), ["S-HDRCONST"])
M("M148", "header PURPOSE_SAVE 2 -> 1 (collides with REVIEW)", hdr(SAVE_H, "constexpr uint8_t PURPOSE_SAVE = 2;", "constexpr uint8_t PURPOSE_SAVE = 1;"), ["S-HDRCONST"])
M("M149", "the IE2 reason made loud (the SAVE's own consumption would publish a B9 line)", hdr(CAP_H, 'constexpr char REASON_SUPERSEDED[] = "superseded";', 'constexpr char REASON_SUPERSEDED[] = "review cleared";'), ["S-HDRCONST"])

# ---- E. the api action -----------------------------------------------------------------------------------------------------------------
M("M160", "an api.respond added to fallback_profile_execute", glob_("              - script.execute:\n                  id: fallback_profile_save\n\nota:\n", "              - script.execute:\n                  id: fallback_profile_save\n        - api.respond:\n            success: true\n\nota:\n"), ["S-API", "S-REBOOT"])
M("M161", "fallback_profile_execute PREPENDED before free_power_recovery_execute", _prepend_api_action, ["S-API", "I-DELTA"])
M("M162", "the action variable target_id renamed id", sub(sp_api, "        target_id: string", "        id: string"), ["S-API"])
M("M163", "the confirmation variable typed int", sub(sp_api, "        confirmation: string", "        confirmation: int"), ["S-API"])
M("M164", "the StringRef is no longer copied with .str()", sub(sp_api, "id(fallback_profile_exec_action) = action.str();", "id(fallback_profile_exec_action) = action;"), ["S-API"])
M("M165", "a fourth api action appended", glob_("\nota:\n", "    - action: fallback_profile_extra\n      then:\n        - lambda: |-\n            id(fallback_profile_exec_hb_ok) = false;\n\nota:\n"), ["S-API", "I-DELTA"])
M("M166", "a second ha_supervision_heartbeat action", glob_("\nota:\n", "    - action: ha_supervision_heartbeat\n      variables:\n        challenge: string\n      then:\n        - lambda: |-\n            (void) challenge;\n\nota:\n"), ["S-API", "I-DELTA"])
M("M167", "the router compares a string literal instead of calling the header function", sub(sp_api, "return ecco_fbsave::is_invalidate_action(id(fallback_profile_exec_action).c_str(), id(fallback_profile_exec_action).size());", "return id(fallback_profile_exec_action) == \"INVALIDATE\";"), ["S-API"])
M("M168", "the router branches swapped (INVALIDATE goes to the SAVE gate)", sub(sp_api, "            then:\n              - script.execute:\n                  id: fallback_profile_invalidate\n            else:\n              - script.execute:\n                  id: fallback_profile_save", "            then:\n              - script.execute:\n                  id: fallback_profile_save\n            else:\n              - script.execute:\n                  id: fallback_profile_invalidate"), ["S-API", "S-AUTH"])

# ---- F. literals / logging / B9 sources / field completeness ----------------------------------------------------------------------------
M("M180", "an operator-text literal in SAVE_FINAL part 1", ins_after(sp_p1, "res = fg.text;", "const char *lit = \"SAVE REFUSED - nope\";", 14), ["S-LIT", "S-B9SRC"])
M("M181", "a raw literal published to B9 by INVALIDATE", sub(SP_INV, "id(fallback_profile_last_result_text).publish_state(busy.c_str());", "id(fallback_profile_last_result_text).publish_state(\"INVALIDATE REFUSED - busy\");"), ["S-LIT", "S-B9SRC"])
M("M182", "an extra serial-log site (INFO) in SAVE_FINAL part 2", ins_before(sp_p2, "ecco_fbdurable::TxnResult r{};", "ESP_LOGI(\"fbdurable\", \"committed g=%u\", (unsigned) plan.generation);", 14), ["S-LIT"])
M("M183", "a new log tag 'fbsave'", sub(SP_INV, "ESP_LOGW(\"fbdurable\", \"%s\", lg.c_str());", "ESP_LOGW(\"fbsave\", \"%s\", lg.c_str());"), ["S-LIT"])
M("M184", "B9 text not built by a header builder (a bare TextBuf)", sub(sp_p1, "res = fg.text;", "res = ecco_fbcap::TextBuf{};"), ["S-B9SRC"])
M("M185", "SAVE_FINAL part 1 publishes a different variable to B9", sub(sp_p1, "id(fallback_profile_last_result_text).publish_state(res.c_str());", "id(fallback_profile_last_result_text).publish_state(t.c_str());"), ["S-B9SRC"])
M("M186", "si.hb_ok never assigned (G10 input missing)", sub(SP_SAVE, "si.hb_ok = id(fallback_profile_exec_hb_ok);", "(void) 0;"), ["S-POD"])
M("M187", "si.cand_id never assigned (G3 id input missing)", sub(SP_SAVE, "si.cand_id = c_id;", "(void) 0;"), ["S-POD"])
M("M188", "ii.bus.diag_write_lock_since_ms never assigned", sub(SP_INV, "ii.bus.diag_write_lock_since_ms = id(diag_write_lock_since_ms);", "(void) 0;"), ["S-POD"])
M("M189", "bn.verification_read_active never assigned (the refreshed bus check)", sub(SP_INV, "bn.verification_read_active = id(verification_read_active);", "(void) 0;"), ["S-POD"])
M("M190", "pj.target_id = 0", sub(SP_INV, "pj.target_id = ecco_fbsave::parse_hex16(id(fallback_profile_exec_target_id).c_str(), id(fallback_profile_exec_target_id).size());", "pj.target_id = 0;"), ["S-POD"])
M("M191", "the seen_hw_gen floor dropped (pi.seen_hw_gen = 0)", sub(sp_p2, "pi.seen_hw_gen = e.seen_hw_gen;", "pi.seen_hw_gen = 0;"), ["S-POD"])
M("M192", "pi.unconfirmed = false", sub(sp_p2, "pi.unconfirmed = id(fallback_profile_save_unconfirmed);", "pi.unconfirmed = false;"), ["S-POD"])
M("M193", "si.unconfirmed = false (a second SAVE after an unknown outcome is no longer refused: MB27)", sub(SP_SAVE, "si.unconfirmed = id(fallback_profile_save_unconfirmed);", "si.unconfirmed = false;"), ["S-POD"])
M("M194", "gi.fp.run_operator loses the last script of its set (SAVE_FINAL part 1)", sub(sp_p1, "id(free_power_recovery_accept_current_state_dispatch).is_running();", "false;"), ["S-POD"])
M("M195", "gi.bus.manual_write_in_progress fixed to false in SAVE_FINAL part 1", sub(sp_p1, "gi.bus.manual_write_in_progress = id(manual_write_in_progress);", "gi.bus.manual_write_in_progress = false;"), ["S-POD"])
M("M196", "si.time_trusted = true (G11 input forced)", sub(SP_SAVE, "si.time_trusted = id(ntp_synced) && id(ntp_time).now().is_valid();", "si.time_trusted = true;"), ["S-POD", "S-NTP"])
M("M197", "the G13 writes fingerprint loses one counter", sub(SP_SAVE, "(uint32_t) id(dump_start_attempts));", "0u);"), ["S-FPARITY", "S-POD"])
M("M198", "an ntp_ read in the INVALIDATE lambda", ins_after(SP_INV, "const bool armed = id(fallback_profile_arm).state;", "const bool nt = id(ntp_synced);"), ["S-NTP", "S-AUTH"])
M("M199", "the clock check of SAVE_FINAL part 2 replaced by a constant", sub(sp_p2, "const bool time_ok = id(ntp_synced) && id(ntp_time).now().is_valid();", "const bool time_ok = true;"), ["S-FIN"])
M("M200", "a name that does not exist: ecco_fbsave::save_gate_decid", sub(SP_SAVE, "ecco_fbsave::save_gate_decide(", "ecco_fbsave::save_gate_decid("), ["S-NAMES"])
M("M201", "a name that does not exist: ecco_fbcap::b9_texxt in SAVE_FINAL part 1", ins_after(sp_p1, "res = fg.text;", "(void) ecco_fbcap::b9_texxt();", 14), ["S-NAMES"])
M("M202", "header: SaveGateInputs gains a field the YAML does not fill", hdr(SAVE_H, "  bool time_trusted = false;     // the clock is synchronised and valid\n", "  bool time_trusted = false;     // the clock is synchronised and valid\n  bool extra_gate_input = false;\n"), ["S-POD", "S-STRUCTS"])

# ---- G. structure / census ----------------------------------------------------------------------------------------------------------------
M("M210", "an extra Modbus read node in the SAVE script", append_to_script("fallback_profile_save", MODBUS_READ_NODE), ["I-MODBUS", "I-WS", "S-REBOOT"])
M("M211", "a Modbus write node in the INVALIDATE script", append_to_script("fallback_profile_invalidate", MODBUS_WRITE_NODE), ["I-WS", "I-MODBUS", "S-INV", "S-REBOOT"])
M("M212", "an extra script", glob_("\nbutton:\n  - platform: restart\n", "\n  - id: fallback_profile_restore\n    mode: single\n    then:\n      - lambda: |-\n          id(fallback_profile_step) = 0;\n\nbutton:\n  - platform: restart\n"), ["I-DELTA"])
M("M213", "an extra (19th) global", glob_("  - id: fallback_profile_save_ctx_replace_corrupt\n    type: bool\n    restore_value: no\n    initial_value: 'false'\n", "  - id: fallback_profile_save_ctx_replace_corrupt\n    type: bool\n    restore_value: no\n    initial_value: 'false'\n  - id: fallback_profile_save_extra\n    type: bool\n    restore_value: no\n    initial_value: 'false'\n"), ["I-DELTA", "S-GLOB"])
M("M214", "a new global with restore_value yes", sub(sp_glob, "  - id: fallback_profile_arm_on_ms\n    type: uint32_t\n    restore_value: no", "  - id: fallback_profile_arm_on_ms\n    type: uint32_t\n    restore_value: yes"), ["I-DELTA"])
M("M215", "the context words array has the wrong size", sub(sp_glob, "  - id: fallback_profile_save_ctx_words\n    type: std::array<uint16_t, 31>", "  - id: fallback_profile_save_ctx_words\n    type: std::array<uint16_t, 30>"), ["I-DELTA"])
M("M216", "the include of ecco_fallback_save.h missing", glob_("    - include/ecco_fallback_save.h\n", ""), ["I-DELTA"])
M("M217", "an extra 10 s interval", glob_("  # Failback Shadow (FB-C1) - RAM-only, zero-authority evaluator. The first\n", EXTRA_INTERVAL + "  # Failback Shadow (FB-C1) - RAM-only, zero-authority evaluator. The first\n"), ["I-DELTA", "S-INTERVAL"])
M("M218", "the housekeeping lambda 2 reads supervision_stable", ins_after(sp_tick, "id(fallback_profile_arm).turn_off();", "const bool sx = id(supervision_stable);"), ["S-INTERVAL", "S-SUP"])
M("M219", "the housekeeping lambda 2 touches the Modbus hub", ins_after(sp_tick, "id(fallback_profile_arm).turn_off();", "(void) id(inverter_modbus)->tx_blocked();"), ["S-INTERVAL"])
M("M220", "IE8 weakened: a read anomaly no longer clears the candidate", sub(sp_tick, "(id(fallback_profile_save_unconfirmed) || id(fallback_profile_read_anomaly) != 0)) {", "(id(fallback_profile_save_unconfirmed))) {"), ["S-INTERVAL"])
M("M221", "an extra text sensor", glob_("    id: fallback_profile_last_result_text\n    update_interval: never\n", "    id: fallback_profile_last_result_text\n    update_interval: never\n  - platform: template\n    name: \"ECCO Fallback Profile Extra\"\n    id: fallback_profile_extra_text\n    update_interval: never\n"), ["I-DELTA"])
M("M222", "an FB-B1 lambda changed outside the declared edit list (invalidate_candidate)", ins_before(sp_script("fallback_profile_invalidate_candidate"), "id(fallback_profile_cand_valid) = false;", "id(fallback_profile_cand_dx) = 0;"), ["I-EDITS"])
M("M223", "a base lambda changed (on_boot lambda[0])", glob_("          id(ntp_synced_sensor).publish_state(false);\n", "          id(ntp_synced_sensor).publish_state(true);\n"), ["I-EDITS"])
M("M226", "SAVE_FINAL part 1: a refusal text without `go = false` (the verification would still pass)", sub(sp_p1, "res = fg.text;\n              go = false;", "res = fg.text;"), ["S-FIN"])
M("M227", "SAVE_FINAL part 2: the plan refusal check removed (the writer could run on an unvalidated plan)", sub(sp_p2, "if (plan.code != ecco_fbsave::PLAN_OK) {", "if (false) {"), ["S-FIN"])
M("M228", "INVALIDATE: a plan refusal that does not return (falls through to the writer)", sub(SP_INV, "publish_state(plan.text.c_str());\n            return;", "publish_state(plan.text.c_str());"), ["S-INV"])
M("M229", "INVALIDATE: a gate refusal that does not return", sub(SP_INV, "publish_state(ir.text.c_str());\n              return;", "publish_state(ir.text.c_str());"), ["S-INV"])
M("M230", "SAVE_FINAL part 1: the verified hand-over is set unconditionally", sub(sp_p1, "          if (go) {\n            id(fallback_profile_save_verified) = true;", "          {\n            id(fallback_profile_save_verified) = true;"), ["S-FIN"])
M("M231", "a Home Assistant package turns the arm on (no automation may)", lambda t: (t, {"home-assistant/packages/ecco_pro.yaml": read_rel("home-assistant/packages/ecco_pro.yaml") + "\n  - service: switch.turn_on\n    target:\n      entity_id: switch.ecco_clock_dongle_ecco_fallback_profile_arm\n"}), ["S-HA"])
M("M232", "a Home Assistant package calls the execute action", lambda t: (t, {"home-assistant/packages/ecco_system_health.yaml": read_rel("home-assistant/packages/ecco_system_health.yaml") + "\n  - service: esphome.ecco_clock_dongle_fallback_profile_execute\n"}), ["S-HA"])
M("M224", "a Modbus raw-send symbol in the SAVE gate (zero inverter authority)", ins_after(SP_SAVE, "const bool armed = id(fallback_profile_arm).state;", "id(inverter_modbus)->send_raw(frame);"), ["S-WRITE", "S-AUTH"])
M("M225", "a legacy durable commit_record added to a base lambda (call-site count moves)", glob_("          id(ntp_synced_sensor).publish_state(false);\n", "          id(ntp_synced_sensor).publish_state(false);\n          ecco_durable::commit_record(ecco_durable::FREE_POWER_TAG, rec);\n"), ["S-WRITE", "I-EDITS"])

# ---- H. second batch: housekeeping placement, Modbus node census, entity census, RELEASE / breaker completeness, POD fields, B9 prefix source ----
HK_START = "  # Fallback Profile REVIEW (FB-B1) - RAM-only housekeeping. Runs every 10 s and\n"
HK_END = "  # Failback Shadow (FB-C1) - RAM-only, zero-authority evaluator. The first\n"
FP_EXPIRY_LOG = 'ESP_LOGI("free_power_recovery", "Review evidence expired (120s window elapsed)");'


def _move_housekeeping_last(t):
    a, b = L.region(t, HK_START, HK_END)
    return (t[:a] + t[b:]).rstrip("\n") + "\n\n" + t[a:b].rstrip("\n") + "\n"


def _move_housekeeping_before_fp_expiry(t):
    a, b = L.region(t, HK_START, HK_END)
    blk, rest = t[a:b], t[:a] + t[b:]
    if rest.count(FP_EXPIRY_LOG) != 1:
        raise AssertionError("the Free Power evidence-expiry interval anchor is not unique")
    j = rest.rfind("\n  - interval:", 0, rest.index(FP_EXPIRY_LOG)) + 1
    while rest[rest.rfind("\n", 0, j - 1) + 1:j].lstrip().startswith("#"):
        j = rest.rfind("\n", 0, j - 1) + 1
    return rest[:j] + blk + rest[j:]


EXTRA_BUTTON = ("\nbutton:\n  - platform: template\n    name: \"ECCO Fallback Save\"\n    id: fallback_save_button\n    on_press:\n"
                "      - script.execute: fallback_profile_save\n  - platform: restart\n")
M("M233", "the housekeeping interval moved to the END of the interval list (a later interval would run after it: it must never be last)", _move_housekeeping_last, ["S-INTERVAL", "I-DELTA"])
M("M234", "the housekeeping interval moved in front of the Free Power evidence-expiry interval", _move_housekeeping_before_fp_expiry, ["S-INTERVAL", "I-DELTA"])
M("M235", "an EspNvs object in the second housekeeping lambda", ins_after(sp_tick, "id(fallback_profile_arm).turn_off();", "ecco_fbdurable::EspNvs nvs;"), ["S-INTERVAL", "X4c"])
M("M236", "the second housekeeping lambda publishes a raw literal to B9", ins_after(sp_tick, "id(fallback_profile_arm).turn_off();", "id(fallback_profile_last_result_text).publish_state(\"arm expired\");"), ["S-INTERVAL", "S-LIT"])
M("M237", "random_uint32 in the second housekeeping lambda", ins_after(sp_tick, "id(fallback_profile_arm).turn_off();", "const uint32_t rz = random_uint32();"), ["S-INTERVAL", "S-NTP"])
M("M238", "an ESP_LOG line in the second housekeeping lambda", ins_after(sp_tick, "id(fallback_profile_arm).turn_off();", "ESP_LOGI(\"fbcap\", \"arm expired\");"), ["S-INTERVAL", "S-LIT"])
M("M240", "a dispatch FC03 read changes its start address (230 -> 231): not the four pinned reads any more", sub(SP_DISP, "                start_address: 230\n", "                start_address: 231\n", 2), ["I-MODBUS", "I-WS", "I-EDITS"])
M("M241", "a dispatch read loses its on_error handler (four of five reply handlers left on every node)", sub(SP_DISP, "on_error:", "on_errorx:", 4), ["I-MODBUS"])
M("M242", "a fifth Modbus read node appended to the dispatch", append_to_script("fallback_profile_capture_dispatch", MODBUS_READ_NODE), ["I-MODBUS", "I-WS", "S-DISPATCH"])
M("M243", "a Modbus read node in the housekeeping interval", glob_("\n  # Failback Shadow (FB-C1) - RAM-only, zero-authority evaluator. The first\n",
                                                                "      - modbus_client.read_holding_registers:\n          modbus_id: inverter_modbus\n          address: 0x01\n"
                                                                "          start_address: 230\n          count: 3\n\n  # Failback Shadow (FB-C1) - RAM-only, zero-authority evaluator. The first\n"),
  ["I-MODBUS", "S-INTERVAL", "S-REBOOT"])
M("M244", "an extra button that starts the SAVE gate (nothing but the api action may)", glob_("\nbutton:\n  - platform: restart\n", EXTRA_BUTTON), ["I-DELTA", "S-AUTH"])
M("M246", "an extra variable on the fallback_profile_execute api action", sub(sp_api, "        confirmation: string", "        confirmation: string\n        extra: string"), ["S-API"])
M("M247", "the api variables reordered (confirmation before target_id)", sub(sp_api, "        target_id: string\n        confirmation: string", "        confirmation: string\n        target_id: string"), ["S-API"])
M("M248", "the api lambda reads a candidate global", sub(sp_api, "id(fallback_profile_exec_action) = action.str();", "id(fallback_profile_exec_action) = action.str();\n            id(fallback_profile_exec_hb_ok) = id(fallback_profile_cand_valid);"), ["S-API"])
M("M249", "a string literal in the api action lambda", sub(sp_api, "id(fallback_profile_exec_hb_ok) = (id(supervision_state) == 1) && id(supervision_stable);", "id(fallback_profile_exec_hb_ok) = (id(supervision_state) == 1) && id(supervision_stable);\n            id(fallback_profile_exec_target_id) = \"x\";"), ["S-API", "S-LIT"])
M("M250", "a legacy load_record on the FB profile key (1000595297) in a base lambda", glob_("          id(ntp_synced_sensor).publish_state(false);\n", "          id(ntp_synced_sensor).publish_state(false);\n          ecco_durable::load_record(1000595297u, rec);\n"), ["X3", "S-WRITE", "I-EDITS"])
M("M251", "a header names global_preferences->make_preference on the FBS key", hdr(CAP_H, "constexpr uint32_t CANDIDATE_TTL_MS = 120000u;", "constexpr uint32_t CANDIDATE_TTL_MS = 120000u;\ninline void zzp() { auto p = global_preferences->make_preference<uint8_t>(ecco_fbdurable::FAILBACK_STATE_KEY); (void) p; }"), ["X3"])
M("M252", "RELEASE does not clear the purpose", sub(sp_rel, "id(fallback_profile_op_purpose) = 0;", "(void) 0;"), ["S-RELEASE", "S-CTX", "I-EDITS"])
M("M253", "RELEASE does not clear the operation flag", sub(sp_rel, "id(fallback_profile_op_in_progress) = false;", "(void) 0;"), ["S-RELEASE", "S-DISPATCH", "S-CTX"])
M("M254", "RELEASE does not release the write mutex", sub(sp_rel, "id(manual_write_in_progress) = false;", "(void) 0;"), ["S-RELEASE", "S-DISPATCH", "S-CTX"])
M("M255", "RELEASE does not wipe the context words", sub(sp_rel, "id(fallback_profile_save_ctx_words) = std::array<uint16_t, 31>{};", "(void) 0;"), ["S-RELEASE", "S-CTX", "I-EDITS"])
M("M256", "the breaker does not clear the purpose", sub(sp_tick, "id(fallback_profile_op_purpose) = 0;", "(void) 0;"), ["S-RELEASE", "S-CTX"])
M("M257", "a script.stop action in front of RELEASE (a path that could skip the release)", glob_("      - lambda: |-\n          // The single release point", "      - script.stop: fallback_profile_capture_dispatch\n      - lambda: |-\n          // The single release point"), ["S-DISPATCH", "S-REBOOT", "S-FIN"])
M("M258", "the arm switch is renamed", sub(sp_sw, "name: \"ECCO Fallback Profile Arm\"", "name: \"ECCO Fallback Arm\""), ["S-ARM"])
M("M259", "si.cand_saveable never assigned (a NOT-SAVEABLE preview could pass G3)", sub(SP_SAVE, "si.cand_saveable = c_saveable;", "(void) 0;"), ["S-POD"])
M("M260", "gi.fbs_slot never assigned in the SAVE gate", sub(SP_SAVE, "gi.fbs_slot = id(fallback_profile_fbs_slot);", "(void) 0;"), ["S-POD", "S-FPARITY"])
M("M261", "pj.seen_hw_gen never assigned in INVALIDATE", sub(SP_INV, "pj.seen_hw_gen = e.seen_hw_gen;", "(void) 0;"), ["S-POD"])
M("M262", "pi.words never assigned in SAVE_FINAL part 2", sub(sp_p2, "pi.words = id(fallback_profile_pass2);", "(void) 0;"), ["S-POD", "S-IDS"])
M("M263", "in.healthy never assigned in SAVE_FINAL part 2", sub(sp_p2, "in.healthy = healthy;", "(void) 0;"), ["S-POD", "S-MIRROR"])
# ---- I. found by the token-mutation red team: publish-on-change idiom and the exact decision skeleton of the SAVE lambdas ----------------------
M("M270", "INVALIDATE: the busy-text publish guard flipped (`state == busy` publishes nothing)", sub(SP_INV, "id(fallback_profile_last_result_text).state != busy.c_str()", "id(fallback_profile_last_result_text).state == busy.c_str()"), ["S-PUBGUARD"])
M("M271", "SAVE_FINAL part 2: both B1 publish guards flipped", sub(sp_p2, "id(fallback_profile_state_text).state != cls_name", "id(fallback_profile_state_text).state == cls_name", 2), ["S-PUBGUARD"])
M("M272", "SAVE gate: the B3 publish guard flipped", sub(SP_SAVE, "id(fallback_profile_review_text).state != t.c_str()", "id(fallback_profile_review_text).state == t.c_str()"), ["S-PUBGUARD"])
M("M273", "SAVE gate: the in-progress / refusal choice flipped (`t = sr.text` on ACCEPT)", sub(SP_SAVE, "if (sr.code != ecco_fbsave::SG_ACCEPT) t = sr.text;", "if (sr.code == ecco_fbsave::SG_ACCEPT) t = sr.text;"), ["S-DECIDE"])
M("M274", "SAVE_FINAL part 2: the final refusal publish `&&` -> `||` (publishes an empty text)", sub(sp_p2, "res.size() > 0 && id(", "res.size() > 0 || id("), ["S-PUBGUARD"])
M("M275", "SAVE_FINAL part 1: the final publish guard compares the wrong entity", sub(sp_p1, "if (id(fallback_profile_last_result_text).state != res.c_str()) id(fallback_profile_last_result_text).publish_state(res.c_str());", "if (id(fallback_profile_review_text).state != res.c_str()) id(fallback_profile_last_result_text).publish_state(res.c_str());"), ["S-PUBGUARD"])
M("M276", "SAVE_FINAL part 1: the final publish loses its on-change guard", sub(sp_p1, "if (id(fallback_profile_last_result_text).state != res.c_str()) id(fallback_profile_last_result_text).publish_state(res.c_str());", "id(fallback_profile_last_result_text).publish_state(res.c_str());"), ["S-PUBGUARD"])
M("M277", "INVALIDATE: the gate-refusal publish guard flipped", sub(SP_INV, "id(fallback_profile_last_result_text).state != ir.text.c_str()", "id(fallback_profile_last_result_text).state == ir.text.c_str()"), ["S-PUBGUARD"])
M("M280", "SAVE_FINAL part 2: `bool go = true` -> false", sub(sp_p2, "bool go = true;", "bool go = false;"), ["S-DECIDE"])
M("M281", "SAVE_FINAL part 1: `bool go = true` -> false", sub(sp_p1, "bool go = true;", "bool go = false;"), ["S-DECIDE"])
M("M282", "SAVE_FINAL part 2: the integrity guard `||` -> `&&`", sub(sp_p2, "id(fallback_profile_op_purpose)) ||\n              !id(fallback_profile_save_ctx_valid)) {", "id(fallback_profile_op_purpose)) &&\n              !id(fallback_profile_save_ctx_valid)) {"), ["S-DECIDE"])
M("M283", "SAVE_FINAL part 2: the trusted-clock refusal loses its negation", sub(sp_p2, "if (!ecco_fbsave::clock_trusted_for_save(time_ok, epoch)) {", "if (ecco_fbsave::clock_trusted_for_save(time_ok, epoch)) {"), ["S-DECIDE"])
M("M284", "SAVE_FINAL part 1: the id-0 integrity term inverted (`!= 0`)", sub(sp_p1, "id(fallback_profile_save_ctx_id) == 0) {", "id(fallback_profile_save_ctx_id) != 0) {"), ["S-DECIDE", "S-FIN"])
M("M285", "SAVE gate: the B3 reset claims a candidate (`false` -> `true`)", sub(SP_SAVE, "b3_text(id(fallback_profile_capture_state), false, 0, 0, 0,", "b3_text(id(fallback_profile_capture_state), true, 0, 0, 0,"), ["S-DECIDE"])
M("M286", "SAVE_FINAL part 2: the closing B3 reset claims a candidate", sub(sp_p2, "b3_text(ecco_fbcap::CAPTURE_IDLE, false, 0, 0, 0,", "b3_text(ecco_fbcap::CAPTURE_IDLE, true, 0, 0, 0,"), ["S-DECIDE"])
M("M287", "SAVE_FINAL part 1: the refusal B3 reset claims a candidate", sub(sp_p1, "b3_text(ecco_fbcap::CAPTURE_IDLE, false, 0, 0, 0,", "b3_text(ecco_fbcap::CAPTURE_IDLE, true, 0, 0, 0,"), ["S-DECIDE"])
M("M288", "SAVE script: the dispatch starts when the gate did NOT accept", sub(SP_SAVE, "lambda: 'return id(fallback_profile_gate_accepted);'", "lambda: 'return !id(fallback_profile_gate_accepted);'"), ["S-DECIDE"])
M("M289", "INVALIDATE: the transaction log is INFO even when not committed", sub(SP_INV, "ESP_LOGW(\"fbdurable\", \"%s\", lg.c_str());", "ESP_LOGI(\"fbdurable\", \"%s\", lg.c_str());"), ["S-DECIDE", "S-LIT"])
M("M290", "SAVE gate: the obligation-text guard always true (`> 0` -> `>= 0`)", sub(SP_SAVE, "if (sr.obl.size() > 0)", "if (sr.obl.size() >= 0)"), ["S-DECIDE"])
M("M291", "SAVE script: an else branch starts the dispatch although the gate refused", sub(SP_SAVE, "            - script.execute:\n                id: fallback_profile_capture_dispatch\n", "            - script.execute:\n                id: fallback_profile_capture_dispatch\n          else:\n            - script.execute:\n                id: fallback_profile_capture_dispatch\n"), ["S-DECIDE", "S-AUTH"])

M("M292", "SAVE_FINAL part 1: the FREE_POWER lease-marker probe result is never fed to the verdict (`pr.fp` dropped)", sub(sp_p1, "pr.fp = ecco_fbcap::probe_result(ld, m.magic, m.state);", "(void) 0;"), ["S-DECIDE"])
M("M293", "SAVE_FINAL part 1: the DUMP probe is keyed on the FREE_POWER flag", sub(sp_p1, "if (f0.gr.probe_dump) {", "if (f0.gr.probe_fp) {"), ["S-DECIDE"])
M("M294", "SAVE_FINAL part 1: the verdict's obligation text is never published to the review state", sub(sp_p1, "id(fallback_profile_obl_text) = fg.gr.obl.c_str();", "(void) 0;"), ["S-DECIDE"])
M("M295", "SAVE_FINAL part 1: `pass1 == pass2` step runs even after an earlier refusal (`go &&` -> `go ||`)", sub(sp_p1, "if (go && ecco_fbcap::first_diff(id(fallback_profile_pass1), id(fallback_profile_pass2)) >= 0) {", "if (go || ecco_fbcap::first_diff(id(fallback_profile_pass1), id(fallback_profile_pass2)) >= 0) {"), ["S-DECIDE"])
M("M296", "SAVE_FINAL part 1: `pass2 == candidate` step runs even after an earlier refusal", sub(sp_p1, "if (go && ecco_fbcap::first_diff(id(fallback_profile_save_ctx_words), id(fallback_profile_pass2)) >= 0) {", "if (go || ecco_fbcap::first_diff(id(fallback_profile_save_ctx_words), id(fallback_profile_pass2)) >= 0) {"), ["S-DECIDE"])
M("M297", "SAVE_FINAL part 1: the L2 re-check is not guarded by `go` (`if (true)`)", sub(sp_p1, "if (go) {\n            const ecco_fbcap::Refusals l2", "if (true) {\n            const ecco_fbcap::Refusals l2"), ["S-DECIDE"])
M("M299", "SAVE_FINAL part 2: the latch is seeded empty instead of from the RAM latch", sub(sp_p2, "ecco_fbdurable::ReadLatch lat{id(fallback_profile_present_seen), id(fallback_profile_read_anomaly)};", "ecco_fbdurable::ReadLatch lat{};"), ["S-DECIDE"])
M("M300", "SAVE_FINAL part 2: B7 after the commit built from the pre-commit record", sub(sp_p2, "b7_text(m.p_load, m.p, e2.cls)", "b7_text(lp, p, e2.cls)"), ["S-DECIDE"])
M("M301", "SAVE_FINAL part 2: a third direct read (the prologue is exactly FBP, FBW, one health check)", sub(sp_p2, "const uint8_t lp = ecco_fbdurable::read_direct_t(nvs, ecco_fbdurable::FALLBACK_PROFILE_KEY, p, dp);", "const uint8_t lp = ecco_fbdurable::read_direct_t(nvs, ecco_fbdurable::FALLBACK_PROFILE_KEY, p, dp);\n          const uint8_t lx = ecco_fbdurable::read_direct_t(nvs, ecco_fbdurable::FAILBACK_PROVISION_KEY, w, dw);"), ["S-DECIDE", "S-MIRROR"])
M("M302", "INVALIDATE: B8 before the commit built from the wrong class", sub(SP_INV, "b8_text(lp, p, e.cls)", "b8_text(lp, p, e2.cls)"), ["S-DECIDE"])

def move_line_after(sp, line, anchor):
    """Mutant: the one source line `line` is removed from its place and re-inserted directly after the line `anchor` (both exact, once, in `sp`)."""
    def fn(t):
        a, b = sp(t)
        seg, ln, an = t[a:b], line + "\n", anchor + "\n"
        if seg.count(ln) != 1 or seg.count(an) != 1:
            raise AssertionError(f"move_line_after anchors {seg.count(ln)}x / {seg.count(an)}x")
        seg = seg.replace(ln, "").replace(an, an + ln)
        return t[:a] + seg + t[b:]
    return fn


M("M313", "INVALIDATE: pj.target_id is assigned AFTER plan_invalidate(pj) (the plan would see target id 0)", move_line_after(SP_INV, "          pj.target_id = ecco_fbsave::parse_hex16(id(fallback_profile_exec_target_id).c_str(), id(fallback_profile_exec_target_id).size());", "          const ecco_fbsave::Plan plan = ecco_fbsave::plan_invalidate(pj);"), ["S-ORDER"])
M("M314", "SAVE_FINAL part 2: pi.captured_epoch is assigned AFTER plan_save(pi) (the capture time would be 0)", move_line_after(sp_p2, "          pi.captured_epoch = epoch;", "          const ecco_fbsave::Plan plan = ecco_fbsave::plan_save(pi);"), ["S-ORDER"])
M("M315", "SAVE gate: si.hb_ok is assigned AFTER save_gate_decide (G10 would see the fail-closed default)", move_line_after(SP_SAVE, "          si.hb_ok = id(fallback_profile_exec_hb_ok);", "          if (sr.obl.size() > 0) id(fallback_profile_obl_text) = sr.obl.c_str();"), ["S-ORDER"])
M("M316", "INVALIDATE: ii.fbs_slot is assigned AFTER invalidate_gate_decide (the FBS slot check would see its default)", move_line_after(SP_INV, "            ii.fbs_slot = id(fallback_profile_fbs_slot);", "            if (ir.code != ecco_fbsave::IG_ACCEPT) {"), ["S-ORDER"])
M("M303", "arm turned ON through the arrow form `id(arm)->turn_on()` in the SAVE gate", ins_after(SP_SAVE, "const bool armed = id(fallback_profile_arm).state;", "id(fallback_profile_arm)->turn_on();"), ["S-ARM"])
M("M304", "the arm object bound to a reference (`auto &sw = id(arm); sw.turn_on();`)", ins_after(SP_SAVE, "const bool armed = id(fallback_profile_arm).state;", "auto &sw = id(fallback_profile_arm); sw.turn_on();"), ["S-ARM"])
M("M305", "a script started through the arrow form `id(review)->execute()` in SAVE_FINAL part 1", ins_after(sp_p1, "id(fallback_profile_save_verified) = false;", "id(fallback_profile_review)->execute();"), ["S-FIN", "S-AUTH"])
M("M306", "a script stopped from a lambda through the arrow form (`id(dispatch)->stop()`)", ins_after(sp_p1, "id(fallback_profile_save_verified) = false;", "id(fallback_profile_capture_dispatch)->stop();"), ["S-AUTH"])

M("M307", "INVALIDATE: the in-flight gate is told the dispatch is never running", sub(SP_INV, "id(fallback_profile_op_in_progress), id(fallback_profile_capture_dispatch).is_running());", "id(fallback_profile_op_in_progress), false);"), ["S-DECIDE"])
M("M308", "INVALIDATE: the outcome text is built with the wrong prior generation", sub(SP_INV, "plan.op, o, r, plan.generation, p.generation);", "plan.op, o, r, plan.generation, plan.generation);"), ["S-DECIDE"])
M("M309", "INVALIDATE: the transaction log text is built without the generation", sub(SP_INV, "ecco_fbsave::txn_log_text(plan.op, o, r, plan.generation);", "ecco_fbsave::txn_log_text(plan.op, o, r, 0);"), ["S-DECIDE"])
M("M310", "INVALIDATE: the busy refusal uses the SAVE builder", sub(SP_INV, "ecco_fbcap::TextBuf busy = ecco_fbsave::invalidate_busy_text();", "ecco_fbcap::TextBuf busy = ecco_fbsave::save_bus_quiet_text();"), ["S-DECIDE"])
M("M311", "INVALIDATE: the first fresh read targets the witness key instead of the profile key", sub(SP_INV, "read_direct_t(nvs, ecco_fbdurable::FALLBACK_PROFILE_KEY, p, dp)", "read_direct_t(nvs, ecco_fbdurable::FAILBACK_PROVISION_KEY, p, dp)"), ["S-DECIDE", "S-MIRROR"])
M("M312", "SAVE gate: the in-flight gate is told the dispatch is never running", sub(SP_SAVE, "id(fallback_profile_op_in_progress), id(fallback_profile_capture_dispatch).is_running());", "id(fallback_profile_op_in_progress), false);"), ["S-DECIDE"])

TOTAL_US_LINE = "constexpr uint32_t total_us(uint32_t w_us, uint32_t p_us) { return (uint32_t) (w_us + p_us); }"
M("M267", "the FB-B2 header calls esp_restart() (BLK-64 at the header level)", hdr(SAVE_H, TOTAL_US_LINE, TOTAL_US_LINE + "\ninline void zr() { esp_restart(); }"), ["X4d"])
M("M268", "the FB-B2 header calls App.reboot()", hdr(SAVE_H, TOTAL_US_LINE, TOTAL_US_LINE + "\ninline void zr() { App.reboot(); }"), ["X4d"])
M("M264", "mirror: save_bus_quiet_text loses its SAVE REFUSED prefix", hdr(MIRROR, 'return save_refused("inverter bus not quiet at commit; profile unchanged")', 'return _tb("inverter bus not quiet at commit; profile unchanged")'), ["S-B9SRC"])
M("M265", "mirror: invalidate_busy_text loses its INVALIDATE REFUSED prefix", hdr(MIRROR, 'return invalidate_refused("inverter busy; try again")', 'return _tb("inverter busy; try again")'), ["S-B9SRC"])
M("M266", "mirror: save_time_text says 'failed' (a hazard word)", hdr(MIRROR, 'return save_refused("clock not NTP-synchronised this boot; the capture time would be untrusted")', 'return save_refused("clock sync failed this boot; the capture time would be untrusted")'), ["S-B9SRC"])


# ===========================================================================
# main
# ===========================================================================
def main() -> int:
    t_start = time.time()
    print("[0] inventory: the base, the firmware context, the helper self-tests")
    live = L.live_text()
    base, base_src, base_why = L.base_text(live)
    check("the pre-FB-B2 base firmware was derived and verified (git base commit / HEAD, sha256 == the chain's pinned fbb1 checkpoint; "
          f"source: {base_src or 'none'})", base is not None and L.chain.sha(base) == L.base_checkpoint(), base_why)
    live_lines = set(live.splitlines())
    changed_base_lines = sum(1 for ln in (base or "").splitlines() if ln not in live_lines)
    check("the live firmware is not the base (FB-B2 edited it) and only ADDS text to it: it is longer and at most 12 base lines (the declared in-place "
          "edits) are missing from it - a coarse sanity bound for the exact I-EDITS / I-DELTA pins below",
          base is not None and live != base and len(live) > len(base) and changed_base_lines <= 12, f"{changed_base_lines} base lines changed")
    P.set_base(base, base_why)
    real_cp = L.base_checkpoint
    L.base_checkpoint = lambda: "0" * 64
    try:
        wrong_pin = L.base_text(live)[0]
    finally:
        L.base_checkpoint = real_cp
    check("negative control: a base whose sha256 is not the chain's pinned fbb1 checkpoint is REFUSED (the base cannot be forged by the edits it is "
          "compared with)", wrong_pin is None)
    ctx = L.Ctx(live)
    check("the live firmware context parsed: 5 FB scripts, the dispatch tail, both housekeeping lambdas, the boot lambda, the api action and the arm switch located",
          all([ctx.save_lam, ctx.inv_lam, ctx.review_lam, ctx.review_final, ctx.save_p1, ctx.save_p2, ctx.release, ctx.tick1, ctx.tick2, ctx.boot,
               ctx.api_lam, ctx.arm is not None, ctx.interval is not None]) and len(ctx.fb) >= 55)

    # ---- helper self-tests (a wrong helper makes a pin vacuous) ----
    check("helper: strip_cpp removes // and /* */ comments but keeps string and character literals",
          L.strip_cpp('int a = 1; // c "x"\nconst char *s = "// not a comment"; /* x */ char c = \'"\';') ==
          'int a = 1; \nconst char *s = "// not a comment";  char c = \'"\';')
    check("helper: close_of / block_after / enclosing_headers / seq_find / diff_lines behave on a known sample",
          L.close_of("f(a, g(b), \"x)\")", 1) == 15
          and L.enclosing_headers("for (int i = 0; i < 2; i++) { if (x) { call(); } }", 40) == ["for (int i = 0; i < 2; i++)", "if (x)"]
          and P.seq_find("a(); b(); a();", ["a();", "a();"]) == [0, 8] and P.seq_find("a();", ["a();", "b();"])[-1] == -1
          and P.diff_lines("x = 1;\ny = 2;\n", "x = 1;\nz = 3;\ny = 2;\n") == ([], ["z = 3;"]))
    check("helper: mutate() raises unless the anchor occurs exactly the declared number of times (a mutant can never be a silent no-op); "
          "mutate_in() counts inside its region only",
          _raises(lambda: L.mutate("abc", "z", "y")) and _raises(lambda: L.mutate("abab", "ab", "x")) and L.mutate("abab", "ab", "x", 2) == "xx"
          and _raises(lambda: L.mutate_in("ab|ab", (0, 2), "ab", "x", 2)) and L.mutate_in("ab|ab", (0, 2), "ab", "x") == "x|ab")
    check("helper: assigned() sees plain / compound / increment / mutating-call writes of a global, rhs_of() the squashed right-hand sides, "
          "publish_args() the argument of a publish_state call",
          L.assigned("id(a) = 1; id(b) += 2; ++id(c); id(d).clear(); id(e)[3] = 4; if (id(f) == 1) {}") == {"a", "b", "c", "d", "e"}
          and L.rhs_of("id(a) = x + 1; id(a) = 2;", "a") == ["x+1", "2"]
          and L.publish_args("id(t).publish_state(res.c_str()); id(u).publish_state(\"a\");", "t") == ["res.c_str()"])
    check("helper: the struct parser reads the real headers (SaveGateInputs has arm_was_on first / time_trusted last; GateInputs flattens to 48 leaf fields)",
          (lambda st: [f for _t, f in st["SaveGateInputs"]][0] == "arm_was_on" and [f for _t, f in st["SaveGateInputs"]][-1] == "time_trusted"
           and len(L.flat_fields(st, "GateInputs")) == 48 and "bus.now_ms" in L.flat_fields(st, "GateInputs"))(
              {**L.parse_structs(L.CAP_HEADER.read_text(encoding="utf-8")), **L.parse_structs(L.SAVE_HEADER.read_text(encoding="utf-8"))}))
    check("helper: the lambda walker names lambdas structurally and finds the commit call in exactly the two expected lambdas",
          sorted(n for n, c_ in ctx.all_lams if "commit_transition_t" in c_) ==
          sorted([f"script:fallback_profile_capture_dispatch.then[{len(ctx.top) - 2}]", "script:fallback_profile_invalidate.then[0]"]))
    check("helper: the base context parses and has the FB-B1 shape (3 FB scripts, 30 other scripts, 2 api actions, 9 switches)",
          P.BASE["ctx"] is not None and len(P.BASE["ctx"].fw["script"]) == 33 and len(P.BASE["ctx"].api_actions) == 2 and len(P.BASE["ctx"].fw["switch"]) == 9)

    # ---- [S] the static pins on the live firmware ----
    print("")
    print("[S] static pins over the live firmware")
    t_s = time.time()
    live_results = P.run_all(ctx)
    for name in P.PINS:
        v = live_results[name]
        check(f"{name}: {P.LABELS[name]}", not v, "; ".join(v[:4]))
    t_s = time.time() - t_s

    # ---- [M] the mutation matrix ----
    print("")
    print("[M] mutation matrix (every mutant = a broken copy of the firmware text / header / mirror; every named pin must flag it)")
    t_m = time.time()
    killed, survivors, errors, total_flags = 0, [], [], 0
    used_by: dict[str, list[str]] = {n: [] for n in P.PINS}
    ids = [m[0] for m in MUTANTS]
    check(f"mutant ids are unique ({len(ids)} mutants)", len(set(ids)) == len(ids))
    for mid, desc, fn, dets in MUTANTS:
        try:
            out = fn(live)
            text, overrides = out if isinstance(out, tuple) else (out, {})
            if text == live and not overrides:
                raise AssertionError("the mutation changed nothing")
            mctx = L.Ctx(text, overrides)
        except Exception as ex:  # noqa: BLE001 - an invalid mutant is a failed check, never a skipped one
            errors.append(f"{mid}: {type(ex).__name__}: {str(ex)[:100]}")
            check(f"{mid}: {desc}", False, f"the mutant could not be built: {type(ex).__name__}: {str(ex)[:140]}")
            continue
        res = P.run_all(mctx, dets)
        # a detector that merely CRASHED on the damaged text did not catch the mutant: only a clean, explained violation is a kill
        raised = [d for d in dets if res[d] and all(x.startswith("detector raised") for x in res[d])]
        missed = [d for d in dets if not res[d]] + raised
        for d in dets:
            used_by[d].append(mid)
        total_flags += len(dets) - len(missed)
        if missed:
            survivors.append(f"{mid}: not (cleanly) flagged by {missed}")
        else:
            killed += 1
        check(f"{mid}: {desc} -> killed by {', '.join(dets)}", not missed,
              f"NOT cleanly flagged by {missed}" + (f" (crashed: {raised}: {res[raised[0]][0]})" if raised else "") if missed else "")
    t_m = time.time() - t_m
    check(f">= 60 mutants, each killed by EVERY detector named for it ({len(MUTANTS)} defined, {killed} killed, {total_flags} detector kills)",
          len(MUTANTS) >= 60 and killed == len(MUTANTS) and not errors, f"survivors {survivors}; invalid {errors}")
    P.set_base(None, "negative control")
    no_base = P.run_all(ctx, ["I-BASE", "I-DELTA", "I-EDITS", "I-WS", "S-DISPATCH", "S-WRITE"])
    P.set_base(base, base_why)
    check("negative control: with no base every base-relative pin (I-BASE, I-DELTA, I-EDITS, I-WS, S-DISPATCH, S-WRITE) FAILS - the suite never skips",
          all(no_base[n] for n in no_base), str({n: bool(v) for n, v in no_base.items()}))
    used_by["I-BASE"].append("control")
    unused = [d for d, m in used_by.items() if not m]
    check("every pin is the named killer of at least one mutant (no vacuous pin)", not unused, f"never exercised: {unused}")
    check("the unmutated firmware passes every pin the matrix uses (control)", all(not live_results[d] for d in P.PINS))

    total = time.time() - t_start
    print("")
    print(f"{NCHECKS[0]} checks in {total:.0f} s (static pins {t_s:.0f} s over {len(P.PINS)} detectors, mutation {t_m:.0f} s over {len(MUTANTS)} mutants, "
          f"{total_flags} detector kills, {len(unused)} unexercised pins)")
    if FAILURES:
        print(f"FAILED: {len(FAILURES)} check(s)")
        for f in FAILURES:
            print("  -", f)
        return 1
    print("ALL CHECKS PASSED")
    print("(Static text / parsed-YAML pins only: they prove the SHAPE of the write path - two commit call sites, no retry, no lock in INVALIDATE, one-shot arm,")
    print(" zero Modbus writes, no literal operator text. What the lambdas DO is proved by the scenario suites; the binary by `esphome compile`.)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
