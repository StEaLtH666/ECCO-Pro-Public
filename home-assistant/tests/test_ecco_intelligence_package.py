#!/usr/bin/env python3
"""Offline behaviour suite for home-assistant/packages/ecco_intelligence.yaml (the ECCO Intelligence presentation package:
the pause helper, the dead-man watchdog binary_sensor.ecco_intel_watchdog_fresh and three notification-only alerts), for the
dashboard registration package home-assistant/packages/ecco_intelligence_dashboard.yaml, and for the post-export entry isp1
that lists both, the preferences package, the standalone dashboard and the card in VERSION.yaml and deployment/ha-manifest.yaml.

The REAL package YAML is driven with home-assistant/tests/_ha_script_sim.py (imported read-only, never edited) on a virtual
clock: its automations, triggers, conditions and service calls run in the simulator. Home Assistant behaviours the simulator
does not model are modelled HERE, in this file only, and each is stated where it is defined:
  * the watchdog is a state-based template binary_sensor: it is re-rendered on every state change and at every minute
    boundary (Home Assistant re-renders a template that uses now() once a minute) and written as on / off, so its
    last_changed is real (the simulator renders template SENSORS only, on read, without a last_changed). Before its first
    render Home Assistant may show its last saved state (a restored state); the first render replaces it;
  * as_timestamp() parses ISO-8601 text with an offset (the status entity's generated_at / valid_until), as Home Assistant's
    dt_util.parse_datetime does; the simulator's own as_timestamp reads only its local "YYYY-MM-DD HH:MM:SS" form;
  * a `state` condition on an entity that does not exist raises in Home Assistant (ConditionErrorMessage "unknown entity"):
    the automation logs "Error evaluating condition" and does not run. The simulator reads such an entity as `unknown`
    silently, so this suite records the error as a warning (the L3 finding P3).

  [1] static      the package's keys, its two entities (ids = the contract's package entities), no `initial:`, no recorder
                  block, three automations whose keys are a fixed allowlist and whose `actions` are exactly ONE node with the keys
                  {action, data}: persistent_notification.create with a fixed ecco_intel_ id; no dismiss, no target, no other
                  entity referenced (the scene and event domains included); each automation's triggers and conditions pinned
                  exactly (the two fault alerts re-check their fault at Home Assistant's start, by a template condition); the
                  PROPOSED thresholds pinned; no automation spells the mode word
  [2] watchdog    over the six golden contract fixtures (intelligence/tests/fixtures/advisory_contract, read in place), at the
                  exact PROPOSED boundaries (the runbook's G8 rules: a computed status needs a future valid_until and a
                  generated_at no older than 1200 s; STARTING bounded by 1200 s; PAUSED fresh while the pause helper is on,
                  plus 130 s), and against an independent oracle over seeded random status attributes, status ages and pause
                  helper states
  [3] alerts      healthy publishing is silent (72 simulated hours at three cadences); a stopped publisher alerts once after the
                  watchdog has been off for 30 min; the pause silences it (also while the integration is down), PAUSED stays
                  fresh for hours while the helper is on, an unpause hands over to STARTING without the watchdog turning off,
                  and an unpause gives the next cycle 30 min before the stale alert; SELF_TEST_FAILED and a contract mismatch (a
                  blank integration_version included) alert once each and suppress the stale alert, also when the fault is
                  ALREADY published as Home Assistant starts; a good status at the start raises nothing; a start with no status
                  entity raises nothing and logs no condition error (P3); a restored watchdog `on` is replaced by the first
                  render; a wrong mode, an unavailable integration, a start-up that never finishes and a watchdog stuck unknown
                  alert as stale; an absent integration never alerts; clock-ahead and malformed timestamps are not fresh
  [4] writes      across every scenario the only service ever called is persistent_notification.create with one of the three
                  ecco_intel_ ids, and nothing writes any entity (the pause helper changes only when the test, standing in for
                  the owner, toggles it)
  [5] mutation    in-memory mutants of the package are each killed by the scenarios above
  [6] dashboard   the standalone dashboard's markdown fallback, rendered with the same stand-ins over the golden fixtures, shows
                  the status, the open decision labels, the watchdog and the pause and no figure; an unrecognised output shows
                  only "Intelligence output not recognised"; a missing status "not publishing"
  [7] derivation  (T1) WATCHDOG_MAX_AGE_S and RESUME_GRACE_S are derived from the integration's and the engine's PROPOSED
                  constants exactly as the install runbook's gate G8 states them, and the runbook states this package's numbers
  [8] registration (T4) ecco_intelligence_dashboard.yaml: exactly one YAML-mode dashboards entry, its keys pinned, its filename
                  the manifest's destination of the standalone dashboard, administrators only, nothing else
  [9] isp1        (T5, T6) the post-export declaration through registry/tests/_pex.py: VERSION.yaml's intelligence block and the
                  manifest's stanzas exact, every path present, the version equal to the integration's and the card's, no
                  custom_components source; isp1 after ovw3, its frozen and chain-pinned edits, added files and fingerprint

Writes nothing; no Home Assistant, no network, no hardware. It does not prove the templates on a live Home Assistant.
"""

from __future__ import annotations

import json
import math
import random
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT))
import _ha_script_sim as S  # noqa: E402
from custom_components.ecco_intelligence import const as C  # noqa: E402  (pure: no homeassistant import)
from intelligence import advisory_contract as ac  # noqa: E402
from intelligence import daily_plan as dp  # noqa: E402

PKG_REL = "home-assistant/packages/ecco_intelligence.yaml"
REG_REL = "home-assistant/packages/ecco_intelligence_dashboard.yaml"
PREFS_REL = "home-assistant/packages/ecco_intelligence_prefs.yaml"
DASH_REL = "home-assistant/dashboards/ecco_intelligence.yaml"
CARD_REL = "frontend/ecco-intelligence-card/ecco-intelligence-card.js"
RUNBOOK_REL = "docs/intelligence/INTELLIGENCE_SHADOW_INSTALL_RUNBOOK.md"
PKG_TEXT = (ROOT / PKG_REL).read_text(encoding="utf-8")
FIXTURES = ROOT / "intelligence" / "tests" / "fixtures" / "advisory_contract"
FIXTURE_NAMES = ("all_open_blocked", "synthetic_ok", "stale", "paused", "self_test_failed", "starting")

STATUS = ac.ENTITY_IDS["status"]
PAUSE = ac.ENTITY_IDS["paused"]
WD = ac.ENTITY_IDS["watchdog_fresh"]
OTHER = "sensor.example_unrelated"     # Home Assistant always has some sensor; the simulator needs one for states.sensor.<id>
OTHER_BOOL = "input_boolean.example_unrelated"   # likewise for states.input_boolean.<id> when the pause helper is absent
NOTE_IDS = ("ecco_intel_watchdog_stale", "ecco_intel_self_test_failed", "ecco_intel_contract_mismatch")
STALE_ID, SELF_ID, MISMATCH_ID = NOTE_IDS
# the PROPOSED thresholds (engineering defaults, not owner decisions), pinned; [7] derives the first two
WATCHDOG_MAX_AGE_S, RESUME_GRACE_S, CLOCK_AHEAD_S, ALERT_AFTER_S = 1200, 130, 120, 1800
FRESH_STATUSES = tuple(s for s in ac.SystemStatus.ALL if s not in (ac.SystemStatus.STALE, ac.SystemStatus.SELF_TEST_FAILED))
COMPUTED = ("OK", "NO_ADVICE", "BLOCKED", "INSUFFICIENT_DATA")
PUBLISH_EVERY_S, VALID_FOR_S = 600, 900   # a refresh every 10 min with the engine's 900 s validity ceiling (slower than real)
T0 = datetime(2030, 1, 15, 21, 0, tzinfo=timezone.utc).timestamp()   # fictional, like the fixtures
HOUR = 3600.0

FAILURES: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  PASS  {name}")
    else:
        FAILURES.append(name)
        print(f"  FAIL  {name}" + (f" - {detail}" if detail else ""))


def code_text(text: str) -> str:
    """The text without whole-line `#` comments (the header documents prohibitions)."""
    return "\n".join(line for line in text.splitlines() if not line.strip().startswith("#"))


def walk(node):
    yield node
    if isinstance(node, dict):
        for v in node.values():
            yield from walk(v)
    elif isinstance(node, list):
        for v in node:
            yield from walk(v)


def iso(t: float) -> str:
    return datetime.fromtimestamp(t, timezone.utc).isoformat()


def next_minute(t: float) -> float:
    """The first minute boundary strictly after t (the watchdog's next timed render)."""
    return math.floor(t / 60) * 60 + 60


# ---------------------------------------------------------------------------------------------------------------------
# Home Assistant behaviour the simulator does not model (see the module docstring)
# ---------------------------------------------------------------------------------------------------------------------
_NO_DEFAULT = object()


class IntelWorld(S.World):
    """The simulator's World with Home Assistant's as_timestamp: an aware datetime, or text that dt_util.parse_datetime reads
    (ISO-8601, an offset included); anything else (a number, None, other text) is not a date/time and gives the default, or
    an error without one."""

    def as_timestamp(self, value, default=_NO_DEFAULT):
        try:
            if isinstance(value, datetime):
                return value.timestamp()
            if isinstance(value, str):
                d = datetime.fromisoformat(value.strip())
                return (d if d.tzinfo is not None else d.replace(tzinfo=S.LOCAL)).timestamp()
            raise ValueError(f"not a date/time: {value!r}")
        except (TypeError, ValueError):
            if default is _NO_DEFAULT:
                raise S.SimError(f"as_timestamp could not parse {value!r} and no default was given")
            return default


class IntelHA(S.HA):
    """The simulator's HA with Home Assistant's `state` condition on an entity that does not exist: Home Assistant raises
    ConditionErrorMessage('unknown entity ...'); the automation logs 'Error evaluating condition' and does not run."""

    def cond(self, conds, v) -> bool:
        for c in ([conds] if isinstance(conds, dict) else conds):
            if c.get("condition") == "state":
                ents = c["entity_id"] if isinstance(c["entity_id"], list) else [c["entity_id"]]
                missing = [e for e in ents if e not in self.w.states]
                if missing:
                    self.w.warnings.append(f"{self.w.t:.3f} Error evaluating condition: unknown entity {missing[0]}")
                    return False
        return super().cond(conds, v)


def as_boolean(text: str) -> bool:
    """Home Assistant's result_as_boolean for a template binary_sensor's rendered state."""
    s = text.strip().lower()
    if s in ("true", "yes", "on", "enable"):
        return True
    try:
        return float(s) != 0
    except ValueError:
        return False


class Watchdog:
    """The state-based template binary_sensor: re-rendered on every state change and at every minute boundary, written on / off."""

    def __init__(self, w: IntelWorld, template: str):
        self.w, self.tpl = w, template
        self.renders = 0
        w.listeners.insert(0, self.update)        # before the automations poll, as HA updates the entity before its listeners
        self.update("setup")                      # the first render (Home Assistant's start)

    def update(self, _kind):
        self.renders += 1
        self.w.set(WD, "on" if as_boolean(self.w.render(self.tpl)) else "off")


def load_pkg(text: str = PKG_TEXT) -> dict:
    return yaml.safe_load(text)


PKG = load_pkg()


def watchdog_template(pkg: dict) -> str:
    return pkg["template"][0]["binary_sensor"][0]["state"]


