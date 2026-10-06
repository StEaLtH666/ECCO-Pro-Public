#!/usr/bin/env python3
"""Offline tests for S3: Free Power reboot-resume hardening
(branch `fix/free-power-reboot-resume`).

Defect: on_boot reloads free_power_active_persisted / free_power_restore_requested
/ free_power_end_epoch from the durable data record. A lease persisted as
active_persisted=1, restore_requested=0 then silently CONTINUED after an MCU
reboot - until its original end_epoch once NTP was valid, or for up to the
invalid-clock grace period (~5 min) if it was not - because the 15s Free
Power watchdog only triggers a restore on restore_requested, !active_persisted,
end_epoch expiry, or the grace fallback.

Fix (RAM-only, on_boot's trusted successful-load branch only): if the
reloaded lease is active, force free_power_restore_requested = true in RAM
- mirroring Dump's existing reboot behaviour - so the EXISTING watchdog ->
restore_free_power_snapshot -> restore_free_power_snapshot_dispatch
(ORIGINAL / INTENDED / NEITHER classifier) path takes control on its first
tick. No durable write, no Modbus I/O, no new schema.

No I/O, no hardware, no ESPHome/C++ toolchain. Techniques:
  * The REAL on_boot successful-load prefix (the three lease-field loads
    plus the S3 statement) is extracted from the firmware and EXECUTED by
    the shared restricted interpreter (_free_power_action_sim), with the
    durable record's fields injected - not a hand-copied model.
  * The REAL Free Power watchdog condition's gate statements are extracted
    and evaluated in order; only its wall-clock/millis() tail is modelled.
  * Mutation: the S3 statement is excised from the real extracted code and
    the same checks are shown to FAIL (the lease silently resumes), so
    these tests cannot pass against the pre-fix behaviour.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _free_power_action_sim as _sim  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
FIRMWARE_PATH = ROOT / "firmware" / "ecco_clock_dongle_stage3_4_free_power.yaml"
HEADER_PATH = ROOT / "firmware" / "include" / "ecco_durable_snapshot.h"

FAILURES: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  PASS  {name}")
    else:
        FAILURES.append(name)
        print(f"  FAIL  {name}" + (f" - {detail}" if detail else ""))


def norm(code: str) -> str:
    return re.sub(r"\s+", " ", code).strip()


fw = FIRMWARE_PATH.read_text(encoding="utf-8")
doc = yaml.load(fw, Loader=_sim._FirmwareLoader)
header = HEADER_PATH.read_text(encoding="utf-8")

MARKERS = {m.group(1): int(m.group(2)) for m in re.finditer(r"\b(MARKER_\w+)\s*=\s*(\d+)", header)}
GRACE_MS = int(re.search(r'ecco_free_power_invalid_clock_grace_ms:\s*"(\d+)"', fw).group(1))

# ---------------------------------------------------------------------------
# Extraction
# ---------------------------------------------------------------------------
BOOT_RAW = doc["esphome"]["on_boot"]["then"][0]["lambda"]
BOOT = _sim._strip_code(BOOT_RAW)  # comments / string contents / log calls removed

FP_LOAD = "load_record(ecco_durable::key_for(ecco_durable::FREE_POWER_DATA_TAG), data)) {"
DUMP_LOAD = "load_record(ecco_durable::key_for(ecco_durable::DUMP_TO_GRID_DATA_TAG), data)"


def success_branch(boot: str) -> tuple[int, int]:
    """(start, end) of the body of Free Power's trusted successful-load branch."""
    open_idx = boot.index(FP_LOAD) + len(FP_LOAD) - 1
    return open_idx + 1, _sim._match_brace(boot, open_idx)


def lease_prefix(boot: str) -> str:
    """The REAL successful-load prefix: everything the branch does before it
    starts copying the per-register snapshot fields (the three lease-field
    loads, plus - with the fix - the S3 conversion)."""
    start, end = success_branch(boot)
    body = boot[start:end]
    return body[: body.index("id(free_power_snapshot_reg230)")]


S3_STMT_START = "if (id(free_power_active_persisted)) {"


