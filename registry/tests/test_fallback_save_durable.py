#!/usr/bin/env python3
"""FB-B2 - the SAVE durable power-cut / NVS-fault / anti-rollback matrix, run THROUGH THE REAL FIRMWARE YAML LAMBDAS.

The FB-B0 suites (test_fallback_durable_model.py / test_fallback_durable_host_compile.py, 575 scenarios) prove the transaction writer
at MODEL level. This suite proves that the real firmware - the SAVE gate, the dispatch, SAVE_FINAL parts 1+2, the INVALIDATE lambda,
the second housekeeping lambda and the FB-B1 boot load, transpiled lambda by lambda by the strict harness (registry/tests/_fbb_harness.py,
driven by _fbb2_drive.Driver) - plus the Python mirror of ecco_fallback_save.h and the FB-B0 model behave identically, end to end.

Every expectation comes from the locked documents (master architecture 3.9 / 4.3 / 4.5-4.8 / 5, S2 final 5.4 / 6.1-6.6, the header contract)
typed into _fbb2_durable_lib.py as tables, or from the FB-B0 model imported as a SEPARATE module object (an oracle that no mutant can
touch) over the raw stored bytes - never from what the YAML printed.

  [1] the oracles are independent of the code under test
  [2] power cuts - SAVE over every prior class (first capture; recapture over VALID / INVALIDATED / CORRUPT_DOMAIN; after loss, loss with a
      corrupt witness, first-save-unconfirmed; over every PROFILE_STALE kind; witness lagging / missing / corrupt; REPLACE CORRUPT over CORRUPT,
      WRONG_SIZE and CORRUPT without a witness): a cut before AND after EVERY direct-NVS event; the S2 6.1 stage model K0..K6 on each key; a cut
      after every Modbus read / delivery / NVS event on a deferred bus; cuts during the mirror / publish and after the release; a nested cut
      during the next boot. After each: the real on_boot, the class against the locked table AND the oracle, nothing held / latched / written,
      the generation and witness fields, and the operator action of the table (Review + Save gets the generation the table states)
  [3] NVS faults - every master 4.3 cell (14 write codes x 7 readback states x 2 health) on the witness key and on the profile key, master 5.5
      rows F1-F13 / F-H1 / F-H2, partition wipe, dedup erase, handle 0 at boot and at the commit, the representative faults over EVERY prior;
      texts (B1 / B2 werr, us / B9), the RAM mirror (PO5), seen_hw_gen, the write latch; every UNKNOWN: overlay + latch set, then repeated
      Review / SAVE / INVALIDATE / housekeeping / retry presses write nothing and never change the overlay; a plain reboot after EVERY outcome
      (COMMITTED, NOT_COMMITTED with and without the witness advanced, UNKNOWN: the ':plain' rows over every prior class), then the operator
      action; and no silent retry: exactly 2 NVS sets per committed SAVE, exactly 1 when the witness write fails
  [4] INVALIDATE - the 5.3 power-cut rows, faults, the UNKNOWN overlay, the W-INV golden
  [5] anti-rollback - witness fields exactly as the locked table + the W-FIRST / W-INV goldens, stale-profile resurrection, same-boot regression
      guard, seen_hw_gen floor (MB34), high-water / wrap boundaries, foreign witness, REPLACE CORRUPT phrase discipline; the generation
      formula (master 3.9) and the class permissions (master 4.6 / 4.8) typed from the documents over a 6 x 4 x 7^3 grid against the shared
      FB-B0 model, and the Python mirror's plan_save gate by gate
  [6] sequences - long scripted and seeded-random operation sequences: generations strictly increase, every refusal writes nothing
  [7] aggregate evidence - only FBW then FBP were ever written (never FBS, never a third key), zero Modbus writes
  [8] MUTANTS - a kill matrix: broken copies of the YAML text / the Python mirror / the FB-B0 model, each killed by named rows above

Pure Python, no I/O beyond reading repository files, no hardware. Runtime ~1.5 min with 4 worker processes (ECCO_DURABLE_WORKERS=1 runs it
in one process, ~6 min).
"""

