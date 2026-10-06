#!/usr/bin/env python3
"""The FB-B2 STATIC pin detectors (text / parsed-YAML analysis of the firmware and the headers).

Each detector is `fn(ctx) -> list[str]` (violations; an empty list = pass) registered in PINS by a stable name, so the
mutation matrix of test_fallback_save_static_pins.py can run any detector against a deliberately broken copy of the firmware
text. Expectations are written HERE, independently of the YAML: from the locked design (FB_B2_IMPLEMENTATION_NOTES.md section 8.2 D1-D19, sections 3-7 of the same notes,
the header ecco_fallback_save.h contract) and from the FB-B0 / FB-B1 pins; derived quantities (base
counts, header constants) are measured from the base text / the headers, never typed twice.

NOT proved here (the behavioural suites and the native compile do that): what the lambdas DO at run time, the C++ semantics
of the headers, the compiled binary, hardware.
"""

from __future__ import annotations

import difflib
import re
import sys
from collections import Counter

import yaml

import _fbb2_static_lib as L
from _fbb2_static_lib import (assigned, block_after, call_args, close_of, enclosing_headers, has, ids_of, in_order, lam_of, literals,
                              log_calls, norm, order_of, parse_structs, flat_fields, publish_args, publishes, rhs_of, split_args,
                              sq, sq_block, strip_cpp, strip_code, var_assignments, var_assignment_count)

PINS: dict = {}
LABELS: dict = {}


def pin(name: str, label: str):
    def deco(fn):
        PINS[name] = fn
        LABELS[name] = label
        return fn
    return deco


def S(x: str) -> str:
    return re.sub(r"\s+", "", x)


# ===========================================================================
# The base (set by the suite before any detector runs)
# ===========================================================================
BASE = {"text": None, "ctx": None, "why": "base not set"}


def set_base(text: str | None, why: str = "") -> None:
    BASE["text"] = text
    BASE["why"] = why
    BASE["ctx"] = L.Ctx(text) if text else None


def base_violation() -> list[str]:
    return [] if BASE["ctx"] is not None else [f"no pre-FB-B2 base text: {BASE['why'] or 'not derived'} (the suite never skips)"]


# ===========================================================================
# Expected surface (written independently of the YAML)
# ===========================================================================
TS = {"B1": "fallback_profile_state_text", "B2": "fallback_profile_summary_text", "B3": "fallback_profile_review_text",
      "B4": "fallback_profile_review_id_text", "B5": "fallback_profile_review_slots_text", "B6": "fallback_profile_review_context_text",
      "B7": "fallback_profile_slots_text", "B8": "fallback_profile_context_text", "B9": "fallback_profile_last_result_text"}
B9 = TS["B9"]
ARM = "fallback_profile_arm"
NEW_SCRIPTS = ["fallback_profile_save", "fallback_profile_invalidate"]
NEW_INCLUDE = "include/ecco_fallback_save.h"
# (id, type, initial_value as the YAML scalar, or None for a std::array which takes none) - FB_B2_IMPLEMENTATION_NOTES.md section 8.2 D4 D5 D10 D11 D13
NEW_GLOBALS = [
    ("fallback_profile_exec_action", "std::string", '""'),
    ("fallback_profile_exec_target_id", "std::string", '""'),
    ("fallback_profile_exec_confirmation", "std::string", '""'),
    ("fallback_profile_exec_hb_ok", "bool", "false"),
    ("fallback_profile_arm_on_ms", "uint32_t", "0"),
    ("fallback_profile_save_unconfirmed", "bool", "false"),
    ("fallback_profile_save_unconfirmed_op", "uint8_t", "0"),
    ("fallback_profile_save_unconfirmed_gen", "uint32_t", "0"),
    ("fallback_durable_last_err", "uint32_t", "0"),
    ("fallback_durable_last_us", "uint32_t", "0"),
    ("fallback_profile_save_ctx_valid", "bool", "false"),
    ("fallback_profile_save_verified", "bool", "false"),
    ("fallback_profile_save_ctx_words", "std::array<uint16_t, 31>", None),
    ("fallback_profile_save_ctx_id", "uint64_t", "0"),
    ("fallback_profile_save_ctx_prior_class", "uint8_t", "0"),
    ("fallback_profile_save_ctx_prior_gen", "uint32_t", "0"),
    ("fallback_profile_save_ctx_prior_binding", "uint64_t", "0"),
    ("fallback_profile_save_ctx_replace_corrupt", "bool", "false"),
]
CTX_IDS = ["fallback_profile_save_ctx_valid", "fallback_profile_save_verified", "fallback_profile_save_ctx_words",
           "fallback_profile_save_ctx_id", "fallback_profile_save_ctx_prior_class", "fallback_profile_save_ctx_prior_gen",
           "fallback_profile_save_ctx_prior_binding", "fallback_profile_save_ctx_replace_corrupt"]
CTX_CLEAR = {"fallback_profile_save_ctx_valid": "false", "fallback_profile_save_verified": "false",
             "fallback_profile_save_ctx_words": "std::array<uint16_t,31>{}", "fallback_profile_save_ctx_id": "0",
             "fallback_profile_save_ctx_prior_class": "0", "fallback_profile_save_ctx_prior_gen": "0",
             "fallback_profile_save_ctx_prior_binding": "0", "fallback_profile_save_ctx_replace_corrupt": "false"}
EXPECTED_DELTAS = {"scripts": 2, "globals": 18, "api_actions": 1, "switches": 1, "includes": 1, "intervals": 0, "text_sensors": 0, "buttons": 0,
                   "numbers": 0, "selects": 0, "sensors": 0, "binary_sensors": 0, "substitutions": 0}
IDLE_COND = ("return !id(poll_inverter_configuration_dispatch).is_running() && !id(poll_inverter_telemetry).is_running() && "
             "id(inverter_modbus)->tx_buffer_empty() && !id(inverter_modbus)->tx_blocked();")
COUNTERS = ["manual_write_attempts", "reg244_apply_attempts", "reg244_restore_attempts", "free_power_start_attempts", "dump_start_attempts"]
FB_PREFIXES = ("fallback_profile_", "fallback_witness_", "fallback_durable_")
# the write-side symbols of the FB-B0 transaction writer and its mirror bookkeeping (nothing but the two commit lambdas may name them)
WRITE_SIDE = re.compile(r"commit_transition|write_one_|TxnResult|TxnOutcome|TXN_|PriorDesc|mirror_after|MirrorRecords|note_committed|KEY_BIT_|"
                        r"KEY_COMMITTED|make_provision|seal_provision|seal_profile|invalidate_profile|PROV_OP_|write_latched|ReadLatch|"
                        r"s_write_latched|next_seen_hw_gen|validate_transition|profile_with_generation")
OUTCOMES = ("on_response", "on_error", "on_no_response", "on_not_sent", "on_custom_response")
SECRETS = "secrets.yaml"


def _bus_table() -> dict:
    t = {}
    for f in ("manual_write_in_progress", "correction_in_progress", "verification_pending", "verification_read_active",
              "free_power_operation_in_progress", "free_power_recovery_force_in_progress", "free_power_recovery_accept_in_progress",
              "reg244_apply_in_progress", "dump_operation_in_progress", "fallback_profile_op_in_progress"):
        t["bus." + f] = f"id({f})"
    t["bus.fallback_profile_capture_dispatch_running"] = "id(fallback_profile_capture_dispatch).is_running()"
    t["bus.diag_write_lock_held"] = "id(diag_write_lock_held)"
    t["bus.diag_write_lock_since_ms"] = "id(diag_write_lock_since_ms)"
    t["bus.now_ms"] = "millis()"
    return t


def _gate_table() -> dict:
    t = _bus_table()
    t["boot_loaded"], t["fbs_slot"], t["probe_latch"] = ("id(fallback_profile_boot_loaded)", "id(fallback_profile_fbs_slot)", "id(fallback_profile_probe_latch)")
    for arm in ("free_power_write_enable", "dump_write_enable", "manual_config_write_enable"):
        t[arm] = f"id({arm}).state"
    for f in ("free_power_marker_boot_load", "free_power_recovery_metadata_corrupt", "free_power_snapshot_valid", "free_power_marker_state",
              "free_power_operator_needed", "free_power_active_persisted", "free_power_restore_requested"):
        t["fp." + f] = f"id({f})"
    for f in ("dump_marker_boot_load", "dump_recovery_metadata_corrupt", "dump_containment_state", "dump_snapshot_valid", "dump_marker_state",
              "dump_operator_needed", "dump_active_persisted", "dump_restore_requested"):
        t["dump." + f] = f"id({f})"
    for f in ("reg244_marker_boot_load", "reg244_recovery_metadata_corrupt", "reg244_snapshot_valid", "reg244_marker_state"):
        t["r244." + f] = f"id({f})"
    return t


BUS_RHS = _bus_table()
GATE_RHS = _gate_table()
FP_OPERATOR = {"free_power_recovery_review", "free_power_recovery_review_dispatch", "free_power_recovery_force_restore",
               "free_power_recovery_force_restore_dispatch", "free_power_recovery_accept_current_state",
               "free_power_recovery_accept_current_state_dispatch"}
RUN_SETS = {"fp.run_start": {"start_free_power_override"}, "fp.run_restore": {"restore_free_power_snapshot", "restore_free_power_snapshot_dispatch"},
            "fp.run_operator": FP_OPERATOR, "dump.run_start": {"start_dump_to_grid_override"}, "dump.run_restore": {"restore_dump_to_grid_snapshot"},
            "r244.run_apply": {"apply_reg244_settings"}, "r244.run_restore": {"restore_reg244_snapshot"}}
FINGERPRINT_ARGS = ["(uint32_t)id(manual_write_attempts)", "(uint32_t)id(reg244_apply_attempts)", "(uint32_t)id(reg244_restore_attempts)",
                    "(uint32_t)id(free_power_start_attempts)", "(uint32_t)id(dump_start_attempts)"]
SI_RHS = {"arm_was_on": "armed", "cand_valid": "c_valid", "cand_saveable": "c_saveable", "cand_id": "c_id", "cand_ms": "c_ms",
          "cand_prior_class": "c_prior_class", "cand_writes_fp": "c_writes_fp", "now_ms": "millis()",
          "writes_fp_now": "ecco_fbcap::writes_fingerprint(" + ",".join(FINGERPRINT_ARGS) + ")",
          "boot_loaded": "id(fallback_profile_boot_loaded)", "unconfirmed": "id(fallback_profile_save_unconfirmed)",
          "read_anomaly": "id(fallback_profile_read_anomaly)", "hb_ok": "id(fallback_profile_exec_hb_ok)",
          "time_trusted": "id(ntp_synced)&&id(ntp_time).now().is_valid()"}
PI_RHS = {"p_load": "lp", "p": "p", "p_stored_len": "dp.stored_len", "w_load": "lw", "w": "w", "w_stored_len": "dw.stored_len",
          "cls": "e.cls", "why": "e.why", "read_anomaly": "e.latch.read_anomaly", "unconfirmed": "id(fallback_profile_save_unconfirmed)",
          "seen_hw_gen": "e.seen_hw_gen", "cand_prior_class": "id(fallback_profile_save_ctx_prior_class)",
          "cand_prior_gen": "id(fallback_profile_save_ctx_prior_gen)", "cand_prior_binding": "id(fallback_profile_save_ctx_prior_binding)",
          "replace_corrupt": "id(fallback_profile_save_ctx_replace_corrupt)", "words": "id(fallback_profile_pass2)", "captured_epoch": "epoch"}
II_RHS = {"arm_was_on": "armed", "boot_loaded": "id(fallback_profile_boot_loaded)", "read_anomaly": "id(fallback_profile_read_anomaly)",
          "unconfirmed": "id(fallback_profile_save_unconfirmed)", "cls": "id(fallback_profile_class)", "p_load": "id(fallback_profile_load)",
          "p": "ecco_fallback::decode_profile(id(fallback_profile_bytes))", "w_load": "id(fallback_witness_load)",
          "w": "ecco_fbdurable::decode_provision(id(fallback_witness_bytes))", "seen_hw_gen": "id(fallback_profile_seen_hw_gen)",
          "tx_buffer_empty": "id(inverter_modbus)->tx_buffer_empty()", "tx_blocked": "id(inverter_modbus)->tx_blocked()",
          "fbs_slot": "id(fallback_profile_fbs_slot)", **BUS_RHS}
PJ_RHS = {"p_load": "lp", "p": "p", "p_stored_len": "dp.stored_len", "w_load": "lw", "w": "w", "w_stored_len": "dw.stored_len",
          "cls": "e.cls", "read_anomaly": "e.latch.read_anomaly", "unconfirmed": "id(fallback_profile_save_unconfirmed)",
          "seen_hw_gen": "e.seen_hw_gen",
          "target_id": "ecco_fbsave::parse_hex16(id(fallback_profile_exec_target_id).c_str(),id(fallback_profile_exec_target_id).size())"}
IN_RHS = {"present_seen": "id(fallback_profile_present_seen)", "read_anomaly": "id(fallback_profile_read_anomaly)",
          "seen_hw_gen": "id(fallback_profile_seen_hw_gen)", "baseline_valid": "id(fallback_profile_boot_loaded)",
          "last_p_load": "id(fallback_profile_load)", "last_p_bytes": "id(fallback_profile_bytes)",
          "last_w_load": "id(fallback_witness_load)", "last_w_bytes": "id(fallback_witness_bytes)", "p_load": "lp", "p": "p",
          "w_load": "lw", "w": "w", "healthy": "healthy"}
RI_RHS = {"words": "id(fallback_profile_pass2)", "ceiling_w": "${ecco_inverter_tou_power_ceiling_w}", "cls": "eff_cls",
          "read_anomaly": "e.latch.read_anomaly", "p_load": "lp", "p": "p", "p_stored_len": "dp.stored_len",
          "salt": "id(fallback_profile_boot_salt)", "seq_next": "id(fallback_profile_cand_seq)+1"}
RUN_IDS = {x for s in RUN_SETS.values() for x in s}
GATE_FOREIGN = {m for v in GATE_RHS.values() for m in re.findall(r"\bid\((\w+)\)", v)} | RUN_IDS


def fb_global_ids() -> set[str]:
    return {g[0] for g in NEW_GLOBALS}


# ===========================================================================
# Small structural helpers
# ===========================================================================
def kinds_of(actions) -> Counter:
    """Every action kind in an action tree (descending into `if` branches and Modbus reply handlers)."""
    c: Counter = Counter()
    for a in actions or []:
        if not isinstance(a, dict):
            c["<non-dict>"] += 1
            continue
        for k, b in a.items():
            c[k] += 1
            if k == "if" and isinstance(b, dict):
                c.update(kinds_of(b.get("then")))
                c.update(kinds_of(b.get("else")))
            elif k.startswith("modbus_client.") and isinstance(b, dict):
                for oc in OUTCOMES:
                    if oc in b and isinstance(b[oc], dict):
                        c.update(kinds_of(b[oc].get("then")))
    return c


def collect_reads(actions, conds=()):
    res = []
    for i, a in enumerate(actions or []):
        if not isinstance(a, dict) or len(a) != 1:
            res.append({"node": {"<damaged>": a}, "idx": i, "conds": conds})
            continue
        (k, b), = a.items()
        if k == "modbus_client.read_holding_registers":
            res.append({"node": b, "idx": i, "conds": conds})
        elif k == "if":
            cond = b["condition"]["lambda"] if isinstance(b["condition"], dict) else str(b["condition"])
            res += collect_reads(b.get("then"), conds + (cond,))
            res += collect_reads(b.get("else"), conds + ("!(" + cond + ")",))
    return res


def paths_of(actions):
    res = [[]]
    for a in actions or []:
        (k, b), = a.items()
        if k == "if":
            branches = paths_of(b.get("then")) + paths_of(b.get("else"))
            res = [p + [a] + q for p in res for q in branches]
        else:
            res = [p + [a] for p in res]
    return res


def seq_find(code: str, parts) -> list[int]:
    """Position of each squashed part in the squashed code, every search starting after the previous hit (-1 = missing)."""
    s = sq(code)
    out, at = [], 0
    for p in parts:
        i = s.find(sq(p), at)
        out.append(i)
        if i < 0:
            break
        at = i + len(sq(p))
    return out


def seq_ok(code: str, parts) -> bool:
    pos = seq_find(code, parts)
    return len(pos) == len(parts) and min(pos) >= 0


def lines_of(code: str) -> list[str]:
    return [ln.strip() for ln in strip_cpp(code).splitlines() if ln.strip()]


def diff_lines(old: str, new: str) -> tuple[list[str], list[str]]:
    a, b = lines_of(old), lines_of(new)
    removed: list[str] = []
    added: list[str] = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if tag != "equal":
            removed += a[i1:i2]
            added += b[j1:j2]
    return sorted(removed), sorted(added)


def count_member_calls(code: str, member: str) -> int:
    return len(re.findall(r"\.\s*%s\s*\(" % re.escape(member), strip_cpp(code)))


def block_of_if(code: str, head: str) -> str:
    """Squashed `{...}` block of the unique `if(...)` statement whose squashed head is `head` (ValueError when absent)."""
    return sq_block(code, head + "{")


# ===========================================================================
# [I] inventory: the surface FB-B2 adds, measured against the pre-FB-B2 base
# ===========================================================================
@pin("I-BASE", "the pre-FB-B2 base (git 65e4be5 / HEAD, accepted only if its sha256 is the chain's pinned fbb1 checkpoint) exists and parses; every delta is measured against it")
def d_base(c):
    return base_violation()


def _counts(fw: dict) -> dict:
    return {"scripts": len(fw["script"]), "globals": len(fw["globals"]), "api_actions": len((fw.get("api") or {}).get("actions") or []),
            "switches": len(fw.get("switch") or []), "includes": len((fw.get("esphome") or {}).get("includes") or []),
            "intervals": len(fw.get("interval") or []), "text_sensors": len(fw.get("text_sensor") or []),
            "buttons": len(fw.get("button") or []), "numbers": len(fw.get("number") or []), "selects": len(fw.get("select") or []),
            "sensors": len(fw.get("sensor") or []), "binary_sensors": len(fw.get("binary_sensor") or []),
            "substitutions": len(fw["_substitutions"])}


@pin("I-DELTA", "vs the base: globals +18, scripts +2 (save, invalidate), api actions +1, switches +1, includes +1; text sensors / buttons / intervals / every other entity count unchanged; every base item untouched, the new ones appended LAST")
def d_delta(c):
    v = base_violation()
    if v:
        return v
    f, b = c.fw, BASE["ctx"].fw
    delta = {k: _counts(f)[k] - _counts(b)[k] for k in EXPECTED_DELTAS}
    if delta != EXPECTED_DELTAS:
        v.append(f"deltas {delta} (want {EXPECTED_DELTAS})")
    # scripts
    if [s["id"] for s in f["script"]][:len(b["script"])] != [s["id"] for s in b["script"]]:
        v.append("the base script id order changed")
    new_sc = f["script"][len(b["script"]):]
    if [s.get("id") for s in new_sc] != NEW_SCRIPTS or any(s.get("mode") != "single" or list(s) != ["id", "mode", "then"] for s in new_sc):
        v.append(f"new scripts {[s.get('id') for s in new_sc]} (want {NEW_SCRIPTS}, appended last, mode single)")
    changed = {s["id"] for s, t in zip(f["script"], b["script"]) if s != t}
    if changed - {"fallback_profile_review", "fallback_profile_capture_dispatch"}:
        v.append(f"base scripts changed beyond the two FB-B1 scripts FB-B2 edits: {sorted(changed)}")
    # globals
    nb = len(b["globals"])
    if f["globals"][:nb] != b["globals"]:
        v.append("a base global changed, moved or was removed")
    new_g = f["globals"][nb:]
    want_ids = [g[0] for g in NEW_GLOBALS]
    if [g.get("id") for g in new_g] != want_ids:
        v.append(f"new global ids {[g.get('id') for g in new_g]} (want {want_ids}, appended at the END of globals)")
    for g, (i, t, init) in zip(new_g, NEW_GLOBALS):
        if g.get("type") != t:
            v.append(f"{i}: type {g.get('type')!r} (want {t!r})")
        if str(g.get("restore_value")).lower() not in ("no", "false"):
            v.append(f"{i}: restore_value {g.get('restore_value')!r} (must be no)")
        if init is None:
            if "initial_value" in g:
                v.append(f"{i}: a std::array global takes no initial_value")
        elif str(g.get("initial_value")) != init:
            v.append(f"{i}: initial_value {g.get('initial_value')!r} (want {init!r})")
        if set(g) - {"id", "type", "restore_value", "initial_value"}:
            v.append(f"{i}: unexpected keys {sorted(g)}")
    if sum(1 for g in f["globals"] if str(g.get("restore_value")).lower() == "yes") != sum(1 for g in b["globals"] if str(g.get("restore_value")).lower() == "yes"):
        v.append("the restore_value: yes set changed")
    # api
    fa, ba = (f.get("api") or {}).get("actions") or [], (b.get("api") or {}).get("actions") or []
    if fa[:len(ba)] != ba:
        v.append("a base api action changed or moved")
    if {k: x for k, x in (f.get("api") or {}).items() if k != "actions"} != {k: x for k, x in (b.get("api") or {}).items() if k != "actions"}:
        v.append("the api section changed beyond its actions list")
    # switches
    if f["switch"][:len(b["switch"])] != b["switch"]:
        v.append("a base switch changed")
    # includes
    if list(f["esphome"]["includes"]) != list(b["esphome"]["includes"]) + [NEW_INCLUDE]:
        v.append(f"includes tail {list(f['esphome']['includes'])[-3:]} (want the base's + {NEW_INCLUDE} appended LAST)")
    # esphome section beyond includes / the FB-B1 boot lambda
    fe, be = {k: x for k, x in f["esphome"].items() if k not in ("includes", "on_boot")}, {k: x for k, x in b["esphome"].items() if k not in ("includes", "on_boot")}
    if fe != be:
        v.append("the esphome section changed beyond includes")
    fb, bb = f["esphome"].get("on_boot") or {}, b["esphome"].get("on_boot") or {}
    if fb.get("priority") != bb.get("priority") or len(fb.get("then") or []) != len(bb.get("then") or []) or (fb.get("then") or [])[:3] != (bb.get("then") or [])[:3]:
        v.append("on_boot priority / item count / items 1-3 changed")
    # everything else byte-identical to the base
    for k in f:
        if k.startswith("_") or k in ("esphome", "api", "globals", "switch", "script", "interval"):
            continue
        if f[k] != b.get(k):
            v.append(f"top-level section {k!r} changed")
    # intervals: only the housekeeping interval differs
    fi, bi = f.get("interval") or [], b.get("interval") or []
    if len(fi) == len(bi):
        diff = [i for i, (x, y) in enumerate(zip(fi, bi)) if x != y]
        if diff != [c.interval_index]:
            v.append(f"intervals that differ from the base: {diff} (want only the housekeeping interval {c.interval_index})")
    return v


