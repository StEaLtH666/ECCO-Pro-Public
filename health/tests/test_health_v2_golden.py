#!/usr/bin/env python3
"""Health v2 H1: deterministic golden vectors for the EXISTING pure health engine, and the contract ledger that H0 records.

Companion of docs/HEALTH_V2_H0_CONTRACT.md. Offline and synthetic: no Home Assistant, no network, no clock (every vector carries
its own fixed 'now'), no real HA history, no private data. Standard library plus PyYAML (already required by the engine).

WHAT THIS SUITE PROVES, AND WHAT IT DOES NOT
  ENGINE vectors     health/system_health.py and the real registry/*.yaml, evaluated on synthetic CheckInputs. A PASS means the
                     CURRENT engine behaves exactly as the vector says. It says nothing about Home Assistant.
  Aggregation vectors  worst-of / tier-cap / UNKNOWN rules on synthetic check results (evaluate_subsystem, evaluate_overall).
  Contract ledger    read-only facts about the current registry, docs and the HA health package (M-01 ... M-14). A PASS means the
                     fact STILL holds; a failure means existing code changed and the contract must be revisited. No behaviour
                     is changed or approved here.
  PENDING vectors    future Health v2 / Home Assistant semantics. They are checked only for being well formed. They are never
                     counted as PASS and assert nothing about any implementation.

Nothing here installs a gate, lowers a threshold, edits an existing file or writes anywhere. Run from the repository root:

    python health/tests/test_health_v2_golden.py
"""

from __future__ import annotations

import json
import random
import re
import sys
from dataclasses import fields
from datetime import date, datetime, time, timedelta, timezone, tzinfo
from pathlib import Path

sys.dont_write_bytecode = True

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
FIXTURES = HERE / "fixtures"
sys.path.insert(0, str(ROOT / "health"))
sys.path.insert(0, str(ROOT))

import system_health as sh  # noqa: E402

FAILURES: list[str] = []
COUNTS = {"engine": 0, "aggregation": 0, "ledger": 0, "invariant": 0, "model": 0}


def check(kind: str, name: str, condition: bool, detail: str = "") -> None:
    if condition:
        COUNTS[kind] = COUNTS.get(kind, 0) + 1
        print(f"  PASS  {name}")
    else:
        FAILURES.append(name)
        print(f"  FAIL  {name}" + (f" - {detail}" if detail else ""))


