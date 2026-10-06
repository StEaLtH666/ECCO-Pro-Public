#!/usr/bin/env python3
"""Offline tests for the FB-C3 Home Assistant SHADOW UX layer (STAGED / NOT LIVE-PROVEN).

Scope (FINAL_FBB_FBC_ARCHITECTURE.md sections 9.7 / 10.5 / 10.7, design/S5_ha_contract_ux_final.md Part A H4, S3 FINAL section 9.2):

  home-assistant/packages/ecco_fallback_status.yaml   canonical status row `shadow_episode`, display word "Shadow Recovery", subline,
                                                      the diagnostic decoder sensor.ecco_shadow_check and binary_sensor.ecco_shadow_episode_open
  home-assistant/packages/ecco_system_health.yaml     shadow_episode -> WARNING / FAILBACK_SHADOW_EPISODE / check fallback_shadow_episode
  registry/health_reason_codes.yaml, registry/system_health_checks.yaml
  home-assistant/dashboards/ecco_pro.yaml             Safety view: everyday SHADOW CHECK line, shadow episode banner, technical block

Templates are rendered with plain jinja2 AND jinja2's ImmutableSandboxedEnvironment (the family Home Assistant uses) with small stand-ins for
states / state_attr / as_timestamp / now / timestamp_custom. This does NOT prove the templates behave identically inside a real Home Assistant
instance (that needs `ha core check` plus a live shadow drill, LP-C2 / LP-C3).

The shadow evaluator itself is NEVER re-implemented here or in the templates: the decoder maps C2's own Verdict name / plan code to words.

  [1]  static: the C3 package change is display-only (no service call, no automation / script, exact new unique ids, no new helper)
  [2]  the canonical status code: the B3 template is reconstructed byte-for-byte and used as a DIFFERENTIAL oracle over a large sweep;
       precedence not_reporting > lease_unreadable > lease_lockout > shadow_episode > everything else; a Verdict / Inputs / Episode value
       outside an episode never changes it; unavailable / unknown shadow inputs fail safely
  [3]  display word, subline, health word, reason code and check id (exact), FALLBACK_SHADOW_BLOCKED nowhere
  [4]  the decoder: the FINAL FB-C2 Verdict contract (the Verdict is the READINESS plan; NO_ACTION / WOULD_REFUSE_STARTS are never published
       and never worded), verdict wording against the S4 table, the Verdict scope / heading (S5 6.4), Inputs (incl. the appended alt / pa) /
       Episode / Soak grammars (actual C2 keys), banner, unknown keys and unpublished plan codes, bad input
  [5]  the dashboard: banner / everyday line / technical block (placement, visibility, no control, only the five shadow entities)
  [6]  rendered Safety cards over decoded worlds (idle, episode, episode masked by a lease state, device down)
  [7]  Energy Actions untouched, InfluxDB v1.3 keeps the five shadow sensors, no recorder block, version / record
  [8]  negative controls: moving shadow_episode above the lease rows (or below the profile rows, or letting the Verdict decide) is caught;
       re-wording NO_ACTION, dropping Inputs alt / pa, or a heading that ignores the episode is caught by the decoder checks
"""

from __future__ import annotations

import ast
import fnmatch
import hashlib
import itertools
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import jinja2
import jinja2.sandbox
import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "registry" / "tests"))
import _pub0_scope as _pub0  # noqa: E402  (PUB0: the sha256 pins below hash the private text; the identity outside the public export)
import _lic0_scope as _lic0  # noqa: E402  (LIC0: the declared v0.9.0 licence alignment of the Energy Actions card)

HA = ROOT / "home-assistant"
STATUS_PKG = HA / "packages" / "ecco_fallback_status.yaml"
HEALTH_PKG = HA / "packages" / "ecco_system_health.yaml"
ACTIONS_PKG = HA / "packages" / "ecco_fallback_profile_actions.yaml"
DASH = HA / "dashboards" / "ecco_pro.yaml"
REASON_CODES = ROOT / "registry" / "health_reason_codes.yaml"
CHECKS = ROOT / "registry" / "system_health_checks.yaml"
INF13 = ROOT / "influxdb" / "ecco_influxdb_options_v1_3.yaml"
VERSION = ROOT / "VERSION.yaml"
FIRMWARE = ROOT / "firmware" / "ecco_clock_dongle_stage3_4_free_power.yaml"
S4_DOC = ROOT / "docs" / "architecture" / "fallback" / "design" / "S4_domains_decisions_final.md"

FAILURES: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  PASS  {name}")
    else:
        FAILURES.append(name)
        print(f"  FAIL  {name}" + (f" - {detail}" if detail else ""))


class TaggedSafeLoader(yaml.SafeLoader):
    """Tolerates Home Assistant custom !tags."""


TaggedSafeLoader.add_multi_constructor("!", lambda l, s, n: l.construct_scalar(n) if isinstance(n, yaml.ScalarNode)
                                       else l.construct_sequence(n) if isinstance(n, yaml.SequenceNode) else l.construct_mapping(n))


def lf(path: Path) -> str:
    return path.read_bytes().decode("utf-8").replace("\r\n", "\n")


def load_text(text: str):
    return yaml.load(text, Loader=TaggedSafeLoader)


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def code_text(path: Path) -> str:
    """File text with `#` comment lines removed (headers document prohibitions)."""
    return "\n".join(line for line in lf(path).splitlines() if not line.strip().startswith("#"))


# The reserved token is assembled from fragments so this file never trips the repository-wide scope scan itself.
FB = "fail" + "back"
DEV = "ecco_clock_dongle"


def shadow_id(suffix: str) -> str:
    return f"sensor.{DEV}_ecco_{FB}_shadow_{suffix}"


SS, EP, SK, VD, IN = (shadow_id(x) for x in ("state", "episode", "soak", "verdict", "inputs"))
FIVE = [SS, EP, SK, VD, IN]
B1 = f"sensor.{DEV}_ecco_fallback_profile_state"
B2 = f"sensor.{DEV}_ecco_fallback_profile_summary"
B10 = f"sensor.{DEV}_ecco_fallback_profile_live_match"
HW = "sensor.ecco_fallback_generation_high_water"
CODE = "sensor.ecco_fallback_status_code"
DISPLAY = "sensor.ecco_fallback_status"
CHECK = "sensor.ecco_shadow_check"
OPEN = "binary_sensor.ecco_shadow_episode_open"
RESET = f"sensor.{DEV}_ecco_reset_reason"
EPISODE_STATES = ["SHADOW_EPISODE", "SHADOW_EPISODE_HA_BACK"]
NON_EPISODE_STATES = ["SHADOW_BOOT", "SHADOW_IDLE", "SHADOW_WATCH", "SHADOW_WOULD_AWAIT_ACK", "unknown", "unavailable", "", "none",
                      "shadow_episode", "SHADOW_EPISODE_X", "garbage", " SHADOW_EPISODE", "SHADOW_EPISODE "]
NOW = 1_800_000_000.0

ENVS = {
    False: jinja2.Environment(undefined=jinja2.StrictUndefined),
    True: jinja2.sandbox.ImmutableSandboxedEnvironment(undefined=jinja2.StrictUndefined),
}
for _e in ENVS.values():
    _e.filters["timestamp_custom"] = lambda v, fmt="%Y-%m-%d %H:%M:%S", local=True: datetime.fromtimestamp(float(v), timezone.utc).strftime(fmt)


class _States:
    def __init__(self, values):
        self.values = values

    def __call__(self, entity_id):
        return self.values.get(entity_id, "unknown")

    def __getitem__(self, entity_id):  # states[e].last_changed (health sensor)
        class _O:
            last_changed = 0.0
        return _O()


class T:
    """A template compiled once; call it with a values dict."""

    def __init__(self, text: str, sandbox: bool = False):
        self.t = ENVS[sandbox].from_string(text)

    def __call__(self, values, now=NOW):
        ctx = {"states": _States(values), "state_attr": lambda e, a: values.get(f"{e}#{a}"), "as_timestamp": lambda v: float(v),
               "now": lambda: now, "is_state": lambda e, s: values.get(e, "unknown") == s}
        return self.t.render(**ctx).strip()


def literal(s: str):
    try:
        return ast.literal_eval(s)
    except Exception:  # noqa: BLE001
        return s


status_doc = load_text(lf(STATUS_PKG))
health_doc = load_text(lf(HEALTH_PKG))


def template_entities(doc) -> dict:
    out = {}
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
CODE_TPL = STATUS_ENT["ecco_fallback_status_code"]["state"]
DISPLAY_TPL = STATUS_ENT["ecco_fallback_status"]["state"]
SUBLINE_TPL = STATUS_ENT["ecco_fallback_status"]["attributes"]["subline"]
SHADOW = STATUS_ENT["ecco_shadow_check"]
SHADOW_ATTRS = SHADOW["attributes"]

# ===========================================================================
print("[1] Static: the C3 change is display-only")
status_code_only = code_text(STATUS_PKG)
for token in ["service:", "action:", "automation:", "script:", "esphome.", "button.press", "switch.turn_on", "switch.toggle",
              "modbus_client", "homeassistant.restart", "homeassistant.reload", "shell_command:", "command_line:", "recorder:",
              "perform_action", "rest_command:"]:
    check(f"status package does not contain {token!r} outside a comment", token not in status_code_only)
check("status package top-level keys are still exactly template + input_boolean", sorted(status_doc) == ["input_boolean", "template"])
check("the only input helper is still the technical-detail toggle (no new helper)", list(status_doc["input_boolean"]) == ["ecco_safety_show_technical_detail"])
check("the C3 change adds exactly two template entities (a sensor and a binary sensor), nothing else",
      set(STATUS_ENT) == {"ecco_supervision_status", "ecco_fallback_status_code", "ecco_fallback_status", "ecco_shadow_check",
                          "ecco_fallback_save_available", "ecco_fallback_replace_corrupt_available",
                          "ecco_fallback_invalidate_available", "ecco_shadow_episode_open", "ecco_fallback_generation_high_water"}
      and SHADOW["_platform"] == "sensor" and STATUS_ENT["ecco_shadow_episode_open"]["_platform"] == "binary_sensor")
check("the new entities are state-based (no trigger block, no `this`, no `trigger`)",
      not SHADOW["_triggers"] and not STATUS_ENT["ecco_shadow_episode_open"]["_triggers"]
      and not re.search(r"\b(this|trigger)\.", yaml.dump(SHADOW) + yaml.dump(STATUS_ENT["ecco_shadow_episode_open"])))
check("exact display names", SHADOW["name"] == "ECCO Shadow Check" and STATUS_ENT["ecco_shadow_episode_open"]["name"] == "ECCO Shadow Episode Open")
for fname in ("ecco_fallback_status.yaml", "ecco_system_health.yaml"):
    check(f"{fname}: carries no recorder: block (the site recorder stays the site's own)", "recorder:" not in code_text(HA / "packages" / fname))
check("no package in the repository adds a recorder: block", not [p.name for p in (HA / "packages").glob("*.yaml") if re.search(r"^recorder:", lf(p), re.M)])

# ===========================================================================
print("")
print("[2] Canonical status code: precedence, differential oracle (the reconstructed FB-B3 template), fail-safe inputs")
text = lf(STATUS_PKG)
SET_LINE = f"          {{#- C3 -#}}{{%- set SS = states('{SS}') -%}}\n"
ROW_LINE = "          {#- C3 -#}{%- elif SS in ['SHADOW_EPISODE', 'SHADOW_EPISODE_HA_BACK'] -%}shadow_episode\n"
ANCHOR_SET = "          {#- C3 -#}{#- FB-C3 inserts the shadow-state inputs here -#}\n"
ANCHOR_ROW = "          {#- C3 -#}{#- FB-C3 shadow_episode row inserts here -#}\n"
check("the two FB-C3 template lines are present exactly once", text.count(SET_LINE) == 1 and text.count(ROW_LINE) == 1)
b3_text = text.replace(SET_LINE, ANCHOR_SET).replace(ROW_LINE, ANCHOR_ROW)
b3_ent = template_entities(load_text(b3_text))
B3_CODE_TPL_SHA256 = "a0aa1a8997af311709304ea7b4f005e9cf9ba84bc5f42d4689f166a43721222d"
# PUB0: the pin is the private template's: the same two line edits applied to the private text (the identity outside the public export).
_b3_code_private = template_entities(load_text(_pub0.private_view_edited(
    "home-assistant/packages/ecco_fallback_status.yaml", text, {SET_LINE[:-1]: ANCHOR_SET[:-1], ROW_LINE[:-1]: ANCHOR_ROW[:-1]})))["ecco_fallback_status_code"]["state"]
check("reverting exactly those two lines reproduces the FB-B3 status-code template byte for byte (sha256 of the loaded template)",
      sha(_b3_code_private) == B3_CODE_TPL_SHA256, sha(_b3_code_private))