class Rig:
    """One Home Assistant: the world, the package's automations and helper (simulator) and the watchdog (modelled here)."""

    def __init__(self, *, t0: float = T0, pkg_text: str = PKG_TEXT, status: tuple | None = None, paused: str | None = "off",
                 restored_wd: str | None = None):
        pkg = load_pkg(pkg_text)
        self.w = IntelWorld(t0)
        self.w.set(OTHER, "1")
        self.w.set(OTHER_BOOL, "off")
        self.owner_toggles: list[tuple[float, str]] = []
        if paused is not None:
            self.w.set(PAUSE, paused)             # a restored helper (no `initial:`)
        if status is not None:
            self.w.set(STATUS, status[0], status[1])
        if restored_wd is not None:
            self.w.set(WD, restored_wd)           # Home Assistant's last saved watchdog state, shown until the first render
        self.ha = IntelHA(self.w, {k: v for k, v in pkg.items() if k != "template"})
        self.wd = Watchdog(self.w, watchdog_template(pkg))
        self.ha.start()

    # --- the integration, as a publisher of sensor.ecco_intel_status ----------------------------------------------------
    def publish(self, state: str = "OK", **over) -> None:
        self.w.set(STATUS, state, status_attrs(self.w.t, **over))

    def publish_every(self, state: str = "OK", *, until: float | None = None, every: float = PUBLISH_EVERY_S, **over) -> None:
        """Publish now and every `every` seconds until `until` (exclusive)."""
        def tick():
            if until is not None and self.w.t >= until:
                return
            self.publish(state, **over)
            self.w.after(every, tick)
        self.w.after(0, tick)

    # --- the owner ----------------------------------------------------------------------------------------------------
    def toggle_pause(self, state: str) -> None:
        self.owner_toggles.append((self.w.t, state))
        self.w.set(PAUSE, state)

    def run_until(self, t: float) -> None:
        self.w.run_until(t)

    def notes(self, nid: str | None = None) -> list[tuple[float, str]]:
        return [(t, d.get("notification_id")) for t, svc, _e, d in self.w.service_log
                if svc == "persistent_notification.create" and (nid is None or d.get("notification_id") == nid)]

    def wd_at(self, t: float) -> str:
        self.run_until(t)
        return self.w.state(WD)

    def wd_changes(self, after: float = -math.inf) -> list[tuple[float, str]]:
        return [(t, s) for t, e, s in self.w.history if e == WD and t >= after]


BASE_ATTRS = json.loads((FIXTURES / "synthetic_ok.json").read_text(encoding="utf-8"))["entities"][STATUS]["recorded"]


def status_attrs(t: float, *, valid_for: float | None = VALID_FOR_S, gen_offset: float = 0.0, drop=(), **over) -> dict:
    a = dict(BASE_ATTRS)
    a.update(generated_at=iso(t + gen_offset), valid_until=None if valid_for is None else iso(t + gen_offset + valid_for),
             next_run_at=iso(t + gen_offset + PUBLISH_EVERY_S))
    a.update(over)
    for k in drop:
        a.pop(k, None)
    return a


ALL_RIGS: list[Rig] = []


def rig(**kw) -> Rig:
    r = Rig(**kw)
    ALL_RIGS.append(r)
    return r


# =====================================================================================================================
print("[1] static: keys, entities, actions, ids, thresholds")
# =====================================================================================================================
code = code_text(PKG_TEXT)
check("the package parses and has exactly the keys input_boolean, template and automation", set(PKG) == {"input_boolean", "template", "automation"},
      str(sorted(PKG)))
check("exactly one helper: input_boolean.ecco_intel_paused (the contract's pause entity) with a name and icon, no `initial:`",
      list(PKG["input_boolean"]) == [ac.object_id(PAUSE)] and set(PKG["input_boolean"][ac.object_id(PAUSE)]) == {"name", "icon"}
      and not re.search(r"^\s*initial\s*:", code, re.M))
tpl_blocks = PKG["template"]
wd_cfg = tpl_blocks[0]["binary_sensor"][0] if (len(tpl_blocks) == 1 and list(tpl_blocks[0]) == ["binary_sensor"]
                                              and len(tpl_blocks[0]["binary_sensor"]) == 1) else {}
check("exactly one template entity: the watchdog binary_sensor, unique_id = object id of the contract's watchdog entity",
      wd_cfg.get("unique_id") == ac.object_id(WD) and wd_cfg.get("name", "").lower().replace(" ", "_") == ac.object_id(WD)
      and set(wd_cfg) == {"name", "unique_id", "icon", "state"}, str(wd_cfg.keys()))
check("no recorder block anywhere (key or line)", not any(isinstance(n, dict) and "recorder" in n for n in walk(PKG))
      and not re.search(r"^\s*recorder\s*:", code, re.M))
autos = PKG["automation"]
check("three automations with the fixed ids", [a.get("id") for a in autos] == ["ecco_intel_alert_watchdog_stale", "ecco_intel_alert_self_test_failed",
                                                                                "ecco_intel_alert_contract_mismatch"])
AUTO_KEYS = {"id", "alias", "description", "mode", "max_exceeded", "triggers", "actions"}
check("every automation's keys are exactly the fixed allowlist (conditions only on the two fault alerts)",
      [set(a) for a in autos] == [AUTO_KEYS, AUTO_KEYS | {"conditions"}, AUTO_KEYS | {"conditions"}], str([sorted(a) for a in autos]))
check("each automation's `actions` is exactly ONE node with the keys exactly {action, data} (no event fire, scene, delay, "
      "variables or any other step, whatever its key)",
      all(isinstance(a.get("actions"), list) and len(a["actions"]) == 1 and isinstance(a["actions"][0], dict)
          and set(a["actions"][0]) == {"action", "data"} for a in autos), str([a.get("actions") for a in autos]))
calls = [n for a in autos for n in walk(a.get("actions")) if isinstance(n, dict) and ("action" in n or "service" in n)]
check("every action is persistent_notification.create (no other service, no `service:` form), one per automation",
      len(calls) == 3 and all(n.get("action") == "persistent_notification.create" and "service" not in n for n in calls))
check("each create has a fixed notification_id starting ecco_intel_ (one of the three), a fixed title and message, and no target",
      [n["data"]["notification_id"] for n in calls] == list(NOTE_IDS)
      and all(set(n) == {"action", "data"} and set(n["data"]) == {"notification_id", "title", "message"}
              and "{" not in n["data"]["title"] + n["data"]["message"] for n in calls))
check("no dismiss / dismiss_all and no other service domain anywhere in the package code",
      "dismiss" not in code and not re.search(r"\b(?:script|switch|button|number|select|input_\w+|esphome|homeassistant|notify|"
                                               r"recorder|logbook|modbus\w*)\.[a-z_]+\s*$", "\n".join(
                                                   str(n.get("action")) for n in calls), re.M))
START = {"trigger": "homeassistant", "event": "start"}
SELF_COND = [{"condition": "template", "value_template": "{{ is_state('sensor.ecco_intel_status', 'SELF_TEST_FAILED') }}"}]
_t0, _t1, _t2 = (a.get("triggers") or [] for a in autos)
check("the stale alert: exactly one template trigger (keys {trigger, value_template}) and no condition",
      len(_t0) == 1 and set(_t0[0]) == {"trigger", "value_template"} and _t0[0]["trigger"] == "template", str(_t0))
check("the self-test alert: the state trigger to SELF_TEST_FAILED plus the Home Assistant start trigger, and ONE TEMPLATE condition "
      "that re-checks SELF_TEST_FAILED with is_state (a start with any other status, or with no status entity, raises nothing and "
      "logs no condition error: P3)",
      _t1 == [{"trigger": "state", "entity_id": STATUS, "to": "SELF_TEST_FAILED"}, START] and autos[1].get("conditions") == SELF_COND,
      str((_t1, autos[1].get("conditions"))))
check("no `state` condition anywhere in the package (a state condition on a missing entity is an error in Home Assistant)",
      not [n for n in walk(PKG) if isinstance(n, dict) and n.get("condition") == "state"])
check("the mismatch alert: its template trigger plus the Home Assistant start trigger, and one template condition that is "
      "exactly the trigger's template (the start re-checks the same fault)",
      len(_t2) == 2 and set(_t2[0]) == {"trigger", "value_template"} and _t2[0]["trigger"] == "template" and _t2[1] == START
      and autos[2].get("conditions") == [{"condition": "template", "value_template": _t2[0]["value_template"]}], str(_t2))
check("modes single with max_exceeded silent", all(a.get("mode") == "single" and a.get("max_exceeded") == "silent" for a in autos))
ids_in_code = set(re.findall(r"\b(?:sensor|binary_sensor|input_boolean|input_number|input_text|input_select|input_datetime|input_button|"
                             r"switch|button|number|select|script|automation|scene|event|light|cover|climate|lock|fan|siren|valve|"
                             r"media_player|water_heater|timer|counter|text|date|time|datetime|notify|esphome)\.[a-z0-9_]+", code))
check("the package references only the status entity, the pause helper and the watchdog (no dongle or other entity)",
      ids_in_code == {STATUS, PAUSE, WD}, str(sorted(ids_in_code)))
check("no automation spells the mode word (the shadow-check UX suite's rule over every package automation)",
      not [a["id"] for a in autos if "shadow" in yaml.dump(a).lower()])
wt = watchdog_template(PKG)
wt1 = re.sub(r"\s+", " ", wt)
check("the watchdog checks the contract version, the mode, applies_nothing and a non-blank (trimmed) integration_version",
      f"'{ac.CONTRACT_VERSION}'" in wt and "state_attr(s, 'mode') == 'SHADOW'" in wt and "'applies_nothing') is sameas true" in wt
      and "iv is string and (iv | trim | length) > 0" in wt)
check("every integration_version test in the package and the dashboard trims (a version of spaces only is blank)",
      PKG_TEXT.count("(iv | trim | length) > 0") == 4 and "(iv | length)" not in PKG_TEXT
      and "(iv | trim | length) > 0" in (ROOT / DASH_REL).read_text(encoding="utf-8")
      and "(iv | length)" not in (ROOT / DASH_REL).read_text(encoding="utf-8"))
check("G8, computed statuses: a parseable valid_until is required (only STARTING and PAUSED may carry none) and still in the future",
      "and (st in ['STARTING', 'PAUSED'] or vt is not none)" in wt1 and "and (v is none or (vt is not none and t <= vt))" in wt1)
check("G8, the age bound: generated_at no older than 1200 s for every status but PAUSED, and no more than 120 s ahead",
      "and (st == 'PAUSED' or (t - gt) <= 1200)" in wt1 and "and gt is not none and (t - gt) >= -120" in wt1)
check("G8, STARTING: bounded by the status entity's last_changed with the same 1200 s",
      "(st != 'STARTING' or (t - as_timestamp(states.sensor.ecco_intel_status.last_changed)) <= 1200)" in wt1, wt1[-400:])
check("G8, PAUSED: fresh only while the pause helper is on, or within 130 s of its last change (and never without the helper)",
      "(st != 'PAUSED' or (p is not none and (p.state == 'on' or (t - as_timestamp(p.last_changed)) <= 130)))" in wt1
      and "{%- set p = states.input_boolean.ecco_intel_paused -%}" in wt, wt1[-400:])
_st = autos[0]["triggers"][0]["value_template"]
check("the stale alert: the watchdog not-on (off or unknown) for 1800 s, and the pause not on and unchanged for 1800 s",
      "w is not none and w.state != 'on'" in _st and "(t - as_timestamp(w.last_changed)) >= 1800" in _st
      and "(p is none or (t - as_timestamp(p.last_changed)) >= 1800)" in _st
      and "not is_state('input_boolean.ecco_intel_paused', 'on')" in _st)
_fresh_m = re.search(r"\{\{ st in \[([^\]]*)\]", wt)
_fresh_list = re.findall(r"'([A-Z_]+)'", _fresh_m.group(1)) if _fresh_m else []
check("the watchdog's fresh statuses are exactly the contract statuses other than STALE and SELF_TEST_FAILED",
      len(_fresh_list) == len(set(_fresh_list)) and set(_fresh_list) == set(FRESH_STATUSES), str(_fresh_list))
check("the PROPOSED thresholds are pinned: 1200 s, 130 s and 120 s in the watchdog, 1800 s in the stale alert, each labelled PROPOSED in "
      "the header",
      wt1.count("<= 1200)") == 2 and wt1.count("<= 130)") == 1 and "(t - gt) >= -120" in wt
      and ">= 1800" in autos[0]["triggers"][0]["value_template"]
      and all(re.search(rf"^#\s+{n}\s+=\s+{v}\s+PROPOSED", PKG_TEXT, re.M) for n, v in
              (("WATCHDOG_MAX_AGE_S", WATCHDOG_MAX_AGE_S), ("RESUME_GRACE_S", RESUME_GRACE_S), ("CLOCK_AHEAD_S", CLOCK_AHEAD_S),
               ("ALERT_AFTER_S", ALERT_AFTER_S))))
