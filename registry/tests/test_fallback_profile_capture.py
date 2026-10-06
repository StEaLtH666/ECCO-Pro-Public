#!/usr/bin/env python3
"""Offline tests for FB-B1 - "Review Current Configuration": the read-only review of the inverter's
fallback-profile registers. Architecture: docs/architecture/fallback/FINAL_FBB_FBC_ARCHITECTURE.md
section 9 and design/S1_fbb_capture_final.md (13.3 pins and tests, adapted to REVIEW-only).

FB-B1 adds a button, three scripts (gate, capture dispatch, candidate invalidation), one 10 s
housekeeping interval, nine text sensors (B1-B9), 46 `fallback_profile_*` / marker-boot globals, one
appended on_boot lambda (a READ-ONLY boot load of the stored profile / witness / failback record) and
three one-line boot-marker retention assignments. A Review runs a gate, then FOUR distinct FC03 reads
(230/3, 241/53, 230/3, 241/53) under the shared write mutex, compares all 31 registers, and only if
both passes agree builds a RAM-only candidate (TTL 120 000 ms). It has ZERO Modbus writes, ZERO NVS
writes and no authority over the inverter.

THIS SUITE PROVES (P1..P5, each printed with its verdict at the end):

  P1  exactly four added Modbus reads per Review (230/3, 241/53, 230/3, 241/53), none when it
      refuses; the write-surface analyzer sees 64 reads (60 + 4) and 52 writes (unchanged);
  P2  zero Modbus writes, zero NVS / durable writes (no nvs set, no commit_record / load_record*,
      nvs_set_blob only in the FB-B0 adapter), zero inverter authority: generic pins over EVERY FB lambda
      (S-AUTH: only the FB invalidate script is ever executed, only FB globals + the shared mutex are
      modified, no foreign symbol is named outside the pinned gate-input statements) and exactly six
      read-only serial-log call sites (S-LOG);
  P3  the candidate disappears / expires correctly: TTL 120 000 ms by the 10 s housekeeping tick,
      wrap-safe, IE1 / IE3 / IE7 / IE9 / IE11 - driven by injected flags AND by the REAL writer scripts
      (apply_manual_slot1, start_free_power_override; the five writes-fingerprint counters are pinned in
      their writers' accept branches) - and it never survives a reboot or a power cut at ~80 instants;
  P4  a disagreement between the two passes NEVER produces a valid candidate (each of the 31 words
      changed at each of the three gaps between the four reads, AND each word wrong in each single
      one of the four reads; immediate and deferred replies);
  P5  no regression to the other features: the FB code takes / releases `manual_write_in_progress`
      exactly once each, assigns none of the other write paths, no other script / button / interval /
      on_boot line changed except the documented ones, and a Free Power / Dump / Manual TOU start that
      arrives while a review holds the mutex is rejected by its own gate while the review completes.

SECTIONS
  [0] inventory   the entities, scripts, interval, globals, include, boot item and the exact delta vs BASE
  [S] static pins S1 13.3 adapted to REVIEW (each a function returning violation strings, so the
                  mutation matrix can use it as a detector)
  [B] behaviour   the REAL YAML executed through _fbb_harness.FbbSim (T-CAP scenarios incl. a power-cut sweep over ~80
                  instants, the real writer scripts started after / during a review, read-failure matrix, L2 previews,
                  stored-profile interplay, a seeded fuzz); every scenario asserts the safety invariants (no write, no NVS
                  set, no commit, lock released) and EVERY review() call asserts the read list its own outcome implies
                  (a prefix of the four reads; all four when a candidate or preview was built; none when refused)
  [C] compile     every FB lambda syntax-compiled for real (-Wall -Wextra -Werror, gnu++17 + gnu++20)
                  through _fbb1_lambda_compile.py, with negative controls that are real compile rejections
  [M] mutation    deliberately broken copies of the firmware (>= 28 required; the table is MUTANTS), each killed by
                  every detector named for it; every detector is proved green on the real firmware first

The suite is anchored on the firmware AS FB-B1 LEFT IT: the on-disk text with every later chain entry reverted
(`CHAIN.as_of(FIRMWARE, "fbb1", disk)`, an identity while fbb1 is the newest entry), and on the pre-FB-B1 BASE derived from the
chain - `_fbb1_scope.pre_fbb1_firmware(live)`, accepted only if its sha256 is the pinned `_fbb1_scope.BASE_FW_SHA` (a61709c3...,
main @ 4649465 = the chain's fbb0 checkpoint), so the base stays independent of the hunks. NO git and NO subprocess call: the suite
runs in a shallow clone (CI checks out with depth 1) and in a copy of the tree without a .git directory. The next PR that appends
a chain entry does not turn it red.

NOT proven here: ESPHome's real loop timing, the compiled binary, a real hub's timing or a second bus master, IDF NVS
erase / lock behaviour (a Review READ can erase a CRC-damaged NVS entry - that is not an NVS write call), hardware. The
header's own C++ semantics are proved by test_fallback_capture_host_compile.py (the sims here execute the Python mirror).
Only `esphome compile` and the soak can prove the rest.
"""

from __future__ import annotations

import difflib
import hashlib
import random
import re
import sys
import tempfile
import time
from collections import Counter
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))        # registry/: fallback_capture, fallback_durable, fallback_profile
sys.path.insert(0, str(ROOT / "tools"))
import _dump_sim as ds  # noqa: E402
import _fbb_harness as H  # noqa: E402
import _fbb1_engine as E  # noqa: E402
import _fbb1_lambda_compile as LC  # noqa: E402
import _fbb1_scope as scope  # noqa: E402
import _scope_chain as chain  # noqa: E402
import analyze_write_surface as aws  # noqa: E402
import fallback_capture as fc  # noqa: E402
import fallback_durable as fd  # noqa: E402
import fallback_profile as fp  # noqa: E402

FW_REL = chain.FIRMWARE
FW_PATH = ROOT / FW_REL
INCLUDE_DIR = ROOT / "firmware" / "include"
CAP_HEADER = INCLUDE_DIR / "ecco_fallback_capture.h"
CARD_SRC = ROOT / "frontend" / "ecco-energy-actions-card" / "src"

FAILURES: list[str] = []
NCHECKS = [0]
T0 = time.time()


def check(name: str, condition: bool, detail: str = "") -> None:
    NCHECKS[0] += 1
    if condition:
        print(f"  PASS  {name}")
    else:
        FAILURES.append(name)
        print(f"  FAIL  {name}" + (f" - {detail}" if detail else ""))


def _raises(fn, exc=AssertionError) -> bool:
    try:
        fn()
    except exc:
        return True
    return False


# ===========================================================================
# The text under test, and the BASE it is measured against: both CHAIN-derived (no git, no subprocess)
# ===========================================================================
CH = chain.CHAIN
# The firmware as FB-B1 left it: the on-disk text with every LATER chain entry reverted (an identity while fbb1 is the newest
# entry), so a later PR that appends an entry and edits the firmware does not turn this suite red.
LIVE_TEXT = CH.as_of(chain.FIRMWARE, "fbb1", FW_PATH.read_text(encoding="utf-8"))


def base_text(live: str) -> tuple[str | None, str]:
    """The BASE every delta is measured against = the pre-FB-B1 firmware (main @ 4649465, FB-B0): the exact reverter of chain
    entry fbb1 applied to `live`, ACCEPTED ONLY if its sha256 is the pinned `_fbb1_scope.BASE_FW_SHA` (a61709c3..., the chain's
    fbb0 checkpoint). The pinned hash keeps the base independent of the hunks: a wrong hunk cannot fabricate a base that passes.
    -> (text, "") or (None, why); the suite FAILS (never skips) on None. No git, no subprocess."""
    try:
        base = scope.pre_fbb1_firmware(live)
    except AssertionError as ex:
        return None, f"the FB-B1 hunks do not revert out of the firmware: {str(ex)[:200]}"
    got = hashlib.sha256(base.encode("utf-8")).hexdigest()
    if got != scope.BASE_FW_SHA:
        return None, f"the reverted firmware hashes to {got}, not the pinned BASE_FW_SHA {scope.BASE_FW_SHA}"
    return base, ""


BASE_TEXT, BASE_ERR = base_text(LIVE_TEXT)
BASE: dict | None = None  # parsed lazily in main()


# ===========================================================================
# Expected FB-B1 surface (written out independently of the YAML)
# ===========================================================================
TEXT_SENSORS = [  # (name, id, diagnostic)
    ("ECCO Fallback Profile State", "fallback_profile_state_text", False),                  # B1
    ("ECCO Fallback Profile Summary", "fallback_profile_summary_text", True),               # B2
    ("ECCO Fallback Profile Review", "fallback_profile_review_text", False),                # B3
    ("ECCO Fallback Profile Review ID", "fallback_profile_review_id_text", False),          # B4
    ("ECCO Fallback Profile Review Slots", "fallback_profile_review_slots_text", False),    # B5
    ("ECCO Fallback Profile Review Context", "fallback_profile_review_context_text", False),  # B6
    ("ECCO Fallback Profile Slots", "fallback_profile_slots_text", False),                  # B7
    ("ECCO Fallback Profile Context", "fallback_profile_context_text", False),              # B8
    ("ECCO Fallback Profile Last Action-Result", "fallback_profile_last_result_text", False),  # B9
]
TS = {k: t[1] for k, t in zip(("B1", "B2", "B3", "B4", "B5", "B6", "B7", "B8", "B9"), TEXT_SENSORS)}
NINE = frozenset(TS.values())
SHORT = {  # short key -> entity id, used by the behavioural helpers
    "state": TS["B1"], "summary": TS["B2"], "review": TS["B3"], "review_id": TS["B4"], "review_slots": TS["B5"],
    "review_context": TS["B6"], "slots": TS["B7"], "context": TS["B8"], "last_result": TS["B9"],
}
BUTTON_ID = "fallback_profile_review_button"
FB_SCRIPT_IDS = ("fallback_profile_review", "fallback_profile_capture_dispatch", "fallback_profile_invalidate_candidate")
INTERVAL_MARK = "fallback_profile_cand_valid"

_G_U8_255 = "'255'"
EXPECTED_GLOBALS = [  # (id, type, initial_value or None) - CONTRACT section 3 (44) + the two additions the Y engineer declared
    ("free_power_marker_boot_load", "uint8_t", _G_U8_255),
    ("dump_marker_boot_load", "uint8_t", _G_U8_255),
    ("reg244_marker_boot_load", "uint8_t", _G_U8_255),
    ("fallback_profile_boot_loaded", "bool", "'false'"),
    ("fallback_profile_boot_salt", "uint32_t", "'0'"),
    ("fallback_profile_fbs_slot", "uint8_t", "'0'"),
    ("fallback_profile_bytes", "std::array<uint8_t, 96>", None),
    ("fallback_profile_load", "uint8_t", "'4'"),
    ("fallback_profile_class", "uint8_t", "'0'"),
    ("fallback_profile_why", "uint8_t", "'0'"),
    ("fallback_witness_bytes", "std::array<uint8_t, 48>", None),
    ("fallback_witness_load", "uint8_t", "'4'"),
    ("fallback_profile_present_seen", "uint8_t", "'0'"),
    ("fallback_profile_read_anomaly", "uint8_t", "'0'"),
    ("fallback_profile_seen_hw_gen", "uint32_t", "'0'"),
    ("fallback_profile_op_in_progress", "bool", "'false'"),
    ("fallback_profile_op_purpose", "uint8_t", "'0'"),
    ("fallback_profile_op_started_ms", "uint32_t", "'0'"),
    ("fallback_profile_capture_state", "uint8_t", "'0'"),
    ("fallback_profile_gate_accepted", "bool", "'false'"),            # addition 1 (gate -> dispatch hand-over flag)
    ("fallback_profile_step", "uint8_t", "'0'"),
    ("fallback_profile_step_terminal", "bool", "'false'"),
    ("fallback_profile_read_failed", "bool", "'false'"),
    ("fallback_profile_read_fail_code", "uint8_t", "'0'"),
    ("fallback_profile_read_exception_code", "uint8_t", "'0'"),      # addition 2 (the handler's exception code)
    ("fallback_profile_pass1", "std::array<uint16_t, 31>", None),
    ("fallback_profile_pass2", "std::array<uint16_t, 31>", None),
    ("fallback_profile_probe_latch", "uint16_t", "'0'"),
    ("fallback_profile_obl_text", "std::string", "'\"-\"'"),
    ("fallback_profile_invalidate_reason", "std::string", "'\"\"'"),
    ("fallback_profile_cand_valid", "bool", "'false'"),
    ("fallback_profile_cand_saveable", "bool", "'false'"),
    ("fallback_profile_cand_words", "std::array<uint16_t, 31>", None),
    ("fallback_profile_cand_id", "uint64_t", "'0'"),
    ("fallback_profile_cand_ms", "uint32_t", "'0'"),
    ("fallback_profile_cand_seq", "uint32_t", "'0'"),
    ("fallback_profile_cand_prior_class", "uint8_t", "'0'"),
    ("fallback_profile_cand_prior_gen", "uint32_t", "'0'"),
    ("fallback_profile_cand_prior_binding", "uint64_t", "'0'"),
    ("fallback_profile_cand_warnings", "uint16_t", "'0'"),
    ("fallback_profile_cand_writes_fp", "uint32_t", "'0'"),
    ("fallback_profile_cand_sv", "std::string", "'\"\"'"),
    ("fallback_profile_cand_dx", "uint32_t", "'0'"),
    ("fallback_profile_cand_dc", "uint16_t", "'0'"),
    ("fallback_profile_cand_di", "uint8_t", "'0'"),
    ("fallback_profile_cand_has_stored", "bool", "'false'"),
]
OUTCOMES = ("on_response", "on_error", "on_no_response", "on_not_sent", "on_custom_response")
FAIL_CODE = {"on_error": "READ_EXCEPTION", "on_no_response": "READ_NO_RESPONSE", "on_not_sent": "READ_NOT_SENT",
             "on_custom_response": "READ_NONSTANDARD"}
READS = [  # (start, count, store helper, pass buffer) in dispatch order
    (230, 3, "store_block_230", "fallback_profile_pass1"),
    (241, 53, "store_block_241", "fallback_profile_pass1"),
    (230, 3, "store_block_230", "fallback_profile_pass2"),
    (241, 53, "store_block_241", "fallback_profile_pass2"),
]
FULL_READS = [(a, n) for a, n, _s, _b in READS]
IDLE_COND = ("return !id(poll_inverter_configuration_dispatch).is_running() && !id(poll_inverter_telemetry).is_running() && "
             "id(inverter_modbus)->tx_buffer_empty() && !id(inverter_modbus)->tx_blocked();")
WRITE_SYMBOLS = re.compile(
    r"commit_transition|write_one_|make_provision|seal_provision|invalidate_profile|note_committed|mirror_after|nvs_set|set_blob|"
    r"nvs_erase|erase_key|ecco_durable::commit_record|ecco_durable::load_record|\bcommit_record\b|\bload_record\b|"
    r"load_record_status|modbus_client\.write|write_multiple|write_single|create_write|send_raw|queue_command|\.save\s*\(|\bsync\s*\(")
MARKER_TAGS = {"fp": "ecco_free_power_snapshot_valid_v1", "dump": "ecco_dump_to_grid_snapshot_valid_v1",
               "r244": "ecco_reg244_snapshot_valid_v1"}
B9_PREFIXES = ("No Fallback Profile action since boot", "review in progress (read-only)", "CANDIDATE READY",
               "CANDIDATE NOT SAVEABLE", "REVIEW REFUSED", "REVIEW NOT COMPLETED", "REVIEW EXPIRED", "REVIEW CLEARED", "INTERNAL")
# D8 hazard words (case-insensitive) no FB-B1 text may contain / begin with, besides the energy-actions card's own regexes.
D8_HAZARD = [re.compile(p, re.I) for p in (
    r"RECOVERY REQUIRED", r"OPERATOR DECISION REQUIRED", r"RESTORE BLOCKED", r"RECOVERY BLOCKED", r"\bFAILED\b",
    r"VERIFY (ERROR|TIMEOUT|REFUSED)", r"DEFERRED", r"ACCEPT REFUSED", r"Recovery Arm first", r"inverter writes? (are |is )?locked",
    r"deliberate recovery required", r"START FAILED", r"ACTIVATION (VERIFY|WRITE) FAILED", r"press End Free Power",
    r"retry restore", r"snapshot retained", r"^RESTORING", r"^STARTING", r"^ACTIVATION VERIFY")]
OPERATOR_TEXT_TAIL = " - do NOT reboot: a reboot may make the record read as absent"
UNKNOWN_PREFIX = "RECOVERY BLOCKED - durable recovery state UNKNOWN (marker could not be read from NVS at boot)"
OPERATOR_TEXTS = {  # the three reworded SG-06 boot texts (domain -> exact text)
    "dump": UNKNOWN_PREFIX + "; an obligation cannot be ruled out; writes locked, export containment not armed" + OPERATOR_TEXT_TAIL,
    "fp": UNKNOWN_PREFIX + "; an obligation cannot be ruled out; inverter writes locked" + OPERATOR_TEXT_TAIL,
    "r244": UNKNOWN_PREFIX + "; inverter writes locked" + OPERATOR_TEXT_TAIL,
}


# ===========================================================================
# C++ text helpers
# ===========================================================================
def strip_cpp(code: str) -> str:
    """Remove // and /* */ comments, keeping string / character literals intact."""
    out, i, n = [], 0, len(code)
    while i < n:
        c = code[i]
        if c in "\"'":
            j = i + 1
            while j < n and code[j] != c:
                j += 2 if code[j] == "\\" else 1
            out.append(code[i:j + 1])
            i = j + 1
        elif code.startswith("//", i):
            j = code.find("\n", i)
            i = n if j < 0 else j
        elif code.startswith("/*", i):
            j = code.find("*/", i + 2)
            i = n if j < 0 else j + 2
        else:
            out.append(c)
            i += 1
    return "".join(out)


def norm(code: str) -> str:
    """Comment-free, whitespace-collapsed C++ (what an exact-shape pin compares)."""
    return " ".join(strip_cpp(code).split())


def close_of(code: str, i: int) -> int:
    """Index of the bracket closing the one at code[i] (code is comment-stripped)."""
    op = code[i]
    cl = {"(": ")", "{": "}", "[": "]"}[op]
    depth, j, n = 0, i, len(code)
    while j < n:
        c = code[j]
        if c in "\"'":
            j += 1
            while j < n and code[j] != c:
                j += 2 if code[j] == "\\" else 1
        elif c == op:
            depth += 1
        elif c == cl:
            depth -= 1
            if depth == 0:
                return j
        j += 1
    raise ValueError(f"unbalanced {op!r} at {i}")


def block_after(code: str, marker: str) -> tuple[int, int]:
    """(start, end) indexes of the `{ ... }` that `marker` (ending in `{`) opens; ValueError if absent."""
    if code.count(marker) < 1:
        raise ValueError(f"marker not found: {marker[:60]!r}")
    i = code.index(marker) + len(marker) - 1
    return i, close_of(code, i)


ASSIGN = re.compile(r"(?<![\w.])id\(\s*(\w+)\s*\)\s*(?:\[[^\]\n]*\]\s*)?(?:=(?!=)|\+=|-=|\*=|/=|%=|\|=|&=|\^=|<<=|>>=|\+\+|--)")
PREINC = re.compile(r"(?:\+\+|--)\s*id\(\s*(\w+)\s*\)")


def assigned(code: str) -> set[str]:
    code = strip_cpp(code)
    return set(ASSIGN.findall(code)) | set(PREINC.findall(code))


def rhs_of(code: str, name: str) -> list[str]:
    """Normalised right-hand sides of every plain `id(name) = <rhs>;` in the code."""
    return [" ".join(m.group(1).split()) for m in re.finditer(r"id\(\s*%s\s*\)\s*=(?!=)\s*([^;]+);" % re.escape(name), strip_cpp(code))]


def ids_of(code: str) -> set[str]:
    return set(re.findall(r"\bid\(\s*(\w+)\s*\)", strip_cpp(code)))


def publishes(code: str) -> set[str]:
    return set(re.findall(r"\bid\(\s*(\w+)\s*\)\s*\.\s*publish_state\s*\(", strip_cpp(code)))


def literals(code: str) -> list[str]:
    """Every string literal (double quotes) of the comment-free code."""
    return re.findall(r'"((?:[^"\\]|\\.)*)"', strip_cpp(code))


def split_args(text: str) -> list[str]:
    """Top-level comma split of a call's argument text (string / character literals, (), [] and {} respected)."""
    out, cur, depth, i, n = [], [], 0, 0, len(text)
    while i < n:
        ch = text[i]
        if ch in "\"'":
            j = i + 1
            while j < n and text[j] != ch:
                j += 2 if text[j] == "\\" else 1
            cur.append(text[i:j + 1])
            i = j + 1
            continue
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        if ch == "," and depth == 0:
            out.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
        i += 1
    out.append("".join(cur))
    return [a.strip() for a in out]


LOG_RX = re.compile(r"\bESP_LOG([A-Z])\s*\(")


def log_calls(code: str) -> list[dict]:
    """Every ESP_LOG* call of the code (comments stripped): level letter, tag argument, format literal (None if it is not a plain
    literal), the remaining arguments and the [start, end) span in the comment-free text `src`."""
    src = strip_cpp(code)
    out = []
    for m in LOG_RX.finditer(src):
        o = m.end() - 1
        e = close_of(src, o)
        args = split_args(src[o + 1:e])
        fmt = args[1][1:-1] if len(args) > 1 and len(args[1]) >= 2 and args[1][0] == '"' and args[1][-1] == '"' else None
        out.append({"level": m.group(1), "tag": args[0] if args else "", "fmt": fmt, "args": args[2:], "start": m.start(), "end": e + 1, "src": src})
    return out


def lam_of(action) -> str:
    return action["lambda"] if isinstance(action, dict) and isinstance(action.get("lambda"), str) else ""


def kinds_of(actions) -> Counter:
    """Every action kind in an action tree (descending into `if` branches and Modbus reply handlers)."""
    c: Counter = Counter()
    for a in actions or []:
        if not isinstance(a, dict):
            c["<non-dict>"] += 1
            continue
        for k, b in a.items():
            c[k] += 1
            if k == "if" and isinstance(b, dict):
                c.update(kinds_of(b.get("then")))
                c.update(kinds_of(b.get("else")))
            elif k.startswith("modbus_client.") and isinstance(b, dict):
                for oc in OUTCOMES:
                    if oc in b:
                        c.update(kinds_of(b[oc].get("then")))
    return c


def collect_reads(actions, conds=()):
    """The Modbus read nodes of an action tree in document order, each with its neighbours in the same list."""
    res = []
    for i, a in enumerate(actions or []):
        (k, b), = a.items()
        if k == "modbus_client.read_holding_registers":
            res.append({"node": b, "idx": i, "list": actions, "conds": conds,
                        "prev": actions[i - 1] if i else None,
                        "nxt": actions[i + 1] if i + 1 < len(actions) else None,
                        "nxt2": actions[i + 2] if i + 2 < len(actions) else None})
        elif k == "if":
            cond = b["condition"]["lambda"] if isinstance(b["condition"], dict) else str(b["condition"])
            res += collect_reads(b.get("then"), conds + (cond,))
            res += collect_reads(b.get("else"), conds + ("!(" + cond + ")",))
    return res


def paths_of(actions):
    """Every execution path (list of the action objects run, in order) through an action list: an `if` forks into its
    then-branch and its else-branch / skip."""
    res = [[]]
    for a in actions or []:
        (k, b), = a.items()
        if k == "if":
            branches = paths_of(b.get("then")) + paths_of(b.get("else"))
            res = [p + [a] + q for p in res for q in branches]
        else:
            res = [p + [a] for p in res]
    return res


def raw_script_block(text: str, sid: str) -> str:
    """The raw YAML text of one script list item (from `  - id: <sid>` to the next item / top-level key)."""
    m = re.search(r"^  - id: %s\n" % re.escape(sid), text, re.M)
    if not m:
        raise ValueError(f"script {sid} not found in the raw text")
    nxt = re.search(r"^(?:  - id: |\S)", text[m.end():], re.M)
    return text[m.start(): m.end() + (nxt.start() if nxt else len(text))]


def header_structs(text: str) -> dict[str, list[tuple[str, str]]]:
    """name -> [(type, field)] of the POD structs of ecco_fallback_capture.h that matter here."""
    out = {}
    for name in ("BusInputs", "FpDomain", "DumpDomain", "R244Domain", "GateInputs", "ReadInputs", "ReviewInputs"):
        m = re.search(r"struct %s \{(.*?)\n\};" % name, text, re.S)
        if not m:
            raise ValueError(f"struct {name} not found in the header")
        fields = []
        for line in m.group(1).splitlines():
            line = line.split("//")[0].strip()
            fm = re.match(r"^([\w:<>, ]+?)\s+(\w+)\s*(?:=[^;]*|\{[^;]*\})?;$", line)
            if fm:
                fields.append((fm.group(1).strip(), fm.group(2)))
        out[name] = fields
    return out


def flat_fields(structs: dict, name: str, prefix: str = "") -> list[str]:
    res = []
    for typ, field in structs[name]:
        if typ in structs:
            res += flat_fields(structs, typ, f"{prefix}{field}.")
        else:
            res.append(prefix + field)
    return res


def fields_assigned(code: str, var: str) -> set[str]:
    return {m.group(1) for m in re.finditer(r"\b%s\.([A-Za-z_][\w.]*)(?:\[[^\]\n]*\])?\s*=(?!=)" % re.escape(var), strip_cpp(code))}


# ===========================================================================
# The parsed firmware text (live or mutated)
# ===========================================================================
class Ctx:
    """One firmware text, parsed once, with the FB-B1 items located. Locating never raises on a damaged structure
    (a mutant): a detector reports the damage instead."""

    def __init__(self, text: str):
        self.text = text
        self.fw = ds.load_firmware_text(text)
        fw = self.fw
        self.sc = {s["id"]: s for s in fw["script"]}
        self.gate = self.sc.get("fallback_profile_review", {})
        self.disp = self.sc.get("fallback_profile_capture_dispatch", {})
        self.inv = self.sc.get("fallback_profile_invalidate_candidate", {})
        self.gate_then = self.gate.get("then") or []
        self.top = self.disp.get("then") or []
        self.inv_then = self.inv.get("then") or []
        ivs = [iv for iv in fw["interval"] if INTERVAL_MARK in yaml.dump(iv["then"])]
        self.interval = ivs[0] if len(ivs) == 1 else None
        self.n_intervals_marked = len(ivs)
        self.tick = lam_of(self.interval["then"][0]) if self.interval and self.interval.get("then") else ""
        self.boot_then = ((fw.get("esphome") or {}).get("on_boot") or {}).get("then") or []
        self.boot = lam_of(self.boot_then[3]) if len(self.boot_then) > 3 else ""
        self.boot0 = lam_of(self.boot_then[0]) if self.boot_then else ""
        self.gate_lam = lam_of(self.gate_then[0]) if self.gate_then else ""
        self.final = lam_of(self.top[-2]) if len(self.top) >= 2 else ""
        self.release = lam_of(self.top[-1]) if self.top else ""
        self.inv_lam = lam_of(self.inv_then[0]) if self.inv_then else ""
        self.reads = collect_reads(self.top)
        self.button = next((b for b in fw.get("button") or [] if b.get("id") == BUTTON_ID), None)
        self.raw_gate = self._raw("fallback_profile_review")
        self.raw_disp = self._raw("fallback_profile_capture_dispatch")
        self.raw_inv = self._raw("fallback_profile_invalidate_candidate")

    def _raw(self, sid: str) -> str:
        try:
            return raw_script_block(self.text, sid)
        except ValueError:
            return ""

    def fb_lambda_texts(self) -> dict[str, str]:
        """Every FB lambda of the three scripts, the interval and the boot item (generic path names)."""
        return {l.name: l.code for l in LC.lambdas_of(self.fw)}


def det(registry: dict, name: str):
    def deco(fn):
        registry[name] = fn
        return fn
    return deco


STATIC: dict = {}      # name -> fn(ctx) -> list[str]   (violations; empty = pass)
BEHAV: dict = {}       # name -> fn(fw) -> list[str]
LABELS: dict = {}      # name -> human label


def static(name: str, label: str):
    LABELS[name] = label
    return det(STATIC, name)


def behav(name: str, label: str):
    LABELS[name] = label
    return det(BEHAV, name)


# ===========================================================================
# [0] INVENTORY detectors
# ===========================================================================
_analyze_cache: dict = {}


def analyze_text(text: str) -> dict:
    """tools/analyze_write_surface.analyze() over in-memory firmware text (the FB headers are copied next to it)."""
    key = hashlib.sha256(text.encode("utf-8")).hexdigest()
    if key not in _analyze_cache:
        with tempfile.TemporaryDirectory(prefix="fbb1_aws_") as d:
            root = Path(d)
            (root / "include").mkdir()
            for h in INCLUDE_DIR.glob("*.h"):
                (root / "include" / h.name).write_bytes(h.read_bytes())
            p = root / "firmware.yaml"
            p.write_text(text, encoding="utf-8", newline="\n")
            _analyze_cache[key] = aws.analyze(p)
    return _analyze_cache[key]


def _head_violation() -> list[str]:
    return [] if BASE is not None else [f"base firmware text unavailable ({BASE_ERR or 'not parsed'}) - the suite never skips"]


@static("I-BASE", "the pre-FB-B1 base (chain-derived: _fbb1_scope.pre_fbb1_firmware(live), sha256 == the pinned BASE_FW_SHA) exists and parses; every delta is measured against it")
def d_base(c):
    return [] if (BASE_TEXT and BASE is not None) else [f"no base text: {BASE_ERR or 'not parsed'}"]


@static("I-TEXT", "nine template text sensors B1-B9: exact names / ids, update_interval never, no lambda or filter, only B2 diagnostic, appended last")
def d_text_sensors(c):
    v = _head_violation()
    ts = c.fw.get("text_sensor") or []
    mine = [t for t in ts if str(t.get("id", "")).startswith("fallback_profile_")]
    if [(t.get("name"), t.get("id")) for t in mine] != [(n, i) for n, i, _d in TEXT_SENSORS]:
        v.append(f"names/ids {[(t.get('name'), t.get('id')) for t in mine]}")
    for (n, i, diag), t in zip(TEXT_SENSORS, mine):
        want = {"platform": "template", "name": n, "id": i, "update_interval": "never"}
        if diag:
            want["entity_category"] = "diagnostic"
        if t != want:
            v.append(f"{i}: {t} != {want}")
    if BASE is not None:
        if ts[:len(BASE["text_sensor"])] != BASE["text_sensor"] or len(ts) != len(BASE["text_sensor"]) + 9:
            v.append("the nine are not appended after the unchanged BASE text sensors")
    return v


@static("I-BTN", "one template button 'Review Current Configuration' whose on_press is the BLOCK-form script.execute of the gate; appended last")
def d_button(c):
    v = _head_violation()
    want = {"platform": "template", "name": "ECCO Fallback Profile: Review Current Configuration", "id": BUTTON_ID,
            "icon": "mdi:file-search-outline", "on_press": [{"script.execute": {"id": "fallback_profile_review"}}]}
    if c.button != want:
        v.append(f"button {c.button} != {want}")
    if not re.search(r"id: %s\n\s+icon: \"?mdi:file-search-outline\"?\n\s+on_press:\n\s+- script\.execute:\n\s+id: fallback_profile_review\n" % BUTTON_ID, c.text):
        v.append("the button's script.execute is not in block form")
    btns = c.fw.get("button") or []
    if BASE is not None and (btns[:len(BASE["button"])] != BASE["button"] or len(btns) != len(BASE["button"]) + 1 or btns[-1].get("id") != BUTTON_ID):
        v.append("the button is not appended after the unchanged BASE buttons")
    return v


@static("I-SCRIPTS", "exactly three new scripts (gate, dispatch, invalidate), mode single, appended after the 30 unchanged BASE scripts")
def d_scripts(c):
    v = _head_violation()
    sc = c.fw["script"]
    if [s["id"] for s in sc[-3:]] != list(FB_SCRIPT_IDS):
        v.append(f"last three scripts {[s['id'] for s in sc[-3:]]}")
    if any(s.get("mode") != "single" for s in sc[-3:]):
        v.append("a new script is not mode: single")
    if [list(s) for s in sc[-3:]] != [["id", "mode", "then"]] * 3:
        v.append(f"script keys {[list(s) for s in sc[-3:]]}")
    if BASE is not None and (sc[:-3] != BASE["script"] or len(sc) != len(BASE["script"]) + 3):
        v.append("a BASE script changed, moved or was removed")
    if [list(a)[0] for a in c.gate_then] != ["lambda", "if"]:
        v.append(f"gate shape {[list(a)[0] for a in c.gate_then]}")
    if [list(a)[0] for a in c.inv_then] != ["lambda"]:
        v.append(f"invalidate shape {[list(a)[0] for a in c.inv_then]}")
    return v


@static("I-IV", "ONE 10 s housekeeping interval directly after the FP evidence-expiry interval and before the FB-C1 interval; never last")
def d_interval(c):
    v = _head_violation()
    ivs = c.fw["interval"]
    if c.n_intervals_marked != 1 or c.interval is None:
        return v + [f"{c.n_intervals_marked} intervals mention {INTERVAL_MARK}"]
    i = ivs.index(c.interval)
    if c.interval.get("interval") != "10s" or "startup_delay" in c.interval or list(c.interval) != ["interval", "then"]:
        v.append(f"interval keys/period {list(c.interval)} {c.interval.get('interval')}")
    if len(c.interval["then"]) != 1 or list(c.interval["then"][0]) != ["lambda"]:
        v.append("the interval is not exactly one lambda")
    if i == 0 or "free_power_recovery_evidence_valid" not in yaml.dump(ivs[i - 1]["then"]):
        v.append("not directly after the Free Power evidence-expiry interval")
    if i + 1 >= len(ivs) or "failback_shadow" not in yaml.dump(ivs[i + 1]["then"]):
        v.append("not directly before the FB-C1 interval")
    if i == len(ivs) - 1:
        v.append("the housekeeping interval is the LAST interval (the Manual TOU staging tick must stay last)")
    if BASE is not None:
        if ivs[:i] + ivs[i + 1:] != BASE["interval"]:
            v.append("a BASE interval changed, moved or was removed")
        if ivs[-1] != BASE["interval"][-1]:
            v.append("the last interval is no longer BASE's last")
    return v


@static("I-GLOB", "46 new RAM-only globals: the CONTRACT list exactly, all restore_value no, std::array without initial_value, marker boot loads '255'")
def d_globals(c):
    v = _head_violation()
    gl = c.fw["globals"]
    if BASE is None:
        return v
    nh = len(BASE["globals"])
    if gl[:nh] != BASE["globals"]:
        v.append("a BASE global changed, moved or was removed")
    new = gl[nh:]
    got = {g["id"]: g for g in new}
    if len(new) != 46 or len(got) != 46:
        v.append(f"{len(new)} new globals (want 46)")
    want = {i: (t, init) for i, t, init in EXPECTED_GLOBALS}
    if set(got) != set(want):
        v.append(f"global ids differ: missing {sorted(set(want) - set(got))} extra {sorted(set(got) - set(want))}")
    for i, (t, init) in want.items():
        g = got.get(i)
        if g is None:
            continue
        if g.get("type") != t:
            v.append(f"{i}: type {g.get('type')!r} != {t!r}")
        if str(g.get("restore_value")).lower() not in ("no", "false"):
            v.append(f"{i}: restore_value {g.get('restore_value')!r}")
        if init is None:
            if "initial_value" in g:
                v.append(f"{i}: a std::array global must not have an initial_value ({g['initial_value']!r})")
        elif str(g.get("initial_value")) != init.strip("'"):
            v.append(f"{i}: initial_value {g.get('initial_value')!r} != {init}")
        if set(g) - {"id", "type", "restore_value", "initial_value"}:
            v.append(f"{i}: unexpected keys {sorted(g)}")
    for i in ("free_power_marker_boot_load", "dump_marker_boot_load", "reg244_marker_boot_load"):
        g = got.get(i, {})
        if not (g.get("type") == "uint8_t" and str(g.get("initial_value")) == "255"):
            v.append(f"{i}: not a uint8_t with initial 255")
    if [g["id"] for g in new if "supervision" in g["id"]] or [g for g in new if not g["id"].startswith(("fallback_", "free_power_marker_boot", "dump_marker_boot", "reg244_marker_boot"))]:
        v.append("a new global is named supervision* or lacks the fallback_ / marker_boot prefix")
    if sum(1 for g in gl if str(g.get("restore_value")).lower() == "yes") != sum(1 for g in BASE["globals"] if str(g.get("restore_value")).lower() == "yes"):
        v.append("the restore_value: yes set changed")
    return v


@static("I-INC", "esphome.includes gains exactly include/ecco_fallback_capture.h, appended LAST; the file exists")
def d_includes(c):
    v = _head_violation()
    inc = (c.fw.get("esphome") or {}).get("includes") or []
    if BASE is not None and inc != list(BASE["esphome"]["includes"]) + ["include/ecco_fallback_capture.h"]:
        v.append(f"includes {inc[-3:]} (want BASE's + the capture header last)")
    if not CAP_HEADER.is_file():
        v.append("the header is missing on disk")
    return v


@static("I-BOOT", "on_boot has 4 lambda items: items 2-3 unchanged, lambda[0] differs from BASE by exactly the 3 BLK-11 lines + the 3 reworded texts, item 4 is new")
def d_boot_items(c):
    v = _head_violation()
    then = c.boot_then
    if len(then) != 4 or any(list(a) != ["lambda"] for a in then):
        return v + [f"on_boot items {[list(a) for a in then]}"]
    if BASE is None:
        return v
    hb = BASE["esphome"]["on_boot"]
    if (c.fw["esphome"]["on_boot"].get("priority"), len(hb["then"])) != (hb.get("priority"), 3):
        v.append("on_boot priority changed or BASE no longer has 3 items")
    if then[1:3] != hb["then"][1:3]:
        v.append("on_boot items 2-3 changed")
    old = [ln.strip() for ln in strip_cpp(hb["then"][0]["lambda"]).splitlines() if ln.strip()]
    new = [ln.strip() for ln in strip_cpp(then[0]["lambda"]).splitlines() if ln.strip()]
    want_added = {f"id({d}_marker_boot_load) = marker_load;" for d in ("free_power", "dump", "reg244")}
    ops = [o for o in difflib.SequenceMatcher(None, old, new, autojunk=False).get_opcodes() if o[0] != "equal"]
    ins = [new[j1:j2] for tag, _i1, _i2, j1, j2 in ops if tag == "insert"]
    rep = [(old[i1:i2], new[j1:j2]) for tag, i1, i2, j1, j2 in ops if tag == "replace"]
    if sorted(ln for blk in ins for ln in blk) != sorted(want_added) or any(len(b) != 1 for b in ins):
        v.append(f"lambda[0] insertions {ins}")
    if len(rep) != 3 or any(len(a) != 1 or len(b) != 1 or a[0].replace(" - reboot to re-read", OPERATOR_TEXT_TAIL) != b[0] for a, b in rep):
        v.append(f"lambda[0] replacements {rep}")
    if any(tag == "delete" for tag, *_ in ops):
        v.append("lambda[0] lost a line")
    return v


