#!/usr/bin/env python3
"""Offline tests for the FB-B3 Home Assistant status / actions / health layer.

Covers Slice B (status / actions / health) and Slice C (dashboard, manifest, InfluxDB v1.3, release metadata):
  home-assistant/packages/ecco_fallback_status.yaml          (display, read-only)
  home-assistant/packages/ecco_fallback_profile_actions.yaml (operator scripts)
  the FB-B3 additions to home-assistant/packages/ecco_system_health.yaml

Contract: docs/architecture/fallback/FINAL_FBB_FBC_ARCHITECTURE.md section 9.6
and 9.7, and design/S5_ha_contract_ux_final.md Part A (which overrides Part B).

Templates are rendered with plain jinja2 and small stand-ins for the Home
Assistant functions they use (states, state_attr, as_timestamp, now, this,
trigger). This does NOT prove the templates behave identically inside a real
Home Assistant instance (that needs `ha core check` plus live observation);
the packages remain STAGED / NOT LIVE-PROVEN.

DELIBERATELY NOT COVERED HERE (integration obligations, need the firmware B10
commit and/or the dashboard and manifest slices; see
docs/architecture/fallback/FB_B3_HA_SLICE_NOTES.md):
  - firmware entity-id derivation including B10, B10 grammar goldens
  - cross-language card-regex scan of firmware/display literals
  - dashboard references to the scripts, manifest package listing
  - InfluxDB options, the whole-repo reserved-token allowlist
  - the final FB-B3 scope-chain registration
"""

from __future__ import annotations

import itertools
import re
import sys
from pathlib import Path

import jinja2
import yaml

ROOT = Path(__file__).resolve().parents[2]
HA = ROOT / "home-assistant"
STATUS_PKG = HA / "packages" / "ecco_fallback_status.yaml"
ACTIONS_PKG = HA / "packages" / "ecco_fallback_profile_actions.yaml"
HEALTH_PKG = HA / "packages" / "ecco_system_health.yaml"
REASON_CODES = ROOT / "registry" / "health_reason_codes.yaml"
CHECKS = ROOT / "registry" / "system_health_checks.yaml"

FAILURES: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  PASS  {name}")
    else:
        FAILURES.append(name)
        print(f"  FAIL  {name}" + (f" - {detail}" if detail else ""))


class TaggedSafeLoader(yaml.SafeLoader):
    """Tolerates Home Assistant custom !tags."""


def _construct_unknown(loader, tag_suffix, node):
    if isinstance(node, yaml.ScalarNode):
        return loader.construct_scalar(node)
    if isinstance(node, yaml.SequenceNode):
        return loader.construct_sequence(node)
    return loader.construct_mapping(node)


TaggedSafeLoader.add_multi_constructor("!", _construct_unknown)


def load(path: Path):
    return yaml.load(path.read_text(encoding="utf-8"), Loader=TaggedSafeLoader)


def code_text(path: Path) -> str:
    """File text with `#` comment lines removed (headers document prohibitions)."""
    return "\n".join(
        line for line in path.read_text(encoding="utf-8").splitlines() if not line.strip().startswith("#")
    )


# Banned tokens are assembled from fragments (the dump-to-grid test precedent)
# so this file never trips the repository-wide scope pins itself.
FB = "fall" + "back_profile"
EXECUTE = FB + "_execute"
ARM_ENTITY = FB + "_arm"

# ---------------------------------------------------------------------------
# entity ids
# ---------------------------------------------------------------------------
DEV = "ecco_clock_dongle"
B1 = f"sensor.{DEV}_ecco_fallback_profile_state"
B2 = f"sensor.{DEV}_ecco_fallback_profile_summary"
B3 = f"sensor.{DEV}_ecco_fallback_profile_review"
B4 = f"sensor.{DEV}_ecco_fallback_profile_review_id"
B7 = f"sensor.{DEV}_ecco_fallback_profile_slots"
B8 = f"sensor.{DEV}_ecco_fallback_profile_context"
B10 = f"sensor.{DEV}_ecco_fallback_profile_live_match"
ARM = f"switch.{DEV}_ecco_fallback_profile_arm"
SUP_STATE = f"sensor.{DEV}_ecco_supervision_state"
SUP_STABLE = f"binary_sensor.{DEV}_ecco_supervision_stable"
HW = "sensor.ecco_fallback_generation_high_water"
CODE = "sensor.ecco_fallback_status_code"

env = jinja2.Environment(undefined=jinja2.StrictUndefined)


class _States:
    """Stand-in for HA's `states`: callable and subscriptable (states[e].last_changed)."""

    class _Obj:
        def __init__(self, last_changed: float):
            self.last_changed = last_changed

    def __init__(self, values: dict[str, str], last_changed: dict[str, float] | None = None):
        self.values = values
        self.last_changed = last_changed or {}

    def __call__(self, entity_id: str) -> str:
        return self.values.get(entity_id, "unknown")

    def __getitem__(self, entity_id: str):
        return self._Obj(self.last_changed.get(entity_id, 0.0))


def render(template: str, values: dict[str, str], *, extra: dict | None = None,
           last_changed: dict[str, float] | None = None, now: float = 10_000.0) -> str:
    ctx = {
        "states": _States(values, last_changed),
        "state_attr": lambda e, a: values.get(f"{e}#{a}", ""),
        "as_timestamp": lambda v: float(v),
        "now": lambda: now,
    }
    ctx.update(extra or {})
    return env.from_string(template).render(**ctx).strip()


status_doc = load(STATUS_PKG)
actions_doc = load(ACTIONS_PKG)
health_doc = load(HEALTH_PKG)


def template_entities(doc) -> dict[str, dict]:
    """unique_id -> entity definition (+ '_trigger_block' for trigger-based ones)."""
    out: dict[str, dict] = {}
    for block in doc.get("template", []):
        for platform in ("sensor", "binary_sensor"):
            for ent in block.get(platform, []) or []:
                e = dict(ent)
                e["_platform"] = platform
                e["_triggers"] = block.get("triggers")
                out[ent["unique_id"]] = e
    return out


STATUS_ENT = template_entities(status_doc)
HEALTH_ENT = template_entities(health_doc)


def tpl(ent: dict, attr: str | None = None) -> str:
    return ent["state"] if attr is None else ent["attributes"][attr]


# ===========================================================================
print("[1] Status package: read-only, exact entity and helper set")
status_code_text = code_text(STATUS_PKG)
for token in ["service:", "action:", "automation:", "script:", "esphome.", "button.press", "switch.turn_on",
              "switch.toggle", "modbus_client", "homeassistant.restart", "homeassistant.reload",
              "shell_command:", "command_line:", "recorder:", "fallback_profile_execute"]:
    check(f"status package does not contain {token!r} outside a comment", token not in status_code_text)
check("status package top-level keys are exactly template + input_boolean",
      sorted(status_doc) == ["input_boolean", "template"], str(sorted(status_doc)))
check("status package header states it is a display/read-only layer",
      "READ-ONLY DISPLAY LAYER" in STATUS_PKG.read_text(encoding="utf-8")
      and "never a firmware safety primitive" in STATUS_PKG.read_text(encoding="utf-8")
      and "NOT a control" in STATUS_PKG.read_text(encoding="utf-8"))
check("exact status-package helper set",
      list(status_doc["input_boolean"]) == ["ecco_safety_show_technical_detail"])
helper = status_doc["input_boolean"]["ecco_safety_show_technical_detail"]
check("helper name/icon/initial", helper == {
    "name": "ECCO Safety Show Technical Detail", "icon": "mdi:chevron-down-box-outline", "initial": False}, str(helper))
check("no deprecated saved-view copies (Part A drops them)",
      "ecco_fallback_saved_slots" not in status_code_text and "ecco_fallback_saved_context" not in status_code_text)

print("")
print("[2] Exact new HA template entities / unique ids")
expected_status = {
    "ecco_supervision_status": ("sensor", "ECCO Supervision Status"),
    "ecco_fallback_status_code": ("sensor", "ECCO Fallback Status Code"),
    "ecco_fallback_status": ("sensor", "ECCO Fallback Status"),
    "ecco_fallback_generation_high_water": ("sensor", "ECCO Fallback Generation High Water"),
    "ecco_fallback_save_available": ("binary_sensor", "ECCO Fallback Save Available"),
    "ecco_fallback_replace_corrupt_available": ("binary_sensor", "ECCO Fallback Replace Corrupt Available"),
    "ecco_fallback_invalidate_available": ("binary_sensor", "ECCO Fallback Invalidate Available"),
    # FB-C3: the diagnostic decoder of the five dongle shadow strings and its banner flag (test_ecco_shadow_check_ux.py owns their behaviour)
    "ecco_shadow_check": ("sensor", "ECCO Shadow Check"),
    "ecco_shadow_episode_open": ("binary_sensor", "ECCO Shadow Episode Open"),
}
check("status package defines exactly the locked unique ids",
      sorted(STATUS_ENT) == sorted(expected_status), str(sorted(STATUS_ENT)))
for uid, (platform, name) in expected_status.items():
    ent = STATUS_ENT.get(uid, {})
    check(f"{uid}: platform {platform} and name {name!r}",
          ent.get("_platform") == platform and ent.get("name") == name)
hw_ent = STATUS_ENT["ecco_fallback_generation_high_water"]
check("only the high-water sensor is trigger-based", [u for u, e in STATUS_ENT.items() if e["_triggers"]] ==
      ["ecco_fallback_generation_high_water"])
check("health package adds ecco_health_supervision and ecco_health_fallback",
      "ecco_health_supervision" in HEALTH_ENT and "ecco_health_fallback" in HEALTH_ENT)

# ===========================================================================
print("")
print("[3] Supervision status matrix (6 display values, 4 x 3 inputs)")
SUP = STATUS_ENT["ecco_supervision_status"]["state"]
expect = {
    ("SUPERVISED", "on"): "Healthy", ("SUPERVISED", "off"): "Recovering",
    ("SUPERVISED", "unknown"): "Unknown", ("SUPERVISED", "unavailable"): "Unknown",
    ("SUSPECT", "on"): "Suspect", ("SUSPECT", "off"): "Suspect", ("SUSPECT", "unknown"): "Suspect",
    ("LOST", "on"): "Lost", ("LOST", "off"): "Lost", ("LOST", "unknown"): "Lost",
    ("STARTUP", "on"): "Awaiting Heartbeat", ("STARTUP", "off"): "Awaiting Heartbeat",
    ("STARTUP", "unknown"): "Awaiting Heartbeat",
    ("unknown", "on"): "Unknown", ("unavailable", "off"): "Unknown", ("", "on"): "Unknown",
    ("WEIRD", "on"): "Unknown",
}
for (s, st), want in expect.items():
    got = render(SUP, {SUP_STATE: s, SUP_STABLE: st})
    check(f"supervision {s!r}/{st!r} -> {want}", got == want, f"got {got!r}")
check("the old 'Starting' display word is gone", "Starting" not in SUP)

# ===========================================================================
print("")
print("[4] Fallback status-code matrix (FINAL 9.7 precedence)")
CODE_TPL = STATUS_ENT["ecco_fallback_status_code"]["state"]


def lm(m="MATCH", obl="FP:CR,DP:CR,R4:CR,BUS:OK", eh="0", dx="-", cx="-", ew="-") -> str:
    return f"m={m};dx={dx};cx={cx};ox=-;ix=-;eh={eh};obl={obl};ca=F;elig=OK;ew={ew}"


def code_for(P="VALID", live=None, hw="0", g="7") -> str:
    summary = f"g={g};id=D852A4FA2DF7DBA3;at=1790000000;ld=OK;df=-;w=OK;hw={g};op=SAVE;why=-;werr=-;us=-"
    values = {B1: P, B2: summary, HW: hw}
    if live is not None:
        values[B10] = live
    return render(CODE_TPL, values)


