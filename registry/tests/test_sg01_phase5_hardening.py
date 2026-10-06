#!/usr/bin/env python3
"""SG-01 Phase 5 - hardening pins for the Free Power interrupted-START
recovery (SELF_PARTIAL) and the operator recovery paths around it.

Phase 5 adds NO behaviour. It pins what Phases 1-4 built so a later change
cannot weaken it silently:

  * Force Restore Original and Accept Current State are EXECUTED as real
    firmware (Review -> the `free_power_recovery_execute` API action ->
    gate script -> dispatch) against every legal SELF_PARTIAL state and
    prove they are unchanged by SG-01: Force never consults the journal or
    the SELF_PARTIAL classification, Accept refuses every SELF_PARTIAL
    state.
  * every SELF_PARTIAL safety rule is pinned statically (the classifier's
    exact guard sequence) and dynamically (real firmware probes).
  * a mutation matrix breaks each rule on purpose and requires the
    detector aimed at it to catch it.
  * the write surface, the durable schema and every script / boot block
    outside the two SG-01 change sites are pinned byte-for-byte against
    main before SG-01 (6c62417, PR #46 merged).
  * end-to-end scenarios A-J run whole-device lifecycles (START, power
    cuts, reboot from NVS, restore, operator recovery, dual obligations).

How the firmware is executed (no ESPHome/C++ toolchain, no hardware, no
Modbus): registry/tests/_dump_sim.py transpiles the real lambdas (strict:
unknown syntax raises) and walks the real action trees over an in-memory
register bank and NVS store; registry/tests/_sg01_recovery_harness.py holds
the device/scenario helpers. Section [1] self-tests the transpiler
constructs Phase 5 added to _dump_sim.py (switch, range-for, captureless
lambdas, snprintf-as-expression, the ecco_recovery_evidence namespace) and
proves the Review fingerprint equals the offline mirror for every block
state.

These are source-level proofs: they show the firmware SOURCE behaves this
way under the simulator's documented semantics - never that the compiled
firmware was exercised against a real inverter.

Sections:
  [1]  harness self-tests (Phase 5 transpiler additions, fingerprint mirror)
  [2]  change scope vs main before SG-01 (6c62417)
  [3]  Force Restore Original - unchanged, journal/SELF_PARTIAL independent
  [4]  Accept Current State - refuses every SELF_PARTIAL state
  [5]  SELF_PARTIAL safety pins (static guard order + dynamic probes)
  [6]  write-surface proof
  [7]  durable-schema proof
  [8]  end-to-end regression scenarios A-J
  [9]  mutation matrix
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _mtou1_scope as mtou1  # noqa: E402
import _sg01_recovery_harness as h  # noqa: E402
import _sg06_scope as sg06  # noqa: E402
import _dump_v2_scope as dv2s  # noqa: E402 - Dump V2's own later edits, reverted before the pins below
import _scope_chain as chain  # noqa: E402 - FB-T0: the change-scope pins are evaluated as of chain entry "dump_v2"
from _sg01_recovery_harness import (  # noqa: E402
    ACCEPT, ACCEPT_DISPATCH, ALL_COMBOS, B1, B2, B3, B4, BITS, BOTH, CLEAR, COMMS, DATA_KEY, DISPATCH, FORCE,
    FORCE_DISPATCH, I, INTENDED, JKEY, LEASE, NEITHER, O, ORIGINAL, OWNED, PENDING, RETRY_KEY, RR, SELF_PARTIAL,
    SNAP, SNAP_INT, SNAP_ORIG, START, VALID_KEY, VERIFIED, WRAPPER, X, D, ds, fpre, fpsim, fsp, jm,
)

ROOT = h.ROOT
sys.path.insert(0, str(ROOT / "tools"))
import analyze_write_surface as aws  # noqa: E402

FAILURES: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  PASS  {name}")
    else:
        FAILURES.append(name)
        print(f"  FAIL  {name}" + (f" - {detail}" if detail else ""))


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def raises(exc, fn) -> bool:
    try:
        fn()
    except exc:
        return True
    except Exception:  # noqa: BLE001 - a DIFFERENT exception is not the one under test
        return False
    return False


FW_TEXT = h.FW_TEXT
HEADER = h.HEADER
REAL = h.FwCtx(FW_TEXT)
FW = REAL.fw
FORCE_ACTION, ACCEPT_ACTION = "FORCE_RESTORE_ORIGINAL", "ACCEPT_CURRENT_STATE"
SP_CASES = h.self_partial_cases()  # every (block states, mask) the model admits as SELF_PARTIAL


def boot(row_or_live, journal=(7, 0), *, snap=SNAP, ctx=REAL, operator_needed=0, binding=None, reg244=LEASE,
         full_boot=False):
    live = h.live_for(h.states_of_row(row_or_live), snap) if isinstance(row_or_live, str) else row_or_live
    return h.boot_device(h.nvs_image(snap, journal=journal, operator_needed=operator_needed, binding=binding),
                         h.make_bank(live, reg244), ctx, full_boot=full_boot)


def locked_out_neither(run: h.Run, bank_before: dict) -> bool:
    s = run.sim
    return (run.dispatched and run.writes == [] and s.g["free_power_restore_unexplained_drift"]
            and s.g["free_power_operator_needed"] and h.nvs_operator_needed(s) == 1
            and s.g["free_power_marker_state"] == RR and h.nvs_marker(s) == RR and s.g["free_power_snapshot_valid"]
            and s.bank == bank_before and not s.g["free_power_operation_in_progress"])


def completed(run: h.Run, orig=SNAP_ORIG) -> bool:
    s = run.sim
    return (h.all_original(s, orig) and s.g["free_power_marker_state"] == CLEAR and h.nvs_marker(s) == CLEAR
            and not s.g["free_power_snapshot_valid"] and not s.g["free_power_operator_needed"]
            and h.nvs_operator_needed(s) == 0 and not s.g["free_power_operation_in_progress"]
            and not s.g["manual_write_in_progress"])


def refused_untouched(run: h.Run, bank_before: dict) -> bool:
    """An operator action that refused: zero writes, zero durable commits,
    obligation retained, locks released."""
    s = run.sim
    return (run.writes == [] and run.commits == [] and s.bank == bank_before and h.nvs_marker(s) == RR
            and s.g["free_power_marker_state"] == RR and s.g["free_power_snapshot_valid"]
            and not s.g["free_power_operation_in_progress"] and not s.g["manual_write_in_progress"]
            and not s.g["free_power_active_persisted"])


def status(sim) -> str:
    return str(sim.ent("free_power_status").state)


def last_action(sim) -> str:
    return str(sim.ent("free_power_recovery_last_action").state)


# ===========================================================================
print("[1] harness self-tests - the _dump_sim.py constructs Phase 5 added, and the fingerprint mirror")
# ===========================================================================
_hs = ds.Sim(FW)


def run_c(code: str, **local):
    return _hs.run_lambda(code, {k: (ds.CStr(v) if isinstance(v, str) else v) for k, v in local.items()},
                          params=tuple(local))


SWITCH = ("int r = 0; switch (v) { case 1: r = 10; break; case 2: case 3: r = 20; break; "
          "default: r = 30; break; } return r;")
check("switch: case / stacked labels / default dispatch like C (v=1..4 -> 10, 20, 20, 30)",
      [run_c(SWITCH, v=v) for v in (1, 2, 3, 4)] == [10, 20, 20, 30])
check("switch: a fall-through clause is REFUSED (Unsupported), never guessed",
      raises(ds.Unsupported, lambda: run_c("int r = 0; switch (v) { case 1: r = 1; case 2: r = 2; break; } return r;", v=1)))
HEX = ("auto ok = [](const std::string &s) -> bool { if (s.size() != 16) return false; for (char c : s) { "
       "if (!((c >= '0' && c <= '9') || (c >= 'A' && c <= 'F'))) return false; } return true; }; return ok(v);")
check("captureless lambda + range-for over a string + char literals (the Force/Accept evidence-ID validator shape)",
      [run_c(HEX, v=s) for s in ("0123456789ABCDEF", "0123456789abcdef", "0123456789ABCDE", "0123456789ABCDEG")]
      == [True, False, False, False])
check("a lambda WITH a capture list is REFUSED (its scope rules are not modelled)",
      raises(ds.Unsupported, lambda: run_c("auto f = [&](int a) -> int { return a; }; return f(v);", v=1)))
APPEND = ("char b[8]; int n = 0; n += snprintf(b + n, sizeof(b) - n, \"%s\", \"abcde\"); "
          "n += snprintf(b + n, sizeof(b) - n, \"%s\", \"fghij\"); int full = n; "
          "if (n < 0 || (size_t) n >= sizeof(b)) n = (int) sizeof(b) - 1; return std::string(b) + \"|\" + "
          "std::string(full == 10 ? \"10\" : \"x\") + \"|\" + std::string(n == 7 ? \"7\" : \"x\");")
check("snprintf as an expression: C99 truncation (writes size-1 chars) and returns the untruncated length",
      run_c(APPEND, v=0) == "abcdefg|10|7", run_c(APPEND, v=0))
check("snprintf into something that is not a sized char array of the lambda is REFUSED",
      raises(ds.Unsupported, lambda: run_c("int n = 0; n += snprintf(q + n, 4, \"%u\", 1); return n;", q=ds.CStr(""))))
check("%016llX formats a 64-bit value like the firmware's evidence ID",
      ds.c_format("%016llX", 0xAB) == "00000000000000AB" and ds.c_format("%016llX", 0xFEDCBA9876543210) == "FEDCBA9876543210")
check("(unsigned long long) casts wrap to 64 bits", run_c("return (unsigned long long) v;", v=-1) == (1 << 64) - 1)
_recovery_scripts = ("free_power_recovery_invalidate_evidence", h.REVIEW, "free_power_recovery_review_dispatch", FORCE,
                     FORCE_DISPATCH, ACCEPT, ACCEPT_DISPATCH)


def _lambdas(node):
    if isinstance(node, dict):
        for k, v in node.items():
            if k in ("lambda", "values") and isinstance(v, str):
                yield v
            else:
                yield from _lambdas(v)
    elif isinstance(node, list):
        for v in node:
            yield from _lambdas(v)


_untranspiled = []
_n_lambdas = 0
for sid in _recovery_scripts:
    for code in _lambdas(REAL.scripts[sid]["then"]):
        _n_lambdas += 1
        try:
            _hs.compile(code, ("values",))
        except ds.Unsupported as exc:
            _untranspiled.append((sid, str(exc)[:60]))
check(f"every one of the {_n_lambdas} lambdas in Review / Force / Accept (+ evidence invalidation) transpiles - "
      "nothing is skipped or stubbed", not _untranspiled and _n_lambdas > 150, str(_untranspiled[:3]))
_fp_bad = []
for combo in ALL_COMBOS:
    snap, live = h.scenario(combo)
    dev = h.boot_device(h.nvs_image(snap, journal=(15, 0)), h.make_bank(live), REAL)
    eid = h.review(dev)
    want = h.expected_fingerprint(dev)
    if eid != fpre.format_fingerprint_hex(want) or dev.g["free_power_recovery_evidence_fingerprint"] != want:
        _fp_bad.append((h.row_of(combo), eid))
check("the REAL Review's evidence fingerprint and published ID equal the offline mirror "
      "(free_power_recovery_evidence.compute_fingerprint) for all 256 block states", not _fp_bad, str(_fp_bad[:3]))
dev = boot("IIIO")
dev.bank[244] = 7
check("...and the fingerprint covers the context registers (244 changed -> different ID)",
      h.review(dev) != h.review(boot("IIIO")))

# ===========================================================================
print("")
print("[2] change scope - everything outside the two SG-01 change sites is byte-identical to main before SG-01 (6c62417)")
# ===========================================================================
# FB-T0: every change-scope PIN below (script-body hashes, on_boot / interval / API / globals hashes, Modbus op lists,
# durable call-site counts, header and evidence-header hashes) is evaluated on the artifacts AS OF chain entry "dump_v2"
# (main @ ca7474e): every LATER chain entry is undone by its exact-match reverter first (registry/tests/_scope_chain.py), so
# a later PR's declared deltas never re-hash these pins and an undeclared edit still breaks them. Today nothing follows
# "dump_v2": the SCOPE_* texts are byte-for-byte the live ones. The behavioural / property checks keep using the LIVE text.
SCOPE_FW_TEXT = chain.CHAIN.as_of(chain.FIRMWARE, "dump_v2", FW_TEXT)
SCOPE_FW = ds.load_firmware_text(SCOPE_FW_TEXT)
SCOPE_HEADER = chain.CHAIN.as_of(chain.DURABLE_HEADER, "dump_v2", h.HEADER)
SCRIPT_IDS = [s["id"] for s in FW["script"]]
SCOPE_SCRIPT_IDS = [s["id"] for s in SCOPE_FW["script"]]
# Manual TOU Phase 1 later edited the six apply_manual_slotN scripts and the
# Load buttons, and added two RAM globals and one RAM-only interval; its exact
# edits are reverted first, so this still proves byte-identity everywhere
# else - see _mtou1_scope.py.
PRE_MTOU1_TEXT = mtou1.pre_mtou1_text(FW_TEXT)
PRE_MTOU1_FW = ds.load_firmware_text(PRE_MTOU1_TEXT)
BODIES = {sid: fpsim.script_body(PRE_MTOU1_TEXT, sid) for sid in SCRIPT_IDS}
SCOPE_PRE_MTOU1_TEXT = mtou1.pre_mtou1_text(SCOPE_FW_TEXT)
SCOPE_PRE_MTOU1_FW = ds.load_firmware_text(SCOPE_PRE_MTOU1_TEXT)
SCOPE_BODIES = {sid: fpsim.script_body(SCOPE_PRE_MTOU1_TEXT, sid) for sid in SCOPE_SCRIPT_IDS}
# Dump V2 (ownership evidence) later edited three Dump scripts; the pins
# below hash them with exactly those edits reverted (_dump_v2_scope.py).
PRE_DUMP_V2_BODIES = {sid: dv2s.pre_dump_v2_script(sid, b) for sid, b in SCOPE_BODIES.items()}
SG01_CHANGED = {START, DISPATCH}
# Measured on main @ 6c62417 (PR #46 merged, before SG-01 Phase 0) and
# re-measured on main @ 2d73eb2 (SG-01 Phase 3/4 merged): identical.
PRE_SG01 = {
    "free_power_recovery_force_restore": "47aa3dbdd589da779d9f16ac39da5f08a147b1778785283de9b63d486bce15fa",
    "free_power_recovery_force_restore_dispatch": "45d3c66f2c7c1d5583ad79525ae88edc783386b1a35ab22cfce0ddae7ecbbe6c",
    "free_power_recovery_accept_current_state": "5cdc0b358c2d1b547254a0dfe6fbc62a2d8580a8fac14d14ffd4be562fa6faf2",
    "free_power_recovery_accept_current_state_dispatch": "7c5806c183db5f5996c0cb2af952c923a9e1f7d042a3f7911a31829e38e96342",
    "free_power_recovery_review": "a1861ea5f21f1bafd78dc06fe55ce01f29ff45fd5fcc616d0cd7c800019dfb21",
    "free_power_recovery_review_dispatch": "9d11477280f15afadc0d39b4d7e21faec050773b499ff832932092d0e842c536",
    "free_power_recovery_invalidate_evidence": "bfd6f39ce8be56e34bd052a2d9b18cc8e97f0ee9dd9d8b7a32c607d4e5774904",
    "restore_free_power_snapshot": "ce0425b5c448822a88e99031782916f5d8b0655fa53c85a39eee6e04c304f343",
    "dump_accept_current_state": "a4fa3cbdb15638e003ed54a8a90fb3b58c30414e7fb16f58d2d45c14cd0c7ea0",
    "dump_force_restore_original": "e4cda9a874231b9b24be1522d7a4d0846d2320c8028ea3e04add6977f8bf28b4",
    "dump_lockout_containment": "ce26ae903ffe7fbd4b2966be4395f3cd86771565f5d00a8d1958c54992cf913d",
}
for sid, digest in PRE_SG01.items():
    check(f"{sid} is byte-identical to main before SG-01 (6c62417)", sha(SCOPE_BODIES[sid]) == digest)
combined = sha("\n".join(f"== {sid}\n{PRE_DUMP_V2_BODIES[sid]}" for sid in sorted(SCOPE_BODIES) if sid not in SG01_CHANGED))
check(f"all {len(SCOPE_BODIES) - 2} scripts other than start_free_power_override (Phase 1/2) and "
      "restore_free_power_snapshot_dispatch (Phase 3/4) are byte-identical to 6c62417 - Force, Accept, Review, "
      "the restore wrapper, every Dump script (#44 Accept gate, #46 containment), reg244, RTC, manual slots",
      combined == "f27aae54f807d92d220047d97abee9c4e81b19e037dd172f84a1db9d6bf24aaa", combined)
BOOT = h.boot_lambda(FW)
JBLOCK_START = "\n}\n{\n  // SG-01 Phase 2: load the Free Power START journal"
JBLOCK_END = "(int) have_journal);\n    }\n  }"
_js = BOOT.index(JBLOCK_START)
_je = BOOT.index(JBLOCK_END, _js) + len(JBLOCK_END)
# SG-06 later edited on_boot (the three marker loads, their status texts and
# the containment seed); its exact edits are reverted first, so this still
# proves byte-identity everywhere else - see _sg06_scope.py.
SCOPE_BOOT = h.boot_lambda(SCOPE_FW)
_sjs = SCOPE_BOOT.index(JBLOCK_START)
_sje = SCOPE_BOOT.index(JBLOCK_END, _sjs) + len(JBLOCK_END)
_PRE_SG06 = sg06.pre_sg06_boot(dv2s.pre_dump_v2_boot(SCOPE_BOOT))
_pjs = _PRE_SG06.index(JBLOCK_START)
_pje = _PRE_SG06.index(JBLOCK_END, _pjs) + len(JBLOCK_END)
check("on_boot = the 6c62417 on_boot + exactly ONE inserted block (the Phase 2 journal load): with it cut out "
      "(and SG-06's own edits reverted), the lambda is byte-identical (Free Power / reg244 / Dump boot blocks, "
      "the S4 and Free Power<->Dump (PR41) arbitration, #46 containment initialisation)",
      sha(_PRE_SG06[:_pjs] + _PRE_SG06[_pje:]) == "52812cf2c29992b1dbb1bbf0eeb90f25844c28dab971cb8dccaa5f9bb5c88e8a"
      and SCOPE_BOOT.count(JBLOCK_START) == 1)
check("...and that inserted block is itself pinned (Phase 1/2 journal load, unchanged by Phase 3/4/5)",
      sha(SCOPE_BOOT[_sjs:_sje]) == "1eb97c99dbd400030ed73b14b9dd1a1a53eeb7d7a6dbcbee5e73b47610e15d27")
_jload = fpsim._strip_code(BOOT[_js:_je])
check("the journal-load block is LOAD-only: one load_record of the journal tag, zero commit_record, zero Modbus, "
      "and it writes only the four journal RAM mirrors",
      len(re.findall(r"load_record\(", _jload)) == 1 and "commit_record" not in _jload and "modbus" not in _jload
      and set(re.findall(r"id\((\w+)\)\s*=(?!=)", _jload)) == {"free_power_start_journal_valid", "free_power_start_journal_mask",
                                                               "free_power_start_journal_flags", "free_power_start_journal_binding"})
check("every other on_boot action, every interval (watchdogs, PR41/S4 arbitration timers) and every API action "
      "is identical to 6c62417",
      sha(json.dumps(SCOPE_FW["esphome"]["on_boot"]["then"][1:], sort_keys=True, default=str))
      == "d9e9f34593af221c552f72a04f7cbc2c1632108eef345774e2791913f48bb4fe"
      and sha(str(SCOPE_PRE_MTOU1_FW.get("interval"))) == "90cbc7673c5afff7d3fd81a534e360d29c8675de69a8d942249e7f0988a29927"
      and sha(json.dumps(SCOPE_FW["api"], sort_keys=True, default=str))
      == "258f3d4747c195f653a525677866130b5d8dd44810b6f215039e9fb518b107da")
SG01_GLOBALS = {"free_power_start_journal_valid", "free_power_start_journal_mask", "free_power_start_journal_flags",
                "free_power_start_journal_binding", "free_power_live_b3_original", "free_power_live_b3_intended",
                "free_power_live_b4_original", "free_power_live_b4_intended", "free_power_live_self_partial"}
_pre_globals = [g for g in dv2s.pre_dump_v2_globals(SCOPE_PRE_MTOU1_FW["globals"]) if g["id"] not in SG01_GLOBALS]
check("globals: exactly the 9 SG-01 RAM globals were added (none changed/removed), all restore_value false - "
      "no ESPHome-persisted durable field hides among them (Manual TOU Phase 1's two RAM globals reverted first)",
      sha(json.dumps(_pre_globals, sort_keys=True, default=str))
      == "1ee042d29f969f8e347ae534ab0e48ebef5e6cf80134de2382ab30a551501e44"
      and all(not g.get("restore_value") for g in FW["globals"] if g["id"] in SG01_GLOBALS)
      and len({g["id"] for g in FW["globals"]} & SG01_GLOBALS) == 9)
check("the recovery evidence header (fingerprint) is byte-identical to 6c62417",
      sha(chain.CHAIN.as_of(chain.EVIDENCE_HEADER, "dump_v2", (ROOT / "firmware" / "include" / "ecco_recovery_evidence.h").read_text(encoding="utf-8")))
      == "c9b9b1d670ce8ef8ec33c5c1208326abd0213f042e8a69b1115b4ea85620875e")
_journal_users = sorted(sid for sid, b in BODIES.items() if fpsim.mentions_journal(b))
_sp_users = sorted(sid for sid, b in BODIES.items() if re.search(r"self_?partial", fpsim._strip_code(b), re.I))
check("only START (writes it) and the restore dispatch (reads it) reference the journal; only the restore dispatch "
      "references SELF_PARTIAL - Force, Accept, Review and every other script consult neither",
      _journal_users == sorted(SG01_CHANGED) and _sp_users == [DISPATCH], f"{_journal_users} / {_sp_users}")

# ===========================================================================
print("")
print("[3] Force Restore Original - executed as real firmware; unchanged, journal- and SELF_PARTIAL-independent")
# ===========================================================================
JOURNAL_VARIANTS = [("mask as recorded", "mask"), ("no journal", None), ("START_VERIFIED", (15, VERIFIED)),
                    ("bound to another snapshot", "unbound"), ("illegal mask 5 in NVS", (5, 0))]


def boot_variant(snap, live, mask, variant, ctx=REAL):
    binding = None
    if variant == "mask":
        j = (mask, 0)
    elif variant == "unbound":
        j, binding = (mask, 0), jm.journal_binding(snap) ^ 0x1
    else:
        j = variant
    return h.boot_device(h.nvs_image(snap, journal=j, binding=binding), h.make_bank(live), ctx)


force_bad, force_n, force_diverge = [], 0, []
for combo, mask in SP_CASES:
    snap, live = h.scenario(combo)
    orig = h.originals_of(snap)
    traces = {}
    for label, variant in JOURNAL_VARIANTS:
        dev = boot_variant(snap, live, mask, variant)
        run, eid = h.operator_action(dev, REAL, FORCE_ACTION)
        force_n += 1
        traces[label] = h.trace(run)
        if not (run.op_seq == h.FORCE_OPS and completed(run, orig) and not run.violations
                and [c[1] for c in run.commits] == [VALID_KEY, VALID_KEY, RETRY_KEY]):
            force_bad.append((h.row_of(combo), mask, label, run.op_seq[:4], run.violations[:1]))
    # the same device with the SELF_PARTIAL RAM flag stale-set before Force
    dev = boot_variant(snap, live, mask, "mask")
    dev.g["free_power_live_self_partial"] = True
    run, _eid = h.operator_action(dev, REAL, FORCE_ACTION)
    traces["stale SELF_PARTIAL flag"] = h.trace(run)
    if len(set(traces.values())) != 1:
        force_diverge.append((h.row_of(combo), mask))
check(f"[Q1] Force on EVERY legal SELF_PARTIAL state ({len(SP_CASES)} block-state/mask cases x {len(JOURNAL_VARIANTS)} "
      f"journal variants = {force_n} runs): Review -> API -> the pinned op sequence, ORIGINAL snapshot values only, "
      "verified ORIGINAL, marker RR -> PENDING_CLEAR -> CLEAR then retry record cleaned, no START, no active_persisted",
      not force_bad and force_n == len(SP_CASES) * len(JOURNAL_VARIANTS), str(force_bad[:3]))
check("[Q2] Force does NOT depend on the journal or on SELF_PARTIAL: for every case the whole observable trace "
      "(every Modbus op + values, every durable commit, final bank, marker, lockout, status) is IDENTICAL with the "
      "journal as recorded, absent, START_VERIFIED, unbound, illegal - and with the SELF_PARTIAL RAM flag stale-set",
      not force_diverge, str(force_diverge[:4]))
check("[Q3] Force's Modbus order is the pinned B1(232) -> B4(256-261) -> 256x6 readback -> 244 -> B3(268-279) -> "
      "B2(230) -> 230x3 + 256x24 final verify, after fresh 230x3 / 256x24 / 244x12 confirm reads",
      h.FORCE_OPS == [("read", 230, 3), ("read", 256, 24), ("read", 244, 12), ("write", 232), ("write", 256),
                      ("read", 256, 6), ("read", 244, 1), ("write", 268), ("write", 230), ("read", 230, 3),
                      ("read", 256, 24)])
_fd = fpsim.flatten(REAL.scripts[FORCE_DISPATCH]["then"])
check("[Q3] ...and statically: Force's writes are 232, 256, 268, 230 carrying ONLY free_power_snapshot_regNNN "
      "(the durable ORIGINAL), no register-244 write",
      [b["start_address"] for k, _g, b in _fd if k == fpsim.WRITE] == [232, 256, 268, 230]
      and all(set(re.findall(r"id\((\w+)\)", b["values"])) <= {f"free_power_snapshot_reg{r}" for r in OWNED}
              for k, _g, b in _fd if k == fpsim.WRITE))
# Rows that are NOT SELF_PARTIAL: Force behaves the same way on them (it never classifies).
_other_bad = []
for row in ("OOOO", "IIII", "XOOO", "IIXO", "IIIX", "OIIO"):
    for j in ((15, 0), None, (15, VERIFIED)):
        run, _e = h.operator_action(boot(row, j), REAL, FORCE_ACTION)
        if not (run.op_seq == h.FORCE_OPS and completed(run) and not run.violations):
            _other_bad.append((row, j))
check("[Q4] Force on ORIGINAL, INTENDED, X-block, internal-mixture and START_VERIFIED-mixed rows performs the "
      "same verified ORIGINAL restore whatever the journal says (Force is the explicit operator recovery for "
      "every state the automatic path locks out)", not _other_bad, str(_other_bad[:3]))

# Gates - each refusal performs zero writes and keeps the obligation, whatever the journal.
GATE_CASES = []
for label, prep, phrase, arm, eid_override, want in (
    ("recovery arm OFF", None, None, False, None, "refused: recovery arm not enabled"),
    ("confirmation phrase wrong", None, "FORCE RESTORE ORIGINAL", True, None, "refused: confirmation phrase mismatch"),
    ("evidence ID of another review", None, None, True, "0123456789ABCDEF", "refused: evidence ID mismatch"),
    ("metadata corrupt after Review", "corrupt", None, True, None, "refused: metadata invalid"),
    ("marker not RESTORE_REQUIRED after Review", "pending", None, True, None, "refused: not RESTORE_REQUIRED"),
    ("evidence expired", "expire", None, True, None, "refused: evidence expired"),
):
    GATE_CASES.append((label, prep, phrase, arm, eid_override, want))
gate_bad = []
for label, prep, phrase, arm, eid_override, want in GATE_CASES:
    for j in ((7, 0), None):
        dev = boot("IIIO", j)
        eid = h.review(dev)
        if prep == "corrupt":
            dev.g["free_power_recovery_metadata_corrupt"] = True
        elif prep == "pending":
            dev.g["free_power_marker_state"] = PENDING
        elif prep == "expire":
            dev.advance(120_000)
        bank = dict(dev.bank)
        dev.ent("free_power_recovery_arm").state = arm
        use = eid_override or eid
        conf = phrase if phrase is not None else "FORCE RESTORE ORIGINAL " + use
        run = h.audited(dev, lambda d=dev, u=use, c=conf: h.api_execute(d, REAL, FORCE_ACTION, u, c))
        if prep == "pending":
            ok = run.ops == [] and run.commits == [] and dev.bank == bank and last_action(dev) == want
        else:
            ok = refused_untouched(run, bank) and run.ops == [] and last_action(dev) == want
        ok = ok and not dev.ent("free_power_recovery_arm").state and not dev.g["free_power_recovery_evidence_valid"]
        if not ok:
            gate_bad.append((label, j, last_action(dev), run.op_seq[:2]))
check(f"[Q5] Force's operator gates ({len(GATE_CASES)} kinds x journal present/absent): arm, exact phrase, evidence "
      "ID, metadata trust, RESTORE_REQUIRED marker, 120 s evidence expiry - each refuses with its own reason, ZERO "
      "Modbus I/O, ZERO durable commits, one-shot disarm + evidence invalidated; a valid journal unlocks nothing",
      not gate_bad, str(gate_bad[:3]))
drift_bad = []
for j in ((7, 0), None):
    for reg, val in ((232, 0x0030), (270, 55), (244, 2)):
        dev = boot("IIIO", j)
        eid = h.review(dev)
        dev.bank[reg] = val  # the inverter changes between Review and the confirm-time re-read
        bank = dict(dev.bank)
        dev.ent("free_power_recovery_arm").state = True
        run = h.audited(dev, lambda d=dev, e=eid: h.api_execute(d, REAL, FORCE_ACTION, e, "FORCE RESTORE ORIGINAL " + e))
        if not (run.writes == [] and run.commits == [] and dev.bank == bank and h.nvs_marker(dev) == RR
                and run.op_seq == h.FORCE_OPS[:3] and not dev.g["free_power_operation_in_progress"]):
            drift_bad.append((j, reg, run.op_seq))
check("[Q6] fingerprint gate: live 232 / 270 / 244 changed between Review and Force -> the fresh confirm-time "
      "fingerprint mismatches, Force stops after its three confirm reads with ZERO writes and zero commits "
      "(journal present or absent)", not drift_bad, str(drift_bad[:3]))
fault_bad, fault_n = [], 0
for idx, op in enumerate(h.FORCE_OPS):
    for outcome in (h.READ_FAILS if op[0] == "read" else h.WRITE_FAILS):
        fault_n += 1
        dev = boot("IIIO", (7, 0))
        run, _eid = h.operator_action(dev, REAL, FORCE_ACTION, fail={idx: outcome})
        cleared = h.nvs_marker(dev) == CLEAR
        if cleared and not (h.all_original(dev, SNAP_ORIG) and run.ops[-1][:2] == ("read", 256) and run.ops[-1][3] == "ok"):
            fault_bad.append((idx, outcome, "cleared without verified ORIGINAL"))
        if not cleared and (h.nvs_marker(dev) != RR or not dev.g["free_power_snapshot_valid"]):
            fault_bad.append((idx, outcome, "obligation changed without a clear"))
        if run.violations or dev.g["free_power_operation_in_progress"] or dev.g["manual_write_in_progress"]:
            fault_bad.append((idx, outcome, run.violations[:1]))
check(f"[Q7] Force fault sweep ({fault_n} runs: every Force op x its failure outcomes, incl. acknowledged-but-not-"
      "applied writes): the marker clears ONLY after a successful final verify with every owned register "
      "ORIGINAL; any other outcome keeps RESTORE_REQUIRED; locks always released; never START, never "
      "active_persisted, never a non-ORIGINAL write", not fault_bad, str(fault_bad[:3]))
check("[Q8] Force never commits the journal or the snapshot data record, and never resumes START "
      "(audited on every Force run above)", not force_bad and not fault_bad)

# ===========================================================================
print("")
print("[4] Accept Current State - executed as real firmware; refuses every SELF_PARTIAL state")
# ===========================================================================
acc_bad, acc_n, acc_diverge = [], 0, []
for combo, mask in SP_CASES:
    snap, live = h.scenario(combo)
    traces = {}
    for label, variant in JOURNAL_VARIANTS:
        dev = boot_variant(snap, live, mask, variant)
        bank = dict(dev.bank)
        op_needed = dev.g["free_power_operator_needed"]
        run, eid = h.operator_action(dev, REAL, ACCEPT_ACTION)
        acc_n += 1
        traces[label] = h.trace(run)
        if not (refused_untouched(run, bank) and run.op_seq == h.ACCEPT_OPS
                and status(dev).startswith("ACCEPT REFUSED - Free Power residue: ")
                and dev.g["free_power_operator_needed"] == op_needed and not run.violations):
            acc_bad.append((h.row_of(combo), mask, label, status(dev)[:50]))
    dev = boot_variant(snap, live, mask, "mask")
    dev.g["free_power_live_self_partial"] = True
    run, _eid = h.operator_action(dev, REAL, ACCEPT_ACTION)
    traces["stale SELF_PARTIAL flag"] = h.trace(run)
    if len(set(traces.values())) != 1:
        acc_diverge.append((h.row_of(combo), mask))
check(f"[R1] Accept refuses EVERY legal SELF_PARTIAL state ({len(SP_CASES)} block-state/mask cases - START rows "
      f"I O O O / I I O O / I I I O, interrupted-restore rows O I I O / O I O O / O I I I, every BOTH degeneracy - "
      f"x {len(JOURNAL_VARIANTS)} journal variants = {acc_n} runs): residue refusal after its three confirm "
      "reads, ZERO writes, ZERO durable commits, marker RESTORE_REQUIRED, snapshot valid, operator_needed unchanged",
      not acc_bad and acc_n == len(SP_CASES) * len(JOURNAL_VARIANTS), str(acc_bad[:3]))
check("[R2] Accept never trusts journal ownership: its whole trace is IDENTICAL with the journal as recorded, "
      "absent, START_VERIFIED, unbound or illegal, and with the SELF_PARTIAL RAM flag stale-set",
      not acc_diverge, str(acc_diverge[:4]))
_sp_rows = {h.row_of(c) for c, _m in SP_CASES}
check("[R1] ...the enumeration covers every START-interruption row, every interrupted-restore row and BOTH "
      "degeneracies (e.g. B I O B, I B O O, O I B O)",
      {"IOOO", "IIOO", "IIIO", "OIIO", "OIOO", "OIII", "BIOB", "IBOO", "OIBO"} <= _sp_rows, str(sorted(_sp_rows)[:8]))
_res_bad = [h.row_of(c) for c, m in SP_CASES
            if not fpre.free_power_residue_registers(originals=h.originals_of(h.scenario(c)[0]),
                                                     intended=h.intended_of(h.scenario(c)[0]), live=h.scenario(c)[1])]
check("[R3] why: every SELF_PARTIAL state has at least one I_ONLY block, so at least one register with "
      "live == INTENDED != ORIGINAL - Accept's unchanged residue scan always fires", not _res_bad, str(_res_bad[:3]))
for row, want in (("OOOO", "ACCEPT REFUSED - state is ORIGINAL, not NEITHER"),
                  ("BBBB", "ACCEPT REFUSED - state is INTENDED, not NEITHER"),
                  ("IIII", "ACCEPT REFUSED - state is INTENDED, not NEITHER")):
    snap = h.make_snapshot({b: True for b in fsp.BLOCKS}) if row == "BBBB" else SNAP
    for j in ((15, 0), None, (15, VERIFIED)):
        dev = boot(row, j, snap=snap)
        bank = dict(dev.bank)
        run, _eid = h.operator_action(dev, REAL, ACCEPT_ACTION)
        check(f"[R4] Accept refuses {row} (journal {j}): '{want[16:]}', zero writes, zero commits, obligation kept",
              refused_untouched(run, bank) and status(dev).startswith(want), status(dev))
# Positive control - Accept's success path is reachable in this harness, so the refusals above are meaningful.
for j in ((15, 0), None, (7, 0)):
    dev = boot("XOOO", j)
    run, _eid = h.operator_action(dev, REAL, ACCEPT_ACTION)
    check(f"[R5] positive control, journal {j}: a genuine third-party NEITHER state with no Free Power residue "
          "(232 changed by someone else) IS accepted - zero writes, marker CLEAR via PENDING_CLEAR, retry record "
          "cleaned; the outcome does not depend on the journal",
          run.writes == [] and h.nvs_marker(dev) == CLEAR and [c[1] for c in run.commits] == [VALID_KEY, VALID_KEY, RETRY_KEY]
          and status(dev).startswith("ACCEPT CURRENT STATE SUCCESS"))
corrupt_bad = []
for row in ("XOOO", "IIIO"):
    for j in ((7, 0), None):
        dev = boot(row, j)
        eid = h.review(dev)
        dev.g["free_power_recovery_metadata_corrupt"] = True
        bank = dict(dev.bank)
        dev.ent("free_power_recovery_arm").state = True
        run = h.audited(dev, lambda d=dev, e=eid: h.api_execute(d, REAL, ACCEPT_ACTION, e, "ACCEPT CURRENT STATE " + e))
        if not (refused_untouched(run, bank) and run.ops == [] and last_action(dev) == "refused: metadata untrustworthy"):
            corrupt_bad.append((row, j, last_action(dev)))
check("[R6] Free Power Accept's corrupt-metadata gate (the Free Power counterpart of the #44 Dump gate): with "
      "metadata corrupt after a valid Review, Accept refuses before any Modbus I/O - even for a residue-free "
      "NEITHER state it would otherwise accept, and whatever the journal says", not corrupt_bad, str(corrupt_bad))
_dump_accept = fpsim._strip_code(BODIES["dump_accept_current_state"])
check("[R6] #44: dump_accept_current_state still refuses while dump_recovery_metadata_corrupt (byte-identical to "
      "6c62417, pinned in [2]; behaviour covered by test_dump_accept_corrupt_metadata_gate.py)",
      "dump_recovery_metadata_corrupt" in _dump_accept)
_ad = fpsim.flatten(REAL.scripts[ACCEPT_DISPATCH]["then"]) + fpsim.flatten(REAL.scripts[ACCEPT]["then"])
check("[R7] Accept has ZERO Modbus writes and never assigns a snapshot field, the journal, active_persisted=true "
      "or SELF_PARTIAL",
      not any(k == fpsim.WRITE for k, _g, _b in _ad)
      and not re.search(r"id\((free_power_snapshot_reg\d+|free_power_start_journal_\w+|free_power_live_self_partial)\)\s*=(?!=)",
                        BODIES[ACCEPT_DISPATCH] + BODIES[ACCEPT])
      and "id(free_power_active_persisted) = true" not in BODIES[ACCEPT_DISPATCH])

# ===========================================================================
print("")
print("[5] SELF_PARTIAL safety pins - the classifier's exact guard sequence (static) and real-firmware probes")
# ===========================================================================
GUARDS = h.classifier_guards(REAL)
EXPECTED_GUARD_SEQUENCE = [
    "id(free_power_live_self_partial) = false;",
    "if (id(free_power_write_failed) || !id(free_power_live_read_ok)) return;",
    "if (id(free_power_live_owned_matches) || id(free_power_live_matches_intended)) return;",
    "if ((!b1_o && !b1_i) || (!b2_o && !b2_i) || (!b3_o && !b3_i) || (!b4_o && !b4_i)) return;",
    "if (id(free_power_marker_state) != ecco_durable::MARKER_RESTORE_REQUIRED) return;",
    "if (!id(free_power_snapshot_valid) || id(free_power_recovery_metadata_corrupt)) return;",
    "if (!id(free_power_start_journal_valid)) return;",
    "if (!ecco_durable::free_power_start_journal_valid(ram_journal, ecco_durable::free_power_start_journal_binding(bound))) return;",
    "if ((id(free_power_start_journal_flags) & ecco_durable::FREE_POWER_START_JOURNAL_FLAG_START_VERIFIED) != 0) return;",
    "if (b1_i && !b1_o && (attempted & 0x01) == 0) return;",
    "if (b2_i && !b2_o && (attempted & 0x02) == 0) return;",
    "if (b3_i && !b3_o && (attempted & 0x04) == 0) return;",
    "if (b4_i && !b4_o && (attempted & 0x08) == 0) return;",
    "if (b4_i && !b4_o && b3_o && !b3_i) return;",
    "id(free_power_live_self_partial) = true;",
]
_seq = [g for g in GUARDS if g.startswith(("if (", "id(free_power_live_self_partial)"))]
check("[S0] the classifier's guard sequence is EXACTLY rules 0,1/2,3,4,5,6,6b(binding+schema),7,8x4,9 then the one "
      "SELF_PARTIAL assignment - in this order, nothing inserted, removed or reordered",
      _seq == EXPECTED_GUARD_SEQUENCE, str([g for g in _seq if g not in EXPECTED_GUARD_SEQUENCE][:3]))
check("[S0] the binding recomputation feeds EVERY FreePowerSnapshotData field on_boot binds (same field set as the "
      "journal load), and the RAM journal is rebuilt with reserved = 0 and the real magic",
      sorted(re.findall(r"bound\.(\w+) =", " ".join(GUARDS))) == sorted(re.findall(r"bound\.(\w+) =", fpsim._strip_code(BOOT[_js:_je])))
      and "ecco_durable::FREE_POWER_START_JOURNAL_MAGIC, id(free_power_start_journal_mask), id(free_power_start_journal_flags), 0, id(free_power_start_journal_binding)}" in " ".join(GUARDS))
_sp_code = fpsim._strip_code(h.classifier_lambda(REAL))
check("[S0] the classifier performs no Modbus, no durable commit/load, no script execution and assigns only "
      "free_power_live_self_partial",
      not re.search(r"modbus|commit_record|load_record|\.execute\(", _sp_code)
      and set(re.findall(r"id\((\w+)\)\s*=(?!=)", _sp_code)) == {"free_power_live_self_partial"})

GOOD = (True, 7, 0, True)


def probe(row, *, journal=GOOD, snap=SNAP, **kw):
    st, wg, ng = h.fw_probe(REAL, snap, h.live_for(h.states_of_row(row), snap), journal=journal, **kw)
    return h.fw_class(st), wg, ng, st


def is_neither(p) -> bool:
    cls, wg, ng, st = p
    return cls == NEITHER and ng and not wg and not st["free_power_live_self_partial"]


def is_sp(p) -> bool:
    cls, wg, ng, st = p
    return cls == SELF_PARTIAL and wg and not ng and st["free_power_live_self_partial"]


check("[S1] baseline: I I I O with a valid bound mask-7 journal, marker RR, trusted snapshot -> SELF_PARTIAL, "
      "write gate only", is_sp(probe("IIIO")))
check("[S1] marker must be RESTORE_REQUIRED (CLEAR / PENDING_CLEAR -> NEITHER)",
      is_neither(probe("IIIO", marker=CLEAR)) and is_neither(probe("IIIO", marker=PENDING)))
check("[S2] snapshot must be trusted (free_power_snapshot_valid false -> NEITHER)", is_neither(probe("IIIO", snapshot_valid=False)))
check("[S3] metadata must not be corrupt (-> NEITHER)", is_neither(probe("IIIO", corrupt=True)))
check("[S4] journal must be valid (absent / RAM valid=false with otherwise perfect fields -> NEITHER)",
      is_neither(probe("IIIO", journal=None)) and is_neither(probe("IIIO", journal=(False, 7, 0, True))))
check("[S4] journal schema re-checked in RAM (illegal masks 2/5/9/14, unknown flag 0x02 -> NEITHER)",
      all(is_neither(probe("IIIO", journal=(True, m, f, True))) for m, f in ((2, 0), (5, 0), (9, 0), (14, 0), (15, 0x02))))
check("[S5] binding must match the snapshot restored NOW (unbound -> NEITHER)", is_neither(probe("IIIO", journal=(True, 7, 0, False))))
check("[S6] START_VERIFIED mixed state stays NEITHER (v1-narrow), for every mixed START/restore row",
      all(is_neither(probe(r, journal=(True, 15, VERIFIED, True))) for r in ("IOOO", "IIOO", "IIIO", "OIIO", "OIOO", "OIII")))
check("[S7] an I_ONLY block requires its own attempt bit (each block, the largest valid prefix mask lacking it)",
      all(is_neither(probe(r, journal=(True, m, 0, True))) for r, m in (("IOOO", 0), ("OIOO", 1), ("OOIO", 3), ("OIII", 7))))
_mix = []
for base, reg in (("IIIO", 268), ("IIIO", 279), ("IIII", 256), ("IIII", 261)):
    st, wg, ng = h.fw_probe(REAL, SNAP, {**h.live_for(h.states_of_row(base), SNAP), reg: 0x7E7E}, journal=(True, 15, 0, True))
    _mix.append(is_neither((h.fw_class(st), wg, ng, st)))
check("[S8] B3 / B4 internal mixtures are X -> NEITHER even with the best journal (first/last register of each)",
      all(_mix) and len(_mix) == 4)
check("[S8] single-register blocks B1/B2 holding a third value are X -> NEITHER",
      is_neither(probe("XIIO", journal=(True, 15, 0, True))) and is_neither(probe("IXIO", journal=(True, 15, 0, True))))
check("[S9] B4 I_ONLY while B3 O_ONLY stays NEITHER (never a raised ceiling over original floors)",
      is_neither(probe("IIOI", journal=(True, 15, 0, True))) and is_neither(probe("OOOI", journal=(True, 15, 0, True))))
_ai = [probe("IIII", journal=j) for j in (None, (False, 0, 0, False), (True, 1, 0, False), (True, 15, VERIFIED, True))]
check("[S10] ALL INTENDED does not require a journal (absent / invalid / unbound / verified -> INTENDED, write gate)",
      all(c == INTENDED and wg and not ng and not st["free_power_live_self_partial"] for c, wg, ng, st in _ai))
_ao = [probe(r, journal=j, snap=h.make_snapshot({b: True for b in fsp.BLOCKS}) if r == "BBBB" else h.make_snapshot({B1: True, B3: True}))
       for r in ("BBBB", "BOBO") for j in (None, (True, 15, 0, True))]
check("[S11] ORIGINAL precedence unchanged: all-BOTH and BOTH/O mixes are ORIGINAL (no write gate, no lockout, "
      "SELF_PARTIAL false) with or without a journal",
      all(c == ORIGINAL and not wg and not ng and not st["free_power_live_self_partial"] for c, wg, ng, st in _ao))
dev = boot("IIIO", (7, 0))
run = h.restore(dev)
_stale_ok = run.cls == SELF_PARTIAL and completed(run) and dev.g["free_power_start_journal_valid"]
_stale_bad = []
for marker in (CLEAR, PENDING):
    dev.g.update({"free_power_snapshot_valid": True, "free_power_end_epoch": SNAP["end_epoch"],
                  "free_power_marker_state": marker, "free_power_write_failed": False,
                  "free_power_operation_in_progress": False, "manual_write_in_progress": False,
                  "free_power_operator_needed": False})
    dev.bank = h.bank_for_row("IIIO")
    bank = dict(dev.bank)
    e0 = len(dev.modbus_log)
    dev.execute(DISPATCH)
    if dev.g["free_power_live_self_partial"] or any(k == "write" for k, *_r in dev.modbus_log[e0:]) or dev.bank != bank:
        _stale_bad.append(marker)
check("[S12] stale valid journal RAM after a marker CLEAR cannot grant SELF_PARTIAL (the RAM mirror stays valid "
      "after a completed restore; a dispatch with marker CLEAR / PENDING_CLEAR refuses it, zero writes)",
      _stale_ok and not _stale_bad, str(_stale_bad))
_on = [h.restore(boot(r, j, operator_needed=1)) for r, j in (("IIIO", (7, 0)), ("IOOO", (1, 0)), ("OIIO", (15, 0)))]
check("[S13] SELF_PARTIAL never bypasses operator_needed: durable lockout + valid journal -> ZERO Modbus ops",
      all(r.ops == [] and not r.dispatched for r in _on))
r1 = h.restore(boot("IIIO", (7, 0), reg244=2))
r2 = h.restore(boot("IIIO", (7, 0)), read_override=lambda a, c, v: [2] if (a, c) == (244, 1) else v)
r3 = h.restore(boot("IIIO", (7, 0), snap=dict(SNAP, reg244_lease_context_plus1=0)))
check("[S14] SELF_PARTIAL never bypasses the FIRST reg244 context gate (pre-write 244x12 mismatch -> context hold, "
      "ZERO writes, durable lockout) nor an UNKNOWN lease context (zero writes)",
      r1.cls == SELF_PARTIAL and r1.writes == [] and r1.sim.g["free_power_context_hold"] and h.nvs_operator_needed(r1.sim) == 1
      and r3.cls == SELF_PARTIAL and r3.writes == [] and r3.sim.g["free_power_context_hold"])
check("[S15] SELF_PARTIAL never bypasses the SECOND reg244 context gate (244 changes before the floors -> only "
      "232 and 256-261 written, 268-279/230 withheld, context hold)",
      r2.writes == [232, 256] and r2.sim.g["free_power_context_hold"] and all(r2.sim.bank[268 + i] == 100 for i in range(6)))
_legal = [h.restore(boot(r, (m, 0))) for r, m in (("IOOO", 1), ("IIOO", 3), ("IIIO", 7), ("IIIO", 15), ("OIIO", 7),
                                                   ("OIOO", 15), ("OIII", 15))]
check("[S16] SELF_PARTIAL never resumes START and never writes intended values: every legal row restores through "
      "the existing restore order with ORIGINAL values only, no START execution, no active_persisted, no "
      "journal/data commit (audited)",
      all(r.cls == SELF_PARTIAL and r.op_seq == h.RESTORE_OPS and completed(r) and not r.violations for r in _legal),
      str([(r.cls, r.violations[:1]) for r in _legal if r.violations or r.cls != SELF_PARTIAL][:2]))
_recovery_ids = (WRAPPER, DISPATCH, FORCE, FORCE_DISPATCH, ACCEPT, ACCEPT_DISPATCH, h.REVIEW,
                 "free_power_recovery_review_dispatch", "free_power_recovery_invalidate_evidence")
_exec_targets, _lambda_code = set(), []
for _sid in _recovery_ids:
    for _k, _g, _b in fpsim.flatten(REAL.scripts[_sid]["then"]):
        if _k == "script.execute":
            _exec_targets.add(_b if isinstance(_b, str) else _b["id"])
    _lambda_code.extend(fpsim._strip_code(c) for c in _lambdas(REAL.scripts[_sid]["then"]))  # incl. Modbus handlers
check("[S16] statically (parsed action trees): no recovery script (restore, Force, Accept, Review) executes START, "
      "and none of their lambdas assigns active_persisted = true or calls START",
      START not in _exec_targets and _lambda_code
      and not any(re.search(r"id\(free_power_active_persisted\)\s*=\s*true|start_free_power_override", c) for c in _lambda_code)
      and not any(re.search(r"id\(free_power_active_persisted\)\s*=\s*true", fpsim._strip_code(BODIES[s])) for s in _recovery_ids),
      str(sorted(_exec_targets)))
_mc = []
for idx, outcome in ((3, "error"), (4, "ack_not_applied"), (7, "ack_not_applied"), (8, "ack_not_applied"),
                     (9, "error"), (10, "timeout"), (5, "error"), (6, "no_response")):
    dev = boot("IIIO", (7, 0))
    run = h.restore(dev, fail={idx: outcome})
    if h.nvs_marker(dev) == CLEAR and not h.all_original(dev, SNAP_ORIG):
        _mc.append((idx, outcome))
    if h.nvs_marker(dev) != CLEAR and (h.nvs_marker(dev) != RR or any(e[1] == VALID_KEY for e in run.commits)):
        _mc.append((idx, outcome, "marker moved"))
check("[S17] the marker clears only after verified ORIGINAL: failures at every restore stage keep "
      "RESTORE_REQUIRED with no marker commit at all", not _mc, str(_mc))

# ===========================================================================
print("")
print("[6] write-surface proof - identical to main before SG-01")
# ===========================================================================
WS = aws.analyze(h.FIRMWARE_PATH)
paths = WS["paths"]
surface = aws.write_surface(paths)
per_path = {p.name: [(o.kind, o.start_address, o.count) for o in p.ops] for p in paths}
# FB-T0: the count / hash pins use the analyzer run on the firmware AS OF chain entry "dump_v2" (see [2]); the property
# checks that follow keep using the LIVE analysis (WS / paths / surface / per_path above).
SCOPE_WS = chain.CHAIN.analyze_as_of("dump_v2", FW_TEXT)
scope_paths = SCOPE_WS["paths"]
scope_surface = aws.write_surface(scope_paths)
scope_per_path = {p.name: [(o.kind, o.start_address, o.count) for o in p.ops] for p in scope_paths}
n_w, n_r = h.count_actions(SCOPE_FW, fpsim.WRITE), h.count_actions(SCOPE_FW, fpsim.READ)
check("Modbus writes: 52, reads: 60 (action tree) - and the analyzer sees the same 52 write / 60 read ops",
      (n_w, n_r) == (52, 60)
      and sum(1 for p in scope_paths for o in p.ops if o.kind == "write") == 52
      and sum(1 for p in scope_paths for o in p.ops if o.kind == "read") == 60, f"{n_w}/{n_r}")
check("register -> writers map identical to 6c62417 (pinned hash)",
      sha(json.dumps({str(k): v for k, v in scope_surface.items()}, sort_keys=True))
      == "70036acf5e1855e8bd07dbadec090c8a55be4aac7f94373bd342fd49c52699d3")
check("every path's ordered Modbus op list identical to 6c62417 (pinned hash; the restore dispatch included - the "
      "SELF_PARTIAL classifier added no op)",
      sha(json.dumps(scope_per_path, sort_keys=True)) == "16d3f2d61b8deb4c4536b7b2e4ad046a558fba4979db576a0d2c45d66f71da7f")
check("written register set unchanged: 22-24, 230, 232, 244, 250-261, 268-279",
      set(surface) == {22, 23, 24, 230, 232, 244, *range(250, 262), *range(268, 280)})
check("no new register-244 writer (exactly the five pre-SG-01 writers)",
      surface[244] == ["apply_reg244_settings", "dump_lockout_containment", "restore_dump_to_grid_snapshot",
                       "restore_reg244_snapshot", "start_dump_to_grid_override"])
check("no new Free Power writer: 230 is written only by START, the automatic restore and Force",
      surface[230] == ["free_power_recovery_force_restore_dispatch", "restore_free_power_snapshot_dispatch",
                       "start_free_power_override"])
check("no new Dump writer: 256-261 writers are exactly the pre-SG-01 set",
      all(surface[r] == sorted([f"apply_manual_slot{r - 255}", "dump_controller_tick", "free_power_recovery_force_restore_dispatch",
                                "restore_dump_to_grid_snapshot", "restore_free_power_snapshot_dispatch",
                                "start_dump_to_grid_override", "start_free_power_override"]) for r in range(256, 262)))
check("no new unguarded writer (only the pre-existing RTC path outside the write mutex)",
      aws.unguarded_write_paths(paths) == [{"script": "write_inverter_rtc", "reason": "never sets manual_write_in_progress"}])
check("no hidden Modbus access anywhere: zero unknown-extent writes and zero bus-access findings (raw C++ bus/UART "
      "calls, ModbusCommandItem/queue_command, uart.write, modbus_controller) across the whole YAML and includes",
      WS["unknown_extent_writes"] == [] and WS["bus_access_findings"] == [])
check("Review and Accept remain read-only; the classifier lambda contains no bus access",
      not per_path.get(ACCEPT_DISPATCH) or all(k == "read" for k, *_r in per_path[ACCEPT_DISPATCH])
      and all(k == "read" for k, *_r in per_path.get("free_power_recovery_review_dispatch", []))
      and not re.search(r"modbus|->send|write_multiple|queue_command", _sp_code))

# ===========================================================================
print("")
print("[7] durable-schema proof - Phase 5 adds no durable change")
# ===========================================================================
check("durable surface: 55 + 2 commit_record (Dump V2: controller evidence commit, START V1 tombstone) / 9 + 1 "
      "load call sites (6 load_record + Dump V2's legacy-V1 probe + SG-06's 3 marker load_record_status), 9 "
      "_TAG-suffixed tags - unchanged since Phase 1/2 apart from SG-06's marker loads and Dump V2's additions",
      (len(re.findall(r"ecco_durable::commit_record\s*\(", SCOPE_FW_TEXT)), len(re.findall(r"ecco_durable::load_record\s*\(", SCOPE_FW_TEXT)),
       len(re.findall(r"ecco_durable::load_record_status\s*\(", SCOPE_FW_TEXT)),
       len(set(re.findall(r"ecco_durable::([A-Za-z0-9_]+_TAG)\b", SCOPE_FW_TEXT)))) == (55 + 2, 6 + 1, 3, 9)
      and len(re.findall(r"constexpr const char \*([A-Z0-9_]+_TAG) = ", SCOPE_HEADER)) == 9)
_jc = {sid: len(re.findall(r"commit_record\(\s*ecco_durable::key_for\(ecco_durable::FREE_POWER_START_JOURNAL_TAG", b))
       for sid, b in BODIES.items()}
check("the journal is committed ONLY by start_free_power_override (5 sites) and loaded ONLY by on_boot (1) - no "
      "recovery path commits it",
      {k: v for k, v in _jc.items() if v} == {START: 5}
      and len(re.findall(r"load_record\(\s*ecco_durable::key_for\(ecco_durable::FREE_POWER_START_JOURNAL_TAG", BOOT)) == 1
      and len(re.findall(r"load_record\(\s*ecco_durable::key_for\(ecco_durable::FREE_POWER_START_JOURNAL_TAG", FW_TEXT)) == 1)
check("durable header pinned (byte-identical to main @ 2d73eb2 once SG-06's and Dump V2's own edits are reverted)",
      sha(sg06.pre_sg06_header(dv2s.pre_dump_v2_header(SCOPE_HEADER))) == "85df3dc7f371c8488935ca958d3fe2943478e7952a9886b1caf57846a39a2f8d")
check("journal tag is exactly ecco_free_power_start_journal_v1 (header and Python mirror)",
      'constexpr const char *FREE_POWER_START_JOURNAL_TAG = "ecco_free_power_start_journal_v1";' in HEADER
      and jm.JOURNAL_TAG == "ecco_free_power_start_journal_v1")
check("journal sizeof is 16 and offsets are magic 0 / start_attempted 4 / flags 5 / reserved 6 / binding 8 "
      "(compile-time static_asserts present; Python pack layout agrees)",
      "static_assert(sizeof(FreePowerStartJournal) == 16" in HEADER
      and "offsetof(FreePowerStartJournal, magic) == 0 && offsetof(FreePowerStartJournal, start_attempted) == 4" in HEADER
      and "offsetof(FreePowerStartJournal, flags) == 5 && offsetof(FreePowerStartJournal, reserved) == 6" in HEADER
      and "offsetof(FreePowerStartJournal, binding) == 8" in HEADER and jm.JOURNAL_SIZE == 16
      and len(jm.pack_journal(h.rec(jm.JOURNAL_KIND, magic=jm.JOURNAL_MAGIC, start_attempted=7, flags=0, reserved=0,
                                    binding=0x1122334455667788))) == 16)
_dom = re.search(r'FREE_POWER_START_JOURNAL_BINDING_DOMAIN\[\] = "([^"]*)"', HEADER)
check("binding domain unchanged ('ECCO-FP-START-JOURNAL-v1', 24 bytes, NUL-free, static_assert present) and "
      "binding golden vector unchanged",
      _dom is not None and _dom.group(1) == "ECCO-FP-START-JOURNAL-v1" and "\x00" not in _dom.group(1)
      and 'sizeof(FREE_POWER_START_JOURNAL_BINDING_DOMAIN) - 1 == 24' in HEADER
      and "free_power_start_journal_binding(FreePowerSnapshotData{}) == 0x9752C546FF6459E7ULL" in HEADER)
check("valid start_attempted masks unchanged: exactly 0, 1, 3, 7, 15 (header, journal model, SELF_PARTIAL model)",
      [m for m in range(256) if D.free_power_start_journal_mask_valid(m)] == [0, 1, 3, 7, 15]
      == list(jm.JOURNAL_VALID_START_ATTEMPTED_MASKS) == list(fsp.VALID_START_ATTEMPTED_MASKS)
      and "mask == 0 || mask == FREE_POWER_START_JOURNAL_MASK_B1 || mask == FREE_POWER_START_JOURNAL_MASK_B2 ||" in HEADER)
_vj = lambda **f: jm.journal_valid(h.rec(jm.JOURNAL_KIND, **{"magic": jm.JOURNAL_MAGIC, "start_attempted": 7, "flags": 0,  # noqa: E731
                                                              "reserved": 0, "binding": 5, **f}), 5)
check("reserved == 0 still required; START_VERIFIED still only valid with mask 15; unknown flags rejected",
      _vj() and not _vj(reserved=1) and not _vj(reserved=0x8000) and not _vj(flags=VERIFIED)
      and _vj(start_attempted=15, flags=VERIFIED) and not _vj(flags=0x02)
      and "j.reserved == 0 &&" in HEADER
      and "((j.flags & FREE_POWER_START_JOURNAL_FLAG_START_VERIFIED) == 0 ||\n          j.start_attempted == FREE_POWER_START_JOURNAL_MASK_B4)" in HEADER)
check("START_VERIFIED semantics unchanged: flag value 0x01, the only known flag, and the header still contains no "
      "SELF_PARTIAL / restore-attempt / v2 field",
      "FREE_POWER_START_JOURNAL_FLAG_START_VERIFIED = 0x01;" in HEADER
      and "FREE_POWER_START_JOURNAL_KNOWN_FLAGS = FREE_POWER_START_JOURNAL_FLAG_START_VERIFIED;" in HEADER
      and not re.search(r"self_?partial|restore_attempt|journal_v2", HEADER, re.I))

# ===========================================================================
print("")
print("[8] end-to-end regression scenarios A-J (whole-device lifecycles)")
# ===========================================================================
START_ORIGINAL = {**h.make_bank(h.live_for(h.states_of_row("OOOO"), SNAP))}
_fp_watchdogs = [iv["then"] for iv in FW["interval"]
                 if any(a.get("if", {}).get("then") == [{"script.execute": {"id": WRAPPER}}] for a in iv["then"])]
check("exactly one interval (the Free Power watchdog) executes restore_free_power_snapshot", len(_fp_watchdogs) == 1)
WATCHDOG = _fp_watchdogs[0]


def start_device(*, start_writes=None, start_reads=None, restore_fail=None, stub_restore=False):
    """A fresh device with no obligation; START's own Modbus outcomes by
    address/occurrence, and optionally the restore's by op index."""
    sim = ds.Sim(FW)
    h.env(sim)
    sim.bank = dict(START_ORIGINAL)
    if stub_restore:
        sim.scripts["restore_free_power_snapshot"] = {"then": []}
    sw, sr, rf = start_writes or {}, start_reads or {}, restore_fail or {}
    seen: dict = {}
    rn = [0]

    def outcome(kind, addr, count):
        if DISPATCH in sim.running:
            i = rn[0]
            rn[0] += 1
            return rf.get(i, "ok")
        if kind == "write":
            return sw.get(addr, "ok")
        seen[(addr, count)] = seen.get((addr, count), 0) + 1
        return sr.get(((addr, count), seen[(addr, count)]), "ok")

    sim.outcome_fn = outcome
    return sim