check("no superseded threshold remains (the reviewed 2700 s, 45 min and source-only wording)",
      "2700" not in PKG_TEXT and "45 min" not in PKG_TEXT and "It is source only" not in PKG_TEXT)
check("the contract mismatch and stale alerts use the contract version literal", all(f"'{ac.CONTRACT_VERSION}'" in a["triggers"][0]["value_template"]
                                                                                   for a in (autos[0], autos[2])))
FB = "fall" + "back"
BANNED = ["ecco_" + FB, FB.upper() + "_PROFILE", "FAIL" + "BACK_STATE", "ecco_" + "fail" + "back", "ecco_" + "shadow_",
          "Shadow " + "Recovery", "fail" + "back_shadow", "ecco_clock_" + "dongle", "ecco-flow-" + "3d-card",
          "input_select.ecco_" + "automation_mode", "binary_sensor.ecco_" + "automatic_writes_armed", "octo" + "pus"]
_reg_text = (ROOT / REG_REL).read_text(encoding="utf-8")
check("no reserved / device-slug / tariff / vestigial / 3D-card token in the package, the registration package or this suite",
      not [b for b in BANNED if b in PKG_TEXT or b in _reg_text or b in Path(__file__).read_text(encoding="utf-8")],
      str([b for b in BANNED if b in PKG_TEXT or b in _reg_text]))

# =====================================================================================================================
print("")
print("[2] watchdog: golden fixtures, PROPOSED boundaries, oracle")
# =====================================================================================================================


def render_wd(state: str | None, attrs: dict | None, t: float, tpl: str = wt, *, since: float | None = None,
              pause: tuple | None = None) -> str:
    """The watchdog's value at `t`; `since` is when the status entity's state last changed (default: at `t`); `pause` is the
    pause helper as (state, last_changed), or None when the helper does not exist."""
    w = IntelWorld(t)
    w.set(OTHER, "1")
    w.set(OTHER_BOOL, "off")
    if pause is not None:
        w.set(PAUSE, pause[0])
        w.changed_at[PAUSE] = pause[1]
    if state is not None:
        w.set(STATUS, state, attrs or {})
        if since is not None:
            w.changed_at[STATUS] = since
    return "on" if as_boolean(w.render(tpl)) else "off"


def pause_on(t: float) -> tuple:
    return ("on", t - 60)


EXPECT_FRESH = {"all_open_blocked": "on", "synthetic_ok": "on", "paused": "on", "starting": "on", "stale": "off", "self_test_failed": "off"}
for name in FIXTURE_NAMES:
    fx = json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))
    ent = fx["entities"][STATUS]
    attrs = {**ent["recorded"], **ent["unrecorded"]}
    gen = datetime.fromisoformat(attrs["generated_at"]).timestamp()
    vu = attrs.get("valid_until")
    if ent["state"] == "PAUSED":
        ok_ = (render_wd("PAUSED", attrs, gen + 300, pause=pause_on(gen)) == "on"
               and render_wd("PAUSED", attrs, gen + 3 * HOUR, pause=pause_on(gen)) == "on"
               and render_wd("PAUSED", attrs, gen + 3 * HOUR, pause=("off", gen + 3 * HOUR - RESUME_GRACE_S)) == "on"
               and render_wd("PAUSED", attrs, gen + 3 * HOUR, pause=("off", gen + 3 * HOUR - RESUME_GRACE_S - 1)) == "off"
               and render_wd("PAUSED", attrs, gen + 300, pause=None) == "off")
        check(f"fixture {name} (PAUSED): fresh while the pause helper is on (5 min and 3 h after generated_at), fresh "
              f"{RESUME_GRACE_S} s after the helper turned off and not 1 s later, never without the helper", ok_)
        continue
    at5 = render_wd(ent["state"], attrs, gen + 300, since=gen)
    at_max = render_wd(ent["state"], attrs, gen + WATCHDOG_MAX_AGE_S, since=gen)
    past = render_wd(ent["state"], attrs, gen + WATCHDOG_MAX_AGE_S + 1, since=gen)
    expired = render_wd(ent["state"], attrs, datetime.fromisoformat(vu).timestamp() + 1, since=gen) if vu else "off"
    check(f"fixture {name} ({ent['state']}): watchdog {EXPECT_FRESH[name]} 5 min after generated_at, the same at the "
          f"PROPOSED {WATCHDOG_MAX_AGE_S} s, off 1 s past it and 1 s past valid_until",
          at5 == EXPECT_FRESH[name] and at_max == (EXPECT_FRESH[name] if not vu or gen + WATCHDOG_MAX_AGE_S
                                                    <= datetime.fromisoformat(vu).timestamp() else "off")
          and past == "off" and expired == "off", f"{at5} {at_max} {past} {expired}")

ok = status_attrs(T0)
check("clock ahead: generated_at 120 s ahead is fresh, 121 s ahead is not (PROPOSED CLOCK_AHEAD_S), PAUSED included",
      render_wd("OK", status_attrs(T0, gen_offset=CLOCK_AHEAD_S), T0) == "on"
      and render_wd("OK", status_attrs(T0, gen_offset=CLOCK_AHEAD_S + 1), T0) == "off"
      and render_wd("PAUSED", status_attrs(T0, valid_for=None, gen_offset=CLOCK_AHEAD_S + 1), T0, pause=pause_on(T0)) == "off")
check("valid_until boundary: fresh at valid_until, not 1 s after", render_wd("OK", ok, T0 + VALID_FOR_S) == "on"
      and render_wd("OK", ok, T0 + VALID_FOR_S + 1) == "off")
check("T2: a computed status (OK, NO_ADVICE, BLOCKED, INSUFFICIENT_DATA) with no valid_until is not fresh, even 1 s after "
      "generated_at", all(render_wd(st, status_attrs(T0, valid_for=None), T0 + 1) == "off" for st in COMPUTED))
check("T2: a result 1201 s old with valid_until 6 h ahead is not fresh (1200 s is)",
      render_wd("OK", status_attrs(T0, valid_for=6 * HOUR), T0 + WATCHDOG_MAX_AGE_S) == "on"
      and render_wd("OK", status_attrs(T0, valid_for=6 * HOUR), T0 + WATCHDOG_MAX_AGE_S + 1) == "off"
      and render_wd("BLOCKED", status_attrs(T0, valid_for=6 * HOUR), T0 + WATCHDOG_MAX_AGE_S + 1) == "off")
check("T2: PAUSED for 3 h (and for 3 days) with the pause helper on stays fresh",
      render_wd("PAUSED", status_attrs(T0, valid_for=None), T0 + 3 * HOUR, pause=pause_on(T0)) == "on"
      and render_wd("PAUSED", status_attrs(T0, valid_for=None), T0 + 72 * HOUR, pause=pause_on(T0)) == "on")
check("T2: PAUSED with the helper off for 131 s is not fresh; for 130 s it is (PROPOSED RESUME_GRACE_S), however old the PAUSED",
      render_wd("PAUSED", status_attrs(T0, valid_for=None), T0 + 3 * HOUR, pause=("off", T0 + 3 * HOUR - 131)) == "off"
      and render_wd("PAUSED", status_attrs(T0, valid_for=None), T0 + 3 * HOUR, pause=("off", T0 + 3 * HOUR - 130)) == "on")
check("PAUSED with the helper missing, unavailable for 131 s or unknown for 131 s is not fresh",
      render_wd("PAUSED", status_attrs(T0, valid_for=None), T0 + 60, pause=None) == "off"
      and render_wd("PAUSED", status_attrs(T0, valid_for=None), T0 + 600, pause=("unavailable", T0 + 600 - 131)) == "off"
      and render_wd("PAUSED", status_attrs(T0, valid_for=None), T0 + 600, pause=("unknown", T0 + 600 - 131)) == "off")
check("PAUSED carrying a valid_until in the past is not fresh, even with the helper on",
      render_wd("PAUSED", status_attrs(T0, valid_for=60), T0 + 61, pause=pause_on(T0)) == "off")
_starting = status_attrs(T0, valid_for=None)
check("T2: STARTING for 1201 s is not fresh, whether it is republished with a new generated_at (last_changed) or not (generated_at)",
      render_wd("STARTING", _starting, T0, since=T0 - WATCHDOG_MAX_AGE_S) == "on"
      and render_wd("STARTING", _starting, T0, since=T0 - WATCHDOG_MAX_AGE_S - 1) == "off"
      and render_wd("STARTING", _starting, T0, since=T0 - 12 * HOUR) == "off"
      and render_wd("STARTING", _starting, T0 + WATCHDOG_MAX_AGE_S, since=T0) == "on"
      and render_wd("STARTING", _starting, T0 + WATCHDOG_MAX_AGE_S + 1, since=T0) == "off")
for label, state, attrs, pause in (
        ("the status entity is absent", None, None, None), ("the status entity is absent, the pause on", None, None, pause_on(T0)),
        ("unavailable", "unavailable", {}, None), ("unknown", "unknown", {}, None),
        ("STALE", "STALE", status_attrs(T0), None), ("SELF_TEST_FAILED", "SELF_TEST_FAILED", status_attrs(T0), None),
        ("an unknown status word", "LEARNING_NORMALLY", status_attrs(T0), None),
        ("contract ecco-intel-entities/2", "OK", status_attrs(T0, contract_version="ecco-intel-entities/2"), None),
        ("no contract_version (the prototype's shape)", "OK", status_attrs(T0, drop=("contract_version",)), None),
        ("mode ASSISTED", "OK", status_attrs(T0, mode="ASSISTED"), None), ("no mode", "OK", status_attrs(T0, drop=("mode",)), None),
        ("applies_nothing false", "OK", status_attrs(T0, applies_nothing=False), None),
        ("applies_nothing as the text 'true'", "OK", status_attrs(T0, applies_nothing="true"), None),
        ("applies_nothing 1", "OK", status_attrs(T0, applies_nothing=1), None),
        ("integration_version empty", "OK", status_attrs(T0, integration_version=""), None),
        ("integration_version of spaces only", "OK", status_attrs(T0, integration_version="   "), None),
        ("integration_version of a tab and a newline", "OK", status_attrs(T0, integration_version="\t\n"), None),
        ("integration_version missing", "OK", status_attrs(T0, drop=("integration_version",)), None),
        ("integration_version a number", "OK", status_attrs(T0, integration_version=1), None),
        ("generated_at missing", "OK", status_attrs(T0, drop=("generated_at",)), None),
        ("generated_at not a time", "OK", status_attrs(T0, generated_at="soon"), None),
        ("generated_at a number", "OK", status_attrs(T0, generated_at=T0), None),
        ("valid_until not a time", "OK", status_attrs(T0, valid_until="later"), None),
        ("valid_until a number", "OK", status_attrs(T0, valid_until=T0 + 600), None),
        ("valid_until missing on OK", "OK", status_attrs(T0, drop=("valid_until",)), None),
        ("PAUSED with generated_at missing, the pause on", "PAUSED", status_attrs(T0, valid_for=None, drop=("generated_at",)), pause_on(T0)),
        ("PAUSED with a wrong contract, the pause on", "PAUSED", status_attrs(T0, valid_for=None, contract_version="x"), pause_on(T0))):
    try:
        got = render_wd(state, attrs, T0 + 60, pause=pause)
        err = ""
    except Exception as exc:  # noqa: BLE001
        got, err = "error", repr(exc)
    check(f"not fresh (and no template error): {label}", got == "off", got + err)
check("a version with text around spaces is still a version (fresh)", render_wd("OK", status_attrs(T0, integration_version=" 0.1.0 "), T0 + 60) == "on")
check("the STARTING bound applies to STARTING only (a long-lived OK, BLOCKED or PAUSED status with a new generated_at is fresh)",
      all(render_wd(st, status_attrs(T0, valid_for=None if st == "PAUSED" else VALID_FOR_S), T0 + 60, since=T0 - 12 * HOUR,
                    pause=pause_on(T0)) == "on"
          for st in ("OK", "BLOCKED", "PAUSED", "NO_ADVICE", "INSUFFICIENT_DATA")))