@static("I-DELTA", "counts vs BASE: scripts +3 globals +46 text sensors +9 buttons +1 intervals +1 includes +1; the rest unchanged; the diff is pure insertion except the three reworded texts")
def d_delta(c):
    v = _head_violation()
    if BASE is None:
        return v
    f, h = c.fw, BASE
    got = {"scripts": len(f["script"]), "globals": len(f["globals"]), "text_sensors": len(f["text_sensor"]),
           "buttons": len(f["button"]), "intervals": len(f["interval"]), "includes": len(f["esphome"]["includes"])}
    base = {"scripts": len(h["script"]), "globals": len(h["globals"]), "text_sensors": len(h["text_sensor"]),
            "buttons": len(h["button"]), "intervals": len(h["interval"]), "includes": len(h["esphome"]["includes"])}
    delta = {k: got[k] - base[k] for k in got}
    if delta != {"scripts": 3, "globals": 46, "text_sensors": 9, "buttons": 1, "intervals": 1, "includes": 1}:
        v.append(f"deltas {delta}")
    if (base["scripts"], base["globals"], base["text_sensors"], base["buttons"], base["intervals"], base["includes"]) != (30, 464, 68, 28, 10, 6):
        v.append(f"BASE baseline {base}")
    for sect in ("switch", "number", "select", "sensor", "binary_sensor", "api", "wifi", "ota", "logger", "debug", "_substitutions", "substitutions"):
        if f.get(sect) != h.get(sect):
            v.append(f"section {sect} changed")
    changed = sorted(k for k in set(f) | set(h) if k != "_text" and f.get(k) != h.get(k))
    if changed != sorted(["button", "esphome", "globals", "interval", "script", "text_sensor"]):
        v.append(f"changed sections {changed}")
    es_f = {k: x for k, x in f["esphome"].items() if k not in ("includes", "on_boot")}
    es_h = {k: x for k, x in h["esphome"].items() if k not in ("includes", "on_boot")}
    if es_f != es_h:
        v.append("an esphome: key other than includes / on_boot changed")
    a, b = BASE_TEXT.splitlines(), c.text.splitlines()
    ops = [o for o in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes() if o[0] != "equal"]
    kinds = Counter(o[0] for o in ops)
    if kinds != Counter({"insert": 10, "replace": 3}):
        v.append(f"diff hunks {dict(kinds)} (want 10 insertions + 3 one-line replacements)")
    for tag, i1, i2, j1, j2 in ops:
        if tag == "replace" and not (i2 - i1 == 1 and j2 - j1 == 1 and a[i1].replace(" - reboot to re-read", OPERATOR_TEXT_TAIL) == b[j1]):
            v.append(f"a replaced line is not one of the three 'reboot to re-read' texts: {a[i1][:60]!r}")
    removed = sum(i2 - i1 for tag, i1, i2, j1, j2 in ops if tag in ("replace", "delete"))
    if removed != 3:
        v.append(f"{removed} BASE lines removed (want exactly the 3 reworded texts)")
    return v


@static("I-WS", "write-surface analyzer: reads 60 -> 64 (exactly the four FB reads), writes 52 unchanged, FB paths have no write op and are no writer, no bus finding")
def d_analyzer(c):
    v = _head_violation()
    if BASE is None:
        return v
    old, new = analyze_text(BASE_TEXT), analyze_text(c.text)

    def count(res, kind):
        return sum(1 for p in res["paths"] for o in p.ops if o.kind == kind)
    if (count(old, "read"), count(old, "write")) != (60, 52):
        v.append(f"BASE analyzer baseline {(count(old, 'read'), count(old, 'write'))}")
    if (count(new, "read"), count(new, "write")) != (64, 52):
        v.append(f"analyzer reads/writes {(count(new, 'read'), count(new, 'write'))} (want 64 / 52)")
    by = {p.name: p for p in new["paths"]}
    d = by.get("fallback_profile_capture_dispatch")
    if d is None or [(o.start_address, o.count) for o in d.reads] != FULL_READS or d.writes:
        v.append("dispatch path: reads/writes wrong")
    for name in FB_SCRIPT_IDS + (BUTTON_ID,):
        p = by.get(name)
        if p is not None and p.writes:
            v.append(f"{name} has write ops")
    writers = aws.write_surface(new["paths"])
    if any(n in FB_SCRIPT_IDS or n == BUTTON_ID for names in writers.values() for n in names):
        v.append("an FB path is a writer of some register")
    if new["bus_access_findings"] or new["unknown_extent_writes"]:
        v.append(f"bus findings {new['bus_access_findings']} / unknown-extent writes {new['unknown_extent_writes']}")
    old_ops = {p.name: [(o.kind, o.start_address, o.count) for o in p.ops] for p in old["paths"]}
    new_ops = {p.name: [(o.kind, o.start_address, o.count) for o in p.ops] for p in new["paths"]}
    changed = sorted(k for k in set(old_ops) | set(new_ops) if old_ops.get(k) != new_ops.get(k))
    if changed != ["fallback_profile_capture_dispatch", "fallback_profile_review", "fallback_profile_review_button"]:
        v.append(f"analyzer paths that changed: {changed}")
    return v


# ===========================================================================
# [S] STATIC PINS (S1 13.3 adapted to REVIEW-only). Each returns violation strings.
# ===========================================================================
ALLOWED_KINDS = {
    "gate": {"lambda", "if", "script.execute"},
    "dispatch": {"lambda", "if", "wait_until", "modbus_client.read_holding_registers"},
    "invalidate": {"lambda"},
    "interval": {"lambda"},
    "boot": {"lambda"},
}
GUARD = "if (!id(fallback_profile_op_in_progress) || id(fallback_profile_step) != %d) return; id(fallback_profile_step_terminal) = true;"
IF_COND = "return !id(fallback_profile_read_failed);"
BOUNDED_POST = ("if (!id(fallback_profile_step_terminal)) { id(fallback_profile_read_failed) = true; "
                "id(fallback_profile_read_fail_code) = ecco_fbcap::READ_BOUNDED_WAIT; }")
DISP_INIT = ("id(fallback_profile_step) = 0; id(fallback_profile_step_terminal) = false; id(fallback_profile_read_failed) = false; "
             "id(fallback_profile_read_fail_code) = 0; id(fallback_profile_read_exception_code) = 0; "
             "id(fallback_profile_pass1) = std::array<uint16_t, 31>{}; id(fallback_profile_pass2) = std::array<uint16_t, 31>{};")
IDLE_FOLLOW = ("if (id(poll_inverter_configuration_dispatch).is_running() || id(poll_inverter_telemetry).is_running() || "
               "!id(inverter_modbus)->tx_buffer_empty() || id(inverter_modbus)->tx_blocked()) { "
               "id(fallback_profile_read_failed) = true; id(fallback_profile_read_fail_code) = ecco_fbcap::READ_IDLE_TIMEOUT; }")
RELEASE = ("id(fallback_profile_op_in_progress) = false; id(manual_write_in_progress) = false; id(fallback_profile_step) = 0; "
           "id(fallback_profile_op_purpose) = 0;")
V1_HEAD = "if (id(fallback_profile_op_in_progress) || id(fallback_profile_capture_dispatch).is_running()) {"
COUNTER_IDS = {"manual_write_attempts", "reg244_apply_attempts", "reg244_restore_attempts", "free_power_start_attempts", "dump_start_attempts"}
# S-LIT: the only string literals an FB lambda may hold. The six serial-log FORMAT strings are NOT in this set: they are allowed
# only as the first-format literal of an ESP_LOG* call tagged "fbcap" at its pinned call site (see LOG_SITES / S-LOG).
BASE_LITERALS = frozenset({"-", "", "fbcap"})
LOG_SITES = {  # first-format literal -> (level letter, where it may appear, conversion kind)
    "boot load: profile ld=%u witness ld=%u state ld=%u class=%u why=%u": ("I", "boot", "u"),
    "review accepted: bus idle wait, then four read passes": ("I", "gate-accept", "u"),
    "review refused: code=%u slot=%u": ("I", "gate-refused", "u"),
    "review not completed: read-fail code=%u step=%u after %u ms": ("I", "final-not-built", "u"),
    "review done: eligible=%u built=%u in %u ms": ("I", "final-end", "u"),
    "Review operation state reset by the housekeeping breaker (write lock held: %d)": ("W", "tick-breaker", "d"),
}
LOG_TAG = '"fbcap"'
N_LOG_SITES = len(LOG_SITES)          # 6: boot, the breaker, and the four review log lines (accepted / refused / not completed / done)
FB_GLOBAL_IDS = frozenset(i for i, _t, _n in EXPECTED_GLOBALS if i.startswith(("fallback_profile_", "fallback_witness_")))
MARKER_BOOT_IDS = frozenset({"free_power_marker_boot_load", "dump_marker_boot_load", "reg244_marker_boot_load"})
FB_ENTITY_IDS = frozenset(NINE) | {BUTTON_ID} | frozenset(FB_SCRIPT_IDS)
POLL_SCRIPTS = frozenset({"poll_inverter_configuration_dispatch", "poll_inverter_configuration", "poll_inverter_telemetry"})
# Run by the PRE-EXISTING on_boot lambda[0] (never by FB code - S-AUTH pins that) in the seeded-marker boots: a RAM-only Free Power
# evidence routine, not a writer (the analyzer agrees; main() checks it).
BOOT_RAM_ROUTINES = frozenset({"free_power_recovery_invalidate_evidence"})
# The scripts that WRITE the inverter, by name (the analyzer's own writer set is added at run time): none may ever be executed by FB code.
WRITER_SCRIPTS = frozenset({f"apply_manual_slot{n}" for n in range(1, 7)} | {
    "apply_reg244_settings", "restore_reg244_snapshot", "start_free_power_override", "restore_free_power_snapshot",
    "restore_free_power_snapshot_dispatch", "start_dump_to_grid_override", "restore_dump_to_grid_snapshot", "dump_controller_tick",
    "dump_lockout_containment", "write_inverter_rtc", "request_dump_end", "free_power_recovery_force_restore",
    "free_power_recovery_force_restore_dispatch", "free_power_recovery_accept_current_state",
    "free_power_recovery_accept_current_state_dispatch"})
# The five counters the Review's writes fingerprint (IE11) sums, and the writer scripts whose ACCEPT branch increments each.
WRITER_COUNTERS = {
    "manual_write_attempts": tuple(f"apply_manual_slot{n}" for n in range(1, 7)),
    "reg244_apply_attempts": ("apply_reg244_settings",),
    "reg244_restore_attempts": ("restore_reg244_snapshot",),
    "free_power_start_attempts": ("start_free_power_override",),
    "dump_start_attempts": ("start_dump_to_grid_override",),
}


def want_handler(k: int, oc: str, store: str, buf: str) -> str:
    base = GUARD % k
    if oc == "on_response":
        return (base + f" if (!ecco_fbcap::{store}(id({buf}), values)) {{ id(fallback_profile_read_failed) = true; "
                f"id(fallback_profile_read_fail_code) = ecco_fbcap::READ_SHORT; }}")
    base += f" id(fallback_profile_read_failed) = true; id(fallback_profile_read_fail_code) = ecco_fbcap::{FAIL_CODE[oc]};"
    if oc == "on_error":
        base += " id(fallback_profile_read_exception_code) = (uint8_t) exception_code;"
    return base


def fb_items(c) -> dict:
    """name -> (allowed-kinds key, action list) of every FB-B1 action tree."""
    return {"gate": c.gate_then, "dispatch": c.top, "invalidate": c.inv_then,
            "interval": (c.interval or {}).get("then") or [], "boot": c.boot_then[3:4]}


def all_fb_lambda_code(c) -> dict[str, str]:
    d = {"gate": c.gate_lam, "final": c.final, "release": c.release, "invalidate": c.inv_lam, "tick": c.tick, "boot": c.boot}
    d["gate_reset"] = lam_of(((c.gate_then[1:2] or [{}])[0].get("if") or {}).get("then", [{}])[0]) if len(c.gate_then) > 1 and isinstance(c.gate_then[1], dict) else ""
    d["disp_init"] = lam_of(c.top[0]) if c.top else ""
    d["idle_follow"] = lam_of(c.top[2]) if len(c.top) > 2 else ""
    return d


@static("S-READS", "exactly 4 Modbus reads (230/3, 241/53, 230/3, 241/53) in the dispatch, none anywhere else; ZERO write / bus actions in every FB script, button, interval and boot item")
def d_reads(c):
    v = []
    shapes = [(r["node"].get("modbus_id"), r["node"].get("address"), r["node"].get("start_address"), r["node"].get("count")) for r in c.reads]
    if shapes != [("inverter_modbus", 1, a, n) for a, n in FULL_READS]:
        v.append(f"read shapes {shapes}")
    for r in c.reads:
        extra = set(r["node"]) - {"modbus_id", "address", "start_address", "count", *OUTCOMES}
        if extra:
            v.append(f"read node has extra keys {sorted(extra)}")
    for name, actions in fb_items(c).items():
        kinds = kinds_of(actions)
        bad = sorted(set(kinds) - ALLOWED_KINDS[name])
        if bad:
            v.append(f"{name}: action kinds {bad} are not allowed")
        if name != "dispatch" and kinds.get("modbus_client.read_holding_registers"):
            v.append(f"{name} issues a Modbus read")
        if any(k.startswith(("modbus_client.write", "modbus_controller", "uart", "esp32", "nvs")) for k in kinds):
            v.append(f"{name}: a write / bus action {sorted(k for k in kinds if k.startswith(('modbus_client.write', 'modbus_controller', 'uart')))}")
    if kinds_of(c.top).get("modbus_client.read_holding_registers") != 4:
        v.append("the dispatch does not hold exactly 4 read nodes")
    btn = kinds_of((c.button or {}).get("on_press") or [])
    if set(btn) != {"script.execute"}:
        v.append(f"button on_press kinds {dict(btn)}")
    for sid, code in all_fb_lambda_code(c).items():
        if re.search(r"modbus_client|create_write|write_multiple|write_single|send_raw|queue_command|uart\.write|->write|\.write_|read_holding", strip_cpp(code)):
            v.append(f"{sid} lambda names a bus API")
    return v


@static("S-HANDLERS", "all 5 outcome handlers on each read, each guarded by `op_in_progress && step == K` BEFORE the terminal assignment; exact failure codes and pass buffers")
def d_handlers(c):
    v = []
    if len(c.reads) != 4:
        return [f"{len(c.reads)} read nodes"]
    for k, (r, (a, n, store, buf)) in enumerate(zip(c.reads, READS), 1):
        node = r["node"]
        for oc in OUTCOMES:
            if oc not in node:
                v.append(f"R{k}: handler {oc} missing")
                continue
            then = node[oc].get("then") if isinstance(node[oc], dict) else None
            if not then or len(then) != 1 or list(then[0]) != ["lambda"]:
                v.append(f"R{k}.{oc}: not exactly one lambda")
                continue
            code = norm(then[0]["lambda"])
            want = want_handler(k, oc, store, buf)
            if code != want:
                v.append(f"R{k}.{oc}: {code!r} != {want!r}")
            # the guard must precede the first terminal assignment, and the terminal is assigned exactly once
            gi, ti = code.find("id(fallback_profile_step) != %d) return;" % k), code.find("step_terminal")
            if gi < 0 or ti < 0 or gi > ti or code.count("step_terminal") != 1:
                v.append(f"R{k}.{oc}: terminal flag not set strictly after the step guard")
    return v


@static("S-STEP", "per read: step lambda sets step=K / terminal=false just before it; 3000 ms bounded wait on the terminal flag; post-wait BOUNDED_WAIT lambda; 7000 ms idle wait on the exact 4-term bus-idle predicate")
def d_steps(c):
    v = []
    if len(c.top) != 6 or [list(a)[0] for a in c.top] != ["lambda", "wait_until", "lambda", "if", "lambda", "lambda"]:
        return [f"dispatch shape {[list(a)[0] for a in c.top]}"]
    if norm(lam_of(c.top[0])) != DISP_INIT:
        v.append(f"dispatch init lambda: {norm(lam_of(c.top[0]))!r}")
    w = c.top[1]["wait_until"]
    wc = w["condition"]["lambda"] if isinstance(w.get("condition"), dict) else w.get("condition")
    if norm(str(wc)) != norm(IDLE_COND) or w.get("timeout") != "7000ms":
        v.append(f"idle wait: {wc!r} / {w.get('timeout')!r}")
    if norm(lam_of(c.top[2])) != IDLE_FOLLOW:
        v.append(f"idle follow-up lambda: {norm(lam_of(c.top[2]))!r}")
    for k, r in enumerate(c.reads, 1):
        if norm(lam_of(r["prev"])) != "id(fallback_profile_step) = %d; id(fallback_profile_step_terminal) = false;" % k:
            v.append(f"R{k}: step lambda {norm(lam_of(r['prev']))!r}")
        nw = (r["nxt"] or {}).get("wait_until")
        nwc = nw["condition"]["lambda"] if nw and isinstance(nw.get("condition"), dict) else None
        if not nw or norm(str(nwc)) != "return id(fallback_profile_step_terminal);" or nw.get("timeout") != "3000ms":
            v.append(f"R{k}: bounded wait {nw}")
        if norm(lam_of(r["nxt2"])) != BOUNDED_POST:
            v.append(f"R{k}: post-wait lambda {norm(lam_of(r['nxt2']))!r}")
    return v


@static("S-NEST", "fail-fast nesting: each later read sits inside `if: !read_failed` of the previous one; no else branch anywhere")
def d_nest(c):
    v = []
    if len(c.top) != 6 or list(c.top[3])[0] != "if":
        return ["dispatch has no top-level fail-fast if"]
    level, depth = c.top[3]["if"], 0
    for k in range(1, 5):
        cond = level["condition"]["lambda"] if isinstance(level.get("condition"), dict) else str(level.get("condition"))
        if norm(cond) != IF_COND:
            v.append(f"R{k}: guard condition {cond!r}")
        if "else" in level:
            v.append(f"R{k}: the fail-fast if has an else branch")
        want = ["lambda", "modbus_client.read_holding_registers", "wait_until", "lambda"] + (["if"] if k < 4 else [])
        got = [list(a)[0] for a in level.get("then") or []]
        if got != want:
            v.append(f"R{k}: nested shape {got}")
            break
        if k < 4:
            level = level["then"][4]["if"]
    if len(c.reads) == 4 and [len(r["conds"]) for r in c.reads] != [1, 2, 3, 4]:
        v.append(f"read nesting depths {[len(r['conds']) for r in c.reads]}")
    return v


@static("S-RELEASE", "exactly one release lambda, the LAST dispatch action, reached on EVERY path (path enumeration), exact content; no other lambda in the dispatch assigns the mutex")
def d_release(c):
    v = []
    if not c.top:
        return ["empty dispatch"]
    rel = c.top[-1]
    if "lambda" not in rel or norm(rel["lambda"]) != RELEASE:
        v.append(f"last dispatch action is not the exact release lambda: {str(rel)[:120]}")
    paths = paths_of(c.top)
    if len(paths) != 5:
        v.append(f"{len(paths)} execution paths (want 5: idle timeout, R1..R4 fail-or-finish)")
    for p in paths:
        n = sum(1 for a in p if a is rel)
        if n != 1 or p[-1] is not rel:
            v.append(f"a path reaches the release lambda {n} times / not last")
            break
    sets_false = [i for i, code in enumerate(l.code for l in _dispatch_lams(c)) if re.search(r"id\(manual_write_in_progress\)\s*=", strip_cpp(code))]
    if len(sets_false) != 1:
        v.append(f"{len(sets_false)} dispatch lambdas assign manual_write_in_progress")
    if len(re.findall(r"fallback_profile_op_in_progress\)\s*=", strip_cpp("\n".join(l.code for l in _dispatch_lams(c))))) != 1:
        v.append("op_in_progress is not assigned exactly once in the dispatch")
    return v


def _dispatch_lams(c):
    out: list = []
    LC._walk(c.top, "d", out)
    return out


@static("S-PAIR", "manual_write_in_progress: exactly one `= true` (gate accept) and one `= false` (release) in all FB code, paired with op_in_progress; the breaker never assigns it; op_in_progress has exactly three assignment sites")
def d_pair(c):
    v = []
    code = all_fb_lambda_code(c)
    lams = c.fb_lambda_texts()
    t = [n for n, x in lams.items() if re.search(r"id\(manual_write_in_progress\)\s*=\s*true", strip_cpp(x))]
    f = [n for n, x in lams.items() if re.search(r"id\(manual_write_in_progress\)\s*=\s*false", strip_cpp(x))]
    other = [n for n, x in lams.items() if set(rhs_of(x, "manual_write_in_progress")) - {"true", "false"}
             or re.search(r"id\(manual_write_in_progress\)\s*(?:\+=|-=|\|=|&=|\^=|\+\+|--)", strip_cpp(x))]
    if t != ["fallback_profile_review[0]"] or f != [n for n in lams if n.startswith("fallback_profile_capture_dispatch[")][-1:]:
        v.append(f"mutex true sites {t}, false sites {f}")
    if other:
        v.append(f"mutex assigned some other way in {other}")
    g, rel = strip_cpp(code["gate"]), strip_cpp(code["release"])
    if "id(fallback_profile_op_in_progress) = true;" not in g or "id(fallback_profile_op_in_progress) = false;" not in rel:
        v.append("op_in_progress is not set/cleared in the same lambdas as the mutex")
    if "manual_write_in_progress" in assigned(code["tick"]) or re.search(r"manual_write_in_progress\)\s*=(?!=)", strip_cpp(code["tick"])):
        v.append("the housekeeping tick (breaker) assigns manual_write_in_progress")
    for n in ("final", "invalidate", "boot"):
        if "manual_write_in_progress" in assigned(code[n]):
            v.append(f"{n} assigns manual_write_in_progress")
    sites = re.findall(r"id\(fallback_profile_op_in_progress\)\s*=(?!=)\s*(\w+)", strip_cpp(c.text))
    if sorted(sites) != ["false", "false", "true"]:
        v.append(f"op_in_progress assignment sites over the whole YAML: {sites}")
    where = sorted(k for k, x in lams.items() if "fallback_profile_op_purpose" in assigned(x))
    if where != ["fallback_profile_capture_dispatch[%d]" % (len(c.top) - 1), "fallback_profile_review[0]", "interval[0]"]:
        v.append(f"op_purpose is assigned in {where} (want gate, release, breaker)")
    return v


@static("S-GATE", "the gate is ONE lambda that decides: V1 first and touching nothing, flags / step=0 set ONLY in the accept branch, gate_accepted hand-over, block-form script.execute of the dispatch")
def d_gate(c):
    v = []
    g = strip_cpp(c.gate_lam)
    if not g.strip().startswith(V1_HEAD):
        v.append("V1 (in-flight check) is not the first statement of the gate lambda")
    else:
        i = g.index("{", g.index(V1_HEAD))
        j = close_of(g, i)
        blk = g[i + 1:j]
        if assigned(blk) or publishes(blk) != {TS["B9"]} or not blk.rstrip().endswith("return;") or "refused_in_flight_text()" not in blk:
            v.append("V1 branch does more than publish B9 and return")
        ie3 = "if (id(fallback_profile_cand_valid)) {"
        if ie3 not in g or norm(g[g.index(ie3):close_of(g, g.index(ie3) + len(ie3) - 1) + 1]) != (
                "if (id(fallback_profile_cand_valid)) { id(fallback_profile_invalidate_reason) = ecco_fbcap::REASON_SUPERSEDED; "
                "id(fallback_profile_invalidate_candidate).execute(); }"):
            v.append("IE3 (supersede the old candidate silently) is missing or changed")
        order = [g.find(x) for x in (V1_HEAD, ie3, "random_uint32()", "ecco_fbcap::GateInputs gi{};", "ecco_fbcap::gate_decide(gi, pr)",
                                     "if (r.code == ecco_fbcap::GATE_NEED_PROBE) {", "id(fallback_profile_probe_latch) = r.latch;",
                                     "if (r.code == ecco_fbcap::GATE_ACCEPT) {")]
        if min(order) < 0 or order != sorted(order):
            v.append(f"gate statement order is wrong {order}")
    marker = "if (r.code == ecco_fbcap::GATE_ACCEPT) {"
    try:
        s, e = block_after(g, marker)
    except ValueError:
        return v + ["no accept branch"]
    acc, outside = g[s:e + 1], g[:s] + g[e + 1:]
    flags = {"fallback_profile_op_in_progress", "manual_write_in_progress", "fallback_profile_op_purpose", "fallback_profile_op_started_ms",
             "fallback_profile_step", "fallback_profile_gate_accepted"}
    if not flags <= assigned(acc):
        v.append(f"the accept branch does not set {sorted(flags - assigned(acc))}")
    if flags & assigned(outside):
        v.append(f"flags assigned outside the accept branch: {sorted(flags & assigned(outside))}")
    want = {"fallback_profile_op_in_progress": "true", "manual_write_in_progress": "true", "fallback_profile_op_purpose": "ecco_fbcap::PURPOSE_REVIEW",
            "fallback_profile_op_started_ms": "millis()", "fallback_profile_step": "0", "fallback_profile_capture_state": "ecco_fbcap::CAPTURE_READING",
            "fallback_profile_gate_accepted": "true"}
    for n, rhs in want.items():
        if rhs_of(acc, n) != [rhs]:
            v.append(f"accept branch: {n} = {rhs_of(acc, n)} (want {rhs})")
    if len(c.gate_then) != 2 or list(c.gate_then[1]) != ["if"]:
        return v + ["gate shape"]
    gif = c.gate_then[1]["if"]
    cond = gif["condition"]["lambda"] if isinstance(gif.get("condition"), dict) else str(gif.get("condition"))
    if norm(cond) != "return id(fallback_profile_gate_accepted);" or "else" in gif:
        v.append(f"gate if: {cond!r}")
    th = gif.get("then") or []
    if len(th) != 2 or norm(lam_of(th[0])) != "id(fallback_profile_gate_accepted) = false;" or th[1] != {"script.execute": {"id": "fallback_profile_capture_dispatch"}}:
        v.append(f"gate then {th}")
    if not re.search(r"script\.execute:\n\s+id: fallback_profile_capture_dispatch\n", c.raw_gate) or re.search(r"script\.execute: fallback_profile_capture_dispatch", c.raw_gate):
        v.append("the dispatch is not started with the BLOCK form of script.execute")
    if sorted(rhs_of("\n".join(l.code for l in LC.lambdas_of(c.fw) if l.name.startswith("fallback_profile_review")), "fallback_profile_gate_accepted")) != ["false", "true"]:
        v.append("gate_accepted is not assigned exactly once true (accept) and once false (reset)")
    if publishes(c.gate_lam) != {TS["B3"], TS["B9"]}:
        v.append(f"the gate publishes {sorted(publishes(c.gate_lam))}")
    return v


def _gate_rhs_table() -> dict:
    t = {}
    for f in ("manual_write_in_progress", "correction_in_progress", "verification_pending", "verification_read_active",
              "free_power_operation_in_progress", "free_power_recovery_force_in_progress", "free_power_recovery_accept_in_progress",
              "reg244_apply_in_progress", "dump_operation_in_progress", "fallback_profile_op_in_progress"):
        t["bus." + f] = f"id({f})"
    t["bus.fallback_profile_capture_dispatch_running"] = "id(fallback_profile_capture_dispatch).is_running()"
    t["bus.diag_write_lock_held"] = "id(diag_write_lock_held)"
    t["bus.diag_write_lock_since_ms"] = "id(diag_write_lock_since_ms)"
    t["bus.now_ms"] = "millis()"
    t["boot_loaded"], t["fbs_slot"], t["probe_latch"] = ("id(fallback_profile_boot_loaded)", "id(fallback_profile_fbs_slot)", "id(fallback_profile_probe_latch)")
    for arm in ("free_power_write_enable", "dump_write_enable", "manual_config_write_enable"):
        t[arm] = f"id({arm}).state"
    for f in ("free_power_marker_boot_load", "free_power_recovery_metadata_corrupt", "free_power_snapshot_valid", "free_power_marker_state",
              "free_power_operator_needed", "free_power_active_persisted", "free_power_restore_requested"):
        t["fp." + f] = f"id({f})"
    for f in ("dump_marker_boot_load", "dump_recovery_metadata_corrupt", "dump_containment_state", "dump_snapshot_valid", "dump_marker_state",
              "dump_operator_needed", "dump_active_persisted", "dump_restore_requested"):
        t["dump." + f] = f"id({f})"
    for f in ("reg244_marker_boot_load", "reg244_recovery_metadata_corrupt", "reg244_snapshot_valid", "reg244_marker_state"):
        t["r244." + f] = f"id({f})"
    return t


GATE_RHS = _gate_rhs_table()
FP_OPERATOR = {"free_power_recovery_review", "free_power_recovery_review_dispatch", "free_power_recovery_force_restore",
               "free_power_recovery_force_restore_dispatch", "free_power_recovery_accept_current_state",
               "free_power_recovery_accept_current_state_dispatch"}
RUN_SETS_GATE = {
    "fp.run_start": {"start_free_power_override"},
    "fp.run_restore": {"restore_free_power_snapshot", "restore_free_power_snapshot_dispatch"},
    "fp.run_operator": FP_OPERATOR,
    "dump.run_start": {"start_dump_to_grid_override"},
    "dump.run_restore": {"restore_dump_to_grid_snapshot"},
    "r244.run_apply": {"apply_reg244_settings"},
    "r244.run_restore": {"restore_reg244_snapshot"},
}
RUN_SETS_TICK = dict(RUN_SETS_GATE, **{"fp.run_operator": FP_OPERATOR - {"free_power_recovery_force_restore", "free_power_recovery_force_restore_dispatch"}})


def gi_statements(code: str) -> dict[str, str]:
    return {m.group(1): " ".join(m.group(2).split()) for m in re.finditer(r"\bgi\.([\w.]+)\s*=(?!=)\s*([^;]+);", strip_cpp(code))}


@static("S-GATEIN", "FIELD-ASSIGNMENT COMPLETENESS (review RH0): every header POD field is assigned from the right source in the gate / tick / final / boot lambdas; only `expired` is left unassigned, on purpose")
def d_gate_inputs(c):
    v = []
    hs = header_structs(CAP_HEADER.read_text(encoding="utf-8"))
    gate_fields = flat_fields(hs, "GateInputs")
    for who, code, tick in (("gate", c.gate_lam, False), ("tick", c.tick, True)):
        st = gi_statements(code)
        for fld, rhs in st.items():
            if fld in RUN_SETS_GATE:
                ids = set(re.findall(r"id\((\w+)\)\.is_running\(\)", rhs))
                want = (RUN_SETS_TICK if tick else RUN_SETS_GATE)[fld]
                if not re.fullmatch(r"id\(\w+\)\.is_running\(\)(?: \|\| id\(\w+\)\.is_running\(\))*", rhs) or ids != want:
                    v.append(f"{who}: gi.{fld} = {rhs!r} (want exactly {sorted(want)})")
            elif fld in GATE_RHS:
                if rhs != GATE_RHS[fld]:
                    v.append(f"{who}: gi.{fld} = {rhs!r} (want {GATE_RHS[fld]!r})")
            else:
                v.append(f"{who}: unknown field gi.{fld}")
        if any(x not in gate_fields for x in st):
            v.append(f"{who}: a gi.* field that does not exist in GateInputs")
        need = [f for f in gate_fields if not f.endswith("expired")]
        if tick:   # lease_domain_nonclear() reads the boot flag, the latch, the bus flags and the three domains
            need = [f for f in need if not (f in ("fbs_slot", "free_power_write_enable", "dump_write_enable", "manual_config_write_enable"))]
        missing = [f for f in need if f not in st]
        if missing:
            v.append(f"{who}: GateInputs fields never assigned: {missing}")
        if any(f.endswith("expired") for f in st):
            v.append(f"{who}: `expired` is assigned (REVIEW must not read the clock; it stays unassigned on purpose)")
    ri_fields, rv_fields = [f for _t, f in hs["ReadInputs"]], [f for _t, f in hs["ReviewInputs"]]
    if fields_assigned(c.final, "in") != set(ri_fields):
        v.append(f"final: ReadInputs fields assigned {sorted(fields_assigned(c.final, 'in'))} (want all {ri_fields})")
    if fields_assigned(c.final, "ri") != set(rv_fields):
        v.append(f"final: ReviewInputs fields assigned {sorted(fields_assigned(c.final, 'ri'))} (want all {rv_fields})")
    if fields_assigned(c.boot, "in") != {"p_load", "p", "w_load", "w", "healthy"}:
        v.append(f"boot: ReadInputs fields assigned {sorted(fields_assigned(c.boot, 'in'))} (want exactly p_load p w_load w healthy; baseline_valid stays false)")
    fin = {m.group(1): " ".join(m.group(2).split()) for m in re.finditer(r"\bin\.(\w+)\s*=(?!=)\s*([^;]+);", strip_cpp(c.final))}
    want_in = {"present_seen": "id(fallback_profile_present_seen)", "read_anomaly": "id(fallback_profile_read_anomaly)",
               "seen_hw_gen": "id(fallback_profile_seen_hw_gen)", "baseline_valid": "id(fallback_profile_boot_loaded)",
               "last_p_load": "id(fallback_profile_load)", "last_p_bytes": "id(fallback_profile_bytes)",
               "last_w_load": "id(fallback_witness_load)", "last_w_bytes": "id(fallback_witness_bytes)", "p_load": "lp", "p": "p",
               "w_load": "lw", "w": "w", "healthy": "healthy"}
    if fin != want_in:
        v.append(f"final: ReadInputs sources {fin}")
    ri = {m.group(1): " ".join(m.group(2).split()) for m in re.finditer(r"\bri\.(\w+)\s*=(?!=)\s*([^;]+);", strip_cpp(c.final))}
    want_ri = {"words": "id(fallback_profile_pass2)", "ceiling_w": "${ecco_inverter_tou_power_ceiling_w}", "cls": "e.cls",
               "read_anomaly": "e.latch.read_anomaly", "p_load": "lp", "p": "p", "p_stored_len": "dp.stored_len",
               "salt": "id(fallback_profile_boot_salt)", "seq_next": "id(fallback_profile_cand_seq) + 1"}
    if ri != want_ri:
        v.append(f"final: ReviewInputs sources {ri}")
    return v


@static("S-SALT", "random_uint32 appears only in the gate (the lazy salt), nowhere in any on_boot lambda added by FB-B1, and boot_salt is assigned only there")
def d_salt(c):
    v = []
    lams = c.fb_lambda_texts()
    where = {n: strip_cpp(x).count("random_uint32") for n, x in lams.items() if "random_uint32" in strip_cpp(x)}
    if where != {"fallback_profile_review[0]": 1}:
        v.append(f"random_uint32 in FB lambdas: {where}")
    if "if (id(fallback_profile_boot_salt) == 0) id(fallback_profile_boot_salt) = random_uint32() | 1u;" not in norm(c.gate_lam):
        v.append("the lazy salt statement is missing or changed")
    if "random_uint32" in strip_cpp(c.boot):
        v.append("random_uint32 in the FB boot lambda")
    if BASE_TEXT is not None and strip_cpp(c.text).count("random_uint32") != strip_cpp(BASE_TEXT).count("random_uint32") + 1:
        v.append("random_uint32 occurrence count in the YAML is not BASE + 1")
    if BASE is not None:
        hb = [lam_of(a) for a in BASE["esphome"]["on_boot"]["then"]]
        nb = [lam_of(a) for a in c.boot_then[:3]]
        if [("random_uint32" in strip_cpp(x)) for x in hb] != [("random_uint32" in strip_cpp(x)) for x in nb]:
            v.append("random_uint32 placement among the BASE on_boot lambdas changed")
    sites = [n for n, x in lams.items() if "fallback_profile_boot_salt" in assigned(x)]
    if sites != ["fallback_profile_review[0]"]:
        v.append(f"boot_salt assigned in {sites}")
    if re.findall(r"fallback_profile_boot_salt\)\s*=(?!=)", strip_cpp(c.text)).__len__() != 1:
        v.append("boot_salt is not assigned exactly once over the whole YAML")
    return v


@static("S-NOSUP", "no 'supervision' / NTP / heartbeat token in any FB script, button, interval, boot lambda or global (REVIEW needs neither)")
def d_nosup(c):
    v = []
    items = {"gate": yaml.dump(c.gate), "dispatch": yaml.dump(c.disp), "invalidate": yaml.dump(c.inv), "button": yaml.dump(c.button),
             "interval": yaml.dump(c.interval), "boot": yaml.dump(c.boot_then[3:4])}
    for n, d in items.items():
        for tok in ("supervision", "upervision", "ntp_", "api_client", "heartbeat", "have_valid"):
            if tok in d:
                v.append(f"{n} contains {tok!r}")
    for name, code in c.fb_lambda_texts().items():
        if re.search(r"supervision|ntp_|api_client|heartbeat", strip_cpp(code), re.I):
            v.append(f"{name} reads a supervision / NTP symbol")
    hs = yaml.dump([g for g in c.fw["globals"] if g["id"].startswith("fallback_")])
    if "supervision" in hs:
        v.append("a fallback_profile global mentions supervision")
    return v


@static("S-FINAL", "the review final lambda starts with the integrity check, has NO write-side symbol, publishes only B1-B9, reads no cache / staging / snapshot / other entity state, takes candidate words ONLY from pass2")
def d_final(c):
    v = []
    f = strip_cpp(c.final)
    head = "if (!ecco_fbcap::review_integrity_ok(id(fallback_profile_op_in_progress), id(fallback_profile_op_purpose))) {"
    if not f.strip().startswith(head):
        v.append("the final lambda does not start with the purpose-integrity check")
    else:
        i = f.index("{", f.index(head))
        blk = f[i + 1:close_of(f, i)]
        if "internal_context_text()" not in blk or not blk.rstrip().endswith("return;") or assigned(blk) - {"fallback_profile_capture_state"}:
            v.append("the integrity branch is not 'publish INTERNAL and return'")
    if WRITE_SYMBOLS.search(f) or "ecco_durable::" in f:
        v.append(f"write-side symbol in the final lambda: {WRITE_SYMBOLS.search(f).group(0) if WRITE_SYMBOLS.search(f) else 'ecco_durable::'}")
    if not publishes(c.final) <= NINE or not NINE <= publishes(c.final):
        v.append(f"final publishes {sorted(publishes(c.final))}")
    refs = ids_of(c.final)
    stray = sorted(r for r in refs if not (r.startswith(("fallback_profile_", "fallback_witness_")) or r in COUNTER_IDS))
    if stray:
        v.append(f"the final lambda references {stray}")
    states = set(re.findall(r"\bid\((\w+)\)\.state\b", f))
    if not states <= NINE:
        v.append(f"the final lambda reads entity states {sorted(states - NINE)}")
    if re.search(r"manual_cfg_|staging|snapshot", f):
        v.append("the final lambda mentions a cache / staging / snapshot / foreign-domain token")
    if rhs_of(c.final, "fallback_profile_cand_words") != ["id(fallback_profile_pass2)"]:
        v.append(f"candidate words are not taken only from pass2: {rhs_of(c.final, 'fallback_profile_cand_words')}")
    rest = re.sub(r"ecco_fbcap::first_diff\([^;{]*?\)\s*>=\s*0|ecco_fbcap::pass_mismatch_text\([^;]*?\)", "", f)
    if "pass1" in rest:
        v.append("pass1 is used outside first_diff / pass_mismatch_text in the final lambda")
    if "} else if (ecco_fbcap::first_diff(id(fallback_profile_pass1), id(fallback_profile_pass2)) >= 0) {" not in norm(f):
        v.append("the pass compare is not exactly `else if (first_diff(pass1, pass2) >= 0)` (all 31 words, nothing else in the condition)")
    if "pass_mismatch_text(id(fallback_profile_pass1), id(fallback_profile_pass2))" not in norm(f):
        v.append("the mismatch text is not built from (pass1, pass2) in that order")
    if c.final.count("read_direct_t(") != 2 or c.final.count("nvs_healthy()") != 1:
        v.append("the fresh read is not two read_direct_t calls and ONE nvs_healthy()")
    return v