def capture_start(**kw):
    sim = start_device(stub_restore=True, **kw)
    caps: list = []
    sim.event_hook = lambda e: caps.append((e, {k: v.copy() for k, v in sim.nvs.items()}, dict(sim.bank)))
    sim.execute(START)
    sim.event_hook = None
    return sim, caps


def reboot(nvs, bank, *, full_boot=False):
    return h.boot_device(nvs, bank, REAL, full_boot=full_boot)


full, caps = capture_start()
S_SNAP = {k: getattr(full.nvs[DATA_KEY], k) for k in ds._RECORD_FIELDS["FreePowerSnapshotData"]}
S_ORIG, S_INT = h.originals_of(S_SNAP), h.intended_of(S_SNAP)

# A - clean START -> clean lease -> clean restore (lease end driven by the real watchdog interval)
a = start_device()
a.execute(START)
a_verified = h.journal_of(a.nvs) == (15, VERIFIED) and a.g["free_power_active_persisted"] and a.bank[230] == S_INT[230]
a.epoch = S_SNAP["end_epoch"] - 60
a.run_actions(WATCHDOG)
a_early = [k for k, *_r in a.modbus_log].count("write")
a.epoch = S_SNAP["end_epoch"]
e0 = len(a.modbus_log)
a.run_actions(WATCHDOG)
a_ops = [(k, ad) if k == "write" else (k, ad, len(v)) for k, ad, v, _o in a.modbus_log[e0:]]
check("[A] clean START (journal 15 + START_VERIFIED, active) -> the real watchdog does nothing before end_epoch -> "
      "at end_epoch it runs the INTENDED restore in the pinned order, ORIGINAL verified, marker CLEAR, no lockout; "
      "the journal record is left as inert evidence",
      a_verified and a_early == 4 and a_ops == h.RESTORE_OPS and h.all_original(a, S_ORIG) and h.nvs_marker(a) == CLEAR
      and not a.g["free_power_operator_needed"] and h.journal_of(a.nvs) == (15, VERIFIED),
      f"{a_verified} {a_early} {a_ops}")


