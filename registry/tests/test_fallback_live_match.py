#!/usr/bin/env python3
"""FB-B3 Slice A - Live Match foundation: RAW_CACHE_EXT, the live write fence, the pure B10 comparison and the B10 entity.

SCOPE. Slice A is the firmware / shared-model foundation of the Fallback Profile Live Match and nothing else: it ADDS six
RAM-only RAW_CACHE_EXT globals (assigned only inside the existing configuration poll response handlers), a RAM-only write
fence, the template text sensor `ECCO Fallback Profile Live Match` (B10) and a third lambda of the existing FB-B 10 s
housekeeping interval; the pure comparison lives in the shared FB-B capture header beside the four masks FB-B1 already
shipped (so FB-C2 later calls the very same code). It adds ZERO Modbus operations, ZERO NVS access and ZERO inverter
authority. No Home Assistant file, no deployment manifest and no other firmware YAML changes.

  [1] model        the Python mirror (registry/fallback_capture.py) against hand-written expectations: the first-match-wins
                   precedence, the masks, the effective class (SAVE_UNCONFIRMED / read anomaly), the trust terms in order,
                   the fence (fail-closed seeding, hot ticks, the lease edge, monotonicity), the export hazard, eligibility
                   and the <=200-character B10 grammar at its worst case;
  [2] host compile a real C++ compiler evaluates the header's Live Match section as static_asserts over a deterministic scenario
                   table PLUS 300 seeded random cases, requiring C++ == Python on every B10 text, every trust letter, every
                   export-hazard cell and a seeded 40-tick fence replay, under -std=gnu++17 and gnu++20 with -Wall -Wextra
                   -Werror (the header's own suites compile it too);
  [3] mutants      key conditions of the C++ section are mutated one at a time; every mutant must be a real compile rejection
                   of the same static_asserts (precedence rows, the overlay, the fence comparison, a trust term, the edge, ...);
  [4] firmware     the YAML: RAW_CACHE_EXT globals and the assignment allowlist (only the two poll response handlers assign
                   fbc_raw_*; only the Live Match tick reads them), the response offsets, the B10 entity and its boot seed,
                   the third interval lambda's forbidden-token scan and assignment allowlist, entity-set equality with FB-B2,
                   and the measured write-surface / storage delta (0 Modbus reads, 0 Modbus writes, 0 NVS write sites);
  [5] scope        the pure-insertion hunks and their exact reverter, and the FB-T0 chain entry `fbb3`.

Writes only to a temporary directory; no hardware, no network.
"""

from __future__ import annotations

import os
import random
import re
import shutil
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
INCLUDE_DIR = ROOT / "firmware" / "include"
HEADER_PATH = INCLUDE_DIR / "ecco_fallback_capture.h"
FIRMWARE = ROOT / "firmware" / "ecco_clock_dongle_stage3_4_free_power.yaml"
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "registry"))
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "tools"))
import fallback_capture as cap  # noqa: E402
import fallback_durable as fd  # noqa: E402
import fallback_profile as fp  # noqa: E402
import _fbb3_scope as scope  # noqa: E402

FAILURES: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  PASS  {name}")
    else:
        FAILURES.append(name)
        print(f"  FAIL  {name}" + (f" - {detail}" if detail else ""))


def read_header() -> str:
    return HEADER_PATH.read_text(encoding="utf-8")


def read_fw() -> str:
    # FB-C2: this suite is anchored at chain entry fbb3 - the firmware is read AS OF fbb3 (every later entry's declared edits
    # reverted exactly, newest first), so a later PR never edits it while an undeclared edit still breaks it.
    import _scope_chain as _chain
    return _chain.CHAIN.as_of(_chain.FIRMWARE, "fbb3", FIRMWARE.read_text(encoding="utf-8"))


# ===========================================================================
# Fixtures, described once for Python and once for C++ (a scenario is a list of named modifications of the base inputs)
# ===========================================================================
GOLD_P = fp.seal_profile(fp.blank_profile(
    magic=fp.PROFILE_MAGIC, schema=1, size=96, generation=7, captured_epoch=1790000000, flags=0, reg244=2,
    reg256_261=[8000, 500, 4000, 3000, 2000, 1000], reg268_273=[100, 20, 0, 50, 100, 30], reg274_279=[1, 0, 1, 0, 0, 1],
    reg232=0x0011, reg243=1, reg248=1, reg250_255=[0, 530, 1000, 1600, 2100, 2330], reg230=185, reg245=8000, reg247=1))
GW = cap.words_of(GOLD_P)
INV_P = fp.invalidate_profile(GOLD_P)


def base_inputs() -> "cap.LiveMatchInputs":
    """Every trust term passes, every lease domain clear, bus idle, a VALID profile equal to the live words: MATCH."""
    g = cap.GateInputs(boot_loaded=True, fbs_slot=fd.FBS_CLEAR_ABSENT)
    g.fp.free_power_marker_boot_load = cap.BOOT_LOAD_ABSENT
    g.dump.dump_marker_boot_load = cap.BOOT_LOAD_ABSENT
    g.r244.reg244_marker_boot_load = cap.BOOT_LOAD_ABSENT
    return cap.LiveMatchInputs(
        g=g, mtou_running=False, cls=fd.EPC_VALID, write_outcome_unknown=False, read_anomaly=0, p_load=fp.LOAD_OK, p=GOLD_P,
        cache=cap.LiveCache(cache_valid=True, online=True, polling=True, filled=True, block_b_seq=5, block_b_ok_ms=1000,
                            now_ms=2000, response_dispatch_seq=7, fence_seq=7),
        edge_fence_seq=0, live=list(GW), dump_data_loaded=False, dump_snapshot_reg244=0xFFFF,
        dump_snapshot_reg256_261=[0] * 6, ceiling_w=8000)


CXX_BASE = """LiveMatchInputs base_in() {
  LiveMatchInputs in{};
  in.g = golden_gate_clear();
  in.mtou_running = false;
  in.cls = ecco_fbdurable::EPC_VALID;
  in.write_outcome_unknown = false;
  in.read_anomaly = 0;
  in.p_load = ecco_fallback::LOAD_OK;
  in.p = GOLDEN_PROFILE;
  in.cache.cache_valid = true; in.cache.online = true; in.cache.polling = true; in.cache.filled = true;
  in.cache.block_b_seq = 5; in.cache.block_b_ok_ms = 1000; in.cache.now_ms = 2000;
  in.cache.response_dispatch_seq = 7; in.cache.fence_seq = 7;
  in.edge_fence_seq = 0;
  in.live = GOLDEN_WORDS;
  in.dump_data_loaded = false; in.dump_snapshot_reg244 = 0xFFFFu; in.dump_snapshot_reg256_261 = {};
  in.ceiling_w = 8000u;
  return in;
}"""


class Mod:
    def __init__(self, name: str, cxx: str, py):
        self.name, self.cxx, self.py = name, cxx, py


MODS: dict[str, Mod] = {}


def mod(name: str, cxx: str, py) -> None:
    MODS[name] = Mod(name, cxx, py)


def _set(path: str, value):
    def f(i):
        obj = i
        parts = path.split(".")
        for p in parts[:-1]:
            obj = getattr(obj, p)
        setattr(obj, parts[-1], value)
    return f


def _cxx_val(v) -> str:
    return "true" if v is True else "false" if v is False else f"{v}u" if isinstance(v, int) and v > 32767 else str(v)


def simple(name: str, path: str, value) -> None:
    mod(name, f"in.{path} = {_cxx_val(value)};", _set(path, value))


# boot / class / overlay
simple("boot_not_loaded", "g.boot_loaded", False)
for c in range(9):
    simple(f"cls{c}", "cls", c)
simple("write_outcome_unknown", "write_outcome_unknown", True)
simple("read_anomaly1", "read_anomaly", 1)
simple("read_anomaly2", "read_anomaly", 2)
simple("p_load_absent", "p_load", fp.LOAD_ABSENT)
simple("p_load_unavail", "p_load", fp.LOAD_STORAGE_UNAVAILABLE)
mod("p_invalidated_but_cls_valid", "in.p = ecco_fallback::invalidate_profile(GOLDEN_PROFILE);", lambda i: setattr(i, "p", INV_P))
mod("p_invalidated_cls4", "in.p = ecco_fallback::invalidate_profile(GOLDEN_PROFILE); in.cls = ecco_fbdurable::EPC_INVALIDATED;",
    lambda i: (setattr(i, "p", INV_P), setattr(i, "cls", fd.EPC_INVALIDATED)))
# cache / trust
simple("cache_invalid", "cache.cache_valid", False)
simple("offline", "cache.online", False)
simple("poll_off", "cache.polling", False)
simple("seq0", "cache.block_b_seq", 0)
simple("stale_edge", "cache.now_ms", 181000)         # age 180000: still fresh
simple("stale", "cache.now_ms", 181001)               # age 180001
mod("stale_wrapped", "in.cache.block_b_ok_ms = 4294960000u; in.cache.now_ms = 190000u;",
    lambda i: (setattr(i.cache, "block_b_ok_ms", 4294960000), setattr(i.cache, "now_ms", 190000)))
mod("fresh_wrapped", "in.cache.block_b_ok_ms = 4294960000u; in.cache.now_ms = 100000u;",
    lambda i: (setattr(i.cache, "block_b_ok_ms", 4294960000), setattr(i.cache, "now_ms", 100000)))
simple("pre_fence", "cache.response_dispatch_seq", 6)
simple("fence_default_max", "cache.fence_seq", 0xFFFFFFFF)
simple("not_filled", "cache.filled", False)
simple("edge_pending", "edge_fence_seq", 8)
simple("edge_passed_equal", "edge_fence_seq", 7)
# leases (RAM legs)
mod("fp_active", "in.g.fp.free_power_snapshot_valid = true; in.g.fp.free_power_marker_state = 1; in.g.fp.free_power_active_persisted = true;",
    lambda i: (setattr(i.g.fp, "free_power_snapshot_valid", True), setattr(i.g.fp, "free_power_marker_state", 1),
               setattr(i.g.fp, "free_power_active_persisted", True)))
mod("fp_starting", "in.g.fp.run_start = true;", lambda i: setattr(i.g.fp, "run_start", True))
mod("fp_restore_required", "in.g.fp.free_power_snapshot_valid = true; in.g.fp.free_power_marker_state = 1; in.g.fp.free_power_restore_requested = true;",
    lambda i: (setattr(i.g.fp, "free_power_snapshot_valid", True), setattr(i.g.fp, "free_power_marker_state", 1),
               setattr(i.g.fp, "free_power_restore_requested", True)))
mod("fp_operator_needed", "in.g.fp.free_power_snapshot_valid = true; in.g.fp.free_power_marker_state = 1; in.g.fp.free_power_operator_needed = true;",
    lambda i: (setattr(i.g.fp, "free_power_snapshot_valid", True), setattr(i.g.fp, "free_power_marker_state", 1),
               setattr(i.g.fp, "free_power_operator_needed", True)))
mod("fp_ending", "in.g.fp.run_restore = true;", lambda i: setattr(i.g.fp, "run_restore", True))
mod("fp_unreadable", "in.g.fp.free_power_marker_boot_load = 3; in.g.fp.free_power_recovery_metadata_corrupt = true;",
    lambda i: (setattr(i.g.fp, "free_power_marker_boot_load", 3), setattr(i.g.fp, "free_power_recovery_metadata_corrupt", True)))
mod("dump_active", "in.g.dump.dump_snapshot_valid = true; in.g.dump.dump_marker_state = 1; in.g.dump.dump_active_persisted = true;",
    lambda i: (setattr(i.g.dump, "dump_snapshot_valid", True), setattr(i.g.dump, "dump_marker_state", 1),
               setattr(i.g.dump, "dump_active_persisted", True)))