@static("S-PROBE", "lazy probe order: marker reads only inside the GATE_NEED_PROBE branch (after the RAM legs decided), the latch assigned only from the gate result")
def d_probe(c):
    v = []
    g = strip_cpp(c.gate_lam)
    marker = "if (r.code == ecco_fbcap::GATE_NEED_PROBE) {"
    try:
        s, e = block_after(g, marker)
    except ValueError:
        return ["no NEED_PROBE branch in the gate"]
    blk, outside = g[s:e + 1], g[:s] + g[e + 1:]
    if g.count("read_direct_t(") != 3 or blk.count("read_direct_t(") != 3 or "read_direct_t" in outside:
        v.append("a marker read_direct_t is outside the NEED_PROBE branch")
    if g.count("key_for(") != 3 or any(t not in blk for t in ("FREE_POWER_VALID_TAG", "DUMP_TO_GRID_VALID_TAG", "REG244_VALID_TAG")):
        v.append("the three marker keys are not read inside the branch")
    for cond in ("if (r.probe_fp) {", "if (r.probe_dump) {", "if (r.probe_r244) {"):
        if cond not in blk:
            v.append(f"probe not guarded by {cond}")
    if g.find("ecco_fbcap::gate_decide(gi, pr)") > s or g.count("ecco_fbcap::gate_decide(") != 2 or blk.count("r = ecco_fbcap::gate_decide(gi, pr);") != 1:
        v.append("the RAM-leg decision (first gate_decide) does not precede the probes, or the re-decision is missing")
    if "ecco_fbdurable::EspNvs nvs;" not in blk:
        v.append("the direct reader is not a named EspNvs")
    for n, x in c.fb_lambda_texts().items():
        if not n.startswith("fallback_profile_review[0]") and re.search(r"ecco_durable::(key_for|FREE_POWER|DUMP_TO|REG244)", strip_cpp(x)):
            v.append(f"{n} touches a marker key")
    sites = [(n, rhs_of(x, "fallback_profile_probe_latch")) for n, x in c.fb_lambda_texts().items() if "fallback_profile_probe_latch" in assigned(x)]
    if sites != [("fallback_profile_review[0]", ["r.latch"])]:
        v.append(f"the probe latch is assigned in {sites}")
    if len(re.findall(r"fallback_profile_probe_latch\)\s*=(?!=)", strip_cpp(c.text))) != 1:
        v.append("the probe latch is not assigned exactly once over the whole YAML")
    gl = {x["id"]: x for x in c.fw["globals"]}.get("fallback_profile_probe_latch", {})
    if str(gl.get("initial_value")) != "0":
        v.append("the probe latch's initial value is not 0")
    return v


def _setters(c) -> dict[str, set]:
    flags = ("free_power_operation_in_progress", "free_power_recovery_force_in_progress", "free_power_recovery_accept_in_progress",
             "dump_operation_in_progress", "reg244_apply_in_progress")

    def lams(node):
        out = []
        if isinstance(node, dict):
            for k, x in node.items():
                out += [x] if (k == "lambda" and isinstance(x, str)) else lams(x)
        elif isinstance(node, list):
            for x in node:
                out += lams(x)
        return out
    res = {f: {s["id"] for s in c.fw["script"] if re.search(r"id\(%s\)\s*=\s*true" % f, "\n".join(strip_cpp(x) for x in lams(s)))} for f in flags}
    others = {f: [sect for sect in ("button", "interval", "api", "switch", "number", "select", "sensor", "binary_sensor", "text_sensor", "esphome")
                  if re.search(r"id\(%s\)\s*=\s*true" % f, "\n".join(strip_cpp(x) for x in lams(c.fw.get(sect))))] for f in flags}
    res["_others"] = others
    return res


@static("S-RUN", "each domain's RUN_* script set equals the awk-derived set of its op-flag setters (documented: Dump excludes dump_lockout_containment; the interval omits the Force Restore pair)")
def d_run(c):
    v = []
    s = _setters(c)
    if any(s["_others"].values()):
        v.append(f"a non-script item sets an op flag: {s['_others']}")
    st = {k: set(x) for k, x in s.items() if k != "_others"}
    fp_setters = st["free_power_operation_in_progress"] | st["free_power_recovery_force_in_progress"] | st["free_power_recovery_accept_in_progress"]
    union = lambda *keys: set().union(*(RUN_SETS_GATE[k] for k in keys))  # noqa: E731
    if union("fp.run_start", "fp.run_restore", "fp.run_operator") != fp_setters | {"free_power_recovery_review"}:
        v.append(f"FP RUN set {sorted(union('fp.run_start', 'fp.run_restore', 'fp.run_operator'))} != setters {sorted(fp_setters)} + the review wrapper")
    if "dump_lockout_containment" not in st["dump_operation_in_progress"]:
        v.append("dump_lockout_containment no longer sets the Dump op flag (the documented exclusion is stale)")
    if union("dump.run_start", "dump.run_restore") != st["dump_operation_in_progress"] - {"dump_lockout_containment"}:
        v.append(f"Dump RUN set vs setters {sorted(st['dump_operation_in_progress'])}")
    if union("r244.run_apply", "r244.run_restore") != st["reg244_apply_in_progress"]:
        v.append(f"R244 RUN set vs setters {sorted(st['reg244_apply_in_progress'])}")
    # what the lambdas actually assign (not the table above)
    for who, code, tbl in (("gate", c.gate_lam, RUN_SETS_GATE), ("tick", c.tick, RUN_SETS_TICK)):
        got = {f: set(re.findall(r"id\((\w+)\)\.is_running\(\)", r)) for f, r in gi_statements(code).items() if f in RUN_SETS_GATE}
        if got != tbl:
            v.append(f"{who}: RUN sets {got}")
    if "free_power_recovery_force_restore" in strip_cpp(c.tick):
        v.append("the interval names a Force Restore script (an older suite pins that no interval mentions it)")
    return v


@static("S-IVRAM", "the housekeeping interval is RAM-only (no bus, no NVS, no script.execute, only the invalidate call), breaker never assigns the mutex, IE1 / IE7 / IE11 present in order")
def d_interval_ram(c):
    v = []
    if c.interval is None:
        return ["no housekeeping interval"]
    t = strip_cpp(c.tick)
    n = norm(c.tick)
    if not n.startswith("const uint32_t now = millis();"):
        v.append("the tick does not start with `const uint32_t now = millis();`")
    for tok in ("modbus_client", "read_direct", "EspNvs", "nvs_", "ecco_fbdurable", "ecco_durable", "script.execute", "supervision", "commit", "free_power_recovery_force_restore"):
        if tok in t:
            v.append(f"the tick contains {tok!r}")
    targets = set(re.findall(r"id\((\w+)\)\.execute\(\)", t))
    if targets != {"fallback_profile_invalidate_candidate"}:
        v.append(f"the tick executes {sorted(targets)}")
    if assigned(c.tick) != {"fallback_profile_op_in_progress", "fallback_profile_op_purpose", "fallback_profile_step", "fallback_profile_invalidate_reason"}:
        v.append(f"the tick assigns {sorted(assigned(c.tick))}")
    if publishes(c.tick) != {TS["B3"]}:
        v.append(f"the tick publishes {sorted(publishes(c.tick))}")
    need = ["ecco_fbcap::breaker_fired(id(fallback_profile_op_in_progress), id(fallback_profile_capture_dispatch).is_running(), now, id(fallback_profile_op_started_ms))",
            "const bool lock_held = id(manual_write_in_progress);", "ecco_fbcap::breaker_text(lock_held)",
            "if (id(fallback_profile_cand_valid) && !id(fallback_profile_op_in_progress)) {",
            "if (ecco_fbcap::candidate_expired(now, id(fallback_profile_cand_ms))) {", "ecco_fbcap::review_expired_text()",
            "const uint8_t dom = ecco_fbcap::lease_domain_nonclear(gi);", "if (dom != ecco_fbcap::SLOT_NONE) {", "ecco_fbcap::review_cleared_domain_text(dom)",
            "ecco_fbcap::writes_fingerprint((uint32_t) id(manual_write_attempts), (uint32_t) id(reg244_apply_attempts), "
            "(uint32_t) id(reg244_restore_attempts), (uint32_t) id(free_power_start_attempts), (uint32_t) id(dump_start_attempts)) != id(fallback_profile_cand_writes_fp)) {",
            "ecco_fbcap::review_cleared_writes_text()", "ecco_fbcap::exp_seconds(now, id(fallback_profile_cand_ms))",
            # publish-on-change (CONTRACT 2): the 10 s refresh publishes B3 only when the string differs from .state
            "if (id(fallback_profile_review_text).state != t.c_str()) id(fallback_profile_review_text).publish_state(t.c_str());"]
    pos = []
    for x in need:
        if x not in n:
            v.append(f"the tick lacks {x[:70]!r}")
        pos.append(n.find(x))
    if min(pos) >= 0 and pos != sorted(pos):
        v.append(f"tick statement order {pos}")
    if t.count("publish_state(") != 1:
        v.append(f"the tick publishes {t.count('publish_state(')} times (want exactly the one guarded B3 refresh)")
    brk = n[n.find("ecco_fbcap::breaker_fired("):n.find("if (id(fallback_profile_cand_valid)")] if "ecco_fbcap::breaker_fired(" in n else ""
    if "manual_write_in_progress) =" in brk or brk.count("manual_write_in_progress") != 1:
        v.append("the breaker touches the mutex other than reading it into lock_held")
    if re.search(r"\b(?:120000|130000|110000|30000|300000)\b", t):
        v.append("a literal TTL / breaker constant in the tick (the constants live in the header)")
    return v


@static("S-BOOT", "the appended on_boot lambda: 4th item, ends with `boot_loaded = true;` (assigned nowhere else), publishes all nine entities, only READS, no random / static_assert / supervision")
def d_boot(c):
    v = []
    b = strip_cpp(c.boot).rstrip()
    if not b.endswith("id(fallback_profile_boot_loaded) = true;"):
        v.append("the last statement is not boot_loaded = true")
    if len(re.findall(r"fallback_profile_boot_loaded\)\s*=(?!=)", strip_cpp(c.text))) != 1:
        v.append("boot_loaded is not assigned exactly once over the whole YAML")
    for tok in ("random_uint32", "static_assert", "supervision"):
        if tok in b:
            v.append(f"the boot lambda contains {tok}")
    if publishes(c.boot) != NINE:
        v.append(f"the boot lambda publishes {sorted(publishes(c.boot))} (want all nine)")
    if WRITE_SYMBOLS.search(b) or "ecco_durable::" in b:
        v.append("write-side symbol in the boot lambda")
    if c.boot.count("read_direct_t(") != 3 or c.boot.count("nvs_healthy()") != 1:
        v.append("the boot load is not three read_direct_t (FBP, FBW, FBS) and ONE nvs_healthy()")
    allowed = {"fallback_profile_fbs_slot", "fallback_profile_present_seen", "fallback_profile_read_anomaly", "fallback_profile_seen_hw_gen",
               "fallback_profile_class", "fallback_profile_why", "fallback_profile_load", "fallback_witness_load", "fallback_profile_bytes",
               "fallback_witness_bytes", "fallback_profile_boot_loaded"}
    if assigned(c.boot) != allowed:
        v.append(f"the boot lambda assigns {sorted(assigned(c.boot) ^ allowed)} beyond / below the allowed set")
    if "modbus" in b.lower().replace("inverter_modbus", ""):
        v.append("the boot lambda touches the bus")
    return v


@static("S-BLK11", "BLK-11: three `*_marker_boot_load = marker_load;` lines, each the LAST statement of its marker block in on_boot lambda[0] (hunk-neutral for the SG-06 reverters)")
def d_blk11(c):
    v = []
    code = strip_cpp(c.boot0)
    for dom in ("free_power", "dump", "reg244"):
        line = f"id({dom}_marker_boot_load) = marker_load;"
        if code.count(line) != 1:
            v.append(f"{dom}: {code.count(line)} assignment lines")
            continue
        i = code.index(line)
        tail = code[i + len(line):]
        if not tail.lstrip().startswith("}"):
            v.append(f"{dom}: the line is not the last statement of its block")
            continue
        close = i + len(line) + (len(tail) - len(tail.lstrip()))
        # find the opening brace of that block and check it declares marker_load
        depth, j = 0, close
        while j >= 0:
            if code[j] == "}":
                depth += 1
            elif code[j] == "{":
                depth -= 1
                if depth == 0:
                    break
            j -= 1
        if "uint8_t marker_load" not in code[j:i]:
            v.append(f"{dom}: the enclosing block does not declare marker_load")
    for tok in ("fallback_profile", "ecco_fbcap", "ecco_fbdurable"):
        if tok in code:
            v.append(f"lambda[0] mentions {tok}")
    return v


@static("S-TEXT3", "the three reworded SG-06 'durable recovery state UNKNOWN' texts: exact strings, <= 255 chars, prefix + 'writes locked' kept, no hazard words, no UNKNOWN in the other RECOVERY BLOCKED branches")
def d_text3(c):
    v = []
    lits = re.findall(r'"(RECOVERY BLOCKED - durable recovery state UNKNOWN[^"]*)"', c.text)
    if sorted(lits) != sorted(OPERATOR_TEXTS.values()):
        v.append(f"the UNKNOWN texts found: {[x[-60:] for x in lits]}")
    for l in lits:
        if len(l) > 255:
            v.append(f"text longer than 255 chars ({len(l)})")
        if not l.startswith(UNKNOWN_PREFIX) or ("inverter writes locked" not in l and "writes locked" not in l):
            v.append("prefix / 'writes locked' phrase lost")
        for w in ("failed", "deferred", "press End Free Power", "retry restore", "snapshot retained", "reboot to re-read"):
            if w.lower() in l.lower():
                v.append(f"hazard word {w!r} in {l[:40]!r}")
    for m in re.finditer(r'publish_state\(\s*"(RECOVERY BLOCKED - [^"]*)"', c.text):
        if "UNKNOWN" in m.group(1) and not m.group(1).startswith(UNKNOWN_PREFIX):
            v.append(f"a non-READ_ERROR branch says UNKNOWN: {m.group(1)[:60]!r}")
    if len(re.findall(r'publish_state\(\s*"RECOVERY BLOCKED - durable recovery marker', c.text)) < 3:
        v.append("the non-READ_ERROR boot branches are no longer found (this pin is stale)")
    if "reboot to re-read" in c.text:
        v.append("an old 'reboot to re-read' tail survives")
    return v


@static("S-WRITE", "ZERO write authority: no write-side symbol in any FB lambda; nvs_set_blob only in the FB-B0 adapter; commit_record / load_record / load_record_status counts unchanged from BASE")
def d_write(c):
    v = []
    for n, x in c.fb_lambda_texts().items():
        m = WRITE_SYMBOLS.search(strip_cpp(x))
        if m:
            v.append(f"{n}: {m.group(0)!r}")
    if BASE_TEXT is not None:
        for pat in (r"ecco_durable::commit_record\s*\(", r"ecco_durable::load_record\s*\(", r"ecco_durable::load_record_status\s*\("):
            if len(re.findall(pat, strip_cpp(c.text))) != len(re.findall(pat, strip_cpp(BASE_TEXT))):
                v.append(f"{pat} count changed vs BASE")
        if (len(re.findall(r"ecco_durable::commit_record\s*\(", c.text)), len(re.findall(r"ecco_durable::load_record\s*\(", c.text)),
                len(re.findall(r"ecco_durable::load_record_status\s*\(", c.text))) != (57, 7, 3):
            v.append("durable call-site counts are not 57 / 7 / 3")
        if len(re.findall(r"\bnvs_(?:set|erase|commit)\w*\s*\(", strip_cpp(c.text))) != len(re.findall(r"\bnvs_(?:set|erase|commit)\w*\s*\(", strip_cpp(BASE_TEXT))):
            v.append("an nvs_set / erase / commit call appeared in the YAML")
    sites = {}
    for p in sorted(INCLUDE_DIR.glob("*.h")):
        n = len(re.findall(r"\bnvs_set_blob\s*\(", strip_cpp(p.read_text(encoding="utf-8"))))
        if n:
            sites[p.name] = n
    if sites != {"ecco_fallback_durable.h": 1}:
        v.append(f"nvs_set_blob call sites: {sites} (want only the FB-B0 adapter, once)")
    cap = strip_cpp(CAP_HEADER.read_text(encoding="utf-8"))
    if re.search(r"nvs_|\bcommit_\w+|modbus|supervision|\bid\(|ecco_durable::", cap):
        v.append("the capture header names an NVS / commit / bus / supervision / id() symbol")
    return v


@static("S-LIT", "every string literal in the FB lambdas is on a short allow-list ('-', '', the log tag); a serial-log format string is allowed ONLY as the format literal of an ESP_LOG* call tagged \"fbcap\" (no operator text or new wording hides in the YAML)")
def d_literals(c):
    v = []
    for n, x in c.fb_lambda_texts().items():
        calls = log_calls(x)
        fmts = Counter(k["fmt"] for k in calls if k["tag"] == LOG_TAG and k["fmt"] is not None)
        lits = Counter(literals(x))
        for lit, k in lits.items():
            if lit in BASE_LITERALS:
                continue
            if lit in LOG_SITES and fmts.get(lit, 0) == k:
                continue
            v.append(f"{n}: literal {lit[:60]!r}" + (" (a log format that is not the format literal of an ESP_LOG* call tagged fbcap)" if lit in LOG_SITES else ""))
        if lits.get("fbcap", 0) != sum(1 for k in calls if k["tag"] == LOG_TAG):
            v.append(f"{n}: the literal \"fbcap\" is used other than as the tag of an ESP_LOG* call")
    return v


def _log_conversions(fmt: str) -> list[str]:
    return re.findall(r"%[-+ #0]*\d*(?:hh|h|ll|l|z|j|t)?[A-Za-z%]", fmt)


@static("S-LOG", "serial logging is read-only and pinned to six call sites (boot, breaker, review accepted / refused / not completed / done): tag \"fbcap\", format literal only, %u with (unsigned) casts, none in the handlers / dispatch actions / invalidate / release / the tick beyond the breaker, none carrying id( or ${")
def d_logs(c):
    v = []
    lams = c.fb_lambda_texts()
    if c.text.count(LOG_TAG) != N_LOG_SITES:
        v.append(f"{c.text.count(LOG_TAG)} occurrences of the \"fbcap\" tag in the firmware (want exactly {N_LOG_SITES}: boot, breaker, +4)")
    if BASE_TEXT is not None and BASE_TEXT.count(LOG_TAG) != 0:
        v.append("the base firmware already uses the fbcap log tag")
    where = {c.gate_lam: ["review accepted: bus idle wait, then four read passes", "review refused: code=%u slot=%u"],
             c.final: ["review not completed: read-fail code=%u step=%u after %u ms", "review done: eligible=%u built=%u in %u ms"],
             c.tick: ["Review operation state reset by the housekeeping breaker (write lock held: %d)"],
             c.boot: ["boot load: profile ld=%u witness ld=%u state ld=%u class=%u why=%u"]}
    total = 0
    for n, x in lams.items():
        calls = log_calls(x)
        total += len(calls)
        want = sorted(where.get(x, []))
        got = sorted(k["fmt"] for k in calls if k["fmt"] is not None)
        if got != want or len(calls) != len(want):
            v.append(f"{n}: log calls {[(k['level'], k['tag'], (k['fmt'] or '?')[:36]) for k in calls]} (want {[w[:36] for w in want]})")
        for k in calls:
            fmt = k["fmt"]
            if k["tag"] != LOG_TAG or fmt is None or fmt not in LOG_SITES:
                v.append(f"{n}: an ESP_LOG{k['level']} call that is not tag \"fbcap\" + a pinned format literal: {k['tag']} {(fmt or '?')[:40]!r}")
                continue
            level, _place, kind = LOG_SITES[fmt]
            if k["level"] != level:
                v.append(f"{n}: {fmt[:30]!r} is ESP_LOG{k['level']}, want ESP_LOG{level}")
            if "id(" in fmt or "${" in fmt or "\\" in fmt or not fmt.isascii():
                v.append(f"{n}: the format literal carries id( / ${{ / an escape / a non-ASCII character: {fmt[:50]!r}")
            conv = _log_conversions(fmt)
            if conv != ["%" + kind] * len(conv):
                v.append(f"{n}: {fmt[:30]!r} uses conversions {conv} (only %{kind} is allowed here)")
            cast = "(unsigned)" if kind == "u" else "(int)"
            if len(k["args"]) != len(conv) or not all(a.startswith(cast) for a in k["args"]):
                v.append(f"{n}: {fmt[:30]!r}: {len(k['args'])} arguments for {len(conv)} conversions, each must start with {cast}: {[a[:24] for a in k['args']]}")
    if total != N_LOG_SITES:
        v.append(f"{total} ESP_LOG* calls in the FB lambdas (want exactly {N_LOG_SITES})")
    # ---- the call sites (where each line sits inside its lambda)
    g = strip_cpp(c.gate_lam)
    try:
        s_, e_ = block_after(g, "if (r.code == ecco_fbcap::GATE_ACCEPT) {")
        acc = g[s_:e_ + 1]
        m2 = re.match(r"\s*else\s*\{", g[e_ + 1:])
        if not m2:
            v.append("the gate's accept branch has no else branch")
        else:
            i2 = e_ + 1 + m2.end() - 1
            els = g[i2:close_of(g, i2) + 1]
            if "review accepted: bus idle wait" not in acc or "review refused:" in acc:
                v.append("the 'review accepted' line is not (only) inside the gate's accept branch")
            if "review refused: code=%u slot=%u" not in els or "review accepted:" in els:
                v.append("the 'review refused' line is not (only) inside the gate's refusal (else) branch")
    except ValueError:
        v.append("no accept branch in the gate")
    f = strip_cpp(c.final)
    try:
        s_, e_ = block_after(f, "if (!built) {")
        if "review not completed: read-fail" not in f[s_:e_ + 1] or "review done:" in f[s_:e_ + 1]:
            v.append("the 'review not completed' line is not (only) inside the final lambda's `if (!built)` branch")
    except ValueError:
        v.append("no `if (!built)` branch in the final lambda")
    done = [k for k in log_calls(c.final) if (k["fmt"] or "").startswith("review done:")]
    pub = f.rfind("id(fallback_profile_last_result_text).publish_state(res.c_str());")
    if len(done) != 1 or pub < 0 or done[0]["start"] < pub or f[done[0]["end"]:].strip() != ";":
        v.append("the 'review done' line is not the LAST statement of the final lambda, after the B9 publish")
    t = strip_cpp(c.tick)
    try:
        i = t.index("ecco_fbcap::breaker_fired(")
        i_if = t.rfind("if (", 0, i)
        o_if = t.index("(", i_if)
        e_if = close_of(t, o_if)
        mo = re.match(r"\s*\{", t[e_if + 1:])
        blk_o = e_if + 1 + mo.end() - 1
        blk = t[blk_o:close_of(t, blk_o) + 1]
        ex_ = blk.find("id(fallback_profile_invalidate_candidate).execute();")
        lg = [k for k in log_calls(c.tick) if (k["fmt"] or "").startswith("Review operation state reset")]
        if len(lg) != 1 or "Review operation state reset by the housekeeping breaker" not in blk or ex_ < 0 or blk.find("ESP_LOGW") < ex_:
            v.append("the breaker's log line is not inside the breaker branch, after the invalidate call")
        if t.count("ESP_LOG") != 1:
            v.append(f"the tick holds {t.count('ESP_LOG')} log calls (want exactly the breaker's one)")
    except (ValueError, AttributeError):
        v.append("the breaker branch of the tick was not found")
    bt = strip_cpp(c.boot)
    bl = [k for k in log_calls(c.boot) if (k["fmt"] or "").startswith("boot load:")]
    if len(bl) != 1 or " ".join(bt[bl[0]["end"]:].split()) != "; id(fallback_profile_boot_loaded) = true;":
        v.append("the boot log line is not the statement right before `boot_loaded = true;`")
    return v


@static("S-PUB", "each FB lambda publishes only its own subset of B1-B9 (gate B3+B9; interval B3; invalidate B3-B6+B9; final and boot all nine)")
def d_publish(c):
    v = []
    want = {"gate": {TS["B3"], TS["B9"]}, "tick": {TS["B3"]}, "invalidate": {TS["B3"], TS["B4"], TS["B5"], TS["B6"], TS["B9"]},
            "final": set(NINE), "boot": set(NINE), "release": set(), "disp_init": set(), "idle_follow": set()}
    code = all_fb_lambda_code(c)
    for n, w in want.items():
        if publishes(code[n]) != w:
            v.append(f"{n} publishes {sorted(publishes(code[n]))} (want {sorted(w)})")
    for n, x in c.fb_lambda_texts().items():
        if publishes(x) - NINE:
            v.append(f"{n} publishes a non-B entity {sorted(publishes(x) - NINE)}")
        if re.search(r"\.(turn_on|turn_off|press|make_call|set_level|write_state|toggle)\s*\(", strip_cpp(x)):
            v.append(f"{n} operates a control")
    return v


def _publish_sources(c) -> list[str]:
    """For every `{ TextBuf t = ecco_fbcap::X(...); ... id(E).publish_state(t...) }` block: 'E<-X' (the builder that feeds each entity)."""
    out = []
    for n, x in c.fb_lambda_texts().items():
        s = strip_cpp(x)
        for m in re.finditer(r"\{\s*(?:const char \*|ecco_fbcap::TextBuf )(\w+) = (?:ecco_fbcap::)?(\w+)\(([^;]*?)\);\s*if \(id\((\w+)\)\.state != \1(?:\.c_str\(\))?\)", s):
            out.append(f"{m.group(4)}<-{m.group(2)}")
    return sorted(set(out))


@static("S-BUILDERS", "each entity is fed only by its own builder (B1 epc_name, B2 b2_text, B3 b3_text, B4 b4_text, B5 b5_text, B6 b6_text, B7 b7_text, B8 b8_text): B5/B6 never show a SAVED view, B4 only for a saveable candidate")
def d_builders(c):
    v = []
    want_pairs = {TS["B1"]: {"epc_name"}, TS["B2"]: {"b2_text"}, TS["B3"]: {"b3_text"}, TS["B4"]: {"b4_text"}, TS["B5"]: {"b5_text"},
                  TS["B6"]: {"b6_text"}, TS["B7"]: {"b7_text"}, TS["B8"]: {"b8_text"}}
    got: dict = {}
    for src in _publish_sources(c):
        e, b = src.split("<-")
        got.setdefault(e, set()).add(b)
    for e, b in got.items():
        if e in want_pairs and not b <= want_pairs[e]:
            v.append(f"{e} is fed by {sorted(b)} (want {sorted(want_pairs[e])})")
    if TS["B4"] in got and any("b4_text(true," in norm(x) for x in c.fb_lambda_texts().values()):
        v.append("B4 is built with saveable=true unconditionally")
    fin = norm(c.final)
    if "ecco_fbcap::b4_text(v.eligible, v.id)" not in fin:
        v.append("B4 is not b4_text(v.eligible, v.id) in the final lambda")
    if "ecco_fbcap::b5_text(true, id(fallback_profile_pass2), v.has_stored, v.dx)" not in fin or "ecco_fbcap::b6_text(true, id(fallback_profile_pass2), v.has_stored, v.dc, v.di)" not in fin:
        v.append("B5 / B6 are not the candidate views of pass2 (v=CAND)")
    if re.search(r"b[78]_text", strip_cpp(c.inv_lam)) or re.search(r"b[78]_text", strip_cpp(c.tick)):
        v.append("a saved-view builder is used by the invalidate script / tick")
    for t5 in ("review_slots_text", "review_context_text"):
        for n, x in c.fb_lambda_texts().items():
            for m in re.finditer(r"\{[^{}]*?(b[5-8]_text)[^{}]*?id\(fallback_profile_%s\)\.publish_state" % t5, strip_cpp(x), re.S):
                if (t5 == "review_slots_text" and m.group(1) != "b5_text") or (t5 == "review_context_text" and m.group(1) != "b6_text"):
                    v.append(f"{n}: {t5} fed by {m.group(1)}")
    return v


@static("S-INV", "the invalidate script is RAM-only: guards on op_in_progress first, resets B3 (keeping obl / latch), B4 '-', B5 / B6 NONE, publishes B9 only through the reason guard")
def d_invalidate(c):
    v = []
    n = norm(c.inv_lam)
    if not n.startswith("if (id(fallback_profile_op_in_progress)) return;"):
        v.append("the invalidate script does not refuse to touch anything while a Review runs")
    for tok in ("ecco_fbcap::b3_text(ecco_fbcap::CAPTURE_IDLE, false, 0, 0, 0, id(fallback_profile_obl_text).c_str(), id(fallback_profile_probe_latch), \"-\")",
                "ecco_fbcap::b4_text(false, 0)", "ecco_fbcap::b5_text(false,", "ecco_fbcap::b6_text(false,",
                "if (ecco_fbcap::invalidate_reason_publishes(id(fallback_profile_invalidate_reason).c_str())) {",
                "id(fallback_profile_invalidate_reason) = \"\";", "id(fallback_profile_cand_valid) = false;"):
        if tok not in n:
            v.append(f"the invalidate lambda lacks {tok[:60]!r}")
    if assigned(c.inv_lam) != {"fallback_profile_cand_valid", "fallback_profile_cand_saveable", "fallback_profile_capture_state", "fallback_profile_invalidate_reason"}:
        v.append(f"the invalidate script assigns {sorted(assigned(c.inv_lam))}")
    if WRITE_SYMBOLS.search(strip_cpp(c.inv_lam)) or "modbus" in strip_cpp(c.inv_lam):
        v.append("write-side symbol in the invalidate script")
    return v


MUTATING_CALL = re.compile(r"\bid\(\s*(\w+)\s*\)\s*\.\s*(?:clear|append|push_back|pop_back|emplace_back|assign|resize|reserve|fill|swap|insert|erase|replace)\s*\(")
ADDRESS_OF = re.compile(r"(?<!&)&(?!&)\s*id\(\s*(\w+)\s*\)")
ALGO_CALL = re.compile(r"(?<![\w.>])(?:std::)?(?:fill|fill_n|swap|iter_swap|copy|copy_n|move|memcpy|memmove|memset|strcpy|strncpy|strcat|strncat)\s*\(")
GI_STMT = re.compile(r"\bgi\.[\w.]+\s*=(?!=)\s*[^;]+;")
EXEC_CALL = re.compile(r"\bid\(\s*(\w+)\s*\)\s*\.\s*execute\s*\(")


def assigned_ext(code: str) -> set[str]:
    """Every global a lambda can MODIFY: plain / compound assignment and ++/-- (`assigned`), a mutating member call
    (`id(x).clear()`, `.append`, ...), an address-of (`&id(x)`) and an algorithm that names it (`std::fill(id(x)...)`)."""
    src = strip_cpp(code)
    out = set(assigned(src)) | set(MUTATING_CALL.findall(src)) | set(ADDRESS_OF.findall(src))
    for m in ALGO_CALL.finditer(src):
        out |= set(re.findall(r"\bid\(\s*(\w+)\s*\)", src[m.end():close_of(src, m.end() - 1)]))
    return out


def script_exec_targets(actions) -> list[str]:
    """Every `script.execute:` ACTION in an action tree (descending into `if` branches and Modbus reply handlers)."""
    out = []
    for a in actions or []:
        if not isinstance(a, dict):
            continue
        for k, b in a.items():
            if k == "script.execute":
                out.append(b.get("id") if isinstance(b, dict) else b)
            elif k == "if" and isinstance(b, dict):
                out += script_exec_targets(b.get("then")) + script_exec_targets(b.get("else"))
            elif k.startswith("modbus_client.") and isinstance(b, dict):
                for oc in OUTCOMES:
                    if oc in b and isinstance(b[oc], dict):
                        out += script_exec_targets(b[oc].get("then"))
    return out


def _lambda_roles(c) -> dict[str, str]:
    """name -> role of every FB lambda that may name a foreign symbol outside the pinned gate-input statements."""
    roles = {}
    for n, x in c.fb_lambda_texts().items():
        if x and x == c.gate_lam:
            roles[n] = "gate"
        elif x and x == c.tick:
            roles[n] = "tick"
        elif x and x == c.final:
            roles[n] = "final"
        elif x and x == c.release:
            roles[n] = "release"
        elif n.startswith("fallback_profile_capture_dispatch[") and (n.endswith("[1].wait") or n.endswith("[2]")):
            roles[n] = "idle"
    return roles


FOREIGN_OK = {   # role -> the foreign (non-FB) ids a lambda may name OUTSIDE the `gi.* = ...;` statements S-GATEIN pins one by one
    "gate": {"manual_write_in_progress"},
    "tick": {"manual_write_in_progress"} | COUNTER_IDS,
    "final": set(COUNTER_IDS),
    "release": {"manual_write_in_progress"},
    "idle": {"inverter_modbus", "poll_inverter_configuration_dispatch", "poll_inverter_telemetry"},
}


@static("S-AUTH", "generic ZERO-AUTHORITY pins over EVERY FB lambda: only fallback_profile_invalidate_candidate is ever .execute()d (the dispatch / gate only by the script.execute action), only FB globals (+ the shared mutex in the gate accept branch and the release) are modified, no foreign symbol is named outside the pinned input statements")
def d_authority(c):
    v = []
    lams = c.fb_lambda_texts()
    roles = _lambda_roles(c)
    # ---- (a) .execute() targets
    for n, x in lams.items():
        src = strip_cpp(x)
        targets = set(EXEC_CALL.findall(src))
        if not targets <= {"fallback_profile_invalidate_candidate"}:
            v.append(f"{n}: executes {sorted(targets - {'fallback_profile_invalidate_candidate'})} (only fallback_profile_invalidate_candidate may be .execute()d)")
        if len(re.findall(r"\.\s*execute\s*\(", src)) != len(EXEC_CALL.findall(src)):
            v.append(f"{n}: an .execute() call that is not `id(<script>).execute()`")
        if re.search(r"\.\s*(?:stop|abort|terminate)\s*\(|esp_restart|\bApp\.|global_preferences|make_preference|esp_ota|esp_deep_sleep|\.reboot\s*\(|\brestart\s*\(", src):
            v.append(f"{n}: stops a script, reboots or touches the preference store")
    acts = {"gate": script_exec_targets(c.gate_then), "dispatch": script_exec_targets(c.top), "invalidate": script_exec_targets(c.inv_then),
            "interval": script_exec_targets((c.interval or {}).get("then")), "boot": script_exec_targets(c.boot_then[3:4]),
            "button": script_exec_targets((c.button or {}).get("on_press"))}
    want = {"gate": ["fallback_profile_capture_dispatch"], "dispatch": [], "invalidate": [], "interval": [], "boot": [], "button": ["fallback_profile_review"]}
    if acts != want:
        v.append(f"script.execute actions {acts} (want {want}: the dispatch is started only by the gate, the gate only by the button)")
    # ---- (b) every global a lambda can modify is an FB global (+ the shared mutex in exactly two places)
    for n, x in lams.items():
        stray = assigned_ext(x) - FB_GLOBAL_IDS - ({"manual_write_in_progress"} if roles.get(n) in ("gate", "release") else set())
        if stray:
            v.append(f"{n}: modifies the foreign global(s) {sorted(stray)}")
    g = strip_cpp(c.gate_lam)
    try:
        s_, e_ = block_after(g, "if (r.code == ecco_fbcap::GATE_ACCEPT) {")
        outside = g[:s_] + g[e_ + 1:]
        if "manual_write_in_progress" in assigned(outside) or rhs_of(g[s_:e_ + 1], "manual_write_in_progress") != ["true"]:
            v.append("manual_write_in_progress is not assigned `true` exactly once, inside the gate's accept branch only")
    except ValueError:
        v.append("no accept branch in the gate")
    if rhs_of(c.release, "manual_write_in_progress") != ["false"]:
        v.append("the release lambda does not assign manual_write_in_progress = false exactly once")
    for n, x in lams.items():
        if roles.get(n) not in ("gate", "release") and "manual_write_in_progress" in assigned_ext(x):
            v.append(f"{n} modifies manual_write_in_progress")
    if BASE is not None:
        base_boot0 = lam_of(BASE["esphome"]["on_boot"]["then"][0])
        if assigned(c.boot0) - assigned(base_boot0) != MARKER_BOOT_IDS:
            v.append(f"on_boot lambda[0] gains assignments {sorted(assigned(c.boot0) - assigned(base_boot0))} (want exactly the three *_marker_boot_load retention globals)")
    # ---- (b2) no foreign symbol is NAMED outside the pinned `gi.* = ...;` input statements, except a short per-role read list
    for n, x in lams.items():
        rest = GI_STMT.sub("", strip_cpp(x))
        extra = ids_of(rest) - FB_GLOBAL_IDS - FB_ENTITY_IDS - FOREIGN_OK.get(roles.get(n), set())
        if extra:
            v.append(f"{n}: names the foreign symbol(s) {sorted(extra)} outside the pinned gate-input statements")
    return v


def _lambdas_in(node) -> list[str]:
    out = []
    if isinstance(node, dict):
        for k, x in node.items():
            out += [x] if (k == "lambda" and isinstance(x, str)) else _lambdas_in(x)
    elif isinstance(node, list):
        for x in node:
            out += _lambdas_in(x)
    return out


@static("S-WRCNT", "IE11 can fire: each of the five writes-fingerprint counters is incremented, exactly once, in the FIRST lambda of the ACCEPT branch of its named writer scripts (apply_manual_slot1-6, apply_reg244_settings, restore_reg244_snapshot, start_free_power_override, start_dump_to_grid_override) and nowhere else")
def d_writer_counters(c):
    v = []
    sc = {s_["id"]: s_ for s_ in c.fw["script"]}
    for ctr, names in WRITER_COUNTERS.items():
        inc = re.compile(r"(?<![\w.])id\(\s*%s\s*\)\s*\+\+|\+\+\s*id\(\s*%s\s*\)" % (ctr, ctr))
        sites = {sid: sum(len(inc.findall(strip_cpp(x))) for x in _lambdas_in(sc_)) for sid, sc_ in sc.items()}
        sites = {k: n for k, n in sites.items() if n}
        if sites != {name: 1 for name in names}:
            v.append(f"{ctr} is incremented in {sites} (want exactly one increment in each of {list(names)})")
        for sect in ("button", "interval", "api", "switch", "number", "select", "binary_sensor", "text_sensor", "esphome"):
            if any(inc.search(strip_cpp(x)) for x in _lambdas_in(c.fw.get(sect))):
                v.append(f"{ctr} is incremented in a {sect}")
        for name in names:
            script = sc.get(name)
            if script is None:
                v.append(f"{name}: writer script not found")
                continue
            ifs = [a["if"] for a in script.get("then") or [] if isinstance(a, dict) and "if" in a]
            first = ifs[0] if ifs else None
            then = (first or {}).get("then") or []
            if not then or "lambda" not in then[0] or not inc.search(strip_cpp(then[0]["lambda"])):
                v.append(f"{name}: {ctr} is not incremented in the first lambda of the accept branch (the then: of its first top-level `if`)")
    return v