# the declared FB-B1 in-place edits (D11 / D12 / yaml_impl_report), as removed / added normalised lines
EDIT_BOOT = ([("ecco_fbcap::TextBuf t = ecco_fbcap::b2_text(lp, p, lw, w, e.why, 0, 0);")],
             [("ecco_fbcap::TextBuf t = ecco_fbcap::b2_text(lp, p, lw, w, e.why, id(fallback_durable_last_err), id(fallback_durable_last_us));")])
EDIT_GATE = ([], ["id(fallback_profile_arm).turn_off();"])
CTX_CLEAR_LINES = ["id(fallback_profile_save_ctx_valid) = false;", "id(fallback_profile_save_verified) = false;",
                   "id(fallback_profile_save_ctx_words) = std::array<uint16_t, 31>{};", "id(fallback_profile_save_ctx_id) = 0;",
                   "id(fallback_profile_save_ctx_prior_class) = 0;", "id(fallback_profile_save_ctx_prior_gen) = 0;",
                   "id(fallback_profile_save_ctx_prior_binding) = 0;", "id(fallback_profile_save_ctx_replace_corrupt) = false;"]
EDIT_CTX = ([], CTX_CLEAR_LINES)
EDIT_FINAL = ([
    "const char *cls_name = ecco_fbcap::epc_name(e.cls);",
    "ecco_fbcap::TextBuf t = ecco_fbcap::b2_text(lp, p, lw, w, e.why, 0, 0);",
    "ri.cls = e.cls;",
    "id(fallback_profile_cand_prior_class) = e.cls;",
    "ecco_fbcap::TextBuf t = ecco_fbcap::b3_text(id(fallback_profile_capture_state), true, e.cls,",
    "res = ecco_fbcap::not_saveable_text(v.refusals, id(fallback_profile_pass2), e.cls, e.latch.read_anomaly);"], [
    "if (id(fallback_profile_op_purpose) == ecco_fbsave::PURPOSE_SAVE) return;",
    "const uint8_t eff_cls = ecco_fbsave::overlay_class(e.cls, id(fallback_profile_save_unconfirmed));",
    "const char *cls_name = ecco_fbcap::epc_name(eff_cls);",
    "ecco_fbcap::TextBuf t = ecco_fbcap::b2_text(lp, p, lw, w, e.why, id(fallback_durable_last_err), id(fallback_durable_last_us));",
    "ri.cls = eff_cls;",
    "id(fallback_profile_arm).turn_off();",
    "id(fallback_profile_cand_prior_class) = eff_cls;",
    "ecco_fbcap::TextBuf t = ecco_fbcap::b3_text(id(fallback_profile_capture_state), true, eff_cls,",
    "res = ecco_fbcap::not_saveable_text(v.refusals, id(fallback_profile_pass2), eff_cls, e.latch.read_anomaly);"])


@pin("I-EDITS", "FB-B2's edits of FB-B1 code are EXACTLY the declared ones (D11 / D12): every other lambda of the firmware is byte-identical to the base; the five edited FB-B1 lambdas differ by precisely the declared removed / added lines")
def d_edits(c):
    v = base_violation()
    if v:
        return v
    bc = BASE["ctx"]
    new_names = ("script:fallback_profile_save", "script:fallback_profile_invalidate", "api:fallback_profile_execute", "switch:fallback_profile_arm")
    iv = c.interval_index
    new_tick2 = f"interval[{iv}].then[1]"
    audited = {"esphome.on_boot.then[3]": EDIT_BOOT, "script:fallback_profile_review.then[0]": EDIT_GATE, f"interval[{iv}].then[0]": EDIT_CTX}
    live = dict(c.all_lams)
    base = dict(bc.all_lams)
    disp = "script:fallback_profile_capture_dispatch.then["
    # dispatch lambdas 0..3 (and everything nested below them) are compared by name; indices >= 4 are audited structurally below
    def dispatch_head(n):
        return n.startswith(disp) and int(re.match(r"\w+:\w+\.then\[(\d+)\]", n).group(1)) < 4

    for n, code in base.items():
        if n.startswith(disp) and not dispatch_head(n):
            continue
        if n not in live:
            v.append(f"base lambda {n} is gone")
            continue
        if n in audited:
            rem, add = diff_lines(code, live[n])
            want_rem, want_add = sorted(audited[n][0]), sorted(audited[n][1])
            if rem != want_rem or add != want_add:
                v.append(f"{n}: removed {rem} added {add} (want removed {want_rem} added {want_add})")
        elif live[n] != code:
            v.append(f"{n}: a lambda the declared FB-B2 edit list does not include changed")
    for n in live:
        if n in base or n in ("<root>",):
            continue
        if n.startswith(disp) and not dispatch_head(n):
            continue
        if n.startswith(new_names) or n == new_tick2:
            continue
        v.append(f"new lambda outside the declared FB-B2 surface: {n}")
    # the dispatch tail: base [.. REVIEW_FINAL, RELEASE] -> live [.. drain if, REVIEW_FINAL, SAVE p1, SAVE p2, RELEASE]
    bt, ft = bc.top, c.top
    if len(bt) != 6 or len(ft) != 9:
        v.append(f"dispatch top-level item counts base {len(bt)} live {len(ft)} (want 6 and 9)")
        return v
    if ft[:4] != bt[:4]:
        v.append("dispatch items 0-3 (init, idle wait, idle follow-up, the four-read nest) changed")
    rem, add = diff_lines(lam_of(bt[4]), c.review_final)
    if (rem, add) != (sorted(EDIT_FINAL[0]), sorted(EDIT_FINAL[1])):
        v.append(f"REVIEW_FINAL edits: removed {rem} added {add} (want removed {sorted(EDIT_FINAL[0])} added {sorted(EDIT_FINAL[1])})")
    rem, add = diff_lines(lam_of(bt[5]), c.release)
    if (rem, add) != ([], sorted(CTX_CLEAR_LINES)):
        v.append(f"RELEASE edits: removed {rem} added {add} (want only the SAVE context clears)")
    if c.inv_cand != bc.inv_cand:
        v.append("fallback_profile_invalidate_candidate changed")
    return v


# ===========================================================================
# [I] the zero-write structural proof (write-surface analyzer) and the Modbus node census
# ===========================================================================
def _paths_ops(fw_text: str) -> dict:
    return chain.per_path_ops(fw_text)


import _scope_chain as chain  # noqa: E402


@pin("I-WS", "zero-write structural proof: the write-surface analyzer finds 64 reads / 52 writes (== base, 0 added), the only changed op path is the SAVE gate (no ops), the dispatch keeps its four reads, FB paths have no write, no Modbus node / script / bus finding added")
def d_writesurface(c):
    v = base_violation()
    if v:
        return v
    base_text = BASE["text"]
    new, old = chain.analyze_text(c.text), chain.analyze_text(base_text)
    nops = [o.kind for p in new["paths"] for o in p.ops]
    oops = [o.kind for p in old["paths"] for o in p.ops]
    if nops.count("write") != oops.count("write") or nops.count("read") != oops.count("read"):
        v.append(f"Modbus ops reads/writes {nops.count('read')}/{nops.count('write')} (base {oops.count('read')}/{oops.count('write')}: FB-B2 adds none)")
    if (nops.count("read"), nops.count("write")) != (64, 52):
        v.append(f"absolute census {nops.count('read')} reads / {nops.count('write')} writes (want 64 / 52)")
    nmap = {p.name: tuple((o.kind, o.start_address, o.count) for o in p.ops) for p in new["paths"]}
    omap = {p.name: tuple((o.kind, o.start_address, o.count) for o in p.ops) for p in old["paths"]}
    changed = sorted(k for k in set(nmap) | set(omap) if nmap.get(k) != omap.get(k))
    if changed != ["fallback_profile_save"]:
        v.append(f"analyzer op paths that changed: {changed} (want only the new SAVE gate path)")
    if nmap.get("fallback_profile_save") != ():
        v.append(f"the SAVE gate path has ops {nmap.get('fallback_profile_save')}")
    if "fallback_profile_invalidate" in nmap:
        v.append("the INVALIDATE script is an analyzer path (it must not acquire the write mutex or dispatch)")
    four = (("read", 230, 3), ("read", 241, 53), ("read", 230, 3), ("read", 241, 53))
    if nmap.get("fallback_profile_capture_dispatch") != four:
        v.append(f"the dispatch ops {nmap.get('fallback_profile_capture_dispatch')} (want the four FB-B1 reads)")
    for name, ops in nmap.items():
        if (name.startswith("fallback_profile_")) and any(o[0] == "write" for o in ops):
            v.append(f"{name} has a write op")
    if new["bus_access_findings"] or new["unknown_extent_writes"]:
        v.append(f"bus findings {new['bus_access_findings']} / unknown-extent writes {new['unknown_extent_writes']}")
    return v


@pin("I-MODBUS", "no new Modbus node anywhere: the dispatch has exactly the four distinct FC03 reads (230/3, 241/53, 230/3, 241/53), five reply handlers each, no write action; no FB-B2 script / api action / switch / interval has a modbus_client action")
def d_modbus_nodes(c):
    v = base_violation()
    def census(fw):
        n: Counter = Counter()
        def rec(x):
            if isinstance(x, dict):
                for k, y in x.items():
                    if isinstance(k, str) and k.startswith("modbus_client."):
                        n[k] += 1
                    rec(y)
            elif isinstance(x, list):
                for y in x:
                    rec(y)
        rec({k: x for k, x in fw.items() if not k.startswith("_")})
        return n
    if BASE["ctx"] is not None and census(c.fw) != census(BASE["ctx"].fw):
        v.append(f"modbus_client action census {dict(census(c.fw))} (base {dict(census(BASE['ctx'].fw))})")
    reads = collect_reads(c.top)
    shapes = [(r["node"].get("modbus_id"), r["node"].get("address"), r["node"].get("start_address"), r["node"].get("count")) for r in reads]
    if shapes != [("inverter_modbus", 1, 230, 3), ("inverter_modbus", 1, 241, 53), ("inverter_modbus", 1, 230, 3), ("inverter_modbus", 1, 241, 53)]:
        v.append(f"dispatch read shapes {shapes}")
    for r in reads:
        have = [oc for oc in OUTCOMES if oc in r["node"]]
        if have != list(OUTCOMES):
            v.append(f"a read node has handlers {have} (want all five)")
    kinds = kinds_of(c.top)
    if sum(n for k, n in kinds.items() if k.startswith("modbus_client.")) != 4 or kinds.get("modbus_client.read_holding_registers") != 4:
        v.append(f"dispatch modbus actions {dict((k, n) for k, n in kinds.items() if k.startswith('modbus_client.'))}")
    for label, node in (("save", c.save_then), ("invalidate", c.inv_then), ("api", c.api_act.get("then")), ("arm", c.arm), ("interval", (c.interval or {}).get("then"))):
        text = repr(node)
        if "modbus_client" in text:
            v.append(f"{label}: a modbus_client action")
    return v


# ===========================================================================
# [X] exclusivity X1-X4 (the FB-B2 form)
# ===========================================================================
NVS_WRITE_RE = re.compile(r"\bnvs_(?:set_\w+|erase\w*|commit)\b")


def code_files(c=None) -> dict:
    """Every C/C++ source under firmware/ (path -> LF text); the overrides of the firmware context (header mutants) replace the disk copy."""
    out = {}
    for p in sorted((L.ROOT / "firmware").rglob("*")):
        if p.is_file() and p.suffix in (".h", ".hpp", ".c", ".cpp", ".cc") and ".esphome" not in p.parts:
            out[p.relative_to(L.ROOT).as_posix()] = p.read_text(encoding="utf-8")
    if c is not None:
        for rel, text in c.overrides.items():
            if rel in out:
                out[rel] = text
    return out


def firmware_yamls(live_text: str) -> dict:
    """firmware/*.yaml (never secrets.yaml, never opened) with the production firmware replaced by the text under test."""
    out = {}
    for p in sorted((L.ROOT / "firmware").glob("*.yaml")):
        if p.name == SECRETS:
            continue
        out[p.relative_to(L.ROOT).as_posix()] = p.read_text(encoding="utf-8")
    out[L.FW_REL] = live_text
    return out


def _all_lambda_codes(yaml_text: str) -> list[tuple[str, str]]:
    return L.walk_lambdas(L.ds.load_firmware_text(yaml_text))


_YAML_LAMBDA_CACHE: dict = {}


def yaml_lambdas(rel: str, text: str) -> list[tuple[str, str]]:
    key = (rel, hash(text))
    if key not in _YAML_LAMBDA_CACHE:
        _YAML_LAMBDA_CACHE[key] = _all_lambda_codes(text)
    return _YAML_LAMBDA_CACHE[key]


def x1_violations(files: dict, yamls: dict) -> list[str]:
    bad = []
    for rel, text in files.items():
        hits = NVS_WRITE_RE.findall(strip_code(text))
        if rel == "firmware/include/ecco_fallback_durable.h":
            if hits != ["nvs_set_blob"] or len(re.findall(r"\bnvs_set_blob\s*\(", strip_code(text))) != 1:
                bad.append(f"{rel}: nvs write names {hits} (want exactly one nvs_set_blob call)")
        elif hits:
            bad.append(f"{rel}: {hits}")
    for rel, text in yamls.items():
        for name, code in yaml_lambdas(rel, text):
            s = strip_cpp(code)
            rest = re.sub(r"ecco_fbdurable::nvs_healthy\b", "", s)
            if re.search(r"\bnvs_", rest):
                bad.append(f"{rel}:{name}: a lambda names nvs_ outside ecco_fbdurable::nvs_healthy")
            rest = re.sub(r"ecco_fbdurable::EspNvs\s+nvs\s*;", "", rest)
            rest = re.sub(r"\(\s*nvs\s*,", "(", rest)
            if re.search(r"\bnvs\b", rest):
                bad.append(f"{rel}:{name}: the EspNvs object is used other than as a read_direct_t / commit_transition_t argument")
    return bad


@pin("X1", "nvs_set_blob / nvs_erase_* / nvs_set_* / nvs_commit only in ecco_fallback_durable.h as exactly ONE nvs_set_blob call; no firmware YAML lambda names nvs_ outside ecco_fbdurable::nvs_healthy; the EspNvs object only as a read_direct_t / commit_transition_t argument")
def d_x1(c):
    return x1_violations(code_files(c), firmware_yamls(c.text))


def x2_violations(model_text: str, others: dict) -> list[str]:
    code = strip_code(model_text)
    inst = re.findall(r"\bwrite_one_<\s*(\w+)\s*,\s*(\w+)\s*>\s*\(", code)
    spec = re.findall(r"template<> struct WriteTarget<(\w+), (\w+)> \{\s*static constexpr bool allowed = true;", code)
    want = [("FailbackProvisionV1", "FAILBACK_PROVISION_KEY"), ("FallbackProfileV1", "FALLBACK_PROFILE_KEY")]
    bad = []
    if inst != want:
        bad.append(f"write_one_ instantiations {inst} (want FBW then FBP only)")
    if sorted(spec) != sorted(want):
        bad.append(f"WriteTarget specialisations {spec}")
    if len(re.findall(r"\.set_blob\(", code)) != 1:
        bad.append("set_blob call sites in the model")
    if any("FailbackStateV1" in a or "FAILBACK_STATE_KEY" in b for a, b in inst + spec):
        bad.append("an FBS (FailbackStateV1 / FAILBACK_STATE_KEY) write target")
    for rel, text in others.items():
        if re.search(r"\bwrite_one_\s*<|\bWriteTarget\s*<", strip_code(text)):
            bad.append(f"{rel} names write_one_ / WriteTarget")
    return bad


@pin("X2", "write_one_< instantiated exactly twice (FBW then FBP), the only two WriteTarget specialisations, one set_blob call, NO FBS write target; no other firmware file (nor any YAML lambda) names write_one_ / WriteTarget")
def d_x2(c):
    files = code_files(c)
    model = files.get("firmware/include/ecco_fallback_durable_model.h", "")
    others = {r: t for r, t in files.items() if not r.endswith("ecco_fallback_durable_model.h")}
    yl = {f"{rel}:{n}": code for rel, text in firmware_yamls(c.text).items() for n, code in yaml_lambdas(rel, text)}
    return x2_violations(model, {**others, **yl})


X3_APIS = re.compile(r"preference_for\s*<|commit_record|load_record|load_record_status|make_preference|make_entity_preference|load_from_key|"
                     r"ESPPreferenceObject|global_preferences")
X3_FB = re.compile(r"FALLBACK_PROFILE_TAG|FAILBACK_PROVISION_TAG|FAILBACK_STATE_TAG|FALLBACK_PROFILE_KEY|FAILBACK_PROVISION_KEY|"
                   r"FAILBACK_STATE_KEY|1609458070|1000595297|2156168643")


def x3_violations(files: dict, yamls: dict) -> list[str]:
    bad = []
    units = [(rel, L.strip_cpp(t)) for rel, t in files.items()]
    units += [(f"{rel}:{n}", L.strip_cpp(code)) for rel, text in yamls.items() for n, code in yaml_lambdas(rel, text)]
    for rel, code in units:
        for piece in re.split(r"[;\n]", code):
            if X3_APIS.search(piece) and X3_FB.search(piece):
                bad.append(f"{rel}: {piece.strip()[:90]}")
    return bad


@pin("X3", "no preference_for< / commit_record / load_record(_status) / make_(entity_)preference / load_from_key / ESPPreferenceObject on an FB tag or key (1609458070 / 1000595297 / 2156168643) in any firmware file or lambda; no esphome preference object in any FB lambda; no FB key or tag string anywhere in the YAML text")
def d_x3(c):
    v = x3_violations(code_files(c), firmware_yamls(c.text))
    for n, code in c.fb.items():
        if re.search(r"ESPPreferenceObject|make_preference|global_preferences|preference_for|\bcommit_record\b|\bload_record\b|load_record_status", strip_cpp(code)):
            v.append(f"{n}: an esphome / ecco_durable preference object")
    raw = "\n".join(ln for ln in c.text.splitlines() if not ln.lstrip().startswith("#"))
    for key in ("1609458070", "1000595297", "2156168643", "0x5FEE6196", "0x3BA3DF61", "0x808485C3"):
        if key.lower() in raw.lower():
            v.append(f"the firmware YAML text names the durable key {key}")
    return v


def _commit_sites(c) -> dict[str, int]:
    return {n: strip_cpp(code).count("commit_transition_t") for n, code in c.all_lams if "commit_transition_t" in strip_cpp(code)}


def _raw_noncomment_count(text: str, token: str) -> int:
    n = 0
    for ln in text.splitlines():
        s = ln.lstrip()
        if s.startswith("#"):
            continue
        s = ln.split("//")[0]
        n += s.count(token)
    return n


@pin("X4a", "commit_transition_t( appears in EXACTLY two firmware lambdas: SAVE_FINAL part 2 and the INVALIDATE lambda - never in on_boot, any interval, FB-C, REVIEW_FINAL, SAVE_FINAL part 1, the gate scripts, the housekeeping, the api action; two code lines in the whole YAML text; no FB header outside the FB-B0 model names it")
def d_x4a(c):
    v = []
    sites = _commit_sites(c)
    want = {c.name_of(c.save_p2): 1, c.name_of(c.inv_lam): 1}
    if set(sites) != set(want) or any(n != 1 for n in sites.values()) or "?" in want:
        v.append(f"commit_transition_t call sites by lambda {sites} (want exactly {want})")
    if c.name_of(c.save_p2) != f"script:fallback_profile_capture_dispatch.then[{len(c.top) - 2}]" or c.name_of(c.inv_lam) != "script:fallback_profile_invalidate.then[0]":
        v.append("the two commit lambdas are not SAVE_FINAL part 2 (the second-to-last dispatch item) and the INVALIDATE script's lambda")
    if _raw_noncomment_count(c.text, "commit_transition_t") != 2:
        v.append(f"{_raw_noncomment_count(c.text, 'commit_transition_t')} non-comment `commit_transition_t` occurrences in the YAML text (want 2)")
    for rel, text in code_files(c).items():
        if rel.endswith("ecco_fallback_durable_model.h"):
            continue
        if "commit_transition_t" in strip_code(text):
            v.append(f"{rel} names commit_transition_t (the writer is called from the two YAML lambdas only)")
    for rel, text in firmware_yamls(c.text).items():
        if rel != L.FW_REL and "commit_transition_t" in text:
            v.append(f"{rel} names commit_transition_t")
    return v