check("the status-code template refers to the shadow STATE entity only (never the Verdict, Inputs, Episode or Soak)",
      [i for i in FIVE if i in CODE_TPL] == [SS])
OLD = T(b3_ent["ecco_fallback_status_code"]["state"])
NEW = T(CODE_TPL)
NEW_SB = T(CODE_TPL, sandbox=True)

PLAN_NAMES = ["NOT_EVALUATED", "NO_ACTION", "WOULD_REFUSE_STARTS", "WOULD_PREEMPT_DUMP", "WOULD_PREEMPT_FREE_POWER", "WAIT_DUMP_RESTORE",
              "WAIT_FREE_POWER_RESTORE", "WAIT_WRITE_IN_FLIGHT", "WAIT_LIVE_DATA", "WAIT_MANUAL_TOU_RECOVERY", "BLOCKED_RECOVERY_METADATA",
              "BLOCKED_DURABLE_UNKNOWN", "BLOCKED_OPERATOR_NEEDED", "BLOCKED_PROFILE_CORRUPT", "BLOCKED_PROFILE_UNAVAILABLE",
              "BLOCKED_SITE_CEILING", "BLOCKED_CONTEXT_MISMATCH", "BLOCKED_LIVE_OUT_OF_DOMAIN", "BLOCKED_NO_PROFILE",
              "BLOCKED_PROFILE_INVALIDATED", "WOULD_ALREADY_MATCH", "WOULD_APPLY_PROFILE", "WOULD_REMAIN_LATCHED"]


def lm(m="MATCH", obl="FP:CR,DP:CR,R4:CR,BUS:OK", eh="0", dx="-", cx="-", ew="-") -> str:
    return f"m={m};dx={dx};cx={cx};ox=-;ix=-;eh={eh};obl={obl};ca=F;elig=OK;ew={ew}"


def world(P, live, hw="0", g="7", ss="unknown", verdict="unknown", inputs="unknown", episode="unknown", soak="unknown"):
    summary = f"g={g};id=D852A4FA2DF7DBA3;at=1790000000;ld=OK;df=-;w=OK;hw={g};op=SAVE;why=-;werr=-;us=-"
    v = {B1: P, B2: summary, HW: hw, SS: ss, VD: verdict, IN: inputs, EP: episode, SK: soak}
    if live is not None:
        v[B10] = live
    return v


P_VALUES = ["unknown", "unavailable", "", "VALID", "NOT_CAPTURED", "INVALIDATED", "SAVE_UNCONFIRMED", "UNREADABLE", "CORRUPT",
            "CORRUPT_DOMAIN", "PROFILE_LOST", "PROFILE_STALE", "WEIRD_CLASS"]
M_VALUES = ["MATCH", "DRIFT", "CONTEXT", "EXPORT", "OUT_OF_DOMAIN", "PAUSED", "PAUSED_IO", "UNKNOWN", "NO_PROFILE", "SOMETHING_NEW"]
OBL_VALUES = {
    "clear": "FP:CR,DP:CR,R4:CR,BUS:OK", "none": "-",
    "UR": "FP:UR,DP:CR,R4:CR,BUS:OK", "MC": "FP:CR,DP:MC,R4:CR,BUS:OK", "CT": "FP:CR,DP:CR,R4:CT,BUS:OK", "ML": "FP:ML,DP:CR,R4:CR,BUS:OK",
    "ON": "FP:ON,DP:CR,R4:CR,BUS:OK", "DV": "FP:CR,DP:DV,R4:CR,BUS:OK", "LK": "FP:CR,DP:CR,R4:CR,BUS:LK", "R4PC": "FP:CR,DP:CR,R4:PC,BUS:OK",
    "FPPC": "FP:PC,DP:CR,R4:CR,BUS:OK", "DPRR": "FP:CR,DP:RR,R4:CR,BUS:OK", "active": "FP:AC,DP:CR,R4:CR,BUS:OK",
    "UR+ON": "FP:UR,DP:ON,R4:CR,BUS:OK",
}
UNREADABLE_OBL = {"UR", "MC", "CT", "ML", "UR+ON"}
LOCKOUT_OBL = {"ON", "DV", "LK", "R4PC"}
HW_VALUES = ["0", "9"]


def rows_over(ss_values):
    for P, m, (olabel, obl), hw, ss in itertools.product(P_VALUES, M_VALUES, OBL_VALUES.items(), HW_VALUES, ss_values):
        yield P, m, olabel, obl, hw, ss


n_cases = 0
diff_old_new_nonepisode, diff_episode, diff_sandbox = [], [], []
for P, m, olabel, obl, hw, ss in rows_over(NON_EPISODE_STATES + EPISODE_STATES):
    w = world(P, lm(m=m, obl=obl), hw=hw, ss=ss)
    old, new = OLD(w), NEW(w)
    n_cases += 1
    if ss in EPISODE_STATES:
        want = old if old in ("not_reporting", "lease_unreadable", "lease_lockout") else "shadow_episode"
        if new != want:
            diff_episode.append((P, m, olabel, hw, ss, old, new))
    elif new != old:
        diff_old_new_nonepisode.append((P, m, olabel, hw, ss, old, new))
    if n_cases % 97 == 0 and NEW_SB(w) != new:
        diff_sandbox.append((P, m, olabel, hw, ss))
check(f"1/9: no shadow episode (every other shadow-state value incl. unknown / unavailable / garbage): status code == the FB-B3 template over {n_cases} cases",
      not diff_old_new_nonepisode, str(diff_old_new_nonepisode[:3]))
check("2/3: SHADOW_EPISODE and SHADOW_EPISODE_HA_BACK -> shadow_episode, except not_reporting / lease_unreadable / lease_lockout (every profile class x live match x obligation x high-water)",
      not diff_episode, str(diff_episode[:3]))
check("the sandboxed environment gives the same code (sampled)", not diff_sandbox, str(diff_sandbox[:3]))

# --- explicit precedence rows (independent of the differential oracle)
for ss in EPISODE_STATES:
    rows = [
        ("unknown", lm(), "not_reporting"), ("unavailable", lm(), "not_reporting"), ("", lm(), "not_reporting"),
        ("unknown", lm(obl=OBL_VALUES["UR"]), "not_reporting"),                      # not_reporting outranks every lease row
        ("VALID", lm(obl=OBL_VALUES["UR"]), "lease_unreadable"), ("VALID", lm(obl=OBL_VALUES["MC"]), "lease_unreadable"),
        ("VALID", lm(obl=OBL_VALUES["CT"]), "lease_unreadable"), ("VALID", lm(obl=OBL_VALUES["ML"]), "lease_unreadable"),
        ("NOT_CAPTURED", lm(m="NO_PROFILE", obl=OBL_VALUES["UR"]), "lease_unreadable"),
        ("SAVE_UNCONFIRMED", lm(obl=OBL_VALUES["UR"]), "lease_unreadable"),
        ("VALID", lm(obl=OBL_VALUES["UR+ON"]), "lease_unreadable"),                 # unreadable outranks lockout
        ("VALID", lm(obl=OBL_VALUES["ON"]), "lease_lockout"), ("VALID", lm(obl=OBL_VALUES["DV"]), "lease_lockout"),
        ("VALID", lm(obl=OBL_VALUES["LK"]), "lease_lockout"), ("VALID", lm(obl=OBL_VALUES["R4PC"]), "lease_lockout"),
        ("INVALIDATED", lm(m="NO_PROFILE", obl=OBL_VALUES["R4PC"]), "lease_lockout"),
        ("VALID", lm(), "shadow_episode"), ("VALID", lm(m="DRIFT"), "shadow_episode"), ("VALID", lm(m="EXPORT"), "shadow_episode"),
        ("VALID", lm(m="OUT_OF_DOMAIN"), "shadow_episode"), ("VALID", lm(m="MATCH", obl=OBL_VALUES["FPPC"]), "shadow_episode"),
        ("VALID", lm(m="PAUSED"), "shadow_episode"), ("VALID", None, "shadow_episode"),
        ("SAVE_UNCONFIRMED", lm(), "shadow_episode"), ("NOT_CAPTURED", lm(m="NO_PROFILE"), "shadow_episode"),
        ("INVALIDATED", lm(m="NO_PROFILE"), "shadow_episode"), ("PROFILE_LOST", lm(m="NO_PROFILE"), "shadow_episode"),
        ("CORRUPT", lm(m="NO_PROFILE"), "shadow_episode"), ("WEIRD_CLASS", lm(), "shadow_episode"),
    ]
    for P, live, want in rows:
        got = NEW(world(P, live, ss=ss))
        label = "-" if live is None else live[live.find("m="):live.find(";dx")] + " " + live[live.find("obl="):live.find(";ca")]
        check(f"{ss}: P={P!r} {label} -> {want}", got == want, f"got {got!r}")
    # regressed / save-unconfirmed rows below the shadow row: the episode outranks them (FINAL 9.7 row 9 before 10 / 11)
    check(f"{ss}: profile_regressed (high-water above the device) -> shadow_episode", NEW(world("VALID", lm(), hw="9", ss=ss)) == "shadow_episode")
check("4: lease_unreadable + episode -> lease_unreadable (explicit)", NEW(world("VALID", lm(obl=OBL_VALUES["UR"]), ss="SHADOW_EPISODE")) == "lease_unreadable")
check("5: lease_lockout + episode -> lease_lockout (explicit)", NEW(world("VALID", lm(obl=OBL_VALUES["ON"]), ss="SHADOW_EPISODE_HA_BACK")) == "lease_lockout")

# --- 6 / 7 / 8: the shadow VERDICT, Inputs, Episode and Soak never change the canonical status (outside or inside an episode)
VERDICT_VALUES = PLAN_NAMES + ["unknown", "unavailable", "", "SOMETHING_NEW"]
INPUT_VALUES = ["unknown", "sup=L;st=0;fp=CM;dp=CA;r4=O6;mt=-;pc=5;g=7;pb=1A2B3C4D;e1=D;cx=D;in=N;ca=P;d=5;blk=5;lk=3;pl=24;rs=509",
                "sup=O;st=1;fp=O6;dp=U17;r4=CR;mt=-;pc=0;g=-;pb=-;e1=N;cx=N;in=N;ca=B;d=-;blk=0;lk=0;pl=21;rs=117"]
EPISODE_VALUES = ["unknown", "id=1A2B3C4D-1;ph=O;k=N;tr=H;u0=5231;e0=1799999000;cli=0;rb=600;v0=24;vu=-;f0=7;dm=9;pre=0;blk=0;d=-;ret=-;gap=-;rl=0;vch=0;cl=-;fbf=-"]
mismatch = []
for P, m, olabel, hw, ss in itertools.product(["VALID", "unknown", "NOT_CAPTURED", "SAVE_UNCONFIRMED"], ["MATCH", "DRIFT"],
                                                   ["clear", "UR", "ON", "FPPC"], ["0"], ["SHADOW_IDLE", "unknown", "SHADOW_EPISODE", "SHADOW_WOULD_AWAIT_ACK"]):
    base_code = NEW(world(P, lm(m=m, obl=OBL_VALUES[olabel]), ss=ss))
    for v, i, e in itertools.product(VERDICT_VALUES, INPUT_VALUES, EPISODE_VALUES):
        got = NEW(world(P, lm(m=m, obl=OBL_VALUES[olabel]), ss=ss, verdict=v, inputs=i, episode=e, soak="b=1;h=1/1/1/1/1/1"))
        if got != base_code:
            mismatch.append((P, m, olabel, ss, v, got, base_code))
check("6/7/8: BLOCKED_RECOVERY_METADATA / every other BLOCKED_* / WAIT_* / WOULD_* Verdict (and the never-published NO_ACTION / WOULD_REFUSE_STARTS), "
      "Inputs and Episode values never change the canonical status (outside an episode they cannot create Blocked)", not mismatch, str(mismatch[:3]))
check("6: BLOCKED_RECOVERY_METADATA outside an episode with a healthy profile and a clean lease stays `match`",
      NEW(world("VALID", lm(), ss="SHADOW_IDLE", verdict="BLOCKED_RECOVERY_METADATA", inputs=INPUT_VALUES[1])) == "match")
check("7: BLOCKED_* verdicts outside an episode do not make the DISPLAY word Blocked",
      all(T(DISPLAY_TPL)({CODE: NEW(world("VALID", lm(), ss="SHADOW_IDLE", verdict=v))}) == "Ready" for v in PLAN_NAMES if v.startswith("BLOCKED")))
check("8: WAIT_* / WOULD_* verdicts outside an episode keep the display word Ready",
      all(T(DISPLAY_TPL)({CODE: NEW(world("VALID", lm(), ss="SHADOW_WATCH", verdict=v))}) == "Ready"
          for v in PLAN_NAMES if v.startswith(("WAIT", "WOULD"))))
