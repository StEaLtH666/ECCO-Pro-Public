#!/usr/bin/env python3
"""Intelligence foundation: the SHADOW-cycle invariants that must hold for ANY body of run_cycle / assess_inputs.

  [1] all decisions OPEN on a complete, fresh input: every advice item, predicted_morning_soc and predicted_day_load is
      BLOCKED, and no finite number appears anywhere in the entity payloads except pv_tomorrow and the diagnostics (the
      exemptions are hard-coded here), and no text carries the example window or a number with a unit
  [2] the example profile used as the site file: the same
  [3] SYNTHETIC_TEST records without an explicit acceptance: the same (provenance cannot unblock)
  [4] paused: PAUSED with every state null
  [5] the caller says fresh but the dongle liveness is stale: BLOCKED with CALLER_FRESHNESS_DISAGREES
  [6] 500 seeded malformed inputs never raise and always give a valid SHADOW envelope
  [7] determinism across two interpreter processes
  [8] AST: no clock read, open(), os, dynamic import or exec in shadow_cycle.py and quality.py
  [9] the conditional gates are wired: I-D4 with several capacity sources, I-D9 and the fixed DST rule on the eve of a
      clock change (the fictional 27 Oct 2030 change), and every INVALID decision BLOCKs (top level and its items)
Streams may not edit this file.
"""

from __future__ import annotations

import ast
import copy
import json
import re
import random
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import _cycle_fixtures as cf  # noqa: E402
from intelligence import advisory_contract as ac  # noqa: E402
from intelligence import site_decisions as sd  # noqa: E402
from intelligence.shadow_cycle import run_cycle  # noqa: E402

FAILURES: list[str] = []
ROOT = Path(__file__).resolve().parents[2]


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  PASS  {name}")
    else:
        FAILURES.append(name)
        print(f"  FAIL  {name}" + (f" - {detail}" if detail else ""))


def numbers(v, path="") -> list[str]:
    if isinstance(v, bool) or v is None or isinstance(v, str):
        return []
    if isinstance(v, (int, float)):
        return [path]
    if isinstance(v, dict):
        return [p for k, x in v.items() for p in numbers(x, f"{path}.{k}")]
    if isinstance(v, (list, tuple)):
        return [p for i, x in enumerate(v) for p in numbers(x, f"{path}[{i}]")]
    return [path + "?"]


def strings(v, path="") -> list[tuple[str, str]]:
    """(path, text) of every string value inside v."""
    if isinstance(v, str):
        return [(path, v)]
    if isinstance(v, dict):
        return [p for k, x in v.items() for p in strings(x, f"{path}.{k}")]
    if isinstance(v, (list, tuple)):
        return [p for i, x in enumerate(v) for p in strings(x, f"{path}[{i}]")]
    return []


# The exemptions are HARD-CODED here (never imported from the module under test), so a contract change cannot widen them.
# Numbers may appear while every decision is OPEN only in: the pv_tomorrow entity (no decision gates it; its advice keys
# are limited to the V1 PV forecast's own), the two diagnostic entities, and on the status entity only input_ages[].age_s /
# limit_s and accuracy.{mae_7d, coverage_7d, n}. self_test is not exempt (strings only).
EXEMPT_ENTITIES = {"sensor.ecco_intel_pv_tomorrow", "sensor.ecco_intel_accuracy", "sensor.ecco_intel_data_quality"}
INPUT_AGE_NUMERIC = {"age_s", "limit_s"}
ACCURACY_NUMERIC = {"mae_7d", "coverage_7d", "n"}
PV_ADVICE_KEYS = {"inflation", "usable", "day", "source", "raw_kwh", "ratio", "p10", "p50", "p90", "n_pairs", "mae_corrected",
                  "mae_raw", "confidence", "label", "notes", "plausibility", "status", "blocker_codes"}
# the SiteConfig example window (00:30-05:30) as text, and any number with an energy, power, percentage, charge or money unit
EXAMPLE_TEXT = re.compile(r"(?<![\d:])(?:00:30|05:30)(?![\d:])|\b31\.7\b")
UNIT_NUMBER = re.compile(r"\d(?:[\d.,]*\d)?\s?(?:%|kwh\b|kw\b|wh\b|w\b|ah\b|v\b|p/kwh|£|gbp\b|pence\b)", re.IGNORECASE)
GATED = ac.ADVICE_ITEMS + ("predicted_morning_soc", "predicted_day_load")


