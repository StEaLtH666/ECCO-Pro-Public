#!/usr/bin/env python3
"""FB-B2 - host C++ compile of the pure SAVE / INVALIDATE header, parity with the Python mirror.

firmware/include/ecco_fallback_save.h (namespace ecco_fbsave) holds every DECISION the FB-B2 firmware lambdas take: the action
router, the byte-exact confirmation grammar, the SAVE gate G0-G16, the INVALIDATE gate, the own-hold masking of the SAVE final lambda,
the intended FBP / FBW pair (plan_save / plan_invalidate, pre-validated against the FB-B0 transition check) and every operator text
(refusals, outcomes, log lines). All of it is constexpr (text included), so a C++ compiler running -fsyntax-only evaluates the header's
golden vectors, golden strings and golden-case tables as static_asserts - no native executable is ever run. This suite:

  [1] compiler: a GCC C++ compiler must exist - it FAILS, never skips (search order: $ECCO_CXX, g++ / c++ on PATH, then the
      xtensa-esp32-elf-g++ ESPHome installs);
  [2] compiles the header, with the FB-A, FB-B0 and FB-B1 headers beside it, under g++ -std=gnu++17 and -std=gnu++20,
      -Wall -Wextra -Werror, included twice (#pragma once), also -O2: every static_assert holds, including the four hand-decided
      golden-case tables (SAVE gate, INVALIDATE gate, SAVE plan, INVALIDATE plan);
  [3] PARITY: every labelled golden static_assert is parsed, the Python mirror (registry/fallback_save.py) must reproduce each value
      and each string EXACTLY, the header's generated golden block must equal what this file emits
      (`python registry/tests/test_fallback_save_host_compile.py --emit-goldens <file>`), the four case tables are re-derived from the
      mirror, and every enumerator / scalar constant of the header equals the mirror's;
  [4] RANDOMIZED parity: a seeded generator written twice (constexpr C++ in a test translation unit, and Python) feeds 120 cases x 7
      components (tokens and grammar, SAVE gate, INVALIDATE gate, plan_save, plan_invalidate, outcome texts, timing / masks / final
      gate) through the header and through the mirror; one FNV digest per case and component is a static_assert (ids that differ only in
      the high or only in the low 32 bits, writes fingerprints below / across the wrap and hazard-word tokens are drawn on purpose);
  [5] negative controls: a deliberately wrong golden, a type error and violated header static_asserts are REAL compile rejections,
      and every mutant of the header (one per decision) must be rejected by a static_assert naming the golden that kills it;
  [6] header discipline scans (includes, banned tokens, namespace, no durable tag, no writer call, the invalidate_profile guard,
      the card-regex word hygiene of every string literal).

Writes only to a temporary directory; no hardware, no network.
"""

from __future__ import annotations

import glob
import os
import re
import shutil
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
INCLUDE_DIR = ROOT / "firmware" / "include"
HEADER_PATH = INCLUDE_DIR / "ecco_fallback_save.h"
CAP_PATH = INCLUDE_DIR / "ecco_fallback_capture.h"
MODEL_PATH = INCLUDE_DIR / "ecco_fallback_durable_model.h"
FBA_PATH = INCLUDE_DIR / "ecco_fallback_profile.h"
THIS = Path(__file__).resolve()

sys.path.insert(0, str(ROOT / "registry"))
import fallback_capture as cap  # noqa: E402
import fallback_durable as fd  # noqa: E402
import fallback_profile as fp  # noqa: E402
import fallback_save as sv  # noqa: E402

FAILURES: list[str] = []
U32 = 0xFFFFFFFF
U64 = 0xFFFFFFFFFFFFFFFF


# The Energy Actions card's hazard patterns (the list the FB-B1 suites pin) plus the words failed / deferred: no FB text may match any of them (re.I).
HAZARD_RX = re.compile("|".join([
    r"RECOVERY REQUIRED", r"OPERATOR DECISION REQUIRED", r"RESTORE BLOCKED", r"RECOVERY BLOCKED", r"\bFAILED\b", r"VERIFY ERROR",
    r"VERIFY TIMEOUT", r"VERIFY REFUSED", r"DEFERRED", r"ACCEPT REFUSED", r"Recovery Arm first", r"inverter writes? (?:are |is )?locked",
    r"deliberate recovery required", r"START FAILED", r"ACTIVATION (?:VERIFY|WRITE) FAILED", r"press End Free Power", r"retry restore",
    r"snapshot retained", r"^(?:RESTORING|STARTING|ACTIVATION VERIFY)", r"failed", r"deferred"]), re.I)


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  PASS  {name}")
    else:
        FAILURES.append(name)
        print(f"  FAIL  {name}" + (f" - {detail}" if detail else ""))


# ===========================================================================
# The golden table: ONE description per golden, a C++ expression and its Python counterpart. The header's generated block
# (between the GENERATED-GOLDENS markers) is produced from it; the compiler then proves the C++ expression equals the literal
# the Python mirror produced.
# ===========================================================================
class Golden:
    def __init__(self, kind: str, label: str, cxx: str, py) -> None:
        self.kind, self.label, self.cxx, self.py = kind, label, cxx, py


GOLDENS: list[Golden] = []


def val(label: str, cxx: str, py) -> None:
    GOLDENS.append(Golden("value", label, cxx, py))


def txt(label: str, cxx: str, py) -> None:
    GOLDENS.append(Golden("text", label, cxx, py))


def strg(label: str, cxx: str, py) -> None:
    GOLDENS.append(Golden("str", label, cxx, py))


def hazard_starts(b: bytes) -> set:
    """F2: the byte offsets at which a case-insensitive hazard word ("fail" / "defer") starts. The header's source never contains one whole
    (the discipline scans forbid the words failed / deferred in any string literal): cxx_str splits the literal after the first letter
    ("f" "ailed") and lab() escapes the first letter in a golden label."""
    low = b.lower()
    out = set()
    for w in (b"fail", b"defer"):
        i = low.find(w)
        while i >= 0:
            out.add(i)
            i = low.find(w, i + 1)
    return out


def cxx_str(s) -> str:
    """A C++ string literal of the UTF-8 bytes of s (NULs and non-ASCII as octal escapes; a hazard word is split into adjacent literals)."""
    b = s.encode("utf-8") if isinstance(s, str) else bytes(s)
    splits = {i + 1 for i in hazard_starts(b)}
    out = []
    for idx, o in enumerate(b):
        if idx in splits:
            out.append('" "')
        ch = chr(o)
        if ch == '"':
            out.append('\\"')
        elif ch == "\\":
            out.append("\\\\")
        elif ch == "\n":
            out.append("\\n")
        elif 32 <= o < 127:
            out.append(ch)
        else:
            out.append(f"\\{o:03o}")
    return '"' + "".join(out) + '"'


def lab(s) -> str:
    """A golden-label-safe rendering of arbitrary text (labels may contain neither a quote nor a backslash)."""
    b = s.encode("utf-8") if isinstance(s, str) else bytes(s)
    hz = hazard_starts(b)
    return "".join(chr(o) if 32 <= o < 127 and chr(o) not in '"\\' and i not in hz else f"~{o:02X}" for i, o in enumerate(b))


# ---- fixtures: the same logical inputs described once for C++ (header golden section, fx_*) and for Python ---------------
GOLD_P = fp.seal_profile(fp.blank_profile(
    magic=fp.PROFILE_MAGIC, schema=1, size=96, generation=7, captured_epoch=1790000000, flags=0, reg244=2,
    reg256_261=[8000, 500, 4000, 3000, 2000, 1000], reg268_273=[100, 20, 0, 50, 100, 30], reg274_279=[1, 0, 1, 0, 0, 1],
    reg232=0x0011, reg243=1, reg248=1, reg250_255=[0, 530, 1000, 1600, 2100, 2330], reg230=185, reg245=8000, reg247=1))
GW = cap.words_of(GOLD_P)
FX_ID = 0x0123456789ABCDEF
FX_BORN_MS = 4294960000
FX_EPOCH = 1790000500
PB = 0x1122334455667788
LOAD_OK, LOAD_ABSENT, LOAD_WSZ, LOAD_RERR, LOAD_UNAV = 0, 1, 2, 3, 4


def fx_profile(generation: int, flags: int) -> dict:
    p = fp._copy(GOLD_P)
    p["generation"] = generation & U32
    p["flags"] = flags
    return fp.seal_profile(p)


def fx_profile_bad(generation: int) -> dict:
    p = dict(fx_profile(generation, 0))
    p["binding"] ^= 1
    return p


def fx_profile_domain(generation: int) -> dict:
    p = fp._copy(GOLD_P)
    p["generation"] = generation
    p["reg244"] = 1
    return fp.seal_profile(p)


def fx_p(pk: int):
    none = fp.blank_profile()
    return {0: (LOAD_ABSENT, none, 0), 1: (LOAD_OK, fx_profile(7, 0), 0), 2: (LOAD_OK, fx_profile(8, 1), 0),
            3: (LOAD_OK, fx_profile_domain(9), 0), 4: (LOAD_OK, fx_profile_bad(11), 0), 5: (LOAD_WSZ, none, 40),
            6: (LOAD_RERR, none, 0), 7: (LOAD_UNAV, none, 0), 8: (LOAD_OK, fx_profile(0xFFFFFFFF, 0), 0)}.get(
        pk, (LOAD_OK, fx_profile(3, 0), 0))


def fx_witness(hw, hw_binding, prior_gen, prior_binding, tag_key, op) -> dict:
    return fd.make_provision(hw & U32, hw_binding, prior_gen & U32, prior_binding, tag_key, 1, op)


def fx_w(wk: int, p: dict):
    none = fd.blank_provision()
    g = p["generation"] if p["generation"] != 0 else 9
    b = p["binding"]
    key = fd.FALLBACK_PROFILE_KEY
    s, i = fd.PROV_OP_SAVE, fd.PROV_OP_INVALIDATE
    pg1, pbb = (g - 1) & U32 if g > 1 else 0, PB if g > 1 else 0
    if wk == 0:
        return LOAD_ABSENT, none, 0
    if wk == 1:
        return LOAD_OK, fx_witness(g, b, pg1, pbb, key, s), 0
    if wk == 2:
        return LOAD_OK, fx_witness(g - 1, 0x77, g - 2, PB, key, s), 0
    if wk == 3:
        w = dict(fx_witness(g, b, pg1, pbb, key, s))
        w["binding"] ^= 1
        return LOAD_OK, w, 0
    if wk == 4:
        return LOAD_WSZ, none, 40
    if wk == 5:
        return LOAD_RERR, none, 0
    if wk == 6:
        return LOAD_OK, fx_witness(1, 0x99, 0, 0, key, s), 0
    if wk == 7:
        return LOAD_OK, fx_witness(5, 0x99, 4, 0xAB, key, s), 0
    if wk == 8:
        return LOAD_OK, fx_witness(g + 1, 0x99, g, b, key, s), 0
    if wk == 9:
        return LOAD_OK, fx_witness(g + 3, 0x99, g + 2, 0xAB, key, s), 0
    if wk == 10:
        return LOAD_OK, fx_witness(0xFFFFFFFF, b, 0xFFFFFFFE, 0xAB, key, s), 0
    if wk == 11:
        return LOAD_OK, fx_witness(g, b, pg1, pbb, 5, s), 0
    if wk == 12:
        return LOAD_OK, fx_witness(g, b, pg1, pbb, key, i), 0
    if wk == 14:  # SEM-2: a corrupt witness whose hw field is huge
        w = dict(fx_witness(0x7FFFFFFF, b, pg1, pbb, key, s))
        w["binding"] ^= 1
        return LOAD_OK, w, 0
    if wk == 15:  # a wrong-size witness whose bytes carry a huge hw field
        return LOAD_WSZ, fx_witness(0x7FFFFFFF, b, 0, 0, key, s), 40
    if wk == 16:  # an absent witness whose bytes carry a huge hw field
        return LOAD_ABSENT, fx_witness(0x7FFFFFFF, b, 0, 0, key, s), 0
    return LOAD_OK, fx_witness(g, b ^ 1, pg1, pbb, key, s), 0


def fx_save_inputs(pk: int, wk: int, seen: int) -> sv.SavePlanInputs:
    pl, p, plen = fx_p(pk)
    wl, w, wlen = fx_w(wk, p)
    in_ = sv.SavePlanInputs()
    in_.p_load, in_.p, in_.p_stored_len, in_.w_load, in_.w, in_.w_stored_len = pl, p, plen, wl, w, wlen
    cls, why, _rule = fd.compose_profile_class(pl, p, wl, w, 0)
    in_.cls, in_.why, in_.read_anomaly, in_.unconfirmed, in_.seen_hw_gen = cls, why, 0, False, seen
    f = cap.prior_fingerprint(pl, p, plen)
    in_.cand_prior_class, in_.cand_prior_gen, in_.cand_prior_binding = cls, f.generation, f.binding
    in_.replace_corrupt = cls == fd.EPC_CORRUPT
    in_.words = list(GW)
    in_.captured_epoch = FX_EPOCH
    return in_


def fx_save_mut(in_: sv.SavePlanInputs, mut: int) -> sv.SavePlanInputs:
    flip_class = 1 if in_.cand_prior_class != 1 else 5
    if mut == 1:
        in_.unconfirmed = True
    elif mut == 2:
        in_.read_anomaly = 4
    elif mut == 3:
        in_.replace_corrupt = not in_.replace_corrupt
    elif mut == 4:
        in_.captured_epoch = 0
    elif mut == 5:
        in_.cand_prior_class = flip_class
    elif mut == 6:
        in_.cand_prior_gen = (in_.cand_prior_gen + 1) & U32
    elif mut == 7:
        in_.cand_prior_binding ^= 1
    elif mut == 8:
        in_.cand_prior_class = flip_class
        in_.unconfirmed = True
    elif mut == 9:
        in_.unconfirmed = True
        in_.read_anomaly = 4
    elif mut == 10:
        in_.read_anomaly = 4
        in_.replace_corrupt = not in_.replace_corrupt
    elif mut == 11:
        in_.replace_corrupt = not in_.replace_corrupt
        in_.captured_epoch = 0
    elif mut == 12:
        in_.captured_epoch = 0
        in_.seen_hw_gen = 0xFFFFFFFF
    elif mut == 13:
        in_.cls = 7
        in_.cand_prior_class = 7
    elif mut == 14:
        in_.cls = 9
        in_.cand_prior_class = 9
    elif mut == 15:  # SEM-1: the candidate's bound prior binding differs only in its HIGH 32 bits (bit 63) ...
        in_.cand_prior_binding ^= 1 << 63
    elif mut == 16:  # ... only in bit 32 ...
        in_.cand_prior_binding ^= 1 << 32
    elif mut == 17:  # ... or is only its LOW 32 bits
        in_.cand_prior_binding &= 0xFFFFFFFF
    return in_


def fx_inv_inputs(pk: int, wk: int, seen: int) -> sv.InvalidatePlanInputs:
    pl, p, plen = fx_p(pk)
    wl, w, wlen = fx_w(wk, p)
    in_ = sv.InvalidatePlanInputs()
    in_.p_load, in_.p, in_.p_stored_len, in_.w_load, in_.w, in_.w_stored_len = pl, p, plen, wl, w, wlen
    in_.cls = fd.compose_profile_class(pl, p, wl, w, 0)[0]
    in_.read_anomaly, in_.unconfirmed, in_.seen_hw_gen, in_.target_id = 0, False, seen, p["binding"]
    return in_


def fx_inv_mut(in_: sv.InvalidatePlanInputs, mut: int) -> sv.InvalidatePlanInputs:
    if mut == 1:
        in_.unconfirmed = True
    elif mut == 2:
        in_.read_anomaly = 4
    elif mut == 3:
        in_.target_id ^= 1
    elif mut == 4:
        in_.target_id = 0
    elif mut == 5:
        in_.unconfirmed = True
        in_.read_anomaly = 4
    elif mut == 6:  # SEM-1: the named binding differs only in bit 63 / only in bit 32 / in every bit of the high word / is only the low 32 bits
        in_.target_id ^= 1 << 63
    elif mut == 7:
        in_.target_id ^= 1 << 32
    elif mut == 8:
        in_.target_id ^= 0xFFFFFFFF00000000
    elif mut == 9:
        in_.target_id &= 0xFFFFFFFF
    elif mut == 10:  # SEM-2: the composed class is forced to VALID
        in_.cls = fd.EPC_VALID
    return in_


_ACTIONS = {0: "SAVE", 1: "INVALIDATE", 2: "RESTORE", 3: "ACKNOWLEDGE", 4: "CAPTURE", 5: "", 6: "save", 7: "SAVE ", 8: "ACCEPT_LIVE",
            9: "PROVISION", 10: "APPLY", 11: "RETRY_APPLY", 12: "SAVE\0x", 13: "INVALIDATE ", 14: "invalidate", 15: "INVALIDATE\0x"}


def fx_action(tok: int) -> str:
    return _ACTIONS[tok]


def fx_target(kind: int, id_: int) -> str:
    h = format(id_ & U64, "016X")
    return {0: h, 1: h.lower(), 2: h[:-1], 3: h + "0", 4: format((id_ ^ 1) & U64, "016X"), 5: "", 6: h + "\n", 7: " " + h,
            8: "G" + h[1:], 9: "0x" + h[2:], 10: h[:8] + "\0" + h[9:], 11: format((id_ ^ (1 << 63)) & U64, "016X"), 12: format((id_ ^ (1 << 32)) & U64, "016X"),
            13: format((id_ ^ 0xFFFFFFFF00000000) & U64, "016X"), 14: format((id_ ^ 0xFFFFFFFF) & U64, "016X")}[kind]


def fx_conf(kind: int, id_: int) -> str:
    h = format(id_ & U64, "016X")
    other = format((id_ ^ 1) & U64, "016X")
    return {0: "SAVE " + h, 1: "SAVE " + h + " REPLACE CORRUPT", 2: "INVALIDATE " + h, 3: "SAVE " + h + "\n", 4: "SAVE " + h + " ",
            5: "SAVE " + h.lower(), 6: "SAVE  " + h, 7: "", 8: "SAVE ", 9: "SAVE " + h + " REPLACE CORRUPT ",
            10: "INVALIDATE " + h + " REPLACE CORRUPT", 11: "save " + h, 12: "SAVE " + h + " REPLACE  CORRUPT",
            13: "SAVE " + h + " replace corrupt", 14: "SAVE " + other, 15: "SAVE " + h + " REPLACE", 16: "SAVE " + h[:-1],
            17: "SAVE " + h + "0", 18: "INVALIDATE " + h + "\n", 19: "INVALIDATE " + h.lower(), 20: "INVALIDATE " + other,
            21: "SAVE " + h + "\0x", 22: "SAVE " + h + "\0", 23: "INVALIDATE " + h + "\0", 24: "INVALIDATE " + format((id_ ^ (1 << 63)) & U64, "016X"),
            25: "INVALIDATE " + format((id_ ^ (1 << 32)) & U64, "016X"), 26: "INVALIDATE " + format((id_ ^ 0xFFFFFFFF00000000) & U64, "016X"),
            27: "INVALIDATE " + format((id_ ^ 0xFFFFFFFF) & U64, "016X")}[kind]


def fx_gate(k: int) -> cap.GateInputs:
    g = cap.GateInputs(boot_loaded=True, fbs_slot=fd.FBS_CLEAR_ABSENT)
    g.fp.free_power_marker_boot_load = 1
    g.dump.dump_marker_boot_load = 1
    g.r244.reg244_marker_boot_load = 1
    if k == 1:
        g.bus.fallback_profile_op_in_progress = True
    elif k == 2:
        g.bus.fallback_profile_capture_dispatch_running = True
    elif k == 3:
        g.boot_loaded = False
    elif k == 4:
        g.free_power_write_enable = True
    elif k == 5:
        g.dump_write_enable = True
    elif k == 6:
        g.manual_config_write_enable = True
    elif k == 7:
        g.bus.manual_write_in_progress = True
    elif k == 8:
        g.bus.correction_in_progress = True
    elif k == 9:
        g.bus.manual_write_in_progress = True
        g.bus.diag_write_lock_held = True
        g.bus.diag_write_lock_since_ms = 1000
        g.bus.now_ms = 302000
    elif k == 10:
        g.fbs_slot = fd.FBS_OBLIGATION
    elif k == 11:
        g.fbs_slot = fd.FBS_CORRUPT
    elif k == 12:
        g.fbs_slot = fd.FBS_UNREADABLE
    elif k == 13:
        g.fp.free_power_marker_boot_load = 0
        g.fp.free_power_snapshot_valid = True
        g.fp.free_power_marker_state = 1
        g.fp.free_power_active_persisted = True
    elif k == 14:
        g.dump.dump_marker_boot_load = 0
        g.dump.dump_snapshot_valid = True
        g.dump.dump_marker_state = 1
        g.dump.dump_operator_needed = True
    elif k == 15:
        g.r244.reg244_snapshot_valid = True
        g.r244.reg244_marker_state = 2
    elif k == 16:
        g.probe_latch = 0x0001
    elif k == 17:
        g.free_power_write_enable = True
        g.bus.manual_write_in_progress = True
    elif k == 18:
        g.bus.manual_write_in_progress = True
        g.fbs_slot = fd.FBS_OBLIGATION
    elif k == 19:
        g.fp.free_power_marker_state = 1
        g.dump.dump_marker_state = 1
    elif k == 20:
        g.bus.verification_pending = True
    elif k == 21:
        g.bus.reg244_apply_in_progress = True
    elif k == 22:
        g.bus.free_power_operation_in_progress = True
    elif k == 23:
        g.fbs_slot = fd.FBS_CLEAR_VALID
    elif k == 24:
        g.bus.dump_operation_in_progress = True
    elif k == 25:
        g.bus.free_power_recovery_force_in_progress = True
    elif k == 26:  # SEM-3: the write lock held ALONE and an ACTIVE Free Power lease
        g.bus.manual_write_in_progress = True
        g.fp.free_power_marker_boot_load = 0
        g.fp.free_power_snapshot_valid = True
        g.fp.free_power_marker_state = 1
        g.fp.free_power_active_persisted = True
    elif k == 27:  # ... and an ACTIVE Dump to Grid lease
        g.bus.manual_write_in_progress = True
        g.dump.dump_marker_boot_load = 0
        g.dump.dump_snapshot_valid = True
        g.dump.dump_marker_state = 1
        g.dump.dump_active_persisted = True
    return g


_BUS_FLAGS = {1: "fallback_profile_op_in_progress", 2: "fallback_profile_capture_dispatch_running", 3: "manual_write_in_progress",
              4: "correction_in_progress", 5: "verification_pending", 6: "verification_read_active",
              7: "free_power_operation_in_progress", 8: "free_power_recovery_force_in_progress",
              9: "free_power_recovery_accept_in_progress", 10: "reg244_apply_in_progress", 11: "dump_operation_in_progress"}


def fx_bus(k: int) -> cap.BusInputs:
    b = cap.BusInputs()
    if k in _BUS_FLAGS:
        setattr(b, _BUS_FLAGS[k], True)
    return b


def fx_sg(cand, age, cls, boot, unc, anom, hb, time, arm, wfp) -> sv.SaveGateInputs:
    si = sv.SaveGateInputs()
    si.arm_was_on = arm != 0
    si.cand_valid = cand in (0, 2, 3, 5)
    si.cand_saveable = cand in (0, 3, 4)
    si.cand_id = FX_ID if cand in (0, 4, 5) else 0
    si.cand_ms = FX_BORN_MS
    si.cand_prior_class = cls
    si.now_ms = (FX_BORN_MS + [0, 119999, 120000, 120001][age & 3]) & U32
    # the writes fingerprint at Review / now (SEM-1): 0 equal, 1 +1, 2 -1 (BELOW), 3 / 4 across the uint32 wrap, 5 equal at the maximum, 6 / 7 across the signed
    # boundary, 8 equal at zero, 9 / 10 differing only in the high 16 bits
    si.cand_writes_fp, si.writes_fp_now = {0: (1000, 1000), 1: (1000, 1001), 2: (1000, 999), 3: (U32, 0), 4: (0, U32), 5: (U32, U32),
                                           6: (0x80000000, 0x7FFFFFFF), 7: (0x7FFFFFFF, 0x80000000), 8: (0, 0), 9: (0, 0x10000),
                                           10: (0x12340000, 0x56780000)}.get(wfp, (1000, 1000))
    si.boot_loaded, si.unconfirmed, si.read_anomaly, si.hb_ok, si.time_trusted = boot != 0, unc != 0, anom, hb != 0, time != 0
    return si


def sg_run(c) -> sv.SaveGateResult:
    tok, arm, cand, age, tgt, cnf, cls, boot, unc, anom, hb, time, wfp, gate = c[:14]
    si = fx_sg(cand, age, cls, boot, unc, anom, hb, time, arm, wfp)
    id_ = FX_ID if cand in (0, 4, 5) else 0
    act, t, cf = fx_action(tok), fx_target(tgt, id_), fx_conf(cnf, id_)
    return sv.save_gate_decide(si, act, len(act), t, len(t), cf, len(cf), fx_gate(gate))


SG_BASE_ROW = (0, 1, 0, 0, 0, 0, 5, 1, 0, 0, 1, 1, 0)


def fx_ig(c) -> sv.InvalidateGateInputs:
    tok, arm, tgt, cnf, boot, anom, unc, cls_o, pk, wk, seen, bus, tx, fbs = c[:14]
    pl, p, _plen = fx_p(pk)
    wl, w, _wlen = fx_w(wk, p)
    in_ = sv.InvalidateGateInputs()
    in_.arm_was_on, in_.boot_loaded, in_.read_anomaly, in_.unconfirmed = arm != 0, boot != 0, anom, unc != 0
    in_.cls = cls_o if cls_o != 255 else fd.compose_profile_class(pl, p, wl, w, 0)[0]
    in_.p_load, in_.p, in_.w_load, in_.w, in_.seen_hw_gen = pl, p, wl, w, seen
    in_.bus = fx_bus(bus)
    in_.tx_buffer_empty, in_.tx_blocked, in_.fbs_slot = tx != 1, tx == 2, fbs
    return in_


def ig_run(c) -> sv.InvalidateGateResult:
    in_ = fx_ig(c)
    id_ = in_.p["binding"]
    act, t, cf = fx_action(c[0]), fx_target(c[2], id_), fx_conf(c[3], id_)
    return sv.invalidate_gate_decide(in_, act, len(act), t, len(t), cf, len(cf))


def plan_digest(r: sv.Plan) -> int:
    return fp.fnv1a_64(fp.pack_profile(r.p_new) + fd.pack_provision(r.w_new))


# ---- the hand-decided golden-case tables of the header, parsed (the expected values are the header's, written by hand) ----------
def read_header() -> str:
    return HEADER_PATH.read_text(encoding="utf-8")


def table_rows(text: str, name: str) -> list[list[str]]:
    """The rows of `constexpr <Row> NAME[] = { {..}, ... };` as lists of tokens (comments stripped)."""
    m = re.search(rf"constexpr \w+ {name}\[\] = \{{(.*?)\n\}};", text, re.S)
    assert m, name
    body = re.sub(r"//[^\n]*", "", m.group(1))
    return [[t.strip() for t in row.split(",")] for row in re.findall(r"\{([^{}]*)\}", body)]


def token_value(tok: str) -> int:
    return int(tok.rstrip("u")) if re.fullmatch(r"\d+u?", tok) else getattr(sv, tok)


def parsed_table(name: str) -> list[list[int]]:
    return [[token_value(t) for t in r] for r in table_rows(read_header(), name)]


SG_ROWS, IG_ROWS, SP_ROWS, IP_ROWS = (parsed_table("SG_CASES"), parsed_table("IG_CASES"), parsed_table("SP_CASES"),
                                      parsed_table("IP_CASES"))


# ---- TxnResult fixtures (C++ lambda text + Python record) ----------------------------------------------------------------
class Tr:
    def __init__(self, w_err=0, w_rb=0, w_out=0, w_us=0, p_err=0, p_rb=0, p_out=3, p_us=0, adv=0, ref=0):
        self.__dict__.update(w_err=w_err, w_rb=w_rb, w_out=w_out, w_us=w_us, p_err=p_err, p_rb=p_rb, p_out=p_out, p_us=p_us, adv=adv, ref=ref)

    def cxx(self) -> str:
        return ("[]{ ecco_fbdurable::TxnResult r{}; "
                f"r.w.err = {self.w_err}; r.w.rb_class = {self.w_rb}; r.w.outcome = {self.w_out}; r.w.us = {self.w_us}u; "
                f"r.p.err = {self.p_err}; r.p.rb_class = {self.p_rb}; r.p.outcome = {self.p_out}; r.p.us = {self.p_us}u; "
                f"r.witness_advanced = {self.adv}; r.refusal = {self.ref}; return r; }}()")

    def py(self) -> fd.TxnResult:
        r = fd.TxnResult()
        r.w = fd.KeyReport(err=self.w_err, rb_class=self.w_rb, outcome=self.w_out, us=self.w_us)
        r.p = fd.KeyReport(err=self.p_err, rb_class=self.p_rb, outcome=self.p_out, us=self.p_us)
        r.witness_advanced, r.refusal = bool(self.adv), self.ref
        return r


# =========================== constants, enums, names =================================================================
for _name in ("ARM_TTL_MS", "PRECOMMIT_WAIT_MS", "PURPOSE_SAVE", "ECHO_MAX", "ECHO_LOOK", "ID_DIGITS", "PHRASE_SCAN_MAX", "ACTION_SCAN_MAX"):
    val(f"constant {_name}", _name, lambda n=_name: getattr(sv, n))
val("constant ecco_fbcap::CAPTURE_SAVING (D8)", "ecco_fbcap::CAPTURE_SAVING", lambda: cap.CAPTURE_SAVING)
val("constant ecco_fbcap::TEXT_CAP", "ecco_fbcap::TEXT_CAP", lambda: cap.TEXT_CAP)
strg("SAVE_REFUSED_PREFIX", "SAVE_REFUSED_PREFIX", lambda: sv.SAVE_REFUSED_PREFIX)
strg("INVALIDATE_REFUSED_PREFIX", "INVALIDATE_REFUSED_PREFIX", lambda: sv.INVALIDATE_REFUSED_PREFIX)
for _c in range(0, 9):
    strg(f"capture_state_name {_c} (D8: 4 is SAVING, 5.. IDLE)", f"ecco_fbcap::capture_state_name({_c})", lambda c=_c: cap.capture_state_name(c))