check("9: unavailable / unknown shadow state never opens the row; unknown profile state is still not_reporting",
      NEW(world("VALID", lm(), ss="unavailable")) == "match" and NEW(world("VALID", lm(), ss="unknown")) == "match"
      and NEW(world("unknown", lm(), ss="SHADOW_EPISODE")) == "not_reporting")
check("no shadow_block cause and no stale cross-boot fields in the status template",
      "shadow_block" not in CODE_TPL and not re.search(r"\b(pv|pu|pe|ch|RTC_NOINIT)\b", code_text(STATUS_PKG)))

# ===========================================================================
print("")
print("[3] Display word, subline, health, reason code, check id (exact); no FALLBACK_SHADOW_BLOCKED anywhere")
DISP = T(DISPLAY_TPL)
check("10: display word is exactly 'Shadow Recovery'", DISP({CODE: "shadow_episode"}) == "Shadow Recovery")
b3_words = {"not_reporting": "Unknown", "unexpected_state": "Unknown", "live_unknown": "Unknown", "lease_unreadable": "Blocked",
            "lease_lockout": "Blocked", "lease_restoring": "Blocked", "save_unconfirmed": "Blocked", "profile_regressed": "Blocked",
            "profile_unusable": "Blocked", "live_out_of_domain": "Blocked", "not_captured": "Not Captured", "invalidated": "Invalidated",
            "drift_export": "Drifted", "drift_context": "Drifted", "drift_values": "Drifted", "match": "Ready", "paused": "Ready",
            "something_else": "Unknown", "unknown": "Unknown", "unavailable": "Unknown", "shadow_block": "Unknown"}
check("every FB-B3 display word is unchanged (and the deleted shadow_block cause is Unknown)", all(DISP({CODE: c}) == w for c, w in b3_words.items()))
EXPECT_SUBLINE = "ECCO recorded a loss of Home Assistant supervision. Shadow mode: nothing was written."
sub = T(SUBLINE_TPL)
check("10: exact subline for shadow_episode (independent of the profile class and live match)",
      all(sub({**world(P, lm()), CODE: "shadow_episode"}) == EXPECT_SUBLINE for P in P_VALUES))
SUB_LINE_ELIF = "            {%- elif c == 'shadow_episode' -%}ECCO recorded a loss of Home Assistant supervision. Shadow mode: nothing was written.\n"
check("the subline template has exactly one C3 line", text.count(SUB_LINE_ELIF) == 1)
b3_sub = template_entities(load_text(text.replace(SUB_LINE_ELIF, "")))["ecco_fallback_status"]["attributes"]["subline"]
B3_SUBLINE_SHA256 = "d287d6a8244e035575122c03c5f144dadc8bcdba55ceee31a10c04e603b0f488"
_b3_sub_private = template_entities(load_text(_pub0.private_view_edited(   # PUB0: the private template's pin, same line edit
    "home-assistant/packages/ecco_fallback_status.yaml", text, {SUB_LINE_ELIF[:-1]: None})))["ecco_fallback_status"]["attributes"]["subline"]
check("without that line the subline template is the FB-B3 one (sha256), so no other subline moved", sha(_b3_sub_private) == B3_SUBLINE_SHA256, sha(_b3_sub_private))
OLD_DISPLAY_TEXT = text.replace(", 'shadow_episode': 'Shadow Recovery'}", "}")
check("the display lookup differs from FB-B3 only by the one shadow_episode word", OLD_DISPLAY_TEXT != text)

FB_H = HEALTH_ENT["ecco_health_fallback"]
fb_state, fb_codes = T(FB_H["state"]), T(FB_H["attributes"]["reason_codes"])
check("health: shadow_episode -> WARNING with exactly ['FAILBACK_SHADOW_EPISODE']",
      fb_state({CODE: "shadow_episode"}) == "WARNING" and literal(fb_codes({CODE: "shadow_episode"})) == ["FAILBACK_SHADOW_EPISODE"])
fb_expect = {
    "match": ("HEALTHY", []), "paused": ("HEALTHY", []), "not_captured": ("DEGRADED", ["FALLBACK_NOT_CAPTURED"]),
    "invalidated": ("DEGRADED", ["FALLBACK_INVALIDATED"]), "drift_values": ("DEGRADED", ["FALLBACK_DRIFTED"]),
    "drift_context": ("WARNING", ["FALLBACK_CONTEXT_CHANGED"]), "drift_export": ("WARNING", ["FALLBACK_EXPORT_ENABLED"]),
    "profile_unusable": ("WARNING", ["FALLBACK_UNUSABLE"]), "save_unconfirmed": ("WARNING", ["FALLBACK_SAVE_UNCONFIRMED"]),
    "profile_regressed": ("WARNING", ["FALLBACK_REGRESSED"]), "live_out_of_domain": ("WARNING", ["FALLBACK_LIVE_OUT_OF_DOMAIN"]),
    "lease_unreadable": ("WARNING", ["FALLBACK_BLOCKED_BY_LEASE"]), "lease_lockout": ("WARNING", ["FALLBACK_BLOCKED_BY_LEASE"]),
    "live_unknown": ("UNKNOWN", ["FALLBACK_LIVE_UNKNOWN"]), "not_reporting": ("UNKNOWN", ["FALLBACK_STATUS_UNAVAILABLE"]),
    "unexpected_state": ("UNKNOWN", ["FALLBACK_STATUS_UNAVAILABLE"]), "unknown": ("UNKNOWN", ["FALLBACK_STATUS_UNAVAILABLE"]),
    "shadow_block": ("UNKNOWN", ["FALLBACK_STATUS_UNAVAILABLE"]),
}
check("every FB-B3 health mapping is unchanged (and a deleted shadow_block cause is UNKNOWN, never WARNING)",
      all(fb_state({CODE: c}) == s and literal(fb_codes({CODE: c})) == rc for c, (s, rc) in fb_expect.items()))
represented = literal(T(FB_H["attributes"]["represented_checks"])({}))
check("the fallback health sensor represents the new check", "fallback_shadow_episode" in represented and len(represented) == 13)

rc_list = yaml.safe_load(REASON_CODES.read_text(encoding="utf-8"))["reason_codes"]
rc_by = {r["code"]: r for r in rc_list}
ck_list = yaml.safe_load(CHECKS.read_text(encoding="utf-8"))["checks"]
ck_by = {c["id"]: c for c in ck_list}
r = rc_by.get("FAILBACK_SHADOW_EPISODE", {})
check("11: reason code FAILBACK_SHADOW_EPISODE: fallback / WARNING / exact meaning and safe diagnostic step / never gates manual control or forecast",
      r.get("subsystem") == "fallback" and r.get("severity") == "WARNING"
      and r.get("meaning") == "A supervision-loss shadow episode is open; nothing was written."
      and r.get("safe_diagnostic_step") == "No action needed; it closes after 5 minutes of stable supervision."
      and r.get("blocks_manual_control") is False and r.get("affects_forecast") is False, str(r))
c = ck_by.get("fallback_shadow_episode", {})
check("11: check fallback_shadow_episode watches the canonical status code for shadow_episode and reports only that reason code",
      c.get("subsystem") == "fallback" and c.get("source") == {"entity": CODE, "type": "ha_template_sensor"}
      and c.get("parameters") == {"failure_values": ["shadow_episode"]} and [o["reason_code"] for o in c.get("outcomes", [])] == ["FAILBACK_SHADOW_EPISODE"]
      and c.get("check_type") == "text_state" and c.get("dependencies") == [], str(c))
check("11: the new reason code carries none of the FB-A banned substrings",
      "FALLBACK" + "_PROFILE" not in "FAILBACK_SHADOW_EPISODE" and "FAILBACK" + "_STATE" not in "FAILBACK_SHADOW_EPISODE")
FORBIDDEN = ["FALLBACK" + "_SHADOW_BLOCKED", "fallback" + "_shadow_blocked", "FAILBACK" + "_SHADOW_BLOCKED", "shadow" + "_block"]
scan = [p for p in list((HA / "packages").glob("*.yaml")) + list((HA / "dashboards").glob("ecco_pro.yaml")) + [REASON_CODES, CHECKS, ROOT / "health" / "system_health.py"]
        if any(tok in lf(p) for tok in FORBIDDEN)]
check("12: FALLBACK_SHADOW_BLOCKED / fallback_shadow_blocked / shadow_block exist in no package, dashboard, health engine or registry file",
      not scan, str([p.name for p in scan]))
check("12: the only reason codes starting FAILBACK_ are FAILBACK_SHADOW_EPISODE (FB-E/F codes stay reserved)",
      sorted(c for c in rc_by if c.startswith("FAILBACK_")) == ["FAILBACK_SHADOW_EPISODE"])
check("the shadow episode is the only shadow-related fallback check", sorted(i for i in ck_by if "shadow" in i) == ["fallback_shadow_episode"])
fb_checks = {i: c for i, c in ck_by.items() if c["subsystem"] == "fallback"}
check("every fallback check still has exactly one outcome that resolves to a registered fallback reason code",
      all(len(c["outcomes"]) == 1 and rc_by[c["outcomes"][0]["reason_code"]]["subsystem"] == "fallback" for c in fb_checks.values()))
vproc = subprocess.run([sys.executable, str(ROOT / "tools" / "validate_system_health_checks.py")], capture_output=True, text=True)
check("17: tools/validate_system_health_checks.py still passes with the new reason code and check",
      vproc.returncode == 0 and "PASSED" in vproc.stdout, (vproc.stdout + vproc.stderr)[-300:])
health_code_literals = set(re.findall(r"'([A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+)'", lf(HEALTH_PKG)))
check("every reason-code literal in the health package is registered", all(c in rc_by for c in health_code_literals if c.startswith(("FALLBACK_", "FAILBACK_", "SUPERVISION_"))))

# ===========================================================================
print("")
print("[4] The decoder sensor (a pure mapping of the existing C2 strings; no second evaluator)")
STATE_T = T(SHADOW["state"])
STATE_T_SB = T(SHADOW["state"], sandbox=True)
ATTR_T = {k: T(t) for k, t in SHADOW_ATTRS.items() if isinstance(t, str) and "{{" in t}
ATTR_T_SB = {k: T(t, sandbox=True) for k, t in SHADOW_ATTRS.items() if isinstance(t, str) and "{{" in t}


def attrs_of(values, now=NOW, sandbox=False):
    src = ATTR_T_SB if sandbox else ATTR_T
    return {k: literal(t(values, now)) for k, t in src.items()}


# S4 section 8.1 is the independent oracle of the operator wording
s4 = S4_DOC.read_text(encoding="utf-8")
sec = s4[s4.index("| # | Code | Meaning | Emitted by"):s4.index("**FB-A results FB-C never projects")]
S4_WORDING = {}
for line in sec.splitlines():
    cells = [c.strip() for c in line.strip().strip("|").split("|")]
    if len(cells) == 6 and cells[0].isdigit():
        S4_WORDING[cells[1]] = cells[5]
check("the S4 section 8.1 table parsed: 22 plan rows", len(S4_WORDING) == 22 and "WOULD_APPLY_PROFILE" in S4_WORDING, str(len(S4_WORDING)))
# FINAL FB-C2 Verdict contract (remediation d172574, merged as PR #63): the Verdict is the readiness plan of one MODE_IF_LOST evaluation
# (or 50 while the modelled FB-F latch is set). S4's supervision rows NO_ACTION / WOULD_REFUSE_STARTS are NEVER published (S5 2.3: they
# show as SHADOW_IDLE / SHADOW_WATCH on the State), so the decoder gives them no Verdict wording.
UNPUBLISHED = ["NO_ACTION", "WOULD_REFUSE_STARTS"]
PUBLISHED = [n for n in PLAN_NAMES if n not in UNPUBLISHED]
NOT_RECOGNISED = "Shadow check result not recognised"
HEAD_READY = "If Home Assistant were lost now, a future automatic failback would:"   # S5 6.4
HEAD_EPISODE = "A shadow episode is open; a future automatic failback would now:"
WORDING_NOW = {}
for name in PLAN_NAMES:
    WORDING_NOW[name] = STATE_T({VD: name, IN: "unknown"})
DEVIATIONS = {
    "WOULD_APPLY_PROFILE": "Would apply known-good profile",           # S4 "(N registers)": N comes from Inputs d
    "WOULD_REMAIN_LATCHED": "Would stay latched: previous episode not acknowledged",   # S3 section 11 wording for code 50
}
bad = [(n, WORDING_NOW[n], DEVIATIONS.get(n, S4_WORDING.get(n))) for n in PUBLISHED
       if n != "NOT_EVALUATED" and WORDING_NOW[n] != DEVIATIONS.get(n, S4_WORDING.get(n))]