def leaks(env: ac.AdvisoryEnvelope) -> list[str]:
    out = []
    for eid, (state, rec, un) in ac.to_entity_payloads(env).items():
        for path, text in strings({"state": state, "recorded": rec, "unrecorded": un}, eid):
            if EXAMPLE_TEXT.search(text) or (eid not in EXEMPT_ENTITIES and UNIT_NUMBER.search(text)):
                out.append(f"{path} (text {text[:60]!r})")
        if eid in EXEMPT_ENTITIES:
            if eid == "sensor.ecco_intel_pv_tomorrow" and isinstance(un.get("advice"), dict):
                out += [f"{eid}.unrecorded.advice.{k} (not a PV forecast key)" for k in un["advice"] if k not in PV_ADVICE_KEYS]
            continue
        if eid == ac.ENTITY_IDS["status"]:
            rec = dict(rec)
            un = dict(un)
            rec["accuracy"] = ({k: v for k, v in rec["accuracy"].items() if k not in ACCURACY_NUMERIC}
                               if isinstance(rec.get("accuracy"), dict) else rec.get("accuracy"))
            un["input_ages"] = [{k: v for k, v in a.items() if k not in INPUT_AGE_NUMERIC} if isinstance(a, dict) else a
                                for a in (un.get("input_ages") or [])]
        out += numbers({"state": state, "recorded": rec, "unrecorded": un}, eid)
    return out


def all_blocked(env: ac.AdvisoryEnvelope) -> bool:
    return all(env.item(k).status == ac.ItemStatus.BLOCKED for k in GATED)


print("== [1] all decisions OPEN on a complete, fresh input")
inp = cf.cycle_inputs()
env = run_cycle(inp)
check("the fixture covers every SITE_READING_KEYS entry", {r.key for r in inp.site_readings} == set(ac.SITE_READING_KEYS))
check("every advice item, predicted_morning_soc and predicted_day_load is BLOCKED", all_blocked(env),
      str([(k, env.item(k).status) for k in GATED]))
check("no finite number anywhere except pv_tomorrow and the diagnostics", leaks(env) == [], str(leaks(env)[:6]))
check("the envelope is SHADOW, applies nothing, and shows every I-D OPEN",
      env.mode == "SHADOW" and env.applies_nothing is True and set(env.decisions.values()) == {"OPEN"})
check("the system status is BLOCKED (no advice item OK, at least one BLOCKED)", env.status == "BLOCKED", env.status)
for later in (timedelta(0), timedelta(hours=6), timedelta(days=200)):
    e2 = run_cycle(cf.cycle_inputs(now=cf.NOW + later))
    check(f"... also at now + {later} (a different day / season)", all_blocked(e2) and leaks(e2) == [])

print("== [2] the example profile as the site file")
prof = json.loads((ROOT / "intelligence" / "profiles" / "site_profile.example.json").read_text(encoding="utf-8"))
pds = sd.DecisionSet.from_mapping(prof["decisions"], source="example_profile")
penv = run_cycle(cf.cycle_inputs(decisions=pds))
check("the example profile's decisions are all OPEN", set(pds.status_map().values()) == {"OPEN"})
check("... every gated item BLOCKED and no number leaks", all_blocked(penv) and leaks(penv) == [], str(leaks(penv)[:4]))
check("... its reserve hints are reported as ignored by the SHADOW path",
      [f.code for f in sd.site_hints_ignored(prof["site"])] == ["SITE_HINT_IGNORED", "SITE_HINT_IGNORED"])

print("== [3] provenance cannot unblock")
syn_default = run_cycle(cf.cycle_inputs(decisions=cf.synthetic_decisions(), accept_provenance=sd.DEFAULT_ACCEPT_PROVENANCE))
check("SYNTHETIC_TEST records under the default acceptance: every gated item BLOCKED, no leak",
      all_blocked(syn_default) and leaks(syn_default) == [] and syn_default.provenance_ok is False)
