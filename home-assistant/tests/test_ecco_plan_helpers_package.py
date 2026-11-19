"""Offline suite for the plan helper package and its two guarded scripts (stage 3 of the two-master-card energy-control work):
home-assistant/packages/ecco_plan_helpers.yaml. NOT installed anywhere; this proves the file against a model of Home Assistant.

The REAL package YAML runs under the FPS1 interpreter (_ha_script_sim.py, through _plan_sim.py's zone and helper-range layer). Anything
outside the supported subset raises: nothing is guessed.

  [1] shape        parses; only helper domains, two scripts, one automation, two sensors; generic ecco_plan_ names; no `initial`; the
                   entities are exactly the ones the card reads (HELPER_IDS, PLAN_CONTROL_IDS) plus the seed flag
  [2] bounds       every helper's min / max / step equals the validator's HELPER_BOUNDS; the bounds and the hard ceilings written into the
                   start script's template equal the validator's; the stable refusal codes equal the plan core's, plus the script-only ones
  [3] no writes    the scripts and the automation call only helper setters and persistent notifications, write only ecco_plan_ helpers, read
                   only a named set of entities; no charge, discharge, TOU, inverter or dongle service or entity anywhere
  [4] parity       the plan core's table (frontend/ecco-plan-core/test/parity/override_parity_cases.json, run against the validator by the
                   plan-core suite) gives the same answer here: started or refused with the same stable code and the same length, on
                   ordinary, spring and autumn days; a refusal changes nothing but the last-result text and one notification
  [5] scripts      revision compare-and-set, unreadable revision, until-a-time, expiry precedence, write order, one record per kind, cancel
                   (always allowed, never touches another kind), the result texts fit the 255-character helper
  [6] sensors      export hold (clear / held / unknown, at the minute an expiry passes) and the effective reserve (larger known value,
                   raise-only, fail closed), over a table and a seeded random sweep
  [7] not a charge Prepare for power cut sets the reserve ECCO's plan uses and starts nothing: the battery below the reserve changes no charge entity,
                   no charge service exists, and the result says "Nothing is charging. Use Charge Battery if you want it filled."
  [8] seed         the owner's accepted limits are written once; the switch stays off; an owner's own value survives a restart
  [9] mutation     in-memory mutants of the package are each caught; an equivalent rewrite survives
  [10] clock      every backend expiry read (the hold sensor's state and held_by, the effective reserve's power-cut expiry, the cancel script) uses the
                  helper's `timestamp` attribute, not the state string: an override ending in the repeated hour of the October clock change stays held
                  to its true expiry second (a 120 minute override from 00:40 BST ends 01:40 GMT), clear from the expiry second; spring-forward and
                  ordinary days agree; a missing or non-numeric attribute is an unreadable record; each read site and the expiry second are mutated
  [11] rounding   the effective reserve is published rounded UP to a whole percent (62.4 -> 63), for the owner's reserve and the running power cut's, so it is never
                  below the owner's own value; the floor and half-to-even mutants are caught
  [12] honesty    additions that kill the five mutants the independent review found alive: cancel ends only its own kind (all three active, every order, every cross-kind
                  mutant), the raise-only boundary (equal, 0.5, 1 and 5 points on each side), and an unreadable record of each kind (unknown, or held by the running kinds)
  [13] guards     the state guard (`states(helper) not in bad`) at EACH of the ten timestamp read sites: a record that reports unavailable, unknown or empty but still carries a stale
                  timestamp attribute (the simulator keeps stale attributes; real Home Assistant drops them) is an unreadable record at every site (hold: unknown; held_by: not named; reserve:
                  the power cut retained since r14 (it was skipped before); cancel: proceeds and repairs it); ten mutants, one per site, each caught by the check of that site
  [14] epoch      (owner decision r14, 19 Nov 2026; the repeated-hour restart, known limitations 11, 17, 19 and 23) each override's expiry is also held as an ABSOLUTE epoch record, an
                  input_number per kind written by the start script BEFORE the date-and-time expiry and by the cancel script with the cancel instant, and the two sources are read
                  RAISE-ONLY (the later instant wins; either source unreadable makes the kind unreadable, and the raised reserve is retained while it cannot be read). The offline model
                  gains a RESTART step (_plan_sim.restart: a date-and-time helper's attribute restored from its state string as the FIRST of two equal local times, so up to 60 minutes
                  EARLY in the repeated hour; a number restored exactly, or one of the abnormal restores). The model of the restore is a recollection, not verified live. Cases: the
                  October repeated hour without and with a restart (before, in and after the hour; an expiry outside the hour), the spring-forward and an ordinary day, every kind, start
                  then cancel then restart, cancel inside the repeated hour after a restart, a missing attribute, a missing, reset, unavailable, unknown, empty, nan, infinite, negative,
                  out-of-range or junk epoch (with the attribute active or past), both sources unreadable (the raised reserve retained; not applied with an invalid stored reserve), a stale-early
                  and a stale-late attribute, an interrupted start or cancel (held), the normal paths, the deadline never extended, and a differential sweep (never earlier than the old attribute
                  read; equal to it and to the true instant whenever both sources agree); 33 mutants, each killed

Writes nothing; no Home Assistant, no network, no hardware. It proves the package's logic against a model; it proves nothing about a live
Home Assistant, the helpers' timestamp attribute on the owner's version, or the dashboard.
"""

from __future__ import annotations

import copy
import json
import random
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
import _ha_script_sim as S  # noqa: E402
import _plan_sim as P  # noqa: E402

PKG_REL = "home-assistant/packages/ecco_plan_helpers.yaml"
PKG_TEXT = (ROOT / PKG_REL).read_text(encoding="utf-8")
PLAN_CORE = ROOT / "frontend" / "ecco-plan-core"
CARD_SRC = ROOT / "frontend" / "ecco-energy-actions-card" / "src"
POLICY_TS = (PLAN_CORE / "src" / "overridePolicy.ts").read_text(encoding="utf-8")
OVERRIDES_TS = (PLAN_CORE / "src" / "overrides.ts").read_text(encoding="utf-8")
HELPERS_TS = (CARD_SRC / "plan" / "helpers.ts").read_text(encoding="utf-8")
ACTIONS_TS = (CARD_SRC / "plan" / "planActions.ts").read_text(encoding="utf-8")
MANIFEST_TEXT = (ROOT / "deployment" / "ha-manifest.yaml").read_text(encoding="utf-8")
PARITY = json.loads((PLAN_CORE / "test" / "parity" / "override_parity_cases.json").read_text(encoding="utf-8"))

FAILURES: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  PASS  {name}")
    else:
        FAILURES.append(name)
        print(f"  FAIL  {name}" + (f" - {detail}" if detail else ""))


def ts_block(text: str, name: str) -> dict:
    m = re.search(r"// BEGIN " + name + r"_JSON\r?\nexport const " + name + r" = (\{.*?\n\}) as const;\r?\n// END " + name + r"_JSON", text, re.S)
    if not m:
        raise AssertionError(f"markers for {name} not found")
    return json.loads(m.group(1))


BOUNDS = ts_block(POLICY_TS, "HELPER_BOUNDS")
IDS = ts_block(HELPERS_TS, "HELPER_IDS")
CONTROL_IDS = ts_block(ACTIONS_TS, "PLAN_CONTROL_IDS")
CODES_TS = sorted(re.findall(r'"([A-Z_]+)"', re.search(r"export type RefusalCode =([\s\S]*?);\n", OVERRIDES_TS).group(1)))
SCRIPT_ONLY_CODES = ["NOT_ACTIVE", "REVISION_CONFLICT", "REVISION_UNREADABLE", "UNTIL_NOT_ALLOWED"]
KINDS = ["hold_battery", "skip_tonight", "prepare_power_cut"]
OWNER_RESERVE = "input_number.ecco_minimum_reserve_soc"
SOC = "sensor.ecco_clock_dongle_ecco_battery_soc"
SWITCH = "input_boolean.ecco_plan_overrides_enabled"
LAST = "input_text.ecco_plan_last_result"
REV = "input_number.ecco_plan_revision"
HOLD = "sensor.ecco_plan_export_hold"
EFF = "sensor.ecco_plan_effective_reserve"
NOTE = "ecco_plan_override_refused"
POLICY_ENT = {
    "min_expiry": "input_number.ecco_plan_policy_min_expiry", "hold_default": "input_number.ecco_plan_policy_hold_default",
    "hold_cap": "input_number.ecco_plan_policy_hold_cap", "skip_until": "input_datetime.ecco_plan_policy_skip_until",
    "skip_cap": "input_number.ecco_plan_policy_skip_cap", "cut_default": "input_number.ecco_plan_policy_cut_default",
    "cut_cap": "input_number.ecco_plan_policy_cut_cap", "cut_reserve": "input_number.ecco_plan_policy_cut_reserve",
}
START_E = {k: f"input_datetime.ecco_plan_override_{k}_start" for k in KINDS}
EXPIRES_E = {k: f"input_datetime.ecco_plan_override_{k}_expires" for k in KINDS}
EPOCH_E = {k: f"input_number.ecco_plan_override_{k}_expires_epoch" for k in KINDS}   # the absolute expiry record (owner decision r14); the card does not read it
CUT_RESERVE_E = "input_number.ecco_plan_override_prepare_power_cut_reserve"
FMT = "%Y-%m-%d %H:%M:%S"


# --------------------------------------------------------------------------------------------------------------------------------
# A fresh world
# --------------------------------------------------------------------------------------------------------------------------------
def world(text: str = PKG_TEXT, now: str = "2026-11-17 21:30:40", zone: str = "Europe/London", policy: dict | None = None,
          owner=40, soc="50.0", confirmed=True, revision=7, extra=None) -> P.PlanWorld:
    """The package as Home Assistant would hold it after the owner confirmed the accepted limits (`policy` overrides single values;
    None makes a limit unreadable)."""
    pkg = yaml.safe_load(text)
    pw = P.PlanWorld(now, [pkg], zone)
    w = pw.w
    pol = {**PARITY["policy"], **(policy or {})}
    for key, ent in POLICY_ENT.items():
        v = pol.get(key)
        if v is None:
            w.set(ent, "unknown")
        elif key == "skip_until":
            pw.set_time(ent, v)
        else:
            w.set(ent, f"{float(v)}")
    w.set(SWITCH, "on" if confirmed else "off")
    w.set("input_boolean.ecco_plan_defaults_seeded", "on")   # the seed is proved in [8]; every other section starts from set limits
    if owner is None:
        w.set(OWNER_RESERVE, "unavailable")
    else:
        w.set(OWNER_RESERVE, f"{float(owner)}")
    w.set(SOC, soc)
    w.set(REV, "unknown" if revision is None else f"{float(revision)}")
    for fn in (extra or []):
        fn(pw)
    return pw


def snapshot(pw: P.PlanWorld, exclude=()) -> dict:
    return {e: v for e, v in pw.w.states.items() if e not in exclude}


def start(pw: P.PlanWorld, **fields) -> str:
    pw.run_script("ecco_plan_override_start", fields)
    return pw.state(LAST)


def cancel(pw: P.PlanWorld, **fields) -> str:
    pw.run_script("ecco_plan_override_cancel", fields)
    return pw.state(LAST)


def expiry_of(pw: P.PlanWorld, kind: str):
    """(start, expires) of a record as local datetimes."""
    z = pw.zone
    a = datetime.fromtimestamp(float(pw.w.state_attr(START_E[kind], "timestamp")), z)
    b = datetime.fromtimestamp(float(pw.w.state_attr(EXPIRES_E[kind], "timestamp")), z)
    return a, b


def case_outcome(pw: P.PlanWorld, kind: str, before: dict) -> dict:
    """What a finished start did, as the parity table states it."""
    last = pw.state(LAST)
    if last.startswith("STARTED"):
        a, b = expiry_of(pw, kind)
        return {"ok": True, "code": "", "expiry_min": round((b.timestamp() - a.timestamp()) / 60)}
    m = re.match(r"REFUSED ([A-Z_]+) - ", last)
    return {"ok": False, "code": m.group(1) if m else "?" + last[:20], "expiry_min": 0}


def run_case(text: str, c: dict) -> tuple[P.PlanWorld, dict, dict]:
    pol = {}
    for k, v in c["policy"].items():
        pol[k] = v
    pw = world(text, now=c["now_local"], zone=PARITY["zone"], policy=pol, owner=c["owner_reserve"], confirmed=pol.get("confirmed", True))
    before = snapshot(pw, exclude=(LAST,))
    fields = {"kind": c["kind"]}
    if c["expiry_min"] is not None:
        fields["expiry_min"] = c["expiry_min"]
    if c["until_local"]:
        fields["until_local"] = True
    pw.run_script("ecco_plan_override_start", fields)
    return pw, case_outcome(pw, c["kind"], before), before


def independent_until_min(c: dict) -> int | None:
    """The real minutes to the next local occurrence of the owner's end time, from zoneinfo alone (the cross-check of the table)."""
    z = ZoneInfo(PARITY["zone"])
    pol = {**PARITY["policy"], **c["policy"]}
    hh, mm, ss = (int(x) for x in str(pol["skip_until"]).split(":"))
    now = datetime.strptime(c["now_local"], FMT).replace(tzinfo=z, second=0)
    cand = now.replace(hour=hh, minute=mm, second=0)
    if cand.timestamp() <= now.timestamp():
        cand = (cand.replace(tzinfo=None) + timedelta(days=1)).replace(tzinfo=z)
    return round((cand.timestamp() - now.timestamp()) / 60)


# --------------------------------------------------------------------------------------------------------------------------------
# The checks that every mutant is run against (the package text under test is a parameter)
# --------------------------------------------------------------------------------------------------------------------------------
def static_problems(text: str) -> list[str]:
    found: list[str] = []
    doc = yaml.safe_load(text)
    allowed_actions = {"input_number.set_value", "input_datetime.set_datetime", "input_text.set_value", "input_boolean.turn_on",
                       "persistent_notification.create", "persistent_notification.dismiss"}
    reads_ok = re.compile(r"^(?:input_(?:boolean|number|datetime|text)\.ecco_plan_[a-z_]+|sensor\.ecco_plan_[a-z_]+|input_number\.ecco_minimum_reserve_soc"
                          r"|sensor\.ecco_clock_dongle_ecco_battery_soc)$")
    ent_re = re.compile(r"\b(?:input_boolean|input_number|input_datetime|input_text|sensor|binary_sensor|switch|number|select|button|script|light|climate|esphome|"
                        r"automation|fan|lock|cover|input_select)\.[a-z][a-z0-9_]*\b")

    def walk(o, path=""):
        if isinstance(o, dict):
            for k, v in o.items():
                yield from walk(v, f"{path}.{k}")
        elif isinstance(o, list):
            for i, v in enumerate(o):
                yield from walk(v, f"{path}[{i}]")
        else:
            yield path, o

    actions: list[dict] = []

    def collect(seq):
        for a in seq or []:
            if isinstance(a, dict):
                if "action" in a:
                    actions.append(a)
                for key in ("choose",):
                    for br in a.get(key, []):
                        collect(br.get("sequence"))
                collect(a.get("default"))
                collect(a.get("then"))
                collect(a.get("else"))
    for sc in (doc.get("script") or {}).values():
        collect(sc.get("sequence"))
    for au in doc.get("automation") or []:
        collect(au.get("actions"))
    for a in actions:
        if a["action"] not in allowed_actions:
            found.append(f"service {a['action']} is not on the allow-list")
        tgt = (a.get("target") or {}).get("entity_id")
        if a["action"].startswith("persistent_notification"):
            continue
        if not isinstance(tgt, str) or not re.fullmatch(r"input_(?:boolean|number|datetime|text)\.ecco_plan_[a-z_]+", tgt):
            found.append(f"{a['action']} writes {tgt!r}, not an ecco_plan_ helper")
    for path, val in walk(doc):
        if isinstance(val, str) and val not in allowed_actions:
            for e in ent_re.findall(val):
                if not reads_ok.match(e) and not e.startswith(("persistent_notification",)):
                    found.append(f"{path} names {e}")
    if re.search(r"\b(?:charge|discharge|tou|inverter|dongle|esphome|modbus|grid_charge)\b", " ".join(a["action"] for a in actions), re.I):
        found.append("a charge / discharge / TOU / inverter / dongle service")
    if (doc.get("script") or {}).keys() != {"ecco_plan_override_start", "ecco_plan_override_cancel"}:
        found.append("the scripts are not exactly start and cancel")
    for name, sc in (doc.get("script") or {}).items():
        if sc.get("mode") != "single":
            found.append(f"{name} is not mode single")
    return sorted(set(found))


