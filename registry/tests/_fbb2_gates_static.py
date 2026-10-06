"""FB-B2 t-gates: the few STATIC pins the gate / race scenarios depend on (registered into _fbb2_gates_lib.SCENARIOS).

The full static pin set belongs to the t-static suite; these are the pins whose violation would make the BEHAVIOURAL scenarios of this
suite vacuous (a scenario that proves "the gate decides on the copies" is only meaningful if no final lambda reads the live candidate or
the call's arguments), plus the mutants' static detectors (a text mutant whose effect is not observable through the harness).
"""

from __future__ import annotations

import re

import yaml

from _fbb2_gates_lib import *  # noqa: F401,F403
from _fbb2_gates_lib import D, Exp, live_text, scenario, script_span


def _fw(mk):
    return mk.fw if getattr(mk, "fw", None) is not None else D.load_fw()


def _text(mk):
    return mk.text if getattr(mk, "text", None) is not None else live_text()


def _scripts(fw):
    return {s["id"]: s for s in fw["script"]}


def code_only(src: str) -> str:
    """A lambda / YAML text without its // comments and # comment lines (statements only)."""
    kept = [ln for ln in src.splitlines() if not ln.lstrip().startswith("#")]
    return re.sub(r"//[^\n]*", "", "\n".join(kept))


def _lambdas(node, out=None):
    out = [] if out is None else out
    if isinstance(node, dict):
        for k, v in node.items():
            if k == "lambda" and isinstance(v, str):
                out.append(v)
            else:
                _lambdas(v, out)
    elif isinstance(node, list):
        for v in node:
            _lambdas(v, out)
    return out


@scenario("st_api_action", "the api action: appended LAST after the heartbeat, actions[0] unchanged, string copies with .str(), ONE heartbeat snapshot, header router")
def st_api_action(mk, ex: Exp):
    fw = _fw(mk)
    acts = fw["api"]["actions"]
    ex.row("action list")
    ex.eq([a["action"] for a in acts], ["free_power_recovery_execute", "ha_supervision_heartbeat", "fallback_profile_execute"], "three actions, appended last")
    a = acts[2]
    ex.eq(a["variables"], {"action": "string", "target_id": "string", "confirmation": "string"}, "variables")
    lam = _lambdas(a)
    body = "\n".join(lam)
    ex.row("lambda body")
    for v in ("action", "target_id", "confirmation"):
        ex.ok(f"id(fallback_profile_exec_{v if v != 'action' else 'action'}) = {v}.str();" in body or
              f"id(fallback_profile_exec_{v}) = {v}.str();" in body, f"{v} is copied with .str() at once (StringRef is not NUL terminated)")
    ex.eq(body.count("supervision_state"), 1, "the supervision state is read exactly once, in this lambda")
    ex.eq(body.count("supervision_stable"), 1, "the Stable flag is read exactly once, in this lambda")
    ex.ok("id(fallback_profile_exec_hb_ok) = (id(supervision_state) == 1) && id(supervision_stable);" in body, "the snapshot predicate is SUPERVISED && Stable")
    ex.ok("ecco_fbsave::is_invalidate_action(" in body and '"INVALIDATE"' not in body and '"SAVE"' not in body,
          "the router is a header function, no operator literal in the YAML")
    ex.ok("c_str()" not in "".join(l for l in lam if "exec_" in l and "= " in l and ".str()" not in l), "no c_str() copy of an argument")