rows = [
    # (P, live-match, hw, g, expected)
    ("unknown", lm(), "0", "7", "not_reporting"),
    ("unavailable", lm(), "0", "7", "not_reporting"),
    ("none", lm(), "0", "7", "not_reporting"),
    ("", lm(), "0", "7", "not_reporting"),
    # not_reporting wins over a lockout (row 1 first)
    ("unknown", lm(obl="FP:UR,DP:CR,R4:CR,BUS:OK"), "0", "7", "not_reporting"),
    # lease_unreadable (row 7): UR MC CT ML, before everything but row 1
    ("VALID", lm(obl="FP:UR,DP:CR,R4:CR,BUS:OK"), "0", "7", "lease_unreadable"),
    ("VALID", lm(obl="FP:CR,DP:MC,R4:CR,BUS:OK"), "0", "7", "lease_unreadable"),
    ("VALID", lm(obl="FP:CR,DP:CR,R4:CT,BUS:OK"), "0", "7", "lease_unreadable"),
    ("VALID", lm(obl="FP:ML,DP:CR,R4:CR,BUS:OK"), "0", "7", "lease_unreadable"),
    ("NOT_CAPTURED", lm(m="NO_PROFILE", obl="FP:UR,DP:CR,R4:CR,BUS:OK"), "0", "-", "lease_unreadable"),
    ("SAVE_UNCONFIRMED", lm(obl="FP:UR,DP:CR,R4:CR,BUS:OK"), "0", "7", "lease_unreadable"),
    ("CORRUPT", lm(obl="FP:UR,DP:CR,R4:CR,BUS:OK"), "0", "-", "lease_unreadable"),
    # unreadable outranks lockout
    ("VALID", lm(obl="FP:UR,DP:ON,R4:CR,BUS:OK"), "0", "7", "lease_unreadable"),
    # lease_lockout (row 8): ON DV LK and R4:PC; FP/DP PC is restoring, not a lockout
    ("VALID", lm(obl="FP:ON,DP:CR,R4:CR,BUS:OK"), "0", "7", "lease_lockout"),
    ("VALID", lm(obl="FP:CR,DP:DV,R4:CR,BUS:OK"), "0", "7", "lease_lockout"),
    ("VALID", lm(obl="FP:CR,DP:CR,R4:CR,BUS:LK"), "0", "7", "lease_lockout"),
    ("VALID", lm(obl="FP:CR,DP:CR,R4:PC,BUS:OK"), "0", "7", "lease_lockout"),
    ("INVALIDATED", lm(obl="FP:CR,DP:CR,R4:PC,BUS:OK"), "0", "8", "lease_lockout"),
    ("NOT_CAPTURED", lm(m="NO_PROFILE", obl="FP:ON,DP:CR,R4:CR,BUS:OK"), "0", "-", "lease_lockout"),
    ("VALID", lm(obl="FP:PC,DP:CR,R4:CR,BUS:OK"), "0", "7", "lease_restoring"),
    ("VALID", lm(obl="FP:CR,DP:PC,R4:CR,BUS:OK"), "0", "7", "lease_restoring"),
    # rows 10-14 (profile class), lockout rows already above them
    ("SAVE_UNCONFIRMED", lm(), "0", "7", "save_unconfirmed"),
    ("UNREADABLE", lm(m="NO_PROFILE"), "0", "-", "profile_unusable"),
    ("CORRUPT", lm(m="NO_PROFILE"), "0", "-", "profile_unusable"),
    ("CORRUPT_DOMAIN", lm(m="NO_PROFILE"), "0", "7", "profile_unusable"),
    ("PROFILE_LOST", lm(m="NO_PROFILE"), "0", "-", "profile_unusable"),
    ("PROFILE_STALE", lm(m="NO_PROFILE"), "0", "-", "profile_unusable"),
    ("NOT_CAPTURED", lm(m="NO_PROFILE"), "0", "-", "not_captured"),
    ("INVALIDATED", lm(m="NO_PROFILE"), "0", "8", "invalidated"),
    # profile_regressed (row 11): high-water above the device, detection only
    ("NOT_CAPTURED", lm(m="NO_PROFILE"), "5", "-", "profile_regressed"),
    ("VALID", lm(), "9", "7", "profile_regressed"),
    ("INVALIDATED", lm(m="NO_PROFILE"), "9", "8", "profile_regressed"),
    ("VALID", lm(), "7", "7", "match"),
    ("VALID", lm(), "6", "7", "match"),
    ("VALID", lm(), "0", "7", "match"),
    ("INVALIDATED", lm(m="NO_PROFILE"), "8", "8", "invalidated"),
    ("NOT_CAPTURED", lm(m="NO_PROFILE"), "0", "-", "not_captured"),
    # save_unconfirmed outranks regressed; regressed outranks unusable
    ("SAVE_UNCONFIRMED", lm(), "9", "7", "save_unconfirmed"),
    ("PROFILE_LOST", lm(m="NO_PROFILE"), "9", "-", "profile_unusable"),
    # VALID rows 15-22
    ("VALID", lm(m="OUT_OF_DOMAIN"), "0", "7", "live_out_of_domain"),
    ("VALID", lm(m="EXPORT"), "0", "7", "drift_export"),
    ("VALID", lm(m="CONTEXT"), "0", "7", "drift_context"),
    ("VALID", lm(m="DRIFT"), "0", "7", "drift_values"),
    ("VALID", lm(m="MATCH"), "0", "7", "match"),
    ("VALID", lm(m="PAUSED"), "0", "7", "paused"),
    ("VALID", lm(m="PAUSED_IO"), "0", "7", "paused"),
    ("VALID", lm(m="PAUSED", obl="FP:AC,DP:CR,R4:CR,BUS:OK"), "0", "7", "paused"),
    ("VALID", lm(m="UNKNOWN"), "0", "7", "live_unknown"),
    ("VALID", lm(m="NO_PROFILE"), "0", "7", "live_unknown"),
    ("VALID", lm(m="SOMETHING_NEW"), "0", "7", "live_unknown"),
    # restoring outranks every m
    ("VALID", lm(m="DRIFT", obl="FP:RR,DP:CR,R4:CR,BUS:OK"), "0", "7", "lease_restoring"),
    ("VALID", lm(m="MATCH", obl="FP:CR,DP:EN,R4:CR,BUS:OK"), "0", "7", "lease_restoring"),
    ("VALID", lm(m="MATCH", obl="FP:IF,DP:CR,R4:CR,BUS:OK"), "0", "7", "lease_restoring"),
    ("VALID", lm(m="MATCH", obl="FP:CR,DP:CR,R4:RR,BUS:OK"), "0", "7", "lease_restoring"),
    # an ACTIVE lease alone is not a lockout/restoring row
    ("VALID", lm(m="DRIFT", obl="FP:ST,DP:CR,R4:CR,BUS:OK"), "0", "7", "drift_values"),
    # anything else
    ("WEIRD_CLASS", lm(), "0", "7", "unexpected_state"),
    # Live Match entity missing (firmware without B10): a VALID profile is Unknown, never Ready
    ("VALID", None, "0", "7", "live_unknown"),
]
for P, live, hw, g, want in rows:
    got = code_for(P=P, live=live, hw=hw, g=g)
    check(f"P={P!r} live={'-' if live is None else live[:2] + '..' + live[live.find('obl='):live.find(';ca')]} hw={hw} -> {want}",
          got == want, f"got {got!r}")

# FB-C3: the shadow_episode row is now LIVE (exactly one, fed only by the Shadow State: test_ecco_shadow_check_ux.py [2]); the deleted
# shadow_block cause and the FB-E/F failback_* causes are still not emitted.
check("FB-C3: shadow_episode is live; the deleted shadow_block cause and the FB-E/F failback_* codes are still not emitted",
      "shadow_episode" in CODE_TPL
      and not any(c in CODE_TPL for c in ["'shadow_block'", "shadow_block", "failback_applying", "failback_applied",
                                           "failback_ack_required", "failback_blocked", "failback_record_unusable"]))
check("FB-C3 consumed its two insertion anchors (two lines tagged C3 now) and the FB-E/F insertion anchor is still present as a comment",
      "FB-C3 shadow_episode row inserts here" not in CODE_TPL and "FB-C3 inserts the shadow-state inputs here" not in CODE_TPL
      and CODE_TPL.count("{#- C3 -#}") == 2 and "FB-E/F rows 2-6 insert here" in CODE_TPL)

# ===========================================================================
print("")
print("[5] Display lookup is total and exact")
DISPLAY_TPL = STATUS_ENT["ecco_fallback_status"]["state"]
display_expect = {
    "not_reporting": "Unknown", "unexpected_state": "Unknown", "live_unknown": "Unknown",
    "lease_unreadable": "Blocked", "lease_lockout": "Blocked", "lease_restoring": "Blocked",
    "save_unconfirmed": "Blocked", "profile_regressed": "Blocked", "profile_unusable": "Blocked",
    "live_out_of_domain": "Blocked", "not_captured": "Not Captured", "invalidated": "Invalidated",
    "drift_export": "Drifted", "drift_context": "Drifted", "drift_values": "Drifted",
    "match": "Ready", "paused": "Ready",
    "shadow_episode": "Shadow Recovery",   # FB-C3
    "something_else": "Unknown", "unknown": "Unknown", "unavailable": "Unknown",
}
for code, word in display_expect.items():
    got = render(DISPLAY_TPL, {CODE: code})
    check(f"display {code} -> {word}", got == word, f"got {got!r}")
produced = {c for _, _, _, _, c in rows}
check("every code the status-code template can emit has a display word",
      produced <= set(display_expect), str(sorted(produced - set(display_expect))))
# FB-C3: one word is added (Shadow Recovery); the FB-E/F words (Applying / Applied / Needs Acknowledgement) stay reserved.
check("the user-facing vocabulary is exactly Unknown/Blocked/Not Captured/Invalidated/Drifted/Ready plus the FB-C3 Shadow Recovery",
      set(display_expect.values()) == {"Unknown", "Blocked", "Not Captured", "Invalidated", "Drifted", "Ready", "Shadow Recovery"})

# sublines: total over the code set, no unresolved placeholders, never empty
SUBLINE = STATUS_ENT["ecco_fallback_status"]["attributes"]["subline"]
for code in sorted(display_expect):
    values = {CODE: code, B1: "VALID", B10: lm(m="PAUSED", obl="FP:AC,DP:CR,R4:CR,BUS:OK"), B2: "g=7;id=D852A4FA2DF7DBA3;hw=7"}
    got = render(SUBLINE, values)
    check(f"subline for {code} is non-empty with no template residue", bool(got) and "{{" not in got and "<" not in got, repr(got))
check("lease_unreadable subline warns not to restart",
      render(SUBLINE, {CODE: "lease_unreadable", B10: lm(obl="DP:UR,FP:CR,R4:CR,BUS:OK")}).startswith(
          "Do NOT restart the dongle: Dump to Grid recovery state is unreadable"))
check("drift_values subline counts differing places from dx",
      "in 3 places" in render(SUBLINE, {CODE: "drift_values", B10: lm(m="DRIFT", dx="00007")}))
check("export hazard eh=1 is appended to a lockout subline",
      "Export is currently ENABLED while Free Power needs recovery." in render(
          SUBLINE, {CODE: "lease_lockout", B10: lm(obl="FP:ON,DP:CR,R4:CR,BUS:OK", eh="1")}))
check("export hazard eh=U with a Dump obligation says state unknown",
      "Export state unknown - check the inverter." in render(
          SUBLINE, {CODE: "lease_lockout", B10: lm(obl="FP:CR,DP:ON,R4:CR,BUS:OK", eh="U")}))
check("paused subline names the running feature (Ready, with subline)",
      render(SUBLINE, {CODE: "paused", B10: lm(m="PAUSED", obl="FP:AC,DP:CR,R4:CR,BUS:OK")}) ==
      "Free Power is running - a restore would first end it")

# ===========================================================================
print("")
print("[6] Save / Replace Corrupt / Invalidate available truth tables")
SAVE_T = STATUS_ENT["ecco_fallback_save_available"]["state"]
RC_T = STATUS_ENT["ecco_fallback_replace_corrupt_available"]["state"]
INV_T = STATUS_ENT["ecco_fallback_invalidate_available"]["state"]


def review(st="CANDIDATE_READY", prior="NOT_CAPTURED") -> str:
    return f"st={st};prior={prior};exp=100;warn=-;obl=FP:CA,DP:CA,R4:CA,MT:CN,FS:CA,BUS:OK;latch=-;sv=OK"


def truth(t: str, values: dict[str, str]) -> bool:
    return render(t, values).strip().lower() == "true"


for st, prior, rid, arm in itertools.product(
        ["CANDIDATE_READY", "IDLE", "CANDIDATE_NOT_SAVEABLE", "READING", "SAVING"],
        ["NOT_CAPTURED", "VALID", "CORRUPT", "INVALIDATED"],
        ["D852A4FA2DF7DBA3", "-", "1234567890123456", "SHORT"],
        ["on", "off", "unknown"]):
    values = {B3: review(st, prior), B4: rid, ARM: arm}
    base = st == "CANDIDATE_READY" and len(rid) == 16 and arm == "on"
    want_save = base and prior != "CORRUPT"
    want_rc = base and prior == "CORRUPT"
    ok = truth(SAVE_T, values) == want_save and truth(RC_T, values) == want_rc
    if not ok:
        check(f"save/replace truth st={st} prior={prior} rid={rid} arm={arm}", False,
              f"save={truth(SAVE_T, values)} rc={truth(RC_T, values)}")
        break
else:
    check("save / replace-corrupt availability matches the truth table over 240 inputs", True)
check("save_available is false for a CORRUPT prior even when everything else holds",
      not truth(SAVE_T, {B3: review(prior="CORRUPT"), B4: "D852A4FA2DF7DBA3", ARM: "on"}))
check("replace_corrupt_available is true only for a CORRUPT prior",
      truth(RC_T, {B3: review(prior="CORRUPT"), B4: "D852A4FA2DF7DBA3", ARM: "on"}))
for P, bid, arm in itertools.product(["VALID", "INVALIDATED", "NOT_CAPTURED", "unknown"],
                                     ["D852A4FA2DF7DBA3", "-", "SHORT"], ["on", "off"]):
    values = {B1: P, B2: f"g=7;id={bid};at=1;ld=OK;df=-;w=OK;hw=7;op=SAVE;why=-;werr=-;us=-", ARM: arm}
    want = P == "VALID" and len(bid) == 16 and arm == "on"
    if truth(INV_T, values) != want:
        check(f"invalidate truth P={P} bid={bid} arm={arm}", False)
        break
else:
    check("invalidate availability matches the truth table over 24 inputs", True)

# ===========================================================================
print("")
print("[7] Generation high-water: rises from authentic generations, resets only on the event")
HW_T = hw_ent["state"]


def hw_render(P: str, g: str, prev: str, trig_id: str = "0") -> str:
    values = {B1: P, B2: f"g={g};id=D852A4FA2DF7DBA3;at=1;ld=OK;df=-;w=OK;hw=7;op=SAVE;why=-;werr=-;us=-"}

    class This:
        state = prev

    return render(HW_T, values, extra={"this": This, "trigger": type("T", (), {"id": trig_id})})


for P, g, prev, trig, want in [
    ("VALID", "7", "unknown", "0", "7"),
    ("VALID", "7", "9", "0", "9"),
    ("VALID", "12", "9", "0", "12"),
    ("INVALIDATED", "8", "7", "1", "8"),
    ("NOT_CAPTURED", "-", "9", "0", "9"),
    ("unavailable", "-", "9", "0", "9"),
    ("SAVE_UNCONFIRMED", "7", "5", "0", "5"),
    ("CORRUPT", "-", "5", "0", "5"),
    ("VALID", "7", "9", "reset", "7"),
    ("NOT_CAPTURED", "-", "9", "reset", "0"),
]:
    got = hw_render(P, g, prev, trig)
    check(f"high-water P={P} g={g} prev={prev} trigger={trig} -> {want}", got == want, f"got {got!r}")