def behaviour_problems(text: str) -> list[str]:
    """Every dynamic check the package must keep passing: the whole parity table, the clock cases, the sensors and the scripts."""
    bad: list[str] = []
    try:
        # (1) the parity table, end to end through the script
        for c in PARITY["cases"]:
            pw, got, before = run_case(text, c)
            if got != c["expect"]:
                bad.append(f"parity {c['id']}: {got} != {c['expect']}")
                continue
            if not got["ok"]:
                after = snapshot(pw, exclude=(LAST,))
                if after != before:
                    bad.append(f"parity {c['id']}: a refusal changed {[k for k in after if after[k] != before.get(k)][:3]}")
                if NOTE not in pw.w.notifications:
                    bad.append(f"parity {c['id']}: no notification")
        # (2) Skip tonight ends exactly on the owner's local end time, on an ordinary, a spring and an autumn day
        for cid in ("skip_default_until_ordinary", "skip_spring_day", "skip_autumn_day", "hold_until_local"):
            c = next(x for x in PARITY["cases"] if x["id"] == cid)
            pw, got, _ = run_case(text, c)
            kind = c["kind"]
            _a, b = expiry_of(pw, kind)
            if b.strftime("%H:%M:%S") != "07:00:00" or got["expiry_min"] != independent_until_min(c):
                bad.append(f"until {cid}: ends {b.strftime(FMT)}, {got['expiry_min']} min vs {independent_until_min(c)}")
        # (2b) a start at 21:30:40 is rounded down to the minute: it ends exactly on the end time, never 40 seconds after it
        c = next(x for x in PARITY["cases"] if x["id"] == "skip_default_until_ordinary")
        pw, got, _ = run_case(text, {**c, "now_local": "2026-11-17 21:30:40"})
        _a, b = expiry_of(pw, "skip_tonight")
        if b.strftime(FMT) != "2026-11-18 07:00:00" or got["expiry_min"] != 570:
            bad.append(f"start not rounded to the minute: ends {b.strftime(FMT)}")
        # (3) the hard ceiling holds even if a limit were allowed above it (bounds raised in a copy: only the ceiling can refuse)
        raised = text.replace("['Hold battery maximum', states('input_number.ecco_plan_policy_hold_cap') | float(none), 5, 4320, 5]",
                              "['Hold battery maximum', states('input_number.ecco_plan_policy_hold_cap') | float(none), 5, 99990, 5]")
        if raised != text:
            pw = world(raised, policy={"hold_cap": 5000})
            out = start(pw, kind="hold_battery", expiry_min=4325)
            if not out.startswith("REFUSED EXPIRY_ABOVE_CEILING"):
                bad.append(f"ceiling: {out[:60]}")
        else:
            bad.append("ceiling: the bound row was not found")
        # (4) the scripts
        bad += script_problems(text)
        # (5) the sensors
        bad += sensor_problems(text)
    except Exception as exc:  # noqa: BLE001 - a package that cannot run is a failed proof
        bad.append(f"raised {type(exc).__name__}: {str(exc)[:120]}")
    return bad


def script_problems(text: str) -> list[str]:
    bad: list[str] = []
    # revision compare-and-set
    pw = world(text, revision=7)
    out = start(pw, kind="hold_battery", expected_revision=6)
    if not out.startswith("REFUSED REVISION_CONFLICT") or pw.state(REV) != "7.0" or pw.state(EXPIRES_E["hold_battery"]).startswith("2026-11-18"):
        bad.append(f"cas conflict: {out[:50]} rev {pw.state(REV)}")
    out = start(pw, kind="hold_battery", expected_revision=7)
    if not out.startswith("STARTED") or pw.state(REV) != "8.0":
        bad.append(f"cas match: {out[:50]} rev {pw.state(REV)}")
    pw = world(text, revision=None)
    out = start(pw, kind="hold_battery")
    if not out.startswith("REFUSED REVISION_UNREADABLE") or not pw.state(EXPIRES_E["hold_battery"]).startswith("1970"):
        bad.append(f"revision unreadable: {out[:50]}")
    # a start bumps the revision by one, a refusal does not
    pw = world(text, revision=41)
    start(pw, kind="skip_tonight")
    r1 = pw.state(REV)
    start(pw, kind="hold_battery", expiry_min=1)
    if r1 != "42.0" or pw.state(REV) != "42.0":
        bad.append(f"revision bump: {r1} then {pw.state(REV)}")
    # until-a-time: not for Prepare for power cut; expiry_min wins over until_local
    pw = world(text)
    if not start(pw, kind="prepare_power_cut", until_local=True).startswith("REFUSED UNTIL_NOT_ALLOWED"):
        bad.append("until for power cut")
    pw = world(text)
    start(pw, kind="skip_tonight", expiry_min=300, until_local=True)
    a, b = expiry_of(pw, "skip_tonight")
    if round((b.timestamp() - a.timestamp()) / 60) != 300:
        bad.append("expiry_min does not win over until_local")
    # one record per kind: a start writes only its own kind's helpers; the write order raises the reserve BEFORE the expiry
    for kind in KINDS:
        pw = world(text)
        n0 = len(pw.w.service_log)
        start(pw, kind=kind)
        writes = [(s, e) for s, e, _d in pw.services(n0) if s.startswith("input_")]
        own = {START_E[kind], EXPIRES_E[kind], EPOCH_E[kind], CUT_RESERVE_E if kind == "prepare_power_cut" else "-", REV, LAST}   # EPOCH_E: owner decision r14, the kind's own absolute record
        if not {e for _s, e in writes} <= own:
            bad.append(f"{kind} wrote {sorted({e for _s, e in writes} - own)}")
        if kind == "prepare_power_cut":
            order = [e for _s, e in writes]
            if not (order.index(CUT_RESERVE_E) < order.index(EXPIRES_E[kind])):
                bad.append("reserve written after the expiry")
    # a restart replaces the record (one active override per kind); the refusal notification is dismissed by a later success
    pw = world(text)
    start(pw, kind="hold_battery", expiry_min=60)
    start(pw, kind="hold_battery", expiry_min=1)
    if NOTE not in pw.w.notifications:
        bad.append("no notification for a refusal")
    start(pw, kind="hold_battery", expiry_min=120)
    a, b = expiry_of(pw, "hold_battery")
    if NOTE in pw.w.notifications or round((b.timestamp() - a.timestamp()) / 60) != 120:
        bad.append("a later success did not replace the record and dismiss the notification")
    # the texts fit the 255-character helper at their longest
    pw = world(text, policy={"min_expiry": 12, "hold_default": 1500, "hold_cap": 5000, "skip_until": "02:30:00", "skip_cap": 10,
                             "cut_default": 5000, "cut_cap": 99999, "cut_reserve": 5})
    out = start(pw, kind="hold_battery")
    if len(out) > 255 or pw.w.warnings or pw.rejected or not out.startswith("REFUSED POLICY_INVALID"):
        bad.append(f"long text: {len(out)} chars, warnings {pw.w.warnings[:1]}")
    # cancel: always allowed (invalid or unconfirmed limits), ends only its own kind, bumps the revision, NOT_ACTIVE changes nothing
    pw = world(text, confirmed=True)
    start(pw, kind="hold_battery")
    start(pw, kind="skip_tonight")
    pw.w.set(SWITCH, "off")
    pw.w.set(POLICY_ENT["hold_cap"], "unknown")
    rev = pw.state(REV)
    out = cancel(pw, kind="hold_battery")
    if not out.startswith("CANCELLED") or pw.state(HOLD) != "held" or float(pw.state(REV)) != float(rev) + 1:
        bad.append(f"cancel hold: {out[:40]} {pw.state(HOLD)} {pw.state(REV)}")
    if "2026-11-18" not in pw.state(EXPIRES_E["skip_tonight"]):
        bad.append("cancel touched another kind")
    cancel(pw, kind="skip_tonight")
    if pw.state(HOLD) != "clear":
        bad.append("after both cancels the hold is not clear")
    rev = pw.state(REV)
    notes = dict(pw.w.notifications)
    out = cancel(pw, kind="hold_battery")
    if not out.startswith("REFUSED NOT_ACTIVE") or pw.state(REV) != rev or pw.w.notifications != notes:
        bad.append(f"cancel when not active: {out[:40]}")
    if not cancel(pw, kind="dump_everything").startswith("REFUSED UNKNOWN_KIND"):
        bad.append("cancel of an unknown kind")
    pw2 = world(text, revision=7)
    start(pw2, kind="hold_battery")
    if not cancel(pw2, kind="hold_battery", expected_revision=3).startswith("REFUSED REVISION_CONFLICT") or pw2.state(HOLD) != "held":
        bad.append("cancel compare-and-set")
    return bad


def sensor_problems(text: str) -> list[str]:
    bad: list[str] = []
    # export hold
    pw = world(text)
    if pw.state(HOLD) != "clear":
        bad.append(f"hold at rest {pw.state(HOLD)}")
    for kind in KINDS:
        pw = world(text)
        start(pw, kind=kind, expiry_min=30)
        if pw.state(HOLD) != "held" or kind not in str(pw.w.render(yaml.safe_load(text)["template"][0]["sensor"][0]["attributes"]["held_by"])):
            bad.append(f"hold for {kind}: {pw.state(HOLD)}")
        pw.w.run_until(pw.w.t + 28 * 60)
        if pw.state(HOLD) != "held":
            bad.append(f"{kind} released early")
        pw.w.run_until(pw.w.t + 3 * 60)
        if pw.state(HOLD) != "clear":
            bad.append(f"{kind} not released after its expiry")
    pw = world(text)
    pw.w.set(EXPIRES_E["skip_tonight"], "unavailable")
    if pw.state(HOLD) != "unknown":
        bad.append("an unreadable record is not unknown")
    start_ok = world(text)
    start_ok.w.set(EXPIRES_E["skip_tonight"], "unavailable")
    start(start_ok, kind="hold_battery", expiry_min=30)
    if start_ok.state(HOLD) != "held":
        bad.append("a known active record must read held even when another record is unreadable")
    # effective reserve, table: (owner, active power cut reserve or None, expected)
    table = [(40, None, "40"), (40, 80, "80"), (90, 80, "90"), (None, 80, "80"), (40, None, "40"), (None, None, "unknown"), (0, None, "0"), (120, None, "unknown"),
             (-3, None, "unknown")]
    for owner, cut, want in table:
        pw = world(text, owner=owner if owner is not None and 0 <= owner <= 100 else None)
        if owner is not None and not 0 <= owner <= 100:
            pw.w.set(OWNER_RESERVE, f"{float(owner)}")
        if cut is not None:
            pw.w.set(CUT_RESERVE_E, f"{float(cut)}")
            pw.set_local(EXPIRES_E["prepare_power_cut"], "2026-11-18 21:30:00")
        got = pw.state(EFF)
        if got != want:
            bad.append(f"effective reserve owner={owner} cut={cut}: {got} != {want}")
    # an expired or cancelled power cut no longer raises; an unreadable cut reserve is skipped, never trusted
    pw = world(text, owner=40)
    start(pw, kind="prepare_power_cut")
    if pw.state(EFF) != "80":
        bad.append(f"started power cut reserve {pw.state(EFF)}")
    cancel(pw, kind="prepare_power_cut")
    if pw.state(EFF) != "40":
        bad.append(f"cancelled power cut still raises: {pw.state(EFF)}")
    pw = world(text, owner=40)
    start(pw, kind="prepare_power_cut", expiry_min=30)
    pw.w.run_until(pw.w.t + 31 * 60)
    if pw.state(EFF) != "40":
        bad.append("an expired power cut still raises")
    pw = world(text, owner=40)
    start(pw, kind="prepare_power_cut")
    pw.w.set(CUT_RESERVE_E, "unavailable")
    if pw.state(EFF) != "40":
        bad.append("an unreadable cut reserve is not skipped")
    # raise-only over a seeded sweep: the effective reserve is never below any known input
    rng = random.Random(1717)
    for _ in range(60):
        owner = rng.choice([None, 0, 10, 40, 55, 80, 100])
        cut = rng.choice([None, 10, 55, 80, 100])
        expired = rng.random() < 0.3
        pw = world(text, owner=owner)
        if cut is not None:
            pw.w.set(CUT_RESERVE_E, f"{float(cut)}")
            pw.set_local(EXPIRES_E["prepare_power_cut"], "2026-11-17 20:00:00" if expired else "2026-11-18 09:00:00")
        known = [v for v in (owner, None if (cut is None or expired) else cut) if v is not None]
        got = pw.state(EFF)
        want = str(max(known)) if known else "unknown"
        if got != want:
            bad.append(f"sweep owner={owner} cut={cut} expired={expired}: {got} != {want}")
            break
    return bad


# ================================================================================================================================
print("[1] shape")
doc = yaml.safe_load(PKG_TEXT)
check("the package parses and has exactly the expected sections", set(doc) == {"input_boolean", "input_number", "input_datetime", "input_text", "script", "automation", "template"}, str(set(doc)))
ALLOWED_ATTRS = {"input_boolean": {"name"}, "input_number": {"name", "min", "max", "step", "mode", "unit_of_measurement"},
                 "input_datetime": {"name", "has_date", "has_time"}, "input_text": {"name", "max"}}
ents: dict[str, dict] = {}
for domain in ALLOWED_ATTRS:
    for oid, attrs in doc[domain].items():
        ents[f"{domain}.{oid}"] = attrs
check("every helper is a generic ecco_plan_ name with only whitelisted attributes (so no `initial` can hide)",
      all(e.split(".", 1)[1].startswith("ecco_plan_") and set(a) <= ALLOWED_ATTRS[e.split(".", 1)[0]] for e, a in ents.items()), "")
expected = set(IDS.values()) | {CONTROL_IDS["last_result"], "input_boolean.ecco_plan_defaults_seeded"} | set(EPOCH_E.values())
check("the helpers are exactly the entities the card reads (HELPER_IDS) plus the last result, the seed flag and the three backend-only epoch records of owner decision r14 "
      "(the card does not read them)", set(ents) == expected, str(set(ents) ^ expected))
check("one automation (the first-run seed), two scripts, two sensors",
      [a["id"] for a in doc["automation"]] == ["ecco_plan_seed_accepted_limits"] and set(doc["script"]) == {"ecco_plan_override_start", "ecco_plan_override_cancel"}
      and [s["name"] for s in doc["template"][0]["sensor"]] == ["ECCO Plan Export Hold", "ECCO Plan Effective Reserve"])
check("the card's script ids are the package's scripts", CONTROL_IDS["start_script"] == "script.ecco_plan_override_start" and CONTROL_IDS["cancel_script"] == "script.ecco_plan_override_cancel")
seed_targets = [a["target"]["entity_id"] for a in doc["automation"][0]["actions"]]
check("the first-run seed never touches the confirmation switch (it stays off until the owner turns it on)", "input_boolean.ecco_plan_overrides_enabled" not in seed_targets, str(seed_targets))

print("[2] bounds")
bad = []
for key, ent in IDS.items():
    if key in BOUNDS:
        b, a = BOUNDS[key], ents[ent]
        if key == "skip_until":
            if not (a.get("has_time") is True and a.get("has_date") is False):
                bad.append(key)
        elif (a.get("min"), a.get("max"), a.get("step")) != (b["min"], b["max"], b["step"]):
            bad.append(f"{key}: {(a.get('min'), a.get('max'), a.get('step'))} != {(b['min'], b['max'], b['step'])}")
check("every limit helper's min / max / step equals the validator's HELPER_BOUNDS", not bad, str(bad))
check("each override kind has an absolute epoch record (owner decision r14): an input_number with min 0, max 4102444800 (the year 2100), step 1 and mode box, one per kind, "
      "with no initial value (Home Assistant restores it), and the card's reader does not name it",
      all(e in ents and (ents[e].get("min"), ents[e].get("max"), ents[e].get("step"), ents[e].get("mode")) == (0, 4102444800, 1, "box") and "initial" not in ents[e]
          for e in EPOCH_E.values()) and not set(EPOCH_E.values()) & set(IDS.values()) and len(EPOCH_E) == 3,
      str({e: ents.get(e) for e in EPOCH_E.values()}))
rows = re.findall(r"\['([^']+)', states\('([a-z_.]+)'\) \| float\(none\), (\d+), (\d+), (\d+)\]", PKG_TEXT)
by_ent = {e: (int(lo), int(hi), int(st)) for _l, e, lo, hi, st in rows}
tpl_bounds = {k: (BOUNDS[k]["min"], BOUNDS[k]["max"], BOUNDS[k]["step"]) for k in POLICY_ENT if k != "skip_until"}
check("the bounds written into the start script's template equal HELPER_BOUNDS, one row per limit",
      len(rows) == 7 and {k: by_ent.get(e) for k, e in POLICY_ENT.items() if k != "skip_until"} == tpl_bounds, str(rows))
su_row = re.search(r"\['Skip tonight end time', su_min, (\d+), (\d+), (\d+)\]", PKG_TEXT)
check("Skip tonight's end time row carries the validator's time-of-day bounds (03:00 to 23:55, 5-minute step)",
      su_row is not None and tuple(int(x) for x in su_row.groups()) == (BOUNDS["skip_until"]["min"], BOUNDS["skip_until"]["max"], BOUNDS["skip_until"]["step"]))
ceil = re.search(r"set ceiling = (\d+) if kind_in == 'hold_battery' else \((\d+) if kind_in == 'skip_tonight' else (\d+)\)", PKG_TEXT)
check("the hard ceilings in the template are the maxima of the cap helpers (hold 72 h, skip 36 h, power cut 7 days)",
      ceil is not None and tuple(int(x) for x in ceil.groups()) == (BOUNDS["hold_cap"]["max"], BOUNDS["skip_cap"]["max"], BOUNDS["cut_cap"]["max"]) == (4320, 2160, 10080))