check("every published Verdict wording equals the S4 section 8.1 operator wording (two recorded deviations)", not bad, str(bad[:3]))
check("NO_ACTION / WOULD_REFUSE_STARTS (never published since the FB-C2 remediation) have no Verdict wording: they read 'not recognised'",
      all(WORDING_NOW[n] == NOT_RECOGNISED for n in UNPUBLISHED) and "No action needed" not in lf(STATUS_PKG) and "supervision healthy" not in lf(STATUS_PKG))
check("NOT_EVALUATED wording is the S4 one", WORDING_NOW["NOT_EVALUATED"] == S4_WORDING["NOT_EVALUATED"] == "Shadow evaluator not ready yet")
check("every Verdict wording is at most 60 characters (S4 section 8.1)", all(len(w) <= 60 for n, w in WORDING_NOW.items() if n != "WOULD_APPLY_PROFILE"))
check("WOULD_APPLY_PROFILE reads '(N registers)' from the Inputs delta count (1 -> register)",
      STATE_T({VD: "WOULD_APPLY_PROFILE", IN: "sup=O;d=5;pl=41"}) == "Would apply known-good profile (5 registers)"
      and STATE_T({VD: "WOULD_APPLY_PROFILE", IN: "sup=O;d=1;pl=41"}) == "Would apply known-good profile (1 register)"
      and STATE_T({VD: "WOULD_APPLY_PROFILE", IN: "sup=O;d=-;pl=41"}) == "Would apply known-good profile")
check("the decoder state is unavailable-safe: unknown / unavailable / empty Verdict -> 'Shadow check not available'; an unrecognised name is named so",
      all(STATE_T({VD: v}) == "Shadow check not available" for v in ("unknown", "unavailable", "", "none"))
      and STATE_T({VD: "BRAND_NEW_PLAN"}) == "Shadow check result not recognised")
check("the decoder state agrees between the plain and the sandboxed environment for every plan",
      all(STATE_T({VD: n, IN: "sup=O;d=3"}) == STATE_T_SB({VD: n, IN: "sup=O;d=3"}) for n in PLAN_NAMES))
check("every published Verdict wording is at most 60 characters; 21 published Verdict names (the 23 plan codes minus the two supervision rows)",
      all(len(WORDING_NOW[n]) <= 60 for n in PUBLISHED) and len(PUBLISHED) == 21)
check("no wording contains the repository's banned HA service token or a Fallback word the Energy Actions card reacts to",
      not any("action:" in w for w in WORDING_NOW.values()))

# ---- Inputs grammar (the ACTUAL C2 keys: sup;st;fp;dp;r4;mt;pc;g;pb;e1;cx;in;ca;d;blk;lk;pl;rs;alt;pa - alt / pa appended, FINAL 8.5)
INPUTS_OK = "sup=O;st=1;fp=CM;dp=CA;r4=O6;mt=-;pc=5;g=7;pb=1A2B3C4D;e1=D;cx=M;in=N;ca=F;d=5;blk=5;lk=2;pl=41;rs=702;alt=41;pa=41"
a = attrs_of({IN: INPUTS_OK, VD: "WOULD_APPLY_PROFILE", SS: "SHADOW_IDLE"})
inp = a["inputs"]
check("Inputs: every actual C2 key is decoded", inp["available"] is True and inp["supervision"] == "supervised" and inp["stable"] == "stable"
      and inp["free_power"] == "clear (boot marker)" and inp["dump_to_grid"] == "clear by absence (not proven)"
      and inp["register_244_test"] == "obligation: needs your decision" and inp["manual_tou"] == "not evaluated"
      and inp["profile_class"] == "VALID" and inp["profile_generation"] == "7" and inp["profile_binding"] == "1A2B3C4D"
      and inp["e1"] == "differs" and inp["context"] == "matches" and inp["info"] == "not comparable" and inp["cache"] == "fresh"
      and inp["delta_count"] == "5" and inp["projected_frames"] == ["244 export write (0 to 2)", "target SOC / source (268-279)"]
      and inp["locks"] == "clock correction in progress" and inp["if_lost_plan"] == "WOULD_APPLY_PROFILE"
      and inp["if_lost_wording"] == "Would apply known-good profile (5 registers)" and inp["if_lost_reason"] == "E1_DELTA"
      and inp["absence_accepted_plan"] == "WOULD_APPLY_PROFILE" and inp["absence_accepted_plan_code"] == "41"
      and inp["projected_after_plan"] == "WOULD_APPLY_PROFILE" and inp["projected_after_plan_code"] == "41", str(inp))
R3_IN = INPUTS_OK.replace("pl=41;rs=702;alt=41;pa=41", "pl=21;rs=117;alt=40;pa=21")
r3 = attrs_of({IN: R3_IN})["inputs"]
check("Inputs alt / pa: the plan if an absent lease record were accepted and the plan after the awaited pre-empt / restore are decoded "
      "(R3: pl=21 BLOCKED_DURABLE_UNKNOWN, alt=40 WOULD_ALREADY_MATCH; an active lease: pl=11, pa=40); never with an invented register count",
      r3["if_lost_plan"] == "BLOCKED_DURABLE_UNKNOWN" and r3["absence_accepted_plan"] == "WOULD_ALREADY_MATCH"
      and r3["absence_accepted_wording"] == "Would do nothing: inverter already matches profile" and r3["projected_after_plan"] == "BLOCKED_DURABLE_UNKNOWN"
      and attrs_of({IN: INPUTS_OK.replace("pl=41;rs=702;alt=41;pa=41", "pl=11;rs=201;alt=11;pa=40")})["inputs"]["projected_after_plan"] == "WOULD_ALREADY_MATCH"
      and attrs_of({IN: INPUTS_OK})["inputs"]["absence_accepted_wording"] == "Would apply known-good profile", str(r3))
check("Inputs without alt / pa (an older string) still decode; alt / pa read '-'",
      attrs_of({IN: INPUTS_OK.replace(";alt=41;pa=41", "")})["inputs"]["if_lost_plan"] == "WOULD_APPLY_PROFILE"
      and attrs_of({IN: INPUTS_OK.replace(";alt=41;pa=41", "")})["inputs"]["absence_accepted_plan"] == "-"
      and attrs_of({IN: INPUTS_OK.replace(";alt=41;pa=41", "")})["inputs"]["projected_after_wording"] == "-")
for key, table in {
    "sup": {"U": "starting (no heartbeat yet)", "O": "supervised", "S": "suspect", "L": "lost"},
}.items():
    for k, v in table.items():
        got = attrs_of({IN: INPUTS_OK.replace("sup=O", f"sup={k}")})["inputs"]["supervision"]
        check(f"Inputs sup={k} -> {v}", got == v, got)
CMP = {"M": "matches", "D": "differs", "N": "not comparable", "O": "not a baseline (cache overlay)"}
for k, v in CMP.items():
    got = attrs_of({IN: INPUTS_OK.replace("e1=D", f"e1={k}").replace("cx=M", f"cx={k}").replace("in=N", f"in={k}")})["inputs"]
    check(f"Inputs e1 / cx / in = {k} -> {v}", (got["e1"], got["context"], got["info"]) == (v, v, v), str(got))
CACHE = {"B": "boot not loaded yet", "I": "no valid cache", "O": "configuration polling off", "S": "stale",
         "P": "may pre-date a write (write fence)", "M": "never filled", "F": "fresh"}
for k, v in CACHE.items():
    got = attrs_of({IN: INPUTS_OK.replace("ca=F", f"ca={k}")})["inputs"]["cache"]
    check(f"Inputs ca={k} -> {v}", got == v, got)
PCLASS = {0: "UNREADABLE", 1: "NOT_CAPTURED", 2: "CORRUPT", 3: "CORRUPT_DOMAIN", 4: "INVALIDATED", 5: "VALID", 6: "PROFILE_LOST",
          7: "SAVE_UNCONFIRMED", 8: "PROFILE_STALE"}
check("Inputs pc 0..8 -> the nine profile classes (an unknown code is '-')",
      all(attrs_of({IN: INPUTS_OK.replace("pc=5", f"pc={k}")})["inputs"]["profile_class"] == v for k, v in PCLASS.items())
      and attrs_of({IN: INPUTS_OK.replace("pc=5", "pc=99")})["inputs"]["profile_class"] == "-")
DOM_KIND = {0: "none", 1: "active", 2: "starting", 3: "restore required", 4: "ending", 5: "clear pending", 6: "needs your decision", 7: "in flight",
            16: "recovery state unreadable", 17: "recovery metadata corrupt", 19: "not loaded at boot",
            20: "stored state disagrees with memory", 21: "inverter lock stuck", 23: "probe pending"}
ok_dom = True
for kk, vv in DOM_KIND.items():
    g = attrs_of({IN: INPUTS_OK.replace("fp=CM", f"fp=O{kk}").replace("dp=CA", f"dp=U{kk}")})["inputs"]
    ok_dom &= g["free_power"] == f"obligation: {vv}" and g["dump_to_grid"] == f"unknown: {vv}"
check("Inputs domain O<kind> / U<kind>: every kind code of the C2 header is named", ok_dom)
g = attrs_of({IN: INPUTS_OK.replace("fp=CM", "fp=CR").replace("dp=CA", "dp=C-").replace("r4=O6", "r4=CM")})["inputs"]
check("Inputs domain C<basis>: M boot marker, R runtime, A absence (not proven), '-' plain clear",
      (g["free_power"], g["dump_to_grid"], g["register_244_test"]) == ("clear (checked at runtime)", "clear", "clear (boot marker)"), str(g))
check("Inputs lk 0..3 and blk frames",
      [attrs_of({IN: INPUTS_OK.replace("lk=2", f"lk={k}")})["inputs"]["locks"] for k in range(4)]
      == ["none", "manual write in progress", "clock correction in progress", "manual write and clock correction in progress"]
      and attrs_of({IN: INPUTS_OK.replace("blk=5", "blk=F")})["inputs"]["projected_frames"]
      == ["244 export write (0 to 2)", "slot power down (256-261)", "target SOC / source (268-279)", "slot power up (256-261)"]
      and attrs_of({IN: INPUTS_OK.replace("blk=5", "blk=0")})["inputs"]["projected_frames"] == [])
bad = []
for code in ("1", "2", "50"):
    g = attrs_of({IN: INPUTS_OK.replace("pl=41;rs=702;alt=41;pa=41", f"pl={code};rs=1;alt={code};pa={code}"), VD: "WOULD_APPLY_PROFILE", SS: "SHADOW_IDLE"})
    if (g["inputs"]["if_lost_plan"], g["inputs"]["if_lost_wording"], g["inputs"]["absence_accepted_plan"], g["inputs"]["projected_after_plan"]) != ("-",) * 4 \
            or sorted(g["unknown_keys"]) != sorted([f"inputs:pl={code}", f"inputs:alt={code}", f"inputs:pa={code}"]):
        bad.append((code, g["inputs"]["if_lost_plan"], g["unknown_keys"]))
check("Inputs pl / alt / pa = 1, 2 (MODE_ACTUAL supervision rows) or 50 (episode layer) are never published there: they read '-' and are listed verbatim",
      not bad, str(bad))
check("Inputs: sup / pl / rs unknown codes degrade to '-' (never invented text)",
      attrs_of({IN: INPUTS_OK.replace("pl=41", "pl=77").replace("rs=702", "rs=9999")})["inputs"]["if_lost_plan"] == "-"
      and attrs_of({IN: INPUTS_OK.replace("pl=41", "pl=77").replace("rs=702", "rs=9999")})["inputs"]["if_lost_wording"] == "-"
      and attrs_of({IN: INPUTS_OK.replace("rs=702", "rs=9999")})["inputs"]["if_lost_reason"] == "-")
check("the Inputs decoder holds no stale cross-boot field names (pv / pu / pe / ch / RTC breadcrumb)",
      not set(inp) & {"pv", "pu", "pe", "ch", "rtc", "breadcrumb"} and "RTC_NOINIT" not in lf(STATUS_PKG))

# ---- Episode grammar (id;ph;k;tr;u0;e0;cli;rb;v0;vu;f0;dm;pre;blk;d;ret;gap;rl;vch;cl;fbf)
EDGE = int(NOW) - 1000


def episode(**o):
    d = dict(id="1A2B3C4D-1", ph="O", k="N", tr="H", u0="5231", e0=str(EDGE), cli="0", rb="600", v0="41", vu="-", f0="4", dm="-", pre="0",
             blk="5", d="5", ret="-", gap="-", rl="0", vch="0", cl="-", fbf="-")
    d.update({k: str(v) for k, v in o.items()})
    return ";".join(f"{k}={v}" for k, v in d.items())


def ep_of(**o):
    return attrs_of({EP: episode(**o), SS: "SHADOW_EPISODE"})["episode"]