@scenario("st_no_supervision_in_fb_code", "no FB script / arm switch mentions supervision, except the ONE commit-time heartbeat re-check of SAVE_FINAL part 2 (two reads, in the dispatch); every other FB script never reads the heartbeat")
def st_no_supervision_in_fb_code(mk, ex: Exp):
    fw = _fw(mk)
    ex.row("scripts")
    for sid, s in _scripts(fw).items():
        if sid.startswith("fallback_profile_"):
            if sid == "fallback_profile_capture_dispatch":
                # FB-B2 hardening: the commit-time heartbeat re-check (SAVE_FINAL part 2) is the only place; it names the two symbols once each
                ex.eq(yaml.dump(s).count("supervision"), 2, f"script {sid}: 'supervision' appears exactly twice (the commit-time re-check statement)")
            else:
                ex.ok("supervision" not in yaml.dump(s), f"script {sid} does not contain 'supervision'")
    ex.row("arm switch")
    arm = [x for x in fw["switch"] if x.get("id") == "fallback_profile_arm"]
    ex.eq(len(arm), 1, "one arm switch")
    ex.ok("upervision" not in yaml.dump(arm[0]), "the arm switch YAML has no 'upervision'")
    ex.eq((arm[0].get("restore_mode"), arm[0].get("optimistic"), arm[0].get("platform")), ("ALWAYS_OFF", True, "template"), "ALWAYS_OFF optimistic template switch")
    ex.ok("fallback_profile_arm_on_ms" in yaml.dump(arm[0]["turn_on_action"]), "turn_on_action only stamps the time")


@scenario("st_final_lambdas", "SAVE final lambdas: no wait / delay / script call, no live candidate or call-argument read, words only from pass 2, one writer call each")
def st_final_lambdas(mk, ex: Exp):
    fw = _fw(mk)
    sc = _scripts(fw)
    disp = sc["fallback_profile_capture_dispatch"]["then"]
    ex.row("dispatch shape")
    lam_idx = [i for i, a in enumerate(disp) if set(a) == {"lambda"}]
    ex.ok(len(lam_idx) >= 4, "the dispatch ends with lambdas")
    last = disp[-1]["lambda"]
    ex.ok("id(fallback_profile_op_in_progress) = false;" in last and "id(manual_write_in_progress) = false;" in last and "ctx" in last,
          "the LAST item of the dispatch is the release (op flag, mutex, context)")
    parts = [disp[i]["lambda"] for i in lam_idx if "SAVE final step" in disp[i]["lambda"]]
    ex.eq(len(parts), 2, "SAVE final = two consecutive lambdas")
    ex.row("no yield between the two parts and no live candidate / argument read")
    idx = [i for i in lam_idx if "SAVE final step" in disp[i]["lambda"]]
    ex.eq(idx[1] - idx[0], 1, "the two parts are consecutive items")
    for n, p in enumerate(parts, 1):
        p = code_only(p)
        # FB-B3: the ONLY script call allowed inside a SAVE final part is the synchronous B10 refresh - none in part 1, exactly two in part 2
        # (after the fresh-read B1 publish and after the commit mirror's B1 publish) - and the script it executes is verified lambda-only below
        # (one lambda action: no wait_until / delay / if / script action, so it cannot yield)
        REFRESH = "id(fallback_profile_live_refresh).execute();"
        ex.ok("wait_until" not in p and "delay" not in p and ".execute()" not in p.replace(REFRESH, "") and p.count(REFRESH) == (0 if n == 1 else 2),
              f"part {n}: no wait_until / delay / script call (FB-B3: except the one synchronous B10 refresh)")
        if REFRESH in p:
            rs = sc.get("fallback_profile_live_refresh")
            ex.ok(rs is not None and len(rs["then"]) == 1 and set(rs["then"][0]) == {"lambda"} and rs.get("mode") == "single",
                  f"part {n}: the refresh script is a single-lambda, mode-single script (it cannot yield)")
        ex.ok("fallback_profile_exec_" not in p, f"part {n}: no fallback_profile_exec_* read after the gate")
        ex.ok("fallback_profile_cand_" not in p, f"part {n}: no fallback_profile_cand_* read after the gate")
        if n == 1:
            ex.ok("supervision" not in p and "random_uint32" not in p, f"part {n}: no heartbeat read, no random")
        else:
            # FB-B2 hardening: part 2 re-checks the heartbeat once, right before the bus-quiet check and the writer (no yield in between)
            stmt = "if (!((id(supervision_state) == 1) && id(supervision_stable))) {"
            ex.eq(p.count("supervision"), 2, f"part {n}: exactly the two reads of the commit-time heartbeat re-check")
            ex.ok(stmt in p and "random_uint32" not in p, f"part {n}: the re-check statement is present, no random")
            ex.ok(0 <= p.find("ecco_fbsave::plan_save(") < p.find(stmt) < p.find("ecco_fbsave::commit_bus_quiet(") < p.find("ecco_fbdurable::commit_transition_t("),
                  f"part {n}: plan_save, THEN the heartbeat re-check, THEN the bus-quiet check, THEN the writer")
    ex.row("committed words come from pass 2 only; one writer call; the forensic log precedes it")
    p2 = parts[1]
    ex.ok("pi.words = id(fallback_profile_pass2);" in p2, "plan_save gets pass 2")
    ex.ok("save_ctx_words" not in p2 and "manual_cfg_" not in p2, "the commit part never touches the context words or the manual configuration")
    ex.eq(p2.count("commit_transition_t("), 1, "exactly one writer call in the commit part")
    ex.eq(parts[0].count("commit_transition_t("), 0, "none in the verification part")
    ex.ok(p2.find("replace_corrupt_log_text(") < p2.find("commit_transition_t(") and p2.find("commit_bus_quiet(") < p2.find("commit_transition_t("),
          "the REPLACE CORRUPT forensic log and the bus-quiet check come BEFORE the writer call")
    ex.ok("save_ctx" not in p2.split("commit_bus_quiet(")[1].split("commit_transition_t(")[0], "nothing reads the context between the bus-quiet check and the writer")
    ex.ok(p2.count("evaluate_read(") == 1 and p2.count("read_direct_t(") == 2, "one fresh two-key read")
    ex.ok("ecco_fbsave::clock_trusted_for_save(" in p2, "the clock is re-checked in the commit part")