check("high-water sensor listens to the reset event and to B1/B2",
      any(t.get("event_type") == "ecco_fallback_reset_high_water" and t.get("id") == "reset"
          for t in hw_ent["_triggers"])
      and any(set(t.get("entity_id", [])) == {B1, B2} for t in hw_ent["_triggers"]))
check("the status-code template reads the high-water entity", HW in CODE_TPL)

# ===========================================================================
print("")
print("[8] Saved-profile decoders (244 in {0,1,2,other}, 243, bit0 flags, source words)")
ATTR = STATUS_ENT["ecco_fallback_status"]["attributes"]


def dec(attr: str, values: dict[str, str]) -> str:
    return render(ATTR[attr], values)


for v, want in [("0", "Allow Export"), ("1", "Essentials"), ("2", "Zero Export"), ("7", "unrecognised (7)"), ("-", "-")]:
    got = dec("saved_export_mode", {B7: f"v=SAVED;g=7;244={v};1=0000/8000/100/1;dx=-;b=00112233"})
    check(f"saved_export_mode 244={v} -> {want}", got == want, f"got {got!r}")
for v, want in [("0", "Battery First"), ("1", "Load First"), ("3", "unrecognised (3)")]:
    got = dec("saved_energy_mode", {B8: f"v=SAVED;232=0011;243={v};248=0001;ring=OK;230=185;245=8000;247=0001;dc=-;di=-;b=0011"})
    check(f"saved_energy_mode 243={v} -> {want}", got == want, f"got {got!r}")
ctxv = {B8: "v=SAVED;232=0011;243=1;248=0000;ring=OK;230=1;245=8000;247=0001;dc=-;di=-;b=0011"}
check("saved_grid_charging reads 232 bit0", dec("saved_grid_charging", ctxv) == "on")
check("saved_tou_schedule reads 248 bit0", dec("saved_tou_schedule", ctxv) == "off")
slots = "v=SAVED;g=7;244=2;1=0000/8000/100/0;2=0530/500/20/1;3=1000/4000/0/2;4=1600/3000/50/3;5=2100/2000/100/5;6=2330/1000/30/99;dx=-;b=0011"
check("saved_sources decodes the six source words (incl. raw out-of-domain word)",
      dec("saved_sources", {B7: slots}) ==
      "None | Grid | Generator | Grid + Generator | Grid + General | raw 0x0063", dec("saved_sources", {B7: slots}))
live_drift = {B10: lm(m="DRIFT", dx="00003", cx="001FB")}
check("drift_count popcounts dx and cx", dec("drift_count", live_drift) == "10", dec("drift_count", live_drift))
cells = dec("drift_cells", {B10: lm(m="DRIFT", dx="00003", cx="00001")})
check("drift_cells names bit0 244 / bit1 power1 and cx bit0 232.b0",
      cells == "['export_mode', 'power1', 'grid_charging']", cells)
check("drift_cells is empty with no masks", dec("drift_cells", {B10: lm()}) == "[]")

# ---- [8b] FB-B3 integration: the CANDIDATE (Review) decoders live in HA template attributes, same tables as the saved ones
B5C = f"sensor.{DEV}_ecco_fallback_profile_review_slots"
B6C = f"sensor.{DEV}_ecco_fallback_profile_review_context"
for v, want in [("0", "Allow Export"), ("1", "Essentials"), ("2", "Zero Export"), ("7", "unrecognised (7)"), ("-", "-")]:
    got = dec("candidate_export_mode", {B5C: f"244={v};1=0000/8000/100/1;dx=00000"})
    check(f"candidate_export_mode 244={v} -> {want}", got == want, f"got {got!r}")
for v, want in [("0", "Battery First"), ("1", "Load First"), ("3", "unrecognised (3)"), ("-", "-")]:
    got = dec("candidate_energy_mode", {B6C: f"232=0011;243={v};248=0001;ring=OK;230=185;245=8000;247=0001;dc=000;di=00"})
    check(f"candidate_energy_mode 243={v} -> {want}", got == want, f"got {got!r}")
cctx = {B6C: "232=0011;243=1;248=0000;ring=OK;230=1;245=8000;247=0001;dc=000;di=00"}
check("candidate_grid_charging reads 232 bit0 (hex word 0011 -> on, 0010 -> off, - -> -)",
      dec("candidate_grid_charging", cctx) == "on"
      and dec("candidate_grid_charging", {B6C: "232=0010;243=1;248=0001"}) == "off"
      and dec("candidate_grid_charging", {B6C: "v=NONE"}) == "-")
check("candidate_tou_schedule reads 248 bit0 (0000 -> off, 0001 -> on, 0003 -> on, - -> -)",
      dec("candidate_tou_schedule", cctx) == "off"
      and dec("candidate_tou_schedule", {B6C: "232=0011;243=1;248=0001"}) == "on"
      and dec("candidate_tou_schedule", {B6C: "232=0011;243=1;248=0003"}) == "on"
      and dec("candidate_tou_schedule", {B6C: "v=NONE"}) == "-")
cslots = "244=2;1=0000/8000/100/0;2=0530/500/20/1;3=1000/4000/0/2;4=1600/3000/50/3;5=2100/2000/100/5;6=2330/1000/30/99;dx=00000"
check("candidate_sources decodes the six source words exactly like the saved decoder (incl. the raw out-of-domain word)",
      dec("candidate_sources", {B5C: cslots}) == "None | Grid | Generator | Grid + Generator | Grid + General | raw 0x0063"
      and dec("candidate_sources", {B5C: cslots}) == dec("saved_sources", {B7: cslots}), dec("candidate_sources", {B5C: cslots}))
words = {0: "None", 1: "Grid", 2: "Generator", 3: "Grid + Generator", 4: "None + General", 8: "None + Backup", 16: "None + Charge",
         5: "Grid + General", 9: "Grid + Backup", 17: "Grid + Charge", 28: "None + General + Backup + Charge",
         29: "Grid + General + Backup + Charge", 31: "Grid + Generator + General + Backup + Charge", 32: "raw 0x0020",
         32768: "raw 0x8000", 65535: "raw 0xFFFF"}
bad = []
for w, want in words.items():
    got = dec("candidate_sources", {B5C: f"244=2;1=0000/8000/100/{w};2=-;3=-;4=-;5=-;6=-;dx=00000"}).split(" | ")[0]
    if got != want:
        bad.append((w, got, want))
check("candidate_sources: source 0 None / 1 Grid / 2 Generator / 3 Grid + Generator, mode bits 0x04 General / 0x08 Backup / 0x10 Charge, any bit above -> raw 0x%04X",
      not bad, str(bad))
check("candidate_sources with no candidate renders six `-`", dec("candidate_sources", {B5C: "v=NONE"}) == "- | - | - | - | - | -")
check("candidate_changed_cells names exactly the changed export / power / soc / source cells from B5 dx",
      dec("candidate_changed_cells", {B5C: "244=2;1=0000/8000/100/0;dx=00000"}) == "[]"
      and dec("candidate_changed_cells", {B5C: "244=0;1=0000/8000/100/0;dx=0000B"}) == "['export_mode', 'power1', 'power3']"
      and dec("candidate_changed_cells", {B5C: "244=2;1=0000/8000/100/0;dx=00180"}) == "['soc1', 'soc2']"
      and dec("candidate_changed_cells", {B5C: "244=2;1=0000/8000/100/0;dx=02000"}) == "['source1']"
      and dec("candidate_changed_cells", {B5C: "v=NONE"}) == "[]", dec("candidate_changed_cells", {B5C: "244=0;1=0000/8000/100/0;dx=0000B"}))
# the dashboard may only RENDER these attributes: no decode tables and no mask arithmetic in the Review panel (pinned in [24])
# next generation wording: display only, exact where the published evidence makes it exact, neutral otherwise (never fabricated)
def ng(P, g="-", hw="-", w="OK"):
    return render(ATTR["next_generation_text"], {B1: P, B2: f"g={g};id=-;at=-;ld=OK;df=-;w={w};hw={hw};op=-;why=-;werr=-;us=-"})
check("next generation: NOT_CAPTURED -> `Will save generation 1`", ng("NOT_CAPTURED") == "Will save generation 1", ng("NOT_CAPTURED"))
check("next generation: VALID g=7 hw=7 witness OK -> generation 8; INVALIDATED g=8 hw=8 -> 9; hw above g -> max + 1",
      ng("VALID", "7", "7") == "Will save generation 8" and ng("INVALIDATED", "8", "8") == "Will save generation 9"
      and ng("VALID", "7", "9") == "Will save generation 10", f"{ng('VALID', '7', '7')} / {ng('INVALIDATED', '8', '8')}")
neutral = [ng("VALID", "7", "7", "LAG"), ng("VALID", "7", "-", "MISS"), ng("VALID", "7", "7", "CORR"), ng("PROFILE_STALE", "7", "7"),
           ng("PROFILE_LOST"), ng("CORRUPT"), ng("CORRUPT_DOMAIN", "7", "7"), ng("UNREADABLE"), ng("SAVE_UNCONFIRMED", "7", "7"),
           ng("VALID", "-", "7"), ng("VALID", "7", "-"), ng("VALID", "4294967295", "4294967295"), ng("unknown"), ng("unavailable")]
check("next generation: every state where the number is not derivable (lagging / missing / corrupt witness, STALE, LOST, CORRUPT, UNREADABLE, "
      "SAVE_UNCONFIRMED, unreadable or exhausted numbers, no data) says exactly `Will save a new generation`",
      all(x == "Will save a new generation" for x in neutral), str(neutral))
check("next generation: the display text is never part of any script or gate (no wrapper, helper or firmware path reads next_generation)",
      "next_generation" not in code_text(ACTIONS_PKG))

# ===========================================================================
print("")
print("[9] Actions package: exactly the operator scripts, with the locked shape")
scripts = actions_doc["script"]
check("actions package top-level key is script only", list(actions_doc) == ["script"])
check("actions package defines exactly save / replace_corrupt / invalidate / reset_high_water",
      sorted(scripts) == sorted(["ecco_fallback_profile_save", "ecco_fallback_profile_replace_corrupt",
                                 "ecco_fallback_profile_invalidate", "ecco_fallback_reset_high_water"]), str(sorted(scripts)))
check("no RESTORE / ACKNOWLEDGE wrapper yet",
      not any(("restore" in s or "acknowledge" in s) for s in scripts))
EXEC_ACTION = "esphome.ecco_clock_dongle_" + EXECUTE
for sid in ["ecco_fallback_profile_save", "ecco_fallback_profile_replace_corrupt", "ecco_fallback_profile_invalidate"]:
    s = scripts[sid]
    seq = s["sequence"]
    check(f"{sid}: mode single, max_exceeded silent, no fields",
          s.get("mode") == "single" and s.get("max_exceeded") == "silent" and "fields" not in s)
    check(f"{sid}: sequence is exactly variables -> {EXEC_ACTION} -> delay 3 s",
          len(seq) == 3 and list(seq[0]) == ["variables"] and seq[1].get("action") == EXEC_ACTION
          and seq[2] == {"delay": {"seconds": 3}}, str(seq))
    check(f"{sid}: data keys are exactly action / target_id / confirmation (never 'id')",
          sorted(seq[1]["data"]) == ["action", "confirmation", "target_id"])

# ---- token / confirmation construction, rendered with real values
def run_script(sid: str, values: dict[str, str]) -> dict[str, str]:
    seq = scripts[sid]["sequence"]
    ctx = {"states": _States(values)}
    vars_: dict[str, str] = {}
    for name, t in seq[0]["variables"].items():
        vars_[name] = env.from_string(t).render(**ctx, **vars_).strip()
    return {k: (env.from_string(v).render(**ctx, **vars_).strip() if isinstance(v, str) else v)
            for k, v in seq[1]["data"].items()}


for rid in ["5F3A9C21B04E7D18", "1234567890123456", "0000000000000001"]:
    d = run_script("ecco_fallback_profile_save", {B4: rid})
    check(f"SAVE {rid}: action literal, target_id = review id, confirmation = 'SAVE <id>'",
          d == {"action": "SAVE", "target_id": rid, "confirmation": f"SAVE {rid}"}, str(d))
    d = run_script("ecco_fallback_profile_replace_corrupt", {B4: rid})
    check(f"REPLACE CORRUPT {rid}: SAVE token, phrase carries REPLACE CORRUPT",
          d == {"action": "SAVE", "target_id": rid, "confirmation": f"SAVE {rid} REPLACE CORRUPT"}, str(d))
    phrase = re.compile(r"^(SAVE|INVALIDATE) [0-9A-F]{16}( REPLACE CORRUPT)?$")
    check(f"{rid}: both save phrases satisfy the firmware phrase grammar",
          bool(phrase.match(f"SAVE {rid}")) and bool(phrase.match(f"SAVE {rid} REPLACE CORRUPT")))
    b2 = f"g=7;id={rid};at=1790000000;ld=OK;df=-;w=OK;hw=7;op=SAVE;why=-;werr=-;us=-"
    d = run_script("ecco_fallback_profile_invalidate", {B2: b2})
    check(f"INVALIDATE {rid}: full 16-hex binding from B2 id, confirmation = 'INVALIDATE <binding>'",
          d == {"action": "INVALIDATE", "target_id": rid, "confirmation": f"INVALIDATE {rid}"}, str(d))
d = run_script("ecco_fallback_profile_invalidate", {B2: "g=-;id=-;at=-;ld=ABS;df=-;w=ABS;hw=-;op=-;why=-;werr=-;us=-"})
check("INVALIDATE with no profile sends '-' (the firmware refuses it)", d["target_id"] == "-")
for sid in ["ecco_fallback_profile_save", "ecco_fallback_profile_replace_corrupt"]:
    data = scripts[sid]["sequence"][1]["data"]
    check(f"{sid}: target_id and confirmation use the same variable, | string on the id",
          data["target_id"] == "{{ rid | string }}" and "{{ rid }}" in data["confirmation"])
