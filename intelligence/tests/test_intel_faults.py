#!/usr/bin/env python3
"""Data quality (dq): every seeded fault injector of intelligence.faults is detected by its rule on every seed, and the clean
bases raise no BLOCK on the same seeds (fictional 2030 data; synthetic houses from synthetic.make_history).

  [0] CCR-DQ-1 has landed (at integration: the raw SOC, clock offset and event table are I-D6 keys with no default limit,
      judged under the synthetic I-D6's own 300 s): the clean fixture raises no BLOCK. The strict branch written before
      it landed is kept as a historical record and never runs on the integrated code
  [1] detection: each fault in faults.FAULTS, SEEDS seeds each, detected 100 % (its codes, and its items BLOCKED; a "both"
      fault by assess_inputs and by prepare_history)
  [2] no false blocks: the clean fixture, a clean synthetic house per seed (assess and prepare), the same house with
      balanced counters, the fixture shifted through the year, and the clock-change cases (WARN only)
  [3] the injectors are deterministic and never modify their input
  [1] to [3] call _dq_helpers.simulate_ccr_dq1, which does nothing on the integrated code, so the three readings are
  judged under the synthetic I-D6's own 300 s. The detection and false-block table is printed at the end.
"""

from __future__ import annotations

import sys
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import _cycle_fixtures as cf  # noqa: E402
import _dq_helpers as h  # noqa: E402
from intelligence import faults  # noqa: E402
from intelligence import quality as q  # noqa: E402
from intelligence import site_decisions as sd  # noqa: E402

FAILURES: list[str] = []
SEEDS = range(25)
DEC = cf.synthetic_decisions()


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  PASS  {name}")
    else:
        FAILURES.append(name)
        print(f"  FAIL  {name}" + (f" - {detail}" if detail else ""))


def house(seed: int):
    return replace(h.clean(), history=faults.synthetic_house(seed, cf.NOW))


def items_requiring(key: str) -> list[str]:
    out = []
    for i in sd.ITEMS:
        ri = sd.required_inputs(i, DEC, h.SYN)
        if key in ri.signals + ri.readings + ri.charge_window_sources or (key == "tariff.events" and i == "export_event"):
            out.append(i)
    return out


def detected(spec: faults.FaultSpec, inp, seed: int) -> tuple[bool, str]:
    if spec.detector in ("prepare", "both"):
        hp, fp = q.prepare_history(inp.history, DEC, inp.now, accept_provenance=h.SYN)
        found = {f.code for f in fp}
        must_none = bool(spec.codes & {"HISTORY_CT_REVERSED", "HISTORY_LOAD_FALSE_ZERO_AFTER_CUTOVER"})
        ok = bool(found & spec.codes) and (hp is None) == must_none
        if spec.detector == "prepare" or not ok:
            return ok, "prepare: " + str(sorted(found))
    r = q.assess_inputs(inp)
    found = h.codes(r)
    ok = bool(found & spec.codes) and set(spec.blocks) <= r.blocked_items
    key = None
    if spec.name == "malformed_reading":
        key = faults.malformed_choice(seed)[0]
    elif spec.name == "missing_input":
        key = faults.missing_choice(seed)
    elif spec.name == "future_timestamp":
        key = faults.future_choice(seed)[0]
    if key is not None:
        need = items_requiring(key) if key != "history.hourly" else list(sd.ITEMS)
        ok = ok and bool(need) and set(need) <= r.blocked_items
    return ok, f"{sorted(found)[:6]} blocked={sorted(r.blocked_items)}"


WINDOW = tuple(i for i in sd.ITEMS if i in sd.CHARGE_WINDOW_ITEMS)
CCR_DQ1_CODES = {("CHARGE_WINDOW_CLOCK_UNKNOWN", i) for i in WINDOW} | {("TARIFF_EVENTS_NOT_FRESH", "export_event")}

print("== [0] CCR-DQ-1 has landed (I-D6 keys, no default limit): the clean fixture")
h.simulate_ccr_dq1(False)
strict_fx = {(f.code, f.subject) for f in h.blocks(q.assess_inputs(h.clean()))}
strict_houses = [{(f.code, f.subject) for f in h.blocks(q.assess_inputs(house(seed)))} for seed in SEEDS]
if h.CCR_DQ1_LANDED:
    check("CCR-DQ-1 has landed: the clean fixture raises no BLOCK", not strict_fx, str(sorted(strict_fx)[:4]))
else:  # historical: CCR-DQ-1 landed at integration, so this strict branch never runs on the integrated code
    check("the clean fixture BLOCKs only the CCR-DQ-1 codes (TOU window without a clock offset limit, events without a limit)",
          strict_fx == CCR_DQ1_CODES, str(sorted(strict_fx ^ CCR_DQ1_CODES)[:4]))
    check(f"... and so does every clean synthetic house ({len(SEEDS)} seeds)", all(s == CCR_DQ1_CODES for s in strict_houses),
          str([sorted(s ^ CCR_DQ1_CODES)[:3] for s in strict_houses if s != CCR_DQ1_CODES][:2]))
h.simulate_ccr_dq1(True)

print("== [1] detection on every seed (the CCR-DQ-1 readings under the synthetic I-D6's own limit)")
TABLE: dict[str, dict] = {}
for name, spec in faults.FAULTS.items():
    hits, misses = 0, []
    for seed in SEEDS:
        base = house(seed) if spec.kind == "history" else h.clean()
        inp = faults.inject(name, base, seed)
        ok, why = detected(spec, inp, seed)
        hits += ok
        if not ok:
            misses.append((seed, why[:160]))
    TABLE[name] = {"kind": spec.kind, "detector": spec.detector, "codes": sorted(spec.codes)[:3], "hits": hits,
                   "severity": "BLOCK" if spec.blocks or spec.codes & set(q.RULE_INPUTS) else "WARN"}
    check(f"{name}: detected by {'/'.join(sorted(spec.codes)[:2])} on {hits}/{len(SEEDS)} seeds", hits == len(SEEDS),
          str(misses[:2]))