def cut_at(pred, occurrence=1):
    n = 0
    for e, nvs, bank in caps:
        if pred(e):
            n += 1
            if n == occurrence:
                return nvs, bank
    raise KeyError("event not found")


def journal_commit(mask):
    return lambda e: e[0] == "commit" and e[1] == JKEY and e[3] and e[2].start_attempted == mask and e[2].flags == 0


def write_of(addr):
    return lambda e: e[0] == "write" and e[1] == addr


BOUNDARY = [  # (label, event, expected row, journal, expected class)
    ("B", "B1 journal committed (mask 1), before the 232 write", journal_commit(1), "OOOO", (1, 0), ORIGINAL),
    ("B", "B1 journal committed, 232 write landed, power lost", write_of(232), "IOOO", (1, 0), SELF_PARTIAL),
    ("C", "B2 journal committed (mask 3), before the 230 write", journal_commit(3), "IOOO", (3, 0), SELF_PARTIAL),
    ("C", "B2 230 write landed, power lost", write_of(230), "IIOO", (3, 0), SELF_PARTIAL),
    ("D", "B3 journal committed (mask 7), before the 268-279 write", journal_commit(7), "IIOO", (7, 0), SELF_PARTIAL),
    ("D", "B3 268-279 write landed, power lost", write_of(268), "IIIO", (7, 0), SELF_PARTIAL),
    ("E", "B4 journal committed (mask 15), before the 256-261 write", journal_commit(15), "IIIO", (15, 0), SELF_PARTIAL),
    ("E", "B4 256-261 write landed, power lost (before START_VERIFIED)", write_of(256), "IIII", (15, 0), INTENDED),
]
for letter, label, pred, row, journal, want in BOUNDARY:
    nvs, bank = cut_at(pred)
    dev = reboot(nvs, bank)
    got_row = h.row_of(fsp.classify_blocks(originals=S_ORIG, intended=S_INT, live=bank))
    run = h.restore(dev)
    ops_ok = run.op_seq == (h.SKIP_OPS if want == ORIGINAL else h.RESTORE_OPS)
    check(f"[{letter}] {label} -> reboot: row {row}, journal {journal} -> {want} -> restored ORIGINAL, marker CLEAR, "
          "no lockout",
          got_row == row and h.journal_of(nvs) == journal and run.cls == want and ops_ok and completed(run, S_ORIG)
          and not run.violations and dev.g["free_power_start_journal_valid"],
          f"row={got_row} j={h.journal_of(nvs)} cls={run.cls}")