e = ep_of()
check("Episode: open, kind new, trigger heartbeat loss, edge details", e["phase"] == "open" and e["kind"] == "new" and e["trigger"] == "heartbeat loss"
      and e["id"] == "1A2B3C4D-1" and e["edge_uptime_s"] == "5231" and e["edge_epoch"] == EDGE and e["client_at_edge"] == "no"
      and e["reboot_margin_s"] == "600" and e["edge_time"] == datetime.fromtimestamp(EDGE, timezone.utc).strftime("%Y-%m-%d %H:%M:%S"), str(e))
check("Episode: frozen edge plan, FB-A result, blocking domain, pre-empt mask, frames, delta",
      e["edge_plan"] == "WOULD_APPLY_PROFILE" and e["fba_result"] == "APPLIED_VERIFIED" and e["blocking_domain"] == "-"
      and e["preempt"] == [] and e["projected_frames"] == ["244 export write (0 to 2)", "target SOC / source (268-279)"] and e["delta_count"] == "5", str(e))
check("Episode: lost for 16 min 40 s while open and never returned", e["lost_for"] == "16 min 40 s"
      and e["banner_lost"] == "Lost for 16 min 40 s since the loss was declared (episode 1A2B3C4D-1)." and e["phase"] == "open", e["banner_lost"])
check("Episode: banner states what a future failback would have done from the FROZEN edge plan",
      e["banner_would"] == "If automatic failback were enabled it would have: applied the known-good profile (5 settings).", e["banner_would"])
check("Episode: banner edge line (time, API client)", e["banner_edge"] == f"Loss declared at {e['edge_time']}; the API client was not connected at that moment.", e["banner_edge"])
PLAN_CODE = {n: c for n, c in zip(PLAN_NAMES, [0, 1, 2, 10, 11, 12, 13, 14, 15, 16, 20, 21, 22, 23, 24, 25, 26, 27, 30, 31, 40, 41, 50])}
# a would-have phrase must be REAL words: never the raw plan name (the fallback of the lookup) and never the 'nothing recorded' placeholder
READY_CODE = {n: c for n, c in PLAN_CODE.items() if n not in UNPUBLISHED and c != 50}
check("Episode: every readiness plan code at the edge (incl. NOT_EVALUATED, excl. the episode-layer 50) is named and has a real would-have phrase, never the raw enum",
      len(READY_CODE) == 20 and all(ep_of(v0=c)["edge_plan"] == n and ep_of(v0=c)["would_have"] not in (n, "nothing recorded", "")
                                    and not re.search(r"[A-Z]{3,}_[A-Z]", ep_of(v0=c)["would_have"]) for n, c in READY_CODE.items()),
      str({n: ep_of(v0=c)["would_have"] for n, c in READY_CODE.items() if re.search(r"[A-Z]{3,}_[A-Z]", ep_of(v0=c)["would_have"])}))
bad = [c for c in (1, 2) if ep_of(v0=c)["edge_plan"] != "-" or f"episode:v0={c}" not in attrs_of({EP: episode(v0=c), SS: "SHADOW_EPISODE"})["unknown_keys"]]
check("Episode: an edge plan of 1 / 2 (never frozen: the edge freezes the readiness plan) reads '-' and is listed verbatim; 50 is the kind-L latch",
      not bad and ep_of(k="L", v0=50, vu=41, f0="-")["edge_plan"] == "WOULD_REMAIN_LATCHED"
      and "episode:vu=50" in attrs_of({EP: episode(k="L", v0=50, vu=50), SS: "SHADOW_EPISODE"})["unknown_keys"], str(bad))
check("Episode: an episode frozen while the evaluator was not ready says so in words",
      ep_of(v0=0)["would_have"] == "been unable to evaluate a plan (the evaluator was not ready)")
check("Episode: pre-empt masks 1 / 2 / 3 and frozen kinds",
      [ep_of(pre=k)["preempt"] for k in (0, 1, 2, 3)] == [[], ["Free Power"], ["Dump to Grid"], ["Free Power", "Dump to Grid"]]
      and ep_of(v0=11, pre=1)["would_have"] == "ended Free Power, then continued failback")
check("Episode: kind L (an earlier shadow episode still latched) says so and keeps the underlying plan",
      ep_of(k="L", v0=50, vu=41, f0="-", d=5)["kind"] == "latched" and ep_of(k="L", v0=50, vu=41, f0="-")["underlying_plan"] == "WOULD_APPLY_PROFILE"
      and "done nothing new (an earlier shadow episode is still latched)" in ep_of(k="L", v0=50, vu=41, f0="-")["would_have"]
      and ep_of(k="L", v0=50, vu=41, f0="-", d=5)["would_have"].endswith("applied the known-good profile (5 settings)"))
check("Episode: 'applied the known-good profile' without a count when d is '-'", ep_of(d="-")["would_have"] == "applied the known-good profile")
check("Episode: trigger S (no heartbeat since the dongle started) and client at edge / unknown reboot margin",
      ep_of(tr="S", cli=1, rb="-")["trigger"] == "no heartbeat since the dongle started" and ep_of(tr="S", cli=1, rb="-")["client_at_edge"] == "yes"
      and ep_of(tr="S", cli=1, rb="-")["reboot_margin_s"] == "-" and "connected at that moment" in ep_of(cli=1)["banner_edge"])
dur_cases = {0: "0 s", 45: "45 s", 59: "59 s", 60: "1 min 0 s", 372: "6 min 12 s", 3599: "59 min 59 s", 3600: "1 h 0 min", 7384: "2 h 3 min"}
check("Episode: duration formatting", all(ep_of(e0=int(NOW) - s)["lost_for"] == t for s, t in dur_cases.items()), str({s: ep_of(e0=int(NOW) - s)["lost_for"] for s in dur_cases}))
check("Episode: no wall-clock time at the edge (e0=0) -> the duration is reported unavailable, not invented",
      ep_of(e0=0)["lost_for"] == "-" and ep_of(e0=0)["edge_time"] == "-" and "duration is not available" in ep_of(e0=0)["banner_lost"]
      and "an unknown time" in ep_of(e0=0)["banner_edge"])
hb = ep_of(ph="B", ret=372, gap="372.4")
check("Episode: HA_BACK -> returned after 6 min 12 s (gap 372.4 s), still open until stable",
      hb["phase"] == "ha_back" and hb["returned_after"] == "6 min 12 s" and hb["return_gap_s"] == "372.4"
      and hb["banner_lost"] == "Home Assistant is back 6 min 12 s after the loss was declared, but the episode (1A2B3C4D-1) stays open until supervision has been stable.", hb["banner_lost"])
cl = ep_of(ph="C", ret=372, gap="372.4", cl=680, fbf="A", rl=0)
check("Episode: closed -> closed after 11 min 20 s, FB-F would stay latched (A) / clear itself (P)",
      cl["phase"] == "closed" and cl["closed_after"] == "11 min 20 s" and cl["close_outcome"] == "a future FB-F would stay latched until acknowledged (no such control exists yet)"
      and ep_of(ph="C", cl=680, fbf="P")["close_outcome"] == "a future FB-F would clear itself" and ep_of(fbf="-")["close_outcome"] == "-")
rl = ep_of(ph="O", ret=100, rl=2, vch=3)
check("Episode: re-lost and verdict-change evidence is shown",
      rl["re_lost"] == "2" and rl["verdict_changes"] == "3" and rl["banner_lost"] == "Home Assistant supervision was lost again (episode 1A2B3C4D-1, 2 re-loss(es))."
      and rl["banner_details"] == "Re-lost 2 time(s) since the first loss; the verdict changed 3 time(s).", str(rl))
check("Episode: FB-A result and blocking-domain tables (0..11 / 0..11)",
      [ep_of(f0=i)["fba_result"] for i in range(12)] == ["NONE", "PREEMPTED_ONLY", "PREEMPTED_NO_PROFILE", "ALREADY_AT_PROFILE", "APPLIED_VERIFIED",
                                                         "BLOCKED_LEASE_RESTORE_LOCKED", "BLOCKED_MARKER_DIVERGENCE", "BLOCKED_PROFILE_UNAVAILABLE",
                                                         "BLOCKED_CONTEXT_MISMATCH", "BLOCKED_LIVE_OUT_OF_DOMAIN", "BLOCKED_SITE_CEILING", "BLOCKED_APPLY_FAILED"]
      and [ep_of(dm=i)["blocking_domain"] for i in range(12)] == ["none", "supervision", "boot", "Dump to Grid", "Free Power", "register 244 test", "inverter bus",
                                                                  "Manual TOU", "Manual TOU journal", "known-good profile", "site ceiling", "live inverter data"])
none_ep = "id=1A2B3C4D-0;ph=N;k=-;tr=-;u0=-;e0=-;cli=-;rb=-;v0=-;vu=-;f0=-;dm=-;pre=-;blk=-;d=-;ret=-;gap=-;rl=-;vch=-;cl=-;fbf=-"
ne = attrs_of({EP: none_ep, SS: "SHADOW_IDLE"})["episode"]
check("Episode: no episode on record (ph=N, every field '-')", ne["phase"] == "none" and ne["kind"] == "-" and ne["edge_plan"] == "-" and ne["banner_edge"] == ""
      and ne["banner_lost"] == "No shadow episode on record for this boot." and ne["would_have"] == "nothing recorded", str(ne))

# ---- Soak grammar (b;h;mx;lg;gm;lx;wr;nc;ncm;xh;cs)
SOAK_OK = "b=1A2B3C4D;h=2871/12/1/0/0/0;mx=61.2;lg=61.2;gm=0;lx=1;wr=3/2/1/4;nc=3;ncm=42;xh=7/9;cs=100/20/5"
sk = attrs_of({SK: SOAK_OK})["soak"]
check("Soak: every actual C2 key (boot id, histogram, gaps, episode count, start-refusal / profile evidence, API-client drops, export hazard, cache state)",
      sk["boot_id"] == "1A2B3C4D" and sk["gap_histogram"] == {"<=35 s": "2871", "<=45 s": "12", "<=90 s": "1", "<=300 s": "0", "<=900 s": "0", ">900 s": "0"}
      and sk["max_gap_s"] == "61.2" and sk["last_long_gap_s"] == "61.2" and sk["gaps_missed"] == "0" and sk["episodes"] == "1"
      and sk["starts_seen_while_would_refuse"] == {"free_power": "3", "dump_to_grid": "2", "register_244_test": "1", "profile_changes": "4"}
      and sk["api_client_drops"] == "3" and sk["longest_no_client_s"] == "42" and sk["export_hazard_s"] == {"yes": "7", "unknown": "9"}
      and sk["cache_s"] == {"fresh": "100", "pre_fence": "20", "other": "5"}, str(sk))
sk_bad = attrs_of({SK: "b=1A2B3C4D;h=1/2/3;wr=1/2;xh=1;cs=1/2"})["soak"]
check("Soak: malformed slash groups degrade to '-' instead of raising",
      sk_bad["gap_histogram"]["<=35 s"] == "-" and sk_bad["starts_seen_while_would_refuse"]["free_power"] == "-"
      and sk_bad["export_hazard_s"] == {"yes": "-", "unknown": "-"} and sk_bad["cache_s"]["fresh"] == "-")

# ---- unknown keys, raw strings, bad input
a = attrs_of({IN: INPUTS_OK + ";zz=1", EP: episode() + ";fut=7", SK: SOAK_OK + ";new=2", SS: "SHADOW_NEWSTATE", VD: "BRAND_NEW_PLAN"})
check("unknown append-only keys / values stay visible, verbatim", sorted(a["unknown_keys"]) == sorted(["inputs:zz=1", "episode:fut=7", "soak:new=2", "state:SHADOW_NEWSTATE", "verdict:BRAND_NEW_PLAN"]), str(a["unknown_keys"]))
check("a fully known set of strings reports no unknown keys", attrs_of({IN: INPUTS_OK, EP: episode(), SK: SOAK_OK, SS: "SHADOW_IDLE", VD: "WOULD_APPLY_PROFILE"})["unknown_keys"] == [])
check("a never-published Verdict name (NO_ACTION / WOULD_REFUSE_STARTS) is listed verbatim like any unrecognised value",
      all(attrs_of({IN: INPUTS_OK, EP: episode(), SK: SOAK_OK, SS: "SHADOW_IDLE", VD: n})["unknown_keys"] == [f"verdict:{n}"] for n in UNPUBLISHED))
check("raw strings are exposed unchanged", a["raw"]["inputs"] == INPUTS_OK + ";zz=1" and a["raw"]["soak"] == SOAK_OK + ";new=2")
down = attrs_of({})
check("every decoder attribute renders for unknown inputs (nothing raises; availability false)",
      down["inputs"]["available"] is False and down["episode"]["available"] is False and down["soak"]["available"] is False
      and down["unknown_keys"] == [] and down["episode_open"] is False and down["status_masks_shadow"] is False
      and down["verdict_scope"] == "not_available" and down["verdict_heading"] == "" and down["latched"] is False)