for _name, _lo, _hi in (("txn_name", 0, 6), ("txn_op_name", 0, 6), ("key_name", 0, 6), ("rb_name", 0, 10)):
    for _c in range(_lo, _hi):
        strg(f"{_name} {_c}", f"{_name}({_c})", lambda c=_c, n=_name: getattr(sv, n)(c))
for _s in range(0, 7):
    strg(f"slot_label {_s}", f"slot_label({_s})", lambda s=_s: sv.slot_label(s))
_CHARS = (("A", 65), ("Z", 90), ("a", 97), ("z", 122), ("0", 48), ("9", 57), ("_", 95), (" ", 32), ("-", 45), ("?", 63), ("@", 64), ("[", 91),
          ("`", 96), ("{", 123), ("/", 47), (":", 58), ("F", 70), ("G", 71), ("f", 102), ("\\n", 10), ("\\0", 0), ("\\377", 255))
for _ch, _o in _CHARS:
    val(f"echo_char_ok byte {_o}", f"echo_char_ok('{_ch}')", lambda o=_o: sv.echo_char_ok(o))
    val(f"hex_digit_ok byte {_o}", f"hex_digit_ok('{_ch}')", lambda o=_o: sv.hex_digit_ok(o))
    val(f"echo_fold byte {_o}", f"(uint8_t) echo_fold('{_ch}')", lambda o=_o: o + 32 if 65 <= o <= 90 else o)

# =========================== action token (both overloads) ===========================================================
_TOKENS = ["SAVE", "INVALIDATE", "RESTORE", "ACKNOWLEDGE", "", "save", "Save", "SAVE ", " SAVE", "SAVE\n", "SAVEX", "SAV", "S", "INVALIDATE ",
           "invalidate", "INVALID", "INVALIDATEX", "RESTORE ", "restore", "ACKNOWLEDGE\n", "acknowledge", "CAPTURE", "APPLY", "RETRY_APPLY",
           "ACCEPT_LIVE", "PROVISION", "X" * 40, "SAVE\0x", "INVALIDATE\0", "RESTORE\0RESTORE"]
for _t in _TOKENS:
    _lab = "'" + lab(_t) + "'"
    val(f"action_token {_lab} (NUL-terminated)", f"action_token({cxx_str(_t)})", lambda t=_t: sv.action_token(t))
    val(f"action_token {_lab} (explicit length {len(_t)})", f"action_token({cxx_str(_t)}, {len(_t)})", lambda t=_t: sv.action_token(t, len(t)))
    val(f"is_invalidate_action {_lab}", f"is_invalidate_action({cxx_str(_t)}, {len(_t)})", lambda t=_t: sv.is_invalidate_action(t, len(t)))
    val(f"is_invalidate_action {_lab} (NUL-terminated)", f"is_invalidate_action({cxx_str(_t)})", lambda t=_t: sv.is_invalidate_action(t))
val("action_token: a null action", "action_token(nullptr)", lambda: sv.action_token(None))
val("action_token: a null action with a length", "action_token(nullptr, 4)", lambda: sv.action_token(None, 4))
val("is_invalidate_action: a null action", "is_invalidate_action(nullptr)", lambda: sv.is_invalidate_action(None))
val("action_token: a shorter explicit length cuts the token (SAVEX, 4)", 'action_token("SAVEX", 4)', lambda: sv.action_token("SAVEX", 4))
val("action_token: a longer explicit length never matches (SAVE, 5 reads the NUL)", 'action_token("SAVE", 5)', lambda: sv.action_token("SAVE\0", 5))

# =========================== bounded string primitives ================================================================
for _s, _lim in (("", 0), ("", 5), ("abc", 2), ("abc", 3), ("abc", 4), ("abcdef", 3), ("a\0b", 5), ("0123456789ABCDEF", 16), ("0123456789ABCDEF0", 16)):
    val(f"bounded_len '{lab(_s)}' limit {_lim}", f"bounded_len({cxx_str(_s)}, {_lim})", lambda s=_s, l=_lim: sv.bounded_len(s, l))
val("bounded_len: a null pointer is empty", "bounded_len(nullptr, 9)", lambda: 0)
val("exact: equal literal", 'exact("SAVE", 4, "SAVE")', lambda: sv.exact("SAVE", 4, "SAVE"))
val("exact: a prefix is not exact", 'exact("SAVEX", 4, "SAVEX")', lambda: sv.exact("SAVEX", 4, "SAVEX"))
val("exact: a longer length is not exact", 'exact("SAVE", 3, "SAVE")', lambda: sv.exact("SAVE", 3, "SAVE"))
val("exact: a different character", 'exact("SAVF", 4, "SAVE")', lambda: sv.exact("SAVF", 4, "SAVE"))
val("exact: a null pointer", 'exact(nullptr, 4, "SAVE")', lambda: sv.exact(None, 4, "SAVE"))
val("starts_with: a longer string", 'starts_with("SAVE x", 6, "SAVE ")', lambda: sv.starts_with("SAVE x", 6, "SAVE "))
val("starts_with: too short", 'starts_with("SAVE", 4, "SAVE ")', lambda: sv.starts_with("SAVE", 4, "SAVE "))
val("starts_with: another verb", 'starts_with("save x", 6, "SAVE ")', lambda: sv.starts_with("save x", 6, "SAVE "))

# =========================== hex ids and the confirmation grammar ====================================================
for _id in (FX_ID, 0, U64, 0x00000000000000AB):
    for _k in range(0, 15):
        _s = fx_target(_k, _id)
        _x = f"[]{{ const TextBuf s = fx_target({_k}, 0x{_id:X}ULL); "
        val(f"is_hex16 target kind {_k} id {_id:X}", _x + "return is_hex16(s.c_str(), s.size()); }()", lambda s=_s: sv.is_hex16(s, len(s)))
        val(f"parse_hex16 target kind {_k} id {_id:X}", _x + "return parse_hex16(s.c_str(), s.size()); }()", lambda s=_s: sv.parse_hex16(s, len(s)))
        val(f"is_hex16 target kind {_k} id {_id:X} (NUL-terminated)", _x + "return is_hex16(s.c_str()); }()", lambda s=_s: sv.is_hex16(s))
for _id in (FX_ID, 0, U64):
    for _k in range(0, 28):
        _s = fx_conf(_k, _id)
        _x = f"[]{{ const TextBuf s = fx_conf({_k}, 0x{_id:X}ULL); "
        val(f"parse_phrase kind of confirmation kind {_k} id {_id:X}", _x + "return parse_phrase(s.c_str(), s.size()).kind; }()", lambda s=_s: sv.parse_phrase(s, len(s)).kind)
        val(f"parse_phrase id of confirmation kind {_k} id {_id:X}", _x + "return parse_phrase(s.c_str(), s.size()).id; }()", lambda s=_s: sv.parse_phrase(s, len(s)).id)
        val(f"parse_phrase kind of confirmation kind {_k} id {_id:X} (NUL-terminated)", _x + "return parse_phrase(s.c_str()).kind; }()", lambda s=_s: sv.parse_phrase(s).kind)
        for _ek in (sv.PHRASE_SAVE, sv.PHRASE_SAVE_REPLACE_CORRUPT, sv.PHRASE_INVALIDATE) if _id == FX_ID else ():
            val(f"phrase_equals confirmation kind {_k} vs expected_phrase kind {_ek}",
                _x + f"return phrase_equals(s.c_str(), s.size(), expected_phrase({_ek}, 0x{_id:X}ULL)); }}()",
                lambda s=_s, e=_ek, i=_id: sv.phrase_equals(s, len(s), sv.expected_phrase(e, i)))
            val(f"phrase_equals (NUL-terminated) confirmation kind {_k} vs expected_phrase kind {_ek}",
                _x + f"return phrase_equals(s.c_str(), expected_phrase({_ek}, 0x{_id:X}ULL)); }}()",
                lambda s=_s, e=_ek, i=_id: sv.phrase_equals(s, sv.expected_phrase(e, i)))
for _k in range(0, 5):
    for _id in (FX_ID, 0, U64, 0xAB):
        txt(f"expected_phrase kind {_k} id {_id:X}", f"expected_phrase({_k}, 0x{_id:X}ULL)", lambda k=_k, i=_id: sv.expected_phrase(k, i))
val("phrase_equals: an empty expected phrase never matches", 'phrase_equals("", 0, TextBuf{})', lambda: False)
val("phrase_equals: a null confirmation", "phrase_equals(nullptr, 21, expected_phrase(1, 1ULL))", lambda: False)
val("parse_phrase: a null confirmation", "parse_phrase(nullptr, 21).kind", lambda: 0)

# the sanitised echo of an operator token
_ECHO = ["CAPTURE", "", "a b", "SAVE\n", "x" * 23, "x" * 24, "x" * 25, "y" * 100, "café", "Rm -rf /", "UPPER_lower_09", "q'uote", "\"dq\"", "tab\tx",
         "ACCEPT_LIVE", "RETRY_APPLY", "PROVISION", "APPLY"]
for _t in _ECHO:
    txt(f"unsupported_action_text '{lab(_t)}' (NUL-terminated)", f"unsupported_action_text({cxx_str(_t)})", lambda t=_t: sv.unsupported_action_text(t))
    txt(f"unsupported_action_text '{lab(_t)}' (explicit length)", f"unsupported_action_text({cxx_str(_t)}, {len(_t.encode())})",
        lambda t=_t: sv.unsupported_action_text(t, len(t.encode())))
txt("unsupported_action_text: a null action", "unsupported_action_text(nullptr)", lambda: sv.unsupported_action_text(None))
txt("unsupported_action_text: an embedded NUL counts with an explicit length", 'unsupported_action_text("AB\\000CD", 5)', lambda: sv.unsupported_action_text("AB\0CD", 5))
txt("unsupported_action_text: an embedded NUL ends a NUL-terminated token", 'unsupported_action_text("AB\\000CD")', lambda: sv.unsupported_action_text("AB\0CD"))
for _tok in range(0, 6):
    txt(f"action_refusal_text token {_tok}", f'action_refusal_text({_tok}, "RETRY_APPLY", 11)', lambda t=_tok: sv.action_refusal_text(t, "RETRY_APPLY", 11))
txt("action_refusal_text: RESTORE", 'action_refusal_text(ACT_RESTORE, "RESTORE", 7)', lambda: sv.action_refusal_text(sv.ACT_RESTORE, "RESTORE", 7))
txt("action_refusal_text: ACKNOWLEDGE", 'action_refusal_text(ACT_ACKNOWLEDGE, "ACKNOWLEDGE", 11)', lambda: sv.action_refusal_text(sv.ACT_ACKNOWLEDGE, "ACKNOWLEDGE", 11))

# =========================== F2: the masked echo of an unsupported action ==================================================
# Every case form, embedded, at the truncation boundary, both overloads, explicit lengths and embedded NULs. The words failed / deferred (any case) are
# never published: every case-insensitive "fail" / "defer" of the SANITISED token becomes '?' (the matched letters only), the mask looks ECHO_LOOK bytes
# past the 24-byte cut (a cut occurrence is masked as far as visible) and the first 24 bytes are published. The hazard words never appear whole in the
# header's source: cxx_str splits them into adjacent literals and lab() escapes their first letter.
_ECHO_HZ = ["failed", "FAILED", "Failed", "fAiLeD", "deferred", "DEFERRED", "Deferred", "dEfErReD", "xDeFeRrEdx", "fail", "FAIL", "defer", "DEFER", "failure",
            "failfail", "faildefer", "deferfail", "FAILED_DEFERRED", "xfailedx", "a failed b", "fa il", "fai", "def", "efer", "ail", "fail_", "_fail", "faifail",
            "defdefer", "failé", "fail\0failed", "fa\0il", "defer\0deferred"]
_ECHO_HZ += ["x" * _k + _w for _k in range(18, 26) for _w in ("failed", "FAILED", "deferred", "DeFeReD")]
_ECHO_HZ += ["x" * 23 + "fox", "x" * 23 + "dex", "x" * 23 + "fa", "x" * 22 + "fai", "x" * 23 + "de", "x" * 24 + "fail", "x" * 40 + "failed", "y" * 12 + "defer" * 3]
for _t in _ECHO_HZ:
    _n = len(_t.encode("utf-8"))
    txt(f"unsupported_action_text '{lab(_t)}' (NUL-terminated)", f"unsupported_action_text({cxx_str(_t)})", lambda t=_t: sv.unsupported_action_text(t))
    txt(f"unsupported_action_text '{lab(_t)}' (explicit length)", f"unsupported_action_text({cxx_str(_t)}, {_n})", lambda t=_t, n=_n: sv.unsupported_action_text(t, n))
    txt(f"action_refusal_text unsupported echo of '{lab(_t)}'", f"action_refusal_text(0, {cxx_str(_t)}, {_n})", lambda t=_t, n=_n: sv.action_refusal_text(0, t, n))
for _t, _n in (("failed", 0), ("failed", 1), ("failed", 3), ("failed", 4), ("failed", 5), ("deferred", 4), ("deferred", 5), ("deferred", 6), ("xxxfailed", 6),
               ("xxxfailed", 7), ("FAILED", 3), ("fail\0failed", 4), ("fail\0failed", 11), ("fa\0il", 5), ("fail\0", 5), ("\0fail", 5), ("defer\0deferred", 14),
               ("failé", 6), ("x" * 23 + "deferred", 24), ("x" * 23 + "deferred", 25), ("x" * 23 + "deferred", 27), ("x" * 23 + "deferred", 28)):
    txt(f"unsupported_action_text '{lab(_t)}' cut to {_n} bytes", f"unsupported_action_text({cxx_str(_t)}, {_n})", lambda t=_t, n=_n: sv.unsupported_action_text(t, n))
_PS_TOKS = ["failed", "FAILED", "deferred", "xDeFeRrEdx", "fail", "defer", "failfail", "faildefer", "fai", "a failed b", "fail\0failed", "x" * 20 + "FAILED",
            "x" * 21 + "failed", "x" * 23 + "deferred", "x" * 24 + "fail", "x" * 23 + "fox"]
for _t in _PS_TOKS:
    _n = len(_t.encode("utf-8"))
    txt(f"put_sanitised '{lab(_t)}' (explicit length)", f"[]{{ TextBuf t; put_sanitised(t, {cxx_str(_t)}, {_n}); return t; }}()", lambda t=_t, n=_n: sv._sanitised(t, n))
    txt(f"put_sanitised '{lab(_t)}' (NUL-terminated)", f"[]{{ TextBuf t; put_sanitised(t, {cxx_str(_t)}); return t; }}()",
        lambda t=_t: sv._sanitised(t, sv.bounded_len(t, sv.ECHO_MAX + sv.ECHO_LOOK)))
txt("put_sanitised: a null pointer publishes nothing", "[]{ TextBuf t; put_sanitised(t, nullptr, 5); return t; }()", lambda: "")
for _t in ("failed", "xdeferx", "DeFeR", "fai", "failfail", "faildefer", "x" * 23 + "defer"):
    for _i in range(len(_t)):
        val(f"echo_masked '{lab(_t)}' byte {_i}", f"echo_masked({cxx_str(_t)}, {len(_t)}, {_i})", lambda t=_t, i=_i: 1 if sv._echo_mask(t, 99)[i] != t[i] else 0)

# =========================== arm TTL, integrity, overlay ==============================================================
for _born in (0, 1000, 4294960000, 4294967295):
    for _age in (0, 1, 119998, 119999, 120000, 120001, 4000000000):
        _now = (_born + _age) % 2 ** 32
        val(f"arm_expired born={_born} age={_age} (now={_now})", f"arm_expired({_now}u, {_born}u)", lambda n=_now, b=_born: sv.arm_expired(n, b))
for _op, _purpose in ((True, 2), (True, 1), (True, 0), (True, 3), (False, 2), (False, 1), (False, 0), (True, 255)):
    val(f"save_integrity_ok op={_op} purpose={_purpose}", f"save_integrity_ok({str(_op).lower()}, {_purpose})", lambda o=_op, p=_purpose: sv.save_integrity_ok(o, p))
for _cls in list(range(0, 10)) + [255]:
    for _u in (False, True):
        val(f"overlay_class cls={_cls} unconfirmed={_u}", f"overlay_class({_cls}, {str(_u).lower()})", lambda c=_cls, u=_u: sv.overlay_class(c, u))

# =========================== the SAVE gate: every golden-case row ====================================================
for _i, _row in enumerate(SG_ROWS):
    _x = f"[]{{ const SaveGateResult r = sg_run(SG_CASES[{_i}]); "
    val(f"sg row {_i}: code | arm_off_only << 8 | replace_corrupt << 9",
        _x + "return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8) | ((uint64_t) r.replace_corrupt << 9); }()",
        lambda r=_row: (lambda g: g.code | (g.arm_off_only << 8) | (g.replace_corrupt << 9))(sg_run(r)))
    txt(f"sg row {_i}: text", _x + "return r.text; }()", lambda r=_row: sg_run(r).text)
for _gate in range(0, 28):
    _x = f"[]{{ const SaveGateResult r = sg_run(SgRow{{0, 1, 0, 0, 0, 0, 5, 1, 0, 0, 1, 1, 0, {_gate}, SG_ACCEPT}}); "
    val(f"sg base with gate scenario {_gate}: code", _x + "return r.code; }()", lambda g=_gate: sg_run(SG_BASE_ROW + (g,)).code)
    txt(f"sg base with gate scenario {_gate}: obl", _x + "return r.obl; }()", lambda g=_gate: sg_run(SG_BASE_ROW + (g,)).obl)
    txt(f"sg base with gate scenario {_gate}: text", _x + "return r.text; }()", lambda g=_gate: sg_run(SG_BASE_ROW + (g,)).text)
# the capture gate decision can also be forged: unset / unknown codes never accept; MTOU is a slot refusal
_SG_FORGE = ("[]{ const SaveGateInputs si = fx_sg(0, 0, 5, 1, 0, 0, 1, 1, 1, 0); const TextBuf act = fx_action(0); const TextBuf tgt = fx_target(0, FX_ID); "
             "const TextBuf cnf = fx_conf(0, FX_ID); ecco_fbcap::GateResult gr{}; ")


def _forge_py(code, **slots):
    gr = cap.GateResult(code=code)
    for k, v in slots.items():
        setattr(gr, k, v)
    si = fx_sg(0, 0, 5, 1, 0, 0, 1, 1, 1, 0)
    return sv.save_gate_with_result(si, "SAVE", 4, fx_target(0, FX_ID), 16, fx_conf(0, FX_ID), 21, fx_gate(0), gr)


for _code in (0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 99, 255):
    _fx = _SG_FORGE + f"gr.code = {_code}; const SaveGateResult r = save_gate_with_result(si, act.c_str(), act.size(), tgt.c_str(), tgt.size(), cnf.c_str(), cnf.size(), fx_gate(0), gr); "
    val(f"save_gate_with_result forged capture gate code {_code}: code | arm_off_only << 8", _fx + "return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8); }()",
        lambda c=_code: (lambda r: r.code | (r.arm_off_only << 8))(_forge_py(c)))
    txt(f"save_gate_with_result forged capture gate code {_code}: text", _fx + "return r.text; }()", lambda c=_code: _forge_py(c).text)
_fx = (_SG_FORGE + "gr.code = ecco_fbcap::GATE_REFUSE_MTOU; gr.mtou = ecco_fbcap::SlotClass{ecco_fbcap::UNK_NOT_PROBED, ecco_fbcap::BASIS_NONE}; "
       "const SaveGateResult r = save_gate_with_result(si, act.c_str(), act.size(), tgt.c_str(), tgt.size(), cnf.c_str(), cnf.size(), fx_gate(0), gr); ")
val("save_gate_with_result: an MTOU slot refusal is SG_MTOU", _fx + "return r.code; }()",
    lambda: _forge_py(cap.GATE_REFUSE_MTOU, mtou=cap.SlotClass(cap.UNK_NOT_PROBED, cap.BASIS_NONE)).code)
txt("save_gate_with_result: an MTOU slot refusal text", _fx + "return r.text; }()",
    lambda: _forge_py(cap.GATE_REFUSE_MTOU, mtou=cap.SlotClass(cap.UNK_NOT_PROBED, cap.BASIS_NONE)).text)
for _a, _b in ((0, 0), (1, 0), (0, 1), (1, 1)):
    val(f"save_in_flight_gate op={_a} dispatch={_b}: code | arm_off_only << 8", f"[]{{ const SaveGateResult r = save_in_flight_gate({str(bool(_a)).lower()}, {str(bool(_b)).lower()}); "
        "return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8); }()", lambda a=_a, b=_b: (lambda r: r.code | (r.arm_off_only << 8))(sv.save_in_flight_gate(bool(a), bool(b))))
    txt(f"save_in_flight_gate op={_a} dispatch={_b}: text", f"save_in_flight_gate({str(bool(_a)).lower()}, {str(bool(_b)).lower()}).text", lambda a=_a, b=_b: sv.save_in_flight_gate(bool(a), bool(b)).text)
    val(f"invalidate_in_flight_gate op={_a} dispatch={_b}: code | arm_off_only << 8", f"[]{{ const InvalidateGateResult r = invalidate_in_flight_gate({str(bool(_a)).lower()}, {str(bool(_b)).lower()}); "
        "return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8); }()", lambda a=_a, b=_b: (lambda r: r.code | (r.arm_off_only << 8))(sv.invalidate_in_flight_gate(bool(a), bool(b))))
    txt(f"invalidate_in_flight_gate op={_a} dispatch={_b}: text", f"invalidate_in_flight_gate({str(bool(_a)).lower()}, {str(bool(_b)).lower()}).text",
        lambda a=_a, b=_b: sv.invalidate_in_flight_gate(bool(a), bool(b)).text)

# direct calls with string literals (NUL-terminated lengths and explicit ones): the public entry points exactly as a lambda calls them
_SG_ID = "0123456789ABCDEF"
_IG_HEX = format(GOLD_P["binding"], "016X")
for _label, _a, _t, _c in (("accept", "SAVE", _SG_ID, "SAVE " + _SG_ID), ("a lower-case action", "save", _SG_ID, "SAVE " + _SG_ID),
                           ("a lower-case target", "SAVE", _SG_ID.lower(), "SAVE " + _SG_ID), ("a wrong phrase", "SAVE", _SG_ID, "SAVE " + _SG_ID[:-1] + "0"),
                           ("a phrase cut short", "SAVE", _SG_ID, "SAVE " + _SG_ID[:-1]), ("a phrase with a trailing NUL", "SAVE", _SG_ID, "SAVE " + _SG_ID + "\0"),
                           ("RESTORE", "RESTORE", _SG_ID, "SAVE " + _SG_ID), ("a hazard action A", "failed", _SG_ID, "SAVE " + _SG_ID),
                           ("a hazard action B", "DEFERRED", _SG_ID, "SAVE " + _SG_ID), ("a hazard action C", "xFaIlDeFeRx", _SG_ID, "SAVE " + _SG_ID),
                           ("a hazard action D (long, cut)", "x" * 23 + "deferred", _SG_ID, "SAVE " + _SG_ID)):
    _x = f"save_gate_decide(fx_sg(0, 0, 5, 1, 0, 0, 1, 1, 1, 0), {cxx_str(_a)}, {len(_a)}, {cxx_str(_t)}, {len(_t)}, {cxx_str(_c)}, {len(_c)}, fx_gate(0))"
    _p = lambda a=_a, t=_t, c=_c: sv.save_gate_decide(fx_sg(0, 0, 5, 1, 0, 0, 1, 1, 1, 0), a, len(a), t, len(t), c, len(c), fx_gate(0))  # noqa: E731
    val(f"save_gate_decide direct [{_label}]: code", f"({_x}).code", lambda p=_p: p().code)
    txt(f"save_gate_decide direct [{_label}]: text", f"({_x}).text", lambda p=_p: p().text)
for _label, _a, _t, _c in (("accept", "INVALIDATE", _IG_HEX, "INVALIDATE " + _IG_HEX), ("SAVE", "SAVE", _IG_HEX, "INVALIDATE " + _IG_HEX),
                           ("the SAVE phrase", "INVALIDATE", _IG_HEX, "SAVE " + _IG_HEX), ("a lower-case target", "INVALIDATE", _IG_HEX.lower(), "INVALIDATE " + _IG_HEX.lower()),
                           ("a phrase with a trailing NUL", "INVALIDATE", _IG_HEX, "INVALIDATE " + _IG_HEX + "\0"),
                           ("a hazard action A", "FAILED", _IG_HEX, "INVALIDATE " + _IG_HEX), ("a hazard action B", "deferred", _IG_HEX, "INVALIDATE " + _IG_HEX),
                           ("a hazard action C (long, cut)", "x" * 21 + "failed", _IG_HEX, "INVALIDATE " + _IG_HEX)):
    _x = f"invalidate_gate_decide(fx_ig(IG_CASES[0]), {cxx_str(_a)}, {len(_a)}, {cxx_str(_t)}, {len(_t)}, {cxx_str(_c)}, {len(_c)})"
    _p = lambda a=_a, t=_t, c=_c: sv.invalidate_gate_decide(fx_ig(IG_ROWS[0]), a, len(a), t, len(t), c, len(c))  # noqa: E731
    val(f"invalidate_gate_decide direct [{_label}]: code", f"({_x}).code", lambda p=_p: p().code)
    txt(f"invalidate_gate_decide direct [{_label}]: text", f"({_x}).text", lambda p=_p: p().text)

# =========================== the SAVE gate refusal texts, slot by slot ================================================
_SLOT_KINDS = [("OBL_ACTIVE", "BASIS_LEASE"), ("OBL_ACTIVE", "BASIS_FBS_EPISODE"), ("OBL_STARTING", "BASIS_PRE_COMMIT"), ("OBL_STARTING", "BASIS_COMMITTED"),
               ("OBL_RESTORE_REQUIRED", "BASIS_NONE"), ("OBL_PENDING_CLEAR", "BASIS_NONE"), ("OBL_ENDING", "BASIS_OPERATOR_ACTION_RUNNING"),
               ("OBL_ENDING", "BASIS_RESTORE_RUNNING"), ("OBL_OPERATOR_NEEDED", "BASIS_NONE"), ("UNK_DURABLE_UNREADABLE", "BASIS_BOOT_READ_ERROR"),
               ("UNK_DURABLE_UNREADABLE", "BASIS_RUNTIME_PROBE"), ("UNK_METADATA_CORRUPT", "BASIS_BOOT_LOCKOUT"), ("UNK_METADATA_CORRUPT", "BASIS_RUNTIME_PROBE"),
               ("UNK_BOOT_NOT_LOADED", "BASIS_NONE"), ("UNK_DIVERGED", "BASIS_GHOST_RR"), ("UNK_DIVERGED", "BASIS_GHOST_PC"),
               ("UNK_DIVERGED", "BASIS_RAM_INCONSISTENT"), ("UNK_BUS_OR_LOCK_STUCK", "BASIS_OP_FLAG_UNATTRIBUTED"), ("UNK_NOT_PROBED", "BASIS_NONE"),
               ("OBL_CLEAR_PROVEN", "BASIS_NONE"), ("OBL_UNSET", "BASIS_NONE")]
for _slot_name, _slot in (("SLOT_R244", cap.SLOT_R244), ("SLOT_FP", cap.SLOT_FP), ("SLOT_DUMP", cap.SLOT_DUMP), ("SLOT_FBS", cap.SLOT_FBS), ("SLOT_MTOU", cap.SLOT_MTOU)):
    for _k, _b in _SLOT_KINDS:
        if _slot_name in ("SLOT_FP", "SLOT_FBS", "SLOT_MTOU") and (_k, _b) not in (("OBL_ACTIVE", "BASIS_LEASE"), ("UNK_METADATA_CORRUPT", "BASIS_BOOT_LOCKOUT"),
                                                                                  ("UNK_DURABLE_UNREADABLE", "BASIS_BOOT_READ_ERROR"), ("OBL_ACTIVE", "BASIS_FBS_EPISODE"),
                                                                                  ("OBL_PENDING_CLEAR", "BASIS_NONE"), ("OBL_STARTING", "BASIS_PRE_COMMIT"),
                                                                                  ("UNK_BOOT_NOT_LOADED", "BASIS_NONE"), ("OBL_UNSET", "BASIS_NONE")):
            continue
        txt(f"save_slot_refusal_text {_slot_name} {_k} {_b}", f'save_slot_refusal_text(ecco_fbcap::{_slot_name}, ecco_fbcap::SlotClass{{ecco_fbcap::{_k}, ecco_fbcap::{_b}}}, 0, "x", 0u)',
            lambda s=_slot, k=_k, b=_b: sv.save_slot_refusal_text(s, cap.SlotClass(getattr(cap, k), getattr(cap, b)), 0, "x", 0))
txt("save_slot_refusal_text SLOT_DUMP corrupt with containment K=5",
    'save_slot_refusal_text(ecco_fbcap::SLOT_DUMP, ecco_fbcap::SlotClass{ecco_fbcap::UNK_METADATA_CORRUPT, ecco_fbcap::BASIS_BOOT_LOCKOUT}, 5, "", 0u)',
    lambda: sv.save_slot_refusal_text(cap.SLOT_DUMP, cap.SlotClass(cap.UNK_METADATA_CORRUPT, cap.BASIS_BOOT_LOCKOUT), 5, "", 0))
txt("save_slot_refusal_text SLOT_FP corrupt ignores the Dump K",
    'save_slot_refusal_text(ecco_fbcap::SLOT_FP, ecco_fbcap::SlotClass{ecco_fbcap::UNK_METADATA_CORRUPT, ecco_fbcap::BASIS_BOOT_LOCKOUT}, 5, "", 0u)',
    lambda: sv.save_slot_refusal_text(cap.SLOT_FP, cap.SlotClass(cap.UNK_METADATA_CORRUPT, cap.BASIS_BOOT_LOCKOUT), 5, "", 0))
for _owner in ("Free Power", "Register 244 test", "Dump to Grid", "Fallback Profile", "clock correction", "clock verification", "manual write"):
    txt(f"save_slot_refusal_text SLOT_BUS busy, owner {_owner}", f'save_slot_refusal_text(ecco_fbcap::SLOT_BUS, ecco_fbcap::SlotClass{{ecco_fbcap::BUS_BUSY, ecco_fbcap::BASIS_BUS_TXN}}, 0, "{_owner}", 0u)',
        lambda o=_owner: sv.save_slot_refusal_text(cap.SLOT_BUS, cap.SlotClass(cap.BUS_BUSY, cap.BASIS_BUS_TXN), 0, o, 0))