codes_pkg = sorted(set(re.findall(r"set r\.code = '([A-Z_]+)'", PKG_TEXT)))
check("the stable refusal codes of the scripts are the plan core's (minus the two a server cannot reach) plus the script-only ones",
      set(codes_pkg) == (set(CODES_TS) - {"TIME_UNKNOWN", "POWER_CUT_RESERVE_RANGE"}) | set(SCRIPT_ONLY_CODES), str(sorted(set(codes_pkg) ^ set(CODES_TS))))
check("every code the package names is spelled in its header comment too", all(c in PKG_TEXT.split("script:")[0] for c in codes_pkg))

print("[3] no writes outside the plan helpers")
check("the package passes the static write / read / service scan", static_problems(PKG_TEXT) == [], str(static_problems(PKG_TEXT)))
text_no_comments = "\n".join(ln for ln in PKG_TEXT.splitlines() if not ln.lstrip().startswith("#"))
check("no button, esphome, modbus, Free Power, Dump to Grid or inverter word in any executable line",
      not re.findall(r"(?i)\b(?:button|esphome|modbus|free_power|dump_to_grid|inverter|tou_)\b[.a-z_]*", text_no_comments), "")

print("[4] parity with the plan core's table")
bad = []
for c in PARITY["cases"]:
    pw, got, before = run_case(PKG_TEXT, c)
    if got != c["expect"]:
        bad.append(f"{c['id']}: {got} != {c['expect']}")
check(f"all {len(PARITY['cases'])} cases of the table give the validator's answer (start or the same stable refusal, the same length)", not bad, str(bad[:4]))
bad = []
for c in PARITY["cases"]:
    if not c["expect"]["ok"]:
        pw, got, before = run_case(PKG_TEXT, c)
        after = snapshot(pw, exclude=(LAST,))
        if after != before or NOTE not in pw.w.notifications or "(reason " + c["expect"]["code"] + ")" not in pw.w.notifications[NOTE]["message"]:
            bad.append(c["id"])
check("a refusal changes nothing but the last-result text and raises one notification that names the stable code", not bad, str(bad[:4]))
bad = []
for c in PARITY["cases"]:
    if c["expect"]["ok"]:
        pw, got, before = run_case(PKG_TEXT, c)
        if NOTE in pw.w.notifications or not pw.state(LAST).startswith("STARTED " + c["kind"]):
            bad.append(c["id"])
check("a start writes its record, bumps the revision and leaves no refusal notification", not bad, str(bad[:4]))
bad = []
for c in PARITY["cases"]:
    if c["id"] in ("skip_default_until_ordinary", "skip_spring_day", "skip_autumn_day", "hold_until_local", "skip_same_minute_means_tomorrow"):
        if c["expect"]["expiry_min"] != independent_until_min(c):
            bad.append(f"{c['id']}: table {c['expect']['expiry_min']} vs zoneinfo {independent_until_min(c)}")
check("the table's clock-change answers equal an independent zoneinfo computation (spring 7 h 30 min, autumn 9 h 30 min, ordinary 9 h 30 min)", not bad, str(bad))
check("the stable codes cover valid starts and every refusal the table lists",
      {c["expect"]["code"] for c in PARITY["cases"]} >= {"", "POLICY_UNCONFIRMED", "POLICY_INVALID", "UNKNOWN_KIND", "EXPIRY_NOT_WHOLE", "RESERVE_UNKNOWN", "RESERVE_BELOW_CURRENT", "EXPIRY_BELOW_MIN", "EXPIRY_ABOVE_CAP"})

print("[5] scripts, sensors, not a charge")
sp = script_problems(PKG_TEXT)
check("revision compare-and-set, until-a-time, one record per kind, write order, cancel, text length", sp == [], str(sp))
sn = sensor_problems(PKG_TEXT)
check("the export hold and the effective reserve over the table, the expiry minute and the seeded sweep", sn == [], str(sn))

# Prepare for power cut: a raised floor, never a charge
charge_calls: list[str] = []


def charge_trap(_e, _d):
    charge_calls.append("charge entity touched")
    raise AssertionError("a charge, discharge, TOU or inverter service was called")


def trap_world(soc: str) -> P.PlanWorld:
    pw = world(PKG_TEXT, soc=soc)
    for svc in ("button.press", "switch.turn_on", "switch.turn_off", "number.set_value", "select.select_option", "script.turn_on"):
        pw.w.service_handlers[svc] = charge_trap
    for e, v in (("number.ecco_clock_dongle_free_power_max_charge_power", "3000.0"), ("switch.ecco_clock_dongle_free_power_write_enable", "off"),
                 ("select.ecco_clock_dongle_manual_slot_1_charge_source", "None"), ("button.ecco_clock_dongle_start_free_power_charge_now", "unknown"),
                 ("number.ecco_clock_dongle_dump_to_grid_stop_soc", "25.0")):
        pw.w.set(e, v)
    return pw


pw = trap_world("35.0")
before_all = snapshot(pw, exclude=(LAST,))
n0 = len(pw.w.service_log)
out = start(pw, kind="prepare_power_cut")
touched = [e for e in pw.w.states if pw.w.states[e] != before_all.get(e) and e not in (LAST, REV, START_E["prepare_power_cut"], EXPIRES_E["prepare_power_cut"], CUT_RESERVE_E, EPOCH_E["prepare_power_cut"]) and not e.startswith("sensor.ecco_plan_")]
check("Prepare for power cut with the battery at 35 percent below the 80 percent reserve starts, writes only plan helpers and starts no charge",
      out.startswith("STARTED prepare_power_cut") and touched == [] and not charge_calls and all(s.startswith(("input_", "persistent_notification")) for s, _e, _d in pw.services(n0)), f"{out[:40]} {touched}")
check("the result says so plainly: battery percent, reserve percent, nothing is charging, use Charge Battery",
      out.endswith("The battery is at 35 percent, below the 80 percent reserve. Nothing is charging. Use Charge Battery if you want it filled."), out)
check("the raised reserve is what the rest of ECCO reads: the effective reserve is 80 while the battery stays at 35", pw.state(EFF) == "80" and pw.state(SOC) == "35.0")
pw = trap_world("90.0")
out = start(pw, kind="prepare_power_cut")
check("a battery above the raised reserve gets no charge sentence", out.startswith("STARTED") and "Nothing is charging" not in out, out)
pw = trap_world("unknown")
out = start(pw, kind="prepare_power_cut")
check("an unreadable battery level starts the override and states nothing about the battery", out.startswith("STARTED") and "battery is at" not in out, out)
pw = trap_world("35.0")
start(pw, kind="hold_battery")
start(pw, kind="skip_tonight")
check("Hold battery and Skip tonight never say anything about a charge and call no charge service", "Nothing is charging" not in pw.state(LAST) and not charge_calls)
check("the scripts name no service outside the allow-list (static, [3]) and the trap saw none (dynamic)", not charge_calls)

print("[8] the owner's accepted limits are seeded once")
pw = P.PlanWorld("2026-11-17 09:00:00", [yaml.safe_load(PKG_TEXT)], "Europe/London")
pw.ha.start()
pw.w.run_until(pw.w.t + 5)
SEEDED = {POLICY_ENT["min_expiry"]: "15.0", POLICY_ENT["hold_default"]: "240.0", POLICY_ENT["hold_cap"]: "1440.0", POLICY_ENT["skip_cap"]: "1440.0",
          POLICY_ENT["cut_default"]: "1440.0", POLICY_ENT["cut_cap"]: "4320.0", POLICY_ENT["cut_reserve"]: "80.0", POLICY_ENT["skip_until"]: "07:00:00"}
check("the first start writes exactly the accepted limits (15 min; Hold 4 h / 24 h; Skip 07:00 / 24 h; power cut 24 h / 80 percent / 72 h)",
      all(pw.state(e) == v for e, v in SEEDED.items()), str({e: pw.state(e) for e in SEEDED}))
check("the confirmation switch is NOT seeded: it stays off, so no override can start until the owner turns it on",
      pw.state(SWITCH) == "off" and pw.state("input_boolean.ecco_plan_defaults_seeded") == "on")
pw.w.set(POLICY_ENT["hold_default"], "120.0")
pw.w.set(SWITCH, "on")
pw.ha.start()
pw.w.run_until(pw.w.t + 5)
check("an owner's own value survives a restart (the seed runs once)", pw.state(POLICY_ENT["hold_default"]) == "120.0" and pw.state(SWITCH) == "on")
seed_writes = [(e, d) for _t, s, e, d in pw.w.service_log if s.startswith("input_")]
check("every seeded value is inside its helper's own range (the interpreter's helper services raise otherwise)", pw.rejected == [])
# an unconfirmed fresh install refuses with the stable code
pw = P.PlanWorld("2026-11-17 09:00:00", [yaml.safe_load(PKG_TEXT)], "Europe/London")
pw.ha.start()
pw.w.run_until(pw.w.t + 5)
pw.w.set(OWNER_RESERVE, "40.0")
out = start(pw, kind="hold_battery")
check("a fresh install with the limits seeded but not confirmed refuses every start (POLICY_UNCONFIRMED)", out.startswith("REFUSED POLICY_UNCONFIRMED"), out)
pw.w.set(SWITCH, "on")
out = start(pw, kind="hold_battery")
check("once the owner confirms, the accepted Hold battery default (4 h) starts", out.startswith("STARTED") and round((expiry_of(pw, "hold_battery")[1].timestamp() - expiry_of(pw, "hold_battery")[0].timestamp()) / 60) == 240, out)

check("no start, refusal, cancel or seed above ever wrote a value a helper refuses (min / max / step)", P.PlanWorld.rejected_all == [], str(P.PlanWorld.rejected_all[:3]))

print("[7] manifest and docs")
check("the manifest lists the package once, with the other packages' method and restart flag",
      MANIFEST_TEXT.count("home-assistant/packages/ecco_plan_helpers.yaml") == 1 and "destination: /config/packages/ecco_plan_helpers.yaml" in MANIFEST_TEXT)

print("[9] mutation")
MUTANTS = [
    # (what is broken, text to find, text to put there, how many places it occurs)
    ("the expiry cap is not enforced", "{%- elif ex > cap -%}", "{%- elif false -%}", 1),
    ("the shortest allowed override is not enforced", "{%- elif ex < p[0] -%}", "{%- elif ex < 0 -%}", 1),
    ("a whole number of minutes is not required", "(ex % 1) != 0)", "false)", 1),
    ("the confirmation switch is not required", "{%- if not confirmed -%}", "{%- if false -%}", 1),
    ("the power-cut reserve may lower the current reserve", "p[7] < owner", "p[7] < 0", 1),
    ("an unknown current reserve passes", "and not owner_ok -%}", "and false -%}", 1),
    ("the limits are not validated against the bounds", "x < s[2] or x > s[3] or ", "", 1),
    ("a limit may be off its step", " or ((x - s[2]) % s[4]) != 0", "", 1),
    ("the hard ceiling is gone", "{%- elif ex > ceiling -%}", "{%- elif false -%}", 1),
    ("Skip tonight never moves to the next day", "else as_timestamp(today_at(su) + timedelta(days=1))", "else as_timestamp(today_at(su))", 1),
    ("Skip tonight counts a clock-change day by the wall clock", "as_timestamp(today_at(su) + timedelta(days=1))", "(as_timestamp(today_at(su)) + 86400)", 1),
    ("the start instant is not rounded to the minute", "{%- set start_ts = (now_ts // 60) * 60 -%}\n            {%- set until_min", "{%- set start_ts = now_ts -%}\n            {%- set until_min", 1),
    ("the revision compare-and-set is gone (start and cancel)", "(rev_in | float(none)) != rev_raw", "false", 2),
    ("a start or cancel does not bump the plan revision", "value: \"{{ decision.revision + 1 }}\"", "value: \"{{ decision.revision }}\"", 2),
    ("the effective reserve takes the smaller input (not raise-only)", "known | max | round(0)", "known | min | round(0)", 1),
    # owner decision r14: the power cut's reserve counts while its record is active OR unreadable, so the anchor moved with the package text; the defect is the same (a FINISHED, readable record still raises)
    ("a finished power cut still raises the reserve", "(e is none or e > n) and c is number", "c is number", 1),
    ("the export hold ignores Skip tonight", "or (b is not none and b > n) or (c is not none and c > n) -%}held", "or (c is not none and c > n) -%}held", 1),
    ("an unreadable record reads clear", "{%- elif a is none or b is none or c is none -%}unknown", "{%- elif false -%}unknown", 1),
    ("a cancel needs the limits switch on", "{%- if kind_in not in ex -%}", "{%- if kind_in not in ex or not is_state('input_boolean.ecco_plan_overrides_enabled', 'on') -%}", 1),
    ("a start also presses a charge button",
     "      - choose:\n          - conditions:\n              - condition: template\n                value_template: \"{{ decision.ok }}\"\n            sequence:\n              - choose:\n                  - conditions:\n                      - condition: template\n                        value_template: \"{{ decision.kind == 'hold_battery' }}\"\n                    sequence:\n                      - action: input_datetime.set_datetime\n                        target:\n                          entity_id: input_datetime.ecco_plan_override_hold_battery_start",
     "      - action: button.press\n        target:\n          entity_id: button.ecco_clock_dongle_start_free_power_charge_now\n      - choose:\n          - conditions:\n              - condition: template\n                value_template: \"{{ decision.ok }}\"\n            sequence:\n              - choose:\n                  - conditions:\n                      - condition: template\n                        value_template: \"{{ decision.kind == 'hold_battery' }}\"\n                    sequence:\n                      - action: input_datetime.set_datetime\n                        target:\n                          entity_id: input_datetime.ecco_plan_override_hold_battery_start", 1),
    ("a script writes an inverter-side switch", "                  notification_id: ecco_plan_override_refused\n        default:\n          - action: input_text.set_value", "                  notification_id: ecco_plan_override_refused\n              - action: switch.turn_on\n                target:\n                  entity_id: switch.ecco_clock_dongle_free_power_write_enable\n        default:\n          - action: input_text.set_value", 2),
    ("the seed switches the confirmation on", "      - action: input_boolean.turn_on\n        target: {entity_id: input_boolean.ecco_plan_defaults_seeded}", "      - action: input_boolean.turn_on\n        target: {entity_id: input_boolean.ecco_plan_defaults_seeded}\n      - action: input_boolean.turn_on\n        target: {entity_id: input_boolean.ecco_plan_overrides_enabled}", 1),
]
killed = 0
for label, old, new, cnt in MUTANTS:
    if PKG_TEXT.count(old) != cnt:
        check(f"mutant anchor: {label}", False, f"anchor found {PKG_TEXT.count(old)}x, wanted {cnt}")
        continue
    mutated = PKG_TEXT.replace(old, new)
    found = static_problems(mutated) + behaviour_problems(mutated)
    seed_caught = False
    if "the seed" in label:
        pwm = P.PlanWorld("2026-11-17 09:00:00", [yaml.safe_load(mutated)], "Europe/London")
        pwm.ha.start()
        pwm.w.run_until(pwm.w.t + 5)
        seed_caught = pwm.state(SWITCH) != "off"
    if found or seed_caught:
        killed += 1
        print(f"  PASS  mutant caught: {label}")
    else:
        FAILURES.append(f"mutant survived: {label}")
        print(f"  FAIL  mutant survived: {label}")
check(f"{len(MUTANTS)} mutants, all caught", killed == len(MUTANTS), f"{killed}/{len(MUTANTS)}")
check("the unmutated package passes every dynamic check", behaviour_problems(PKG_TEXT) == [], str(behaviour_problems(PKG_TEXT)[:3]))
equiv = PKG_TEXT.replace("Unknown override.", "Unknown override kind.")
check("a harmless rewrite of a refusal text survives (the checks look at the stable codes, not the words)", behaviour_problems(equiv) == [] and static_problems(equiv) == [])

# ================================================================================================================================
print("[10] clock changes and the exact expiry second: every backend expiry read uses the helper's timestamp attribute")
# ================================================================================================================================
# New with the independent review of 18 Nov 2026 (finding 1). The three expiry records are date-and-time helpers. Their STATE is local
# wall-clock time; their `timestamp` attribute is the true instant (Home Assistant sets it from an aware datetime). Parsing the state string
# takes the FIRST of the two equal local times on the October clock-change day, so an override whose expiry falls in the repeated hour was
# released up to 60 minutes early (Europe/London: a 120 minute override started at 00:40 BST ends at 01:40 GMT, state '01:40:00', which the
# string parse reads as 01:40 BST, one hour too soon). The hold sensor (state and held_by), the effective reserve's power-cut expiry and the
# cancel script now read the attribute. Existing checks stay as they were; these only add.
class _Early(Exception):
    pass


def exp_ts(pw: P.PlanWorld, kind: str) -> float:
    return float(pw.w.state_attr(EXPIRES_E[kind], "timestamp"))


def held_by_of(pw: P.PlanWorld, text: str) -> str:
    return str(pw.w.render(yaml.safe_load(text)["template"][0]["sensor"][0]["attributes"]["held_by"])).strip()


def utc_ts(local_utc: str) -> float:
    return datetime.strptime(local_utc, FMT).replace(tzinfo=ZoneInfo("UTC")).timestamp()