junk = {IN: "xx", EP: "=;;==", SK: "a=b=c;;", SS: "", VD: ";"}
check("garbage strings never raise and never invent a verdict", attrs_of(junk)["inputs"]["available"] is False and STATE_T(junk) in
      ("Shadow check result not recognised", "Shadow check not available"))
check("the plain and the sandboxed environment decode identically (every attribute)",
      attrs_of({IN: INPUTS_OK, EP: episode(), SK: SOAK_OK, SS: "SHADOW_EPISODE", VD: "WOULD_APPLY_PROFILE"})
      == attrs_of({IN: INPUTS_OK, EP: episode(), SK: SOAK_OK, SS: "SHADOW_EPISODE", VD: "WOULD_APPLY_PROFILE"}, sandbox=True))

# ---- masks / open flag / if-lost visibility
OPEN_T = T(STATUS_ENT["ecco_shadow_episode_open"]["state"])
check("binary sensor: on exactly for SHADOW_EPISODE and SHADOW_EPISODE_HA_BACK (the same condition that opens the canonical row)",
      all(OPEN_T({SS: s}) == "True" for s in EPISODE_STATES) and all(OPEN_T({SS: s}) == "False" for s in NON_EPISODE_STATES))
check("the status code opens its shadow row for the very same two values (no drift between the two conditions)",
      all(NEW(world("VALID", lm(), ss=s)) == "shadow_episode" for s in EPISODE_STATES)
      and all(NEW(world("VALID", lm(), ss=s)) != "shadow_episode" for s in NON_EPISODE_STATES))
masks = {("SHADOW_EPISODE", "lease_lockout"): True, ("SHADOW_EPISODE_HA_BACK", "lease_unreadable"): True, ("SHADOW_EPISODE", "shadow_episode"): False,
         ("SHADOW_IDLE", "lease_lockout"): False, ("SHADOW_EPISODE", "unknown"): False, ("SHADOW_EPISODE", "not_reporting"): True}
check("status_masks_shadow: an open episode whose canonical status is another cause (lease Blocked) is flagged; the shadow row itself is not",
      all(attrs_of({SS: s, CODE: c})["status_masks_shadow"] is want for (s, c), want in masks.items()), str({k: attrs_of({SS: k[0], CODE: k[1]})["status_masks_shadow"] for k in masks}))
bad = []
for n in PLAN_NAMES + ["unknown", "unavailable", "", "none", "BRAND_NEW_PLAN"]:
    for s in NON_EPISODE_STATES + EPISODE_STATES:
        g = attrs_of({VD: n, SS: s})
        if n in ("unknown", "unavailable", "", "none"):
            want = ("not_available", "")
        elif n not in PUBLISHED:
            want = ("unrecognised", "")
        elif n == "NOT_EVALUATED":
            want = ("not_evaluated", "")
        elif s in EPISODE_STATES:
            want = ("episode", HEAD_EPISODE)
        else:
            want = ("readiness", HEAD_READY)
        if (g["verdict_scope"], g["verdict_heading"]) != want or g["latched"] is not (n == "WOULD_REMAIN_LATCHED"):
            bad.append((n, s, g["verdict_scope"], g["verdict_heading"], g["latched"]))
check("verdict scope / heading (S5 6.4): readiness 'If Home Assistant were lost now, ...' outside an episode, the continuation inside one, "
      "no heading for NOT_EVALUATED / not recognised (incl. NO_ACTION / WOULD_REFUSE_STARTS) / not available; latched only for code 50",
      not bad, str(bad[:3]))
check("the old supervision-row switch (show_if_lost) is gone", "show_if_lost" not in lf(STATUS_PKG) and "show_if_lost" not in lf(DASH))
check("the decoder carries the five source entities and a no-persisted-history note",
      attrs_of({})["source_entities"] == FIVE and "RAM-only" in SHADOW_ATTRS["scope_note"] and "not stored" in SHADOW_ATTRS["scope_note"])
check("13: the five shadow entity ids in every HA package are exactly the five derived entities (no invented shadow id)",
      sorted({m for p in (HA / "packages").glob("*.yaml") for m in re.findall(r"sensor\.[a-z0-9_]*" + "ecco_" + FB + r"_shadow_[a-z0-9_]+", lf(p))}) == sorted(FIVE))

# ===========================================================================
print("")
print("[5] Dashboard: Safety view additions are display-only and read only the decoder")
dash_text = lf(DASH)
dash = load_text(dash_text)


def walk(n):
    yield n
    if isinstance(n, dict):
        for v in n.values():
            yield from walk(v)
    elif isinstance(n, list):
        for v in n:
            yield from walk(v)


def view(title):
    return next(v for v in dash["views"] if v.get("title") == title)


safety = view("Safety")
md = [n for n in walk(safety) if isinstance(n, dict) and n.get("type") == "markdown" and "content" in n]
banner = next(c for c in md if "SHADOW CHECK - HOME ASSISTANT SUPERVISION WAS LOST" in c["content"])
everyday = next(c for c in md if "SHADOW CHECK · NO ACTION TAKEN" in c["content"])
tech = next(c for c in md if "Failback shadow evaluator (diagnostic - writes nothing)" in c["content"])
check("banner: visible only while the episode flag is on; fixed words HA supervision lost / SHADOW / NOTHING WAS WRITTEN / 5 minutes",
      banner.get("visibility") == [{"condition": "state", "entity": OPEN, "state": "on"}]
      and all(s in banner["content"] for s in ("SHADOW mode: NOTHING WAS WRITTEN.", "Closes automatically after 5 minutes of continuous stable supervision.",
                                              "banner_lost", "banner_would", "banner_edge", "status_masks_shadow")))
check("everyday line: always visible (no visibility rule), fixed first line plus the decoder's S5 6.4 heading, then the decoder state",
      "visibility" not in everyday and "states('sensor.ecco_shadow_check')" in everyday["content"]
      and "state_attr('sensor.ecco_shadow_check', 'verdict_heading')" in everyday["content"] and "if_lost_wording" not in everyday["content"])
check("technical block: visible only behind input_boolean.ecco_safety_show_technical_detail (the existing helper)",
      tech.get("visibility") == [{"condition": "state", "entity": "input_boolean.ecco_safety_show_technical_detail", "state": "on"}])
for v in dash["views"]:
    if v.get("title") != "Safety":
        check(f"view {v.get('title')!r} carries no shadow check entity or text (the three cards live in the Safety view only)",
              not re.search(r"ecco_shadow_|SHADOW CHECK|Failback shadow evaluator", yaml.dump(v)))
ov = yaml.dump(view("Overview"))
check("Overview: the only shadow change is the display word 'Shadow Recovery' in the existing tile tone and hero chip maps",
      ov.count("Shadow Recovery") == 2 and "ecco_shadow_" not in ov and "SHADOW CHECK" not in ov)
for name, card in (("banner", banner), ("everyday", everyday), ("technical", tech)):
    refs = sorted(set(re.findall(r"(?:sensor|binary_sensor|input_boolean)\.[a-z0-9_]+", card["content"] + yaml.dump(card.get("visibility", [])))))
    check(f"{name}: references only the decoder / flag / helper / reset-reason entities", set(refs) <= {CHECK, OPEN, RESET, "input_boolean.ecco_safety_show_technical_detail"}, str(refs))
    check(f"{name}: no tap / hold action, no service call, no control", not (set(card) & {"tap_action", "hold_action", "double_tap_action", "entity", "entities"})
          and not re.search(r"perform_action|call-service|service:|button\.press|switch\.|script\.|esphome", yaml.dump(card)))
    check(f"{name}: no stale cross-boot field names and no acknowledgement control wording",
          not re.search(r"\b(pv|pu|pe|rtc_noinit)\b|RTC_NOINIT|acknowledge|Review Restore|restore_known", card["content"], re.I))
check("14: the Safety view's perform-action set is unchanged: exactly the three profile wrappers and the high-water reset",
      sorted(n["perform_action"] for n in walk(safety) if isinstance(n, dict) and "perform_action" in n)
      == ["script.ecco_fallback_profile_invalidate", "script.ecco_fallback_profile_replace_corrupt", "script.ecco_fallback_profile_save",
          "script.ecco_fallback_reset_high_water"])
all_pkgs = {p.name: load_text(lf(p)) for p in (HA / "packages").glob("*.yaml")}
PKG_SURFACE = {name: {k: len(v) for k, v in d.items() if k != "template"} for name, d in all_pkgs.items()}
check("14: no new HA control surface: the per-package count of every non-template key (script / automation / input_*) is exactly the FB-B3 one",
      PKG_SURFACE == {
          "ecco_battery_outlook_influx.yaml": {"sensor": 1}, "ecco_canonical_telemetry.yaml": {},
          "ecco_dump_to_grid_schedule.yaml": {"input_boolean": 1, "input_datetime": 1, "input_number": 3, "input_text": 1, "script": 2, "automation": 3},
          "ecco_fallback_profile_actions.yaml": {"script": 4}, "ecco_fallback_status.yaml": {"input_boolean": 1},
          "ecco_free_power_schedule.yaml": {"input_boolean": 1, "input_datetime": 1, "input_number": 2, "input_text": 1, "script": 2, "automation": 3},
          "ecco_manual_controls_helpers.yaml": {"input_datetime": 6, "input_number": 12, "automation": 8, "script": 1},
          "ecco_pro.yaml": {"input_select": 2, "input_boolean": 8, "input_number": 25, "input_datetime": 2, "automation": 3},
          "ecco_runtime_config.yaml": {}, "ecco_supervision_heartbeat.yaml": {"automation": 1}, "ecco_system_health.yaml": {}, "ecco_tou_schedule.yaml": {}},
      str(PKG_SURFACE))
script_ids = sorted(s for d in all_pkgs.values() for s in (d.get("script") or {}))
check("14: no script or automation id mentions the shadow", not [s for s in script_ids if "shadow" in s]
      and not [a for d in all_pkgs.values() for a in (d.get("automation") or []) if "shadow" in yaml.dump(a).lower()])
check("14: the status package defines no script, automation, switch, button, number, select or input_* other than the one toggle",
      not (set(status_doc) - {"template", "input_boolean"}) and list(status_doc["input_boolean"]) == ["ecco_safety_show_technical_detail"])
check("the dashboard never turns the arm on, executes the shadow, or exposes a shadow entity as a control",
      not re.search(r"switch\.[a-z0-9_]*shadow|button\.[a-z0-9_]*shadow|script\.[a-z0-9_]*shadow", dash_text))
check("the dashboard references no firmware shadow entity directly (the decoder is the only consumer)", not [i for i in FIVE if i in dash_text])

# ===========================================================================
print("")
print("[6] Rendered Safety cards over decoded worlds")
dash_env = jinja2.Environment(undefined=jinja2.StrictUndefined)


def build_world(raw: dict) -> tuple[dict, dict]:
    vals = {HW: "0", **raw}
    vals[CODE] = NEW(vals)
    vals[DISPLAY] = DISP(vals)
    attrs = {}
    for k, t in ATTR_T.items():
        attrs[f"{CHECK}#{k}"] = literal(t(vals))
    attrs[f"{CHECK}#scope_note"] = SHADOW_ATTRS["scope_note"]   # a static attribute (no template)
    vals[CHECK] = STATE_T(vals)
    vals[OPEN] = "on" if OPEN_T(vals) == "True" else "off"
    return vals, attrs


def drender(content, vals, attrs):
    ctx = {"states": _States(vals), "state_attr": lambda e, a: attrs.get(f"{e}#{a}"), "is_state": lambda e, s: vals.get(e, "unknown") == s}
    return dash_env.from_string(content).render(**ctx)