# Interrupted power cut mid-restore after a boundary interruption: the retry is still SELF_PARTIAL.
nvs, bank = cut_at(write_of(268))
first = reboot(nvs, bank)
rc: list = []
h.restore(first, hook=lambda e: rc.append((e, {k: v.copy() for k, v in first.nvs.items()}, dict(first.bank))))
_nested = []
for e, nvs2, bank2 in rc:
    d2 = reboot(nvs2, bank2)
    r2 = h.restore(d2)
    _nested.append((h.row_of(fsp.classify_blocks(originals=S_ORIG, intended=S_INT, live=bank2)), r2.cls,
                    h.all_original(d2, S_ORIG) and h.nvs_marker(d2) in (None, CLEAR) and not d2.g["free_power_operator_needed"]))
check("[D] ...and a second power cut after EVERY event of that SELF_PARTIAL restore still recovers on the next "
      "boot (O I I O / O I O O are SELF_PARTIAL, never a lockout)",
      all(ok for _r, _c, ok in _nested) and ("OIIO", SELF_PARTIAL, True) in _nested and ("OIOO", SELF_PARTIAL, True) in _nested,
      str(sorted({(r, str(c)) for r, c, _o in _nested})))

# F - failed START (activation verify fails -> not verified) followed by a partially failed restore
f = start_device(start_reads={((256, 24), 2): "error"}, restore_fail={7: "error"})
f.execute(START)
f_row = h.row_of(fsp.classify_blocks(originals=S_ORIG, intended=S_INT, live=f.bank))
f_state = (h.journal_of(f.nvs), f_row, h.nvs_marker(f), f.g["free_power_comms_restore_attempts"], f.g["free_power_operator_needed"])
f.advance(400_000)
f.outcome_fn = lambda kind, addr, count: "ok"
rf = h.restore(f)
check("[F] failed START (activation verify read error -> journal 15, NOT verified) whose own restore then fails at "
      "the B3 write leaves O I I O with RESTORE_REQUIRED and COMMS backoff (no lockout); the next attempt "
      "classifies it SELF_PARTIAL and completes",
      f_state == ((15, 0), "OIIO", RR, 1, False) and rf.cls == SELF_PARTIAL and completed(rf, S_ORIG) and not rf.violations,
      f"{f_state} -> {rf.cls}")