def s3_statement(boot: str) -> str | None:
    prefix = lease_prefix(boot)
    if S3_STMT_START not in prefix:
        return None
    idx = prefix.index(S3_STMT_START)
    return prefix[idx: idx + _sim._skip_one_statement(prefix[idx:])]


def run_boot_load(boot: str, *, active: int, restore: int, end_epoch: int) -> dict:
    """Executes the REAL extracted lease prefix against injected durable
    record fields (`data.X` -> an injected `id(__data_X)`)."""
    code = re.sub(r"\bdata\.(\w+)", r"id(__data_\1)", lease_prefix(boot))
    state = {
        "__data_active_persisted": active,
        "__data_restore_requested": restore,
        "__data_end_epoch": end_epoch,
        # power-on-reset defaults of the RAM globals
        "free_power_snapshot_valid": False,
        "free_power_active_persisted": False,
        "free_power_restore_requested": False,
        "free_power_end_epoch": 0,
    }
    _sim.exec_lambda(code, state)  # STRICT: any unrecognised statement raises
    return state


def _fp_watchdog_lambda() -> str:
    for entry in doc["interval"]:
        for action in entry.get("then", []):
            body = action.get("if")
            if not body:
                continue
            targets = [a.get("script.execute", {}) for a in body.get("then", [])]
            if any(isinstance(t, dict) and t.get("id") == "restore_free_power_snapshot" for t in targets):
                return body["condition"]["lambda"]
    raise AssertionError("Free Power watchdog interval not found")


WATCHDOG_RAW = _fp_watchdog_lambda()
WATCHDOG = _sim._strip_code(WATCHDOG_RAW)
WD_HEAD, WD_TAIL = WATCHDOG.split("auto now", 1)
WD_GATE_RE = re.compile(r"if\s*\((.+?)\)\s*return\s+(true|false)\s*;")
WD_GATES = [(m.group(1), m.group(2) == "true") for m in WD_GATE_RE.finditer(WD_HEAD)]


def _compile_gate(cond: str):
    cond = re.sub(r"ecco_durable::(MARKER_\w+)", lambda m: str(MARKERS[m.group(1)]), cond)
    return _sim._compile_expr(cond)


WD_COMPILED = [(_compile_gate(c), r) for c, r in WD_GATES]


def watchdog_fires(state: dict, *, clock_valid: bool, now: int, millis: int) -> bool:
    """REAL gate statements evaluated in firmware order; only the wall-clock/
    millis() tail (asserted structurally in [6]) is modelled."""
    for code, result in WD_COMPILED:
        if _sim._eval_expr(code, state, {}):
            return result
    if clock_valid and state["free_power_end_epoch"] != 0:
        return now >= state["free_power_end_epoch"]
    return millis >= GRACE_MS


def after_boot(state: dict, **extra) -> dict:
    s = {
        "free_power_recovery_metadata_corrupt": False,
        "free_power_operation_in_progress": False,
        "manual_write_in_progress": False,
        "correction_in_progress": False,
        "free_power_marker_state": MARKERS["MARKER_RESTORE_REQUIRED"],
    }
    s.update({k: v for k, v in state.items() if not k.startswith("__data_")})
    s.update(extra)
    return s


# Pre-fix / mutation source: the real boot lambda with ONLY the S3 statement excised.
_s3 = s3_statement(BOOT)
BOOT_MUTATED = BOOT.replace(_s3, "", 1) if _s3 else BOOT

NOW = 1_790_000_000
END = NOW + 3600  # lease with an hour still to run

# ===========================================================================
print("[1] S3 statement exists, inside the trusted successful-load branch, after the three lease-field loads")
check("S3 conversion statement present in the successful-load prefix", _s3 is not None)
prefix = lease_prefix(BOOT)
loads = [
    "id(free_power_active_persisted) = data.active_persisted != 0;",
    "id(free_power_restore_requested) = data.restore_requested != 0;",
    "id(free_power_end_epoch) = data.end_epoch;",
]
check("all three lease-field loads present in the successful-load branch", all(l in prefix for l in loads))
if _s3:
    check(
        "S3 statement comes AFTER every lease-field load (cannot be overwritten by the reload)",
        all(prefix.index(l) < prefix.index(_s3) for l in loads if l in prefix),
    )
    check(
        "S3 body is exactly: active_persisted -> restore_requested = true (no else, nothing else)",
        norm(_s3) == norm("if (id(free_power_active_persisted)) { id(free_power_restore_requested) = true; }"),
        norm(_s3),
    )
