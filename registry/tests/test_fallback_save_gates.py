#!/usr/bin/env python3
"""FB-B2 - the SAVE gates, refusals and races, through the REAL firmware YAML (t-gates).

The operator flow of the durable Fallback Profile SAVE (Review -> arm -> `fallback_profile_execute`) is driven the way an operator, Home
Assistant and the inverter would drive it, on the strict FbbSim harness that transpiles the real firmware lambdas
(registry/tests/_fbb2_drive.Driver). Nothing here is a model of the firmware: the gate script, the api action, the arm switch, the
dispatch, the SAVE final lambdas and the housekeeping tick run as written in firmware/ecco_clock_dongle_stage3_4_free_power.yaml, over the
FB-B0 direct-NVS fault model and a Modbus hub model. Expectations are NOT copied from the implementation: the expected FBP / FBW bytes
come from the FB-A / FB-B0 mirrors over the named golden fields (and the locked golden vectors as literals), the operator texts are the
locked literals of the design (FB_B2_IMPLEMENTATION_NOTES.md section 3, S1 4.5 / 8.5, master 4.7), the next-boot class is judged by the FB-B0 model
oracle, and the gate ORDER is the S1 8.5 list.

  [0] inventory         every scenario registered, every mutant names registered scenarios, counts
  [1] SAVE SUCCESS      exact FBW-then-FBP bytes, texts, reads, locks, reboot; recapture over every prior class; SAVING on a deferred bus
  [2] REFUSALS          G0 tokens, G2 arm (+ lifetime), G3 candidate, G4 expiry (119999 / 120000, wrap), G5 / G6 id, G7 phrase, G8 / G9 / G9a,
                        G10 heartbeat, G11 clock, G12 write arms, G13 writes fingerprint, G14 bus (+ 300 s stuck lock), G15 failback
                        record, G16 leases / boot-load status / probe latch / running scripts; the in-flight (G1) refusals; the dispatch
                        (7 s idle wait, 3 s pre-commit drain, a failing read on each of the four reads); the lazy lease-marker probes of
                        the final lambda; storage health; after a real UNKNOWN outcome; first-failure-wins over all 190 PAIRS of gates
  [3] RACES / CHANGES   each of the 31 words changing between Review and SAVE, differing between the passes, changing at every instant
                        of a deferred SAVE; the candidate / call arguments clobbered mid-dispatch; a temporary operation, a write arm, an
                        FBS record, the clock, appearing before the commit; the stored profile changed behind the SAVE; the heartbeat
                        snapshot PIN; the housekeeping ticks and the leak breaker during a long SAVE;
                        FB-B2 final review: requirement 9 (the capture checks re-run on the fresh words, forged candidates, then the
                        built-record validation), a Free Power / Dump START and a Manual TOU apply colliding with the SAVE's mutex
                        (T-CAP-17, SAVE side), every obligation input of the final re-check on its own row
  [4] ONE-SHOT / ARM    every call past the in-flight check turns the arm off and consumes the candidate; a Review press turns the arm
                        off; the arm cannot be turned on by firmware (grep + a long mixed run); the candidate is copied before IE2;
                        the stored profile never updates itself (24 h of housekeeping + FB-C1 + supervision ticks over heartbeat / NTP /
                        arm / Review traffic: zero NVS operations, unchanged FBP / FBW bytes and mirror, zero Modbus writes)
  [5] SAFETY            over EVERY simulator of the live run: no Modbus write ever, no direct NVS set to any key but FBW / FBP, FBS never
  [6] MUTANTS           broken copies of the firmware YAML text and of the Python mirrors, each KILLED by named scenarios

No I/O beyond reading repository files; pure Python (no compiler), ~5 minutes (the 24 h idle run and the mutant stage dominate).
"""

from __future__ import annotations

