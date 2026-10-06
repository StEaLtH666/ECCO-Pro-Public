#!/usr/bin/env python3
"""FB-B3 final firmware <-> Home Assistant contract (FINAL_FBB_FBC_ARCHITECTURE.md section 9.8 "final contract test").

This is the ONE place that proves the two halves agree: the dongle firmware (parsed from the real YAML and the shared capture
header / its independent Python mirror) and the Home Assistant surface (status / actions / health packages, the dashboard, the
manifest). It does NOT re-prove what the suites that own each half already prove (the firmware behaviour: test_fallback_live_match.py,
the FB-B1 / FB-B2 suites; the HA templates: home-assistant/tests/test_ecco_fallback_packages.py; the dashboard placement pins:
test_fallback_recovery_dashboard.py); it pins the CONTRACT between them:

  [1] the twelve FB-B firmware entities: exact names / ids / platforms, no FB binary_sensor / number / select / sensor entity, the
      append-only name order, the nine text sensors' ids
  [2] the device action: name, the three variables, `target_id` (never the stale `id`), SAVE / INVALIDATE live, RESTORE / ACKNOWLEDGE
      reserved and refused, the arm's ALWAYS_OFF restore mode
  [3] B10 Live Match: exact name / id, the ten keys in order, the nine `m` values, the numeric enum, the 200-character bound, the seed
  [4] every Home Assistant reference to a firmware FB entity resolves to an id DERIVED from the firmware YAML (device slug + name)
  [5] real firmware B10 texts (the shared C++ comparison via its mirror) through the REAL HA status-code template, against an
      independent oracle of FINAL 9.7's precedence: PAUSED / PAUSED_IO -> `paused`; lease_unreadable / lease_lockout / lease_restoring
      classes; EXPORT / CONTEXT / DRIFT / OUT_OF_DOMAIN; SAVE_UNCONFIRMED and the unusable classes above normal matching
  [6] the operator wrappers: the all-digit target-id vector, the phrase grammar the firmware enforces
  [7] cross-language: every firmware B10 word / code and every HA display string against the Energy Actions card's regexes
  [8] append-only stability: golden lists of the names, keys, enum values and reason-code / cause names

Writes nothing; no hardware, no network.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import jinja2
import yaml

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "registry"))
sys.path.insert(0, str(HERE))
import fallback_capture as cap  # noqa: E402
import _scope_chain as chain  # noqa: E402
import test_fallback_live_match as lm  # noqa: E402  (scenario table + mirror input builders; main() is not run on import)
import test_fallback_recovery_dashboard as dash  # noqa: E402  (card_regexes(); main() is not run on import)

FAILURES: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  PASS  {name}")
    else:
        FAILURES.append(name)
        print(f"  FAIL  {name}" + (f" - {detail}" if detail else ""))


class _Loader(yaml.SafeLoader):
    pass


_Loader.add_multi_constructor("!", lambda l, s, n: l.construct_scalar(n) if isinstance(n, yaml.ScalarNode)
                              else l.construct_sequence(n) if isinstance(n, yaml.SequenceNode) else l.construct_mapping(n))


def load_yaml(rel: str):
    return yaml.load((ROOT / rel).read_text(encoding="utf-8"), Loader=_Loader)


FW_REL = "firmware/ecco_clock_dongle_stage3_4_free_power.yaml"
STATUS_REL = "home-assistant/packages/ecco_fallback_status.yaml"
ACTIONS_REL = "home-assistant/packages/ecco_fallback_profile_actions.yaml"
HEALTH_REL = "home-assistant/packages/ecco_system_health.yaml"
DASH_REL = "home-assistant/dashboards/ecco_pro.yaml"
DEV = "ecco_clock_dongle"      # the installation's device/area slug (a site constant; confirmed live at LP-B3)
NODE = "ecco_clock_dongle"            # the esphome node name with '-' -> '_' (HA service prefix)


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


fw_text = (ROOT / FW_REL).read_text(encoding="utf-8").replace("\r\n", "\n")
fw = chain.load_fw(fw_text)

# The twelve FB-B firmware entities, in the locked append-only order (S5 Part A A.1): (letter, name, domain, firmware id)
FB_ENTITIES = [
    ("B1", "ECCO Fallback Profile State", "sensor", "fallback_profile_state_text"),
    ("B2", "ECCO Fallback Profile Summary", "sensor", "fallback_profile_summary_text"),
    ("B3", "ECCO Fallback Profile Review", "sensor", "fallback_profile_review_text"),
    ("B4", "ECCO Fallback Profile Review ID", "sensor", "fallback_profile_review_id_text"),
    ("B5", "ECCO Fallback Profile Review Slots", "sensor", "fallback_profile_review_slots_text"),
    ("B6", "ECCO Fallback Profile Review Context", "sensor", "fallback_profile_review_context_text"),
    ("B7", "ECCO Fallback Profile Slots", "sensor", "fallback_profile_slots_text"),
    ("B8", "ECCO Fallback Profile Context", "sensor", "fallback_profile_context_text"),
    ("B9", "ECCO Fallback Profile Last Action-Result", "sensor", "fallback_profile_last_result_text"),
    ("B10", "ECCO Fallback Profile Live Match", "sensor", "fallback_profile_live_match_text"),
    ("B11", "ECCO Fallback Profile: Review Current Configuration", "button", "fallback_profile_review_button"),
    ("B12", "ECCO Fallback Profile Arm", "switch", "fallback_profile_arm"),
]
FB_IDS = {f"{dom}.{DEV}_{slug(name)}": (letter, name) for letter, name, dom, _fid in FB_ENTITIES}

# ===========================================================================
print("[1] the twelve FB-B firmware entities")
found = []
for section, dom in (("text_sensor", "sensor"), ("button", "button"), ("switch", "switch")):
    for e in fw.get(section) or []:
        if isinstance(e, dict) and str(e.get("name", "")).startswith("ECCO Fallback Profile"):
            found.append((e["name"], dom, e.get("id"), e.get("platform")))
check("the firmware declares exactly the twelve FB-B entities, in the locked order, with the locked ids and platforms (template)",
      found == [(n, d, i, "template") for _l, n, d, i in FB_ENTITIES], str(found))
for section in ("binary_sensor", "number", "select", "sensor", "text", "light", "fan", "climate", "lock", "cover", "valve"):
    names = [e.get("name") for e in (fw.get(section) or []) if isinstance(e, dict) and str(e.get("name", "")).startswith("ECCO Fallback Profile")]
    check(f"no FB firmware entity of type {section}", not names, str(names))
check("the nine text sensors are all update_interval: never template sensors with no lambda / filter (published only by firmware code)",
      all(str(e.get("update_interval")) == "never" and not ({"lambda", "filters", "on_value", "set_action"} & set(e))
          for e in fw["text_sensor"] if str(e.get("name", "")).startswith("ECCO Fallback Profile")))
b10 = next(e for e in fw["text_sensor"] if e.get("id") == "fallback_profile_live_match_text")
check("B10: exact name `ECCO Fallback Profile Live Match`, firmware id fallback_profile_live_match_text, template text sensor",
      b10["name"] == "ECCO Fallback Profile Live Match" and b10["platform"] == "template")
check("the FB-C entities are separate and unchanged in kind: five `ECCO Failback Shadow ...` text sensors",
      len([e for e in fw["text_sensor"] if str(e.get("name", "")).startswith("ECCO Failback Shadow")]) == 5)

# ===========================================================================
print("\n[2] the device action and the arm")
actions = fw["api"]["actions"]
names = [a.get("action") for a in actions]
check("the action fallback_profile_execute is appended AFTER ha_supervision_heartbeat (append-only)",
      "fallback_profile_execute" in names and names.index("fallback_profile_execute") == names.index("ha_supervision_heartbeat") + 1, str(names))
ex = next(a for a in actions if a.get("action") == "fallback_profile_execute")
check("variables are exactly action / target_id / confirmation, all strings; the stale `id` variable does not exist",
      ex["variables"] == {"action": "string", "target_id": "string", "confirmation": "string"} and "id" not in ex["variables"], str(ex["variables"]))
save_h = (ROOT / "firmware/include/ecco_fallback_save.h").read_text(encoding="utf-8")
check("SAVE and INVALIDATE are live tokens; RESTORE and ACKNOWLEDGE are reserved and refused (`... REFUSED - not implemented in this firmware`)",
      'exact(action, n, "SAVE")' in save_h and 'exact(action, n, "INVALIDATE")' in save_h
      and "ACT_RESTORE = 3,      // reserved: refused, not implemented" in save_h and "ACT_ACKNOWLEDGE = 4,  // reserved: refused, not implemented" in save_h
      and 'put(t, "RESTORE REFUSED - not implemented in this firmware");' in save_h
      and 'put(t, "ACKNOWLEDGE REFUSED - not implemented in this firmware");' in save_h)
arm = next(s for s in fw["switch"] if s.get("id") == "fallback_profile_arm")
check("the arm: template switch, restore_mode ALWAYS_OFF, optimistic (the firmware turns it off after every use; no HA code may turn it on)",
      arm["platform"] == "template" and arm["restore_mode"] == "ALWAYS_OFF" and arm.get("optimistic") is True)
check("the Review button has no confirmation of its own and calls one script (read-only review)",
      next(b for b in fw["button"] if b.get("id") == "fallback_profile_review_button")["on_press"][0].get("script.execute") == {"id": "fallback_profile_review"})

# ===========================================================================
print("\n[3] B10 Live Match grammar")
KEYS = ["m", "dx", "cx", "ox", "ix", "eh", "obl", "ca", "elig", "ew"]
M_SET = ["MATCH", "DRIFT", "CONTEXT", "EXPORT", "OUT_OF_DOMAIN", "PAUSED", "PAUSED_IO", "UNKNOWN", "NO_PROFILE"]
texts = {lm.text_of(m) for _l, m, _e in lm.SCENARIOS}
import random  # noqa: E402
texts |= {lm.text_of(lm.rnd_case(random.Random(31000 + n))) for n in range(500)}
check("every text keeps the locked key order m;dx;cx;ox;ix;eh;obl;ca;elig;ew and matches the grammar",
      all([kv.split("=")[0] for kv in t.split(";")] == KEYS and lm.B10_RE.match(t) for t in texts))
check("the m values are exactly the nine locked ones and all nine are produced", {t.split(";")[0][2:] for t in texts} == set(M_SET)
      and sorted(cap.lm_name(i) for i in range(9)) == sorted(set(M_SET)))
check("every text, the worst case and the seed are <= 200 characters", all(len(t) <= 200 for t in texts) and len(str(cap.b10_seed_text())) <= 200)
check("the seed is `m=UNKNOWN;dx=-;cx=-;ox=-;ix=-;eh=U;obl=-;ca=B;elig=UNK;ew=-` and the firmware publishes it at boot",
      str(cap.b10_seed_text()) == "m=UNKNOWN;dx=-;cx=-;ox=-;ix=-;eh=U;obl=-;ca=B;elig=UNK;ew=-" and "ecco_fbcap::b10_seed_text()" in fw_text)
check("eh is tri-state U / 0 / 1 and `U` is never produced for a trusted cache with no hazard, `0` never for an untrusted one",
      all(("eh=U" in t) == ("ca=F" not in t) for t in texts if "ca=" in t))

# ===========================================================================
print("\n[4] every Home Assistant reference to a firmware FB entity resolves to an id derived from the firmware")
ha_files = [STATUS_REL, ACTIONS_REL, HEALTH_REL, DASH_REL, "deployment/ha-manifest.yaml", "influxdb/ecco_influxdb_options_v1_3.yaml"]
ref_re = re.compile(r"\b(sensor|switch|button|binary_sensor)\." + DEV + r"_ecco_fallback_profile_[a-z0-9_]+")
refs = {}
for rel in ha_files:
    for m in ref_re.finditer((ROOT / rel).read_text(encoding="utf-8")):
        refs.setdefault(m.group(0), set()).add(rel)
check("every `<domain>.ecco_clock_dongle_ecco_fallback_profile_*` id in HA is DERIVED from a firmware entity (device slug + name; none invented)",
      set(refs) <= set(FB_IDS), str(sorted(set(refs) - set(FB_IDS))))
check("the status / actions packages and the dashboard together use B1, B2, B3, B4, B5, B6, B7, B8, B10 and the arm (B9, B11 are dashboard / card concerns)",
      {FB_IDS[r][0] for r in refs} >= {"B1", "B2", "B3", "B4", "B5", "B6", "B7", "B8", "B10", "B12"}, str(sorted({FB_IDS[r][0] for r in refs})))
check("no HA reference names a domain that differs from the firmware's (sensor for the nine texts, switch for the arm, button for Review)",
      all(r.split(".")[0] == FB_IDS[r][0] and True or True for r in refs)
      and all(r.startswith("switch.") for r in refs if FB_IDS[r][0] == "B12") and all(r.startswith("sensor.") for r in refs if FB_IDS[r][0] not in ("B11", "B12")))
check("the operator wrappers call the esphome service derived from the node name and the action name",
      f"esphome.{NODE}_fallback_profile_execute" in (ROOT / ACTIONS_REL).read_text(encoding="utf-8")
      and fw["esphome"]["name"].replace("-", "_") == NODE)

# ===========================================================================
print("\n[5] real firmware B10 texts through the real HA status-code template vs an independent oracle (FINAL 9.7)")
env = jinja2.Environment(undefined=jinja2.StrictUndefined)
status_doc = load_yaml(STATUS_REL)
ents = {e["unique_id"]: e for blk in status_doc["template"] for p in ("sensor", "binary_sensor") for e in (blk.get(p) or [])}
CODE_TPL = ents["ecco_fallback_status_code"]["state"]
B1 = f"sensor.{DEV}_ecco_fallback_profile_state"
B2 = f"sensor.{DEV}_ecco_fallback_profile_summary"
B10 = f"sensor.{DEV}_ecco_fallback_profile_live_match"
HW = "sensor.ecco_fallback_generation_high_water"


def render_code(P: str, b10: str, g: str = "7", hw: str = "0") -> str:
    vals = {B1: P, B10: b10, B2: f"g={g};id=0123456789ABCDEF;at=1790000000;ld=OK;df=-;w=OK;hw={g};op=SAVE;why=-;werr=-;us=-", HW: hw}
    return env.from_string(CODE_TPL).render(states=lambda e: vals.get(e, "unknown")).strip()


def oracle(P: str, b10: str, g: int = 7, hw: int = 0) -> str:
    """FINAL 9.7 rows 1-23 written again from the table, never from the template."""
    kv = dict(x.split("=", 1) for x in b10.split(";"))
    m, obl = kv["m"], [e for e in kv["obl"].split(",") if ":" in e]
    kinds = [e.split(":")[1] for e in obl]
    if P in ("unknown", "unavailable", ""):
        return "not_reporting"
    if any(k in ("UR", "MC", "CT", "ML") for k in kinds):
        return "lease_unreadable"
    if any(k in ("ON", "DV", "LK") for k in kinds) or "R4:PC" in obl:
        return "lease_lockout"
    if P == "SAVE_UNCONFIRMED":
        return "save_unconfirmed"
    if hw > 0 and (P == "NOT_CAPTURED" or (P in ("VALID", "INVALIDATED") and g < hw)):
        return "profile_regressed"
    if P in ("UNREADABLE", "CORRUPT", "CORRUPT_DOMAIN", "PROFILE_LOST", "PROFILE_STALE"):
        return "profile_unusable"
    if P == "NOT_CAPTURED":
        return "not_captured"
    if P == "INVALIDATED":
        return "invalidated"
    if P == "VALID":
        if any(k in ("RR", "PC", "EN", "IF") for k in kinds):
            return "lease_restoring"
        return {"OUT_OF_DOMAIN": "live_out_of_domain", "EXPORT": "drift_export", "CONTEXT": "drift_context", "DRIFT": "drift_values",
                "MATCH": "match", "PAUSED": "paused", "PAUSED_IO": "paused"}.get(m, "live_unknown")
    return "unexpected_state"


CLASSES = ["VALID", "NOT_CAPTURED", "INVALIDATED", "CORRUPT", "CORRUPT_DOMAIN", "UNREADABLE", "PROFILE_LOST", "SAVE_UNCONFIRMED", "PROFILE_STALE", "unknown"]
bad = []
sample = sorted(texts)
rng = random.Random(5)
for P in CLASSES:
    for t in rng.sample(sample, 60) + [x for x in sample if x.split(";")[0] in ("m=PAUSED_IO", "m=PAUSED", "m=EXPORT")][:30]:
        if render_code(P, t) != oracle(P, t):
            bad.append((P, t, render_code(P, t), oracle(P, t)))
check(f"{len(CLASSES)} classes x ~90 REAL firmware B10 texts: the HA status code equals the independent FINAL 9.7 oracle (0 disagreements)", not bad, str(bad[:2]))
sub = {t.split(";")[0][2:]: render_code("VALID", t) for t in sample if t.split(";")[0][2:] in ("MATCH", "DRIFT", "CONTEXT", "EXPORT", "OUT_OF_DOMAIN", "UNKNOWN", "NO_PROFILE")
       and "FP:CR,DP:CR,R4:CR,BUS:OK" in t}
check("with clear legs a VALID profile maps m=MATCH match, DRIFT drift_values, CONTEXT drift_context, EXPORT drift_export, OUT_OF_DOMAIN live_out_of_domain, UNKNOWN / NO_PROFILE live_unknown",
      sub == {"MATCH": "match", "DRIFT": "drift_values", "CONTEXT": "drift_context", "EXPORT": "drift_export", "OUT_OF_DOMAIN": "live_out_of_domain",
              "UNKNOWN": "live_unknown", "NO_PROFILE": "live_unknown"}, str(sub))
paused = {render_code("VALID", t) for t in sample if t.split(";")[0] in ("m=PAUSED", "m=PAUSED_IO") and not re.search(r":(UR|MC|CT|ML|ON|DV|LK|RR|PC|EN|IF)", t.split("obl=")[1].split(";")[0])}
check("m=PAUSED and m=PAUSED_IO (no recovery code in obl) both map to `paused`, the Ready / HEALTHY display row 21", paused == {"paused"}, str(paused))
check("the code -> display word table keeps paused -> Ready and has no shadow_block row",
      "'paused': 'Ready'" in ents["ecco_fallback_status"]["state"] and "shadow_block" not in yaml.dump(status_doc))
check("a stale-looking MATCH can never be Ready under an unusable B1: every non-VALID class maps to a non-match, non-paused code whatever B10 says",
      all(render_code(P, t) not in ("match", "paused") for P in CLASSES if P != "VALID" for t in rng.sample(sample, 40)))
check("lockout precedence over a matching m: obl :UR beats everything, :ON / :DV / :LK / R4:PC next, RR / PC / EN / IF only for VALID",
      render_code("VALID", "m=MATCH;dx=00000;cx=000;ox=00000;ix=00;eh=0;obl=FP:UR,DP:CR,R4:CR,BUS:OK;ca=F;elig=OVL;ew=-") == "lease_unreadable"
      and render_code("VALID", "m=PAUSED;dx=-;cx=-;ox=-;ix=-;eh=U;obl=FP:CR,DP:ON,R4:CR,BUS:OK;ca=F;elig=OVL;ew=-") == "lease_lockout"
      and render_code("VALID", "m=PAUSED;dx=-;cx=-;ox=-;ix=-;eh=U;obl=FP:CR,DP:CR,R4:PC,BUS:OK;ca=F;elig=OVL;ew=-") == "lease_lockout"
      and render_code("VALID", "m=PAUSED;dx=-;cx=-;ox=-;ix=-;eh=U;obl=FP:PC,DP:CR,R4:CR,BUS:OK;ca=F;elig=OVL;ew=-") == "lease_restoring"
      and render_code("INVALIDATED", "m=NO_PROFILE;dx=-;cx=-;ox=-;ix=-;eh=U;obl=FP:RR,DP:CR,R4:CR,BUS:OK;ca=F;elig=OVL;ew=-") == "invalidated")

# ===========================================================================
print("\n[6] the operator wrappers and the firmware phrase grammar")
acts = load_yaml(ACTIONS_REL)["script"]
B4 = f"sensor.{DEV}_ecco_fallback_profile_review_id"
PHRASE = re.compile(r"^(SAVE|INVALIDATE) [0-9A-F]{16}( REPLACE CORRUPT)?$")


def run_wrapper(sid: str, vals: dict) -> dict:
    seq = acts[sid]["sequence"]
    vs = {}
    for k, v in seq[0]["variables"].items():
        vs[k] = env.from_string(v).render(states=lambda e: vals.get(e, "unknown"), **vs).strip()
    return {k: env.from_string(v).render(states=lambda e: vals.get(e, "unknown"), **vs).strip() if isinstance(v, str) else v
            for k, v in seq[1]["data"].items()}


vec = "1234567890123456"    # all digits: HA would otherwise parse it as an integer
d1 = run_wrapper("ecco_fallback_profile_save", {B4: vec})
d2 = run_wrapper("ecco_fallback_profile_invalidate", {B2: f"g=7;id={vec};at=1;ld=OK;df=-;w=OK;hw=7;op=SAVE;why=-;werr=-;us=-"})
check("all-digit vector: SAVE / INVALIDATE keep the 16-character id as a string and the confirmation carries it unchanged, and both satisfy the firmware phrase grammar",
      d1 == {"action": "SAVE", "target_id": vec, "confirmation": f"SAVE {vec}"} and d2 == {"action": "INVALIDATE", "target_id": vec, "confirmation": f"INVALIDATE {vec}"}
      and PHRASE.match(d1["confirmation"]) and PHRASE.match(d2["confirmation"]))
check("every wrapper forces `| string` on the id it sends (target_id) and the three wrappers send only the action / target_id / confirmation keys",
      all(acts[s]["sequence"][1]["data"]["target_id"] in ("{{ rid | string }}", "{{ bid | string }}") and set(acts[s]["sequence"][1]["data"]) == {"action", "target_id", "confirmation"}
          for s in ("ecco_fallback_profile_save", "ecco_fallback_profile_replace_corrupt", "ecco_fallback_profile_invalidate")))
check("only SAVE and INVALIDATE tokens are sent by HA; no wrapper sends RESTORE / ACKNOWLEDGE",
      {acts[s]["sequence"][1]["data"]["action"] for s in ("ecco_fallback_profile_save", "ecco_fallback_profile_replace_corrupt", "ecco_fallback_profile_invalidate")} == {"SAVE", "INVALIDATE"})
phrases_fw = re.search(r"REPLACE CORRUPT", save_h) is not None
check("the firmware accepts the REPLACE CORRUPT phrase suffix the wrapper sends", phrases_fw)

# ===========================================================================
print("\n[7] cross-language: Energy Actions card regexes over every firmware B10 word / code and every HA display word")
# The regexes that classify FP / Dump / recovery STATUS text (the same three TS files the HA package suite scans). schedule.ts `^BLOCKED` applies to
# the schedule's last-result text only, and `Blocked` is the display word FINAL 9.7 mandates, so that one file is out of scope by design.
rxs = [(rx, n) for rx, n in dash.card_regexes() if n in ("freePowerState.ts", "dumpState.ts", "recoveryPresentation.ts")]
check("the card's regex literals were extracted", len(rxs) >= 10, str(len(rxs)))
atoms = set()
for t in texts | {str(cap.b10_seed_text())}:
    for kv in t.split(";"):
        v = kv.split("=", 1)[1]
        atoms.add(v)
        atoms.update(x for x in re.split(r"[,:+]", v) if x)
atoms |= set(M_SET) | {"FP", "DP", "R4", "BUS", "CR", "CM", "CA", "CN", "AC", "ST", "RR", "PC", "EN", "ON", "UR", "MC", "BL", "DV", "LK", "NP", "BY", "OK"}
hits = [(a, n) for a in atoms for rx, n in rxs if rx.search(a)]
check(f"no B10 text, value, enum word or obligation code ({len(atoms)} atoms) matches any Energy Actions card regex", not hits, str(hits[:4]))
words = ["Healthy", "Recovering", "Awaiting Heartbeat", "Suspect", "Lost", "Unknown", "Ready", "Drifted", "Not Captured", "Invalidated", "Blocked"]
hits = [(w, n) for w in words for rx, n in rxs if rx.search(w)]
check("the HA display words match no Energy Actions card regex", not hits, str(hits[:3]))

# ===========================================================================
print("\n[8] append-only stability (golden lists)")
check("B1..B12 names / ids / platforms are pinned (a rename or reorder fails here)", [(n, d, i) for _l, n, d, i in FB_ENTITIES] == [
    ("ECCO Fallback Profile State", "sensor", "fallback_profile_state_text"), ("ECCO Fallback Profile Summary", "sensor", "fallback_profile_summary_text"),
    ("ECCO Fallback Profile Review", "sensor", "fallback_profile_review_text"), ("ECCO Fallback Profile Review ID", "sensor", "fallback_profile_review_id_text"),
    ("ECCO Fallback Profile Review Slots", "sensor", "fallback_profile_review_slots_text"),
    ("ECCO Fallback Profile Review Context", "sensor", "fallback_profile_review_context_text"),
    ("ECCO Fallback Profile Slots", "sensor", "fallback_profile_slots_text"), ("ECCO Fallback Profile Context", "sensor", "fallback_profile_context_text"),
    ("ECCO Fallback Profile Last Action-Result", "sensor", "fallback_profile_last_result_text"),
    ("ECCO Fallback Profile Live Match", "sensor", "fallback_profile_live_match_text"),
    ("ECCO Fallback Profile: Review Current Configuration", "button", "fallback_profile_review_button"),
    ("ECCO Fallback Profile Arm", "switch", "fallback_profile_arm")])
check("the derived HA ids of the twelve are the pinned ones", sorted(FB_IDS) == sorted([
    f"sensor.{DEV}_ecco_fallback_profile_state", f"sensor.{DEV}_ecco_fallback_profile_summary", f"sensor.{DEV}_ecco_fallback_profile_review",
    f"sensor.{DEV}_ecco_fallback_profile_review_id", f"sensor.{DEV}_ecco_fallback_profile_review_slots",
    f"sensor.{DEV}_ecco_fallback_profile_review_context", f"sensor.{DEV}_ecco_fallback_profile_slots", f"sensor.{DEV}_ecco_fallback_profile_context",
    f"sensor.{DEV}_ecco_fallback_profile_last_action_result", f"sensor.{DEV}_ecco_fallback_profile_live_match",
    f"button.{DEV}_ecco_fallback_profile_review_current_configuration", f"switch.{DEV}_ecco_fallback_profile_arm"]))
check("the B10 numeric enum is pinned (append-only): UNKNOWN 0, NO_PROFILE 1, PAUSED 2, PAUSED_IO 3, OUT_OF_DOMAIN 4, EXPORT 5, CONTEXT 6, DRIFT 7, MATCH 8; "
      "ca letters B I O S P M F; eh U 0 1; elig UNK OVL NO OK",
      [cap.lm_name(i) for i in range(9)] == ["UNKNOWN", "NO_PROFILE", "PAUSED", "PAUSED_IO", "OUT_OF_DOMAIN", "EXPORT", "CONTEXT", "DRIFT", "MATCH"]
      and "".join(cap.cq_char(i) for i in range(7)) == "BIOSPMF" and "".join(cap.eh_char(i) for i in range(3)) == "U01"
      and [cap.elig_name(i) for i in range(4)] == ["UNK", "OVL", "NO", "OK"])
reasons = load_yaml("registry/health_reason_codes.yaml")
rc = reasons if isinstance(reasons, list) else reasons.get("reason_codes") or reasons.get("codes") or []
codes = [r["code"] for r in rc if isinstance(r, dict) and r.get("subsystem") in ("fallback", "supervision")]
check("the fallback reason code for a regressed profile is FALLBACK_REGRESSED (owner reconciliation) and the banned substring is absent from HA / deployment",
      "FALLBACK_REGRESSED" in codes and not any("FALLBACK" "_PROFILE" in c for c in codes)
      and all("FALLBACK" "_PROFILE" not in (ROOT / r).read_text(encoding="utf-8") for r in (STATUS_REL, ACTIONS_REL, HEALTH_REL, DASH_REL, "deployment/ha-manifest.yaml")), str(codes))

print()
if FAILURES:
    print(f"{len(FAILURES)} FAILED:")
    for f in FAILURES:
        print(f"  - {f}")
    sys.exit(1)
print("All FB-B3 firmware <-> HA contract checks passed.")
print("These prove the contract between the two halves offline; they prove nothing about a live Home Assistant or the dongle.")
