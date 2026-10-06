#!/usr/bin/env python3
"""FB-B2 - INVALIDATE (and the REPLACE CORRUPT edges that interact with it) of the durable Fallback Profile, through the REAL firmware YAML.

Everything here executes the repository's firmware YAML (api action fallback_profile_execute, script fallback_profile_invalidate, the arm
switch, the boot lambda, the housekeeping tick) through the strict simulator registry/tests/_fbb_harness.FbbSim, driven by the scenario
driver registry/tests/_fbb2_drive.Driver. Expectations come from the locked design (master 4.8 / 5, S2B 4.2-4.4, the FB-B2 brief) or from
the independent FB-B0 model (see registry/tests/_fbb2_invalidate_kit.py): the intended FBP / FBW pair is built from the FB-A mirror and
make_provision, the writer's verdict is the FB-B0 model replayed over a copy of the same flash image with the same injected faults, the
next-boot class is fd.compose_profile_class over the resolved flash. Nothing is copied from the output of the firmware under test.

  [0] inventory: the script / api action / arm switch exist, the INVALIDATE script is ONE lambda, the golden W-INV witness
  [1] static pins of the INVALIDATE script (no wait / delay / script.execute / Modbus, no mutex or op flag, one commit call, order)
  [2] CLEAN INVALIDATE: VALID with a consistent / lagging / missing / corrupt witness: exact FBP + FBW bytes, texts, mirror, reboot, re-Save
      g+2; legal under every condition the design says is irrelevant (no supervision / NTP, write arms on, leases, candidate, FBS clear)
  [3] REFUSALS: arm, id format, wrong id, phrase, boot not loaded, read anomaly, SAVE_UNCONFIRMED, every class, generation exhausted,
      seen_hw_gen floor, bus busy (9 flags + tx buffer + tx blocked + stuck lock), FBS, gate ORDER, candidate consumption (every row again
      with a REVIEW candidate pending), fresh-read stage
  [4] one-shot arm, arm TTL, candidate expiry, wrong tokens, in-flight (SAVE / REVIEW / injected), busy then retry, races after the gate
  [5] writer-stage refusals (handle gone / unhealthy at commit) and the PLAN layer on its own (the storage / RAM changes between the
      gate and the plan: binding changed, generation floor raised, overlay raised): nothing written, no latch
  [6] POWER CUT before and after EVERY direct-NVS event of an INVALIDATE (4 witness situations), then the real on_boot
  [7] NVS WRITE FAULTS: the locked outcome table (F1..F8, F-H2) and the full key x raw result x readback x health matrix (+ boot resolution;
      again over the B14 / B15 witness situations) against the independent model, each followed by the UNKNOWN / NOT_COMMITTED
      aftermath and a reboot
  [8] sequences: invalidate -> save -> invalidate (strictly increasing generations), REPLACE CORRUPT -> INVALIDATE, boundary generations
  [9] MUTANTS: broken copies of the firmware text (and of the Python mirror / the FB-B0 writer the lambda calls), each killed by named scenarios;
      every bus flag is mutated in BOTH bus checks (the gate and the last statement before the writer), every layer (gate over the RAM mirror,
      plan over the fresh read) is mutated on its own

Pure Python, no I/O besides reading repository files, no hardware.
"""

from __future__ import annotations

import hashlib
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "registry"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _fbb2_drive as D  # noqa: E402
import _fbb2_invalidate_kit as K  # noqa: E402
import _fbb2_invalidate_mut as M  # noqa: E402
import _fbb2_invalidate_scn as S  # noqa: E402
import fallback_durable as fd  # noqa: E402

FAILURES: list[str] = []
NCHECKS = [0]
STATS = {"scenarios": 0, "assertions": 0, "rows": {}}
T0 = time.time()


def check(name: str, condition: bool, detail: str = "") -> None:
    NCHECKS[0] += 1
    if condition:
        print(f"  PASS  {name}")
    else:
        FAILURES.append(name)
        print(f"  FAIL  {name}" + (f" - {detail}" if detail else ""))


def live(**kw):
    return D.Driver(**kw)


def run(name: str, fn, *args, **kw):
    """One scenario on the live firmware -> one check."""
    STATS["scenarios"] += 1
    try:
        e = fn(live, *args, **kw)
    except Exception as ex:  # noqa: BLE001 - reported as a failure of the check, never swallowed
        check(name, False, f"exception {type(ex).__name__}: {str(ex)[:160]}")
        return None
    STATS["assertions"] += getattr(e, "n", 0)
    check(name, not e, "; ".join(str(x)[:140] for x in e[:3]) + (f" (+{len(e) - 3} more)" if len(e) > 3 else ""))
    return e