COMMIT_ARGS = ["nvs", "plan.w_new", "w", "ecco_fbdurable::PriorDesc{lw,dw.stored_len}", "plan.p_new", "p",
               "ecco_fbdurable::PriorDesc{lp,dp.stored_len}", "r"]
LOOP_RX = re.compile(r"\b(?:for|while|do|goto)\b|\bretry\w*|\bagain\b|\battempt\w*\b")


@pin("X4b", "exactly ONE commit_transition_t per commit lambda, no loop / goto / retry construct in either, never inside a loop; its record arguments are exactly (nvs, plan.w_new, w, PriorDesc{lw, ...}, plan.p_new, p, PriorDesc{lp, ...}, r); `plan` comes only from plan_save / plan_invalidate and is never edited; the YAML builds no record itself")
def d_x4b(c):
    v = []
    for who, lam, planner in (("SAVE_FINAL part 2", c.save_p2, "ecco_fbsave::plan_save"), ("INVALIDATE", c.inv_lam, "ecco_fbsave::plan_invalidate")):
        code = strip_cpp(lam)
        if code.count("commit_transition_t") != 1:
            v.append(f"{who}: {code.count('commit_transition_t')} commit_transition_t calls (want exactly 1)")
            continue
        if LOOP_RX.search(re.sub(r'"[^"]*"', '""', code)):
            v.append(f"{who}: a loop / goto / retry construct ({LOOP_RX.search(code).group(0)!r})")
        try:
            args = call_args(lam, r"ecco_fbdurable::commit_transition_t")
        except ValueError:
            v.append(f"{who}: the commit call is not parseable")
            continue
        if args != COMMIT_ARGS:
            v.append(f"{who}: commit_transition_t arguments {args} (want {COMMIT_ARGS})")
        pos = code.index("commit_transition_t")
        loops = [h for h in enclosing_headers(code, pos) if re.match(r"^(?:for|while|do)\b", h) or h.endswith("do")]
        if loops:
            v.append(f"{who}: the commit sits inside a loop {loops}")
        if len(re.findall(r"\b%s\s*\(" % re.escape(planner), code)) != 1 or not has(lam, f"const ecco_fbsave::Plan plan = {planner}("):
            v.append(f"{who}: `plan` is not built by exactly one {planner}(...) call")
        if re.search(r"\bplan\s*\.\s*[\w.]+\s*(?:=(?!=)|\+=|-=|\|=|&=)|\bplan\s*=(?!=)", code.replace("const ecco_fbsave::Plan plan =", "")):
            v.append(f"{who}: the plan is edited after it was built")
        if re.search(r"\bp_new\b|\bw_new\b", re.sub(r"plan\.(?:p_new|w_new)", "", code)):
            v.append(f"{who}: a p_new / w_new record that does not come from `plan`")
        if "plan.code" not in code or "PLAN_OK" not in code:
            v.append(f"{who}: the plan code is not checked against PLAN_OK")
    for n, code in c.fb.items():
        s = strip_cpp(code)
        if re.search(r"make_provision|seal_provision|seal_profile|invalidate_profile|profile_with_generation|classify_key_outcome|readback_class", s):
            v.append(f"{n}: the YAML builds / seals / invalidates a record itself (that lives in plan_save / plan_invalidate)")
    return v


READ_SIDE_FBD = {"EspNvs", "ReadDiag", "FailbackProvisionV1", "read_direct_t", "nvs_healthy", "FALLBACK_PROFILE_KEY", "FAILBACK_PROVISION_KEY",
                 "FAILBACK_STATE_KEY", "encode_provision", "decode_provision", "classify_witness", "compose_profile_class",
                 "EffectiveProfile", "fbs_slot"}


@pin("X4c", "EspNvs only in the boot lambda, the REVIEW gate / REVIEW_FINAL and the three FB-B2 lambdas that read or write (SAVE_FINAL part 1 for the lazy marker probes, part 2, INVALIDATE); every write-side ecco_fbdurable symbol (TxnResult, mirror_after, note_committed, PROV_OP_*, ...) only in SAVE_FINAL part 2 and INVALIDATE; REVIEW code names no ecco_fbsave symbol but overlay_class / PURPOSE_SAVE")
def d_x4c(c):
    v = []
    users = sorted(n for n, code in c.all_lams if "EspNvs" in strip_cpp(code))
    want = sorted({"esphome.on_boot.then[3]", "script:fallback_profile_review.then[0]", c.name_of(c.review_final), c.name_of(c.save_p1),
                   c.name_of(c.save_p2), c.name_of(c.inv_lam)})
    if users != want:
        v.append(f"EspNvs used by {users} (want {want})")
    writers = {c.name_of(c.save_p2), c.name_of(c.inv_lam)}
    for n, code in c.all_lams:
        s = strip_cpp(code)
        m = WRITE_SIDE_RX.search(s)
        if m and n not in writers:
            v.append(f"{n}: write-side symbol {m.group(0)!r} outside the two commit lambdas")
        if "ecco_fbdurable::" in s:
            names = set(re.findall(r"ecco_fbdurable::(\w+)", s))
            if n not in writers and names - READ_SIDE_FBD:
                v.append(f"{n}: ecco_fbdurable symbols {sorted(names - READ_SIDE_FBD)} beyond the read side")
    for who, lam in (("REVIEW gate", c.review_lam), ("REVIEW_FINAL", c.review_final), ("boot", c.boot), ("tick 1", c.tick1)):
        syms = set(re.findall(r"ecco_fbsave::(\w+)", strip_cpp(lam)))
        if who == "REVIEW_FINAL":
            if syms != {"overlay_class", "PURPOSE_SAVE"}:
                v.append(f"REVIEW_FINAL names ecco_fbsave symbols {sorted(syms)} (want overlay_class + PURPOSE_SAVE)")
        elif syms:
            v.append(f"{who} names ecco_fbsave symbols {sorted(syms)}")
    if not any("commit_transition_t" in strip_cpp(code) and "EspNvs" in strip_cpp(code) for _n, code in c.all_lams):
        v.append("the commit lambdas do not declare their own EspNvs")
    return v


WRITE_SIDE_RX = WRITE_SIDE


GUARD_COND = S("if (!ecco_fallback::profile_invalidate_permitted(in.p) || !ecco_fbdurable::invalidate_generation_permitted("
               "in.p.generation, wc, in.w.hw_generation, in.seen_hw_gen)) return plan_refuse(r, PLAN_GENERATION,")


def save_header_violations(htext: str) -> list[str]:
    """BLK-51 + purity pins over the text of firmware/include/ecco_fallback_save.h."""
    v = []
    h = strip_code(htext)
    calls = [m.start() for m in re.finditer(r"\binvalidate_profile\s*\(", h)]
    if len(calls) != 1:
        v.append(f"the header calls invalidate_profile {len(calls)} times (want exactly 1, inside plan_invalidate)")
    m = re.search(r"constexpr Plan plan_invalidate\(const InvalidatePlanInputs &in\) \{", h)
    if not m:
        v.append("plan_invalidate not found")
    else:
        body = S(h[m.end() - 1:close_of(h, m.end() - 1) + 1])
        at = body.find("invalidate_profile(")
        g = body.find(GUARD_COND)
        if at < 0 or g < 0 or g > at:
            v.append("invalidate_profile( is not behind the exact refusal `!profile_invalidate_permitted(p) || !invalidate_generation_permitted(g, wc, hw, seen)` in plan_invalidate")
        if len(calls) == 1 and not (m.end() <= calls[0] <= close_of(h, m.end() - 1)):
            v.append("the one invalidate_profile call is outside plan_invalidate")
    for tok in (r"commit_transition", r"write_one_", r"set_blob", r"\bnvs_", r"ESP_LOG", r"\bid\(", r"millis\(", r"random", r"EspNvs", r"global_preferences"):
        if re.search(tok, h):
            v.append(f"the FB-B2 header names {tok!r} (it must stay pure: it never calls the writer or touches storage / the clock / the logger)")
    # BLK-64 (zero reboot) at the header level: no restart / reboot / power-state CODE token (the operator TEXT may say 'reboot the dongle': string
    # literal content is removed by strip_code; the UPPER-case enum names TXN_UNKNOWN_REBOOT / KEY_UNKNOWN_REBOOT are not call tokens)
    m = re.search(r"esp_restart|arch_restart|\breboot\w*|\brestart\w*|App\s*\.|esp_deep_sleep|deep_sleep|safe_reboot|software_reset", h)
    if m:
        v.append(f"the FB-B2 header names the reboot / power-state token {m.group(0)!r} (BLK-64: FB-B2 never reboots the device)")
    return v


@pin("X4d", "invalidate_profile( is never called from YAML; in the header it is called only inside plan_invalidate, after the EXACT refusal on profile_invalidate_permitted || invalidate_generation_permitted (BLK-51); the header calls no writer, no nvs, no logger, no id(), no clock")
def d_x4d(c):
    v = []
    for n, code in c.all_lams:
        if "invalidate_profile" in strip_cpp(code):
            v.append(f"{n}: names invalidate_profile (BLK-51: only plan_invalidate may call it)")
    return v + save_header_violations(c.file("firmware/include/ecco_fallback_save.h"))


# ===========================================================================
# [S] INVALIDATE (D1 / D2) and SAVE_FINAL (D3 / D7) structure
# ===========================================================================
WAITS_RX = re.compile(r"wait_until|\bdelay\s*\(|\byield\b|vTaskDelay|\bsleep\w*\s*\(|\bscript\s*\.|\.\s*(?:stop|wait)\s*\(")


@pin("S-INV", "INVALIDATE is ONE synchronous lambda (D1): single lambda action, no wait / delay / script.execute / dispatch / Modbus access; it never assigns manual_write_in_progress or op_in_progress (D2); the in-flight gate is its first statement; the bus-idle check is the LAST statement before the writer; it executes only the IE2 candidate invalidation")
def d_invalidate(c):
    v = []
    if [list(a)[0] for a in c.inv_then] != ["lambda"] or c.inv.get("mode") != "single":
        v.append(f"INVALIDATE script shape {[list(a)[0] for a in c.inv_then]} mode {c.inv.get('mode')!r} (want one lambda, mode single)")
    kinds = kinds_of(c.inv_then)
    if set(kinds) - {"lambda"}:
        v.append(f"INVALIDATE has actions {sorted(set(kinds) - {'lambda'})}")
    code = strip_cpp(c.inv_lam)
    m = WAITS_RX.search(code)
    if m:
        v.append(f"INVALIDATE lambda contains {m.group(0)!r}")
    if EXEC_RX.findall(code) != ["fallback_profile_invalidate_candidate"]:
        v.append(f"INVALIDATE executes {EXEC_RX.findall(code)} (want only the one IE2 fallback_profile_invalidate_candidate)")
    bad = assigned(c.inv_lam) & {"manual_write_in_progress", "fallback_profile_op_in_progress", "fallback_profile_op_purpose", "fallback_profile_step",
                                 "fallback_profile_op_started_ms", "fallback_profile_capture_state", "fallback_profile_gate_accepted"} | {
        x for x in assigned(c.inv_lam) if x.startswith("fallback_profile_save_ctx_") or x == "fallback_profile_save_verified"}
    if bad:
        v.append(f"INVALIDATE assigns {sorted(bad)} (D2: it holds no lock and no operation flag)")
    allowed = {"fallback_profile_invalidate_reason", "fallback_profile_present_seen", "fallback_profile_read_anomaly", "fallback_profile_seen_hw_gen",
               "fallback_profile_class", "fallback_profile_why", "fallback_profile_load", "fallback_witness_load", "fallback_profile_bytes",
               "fallback_witness_bytes", "fallback_profile_save_unconfirmed", "fallback_profile_save_unconfirmed_op",
               "fallback_profile_save_unconfirmed_gen", "fallback_durable_last_err", "fallback_durable_last_us"}
    stray = assigned(c.inv_lam) - allowed
    if stray:
        v.append(f"INVALIDATE assigns {sorted(stray)} beyond its allowed set")
    if re.search(r"modbus", re.sub(r"id\(inverter_modbus\)->(?:tx_buffer_empty|tx_blocked)\(\)", "", code)):
        v.append("INVALIDATE touches the Modbus hub beyond tx_buffer_empty() / tx_blocked()")
    if not sq(c.inv_lam).startswith(S("{ const ecco_fbsave::InvalidateGateResult i1 = ecco_fbsave::invalidate_in_flight_gate(")):
        v.append("the in-flight gate (I1) is not the first statement")
    # bus-idle check LAST before the writer
    s = sq(c.inv_lam)
    chk = S("if (!ecco_fbsave::invalidate_bus_idle(bn, id(inverter_modbus)->tx_buffer_empty(), id(inverter_modbus)->tx_blocked())) {")
    if s.count(chk) != 1:
        v.append("the bus-idle check is missing or not unique")
    else:
        i = s.index(chk) + len(chk) - 1
        j = close_of(s, i)
        tail = s[j + 1:]
        if not tail.startswith(S("const ecco_fbdurable::TxnOutcome o = ecco_fbdurable::commit_transition_t(")):
            v.append("the bus-idle check is not immediately followed by the writer call (it must be the LAST statement before commit_transition_t)")
        blk = s[i:j + 1]
        if "return;" not in blk or "commit_transition_t" in blk:
            v.append("the bus-idle refusal does not return")
    if not has(c.inv_lam, "ecco_fbdurable::TxnResult r{};"):
        v.append("TxnResult r{} (zero = UNKNOWN_REBOOT) is not declared")
    # every refusal ends in `return;` and the writer sits at the top level, after all three refusals (nothing can reach it on a refusal)
    cs = strip_cpp(c.inv_lam)
    if "commit_transition_t" in cs and enclosing_headers(cs, cs.index("commit_transition_t")) != []:
        v.append("the INVALIDATE writer call is nested in a block (it must be a top-level statement after the refusals)")
    for head in ("if (ir.code != ecco_fbsave::IG_ACCEPT) {", "if (plan.code != ecco_fbsave::PLAN_OK) {"):
        try:
            blk = sq_block(c.inv_lam, head)
            if not blk.endswith("return;}"):
                v.append(f"INVALIDATE: the refusal block `{head}` does not end in return;")
        except ValueError:
            v.append(f"INVALIDATE: the refusal block `{head}` was not found")
    return v


EXEC_RX = re.compile(r"\bid\(\s*(\w+)\s*\)\s*(?:\.|->)\s*execute\s*\(")


@pin("S-FIN", "SAVE_FINAL = two CONSECUTIVE lambdas with no wait_until / delay / script.execute (nor any non-lambda action) between REVIEW_FINAL, part 1, part 2 and RELEASE; the guards: REVIEW_FINAL skips SAVE, part 1 needs purpose SAVE, part 2 needs the verified hand-over; the commit's bus-quiet check is the last check (the writer is the first statement of its else branch)")
def d_savefinal(c):
    v = []
    top = c.top
    if len(top) < 6 or [list(a)[0] for a in top[-4:]] != ["lambda"] * 4:
        v.append(f"dispatch tail kinds {[list(a)[0] for a in top[-5:]]} (want the REVIEW_FINAL, SAVE part 1, SAVE part 2 and RELEASE lambdas consecutive, no other action)")
    for who, lam in (("REVIEW_FINAL", c.review_final), ("SAVE_FINAL part 1", c.save_p1), ("SAVE_FINAL part 2", c.save_p2), ("RELEASE", c.release)):
        m = WAITS_RX.search(strip_cpp(lam))
        if m:
            v.append(f"{who} contains {m.group(0)!r}")
        if EXEC_RX.search(strip_cpp(lam)):
            v.append(f"{who} calls .execute()")
    if not has(c.review_final, "if (id(fallback_profile_op_purpose) == ecco_fbsave::PURPOSE_SAVE) return; if (!ecco_fbcap::review_integrity_ok("):
        v.append("REVIEW_FINAL is not guarded by the SAVE purpose in front of its integrity check")
    if not sq(c.save_p1).startswith(S("if (id(fallback_profile_op_purpose) != ecco_fbsave::PURPOSE_SAVE) return; id(fallback_profile_save_verified) = false;")):
        v.append("SAVE_FINAL part 1 does not start with the purpose guard and the verified reset")
    if not sq(c.save_p2).startswith(S("if (!id(fallback_profile_save_verified)) return; id(fallback_profile_save_verified) = false;")):
        v.append("SAVE_FINAL part 2 does not start with the verified hand-over guard (and its immediate reset)")
    for who, lam in (("part 1", c.save_p1), ("part 2", c.save_p2)):
        if not has(lam, "!ecco_fbsave::save_integrity_ok(id(fallback_profile_op_in_progress), id(fallback_profile_op_purpose))") or not has(lam, "!id(fallback_profile_save_ctx_valid)"):
            v.append(f"SAVE_FINAL {who}: the integrity check (op in flight, purpose SAVE, context taken) is missing")
        if not has(lam, "ecco_fbcap::internal_context_text()"):
            v.append(f"SAVE_FINAL {who}: the integrity refusal is not the INTERNAL text")
    if not has(c.save_p1, "id(fallback_profile_save_ctx_id) == 0"):
        v.append("SAVE_FINAL part 1: the candidate-id integrity term (a context with id 0 can never save) is missing")
    # part 1 order
    if not seq_ok(c.save_p1, ["!ecco_fbsave::save_integrity_ok(", "if (go && id(fallback_profile_read_failed)) {", "ecco_fbsave::save_read_fail_text(",
                              "ecco_fbcap::first_diff(id(fallback_profile_pass1), id(fallback_profile_pass2)) >= 0",
                              "ecco_fbsave::save_changed_during_read_text(id(fallback_profile_pass1), id(fallback_profile_pass2))",
                              "ecco_fbcap::first_diff(id(fallback_profile_save_ctx_words), id(fallback_profile_pass2)) >= 0",
                              "ecco_fbsave::save_changed_since_review_text(id(fallback_profile_save_ctx_words), id(fallback_profile_pass2))",
                              "ecco_fbcap::capture_refusals(id(fallback_profile_pass2), ${ecco_inverter_tou_power_ceiling_w})", "l2.count > 0",
                              "ecco_fbsave::save_l2_text(l2, id(fallback_profile_pass2))", "const ecco_fbsave::FinalGate f0 = ecco_fbsave::final_gate_decide(gi, pr);",
                              "if (f0.gr.code == ecco_fbcap::GATE_NEED_PROBE) {", "const ecco_fbsave::FinalGate fg = ecco_fbsave::final_gate_decide(gi, pr);",
                              "id(fallback_profile_probe_latch) = fg.gr.latch;", "if (fg.gr.code != ecco_fbcap::GATE_ACCEPT) {", "res = fg.text;",
                              "id(fallback_profile_save_verified) = true;"]):
        v.append("SAVE_FINAL part 1: the verification order (integrity, read failure, pass1==pass2, pass2==candidate, L2, obligation vector, verified) is wrong or a step is missing")
    # lazy probes only inside the NEED_PROBE branch, after the first RAM decision
    s1 = sq(c.save_p1)
    try:
        a, b = block_after(s1, S("if (f0.gr.code == ecco_fbcap::GATE_NEED_PROBE) {"))
        blk = s1[a:b + 1]
        outside = s1[:a] + s1[b + 1:]
        if "read_direct_t(" in outside or s1.count("read_direct_t(") != 3 or blk.count("read_direct_t(") != 3:
            v.append("SAVE_FINAL part 1: a lease-marker read_direct_t outside the lazy NEED_PROBE branch (or not exactly three probes)")
        for tag in ("FREE_POWER_VALID_TAG", "DUMP_TO_GRID_VALID_TAG", "REG244_VALID_TAG"):
            if blk.count(tag) != 1:
                v.append(f"SAVE_FINAL part 1: the {tag} marker is not probed exactly once")
        if s1.find("read_direct_t(") < s1.find(S("const ecco_fbsave::FinalGate f0 = ecco_fbsave::final_gate_decide(gi, pr);")):
            v.append("SAVE_FINAL part 1: a marker is read before the RAM-leg decision")
    except ValueError:
        v.append("SAVE_FINAL part 1: the NEED_PROBE branch was not found")
    if rhs_of(c.save_p1, "fallback_profile_probe_latch") != ["fg.gr.latch"]:
        v.append(f"SAVE_FINAL part 1: probe_latch assigned {rhs_of(c.save_p1, 'fallback_profile_probe_latch')} (want only the gate's latch)")
    if re.search(r"ecco_fbcap::gate_decide\(", strip_cpp(c.save_p1)):
        v.append("SAVE_FINAL part 1 calls the REVIEW-worded gate_decide (it must use final_gate_decide: own holds masked, SAVE wording)")
    # part 2: bus quiet is the last check; the writer is the first statement of its else branch
    p2 = sq(c.save_p2)
    quiet = S("if (!ecco_fbsave::commit_bus_quiet(id(fallback_profile_op_in_progress), id(manual_write_in_progress), id(correction_in_progress), id(inverter_modbus)->tx_buffer_empty(), id(inverter_modbus)->tx_blocked())) {")
    if p2.count(quiet) != 1:
        v.append("SAVE_FINAL part 2: the commit_bus_quiet check is missing, altered or not unique")
    else:
        i = p2.index(quiet) + len(quiet) - 1
        j = close_of(p2, i)
        if not p2[j + 1:].startswith(S("else { const ecco_fbdurable::TxnOutcome o = ecco_fbdurable::commit_transition_t(")):
            v.append("SAVE_FINAL part 2: the writer call is not the first statement of the bus-quiet check's else branch (the check must be the LAST statement before it)")
        if "res=ecco_fbsave::save_bus_quiet_text();" not in p2[i:j]:
            v.append("SAVE_FINAL part 2: the bus-quiet refusal does not use save_bus_quiet_text()")
    # part 2 order
    if not seq_ok(c.save_p2, ["!id(fallback_profile_save_ctx_valid)", "const bool time_ok = id(ntp_synced) && id(ntp_time).now().is_valid();",
                              "epoch = time_ok ? (uint32_t) id(ntp_time).now().timestamp : 0u;", "ecco_fbsave::clock_trusted_for_save(time_ok, epoch)",
                              "ecco_fbdurable::read_direct_t(nvs, ecco_fbdurable::FALLBACK_PROFILE_KEY, p, dp)",
                              "ecco_fbdurable::read_direct_t(nvs, ecco_fbdurable::FAILBACK_PROVISION_KEY, w, dw)",
                              "const bool healthy = ecco_fbdurable::nvs_healthy();", "ecco_fbcap::evaluate_read(in)", "pi.captured_epoch = epoch;",
                              "const ecco_fbsave::Plan plan = ecco_fbsave::plan_save(pi);", "if (plan.op == ecco_fbdurable::PROV_OP_REPLACE_CORRUPT) {",
                              "ecco_fbdurable::TxnResult r{};", "ecco_fbsave::commit_bus_quiet(", "ecco_fbdurable::commit_transition_t(",
                              "id(fallback_durable_last_err) = ecco_fbsave::first_non_ok(r.w.err, r.p.err);",
                              "id(fallback_durable_last_us) = ecco_fbsave::total_us(r.w.us, r.p.us);", "if (o == ecco_fbdurable::TXN_UNKNOWN_REBOOT) {",
                              "ecco_fbdurable::mirror_after(o, r, p, lp, w, lw)", "ecco_fbdurable::note_committed(", "ecco_fbdurable::next_seen_hw_gen(",
                              "ecco_fbsave::txn_outcome_text(plan.op, o, r, plan.generation, p.generation)", "ecco_fbsave::txn_log_text(plan.op, o, r, plan.generation)"]):
        v.append("SAVE_FINAL part 2: the commit sequence (clock, fresh reads, health, evaluate, plan, forensic log, bus quiet, writer, outcome bookkeeping, mirror, texts, log) is wrong or a step is missing")
    # every refusal text of part 1 / part 2 is immediately followed by go = false (a refusal can never reach the hand-over / the writer)
    for who, lam in (("part 1", c.save_p1), ("part 2", c.save_p2)):
        loose = re.findall(r"res=[^;]*;(?!go=false;)", sq(lam))
        if loose:
            v.append(f"SAVE_FINAL {who}: a refusal text without `go = false;` right after it: {loose}")
    if not has(c.save_p1, "if (go) { id(fallback_profile_save_verified) = true; } else {"):
        v.append("SAVE_FINAL part 1: the verified hand-over is not set only under `if (go)`")
    if not has(c.save_p2, "if (plan.code != ecco_fbsave::PLAN_OK) { res = plan.text; go = false; } else {"):
        v.append("SAVE_FINAL part 2: the plan refusal is not `if (plan.code != PLAN_OK) { res = plan.text; go = false; } else { ... }`")
    s2c = strip_cpp(c.save_p2)
    if "commit_transition_t" in s2c and enclosing_headers(s2c, s2c.index("commit_transition_t")) != ["if (go)", "else", "else"]:
        v.append(f"SAVE_FINAL part 2: the writer call sits in {enclosing_headers(s2c, s2c.index('commit_transition_t'))} (want if (go) -> else of the plan check -> else of the bus-quiet check)")
    # the forensic log of a REPLACE CORRUPT comes BEFORE the writer call
    rc = sq(c.save_p2)
    if rc.find("replace_corrupt_log_text(") < 0 or rc.find("replace_corrupt_log_text(") > rc.find("commit_transition_t("):
        v.append("SAVE_FINAL part 2: the discarded CORRUPT record is not logged before it is replaced")
    if not has(c.save_p2, 'ESP_LOGW("fbdurable", "%s", rc0.c_str());') or not has(c.save_p2, 'ESP_LOGW("fbdurable", "%s", rc1.c_str());'):
        v.append("SAVE_FINAL part 2: the two REPLACE CORRUPT forensic WARN lines are missing")
    if not has(c.save_p2, 'if (o == ecco_fbdurable::TXN_COMMITTED) { ESP_LOGI("fbdurable", "%s", lg.c_str()); } else { ESP_LOGW("fbdurable", "%s", lg.c_str()); }'):
        v.append("SAVE_FINAL part 2: the per-transaction log line is not INFO when committed / WARN otherwise")
    return v