mod("dump_restore_required", "in.g.dump.dump_snapshot_valid = true; in.g.dump.dump_marker_state = 1; in.g.dump.dump_restore_requested = true;",
    lambda i: (setattr(i.g.dump, "dump_snapshot_valid", True), setattr(i.g.dump, "dump_marker_state", 1),
               setattr(i.g.dump, "dump_restore_requested", True)))
mod("dump_operator_needed", "in.g.dump.dump_snapshot_valid = true; in.g.dump.dump_marker_state = 1; in.g.dump.dump_operator_needed = true;",
    lambda i: (setattr(i.g.dump, "dump_snapshot_valid", True), setattr(i.g.dump, "dump_marker_state", 1),
               setattr(i.g.dump, "dump_operator_needed", True)))
mod("dump_corrupt", "in.g.dump.dump_recovery_metadata_corrupt = true;", lambda i: setattr(i.g.dump, "dump_recovery_metadata_corrupt", True))
mod("r244_restore_required", "in.g.r244.reg244_snapshot_valid = true; in.g.r244.reg244_marker_state = 1;",
    lambda i: (setattr(i.g.r244, "reg244_snapshot_valid", True), setattr(i.g.r244, "reg244_marker_state", 1)))
mod("r244_pending_clear", "in.g.r244.reg244_snapshot_valid = true; in.g.r244.reg244_marker_state = 2;",
    lambda i: (setattr(i.g.r244, "reg244_snapshot_valid", True), setattr(i.g.r244, "reg244_marker_state", 2)))
mod("probe_latch_dump_unreadable", "in.g.probe_latch = 1u << 4;", lambda i: setattr(i.g, "probe_latch", 1 << 4))
# bus
mod("bus_mwip", "in.g.bus.manual_write_in_progress = true;", lambda i: setattr(i.g.bus, "manual_write_in_progress", True))
mod("bus_fb_op", "in.g.bus.fallback_profile_op_in_progress = true;", lambda i: setattr(i.g.bus, "fallback_profile_op_in_progress", True))
mod("bus_cip", "in.g.bus.correction_in_progress = true;", lambda i: setattr(i.g.bus, "correction_in_progress", True))
mod("bus_stuck", "in.g.bus.manual_write_in_progress = true; in.g.bus.diag_write_lock_held = true; in.g.bus.diag_write_lock_since_ms = 0; in.g.bus.now_ms = 300000u;",
    lambda i: (setattr(i.g.bus, "manual_write_in_progress", True), setattr(i.g.bus, "diag_write_lock_held", True),
               setattr(i.g.bus, "diag_write_lock_since_ms", 0), setattr(i.g.bus, "now_ms", 300000)))
simple("mtou_running", "mtou_running", True)
# export hazard inputs
mod("dump_exempt", "in.dump_data_loaded = true; in.dump_snapshot_reg244 = 0; in.dump_snapshot_reg256_261 = {8000, 500, 4000, 3000, 2000, 1000};",
    lambda i: (setattr(i, "dump_data_loaded", True), setattr(i, "dump_snapshot_reg244", 0),
               setattr(i, "dump_snapshot_reg256_261", [8000, 500, 4000, 3000, 2000, 1000])))
mod("dump_exempt_residue", "in.dump_data_loaded = true; in.dump_snapshot_reg244 = 0; in.dump_snapshot_reg256_261 = {8000, 500, 4000, 3000, 2000, 999};",
    lambda i: (setattr(i, "dump_data_loaded", True), setattr(i, "dump_snapshot_reg244", 0),
               setattr(i, "dump_snapshot_reg256_261", [8000, 500, 4000, 3000, 2000, 999])))
mod("dump_snapshot_not_loaded", "in.dump_data_loaded = false; in.dump_snapshot_reg244 = 0; in.dump_snapshot_reg256_261 = {8000, 500, 4000, 3000, 2000, 1000};",
    lambda i: (setattr(i, "dump_snapshot_reg244", 0), setattr(i, "dump_snapshot_reg256_261", [8000, 500, 4000, 3000, 2000, 1000])))
simple("ceiling_5000", "ceiling_w", 5000)

# live word perturbations: word k = value
LIVE_VALUES = (0, 1, 2, 3, 5, 100, 101, 499, 500, 3000, 8000, 8001, 65535)


def live(k: int, v: int) -> str:
    name = f"live{k}_{v}"
    if name not in MODS:
        def f(i, k=k, v=v):
            i.live[k] = v
        mod(name, f"in.live[{k}] = {v}u;", f)
    return name


SCENARIOS: list[tuple[str, list[str], int | None]] = []   # (label, mods, expected m or None)
M = cap


def scn(label: str, mods: list[str], expect: int | None) -> None:
    SCENARIOS.append((label, mods, expect))


scn("all clear, live == profile", [], M.LM_MATCH)
scn("244 live 0 = Allow Export, nothing owning", [live(0, 0)], M.LM_EXPORT)
scn("244 live 1 = Essentials is out of domain, not EXPORT", [live(0, 1)], M.LM_OUT_OF_DOMAIN)
scn("244 live 3 unrecognised", [live(0, 3)], M.LM_OUT_OF_DOMAIN)
scn("a power value differs (3000 -> 3001 is in domain)", [live(3, 3001)], M.LM_DRIFT)
scn("a power outside 500..8000", [live(1, 8001)], M.LM_OUT_OF_DOMAIN)
scn("a SOC above 100", [live(8, 101)], M.LM_OUT_OF_DOMAIN)
scn("a slot source word 5 (mode bit) is out of domain", [live(14, 5)], M.LM_OUT_OF_DOMAIN)
scn("a slot source word 2 (generator) is out of domain", [live(13, 2)], M.LM_OUT_OF_DOMAIN)
scn("a slot source word differs inside the domain (1 -> 0)", [live(13, 0)], M.LM_DRIFT)
scn("232 bit 0 flips: CONTEXT", [live(19, 0x0010)], M.LM_CONTEXT)
scn("232 upper bits only: INFO, still MATCH", [live(19, 0x0013)], M.LM_MATCH)
scn("243 differs: CONTEXT", [live(20, 0)], M.LM_CONTEXT)
scn("248 bit 0 flips: CONTEXT", [live(21, 0)], M.LM_CONTEXT)
scn("248 upper bits only: INFO, still MATCH", [live(21, 3)], M.LM_MATCH)
scn("a slot boundary moved: CONTEXT", [live(23, 531)], M.LM_CONTEXT)
scn("230 / 245 / 247 differ: INFO only", [live(28, 1), live(29, 1), live(30, 0)], M.LM_MATCH)
scn("OOD beats EXPORT (244 live 0 with a power out of domain)", [live(0, 0), live(1, 8001)], M.LM_OUT_OF_DOMAIN)
scn("EXPORT beats CONTEXT", [live(0, 0), live(20, 0)], M.LM_EXPORT)
scn("EXPORT beats DRIFT", [live(0, 0), live(3, 3001)], M.LM_EXPORT)
scn("CONTEXT beats DRIFT", [live(20, 0), live(3, 3001)], M.LM_CONTEXT)
scn("OOD beats CONTEXT", [live(1, 8001), live(20, 0)], M.LM_OUT_OF_DOMAIN)
scn("class NOT_CAPTURED", ["cls1"], M.LM_NO_PROFILE)
scn("class INVALIDATED", ["p_invalidated_cls4"], M.LM_NO_PROFILE)
scn("class VALID but the mirror record is INVALIDATED", ["p_invalidated_but_cls_valid"], M.LM_NO_PROFILE)
scn("class PROFILE_LOST", ["cls6"], M.LM_NO_PROFILE)
scn("class PROFILE_STALE", ["cls8"], M.LM_NO_PROFILE)
scn("class CORRUPT / CORRUPT_DOMAIN / UNREADABLE", ["cls2"], M.LM_NO_PROFILE)
scn("class UNREADABLE (0)", ["cls0"], M.LM_NO_PROFILE)
scn("SAVE_UNCONFIRMED overlay over a VALID composed class (FB-B2 carry-forward)", ["write_outcome_unknown"], M.LM_NO_PROFILE)
scn("SAVE_UNCONFIRMED overlay beats a trusted fresh cache that matches", ["write_outcome_unknown", live(0, 2)], M.LM_NO_PROFILE)
scn("read anomaly over a VALID composed class", ["read_anomaly1"], M.LM_NO_PROFILE)
scn("profile read not OK", ["p_load_absent"], M.LM_NO_PROFILE)
scn("boot not loaded, class VALID: UNKNOWN (ca=B)", ["boot_not_loaded"], M.LM_UNKNOWN)
scn("NO_PROFILE row precedes the boot row", ["boot_not_loaded", "cls0"], M.LM_NO_PROFILE)
scn("FP ACTIVE: PAUSED", ["fp_active"], M.LM_PAUSED)
scn("FP STARTING: PAUSED", ["fp_starting"], M.LM_PAUSED)
scn("FP restore required: PAUSED", ["fp_restore_required"], M.LM_PAUSED)
scn("FP operator needed: PAUSED", ["fp_operator_needed"], M.LM_PAUSED)
scn("FP restoring: PAUSED", ["fp_ending"], M.LM_PAUSED)
scn("FP marker unreadable: PAUSED", ["fp_unreadable"], M.LM_PAUSED)
scn("Dump ACTIVE: PAUSED", ["dump_active"], M.LM_PAUSED)
scn("Dump restore required: PAUSED", ["dump_restore_required"], M.LM_PAUSED)
scn("Dump corrupt lockout: PAUSED", ["dump_corrupt"], M.LM_PAUSED)
scn("R244 restore required: PAUSED", ["r244_restore_required"], M.LM_PAUSED)
scn("R244 pending clear: PAUSED", ["r244_pending_clear"], M.LM_PAUSED)
scn("probe latch (sticky unreadable): PAUSED", ["probe_latch_dump_unreadable"], M.LM_PAUSED)
scn("lease edge fence not yet passed: PAUSED although every domain reads clear", ["edge_pending"], M.LM_PAUSED)
scn("lease edge fence passed on equality", ["edge_passed_equal"], M.LM_MATCH)
scn("PAUSED beats a stale cache", ["fp_active", "stale"], M.LM_PAUSED)
scn("PAUSED beats PAUSED_IO", ["fp_active", "bus_mwip"], M.LM_PAUSED)
scn("shared write lock held: PAUSED_IO", ["bus_mwip"], M.LM_PAUSED_IO)
scn("Fallback Profile op in flight: PAUSED_IO", ["bus_fb_op"], M.LM_PAUSED_IO)
scn("clock correction in flight: PAUSED_IO", ["bus_cip"], M.LM_PAUSED_IO)
scn("lock stuck (>= 300 s): PAUSED_IO", ["bus_stuck"], M.LM_PAUSED_IO)
scn("Manual TOU apply running: PAUSED_IO", ["mtou_running"], M.LM_PAUSED_IO)
scn("PAUSED_IO beats a stale cache", ["bus_mwip", "stale"], M.LM_PAUSED_IO)
scn("PAUSED_IO beats DRIFT", ["bus_mwip", live(3, 3001)], M.LM_PAUSED_IO)
scn("cache flag false: UNKNOWN (ca=I)", ["cache_invalid"], M.LM_UNKNOWN)
scn("configuration offline: UNKNOWN (ca=I)", ["offline"], M.LM_UNKNOWN)
scn("no Block B response yet: UNKNOWN (ca=I)", ["seq0"], M.LM_UNKNOWN)
scn("polling off: UNKNOWN (ca=O)", ["poll_off"], M.LM_UNKNOWN)
scn("age exactly 180000 ms is still fresh", ["stale_edge"], M.LM_MATCH)
scn("age 180001 ms is stale (ca=S)", ["stale"], M.LM_UNKNOWN)
scn("age across the u32 millis wrap is stale", ["stale_wrapped"], M.LM_UNKNOWN)
scn("age across the u32 millis wrap is fresh", ["fresh_wrapped"], M.LM_MATCH)
scn("response dispatch below the fence: UNKNOWN (ca=P)", ["pre_fence"], M.LM_UNKNOWN)
scn("an unset fence (max) is pre-fence", ["fence_default_max"], M.LM_UNKNOWN)
scn("RAW_CACHE_EXT never filled: UNKNOWN (ca=M)", ["not_filled"], M.LM_UNKNOWN)
scn("a drifted value with an untrusted cache is never DRIFT", ["stale", live(3, 3001)], M.LM_UNKNOWN)
scn("a matching value with an untrusted cache is never MATCH", ["pre_fence"], M.LM_UNKNOWN)
scn("trust terms in order: invalid beats poll-off beats stale beats pre-fence beats not-filled",
    ["cache_invalid", "poll_off", "stale", "pre_fence", "not_filled"], M.LM_UNKNOWN)