for _age in (300, 4294967):
    txt(f"save_slot_refusal_text SLOT_BUS stuck, {_age} s", f'save_slot_refusal_text(ecco_fbcap::SLOT_BUS, ecco_fbcap::SlotClass{{ecco_fbcap::UNK_BUS_OR_LOCK_STUCK, ecco_fbcap::BASIS_LOCK_STUCK}}, 0, "", {_age}u)',
        lambda a=_age: sv.save_slot_refusal_text(cap.SLOT_BUS, cap.SlotClass(cap.UNK_BUS_OR_LOCK_STUCK, cap.BASIS_LOCK_STUCK), 0, "", a))
for _name in ("save_in_flight_text", "save_arm_off_text", "save_no_candidate_text", "save_expired_text", "save_id_format_text", "save_id_mismatch_text",
              "save_not_loaded_text", "save_prior_unknown_text", "save_anomaly_text", "save_hb_text", "save_time_text", "save_arms_text", "save_writes_text",
              "save_internal_text", "save_in_progress_text", "save_bus_quiet_text", "save_prior_changed_text", "save_generation_text", "save_internal_record_text",
              "invalidate_in_flight_text", "invalidate_arm_off_text", "invalidate_id_format_text", "invalidate_not_loaded_text", "invalidate_anomaly_text",
              "invalidate_prior_unknown_text", "invalidate_id_mismatch_text", "invalidate_busy_text", "invalidate_changed_text", "invalidate_internal_text",
              "save_witness_advanced_text"):
    txt(_name, f"{_name}()", lambda n=_name: getattr(sv, n)())
txt("save_phrase_text (plain)", "save_phrase_text(expected_phrase(PHRASE_SAVE, FX_ID))", lambda: sv.save_phrase_text(sv.expected_phrase(sv.PHRASE_SAVE, FX_ID)))
txt("save_phrase_text (REPLACE CORRUPT)", "save_phrase_text(expected_phrase(PHRASE_SAVE_REPLACE_CORRUPT, FX_ID))",
    lambda: sv.save_phrase_text(sv.expected_phrase(sv.PHRASE_SAVE_REPLACE_CORRUPT, FX_ID)))
txt("invalidate_phrase_text", "invalidate_phrase_text(expected_phrase(PHRASE_INVALIDATE, FX_ID))",
    lambda: sv.invalidate_phrase_text(sv.expected_phrase(sv.PHRASE_INVALIDATE, FX_ID)))
for _cls in list(range(0, 10)) + [255]:
    txt(f"invalidate_class_text {_cls}", f"invalidate_class_text({_cls})", lambda c=_cls: sv.invalidate_class_text(c))
    txt(f"invalidate_class_now_text {_cls}", f"invalidate_class_now_text({_cls})", lambda c=_cls: sv.invalidate_class_now_text(c))
    for _why in (0, 8, 9, 10):
        txt(f"save_class_text cls {_cls} why {_why}", f"save_class_text({_cls}, {_why})", lambda c=_cls, w=_why: sv.save_class_text(c, w))
for _e in (True, False):
    txt(f"invalidate_generation_text exhausted={_e}", f"invalidate_generation_text({str(_e).lower()})", lambda e=_e: sv.invalidate_generation_text(e))
for _fk in (0, 1, 2, 3, 4):
    txt(f"invalidate_fbs_text of FBS slot {_fk}", f"invalidate_fbs_text(ecco_fbcap::classify_fbs([]{{ ecco_fbcap::GateInputs g{{}}; g.boot_loaded = true; g.fbs_slot = {_fk}; return g; }}()))",
        lambda fk=_fk: sv.invalidate_fbs_text(cap.classify_fbs(cap.GateInputs(boot_loaded=True, fbs_slot=fk))))
txt("invalidate_fbs_text of an unloaded boot", "invalidate_fbs_text(ecco_fbcap::SlotClass{ecco_fbcap::UNK_BOOT_NOT_LOADED, ecco_fbcap::BASIS_NONE})",
    lambda: sv.invalidate_fbs_text(cap.SlotClass(cap.UNK_BOOT_NOT_LOADED, cap.BASIS_NONE)))

# =========================== save final: read failures, comparisons, L2 ===============================================
for _code in range(0, 9):
    for _step in (0, 1, 2, 3, 4, 9):
        txt(f"save_read_fail_text code {_code} step {_step}", f"save_read_fail_text({_code}, {_step}, 0)", lambda c=_code, s=_step: sv.save_read_fail_text(c, s, 0))
txt("save_read_fail_text: exception code 0x02 on step 2", "save_read_fail_text(ecco_fbcap::READ_EXCEPTION, 2, 2)", lambda: sv.save_read_fail_text(cap.READ_EXCEPTION, 2, 2))
txt("save_read_fail_text: exception code 0xFF on step 1", "save_read_fail_text(ecco_fbcap::READ_EXCEPTION, 1, 255)", lambda: sv.save_read_fail_text(cap.READ_EXCEPTION, 1, 255))
txt("save_read_fail_text: the idle timeout names the bus", "save_read_fail_text(ecco_fbcap::READ_IDLE_TIMEOUT, 0, 0)", lambda: sv.save_read_fail_text(cap.READ_IDLE_TIMEOUT, 0, 0))


class Wd:
    """A CaptureWords value: the golden words plus word changes."""

    def __init__(self, changes=None, base="ecco_fbcap::GOLDEN_WORDS", base_py=None):
        self.changes, self.base, self.base_py = dict(changes or {}), base, list(GW if base_py is None else base_py)

    def cxx(self) -> str:
        expr = self.base
        for k, v in self.changes.items():
            expr = f"ecco_fbcap::golden_words_with({expr}, {k}, {v}u)"
        return expr

    def py(self) -> list:
        w = list(self.base_py)
        for k, v in self.changes.items():
            w[k] = v
        return w


def WD(**kw) -> Wd:
    return Wd({int(k[1:]): v for k, v in kw.items()})


ALL_FFFF = Wd(base="ecco_fbcap::golden_words_all(65535u)", base_py=[65535] * 31)
ALL_ZERO = Wd(base="ecco_fbcap::golden_words_all(0u)", base_py=[0] * 31)
for _label, _w in (("first difference is register 244", WD(w0=0)), ("first is 256", WD(w1=501)), ("first is 274 (index 13)", WD(w13=3, w25=1)),
                   ("232 (index 19)", WD(w19=0x13)), ("247 (index 30)", WD(w30=65535)), ("both at 5 and 20: the lower index", WD(w20=0, w5=1)),
                   ("the passes agree", Wd()), ("widest values", ALL_ZERO)):
    _a = ALL_FFFF if _label == "widest values" else Wd()
    txt(f"save_changed_during_read_text: {_label}", f"save_changed_during_read_text({_a.cxx()}, {_w.cxx()})", lambda a=_a, w=_w: sv.save_changed_during_read_text(a.py(), w.py()))
    txt(f"save_changed_since_review_text: {_label}", f"save_changed_since_review_text({_a.cxx()}, {_w.cxx()})", lambda a=_a, w=_w: sv.save_changed_since_review_text(a.py(), w.py()))
for _label, _w in (("one refusal", WD(w0=0)), ("two refusals", WD(w0=0, w1=499)), ("three refusals: +1 more", WD(w0=0, w1=499, w8=101)), ("every refusal", ALL_FFFF),
                   ("a source refusal", WD(w15=0x27)), ("243", WD(w20=7)), ("no refusal at all", Wd())):
    txt(f"save_l2_text: {_label}", f"save_l2_text(ecco_fbcap::capture_refusals({_w.cxx()}, 8000u), {_w.cxx()})",
        lambda w=_w: sv.save_l2_text(cap.capture_refusals(w.py(), 8000), w.py()))

# =========================== the INVALIDATE gate: every golden-case row ==============================================
for _i, _row in enumerate(IG_ROWS):
    _x = f"[]{{ const InvalidateGateResult r = ig_run(IG_CASES[{_i}]); "
    val(f"ig row {_i}: code | arm_off_only << 8", _x + "return (uint64_t) r.code | ((uint64_t) r.arm_off_only << 8); }()",
        lambda r=_row: (lambda g: g.code | (g.arm_off_only << 8))(ig_run(r)))
    txt(f"ig row {_i}: text", _x + "return r.text; }()", lambda r=_row: ig_run(r).text)

# =========================== own-hold masking, the final gate, bus predicates =========================================
_OWN = ("g.bus.fallback_profile_op_in_progress = true; g.bus.fallback_profile_capture_dispatch_running = true; g.bus.manual_write_in_progress = true; ")


def _own(g: cap.GateInputs) -> cap.GateInputs:
    g.bus.fallback_profile_op_in_progress = True
    g.bus.fallback_profile_capture_dispatch_running = True
    g.bus.manual_write_in_progress = True
    return g


_PROBES = [("none", "ecco_fbcap::ProbeResults{}", cap.ProbeResults()),
           ("all clear", "ecco_fbcap::ProbeResults{ecco_fbcap::PROBE_ABSENT, ecco_fbcap::PROBE_CLEAR, ecco_fbcap::PROBE_ABSENT}",
            cap.ProbeResults(cap.PROBE_ABSENT, cap.PROBE_CLEAR, cap.PROBE_ABSENT)),
           ("FP unreadable", "ecco_fbcap::ProbeResults{ecco_fbcap::PROBE_UNREADABLE, ecco_fbcap::PROBE_CLEAR, ecco_fbcap::PROBE_ABSENT}",
            cap.ProbeResults(cap.PROBE_UNREADABLE, cap.PROBE_CLEAR, cap.PROBE_ABSENT)),
           ("Dump malformed", "ecco_fbcap::ProbeResults{ecco_fbcap::PROBE_ABSENT, ecco_fbcap::PROBE_MALFORMED, ecco_fbcap::PROBE_ABSENT}",
            cap.ProbeResults(cap.PROBE_ABSENT, cap.PROBE_MALFORMED, cap.PROBE_ABSENT)),
           ("R244 ghost restore required", "ecco_fbcap::ProbeResults{ecco_fbcap::PROBE_ABSENT, ecco_fbcap::PROBE_CLEAR, ecco_fbcap::PROBE_RESTORE_REQUIRED}",
            cap.ProbeResults(cap.PROBE_ABSENT, cap.PROBE_CLEAR, cap.PROBE_RESTORE_REQUIRED))]
_FINAL_PACK = ("(uint64_t) r.gr.code | ((uint64_t) r.gr.slot << 8) | ((uint64_t) ((r.gr.probe_fp ? 4 : 0) + (r.gr.probe_dump ? 2 : 0) + (r.gr.probe_r244 ? 1 : 0)) << 16) "
               "| ((uint64_t) r.gr.latch << 24)")


def _final_py(g, pr):
    r = sv.final_gate_decide(_own(g), pr)
    return r, r.gr.code | (r.gr.slot << 8) | ((r.gr.probe_fp * 4 + r.gr.probe_dump * 2 + r.gr.probe_r244) << 16) | (r.gr.latch << 24)


for _k in range(0, 28):
    for _pl, _pc, _pp in (_PROBES[0], _PROBES[1]):
        _x = f"[]{{ GateInputs g = fx_gate({_k}); {_OWN}const FinalGate r = final_gate_decide(g, {_pc}); "
        val(f"final_gate_decide [scenario {_k} + own holds, probes {_pl}]: code | slot | probes | latch", _x + f"return {_FINAL_PACK}; }}()",
            lambda k=_k, pp=_pp: _final_py(fx_gate(k), pp)[1])
        txt(f"final_gate_decide [scenario {_k} + own holds, probes {_pl}]: text", _x + "return r.text; }()", lambda k=_k, pp=_pp: _final_py(fx_gate(k), pp)[0].text)
        txt(f"final_gate_decide [scenario {_k} + own holds, probes {_pl}]: obl", _x + "return r.gr.obl; }()", lambda k=_k, pp=_pp: _final_py(fx_gate(k), pp)[0].gr.obl)
    val(f"gate_decide WITHOUT the masking [scenario {_k} + own holds]: code (the SAVE itself would be refused as in flight)",
        f"[]{{ GateInputs g = fx_gate({_k}); {_OWN}return ecco_fbcap::gate_decide(g, ecco_fbcap::ProbeResults{{}}).code; }}()", lambda k=_k: cap.gate_decide(_own(fx_gate(k)), cap.ProbeResults()).code)
for _pl, _pc, _pp in _PROBES[2:]:
    _x = f"[]{{ GateInputs g = fx_gate(0); {_OWN}const FinalGate r = final_gate_decide(g, {_pc}); "
    val(f"final_gate_decide [clear + own holds, probes {_pl}]: code | slot | probes | latch", _x + f"return {_FINAL_PACK}; }}()", lambda pp=_pp: _final_py(fx_gate(0), pp)[1])
    txt(f"final_gate_decide [clear + own holds, probes {_pl}]: text", _x + "return r.text; }()", lambda pp=_pp: _final_py(fx_gate(0), pp)[0].text)
val("final_gate_decide: a latched domain keeps its latch and is never rewritten",
    f"[]{{ GateInputs g = fx_gate(16); {_OWN}const FinalGate r = final_gate_decide(g, ecco_fbcap::ProbeResults{{ecco_fbcap::PROBE_PENDING_CLEAR, ecco_fbcap::PROBE_CLEAR, ecco_fbcap::PROBE_CLEAR}}); return r.gr.latch; }}()",
    lambda: _final_py(fx_gate(16), cap.ProbeResults(cap.PROBE_PENDING_CLEAR, cap.PROBE_CLEAR, cap.PROBE_CLEAR))[0].gr.latch)
for _name in ("fallback_profile_op_in_progress", "fallback_profile_capture_dispatch_running", "manual_write_in_progress", "correction_in_progress", "verification_pending",
              "verification_read_active", "free_power_operation_in_progress", "free_power_recovery_force_in_progress", "free_power_recovery_accept_in_progress",
              "reg244_apply_in_progress", "dump_operation_in_progress", "diag_write_lock_held"):
    # exactly three of the busy flags are masked; every other one still refuses (and the stuck-lock diagnostic alone is inert)
    val(f"final_gate_decide: only {_name} set -> code",
        f"[]{{ GateInputs g = fx_gate(0); g.bus.{_name} = true; return final_gate_decide(g, ecco_fbcap::ProbeResults{{}}).gr.code; }}()",
        lambda n=_name: (lambda g: (setattr(g.bus, n, True), sv.final_gate_decide(g, cap.ProbeResults()).gr.code)[1])(fx_gate(0)))
for _arm in ("free_power_write_enable", "dump_write_enable", "manual_config_write_enable"):
    val(f"final_gate_decide: the write arm {_arm} is not masked",
        f"[]{{ GateInputs g = fx_gate(0); {_OWN}g.{_arm} = true; return final_gate_decide(g, ecco_fbcap::ProbeResults{{}}).gr.code; }}()",
        lambda a=_arm: (lambda g: (setattr(g, a, True), sv.final_gate_decide(_own(g), cap.ProbeResults()).gr.code)[1])(fx_gate(0)))
val("final_gate_decide: the stuck-lock diagnostic with the masked mutex is not a stuck lock (the lock is the SAVE's own)",
    "[]{ GateInputs g = fx_gate(9); " + _OWN + "return final_gate_decide(g, ecco_fbcap::ProbeResults{}).gr.code; }()", lambda: _final_py(fx_gate(9), cap.ProbeResults())[0].gr.code)


def _populated() -> cap.GateInputs:
    g = fx_gate(0)
    g.free_power_write_enable, g.fbs_slot, g.probe_latch, g.bus.correction_in_progress = True, fd.FBS_OBLIGATION, 0x0123, True
    g.bus.diag_write_lock_held, g.bus.diag_write_lock_since_ms, g.bus.now_ms = True, 77, 99
    g.dump.dump_containment_state, g.fp.run_start, g.r244.run_apply = 3, True, True
    return _own(g)


def _exact_py() -> bool:
    from dataclasses import asdict
    g = _populated()
    want = asdict(g)
    for n in ("fallback_profile_op_in_progress", "fallback_profile_capture_dispatch_running", "manual_write_in_progress"):
        want["bus"][n] = False
    return asdict(sv.final_phase_inputs(g)) == want


val("final_phase_inputs: EXACTLY the three own holds are cleared (every other field of a fully populated input is untouched)",
    "[]{ GateInputs g = fx_gate(0); g.free_power_write_enable = true; g.fbs_slot = ecco_fbdurable::FBS_OBLIGATION; g.probe_latch = 0x0123; g.bus.correction_in_progress = true; "
    "g.bus.diag_write_lock_held = true; g.bus.diag_write_lock_since_ms = 77u; g.bus.now_ms = 99u; g.dump.dump_containment_state = 3; g.fp.run_start = true; g.r244.run_apply = true; "
    + _OWN + "const GateInputs m = final_phase_inputs(g); return fx_same_except_holds(m, g); }()", _exact_py)

for _op in (True, False):
    for _mu in (True, False):
        for _co in (True, False):
            for _te in (True, False):
                for _tb in (True, False):
                    val(f"commit_bus_quiet op={_op} mutex={_mu} correction={_co} tx_empty={_te} tx_blocked={_tb}",
                        f"commit_bus_quiet({str(_op).lower()}, {str(_mu).lower()}, {str(_co).lower()}, {str(_te).lower()}, {str(_tb).lower()})",
                        lambda o=_op, m=_mu, c=_co, e=_te, b=_tb: sv.commit_bus_quiet(o, m, c, e, b))
for _k in range(0, 12):
    for _tx in (0, 1, 2):
        val(f"invalidate_bus_idle bus scenario {_k} tx {_tx}", f"invalidate_bus_idle(fx_bus({_k}), {str(_tx != 1).lower()}, {str(_tx == 2).lower()})",
            lambda k=_k, t=_tx: sv.invalidate_bus_idle(fx_bus(k), t != 1, t == 2))
for _t, _e in ((True, 1790000000), (True, 0), (False, 1790000000), (False, 0), (True, 4294967295), (True, 1)):
    val(f"clock_trusted_for_save trusted={_t} epoch={_e}", f"clock_trusted_for_save({str(_t).lower()}, {_e}u)", lambda t=_t, e=_e: sv.clock_trusted_for_save(t, e))

# =========================== the intended record pair: every plan row =================================================
for _i, _row in enumerate(SP_ROWS):
    _x = f"[]{{ const Plan r = plan_save(sp_inputs(SP_CASES[{_i}])); "
    val(f"sp row {_i}: code | op << 8", _x + "return (uint64_t) r.code | ((uint64_t) r.op << 8); }()",
        lambda r=_row: (lambda p: p.code | (p.op << 8))(sv.plan_save(fx_save_mut(fx_save_inputs(r[0], r[1], r[2]), r[3]))))
    val(f"sp row {_i}: generation", _x + "return r.generation; }()", lambda r=_row: sv.plan_save(fx_save_mut(fx_save_inputs(r[0], r[1], r[2]), r[3])).generation)
    val(f"sp row {_i}: FNV digest of both records", _x + "return fx_digest(r); }()", lambda r=_row: plan_digest(sv.plan_save(fx_save_mut(fx_save_inputs(r[0], r[1], r[2]), r[3]))))
    txt(f"sp row {_i}: text", _x + "return r.text; }()", lambda r=_row: sv.plan_save(fx_save_mut(fx_save_inputs(r[0], r[1], r[2]), r[3])).text)
for _i, _row in enumerate(IP_ROWS):
    _x = f"[]{{ const Plan r = plan_invalidate(ip_inputs(IP_CASES[{_i}])); "
    val(f"ip row {_i}: code | op << 8", _x + "return (uint64_t) r.code | ((uint64_t) r.op << 8); }()",
        lambda r=_row: (lambda p: p.code | (p.op << 8))(sv.plan_invalidate(fx_inv_mut(fx_inv_inputs(r[0], r[1], r[2]), r[3]))))
    val(f"ip row {_i}: generation", _x + "return r.generation; }()", lambda r=_row: sv.plan_invalidate(fx_inv_mut(fx_inv_inputs(r[0], r[1], r[2]), r[3])).generation)
    val(f"ip row {_i}: FNV digest of both records", _x + "return fx_digest(r); }()", lambda r=_row: plan_digest(sv.plan_invalidate(fx_inv_mut(fx_inv_inputs(r[0], r[1], r[2]), r[3]))))
    txt(f"ip row {_i}: text", _x + "return r.text; }()", lambda r=_row: sv.plan_invalidate(fx_inv_mut(fx_inv_inputs(r[0], r[1], r[2]), r[3])).text)
# the forensic log of a REPLACE CORRUPT
for _pk in (0, 1, 4, 5, 6):
    for _part in (0, 1, 2):
        txt(f"replace_corrupt_log_text stored profile kind {_pk} part {_part}",
            f"[]{{ const FxP pr = fx_p({_pk}); return replace_corrupt_log_text(pr.load, pr.p, pr.len, {_part}); }}()",
            lambda k=_pk, pt=_part: (lambda pr: sv.replace_corrupt_log_text(pr[0], pr[1], pr[2], pt))(fx_p(k)))
val("replace_corrupt_log_text: a wrong-size record of 4294967295 bytes",
    "replace_corrupt_log_text(ecco_fallback::LOAD_WRONG_SIZE, ecco_fallback::FallbackProfileV1{}, 4294967295u, 0).size()",
    lambda: len(sv.replace_corrupt_log_text(fp.LOAD_WRONG_SIZE, fp.blank_profile(), 4294967295, 0)))

# =========================== the outcome of the writer call ===========================================================
for _a, _b in ((0, 0), (5, 0), (0, 5), (-1, 7), (0x1107, 0x1104), (-1, -1), (-2147483647, 0), (0, -2147483647)):
    val(f"first_non_ok({_a}, {_b})", f"first_non_ok({_a}, {_b})", lambda a=_a, b=_b: sv.first_non_ok(a, b))
for _a, _b in ((0, 0), (5, 7), (4294967295, 1), (4294967295, 4294967295), (2147483648, 2147483648), (1, 4294967295)):
    val(f"total_us({_a}u, {_b}u)", f"total_us({_a}u, {_b}u)", lambda a=_a, b=_b: sv.total_us(a, b))
_OUTCOME_CELLS = []
for _op in (1, 3, 2, 0, 7):
    _OUTCOME_CELLS += [
        (_op, 1, Tr(w_out=1, p_out=1), 1, 0), (_op, 1, Tr(w_out=1, p_out=1), 7, 6), (_op, 1, Tr(w_out=1, p_out=1), 4294967295, 4294967294),
        (_op, 2, Tr(w_err=0x1107, w_rb=2, w_out=2), 0, 7), (_op, 2, Tr(w_err=0x1104, w_rb=2, w_out=2), 0, 4294967295),
        (_op, 2, Tr(w_err=0x1101, w_rb=2, w_out=2), 0, 1), (_op, 2, Tr(w_out=1, p_err=0x1107, p_rb=2, p_out=2, adv=1), 8, 7),
        (_op, 0, Tr(w_err=0x1102, w_rb=3, w_out=0), 8, 7), (_op, 0, Tr(w_err=0, w_rb=1, w_out=0), 8, 7), (_op, 0, Tr(w_err=-1, w_rb=6, w_out=0), 8, 7),
        (_op, 0, Tr(w_err=0x103, w_rb=7, w_out=0), 8, 7), (_op, 0, Tr(w_out=1, p_err=0x1105, p_rb=5, p_out=0), 8, 7),
        (_op, 0, Tr(w_out=1, p_err=0, p_rb=4, p_out=0), 8, 7), (_op, 0, Tr(w_err=0x1102, w_rb=3, w_out=0, adv=1), 8, 7),
        (_op, 3, Tr(ref=0), 8, 7), (_op, 3, Tr(ref=1), 8, 7), (_op, 3, Tr(ref=2), 8, 7), (_op, 3, Tr(ref=3), 8, 7), (_op, 3, Tr(ref=4), 8, 7),
        (_op, 3, Tr(ref=5), 8, 7), (_op, 3, Tr(ref=6), 8, 7), (_op, 9, Tr(), 8, 7),
    ]
for _n, (_op, _o, _tr, _g, _pg) in enumerate(_OUTCOME_CELLS):
    txt(f"txn_outcome_text cell {_n} (op {_op}, outcome {_o}, w err {_tr.w_err} rb {_tr.w_rb}, p err {_tr.p_err} rb {_tr.p_rb}, adv {_tr.adv}, ref {_tr.ref}, g {_g}/{_pg})",
        f"txn_outcome_text({_op}, {_o}, {_tr.cxx()}, {_g}u, {_pg}u)", lambda op=_op, o=_o, t=_tr, g=_g, pg=_pg: sv.txn_outcome_text(op, o, t.py(), g, pg))
for _op in (1, 2, 3):
    for _o in (0, 1, 2, 3):
        for _tr in (Tr(), Tr(w_err=0x1107, w_rb=2, w_out=2, w_us=1234, p_us=5), Tr(w_out=1, p_out=1, w_us=70, p_us=80), Tr(w_err=-1, w_rb=7, w_out=0, w_us=4294967295, p_err=-1, p_rb=7, p_out=2, p_us=4294967295)):
            txt(f"txn_log_text op {_op} outcome {_o} w {_tr.w_err}/{_tr.w_rb}/{_tr.w_out}/{_tr.w_us} p {_tr.p_err}/{_tr.p_rb}/{_tr.p_out}/{_tr.p_us}",
                f"txn_log_text({_op}, {_o}, {_tr.cxx()}, 4294967295u)", lambda op=_op, o=_o, t=_tr: sv.txn_log_text(op, o, t.py(), 4294967295))
for _ref in range(0, 7):
    for _op in (1, 2):
        txt(f"txn_refusal_text op {_op} refusal {_ref}", f"txn_refusal_text({_op}, {_ref})", lambda op=_op, r=_ref: sv.txn_refusal_text(op, r))
for _g in (0, 1, 7, 4294967295):
    txt(f"saved_text {_g}", f"saved_text({_g}u)", lambda g=_g: sv.saved_text(g))
    txt(f"invalidated_text {_g}", f"invalidated_text({_g}u, {(_g + 1) & U32}u)", lambda g=_g: sv.invalidated_text(g, (g + 1) & U32))
    txt(f"invalidate_not_committed_text g {_g}", f"invalidate_not_committed_text(4294967295u, {_g}u)", lambda g=_g: sv.invalidate_not_committed_text(U32, g))
    txt(f"invalidate_witness_advanced_text g {_g}", f"invalidate_witness_advanced_text({_g}u)", lambda g=_g: sv.invalidate_witness_advanced_text(g))
for _e in (0, 0x1107, 4294967295):
    txt(f"save_not_committed_text err {_e}", f"save_not_committed_text({_e}u)", lambda e=_e: sv.save_not_committed_text(e))
    txt(f"save_unknown_text w err {_e}", f"save_unknown_text({Tr(w_err=_e if _e < 2**31 else -1, w_rb=3, w_out=0).cxx()})", lambda e=_e: sv.save_unknown_text(Tr(w_err=e if e < 2 ** 31 else -1, w_rb=3, w_out=0).py()))
    txt(f"invalidate_unknown_text w err {_e}", f"invalidate_unknown_text({Tr(w_err=_e if _e < 2**31 else -1, w_rb=3, w_out=0).cxx()})", lambda e=_e: sv.invalidate_unknown_text(Tr(w_err=e if e < 2 ** 31 else -1, w_rb=3, w_out=0).py()))
txt("save_unknown_text: the witness COMMITTED, the profile write is the unknown key", f"save_unknown_text({Tr(w_out=1, w_err=0, w_rb=1, p_err=0x1105, p_rb=5, p_out=0).cxx()})",
    lambda: sv.save_unknown_text(Tr(w_out=1, w_err=0, w_rb=1, p_err=0x1105, p_rb=5, p_out=0).py()))
# B2 werr / us in the b2 grammar (the D11 derivation)
txt("b2_text with werr / us derived from a refused witness write (first_non_ok, total_us)",
    f"ecco_fbcap::b2_text(0, ecco_fbcap::GOLDEN_PROFILE, 0, ecco_fbcap::GOLDEN_WITNESS, 0, first_non_ok(0x1107, 0), total_us(1200u, 0u))",
    lambda: cap.b2_text(0, GOLD_P, 0, fd.make_provision(7, GOLD_P["binding"], 6, 0x1122334455667788, fd.FALLBACK_PROFILE_KEY, 1, fd.PROV_OP_SAVE), 0,
                        sv.first_non_ok(0x1107, 0), sv.total_us(1200, 0)))
txt("b3_text with the SAVING state (D8): the candidate is consumed, obl and latch persist",
    'ecco_fbcap::b3_text(ecco_fbcap::CAPTURE_SAVING, false, 0, 0, 0, "FP:CA,DP:CA,R4:CA,MT:CN,FS:CA,BUS:BY", 0u, "-")',
    lambda: cap.b3_text(cap.CAPTURE_SAVING, False, 0, 0, 0, "FP:CA,DP:CA,R4:CA,MT:CN,FS:CA,BUS:BY", 0, "-"))
txt("candidate_ready_text (D8: the FB-B2 wording)", "ecco_fbcap::candidate_ready_text()", lambda: cap.candidate_ready_text())

# =========================== text lengths: no builder ever truncates ==================================================
_LEN_SLOTS = ("[]{ size_t m = 0; for (uint8_t s = 0; s < 6; s++) { for (uint8_t k = 0; k < 15; k++) { for (uint8_t b = 0; b < 20; b++) { "
              "const TextBuf t = save_slot_refusal_text(s, ecco_fbcap::SlotClass{k, b}, 255, \"Register 244 test\", 4294967u); if (t.overflow) return (size_t) 9999; "
              "if (t.size() > m) m = t.size(); } } } return m; }()")


def _len_slots():
    m = 0
    for s in range(6):
        for k in range(15):
            for b in range(20):
                t = sv.save_slot_refusal_text(s, cap.SlotClass(k, b), 255, "Register 244 test", 4294967)
                m = max(m, len(t))
                if len(sv._slot_body(s, cap.SlotClass(k, b), 255, "Register 244 test", 4294967)) + len(sv.SAVE_REFUSED_PREFIX) > cap.TEXT_CAP:
                    return 9999
    return m