check(
    "the ONLY boot-time `free_power_restore_requested = true` is inside the successful-load branch",
    BOOT.count("id(free_power_restore_requested) = true;") == 1
    and success_branch(BOOT)[0] < BOOT.index("id(free_power_restore_requested) = true;") < success_branch(BOOT)[1],
)

# ===========================================================================
print("[2] Behaviour of the REAL extracted boot load (executed, not pattern-matched)")
s = run_boot_load(BOOT, active=1, restore=0, end_epoch=END)
check("active=1, restore=0 -> restore_requested forced TRUE in RAM", s["free_power_restore_requested"] is True)
check("active=1, restore=0 -> active_persisted/end_epoch still reloaded unchanged",
      s["free_power_active_persisted"] is True and s["free_power_end_epoch"] == END)
s = run_boot_load(BOOT, active=1, restore=1, end_epoch=END)
check("active=1, restore=1 -> restore_requested remains TRUE", s["free_power_restore_requested"] is True)
s = run_boot_load(BOOT, active=0, restore=0, end_epoch=END)
check("active=0, restore=0 -> NO restore request manufactured (existing semantics preserved)",
      s["free_power_restore_requested"] is False)
s = run_boot_load(BOOT, active=0, restore=1, end_epoch=END)
check("active=0, restore=1 -> restore_requested stays TRUE (unchanged)", s["free_power_restore_requested"] is True)

# ===========================================================================
print("[3] Fail-closed / non-trusted boot paths are untouched by S3")
sb_start, sb_end = success_branch(BOOT)
outside = BOOT[BOOT.index("FREE_POWER_VALID_TAG"): sb_start] + BOOT[sb_end: BOOT.index("FREE_POWER_RETRY_TAG")]
check("no restore_requested assignment in malformed-marker / PENDING_CLEAR / unreadable-data branches",
      "free_power_restore_requested" not in outside)
check("unreadable-data branch still fails closed (metadata_corrupt = true)",
      "id(free_power_recovery_metadata_corrupt) = true;" in BOOT[sb_end: BOOT.index("FREE_POWER_RETRY_TAG")])
check("malformed-marker branch still fails closed (metadata_corrupt = true)",
      "id(free_power_recovery_metadata_corrupt) = true;" in BOOT[BOOT.index("FREE_POWER_VALID_TAG"): sb_start])
check("PENDING_CLEAR branch still forces active_persisted = false (no write-capable state)",
      "id(free_power_active_persisted) = false;" in BOOT[BOOT.index("FREE_POWER_VALID_TAG"): sb_start])
check("S3 block does not touch metadata_corrupt / snapshot_valid / marker_state",
      _s3 is not None and not re.search(r"metadata_corrupt|snapshot_valid|marker_state", _s3))

# ===========================================================================
print("[4] No durable write and no Modbus I/O introduced by S3")
for token in ("commit_record", "save", "sync", "key_for", "_TAG", "modbus", "write", "publish_state", "execute"):
    check(f"S3 block contains no `{token}`", _s3 is not None and token not in _s3)
s3_raw = ""
if _s3:
    _raw_start = BOOT_RAW.index(S3_STMT_START, BOOT_RAW.index(FP_LOAD))
    s3_raw = BOOT_RAW[_raw_start: _raw_start + _sim._skip_one_statement(BOOT_RAW[_raw_start:])]
check("S3 raw block (incl. log line) contains no commit/Modbus call",
      bool(s3_raw) and not re.search(r"commit_record|modbus|script\.execute|\.execute\(", s3_raw))
check("on_boot lambda still contains no Modbus access at all",
      "inverter_modbus" not in BOOT and "modbus_client" not in BOOT)