f2 = start_device(start_reads={((256, 24), 2): "error"}, restore_fail={7: "error"})
f2.execute(START)
d = reboot({k: v.copy() for k, v in f2.nvs.items()}, dict(f2.bank))
rf2 = h.restore(d)
check("[F] ...the same after a power cut + reboot in between (journal-backed SELF_PARTIAL from NVS)",
      rf2.cls == SELF_PARTIAL and completed(rf2, S_ORIG))

# G - verified lease followed by a partial restore
g = start_device(restore_fail={7: "error"})
g.execute(START)
g.epoch = S_SNAP["end_epoch"]
g.run_actions(WATCHDOG)
g_row = h.row_of(fsp.classify_blocks(originals=S_ORIG, intended=S_INT, live=g.bank))
gd = reboot({k: v.copy() for k, v in g.nvs.items()}, dict(g.bank))
g_bank = dict(gd.bank)
rg = h.restore(gd)
check("[G] verified lease (journal 15 + START_VERIFIED) whose lease-end restore fails at the B3 write -> O I I O; "
      "after reboot the v1-narrow rule makes it NEITHER: zero writes, durable operator lockout, obligation kept",
      h.journal_of(g.nvs) == (15, VERIFIED) and g_row == "OIIO" and rg.cls == NEITHER and locked_out_neither(rg, g_bank),
      f"{h.journal_of(g.nvs)} {g_row} {rg.cls}")