val("length of the longest save_slot_refusal_text over every slot, kind and basis (never overflows; <= 200)", _LEN_SLOTS, _len_slots)
_LEN_OUT = ("[]{ size_t m = 0; for (uint8_t op = 1; op <= 3; op++) { for (uint8_t o = 0; o < 4; o++) { for (uint8_t rb = 0; rb < 9; rb++) { for (uint8_t adv = 0; adv < 2; adv++) { "
            "for (uint8_t rf = 0; rf < 6; rf++) { ecco_fbdurable::TxnResult r{}; r.w.err = -1; r.w.rb_class = rb; r.w.outcome = 0; r.w.us = 4294967295u; r.p.err = -1; r.p.rb_class = rb; "
            "r.p.us = 4294967295u; r.witness_advanced = adv; r.refusal = rf; const TextBuf t = txn_outcome_text(op, o, r, 4294967295u, 4294967294u); if (t.overflow) return (size_t) 9999; "
            "if (t.size() > m) m = t.size(); const TextBuf l = txn_log_text(op, o, r, 4294967295u); if (l.overflow) return (size_t) 9999; if (l.size() > m) m = l.size(); } } } } } return m; }()")


def _len_out():
    m = 0
    for op in (1, 2, 3):
        for o in range(4):
            for rb in range(9):
                for adv in (0, 1):
                    for rf in range(6):
                        r = Tr(w_err=-1, w_rb=rb, w_out=0, w_us=U32, p_err=-1, p_rb=rb, p_out=3, p_us=U32, adv=adv, ref=rf).py()
                        r.p.outcome = 0
                        m = max(m, len(sv.txn_outcome_text(op, o, r, U32, 4294967294)), len(sv.txn_log_text(op, o, r, U32)))
    return m


val("length of the longest txn_outcome_text / txn_log_text over every op, outcome, readback class, witness_advanced and refusal (never overflows)", _LEN_OUT, _len_out)
val("length of the SAVE UNKNOWN text at its widest", f"save_unknown_text({Tr(w_err=-1, w_rb=4, w_out=0).cxx()}).size()", lambda: len(sv.save_unknown_text(Tr(w_err=-1, w_rb=4, w_out=0).py())))
val("length of the INVALIDATED text at its widest (both generations 10 digits)", "invalidated_text(4294967294u, 4294967295u).size()", lambda: len(sv.invalidated_text(4294967294, 4294967295)))
val("length of the INVALIDATE UNKNOWN text at its widest", f"invalidate_unknown_text({Tr(w_err=-1, w_rb=4, w_out=0).cxx()}).size()", lambda: len(sv.invalidate_unknown_text(Tr(w_err=-1, w_rb=4, w_out=0).py())))
val("length of save_phrase_text / invalidate_phrase_text at their widest (id FFFFFFFFFFFFFFFF, REPLACE CORRUPT)",
    "save_phrase_text(expected_phrase(PHRASE_SAVE_REPLACE_CORRUPT, 0xFFFFFFFFFFFFFFFFULL)).size() * 1000u + invalidate_phrase_text(expected_phrase(PHRASE_INVALIDATE, 0xFFFFFFFFFFFFFFFFULL)).size()",
    lambda: len(sv.save_phrase_text(sv.expected_phrase(sv.PHRASE_SAVE_REPLACE_CORRUPT, U64))) * 1000 + len(sv.invalidate_phrase_text(sv.expected_phrase(sv.PHRASE_INVALIDATE, U64))))
val("length of the longest unsupported_action_text (a 100-byte token is cut at 24)", f"unsupported_action_text({cxx_str('y' * 100)}, 100).size()", lambda: len(sv.unsupported_action_text("y" * 100, 100)))
val("length of save_read_fail_text at its widest (exception code, longest block name)", "save_read_fail_text(ecco_fbcap::READ_EXCEPTION, 2, 255).size()", lambda: len(sv.save_read_fail_text(cap.READ_EXCEPTION, 2, 255)))
val("length of save_changed_since_review_text / save_changed_during_read_text at their widest (65535 words)",
    f"save_changed_since_review_text({ALL_FFFF.cxx()}, {ALL_ZERO.cxx()}).size() * 1000u + save_changed_during_read_text({ALL_FFFF.cxx()}, {ALL_ZERO.cxx()}).size()",
    lambda: len(sv.save_changed_since_review_text(ALL_FFFF.py(), ALL_ZERO.py())) * 1000 + len(sv.save_changed_during_read_text(ALL_FFFF.py(), ALL_ZERO.py())))
val("length of save_l2_text at its widest (every register wrong)", f"save_l2_text(ecco_fbcap::capture_refusals({ALL_FFFF.cxx()}, 8000u), {ALL_FFFF.cxx()}).size()",
    lambda: len(sv.save_l2_text(cap.capture_refusals(ALL_FFFF.py(), 8000), ALL_FFFF.py())))
val("lengths of the two replace_corrupt_log_text parts (hex of 48 bytes each)", "replace_corrupt_log_text(ecco_fallback::LOAD_OK, ecco_fbcap::GOLDEN_PROFILE, 0u, 0).size() * 1000u + "
    "replace_corrupt_log_text(ecco_fallback::LOAD_OK, ecco_fbcap::GOLDEN_PROFILE, 0u, 1).size()", lambda: len(sv.replace_corrupt_log_text(fp.LOAD_OK, GOLD_P, 0, 0)) * 1000 + len(sv.replace_corrupt_log_text(fp.LOAD_OK, GOLD_P, 0, 1)))
val("an overflowing text would be flagged: the capture TextBuf at its cap reports overflow on the 201st character (the control of every no-overflow golden)",
    "[]{ TextBuf t; for (size_t i = 0; i < 201; i++) put_char(t, 'x'); return t.overflow ? 1 : 0; }()", lambda: 1)


def lit_esc(s: str) -> str:
    """A question mark is written as backslash + question mark, so no `??x` trigraph can form inside a golden string literal."""
    return s.replace("?", BSQ)


BSQ = chr(92) + "?"


# ===========================================================================================================
def emit_block() -> str:
    """The C++ lines of the header's generated golden block, produced from GOLDENS and the Python mirror."""
    seen: set[str] = set()
    lines: list[str] = []
    for g in GOLDENS:
        assert g.label not in seen, f"duplicate golden label {g.label!r}"
        assert '"' not in g.label and "\\" not in g.label, g.label
        seen.add(g.label)
        v = g.py()
        if g.kind == "value":
            iv = int(v)
            lit = str(iv) if -(2 ** 31) <= iv < 2 ** 31 else f"{iv}u" if 0 <= iv < 2 ** 32 else f"0x{iv:X}ULL"
            lines.append(f"static_assert(({g.cxx}) == {lit}, \"FB-B2 value: {g.label}\");")
        elif g.kind == "text":
            s = str(v)
            assert '"' not in s and "\\" not in s and "\n" not in s and "\0" not in s, s
            lines.append(f"static_assert(text_is(\"{lit_esc(s)}\", {g.cxx}), \"FB-B2 text: {g.label}\");")
        else:
            s = str(v)
            assert '"' not in s and "\\" not in s, s
            lines.append(f"static_assert(str_is({g.cxx}, \"{lit_esc(s)}\"), \"FB-B2 name: {g.label}\");")
    return "\n".join(lines) + "\n"

# the capture gate's refusals rendered with the SAVE wording, scenario by scenario
for _k in range(0, 28):
    txt(f"save_gate_refusal_text of gate_decide over scenario {_k}",
        f"[]{{ const GateInputs g = fx_gate({_k}); return save_gate_refusal_text(ecco_fbcap::gate_decide(g, ecco_fbcap::ProbeResults{{}}), g); }}()",
        lambda k=_k: sv.save_gate_refusal_text(cap.gate_decide(fx_gate(k), cap.ProbeResults()), fx_gate(k)))


# ===========================================================================================================
# Compiler discovery, TU helpers
# ===========================================================================================================
STRICT = ["-Wall", "-Wextra", "-Werror"]


def find_compiler() -> str | None:
    env = os.environ.get("ECCO_CXX")
    if env:
        return env
    for name in ("g++", "c++"):
        found = shutil.which(name)
        if found:
            return found
    patterns = []
    local = os.environ.get("LOCALAPPDATA")
    if local:
        patterns.append(os.path.join(local, "esphome", "Cache", "idf", "tools", "xtensa-esp-elf", "*",
                                     "xtensa-esp-elf", "bin", "xtensa-esp32-elf-g++*"))
    home = Path.home()
    patterns += [str(home / ".esphome" / "**" / "xtensa-esp32-elf-g++*"),
                 str(home / ".platformio" / "packages" / "toolchain-xtensa*" / "bin" / "xtensa-esp32-elf-g++*"),
                 str(home / ".espressif" / "tools" / "xtensa-esp-elf" / "*" / "xtensa-esp-elf" / "bin" / "xtensa-esp32-elf-g++*")]
    for pattern in patterns:
        hits = sorted(glob.glob(pattern, recursive=True))
        if hits:
            return hits[-1]
    return None


def run(cmd, **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=1800, **kw)


class Toolchain:
    """Stages the four headers in an include directory and compiles translation units against it."""

    def __init__(self, cxx: str) -> None:
        self.cxx = cxx
        self.tmp = Path(tempfile.mkdtemp(prefix="ecco_fbb2_save_"))

    def stage(self, name: str, save_text: str | None = None) -> Path:
        inc = self.tmp / name / "include"
        inc.mkdir(parents=True, exist_ok=True)
        for src in (FBA_PATH, MODEL_PATH, CAP_PATH):
            shutil.copy(src, inc / src.name)
        (inc / HEADER_PATH.name).write_text(read_header() if save_text is None else save_text, encoding="utf-8", newline="\n")
        return inc

    def compile(self, inc: Path, source: str, std: str = "gnu++17", extra=()) -> subprocess.CompletedProcess:
        tu = inc.parent / f"tu_{abs(hash((source, std, tuple(extra)))) % 10 ** 9}.cpp"
        tu.write_text(source, encoding="utf-8", newline="\n")
        return run([self.cxx, f"-std={std}", "-fsyntax-only", *STRICT, *extra, "-I", str(inc), str(tu)])


TWICE = '#include "ecco_fallback_save.h"\n#include "ecco_fallback_save.h"\nint main() { return 0; }\n'


# ===========================================================================================================
def section_compiler(tc: Toolchain):
    print("[1] compiler")
    check("the save header exists", HEADER_PATH.is_file(), str(HEADER_PATH))
    version = run([tc.cxx, "--version"]).stdout.splitlines()[:1]
    print(f"  info  compiler: {tc.cxx}")
    print(f"  info  version:  {version[0] if version else '?'}")
    macros = run([tc.cxx, "-x", "c++", "-dM", "-E", os.devnull]).stdout
    check("the compiler is GCC (defines __GNUC__, not __clang__) - the constexpr limits the headers rely on are GCC's",
          "#define __GNUC__ " in macros and "__clang__" not in macros)


def section_compile(tc: Toolchain):
    print("[2] compile: standalone, gnu++17 / gnu++20, -Wall -Wextra -Werror, every static_assert and every golden-case table")
    inc = tc.stage("clean")
    check("the include directory holds ONLY the FB-A profile header, the FB-B0 model header, the FB-B1 capture header and the save header",
          sorted(p.name for p in inc.iterdir()) == sorted([FBA_PATH.name, MODEL_PATH.name, CAP_PATH.name, HEADER_PATH.name]))
    for std in ("gnu++17", "gnu++20"):
        r = tc.compile(inc, TWICE, std)
        check(f"the header compiles under -std={std} {' '.join(STRICT)} -fsyntax-only (included twice: #pragma once) - every golden static_assert, "
              "golden-case table and layout proof holds", r.returncode == 0, (r.stderr or r.stdout)[-2500:])
    r = tc.compile(inc, '#include "ecco_fallback_save.h"\nint main() { return 0; }\n', "gnu++17", ["-O2"])
    check("...and optimised (-O2) too", r.returncode == 0, (r.stderr or r.stdout)[-1500:])
    r = tc.compile(inc, '#include "ecco_fallback_save.h"\n#include "ecco_fallback_capture.h"\n#include "ecco_fallback_durable_model.h"\nint main() { return 0; }\n')
    check("the save header composes with the capture and model headers included before or after it", r.returncode == 0, (r.stderr or "")[-600:])


def check_value_line(g: Golden, line: str) -> bool:
    m = re.fullmatch(r'static_assert\(\((.*)\) == (-?\d+u?|0x[0-9A-F]+ULL), "FB-B2 value: (.*)"\);', line)
    if not m or m.group(3) != g.label or m.group(1) != g.cxx:
        return False
    lit = m.group(2)
    got = int(lit[:-3], 16) if lit.endswith("ULL") else int(lit.rstrip("u"))
    return got == int(g.py())


def check_text_line(g: Golden, line: str) -> bool:
    m = re.fullmatch(r'static_assert\(text_is\("([^"]*)", (.*)\), "FB-B2 text: (.*)"\);', line)
    return bool(m) and m.group(3) == g.label and m.group(2) == g.cxx and m.group(1) == lit_esc(str(g.py()))


def check_str_line(g: Golden, line: str) -> bool:
    m = re.fullmatch(r'static_assert\(str_is\((.*), "([^"]*)"\), "FB-B2 name: (.*)"\);', line)
    return bool(m) and m.group(3) == g.label and m.group(1) == g.cxx and m.group(2) == lit_esc(str(g.py()))


def default_refusal(kind: str, struct: str, fld: str) -> int:
    """The mirror's decision for the all-pass input of `kind` with exactly ONE field put back to its dataclass default."""
    if kind == "sgd":
        si = fx_sg(0, 0, 5, 1, 0, 0, 1, 1, 1, 0)
        setattr(si, fld, getattr(sv.SaveGateInputs(), fld))
        t, c = fx_target(0, FX_ID), fx_conf(0, FX_ID)
        return sv.save_gate_decide(si, "SAVE", 4, t, len(t), c, len(c), fx_gate(0)).code
    if kind == "igd":
        id_ = fx_ig(IG_ROWS[0]).p["binding"]
        in_ = fx_ig(IG_ROWS[0])
        setattr(in_, fld, getattr(sv.InvalidateGateInputs(), fld))
        t, c = fx_target(0, id_), fx_conf(2, id_)
        return sv.invalidate_gate_decide(in_, "INVALIDATE", 10, t, len(t), c, len(c)).code
    if kind == "spd":
        in_ = fx_save_inputs(1, 1, 0)
        setattr(in_, fld, getattr(sv.SavePlanInputs(), fld))
        return sv.plan_save(in_).code
    in_ = fx_inv_inputs(1, 1, 0)
    setattr(in_, fld, getattr(sv.InvalidatePlanInputs(), fld))
    return sv.plan_invalidate(in_).code


def section_parity():
    print("[3] PARITY: every golden value / string / table row equals what the Python mirror produces")
    text = read_header()
    begin = text.index("// ---- GENERATED-GOLDENS-BEGIN")
    end = text.index("// ---- GENERATED-GOLDENS-END ----")
    block = text[text.index("\n", begin) + 1:end].replace("\r\n", "\n")
    lines = block.splitlines()
    check(f"the header's generated golden block ({len(lines)} static_asserts) is exactly what this file emits from the Python mirror "
          "(regenerate: python registry/tests/test_fallback_save_host_compile.py --emit-goldens <file>, then paste between the markers)",
          block == emit_block())
    check("one static_assert line per golden, labels unique and every one parsed", len(lines) == len(GOLDENS) and len({g.label for g in GOLDENS}) == len(GOLDENS))
    bad = [g.label for g, line in zip(GOLDENS, lines) if not {"value": check_value_line, "text": check_text_line, "str": check_str_line}[g.kind](g, line)]
    check(f"each of the {len(GOLDENS)} header goldens parses and equals the mirror's value exactly (independent regex parse)", not bad, str(bad[:5]))
    kinds = {k: sum(1 for g in GOLDENS if g.kind == k) for k in ("value", "text", "str")}
    print(f"  info  goldens: {kinds}")
    check("the golden set covers every public function by name",
          all(any(name in g.cxx for g in GOLDENS) for name in (
              "action_token", "is_invalidate_action", "action_refusal_text", "unsupported_action_text", "is_hex16", "parse_hex16", "parse_phrase",
              "expected_phrase", "phrase_equals", "arm_expired", "save_integrity_ok", "overlay_class", "save_in_flight_gate", "save_gate_decide",
              "save_gate_with_result", "save_gate_refusal_text", "final_phase_inputs", "final_gate_decide", "commit_bus_quiet", "clock_trusted_for_save",
              "plan_save", "invalidate_in_flight_gate", "invalidate_gate_decide", "invalidate_bus_idle", "plan_invalidate", "txn_outcome_text",
              "first_non_ok", "total_us", "txn_log_text", "replace_corrupt_log_text", "bounded_len", "exact", "starts_with", "echo_char_ok",
              "hex_digit_ok", "save_slot_refusal_text", "save_read_fail_text", "save_changed_during_read_text", "save_changed_since_review_text",
              "save_l2_text", "save_class_text", "invalidate_class_text", "invalidate_fbs_text", "txn_refusal_text", "saved_text", "invalidated_text",
              "slot_label", "txn_name", "txn_op_name", "key_name", "rb_name", "put_sanitised", "echo_fold", "echo_masked")))
    # hand-written case tables: the row counts and widths, and every row re-derived from the mirror
    tabs = {"SG_CASES": (15, 100), "IG_CASES": (15, 80), "SP_CASES": (9, 40), "IP_CASES": (7, 20)}
    ok = True
    for name, (width, minrows) in tabs.items():
        rows = table_rows(text, name)
        ok = ok and all(len(r) == width for r in rows) and len(rows) >= minrows
    check(f"the golden-case tables parse: SAVE gate {len(SG_ROWS)} rows x 15, INVALIDATE gate {len(IG_ROWS)} x 15, SAVE plan {len(SP_ROWS)} x 9, INVALIDATE plan {len(IP_ROWS)} x 7", ok)
    bad = [i for i, r in enumerate(SG_ROWS) if sg_run(r).code != r[14]]
    check("every SAVE gate golden-case row (expected code written by hand from S1 8.5, first failure wins) equals the mirror's decision", not bad, str(bad[:5]))
    bad = [i for i, r in enumerate(IG_ROWS) if ig_run(r).code != r[14]]
    check("every INVALIDATE gate golden-case row (S2 4.2 as amended by master 4.8) equals the mirror's decision", not bad, str(bad[:5]))
    bad = []
    for i, r in enumerate(SP_ROWS):
        in_ = fx_save_mut(fx_save_inputs(r[0], r[1], r[2]), r[3])
        plan = sv.plan_save(in_)
        want_ok = r[4] == sv.PLAN_OK
        if plan.code != r[4]:
            bad.append((i, "code", plan.code, r[4]))
        elif want_ok:
            _pl, _p, _pn = in_.p_load, in_.p, in_.p_stored_len
            auth = fd.fba_authentic(fp.classify_profile(_pl, _p))
            if (plan.generation, plan.op, plan.w_new["prior_generation"], plan.w_new["prior_binding"]) != (
                    r[5], r[6], r[7], _p["binding"] if r[8] else 0) or not fd.validate_transition(
                    plan.w_new, in_.w, (in_.w_load, in_.w_stored_len), plan.p_new, _p, (_pl, _pn)) or (auth != bool(r[8])):
                bad.append((i, "fields"))
    check("every SAVE plan golden-case row (generation, op, witness prior_* decided by hand from FB_B2_IMPLEMENTATION_NOTES.md section 6) equals the mirror and is accepted by the FB-B0 validate_transition",
          not bad, str(bad[:4]))
    bad = []
    for i, r in enumerate(IP_ROWS):
        in_ = fx_inv_mut(fx_inv_inputs(r[0], r[1], r[2]), r[3])
        plan = sv.plan_invalidate(in_)
        if plan.code != r[4]:
            bad.append((i, "code", plan.code, r[4]))
        elif r[4] == sv.PLAN_OK and (plan.generation != r[5] or plan.w_new["prior_generation"] != r[6] or not fd.validate_transition(
                plan.w_new, in_.w, (in_.w_load, in_.w_stored_len), plan.p_new, in_.p, (in_.p_load, in_.p_stored_len))):
            bad.append((i, "fields"))
    check("every INVALIDATE plan golden-case row equals the mirror and is accepted by the FB-B0 validate_transition", not bad, str(bad[:4]))
    # enum numbering and constants parity
    enum_bad, n_enum = [], 0
    for ename, body in re.findall(r"enum (\w+) : uint8_t \{(.*?)\};", text, re.S):
        for name, value in re.findall(r"(\w+) = (\d+)", re.sub(r"//[^\n]*", "", body)):
            n_enum += 1
            if not hasattr(sv, name) or getattr(sv, name) != int(value):
                enum_bad.append((ename, name, value))
    check(f"every enumerator of the header's {n_enum} (explicit numbers) equals the mirror's constant of the same name", n_enum >= 50 and not enum_bad, str(enum_bad[:4]))
    const_bad = []
    for name, value in re.findall(r"^constexpr (?:uint8_t|uint16_t|uint32_t|size_t|bool) (\w+) = (\w+?)u?;", text, re.M):
        if hasattr(sv, name) and name.isupper():
            want = {"true": True, "false": False}.get(value, int(value, 0) if re.fullmatch(r"(0x)?[0-9A-Fa-f]+", value) else None)
            if want is not None and getattr(sv, name) != want:
                const_bad.append((name, value))
    check("every scalar constant the header defines equals the mirror's", not const_bad, str(const_bad))
    check("the two refusal prefixes are the same literals in both languages",
          'constexpr char SAVE_REFUSED_PREFIX[] = "SAVE REFUSED - ";' in text and 'constexpr char INVALIDATE_REFUSED_PREFIX[] = "INVALIDATE REFUSED - ";' in text
          and sv.SAVE_REFUSED_PREFIX == "SAVE REFUSED - " and sv.INVALIDATE_REFUSED_PREFIX == "INVALIDATE REFUSED - ")
    # F2: no echoed token can match a card hazard regex (re.I), and no echo contains the words fail / defer at all
    echoes = [str(sv.unsupported_action_text(t, len(t.encode("utf-8")))) for t in _ECHO_HZ] + [str(sv.unsupported_action_text(t)) for t in _ECHO_HZ]
    echoes += [str(sv.save_gate_decide(fx_sg(0, 0, 5, 1, 0, 0, 1, 1, 1, 0), t, len(t.encode()), fx_target(0, FX_ID), 16, fx_conf(0, FX_ID), 21, fx_gate(0)).text)
               for t in _ECHO_HZ]
    bad = [e for e in echoes if HAZARD_RX.search(e) or re.search(r"(?i)fail|defer", e)]
    check(f"none of the {len(echoes)} hazard-token echoes of the mirror (both overloads and the SAVE gate) matches an Energy Actions card pattern (re.I) "
          "or contains the letters fail / defer in any case", not bad, str(bad[:3]))
    # SEM-4: every fail-closed default assertion of the header is re-derived from the mirror's dataclass defaults
    dl = re.findall(r'static_assert\((sgd|igd|spd|ipd)\(dflt<&(\w+)::(\w+)>\((\w+)\(\)\)\) == (\w+), "FB-B2 default: (\w+)\.(\w+) refuses \((\w+)\)"\);', text)
    want_fields = {
        "SaveGateInputs": ["arm_was_on", "cand_valid", "cand_saveable", "cand_id", "cand_ms", "cand_writes_fp", "writes_fp_now", "boot_loaded", "unconfirmed",
                           "read_anomaly", "hb_ok", "time_trusted"],
        "InvalidateGateInputs": ["arm_was_on", "boot_loaded", "read_anomaly", "unconfirmed", "cls", "p_load", "p", "seen_hw_gen", "tx_buffer_empty", "tx_blocked",
                                 "fbs_slot"],
        "SavePlanInputs": ["p_load", "p", "cls", "read_anomaly", "unconfirmed", "seen_hw_gen", "cand_prior_class", "cand_prior_gen", "cand_prior_binding",
                           "captured_epoch"],
        "InvalidatePlanInputs": ["p_load", "p", "cls", "read_anomaly", "unconfirmed", "seen_hw_gen", "target_id"]}
    kind_of = {"sgd": "SaveGateInputs", "igd": "InvalidateGateInputs", "spd": "SavePlanInputs", "ipd": "InvalidatePlanInputs"}
    bad, found = [], {}
    for kind, struct, fld, passfn, expect, struct2, fld2, expect2 in dl:
        found.setdefault(struct, []).append(fld)
        if kind_of[kind] != struct or (struct, fld, expect) != (struct2, fld2, expect2) or not hasattr(sv, expect):
            bad.append(("label", kind, struct, fld, expect))
            continue
        got = default_refusal(kind, struct, fld)
        if got != getattr(sv, expect):
            bad.append((struct, fld, got, expect))
    check(f"the {len(dl)} fail-closed-default static_asserts of the header (one per field that must refuse) equal what the mirror does with its own dataclass "
          "defaults, and cover exactly the field set the model lists",
          not bad and {k: sorted(v) for k, v in found.items()} == {k: sorted(v) for k, v in want_fields.items()}, str(bad[:4]) + str(
              {k: sorted(set(want_fields[k]) ^ set(found.get(k, []))) for k in want_fields}))
    controls = (sv.save_gate_decide(fx_sg(0, 0, 5, 1, 0, 0, 1, 1, 1, 0), "SAVE", 4, fx_target(0, FX_ID), 16, fx_conf(0, FX_ID), 21, fx_gate(0)).code == sv.SG_ACCEPT
                and ig_run(IG_ROWS[0]).code == sv.IG_ACCEPT and sv.plan_save(fx_save_inputs(1, 1, 0)).code == sv.PLAN_OK
                and sv.plan_invalidate(fx_inv_inputs(1, 1, 0)).code == sv.PLAN_OK)
    check("the four all-pass default-control inputs accept in the mirror (and the header asserts the same)",
          controls and all(s in text for s in ("sgd(fx_sg_pass()) == SG_ACCEPT", "igd(fx_ig_pass()) == IG_ACCEPT", "spd(fx_sp_pass()) == PLAN_OK", "ipd(fx_ip_pass()) == PLAN_OK")))


# ===========================================================================================================
# Randomized parity: the SAME seeded generator in C++ (constexpr, evaluated by the compiler) and in Python
# ===========================================================================================================
RANDOM_CASES = 120
RANDOM_COMPONENTS = ("tokens and grammar", "SAVE gate", "INVALIDATE gate", "plan_save", "plan_invalidate", "outcome texts", "timing masks and final gate")