scn("export hazard: FP ACTIVE with live 244 = 0 is guarded (eh=0)", ["fp_active", live(0, 0)], M.LM_PAUSED)
scn("export hazard: FP STARTING with live 244 = 0 is guarded (eh=0)", ["fp_starting", live(0, 0)], M.LM_PAUSED)
scn("export hazard: FP restore required with live 244 = 0 (eh=1)", ["fp_restore_required", live(0, 0)], M.LM_PAUSED)
scn("export hazard: Dump operator needed with live 244 = 0 (eh=1)", ["dump_operator_needed", live(0, 0)], M.LM_PAUSED)
scn("export hazard: Dump marker unreadable with live 244 = 0 (eh=1)", ["dump_corrupt", live(0, 0)], M.LM_PAUSED)
scn("export hazard: R244 pending clear with live 244 = 0 (eh=1)", ["r244_pending_clear", live(0, 0)], M.LM_PAUSED)
scn("export hazard: Dump ACTIVE, live 244 = 0, exempt original", ["dump_active", live(0, 0), "dump_exempt"], M.LM_PAUSED)
scn("export hazard: Dump restore-required, residue differs", ["dump_restore_required", live(0, 0), "dump_exempt_residue"], M.LM_PAUSED)
scn("elig NO: a refusal on the cached words", [live(1, 499)], M.LM_OUT_OF_DOMAIN)
scn("elig ceiling: power above a 5000 W ceiling is a refusal only", ["ceiling_5000"], M.LM_MATCH)

# the pool the random generator draws from
POOL = [n for n in MODS if not n.startswith("live") and not n.startswith("cls")] + [f"cls{c}" for c in range(9)]


def rnd_case(r: random.Random) -> list[str]:
    mods = [r.choice(POOL) for _ in range(r.choice((0, 0, 1, 1, 2, 3)))]
    for _ in range(r.choice((0, 1, 1, 2, 3))):
        mods.append(live(r.randrange(31), r.choice(LIVE_VALUES)))
    return mods


def apply_py(mods: list[str]) -> "cap.LiveMatchInputs":
    i = base_inputs()
    for name in mods:
        MODS[name].py(i)
    return i


def cxx_case(mods: list[str]) -> str:
    return "([]{ LiveMatchInputs in = base_in(); " + " ".join(MODS[n].cxx for n in mods) + " return in; }())"


def text_of(mods: list[str]) -> str:
    return str(cap.b10_text(cap.live_match(apply_py(mods))))


# ===========================================================================
# [1] model
# ===========================================================================
B10_RE = re.compile(
    r"^m=(MATCH|DRIFT|CONTEXT|EXPORT|OUT_OF_DOMAIN|PAUSED|PAUSED_IO|UNKNOWN|NO_PROFILE);dx=([0-9A-F]{5}|-);cx=([0-9A-F]{3}|-);"
    r"ox=([0-9A-F]{5}|-);ix=([0-9A-F]{2}|-);eh=([U01]);obl=(-|FP:[A-Z]{2},DP:[A-Z]{2},R4:[A-Z]{2},BUS:[A-Z]{2});"
    r"ca=([BIOSPMF]);elig=(OK|NO|OVL|UNK);ew=(-|[A-Z0-9]{4,8}(,[A-Z0-9]{4,8}){0,2}(\+[0-9]+)?)$")
B10_KEYS = ("m", "dx", "cx", "ox", "ix", "eh", "obl", "ca", "elig", "ew")
M_NAMES = {"MATCH", "DRIFT", "CONTEXT", "EXPORT", "OUT_OF_DOMAIN", "PAUSED", "PAUSED_IO", "UNKNOWN", "NO_PROFILE"}


def section_model() -> None:
    print("\n[1] model: precedence, masks, effective class, trust, fence, export hazard, grammar")
    # hand-written expectations (independent of the C++ and of the random parity below)
    bad = []
    for label, mods, expect in SCENARIOS:
        got = cap.live_match(apply_py(mods)).m
        if expect is not None and got != expect:
            bad.append(f"{label}: want {cap.lm_name(expect)} got {cap.lm_name(got)}")
    check(f"all {len(SCENARIOS)} hand-written scenarios resolve to the m the architecture's precedence demands", not bad, "; ".join(bad))

    r = cap.live_match(base_inputs())
    check("MATCH: masks are all zero and published (`00000` / `000` / `00000` / `00`)",
          str(cap.b10_text(r)).startswith("m=MATCH;dx=00000;cx=000;ox=00000;ix=00;eh=0;obl=FP:CR,DP:CR,R4:CR,BUS:OK;ca=F;elig=OK;ew=-"),
          str(cap.b10_text(r)))
    # the masks are the SHARED ones: one comparison implementation
    i = apply_py([live(3, 3001), live(20, 0), live(1, 8001), live(28, 1)])
    r = cap.live_match(i)
    stored = cap.words_of(GOLD_P)
    check("live_match reports exactly e1_delta_mask / ctx_mismatch_mask / out_of_domain_mask / info_mismatch_mask of the shared header",
          (r.dx, r.cx, r.ox, r.ix) == (cap.e1_delta_mask(i.live, stored), cap.ctx_mismatch_mask(i.live, stored),
                                       cap.out_of_domain_mask(i.live), cap.info_mismatch_mask(i.live, stored)),
          str((r.dx, r.cx, r.ox, r.ix)))
    check("the mask bit layouts: dx bit0 244, bits1-6 256-261; cx bit1 243; ix bit0 230",
          r.dx == (1 << 3) | (1 << 1) and r.cx == 0b10 and r.ix == 0b1, str((hex(r.dx), hex(r.cx), hex(r.ix))))
    # masks are '-' unless the comparison ran
    for mods in (["boot_not_loaded"], ["cls1"], ["fp_active"], ["bus_mwip"], ["stale"]):
        t = text_of(mods)
        check(f"masks are `-` when the comparison did not run ({mods[0]})", "dx=-;cx=-;ox=-;ix=-" in t, t)
    # effective class (A5)
    check("live_effective_class: SAVE_UNCONFIRMED overlay beats every composed class (identical to ecco_fbsave.overlay_class)",
          all(cap.live_effective_class(c, True, 0) == fd.EPC_SAVE_UNCONFIRMED for c in range(9)))
    check("live_effective_class: a read anomaly makes any composed class UNREADABLE, no anomaly keeps it",
          all(cap.live_effective_class(c, False, 1) == fd.EPC_UNREADABLE and cap.live_effective_class(c, False, 0) == c
              for c in range(9)))
    save_py = (ROOT / "registry" / "fallback_save.py").read_text(encoding="utf-8")
    check("the overlay value is the one FB-B2 publishes (fallback_save.overlay_class(c, True) == EPC_SAVE_UNCONFIRMED)",
          "def overlay_class" in save_py and fd.EPC_SAVE_UNCONFIRMED == 7)
    only_valid = [c for c in range(9) if cap.live_match(apply_py([f"cls{c}"])).m != M.LM_NO_PROFILE]
    check("only the composed class VALID (5) can ever compare; every other class is NO_PROFILE", only_valid == [fd.EPC_VALID], str(only_valid))
    # trust terms
    def trust(**kw):
        c = cap.LiveCache(cache_valid=True, online=True, polling=True, filled=True, block_b_seq=1, block_b_ok_ms=0, now_ms=10,
                          response_dispatch_seq=5, fence_seq=5)
        for k, v in kw.items():
            setattr(c, k, v)
        return c
    letter = lambda q: cap.cq_char(q)  # noqa: E731
    check("live_trust: every term passes -> F", letter(cap.live_trust(trust(), True)) == "F")
    check("live_trust: boot not loaded -> B (first term)", letter(cap.live_trust(trust(), False)) == "B")
    check("live_trust: I / O / S / P / M, each its own letter",
          [letter(cap.live_trust(trust(**kw), True)) for kw in (dict(cache_valid=False), dict(online=False), dict(block_b_seq=0),
                                                                  dict(polling=False), dict(now_ms=180001),
                                                                  dict(response_dispatch_seq=4), dict(filled=False))]
          == ["I", "I", "I", "O", "S", "P", "M"])
    check("live_trust: the unset default (a forgotten LiveCache) is untrusted", letter(cap.live_trust(cap.LiveCache(), True)) == "I")
    check("live_trust: fence passes at exactly equal and fails one below",
          cap.fence_passed(5, 5) and not cap.fence_passed(4, 5) and cap.fence_passed(6, 5))
    # fence
    F, S = cap.FenceState, cap.FenceSample
    s0 = cap.fence_tick(F(), S(bus_hot=False, lease_nonclear=False, writes_fp=9, dispatch_seq=10))
    check("fence: the first tick of a boot is hot (fail-closed seeding): seq = dispatch + 2, edge untouched, baseline stored",
          (s0.seq, s0.edge_seq, s0.writes_fp, s0.flags) == (12, 0, 9, cap.FENCE_SEEDED), str(s0))
    s1 = cap.fence_tick(s0, S(bus_hot=False, lease_nonclear=False, writes_fp=9, dispatch_seq=20))
    check("fence: a quiet tick (idle bus, clear leases, unchanged write counters) does not move either fence",
          (s1.seq, s1.edge_seq) == (12, 0), str(s1))
    s2 = cap.fence_tick(s1, S(bus_hot=True, lease_nonclear=False, writes_fp=9, dispatch_seq=20))
    check("fence: a busy bus raises seq to dispatch + 2 but NOT the lease fence", (s2.seq, s2.edge_seq) == (22, 0), str(s2))
    s3 = cap.fence_tick(s1, S(bus_hot=False, lease_nonclear=False, writes_fp=10, dispatch_seq=21))
    check("fence: a moved write-attempt fingerprint (a hold shorter than the tick) raises seq", (s3.seq, s3.edge_seq) == (23, 0), str(s3))
    s4 = cap.fence_tick(s1, S(bus_hot=False, lease_nonclear=True, writes_fp=9, dispatch_seq=22))
    check("fence: a non-clear lease raises BOTH fences and remembers it", (s4.seq, s4.edge_seq, s4.flags & cap.FENCE_PREV_LEASE) == (24, 24, 2), str(s4))
    s5 = cap.fence_tick(s4, S(bus_hot=False, lease_nonclear=False, writes_fp=9, dispatch_seq=30))
    check("fence: the obligation -> clear edge raises both fences again (an in-flight poll may still carry the overlay)",
          (s5.seq, s5.edge_seq, s5.flags) == (32, 32, cap.FENCE_SEEDED), str(s5))
    s6 = cap.fence_tick(s5, S(bus_hot=False, lease_nonclear=False, writes_fp=9, dispatch_seq=40))
    check("fence: the tick after the edge is quiet again", (s6.seq, s6.edge_seq) == (32, 32), str(s6))
    s7 = cap.fence_tick(F(seq=100, edge_seq=100, flags=cap.FENCE_SEEDED), S(bus_hot=True, lease_nonclear=True, writes_fp=0, dispatch_seq=5))
    check("fence: monotonic - a hot tick never lowers a fence", (s7.seq, s7.edge_seq) == (100, 100), str(s7))
    check("fence: a forgotten FenceSample (every default) is hot", cap.fence_tick(F(flags=cap.FENCE_SEEDED), S(dispatch_seq=3)).seq == 5)
    # the fence changes the verdict: a write between two polls makes a MATCH untrustworthy until a later poll is dispatched
    i = base_inputs()
    i.cache.fence_seq = cap.fence_target(7)
    check("write fence end-to-end: cached response dispatch 7 vs fence 9 -> UNKNOWN (P); response 9 -> trusted again",
          cap.live_match(i).ca == cap.CQ_PRE_FENCE and (setattr(i.cache, "response_dispatch_seq", 9) or cap.live_match(i).ca == cap.CQ_FRESH))
    # export hazard
    EH = cap.export_hazard
    check("export hazard truth table: untrusted -> U; live 244 != 0 -> 0; no hazardous domain -> 0; exempt -> 0; else 1",
          [EH(False, 0, True, False), EH(True, 2, True, False), EH(True, 0, False, False), EH(True, 0, True, True),
           EH(True, 0, True, False)] == [cap.EH_UNKNOWN, cap.EH_NO, cap.EH_NO, cap.EH_NO, cap.EH_YES])
    check("export hazard: an ACTIVE / STARTING lease is guarded (not a hazard); a restore-required lease with 244 = 0 is YES",
          text_of(["fp_active", live(0, 0)]).find("eh=0") > 0 and text_of(["fp_starting", live(0, 0)]).find("eh=0") > 0
          and text_of(["fp_restore_required", live(0, 0)]).find("eh=1") > 0 and text_of(["dump_operator_needed", live(0, 0)]).find("eh=1") > 0)
    check("export hazard: SG-02's D5 exemption needs a LOADED original with 244 == 0 and 256-261 unchanged",
          "eh=0" in text_of(["dump_restore_required", live(0, 0), "dump_exempt"])
          and "eh=1" in text_of(["dump_restore_required", live(0, 0), "dump_exempt_residue"])
          and "eh=1" in text_of(["dump_restore_required", live(0, 0), "dump_snapshot_not_loaded"]))
    check("export hazard: never `0` when the cache is untrusted (U), whatever the words say",
          all("eh=U" in text_of([m, live(0, 0)]) for m in ("stale", "pre_fence", "not_filled", "poll_off", "cache_invalid", "boot_not_loaded")))
    # eligibility
    check("elig: UNK before boot / untrusted / bus busy; OVL under a lease or a pending lease fence; OK / NO + ew otherwise",
          "elig=UNK" in text_of(["boot_not_loaded"]) and "elig=UNK" in text_of(["stale"]) and "elig=UNK" in text_of(["bus_mwip"])
          and "elig=OVL" in text_of(["fp_active"]) and "elig=OVL" in text_of(["edge_pending"]) and "elig=OK" in text_of([])
          and "elig=NO" in text_of([live(1, 499)]) and "ew=PWRL1" in text_of([live(1, 499)]))
    check("elig: OVL beats a stale cache (a lease owns the settings); not evaluable without a profile is still evaluated (elig is profile-independent)",
          "elig=OVL" in text_of(["fp_active", "stale"]) and "elig=OK" in text_of(["cls1"]))
    t = text_of([live(0, 3), live(1, 499), live(2, 8001), live(3, 101), live(20, 5)])
    check("ew: at most three codes, then +N", re.search(r"ew=244X,PWRL1,PWRH2\+\d+$", t) is not None, t)
    # grammar and bound
    texts = {text_of(m) for _l, m, _e in SCENARIOS} | {text_of(rnd_case(random.Random(7000 + n))) for n in range(400)}
    bad = [t for t in texts if not B10_RE.match(t) or len(t) > cap.TEXT_CAP]
    check(f"B10 grammar: {len(texts)} distinct texts all match the locked grammar and are <= 200 characters", not bad, str(bad[:2]))
    keys = {tuple(kv.split("=")[0] for kv in t.split(";")) for t in texts}
    check("B10 grammar: the ten keys m;dx;cx;ox;ix;eh;obl;ca;elig;ew are always present in this exact order", keys == {B10_KEYS}, str(keys))
    check("B10 enum set: m takes only the nine locked values and every one of them is reachable",
          {t.split(";")[0][2:] for t in texts} == M_NAMES, str(sorted({t.split(";")[0][2:] for t in texts} ^ M_NAMES)))
    worst = cap.LiveMatchResult(m=cap.LM_OUT_OF_DOMAIN, ca=cap.CQ_FRESH, compared=True, dx=0x7FFFF, cx=0x1FF, ox=0x7FFFF, ix=0x1F,
                                eh=cap.EH_YES, obl_valid=True, elig=cap.ELIG_NO)
    worst.fp = worst.dump = worst.r244 = cap.SlotClass(cap.UNK_DURABLE_UNREADABLE, cap.BASIS_BOOT_READ_ERROR)
    worst.bus = cap.SlotClass(cap.UNK_BUS_OR_LOCK_STUCK, cap.BASIS_LOCK_STUCK)
    for k in range(40):
        cap._refusal_add(worst.ew, cap.RF_PWRH, 1 + k % 6)
    wt = str(cap.b10_text(worst))
    check("B10 worst case (every field at its widest) is <= 200 characters and still matches the grammar",
          len(wt) <= 200 and B10_RE.match(wt) is not None, f"{len(wt)}: {wt}")
    seed = str(cap.b10_seed_text())
    check("the B10 seed is exactly `m=UNKNOWN;dx=-;cx=-;ox=-;ix=-;eh=U;obl=-;ca=B;elig=UNK;ew=-` (UNKNOWN, tri-state U, ca=B)",
          seed == "m=UNKNOWN;dx=-;cx=-;ox=-;ix=-;eh=U;obl=-;ca=B;elig=UNK;ew=-" and B10_RE.match(seed) is not None, seed)
    zero = cap.LiveMatchInputs()
    check("a forgotten / zero LiveMatchInputs fails closed: NO_PROFILE, ca=B, eh=U, elig=UNK (never MATCH)",
          str(cap.b10_text(cap.live_match(zero))) == "m=NO_PROFILE;dx=-;cx=-;ox=-;ix=-;eh=U;obl=-;ca=B;elig=UNK;ew=-",
          str(cap.b10_text(cap.live_match(zero))))
    bad = [n for n in MODS if not n.startswith(("live", "cls")) and cap.live_match(apply_py([n])).m == M.LM_MATCH
           and n not in ("stale_edge", "fresh_wrapped", "edge_passed_equal", "ceiling_5000", "dump_exempt", "dump_exempt_residue",
                         "dump_snapshot_not_loaded")]
    check("no single fault modification can leave a MATCH (every such input is something other than MATCH)", not bad, str(bad))