acc, _e = h.operator_action(gd, REAL, ACCEPT_ACTION)
check("[G] ...Accept Current State refuses it (Free Power residue), zero writes, lockout kept",
      acc.writes == [] and acc.commits == [] and h.nvs_marker(gd) == RR and h.nvs_operator_needed(gd) == 1
      and status(gd).startswith("ACCEPT REFUSED - Free Power residue"))
frc, _e = h.operator_action(gd, REAL, FORCE_ACTION)
check("[G] ...and Force Restore Original (the explicit operator recovery) restores ORIGINAL and clears marker + lockout",
      frc.op_seq == h.FORCE_OPS and completed(frc, S_ORIG) and not frc.violations)

# H - pre-SG-01 obligation: missing or malformed journal -> legacy behaviour, trace-identical to "no journal"
_js_sim = ds.Sim(FW)


def raw_journal(data: bytes):
    _js_sim.nvs_put_journal_bytes(JKEY, data)
    return _js_sim.nvs[JKEY]


GOOD_J = dict(magic=jm.JOURNAL_MAGIC, start_attempted=7, flags=0, reserved=0, binding=jm.journal_binding(SNAP))
MALFORMED = {
    "wrong magic": jm.pack_journal(h.rec(jm.JOURNAL_KIND, **{**GOOD_J, "magic": 0x4543534B})),
    "reserved != 0": jm.pack_journal(h.rec(jm.JOURNAL_KIND, **{**GOOD_J, "reserved": 1})),
    "illegal mask 5": jm.pack_journal(h.rec(jm.JOURNAL_KIND, **{**GOOD_J, "start_attempted": 5})),
    "unknown flag": jm.pack_journal(h.rec(jm.JOURNAL_KIND, **{**GOOD_J, "flags": 0x80})),
    "wrong binding": jm.pack_journal(h.rec(jm.JOURNAL_KIND, **{**GOOD_J, "binding": GOOD_J["binding"] ^ 1})),
    "wrong size (15 bytes)": b"\x00" * 15,
    "all 0xFF": b"\xff" * 16,
}
h_bad = []
for row in ("IIII", "OOOO", "IOOO", "IIIO", "OIIO"):
    base = reboot(h.nvs_image(SNAP, journal=None), h.bank_for_row(row))
    want = h.trace(h.restore(base))
    for label, data in MALFORMED.items():
        nvs = h.nvs_image(SNAP, journal=None)
        nvs[JKEY] = raw_journal(data)
        dev = reboot(nvs, h.bank_for_row(row))
        run = h.restore(dev)
        if h.trace(run) != want or dev.g["free_power_start_journal_valid"] or run.violations:
            h_bad.append((row, label))
check("[H] pre-SG-01 obligation (no journal) and 7 malformed journals (wrong magic / reserved / illegal mask / "
      "unknown flag / wrong binding / wrong size / erased flash) behave IDENTICALLY (whole trace) on I I I I, "
      "O O O O, I O O O, I I I O, O I I O: journal RAM invalid, legacy classification", not h_bad, str(h_bad[:4]))
hl = h.restore(reboot(h.nvs_image(SNAP, journal=None), h.bank_for_row("IIII")))
hn = h.restore(reboot(h.nvs_image(SNAP, journal=None), h.bank_for_row("IIIO")))
check("[H] ...legacy outcomes: all-INTENDED restores normally (INTENDED), mixed I I I O is the pre-SG-01 NEITHER "
      "operator lockout",
      hl.cls == INTENDED and completed(hl) and hn.cls == NEITHER and locked_out_neither(hn, h.bank_for_row("IIIO")))

# The journal is evidence, never an obligation of its own.
check("[H2] no interval, API action or other on_boot action references the journal (only START writes it, only the "
      "on_boot load block and the restore classifier read it)",
      not fpsim.mentions_journal(json.dumps(FW.get("interval"), default=str))
      and not fpsim.mentions_journal(json.dumps(FW["api"], default=str))
      and not fpsim.mentions_journal(BOOT[:_js] + BOOT[_je:]))
lo_bad = []
for label, nvs in (("marker CLEAR + old data record + bound journal",
                    {**h.nvs_image(SNAP, journal=(7, 0), marker=CLEAR)}),
                   ("journal record alone", {JKEY: h.rec(jm.JOURNAL_KIND, magic=jm.JOURNAL_MAGIC, start_attempted=15,
                                                          flags=0, reserved=0, binding=jm.journal_binding(SNAP))})):
    dev = reboot(nvs, h.bank_for_row("IIIO"), full_boot=True)
    e0 = len(dev.modbus_log)
    dev.run_actions(WATCHDOG)
    rr = h.restore(dev)
    h.review(dev)
    if (dev.g["free_power_snapshot_valid"] or dev.g["free_power_start_journal_valid"] or len(dev.modbus_log) != e0
            or rr.ops or dev.g["free_power_recovery_evidence_valid"] or any(e[0] == "commit" for e in dev.events)):
        lo_bad.append(label)
check("[H2] a journal record WITHOUT a RESTORE_REQUIRED obligation is inert: boot leaves the journal RAM invalid, "
      "the watchdog, the restore wrapper and Review perform ZERO Modbus I/O and ZERO commits", not lo_bad, str(lo_bad))
st = start_device()
st.nvs = {JKEY: h.rec(jm.JOURNAL_KIND, magic=jm.JOURNAL_MAGIC, start_attempted=15, flags=VERIFIED, reserved=0,
                      binding=jm.journal_binding(SNAP) ^ 0x5A)}
st.execute(START)
check("[H2] a stale journal left by an earlier lease never blocks a new START: it runs verified and its journal is "
      "rebound to the NEW snapshot",
      st.g["free_power_active_persisted"] and h.journal_of(st.nvs) == (15, VERIFIED)
      and st.nvs[JKEY].binding == jm.journal_binding(st.nvs[DATA_KEY]))

# I - corrupt recovery metadata: independent containment, SELF_PARTIAL never runs
ic_bad = []
for label, mutate_nvs in (("snapshot data record missing", lambda n: n.pop(DATA_KEY)),
                          ("malformed marker magic", lambda n: setattr(n[VALID_KEY], "magic", 0x12345678))):
    nvs = h.nvs_image(SNAP, journal=(7, 0))
    mutate_nvs(nvs)
    dev = reboot(nvs, h.bank_for_row("IIIO"), full_boot=True)
    bank = dict(dev.bank)
    run = h.restore(dev)
    fr, _e = h.operator_action(dev, REAL, FORCE_ACTION)
    ar, _e = h.operator_action(dev, REAL, ACCEPT_ACTION)
    if not (dev.g["free_power_recovery_metadata_corrupt"] and not dev.g["free_power_start_journal_valid"]
            and run.ops == [] and not dev.g["free_power_live_self_partial"] and fr.ops == [] and ar.ops == []
            and dev.bank == bank and h.nvs_marker(dev) == RR and "RECOVERY BLOCKED" in status(dev)):
        ic_bad.append((label, dev.g["free_power_recovery_metadata_corrupt"], run.op_seq[:2], status(dev)[:40]))
check("[I] Free Power metadata corrupt (data record missing / malformed marker) with a valid-looking journal in "
      "NVS: boot fails closed, the journal is NOT loaded, the automatic restore performs ZERO Modbus I/O "
      "('RECOVERY BLOCKED'), SELF_PARTIAL never evaluated, Force and Accept refuse before any Modbus I/O",
      not ic_bad, str(ic_bad))
DUMP_ORIG = {244: 2, 256: 8000, 257: 8000, 258: 7000, 259: 8000, 260: 8000, 261: 5000}
DUMP_WATCHDOG = ds.find_interval(FW, "dump_overpower_samples")