RANDOM_TU_CXX = r'''#include "ecco_fallback_save.h"
using namespace ecco_fbcap;
using namespace ecco_fbsave;
namespace rnd {
struct Rng {
  uint32_t s;
  constexpr uint32_t next() { s = s * 1664525u + 1013904223u; return s; }
  constexpr uint32_t below(uint32_t n) { return (next() >> 8) % n; }
};
constexpr uint64_t u64(Rng &r) { const uint64_t hi = r.next(); const uint64_t lo = r.next(); return (hi << 32) | lo; }
struct Dg {
  uint64_t h = ecco_fallback::FNV1A64_OFFSET_BASIS;
  constexpr void u(uint64_t v) { h = step_le(h, v, 8); }
  constexpr void s(const char *t) {
    for (; *t != '\0'; t++)
      h = ecco_fallback::fnv1a64_step(h, (uint8_t) *t);
    h = ecco_fallback::fnv1a64_step(h, 0xFF);
  }
  constexpr void t(const TextBuf &x) { s(x.c_str()); }
};
constexpr uint16_t POOL[] = {0, 1, 2, 3, 0x20, 0x27, 59, 60, 99, 100, 101, 499, 500, 2359, 2400, 3000, 3001, 8000, 8001, 65535};
constexpr uint32_t POOL_N = sizeof(POOL) / sizeof(POOL[0]);
constexpr CaptureWords gen_words(Rng &r, uint32_t pchange) {
  CaptureWords w = GOLDEN_WORDS;
  for (size_t k = 0; k < REG_COUNT; k++) {
    const uint32_t c = r.below(100);
    if (c < pchange) {
      const uint32_t pick = r.below(100);
      if (pick < 85) {
        const uint32_t i = r.below(POOL_N);
        w[k] = POOL[i];
      } else {
        w[k] = (uint16_t) r.below(65536);
      }
    }
  }
  return w;
}
constexpr uint8_t gen_load(Rng &r) {
  const uint32_t x = r.below(100);
  return x < 70 ? 0 : x < 80 ? 1 : x < 88 ? 2 : x < 95 ? 3 : 4;
}
struct Rec {
  uint8_t load;
  ecco_fallback::FallbackProfileV1 p;
  uint32_t len;
};
constexpr void maybe_set(Rng &r, uint16_t *arr) {
  const uint32_t c = r.below(100);
  if (c < 25) {
    const uint32_t i = r.below(6);
    const uint32_t j = r.below(POOL_N);
    arr[i] = POOL[j];
  }
}
constexpr Rec gen_profile(Rng &r) {
  constexpr uint32_t GENP[5] = {0u, 1u, 7u, 8u, 4294967295u};
  constexpr uint16_t R244P[5] = {0, 1, 2, 3, 65535};
  constexpr uint32_t EPOCHP[3] = {0u, 1790000000u, 4294967295u};
  constexpr uint32_t LENP[5] = {0u, 40u, 95u, 97u, 1000u};
  constexpr uint32_t CGEN[3] = {1u, 7u, 8u};
  ecco_fallback::FallbackProfileV1 p = GOLDEN_PROFILE;
  const uint32_t mode = r.below(100);
  if (mode < 50) {
    { const uint32_t i = r.below(3); p.generation = CGEN[i]; }
    { const uint32_t f = r.below(2); p.flags = (uint16_t) f; }
    { const uint32_t i = r.below(3); p.captured_epoch = EPOCHP[i]; }
    p = ecco_fallback::seal_profile(p);
    const uint32_t lc = r.below(100);
    const uint8_t cload = lc < 90 ? 0 : lc < 95 ? 1 : 3;
    if (cload != 0) p = ecco_fallback::FallbackProfileV1{};
    return {cload, p, 0};
  }
  if (r.below(100) < 35) { const uint32_t i = r.below(5); p.generation = GENP[i]; }
  if (r.below(100) < 30) { const uint32_t i = r.below(5); p.reg244 = R244P[i]; }
  if (r.below(100) < 25) { const uint32_t i = r.below(4); p.flags = (uint16_t) i; }
  if (r.below(100) < 15) { const uint32_t m = r.below(3); p.magic = m == 0 ? 0u : m == 1 ? 1u : (ecco_fallback::PROFILE_MAGIC ^ 1u); }
  if (r.below(100) < 10) p.reserved0 = 1;
  if (r.below(100) < 30) { const uint32_t i = r.below(3); p.captured_epoch = EPOCHP[i]; }
  maybe_set(r, p.reg256_261);
  maybe_set(r, p.reg268_273);
  maybe_set(r, p.reg274_279);
  maybe_set(r, p.reg250_255);
  p = ecco_fallback::seal_profile(p);
  if (r.below(100) < 15) { const uint32_t b = r.below(64); p.binding ^= (1ULL << b); }
  const uint8_t load = gen_load(r);
  uint32_t len = 0;
  if (load == 2) { const uint32_t i = r.below(5); len = LENP[i]; }
  if (load != 0) p = ecco_fallback::FallbackProfileV1{};
  return {load, p, len};
}
struct WRec {
  uint8_t load;
  ecco_fbdurable::FailbackProvisionV1 w;
};
constexpr WRec gen_witness(Rng &r, const ecco_fallback::FallbackProfileV1 &p) {
  constexpr uint32_t HWP[5] = {1u, 6u, 7u, 8u, 4294967294u};
  const uint8_t load = gen_load(r);
  if (load != 0)
    return {load, ecco_fbdurable::FailbackProvisionV1{}};
  const uint32_t hi = r.below(5);
  const uint32_t hw = HWP[hi];
  const uint32_t pgc = r.below(3);
  uint32_t pg = pgc == 0 ? 0u : pgc == 1 ? (hw > 1 ? hw - 1 : 0u) : 3u;
  if (pg >= hw) pg = 0;
  const uint32_t pbc = r.below(3);
  const uint64_t pb = pg == 0 ? 0ULL : pbc == 0 ? 0x1122ULL : pbc == 1 ? p.binding : 0xABULL;
  const uint32_t hbc = r.below(2);
  const uint64_t hwb = hbc == 0 ? p.binding : 0x77ULL;
  const uint32_t kc = r.below(3);
  const uint32_t key = kc < 2 ? ecco_fbdurable::FALLBACK_PROFILE_KEY : 5u;
  const uint32_t sc = r.below(3);
  const uint16_t schema = sc < 2 ? (uint16_t) 1 : (uint16_t) 2;
  const uint32_t oc = r.below(3);
  const uint8_t op = (uint8_t) (1 + oc);
  ecco_fbdurable::FailbackProvisionV1 w = ecco_fbdurable::make_provision(hw, hwb, pg, pb, key, schema, op);
  if (r.below(100) < 15) w.binding ^= 1u;
  return {0, w};
}
struct SP {
  const char *s;
  size_t n;
};
constexpr SP TOKS[] = {{"SAVE", 4}, {"INVALIDATE", 10}, {"RESTORE", 7}, {"ACKNOWLEDGE", 11}, {"", 0}, {"save", 4}, {"SAVE ", 5}, {"CAPTURE", 7},
                       {"RETRY_APPLY", 11}, {"SAVE\0x", 6}, {"INVALIDATE\0x", 12}, {"APPLY", 5}, {"ACCEPT_LIVE", 11}, {"PROVISION", 9}, {" SAVE", 5},
                       {"failed", 6}, {"DEFERRED", 8}, {"xfaildeferx", 11}, {"FaIlEd", 6}, {"dEfEr", 5}, {"fail", 4}};
constexpr uint32_t NTOKS = sizeof(TOKS) / sizeof(TOKS[0]);
constexpr const char *PIECES[] = {"fail", "FAIL", "Fail", "fAiL", "defer", "DEFER", "dEfEr", "Defer", "ed", "red", "x", "_", "a", "7", " ", "fai", "def", "il", "fer"};
constexpr uint32_t NPIECES = sizeof(PIECES) / sizeof(PIECES[0]);
constexpr char ALPHA[] = {'S', 'A', 'V', 'E', 'I', 'N', 'L', 'D', 'T', 'R', 'C', 'O', 'P', '0', '1', '9', 'a', 'f', 'A', 'F', 'G', ' ', '_', '\n', 'x'};
constexpr uint32_t ALPHA_N = sizeof(ALPHA) / sizeof(ALPHA[0]);
constexpr TextBuf gen_text(Rng &r) {
  TextBuf t;
  const uint32_t mode = r.below(100);
  const uint64_t id = u64(r);
  if (mode < 35) {
    const uint32_t i = r.below(NTOKS);
    for (size_t k = 0; k < TOKS[i].n; k++) put_char(t, TOKS[i].s[k]);
  } else if (mode < 55) {
    const uint32_t k = r.below(28);
    t = fx_conf((uint8_t) k, id);
  } else if (mode < 72) {
    const uint32_t k = r.below(15);
    t = fx_target((uint8_t) k, id);
  } else if (mode < 88) {
    const uint32_t np = 1 + r.below(8);
    for (uint32_t i = 0; i < np; i++) {
      const uint32_t pi = r.below(NPIECES);
      for (const char *c = PIECES[pi]; *c != '\0'; c++) put_char(t, *c);
    }
  } else {
    const uint32_t len = r.below(46);
    for (uint32_t i = 0; i < len; i++) { const uint32_t c = r.below(ALPHA_N); put_char(t, ALPHA[c]); }
  }
  const uint32_t m = r.below(100);
  if (m < 25 && t.size() > 0) {
    const uint32_t pos = r.below((uint32_t) t.size());
    const uint32_t c = r.below(ALPHA_N);
    t.buf[pos] = ALPHA[c];
  } else if (m < 40 && t.size() > 0) {
    t.len = (uint16_t) (t.len - 1);
    t.buf[t.len] = '\0';
  } else if (m < 55) {
    const uint32_t c = r.below(ALPHA_N);
    put_char(t, ALPHA[c]);
  }
  return t;
}
constexpr uint32_t SEEDP[7] = {0u, 5u, 7u, 20u, 4294967294u, 4294967295u, 0u};
constexpr uint32_t gen_seen(Rng &r) {
  const uint32_t i = r.below(7);
  if (i == 6) return r.next();
  return SEEDP[i];
}
constexpr uint32_t gen_epoch(Rng &r) {
  const uint32_t em = r.below(100);
  if (em < 5) return 0u;
  if (em < 15) return 4294967295u;
  const uint32_t q = r.below(1000);
  return 1790000000u + q;
}
// a SAVE plan input for a stored pair: either a fixture pair or a random one, faithful to its own prior, then mutated
constexpr SavePlanInputs gen_save_inputs(Rng &r) {
  const uint32_t mode = r.below(100);
  SavePlanInputs in{};
  if (mode < 50) {
    const uint32_t pk = r.below(10);
    const uint32_t wk = r.below(17);
    const uint32_t seen = gen_seen(r);
    in = fx_save_inputs((uint8_t) pk, (uint8_t) wk, seen);
  } else {
    const Rec pr = gen_profile(r);
    const WRec wr = gen_witness(r, pr.p);
    const uint32_t seen = gen_seen(r);
    in = fx_save_from(pr.load, pr.p, pr.len, wr.load, wr.w, 0u, seen);
  }
  const uint32_t mm = r.below(100);
  uint8_t mut = 0;
  if (mm >= 55) { const uint32_t q = r.below(17); mut = (uint8_t) (1 + q); }
  in = fx_save_mut(in, mut);
  if (r.below(100) < 35) in.words = gen_words(r, 25);
  in.captured_epoch = gen_epoch(r);
  return in;
}
constexpr InvalidatePlanInputs gen_inv_inputs(Rng &r) {
  const uint32_t mode = r.below(100);
  InvalidatePlanInputs in{};
  if (mode < 50) {
    const uint32_t pk = r.below(10);
    const uint32_t wk = r.below(17);
    const uint32_t seen = gen_seen(r);
    in = fx_inv_inputs((uint8_t) pk, (uint8_t) wk, seen);
  } else {
    const Rec pr = gen_profile(r);
    const WRec wr = gen_witness(r, pr.p);
    const uint32_t seen = gen_seen(r);
    in = fx_inv_from(pr.load, pr.p, pr.len, wr.load, wr.w, 0u, seen);
  }
  const uint32_t mm = r.below(100);
  uint8_t mut = 0;
  if (mm >= 55) { const uint32_t q = r.below(10); mut = (uint8_t) (1 + q); }
  return fx_inv_mut(in, mut);
}
constexpr ecco_fbdurable::TxnResult gen_txn(Rng &r) {
  constexpr int32_t ERRP[8] = {0, 0x1101, 0x1102, 0x1104, 0x1107, 0x107, -1, 0};
  ecco_fbdurable::TxnResult t{};
  { const uint32_t i = r.below(8); t.w.err = ERRP[i]; }
  { const uint32_t i = r.below(9); t.w.rb_class = (uint8_t) i; }
  { const uint32_t i = r.below(4); t.w.outcome = (uint8_t) i; }
  t.w.us = r.next() % 100000u;
  { const uint32_t i = r.below(8); t.p.err = ERRP[i]; }
  { const uint32_t i = r.below(9); t.p.rb_class = (uint8_t) i; }
  { const uint32_t i = r.below(4); t.p.outcome = (uint8_t) i; }
  t.p.us = r.next() % 100000u;
  { const uint32_t i = r.below(2); t.witness_advanced = (uint8_t) i; }
  { const uint32_t i = r.below(7); t.refusal = (uint8_t) i; }
  if (r.below(100) < 8) { t.w.err = -1; t.w.us = 4294967295u; t.p.us = 4294967295u; }
  return t;
}
constexpr GateInputs gen_gate_inputs(Rng &r) {
  const uint32_t gm = r.below(100);
  uint8_t k = 0;
  if (gm >= 45) { const uint32_t q = r.below(28); k = (uint8_t) q; }
  GateInputs g = fx_gate(k);
  if (r.below(100) < 50) { g.bus.fallback_profile_op_in_progress = true; g.bus.fallback_profile_capture_dispatch_running = true; g.bus.manual_write_in_progress = true; }
  if (r.below(100) < 8) g.bus.correction_in_progress = true;
  if (r.below(100) < 6) g.free_power_write_enable = true;
  if (r.below(100) < 6) { g.bus.diag_write_lock_held = true; g.bus.diag_write_lock_since_ms = 1000u; g.bus.now_ms = 1000u + r.below(600000u); }
  return g;
}
constexpr uint64_t comp_digest(uint32_t seed, uint32_t comp) {
  Rng r{seed * 2654435761u + comp * 40503u + 1u};
  Dg d;
  if (comp == 0) {
    const TextBuf s = gen_text(r);
    const uint32_t k2 = r.below(5);
    const uint64_t id2 = u64(r);
    d.u(action_token(s.c_str(), s.size()));
    d.u(action_token(s.c_str()));
    d.u(is_invalidate_action(s.c_str(), s.size()) ? 1 : 0);
    d.u(is_invalidate_action(s.c_str()) ? 1 : 0);
    d.u(is_hex16(s.c_str(), s.size()) ? 1 : 0);
    d.u(is_hex16(s.c_str()) ? 1 : 0);
    d.u(parse_hex16(s.c_str(), s.size()));
    const Phrase p = parse_phrase(s.c_str(), s.size());
    d.u(p.kind);
    d.u(p.id);
    d.u(parse_phrase(s.c_str()).kind);
    d.t(unsupported_action_text(s.c_str(), s.size()));
    d.t(unsupported_action_text(s.c_str()));
    d.t(action_refusal_text(action_token(s.c_str(), s.size()), s.c_str(), s.size()));
    const TextBuf e = expected_phrase((uint8_t) k2, id2);
    d.t(e);
    d.u(phrase_equals(s.c_str(), s.size(), e) ? 1 : 0);
    d.u(phrase_equals(s.c_str(), e) ? 1 : 0);
    const TextBuf e2 = expected_phrase(p.kind, p.id);
    d.u(phrase_equals(s.c_str(), s.size(), e2) ? 1 : 0);
    d.u(bounded_len(s.c_str(), 16));
    for (uint32_t i = 0; i < NTOKS; i++) {
      d.u(action_token(TOKS[i].s, TOKS[i].n));
      d.u(action_token(TOKS[i].s));
      d.u(is_invalidate_action(TOKS[i].s, TOKS[i].n) ? 1 : 0);
      d.u(is_invalidate_action(TOKS[i].s) ? 1 : 0);
    }
  } else if (comp == 1) {
    uint64_t id = u64(r);
    if (r.below(100) < 12) id = 0;
    SaveGateInputs si{};
    si.arm_was_on = r.below(100) < 90;
    si.cand_valid = r.below(100) < 90;
    si.cand_saveable = r.below(100) < 90;
    si.cand_id = id;
    si.cand_ms = r.next();
    { constexpr uint8_t CLS[10] = {5, 5, 5, 2, 2, 1, 3, 4, 6, 8}; const uint32_t i = r.below(10); si.cand_prior_class = CLS[i]; }
    {
      constexpr uint32_t AG[7] = {0u, 1u, 119999u, 120000u, 120001u, 30000u, 4000000000u};
      const uint32_t a = r.below(8);
      if (a == 7) si.now_ms = r.next();
      else si.now_ms = si.cand_ms + AG[a];
    }
    { const uint32_t cm = r.below(100); si.cand_writes_fp = cm < 70 ? r.next() : cm < 80 ? 0u : cm < 90 ? 0xFFFFFFFFu : 0x7FFFFFFFu + r.below(2); }
    { const uint32_t wm = r.below(100); si.writes_fp_now = wm < 80 ? si.cand_writes_fp : wm < 88 ? si.cand_writes_fp + 1u : wm < 96 ? si.cand_writes_fp - 1u : r.next(); }
    si.boot_loaded = r.below(100) < 95;
    si.unconfirmed = r.below(100) < 6;
    { const uint32_t an = r.below(100); si.read_anomaly = an < 90 ? 0 : an < 94 ? 1 : an < 97 ? 4 : 255; }
    si.hb_ok = r.below(100) < 92;
    si.time_trusted = r.below(100) < 92;
    const uint32_t gk = r.below(100);
    uint8_t gate = 0;
    if (gk >= 55) { const uint32_t q = r.below(28); gate = (uint8_t) q; }
    const uint32_t sm = r.below(100);
    TextBuf act, tgt, cnf;
    if (sm < 60) {
      act = fx_action(0);
      tgt = fx_target(0, id);
      cnf = fx_conf(si.cand_prior_class == 2 ? 1 : 0, id);
    } else {
      const uint32_t a1 = r.below(16);
      const uint32_t t1 = r.below(15);
      const uint32_t c1 = r.below(28);
      act = fx_action((uint8_t) a1);
      tgt = fx_target((uint8_t) t1, id);
      cnf = fx_conf((uint8_t) c1, id);
    }
    const SaveGateResult g = save_gate_decide(si, act.c_str(), act.size(), tgt.c_str(), tgt.size(), cnf.c_str(), cnf.size(), fx_gate(gate));
    d.u(g.code);
    d.u(g.arm_off_only ? 1 : 0);
    d.u(g.replace_corrupt ? 1 : 0);
    d.t(g.obl);
    d.t(g.text);
  } else if (comp == 2) {
    const uint32_t pk = r.below(10);
    const uint32_t wk = r.below(17);
    const FxP pr = fx_p((uint8_t) pk);
    const FxW wr = fx_w((uint8_t) wk, pr.p);
    InvalidateGateInputs in{};
    in.arm_was_on = r.below(100) < 92;
    in.boot_loaded = r.below(100) < 95;
    in.read_anomaly = r.below(100) < 6 ? 4 : 0;
    in.unconfirmed = r.below(100) < 5;
    {
      const uint32_t cm = r.below(100);
      uint8_t cl = ecco_fbdurable::compose_profile_class(pr.load, pr.p, wr.load, wr.w, 0).cls;
      if (cm >= 85) { const uint32_t c2 = r.below(10); cl = (uint8_t) c2; }
      in.cls = cl;
    }
    in.p_load = pr.load;
    in.p = pr.p;
    in.w_load = wr.load;
    in.w = wr.w;
    { constexpr uint32_t SN[6] = {0u, 6u, 7u, 8u, 100u, 4294967295u}; const uint32_t i = r.below(6); in.seen_hw_gen = SN[i]; }
    {
      const uint32_t bm = r.below(100);
      uint8_t bk = 0;
      if (bm >= 82) { const uint32_t q = r.below(11); bk = (uint8_t) (1 + q); }
      in.bus = fx_bus(bk);
    }
    { const uint32_t tx = r.below(100); in.tx_buffer_empty = tx >= 6; in.tx_blocked = tx >= 6 && tx < 10; }
    { const uint32_t fb = r.below(100); in.fbs_slot = fb < 80 ? (uint8_t) 1 : (uint8_t) (fb % 5); }
    const uint64_t id = pr.p.binding;
    const uint32_t sm = r.below(100);
    TextBuf act, tgt, cnf;
    if (sm < 65) {
      act = fx_action(1);
      tgt = fx_target(0, id);
      cnf = fx_conf(2, id);
    } else {
      const uint32_t a1 = r.below(16);
      const uint32_t t1 = r.below(15);
      const uint32_t c1 = r.below(28);
      act = fx_action((uint8_t) a1);
      tgt = fx_target((uint8_t) t1, id);
      cnf = fx_conf((uint8_t) c1, id);
    }
    const InvalidateGateResult g = invalidate_gate_decide(in, act.c_str(), act.size(), tgt.c_str(), tgt.size(), cnf.c_str(), cnf.size());
    d.u(g.code);
    d.u(g.arm_off_only ? 1 : 0);
    d.t(g.text);
  } else if (comp == 3) {
    const SavePlanInputs in = gen_save_inputs(r);
    const Plan p = plan_save(in);
    d.u(p.code);
    d.u(p.op);
    d.u(p.generation);
    d.t(p.text);
    d.u(fx_digest(p));
    if (p.code == PLAN_OK) {
      const ecco_fbdurable::PriorDesc wpd{in.w_load, in.w_stored_len};
      const ecco_fbdurable::PriorDesc ppd{in.p_load, in.p_stored_len};
      d.u(ecco_fbdurable::validate_transition(p.w_new, in.w, wpd, p.p_new, in.p, ppd) ? 1 : 0);
    }
  } else if (comp == 4) {
    const InvalidatePlanInputs in = gen_inv_inputs(r);
    const Plan p = plan_invalidate(in);
    d.u(p.code);
    d.u(p.op);
    d.u(p.generation);
    d.t(p.text);
    d.u(fx_digest(p));
    if (p.code == PLAN_OK) {
      const ecco_fbdurable::PriorDesc wpd{in.w_load, in.w_stored_len};
      const ecco_fbdurable::PriorDesc ppd{in.p_load, in.p_stored_len};
      d.u(ecco_fbdurable::validate_transition(p.w_new, in.w, wpd, p.p_new, in.p, ppd) ? 1 : 0);
    }
  } else if (comp == 5) {
    const ecco_fbdurable::TxnResult t = gen_txn(r);
    const uint32_t op = r.below(5);
    const uint32_t o = r.below(5);
    const uint32_t gen = r.next();
    const uint32_t pgen = r.next();
    d.t(txn_outcome_text((uint8_t) op, (uint8_t) o, t, gen, pgen));
    d.t(txn_log_text((uint8_t) op, (uint8_t) o, t, gen));
    d.u(first_non_ok(t.w.err, t.p.err));
    d.u(total_us(t.w.us, t.p.us));
    d.s(txn_name((uint8_t) o));
    d.s(key_name(t.w.outcome));
    d.s(rb_name(t.w.rb_class));
    const uint32_t code = r.below(9);
    const uint32_t step = r.below(6);
    const uint32_t exc = r.below(3);
    d.t(save_read_fail_text((uint8_t) code, (uint8_t) step, exc == 0 ? 0 : exc == 1 ? 2 : 255));
    const CaptureWords a = gen_words(r, 20);
    const CaptureWords b = gen_words(r, 20);
    d.t(save_changed_during_read_text(a, b));
    d.t(save_changed_since_review_text(a, b));
    d.t(save_l2_text(capture_refusals(a, 8000), a));
    const uint32_t cls = r.below(11);
    const uint32_t why = r.below(14);
    d.t(save_class_text((uint8_t) cls, (uint8_t) why));
    d.t(invalidate_class_text((uint8_t) cls));
    d.t(invalidate_class_now_text((uint8_t) cls));
    const uint64_t id = u64(r);
    d.t(save_phrase_text(expected_phrase(PHRASE_SAVE_REPLACE_CORRUPT, id)));
    d.t(invalidate_phrase_text(expected_phrase(PHRASE_INVALIDATE, id)));
    d.t(saved_text(gen));
    d.t(invalidated_text(pgen, gen));
    d.t(invalidate_generation_text(r.below(2) == 1));
    const uint32_t pk = r.below(10);
    const FxP pr = fx_p((uint8_t) pk);
    const uint32_t part = r.below(3);
    d.t(replace_corrupt_log_text(pr.load, pr.p, pr.len, (uint8_t) part));
  } else {
    const uint32_t now = r.next();
    const uint32_t born = r.next();
    { constexpr uint32_t AG[8] = {0u, 1u, 119999u, 120000u, 120001u, 30000u, 4000000000u, 0u}; const uint32_t a = r.below(8); const uint32_t b2 = r.next(); d.u(arm_expired(b2 + AG[a], b2) ? 1 : 0); }
    d.u(arm_expired(now, born) ? 1 : 0);
    const uint32_t o1 = r.below(2);
    const uint32_t o2 = r.below(4);
    d.u(save_integrity_ok(o1 == 1, (uint8_t) o2) ? 1 : 0);
    const uint32_t cls = r.below(10);
    const uint32_t un = r.below(2);
    d.u(overlay_class((uint8_t) cls, un == 1));
    { const uint32_t f = r.below(32); d.u(commit_bus_quiet((f & 1) != 0, (f & 2) != 0, (f & 4) != 0, (f & 8) != 0, (f & 16) != 0) ? 1 : 0); }
    {
      BusInputs b{};
      b.manual_write_in_progress = r.below(100) < 10;
      b.correction_in_progress = r.below(100) < 10;
      b.verification_pending = r.below(100) < 10;
      b.free_power_operation_in_progress = r.below(100) < 5;
      b.dump_operation_in_progress = r.below(100) < 5;
      b.fallback_profile_op_in_progress = r.below(100) < 5;
      const uint32_t tx = r.below(100);
      d.u(invalidate_bus_idle(b, tx >= 8, tx >= 8 && tx < 14) ? 1 : 0);
    }
    { const uint32_t ep = r.below(3); d.u(clock_trusted_for_save(r.below(2) == 1, ep == 0 ? 0u : ep == 1 ? 1790000000u : 4294967295u) ? 1 : 0); }
    const GateInputs g = gen_gate_inputs(r);
    ProbeResults pr{};
    {
      const uint32_t pm = r.below(100);
      if (pm < 40) { pr.fp = PROBE_ABSENT; pr.dump = PROBE_CLEAR; pr.r244 = PROBE_ABSENT; }
      else if (pm < 55) { const uint32_t a = r.below(7); const uint32_t b = r.below(7); const uint32_t c = r.below(7); pr.fp = (uint8_t) a; pr.dump = (uint8_t) b; pr.r244 = (uint8_t) c; }
    }
    const FinalGate f = final_gate_decide(g, pr);
    d.u(f.gr.code);
    d.u(f.gr.slot);
    d.u(f.gr.latch);
    d.u((f.gr.probe_fp ? 4 : 0) + (f.gr.probe_dump ? 2 : 0) + (f.gr.probe_r244 ? 1 : 0));
    d.t(f.gr.obl);
    d.t(f.text);
    const GateResult plain = gate_decide(g, ProbeResults{});
    d.u(plain.code);
    d.t(save_gate_refusal_text(plain, g));
    d.u(final_phase_inputs(g).bus.manual_write_in_progress ? 1 : 0);
  }
  return d.h;
}
}  // namespace rnd
'''


class PRng:
    def __init__(self, s: int) -> None:
        self.s = s & U32

    def next(self) -> int:
        self.s = (self.s * 1664525 + 1013904223) & U32
        return self.s

    def below(self, n: int) -> int:
        return (self.next() >> 8) % n


def p_u64(r: PRng) -> int:
    hi = r.next()
    lo = r.next()
    return (hi << 32) | lo


class PDg:
    def __init__(self) -> None:
        self.h = fp.FNV1A64_OFFSET_BASIS

    def u(self, v) -> None:
        self.h = cap.step_le(self.h, int(v), 8)

    def s(self, t) -> None:
        self.h = fp.fnv1a_64(str(t).encode() + b"\xff", self.h)

    t = s


R_POOL = [0, 1, 2, 3, 0x20, 0x27, 59, 60, 99, 100, 101, 499, 500, 2359, 2400, 3000, 3001, 8000, 8001, 65535]


def r_words(r: PRng, pchange: int) -> list:
    w = list(GW)
    for k in range(31):
        c = r.below(100)
        if c < pchange:
            pick = r.below(100)
            if pick < 85:
                w[k] = R_POOL[r.below(len(R_POOL))]
            else:
                w[k] = r.below(65536)
    return w


def r_load(r: PRng) -> int:
    x = r.below(100)
    return 0 if x < 70 else 1 if x < 80 else 2 if x < 88 else 3 if x < 95 else 4


def r_maybe_set(r: PRng, arr: list) -> None:
    c = r.below(100)
    if c < 25:
        i = r.below(6)
        j = r.below(len(R_POOL))
        arr[i] = R_POOL[j]


def r_profile(r: PRng):
    p = fp._copy(GOLD_P)
    mode = r.below(100)
    if mode < 50:
        i = r.below(3)
        p["generation"] = [1, 7, 8][i]
        f = r.below(2)
        p["flags"] = f
        i = r.below(3)
        p["captured_epoch"] = [0, 1790000000, 4294967295][i]
        p = fp.seal_profile(p)
        lc = r.below(100)
        cload = 0 if lc < 90 else 1 if lc < 95 else 3
        if cload != 0:
            p = fp.blank_profile()
        return cload, p, 0
    if r.below(100) < 35:
        p["generation"] = [0, 1, 7, 8, 4294967295][r.below(5)]
    if r.below(100) < 30:
        p["reg244"] = [0, 1, 2, 3, 65535][r.below(5)]
    if r.below(100) < 25:
        p["flags"] = r.below(4)
    if r.below(100) < 15:
        m = r.below(3)
        p["magic"] = 0 if m == 0 else 1 if m == 1 else fp.PROFILE_MAGIC ^ 1
    if r.below(100) < 10:
        p["reserved0"] = 1
    if r.below(100) < 30:
        p["captured_epoch"] = [0, 1790000000, 4294967295][r.below(3)]
    for name in ("reg256_261", "reg268_273", "reg274_279", "reg250_255"):
        r_maybe_set(r, p[name])
    p = fp.seal_profile(p)
    if r.below(100) < 15:
        b = r.below(64)
        p["binding"] ^= 1 << b
    load = r_load(r)
    ln = 0
    if load == 2:
        ln = [0, 40, 95, 97, 1000][r.below(5)]
    if load != 0:
        p = fp.blank_profile()
    return load, p, ln


def r_witness(r: PRng, p: dict):
    load = r_load(r)
    if load != 0:
        return load, fd.blank_provision()
    hw = [1, 6, 7, 8, 4294967294][r.below(5)]
    pgc = r.below(3)
    pg = 0 if pgc == 0 else (hw - 1 if hw > 1 else 0) if pgc == 1 else 3
    if pg >= hw:
        pg = 0
    pbc = r.below(3)
    pb = 0 if pg == 0 else 0x1122 if pbc == 0 else p["binding"] if pbc == 1 else 0xAB
    hwb = p["binding"] if r.below(2) == 0 else 0x77
    key = fd.FALLBACK_PROFILE_KEY if r.below(3) < 2 else 5
    schema = 1 if r.below(3) < 2 else 2
    op = 1 + r.below(3)
    w = fd.make_provision(hw, hwb, pg, pb, key, schema, op)
    if r.below(100) < 15:
        w = dict(w)
        w["binding"] ^= 1
    return 0, w


R_TOKS = [("SAVE", 4), ("INVALIDATE", 10), ("RESTORE", 7), ("ACKNOWLEDGE", 11), ("", 0), ("save", 4), ("SAVE ", 5), ("CAPTURE", 7), ("RETRY_APPLY", 11),
          ("SAVE\0x", 6), ("INVALIDATE\0x", 12), ("APPLY", 5), ("ACCEPT_LIVE", 11), ("PROVISION", 9), (" SAVE", 5),
          ("failed", 6), ("DEFERRED", 8), ("xfaildeferx", 11), ("FaIlEd", 6), ("dEfEr", 5), ("fail", 4)]
R_PIECES = ["fail", "FAIL", "Fail", "fAiL", "defer", "DEFER", "dEfEr", "Defer", "ed", "red", "x", "_", "a", "7", " ", "fai", "def", "il", "fer"]
R_ALPHA = ["S", "A", "V", "E", "I", "N", "L", "D", "T", "R", "C", "O", "P", "0", "1", "9", "a", "f", "A", "F", "G", " ", "_", "\n", "x"]


def r_text(r: PRng) -> str:
    mode = r.below(100)
    id_ = p_u64(r)
    if mode < 35:
        i = r.below(len(R_TOKS))
        t = R_TOKS[i][0][:R_TOKS[i][1]]
    elif mode < 55:
        k = r.below(28)
        t = fx_conf(k, id_)
    elif mode < 72:
        k = r.below(15)
        t = fx_target(k, id_)
    elif mode < 88:
        np_ = 1 + r.below(8)
        parts = []
        for _ in range(np_):
            parts.append(R_PIECES[r.below(len(R_PIECES))])
        t = "".join(parts)
    else:
        ln = r.below(46)
        chars = []
        for _ in range(ln):
            c = r.below(len(R_ALPHA))
            chars.append(R_ALPHA[c])
        t = "".join(chars)
    m = r.below(100)
    if m < 25 and len(t) > 0:
        pos = r.below(len(t))
        c = r.below(len(R_ALPHA))
        t = t[:pos] + R_ALPHA[c] + t[pos + 1:]
    elif m < 40 and len(t) > 0:
        t = t[:-1]
    elif m < 55:
        c = r.below(len(R_ALPHA))
        t = t + R_ALPHA[c]
    return t


R_SEEN = [0, 5, 7, 20, 4294967294, 4294967295]


def r_seen(r: PRng) -> int:
    i = r.below(7)
    if i == 6:
        return r.next()
    return R_SEEN[i] if i < 6 else 0


def r_epoch(r: PRng) -> int:
    em = r.below(100)
    if em < 5:
        return 0
    if em < 15:
        return 4294967295
    q = r.below(1000)
    return 1790000000 + q