from __future__ import annotations

import multiprocessing
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
import _fbb2_durable_ar as A  # noqa: E402,F401  (registers the INVALIDATE / anti-rollback / sequence rows)
import _fbb2_durable_fam as F  # noqa: E402
import _fbb2_durable_lib as L  # noqa: E402
import _fbb2_durable_mut as M  # noqa: E402

FAILURES: list[str] = []
NCHECKS = [0]


def check(name: str, condition: bool, detail: str = "") -> None:
    NCHECKS[0] += 1
    if condition:
        print(f"  PASS  {name}")
    else:
        FAILURES.append(name)
        print(f"  FAIL  {name}" + (f" - {detail}" if detail else ""))


# How many rows each family must contain at least (the matrix may grow, never silently shrink).
MIN_ROWS = {"cuts-nvs": 600, "cuts-k": 150, "cuts-timeline": 130, "cuts-boot": 30, "faults-grid-W": 205, "faults-grid-P": 200,
            "faults-doc": 40, "faults-prior": 190, "invalidate": 35, "antirollback": 60, "sequences": 30}
SHARDS = {"cuts-nvs": 5, "cuts-k": 2, "cuts-timeline": 2, "cuts-boot": 1, "faults-grid-W": 3, "faults-grid-P": 3, "faults-doc": 1,
          "faults-prior": 2, "invalidate": 1, "antirollback": 1, "sequences": 2}
FAMILY_TITLE = {
    "cuts-nvs": "power cut before AND after every direct-NVS event of SAVE over every prior class",
    "cuts-k": "S2 6.1 per-key stage model K0..K6 on FBW and FBP over every prior class",
    "cuts-timeline": "power cut after every Modbus read / delivery / NVS / switch event (deferred bus), during mirror / publish and after the release",
    "cuts-boot": "nested power cut during the next boot's load",
    "faults-grid-W": "master 4.3 cells on the WITNESS key (14 codes x 7 readbacks x 2 health, + first-capture ABSENT cells)",
    "faults-grid-P": "master 4.3 cells on the PROFILE key",
    "faults-doc": "master 5.5 rows F1-F13, F-H1, F-H2, wipe, dedup erase, handle 0",
    "faults-prior": "the representative faults over EVERY prior class",
    "invalidate": "INVALIDATE: power cuts, faults, UNKNOWN overlay, W-INV golden",
    "antirollback": "anti-rollback / generation / witness / regression-guard / wrap rows",
    "sequences": "long operation sequences: generations strictly increase",
}


def workers() -> int:
    try:
        n = int(os.environ.get("ECCO_DURABLE_WORKERS", "4"))
    except ValueError:
        n = 4
    return max(1, min(6, n))


def run_tasks(tasks: list, n_workers: int) -> dict:
    """tasks: [(key, fn, args)] -> {key: result}. Process pool (spawn), or in-process when n_workers == 1 / the pool cannot start."""
    out: dict = {}
    if n_workers > 1:
        try:
            ctx = multiprocessing.get_context("spawn")
            with ProcessPoolExecutor(max_workers=n_workers, mp_context=ctx) as ex:
                futs = [(key, ex.submit(fn, *args)) for key, fn, args in tasks]
                for key, fut in futs:
                    out[key] = fut.result()
            return out
        except (OSError, RuntimeError, ImportError) as e:   # no process pool on this host: run in-process, still complete
            print(f"  (process pool unavailable: {e}; running in one process)")
            out.clear()
    for key, fn, args in tasks:
        out[key] = fn(*args)
    return out