class Batch:
    """Many rows of one family -> ONE check naming the failing rows."""

    def __init__(self, name: str, family: str):
        self.name, self.family = name, family
        self.bad: list = []
        self.n = 0

    def row(self, label: str, fn, *args, **kw):
        self.n += 1
        STATS["scenarios"] += 1
        try:
            e = fn(live, *args, **kw)
        except Exception as ex:  # noqa: BLE001
            self.bad.append(f"[{label}] exception {type(ex).__name__}: {str(ex)[:100]}")
            return None
        STATS["assertions"] += getattr(e, "n", 0)
        for m in e:
            self.bad.append(f"[{label}] {str(m)[:140]}")
        return e

    def done(self, minimum: int):
        STATS["rows"][self.family] = STATS["rows"].get(self.family, 0) + self.n
        check(f"{self.name}: {self.n} rows (>= {minimum})", self.n >= minimum and not self.bad,
              "; ".join(self.bad[:3]) + (f" (+{len(self.bad) - 3} more)" if len(self.bad) > 3 else ""))


LIVE_TEXT = M.LIVE_TEXT

# ---------------------------------------------------------------------------
print("[0] inventory")
fw = D.load_fw()
scripts = {s["id"]: s for s in fw["script"]}
inv = scripts.get("fallback_profile_invalidate")
check("script fallback_profile_invalidate exists, mode single", inv is not None and inv.get("mode") == "single")
check("the INVALIDATE script is ONE lambda (no dispatch, no wait, no second action)",
      inv is not None and len(inv["then"]) == 1 and list(inv["then"][0]) == ["lambda"])
acts = fw["api"]["actions"]
check("api actions: free_power_recovery_execute first, then ha_supervision_heartbeat, then fallback_profile_execute",
      [a["action"] for a in acts] == ["free_power_recovery_execute", "ha_supervision_heartbeat", "fallback_profile_execute"])
fpe = acts[2]
check("fallback_profile_execute(action, target_id, confirmation) are three strings",
      fpe["variables"] == {"action": "string", "target_id": "string", "confirmation": "string"})
arm = next((s for s in fw["switch"] if s.get("id") == "fallback_profile_arm"), None)
check("arm switch fallback_profile_arm: template, optimistic, ALWAYS_OFF",
      arm is not None and arm.get("platform") == "template" and arm.get("optimistic") is True and arm.get("restore_mode") == "ALWAYS_OFF")
d0 = D.Driver()
check("driver boots the live firmware VALID g7 with the golden profile id", d0.b1 == "VALID" and d0.b2_id() == S.GOLD_ID, d0.b2)
check("golden W-INV: the independent oracle's witness for the golden profile has binding 0x9E8AEC8F7D7DF2D7 and the locked fields",
      K.intended_pair(D.GOLD)[1]["binding"] == S.GOLD_W_INV_BINDING and K.intended_pair(D.GOLD)[1]["hw_generation"] == 8
      and K.intended_pair(D.GOLD)[1]["prior_generation"] == 7 and K.intended_pair(D.GOLD)[1]["last_op"] == 2)
check("oracle sanity: the intended invalidated profile id is F49A36C9C9720301",
      f"{K.intended_pair(D.GOLD)[0]['binding']:016X}" == S.GOLD_INVALIDATED_ID == "F49A36C9C9720301")

# ---------------------------------------------------------------------------
print("[1] static pins of the INVALIDATE script (the real text)")
STATS["scenarios"] += 1
st_e = S.static_inv(LIVE_TEXT)
STATS["assertions"] += st_e.n
check(f"S-INV: {st_e.n} static pins hold on the real INVALIDATE script (one lambda, no wait/delay/execute/Modbus/supervision/ntp/mutex/op flag, "
      "one commit_transition_t, the bus check last, no retry, guarded plan only)", not st_e, "; ".join(st_e[:3]))
check("S-INV: the pin runner finds >= 40 pins", st_e.n >= 40, str(st_e.n))

