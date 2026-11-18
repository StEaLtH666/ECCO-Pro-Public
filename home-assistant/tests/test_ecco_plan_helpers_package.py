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
  [7] not a charge Prepare for power cut raises a protected reserve and starts nothing: the battery below the reserve changes no charge entity,
                   no charge service exists, and the result says "Nothing is charging. Use Charge Battery if you want it filled."
  [8] seed         the owner's accepted limits are written once; the switch stays off; an owner's own value survives a restart
  [9] mutation     in-memory mutants of the package are each caught; an equivalent rewrite survives

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
        own = {START_E[kind], EXPIRES_E[kind], CUT_RESERVE_E if kind == "prepare_power_cut" else "-", REV, LAST}
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
expected = set(IDS.values()) | {CONTROL_IDS["last_result"], "input_boolean.ecco_plan_defaults_seeded"}
check("the helpers are exactly the entities the card reads (HELPER_IDS) plus the last result and the seed flag", set(ents) == expected, str(set(ents) ^ expected))
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
touched = [e for e in pw.w.states if pw.w.states[e] != before_all.get(e) and e not in (LAST, REV, START_E["prepare_power_cut"], EXPIRES_E["prepare_power_cut"], CUT_RESERVE_E) and not e.startswith("sensor.ecco_plan_")]
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
    ("a finished power cut still raises the reserve", "e is not none and e > n and c is number", "e is not none and c is number", 1),
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

if FAILURES:
    print(f"\nFAILED: {len(FAILURES)} check(s)")
    for f in FAILURES:
        print("  -", f)
    sys.exit(1)
print("\nAll plan helper package checks passed.")
print("These prove the package against a model of Home Assistant; nothing was installed and nothing was written live.")