def fx_save_from(pl, p, plen, wl, w, wlen, seen) -> sv.SavePlanInputs:
    in_ = sv.SavePlanInputs()
    in_.p_load, in_.p, in_.p_stored_len, in_.w_load, in_.w, in_.w_stored_len = pl, p, plen, wl, w, wlen
    cls, why, _rule = fd.compose_profile_class(pl, p, wl, w, 0)
    in_.cls, in_.why, in_.read_anomaly, in_.unconfirmed, in_.seen_hw_gen = cls, why, 0, False, seen
    f = cap.prior_fingerprint(pl, p, plen)
    in_.cand_prior_class, in_.cand_prior_gen, in_.cand_prior_binding = cls, f.generation, f.binding
    in_.replace_corrupt = cls == fd.EPC_CORRUPT
    in_.words = list(GW)
    in_.captured_epoch = FX_EPOCH
    return in_


def fx_inv_from(pl, p, plen, wl, w, wlen, seen) -> sv.InvalidatePlanInputs:
    in_ = sv.InvalidatePlanInputs()
    in_.p_load, in_.p, in_.p_stored_len, in_.w_load, in_.w, in_.w_stored_len = pl, p, plen, wl, w, wlen
    in_.cls = fd.compose_profile_class(pl, p, wl, w, 0)[0]
    in_.read_anomaly, in_.unconfirmed, in_.seen_hw_gen, in_.target_id = 0, False, seen, p["binding"]
    return in_


def r_save_inputs(r: PRng) -> sv.SavePlanInputs:
    mode = r.below(100)
    if mode < 50:
        pk = r.below(10)
        wk = r.below(17)
        seen = r_seen(r)
        in_ = fx_save_inputs(pk, wk, seen)
    else:
        pl, p, plen = r_profile(r)
        wl, w = r_witness(r, p)
        seen = r_seen(r)
        in_ = fx_save_from(pl, p, plen, wl, w, 0, seen)
    mm = r.below(100)
    mut = 0
    if mm >= 55:
        q = r.below(17)
        mut = 1 + q
    in_ = fx_save_mut(in_, mut)
    if r.below(100) < 35:
        in_.words = r_words(r, 25)
    in_.captured_epoch = r_epoch(r)
    return in_


def r_inv_inputs(r: PRng) -> sv.InvalidatePlanInputs:
    mode = r.below(100)
    if mode < 50:
        pk = r.below(10)
        wk = r.below(17)
        seen = r_seen(r)
        in_ = fx_inv_inputs(pk, wk, seen)
    else:
        pl, p, plen = r_profile(r)
        wl, w = r_witness(r, p)
        seen = r_seen(r)
        in_ = fx_inv_from(pl, p, plen, wl, w, 0, seen)
    mm = r.below(100)
    mut = 0
    if mm >= 55:
        q = r.below(10)
        mut = 1 + q
    return fx_inv_mut(in_, mut)


def r_txn(r: PRng) -> fd.TxnResult:
    ERRP = [0, 0x1101, 0x1102, 0x1104, 0x1107, 0x107, -1, 0]
    t = fd.TxnResult()
    t.w = fd.KeyReport()
    t.p = fd.KeyReport()
    t.w.err = ERRP[r.below(8)]
    t.w.rb_class = r.below(9)
    t.w.outcome = r.below(4)
    t.w.us = r.next() % 100000
    t.p.err = ERRP[r.below(8)]
    t.p.rb_class = r.below(9)
    t.p.outcome = r.below(4)
    t.p.us = r.next() % 100000
    t.witness_advanced = bool(r.below(2))
    t.refusal = r.below(7)
    if r.below(100) < 8:
        t.w.err = -1
        t.w.us = 4294967295
        t.p.us = 4294967295
    return t


def r_gate_inputs(r: PRng) -> cap.GateInputs:
    gm = r.below(100)
    k = 0
    if gm >= 45:
        k = r.below(28)
    g = fx_gate(k)
    if r.below(100) < 50:
        g.bus.fallback_profile_op_in_progress = True
        g.bus.fallback_profile_capture_dispatch_running = True
        g.bus.manual_write_in_progress = True
    if r.below(100) < 8:
        g.bus.correction_in_progress = True
    if r.below(100) < 6:
        g.free_power_write_enable = True
    if r.below(100) < 6:
        g.bus.diag_write_lock_held = True
        g.bus.diag_write_lock_since_ms = 1000
        g.bus.now_ms = (1000 + r.below(600000)) & U32
    return g


def r_comp_digest(seed: int, comp: int) -> int:
    r = PRng((seed * 2654435761 + comp * 40503 + 1) & U32)
    d = PDg()
    if comp == 0:
        s = r_text(r)
        k2 = r.below(5)
        id2 = p_u64(r)
        n = len(s)
        d.u(sv.action_token(s, n))
        d.u(sv.action_token(s))
        d.u(1 if sv.is_invalidate_action(s, n) else 0)
        d.u(1 if sv.is_invalidate_action(s) else 0)
        d.u(1 if sv.is_hex16(s, n) else 0)
        d.u(1 if sv.is_hex16(s) else 0)
        d.u(sv.parse_hex16(s, n))
        p = sv.parse_phrase(s, n)
        d.u(p.kind)
        d.u(p.id)
        d.u(sv.parse_phrase(s).kind)
        d.t(sv.unsupported_action_text(s, n))
        d.t(sv.unsupported_action_text(s))
        d.t(sv.action_refusal_text(sv.action_token(s, n), s, n))
        e = sv.expected_phrase(k2, id2)
        d.t(e)
        d.u(1 if sv.phrase_equals(s, n, e) else 0)
        d.u(1 if sv.phrase_equals(s, e) else 0)
        e2 = sv.expected_phrase(p.kind, p.id)
        d.u(1 if sv.phrase_equals(s, n, e2) else 0)
        d.u(sv.bounded_len(s, 16))
        for tk, tn in R_TOKS:
            tv = tk[:tn]
            d.u(sv.action_token(tv, tn))
            d.u(sv.action_token(tv))
            d.u(1 if sv.is_invalidate_action(tv, tn) else 0)
            d.u(1 if sv.is_invalidate_action(tv) else 0)
    elif comp == 1:
        id_ = p_u64(r)
        if r.below(100) < 12:
            id_ = 0
        si = sv.SaveGateInputs()
        si.arm_was_on = r.below(100) < 90
        si.cand_valid = r.below(100) < 90
        si.cand_saveable = r.below(100) < 90
        si.cand_id = id_
        si.cand_ms = r.next()
        si.cand_prior_class = [5, 5, 5, 2, 2, 1, 3, 4, 6, 8][r.below(10)]
        a = r.below(8)
        if a == 7:
            si.now_ms = r.next()
        else:
            si.now_ms = (si.cand_ms + [0, 1, 119999, 120000, 120001, 30000, 4000000000][a]) & U32
        cm = r.below(100)
        si.cand_writes_fp = r.next() if cm < 70 else 0 if cm < 80 else U32 if cm < 90 else (0x7FFFFFFF + r.below(2)) & U32
        wm = r.below(100)
        si.writes_fp_now = si.cand_writes_fp if wm < 80 else (si.cand_writes_fp + 1) & U32 if wm < 88 else (si.cand_writes_fp - 1) & U32 if wm < 96 else r.next()
        si.boot_loaded = r.below(100) < 95
        si.unconfirmed = r.below(100) < 6
        an = r.below(100)
        si.read_anomaly = 0 if an < 90 else 1 if an < 94 else 4 if an < 97 else 255
        si.hb_ok = r.below(100) < 92
        si.time_trusted = r.below(100) < 92
        gk = r.below(100)
        gate = 0
        if gk >= 55:
            gate = r.below(28)
        sm = r.below(100)
        if sm < 60:
            act, tgt, cnf = fx_action(0), fx_target(0, id_), fx_conf(1 if si.cand_prior_class == 2 else 0, id_)
        else:
            a1 = r.below(16)
            t1 = r.below(15)
            c1 = r.below(28)
            act, tgt, cnf = fx_action(a1), fx_target(t1, id_), fx_conf(c1, id_)
        g = sv.save_gate_decide(si, act, len(act), tgt, len(tgt), cnf, len(cnf), fx_gate(gate))
        d.u(g.code)
        d.u(1 if g.arm_off_only else 0)
        d.u(1 if g.replace_corrupt else 0)
        d.t(g.obl)
        d.t(g.text)
    elif comp == 2:
        pk = r.below(10)
        wk = r.below(17)
        pl, p, _plen = fx_p(pk)
        wl, w, _wlen = fx_w(wk, p)
        in_ = sv.InvalidateGateInputs()
        in_.arm_was_on = r.below(100) < 92
        in_.boot_loaded = r.below(100) < 95
        in_.read_anomaly = 4 if r.below(100) < 6 else 0
        in_.unconfirmed = r.below(100) < 5
        cm = r.below(100)
        cl = fd.compose_profile_class(pl, p, wl, w, 0)[0]
        if cm >= 85:
            cl = r.below(10)
        in_.cls = cl
        in_.p_load, in_.p, in_.w_load, in_.w = pl, p, wl, w
        in_.seen_hw_gen = [0, 6, 7, 8, 100, 4294967295][r.below(6)]
        bm = r.below(100)
        bk = 0
        if bm >= 82:
            bk = 1 + r.below(11)
        in_.bus = fx_bus(bk)
        tx = r.below(100)
        in_.tx_buffer_empty = tx >= 6
        in_.tx_blocked = 6 <= tx < 10
        fb = r.below(100)
        in_.fbs_slot = 1 if fb < 80 else fb % 5
        id_ = p["binding"]
        sm = r.below(100)
        if sm < 65:
            act, tgt, cnf = fx_action(1), fx_target(0, id_), fx_conf(2, id_)
        else:
            a1 = r.below(16)
            t1 = r.below(15)
            c1 = r.below(28)
            act, tgt, cnf = fx_action(a1), fx_target(t1, id_), fx_conf(c1, id_)
        g = sv.invalidate_gate_decide(in_, act, len(act), tgt, len(tgt), cnf, len(cnf))
        d.u(g.code)
        d.u(1 if g.arm_off_only else 0)
        d.t(g.text)
    elif comp == 3:
        in_ = r_save_inputs(r)
        p = sv.plan_save(in_)
        d.u(p.code)
        d.u(p.op)
        d.u(p.generation)
        d.t(p.text)
        d.u(plan_digest(p))
        if p.code == sv.PLAN_OK:
            d.u(1 if fd.validate_transition(p.w_new, in_.w, (in_.w_load, in_.w_stored_len), p.p_new, in_.p, (in_.p_load, in_.p_stored_len)) else 0)
    elif comp == 4:
        in_ = r_inv_inputs(r)
        p = sv.plan_invalidate(in_)
        d.u(p.code)
        d.u(p.op)
        d.u(p.generation)
        d.t(p.text)
        d.u(plan_digest(p))
        if p.code == sv.PLAN_OK:
            d.u(1 if fd.validate_transition(p.w_new, in_.w, (in_.w_load, in_.w_stored_len), p.p_new, in_.p, (in_.p_load, in_.p_stored_len)) else 0)
    elif comp == 5:
        t = r_txn(r)
        op = r.below(5)
        o = r.below(5)
        gen = r.next()
        pgen = r.next()
        d.t(sv.txn_outcome_text(op, o, t, gen, pgen))
        d.t(sv.txn_log_text(op, o, t, gen))
        d.u(sv.first_non_ok(t.w.err, t.p.err))
        d.u(sv.total_us(t.w.us, t.p.us))
        d.s(sv.txn_name(o))
        d.s(sv.key_name(t.w.outcome))
        d.s(sv.rb_name(t.w.rb_class))
        code = r.below(9)
        step = r.below(6)
        exc = r.below(3)
        d.t(sv.save_read_fail_text(code, step, 0 if exc == 0 else 2 if exc == 1 else 255))
        a = r_words(r, 20)
        b = r_words(r, 20)
        d.t(sv.save_changed_during_read_text(a, b))
        d.t(sv.save_changed_since_review_text(a, b))
        d.t(sv.save_l2_text(cap.capture_refusals(a, 8000), a))
        cls = r.below(11)
        why = r.below(14)
        d.t(sv.save_class_text(cls, why))
        d.t(sv.invalidate_class_text(cls))
        d.t(sv.invalidate_class_now_text(cls))
        id_ = p_u64(r)
        d.t(sv.save_phrase_text(sv.expected_phrase(sv.PHRASE_SAVE_REPLACE_CORRUPT, id_)))
        d.t(sv.invalidate_phrase_text(sv.expected_phrase(sv.PHRASE_INVALIDATE, id_)))
        d.t(sv.saved_text(gen))
        d.t(sv.invalidated_text(pgen, gen))
        d.t(sv.invalidate_generation_text(r.below(2) == 1))
        pk = r.below(10)
        pl, p, plen = fx_p(pk)
        part = r.below(3)
        d.t(sv.replace_corrupt_log_text(pl, p, plen, part))
    else:
        now = r.next()
        born = r.next()
        a = r.below(8)
        b2 = r.next()
        d.u(1 if sv.arm_expired((b2 + [0, 1, 119999, 120000, 120001, 30000, 4000000000, 0][a]) & U32, b2) else 0)
        d.u(1 if sv.arm_expired(now, born) else 0)
        o1 = r.below(2)
        o2 = r.below(4)
        d.u(1 if sv.save_integrity_ok(o1 == 1, o2) else 0)
        cls = r.below(10)
        un = r.below(2)
        d.u(sv.overlay_class(cls, un == 1))
        f = r.below(32)
        d.u(1 if sv.commit_bus_quiet(bool(f & 1), bool(f & 2), bool(f & 4), bool(f & 8), bool(f & 16)) else 0)
        b = cap.BusInputs()
        b.manual_write_in_progress = r.below(100) < 10
        b.correction_in_progress = r.below(100) < 10
        b.verification_pending = r.below(100) < 10
        b.free_power_operation_in_progress = r.below(100) < 5
        b.dump_operation_in_progress = r.below(100) < 5
        b.fallback_profile_op_in_progress = r.below(100) < 5
        tx = r.below(100)
        d.u(1 if sv.invalidate_bus_idle(b, tx >= 8, 8 <= tx < 14) else 0)
        ep = r.below(3)
        tt = r.below(2) == 1
        d.u(1 if sv.clock_trusted_for_save(tt, 0 if ep == 0 else 1790000000 if ep == 1 else 4294967295) else 0)
        g = r_gate_inputs(r)
        pr = cap.ProbeResults()
        pm = r.below(100)
        if pm < 40:
            pr = cap.ProbeResults(cap.PROBE_ABSENT, cap.PROBE_CLEAR, cap.PROBE_ABSENT)
        elif pm < 55:
            a2 = r.below(7)
            b3 = r.below(7)
            c3 = r.below(7)
            pr = cap.ProbeResults(a2, b3, c3)
        fg = sv.final_gate_decide(g, pr)
        d.u(fg.gr.code)
        d.u(fg.gr.slot)
        d.u(fg.gr.latch)
        d.u((4 if fg.gr.probe_fp else 0) + (2 if fg.gr.probe_dump else 0) + (1 if fg.gr.probe_r244 else 0))
        d.t(fg.gr.obl)
        d.t(fg.text)
        plain = cap.gate_decide(g, cap.ProbeResults())
        d.u(plain.code)
        d.t(sv.save_gate_refusal_text(plain, g))
        d.u(1 if sv.final_phase_inputs(g).bus.manual_write_in_progress else 0)
    return d.h


def random_tu() -> str:
    lines = [RANDOM_TU_CXX]
    for seed in range(1, RANDOM_CASES + 1):
        for comp in range(len(RANDOM_COMPONENTS)):
            lines.append(f'static_assert(rnd::comp_digest({seed}u, {comp}u) == 0x{r_comp_digest(seed, comp):016X}ULL, '
                         f'"FB-B2 random parity: {RANDOM_COMPONENTS[comp]} case {seed}");')
    lines.append("int main() { return 0; }")
    return "\n".join(lines) + "\n"


def section_random(tc: Toolchain):
    print(f"[4] randomized parity: {RANDOM_CASES} seeded cases x {len(RANDOM_COMPONENTS)} components, evaluated by the compiler")
    inc = tc.stage("random")
    tu = random_tu()
    r = tc.compile(inc, tu, "gnu++17")
    check(f"the C++ generator + header reproduce the Python mirror's digest of {RANDOM_CASES * len(RANDOM_COMPONENTS)} random cases (gnu++17)",
          r.returncode == 0, (r.stderr or "")[:1500])
    r = tc.compile(inc, tu, "gnu++20")
    check("...and under gnu++20", r.returncode == 0, (r.stderr or "")[:1500])
    bad = tu.replace("== 0x", "== 0x1", 1)
    r = tc.compile(inc, bad, "gnu++17")
    check("negative control: one corrupted digest is a static_assert failure naming its component and case",
          r.returncode != 0 and "FB-B2 random parity" in r.stderr, r.stderr[-300:])


# ===========================================================================================================
# Negative controls: every mutant is a text mutation of the header; each `old` occurs EXACTLY ONCE and the mutated header must fail to
# compile with the named message (a real static_assert naming the golden / table / random digest that kills it)
# ===========================================================================================================
GC_SG = "FB-B2 golden cases: SAVE GATE"
GC_IG = "FB-B2 golden cases: INVALIDATE GATE"
GC_SP = "FB-B2 golden cases: SAVE PLAN"
GC_IP = "FB-B2 golden cases: INVALIDATE PLAN"


def _drop(line: str) -> tuple[str, str]:
    return line, ""