@scenario("st_writer_sites", "the writer is called from exactly two lambdas of the firmware (SAVE commit part, INVALIDATE); no direct NVS write, no restart")
def st_writer_sites(mk, ex: Exp):
    text = _text(mk)
    ex.row("call sites")
    ex.eq(len(re.findall(r"commit_transition_t\(", text)), 2, "commit_transition_t( appears at exactly two sites")
    ex.eq(len(re.findall(r"nvs_set_blob|nvs_erase|write_one_|ecco_fbdurable::EspNvs\{", code_only(text))), 0, "no direct NVS write call in the YAML code")
    ex.eq(len(re.findall(r"esp_restart|arch_restart|App\.reboot|safe_reboot", text)), 0, "no restart call")
    sc = _scripts(_fw(mk))
    inv = "\n".join(_lambdas(sc["fallback_profile_invalidate"]))
    ex.ok(not re.search(r"id\(manual_write_in_progress\)\s*=(?!=)", inv) and not re.search(r"id\(fallback_profile_op_in_progress\)\s*=(?!=)", inv),
          "the INVALIDATE lambda never assigns the mutex or the op flag")
    ex.ok("wait_until" not in str(sc["fallback_profile_invalidate"]) and "delay" not in str(sc["fallback_profile_invalidate"]), "INVALIDATE never waits")
    ex.row("the gate scripts never write storage")
    sv = "\n".join(_lambdas(sc["fallback_profile_save"]))
    ex.ok("commit_transition_t" not in sv and "read_direct_t" not in sv and "nvs" not in sv.lower().replace("ecco_fbdurable", ""),
          "the SAVE gate script has no storage access at all")
    ex.row("the lambda order of the SAVE gate")
    ex.ok(sv.index("save_in_flight_gate(") < sv.index("const bool armed") < sv.index("save_gate_decide("), "G1, then the one-shot preamble, then G0..G16")