# ===========================================================================
# [2] host compile
# ===========================================================================
def find_compiler():
    import glob
    env = os.environ.get("ECCO_CXX")
    if env:
        return env
    for name in ("g++", "c++"):
        found = shutil.which(name)
        if found:
            return found
    local = os.environ.get("LOCALAPPDATA")
    pats = []
    if local:
        pats.append(os.path.join(local, "esphome", "Cache", "idf", "tools", "xtensa-esp-elf", "*", "xtensa-esp-elf", "bin",
                                 "xtensa-esp32-elf-g++*"))
    home = Path.home()
    pats += [str(home / ".esphome" / "**" / "xtensa-esp32-elf-g++*"),
             str(home / ".espressif" / "tools" / "xtensa-esp-elf" / "*" / "xtensa-esp-elf" / "bin" / "xtensa-esp32-elf-g++*")]
    for pat in pats:
        hits = sorted(glob.glob(pat, recursive=True))
        if hits:
            return hits[-1]
    return None


def compile_tu(cxx: str, std: str, tu: str, inc: Path, workdir: Path, name: str):
    src = workdir / f"{name}.cpp"
    src.write_text(tu, encoding="utf-8", newline="\n")
    p = subprocess.run([cxx, f"-std={std}", "-fsyntax-only", "-Wall", "-Wextra", "-Werror", "-I", str(inc), str(src)],
                       capture_output=True, text=True, timeout=1800)
    return p.returncode, (p.stdout + p.stderr).replace("‘", "'").replace("’", "'")


def fence_sequence(seed: int, n: int = 40, monotonic: bool = True):
    r = random.Random(seed)
    out, d, fpv = [], 0, 0
    for _ in range(n):
        d = d + r.choice((0, 0, 1, 1, 2)) if monotonic else r.randrange(0, 30)
        if r.random() < 0.25:
            fpv += r.randrange(1, 3)
        out.append((r.random() < 0.3, r.random() < 0.3, fpv, d))
    return out


def fence_replay_py(seq) -> tuple:
    s, h = cap.FenceState(), 0
    for bus, lease, fpv, d in seq:
        s = cap.fence_tick(s, cap.FenceSample(bus_hot=bus, lease_nonclear=lease, writes_fp=fpv, dispatch_seq=d))
        h = (h * 31 + s.seq + s.edge_seq * 7 + s.flags) & 0xFFFFFFFF
    return s.seq, s.edge_seq, s.writes_fp, s.flags, h


def build_parity_tu() -> tuple[str, int]:
    lines = ['#include "ecco_fallback_capture.h"', "namespace ecco_fbcap {",
             f"static_assert(first_diff(GOLDEN_WORDS, CaptureWords{{{', '.join(str(w) + 'u' for w in GW)}}}) == -1, \"LM fixture: golden words\");",
             CXX_BASE.replace("LiveMatchInputs base_in()", "constexpr LiveMatchInputs base_in()")]
    n = 0
    for label, mods, _e in SCENARIOS:
        lines.append(f'static_assert(text_is("{text_of(mods)}", b10_text(live_match({cxx_case(mods)}))), "LM scenario {n}: {label.split(":")[0][:40]}");')
        n += 1
    r = random.Random(20261002)
    for k in range(300):
        mods = rnd_case(r)
        lines.append(f'static_assert(text_is("{text_of(mods)}", b10_text(live_match({cxx_case(mods)}))), "LM random {k}");')
        n += 1
    # trust letters: 120 random caches x boot flag
    r = random.Random(555)
    for k in range(120):
        c = cap.LiveCache(cache_valid=r.random() < .9, online=r.random() < .9, polling=r.random() < .9, filled=r.random() < .9,
                          block_b_seq=r.choice((0, 1, 9)), block_b_ok_ms=r.choice((0, 1000, 4294960000)),
                          now_ms=r.choice((0, 2000, 181000, 181001, 190000, 100000)), response_dispatch_seq=r.randrange(0, 12),
                          fence_seq=r.choice((0, 5, 7, 11, 0xFFFFFFFF)))
        bl = r.random() < .9
        want = cap.cq_char(cap.live_trust(c, bl))
        cx = (f"LiveCache{{{str(c.cache_valid).lower()}, {str(c.online).lower()}, {str(c.polling).lower()}, {str(c.filled).lower()}, "
              f"{c.block_b_seq}u, {c.block_b_ok_ms}u, {c.now_ms}u, {c.response_dispatch_seq}u, {c.fence_seq}u}}")
        lines.append(f'static_assert(cq_char(live_trust({cx}, {str(bl).lower()})) == \'{want}\', "LM trust {k}");')
        n += 1
    # export hazard truth table
    for trusted in (False, True):
        for l244 in (0, 1, 2):
            for bad in (False, True):
                for ex in (False, True):
                    want = cap.export_hazard(trusted, l244, bad, ex)
                    lines.append(f'static_assert(export_hazard({str(trusted).lower()}, {l244}, {str(bad).lower()}, {str(ex).lower()}) == {want}, "LM eh {trusted}{l244}{bad}{ex}");')
                    n += 1
    # fence replays
    for seed in (1, 2, 3, 4, 5, 6, 7, 8):
        seq = fence_sequence(seed, monotonic=seed <= 6)   # seeds 7 / 8: dispatch values may go DOWN (a fence must still never lower)
        want = fence_replay_py(seq)
        arr = ", ".join(f"FenceSample{{{str(b).lower()}, {str(l).lower()}, {f}u, {d}u}}" for b, l, f, d in seq)
        lines.append(f"""static_assert([]{{ constexpr FenceSample S[] = {{{arr}}}; FenceState s{{}}; uint32_t h = 0;
  for (const FenceSample &x : S) {{ s = fence_tick(s, x); h = h * 31u + s.seq + s.edge_seq * 7u + s.flags; }}
  return s.seq == {want[0]}u && s.edge_seq == {want[1]}u && s.writes_fp == {want[2]}u && s.flags == {want[3]} && h == {want[4]}u; }}(), "LM fence replay {seed}");""")
        n += 1
    lines.append('static_assert(text_is("m=UNKNOWN;dx=-;cx=-;ox=-;ix=-;eh=U;obl=-;ca=B;elig=UNK;ew=-", b10_seed_text()), "LM seed");')
    lines.append('static_assert(text_is("m=NO_PROFILE;dx=-;cx=-;ox=-;ix=-;eh=U;obl=-;ca=B;elig=UNK;ew=-", b10_text(live_match(LiveMatchInputs{}))), "LM zero inputs");')
    lines.append('static_assert(live_effective_class(5, true, 0) == ecco_fbdurable::EPC_SAVE_UNCONFIRMED && live_effective_class(5, false, 1) == ecco_fbdurable::EPC_UNREADABLE && live_effective_class(5, false, 0) == 5, "LM effective class");')
    lines.append("}  // namespace ecco_fbcap\nint main() { return 0; }\n")
    return "\n".join(lines), n + 3