def clock_problems(text: str, stop_early: bool = False) -> list[str]:
    """Every clock-change and exact-second case on the package text given. `stop_early` returns at the first problem (the mutants)."""
    bad: list[str] = []

    def add(msg: str) -> None:
        bad.append(msg)
        if stop_early:
            raise _Early()

    def edge_checks(pw: P.PlanWorld, kinds: list, tag: str, offsets=(-3540, -1800, -60, -1, 0, 1, 61)) -> None:
        """Around each running kind's own expiry (read from its attribute): the hold, held_by and the effective reserve must equal an independent
        oracle, `expiry > now` (strictly: clear AT the expiry second, held the second before)."""
        exps = {k: exp_ts(pw, k) for k in kinds}
        for t in sorted({e + d for e in exps.values() for d in offsets}):
            pw.w.run_until(t)
            want = [k for k in KINDS if k in exps and exps[k] > t]
            got, by = pw.state(HOLD), held_by_of(pw, text)
            if got != ("held" if want else "clear") or by != ",".join(want):
                add(f"{tag}: {t - min(exps.values()):+.0f} s from the first expiry the hold reads {got!r} held_by {by!r}, wanted {want}")
            if pw.state(EFF) != ("80" if "prepare_power_cut" in want else "40"):
                add(f"{tag}: {t - min(exps.values()):+.0f} s from the first expiry the effective reserve is {pw.state(EFF)}")

    try:
        # (1) the days: the October clock-change day (repeated hour), the spring-forward day, an ordinary day. Expiry from the attribute.
        days = (("autumn clock-change day", "2026-10-25 00:40:40", "2026-10-25 01:40:00", "2026-10-25 01:40:00"),
                ("spring-forward day", "2027-03-28 00:30:40", "2027-03-28 02:30:00", "2027-03-28 03:30:00"),
                ("ordinary day", "2026-11-17 21:30:40", "2026-11-17 23:30:00", "2026-11-17 23:30:00"))
        for label, started, exp_utc, state_str in days:
            for kind in KINDS:
                pw = world(text, now=started, zone="Europe/London")
                out = start(pw, kind=kind, expiry_min=120)
                exp = exp_ts(pw, kind) if out.startswith("STARTED") else 0.0
                if not out.startswith("STARTED") or exp != utc_ts(exp_utc) or pw.state(EXPIRES_E[kind]) != state_str:
                    add(f"{label} {kind}: started {out[:40]!r}, expiry {exp} state {pw.state(EXPIRES_E[kind])!r}, wanted {utc_ts(exp_utc)} {state_str!r}")
                    continue
                edge_checks(pw, [kind], f"{label} {kind}")
            # all three at once (each start moves the model clock by 30 s, so the minute-floored expiries differ): every kind is named while it runs
            pw = world(text, now=started, zone="Europe/London")
            for kind in KINDS:
                start(pw, kind=kind, expiry_min=120)
            edge_checks(pw, KINDS, f"{label} all three")
        # (2) the repeated hour, spelled out: the old read released at +60 min; now still held at +61, +90, +110 min of a 120 min override
        pw = world(text, now="2026-10-25 00:40:40", zone="Europe/London")
        start(pw, kind="hold_battery", expiry_min=120)
        t0 = exp_ts(pw, "hold_battery") - 7200
        for minutes in (59, 61, 90, 110, 119):
            pw.w.run_until(t0 + minutes * 60)
            if pw.state(HOLD) != "held":
                add(f"a 120 minute Hold battery started at 00:40 BST on the clock-change day reads {pw.state(HOLD)!r} {minutes} minutes in")
        # (3) the cancel script decides NOT_ACTIVE from the same instant: inside the repeated hour a running override can still be cancelled
        for kind in KINDS:
            pw = world(text, now="2026-10-25 00:40:40", zone="Europe/London")
            start(pw, kind=kind, expiry_min=120)
            pw.w.run_until(exp_ts(pw, kind) - 3000)       # 00:50 GMT: the override has 50 minutes left
            out = cancel(pw, kind=kind)
            if not out.startswith("CANCELLED") or pw.state(HOLD) != "clear" or exp_ts(pw, kind) > pw.w.t:
                add(f"cancel {kind} on the clock-change day: {out[:40]!r} hold {pw.state(HOLD)!r}")
        # (4) the instant is the attribute, never the string: a string that says 'long past' with a future attribute is held, and the reverse
        for kind in KINDS:
            pw = world(text)
            pw.w.set(EXPIRES_E[kind], "2020-01-01 00:00:00", {"timestamp": pw.w.t + 600, "has_date": True, "has_time": True})
            if pw.state(HOLD) != "held" or held_by_of(pw, text) != kind:
                add(f"{kind}: a past-looking string with a future timestamp attribute reads {pw.state(HOLD)!r} held_by {held_by_of(pw, text)!r}")
            pw = world(text)
            pw.w.set(EXPIRES_E[kind], "2099-01-01 00:00:00", {"timestamp": pw.w.t - 600, "has_date": True, "has_time": True})
            if pw.state(HOLD) != "clear":
                add(f"{kind}: a future-looking string with a past timestamp attribute reads {pw.state(HOLD)!r}")
        pw = world(text, owner=40)
        pw.w.set(CUT_RESERVE_E, "80.0")
        pw.w.set(EXPIRES_E["prepare_power_cut"], "2020-01-01 00:00:00", {"timestamp": pw.w.t + 600, "has_date": True, "has_time": True})
        if pw.state(EFF) != "80":
            add(f"the effective reserve of a power cut with a past-looking string and a future attribute is {pw.state(EFF)}, wanted 80")
        pw = world(text, owner=40)
        pw.w.set(CUT_RESERVE_E, "80.0")
        pw.w.set(EXPIRES_E["prepare_power_cut"], "2099-01-01 00:00:00", {"timestamp": pw.w.t - 600, "has_date": True, "has_time": True})
        if pw.state(EFF) != "40":
            add(f"the effective reserve of a power cut with a future-looking string and a past attribute is {pw.state(EFF)}, wanted 40")
        # (5) an attribute that is missing or not a number is an unreadable record: unknown (and a readable held record still reads held)
        for kind in KINDS:
            others = [k for k in KINDS if k != kind]
            for label, attrs in (("missing", {"has_date": True, "has_time": True}), ("not a number", {"timestamp": "abc"}), ("None", {"timestamp": None}),
                                 ("nan", {"timestamp": float("nan")}), ("empty", {"timestamp": ""})):
                pw = world(text)
                pw.w.set(EXPIRES_E[kind], "2026-11-18 09:00:00", attrs)
                if pw.state(HOLD) != "unknown" or held_by_of(pw, text) != "":
                    add(f"{kind}: a timestamp attribute that is {label} reads {pw.state(HOLD)!r} held_by {held_by_of(pw, text)!r}, wanted unknown")
                pw = world(text)
                pw.w.set(EXPIRES_E[kind], "2026-11-18 09:00:00", attrs)
                start(pw, kind=others[0], expiry_min=30)
                if pw.state(HOLD) != "held" or held_by_of(pw, text) != others[0]:
                    add(f"{kind}: unreadable ({label}) with {others[0]} running reads {pw.state(HOLD)!r} held_by {held_by_of(pw, text)!r}, wanted held")
        # an unreadable power-cut expiry RETAINS the raised reserve: owner decision r14 (fail closed, until a cancel or a readable record reconciles it). Before r14 the record was
        # SKIPPED here and the owner's 40 was published; that old behaviour is a mutant of [14] ("effective reserve dropped on an unreadable expiry"), killed there.
        for label, attrs in (("missing", {"has_date": True, "has_time": True}), ("not a number", {"timestamp": "abc"})):
            pw = world(text, owner=40)
            pw.w.set(CUT_RESERVE_E, "80.0")
            pw.w.set(EXPIRES_E["prepare_power_cut"], "2026-11-18 21:30:00", attrs)
            if pw.state(EFF) != "80":
                add(f"a power-cut expiry attribute that is {label}: the effective reserve is {pw.state(EFF)}, wanted 80 (the raised reserve is retained while the expiry cannot be read)")
        # cancel treats an unreadable record as it did: it proceeds, and writes a readable expiry (the record is repaired)
        for kind in KINDS:
            pw = world(text)
            start(pw, kind=kind, expiry_min=120)
            pw.w.set(EXPIRES_E[kind], pw.state(EXPIRES_E[kind]), {"has_date": True, "has_time": True})
            out = cancel(pw, kind=kind)
            if not out.startswith("CANCELLED") or pw.state(HOLD) != "clear" or exp_ts(pw, kind) > pw.w.t:
                add(f"cancel {kind} with an unreadable record: {out[:40]!r} hold {pw.state(HOLD)!r}")
        # (6) the attribute ALONE (additive, owner decision r14): since r14 each expiry is also an absolute epoch record, which on its own would carry a read site that was reverted to the
        # state string. With the epoch record reset to 0 only the date-and-time attribute carries the override, so every read site must still follow the attribute: held to the true expiry
        # in the repeated hour (hold, held_by and the effective reserve), and a running override can still be cancelled there. These cases pass on the package before r14 as well.
        for kind in KINDS:
            pw = world(text, now="2026-10-25 00:40:40", zone="Europe/London")
            start(pw, kind=kind, expiry_min=120)
            pw.w.set(EPOCH_E[kind], "0.0")
            t0 = exp_ts(pw, kind) - 7200
            for minutes in (59, 61, 90, 110, 119):
                pw.w.run_until(t0 + minutes * 60)
                if pw.state(HOLD) != "held" or held_by_of(pw, text) != kind:
                    add(f"{kind}, attribute alone (epoch reset to 0): {minutes} minutes in the hold reads {pw.state(HOLD)!r} held_by {held_by_of(pw, text)!r}")
                if kind == "prepare_power_cut" and pw.state(EFF) != "80":
                    add(f"{kind}, attribute alone (epoch reset to 0): {minutes} minutes in the effective reserve is {pw.state(EFF)}")
            pw = world(text, now="2026-10-25 00:40:40", zone="Europe/London")
            start(pw, kind=kind, expiry_min=120)
            pw.w.set(EPOCH_E[kind], "0.0")
            pw.w.run_until(exp_ts(pw, kind) - 3000)
            out = cancel(pw, kind=kind)
            if not out.startswith("CANCELLED") or pw.state(HOLD) != "clear" or exp_ts(pw, kind) > pw.w.t:
                add(f"cancel {kind} on the clock-change day, attribute alone (epoch reset to 0): {out[:40]!r} hold {pw.state(HOLD)!r}")
    except _Early:
        pass
    return bad


READ_RE_FIX1 = re.compile(r"\{%- set (\w+) = state_attr\('(input_datetime\.[a-z_]+)', 'timestamp'\) \| float\(none\) -%\}\n[ ]*\{%- set \1 = \1 if \([^\n]*\) else none -%\}")
cp = clock_problems(PKG_TEXT)
check("clock changes and the exact expiry second, for each kind: an override that ends in the repeated hour of the October clock change stays held "
      "until its true expiry (the old read released it 60 minutes early); held at the last second, clear at the expiry second; the spring-forward and ordinary "
      "days agree; the effective reserve and the cancel script follow the same instant; a missing or non-numeric attribute is unreadable (unknown); the instant is "
      "the attribute, never the state string", cp == [], str(cp[:3]))
check("no backend template parses an expiry (or any) helper state string with as_timestamp(states(...)): every expiry read is the timestamp attribute",
      re.findall(r"as_timestamp\(\s*states\(", PKG_TEXT) == [] and len(READ_RE_FIX1.findall(PKG_TEXT)) == 10, str(re.findall(r"as_timestamp\(\s*states\([^)]*\)", PKG_TEXT)))

print("[10] mutation: reverting any read site to the state string, or moving the expiry second, is caught by a running case above")
SITES = ["the cancel script, Hold battery", "the cancel script, Skip tonight", "the cancel script, Prepare for power cut",
         "the hold sensor's state, Hold battery", "the hold sensor's state, Skip tonight", "the hold sensor's state, Prepare for power cut",
         "the held_by attribute, Hold battery", "the held_by attribute, Skip tonight", "the held_by attribute, Prepare for power cut",
         "the effective reserve's power-cut expiry"]


def revert_site(text: str, k: int) -> str:
    """Read site k (file order) back to the old parse of the state string."""
    ms = list(READ_RE_FIX1.finditer(text))
    assert len(ms) == 10, len(ms)
    m = ms[k]
    return text[:m.start()] + "{%- set " + m.group(1) + " = as_timestamp(states('" + m.group(2) + "'), none) -%}" + text[m.end():]


def swap_once(text: str, old: str, new: str) -> str:
    assert text.count(old) == 1, (text.count(old), old[:60])
    return text.replace(old, new)


HOLD_LINE = "{%- if (a is not none and a > n) or (b is not none and b > n) or (c is not none and c > n) -%}held"
CUT_ACTIVE = "(e is none or e > n) and c is number"     # owner decision r14: the record counts while ACTIVE or UNREADABLE (it was `e is not none and e > n and c is number`: active only)
MUT10 = [(f"a read site reverted to the state string: {SITES[k]}", revert_site(PKG_TEXT, k)) for k in range(10)]
for v, kind_name in (("a", "Hold battery"), ("b", "Skip tonight"), ("c", "Prepare for power cut")):
    MUT10.append((f"the hold sensor releases {kind_name} 45 s early ({v} > n + 45)", swap_once(PKG_TEXT, HOLD_LINE, HOLD_LINE.replace(f"{v} > n", f"{v} > n + 45"))))
    MUT10.append((f"the hold sensor still holds {kind_name} at the expiry second ({v} >= n)", swap_once(PKG_TEXT, HOLD_LINE, HOLD_LINE.replace(f"{v} > n", f"{v} >= n"))))
if PKG_TEXT.count(CUT_ACTIVE) == 1:     # (a missing anchor is a failed check, not a crash of the suite: the anchor moved with the package text in owner decision r14)
    MUT10.append(("the effective reserve releases the power cut's reserve 45 s early (e > n + 45)", swap_once(PKG_TEXT, CUT_ACTIVE, CUT_ACTIVE.replace("e > n", "e > n + 45"))))
    MUT10.append(("the effective reserve still raises at the expiry second (e >= n)", swap_once(PKG_TEXT, CUT_ACTIVE, CUT_ACTIVE.replace("e > n", "e >= n"))))
else:
    check("mutant anchor: the effective reserve's power-cut condition", False, f"anchor found {PKG_TEXT.count(CUT_ACTIVE)}x, wanted 1")
caught10 = 0
for label, mutated in MUT10:
    try:
        yaml.safe_load(mutated)
    except yaml.YAMLError as exc:
        check(f"mutant loads as YAML: {label}", False, str(exc)[:80])
        continue
    found = clock_problems(mutated, stop_early=True)
    if found:
        caught10 += 1
        print(f"  PASS  mutant caught: {label} (first failing case: {found[0][:70]})")
    else:
        FAILURES.append(f"mutant survived: {label}")
        print(f"  FAIL  mutant survived: {label}")
check(f"{len(MUT10)} clock-change / expiry-second mutants, all caught by a running case", caught10 == len(MUT10), f"{caught10}/{len(MUT10)}")
check("control: the unmutated package passes the same running cases", cp == [])


# ================================================================================================================================
print("[11] the effective reserve is published rounded UP: never below the owner's own value (review finding 5)")
# ================================================================================================================================
# The sensor published known | max | round(0) | int. Home Assistant's round filter rounds half to even, so an owner reserve of 62.4 (or 62.5) was published as 62,
# below the owner's value, and the start scripts' rounded-up comparison then accepted a Stop SOC of 62. The helper is whole in the UI, but a service call
# checks only the helper's min and max. The inputs are now rounded UP to a whole percent before the larger is taken. The same for the running power cut's reserve.
ROUND_CASES = (  # (owner, running power cut reserve or None, published)
    (62.4, None, "63"), (62.0, None, "62"), (62.5, None, "63"), (0.2, None, "1"), (80, None, "80"), (0, None, "0"), (100, None, "100"), (99.5, None, "100"),
    (61.5, None, "62"), (62.6, None, "63"), (0.0, None, "0"), (0.5, None, "1"), (1.0, None, "1"),
    (40, 62.4, "63"), (40, 62.0, "62"), (40, 62.5, "63"), (40, 80, "80"), (40, 100, "100"), (40, 99.5, "100"), (40, 10.0, "40"),
    (None, 10.2, "11"), (None, 62.4, "63"), (None, 62.0, "62"), (None, 62.5, "63"), (None, 99.5, "100"), (None, 10.0, "10"),
    (70, 62.4, "70"), (62.4, 40, "63"), (62.4, 62.4, "63"), (62.1, 62.0, "63"), (62.0, 62.4, "63"), (80, 80, "80"))