syn_acc = run_cycle(cf.cycle_inputs(synthetic_recorded=True))
check("with SYNTHETIC_TEST explicitly accepted the decisions no longer block (provenance_ok)",
      syn_acc.provenance_ok is True and not [c for k in GATED for c, _t in syn_acc.item(k).blockers if c.startswith("DECISION_")])

print("== [4] paused")
pz = run_cycle(cf.cycle_inputs(paused=True))
pp = ac.to_entity_payloads(pz)
check("paused -> PAUSED", pz.status == "PAUSED" and pz.pause_control == "ON")
check("paused: every item, forecast and diagnostic state is None and fresh is False",
      all(st is None for eid, (st, _r, _u) in pp.items() if eid not in (ac.ENTITY_IDS["status"], ac.ENTITY_IDS["fresh"]))
      and pp[ac.ENTITY_IDS["fresh"]][0] is False)
check("paused: no number anywhere at all", [p for eid, (st, r, u) in pp.items() for p in numbers({"s": st, "r": r, "u": u}, eid)] == [])
pm = run_cycle(cf.cycle_inputs(paused=None))
check("a missing pause control is not paused (MISSING, not PAUSED)", pm.status != "PAUSED" and pm.pause_control == "MISSING")

print("== [5] caller freshness disagreement")
for synthetic in (False, True):
    sl = run_cycle(cf.cycle_inputs(stale_liveness=True, synthetic_recorded=synthetic))
    codes = {c for c, _t in sl.blockers} | set(sl.reason_codes)
    check(f"caller says fresh, liveness 2 h old (synthetic_recorded={synthetic}): BLOCKED with CALLER_FRESHNESS_DISAGREES",
          sl.status == "BLOCKED" and "CALLER_FRESHNESS_DISAGREES" in codes and all_blocked(sl) and leaks(sl) == [], f"{sl.status} {sorted(codes)}")
as_list = cf.cycle_inputs(stale_liveness=True, synthetic_recorded=True)
object.__setattr__(as_list, "caller_assessments", list(as_list.caller_assessments))
ll = run_cycle(as_list)
check("... also when the caller assessments arrive as a list after construction (no post-init bypass hides it)",
      ll.status == "BLOCKED" and "CALLER_FRESHNESS_DISAGREES" in {c for c, _t in ll.blockers} | set(ll.reason_codes),
      f"{ll.status} {sorted({c for c, _t in ll.blockers})[:4]}")

print("== [6] 500 seeded malformed inputs")
NAIVE = datetime(2030, 1, 15, 21, 0)
FUTURE = datetime(2099, 1, 1, tzinfo=timezone.utc)
JUNK = [None, float("nan"), float("inf"), -1, 0, 10 ** 15, "", "x", "unavailable", [], {}, (), set(), object(), NAIVE, FUTURE,
        True, False, b"\x00", ("battery.soc",), (("battery.soc", "yes", None),), {"D1": "x"}, frozenset({"OWNER_RECORD", 1}),
        ac.SiteFacts(pv_array_kwp=6.0, tz="Nowhere/Invalid_Zone"), ac.SiteFacts(pv_array_kwp=float("nan"), tz=""),
        ac.Versions(None, None, None, None)]