check("durable commit count in on_boot lambda is still zero (boot only loads)",
      "commit_record" not in BOOT)

# ===========================================================================
print("[5] Watchdog: real gate order - lockouts first, then restore_requested")
gate_conds = [norm(c) for c, _ in WD_GATES]
check("watchdog head consists ONLY of `if (...) return ...;` gates (none skipped by the evaluator)",
      WD_HEAD.count(";") == len(WD_GATES), f"{WD_HEAD.count(';')} statements vs {len(WD_GATES)} gates")


def gate_idx(fragment: str) -> int:
    for i, c in enumerate(gate_conds):
        if fragment in c:
            return i
    return -1


i_corrupt = gate_idx("id(free_power_recovery_metadata_corrupt)")
i_busy = gate_idx("id(free_power_operation_in_progress)")
i_req = gate_idx("id(free_power_restore_requested)")
check("metadata_corrupt gate returns false and precedes the restore_requested gate",
      0 <= i_corrupt < i_req and WD_GATES[i_corrupt][1] is False)
check("busy gate precedes the restore_requested gate", 0 <= i_busy < i_req)
check("restore_requested gate returns true", i_req >= 0 and WD_GATES[i_req][1] is True)

# ===========================================================================
print("[6] Watchdog tail (modelled part) matches firmware")
tail = norm(WD_TAIL)
check("tail compares wall clock against end_epoch", "now.is_valid() && id(free_power_end_epoch) != 0" in tail
      and "(uint32_t) now.timestamp >= id(free_power_end_epoch)" in tail)
check("tail falls back to the bounded invalid-clock grace period",
      "millis() >= ${ecco_free_power_invalid_clock_grace_ms}UL" in tail)

# ===========================================================================
print("[7] Reference timeline: active lease -> reboot -> forced restore -> existing restore path")
for clock_valid in (True, False):
    label = "NTP valid" if clock_valid else "NTP not yet valid"
    booted = after_boot(run_boot_load(BOOT, active=1, restore=0, end_epoch=END))
    check(f"[{label}] FIRST watchdog tick (t=15s) fires restore - lease NOT resumed",
          watchdog_fires(booted, clock_valid=clock_valid, now=NOW + 15, millis=15_000))
    pre = after_boot(run_boot_load(BOOT_MUTATED, active=1, restore=0, end_epoch=END))
    resumed_ticks = [t for t in range(15, 3600, 15)
                     if not watchdog_fires(pre, clock_valid=clock_valid, now=NOW + t, millis=t * 1000)]
    check(f"[{label}] MUTATION (S3 excised): lease silently resumes - tests would fail pre-fix",
          len(resumed_ticks) > 0 and resumed_ticks[0] == 15, f"resumed ticks: {len(resumed_ticks)}")

booted = after_boot(run_boot_load(BOOT, active=0, restore=0, end_epoch=END), free_power_active_persisted=False)
check("inactive-but-valid snapshot still restores via the pre-existing !active_persisted gate",
      watchdog_fires(booted, clock_valid=True, now=NOW + 15, millis=15_000))
booted = after_boot(run_boot_load(BOOT, active=1, restore=0, end_epoch=END), free_power_recovery_metadata_corrupt=True)
check("dual-obligation / corrupt lockout still WINS over the S3 restore request (watchdog does not fire)",
      not watchdog_fires(booted, clock_valid=True, now=NOW + 15, millis=15_000))
booted = after_boot(run_boot_load(BOOT, active=1, restore=0, end_epoch=END), free_power_snapshot_valid=False)
check("no snapshot -> watchdog does not fire", not watchdog_fires(booted, clock_valid=True, now=NOW + 15, millis=15_000))

# ===========================================================================
print("[8] Existing restore path / ORIGINAL-INTENDED-NEITHER classifier remains present and reachable")
_text, scripts = _sim.load_scripts(FIRMWARE_PATH)
restore = scripts["restore_free_power_snapshot"]
dispatch_body = _sim.script_body(fw, "restore_free_power_snapshot_dispatch")
restore_body = _sim.script_body(fw, "restore_free_power_snapshot")
check("restore_free_power_snapshot still executes restore_free_power_snapshot_dispatch",
      "id: restore_free_power_snapshot_dispatch" in restore_body)