# ===========================================================================
# [B] BEHAVIOUR: the REAL YAML through FbbSim
# ===========================================================================
ALL_SIMS: list = []          # every simulator built for the REAL firmware (T-CAP-23 and the string sweeps read it)
_SINK = [ALL_SIMS]
GOLD_FIELDS = dict(magic=fp.PROFILE_MAGIC, schema=1, size=96, generation=7, captured_epoch=1790000000, flags=0, reg244=2,
                   reg256_261=[8000, 500, 4000, 3000, 2000, 1000], reg268_273=[100, 20, 0, 50, 100, 30], reg274_279=[1, 0, 1, 0, 0, 1],
                   reg232=0x0011, reg243=1, reg248=1, reg250_255=[0, 530, 1000, 1600, 2100, 2330], reg230=185, reg245=8000, reg247=1,
                   reserved0=0, reserved1=0, binding=0)


def gold_profile(**over) -> dict:
    return fp.seal_profile(fp.blank_profile(**{**GOLD_FIELDS, **over}))


GOLD = gold_profile()
GWORDS = fc.words_of(GOLD)
GOLD_ID_BINDING = GOLD["binding"]
K_P, K_W, K_S = fd.FALLBACK_PROFILE_KEY, fd.FAILBACK_PROVISION_KEY, fd.FAILBACK_STATE_KEY
CLASS = {0: "UNREADABLE", 1: "NOT_CAPTURED", 2: "CORRUPT", 3: "CORRUPT_DOMAIN", 4: "INVALIDATED", 5: "VALID", 6: "PROFILE_LOST",
         7: "SAVE_UNCONFIRMED", 8: "PROFILE_STALE"}
SAVED_B7 = ("v=SAVED;g=7;244=2;1=0000/8000/100/1;2=0530/500/20/0;3=1000/4000/0/1;4=1600/3000/50/0;5=2100/2000/100/0;6=2330/1000/30/1;"
            "dx=-;b=D852A4FA")
SAVED_B8 = "v=SAVED;232=0011;243=1;248=0001;ring=OK;230=185;245=8000;247=0001;dc=-;di=-;b=D852A4FA"
NONE_B5 = "v=NONE;g=-;244=-;1=-;2=-;3=-;4=-;5=-;6=-;dx=-"
NONE_B6 = "v=NONE;232=-;243=-;248=-;ring=-;230=-;245=-;247=-;dc=-;di=-"
NONE_B7 = "v=NONE;g=-;244=-;1=-;2=-;3=-;4=-;5=-;6=-;dx=-;b=-"
NONE_B8 = "v=NONE;232=-;243=-;248=-;ring=-;230=-;245=-;247=-;dc=-;di=-;b=-"
IDLE_B3 = "st=IDLE;prior=-;exp=-;warn=-;obl=-;latch=-;sv=-"
SEED_B9 = "No Fallback Profile action since boot"
ALL_CLEAR_OBL = "FP:CA,DP:CA,R4:CA,MT:CN,FS:CA,BUS:OK"
# FB-B2 (D8): a Save exists now, so the FB-B1 "values are shown for review only; expires in 120 s" wording was false; the live header
# (ecco_fbcap::candidate_ready_text, mirrored in registry/fallback_capture.py) now says to check the values and arm and save within 120 s.
READY_B9 = "CANDIDATE READY - both read passes agree on all 31 registers; check the values, then arm and save within 120 s"
INFLIGHT_B9 = "REVIEW REFUSED - another Fallback Profile operation is in progress"
ARMS = ("free_power_write_enable", "dump_write_enable", "manual_config_write_enable")
DOMAINS = (("fp", "FP", "Free Power", "free_power"), ("dump", "DP", "Dump to Grid", "dump"), ("r244", "R4", "Register 244 test", "reg244"))
_S = r"(?:\d{4,5}/\d+/\d+/\d+|-)"   # `%04u`: four digits, five for a word above 9999 (an out-of-range register is still printed)
_NAMES = "|".join(CLASS.values())
_OBL = r"(?:FP:[A-Z]{2},DP:[A-Z]{2},R4:[A-Z]{2},MT:[A-Z]{2},FS:[A-Z]{2},BUS:[A-Z]{2}|-)"
RX = {
    "state": re.compile(rf"(?:{_NAMES})"),
    "summary": re.compile(r"g=(?:\d+|-);id=(?:[0-9A-F]{16}|-);at=(?:\d+|-);ld=(?:OK|ABS|WSZ|RERR|UNAV);df=(?:MAGIC|SCHEMA|SIZE|BINDING|RESERVED|FLAGS|GEN|DOMAIN|-);"
                          r"w=(?:OK|LAG|MISS|CORR|UNR|ABS);hw=(?:\d+|-);op=(?:SAVE|INV|RC|-);why=(?:-|INT|RBK|MIS|SUP|LAG|MISS|CORR|PRD|WRD|ANOM|FIRST|LWC);werr=-;us=-"),
    "review": re.compile(rf"st=(?:IDLE|READING|CANDIDATE_READY|CANDIDATE_NOT_SAVEABLE);prior=(?:{_NAMES}|-);exp=(?:\d{{1,3}}|-);warn=(?:-|W[1-6](?:,W[1-6])*);"
                         rf"obl={_OBL};latch=(?:-|(?:FP|DP|R4)(?:,(?:FP|DP|R4))*);sv=(?:-|OK|NO:[A-Z0-9]+(?:,[A-Z0-9]+){{0,2}}(?:\+\d+)?)"),
    "review_id": re.compile(r"(?:-|[0-9A-F]{16})"),
    "review_slots": re.compile(rf"v=(?:CAND|NONE);g=-;244=(?:\d+|-);1={_S};2={_S};3={_S};4={_S};5={_S};6={_S};dx=(?:[0-9A-F]{{5}}|-)"),
    "review_context": re.compile(r"v=(?:CAND|NONE);232=(?:[0-9A-F]{4}|-);243=(?:\d+|-);248=(?:[0-9A-F]{4}|-);ring=(?:OK|BAD|-);230=(?:\d+|-);245=(?:\d+|-);"
                                 r"247=(?:[0-9A-F]{4}|-);dc=(?:[0-9A-F]{3}|-);di=(?:[0-9A-F]{2}|-)"),
    "slots": re.compile(rf"v=(?:SAVED|NONE);g=(?:\d+|-);244=(?:\d+|-);1={_S};2={_S};3={_S};4={_S};5={_S};6={_S};dx=-;b=(?:[0-9A-F]{{8}}|-)"),
    "context": re.compile(r"v=(?:SAVED|NONE);232=(?:[0-9A-F]{4}|-);243=(?:\d+|-);248=(?:[0-9A-F]{4}|-);ring=(?:OK|BAD|-);230=(?:\d+|-);245=(?:\d+|-);"
                          r"247=(?:[0-9A-F]{4}|-);dc=-;di=-;b=(?:[0-9A-F]{8}|-)"),
}
GRAMMAR_CHARSET = re.compile(r"[A-Za-z0-9_.,:/>+=;-]*")
CAPTURE_STATE_NAME = {0: "IDLE", 1: "READING", 2: "CANDIDATE_READY", 3: "CANDIDATE_NOT_SAVEABLE"}


def bank_for(words) -> dict:
    b = {a: 0 for a in range(230, 294)}
    for k, r in enumerate(fc.REGS):
        b[r] = words[k]
    return b


def prov_bytes(hw, hwb, pg, op=fd.PROV_OP_SAVE) -> bytes:
    return fd.pack_provision(fd.make_provision(hw, hwb, pg, 0x6666, K_P, 1, op))


def _seed_valid(sim):
    sim.nvs_direct.put(K_P, fp.pack_profile(GOLD))
    sim.nvs_direct.put(K_W, prov_bytes(7, GOLD["binding"], 6))


def _seed_invalidated(sim):
    inv = fp.invalidate_profile(GOLD)
    sim.nvs_direct.put(K_P, fp.pack_profile(inv))
    sim.nvs_direct.put(K_W, prov_bytes(8, inv["binding"], 7, fd.PROV_OP_INVALIDATE))


def _seed_unreadable(sim):
    sim.nvs_direct.put(K_P, fp.pack_profile(GOLD))
    sim.nvs_direct.read_faults[K_P] = [fd.IDF_FAIL, fd.IDF_FAIL]   # the boot read AND the review's fresh read fail


SEEDS = {
    "none": lambda sim: None,
    "valid": _seed_valid,
    "invalidated": _seed_invalidated,
    "corrupt": lambda sim: sim.nvs_direct.put(K_P, bytes(range(96))),
    "wsize": lambda sim: sim.nvs_direct.put(K_P, bytes(40)),
    "corrupt_domain": lambda sim: sim.nvs_direct.put(K_P, fp.pack_profile(gold_profile(reg244=7))),
    "unreadable": _seed_unreadable,
    "lost": lambda sim: sim.nvs_direct.put(K_W, prov_bytes(7, GOLD["binding"], 6)),
    "stale": lambda sim: (sim.nvs_direct.put(K_P, fp.pack_profile(gold_profile(generation=5))), sim.nvs_direct.put(K_W, prov_bytes(7, GOLD["binding"], 6))),
    "lag": lambda sim: (sim.nvs_direct.put(K_P, fp.pack_profile(GOLD)), sim.nvs_direct.put(K_W, prov_bytes(6, 0x1111, 5))),
}


def mk_sim(fw, *, seed="valid", words=None, markers=(), fail_tags=(), boot=True, salt=True, pre=None, mode=None, fbs=None):
    """A booted FbbSim over `fw`. markers: (domain, state, seed_marker kwargs). The register bank holds `words` (default: the
    golden profile). `salt` pins the review salt to 1 (random_values = [0] after the boot)."""
    sim = H.FbbSim(fw)
    _SINK[0].append(sim)
    if fail_tags:
        sim.nvs_fail_load_tags = set(fail_tags)
    for dom, state, kw in markers:
        sim.seed_marker(MARKER_TAGS[dom], state, **kw)
    SEEDS[seed](sim)
    if fbs is not None:
        fbs(sim)
    if pre:
        pre(sim)
    if boot:
        sim.run_boot()
    if salt:
        sim.random_values = [0]
    sim.bank.update(bank_for(GWORDS if words is None else words))
    if mode:
        sim.set_modbus_mode(*mode)
    return sim


def txt(sim, which: str) -> str:
    return str(sim.ent(SHORT[which]).state)


def obl_of(sim) -> str:
    return txt(sim, "review").split("obl=")[1].split(";")[0]


def latch_of(sim) -> str:
    return txt(sim, "review").split("latch=")[1].split(";")[0]


def press(sim):
    return sim.press_button(BUTTON_ID)


def review_read_errors(sim, sn) -> list[str]:
    """The read-only contract of ONE review, whatever its outcome: no Modbus write / NVS set / commit / record change, the reads
    are a PREFIX of the four (a review is fail-fast), all four when a candidate or a preview was built, none when it was refused."""
    errs = list(sn.violations())
    reads = sn.reads
    if reads != FULL_READS[:len(reads)]:
        errs.append(f"reads {reads} are not a prefix of {FULL_READS}")
    b9 = txt(sim, "last_result")
    if b9.startswith("CANDIDATE") and reads != FULL_READS:
        errs.append(f"a candidate was built from reads {reads}")
    if b9.startswith("REVIEW REFUSED") and reads:
        errs.append(f"a refused review issued reads {reads}")
    return errs


def review(sim):
    """Press Review and run to idle. EVERY call asserts the read-only contract of its own outcome (review_read_errors): a violation
    raises, which a detector reports as a failure (so every scenario that runs a review checks the exact read list it implies)."""
    m = sim.mark()
    press(sim)
    sim.run_until_idle()
    sn = sim.since(m)
    errs = review_read_errors(sim, sn)
    if errs:
        raise AssertionError("review(): " + "; ".join(errs))
    return sn


def key_of(dom: str) -> str:
    return fd.decimal_key(fp.tag_key_fnv1_32(MARKER_TAGS[dom]))


def marker_gets(sn, dom: str) -> int:
    return sum(1 for o in sn.nvs_ops if o[0] == "get" and o[1] == key_of(dom))


class Exp:
    """Accumulates the failed expectations of one scenario."""

    def __init__(self, tag: str = ""):
        self.fails: list[str] = []
        self.n = 0
        self.tag = tag

    def ok(self, cond, msg: str):
        self.n += 1
        if not cond:
            self.fails.append(f"{self.tag}{msg}")

    def eq(self, got, want, msg: str):
        self.n += 1
        if got != want:
            self.fails.append(f"{self.tag}{msg}: got {got!r}, want {want!r}")

    def starts(self, got, prefix, msg: str):
        self.n += 1
        if not str(got).startswith(prefix):
            self.fails.append(f"{self.tag}{msg}: {str(got)[:110]!r} does not start with {prefix[:60]!r}")

    def has(self, got, needle, msg: str):
        self.n += 1
        if needle not in str(got):
            self.fails.append(f"{self.tag}{msg}: {str(got)[:130]!r} lacks {needle!r}")


def text_errors(sim) -> list[str]:
    """Grammar, length, charset, B9-prefix and capture_state consistency of every string any FB entity ever published."""
    errs = []
    for key, eid in SHORT.items():
        for s in [str(x) for x in sim.ent(eid).published]:
            if len(s) > 200:
                errs.append(f"{key}: {len(s)} chars")
            if key == "last_result":
                if not s.startswith(B9_PREFIXES):
                    errs.append(f"B9 prefix: {s[:70]!r}")
            else:
                if not RX[key].fullmatch(s):
                    errs.append(f"{key}: grammar {s[:100]!r}")
                if " " in s or not GRAMMAR_CHARSET.fullmatch(s):
                    errs.append(f"{key}: space / charset {s[:80]!r}")
    return errs


def consistency_errors(sim) -> list[str]:
    g = sim.g
    errs = []
    st = g["fallback_profile_capture_state"]
    b3 = txt(sim, "review")
    if not b3.startswith(f"st={CAPTURE_STATE_NAME[st]};"):
        errs.append(f"B3 {b3[:40]!r} vs capture_state {st}")
    cv = g["fallback_profile_cand_valid"]
    if st != 1 and cv != (st in (2, 3)):
        errs.append(f"cand_valid {cv} vs capture_state {st}")
    if cv:
        if not (txt(sim, "review_slots").startswith("v=CAND;") and txt(sim, "review_context").startswith("v=CAND;")):
            errs.append("B5/B6 are not the candidate views while a candidate exists")
    elif st != 1:
        if not (txt(sim, "review_slots") == NONE_B5 and txt(sim, "review_context") == NONE_B6 and txt(sim, "review_id") == "-"):
            errs.append("B4 / B5 / B6 are not cleared without a candidate")
    b4 = txt(sim, "review_id")
    if st != 1 and (st == 2) != (b4 != "-" and len(b4) == 16):
        errs.append(f"B4 {b4!r} vs capture_state {st}")
    if st == 3 and b4 != "-":
        errs.append("a not-saveable preview shows a candidate id")
    if not txt(sim, "review_slots").startswith(("v=CAND;", "v=NONE;")) or not txt(sim, "review_context").startswith(("v=CAND;", "v=NONE;")):
        errs.append("B5 / B6 carry a SAVED view")
    if not txt(sim, "slots").startswith(("v=SAVED;", "v=NONE;")) or not txt(sim, "context").startswith(("v=SAVED;", "v=NONE;")):
        errs.append("B7 / B8 carry a candidate view")
    # the RAM mirror of the last durable read (class / load / why) always agrees with what B1 / B2 last showed
    if txt(sim, "state"):
        m = re.search(r"ld=(\w+);.*why=([\w-]+);", txt(sim, "summary") + ";")
        if str(fc.epc_name(g["fallback_profile_class"])) != txt(sim, "state"):
            errs.append(f"mirror class {g['fallback_profile_class']} vs B1 {txt(sim, 'state')}")
        if not m or str(fc.ld_name(g["fallback_profile_load"])) != m.group(1) or str(fc.why_name(g["fallback_profile_why"])) != m.group(2):
            errs.append(f"mirror load/why {g['fallback_profile_load']}/{g['fallback_profile_why']} vs B2 {txt(sim, 'summary')[:80]}")
    return errs


def safety_errors(sim) -> list[str]:
    errs = []
    if [x for x in sim.modbus_log if x[0] == "write"]:
        errs.append("a Modbus WRITE was issued")
    if sim.nvs_direct.set_count():
        errs.append("a direct NVS set was issued")
    if sim.nvs_commits:
        errs.append("an ecco_durable commit was issued")
    return errs


def idle_errors(sim, locked: bool = False) -> list[str]:
    g = sim.g
    errs = []
    if g["fallback_profile_op_in_progress"] or g["fallback_profile_step"] != 0 or g["fallback_profile_gate_accepted"] or g["fallback_profile_op_purpose"] != 0:
        errs.append("a Review is still marked in progress / step != 0 at idle: " + str({k: g[k] for k in (
            "fallback_profile_op_in_progress", "fallback_profile_step", "fallback_profile_gate_accepted", "fallback_profile_op_purpose")}))
    if g["manual_write_in_progress"] and not locked:
        errs.append("manual_write_in_progress is still held at idle")
    if "fallback_profile_capture_dispatch" in sim.running or "fallback_profile_review" in sim.running:
        errs.append("an FB script is still running at idle")
    return errs


def invariants(sim, ex: Exp, tag: str, *, locked: bool = False, idle: bool = True):
    for e in safety_errors(sim) + text_errors(sim) + consistency_errors(sim) + (idle_errors(sim, locked) if idle else []):
        ex.ok(False, f"{tag}: invariant: {e}")
    ex.n += 1


def refused(ex: Exp, sim, sn, tag: str, *, probes: int | None = None, prefix: str = "REVIEW REFUSED - ", locked: bool = False):
    ex.starts(txt(sim, "last_result"), prefix, f"{tag}: B9")
    ex.eq(sn.violations(reads=[]), [], f"{tag}: zero reads, no write / nvs set / commit")
    if probes is not None:
        ex.eq(len(sn.nvs_read_probes), probes, f"{tag}: NVS probes")
    ex.ok(sim.g["fallback_profile_op_in_progress"] is False and (locked or sim.g["manual_write_in_progress"] is False), f"{tag}: no lock taken")
    ex.starts(txt(sim, "review"), "st=IDLE;", f"{tag}: B3")
    invariants(sim, ex, tag, locked=locked)


# --------------------------------------------------------------------------- boot
@behav("B-BOOT", "boot: every B1 class via seeded NVS (B1 / B2 / B7 / B8 / B3-B6 / B9 values), every entity published once, boot_loaded true, nothing written")
def sc_boot(fw):
    ex = Exp()
    cases = {  # seed -> (B1, B2 exact or substrings, B7 exact or v=, B8 v=)
        "none": ("NOT_CAPTURED", "g=-;id=-;at=-;ld=ABS;df=-;w=ABS;hw=-;op=-;why=-;werr=-;us=-", NONE_B7, NONE_B8),
        "valid": ("VALID", "g=7;id=D852A4FA2DF7DBA3;at=1790000000;ld=OK;df=-;w=OK;hw=7;op=SAVE;why=-;werr=-;us=-", SAVED_B7, SAVED_B8),
        "invalidated": ("INVALIDATED", None, None, None),
        "corrupt": ("CORRUPT", "g=-;id=-;at=-;ld=OK;df=MAGIC;w=ABS;hw=-;op=-;why=-;werr=-;us=-", NONE_B7, NONE_B8),
        "wsize": ("CORRUPT", "g=-;id=-;at=-;ld=WSZ;df=-;w=ABS;hw=-;op=-;why=-;werr=-;us=-", NONE_B7, NONE_B8),
        "corrupt_domain": ("CORRUPT_DOMAIN", None, None, None),
        "unreadable": ("UNREADABLE", "g=-;id=-;at=-;ld=RERR;df=-;w=ABS;hw=-;op=-;why=PRD;werr=-;us=-", NONE_B7, NONE_B8),
        "lost": ("PROFILE_LOST", "g=-;id=-;at=-;ld=ABS;df=-;w=OK;hw=7;op=SAVE;why=-;werr=-;us=-", NONE_B7, NONE_B8),
        "stale": ("PROFILE_STALE", None, None, None),
        "lag": ("VALID", "g=7;id=D852A4FA2DF7DBA3;at=1790000000;ld=OK;df=-;w=LAG;hw=6;op=SAVE;why=LAG;werr=-;us=-", SAVED_B7, SAVED_B8),
    }
    for seed, (b1, b2, b7, b8) in cases.items():
        sim = mk_sim(fw, seed=seed)
        t = f"boot {seed}"
        ex.eq(txt(sim, "state"), b1, f"{t}: B1")
        if b2:
            ex.eq(txt(sim, "summary"), b2, f"{t}: B2")
        if b7:
            ex.eq(txt(sim, "slots"), b7, f"{t}: B7")
            ex.eq(txt(sim, "context"), b8, f"{t}: B8")
        ex.eq(txt(sim, "review"), IDLE_B3, f"{t}: B3 idle form")
        ex.eq((txt(sim, "review_id"), txt(sim, "review_slots"), txt(sim, "review_context")), ("-", NONE_B5, NONE_B6), f"{t}: B4/B5/B6 empty")
        ex.eq(txt(sim, "last_result"), SEED_B9, f"{t}: B9 seed")
        ex.eq([len(sim.ent(e).published) for e in NINE], [1] * 9, f"{t}: every entity published exactly once at boot")
        ex.ok(sim.g["fallback_profile_boot_loaded"] is True, f"{t}: boot_loaded")
        ex.ok(sim.g["fallback_profile_op_in_progress"] is False and sim.g["manual_write_in_progress"] is False, f"{t}: no lock at boot")
        invariants(sim, ex, t)
    s = mk_sim(fw, seed="invalidated")
    ex.has(txt(s, "summary"), "g=8;", "invalidated: B2 g=8")
    ex.has(txt(s, "summary"), "op=INV;", "invalidated: B2 op=INV")
    ex.starts(txt(s, "slots"), "v=SAVED;g=8;", "invalidated: B7 saved view of the invalidated record")
    s = mk_sim(fw, seed="corrupt_domain")
    ex.has(txt(s, "summary"), "df=DOMAIN;", "corrupt_domain: B2 df=DOMAIN")
    ex.starts(txt(s, "slots"), "v=SAVED;g=7;244=7;", "corrupt_domain: B7 shows the authentic-but-out-of-domain record")
    s = mk_sim(fw, seed="stale")
    ex.has(txt(s, "summary"), "g=5;", "stale: B2 g=5")
    ex.has(txt(s, "summary"), "hw=7;op=SAVE;why=RBK", "stale: B2 hw=7 why=RBK")
    ex.starts(txt(s, "slots"), "v=SAVED;g=5;", "stale: B7")
    s = mk_sim(fw, seed="none", pre=lambda sim: setattr(sim.nvs_direct, "unavailable", True))
    ex.eq(txt(s, "state"), "UNREADABLE", "storage unavailable: B1 UNREADABLE")
    ex.has(txt(s, "summary"), "ld=UNAV;", "storage unavailable: B2 ld=UNAV")
    # the three marker boot loads are retained (0 OK, 1 ABSENT, 2 WRONG_SIZE, 3 READ_ERROR) and the SG-06 flags agree
    for dom, short, label, pre in DOMAINS:
        g_load, g_corrupt = f"{pre}_marker_boot_load", f"{pre}_recovery_metadata_corrupt"
        s0 = mk_sim(fw)
        ex.eq(s0.g[g_load], 1, f"{dom}: marker boot load ABSENT = 1")
        s = mk_sim(fw, markers=[(dom, 0, {})])
        ex.eq((s.g[g_load], s.g[g_corrupt]), (0, False), f"{dom}: marker boot load OK = 0, flag clear")
        s = mk_sim(fw, fail_tags=[MARKER_TAGS[dom]])
        ex.eq((s.g[g_load], s.g[g_corrupt]), (3, True), f"{dom}: marker boot load READ_ERROR = 3, lockout flag set")
        s = mk_sim(fw, pre=lambda sim, t=MARKER_TAGS[dom]: sim.nvs.__setitem__(t, ds.Record("_WrongSizeBlob")))
        ex.eq(s.g[g_load], 2, f"{dom}: marker boot load WRONG_SIZE = 2")
        ex.ok(s.g[g_corrupt] is True, f"{dom}: WRONG_SIZE marker -> lockout flag set")
    s = H.FbbSim(fw)
    _SINK[0].append(s)
    ex.eq((s.g["free_power_marker_boot_load"], s.g["dump_marker_boot_load"], s.g["reg244_marker_boot_load"], s.g["fallback_profile_boot_loaded"]),
          (255, 255, 255, False), "before the boot lambdas run: marker loads 255 (not loaded), boot_loaded false")
    # boot_loaded is assigned exactly once, and only after all nine entities were published (the gate refuses until then)
    orig, seen = s.set_global, []

    def wrap(name, value):
        if name == "fallback_profile_boot_loaded":
            seen.append([len(s.ent(e).published) for e in sorted(NINE)])
        return orig(name, value)
    s.set_global = wrap
    s.run_boot()
    ex.eq(seen, [[1] * 9], "boot_loaded is assigned once, after every one of the nine entities was published")
    return ex.fails


# --------------------------------------------------------------------------- happy path, golden id
@behav("B-HAPPY", "happy path (P1): exactly the four reads in order, candidate READY, texts / ids / masks exact, mutex released, nothing written, no NVS set")
def sc_happy(fw):
    ex = Exp()
    sim = mk_sim(fw)
    sn = review(sim)
    ex.eq(sn.violations(reads=FULL_READS), [], "reads exactly [230/3, 241/53, 230/3, 241/53]; no write / nvs set / commit")
    ex.eq(sn.reads_by("fallback_profile_"), FULL_READS, "every one of the four reads is issued by the dispatch script")
    ex.eq(txt(sim, "review"), f"st=CANDIDATE_READY;prior=VALID;exp=120;warn=-;obl={ALL_CLEAR_OBL};latch=-;sv=OK", "B3")
    want_id = "%016X" % fc.candidate_id(1, 1, 5, 7, GOLD_ID_BINDING, GWORDS)
    ex.eq((txt(sim, "review_id"), len(txt(sim, "review_id"))), (want_id, 16), "B4 = candidate_id(salt 1, seq 1, VALID, g 7, binding, words)")
    ex.eq(txt(sim, "review_slots"), "v=CAND;g=-;244=2;1=0000/8000/100/1;2=0530/500/20/0;3=1000/4000/0/1;4=1600/3000/50/0;5=2100/2000/100/0;6=2330/1000/30/1;dx=00000", "B5")
    ex.eq(txt(sim, "review_context"), "v=CAND;232=0011;243=1;248=0001;ring=OK;230=185;245=8000;247=0001;dc=000;di=00", "B6")
    ex.eq(txt(sim, "last_result"), READY_B9, "B9")
    ex.eq((txt(sim, "slots"), txt(sim, "context"), txt(sim, "state")), (SAVED_B7, SAVED_B8, "VALID"), "B7 / B8 / B1 unchanged by a review of an unchanged profile")
    ex.eq([len(sim.ent(e).published) for e in (TS["B1"], TS["B2"], TS["B7"], TS["B8"])], [1, 1, 1, 1], "B1 / B2 / B7 / B8 were not re-published (publish on change)")
    g = sim.g
    ex.ok(g["fallback_profile_cand_valid"] and g["fallback_profile_cand_saveable"] and g["fallback_profile_capture_state"] == 2, "candidate valid + saveable, READY")
    ex.eq((g["fallback_profile_boot_salt"], g["fallback_profile_cand_seq"], g["fallback_profile_cand_prior_class"], g["fallback_profile_cand_prior_gen"]),
          (1, 1, 5, 7), "salt 1, seq 1, prior class VALID, prior generation 7")
    ex.eq(list(g["fallback_profile_cand_words"]), list(GWORDS), "candidate words are the register words")
    ex.eq((g["fallback_profile_cand_id"], g["fallback_profile_cand_prior_binding"], g["fallback_profile_cand_sv"], g["fallback_profile_cand_warnings"]),
          (int(want_id, 16), GOLD_ID_BINDING, "OK", 0), "candidate globals: id, prior binding, sv, warnings")
    ex.eq((g["fallback_profile_cand_dx"], g["fallback_profile_cand_dc"], g["fallback_profile_cand_di"], g["fallback_profile_cand_has_stored"]),
          (0, 0, 0, True), "candidate globals: dx / dc / di meaningful (a TRUSTED stored profile) and zero for identical words")
    ex.eq(g["fallback_profile_cand_ms"], sim.now_ms, "cand_ms is the millis() of the final step (the review took zero virtual ms)")
    ex.eq(len(sn.nvs_read_probes), 5, "NVS reads: 3 marker probes (all absent) + the fresh FBP + FBW read, nothing else")
    ex.eq(sn.nvs_sets, [], "no NVS set")
    ex.ok(sim.g["fallback_profile_cand_writes_fp"] == 0, "writes fingerprint 0 at rest")
    invariants(sim, ex, "happy")
    # deferred mode gives the same result and the 4 frames leave the bus in order with no foreign frame
    sim = mk_sim(fw, mode=("deferred", 120))
    sn = review(sim)
    ex.eq(sn.violations(reads=FULL_READS), [], "deferred: exactly the four reads")
    ex.eq([(w.addr, w.count, w.origin) for w in sn.wire if w.kind == "read"], [(a, n, "fw") for a, n in FULL_READS], "deferred: four firmware frames on the wire, nothing else")
    ex.eq(txt(sim, "review_id"), want_id, "deferred: same candidate id")
    invariants(sim, ex, "happy deferred")
    # a second review supersedes: new sequence number, new id, no stale outcome text in between
    sn = review(sim)
    ex.eq(sn.violations(reads=FULL_READS), [], "second review: exactly four reads again")
    ex.ok(txt(sim, "review_id") != want_id and sim.g["fallback_profile_cand_seq"] == 2, "second review: new sequence number and a different id")
    ex.eq(txt(sim, "review_id"), "%016X" % fc.candidate_id(1, 2, 5, 7, GOLD_ID_BINDING, GWORDS), "second review: id for seq 2")
    return ex.fails


@behav("B-GOLD", "golden candidate id 1D63D8CBC6CB4D55 (salt 1, seq 1, NOT_CAPTURED, prior g 0 binding 0, golden words); ids differ across reviews and across salts")
def sc_gold(fw):
    ex = Exp()
    sim = mk_sim(fw, seed="none")
    review(sim)
    ex.eq(txt(sim, "review_id"), "1D63D8CBC6CB4D55", "golden candidate id")
    ex.starts(txt(sim, "review"), "st=CANDIDATE_READY;prior=NOT_CAPTURED;exp=120;", "B3 prior=NOT_CAPTURED")
    ex.eq((sim.g["fallback_profile_cand_prior_gen"], sim.g["fallback_profile_cand_prior_binding"]), (0, 0), "prior fingerprint (0, 0)")
    ids = {txt(sim, "review_id")}
    for n in range(2, 5):
        review(sim)
        ids.add(txt(sim, "review_id"))
    ex.eq(len(ids), 4, "ids differ across reviews (sequence number is bound)")
    for rv, salt in ((0, 1), (2, 3), (6, 7), (0xFFFFFFFE, 0xFFFFFFFF)):
        s = mk_sim(fw, seed="none", salt=False)
        s.random_values = [rv]
        review(s)
        ex.eq(txt(s, "review_id"), "%016X" % fc.candidate_id(salt, 1, 1, 0, 0, GWORDS), f"salt {salt}: candidate id")
        ex.eq(s.g["fallback_profile_boot_salt"], salt, f"random {rv:#x} -> salt {salt} (| 1)")
        if salt != 1:
            ids.add(txt(s, "review_id"))   # salt 1 / seq 1 is the golden id already in the set
    ex.eq(len(ids), 7, "ids differ across salts (4 sequence numbers under salt 1 + 3 other salts)")
    # the salt is drawn once (lazily, at the first review) and survives across reviews
    s = mk_sim(fw, seed="none", salt=False)
    s.random_values = [4, 8]
    ex.eq(s.g["fallback_profile_boot_salt"], 0, "no salt before the first review (never seeded in on_boot)")
    review(s)
    review(s)
    ex.eq((s.g["fallback_profile_boot_salt"], len(s.random_values)), (5, 1), "one random_uint32() per boot, not per review")
    return ex.fails


@behav("B-V1", "T-CAP-05': a Review press during a parked dispatch (idle wait, each read) is REFUSED by V1 and changes NOTHING except B9; the first review still completes with exactly 4 reads")
def sc_v1(fw):
    ex = Exp()
    for where, setup, offset, step in (("idle wait", lambda s: s.hold_bus(1500), 100, 0), ("R1", None, 50, 1), ("R2", None, 190, 2),
                                       ("R3", None, 310, 3), ("R4", None, 430, 4)):
        sim = mk_sim(fw, mode=("deferred", 120))
        if setup:
            setup(sim)
            sim.run_for(1)
        m = sim.mark()
        t0 = sim.now_ms
        press(sim)
        sim.run_until(t0 + offset)
        ex.ok(sim.g["fallback_profile_op_in_progress"] and "fallback_profile_capture_dispatch" in sim.running, f"{where}: the dispatch is parked and running")
        ex.eq(sim.g["fallback_profile_step"], step, f"{where}: the dispatch is parked at step {step} (idle wait 0, R1..R4 = 1..4), not merely 'running'")
        ex.ok(sim.g["manual_write_in_progress"] is True and sim.g["fallback_profile_capture_state"] == 1 and sim.g["fallback_profile_op_purpose"] == 1,
              f"{where}: while the dispatch runs it holds the shared write mutex (READING, purpose REVIEW)")
        snap = sim.snapshot_state()
        m2 = sim.mark()
        press(sim)
        sim.run_for(3)
        d = sim.state_diff(snap)
        ex.eq(d["globals"], [], f"{where}: the refused press changed no global")
        ex.eq(d["published"], {TS["B9"]: [INFLIGHT_B9]}, f"{where}: only B9 was published, with the in-flight text")
        sn2 = sim.since(m2)
        ex.eq((sn2.writes, sn2.nvs_ops, sn2.reads), ([], [], []), f"{where}: the refused press issued no frame and touched no NVS")
        sim.run_until_idle()
        sn = sim.since(m)
        ex.eq(sn.violations(reads=FULL_READS), [], f"{where}: the first review completes with exactly the four reads")
        ex.starts(txt(sim, "review"), "st=CANDIDATE_READY;", f"{where}: candidate READY")
        ex.eq(sim.g["fallback_profile_cand_seq"], 1, f"{where}: one candidate only")
        invariants(sim, ex, f"v1 {where}")
    return ex.fails


@behav("B-ARMS", "T-CAP-18: each write arm ON refuses (V3) with zero reads and zero NVS access; arms off again -> accepted")
def sc_arms(fw):
    ex = Exp()
    for arm in ARMS:
        sim = mk_sim(fw)
        sim.ent(arm).set(True)
        sn = review(sim)
        refused(ex, sim, sn, f"arm {arm}", probes=0)
        ex.eq(txt(sim, "last_result"), "REVIEW REFUSED - a Free Power / Dump to Grid / Manual Configuration write arm is on; finish or turn it off first", f"{arm}: text")
        ex.eq(sn.nvs_ops, [], f"{arm}: no NVS operation of any kind")
        sim.ent(arm).set(False)
        sn = review(sim)
        ex.eq(sn.violations(reads=FULL_READS), [], f"{arm}: off again -> accepted with the 4 reads")
    sim = mk_sim(fw)
    for arm in ARMS:
        sim.ent(arm).set(True)
    sn = review(sim)
    refused(ex, sim, sn, "all arms", probes=0)
    return ex.fails


BUS_TERMS = ("manual_write_in_progress", "correction_in_progress", "verification_pending", "verification_read_active",
             "free_power_operation_in_progress", "free_power_recovery_force_in_progress", "free_power_recovery_accept_in_progress",
             "reg244_apply_in_progress", "dump_operation_in_progress")


@behav("B-BUS", "V4: every FBP_TXN_BUSY term (incl. Manual TOU = the shared mutex) refuses with BUS busy, zero reads, zero NVS access; a stuck lock (>= 300 s) reads LK")
def sc_bus(fw):
    ex = Exp()
    for term in BUS_TERMS:
        sim = mk_sim(fw)
        sim.run_lambda(f"id({term}) = true;")
        sn = review(sim)
        refused(ex, sim, sn, f"bus {term}", probes=0, locked=True)
        ex.has(obl_of(sim), "BUS:BY", f"{term}: vector shows BUS busy")
        ex.has(txt(sim, "last_result"), "another inverter transaction is in progress", f"{term}: text")
        ex.eq(sn.nvs_ops, [], f"{term}: lazy - no NVS read at all")
        if term == "manual_write_in_progress":
            ex.ok(sim.g["manual_write_in_progress"] is True, "an external holder of the mutex is left alone")
        sim.run_lambda(f"id({term}) = false;")
        sn = review(sim)
        ex.eq(sn.violations(reads=FULL_READS), [], f"{term}: cleared -> accepted")
    # stuck lock boundary: held >= 300 000 ms by the read-only diagnostic
    for age, want_lk in ((299_999, False), (300_000, True), (900_000, True)):
        sim = mk_sim(fw)
        sim.rebase_clock(2_000_000)
        sim.run_lambda("id(manual_write_in_progress) = true; id(diag_write_lock_held) = true; "
                       f"id(diag_write_lock_since_ms) = millis() - {age};")
        sn = review(sim)
        refused(ex, sim, sn, f"stuck lock age {age}", probes=0, locked=True)
        ex.eq("BUS:LK" in obl_of(sim), want_lk, f"lock age {age}: LK iff >= 300000 ms")
        if want_lk:
            ex.has(txt(sim, "last_result"), "write lock held for", f"lock age {age}: stuck text")
    # the lock-age counter across the millis() wrap
    sim = mk_sim(fw)
    sim.rebase_clock(2 ** 32 - 1000)
    sim.run_lambda("id(manual_write_in_progress) = true; id(diag_write_lock_held) = true; id(diag_write_lock_since_ms) = millis() - 400000;")
    sn = review(sim)
    ex.ok("BUS:LK" in obl_of(sim), "stuck lock detected across the millis() wrap")
    return ex.fails


LEASE_ACTIVE = {
    "fp": "id(free_power_snapshot_valid) = true; id(free_power_marker_state) = 1; id(free_power_active_persisted) = true;",
    "dump": "id(dump_snapshot_valid) = true; id(dump_marker_state) = 1; id(dump_active_persisted) = true;",
}
MUTEX_ON = "id(manual_write_in_progress) = true;"
OWNER_B9 = "REVIEW REFUSED - another inverter transaction is in progress (%s); try again shortly"