FIELDS = [f.name for f in ac.CycleInputs.__dataclass_fields__.values()]
bases = [cf.cycle_inputs(), cf.cycle_inputs(synthetic_recorded=True), cf.cycle_inputs(stale_liveness=True)]
raised, bad_env, kinds = [], [], set()
for i in range(500):
    rnd = random.Random(1000 + i)
    x = copy.copy(rnd.choice(bases))
    for _ in range(rnd.randint(1, 3)):
        mode = rnd.random()
        if mode < 0.5:
            object.__setattr__(x, rnd.choice(FIELDS), rnd.choice(JUNK))
        elif mode < 0.8 and isinstance(x.site_readings, tuple) and x.site_readings:
            rs = list(x.site_readings)
            j = rnd.randrange(len(rs))
            r = rs[j]
            rk, rv, ru, ro, rsrc = (getattr(r, a, None) for a in ("key", "value", "unit", "observed_at", "source"))
            rs[j] = ac.SiteReading(rnd.choice([rk, "nope.key", None, 5]), rnd.choice(JUNK + [rv]),
                                   rnd.choice([ru, None, "kW", 3]), rnd.choice([ro, None, NAIVE, FUTURE, "2030"]),
                                   rnd.choice([rsrc, "", None]))
            if rnd.random() < 0.3:
                rs.append(rs[j])
            object.__setattr__(x, "site_readings", tuple(rs))
        else:
            object.__setattr__(x, "caller_assessments", tuple(rnd.choice(JUNK) for _ in range(rnd.randint(0, 4))))
    try:
        e = run_cycle(x)
        if not (isinstance(e, ac.AdvisoryEnvelope) and e.mode == "SHADOW" and e.applies_nothing is True):
            bad_env.append(i)
        json.dumps({eid: [st, r, u] for eid, (st, r, u) in ac.to_entity_payloads(e).items()}, allow_nan=False)
        kinds.add(e.status)
        if x.decisions is not None and isinstance(x.decisions, sd.DecisionSet) and set(x.decisions.status_map().values()) == {"OPEN"} \
                and e.status not in ac.SystemStatus.NULL and leaks(e):
            bad_env.append(i)
    except Exception as exc:  # noqa: BLE001 - the invariant under test
        raised.append((i, type(exc).__name__, str(exc)[:80]))
check("500 malformed inputs: run_cycle never raises", raised == [], str(raised[:3]))
check("... and always returns a valid SHADOW envelope whose payloads are strict JSON (no leak while all OPEN)", bad_env == [], str(bad_env[:5]))
check("... the fuzz reached more than one outcome", len(kinds) >= 2, str(kinds))

print("== [6b] a missing dongle liveness reading blocks every dongle-dependent item")
nl = run_cycle(cf.cycle_inputs(synthetic_recorded=True, missing_key="liveness.dongle_poll_changed_at"))
dongle_items = [k for k in sd.ITEMS if k in ac.ADVICE_ITEMS + ac.FORECAST_ITEMS and sd.LIVENESS_KEY in sd.required_inputs(k, cf.synthetic_decisions(), cf.SYNTHETIC_ACCEPT).readings]
check("liveness missing (decisions accepted): every dongle-dependent item is BLOCKED and nothing leaks",
      dongle_items and all(nl.item(k).status == ac.ItemStatus.BLOCKED for k in dongle_items) and leaks(nl) == [],
      str([(k, nl.item(k).status) for k in dongle_items]))

print("== [6c] prepare_history: no learning history without a satisfied I-D8; EXCLUDE works on a copy")
from intelligence.quality import prepare_history as _prepare_history  # noqa: E402


def prepare_history(*a, **kw):
    """prepare_history, with an exception reported as a result (the contract: it never raises for these inputs)."""
    try:
        return _prepare_history(*a, **kw)
    except Exception as exc:  # noqa: BLE001
        return "RAISED", [type(exc).__name__]


hist = cf.history()
h0, f0 = prepare_history(hist, sd.DecisionSet(), cf.NOW)
check("I-D8 OPEN: no history, with a BLOCK finding", h0 is None and any(getattr(f, "severity", "") == "BLOCK" for f in f0), str(f0)[:80])
h1, _f1 = prepare_history(hist, cf.synthetic_decisions(), cf.NOW)
check("I-D8 recorded with SYNTHETIC_TEST but not accepted: no history", h1 is None)
cut = datetime(2030, 1, 1, tzinfo=timezone.utc)
ds8 = sd.DecisionSet().with_decision("D8", sd.HD1Cutover(cut, sd.EXCLUDE, sd.EXCLUDE_PRE_CUTOVER), sd.Provenance.SYNTHETIC_TEST)
before = {s: (r.load_w_mean, dict(r.e)) for s, r in hist.by_start.items()}
h2, _f2 = prepare_history(hist, ds8, cf.NOW, accept_provenance=cf.SYNTHETIC_ACCEPT)
cut_ts = int(cut.timestamp())
pre = [r for s, r in h2.by_start.items() if s < cut_ts] if hasattr(h2, "by_start") else []
post = [r for s, r in h2.by_start.items() if s >= cut_ts] if hasattr(h2, "by_start") else []
check("I-D8 EXCLUDE accepted: a copy without pre-cut-over load power or load energy; later hours keep theirs",
      h2 is not None and h2 is not hist and pre and all(r.load_w_mean is None and "load" not in r.e for r in pre)
      and post and all("load" in r.e for r in post))