def dump_data():
    return ds.Record("DumpToGridSnapshotData", 0, 1, 0, DUMP_ORIG[244], *[DUMP_ORIG[r] for r in range(256, 262)], 1000)


def dump_env(sim):
    sim.ent("configuration_polling").state = True
    sim.ent("dump_write_enable").state = False
    sim.ent("dump_recovery_arm").state = False


def containment_run(fp_journal):
    """Dump obligation with an UNREADABLE data record (#46 containment case);
    Free Power has NO obligation (marker CLEAR) but a leftover journal record
    may or may not be in NVS."""
    nvs = {h.DUMP_VALID_KEY: h.rec("ValidMarker", magic=D.VALID_MARKER_MAGIC, state=RR)}
    if fp_journal:
        nvs[VALID_KEY] = h.rec("ValidMarker", magic=D.VALID_MARKER_MAGIC, state=CLEAR)
        nvs[JKEY] = h.rec(jm.JOURNAL_KIND, **GOOD_J)
    bank = {**h.bank_for_row("OOOO"), 244: 0}
    dev = reboot(nvs, bank, full_boot=True)
    dump_env(dev)
    e0 = len(dev.modbus_log)
    for _ in range(3):
        dev.advance(15_000)
        dev.run_actions(DUMP_WATCHDOG)
    return dev, dev.modbus_log[e0:]


c1, ops1 = containment_run(False)
c2, ops2 = containment_run(True)
check("[I] #46 Dump containment is independent of SG-01: Dump metadata corrupt (unreadable data) -> containment "
      "fresh-reads 244 and writes ONLY the literal 2 to 244, identically with or without a Free Power journal "
      "record in NVS; no Free Power register touched, Free Power journal RAM stays invalid",
      c1.g["dump_recovery_metadata_corrupt"] and [(k, a, v) for k, a, v, _o in ops1 if k == "write"] == [("write", 244, [2])]
      and ops1 == ops2 and c2.bank == c1.bank and not c2.g["free_power_start_journal_valid"]
      and all(c2.bank[r] == h.bank_for_row("OOOO")[r] for r in OWNED),
      f"{[(k, a, v) for k, a, v, _o in ops1]}")

# J - dual Free Power / Dump obligation: PR41 arbitration unchanged, SELF_PARTIAL cannot run
def dual_boot(fp_journal):
    nvs = h.nvs_image(SNAP, journal=(7, 0) if fp_journal else None)
    nvs[h.DUMP_VALID_KEY] = h.rec("ValidMarker", magic=D.VALID_MARKER_MAGIC, state=RR)
    nvs[h.DUMP_DATA_KEY] = dump_data()
    return reboot(nvs, h.bank_for_row("IIIO"), full_boot=True)


def boot_state(sim):
    return {k: v for k, v in sim.g.items() if not k.startswith("free_power_start_journal_")}


j1, j0 = dual_boot(True), dual_boot(False)
jb = dict(j1.bank)
jr = h.restore(j1)
jf, _e = h.operator_action(j1, REAL, FORCE_ACTION)
check("[J] dual Free Power + Dump RESTORE_REQUIRED obligation (legal SELF_PARTIAL I I I O on the Free Power side): "
      "the PR41 boot arbitration fails BOTH domains closed exactly as before - identical boot state with and "
      "without the journal - so the Free Power restore performs ZERO Modbus I/O, SELF_PARTIAL is never set, Force "
      "refuses, nothing is cleared",
      j1.g["free_power_recovery_metadata_corrupt"] and j1.g["dump_recovery_metadata_corrupt"]
      and boot_state(j0) == {k: v for k, v in boot_state(dual_boot(True)).items()}
      and jr.ops == [] and not j1.g["free_power_live_self_partial"] and jf.ops == [] and j1.bank == jb
      and h.nvs_marker(j1) == RR and j1.nvs[h.DUMP_VALID_KEY].state == RR)
check("[J] ...the classifier would ALSO refuse it on its own (rule 5: metadata corrupt), even with a valid journal "
      "RAM mirror", is_neither(probe("IIIO", corrupt=True)))
s4 = h.nvs_image(SNAP, journal=None, marker=CLEAR)
s4[h.DUMP_VALID_KEY] = h.rec("ValidMarker", magic=D.VALID_MARKER_MAGIC, state=RR)
s4[h.DUMP_DATA_KEY] = dump_data()
s4[D.REG244_VALID_TAG] = h.rec("ValidMarker", magic=D.VALID_MARKER_MAGIC, state=RR)
s4[D.REG244_DATA_TAG] = h.rec("Reg244SnapshotData", value=2)
s4j = {k: v.copy() for k, v in s4.items()}
s4j[JKEY] = h.rec(jm.JOURNAL_KIND, **GOOD_J)
sa, sb = reboot(s4, h.bank_for_row("OOOO"), full_boot=True), reboot(s4j, h.bank_for_row("OOOO"), full_boot=True)
check("[J] S4 (Dump + reg244 proof-harness dual obligation over 244): Dump fails closed exactly as before, and a "
      "leftover Free Power journal record changes nothing (identical boot state)",
      sa.g["dump_recovery_metadata_corrupt"] and boot_state(sa) == boot_state(sb) and not sb.g["free_power_start_journal_valid"])

# ===========================================================================
print("")
print("[9] mutation matrix - each rule broken on purpose; the detector aimed at it must catch it")
# ===========================================================================


def d_equivalence(ctx):
    combos = ALL_COMBOS[::5] + [h.states_of_row(r) for r in ("IIIO", "IOOO", "OIIO", "IIOI", "IIII", "BOBO")]
    journals = [None, (False, 15, 0, True), (True, 1, 0, True), (True, 3, 0, True), (True, 7, 0, True),
                (True, 15, 0, True), (True, 15, VERIFIED, True), (True, 5, 0, True), (True, 15, 0, False)]
    contexts = [dict(marker=RR), dict(marker=CLEAR), dict(marker=RR, corrupt=True), dict(marker=RR, snapshot_valid=False)]
    for combo in combos:
        snap, live = h.scenario(combo)
        for ckw in contexts:
            for j in journals:
                st, wg, ng = h.fw_probe(ctx, snap, live, journal=j, **ckw)
                want = h.model(snap, live, h.evidence(snap, journal=j, **ckw))
                route = ("BOTH" if wg and ng else fsp.ROUTE_RESTORE if wg else fsp.ROUTE_OPERATOR_LOCKOUT if ng
                         else fsp.ROUTE_COMMS_BACKOFF if (st["free_power_write_failed"] or not st["free_power_live_read_ok"])
                         else fsp.ROUTE_SKIP_WRITE)
                if (h.fw_class(st) != want or route != fsp.restore_route(want)
                        or st["free_power_live_self_partial"] != (want == SELF_PARTIAL)):
                    return False
    return True


def _probe_neither(ctx, row, journal, **kw):
    snap = SNAP
    st, wg, ng = h.fw_probe(ctx, snap, h.live_for(h.states_of_row(row), snap), journal=journal, **kw)
    return h.fw_class(st) == NEITHER and ng and not wg and not st["free_power_live_self_partial"]


def _dev(ctx, row, journal, **kw):
    snap = kw.pop("snap", SNAP)
    return h.boot_device(h.nvs_image(snap, journal=journal, operator_needed=kw.pop("operator_needed", 0)),
                         kw.pop("bank", None) or h.bank_for_row(row, snap), ctx)


def d_marker(ctx):
    return _probe_neither(ctx, "IIIO", GOOD, marker=CLEAR) and _probe_neither(ctx, "IIIO", GOOD, marker=PENDING)


def d_snapshot_trust(ctx):
    return _probe_neither(ctx, "IIIO", GOOD, snapshot_valid=False)


def d_metadata(ctx):
    return _probe_neither(ctx, "IIIO", GOOD, corrupt=True)


def d_binding(ctx):
    return _probe_neither(ctx, "IIIO", (True, 7, 0, False))


def d_journal_required(ctx):
    if not (_probe_neither(ctx, "IIIO", None) and _probe_neither(ctx, "IIIO", (False, 7, 0, True))):
        return False
    bank = h.bank_for_row("IOOO")
    return locked_out_neither(h.restore(_dev(ctx, "IOOO", None)), bank)


def d_attempt_bits(ctx):
    return all(_probe_neither(ctx, r, (True, m, 0, True)) for r, m in (("IOOO", 0), ("OIOO", 1), ("OOIO", 3), ("OIII", 7)))


def d_x_block(ctx):
    return all(_probe_neither(ctx, r, (True, 15, 0, True)) for r in ("XOOO", "XIIO", "IIXO", "IIIX"))


def d_coupling(ctx):
    return _probe_neither(ctx, "IIOI", (True, 15, 0, True)) and _probe_neither(ctx, "OOOI", (True, 15, 0, True))


def d_verified(ctx):
    bank = h.bank_for_row("OIIO")
    return (_probe_neither(ctx, "OIIO", (True, 15, VERIFIED, True))
            and locked_out_neither(h.restore(_dev(ctx, "OIIO", (15, VERIFIED))), bank))


def d_all_intended_no_journal(ctx):
    r = h.restore(_dev(ctx, "IIII", None))
    return r.cls == INTENDED and r.op_seq == h.RESTORE_OPS and completed(r)


def d_original_precedence(ctx):
    for row, both in (("BBBB", {b: True for b in fsp.BLOCKS}), ("BOBO", {B1: True, B3: True})):
        snap = h.make_snapshot(both)
        r = h.restore(_dev(ctx, row, (15, 0), snap=snap))
        if not (r.writes == [] and r.op_seq == h.SKIP_OPS and completed(r, h.originals_of(snap))):
            return False
    return True


def d_legal_restore(ctx):
    for row, j in (("IIIO", (7, 0)), ("IOOO", (1, 0)), ("OIIO", (15, 0))):
        r = h.restore(_dev(ctx, row, j))
        if not (r.cls == SELF_PARTIAL and r.op_seq == h.RESTORE_OPS and completed(r)):
            return False
    return True


def _audit(ctx, needle):
    for row, j in (("IIIO", (7, 0)), ("IOOO", (1, 0)), ("OIIO", (15, 0))):
        if any(needle in v for v in h.restore(_dev(ctx, row, j)).violations):
            return False
    return True


def d_no_start(ctx):
    return _audit(ctx, "start_free_power_override executed")


def d_no_active_persisted(ctx):
    if not _audit(ctx, "active_persisted set"):
        return False
    dev = _dev(ctx, "IIIO", (7, 0))
    run = h.restore(dev, fail={7: "error"})  # a failed attempt: nothing resets the flag afterwards
    return not dev.g["free_power_active_persisted"] and not any("active_persisted" in v for v in run.violations)


def d_original_values_only(ctx):
    return _audit(ctx, "not the snapshot ORIGINAL")


def d_operator_needed(ctx):
    return all(h.restore(_dev(ctx, r, j, operator_needed=1)).ops == [] for r, j in (("IIIO", (7, 0)), ("OIIO", (15, 0))))


def d_reg244_prewrite(ctx):
    r = h.restore(_dev(ctx, "IIIO", (7, 0), bank=h.make_bank(h.live_for(h.states_of_row("IIIO"), SNAP), reg244=2)))
    return r.writes == [] and r.sim.g["free_power_context_hold"]


def d_reg244_prefloor(ctx):
    r = h.restore(_dev(ctx, "IIIO", (7, 0)), read_override=lambda a, c, v: [2] if (a, c) == (244, 1) else v)
    return r.writes == [232, 256] and r.sim.g["free_power_context_hold"]


def d_marker_after_verify(ctx):
    # Faults that leave an owned register NOT ORIGINAL (I I I O: B1/B2/B3 are
    # INTENDED, so an unapplied 232/268/230 write matters) or make the final
    # verify itself fail.
    for fail in ({3: "ack_not_applied"}, {7: "ack_not_applied"}, {8: "ack_not_applied"}, {10: "error"}):
        dev = _dev(ctx, "IIIO", (7, 0))
        run = h.restore(dev, fail=fail)
        if h.nvs_marker(dev) != RR or any(e[1] == VALID_KEY for e in run.commits) or run.violations:
            return False
    return True


def d_neither_lockout(ctx):
    for row, j in (("IIOO", (1, 0)), ("IIOI", (15, 0)), ("IIXO", (15, 0))):
        bank = h.bank_for_row(row)
        if not locked_out_neither(h.restore(_dev(ctx, row, j)), bank):
            return False
    return True


def d_stale_flag(ctx):
    dev = _dev(ctx, "IIIO", (7, 0))
    h.restore(dev, fail={3: "error"})
    dev.advance(400_000)
    dev.bank[270] = 0x7E7E
    bank = dict(dev.bank)
    r = h.restore(dev)
    return r.writes == [] and dev.bank == bank


def d_accept_refuses_sp(ctx):
    for row, j in (("IIIO", (7, 0)), ("OIIO", (15, 0)), ("IOOO", (1, 0))):
        dev = _dev(ctx, row, j)
        bank = dict(dev.bank)
        run, _e = h.operator_action(dev, ctx, ACCEPT_ACTION)
        if not (refused_untouched(run, bank) and status(dev).startswith("ACCEPT REFUSED - Free Power residue")):
            return False
    return True


def d_accept_refuses_original(ctx):
    dev = _dev(ctx, "OOOO", (15, 0))
    run, _e = h.operator_action(dev, ctx, ACCEPT_ACTION)
    return refused_untouched(run, h.bank_for_row("OOOO")) and status(dev).startswith("ACCEPT REFUSED - state is ORIGINAL")