check("invalidate: target_id and confirmation use the same variable",
      scripts["ecco_fallback_profile_invalidate"]["sequence"][1]["data"]["target_id"] == "{{ bid | string }}"
      and "{{ bid }}" in scripts["ecco_fallback_profile_invalidate"]["sequence"][1]["data"]["confirmation"])
check("SAVE reads exactly the Review ID entity; INVALIDATE reads exactly the Summary entity",
      B4 in str(scripts["ecco_fallback_profile_save"]["sequence"][0])
      and B2 in str(scripts["ecco_fallback_profile_invalidate"]["sequence"][0])
      and B2 not in str(scripts["ecco_fallback_profile_save"]["sequence"][0]))
reset = scripts["ecco_fallback_reset_high_water"]
check("reset script only fires the high-water event (no device call)",
      reset["sequence"] == [{"event": "ecco_fallback_reset_high_water"}] and reset.get("mode") == "single")
actions_code = code_text(ACTIONS_PKG)
check("no wrapper references the arm entity or turns anything on",
      ARM_ENTITY not in actions_code and "turn_on" not in actions_code and "toggle" not in actions_code
      and "switch." not in actions_code and "button." not in actions_code)
check("actions package has no automation / service / recorder block",
      all(t not in actions_code for t in ["automation:", "service:", "recorder:", "modbus_client"]))
check("actions package is the only file naming the execute action under home-assistant/",
      sorted(str(p.relative_to(ROOT)).replace("\\", "/") for p in HA.rglob("*.yaml")
             if EXECUTE in code_text(p)) == ["home-assistant/packages/ecco_fallback_profile_actions.yaml"])

# ===========================================================================
print("")
print("[10] No automation in home-assistant/ reaches the fallback operator surface")
guard_tokens = [
    "script.ecco_" + "fallback_profile_",
    "script.ecco_" + "fallback_reset_high_water",
    "script.ecco_" + "failback_",
    EXECUTE,
    ARM_ENTITY,
    FB + "_review_current_configuration",
]
yaml_files = sorted(p for p in HA.rglob("*.yaml") if p.is_file())
automation_blocks: list[tuple[str, str]] = []
for p in yaml_files:
    try:
        d = load(p)
    except Exception:  # noqa: BLE001
        continue
    if isinstance(d, dict) and "automation" in d:
        automation_blocks.append((str(p.relative_to(ROOT)), yaml.safe_dump(d["automation"])))
    elif isinstance(d, list):
        automation_blocks.append((str(p.relative_to(ROOT)), yaml.safe_dump(d)))
check("automation blocks were found to scan (heartbeat package at least)", len(automation_blocks) >= 1)
for path, blob in automation_blocks:
    if "ecco_supervision_heartbeat" in path or "automation" in path:
        for tok in guard_tokens:
            check(f"{path}: automation does not reference {tok!r}", tok not in blob)
# scripts other than the operator wrappers never call them either
for p in yaml_files:
    if p == ACTIONS_PKG:
        continue
    t = code_text(p)
    for tok in guard_tokens[:5]:
        # the status package only READS the arm / defines no script; the other packages must not name these
        if p != STATUS_PKG and p.parent.name != "dashboards":
            check(f"{p.relative_to(ROOT).as_posix()}: no reference to {tok!r}", tok not in t)
# the status package may READ the arm switch but never invoke a service on it
check("status package reads the arm switch state only",
      ARM in STATUS_PKG.read_text(encoding="utf-8") and "turn_on" not in status_code_text)
# any non-dashboard yaml naming the arm entity must not carry a switch service
for p in yaml_files:
    if p.parent.name == "dashboards":
        continue
    t = code_text(p)
    if ARM_ENTITY in t:
        check(f"{p.relative_to(ROOT).as_posix()}: arm entity named without turn_on / toggle / homeassistant.*",
              not re.search(r"turn_on|toggle|homeassistant\.turn", t))

# ===========================================================================
print("")
print("[11] System Health: new sensors, registry consistency, reason codes")
registry = yaml.safe_load(REASON_CODES.read_text(encoding="utf-8"))["reason_codes"]
rc_by = {r["code"]: r for r in registry}
checks_reg = yaml.safe_load(CHECKS.read_text(encoding="utf-8"))["checks"]
ck_by = {c["id"]: c for c in checks_reg}

NEW_CODES = {
    "SUPERVISION_STARTING": ("supervision", "DEGRADED"), "SUPERVISION_NOT_STABLE": ("supervision", "DEGRADED"),
    "SUPERVISION_SUSPECT": ("supervision", "WARNING"), "SUPERVISION_LOST": ("supervision", "WARNING"),
    "SUPERVISION_UNAVAILABLE": ("supervision", "UNKNOWN"),
    "FALLBACK_STATUS_UNAVAILABLE": ("fallback", "UNKNOWN"), "FALLBACK_LIVE_UNKNOWN": ("fallback", "UNKNOWN"),
    "FALLBACK_NOT_CAPTURED": ("fallback", "DEGRADED"), "FALLBACK_INVALIDATED": ("fallback", "DEGRADED"),
    "FALLBACK_DRIFTED": ("fallback", "DEGRADED"), "FALLBACK_CONTEXT_CHANGED": ("fallback", "WARNING"),
    "FALLBACK_EXPORT_ENABLED": ("fallback", "WARNING"), "FALLBACK_UNUSABLE": ("fallback", "WARNING"),
    "FALLBACK_SAVE_UNCONFIRMED": ("fallback", "WARNING"), "FALLBACK_REGRESSED": ("fallback", "WARNING"),
    "FALLBACK_LIVE_OUT_OF_DOMAIN": ("fallback", "WARNING"), "FALLBACK_BLOCKED_BY_LEASE": ("fallback", "WARNING"),
    "FAILBACK_SHADOW_EPISODE": ("fallback", "WARNING"),   # FB-C3
}
check("exactly the 17 FB-B3 reason codes plus the FB-C3 FAILBACK_SHADOW_EPISODE are registered for supervision/fallback",
      {c for c, r in rc_by.items() if r["subsystem"] in ("supervision", "fallback")} == set(NEW_CODES))
for code, (sub, sev) in NEW_CODES.items():
    r = rc_by.get(code, {})
    check(f"{code}: subsystem {sub}, severity {sev}, never gates manual control or forecast",
          r.get("subsystem") == sub and r.get("severity") == sev and r.get("blocks_manual_control") is False
          and r.get("affects_forecast") is False)
check("no reason code contains the banned FB substrings",
      not any(("FALLBACK" + "_PROFILE") in c or ("FAILBACK" + "_STATE") in c for c in rc_by))
check("FB-C3: FAILBACK_SHADOW_EPISODE is the ONLY FAILBACK_ code registered (FB-E/F codes stay reserved; FALLBACK_SHADOW_BLOCKED never exists)",
      sorted(c for c in rc_by if c.startswith("FAILBACK_")) == ["FAILBACK_SHADOW_EPISODE"] and "FALLBACK_SHADOW_BLOCKED" not in rc_by)
new_checks = {i: c for i, c in ck_by.items() if c["subsystem"] in ("supervision", "fallback")}
check("one check per new reason code, no more",
      sorted(o["reason_code"] for c in new_checks.values() for o in c["outcomes"]) == sorted(NEW_CODES)
      and len(new_checks) == len(NEW_CODES))
for cid, c in new_checks.items():
    check(f"{cid}: single outcome, severity subsystem matches its reason code",
          len(c["outcomes"]) == 1 and rc_by[c["outcomes"][0]["reason_code"]]["subsystem"] == c["subsystem"])
check("supervision checks use display words, not firmware enums",
      ck_by["supervision_startup"]["parameters"]["failure_values"] == ["Awaiting Heartbeat"]
      and ck_by["supervision_lost"]["parameters"]["failure_values"] == ["Lost"])

# engine tiers + validator subsystems
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
from health import system_health as engine  # noqa: E402
import validate_system_health_checks as validator  # noqa: E402

check("engine: supervision and fallback are STANDARD tier (not CRITICAL until FB-F)",
      engine.SUBSYSTEM_TIER.get("supervision") == engine.STANDARD and engine.SUBSYSTEM_TIER.get("fallback") == engine.STANDARD)
check("engine tier map and validator subsystem set agree",
      set(engine.SUBSYSTEM_TIER) == set(validator.VALID_SUBSYSTEMS))
check("sixteen subsystems", len(validator.VALID_SUBSYSTEMS) == 16)

# ---- health template matrices
SUP_H = HEALTH_ENT["ecco_health_supervision"]
for disp, want_state, want_codes in [
    ("Healthy", "HEALTHY", []), ("Recovering", "DEGRADED", ["SUPERVISION_NOT_STABLE"]),
    ("Awaiting Heartbeat", "DEGRADED", ["SUPERVISION_STARTING"]), ("Suspect", "WARNING", ["SUPERVISION_SUSPECT"]),
    ("Lost", "WARNING", ["SUPERVISION_LOST"]), ("Unknown", "UNKNOWN", ["SUPERVISION_UNAVAILABLE"]),
    ("unavailable", "UNKNOWN", ["SUPERVISION_UNAVAILABLE"]), ("Starting", "UNKNOWN", ["SUPERVISION_UNAVAILABLE"]),
]:
    v = {"sensor.ecco_supervision_status": disp}
    check(f"health supervision {disp!r} -> {want_state} {want_codes}",
          render(SUP_H["state"], v) == want_state
          and eval(render(tpl(SUP_H, "reason_codes"), v)) == want_codes)  # noqa: S307 - literal list from a test stub

FB_H = HEALTH_ENT["ecco_health_fallback"]
fb_expect = {
    "match": ("HEALTHY", []), "paused": ("HEALTHY", []),
    "not_captured": ("DEGRADED", ["FALLBACK_NOT_CAPTURED"]), "invalidated": ("DEGRADED", ["FALLBACK_INVALIDATED"]),
    "drift_values": ("DEGRADED", ["FALLBACK_DRIFTED"]),
    "drift_context": ("WARNING", ["FALLBACK_CONTEXT_CHANGED"]), "drift_export": ("WARNING", ["FALLBACK_EXPORT_ENABLED"]),
    "profile_unusable": ("WARNING", ["FALLBACK_UNUSABLE"]), "save_unconfirmed": ("WARNING", ["FALLBACK_SAVE_UNCONFIRMED"]),
    "profile_regressed": ("WARNING", ["FALLBACK_REGRESSED"]),
    "live_out_of_domain": ("WARNING", ["FALLBACK_LIVE_OUT_OF_DOMAIN"]),
    "lease_unreadable": ("WARNING", ["FALLBACK_BLOCKED_BY_LEASE"]), "lease_lockout": ("WARNING", ["FALLBACK_BLOCKED_BY_LEASE"]),
    "live_unknown": ("UNKNOWN", ["FALLBACK_LIVE_UNKNOWN"]),
    "not_reporting": ("UNKNOWN", ["FALLBACK_STATUS_UNAVAILABLE"]), "unexpected_state": ("UNKNOWN", ["FALLBACK_STATUS_UNAVAILABLE"]),
    "unknown": ("UNKNOWN", ["FALLBACK_STATUS_UNAVAILABLE"]), "unavailable": ("UNKNOWN", ["FALLBACK_STATUS_UNAVAILABLE"]),
    "shadow_episode": ("WARNING", ["FAILBACK_SHADOW_EPISODE"]),   # FB-C3
}
for code, (want_state, want_codes) in fb_expect.items():
    v = {CODE: code}
    check(f"health fallback {code} -> {want_state} {want_codes}",
          render(FB_H["state"], v) == want_state and eval(render(tpl(FB_H, "reason_codes"), v)) == want_codes)  # noqa: S307
produced_codes = {c for _, _, _, _, c in rows}
check("every status code the display layer can emit is handled by the health sensor",
      all(c in fb_expect or c == "lease_restoring" for c in produced_codes))
# lease_restoring: DEGRADED, WARNING after 10 minutes
for age, want in [(0, "DEGRADED"), (599, "DEGRADED"), (600, "WARNING"), (3600, "WARNING")]:
    v = {CODE: "lease_restoring"}
    got = render(FB_H["state"], v, last_changed={CODE: 10_000.0 - age}, now=10_000.0)
    check(f"health fallback lease_restoring held {age}s -> {want}", got == want, f"got {got!r}")
check("lease_restoring reason code is FALLBACK_BLOCKED_BY_LEASE",
      eval(render(tpl(FB_H, "reason_codes"), {CODE: "lease_restoring"})) == ["FALLBACK_BLOCKED_BY_LEASE"])  # noqa: S307
check("MATCH and PAUSED are HEALTHY, drift values DEGRADED, context WARNING (brief)",
      render(FB_H["state"], {CODE: "match"}) == "HEALTHY" and render(FB_H["state"], {CODE: "paused"}) == "HEALTHY"
      and render(FB_H["state"], {CODE: "drift_values"}) == "DEGRADED"
      and render(FB_H["state"], {CODE: "drift_context"}) == "WARNING")

# attribute conventions
for ent in (SUP_H, FB_H):
    attrs = ent["attributes"]
    check(f"{ent['unique_id']}: carries the standard health attributes",
          all(k in attrs for k in ["reason_codes", "represented_checks", "source_entity", "blocks_manual_control",
                                   "affects_forecast", "partial_implementation"])
          and attrs["blocks_manual_control"] is False and attrs["affects_forecast"] is False
          and attrs["partial_implementation"] is True)
    check(f"{ent['unique_id']}: list attributes are template strings, never literal YAML lists",
          not any(isinstance(v, list) for v in attrs.values()))
    rc = eval(render(attrs["represented_checks"], {}))  # noqa: S307
    check(f"{ent['unique_id']}: every represented check id exists in the registry",
          all(c in ck_by for c in rc), str([c for c in rc if c not in ck_by]))