check("... the History passed in is unchanged", {s: (r.load_w_mean, dict(r.e)) for s, r in hist.by_start.items()} == before)
check("... and no hour that had not ended by now is kept", hasattr(h2, "by_start") and max(h2.by_start) + 3600 <= int(cf.NOW.timestamp()))

print("== [7] determinism across interpreter processes")
script = (
    "import sys, json\n"
    f"sys.path.insert(0, {str(ROOT)!r}); sys.path.insert(0, {str(Path(__file__).resolve().parent)!r})\n"
    "import _cycle_fixtures as cf\n"
    "from intelligence.shadow_cycle import run_cycle\n"
    "from intelligence import advisory_contract as ac\n"
    "out = []\n"
    "for kw in ({}, {'synthetic_recorded': True}, {'stale_liveness': True}, {'paused': None}):\n"
    "    e = run_cycle(cf.cycle_inputs(**kw))\n"
    "    out.append([e.to_dict(), {k: list(v) for k, v in ac.to_entity_payloads(e).items()}])\n"
    "print(json.dumps(out, sort_keys=True, allow_nan=False))\n")
runs = [subprocess.run([sys.executable, "-I", "-B", "-c", script], capture_output=True, text=True, timeout=600) for _ in range(2)]
check("two interpreter processes (independent hash seeds) produce byte-identical envelopes and payloads",
      all(r.returncode == 0 for r in runs) and runs[0].stdout == runs[1].stdout and len(runs[0].stdout) > 1000,
      " | ".join(r.stderr[-200:] for r in runs))
here = []
for kw in ({}, {"synthetic_recorded": True}, {"stale_liveness": True}, {"paused": None}):
    e = run_cycle(cf.cycle_inputs(**kw))
    here.append([e.to_dict(), {k: list(v) for k, v in ac.to_entity_payloads(e).items()}])
check("... and the same as this process", runs[0].stdout.strip() == json.dumps(here, sort_keys=True, allow_nan=False))

print("== [8] the seams read no clock and touch no file")
for name in ("shadow_cycle.py", "quality.py"):
    tree = ast.parse((ROOT / "intelligence" / name).read_text(encoding="utf-8"))
    mods = {a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names} | \
           {(n.module or "").split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.level == 0}
    calls = {ast.unparse(n.func) for n in ast.walk(tree) if isinstance(n, ast.Call)}
    attrs = {n.func.attr for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
    names = {n.func.id for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    clock = {"now", "utcnow", "today", "time", "time_ns", "monotonic", "monotonic_ns", "perf_counter", "process_time",
             "localtime", "gmtime", "ctime"}
    imported_names = {a.asname or a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom))
                      for a in n.names}
    # getattr on an imported module or class (datetime, timezone, ...) with a computed name or a clock / I/O name
    dyn_attr = [ast.unparse(n) for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                and n.func.id in ("getattr", "setattr", "hasattr") and len(n.args) > 1
                and isinstance(n.args[0], ast.Name) and n.args[0].id in imported_names
                and (not isinstance(n.args[1], ast.Constant) or n.args[1].value in clock | {"open", "system", "__import__"})]
    check(f"{name}: no os / time / io / pathlib / socket / subprocess / sys / builtins / importlib import",
          not (mods & {"os", "time", "io", "pathlib", "socket", "subprocess", "shutil", "sys", "builtins", "importlib", "nt",
                       "posix", "_thread", "threading", "asyncio"}), str(mods))
    check(f"{name}: no datetime.now / utcnow / today / time.time / open()",
          not (attrs & {"now", "utcnow", "today", "time_ns", "monotonic", "perf_counter"})
          and not [c for c in calls if c in ("open", "time.time", "input", "print")], str(sorted(attrs & {"now", "utcnow", "today"})))
    check(f"{name}: no dynamic import, exec / eval / compile, or getattr of a clock or a computed name",
          not (names & {"__import__", "exec", "eval", "compile", "breakpoint", "vars", "globals", "locals"}) and not dyn_attr
          and not [c for c in calls if c.startswith("__import__")], str(sorted(names & {"__import__", "exec", "eval"})) + str(dyn_attr[:3]))