@pin("S-IDS", "words committed come ONLY from fallback_profile_pass2 and the save context taken at the gate: after the gate no SAVE lambda reads fallback_profile_cand_* / fallback_profile_exec_* / manual config staging, and every id() the two SAVE_FINAL lambdas name is on an explicit allow-list; SAVE_FINAL names pass2 for the words (pi.words) and the context for the prior")
def d_ids(c):
    v = []
    fbg = fb_global_ids() | {"fallback_profile_" + x for x in (
        "boot_loaded", "boot_salt", "fbs_slot", "bytes", "load", "class", "why", "present_seen", "read_anomaly", "seen_hw_gen", "op_in_progress", "op_purpose",
        "op_started_ms", "capture_state", "gate_accepted", "step", "step_terminal", "read_failed", "read_fail_code", "read_exception_code", "pass1",
        "pass2", "probe_latch", "obl_text", "invalidate_reason")} | {"fallback_witness_bytes", "fallback_witness_load"}
    entities = set(TS.values()) | {"fallback_profile_capture_dispatch", ARM}
    foreign_p1 = GATE_FOREIGN | {"free_power_write_enable", "dump_write_enable", "manual_config_write_enable"}
    # FB-B2 hardening: + the two heartbeat symbols of the commit-time re-check (S-SUP pins that one statement exactly)
    foreign_p2 = {"ntp_synced", "ntp_time", "manual_write_in_progress", "correction_in_progress", "inverter_modbus",
                  "supervision_state", "supervision_stable"}
    for who, lam, foreign in (("SAVE_FINAL part 1", c.save_p1, foreign_p1), ("SAVE_FINAL part 2", c.save_p2, foreign_p2)):
        refs = ids_of(lam)
        banned = sorted(r for r in refs if r.startswith(("fallback_profile_cand_", "fallback_profile_exec_")) or r.startswith("manual_cfg") or "manual_slot" in r)
        if banned:
            v.append(f"{who} reads {banned} after the gate (only the save context, pass1 / pass2 and live bus state may be read)")
        stray = sorted(r for r in refs if r not in fbg and r not in entities and r not in foreign)
        if stray:
            v.append(f"{who} names the id(s) {stray} off the allow-list")
    if var_assignments(c.save_p2, "pi").get("words") != "id(fallback_profile_pass2)":
        v.append("SAVE_FINAL part 2: the words to commit are not pi.words = id(fallback_profile_pass2)")
    if re.search(r"fallback_profile_pass1|fallback_profile_cand_words|fallback_profile_save_ctx_words", strip_cpp(c.save_p2)):
        v.append("SAVE_FINAL part 2 names pass1 / the candidate words / the context words (the committed words come from pass2 only)")
    return v


@pin("S-PREAMBLE", "the one-shot preamble order of the SAVE gate and the INVALIDATE lambda: the in-flight gate FIRST with a refusal branch holding ONLY arm.turn_off() and the B9 publish; then the arm read, arm.turn_off(), the candidate copy (SAVE), IE2 with the silent reason, and only then the gate decision; the candidate is copied BEFORE IE2 and never read after it; no code after the SAVE gate decision reads fallback_profile_exec_*")
def d_preamble(c):
    v = []
    # ---- SAVE
    lam = c.save_lam
    if not sq(lam).startswith(S("{ const ecco_fbsave::SaveGateResult g1 = ecco_fbsave::save_in_flight_gate(id(fallback_profile_op_in_progress), id(fallback_profile_capture_dispatch).is_running());")):
        v.append("SAVE gate: G1 (the in-flight check) is not the first statement")
    g1 = sq(lam)
    try:
        blk = sq_block(lam, "if (g1.code != ecco_fbsave::SG_UNSET) {")
        if blk != S("{ id(fallback_profile_arm).turn_off(); if (id(fallback_profile_last_result_text).state != g1.text.c_str()) id(fallback_profile_last_result_text).publish_state(g1.text.c_str()); return; }"):
            v.append("SAVE gate: the G1 refusal branch is not exactly `arm.turn_off(); publish B9; return;`")
        if assigned(blk) or publishes(blk) != {B9}:
            v.append("SAVE gate: the G1 refusal branch assigns or publishes more than the B9 text")
    except ValueError:
        v.append("SAVE gate: the G1 branch was not found")
    cand = ["const bool c_valid = id(fallback_profile_cand_valid);", "const bool c_saveable = id(fallback_profile_cand_saveable);",
            "const uint64_t c_id = id(fallback_profile_cand_id);", "const uint32_t c_ms = id(fallback_profile_cand_ms);",
            "const uint8_t c_prior_class = id(fallback_profile_cand_prior_class);", "const uint32_t c_prior_gen = id(fallback_profile_cand_prior_gen);",
            "const uint64_t c_prior_binding = id(fallback_profile_cand_prior_binding);", "const uint32_t c_writes_fp = id(fallback_profile_cand_writes_fp);",
            "const std::array<uint16_t, 31> c_words = id(fallback_profile_cand_words);"]
    if not seq_ok(lam, ["const ecco_fbsave::SaveGateResult g1 = ecco_fbsave::save_in_flight_gate(", "return; } }", "const bool armed = id(fallback_profile_arm).state;",
                        "id(fallback_profile_arm).turn_off();", *cand, "id(fallback_profile_invalidate_reason) = ecco_fbcap::REASON_SUPERSEDED;",
                        "id(fallback_profile_invalidate_candidate).execute();", "ecco_fbsave::SaveGateInputs si{};", "ecco_fbcap::GateInputs gi{};",
                        "const ecco_fbsave::SaveGateResult sr = ecco_fbsave::save_gate_decide(", "if (sr.code == ecco_fbsave::SG_ACCEPT) {"]):
        v.append("SAVE gate: the preamble order is wrong (in-flight, arm read, arm off, candidate copy, IE2, inputs, gate decision, accept)")
    s = strip_cpp(lam)
    cands = [m.start() for m in re.finditer(r"fallback_profile_cand_", s)]
    ie2 = s.find("id(fallback_profile_invalidate_candidate).execute()")
    if len(cands) != 9 or ie2 < 0 or (cands and max(cands) > ie2):
        v.append(f"SAVE gate: {len(cands)} reads of fallback_profile_cand_* (want exactly the nine copies, all BEFORE the candidate is invalidated)")
    if sorted(set(re.findall(r"fallback_profile_cand_(\w+)", s))) != sorted({"valid", "saveable", "id", "ms", "prior_class", "prior_gen", "prior_binding", "writes_fp", "words"}):
        v.append("SAVE gate: the candidate fields copied are not exactly valid / saveable / id / ms / prior class / gen / binding / writes_fp / words")
    if not has(lam, "if (c_valid) { id(fallback_profile_invalidate_reason) = ecco_fbcap::REASON_SUPERSEDED; id(fallback_profile_invalidate_candidate).execute(); }"):
        v.append("SAVE gate: IE2 (consume the candidate with the silent superseded reason) is missing or changed")
    # no exec_* read after the gate decision
    gs = sq(lam)
    at = gs.find(S("ecco_fbsave::save_gate_decide("))
    if at < 0:
        v.append("SAVE gate: save_gate_decide not found")
    else:
        end = close_of(gs, gs.index("(", at))
        if "fallback_profile_exec_" in gs[end:]:
            v.append("SAVE gate: code after the gate decision reads fallback_profile_exec_*")
        args = call_args(lam, r"ecco_fbsave::save_gate_decide")
        want = ["si", "id(fallback_profile_exec_action).c_str()", "id(fallback_profile_exec_action).size()", "id(fallback_profile_exec_target_id).c_str()",
                "id(fallback_profile_exec_target_id).size()", "id(fallback_profile_exec_confirmation).c_str()", "id(fallback_profile_exec_confirmation).size()", "gi"]
        if args != want:
            v.append(f"SAVE gate: save_gate_decide arguments {args} (want {want})")
    for who, code in (("SAVE script", repr(c.save_then[1:])), ):
        if "fallback_profile_exec_" in code:
            v.append(f"{who}: an action after the gate lambda reads exec_*")
    # ---- INVALIDATE
    lam = c.inv_lam
    try:
        blk = sq_block(lam, "if (i1.code != ecco_fbsave::IG_UNSET) {")
        if blk != S("{ id(fallback_profile_arm).turn_off(); if (id(fallback_profile_last_result_text).state != i1.text.c_str()) id(fallback_profile_last_result_text).publish_state(i1.text.c_str()); return; }"):
            v.append("INVALIDATE: the I1 refusal branch is not exactly `arm.turn_off(); publish B9; return;`")
    except ValueError:
        v.append("INVALIDATE: the I1 branch was not found")
    if not seq_ok(lam, ["const ecco_fbsave::InvalidateGateResult i1 = ecco_fbsave::invalidate_in_flight_gate(", "return; } }", "const bool armed = id(fallback_profile_arm).state;",
                        "id(fallback_profile_arm).turn_off();", "if (id(fallback_profile_cand_valid)) {", "id(fallback_profile_invalidate_reason) = ecco_fbcap::REASON_SUPERSEDED;",
                        "id(fallback_profile_invalidate_candidate).execute();", "ecco_fbsave::InvalidateGateInputs ii{};",
                        "const ecco_fbsave::InvalidateGateResult ir = ecco_fbsave::invalidate_gate_decide(", "if (ir.code != ecco_fbsave::IG_ACCEPT) {",
                        "ecco_fbdurable::EspNvs nvs;", "ecco_fbdurable::read_direct_t(nvs, ecco_fbdurable::FALLBACK_PROFILE_KEY, p, dp)",
                        "ecco_fbdurable::read_direct_t(nvs, ecco_fbdurable::FAILBACK_PROVISION_KEY, w, dw)", "const bool healthy = ecco_fbdurable::nvs_healthy();",
                        "ecco_fbcap::evaluate_read(in)", "ecco_fbsave::plan_invalidate(pj)", "ecco_fbsave::invalidate_bus_idle(bn,",
                        "ecco_fbdurable::commit_transition_t("]):
        v.append("INVALIDATE: the order (in-flight, arm read, arm off, IE2, gate decision, fresh reads, health, evaluate, plan, bus idle, writer) is wrong or a step is missing")
    ss = strip_cpp(lam)
    if len(re.findall(r"fallback_profile_cand_", ss)) != 1:
        v.append("INVALIDATE: reads fallback_profile_cand_* other than the one IE2 `cand_valid` test")
    if not has(lam, "if (id(fallback_profile_cand_valid)) { id(fallback_profile_invalidate_reason) = ecco_fbcap::REASON_SUPERSEDED; id(fallback_profile_invalidate_candidate).execute(); }"):
        v.append("INVALIDATE: IE2 (consume the candidate with the silent superseded reason) is missing or changed")
    args = call_args(lam, r"ecco_fbsave::invalidate_gate_decide")
    want = ["ii", "id(fallback_profile_exec_action).c_str()", "id(fallback_profile_exec_action).size()", "id(fallback_profile_exec_target_id).c_str()",
            "id(fallback_profile_exec_target_id).size()", "id(fallback_profile_exec_confirmation).c_str()", "id(fallback_profile_exec_confirmation).size()"]
    if args != want:
        v.append(f"INVALIDATE: invalidate_gate_decide arguments {args} (want {want})")
    return v


# ===========================================================================
# [S] api action, arm switch, supervision, reboot
# ===========================================================================
@pin("S-API", "api actions: exactly 3; actions[0] stays free_power_recovery_execute; exactly one ha_supervision_heartbeat; fallback_profile_execute appended LAST with variables exactly action / target_id / confirmation (all `string`), the three StringRefs copied with .str() first, the router is the header function is_invalidate_action, and NO api.respond")
def d_api(c):
    v = []
    acts = c.api_actions
    names = [a.get("action") for a in acts]
    if names != ["free_power_recovery_execute", "ha_supervision_heartbeat", "fallback_profile_execute"]:
        v.append(f"api actions {names} (want exactly the two existing ones, then fallback_profile_execute LAST)")
    if names.count("ha_supervision_heartbeat") != 1 or (names and names[0] != "free_power_recovery_execute"):
        v.append("the heartbeat action is not unique or actions[0] is not free_power_recovery_execute")
    a = c.api_act
    if list(a) != ["action", "variables", "then"]:
        v.append(f"fallback_profile_execute keys {list(a)} (want action / variables / then: no api.respond, no response block)")
    if a.get("variables") != {"action": "string", "target_id": "string", "confirmation": "string"} or list(a.get("variables") or {}) != ["action", "target_id", "confirmation"]:
        v.append(f"fallback_profile_execute variables {a.get('variables')}")
    if "api.respond" in repr(a) or "respond" in repr(list(a)) or "supports_response" in repr(a):
        v.append("fallback_profile_execute answers (api.respond / supports_response)")
    if [list(x)[0] for x in (a.get("then") or [])] != ["lambda", "if"]:
        v.append(f"fallback_profile_execute then {[list(x)[0] for x in (a.get('then') or [])]} (want a lambda then the router if)")
    want = ["id(fallback_profile_exec_action)=action.str();", "id(fallback_profile_exec_target_id)=target_id.str();",
            "id(fallback_profile_exec_confirmation)=confirmation.str();", "id(fallback_profile_exec_hb_ok)=(id(supervision_state)==1)&&id(supervision_stable);"]
    if sq(c.api_lam) != "".join(want):
        v.append("the api lambda is not exactly the three .str() copies followed by the one heartbeat snapshot")
    cond = (c.api_if.get("condition") or {}).get("lambda") if isinstance(c.api_if.get("condition"), dict) else None
    if S(cond or "") != S("return ecco_fbsave::is_invalidate_action(id(fallback_profile_exec_action).c_str(), id(fallback_profile_exec_action).size());"):
        v.append("the router condition is not ecco_fbsave::is_invalidate_action(exec_action ...)")
    if c.api_if.get("then") != [{"script.execute": {"id": "fallback_profile_invalidate"}}] or c.api_if.get("else") != [{"script.execute": {"id": "fallback_profile_save"}}] or set(c.api_if) != {"condition", "then", "else"}:
        v.append("the router does not execute INVALIDATE for the invalidate token and the SAVE gate for every other token")
    if literals(c.api_lam) or literals(cond or ""):
        v.append("the api action holds a string literal (the router is a header function)")
    if set(assigned(c.api_lam)) != {"fallback_profile_exec_action", "fallback_profile_exec_target_id", "fallback_profile_exec_confirmation", "fallback_profile_exec_hb_ok"}:
        v.append(f"the api lambda assigns {sorted(assigned(c.api_lam))}")
    return v