def ts_of(v):
    if not isinstance(v, str):
        return None
    try:
        d = datetime.fromisoformat(v)
    except ValueError:
        return None
    return (d if d.tzinfo else d.replace(tzinfo=S.LOCAL)).timestamp()


def oracle(state: str | None, a: dict | None, t: float, since: float | None = None, pause: tuple | None = None) -> bool:
    """An independent statement of the watchdog's rule (the package header and the runbook's G8), over the same inputs."""
    if state not in FRESH_STATUSES or not isinstance(a, dict):
        return False
    if a.get("contract_version") != ac.CONTRACT_VERSION or a.get("mode") != "SHADOW" or a.get("applies_nothing") is not True:
        return False
    iv = a.get("integration_version")
    if not (isinstance(iv, str) and iv.strip()):
        return False
    g = ts_of(a.get("generated_at"))
    if g is None or t - g < -CLOCK_AHEAD_S:
        return False
    v = a.get("valid_until")
    vt = ts_of(v)
    if v is not None and (vt is None or t > vt):
        return False
    if state in COMPUTED and vt is None:
        return False
    if state != "PAUSED" and t - g > WATCHDOG_MAX_AGE_S:
        return False
    if state == "STARTING" and since is not None and t - since > WATCHDOG_MAX_AGE_S:
        return False
    if state == "PAUSED":
        return pause is not None and (pause[0] == "on" or t - pause[1] <= RESUME_GRACE_S)
    return True


rnd = random.Random(20301015)
mismatch = []
CHOICES = {
    "state": list(ac.SystemStatus.ALL) + ["PAUSED"] * 4 + ["STARTING"] * 2 + ["unknown", "unavailable", "", "ok"],
    "contract_version": [ac.CONTRACT_VERSION] * 6 + ["ecco-intel-entities/2", "", None, 1],
    "mode": ["SHADOW"] * 6 + ["ASSISTED", "AUTONOMOUS", "OFF", "shadow", None],
    "applies_nothing": [True] * 6 + [False, "true", 1, None],
    "integration_version": ["0.1.0"] * 6 + ["", None, 1, "   ", " 0.1 "],
}
AGES = [0, 1, 60, 119, 120, 121, 899, 900, 901, 1199, 1200, 1201, 2700, 9000, -1, -119, -120, -121, -600]
for i in range(1200):
    t = T0 + rnd.randint(0, 10_000)
    st = rnd.choice(CHOICES["state"])
    a = {k: rnd.choice(v) for k, v in CHOICES.items() if k != "state"}
    a = {k: v for k, v in a.items() if not (v is None and rnd.random() < 0.5)}       # sometimes absent, sometimes None
    gen = t - rnd.choice(AGES)
    a["generated_at"] = rnd.choice([iso(gen)] * 8 + ["garbage", gen, None])
    a["valid_until"] = rnd.choice([None, None, iso(gen + rnd.choice([0, 30, 900, 1800, 3600, -5])), "x", 5])
    if rnd.random() < 0.1:
        a.pop("valid_until")
    since = t - rnd.choice([0, 60, 1199, 1200, 1201, 9000])                 # when the status state last changed
    pz = rnd.choice([None, "on", "on", "off", "off", "unavailable"])
    pause = None if pz is None else (pz, t - rnd.choice([0, 60, 129, 130, 131, 9000]))
    exp = "on" if oracle(st, a, t, since, pause) else "off"
    try:
        got = render_wd(st, a, t, since=since, pause=pause)
    except Exception as exc:  # noqa: BLE001
        got = f"error {exc!r}"
    if got != exp:
        mismatch.append((i, st, a, t - T0, t - since, pause, got, exp))
check("the watchdog template equals the independent oracle on 1200 seeded random statuses, status ages and pause helper states "
      "(no template error either)", not mismatch, str(mismatch[:2]))

# =====================================================================================================================
print("")
print("[3] alerts driven through the simulator")
# =====================================================================================================================
# A. healthy publishing: silent, the watchdog on throughout (the 72 h regression, three cadences)
for every, valid in ((PUBLISH_EVERY_S, VALID_FOR_S), (90, 160), (60, VALID_FOR_S)):
    r = rig()
    r.publish_every("OK", every=every, valid_for=valid)
    r.run_until(T0 + 72 * HOUR)
    check(f"healthy: a result every {every} s with {valid} s validity for 72 h keeps the watchdog on (it never flaps) and raises "
          "no notification", r.wd_changes() == [(T0, "off"), (T0, "on")] and r.notes() == [], f"{r.wd_changes()[:4]} {r.notes()}")

# B. the publisher stops: off once valid_until passes, alert after the watchdog has been off for 30 min, once
r = rig()
last = T0 + 3 * PUBLISH_EVERY_S
r.publish_every("OK", until=last + 1)
off_at = last + VALID_FOR_S + 60                  # the first minute boundary after valid_until
check("stale: on at valid_until, off at the next minute boundary", r.wd_at(last + VALID_FOR_S) == "on" and r.wd_at(off_at) == "off")
r.run_until(off_at + ALERT_AFTER_S - 1)
check("stale: no notification before the watchdog has been off for 1800 s", r.notes() == [], str(r.notes()))
r.run_until(off_at + ALERT_AFTER_S + 1)
check("stale: exactly one ecco_intel_watchdog_stale when it has been off for 1800 s (PROPOSED ALERT_AFTER_S)",
      [(round(t - off_at), n) for t, n in r.notes()] == [(ALERT_AFTER_S, STALE_ID)], str(r.notes()))
r.run_until(off_at + 12 * HOUR)
check("stale: not repeated while it stays off (12 h)", len(r.notes()) == 1, str(r.notes()))
r.publish_every("OK")
r.run_until(r.w.t + 60)
on_again = r.w.state(WD)
r.run_until(r.w.t + 30)
check("stale: a fresh result turns the watchdog on again", on_again == "on" and len(r.notes()) == 1)

# C. the max age decides when valid_until is far ahead
r = rig()
r.publish("OK", valid_for=6 * HOUR)
check("max age: a result with a 6 h validity is not fresh after the PROPOSED 1200 s",
      r.wd_at(T0 + WATCHDOG_MAX_AGE_S) == "on" and r.wd_at(T0 + WATCHDOG_MAX_AGE_S + 60) == "off")
r.run_until(T0 + WATCHDOG_MAX_AGE_S + 60 + ALERT_AFTER_S + 1)
check("max age: the stale alert follows 1800 s later", [(round(t - T0), n) for t, n in r.notes()]
      == [(WATCHDOG_MAX_AGE_S + 60 + ALERT_AFTER_S, STALE_ID)], str(r.notes()))

# D. pause (gate G8): PAUSED is published once per pause and stays fresh while the helper is on
r = rig()
r.publish("OK")
r.run_until(T0 + 600)
r.toggle_pause("on")
r.publish("PAUSED", valid_for=None)
r.run_until(T0 + 24 * HOUR)
check("pause: one PAUSED publish and 24 h with the helper on: the watchdog stays on (AUD-6) and nothing alerts",
      r.notes() == [] and not [s for _t, s in r.wd_changes(T0 + 1) if s != "on"] and r.w.state(WD) == "on",
      f"{r.wd_changes(T0 + 1)} {r.notes()}")
r.toggle_pause("off")
t_off = r.w.t
r.run_until(t_off + RESUME_GRACE_S)
on_in_grace = r.w.state(WD)
wd_off_at = next_minute(t_off + RESUME_GRACE_S)
r.run_until(wd_off_at)
off_after_grace = r.w.state(WD)
r.run_until(wd_off_at + ALERT_AFTER_S - 1)
quiet_after_unpause = r.notes() == []
r.run_until(wd_off_at + ALERT_AFTER_S + 120)
check("pause: an unpause with the integration down (PAUSED stays published) keeps the watchdog on for the 130 s grace, turns it off "
      "at the next minute boundary, and the stale alert follows once, 1800 s after that",
      on_in_grace == "on" and off_after_grace == "off" and quiet_after_unpause
      and [(round(t - wd_off_at), n) for t, n in r.notes()] == [(ALERT_AFTER_S, STALE_ID)], f"{on_in_grace} {off_after_grace} {r.notes()}")
# the owner's pause silences the stale alert even when the integration is down and publishes nothing (no PAUSED)
r = rig()
r.publish("OK")
r.run_until(T0 + 60)
r.toggle_pause("on")
r.run_until(T0 + 24 * HOUR)
check("pause: the pause silences the stale alert while the integration is down (24 h, the watchdog off, no PAUSED published)",
      r.notes() == [] and r.w.state(WD) == "off", str(r.notes()))
r.toggle_pause("off")
t_off = r.w.t
r.run_until(t_off + ALERT_AFTER_S - 1)
quiet_after_unpause = r.notes() == []
r.run_until(t_off + ALERT_AFTER_S + 120)
check("pause: switching the pause off while nothing is fresh is quiet for 1800 s (the next cycle's chance), then alerts once",
      quiet_after_unpause and [(round(t - t_off), n) for t, n in r.notes()] == [(ALERT_AFTER_S, STALE_ID)], str(r.notes()))
# the hand-over: the integration publishes STARTING at its next tick after the helper turns off (within 65 s), then results
r = rig()
r.publish("OK")
r.run_until(T0 + 60)
r.toggle_pause("on")
r.publish("PAUSED", valid_for=None)
r.run_until(T0 + 4 * HOUR + 17)
r.toggle_pause("off")
t_off = r.w.t
r.run_until(t_off + 64)
r.publish("STARTING", valid_for=None)
r.run_until(t_off + 64 + 200)
r.publish_every("OK")
r.run_until(t_off + 6 * HOUR)
check("pause: an unpause handed over to STARTING at the next tick (within 65 s), then normal results: the watchdog never turns off "
      "(G8: PAUSED fresh for 130 s after the helper turns off) and nothing alerts",
      not [s for _t, s in r.wd_changes(T0 + 1) if s != "on"] and r.notes() == [] and r.w.state(WD) == "on",
      f"{r.wd_changes(T0 + 1)} {r.notes()}")
r = rig(paused="on")
r.publish_every("PAUSED", valid_for=None)
r.run_until(T0 + 6 * HOUR)
check("pause: a paused integration that keeps publishing PAUSED is fresh and silent", r.w.state(WD) == "on" and r.notes() == [])

# E. SELF_TEST_FAILED: one alert, no stale alert, again after a recovery and a new failure
r = rig()
r.publish_every("OK", until=T0 + HOUR)
r.run_until(T0 + HOUR)
r.publish_every("SELF_TEST_FAILED", valid_for=None, blockers=[{"code": "ENTITY_ID_MISMATCH", "text": "registered with a suffix"}])
r.run_until(T0 + 7 * HOUR)
check("self-test: SELF_TEST_FAILED raises exactly one ecco_intel_self_test_failed, at once, and no stale alert in 6 h",
      [(round(t - T0 - HOUR), n) for t, n in r.notes()] == [(0, SELF_ID)] and r.w.state(WD) == "off", str(r.notes()))
r2 = rig()
r2.publish_every("SELF_TEST_FAILED", valid_for=None, until=T0 + 1)
r2.run_until(T0 + HOUR)
r2.publish_every("OK", until=T0 + 2 * HOUR)       # recovered: results again until the new failure
r2.run_until(T0 + 2 * HOUR)
r2.publish("SELF_TEST_FAILED", valid_for=None)
r2.run_until(T0 + 2 * HOUR + 60)
check("self-test: a recovery and a new failure alert again (two creates, same id)", [n for _t, n in r2.notes()] == [SELF_ID, SELF_ID],
      str(r2.notes()))