rep_sup = set(eval(render(tpl(SUP_H, "represented_checks"), {})))  # noqa: S307
rep_fb = set(eval(render(tpl(FB_H, "represented_checks"), {})))  # noqa: S307
check("represented checks cover exactly the supervision / fallback registry checks",
      rep_sup == {c for c, v in new_checks.items() if v["subsystem"] == "supervision"}
      and rep_fb == {c for c, v in new_checks.items() if v["subsystem"] == "fallback"})
check("health fallback source entity is the status code; supervision source is the status sensor",
      FB_H["attributes"]["source_entity"] == CODE
      and SUP_H["attributes"]["source_entity"] == "sensor.ecco_supervision_status")
sup_trig = SUP_H["_triggers"]
check("supervision health sensor has start + state triggers", [t.get("trigger") for t in sup_trig] == ["homeassistant", "state"])
check("fallback health sensor has a one-minute time_pattern for lease_restoring escalation",
      any(t.get("trigger") == "time_pattern" and t.get("minutes") == "/1" for t in FB_H["_triggers"]))
check("no reason code literal in either health sensor is unregistered",
      all(c in rc_by for c in set(re.findall(r"'([A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+)'", HEALTH_PKG.read_text(encoding="utf-8")))))
check("health package still has no reserved final control-readiness gate",
      not re.search(r"unique_id:\s*ecco_manual_control_ready\s*$", HEALTH_PKG.read_text(encoding="utf-8"), re.M))

# ===========================================================================
print("")
print("[12] Owner reconciliations: FALLBACK_REGRESSED, target_id always a string, reset-helper isolation")
BANNED_UPPER = "FALLBACK" + "_PROFILE"
for pkg in (STATUS_PKG, ACTIONS_PKG, HEALTH_PKG):
    check(f"{pkg.name}: no {BANNED_UPPER} token anywhere (comments included)",
          BANNED_UPPER not in pkg.read_text(encoding="utf-8"))
check("the regressed reason code is exactly FALLBACK_REGRESSED, in the registry and the health sensor",
      "FALLBACK_REGRESSED" in rc_by and "'FALLBACK_REGRESSED'" in HEALTH_PKG.read_text(encoding="utf-8")
      and (BANNED_UPPER + "_REGRESSED") not in rc_by)
check("the display cause stays profile_regressed",
      "profile_regressed" in CODE_TPL and "'profile_regressed': 'Blocked'" in DISPLAY_TPL
      and eval(render(tpl(FB_H, "reason_codes"), {CODE: "profile_regressed"})) == ["FALLBACK_REGRESSED"])  # noqa: S307
check("the regressed subline keeps its exact wording",
      render(SUBLINE, {CODE: "profile_regressed"}) ==
      "The saved profile appears to have been lost or rolled back. Lease records may also be affected - check Free Power and Dump status.")
check("supervision Lost is WARNING everywhere (sensor, reason code, check evidence), never FAILED",
      render(SUP_H["state"], {"sensor.ecco_supervision_status": "Lost"}) == "WARNING"
      and rc_by["SUPERVISION_LOST"]["severity"] == "WARNING" and "'FAILED'" not in HEALTH_PKG.read_text(encoding="utf-8").split("ECCO Health Supervision")[1].split("ECCO Health Fallback")[0])

# ---- target_id is always a string: every wrapper forces `| string`, the confirmation uses the same string
ALL_DIGIT = "1234567890123456"
check("the all-digit test id is 16 characters", len(ALL_DIGIT) == 16 and ALL_DIGIT.isdigit())
for sid, src in [("ecco_fallback_profile_save", "rid"), ("ecco_fallback_profile_replace_corrupt", "rid"),
                 ("ecco_fallback_profile_invalidate", "bid")]:
    seq = scripts[sid]["sequence"]
    var_tpl = seq[0]["variables"][src]
    data = seq[1]["data"]
    check(f"{sid}: the id variable is forced through | string", "| string" in var_tpl)
    check(f"{sid}: target_id is exactly the string-forced variable, and the confirmation embeds the same variable",
          data["target_id"] == "{{ " + src + " | string }}" and ("{{ " + src + " }}") in data["confirmation"])
    check(f"{sid}: target_id is a plain template string (not a bare number or a field)",
          isinstance(data["target_id"], str) and data["target_id"].startswith("{{") and "fields" not in scripts[sid])
d = run_script("ecco_fallback_profile_save", {B4: ALL_DIGIT})
check("SAVE all-digit id: target_id is the exact 16-character str, not coerced",
      d["target_id"] == ALL_DIGIT and isinstance(d["target_id"], str) and len(d["target_id"]) == 16, repr(d))
check("SAVE all-digit id: confirmation is exactly 'SAVE 1234567890123456'",
      d["confirmation"] == "SAVE " + ALL_DIGIT and d["action"] == "SAVE", repr(d))
d = run_script("ecco_fallback_profile_replace_corrupt", {B4: ALL_DIGIT})
check("REPLACE CORRUPT all-digit id: str target_id and 'SAVE <id> REPLACE CORRUPT' confirmation",
      d["target_id"] == ALL_DIGIT and isinstance(d["target_id"], str)
      and d["confirmation"] == "SAVE " + ALL_DIGIT + " REPLACE CORRUPT", repr(d))
d = run_script("ecco_fallback_profile_invalidate",
               {B2: f"g=7;id={ALL_DIGIT};at=1790000000;ld=OK;df=-;w=OK;hw=7;op=SAVE;why=-;werr=-;us=-"})
check("INVALIDATE all-digit binding: str target_id and 'INVALIDATE <binding>' confirmation",
      d["target_id"] == ALL_DIGIT and isinstance(d["target_id"], str)
      and d["confirmation"] == "INVALIDATE " + ALL_DIGIT and d["action"] == "INVALIDATE", repr(d))
check("an all-digit id survives the variables -> data render with no numeric normalisation (leading zeros kept)",
      run_script("ecco_fallback_profile_save", {B4: "0000000000000001"})["target_id"] == "0000000000000001")

# ---- reset helper: no device call, event consumed only by the high-water sensor, detection only
ev_name = "ecco_fallback_reset_high_water"
reset_seq = scripts[ev_name]["sequence"]
check("reset helper has no ESPHome / device call (its only step is the event)",
      reset_seq == [{"event": ev_name}] and "esphome" not in str(reset_seq) and "action" not in str(reset_seq).replace("event", ""))
consumers: list[str] = []
firers: list[str] = []
for p in yaml_files:
    doc = load(p)
    blob = yaml.safe_dump(doc)
    if ev_name not in blob:
        continue
    rel = p.relative_to(ROOT).as_posix()
    for block in (doc.get("template", []) if isinstance(doc, dict) else []):
        for trg in block.get("triggers", []) or []:
            if trg.get("event_type") == ev_name:
                consumers.append(rel + ":" + ",".join(e["unique_id"] for e in block.get("sensor", [])))
    if isinstance(doc, dict) and any(ev_name in str(s.get("sequence", "")) for s in (doc.get("script") or {}).values()):
        firers.append(rel)
check("the reset event is consumed only by the generation-high-water sensor",
      consumers == ["home-assistant/packages/ecco_fallback_status.yaml:ecco_fallback_generation_high_water"], str(consumers))
check("the reset event is fired only by the reset helper script", firers == ["home-assistant/packages/ecco_fallback_profile_actions.yaml"], str(firers))
check("the event name appears nowhere else in home-assistant/ (no automation trigger); the dashboard may only name the script id",
      sorted(p.relative_to(ROOT).as_posix() for p in yaml_files if ev_name in p.read_text(encoding="utf-8") and p.parent.name != "dashboards") ==
      ["home-assistant/packages/ecco_fallback_profile_actions.yaml", "home-assistant/packages/ecco_fallback_status.yaml"]
      and all(re.search(r"(?<!script\.)" + ev_name, p.read_text(encoding="utf-8")) is None
              for p in yaml_files if p.parent.name == "dashboards"))
hw_users = sorted(p.relative_to(ROOT).as_posix() for p in yaml_files
                  if "ecco_fallback_generation_high_water" in code_text(p))
check("the high-water sensor is read only by display templates (status package, dashboard warning/technical panel), never by a script, automation, gate or health sensor",
      hw_users == ["home-assistant/dashboards/ecco_pro.yaml", "home-assistant/packages/ecco_fallback_status.yaml"], str(hw_users))
check("no script or action wrapper reads the high-water sensor (detection only; never gates the firmware action)",
      all("high_water" not in str(scripts[s]["sequence"][1:]) for s in scripts if s != ev_name)
      and all("high_water" not in str(scripts[s]["sequence"][0]) for s in scripts if s != ev_name))

# ===========================================================================
# SLICE C: dashboard / manifest / InfluxDB / release metadata (FB-B3)
# ===========================================================================
import ast
import hashlib

sys.path.insert(0, str(ROOT / "registry" / "tests"))
import _pub0_scope as _pub0  # noqa: E402  (PUB0: the sha256 pins below hash the private text; the identity outside the public export)
import _lic0_scope as _lic0  # noqa: E402  (LIC0: the declared v0.9.0 licence alignment of the Energy Actions card)
import _pex  # noqa: E402  (PEX0: the historical pins below read their file AS OF pub0; live safety invariants read the live file)
from datetime import datetime, timezone

DASH = HA / "dashboards" / "ecco_pro.yaml"
MANIFEST = ROOT / "deployment" / "ha-manifest.yaml"
VERSION = ROOT / "VERSION.yaml"
INF12 = ROOT / "influxdb" / "ecco_influxdb_options_v1_2.yaml"
INF13 = ROOT / "influxdb" / "ecco_influxdb_options_v1_3.yaml"
FIRMWARE = ROOT / "firmware" / "ecco_clock_dongle_stage3_4_free_power.yaml"


def lf(path: Path) -> str:
    return path.read_bytes().decode("utf-8").replace("\r\n", "\n")


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


dash_text = lf(DASH)
dash = yaml.load(dash_text, Loader=TaggedSafeLoader)
views = dash["views"]
titles = [v["title"] for v in views]


def walk(node):
    yield node
    if isinstance(node, dict):
        for v in node.values():
            yield from walk(v)
    elif isinstance(node, list):
        for v in node:
            yield from walk(v)


def view_by_path(path: str) -> dict:
    return next(v for v in views if v.get("path") == path)


safety = view_by_path("ecco-safety") if any(v.get("path") == "ecco-safety" for v in views) else {}
manual = view_by_path("ecco-manual-controls")
overview = view_by_path("ecco-overview")


def view_text(title: str) -> str:
    start = dash_text.index(f"  - title: {title}\n")
    nxt = [m.start() for m in re.finditer(r"^  - title: ", dash_text, re.M) if m.start() > start]
    return dash_text[start:(nxt[0] if nxt else len(dash_text))]


print("")
print("[13] Dashboard: Safety view placement and shape")
check("the Safety view exists exactly once (by title and by path)",
      titles.count("Safety") == 1 and sum(1 for v in views if v.get("path") == "ecco-safety") == 1, str(titles))
check("path is ecco-safety, icon mdi:shield-home-outline, type sections",
      safety.get("path") == "ecco-safety" and safety.get("icon") == "mdi:shield-home-outline" and safety.get("type") == "sections")
# PEX0 (O4): the two view-list pins below are FB-B3's pub0-era layout, so they read the dashboard AS OF pub0; the live adjacency
# Fallback / Recovery -> Safety -> Manual Controls they carried stays a live check (the third check).
_titles0 = [v["title"] for v in yaml.load(_pex.as_of_pub0("home-assistant/dashboards/ecco_pro.yaml", dash_text), Loader=TaggedSafeLoader)["views"]]   # PEX0: as of pub0
check("the Safety view sits immediately before Manual Controls (after Fallback / Recovery)",
      _titles0[-2:] == ["Safety", "Manual Controls"] and _titles0[-3] == "Fallback / Recovery", str(_titles0))
check("the original views keep their relative order",
      [t for t in _titles0 if t != "Safety"] == ["Overview", "Intelligence", "Tariffs", "Control", "Recommended", "System",
                                                  "Inverter / Advanced", "Fallback / Recovery", "Manual Controls"])
check("live: Fallback / Recovery, Safety and Manual Controls are consecutive views in this order (PEX0: the live part of the FB-B3 placement)",
      "Fallback / Recovery" in titles and titles[titles.index("Fallback / Recovery"):titles.index("Fallback / Recovery") + 3]
      == ["Fallback / Recovery", "Safety", "Manual Controls"], str(titles))
check("the Safety view has the same view keys as the other sections views",
      set(safety) == {"title", "path", "icon", "type", "max_columns", "dense_section_placement", "sections"}, str(sorted(safety)))
check("the existing frontend card and Fallback / Recovery view are still present once",
      dash_text.count("type: custom:ecco-fallback-recovery-card") == 1)

# ---------------------------------------------------------------------------
print("")
print("[14] Dashboard: Overview hero chips, hardAttention, compact System Health")
hero_js = next(c["custom_fields"]["body"] for n in walk(overview) if isinstance(n, dict) and n.get("name") == "ECCO Pro"
               and isinstance(n.get("custom_fields"), dict) for c in [n])
check("hero reads sensor.ecco_supervision_status and sensor.ecco_fallback_status",
      "get('sensor.ecco_supervision_status')" in hero_js and "get('sensor.ecco_fallback_status')" in hero_js)
required_line = next(l for l in hero_js.splitlines() if l.strip().startswith("const required ="))
check("neither new status is part of the `required` (STATUS PARTIAL) inputs",
      "sup" not in re.findall(r"\b\w+\b", required_line) and "fb" not in re.findall(r"\b\w+\b", required_line))