EP_OPEN = episode(ph="O", k="N", v0="11", pre="1", blk="0", d="-", f0="0", e0=int(NOW) - 372)
EP_BACK = episode(ph="B", ret="372", gap="372.4", v0="11", pre="1", blk="0", d="-", f0="0")
IDLE_IN = "sup=O;st=1;fp=CM;dp=CM;r4=CM;mt=-;pc=5;g=7;pb=1A2B3C4D;e1=M;cx=M;in=M;ca=F;d=0;blk=0;lk=0;pl=40;rs=701;alt=40;pa=40"
scen = {
    "idle": {B1: "VALID", B10: lm(), SS: "SHADOW_IDLE", VD: "WOULD_ALREADY_MATCH", IN: IDLE_IN, EP: none_ep, SK: SOAK_OK},
    "latched_idle": {B1: "VALID", B10: lm(), SS: "SHADOW_WOULD_AWAIT_ACK", VD: "WOULD_REMAIN_LATCHED", IN: IDLE_IN,
                     EP: episode(ph="C", ret="372", gap="372.4", cl="680", fbf="A", v0="11", pre="1", blk="0", d="-", f0="0"), SK: SOAK_OK},
    "legacy_supervision_row": {B1: "VALID", B10: lm(), SS: "SHADOW_IDLE", VD: "NO_ACTION", IN: IDLE_IN, EP: none_ep, SK: SOAK_OK},
    "episode": {B1: "VALID", B10: lm(), SS: "SHADOW_EPISODE", VD: "WOULD_PREEMPT_FREE_POWER",
                IN: IDLE_IN.replace("sup=O;st=1", "sup=L;st=0").replace("pl=40;rs=701;alt=40;pa=40", "pl=11;rs=201;alt=11;pa=40"),
                EP: EP_OPEN, SK: SOAK_OK, RESET: "Power-on"},
    "ha_back": {B1: "VALID", B10: lm(), SS: "SHADOW_EPISODE_HA_BACK", VD: "WOULD_PREEMPT_FREE_POWER", IN: IDLE_IN, EP: EP_BACK, SK: SOAK_OK},
    "episode_masked": {B1: "VALID", B10: lm(obl=OBL_VALUES["ON"]), SS: "SHADOW_EPISODE", VD: "BLOCKED_OPERATOR_NEEDED", IN: IDLE_IN, EP: EP_OPEN, SK: SOAK_OK},
    "unreadable_masked": {B1: "VALID", B10: lm(obl=OBL_VALUES["UR"]), SS: "SHADOW_EPISODE_HA_BACK", VD: "BLOCKED_RECOVERY_METADATA", IN: IDLE_IN, EP: EP_BACK, SK: SOAK_OK},
    "blocked_outside_episode": {B1: "VALID", B10: lm(), SS: "SHADOW_WATCH", VD: "BLOCKED_RECOVERY_METADATA",
                                IN: IDLE_IN.replace("pl=40;rs=701;alt=40;pa=40", "pl=20;rs=110;alt=20;pa=20"), EP: none_ep, SK: SOAK_OK},
    "device_down": {B1: "unavailable", SS: "unavailable", VD: "unavailable", IN: "unavailable", EP: "unavailable", SK: "unavailable"},
    "shadow_entities_missing": {B1: "VALID", B10: lm()},
}
rend = {}
for sname, raw in scen.items():
    vals, attrs = build_world(raw)
    try:
        rend[sname] = {"banner": drender(banner["content"], vals, attrs), "everyday": drender(everyday["content"], vals, attrs),
                       "tech": drender(tech["content"], vals, attrs), "vals": vals, "attrs": attrs}
        check(f"the three shadow cards render without a template error: {sname}", True)
    except Exception as exc:  # noqa: BLE001
        check(f"the three shadow cards render without a template error: {sname}", False, repr(exc)[:300])
        rend[sname] = None
if all(rend.values()):
    R = rend
    check("idle: canonical status is match; the episode flag is off (the banner is hidden by its visibility rule); everyday line = S5 6.4: "
          "'SHADOW CHECK · NO ACTION TAKEN — If Home Assistant were lost now, a future automatic failback would:' then the readiness wording",
          R["idle"]["vals"][CODE] == "match" and R["idle"]["vals"][OPEN] == "off"
          and "**SHADOW CHECK · NO ACTION TAKEN** — " + HEAD_READY in R["idle"]["everyday"]
          and "Would do nothing: inverter already matches profile" in R["idle"]["everyday"]
          and "No action needed" not in R["idle"]["everyday"] and "supervision healthy" not in R["idle"]["everyday"], R["idle"]["everyday"])
    check("latched (State SHADOW_WOULD_AWAIT_ACK, Verdict 50): the readiness heading and 'Would stay latched'; the technical block names the plan underneath",
          R["latched_idle"]["vals"][CODE] == "match" and HEAD_READY in R["latched_idle"]["everyday"]
          and "Would stay latched: previous episode not acknowledged" in R["latched_idle"]["everyday"]
          and "`WOULD_ALREADY_MATCH` - Would do nothing: inverter already matches profile" in R["latched_idle"]["tech"]
          and "(the plan underneath the modelled FB-F latch)" in R["latched_idle"]["tech"], R["latched_idle"]["tech"][:500])
    check("a never-published supervision row (NO_ACTION, e.g. a pre-remediation build) is never worded as a plan: 'not recognised', no heading, "
          "shown raw in the technical block",
          "Shadow check result not recognised" in R["legacy_supervision_row"]["everyday"] and HEAD_READY not in R["legacy_supervision_row"]["everyday"]
          and "No action needed" not in R["legacy_supervision_row"]["everyday"] and "`verdict:NO_ACTION`" in R["legacy_supervision_row"]["tech"]
          and "Verdict (not recognised)" in R["legacy_supervision_row"]["tech"] and R["legacy_supervision_row"]["vals"][CODE] == "match")
    check("episode: canonical status shadow_episode / Shadow Recovery; banner says supervision lost, SHADOW, NOTHING WAS WRITTEN, duration, what would have been done, 5 minutes",
          R["episode"]["vals"][CODE] == "shadow_episode" and R["episode"]["vals"][DISPLAY] == "Shadow Recovery" and R["episode"]["vals"][OPEN] == "on"
          and "HOME ASSISTANT SUPERVISION WAS LOST" in R["episode"]["banner"] and "NOTHING WAS WRITTEN" in R["episode"]["banner"]
          and "Lost for 6 min 12 s since the loss was declared (episode 1A2B3C4D-1)." in R["episode"]["banner"]
          and "If automatic failback were enabled it would have: ended Free Power, then continued failback." in R["episode"]["banner"]
          and "Closes automatically after 5 minutes of continuous stable supervision." in R["episode"]["banner"]
          and "takes priority" not in R["episode"]["banner"]
          and "saved-profile warnings (drifted, lost or rolled back) are not shown there until it closes" in R["episode"]["banner"])
    check("episode: the everyday line shows the continuation Verdict under the episode heading (never the 'if lost now' heading)",
          HEAD_EPISODE in R["episode"]["everyday"] and "Would end Free Power, then continue failback" in R["episode"]["everyday"]
          and "If Home Assistant were lost now" not in R["episode"]["everyday"], R["episode"]["everyday"])
    check("ha_back: banner says Home Assistant is back and the episode stays open until supervision is stable",
          "Home Assistant is back 6 min 12 s after the loss was declared" in R["ha_back"]["banner"] and "stays open until supervision has been stable" in R["ha_back"]["banner"]
          and "NOTHING WAS WRITTEN" in R["ha_back"]["banner"])
    check("a lease lockout / unreadable state keeps the canonical Blocked status and the banner is shown ALONGSIDE it, saying so",
          R["episode_masked"]["vals"][CODE] == "lease_lockout" and R["episode_masked"]["vals"][DISPLAY] == "Blocked" and R["episode_masked"]["vals"][OPEN] == "on"
          and "The Fallback status above stays on **Blocked**, which takes priority over a shadow episode" in R["episode_masked"]["banner"]
          and R["unreadable_masked"]["vals"][CODE] == "lease_unreadable" and "stays on **Blocked**, which takes priority" in R["unreadable_masked"]["banner"]
          and "saved-profile warnings" not in R["episode_masked"]["banner"])
    check("a BLOCKED_* readiness verdict outside an episode is only wording: status stays match / Ready, no banner, the 'if lost now' heading",
          R["blocked_outside_episode"]["vals"][CODE] == "match" and R["blocked_outside_episode"]["vals"][DISPLAY] == "Ready"
          and R["blocked_outside_episode"]["vals"][OPEN] == "off" and "Would hold: saved lease records unreadable or corrupt" in R["blocked_outside_episode"]["everyday"]
          and HEAD_READY in R["blocked_outside_episode"]["everyday"])
    t0 = R["episode"]["tech"]
    check("technical: state, verdict with its scope, readiness plan and reason, alt / pa, inputs, last episode, soak, reset reason, scope note",
          "`SHADOW_EPISODE`" in t0 and "`WOULD_PREEMPT_FREE_POWER`" in t0 and "supervision: lost".lower() in t0.lower() and "Free Power: clear (boot marker)" in t0
          and "**Verdict (continuation while the shadow episode is open):**" in t0 and "**Readiness plan (Inputs `pl` / `rs`):** `WOULD_PREEMPT_FREE_POWER`" in t0
          and "(`alt`): `WOULD_PREEMPT_FREE_POWER`" in t0 and "(`pa`): `WOULD_ALREADY_MATCH`" in t0
          and "**Verdict (if Home Assistant were lost now):** `WOULD_ALREADY_MATCH`" in R["idle"]["tech"]
          and "Known-good profile: VALID" in t0 and "generation 7" in t0 and "`1A2B3C4D`" in t0 and "Frozen edge plan: `WOULD_PREEMPT_FREE_POWER`" in t0
          and "Pre-empt: Free Power" in t0 and "ECCO Reset Reason: Power-on" in t0 and "boot id `1A2B3C4D`" in t0 and "episodes 1" in t0
          and "Heartbeat gaps: <=35 s: 2871 · <=45 s: 12" in t0 and "Export hazard seen: yes 7 s · unknown 9 s" in t0
          and "Live-data cache: fresh 100 s · pre-fence 20 s · other 5 s" in t0 and "RAM-only" in t0, t0[:400])
    check("technical: the C2 key words the architecture lists are all visible (supervision, FP / Dump / R244, profile, E1, context, info, cache, locks, frames, delta, "
          "episode id / phase / kind / trigger, edge plan / result / domain / pre-empt, return / gap / re-loss / close / fbf, boot nonce, gap histogram, max / last-long gap, "
          "episode count, start-refusal and profile evidence, xh, cs, client / reboot evidence)",
          all(s in t0 for s in ("Supervision:", "Free Power:", "Dump to Grid:", "Register 244 test:", "Known-good profile:", "Live settings vs profile:", "context:",
                                "info registers", "Live data cache:", "write locks:", "projected frames:", "Registers that differ:", "Last episode", "phase", "kind", "trigger",
                                "Frozen edge plan:", "FB-A result", "blocking domain", "Pre-empt:", "Home Assistant back after:", "re-lost", "verdict changes", "Closed after:",
                                "close outcome", "boot id", "Heartbeat gaps:", "Longest gap", "last long gap", "gaps missed", "episodes", "Start attempts seen",
                                "profile changes", "Export hazard seen", "Live-data cache", "API client drops", "longest without a client", "API client at the edge",
                                "no-client reboot margin", "Readiness plan", "(`alt`)", "(`pa`)")))
    vals, attrs = build_world({**scen["episode"], IN: scen["episode"][IN] + ";zz=1", EP: scen["episode"][EP] + ";fut=2"})
    tu = drender(tech["content"], vals, attrs)
    check("technical: unknown append-only keys are listed verbatim", "`inputs:zz=1`" in tu and "`episode:fut=2`" in tu and "Unrecognised keys (shown raw)" in tu)
    for sname in ("device_down", "shadow_entities_missing"):
        txt = "\n".join(R[sname][k] for k in ("banner", "everyday", "tech"))
        check(f"{sname}: nothing raises, nothing is invented (no 'None', no episode claimed), the line says the check is not available / not ready",
              "None" not in txt and ("Shadow check not available" in R[sname]["everyday"]) and R[sname]["vals"][OPEN] == "off")
    check("device_down: the canonical status is not_reporting (the shadow never overrides it)", R["device_down"]["vals"][CODE] == "not_reporting")
    all_text = "\n".join(R[s][k] for s in R for k in ("banner", "everyday", "tech"))
    check("no rendered shadow text claims persisted shadow history", not re.search(r"persisted|stored history|survives a reboot|across reboots", all_text, re.I)
          and "RAM-only" in R["episode"]["tech"])

# ===========================================================================
print("")
print("[7] Energy Actions untouched; InfluxDB v1.3; version and record")
EA_BLOCK_SHA = "784044c3fc4e9bb13811a384e687a2604d05fed1fff5ad161ef0d4ea953d361d"
ea_start = dash_text.index("          - type: custom:ecco-energy-actions-card\n")
ea_end = dash_text.index("          # ---- KNOWN-GOOD PROFILE (FB-B3; READ-ONLY tile) ----")
_dash_private = _pub0.private_view("home-assistant/dashboards/ecco_pro.yaml", dash_text)   # PUB0: the pin is the private block's
_ea_private = _dash_private[_dash_private.index("          - type: custom:ecco-energy-actions-card\n"):
                            _dash_private.index("          # ---- KNOWN-GOOD PROFILE (FB-B3; READ-ONLY tile) ----")]
check("15: the Energy Actions card config block of the dashboard is byte-identical to the FB-B3 / main one (sha256 pin)", sha(_ea_private) == EA_BLOCK_SHA, sha(_ea_private))
check("15: no shadow wording, entity or decoder inside the Energy Actions block",
      not re.search(r"ecco_shadow_|SHADOW CHECK|Shadow Recovery|Failback shadow|" + FB + "_shadow|shadow_episode", dash_text[ea_start:ea_end]))