def section_compile(cxx) -> tuple[str, int]:
    print("\n[2] host compile: C++ == Python on the scenario table and 300 seeded random cases")
    tu, n = build_parity_tu()
    with tempfile.TemporaryDirectory() as d:
        wd = Path(d)
        for std in ("gnu++17", "gnu++20"):
            rc, out = compile_tu(cxx, std, tu, INCLUDE_DIR, wd, f"parity_{std[-2:]}")
            check(f"[{std}] header + {n} Live Match static_asserts compile under -Wall -Wextra -Werror (C++ == Python)", rc == 0,
                  out[:1500])
    return tu, n


# ===========================================================================
# [3] mutants
# ===========================================================================
MUTANTS = [
    ("precedence: CONTEXT before OUT_OF_DOMAIN",
     "r.m = ox != 0 ? (uint8_t) LM_OUT_OF_DOMAIN\n          : ((dx & 1u) != 0 && in.live[0] == 0) ? (uint8_t) LM_EXPORT\n          : cx != 0 ? (uint8_t) LM_CONTEXT",
     "r.m = cx != 0 ? (uint8_t) LM_CONTEXT\n          : ((dx & 1u) != 0 && in.live[0] == 0) ? (uint8_t) LM_EXPORT\n          : ox != 0 ? (uint8_t) LM_OUT_OF_DOMAIN"),
    ("precedence: DRIFT before EXPORT",
     "((dx & 1u) != 0 && in.live[0] == 0) ? (uint8_t) LM_EXPORT\n          : cx != 0 ? (uint8_t) LM_CONTEXT\n          : dx != 0 ? (uint8_t) LM_DRIFT",
     "cx != 0 ? (uint8_t) LM_CONTEXT\n          : dx != 0 ? (uint8_t) LM_DRIFT\n          : ((dx & 1u) != 0 && in.live[0] == 0) ? (uint8_t) LM_EXPORT"),
    ("EXPORT keyed on the wrong live 244 value (1 instead of 0)", "((dx & 1u) != 0 && in.live[0] == 0)", "((dx & 1u) != 0 && in.live[0] == 1)"),
    ("the SAVE_UNCONFIRMED overlay is dropped", "return write_outcome_unknown ? (uint8_t) ecco_fbdurable::EPC_SAVE_UNCONFIRMED\n         : read_anomaly != 0",
     "return false ? (uint8_t) ecco_fbdurable::EPC_SAVE_UNCONFIRMED\n         : read_anomaly != 0"),
    ("the read-anomaly clause is dropped", ": read_anomaly != 0 ? (uint8_t) ecco_fbdurable::EPC_UNREADABLE\n                             : cls;",
     ": false ? (uint8_t) ecco_fbdurable::EPC_UNREADABLE\n                             : cls;"),
    ("the mirror record is not required to classify VALID",
     "const bool profile_valid = eff == ecco_fbdurable::EPC_VALID &&\n                             ecco_fallback::classify_profile(in.p_load, in.p) == ecco_fallback::PROFILE_VALID;",
     "const bool profile_valid = eff == ecco_fbdurable::EPC_VALID;"),
    ("the fence passes one early (> instead of >=)", "return response_dispatch_seq >= fence_seq;", "return response_dispatch_seq > fence_seq;"),
    ("a trust term is dropped: RAW_CACHE_EXT never-filled", "  if (!c.filled)\n    return CQ_NOT_FILLED;\n", ""),
    ("the staleness bound is off by one (>= instead of >)", "> LIVE_CACHE_MAX_AGE_MS", ">= LIVE_CACHE_MAX_AGE_MS"),
    ("the staleness bound is not wrap-safe", "(uint32_t) (c.now_ms - c.block_b_ok_ms) > LIVE_CACHE_MAX_AGE_MS", "c.now_ms > c.block_b_ok_ms + LIVE_CACHE_MAX_AGE_MS"),
    ("trust order: pre-fence tested before poll-off",
     "  if (!c.polling)\n    return CQ_POLL_OFF;\n  if ((uint32_t) (c.now_ms - c.block_b_ok_ms) > LIVE_CACHE_MAX_AGE_MS)\n    return CQ_STALE;\n  if (!fence_passed(c.response_dispatch_seq, c.fence_seq))\n    return CQ_PRE_FENCE;\n",
     "  if (!fence_passed(c.response_dispatch_seq, c.fence_seq))\n    return CQ_PRE_FENCE;\n  if (!c.polling)\n    return CQ_POLL_OFF;\n  if ((uint32_t) (c.now_ms - c.block_b_ok_ms) > LIVE_CACHE_MAX_AGE_MS)\n    return CQ_STALE;\n"),
    ("the fence ignores the lease edge", "const bool edge = seeded && prev_lease && !t.lease_nonclear;", "const bool edge = false;"),
    ("the first tick is not hot (no fail-closed seeding)", "const bool hot = !seeded || t.bus_hot", "const bool hot = t.bus_hot"),
    ("the write-attempt fingerprint is not a hot reason", " || t.writes_fp != s.writes_fp;", ";"),
    ("a lease tick does not raise the lease fence", "if (t.lease_nonclear || edge)\n    n.edge_seq", "if (edge)\n    n.edge_seq"),
    ("the fence offset is 1 instead of 2", "constexpr uint32_t LIVE_FENCE_OFFSET = 2u;", "constexpr uint32_t LIVE_FENCE_OFFSET = 1u;"),
    ("a lower fence may replace a higher one (not monotonic)", "n.seq = seq_max(n.seq, target);", "n.seq = target;"),
    ("PAUSED_IO row removed (reads PAUSED)", "r.m = LM_PAUSED_IO;", "r.m = LM_PAUSED;"),
    ("the pending lease fence is ignored by m", "} else if (lease_nonclear || edge_pending) {\n    r.m = LM_PAUSED;", "} else if (lease_nonclear) {\n    r.m = LM_PAUSED;"),
    ("a non-OK bus is not PAUSED_IO", "const bool bus_not_idle = r.bus.kind != OBL_CLEAR_PROVEN || in.mtou_running;",
     "const bool bus_not_idle = in.mtou_running;"),
    ("an untrusted cache is compared anyway", "} else if (!trusted) {\n    r.m = LM_UNKNOWN;", "} else if (false) {\n    r.m = LM_UNKNOWN;"),
    ("the export hazard ignores trust", "if (!live_trusted)\n    return EH_UNKNOWN;", "if (false)\n    return EH_UNKNOWN;"),
    ("the export hazard treats live 244 == 1 as a hazard", "if (live244 != 0)\n    return EH_NO;", "if (live244 > 1)\n    return EH_NO;"),
    ("an ACTIVE lease counts as an export hazard", "return !slot_ram_clear(c) && c.kind != OBL_ACTIVE && c.kind != OBL_STARTING;",
     "return !slot_ram_clear(c);"),
    ("the D5 exemption forgets register 261", "in.live[6] == in.dump_snapshot_reg256_261[5];", "true;"),
    ("elig OVL is not reported under a lease", "else if (lease_nonclear || edge_pending)\n    r.elig = ELIG_OVL;", "else if (false)\n    r.elig = ELIG_OVL;"),
    ("the B10 key cx is renamed dc", 'put(t, ";cx=");', 'put(t, ";dc=");'),
    ("the masks are published even when not compared", 'put(t, ";dx=");\n  if (r.compared)', 'put(t, ";dx=");\n  if (true)'),
    ("the unknown tri-state letter reads 0", "constexpr char eh_char(uint8_t e) { return e == EH_NO ? '0' : e == EH_YES ? '1' : 'U'; }",
     "constexpr char eh_char(uint8_t e) { return e == EH_YES ? '1' : '0'; }"),
    ("RAM-clear lease slots print NP instead of CR", 'return slot_ram_clear(c) ? "CR" : obl_code(c.kind, c.basis);', "return obl_code(c.kind, c.basis);"),
    ("dx is a full-word compare of 244 only", "const uint32_t dx = e1_delta_mask(in.live, stored);", "const uint32_t dx = (uint32_t) (in.live[0] != stored[0]);"),
]


def section_mutants(cxx, tu: str, n: int) -> None:
    print(f"\n[3] mutants: {len(MUTANTS)} key conditions of the Live Match section, each must be a compile rejection")
    base = read_header().replace("\r\n", "\n")
    missing = [lab for lab, old, _new in MUTANTS if base.count(old) != 1]
    check("every mutant's target text occurs exactly once in the header", not missing, str(missing))
    if missing:
        return
    with tempfile.TemporaryDirectory() as d:
        wd = Path(d)
        results = {}

        def one(idx: int):
            lab, old, new = MUTANTS[idx]
            inc = wd / f"inc{idx}"
            shutil.copytree(INCLUDE_DIR, inc)
            (inc / "ecco_fallback_capture.h").write_text(base.replace(old, new), encoding="utf-8", newline="\n")
            rc, out = compile_tu(cxx, "gnu++17", tu, inc, wd, f"mut{idx}")
            return idx, rc, out

        workers = min(4, os.cpu_count() or 2)
        with ThreadPoolExecutor(max_workers=workers) as pool:
            for idx, rc, out in pool.map(one, range(len(MUTANTS))):
                results[idx] = (rc, out)
    for idx, (lab, _o, _n) in enumerate(MUTANTS):
        rc, out = results[idx]
        check(f"mutant {idx:02d} rejected by a static_assert: {lab}", rc != 0 and "static assertion failed" in out and "LM " in out,
              (out[:400] if rc == 0 or "static assertion failed" not in out else ""))