def d_accept_refuses_intended(ctx):
    dev = _dev(ctx, "IIII", (15, 0))
    run, _e = h.operator_action(dev, ctx, ACCEPT_ACTION)
    return refused_untouched(run, h.bank_for_row("IIII")) and status(dev).startswith("ACCEPT REFUSED - state is INTENDED")


def d_accept_corrupt(ctx):
    dev = _dev(ctx, "XOOO", (15, 0))
    eid = h.review(dev)
    dev.g["free_power_recovery_metadata_corrupt"] = True
    dev.ent("free_power_recovery_arm").state = True
    run = h.audited(dev, lambda: h.api_execute(dev, ctx, ACCEPT_ACTION, eid, "ACCEPT CURRENT STATE " + eid))
    return run.ops == [] and run.commits == [] and h.nvs_marker(dev) == RR


def d_force_journal_independent(ctx):
    traces = []
    for j, stale in (((7, 0), False), (None, False), ((15, VERIFIED), False), ((7, 0), True)):
        dev = _dev(ctx, "IIIO", j)
        dev.g["free_power_live_self_partial"] = stale
        run, _e = h.operator_action(dev, ctx, FORCE_ACTION)
        if not (run.op_seq == h.FORCE_OPS and completed(run)):
            return False
        traces.append(h.trace(run))
    return len(set(traces)) == 1


def d_force_gates(ctx):
    dev = _dev(ctx, "IIIO", (7, 0))
    eid = h.review(dev)
    dev.g["free_power_recovery_metadata_corrupt"] = True
    dev.ent("free_power_recovery_arm").state = True
    run = h.audited(dev, lambda: h.api_execute(dev, ctx, FORCE_ACTION, eid, "FORCE RESTORE ORIGINAL " + eid))
    if run.ops:
        return False
    dev = _dev(ctx, "IIIO", (7, 0))
    eid = h.review(dev)
    dev.bank[270] = 55
    dev.ent("free_power_recovery_arm").state = True
    run = h.audited(dev, lambda: h.api_execute(dev, ctx, FORCE_ACTION, eid, "FORCE RESTORE ORIGINAL " + eid))
    return run.writes == []


DETECTORS = {
    "equivalence": d_equivalence, "marker": d_marker, "snapshot_trust": d_snapshot_trust, "metadata": d_metadata,
    "binding": d_binding, "journal_required": d_journal_required, "attempt_bits": d_attempt_bits,
    "x_block": d_x_block, "coupling": d_coupling, "verified": d_verified,
    "all_intended_no_journal": d_all_intended_no_journal, "original_precedence": d_original_precedence,
    "legal_restore": d_legal_restore, "no_start": d_no_start, "no_active_persisted": d_no_active_persisted,
    "original_values_only": d_original_values_only, "operator_needed": d_operator_needed,
    "reg244_prewrite": d_reg244_prewrite, "reg244_prefloor": d_reg244_prefloor,
    "marker_after_verify": d_marker_after_verify, "neither_lockout": d_neither_lockout, "stale_flag": d_stale_flag,
    "accept_refuses_sp": d_accept_refuses_sp, "accept_refuses_original": d_accept_refuses_original,
    "accept_refuses_intended": d_accept_refuses_intended, "accept_corrupt": d_accept_corrupt,
    "force_journal_independent": d_force_journal_independent, "force_gates": d_force_gates,
}


def run_detectors(ctx) -> list[str]:
    failed = []
    for name, fn in DETECTORS.items():
        try:
            ok = fn(ctx)
        except Exception as exc:  # noqa: BLE001 - a crash on a mutant is a detection, recorded as such
            ok = False
            name = f"{name} (crashed: {type(exc).__name__})"
        if not ok:
            failed.append(name)
    return failed


baseline = run_detectors(REAL)
check(f"all {len(DETECTORS)} detectors pass on the real firmware", baseline == [], str(baseline))

IND = "          "  # classifier-lambda statement indentation
FGATE = "          } else if (id(free_power_recovery_metadata_corrupt)) {\n"
MUTANTS = [
    # (name, script, edits, detector that MUST catch it)
    ("remove marker requirement", DISPATCH,
     [(IND + "if (id(free_power_marker_state) != ecco_durable::MARKER_RESTORE_REQUIRED) return;\n", "", 1)], "marker"),
    ("remove snapshot-trust requirement", DISPATCH,
     [("if (!id(free_power_snapshot_valid) || id(free_power_recovery_metadata_corrupt)) return;",
       "if (id(free_power_recovery_metadata_corrupt)) return;", 1)], "snapshot_trust"),
    ("ignore metadata_corrupt", DISPATCH,
     [("if (!id(free_power_snapshot_valid) || id(free_power_recovery_metadata_corrupt)) return;",
       "if (!id(free_power_snapshot_valid)) return;", 1)], "metadata"),
    ("ignore binding", DISPATCH,
     [("ecco_durable::free_power_start_journal_binding(bound))) return;",
       "id(free_power_start_journal_binding))) return;", 1)], "binding"),
    ("remove the journal-valid requirement", DISPATCH,
     [(IND + "if (!id(free_power_start_journal_valid)) return;\n", "", 1)], "journal_required"),
    ("accept a missing journal as permission", DISPATCH,
     [(IND + "if (!id(free_power_start_journal_valid)) return;\n",
       IND + "if (!id(free_power_start_journal_valid)) { id(free_power_live_self_partial) = true; return; }\n", 1)],
     "journal_required"),
    ("remove every attempt-bit requirement", DISPATCH,
     [(IND + f"if (b{n}_i && !b{n}_o && (attempted & 0x0{bit}) == 0) return;\n", "", 1)
      for n, bit in ((1, 1), (2, 2), (3, 4), (4, 8))], "attempt_bits"),
    *[(f"remove the B{n} attempt-bit requirement only", DISPATCH,
       [(IND + f"if (b{n}_i && !b{n}_o && (attempted & 0x0{bit}) == 0) return;\n", "", 1)], "attempt_bits")
      for n, bit in ((1, 1), (2, 2), (3, 4), (4, 8))],
    ("allow an X block", DISPATCH,
     [(IND + "if ((!b1_o && !b1_i) || (!b2_o && !b2_i) || (!b3_o && !b3_i) || (!b4_o && !b4_i)) return;\n", "", 1)],
     "x_block"),
    ("remove the B4-over-B3 coupling", DISPATCH, [(IND + "if (b4_i && !b4_o && b3_o && !b3_i) return;\n", "", 1)],
     "coupling"),
    ("remove the START_VERIFIED exclusion", DISPATCH,
     [(IND + "if ((id(free_power_start_journal_flags) & ecco_durable::FREE_POWER_START_JOURNAL_FLAG_START_VERIFIED) != 0) return;\n",
       "", 1)], "verified"),
    ("make ALL INTENDED depend on the journal", DISPATCH,
     [("(id(free_power_live_matches_intended) || id(free_power_live_self_partial))",
       "((id(free_power_live_matches_intended) && id(free_power_start_journal_valid)) || id(free_power_live_self_partial))", 1)],
     "all_intended_no_journal"),
    ("ORIGINAL precedence lost in the write gate", DISPATCH,
     [("&& !id(free_power_live_owned_matches) && (id(free_power_live_matches_intended)",
       "&& (id(free_power_live_matches_intended)", 1)], "original_precedence"),
    ("ORIGINAL precedence lost in the classifier", DISPATCH,
     [("if (id(free_power_live_owned_matches) || id(free_power_live_matches_intended)) return;",
       "if (id(free_power_live_matches_intended)) return;", 1)], "equivalence"),
    ("route SELF_PARTIAL to the activation path", DISPATCH,
     [("      # Fail closed if the fresh read itself failed: retain the obligation,",
       "      - if:\n          condition:\n            lambda: 'return id(free_power_live_self_partial);'\n"
       "          then:\n            - script.execute: start_free_power_override\n"
       "      # Fail closed if the fresh read itself failed: retain the obligation,", 1)], "no_start"),
    ("set active_persisted from SELF_PARTIAL", DISPATCH,
     [(IND + "id(free_power_live_self_partial) = true;\n",
       IND + "id(free_power_live_self_partial) = true;\n" + IND + "id(free_power_active_persisted) = true;\n", 1)],
     "no_active_persisted"),
    ("SELF_PARTIAL restore writes an INTENDED value", DISPATCH,
     [("return std::vector<uint16_t>{id(free_power_snapshot_reg232)};",
       "return std::vector<uint16_t>{(uint16_t)(id(free_power_snapshot_reg232) | 0x0001)};", 1)], "original_values_only"),
    ("bypass operator_needed for a journalled obligation", WRAPPER,
     [("if (id(free_power_operator_needed)) {", "if (id(free_power_operator_needed) && !id(free_power_start_journal_valid)) {", 1)],
     "operator_needed"),
    ("bypass the FIRST (pre-write) reg244 context gate", DISPATCH,
     [("id(free_power_restore_live_reg244) == id(free_power_lease_context_reg244);",
       "(id(free_power_restore_live_reg244) == id(free_power_lease_context_reg244) || id(free_power_live_self_partial));", 2, 1)],
     "reg244_prewrite"),
    ("bypass the SECOND (pre-floor) reg244 context gate", DISPATCH,
     [("id(free_power_restore_live_reg244) == id(free_power_lease_context_reg244);",
       "(id(free_power_restore_live_reg244) == id(free_power_lease_context_reg244) || id(free_power_live_self_partial));", 2, 2)],
     "reg244_prefloor"),
    ("clear the marker before the final verify", DISPATCH,
     [(IND + "id(free_power_live_self_partial) = true;\n",
       IND + "id(free_power_live_self_partial) = true;\n" + IND
       + "ecco_durable::ValidMarker early{ecco_durable::VALID_MARKER_MAGIC, ecco_durable::MARKER_CLEAR};\n" + IND
       + "ecco_durable::commit_record(ecco_durable::key_for(ecco_durable::FREE_POWER_VALID_TAG), early);\n" + IND
       + "id(free_power_marker_state) = ecco_durable::MARKER_CLEAR;\n", 1)], "marker_after_verify"),
    ("final verify gate always ok", DISPATCH, [("if (ok) {", "if (true) {", 1)], "marker_after_verify"),
    ("NEITHER lockout no longer excludes SELF_PARTIAL", DISPATCH,
     [(" && !id(free_power_live_matches_intended) && !id(free_power_live_self_partial);",
       " && !id(free_power_live_matches_intended);", 1)], "legal_restore"),
    ("SELF_PARTIAL flag not reset per attempt", DISPATCH, [(IND + "id(free_power_live_self_partial) = false;\n", "", 2)],
     "stale_flag"),
    ("Accept clears SELF_PARTIAL (residue scan disabled)", ACCEPT_DISPATCH, [("if (any_residue) {", "if (false) {", 1)],
     "accept_refuses_sp"),
    ("Accept trusts journal ownership as permission", ACCEPT_DISPATCH,
     [("if (any_residue) {", "if (any_residue && !id(free_power_start_journal_valid)) {", 1)], "accept_refuses_sp"),
    ("Accept no longer refuses ORIGINAL", ACCEPT_DISPATCH, [("if (matches_original) {", "if (false) {", 1)],
     "accept_refuses_original"),
    ("Accept no longer refuses INTENDED explicitly", ACCEPT_DISPATCH, [("if (matches_intended) {", "if (false) {", 1)],
     "accept_refuses_intended"),
    ("Accept corrupt-metadata gate removed", ACCEPT,
     [("} else if (id(free_power_recovery_metadata_corrupt)) {\n            refusal = \"refused: metadata untrustworthy\";",
       "} else if (false) {\n            refusal = \"refused: metadata untrustworthy\";", 1)], "accept_corrupt"),
    ("Force refuses without a START journal", FORCE,
     [(FGATE, "          } else if (!id(free_power_start_journal_valid)) {\n            refusal = \"refused: no journal\";\n"
       + FGATE, 1)], "force_journal_independent"),
    ("Force skips its writes when SELF_PARTIAL is flagged", FORCE_DISPATCH,
     [("lambda: 'return id(free_power_recovery_force_fingerprint_ok);'",
       "lambda: 'return id(free_power_recovery_force_fingerprint_ok) && !id(free_power_live_self_partial);'", 1)],
     "force_journal_independent"),
    ("Force metadata gate removed", FORCE,
     [(FGATE + "            refusal = \"refused: metadata invalid\";",
       "          } else if (false) {\n            refusal = \"refused: metadata invalid\";", 1)], "force_gates"),
]
killed = 0
for name, sid, edits, target in MUTANTS:
    ctx = h.FwCtx(h.mutate(FW_TEXT, sid, edits))
    failed = run_detectors(ctx)
    hit = any(f == target or f.startswith(target + " ") for f in failed)
    killed += bool(failed)
    check(f"mutant killed by '{target}': {name}", hit, f"detected by {failed}" if failed else "SURVIVED")
    if failed:
        print(f"        detected by: {', '.join(failed[:6])}")
check(f"every one of the {len(MUTANTS)} mutants is killed (and by the detector aimed at it)", killed == len(MUTANTS))

print("")
if FAILURES:
    print(f"FAILED: {len(FAILURES)} check(s)")
    for f in FAILURES:
        print(f"  - {f}")
    sys.exit(1)
print("All SG-01 Phase 5 hardening checks passed.")