@behav("B-OWNER", "review FW1: the BUS refusal names the REAL owner - an ACTIVE Dump / Free Power lease whose controller holds the shared mutex alone is named (not '(manual write)'), a plain manual write still says '(manual write)', a named owner flag outranks a lease, RR leases are not named; vector and slot precedence unchanged")
def sc_owner(fw):
    ex = Exp()
    cases = [  # (label, lambda, owner named in B9, expected obl vector)
        ("Dump controller holds the mutex, ACTIVE Dump lease", LEASE_ACTIVE["dump"] + MUTEX_ON, "Dump to Grid", "FP:NP,DP:AC,R4:NP,MT:NP,FS:CA,BUS:BY"),
        ("Free Power controller holds the mutex, ACTIVE Free Power lease", LEASE_ACTIVE["fp"] + MUTEX_ON, "Free Power", "FP:AC,DP:NP,R4:NP,MT:NP,FS:CA,BUS:BY"),
        ("both leases ACTIVE: Free Power is named first (owner-chain order)", LEASE_ACTIVE["fp"] + LEASE_ACTIVE["dump"] + MUTEX_ON, "Free Power", "FP:AC,DP:AC,R4:NP,MT:NP,FS:CA,BUS:BY"),
        ("a plain manual write: no lease", MUTEX_ON, "manual write", "FP:NP,DP:NP,R4:NP,MT:NP,FS:CA,BUS:BY"),
        ("Dump lease RESTORE_REQUIRED + mutex: only ACTIVE names a lease", "id(dump_snapshot_valid) = true; id(dump_marker_state) = 1;" + MUTEX_ON, "manual write", "FP:NP,DP:RR,R4:NP,MT:NP,FS:CA,BUS:BY"),
        ("clock correction + ACTIVE Dump lease + mutex: a named owner outranks a lease", LEASE_ACTIVE["dump"] + MUTEX_ON + "id(correction_in_progress) = true;", "clock correction", "FP:NP,DP:AC,R4:NP,MT:NP,FS:CA,BUS:BY"),
        ("a Free Power operation flag + ACTIVE Dump lease + mutex: the operation flag wins", LEASE_ACTIVE["dump"] + MUTEX_ON + "id(free_power_operation_in_progress) = true;", "Free Power", None),
    ]
    for label, code, owner, vec in cases:
        sim = mk_sim(fw)
        sim.run_lambda(code)
        sn = review(sim)
        refused(ex, sim, sn, label, probes=0, locked=True)
        ex.eq(txt(sim, "last_result"), OWNER_B9 % owner, f"{label}: B9 names '{owner}'")
        if vec is not None:
            ex.eq(obl_of(sim), vec, f"{label}: vector (slot precedence and codes unchanged)")
        else:   # the FP slot's own classification for an operation flag is not this scenario's subject: the Dump lease and the busy bus still show
            ex.ok("DP:AC" in obl_of(sim) and obl_of(sim).endswith("BUS:BY"), f"{label}: the vector still shows the Dump lease and BUS busy ({obl_of(sim)})")
        ex.eq(sn.nvs_ops, [], f"{label}: lazy - not one NVS read")
        ex.ok(sim.g["manual_write_in_progress"] is True, f"{label}: an external holder of the mutex is left alone")
    # the mutex released: the ordinary lease refusal (the lease domain text, not the BUS one) - the next press after the controller tick
    sim = mk_sim(fw)
    sim.run_lambda(LEASE_ACTIVE["dump"] + MUTEX_ON)
    review(sim)
    sim.run_lambda("id(manual_write_in_progress) = false;")
    sn = review(sim)
    refused(ex, sim, sn, "Dump ACTIVE, mutex free", probes=0)
    ex.has(txt(sim, "last_result"), "Dump to Grid is active", "mutex free: the Dump lease text")
    ex.ok("another inverter transaction" not in txt(sim, "last_result"), "mutex free: no BUS text")
    return ex.fails


FP_RAM = {  # name -> (lambda, expected vector code, text fragment)
    "FP active lease": ("id(free_power_snapshot_valid) = true; id(free_power_marker_state) = 1; id(free_power_active_persisted) = true;", "FP:AC", "Free Power is active"),
    "FP restore required": ("id(free_power_snapshot_valid) = true; id(free_power_marker_state) = 1; id(free_power_restore_requested) = true;", "FP:RR", "Free Power must restore original settings first"),
    "FP pending clear": ("id(free_power_snapshot_valid) = true; id(free_power_marker_state) = 2;", "FP:PC", "Free Power restore verified; durable clear still pending"),
    "FP operator needed": ("id(free_power_snapshot_valid) = true; id(free_power_marker_state) = 1; id(free_power_operator_needed) = true;", "FP:ON", "Free Power needs an operator recovery action first"),
    "FP metadata corrupt": ("id(free_power_recovery_metadata_corrupt) = true;", "FP:MC", "Free Power recovery metadata is CORRUPT"),
    "Dump active lease": ("id(dump_snapshot_valid) = true; id(dump_marker_state) = 1; id(dump_active_persisted) = true;", "DP:AC", "Dump to Grid is active"),
    "Dump operator needed (live 244 = 0 lockout)": ("id(dump_snapshot_valid) = true; id(dump_marker_state) = 1; id(dump_operator_needed) = true;", "DP:ON", "Dump to Grid needs an operator recovery action first"),
    "Dump restore required": ("id(dump_snapshot_valid) = true; id(dump_marker_state) = 1;", "DP:RR", "Dump to Grid must restore original settings first"),
    "Dump metadata corrupt with K=3": ("id(dump_recovery_metadata_corrupt) = true; id(dump_containment_state) = 3;", "DP:MC", "containment K=3"),
    "Dump containment without corrupt flag": ("id(dump_containment_state) = 5;", "DP:DV", "in-memory recovery state is inconsistent"),
    "R244 restore required": ("id(reg244_snapshot_valid) = true; id(reg244_marker_state) = 1;", "R4:ON", "Register 244 test needs an operator recovery action first"),
    "R244 pending clear": ("id(reg244_snapshot_valid) = true; id(reg244_marker_state) = 2;", "R4:PC", "Register 244 test restore verified; durable clear still pending"),
    "R244 metadata corrupt": ("id(reg244_recovery_metadata_corrupt) = true;", "R4:MC", "Register 244 test recovery metadata is CORRUPT"),
}
RUN_SCRIPTS = (("start_free_power_override", "FP:ST", "Free Power"), ("restore_free_power_snapshot", "FP:EN", "Free Power"),
               ("restore_free_power_snapshot_dispatch", "FP:EN", "Free Power"), ("free_power_recovery_review", "FP:EN", "Free Power"),
               ("free_power_recovery_review_dispatch", "FP:EN", "Free Power"), ("free_power_recovery_force_restore", "FP:EN", "Free Power"),
               ("free_power_recovery_force_restore_dispatch", "FP:EN", "Free Power"), ("free_power_recovery_accept_current_state", "FP:EN", "Free Power"),
               ("free_power_recovery_accept_current_state_dispatch", "FP:EN", "Free Power"), ("start_dump_to_grid_override", "DP:ST", "Dump to Grid"),
               ("restore_dump_to_grid_snapshot", "DP:EN", "Dump to Grid"), ("apply_reg244_settings", "R4:ST", "Register 244 test"),
               ("restore_reg244_snapshot", "R4:EN", "Register 244 test"))


@behav("B-LEASE", "T-CAP-11 / T-CAP-25: every RAM leg of FP / Dump / R244 (active lease, RR, PC, operator needed, corrupt, K, a RUN script) refuses with the right vector kind and text and ZERO marker reads")
def sc_lease(fw):
    ex = Exp()
    for name, (code, want, frag) in FP_RAM.items():
        sim = mk_sim(fw)
        sim.run_lambda(code)
        sn = review(sim)
        refused(ex, sim, sn, name, probes=0)
        ex.has(obl_of(sim), want, f"{name}: vector")
        ex.has(txt(sim, "last_result"), frag, f"{name}: operator text")
        ex.eq(sn.nvs_ops, [], f"{name}: LAZY probing - not one NVS read when a RAM leg refuses")
        ex.eq(latch_of(sim), "-", f"{name}: nothing latched without a probe")
    for scr, code, label in RUN_SCRIPTS:
        sim = mk_sim(fw)
        sim.hold_script_running(scr, 100_000)
        sim.run_for(1)
        sn = review(sim)
        refused(ex, sim, sn, f"RUN {scr}", probes=0)
        ex.has(obl_of(sim), code, f"{scr}: vector {code}")
        ex.has(txt(sim, "last_result"), label, f"{scr}: names {label}")
        ex.eq(sn.nvs_ops, [], f"{scr}: no NVS read")
    # Dump operator_needed with the LIVE register 244 at 0 (export allowed: the lockout path): still the RAM leg, still zero NVS reads
    sim = mk_sim(fw, words=_w(r244=0))
    sim.run_lambda(FP_RAM["Dump operator needed (live 244 = 0 lockout)"][0])
    sn = review(sim)
    refused(ex, sim, sn, "Dump operator needed, live 244 = 0", probes=0)
    ex.has(obl_of(sim), "DP:ON", "Dump operator needed + live 244 = 0: vector DP:ON")
    ex.has(txt(sim, "last_result"), "Dump to Grid needs an operator recovery action first", "Dump operator needed + live 244 = 0: text")
    ex.eq(sn.nvs_ops, [], "Dump operator needed + live 244 = 0: no NVS read")
    # a RAM leg wins even with the other domains CLEAR: the not-yet-probed domains show NP
    sim = mk_sim(fw)
    sim.run_lambda(FP_RAM["FP active lease"][0])
    review(sim)
    ex.starts(obl_of(sim), "FP:AC,DP:NP,R4:NP,MT:CN,FS:CA,BUS:OK", "RAM-clear domains behind a refusing leg are NOT PROBED (NP)")
    # Manual TOU in flight is the shared mutex: BUS busy, MT not evaluated
    sim = mk_sim(fw)
    sim.run_lambda("id(manual_write_in_progress) = true;")
    sn = review(sim)
    ex.has(obl_of(sim), "BUS:BY", "Manual TOU (mutex held): BUS busy")
    refused(ex, sim, sn, "manual tou in flight", probes=0, locked=True)
    return ex.fails


# --------------------------------------------------------------------------- marker probes, latch, boot truth, FBS
PROBE_FAULTS = {  # name -> (marker state, seed_marker kwargs, queued read faults, latch text fragment)
    "crc-bad chunk (read error, then ESP_FAIL, then ABSENT)": (0, {"legacy": False, "crc_ok": False}, None, "became unreadable at runtime"),
    "missing chunk (ESP_FAIL, then ABSENT)": (0, {"legacy": False, "chunk_present": False}, None, "became unreadable at runtime"),
    "queued ESP_FAIL x2, then ABSENT": (None, None, [fd.IDF_FAIL, fd.IDF_FAIL], "became unreadable at runtime"),
    "bad magic": (0, {"legacy": False, "magic": 0x1234}, None, "is malformed"),
    "wrong size": (0, {"legacy": False, "size": 24}, None, "is malformed"),
    "ghost RESTORE_REQUIRED": (1, {"legacy": False}, None, "stored marker says RESTORE_REQUIRED but memory says clear"),
    "ghost PENDING_CLEAR": (2, {"legacy": False}, None, "stored marker says PENDING_CLEAR but memory says clear"),
}


@behav("B-PROBE", "T-CAP-09 / T-CAP-10: a bad marker (unreadable / ESP_FAIL / malformed / ghost RR / ghost PC) refuses on EVERY press for each of FP / Dump / R244; the latch is set on press 1; presses 2-3 do NOT probe (zero NVS ops)")
def sc_probe(fw):
    ex = Exp()
    for dom, short, label, pre in DOMAINS:
        for name, (state, kw, queue, frag) in PROBE_FAULTS.items():
            tag = f"{dom}: {name}"
            sim = mk_sim(fw, markers=[] if state is None else [(dom, state, kw)])
            if queue:
                sim.nvs_direct.read_faults[fp.tag_key_fnv1_32(MARKER_TAGS[dom])] = list(queue)
            sn1 = review(sim)
            refused(ex, sim, sn1, f"{tag} press 1")
            ex.has(txt(sim, "last_result"), frag, f"{tag}: latch text")
            ex.has(txt(sim, "last_result"), label, f"{tag}: names {label}")
            ex.eq(latch_of(sim), short, f"{tag}: latch set on press 1")
            ex.eq(len([o for o in sn1.nvs_ops if o[0] == "get"]), 3, f"{tag}: press 1 probes each of the three markers once (all RAM legs clear)")
            ex.ok(all(marker_gets(sn1, d) == 1 for d, *_ in DOMAINS), f"{tag}: one probe per domain on press 1")
            before = dict(sim.nvs_direct.read_faults)
            for press_no in (2, 3):
                sn = review(sim)
                refused(ex, sim, sn, f"{tag} press {press_no}", probes=0)
                ex.eq(sn.nvs_ops, [], f"{tag} press {press_no}: NO probe at all (the latched domain is never re-probed, and the RAM leg refuses first)")
                ex.eq(latch_of(sim), short, f"{tag} press {press_no}: latch persists")
                ex.has(txt(sim, "last_result"), frag, f"{tag} press {press_no}: same latch text")
            ex.eq({k: list(v) for k, v in sim.nvs_direct.read_faults.items()}, {k: list(v) for k, v in before.items()}, f"{tag}: the queued fault list was not consumed by presses 2-3")
            ex.eq(sim.g["fallback_profile_op_in_progress"], False, f"{tag}: never accepted")
    # T-CAP-10: ghost RR, then the marker later reads ABSENT: still refused (latched), no probe
    for dom, short, label, pre in DOMAINS:
        sim = mk_sim(fw, markers=[(dom, 1, {"legacy": False})])
        review(sim)
        ex.eq(latch_of(sim), short, f"ghost RR {dom}: latched")
        sim.nvs_direct.blobs.pop(fp.tag_key_fnv1_32(MARKER_TAGS[dom]), None)
        sn = review(sim)
        refused(ex, sim, sn, f"ghost RR {dom} then ABSENT", probes=0)
        ex.has(txt(sim, "last_result"), "stored marker says RESTORE_REQUIRED", f"ghost RR {dom} then ABSENT: still the ghost text")
    # two domains latched at once: both persist, nothing probed afterwards
    sim = mk_sim(fw, markers=[("fp", 1, {"legacy": False}), ("r244", 0, {"legacy": False, "crc_ok": False})])
    review(sim)
    ex.eq(latch_of(sim), "FP,R4", "two latched domains, in order FP,R4")
    sn = review(sim)
    ex.eq(sn.nvs_ops, [], "two latched domains: no NVS access on the next press")
    # a CLEAR marker and an ABSENT marker are accepted: vector CM / CA, latch stays empty
    for dom, short, label, pre in DOMAINS:
        sim = mk_sim(fw, markers=[(dom, 0, {})])
        sn = review(sim)
        ex.eq(sn.violations(reads=FULL_READS), [], f"{dom}: CLEAR marker -> accepted with the 4 reads")
        ex.has(obl_of(sim), f"{short}:CM", f"{dom}: vector CM")
        ex.eq(latch_of(sim), "-", f"{dom}: latch empty")
    return ex.fails


@behav("B-BOOTTRUTH", "T-CAP-12: a boot READ_ERROR / malformed marker (SG-06 truth) refuses with UNKNOWN / CORRUPT and ZERO probes; the retained boot load, not a runtime probe, decides")
def sc_boot_truth(fw):
    ex = Exp()
    for dom, short, label, pre in DOMAINS:
        sim = mk_sim(fw, fail_tags=[MARKER_TAGS[dom]])
        sn = review(sim)
        refused(ex, sim, sn, f"{dom} boot READ_ERROR", probes=0)
        ex.has(txt(sim, "last_result"), f"{label} recovery state UNKNOWN since boot (marker unreadable)", f"{dom}: UNKNOWN text")
        ex.has(obl_of(sim), f"{short}:UR", f"{dom}: vector UR")
        ex.eq(sn.nvs_ops, [], f"{dom}: zero probes")
        # the same marker readable at runtime (a probe would say ABSENT / CLEAR) does not change the verdict
        sim.nvs_direct.put(fp.tag_key_fnv1_32(MARKER_TAGS[dom]), H.FbbSim.marker_bytes(ds.Durable.VALID_MARKER_MAGIC, 0))
        sn = review(sim)
        refused(ex, sim, sn, f"{dom} boot READ_ERROR, marker readable now", probes=0)
        ex.has(obl_of(sim), f"{short}:UR", f"{dom}: still UR")
        sim = mk_sim(fw, pre=lambda s, d=dom: s.seed_marker(MARKER_TAGS[d], 0, magic=0x1234, direct=False))
        sn = review(sim)
        refused(ex, sim, sn, f"{dom} malformed boot marker", probes=0)
        ex.has(txt(sim, "last_result"), "recovery metadata is CORRUPT (hard lockout)", f"{dom}: CORRUPT text")
        ex.has(obl_of(sim), f"{short}:MC", f"{dom}: vector MC")
    sim = mk_sim(fw, pre=lambda s: s.seed_marker(MARKER_TAGS["dump"], 0, magic=0x1234, direct=False))
    sim.run_lambda("id(dump_containment_state) = 3;")
    review(sim)
    ex.has(txt(sim, "last_result"), "containment K=3", "Dump corrupt text carries K")
    # the boot lambdas have not run: durable state not loaded yet
    sim = mk_sim(fw, boot=False)
    sim.run_boot(select=[0, 1, 2])
    sn = review(sim)
    ex.eq(txt(sim, "last_result"), "REVIEW REFUSED - durable state not loaded yet (starting up)", "V2: boot load not finished")
    ex.eq((sn.violations(reads=[]), sn.nvs_ops), ([], []), "V2: zero reads, zero NVS")
    ex.ok(sim.g["fallback_profile_boot_loaded"] is False and sim.g["manual_write_in_progress"] is False, "V2: no lock, boot_loaded still false")
    sim.run_boot(select=3)
    sn = review(sim)
    ex.eq(sn.violations(reads=FULL_READS), [], "after the FB boot item ran: accepted")
    return ex.fails


def _fbs_seed(kind):
    def seed(sim):
        if kind == "clear":
            sim.nvs_direct.put(K_S, fp.pack_failback(fp.failback_clear_record(3)))
        elif kind == "episode":
            rec = fp.seal_failback(fp.blank_failback(magic=fp.FAILBACK_MAGIC, schema=fp.FAILBACK_SCHEMA, size=fp.FAILBACK_SIZE, state=1, reason=1, event_seq=2))
            sim.nvs_direct.put(K_S, fp.pack_failback(rec))
        elif kind == "corrupt":
            sim.nvs_direct.put(K_S, bytes(range(fp.FAILBACK_SIZE)))
        elif kind == "unreadable":
            sim.nvs_direct.put(K_S, fp.pack_failback(fp.failback_clear_record(3)))
            sim.nvs_direct.read_faults[K_S] = [fd.IDF_FAIL]
    return seed


@behav("B-FBS", "T-CAP-25: the failback-state record (absent / CLEAR / episode / corrupt / unreadable) read ONCE at boot decides the FS slot; a review never touches it")
def sc_fbs(fw):
    ex = Exp()
    cases = {"absent": ("FS:CA", None), "clear": ("FS:CM", None), "episode": ("FS:AC", "a failback episode record exists"),
             "corrupt": ("FS:MC", "Failback record recovery metadata is CORRUPT"), "unreadable": ("FS:UR", "Failback record recovery state UNKNOWN since boot")}
    for kind, (code, frag) in cases.items():
        sim = mk_sim(fw, fbs=_fbs_seed(kind) if kind != "absent" else None)
        boot_ops = [o for o in sim.nvs_direct.ops if o[1] == fd.decimal_key(K_S)]
        ex.eq(len([o for o in boot_ops if o[0] == "get"]), 1, f"{kind}: the failback record is read exactly once at boot")
        sn = review(sim)
        ex.ok(not [o for o in sn.nvs_ops if o[1] == fd.decimal_key(K_S)], f"{kind}: the review never reads the failback record")
        if frag is None:
            ex.eq(sn.violations(reads=FULL_READS), [], f"{kind}: accepted")
            ex.has(obl_of(sim), code, f"{kind}: vector {code}")
        else:
            refused(ex, sim, sn, f"FBS {kind}", probes=0)
            ex.has(txt(sim, "last_result"), frag, f"{kind}: text")
            ex.has(obl_of(sim), code, f"{kind}: vector {code}")
    return ex.fails


# --------------------------------------------------------------------------- pass compare (P4), read failures, late callbacks
def _mutator(sim, k: int, gap: int, delta: int = 1):
    """The inverter changes word k (persistently) right after the `gap`-th firmware read has been served."""
    reg = fc.REGS[k]
    n = [0]

    def ov(addr, count, values):
        n[0] += 1
        if n[0] > gap and addr <= reg < addr + count:
            vv = list(values)
            vv[reg - addr] = (vv[reg - addr] + delta) & 0xFFFF
            return vv
        return values
    sim.read_override_fn = ov


def _mismatch_expected(reg: int, gap: int) -> bool:
    block_a = reg in (230, 231, 232)          # read by R1 and R3
    return gap in ((1, 2) if block_a else (2, 3))


def _mismatch_text(reg: int, a: int, b: int) -> str:
    return f"REVIEW NOT COMPLETED - live configuration changed during the read (register {reg}: {a} then {b}); another controller may be editing - review again"


def _run_mismatch(fw, ks, modes):
    ex = Exp()
    for mode in modes:
        for k in ks:
            reg = fc.REGS[k]
            for gap in (1, 2, 3):
                sim = mk_sim(fw, mode=mode)
                _mutator(sim, k, gap)
                sn = review(sim)
                tag = f"word {k} (reg {reg}) changes after read {gap} [{mode[0] if mode else 'immediate'}]"
                ex.eq(sn.violations(reads=FULL_READS), [], f"{tag}: the four reads, nothing written")
                a, b = GWORDS[k], (GWORDS[k] + 1) & 0xFFFF
                if _mismatch_expected(reg, gap):
                    ex.eq(txt(sim, "last_result"), _mismatch_text(reg, a, b), f"{tag}: pass mismatch names the register")
                    ex.ok(not sim.g["fallback_profile_cand_valid"] and sim.g["fallback_profile_capture_state"] == 0 and sim.g["fallback_profile_cand_seq"] == 0,
                          f"{tag}: NEVER a candidate when the two passes disagree")
                    ex.eq((txt(sim, "review_id"), txt(sim, "review_slots"), txt(sim, "review_context")), ("-", NONE_B5, NONE_B6), f"{tag}: B4 / B5 / B6 stay empty")
                    ex.starts(txt(sim, "review"), "st=IDLE;", f"{tag}: B3 idle")
                else:
                    ex.ok(sim.g["fallback_profile_cand_valid"], f"{tag}: passes agree (the word moved only before its first / after its last read) -> a candidate")
                    want = list(GWORDS)
                    want[k] = b if gap == 1 and reg not in (230, 231, 232) else a
                    ex.eq(list(sim.g["fallback_profile_cand_words"]), want, f"{tag}: candidate holds the pass-2 value")
                ex.eq(list(sim.g["fallback_profile_pass1"]) == list(sim.g["fallback_profile_pass2"]), not _mismatch_expected(reg, gap), f"{tag}: pass buffers agree iff no mismatch")
                invariants(sim, ex, tag)
    return ex.fails


def _glitch(sim, k: int, p: int, delta: int = 1):
    """Only the p-th firmware read returns word k wrong (a one-shot glitch, not a persistent change)."""
    reg = fc.REGS[k]
    n = [0]

    def ov(addr, count, values):
        n[0] += 1
        if n[0] == p and addr <= reg < addr + count:
            vv = list(values)
            vv[reg - addr] = (vv[reg - addr] + delta) & 0xFFFF
            return vv
        return values
    sim.read_override_fn = ov


def _run_glitch(fw, ks, modes):
    """Each word k wrong in exactly ONE of the four reads p: a mismatch iff that read covers the word."""
    ex = Exp()
    for mode in modes:
        for k in ks:
            reg = fc.REGS[k]
            for p in (1, 2, 3, 4):
                sim = mk_sim(fw, mode=mode)
                _glitch(sim, k, p)
                sn = review(sim)
                tag = f"word {k} (reg {reg}) wrong in read {p} only [{mode[0] if mode else 'immediate'}]"
                covered = (reg in (230, 231, 232)) if p in (1, 3) else (241 <= reg <= 293)
                ex.eq(sn.violations(reads=FULL_READS), [], f"{tag}: the four reads, nothing written")
                true, bad = GWORDS[k], (GWORDS[k] + 1) & 0xFFFF
                if covered:
                    a, b = (bad, true) if p in (1, 2) else (true, bad)
                    ex.eq(txt(sim, "last_result"), _mismatch_text(reg, a, b), f"{tag}: pass mismatch names the register")
                    ex.ok(not sim.g["fallback_profile_cand_valid"] and sim.g["fallback_profile_capture_state"] == 0, f"{tag}: NEVER a candidate")
                else:
                    ex.ok(sim.g["fallback_profile_cand_valid"] and list(sim.g["fallback_profile_cand_words"]) == list(GWORDS), f"{tag}: the read does not cover the word -> the passes agree")
                invariants(sim, ex, tag)
    return ex.fails


@behav("B-MISMATCH", "P4 / T-CAP-06: each of the 31 words changed between each pair of reads AND wrong in each single read: pass mismatch naming the register, NEVER a candidate (immediate AND deferred)")
def sc_mismatch(fw):
    return _run_mismatch(fw, range(31), (None, ("deferred", 120))) + _run_glitch(fw, range(31), (None, ("deferred", 120)))


@behav("B-MISMATCHQ", "T-CAP-06 (quick form for the mutation matrix): words 0, 19, 28 and 30 at the three gaps and in each single read")
def sc_mismatch_quick(fw):
    return _run_mismatch(fw, (0, 19, 28, 30), (None,)) + _run_glitch(fw, (0, 19, 28, 30), (None,))


@behav("B-MISMATCH2", "the FIRST differing register in canonical order is named (232 before 230, 244 before everything), whatever the register number order")
def sc_mismatch_first(fw):
    ex = Exp()
    k_232, k_230 = fc.REGS.index(232), fc.REGS.index(230)
    for k1, k2 in ((k_232, k_230), (0, 30), (5, 12), (19, 28), (13, 20)):
        sim = mk_sim(fw)
        r1, r2 = fc.REGS[k1], fc.REGS[k2]
        n = [0]

        def ov(addr, count, values, r1=r1, r2=r2, n=n):
            n[0] += 1
            vv = list(values)
            if n[0] in (3, 4):
                for r in (r1, r2):
                    if addr <= r < addr + count:
                        vv[r - addr] = (vv[r - addr] + 5) & 0xFFFF
            return vv
        sim.read_override_fn = ov
        review(sim)
        first = fc.REGS[min(k1, k2)]
        ex.starts(txt(sim, "last_result"), f"REVIEW NOT COMPLETED - live configuration changed during the read (register {first}:", f"words {k1}/{k2}: the first differing register in canonical order is {first}")
        ex.ok(not sim.g["fallback_profile_cand_valid"], f"words {k1}/{k2}: no candidate")
    return ex.fails


def _fail_text(k: int, kind: str, exc: int = 2) -> str:
    blk = "230/3" if k in (1, 3) else "241/53"
    return {"error": f"REVIEW NOT COMPLETED - inverter returned exception code 0x{exc:02X} on registers {blk}",
            "no_response": f"REVIEW NOT COMPLETED - no response reading registers {blk}",
            "not_sent": f"REVIEW NOT COMPLETED - read of registers {blk} could not be queued",
            "custom_response": f"REVIEW NOT COMPLETED - non-standard reply reading registers {blk}",
            "short": f"REVIEW NOT COMPLETED - short reply reading registers {blk}",
            "bounded": f"REVIEW NOT COMPLETED - read of registers {blk} did not complete within 3 s"}[kind]


def _failed_ok(ex: Exp, sim, sn, tag: str, k: int, text: str):
    ex.eq(txt(sim, "last_result"), text, f"{tag}: B9")
    ex.eq(sn.reads, FULL_READS[:k], f"{tag}: fail-fast - exactly the reads up to the failing one")
    ex.eq(sn.violations(), [], f"{tag}: no write / nvs set / commit")
    ex.ok(not sim.g["fallback_profile_cand_valid"] and txt(sim, "review_id") == "-" and txt(sim, "review_slots") == NONE_B5, f"{tag}: no candidate")
    ex.starts(txt(sim, "review"), "st=IDLE;", f"{tag}: B3 idle")
    ex.eq([len(sim.ent(e).published) for e in (TS["B1"], TS["B2"], TS["B7"], TS["B8"])], [1, 1, 1, 1], f"{tag}: no fresh stored-profile read after a failed read")
    ex.eq(len(sn.nvs_read_probes), 3, f"{tag}: only the three marker probes touched NVS")
    invariants(sim, ex, tag)


@behav("B-FAIL", "read-failure matrix: exception / no response / not sent / non-standard / short / bounded wait at each of the 4 steps, immediate and deferred: exact text, fail-fast, released, no candidate")
def sc_fail(fw):
    ex = Exp()
    for k in (1, 2, 3, 4):
        for kind in ("error", "no_response", "not_sent", "custom_response"):
            for mode in (None, ("deferred", 120)):
                sim = mk_sim(fw, mode=mode)
                sim.queue_frames(*(["ok"] * (k - 1) + [kind]))
                sn = review(sim)
                _failed_ok(ex, sim, sn, f"R{k} {kind} {'deferred' if mode else 'immediate'}", k, _fail_text(k, kind))
        for exc in (1, 0x0B):
            sim = mk_sim(fw, mode=("deferred", 120))
            sim.queue_frames(*(["ok"] * (k - 1) + [E.FrameSpec(outcome="error", exception_code=exc)]))
            sn = review(sim)
            _failed_ok(ex, sim, sn, f"R{k} exception {exc:#04x}", k, _fail_text(k, "error", exc))
        for mode in (None, ("deferred", 120)):
            sim = mk_sim(fw, mode=mode)
            sim.queue_frames(*(["ok"] * (k - 1) + [E.FrameSpec(values=[0] * (2 if k in (1, 3) else 52))]))
            sn = review(sim)
            _failed_ok(ex, sim, sn, f"R{k} short reply {'deferred' if mode else 'immediate'}", k, _fail_text(k, "short"))
            sim = mk_sim(fw, mode=mode)
            sim.queue_frames(*(["ok"] * (k - 1) + [E.FrameSpec(values=[0] * (4 if k in (1, 3) else 54))]))
            sn = review(sim)
            _failed_ok(ex, sim, sn, f"R{k} long reply {'deferred' if mode else 'immediate'}", k, _fail_text(k, "short"))
        sim = mk_sim(fw, mode=("deferred", 120))
        sim.queue_frames(*(["ok"] * (k - 1) + [E.FrameSpec(latency_ms=3500)]))
        sn = review(sim)
        _failed_ok(ex, sim, sn, f"R{k} bounded wait", k, _fail_text(k, "bounded"))
        # the 3 s wait is exactly 3 s: a reply at 2 900 ms is accepted
        sim = mk_sim(fw, mode=("deferred", 120))
        sim.queue_frames(*(["ok"] * (k - 1) + [E.FrameSpec(latency_ms=2900)]))
        sn = review(sim)
        ex.eq(sn.violations(reads=FULL_READS), [], f"R{k} reply at 2.9 s: still accepted")
    # idle wait: 7 s bound
    for how in ("bus held 8 s", "config poll running 9 s", "telemetry poll running 8 s"):
        sim = mk_sim(fw, mode=("deferred", 120))
        if how.startswith("bus"):
            sim.hold_bus(8000)
        else:
            sim.hold_script_running("poll_inverter_configuration_dispatch" if how.startswith("config") else "poll_inverter_telemetry", 9000 if how.startswith("config") else 8000)
        sim.run_for(1)
        t0 = sim.now_ms
        sn = review(sim)
        ex.eq(txt(sim, "last_result"), "REVIEW NOT COMPLETED - inverter bus stayed busy for 7 s; press Review again", f"idle timeout ({how}): B9")
        ex.eq((sn.reads, sn.violations(reads=[])), ([], []), f"idle timeout ({how}): zero FB reads")
        ex.ok(sim.g["manual_write_in_progress"] is False and not sim.g["fallback_profile_cand_valid"], f"idle timeout ({how}): released, no candidate")
        invariants(sim, ex, f"idle timeout {how}")
    for how, secs in (("bus held 3 s", 3), ("poll running 4 s", 4), ("bus held 6.9 s", 6.9)):
        sim = mk_sim(fw, mode=("deferred", 120))
        if how.startswith("bus"):
            sim.hold_bus(int(secs * 1000))
        else:
            sim.hold_script_running("poll_inverter_telemetry", int(secs * 1000))
        sim.run_for(1)
        sn = review(sim)
        ex.eq(sn.violations(reads=FULL_READS), [], f"idle drain ({how}): the review waits and completes with the 4 reads")
    return ex.fails


@behav("B-POLLS", "T-CAP-01 / T-CAP-02: the REAL poll scripts in flight at the gate: the idle wait drains them, the four FB reads are contiguous on the wire; a poll that drains past 7 s refuses with zero FB reads")
def sc_polls(fw):
    ex = Exp()
    for name in ("poll_inverter_configuration_dispatch", "poll_inverter_telemetry"):
        sim = mk_sim(fw, mode=("deferred", 120))
        m = sim.mark()
        sim.start_script(name)
        sim.run_for(300)
        press(sim)
        sim.run_until_idle()
        sn = sim.since(m)
        fb = [(w.addr, w.count) for w in sn.wire if w.kind == "read" and (w.issuer or "").startswith("fallback_profile_")]
        order = [(w.origin, w.issuer) for w in sn.wire if w.kind == "read"]
        idx = [i for i, o in enumerate(order) if (o[1] or "").startswith("fallback_profile_")]
        ex.eq(fb, FULL_READS, f"{name}: the review issued exactly the four reads")
        ex.eq(idx, list(range(idx[0], idx[0] + 4)) if idx else None, f"{name}: the four FB reads are contiguous on the wire (no foreign frame between R1 and R4)")
        ex.ok(all(i < idx[0] for i, o in enumerate(order) if not (o[1] or "").startswith("fallback_profile_")) if idx else False, f"{name}: every poll frame precedes the FB reads")
        ex.starts(txt(sim, "review"), "st=CANDIDATE_READY;", f"{name}: candidate READY")
        ex.eq(sn.writes, [], f"{name}: no write")
        invariants(sim, ex, name)
    sim = mk_sim(fw, mode=("deferred", 2400))
    m = sim.mark()
    sim.start_script("poll_inverter_configuration_dispatch")
    sim.run_for(300)
    press(sim)
    sim.run_until_idle()
    sn = sim.since(m)
    ex.eq(txt(sim, "last_result"), "REVIEW NOT COMPLETED - inverter bus stayed busy for 7 s; press Review again", "slow poll (> 7 s drain): REVIEW NOT COMPLETED")
    ex.eq([(w.addr, w.count) for w in sn.wire if (w.issuer or "").startswith("fallback_profile_")], [], "slow poll: zero FB reads")
    ex.ok(not sim.g["manual_write_in_progress"] and not sim.g["fallback_profile_op_in_progress"], "slow poll: lock released")
    invariants(sim, ex, "slow poll")
    return ex.fails


@behav("B-LATE", "T-CAP-03: a late reply of a timed-out read is ignored (step == 0 / released): while a new review idles, and while NOTHING runs - it changes not one global; then a new review gets its own data")
def sc_late(fw):
    ex = Exp()
    sim = mk_sim(fw, mode=("deferred", 120))
    sim.queue_frames("ok", E.FrameSpec(latency_ms=3500))
    t0 = sim.now_ms
    m = sim.mark()
    press(sim)
    sim.at_press(t0 + 3400, BUTTON_ID)
    sim.run_until_idle()
    sn = sim.since(m)
    ex.starts(txt(sim, "review"), "st=CANDIDATE_READY;", "late R2 then a new review: the second review's candidate")
    ex.eq(sim.g["fallback_profile_cand_seq"], 1, "only one candidate was built (the first review failed)")
    ex.eq(txt(sim, "review_id"), "%016X" % fc.candidate_id(1, 1, 5, 7, GOLD_ID_BINDING, GWORDS), "the second review's id is that of a clean run")
    ex.eq((sn.writes, sim.g["manual_write_in_progress"], sim.g["fallback_profile_step"]), ([], False, 0), "no write, mutex released, step 0")
    deliver = [i for i, e in enumerate(sn.events) if e[0] == "deliver" and e[2:4] == (241, 53)]
    reads = [i for i, e in enumerate(sn.events) if e[0] == "read"]
    ex.ok(len(deliver) >= 1 and len(reads) >= 6, "the stale reply was delivered during the second review's idle wait")
    invariants(sim, ex, "late then new review")
    for k in (1, 2, 3, 4):
        for outcome in ("ok", "error", "no_response", "custom_response"):
            sim = mk_sim(fw, mode=("deferred", 120))
            sim.queue_frames(*(["ok"] * (k - 1) + [E.FrameSpec(outcome=outcome, latency_ms=3500)]))
            press(sim)
            task = sim.task_of("fallback_profile_capture_dispatch")
            sim.run_until_done(task)
            ex.starts(txt(sim, "last_result"), "REVIEW NOT COMPLETED - read of registers", f"R{k} {outcome}: bounded-wait failure first")
            snap = sim.snapshot_state()
            sim.run_until_idle()
            d = sim.state_diff(snap)
            ex.eq(d["globals"], [], f"R{k} {outcome}: the late reply changed NO global")
            ex.eq(d["published"], {}, f"R{k} {outcome}: the late reply published nothing")
            invariants(sim, ex, f"late R{k} {outcome}")
    return ex.fails


# --------------------------------------------------------------------------- candidate lifetime (P3)
HK = INTERVAL_MARK


def _with_candidate(fw, *, words=None, seed="valid", rebase=None, phase=0, markers=()):
    sim = mk_sim(fw, words=words, seed=seed, markers=markers)
    if rebase is not None:
        sim.rebase_clock(rebase)
    sn = review(sim)
    t_born = sim.now_ms
    assert sim.g["fallback_profile_cand_valid"], (txt(sim, "last_result"), sn.reads)
    sim.start_intervals(HK, phase=phase)
    return sim, t_born