hard = hero_js[hero_js.index("const hardAttention"):hero_js.index("const busy")]
check("hardAttention gains supervision == Lost only (no fallback state)", "sup === 'Lost'" in hard and "fb" not in re.findall(r"\b\w+\b", hard))
check("hero has a SUPERVISION chip and a FALLBACK chip after RECOVERY",
      hero_js.index("pill('RECOVERY'") < hero_js.index("pill('SUPERVISION', supChip[0], supChip[1])") < hero_js.index("pill('FALLBACK', fbChip[0], fbChip[1])"))
check("supervision chips use the FINAL vocabulary (Awaiting Heartbeat, not Starting)",
      all(w in hero_js for w in ["'Healthy'", "'Recovering'", "'Awaiting Heartbeat'", "'Suspect'", "'Lost'"])
      and "'Starting'" not in hero_js and "'AWAITING'" in hero_js)
# FB-C3: the Shadow Recovery word is real now (one chip-map entry, so the hero does not show an UNKNOWN chip during a shadow episode); Applying stays reserved.
check("fallback chips use only the FINAL display words (FB-C3 adds Shadow Recovery; the FB-E/F Applying word stays reserved)",
      all(w in hero_js for w in ["'Ready'", "'Drifted'", "'Not Captured'", "'Invalidated'", "'Blocked'"])
      and hero_js.count("Shadow Recovery") == 1 and "'Shadow Recovery': ['SHADOW', 'warn']" in hero_js and "Applying" not in hero_js)

health_card = next(n for n in walk(overview) if isinstance(n, dict) and n.get("name") == "System Health" and "custom_fields" in n)
health_js = health_card["custom_fields"]["health"]
check("compact System Health has Supervision and Fallback rows",
      "['Supervision', read('sensor.ecco_health_supervision')]" in health_js
      and "['Fallback', read('sensor.ecco_health_fallback')]" in health_js)
check("DEGRADED is a real rendered mapping (accepted by read() and given a tone)",
      "['HEALTHY', 'DEGRADED', 'WARNING', 'FAILED'].includes(s)" in health_js and "s === 'DEGRADED' ? '#66b3ff'" in health_js)
check("the five Task 007 rows are untouched",
      all(f"read('sensor.ecco_health_{k}')" in health_js for k in ["manual_write_system", "rtc", "free_power", "configuration", "inverter_telemetry"]))

# ---------------------------------------------------------------------------
print("")
print("[15] Dashboard: Overview Known-Good Profile tile (read-only, directly after Energy Actions)")
ov_cards = [c for sec in overview["sections"] for c in sec.get("cards", [])]
ea_i = next(i for i, c in enumerate(ov_cards) if c.get("type") == "custom:ecco-energy-actions-card")
tile = ov_cards[ea_i + 1]
check("the Known-Good Profile tile is the card directly after Energy Actions",
      tile.get("name") == "Known-Good Profile" and tile.get("entity") == "sensor.ecco_fallback_status")
check("the tile tap action is the existing safe more-info pattern; no write action",
      tile.get("tap_action") == {"action": "more-info"} and "perform_action" not in yaml.safe_dump(tile)
      and "call-service" not in yaml.safe_dump(tile) and "script." not in yaml.safe_dump(tile) and "button." not in yaml.safe_dump(tile))
check("the tile consumes sensor.ecco_fallback_status (word + subline) and the saved summary only",
      "sensor.ecco_fallback_status" in tile["custom_fields"]["body"] and "attributes?.subline" in tile["custom_fields"]["body"])

# ---------------------------------------------------------------------------
print("")
print("[16] Safety view: only current FINAL entities, no stale saved-copy sensors, no Review Age")
safety_text = view_text("Safety")
ENT_RE = re.compile(r"\b(?:sensor|binary_sensor|switch|button|input_boolean|script|input_number|select|number)\.[a-z0-9_]+")
used = set(ENT_RE.findall(safety_text))
B5 = f"sensor.{DEV}_ecco_fallback_profile_review_slots"
B6 = f"sensor.{DEV}_ecco_fallback_profile_review_context"
B9 = f"sensor.{DEV}_ecco_fallback_profile_last_action_result"
REVIEW_BTN = f"button.{DEV}_ecco_fallback_profile_review_current_configuration"
ALLOWED = {
    B1, B2, B3, B4, B5, B6, B7, B8, B9, B10, REVIEW_BTN, ARM,
    SUP_STATE, SUP_STABLE, f"binary_sensor.{DEV}_ecco_api_client_connected", f"binary_sensor.{DEV}_ntp_synced",
    f"sensor.{DEV}_ecco_supervision_heartbeat_age", f"sensor.{DEV}_ecco_supervision_last_gap",
    f"sensor.{DEV}_ecco_supervision_longest_gap", f"sensor.{DEV}_ecco_supervision_valid_heartbeat_count",
    f"sensor.{DEV}_ecco_supervision_invalid_heartbeat_count", f"sensor.{DEV}_ecco_supervision_last_invalid_heartbeat_reason",
    "sensor.ecco_supervision_status", "sensor.ecco_fallback_status", CODE, HW,
    "binary_sensor.ecco_fallback_save_available", "binary_sensor.ecco_fallback_replace_corrupt_available",
    "binary_sensor.ecco_fallback_invalidate_available", "input_boolean.ecco_safety_show_technical_detail",
    "script.ecco_fallback_profile_save", "script.ecco_fallback_profile_replace_corrupt",
    "script.ecco_fallback_profile_invalidate", "script.ecco_fallback_reset_high_water",
    # FB-C3: the shadow decoder, its banner flag and the existing Reset Reason sensor (cross-boot evidence), all read-only
    "sensor.ecco_shadow_check", "binary_sensor.ecco_shadow_episode_open", f"sensor.{DEV}_ecco_reset_reason",
}
# the "Now" values of drifted cells are built as 'sensor...timezone' ~ n ~ '_time|_power|_soc|_charge'
check("the Safety view references only entities of the current FINAL set",
      all(u in ALLOWED or u.startswith(f"sensor.{DEV}_ecco_timezone") for u in used), str(sorted(u for u in used if u not in ALLOWED and not u.startswith(f"sensor.{DEV}_ecco_timezone"))))
check("every B1-B8, B10 (Live Match) and the Review button are consumed by the Safety view",
      all(e in used for e in [B1, B2, B3, B4, B5, B6, B7, B8, B9, B10, REVIEW_BTN, ARM]))
check("no stale HA saved-view copy entity anywhere in the dashboard",
      "ecco_fallback_saved_slots" not in dash_text and "ecco_fallback_saved_context" not in dash_text)
for pth in (DASH, MANIFEST, INF13, STATUS_PKG, ACTIONS_PKG, HEALTH_PKG, ROOT / "VERSION.yaml"):
    check(f"{pth.relative_to(ROOT).as_posix()}: no Review Age entity is introduced",
          "review_age" not in pth.read_text(encoding="utf-8").lower() and "review age" not in pth.read_text(encoding="utf-8").lower())
fw_text = FIRMWARE.read_text(encoding="utf-8")
check("the merged firmware has no Review Age entity (the FINAL set dropped it)",
      "Review Age" not in fw_text and "review_age" not in fw_text)
safety_dump = yaml.safe_dump(safety)
check("no FB-E/F restore, acknowledge or shadow-evaluator control in the Safety view",
      not re.search(r"restore_known|ecco_fallback_profile_restore|acknowledge|failback_shadow|Review Restore|ecco_" r"failback", safety_dump, re.I))
check("the Safety view does not use the retired 'Starting' supervision word", "Starting" not in safety_text)

# ---------------------------------------------------------------------------
print("")
print("[17] Safety view: operator buttons, arm, reset helper")
actions_in_dash = [(n.get("perform_action"), n) for n in walk(dash) if isinstance(n, dict) and "perform_action" in n]
check("the only perform_action targets in the whole dashboard are the four operator scripts",
      sorted(a for a, _ in actions_in_dash) == sorted(["script.ecco_fallback_profile_save", "script.ecco_fallback_profile_replace_corrupt",
                                                       "script.ecco_fallback_profile_invalidate", "script.ecco_fallback_reset_high_water"]),
      str(sorted(a for a, _ in actions_in_dash)))
buttons = {n["name"]: n for n in walk(safety) if isinstance(n, dict) and n.get("type") == "button"}
want = {"Save Known-Good Profile": ("script.ecco_fallback_profile_save", "binary_sensor.ecco_fallback_save_available"),
        "Replace Damaged Profile": ("script.ecco_fallback_profile_replace_corrupt", "binary_sensor.ecco_fallback_replace_corrupt_available"),
        "Invalidate Profile": ("script.ecco_fallback_profile_invalidate", "binary_sensor.ecco_fallback_invalidate_available")}
for name, (script_id, avail) in want.items():
    b = buttons.get(name, {})
    check(f"'{name}' calls only {script_id}, is visible only while {avail} is on, and has a confirmation dialog",
          b.get("tap_action", {}).get("perform_action") == script_id and b.get("tap_action", {}).get("action") == "perform-action"
          and b.get("visibility") == [{"condition": "state", "entity": avail, "state": "on"}]
          and isinstance(b.get("tap_action", {}).get("confirmation", {}).get("text"), str)
          and len(b["tap_action"]["confirmation"]["text"]) > 40)
check("Save / Replace / Invalidate buttons are not hold/double-tap actions and name no other service",
      all(set(b.get("tap_action", {})) <= {"action", "perform_action", "confirmation"} and "hold_action" not in b and "double_tap_action" not in b
          for n, b in buttons.items()))
check("Save confirmation says the inverter is not changed; Replace names the raw-byte log and says it does not erase NVS",
      "The inverter is not changed" in buttons["Save Known-Good Profile"]["tap_action"]["confirmation"]["text"]
      and "raw bytes" in buttons["Replace Damaged Profile"]["tap_action"]["confirmation"]["text"]
      and "does not erase NVS" in buttons["Replace Damaged Profile"]["tap_action"]["confirmation"]["text"])
reset_b = next(b for n, b in buttons.items() if n.startswith("Reset detection history"))
check("the high-water reset button is operator-only, in technical detail only (visible only behind the helper toggle)",
      reset_b["visibility"] == [{"condition": "state", "entity": "input_boolean.ecco_safety_show_technical_detail", "state": "on"}]
      and reset_b["tap_action"]["perform_action"] == "script.ecco_fallback_reset_high_water")
check("the reset wording says it resets Home Assistant's detection history and does NOT change the dongle/inverter",
      "Home Assistant" in reset_b["name"] and "does NOT change the dongle or the inverter" in reset_b["tap_action"]["confirmation"]["text"]
      and "Operator use only" in reset_b["tap_action"]["confirmation"]["text"])
check("the reset script is referenced from nowhere but that one dashboard button",
      dash_text.count("script.ecco_fallback_reset_high_water") == 1)
# arm: only a human tap on an entities row (or a read in a template); never a service/action
arm_nodes = [n for n in walk(dash) if isinstance(n, dict) and n.get("entity") == ARM]
check("the arm switch is a plain `entities` row in the Safety view (a human toggle), nowhere used as a button action",
      any(n.get("name") == "Arm (turns off after 2 min)" for n in arm_nodes)
      and not any("tap_action" in n or "hold_action" in n or "perform_action" in n for n in arm_nodes))
check("no dashboard action or service targets the arm switch (only the card's entity list, the Safety row and template reads)",
      not any(isinstance(n, dict) and (str(n.get("perform_action", "")).startswith(("switch.", "homeassistant.")) or str(n.get("service", "")).startswith(("switch.", "homeassistant.")))
              for n in walk(dash))
      and not re.search(r"(switch|homeassistant)\.(turn_on|toggle|turn_off)", dash_text))
check("the Review button is an entity row only (no automatic press)", any(n.get("entity") == REVIEW_BTN for n in walk(safety) if isinstance(n, dict))
      and "button.press" not in dash_text)
# nothing outside the dashboard turns the arm on
arm_callers = []
for p in sorted(HA.rglob("*.yaml")):
    if p.parent.name == "dashboards":
        continue
    tx = code_text(p)
    if ARM_ENTITY in tx and re.search(r"turn_on|toggle|homeassistant\.turn", tx):
        arm_callers.append(p.name)
check("no HA package, automation or script anywhere turns the fallback arm on", arm_callers == [], str(arm_callers))
check("the Slice-B scripts still never reference the arm", ARM_ENTITY not in actions_code)

# ---------------------------------------------------------------------------
print("")
print("[18] Manual Controls banner is advisory, not a gate")
man_cards = [c for sec in manual["sections"] for c in sec.get("cards", [])]
banner = man_cards[1]
check("the FB-B3 banner is the first card after the Manual Controls heading",
      man_cards[0].get("type") == "heading" and banner.get("type") == "markdown" and "Advisory only" in banner["content"])
check("the banner is visible only for drift_values / drift_context / drift_export / live_out_of_domain",
      banner["visibility"] == [{"condition": "state", "entity": CODE,
                                "state": ["drift_values", "drift_context", "drift_export", "live_out_of_domain"]}])
check("the banner has no tap/hold action, no script and no service", not any(k in banner for k in ("tap_action", "hold_action", "entity"))
      and "script." not in banner["content"] and "perform" not in banner["content"])
check("the banner says the profile will NOT update itself and points at Safety -> Review Current Configuration -> Save",
      banner["content"].count("NOT update itself") == 4 and banner["content"].count("Safety tab → Review Current Configuration → Save") == 4)
mc_text = view_text("Manual Controls")
check("Manual Controls names no fallback script, arm switch or Review button (it only reads status sensors)",
      "script.ecco_fallback" not in mc_text and ARM_ENTITY not in mc_text and "review_current_configuration" not in mc_text and "perform_action" not in mc_text.split("# ================= 1. TOU")[0])
mc_nodes = [n for n in walk(manual) if isinstance(n, dict)]
check("Manual Controls adds no perform_action / script call for the fallback surface",
      not any("perform_action" in n and "fallback" in str(n["perform_action"]) for n in mc_nodes))