@pin("S-ARM", "the arm switch: exactly one new template switch with the pinned shape (optimistic, ALWAYS_OFF, turn_on_action only stamping arm_on_ms = millis()); no 'upervision' in its YAML; no firmware code ever turns it ON (members used: .turn_off() and .state only; no switch.* action names it); turned off by exactly the SAVE gate, the INVALIDATE lambda, the REVIEW gate, REVIEW_FINAL and the 10 s housekeeping TTL lambda; TTL via ecco_fbsave::arm_expired; arm_on_ms assigned only by the switch")
def d_arm(c):
    v = []
    want = {"platform": "template", "name": "ECCO Fallback Profile Arm", "id": ARM, "optimistic": True, "restore_mode": "ALWAYS_OFF",
            "icon": "mdi:shield-key-outline"}
    a = c.arm or {}
    if {k: x for k, x in a.items() if k != "turn_on_action"} != want or list(a) != [*want, "turn_on_action"]:
        v.append(f"arm switch {a}")
    ta = a.get("turn_on_action")
    if not isinstance(ta, list) or len(ta) != 1 or list(ta[0]) != ["lambda"] or sq(lam_of(ta[0])) != S("id(fallback_profile_arm_on_ms) = millis();"):
        v.append("turn_on_action is not exactly the one lambda `id(fallback_profile_arm_on_ms) = millis();`")
    if re.search(r"upervision", L.raw_switch_block(c.text, ARM), re.I) or not L.raw_switch_block(c.text, ARM):
        v.append("the arm switch YAML names 'upervision' (or was not found)")
    members: dict[str, set] = {}
    for n, code in c.all_lams:
        s_ = strip_cpp(code)
        for m in re.finditer(r"\bid\(\s*%s\s*\)\s*(?:\.|->)\s*(\w+)" % ARM, s_):
            members.setdefault(m.group(1), set()).add(n)
        # every use of the arm object is a member access: a bare id(fallback_profile_arm) (a reference, a pointer, an argument) could
        # call turn_on() where no pin looks
        if len(re.findall(r"\bid\(\s*%s\s*\)" % ARM, s_)) != len(re.findall(r"\bid\(\s*%s\s*\)\s*(?:\.|->)\s*\w+" % ARM, s_)):
            v.append(f"{n}: the arm object is used other than through a member access (a bare id(fallback_profile_arm))")
    if set(members) - {"turn_off", "state"}:
        v.append(f"the arm is used through {sorted(set(members) - {'turn_off', 'state'})} (firmware may only call turn_off() and read .state; it never turns the arm ON)")
    # no non-lambda action names the arm
    def acts(x, found):
        if isinstance(x, dict):
            for k, y in x.items():
                if isinstance(k, str) and k.startswith(("switch.", "homeassistant.")) and ARM in repr(y):
                    found.append(k)
                acts(y, found)
        elif isinstance(x, list):
            for y in x:
                acts(y, found)
        return found
    hits = acts({k: x for k, x in c.fw.items() if not k.startswith("_")}, [])
    if hits:
        v.append(f"a switch.* / homeassistant.* action names the arm: {hits}")
    off = {n: strip_cpp(code).count(f"id({ARM}).turn_off()") for n, code in c.all_lams if f"id({ARM}).turn_off()" in strip_cpp(code)}
    iv = c.interval_index
    want_off = {"script:fallback_profile_review.then[0]": 1, c.name_of(c.review_final): 1, "script:fallback_profile_save.then[0]": 2,
                "script:fallback_profile_invalidate.then[0]": 2, f"interval[{iv}].then[1]": 1}
    if off != want_off:
        v.append(f"arm.turn_off() sites {off} (want {want_off})")
    if not sq(c.tick2).startswith(S("if (id(fallback_profile_arm).state && ecco_fbsave::arm_expired(millis(), id(fallback_profile_arm_on_ms))) { id(fallback_profile_arm).turn_off(); }")):
        v.append("the TTL statement of the housekeeping lambda is missing or changed (arm_expired(millis(), arm_on_ms))")
    if re.search(r"\b(?:120000|130000|110000|100000)\b", strip_cpp(c.tick2)):
        v.append("a literal TTL in the housekeeping lambda (the constant lives in the header)")
    sites = [(n, r) for n, code in c.all_lams for r in rhs_of(code, "fallback_profile_arm_on_ms")]
    if sites != [("switch:fallback_profile_arm.turn_on_action[0]", "millis()")] or any("fallback_profile_arm_on_ms" in assigned(code) for n, code in c.all_lams if n != "switch:fallback_profile_arm.turn_on_action[0]"):
        v.append(f"arm_on_ms assignment sites {sites} (want only the switch's turn_on_action)")
    reads = sorted(n for n, code in c.all_lams if "fallback_profile_arm_on_ms" in strip_cpp(code))
    if reads != sorted([f"interval[{iv}].then[1]", "switch:fallback_profile_arm.turn_on_action[0]"]):
        v.append(f"arm_on_ms is named by {reads}")
    return v


@pin("S-DRAIN", "the pre-commit drain: ONE `if purpose == SAVE && !read_failed` guarding ONE wait_until on the four-term bus-idle predicate with timeout 3000ms, placed after the four-read nest and before REVIEW_FINAL; the timeout equals ecco_fbsave::PRECOMMIT_WAIT_MS in the header AND the Python mirror (3000)")
def d_drain(c):
    v = []
    d = c.drain_if.get("if") if isinstance(c.drain_if, dict) else None
    if not isinstance(d, dict) or set(d) != {"condition", "then"}:
        return ["the dispatch item before REVIEW_FINAL is not the drain `if` (condition + then, no else)"]
    if S((d.get("condition") or {}).get("lambda", "")) != S("return id(fallback_profile_op_purpose) == ecco_fbsave::PURPOSE_SAVE && !id(fallback_profile_read_failed);"):
        v.append("the drain guard is not `purpose == SAVE && !read_failed`")
    th = d.get("then") or []
    if len(th) != 1 or list(th[0]) != ["wait_until"] or set(th[0]["wait_until"]) != {"condition", "timeout"}:
        return v + [f"the drain body is {[list(x) for x in th]} (want exactly one wait_until)"]
    w = th[0]["wait_until"]
    if S(w["condition"].get("lambda", "")) != S(IDLE_COND):
        v.append("the drain predicate is not the four-term bus-idle predicate")
    m = re.fullmatch(r"(\d+)ms", str(w["timeout"]))
    ms = int(m.group(1)) if m else None
    hdr = re.search(r"constexpr uint32_t PRECOMMIT_WAIT_MS = (\d+)u;", c.file("firmware/include/ecco_fallback_save.h"))
    mir = re.search(r"^PRECOMMIT_WAIT_MS\s*=\s*(\d+)\s*$", c.file("registry/fallback_save.py"), re.M)
    if ms != 3000 or not hdr or int(hdr.group(1)) != ms or not mir or int(mir.group(1)) != ms:
        v.append(f"drain timeout {w['timeout']!r} vs header PRECOMMIT_WAIT_MS {hdr.group(1) if hdr else None} vs mirror {mir.group(1) if mir else None} (want 3000 everywhere)")
    top = c.top
    if len(top) >= 6 and not (isinstance(top[-6], dict) and list(top[-6]) == ["if"] and S(top[-6]["if"]["condition"].get("lambda", "")) == S("return !id(fallback_profile_read_failed);")):
        v.append("the drain does not directly follow the four-read nest")
    kinds = kinds_of(top)
    if kinds.get("wait_until") != 1 + len(collect_reads(top)) + 1 or kinds.get("delay"):
        # one idle wait + one bounded wait per read + the drain
        v.append(f"dispatch wait_until count {kinds.get('wait_until')} (want idle wait + 4 bounded waits + the drain = 6), delay {kinds.get('delay')}")
    return v


@pin("S-DISPATCH", "the dispatch keeps its FB-B1 shape: items 0-3 untouched, then drain / REVIEW_FINAL / SAVE part 1 / part 2 / RELEASE; RELEASE is the last action and is reached on EVERY path; no script.execute / delay; exactly the four FC03 reads")
def d_dispatch(c):
    v = base_violation()
    top = c.top
    kinds = [list(a)[0] for a in top]
    if kinds != ["lambda", "wait_until", "lambda", "if", "if", "lambda", "lambda", "lambda", "lambda"]:
        v.append(f"dispatch top-level kinds {kinds}")
    if BASE["ctx"] is not None and top[:4] != BASE["ctx"].top[:4]:
        v.append("dispatch items 0-3 differ from the base")
    paths = paths_of(top)
    if not paths or any(p[-1] != top[-1] for p in paths):
        v.append("a dispatch path does not end in the RELEASE lambda")
    k = kinds_of(top)
    if k.get("script.execute") or k.get("delay"):
        v.append(f"the dispatch has script.execute / delay actions {dict(k)}")
    if rhs_of(c.release, "manual_write_in_progress") != ["false"] or rhs_of(c.release, "fallback_profile_op_in_progress") != ["false"]:
        v.append("RELEASE does not clear the operation flag and the write mutex")
    return v


@pin("S-RELEASE", "RELEASE clears the operation flag, the write mutex, the step, the purpose and EVERY SAVE context / verified global (exact values) and assigns nothing else; the breaker clears the same state (never the write mutex)")
def d_release(c):
    v = []
    want = {"fallback_profile_op_in_progress": "false", "manual_write_in_progress": "false", "fallback_profile_step": "0", "fallback_profile_op_purpose": "0", **CTX_CLEAR}
    got = {k: rhs_of(c.release, k) for k in assigned(c.release)}
    if {k: x for k, x in got.items()} != {k: [x] for k, x in want.items()}:
        v.append(f"RELEASE assigns {got} (want {want})")
    t = strip_cpp(c.tick1)
    try:
        i = t.index("ecco_fbcap::breaker_fired(")
        i_if = t.rfind("if (", 0, i)
        o_if = t.index("(", i_if)
        e_if = close_of(t, o_if)
        ob = t.index("{", e_if)
        brk = t[ob:close_of(t, ob) + 1]
    except ValueError:
        return v + ["the breaker block of the housekeeping tick was not found"]
    bwant = {"fallback_profile_op_in_progress": "false", "fallback_profile_op_purpose": "0", "fallback_profile_step": "0",
             "fallback_profile_invalidate_reason": "brk.c_str()", **CTX_CLEAR}
    bgot = {k: rhs_of(brk, k) for k in assigned(brk)}
    if bgot != {k: [x] for k, x in bwant.items()}:
        v.append(f"the breaker assigns {bgot} (want {bwant})")
    if "manual_write_in_progress" in assigned(c.tick1) or "manual_write_in_progress" in assigned(c.tick2) or re.search(r"manual_write_in_progress\)\s*=(?!=)", t):
        v.append("the housekeeping tick assigns manual_write_in_progress (the breaker must never touch the mutex)")
    return v


@pin("S-CTX", "SAVE context: assigned ONLY in the SAVE gate's acceptance branch (with the lock flags, purpose SAVE, SAVING and the gate hand-over, from the lambda-local candidate copy), cleared by RELEASE and the breaker; purpose SAVE set only at acceptance; the write mutex / operation flag have exactly the pinned assignment sites")
def d_ctx(c):
    v = []
    s = c.save_lam
    try:
        acc = sq_block(s, "if (sr.code == ecco_fbsave::SG_ACCEPT) {")
        ss = sq(s)
        a0 = ss.index(acc)
        outside = ss[:a0] + ss[a0 + len(acc):]
    except ValueError:
        return ["SAVE gate: no unique accept branch"]
    wantacc = {"fallback_profile_save_ctx_words": "c_words", "fallback_profile_save_ctx_id": "c_id", "fallback_profile_save_ctx_prior_class": "c_prior_class",
               "fallback_profile_save_ctx_prior_gen": "c_prior_gen", "fallback_profile_save_ctx_prior_binding": "c_prior_binding",
               "fallback_profile_save_ctx_replace_corrupt": "sr.replace_corrupt", "fallback_profile_save_ctx_valid": "true",
               "fallback_profile_op_in_progress": "true", "manual_write_in_progress": "true", "fallback_profile_op_purpose": "ecco_fbsave::PURPOSE_SAVE",
               "fallback_profile_op_started_ms": "millis()", "fallback_profile_step": "0", "fallback_profile_capture_state": "ecco_fbcap::CAPTURE_SAVING",
               "fallback_profile_gate_accepted": "true"}
    for k, x in wantacc.items():
        if rhs_of(acc, k) != [x]:
            v.append(f"accept branch: {k} = {rhs_of(acc, k)} (want {x})")
    if set(assigned(acc)) != set(wantacc):
        v.append(f"the accept branch assigns {sorted(set(assigned(acc)) ^ set(wantacc))} beyond / below the pinned set")
    stray = set(wantacc) & set(assigned(outside)) - {"fallback_profile_capture_state"}
    if stray:
        v.append(f"the SAVE gate assigns {sorted(stray)} outside its accept branch")
    if rhs_of(outside, "fallback_profile_capture_state") != ["ecco_fbcap::CAPTURE_IDLE"]:
        v.append("the SAVE gate's non-accept path does not set capture_state to IDLE exactly once")
    # whole-firmware assignment sites
    def sites(name):
        out = {}
        for n, code in c.fb.items():
            r = rhs_of(code, name)
            if r or name in assigned(code):
                out[n] = r if r else ["<other>"]
        return out
    iv = c.interval_index
    rel, gate_rev, save, p1, p2 = (c.name_of(c.release), "script:fallback_profile_review.then[0]", "script:fallback_profile_save.then[0]",
                                   c.name_of(c.save_p1), c.name_of(c.save_p2))
    tick = f"interval[{iv}].then[0]"
    want_sites = {
        "fallback_profile_op_purpose": {gate_rev: ["ecco_fbcap::PURPOSE_REVIEW"], save: ["ecco_fbsave::PURPOSE_SAVE"], rel: ["0"], tick: ["0"]},
        "manual_write_in_progress": {gate_rev: ["true"], save: ["true"], rel: ["false"]},
        "fallback_profile_op_in_progress": {gate_rev: ["true"], save: ["true"], rel: ["false"], tick: ["false"]},
        "fallback_profile_save_ctx_valid": {save: ["true"], rel: ["false"], tick: ["false"]},
        "fallback_profile_save_ctx_words": {save: ["c_words"], rel: ["std::array<uint16_t,31>{}"], tick: ["std::array<uint16_t,31>{}"]},
        "fallback_profile_save_ctx_id": {save: ["c_id"], rel: ["0"], tick: ["0"]},
        "fallback_profile_save_ctx_replace_corrupt": {save: ["sr.replace_corrupt"], rel: ["false"], tick: ["false"]},
        "fallback_profile_save_verified": {p1: ["false", "true"], p2: ["false"], rel: ["false"], tick: ["false"]},
        "fallback_profile_gate_accepted": {gate_rev: ["true"], "script:fallback_profile_review.then[1].if.then[0]": ["false"], save: ["true"],
                                           "script:fallback_profile_save.then[1].if.then[0]": ["false"]},
    }
    for name, want in want_sites.items():
        got = sites(name)
        if got != want:
            v.append(f"{name} is assigned at {got} (want {want})")
    return v


@pin("S-UNCONF", "RAM overlay + B2 diagnostics: fallback_profile_save_unconfirmed is set to true ONLY inside the `o == TXN_UNKNOWN_REBOOT` branch of the two commit lambdas (never cleared, never in boot / REVIEW / the tick); fallback_durable_last_err / _us are assigned only after the writer call by first_non_ok / total_us; the boot lambda and REVIEW_FINAL only read them")
def d_unconfirmed(c):
    v = []
    iv = c.interval_index
    for name, want in (("fallback_profile_save_unconfirmed", {c.name_of(c.save_p2): ["true"], c.name_of(c.inv_lam): ["true"]}),
                       ("fallback_profile_save_unconfirmed_op", {c.name_of(c.save_p2): ["plan.op"], c.name_of(c.inv_lam): ["plan.op"]}),
                       ("fallback_profile_save_unconfirmed_gen", {c.name_of(c.save_p2): ["plan.generation"], c.name_of(c.inv_lam): ["plan.generation"]}),
                       ("fallback_durable_last_err", {c.name_of(c.save_p2): ["ecco_fbsave::first_non_ok(r.w.err,r.p.err)"], c.name_of(c.inv_lam): ["ecco_fbsave::first_non_ok(r.w.err,r.p.err)"]}),
                       ("fallback_durable_last_us", {c.name_of(c.save_p2): ["ecco_fbsave::total_us(r.w.us,r.p.us)"], c.name_of(c.inv_lam): ["ecco_fbsave::total_us(r.w.us,r.p.us)"]})):
        got = {}
        for n, code in c.all_lams:
            r = rhs_of(code, name)
            if r or name in assigned(code):
                got[n] = r if r else ["<other>"]
        if got != want:
            v.append(f"{name} is assigned at {got} (want {want})")
    for who, lam in (("SAVE_FINAL part 2", c.save_p2), ("INVALIDATE", c.inv_lam)):
        try:
            blk = sq_block(lam, "if (o == ecco_fbdurable::TXN_UNKNOWN_REBOOT) {")
        except ValueError:
            v.append(f"{who}: the UNKNOWN_REBOOT branch was not found")
            continue
        if set(assigned(blk)) != {"fallback_profile_save_unconfirmed", "fallback_profile_save_unconfirmed_op", "fallback_profile_save_unconfirmed_gen"}:
            v.append(f"{who}: the UNKNOWN_REBOOT branch assigns {sorted(assigned(blk))}")
        s = sq(lam)
        at = [s.find("commit_transition_t("), s.find(sq("id(fallback_profile_save_unconfirmed) = true;")), s.find("mirror_after(")]
        if min(at) < 0 or not at[0] < at[1] < at[2]:
            v.append(f"{who}: the overlay is not set after the writer call and before the mirror is rebuilt")
    for who, lam in (("boot", c.boot), ("REVIEW_FINAL", c.review_final)):
        if {"fallback_durable_last_err", "fallback_durable_last_us", "fallback_profile_save_unconfirmed"} & set(assigned(lam)):
            v.append(f"{who} assigns the overlay / B2 diagnostics (it only reads them)")
    if "fallback_profile_save_unconfirmed" in strip_cpp(c.boot):
        v.append("the boot lambda names the SAVE_UNCONFIRMED overlay (a reboot IS the resolution; boot never sets it)")
    readers = sorted(n for n, code in c.all_lams if "fallback_profile_save_unconfirmed)" in S(strip_cpp(code)).replace("fallback_profile_save_unconfirmed_", "x"))
    want_r = sorted({"script:fallback_profile_save.then[0]", c.name_of(c.save_p2), c.name_of(c.inv_lam), c.name_of(c.review_final), f"interval[{iv}].then[1]"})
    if readers != want_r:
        v.append(f"the overlay is read by {readers} (want {want_r})")
    return v


@pin("S-OVERLAY", "the overlay wins at every B1 publish and in the review eligibility: every epc_name( argument outside the boot load is overlay_class(...) or eff_cls (= overlay_class(e.cls, save_unconfirmed)); ri.cls = eff_cls; every b2_text( call passes the retained id(fallback_durable_last_err) / id(fallback_durable_last_us)")
def d_overlay(c):
    v = []
    ov = "ecco_fbsave::overlay_class(e.cls,id(fallback_profile_save_unconfirmed))"
    ov2 = "ecco_fbsave::overlay_class(e2.cls,id(fallback_profile_save_unconfirmed))"
    n_b1 = 0
    for n, code in c.fb.items():
        sc_ = strip_cpp(code)
        for a in [S(sc_[m.end():close_of(sc_, m.end() - 1)]) for m in re.finditer(r"\bepc_name\s*\(", sc_)]:
            n_b1 += 1
            if n == "esphome.on_boot.then[3]":
                if a != "e.cls":
                    v.append(f"boot epc_name({a}) (unchanged: e.cls)")
            elif a not in ("eff_cls", ov, ov2):
                v.append(f"{n}: B1 published through epc_name({a}) - not the SAVE_UNCONFIRMED overlay")
    if n_b1 != 6:
        v.append(f"{n_b1} epc_name( sites in FB lambdas (want boot 1, REVIEW_FINAL 1, SAVE_FINAL part 2 2, INVALIDATE 2)")
    if rhs_of(c.review_final, "eff_cls") or not has(c.review_final, "const uint8_t eff_cls = ecco_fbsave::overlay_class(e.cls, id(fallback_profile_save_unconfirmed));"):
        v.append("REVIEW_FINAL: eff_cls is not defined once as overlay_class(e.cls, save_unconfirmed)")
    if var_assignments(c.review_final, "ri").get("cls") != "eff_cls" or rhs_of(c.review_final, "fallback_profile_cand_prior_class") != ["eff_cls"]:
        v.append("REVIEW_FINAL: ri.cls / cand_prior_class are not the overlay class")
    if rhs_of(c.review_final, "fallback_profile_class") != ["e.cls"]:
        v.append("REVIEW_FINAL: fallback_profile_class must stay the composed class (e.cls)")
    nb2 = 0
    for n, code in c.fb.items():
        s = strip_cpp(code)
        for m in re.finditer(r"\bb2_text\s*\(", s):
            nb2 += 1
            args = [re.sub(r"\s+", "", a) for a in split_args(s[m.end():close_of(s, m.end() - 1)])]
            if args[-2:] != ["id(fallback_durable_last_err)", "id(fallback_durable_last_us)"] or len(args) != 7:
                v.append(f"{n}: b2_text arguments {args} (the last two must be the retained werr / us globals)")
    if nb2 != 6:
        v.append(f"{nb2} b2_text( calls in FB lambdas (want 6: boot, REVIEW_FINAL, SAVE_FINAL part 2 x2, INVALIDATE x2)")
    return v