# F. contract mismatch: one alert, no stale alert; each variant
for label, over in (("contract ecco-intel-entities/2", {"contract_version": "ecco-intel-entities/2"}),
                    ("no contract_version", {"drop": ("contract_version",)}),
                    ("applies_nothing false", {"applies_nothing": False}),
                    ("integration_version empty", {"integration_version": ""}),
                    ("integration_version of spaces only", {"integration_version": "   "}),
                    ("integration_version missing", {"drop": ("integration_version",)})):
    r = rig()
    r.publish_every("OK", **over)
    r.run_until(T0 + 6 * HOUR)
    check(f"contract mismatch ({label}): exactly one ecco_intel_contract_mismatch, at once, no stale alert in 6 h",
          [(round(t - T0), n) for t, n in r.notes()] == [(0, MISMATCH_ID)] and r.w.state(WD) == "off", str(r.notes()))
r = rig()
r.publish_every("OK")
r.run_until(T0 + HOUR)
check("contract mismatch: a valid contract never raises it", r.notes() == [])


# R. Home Assistant restarts with the fault ALREADY published (an integration upgraded and restarted out of step with this
#    package): the automations attach after the status exists, so the template trigger arms as already true (it never fires)
#    and the state trigger sees no change; persistent notifications do not survive the restart. The start triggers raise the
#    alert once; the integration keeps republishing the same fault every cycle for 24 h.
def restart_notes(state: str, pkg_text: str = PKG_TEXT, hours: float = 24, paused: str = "off", **over) -> tuple[list, str]:
    x = rig(pkg_text=pkg_text, status=(state, status_attrs(T0, **over)), paused=paused)
    x.publish_every(state, **over)
    x.run_until(T0 + hours * HOUR)
    return [(round(t - T0), n) for t, n in x.notes()], x.w.state(WD)


RESTART_FAULTS = (("SELF_TEST_FAILED", "SELF_TEST_FAILED", {"valid_for": None}, SELF_ID),
                  ("contract ecco-intel-entities/2", "OK", {"contract_version": "ecco-intel-entities/2"}, MISMATCH_ID),
                  ("no contract_version", "OK", {"drop": ("contract_version",)}, MISMATCH_ID),
                  ("applies_nothing false", "OK", {"applies_nothing": False}, MISMATCH_ID),
                  ("integration_version missing", "OK", {"drop": ("integration_version",)}, MISMATCH_ID),
                  ("integration_version of spaces only", "OK", {"integration_version": "   "}, MISMATCH_ID))
for label, state, over, nid in RESTART_FAULTS:
    got, wd_state = restart_notes(state, **over)
    check(f"restart with the fault already published ({label}): exactly one {nid} at the start, nothing else in 24 h",
          got == [(0, nid)] and wd_state == "off", f"{got} {wd_state}")
for label, state, paused, hours, over in (("a valid OK", "OK", "off", 0.5, {}), ("BLOCKED", "BLOCKED", "off", 0.5, {}),
                                          ("STARTING (for 15 min)", "STARTING", "off", 0.25, {"valid_for": None}),
                                          ("PAUSED (the pause helper on)", "PAUSED", "on", 0.5, {"valid_for": None})):
    got, wd_state = restart_notes(state, hours=hours, paused=paused, **over)
    check(f"restart with a good status ({label}): the start triggers raise nothing", got == [] and wd_state == "on", f"{got} {wd_state}")
got, _wd = restart_notes("STALE", hours=1, valid_for=None)
check("restart with STALE already published: no fault alert at the start, one stale alert 1800 s later",
      got == [(ALERT_AFTER_S, STALE_ID)], str(got))
r = rig(status=("SELF_TEST_FAILED", status_attrs(T0, valid_for=None)))
r.run_until(T0 + HOUR)
r.publish_every("OK", until=T0 + 2 * HOUR)        # recovered: results again until the new failure
r.run_until(T0 + 2 * HOUR)
r.publish("SELF_TEST_FAILED", valid_for=None)
r.run_until(T0 + 2 * HOUR + 60)
check("restart with SELF_TEST_FAILED, a recovery, then a new failure: two creates (the start, then the state change)",
      [(round(t - T0), n) for t, n in r.notes()] == [(0, SELF_ID), (2 * 3600, SELF_ID)], str(r.notes()))

# P. P3: Home Assistant starts with NO status entity (the integration not installed, or not set up yet): the self-test alert's
#    start trigger re-checks with a template condition, so nothing is raised and no condition error is logged
r = rig()
r.run_until(T0 + 120)
check("P3: a start with no status entity runs the start triggers, raises nothing and logs no condition error",
      r.notes() == [] and not r.w.warnings and r.ha.automations[1].ready, str(r.w.warnings[:2]))
r = rig(paused="on")
r.run_until(T0 + 120)
r.publish("PAUSED", valid_for=None)
r.run_until(T0 + 600)
check("P3: a start with no status entity and the pause on, then the integration's first PAUSED: quiet, no condition error, "
      "the watchdog on from that publish", r.notes() == [] and not r.w.warnings and r.w.state(WD) == "on", str(r.w.warnings[:2]))

# W. Home Assistant shows the watchdog's last saved state until its first render: the first render replaces it
r = rig(restored_wd="on")
check("restore: a watchdog restored `on` with no status entity is `off` from its first render at the start, and nothing alerts in "
      "24 h (no status entity)", r.wd_changes()[:2] == [(T0, "on"), (T0, "off")] and r.w.state(WD) == "off", str(r.wd_changes()))
r.run_until(T0 + 24 * HOUR)
check("restore: ... and stays off with no notification and no condition error", r.notes() == [] and not r.w.warnings
      and r.wd_changes() == [(T0, "on"), (T0, "off")], str(r.notes()))
r = rig(restored_wd="on")
r.run_until(T0 + 3)
r.publish("STARTING", valid_for=None)
r.run_until(T0 + 120)
check("restore: ... and turns on when the integration publishes its first STARTING", r.w.state(WD) == "on" and r.notes() == [])

# S. a start-up that never finishes: STARTING republished every cycle with a new generated_at
r = rig()
r.publish_every("STARTING", valid_for=None)
on_at_max = r.wd_at(T0 + WATCHDOG_MAX_AGE_S)
off_after = r.wd_at(T0 + WATCHDOG_MAX_AGE_S + 60)
r.run_until(T0 + WATCHDOG_MAX_AGE_S + 60 + ALERT_AFTER_S + 60)
check("STARTING for longer than the PROPOSED 1200 s: the watchdog turns off, and one stale alert follows 1800 s later",
      on_at_max == "on" and off_after == "off" and [(round(t - T0), n) for t, n in r.notes()]
      == [(WATCHDOG_MAX_AGE_S + 60 + ALERT_AFTER_S, STALE_ID)], f"{on_at_max} {off_after} {r.notes()}")

# U. the watchdog entity stuck `unknown` (a template fault in Home Assistant renders unknown): the stale alert still fires
r = rig()
r.publish_every("OK", until=T0 + 1)
r.w.listeners.remove(r.wd.update)           # the watchdog stops rendering on / off ...
r.w.set(WD, "unknown")                       # ... and reads unknown from now on
r.run_until(T0 + ALERT_AFTER_S - 1)
quiet_unknown = r.notes() == []
r.run_until(T0 + ALERT_AFTER_S + 61)
check("a watchdog stuck unknown counts as not fresh: quiet for 1800 s, then one stale alert", quiet_unknown
      and [n for _t, n in r.notes()] == [STALE_ID], str(r.notes()))

# G. a wrong mode with a valid contract: watchdog off -> stale alert after 1800 s
r = rig()
r.publish_every("OK", mode="ASSISTED")
r.run_until(T0 + ALERT_AFTER_S + 120)
check("wrong mode (contract valid): not fresh, and the stale alert after 1800 s (no mismatch alert: it never spells the mode)",
      [(round(t - T0, -1), n) for t, n in r.notes()] == [(ALERT_AFTER_S, STALE_ID)], str(r.notes()))

# H. not installed: never an alert
r = rig()
r.run_until(T0 + 24 * HOUR)
check("integration not installed (no status entity): watchdog off and no notification in 24 h", r.w.state(WD) == "off" and r.notes() == [])

# I. installed but unavailable from Home Assistant's start
r = rig(status=("unavailable", {}))
r.run_until(T0 + ALERT_AFTER_S - 1)
quiet = r.notes() == []
r.run_until(T0 + ALERT_AFTER_S + 61)
check("integration unavailable since the start: quiet for 1800 s, then one stale alert (no mismatch alert for unavailable)",
      quiet and [n for _t, n in r.notes()] == [STALE_ID], str(r.notes()))
r = rig(status=("unavailable", {}))
r.run_until(T0 + 600)
r.publish_every("STARTING", valid_for=None, until=T0 + 601)
r.run_until(T0 + 900)
r.publish_every("BLOCKED")
r.run_until(T0 + 6 * HOUR)
check("a normal start (unavailable, STARTING, then BLOCKED every 10 min) raises nothing", r.notes() == [] and r.w.state(WD) == "on",
      str(r.notes()))

# K. the integration is alive but its result is STALE
r = rig()
r.publish_every("STALE", valid_for=None)
r.run_until(T0 + ALERT_AFTER_S + 120)
check("STALE published every cycle: not fresh, one stale alert after 1800 s", [n for _t, n in r.notes()] == [STALE_ID], str(r.notes()))

# L. clock ahead in a running system
r = rig()
r.publish_every("OK", gen_offset=HOUR)
r.run_until(T0 + ALERT_AFTER_S + 120)
check("generated_at 1 h ahead of this clock: not fresh, one stale alert", r.w.state(WD) == "off" and [n for _t, n in r.notes()] == [STALE_ID])

# M. malformed timestamps in a running system never raise
r = rig()
r.publish_every("OK", generated_at="garbage", valid_until=12345)
r.run_until(T0 + ALERT_AFTER_S + 120)
check("malformed generated_at / valid_until: not fresh, the run never raised, one stale alert",
      r.w.state(WD) == "off" and [n for _t, n in r.notes()] == [STALE_ID] and not r.w.warnings, str(r.w.warnings[:2]))

# =====================================================================================================================
print("")
print("[4] write surface over every scenario")
# =====================================================================================================================
services = sorted({svc for x in ALL_RIGS for _t, svc, _e, _d in x.w.service_log})
check(f"only persistent_notification.create was ever called across {len(ALL_RIGS)} scenarios", services in ([], ["persistent_notification.create"]),
      str(services))
nids = sorted({d.get("notification_id") for x in ALL_RIGS for _t, _s, _e, d in x.w.service_log})
check("every notification id is one of the three ecco_intel_ ids, and each was raised somewhere", nids == sorted(NOTE_IDS), str(nids))
check("no service call names a target entity", all(not e for x in ALL_RIGS for _t, _s, e, _d in x.w.service_log))
writes = {e for x in ALL_RIGS for _t, e, _s in x.w.history}
check("nothing but the test's own inputs and the watchdog entity itself is ever written (no helper, script or other entity)",
      writes <= {STATUS, PAUSE, WD, OTHER, OTHER_BOOL}, str(sorted(writes - {STATUS, PAUSE, WD, OTHER, OTHER_BOOL})))
pause_writes = [(x, t, s) for x in ALL_RIGS for t, e, s in x.w.history if e == PAUSE]
check("the pause helper changes only when the owner (the test) toggles it", all(
    t == x.w.history[0][0] or (t, s) in x.owner_toggles for x, t, s in pause_writes), str(len(pause_writes)))
check("no automation run was dropped or failed and no condition error was logged (no simulator warning)",
      not [w for x in ALL_RIGS for w in x.w.warnings])

# =====================================================================================================================
print("")
print("[5] mutation: each in-memory mutant is killed")
# =====================================================================================================================


def wt_of(pkg_text: str) -> str:
    return watchdog_template(load_pkg(pkg_text))


def stale_alert_time(pkg_text: str) -> list:
    x = Rig(pkg_text=pkg_text)
    x.publish_every("OK", until=T0 + 1)
    x.run_until(T0 + 6 * HOUR)
    return [(round(t - T0), n) for t, n in x.notes()]