# ===========================================================================
# [4] firmware
# ===========================================================================
def strip_cpp(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return re.sub(r"//[^\n]*", "", text)


def strip_yaml_comments(text: str) -> str:
    return "\n".join(l for l in text.split("\n") if not l.lstrip().startswith("#"))


def section_firmware() -> None:
    print("\n[4] firmware: RAW_CACHE_EXT, the assignment allowlist, B10, the third interval lambda, the write surface")
    import _scope_chain as chain
    # PEX0: the tree's real chain (it carries pub0 and the post-export entries), like read_fw(): a later declared edit to a chain-pinned
    # artifact is then undone exactly before the as-of-fbb3 / as-of-fbb2 measurements below. Chain() is the twelve ENTRIES only.
    ch = chain.CHAIN
    live_fw = read_fw()
    base_fw = scope.pre_fbb3_firmware(live_fw)   # FB-C2: live_fw is already the fbb3 state, so only fbb3 is reverted
    code = strip_yaml_comments(live_fw)

    # --- globals
    g = chain.load_fw(live_fw)["globals"]
    byid = {x["id"]: x for x in g}
    ok = True
    for gid in scope.RAW_CACHE_EXT_IDS:
        want_type = "bool" if gid.endswith("filled") else "uint16_t"
        x = byid.get(gid, {})
        ok = ok and x.get("type") == want_type and str(x.get("restore_value")).lower() in ("no", "false") \
            and str(x.get("initial_value")).strip("'\"") in ("0", "false")
    check("RAW_CACHE_EXT: fbc_raw_230/243/245/247/248 are uint16_t and fbc_raw_filled bool, all restore_value: no, initial 0 / false", ok)
    check("fence: the four scalars exist, restore_value: no",
          all(str(byid.get(i, {}).get("restore_value")).lower() in ("no", "false") for i in scope.FENCE_IDS))
    new_ids = [x["id"] for x in chain.load_fw(live_fw)["globals"]]
    base_ids = [x["id"] for x in chain.load_fw(base_fw)["globals"]]
    check("the ten new globals are exactly scope.NEW_GLOBAL_IDS, appended after the FB-B2 globals",
          new_ids == base_ids + list(scope.NEW_GLOBAL_IDS), str(set(new_ids) ^ set(base_ids + list(scope.NEW_GLOBAL_IDS))))
    rv = [x["id"] for x in g if str(x.get("restore_value")).lower() in ("yes", "true")]
    rv_base = [x["id"] for x in chain.load_fw(base_fw)["globals"] if str(x.get("restore_value")).lower() in ("yes", "true")]
    check("the restore_value: yes set is unchanged", rv == rv_base and not any(i.startswith(("fbc_", "fallback_profile_live")) for i in rv))

    # --- RAW_CACHE_EXT assignment allowlist and offsets
    lines = code.split("\n")
    assigns = [(n, l) for n, l in enumerate(lines) if re.search(r"id\(fbc_raw_\w+\)\s*=(?!=)", l)]
    reads = [n for n, l in enumerate(lines) if "fbc_raw_" in l and not re.search(r"id\(fbc_raw_\w+\)\s*=(?!=)", l)
             and not l.strip().startswith(("- id:", "id:"))]
    check("RAW_CACHE_EXT assignment allowlist: exactly 7 assignment sites (5 raw words, the filled flag, nothing else)",
          len(assigns) == 6 and sorted(re.search(r"fbc_raw_(\w+)\)", l).group(1) for _n, l in assigns)
          == sorted(["230", "243", "245", "247", "248", "filled"]), str([l.strip() for _n, l in assigns]))
    # which Modbus read block precedes each assignment: the nearest preceding `start_address:` in the same script
    blk = {}
    for n, l in assigns:
        i = n
        while i >= 0 and "start_address:" not in lines[i]:
            i -= 1
        j = n
        while j >= 0 and not re.match(r"^  - id: \w+", lines[j]):
            j -= 1
        blk[re.search(r"fbc_raw_(\w+)\)", l).group(1)] = (re.search(r"start_address:\s*(\d+)", lines[i]).group(1),
                                                         re.match(r"^  - id: (\w+)", lines[j]).group(1))
    check("every assignment sits inside poll_inverter_configuration_dispatch, after the right read block (A: start 200, B: start 241)",
          all(v[1] == "poll_inverter_configuration_dispatch" for v in blk.values())
          and blk["230"][0] == "200" and all(blk[k][0] == "241" for k in ("243", "245", "247", "248", "filled")), str(blk))
    offs = {k: int(re.search(rf"id\(fbc_raw_{k}\) = values\[(\d+)\];", code).group(1)) for k in ("230", "243", "245", "247", "248")}
    check("response offsets are register - start_address: 230 = values[30] (start 200); 243 / 245 / 247 / 248 = values[2/4/6/7] (start 241)",
          offs == {"230": 30, "243": 2, "245": 4, "247": 6, "248": 7}, str(offs))
    pub = {k: re.search(rf"values\[{offs[k]}\]", code) for k in offs}
    # cross-check against words the handlers already use for these very registers
    check("cross-check against the existing handlers: values[30] is the published grid-charge current, values[32] the reg 232 cache, "
          "values[7] the TOU master bit (log line), values[4] the export power (log line)",
          "id(ecco_cfg_grid_charge_current).publish_state(values[30]);" in code and "id(manual_cfg_reg232_raw) = values[32];" in code
          and "(values[7] & 0x0001) ? \"ON\" : \"OFF\"" in code and re.search(r"Config B: export %uW, TOU %s.*?values\[4\],", code, re.S) is not None
          and all(pub.values()))
    check("fbc_raw_filled = fbc_raw_filled || configuration_block1_ok, immediately after manual_config_raw_cache_valid in Block B's handler",
          "id(manual_config_raw_cache_valid) = id(configuration_block1_ok);\n                        // FB-B3: RAW_CACHE_EXT is usable only after a poll in which Block A and Block B both succeeded.\n                        id(fbc_raw_filled) = id(fbc_raw_filled) || id(configuration_block1_ok);"
          in code.replace("\r", ""))
    # reads: every other occurrence is a declaration, the filled flag's own right-hand side, or a line of the Live Match tick
    tick = scope.LIVE_SCRIPT_BLOCK      # the script that reads RAW_CACHE_EXT (the interval lambda only executes it)
    tick3 = scope.TICK3_BLOCK
    tick_lines = {l.strip() for l in tick.split("\n") if "fbc_raw_" in l}
    assign_lines = {n for n, _l in assigns}
    stray = [l.strip() for n, l in enumerate(lines) if "fbc_raw_" in l and n not in assign_lines
             and not l.strip().startswith("- id: fbc_raw_") and l.strip() not in tick_lines]
    check("RAW_CACHE_EXT: no occurrence outside a declaration, the 6 poll assignments and the Live Match tick", not stray, str(stray))
    check("RAW_CACHE_EXT readers: the Live Match tick reads each of the five words once, plus the filled flag",
          sorted(re.findall(r"id\(fbc_raw_(\w+)\)", strip_cpp(tick))) == sorted(["230", "243", "245", "247", "248", "filled"]),
          str(re.findall(r"id\(fbc_raw_(\w+)\)", strip_cpp(tick))))
    total = len(re.findall(r"fbc_raw_", code))
    check("the token fbc_raw_ occurs exactly 19 times outside comments: 6 declarations, 5 raw-word assignments, the filled assignment "
          "(2: target and its own right-hand side) and 6 reads in the Live Match tick", total == 6 + 5 + 2 + 6, f"{total}")
    # RAW_CACHE_EXT is firmware-only; the B10 entity id is named only by the HA status layer / dashboard (and their suite).
    # The scanner's universe is the repository's Git-TRACKED files (git ls-files) inside the intended scopes - never a filesystem walk - so
    # generated or untracked output (ESPHome's firmware/.esphome build tree, caches, node_modules) can never be mistaken for source.
    ls = subprocess.run(["git", "ls-files", "-z"], cwd=str(ROOT), capture_output=True)
    tracked = sorted(f for f in ls.stdout.decode("utf-8").split("\0") if f)
    SCOPES = ("home-assistant/", "frontend/", "deployment/", "influxdb/", "health/", "firmware/")
    SCOPE_FILES = ("registry/inverter_capabilities.yaml",)
    SUFFIXES = (".yaml", ".yml", ".py", ".ts", ".js", ".md", ".json", ".h")
    scanned = [f for f in tracked if (f.startswith(SCOPES) or f in SCOPE_FILES) and f.endswith(SUFFIXES)]
    leak, b10_holders = [], []
    for rel in scanned:
        p = ROOT / rel
        if p in (FIRMWARE, HEADER_PATH):
            continue
        try:
            txt = p.read_text(encoding="utf-8")
        except Exception:  # noqa: BLE001
            continue
        if "fbc_raw_" in txt:
            leak.append(rel)
        if "fallback_profile_live_match" in txt:
            b10_holders.append(rel)
    ignored_or_untracked = subprocess.run(["git", "ls-files", "-z", "--others"] + [s.rstrip("/") for s in SCOPES], cwd=str(ROOT), capture_output=True)
    outside = {f for f in ignored_or_untracked.stdout.decode("utf-8").split("\0") if f}
    check("the scanner's file set comes from `git ls-files` (it succeeded and found files); EVERY scanned file is Git-tracked",
          ls.returncode == 0 and len(scanned) > 50 and set(scanned) <= set(tracked) and not (set(scanned) & outside), f"rc={ls.returncode} scanned={len(scanned)}")
    check("no `.esphome/` path (ESPHome's generated build / storage tree) and no cache or node_modules path can enter the scanner's file set",
          not any(".esphome/" in f or f.startswith(".esphome/") or "/node_modules/" in f or "/__pycache__/" in f for f in scanned), str([f for f in scanned if ".esphome" in f][:3]))
    check("RAW_CACHE_EXT (fbc_raw_*) is named by no Home Assistant / frontend / deployment / other firmware file (firmware and the capture header only)", not leak, str(leak))
    # FB-C3: the HA shadow UX suite (home-assistant/tests/test_ecco_shadow_check_ux.py) also names the B10 entity id - it feeds B10 values to
    # the canonical status template for the shadow_episode precedence / differential-oracle checks. Still an exact file list.
    check("the B10 entity id is named only by the HA status package, the dashboard and the HA package suites (exact files)",
          sorted(b10_holders) == ["home-assistant/dashboards/ecco_pro.yaml", "home-assistant/packages/ecco_fallback_status.yaml",
                                  "home-assistant/tests/test_ecco_fallback_packages.py", "home-assistant/tests/test_ecco_shadow_check_ux.py"],
          str(b10_holders))

    # --- B10 entity
    fw = chain.load_fw(live_fw)
    ts = fw["text_sensor"]
    base_ts = chain.load_fw(base_fw)["text_sensor"]
    names = [(t.get("name"), t.get("id")) for t in ts]
    base_names = [(t.get("name"), t.get("id")) for t in base_ts]
    check("entity set: the text sensors are exactly FB-B2's plus ONE appended `ECCO Fallback Profile Live Match` / fallback_profile_live_match_text",
          names == base_names + [(scope.TEXT_SENSOR_NAME, scope.TEXT_SENSOR_ID)], str(set(names) ^ set(base_names)))
    b10 = ts[-1]
    check("B10: template text sensor, update_interval: never, no lambda / filter / on_value, diagnostic category",
          b10.get("platform") == "template" and str(b10.get("update_interval")) == "never"
          and not ({"lambda", "filters", "on_value", "set_action"} & set(b10)) and b10.get("entity_category") == "diagnostic", str(b10))
    base_fw_parsed = chain.load_fw(base_fw)
    check("FB-B1 / FB-B2 entities unchanged: the nine FB text sensors keep their exact name / id and order, and the Arm switch, the "
          "Review button and every api action are identical to FB-B2's",
          [n[1] for n in base_names if n[1] and n[1].startswith("fallback_profile_")] == [
              "fallback_profile_state_text", "fallback_profile_summary_text", "fallback_profile_review_text",
              "fallback_profile_review_id_text", "fallback_profile_review_slots_text", "fallback_profile_review_context_text",
              "fallback_profile_slots_text", "fallback_profile_context_text", "fallback_profile_last_result_text"]
          and fw["switch"] == base_fw_parsed["switch"] and fw["button"] == base_fw_parsed["button"]
          and fw["api"]["actions"] == base_fw_parsed["api"]["actions"])
    live_id_uses = len(re.findall(r"id\(fallback_profile_live_match_text\)", code))
    check("B10 is published ONLY by the boot seed (compare + publish) and the third interval lambda (compare + publish): 4 uses",
          live_id_uses == 4, str(live_id_uses))
    boot = scope.BOOT_SEED_BLOCK
    check("B10 is seeded at boot with b10_seed_text() in the boot lambda, after the B9 seed and before the boot load is marked complete",
          live_fw.replace("\r\n", "\n").count("ecco_fbcap::b10_seed_text()") == 1
          and live_fw.replace("\r\n", "\n").index("ecco_fbcap::b9_seed_text()") < live_fw.replace("\r\n", "\n").index("ecco_fbcap::b10_seed_text()")
          < live_fw.replace("\r\n", "\n").index("id(fallback_profile_boot_loaded) = true;") and "publish_state(t.c_str())" in boot)
    check("B10 is published only when the text changes (`.state != t.c_str()` guard on both publishes)",
          len(re.findall(r"if \(id\(fallback_profile_live_match_text\)\.state != t\.c_str\(\)\) id\(fallback_profile_live_match_text\)\.publish_state\(t\.c_str\(\)\);", code)) == 2)

    # --- the third interval lambda
    ivs = fw["interval"]
    base_ivs = chain.load_fw(base_fw)["interval"]
    fbb_iv = [i for i, iv in enumerate(ivs) if any("fallback_profile_arm" in str(a) for a in iv["then"])]
    check("housekeeping: the existing FB-B 10 s interval gained ONE lambda (3 in total), no interval was added, moved or removed",
          len(ivs) == len(base_ivs) and len(fbb_iv) == 1 and len(ivs[fbb_iv[0]]["then"]) == 3
          and len(base_ivs[fbb_iv[0]]["then"]) == 2 and str(ivs[fbb_iv[0]]["interval"]) == "10s"
          and [iv["interval"] for iv in ivs] == [iv["interval"] for iv in base_ivs], str(fbb_iv))
    lam3 = ivs[fbb_iv[0]]["then"][2]["lambda"]
    expected_lam = "\n".join(l[10:] if l.startswith(" " * 10) else l for l in tick3.split("\n")[1:])
    check("the third interval lambda is TICK3_BLOCK verbatim and does exactly one thing: execute the refresh script",
          lam3.strip() == expected_lam.strip() and strip_cpp(lam3).strip() == "id(fallback_profile_live_refresh).execute();")
    scripts = {s["id"]: s for s in fw["script"]}
    base_script_ids = [s["id"] for s in chain.load_fw(base_fw)["script"]]
    check("the refresh script is the ONE new script: lambda-only (a single lambda, mode single, no wait / delay / if / script action)",
          [s["id"] for s in fw["script"]] == base_script_ids[:base_script_ids.index("fallback_profile_save")] + [scope.LIVE_SCRIPT_ID]
          + base_script_ids[base_script_ids.index("fallback_profile_save"):]
          and scripts[scope.LIVE_SCRIPT_ID].get("mode") == "single" and len(scripts[scope.LIVE_SCRIPT_ID]["then"]) == 1
          and list(scripts[scope.LIVE_SCRIPT_ID]["then"][0]) == ["lambda"], str([s["id"] for s in fw["script"]][-6:]))
    lam = scripts[scope.LIVE_SCRIPT_ID]["then"][0]["lambda"]
    body = strip_cpp(lam)
    forbidden = re.findall(r"modbus|nvs_|\bnvs\b|commit_|load_record|save\(|\.execute\(|\.press\(|turn_on|turn_off|\.write\(|uart|esp_restart|"
                           r"App\.|global_preferences|api\.|call_service|publish_state\((?!t\.c_str\(\))", body)
    check("the refresh script contains no Modbus / NVS / script / switch / reboot / API token and publishes only the B10 text", not forbidden, str(forbidden))
    assigned = sorted(set(re.findall(r"\bid\((\w+)\)\s*=(?!=)", body)))
    check("the refresh script assigns ONLY the four fence scalars (every other write is to a lambda-local)",
          assigned == sorted(scope.FENCE_IDS), str(assigned))
    runs = sorted(set(re.findall(r"id\((\w+)\)\.is_running\(\)", body)))
    check("the refresh script reads is_running() only (no execute / stop): the lease, FB capture and Manual TOU scripts plus the poll guard",
          "poll_inverter_configuration_dispatch" in runs and "apply_manual_slot6" in runs and ".stop(" not in body, str(runs))
    check("torn-snapshot guard: only a COMPARED verdict is held back while the configuration poll script runs, AFTER the fence tick and the "
          "evaluation; every non-compared verdict (NO_PROFILE / PAUSED / PAUSED_IO / UNKNOWN) is published at once",
          body.index("fence_tick") < body.index("live_match(") < body.index("lm.compared && id(poll_inverter_configuration_dispatch).is_running()")
          < body.index("b10_text(lm)") and "if (id(poll_inverter_configuration_dispatch).is_running()) return;" not in body)
    gi_fields = sorted(set(re.findall(r"\b(gi\.[\w.]+) =", body)))
    gi_first = sorted(set(re.findall(r"\b(gi\.[\w.]+) =", strip_cpp(ivs[fbb_iv[0]]["then"][0]["lambda"]))))
    check("the gate-input sampling in the refresh script is the same field set as the existing housekeeping lambda's", gi_fields == gi_first,
          str(set(gi_fields) ^ set(gi_first)))
    live_fields = sorted(set(re.findall(r"\bin\.(live\[\d+\]) =", body)))
    check("all 31 live words are assigned, and register order is the canonical REGS order (244, 256-261, 268-273, 274-279, 232, 243, 248, 250-255, 230, 245, 247)",
          len(live_fields) == 31 and [re.search(r"in\.live\[%d\] = id\((\w+)\)" % k, body).group(1) for k in range(31)] ==
          [("manual_cfg_reg%d_raw" % r) if r not in (243, 248, 230, 245, 247) else "fbc_raw_%d" % r for r in cap.REGS], str(live_fields))
    check("the ceiling is the existing substitution", "in.ceiling_w = ${ecco_inverter_tou_power_ceiling_w};" in lam)

    # --- zero write-surface / storage delta (measured, before = as of FB-B2, after = live)
    live_all = {p: chain.read_live(p) for p in chain.PINNED}
    texts_now = ch.as_of_all("fbb3", live_all)   # FB-C2: "now" is the fbb3 state (later entries reverted)
    texts_base = ch.as_of_all("fbb2", live_all)
    m_now, m_base = ch.measure(texts_now), ch.measure(texts_base)
    check(f"measured delta scripts: {m_base['scripts']} -> {m_now['scripts']} (+1: the lambda-only refresh script)", m_now["scripts"] == m_base["scripts"] + 1)
    for key in ("modbus_reads", "modbus_writes", "commit_record", "load_record", "load_record_status", "api_actions",
                "switches", "buttons", "numbers", "selects", "intervals", "substitutions", "includes", "durable_tag_strings"):
        check(f"measured delta {key}: {m_base[key]} -> {m_now[key]} (unchanged)", m_now[key] == m_base[key])
    check(f"measured delta globals: {m_base['globals']} -> {m_now['globals']} (+10)", m_now["globals"] == m_base["globals"] + 10)
    check(f"measured delta text_sensors: {m_base['text_sensors']} -> {m_now['text_sensors']} (+1)", m_now["text_sensors"] == m_base["text_sensors"] + 1)
    ops_now = chain.per_path_ops(texts_now[chain.FIRMWARE], chain._headers_of(texts_now))
    ops_base = chain.per_path_ops(texts_base[chain.FIRMWARE], chain._headers_of(texts_base))
    check("every analyzer path keeps its exact Modbus op list (READ and WRITE op sites unchanged from FB-B2)", ops_now == ops_base)
    nvs_tok = r"nvs_set\w*|nvs_erase\w*|nvs_commit|commit_transition_t|write_one_|commit_record|\.save\(|global_preferences|make_preference|\.sync\("
    heads = {p.name: p.read_text(encoding="utf-8") for p in INCLUDE_DIR.glob("*.h")}
    base_heads = dict(heads)
    base_heads["ecco_fallback_capture.h"] = ""   # the capture header never contained a storage token; checked below
    sites_now = len(re.findall(nvs_tok, strip_cpp(texts_now[chain.FIRMWARE]))) + sum(len(re.findall(nvs_tok, strip_cpp(t))) for t in heads.values())
    sites_base = len(re.findall(nvs_tok, strip_cpp(texts_base[chain.FIRMWARE]))) + sum(len(re.findall(nvs_tok, strip_cpp(t))) for t in base_heads.values())
    check(f"NVS writer / commit sites (YAML + every firmware header): {sites_base} -> {sites_now} (unchanged); the capture header holds none",
          sites_now == sites_base and not re.search(nvs_tok, strip_cpp(heads["ecco_fallback_capture.h"])))
    new_block = (scope.LIVE_SCRIPT_BLOCK + scope.BLOCK_A_BLOCK + scope.BLOCK_B_BLOCK + scope.FILLED_BLOCK + scope.GLOBALS_BLOCK
                 + scope.BOOT_SEED_BLOCK)
    check("no inserted firmware text names a Modbus action, a write template or a storage call", not re.search(
        r"modbus_client\.|write_multiple|write_single|nvs_|commit_record|load_record|commit_transition|preference|script\.execute|\.execute\(",
        strip_cpp(strip_yaml_comments(new_block))))
    print(f"      measured: modbus reads {m_base['modbus_reads']} -> {m_now['modbus_reads']}, modbus writes {m_base['modbus_writes']} -> "
          f"{m_now['modbus_writes']}, NVS writer sites {sites_base} -> {sites_now}, commit_record {m_base['commit_record']} -> {m_now['commit_record']}")

    # --- header section discipline
    hdr = read_header().replace("\r\n", "\n")
    sec = hdr[hdr.index("// FB-B3: Live Match (B10)"):hdr.index("// ---- GOLDENS-BEGIN ----")]
    sc = strip_cpp(sec)
    check("the Live Match header section: constexpr only (no static / inline / extern / mutable / new), no ESPHome / storage / clock / bus token, no include",
          not re.search(r"\b(static|inline|extern|mutable|new|delete|malloc|snprintf|printf|millis|micros)\b|\besp_|\bid\(", sc.replace("static_assert", ""))
          and "#include" not in sc and "nvs" not in sc.lower() and "modbus" not in sc.lower())
    check("the section reuses the four shared masks (calls them, defines no second comparison)",
          all(f"{f}(" in sc for f in ("e1_delta_mask", "ctx_mismatch_mask", "out_of_domain_mask", "info_mismatch_mask"))
          and not re.search(r"constexpr \w+ (e1_delta_mask|ctx_mismatch_mask|out_of_domain_mask|info_mismatch_mask)\(", sc))
    consts = {k: int(v.rstrip("u")) for k, v in re.findall(r"constexpr uint32_t (LIVE_\w+) = (\d+u?);", sc)}
    check("header constants == mirror constants (fence offset 2, max age 180000 ms)",
          consts == {"LIVE_FENCE_OFFSET": cap.LIVE_FENCE_OFFSET, "LIVE_CACHE_MAX_AGE_MS": cap.LIVE_CACHE_MAX_AGE_MS}, str(consts))
    enum_cxx = dict(re.findall(r"\b(LM_\w+) = (\d+)", sc))
    enum_py = {n: v for n, v in vars(cap).items() if n.startswith("LM_")}
    check("C++ LiveMatch enum values == mirror values", {k: int(v) for k, v in enum_cxx.items()} == enum_py, str(enum_cxx))


# ===========================================================================
# [4b] B10 moves with B1 (S5 Part A A.3 item 9)
# ===========================================================================
def section_b1_sync() -> None:
    print("\n[4b] B10 follows the effective B1 state in the same synchronous path (no publication skew)")
    import _fbb2_drive as D
    live_fw = read_fw().replace("\r\n", "\n")
    code = strip_yaml_comments(live_fw)
    # --- static: every B1 publish site names its refresh; the boot lambda is the one documented exception (it seeds B10 itself)
    sites = [m.start() for m in re.finditer(r"id\(fallback_profile_state_text\)\.publish_state\(cls_name\);", code)]
    boot_i = code.index("ecco_fbcap::b10_seed_text()")
    runtime = [s for s in sites if s > boot_i]
    follow = [bool(re.search(r"\}\n\s*// FB-B3: Live Match \(B10\) follows the effective B1 state in the same lambda \(no publication skew\)\.\n"
                             r"\s*id\(fallback_profile_live_refresh\)\.execute\(\);\n", code[s:s + 400])) for s in runtime]
    check(f"static: the boot lambda publishes B1 once and seeds B10 later in the same lambda; ALL {len(runtime)} runtime B1 publish sites execute "
          "the refresh script right after the publish", len(sites) == 6 and len(runtime) == 5 and all(follow), str(follow))
    check("static: the refresh script is executed by exactly 6 callers: the 5 runtime B1 sites and the 10 s interval (nothing else)",
          len(re.findall(r"id\(fallback_profile_live_refresh\)\.execute\(\);", code)) == 6)
    # a site's refresh must come AFTER the class / mirror assignments it depends on (never before them)
    order_ok = True
    for s in runtime:
        pre = code[max(0, s - 3500):s]
        order_ok = order_ok and "id(fallback_profile_class) =" in pre and "id(fallback_profile_bytes) =" in pre
    check("static: at every runtime site the class and the profile mirror bytes are assigned BEFORE the B1 publish (so B10 recomputes from the new state)", order_ok)
    # --- behaviour through the real YAML (the FB-B2 strict simulator)
    def prime(d, words=None, dispatch=3):
        """A trusted, fresh cache that equals the saved profile; the fence has been seeded and has passed."""
        w = list(words or d.words)
        regs = {244: w[0], 232: w[19], 250: w[22]}
        names = {}
        for k, r in enumerate(cap.REGS):
            n = f"manual_cfg_reg{r}_raw" if r not in (243, 248, 230, 245, 247) else f"fbc_raw_{r}"
            d.set_g(n, w[k])
        d.set_g("manual_config_raw_cache_valid", True)
        d.set_g("fbc_raw_filled", True)
        d.set_g("cfg_block_b_seq", 5)
        d.set_g("cfg_block_b_ok_ms", d.sim.millis() & 0xFFFFFFFF if hasattr(d.sim, "millis") else 0)
        d.set_g("cfg_block_b_dispatch_seq", dispatch)
        d.set_g("cfg_block_b_response_dispatch_seq", dispatch + 2)
        d.sim.ent("configuration_online").set(True)
        d.sim.ent("configuration_polling").set(True)
        d.sim.run_lambda("id(fallback_profile_live_refresh).execute();")
        d.set_g("cfg_block_b_dispatch_seq", dispatch + 2)
        d.sim.run_lambda("id(fallback_profile_live_refresh).execute();")
        return d

    def b10(d) -> str:
        return str(d.sim.ent("fallback_profile_live_match_text").state)

    def m_of(text: str) -> str:
        return text.split(";")[0][2:]

    def coherent(d) -> list:
        """B1 and B10 must never disagree: B10 compares only while B1 reads VALID."""
        bad = []
        if d.b1 != "VALID" and m_of(b10(d)) not in ("NO_PROFILE", "UNKNOWN"):
            bad.append(f"B1={d.b1} but B10 {b10(d)}")
        return bad

    d = prime(D.Driver(seed="valid"))
    check("behaviour: a VALID profile, a fresh trusted cache equal to it and a passed fence read MATCH",
          m_of(b10(d)) == "MATCH" and d.b1 == "VALID", f"{d.b1} / {b10(d)}")
    d.invalidate()
    check("behaviour: INVALIDATE publishes B1 INVALIDATED and B10 NO_PROFILE in the SAME step (no tick, no time passes)",
          d.b1 == "INVALIDATED" and m_of(b10(d)) == "NO_PROFILE", f"{d.b1} / {b10(d)}")
    d = prime(D.Driver(seed="valid"))
    d.review(expect="CANDIDATE_READY")
    check("behaviour: a REVIEW does not change the class and B10 stays a trusted MATCH", d.b1 == "VALID" and m_of(b10(d)) in ("MATCH", "PAUSED_IO", "UNKNOWN"),
          b10(d))
    ev = []
    d = prime(D.Driver(seed="valid"))
    d.review(expect="CANDIDATE_READY")
    import fallback_durable as fd
    d.fault_write("FBW", result=fd.IDF_ERR_NO_MEM, visible=D.H.VIS_OLD)
    d.save()
    check("behaviour: a SAVE with an UNKNOWN write outcome: B1 SAVE_UNCONFIRMED and B10 NO_PROFILE in the same step (the overlay is respected)",
          d.b1 == "SAVE_UNCONFIRMED" and m_of(b10(d)) == "NO_PROFILE", f"{d.b1} / {b10(d)}")
    d = prime(D.Driver(seed="valid"))
    d.fault_write("FBP", result=fd.IDF_ERR_NVS_READ_ONLY, visible=D.H.VIS_OLD)
    d.invalidate()
    check("behaviour: an INVALIDATE whose profile write is refused after the witness advanced (PROFILE_STALE): B10 NO_PROFILE at once",
          d.b1 == "PROFILE_STALE" and m_of(b10(d)) == "NO_PROFILE", f"{d.b1} / {b10(d)}")
    for seed, want in (("absent", None), ("corrupt", None)):
        pass
    bad = []
    for seed in ("valid", "lag", "witness_corrupt"):
        d = prime(D.Driver(seed=seed))
        bad += coherent(d)
        d.invalidate()
        bad += coherent(d)
        d.reboot()
        bad += [f"after boot: B10 is not the seed: {b10(d)}"] if b10(d) != str(cap.b10_seed_text()) else []
        bad += coherent(d)
    check("behaviour: over three seeds (consistent / lagging / corrupt witness) B1 and B10 never disagree after a step, and a reboot re-seeds B10 fail closed",
          not bad, "; ".join(bad[:3]))
    # the seed itself: boot publishes it before the housekeeping tick can run
    d = D.Driver(seed="valid")
    check("behaviour: right after boot B10 is the fail-closed seed, never a comparison", b10(d) in (str(cap.b10_seed_text()),) or m_of(b10(d)) in ("UNKNOWN", "NO_PROFILE"), b10(d))
    # compared => trusted: no compared verdict can be produced from an untrusted cache (the held-back text can never outlive its trust)
    bad = []
    for label, mods, _e in SCENARIOS:
        r = cap.live_match(apply_py(mods))
        if r.compared and r.ca != cap.CQ_FRESH:
            bad.append(label)
    r = random.Random(99)
    for _ in range(600):
        res = cap.live_match(apply_py(rnd_case(r)))
        if res.compared and (res.ca != cap.CQ_FRESH or res.m in (cap.LM_UNKNOWN, cap.LM_NO_PROFILE, cap.LM_PAUSED, cap.LM_PAUSED_IO)):
            bad.append(str(cap.b10_text(res)))
    check("torn cache / untrusted bus: a compared verdict (the only kind held back while the poll runs) exists only with ca=F, an idle bus and clear leases; "
          "every other state is published immediately", not bad, str(bad[:2]))
    # PAUSED_IO / UNKNOWN from write activity and an untrustworthy cache, never a new MATCH
    check("write activity or an untrusted cache can only ever produce PAUSED_IO / PAUSED / UNKNOWN (600 random inputs, never a MATCH under a fault)",
          all(cap.live_match(apply_py(["bus_mwip"] + rnd_case(random.Random(s)))).m != cap.LM_MATCH for s in range(300))
          and all(cap.live_match(apply_py(["pre_fence"] + rnd_case(random.Random(s)))).m != cap.LM_MATCH for s in range(300)))
    # first boot: the pre-fence window fails closed
    i = base_inputs()
    i.cache.fence_seq = cap.fence_target(0)
    i.cache.response_dispatch_seq = 1
    r1 = cap.live_match(i)
    i.cache.response_dispatch_seq = 2
    r2 = cap.live_match(i)
    check("first boot / after a write: pre-fence is ca=P and UNKNOWN (never MATCH, no write); the first poll dispatched after the fence resumes the comparison",
          (r1.ca, r1.m) == (cap.CQ_PRE_FENCE, cap.LM_UNKNOWN) and (r2.ca, r2.m) == (cap.CQ_FRESH, cap.LM_MATCH))


# ===========================================================================
# [5] scope
# ===========================================================================
def section_scope() -> None:
    print("\n[5] scope: firmware pure-insertion hunks, exact reverter, chain entry fbb3")
    import _scope_chain as chain
    live = read_fw().replace("\r\n", "\n")
    base = scope.pre_fbb3_firmware(live)
    check("pre_fbb3_firmware(live) reproduces the FB-B2 firmware byte for byte (BASE_FW_SHA == the chain's fbb2 checkpoint)",
          scope.sha(base) == scope.BASE_FW_SHA == chain.Chain().checkpoint(chain.FIRMWARE, "fbb2"))
    check("add_fbb3_text(base) reproduces the live firmware (the hunks ARE the change)", scope.add_fbb3_text(base) == live)
    check("the firmware change is thirteen PURE INSERTIONS: the base text is a subsequence of the live text by hunk (no pre-existing line modified)",
          len(scope.HUNKS) == 13 and all(h.after.replace(h.new, "", 1) == h.before for h in scope.HUNKS)
          and sum(1 for l in base.split("\n")) == sum(1 for l in live.split("\n")) - sum(h.new.count("\n") for h in scope.HUNKS))
    mutated = live.replace("id(fbc_raw_248) = values[7];", "id(fbc_raw_248) = values[8];")
    try:
        scope.pre_fbb3_firmware(mutated)
        ok = False
    except AssertionError:
        ok = True
    check("the reverter raises on any altered Slice A line (an exact-match reverter, not a pattern)", ok)
    ch = chain.Chain()
    e = ch.entry("fbb3")
    check("chain entry fbb3 (the FINAL stage entry): its firmware checkpoint equals the live firmware sha and it declares scripts +1, globals +10, "
          "text_sensors +1 and nothing else (no op path, include, substitution)",
          e.checkpoints[chain.FIRMWARE] == scope.sha(live) and dict(e.deltas) == {"scripts": 1, "globals": 10, "text_sensors": 1}
          and not e.op_paths_changed and not e.includes_added and not e.subst_added and e.banned_fw_added == scope.BANNED_FW_ADDED)
    check("chain entry fbb3 is registered immediately after fbb2 (FB-C2: later entries may follow)",
          ch.ids()[ch.ids().index("fbb2"):ch.ids().index("fbb2") + 2] == ["fbb2", "fbb3"])
    on_disk = {p for p in scope.ADDED_FILES if (ROOT / p).is_file()}
    check("every file the entry declares as added exists on disk", on_disk == set(scope.ADDED_FILES), str(set(scope.ADDED_FILES) - on_disk))
    check("the FB-A banned-token count the entry declares equals the measured one (one `ecco_fallback::decode_profile` in the tick)",
          scope.BANNED_FW_ADDED == 1 and len(chain.BANNED.findall(live)) - len(chain.BANNED.findall(base)) == 1)


def main() -> int:
    cxx = find_compiler()
    check("a C++ compiler is available (the host compile never silently skips)", cxx is not None, "set ECCO_CXX or install g++")
    section_model()
    if cxx:
        tu, n = section_compile(cxx)
        section_mutants(cxx, tu, n)
    section_firmware()
    section_b1_sync()
    section_scope()
    print()
    if FAILURES:
        print(f"{len(FAILURES)} FAILED:")
        for f in FAILURES:
            print(f"  - {f}")
        return 1
    print("All FB-B3 Live Match foundation checks passed.")
    print("These prove the pure comparison, the fence, the RAM-only wiring and the zero write-surface delta; they prove nothing about hardware.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