check("the pre-apply advisory is appended to the existing intro markdown and says it does not block Apply",
      "Apply is not blocked" in man_cards[2]["content"] and "outside what Fallback V1 can save or restore" in man_cards[2]["content"])

# ---------------------------------------------------------------------------
print("")
print("[19] Energy Actions card config and frontend unchanged")
ea_start = dash_text.index("          - type: custom:ecco-energy-actions-card\n")
ea_end = dash_text.index("          # ---- KNOWN-GOOD PROFILE (FB-B3; READ-ONLY tile) ----")
EA_BLOCK_SHA = "784044c3fc4e9bb13811a384e687a2604d05fed1fff5ad161ef0d4ea953d361d"
_dash_private = _pub0.private_view("home-assistant/dashboards/ecco_pro.yaml", _pex.as_of_pub0("home-assistant/dashboards/ecco_pro.yaml", dash_text))   # PUB0: the pin is the private block's; PEX0: as of pub0
_ea_private = _dash_private[_dash_private.index("          - type: custom:ecco-energy-actions-card\n"):
                            _dash_private.index("          # ---- KNOWN-GOOD PROFILE (FB-B3; READ-ONLY tile) ----")]
check("the Energy Actions card config block is byte-identical to the pre-FB-B3 dashboard (sha256 pin)",
      sha(_ea_private) == EA_BLOCK_SHA, sha(_ea_private))
# The file set is whatever Git TRACKS beneath the card directory (never a filesystem walk): untracked files, git-ignored files, node_modules and
# build / cache artifacts therefore cannot change the pin on any machine (a CI checkout, a developer worktree after `npm ci` or a test run).
import subprocess  # noqa: E402

FE_DIR = "frontend/ecco-energy-actions-card/"
_ls = subprocess.run(["git", "ls-files", "-z", "--", FE_DIR], cwd=str(ROOT), capture_output=True)
fe_tracked = sorted(f for f in _ls.stdout.decode("utf-8").split("\0") if f)
_other = subprocess.run(["git", "ls-files", "-z", "--others", "--ignored", "--exclude-standard", "--", FE_DIR], cwd=str(ROOT), capture_output=True)
_untracked = subprocess.run(["git", "ls-files", "-z", "--others", "--exclude-standard", "--", FE_DIR], cwd=str(ROOT), capture_output=True)
fe_not_tracked = {f for f in (_other.stdout.decode("utf-8") + "\0" + _untracked.stdout.decode("utf-8")).split("\0") if f}
check("the Energy Actions pin enumerates ONLY Git-tracked files (git ls-files succeeded, files found, every one inside the card directory)",
      _ls.returncode == 0 and len(fe_tracked) > 0 and all(f.startswith(FE_DIR) for f in fe_tracked), f"rc={_ls.returncode} files={len(fe_tracked)}")
check("no untracked or git-ignored file is part of the pin's file set (node_modules, build / cache artifacts are excluded by construction)",
      not (set(fe_tracked) & fe_not_tracked), str(sorted(set(fe_tracked) & fe_not_tracked)))
fe_hash = hashlib.sha256()
for rel in fe_tracked:
    fe_hash.update(rel.encode())                                   # repository-relative POSIX path
    _fe_lf = (ROOT / rel).read_bytes().replace(b"\r\n", b"\n")   # tracked content, LF
    _fe_lf = _pex.as_of_pub0(rel, _fe_lf.decode("utf-8")).encode("utf-8") if rel in _pex.FROZEN else _fe_lf   # PEX (esb1): a frozen card file (pub0 target or enrolled) AS OF pub0
    fe_hash.update(_lic0.pre_lic0_bytes(rel, _pub0.private_view_bytes(rel, _fe_lf)))   # tracked content, LF (PUB0: private text); LIC0: pre-lic0 bytes
FE_SHA = "57c9798206d8a1850047474e9bdf89401523b03de89a2562a0cc18d81ac17471"   # main @ 87e6151 == a clean GitHub checkout
check("the Energy Actions frontend folder is unchanged (sha256 pin over every Git-tracked file)", fe_hash.hexdigest() == FE_SHA,
      f"{fe_hash.hexdigest()} over {len(fe_tracked)} tracked files: {fe_tracked}")

# ---------------------------------------------------------------------------
print("")
print("[20] Deployment manifest")
man_text = lf(MANIFEST)
man = yaml.safe_load(man_text)
pk = man["home_assistant_packages"]
for src, dst in [("home-assistant/packages/ecco_fallback_status.yaml", "/config/packages/ecco_fallback_status.yaml"),
                 ("home-assistant/packages/ecco_fallback_profile_actions.yaml", "/config/packages/ecco_fallback_profile_actions.yaml")]:
    ents = [e for e in pk if e["source"] == src]
    check(f"{src} occurs exactly once in the package list with the right destination, method and restart flag",
          len(ents) == 1 and ents[0] == {"source": src, "destination": dst, "method": "ssh_file_copy", "restart_required": True}, str(ents))
    check(f"{src} is named only in its own package stanza (source + destination)", man_text.count(Path(src).name) == 2, str(man_text.count(Path(src).name)))
    check(f"{src} exists", (ROOT / src).is_file())
_man0 = yaml.safe_load(_pex.as_of_pub0("deployment/ha-manifest.yaml", man_text))   # PEX0: FB-B3's package count and release are pub0-era pins
check("the manifest has exactly two new package entries (11 packages in total)", len(_man0["home_assistant_packages"]) == 11,
      str(len(_man0["home_assistant_packages"])))
check("the existing fallback recovery frontend asset entry is kept",
      any("ecco-fallback-recovery-card" in a["source"] for a in man["frontend_assets"])
      and len(_man0["frontend_assets"]) == 2)   # PEX (acfg1): the asset count is a pub0-era pin (acfg1 adds a third asset)
inf = man["influxdb"]
check("the InfluxDB reference points at v1.3 (reference_only) and no longer at v1.2",
      {"source": "influxdb/ecco_influxdb_options_v1_3.yaml", "destination": "home_assistant_influx_export_configuration", "method": "reference_only"} in inf
      and "ecco_influxdb_options_v1_2" not in man_text)
check("the manifest carries the firmware-first dependency note",
      "Fallback packages require firmware with FB-B1/FB-B2/FB-B3 entities; deploy firmware first, then packages, then the dashboard." in man["notes"])
check("the unrelated ecco_tou_schedule manifest gap is left alone (still not listed)",
      "ecco_tou_schedule" not in man_text)
check("the manifest release string is updated", _man0["release"] == "2026-10-02-fbb3-dashboard")   # PEX0: as of pub0

# ---------------------------------------------------------------------------
print("")
print("[21] InfluxDB v1.3 / v1.2, VERSION.yaml")
V12_SHA = "a6fa5204d717bbb761824266c7afc3c0051b793d3a7bf551952cd01651d74fc9"
_inf12_private = _pub0.private_view("influxdb/ecco_influxdb_options_v1_2.yaml", lf(INF12))   # PUB0: the pin is the private file's
check("v1.2 is unchanged (sha256 pin of its normalised content)", sha(_inf12_private) == V12_SHA, sha(_inf12_private))
i12 = yaml.safe_load(lf(INF12))
i13 = yaml.safe_load(lf(INF13))
check("v1.3 parses and keeps every v1.2 key except the added exclude",
      {k: v for k, v in i13.items() if k != "exclude"} == i12)
check("v1.3 keeps the dongle globs, so the fallback / shadow / supervision evidence stays exported",
      all(g in i13["include"]["entity_globs"] for g in ["sensor.ecco_clock_dongle_*", "binary_sensor.ecco_clock_dongle_*",
                                                         "switch.ecco_clock_dongle_*", "sensor.ecco_*", "binary_sensor.ecco_*", "input_boolean.ecco_*"]))
check("v1.3 excludes exactly the supervision challenge and the Review ID (nothing else)",
      i13["exclude"] == {"entities": [f"sensor.{DEV}_ecco_supervision_challenge", f"sensor.{DEV}_ecco_fallback_profile_review_id"]}, str(i13.get("exclude")))
check("both excluded entities exist in the firmware (names derive to those ids)",
      'name: "ECCO Supervision Challenge"' in fw_text and 'name: "ECCO Fallback Profile Review ID"' in fw_text)
check("v1.3 does not enumerate the dongle sensors individually (only the two exclusions are named)",
      lf(INF13).count(f"ecco_clock_dongle_ecco_") == 2)
ver = yaml.safe_load(_pex.as_of_pub0("VERSION.yaml", lf(VERSION)))   # PEX0: the FB-B3 / FB-C3 version facts below are pub0-era pins
# FB-C3: dashboard 7.18.0 is STAGED (7.17.0 was the live-tested one at LP-B3; its record is kept in VERSION.yaml's comments, same convention as 7.16.0 -> 7.17.0).
check("VERSION.yaml: dashboard 7.18.0 (7.17.0 + FB-C3 shadow check) staged, NOT live-tested (7.17.0 was tested in HA at LP-B3, 2026-10-03); influx export config v1.3",
      ver["current"]["dashboard"]["version"] == "7.18.0" and ver["current"]["dashboard"]["tested_in_home_assistant"] is False
      and ver["current"]["influxdb"]["export_config"] == "influxdb/ecco_influxdb_options_v1_3.yaml"
      and (ROOT / ver["current"]["influxdb"]["export_config"]).is_file())
check("the dashboard header's first line is untouched and a v7.17.0 note follows", dash_text.startswith("# ECCO Pro Dashboard v7.16.0")
      and "# v7.17.0 (FB-B3, STAGED / NOT LIVE-PROVEN)" in dash_text.split("views:")[0])

# ---------------------------------------------------------------------------
print("")
print("[22] YAML parses, pure CRLF/LF files stay pure")
for pth in (DASH, MANIFEST, VERSION, INF12, INF13, STATUS_PKG, ACTIONS_PKG, HEALTH_PKG):
    raw = pth.read_bytes()
    crlf, nlf = raw.count(b"\r\n"), raw.count(b"\n")
    check(f"{pth.relative_to(ROOT).as_posix()} parses and has pure line endings",
          isinstance(yaml.load(raw.decode("utf-8"), Loader=TaggedSafeLoader), dict) and (crlf == nlf or crlf == 0), f"{crlf}/{nlf}")

# ---------------------------------------------------------------------------
# Rendered dashboard Jinja (plain jinja2 + HA stand-ins), driven by the Slice-B templates
# ---------------------------------------------------------------------------
denv = jinja2.Environment(undefined=jinja2.StrictUndefined)
denv.filters["timestamp_custom"] = lambda v, fmt="%Y-%m-%d": datetime.fromtimestamp(float(v), timezone.utc).strftime(fmt)


def to_attr(v: str):
    try:
        return ast.literal_eval(v)
    except Exception:  # noqa: BLE001
        return v


def world(raw: dict[str, str]) -> tuple[dict[str, str], dict[str, object]]:
    """Compute the Slice-B display layer from raw firmware values."""
    vals = {HW: "0", ARM: "off", **raw}
    attrs: dict[str, object] = {}
    vals["sensor.ecco_supervision_status"] = render(SUP, vals)
    attrs["sensor.ecco_supervision_status#subline"] = render(STATUS_ENT["ecco_supervision_status"]["attributes"]["subline"], vals)
    vals[CODE] = render(CODE_TPL, vals)
    for a in ("live_match", "obligations", "export_hazard"):
        attrs[f"{CODE}#{a}"] = render(STATUS_ENT["ecco_fallback_status_code"]["attributes"][a], vals)
    vals["sensor.ecco_fallback_status"] = render(DISPLAY_TPL, vals)
    for a, t in STATUS_ENT["ecco_fallback_status"]["attributes"].items():
        attrs[f"sensor.ecco_fallback_status#{a}"] = to_attr(render(t, vals))
    return vals, attrs


def drender(content: str, vals: dict[str, str], attrs: dict[str, object]) -> str:
    def _state_attr(e, a):
        return attrs.get(f"{e}#{a}")

    ctx = {"states": _States(vals), "state_attr": _state_attr,
           "is_state": lambda e, s: vals.get(e, "unknown") == s}
    return denv.from_string(content).render(**ctx)


def md_cards(view: dict) -> list[dict]:
    return [n for n in walk(view) if isinstance(n, dict) and n.get("type") == "markdown" and "content" in n]


GOOD_SLOTS = "v=SAVED;g=7;244=2;1=0000/8000/100/1;2=0530/500/20/0;3=1000/4000/0/1;4=1600/3000/50/0;5=2100/2000/100/0;6=2330/1000/30/1;dx=-;b=00112233"
GOOD_CTX = "v=SAVED;232=0011;243=1;248=0001;ring=OK;230=185;245=8000;247=0001;dc=-;di=-;b=00112233"
GOOD_B2 = "g=7;id=D852A4FA2DF7DBA3;at=1790000000;ld=OK;df=-;w=OK;hw=7;op=SAVE;why=-;werr=-;us=-"
IDLE_B3 = "st=IDLE;prior=-;exp=-;warn=-;obl=-;latch=-;sv=-"
CAND_B3 = "st=CANDIDATE_READY;prior=VALID;exp=100;warn=W1;obl=FP:CA,DP:CM,R4:CA,MT:CN,FS:CA,BUS:OK;latch=-;sv=OK"
CAND_B5 = "v=CAND;g=-;244=2;1=0000/8000/100/1;2=0530/300/20/0;3=1000/4000/0/1;4=1600/3000/50/0;5=2100/2000/100/0;6=2330/1000/30/1;dx=00004"
CAND_B6 = "v=CAND;232=0011;243=1;248=0001;ring=OK;230=185;245=8000;247=0001;dc=-;di=-"
BASE = {
    SUP_STATE: "SUPERVISED", SUP_STABLE: "on", B1: "VALID", B2: GOOD_B2, B3: IDLE_B3, B4: "-", B5: "v=NONE;g=-;244=-;1=-;2=-;3=-;4=-;5=-;6=-;dx=-",
    B6: "v=NONE;232=-;243=-;248=-;ring=-;230=-;245=-;247=-;dc=-;di=-", B7: GOOD_SLOTS, B8: GOOD_CTX, B10: lm(),
    B9: "SAVED - known-good profile generation 7 committed",
    f"binary_sensor.{DEV}_ntp_synced": "on", f"binary_sensor.{DEV}_ecco_api_client_connected": "on",
    f"sensor.{DEV}_ecco_supervision_longest_gap": "31.0 s", f"sensor.{DEV}_ecco_supervision_heartbeat_age": "12",
}
SAFETY_MD = md_cards(safety)