# ---------------------------------------------------------------------------
print("[2] CLEAN INVALIDATE")
for label, seed in S.SEEDS_CLEAN.items():
    run(f"clean INVALIDATE of {label}: exact bytes, texts, mirror, reboot, re-Save g+2", S.scn_clean, seed, tail_save=True)
for label, kw in S.CLEAN_CONDITIONS.items():
    run(f"clean INVALIDATE is legal: {label}", S.scn_clean, "valid", **kw)
run("clean INVALIDATE, Review straight after (no reboot): the retained B2 werr / us are republished, then Save g+2", S.scn_clean, "valid", tail_save=True, reboot=False)
run("clean INVALIDATE on a deferred Modbus bus: no frame, no wait", S.scn_clean_deferred_bus)
run("clean INVALIDATE with an api StringRef over-read tail", S.scn_tail_garbage)
run("INVALIDATED is never writer-usable (B10, B8, B14, B15 before; INVALIDATED after)", S.scn_writer_usable)

# ---------------------------------------------------------------------------
print("[3] REFUSALS (exact locked text, arm off, candidate consumed, nothing written)")
ROWS = S.refusal_rows()
names = [r.name for r in ROWS]
check("refusal table rows have unique names", len(set(names)) == len(names))
check(f"refusal table: {len(ROWS)} rows (>= 100)", len(ROWS) >= 100)
families = {"arm": 0, "id format": 0, "wrong id": 0, "phrase": 0, "class": 0, "bus busy": 0, "fresh read": 0, "with a pending candidate": 0}
for r in ROWS:
    for f in families:
        if r.name.startswith(f):
            families[f] += 1
for f, n in families.items():
    check(f"refusal family '{f}' has rows ({n})", n >= 3)
for r in ROWS:
    run(f"refuse: {r.name}", S.scn_refusal, r)
    STATS["rows"]["refusal rows"] = STATS["rows"].get("refusal rows", 0) + 1
bcand = Batch("every refusal row again with a REVIEW candidate pending: consumed by each refusal that passed the in-flight check", "refusal + candidate")
pending = [0]
for r in ROWS:
    if r.candidate or r.drv.get("boot") is False:
        continue
    ec = bcand.row(r.name, S.scn_refusal_with_candidate, r)
    pending[0] += 1 if (ec is not None and getattr(ec, "pending", False)) else 0
bcand.done(100)
check(f"a candidate was really pending in {pending[0]} of those rows (>= 90)", pending[0] >= 90)
bf = Batch("fresh-read refusals leave a coherent mirror and a gate-refused follow-up", "fresh follow-ups")
for r in ROWS:
    if r.stage == "fresh":
        bf.row(r.name, S.scn_fresh_followup, r)
bf.done(10)

# ---------------------------------------------------------------------------
print("[4] one-shot arm, TTL, tokens, in-flight, busy, races")
run("the arm is one-shot: a second call without a fresh arm is refused; a repeated INVALIDATE is refused (class INVALIDATED)", S.scn_arm_is_one_shot)
run("the arm survives candidate expiry (INVALIDATE stays usable after 120 s)", S.scn_arm_survives_candidate_expiry)
run("only the exact token INVALIDATE reaches the INVALIDATE script (13 spellings / reserved tokens write nothing)", S.scn_wrong_tokens)
run("the router still sends SAVE to the SAVE gate", S.scn_router_save)
run("second execute during an in-flight SAVE: arm off only; the SAVE still commits the reviewed bytes", S.scn_inflight_save)
run("second execute during an in-flight REVIEW: arm off only", S.scn_inflight_review)
# FB-B2 serialisation proof (final hardening): INVALIDATE never overlaps an in-flight SAVE / REVIEW / real ECCO writer
run("INVALIDATE attempted at EVERY phase of an in-flight SAVE: refused, no storage / Modbus access, flags untouched; the SAVE commits; INVALIDATE works right after", S.scn_inflight_save_every_phase)
run("INVALIDATE attempted at every phase of an in-flight REVIEW: refused, nothing written", S.scn_inflight_review_every_phase)
for _script in ("apply_manual_slot1", "start_free_power_override", "start_dump_to_grid_override"):
    run(f"a REAL {_script} parked holding the write mutex: INVALIDATE refused (busy), no access, writer flags untouched", S.scn_inflight_real_writer, _script)