def paused_dead_notes(pkg_text: str) -> list:
    """The owner pauses while the integration is down (no PAUSED is published): the pause alone must keep the alert quiet."""
    x = Rig(pkg_text=pkg_text)
    x.publish("OK")
    x.run_until(T0 + 60)
    x.toggle_pause("on")
    x.run_until(T0 + 6 * HOUR)
    return x.notes()


def mismatch_notes(pkg_text: str) -> list:
    x = Rig(pkg_text=pkg_text)
    x.publish_every("OK", contract_version="ecco-intel-entities/2")
    x.run_until(T0 + 3 * HOUR)
    return [n for _t, n in x.notes()]


def mismatch_blank_notes(pkg_text: str) -> list:
    x = Rig(pkg_text=pkg_text)
    x.publish_every("OK", integration_version="   ")
    x.run_until(T0 + 2 * HOUR)
    return [n for _t, n in x.notes()]


def self_test_notes(pkg_text: str) -> list:
    x = Rig(pkg_text=pkg_text)
    x.publish_every("SELF_TEST_FAILED", valid_for=None)
    x.run_until(T0 + 3 * HOUR)
    return [n for _t, n in x.notes()]


def unpause_dead_notes(pkg_text: str) -> list:
    """Paused while the integration is down for 4 h, then unpaused: the stale alert waits 1800 s after the unpause."""
    x = Rig(pkg_text=pkg_text)
    x.publish("OK")
    x.run_until(T0 + 60)
    x.toggle_pause("on")
    x.run_until(T0 + 4 * HOUR)
    x.toggle_pause("off")
    t_off = x.w.t
    x.run_until(t_off + 2 * HOUR)
    return [(round(t - t_off), n) for t, n in x.notes()]


def handover_flaps(pkg_text: str) -> list:
    """Paused (PAUSED once), unpaused, STARTING at the next tick: the watchdog's changes after the pause began."""
    x = Rig(pkg_text=pkg_text, paused="on")
    x.publish("PAUSED", valid_for=None)
    x.run_until(T0 + 3 * HOUR + 17)
    x.toggle_pause("off")
    t_off = x.w.t
    x.run_until(t_off + 64)
    x.publish("STARTING", valid_for=None)
    x.run_until(t_off + 600)
    return [s for _t, s in x.wd_changes(T0 + 1) if s != "on"]


def starting_notes(pkg_text: str) -> list:
    x = Rig(pkg_text=pkg_text)
    x.publish_every("STARTING", valid_for=None)
    x.run_until(T0 + 3 * HOUR)
    return [n for _t, n in x.notes()]


def unknown_wd_notes(pkg_text: str) -> list:
    x = Rig(pkg_text=pkg_text)
    x.publish_every("OK", until=T0 + 1)
    x.w.listeners.remove(x.wd.update)
    x.w.set(WD, "unknown")
    x.run_until(T0 + 2 * HOUR)
    return [n for _t, n in x.notes()]


def restart_ids(pkg_text: str, state: str, **over) -> list:
    x = Rig(pkg_text=pkg_text, status=(state, status_attrs(T0, **over)))
    x.publish_every(state, **over)
    x.run_until(T0 + HOUR)
    return [n for _t, n in x.notes()]


def start_without_status_warnings(pkg_text: str) -> list:
    x = Rig(pkg_text=pkg_text)
    x.run_until(T0 + 120)
    return x.w.warnings


baseline_stale = stale_alert_time(PKG_TEXT)
_SELF_TPL = "        value_template: \"{{ is_state('sensor.ecco_intel_status', 'SELF_TEST_FAILED') }}\"\n"
_START_THEN_SELF = "      - trigger: homeassistant\n        event: start\n    conditions:\n      - condition: template\n" + _SELF_TPL
_START_THEN_TPL_COND = ("      - trigger: homeassistant\n        event: start\n    conditions:\n      - condition: template\n"
                        "        value_template: >-\n")
_SELF_COND = "    conditions:\n      - condition: template\n" + _SELF_TPL
_SELF_STATE_COND = ("    conditions:\n      - condition: state\n        entity_id: sensor.ecco_intel_status\n"
                    "        state: \"SELF_TEST_FAILED\"\n")
_m = re.search(r"    conditions:\n      - condition: template\n        value_template: >-\n[\s\S]*?(?=    actions:\n)", PKG_TEXT)
_MISMATCH_COND_BLOCK = _m.group(0) if _m else "(the mismatch condition block was not found)"
_PAUSED_CLAUSE = ("                  or (p is not none\n"
                  "                      and (p.state == 'on' or (t - as_timestamp(p.last_changed)) <= 130))) }}")
check("baseline for the mutants: one stale alert 1800 s after the watchdog turned off",
      baseline_stale == [(VALID_FOR_S + 60 + ALERT_AFTER_S, STALE_ID)], str(baseline_stale))
check("baselines for the mutants: the pause silences a dead integration; an unpause after it alerts 1800 s later; the hand-over "
      "never turns the watchdog off; a start with no status entity logs nothing",
      paused_dead_notes(PKG_TEXT) == [] and unpause_dead_notes(PKG_TEXT) == [(ALERT_AFTER_S, STALE_ID)]
      and handover_flaps(PKG_TEXT) == [] and start_without_status_warnings(PKG_TEXT) == [])
MUTANTS = (
    ("T3: the generated_at max age loosened to 12000 s", "and (st == 'PAUSED' or (t - gt) <= 1200)",
     "and (st == 'PAUSED' or (t - gt) <= 12000)",
     lambda m: render_wd("OK", status_attrs(T0, valid_for=6 * HOUR), T0 + WATCHDOG_MAX_AGE_S + 100, wt_of(m)) == "off"),
    ("valid_until ignored", "\n             and (v is none or (vt is not none and t <= vt))", "", lambda m: stale_alert_time(m) == baseline_stale),
    ("T3: valid_until made optional for a computed status", "\n             and (st in ['STARTING', 'PAUSED'] or vt is not none)", "",
     lambda m: all(render_wd(st, status_attrs(T0, valid_for=None), T0 + 1, wt_of(m)) == "off" for st in COMPUTED)),
    ("the alert delay cut to 60 s", "(t - as_timestamp(w.last_changed)) >= 1800", "(t - as_timestamp(w.last_changed)) >= 60",
     lambda m: stale_alert_time(m) == baseline_stale),
    ("the pause condition removed from the stale alert", "and not is_state('input_boolean.ecco_intel_paused', 'on')", "",
     lambda m: paused_dead_notes(m) == []),
    ("the mismatch exclusion dropped from the stale alert", "or (state_attr(s, 'contract_version') == 'ecco-intel-entities/1'",
     "or true or (state_attr(s, 'contract_version') == 'ecco-intel-entities/1'", lambda m: mismatch_notes(m) == [MISMATCH_ID]),
    ("the SELF_TEST_FAILED exclusion dropped from the stale alert", "and not is_state(s, 'SELF_TEST_FAILED')", "",
     lambda m: self_test_notes(m) == [SELF_ID]),
    ("STALE counted as fresh", "{{ st in ['OK', 'NO_ADVICE',", "{{ st in ['OK', 'STALE', 'NO_ADVICE',",
     lambda m: render_wd("STALE", status_attrs(T0), T0 + 60, wt_of(m)) == "off"),
    ("the watchdog's integration_version not trimmed", "and iv is string and (iv | trim | length) > 0\n",
     "and iv is string and (iv | length) > 0\n",
     lambda m: render_wd("OK", status_attrs(T0, integration_version="   "), T0 + 60, wt_of(m)) == "off"),
    ("the mismatch trigger's integration_version not trimmed", "                  or not (iv is string and (iv | trim | length) > 0)) }}\n      - trigger",
     "                  or not (iv is string and (iv | length) > 0)) }}\n      - trigger",
     lambda m: mismatch_blank_notes(m) == [MISMATCH_ID]),
    ("the STARTING bound removed", "             and (st != 'STARTING'\n",
     "             and (true or st != 'STARTING'\n", lambda m: starting_notes(m) == [STALE_ID]),
    ("the STARTING bound loosened to 12000 s", "last_changed)) <= 1200)", "last_changed)) <= 12000)",
     lambda m: starting_notes(m) == [STALE_ID]),
    ("T3: the PAUSED exemption without the helper check", _PAUSED_CLAUSE, "                  or true) }}",
     lambda m: render_wd("PAUSED", status_attrs(T0, valid_for=None), T0 + 600, wt_of(m), pause=("off", T0 + 600 - 131)) == "off"
     and render_wd("PAUSED", status_attrs(T0, valid_for=None), T0 + 600, wt_of(m), pause=None) == "off"),
    ("the PAUSED status bounded by the max age again (AUD-6)", "and (st == 'PAUSED' or (t - gt) <= 1200)", "and ((t - gt) <= 1200)",
     lambda m: render_wd("PAUSED", status_attrs(T0, valid_for=None), T0 + 3 * HOUR, wt_of(m), pause=pause_on(T0)) == "on"),
    ("the resume grace loosened to 1300 s", "(t - as_timestamp(p.last_changed)) <= 130)", "(t - as_timestamp(p.last_changed)) <= 1300)",
     lambda m: render_wd("PAUSED", status_attrs(T0, valid_for=None), T0 + 3 * HOUR, wt_of(m), pause=("off", T0 + 3 * HOUR - 131)) == "off"),
    ("the resume grace removed (PAUSED only while the helper is on)", "(p.state == 'on' or (t - as_timestamp(p.last_changed)) <= 130)",
     "(p.state == 'on')", lambda m: handover_flaps(m) == []),
    ("the clock-ahead bound loosened to 1200 s", "(t - gt) >= -120", "(t - gt) >= -1200",
     lambda m: render_wd("OK", status_attrs(T0, gen_offset=CLOCK_AHEAD_S + 1), T0, wt_of(m)) == "off"),
    ("the pause-change delay removed from the stale alert", "and (p is none or (t - as_timestamp(p.last_changed)) >= 1800)",
     "and (p is none or true)", lambda m: unpause_dead_notes(m) == [(ALERT_AFTER_S, STALE_ID)]),
    ("the stale alert narrowed to a watchdog that is off (unknown ignored)", "w is not none and w.state != 'on'",
     "w is not none and w.state == 'off'", lambda m: unknown_wd_notes(m) == [STALE_ID]),
    ("the self-test start trigger removed", _START_THEN_SELF, "    conditions:\n      - condition: template\n" + _SELF_TPL,
     lambda m: restart_ids(m, "SELF_TEST_FAILED", valid_for=None) == [SELF_ID]),
    ("the mismatch start trigger removed", _START_THEN_TPL_COND, "    conditions:\n      - condition: template\n        value_template: >-\n",
     lambda m: restart_ids(m, "OK", contract_version="ecco-intel-entities/2") == [MISMATCH_ID]),
    ("the self-test condition removed (a start alerts whatever the status)", _SELF_COND, "",
     lambda m: restart_ids(m, "OK") == []),
    ("P3: the self-test condition back to a state condition", _SELF_COND, _SELF_STATE_COND,
     lambda m: start_without_status_warnings(m) == []),
    ("the mismatch condition removed (a start alerts whatever the status)", _MISMATCH_COND_BLOCK, "",
     lambda m: restart_ids(m, "OK") == []),
)

for label, old, new, survives in MUTANTS:
    mutant = PKG_TEXT.replace(old, new, 1)
    applied = mutant != PKG_TEXT and PKG_TEXT.count(old) == 1
    try:
        killed = not survives(mutant)
    except Exception:  # noqa: BLE001  (a mutant that breaks the run is killed too)
        killed = True
    check(f"mutant killed: {label}", applied and killed, "not applied (or not unique)" if not applied else "survived")

# =====================================================================================================================
print("")
print("[6] the dashboard's markdown fallback, rendered with the same template stand-ins")
# =====================================================================================================================
_dash = yaml.safe_load((ROOT / DASH_REL).read_text(encoding="utf-8"))
MD = [c for c in _dash["views"][0]["cards"] if c.get("type") == "markdown"][0]["content"]
FIGURE = re.compile(r"\d(?:\.\d+)?\s*(?:%|kWh)|£\s*\d")