def round_problems(text: str, stop_early: bool = False) -> list[str]:
    bad: list[str] = []

    def add(msg: str) -> None:
        bad.append(msg)
        if stop_early:
            raise _Early()

    try:
        for owner, cut, want in ROUND_CASES:
            pw = world(text, owner=owner)
            if cut is not None:
                pw.w.set(CUT_RESERVE_E, f"{float(cut)}")
                pw.set_local(EXPIRES_E["prepare_power_cut"], "2026-11-18 21:30:00")
            got = pw.state(EFF)
            if got != want:
                add(f"owner {owner}, power cut {cut}: published {got}, wanted {want}")
        # never below the owner's own value and never a whole percent above it: every tenth from 0.0 to 100.0
        pw = world(text, owner=0)
        for i in range(0, 1001):
            s = f"{i / 10:.1f}"
            pw.w.set(OWNER_RESERVE, s)
            got = pw.state(EFF)
            if got != str(-(-i // 10)):
                add(f"owner {s}: published {got}, wanted {-(-i // 10)}")
                break
        # the same for the running power cut's reserve (owner unreadable, so only the cut counts): every tenth from 10.0 to 100.0
        pw = world(text, owner=None)
        pw.set_local(EXPIRES_E["prepare_power_cut"], "2026-11-18 21:30:00")
        for i in range(100, 1001):
            s = f"{i / 10:.1f}"
            pw.w.set(CUT_RESERVE_E, s)
            got = pw.state(EFF)
            if got != str(-(-i // 10)):
                add(f"power cut reserve {s}: published {got}, wanted {-(-i // 10)}")
                break
    except _Early:
        pass
    return bad


rp = round_problems(PKG_TEXT)
check("the effective reserve is rounded UP (62.4 -> 63, 62.0 -> 62, 62.5 -> 63, 0.2 -> 1, 80 -> 80, 99.5 -> 100), for the owner's reserve and the running power cut's, "
      "and over every tenth never below the input and never a whole percent above it", rp == [], str(rp[:3]))

print("[11] mutation: rounding down, rounding half to even, or rounding only one input up is caught by a running case above")
CEIL_O = "{%- set o = (o | round(0, 'ceil')) if o is not none else none -%}"
CEIL_C = "{%- set c = (c | round(0, 'ceil')) if c is not none else none -%}"
MUT11 = [
    ("the effective reserve rounds down (floor): the mutant that survived the review", [(CEIL_O, CEIL_O.replace("'ceil'", "'floor'")), (CEIL_C, CEIL_C.replace("'ceil'", "'floor'"))]),
    ("the effective reserve rounds half to even (the earlier round(0))", [(CEIL_O, CEIL_O.replace("round(0, 'ceil')", "round(0)")), (CEIL_C, CEIL_C.replace("round(0, 'ceil')", "round(0)"))]),
    ("only the owner's reserve is rounded up", [(CEIL_C, "{%- set c = c -%}")]),
    ("only the power cut's reserve is rounded up", [(CEIL_O, "{%- set o = o -%}")]),
    ("the owner's reserve rounds down, the power cut's up", [(CEIL_O, CEIL_O.replace("'ceil'", "'floor'"))]),
]
caught11 = 0
for label, pairs in MUT11:
    mutated = PKG_TEXT
    for old, new in pairs:
        assert mutated.count(old) == 1, (label, old)
        mutated = mutated.replace(old, new)
    found = round_problems(mutated, stop_early=True)
    if found:
        caught11 += 1
        print(f"  PASS  mutant caught: {label} (first failing case: {found[0][:70]})")
    else:
        FAILURES.append(f"mutant survived: {label}")
        print(f"  FAIL  mutant survived: {label}")
check(f"{len(MUT11)} reserve-rounding mutants, all caught by a running case", caught11 == len(MUT11), f"{caught11}/{len(MUT11)}")
check("control: the unmutated package passes the same running cases", rp == [])

# ================================================================================================================================
print("[12] test honesty: cancel ends only its own kind, the raise-only boundary, and an unreadable record of each kind (review finding 4)")
# ================================================================================================================================
# The independent review mutated the package and five safety-relevant mutants survived every running check: M3 (cancelling Skip tonight also ends Hold battery) and M4
# (cancelling Prepare for power cut also ends Skip tonight), so the README's 'cancel ends only its own kind' was claimed but not proved; M5 (the raise-only test weakened to
# 'the power-cut reserve may be 5 below the owner's', the only refusal case having a 10 point gap); M1 (Hold battery released 45 s early, covered with finding 1 in [10] for
# every kind: the exact expiry second) and M11 (the hold sensor ignores an unreadable Prepare for power cut record, the only unreadable-record case using Skip tonight).
# These are additions only: no existing check, mutant list or assertion changed, and no package line changed with them.
import itertools as _it  # noqa: E402

class _Early12(Exception):
    pass


def exp_ts12(pw: P.PlanWorld, kind: str) -> float:
    return float(pw.w.state_attr(EXPIRES_E[kind], "timestamp"))


def held_by12(pw: P.PlanWorld, text: str) -> str:
    return str(pw.w.render(yaml.safe_load(text)["template"][0]["sensor"][0]["attributes"]["held_by"])).strip()


STAY_MIN = {"hold_battery": 240, "skip_tonight": 300, "prepare_power_cut": 600}


def cancel_problems(text: str, stop_early: bool = False) -> list[str]:
    """With all three kinds active, cancelling any one (in every order) ends that kind and leaves the other two, their records, the hold sensor, held_by and the
    effective reserve exactly as they were."""
    bad: list[str] = []

    def add(msg: str) -> None:
        bad.append(msg)
        if stop_early:
            raise _Early12()

    def rec(pw, k):
        return (pw.w.states[START_E[k]], pw.w.states[EXPIRES_E[k]])

    try:
        for perm in _it.permutations(KINDS):
            pw = world(text)
            for k in KINDS:
                out = start(pw, kind=k, expiry_min=STAY_MIN[k])
                if not out.startswith("STARTED"):
                    add(f"{perm}: {k} did not start: {out[:50]!r}")
            running = list(KINDS)
            cut_reserve = pw.w.states[CUT_RESERVE_E]
            for K in perm:
                before = {k: rec(pw, k) for k in running if k != K}
                own_start = pw.w.states[START_E[K]]
                rev = float(pw.state(REV))
                out = cancel(pw, kind=K)
                running.remove(K)
                tag = f"order {'>'.join(perm)}, cancelling {K}"
                if not out.startswith(f"CANCELLED {K}"):
                    add(f"{tag}: {out[:50]!r}")
                if pw.w.states[START_E[K]] != own_start or exp_ts12(pw, K) > pw.w.t:
                    add(f"{tag}: the cancelled record is not just ended (expires {exp_ts12(pw, K) - pw.w.t:+.0f} s)")
                after = {k: rec(pw, k) for k in running}
                if after != before:
                    add(f"{tag}: it changed the record of {[k for k in running if after[k] != before[k]]}")
                if pw.w.states[CUT_RESERVE_E] != cut_reserve:
                    add(f"{tag}: it changed the power-cut reserve record")
                want = [k for k in KINDS if k in running]
                if pw.state(HOLD) != ("held" if want else "clear") or held_by12(pw, text) != ",".join(want):
                    add(f"{tag}: the hold reads {pw.state(HOLD)!r} held_by {held_by12(pw, text)!r}, wanted {want}")
                if pw.state(EFF) != ("80" if "prepare_power_cut" in running else "40"):
                    add(f"{tag}: the effective reserve is {pw.state(EFF)}")
                if float(pw.state(REV)) != rev + 1:
                    add(f"{tag}: the revision went {rev} -> {pw.state(REV)}")
    except _Early12:
        pass
    return bad


RAISE_CASES = (  # (power-cut reserve limit, owner's reserve, starts?)  equal, 1 and 0.5 below, 5 below (the M5 gap), 1 and 0.5 above
    (80, 80, True), (80, 81, False), (80, 80.5, False), (80, 85, False), (80, 86, False), (80, 100, False), (80, 79, True), (80, 79.5, True), (80, 0, True), (80, 0.5, True),
    (10, 10, True), (10, 10.5, False), (10, 11, False), (10, 9.5, True), (100, 100, True), (100, 99.5, True), (100, 99, True))


def raise_only_problems(text: str, stop_early: bool = False) -> list[str]:
    """Prepare for power cut starts only when its reserve is at least the owner's current reserve: the boundary on both sides, 0.5 and 1 points, and 5 points below."""
    bad: list[str] = []
    try:
        for cut, owner, starts in RAISE_CASES:
            pw = world(text, owner=owner, policy={"cut_reserve": cut})
            before = snapshot(pw, exclude=(LAST,))
            out = start(pw, kind="prepare_power_cut", expiry_min=60)
            if starts:
                ok = out.startswith("STARTED prepare_power_cut") and pw.state(CUT_RESERVE_E) == f"{float(cut)}" and pw.state(HOLD) == "held" and pw.state(EFF) == str(cut)
            else:
                after = snapshot(pw, exclude=(LAST,))
                ok = out.startswith("REFUSED RESERVE_BELOW_CURRENT") and after == before and NOTE in pw.w.notifications and pw.state(HOLD) == "clear"
            if not ok:
                bad.append(f"power-cut reserve {cut}, owner's reserve {owner}: wanted {'a start' if starts else 'RESERVE_BELOW_CURRENT, nothing changed'}, got {out[:60]!r}")
                if stop_early:
                    break
    except Exception as exc:  # noqa: BLE001 - a package that cannot run is a failed proof
        bad.append(f"raised {type(exc).__name__}: {str(exc)[:120]}")
    return bad


def unreadable_problems(text: str, stop_early: bool = False) -> list[str]:
    """An unreadable record of EACH kind: unknown with the other two clear, held (naming only the running one) when another kind is running."""
    bad: list[str] = []

    def add(msg: str) -> None:
        bad.append(msg)
        if stop_early:
            raise _Early12()

    ways = [("unavailable", None), ("unknown", None), ("empty", None)]
    if "'timestamp') | float(none)" in text:      # a package that reads the expiry from the timestamp attribute (the clock-change fix) also has this way
        ways.append(("a valid state with no timestamp attribute", {"has_date": True, "has_time": True}))
    try:
        for K in KINDS:
            others = [k for k in KINDS if k != K]
            for label, attrs in ways:
                def break_record(pw, K=K, label=label, attrs=attrs):
                    if attrs is None:
                        pw.w.set(EXPIRES_E[K], {"unavailable": "unavailable", "unknown": "unknown", "empty": ""}[label])
                    else:
                        pw.w.set(EXPIRES_E[K], "2026-11-18 09:00:00", attrs)
                pw = world(text)
                break_record(pw)
                if pw.state(HOLD) != "unknown" or held_by12(pw, text) != "":
                    add(f"{K} unreadable ({label}), the others clear: the hold reads {pw.state(HOLD)!r}, wanted unknown")
                for J in others:
                    pw = world(text)
                    break_record(pw)
                    start(pw, kind=J, expiry_min=30)
                    if pw.state(HOLD) != "held" or held_by12(pw, text) != J:
                        add(f"{K} unreadable ({label}) while {J} runs: the hold reads {pw.state(HOLD)!r} held_by {held_by12(pw, text)!r}, wanted held by {J} only")
                pw = world(text)
                break_record(pw)
                for J in others:
                    start(pw, kind=J, expiry_min=30)
                if pw.state(HOLD) != "held" or held_by12(pw, text) != ",".join(others):
                    add(f"{K} unreadable ({label}) while {others} run: the hold reads {pw.state(HOLD)!r} held_by {held_by12(pw, text)!r}")
    except _Early12:
        pass
    return bad


cl = cancel_problems(PKG_TEXT)
check("cancel ends only its own kind: with all three active, cancelling any one (all six orders) ends that kind, bumps the revision, and leaves the other two records, "
      "their start and expiry, the power-cut reserve record, the hold, held_by and the effective reserve exactly as they were", cl == [], str(cl[:3]))
ro = raise_only_problems(PKG_TEXT)
check("raise-only boundary: a power-cut reserve limit equal to the owner's reserve starts; 0.5, 1 and 5 points below it is refused (RESERVE_BELOW_CURRENT, nothing "
      "changed but the last answer and one notification); 0.5 and 1 points above starts", ro == [], str(ro[:3]))
ur = unreadable_problems(PKG_TEXT)
check("an unreadable expiry record of EACH kind (unavailable, unknown, empty, no timestamp attribute) reads unknown with the other two clear and held (naming only the "
      "running kinds) when another kind runs", ur == [], str(ur[:3]))

print("[12] mutation: cancel touching another kind, a weakened raise-only test, and an ignored unreadable record are each caught by a running case above")
_CANCEL_START = PKG_TEXT.index("  ecco_plan_override_cancel:")
_CANCEL_END = PKG_TEXT.index("\nautomation:")
_CSEG = PKG_TEXT[_CANCEL_START:_CANCEL_END]


def _write_block(kind: str, ind: str) -> str:
    return (f"{ind}- action: input_datetime.set_datetime\n{ind}  target:\n{ind}    entity_id: input_datetime.ecco_plan_override_{kind}_expires\n"
            f"{ind}  data:\n{ind}    timestamp: \"{{{{ decision.expires_ts }}}}\"\n")


def cross_cancel(k: str, j: str) -> str:
    """The cancel script's branch for kind k also ends kind j."""
    ind = "                  " if k == "prepare_power_cut" else "                      "
    seg = _CSEG
    anchor = _write_block(k, ind)
    assert seg.count(anchor) == 1, (k, seg.count(anchor))
    return PKG_TEXT[:_CANCEL_START] + seg.replace(anchor, anchor + _write_block(j, ind)) + PKG_TEXT[_CANCEL_END:]


RAISE_LINE = "kind_in == 'prepare_power_cut' and p[7] < owner -%}"
HOLD_UNKNOWN = "{%- elif a is none or b is none or c is none -%}unknown"
MUT12 = []
for _k, _j in ((_a, _b) for _a in KINDS for _b in KINDS if _a != _b):
    _tag = " (M3)" if (_k, _j) == ("skip_tonight", "hold_battery") else (" (M4)" if (_k, _j) == ("prepare_power_cut", "skip_tonight") else "")
    MUT12.append((f"cancel of {_k} also ends {_j}{_tag}", cross_cancel(_k, _j), cancel_problems))
for _label, _new in (("the power-cut reserve may be 5 below the owner's (M5)", "kind_in == 'prepare_power_cut' and p[7] < owner - 5 -%}"),
                     ("the power-cut reserve may be 0.5 below the owner's", "kind_in == 'prepare_power_cut' and p[7] < owner - 0.5 -%}"),
                     ("the power-cut reserve must be 0.5 above the owner's", "kind_in == 'prepare_power_cut' and p[7] < owner + 0.5 -%}"),
                     ("a power-cut reserve equal to the owner's is refused", "kind_in == 'prepare_power_cut' and p[7] <= owner -%}"),
                     ("the owner's reserve is rounded before the comparison", "kind_in == 'prepare_power_cut' and p[7] < (owner | round(0)) -%}")):
    assert PKG_TEXT.count(RAISE_LINE) == 1
    MUT12.append((_label, PKG_TEXT.replace(RAISE_LINE, _new), raise_only_problems))
for _label, _new in (("the hold sensor ignores an unreadable Prepare for power cut record (M11)", "{%- elif a is none or b is none -%}unknown"),
                     ("the hold sensor ignores an unreadable Skip tonight record", "{%- elif a is none or c is none -%}unknown"),
                     ("the hold sensor ignores an unreadable Hold battery record", "{%- elif b is none or c is none -%}unknown")):
    assert PKG_TEXT.count(HOLD_UNKNOWN) == 1
    MUT12.append((_label, PKG_TEXT.replace(HOLD_UNKNOWN, _new), unreadable_problems))
caught12 = 0
for label, mutated, fn in MUT12:
    try:
        yaml.safe_load(mutated)
    except yaml.YAMLError as exc:
        check(f"mutant loads as YAML: {label}", False, str(exc)[:80])
        continue
    found = fn(mutated, stop_early=True)
    if found:
        caught12 += 1
        print(f"  PASS  mutant caught: {label} (first failing case: {found[0][:90]})")
    else:
        FAILURES.append(f"mutant survived: {label}")
        print(f"  FAIL  mutant survived: {label}")
check(f"{len(MUT12)} mutants (the six cross-kind cancels, the weakened raise-only tests, the ignored unreadable records), all caught by a running case", caught12 == len(MUT12) == 14, f"{caught12}/{len(MUT12)}")
check("control: the unmutated package passes the same running cases", cl == [] and ro == [] and ur == [])

# ================================================================================================================================
print("[13] test honesty, part 2: the state guard at EACH of the ten timestamp read sites (re-review of 18 Nov 2026, minor 4)")
# ================================================================================================================================
# Every expiry read is `state_attr(helper, 'timestamp') | float(none)` and then `a if (a is number and a == a and states(helper) not in bad) else none`: the attribute is trusted only when
# the helper's state is not unknown, unavailable or empty. The simulator KEEPS a helper's attributes when its state is set to unavailable; real Home Assistant drops them. So a record
# that reports unavailable (or unknown, or empty) but still carries a STALE timestamp attribute is what reaches a site without the guard. [12] covered the guard at one site (the hold sensor's
# state, Hold battery); removing it at the reserve sensor's power-cut site, at the cancel script's three sites and at the three held_by sites passed every check. The checks below put each
# of the three kinds, in each of the three bad states, with a stale attribute that is in the FUTURE (the override was still running: a missing guard reads it as active) or in the PAST (it had
# ended: a missing guard reads it as a readable, expired record), and require at EACH site that the record is UNREADABLE: the hold sensor reads unknown, held_by does not name it (also when another
# kind is running), the effective reserve skips a power cut it cannot trust, and the cancel script proceeds and repairs the record (a stale PAST attribute: a missing guard answers NOT_ACTIVE).
# The ten mutants remove the guard at one site each; the first problem found must come from the check of THAT site. Existing checks are untouched.
BAD_STATES = (("unavailable", "unavailable"), ("unknown", "unknown"), ("empty", ""))
SITE_TAGS = ["cancel", "cancel", "cancel", "hold sensor", "hold sensor", "hold sensor", "held_by", "held_by", "held_by", "effective reserve"]


def stale_record(text: str, kind: str, bad_state: str, stale: str) -> P.PlanWorld:
    """`kind`'s expiry helper reports `bad_state` but keeps a stale timestamp attribute (an hour ahead: `future`, ten minutes behind: `past`); the power-cut reserve is 80 and the owner's is 40."""
    pw = world(text, owner=40)
    pw.w.set(CUT_RESERVE_E, "80.0")
    ts = pw.w.t + 3600 if stale == "future" else pw.w.t - 600
    pw.w.set(EXPIRES_E[kind], bad_state, {"timestamp": ts, "has_date": True, "has_time": True})
    return pw


def guard_problems(text: str, stop_early: bool = False) -> list[str]:
    bad: list[str] = []

    def add(msg: str) -> None:
        bad.append(msg)
        if stop_early:
            raise _Early()

    try:
        for kind in KINDS:
            others = [k for k in KINDS if k != kind]
            for bname, bstate in BAD_STATES:
                for stale in ("future", "past"):
                    tag = f"{kind}, state {bname}, stale {stale} attribute"
                    pw = stale_record(text, kind, bstate, stale)
                    if pw.state(HOLD) != "unknown":
                        add(f"hold sensor, {tag}: the hold reads {pw.state(HOLD)!r}, wanted 'unknown' (an unreadable record)")
                    if held_by_of(pw, text) != "":
                        add(f"held_by, {tag}: held_by reads {held_by_of(pw, text)!r}, wanted '' (an unreadable record is not named)")
                    # owner decision r14: a power-cut record that cannot be trusted RETAINS the raised reserve (80) until a cancel or a readable record reconciles it; it was skipped (the owner's 40) before
                    if kind == "prepare_power_cut" and pw.state(EFF) != "80":
                        add(f"effective reserve, {tag}: the effective reserve is {pw.state(EFF)}, wanted 80 (the power cut's record cannot be trusted, so its raised reserve is retained)")
                    pw = stale_record(text, kind, bstate, stale)
                    out = cancel(pw, kind=kind)
                    repaired = pw.state(EXPIRES_E[kind]) not in ("unavailable", "unknown", "") and exp_ts(pw, kind) <= pw.w.t
                    if not out.startswith("CANCELLED") or not repaired or pw.state(HOLD) != "clear":
                        add(f"cancel, {tag}: {out[:50]!r}, record {pw.state(EXPIRES_E[kind])!r}, hold {pw.state(HOLD)!r}; wanted CANCELLED, the record repaired and the hold clear")
                    if stale == "future":
                        # another kind is running: held, and it alone is named
                        pw = stale_record(text, kind, bstate, stale)
                        start(pw, kind=others[0], expiry_min=30)
                        if pw.state(HOLD) != "held" or held_by_of(pw, text) != others[0]:
                            add(f"held_by, {tag}, with {others[0]} running: the hold reads {pw.state(HOLD)!r} held_by {held_by_of(pw, text)!r}, wanted held, naming only {others[0]}")
    except _Early:
        pass
    return bad


gp = guard_problems(PKG_TEXT)
check("the state guard at every timestamp read site: each kind, with its record unavailable, unknown or empty and a stale attribute in the future or the past (18 cases per site family): "
      "the hold sensor reads unknown, held_by does not name it (also with another kind running), the effective reserve skips an untrusted power cut, and the cancel script proceeds and repairs "
      "the record", gp == [], str(gp[:3]))

print("[13] mutation: removing the state guard at any one of the ten read sites is caught by the running check of that site")
GUARD_FRAG = re.compile(r" and states\('input_datetime\.[a-z_]+'\) not in bad")


def drop_guard_site(text: str, k: int) -> str:
    """Read site k (file order: the cancel script x3, the hold sensor's state x3, held_by x3, the effective reserve's power-cut expiry) without the `states(helper) not in bad` test."""
    ms = list(READ_RE_FIX1.finditer(text))
    assert len(ms) == 10, len(ms)
    seg = ms[k].group(0)
    new = GUARD_FRAG.sub("", seg)
    assert new != seg and GUARD_FRAG.search(new) is None, k
    return text[:ms[k].start()] + new + text[ms[k].end():]


caught13 = 0
for k in range(10):
    label = f"the state guard removed at a read site: {SITES[k]}"
    mutated = drop_guard_site(PKG_TEXT, k)
    try:
        yaml.safe_load(mutated)
    except yaml.YAMLError as exc:
        check(f"mutant loads as YAML: {label}", False, str(exc)[:80])
        continue
    found = guard_problems(mutated, stop_early=True)
    if found and found[0].startswith(SITE_TAGS[k]):
        caught13 += 1
        print(f"  PASS  mutant caught: {label} (first failing case: {found[0][:90]})")
    else:
        FAILURES.append(f"mutant survived: {label}")
        print(f"  FAIL  mutant survived: {label} ({found[:1]})")
check("10 guard mutants (the state guard removed at each read site), each caught by the running check of its own site", caught13 == 10, f"{caught13}/10")
check("control: the unmutated package passes the same running cases", gp == [])

# ================================================================================================================================
print("[14] an override's expiry is also an ABSOLUTE epoch record, read raise-only with the date-and-time attribute (owner decision r14, 19 Nov 2026; known limitations 11, 17, 19, 23)")
# ================================================================================================================================
# THE PROBLEM (known limitation 19; recalled from Home Assistant core, NOT verified live): a restart restores a date-and-time helper from its STATE STRING, local wall-clock time without an
# offset, so an expiry in the repeated hour of the autumn clock change (01:00 to 01:59 on the fall-back day, Europe/London) is restored as the FIRST of the two equal local times, 60 minutes
# EARLY, and the hold and the raised reserve would release up to 60 minutes early. THE DECISION (owner, r14): prefer absolute timestamps; if the instant cannot be established reliably fail
# closed and keep the safety-related override; do not blindly extend every override by an hour and do not silently alter the owner's deadline. THE DESIGN: an input_number per kind holds the expiry as
# epoch seconds (the SAME number the start script already computes, so nothing is extended), written BEFORE the date-and-time expiry; every expiry read takes the later of the two valid sources
# (raise-only), a kind is unreadable when either source is not a valid reading, and the raised reserve is retained while its expiry is unreadable. WHAT THIS SECTION DOES: it adds a RESTART step to
# the offline model (_plan_sim.PlanWorld.restart) and runs the cases the owner listed. Every earlier section is untouched except where it pinned the old fail-open behaviour: the effective
# reserve used to SKIP an unreadable power-cut record ([10] and [13] now expect the raised reserve to be retained; the old behaviour is the mutant below that the new cases kill).
# The restore model is a RECOLLECTION, not verified live: these checks prove the package against the model, not against Home Assistant.
LONDON, AUTUMN, ORDINARY = "Europe/London", "2026-10-25 00:40:40", "2026-11-17 21:30:40"   # AUTUMN (BST): a 120 minute override ends at 01:40 GMT, inside the repeated hour
DAYS14 = (  # (label, local start, length in minutes, restart moments in minutes after the start (None: no restart))
    ("October repeated hour (a 120 minute override from 00:40 BST ends at 01:40 GMT)", AUTUMN, 120, (None, 30, 61, 90, 110, 119, 125)),
    ("October day, expiry after the repeated hour", "2026-10-25 01:10:40", 180, (None, 30, 100, 179, 185)),
    ("October night across the repeated hour, expiry before it", "2026-10-24 21:30:40", 600, (None, 240, 300, 380, 600)),
    ("spring-forward day", "2027-03-28 00:30:40", 120, (None, 30, 61, 110)),
    ("ordinary day", ORDINARY, 120, (None, 30, 61, 110)),
)
EPOCH_BAD14 = (("missing", None), ("unavailable", "unavailable"), ("unknown", "unknown"), ("empty", ""), ("nan", "nan"), ("inf", "inf"), ("negative", "-5.0"),
               ("junk", "abc"), ("above its range", "4102444801.0"))


_HB14: dict[str, str] = {}


def held_by14(pw: P.PlanWorld, text: str) -> str:
    """held_by_of, with the attribute template parsed once per package text (the suite reads it thousands of times)."""
    tpl = _HB14.get(text)
    if tpl is None:
        tpl = _HB14[text] = yaml.safe_load(text)["template"][0]["sensor"][0]["attributes"]["held_by"]
    return str(pw.w.render(tpl)).strip()


class _Stop14(Exception):
    pass


class _G:
    """The problems of one group of cases; `stop_early` ends the group at the first one (the mutants)."""

    def __init__(self, stop_early: bool):
        self.bad: list[str] = []
        self.stop_early = stop_early

    def add(self, msg: str) -> None:
        self.bad.append(msg)
        if self.stop_early:
            raise _Stop14()


def put_dt14(pw: P.PlanWorld, kind: str, ts: float) -> None:
    """The kind's date-and-time expiry at the instant `ts`, as Home Assistant stores it from an aware datetime (state: local wall clock; attribute: the instant)."""
    pw._store_datetime(EXPIRES_E[kind], datetime.fromtimestamp(ts, pw.zone))


def epoch_of(pw: P.PlanWorld, kind: str):
    try:
        return float(pw.state(EPOCH_E[kind]))
    except ValueError:
        return None


def probe14(g: _G, pw: P.PlanWorld, text: str, exps: dict, tag: str) -> None:
    """Right now (the model clock): the hold, held_by and the effective reserve must equal the TRUE instants: held while `expiry > now`, clear from the expiry second."""
    t = pw.w.t
    want = [k for k in KINDS if k in exps and exps[k] > t]
    got, by = pw.state(HOLD), held_by14(pw, text)
    rel = t - (min(exps.values()) if exps else t)
    if got != ("held" if want else "clear") or by != ",".join(want):
        g.add(f"{tag}: {rel:+.0f} s from the first true expiry the hold reads {got!r} held_by {by!r}, wanted {want}")
    if pw.state(EFF) != ("80" if "prepare_power_cut" in want else "40"):
        g.add(f"{tag}: {rel:+.0f} s from the first true expiry the effective reserve is {pw.state(EFF)}, wanted {'80' if 'prepare_power_cut' in want else '40'}")


def running(text: str, kind: str, minutes: int = 120, now: str = ORDINARY):
    """A world on `now` (Europe/London) with `kind` started for `minutes`; returns (pw, true expiry)."""
    pw = world(text, now=now, zone=LONDON)
    out = start(pw, kind=kind, expiry_min=minutes)
    if not out.startswith("STARTED"):
        raise AssertionError(f"{kind} did not start: {out[:60]!r}")
    return pw, exp_ts(pw, kind)


def g_writes(text: str, stop_early: bool = False) -> list[str]:
    """What the start and the cancel script write: the epoch is the same number as the expiry, written first, for the kind's own record only."""
    g = _G(stop_early)
    try:
        for kind in KINDS:
            pw = world(text, now=ORDINARY, zone=LONDON)
            n0 = len(pw.w.service_log)
            out = start(pw, kind=kind, expiry_min=90)
            if not out.startswith("STARTED"):
                g.add(f"{kind}: did not start: {out[:50]!r}")
                continue
            exp = exp_ts(pw, kind)
            if epoch_of(pw, kind) != exp:
                g.add(f"{kind}: the start wrote the epoch record {pw.state(EPOCH_E[kind])!r}, wanted the same instant as the date-and-time expiry ({exp})")
            order = [e for s, e, _d in pw.services(n0) if s.startswith("input_")]
            others = (set(order) & set(EPOCH_E.values())) - {EPOCH_E[kind]}
            if EPOCH_E[kind] not in order:
                g.add(f"{kind}: the start did not write its epoch record")
            elif order.index(EPOCH_E[kind]) > order.index(EXPIRES_E[kind]):
                g.add(f"{kind}: the epoch record is written AFTER the date-and-time expiry")
            elif kind == "prepare_power_cut" and not order.index(CUT_RESERVE_E) < order.index(EPOCH_E[kind]) < order.index(START_E[kind]) < order.index(EXPIRES_E[kind]):
                g.add(f"{kind}: the write order is not reserve, epoch, start, expiry: {[o.split('.')[1][-24:] for o in order]}")
            if others:
                g.add(f"{kind}: the start also wrote another kind's epoch record {sorted(others)}")
        pw = world(text, now=ORDINARY, zone=LONDON)
        for k in KINDS:
            start(pw, kind=k, expiry_min=90)
        for K in KINDS:
            before = {k: pw.state(EPOCH_E[k]) for k in KINDS if k != K}
            n0, t_c = len(pw.w.service_log), pw.w.t
            out = cancel(pw, kind=K)
            order = [e for s, e, _d in pw.services(n0) if s.startswith("input_")]
            want = t_c // 60 * 60
            if not out.startswith(f"CANCELLED {K}"):
                g.add(f"cancel {K}: {out[:50]!r}")
            if epoch_of(pw, K) != want or exp_ts(pw, K) != want:
                g.add(f"cancel {K}: the epoch record {epoch_of(pw, K)} and the date-and-time expiry {exp_ts(pw, K)} are not both the cancel instant {want} (the minute-floored now)")
            if EPOCH_E[K] not in order or (set(order) & set(EPOCH_E.values())) - {EPOCH_E[K]}:
                g.add(f"cancel {K}: it must write its own epoch record and no other: {[o.split('.')[1][-24:] for o in order]}")
            if {k: pw.state(EPOCH_E[k]) for k in KINDS if k != K} != before:
                g.add(f"cancel {K}: it changed another kind's epoch record")
    except _Stop14:
        pass
    return g.bad


def g_restart(text: str, stop_early: bool = False) -> list[str]:
    """The October repeated hour, the spring-forward day and an ordinary day, every kind, without a restart and with one (before, in and after the hour; an expiry outside it)."""
    g = _G(stop_early)
    try:
        for label, started, minutes, restarts in DAYS14:
            for kind in KINDS:
                for r in restarts:
                    pw, exp = running(text, kind, minutes, started)
                    t0 = exp - minutes * 60
                    tag = f"{label}, {kind}, " + ("no restart" if r is None else f"restart {r} min in")
                    tr = None if r is None else t0 + r * 60
                    times = {t0 + m * 60 for m in (30, 61, 90, 110)} | {exp - 60, exp - 1, exp, exp + 1, exp + 61}
                    if tr is not None:
                        times |= {tr, tr + 61}
                    pending = tr is not None
                    for t in sorted(x for x in times if x >= pw.w.t):
                        if pending and tr <= t:
                            pw.w.run_until(tr)
                            pw.restart("first")
                            pending = False
                        pw.w.run_until(t)
                        probe14(g, pw, text, {kind: exp}, tag)
        # all three running at once, every expiry in the repeated hour (each start moves the model clock by 30 s, so the minute-floored expiries differ), a restart inside it
        for r in (None, 61, 90, 115):
            pw = world(text, now=AUTUMN, zone=LONDON)
            for k in KINDS:
                start(pw, kind=k, expiry_min=120)
            exps = {k: exp_ts(pw, k) for k in KINDS}
            first = min(exps.values())
            tr = None if r is None else first - 7200 + r * 60
            times = {first - 7200 + m * 60 for m in (61, 90, 110)} | {e + d for e in exps.values() for d in (-1, 0, 1, 61)}
            if tr is not None:
                times |= {tr}
            pending = tr is not None
            for t in sorted(x for x in times if x >= pw.w.t):
                if pending and tr <= t:
                    pw.w.run_until(tr)
                    pw.restart("first")
                    pending = False
                pw.w.run_until(t)
                probe14(g, pw, text, exps, f"all three running, " + ("no restart" if r is None else f"restart {r} min in"))
    except _Stop14:
        pass
    return g.bad


def g_cancel(text: str, stop_early: bool = False) -> list[str]:
    """Start then cancel then restart (stays released); a restart in the repeated hour and then a cancel inside it (allowed, releases); a cancel when it is really over (NOT_ACTIVE)."""
    g = _G(stop_early)
    try:
        for kind in KINDS:
            # (a) cancel inside the repeated hour, then restart (twice): it stays released, and a second cancel finds nothing to cancel
            pw, exp = running(text, kind, 120, AUTUMN)
            pw.w.run_until(exp - 3000)
            out = cancel(pw, kind=kind)
            tag = f"{kind}, cancelled 50 minutes before its true expiry then restarted"
            if not out.startswith("CANCELLED") or pw.state(HOLD) != "clear" or pw.state(EFF) != "40":
                g.add(f"{tag}: {out[:40]!r} hold {pw.state(HOLD)!r} reserve {pw.state(EFF)}")
            if epoch_of(pw, kind) is None or epoch_of(pw, kind) > pw.w.t or epoch_of(pw, kind) != exp_ts(pw, kind):
                g.add(f"{tag}: the epoch record {epoch_of(pw, kind)} is not the cancel instant {exp_ts(pw, kind)}")
            for t in (pw.w.t, exp - 1500, exp - 1, exp, exp + 61):
                pw.w.run_until(t)
                pw.restart("first")
                probe14(g, pw, text, {}, tag + " ... " + str(int(t - exp)))
            if not cancel(pw, kind=kind).startswith("REFUSED NOT_ACTIVE"):
                g.add(f"{tag}: a second cancel was not refused as NOT_ACTIVE")
            # (b) a restart inside the repeated hour (the attribute is now 60 minutes early), then a cancel inside it: allowed, and it releases
            pw, exp = running(text, kind, 120, AUTUMN)
            pw.w.run_until(exp - 1800)
            pw.restart("first")
            probe14(g, pw, text, {kind: exp}, f"{kind}, restarted at 01:10 GMT")
            pw.w.run_until(exp - 1500)
            out = cancel(pw, kind=kind)
            tag = f"{kind}, restarted in the repeated hour then cancelled inside it"
            if not out.startswith("CANCELLED") or pw.state(HOLD) != "clear" or pw.state(EFF) != "40" or epoch_of(pw, kind) is None or epoch_of(pw, kind) > pw.w.t:
                g.add(f"{tag}: {out[:40]!r} hold {pw.state(HOLD)!r} reserve {pw.state(EFF)} epoch {epoch_of(pw, kind)}")
            for t in (exp - 1, exp, exp + 61):
                pw.w.run_until(t)
                pw.restart("first")
                probe14(g, pw, text, {}, tag)
            # (c) restarted after the true expiry: nothing to cancel, nothing changed
            pw, exp = running(text, kind, 120, AUTUMN)
            pw.w.run_until(exp + 120)
            pw.restart("first")
            rev = pw.state(REV)
            if not cancel(pw, kind=kind).startswith("REFUSED NOT_ACTIVE") or pw.state(REV) != rev:
                g.add(f"{kind}: a cancel after the true expiry (and a restart) is not NOT_ACTIVE with the revision unchanged")
            # (d) the last second: cancel allowed one second before the expiry, refused AT the expiry second
            for off, allowed in ((-1, True), (0, False)):
                pw, exp = running(text, kind, 120, AUTUMN)
                pw.w.run_until(exp + off)
                pw.restart("first")
                out = cancel(pw, kind=kind)
                if allowed != out.startswith("CANCELLED"):
                    g.add(f"{kind}: a cancel {off:+d} s from the true expiry (after a restart) answers {out[:40]!r}")
    except _Stop14:
        pass
    return g.bad


def g_abnormal(text: str, stop_early: bool = False) -> list[str]:
    """The epoch record missing, reset, unavailable, unknown, empty, nan, infinite, negative, out of range or junk; the attribute missing; both unreadable; stale-early and stale-late sources;
    the stored reserve while the expiry is unreadable."""
    g = _G(stop_early)
    held_eff = lambda kind: "80" if kind == "prepare_power_cut" else "40"   # noqa: E731 - the effective reserve while `kind` is held or retained (the stored cut reserve is 80)
    try:
        for kind in KINDS:
            others = [k for k in KINDS if k != kind]
            for label, restored in EPOCH_BAD14:
                tag = f"{kind}, epoch {label}"
                # (A) the attribute still shows it running: held, the cut's reserve kept, a cancel allowed (and it repairs the epoch record); at the expiry second the record is unreadable: unknown
                pw, exp = running(text, kind)
                pw.restart("exact", {EPOCH_E[kind]: restored})
                probe14(g, pw, text, {kind: exp}, tag + ", attribute running")
                pw.w.run_until(exp - 1)
                probe14(g, pw, text, {kind: exp}, tag + ", attribute running")
                pw.w.run_until(exp)
                if pw.state(HOLD) != "unknown" or held_by14(pw, text) != "" or pw.state(EFF) != held_eff(kind):
                    g.add(f"{tag}, at the expiry second: the hold reads {pw.state(HOLD)!r} held_by {held_by14(pw, text)!r} reserve {pw.state(EFF)}, wanted unknown, nothing named, reserve {held_eff(kind)}")
                pw, exp = running(text, kind)
                pw.restart("exact", {EPOCH_E[kind]: restored})
                pw.w.run_until(exp - 600)
                out = cancel(pw, kind=kind)
                ep = epoch_of(pw, kind)
                if not out.startswith("CANCELLED") or pw.state(HOLD) != "clear" or pw.state(EFF) != "40" or ep is None or ep > pw.w.t:
                    g.add(f"{tag}, cancel while the attribute shows it running: {out[:40]!r} hold {pw.state(HOLD)!r} epoch {ep}")
                # (B) the attribute is past (nothing running): the kind is unreadable: unknown, the cut's reserve retained, held when another kind runs, a cancel allowed and it repairs
                pw = world(text, now=ORDINARY, zone=LONDON)
                pw.w.set(CUT_RESERVE_E, "80.0")
                pw.restart("exact", {EPOCH_E[kind]: restored})
                if pw.state(HOLD) != "unknown" or held_by14(pw, text) != "" or pw.state(EFF) != held_eff(kind):
                    g.add(f"{tag}, attribute past: the hold reads {pw.state(HOLD)!r} held_by {held_by14(pw, text)!r} reserve {pw.state(EFF)}, wanted unknown, nothing named, reserve {held_eff(kind)}")
                start(pw, kind=others[0], expiry_min=30)
                want_eff = "80" if "prepare_power_cut" in (kind, others[0]) else "40"
                if pw.state(HOLD) != "held" or held_by14(pw, text) != others[0] or pw.state(EFF) != want_eff:
                    g.add(f"{tag}, attribute past, {others[0]} running: hold {pw.state(HOLD)!r} held_by {held_by14(pw, text)!r} reserve {pw.state(EFF)}, wanted held by {others[0]} only, reserve {want_eff}")
                out = cancel(pw, kind=kind)
                if not out.startswith("CANCELLED") or epoch_of(pw, kind) is None or epoch_of(pw, kind) > pw.w.t or held_by14(pw, text) != others[0]:
                    g.add(f"{tag}, attribute past: a cancel answers {out[:40]!r}, epoch {epoch_of(pw, kind)}, held_by {held_by14(pw, text)!r}")
            # (C) the epoch RESET to 0 (a valid number in the past): it can never release what the attribute still shows as running, and it is not an unreadable record
            pw, exp = running(text, kind)
            pw.restart("exact", {EPOCH_E[kind]: "0.0"})
            probe14(g, pw, text, {kind: exp}, f"{kind}, epoch reset to 0, attribute running")
            pw.w.run_until(exp - 1)
            probe14(g, pw, text, {kind: exp}, f"{kind}, epoch reset to 0, attribute running")
            pw.w.run_until(exp)
            probe14(g, pw, text, {kind: exp}, f"{kind}, epoch reset to 0, at the expiry second")
            pw, exp = running(text, kind)
            pw.restart("exact", {EPOCH_E[kind]: "0.0"})
            pw.w.run_until(exp - 600)
            out = cancel(pw, kind=kind)
            if not out.startswith("CANCELLED") or pw.state(HOLD) != "clear":
                g.add(f"{kind}, epoch reset to 0: a cancel while the attribute shows it running answers {out[:40]!r} hold {pw.state(HOLD)!r}")
            pw = world(text, now=ORDINARY, zone=LONDON)
            pw.restart("exact", {EPOCH_E[kind]: "0.0"})
            if pw.state(HOLD) != "clear" or not cancel(pw, kind=kind).startswith("REFUSED NOT_ACTIVE"):
                g.add(f"{kind}, epoch 0 and nothing running: the hold reads {pw.state(HOLD)!r} or a cancel is not NOT_ACTIVE")
            # (D) the attribute MISSING (the helper's state is kept, its attribute is gone): with the epoch running it is held; with the epoch past it is unreadable
            pw, exp = running(text, kind)
            pw.w.set(EXPIRES_E[kind], pw.state(EXPIRES_E[kind]), {"has_date": True, "has_time": True})
            probe14(g, pw, text, {kind: exp}, f"{kind}, attribute missing, epoch running")
            pw.w.run_until(exp - 1)
            probe14(g, pw, text, {kind: exp}, f"{kind}, attribute missing, epoch running")
            pw.w.run_until(exp)
            if pw.state(HOLD) != "unknown" or held_by14(pw, text) != "" or pw.state(EFF) != held_eff(kind):
                g.add(f"{kind}, attribute missing, epoch past: the hold reads {pw.state(HOLD)!r} held_by {held_by14(pw, text)!r} reserve {pw.state(EFF)}, wanted unknown, nothing named, reserve {held_eff(kind)}")
            out = cancel(pw, kind=kind)
            if not out.startswith("CANCELLED") or pw.state(HOLD) != "clear" or pw.state(EFF) != "40" or exp_ts(pw, kind) > pw.w.t:
                g.add(f"{kind}, attribute missing, epoch past: a cancel answers {out[:40]!r} hold {pw.state(HOLD)!r}; it must repair the record")
            pw, exp = running(text, kind)
            pw.w.set(EXPIRES_E[kind], pw.state(EXPIRES_E[kind]), {"has_date": True, "has_time": True})
            pw.w.run_until(exp - 600)
            out = cancel(pw, kind=kind)
            if not out.startswith("CANCELLED") or pw.state(HOLD) != "clear":
                g.add(f"{kind}, attribute missing, epoch running: a cancel answers {out[:40]!r} hold {pw.state(HOLD)!r}")
            # (E) both sources unreadable (a missing attribute, a state that is not a time, a broken epoch): unknown, nothing named, the cut's reserve retained, a cancel repairs both
            for dlabel, dset in (("attribute missing", lambda pw, k: pw.w.set(EXPIRES_E[k], pw.state(EXPIRES_E[k]), {"has_date": True, "has_time": True})),
                                 ("state unavailable", lambda pw, k: pw.w.set(EXPIRES_E[k], "unavailable"))):
                for elabel, restored in (("missing", None), ("junk", "abc"), ("unavailable", "unavailable")):
                    pw = world(text, now=ORDINARY, zone=LONDON)
                    pw.w.set(CUT_RESERVE_E, "80.0")
                    dset(pw, kind)
                    pw.restart("exact", {EPOCH_E[kind]: restored})
                    tag = f"{kind}, {dlabel} and epoch {elabel}"
                    if pw.state(HOLD) != "unknown" or held_by14(pw, text) != "" or pw.state(EFF) != held_eff(kind):
                        g.add(f"{tag}: the hold reads {pw.state(HOLD)!r} held_by {held_by14(pw, text)!r} reserve {pw.state(EFF)}, wanted unknown, nothing named, reserve {held_eff(kind)}")
                    out = cancel(pw, kind=kind)
                    if not out.startswith("CANCELLED") or pw.state(HOLD) != "clear" or pw.state(EFF) != "40" or epoch_of(pw, kind) is None:
                        g.add(f"{tag}: a cancel answers {out[:40]!r} hold {pw.state(HOLD)!r} reserve {pw.state(EFF)}; it must repair both records")
            # (F) the sources disagree. STALE-EARLY attribute (restored early) against a later epoch: held until the epoch instant. STALE-LATE attribute (a partial write left a later date-and-time
            # expiry) against an earlier epoch: held until the attribute's instant (fail closed), and a cancel reconciles it
            for label, dt_off, ep_off in (("stale-early attribute", -600, 600), ("stale-late attribute", 3600, -600), ("stale-early attribute, epoch far ahead", -3000, 1800)):
                pw = world(text, now=ORDINARY, zone=LONDON)
                pw.w.set(CUT_RESERVE_E, "80.0")
                t = pw.w.t
                put_dt14(pw, kind, t + dt_off)
                pw.restart("exact", {EPOCH_E[kind]: f"{float(t // 60 * 60 + ep_off)}"})
                later = max(t + dt_off, t // 60 * 60 + ep_off)
                for t_probe in (t, later - 1, later, later + 1):
                    pw.w.run_until(t_probe)
                    probe14(g, pw, text, {kind: later}, f"{kind}, {label}")
                pw = world(text, now=ORDINARY, zone=LONDON)
                t = pw.w.t
                put_dt14(pw, kind, t + dt_off)
                pw.restart("exact", {EPOCH_E[kind]: f"{float(t // 60 * 60 + ep_off)}"})
                out = cancel(pw, kind=kind)
                if not out.startswith("CANCELLED") or pw.state(HOLD) != "clear" or epoch_of(pw, kind) != exp_ts(pw, kind):
                    g.add(f"{kind}, {label}: a cancel answers {out[:40]!r} hold {pw.state(HOLD)!r}; it must reconcile both sources to the cancel instant")
        # (G) the stored reserve while the power cut's expiry cannot be read: a valid value 10 to 100 is retained, an invalid one is not applied; a readable past record never counts
        for stored, want in (("80.0", "80"), ("55.0", "55"), ("100.0", "100"), ("41.0", "41"), ("62.4", "63"), ("unavailable", "40"), ("unknown", "40"), ("", "40"), ("nan", "40"), ("inf", "40"),
                             ("9.0", "40"), ("100.5", "40"), ("abc", "40"), ("-3.0", "40")):
            pw = world(text, now=ORDINARY, zone=LONDON)
            pw.w.set(CUT_RESERVE_E, stored)
            pw.w.set(EXPIRES_E["prepare_power_cut"], pw.state(EXPIRES_E["prepare_power_cut"]), {"has_date": True, "has_time": True})
            pw.restart("exact", {EPOCH_E["prepare_power_cut"]: "abc"})
            if pw.state(EFF) != want:
                g.add(f"the power cut's expiry is unreadable and its stored reserve is {stored!r}: the effective reserve is {pw.state(EFF)}, wanted {want}")
        pw = world(text, now=ORDINARY, zone=LONDON)
        pw.w.set(CUT_RESERVE_E, "80.0")
        if pw.state(EFF) != "40":
            g.add(f"a readable, past power-cut record with a stored reserve of 80 raises the effective reserve to {pw.state(EFF)}")
    except _Stop14:
        pass
    return g.bad


def inject_expiry_failure(pw: P.PlanWorld, kind: str):
    """Make the date-and-time write of `kind`'s expiry raise (a service error, as an interrupted script would see); returns the function that restores the handler."""
    orig = pw.w.service_handlers["input_datetime.set_datetime"]

    def failing(entity, data):
        if entity == EXPIRES_E[kind]:
            raise S.ServiceError("injected: the date-and-time expiry write fails")
        return orig(entity, data)

    pw.w.service_handlers["input_datetime.set_datetime"] = failing
    return lambda: pw.w.service_handlers.__setitem__("input_datetime.set_datetime", orig)


def g_interrupt(text: str, stop_early: bool = False) -> list[str]:
    """An interrupted start (the date-and-time expiry write fails after the epoch was written) leaves the override HELD, never half released; an interrupted cancel leaves it held, and a second cancel finishes it."""
    g = _G(stop_early)
    try:
        for kind in KINDS:
            pw = world(text, now=ORDINARY, zone=LONDON)
            restore = inject_expiry_failure(pw, kind)
            pw.run_script("ecco_plan_override_start", {"kind": kind, "expiry_min": 60})
            if pw.state(HOLD) != "held" or held_by14(pw, text) != kind:
                g.add(f"{kind}: a start whose date-and-time expiry write failed leaves the hold {pw.state(HOLD)!r} held_by {held_by14(pw, text)!r}, wanted held (the epoch record is written first)")
            restore()
            out = cancel(pw, kind=kind)
            if not out.startswith("CANCELLED") or pw.state(HOLD) != "clear":
                g.add(f"{kind}: a cancel after an interrupted start answers {out[:40]!r} hold {pw.state(HOLD)!r}")
            pw, exp = running(text, kind, 60)
            restore = inject_expiry_failure(pw, kind)
            pw.run_script("ecco_plan_override_cancel", {"kind": kind})
            if pw.state(HOLD) != "held":
                g.add(f"{kind}: an interrupted cancel leaves the hold {pw.state(HOLD)!r}, wanted held (fail closed)")
            restore()
            if not cancel(pw, kind=kind).startswith("CANCELLED") or pw.state(HOLD) != "clear":
                g.add(f"{kind}: a second cancel does not finish an interrupted one")
    except _Stop14:
        pass
    return g.bad


def g_normal(text: str, stop_early: bool = False) -> list[str]:
    """The normal paths, every kind, on an ordinary day and the clock-change day: held through the last second of a 15 minute override, clear at the expiry second, never extended; then a cancel."""
    g = _G(stop_early)
    try:
        for kind in KINDS:
            for label, started in (("ordinary day", ORDINARY), ("clock-change day", AUTUMN)):
                pw, exp = running(text, kind, 15, started)
                if epoch_of(pw, kind) != exp:
                    g.add(f"{kind}, {label}: the epoch record {epoch_of(pw, kind)} is not the expiry {exp}")
                for k in range(1, 16):
                    pw.w.run_until(exp - 900 + 60 * k - 1)
                    probe14(g, pw, text, {kind: exp}, f"{kind}, {label}, minute {k}")
                for d in (0, 1, 61):
                    pw.w.run_until(exp + d)
                    probe14(g, pw, text, {kind: exp}, f"{kind}, {label}")
                pw, exp = running(text, kind, 60, started)
                pw.w.run_until(exp - 1800)
                out = cancel(pw, kind=kind)
                if not out.startswith("CANCELLED") or pw.state(HOLD) != "clear" or pw.state(EFF) != "40":
                    g.add(f"{kind}, {label}: a cancel answers {out[:40]!r} hold {pw.state(HOLD)!r}")
    except _Stop14:
        pass
    return g.bad


def g_diff(text: str, stop_early: bool = False) -> list[str]:
    """A seeded sweep of start times, lengths and restart moments. The new read is never EARLIER than the old attribute-only read, equals it whenever the two sources agree, and equals
    the true instant (the epoch record is restored exactly in every restart modelled here)."""
    g = _G(stop_early)
    rng = random.Random(1119)
    starts = ("2026-10-24 22:15:20", "2026-10-25 00:05:10", AUTUMN, "2026-10-25 01:20:05", "2026-10-25 03:30:00", ORDINARY, "2027-03-27 23:10:00", "2027-03-28 00:30:40", "2027-03-28 05:00:00")
    lengths = (15, 30, 45, 60, 75, 90, 120, 150, 180, 240, 360, 600)
    try:
        for i in range(34):
            started, kind, minutes = rng.choice(starts), rng.choice(KINDS), rng.choice(lengths)
            mode = rng.choice((None, "first", "exact"))
            pw, exp = running(text, kind, minutes, started)
            t0 = exp - minutes * 60
            tr = max(t0 + rng.randrange(1, minutes + 90) * 60, pw.w.t)
            probes = sorted({t0 + rng.randrange(0, (minutes + 100) * 60) for _ in range(9)} | {exp - 1, exp})
            pending = mode is not None
            for t in probes:
                if t < pw.w.t:
                    continue
                if pending and tr <= t:
                    pw.w.run_until(tr)
                    pw.restart(mode)
                    pending = False
                pw.w.run_until(t)
                now = pw.w.t
                old_held = float(pw.w.state_attr(EXPIRES_E[kind], "timestamp")) > now                 # the earlier read: the attribute alone
                agree = epoch_of(pw, kind) == float(pw.w.state_attr(EXPIRES_E[kind], "timestamp"))
                new_held = pw.state(HOLD) == "held" and held_by14(pw, text) == kind
                tag = f"sweep {i} ({started}, {kind}, {minutes} min, restart {mode} at {tr - t0:+.0f} s), {now - exp:+.0f} s from the true expiry"
                if old_held and not new_held:
                    g.add(f"{tag}: the new read is EARLIER than the attribute-only read")
                if agree and new_held != old_held:
                    g.add(f"{tag}: the sources agree but the new read differs from the old one ({new_held} vs {old_held})")
                if new_held != (exp > now):
                    g.add(f"{tag}: the new read ({new_held}) is not the true instant's ({exp > now})")
                if kind == "prepare_power_cut" and pw.state(EFF) != ("80" if exp > now else "40"):
                    g.add(f"{tag}: the effective reserve is {pw.state(EFF)}")
    except _Stop14:
        pass
    return g.bad


GROUPS14 = (g_writes, g_restart, g_cancel, g_abnormal, g_interrupt, g_normal, g_diff)


def problems14(text: str, stop_early: bool = False) -> list[str]:
    out: list[str] = []
    for fn in GROUPS14:
        try:
            out += fn(text, stop_early)
        except Exception as exc:  # noqa: BLE001 - a package that cannot run is a failed proof
            out.append(f"{fn.__name__} raised {type(exc).__name__}: {str(exc)[:100]}")
        if out and stop_early:
            break
    return out


# ---- the model itself (independent of the package): what the restart restores ----
def premise_problems() -> list[str]:
    bad = []
    pw, exp = running(PKG_TEXT, "hold_battery", 120, AUTUMN)
    state_before, attr_before = pw.state(EXPIRES_E["hold_battery"]), exp_ts(pw, "hold_battery")
    pw.restart("first")
    if pw.state(EXPIRES_E["hold_battery"]) != state_before or exp_ts(pw, "hold_battery") != attr_before - 3600:
        bad.append(f"an expiry in the repeated hour is not restored 60 minutes early with its state string unchanged: {pw.state(EXPIRES_E['hold_battery'])!r} {exp_ts(pw, 'hold_battery') - attr_before:+.0f} s")
    for label, started in (("ordinary day", ORDINARY), ("spring-forward day", "2027-03-28 00:30:40"), ("October, expiry after the hour", "2026-10-25 01:10:40")):
        pw, exp = running(PKG_TEXT, "skip_tonight", 120 if label != "October, expiry after the hour" else 180, started)
        pw.restart("first")
        if exp_ts(pw, "skip_tonight") != exp:
            bad.append(f"{label}: a restart changed an expiry outside the repeated hour by {exp_ts(pw, 'skip_tonight') - exp:+.0f} s")
    pw, exp = running(PKG_TEXT, "hold_battery", 120, AUTUMN)
    before = {e: v for e, v in pw.w.states.items() if e.startswith("input_number.")}
    pw.restart("first")
    if {e: v for e, v in pw.w.states.items() if e.startswith("input_number.")} != before:
        bad.append("a restart changed a number helper (they are restored exactly)")
    pw.restart("missing")
    if pw.w.state_attr(EXPIRES_E["hold_battery"], "timestamp") is not None:
        bad.append("restart('missing') left the attribute")
    return bad


pm = premise_problems()
check("the restart model: a date-and-time expiry in the repeated hour is restored 60 minutes EARLY with its state string unchanged, one outside it exactly, a number helper exactly, "
      "and an abnormal restore can be stated (the recollection of Home Assistant core that known limitation 19 describes; not verified live)", pm == [], str(pm[:3]))

SHAPE14 = {
    "epoch": re.compile(r"\{%- set (\w+) = states\('input_number\.ecco_plan_override_[a-z_]+_expires_epoch'\) \| float\(none\) -%\}\n[ ]*\{%- set \1 = \1 if \(\1 is number and \1 == \1 and \1 >= 0 and \1 <= 4102444800\) else none -%\}"),
    "combine": re.compile(r"\{%- set (\w+) = \(\[\1, (\w+)\] \| reject\('none'\) \| list \| max\) if \(\(\1 is not none and \2 is not none\) or \(\1 is not none and \1 > (\w+)\) or \(\2 is not none and \2 > \3\)\) else none -%\}"),
    "write": re.compile(r"[ ]*- action: input_number\.set_value\n[ ]*target:\n[ ]*entity_id: input_number\.ecco_plan_override_(\w+?)_expires_epoch\n[ ]*data:\n[ ]*value: \"\{\{ decision\.expires_ts \}\}\"\n"),
}
shape = {k: len(rx.findall(PKG_TEXT)) for k, rx in SHAPE14.items()}
check("the text has the new read at all ten expiry read sites (an epoch read with a positive-range test and the raise-only combination) and six epoch writes (three starts, three cancels)",
      shape == {"epoch": 10, "combine": 10, "write": 6}, str(shape))

def _guarded14(fn) -> list[str]:
    try:
        return fn(PKG_TEXT)
    except Exception as exc:  # noqa: BLE001 - a package that cannot run is a failed proof, not a crash of the suite
        return [f"{fn.__name__} raised {type(exc).__name__}: {str(exc)[:100]}"]


R14 = {fn.__name__: _guarded14(fn) for fn in GROUPS14}
check("start and cancel write the epoch record: the same number as the date-and-time expiry (the cancel: the minute-floored now), BEFORE the date-and-time expiry (the power cut: reserve, epoch, start, "
      "expiry), the kind's own record only, and a cancel leaves the other kinds' epoch records alone", R14["g_writes"] == [], str(R14["g_writes"][:3]))
check("the October repeated hour, the October day and night around it, the spring-forward day and an ordinary day, each kind, with no restart and with a restart before, inside and after the hour "
      "(the attribute restored 60 minutes early when the expiry is in the hour): the hold, held_by and the effective reserve equal the TRUE instants: held to the last second, clear at the expiry "
      "second, never a second longer; all three kinds at once", R14["g_restart"] == [], str(R14["g_restart"][:3]))
check("start then cancel then restart stays released; a restart inside the repeated hour and then a cancel inside it is allowed and releases; a cancel after the true expiry is NOT_ACTIVE with the "
      "revision unchanged; one second before the expiry a cancel is allowed, at the expiry second it is not", R14["g_cancel"] == [], str(R14["g_cancel"][:3]))
check("an epoch record that is missing, unavailable, unknown, empty, nan, infinite, negative, out of range or junk: with the attribute running it is held (the cut's reserve kept, a cancel repairs it); "
      "with the attribute past the kind is unreadable (unknown; the cut's raised reserve retained; held by another running kind); an epoch reset to 0 can never release what the attribute shows as "
      "running; a missing attribute with the epoch running is held, with the epoch past unreadable; both unreadable: unknown and the reserve retained; stale-early and stale-late sources; the stored "
      "reserve (valid 10 to 100 retained, an invalid value not applied)", R14["g_abnormal"] == [], str(R14["g_abnormal"][:3]))
check("an interrupted start leaves the override held (the epoch record is written first), an interrupted cancel leaves it held and a second cancel finishes it", R14["g_interrupt"] == [], str(R14["g_interrupt"][:3]))
check("the normal paths of all three kinds on an ordinary day and the clock-change day: held through the last second of a 15 minute override, clear at the expiry second, never extended, then a cancel",
      R14["g_normal"] == [], str(R14["g_normal"][:3]))
check("a differential sweep of 34 seeded start times, lengths and restart moments: the new read is never EARLIER than the attribute-only read, equals it whenever the two sources agree, and equals the "
      "true instant", R14["g_diff"] == [], str(R14["g_diff"][:3]))

print("[14] mutation: each way of ignoring, mixing up, mis-writing or loosening the epoch record is caught by a running case above")


def _line_indent(t: str, pos: int) -> str:
    return t[t.rfind("\n", 0, pos) + 1:pos]


def _sub_sites(t: str, rx: re.Pattern, fn, only=None) -> str:
    out, last = [], 0
    for k, m in enumerate(rx.finditer(t)):
        out.append(t[last:m.start()])
        out.append(fn(m, _line_indent(t, m.start())) if only is None or k in only else m.group(0))
        last = m.end()
    out.append(t[last:])
    return "".join(out)


def build_mutants14(t: str) -> list[tuple[str, str]]:
    ident = lambda m, ind: "{%- set " + m.group(1) + " = " + m.group(1) + " -%}"                                       # noqa: E731 - the epoch source ignored
    sites = ("the cancel script, Hold battery", "the cancel script, Skip tonight", "the cancel script, Prepare for power cut", "the hold sensor's state, Hold battery",
             "the hold sensor's state, Skip tonight", "the hold sensor's state, Prepare for power cut", "the held_by attribute, Hold battery", "the held_by attribute, Skip tonight",
             "the held_by attribute, Prepare for power cut", "the effective reserve's power-cut expiry")
    muts: list[tuple[str, str]] = []
    muts.append(("the epoch record is ignored at every read site", _sub_sites(t, SHAPE14["combine"], ident)))
    for k in range(10):
        muts.append((f"the epoch record is ignored at one read site: {sites[k]}", _sub_sites(t, SHAPE14["combine"], ident, only={k})))
    muts.append(("min instead of max (the earlier instant wins)", _sub_sites(t, SHAPE14["combine"], lambda m, ind: m.group(0).replace("| list | max)", "| list | min)"))))
    muts.append(("the epoch record replaces the attribute when it is valid (not raise-only)", _sub_sites(t, SHAPE14["combine"], lambda m, ind: "{%- set " + m.group(1) + " = " + m.group(2) + " if " + m.group(2) + " is not none else " + m.group(1) + " -%}")))
    muts.append(("the attribute replaces the epoch record when it is valid (not raise-only)", _sub_sites(t, SHAPE14["combine"], lambda m, ind: "{%- set " + m.group(1) + " = " + m.group(1) + " if " + m.group(1) + " is not none else " + m.group(2) + " -%}")))
    muts.append(("an unreadable epoch record is treated as clear (a valid 0)", _sub_sites(t, SHAPE14["epoch"], lambda m, ind: m.group(0).replace("else none -%}", "else 0 -%}"))))
    muts.append(("an unreadable attribute is treated as clear (a valid 0)", _sub_sites(t, SHAPE14["combine"], lambda m, ind: "{%- set " + m.group(1) + " = " + m.group(1) + " if " + m.group(1) + " is not none else 0 -%}\n" + ind + m.group(0))))
    muts.append(("the positive-range test is removed from the epoch read (inf and negative accepted)", _sub_sites(t, SHAPE14["epoch"], lambda m, ind: re.sub(r" and (\w+) >= 0 and \1 <= 4102444800", "", m.group(0)))))
    muts.append(("the positive-range test is written as a negation without the self-equality test (nan accepted)",
                 _sub_sites(t, SHAPE14["epoch"], lambda m, ind: re.sub(r" and (\w+) == \1 and \1 >= 0 and \1 <= 4102444800", lambda x: " and not (" + x.group(1) + " < 0 or " + x.group(1) + " > 4102444800)", m.group(0)))))
    muts.append(("NOT_ACTIVE is decided from the date-and-time source only", _sub_sites(t, SHAPE14["combine"], ident, only={0, 1, 2})))
    muts.append(("NOT_ACTIVE is decided from the epoch source only", _sub_sites(t, SHAPE14["combine"], lambda m, ind: "{%- set " + m.group(1) + " = " + m.group(2) + " -%}", only={0, 1, 2})))
    old = "(e is none or e > n) and c is number"
    muts.append(("the effective reserve drops the power cut's reserve when its expiry is unreadable (the behaviour before r14)", t.replace(old, "(e is not none and e > n) and c is number") if t.count(old) == 1 else ""))
    old2 = "{%- set c = c if ((e is none or e > n) and c is number and c == c and c >= 10 and c <= 100) else none -%}"
    muts.append(("the stored reserve range test is dropped while the expiry is unreadable", t.replace(old2, "{%- set c = c if (e is none or e > n) else none -%}") if t.count(old2) == 1 else ""))
    blocks = list(SHAPE14["write"].finditer(t))
    names = ("Hold battery", "Skip tonight", "Prepare for power cut")
    for i in range(6):
        who = f"the start of {names[i]}" if i < 3 else f"the cancel of {names[i - 3]}"
        muts.append((f"the epoch record is not written by {who}", t[:blocks[i].start()] + t[blocks[i].end():] if len(blocks) == 6 else ""))
    for i in range(3):
        if len(blocks) != 6:
            muts.append((f"the epoch record is written AFTER the date-and-time expiry: {names[i]}", ""))
            continue
        m, kind = blocks[i], KINDS[i]
        rest = t[:m.start()] + t[m.end():]
        at = rest.index(f"entity_id: input_datetime.ecco_plan_override_{kind}_expires\n", m.start())
        j = rest.index("\n", rest.index("timestamp:", at)) + 1
        muts.append((f"the epoch record is written AFTER the date-and-time expiry: {names[i]}", rest[:j] + m.group(0) + rest[j:]))
    cancel_plus = lambda m, ind: m.group(0).replace("decision.expires_ts }}", "decision.expires_ts + 3600 }}")        # noqa: E731
    muts.append(("a cancel leaves the epoch record in the future (an hour after the cancel instant)", _sub_sites(t, SHAPE14["write"], cancel_plus, only={3, 4, 5})))
    muts.append(("a start blindly extends the epoch record by an hour", _sub_sites(t, SHAPE14["write"], cancel_plus, only={0, 1, 2})))
    return muts


caught14, built14 = 0, 0
if shape == {"epoch": 10, "combine": 10, "write": 6}:
    for label, mutated in build_mutants14(PKG_TEXT):
        built14 += 1
        if not mutated or mutated == PKG_TEXT:
            check(f"mutant anchor: {label}", False, "the mutation did not change the text")
            continue
        try:
            yaml.safe_load(mutated)
        except yaml.YAMLError as exc:
            check(f"mutant loads as YAML: {label}", False, str(exc)[:80])
            continue
        found = problems14(mutated, stop_early=True)
        if found:
            caught14 += 1
            print(f"  PASS  mutant caught: {label} (first failing case: {found[0][:90]})")
        else:
            FAILURES.append(f"mutant survived: {label}")
            print(f"  FAIL  mutant survived: {label}")
else:
    check("the epoch-record mutants could be built (the new read and writes are in the package text)", False, f"shape {shape}")
check(f"{built14} epoch-record mutants (the epoch ignored everywhere and at each of the ten read sites, min for max, either source replacing the other, an unreadable source read as clear, the positive-range "
      "test removed or written as a negation, NOT_ACTIVE from one source, the old skip of an unreadable power cut, the stored-reserve range test dropped, an epoch not written by any start or cancel, "
      "written after the expiry, a cancel that leaves it in the future, a start that extends it by an hour), all caught by a running case",
      built14 == 33 and caught14 == built14, f"{caught14}/{built14}")
check("control: the unmutated package passes the same running cases", all(v == [] for v in R14.values()))

if FAILURES:
    print(f"\nFAILED: {len(FAILURES)} check(s)")
    for f in FAILURES:
        print("  -", f)
    sys.exit(1)
print("\nAll plan helper package checks passed.")
print("These prove the package against a model of Home Assistant; nothing was installed and nothing was written live.")