run("INVALIDATE then SAVE back to back: the SAVE finds no candidate and writes nothing", S.scn_invalidate_then_save_same_instant)
run("in-flight refusal with op_in_progress set: candidate untouched, arm off only", S.scn_inflight_injected, "op_in_progress")
run("in-flight refusal with the dispatch script running: candidate untouched, arm off only", S.scn_inflight_injected, "dispatch")
bb = Batch("busy refusal leaves the bus flag alone, then a re-armed call succeeds", "busy retry")
for flag in ("manual_write_in_progress", "correction_in_progress", "verification_pending", "verification_read_active",
             "free_power_operation_in_progress", "free_power_recovery_force_in_progress", "free_power_recovery_accept_in_progress",
             "reg244_apply_in_progress", "dump_operation_in_progress", "tx"):
    bb.row(flag, S.scn_busy_then_retry, flag)
bb.done(10)
br = Batch("bus turns busy AFTER the gate and the fresh read: the last check refuses before the writer", "bus races")
for how in S.RACES:
    br.row(how, S.scn_bus_race, how)
br.done(13)
run("after the call the 10 s housekeeping changes nothing (clean)", S.scn_idle_stability, "clean")
run("after the call the 10 s housekeeping changes nothing (UNKNOWN)", S.scn_idle_stability, "unknown")
run("after the call the 10 s housekeeping changes nothing (witness advanced)", S.scn_idle_stability, "witness_advanced")

# ---------------------------------------------------------------------------
print("[5] writer-stage refusals")
run("handle gone at the commit: 'storage unavailable - nothing written', no write, no latch", S.scn_writer_refusal, "handle")
run("storage unhealthy at the commit: 'storage not healthy - nothing written', no write, no latch", S.scn_writer_refusal, "unhealthy")
run("plan layer: the profile changed behind the mirror (another VALID record in flash AND RAM): 'stored profile changed; nothing written', "
    "then only ITS id works", S.scn_plan_stage, "binding_changed")
run("plan layer: the generation floor rose after the gate: 'not ahead of this boot's generation high-water mark', gate refuses next time, "
    "reboot re-derives", S.scn_plan_stage, "seen_raised")
run("plan layer: the SAVE_UNCONFIRMED overlay appeared after the gate: 'previous write outcome unknown', overlay kept, reboot clears it",
    S.scn_plan_stage, "unconfirmed_raised")

# ---------------------------------------------------------------------------
print("[6] power cuts at every NVS event of an INVALIDATE, then the real on_boot")
CUT_TOTAL = [0]
for label, seed in S.CUT_SEEDS.items():
    STATS["scenarios"] += 1
    e, rows = S.scn_cut_sweep(live, seed)
    STATS["assertions"] += e.n
    STATS["scenarios"] += len(rows)
    CUT_TOTAL[0] += len(rows)
    STATS["rows"]["power-cut rows"] = STATS["rows"].get("power-cut rows", 0) + len(rows)
    classes = {}
    for c in e.classes:
        classes[c] = classes.get(c, 0) + 1
    check(f"power cut sweep ({label}): {len(rows)} rows, boot class VALID/PROFILE_STALE/INVALIDATED = "
          f"{classes.get('VALID', 0)}/{classes.get('PROFILE_STALE', 0)}/{classes.get('INVALIDATED', 0)}",
          not e and set(classes) == {"VALID", "PROFILE_STALE", "INVALIDATED"}, "; ".join(e[:3]))

# ---------------------------------------------------------------------------
print("[7] NVS write faults")
hand_batch = Batch("locked outcome table (F1..F8, F-H2): model verdict, texts, flash, mirror, overlay, aftermath, reboot", "locked fault table")
VERDICTS = set()
for label, faults, *h in S.HAND_TABLE:
    e = hand_batch.row(label, S.scn_fault_row, "valid", faults, label, hand=tuple(h))
    if e is not None and e.verdict is not None:
        VERDICTS.add((e.verdict.outcome, bool(e.verdict.r.witness_advanced)))
hand_batch.done(len(S.HAND_TABLE))
mat = Batch("fault matrix, VALID/B10 (key x raw result x readback x health)", "fault matrix")
RB_SEEN = set()
for label, faults in S.fault_matrix_valid():
    e = mat.row(label, S.scn_fault_row, "valid", faults, label)
    if e is not None and e.verdict is not None:
        VERDICTS.add((e.verdict.outcome, bool(e.verdict.r.witness_advanced)))
        RB_SEEN.add(fd.RB_NAMES[(e.verdict.r.w if e.verdict.r.w.outcome == fd.KEY_UNKNOWN_REBOOT else e.verdict.r.p).rb_class])
