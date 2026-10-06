"""A SYNTHETIC SAVE / INVALIDATE for the harness self-tests (test_fallback_save_harness.py) - NOT the firmware under test.

The FB-B2 firmware YAML is written by someone else, after this harness. To prove the harness against lambdas of the shape that
YAML will contain, `with_mini_save(fw)` bolts a miniature SAVE and INVALIDATE onto a copy of the parsed firmware (the live FB-B1
one, or any other): an api action `fbs_synth_execute(action, target_id, confirmation)` that copies its StringRefs to globals and
routes, a template switch `fbs_synth_arm` with a `turn_on_action` that stamps millis(), and two single-lambda scripts that read
the arm, turn it off, check the candidate / ids / phrase, read FBP + FBW fresh, build the intended pair, call
`ecco_fbdurable::commit_transition_t`, mirror from the readbacks and publish. Every name is prefixed `fbs_synth_` so the real
`fallback_profile_*` additions can never collide with it, and the Driver is told the names (api=, arm=).

It is deliberately NOT a copy of the design (no dispatch, no re-read, no gate order): it is the smallest program that exercises
every harness construct a real SAVE needs - StringRef variables, `std::string` compare / `+` / `snprintf("%016llX")`, a
switch read + turn_off() + turn_on_action, brace-init PriorDesc / TxnResult / MirrorRecords, TxnOutcome, record fields, the
FB-B0 commit and the RAM mirror update - so the scenario drivers (execute / arm_on / reboot / power-cut sweeps) can be proved on
something real before the real thing exists.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

SYNTH_API = "fbs_synth_execute"
SYNTH_ARM = "fbs_synth_arm"
SYNTH_SAVE = "fbs_synth_save"
SYNTH_INVALIDATE = "fbs_synth_invalidate"

_GLOBALS = [
    ("fbs_synth_exec_action", "std::string", '""'),
    ("fbs_synth_exec_target_id", "std::string", '""'),
    ("fbs_synth_exec_confirmation", "std::string", '""'),
    ("fbs_synth_arm_on_ms", "uint32_t", "0"),
    ("fbs_synth_unconfirmed", "bool", "false"),
    ("fbs_synth_last_err", "uint32_t", "0"),
    ("fbs_synth_last_us", "uint32_t", "0"),
    ("fbs_synth_outcome", "uint8_t", "255"),
    ("fbs_synth_calls", "uint32_t", "0"),
]

_API_THEN = [
    {"lambda": "id(fbs_synth_exec_action) = action.str();\n"
               "id(fbs_synth_exec_target_id) = target_id;\n"
               "id(fbs_synth_exec_confirmation) = std::string(confirmation.c_str(), confirmation.size());\n"
               "id(fbs_synth_calls) += 1;"},
    {"if": {"condition": {"lambda": 'return action == "INVALIDATE";'},
            "then": [{"script.execute": SYNTH_INVALIDATE}],
            "else": [{"script.execute": SYNTH_SAVE}]}},
]

_SAVE = r'''
const bool armed = id(fbs_synth_arm).state;
id(fbs_synth_arm).turn_off();
if (id(fbs_synth_exec_action) != "SAVE") {
  id(fallback_profile_last_result_text).publish_state("REFUSED - unsupported action");
  return;
}
if (!armed) {
  id(fallback_profile_last_result_text).publish_state("SAVE REFUSED - arm is not on");
  return;
}
if (!id(fallback_profile_cand_valid) || !id(fallback_profile_cand_saveable) || id(fallback_profile_cand_id) == 0) {
  id(fallback_profile_last_result_text).publish_state("SAVE REFUSED - no saveable candidate");
  return;
}
if ((uint32_t) (millis() - id(fallback_profile_cand_ms)) >= 120000u) {
  id(fallback_profile_last_result_text).publish_state("SAVE REFUSED - candidate expired");
  return;
}
if (id(fbs_synth_unconfirmed)) {
  id(fallback_profile_last_result_text).publish_state("SAVE REFUSED - previous save outcome unknown");
  return;
}
char idbuf[17];
snprintf(idbuf, sizeof(idbuf), "%016llX", (unsigned long long) id(fallback_profile_cand_id));
if (id(fbs_synth_exec_target_id) != idbuf) {
  id(fallback_profile_last_result_text).publish_state("SAVE REFUSED - candidate ID does not match");
  return;
}
std::string want = std::string("SAVE ") + idbuf;
if (id(fbs_synth_exec_confirmation) != want) {
  id(fallback_profile_last_result_text).publish_state(("SAVE REFUSED - confirmation phrase mismatch (expected '" + want + "')").c_str());
  return;
}
ecco_fbdurable::EspNvs nvs;
ecco_fallback::FallbackProfileV1 pp{};
ecco_fbdurable::FailbackProvisionV1 wp{};
ecco_fbdurable::ReadDiag dp{}, dw{};
const uint8_t pl = ecco_fbdurable::read_direct_t(nvs, ecco_fbdurable::FALLBACK_PROFILE_KEY, pp, dp);
const uint8_t wl = ecco_fbdurable::read_direct_t(nvs, ecco_fbdurable::FAILBACK_PROVISION_KEY, wp, dw);
const bool healthy = ecco_fbdurable::nvs_healthy();
const ecco_fbdurable::EffectiveProfile e = ecco_fbdurable::compose_profile_class(pl, pp, wl, wp, id(fallback_profile_read_anomaly));
if (!healthy || !ecco_fbdurable::save_class_permitted(e.cls)) {
  id(fallback_profile_last_result_text).publish_state("SAVE REFUSED - stored profile not writable");
  return;
}
const uint8_t pc = ecco_fallback::classify_profile(pl, pp);
const uint8_t wc = ecco_fbdurable::classify_witness(wl, wp);
const uint32_t base = ecco_fbdurable::save_generation_base(pc, pp.generation, wc, wp.hw_generation, id(fallback_profile_seen_hw_gen));
if (!ecco_fbdurable::save_generation_available(base)) {
  id(fallback_profile_last_result_text).publish_state("SAVE REFUSED - generation counter exhausted");
  return;
}
const uint32_t gen = base + 1u;
ecco_fallback::FallbackProfileV1 pn = ecco_fbcap::profile_from_words(id(fallback_profile_cand_words));
pn.generation = gen;
pn.captured_epoch = (uint32_t) id(ntp_time).now().timestamp;
pn.flags = 0;
pn = ecco_fallback::seal_profile(pn);
const bool auth = ecco_fbdurable::fba_authentic(pc);
const uint8_t op = (e.cls == ecco_fbdurable::EPC_CORRUPT) ? ecco_fbdurable::PROV_OP_REPLACE_CORRUPT : ecco_fbdurable::PROV_OP_SAVE;
const ecco_fbdurable::FailbackProvisionV1 wn = ecco_fbdurable::make_provision(gen, pn.binding, auth ? pp.generation : 0u,
    auth ? pp.binding : 0u, ecco_fbdurable::FALLBACK_PROFILE_KEY, ecco_fallback::PROFILE_SCHEMA, op);
ecco_fbdurable::TxnResult r{};
const ecco_fbdurable::TxnOutcome o = ecco_fbdurable::commit_transition_t(nvs, wn, wp, ecco_fbdurable::PriorDesc{wl, dw.stored_len},
    pn, pp, ecco_fbdurable::PriorDesc{pl, dp.stored_len}, r);
const ecco_fbdurable::MirrorRecords m = ecco_fbdurable::mirror_after(o, r, pp, pl, wp, wl);
id(fallback_profile_bytes) = ecco_fallback::encode_profile(m.p);
id(fallback_witness_bytes) = ecco_fbdurable::encode_provision(m.w);
id(fallback_profile_load) = m.p_load;
id(fallback_witness_load) = m.w_load;
id(fbs_synth_outcome) = (uint8_t) o;
id(fbs_synth_last_err) = (r.w.err != 0) ? (uint32_t) r.w.err : (uint32_t) r.p.err;
id(fbs_synth_last_us) = r.w.us + r.p.us;
if (o == ecco_fbdurable::TXN_COMMITTED || o == ecco_fbdurable::TXN_NOT_COMMITTED) {
  ecco_fbdurable::ReadLatch latch{id(fallback_profile_present_seen), id(fallback_profile_read_anomaly)};
  if (o == ecco_fbdurable::TXN_COMMITTED) {
    latch = ecco_fbdurable::note_committed(latch, ecco_fbdurable::KEY_BIT_WITNESS);
    latch = ecco_fbdurable::note_committed(latch, ecco_fbdurable::KEY_BIT_PROFILE);
  }
  id(fallback_profile_present_seen) = latch.present_seen;
  id(fallback_profile_seen_hw_gen) = ecco_fbdurable::next_seen_hw_gen(id(fallback_profile_seen_hw_gen),
      ecco_fallback::classify_profile(m.p_load, m.p), m.p.generation, ecco_fbdurable::classify_witness(m.w_load, m.w), m.w.hw_generation);
  const ecco_fbdurable::EffectiveProfile e2 = ecco_fbdurable::compose_profile_class(m.p_load, m.p, m.w_load, m.w, id(fallback_profile_read_anomaly));
  id(fallback_profile_class) = e2.cls;
  id(fallback_profile_state_text).publish_state(ecco_fbcap::epc_name(e2.cls));
  id(fallback_profile_summary_text).publish_state(
      ecco_fbcap::b2_text(m.p_load, m.p, m.w_load, m.w, e2.why, id(fbs_synth_last_err), id(fbs_synth_last_us)).c_str());
}
if (o == ecco_fbdurable::TXN_COMMITTED) {
  id(fallback_profile_cand_valid) = false;
  id(fallback_profile_last_result_text).publish_state("SAVED - synthetic");
} else if (o == ecco_fbdurable::TXN_UNKNOWN_REBOOT) {
  id(fbs_synth_unconfirmed) = true;
  id(fallback_profile_state_text).publish_state(ecco_fbcap::epc_name(ecco_fbdurable::EPC_SAVE_UNCONFIRMED));
  id(fallback_profile_last_result_text).publish_state("SAVE OUTCOME UNKNOWN - synthetic");
} else if (o == ecco_fbdurable::TXN_NOT_COMMITTED) {
  id(fallback_profile_last_result_text).publish_state(r.witness_advanced ? "SAVE NOT COMMITTED - witness advanced" : "SAVE NOT COMMITTED - nothing changed");
} else {
  id(fallback_profile_last_result_text).publish_state("SAVE REFUSED - storage refused the write");
}
'''

_INVALIDATE = r'''
const bool armed = id(fbs_synth_arm).state;
id(fbs_synth_arm).turn_off();
if (id(fbs_synth_exec_action) != "INVALIDATE") {
  id(fallback_profile_last_result_text).publish_state("REFUSED - unsupported action");
  return;
}
if (!armed) {
  id(fallback_profile_last_result_text).publish_state("INVALIDATE REFUSED - arm is not on");
  return;
}
if (id(fbs_synth_unconfirmed)) {
  id(fallback_profile_last_result_text).publish_state("INVALIDATE REFUSED - previous outcome unknown");
  return;
}
if (!id(inverter_modbus)->tx_buffer_empty() || id(inverter_modbus)->tx_blocked() || id(manual_write_in_progress)) {
  id(fallback_profile_last_result_text).publish_state("INVALIDATE REFUSED - inverter busy; try again");
  return;
}
ecco_fbdurable::EspNvs nvs;
ecco_fallback::FallbackProfileV1 pp{};
ecco_fbdurable::FailbackProvisionV1 wp{};
ecco_fbdurable::ReadDiag dp{}, dw{};
const uint8_t pl = ecco_fbdurable::read_direct_t(nvs, ecco_fbdurable::FALLBACK_PROFILE_KEY, pp, dp);
const uint8_t wl = ecco_fbdurable::read_direct_t(nvs, ecco_fbdurable::FAILBACK_PROVISION_KEY, wp, dw);
const bool healthy = ecco_fbdurable::nvs_healthy();
const ecco_fbdurable::EffectiveProfile e = ecco_fbdurable::compose_profile_class(pl, pp, wl, wp, id(fallback_profile_read_anomaly));
const uint8_t wc = ecco_fbdurable::classify_witness(wl, wp);
if (!healthy || !ecco_fbdurable::invalidate_class_permitted(e.cls) || !ecco_fallback::profile_invalidate_permitted(pp)
    || !ecco_fbdurable::invalidate_generation_permitted(pp.generation, wc, wp.hw_generation, id(fallback_profile_seen_hw_gen))) {
  id(fallback_profile_last_result_text).publish_state("INVALIDATE REFUSED - stored profile is not a VALID profile");
  return;
}
char idbuf[17];
snprintf(idbuf, sizeof(idbuf), "%016llX", (unsigned long long) pp.binding);
if (id(fbs_synth_exec_target_id) != idbuf) {
  id(fallback_profile_last_result_text).publish_state("INVALIDATE REFUSED - profile ID does not match");
  return;
}
const ecco_fallback::FallbackProfileV1 pn = ecco_fallback::invalidate_profile(pp);
const ecco_fbdurable::FailbackProvisionV1 wn = ecco_fbdurable::make_provision(pn.generation, pn.binding, pp.generation, pp.binding,
    ecco_fbdurable::FALLBACK_PROFILE_KEY, ecco_fallback::PROFILE_SCHEMA, ecco_fbdurable::PROV_OP_INVALIDATE);
ecco_fbdurable::TxnResult r{};
const ecco_fbdurable::TxnOutcome o = ecco_fbdurable::commit_transition_t(nvs, wn, wp, ecco_fbdurable::PriorDesc{wl, dw.stored_len},
    pn, pp, ecco_fbdurable::PriorDesc{pl, dp.stored_len}, r);
const ecco_fbdurable::MirrorRecords m = ecco_fbdurable::mirror_after(o, r, pp, pl, wp, wl);
id(fallback_profile_bytes) = ecco_fallback::encode_profile(m.p);
id(fallback_witness_bytes) = ecco_fbdurable::encode_provision(m.w);
id(fallback_profile_load) = m.p_load;
id(fallback_witness_load) = m.w_load;
id(fbs_synth_outcome) = (uint8_t) o;
if (o == ecco_fbdurable::TXN_COMMITTED || o == ecco_fbdurable::TXN_NOT_COMMITTED) {
  const ecco_fbdurable::EffectiveProfile e2 = ecco_fbdurable::compose_profile_class(m.p_load, m.p, m.w_load, m.w, id(fallback_profile_read_anomaly));
  id(fallback_profile_class) = e2.cls;
  id(fallback_profile_state_text).publish_state(ecco_fbcap::epc_name(e2.cls));
  id(fallback_profile_summary_text).publish_state(ecco_fbcap::b2_text(m.p_load, m.p, m.w_load, m.w, e2.why, 0, 0).c_str());
}
if (o == ecco_fbdurable::TXN_COMMITTED) {
  id(fallback_profile_last_result_text).publish_state("INVALIDATED - synthetic");
} else if (o == ecco_fbdurable::TXN_UNKNOWN_REBOOT) {
  id(fbs_synth_unconfirmed) = true;
  id(fallback_profile_state_text).publish_state(ecco_fbcap::epc_name(ecco_fbdurable::EPC_SAVE_UNCONFIRMED));
  id(fallback_profile_last_result_text).publish_state("INVALIDATE OUTCOME UNKNOWN - synthetic");
} else {
  id(fallback_profile_last_result_text).publish_state("INVALIDATE NOT COMMITTED - synthetic");
}
'''


SAVE_TEXT = _SAVE.strip("\n")
INVALIDATE_TEXT = _INVALIDATE.strip("\n")


def with_mini_save(fw: dict, *, save_text: str | None = None, invalidate_text: str | None = None) -> dict:
    """A shallow copy of the parsed firmware `fw` with the synthetic SAVE / INVALIDATE added (`fw` itself is untouched).
    `save_text` / `invalidate_text` replace the script lambdas (the suite derives its mutants from SAVE_TEXT / INVALIDATE_TEXT)."""
    for gid, _t, _v in _GLOBALS:
        if any(g["id"] == gid for g in fw["globals"]):
            raise ValueError(f"the firmware already has {gid}")
    out = dict(fw)
    out["globals"] = list(fw["globals"]) + [{"id": i, "type": t, "restore_value": "no", "initial_value": v}
                                            for i, t, v in _GLOBALS]
    out["script"] = list(fw["script"]) + [
        {"id": SYNTH_SAVE, "mode": "single", "then": [{"lambda": (SAVE_TEXT if save_text is None else save_text)}]},
        {"id": SYNTH_INVALIDATE, "mode": "single",
         "then": [{"lambda": (INVALIDATE_TEXT if invalidate_text is None else invalidate_text)}]},
    ]
    out["switch"] = list(fw.get("switch") or []) + [
        {"platform": "template", "name": "Synthetic Arm", "id": SYNTH_ARM, "optimistic": True, "restore_mode": "ALWAYS_OFF",
         "turn_on_action": [{"lambda": "id(fbs_synth_arm_on_ms) = millis();"}]},
    ]
    api = dict(fw.get("api") or {})
    api["actions"] = list(api.get("actions") or []) + [
        {"action": SYNTH_API, "variables": {"action": "string", "target_id": "string", "confirmation": "string"},
         "then": _API_THEN},
    ]
    out["api"] = api
    return out