import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "registry"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _fbb1_engine as E  # noqa: E402
import _fbb2_gates_lib as L  # noqa: E402
import _fbb_harness as H  # noqa: E402
import _fbb2_gates_mutants as M  # noqa: E402
import _fbb2_gates_races  # noqa: E402,F401
import _fbb2_gates_refusals  # noqa: E402,F401
import _fbb2_gates_refusals2  # noqa: E402,F401
import _fbb2_gates_static  # noqa: E402,F401
import _fbb2_gates_success  # noqa: E402,F401

FAILURES: list[str] = []
NCHECKS = [0]


def check(name: str, condition: bool, detail: str = "") -> None:
    NCHECKS[0] += 1
    if condition:
        print(f"  PASS  {name}")
    else:
        FAILURES.append(name)
        print(f"  FAIL  {name}" + (f" - {detail}" if detail else ""))


SECTIONS = [
    ("[1] SAVE SUCCESS", ("ss_",)),
    ("[2] REFUSALS", ("rf_",)),
    ("[3] RACES / CHANGES", ("rc_",)),
    ("[4] ONE-SHOT / ARM, static pins", ("os_", "st_")),
]


def main() -> int:
    t_start = time.time()

    # =======================================================================
    print("[0] inventory")
    # =======================================================================
    names = list(L.SCENARIOS)
    check(f"{len(names)} scenarios registered, every name unique and prefixed ss_ / rf_ / rc_ / os_ / st_",
          len(names) == len(set(names)) and all(n.split("_")[0] in ("ss", "rf", "rc", "os", "st") for n in names))
    mids = [m.mid for m in M.MUTANTS]
    check(f"{len(mids)} mutants, ids unique, at least 40", len(mids) == len(set(mids)) and len(mids) >= 40)
    check("every mutant names registered scenarios as its killers", all(k in L.SCENARIOS for m in M.MUTANTS for k in m.killers),
          str([k for m in M.MUTANTS for k in m.killers if k not in L.SCENARIOS]))
    covered = {k for m in M.MUTANTS for k in m.killers}
    kinds = Counter("combo" if sum(bool(x) for x in (m.yaml, m.save, m.capture)) > 1 else
                    "yaml" if m.yaml else "save-mirror" if m.save else "capture-mirror" for m in M.MUTANTS)
    print(f"    mutant kinds: {dict(kinds)}; scenarios used as killers: {len(covered)} of {len(names)}")

    # the safety evidence of the whole live run (counted at the lowest level, over every simulator any scenario builds)
    safety = {"modbus_writes": 0, "sets": Counter(), "drivers": 0}
    orig_set, orig_write = H.DirectNvs.set_blob, E.EngineMixin._modbus_write
    orig_init = L.D.Driver.__init__

    def set_blob(self, key, data):
        safety["sets"][int(key)] += 1
        return orig_set(self, key, data)

    def modbus_write(self, body, local):
        # FB-B2 (gates-extra): a simulator in which a REAL Free Power / Dump / Manual TOU writer is started on purpose (the T-CAP-17 positive
        # controls: rc_collision_writers_during_save) marks itself safety_exempt - that writer writes the inverter by design, the SAVE never does
        if not getattr(self, "safety_exempt", False):
            safety["modbus_writes"] += 1
        return orig_write(self, body, local)

    def driver_init(self, *a, **k):
        safety["drivers"] += 1
        return orig_init(self, *a, **k)
    H.DirectNvs.set_blob, E.EngineMixin._modbus_write, L.D.Driver.__init__ = set_blob, modbus_write, driver_init

    live_ok: dict = {}
    totals = {"scenarios": 0, "rows": 0, "assertions": 0}
    try:
        for title, prefixes in SECTIONS:
            # =======================================================================
            print(title)
            # =======================================================================
            for name in [n for n in names if n.startswith(prefixes)]:
                t0 = time.time()
                ex = L.run_scenario(name, L.LIVE)
                totals["scenarios"] += 1
                totals["rows"] += ex.n_rows
                totals["assertions"] += ex.n
                bad = dict(ex.failed)
                print(f"  -- {name}: {L.SCENARIO_DOC[name]}  [{ex.n_rows} rows, {ex.n} assertions, {time.time() - t0:.1f} s]")
                for label, fails in [(r[0], r[1]) for r in ex.rows]:
                    check(f"{name}: {label}", not fails, "; ".join(fails[:3]))
                for err in ex.errors:
                    check(f"{name}: runs to completion on the live firmware", False, err)
                live_ok[name] = not ex.failed and not ex.errors
        # =======================================================================
        print("[5] SAFETY over every simulator of the live run")
        # =======================================================================
    finally:
        H.DirectNvs.set_blob, E.EngineMixin._modbus_write, L.D.Driver.__init__ = orig_set, orig_write, orig_init
    fb_keys = {L.K_P: "FBP", L.K_W: "FBW"}
    check(f"{safety['drivers']} simulators built: ZERO Modbus writes in any of them (bar the deliberate real-writer control simulators)",
          safety["modbus_writes"] == 0, str(safety["modbus_writes"]))
    foreign = {k: n for k, n in safety["sets"].items() if k not in fb_keys}
    check("every direct NVS set of the whole live run went to FBW or FBP (no third durable key)", not foreign, str(foreign))
    check("the failback-state key (FBS) was never written", safety["sets"].get(L.K_S, 0) == 0)
    n_w, n_p = safety["sets"].get(L.K_W, 0), safety["sets"].get(L.K_P, 0)
    check(f"witness-first accounting: {n_w} FBW sets, {n_p} FBP sets (every FBP set was preceded by its FBW set, so FBW >= FBP)", n_w >= n_p > 0)

    # =======================================================================
    print("[6] MUTANTS")
    # =======================================================================
    n_killed = 0
    survivors = []
    for m in M.MUTANTS:
        t0 = time.time()
        controls = all(live_ok.get(k, False) for k in m.killers)
        try:
            mk = m.build()
        except Exception as e:  # noqa: BLE001 - a mutant that cannot be built is a failure of this suite, never a silent skip
            check(f"mutant {m.mid} builds: {m.desc}", False, f"{type(e).__name__}: {e}")
            # FB-B2 (final review WD-3): a mutant that does not build is NOT killed - it counts against the aggregate line below
            survivors.append(f"{m.mid} (does not build)")
            continue
        results = []
        for k in m.killers:
            ex = L.run_scenario(k, mk)
            results.append((k, "killed" if ex.failed else ("ERROR" if ex.errors else "SURVIVED"), ex))
        killed = controls and all(r[1] == "killed" for r in results)
        n_killed += killed
        if not killed:
            survivors.append(m.mid)
        detail = "; ".join(f"{k}: {st}" + (f" ({ex.errors[0][:80]})" if st == "ERROR" else "") for k, st, ex in results)
        if not controls:
            detail = "a killer scenario fails on the REAL firmware (no valid control); " + detail
        first = ""
        for k, st, ex in results:
            if st == "killed":
                lab, msgs = ex.failed[0]
                first = f" [{k} row '{lab[:40]}': {msgs[0][:90]}]"
                break
        check(f"mutant {m.mid} KILLED - {m.desc} (by {', '.join(m.killers)})", killed, detail)
        print(f"          {time.time() - t0:.1f} s{first}")
    check(f"{len(M.MUTANTS)} mutants (yaml / mirror / combo), every one killed by every scenario named for it",
          n_killed == len(M.MUTANTS) and not survivors, f"{n_killed} killed of {len(M.MUTANTS)}; not killed: {survivors}")

    print("")
    print(f"scenarios: {totals['scenarios']}   sweep/rows: {totals['rows']}   assertions: {totals['assertions']}   simulators: {safety['drivers']}")
    print(f"mutants: {len(M.MUTANTS)} total, {n_killed} killed")
    print(f"{NCHECKS[0]} checks in {time.time() - t_start:.0f} s")
    if FAILURES:
        print(f"FAILED: {len(FAILURES)} check(s)")
        for f in FAILURES[:40]:
            print(f"  - {f}")
        return 1
    print("All FB-B2 SAVE gate / refusal / race checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