def load_json(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def parse_utc(text: str) -> datetime:
    return datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


CHECKS = sh.load_check_registry()
REASONS = sh.load_reason_codes()
VECTORS = load_json("health_v2_golden_vectors.json")
MAPPING = load_json("health_v2_ha_mapping.json")
LEDGER = load_json("health_v2_contract_ledger.json")
DEFAULT_NOW = parse_utc(VECTORS["default_now"])

# ---------------------------------------------------------------------------------------------------------------------------
# A self-contained Europe/London model for the two clock-change nights used here (no tz database needed, so the result is the
# same on every machine). Valid for any year by the usual rule: BST from the last Sunday of March 01:00 UTC to the last Sunday of
# October 01:00 UTC.
# ---------------------------------------------------------------------------------------------------------------------------

_HOUR = timedelta(hours=1)


class _London(tzinfo):
    @staticmethod
    def _bounds(year: int) -> tuple[datetime, datetime]:
        def last_sunday(month: int) -> date:
            d = date(year, month, 31)
            return d - timedelta(days=(d.weekday() + 1) % 7)
        return datetime.combine(last_sunday(3), time(1, 0)), datetime.combine(last_sunday(10), time(1, 0))

    def utcoffset(self, dt):
        wall = dt.replace(tzinfo=None)
        start, end = self._bounds(wall.year)
        if start + _HOUR <= wall < end:
            return _HOUR
        if end <= wall < end + _HOUR:  # the repeated hour: fold 0 = first pass (BST), fold 1 = second pass (GMT)
            return _HOUR if dt.fold == 0 else timedelta(0)
        return timedelta(0)

    def dst(self, dt):
        return self.utcoffset(dt)

    def tzname(self, dt):
        return "BST" if self.utcoffset(dt) else "GMT"

    def fromutc(self, dt):
        u = dt.replace(tzinfo=None)
        start, end = self._bounds(u.year)
        local = u + (_HOUR if start <= u < end else timedelta(0))
        return local.replace(tzinfo=self, fold=1 if end <= u < end + _HOUR else 0)


LONDON = _London()  # ONE shared instance: datetimes that share it are subtracted by wall clock, which is the hazard under test

# ---------------------------------------------------------------------------------------------------------------------------
# Synthetic input construction
# ---------------------------------------------------------------------------------------------------------------------------

DT_FIELDS = ("last_updated", "active_since", "baseline_observed_at", "timestamp_a", "timestamp_b")
INPUT_FIELDS = {f.name for f in fields(sh.CheckInput)}


def healthy_input_for(chk: sh.CheckDef, now: datetime) -> sh.CheckInput:
    inp = sh.CheckInput()
    ct = chk.check_type
    if ct in ("freshness", "timestamp_age"):
        inp.last_updated = now - timedelta(seconds=1)
    elif ct == "boolean_expected":
        inp.value = chk.parameters.get("expected_value", True)
    elif ct == "numeric_range":
        inp.value = (chk.parameters.get("min", 0) + chk.parameters.get("max", 0)) / 2
    elif ct == "text_state":
        inp.value = "normal"
    elif ct == "transaction_state":
        inp.active = False
    elif ct == "failure_counter_delta":
        inp.baseline_counter_value = 5
        inp.counter_value = 5
        inp.baseline_observed_at = now - timedelta(seconds=chk.parameters.get("window_seconds", 600) + 10)
    elif ct == "cross_source_agreement":
        inp.value_a, inp.value_b = 1, 1
        inp.timestamp_a, inp.timestamp_b = now, now
    elif ct == "history_depth":
        inp.depth_value = chk.parameters.get("minimum_value", 0) + 100
    elif ct == "entity_available":
        inp.available, inp.ever_observed = True, True
    elif ct == "version_match":
        inp.value = True if chk.rollup_participation == sh.ROLLUP_AUTOMATIC else None
    elif ct == "conditional_presence":
        inp.checkpoint_passed, inp.scored_since_checkpoint = True, True
    return inp


def baseline_signals(now: datetime) -> dict[str, sh.CheckInput]:
    return {cid: healthy_input_for(chk, now) for cid, chk in CHECKS.items()}


def dt_value(spec, now: datetime):
    if spec is None:
        return None
    if isinstance(spec, dict):
        if "age_s" in spec:
            return now - timedelta(seconds=spec["age_s"])
        if "utc" in spec:
            return parse_utc(spec["utc"])
        raise ValueError(f"bad datetime spec {spec!r}")
    raise ValueError(f"bad datetime spec {spec!r}")


def apply_set(signals: dict[str, sh.CheckInput], spec: dict, now: datetime) -> None:
    for cid, changes in spec.items():
        if cid not in signals:
            raise KeyError(f"vector sets unknown check {cid!r}")
        for name, val in changes.items():
            if name not in INPUT_FIELDS:
                raise KeyError(f"CheckInput has no field {name!r}")
            setattr(signals[cid], name, dt_value(val, now) if name in DT_FIELDS else val)


def apply_transform(signals: dict[str, sh.CheckInput], transform: str) -> None:
    if transform != "ha_restart":
        raise ValueError(f"unknown transform {transform!r}")
    for cid, chk in CHECKS.items():
        s = signals[cid]
        if chk.check_type == "failure_counter_delta":
            s.baseline_counter_value = None
            s.baseline_observed_at = None
        elif chk.check_type == "transaction_state":
            s.active = None
            s.active_since = None


def render(signals: dict[str, sh.CheckInput], now: datetime, mode: str) -> datetime:
    """Return 'now' as rendered for the mode and convert the datetimes inside the inputs in place."""
    if mode == "utc":
        return now
    if mode not in ("london_same_tz", "london_now_utc_inputs"):
        raise ValueError(f"unknown render mode {mode!r}")
    if mode == "london_same_tz":
        for s in signals.values():
            for name in DT_FIELDS:
                v = getattr(s, name)
                if v is not None:
                    setattr(s, name, v.astimezone(LONDON))
    return now.astimezone(LONDON)


def ha_represented_ids() -> set[str]:
    ids: set[str] = set()
    for s in MAPPING["sensors"]:
        rc = s["represented_checks"]
        if rc == "ALL_FALLBACK_SUBSYSTEM_CHECKS":
            ids |= {cid for cid, c in CHECKS.items() if c.subsystem == "fallback"}
        else:
            ids |= set(rc)
    return ids


class Run:
    """Everything the engine returns for one signal set."""

    def __init__(self, signals: dict[str, sh.CheckInput], now: datetime):
        self.check_results, self.subsystems, self.overall, self.readiness = sh.evaluate_all(CHECKS, REASONS, signals, now)
        self.by_check = {r.check_id: r for r in self.check_results}
        self.by_subsystem = {s.subsystem: s for s in self.subsystems}


def run_vector(v: dict) -> Run:
    now = parse_utc(v["now"]) if "now" in v else DEFAULT_NOW
    signals = baseline_signals(now)
    if v.get("only_checks_from") == "ha_represented":
        keep = ha_represented_ids()
        signals = {cid: s for cid, s in signals.items() if cid in keep}
    if v.get("transform"):
        apply_transform(signals, v["transform"])
    apply_set(signals, v.get("set", {}), now)
    for cid in v.get("omit", []):
        signals.pop(cid)
    now = render(signals, now, v.get("render", "utc"))
    return Run(signals, now)


def compare_expect(run: Run, expect: dict) -> list[str]:
    bad: list[str] = []
    for cid, e in expect.get("checks", {}).items():
        r = run.by_check.get(cid)
        if r is None:
            bad.append(f"{cid}: not evaluated")
            continue
        if r.state != e["state"]:
            bad.append(f"{cid}: state {r.state} != {e['state']}")
        if sorted(r.reason_codes) != sorted(e["codes"]):
            bad.append(f"{cid}: codes {r.reason_codes} != {e['codes']}")
        if "age_s" in e and (r.age_seconds is None or abs(r.age_seconds - e["age_s"]) > 1e-6):
            bad.append(f"{cid}: age {r.age_seconds} != {e['age_s']}")
        if "reason_contains" in e and e["reason_contains"] not in r.human_reason:
            bad.append(f"{cid}: reason {r.human_reason!r} lacks {e['reason_contains']!r}")
    for cid in expect.get("absent", []):
        if cid in run.by_check:
            bad.append(f"{cid}: unexpectedly evaluated")
    for name, state in expect.get("subsystems", {}).items():
        s = run.by_subsystem.get(name)
        if s is None or s.state != state:
            bad.append(f"subsystem {name}: {None if s is None else s.state} != {state}")
    if "overall" in expect:
        e, o = expect["overall"], run.overall
        if o.state != e["state"]:
            bad.append(f"overall state {o.state} != {e['state']}")
        if o.severity_rank != e["rank"]:
            bad.append(f"overall rank {o.severity_rank} != {e['rank']}")
        for name in e.get("contains", []):
            if name not in o.contributing_subsystems:
                bad.append(f"overall lacks contributor {name}")
        for name in e.get("excludes", []):
            if name in o.contributing_subsystems:
                bad.append(f"overall wrongly contains {name}")
        if "codes" in e and sorted(o.reason_codes) != sorted(e["codes"]):
            bad.append(f"overall codes {o.reason_codes} != {e['codes']}")
    if "readiness" in expect:
        e, c = expect["readiness"], run.readiness
        if c.ready != e["ready"]:
            bad.append(f"ready {c.ready} != {e['ready']}")
        for key, got in (("blocking", c.blocking_checks), ("insufficient", c.insufficient_evidence_checks), ("missing", c.missing_required_checks)):
            if key in e and sorted(got) != sorted(e[key]):
                bad.append(f"readiness {key} {sorted(got)} != {sorted(e[key])}")
    return bad


# ===========================================================================================================================
print("[0] fixtures and model self-checks")
# ===========================================================================================================================

ids_seen: set[str] = set()
dup = False
for group in ("engine_vectors", "aggregation_vectors", "pending_vectors"):
    for v in VECTORS[group]:
        if v["id"] in ids_seen:
            dup = True
        ids_seen.add(v["id"])
check("model", "vector ids are unique across engine, aggregation and pending vectors", not dup)
check("model", "fixture schemas are the expected versions",
      VECTORS["schema"] == "ecco-health-v2-golden/1" and MAPPING["schema"] == "ecco-health-v2-ha-mapping/1"
      and LEDGER["schema"] == "ecco-health-v2-ledger/1")

unknown_ids: list[str] = []
for v in VECTORS["engine_vectors"]:
    for cid in list(v.get("set", {})) + list(v.get("omit", [])) + list(v.get("expect", {}).get("checks", {})) \
            + list(v.get("expect", {}).get("absent", [])):
        if cid not in CHECKS:
            unknown_ids.append(f"{v['id']}:{cid}")
    exp = v.get("expect", {})
    for cid, e in exp.get("checks", {}).items():
        for code in e["codes"]:
            if code not in REASONS:
                unknown_ids.append(f"{v['id']}:{code}")
    for key in ("blocking", "insufficient", "missing"):
        for cid in exp.get("readiness", {}).get(key, []):
            if cid not in CHECKS:
                unknown_ids.append(f"{v['id']}:{cid}")
    for name in list(exp.get("subsystems", {})) + list(exp.get("overall", {}).get("contains", [])):
        if name not in sh.SUBSYSTEM_TIER:
            unknown_ids.append(f"{v['id']}:{name}")
check("model", "every check id, reason code and subsystem named by an engine vector exists in the real registry",
      not unknown_ids, str(unknown_ids))

# the London model: round trip and (when a tz database exists) agreement with zoneinfo
probes = [parse_utc(t) for t in ("2026-10-24T23:00:00Z", "2026-10-25T00:59:50Z", "2026-10-25T01:00:00Z", "2026-10-25T01:00:50Z",
                                 "2027-03-28T00:59:50Z", "2027-03-28T01:00:00Z", "2027-03-28T01:00:50Z", "2026-07-01T12:00:00Z")]
roundtrip = all(p.astimezone(LONDON).astimezone(timezone.utc) == p for p in probes)
check("model", "the built-in Europe/London model round-trips the clock-change instants", roundtrip)
wall = {p.strftime("%Y-%m-%dT%H:%M:%SZ"): p.astimezone(LONDON) for p in probes}
check("model", "fall-back: 00:59:50Z is 01:59:50 BST (first pass), 01:00:50Z is 01:00:50 GMT (second pass, fold=1)",
      wall["2026-10-25T00:59:50Z"].strftime("%H:%M:%S") == "01:59:50" and wall["2026-10-25T00:59:50Z"].fold == 0
      and wall["2026-10-25T01:00:50Z"].strftime("%H:%M:%S") == "01:00:50" and wall["2026-10-25T01:00:50Z"].fold == 1)
check("model", "spring-forward: 00:59:50Z is 00:59:50 GMT, 01:00:50Z is 02:00:50 BST",
      wall["2027-03-28T00:59:50Z"].strftime("%H:%M:%S") == "00:59:50" and wall["2027-03-28T01:00:50Z"].strftime("%H:%M:%S") == "02:00:50")
check("model", "the 25 Oct 2026 UK day is 25 h and the 28 Mar 2027 UK day is 23 h",
      (datetime(2026, 10, 26, tzinfo=LONDON).astimezone(timezone.utc) - datetime(2026, 10, 25, tzinfo=LONDON).astimezone(timezone.utc)) == timedelta(hours=25)
      and (datetime(2027, 3, 29, tzinfo=LONDON).astimezone(timezone.utc) - datetime(2027, 3, 28, tzinfo=LONDON).astimezone(timezone.utc)) == timedelta(hours=23))
try:
    from zoneinfo import ZoneInfo
    zi = ZoneInfo("Europe/London")
    agree = all(p.astimezone(zi).utcoffset() == p.astimezone(LONDON).utcoffset() for p in probes)
    check("model", "the built-in London model agrees with the system tz database at every probe", agree)
except Exception as exc:  # no tz database on this machine: not a failure, the built-in model is the reference
    print(f"  SKIP  system tz database comparison ({type(exc).__name__}); the built-in model is authoritative here")

# ===========================================================================================================================
print("")
print("[1] ENGINE golden vectors (current health/system_health.py + real registry; synthetic inputs)")
# ===========================================================================================================================

RESULTS: dict[str, Run] = {}
for v in VECTORS["engine_vectors"]:
    try:
        run = run_vector(v)
        RESULTS[v["id"]] = run
        bad = compare_expect(run, v["expect"])
    except Exception as exc:  # a malformed vector is a failure, not a skip
        bad = [f"{type(exc).__name__}: {exc}"]
    gap = f" [known gap {v['known_gap']}]" if v.get("known_gap") else ""
    check("engine", f"{v['id']} {v['title']}{gap}", not bad, "; ".join(bad))

# determinism: the same vector twice, and in a shuffled signal order, gives an identical outcome
det_ok = True
for v in VECTORS["engine_vectors"]:
    a = RESULTS[v["id"]]
    b = run_vector(v)
    sig = (lambda r: (r.overall, r.readiness, [(c.check_id, c.state, c.reason_codes, c.human_reason, c.age_seconds) for c in sorted(r.check_results, key=lambda x: x.check_id)]))
    if sig(a) != sig(b):
        det_ok = False
check("invariant", "every engine vector gives an identical result when evaluated twice", det_ok)

now0 = DEFAULT_NOW
base = baseline_signals(now0)
shuffled = dict(random.Random(20261018).sample(sorted(base.items()), len(base)))
r_a, r_b = Run(base, now0), Run(shuffled, now0)
check("invariant", "overall and readiness do not depend on the order the signals are supplied in",
      r_a.overall == r_b.overall and r_a.readiness == r_b.readiness)

# ===========================================================================================================================
print("")
print("[2] aggregation vectors (worst-of, tier caps, UNKNOWN rules) on synthetic check results")
# ===========================================================================================================================

for v in VECTORS["aggregation_vectors"]:
    try:
        results = [
            sh.CheckResult("synthetic", r["subsystem"], r["state"], list(r["codes"]), "synthetic", None, r.get("rollup", sh.ROLLUP_AUTOMATIC))
            for r in v["results"]
        ]
        subs = [sh.evaluate_subsystem(s, results) for s in sorted({r.subsystem for r in results})]
        o = sh.evaluate_overall(subs)
        e = v["expect"]
        bad = []
        if o.state != e["state"]:
            bad.append(f"state {o.state} != {e['state']}")
        if o.severity_rank != e["rank"]:
            bad.append(f"rank {o.severity_rank} != {e['rank']}")
        for name in e.get("contains", []):
            if name not in o.contributing_subsystems:
                bad.append(f"lacks {name}")
        if "contains" in e and not e["contains"] and o.contributing_subsystems:
            bad.append(f"expected no contributors, got {o.contributing_subsystems}")
        for name in e.get("excludes", []):
            if name in o.contributing_subsystems:
                bad.append(f"wrongly contains {name}")
        if "codes" in e and sorted(o.reason_codes) != sorted(e["codes"]):
            bad.append(f"codes {o.reason_codes} != {e['codes']}")
    except Exception as exc:
        bad = [f"{type(exc).__name__}: {exc}"]
    check("aggregation", f"{v['id']} {v['title']}", not bad, "; ".join(bad))

# ===========================================================================================================================
print("")
print("[3] engine invariants swept over the whole registry")
# ===========================================================================================================================

bare_healthy = [cid for cid, chk in CHECKS.items()
                if sh.evaluate_check(chk, sh.CheckInput(), REASONS, now0).state == sh.HEALTHY]
check("invariant", "a bare CheckInput (no evidence supplied) is never HEALTHY, for any of the 63 registry checks",
      not bare_healthy, str(bare_healthy))

required = sh.required_control_checks(CHECKS, REASONS)
check("invariant", "the required-for-control set is exactly the 11 recorded in the ledger",
      sorted(required) == sorted(LEDGER["registry"]["required_control_checks"]), str(sorted(required)))
omit_ok, bare_ok = True, True
for cid in sorted(required):
    sig = baseline_signals(now0)
    sig.pop(cid)
    run = Run(sig, now0)
    if run.readiness.ready or cid not in run.readiness.missing_required_checks:
        omit_ok = False
    sig = baseline_signals(now0)
    sig[cid] = sh.CheckInput()
    run = Run(sig, now0)
    if run.readiness.ready:
        bare_ok = False
check("invariant", "removing any one required check makes readiness False and names it as missing", omit_ok)
check("invariant", "replacing any one required check's evidence by a bare CheckInput makes readiness False", bare_ok)

ranks_ok, order = True, {sh.HEALTHY: 0, sh.DEGRADED: 1, sh.FAILED: 3}
for cid, subsystem in (("telemetry_freshness", "inverter_telemetry"), ("configuration_freshness", "inverter_configuration"),
                       ("rtc_read_freshness", "rtc_time")):
    prev_rank = -1
    for age in range(0, 701):
        sig = baseline_signals(now0)
        sig[cid].last_updated = now0 - timedelta(seconds=age)
        run = Run(sig, now0)
        rank = max(sh.SEVERITY_RANK[run.by_check[cid].state], 0)
        if rank < prev_rank or run.overall.severity_rank < (0 if rank == 0 else 1):
            ranks_ok = False
        prev_rank = rank
check("invariant", "ageing evidence 0..700 s never improves a freshness check or the overall rank (monotonic)", ranks_ok)

tier_ok = all(sh.TIER_CAP[sh.SUBSYSTEM_TIER[s]] in (1, 2, 3) for s in sh.SUBSYSTEM_TIER) \
    and {c.subsystem for c in CHECKS.values()} <= set(sh.SUBSYSTEM_TIER)
check("invariant", "every registry subsystem has a criticality tier", tier_ok)

# ===========================================================================================================================
print("")
print("[4] contract ledger: facts about the current registry, docs and HA package (M-01 ... M-14)")
# ===========================================================================================================================

try:
    ARCH = (ROOT / "docs" / "SYSTEM_HEALTH_ARCHITECTURE.md").read_text(encoding="utf-8")
    PKG = (ROOT / "home-assistant" / "packages" / "ecco_system_health.yaml").read_text(encoding="utf-8")
    import yaml
    REG_RAW = yaml.safe_load((ROOT / "registry" / "system_health_checks.yaml").read_text(encoding="utf-8"))
    PKG_FILES = {p.name: p.read_text(encoding="utf-8") for p in sorted((ROOT / "home-assistant" / "packages").glob("*.yaml"))}
    inputs_ok = True
except Exception as exc:
    inputs_ok = False
    check("ledger", "ledger inputs could be read", False, str(exc))

if inputs_ok:
    reg = LEDGER["registry"]
    import collections
    check("ledger", "registry totals: 63 checks, 70 reason codes, 16 subsystems",
          len(CHECKS) == reg["checks_total"] and len(REASONS) == reg["reason_codes_total"]
          and len({c.subsystem for c in CHECKS.values()}) == reg["subsystems_total"])
    check("ledger", "registry implementation_status 41 designed / 22 implemented_offline; live_proof_status all 'unknown'",
          dict(collections.Counter(c.get("implementation_status") for c in REG_RAW["checks"])) == reg["implementation_status"]
          and dict(collections.Counter(c.get("live_proof_status") for c in REG_RAW["checks"])) == reg["live_proof_status"])
    check("ledger", "registry rollup participation 58 automatic / 3 diagnostic_only / 2 manual_only",
          dict(collections.Counter(c.get("rollup_participation", "automatic") for c in REG_RAW["checks"])) == reg["rollup_participation"])

    ledger_ids = [m["id"] for m in LEDGER["mismatches"]]
    check("ledger", "ledger ids are M-01 ... M-14 in order", ledger_ids == [f"M-{i:02d}" for i in range(1, 15)], str(ledger_ids))

    def vec_ok(*vids: str) -> bool:
        by_id = {x["id"]: x for x in VECTORS["engine_vectors"]}
        return all(i in RESULTS and not compare_expect(RESULTS[i], by_id[i]["expect"]) for i in vids)

    # M-01
    check("ledger", "M-01 the architecture document still says '43-check' and '46 reason codes' while the registry has 63 / 70",
          "full 43-check" in ARCH and "of 46 reason codes" in ARCH and len(CHECKS) == 63 and len(REASONS) == 70)

    # M-02
    uids = re.findall(r"^\s*unique_id:\s*(ecco_health_[a-z_]+)\s*$", PKG, re.M)
    all_pkg_uids = [u for text in PKG_FILES.values() for u in re.findall(r"^\s*unique_id:\s*([A-Za-z0-9_]+)\s*$", text, re.M)]
    absent_ok = not any(u in all_pkg_uids for u in MAPPING["absent_designed_entities"])
    check("ledger", "M-02 exactly the ten ecco_health_* sensors exist; the rollup, attention flag and gating readiness entity do not",
          sorted(uids) == sorted(LEDGER["ha_package"]["health_sensor_unique_ids"]) and len(uids) == 10 and absent_ok
          and MAPPING["non_gating_reference_entity"] in all_pkg_uids
          and "REFERENCE ONLY, DO NOT USE TO GATE" in PKG, f"{uids} absent_ok={absent_ok}")

    # the HA mapping fixture against the package text
    blocks: dict[str, str] = {}
    positions = [(m.start(), m.group(1)) for m in re.finditer(r"^\s*unique_id:\s*([A-Za-z0-9_]+)\s*$", PKG, re.M)]
    for i, (pos, uid) in enumerate(positions):
        blocks[uid] = PKG[pos:(positions[i + 1][0] if i + 1 < len(positions) else len(PKG))]
    map_bad: list[str] = []
    for s in MAPPING["sensors"]:
        block = blocks.get(s["unique_id"], "")
        parsed = None
        m = re.search(r"represented_checks:\s*\"\{\{\s*\[(.*?)\]\s*\}\}\"", block, re.S)
        if m:
            parsed = set(re.findall(r"'([a-z0-9_]+)'", m.group(1)))
        expect_ids = ({cid for cid, c in CHECKS.items() if c.subsystem == "fallback"} if s["represented_checks"] == "ALL_FALLBACK_SUBSYSTEM_CHECKS"
                      else set(s["represented_checks"]))
        if s["source"] == "attribute" and parsed != expect_ids:
            map_bad.append(f"{s['unique_id']}: package {sorted(parsed or [])} != fixture {sorted(expect_ids)}")
        if s["source"] == "comment" and parsed is not None:
            map_bad.append(f"{s['unique_id']}: fixture says comment-only but the package now declares represented_checks")
        if ("partial_implementation: true" in block) != s["declares_partial"]:
            map_bad.append(f"{s['unique_id']}: partial_implementation mismatch")
        if re.search(r"sufficient_for_control_decision:\s*true", block):
            map_bad.append(f"{s['unique_id']}: declares sufficient_for_control_decision true")
        for cid in expect_ids | set(s["simplified_checks"]):
            if cid not in CHECKS:
                map_bad.append(f"{s['unique_id']}: {cid} not in registry")
        for sub in s["subsystems"]:
            if sub not in sh.SUBSYSTEM_TIER:
                map_bad.append(f"{s['unique_id']}: unknown subsystem {sub}")
    check("ledger", "the frozen HA mapping equals what the package declares (represented_checks, partial_implementation, never sufficient for control)",
          not map_bad, "; ".join(map_bad))

    represented = ha_represented_ids()
    not_full = sorted(c for c in required if c not in represented)
    check("ledger", "10/10 is not clearance: three of the 11 control-required checks are not fully represented in HA (esphome_reachable and the two simplified freshness checks)",
          not_full == sorted(MAPPING["required_checks_not_fully_represented"]), str(not_full))
    unrep_total = sorted(c for c in CHECKS if c not in represented)
    check("ledger", "the ten HA sensors declare 32 of the 63 registry checks as represented; 31 are not (the two simplified freshness checks are among the 31)",
          len(represented) == 32 and len(unrep_total) == 31 and {"telemetry_freshness", "configuration_freshness"} <= set(unrep_total),
          f"{len(represented)}/{len(unrep_total)}")

    # M-03
    sub_f = {f.name for f in fields(sh.SubsystemResult)}
    chk_f = {f.name for f in fields(sh.CheckResult)}
    ov_f = {f.name for f in fields(sh.OverallHealthResult)}
    documented_missing = {"last_good", "source_signals", "age_seconds", "blocks_manual_control", "affects_forecast_only", "informational_only"}
    check("ledger", "M-03 SubsystemResult has none of the evidence fields the architecture lists; CheckResult has only age_seconds; OverallHealthResult has no evidence fields",
          not (documented_missing & sub_f) and "last_good" not in chk_f and {"source", "provenance", "observed_at"}.isdisjoint(chk_f | sub_f | ov_f)
          and "age_seconds" in chk_f and ov_f == {"state", "severity_rank", "contributing_subsystems", "reason_codes"},
          f"{sorted(sub_f)} {sorted(chk_f)} {sorted(ov_f)}")
    check("ledger", "M-03 the architecture document does list those fields for SubsystemResult",
          all(w in ARCH for w in ("last_good", "source_signals", "blocks_manual_control", "informational_only")))

    check("ledger", "M-04 an absent required check leaves overall HEALTHY while readiness lists it as missing (HV-B02, HV-B06)", vec_ok("HV-B02", "HV-B06"))
    check("ledger", "M-05 a future timestamp is HEALTHY in the engine (HV-D11) and ecco_core.freshness documents the opposite", vec_ok("HV-D11"))
    try:
        from ecco_core import freshness as ecf
        ecf_src = Path(ecf.__file__).read_text(encoding="utf-8")
        future_rule = "unknown or in the future" in (ecf.__doc__ or "") and "observation time unknown or in the future" in ecf_src
        check("ledger", "M-05 ecco_core.freshness treats an observation time that is unknown or in the future as never fresh", future_rule)
    except Exception as exc:
        check("ledger", "M-05 ecco_core.freshness could be imported", False, str(exc))
        ecf = None

    check("ledger", "M-06 same-tzinfo local datetimes give wrong ages on both UK clock-change nights; UTC-aware and mixed inputs give the right ones",
          vec_ok("HV-F01", "HV-F02", "HV-F03", "HV-F04", "HV-F05", "HV-F06", "HV-F07", "HV-F08", "HV-F09"))
    check("ledger", "M-07 UNKNOWN from an INFORMATIONAL subsystem is reported with rank 1 (HV-B07)",
          vec_ok("HV-B07") and RESULTS["HV-B07"].overall.severity_rank == 1 and sh.SEVERITY_RANK[sh.UNKNOWN] == 2)

    comm = blocks["ecco_health_communications"]
    state_part = comm[:comm.index("attributes:")]
    check("ledger", "M-08 the HA communications state maps anything other than 'on' to FAILED, has no UNKNOWN branch and no age brackets",
          state_part.count("== 'on'") == 2 and "FAILED" in state_part and "UNKNOWN" not in state_part
          and "online/offline only" in comm and "last_changed" not in state_part)

    check("ledger", "M-09 the engine cannot tell an isolated from a sustained stall (HV-C01, HV-C02 identical)",
          vec_ok("HV-C01", "HV-C02") and CHECKS["rtc_stall_detected"].check_type == "boolean_expected"
          and "duration" not in json.dumps(CHECKS["rtc_stall_detected"].parameters))
    sync_codes = [c for c in REASONS if re.search(r"SYNC.*(DISABLED|OFF)|(DISABLED|OFF).*SYNC", c)]
    check("ledger", "M-10 with automatic clock sync OFF the drift check is SUPPRESSED, overall HEALTHY, and no 'sync disabled' reason code exists; HA does not represent rtc_drift_uncorrected",
          vec_ok("HV-C11") and not sync_codes and "rtc_drift_uncorrected" not in represented
          and CHECKS["rtc_drift_uncorrected"].applicability_condition == "automatic_clock_sync switch is on", str(sync_codes))

    check("ledger", "M-11 the engine needs a baseline older than the window and reports UNKNOWN after a reset; the HA RTC row's own comment says only a numeric-to-numeric increase is a failure",
          vec_ok("HV-C09", "HV-E02", "HV-E04") and re.search(r"numeric-to-numeric\s+INCREASE", PKG) is not None
          and "failure_counter_delta" == CHECKS["rtc_correction_failures_recent"].check_type)
    check("ledger", "M-12 HA durations come from last_changed and the architecture document records the restart/reconnect limitation",
          "last_changed" in PKG and "Restart/reconnect limitation" in ARCH)

    texts = {
        "never_updated": RESULTS["HV-B01"].by_check["telemetry_freshness"].human_reason,
        "observed_before": RESULTS["HV-B03"].by_check["esphome_reachable"].human_reason,
        "never_observed": RESULTS["HV-B04"].by_check["esphome_reachable"].human_reason,
        "start_unknown": RESULTS["HV-C06"].by_check["rtc_correction_duration"].human_reason,
        "baseline_young": RESULTS["HV-C09"].by_check["rtc_correction_failures_recent"].human_reason,
        "counter_reset": RESULTS["HV-E02"].by_check["rtc_correction_failures_recent"].human_reason,
        "no_baseline": RESULTS["HV-E03"].by_check["rtc_correction_failures_recent"].human_reason,
    }
    check("ledger", "M-13 each UNKNOWN cause has its own free-text reason today (distinct), but no machine-readable subtype field exists",
          len(set(texts.values())) == len(texts) and not {"subtype", "unknown_reason", "unknown_kind"} & chk_f, str(texts))

    if ecf is not None:
        cat = {(l.signal, l.purpose): l for l in ecf.CATALOGUE}
        tel, cfg = cat[("controller.telemetry", "health")], cat[("controller.configuration", "health")]
        t_fail = CHECKS["telemetry_freshness"].parameters["failure_threshold_seconds"]
        c_fail = CHECKS["configuration_freshness"].parameters["failure_threshold_seconds"]
        check("ledger", "M-14 the freshness catalogue carries the registry FAILURE thresholds (180 s, 600 s) and records the 60/180 s warning tiers only in a note; HA templates carry neither",
              tel.max_age_s == t_fail == 180 and cfg.max_age_s == c_fail == 600
              and "warning at 60" in tel.note and "warning at 180" in cfg.note
              and "warning_threshold_seconds" not in PKG)
    else:
        check("ledger", "M-14 the freshness catalogue could be read", False)

# ===========================================================================================================================
print("")
print("[5] PENDING vectors: future semantics, checked for form only (never counted as PASS)")
# ===========================================================================================================================

ledger_known = {m["id"] for m in LEDGER["mismatches"]}
pending_bad: list[str] = []
for p in VECTORS["pending_vectors"]:
    for key in ("id", "title", "requires", "semantics", "engine_today", "ledger"):
        if not p.get(key):
            pending_bad.append(f"{p.get('id')}: missing {key}")
    if p.get("ledger") not in ledger_known:
        pending_bad.append(f"{p['id']}: unknown ledger entry {p.get('ledger')}")
    if "expect" in p or "set" in p:
        pending_bad.append(f"{p['id']}: a PENDING vector must not carry engine expectations")
    # every engine vector a PENDING entry cites must exist
    for cited in re.findall(r"HV-[A-G]\d\d", p["engine_today"] + p["semantics"]):
        if cited not in {x["id"] for x in VECTORS["engine_vectors"]}:
            pending_bad.append(f"{p['id']}: cites missing {cited}")
check("model", f"all {len(VECTORS['pending_vectors'])} PENDING vectors are well formed, cite a ledger entry and carry no asserted outcome",
      not pending_bad, "; ".join(pending_bad))
for p in VECTORS["pending_vectors"]:
    print(f"  PENDING {p['id']} {p['title']}  [needs: {p['requires']}]")

# ===========================================================================================================================
print("")
total_pass = sum(COUNTS.values())
print(f"SUMMARY engine_vectors={COUNTS['engine']}/{len(VECTORS['engine_vectors'])} aggregation_vectors={COUNTS['aggregation']}/{len(VECTORS['aggregation_vectors'])} "
      f"ledger_checks={COUNTS['ledger']} invariants={COUNTS['invariant']} model_checks={COUNTS['model']} "
      f"pending={len(VECTORS['pending_vectors'])} (not asserted) failures={len(FAILURES)}")
if FAILURES:
    print(f"{len(FAILURES)} check(s) FAILED:")
    for name in FAILURES:
        print(f"  - {name}")
    sys.exit(1)
print("All Health v2 H1 golden checks PASSED.")
print("")
print("This proves what the CURRENT pure engine does on synthetic inputs, and that the recorded facts about the registry, docs and the")
print("HA health package still hold. It does NOT prove any Home Assistant behaviour, any live threshold, or any PENDING semantic.")