check("restore_free_power_snapshot's gate does not depend on active_persisted / restore_requested",
      not re.search(r"free_power_(active_persisted|restore_requested)",
                    _sim._strip_code(restore["then"][1]["if"]["condition"]["lambda"])))
check("ORIGINAL leg (live_owned_matches) present", "id(free_power_live_owned_matches) = owned_matches;" in dispatch_body)
check("INTENDED leg (or, since SG-01 Phase 4, a journal-proven SELF_PARTIAL state) gates the restore write",
      "!id(free_power_live_owned_matches) && (id(free_power_live_matches_intended) || id(free_power_live_self_partial));"
      in dispatch_body)
check("NEITHER leg (not SELF_PARTIAL) fails closed into operator lockout",
      "!id(free_power_live_owned_matches) && !id(free_power_live_matches_intended) && !id(free_power_live_self_partial);"
      in dispatch_body
      and "id(free_power_restore_unexplained_drift) = true;" in dispatch_body
      and "retry.operator_needed = 1;" in dispatch_body)
check("classifier dispatch does not branch on restore_requested (S3 cannot bypass classification)",
      "free_power_restore_requested)" not in _sim._strip_code(dispatch_body).replace(
          "id(free_power_restore_requested) = false;", ""))

# ===========================================================================
print("[9] Neighbouring behaviour untouched: PR #41, S4, Dump reboot, normal START")
check("PR #41 Free Power<->Dump arbitration present exactly once",
      fw.count("DUAL DURABLE OBLIGATION (Free Power/Dump, 256-261)") == 1)
check("PR #41 arbitration still sets BOTH lockouts",
      "id(free_power_recovery_metadata_corrupt) = true; id(dump_recovery_metadata_corrupt) = true;" in norm(BOOT))
check("PR #41 arbitration runs AFTER the S3 conversion (its lockout is the final word)",
      0 <= BOOT.find("id(free_power_restore_requested) = true;")
      < BOOT.find("id(free_power_marker_state) == ecco_durable::MARKER_RESTORE_REQUIRED"))
check("S4 (Dump/reg244) arbitration present exactly once", fw.count("DUAL DURABLE OBLIGATION (S4)") == 1)
check("S4 arbitration still sets BOTH lockouts",
      "id(dump_recovery_metadata_corrupt) = true; id(reg244_recovery_metadata_corrupt) = true;" in norm(BOOT))
dump_open = BOOT.index(DUMP_LOAD)
dump_body = BOOT[dump_open: _sim._match_brace(BOOT, BOOT.index("{", dump_open))]
check("Dump reboot behaviour unchanged: active -> dump_restore_requested = true",
      "if (id(dump_active_persisted)) { id(dump_restore_requested) = true;" in norm(dump_body))
check("S3 code does not appear inside the Dump block", "free_power_restore_requested" not in dump_body)
start_body = _sim._strip_code(_sim.script_body(fw, "start_free_power_override"))
check("normal START still clears restore_requested for a new lease",
      "id(free_power_restore_requested) = false;" in start_body)
check("normal START still persists restore_requested from RAM",
      "data.restore_requested = id(free_power_restore_requested) ? 1 : 0;" in start_body)
check("END button still sets restore_requested and durably records it",
      "data.restore_requested = 1;" in _sim._strip_code(fw[fw.index("id: end_free_power_button"):
                                                          fw.index("id: restore_free_power_snapshot", fw.index("id: end_free_power_button"))]))

# ===========================================================================
print("")
if FAILURES:
    print(f"{len(FAILURES)} S3 Free Power reboot-behaviour check(s) FAILED:")
    for name in FAILURES:
        print(f"  - {name}")
else:
    print("All S3 Free Power reboot-behaviour tests PASSED.")
print("")
print("Structural checks plus execution of the REAL extracted boot-load prefix and")
print("watchdog gates via the restricted interpreter; the watchdog's wall-clock tail")
print("is modelled. Not a substitute for on-hardware reboot verification.")

if FAILURES:
    sys.exit(1)