dst_hits, dst_block = 0, 0
for seed in SEEDS:
    r = q.assess_inputs(cf.cycle_inputs(synthetic_recorded=True, now=faults.dst_now(seed)))
    dst_hits += "DST_NIGHT_IN_LOOKBACK" in h.codes(r, "WARN")
    dst_block += bool(h.blocks(r))
TABLE["dst_nights"] = {"kind": "cycle", "detector": "assess", "codes": ["DST_NIGHT_IN_LOOKBACK"], "hits": dst_hits,
                       "severity": "WARN"}
check(f"dst_nights: a clock change in the learning lookback is reported on {dst_hits}/{len(SEEDS)} seeds",
      dst_hits == len(SEEDS))
check("... and the clock-change cases raise no BLOCK of their own (I-D9 gating is the cycle's)", dst_block == 0,
      str(dst_block))

print("== [2] no false blocks on the clean bases, same seeds")
fixture_blocks = [(f.code, f.subject) for f in h.blocks(q.assess_inputs(h.clean()))]
check("the clean _cycle_fixtures input (synthetic decisions accepted): zero BLOCK findings", not fixture_blocks, str(fixture_blocks[:4]))
clean_counts = {"house_assess": 0, "house_prepare": 0, "counters_assess": 0, "counters_prepare": 0, "shifted": 0}
details = []
for seed in SEEDS:
    hs = house(seed)
    ra = q.assess_inputs(hs)
    hp, fp = q.prepare_history(hs.history, DEC, hs.now, accept_provenance=h.SYN)
    hc = replace(hs, history=faults.add_balanced_counters(hs.history))
    rc = q.assess_inputs(hc)
    hcp, fcp = q.prepare_history(hc.history, DEC, hc.now, accept_provenance=h.SYN)
    shifted = cf.cycle_inputs(synthetic_recorded=True, now=cf.NOW + timedelta(days=13 * seed, hours=-(seed % 5)))   # evenings: the fixture forecast is issued the same local day
    rs = q.assess_inputs(shifted)
    for key, bad in (("house_assess", h.blocks(ra)), ("house_prepare", [f for f in fp if f.severity == "BLOCK"] or ([1] if hp is None else [])),
                     ("counters_assess", h.blocks(rc)), ("counters_prepare", [f for f in fcp if f.severity == "BLOCK"] or ([1] if hcp is None else [])),
                     ("shifted", h.blocks(rs))):
        if bad:
            clean_counts[key] += 1
            details.append((seed, key, [getattr(f, "code", f) for f in bad][:3]))
for key, n in clean_counts.items():
    check(f"clean {key.replace('_', ' ')}: zero BLOCK findings on {len(SEEDS)} seeds", n == 0, str([d for d in details if d[1] == key][:3]))
warns = {}
for seed in SEEDS:
    for f in q.assess_inputs(house(seed)).findings:
        if f.severity == "WARN":
            warns[f.code] = warns.get(f.code, 0) + 1
check("clean houses: the only WARN is the TOU-table charge window", set(warns) <= {"CHARGE_WINDOW_FROM_TOU_TABLE"}, str(warns))

print("== [3] determinism and no mutation")
base = h.clean()
snap_before = base.snapshot.to_dict()
read_before = [(r.key, repr(r.value), r.observed_at) for r in base.site_readings]
hist_before = {s: (r.load_w_mean, r.pv_w_mean, r.soc_mean, dict(r.e)) for s, r in base.history.by_start.items()}
same = True
for name in faults.FAULTS:
    a = q.assess_inputs(faults.inject(name, base, 7))
    b = q.assess_inputs(faults.inject(name, base, 7))
    same = same and [x.to_dict() for x in a.findings] == [x.to_dict() for x in b.findings]
check("every injector gives identical findings for the same seed", same)
check("... and leaves its input unchanged (snapshot, readings, history)",
      base.snapshot.to_dict() == snap_before and [(r.key, repr(r.value), r.observed_at) for r in base.site_readings] == read_before
      and {s: (r.load_w_mean, r.pv_w_mean, r.soc_mean, dict(r.e)) for s, r in base.history.by_start.items()} == hist_before)
check("different seeds give different faults (the seeds are used)",
      len({repr(faults.inject("ct_reversal", base, s).snapshot.value("grid.power")) for s in SEEDS}) > 20)
try:
    faults.inject("no_such_fault", base, 0)
    check("an unknown fault name is refused", False)
except ValueError:
    check("an unknown fault name is refused", True)

print("")
print("detection and false-block table (seeds: %d)" % len(SEEDS))
print(f"  {'fault':32} {'kind':8} {'detector':8} {'severity':8} {'detected':9} codes")
for name, row in TABLE.items():
    print(f"  {name:32} {row['kind']:8} {row['detector']:8} {row['severity']:8} {row['hits']:>3}/{len(SEEDS):<5} {','.join(row['codes'])}")
print(f"  clean bases with a BLOCK: fixture {len(fixture_blocks)}, " + ", ".join(f"{k} {v}/{len(SEEDS)}" for k, v in clean_counts.items())
      + f", clock-change cases {dst_block}/{len(SEEDS)}")
print("")
if FAILURES:
    print(f"{len(FAILURES)} check(s) FAILED:")
    for f in FAILURES:
        print("  -", f)
    sys.exit(1)
print("all fault-injection checks passed")