@pin("S-SUP", "supervision: FB code reads the heartbeat in exactly TWO places - the execute-time snapshot (one line of the api action lambda) and the commit-time RE-CHECK (one statement of SAVE_FINAL part 2, after plan_save and BEFORE the bus-quiet check and the writer); the substring 'supervision' appears nowhere else in FB code including comments (+4 occurrences over the base, two on each line); 'upervision' absent from the arm switch YAML and every FB script / interval / boot lambda / global comment; exec_hb_ok read only by the SAVE gate; exec_* names only in the api action and the two gate lambdas")
def d_supervision(c):
    v = base_violation()
    live_n = len(re.findall("supervision", c.text, re.I))
    if BASE["text"] is not None:
        base_n = len(re.findall("supervision", BASE["text"], re.I))
        if live_n - base_n != 4:
            v.append(f"'supervision' occurs {live_n - base_n} times more than in the base (want exactly four: the two on the heartbeat snapshot line and the two of the commit-time re-check)")
    api = L.raw_api_action(c.text, "fallback_profile_execute")
    if not api:
        v.append("the api action text was not found")
    elif len(re.findall("supervision", api, re.I)) != 2 or sum(1 for ln in api.splitlines() if re.search("supervision", ln, re.I)) != 1:
        v.append("the api action names 'supervision' other than on the single heartbeat snapshot line")
    for n, code in c.fb.items():
        if n.startswith("api:fallback_profile_execute.then[0]"):
            if len(re.findall(r"id\(supervision_(?:state|stable)\)", strip_cpp(code))) != 2 or re.search(r"supervision", re.sub(r"id\(supervision_(?:state|stable)\)", "", strip_cpp(code))):
                v.append("the api lambda reads supervision other than the one snapshot line")
        elif n == c.name_of(c.save_p2):
            # the commit-time re-check: exactly one statement, two reads, nothing else mentions the word (comments included)
            code_s = strip_cpp(code)
            stmt = S("if (!((id(supervision_state) == 1) && id(supervision_stable))) {")
            sq_code = sq(code)
            if sq_code.count(stmt) != 1 or len(re.findall("supervision", code, re.I)) != 2:
                v.append(f"{n}: the commit-time heartbeat re-check is not exactly one `{stmt}` statement with no other mention")
            else:
                i_stmt = sq_code.index(stmt)
                i_plan = sq_code.find("ecco_fbsave::plan_save(")
                i_quiet = sq_code.find("ecco_fbsave::commit_bus_quiet(")
                i_commit = sq_code.find("ecco_fbdurable::commit_transition_t(")
                if not (0 <= i_plan < i_stmt < i_quiet < i_commit):
                    v.append(f"{n}: the heartbeat re-check is not between plan_save and the bus-quiet check / the writer")
                blk = sq_code[i_stmt:i_stmt + len(stmt) + 90]
                if not blk.startswith(stmt + S(" res = ecco_fbsave::save_hb_text(); go = false; } else if (!ecco_fbsave::commit_bus_quiet(")):
                    v.append(f"{n}: the heartbeat re-check refusal is not `res = save_hb_text(); go = false;` chained into the bus-quiet check (else if)")
            if re.search(r"yield|wait_until|delay|script\.execute", code_s):
                v.append(f"{n}: a yield between the re-check and the writer")
        elif re.search("supervision", code, re.I):
            v.append(f"{n} mentions supervision (code or comment)")
    for sid in ("fallback_profile_review", "fallback_profile_capture_dispatch", "fallback_profile_invalidate_candidate", *NEW_SCRIPTS):
        try:
            blk = L.raw_script_block(c.text, sid)
            # FB-B2 hardening: the dispatch holds SAVE_FINAL part 2, whose commit-time re-check names the two symbols
            want = 2 if sid == "fallback_profile_capture_dispatch" else 0
            if len(re.findall("upervision", blk, re.I)) != want:
                v.append(f"script {sid} (raw text) names 'upervision' {len(re.findall('upervision', blk, re.I))} times (want {want})")
        except ValueError:
            v.append(f"script {sid} not found in the raw text")
    a, b = L.region(c.text, "  # Fallback Profile SAVE / INVALIDATE (FB-B2) - RAM-only state of the", "\nnumber:\n") if c.text.count("  # Fallback Profile SAVE / INVALIDATE (FB-B2) - RAM-only state of the") == 1 else (0, 0)
    if a == b:
        v.append("the FB-B2 globals comment block was not found")
    elif re.search("upervision", c.text[a:b], re.I):
        v.append("the FB-B2 globals block (comments included) names 'upervision'")
    if any("upervision" in g.get("id", "") for g in c.fw["globals"][-18:]):
        v.append("a new global is named supervision*")
    for n, code in c.fb.items():
        refs = ids_of(code)
        if "fallback_profile_exec_hb_ok" in refs and n not in ("api:fallback_profile_execute.then[0]", "script:fallback_profile_save.then[0]"):
            v.append(f"{n} names exec_hb_ok")
        if refs & {"fallback_profile_exec_action", "fallback_profile_exec_target_id", "fallback_profile_exec_confirmation"} and n not in (
                "api:fallback_profile_execute.then[0]", "api:fallback_profile_execute.then[1].if.condition", "script:fallback_profile_save.then[0]", "script:fallback_profile_invalidate.then[0]"):
            v.append(f"{n} names exec_action / exec_target_id / exec_confirmation")
    if rhs_of(c.save_lam, "fallback_profile_exec_hb_ok") or "fallback_profile_exec_hb_ok" in assigned(c.save_lam):
        v.append("the SAVE gate assigns exec_hb_ok (it only reads the snapshot)")
    return v


@pin("S-NTP", "the NTP / clock symbols (ntp_synced, ntp_time) appear in FB code only in the SAVE gate (the G11 input) and SAVE_FINAL part 2 (the capture-time re-check), each in its exact statement; none in the INVALIDATE lambda, the REVIEW code, the tick or the boot lambda; random_uint32 only in the REVIEW gate, never in any on_boot lambda")
def d_ntp(c):
    v = []
    users = sorted(n for n, code in c.fb.items() if re.search(r"ntp_", strip_cpp(code)))
    want = sorted({"script:fallback_profile_save.then[0]", c.name_of(c.save_p2)})
    if users != want:
        v.append(f"ntp_ used by {users} (want {want})")
    if var_assignments(c.save_lam, "si").get("time_trusted") != "id(ntp_synced)&&id(ntp_time).now().is_valid()":
        v.append("the SAVE gate's time_trusted is not ntp_synced && now().is_valid()")
    boot_rnd = sorted(n for n, code in c.all_lams if n.startswith("esphome.on_boot") and "random_uint32" in strip_cpp(code))
    base_rnd = sorted(n for n, code in BASE["ctx"].all_lams if n.startswith("esphome.on_boot") and "random_uint32" in strip_cpp(code)) if BASE["ctx"] is not None else None
    if base_rnd is None or boot_rnd != base_rnd:
        v.append(f"random_uint32 in on_boot lambdas {boot_rnd} (the base's: {base_rnd}); FB code must add none")
    if "random_uint32" in strip_cpp(c.boot):
        v.append("the FB boot lambda calls random_uint32")
    where = sorted(n for n, code in c.fb.items() if "random_uint32" in strip_cpp(code))
    if where != ["script:fallback_profile_review.then[0]"]:
        v.append(f"random_uint32 in FB lambdas: {where}")
    return v


FORBIDDEN_ACTION_KINDS = {"button.press", "switch.turn_on", "switch.turn_off", "switch.toggle", "homeassistant.service", "homeassistant.action",
                          "homeassistant.event", "deep_sleep.enter", "script.stop", "script.wait", "esphome.reboot", "api.respond", "light.turn_on", "number.set",
                          "select.set", "text.set", "output.turn_on", "output.turn_off"}
REBOOT_RX = re.compile(r"\b(?:esp_restart|arch_restart|App\s*\.\s*reboot|safe_reboot|reboot\w*|restart\w*|software_reset|esp_deep_sleep|deep_sleep\w*)\b|\.\s*press\s*\(")


@pin("S-REBOOT", "zero reboot (BLK-64): no esp_restart / arch_restart / App.reboot / reboot / restart token and no button press in any FB-B lambda (comments aside), no restart / press / switch / homeassistant / script.stop action in any FB-B script, api action, interval or boot item; the action kinds of every FB-B tree are on a whitelist")
def d_reboot(c):
    v = []
    fbb = {n: code for n, code in c.fb.items() if not re.match(r"interval\[\d+\]", n) or n.startswith(f"interval[{c.interval_index}]")}
    for n, code in fbb.items():
        m = REBOOT_RX.search(strip_cpp(code))
        if m:
            v.append(f"{n}: reboot / restart / press token {m.group(0)!r}")
    allowed = {"gate": {"lambda", "if", "script.execute"}, "save": {"lambda", "if", "script.execute"}, "dispatch": {"lambda", "if", "wait_until", "modbus_client.read_holding_registers"},
               "inv": {"lambda"}, "inv_cand": {"lambda"}, "api": {"lambda", "if", "script.execute"}, "interval": {"lambda"}, "boot": {"lambda"}}
    trees = {"gate": c.review_then, "save": c.save_then, "dispatch": c.top, "inv": c.inv_then, "inv_cand": c.inv_cand.get("then") or [],
             "api": c.api_act.get("then") or [], "interval": (c.interval or {}).get("then") or [], "boot": c.boot_then[3:4]}
    for who, tree in trees.items():
        kinds = set(kinds_of(tree))
        if kinds - allowed[who] or kinds & FORBIDDEN_ACTION_KINDS:
            v.append(f"{who}: action kinds {sorted(kinds - allowed[who])} beyond the whitelist")
    return v


@pin("S-GLOB", "the 18 new globals: exact names / types / initial values, all restore_value no, appended at the end; every SAVE context / exec global is referenced only by the lambdas that own it")
def d_globals(c):
    v = base_violation()
    if v:
        return v
    ids = [g["id"] for g in c.fw["globals"][len(BASE["ctx"].fw["globals"]):]]
    if ids != [g[0] for g in NEW_GLOBALS]:
        v.append(f"new globals {ids}")
    owners = {"fallback_profile_exec_action": {"api", "save", "inv"}, "fallback_profile_arm_on_ms": {"switch", "tick2"}}
    for g in ("fallback_profile_save_ctx_words", "fallback_profile_save_ctx_id", "fallback_profile_save_ctx_prior_class", "fallback_profile_save_ctx_prior_gen",
              "fallback_profile_save_ctx_prior_binding", "fallback_profile_save_ctx_replace_corrupt"):
        refs = sorted(n for n, code in c.all_lams if g in ids_of(code))
        want = sorted({"script:fallback_profile_save.then[0]", c.name_of(c.release), f"interval[{c.interval_index}].then[0]"} | (
            {c.name_of(c.save_p1)} if g in ("fallback_profile_save_ctx_words", "fallback_profile_save_ctx_id") else set()) | (
            {c.name_of(c.save_p2)} if g in ("fallback_profile_save_ctx_prior_class", "fallback_profile_save_ctx_prior_gen", "fallback_profile_save_ctx_prior_binding", "fallback_profile_save_ctx_replace_corrupt") else set()))
        if refs != want:
            v.append(f"{g} is named by {refs} (want {want})")
    return v


# ===========================================================================
# [S] literals, logging, B9 sources, input PODs, authority
# ===========================================================================
BASE_LITERALS = {"-", ""}
LOG_TAGS = {"fbcap", "fbdurable"}


def _fb_logs(ctx) -> list[tuple[str, str, str | None, str | None]]:
    out = []
    for n, code in ctx.fb.items():
        for k in log_calls(code):
            out.append((n, k["level"], k["tag"], k["fmt"]))
    return out


@pin("S-LIT", "every string literal in FB lambdas is on the allow-list ('-', '', the log tags 'fbcap' / 'fbdurable' as ESP_LOG tags only, the FB-B1 six format strings, and '%s' only as the format of the six FB-B2 'fbdurable' log sites); counts derived from the YAML are compared with an independent raw-text count")
def d_literals(c):
    v = base_violation()
    fb1_fmts: list = []
    if BASE["ctx"] is not None:
        fb1_fmts = sorted((lv, tag, fmt) for _n, lv, tag, fmt in _fb_logs(BASE["ctx"]))
    now = _fb_logs(c)
    live_fbcap = sorted((lv, tag, fmt) for _n, lv, tag, fmt in now if tag == "fbcap")
    if fb1_fmts and live_fbcap != fb1_fmts:
        v.append(f"the 'fbcap' log sites changed: {live_fbcap} vs the base's {fb1_fmts}")
    if len(fb1_fmts) != 6 and BASE["ctx"] is not None:
        v.append(f"the base has {len(fb1_fmts)} FB log sites (want 6)")
    new = [(n, lv, tag, fmt) for n, lv, tag, fmt in now if tag == "fbdurable"]
    if sorted((lv, fmt) for _n, lv, _t, fmt in new) != sorted([("W", "%s")] * 4 + [("I", "%s")] * 2):
        v.append(f"the 'fbdurable' log sites {[(n[-20:], lv, fmt) for n, lv, _t, fmt in new]} (want exactly six, format \"%s\": 4 WARN + 2 INFO)")
    by = {}
    for n, lv, _t, _f in new:
        by.setdefault(n, []).append(lv)
    if by != {c.name_of(c.save_p2): ["W", "W", "I", "W"], c.name_of(c.inv_lam): ["I", "W"]}:
        v.append(f"the 'fbdurable' log sites by lambda {by} (want SAVE_FINAL part 2: W W I W; INVALIDATE: I W)")
    if {t for _n, _l, t, _f in now} - LOG_TAGS or any(t is None or f is None for _n, _l, t, f in now):
        v.append("an ESP_LOG* call that is not a plain literal tag + format")
    # independent raw-text count
    raw = "\n".join(ln for ln in c.text.splitlines() if not ln.lstrip().startswith("#"))
    n_fbcap = len(re.findall(r'ESP_LOG[A-Z]\(\s*"fbcap"', raw))
    n_fbdur = len(re.findall(r'ESP_LOG[A-Z]\(\s*"fbdurable"', raw))
    if (n_fbcap, n_fbdur) != (6, 6) or raw.count('"fbdurable"') != 6 or raw.count('"fbcap"') != 6:
        v.append(f"raw-text log census fbcap {n_fbcap}/{raw.count('\"fbcap\"')} fbdurable {n_fbdur}/{raw.count('\"fbdurable\"')} (want 6 and 6)")
    if BASE["text"] is not None and raw.count('"%s"') - "\n".join(ln for ln in BASE["text"].splitlines() if not ln.lstrip().startswith("#")).count('"%s"') != 6:
        v.append("the literal \"%s\" does not occur exactly 6 times more than in the base")
    # literal allow-list
    for n, code in c.fb.items():
        calls = log_calls(code)
        fmts = Counter(k["fmt"] for k in calls if k["fmt"] is not None)
        tags = Counter(k["tag"] for k in calls)
        for lit, k in Counter(literals(code)).items():
            if lit in BASE_LITERALS:
                continue
            if lit in LOG_TAGS and tags.get(lit, 0) == k:
                continue
            if lit in fmts and fmts[lit] == k:
                continue
            v.append(f"{n}: literal {lit[:60]!r}")
    for n, lv, tag, fmt in new:
        if "id(" in (fmt or "") or "${" in (fmt or ""):
            v.append(f"{n}: a log format carrying id( / ${{")
    for n in (c.name_of(c.save_p2), c.name_of(c.inv_lam)):
        for k in log_calls(c.fb.get(n, "")):
            if k["tag"] == "fbdurable" and not (len(k["args"]) == 1 and re.fullmatch(r"(?:rc0|rc1|lg)\.c_str\(\)", k["args"][0])):
                v.append(f"{n}: an fbdurable log carries {k['args']} (want one finished header text .c_str())")
    for var, builder in (("rc0", "ecco_fbsave::replace_corrupt_log_text("), ("rc1", "ecco_fbsave::replace_corrupt_log_text("), ("lg", "ecco_fbsave::txn_log_text(")):
        if not any(has(code, f"const ecco_fbcap::TextBuf {var} = {builder}") for code in (c.save_p2, c.inv_lam)):
            v.append(f"the log text {var} is not built by {builder}")
    return v


# The B9 prefixes an FB-B2 lambda may publish (FINAL architecture 4.7 / 4.8 and the FB-B1 D8 list), plus the lowercase in-progress line
LOCKED_B9_PREFIXES = ("SAVE REFUSED", "SAVED", "SAVE NOT COMMITTED", "SAVE OUTCOME UNKNOWN", "INVALIDATE REFUSED", "INVALIDATED",
                      "INVALIDATE NOT COMMITTED", "INVALIDATE OUTCOME UNKNOWN", "REFUSED", "RESTORE REFUSED", "ACKNOWLEDGE REFUSED", "INTERNAL")
B9_PROGRESS = ("save in progress",)


def _mirror_module(text: str):
    """The Python mirror registry/fallback_save.py compiled from `text` (the context's override or the disk copy) as a fresh module."""
    import types
    name = "fallback_save_ctx"
    mod = types.ModuleType(name)
    mod.__file__ = str(L.ROOT / "registry" / "fallback_save.py")
    sys.modules[name] = mod   # dataclasses resolve their own module through sys.modules
    try:
        exec(compile(text, mod.__file__, "exec"), mod.__dict__)  # noqa: S102 - the repo's own mirror (or a deliberately broken copy of it)
    finally:
        sys.modules.pop(name, None)
    return mod


@pin("S-B9SRC", "every operator-visible text an FB-B2 lambda publishes comes from a header builder: B9 is published only from the pinned header-built TextBufs (no literal), every TextBuf assigned in the new lambdas is built by an ecco_fbsave / ecco_fbcap builder or is a `.text` of a header result; the zero-argument builders it relies on carry a locked B9 prefix")
def d_b9sources(c):
    v = []
    want_pub = {
        "script:fallback_profile_save.then[0]": {"g1.text.c_str()", "t.c_str()"},
        c.name_of(c.save_p1): {"res.c_str()"},
        c.name_of(c.save_p2): {"t.c_str()", "res.c_str()"},
        "script:fallback_profile_invalidate.then[0]": {"i1.text.c_str()", "ir.text.c_str()", "plan.text.c_str()", "busy.c_str()", "t.c_str()"},
    }
    ok_rhs = re.compile(r"^(?:ecco_fbsave::\w+\(.*\)|ecco_fbcap::(?:internal_context_text|b[2-8]_text)\(.*\)|(?:sr|plan|fg|g1|i1|ir)\.text|\{\})$|^ecco_fbsave::txn_outcome_text\(.*\)$")
    for n, code in c.fb.items():
        if n not in want_pub:
            continue
        got = set(publish_args(code, B9))
        if got != want_pub[n]:
            v.append(f"{n}: B9 published from {sorted(got)} (want {sorted(want_pub[n])})")
        s = strip_cpp(code)
        for m in re.finditer(r"(?:const\s+)?ecco_fbcap::TextBuf\s+(\w+)\s*(?:=\s*([^;]+))?;|(?<![\w.])(res|t|busy)\s*=(?!=)\s*([^;]+);", s):
            var, rhs = (m.group(1), m.group(2)) if m.group(1) else (m.group(3), m.group(4))
            if rhs is None:
                continue
            r = re.sub(r"\s+", "", rhs)
            if r.startswith("ecco_fbcap::b3_text(") or var in ("lg", "rc0", "rc1", "brk"):
                if r.startswith("ecco_fbcap::b3_text(") or r.startswith(("ecco_fbsave::txn_log_text(", "ecco_fbsave::replace_corrupt_log_text(")):
                    continue
            if not ok_rhs.match(r):
                v.append(f"{n}: TextBuf {var} = {r[:70]} is not built by a header builder")
        if '"' in re.sub(r'ESP_LOG[A-Z]\([^;]*;', "", s).replace('""', "").replace('"-"', ""):
            v.append(f"{n}: a string literal outside the allowed ones")
    # every PARAMETERLESS ecco_fbsave text builder an FB-B2 lambda names is evaluated through the mirror text of THIS context (a mirror
    # mutant is therefore seen) and must start with a locked B9 prefix (the D8 list, written here independently of the header suites),
    # stay <= 200 characters and ASCII, and never say failed / deferred / supervision
    fs = _mirror_module(c.file("registry/fallback_save.py"))
    named = sorted({m.group(1) for n, code in c.fb.items() if n in want_pub for m in re.finditer(r"\becco_fbsave::(\w+_text)\s*\(\s*\)", strip_cpp(code))})
    for must in ("save_in_progress_text", "save_bus_quiet_text", "save_time_text", "invalidate_busy_text"):
        if must not in named:
            v.append(f"the FB-B2 lambdas no longer name {must}() (the zero-argument texts this pin evaluates)")
    for fn in sorted(set(named) | {"save_in_flight_text", "save_arm_off_text"}):
        if not hasattr(fs, fn):
            v.append(f"{fn}() is not a builder of the mirror")
            continue
        t = str(getattr(fs, fn)())
        if not (t.startswith(LOCKED_B9_PREFIXES) or t.startswith(B9_PROGRESS)):
            v.append(f"{fn}() = {t[:40]!r} does not start with a locked B9 prefix")
        if len(t) > 200 or not t.isascii() or re.search(r"(?i)failed|deferred|supervision", t):
            v.append(f"{fn}() = {t[:40]!r} is longer than 200 characters / not ASCII / names failed, deferred or supervision")
    return v


INTEGRITY_P1 = ("if (!ecco_fbsave::save_integrity_ok(id(fallback_profile_op_in_progress), id(fallback_profile_op_purpose)) || "
                "!id(fallback_profile_save_ctx_valid) || id(fallback_profile_save_ctx_id) == 0) { res = ecco_fbcap::internal_context_text(); go = false; }")
INTEGRITY_P2 = ("if (!ecco_fbsave::save_integrity_ok(id(fallback_profile_op_in_progress), id(fallback_profile_op_purpose)) || "
                "!id(fallback_profile_save_ctx_valid)) { res = ecco_fbcap::internal_context_text(); go = false; }")
B3_RESET = ('ecco_fbcap::TextBuf t = ecco_fbcap::b3_text({state}, false, 0, 0, 0, id(fallback_profile_obl_text).c_str(), '
            'id(fallback_profile_probe_latch), "-");')