def render_md(state: str | None, attrs: dict | None, t: float = T0 + 120) -> str:
    w = IntelWorld(t)
    w.set(OTHER, "1")
    w.set(PAUSE, "off")
    w.set(WD, "on")
    if state is not None:
        w.set(STATUS, state, attrs or {})
    return w.render(MD)


EXPECT_OPEN = {"all_open_blocked": " ".join(f"I-D{n}" for n in range(1, 10)), "synthetic_ok": "I-D7", "stale": "I-D7"}
for name in FIXTURE_NAMES:
    ent = json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))["entities"][STATUS]
    attrs = {**ent["recorded"], **ent["unrecorded"]}
    try:
        out, err = render_md(ent["state"], attrs, datetime.fromisoformat(attrs["generated_at"]).timestamp() + 120), ""
    except Exception as exc:  # noqa: BLE001
        out, err = "", repr(exc)
    check(f"markdown fallback, fixture {name}: the banner, the status, the open decisions, the watchdog and the pause; no figure",
          not err and "SHADOW MODE - advice only, nothing is applied" in out and f"Status: **{ent['state']}**" in out
          and f"Open decisions: {EXPECT_OPEN.get(name, ' '.join(f'I-D{n}' for n in range(1, 10)))}\n" in out
          and "Watchdog: fresh" in out and "Pause: off" in out and not FIGURE.search(out), err or out[:200])
for label, state, attrs in (("contract ecco-intel-entities/2", "OK", status_attrs(T0, contract_version="ecco-intel-entities/2")),
                            ("no contract_version", "OK", status_attrs(T0, drop=("contract_version",))),
                            ("mode ASSISTED", "OK", status_attrs(T0, mode="ASSISTED")),
                            ("applies_nothing false", "OK", status_attrs(T0, applies_nothing=False)),
                            ("integration_version missing", "OK", status_attrs(T0, drop=("integration_version",))),
                            ("integration_version of spaces only", "OK", status_attrs(T0, integration_version="   ")),
                            ("an unknown status word", "LEARNING_NORMALLY", status_attrs(T0))):
    out = render_md(state, attrs)
    check(f"markdown fallback, {label}: 'Intelligence output not recognised' and nothing from the output",
          "Intelligence output not recognised" in out and "SHADOW MODE" not in out and "Status:" not in out and "LEARNING" not in out)
for label, state in (("absent", None), ("unavailable", "unavailable"), ("unknown", "unknown")):
    out = render_md(state, {})
    check(f"markdown fallback, status {label}: 'ECCO Intelligence is not publishing.'", "ECCO Intelligence is not publishing." in out
          and "Status:" not in out)

# =====================================================================================================================
print("")
print("[7] T1: the thresholds are derived from the integration's constants, as the runbook's gate G8 states them")
# =====================================================================================================================
check("T1: WATCHDOG_MAX_AGE_S = the engine's advice validity ceiling + one tick + the cycle budget + 2 ticks (900 + 60 + 120 + 120)",
      WATCHDOG_MAX_AGE_S == dp.PROPOSED_ADVICE_VALIDITY_S + C.TICK_S + C.PROPOSED_TIME_BUDGET_S + 2 * C.TICK_S
      and (dp.PROPOSED_ADVICE_VALIDITY_S, C.TICK_S, C.PROPOSED_TIME_BUDGET_S) == (900.0, 60.0, 120.0),
      str((dp.PROPOSED_ADVICE_VALIDITY_S, C.TICK_S, C.PROPOSED_TIME_BUDGET_S)))
check("T1: RESUME_GRACE_S = 2 x (one tick + the tick margin): the STARTING that follows an unpause arrives within one late tick",
      RESUME_GRACE_S == 2 * (C.TICK_S + C.PROPOSED_TICK_MARGIN_S))
check("the STARTING allowance is positive: WATCHDOG_MAX_AGE_S leaves Home Assistant 835 s of start-up beyond the start-up grace, a "
      "late tick and one cycle budget",
      WATCHDOG_MAX_AGE_S - (C.PROPOSED_STARTUP_GRACE_S + C.TICK_S + C.PROPOSED_TICK_MARGIN_S + C.PROPOSED_TIME_BUDGET_S) == 835)
check("a healthy result is always fresh: the validity ceiling ends before the age bound, so only valid_until decides for a computed status",
      dp.PROPOSED_ADVICE_VALIDITY_S < WATCHDOG_MAX_AGE_S)
check("ALERT_AFTER_S is at least twice the validity ceiling", ALERT_AFTER_S >= 2 * dp.PROPOSED_ADVICE_VALIDITY_S)
_rb = (ROOT / RUNBOOK_REL).read_text(encoding="utf-8")
_g8 = next((ln for ln in _rb.splitlines() if ln.startswith("| G8 |")), "")
check("the runbook's G8 row states this package's numbers and rules (a change on either side fails here)",
      "`WATCHDOG_MAX_AGE_S` = **1200 s** (900 s validity + 60 s tick + 120 s budget + 2 x 60 s)" in _g8
      and "`ALERT_AFTER_S` 1800 s" in _g8 and "`CLOCK_AHEAD_S` 120 s" in _g8
      and "PAUSED fresh only while the helper is on (plus 130 s)" in _g8 and "STARTING bounded by 1200 s" in _g8
      and "ecco_intelligence.yaml" in _g8 and "PR-6's numbers" not in _g8, _g8[:300])
# PR6-2 (accepted residual): before the template's first render Home Assistant shows the watchdog's saved state (scenario W), so the
# documents that judge or describe the watchdog say it is judged from its first render and that nothing acts on it alone.
_t4 = next((ln for ln in _rb.splitlines() if ln.startswith("| T4 |")), "")
_guide = " ".join((ROOT / "docs/intelligence/INTELLIGENCE_CONTINUATION_GUIDE.md").read_text(encoding="utf-8").split())
_ui = " ".join((ROOT / "docs/intelligence/UI_DESIGN.md").read_text(encoding="utf-8").split())
check("the runbook's T4 judges the watchdog from its first render with the status entity present after each Home Assistant "
      "start, within 600 s of it (the restored state and a status-less first render before it are not judged; a missing status "
      "entity after it fails T4; A53)",
      "judged from its first render with the status entity present after each Home Assistant start, which comes within 600 s "
      "of the start or of the window start (a later first render fails T4)" in _t4
      and "which nothing acts on and which T4 does not judge" in _t4
      and "after it, a missing status entity fails T4" in _t4, _t4[:300])
check("the guide and UI_DESIGN say nothing acts on the watchdog alone, that its own row and the card footer show the saved state "
      "until the first render, and that T4 / M7.2 judge it from its first render with the status entity present, within 600 s of "
      "the start, a missing status entity after it being a failure (A53)",
      "Nothing acts on the watchdog alone; its own dashboard row and the card footer show the saved state until the first render"
      in _guide and "Nothing reads the watchdog alone" not in _guide
      and "judge the watchdog from its first render with the status entity present after each start, which comes within 600 s "
          "of the start or of the window start; a later first render is a failure, and so is a missing status entity after it"
          in _guide
      and "Nothing acts on the watchdog alone: until that render its own row and the card's footer show the saved state" in _ui
      and "judge the watchdog from its first render with the status entity present after each start, which comes within 600 s "
          "of the start or of the window start; a later first render is a failure, and so is a missing status entity after it"
          in _ui)

# =====================================================================================================================
print("")
print("[8] T4: the dashboard registration package")
# =====================================================================================================================
REG = yaml.safe_load(_reg_text)
_man = yaml.safe_load((ROOT / "deployment/ha-manifest.yaml").read_text(encoding="utf-8"))
_dest = (_man.get("intelligence_dashboard") or {}).get("destination", "")
_entry = ((REG or {}).get("lovelace") or {}).get("dashboards", {}).get("ecco-intelligence") if isinstance(REG, dict) else None
check("T4: exactly `lovelace: dashboards: ecco-intelligence:` and nothing else (no entity, automation, script, resource or mode key)",
      isinstance(REG, dict) and list(REG) == ["lovelace"] and list(REG["lovelace"]) == ["dashboards"]
      and list(REG["lovelace"]["dashboards"]) == ["ecco-intelligence"], str(REG))
check("T4: the entry's keys are exactly mode, title, icon, show_in_sidebar, require_admin and filename, with these values",
      _entry == {"mode": "yaml", "title": "ECCO Intelligence", "icon": "mdi:head-lightbulb-outline", "show_in_sidebar": True,
                 "require_admin": True, "filename": "ecco/dashboards/ecco_intelligence.yaml"}, str(_entry))
check("T4: its filename is the manifest's destination of the standalone dashboard, relative to /config",
      _dest.startswith("/config/") and _entry is not None and _entry.get("filename") == _dest[len("/config/"):], _dest)
check("T4: require_admin is true (the pause tile is the dashboard's one control)", _entry is not None and _entry.get("require_admin") is True)
check("T4: the title and icon equal the dashboard's own (its title and its view's icon)", _entry is not None
      and _entry.get("title") == _dash.get("title") and _entry.get("icon") == _dash["views"][0].get("icon"))
check("T4: the url slug contains a hyphen (Home Assistant requires one for a dashboard url) and is not the production dashboard's",
      "-" in "ecco-intelligence" and "ecco_pro" not in _reg_text)
check("T4: the registration names no entity id and no service", not re.search(r"\b(?:sensor|binary_sensor|input_\w+|switch|script|"
                                                                               r"automation)\.[a-z0-9_]+", code_text(_reg_text))
      and "action:" not in _reg_text and "service" not in code_text(_reg_text))

# =====================================================================================================================
print("")
print("[9] T5 / T6: the post-export declaration (PEX entry isp1)")
# =====================================================================================================================
sys.path.insert(0, str(ROOT / "registry" / "tests"))
import _isp1_scope as I  # noqa: E402
import _scope_chain as sc  # noqa: E402
import _pex  # noqa: E402  (PEX: the files as of the entry before isp1, undone exactly; this suite pins isp1's declaration)

ISP1_FINGERPRINT = "ad3a192fb075d32b0b4bb1a36f687941091f49ceb8d9744dd0ba56cc538d0f8c"
OVW3_FINGERPRINT = "42a7ad40caa587d7d2b8c5da732bd177d90a7259a865dc347cfcc94394b91a89"   # its parent (the newest entry when isp1 was built)
BEFORE = {   # sha256 (LF) as of ovw3: the newest declared states isp1 starts from
    I.VERSION_REL: "0dddce0c82eee252f28b3a02a13782c69e9fc6a03b5874e8f9ddfc286db7cfb0",
    I.MANIFEST_REL: "ca537531897fa73c3f61a7a5a151397643b1bb80764c8e8f689e0d3120a100cf",
    I.PROTO_SUITE_REL: "0cf2ab64a06e146ecc39a5afeecb0c55334ab573290b914a4621bc63022898dc",
}


def at_ovw3(rel: str) -> str:
    return _pex.as_of(rel, "ovw3", _pex.read(rel))   # PEX: isp1 (and any later entry) undone exactly, sha256-checked at each step


def at_isp1(rel: str) -> str:
    """The file exactly as isp1 leaves it (a later entry's edits undone, so this suite keeps passing after one is appended)."""
    return _pex.as_of(rel, "isp1", _pex.read(rel))   # PEX: later entries undone exactly, sha256-checked at each step


ISP1 = sc.CHAIN.entry("isp1")
post = list(sc.POST_EXPORT_ENTRIES)
ids = [e.id for e in post]
check("T6: isp1 is a post-export entry appended right after ovw3, the newest entry when it was built (re-seal it if another "
      "entry merges first)", "isp1" in ids and "ovw3" in ids and sc.CHAIN.prev_id("isp1") == "ovw3", str(ids[-3:]))