print("")
print("[23] Rendered Safety / banner / advisory templates (Slice-B display layer feeding the dashboard)")
scenarios = {
    "match": dict(BASE),
    "drift": {**BASE, B10: lm(m="DRIFT", dx="00006")},
    "candidate": {**BASE, B3: CAND_B3, B4: "5F3A9C21B04E7D18", B5: CAND_B5, B6: CAND_B6, ARM: "on", B10: lm(m="DRIFT", dx="00004")},
    "not_captured": {**BASE, B1: "NOT_CAPTURED", B2: "g=-;id=-;at=-;ld=ABS;df=-;w=ABS;hw=-;op=-;why=-;werr=-;us=-",
                     B7: "v=NONE;g=-;244=-;1=-;2=-;3=-;4=-;5=-;6=-;dx=-;b=-", B8: "v=NONE;232=-;243=-;248=-;ring=-;230=-;245=-;247=-;dc=-;di=-;b=-",
                     B10: lm(m="NO_PROFILE")},
    "regressed": {**BASE, HW: "9"},
    "lockout_eh": {**BASE, B10: lm(obl="FP:ON,DP:CR,R4:CR,BUS:OK", eh="1")},
    "unreadable": {**BASE, B10: lm(obl="DP:UR,FP:CR,R4:CR,BUS:OK", eh="U")},
    "no_live_entity": {k: v for k, v in BASE.items() if k != B10},
    "device_down": {SUP_STATE: "unavailable", SUP_STABLE: "unavailable", B1: "unavailable"},
}
rendered: dict[str, list[str]] = {}
for sname, raw in scenarios.items():
    vals, attrs = world(raw)
    outs = []
    ok = True
    for card in SAFETY_MD:
        try:
            outs.append(drender(card["content"], vals, attrs))
        except Exception as exc:  # noqa: BLE001
            ok = False
            check(f"Safety markdown renders in scenario {sname}", False, repr(exc)[:200])
            break
    rendered[sname] = outs
    if ok:
        check(f"all {len(SAFETY_MD)} Safety markdown cards render without a template error in scenario {sname}", True)

full = {k: "\n".join(v) for k, v in rendered.items()}
check("match: Known-Good panel says READY with saved line, slot rows and decoded context",
      "Known-Good Profile: READY" in full["match"] and "generation **7**" in full["match"] and "ID **D852A4FA**" in full["match"]
      and "00:00-05:30" in full["match"] and "| 1 | 00:00-05:30 | 8000 W | 100 % | Grid |" in full["match"]
      and "Export mode **Zero Export**" in full["match"] and "Energy mode **Load First**" in full["match"]
      and "Grid charging **on**" in full["match"] and "TOU schedule **on**" in full["match"])
check("match: slot 6 wraps to slot 1's start (23:30-00:00)", "| 6 | 23:30-00:00 |" in full["match"])
check("match: Supervision section says HEALTHY and no regression warning is rendered",
      "Home Assistant supervision: HEALTHY" in full["match"])
check("drift: drifted cells show 'Now' values from the live entities (sensor derivation, not dashboard decoding)",
      "◀ now" in full["drift"] and "Known-Good Profile: DRIFTED" in full["drift"])
check("candidate: Review panel header, id, countdown, saved-vs-candidate marker and warning text",
      "CANDIDATE READY" in full["candidate"] and "Review ID **5F3A9C21B04E7D18**" in full["candidate"] and "expires in **1:40**" in full["candidate"]
      and "◀ saved 500" in full["candidate"] and "Looks like a Free Power overlay - confirm this is your normal setup." in full["candidate"]
      and "Replaces: **VALID** (generation 7)" in full["candidate"])
check("candidate: Save-needs row reflects Review, Arm, Supervision stable, NTP",
      "✓ Review" in full["candidate"] and "✓ Arm" in full["candidate"] and "✓ Supervision stable" in full["candidate"] and "✓ NTP time" in full["candidate"])
check("idle: the Review panel says no review in progress", "No review in progress" in full["match"])
check("not captured: no profile line and the sentence from the display layer",
      "**No profile saved yet.**" in full["not_captured"] and "No known-good profile saved yet. Review your current configuration and save it." in full["not_captured"])
check("regressed: the generation high-water warning is rendered with both generations",
      "Saved profile may have been lost or rolled back" in full["regressed"] and "highest seen **9**" in full["regressed"])
check("lockout + eh=1: the Live match panel carries the export warning", "Export is currently ENABLED" in full["lockout_eh"])
check("unreadable + eh=U + Dump obligation: 'Export state unknown - check the inverter'", "Export state unknown - check the inverter." in full["unreadable"])
check("no Live Match entity (older firmware): panel degrades to Unknown, never Ready",
      "Known-Good Profile: UNKNOWN" in full["no_live_entity"] and "READY" not in full["no_live_entity"].split("Live match")[0])
check("device unreachable: renders Unknown words", "Known-Good Profile: UNKNOWN" in full["device_down"] and "supervision: UNKNOWN" in full["device_down"])
tech = next(c for c in SAFETY_MD if "### Technical detail" in c["content"])
rt = drender(tech["content"], *world({**BASE, B3: CAND_B3}))
check("technical panel shows raw B2-B10 strings, the review obligation vector and the high-water value",
      "Summary: `g=7;id=D852A4FA2DF7DBA3" in rt and "Live match: `m=MATCH" in rt and "Review obligations:** `FP:CA,DP:CM" in rt
      and "Generation high-water (Home Assistant detection only):" in rt and "Free Power: clear (live legs only) (`FP:CR`)" in rt)

banner_md = banner["content"]
for code, want_s in [("drift_values", "(2 settings differ)"), ("drift_context", "Slot times or context changed"),
                     ("drift_export", "Export mode is Allow Export"), ("live_out_of_domain", "outside what Fallback V1 can save or restore (PWRL2)")]:
    live = {"drift_values": lm(m="DRIFT", dx="00006"), "drift_context": lm(m="CONTEXT", cx="00001"), "drift_export": lm(m="EXPORT"),
            "live_out_of_domain": lm(m="OUT_OF_DOMAIN", ew="PWRL2,SOCH3+1")}[code]
    vals, attrs = world({**BASE, B10: live})
    out = drender(banner_md, vals, attrs)
    check(f"banner renders for {code} and directs the operator to Safety -> Review -> Save",
          vals[CODE] == code and want_s in out and "NOT update itself" in out and "Safety tab → Review Current Configuration → Save" in out and "Advisory only" in out, out[:160])

adv = man_cards[2]["content"]
stage = {**BASE, "input_number.ecco_manual_slot_1_power_staged": "8000", "input_number.ecco_manual_slot_2_power_staged": "300",
         "select.ecco_clock_dongle_manual_slot_3_charge_source": "Grid + Generator"}
for n in (3, 4, 5, 6):
    stage.setdefault(f"input_number.ecco_manual_slot_{n}_power_staged", "8000")
for n in (1, 2, 4, 5, 6):
    stage.setdefault(f"select.ecco_clock_dongle_manual_slot_{n}_charge_source", "Grid")
out = drender(adv, *world(stage))
check("staged advisory notes slot 2 (power below 500 W) and slot 3 (generator source), advisory only",
      "Note: staged Slot 2 (power 300 W is below 500 W) is outside what Fallback V1 can save or restore." in out
      and "Note: staged Slot 3 (charge source Grid + Generator) is outside what Fallback V1 can save or restore." in out
      and "Note: staged Slot 1" not in out and "Apply is not blocked" in out)
clean = {k: v for k, v in stage.items()}
clean["input_number.ecco_manual_slot_2_power_staged"] = "8000"
clean["select.ecco_clock_dongle_manual_slot_3_charge_source"] = "Grid"
check("no advisory when every staged slot is inside Fallback V1", "Note: staged" not in drender(adv, *world(clean)))

# ---------------------------------------------------------------------------
print("")
print("[24] Regex safety (the Energy Actions card regexes, parsed from its TS source) over every new string")
TS_DIR = ROOT / "frontend" / "ecco-energy-actions-card" / "src"
card_regexes: list[tuple[str, re.Pattern]] = []
for tsf in ("freePowerState.ts", "dumpState.ts", "recoveryPresentation.ts"):
    ts_src = (TS_DIR / tsf).read_text(encoding="utf-8")
    for m in re.finditer(r"^\s*(?:export\s+)?const\s+([A-Z0-9_]+)\s*=\s*\n?\s*/(.+)/([a-z]*);\s*$", ts_src, re.M):
        card_regexes.append((f"{tsf}:{m.group(1)}", re.compile(m.group(2), re.I if "i" in m.group(3) else 0)))
check("card regex literals were extracted from the TS source (the TS tests are not in CI)", len(card_regexes) >= 15 and any("RECOVERY REQUIRED" in rx.pattern for _, rx in card_regexes) and any(rx.pattern.startswith("^(RESTORING|STARTING") for _, rx in card_regexes), str(len(card_regexes)))


def text_atoms(blob: str) -> list[str]:
    """Split rendered markdown / JS-literal text into the lines and quoted strings a card regex could classify."""
    atoms = [ln.strip() for ln in blob.splitlines() if ln.strip()]
    atoms += re.findall(r"'([^']{2,80})'", blob) + re.findall(r'"([^"]{2,200})"', blob)
    return atoms


all_text = [("safety view source", safety_text), ("overview tile", yaml.safe_dump(tile)), ("manual banner+advisory", banner_md + "\n" + adv),
            ("hero/chip vocabulary", "\n".join(re.findall(r"const (?:supChips|fbChips) = .*", hero_js))),
            ("health rows", "\n".join(re.findall(r"\['(?:Supervision|Fallback)'.*", health_js)))]
all_text += [(f"rendered {k}", v) for k, v in full.items()]
hits = []
for label, blob in all_text:
    for atom in text_atoms(blob):
        for rname, rx in card_regexes:
            if rx.search(atom):
                hits.append((label, rname, atom[:80]))
check("no Safety / tile / banner / chip string (source or rendered) matches any Energy Actions card regex", not hits, str(hits[:5]))

# Slice-B display strings against the same regexes (a hit here is a Slice-B finding to REPORT, not to refactor)
b_strings: list[str] = ["Healthy", "Recovering", "Awaiting Heartbeat", "Suspect", "Lost", "Unknown", "Ready", "Drifted",
                        "Not Captured", "Invalidated", "Blocked", "AWAITING", "NOT SAVED"]
b_strings += list(display_expect)
for code in display_expect:
    vals, attrs = world({**BASE, CODE: code})
    vals[CODE] = code
    b_strings.append(render(SUBLINE, {**vals, B1: "VALID", B10: lm(m="PAUSED", obl="FP:AC,DP:CR,R4:CR,BUS:OK"), B2: GOOD_B2}))
b_strings += [r["meaning"] + " " + r["safe_diagnostic_step"] for r in registry if r["subsystem"] in ("supervision", "fallback")]
b_hits = [(s[:70], n) for s in b_strings for n, rx in card_regexes if rx.search(s)]
check("Slice-B words, sublines and health reason-code strings match no Energy Actions card regex", not b_hits, str(b_hits[:5]))


# ===========================================================================
print("")
print("[25] FB-B3 integration: the dashboard renders decoded strings; it never decodes a register word")
safety_text = view_text("Safety")
check("the Safety view contains no register-word decode table (no 244 / 243 enum names as lookup keys, no raw 0x%04X formatter, no source/mode label table)",
      not any(tok in safety_text for tok in ("'Essentials'", "'Battery First'", "'Load First'", "'Zero Export':", "raw 0x", "'Grid + Generator'",
                                              "' + General'", "' + Backup'", "' + Charge'", "base = [")))
check("the Safety view contains no hex-mask / bit arithmetic over firmware words (no int(0, 16), no `// (2 **`, no `% 2 == 1`)",
      not any(tok in safety_text for tok in ("int(0, 16)", "// (2 **", "% 2 == 1", "** 2")))
for attr in ("candidate_export_mode", "candidate_energy_mode", "candidate_grid_charging", "candidate_tou_schedule", "candidate_sources",
             "candidate_changed_cells", "next_generation_text"):
    check(f"the Review panel renders the HA attribute {attr} (exactly once)", safety_text.count(f"'{attr}'") == 1, str(safety_text.count(f"'{attr}'")))
check("the Review panel carries no fabricated generation number: only `Will create` is absent and the text comes from next_generation_text",
      "Will create generation" not in safety_text and not re.search(r"\b(?:ng|pg)=", safety_text))
check("the candidate decoders exist as HA attributes on sensor.ecco_fallback_status and use the saved-decoder naming convention (candidate_<what> next to saved_<what>)",
      all(f"candidate_{k}" in ATTR for k in ("export_mode", "energy_mode", "grid_charging", "tou_schedule", "sources", "changed_cells"))
      and all(f"saved_{k}" in ATTR for k in ("export_mode", "energy_mode", "grid_charging", "tou_schedule", "sources")))

print("")
if FAILURES:
    print(f"{len(FAILURES)} check(s) FAILED:")
    for name in FAILURES:
        print(f"  - {name}")
    sys.exit(1)
print("All FB-B3 HA status / actions / health checks PASSED.")
print("NOTE: this proves plain-Jinja behaviour against stub inputs only. It does not prove the")
print("templates on a live Home Assistant instance. Package files remain STAGED / NOT LIVE-PROVEN.")