def mutants() -> list[tuple[str, str, str, str]]:
    """(label, old, new, message that must appear in the compiler's output). Each `old` occurs exactly once."""
    M: list[tuple[str, str, str, str]] = []

    def add(label, old, new, msg):
        M.append((label, old, new, msg))

    # ---- action token, router --------------------------------------------------------------------------------------------
    add("token: a lower-case save is accepted", '  return exact(action, n, "SAVE")              ? ACT_SAVE',
        '  return (exact(action, n, "SAVE") || exact(action, n, "save")) ? ACT_SAVE', "FB-B2 value: action_token 'save'")
    add("token: a retired CAPTURE maps to SAVE", '  return exact(action, n, "SAVE")              ? ACT_SAVE',
        '  return (exact(action, n, "SAVE") || exact(action, n, "CAPTURE")) ? ACT_SAVE', "FB-B2 value: action_token 'CAPTURE'")
    add("token: a prefix of INVALIDATE is accepted", '         : exact(action, n, "INVALIDATE")      ? ACT_INVALIDATE',
        '         : starts_with(action, n, "INVALIDATE") ? ACT_INVALIDATE', "FB-B2 value: action_token 'INVALIDATEX'")
    add("token: RESTORE reads as SAVE", '         : exact(action, n, "RESTORE")         ? ACT_RESTORE',
        '         : exact(action, n, "RESTORE")         ? ACT_SAVE', "FB-B2 value: action_token 'RESTORE'")
    add("token: ACKNOWLEDGE is unsupported", '         : exact(action, n, "ACKNOWLEDGE")     ? ACT_ACKNOWLEDGE\n', "", "FB-B2 value: action_token 'ACKNOWLEDGE'")
    add("router: every token but SAVE routes to INVALIDATE", "constexpr bool is_invalidate_action(const char *action, size_t n) { return action_token(action, n) == ACT_INVALIDATE; }",
        "constexpr bool is_invalidate_action(const char *action, size_t n) { return action_token(action, n) != ACT_SAVE; }", "FB-B2 value: is_invalidate_action")
    add("router: SAVE routes to INVALIDATE (NUL-terminated overload)", "constexpr bool is_invalidate_action(const char *action) { return action_token(action) == ACT_INVALIDATE; }",
        "constexpr bool is_invalidate_action(const char *action) { return action_token(action) == ACT_SAVE; }", "FB-B2 value: is_invalidate_action 'SAVE' (NUL-terminated)")
    add("scan bound: the NUL-terminated action scan is 4", "constexpr size_t ACTION_SCAN_MAX = 16;", "constexpr size_t ACTION_SCAN_MAX = 4;", "FB-B2 value: constant ACTION_SCAN_MAX")
    add("echo: ECHO_MAX is 25", "constexpr size_t ECHO_MAX = 24;", "constexpr size_t ECHO_MAX = 25;", "FB-B2 value: constant ECHO_MAX")
    # FB-B2: re-anchored for F2 (the loop now runs over the examined bytes m = min(n, ECHO_MAX + ECHO_LOOK); the same mutant, the same killer)
    add("echo: the token is not cut", "  for (size_t i = 0; i < m && i < ECHO_MAX; i++)", "  for (size_t i = 0; i < m; i++)", "FB-B2 value: length of the longest unsupported_action_text")
    add("echo: a space is kept", "|| (c >= '0' && c <= '9') || c == '_';", "|| (c >= '0' && c <= '9') || c == '_' || c == ' ';", "FB-B2 value: echo_char_ok byte 32")
    add("echo: the closing quote is dropped", "  put_sanitised(t, action, n);\n  put_char(t, '\\'');", "  put_sanitised(t, action, n);", "FB-B2 text: unsupported_action_text")
    add("echo: RESTORE refusal names ACKNOWLEDGE", 'put(t, "RESTORE REFUSED - not implemented in this firmware");',
        'put(t, "ACKNOWLEDGE REFUSED - not implemented in this firmware");', "FB-B2 text: action_refusal_text: RESTORE")
    # ---- confirmation grammar ---------------------------------------------------------------------------------------------
    add("hex: lower-case digits are accepted", "constexpr bool hex_digit_ok(char c) { return (c >= '0' && c <= '9') || (c >= 'A' && c <= 'F'); }",
        "constexpr bool hex_digit_ok(char c) { return (c >= '0' && c <= '9') || (c >= 'A' && c <= 'F') || (c >= 'a' && c <= 'f'); }", "FB-B2 value: hex_digit_ok byte 97")
    add("hex: 15 digits are accepted",
        "  if (s == nullptr || n != ID_DIGITS)\n    return false;\n  for (size_t i = 0; i < ID_DIGITS; i++) {\n    if (!hex_digit_ok(s[i]))",
        "  if (s == nullptr || n > ID_DIGITS)\n    return false;\n  for (size_t i = 0; i < n; i++) {\n    if (!hex_digit_ok(s[i]))", "FB-B2 value: is_hex16 target kind 2")
    add("hex: letters are worth 9", "(uint64_t) (c - 'A' + 10)", "(uint64_t) (c - 'A' + 9)", "FB-B2 value: parse_hex16 target kind 0")
    add("phrase: INVALIDATE accepts REPLACE CORRUPT", '  if (kind == PHRASE_SAVE && n > after && exact(confirmation + after, n - after, " REPLACE CORRUPT")) {',
        '  if (n > after && exact(confirmation + after, n - after, " REPLACE CORRUPT")) {', "FB-B2 value: parse_phrase kind of confirmation kind 10")
    add("phrase: a trailing space is accepted", "  if (n == after) {\n    p.kind = kind;", "  if (n == after || (n == after + 1 && confirmation[after] == ' ')) {\n    p.kind = kind;",
        "FB-B2 value: parse_phrase kind of confirmation kind 4")
    add("phrase: a trailing newline is accepted", "  if (n == after) {\n    p.kind = kind;", "  if (n == after || (n == after + 1 && confirmation[after] == '\\n')) {\n    p.kind = kind;",
        "FB-B2 value: parse_phrase kind of confirmation kind 3")
    add("phrase: REPLACE alone is accepted", '  if (kind == PHRASE_SAVE && n > after && exact(confirmation + after, n - after, " REPLACE CORRUPT")) {',
        '  if (kind == PHRASE_SAVE && n > after && starts_with(confirmation + after, n - after, " REPLACE")) {', "FB-B2 value: parse_phrase kind of confirmation kind 15")
    add("phrase: a lower-case verb is accepted", '  if (starts_with(confirmation, n, "SAVE ")) {', '  if (starts_with(confirmation, n, "SAVE ") || starts_with(confirmation, n, "save ")) {',
        "FB-B2 value: parse_phrase kind of confirmation kind 11")
    add("phrase: the id may be shorter (the hex check is dropped)", "  if (n < head + ID_DIGITS || !is_hex16(confirmation + head, ID_DIGITS))\n    return p;",
        "  if (n < head + ID_DIGITS)\n    return p;", "FB-B2 value: parse_phrase kind of confirmation kind 5")
    add("expected_phrase: the REPLACE CORRUPT suffix is dropped", '  if (kind == PHRASE_SAVE_REPLACE_CORRUPT)\n    put(t, " REPLACE CORRUPT");', "",
        "FB-B2 text: expected_phrase kind 2")
    add("expected_phrase: INVALIDATE uses the SAVE verb", '  else if (kind == PHRASE_INVALIDATE)\n    put(t, "INVALIDATE ");', '  else if (kind == PHRASE_INVALIDATE)\n    put(t, "SAVE ");',
        "FB-B2 text: expected_phrase kind 3")
    add("phrase_equals: a longer confirmation matches by its prefix (a trailing NUL reads as the buffer's terminator)",
        "if (confirmation == nullptr || expected.size() == 0 || n != expected.size())", "if (confirmation == nullptr || expected.size() == 0 || n < expected.size())",
        "FB-B2 value: phrase_equals confirmation kind 22 vs expected_phrase")
    add("phrase_equals: an empty expected phrase matches", "if (confirmation == nullptr || expected.size() == 0 || n != expected.size())",
        "if (confirmation == nullptr || n != expected.size())", "FB-B2 value: phrase_equals: an empty expected phrase never matches")
    # ---- arm TTL, integrity, overlay --------------------------------------------------------------------------------------
    add("arm TTL: 120001 ms", "constexpr uint32_t ARM_TTL_MS = 120000u;", "constexpr uint32_t ARM_TTL_MS = 120001u;", "FB-B2 value: constant ARM_TTL_MS")
    add("arm TTL: the boundary is exclusive", "return (uint32_t) (now_ms - on_ms) >= ARM_TTL_MS; }", "return (uint32_t) (now_ms - on_ms) > ARM_TTL_MS; }", "FB-B2 value: arm_expired born")
    add("arm TTL: not wrap safe", "return (uint32_t) (now_ms - on_ms) >= ARM_TTL_MS; }", "return now_ms >= on_ms + ARM_TTL_MS; }", "FB-B2 value: arm_expired born")
    add("pre-commit wait: 7000 ms", "constexpr uint32_t PRECOMMIT_WAIT_MS = 3000u;", "constexpr uint32_t PRECOMMIT_WAIT_MS = 7000u;", "FB-B2 value: constant PRECOMMIT_WAIT_MS")
    add("purpose: SAVE shares REVIEW's value", "constexpr uint8_t PURPOSE_SAVE = 2;", "constexpr uint8_t PURPOSE_SAVE = 1;", "FB-B2 value: constant PURPOSE_SAVE")
    add("integrity: any purpose passes", "return op_in_progress && op_purpose == PURPOSE_SAVE; }", "return op_in_progress && op_purpose != 0; }",
        "FB-B2 value: save_integrity_ok op=True purpose=1")
    add("integrity: the operation flag is not required", "return op_in_progress && op_purpose == PURPOSE_SAVE; }", "return op_purpose == PURPOSE_SAVE; }", "FB-B2 value: save_integrity_ok op=False purpose=2")
    add("overlay: the composed class wins", "return unconfirmed ? (uint8_t) ecco_fbdurable::EPC_SAVE_UNCONFIRMED : cls;", "return cls;", "FB-B2 value: overlay_class cls=5 unconfirmed=True")
    # ---- the SAVE gate ---------------------------------------------------------------------------------------------------
    add("G1 is skipped", "if (gr.code == ecco_fbcap::GATE_REFUSE_IN_FLIGHT) {  // G1", "if (false) {  // G1", GC_SG)
    add("G1 touches more than the arm (arm_off_only is dropped)",
        "    r = save_refuse(r, SG_IN_FLIGHT, save_in_flight_text());\n    r.arm_off_only = true;\n    return r;", "    r = save_refuse(r, SG_IN_FLIGHT, save_in_flight_text());\n    return r;",
        "FB-B2 value: sg row")
    add("G1 gate: only the operation flag counts (the dispatch is ignored)", "  if (op_in_progress || dispatch_running) {\n    r.code = SG_IN_FLIGHT;", "  if (op_in_progress) {\n    r.code = SG_IN_FLIGHT;",
        "FB-B2 value: save_in_flight_gate op=0 dispatch=1")
    add("G0 is skipped", "if (token != ACT_SAVE)  // G0", "if (false)  // G0", GC_SG)
    add("G0 accepts INVALIDATE too", "if (token != ACT_SAVE)  // G0", "if (token != ACT_SAVE && token != ACT_INVALIDATE)  // G0", GC_SG)
    add("G2 is skipped", "if (!in.arm_was_on)  // G2", "if (false)  // G2", GC_SG)
    add("G3: a candidate with id 0 is saveable", "if (!in.cand_valid || !in.cand_saveable || in.cand_id == 0)  // G3", "if (!in.cand_valid || !in.cand_saveable)  // G3", GC_SG)
    add("G3: the saveable flag is ignored", "if (!in.cand_valid || !in.cand_saveable || in.cand_id == 0)  // G3", "if (!in.cand_valid || in.cand_id == 0)  // G3", GC_SG)
    add("G3: the valid flag is ignored", "if (!in.cand_valid || !in.cand_saveable || in.cand_id == 0)  // G3", "if (!in.cand_saveable || in.cand_id == 0)  // G3", GC_SG)
    add("G4: the boundary is exclusive", "if (ecco_fbcap::candidate_expired(in.now_ms, in.cand_ms))  // G4", "if (in.now_ms - in.cand_ms > ecco_fbcap::CANDIDATE_TTL_MS)  // G4", GC_SG)
    add("G4: not wrap safe", "if (ecco_fbcap::candidate_expired(in.now_ms, in.cand_ms))  // G4", "if (in.now_ms >= in.cand_ms + ecco_fbcap::CANDIDATE_TTL_MS)  // G4", GC_SG)
    add("G4 is skipped", "if (ecco_fbcap::candidate_expired(in.now_ms, in.cand_ms))  // G4", "if (false)  // G4", GC_SG)
    add("G5 is skipped", "if (!is_hex16(target_id, target_len))  // G5", "if (false)  // G5", GC_SG)
    add("G6 is skipped", "if (parse_hex16(target_id, target_len) != in.cand_id)  // G6", "if (false)  // G6", GC_SG)
    add("G7: the phrase never carries REPLACE CORRUPT", "  const bool replace = ecco_fbdurable::save_requires_replace_phrase(in.cand_prior_class);",
        "  const bool replace = false;", GC_SG)
    add("G7: REPLACE CORRUPT is always required", "  const bool replace = ecco_fbdurable::save_requires_replace_phrase(in.cand_prior_class);",
        "  const bool replace = true;", GC_SG)
    add("G7 is skipped", "if (!phrase_equals(confirmation, confirmation_len, expected))  // G7", "if (false)  // G7", GC_SG)
    add("G7: the verb is not part of the comparison", "  const TextBuf expected = expected_phrase(replace ? PHRASE_SAVE_REPLACE_CORRUPT : PHRASE_SAVE, in.cand_id);",
        "  const TextBuf expected = expected_phrase(replace ? PHRASE_SAVE_REPLACE_CORRUPT : PHRASE_INVALIDATE, in.cand_id);", GC_SG)
    add("G8 is skipped", "if (!in.boot_loaded)  // G8", "if (false)  // G8", GC_SG)
    add("G9 is skipped", "if (in.unconfirmed)  // G9", "if (false)  // G9", GC_SG)
    add("G9a is skipped", "if (in.read_anomaly != 0)  // G9a", "if (false)  // G9a", GC_SG)
    add("G9a: only anomaly bit 4 refuses", "if (in.read_anomaly != 0)  // G9a", "if (in.read_anomaly > 3)  // G9a", GC_SG)
    add("G10 is skipped", "if (!in.hb_ok)  // G10", "if (false)  // G10", GC_SG)
    add("G11 is skipped", "if (!in.time_trusted)  // G11", "if (false)  // G11", GC_SG)
    add("G12 is skipped", "if (gr.code == ecco_fbcap::GATE_REFUSE_ARMS)  // G12", "if (false)  // G12", GC_SG)
    add("G13 is skipped", "if (in.writes_fp_now != in.cand_writes_fp)  // G13", "if (false)  // G13", GC_SG)
    add("G13 is a less-than compare", "if (in.writes_fp_now != in.cand_writes_fp)  // G13", "if (in.writes_fp_now < in.cand_writes_fp)  // G13", GC_SG)
    add("G14 is reported as FBS", "    case ecco_fbcap::GATE_REFUSE_BUS:\n      return save_refuse(r, SG_BUS, slot_text);",
        "    case ecco_fbcap::GATE_REFUSE_BUS:\n      return save_refuse(r, SG_FBS, slot_text);", GC_SG)
    add("G16 Free Power is reported as Dump", "    case ecco_fbcap::GATE_REFUSE_FP:\n      return save_refuse(r, SG_FP, slot_text);",
        "    case ecco_fbcap::GATE_REFUSE_FP:\n      return save_refuse(r, SG_DUMP, slot_text);", GC_SG)
    add("G16 a forged unknown capture decision accepts", "    default:  // GATE_UNSET or an unknown code: never an accept\n      return save_refuse(r, SG_UNSET, save_internal_text());",
        "    default:\n      r.code = SG_ACCEPT;\n      return r;", "FB-B2 value: save_gate_with_result forged capture gate code 0")
    add("accept forgets replace_corrupt", "      r.code = SG_ACCEPT;\n      r.replace_corrupt = replace;", "      r.code = SG_ACCEPT;\n      r.replace_corrupt = false;", "FB-B2 value: sg row")
    add("the SAVE gate masks the own holds (it would never see an operation in flight)",
        "  return save_gate_with_result(in, action, action_len, target_id, target_len, confirmation, confirmation_len, g,\n                               ecco_fbcap::gate_decide(g, ProbeResults{}));",
        "  return save_gate_with_result(in, action, action_len, target_id, target_len, confirmation, confirmation_len, g,\n                               ecco_fbcap::gate_decide(final_phase_inputs(g), ProbeResults{}));", GC_SG)
    add("the SAVE gate probes a marker (a probe result is invented)",
        "                               ecco_fbcap::gate_decide(g, ProbeResults{}));", "                               ecco_fbcap::gate_decide(g, ProbeResults{ecco_fbcap::PROBE_ABSENT, ecco_fbcap::PROBE_CLEAR, ecco_fbcap::PROBE_ABSENT}));",
        "FB-B2 text: sg base with gate scenario 0: obl")
    # order swaps (the S1 8.5 order is pinned by the golden-case table)
    add("order: G2 before G0",
        "  if (token != ACT_SAVE)  // G0\n    return save_refuse(r, SG_UNSUPPORTED, action_refusal_text(token, action, action_len));\n"
        "  if (!in.arm_was_on)  // G2\n    return save_refuse(r, SG_ARM_OFF, save_arm_off_text());\n",
        "  if (!in.arm_was_on)  // G2\n    return save_refuse(r, SG_ARM_OFF, save_arm_off_text());\n"
        "  if (token != ACT_SAVE)  // G0\n    return save_refuse(r, SG_UNSUPPORTED, action_refusal_text(token, action, action_len));\n", GC_SG)
    add("order: G9 before G8", "  if (!in.boot_loaded)  // G8\n    return save_refuse(r, SG_NOT_LOADED, save_not_loaded_text());\n  if (in.unconfirmed)  // G9\n    return save_refuse(r, SG_UNCONFIRMED, save_prior_unknown_text());\n",
        "  if (in.unconfirmed)  // G9\n    return save_refuse(r, SG_UNCONFIRMED, save_prior_unknown_text());\n  if (!in.boot_loaded)  // G8\n    return save_refuse(r, SG_NOT_LOADED, save_not_loaded_text());\n", GC_SG)
    add("order: G10 before G9a", "  if (in.read_anomaly != 0)  // G9a\n    return save_refuse(r, SG_ANOMALY, save_anomaly_text());\n  if (!in.hb_ok)  // G10\n    return save_refuse(r, SG_HB, save_hb_text());\n",
        "  if (!in.hb_ok)  // G10\n    return save_refuse(r, SG_HB, save_hb_text());\n  if (in.read_anomaly != 0)  // G9a\n    return save_refuse(r, SG_ANOMALY, save_anomaly_text());\n", GC_SG)
    add("order: G13 before G12", "  if (gr.code == ecco_fbcap::GATE_REFUSE_ARMS)  // G12\n    return save_refuse(r, SG_ARMS, save_arms_text());\n  if (in.writes_fp_now != in.cand_writes_fp)  // G13\n    return save_refuse(r, SG_WRITES, save_writes_text());\n",
        "  if (in.writes_fp_now != in.cand_writes_fp)  // G13\n    return save_refuse(r, SG_WRITES, save_writes_text());\n  if (gr.code == ecco_fbcap::GATE_REFUSE_ARMS)  // G12\n    return save_refuse(r, SG_ARMS, save_arms_text());\n", GC_SG)
    add("order: G6 before G5", "  if (!is_hex16(target_id, target_len))  // G5\n    return save_refuse(r, SG_ID_FORMAT, save_id_format_text());\n  if (parse_hex16(target_id, target_len) != in.cand_id)  // G6\n    return save_refuse(r, SG_ID_MISMATCH, save_id_mismatch_text());\n",
        "  if (parse_hex16(target_id, target_len) != in.cand_id)  // G6\n    return save_refuse(r, SG_ID_MISMATCH, save_id_mismatch_text());\n  if (!is_hex16(target_id, target_len))  // G5\n    return save_refuse(r, SG_ID_FORMAT, save_id_format_text());\n", GC_SG)
    add("order: G4 before G3", "  if (!in.cand_valid || !in.cand_saveable || in.cand_id == 0)  // G3\n    return save_refuse(r, SG_NO_CANDIDATE, save_no_candidate_text());\n  if (ecco_fbcap::candidate_expired(in.now_ms, in.cand_ms))  // G4\n    return save_refuse(r, SG_EXPIRED, save_expired_text());\n",
        "  if (ecco_fbcap::candidate_expired(in.now_ms, in.cand_ms))  // G4\n    return save_refuse(r, SG_EXPIRED, save_expired_text());\n  if (!in.cand_valid || !in.cand_saveable || in.cand_id == 0)  // G3\n    return save_refuse(r, SG_NO_CANDIDATE, save_no_candidate_text());\n", GC_SG)
    # ---- the INVALIDATE gate ---------------------------------------------------------------------------------------------
    add("I1 is skipped", "  if (in.bus.fallback_profile_op_in_progress || in.bus.fallback_profile_capture_dispatch_running) {  // I1", "  if (false) {  // I1", GC_IG)
    add("I1 touches more than the arm (arm_off_only is dropped)", "    r = invalidate_refuse(r, IG_IN_FLIGHT, invalidate_in_flight_text());\n    r.arm_off_only = true;\n    return r;",
        "    r = invalidate_refuse(r, IG_IN_FLIGHT, invalidate_in_flight_text());\n    return r;", "FB-B2 value: ig row")
    add("INVALIDATE gate: the token is not checked", "  if (token != ACT_INVALIDATE)\n", "  if (false)\n", GC_IG)
    add("I2 is skipped", "if (!in.arm_was_on)  // I2", "if (false)  // I2", GC_IG)
    add("I3 is skipped", "if (!is_hex16(target_id, target_len))  // I3", "if (false)  // I3", GC_IG)
    add("I4 is skipped", "if (!phrase_equals(confirmation, confirmation_len, expected))  // I4", "if (false)  // I4", GC_IG)
    add("I4: the SAVE verb is expected", "  const TextBuf expected = expected_phrase(PHRASE_INVALIDATE, id);", "  const TextBuf expected = expected_phrase(PHRASE_SAVE, id);", GC_IG)
    add("I5 is skipped", "if (!in.boot_loaded)  // I5", "if (false)  // I5", GC_IG)
    add("I6 is skipped", "if (in.read_anomaly != 0)  // I6", "if (false)  // I6", GC_IG)
    add("I7 is skipped", "if (in.unconfirmed)  // I7", "if (false)  // I7", GC_IG)
    add("I8 accepts every saveable class", "if (!ecco_fbdurable::invalidate_class_permitted(in.cls))  // I8", "if (!ecco_fbdurable::save_class_permitted(in.cls))  // I8", GC_IG)
    add("I8 is skipped", "if (!ecco_fbdurable::invalidate_class_permitted(in.cls))  // I8", "if (false)  // I8", GC_IG)
    add("I9 is skipped", "if (in.p_load != ecco_fallback::LOAD_OK || in.p.binding != id)  // I9", "if (false)  // I9", GC_IG)
    add("I9 does not need a loaded profile", "if (in.p_load != ecco_fallback::LOAD_OK || in.p.binding != id)  // I9", "if (in.p.binding != id)  // I9", GC_IG)
    add("I10 is skipped", "  if (!ecco_fallback::profile_invalidate_permitted(in.p) ||\n      !ecco_fbdurable::invalidate_generation_permitted(in.p.generation, wc, in.w.hw_generation, in.seen_hw_gen))  // I10",
        "  if (false)  // I10", GC_IG)
    add("I10 forgets the seen high-water mark", "!ecco_fbdurable::invalidate_generation_permitted(in.p.generation, wc, in.w.hw_generation, in.seen_hw_gen))  // I10",
        "!ecco_fbdurable::invalidate_generation_permitted(in.p.generation, wc, in.w.hw_generation, 0u))  // I10", GC_IG)
    add("I11 is skipped", "if (!invalidate_bus_idle(in.bus, in.tx_buffer_empty, in.tx_blocked))  // I11", "if (false)  // I11", GC_IG)
    add("I12 is skipped", "if (!ecco_fbdurable::fbs_slot_clear(in.fbs_slot)) {  // I12", "if (false) {  // I12", GC_IG)
    add("the INVALIDATE bus predicate ignores the transmit block", "return !ecco_fbcap::bus_busy(b) && tx_buffer_empty && !tx_blocked;", "return !ecco_fbcap::bus_busy(b) && tx_buffer_empty;",
        "FB-B2 value: invalidate_bus_idle bus scenario")
    add("the INVALIDATE bus predicate ignores the busy flags", "return !ecco_fbcap::bus_busy(b) && tx_buffer_empty && !tx_blocked;", "return tx_buffer_empty && !tx_blocked;",
        "FB-B2 value: invalidate_bus_idle bus scenario")
    add("the INVALIDATE bus predicate ignores an empty queue", "return !ecco_fbcap::bus_busy(b) && tx_buffer_empty && !tx_blocked;", "return !ecco_fbcap::bus_busy(b) && !tx_blocked;",
        "FB-B2 value: invalidate_bus_idle bus scenario")
    add("invalidate_in_flight_gate: the dispatch is ignored", "  if (op_in_progress || dispatch_running) {\n    r.code = IG_IN_FLIGHT;", "  if (op_in_progress) {\n    r.code = IG_IN_FLIGHT;",
        "FB-B2 value: invalidate_in_flight_gate op=0 dispatch=1")
    # ---- own-hold masking, bus quiet, clock ---------------------------------------------------------------------------------
    add("masking forgets the write lock", "  g.bus.manual_write_in_progress = false;\n  return g;", "  return g;", "FB-B2 value: final_gate_decide")
    add("masking forgets the capture dispatch", "  g.bus.fallback_profile_capture_dispatch_running = false;\n", "", "FB-B2 value: final_gate_decide")
    add("masking forgets the operation flag", "  g.bus.fallback_profile_op_in_progress = false;\n  g.bus.fallback_profile_capture_dispatch_running = false;\n",
        "  g.bus.fallback_profile_capture_dispatch_running = false;\n", "FB-B2 value: final_gate_decide")
    add("masking also clears a clock correction", "  g.bus.manual_write_in_progress = false;\n  return g;", "  g.bus.manual_write_in_progress = false;\n  g.bus.correction_in_progress = false;\n  return g;",
        "FB-B2 value: final_phase_inputs: EXACTLY")
    add("masking also clears the write arms", "  g.bus.manual_write_in_progress = false;\n  return g;", "  g.bus.manual_write_in_progress = false;\n  g.free_power_write_enable = false;\n  return g;",
        "FB-B2 value: final_phase_inputs: EXACTLY")
    add("the final gate asks the unmasked inputs", "  f.gr = ecco_fbcap::gate_decide(m, pr);", "  f.gr = ecco_fbcap::gate_decide(g, pr);", "FB-B2 value: final_gate_decide")
    add("the final gate renders the refusal over the unmasked inputs", "  f.text = save_gate_refusal_text(f.gr, m);", "  f.text = save_gate_refusal_text(f.gr, g);", "FB-B2 text: final_gate_decide")
    add("commit quiet: the operation flag is not required", "return op_in_progress && mutex_held && !correction_in_progress && tx_buffer_empty && !tx_blocked;",
        "return mutex_held && !correction_in_progress && tx_buffer_empty && !tx_blocked;", "FB-B2 value: commit_bus_quiet")
    add("commit quiet: the write lock is not required", "return op_in_progress && mutex_held && !correction_in_progress && tx_buffer_empty && !tx_blocked;",
        "return op_in_progress && !correction_in_progress && tx_buffer_empty && !tx_blocked;", "FB-B2 value: commit_bus_quiet")
    add("commit quiet: a clock correction is ignored", "return op_in_progress && mutex_held && !correction_in_progress && tx_buffer_empty && !tx_blocked;",
        "return op_in_progress && mutex_held && tx_buffer_empty && !tx_blocked;", "FB-B2 value: commit_bus_quiet")
    add("commit quiet: a blocked queue is ignored", "return op_in_progress && mutex_held && !correction_in_progress && tx_buffer_empty && !tx_blocked;",
        "return op_in_progress && mutex_held && !correction_in_progress && tx_buffer_empty;", "FB-B2 value: commit_bus_quiet")
    add("commit quiet: a non-empty queue is ignored", "return op_in_progress && mutex_held && !correction_in_progress && tx_buffer_empty && !tx_blocked;",
        "return op_in_progress && mutex_held && !correction_in_progress && !tx_blocked;", "FB-B2 value: commit_bus_quiet")
    add("clock: a zero epoch is trusted", "constexpr bool clock_trusted_for_save(bool time_trusted, uint32_t epoch) { return time_trusted && epoch != 0; }",
        "constexpr bool clock_trusted_for_save(bool time_trusted, uint32_t epoch) { return time_trusted; }", "FB-B2 value: clock_trusted_for_save trusted=True epoch=0")
    # ---- plan_save -------------------------------------------------------------------------------------------------------
    _pc = "  if (in.cls != in.cand_prior_class || f.generation != in.cand_prior_gen || f.binding != in.cand_prior_binding)\n"
    add("plan: the candidate's prior class is not compared", _pc, "  if (f.generation != in.cand_prior_gen || f.binding != in.cand_prior_binding)\n", GC_SP)
    add("plan: the candidate's prior generation is not compared", _pc, "  if (in.cls != in.cand_prior_class || f.binding != in.cand_prior_binding)\n", GC_SP)
    add("plan: the candidate's prior binding is not compared", _pc, "  if (in.cls != in.cand_prior_class || f.generation != in.cand_prior_gen)\n", GC_SP)
    add("plan: the overlay is not refused", "  if (in.unconfirmed)\n    return plan_refuse(r, PLAN_UNCONFIRMED, save_prior_unknown_text());", "", GC_SP)
    add("plan: a read anomaly is not refused", "  if (in.read_anomaly != 0)\n    return plan_refuse(r, PLAN_ANOMALY, save_anomaly_text());\n  if (!ecco_fbdurable::save_class_permitted(cls))",
        "  if (!ecco_fbdurable::save_class_permitted(cls))", GC_SP)
    add("plan: every class except UNREADABLE is saveable (SAVE_UNCONFIRMED overlay passes)", "  if (!ecco_fbdurable::save_class_permitted(cls))\n    return plan_refuse(r, PLAN_CLASS, save_class_text(cls, in.why));",
        "  if (cls == ecco_fbdurable::EPC_UNREADABLE)\n    return plan_refuse(r, PLAN_CLASS, save_class_text(cls, in.why));", GC_SP)
    add("plan: the REPLACE flag is not cross-checked", "  if (in.replace_corrupt != replace)\n    return plan_refuse(r, PLAN_CONTEXT, ecco_fbcap::internal_context_text());", "", GC_SP)
    add("plan: a zero capture time is stored", "  if (in.captured_epoch == 0)\n    return plan_refuse(r, PLAN_CLOCK, save_time_text());", "", GC_SP)
    add("plan: the seen high-water mark is not part of the generation base",
        "ecco_fbdurable::save_generation_base(pc, in.p.generation, wc, in.w.hw_generation, in.seen_hw_gen);", "ecco_fbdurable::save_generation_base(pc, in.p.generation, wc, in.w.hw_generation, 0u);", GC_SP)
    add("plan: the new generation is the base itself (does not advance)", "  const uint32_t gen = base + 1u;", "  const uint32_t gen = base;", GC_SP)
    add("plan: an exhausted counter wraps", "  if (!ecco_fbdurable::save_generation_available(base))\n    return plan_refuse(r, PLAN_GENERATION, save_generation_text());",
        "", GC_SP)
    add("plan: the record's generation is not the witness' generation", "  pn.generation = gen;\n  pn.captured_epoch = in.captured_epoch;", "  pn.generation = gen + 1u;\n  pn.captured_epoch = in.captured_epoch;", GC_SP)
    add("plan: the capture time is not stored", "  pn.generation = gen;\n  pn.captured_epoch = in.captured_epoch;", "  pn.generation = gen;\n", GC_SP)
    add("plan: the witness always names the prior (even a non-authentic one)", "authentic ? in.p.generation : 0u, authentic ? in.p.binding : 0u, ecco_fbdurable::FALLBACK_PROFILE_KEY,",
        "in.p.generation, in.p.binding, ecco_fbdurable::FALLBACK_PROFILE_KEY,", GC_SP)
    add("plan: the witness never names the prior", "authentic ? in.p.generation : 0u, authentic ? in.p.binding : 0u, ecco_fbdurable::FALLBACK_PROFILE_KEY,",
        "0u, 0u, ecco_fbdurable::FALLBACK_PROFILE_KEY,", GC_SP)
    add("plan: REPLACE CORRUPT is written as a plain SAVE", "  const uint8_t op = replace ? ecco_fbdurable::PROV_OP_REPLACE_CORRUPT : ecco_fbdurable::PROV_OP_SAVE;",
        "  const uint8_t op = ecco_fbdurable::PROV_OP_SAVE;", GC_SP)
    add("plan: a plain SAVE is written as REPLACE CORRUPT", "  const uint8_t op = replace ? ecco_fbdurable::PROV_OP_REPLACE_CORRUPT : ecco_fbdurable::PROV_OP_SAVE;",
        "  const uint8_t op = ecco_fbdurable::PROV_OP_REPLACE_CORRUPT;", GC_SP)
    add("plan: the witness names the stored record, not the new one", "      gen, pn.binding, authentic ? in.p.generation", "      gen, in.p.binding, authentic ? in.p.generation", GC_SP)
    add("plan: the witness leads with the old generation", "      gen, pn.binding, authentic ? in.p.generation", "      base, pn.binding, authentic ? in.p.generation", GC_SP)
    # ---- plan_invalidate ---------------------------------------------------------------------------------------------------
    add("invalidate plan: the overlay is not refused", "  if (in.unconfirmed)\n    return plan_refuse(r, PLAN_UNCONFIRMED, invalidate_prior_unknown_text());", "", GC_IP)
    add("invalidate plan: any class is invalidatable", "  if (!ecco_fbdurable::invalidate_class_permitted(cls))\n    return plan_refuse(r, PLAN_CLASS, invalidate_class_now_text(cls));", "", GC_IP)
    add("invalidate plan: the named binding is not compared", "  if (in.p_load != ecco_fallback::LOAD_OK || in.p.binding != in.target_id)\n    return plan_refuse(r, PLAN_BINDING_CHANGED, invalidate_changed_text());", "", GC_IP)
    add("invalidate plan: the generation guards are skipped (invalidate_profile would wrap)",
        "  if (!ecco_fallback::profile_invalidate_permitted(in.p) ||\n      !ecco_fbdurable::invalidate_generation_permitted(in.p.generation, wc, in.w.hw_generation, in.seen_hw_gen))\n    return plan_refuse(r, PLAN_GENERATION, invalidate_generation_text(in.p.generation == ecco_fbdurable::GENERATION_MAX));",
        "", GC_IP)
    add("invalidate plan: the seen high-water mark is ignored",
        "      !ecco_fbdurable::invalidate_generation_permitted(in.p.generation, wc, in.w.hw_generation, in.seen_hw_gen))\n    return plan_refuse(r, PLAN_GENERATION, invalidate_generation_text(in.p.generation == ecco_fbdurable::GENERATION_MAX));",
        "      !ecco_fbdurable::invalidate_generation_permitted(in.p.generation, wc, in.w.hw_generation, 0u))\n    return plan_refuse(r, PLAN_GENERATION, invalidate_generation_text(in.p.generation == ecco_fbdurable::GENERATION_MAX));", GC_IP)
    add("invalidate plan: the witness does not name the prior", "      pn.generation, pn.binding, in.p.generation, in.p.binding, ecco_fbdurable::FALLBACK_PROFILE_KEY,",
        "      pn.generation, pn.binding, 0u, 0u, ecco_fbdurable::FALLBACK_PROFILE_KEY,", GC_IP)
    add("invalidate plan: the witness op is SAVE", "      ecco_fallback::PROFILE_SCHEMA, ecco_fbdurable::PROV_OP_INVALIDATE);\n  if (!invalidate_pair_valid", "      ecco_fallback::PROFILE_SCHEMA, ecco_fbdurable::PROV_OP_SAVE);\n  if (!invalidate_pair_valid", GC_IP)
    add("invalidate plan: the reported generation is the prior's", "  r.op = ecco_fbdurable::PROV_OP_INVALIDATE;\n  r.generation = pn.generation;", "  r.op = ecco_fbdurable::PROV_OP_INVALIDATE;\n  r.generation = in.p.generation;", GC_IP)
    # ---- outcome ----------------------------------------------------------------------------------------------------------
    add("werr: the profile error comes first", "constexpr uint32_t first_non_ok(int32_t err_w, int32_t err_p) { return (uint32_t) (err_w != 0 ? err_w : err_p); }",
        "constexpr uint32_t first_non_ok(int32_t err_w, int32_t err_p) { return (uint32_t) (err_p != 0 ? err_p : err_w); }", "FB-B2 value: first_non_ok")
    add("us: the maximum, not the sum", "constexpr uint32_t total_us(uint32_t w_us, uint32_t p_us) { return (uint32_t) (w_us + p_us); }",
        "constexpr uint32_t total_us(uint32_t w_us, uint32_t p_us) { return w_us > p_us ? w_us : p_us; }", "FB-B2 value: total_us")
    add("outcome: witness_advanced is inverted", "    if (r.witness_advanced != 0)\n      return inv ?", "    if (r.witness_advanced == 0)\n      return inv ?", "FB-B2 text: txn_outcome_text cell")
    add("outcome: a SAVE reports the prior generation", "    return inv ? invalidated_text(prior_generation, generation) : saved_text(generation);",
        "    return inv ? invalidated_text(prior_generation, generation) : saved_text(prior_generation);", "FB-B2 text: txn_outcome_text cell")
    add("outcome: an INVALIDATE reports its generations swapped", "    return inv ? invalidated_text(prior_generation, generation) : saved_text(generation);",
        "    return inv ? invalidated_text(generation, prior_generation) : saved_text(generation);", "FB-B2 text: txn_outcome_text cell")
    add("outcome: NOT_COMMITTED names the profile error", "    return inv ? invalidate_not_committed_text((uint32_t) r.w.err, prior_generation) : save_not_committed_text((uint32_t) r.w.err);",
        "    return inv ? invalidate_not_committed_text((uint32_t) r.p.err, prior_generation) : save_not_committed_text((uint32_t) r.p.err);", "FB-B2 text: txn_outcome_text cell")
    add("outcome: UNKNOWN always details the witness key", "  const ecco_fbdurable::KeyReport &k = r.w.outcome == ecco_fbdurable::KEY_UNKNOWN_REBOOT ? r.w : r.p;",
        "  const ecco_fbdurable::KeyReport &k = r.w;", "FB-B2 text: save_unknown_text")
    add("outcome: an unknown op reads as a SAVE", "  if (!inv && op != ecco_fbdurable::PROV_OP_SAVE && op != ecco_fbdurable::PROV_OP_REPLACE_CORRUPT)\n    return ecco_fbcap::internal_context_text();",
        "", "FB-B2 text: txn_outcome_text cell")
    add("outcome: a refusal without a reason reads as a success", "  if (outcome == ecco_fbdurable::TXN_REFUSED_LATCHED)\n    return txn_refusal_text(op, r.refusal);",
        "  if (outcome == ecco_fbdurable::TXN_REFUSED_LATCHED)\n    return saved_text(generation);", "FB-B2 text: txn_outcome_text cell")
    add("outcome: a latched refusal reads as an invalid transition", "  if (refusal == ecco_fbdurable::REFUSAL_LATCHED)\n    return inv ? invalidate_prior_unknown_text() : save_prior_unknown_text();",
        "  if (refusal == ecco_fbdurable::REFUSAL_LATCHED)\n    return inv ? invalidate_internal_text() : save_internal_record_text();", "FB-B2 text: txn_refusal_text")
    add("outcome: the error 0 renders E0", "  if (err == 0) {\n    put_char(t, '-');\n    return;\n  }\n  put_char(t, 'E');", "  put_char(t, 'E');", "FB-B2 text: save_unknown_text")
    add("outcome: the readback name is dropped from UNKNOWN", "  put_char(t, '/');\n  put(t, rb_name(k.rb_class));", "", "FB-B2 text: save_unknown_text")
    add("outcome: SAVED loses its verified clause", 'put(t, " saved (verified this boot)");', 'put(t, " saved");', "FB-B2 text: saved_text")
    add("outcome: the NOT COMMITTED text says failed", 'put(t, "SAVE NOT COMMITTED - storage refused the write (");', 'put(t, "SAVE NOT COMMITTED - storage write failed (");',
        "FB-B2 text: save_not_committed_text")
    add("text: the heartbeat refusal names the supervision", '"Home Assistant heartbeat is not stable; wait until the dashboard shows it healthy, then review and save again"',
        '"Home Assistant supervision heartbeat is not stable; wait until the dashboard shows it healthy, then review and save again"', "FB-B2 text: save_hb_text")
    add("text: the INVALIDATE busy refusal waits", '"inverter busy; try again"', '"inverter busy; wait and try again"', "FB-B2 text: invalidate_busy_text")
    add("text: the acceptance line is dropped to the REVIEW wording", 'put(t, "save in progress - re-reading live configuration");',
        'put(t, "review in progress (read-only)");', "FB-B2 text: save_in_progress_text")
    add("text: the arm refusal names the wrong arm", 'constexpr TextBuf save_arm_off_text() { return save_refused("ECCO Fallback Profile Arm is not on"); }',
        'constexpr TextBuf save_arm_off_text() { return save_refused("ECCO Fallback Arm is not on"); }', "FB-B2 text: save_arm_off_text")
    add("text: the phrase refusal does not echo the expected phrase", "  put(t, SAVE_REFUSED_PREFIX);\n  put(t, \"confirmation phrase mismatch (expected '\");\n  put(t, expected.c_str());\n  put(t, \"')\");",
        "  put(t, SAVE_REFUSED_PREFIX);\n  put(t, \"confirmation phrase mismatch (expected '\");\n  put(t, \"SAVE\");\n  put(t, \"')\");", "FB-B2 text: save_phrase_text")
    add("text: an R244 pending clear loses its restore hint", '      put(t, " - press Restore Original (armed)");', '      put(t, "");', "FB-B2 text: save_slot_refusal_text SLOT_R244 OBL_PENDING_CLEAR")
    add("text: the stuck lock shows milliseconds", '      put(t, " s (possible leak); a reboot may be required");', '      put(t, " ms (possible leak); a reboot may be required");', "FB-B2 text: save_slot_refusal_text SLOT_BUS stuck")
    add("text: the IDLE timeout read failure loses its suffix", 'put(t, "inverter bus stayed busy for 7 s; profile unchanged; review again");',
        'put(t, "inverter bus stayed busy for 7 s");', "FB-B2 text: save_read_fail_text")
    add("text: the read failure detail is not retargeted (the REVIEW prefix leaks)", "  const size_t skip = sizeof(ecco_fbcap::NOT_COMPLETED_PREFIX) - 1;\n  for (size_t i = skip;",
        "  const size_t skip = 0;\n  for (size_t i = skip;", "FB-B2 text: save_read_fail_text")
    add("text: the L2 refusal keeps the REVIEW heading", "  const size_t skip = 25;  // \"CANDIDATE NOT SAVEABLE - \"", "  const size_t skip = 0;  // \"CANDIDATE NOT SAVEABLE - \"", "FB-B2 text: save_l2_text")
    add("text: the changed-since-review text drops the reviewed value", '  put(t, ": reviewed ");\n  put_u(t, k >= 0 ? candidate[(size_t) k] : (uint16_t) 0);',
        '  put(t, ": reviewed ");\n  put_u(t, k >= 0 ? pass2[(size_t) k] : (uint16_t) 0);', "FB-B2 text: save_changed_since_review_text")
    add("text: the class refusal for UNREADABLE loses its why", '    put(t, ecco_fbcap::why_name(why));', '    put(t, "-");', "FB-B2 text: save_class_text cls 0")
    add("log: the forensic part 1 prints the first half again", "  for (size_t i = (size_t) part * 48; i < (size_t) part * 48 + 48; i++)", "  for (size_t i = 0; i < 48; i++)", "FB-B2 text: replace_corrupt_log_text")
    add("log: the wrong-size forensic line loses its length", '    put(t, "REPLACE CORRUPT discards a stored profile of the wrong size, stored length ");\n    put_u(t, stored_len);',
        '    put(t, "REPLACE CORRUPT discards a stored profile of the wrong size, stored length ");\n    put_u(t, 0u);', "FB-B2 text: replace_corrupt_log_text")

    # ---- F2: the masked echo of an unsupported action ---------------------------------------------------------------------------
    def hz(t, tail=""):
        return f"FB-B2 text: unsupported_action_text '{lab(t)}'{tail}"
    _put = "    put_char(t, echo_masked(s, m, i) ? '?' : echo_byte(s, i));"
    add("echo F2: the mask is removed", _put, "    put_char(t, echo_byte(s, i));", hz("failed"))
    add("echo F2: the mask is case-sensitive (lower-case words only)", "    if (echo_fold(echo_byte(s, i + k)) != lit[k])", "    if (echo_byte(s, i + k) != lit[k])", hz("FAILED"))
    add("echo F2: the mask is applied after the truncation (a cut occurrence stays visible)",
        "  const size_t m = n < ECHO_MAX + ECHO_LOOK ? n : ECHO_MAX + ECHO_LOOK;  // the bytes examined",
        "  const size_t m = n < ECHO_MAX ? n : ECHO_MAX;  // the bytes examined", hz("x" * 21 + "failed"))
    add("echo F2: the mask looks only 3 bytes past the cut", "  const size_t m = n < ECHO_MAX + ECHO_LOOK ? n : ECHO_MAX + ECHO_LOOK;  // the bytes examined",
        "  const size_t m = n < ECHO_MAX + 3 ? n : ECHO_MAX + 3;  // the bytes examined", hz("x" * 23 + "deferred"))
    add("echo F2: 'fail' is not masked", '    if ((j + 4 > i && echo_word_at(s, m, j, "fail")) || (j + 5 > i && echo_word_at(s, m, j, "defer")))',
        '    if ((j + 5 > i && echo_word_at(s, m, j, "defer")))', hz("failed"))
    add("echo F2: 'defer' is not masked", '    if ((j + 4 > i && echo_word_at(s, m, j, "fail")) || (j + 5 > i && echo_word_at(s, m, j, "defer")))',
        '    if ((j + 4 > i && echo_word_at(s, m, j, "fail")))', hz("deferred"))
    add("echo F2: an occurrence starting beyond byte 12 is not masked", "  for (size_t j = i >= ECHO_LOOK ? i - ECHO_LOOK : 0; j <= i; j++) {",
        "  for (size_t j = i >= ECHO_LOOK ? i - ECHO_LOOK : 0; j <= i && j < 12; j++) {", hz("x" * 20 + "failed"))
    add("echo F2: the back-scan misses the last letter of 'defer'", "  for (size_t j = i >= ECHO_LOOK ? i - ECHO_LOOK : 0; j <= i; j++) {",
        "  for (size_t j = i >= ECHO_LOOK ? i - ECHO_LOOK + 1 : 0; j <= i; j++) {", hz("deferred"))
    add("echo F2: the masked letters are dropped, not replaced by '?'", _put, "    if (!echo_masked(s, m, i))\n      put_char(t, echo_byte(s, i));", hz("failed"))
    add("echo F2: a '?' is not published for a non-alphanumeric byte", "constexpr char echo_byte(const char *s, size_t i) { return echo_char_ok(s[i]) ? s[i] : '?'; }",
        "constexpr char echo_byte(const char *s, size_t i) { return echo_char_ok(s[i]) ? s[i] : '_'; }", hz("fa il"))
    add("echo F2: the NUL-terminated overload does not look past the cut",
        "constexpr TextBuf unsupported_action_text(const char *action) { return unsupported_action_text(action, bounded_len(action, ECHO_MAX + ECHO_LOOK)); }",
        "constexpr TextBuf unsupported_action_text(const char *action) { return unsupported_action_text(action, bounded_len(action, ECHO_MAX)); }",
        hz("x" * 23 + "deferred", " (NUL-terminated)"))
    add("echo F2: the 2-argument put_sanitised does not look past the cut",
        "constexpr void put_sanitised(TextBuf &t, const char *s) { put_sanitised(t, s, bounded_len(s, ECHO_MAX + ECHO_LOOK)); }",
        "constexpr void put_sanitised(TextBuf &t, const char *s) { put_sanitised(t, s, bounded_len(s, ECHO_MAX)); }",
        f"FB-B2 text: put_sanitised '{lab('x' * 23 + 'deferred')}' (NUL-terminated)")
    add("echo F2: ECHO_LOOK is 3", "constexpr size_t ECHO_LOOK = 4;", "constexpr size_t ECHO_LOOK = 3;", "FB-B2 value: constant ECHO_LOOK")
    add("echo F2: echo_fold does not fold upper case", "constexpr char echo_fold(char c) { return (c >= 'A' && c <= 'Z') ? (char) (c + ('a' - 'A')) : c; }",
        "constexpr char echo_fold(char c) { return c; }", "FB-B2 value: echo_fold byte 65")

    # ---- SEM-1: ids / bindings that differ only in the high or only in the low 32 bits, the writes fingerprint -------------------
    add("G6 compares only the low 32 bits of the id", "if (parse_hex16(target_id, target_len) != in.cand_id)  // G6",
        "if ((uint32_t) parse_hex16(target_id, target_len) != (uint32_t) in.cand_id)  // G6", GC_SG)
    add("G6 compares only the high 32 bits of the id", "if (parse_hex16(target_id, target_len) != in.cand_id)  // G6",
        "if ((parse_hex16(target_id, target_len) >> 32) != (in.cand_id >> 32))  // G6", GC_SG)
    add("I9 compares only the low 32 bits of the binding", "if (in.p_load != ecco_fallback::LOAD_OK || in.p.binding != id)  // I9",
        "if (in.p_load != ecco_fallback::LOAD_OK || (uint32_t) in.p.binding != (uint32_t) id)  // I9", GC_IG)
    add("I9 compares only the high 32 bits of the binding", "if (in.p_load != ecco_fallback::LOAD_OK || in.p.binding != id)  // I9",
        "if (in.p_load != ecco_fallback::LOAD_OK || (in.p.binding >> 32) != (id >> 32))  // I9", GC_IG)
    _ib = "  if (in.p_load != ecco_fallback::LOAD_OK || in.p.binding != in.target_id)\n    return plan_refuse(r, PLAN_BINDING_CHANGED, invalidate_changed_text());"
    add("invalidate plan compares only the low 32 bits of the named binding", _ib,
        "  if (in.p_load != ecco_fallback::LOAD_OK || (uint32_t) in.p.binding != (uint32_t) in.target_id)\n    return plan_refuse(r, PLAN_BINDING_CHANGED, invalidate_changed_text());", GC_IP)
    add("invalidate plan compares only the high 32 bits of the named binding", _ib,
        "  if (in.p_load != ecco_fallback::LOAD_OK || (in.p.binding >> 32) != (in.target_id >> 32))\n    return plan_refuse(r, PLAN_BINDING_CHANGED, invalidate_changed_text());", GC_IP)
    _pc2 = "  if (in.cls != in.cand_prior_class || f.generation != in.cand_prior_gen || f.binding != in.cand_prior_binding)\n"
    add("plan compares only the low 32 bits of the candidate's prior binding", _pc2,
        "  if (in.cls != in.cand_prior_class || f.generation != in.cand_prior_gen || (uint32_t) f.binding != (uint32_t) in.cand_prior_binding)\n", GC_SP)
    add("plan compares only the high 32 bits of the candidate's prior binding", _pc2,
        "  if (in.cls != in.cand_prior_class || f.generation != in.cand_prior_gen || (f.binding >> 32) != (in.cand_prior_binding >> 32))\n", GC_SP)
    add("G13 is a greater-than compare", "if (in.writes_fp_now != in.cand_writes_fp)  // G13", "if (in.writes_fp_now > in.cand_writes_fp)  // G13", GC_SG)
    add("G13 is a signed difference", "if (in.writes_fp_now != in.cand_writes_fp)  // G13", "if ((int32_t) (in.writes_fp_now - in.cand_writes_fp) > 0)  // G13", GC_SG)
    add("G13 compares only the low 16 bits", "if (in.writes_fp_now != in.cand_writes_fp)  // G13", "if ((uint16_t) in.writes_fp_now != (uint16_t) in.cand_writes_fp)  // G13", GC_SG)

    # ---- SEM-2: only a VALID witness' high-water counts ------------------------------------------------------------------------------
    _wcl = "  const uint8_t wc = ecco_fbdurable::classify_witness(in.w_load, in.w);\n"
    _pit = ("  if (!ecco_fallback::profile_invalidate_permitted(in.p) ||\n      !ecco_fbdurable::invalidate_generation_permitted(in.p.generation, wc, in.w.hw_generation, "
            "in.seen_hw_gen))\n    return plan_refuse(")
    _git = ("  if (!ecco_fallback::profile_invalidate_permitted(in.p) ||\n      !ecco_fbdurable::invalidate_generation_permitted(in.p.generation, wc, in.w.hw_generation, "
            "in.seen_hw_gen))  // I10")
    add("invalidate plan: every witness counts as VALID (a corrupt witness' hw raises the high-water)", _wcl + _pit,
        "  const uint8_t wc = (uint8_t) ecco_fbdurable::W_VALID;\n" + _pit, GC_IP)
    add("invalidate plan: no witness' high-water ever counts", _wcl + _pit, "  const uint8_t wc = (uint8_t) ecco_fbdurable::W_ABSENT;\n" + _pit, GC_IP)
    add("I10: every witness counts as VALID", _wcl + _git, "  const uint8_t wc = (uint8_t) ecco_fbdurable::W_VALID;\n" + _git, GC_IG)
    add("I10: no witness' high-water ever counts", _wcl + _git, "  const uint8_t wc = (uint8_t) ecco_fbdurable::W_ABSENT;\n" + _git, GC_IG)
    _wb = "  const uint8_t wc = ecco_fbdurable::classify_witness(in.w_load, in.w);\n  const uint32_t base ="
    add("plan: every witness counts as VALID in the generation base", _wb, "  const uint8_t wc = (uint8_t) ecco_fbdurable::W_VALID;\n  const uint32_t base =", GC_SP)
    add("plan: no witness' high-water ever counts in the generation base", _wb, "  const uint8_t wc = (uint8_t) ecco_fbdurable::W_ABSENT;\n  const uint32_t base =", GC_SP)

    # ---- SEM-3: the lease owner of the BUS refusal ----------------------------------------------------------------------------------------
    add("save_gate_refusal_text names the plain bus owner, not the lease",
        "  const char *owner = ecco_fbcap::bus_owner_text_with_leases(g.bus, gr.fp, gr.dump);", "  const char *owner = ecco_fbcap::bus_owner_text(g.bus);",
        "FB-B2 text: save_gate_refusal_text of gate_decide over scenario 26")
    add("save_gate_refusal_text never names Dump to Grid for a lease", "  const char *owner = ecco_fbcap::bus_owner_text_with_leases(g.bus, gr.fp, gr.dump);",
        "  const char *owner = ecco_fbcap::bus_owner_text_with_leases(g.bus, gr.fp, GateResult{}.dump);", "FB-B2 text: save_gate_refusal_text of gate_decide over scenario 27")

    # ---- SEM-4: a default flipped to its fail-open value is a compile error naming the field ----------------------------------------------------
    def decl(struct: str, fld: str) -> str:
        """The exact header text (whole lines, with their newlines) declaring `struct.fld = <default>`: the declaration line alone when it is unique in the header,
        else with the previous line, else with the next line, else with both (two structs declare an identical `bool unconfirmed = true;`)."""
        htext = read_header()
        body = re.search(rf"^struct {struct} \{{(.*?)^\}};", htext, re.S | re.M).group(1)
        lines = body.split("\n")
        idx = [i for i, ln in enumerate(lines) if re.match(rf"\s+[\w:<> ]+? {fld} = ", ln)]
        assert len(idx) == 1, (struct, fld, idx)
        i = idx[0]
        for lo, hi in ((0, 0), (1, 0), (0, 1), (1, 1)):
            chunk = "\n".join(lines[i - lo:i + hi + 1]) + "\n"
            if htext.count(chunk) == 1:
                return chunk
        raise AssertionError((struct, fld, "no unique anchor"))

    for struct, fld, value in (("SaveGateInputs", "arm_was_on", "true"), ("SaveGateInputs", "cand_valid", "true"), ("SaveGateInputs", "cand_saveable", "true"),
                               ("SaveGateInputs", "hb_ok", "true"), ("SaveGateInputs", "time_trusted", "true"), ("SaveGateInputs", "boot_loaded", "true"),
                               ("SaveGateInputs", "unconfirmed", "false"), ("SaveGateInputs", "read_anomaly", "0"),
                               ("InvalidateGateInputs", "arm_was_on", "true"), ("InvalidateGateInputs", "boot_loaded", "true"),
                               ("InvalidateGateInputs", "unconfirmed", "false"), ("InvalidateGateInputs", "read_anomaly", "0"),
                               ("InvalidateGateInputs", "seen_hw_gen", "0u"), ("InvalidateGateInputs", "tx_buffer_empty", "true"),
                               ("InvalidateGateInputs", "tx_blocked", "false"), ("InvalidateGateInputs", "fbs_slot", "ecco_fbdurable::FBS_CLEAR_ABSENT"),
                               ("InvalidateGateInputs", "cls", "ecco_fbdurable::EPC_VALID"), ("SavePlanInputs", "seen_hw_gen", "0u"),
                               ("SavePlanInputs", "read_anomaly", "0"), ("SavePlanInputs", "unconfirmed", "false"), ("SavePlanInputs", "captured_epoch", "1u"),
                               ("InvalidatePlanInputs", "seen_hw_gen", "0u"), ("InvalidatePlanInputs", "unconfirmed", "false"),
                               ("InvalidatePlanInputs", "read_anomaly", "0"), ("InvalidatePlanInputs", "cls", "ecco_fbdurable::EPC_VALID")):
        old = decl(struct, fld)
        new = re.sub(rf"({fld} = )[^;]+;", rf"\g<1>{value};", old, count=1)
        add(f"default: {struct}.{fld} is {value} (fail-open)", old, new, f"FB-B2 default: {struct}.{fld} refuses")

    # ---- SEM-5: the INVALIDATE gate bodies of S2 Part B 4.2 ---------------------------------------------------------------------------------
    add("text: the INVALIDATE not-loaded refusal loses its (starting up)", 'invalidate_refused("durable state not loaded yet (starting up)")',
        'invalidate_refused("durable state not loaded yet")', "FB-B2 text: invalidate_not_loaded_text")
    add("text: the INVALIDATE read-anomaly refusal says 're-derive it first'", 'invalidate_refused("stored profile read anomaly this boot; reboot to re-derive first")',
        'invalidate_refused("stored profile read anomaly this boot; reboot to re-derive it first")', "FB-B2 text: invalidate_anomaly_text")

    # ---- SEM-6: the log line ----------------------------------------------------------------------------------------------------------------------
    add("log: the operation is the capture header's short name (RC / INV)", "  put(t, txn_op_name(op));", "  put(t, ecco_fbcap::op_name(op));", "FB-B2 text: txn_log_text op 3")
    add("log: total_us is printed as tot", '  put(t, " total_us=");', '  put(t, " tot=");', "FB-B2 text: txn_log_text op 1")
    add("log: INVALIDATE is abbreviated INV", '         : op == ecco_fbdurable::PROV_OP_INVALIDATE      ? "INVALIDATE"', '         : op == ecco_fbdurable::PROV_OP_INVALIDATE      ? "INV"',
        "FB-B2 name: txn_op_name 2")
    add("log: REPLACE_CORRUPT is abbreviated RC", '         : op == ecco_fbdurable::PROV_OP_REPLACE_CORRUPT ? "REPLACE_CORRUPT"', '         : op == ecco_fbdurable::PROV_OP_REPLACE_CORRUPT ? "RC"',
        "FB-B2 name: txn_op_name 3")
    add("log: an unknown operation is named SAVE", '                                                         : "-";\n}\nconstexpr const char *txn_name(',
        '                                                         : "SAVE";\n}\nconstexpr const char *txn_name(', "FB-B2 name: txn_op_name 0")
    add("log: the per-key us fields come back (213 characters at the widest values: over the TextBuf)",
        '  put(t, key_name(r.w.outcome));\n  put(t, " p:err=");', '  put(t, key_name(r.w.outcome));\n  put(t, " us=");\n  put_u(t, r.w.us);\n  put(t, " p:err=");',
        "FB-B2 value: length of the longest txn_outcome_text / txn_log_text")
    return M