print("== [9] the conditional gates are wired, and INVALID always BLOCKs")
syn = cf.synthetic_decisions()


def item_codes(e, k):
    return {c for c, _t in e.item(k).blockers}


d4 = run_cycle(cf.cycle_inputs(decisions=syn.without("D4"), accept_provenance=cf.SYNTHETIC_ACCEPT))
CAP_ITEMS = ("charge_target", "export_event", "dump_to_grid", "predicted_morning_soc")
check("several capacity sources present (stated, helper, FE-1, Ah) and I-D4 OPEN: every capacity item BLOCKs DECISION_D4_OPEN",
      all(d4.item(k).status == "BLOCKED" and "DECISION_D4_OPEN" in item_codes(d4, k) for k in CAP_ITEMS),
      str({k: sorted(item_codes(d4, k))[:4] for k in CAP_ITEMS}))
EVE = datetime(2030, 10, 26, 20, 0, tzinfo=timezone.utc)          # the evening before the 27 Oct 2030 change
from intelligence.periods import clock_changes  # noqa: E402
check("the eve is fictional 2030 data: the evening before the 27 Oct 2030 clock change (Europe/London)",
      EVE.year == 2030 and [c.local_day.isoformat() for c in clock_changes(EVE, EVE + timedelta(days=1))] == ["2030-10-27"],
      str(clock_changes(EVE, EVE + timedelta(days=1))))
d9 = run_cycle(cf.cycle_inputs(now=EVE, decisions=syn.without("D9"), accept_provenance=cf.SYNTHETIC_ACCEPT))
check("the eve of a clock change with I-D9 OPEN: charge_target, overnight_demand, predicted_morning_soc BLOCK DECISION_D9_OPEN",
      all(d9.item(k).status == "BLOCKED" and "DECISION_D9_OPEN" in item_codes(d9, k)
          for k in ("charge_target", "overnight_demand", "predicted_morning_soc")),
      str({k: (d9.item(k).status, sorted(item_codes(d9, k))[:4]) for k in ("charge_target", "overnight_demand")}))
d9r = run_cycle(cf.cycle_inputs(now=EVE, synthetic_recorded=True))
check("... and with I-D9 recorded the fixed rule still BLOCKs a charge window starting in the repeated hour (01:00 on 27 Oct)",
      all("DST_BOUNDARY_IN_CHANGED_HOUR" in item_codes(d9r, k) for k in ("charge_target", "overnight_demand", "predicted_morning_soc")),
      str(sorted(item_codes(d9r, "charge_target"))[:5]))
eve_open = run_cycle(cf.cycle_inputs(now=EVE))
check("... all OPEN on the eve of the change: every gated item BLOCKED and no leak", all_blocked(eve_open) and leaks(eve_open) == [],
      str(leaks(eve_open)[:3]))
for did, raw in (("D9", {"value": "garbage"}), ("D4", {"provenance": "SYNTHETIC_TEST", "value": {"pct": 99}}),
                 ("D8", {"provenance": "SYNTHETIC_TEST", "value": {"cutover": "2030-01-01T00:00:00+00:00"}})):
    bad = sd.DecisionSet({**syn.decisions, did: sd.DecisionSet.from_mapping({did: raw}, source="test").get(did)})
    e = run_cycle(cf.cycle_inputs(decisions=bad, accept_provenance=cf.SYNTHETIC_ACCEPT))
    code = f"DECISION_{did}_INVALID"
    gated = [k for k in sd.items_gated_by(did) if k in ac.ADVICE_ITEMS + ac.FORECAST_ITEMS]
    check(f"an INVALID {sd.display_label(did)} out of any conditional scope: a top-level {code} BLOCK and every item it can gate "
          "BLOCKED with it", bad.status(did) == "INVALID" and code in {c for c, _t in e.blockers} and e.status == "BLOCKED"
          and gated and all(e.item(k).status == "BLOCKED" and code in item_codes(e, k) for k in gated),
          str((e.status, [c for c, _t in e.blockers][:4])))

print("")
if FAILURES:
    print(f"{len(FAILURES)} check(s) FAILED:")
    for f in FAILURES:
        print("  -", f)
    sys.exit(1)
print("all SHADOW-cycle contract checks passed")