def main() -> int:
    t0 = time.time()
    nw = workers()

    print("[1] the oracles are independent of the code under test")
    check("the FB-B0 oracle is a separate module object (an exec of registry/fallback_durable.py) from the one the harness executes",
          L.fdo is not L.fd and L.fdo.__name__ != L.fd.__name__ and L.fdo.commit_transition.__code__ is not L.fd.commit_transition.__code__)
    check("the oracle and the shared model agree on the constants the harness compares (keys, sizes, enums)",
          (L.fdo.FALLBACK_PROFILE_KEY, L.fdo.FAILBACK_PROVISION_KEY, L.fdo.PROVISION_SIZE, L.fdo.TXN_COMMITTED, L.fdo.KEY_COMMITTED)
          == (L.fd.FALLBACK_PROFILE_KEY, L.fd.FAILBACK_PROVISION_KEY, L.fd.PROVISION_SIZE, L.fd.TXN_COMMITTED, L.fd.KEY_COMMITTED))
    check("the durable keys are exactly FBP 0x5FEE6196 and FBW 0x3BA3DF61 (and FBS 0x808485C3 is never a write target)",
          (L.K_P, L.K_W, L.K_S) == (0x5FEE6196, 0x3BA3DF61, 0x808485C3))
    check("the doc tables cover the 14 write codes x 7 readback states of master 4.3 / FB-B0 and the 18 prior classes of the locked tables",
          len(F.CODES) == 14 and len(F.VISIBLES) == 7 and len(L.PRIORS) >= 19
          and {p.name for p in L.PRIORS.values() if p.rc} == {"corrupt", "wsize", "corrupt_nw"},
          f"{len(F.CODES)} codes, {len(F.VISIBLES)} states, {len(L.PRIORS)} priors")
    check("every master 4.3 pre-write code is in the document table (INVALID_HANDLE, READ_ONLY, NOT_INITIALIZED) and ESP_OK is not",
          set(L.PRE_WRITE) == {0x1107, 0x1104, 0x1101} and L.fdo.IDF_OK not in L.PRE_WRITE)

    tasks = []
    for fam, n in SHARDS.items():
        for k in range(n):
            tasks.append(((fam, k), F.run_family, (fam, k, n)))
    mut_ids = [m.mid for m in M.MUTANTS]
    groups = [mut_ids[i::4] for i in range(4)]
    for i, g in enumerate(groups):
        tasks.append((("mutants", i), M.run_mutants, (g,)))
    for i in range(len(M.EQUIVALENT)):
        tasks.append((("equiv", i), M.run_equivalent, (i,)))
    # largest first: the pool then balances itself
    tasks.sort(key=lambda t: {"cuts-nvs": 0, "mutants": 9, "equiv": 8}.get(t[0][0], 5))
    print(f"running {len(tasks)} work items on {nw} worker process(es) ...")
    res = run_tasks(tasks, nw)
    print(f"all work items done after {time.time() - t0:.0f} s")

    acc = {}
    for (fam, _k), r in res.items():
        if fam in ("mutants", "equiv"):
            continue
        a = acc.setdefault(fam, F.Acc(fam))
        a.merge(r)
    keys_seen: set = set()
    for (fam, _k), r in res.items():
        if fam not in ("mutants", "equiv"):
            keys_seen.update(r.extra.get("keys", []))

    sections = [("[2] power cuts through the real YAML lambdas", ("cuts-nvs", "cuts-k", "cuts-timeline", "cuts-boot")),
                ("[3] NVS faults through the real YAML lambdas", ("faults-grid-W", "faults-grid-P", "faults-doc", "faults-prior")),
                ("[4] INVALIDATE", ("invalidate",)), ("[5] anti-rollback / generation / witness", ("antirollback",)),
                ("[6] sequences", ("sequences",))]
    totals = {"rows": 0, "asserts": 0}
    fam_rows = {}
    for title, fams in sections:
        print(title)
        for fam in fams:
            a = acc[fam]
            fam_rows[fam] = a.rows
            totals["rows"] += a.rows
            totals["asserts"] += a.asserts
            check(f"[{fam}] {a.rows} rows / {a.asserts} assertions: {FAMILY_TITLE[fam]}", not a.fails and a.rows >= MIN_ROWS[fam],
                  f"{len(a.fails)} failing assertion(s) in {a.rows} rows (min {MIN_ROWS[fam]}); first: " + " | ".join(m[:300] for m in a.fails[:3]))
            for m in a.fails[:6]:
                print("        " + m[:400])

    print("[7] aggregate evidence over every row")
    names = {L.K_P: "FBP", L.K_W: "FBW"}
    check("only FBW and FBP were ever written by any row (no FBS write, no third durable key): "
          f"{sorted(names.get(k, hex(k)) for k in keys_seen)}", keys_seen <= {L.K_P, L.K_W} and keys_seen == {L.K_P, L.K_W})
    row_total = totals["rows"]
    check(f"{row_total} rows and {totals['asserts']} assertions evaluated (power cuts {sum(fam_rows[f] for f in ('cuts-nvs', 'cuts-k', 'cuts-timeline', 'cuts-boot'))}, "
          f"faults {sum(fam_rows[f] for f in ('faults-grid-W', 'faults-grid-P', 'faults-doc', 'faults-prior'))}, "
          f"anti-rollback {fam_rows['invalidate'] + fam_rows['antirollback'] + fam_rows['sequences']})", row_total >= 1600 and totals["asserts"] >= 60000)

    print("[8] mutants: broken copies of the YAML / the Python mirror / the FB-B0 model, each killed by named rows of the matrix")
    mres = {}
    for (fam, _i), r in res.items():
        if fam == "mutants":
            for x in r:
                mres[x["mid"]] = x
    base_rows = sorted({n for m in M.MUTANTS for n in m.rows})
    bad_base = []
    for n in base_rows:
        f = F.run_row(n)
        if f:
            bad_base.append((n, f[0][:200]))
    check(f"every row named by the kill matrix ({len(base_rows)} rows) is green on the REAL firmware first", not bad_base, str(bad_base[:3]))
    killed = [m for m in M.MUTANTS if mres.get(m.mid, {}).get("killed")]
    for m in M.MUTANTS:
        r = mres.get(m.mid)
        ok = bool(r and r["killed"])
        why = "; ".join(f"{n}: {st} {msg[:90]}" for n, (st, msg) in (r or {"per_row": {}})["per_row"].items()) if r else "no result"
        check(f"mutant {m.mid} killed - {m.desc}", ok, why)
    check(f">= 40 mutants and every one killed: {len(killed)} / {len(M.MUTANTS)} (YAML {sum(m.mid[0] == 'Y' for m in M.MUTANTS)}, "
          f"Python mirror {sum(m.mid[0] == 'S' for m in M.MUTANTS)}, FB-B0 model {sum(m.mid[0] == 'P' for m in M.MUTANTS)})",
          len(M.MUTANTS) >= 40 and len(killed) == len(M.MUTANTS))

    print("  redundant (defence-in-depth) layers: mutants no representative row can tell from the original - informational, never a failure:")
    n_equiv = 0
    for (fam, i), r in sorted(res.items(), key=lambda kv: str(kv[0])):
        if fam != "equiv":
            continue
        n_equiv += not r["killers"]
        print(f"    INFO  {r['name']}: {'survives all ' + str(len(M.EQ_ROWS)) + ' rows' if not r['killers'] else 'KILLED by ' + ', '.join(r['killers'][:3])} ({r['desc']})")
    print("")
    print(f"{NCHECKS[0]} checks; {totals['rows']} rows ({totals['asserts']} assertions); mutants {len(killed)}/{len(M.MUTANTS)}; "
          f"{n_equiv} redundant-layer mutants survive (informational); {time.time() - t0:.0f} s on {nw} worker(s)")
    if FAILURES:
        print(f"FAILED: {len(FAILURES)} check(s)")
        for f in FAILURES:
            print(f"  - {f}")
        return 1
    print("All FB-B2 durable (SAVE) matrix checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