def section_negative(tc: Toolchain):
    print("[5] negative controls: the static_asserts are really evaluated (every mutant must be a REAL compile rejection)")
    text = read_header()
    inc = tc.stage("negative")
    r = tc.compile(inc, '#include "ecco_fallback_save.h"\nstatic_assert(ecco_fbsave::arm_expired(120000u, 0u) == false, "negative control: a false golden");\n')
    check("a deliberately WRONG golden (an arm expired at 120000 ms is not expired) fails to compile with its message",
          r.returncode != 0 and "static assertion failed" in r.stderr and "negative control: a false golden" in r.stderr, r.stderr[-500:])
    r = tc.compile(inc, '#include "ecco_fallback_save.h"\nint main() { return ecco_fbsave::action_token(3.5, "x") == 0; }\n')
    check("a TYPE error (a double passed as a string) is rejected as an ordinary compile error, not a static_assert",
          r.returncode != 0 and "error:" in r.stderr and "static assertion" not in r.stderr, r.stderr[-400:])
    r = tc.compile(inc, '#include "ecco_fallback_save.h"\nint main() { ecco_fbsave::SaveGateInputs s; s.no_such_input = true; return 0; }\n')
    check("a misspelled POD field is rejected", r.returncode != 0 and "no_such_input" in r.stderr)
    r = tc.compile(inc, '#include "ecco_fallback_save.h"\nstatic_assert(ecco_fbsave::save_gate_decide(ecco_fbsave::SaveGateInputs{}, "SAVE", 4, "", 0, "", 0, ecco_fbcap::GateInputs{}).code == ecco_fbsave::SG_ACCEPT, "negative control: the default inputs accept");\n')
    check("a VIOLATED static_assert in a client TU fails with its own message: the fail-closed default SAVE gate inputs never accept",
          r.returncode != 0 and "negative control: the default inputs accept" in r.stderr)
    r = tc.compile(inc, '#include "ecco_fallback_save.h"\nstatic_assert(ecco_fbsave::save_gate_decide(ecco_fbsave::SaveGateInputs{}, "SAVE", 4, "", 0, "", 0, ecco_fbcap::GateInputs{}).code != ecco_fbsave::SG_ACCEPT, "ok");\nint main() { return 0; }\n')
    check("...while the true form of the same assertion compiles (the control is specific)", r.returncode == 0, r.stderr[-300:])

    muts = mutants()
    problems = [f"{label}: pattern found {text.count(old)}x" for label, old, new, msg in muts if text.count(old) != 1]
    check(f"all {len(muts)} mutation patterns occur exactly once in the header", not problems, "; ".join(problems[:6]))
    check("every mutant actually changes the header", all(old != new for _l, old, new, _m in muts))

    def one(item):
        label, old, new, msg = item
        if text.count(old) != 1:
            return label, None, msg
        mutated = text.replace(old, new, 1)
        d = tc.stage("mut_" + re.sub(r"\W+", "_", label)[:50] + f"_{abs(hash(label)) % 10000}", mutated)
        r = tc.compile(d, '#include "ecco_fallback_save.h"\nint main() { return 0; }\n')
        return label, r, msg

    with ThreadPoolExecutor(max_workers=max(1, min(8, os.cpu_count() or 1))) as pool:
        results = list(pool.map(one, muts))
    killed = 0
    for label, r, msg in results:
        ok = r is not None and r.returncode != 0 and ("static assertion failed" in r.stderr or "error:" in r.stderr) and msg in r.stderr
        killed += 1 if ok else 0
        check(f"mutant [{label}] is rejected by a static_assert naming '{msg}'", ok,
              "compiled" if r is not None and r.returncode == 0 else (r.stderr[-500:] if r is not None else "pattern missing"))
    print(f"  info  mutants: {len(muts)} total, {killed} killed")


# ===========================================================================================================
# Header discipline
# ===========================================================================================================
def strip_comments(text: str) -> str:
    return re.sub(r"//[^\n]*", "", re.sub(r"/\*.*?\*/", " ", text, flags=re.S))


def section_discipline():
    print("[6] header discipline (the pins the other fallback headers carry, plus the FB-B2 ones)")
    sys.path.insert(0, str(THIS.parent))
    import _tag_inventory as ti  # noqa: E402
    text = read_header()
    code = strip_comments(text)
    check("#pragma once is the first line", text.replace("\r\n", "\n").startswith("#pragma once\n"))
    includes = re.findall(r'#\s*include\s*([<"][^>"]+[>"])', text)
    check("it includes only <array>, <cstddef>, <cstdint>, <type_traits>, the FB-B0 model header and the FB-B1 capture header",
          includes == ["<array>", "<cstddef>", "<cstdint>", "<type_traits>", '"ecco_fallback_durable_model.h"', '"ecco_fallback_capture.h"'], str(includes))
    banned = [("id( (the ESPHome accessor)", r"\bid\("), ("nvs_", r"nvs_"), ("modbus", r"(?i)modbus"), ("supervision", r"(?i)supervision"),
              ("self-partial", r"(?i)self_?partial"), ("start-journal", r"(?i)start_?journal"), ("an ESPHome include", r'#\s*include\s*["<]esphome'),
              ("App.", r"\bApp\."), ("commit_record", r"commit_record"), ("load_record", r"load_record"), ("make_preference", r"make_preference"),
              ("global_preferences", r"global_preferences"), ("esphome::", r"esphome::"), ("ESP_LOG", r"ESP_LOG"), ("millis(", r"\bmillis\s*\("),
              ("delay(", r"\bdelay\s*\("), ("uart", r"(?i)\buart"), ("random_uint32", r"random_uint32"), ("ntp_", r"(?i)\bntp_"),
              ("snprintf / printf / sprintf", r"\b(?:snprintf|printf|sprintf|vsnprintf)\b"), ("std::string / <string>", r"std::string|<string>"),
              ("the writer call: commit_transition", r"commit_transition"), ("write_one_", r"write_one_"), ("WriteTarget", r"WriteTarget"),
              ("s_write_latched", r"s_write_latched"), ("note_committed", r"note_committed"), ("mirror_after", r"mirror_after"), ("seal_provision", r"seal_provision"),
              ("a Save / arm entity name", r"fallback_profile_arm|fallback_profile_execute|save_unconfirmed|exec_action"),
              ("a bus-layer include", r"#\s*include\s*[<\"]modbus")]
    hits = [label for label, pat in banned if re.search(pat, text)]
    check("the header (comments included) names none of: id(, nvs_, the bus layer, supervision, the journal / partial classifiers, an ESPHome include, App., "
          "commit_record, load_record, make_preference, global_preferences, esphome::, ESP_LOG, millis(, delay(, uart, random_uint32, the clock globals, printf, "
          "std::string, the writer call (commit_transition, write_one_, WriteTarget, s_write_latched, note_committed, mirror_after), the arm / execute / "
          "save_unconfirmed / exec_action names", not hits, str(hits))
    check("exactly one namespace, ecco_fbsave, and no anonymous or nested namespace",
          re.findall(r"^\s*namespace\s*(\w*)\s*\{", code, re.M) == ["ecco_fbsave"] and "}  // namespace ecco_fbsave" in text)
    ns_vars = re.findall(r"^(?!static_assert|struct|enum|namespace|using|template|\}|#|\s)(\S[^(\n;]*?)\s(\w+)(?:\[[^\]]*\])?(?:\[\])? =", code, re.M)
    check("every namespace-scope object is constexpr (no static init, no mutable state)",
          bool(ns_vars) and all(q.startswith("constexpr") for q, _n in ns_vars) and not re.search(r"^\s*(?:static|extern|inline)\s+(?!constexpr)", code, re.M),
          str([n for q, n in ns_vars if not q.startswith("constexpr")]))
    fn_defs = re.findall(r"^(?:template<[^>]*> )?([a-zA-Z_][\w:<>, *&]*?) (\w+)\([^;{]*\) \{", code, re.M)
    non_constexpr = [n for q, n in fn_defs if "constexpr" not in q and n not in ("main",)]
    check("every function is constexpr", not non_constexpr, str(non_constexpr[:6]))
    check("the durable-tag inventory finds NO tag in the header (no name containing 'tag', no `ecco_<words>_v<N>` literal, no `*_TAG`)",
          ti.inventory(text) == [] and not ti.durable_literals(text), str(ti.inventory(text)))
    lit_hazard = re.compile("|".join([
        r"RECOVERY REQUIRED", r"OPERATOR DECISION REQUIRED", r"RESTORE BLOCKED", r"RECOVERY BLOCKED", r"\bFAILED\b", r"VERIFY ERROR",
        r"VERIFY TIMEOUT", r"VERIFY REFUSED", r"DEFERRED", r"ACCEPT REFUSED", r"Recovery Arm first", r"inverter writes? (?:are |is )?locked",
        r"deliberate recovery required", r"START FAILED", r"ACTIVATION (?:VERIFY|WRITE) FAILED", r"press End Free Power", r"retry restore",
        r"snapshot retained", r"^(?:RESTORING|STARTING|ACTIVATION VERIFY)"]), re.I)
    literals = re.findall(r'"((?:[^"\\\n]|\\.)*)"', code)
    bad = [s for s in literals if lit_hazard.search(s)]
    check(f"none of the header's {len(literals)} string literals (golden strings included) matches an Energy Actions card pattern, case-insensitively", not bad, str(bad[:3]))
    words = [s for s in literals if re.search(r"(?i)\b(failed|failure|deferred|supervision)\b", s)]
    check("no operator text uses the words failed / failure / deferred / supervision (any case)", not words, str(words[:3]))
    prod_raw = text[:text.index("// ---- GOLDENS-BEGIN ----")]
    prod_code = strip_comments(prod_raw)
    calls = [m.start() for m in re.finditer(r"\binvalidate_profile\(", prod_code)]
    head = prod_code[:calls[0]] if calls else ""
    inside = head[head.rindex("constexpr Plan plan_invalidate("):] if "constexpr Plan plan_invalidate(" in head else ""
    check("invalidate_profile( is called exactly once in the production code, only inside plan_invalidate and only AFTER profile_invalidate_permitted (BLK-51)",
          len(calls) == 1 and "profile_invalidate_permitted(in.p)" in inside)
    check("the production code calls the FB-B0 transition validator exactly in plan_save and plan_invalidate (PO14 + the writer's own rule), never the writer",
          len(re.findall(r"\bvalidate_transition\(", prod_code)) == 2 and "commit_transition_t" not in text)
    check("no function of the production code reads a clock or a global (every input is a parameter): no `now(`, no `millis`, no `id(`", not re.search(r"\bnow\s*\(|\bmillis\b", prod_code))
    structs = re.findall(r"^struct (\w+) \{(.*?)^\};", prod_raw, re.M | re.S)
    multi = [n for n, body in structs if re.search(r"^\s+[\w:<>, ]+?\s+\w+(?:\{\})?(?: = [^;,]+)?,\s*\w+", body, re.M) or "*" in re.sub(r"//[^\n]*", "", body)]
    check(f"every POD struct of the production code ({len(structs)}) has ONE field per line and no pointer field (the model suite parses the field lists)", not multi, str(multi))
    check("the DEFAULTS note says the defaults are fail-closed and names the two inherited permissive exceptions",
          "DEFAULTS ARE FAIL-CLOSED" in text and "BusInputs" in text[:text.index("namespace ecco_fbsave")] and "permissive" in text[:text.index("namespace ecco_fbsave")])
    check("the top comment names the mirror and every entry point family",
          "registry/fallback_save.py" in text[:text.index("namespace ecco_fbsave")] and all(
              n in text[:text.index("namespace ecco_fbsave")] for n in ("save_gate_decide", "plan_save", "plan_invalidate", "final_gate_decide", "txn_outcome_text", "arm_expired")))


# ===========================================================================================================
def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] == "--emit-goldens":
        out = emit_block()
        if len(sys.argv) > 2:
            Path(sys.argv[2]).write_text(out, encoding="utf-8", newline="\n")
            print(f"wrote {len(GOLDENS)} goldens to {sys.argv[2]}")
        else:
            sys.stdout.write(out)
        return 0
    cxx = find_compiler()
    check("a C++ compiler is available (the host compile never silently skips)", cxx is not None, "set ECCO_CXX or install g++")
    if cxx is None:
        print("\nFAILED: no C++ compiler found")
        return 1
    tc = Toolchain(cxx)
    try:
        section_compiler(tc)
        section_compile(tc)
        section_parity()
        section_random(tc)
        section_negative(tc)
        section_discipline()
    finally:
        shutil.rmtree(tc.tmp, ignore_errors=True)
    print("")
    if FAILURES:
        print(f"FAILED: {len(FAILURES)} check(s)")
        for f in FAILURES:
            print(f"  - {f}")
        return 1
    print("All FB-B2 save-header host-compile checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