check("T6: isp1 declares exactly the manifest as chain-pinned and exactly VERSION.yaml and the V1 prototype suite as frozen, each "
      "with its reverter and checkpoint, and no delta, op path, include, substitution, banned token or tag",
      set(ISP1.reverts) == set(ISP1.checkpoints) == {sc.HA_MANIFEST} == set(I.PINNED_REVERTERS)
      and set(ISP1.frozen_reverts) == set(ISP1.frozen_checkpoints) == {I.VERSION_REL, I.PROTO_SUITE_REL} == set(I.FROZEN_REVERTERS)
      and not ISP1.deltas and not ISP1.op_paths_changed and not ISP1.includes_added and not ISP1.subst_added
      and not ISP1.subst_changed and not ISP1.subst_removed and not ISP1.banned_fw_added and not ISP1.banned_files
      and not ISP1.tags_declared and not ISP1.tags_promoted)
check("T6: isp1 declares exactly the six files it adds (the three packages, their two suites, its scope module) and each exists",
      ISP1.added_files == I.ADDED_FILES and len(I.ADDED_FILES) == 6
      and {PKG_REL, REG_REL, PREFS_REL, "home-assistant/tests/test_ecco_intelligence_package.py",
           "home-assistant/tests/test_ecco_intelligence_prefs_package.py", "registry/tests/_isp1_scope.py"} == set(I.ADDED_FILES)
      and all((ROOT / f).is_file() for f in ISP1.added_files))
check("T6: no file is newly enrolled for isp1 (ENROLLED stays at six files; VERSION.yaml is already enrolled)",
      len(_pex.ENROLLED) == 6 and I.VERSION_REL in _pex.ENROLLED)
check("T6: isp1's fingerprint is the pinned value, the sha256 of its canonical record, linked to ovw3's",
      ISP1.fingerprint == ISP1_FINGERPRINT == _pex.fingerprint(ISP1) and _pex.record(ISP1)["parent"] == OVW3_FINGERPRINT   # PEX: hash link
      and sc.CHAIN.entry("ovw3").fingerprint == OVW3_FINGERPRINT)
old = {rel: at_ovw3(rel) for rel in BEFORE}
check("T6: undone exactly, VERSION.yaml, the manifest and the prototype suite are their ovw3 state byte for byte (sha256)",
      all(I.sha(old[rel]) == h for rel, h in BEFORE.items()), str({r: I.sha(t)[:16] for r, t in old.items()}))
check("T6: ...in which nothing of isp1 exists (no intelligence block, no ecco_intelligence stanza, no intelligence_dashboard key)",
      "intelligence:" not in old[I.VERSION_REL] and "intelligence_package" not in old[I.VERSION_REL]
      and "ecco_intelligence" not in old[I.MANIFEST_REL] and "ecco-intelligence-card" not in old[I.MANIFEST_REL]
      and "intelligence_dashboard" not in old[I.MANIFEST_REL])
check("T6: each isp1 pair round-trips (applying it to the ovw3 text gives the file as of isp1)",
      I.add_isp1_version(old[I.VERSION_REL]) == at_isp1(I.VERSION_REL)
      and I.add_isp1_manifest(old[I.MANIFEST_REL]) == at_isp1(I.MANIFEST_REL)
      and I.add_isp1_proto_suite(old[I.PROTO_SUITE_REL]) == at_isp1(I.PROTO_SUITE_REL))


def proto_pin(manifest_text: str) -> list:
    """The amended prototype pin's own code (the frozen suite's isp1 hunk), run on a manifest text: its failures."""
    fails: list = []
    ns = {"re": re, "manifest": manifest_text, "check": lambda n, c, d="": None if c else fails.append(n)}
    exec(I.PROTO_0_NEW, ns)   # noqa: S102  (the declared hunk, from this repository's own scope module)
    return fails


_live_man = (ROOT / I.MANIFEST_REL).read_text(encoding="utf-8")
check("T6: this suite reads the manifest's path lines with the pin's own pattern (the frozen hunk's regex, verbatim), which "
      "takes a path line with or without a trailing comment",
      f're.findall(r"{I.MANIFEST_PATH_RE}", manifest, re.M)' in I.PROTO_0_NEW
      and re.findall(I.MANIFEST_PATH_RE, "  - source: a/b.yaml   # a note\n    destination: /c/d.yaml\n"
                                         "    resource_url: /e#f\n", re.M) == ["a/b.yaml", "/c/d.yaml", "/e#f"])
_intel_paths = {p for p in re.findall(I.MANIFEST_PATH_RE, _live_man, re.M) if "intelligence" in p.lower()}
check("T6: the prototype pin's exemption is exactly the Intelligence paths isp1 adds to the manifest (none wider), and the pin holds "
      "on the live manifest", _intel_paths == set(I.ISP1_MANIFEST_PATHS) and len(I.ISP1_MANIFEST_PATHS) == 11
      and proto_pin(_live_man) == [] and "_ISP1_PATHS = {" in I.PROTO_0_NEW
      and all(f'"{p}"' in I.PROTO_0_NEW for p in I.ISP1_MANIFEST_PATHS), str(sorted(_intel_paths ^ set(I.ISP1_MANIFEST_PATHS))))
_ANCHOR = "  - source: home-assistant/packages/ecco_intelligence.yaml\n"
_extra = _live_man.replace(_ANCHOR, "  - source: home-assistant/packages/ecco_intelligence_extra.yaml\n"
                                    "    destination: /config/packages/ecco_intelligence_extra.yaml\n" + _ANCHOR, 1)
_proto = _live_man.replace(_ANCHOR, "  - source: home-assistant/prototypes/intelligence-v1/ecco_intelligence_v1_mock_package.yaml\n"
                           + _ANCHOR, 1)
check("T6: the amended prototype pin still fails a manifest with one more Intelligence path or with a prototype file "
      "(non-vacuity), as the pre-isp1 pin did",
      _extra != _live_man and _proto != _live_man and proto_pin(_extra) != [] and proto_pin(_proto) != [])
# PR6-1: a path line that carries a trailing YAML comment is still a path line. The pattern before this fix (`(\S+)\s*$`) skipped
# such a line, so one more Intelligence path written with a comment passed the pin.
_PRE_FIX_RE = r"^\s*(?:-\s*)?(?:source|destination|resource_url):\s*(\S+)\s*$"
_c_src = _live_man.replace(_ANCHOR, "  - source: home-assistant/packages/ecco_intelligence_extra.yaml   # a note\n"
                                    "    destination: /config/packages/ecco_extra.yaml\n" + _ANCHOR, 1)
_c_dst = _live_man.replace(_ANCHOR, "  - source: home-assistant/packages/ecco_extra.yaml\n"
                                    "    destination: /config/packages/ecco_intelligence_extra.yaml # a note\n" + _ANCHOR, 1)
_c_own = _live_man.replace(_ANCHOR, _ANCHOR.rstrip("\n") + "   # the presentation package\n", 1)
check("T6: the amended prototype pin fails one more Intelligence path on a source or a destination line that carries a "
      "trailing comment (the pattern before PR6-1 skipped both lines); the same stanza without Intelligence passes",
      _c_src != _live_man and _c_dst != _live_man and proto_pin(_c_src) != [] and proto_pin(_c_dst) != []
      and not [p for t in (_c_src, _c_dst) for p in re.findall(_PRE_FIX_RE, t, re.M) if "ecco_intelligence_extra" in p]
      and proto_pin(_c_src.replace("ecco_intelligence_extra", "ecco_extra")) == [])
check("T6: ...and still holds when one of isp1's own path lines carries a trailing comment (the comment is not part of the path)",
      _c_own != _live_man and proto_pin(_c_own) == [])

ver = yaml.safe_load(at_isp1(I.VERSION_REL))
ver_old = yaml.safe_load(old[I.VERSION_REL])
man = yaml.safe_load(at_isp1(I.MANIFEST_REL))
man_old = yaml.safe_load(old[I.MANIFEST_REL])
INTEL = {"version": "0.1.0", "contract": "ecco-intel-entities/1", "mode": "SHADOW", "applies_nothing": True,
         "path": "custom_components/ecco_intelligence", "package": PKG_REL, "prefs_package": PREFS_REL,
         "dashboard_registration": REG_REL, "dashboard": DASH_REL, "card": CARD_REL, "tested_in_home_assistant": False}
check("T5: VERSION.yaml's current.intelligence block is exactly the declared one (0.1.0, the contract, SHADOW, applies nothing, "
      "its paths, not tested in Home Assistant)", ver["current"].get("intelligence") == INTEL, str(ver["current"].get("intelligence")))
check("T5: current.home_assistant gains exactly intelligence_package; everything else in VERSION.yaml is unchanged (project_version, "
      "the dashboard version 7.23.0 and its record)",
      ver["current"]["home_assistant"] == {**ver_old["current"]["home_assistant"], "intelligence_package": PKG_REL}
      and {k: v for k, v in ver["current"].items() if k not in ("intelligence", "home_assistant")}
      == {k: v for k, v in ver_old["current"].items() if k != "home_assistant"}
      and {k: v for k, v in ver.items() if k != "current"} == {k: v for k, v in ver_old.items() if k != "current"}
      and ver["project_version"] == "0.9.0" and ver["current"]["dashboard"]["version"] == "7.23.0")
_mf = json.loads((ROOT / "custom_components/ecco_intelligence/manifest.json").read_text(encoding="utf-8"))
_card_ver = re.search(r"^export const VERSION = '([^']+)';$", (ROOT / CARD_REL).read_text(encoding="utf-8"), re.M)
check("T5: the version equals the integration's manifest.json, const.INTEGRATION_VERSION and the card's VERSION",
      INTEL["version"] == _mf.get("version") == C.INTEGRATION_VERSION == (_card_ver.group(1) if _card_ver else None)
      and INTEL["contract"] == ac.CONTRACT_VERSION and INTEL["mode"] == C.MODE)
check("T5: every path the intelligence block and intelligence_package name exists in this tree",
      all((ROOT / INTEL[k]).exists() for k in ("path", "package", "prefs_package", "dashboard_registration", "dashboard", "card"))
      and (ROOT / ver["current"]["home_assistant"]["intelligence_package"]).is_file())
STANZAS = [{"source": f"home-assistant/packages/{n}", "destination": f"/config/packages/{n}", "method": "ssh_file_copy",
            "restart_required": True} for n in ("ecco_intelligence.yaml", "ecco_intelligence_prefs.yaml", "ecco_intelligence_dashboard.yaml")]
check("T5: the manifest's package list gains exactly the three stanzas, appended in order, every older stanza unchanged",
      man["home_assistant_packages"] == man_old["home_assistant_packages"] + STANZAS, str(man["home_assistant_packages"][-3:]))
check("T5: a new top-level intelligence_dashboard mapping, exactly; the production dashboard mapping unchanged",
      man.get("intelligence_dashboard") == {"source": DASH_REL, "destination": "/config/ecco/dashboards/ecco_intelligence.yaml",
                                            "method": "ssh_file_copy", "restart_required": False, "activation_required": True}
      and man["dashboard"] == man_old["dashboard"] and list(man) == [*list(man_old)[:list(man_old).index("dashboard") + 1],
                                                                     "intelligence_dashboard", *list(man_old)[list(man_old).index("dashboard") + 1:]])
check("T5: the frontend_assets list gains exactly the card's stanza (manual resource registration), every older stanza unchanged",
      man["frontend_assets"] == man_old["frontend_assets"] + [{
          "source": CARD_REL, "destination": "/config/www/ecco/ecco-intelligence-card.js", "method": "ssh_file_copy",
          "restart_required": False, "resource_registration": "manual", "resource_url": "/local/ecco/ecco-intelligence-card.js"}])
check("T5: every other manifest section is unchanged",
      {k: v for k, v in man.items() if k not in ("home_assistant_packages", "frontend_assets", "intelligence_dashboard")}
      == {k: v for k, v in man_old.items() if k not in ("home_assistant_packages", "frontend_assets")})
_sources = [n.get("source") for n in walk(man) if isinstance(n, dict) and "source" in n]
check("T5: no manifest source under custom_components (the integration installs by its own kit route) and every source exists",
      not [s for s in _sources if str(s).startswith("custom_components")] and all((ROOT / s).is_file() for s in _sources))

print("")
if FAILURES:
    print(f"{len(FAILURES)} check(s) FAILED:")
    for f in FAILURES:
        print(f"  - {f}")
    sys.exit(1)
print("all checks passed")
