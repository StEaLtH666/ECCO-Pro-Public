#!/usr/bin/env python3
"""Run every named scenario of the dynamic-energy-control test bench and print one table row each.

REFERENCE MODEL AND TEST BENCH. NOT PRODUCTION CODE. Not wired to Home Assistant, the dongle, the inverter or any register; it reads
no file, contacts nothing and writes nothing but its own table on standard output. Exit status 0 only when every scenario passes
(every applicable invariant holds, every documented gap and every PINNED FINDING fails exactly as pinned, every expectation holds, and the set
of failing (scenario, invariant) pairs equals the pinned set exactly, so a fix flips its pin red and a new failure fails too); 1 otherwise.
A pinned finding is a defect of the design the bench found (scenarios.py, known_finding): it is printed as FINDING with its id and reason.

    python -I -B -X utf8 docs/dev/dynamic-energy-control/sim/run_sim.py            # the table
    python -I -B -X utf8 docs/dev/dynamic-energy-control/sim/run_sim.py -v         # plus invariants, expectations and explanations
    python -I -B -X utf8 docs/dev/dynamic-energy-control/sim/run_sim.py g03_heavy_load_import_ceiling -v     # one scenario
    python -I -B -X utf8 docs/dev/dynamic-energy-control/sim/run_sim.py --covers   # the scenario / requirement table of SIM_README.md
    python -I -B -X utf8 docs/dev/dynamic-energy-control/sim/run_sim.py --params   # the MEASURED versus ASSUMED table of SIM_README.md
    python -I -B -X utf8 docs/dev/dynamic-energy-control/sim/run_sim.py --counts   # the catalogue's size, as SIM_README.md states it
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import kernel as K          # noqa: E402
import scenarios as S       # noqa: E402


def short_inv(res):
    applicable = [(n, v) for n, v in res.inv.items() if v[0] is not None]
    held = sum(1 for _n, v in applicable if v[0])
    bad = [n for n, v in applicable if not v[0]]
    return "%d/%d" % (held, len(applicable)) + ("" if not bad else " FAIL " + ",".join(bad))


def short_codes(res, limit=5):
    names = list(res.codes)
    return ", ".join(names[:limit]) + (" +%d" % (len(names) - limit) if len(names) > limit else "")


def main(argv):
    if "--covers" in argv:
        print(S.coverage_table_md())
        return 0
    if "--counts" in argv:
        print(S.catalogue_counts_md())
        return 0
    if "--params" in argv:
        import plant
        print(plant.parameter_table_md())
        return 0
    verbose = "-v" in argv
    names = [a for a in argv if not a.startswith("-")]
    specs = [S.SPEC_BY_NAME[n] for n in names] if names else S.SPECS
    results = []
    for spec in specs:
        run, res = S.run_spec(spec, K)
        results.append((spec, run, res))
    w = max(len(r.name) for _s, _r, r in results)
    print("%-*s  %-34s  %-22s  %6s  %8s  %s" % (w, "scenario", "outcome", "invariants", "writes", "final SOC", "reason codes (reason/detail)"))
    for spec, run, res in results:
        pinned = bool(spec.known_finding)
        flag = "FAIL" if not res.ok else ("FINDING" if pinned else "ok  ")
        print("%-*s  %-34s  %-22s  %6d  %8.1f  %s" % (w, res.name, res.outcome[:34], short_inv(res), res.writes, res.final_soc, short_codes(res)), flag)
        for (inv, fid, why) in spec.known_finding:
            print("    FINDING %s on %s: %s" % (fid, inv, why))
        if res.backstop and not (verbose or not res.ok) and not pinned:
            print("    backstop that applies: " + res.backstop)
        if verbose or not res.ok:
            print("    " + spec.sc.summary)
            for n, (ok, detail) in res.inv.items():
                print("    %-24s %-4s %s" % (n, "-" if ok is None else ("ok" if ok else "FAIL"), detail))
            for n, (ok, detail) in res.expect.items():
                print("    expect %-60s %-4s %s" % (n[:60], "ok" if ok else "FAIL", detail))
            for f in res.failures:
                print("    >>> " + f)
            if res.backstop and not pinned:
                print("    backstop that applies: " + res.backstop)
        if verbose:
            for r in run.recs[:6]:
                print("    [%6d s %s %s] %s/%s: %s" % (r.t, r.who, r.policy, r.reason, r.detail, r.explanation))
    bad = [r.name for _s, _r, r in results if not r.ok]
    found = [r.name for s_, _r, r in results if s_.known_finding]
    pinned_set = S.pinned_pairs([s_ for s_, _r, _x in results])
    failing_set = S.failing_pairs([r for _s, _r, r in results])
    print("")
    print("%d scenarios, %d passed (%d of them pin a finding), %d failed" % (len(results), len(results) - len(bad), len(found), len(bad)))
    exact = failing_set == pinned_set
    print("failing (scenario, invariant) pairs: %d; pinned (documented gaps and findings): %d; %s" % (
        len(failing_set), len(pinned_set), "equal" if exact else "DIFFERENT"))
    if not exact:
        for pair in sorted(failing_set - pinned_set):
            print("  NEW failure, not pinned: %s %s" % pair)
        for pair in sorted(pinned_set - failing_set):
            print("  pinned but HOLDS (fixed? remove the pin): %s %s" % pair)
    if bad:
        print("FAILED: " + ", ".join(bad))
    if bad or not exact:
        return 1
    if found:
        print("FINDINGS: %s (defects of the design the bench found, pinned; see SIM_README.md)" % ", ".join(found))
    print("All scenarios passed. This proves the kernel against this model, not the inverter.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