@behav("B-TTL", "P3 / T-CAP-14: TTL 120 000 ms applied by the 10 s tick: alive at 119 999 ms, cleared by the first tick at >= 120 000 ms (exact boundary), also across the millis() wrap; a not-saveable preview expires too")
def sc_ttl(fw):
    ex = Exp()
    for rebase in (None, 2 ** 32 - 60_000, 2 ** 32 - 119_999, 2 ** 32 - 1):
        for words, what in ((None, "READY"), ("pre244", "NOT SAVEABLE preview")):
            w = None
            if words == "pre244":
                w = list(GWORDS)
                w[0] = 0
            tagbase = f"{what} rebase={rebase}"
            # (a) tick lands at age 119 999: still alive
            sim, tb = _with_candidate(fw, words=w, rebase=rebase, phase=9_999)
            b3_born = txt(sim, "review")
            sim.run_until(tb + 9_999)
            ex.eq(txt(sim, "review"), b3_born.replace("exp=120;", "exp=110;"), f"{tagbase}: the first tick refreshes ONLY exp (everything else of B3 is kept)")
            sim.run_until(tb + 119_999)
            ex.ok(sim.g["fallback_profile_cand_valid"], f"{tagbase}: alive at age 119 999 ms")
            ex.eq(txt(sim, "review").split("exp=")[1].split(";")[0], "0", f"{tagbase}: exp=0 at age 119 999 ms (floor)")
            sim.run_until(tb + 129_999)
            ex.ok(not sim.g["fallback_profile_cand_valid"], f"{tagbase}: gone by the first tick after the TTL (age 129 999 ms)")
            ex.eq(txt(sim, "last_result"), "REVIEW EXPIRED - candidate expired (120 s); review again", f"{tagbase}: expiry text")
            # (b) tick lands at age exactly 120 000: cleared at that tick
            sim, tb = _with_candidate(fw, words=w, rebase=rebase, phase=10_000)
            sim.run_until(tb + 119_999)
            ex.ok(sim.g["fallback_profile_cand_valid"], f"{tagbase}: (ticks at 10 000 n) alive until the 120 000 ms tick")
            sim.run_until(tb + 120_000)
            ex.ok(not sim.g["fallback_profile_cand_valid"], f"{tagbase}: cleared by the tick at exactly age 120 000 ms")
            ex.eq(txt(sim, "review"), f"st=IDLE;prior=-;exp=-;warn=-;obl={ALL_CLEAR_OBL};latch=-;sv=-", f"{tagbase}: B3 back to the idle form, obl kept")
            ex.eq((txt(sim, "review_id"), txt(sim, "review_slots"), txt(sim, "review_context")), ("-", NONE_B5, NONE_B6), f"{tagbase}: B4 / B5 / B6 cleared")
            ex.eq(sim.g["fallback_profile_capture_state"], 0, f"{tagbase}: capture_state IDLE")
            ex.eq(len([x for x in sim.ent(TS["B9"]).published if str(x).startswith("REVIEW EXPIRED")]), 1, f"{tagbase}: the expiry is published once")
            invariants(sim, ex, tagbase)
    # exp counts down on the tick and is published only on change
    sim, tb = _with_candidate(fw, phase=9_999)
    seen = []
    for n in range(1, 12):
        sim.run_until(tb + 9_999 + 10_000 * (n - 1))
        seen.append(txt(sim, "review").split("exp=")[1].split(";")[0])
    ex.eq(seen, [str((120_000 - (9_999 + 10_000 * i)) // 1000) for i in range(11)], "exp counts down 110, 100, ... 0 on the 10 s tick")
    # random tick phase: expiry always within one tick period after 120 s
    for seed in (1, 2, 3, 4, 5):
        sim = mk_sim(fw)
        sim.seed_rng(seed)
        sn = review(sim)
        tb = sim.now_ms
        sim.start_intervals(HK, phase="random")
        sim.run_until(tb + 119_999)
        ex.ok(sim.g["fallback_profile_cand_valid"], f"random phase {seed}: alive before 120 s")
        sim.run_until(tb + 130_000)
        ex.ok(not sim.g["fallback_profile_cand_valid"], f"random phase {seed}: cleared within one tick period after 120 s")
    return ex.fails


@behav("B-IE", "P3: IE3 supersede, IE7 (a recovery domain turned non-clear), IE11 (another ECCO write started), a mutex-only change does NOT invalidate; cleared within one 10 s tick with the right reason")
def sc_ie(fw):
    ex = Exp()
    ie7 = {"FP snapshot + RR": ("id(free_power_snapshot_valid) = true; id(free_power_marker_state) = 1;", "Free Power"),
           "FP metadata corrupt": ("id(free_power_recovery_metadata_corrupt) = true;", "Free Power"),
           "Dump snapshot + RR": ("id(dump_snapshot_valid) = true; id(dump_marker_state) = 1;", "Dump to Grid"),
           "Dump containment": ("id(dump_containment_state) = 3;", "Dump to Grid"),
           "R244 snapshot + RR": ("id(reg244_snapshot_valid) = true; id(reg244_marker_state) = 1;", "Register 244 test"),
           "R244 pending clear": ("id(reg244_snapshot_valid) = true; id(reg244_marker_state) = 2;", "Register 244 test")}
    for name, (code, dom) in ie7.items():
        sim, tb = _with_candidate(fw, phase=3_000)
        t = sim.now_ms
        sim.run_until(t + 3_001)
        ex.ok(sim.g["fallback_profile_cand_valid"], f"IE7 {name}: (setup) the candidate survives the first tick unchanged")
        sim.run_lambda(code)
        sim.run_until(t + 12_999)
        ex.ok(sim.g["fallback_profile_cand_valid"], f"IE7 {name}: the candidate may linger until the next tick (D9)")
        sim.run_until(t + 13_000)
        ex.ok(not sim.g["fallback_profile_cand_valid"], f"IE7 {name}: candidate cleared by the very next 10 s tick")
        ex.eq(txt(sim, "last_result"), f"REVIEW CLEARED - a temporary operation started ({dom})", f"IE7 {name}: B9")
        ex.eq((txt(sim, "review_id"), txt(sim, "review_slots"), sim.g["fallback_profile_capture_state"]), ("-", NONE_B5, 0), f"IE7 {name}: B4 / B5 cleared, IDLE")
        invariants(sim, ex, f"IE7 {name}", locked=False)
    for scr, dom in (("start_free_power_override", "Free Power"), ("restore_free_power_snapshot", "Free Power"), ("start_dump_to_grid_override", "Dump to Grid"),
                     ("restore_dump_to_grid_snapshot", "Dump to Grid"), ("apply_reg244_settings", "Register 244 test"), ("restore_reg244_snapshot", "Register 244 test"),
                     ("free_power_recovery_review", "Free Power")):
        sim, tb = _with_candidate(fw, phase=2_000)
        sim.hold_script_running(scr, 40_000)
        sim.run_until(sim.now_ms + 12_001)
        ex.ok(not sim.g["fallback_profile_cand_valid"] and txt(sim, "last_result") == f"REVIEW CLEARED - a temporary operation started ({dom})", f"IE7 script {scr}: cleared")
    # FP START between review and expiry: both the domain and the write counter change; the domain is named
    sim, tb = _with_candidate(fw, phase=2_000)
    sim.hold_script_running("start_free_power_override", 60_000)
    sim.run_lambda("id(free_power_start_attempts)++;")
    sim.run_until(sim.now_ms + 10_001)
    ex.ok(not sim.g["fallback_profile_cand_valid"] and "Free Power" in txt(sim, "last_result"), "T-CAP-13: FP START after the review: candidate cleared within one 10 s tick, reason names Free Power")
    for ctr in ("manual_write_attempts", "reg244_apply_attempts", "reg244_restore_attempts", "free_power_start_attempts", "dump_start_attempts"):
        sim, tb = _with_candidate(fw, phase=2_000)
        sim.run_lambda(f"id({ctr})++;")
        sim.run_until(sim.now_ms + 10_001)
        ex.ok(not sim.g["fallback_profile_cand_valid"], f"IE11 {ctr}: cleared within one tick")
        ex.eq(txt(sim, "last_result"), "REVIEW CLEARED - another ECCO write started since Review", f"IE11 {ctr}: B9")
        sim, tb = _with_candidate(fw, words=[0 if i == 0 else w for i, w in enumerate(GWORDS)], phase=2_000)
        sim.run_lambda(f"id({ctr})++;")
        sim.run_until(sim.now_ms + 10_001)
        ex.ok(not sim.g["fallback_profile_cand_valid"], f"IE11 {ctr}: a not-saveable preview is cleared too")
    sim, tb = _with_candidate(fw, phase=2_000)
    sim.run_lambda("id(manual_write_in_progress) = true;")
    sim.run_until(sim.now_ms + 35_000)
    ex.ok(sim.g["fallback_profile_cand_valid"] and txt(sim, "review").startswith("st=CANDIDATE_READY"), "a mutex-only change is not a write: the candidate survives (IE11 detects real writes)")
    sim, tb = _with_candidate(fw, phase=2_000)
    sim.run_until(sim.now_ms + 55_000)
    ex.ok(sim.g["fallback_profile_cand_valid"], "no change: the candidate survives five ticks")
    # earlier writes (non-zero counters at the review) are NOT a change since the review: the fingerprint covers all five counters
    sim = mk_sim(fw)
    sim.run_lambda("id(manual_write_attempts) = 3; id(reg244_apply_attempts) = 4; id(reg244_restore_attempts) = 5; "
                   "id(free_power_start_attempts) = 6; id(dump_start_attempts) = 7;")
    review(sim)
    sim.start_intervals(HK, phase=2_000)
    sim.run_for(55_000)
    ex.ok(sim.g["fallback_profile_cand_valid"] and sim.g["fallback_profile_cand_writes_fp"] == 3 + 4 + 5 + 6 + 7,
          "counters already non-zero at the review: the candidate survives five ticks, the fingerprint is their u32 sum")
    for ctr in ("manual_write_attempts", "reg244_apply_attempts", "reg244_restore_attempts", "free_power_start_attempts", "dump_start_attempts"):
        sim2 = mk_sim(fw)
        sim2.run_lambda("id(manual_write_attempts) = 3; id(reg244_apply_attempts) = 4; id(reg244_restore_attempts) = 5; "
                        "id(free_power_start_attempts) = 6; id(dump_start_attempts) = 7;")
        review(sim2)
        sim2.start_intervals(HK, phase=2_000)
        sim2.run_lambda(f"id({ctr})++;")
        sim2.run_for(11_000)
        ex.ok(not sim2.g["fallback_profile_cand_valid"], f"IE11 with non-zero counters: a bump of {ctr} clears the candidate")
    # IE3: a new review supersedes silently
    sim, tb = _with_candidate(fw, phase=2_000)
    sim.set_modbus_mode("deferred", 120)
    n_b9 = len(sim.ent(TS["B9"]).published)
    t = sim.now_ms
    press(sim)
    sim.run_until(t + 50)
    ex.ok(not sim.g["fallback_profile_cand_valid"] and txt(sim, "review_id") == "-" and txt(sim, "review_slots") == NONE_B5, "IE3: the old candidate is gone at the next press")
    ex.eq(txt(sim, "review"), f"st=READING;prior=-;exp=-;warn=-;obl={ALL_CLEAR_OBL};latch=-;sv=-", "IE3: B3 READING form")
    ex.eq([str(x) for x in sim.ent(TS["B9"]).published[n_b9:]], ["review in progress (read-only)"], "IE3: only `review in progress` was published - no 'superseded' outcome")
    sim.run_until_idle()
    ex.ok(sim.g["fallback_profile_cand_seq"] == 2 and txt(sim, "review").startswith("st=CANDIDATE_READY"), "IE3: the new candidate has sequence 2")
    return ex.fails


@behav("B-BRK", "P3 / T-CAP-16 (IE9): a leaked operation flag with no running dispatch for > 30 s is cleared by the breaker WITHOUT ever assigning manual_write_in_progress; INTERNAL text with the lock state")
def sc_breaker(fw):
    ex = Exp()
    for lock in (True, False):
        sim = mk_sim(fw)
        sim.start_intervals(HK, phase=1_000)
        t = sim.now_ms
        sim.run_lambda("id(fallback_profile_op_in_progress) = true; id(fallback_profile_capture_state) = 1; id(fallback_profile_op_purpose) = 1; "
                       "id(fallback_profile_step) = 2; id(fallback_profile_op_started_ms) = millis() - 31000; "
                       f"id(manual_write_in_progress) = {'true' if lock else 'false'};")
        sim.run_until(t + 1_000)
        ex.eq((sim.g["fallback_profile_op_in_progress"], sim.g["fallback_profile_capture_state"], sim.g["fallback_profile_op_purpose"], sim.g["fallback_profile_step"]),
              (False, 0, 0, 0), f"breaker (lock {lock}): FB flags cleared, capture IDLE, step 0")
        ex.eq(sim.g["manual_write_in_progress"], lock, f"breaker (lock {lock}): the shared mutex is NEVER assigned (stays {lock})")
        ex.eq(txt(sim, "last_result"), "INTERNAL - Fallback Profile operation state reset by watchdog; " + ("write lock still held - reboot required" if lock else "write lock free"), f"breaker (lock {lock}): INTERNAL text")
        ex.starts(txt(sim, "review"), "st=IDLE;", f"breaker (lock {lock}): B3 idle")
        invariants(sim, ex, f"breaker lock={lock}", locked=lock)
    # boundary: exactly 30 000 ms is not yet a leak, 30 001 is
    for age, fires in ((30_000, False), (30_001, True)):
        sim = mk_sim(fw)
        sim.start_intervals(HK, phase=1_000)
        t = sim.now_ms
        sim.at(t + 1_000, lambda s, age=age: s.run_lambda("id(fallback_profile_op_in_progress) = true; id(fallback_profile_op_started_ms) = millis() - %d;" % age))
        sim.run_until(t + 1_000)
        ex.eq(sim.g["fallback_profile_op_in_progress"], not fires, f"breaker age {age}: fires only above 30 000 ms")
    sim = mk_sim(fw)
    sim.start_intervals(HK, phase=1_000)
    sim.run_lambda("id(fallback_profile_op_in_progress) = true; id(fallback_profile_op_started_ms) = millis() - 10000;")
    sim.run_for(11_000)
    ex.ok(sim.g["fallback_profile_op_in_progress"], "a young operation (10 s) is left alone")
    sim = mk_sim(fw)
    sim.start_intervals(HK, phase=1_000)
    sim.run_lambda("id(fallback_profile_op_in_progress) = true; id(fallback_profile_op_started_ms) = millis() - 40000;")
    sim.hold_script_running("fallback_profile_capture_dispatch", 60_000)
    sim.run_for(11_000)
    ex.ok(sim.g["fallback_profile_op_in_progress"], "a RUNNING dispatch is never broken, however old")
    # V1 covers a LEAKED flag too (op_in_progress with no running dispatch): a press is refused untouched until the breaker clears it,
    # then (the mutex is free) the next press is accepted again
    sim = mk_sim(fw)
    sim.start_intervals(HK, phase=1_000)
    sim.run_lambda("id(fallback_profile_op_in_progress) = true; id(fallback_profile_op_started_ms) = millis() - 10000;")
    snap, m = sim.snapshot_state(), sim.mark()
    press(sim)
    sim.run_for(1)
    d = sim.state_diff(snap)
    ex.eq((d["globals"], d["published"]), ([], {TS["B9"]: [INFLIGHT_B9]}), "a leaked op flag: the press is refused by V1 and changes nothing but B9")
    ex.eq(sim.since(m).reads, [], "a leaked op flag: zero reads")
    sim.run_for(25_000)
    ex.ok(not sim.g["fallback_profile_op_in_progress"], "(setup) the breaker cleared the leaked flag")
    sn = review(sim)
    ex.eq(sn.violations(reads=FULL_READS), [], "after the breaker: a Review is accepted again (the mutex was free)")
    # the breaker also drops a candidate (IE9)
    sim, tb = _with_candidate(fw, phase=500)
    sim.run_lambda("id(fallback_profile_op_in_progress) = true; id(fallback_profile_op_started_ms) = millis() - 31000;")
    sim.run_until(sim.now_ms + 500)
    ex.ok(not sim.g["fallback_profile_cand_valid"] and txt(sim, "last_result").startswith("INTERNAL - Fallback Profile operation state reset by watchdog"), "IE9: the breaker also invalidates the candidate")
    # across the millis() wrap
    sim = mk_sim(fw)
    sim.rebase_clock(2 ** 32 - 5_000)
    sim.start_intervals(HK, phase=1_000)
    sim.run_lambda("id(fallback_profile_op_in_progress) = true; id(fallback_profile_op_started_ms) = millis() - 31000;")
    sim.run_for(12_000)
    ex.ok(not sim.g["fallback_profile_op_in_progress"], "breaker across the millis() wrap")
    return ex.fails


@behav("B-INTEG", "T-CAP-24: a purpose-integrity failure (the dispatch context is not a REVIEW) ends in INTERNAL, nothing written, no fresh stored-profile read, lock released")
def sc_integrity(fw):
    ex = Exp()
    sim = mk_sim(fw, mode=("deferred", 120))
    t0 = sim.now_ms
    m = sim.mark()
    press(sim)
    sim.at(t0 + 30, lambda s: s.run_lambda("id(fallback_profile_op_purpose) = 7;"))
    sim.run_until_idle()
    sn = sim.since(m)
    ex.eq(txt(sim, "last_result"), "INTERNAL - Fallback Profile dispatch context invalid; nothing written", "INTERNAL text")
    ex.eq((sn.writes, sn.nvs_sets, sn.commits), ([], [], []), "nothing written")
    ex.ok(reads_valid(sn.reads), f"the reads are a prefix of the four ({sn.reads})")
    ex.eq(len(sn.nvs_read_probes), 3, "no fresh FBP / FBW read: only the gate's three marker probes")
    ex.ok(not sim.g["fallback_profile_cand_valid"] and sim.g["fallback_profile_capture_state"] == 0, "no candidate")
    ex.starts(txt(sim, "review"), "st=IDLE;", "B3 idle")
    ex.eq((sim.g["fallback_profile_op_purpose"], sim.g["fallback_profile_step"], sim.g["manual_write_in_progress"]), (0, 0, False), "released: purpose 0, step 0, mutex free")
    invariants(sim, ex, "integrity")
    return ex.fails


# --------------------------------------------------------------------------- L2 previews and warnings
def _w(**over):
    """Golden words with registers replaced: keys are register numbers."""
    w = list(GWORDS)
    for reg, val in over.items():
        w[fc.REGS.index(int(reg.lstrip("r")))] = val
    return w


L2_CASES = [  # (label, words, expected sv value)
    ("244 = 0 (Allow Export)", _w(r244=0), "NO:244X"),
    ("244 = 1", _w(r244=1), "NO:244X"),
    ("244 = 3", _w(r244=3), "NO:244X"),
    ("power slot 1 = 499", _w(r256=499), "NO:PWRL1"),
    ("power slot 3 = 0", _w(r258=0), "NO:PWRL3"),
    ("power slot 6 = 8001 (above the site ceiling)", _w(r261=8001), "NO:PWRH6"),
    ("power slot 2 = 8000 is fine", _w(r257=8000), "OK"),
    ("power slot 2 = 500 is fine", _w(r257=500), "OK"),
    ("SOC slot 2 = 101", _w(r269=101), "NO:SOCH2"),
    ("SOC slot 2 = 100 is fine", _w(r269=100), "OK"),
    ("source word slot 4 = 2 (bits 0-1 > 1)", _w(r277=2), "NO:SRCG4"),
    ("source word slot 4 = 3", _w(r277=3), "NO:SRCG4"),
    ("source word slot 5 = 4 (mode bits 2-4)", _w(r278=4), "NO:MODE5"),
    ("source word slot 5 = 0x10 (mode bit 4)", _w(r278=0x10), "NO:MODE5"),
    ("source word slot 6 = 0x20 (other bit)", _w(r279=0x20), "NO:BITS6"),
    ("source word slot 6 = 0x8000", _w(r279=0x8000), "NO:BITS6"),
    ("source word slot 1 = 6 (source + mode)", _w(r274=6), "NO:SRCG1,MODE1"),
    ("HHMM slot 3 = 2400", _w(r252=2400), "NO:HHMM3"),
    ("HHMM slot 3 = 1260", _w(r252=1260), "NO:HHMM3"),
    ("HHMM slot 3 = 2359 is decodable", _w(r252=2359), "OK"),
    ("243 = 2", _w(r243=2), "NO:243X"),
    ("243 = 0 is fine", _w(r243=0), "OK"),
    ("three reasons", _w(r244=0, r256=100, r269=200), "NO:244X,PWRL1,SOCH2"),
    ("more than three reasons are counted", _w(r244=0, r256=100, r257=100, r269=200), "NO:244X,PWRL1,PWRL2+1"),
    ("232 / 248 / 230 / 245 / 247 are never refused", _w(r232=0xFFFF, r248=0xFFFF, r230=0xFFFF, r245=0xFFFF, r247=0xFFFF), "OK"),
]


@behav("B-L2", "L2 not-saveable previews: 244 != 2, power < 500 / > 8000, SOC > 100, source / mode / bits, undecodable HHMM, 243: the right sv codes, B9, B4 '-', B5 / B6 v=CAND, no sequence number used")
def sc_l2(fw):
    ex = Exp()
    for label, words, sv in L2_CASES:
        sim = mk_sim(fw, words=words)
        sn = review(sim)
        ex.eq(sn.violations(reads=FULL_READS), [], f"{label}: the four reads")
        b3 = txt(sim, "review")
        ex.ok(b3.endswith(f";sv={sv}"), f"{label}: sv code is {sv}: {b3[-60:]!r}")
        ex.eq(sim.g["fallback_profile_cand_sv"], sv, f"{label}: cand_sv global")
        if sv == "OK":
            ex.starts(b3, "st=CANDIDATE_READY;", f"{label}: a candidate")
            ex.starts(txt(sim, "last_result"), "CANDIDATE READY - ", f"{label}: B9")
        else:
            ex.starts(b3, "st=CANDIDATE_NOT_SAVEABLE;prior=VALID;exp=120;", f"{label}: B3")
            ex.starts(txt(sim, "last_result"), "CANDIDATE NOT SAVEABLE - ", f"{label}: B9")
            ex.eq(txt(sim, "review_id"), "-", f"{label}: B4 is '-'")
            ex.ok(sim.g["fallback_profile_cand_valid"] and not sim.g["fallback_profile_cand_saveable"] and sim.g["fallback_profile_cand_seq"] == 0, f"{label}: preview kept, not saveable, sequence number not used")
        ex.starts(txt(sim, "review_slots"), "v=CAND;", f"{label}: B5 v=CAND")
        ex.starts(txt(sim, "review_context"), "v=CAND;", f"{label}: B6 v=CAND")
        invariants(sim, ex, label)
    return ex.fails


WARN_CASES = [  # (label, words, expected warn=)
    ("W1 FP overlay look-alike", _w(r268=100, r269=100, r270=100, r271=100, r272=100, r273=100, r274=1, r275=1, r276=1, r277=1, r278=1, r279=1), "W1"),
    ("W2 uniform power <= 3000 W", _w(r256=2000, r257=2000, r258=2000, r259=2000, r260=2000, r261=2000), "W2"),
    ("W3 TOU switch (248 bit 0) off", _w(r248=0), "W3"),
    ("W4 grid charge off with a grid source", _w(r232=0x0010), "W4"),
    ("W5 start off the 5-minute grid", _w(r251=537), "W5"),
    ("W6 ring invalid (duplicate times)", _w(r250=0, r251=0, r252=0, r253=0, r254=0, r255=0), "W6"),
    ("no warning", list(GWORDS), "-"),
    ("W3 + W5", _w(r248=0, r251=537), "W3,W5"),
    # boundary cases (review TESTS5): the exact edges of W2 / W3 / W6, and their neighbours that must NOT warn
    ("W2 uniform power at exactly 3000 W", _w(r256=3000, r257=3000, r258=3000, r259=3000, r260=3000, r261=3000), "W2"),
    ("no W2 for a uniform 3001 W (just above the limit)", _w(r256=3001, r257=3001, r258=3001, r259=3001, r260=3001, r261=3001), "-"),
    ("no W2 when one slot differs (2000 x 5, 2001)", _w(r256=2000, r257=2000, r258=2000, r259=2000, r260=2000, r261=2001), "-"),
    ("W3 for an even non-zero 248 (= 2: bit 0 clear)", _w(r248=2), "W3"),
    ("no W3 for 248 = 3 (bit 0 set, other bits ignored)", _w(r248=3), "-"),
    # minutes 0, 720, 360, 1080, 180, 540: every delta is positive (720, 1080, 720, 540, 360, 900) but they sum to 4320, not 1440
    ("W6 for a positive-delta non-monotone ring 0000/1200/0600/1800/0300/0900", _w(r250=0, r251=1200, r252=600, r253=1800, r254=300, r255=900), "W6"),
    ("no W6 for a valid ring 0000/0400/0800/1200/1600/2000", _w(r250=0, r251=400, r252=800, r253=1200, r254=1600, r255=2000), "-"),
]


@behav("B-WARN", "warnings W1-W6 are shown (display only): the candidate stays saveable, no sv refusal, B3 warn= lists exactly the right ones")
def sc_warn(fw):
    ex = Exp()
    for label, words, warn in WARN_CASES:
        sim = mk_sim(fw, words=words)
        review(sim)
        b3_born = txt(sim, "review")
        sim.start_intervals(HK, phase=9_999)
        sim.run_until(sim.now_ms + 9_999)
        ex.eq(txt(sim, "review"), b3_born.replace("exp=120;", "exp=110;"), f"{label}: the 10 s tick refresh keeps warn / sv / prior / obl and changes only exp")
        ex.has(txt(sim, "review"), f";warn={warn};", f"{label}: warn=")
        ex.eq(sim.g["fallback_profile_cand_warnings"], 0 if warn == "-" else sum(1 << (int(w[1]) - 1) for w in warn.split(",")), f"{label}: cand_warnings bit mask (bit n-1 = Wn)")
        ex.starts(txt(sim, "review"), "st=CANDIDATE_READY;", f"{label}: still a saveable candidate (a warning never refuses)")
        ex.has(txt(sim, "review"), ";sv=OK", f"{label}: sv=OK")
        invariants(sim, ex, label)
    return ex.fails


# --------------------------------------------------------------------------- the stored profile, divergence, reboot
@behav("B-STORED", "stored-profile interplay: prior class / eligibility / fingerprint per class; dx / dc / di masks against a TRUSTED stored profile (authentic AND class != UNREADABLE) and '-' otherwise (H3, review FW0: '-' exactly when B7 / B8 are v=NONE)")
def sc_stored(fw):
    ex = Exp()
    cases = [  # seed -> (prior name, saveable, prior gen, prior binding, expected dx against the stored profile or None)
        ("none", "NOT_CAPTURED", True, 0, 0, None),
        ("valid", "VALID", True, 7, GOLD["binding"], "00000"),
        ("invalidated", "INVALIDATED", True, 8, None, "00000"),
        ("corrupt", "CORRUPT", True, None, None, None),
        ("wsize", "CORRUPT", True, 0, 40, None),
        ("corrupt_domain", "CORRUPT_DOMAIN", True, 7, None, "00001"),   # the stored 244 is 7, the live one 2
        ("unreadable", "UNREADABLE", False, 0, 0, None),
        ("lost", "PROFILE_LOST", True, 0, 0, None),
        ("stale", "PROFILE_STALE", True, 5, None, "00000"),
    ]
    for seed, prior, saveable, pg, pb, dx_exp in cases:
        sim = mk_sim(fw, seed=seed)
        sn = review(sim)
        t = f"stored {seed}"
        ex.eq(sn.violations(reads=FULL_READS), [], f"{t}: four reads, nothing written")
        b3 = txt(sim, "review")
        ex.starts(b3, f"st={'CANDIDATE_READY' if saveable else 'CANDIDATE_NOT_SAVEABLE'};prior={prior};exp=120;", f"{t}: B3 prior / saveable")
        ex.eq(fd.save_class_permitted([k for k, v in CLASS.items() if v == prior][0]), saveable, f"{t}: eligibility agrees with save_class_permitted")
        ex.eq(txt(sim, "review_id") == "-", not saveable, f"{t}: B4 is '-' iff not saveable")
        if pg is not None:
            ex.eq(sim.g["fallback_profile_cand_prior_gen"], pg, f"{t}: prior generation")
        if pb is not None:
            ex.eq(sim.g["fallback_profile_cand_prior_binding"], pb, f"{t}: prior binding")
        if saveable:
            cls_no = [k for k, v in CLASS.items() if v == prior][0]
            ex.eq(txt(sim, "review_id"), "%016X" % fc.candidate_id(1, 1, cls_no, sim.g["fallback_profile_cand_prior_gen"], sim.g["fallback_profile_cand_prior_binding"], GWORDS), f"{t}: candidate id binds the prior fingerprint")
        has = dx_exp is not None
        ex.eq(sim.g["fallback_profile_cand_has_stored"], has, f"{t}: cand_has_stored is the TRUSTED-profile predicate")
        if not has:
            ex.ok(txt(sim, "review_slots").endswith("dx=-") and txt(sim, "review_context").endswith("dc=-;di=-"), f"{t}: masks are '-' without a trusted stored profile")
            ex.eq((sim.g["fallback_profile_cand_dx"], sim.g["fallback_profile_cand_dc"], sim.g["fallback_profile_cand_di"]), (0, 0, 0), f"{t}: no masks stored")
        else:
            ex.ok(txt(sim, "review_slots").endswith(f"dx={dx_exp}") and txt(sim, "review_context").endswith("dc=000;di=00"), f"{t}: masks computed against the trusted stored profile (dx={dx_exp})")
        # B7 / B8 and the masks agree: the saved views are v=SAVED exactly when the masks are shown
        ex.eq(txt(sim, "slots").startswith("v=SAVED;"), has, f"{t}: B7 is v=SAVED iff the masks are shown")
        invariants(sim, ex, t)
    # H3 (review FW0): an AUTHENTIC stored profile under an effective class UNREADABLE is NOT trusted - B7 / B8 are v=NONE, B1 says
    # UNREADABLE, so the masks are '-' too (never "identical to the saved profile" next to "no saved profile"): has_stored false,
    # dx / dc / di '-', cand_dx / cand_dc / cand_di 0.
    def _untrusted(sim, t):
        ex.starts(txt(sim, "review"), "st=CANDIDATE_NOT_SAVEABLE;prior=UNREADABLE;", f"{t}: UNREADABLE, not saveable")
        ex.eq(txt(sim, "review_id"), "-", f"{t}: B4 '-'")
        ex.ok(txt(sim, "review_slots").endswith("dx=-"), f"{t}: B5 ends dx=- (got {txt(sim, 'review_slots')[-24:]!r})")
        ex.ok(txt(sim, "review_context").endswith("dc=-;di=-"), f"{t}: B6 ends dc=-;di=- (got {txt(sim, 'review_context')[-24:]!r})")
        ex.eq((sim.g["fallback_profile_cand_has_stored"], sim.g["fallback_profile_cand_dx"], sim.g["fallback_profile_cand_dc"], sim.g["fallback_profile_cand_di"]),
              (False, 0, 0, 0), f"{t}: cand_has_stored false, no masks")
        ex.eq((txt(sim, "state"), txt(sim, "slots"), txt(sim, "context")), ("UNREADABLE", NONE_B7, NONE_B8), f"{t}: B1 UNREADABLE, B7 / B8 NONE")
    # (1) a boot read error that heals: the fresh read is authentic, the class stays UNREADABLE (sticky anomaly)
    sim = mk_sim(fw, seed="none", pre=lambda s: (s.nvs_direct.put(K_P, fp.pack_profile(GOLD)), s.nvs_direct.read_faults.__setitem__(K_P, [fd.IDF_FAIL])))
    sn = review(sim)
    _untrusted(sim, "boot read error that heals")
    # (2) the review's repro: a valid FBP + a witness whose CRC is bad (the witness cannot be read) -> UNREADABLE
    sim = mk_sim(fw, seed="none", pre=lambda s: (s.nvs_direct.put(K_P, fp.pack_profile(GOLD)), s.nvs_direct.put(K_W, prov_bytes(7, GOLD["binding"], 6), crc_ok=False)))
    sn = review(sim)
    _untrusted(sim, "valid FBP + CRC-bad witness")
    # masks: one differing register at a time against the trusted (VALID) golden profile
    mask_cases = [("244", {"r244": 0}, "dx=00001", None), ("256", {"r256": 1000}, "dx=00002", None), ("257", {"r257": 1000}, "dx=00004", None),
                  ("261", {"r261": 2000}, "dx=00040", None), ("268", {"r268": 90}, "dx=00080", None), ("273", {"r273": 90}, "dx=01000", None),
                  ("274", {"r274": 0}, "dx=02000", None), ("279", {"r279": 0}, "dx=40000", None),
                  ("232 bit0", {"r232": 0x0010}, "dx=00000", ("dc=001", "di=00")), ("243", {"r243": 0}, "dx=00000", ("dc=002", "di=00")),
                  ("248 bit0", {"r248": 0}, "dx=00000", ("dc=004", "di=00")), ("250", {"r250": 5}, "dx=00000", ("dc=008", "di=00")),
                  ("255", {"r255": 2335}, "dx=00000", ("dc=100", "di=00")),
                  ("230", {"r230": 190}, "dx=00000", ("dc=000", "di=01")), ("245", {"r245": 7000}, "dx=00000", ("dc=000", "di=02")),
                  ("247", {"r247": 0}, "dx=00000", ("dc=000", "di=04")), ("232 bits1-15", {"r232": 0x0013}, "dx=00000", ("dc=000", "di=08")),
                  ("248 bits1-15", {"r248": 3}, "dx=00000", ("dc=000", "di=10"))]
    for label, over, dx, dcdi in mask_cases:
        sim = mk_sim(fw, words=_w(**over))
        review(sim)
        ex.has(txt(sim, "review_slots"), f";{dx}", f"mask {label}: B5 {dx}")
        ex.eq(sim.g["fallback_profile_cand_dx"], int(dx.split("=")[1], 16), f"mask {label}: cand_dx global")
        ex.ok(sim.g["fallback_profile_cand_has_stored"] is True, f"mask {label}: cand_has_stored")
        if dcdi:
            ex.has(txt(sim, "review_context"), f";{dcdi[0]};{dcdi[1]}", f"mask {label}: B6 {dcdi}")
            ex.eq((sim.g["fallback_profile_cand_dc"], sim.g["fallback_profile_cand_di"]), (int(dcdi[0].split("=")[1], 16), int(dcdi[1].split("=")[1], 16)), f"mask {label}: cand_dc / cand_di globals")
        invariants(sim, ex, f"mask {label}")
    return ex.fails


@behav("B-DIVERGE", "the same-boot divergence rule: the stored profile changing / vanishing / turning corrupt after the boot read -> UNREADABLE, not saveable, sticky until reboot; never offered as NOT_CAPTURED")
def sc_diverge(fw):
    ex = Exp()
    flips = {
        "FBP turns corrupt": lambda s: s.nvs_direct.put(K_P, bytes(range(96))),
        "FBP vanishes": lambda s: s.nvs_direct.blobs.pop(K_P, None),
        "FBP becomes another valid generation": lambda s: s.nvs_direct.put(K_P, fp.pack_profile(gold_profile(generation=8))),
        "FBP wrong size": lambda s: s.nvs_direct.put(K_P, bytes(40)),
        "witness vanishes": lambda s: s.nvs_direct.blobs.pop(K_W, None),
        "witness changes": lambda s: s.nvs_direct.put(K_W, prov_bytes(9, 0x1234, 8)),
    }
    for name, flip in flips.items():
        sim = mk_sim(fw)
        ex.eq(txt(sim, "state"), "VALID", f"{name}: boot VALID")
        flip(sim)
        sn = review(sim)
        ex.eq(sn.violations(reads=FULL_READS), [], f"{name}: the four reads, nothing written")
        ex.eq(txt(sim, "state"), "UNREADABLE", f"{name}: B1 UNREADABLE (never NOT_CAPTURED / VALID)")
        ex.has(txt(sim, "summary"), ";why=ANOM;", f"{name}: B2 why=ANOM")
        ex.starts(txt(sim, "review"), "st=CANDIDATE_NOT_SAVEABLE;prior=UNREADABLE;", f"{name}: not saveable")
        ex.eq(txt(sim, "review_id"), "-", f"{name}: B4 '-'")
        ex.ok(sim.g["fallback_profile_read_anomaly"] != 0, f"{name}: sticky anomaly bit set")
        ex.eq((txt(sim, "slots"), txt(sim, "context")), (NONE_B7, NONE_B8), f"{name}: B7 / B8 show NO saved profile")
        ex.ok(txt(sim, "review_slots").endswith("dx=-") and txt(sim, "review_context").endswith("dc=-;di=-")
              and sim.g["fallback_profile_cand_has_stored"] is False, f"{name}: the masks are '-' too (H3: no trusted stored profile)")
        # sticky: even if the store looks healthy again the same boot never trusts it
        SEEDS["valid"](sim)
        sn = review(sim)
        ex.eq(txt(sim, "state"), "UNREADABLE", f"{name}: still UNREADABLE on the next review (sticky)")
        ex.starts(txt(sim, "review"), "st=CANDIDATE_NOT_SAVEABLE;prior=UNREADABLE;", f"{name}: still not saveable")
        invariants(sim, ex, name)
        sim2 = sim.reboot()
        sim2.run_boot()
        sim2.random_values = [0]
        sim2.bank.update(bank_for(GWORDS))
        ex.ok(sim2.g["fallback_profile_read_anomaly"] == 0, f"{name}: a reboot re-derives everything (anomaly cleared)")
    # a transient read error that heals is an anomaly too
    sim = mk_sim(fw)
    sim.nvs_direct.read_faults[K_P] = [fd.IDF_FAIL]
    review(sim)
    ex.eq(txt(sim, "state"), "UNREADABLE", "a runtime read error of the stored profile -> UNREADABLE")
    return ex.fails


@behav("B-NVSFAULT", "storage faults at review time fail CLOSED: an unavailable / handle-less NVS latches every marker unreadable (zero reads, nothing written); an unhealthy partition makes the fresh read UNREADABLE (not saveable)")
def sc_nvs_fault(fw):
    ex = Exp()
    for name, flip in (("NVS unavailable", lambda s: setattr(s.nvs_direct, "unavailable", True)), ("NVS handle 0", lambda s: setattr(s.nvs_direct, "handle_value", 0))):
        for seed in ("valid", "none"):
            sim = mk_sim(fw, seed=seed)
            flip(sim)
            sn = review(sim)
            refused(ex, sim, sn, f"{name} ({seed})")
            ex.has(txt(sim, "last_result"), "recovery marker became unreadable at runtime", f"{name} ({seed}): the unreadable-marker text")
            ex.eq(latch_of(sim), "FP,DP,R4", f"{name} ({seed}): all three markers latched")
            ex.eq([o for o in sn.nvs_ops if o[0] == "set"], [], f"{name} ({seed}): no NVS set")
    for seed in ("valid", "none"):   # an unhealthy partition AT BOOT: the boot read is UNREADABLE (anomaly), nothing is offered as a saved profile
        sim = mk_sim(fw, seed=seed, pre=lambda s: setattr(s.nvs_direct, "healthy", False))
        ex.eq(txt(sim, "state"), "UNREADABLE", f"unhealthy NVS at boot ({seed}): B1 UNREADABLE")
        ex.has(txt(sim, "summary"), ";why=ANOM;", f"unhealthy NVS at boot ({seed}): B2 why=ANOM")
        ex.eq((txt(sim, "slots"), txt(sim, "context")), (NONE_B7, NONE_B8), f"unhealthy NVS at boot ({seed}): B7 / B8 show no saved profile")
    for seed in ("valid", "none"):
        sim = mk_sim(fw, seed=seed)
        sim.nvs_direct.healthy = False
        sn = review(sim)
        ex.eq(sn.violations(reads=FULL_READS), [], f"unhealthy NVS ({seed}): the four reads, nothing written")
        ex.starts(txt(sim, "review"), "st=CANDIDATE_NOT_SAVEABLE;prior=UNREADABLE;", f"unhealthy NVS ({seed}): the stored profile is UNREADABLE -> not saveable")
        ex.eq(txt(sim, "state"), "UNREADABLE", f"unhealthy NVS ({seed}): B1 UNREADABLE")
        invariants(sim, ex, f"unhealthy NVS {seed}")
    return ex.fails


@behav("B-REBOOT", "P3: a candidate / latch / salt never survives a reboot; the register bank and the NVS are untouched; a power cut mid-review leaves nothing behind")
def sc_reboot(fw):
    ex = Exp()
    sim, tb = _with_candidate(fw)
    sim2 = sim.reboot()
    sim2.run_boot()
    ex.eq(txt(sim2, "review"), IDLE_B3, "reboot: B3 idle form")
    ex.ok(sim2.g["fallback_profile_cand_valid"] is False and sim2.g["fallback_profile_boot_salt"] == 0 and sim2.g["fallback_profile_probe_latch"] == 0 and sim2.g["fallback_profile_cand_seq"] == 0, "reboot: no candidate, salt 0, latch 0, sequence 0")
    ex.eq((txt(sim2, "review_id"), txt(sim2, "review_slots"), txt(sim2, "last_result")), ("-", NONE_B5, SEED_B9), "reboot: B4 / B5 / B9 back to their boot values")
    ex.eq(sim2.nvs_direct.set_count(), 0, "reboot: nothing was ever written to the NVS")
    # a latch does not survive a reboot (the boot re-derives); the damaged marker was already erased by the read (honest C6 residual)
    sim = mk_sim(fw, markers=[("fp", 1, {"legacy": False})])
    review(sim)
    ex.eq(latch_of(sim), "FP", "(setup) latched")
    sim2 = sim.reboot()
    sim2.run_boot()
    ex.eq(txt(sim2, "review"), IDLE_B3, "reboot: the latch is gone from B3")
    # power cut at every event of a deferred review: the next boot is clean, nothing was written
    sim = mk_sim(fw, mode=("deferred", 120))
    t0 = sim.now_ms
    press(sim)
    sim.at_power_cut(t0 + 250)
    try:
        sim.run_until_idle()
        ex.ok(False, "power cut: PowerCut was not raised")
    except H.PowerCut:
        pass
    ex.eq((sim.nvs_direct.set_count(), [x for x in sim.modbus_log if x[0] == "write"]), (0, []), "power cut mid-review: nothing written")
    sim2 = sim.reboot()
    sim2.run_boot()
    ex.eq(txt(sim2, "review"), IDLE_B3, "after the power cut: clean boot, no candidate")
    ex.ok(sim2.g["manual_write_in_progress"] is False and sim2.g["fallback_profile_op_in_progress"] is False, "after the power cut: no lock")
    sn = review(sim2)
    ex.eq(sn.violations(reads=FULL_READS), [], "after the power cut: a fresh review works")
    return ex.fails


@behav("B-B9", "B9 sequences: seed -> in progress -> READY -> refusal (arm) -> READY -> mismatch -> expiry; each transition is published exactly once, in order")
def sc_b9(fw):
    ex = Exp()
    sim = mk_sim(fw)
    sim.start_intervals(HK, phase=0)
    review(sim)
    sim.ent(ARMS[0]).set(True)
    review(sim)
    sim.ent(ARMS[0]).set(False)
    review(sim)
    _mutator(sim, 0, 2)
    review(sim)
    sim.read_override_fn = None
    review(sim)
    t = sim.now_ms
    sim.run_until(t + 135_000)
    got = [str(x) for x in sim.ent(TS["B9"]).published]
    want = [SEED_B9, "review in progress (read-only)", "CANDIDATE READY - both read passes agree",
            "REVIEW REFUSED - a Free Power / Dump to Grid", "review in progress (read-only)", "CANDIDATE READY - both read passes agree",
            "review in progress (read-only)", "REVIEW NOT COMPLETED - live configuration changed", "review in progress (read-only)",
            "CANDIDATE READY - both read passes agree", "REVIEW EXPIRED - candidate expired (120 s); review again"]
    ex.ok(len(got) == len(want) and all(g.startswith(w) for g, w in zip(got, want)), f"B9 publication sequence: {[g[:30] for g in got]}")
    invariants(sim, ex, "b9 sequence")
    return ex.fails


# --------------------------------------------------------------------------- T-CAP-22: a power cut at every instant of a review
CUT_TIMES = sorted(set(list(range(0, 520, 13)) + [1, 119, 120, 121, 239, 240, 241, 359, 360, 361, 479, 480, 481]
                       + [600, 700, 800, 900, 1000, 1200, 1500, 1800, 2000, 2200, 2400, 2500, 2800, 3000, 3100, 3300, 3500, 3600, 3800, 4000,
                          4500, 5000, 5500, 6000, 6500, 6900, 6990, 7000, 7100, 7300]))
CUT_CONFIGS = (  # (label, modbus mode, bus held for ms before the press)
    ("deferred 120 ms, bus free", ("deferred", 120), 0),
    ("deferred 120 ms, bus held 6.8 s", ("deferred", 120), 6800),
    ("immediate, bus held 6.8 s", None, 6800),
)


def _nvs_image(sim) -> dict:
    return {k: (bytes(b.data), b.crc_ok, b.chunk_present) for k, b in sim.nvs_direct.blobs.items()}


@behav("B-CUT", "T-CAP-22: a power cut at ~80 instants (0..7300 ms) of a review - idle wait, each read, the final step; deferred and immediate hub: nothing written, the NVS image unchanged, the next boot clean, a fresh review works")
def sc_power_cut_sweep(fw):
    ex = Exp()
    cuts = Counter()
    for label, mode, hold in CUT_CONFIGS:
        for cut in CUT_TIMES:
            if hold == 0 and cut > 600:
                continue                      # the review is over long before (4 x 120 ms); the later cuts only repeat the bus-held rows
            sim = mk_sim(fw, mode=mode)
            if hold:
                sim.hold_bus(hold)
                sim.run_for(1)
            image = _nvs_image(sim)
            t0 = sim.now_ms
            tag = f"{label}, cut at +{cut} ms"
            press(sim)
            sim.at_power_cut(t0 + cut)
            try:
                sim.run_until_idle()
                cut_here = False
            except H.PowerCut:
                cut_here = True
            cuts[label] += cut_here
            ex.eq((sim.nvs_direct.set_count(), [x for x in sim.modbus_log if x[0] == "write"], list(sim.nvs_commits)), (0, [], []), f"{tag}: nothing written")
            ex.ok(reads_valid([(e[1], len(e[2])) for e in sim.modbus_log if e[0] == "read"]), f"{tag}: the reads so far are a prefix of the four")
            sim2 = sim.reboot()
            sim2.run_boot()
            ex.eq(txt(sim2, "review"), IDLE_B3, f"{tag}: the next boot is clean (B3 idle form, no candidate)")
            ex.ok(not sim2.g["manual_write_in_progress"] and not sim2.g["fallback_profile_op_in_progress"] and not sim2.g["fallback_profile_cand_valid"]
                  and sim2.g["fallback_profile_probe_latch"] == 0 and sim2.g["fallback_profile_boot_salt"] == 0, f"{tag}: no lock, no op flag, no candidate, no latch")
            ex.eq(_nvs_image(sim2), image, f"{tag}: the NVS image is byte-for-byte what it was before the review")
            sim2.random_values = [0]
            sim2.bank.update(bank_for(GWORDS))
            review(sim2)                       # asserts the four reads and no write
            ex.starts(txt(sim2, "review"), "st=CANDIDATE_READY;", f"{tag}: a fresh review works after the cut")
    for label, _m, hold in CUT_CONFIGS:
        ex.ok(cuts[label] >= 25, f"{label}: the sweep really cut the review ({cuts[label]} cuts)")
    ex.ok(len(CUT_TIMES) >= 80 and CUT_TIMES[0] == 0 and CUT_TIMES[-1] >= 7000, f"{len(CUT_TIMES)} cut instants over 0..{CUT_TIMES[-1]} ms")
    return ex.fails


# --------------------------------------------------------------------------- T-CAP-08 / 13 / 17 with the REAL writer scripts
def mk_writer_sim(fw, **kw):
    """A booted sim in which the TEST starts REAL writer scripts (the review itself never writes). Built outside ALL_SIMS - the
    matrix-wide 'no simulator ever wrote / only FB scripts ran' sweeps are about the Review - and asserted by its own scenario."""
    keep = _SINK[0]
    _SINK[0] = []
    try:
        return mk_sim(fw, **kw)
    finally:
        _SINK[0] = keep


def prime_manual_slot1(sim):
    """The entity states the REAL apply_manual_slot1 needs to be admitted (the harness models no select, so the two options are set)."""
    sim.ent("manual_config_write_enable").set(True)
    sim.ent("configuration_online").set(True)
    for name, val in (("manual_slot1_start_hhmm", 100), ("manual_slot1_end_hhmm", 500), ("manual_slot1_power", 3000), ("manual_slot1_soc", 50)):
        sim.ent(name).set(val)
    sim.ent("manual_stage_grid_charge_enabled").set(True)
    sim.ent("manual_slot1_charge_source").current_option = lambda: ds.CStr("Grid")
    sim.ent("manual_slot1_mode").current_option = lambda: ds.CStr("General")
    sim.run_lambda("id(manual_slot1_staging_loaded) = true; id(manual_config_raw_cache_valid) = true; id(manual_cfg_reg274_raw) = 1; "
                   "id(manual_cfg_reg232_raw) = 0x11;")


def prime_free_power(sim):
    sim.ent("free_power_write_enable").set(True)
    sim.ent("configuration_online").set(True)
    sim.ent("ecco_battery_voltage").set(52.0)
    sim.ent("free_power_duration_minutes").set(30)
    sim.ent("free_power_max_power").set(3000)
    sim.run_lambda("id(ntp_synced) = true;")


def prime_dump(sim):
    sim.ent("dump_write_enable").set(True)
    sim.ent("configuration_online").set(True)
    sim.ent("configuration_polling").set(True)
    sim.ent("ecco_battery_voltage").set(52.0)
    sim.ent("ecco_battery_soc").set(80.0)
    sim.ent("dump_stop_soc").set(30.0)
    sim.ent("dump_export_power").set(2000.0)
    sim.ent("dump_duration_minutes").set(30)
    sim.ent("ecco_grid_ct_power").set(0.0)
    sim.run_lambda("id(ntp_synced) = true; id(dump_soc_last_update_ms) = millis(); id(cfg_block_b_seq) = 1; id(cfg_block_b_ok_ms) = millis(); "
                   "id(dump_grid_last_update_ms) = millis();")


WRITERS = (  # (script, its counter, the prime function)
    ("apply_manual_slot1", "manual_write_attempts", prime_manual_slot1),
    ("start_free_power_override", "free_power_start_attempts", prime_free_power),
    ("start_dump_to_grid_override", "dump_start_attempts", prime_dump),
)
IE11_B9 = "REVIEW CLEARED - another ECCO write started since Review"


@behav("B-WRITERS", "T-CAP-08 / T-CAP-13 with the REAL writers: after a Review the real apply_manual_slot1 (IE11) and start_free_power_override (IE7) run through the harness - each bumps ITS counter in its own accept branch, writes the inverter itself (not the review), and the candidate is cleared within one 10 s tick with the right reason")
def sc_real_writers(fw):
    ex = Exp()
    # (1) the REAL apply_manual_slot1: IE11 (a counter of the writes fingerprint moved)
    sim = mk_writer_sim(fw)
    review(sim)
    ex.starts(txt(sim, "review"), "st=CANDIDATE_READY;", "manual: a READY candidate")
    sim.start_intervals(HK, phase=2_000)
    prime_manual_slot1(sim)
    ctrs0 = {k: sim.g[k] for k in COUNTER_IDS}
    m = sim.mark()
    sim.start_script("apply_manual_slot1")
    sim.run_until_idle()
    sim.run_until(sim.now_ms + 12_000)               # the real writer has finished; at least one more 10 s tick has run
    sw = sim.since(m)
    ex.eq((ctrs0["manual_write_attempts"], sim.g["manual_write_attempts"]), (0, 1), "manual: the REAL apply_manual_slot1 bumped manual_write_attempts in its accept branch")
    ex.eq({k: v for k, v in {k: sim.g[k] for k in COUNTER_IDS}.items() if k != "manual_write_attempts"},
          {k: v for k, v in ctrs0.items() if k != "manual_write_attempts"}, "manual: no other counter moved")
    ex.ok([w[1] for w in sw.writes][:2] == [232, 250], f"manual: the real writer issued its own register writes ({[w[1] for w in sw.writes]}) - the review issued none")
    ex.ok(not sim.g["fallback_profile_cand_valid"] and txt(sim, "last_result") == IE11_B9, f"manual: IE11 cleared the candidate ({txt(sim, 'last_result')[:70]!r})")
    ex.eq((txt(sim, "review_id"), txt(sim, "review_slots"), sim.g["fallback_profile_capture_state"]), ("-", NONE_B5, 0), "manual: B4 / B5 cleared, IDLE")
    ex.ok(not sim.g["manual_write_in_progress"], "manual: the writer released the shared mutex")
    # (2) the REAL start_free_power_override: IE7 (the Free Power domain turned non-clear) and, as well, IE11 (its counter)
    sim = mk_writer_sim(fw)
    review(sim)
    sim.start_intervals(HK, phase=2_000)
    prime_free_power(sim)
    m = sim.mark()
    sim.start_script("start_free_power_override")
    sim.run_until_idle()
    sim.run_until(sim.now_ms + 12_000)
    sw = sim.since(m)
    g = sim.g
    ex.eq(g["free_power_start_attempts"], 1, "free power: the REAL start_free_power_override bumped free_power_start_attempts in its accept branch")
    ex.ok(bool(sw.writes) and g["free_power_snapshot_valid"] and g["free_power_active_persisted"], "free power: the real writer wrote the inverter and took the lease (its writes, not the review's)")
    ex.ok(not g["fallback_profile_cand_valid"] and txt(sim, "last_result") == "REVIEW CLEARED - a temporary operation started (Free Power)",
          f"free power: IE7 cleared the candidate and names Free Power ({txt(sim, 'last_result')[:70]!r})")
    ex.ok(fc.writes_fingerprint(g["manual_write_attempts"], g["reg244_apply_attempts"], g["reg244_restore_attempts"], g["free_power_start_attempts"], g["dump_start_attempts"])
          != g["fallback_profile_cand_writes_fp"], "free power: the writes fingerprint moved too (IE11 alone would also have cleared it)")
    # (3) control: the same states without starting a writer leave the candidate alone for the same time
    for script, ctr, prime in WRITERS[:2]:
        sim = mk_writer_sim(fw)
        review(sim)
        sim.start_intervals(HK, phase=2_000)
        prime(sim)
        sim.run_until(sim.now_ms + 25_000)
        ex.ok(sim.g["fallback_profile_cand_valid"] and sim.g[ctr] == 0, f"control ({script}): priming the writer's entity states alone does not clear the candidate")
    return ex.fails


@behav("B-COLLIDE", "T-CAP-17: a Free Power / Dump to Grid START and a Manual TOU apply arriving while the review holds the shared mutex are REJECTED by their own existing gates (counters untouched, nothing written), the review completes with exactly the four reads, and the retry after the review is admitted")
def sc_collision(fw):
    ex = Exp()
    # positive controls: with the mutex FREE the very same primed start is admitted (so the mutex was the only reason below)
    for script, ctr, prime in WRITERS:
        sim = mk_writer_sim(fw)
        prime(sim)
        try:
            sim.start_script(script)
        except H.FbbNotModelled:
            pass   # the harness does not model one of the writer's LATER lambdas (a char* table); its accept branch - which bumps the counter - ran first
        ex.eq(sim.g[ctr], 1, f"control: {script} is admitted when nothing holds the mutex ({ctr} == 1)")
    sim = mk_writer_sim(fw, mode=("deferred", 120))
    sim.start_intervals(HK, phase=3_000)
    t0 = sim.now_ms
    m = sim.mark()
    press(sim)
    sim.run_until(t0 + 190)                          # parked in R2: the review owns the mutex
    ex.ok(sim.g["manual_write_in_progress"] is True and sim.g["fallback_profile_op_in_progress"] is True and sim.g["fallback_profile_step"] == 2,
          "the review is parked in R2 holding the shared write mutex")
    for _script, _ctr, prime in WRITERS:
        prime(sim)
    m2 = sim.mark()
    for script, ctr, _prime in WRITERS:
        sim.start_script(script)
        sim.run_for(5)
        ex.eq(sim.g[ctr], 0, f"{script} arriving during the review: rejected by its own gate ({ctr} untouched)")
    sc = sim.since(m2)
    ex.eq([e[0] for e in sc.executed], [w[0] for w in WRITERS], "all three starts were really issued (and refused)")
    ex.eq((sc.writes, sc.nvs_ops, sc.commits), ([], [], []), "the refused starts wrote nothing and touched no NVS")
    ex.ok(not sim.g["free_power_operation_in_progress"] and not sim.g["dump_operation_in_progress"] and not sim.g["free_power_snapshot_valid"]
          and not sim.g["dump_snapshot_valid"], "no lease and no operation flag was taken")
    ex.ok(sim.g["manual_write_in_progress"] is True and sim.g["fallback_profile_op_in_progress"] is True, "the mutex and the review are undisturbed")
    sim.run_until_idle()
    sn = sim.since(m)
    ex.eq(sn.violations(reads=FULL_READS), [], "the review still completes with exactly the four reads and no write")
    ex.eq(sn.writes, [], "nothing at all was written during the collision")
    ex.starts(txt(sim, "review"), "st=CANDIDATE_READY;", "the review's candidate is READY")
    ex.eq(txt(sim, "review_id"), "%016X" % fc.candidate_id(1, 1, 5, 7, GOLD_ID_BINDING, GWORDS), "the candidate is that of a clean run")
    ex.ok(sim.g["manual_write_in_progress"] is False, "the mutex is released after the review")
    # the retry after the review (the HA schedule retries ~33 s later) is admitted - and only THEN does the candidate go (IE7)
    sim.run_until(sim.now_ms + 25_000)
    ex.ok(sim.g["fallback_profile_cand_valid"], "the candidate survived the refused starts (no counter moved)")
    prime_free_power(sim)
    sim.start_script("start_free_power_override")
    ex.eq(sim.g["free_power_start_attempts"], 1, "the retry of the Free Power start after the review is admitted")
    sim.run_until_idle()
    sim.run_until(sim.now_ms + 12_000)
    ex.ok(not sim.g["fallback_profile_cand_valid"] and "Free Power" in txt(sim, "last_result"), "the admitted start then clears the candidate (IE7 names Free Power)")
    return ex.fails


# --------------------------------------------------------------------------- P5: no side effect outside the FB state; fuzz
FB_GLOBAL_PREFIX = ("fallback_profile_", "fallback_witness_")


def _zero_effects(ex: Exp, sim, snap, sn, tag: str, ignore=()):
    d = sim.state_diff(snap, ignore=ignore)
    stray = [g for g in d["globals"] if not g.startswith(FB_GLOBAL_PREFIX) and g != "manual_write_in_progress"]
    ex.eq(stray, [], f"{tag}: no non-FB global changed (the shared mutex is the only shared one)")
    ex.ok(set(d["published"]) <= NINE, f"{tag}: only B1-B9 were published ({sorted(set(d['published']) - NINE)})")
    ex.ok({sid for sid, _p in sn.executed} <= set(FB_SCRIPT_IDS), f"{tag}: only the FB scripts were executed ({[s for s, _p in sn.executed]})")
    ex.eq((sn.violations(), reads_valid(sn.reads)), ([], True), f"{tag}: no write / NVS set / commit, and the reads are a prefix of the four ({sn.reads})")
    ex.ok(sim.g["manual_write_in_progress"] is False, f"{tag}: the shared mutex is back to free")


@behav("B-ZERO", "P5: across a whole review (accepted, refused, failed, mismatched, expired, cleared, breaker) no non-FB global changes, only B1-B9 are published, only FB scripts run, the mutex is free again")
def sc_zero(fw):
    ex = Exp()
    runs = {}

    def run(tag, setup=None, after=None, mode=None, ticks=False, ignore=()):
        sim = mk_sim(fw, mode=mode)
        if setup:
            setup(sim)
        if ticks:
            sim.start_intervals(HK, phase=1_000)
        snap, m = sim.snapshot_state(), sim.mark()
        press(sim)
        sim.run_until_idle()
        if after:
            after(sim)
        _zero_effects(ex, sim, snap, sim.since(m), tag, ignore)
        invariants(sim, ex, tag)
        return sim
    run("accepted")
    run("accepted deferred", mode=("deferred", 120))
    run("refused by an arm", setup=lambda s: s.ent(ARMS[1]).set(True))
    run("refused by a lease", setup=lambda s: s.run_lambda(FP_RAM["FP active lease"][0]))
    run("refused by a latch probe", setup=lambda s: s.seed_marker(MARKER_TAGS["dump"], 2, legacy=False))
    run("failed read", setup=lambda s: s.queue_frames("ok", "no_response"))
    run("pass mismatch", setup=lambda s: _mutator(s, 0, 2))
    run("expiry", ticks=True, after=lambda s: s.run_for(135_000))
    run("IE11", ticks=True, after=lambda s: (s.run_lambda("id(dump_start_attempts)++;"), s.run_for(11_000)), ignore=("dump_start_attempts",))

    sim = mk_sim(fw)
    sim.start_intervals(HK, phase=1_000)
    snap = sim.snapshot_state()
    sim.run_lambda("id(fallback_profile_op_in_progress) = true; id(fallback_profile_op_started_ms) = millis() - 31000;")
    sim.run_for(11_000)
    d = sim.state_diff(snap)
    ex.eq([g for g in d["globals"] if not g.startswith(FB_GLOBAL_PREFIX)], [], "breaker: no non-FB global changed")
    ex.ok(set(d["published"]) <= NINE, "breaker: only B1-B9 published")
    return ex.fails


FUZZ_ARMS = list(ARMS)
FUZZ_BUS = ["correction_in_progress", "verification_pending", "verification_read_active", "free_power_operation_in_progress",
            "free_power_recovery_force_in_progress", "free_power_recovery_accept_in_progress", "reg244_apply_in_progress", "dump_operation_in_progress"]
FUZZ_LEASE = ["id(free_power_snapshot_valid) = %s; id(free_power_marker_state) = %d;", "id(dump_snapshot_valid) = %s; id(dump_marker_state) = %d;",
              "id(reg244_snapshot_valid) = %s; id(reg244_marker_state) = %d;"]
FUZZ_SCRIPTS = ["start_free_power_override", "restore_dump_to_grid_snapshot", "apply_reg244_settings", "poll_inverter_telemetry", "poll_inverter_configuration_dispatch"]
FUZZ_COUNTERS = ["manual_write_attempts", "reg244_apply_attempts", "free_power_start_attempts", "dump_start_attempts"]
FUZZ_OUTCOMES = ["ok", "ok", "ok", "ok", "error", "no_response", "not_sent", "custom_response"]


def reads_valid(reads) -> bool:
    """True when `reads` is a concatenation of prefixes of the four reads (each review issues a prefix: fail-fast)."""
    states = {0}
    for r in reads:
        nxt = set()
        for s in states:
            if s < 4 and r == FULL_READS[s]:
                nxt.add(s + 1)
            if r == FULL_READS[0]:
                nxt.add(1)
        states = nxt
        if not states:
            return False
    return True


def fuzz_run(fw, seed: int) -> list[str]:
    rng = random.Random(seed)
    ex = Exp(f"[fuzz seed {seed}] ")
    sim = H.FbbSim(fw)
    _SINK[0].append(sim)
    sim.seed_rng(rng.randrange(1 << 30))
    for dom, tag in MARKER_TAGS.items():
        r = rng.random()
        if r < 0.08:
            sim.seed_marker(tag, rng.choice([0, 1, 2]), legacy=False)
        elif r < 0.12:
            sim.seed_marker(tag, 0, legacy=False, crc_ok=False)
        elif r < 0.15:
            sim.seed_marker(tag, 0, legacy=False, size=24)
        elif r < 0.25:
            sim.seed_marker(tag, 0)
    r = rng.random()
    if r < 0.75:
        SEEDS["valid"](sim) if rng.random() < 0.85 else sim.nvs_direct.put(K_P, fp.pack_profile(GOLD))
    elif r < 0.85:
        sim.nvs_direct.put(K_P, bytes(rng.randrange(256) for _ in range(96)))
    r = rng.random()
    if r < 0.1:
        _fbs_seed(rng.choice(["clear", "episode", "corrupt", "unreadable"]))(sim)
    sim.run_boot()
    sim.bank.update(bank_for(GWORDS))
    sim.start_intervals(HK, phase="random")
    reads_total: list = []
    for _ in range(rng.randrange(4, 14)):
        a = rng.random()
        if a < 0.34:
            m = sim.mark()
            press(sim)
            if rng.random() < 0.25:
                sim.run_for(rng.randrange(1, 4000))
                press(sim)
            sim.run_until_idle()
            sn = sim.since(m)
            ex.ok(not sn.writes and not sn.nvs_sets and not sn.commits, "a write / nvs set / commit during a review")
            ex.ok(reads_valid(sn.reads), f"odd read sequence {sn.reads}")
            reads_total += sn.reads
        elif a < 0.42:
            sim.set_modbus_mode(rng.choice(["immediate", "deferred"]), rng.choice([20, 120, 400]))
        elif a < 0.52:
            sim.queue_frames(*[rng.choice(FUZZ_OUTCOMES) for _ in range(rng.randrange(1, 5))])
        elif a < 0.60:
            w = list(GWORDS)
            k = rng.randrange(31)
            w[k] = rng.choice([w[k] + 1, 0, 65535, rng.randrange(65536)])
            sim.bank.update(bank_for(w))
        elif a < 0.64:
            _mutator(sim, rng.randrange(31), rng.randrange(1, 4))
        elif a < 0.69:
            sim.ent(rng.choice(FUZZ_ARMS)).set(rng.random() < 0.5)
        elif a < 0.74:
            sim.run_lambda("id(%s) = %s;" % (rng.choice(FUZZ_BUS), rng.choice(["true", "false"])))
        elif a < 0.80:
            sim.run_lambda(rng.choice(FUZZ_LEASE) % (rng.choice(["true", "false"]), rng.choice([0, 1, 2])))
        elif a < 0.85:
            sim.run_lambda("id(%s)++;" % rng.choice(FUZZ_COUNTERS))
        elif a < 0.90:
            sim.hold_script_running(rng.choice(FUZZ_SCRIPTS), rng.randrange(500, 12000))
        elif a < 0.94:
            sim.hold_bus(rng.randrange(200, 9000))
        elif a < 0.96:
            sim.at_bank(sim.now_ms + rng.randrange(1, 800), bank_for([(x + 1) & 0xFFFF if rng.random() < 0.2 else x for x in GWORDS]))
        else:
            sim.run_for(rng.randrange(1000, 60000))
        sim.run_for(rng.randrange(0, 3000))
    sim.run_for(15000)
    sim.run_until_idle()
    for e in safety_errors(sim) + text_errors(sim) + consistency_errors(sim) + idle_errors(sim):
        ex.ok(False, e)
    ex.ok(reads_valid([(e[1], len(e[2])) for e in sim.modbus_log if e[0] == "read"]), "odd global read sequence")
    return ex.fails


@behav("B-FUZZ", "seeded fuzz, 300 runs: random presses / overlapping presses / bank mutations / arms / bus + lease flags / held bus / failure frames / markers / interval phases: every run ends with the safety invariants")
def sc_fuzz(fw):
    out = []
    for seed in range(300):
        try:
            out += fuzz_run(fw, seed)
        except ds.Unsupported as ex_:
            out.append(f"seed {seed}: harness {type(ex_).__name__}: {str(ex_)[:120]}")
        except Exception as ex_:  # noqa: BLE001
            out.append(f"seed {seed}: {type(ex_).__name__}: {str(ex_)[:160]}")
    return out


@behav("B-FUZZQ", "the same fuzz, 30 runs (the mutation matrix uses this form)")
def sc_fuzz_quick(fw):
    out = []
    for seed in range(1000, 1030):
        try:
            out += fuzz_run(fw, seed)
        except ds.Unsupported as ex_:
            out.append(f"seed {seed}: harness {type(ex_).__name__}: {str(ex_)[:120]}")
        except Exception as ex_:  # noqa: BLE001
            out.append(f"seed {seed}: {type(ex_).__name__}: {str(ex_)[:160]}")
    return out


# --------------------------------------------------------------------------- every text FB-B1 can publish (mirror sweep)
def card_regexes() -> list[tuple[str, int, str]]:
    """Every regex literal in the Energy Actions card's TypeScript source that is used with `.test(` (named constants and inline
    literals): (pattern, flags, origin). The same extraction as test_failback_shadow_core.card_regexes()."""
    out, seen = [], set()
    files = sorted(CARD_SRC.glob("*.ts")) + sorted((CARD_SRC / "utils").glob("*.ts"))
    for f in files:
        src = f.read_text(encoding="utf-8")
        pats = [m for m in re.finditer(r"const\s+\w+\s*=\s*/((?:\\.|[^/\n\\])+)/([a-z]*)\s*;", src)]
        pats += [m for m in re.finditer(r"(?<![\w/])/((?:\\.|[^/\n\\])+)/([a-z]*)\.test\(", src)]
        for m in pats:
            key = (m.group(1), m.group(2))
            if key in seen:
                continue
            seen.add(key)
            out.append((m.group(1), re.I if "i" in m.group(2) else 0, f.name))
    return out


def _randomise(obj, rng):
    import dataclasses
    for f in dataclasses.fields(obj):
        cur = getattr(obj, f.name)
        if dataclasses.is_dataclass(cur):
            _randomise(cur, rng)
        elif isinstance(cur, bool):
            setattr(obj, f.name, rng.random() < 0.18)
        elif isinstance(cur, int):
            n = f.name
            if n.endswith("boot_load"):
                v = rng.choice([0, 1, 2, 3, 255, 0, 1, 9])
            elif n.endswith("marker_state"):
                v = rng.choice([0, 0, 0, 1, 2, 5])
            elif n == "dump_containment_state":
                v = rng.choice([0, 0, 0, 1, 3, 5, 8, 200])
            elif n == "fbs_slot":
                v = rng.choice([0, 1, 2, 3, 4, 5, 6, 0x101, 0x205, 255])
            elif n == "probe_latch":
                v = rng.choice([0, 0, 0, 1, 2, 3, 4, 0x10, 0x30, 0x200, 0x421, 0xFFF])
            elif n.endswith("_ms"):
                v = rng.choice([0, 1000, 299_999, 300_000, 900_000, rng.randrange(1 << 32)])
            else:
                v = rng.randrange(0, 4)
            setattr(obj, f.name, v)


def mirror_texts() -> dict[str, set]:
    """Every B9-class text and every B1-B8 string the mirror builders produce over a sweep (independent of the YAML)."""
    rng = random.Random(20260930)
    b9: set = set()
    grid: set = set()
    svs: set = set()

    def add(s):
        b9.add(str(s))
    for fn in (fc.refused_in_flight_text, fc.refused_not_loaded_text, fc.refused_arms_text, fc.review_in_progress_text, fc.candidate_ready_text,
               fc.internal_context_text, fc.review_expired_text, fc.review_cleared_writes_text, fc.b9_seed_text):
        add(fn())
    for lock in (True, False):
        add(fc.breaker_text(lock))
    for slot in (fc.SLOT_FP, fc.SLOT_DUMP, fc.SLOT_R244):
        add(fc.review_cleared_domain_text(slot))
    for code in range(0, 9):
        for step in range(0, 6):
            for exc in (0, 2, 0x0B, 0xFF):
                add(fc.read_fail_text(code, step, exc))
    for _ in range(2500):
        g = fc.GateInputs()
        _randomise(g, rng)
        g.boot_loaded = rng.random() < 0.9
        pr = fc.ProbeResults()
        for dom in ("fp", "dump", "r244"):
            setattr(pr, dom, rng.choice([fc.PROBE_NONE, fc.PROBE_CLEAR, fc.PROBE_ABSENT, fc.PROBE_UNREADABLE, fc.PROBE_MALFORMED,
                                         fc.PROBE_RESTORE_REQUIRED, fc.PROBE_PENDING_CLEAR]))
        r = fc.gate_decide(g, pr)
        if r.code not in (fc.GATE_ACCEPT, fc.GATE_NEED_PROBE):
            add(r.text)
        grid.add(str(r.obl))
    words = [list(GWORDS)]
    for k in range(31):
        for val in (0, 1, 2, 3, 4, 100, 101, 499, 500, 8000, 8001, 2359, 2360, 2400, 65535):
            w = list(GWORDS)
            w[k] = val
            words.append(w)
    for _ in range(300):
        w = list(GWORDS)
        for k in rng.sample(range(31), rng.randrange(1, 8)):
            w[k] = rng.choice([0, 1, 2, 4, 6, 0x20, 101, 499, 8001, 2400, 1260, 65535, rng.randrange(65536)])
        words.append(w)
    for w in words:
        ref = fc.capture_refusals(w, 8000)
        for cls in range(0, 9):
            for anomaly in (0, 1):
                add(fc.not_saveable_text(ref, w, cls, anomaly))
        svs.add(str(fc.sv_text(ref)))
    for _ in range(300):
        a, b = list(GWORDS), list(GWORDS)
        for k in rng.sample(range(31), rng.randrange(1, 5)):
            b[k] = rng.randrange(65536)
        if fc.first_diff(a, b) >= 0:
            add(fc.pass_mismatch_text(a, b))
    return {"b9": b9, "grid": grid, "sv": svs}


STATE: dict = {}


@static("S-CARD", "every text FB-B1 can publish (mirror builders over a sweep + the FB lambda literals) is <= 200 chars, matches NO Energy Actions card regex (case-insensitive), none of the D8 hazard words, and B9 texts carry a D8 prefix")
def d_card(c):
    v = []
    if "mirror" not in STATE:
        STATE["mirror"] = mirror_texts()
        STATE["rx"] = card_regexes()
    rx = STATE["rx"]
    if len(rx) < 19 or not any(p == "^FAILED" for p, _f, _o in rx):
        v.append(f"only {len(rx)} card regex literals found (the TypeScript source moved?)")
    b9 = STATE["mirror"]["b9"]
    lits = {l for x in c.fb_lambda_texts().values() for l in literals(x) if l}
    for s in sorted(b9 | lits):
        if len(s) > 200:
            v.append(f"{len(s)} chars: {s[:50]!r}")
        for p, fl, o in rx:
            if re.search(p, s, re.I):
                v.append(f"card regex {p!r} ({o}) matches {s[:60]!r}")
        for h in D8_HAZARD:
            if h.search(s):
                v.append(f"D8 hazard {h.pattern!r} in {s[:60]!r}")
    for s in sorted(b9):
        if not s.startswith(B9_PREFIXES):
            v.append(f"B9 text with no D8 prefix: {s[:60]!r}")
    for s in sorted(x for x in STATE["mirror"]["grid"] if x):
        if not RX["review"].fullmatch("st=IDLE;prior=-;exp=-;warn=-;obl=%s;latch=-;sv=-" % s):
            v.append(f"obl vector off-grammar: {s!r}")
    for s in sorted(STATE["mirror"]["sv"]):
        if not RX["review"].fullmatch("st=IDLE;prior=-;exp=-;warn=-;obl=-;latch=-;sv=%s" % s) or len(s) > 40:
            v.append(f"sv value off-grammar: {s!r}")
    STATE["n_texts"] = len(b9)
    return v






# ===========================================================================
# [C] COMPILE: every FB lambda, for real
# ===========================================================================
def compile_section(fw: dict) -> None:
    from concurrent.futures import ThreadPoolExecutor
    cxx = LC.find_compiler()
    print(f"    compiler: {cxx}")
    check("a C++ compiler is available ($ECCO_CXX, g++ / c++ / clang++ on PATH, or ESPHome's xtensa GCC) - this check FAILS rather than skips",
          cxx is not None, LC.NO_CXX)
    lams = LC.lambdas_of(fw)
    kinds = Counter(l.kind for l in lams)
    handlers = sum(1 for l in lams if l.params)
    check(f"the walker found every FB lambda: {len(lams)} ({kinds['void']} actions + {kinds['bool']} conditions, {handlers} Modbus reply handlers) across the gate, "
          "the dispatch (idle wait, 4 reads x 5 handlers, step / post-wait lambdas, final, release), the invalidate script, the tick and the boot lambda",
          len(lams) == 47 and handlers == 20 and kinds["void"] + kinds["bool"] == 47, str(dict(kinds)))
    controls = {
        "a type error in a lambda (const char* assigned to a uint8_t global)": ("fallback_profile_step", dict(inject=("capture_dispatch[4]", 'id(fallback_profile_step) = "text";'))),
        "a misspelled ecco_fbcap field (gi.bus.now_msx)": ("now_msx", dict(rename=("gi.bus.now_ms", "gi.bus.now_msx"))),
        "a misused std::array size (pass1 declared with 30 elements)": ("pass1", dict(type_override={"fallback_profile_pass1": "std::array<uint16_t, 30>"})),
        "a misspelled ecco_fbcap function (b3_textx)": ("b3_textx", dict(rename=("ecco_fbcap::b3_text(", "ecco_fbcap::b3_textx("))),
        "-Werror has teeth: an unused variable is an error": ("unused_fbb1_probe", dict(inject=("capture_dispatch[4]", "int unused_fbb1_probe = 5;"))),
        "a serial-log call whose argument does not match its %u conversion (the log stubs are printf-checked)": ("format", dict(inject=("capture_dispatch[4]", 'ESP_LOGI("fbcap", "x %u", "text");'))),
    }
    if cxx is None:
        for name in controls:
            check(f"negative control rejected by a REAL compile: {name}", False, LC.NO_CXX)
        return
    with ThreadPoolExecutor(max_workers=4) as pool:
        f_real = pool.submit(LC.compile_all, fw)
        f_ctl = {n: pool.submit(LC.compile_rejects, fw, needle, "gnu++20", **kw) for n, (needle, kw) in controls.items()}
        real = f_real.result()
        ctl = {n: f.result() for n, f in f_ctl.items()}
    check("every FB lambda compiles clean with -fsyntax-only -Wall -Wextra -Werror under gnu++17 AND gnu++20, against the REAL "
          "ecco_fallback_profile.h / ecco_fallback_durable_model.h / ecco_fallback_capture.h (ESPHome symbols are stubs)", not real, "; ".join(real)[:500])
    for name, (ok, out) in ctl.items():
        check(f"negative control: {name} is rejected by the compiler itself (rc != 0, an `error:` line naming the defect)", ok, out[:300])
    # a stub set that does not know an id must fail loudly, never compile vacuously
    check("negative control: a lambda that references an unknown id() is refused by the TU builder (never a vacuous compile)",
          _raises(lambda: LC.build_source(fw, lams + [LC.Lam("x", "void", "", "id(no_such_symbol_xyz) = 1;")]), ValueError))


# ===========================================================================
# [M] MUTATION: deliberately broken copies of the live firmware, each killed by named detectors
# ===========================================================================
def mutate(text: str, old: str, new: str, count: int = 1) -> str:
    n = text.count(old)
    if n != count:
        raise AssertionError(f"mutation anchor occurs {n} times, want {count}: {old[:80]!r}")
    return text.replace(old, new)


def mutate_re(text: str, pattern: str, repl, count: int = 1, flags: int = re.M) -> str:
    n = len(re.findall(pattern, text, flags))
    if n != count:
        raise AssertionError(f"mutation pattern matches {n} times, want {count}: {pattern[:80]!r}")
    return re.sub(pattern, repl if callable(repl) else (lambda m: repl), text, flags=flags)


def mutate_nth(text: str, old: str, new: str, n: int, total: int) -> str:
    """Replace only the n-th (1-based) of exactly `total` occurrences."""
    if text.count(old) != total:
        raise AssertionError(f"mutation anchor occurs {text.count(old)} times, want {total}: {old[:80]!r}")
    i = -1
    for _ in range(n):
        i = text.index(old, i + 1)
    return text[:i] + new + text[i + len(old):]


def _guard_re(k: int) -> str:
    return r"if \(!id\(fallback_profile_op_in_progress\) \|\| id\(fallback_profile_step\) != %d\) return;" % k


def _m_drop_guard_r2_response(t):
    return mutate_re(t, _guard_re(2) + r"\n([ ]+)id\(fallback_profile_step_terminal\) = true;\n([ ]+)if \(!ecco_fbcap::store_block_241\(id\(fallback_profile_pass1\)",
                     lambda m: f"id(fallback_profile_step_terminal) = true;\n{m.group(2)}if (!ecco_fbcap::store_block_241(id(fallback_profile_pass1)")


def _m_terminal_first(t):
    return mutate_re(t, _guard_re(1) + r"\n([ ]+)id\(fallback_profile_step_terminal\) = true;\n([ ]+id\(fallback_profile_read_failed\) = true;\n[ ]+id\(fallback_profile_read_fail_code\) = ecco_fbcap::READ_EXCEPTION;)",
                     lambda m: f"id(fallback_profile_step_terminal) = true;\n{m.group(1)}if (!id(fallback_profile_op_in_progress) || id(fallback_profile_step) != 1) return;\n{m.group(2)}")


def _m_drop_custom_r3(t):
    return mutate_re(t, r"^[ ]+on_custom_response:\n[ ]+then:\n[ ]+- lambda: \|-\n[ ]+" + _guard_re(3) + r"\n(?:[ ]+.*\n){3}", "")


def _m_no_failfast(t):
    return mutate_nth(t, "lambda: 'return !id(fallback_profile_read_failed);'", "lambda: 'return true;'", 2, 4)


def _edit_script(t: str, sid: str, fn) -> str:
    """Apply `fn` to the raw text of one script block only (the block ends at the next list item / top-level key)."""
    m = re.search(r"^  - id: %s\n" % re.escape(sid), t, re.M)
    if not m:
        raise AssertionError(f"script {sid} not found")
    nxt = re.search(r"^(?:  - id: |\S)", t[m.end():], re.M)
    end = m.end() + (nxt.start() if nxt else len(t))
    return t[:m.start()] + fn(t[m.start():end]) + t[end:]


def _m_reuse_node(t):
    def edit(b):
        b = mutate_nth(b, "start_address: 230\n", "start_address: 241\n", 2, 2)
        return mutate_nth(b, "count: 3\n", "count: 53\n", 2, 2)
    return _edit_script(t, "fallback_profile_capture_dispatch", edit)


def _m_30_words(t):
    return mutate(t, "ecco_fbcap::first_diff(id(fallback_profile_pass1), id(fallback_profile_pass2)) >= 0)",
                  "ecco_fbcap::first_diff(id(fallback_profile_pass1), id(fallback_profile_pass2)) >= 0 &&\n"
                  "           ecco_fbcap::first_diff(id(fallback_profile_pass1), id(fallback_profile_pass2)) < 30)")


def _m_cache_words(t):
    return mutate_re(t, r"^([ ]+)ri\.words = id\(fallback_profile_pass2\);\n",
                     lambda m: m.group(0) + f"{m.group(1)}ri.words[0] = (uint16_t) id(manual_cfg_reg244_raw);\n")


def _m_probe_first(t):
    t = mutate(t, "if (r.code == ecco_fbcap::GATE_NEED_PROBE) {", "if (true) {")
    for d in ("fp", "dump", "r244"):
        t = mutate(t, f"if (r.probe_{d}) {{", "if (true) {")
    return t


def _m_clear_latch(t):
    return mutate(t, "id(fallback_profile_probe_latch) = r.latch;", "id(fallback_profile_probe_latch) = 0;")


def _m_no_arms(t):
    return mutate(t, "gi.free_power_write_enable = id(free_power_write_enable).state;", "gi.free_power_write_enable = false;")


def _m_drop_bus_term(t):
    return mutate(t, "gi.bus.verification_pending = id(verification_pending);", "gi.bus.verification_pending = false;", 2)


def _m_drop_ie11(t):
    return mutate_re(t, r"\) != id\(fallback_profile_cand_writes_fp\)\) \{", ") != id(fallback_profile_cand_writes_fp) && false) {")


def _m_drop_ie7(t):
    return mutate(t, "if (dom != ecco_fbcap::SLOT_NONE) {", "if (false) {")


def _m_breaker_releases(t):
    return mutate(t, "ecco_fbcap::TextBuf brk = ecco_fbcap::breaker_text(lock_held);", "id(manual_write_in_progress) = false;\n            ecco_fbcap::TextBuf brk = ecco_fbcap::breaker_text(lock_held);")


def _m_interval_eof(t):
    start = t.index("  # Fallback Profile REVIEW (FB-B1) - RAM-only housekeeping.")
    end = t.index("  # Failback Shadow (FB-C1) - RAM-only, zero-authority evaluator.")
    block = t[start:end]
    t = t[:start] + t[end:]
    return t.rstrip("\n") + "\n\n" + block.rstrip("\n") + "\n"


def _m_no_integrity(t):
    return mutate(t, "if (!ecco_fbcap::review_integrity_ok(id(fallback_profile_op_in_progress), id(fallback_profile_op_purpose))) {", "if (false) {")


def _m_b4_unsaveable(t):
    return mutate(t, "ecco_fbcap::b4_text(v.eligible, v.id)", "ecco_fbcap::b4_text(true, v.id)")


def _m_ttl_130(t):
    return mutate(t, "ecco_fbcap::candidate_expired(now, id(fallback_profile_cand_ms))", "(uint32_t) (now - id(fallback_profile_cand_ms)) >= 130000")


def _m_not_wrap_safe(t):
    return mutate(t, "ecco_fbcap::candidate_expired(now, id(fallback_profile_cand_ms))", "now >= id(fallback_profile_cand_ms) + 120000")


def _m_salt_in_boot(t):
    return mutate_re(t, r"^([ ]+)ecco_fallback::FailbackStateV1 s\{\};\n", lambda m: f"{m.group(0)}{m.group(1)}id(fallback_profile_boot_salt) = random_uint32() | 1u;\n")


def _m_write_action(t):
    node = ("      - modbus_client.write_multiple_registers:\n"
            "          modbus_id: inverter_modbus\n"
            "          address: 0x01\n"
            "          start_address: 244\n"
            "          values: !lambda |-\n"
            "            return std::vector<uint16_t>{2};\n")
    return mutate_re(t, r"^      - lambda: \|-\n(?=[ ]+// REVIEW final step: integrity check first)", lambda m: node + m.group(0))


def _m_supervision(t):
    return mutate(t, "          const uint32_t now = millis();\n          // 1. Leak breaker", "          const uint32_t now = millis();\n          const bool sup_dummy = id(supervision_stable);\n          (void) sup_dummy;\n          // 1. Leak breaker")


def _m_b5_saved(t):
    return mutate(t, "ecco_fbcap::b5_text(true, id(fallback_profile_pass2), v.has_stored, v.dx)", "ecco_fbcap::b7_text(lp, p, e.cls)")


def _m_release_skip_mismatch(t):
    return mutate_re(t, r"^([ ]+)// The single release point, reached on every path of this script.\n",
                     lambda m: m.group(0) + f"{m.group(1)}if (ecco_fbcap::first_diff(id(fallback_profile_pass1), id(fallback_profile_pass2)) >= 0) return;\n")


def _m_swap_mismatch(t):
    return mutate(t, "ecco_fbcap::pass_mismatch_text(id(fallback_profile_pass1), id(fallback_profile_pass2))", "ecco_fbcap::pass_mismatch_text(id(fallback_profile_pass2), id(fallback_profile_pass1))")


def _m_failed_text(t):
    return mutate(t, "at boot); inverter writes locked - do NOT reboot", "at boot); inverter writes locked - read FAILED - do NOT reboot")


def _m_unclamped(t):
    return mutate(t, "id(fallback_profile_invalidate_reason) = brk.c_str();", 'id(fallback_profile_invalidate_reason) = brk.c_str();\n            id(fallback_profile_invalidate_reason) += "' + "x" * 150 + '";')


def _m_v1_touches(t):
    return mutate_re(t, r"^([ ]+)ecco_fbcap::TextBuf busy = ecco_fbcap::refused_in_flight_text\(\);\n",
                     lambda m: f"{m.group(1)}id(fallback_profile_capture_state) = 0;\n" + m.group(0))


def _m_step1(t):
    return mutate_re(t, r"id\(fallback_profile_step\) = 0;(\n[ ]+)id\(fallback_profile_capture_state\) = ecco_fbcap::CAPTURE_READING;",
                     lambda m: f"id(fallback_profile_step) = 1;{m.group(1)}id(fallback_profile_capture_state) = ecco_fbcap::CAPTURE_READING;")


def _m_boot_baseline(t):
    """Only the FIRST of the two `in.healthy = healthy;` lines (the boot lambda; the final lambda is the second)."""
    ms = list(re.finditer(r"^([ ]+)in\.healthy = healthy;\n", t, re.M))
    if len(ms) != 2:
        raise AssertionError(f"{len(ms)} `in.healthy = healthy;` lines, want 2")
    m = ms[0]
    return t[:m.end()] + f"{m.group(1)}in.baseline_valid = true;\n" + t[m.end():]


def _m_boot_loaded_early(t):
    return mutate_re(t, r"^([ ]+)ecco_fallback::FailbackStateV1 s\{\};\n", lambda m: f"{m.group(0)}{m.group(1)}id(fallback_profile_boot_loaded) = true;\n")


def _m_blk11_const(t):
    return mutate(t, "id(dump_marker_boot_load) = marker_load;", "id(dump_marker_boot_load) = 0;")


def _m_superseded_publishes(t):
    return mutate(t, "if (ecco_fbcap::invalidate_reason_publishes(id(fallback_profile_invalidate_reason).c_str())) {", "if (true) {")


def _m_idle_wait(t):
    return mutate_re(t, r"(tx_blocked\(\);'\n[ ]+timeout: )7000ms", lambda m: m.group(1) + "70000ms")


def _m_bounded_wait(t):
    return mutate_re(t, r"(id\(fallback_profile_step\) = 3;(?:(?!id\(fallback_profile_step\) = 4;).)*?timeout: )3000ms",
                     lambda m: m.group(1) + "30000ms", flags=re.M | re.S)


def _m_no_mutex_take(t):
    return mutate_re(t, r"(id\(fallback_profile_op_in_progress\) = true;\n)[ ]+id\(manual_write_in_progress\) = true;\n", lambda m: m.group(1))


def _m_release_keeps_mutex(t):
    return mutate_re(t, r"(id\(fallback_profile_op_in_progress\) = false;\n)[ ]+id\(manual_write_in_progress\) = false;\n(?=[ ]+id\(fallback_profile_step\) = 0;)", lambda m: m.group(1))


def _m_seq_not_bumped(t):
    return mutate(t, "if (v.eligible) id(fallback_profile_cand_seq) = ri.seq_next;", "// seq not bumped")


def _m_no_ie3(t):
    return mutate_re(t, r"^([ ]+)if \(id\(fallback_profile_cand_valid\)\) \{\n([ ]+id\(fallback_profile_invalidate_reason\) = ecco_fbcap::REASON_SUPERSEDED;)",
                     lambda m: f"{m.group(1)}if (false) {{\n{m.group(2)}")


def _m_cand_ms_unset(t):
    return mutate(t, "id(fallback_profile_cand_ms) = millis();", "// cand_ms not set")


def _m_tick_fingerprint(t):
    return mutate_nth(t, "(uint32_t) id(dump_start_attempts)) != id(fallback_profile_cand_writes_fp)", "(uint32_t) 0) != id(fallback_profile_cand_writes_fp)", 1, 1)


def _m_now_ms_zero(t):
    return mutate_nth(t, "gi.bus.now_ms = millis();", "gi.bus.now_ms = 0;", 1, 2)


def _m_r4_buffer(t):
    return mutate_re(t, r"(ecco_fbcap::store_block_241\(id\(fallback_profile_pass)2(\), values\))", lambda m: m.group(1) + "1" + m.group(2))


def _m_cand_from_pass1(t):
    return mutate(t, "id(fallback_profile_cand_words) = id(fallback_profile_pass2);", "id(fallback_profile_cand_words) = id(fallback_profile_pass1);")


def _m_dump_bus_lease(t):
    return mutate(t, "gi.dump.dump_snapshot_valid = id(dump_snapshot_valid);", "gi.dump.dump_snapshot_valid = false;", 2)


def _m_run_term(t):
    return mutate(t, "id(restore_free_power_snapshot_dispatch).is_running()", "false", 2)


def _m_warnings_zero(t):
    return mutate(t, "id(fallback_profile_cand_warnings) = v.warnings;", "id(fallback_profile_cand_warnings) = 0;")


def _m_class_mirror(t):
    """The final lambda no longer updates the RAM mirror of the class (the 2nd of the two assignments; the 1st is the boot lambda)."""
    return mutate_nth(t, "id(fallback_profile_class) = e.cls;", "id(fallback_profile_class) = 5;", 2, 2)


def _m_v1_running_only(t):
    return mutate(t, "if (id(fallback_profile_op_in_progress) || id(fallback_profile_capture_dispatch).is_running()) {",
                  "if (id(fallback_profile_capture_dispatch).is_running()) {")


def _m_tick_during_op(t):
    return mutate(t, "if (id(fallback_profile_cand_valid) && !id(fallback_profile_op_in_progress)) {", "if (id(fallback_profile_cand_valid)) {")


_GATE_IE3 = "          // IE3: a new Review supersedes any earlier candidate (its own outcome is not published).\n"


def _gate_insert(stmt: str):
    """Insert one statement at the top of the gate's decision section (before IE3)."""
    return lambda t: mutate(t, _GATE_IE3, f"          {stmt}\n" + _GATE_IE3)


def _m_boot_exec(t):
    return mutate(t, "          const uint8_t ls = ecco_fbdurable::read_direct_t(nvs, ecco_fbdurable::FAILBACK_STATE_KEY, s, dfs);\n",
                  "          const uint8_t ls = ecco_fbdurable::read_direct_t(nvs, ecco_fbdurable::FAILBACK_STATE_KEY, s, dfs);\n"
                  "          if (lp == 99) id(apply_reg244_settings).execute();\n")


def _m_inv_exec(t):
    return _edit_script(t, "fallback_profile_invalidate_candidate",
                        lambda b: mutate(b, "          if (id(fallback_profile_op_in_progress)) return;\n",
                                         "          if (id(fallback_profile_op_in_progress)) return;\n"
                                         "          if (id(fallback_profile_probe_latch) == 0x0FFF) id(apply_reg244_settings).execute();\n"))


def _m_log_in_handler(t):
    return mutate_nth(t, "id(fallback_profile_read_fail_code) = ecco_fbcap::READ_NO_RESPONSE;\n",
                      "id(fallback_profile_read_fail_code) = ecco_fbcap::READ_NO_RESPONSE;\n"
                      "                        ESP_LOGI(\"fbcap\", \"step %u failed\", (unsigned) 1);\n", 1, 4)


def _m_log_wrong_site(t):
    return mutate(t, "            ESP_LOGI(\"fbcap\", \"review refused: code=%u slot=%u\", (unsigned) r.code, (unsigned) r.slot);\n",
                  "            ESP_LOGI(\"fbcap\", \"review accepted: bus idle wait, then four read passes\");\n"
                  "            ESP_LOGI(\"fbcap\", \"review refused: code=%u slot=%u\", (unsigned) r.code, (unsigned) r.slot);\n")


def _m_log_uncast(t):
    return mutate(t, "(unsigned) r.code, (unsigned) r.slot);", "r.code, (unsigned) r.slot);")


def _m_drop_dump_counter(t):
    return _edit_script(t, "start_dump_to_grid_override", lambda b: mutate(b, "                id(dump_start_attempts)++;\n", ""))


def _m_drop_manual_counter(t):
    return _edit_script(t, "apply_manual_slot1", lambda b: mutate(b, "                id(manual_write_attempts)++;\n", ""))


def _m_tick_unconditional(t):
    return mutate_re(t, r"(id\(fallback_profile_probe_latch\), id\(fallback_profile_cand_sv\)\.c_str\(\)\);\n[ ]+)"
                        r"if \(id\(fallback_profile_review_text\)\.state != t\.c_str\(\)\) (id\(fallback_profile_review_text\)\.publish_state\(t\.c_str\(\)\);)",
                     lambda m: m.group(1) + m.group(2))


MUTANTS = [
    ("M01", "drop the `op_in_progress && step == K` guard of ONE handler (R2 on_response)", _m_drop_guard_r2_response, ["S-HANDLERS", "B-LATE"]),
    ("M02", "set the terminal flag BEFORE the guard (R1 on_error)", _m_terminal_first, ["S-HANDLERS", "B-LATE"]),
    ("M03", "drop on_custom_response on one read (R3)", _m_drop_custom_r3, ["S-HANDLERS", "B-FAIL"]),
    ("M04", "continue after a failed read (remove the fail-fast nesting after R1)", _m_no_failfast, ["S-NEST", "B-FAIL"]),
    ("M05", "reuse one read node for both passes (R3 reads 241/53)", _m_reuse_node, ["S-READS", "B-HAPPY"]),
    ("M06", "compare 30 words instead of 31 (a difference in the last word is ignored)", _m_30_words, ["S-FINAL", "B-MISMATCHQ"]),
    ("M07", "take a candidate word from the config-poll cache (manual_cfg_reg244_raw)", _m_cache_words, ["S-FINAL", "B-HAPPY"]),
    ("M08", "probe the markers before / without the RAM legs (probes always run)", _m_probe_first, ["S-PROBE", "B-ARMS"]),
    ("M09", "clear the probe latch (set it to 0 every gate)", _m_clear_latch, ["S-PROBE", "B-PROBE"]),
    ("M10", "skip the arms check (the arm input is hard-wired false)", _m_no_arms, ["S-GATEIN", "B-ARMS"]),
    ("M11", "drop one BUS term (verification_pending) from the gate inputs", _m_drop_bus_term, ["S-GATEIN", "B-BUS"]),
    ("M12", "drop IE11 (another write started since Review)", _m_drop_ie11, ["S-IVRAM", "B-IE"]),
    ("M13", "drop IE7 (a recovery domain turned non-clear)", _m_drop_ie7, ["S-IVRAM", "B-IE"]),
    ("M14", "the breaker releases manual_write_in_progress", _m_breaker_releases, ["S-IVRAM", "S-PAIR", "B-BRK"]),
    ("M15", "the housekeeping interval moved to the END of the interval list", _m_interval_eof, ["I-IV"]),
    ("M16", "remove the purpose-integrity check from the final lambda", _m_no_integrity, ["S-FINAL", "B-INTEG"]),
    ("M17", "publish B4 for a not-saveable candidate", _m_b4_unsaveable, ["S-BUILDERS", "B-L2"]),
    ("M18", "TTL 130 000 ms instead of 120 000", _m_ttl_130, ["S-IVRAM", "B-TTL"]),
    ("M19", "drop the wrap-safe subtraction in the expiry test", _m_not_wrap_safe, ["S-IVRAM", "B-TTL"]),
    ("M20", "seed the salt (random_uint32) in on_boot", _m_salt_in_boot, ["S-SALT", "B-GOLD"]),
    ("M21", "add a Modbus WRITE action to the dispatch", _m_write_action, ["S-READS", "I-WS", "B-HAPPY"]),
    ("M22", "read a supervision symbol in the housekeeping interval", _m_supervision, ["S-NOSUP"]),
    ("M23", "B5 fed with the SAVED view (b7_text)", _m_b5_saved, ["S-BUILDERS", "B-HAPPY"]),
    ("M24", "skip the release on the pass-mismatch path", _m_release_skip_mismatch, ["S-RELEASE", "B-MISMATCHQ"]),
    ("M25", "swap the two passes in the mismatch text (a / b)", _m_swap_mismatch, ["S-FINAL", "B-MISMATCHQ"]),
    ("M26", "'FAILED' in an operator text (reg244 boot text)", _m_failed_text, ["S-TEXT3"]),
    ("M27", "an unclamped B9 text > 200 chars (breaker text padded)", _m_unclamped, ["S-LIT", "B-BRK"]),
    ("M28", "V1 touches state (the in-flight refusal resets capture_state)", _m_v1_touches, ["S-GATE", "B-V1"]),
    ("M29", "the accept branch sets step = 1 instead of 0", _m_step1, ["S-GATE"]),
    ("M30", "the boot lambda sets baseline_valid = true (the divergence rule fires against an empty mirror)", _m_boot_baseline, ["S-GATEIN", "B-BOOT"]),
    ("M31", "boot_loaded = true set before the boot load", _m_boot_loaded_early, ["S-BOOT"]),
    ("M32", "BLK-11 retains a constant instead of marker_load", _m_blk11_const, ["S-BLK11", "B-BOOT"]),
    ("M33", "a superseded reason publishes B9 (IE3 outcome shown)", _m_superseded_publishes, ["S-INV", "B-IE"]),
    ("M34", "idle wait 70 000 ms instead of 7 000", _m_idle_wait, ["S-STEP", "B-FAIL"]),
    ("M35", "bounded wait 30 000 ms on R3 instead of 3 000", _m_bounded_wait, ["S-STEP", "B-FAIL"]),
    ("M36", "the gate accepts without taking manual_write_in_progress", _m_no_mutex_take, ["S-PAIR", "S-GATE", "B-V1"]),
    ("M37", "the release lambda forgets manual_write_in_progress", _m_release_keeps_mutex, ["S-RELEASE", "B-HAPPY", "B-FUZZQ"]),
    ("M38", "the sequence number is not advanced for an eligible candidate", _m_seq_not_bumped, ["B-GOLD"]),
    ("M39", "IE3 removed: an old candidate survives a new Review", _m_no_ie3, ["S-GATE", "B-IE"]),
    ("M40", "cand_ms is never set (the TTL runs from 0)", _m_cand_ms_unset, ["B-TTL"]),
    ("M41", "the tick's writes fingerprint omits a counter (IE11 fires at once)", _m_tick_fingerprint, ["S-IVRAM", "B-IE"]),
    ("M42", "gi.bus.now_ms = 0 (the stuck-lock age is wrong)", _m_now_ms_zero, ["S-GATEIN", "B-BUS"]),
    ("M43", "R4 stores into pass1 (pass2 never gets the second 241/53)", _m_r4_buffer, ["S-HANDLERS", "B-HAPPY"]),
    ("M44", "candidate words taken from pass1", _m_cand_from_pass1, ["S-FINAL"]),
    ("M45", "the Dump snapshot_valid input is hard-wired false (a Dump lease is invisible)", _m_dump_bus_lease, ["S-GATEIN", "B-LEASE"]),
    ("M46", "a restore script is dropped from the FP RUN set", _m_run_term, ["S-GATEIN", "S-RUN", "B-LEASE"]),
    ("M47", "V1 forgets the leaked op_in_progress flag (only is_running() is checked)", _m_v1_running_only, ["S-GATE", "B-BRK"]),
    ("M48", "the tick checks the candidate even while a Review runs (drops `!op_in_progress`)", _m_tick_during_op, ["S-IVRAM"]),
    ("M49", "the stored candidate warnings are zeroed (the 10 s tick refresh loses warn=)", _m_warnings_zero, ["B-WARN"]),
    ("M50", "the final lambda stops updating the RAM class mirror", _m_class_mirror, ["B-DIVERGE", "B-STORED"]),
    # ---- the generic zero-authority pins (review TESTS0: eight mutants that passed every older detector)
    ("M51", "gate: `if (false) id(apply_manual_slot2).execute();` - a WRITER script executed from the gate (review R82)",
     _gate_insert("if (false) id(apply_manual_slot2).execute();"), ["S-AUTH"]),
    ("M52", "gate: a writer script executed behind an unreachable condition (latch == 0x0FFF -> apply_reg244_settings; review R84)",
     _gate_insert("if (id(fallback_profile_probe_latch) == 0x0FFF) id(apply_reg244_settings).execute();"), ["S-AUTH"]),
    ("M53", "gate: a non-FB write-attempt counter bumped behind an unreachable condition (id(dump_start_attempts)++; review R85)",
     _gate_insert("if (id(fallback_profile_probe_latch) == 0x0FFF) id(dump_start_attempts)++;"), ["S-AUTH"]),
    ("M54", "gate: a foreign recovery flag cleared behind an unreachable condition (free_power_snapshot_valid = false; review R86)",
     _gate_insert("if (id(fallback_profile_probe_latch) == 0x0FFF) id(free_power_snapshot_valid) = false;"), ["S-AUTH"]),
    ("M55", "boot lambda: a writer script executed behind an unreachable condition (lp == 99; review R87)", _m_boot_exec, ["S-AUTH"]),
    ("M56", "invalidate script: a writer script executed behind an unreachable condition (review R88)", _m_inv_exec, ["S-AUTH"]),
    ("M57", "gate: a writer script executed when dump_containment_state == 7 - a REACHABLE state no scenario sets (review R130)",
     _gate_insert("if (id(dump_containment_state) == 7) id(apply_reg244_settings).execute();"), ["S-AUTH"]),
    ("M58", "gate: a foreign recovery flag cleared when dump_containment_state == 7 (review R131)",
     _gate_insert("if (id(dump_containment_state) == 7) id(free_power_snapshot_valid) = false;"), ["S-AUTH"]),
    ("M59", "gate: a foreign std::string global cleared through a member call (id(...).clear()), not an assignment",
     _gate_insert("if (id(fallback_profile_probe_latch) == 0x0FFF) id(free_power_recovery_invalidate_reason).clear();"), ["S-AUTH"]),
    ("M60", "gate: a foreign global READ outside the pinned gate-input statements (only an FB global is modified)",
     _gate_insert("if (id(dump_containment_state) == 7) id(fallback_profile_probe_latch) = id(fallback_profile_probe_latch);"), ["S-AUTH"]),
    # ---- serial logging (review GLUE0): exactly six pinned call sites
    ("M61", "a seventh fbcap log call inside a Modbus reply handler (logging on a hot path)", _m_log_in_handler, ["S-LOG", "S-LIT"]),
    ("M62", "the 'review accepted' log line also emitted on the REFUSAL branch of the gate", _m_log_wrong_site, ["S-LOG"]),
    ("M63", "a log argument without its (unsigned) cast", _m_log_uncast, ["S-LOG"]),
    # ---- IE11 stays alive (review TESTS1) and the tick's publish-on-change guard (review TESTS4)
    ("M64", "start_dump_to_grid_override no longer bumps dump_start_attempts (IE11 would silently stop firing)", _m_drop_dump_counter, ["S-WRCNT"]),
    ("M65", "apply_manual_slot1 no longer bumps manual_write_attempts (the REAL writer no longer clears the candidate)", _m_drop_manual_counter, ["S-WRCNT", "B-WRITERS"]),
    ("M66", "the 10 s tick publishes the B3 refresh unconditionally (no publish-on-change guard)", _m_tick_unconditional, ["S-IVRAM"]),
]


# ===========================================================================
# main
# ===========================================================================
def run_detector(name: str, ctx: Ctx):
    """-> (status, violations). status "ok" | "error" (the detector could not run on this text: a mutant the harness cannot execute)."""
    try:
        if name in STATIC:
            return "ok", STATIC[name](ctx)
        if name in BEHAV:
            return "ok", BEHAV[name](ctx.fw)
        raise KeyError(name)
    except ds.Unsupported as ex:
        return "error", [f"Unsupported: {ex}"]
    except Exception as ex:  # noqa: BLE001 - any other failure on a broken text is a detection
        return "ok", [f"{type(ex).__name__}: {str(ex)[:160]}"]


PROOFS = {
    "P1": ("exactly four added Modbus reads per Review (230/3, 241/53, 230/3, 241/53), none when it refuses; analyzer 64 reads / 52 writes",
           ["I-WS", "S-READS", "S-STEP", "S-NEST", "B-HAPPY", "B-ARMS", "B-BUS", "B-LEASE", "B-PROBE", "B-BOOTTRUTH", "B-FBS", "B-FAIL", "B-POLLS"]),
    "P2": ("zero Modbus writes, zero NVS / durable writes (nvs_set_blob only in the FB-B0 adapter, no commit / load_record*), zero inverter authority "
           "(only the FB invalidate script is ever executed, only FB globals + the mutex are modified, logging is read-only)",
           ["S-WRITE", "S-READS", "S-FINAL", "S-BOOT", "S-IVRAM", "S-INV", "S-PUB", "S-AUTH", "S-LOG", "S-LIT", "B-ZERO", "B-FUZZ", "B-INTEG", "B-CUT"]),
    "P3": ("the candidate disappears / expires correctly: TTL 120 000 ms by the 10 s tick, wrap-safe, IE1 / IE3 / IE7 / IE9 / IE11 (driven by injected flags AND by the "
           "REAL writer scripts, whose counters are pinned), never survives a reboot or a power cut at any of ~80 instants",
           ["S-IVRAM", "S-WRCNT", "B-TTL", "B-IE", "B-BRK", "B-REBOOT", "B-CUT", "B-WRITERS", "B-B9"]),
    "P4": ("a disagreement between the two passes NEVER produces a valid candidate (each of the 31 words, each gap between the four reads)",
           ["S-FINAL", "B-MISMATCH", "B-MISMATCH2"]),
    "P5": ("no regression to the other features: FB code takes / releases manual_write_in_progress exactly once, no other script / button / interval / on_boot line changed, "
           "a Free Power / Dump / Manual TOU start arriving during a review is rejected by its own gate and the review still completes",
           ["I-SCRIPTS", "I-BTN", "I-IV", "I-BOOT", "I-DELTA", "I-GLOB", "S-PAIR", "S-RUN", "S-BLK11", "S-TEXT3", "S-AUTH", "B-ZERO", "B-COLLIDE", "B-OWNER"]),
}


def main() -> int:
    global BASE
    t_start = time.time()
    print(f"FB-B1 firmware suite: {FW_REL}")
    results: dict = {}
    section_t: dict = {}

    # ------------------------------------------------------------------
    print("[0] Inventory: what FB-B1 adds to BASE, and nothing else")
    # ------------------------------------------------------------------
    ts = time.time()
    check("the pre-FB-B1 BASE is chain-derived: _fbb1_scope.pre_fbb1_firmware(live) hashes to the pinned BASE_FW_SHA (a61709c3...), which is the "
          "chain's fbb0 checkpoint (main @ 4649465) - no git, no subprocess; the suite never skips without it",
          BASE_TEXT is not None and scope.BASE_FW_SHA == CH.checkpoint(chain.FIRMWARE, "fbb0")
          == "a61709c3fe42a8da60e16652891888988d96254be9f37e844ab665543d8c5881", BASE_ERR)
    import ast
    _tree = ast.parse(Path(__file__).read_text(encoding="utf-8"))
    _spawns = [n for n in ast.walk(_tree)
               if (isinstance(n, ast.Import) and any(a.name.split(".")[0] == "subprocess" for a in n.names))
               or (isinstance(n, ast.ImportFrom) and (n.module or "").split(".")[0] == "subprocess")
               or (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr in ("system", "popen", "Popen"))
               or (isinstance(n, ast.Constant) and n.value in ("g" + "it", "g" + "it.exe"))]
    check("this suite spawns no process and asks git nothing (no subprocess import, no os.system / popen, no 'git' argv): it works in a "
          "shallow clone and in a copy of the tree without .git", not _spawns, str([getattr(n, "lineno", 0) for n in _spawns]))
    if BASE_TEXT is not None:
        BASE = ds.load_firmware_text(BASE_TEXT)
    ctx = Ctx(LIVE_TEXT)
    check("the live firmware has exactly one housekeeping interval and the three FB scripts, the button and the appended boot item are located",
          ctx.interval is not None and bool(ctx.gate) and bool(ctx.disp) and bool(ctx.inv) and ctx.button is not None and len(ctx.boot_then) == 4)
    for name in [n for n in STATIC if n.startswith("I-")]:
        st, v = run_detector(name, ctx)
        results[name] = st == "ok" and not v
        check(LABELS[name], results[name], "; ".join(v)[:400])
    section_t["0"] = time.time() - ts

    # ------------------------------------------------------------------
    print("")
    print("[S] Static pins (S1 13.3 adapted to REVIEW-only; every one is also a mutation detector)")
    # ------------------------------------------------------------------
    ts = time.time()
    for name in [n for n in STATIC if not n.startswith("I-")]:
        st, v = run_detector(name, ctx)
        results[name] = st == "ok" and not v
        check(LABELS[name], results[name], "; ".join(v)[:400])
    section_t["S"] = time.time() - ts

    # ------------------------------------------------------------------
    print("")
    print("[B] Behaviour: the REAL YAML through FbbSim (every scenario also asserts the safety invariants)")
    # ------------------------------------------------------------------
    ts = time.time()
    for name in BEHAV:
        t1 = time.time()
        st, v = run_detector(name, ctx)
        results[name] = st == "ok" and not v
        check(f"{LABELS[name]}  [{time.time() - t1:.1f}s]", results[name], "; ".join(v[:3])[:600])
    live_sims = list(ALL_SIMS)
    bad = [(i, e) for i, s in enumerate(live_sims) for e in safety_errors(s)]
    check(f"T-CAP-23 / P2: across ALL {len(live_sims)} simulators of the matrix: zero Modbus writes, zero direct-NVS sets, zero ecco_durable commits", not bad, str(bad[:3]))
    fw_reads = sum(1 for s in live_sims for e in s.modbus_log if e[0] == "read")
    scripts_run = {sid for s in live_sims for sid, _p in s.executed}
    paths_ = analyze_text(LIVE_TEXT)["paths"]
    writers_ = WRITER_SCRIPTS | {p_.name for p_ in paths_ if p_.writes}
    check("every script any simulator of the FB matrix executed is on an ALLOWLIST - the three FB scripts + the read-only poll scripts the suite starts itself + the "
          "RAM-only evidence routine the pre-existing boot lambda runs - and "
          f"none is a writer, by name or by the write-surface analyzer ({len(writers_)} writer paths); the scenarios that start REAL writers run in their own simulators",
          scripts_run <= (set(FB_SCRIPT_IDS) | POLL_SCRIPTS | BOOT_RAM_ROUTINES) and not (scripts_run & writers_)
          and not ((POLL_SCRIPTS | BOOT_RAM_ROUTINES) & writers_),
          f"ran {sorted(scripts_run)}; outside the allowlist {sorted(scripts_run - set(FB_SCRIPT_IDS) - POLL_SCRIPTS - BOOT_RAM_ROUTINES)}; "
          f"writers run {sorted(scripts_run & writers_)}")
    all_b9 = {str(x) for s in live_sims for x in s.ent(TS["B9"]).published}
    rx = STATE.get("rx") or card_regexes()
    hits = [(s[:50], p) for s in all_b9 for p, fl, o in rx if re.search(p, s, re.I)] + [(s[:50], h.pattern) for s in all_b9 for h in D8_HAZARD if h.search(s)]
    check(f"every B9 text published in the behavioural matrix ({len(all_b9)} distinct, longest {max(map(len, all_b9))}) is <= 200 chars, carries a D8 prefix, and matches no "
          "card regex or D8 hazard word", not hits and all(len(s) <= 200 and s.startswith(B9_PREFIXES) for s in all_b9), str(hits[:3]))
    grammar_bad = []
    for key in RX:
        for s in {str(x) for sm in live_sims for x in sm.ent(SHORT[key]).published}:
            if not RX[key].fullmatch(s) or len(s) > 200 or " " in s:
                grammar_bad.append((key, s[:80]))
    check(f"every B1-B8 string published in the matrix is grammar-valid, charset-clean and <= 200 chars ({sum(len({str(x) for sm in live_sims for x in sm.ent(SHORT[k]).published}) for k in RX)} distinct)",
          not grammar_bad, str(grammar_bad[:3]))
    section_t["B"] = time.time() - ts

    # ------------------------------------------------------------------
    print("")
    print("[C] Real syntax-level compile of every FB lambda (xtensa g++ -fsyntax-only -Wall -Wextra -Werror, gnu++17 + gnu++20)")
    # ------------------------------------------------------------------
    ts = time.time()
    compile_section(ctx.fw)
    section_t["C"] = time.time() - ts

    # ------------------------------------------------------------------
    print("")
    print("[M] Mutation matrix: deliberately broken copies of the live firmware, each killed by its named detectors")
    # ------------------------------------------------------------------
    ts = time.time()
    names = sorted({d for _i, _d, _f, ds_ in MUTANTS for d in ds_})
    check("every detector the matrix uses ran green on the REAL firmware first", all(results.get(n) for n in names),
          str([n for n in names if not results.get(n)]))
    check("the mutation helper refuses an anchor that does not occur exactly once (no silent no-op mutant)",
          _raises(lambda: mutate(LIVE_TEXT, "this text does not occur in the firmware", "x")) and _raises(lambda: mutate(LIVE_TEXT, "id(", "id (")))
    scratch: list = []
    _SINK[0] = scratch
    killed = 0
    survivors = []
    for mid, desc, fn, dets in MUTANTS:
        t1 = time.time()
        try:
            mtext = fn(LIVE_TEXT)
            mctx = Ctx(mtext)
        except Exception as ex:  # noqa: BLE001
            check(f"{mid}: {desc}", False, f"mutant could not be built: {type(ex).__name__}: {str(ex)[:200]}")
            continue
        caught, missed, errs = [], [], []
        for d in dets:
            st, v = run_detector(d, mctx)
            if st == "error":
                errs.append(f"{d}: {v[0][:100]}")
            elif v:
                caught.append(d)
            else:
                missed.append(d)
        also = []
        ok = not errs and not missed
        killed += ok
        if not ok:
            survivors.append(mid)
        scratch.clear()
        check(f"{mid}: {desc} -> killed by {' + '.join(dets)}  [{time.time() - t1:.1f}s]", ok, f"caught={caught} NOT caught={missed} errors={errs}")
    _SINK[0] = ALL_SIMS
    print(f"  mutants killed: {killed}/{len(MUTANTS)}")
    check(f"at least 28 distinct mutants, every one killed by every detector named for it ({len(MUTANTS)} defined, {killed} killed)",
          len(MUTANTS) >= 28 and killed == len(MUTANTS), f"survivors {survivors}")
    section_t["M"] = time.time() - ts

    # ------------------------------------------------------------------
    print("")
    print("[P] The five proofs this suite exists for")
    # ------------------------------------------------------------------
    for pid, (what, dets) in PROOFS.items():
        failing = [d for d in dets if not results.get(d)]
        check(f"{pid}: {what}  [{len(dets)} detectors]", not failing, f"failing: {failing}")

    total = time.time() - t_start
    print("")
    print(f"{NCHECKS[0]} checks in {total:.0f} s (inventory {section_t['0']:.0f} s, static {section_t['S']:.0f} s, behaviour {section_t['B']:.0f} s "
          f"over {len(live_sims)} simulators, compile {section_t['C']:.0f} s, mutation {section_t['M']:.0f} s); {len(STATIC)} static + {len(BEHAV)} behavioural detectors, "
          f"{len(MUTANTS)} mutants")
    if FAILURES:
        print(f"FAILED: {len(FAILURES)} check(s)")
        for f in FAILURES:
            print("  -", f)
        return 1
    print("ALL CHECKS PASSED")
    print("(These execute the firmware SOURCE under registry/tests/_fbb_harness.py and compile every FB lambda against stubs. They do not prove")
    print(" ESPHome's real loop timing, its generated glue, the linked binary or any live behaviour - only `esphome compile` and a soak can.)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