mat.done(352)
boot = Batch("fault matrix, boot resolution of the written key (NEW / OLD / ABSENT)", "fault boot rows")
for label, faults in S.fault_matrix_boot():
    boot.row(label, S.scn_fault_row, "valid", faults, label, aftermath=False)
boot.done(144)
for label, seed in list(S.SEEDS_CLEAN.items())[1:]:
    other = Batch(f"fault cells over {label}", "fault other seeds")
    for flabel, faults in S.fault_matrix_seed(seed):
        other.row(flabel, S.scn_fault_row, seed, faults, flabel)
    other.done(len(S.HAND_TABLE))
# the witness situations whose PRIOR descriptor differs (B14: the witness is ABSENT, B15: present but unusable): the whole key x raw result x
# readback grid again (healthy pages; the INVALID-page dimension and the aftermath do not depend on the witness situation)
wfull = Batch("full fault matrix over B14 (witness missing) / B15 (witness corrupt): key x raw result x readback, model verdict + flash + mirror + reboot",
              "fault matrix other witness")
for label in ("VALID/B14 witness missing", "VALID/B15 witness corrupt"):
    for flabel, faults in S.fault_matrix_valid():
        if all(f.healthy_after for f in faults.values()):
            wfull.row(f"{label[6:9]} {flabel}", S.scn_fault_row, S.SEEDS_CLEAN[label], faults, flabel, aftermath=False)
wfull.done(352)
check("the fault matrix reaches COMMITTED, NOT_COMMITTED (witness not advanced), NOT_COMMITTED (witness advanced) and UNKNOWN_REBOOT",
      VERDICTS == {(fd.TXN_COMMITTED, False), (fd.TXN_NOT_COMMITTED, False), (fd.TXN_NOT_COMMITTED, True), (fd.TXN_UNKNOWN_REBOOT, False)},
      str(sorted(VERDICTS)))
check("UNKNOWN rows cover every readback class the writer can report (INTENDED PRIOR OTHER_BYTES ABSENT_UNEXPECTED WRONG_SIZE READ_ERROR UNAVAILABLE)",
      {"INTENDED", "PRIOR", "OTHER_BYTES", "ABSENT_UNEXPECTED", "WRONG_SIZE", "READ_ERROR", "UNAVAILABLE"} <= RB_SEEN, str(sorted(RB_SEEN)))
run("UNKNOWN where nothing landed: B1 is the overlay, only the reboot reports VALID g7 again, then a re-issued INVALIDATE works", S.scn_unknown_residual_valid_reboot)
run("a SAVE with an UNKNOWN outcome blocks INVALIDATE until the reboot", S.scn_save_unknown_blocks_invalidate)

# ---------------------------------------------------------------------------
print("[8] sequences, REPLACE CORRUPT edges, boundaries")
run("INVALIDATE -> Review+SAVE -> reboot -> INVALIDATE -> SAVE: generations 7,8,9,10,11 and the witness chain", S.scn_seq_inv_save_inv)
run("REPLACE CORRUPT (garbage record, hw 9) -> VALID g10 -> INVALIDATE g11 -> reboot -> Save g12", S.scn_seq_replace_corrupt_then_invalidate, "garbage")
run("REPLACE CORRUPT (wrong-size record, hw 9) -> VALID g10 -> INVALIDATE g11 -> reboot -> Save g12", S.scn_seq_replace_corrupt_then_invalidate, "wrong size")
run("REPLACE CORRUPT with the FBP write refused after the witness advanced: still CORRUPT, INVALIDATE refused, next REPLACE CORRUPT g11, INVALIDATE g12", S.scn_replace_corrupt_half_landed)
run("a PROFILE_STALE profile is refused, a plain Save makes it VALID g8, INVALIDATE works", S.scn_seq_stale_save_then_invalidate)
run("g = 0xFFFFFFFE: INVALIDATE gives 0xFFFFFFFF, then SAVE is refused 'counter exhausted'", S.scn_boundary_generation)
run("seen_hw_gen == g allows the INVALIDATE and is raised to g+1", S.scn_seen_floor_boundary)
run("RAM class forced VALID over an INVALIDATED mirror: refused at I10 (profile_invalidate_permitted), nothing written", S.scn_inconsistent_class_over_invalidated)
rnd = Batch("randomised operation sequences (Review / INVALIDATE / SAVE / REPLACE CORRUPT / faults / leases / mutex / reboot), invariants after every step",
            "random sequences")