@pin("S-DECIDE", "the decision skeleton of the SAVE lambdas, as exact statements derived from the design (brief A.4 steps 0 / 6, S1 8.5): SAVE_FINAL part 1 / part 2 open with the purpose / hand-over guard, the pristine `go = true`, the exact integrity guard (part 1 also refuses a context with id 0), part 2 the trusted-clock re-check `if (!clock_trusted_for_save(...))`; the gate result routing (`gate_accepted` -> dispatch, obligation text, in-progress text vs the refusal), the B3 reset (no candidate) in the gate and in both parts, the final commit log level")
def d_decide(c):
    v = []
    h1 = ("if (id(fallback_profile_op_purpose) != ecco_fbsave::PURPOSE_SAVE) return; id(fallback_profile_save_verified) = false; ecco_fbdurable::EspNvs nvs; "
          "ecco_fbcap::TextBuf res{}; bool go = true; " + INTEGRITY_P1 + " if (go && id(fallback_profile_read_failed)) {")
    if not sq(c.save_p1).startswith(S(h1)):
        v.append("SAVE_FINAL part 1 does not open with: purpose guard, verified reset, EspNvs, `TextBuf res{}`, `bool go = true`, the exact integrity guard (op in flight, purpose SAVE, context taken, id != 0)")
    h2 = ("if (!id(fallback_profile_save_verified)) return; id(fallback_profile_save_verified) = false; ecco_fbdurable::EspNvs nvs; ecco_fbcap::TextBuf res{}; "
          "bool go = true; uint32_t epoch = 0; " + INTEGRITY_P2 + " if (go) { const bool time_ok = id(ntp_synced) && id(ntp_time).now().is_valid(); "
          "epoch = time_ok ? (uint32_t) id(ntp_time).now().timestamp : 0u; if (!ecco_fbsave::clock_trusted_for_save(time_ok, epoch)) { "
          "res = ecco_fbsave::save_time_text(); go = false; } } if (go) {")
    if not sq(c.save_p2).startswith(S(h2)):
        v.append("SAVE_FINAL part 2 does not open with: hand-over guard + reset, EspNvs, `TextBuf res{}`, `bool go = true`, `uint32_t epoch = 0`, the exact integrity guard, the trusted-clock re-check")
    # SAVE_FINAL part 1: the verification steps 1-5 as exact statements, in order (first failure wins: every step is guarded by `go`)
    probe = ("if (f0.gr.{flag}) {{ ecco_durable::ValidMarker m{{}}; ecco_fbdurable::ReadDiag d{{}}; const uint8_t ld = ecco_fbdurable::read_direct_t(nvs, "
             "ecco_durable::key_for(ecco_durable::{tag}), m, d); pr.{slot} = ecco_fbcap::probe_result(ld, m.magic, m.state); }}")
    p1_steps = [
        "if (go && id(fallback_profile_read_failed)) { res = ecco_fbsave::save_read_fail_text(id(fallback_profile_read_fail_code), id(fallback_profile_step), "
        "id(fallback_profile_read_exception_code)); go = false; }",
        "if (go && ecco_fbcap::first_diff(id(fallback_profile_pass1), id(fallback_profile_pass2)) >= 0) { "
        "res = ecco_fbsave::save_changed_during_read_text(id(fallback_profile_pass1), id(fallback_profile_pass2)); go = false; }",
        "if (go && ecco_fbcap::first_diff(id(fallback_profile_save_ctx_words), id(fallback_profile_pass2)) >= 0) { "
        "res = ecco_fbsave::save_changed_since_review_text(id(fallback_profile_save_ctx_words), id(fallback_profile_pass2)); go = false; }",
        "if (go) { const ecco_fbcap::Refusals l2 = ecco_fbcap::capture_refusals(id(fallback_profile_pass2), ${ecco_inverter_tou_power_ceiling_w}); "
        "if (l2.count > 0) { res = ecco_fbsave::save_l2_text(l2, id(fallback_profile_pass2)); go = false; } }",
        "if (go) { ecco_fbcap::GateInputs gi{};",
        "ecco_fbcap::ProbeResults pr{}; { const ecco_fbsave::FinalGate f0 = ecco_fbsave::final_gate_decide(gi, pr); "
        "if (f0.gr.code == ecco_fbcap::GATE_NEED_PROBE) { "
        + probe.format(flag="probe_fp", tag="FREE_POWER_VALID_TAG", slot="fp") + " "
        + probe.format(flag="probe_dump", tag="DUMP_TO_GRID_VALID_TAG", slot="dump") + " "
        + probe.format(flag="probe_r244", tag="REG244_VALID_TAG", slot="r244") + " } } "
        "const ecco_fbsave::FinalGate fg = ecco_fbsave::final_gate_decide(gi, pr); id(fallback_profile_probe_latch) = fg.gr.latch; "
        "id(fallback_profile_obl_text) = fg.gr.obl.c_str(); if (fg.gr.code != ecco_fbcap::GATE_ACCEPT) { res = fg.text; go = false; } } "
        "if (go) { id(fallback_profile_save_verified) = true; } else {",
    ]
    if not seq_ok(c.save_p1, p1_steps):
        pos = seq_find(c.save_p1, p1_steps)
        bad_i = next((i for i, x in enumerate(pos) if x < 0), -1)
        v.append(f"SAVE_FINAL part 1: verification step {bad_i + 1} of {len(p1_steps)} is missing, altered or out of order (steps 1-5 as exact guarded statements)")
    # SAVE_FINAL part 2: the fresh read / mirror / plan prologue and the post-commit text builders
    h2b = ("if (go) { ecco_fallback::FallbackProfileV1 p{}; ecco_fbdurable::FailbackProvisionV1 w{}; ecco_fbdurable::ReadDiag dp{}; ecco_fbdurable::ReadDiag dw{}; "
           "const uint8_t lp = ecco_fbdurable::read_direct_t(nvs, ecco_fbdurable::FALLBACK_PROFILE_KEY, p, dp); "
           "const uint8_t lw = ecco_fbdurable::read_direct_t(nvs, ecco_fbdurable::FAILBACK_PROVISION_KEY, w, dw); "
           "const bool healthy = ecco_fbdurable::nvs_healthy(); ecco_fbsave::SavePlanInputs pi{}; { ecco_fbcap::ReadInputs in{};")
    if not sq(c.save_p2).startswith(S(h2 + " " + h2b[len("if (go) {"):])):
        v.append("SAVE_FINAL part 2: the fresh-read prologue (p / w / dp / dw, the two direct reads FBP then FBW, ONE health check, the plan and read inputs) is not the exact one")
    # gate result routing
    for who, lam, needle in (
            ("SAVE gate", c.save_lam, "if (sr.obl.size() > 0) id(fallback_profile_obl_text) = sr.obl.c_str();"),
            ("SAVE gate", c.save_lam, B3_RESET.format(state="id(fallback_profile_capture_state)")),
            ("SAVE gate", c.save_lam, "ecco_fbcap::TextBuf t = ecco_fbsave::save_in_progress_text(); if (sr.code != ecco_fbsave::SG_ACCEPT) t = sr.text;"),
            ("SAVE_FINAL part 1", c.save_p1, "id(fallback_profile_capture_state) = ecco_fbcap::CAPTURE_IDLE; { " + B3_RESET.format(state="ecco_fbcap::CAPTURE_IDLE")),
            ("SAVE_FINAL part 2", c.save_p2, "id(fallback_profile_capture_state) = ecco_fbcap::CAPTURE_IDLE; { " + B3_RESET.format(state="ecco_fbcap::CAPTURE_IDLE")),
            ("INVALIDATE", c.inv_lam, 'if (o == ecco_fbdurable::TXN_COMMITTED) { ESP_LOGI("fbdurable", "%s", lg.c_str()); } else { ESP_LOGW("fbdurable", "%s", lg.c_str()); }'),
            ("SAVE_FINAL part 2", c.save_p2, 'if (o == ecco_fbdurable::TXN_COMMITTED) { ESP_LOGI("fbdurable", "%s", lg.c_str()); } else { ESP_LOGW("fbdurable", "%s", lg.c_str()); }')):
        if not has(lam, needle):
            v.append(f"{who}: the exact statement is missing or changed: {needle[:100]}")
    # INVALIDATE: the in-flight call, the fresh-read prologue and the busy / bus-input statements as exact text
    inv_prologue = ("ecco_fbdurable::EspNvs nvs; ecco_fallback::FallbackProfileV1 p{}; ecco_fbdurable::FailbackProvisionV1 w{}; ecco_fbdurable::ReadDiag dp{}; "
                    "ecco_fbdurable::ReadDiag dw{}; const uint8_t lp = ecco_fbdurable::read_direct_t(nvs, ecco_fbdurable::FALLBACK_PROFILE_KEY, p, dp); "
                    "const uint8_t lw = ecco_fbdurable::read_direct_t(nvs, ecco_fbdurable::FAILBACK_PROVISION_KEY, w, dw); "
                    "const bool healthy = ecco_fbdurable::nvs_healthy(); ecco_fbsave::InvalidatePlanInputs pj{}; { ecco_fbcap::ReadInputs in{};")
    for who, lam, needle in (
            ("INVALIDATE", c.inv_lam, inv_prologue),
            ("INVALIDATE", c.inv_lam, "const ecco_fbsave::InvalidateGateResult i1 = ecco_fbsave::invalidate_in_flight_gate(id(fallback_profile_op_in_progress), "
                                      "id(fallback_profile_capture_dispatch).is_running());"),
            ("INVALIDATE", c.inv_lam, "ecco_fbcap::BusInputs bn{};"),
            ("INVALIDATE", c.inv_lam, "ecco_fbcap::TextBuf busy = ecco_fbsave::invalidate_busy_text(); if (id(fallback_profile_last_result_text).state != busy.c_str()) "
                                      "id(fallback_profile_last_result_text).publish_state(busy.c_str()); return;"),
            ("SAVE gate", c.save_lam, "const ecco_fbsave::SaveGateResult g1 = ecco_fbsave::save_in_flight_gate(id(fallback_profile_op_in_progress), "
                                      "id(fallback_profile_capture_dispatch).is_running());")):
        if sq(lam).count(S(needle)) != 1:
            v.append(f"{who}: the exact statement is missing, changed or repeated: {needle[:100]}")
    # the outcome text and the transaction log come from the one commit outcome in BOTH commit lambdas
    for who, lam in (("SAVE_FINAL part 2", c.save_p2), ("INVALIDATE", c.inv_lam)):
        for needle in ("ecco_fbcap::TextBuf t = ecco_fbsave::txn_outcome_text(plan.op, o, r, plan.generation, p.generation);",
                       "const ecco_fbcap::TextBuf lg = ecco_fbsave::txn_log_text(plan.op, o, r, plan.generation);"):
            if sq(lam).count(S(needle)) != 1:
                v.append(f"{who}: the exact statement is missing, changed or repeated: {needle[:100]}")
    # the B7 / B8 refresh before and after the commit (the class used is the one composed from the SAME records the texts are built from)
    for who, lam in (("SAVE_FINAL part 2", c.save_p2), ("INVALIDATE", c.inv_lam)):
        for needle in ("ecco_fbcap::TextBuf t = ecco_fbcap::b7_text(lp, p, e.cls);", "ecco_fbcap::TextBuf t = ecco_fbcap::b8_text(lp, p, e.cls);",
                       "ecco_fbcap::TextBuf t = ecco_fbcap::b7_text(m.p_load, m.p, e2.cls);", "ecco_fbcap::TextBuf t = ecco_fbcap::b8_text(m.p_load, m.p, e2.cls);",
                       "ecco_fbdurable::ReadLatch lat{id(fallback_profile_present_seen), id(fallback_profile_read_anomaly)};",
                       "const ecco_fbdurable::EffectiveProfile e2 = ecco_fbdurable::compose_profile_class(m.p_load, m.p, m.w_load, m.w, id(fallback_profile_read_anomaly));",
                       "const ecco_fbdurable::MirrorRecords m = ecco_fbdurable::mirror_after(o, r, p, lp, w, lw);"):
            if sq(lam).count(S(needle)) != 1:
                v.append(f"{who}: the exact statement is missing, changed or repeated: {needle[:100]}")
    sc = c.save_then[1].get("if") if len(c.save_then) > 1 and isinstance(c.save_then[1], dict) else None
    if (not isinstance(sc, dict) or set(sc) != {"condition", "then"} or sc["condition"] != {"lambda": "return id(fallback_profile_gate_accepted);"}
            or sc["then"] != [{"lambda": "id(fallback_profile_gate_accepted) = false;"}, {"script.execute": {"id": "fallback_profile_capture_dispatch"}}]):
        v.append("the SAVE script's second action is not `if (return gate_accepted) { gate_accepted = false; script.execute dispatch }` with no else")
    if len(c.save_then) != 2:
        v.append(f"the SAVE script has {len(c.save_then)} actions (want the gate lambda and the one `if`)")
    return v


@pin("S-ORDER", "every input POD is declared, then FULLY assigned, BEFORE the decision that consumes it (a field filled after the call would be read as its default): SaveGateInputs si / GateInputs gi before save_gate_decide; gi before final_gate_decide; ReadInputs in before evaluate_read; SavePlanInputs pi before plan_save; InvalidateGateInputs ii before invalidate_gate_decide; InvalidatePlanInputs pj before plan_invalidate; BusInputs bn before invalidate_bus_idle")
def d_order(c):
    v = []
    jobs = (("SAVE gate", c.save_lam, (("si", "ecco_fbsave::save_gate_decide("), ("gi", "ecco_fbsave::save_gate_decide("))),
            ("SAVE_FINAL part 1", c.save_p1, (("gi", "ecco_fbsave::final_gate_decide("),)),
            ("SAVE_FINAL part 2", c.save_p2, (("in", "ecco_fbcap::evaluate_read("), ("pi", "ecco_fbsave::plan_save("))),
            ("INVALIDATE", c.inv_lam, (("ii", "ecco_fbsave::invalidate_gate_decide("), ("in", "ecco_fbcap::evaluate_read("),
                                       ("pj", "ecco_fbsave::plan_invalidate("), ("bn", "ecco_fbsave::invalidate_bus_idle("))))
    for who, lam, pairs in jobs:
        s = sq(lam)
        for var, consumer in pairs:
            decl = s.find(var + "{};")
            call = s.find(S(consumer))
            ass = [m.start() for m in re.finditer(r"(?<![\w.])%s\.[\w.]+=(?!=)" % re.escape(var), s)]
            if decl < 0 or call < 0 or not ass:
                v.append(f"{who}: `{var}` declaration / assignments / consumer `{consumer}` not found")
                continue
            if not decl < min(ass):
                v.append(f"{who}: `{var}` is assigned before it is declared")
            if not max(ass) < call:
                v.append(f"{who}: a field of `{var}` is assigned AFTER the consumer {consumer}...) (it would be read as its default)")
    return v


PUB_STMT_RX = re.compile(r"if\((?P<extra>res\.size\(\)>0&&)?id\((?P<e>\w+)\)\.state!=(?P<a>.+)\)id\((?P=e)\)\.publish_state\((?P=a)\);")


def publish_statements(code: str) -> list[str]:
    """Squashed text of every STATEMENT (from the previous ; { or } up to its closing ;) that contains a publish_state call."""
    s = sq(code)
    out = []
    for m in re.finditer(r"publish_state\(", s):
        start = max(s.rfind(";", 0, m.start()), s.rfind("{", 0, m.start()), s.rfind("}", 0, m.start())) + 1
        out.append(s[start:s.find(";", m.start()) + 1])
    return out


@pin("S-PUBGUARD", "every text FB-B2 code publishes uses the publish-on-change idiom exactly: `if (id(E).state != X) id(E).publish_state(X);` with the SAME entity and value on both sides, E one of the nine B-texts, the only extra conjunct being `res.size() > 0 &&` on the final refusal publish of SAVE_FINAL part 2 (a flipped / unguarded / mismatched guard would silence or spam a text)")
def d_pubguard(c):
    v = []
    texts = set(TS.values())
    # publish census (design: B9 refusals / outcome, B3, and the B1 + B2 + B7 + B8 refresh after each fresh read and again after the commit):
    # SAVE gate G1 B9 + B3 + B9 = 3; INVALIDATE I1, gate, plan, busy, outcome B9 = 5 + 2 x 4 = 13; part 1 B3 + B9 = 2; part 2 2 x 4 + outcome B9 + B3 + res B9 = 11
    jobs = (("SAVE gate", c.save_lam, 3, False), ("INVALIDATE", c.inv_lam, 13, False), ("SAVE_FINAL part 1", c.save_p1, 2, False),
            ("SAVE_FINAL part 2", c.save_p2, 11, True))
    for who, lam, want_n, allow_res in jobs:
        stmts = publish_statements(lam)
        if len(stmts) != want_n:
            v.append(f"{who}: {len(stmts)} publish_state statements (want {want_n})")
        n_res = 0
        for st in stmts:
            m = PUB_STMT_RX.fullmatch(st)
            if not m:
                v.append(f"{who}: a publish that is not the publish-on-change idiom: {st[:110]}")
                continue
            if m.group("e") not in texts:
                v.append(f"{who}: publishes {m.group('e')}, which is not one of the nine B-texts")
            if m.group("extra"):
                n_res += 1
                if not allow_res or m.group("e") != B9 or m.group("a") != "res.c_str()":
                    v.append(f"{who}: the `res.size() > 0 &&` conjunct outside the final refusal publish of SAVE_FINAL part 2: {st[:90]}")
        if allow_res and n_res != 1:
            v.append(f"{who}: {n_res} `res.size() > 0 &&` publishes (want exactly the one final refusal publish)")
        if allow_res and not sq(lam).endswith(S("if (res.size() > 0 && id(fallback_profile_last_result_text).state != res.c_str()) id(fallback_profile_last_result_text).publish_state(res.c_str());")):
            v.append(f"{who}: the final statement is not the guarded refusal publish")
    return v


def _pod_check(code: str, var: str, struct: str, structs: dict, table: dict, who: str, exempt=lambda f: False, strict_sources=True) -> list[str]:
    v = []
    fields = flat_fields(structs, struct)
    got = var_assignments(code, var)
    counts = var_assignment_count(code, var)
    miss = [f for f in fields if f not in got and not exempt(f)]
    if miss:
        v.append(f"{who}: {struct} fields never assigned: {miss}")
    unknown = [f for f in got if f not in fields]
    if unknown:
        v.append(f"{who}: {var}.{unknown} is not a field of {struct}")
    for f, rhs in got.items():
        if f in table and strict_sources and rhs != S(table[f]):
            v.append(f"{who}: {var}.{f} = {rhs!r} (want {S(table[f])!r})")
    dup = [f for f, n in counts.items() if n > 1]
    if dup:
        v.append(f"{who}: {var}.{dup} assigned more than once")
    if any(exempt(f) for f in got):
        v.append(f"{who}: an exempt field is assigned {[f for f in got if exempt(f)]}")
    return v


def _run_flags(code: str, var: str, tick=False) -> list[str]:
    v = []
    for fld, rhs in var_assignments(code, var).items():
        if fld in RUN_SETS:
            ids = set(re.findall(r"id\((\w+)\)\.is_running\(\)", rhs))
            if not re.fullmatch(r"id\(\w+\)\.is_running\(\)(?:\|\|id\(\w+\)\.is_running\(\))*", rhs) or ids != RUN_SETS[fld]:
                v.append(f"{var}.{fld} = {rhs!r} (want exactly {sorted(RUN_SETS[fld])})")
    return v


@pin("S-POD", "FIELD-ASSIGNMENT COMPLETENESS: every field of SaveGateInputs, InvalidateGateInputs, SavePlanInputs, InvalidatePlanInputs and of ecco_fbcap::GateInputs / ReadInputs / ReviewInputs / BusInputs is assigned (once, from the pinned source) in every lambda that builds it; only the FpDomain / DumpDomain `expired` flags stay unassigned, on purpose")
def d_pod(c):
    v = []
    hs = parse_structs(c.file("firmware/include/ecco_fallback_save.h"))
    hc = parse_structs(c.file("firmware/include/ecco_fallback_capture.h"))
    st = {**hc, **hs}
    expired = lambda f: f.endswith("expired")  # noqa: E731 - REVIEW / SAVE never read the clock for the domains
    jobs = [
        ("SAVE gate si", c.save_lam, "si", "SaveGateInputs", SI_RHS, lambda f: False),
        ("SAVE gate gi", c.save_lam, "gi", "GateInputs", GATE_RHS, expired),
        ("SAVE_FINAL part 1 gi", c.save_p1, "gi", "GateInputs", GATE_RHS, expired),
        ("SAVE_FINAL part 2 pi", c.save_p2, "pi", "SavePlanInputs", PI_RHS, lambda f: False),
        ("SAVE_FINAL part 2 in", c.save_p2, "in", "ReadInputs", IN_RHS, lambda f: False),
        ("INVALIDATE ii", c.inv_lam, "ii", "InvalidateGateInputs", II_RHS, lambda f: False),
        ("INVALIDATE bn", c.inv_lam, "bn", "BusInputs", {k[4:]: x for k, x in BUS_RHS.items()}, lambda f: False),
        ("INVALIDATE in", c.inv_lam, "in", "ReadInputs", IN_RHS, lambda f: False),
        ("INVALIDATE pj", c.inv_lam, "pj", "InvalidatePlanInputs", PJ_RHS, lambda f: False),
        ("REVIEW_FINAL in", c.review_final, "in", "ReadInputs", IN_RHS, lambda f: False),
        ("REVIEW_FINAL ri", c.review_final, "ri", "ReviewInputs", RI_RHS, lambda f: False),
    ]
    for who, code, var, struct, table, ex in jobs:
        if not code:
            v.append(f"{who}: the lambda was not found")
            continue
        v += _pod_check(code, var, struct, st, table, who, ex)
        if struct == "GateInputs":
            v += _run_flags(code, var)
    return v


