"""Python mirror of the FB-B2 pure SAVE / INVALIDATE header (C++-exact).

firmware/include/ecco_fallback_save.h (namespace ecco_fbsave) is the C++ side. FB-B2 turns the read-only REVIEW candidate
into a durable known-good profile: a SAVE gate, the dispatch re-read, one synchronous final lambda that calls the FB-B0
writer, and the INVALIDATE gate+commit. Every DECISION those lambdas take is a PURE function of plain values and lives in
the header; the lambdas only gather RAM flags into the POD structs below, make ONE call per decision, publish the result
and make the one writer call themselves. This module is the independent mirror the offline suites hold the header to:
  - registry/tests/test_fallback_save_model.py exercises every function here (truth tables for every gate, the grammar of
    the confirmation phrase against an independent regex oracle, every plan against the FB-B0 transition validator, every
    outcome text cell);
  - registry/tests/test_fallback_save_host_compile.py makes a real C++ compiler evaluate the header's static_asserts and
    requires every golden value / golden string to equal what this module produces, plus randomized parity;
  - registry/tests/_fbb_harness.py adapts this module generically as the namespace `ecco_fbsave` when it simulates the
    firmware lambdas.

NAMING. Every function, constant and struct field below has the SAME snake_case name as in the C++ namespace. C++
`const char *` strings arrive as `str | bytes | None` (None is a null pointer) and an optional byte length `n`: without it
the string is read up to its first NUL (and at most `limit + 1` bytes), with it exactly n bytes count (embedded NULs are
characters). Strings are processed as UTF-8 BYTES, exactly like the C++ std::string they come from. Structs are dataclasses
in the C++ field order; records are the dicts of registry/fallback_profile.py / registry/fallback_durable.py. C++ TextBuf is
fallback_capture.TextBuf (a str with c_str() / size()); texts are cut at TEXT_CAP (200) exactly like the C++ builders.

SIGNATURES (C++ shown; the Python parameters are the same, in the same order; an optional `n` replaces the C++ overload)
  router / grammar
    uint8_t action_token(const char *action[, size_t n])                 ACT_*: exact, case-sensitive
    bool is_invalidate_action(const char *action[, size_t n])            the router: INVALIDATE only
    TextBuf action_refusal_text(uint8_t token, const char *action, size_t n)   reserved / unsupported-action text (sanitised echo)
    TextBuf unsupported_action_text(const char *action[, size_t n])      the echo: [A-Za-z0-9_] kept, every other byte '?', every
                                                                         case-insensitive "fail" / "defer" masked to '?', first 24 bytes
    bool is_hex16(const char *s[, size_t n])    uint64_t parse_hex16(...)    Phrase parse_phrase(const char *c[, size_t n])
    TextBuf expected_phrase(uint8_t kind, uint64_t id)    bool phrase_equals(const char *c[, size_t n], const TextBuf &expected)
  timing / integrity
    bool arm_expired(uint32_t now_ms, uint32_t on_ms)     bool save_integrity_ok(bool op_in_progress, uint8_t op_purpose)
    uint8_t overlay_class(uint8_t cls, bool unconfirmed)
  SAVE gate
    SaveGateResult save_in_flight_gate(bool op_in_progress, bool dispatch_running)       G1 only (before the one-shot preamble)
    SaveGateResult save_gate_decide(in, action, action_len, target_id, target_len, confirmation, confirmation_len, g)
    SaveGateResult save_gate_with_result(in, ..., g, gr)                                  the same over a given capture gate decision
    TextBuf save_gate_refusal_text(const GateResult &gr, const GateInputs &g)             a capture-gate decision with the SAVE wording
  SAVE final
    GateInputs final_phase_inputs(GateInputs g)           clears the three own holds, nothing else
    FinalGate final_gate_decide(const GateInputs &g, const ProbeResults &pr)
    bool commit_bus_quiet(op_in_progress, mutex_held, correction_in_progress, tx_buffer_empty, tx_blocked)
    bool clock_trusted_for_save(bool time_trusted, uint32_t epoch)
    Plan plan_save(const SavePlanInputs &in)              the intended FBP / FBW pair, PO14 pre-validated
  INVALIDATE
    InvalidateGateResult invalidate_in_flight_gate(bool op_in_progress, bool dispatch_running)
    InvalidateGateResult invalidate_gate_decide(in, action, action_len, target_id, target_len, confirmation, confirmation_len)
    bool invalidate_bus_idle(const BusInputs &b, bool tx_buffer_empty, bool tx_blocked)
    Plan plan_invalidate(const InvalidatePlanInputs &in)
  outcome
    TextBuf txn_outcome_text(op, outcome, r, generation, prior_generation)    uint32_t first_non_ok(err_w, err_p)    uint32_t total_us(w_us, p_us)
    TextBuf txn_log_text(op, outcome, r, generation)      TextBuf replace_corrupt_log_text(p_load, p, stored_len, part)
  names / texts: txn_name txn_op_name key_name rb_name slot_label echo_char_ok hex_digit_ok bounded_len exact starts_with and every
                 *_text builder

C WIDTHS (AW-5). Every dataclass below declares the C type of each scalar field in a class attribute `CTYPES = {"field": "uint32_t"}` (the
header's own types: uint8_t / uint32_t / uint64_t / bool; an std::array<uint16_t, N> field names its ELEMENT type). The strict firmware
simulator (registry/tests/_fbb1_fbcap.py) wraps every store into such a field to that width, exactly like the C++ assignment would; the
mirror functions themselves never look at CTYPES.

Pure: stdlib only, no I/O. Reuses registry/fallback_capture.py, registry/fallback_profile.py and registry/fallback_durable.py.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field, replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fallback_capture as cap  # noqa: E402
import fallback_durable as fd  # noqa: E402
import fallback_profile as fp  # noqa: E402

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
ARM_TTL_MS = 120000
PRECOMMIT_WAIT_MS = 3000
PURPOSE_SAVE = 2
ECHO_MAX = 24
ECHO_LOOK = 4   # the echo examines this many bytes beyond ECHO_MAX, so a hazard word cut by the cut is masked as far as visible
ID_DIGITS = 16
PHRASE_SCAN_MAX = 64
ACTION_SCAN_MAX = 16
TEXT_CAP = cap.TEXT_CAP
U32 = 0xFFFFFFFF
U64 = 0xFFFFFFFFFFFFFFFF

SAVE_REFUSED_PREFIX = "SAVE REFUSED - "
INVALIDATE_REFUSED_PREFIX = "INVALIDATE REFUSED - "

(ACT_UNSUPPORTED, ACT_SAVE, ACT_INVALIDATE, ACT_RESTORE, ACT_ACKNOWLEDGE) = range(5)
(PHRASE_INVALID, PHRASE_SAVE, PHRASE_SAVE_REPLACE_CORRUPT, PHRASE_INVALIDATE) = range(4)
(SG_UNSET, SG_ACCEPT, SG_IN_FLIGHT, SG_UNSUPPORTED, SG_ARM_OFF, SG_NO_CANDIDATE, SG_EXPIRED, SG_ID_FORMAT, SG_ID_MISMATCH,
 SG_PHRASE, SG_NOT_LOADED, SG_UNCONFIRMED, SG_ANOMALY, SG_HB, SG_TIME, SG_ARMS, SG_WRITES, SG_BUS, SG_FBS, SG_FP, SG_DUMP,
 SG_R244, SG_MTOU) = range(23)
(IG_UNSET, IG_ACCEPT, IG_IN_FLIGHT, IG_UNSUPPORTED, IG_ARM_OFF, IG_ID_FORMAT, IG_PHRASE, IG_NOT_LOADED, IG_ANOMALY,
 IG_UNCONFIRMED, IG_CLASS, IG_ID_MISMATCH, IG_GENERATION, IG_BUS, IG_FBS) = range(15)
(PLAN_UNSET, PLAN_OK, PLAN_PRIOR_CHANGED, PLAN_UNCONFIRMED, PLAN_ANOMALY, PLAN_CLASS, PLAN_CONTEXT, PLAN_CLOCK,
 PLAN_GENERATION, PLAN_INTERNAL, PLAN_BINDING_CHANGED) = range(11)

TextBuf = cap.TextBuf


def _tb(text: str) -> TextBuf:
    return TextBuf(text[:TEXT_CAP])


def _hex(value: int, digits: int) -> str:
    return format(value, "X").rjust(digits, "0")


def _prof(record) -> dict:
    """A FallbackProfileV1 as a dict: accepts a dict, 96 raw bytes, or a harness record object."""
    if hasattr(record, "as_dict"):
        return record.as_dict()
    return fp._as_profile(record)


def _wit(record) -> dict:
    """A FailbackProvisionV1 as a dict: accepts a dict, 48 raw bytes, or a harness record object."""
    if hasattr(record, "as_dict"):
        return record.as_dict()
    return fd._as_provision(record)


def _cb(s):
    """A C string as bytes (None stays None); a str is its UTF-8 bytes, like the std::string it came from."""
    if s is None:
        return None
    if isinstance(s, (bytes, bytearray)):
        return bytes(s)
    return str(s).encode("utf-8", "surrogatepass")


# ---------------------------------------------------------------------------
# Bounded string primitives
# ---------------------------------------------------------------------------
def bounded_len(s, limit: int) -> int:
    """Characters of `s` before its NUL, never reading more than limit + 1 bytes; a null pointer is empty."""
    b = _cb(s)
    if b is None:
        return 0
    i = b.find(b"\0")
    n = len(b) if i < 0 else i
    return min(n, limit + 1)


def exact(s, n: int, lit: str) -> bool:
    """The n bytes at s are exactly the literal."""
    b = _cb(s)
    lb = lit.encode("ascii")
    return b is not None and n == len(lb) and b[:n] == lb


def starts_with(s, n: int, lit: str) -> bool:
    """The n bytes at s start with the literal."""
    b = _cb(s)
    lb = lit.encode("ascii")
    return b is not None and n >= len(lb) and b[:len(lb)] == lb


# ---------------------------------------------------------------------------
# Action token
# ---------------------------------------------------------------------------
def action_token(action, n=None) -> int:
    if n is None:
        n = bounded_len(action, ACTION_SCAN_MAX)
    if exact(action, n, "SAVE"):
        return ACT_SAVE
    if exact(action, n, "INVALIDATE"):
        return ACT_INVALIDATE
    if exact(action, n, "RESTORE"):
        return ACT_RESTORE
    if exact(action, n, "ACKNOWLEDGE"):
        return ACT_ACKNOWLEDGE
    return ACT_UNSUPPORTED


def is_invalidate_action(action, n=None) -> bool:
    return action_token(action, n) == ACT_INVALIDATE


def echo_char_ok(c: int) -> bool:
    """[A-Za-z0-9_] (c is a byte value)."""
    return 65 <= c <= 90 or 97 <= c <= 122 or 48 <= c <= 57 or c == 95


def _echo_mask(t: str, visible: int) -> str:
    """F2: every case-insensitive occurrence of the hazard words "fail" and "defer" in the SANITISED token t becomes '?' (the matched
    letters only: "failed" -> "????ed", "xDeFeRrEdx" -> "x?????rEdx"), then the first `visible` characters are kept - so an occurrence
    cut by the ECHO_MAX cut is masked as far as visible, and an operator-supplied token can never put the words failed / deferred
    on B9. t holds only [A-Za-z0-9_?] (ASCII), so str.lower() is the ASCII fold. The two words cannot overlap each other or themselves."""
    low = t.lower()
    out = list(t)
    for word in ("fail", "defer"):
        start = low.find(word)
        while start >= 0:
            for k in range(start, start + len(word)):
                out[k] = "?"
            start = low.find(word, start + 1)
    return "".join(out[:visible])


def _sanitised(s, n: int) -> str:
    """The sanitised, masked echo of an operator token: sanitise (at most ECHO_MAX + ECHO_LOOK bytes examined), mask, publish the first ECHO_MAX."""
    b = _cb(s)
    if b is None:
        return ""
    m = min(n, ECHO_MAX + ECHO_LOOK, len(b))
    return _echo_mask("".join(chr(b[i]) if echo_char_ok(b[i]) else "?" for i in range(m)), ECHO_MAX)


def unsupported_action_text(action, n=None) -> TextBuf:
    if n is None:
        n = bounded_len(action, ECHO_MAX + ECHO_LOOK)
    return _tb("REFUSED - unsupported action '" + _sanitised(action, n) + "'")


def action_refusal_text(token: int, action, n: int) -> TextBuf:
    if token == ACT_RESTORE:
        return _tb("RESTORE REFUSED - not implemented in this firmware")
    if token == ACT_ACKNOWLEDGE:
        return _tb("ACKNOWLEDGE REFUSED - not implemented in this firmware")
    return unsupported_action_text(action, n)


# ---------------------------------------------------------------------------
# Confirmation grammar
# ---------------------------------------------------------------------------
def hex_digit_ok(c: int) -> bool:
    """[0-9A-F] (c is a byte value)."""
    return 48 <= c <= 57 or 65 <= c <= 70


def is_hex16(s, n=None) -> bool:
    if n is None:
        n = bounded_len(s, ID_DIGITS)
    b = _cb(s)
    if b is None or n != ID_DIGITS or len(b) < ID_DIGITS:
        return False
    return all(hex_digit_ok(b[i]) for i in range(ID_DIGITS))


def parse_hex16(s, n=None) -> int:
    if n is None:
        n = bounded_len(s, ID_DIGITS)
    if not is_hex16(s, n):
        return 0
    return int(_cb(s)[:ID_DIGITS].decode("ascii"), 16)


@dataclass
class Phrase:
    kind: int = PHRASE_INVALID
    id: int = 0
    CTYPES = {"kind": "uint8_t", "id": "uint64_t"}


def parse_phrase(confirmation, n=None) -> Phrase:
    if n is None:
        n = bounded_len(confirmation, PHRASE_SCAN_MAX)
    p = Phrase()
    b = _cb(confirmation)
    if starts_with(confirmation, n, "SAVE "):
        head, kind = 5, PHRASE_SAVE
    elif starts_with(confirmation, n, "INVALIDATE "):
        head, kind = 11, PHRASE_INVALIDATE
    else:
        return p
    if n < head + ID_DIGITS or not is_hex16(b[head:], ID_DIGITS):
        return p
    after = head + ID_DIGITS
    if n == after:
        p.kind = kind
        p.id = parse_hex16(b[head:], ID_DIGITS)
        return p
    if kind == PHRASE_SAVE and n > after and exact(b[after:], n - after, " REPLACE CORRUPT"):
        p.kind = PHRASE_SAVE_REPLACE_CORRUPT
        p.id = parse_hex16(b[head:], ID_DIGITS)
    return p


def expected_phrase(kind: int, id: int) -> TextBuf:  # noqa: A002 - the C++ parameter name
    if kind in (PHRASE_SAVE, PHRASE_SAVE_REPLACE_CORRUPT):
        text = "SAVE "
    elif kind == PHRASE_INVALIDATE:
        text = "INVALIDATE "
    else:
        return _tb("")
    text += _hex(id & U64, 16)
    if kind == PHRASE_SAVE_REPLACE_CORRUPT:
        text += " REPLACE CORRUPT"
    return _tb(text)


def phrase_equals(confirmation, n_or_expected, expected=None) -> bool:
    if expected is None:
        expected = n_or_expected
        n = bounded_len(confirmation, len(expected))
    else:
        n = n_or_expected
    b = _cb(confirmation)
    if b is None or len(expected) == 0 or n != len(expected):
        return False
    return b[:n] == str(expected).encode("utf-8")


# ---------------------------------------------------------------------------
# Arm TTL, integrity, class overlay
# ---------------------------------------------------------------------------
def arm_expired(now_ms: int, on_ms: int) -> bool:
    return ((now_ms - on_ms) & U32) >= ARM_TTL_MS


def save_integrity_ok(op_in_progress: bool, op_purpose: int) -> bool:
    return bool(op_in_progress) and op_purpose == PURPOSE_SAVE


def overlay_class(cls: int, unconfirmed: bool) -> int:
    return fd.EPC_SAVE_UNCONFIRMED if unconfirmed else cls


# ---------------------------------------------------------------------------
# Text: SAVE refusals
# ---------------------------------------------------------------------------
def save_refused(body: str) -> TextBuf:
    return _tb(SAVE_REFUSED_PREFIX + body)


def invalidate_refused(body: str) -> TextBuf:
    return _tb(INVALIDATE_REFUSED_PREFIX + body)


def save_in_flight_text() -> TextBuf:
    return save_refused("another Fallback Profile operation is in progress")


def save_arm_off_text() -> TextBuf:
    return save_refused("ECCO Fallback Profile Arm is not on")


def save_no_candidate_text() -> TextBuf:
    return save_refused("no saveable candidate - press Review Current Configuration first")


def save_expired_text() -> TextBuf:
    return save_refused("candidate expired (120 s) - review again")


def save_id_format_text() -> TextBuf:
    return save_refused("candidate ID must be 16 hex characters")


def save_id_mismatch_text() -> TextBuf:
    return save_refused("candidate ID does not match the current candidate")


def save_phrase_text(expected) -> TextBuf:
    return save_refused("confirmation phrase mismatch (expected '" + str(expected) + "')")


def save_not_loaded_text() -> TextBuf:
    return save_refused("durable state not loaded yet")


def save_prior_unknown_text() -> TextBuf:
    return save_refused("previous save outcome unknown this boot - reboot to re-verify first")


def save_anomaly_text() -> TextBuf:
    return save_refused("stored profile read anomaly this boot; reboot to re-derive it first")


def save_hb_text() -> TextBuf:
    return save_refused("Home Assistant heartbeat is not stable; wait until the dashboard shows it healthy, then review "
                        "and save again")


def save_time_text() -> TextBuf:
    return save_refused("clock not NTP-synchronised this boot; the capture time would be untrusted")


def save_arms_text() -> TextBuf:
    return save_refused("a Free Power / Dump to Grid / Manual Configuration write arm is on; finish or turn it off first")


def save_writes_text() -> TextBuf:
    return save_refused("another ECCO inverter write started since Review - review again")


def save_internal_text() -> TextBuf:
    return save_refused("internal: gate state unavailable; nothing written")


def save_in_progress_text() -> TextBuf:
    return _tb("save in progress - re-reading live configuration")


def slot_label(slot: int) -> str:
    return {cap.SLOT_FP: "Free Power", cap.SLOT_DUMP: "Dump to Grid", cap.SLOT_R244: "Register 244 test",
            cap.SLOT_FBS: "Failback record", cap.SLOT_MTOU: "Manual TOU"}.get(slot, "")


def _slot_body(slot: int, c: cap.SlotClass, dump_containment: int, owner: str, lock_age_s: int) -> str:
    d = slot_label(slot)
    kind, basis = c.kind, c.basis
    if slot == cap.SLOT_BUS:
        if kind == cap.UNK_BUS_OR_LOCK_STUCK:
            return f"inverter write lock held for {lock_age_s & U32} s (possible leak); a reboot may be required"
        return f"another inverter transaction is in progress ({owner}); try again shortly"
    if kind == cap.UNK_BOOT_NOT_LOADED:
        return "durable state not loaded yet"
    if kind == cap.UNK_DURABLE_UNREADABLE:
        if basis == cap.BASIS_RUNTIME_PROBE:
            return (d + " recovery marker became unreadable at runtime; saving blocked until reboot. After reboot it may "
                    "read absent: verify live settings first; do not erase NVS")
        return (d + " recovery state UNKNOWN since boot (marker unreadable); an obligation cannot be ruled out; Fallback "
                "never proceeds past it")
    if kind == cap.UNK_METADATA_CORRUPT:
        if basis == cap.BASIS_RUNTIME_PROBE:
            return (d + " recovery marker is malformed (found at runtime); saving blocked until reboot, which re-derives "
                    "it as a hard lockout")
        text = (d + " recovery metadata is CORRUPT (hard lockout); Fallback never overwrites or proceeds past it; do not "
                "erase NVS")
        if slot == cap.SLOT_DUMP and dump_containment != 0:
            text += f"; containment K={dump_containment}"
        return text
    if kind == cap.UNK_DIVERGED:
        if basis in (cap.BASIS_GHOST_RR, cap.BASIS_GHOST_PC):
            word = "RESTORE_REQUIRED" if basis == cap.BASIS_GHOST_RR else "PENDING_CLEAR"
            return (d + f" stored marker says {word} but memory says clear; saving blocked until reboot, which re-derives "
                    "it (the domain may then restore its saved original)")
        return d + " in-memory recovery state is inconsistent; a reboot must re-derive it before saving"
    if kind == cap.UNK_BUS_OR_LOCK_STUCK:
        return d + " in-progress flag is set with no running operation (possible leak); a reboot re-derives it"
    if kind == cap.OBL_ACTIVE:
        if basis == cap.BASIS_FBS_EPISODE:
            return "a failback episode record exists; only the firmware that created it can resolve it"
        return d + " is active; live settings are a temporary overlay - end it first"
    if kind == cap.OBL_RESTORE_REQUIRED:
        return d + " must restore original settings first"
    if kind == cap.OBL_PENDING_CLEAR:
        return d + " restore verified; durable clear still pending" + (" - press Restore Original (armed)" if slot == cap.SLOT_R244 else "")
    if kind == cap.OBL_OPERATOR_NEEDED:
        return d + " needs an operator recovery action first"
    if kind == cap.OBL_STARTING:
        return "a " + d + " start is in progress; live settings are about to become a temporary overlay"
    if kind == cap.OBL_ENDING:
        return "a " + d + " restore or recovery action is running; try again when it finishes"
    return d + " state does not permit saving"


def save_slot_refusal_text(slot: int, c: cap.SlotClass, dump_containment: int, owner: str, lock_age_s: int) -> TextBuf:
    return _tb(SAVE_REFUSED_PREFIX + _slot_body(slot, c, dump_containment, owner, lock_age_s))


def save_gate_refusal_text(gr: cap.GateResult, g: cap.GateInputs) -> TextBuf:
    owner = cap.bus_owner_text_with_leases(g.bus, gr.fp, gr.dump)
    age_s = cap.lock_age_ms(g.bus) // 1000
    dc = g.dump.dump_containment_state
    code = gr.code
    if code in (cap.GATE_ACCEPT, cap.GATE_NEED_PROBE):
        return _tb("")
    if code == cap.GATE_REFUSE_IN_FLIGHT:
        return save_in_flight_text()
    if code == cap.GATE_REFUSE_NOT_LOADED:
        return save_not_loaded_text()
    if code == cap.GATE_REFUSE_ARMS:
        return save_arms_text()
    slot_of = {cap.GATE_REFUSE_BUS: (cap.SLOT_BUS, gr.bus), cap.GATE_REFUSE_FBS: (cap.SLOT_FBS, gr.fbs),
               cap.GATE_REFUSE_FP: (cap.SLOT_FP, gr.fp), cap.GATE_REFUSE_DUMP: (cap.SLOT_DUMP, gr.dump),
               cap.GATE_REFUSE_R244: (cap.SLOT_R244, gr.r244), cap.GATE_REFUSE_MTOU: (cap.SLOT_MTOU, gr.mtou)}
    if code in slot_of:
        slot, c = slot_of[code]
        return save_slot_refusal_text(slot, c, dc, owner, age_s)
    return save_internal_text()


# ---------------------------------------------------------------------------
# The SAVE gate
# ---------------------------------------------------------------------------
@dataclass
class SaveGateInputs:
    arm_was_on: bool = False
    cand_valid: bool = False
    cand_saveable: bool = False
    cand_id: int = 0
    cand_ms: int = 0
    cand_prior_class: int = 0
    cand_writes_fp: int = 0
    now_ms: int = 0
    writes_fp_now: int = 0
    boot_loaded: bool = False
    unconfirmed: bool = True
    read_anomaly: int = 0xFF
    hb_ok: bool = False
    time_trusted: bool = False
    CTYPES = {"arm_was_on": "bool", "cand_valid": "bool", "cand_saveable": "bool", "cand_id": "uint64_t", "cand_ms": "uint32_t",
              "cand_prior_class": "uint8_t", "cand_writes_fp": "uint32_t", "now_ms": "uint32_t", "writes_fp_now": "uint32_t",
              "boot_loaded": "bool", "unconfirmed": "bool", "read_anomaly": "uint8_t", "hb_ok": "bool", "time_trusted": "bool"}


@dataclass
class SaveGateResult:
    code: int = SG_UNSET
    arm_off_only: bool = False
    replace_corrupt: bool = False
    obl: TextBuf = field(default_factory=TextBuf)
    text: TextBuf = field(default_factory=TextBuf)
    CTYPES = {"code": "uint8_t", "arm_off_only": "bool", "replace_corrupt": "bool"}


def save_in_flight_gate(op_in_progress: bool, dispatch_running: bool) -> SaveGateResult:
    r = SaveGateResult()
    if op_in_progress or dispatch_running:
        r.code = SG_IN_FLIGHT
        r.arm_off_only = True
        r.text = save_in_flight_text()
    return r


def save_refuse(r: SaveGateResult, code: int, text) -> SaveGateResult:
    out = replace(r)
    out.code = code
    out.text = _tb(str(text))
    return out


def save_gate_with_result(inp: SaveGateInputs, action, action_len: int, target_id, target_len: int, confirmation,
                          confirmation_len: int, g: cap.GateInputs, gr: cap.GateResult) -> SaveGateResult:
    r = SaveGateResult()
    r.obl = gr.obl
    if gr.code == cap.GATE_REFUSE_IN_FLIGHT:  # G1
        r = save_refuse(r, SG_IN_FLIGHT, save_in_flight_text())
        r.arm_off_only = True
        return r
    token = action_token(action, action_len)
    if token != ACT_SAVE:  # G0
        return save_refuse(r, SG_UNSUPPORTED, action_refusal_text(token, action, action_len))
    if not inp.arm_was_on:  # G2
        return save_refuse(r, SG_ARM_OFF, save_arm_off_text())
    if not inp.cand_valid or not inp.cand_saveable or inp.cand_id == 0:  # G3
        return save_refuse(r, SG_NO_CANDIDATE, save_no_candidate_text())
    if cap.candidate_expired(inp.now_ms, inp.cand_ms):  # G4
        return save_refuse(r, SG_EXPIRED, save_expired_text())
    if not is_hex16(target_id, target_len):  # G5
        return save_refuse(r, SG_ID_FORMAT, save_id_format_text())
    if parse_hex16(target_id, target_len) != inp.cand_id:  # G6
        return save_refuse(r, SG_ID_MISMATCH, save_id_mismatch_text())
    replace_ = fd.save_requires_replace_phrase(inp.cand_prior_class)
    expected = expected_phrase(PHRASE_SAVE_REPLACE_CORRUPT if replace_ else PHRASE_SAVE, inp.cand_id)
    if not phrase_equals(confirmation, confirmation_len, expected):  # G7
        return save_refuse(r, SG_PHRASE, save_phrase_text(expected))
    if not inp.boot_loaded:  # G8
        return save_refuse(r, SG_NOT_LOADED, save_not_loaded_text())
    if inp.unconfirmed:  # G9
        return save_refuse(r, SG_UNCONFIRMED, save_prior_unknown_text())
    if inp.read_anomaly != 0:  # G9a
        return save_refuse(r, SG_ANOMALY, save_anomaly_text())
    if not inp.hb_ok:  # G10
        return save_refuse(r, SG_HB, save_hb_text())
    if not inp.time_trusted:  # G11
        return save_refuse(r, SG_TIME, save_time_text())
    if gr.code == cap.GATE_REFUSE_NOT_LOADED:  # the capture gate disagrees with G8
        return save_refuse(r, SG_NOT_LOADED, save_not_loaded_text())
    if gr.code == cap.GATE_REFUSE_ARMS:  # G12
        return save_refuse(r, SG_ARMS, save_arms_text())
    if (inp.writes_fp_now & U32) != (inp.cand_writes_fp & U32):  # G13
        return save_refuse(r, SG_WRITES, save_writes_text())
    slot_text = save_gate_refusal_text(gr, g)
    code_of = {cap.GATE_REFUSE_BUS: SG_BUS, cap.GATE_REFUSE_FBS: SG_FBS, cap.GATE_REFUSE_FP: SG_FP,
               cap.GATE_REFUSE_DUMP: SG_DUMP, cap.GATE_REFUSE_R244: SG_R244, cap.GATE_REFUSE_MTOU: SG_MTOU}
    if gr.code in code_of:  # G14-G16
        return save_refuse(r, code_of[gr.code], slot_text)
    if gr.code in (cap.GATE_ACCEPT, cap.GATE_NEED_PROBE):
        r.code = SG_ACCEPT
        r.replace_corrupt = replace_
        return r
    return save_refuse(r, SG_UNSET, save_internal_text())  # GATE_UNSET or an unknown code: never an accept


def save_gate_decide(inp: SaveGateInputs, action, action_len: int, target_id, target_len: int, confirmation,
                     confirmation_len: int, g: cap.GateInputs) -> SaveGateResult:
    return save_gate_with_result(inp, action, action_len, target_id, target_len, confirmation, confirmation_len, g,
                                 cap.gate_decide(g, cap.ProbeResults()))


# ---------------------------------------------------------------------------
# SAVE final
# ---------------------------------------------------------------------------
def final_phase_inputs(g: cap.GateInputs) -> cap.GateInputs:
    """A copy of g with exactly the three own holds cleared (op flag, capture dispatch, shared write lock)."""
    bus = replace(g.bus, fallback_profile_op_in_progress=False, fallback_profile_capture_dispatch_running=False,
                  manual_write_in_progress=False)
    return replace(g, bus=bus, fp=replace(g.fp), dump=replace(g.dump), r244=replace(g.r244))


@dataclass
class FinalGate:
    gr: cap.GateResult = field(default_factory=cap.GateResult)
    text: TextBuf = field(default_factory=TextBuf)


def final_gate_decide(g: cap.GateInputs, pr: cap.ProbeResults) -> FinalGate:
    f = FinalGate()
    m = final_phase_inputs(g)
    f.gr = cap.gate_decide(m, pr)
    f.text = save_gate_refusal_text(f.gr, m)
    return f


def commit_bus_quiet(op_in_progress: bool, mutex_held: bool, correction_in_progress: bool, tx_buffer_empty: bool,
                     tx_blocked: bool) -> bool:
    return bool(op_in_progress and mutex_held and not correction_in_progress and tx_buffer_empty and not tx_blocked)


def save_bus_quiet_text() -> TextBuf:
    return save_refused("inverter bus not quiet at commit; profile unchanged")


def clock_trusted_for_save(time_trusted: bool, epoch: int) -> bool:
    return bool(time_trusted and (epoch & U32) != 0)


# ---------------------------------------------------------------------------
# Text: SAVE final refusals
# ---------------------------------------------------------------------------
def save_prior_changed_text() -> TextBuf:
    return save_refused("stored profile changed since Review; profile unchanged")


def save_generation_text() -> TextBuf:
    return save_refused("profile generation counter exhausted; profile unchanged")


def save_internal_record_text() -> TextBuf:
    return save_refused("internal: built record did not validate; nothing written")


def save_class_text(cls: int, why: int) -> TextBuf:
    if cls == fd.EPC_SAVE_UNCONFIRMED:
        return save_prior_unknown_text()
    if cls == fd.EPC_UNREADABLE:
        return save_refused("stored profile UNREADABLE (" + cap.why_name(why) + "); reboot to re-derive it (it will then "
                            "read VALID, LOST or NOT_CAPTURED)")
    return save_refused("stored profile state does not permit saving")


def save_read_fail_text(code: int, step: int, exception_code: int) -> TextBuf:
    if code == cap.READ_IDLE_TIMEOUT:
        return save_refused("inverter bus stayed busy for 7 s; profile unchanged; review again")
    detail = str(cap.read_fail_text(code, step, exception_code))[len(cap.NOT_COMPLETED_PREFIX):]
    return save_refused(detail + "; profile unchanged")


def save_changed_during_read_text(a, b) -> TextBuf:
    k = cap.first_diff(a, b)
    va, vb = (a[k], b[k]) if k >= 0 else (0, 0)
    return save_refused(f"live configuration changed during the read (register {cap.reg_of(k)}: {va} then {vb}); "
                        "profile unchanged")


def save_changed_since_review_text(candidate, pass2) -> TextBuf:
    k = cap.first_diff(candidate, pass2)
    va, vb = (candidate[k], pass2[k]) if k >= 0 else (0, 0)
    return save_refused(f"live configuration changed since Review (register {cap.reg_of(k)}: reviewed {va}, now {vb}); "
                        "profile unchanged; review again")


def save_l2_text(r: cap.Refusals, words) -> TextBuf:
    reasons = str(cap.not_saveable_text(r, words, fd.EPC_VALID, 0))[25:]
    return save_refused(reasons + "; profile unchanged")


# ---------------------------------------------------------------------------
# The INVALIDATE gate
# ---------------------------------------------------------------------------
@dataclass
class InvalidateGateInputs:
    arm_was_on: bool = False
    boot_loaded: bool = False
    read_anomaly: int = 0xFF
    unconfirmed: bool = True
    cls: int = fd.EPC_UNREADABLE
    p_load: int = fp.LOAD_STORAGE_UNAVAILABLE
    p: dict = field(default_factory=fp.blank_profile)
    w_load: int = fp.LOAD_STORAGE_UNAVAILABLE
    w: dict = field(default_factory=fd.blank_provision)
    seen_hw_gen: int = 0xFFFFFFFF
    bus: cap.BusInputs = field(default_factory=cap.BusInputs)
    tx_buffer_empty: bool = False
    tx_blocked: bool = True
    fbs_slot: int = fd.FBS_UNREADABLE
    CTYPES = {"arm_was_on": "bool", "boot_loaded": "bool", "read_anomaly": "uint8_t", "unconfirmed": "bool", "cls": "uint8_t",
              "p_load": "uint8_t", "w_load": "uint8_t", "seen_hw_gen": "uint32_t", "tx_buffer_empty": "bool", "tx_blocked": "bool",
              "fbs_slot": "uint8_t"}


@dataclass
class InvalidateGateResult:
    code: int = IG_UNSET
    arm_off_only: bool = False
    text: TextBuf = field(default_factory=TextBuf)
    CTYPES = {"code": "uint8_t", "arm_off_only": "bool"}


def invalidate_in_flight_text() -> TextBuf:
    return invalidate_refused("another Fallback Profile operation is in progress")


def invalidate_arm_off_text() -> TextBuf:
    return invalidate_refused("ECCO Fallback Profile Arm is not on")


def invalidate_id_format_text() -> TextBuf:
    return invalidate_refused("profile ID must be 16 hex characters")


def invalidate_phrase_text(expected) -> TextBuf:
    return invalidate_refused("confirmation phrase mismatch (expected '" + str(expected) + "')")


def invalidate_not_loaded_text() -> TextBuf:
    return invalidate_refused("durable state not loaded yet (starting up)")


def invalidate_anomaly_text() -> TextBuf:
    return invalidate_refused("stored profile read anomaly this boot; reboot to re-derive first")


def invalidate_prior_unknown_text() -> TextBuf:
    return invalidate_refused("previous Fallback Profile write outcome unknown this boot - reboot to re-verify first")


def invalidate_class_text(cls: int) -> TextBuf:
    return invalidate_refused("profile is " + cap.epc_name(cls) + "; only a VALID profile can be invalidated")


def invalidate_id_mismatch_text() -> TextBuf:
    return invalidate_refused("profile ID does not match the stored VALID profile")


def invalidate_generation_text(exhausted: bool) -> TextBuf:
    if exhausted:
        return invalidate_refused("generation counter exhausted")
    return invalidate_refused("profile generation is not ahead of this boot's generation high-water mark; reboot to re-verify")


def invalidate_busy_text() -> TextBuf:
    return invalidate_refused("inverter busy; try again")


def invalidate_fbs_text(c: cap.SlotClass) -> TextBuf:
    return invalidate_refused(_slot_body(cap.SLOT_FBS, c, 0, "", 0))


def invalidate_bus_idle(b: cap.BusInputs, tx_buffer_empty: bool, tx_blocked: bool) -> bool:
    return bool((not cap.bus_busy(b)) and tx_buffer_empty and not tx_blocked)


def invalidate_in_flight_gate(op_in_progress: bool, dispatch_running: bool) -> InvalidateGateResult:
    r = InvalidateGateResult()
    if op_in_progress or dispatch_running:
        r.code = IG_IN_FLIGHT
        r.arm_off_only = True
        r.text = invalidate_in_flight_text()
    return r


def invalidate_refuse(r: InvalidateGateResult, code: int, text) -> InvalidateGateResult:
    out = replace(r)
    out.code = code
    out.text = _tb(str(text))
    return out


def invalidate_gate_decide(inp: InvalidateGateInputs, action, action_len: int, target_id, target_len: int, confirmation,
                           confirmation_len: int) -> InvalidateGateResult:
    r = InvalidateGateResult()
    if inp.bus.fallback_profile_op_in_progress or inp.bus.fallback_profile_capture_dispatch_running:  # I1
        r = invalidate_refuse(r, IG_IN_FLIGHT, invalidate_in_flight_text())
        r.arm_off_only = True
        return r
    token = action_token(action, action_len)
    if token != ACT_INVALIDATE:
        return invalidate_refuse(r, IG_UNSUPPORTED, action_refusal_text(token, action, action_len))
    if not inp.arm_was_on:  # I2
        return invalidate_refuse(r, IG_ARM_OFF, invalidate_arm_off_text())
    if not is_hex16(target_id, target_len):  # I3
        return invalidate_refuse(r, IG_ID_FORMAT, invalidate_id_format_text())
    id_ = parse_hex16(target_id, target_len)
    expected = expected_phrase(PHRASE_INVALIDATE, id_)
    if not phrase_equals(confirmation, confirmation_len, expected):  # I4
        return invalidate_refuse(r, IG_PHRASE, invalidate_phrase_text(expected))
    if not inp.boot_loaded:  # I5
        return invalidate_refuse(r, IG_NOT_LOADED, invalidate_not_loaded_text())
    if inp.read_anomaly != 0:  # I6
        return invalidate_refuse(r, IG_ANOMALY, invalidate_anomaly_text())
    if inp.unconfirmed:  # I7
        return invalidate_refuse(r, IG_UNCONFIRMED, invalidate_prior_unknown_text())
    if not fd.invalidate_class_permitted(inp.cls):  # I8
        return invalidate_refuse(r, IG_CLASS, invalidate_class_text(inp.cls))
    p = _prof(inp.p)
    w = _wit(inp.w)
    if inp.p_load != fp.LOAD_OK or p["binding"] != id_:  # I9
        return invalidate_refuse(r, IG_ID_MISMATCH, invalidate_id_mismatch_text())
    wc = fd.classify_witness(inp.w_load, w)
    if not fp.profile_invalidate_permitted(p) or not fd.invalidate_generation_permitted(
            p["generation"], wc, w["hw_generation"], inp.seen_hw_gen):  # I10
        return invalidate_refuse(r, IG_GENERATION, invalidate_generation_text(p["generation"] == fd.GENERATION_MAX))
    if not invalidate_bus_idle(inp.bus, inp.tx_buffer_empty, inp.tx_blocked):  # I11
        return invalidate_refuse(r, IG_BUS, invalidate_busy_text())
    if not fd.fbs_slot_clear(inp.fbs_slot):  # I12
        gi = cap.GateInputs()
        gi.boot_loaded = inp.boot_loaded
        gi.fbs_slot = inp.fbs_slot
        return invalidate_refuse(r, IG_FBS, invalidate_fbs_text(cap.classify_fbs(gi)))
    r.code = IG_ACCEPT
    return r


# ---------------------------------------------------------------------------
# Building the intended FBP / FBW pair
# ---------------------------------------------------------------------------
@dataclass
class SavePlanInputs:
    p_load: int = fp.LOAD_STORAGE_UNAVAILABLE
    p: dict = field(default_factory=fp.blank_profile)
    p_stored_len: int = 0
    w_load: int = fp.LOAD_STORAGE_UNAVAILABLE
    w: dict = field(default_factory=fd.blank_provision)
    w_stored_len: int = 0
    cls: int = fd.EPC_UNREADABLE
    why: int = 0
    read_anomaly: int = 0xFF
    unconfirmed: bool = True
    seen_hw_gen: int = 0xFFFFFFFF
    cand_prior_class: int = 0
    cand_prior_gen: int = 0
    cand_prior_binding: int = 0
    replace_corrupt: bool = False
    words: list = field(default_factory=lambda: [0] * cap.REG_COUNT)
    captured_epoch: int = 0
    CTYPES = {"p_load": "uint8_t", "p_stored_len": "uint32_t", "w_load": "uint8_t", "w_stored_len": "uint32_t", "cls": "uint8_t", "why": "uint8_t",
              "read_anomaly": "uint8_t", "unconfirmed": "bool", "seen_hw_gen": "uint32_t", "cand_prior_class": "uint8_t",
              "cand_prior_gen": "uint32_t", "cand_prior_binding": "uint64_t", "replace_corrupt": "bool", "words": "uint16_t",
              "captured_epoch": "uint32_t"}


@dataclass
class InvalidatePlanInputs:
    p_load: int = fp.LOAD_STORAGE_UNAVAILABLE
    p: dict = field(default_factory=fp.blank_profile)
    p_stored_len: int = 0
    w_load: int = fp.LOAD_STORAGE_UNAVAILABLE
    w: dict = field(default_factory=fd.blank_provision)
    w_stored_len: int = 0
    cls: int = fd.EPC_UNREADABLE
    read_anomaly: int = 0xFF
    unconfirmed: bool = True
    seen_hw_gen: int = 0xFFFFFFFF
    target_id: int = 0
    CTYPES = {"p_load": "uint8_t", "p_stored_len": "uint32_t", "w_load": "uint8_t", "w_stored_len": "uint32_t", "cls": "uint8_t",
              "read_anomaly": "uint8_t", "unconfirmed": "bool", "seen_hw_gen": "uint32_t", "target_id": "uint64_t"}


@dataclass
class Plan:
    code: int = PLAN_UNSET
    text: TextBuf = field(default_factory=TextBuf)
    op: int = 0
    generation: int = 0
    p_new: dict = field(default_factory=fp.blank_profile)
    w_new: dict = field(default_factory=fd.blank_provision)
    CTYPES = {"code": "uint8_t", "op": "uint8_t", "generation": "uint32_t"}


def invalidate_changed_text() -> TextBuf:
    return invalidate_refused("stored profile changed; nothing written")


def invalidate_internal_text() -> TextBuf:
    return invalidate_refused("internal: built record did not validate; nothing written")


def invalidate_class_now_text(cls: int) -> TextBuf:
    return invalidate_refused("profile is now " + cap.epc_name(cls) + "; nothing written")


def plan_refuse(r: Plan, code: int, text) -> Plan:
    out = replace(r)
    out.code = code
    out.text = _tb(str(text))
    return out


def save_pair_valid(pn, wn, base: int) -> bool:
    pn, wn = _prof(pn), _wit(wn)
    cls, why, _rule = fd.compose_profile_class(fp.LOAD_OK, pn, fp.LOAD_OK, wn, 0)
    return (fp.classify_profile(fp.LOAD_OK, pn) == fp.PROFILE_VALID
            and fd.classify_witness(fp.LOAD_OK, wn) == fd.W_VALID
            and cls == fd.EPC_VALID and why == fd.WHY_NONE and pn["generation"] > base
            and wn["hw_generation"] == pn["generation"] and wn["hw_binding"] == pn["binding"])


def plan_save(inp: SavePlanInputs) -> Plan:
    r = Plan()
    p = _prof(inp.p)
    w = _wit(inp.w)
    f = cap.prior_fingerprint(inp.p_load, p, inp.p_stored_len)
    if inp.cls != inp.cand_prior_class or f.generation != inp.cand_prior_gen or f.binding != inp.cand_prior_binding:
        return plan_refuse(r, PLAN_PRIOR_CHANGED, save_prior_changed_text())
    cls = overlay_class(inp.cls, inp.unconfirmed)
    if inp.unconfirmed:
        return plan_refuse(r, PLAN_UNCONFIRMED, save_prior_unknown_text())
    if inp.read_anomaly != 0:
        return plan_refuse(r, PLAN_ANOMALY, save_anomaly_text())
    if not fd.save_class_permitted(cls):
        return plan_refuse(r, PLAN_CLASS, save_class_text(cls, inp.why))
    replace_ = fd.save_requires_replace_phrase(cls)
    if bool(inp.replace_corrupt) != replace_:
        return plan_refuse(r, PLAN_CONTEXT, cap.internal_context_text())
    if (inp.captured_epoch & U32) == 0:
        return plan_refuse(r, PLAN_CLOCK, save_time_text())
    pc = fp.classify_profile(inp.p_load, p)
    wc = fd.classify_witness(inp.w_load, w)
    base = fd.save_generation_base(pc, p["generation"], wc, w["hw_generation"], inp.seen_hw_gen)
    if not fd.save_generation_available(base):
        return plan_refuse(r, PLAN_GENERATION, save_generation_text())
    gen = (base + 1) & U32
    pn = cap.profile_from_words(inp.words)
    pn["generation"] = gen
    pn["captured_epoch"] = inp.captured_epoch & U32
    pn["flags"] = 0
    pn["reserved0"] = 0
    pn["reserved1"] = 0
    pn = fp.seal_profile(pn)
    authentic = fd.fba_authentic(pc)
    op = fd.PROV_OP_REPLACE_CORRUPT if replace_ else fd.PROV_OP_SAVE
    wn = fd.make_provision(gen, pn["binding"], p["generation"] if authentic else 0, p["binding"] if authentic else 0,
                           fd.FALLBACK_PROFILE_KEY, fp.PROFILE_SCHEMA, op)
    if not save_pair_valid(pn, wn, base) or not fd.validate_transition(
            wn, w, (inp.w_load, inp.w_stored_len), pn, p, (inp.p_load, inp.p_stored_len)):
        return plan_refuse(r, PLAN_INTERNAL, save_internal_record_text())
    r.code = PLAN_OK
    r.op = op
    r.generation = gen
    r.p_new = pn
    r.w_new = wn
    return r


def invalidate_pair_valid(pn, wn, prior) -> bool:
    pn, wn, prior = _prof(pn), _wit(wn), _prof(prior)
    cls, why, _rule = fd.compose_profile_class(fp.LOAD_OK, pn, fp.LOAD_OK, wn, 0)
    a, b = fp.pack_profile(pn), fp.pack_profile(prior)
    for i in range(fp.PROFILE_BOUND_BYTES):
        changed_field = 8 <= i < 12 or 16 <= i < 18
        if not changed_field and a[i] != b[i]:
            return False
    return (fp.classify_profile(fp.LOAD_OK, pn) == fp.PROFILE_INVALIDATED
            and fd.classify_witness(fp.LOAD_OK, wn) == fd.W_VALID
            and cls == fd.EPC_INVALIDATED and why == fd.WHY_NONE and wn["hw_generation"] == pn["generation"]
            and wn["hw_binding"] == pn["binding"] and wn["last_op"] == fd.PROV_OP_INVALIDATE)


def plan_invalidate(inp: InvalidatePlanInputs) -> Plan:
    r = Plan()
    p = _prof(inp.p)
    w = _wit(inp.w)
    cls = overlay_class(inp.cls, inp.unconfirmed)
    if inp.unconfirmed:
        return plan_refuse(r, PLAN_UNCONFIRMED, invalidate_prior_unknown_text())
    if inp.read_anomaly != 0:
        return plan_refuse(r, PLAN_ANOMALY, invalidate_anomaly_text())
    if not fd.invalidate_class_permitted(cls):
        return plan_refuse(r, PLAN_CLASS, invalidate_class_now_text(cls))
    if inp.p_load != fp.LOAD_OK or p["binding"] != (inp.target_id & U64):
        return plan_refuse(r, PLAN_BINDING_CHANGED, invalidate_changed_text())
    wc = fd.classify_witness(inp.w_load, w)
    if not fp.profile_invalidate_permitted(p) or not fd.invalidate_generation_permitted(
            p["generation"], wc, w["hw_generation"], inp.seen_hw_gen):
        return plan_refuse(r, PLAN_GENERATION, invalidate_generation_text(p["generation"] == fd.GENERATION_MAX))
    pn = fd.invalidate_profile_cxx(p)
    wn = fd.make_provision(pn["generation"], pn["binding"], p["generation"], p["binding"], fd.FALLBACK_PROFILE_KEY,
                           fp.PROFILE_SCHEMA, fd.PROV_OP_INVALIDATE)
    if not invalidate_pair_valid(pn, wn, p) or not fd.validate_transition(
            wn, w, (inp.w_load, inp.w_stored_len), pn, p, (inp.p_load, inp.p_stored_len)):
        return plan_refuse(r, PLAN_INTERNAL, invalidate_internal_text())
    r.code = PLAN_OK
    r.op = fd.PROV_OP_INVALIDATE
    r.generation = pn["generation"]
    r.p_new = pn
    r.w_new = wn
    return r


# ---------------------------------------------------------------------------
# The outcome of the writer call
# ---------------------------------------------------------------------------
def first_non_ok(err_w: int, err_p: int) -> int:
    return (err_w if err_w != 0 else err_p) & U32


def total_us(w_us: int, p_us: int) -> int:
    return (w_us + p_us) & U32


def txn_op_name(op: int) -> str:
    """The long operation name of the log line (S2 1.9): SAVE / INVALIDATE / REPLACE_CORRUPT; '-' for any other value."""
    return {fd.PROV_OP_SAVE: "SAVE", fd.PROV_OP_INVALIDATE: "INVALIDATE", fd.PROV_OP_REPLACE_CORRUPT: "REPLACE_CORRUPT"}.get(op, "-")


def txn_name(outcome: int) -> str:
    return {fd.TXN_UNKNOWN_REBOOT: "UNKNOWN_REBOOT", fd.TXN_COMMITTED: "COMMITTED", fd.TXN_NOT_COMMITTED: "NOT_COMMITTED",
            fd.TXN_REFUSED_LATCHED: "REFUSED_LATCHED"}.get(outcome, "?")


def key_name(outcome: int) -> str:
    return {fd.KEY_UNKNOWN_REBOOT: "UNKNOWN_REBOOT", fd.KEY_COMMITTED: "COMMITTED", fd.KEY_NOT_COMMITTED: "NOT_COMMITTED",
            fd.KEY_NOT_ATTEMPTED: "NOT_ATTEMPTED"}.get(outcome, "?")


def rb_name(rb_class: int) -> str:
    return {fd.RB_NOT_READ: "NOT_READ", fd.RB_INTENDED: "INTENDED", fd.RB_PRIOR: "PRIOR", fd.RB_OTHER_BYTES: "OTHER_BYTES",
            fd.RB_ABSENT_UNEXPECTED: "ABSENT_UNEXPECTED", fd.RB_WRONG_SIZE: "WRONG_SIZE", fd.RB_READ_ERROR: "READ_ERROR",
            fd.RB_UNAVAILABLE: "UNAVAILABLE"}.get(rb_class, "?")


def _err(err: int) -> str:
    err &= U32
    return "-" if err == 0 else "E" + _hex(err, 1)


def _unknown_detail(r: fd.TxnResult) -> str:
    k = r.w if r.w.outcome == fd.KEY_UNKNOWN_REBOOT else r.p
    return _err(k.err) + "/" + rb_name(k.rb_class)


def saved_text(generation: int) -> TextBuf:
    return _tb(f"SAVED - known-good profile generation {generation & U32} saved (verified this boot)")


def save_not_committed_text(err: int) -> TextBuf:
    return _tb(f"SAVE NOT COMMITTED - storage refused the write ({_err(err)}); nothing changed")


def save_witness_advanced_text() -> TextBuf:
    return _tb("SAVE NOT COMMITTED - witness advanced; profile unchanged; stored profile is now out of step - review and "
               "save again")


def save_unknown_text(r: fd.TxnResult) -> TextBuf:
    return _tb("SAVE OUTCOME UNKNOWN - storage reported " + _unknown_detail(r) + "; reboot the dongle (when no temporary "
               "operation is active) to re-verify; saving disabled until then")


def invalidated_text(prior_generation: int, generation: int) -> TextBuf:
    return _tb(f"INVALIDATED - profile generation {prior_generation & U32} is no longer usable (now INVALIDATED "
               f"g{generation & U32}); payload kept for reference; save a new profile to re-enable")


def invalidate_not_committed_text(err: int, prior_generation: int) -> TextBuf:
    return _tb(f"INVALIDATE NOT COMMITTED - storage refused the write ({_err(err)}); profile still VALID "
               f"g{prior_generation & U32}")


def invalidate_witness_advanced_text(prior_generation: int) -> TextBuf:
    return _tb("INVALIDATE NOT COMMITTED for the profile record, but the generation record advanced: "
               f"g{prior_generation & U32} is now STALE (unusable)")


def invalidate_unknown_text(r: fd.TxnResult) -> TextBuf:
    return _tb("INVALIDATE OUTCOME UNKNOWN - " + _unknown_detail(r) + "; treat the profile as unusable; reboot to re-verify "
               "(Fallback Profile writes locked until reboot)")


def txn_refusal_text(op: int, refusal: int) -> TextBuf:
    inv = op == fd.PROV_OP_INVALIDATE
    if refusal == fd.REFUSAL_LATCHED:
        return invalidate_prior_unknown_text() if inv else save_prior_unknown_text()
    if refusal == fd.REFUSAL_INVALID_TRANSITION:
        return invalidate_internal_text() if inv else save_internal_record_text()
    if refusal == fd.REFUSAL_STORAGE_UNAVAILABLE:
        return invalidate_refused("storage unavailable - nothing written") if inv else save_refused("storage unavailable - nothing saved")
    if refusal == fd.REFUSAL_STORAGE_UNHEALTHY:
        return invalidate_refused("storage not healthy - nothing written") if inv else save_refused("storage not healthy - nothing saved")
    body = "internal: write refused for an unknown reason; nothing written"
    return invalidate_refused(body) if inv else save_refused(body)


def txn_outcome_text(op: int, outcome: int, r: fd.TxnResult, generation: int, prior_generation: int) -> TextBuf:
    inv = op == fd.PROV_OP_INVALIDATE
    if not inv and op not in (fd.PROV_OP_SAVE, fd.PROV_OP_REPLACE_CORRUPT):
        return cap.internal_context_text()
    if outcome == fd.TXN_COMMITTED:
        return invalidated_text(prior_generation, generation) if inv else saved_text(generation)
    if outcome == fd.TXN_NOT_COMMITTED:
        if r.witness_advanced:
            return invalidate_witness_advanced_text(prior_generation) if inv else save_witness_advanced_text()
        return (invalidate_not_committed_text(r.w.err, prior_generation) if inv else save_not_committed_text(r.w.err))
    if outcome == fd.TXN_REFUSED_LATCHED:
        return txn_refusal_text(op, r.refusal)
    return invalidate_unknown_text(r) if inv else save_unknown_text(r)


def txn_log_text(op: int, outcome: int, r: fd.TxnResult, generation: int) -> TextBuf:
    """S2 1.9: txn=<SAVE|INVALIDATE|REPLACE_CORRUPT> gen=<n> w:err=.. rb=.. out=.. p:err=.. rb=.. out=.. total_us=<n> -> <TxnOutcome>.
    The per-key us= fields of S2 1.9 are NOT printed: with the long operation names the line would be 213 characters at the widest values
    (over the 200-character TextBuf), without them it is 185; total_us (their wrapping sum) is the figure LP-B2 records."""
    return _tb(f"txn={txn_op_name(op)} gen={generation & U32} w:err={_err(r.w.err)} rb={rb_name(r.w.rb_class)} "
               f"out={key_name(r.w.outcome)} p:err={_err(r.p.err)} rb={rb_name(r.p.rb_class)} "
               f"out={key_name(r.p.outcome)} total_us={total_us(r.w.us, r.p.us)} -> {txn_name(outcome)}")


def replace_corrupt_log_text(p_load: int, p, stored_len: int, part: int) -> TextBuf:
    if p_load == fp.LOAD_WRONG_SIZE and part == 0:
        return _tb(f"REPLACE CORRUPT discards a stored profile of the wrong size, stored length {stored_len & U32}")
    if p_load != fp.LOAD_OK or part > 1:
        return _tb("")
    raw = fp.pack_profile(_prof(p))
    head = "REPLACE CORRUPT discards stored profile bytes 0-47: " if part == 0 else \
        "REPLACE CORRUPT discards stored profile bytes 48-95: "
    return _tb(head + "".join(f"{raw[i]:02X}" for i in range(part * 48, part * 48 + 48)))