for seed_no in range(1, 201):
    rnd.row(f"seed {seed_no}", S.scn_random_sequence, seed_no)
rnd.done(200)

# ---------------------------------------------------------------------------
print("[9] MUTANTS (broken copies of the firmware / mirror / writer, each killed by named scenarios)")
YAML_MUTANTS = M.yaml_mutants()
MIRROR_MUTANTS = M.mirror_mutants()
WRITER_MUTANTS = M.writer_mutants()
ALL_MUTANTS = YAML_MUTANTS + MIRROR_MUTANTS + WRITER_MUTANTS
check(f"mutant inventory: {len(YAML_MUTANTS)} firmware-text + {len(MIRROR_MUTANTS)} mirror + {len(WRITER_MUTANTS)} writer mutants (>= 30 firmware-text)",
      len(YAML_MUTANTS) >= 30 and len(set(mu.mid for mu in ALL_MUTANTS)) == len(ALL_MUTANTS))
needed = sorted({dn for mu in ALL_MUTANTS for dn in mu.detectors})
control_bad = []
for dn in needed:
    try:
        e = M.DETECTORS[dn](live)
    except Exception as ex:  # noqa: BLE001
        control_bad.append(f"{dn}: exception {type(ex).__name__} {str(ex)[:80]}")
        continue
    STATS["scenarios"] += 1
    if e:
        control_bad.append(f"{dn}: {str(e[0])[:100]}")
check(f"control: all {len(needed)} detectors named by the mutants are GREEN on the real firmware", not control_bad, "; ".join(control_bad[:3]))
check("control: the static INVALIDATE pins are green on the real firmware", not S.static_inv(LIVE_TEXT))
KILLED = {"yaml": 0, "mirror": 0, "writer": 0}
TOTAL = {"yaml": 0, "mirror": 0, "writer": 0}
for mu in ALL_MUTANTS:
    TOTAL[mu.kind] += 1
    mk, ctx = M.make_factory(mu)
    kills, errors = [], []
    with ctx:
        for dn in mu.detectors:
            STATS["scenarios"] += 1
            try:
                e = M.DETECTORS[dn](mk)
            except Exception as ex:  # noqa: BLE001 - a harness error is NOT a kill
                errors.append(f"{dn}: {type(ex).__name__} {str(ex)[:60]}")
                continue
            if e:
                kills.append(f"{dn} ({str(e[0])[:70]})")
    if mu.kind == "yaml" and mu.static:
        se = S.static_inv(mu.text)
        STATS["scenarios"] += 1
        if se:
            kills.append(f"static pin ({str(se[0])[:70]})")
    if mu.kind == "yaml":
        D._FW_CACHE.pop(hashlib.sha256(mu.text.encode("utf-8")).hexdigest(), None)      # keep the process small (one parse per mutant)
        mu.text = ""
    if kills:
        KILLED[mu.kind] += 1
    check(f"mutant {mu.mid} [{mu.kind}] killed: {mu.desc}", bool(kills),
          "SURVIVED" + (f"; detector errors: {errors[:2]}" if errors else ""))
total_m, killed_m = sum(TOTAL.values()), sum(KILLED.values())
check(f"mutants: {killed_m}/{total_m} killed ({KILLED['yaml']}/{TOTAL['yaml']} firmware text, {KILLED['mirror']}/{TOTAL['mirror']} mirror, "
      f"{KILLED['writer']}/{TOTAL['writer']} writer)", killed_m == total_m and TOTAL["yaml"] >= 30)

# ---------------------------------------------------------------------------
print()
print(f"scenario executions: {STATS['scenarios']}; sweep / matrix / refusal rows: {dict(STATS['rows'])}; "
      f"power-cut rows {CUT_TOTAL[0]}; assertions inside scenarios: {STATS['assertions']}; check() calls: {NCHECKS[0]}; "
      f"mutants {killed_m}/{total_m}; {time.time() - T0:.0f} s")
check("suite summary: every section ran", STATS["scenarios"] > 1000 and NCHECKS[0] > 250)

if FAILURES:
    print(f"\n{len(FAILURES)} FAILURE(S):")
    for f in FAILURES:
        print("  -", f)
    sys.exit(1)
print("\nall checks passed")