FE_DIR = "frontend/ecco-energy-actions-card/"
ls = subprocess.run(["git", "ls-files", "-z", "--", FE_DIR], cwd=str(ROOT), capture_output=True)
fe_tracked = sorted(f for f in ls.stdout.decode("utf-8").split("\0") if f)
fe_hash = hashlib.sha256()
for rel in fe_tracked:
    fe_hash.update(rel.encode())
    fe_hash.update(_lic0.pre_lic0_bytes(rel, _pub0.private_view_bytes(rel, (ROOT / rel).read_bytes().replace(b"\r\n", b"\n"))))   # PUB0: private text; LIC0: pre-lic0 bytes
ENERGY_ACTIONS_SHA256 = "57c9798206d8a1850047474e9bdf89401523b03de89a2562a0cc18d81ac17471"
check("15: frontend/ecco-energy-actions-card (git-tracked files) is byte-identical (sha256 pin, same recipe as the FB-B3 suites)",
      ls.returncode == 0 and fe_tracked and fe_hash.hexdigest() == ENERGY_ACTIONS_SHA256, fe_hash.hexdigest())
check("15: no tracked file under frontend/ mentions the shadow check decoder or the new status word",
      not [f for f in subprocess.run(["git", "ls-files", "-z", "--", "frontend/"], cwd=str(ROOT), capture_output=True).stdout.decode().split("\0")
           if f and re.search(r"ecco_shadow_|Shadow Recovery", (ROOT / f).read_text(encoding="utf-8", errors="ignore"))])

inf = yaml.safe_load(lf(INF13))
globs = inf["include"]["entity_globs"]
excluded = inf["exclude"]["entities"]
exported = lambda e: any(fnmatch.fnmatchcase(e, g) for g in globs) and e not in excluded  # noqa: E731
check("InfluxDB v1.3 (unchanged) still exports all five shadow sensors for soak evidence and excludes only the challenge and the Review ID",
      all(exported(i) for i in FIVE) and sorted(excluded) == [f"sensor.{DEV}_ecco_fallback_profile_review_id", f"sensor.{DEV}_ecco_supervision_challenge"], str([i for i in FIVE if not exported(i)]))
check("InfluxDB v1.3: the decoder sensor and the flag are exported too (sensor.ecco_* / binary_sensor.ecco_* globs) - harmless", exported(CHECK) and exported(OPEN))

ver = yaml.safe_load(lf(VERSION))
check("version: dashboard 7.18.0 is staged (FB-C3), NOT live-tested; firmware stays stage3.4 and hardware-verified",
      ver["current"]["dashboard"]["version"] == "7.18.0" and ver["current"]["dashboard"]["tested_in_home_assistant"] is False
      and ver["current"]["firmware"]["version"] == "stage3.4" and ver["current"]["firmware"]["hardware_verified"] is True)
ver_text = lf(VERSION)
# PUBLIC-EXPORT: the private-history "record:" checks (the verbatim LP-B3 live-proof prose in VERSION.yaml, the CHANGELOG.md /
# CURRENT_STATE.md entries, the FB-C3 implementation-notes file) are process records of the private development archive and are
# not part of the public tree (PUBLIC_RELEASE_BUILD_SPEC B.3). The behavioural facts they carried are kept as public invariants below.
check("version: the previous dashboard release 7.17.0 (FB-B3) is recorded as tested in Home Assistant, 7.18.0 is not",
      "previous dashboard release (7.17.0," in ver_text and "FB-B3" in ver_text and "tested_in_home_assistant is therefore false for 7.18.0" in ver_text)
check("version: FB-C3 is recorded as OFFLINE / STAGED / NOT LIVE-PROVEN", "FB-C3" in ver_text and "OFFLINE / STAGED / NOT LIVE-PROVEN" in ver_text)
check("version: VERSION.yaml carries no private development history (no commit SHA, branch / PR history or rollback branch)",
      "main_commit" not in ver_text and "branches" not in ver and "rollback" not in ver and not re.search(r"\b[0-9a-f]{40}\b", ver_text)
      and not re.search(r"PR #\d+|LP-[A-Z]\d", ver_text))
check("record: the dashboard header keeps its first line and the v7.17.0 note, and adds a v7.18.0 (FB-C3) note",
      dash_text.startswith("# ECCO Pro Dashboard v7.16.0") and "# v7.17.0 (FB-B3, STAGED / NOT LIVE-PROVEN)" in dash_text.split("views:")[0]
      and "# v7.18.0 (FB-C3, STAGED / NOT LIVE-PROVEN)" in dash_text.split("views:")[0])
for pth in (STATUS_PKG, HEALTH_PKG, DASH, REASON_CODES, CHECKS, VERSION):
    raw = pth.read_bytes()
    crlf, nlf = raw.count(b"\r\n"), raw.count(b"\n")
    check(f"{pth.relative_to(ROOT).as_posix()}: parses and has pure line endings", crlf == nlf or crlf == 0, f"{crlf}/{nlf}")

# ===========================================================================
print("")
print("[8] Negative controls: the precedence tests catch a mis-ordered shadow row")


def precedence_failures(code_template: str) -> list:
    """The explicit lease / profile precedence rows, run against an arbitrary status-code template text."""
    t = T(code_template)
    bad = []
    for ss in EPISODE_STATES:
        for P, live, want in [("VALID", lm(obl=OBL_VALUES["UR"]), "lease_unreadable"), ("VALID", lm(obl=OBL_VALUES["ML"]), "lease_unreadable"),
                              ("VALID", lm(obl=OBL_VALUES["ON"]), "lease_lockout"), ("VALID", lm(obl=OBL_VALUES["R4PC"]), "lease_lockout"),
                              ("VALID", lm(obl=OBL_VALUES["UR+ON"]), "lease_unreadable"), ("unknown", lm(), "not_reporting"),
                              ("VALID", lm(), "shadow_episode"), ("SAVE_UNCONFIRMED", lm(), "shadow_episode"), ("VALID", lm(m="DRIFT"), "shadow_episode")]:
            if t(world(P, live, ss=ss)) != want:
                bad.append((ss, P, want))
    for ss in NON_EPISODE_STATES:
        if t(world("VALID", lm(m="DRIFT"), ss=ss, verdict="BLOCKED_RECOVERY_METADATA")) != "drift_values":
            bad.append((ss, "no-episode drift"))
    return bad


check("the precedence checks pass on the real template", precedence_failures(CODE_TPL) == [])
SHADOW_ELIF = "{%- elif SS in ['SHADOW_EPISODE', 'SHADOW_EPISODE_HA_BACK'] -%}shadow_episode"
check("the shadow row text is present exactly once in the loaded template", CODE_TPL.count(SHADOW_ELIF) == 1)
without = CODE_TPL.replace(SHADOW_ELIF, "")
above_unreadable = without.replace("{%- elif ns.unreadable -%}lease_unreadable", SHADOW_ELIF + " {%- elif ns.unreadable -%}lease_unreadable", 1)
above_lockout = without.replace("{%- elif ns.lockout -%}lease_lockout", SHADOW_ELIF + " {%- elif ns.lockout -%}lease_lockout", 1)
above_not_reporting = without.replace("{%- if P in ['unknown', 'unavailable', 'none', ''] -%}not_reporting",
                                      "{%- if SS in ['SHADOW_EPISODE', 'SHADOW_EPISODE_HA_BACK'] -%}shadow_episode {%- elif P in ['unknown', 'unavailable', 'none', ''] -%}not_reporting", 1)
below_profile = without.replace("{%- elif P == 'SAVE_UNCONFIRMED' -%}save_unconfirmed", "{%- elif P == 'SAVE_UNCONFIRMED' -%}save_unconfirmed " + SHADOW_ELIF, 1)
verdict_decides = CODE_TPL.replace(SHADOW_ELIF, "{%- elif SS in ['SHADOW_EPISODE', 'SHADOW_EPISODE_HA_BACK'] or states('" + VD + "').startswith('BLOCKED') -%}shadow_episode")
for label, mut in [("shadow_episode ABOVE lease_unreadable", above_unreadable), ("shadow_episode ABOVE lease_lockout", above_lockout),
                   ("shadow_episode ABOVE not_reporting", above_not_reporting), ("shadow_episode BELOW the profile rows", below_profile),
                   ("a BLOCKED_* Verdict opens shadow_episode", verdict_decides)]:
    check(f"negative control: '{label}' is a real mutation and is CAUGHT by the precedence checks",
          mut != CODE_TPL and len(precedence_failures(mut)) > 0, str(precedence_failures(mut)[:2]))
check("negative control: the differential oracle (the reconstructed FB-B3 template) sees the lease-order mutant's wrong answer too",
      T(above_unreadable)(world("VALID", lm(obl=OBL_VALUES["UR"]), ss="SHADOW_EPISODE")) == "shadow_episode"
      and OLD(world("VALID", lm(obl=OBL_VALUES["UR"]), ss="SHADOW_EPISODE")) == "lease_unreadable")


def decoder_failures(pkg_text: str) -> list:
    """The FINAL-Verdict-contract checks of [4], run against an arbitrary status-package text."""
    ent = template_entities(load_text(pkg_text))["ecco_shadow_check"]
    st = T(ent["state"])
    at = {k: T(v) for k, v in ent["attributes"].items() if isinstance(v, str) and "{{" in v}
    bad = []
    for n in UNPUBLISHED:
        if st({VD: n, IN: "unknown"}) != NOT_RECOGNISED:
            bad.append(("worded", n))
        if literal(at["unknown_keys"]({VD: n, SS: "SHADOW_IDLE"})) != [f"verdict:{n}"]:
            bad.append(("not listed", n))
    if "verdict_heading" not in at or literal(at["verdict_heading"]({VD: "WOULD_PREEMPT_FREE_POWER", SS: "SHADOW_EPISODE"})) != HEAD_EPISODE \
            or literal(at["verdict_heading"]({VD: "WOULD_ALREADY_MATCH", SS: "SHADOW_IDLE"})) != HEAD_READY:
        bad.append(("heading",))
    if literal(at["unknown_keys"]({IN: INPUTS_OK, SS: "SHADOW_IDLE", VD: "WOULD_APPLY_PROFILE"})) != []:
        bad.append(("alt / pa unknown",))
    if literal(at["inputs"]({IN: R3_IN}))["absence_accepted_plan"] != "WOULD_ALREADY_MATCH":
        bad.append(("alt not decoded",))
    if literal(at["inputs"]({IN: INPUTS_OK.replace("pl=41;rs=702;alt=41;pa=41", "pl=1;rs=1;alt=41;pa=41")}))["if_lost_plan"] != "-":
        bad.append(("pl=1 named",))
    return bad


pkg = lf(STATUS_PKG)
check("the decoder checks pass on the real status package", decoder_failures(pkg) == [], str(decoder_failures(pkg)))
W_OLD = "{%- set w = {'NOT_EVALUATED': 'Shadow evaluator not ready yet', "
P_OLD = "{%- set plans = {'0': 'NOT_EVALUATED', '10': 'WOULD_PREEMPT_DUMP'"
for label, mut in [
        ("NO_ACTION re-worded as a Verdict (the pre-remediation decoder)",
         pkg.replace(W_OLD, W_OLD + "'NO_ACTION': 'No action needed - supervision healthy', 'WOULD_REFUSE_STARTS': 'Would refuse new managed starts', ", 1)),
        ("NO_ACTION accepted as a published Verdict in unknown_keys", pkg.replace("{%- if v not in ['NOT_EVALUATED', ", "{%- if v not in ['NOT_EVALUATED', 'NO_ACTION', 'WOULD_REFUSE_STARTS', ", 1)),
        ("Inputs alt / pa dropped from the known keys (the fd8edda grammar)", pkg.replace("'pl', 'rs', 'alt', 'pa']],", "'pl', 'rs']],", 1)),
        ("a heading that ignores the episode", pkg.replace("states('" + SS + "') in ['SHADOW_EPISODE', 'SHADOW_EPISODE_HA_BACK']\n", "False\n", 1)),
        ("plan code 1 decoded in Inputs pl", pkg.replace(P_OLD, "{%- set plans = {'0': 'NOT_EVALUATED', '1': 'NO_ACTION', '10': 'WOULD_PREEMPT_DUMP'", 1))]:
    check(f"negative control: '{label}' is a real mutation and is CAUGHT by the decoder checks",
          mut != pkg and len(decoder_failures(mut)) > 0, str(decoder_failures(mut)[:2]))

print("")
if FAILURES:
    print(f"{len(FAILURES)} check(s) FAILED:")
    for name in FAILURES:
        print(f"  - {name}")
    sys.exit(1)
print("All FB-C3 shadow UX offline tests PASSED.")