@pin("S-AUTH", "generic zero-authority pins over EVERY FB lambda: only fallback_profile_invalidate_candidate is ever .execute()d; script.execute actions: review button -> gate, gate -> dispatch, SAVE gate -> dispatch, api router -> the two scripts, nothing else; only FB globals (+ the shared write mutex in the two gate accept branches and RELEASE) are modified; no foreign symbol outside the pinned gate-input statements")
def d_authority(c):
    v = []
    fbg = fb_global_ids() | {"fallback_profile_" + x for x in (
        "boot_loaded", "boot_salt", "fbs_slot", "bytes", "load", "class", "why", "present_seen", "read_anomaly", "seen_hw_gen", "op_in_progress", "op_purpose",
        "op_started_ms", "capture_state", "gate_accepted", "step", "step_terminal", "read_failed", "read_fail_code", "read_exception_code", "pass1",
        "pass2", "probe_latch", "obl_text", "invalidate_reason", "cand_valid", "cand_saveable", "cand_words", "cand_id", "cand_ms", "cand_seq",
        "cand_prior_class", "cand_prior_gen", "cand_prior_binding", "cand_warnings", "cand_writes_fp", "cand_sv", "cand_dx", "cand_dc", "cand_di",
        "cand_has_stored")} | {"fallback_witness_bytes", "fallback_witness_load"}
    mw_ok = {"script:fallback_profile_review.then[0]", "script:fallback_profile_save.then[0]", c.name_of(c.release)}
    for n, code in c.fb.items():
        s = strip_cpp(code)
        if not set(EXEC_RX.findall(s)) <= {"fallback_profile_invalidate_candidate"}:
            v.append(f"{n}: executes {sorted(set(EXEC_RX.findall(s)) - {'fallback_profile_invalidate_candidate'})}")
        if len(re.findall(r"(?:\.|->)\s*execute\s*\(", s)) != len(EXEC_RX.findall(s)):
            v.append(f"{n}: an .execute() that is not id(<script>).execute()")
        if re.search(r"(?:\.|->)\s*(?:stop|abort|terminate)\s*\(|esp_restart|\bApp\.|global_preferences|make_preference|esp_ota|esp_deep_sleep", s):
            v.append(f"{n}: stops a script, reboots or touches the preference store")
        stray = {x for x in assigned(code) if x not in fbg and not (x == "manual_write_in_progress" and n in mw_ok)}
        if stray and not n.startswith("api:fallback_profile_execute"):
            v.append(f"{n}: modifies the foreign global(s) {sorted(stray)}")
        if re.search(r"(?<!&)&(?!&)\s*id\(", s):
            v.append(f"{n}: takes the address of a global")
    def execs(actions):
        out = []
        for a in actions or []:
            if not isinstance(a, dict):
                continue
            for k, b in a.items():
                if k == "script.execute":
                    out.append(b.get("id") if isinstance(b, dict) else b)
                elif k == "if" and isinstance(b, dict):
                    out += execs(b.get("then")) + execs(b.get("else"))
        return out
    got = {"review": execs(c.review_then), "save": execs(c.save_then), "dispatch": execs(c.top), "inv": execs(c.inv_then), "interval": execs((c.interval or {}).get("then")),
           "boot": execs(c.boot_then[3:4]), "api": execs(c.api_act.get("then"))}
    want = {"review": ["fallback_profile_capture_dispatch"], "save": ["fallback_profile_capture_dispatch"], "dispatch": [], "inv": [], "interval": [], "boot": [],
            "api": ["fallback_profile_invalidate", "fallback_profile_save"]}
    if got != want:
        v.append(f"script.execute actions {got} (want {want})")
    # the SAVE / INVALIDATE scripts are started only by the api action (no other script / button / interval names them)
    for sid in NEW_SCRIPTS:
        users = []
        def find(x, path):
            if isinstance(x, dict):
                for k, y in x.items():
                    if k == "script.execute" and (y == sid or (isinstance(y, dict) and y.get("id") == sid)):
                        users.append(path)
                    find(y, path)
            elif isinstance(x, list):
                for y in x:
                    find(y, path)
        for sect, body in c.fw.items():
            if sect.startswith("_"):
                continue
            if sect == "script":
                for sc in body:
                    find(sc.get("then"), f"script:{sc['id']}")
            elif sect == "api":
                for a in body.get("actions") or []:
                    find(a, f"api:{a.get('action')}")
            else:
                find(body, sect)
        if users != ["api:fallback_profile_execute"]:
            v.append(f"{sid} is started by {users} (only the api action may start it)")
        for n, code in c.all_lams:
            if f"id({sid})" in strip_cpp(code) and ".execute" in strip_cpp(code):
                v.append(f"{n}: executes {sid} from a lambda")
    # foreign ids named by the new lambdas (outside the pinned input statements)
    roles = {"script:fallback_profile_save.then[0]": GATE_FOREIGN | {"ntp_synced", "ntp_time", *COUNTERS},
             c.name_of(c.save_p1): GATE_FOREIGN, c.name_of(c.save_p2): {"ntp_synced", "ntp_time", "manual_write_in_progress", "correction_in_progress", "inverter_modbus",
                                    "supervision_state", "supervision_stable"},  # FB-B2 hardening: commit-time heartbeat re-check
             "script:fallback_profile_invalidate.then[0]": GATE_FOREIGN | {"inverter_modbus"}}
    ents = set(TS.values()) | {"fallback_profile_capture_dispatch", ARM, "fallback_profile_invalidate_candidate"}
    for n, foreign in roles.items():
        extra = ids_of(c.fb.get(n, "")) - fbg - ents - foreign
        if extra:
            v.append(f"{n}: names the foreign symbol(s) {sorted(extra)}")
    return v


@pin("S-INTERVAL", "the housekeeping interval stays directly between the FP evidence-expiry interval and the FB-C1 interval, never last, still one 10 s interval of exactly two lambdas; its second lambda (arm TTL + IE8) is RAM-only: no supervision / Modbus / NVS / writer / log tokens, executes only the candidate invalidation")
def d_interval(c):
    v = base_violation()
    ivs = c.fw.get("interval") or []
    if c.n_marked_intervals != 1 or c.interval is None:
        return v + [f"{c.n_marked_intervals} intervals mention the housekeeping marker"]
    i = c.interval_index
    if c.interval.get("interval") != "10s" or list(c.interval) != ["interval", "then"] or [list(a)[0] for a in c.interval["then"]] != ["lambda", "lambda"]:
        v.append(f"interval shape {list(c.interval)} {c.interval.get('interval')} {[list(a)[0] for a in c.interval['then']]} (want 10s, exactly two lambdas)")
    if i == 0 or "free_power_recovery_evidence_valid" not in yaml.dump(ivs[i - 1]["then"]):
        v.append("not directly after the Free Power evidence-expiry interval")
    if i + 1 >= len(ivs) or "failback_shadow" not in yaml.dump(ivs[i + 1]["then"]):
        v.append("not directly before the FB-C1 interval")
    if i == len(ivs) - 1:
        v.append("the housekeeping interval is the LAST interval")
    if BASE["ctx"] is not None and (BASE["ctx"].interval_index != i or len(ivs) != len(BASE["ctx"].fw["interval"])):
        v.append("the housekeeping interval moved or an interval was added")
    t = strip_cpp(c.tick2)
    for tok in ("supervision", "modbus", "read_direct", "EspNvs", "nvs_", "ecco_fbdurable", "ecco_durable", "script.execute", "commit", "ESP_LOG", "random_uint32", "ntp_", "publish_state"):
        if tok in t:
            v.append(f"the second housekeeping lambda contains {tok!r}")
    if set(EXEC_RX.findall(t)) != {"fallback_profile_invalidate_candidate"}:
        v.append(f"the second housekeeping lambda executes {sorted(EXEC_RX.findall(t))}")
    if assigned(c.tick2) != {"fallback_profile_invalidate_reason"}:
        v.append(f"the second housekeeping lambda assigns {sorted(assigned(c.tick2))}")
    if not has(c.tick2, "if (id(fallback_profile_cand_valid) && !id(fallback_profile_op_in_progress) && (id(fallback_profile_save_unconfirmed) || id(fallback_profile_read_anomaly) != 0)) { id(fallback_profile_invalidate_reason) = ecco_fbcap::REASON_SUPERSEDED; id(fallback_profile_invalidate_candidate).execute(); }"):
        v.append("IE8 (clear any candidate once the outcome is unknown / a read anomaly is latched, silently) is missing or changed")
    return v


@pin("S-FPARITY", "G13 (writes fingerprint): the SAVE gate samples the same five write counters, in the same order, as the FB-B1 housekeeping tick's IE11; the SAVE gate's arms / bus / domain inputs use the same sources as the REVIEW gate")
def d_fingerprint(c):
    v = []
    try:
        a = call_args(c.save_lam, r"ecco_fbcap::writes_fingerprint")
        b = call_args(c.tick1, r"ecco_fbcap::writes_fingerprint")
    except ValueError:
        return ["a writes_fingerprint call was not found"]
    if a != FINGERPRINT_ARGS or b != FINGERPRINT_ARGS:
        v.append(f"fingerprint arguments save {a} tick {b} (want {FINGERPRINT_ARGS})")
    g_rev, g_save = var_assignments(c.review_lam, "gi"), var_assignments(c.save_lam, "gi")
    if g_rev != g_save:
        v.append(f"the SAVE gate's gi sources differ from the REVIEW gate's: {sorted(set(g_rev.items()) ^ set(g_save.items()))[:4]}")
    return v

@pin("S-MIRROR", "the RAM mirror comes only from readbacks, never from the intended records (PO5 / MB26): before the writer the mirror is rebuilt from the fresh reads (evaluate_read); after it ONLY from mirror_after(o, r, p, lp, w, lw) (m.p / m.w), the class is re-composed from that mirror, seen_hw_gen is raised through next_seen_hw_gen (MB34 floor) and the latch notes follow the per-key COMMITTED outcome; nothing is ever encoded from plan.p_new / plan.w_new")
def d_mirror(c):
    v = []
    for who, lam in (("SAVE_FINAL part 2", c.save_p2), ("INVALIDATE", c.inv_lam)):
        want = {
            "fallback_profile_bytes": ["ecco_fallback::encode_profile(p)", "ecco_fallback::encode_profile(m.p)"],
            "fallback_witness_bytes": ["ecco_fbdurable::encode_provision(w)", "ecco_fbdurable::encode_provision(m.w)"],
            "fallback_profile_load": ["lp", "m.p_load"], "fallback_witness_load": ["lw", "m.w_load"],
            "fallback_profile_class": ["e.cls", "e2.cls"], "fallback_profile_why": ["e.why", "e2.why"],
            "fallback_profile_present_seen": ["e.latch.present_seen", "lat.present_seen"],
            "fallback_profile_read_anomaly": ["e.latch.read_anomaly"],
            "fallback_profile_seen_hw_gen": ["e.seen_hw_gen", "ecco_fbdurable::next_seen_hw_gen(id(fallback_profile_seen_hw_gen),ecco_fallback::classify_profile(m.p_load,m.p),m.p.generation,ecco_fbdurable::classify_witness(m.w_load,m.w),m.w.hw_generation)"]}
        for name, rhs in want.items():
            if rhs_of(lam, name) != [S(x) for x in rhs]:
                v.append(f"{who}: {name} = {rhs_of(lam, name)} (want {[S(x) for x in rhs]})")
        if call_args(lam, r"ecco_fbdurable::mirror_after") != ["o", "r", "p", "lp", "w", "lw"]:
            v.append(f"{who}: mirror_after arguments {call_args(lam, r'ecco_fbdurable::mirror_after')}")
        if not has(lam, "if (r.w.outcome == ecco_fbdurable::KEY_COMMITTED) lat = ecco_fbdurable::note_committed(lat, ecco_fbdurable::KEY_BIT_WITNESS);") or \
                not has(lam, "if (r.p.outcome == ecco_fbdurable::KEY_COMMITTED) lat = ecco_fbdurable::note_committed(lat, ecco_fbdurable::KEY_BIT_PROFILE);"):
            v.append(f"{who}: the latch notes are not one per key, each only when that key COMMITTED")
        if not has(lam, "ecco_fbdurable::compose_profile_class(m.p_load, m.p, m.w_load, m.w, id(fallback_profile_read_anomaly))"):
            v.append(f"{who}: the class is not re-composed from the mirror after the commit")
        s = strip_cpp(lam)
        if re.search(r"encode_(?:profile|provision)\s*\(\s*plan", s) or re.search(r"id\(\w+\)\s*=[^;]*plan\.(?:p_new|w_new)", s):
            v.append(f"{who}: a RAM mirror is assigned from the intended records")
        if not has(lam, "const bool healthy = ecco_fbdurable::nvs_healthy();") or not has(lam, "in.healthy = healthy;"):
            v.append(f"{who}: the health check does not feed the fresh read (healthy = nvs_healthy() -> in.healthy)")
        s2 = sq(lam)
        if not (s2.find("boolhealthy=") > s2.find("read_direct_t(nvs,ecco_fbdurable::FAILBACK_PROVISION_KEY") > s2.find("read_direct_t(nvs,ecco_fbdurable::FALLBACK_PROFILE_KEY") > 0):
            v.append(f"{who}: the fresh reads are not FBP, FBW, then ONE health check")
        if s2.count("read_direct_t(") != 2:
            v.append(f"{who}: {s2.count('read_direct_t(')} direct reads (want exactly the two fresh ones)")
    return v


WRITE_AUTH_RX = re.compile(r"modbus_client\.write|write_multiple|write_single|create_write|send_raw|queue_command|\.save\s*\(|\bsync\s*\(|nvs_erase|erase_key|"
                           r"ecco_durable::commit_record|ecco_durable::load_record|\bcommit_record\b|\bload_record\b|load_record_status")


@pin("S-WRITE", "zero inverter authority and no legacy durable record access: no Modbus write / queue / raw-send symbol and no ecco_durable commit_record / load_record(_status) in any FB lambda (the two commit lambdas included); the firmware-wide commit_record / load_record / load_record_status call-site counts equal the base's (and 57 / 7 / 3)")
def d_write(c):
    v = base_violation()
    for n, code in c.fb.items():
        m = WRITE_AUTH_RX.search(strip_cpp(code))
        if m:
            v.append(f"{n}: {m.group(0)!r}")
    pats = (r"ecco_durable::commit_record\s*\(", r"ecco_durable::load_record\s*\(", r"ecco_durable::load_record_status\s*\(")
    got = tuple(len(re.findall(p_, c.text)) for p_ in pats)
    if BASE["text"] is not None:
        want = tuple(len(re.findall(p_, BASE["text"])) for p_ in pats)
        if got != want:
            v.append(f"durable call-site counts {got} vs the base's {want}")
    if got != (57, 7, 3):
        v.append(f"durable call-site counts {got} (want 57 / 7 / 3)")
    return v


@pin("S-HDRCONST", "the constants the YAML relies on are the header's, the mirror's and the design's: ARM_TTL_MS = 120000 (== the candidate TTL), PRECOMMIT_WAIT_MS = 3000, PURPOSE_SAVE = 2 (REVIEW is 1), and the IE2 reason REASON_SUPERSEDED is silent (it starts with 'superseded', so invalidate_reason_publishes is false)")
def d_hdrconst(c):
    v = []
    h = c.file("firmware/include/ecco_fallback_save.h")
    cap = c.file("firmware/include/ecco_fallback_capture.h")
    mir = c.file("registry/fallback_save.py")
    for name, val in (("ARM_TTL_MS", 120000), ("PRECOMMIT_WAIT_MS", 3000), ("PURPOSE_SAVE", 2)):
        m = re.search(r"constexpr uint\d+_t %s = (\d+)u?;" % name, h)
        mm = re.search(r"^%s\s*=\s*(\d+)\s*$" % name, mir, re.M)
        if not m or int(m.group(1)) != val:
            v.append(f"header {name} = {m.group(1) if m else None} (want {val})")
        if not mm or int(mm.group(1)) != val:
            v.append(f"mirror {name} = {mm.group(1) if mm else None} (want {val})")
    t_ = re.search(r"constexpr uint32_t CANDIDATE_TTL_MS = (\d+)u;", cap)
    if not t_ or int(t_.group(1)) != 120000:
        v.append("the capture header's CANDIDATE_TTL_MS is not 120000 (the arm lifetime equals it by design)")
    pr = re.search(r"PURPOSE_REVIEW = (\d+)", cap)
    if not pr or int(pr.group(1)) != 1:
        v.append("PURPOSE_REVIEW is not 1")
    rs = re.search(r'constexpr char REASON_SUPERSEDED\[\] = "([^"]*)";', cap)
    if not rs or not rs.group(1).startswith("superseded"):
        v.append("REASON_SUPERSEDED does not start with 'superseded' (IE2 would publish its own B9 line)")
    return v


@pin("S-HA", "no Home Assistant package / automation / script names the Fallback Profile arm or the execute action (nothing but a person ever arms or executes: the arm is turned on from a dashboard tap only, never by an automation, script or blueprint)")
def d_ha(c):
    """FB-B3: exact allowlist. Only the operator ACTIONS package may name the device action (and the save / invalidate wrapper scripts);
    only the STATUS package may name the arm, and only as a READ (`states('switch....') == 'on'`); no other package, automation or
    override names any of them. Nothing in a package ever arms or toggles the arm."""
    v = []
    rx = re.compile(r"fallback_profile_arm|fallback_profile_execute|fallback_profile_save\b|fallback_profile_invalidate\b|ecco_fallback_profile_arm", re.I)
    ACTIONS, STATUS = "home-assistant/packages/ecco_fallback_profile_actions.yaml", "home-assistant/packages/ecco_fallback_status.yaml"

    def judge(rel, text):
        hits = [m for m in rx.finditer(text)]
        if not hits:
            return
        if rel == ACTIONS:
            if any("arm" in m.group(0).lower() for m in hits):
                v.append(f"{rel} names the arm")
        elif rel == STATUS:
            for m in hits:
                line = text[text.rfind("\n", 0, m.start()) + 1:text.find("\n", m.end())]
                if "fallback_profile_arm" not in m.group(0) or "states('switch." not in line or "== 'on'" not in line:
                    v.append(f"{rel} names {m.group(0)!r} outside a read-only states('switch....') == 'on'")
        else:
            v.append(f"{rel} names {hits[0].group(0)!r}")

    for p in sorted((L.ROOT / "home-assistant" / "packages").glob("*.y*ml")):
        rel = p.relative_to(L.ROOT).as_posix()
        judge(rel, c.file(rel))
    for rel in c.overrides:
        if rel.startswith("home-assistant/packages/"):
            judge(rel, c.overrides[rel])
    return v


NAMESPACE_HEADERS = {"ecco_fbsave": ("firmware/include/ecco_fallback_save.h",), "ecco_fbcap": ("firmware/include/ecco_fallback_capture.h",),
                     "ecco_fbdurable": ("firmware/include/ecco_fallback_durable_model.h", "firmware/include/ecco_fallback_durable.h"),
                     "ecco_fallback": ("firmware/include/ecco_fallback_profile.h",)}


@pin("S-NAMES", "every ecco_fbsave:: / ecco_fbcap:: / ecco_fbdurable:: / ecco_fallback:: name an FB lambda uses is declared in that namespace's header (a typo or a name that does not exist is a static failure, not only a compile failure)")
def d_names(c):
    v = []
    decl = {ns: [strip_cpp(c.file(h)) for h in hs] for ns, hs in NAMESPACE_HEADERS.items()}
    seen = set()
    for n, code in c.fb.items():
        for ns, name in re.findall(r"\b(ecco_fbsave|ecco_fbcap|ecco_fbdurable|ecco_fallback)::(\w+)", strip_cpp(code)):
            if (ns, name) in seen:
                continue
            seen.add((ns, name))
            if not any(re.search(r"\b%s\b" % re.escape(name), h) for h in decl[ns]):
                v.append(f"{n}: {ns}::{name} is not declared in {NAMESPACE_HEADERS[ns]}")
    return v


@pin("S-STRUCTS", "the input PODs the YAML must fill have exactly the field census the contract lists (SaveGateInputs 14, InvalidateGateInputs 27 flattened, SavePlanInputs 17, InvalidatePlanInputs 11, GateInputs 48 flattened, ReadInputs 13, ReviewInputs 9, BusInputs 14) - a field added to a header without the YAML filling it is caught by S-POD, a struct that silently changed is caught here")
def d_structs(c):
    v = []
    st = {**parse_structs(c.file("firmware/include/ecco_fallback_capture.h")), **parse_structs(c.file("firmware/include/ecco_fallback_save.h"))}
    want = {"SaveGateInputs": 14, "InvalidateGateInputs": 27, "SavePlanInputs": 17, "InvalidatePlanInputs": 11, "GateInputs": 48, "ReadInputs": 13,
            "ReviewInputs": 9, "BusInputs": 14}
    for name, n in want.items():
        if name not in st:
            v.append(f"struct {name} not found")
        elif len(flat_fields(st, name)) != n:
            v.append(f"{name} has {len(flat_fields(st, name))} flattened fields (want {n})")
    return v


def run_all(ctx, names=None) -> dict:
    """name -> violations for every (or the named) detector; an exception inside a detector is reported as a violation."""
    out = {}
    for n in (names or PINS):
        try:
            out[n] = PINS[n](ctx)
        except Exception as ex:  # noqa: BLE001 - a detector that cannot run on a damaged text is a violation, never a skip
            out[n] = [f"detector raised {type(ex).__name__}: {str(ex)[:120]}"]
    return out
