"""Python mirror of the FB-B1 pure capture header (C++-exact).

firmware/include/ecco_fallback_capture.h (namespace ecco_fbcap) is the C++
side. FB-B1 is the READ-ONLY "Review Current Configuration" flow of the
Fallback Profile: a gate, four distinct FC03 reads (230/3, 241/53, 230/3,
241/53), a 31-word compare, a RAM-only candidate and the text entities that
publish all of it. Every decision the firmware lambdas take is a PURE
function of plain values and lives in the header; the lambdas only gather
RAM flags into the POD structs below, make ONE call per decision and publish
the result. This module is the independent mirror the offline suites hold
the header to:
  - registry/tests/test_fallback_capture_model.py exercises every function
    here (truth tables, every classifier row, every grammar, worst-case
    lengths);
  - registry/tests/test_fallback_capture_host_compile.py makes a real C++
    compiler evaluate the header's static_asserts and requires every golden
    value / golden string to equal what this module produces;
  - registry/tests/_fbb_harness.py adapts this module generically as the
    namespace `ecco_fbcap` when it simulates the firmware lambdas.

NAMING. Every function, constant and struct field below has the SAME
snake_case name as in the C++ namespace. The POD structs use the real
firmware global ids as field names (free_power_snapshot_valid, ...), so a
lambda line `gi.fp.free_power_snapshot_valid = id(free_power_snapshot_valid);`
is greppable on both sides. Structs are dataclasses; C++ std::array<uint16_t,
31> words are plain lists of 31 ints (`CaptureWords`); records are the dicts
of registry/fallback_profile.py / registry/fallback_durable.py (raw bytes are
accepted wherever the C++ takes a record). C++ TextBuf is TextBuf(str): a
plain str with c_str() and size(). Texts are cut at TEXT_CAP (200) exactly
like the C++ builders (which never overflow by construction; a test proves
every grammar at worst-case widths).

SIGNATURES (C++ shown; the Python parameters are the same, in the same order)
  words / L2
    int  first_diff(const CaptureWords &a, const CaptureWords &b)     first differing index k, or -1
    uint16_t reg_of(int k)                                            register number of word k (0 outside 0..30)
    bool store_block_230(CaptureWords &w, const V &values)            R1/R3 handler: words 19 (232) and 28 (230); false on a wrong size
    bool store_block_241(CaptureWords &w, const V &values)            R2/R4 handler: the other 29 words; false on a wrong size
    Refusals capture_refusals(const CaptureWords &w, uint32_t ceiling_w)   L2 refusals in the S1 10.2 order (never feeds classify_profile)
    uint16_t capture_warnings(const CaptureWords &w)                  L2w warnings, bit n-1 = Wn (W1..W6)
    TextBuf sv_text(const Refusals &r)                                B3 sv= value: OK | NO:c1[,c2[,c3]][+N]
    bool review_eligible(const Refusals &r, uint8_t cls, uint8_t read_anomaly)
    ReviewVerdict review_evaluate(const ReviewInputs &in)             REVIEW-final step 3/5/7 in one call
  fresh read (boot lambda and REVIEW-final step 4)
    ReadEval evaluate_read(const ReadInputs &in)                      note_read x2 + S1 divergence rule + next_seen_hw_gen + RE-compose
  gate (REVIEW gate lambda)
    GateResult gate_decide(const GateInputs &g, const ProbeResults &pr)   V1-V7 in one call; call twice when it answers GATE_NEED_PROBE
    uint8_t probe_result(uint8_t load, uint32_t magic, uint8_t state)     marker read -> PROBE_*
  housekeeping tick (10 s, RAM only)
    bool candidate_expired(uint32_t now_ms, uint32_t born_ms)
    uint32_t exp_seconds(uint32_t now_ms, uint32_t born_ms)
    uint8_t lease_domain_nonclear(const GateInputs &g)                IE7: SLOT_FP / SLOT_DUMP / SLOT_R244 or SLOT_NONE
    bool breaker_fired(bool op_in_progress, bool dispatch_running, uint32_t now_ms, uint32_t started_ms)
    uint32_t writes_fingerprint(a, b, c, d, e)                        IE11 u32 sum of the five attempt counters
  text builders (every one returns a TextBuf of at most 200 chars)
    b2_text b3_text b4_text b5_text b6_text b7_text b8_text, the B9 builders, vector_text, latch_text
    bool b3_value_fits(const char *s, size_t max_chars)               B3 obl / sv guard: a null, empty or over-long value renders `-`
    (B7 and B8 share ONE predicate, saved_view: both are NONE when the B7 SAVED text would exceed 200 characters)
  live match (B10, FB-B3; the same pure comparison FB-C2 calls)
    LiveMatchResult live_match(const LiveMatchInputs &in)             first-match-wins m, the four masks, eh, ca, elig, ew
    TextBuf b10_text(const LiveMatchResult &r) / b10_seed_text()      m;dx;cx;ox;ix;eh;obl;ca;elig;ew (<= 200 chars)
    uint8_t live_trust(const LiveCache &c, bool boot_loaded)          ca: first failing term (B I O S P M, else F)
    FenceState fence_tick(const FenceState &s, const FenceSample &t)  the write fence (seq + lease edge_seq), RAM only
    uint8_t export_hazard(...) / live_effective_class(cls, save_unconfirmed, read_anomaly)
  names: epc_name ld_name df_name w_name op_name why_name capture_state_name domain_label block_name obl_code

Pure: stdlib only, no I/O. Reuses registry/fallback_profile.py and
registry/fallback_durable.py for everything those already define.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fallback_durable as fd  # noqa: E402
import fallback_profile as fp  # noqa: E402

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
CANDIDATE_TTL_MS = 120000
IDLE_WAIT_MS = 7000
STEP_WAIT_MS = 3000
BREAKER_MS = 30000
LOCK_STUCK_MS = 300000
TEXT_CAP = 200
REG_COUNT = 31
DUMP_CONTROLLER_MAX_W = 3000          # W2: the Dump controller's maximum ceiling
REFUSAL_MAX = 40
B3_OBL_MAX = 36                       # grammar width of the obl vector FP:xx,DP:xx,R4:xx,MT:xx,FS:xx,BUS:xx
B3_SV_MAX = 26                        # widest sv NO:c1,c2,c3+N is 23; 26 leaves headroom
U32 = 0xFFFFFFFF

# Canonical register order == FallbackProfileV1 field order == offset 18 + 2k.
REGS = (244, 256, 257, 258, 259, 260, 261, 268, 269, 270, 271, 272, 273, 274, 275, 276, 277, 278, 279,
        232, 243, 248, 250, 251, 252, 253, 254, 255, 230, 245, 247)

PURPOSE_NONE, PURPOSE_REVIEW = 0, 1
CAPTURE_IDLE, CAPTURE_READING, CAPTURE_CANDIDATE_READY, CAPTURE_CANDIDATE_NOT_SAVEABLE, CAPTURE_SAVING = 0, 1, 2, 3, 4
(READ_NONE, READ_NO_RESPONSE, READ_EXCEPTION, READ_NOT_SENT, READ_NONSTANDARD, READ_SHORT, READ_BOUNDED_WAIT,
 READ_IDLE_TIMEOUT) = range(8)

# Marker probe results and the sticky runtime latch (u16, one nibble per domain).
(PROBE_NONE, PROBE_ABSENT, PROBE_CLEAR, PROBE_RESTORE_REQUIRED, PROBE_PENDING_CLEAR, PROBE_MALFORMED,
 PROBE_UNREADABLE) = range(7)
LATCH_NONE, LATCH_UNREADABLE, LATCH_MALFORMED, LATCH_GHOST_RR, LATCH_GHOST_PC = range(5)
DOM_FP, DOM_DUMP, DOM_R244 = 0, 1, 2

# Marker record facts (equal ecco_durable::VALID_MARKER_MAGIC / MARKER_*).
MARKER_RECORD_MAGIC = 0x45434356
MARKER_STATE_CLEAR, MARKER_STATE_RESTORE_REQUIRED, MARKER_STATE_PENDING_CLEAR = 0, 1, 2

# SG-06 marker boot loads (equal ecco_durable::LoadStatus) and the "not assigned" value.
BOOT_LOAD_OK, BOOT_LOAD_ABSENT, BOOT_LOAD_WRONG_SIZE, BOOT_LOAD_READ_ERROR, BOOT_LOAD_NOT_LOADED = 0, 1, 2, 3, 255

# Obligation kinds (charter C0 vocabulary) and bases. 0 is the fail-closed value.
(OBL_UNSET, OBL_CLEAR_PROVEN, OBL_ACTIVE, OBL_STARTING, OBL_RESTORE_REQUIRED, OBL_PENDING_CLEAR, OBL_ENDING,
 OBL_OPERATOR_NEEDED, UNK_DURABLE_UNREADABLE, UNK_METADATA_CORRUPT, UNK_BOOT_NOT_LOADED, UNK_DIVERGED,
 UNK_BUS_OR_LOCK_STUCK, UNK_NOT_PROBED, BUS_BUSY) = range(15)
(BASIS_NONE, BASIS_MARKER_CLEAR, BASIS_ABSENT, BASIS_NO_DURABLE_STATE, BASIS_BOOT_READ_ERROR, BASIS_BOOT_LOCKOUT,
 BASIS_RUNTIME_PROBE, BASIS_GHOST_RR, BASIS_GHOST_PC, BASIS_RAM_INCONSISTENT, BASIS_OP_FLAG_UNATTRIBUTED,
 BASIS_LEASE, BASIS_PRE_COMMIT, BASIS_COMMITTED, BASIS_RESTORE_RUNNING, BASIS_OPERATOR_ACTION_RUNNING,
 BASIS_FBS_EPISODE, BASIS_BUS_IDLE, BASIS_BUS_TXN, BASIS_LOCK_STUCK) = range(20)

# Slots, in the reporting / evaluation order of the gate.
SLOT_BUS, SLOT_FBS, SLOT_FP, SLOT_DUMP, SLOT_R244, SLOT_MTOU = range(6)
SLOT_NONE = 0xFF

# Gate codes. 0 is the fail-closed "no decision".
(GATE_UNSET, GATE_ACCEPT, GATE_NEED_PROBE, GATE_REFUSE_IN_FLIGHT, GATE_REFUSE_NOT_LOADED, GATE_REFUSE_ARMS,
 GATE_REFUSE_BUS, GATE_REFUSE_FBS, GATE_REFUSE_FP, GATE_REFUSE_DUMP, GATE_REFUSE_R244, GATE_REFUSE_MTOU) = range(12)

# L2 refusal kinds. An item is (kind << 8) | slot.
(RF_NONE, RF_244X, RF_PWRL, RF_PWRH, RF_SOCH, RF_SRCG, RF_MODE, RF_BITS, RF_HHMM, RF_243X, RF_CLASS,
 RF_ANOMALY) = range(12)

# Witness view codes for the B2 `w=` key (grammar order).
WVIEW_OK, WVIEW_LAG, WVIEW_MISS, WVIEW_CORR, WVIEW_UNR, WVIEW_ABS = range(6)

MTOU_JOURNAL_NOT_IMPLEMENTED = True
REASON_SUPERSEDED = "superseded"


class TextBuf(str):
    """A text builder result: a plain str (<= TEXT_CAP) with the C++ TextBuf accessors."""

    __slots__ = ()

    def c_str(self) -> str:
        return str(self)

    def size(self) -> int:
        return len(self)


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


def _bytes(raw) -> bytes:
    """Record bytes from bytes, a list / std::array of ints, or a harness record object."""
    if hasattr(raw, "to_bytes"):
        return raw.to_bytes()
    return bytes(raw)


# ---------------------------------------------------------------------------
# Names
# ---------------------------------------------------------------------------
_EPC = ("UNREADABLE", "NOT_CAPTURED", "CORRUPT", "CORRUPT_DOMAIN", "INVALIDATED", "VALID", "PROFILE_LOST",
        "SAVE_UNCONFIRMED", "PROFILE_STALE")


def epc_name(cls: int) -> str:
    """B1 value. TOTAL: every value outside 0..8 renders UNREADABLE (fail-closed)."""
    return _EPC[cls] if 0 <= cls < len(_EPC) else "UNREADABLE"


def ld_name(load: int) -> str:
    return {0: "OK", 1: "ABS", 2: "WSZ", 3: "RERR", 4: "UNAV"}.get(load, "RERR")


def df_name(defect: int) -> str:
    return {1: "MAGIC", 2: "SCHEMA", 3: "SIZE", 4: "BINDING", 5: "RESERVED", 6: "FLAGS", 7: "GEN",
            8: "DOMAIN"}.get(defect, "-")


def w_name(code: int) -> str:
    return ("OK", "LAG", "MISS", "CORR", "UNR", "ABS")[code] if 0 <= code <= 5 else "UNR"


def op_name(last_op: int) -> str:
    return {1: "SAVE", 2: "INV", 3: "RC"}.get(last_op, "-")


def why_name(why: int) -> str:
    return fd.WHY_NAMES.get(why, "-")


def capture_state_name(state: int) -> str:
    return {1: "READING", 2: "CANDIDATE_READY", 3: "CANDIDATE_NOT_SAVEABLE", 4: "SAVING"}.get(state, "IDLE")


def domain_label(slot: int) -> str:
    return {SLOT_FP: "Free Power", SLOT_DUMP: "Dump to Grid", SLOT_R244: "Register 244 test",
            SLOT_FBS: "Failback record"}.get(slot, "")


def block_name(step: int) -> str:
    return {1: "230/3", 2: "241/53", 3: "230/3", 4: "241/53"}.get(step, "?")


def w_view(fba_cls: int, wc: int, generation: int, hw_generation: int) -> int:
    """B2 `w=`: the witness as seen from the profile (S2 section 3.2, derived)."""
    authentic = fd.fba_authentic(fba_cls)
    if wc == fd.W_UNREADABLE:
        return WVIEW_UNR
    if wc == fd.W_ABSENT:
        return WVIEW_MISS if authentic else WVIEW_ABS
    if wc == fd.W_CORRUPT:
        return WVIEW_CORR
    return WVIEW_LAG if (authentic and generation > hw_generation) else WVIEW_OK


# ---------------------------------------------------------------------------
# Words, index map, pass buffers
# ---------------------------------------------------------------------------
def reg_of(k: int) -> int:
    return REGS[k] if 0 <= k < REG_COUNT else 0


def words_of(p) -> list[int]:
    """The 31 register words of a FallbackProfileV1 record (dict or 96 bytes), canonical order."""
    p = _prof(p)
    return ([p["reg244"]] + list(p["reg256_261"]) + list(p["reg268_273"]) + list(p["reg274_279"])
            + [p["reg232"], p["reg243"], p["reg248"]] + list(p["reg250_255"])
            + [p["reg230"], p["reg245"], p["reg247"]])


def profile_from_words(words) -> dict:
    """q: the profile record carrying `words` with the CONSTANT magic/schema/size and everything else zero."""
    w = list(words)
    return fp.blank_profile(
        magic=fp.PROFILE_MAGIC, schema=fp.PROFILE_SCHEMA, size=fp.PROFILE_SIZE, reg244=w[0],
        reg256_261=w[1:7], reg268_273=w[7:13], reg274_279=w[13:19], reg232=w[19], reg243=w[20], reg248=w[21],
        reg250_255=w[22:28], reg230=w[28], reg245=w[29], reg247=w[30])


def store_block_230(words: list, values) -> bool:
    if len(values) != 3:
        return False
    words[28] = values[0] & 0xFFFF
    words[19] = values[2] & 0xFFFF
    return True


def store_block_241(words: list, values) -> bool:
    if len(values) != 53:
        return False
    v = [x & 0xFFFF for x in values]
    words[0] = v[3]
    words[1:7] = v[15:21]
    words[7:13] = v[27:33]
    words[13:19] = v[33:39]
    words[20] = v[2]
    words[21] = v[7]
    words[22:28] = v[9:15]
    words[29] = v[4]
    words[30] = v[6]
    return True


def first_diff(a, b) -> int:
    for k in range(REG_COUNT):
        if a[k] != b[k]:
            return k
    return -1


# ---------------------------------------------------------------------------
# L2 capture refusals, L2w warnings
# ---------------------------------------------------------------------------
def hhmm_decodable(raw: int) -> bool:
    return raw // 100 <= 23 and raw % 100 <= 59


def on_5min_grid(raw: int) -> bool:
    return (raw % 100) % 5 == 0


def ring_valid(words) -> bool:
    minutes = []
    for i in range(6):
        t = words[22 + i]
        if not hhmm_decodable(t):
            return False
        minutes.append((t // 100) * 60 + t % 100)
    deltas = [(minutes[(i + 1) % 6] - minutes[i] + 1440) % 1440 for i in range(6)]
    return all(d > 0 for d in deltas) and sum(deltas) == 1440


@dataclass
class Refusals:
    item: list = field(default_factory=lambda: [0] * REFUSAL_MAX)
    count: int = 0


def _refusal_add(r: Refusals, kind: int, slot: int) -> None:
    if r.count < REFUSAL_MAX:
        r.item[r.count] = (kind << 8) | slot
        r.count += 1


def refusal_kind(item: int) -> int:
    return item >> 8


def refusal_slot(item: int) -> int:
    return item & 0xFF


def capture_refusals(words, ceiling_w: int) -> Refusals:
    r = Refusals()
    if not fp.reg244_domain_valid(words[0]):
        _refusal_add(r, RF_244X, 0)
    for n in range(1, 7):
        w = words[n]
        if w < fp.V1_TOU_POWER_MIN_W:
            _refusal_add(r, RF_PWRL, n)
        elif (not fp.tou_power_domain_valid(w)) or w > ceiling_w:
            _refusal_add(r, RF_PWRH, n)
    for n in range(1, 7):
        if not fp.soc_domain_valid(words[6 + n]):
            _refusal_add(r, RF_SOCH, n)
    for n in range(1, 7):
        src = words[12 + n]
        if not fp.slot_source_domain_valid(src):
            if (src & 0x0003) > 1:
                _refusal_add(r, RF_SRCG, n)
            if src & 0x001C:
                _refusal_add(r, RF_MODE, n)
            if src & 0xFFE0:
                _refusal_add(r, RF_BITS, n)
    for n in range(1, 7):
        if not hhmm_decodable(words[21 + n]):
            _refusal_add(r, RF_HHMM, n)
    if words[20] > 1:
        _refusal_add(r, RF_243X, 0)
    return r


def capture_warnings(words) -> int:
    mask = 0
    if all(words[7 + i] == 100 for i in range(6)) and all(words[13 + i] == 1 for i in range(6)) and words[19] & 1:
        mask |= 1 << 0
    powers = [words[1 + i] for i in range(6)]
    if len(set(powers)) == 1 and powers[0] <= DUMP_CONTROLLER_MAX_W:
        mask |= 1 << 1
    if (words[21] & 1) == 0:
        mask |= 1 << 2
    if (words[19] & 1) == 0 and any((words[13 + i] & 3) == 1 for i in range(6)):
        mask |= 1 << 3
    if any(hhmm_decodable(words[22 + i]) and not on_5min_grid(words[22 + i]) for i in range(6)):
        mask |= 1 << 4
    if not ring_valid(words):
        mask |= 1 << 5
    return mask


def _refusal_code(item: int) -> str:
    kind, slot = refusal_kind(item), refusal_slot(item)
    if kind == RF_244X:
        return "244X"
    if kind == RF_243X:
        return "243X"
    name = {RF_PWRL: "PWRL", RF_PWRH: "PWRH", RF_SOCH: "SOCH", RF_SRCG: "SRCG", RF_MODE: "MODE", RF_BITS: "BITS",
            RF_HHMM: "HHMM"}.get(kind)
    # RF_NONE, the text-only kinds (RF_CLASS, RF_ANOMALY) and anything unknown render NOTHING, exactly like the C++
    # put_refusal_code (none of them is ever added to a Refusals list, so none reaches sv_text in production).
    return "" if name is None else f"{name}{slot}"


def sv_text(r: Refusals) -> TextBuf:
    if r.count == 0:
        return _tb("OK")
    text = "NO:" + ",".join(_refusal_code(r.item[i]) for i in range(min(r.count, 3)))
    if r.count > 3:
        text += f"+{r.count - 3}"
    return _tb(text)


def warn_text(mask: int) -> TextBuf:
    names = [f"W{n}" for n in range(1, 7) if mask & (1 << (n - 1))]
    return _tb(",".join(names) if names else "-")


def review_eligible(r: Refusals, cls: int, read_anomaly: int) -> bool:
    return r.count == 0 and fd.save_class_permitted(cls) and read_anomaly == 0


# ---------------------------------------------------------------------------
# Candidate id
# ---------------------------------------------------------------------------
CANDIDATE_DOMAIN = b"ECCO-FALLBACK-PROFILE-CANDIDATE-v1"


def step_le(h: int, value: int, width: int) -> int:
    for i in range(width):
        h = ((h ^ ((value >> (8 * i)) & 0xFF)) * fp.FNV1A64_PRIME) & 0xFFFFFFFFFFFFFFFF
    return h


def _candidate_id_over(q: dict, salt: int, seq: int, prior_class: int, prior_generation: int,
                       prior_binding: int) -> int:
    h = fp.FNV1A64_OFFSET_BASIS
    for byte in CANDIDATE_DOMAIN:
        h = ((h ^ byte) * fp.FNV1A64_PRIME) & 0xFFFFFFFFFFFFFFFF
    h = step_le(h, salt, 4)
    h = step_le(h, seq, 4)
    h = step_le(h, prior_class, 1)
    h = step_le(h, prior_generation, 4)
    h = step_le(h, prior_binding, 8)
    raw = fp.pack_profile(q)
    for i in range(fp.PROFILE_BOUND_BYTES):
        h = ((h ^ raw[i]) * fp.FNV1A64_PRIME) & 0xFFFFFFFFFFFFFFFF
    return h


def candidate_id(salt: int, seq: int, prior_class: int, prior_generation: int, prior_binding: int, words) -> int:
    """THE locked reading: q carries the CONSTANT magic / schema / size."""
    return _candidate_id_over(profile_from_words(words), salt, seq, prior_class, prior_generation, prior_binding)


def candidate_id_alt_zero_header_reading(salt: int, seq: int, prior_class: int, prior_generation: int,
                                         prior_binding: int, words) -> int:
    """The REJECTED reading (q magic / schema / size = 0). TEST-ONLY: no firmware lambda calls it; it exists solely so
    a golden proves the two readings differ (it keeps the S1 9.3 choice of the constants reading pinned)."""
    q = profile_from_words(words)
    q["magic"] = 0
    q["schema"] = 0
    q["size"] = 0
    return _candidate_id_over(q, salt, seq, prior_class, prior_generation, prior_binding)


def id_text(candidate: int) -> TextBuf:
    return _tb(_hex(candidate, 16))


# ---------------------------------------------------------------------------
# Compare masks (candidate a vs stored b, both CaptureWords)
# ---------------------------------------------------------------------------
_CTX_ADDRS = (232, 243, 248, 250, 251, 252, 253, 254, 255)
_CTX_INDEX = (19, 20, 21, 22, 23, 24, 25, 26, 27)


def e1_delta_mask(a, b) -> int:
    """bit k = a[k] != b[k] for k = 0..18 (244; 256-261; 268-273; 274-279). FULL word, also for 274-279."""
    return sum(1 << k for k in range(19) if a[k] != b[k])


def ctx_mismatch_mask(a, b) -> int:
    """bit0 232.b0, bit1 243, bit2 248.b0, bits3-8 250-255 (FB-A ctx_matches semantics, stored b vs live a)."""
    return sum(1 << i for i in range(9) if not fp.ctx_matches(_CTX_ADDRS[i], b[_CTX_INDEX[i]], a[_CTX_INDEX[i]]))


def info_mismatch_mask(a, b) -> int:
    mask = 0
    if a[28] != b[28]:
        mask |= 1
    if a[29] != b[29]:
        mask |= 2
    if a[30] != b[30]:
        mask |= 4
    if (a[19] ^ b[19]) & 0xFFFE:
        mask |= 8
    if (a[21] ^ b[21]) & 0xFFFE:
        mask |= 16
    return mask


def out_of_domain_mask(w) -> int:
    """19-bit layout of e1_delta_mask over LIVE words: bit0 244 not in {0,2}, 1-6 power, 7-12 SOC, 13-18 source."""
    mask = 0 if fp.from_244_domain_valid(w[0]) else 1
    for i in range(6):
        if not fp.tou_power_domain_valid(w[1 + i]):
            mask |= 1 << (1 + i)
        if not fp.soc_domain_valid(w[7 + i]):
            mask |= 1 << (7 + i)
        if not fp.slot_source_domain_valid(w[13 + i]):
            mask |= 1 << (13 + i)
    return mask


# ---------------------------------------------------------------------------
# Same-boot divergence rule, fresh read evaluation
# ---------------------------------------------------------------------------
def diverged(last_load: int, new_load: int, bytes_equal: bool) -> bool:
    """The rule: a read whose load code or bytes differ from the last read of that key this boot (no commit in between)."""
    return last_load != new_load or not bytes_equal


def profile_diverged(last_load: int, last_bytes, new_load: int, new_bytes) -> bool:
    return diverged(last_load, new_load, _bytes(last_bytes) == _bytes(new_bytes))


def witness_diverged(last_load: int, last_bytes, new_load: int, new_bytes) -> bool:
    return diverged(last_load, new_load, _bytes(last_bytes) == _bytes(new_bytes))


@dataclass
class ReadInputs:
    p_load: int = fp.LOAD_STORAGE_UNAVAILABLE
    p: dict = field(default_factory=fp.blank_profile)
    w_load: int = fp.LOAD_STORAGE_UNAVAILABLE
    w: dict = field(default_factory=fd.blank_provision)
    healthy: bool = False
    present_seen: int = 0
    read_anomaly: int = 0
    seen_hw_gen: int = 0
    baseline_valid: bool = False
    last_p_load: int = fp.LOAD_STORAGE_UNAVAILABLE
    last_p_bytes: bytes = bytes(fp.PROFILE_SIZE)
    last_w_load: int = fp.LOAD_STORAGE_UNAVAILABLE
    last_w_bytes: bytes = bytes(fd.PROVISION_SIZE)


@dataclass
class ReadEval:
    latch: fd.ReadLatch = field(default_factory=fd.ReadLatch)
    p_fba_class: int = 0
    w_class: int = 0
    cls: int = 0
    why: int = 0
    rule: int = 0
    seen_hw_gen: int = 0
    p_diverged: bool = False
    w_diverged: bool = False


def evaluate_read(r: ReadInputs) -> ReadEval:
    present_seen, read_anomaly = fd.note_read(r.present_seen, r.read_anomaly, fd.KEY_BIT_PROFILE, r.p_load, r.healthy)
    present_seen, read_anomaly = fd.note_read(present_seen, read_anomaly, fd.KEY_BIT_WITNESS, r.w_load, r.healthy)
    p = _prof(r.p)
    w = _wit(r.w)
    p_div = r.baseline_valid and profile_diverged(r.last_p_load, r.last_p_bytes, r.p_load, fp.pack_profile(p))
    w_div = r.baseline_valid and witness_diverged(r.last_w_load, r.last_w_bytes, r.w_load, fd.pack_provision(w))
    if p_div:
        read_anomaly |= fd.KEY_BIT_PROFILE
    if w_div:
        read_anomaly |= fd.KEY_BIT_WITNESS
    cls, why, rule = fd.compose_profile_class(r.p_load, p, r.w_load, w, read_anomaly)
    fba = fp.classify_profile(r.p_load, p)
    wc = fd.classify_witness(r.w_load, w)
    seen = fd.next_seen_hw_gen(r.seen_hw_gen, fba, p["generation"], wc, w["hw_generation"])
    return ReadEval(fd.ReadLatch(present_seen, read_anomaly), fba, wc, cls, why, rule, seen, p_div, w_div)


# ---------------------------------------------------------------------------
# REVIEW-final evaluation
# ---------------------------------------------------------------------------
@dataclass
class PriorFingerprint:
    generation: int = 0
    binding: int = 0


def prior_fingerprint(p_load: int, p, stored_len: int) -> PriorFingerprint:
    """S2 3.1: authentic -> (g, binding); CORRUPT + LOAD_OK -> the raw fields; CORRUPT + WRONG_SIZE -> (0, stored_len);
    everything else -> (0, 0)."""
    p = _prof(p)
    c = fp.classify_profile(p_load, p)
    if fd.fba_authentic(c):
        return PriorFingerprint(p["generation"], p["binding"])
    if c == fp.PROFILE_CORRUPT and p_load == fp.LOAD_OK:
        return PriorFingerprint(p["generation"], p["binding"])
    if c == fp.PROFILE_CORRUPT and p_load == fp.LOAD_WRONG_SIZE:
        return PriorFingerprint(0, stored_len & U32)
    return PriorFingerprint(0, 0)


def writes_fingerprint(a: int, b: int, c: int, d: int, e: int) -> int:
    return ((a & U32) + (b & U32) + (c & U32) + (d & U32) + (e & U32)) & U32


def candidate_expired(now_ms: int, born_ms: int) -> bool:
    return ((now_ms - born_ms) & U32) >= CANDIDATE_TTL_MS


def exp_seconds(now_ms: int, born_ms: int) -> int:
    age = (now_ms - born_ms) & U32
    return 0 if age >= CANDIDATE_TTL_MS else (CANDIDATE_TTL_MS - age) // 1000


def review_integrity_ok(op_in_progress: bool, op_purpose: int) -> bool:
    return bool(op_in_progress) and op_purpose == PURPOSE_REVIEW


@dataclass
class ReviewInputs:
    words: list = field(default_factory=lambda: [0] * REG_COUNT)
    ceiling_w: int = fp.V1_TOU_POWER_MAX_W
    cls: int = 0
    read_anomaly: int = 0
    p_load: int = fp.LOAD_STORAGE_UNAVAILABLE
    p: dict = field(default_factory=fp.blank_profile)
    p_stored_len: int = 0
    salt: int = 0
    seq_next: int = 0


@dataclass
class ReviewVerdict:
    refusals: Refusals = field(default_factory=Refusals)
    warnings: int = 0
    eligible: bool = False
    has_stored: bool = False
    prior_generation: int = 0
    prior_binding: int = 0
    id: int = 0
    dx: int = 0
    dc: int = 0
    di: int = 0
    sv: TextBuf = field(default_factory=TextBuf)   # empty, like the C++ default; review_evaluate always overwrites it


def _stored_trusted(p_load: int, p, cls: int) -> bool:
    """The stored profile is TRUSTED (the C++ stored_trusted): the FB-A record is authentic (VALID, INVALIDATED or
    CORRUPT_DOMAIN, hence also STALE) AND the effective class is not UNREADABLE. ONE predicate for the review masks
    (has_stored: dx / dc / di) and for the saved views (_saved_view: B7 / B8), so dx=00000 / dc=000 / di=00 is never
    shown next to a B7 / B8 `v=NONE` and a B1 UNREADABLE."""
    return fd.fba_authentic(fp.classify_profile(p_load, p)) and cls != fd.EPC_UNREADABLE


def review_evaluate(r: ReviewInputs) -> ReviewVerdict:
    v = ReviewVerdict()
    v.refusals = capture_refusals(r.words, r.ceiling_w)
    v.warnings = capture_warnings(r.words)
    v.eligible = review_eligible(v.refusals, r.cls, r.read_anomaly)
    fpr = prior_fingerprint(r.p_load, r.p, r.p_stored_len)
    v.prior_generation, v.prior_binding = fpr.generation, fpr.binding
    v.has_stored = _stored_trusted(r.p_load, r.p, r.cls)
    if v.has_stored:
        stored = words_of(r.p)
        v.dx = e1_delta_mask(r.words, stored)
        v.dc = ctx_mismatch_mask(r.words, stored)
        v.di = info_mismatch_mask(r.words, stored)
    if v.eligible:
        v.id = candidate_id(r.salt, r.seq_next, r.cls, v.prior_generation, v.prior_binding, r.words)
    v.sv = sv_text(v.refusals)
    return v


# ---------------------------------------------------------------------------
# Gate inputs (the real firmware global ids are the field names)
#
# DEFAULTS ARE NOT UNIFORMLY FAIL-CLOSED (the same note as in the header): a forgotten assignment fails closed only
# for boot_loaded (False), fbs_slot (FBS_UNREADABLE), the three *_marker_boot_load (255), ProbeResults (PROBE_NONE),
# SlotClass (OBL_UNSET) and, in ReadInputs / ReviewInputs, the load codes, `healthy`, ReviewInputs.cls and
# ReviewInputs.words. Every other default is the PERMISSIVE idle value (the three write arms, every BusInputs field,
# the FP / Dump / R244 flags, marker states, containment, run_* bits, probe_latch, and ReadInputs.baseline_valid /
# present_seen / read_anomaly / seen_hw_gen, ReviewInputs.read_anomaly / salt / seq_next / ceiling_w), so the firmware
# lambdas must assign EVERY field they use (only FpDomain.expired / DumpDomain.expired are left alone on purpose).
# ---------------------------------------------------------------------------
@dataclass
class BusInputs:
    manual_write_in_progress: bool = False
    correction_in_progress: bool = False
    verification_pending: bool = False
    verification_read_active: bool = False
    free_power_operation_in_progress: bool = False
    free_power_recovery_force_in_progress: bool = False
    free_power_recovery_accept_in_progress: bool = False
    reg244_apply_in_progress: bool = False
    dump_operation_in_progress: bool = False
    fallback_profile_op_in_progress: bool = False
    fallback_profile_capture_dispatch_running: bool = False
    diag_write_lock_held: bool = False
    diag_write_lock_since_ms: int = 0
    now_ms: int = 0


@dataclass
class FpDomain:
    free_power_marker_boot_load: int = BOOT_LOAD_NOT_LOADED
    free_power_recovery_metadata_corrupt: bool = False
    free_power_snapshot_valid: bool = False
    free_power_marker_state: int = MARKER_STATE_CLEAR
    free_power_operator_needed: bool = False
    free_power_active_persisted: bool = False
    free_power_restore_requested: bool = False
    expired: bool = False
    run_start: bool = False
    run_restore: bool = False
    run_operator: bool = False


@dataclass
class DumpDomain:
    dump_marker_boot_load: int = BOOT_LOAD_NOT_LOADED
    dump_recovery_metadata_corrupt: bool = False
    dump_containment_state: int = 0
    dump_snapshot_valid: bool = False
    dump_marker_state: int = MARKER_STATE_CLEAR
    dump_operator_needed: bool = False
    dump_active_persisted: bool = False
    dump_restore_requested: bool = False
    expired: bool = False
    run_start: bool = False
    run_restore: bool = False


@dataclass
class R244Domain:
    reg244_marker_boot_load: int = BOOT_LOAD_NOT_LOADED
    reg244_recovery_metadata_corrupt: bool = False
    reg244_snapshot_valid: bool = False
    reg244_marker_state: int = MARKER_STATE_CLEAR
    run_apply: bool = False
    run_restore: bool = False


@dataclass
class GateInputs:
    boot_loaded: bool = False
    fbs_slot: int = fd.FBS_UNREADABLE
    probe_latch: int = 0
    free_power_write_enable: bool = False
    dump_write_enable: bool = False
    manual_config_write_enable: bool = False
    bus: BusInputs = field(default_factory=BusInputs)
    fp: FpDomain = field(default_factory=FpDomain)
    dump: DumpDomain = field(default_factory=DumpDomain)
    r244: R244Domain = field(default_factory=R244Domain)


@dataclass
class ProbeResults:
    fp: int = PROBE_NONE
    dump: int = PROBE_NONE
    r244: int = PROBE_NONE


@dataclass
class SlotClass:
    kind: int = OBL_UNSET
    basis: int = BASIS_NONE


# ---------------------------------------------------------------------------
# Probe and latch
# ---------------------------------------------------------------------------
def probe_result(load: int, magic: int, state: int) -> int:
    """Classify one marker read (ecco_fbdurable::read_direct_t load + the record's magic/state)."""
    if load == fp.LOAD_ABSENT:
        return PROBE_ABSENT
    if load == fp.LOAD_WRONG_SIZE:
        return PROBE_MALFORMED
    if load != fp.LOAD_OK:
        return PROBE_UNREADABLE
    if magic != MARKER_RECORD_MAGIC:
        return PROBE_MALFORMED
    if state == MARKER_STATE_CLEAR:
        return PROBE_CLEAR
    if state == MARKER_STATE_RESTORE_REQUIRED:
        return PROBE_RESTORE_REQUIRED
    if state == MARKER_STATE_PENDING_CLEAR:
        return PROBE_PENDING_CLEAR
    return PROBE_MALFORMED


def probe_latch_code(probe: int) -> int:
    """The latch code a probe result sets (0 = none: CLEAR, ABSENT, not probed)."""
    return {PROBE_UNREADABLE: LATCH_UNREADABLE, PROBE_MALFORMED: LATCH_MALFORMED,
            PROBE_RESTORE_REQUIRED: LATCH_GHOST_RR, PROBE_PENDING_CLEAR: LATCH_GHOST_PC}.get(probe, LATCH_NONE)


def latch_get(latch: int, domain: int) -> int:
    return (latch >> (4 * domain)) & 0xF if 0 <= domain <= 3 else 0


def latch_set(latch: int, domain: int, code: int) -> int:
    """SET-ONLY: an already non-zero nibble is never changed, and the code 0 never writes."""
    if not 0 <= domain <= 3 or code == 0 or latch_get(latch, domain) != 0:
        return latch & 0xFFFF
    return (latch | ((code & 0xF) << (4 * domain))) & 0xFFFF


def latch_text(latch: int) -> TextBuf:
    names = [name for dom, name in ((DOM_FP, "FP"), (DOM_DUMP, "DP"), (DOM_R244, "R4")) if latch_get(latch, dom)]
    return _tb(",".join(names) if names else "-")


# ---------------------------------------------------------------------------
# Classifiers (S1 4.4, rows evaluated top to bottom, first match wins)
# ---------------------------------------------------------------------------
def _boot_and_latch_rows(boot_loaded: bool, load: int, corrupt: bool, latch_code: int) -> SlotClass | None:
    """Rows 1-4 shared by FP, DUMP and R244. The boot truth is the pair (marker boot load, metadata-corrupt flag)."""
    if (not boot_loaded) or load > BOOT_LOAD_READ_ERROR:
        return SlotClass(UNK_BOOT_NOT_LOADED, BASIS_NONE)
    if corrupt and load == BOOT_LOAD_READ_ERROR:
        return SlotClass(UNK_DURABLE_UNREADABLE, BASIS_BOOT_READ_ERROR)
    if corrupt:
        return SlotClass(UNK_METADATA_CORRUPT, BASIS_BOOT_LOCKOUT)
    if load == BOOT_LOAD_WRONG_SIZE or load == BOOT_LOAD_READ_ERROR:
        return SlotClass(UNK_DIVERGED, BASIS_RAM_INCONSISTENT)
    if latch_code == LATCH_UNREADABLE:
        return SlotClass(UNK_DURABLE_UNREADABLE, BASIS_RUNTIME_PROBE)
    if latch_code == LATCH_MALFORMED:
        return SlotClass(UNK_METADATA_CORRUPT, BASIS_RUNTIME_PROBE)
    if latch_code == LATCH_GHOST_RR:
        return SlotClass(UNK_DIVERGED, BASIS_GHOST_RR)
    if latch_code == LATCH_GHOST_PC:
        return SlotClass(UNK_DIVERGED, BASIS_GHOST_PC)
    if latch_code != LATCH_NONE:
        return SlotClass(UNK_DIVERGED, BASIS_RAM_INCONSISTENT)
    return None


def _probe_rows(probe: int) -> SlotClass:
    """The durable-leg rows, reached only when every RAM leg is clear."""
    if probe == PROBE_NONE:
        return SlotClass(UNK_NOT_PROBED, BASIS_NONE)
    if probe == PROBE_RESTORE_REQUIRED:
        return SlotClass(UNK_DIVERGED, BASIS_GHOST_RR)
    if probe == PROBE_PENDING_CLEAR:
        return SlotClass(UNK_DIVERGED, BASIS_GHOST_PC)
    if probe == PROBE_MALFORMED:
        return SlotClass(UNK_METADATA_CORRUPT, BASIS_RUNTIME_PROBE)
    if probe == PROBE_CLEAR:
        return SlotClass(OBL_CLEAR_PROVEN, BASIS_MARKER_CLEAR)
    if probe == PROBE_ABSENT:
        return SlotClass(OBL_CLEAR_PROVEN, BASIS_ABSENT)
    return SlotClass(UNK_DURABLE_UNREADABLE, BASIS_RUNTIME_PROBE)


def classify_fp(g: GateInputs, probe: int) -> SlotClass:
    d, b = g.fp, g.bus
    early = _boot_and_latch_rows(g.boot_loaded, d.free_power_marker_boot_load, d.free_power_recovery_metadata_corrupt,
                                 latch_get(g.probe_latch, DOM_FP))
    if early is not None:
        return early
    sv, ms = d.free_power_snapshot_valid, d.free_power_marker_state
    if b.free_power_recovery_force_in_progress or b.free_power_recovery_accept_in_progress or d.run_operator:
        return SlotClass(OBL_ENDING, BASIS_OPERATOR_ACTION_RUNNING)
    if d.run_restore:
        return SlotClass(OBL_ENDING, BASIS_RESTORE_RUNNING)
    if d.run_start and not sv:
        return SlotClass(OBL_STARTING, BASIS_PRE_COMMIT)
    if d.run_start and sv:
        return SlotClass(OBL_STARTING, BASIS_COMMITTED)
    if b.free_power_operation_in_progress:
        return SlotClass(UNK_BUS_OR_LOCK_STUCK, BASIS_OP_FLAG_UNATTRIBUTED)
    if sv and ms == MARKER_STATE_PENDING_CLEAR:
        return SlotClass(OBL_PENDING_CLEAR, BASIS_NONE)
    if sv and ms == MARKER_STATE_RESTORE_REQUIRED and d.free_power_operator_needed:
        return SlotClass(OBL_OPERATOR_NEEDED, BASIS_NONE)
    if (sv and ms == MARKER_STATE_RESTORE_REQUIRED and d.free_power_active_persisted
            and not d.free_power_restore_requested and not d.expired):
        return SlotClass(OBL_ACTIVE, BASIS_LEASE)
    if sv and ms == MARKER_STATE_RESTORE_REQUIRED:
        return SlotClass(OBL_RESTORE_REQUIRED, BASIS_NONE)
    if sv:
        return SlotClass(UNK_DIVERGED, BASIS_RAM_INCONSISTENT)
    if d.free_power_active_persisted or d.free_power_restore_requested or ms != MARKER_STATE_CLEAR:
        return SlotClass(UNK_DIVERGED, BASIS_RAM_INCONSISTENT)
    return _probe_rows(probe)


def classify_dump(g: GateInputs, probe: int) -> SlotClass:
    d, b = g.dump, g.bus
    early = _boot_and_latch_rows(g.boot_loaded, d.dump_marker_boot_load, d.dump_recovery_metadata_corrupt,
                                 latch_get(g.probe_latch, DOM_DUMP))
    if early is not None:
        return early
    sv, ms = d.dump_snapshot_valid, d.dump_marker_state
    if d.dump_containment_state != 0:
        return SlotClass(UNK_DIVERGED, BASIS_RAM_INCONSISTENT)
    if d.run_restore:
        return SlotClass(OBL_ENDING, BASIS_RESTORE_RUNNING)
    if d.run_start and not sv:
        return SlotClass(OBL_STARTING, BASIS_PRE_COMMIT)
    if d.run_start and sv:
        return SlotClass(OBL_STARTING, BASIS_COMMITTED)
    if b.dump_operation_in_progress:
        return SlotClass(UNK_BUS_OR_LOCK_STUCK, BASIS_OP_FLAG_UNATTRIBUTED)
    if sv and ms == MARKER_STATE_PENDING_CLEAR:
        return SlotClass(OBL_PENDING_CLEAR, BASIS_NONE)
    if sv and ms == MARKER_STATE_RESTORE_REQUIRED and d.dump_operator_needed:
        return SlotClass(OBL_OPERATOR_NEEDED, BASIS_NONE)
    if (sv and ms == MARKER_STATE_RESTORE_REQUIRED and d.dump_active_persisted and not d.dump_restore_requested
            and not d.expired):
        return SlotClass(OBL_ACTIVE, BASIS_LEASE)
    if sv and ms == MARKER_STATE_RESTORE_REQUIRED:
        return SlotClass(OBL_RESTORE_REQUIRED, BASIS_NONE)
    if sv:
        return SlotClass(UNK_DIVERGED, BASIS_RAM_INCONSISTENT)
    if d.dump_active_persisted or d.dump_operator_needed or ms != MARKER_STATE_CLEAR:
        return SlotClass(UNK_DIVERGED, BASIS_RAM_INCONSISTENT)
    return _probe_rows(probe)


def classify_r244(g: GateInputs, probe: int) -> SlotClass:
    d, b = g.r244, g.bus
    early = _boot_and_latch_rows(g.boot_loaded, d.reg244_marker_boot_load, d.reg244_recovery_metadata_corrupt,
                                 latch_get(g.probe_latch, DOM_R244))
    if early is not None:
        return early
    sv, ms = d.reg244_snapshot_valid, d.reg244_marker_state
    if d.run_restore:
        return SlotClass(OBL_ENDING, BASIS_RESTORE_RUNNING)
    if d.run_apply and not sv:
        return SlotClass(OBL_STARTING, BASIS_PRE_COMMIT)
    if d.run_apply and sv:
        return SlotClass(OBL_STARTING, BASIS_COMMITTED)
    if b.reg244_apply_in_progress:
        return SlotClass(UNK_BUS_OR_LOCK_STUCK, BASIS_OP_FLAG_UNATTRIBUTED)
    if sv and ms == MARKER_STATE_PENDING_CLEAR:
        return SlotClass(OBL_PENDING_CLEAR, BASIS_NONE)
    if sv and ms == MARKER_STATE_RESTORE_REQUIRED:
        return SlotClass(OBL_OPERATOR_NEEDED, BASIS_NONE)
    if sv:
        return SlotClass(UNK_DIVERGED, BASIS_RAM_INCONSISTENT)
    if ms != MARKER_STATE_CLEAR:
        return SlotClass(UNK_DIVERGED, BASIS_RAM_INCONSISTENT)
    return _probe_rows(probe)


def bus_busy(b: BusInputs) -> bool:
    """FBP_TXN_BUSY."""
    return any((b.manual_write_in_progress, b.correction_in_progress, b.verification_pending,
                b.verification_read_active, b.free_power_operation_in_progress,
                b.free_power_recovery_force_in_progress, b.free_power_recovery_accept_in_progress,
                b.reg244_apply_in_progress, b.dump_operation_in_progress, b.fallback_profile_op_in_progress,
                b.fallback_profile_capture_dispatch_running))


def lock_age_ms(b: BusInputs) -> int:
    return (b.now_ms - b.diag_write_lock_since_ms) & U32


def lock_stuck(b: BusInputs) -> bool:
    """FBP_LOCK_STUCK (D11): the mutex held >= 300 s according to the read-only diagnostic."""
    return bool(b.manual_write_in_progress and b.diag_write_lock_held and lock_age_ms(b) >= LOCK_STUCK_MS)


def bus_owner_text(b: BusInputs) -> str:
    if (b.free_power_operation_in_progress or b.free_power_recovery_force_in_progress
            or b.free_power_recovery_accept_in_progress):
        return "Free Power"
    if b.reg244_apply_in_progress:
        return "Register 244 test"
    if b.dump_operation_in_progress:
        return "Dump to Grid"
    if b.fallback_profile_op_in_progress or b.fallback_profile_capture_dispatch_running:
        return "Fallback Profile"
    if b.correction_in_progress:
        return "clock correction"
    if b.verification_pending or b.verification_read_active:
        return "clock verification"
    if b.manual_write_in_progress:
        return "manual write"
    return "none"


def bus_owner_text_with_leases(b: BusInputs, fp_slot: SlotClass, dump_slot: SlotClass) -> str:
    """The owner named in the BUS refusal. The Free Power / Dump to Grid controller ticks hold the shared write lock
    through manual_write_in_progress ALONE (they never set free_power_operation_in_progress / dump_operation_in_progress),
    so bus_owner_text() would call an ACTIVE lease "manual write" while the vector says FP:AC / DP:AC. When the generic
    mutex flag is the ONLY owner flag set and the gate's own classification of a lease slot says OBL_ACTIVE, that domain
    is named (Free Power before Dump to Grid, the order of the owner chain); in every other case this is bus_owner_text().
    Wording only: the slot precedence and every refusal code are unchanged."""
    mutex_only = bool(b.manual_write_in_progress) and not any((
        b.correction_in_progress, b.verification_pending, b.verification_read_active,
        b.free_power_operation_in_progress, b.free_power_recovery_force_in_progress,
        b.free_power_recovery_accept_in_progress, b.reg244_apply_in_progress, b.dump_operation_in_progress,
        b.fallback_profile_op_in_progress, b.fallback_profile_capture_dispatch_running))
    if mutex_only and fp_slot.kind == OBL_ACTIVE:
        return "Free Power"
    if mutex_only and dump_slot.kind == OBL_ACTIVE:
        return "Dump to Grid"
    return bus_owner_text(b)


def classify_bus(g: GateInputs) -> SlotClass:
    if lock_stuck(g.bus):
        return SlotClass(UNK_BUS_OR_LOCK_STUCK, BASIS_LOCK_STUCK)
    if bus_busy(g.bus):
        return SlotClass(BUS_BUSY, BASIS_BUS_TXN)
    return SlotClass(OBL_CLEAR_PROVEN, BASIS_BUS_IDLE)


def classify_fbs(g: GateInputs) -> SlotClass:
    if not g.boot_loaded:
        return SlotClass(UNK_BOOT_NOT_LOADED, BASIS_NONE)
    slot = g.fbs_slot
    if slot == fd.FBS_CLEAR_ABSENT:
        return SlotClass(OBL_CLEAR_PROVEN, BASIS_ABSENT)
    if slot == fd.FBS_CLEAR_VALID:
        return SlotClass(OBL_CLEAR_PROVEN, BASIS_MARKER_CLEAR)
    if slot == fd.FBS_OBLIGATION:
        return SlotClass(OBL_ACTIVE, BASIS_FBS_EPISODE)
    if slot == fd.FBS_CORRUPT:
        return SlotClass(UNK_METADATA_CORRUPT, BASIS_BOOT_LOCKOUT)
    return SlotClass(UNK_DURABLE_UNREADABLE, BASIS_BOOT_READ_ERROR)


def classify_mtou(g: GateInputs) -> SlotClass:
    """MTOU_JOURNAL_NOT_IMPLEMENTED: Manual TOU has no durable state; it is clear iff the BUS slot is clear."""
    if not g.boot_loaded:
        return SlotClass(UNK_BOOT_NOT_LOADED, BASIS_NONE)
    if MTOU_JOURNAL_NOT_IMPLEMENTED and classify_bus(g).kind == OBL_CLEAR_PROVEN:
        return SlotClass(OBL_CLEAR_PROVEN, BASIS_NO_DURABLE_STATE)
    return SlotClass(UNK_NOT_PROBED, BASIS_NONE)


def obl_code(kind: int, basis: int) -> str:
    """The S5 alphabet entry for one slot (BUS uses OK / BY / LK)."""
    if kind == OBL_CLEAR_PROVEN:
        return {BASIS_MARKER_CLEAR: "CM", BASIS_ABSENT: "CA", BASIS_NO_DURABLE_STATE: "CN",
                BASIS_BUS_IDLE: "OK"}.get(basis, "UR")
    return {OBL_ACTIVE: "AC", OBL_STARTING: "ST", OBL_RESTORE_REQUIRED: "RR", OBL_PENDING_CLEAR: "PC",
            OBL_ENDING: "EN", OBL_OPERATOR_NEEDED: "ON", UNK_DURABLE_UNREADABLE: "UR", UNK_METADATA_CORRUPT: "MC",
            UNK_BOOT_NOT_LOADED: "BL", UNK_DIVERGED: "DV", UNK_BUS_OR_LOCK_STUCK: "LK", UNK_NOT_PROBED: "NP",
            BUS_BUSY: "BY"}.get(kind, "UR")


def vector_text(fp_c: SlotClass, dump_c: SlotClass, r244_c: SlotClass, mtou_c: SlotClass, fbs_c: SlotClass,
                bus_c: SlotClass) -> TextBuf:
    return _tb("FP:" + obl_code(fp_c.kind, fp_c.basis) + ",DP:" + obl_code(dump_c.kind, dump_c.basis)
               + ",R4:" + obl_code(r244_c.kind, r244_c.basis) + ",MT:" + obl_code(mtou_c.kind, mtou_c.basis)
               + ",FS:" + obl_code(fbs_c.kind, fbs_c.basis) + ",BUS:" + obl_code(bus_c.kind, bus_c.basis))


def _slot_clear(c: SlotClass) -> bool:
    return c.kind == OBL_CLEAR_PROVEN


def _slot_ram_clear(c: SlotClass) -> bool:
    return c.kind == OBL_CLEAR_PROVEN or c.kind == UNK_NOT_PROBED


# ---------------------------------------------------------------------------
# Refusal texts (REVIEW REFUSED - ...)
# ---------------------------------------------------------------------------
REFUSED_PREFIX = "REVIEW REFUSED - "
NOT_COMPLETED_PREFIX = "REVIEW NOT COMPLETED - "


def refused_in_flight_text() -> TextBuf:
    return _tb(REFUSED_PREFIX + "another Fallback Profile operation is in progress")


def refused_not_loaded_text() -> TextBuf:
    return _tb(REFUSED_PREFIX + "durable state not loaded yet (starting up)")


def refused_arms_text() -> TextBuf:
    return _tb(REFUSED_PREFIX + "a Free Power / Dump to Grid / Manual Configuration write arm is on; "
               "finish or turn it off first")


def refusal_text(slot: int, c: SlotClass, dump_containment: int, owner: str, lock_age_s: int) -> TextBuf:
    """One slot's refusal (S1 4.5). `owner` names the bus owner; `lock_age_s` is the stuck lock age in seconds."""
    d = domain_label(slot)
    kind, basis = c.kind, c.basis
    if slot == SLOT_BUS:
        if kind == UNK_BUS_OR_LOCK_STUCK:
            return _tb(REFUSED_PREFIX + f"inverter write lock held for {lock_age_s} s (possible leak); "
                       "a reboot may be required")
        return _tb(REFUSED_PREFIX + f"another inverter transaction is in progress ({owner}); try again shortly")
    if kind == UNK_BOOT_NOT_LOADED:
        return refused_not_loaded_text()
    if kind == UNK_DURABLE_UNREADABLE:
        if basis == BASIS_RUNTIME_PROBE:
            return _tb(REFUSED_PREFIX + d + " recovery marker became unreadable at runtime; review blocked until "
                       "reboot. After reboot it may read absent: verify live settings first; do not erase NVS")
        return _tb(REFUSED_PREFIX + d + " recovery state UNKNOWN since boot (marker unreadable); an obligation "
                   "cannot be ruled out; Fallback never proceeds past it")
    if kind == UNK_METADATA_CORRUPT:
        if basis == BASIS_RUNTIME_PROBE:
            return _tb(REFUSED_PREFIX + d + " recovery marker is malformed (found at runtime); review blocked "
                       "until reboot, which re-derives it as a hard lockout")
        text = (REFUSED_PREFIX + d + " recovery metadata is CORRUPT (hard lockout); Fallback never overwrites or "
                "proceeds past it; do not erase NVS")
        if slot == SLOT_DUMP and dump_containment != 0:
            text += f"; containment K={dump_containment}"
        return _tb(text)
    if kind == UNK_DIVERGED:
        if basis == BASIS_GHOST_RR or basis == BASIS_GHOST_PC:
            word = "RESTORE_REQUIRED" if basis == BASIS_GHOST_RR else "PENDING_CLEAR"
            return _tb(REFUSED_PREFIX + d + f" stored marker says {word} but memory says clear; review blocked "
                       "until reboot, which re-derives it (the domain may then restore its saved original)")
        return _tb(REFUSED_PREFIX + d + " in-memory recovery state is inconsistent; a reboot must re-derive it "
                   "before review")
    if kind == UNK_BUS_OR_LOCK_STUCK:
        return _tb(REFUSED_PREFIX + d + " in-progress flag is set with no running operation (possible leak); "
                   "a reboot re-derives it")
    if kind == OBL_ACTIVE:
        if basis == BASIS_FBS_EPISODE:
            return _tb(REFUSED_PREFIX + "a failback episode record exists; only the firmware that created it can "
                       "resolve it")
        return _tb(REFUSED_PREFIX + d + " is active; live settings are a temporary overlay - end it first")
    if kind == OBL_RESTORE_REQUIRED:
        return _tb(REFUSED_PREFIX + d + " must restore original settings first")
    if kind == OBL_PENDING_CLEAR:
        text = REFUSED_PREFIX + d + " restore verified; durable clear still pending"
        if slot == SLOT_R244:
            text += " - press Restore Original (armed)"
        return _tb(text)
    if kind == OBL_OPERATOR_NEEDED:
        return _tb(REFUSED_PREFIX + d + " needs an operator recovery action first")
    if kind == OBL_STARTING:
        return _tb(REFUSED_PREFIX + "a " + d + " start is in progress; live settings are about to become a "
                   "temporary overlay")
    if kind == OBL_ENDING:
        return _tb(REFUSED_PREFIX + "a " + d + " restore or recovery action is running; try again when it finishes")
    return _tb(REFUSED_PREFIX + d + " state does not permit a review")


# ---------------------------------------------------------------------------
# Gate
# ---------------------------------------------------------------------------
@dataclass
class GateResult:
    code: int = GATE_UNSET
    slot: int = SLOT_NONE
    probe_fp: bool = False
    probe_dump: bool = False
    probe_r244: bool = False
    latch: int = 0
    bus: SlotClass = field(default_factory=SlotClass)
    fbs: SlotClass = field(default_factory=SlotClass)
    fp: SlotClass = field(default_factory=SlotClass)
    dump: SlotClass = field(default_factory=SlotClass)
    r244: SlotClass = field(default_factory=SlotClass)
    mtou: SlotClass = field(default_factory=SlotClass)
    obl: TextBuf = field(default_factory=TextBuf)
    text: TextBuf = field(default_factory=TextBuf)


_SLOT_CODE = {SLOT_BUS: GATE_REFUSE_BUS, SLOT_FBS: GATE_REFUSE_FBS, SLOT_FP: GATE_REFUSE_FP,
              SLOT_DUMP: GATE_REFUSE_DUMP, SLOT_R244: GATE_REFUSE_R244, SLOT_MTOU: GATE_REFUSE_MTOU}


def _arms_on(g: GateInputs) -> bool:
    return bool(g.free_power_write_enable or g.dump_write_enable or g.manual_config_write_enable)


def gate_decide(g: GateInputs, pr: ProbeResults) -> GateResult:
    """V1-V7 in one pure call. The RAM legs are always evaluated; the three durable marker probes are consumed only
    when every other slot is clear. GATE_NEED_PROBE: probe the flagged markers and call again with the results."""
    r = GateResult()
    r.latch = g.probe_latch & 0xFFFF
    if g.bus.fallback_profile_op_in_progress or g.bus.fallback_profile_capture_dispatch_running:
        r.code = GATE_REFUSE_IN_FLIGHT
        r.text = refused_in_flight_text()
        return r
    r.bus = classify_bus(g)
    r.fbs = classify_fbs(g)
    r.fp = classify_fp(g, pr.fp)
    r.dump = classify_dump(g, pr.dump)
    r.r244 = classify_r244(g, pr.r244)
    r.mtou = classify_mtou(g)
    r.obl = vector_text(r.fp, r.dump, r.r244, r.mtou, r.fbs, r.bus)
    # the sticky latch only ever gains the code of a marker that was probed while its RAM legs were clear
    for dom, probe, probed in ((DOM_FP, pr.fp, classify_fp(g, PROBE_NONE)), (DOM_DUMP, pr.dump, classify_dump(g, PROBE_NONE)),
                               (DOM_R244, pr.r244, classify_r244(g, PROBE_NONE))):
        if probed.kind == UNK_NOT_PROBED:
            r.latch = latch_set(r.latch, dom, probe_latch_code(probe))
    if not g.boot_loaded:
        r.code = GATE_REFUSE_NOT_LOADED
        r.text = refused_not_loaded_text()
        return r
    if _arms_on(g):
        r.code = GATE_REFUSE_ARMS
        r.text = refused_arms_text()
        return r
    slots = (r.bus, r.fbs, r.fp, r.dump, r.r244, r.mtou)
    for slot in range(6):
        if not _slot_ram_clear(slots[slot]):
            r.code = _SLOT_CODE[slot]
            r.slot = slot
            r.text = refusal_text(slot, slots[slot], g.dump.dump_containment_state,
                                  bus_owner_text_with_leases(g.bus, r.fp, r.dump), lock_age_ms(g.bus) // 1000)
            return r
    r.probe_fp = r.fp.kind == UNK_NOT_PROBED
    r.probe_dump = r.dump.kind == UNK_NOT_PROBED
    r.probe_r244 = r.r244.kind == UNK_NOT_PROBED
    r.code = GATE_NEED_PROBE if (r.probe_fp or r.probe_dump or r.probe_r244) else GATE_ACCEPT
    return r


def lease_domain_nonclear(g: GateInputs) -> int:
    """IE7 (housekeeping tick): the first lease domain whose RAM legs are not clear, else SLOT_NONE."""
    for slot, c in ((SLOT_FP, classify_fp(g, PROBE_NONE)), (SLOT_DUMP, classify_dump(g, PROBE_NONE)),
                    (SLOT_R244, classify_r244(g, PROBE_NONE))):
        if not _slot_ram_clear(c):
            return slot
    return SLOT_NONE


def breaker_fired(op_in_progress: bool, dispatch_running: bool, now_ms: int, started_ms: int) -> bool:
    return bool(op_in_progress and not dispatch_running and ((now_ms - started_ms) & U32) > BREAKER_MS)


# ---------------------------------------------------------------------------
# B1-B8 grammars (k=v;, fixed key order, every key always present, `-` = n/a, hard cap 200)
# ---------------------------------------------------------------------------
def b2_text(p_load: int, p, w_load: int, w, why: int, last_err: int, last_us: int) -> TextBuf:
    """B2 Summary: g;id;at;ld;df;w;hw;op;why;werr;us. `why` is the why of the effective composition of the mirror
    (the class itself is published by B1); last_err / last_us are 0 in FB-B1 (both render `-`)."""
    p = _prof(p)
    w = _wit(w)
    fba = fp.classify_profile(p_load, p)
    authentic = fd.fba_authentic(fba)
    wc = fd.classify_witness(w_load, w)
    witness_ok = wc == fd.W_VALID
    df = "-"
    if p_load == fp.LOAD_OK and fba in (fp.PROFILE_CORRUPT, fp.PROFILE_CORRUPT_DOMAIN):
        df = df_name(fp.profile_defect(p))
    return _tb("g=" + (str(p["generation"]) if authentic else "-")
               + ";id=" + (_hex(p["binding"], 16) if authentic else "-")
               + ";at=" + (str(p["captured_epoch"]) if authentic else "-")
               + ";ld=" + ld_name(p_load)
               + ";df=" + df
               + ";w=" + w_name(w_view(fba, wc, p["generation"], w["hw_generation"]))
               + ";hw=" + (str(w["hw_generation"]) if witness_ok else "-")
               + ";op=" + (op_name(w["last_op"]) if witness_ok else "-")
               + ";why=" + why_name(why)
               + ";werr=" + ("-" if last_err == 0 else "E" + _hex(last_err & U32, 1))
               + ";us=" + ("-" if last_us == 0 else str(last_us & U32)))


def b3_value_fits(s, max_chars: int) -> bool:
    """True iff `s` is a usable B3 value: not None, non-empty and at most `max_chars` characters (the C++ reads at
    most max_chars + 1 bytes looking for the NUL)."""
    return s is not None and 0 < len(s) <= max_chars


def b3_text(capture_state: int, have_cand: bool, prior_cls: int, exp_s: int, warn_mask: int, obl: str, latch: int,
            sv: str) -> TextBuf:
    """B3 Review: st;prior;exp;warn;obl;latch;sv. prior / exp / warn / sv are `-` without a candidate.

    ROBUSTNESS RULE (every key is ALWAYS present, whatever the caller passes): an `obl` that is None, empty or longer
    than B3_OBL_MAX renders `-` (never evaluated), and likewise an `sv` that is None, empty or longer than B3_SV_MAX
    renders `-`; a value is never cut mid-way, so a truncated vector can never read as a real one. The producers
    (vector_text, sv_text) stay inside the bounds, so the rule only matters for a corrupted caller value. The charset
    of the two values is the caller's contract."""
    return _tb("st=" + capture_state_name(capture_state)
               + ";prior=" + (epc_name(prior_cls) if have_cand else "-")
               + ";exp=" + (str(exp_s) if have_cand else "-")
               + ";warn=" + (str(warn_text(warn_mask)) if have_cand else "-")
               + ";obl=" + (str(obl) if b3_value_fits(obl, B3_OBL_MAX) else "-")
               + ";latch=" + str(latch_text(latch))
               + ";sv=" + (str(sv) if have_cand and b3_value_fits(sv, B3_SV_MAX) else "-"))


def b4_text(saveable: bool, candidate: int) -> TextBuf:
    return id_text(candidate) if saveable else _tb("-")


def _slot_tuple(words, n: int) -> str:
    """`<HHMM %04u>/<W>/<SOC>/<SRC full word>` of slot n (1-6)."""
    return f"{words[21 + n]:04d}/{words[n]}/{words[6 + n]}/{words[12 + n]}"


def _slots_body(words) -> str:
    return f"244={words[0]};" + ";".join(f"{n}={_slot_tuple(words, n)}" for n in range(1, 7))


_NONE_SLOTS = "244=-;1=-;2=-;3=-;4=-;5=-;6=-"


def _ring_text(words) -> str:
    return "OK" if ring_valid(words) else "BAD"


def _context_body(words) -> str:
    return (f"232={_hex(words[19], 4)};243={words[20]};248={_hex(words[21], 4)};ring={_ring_text(words)};"
            f"230={words[28]};245={words[29]};247={_hex(words[30], 4)}")


_NONE_CONTEXT = "232=-;243=-;248=-;ring=-;230=-;245=-;247=-"


def b5_text(have_cand: bool, words, have_stored: bool, dx: int) -> TextBuf:
    """B5 Review Slots (candidate only): v=CAND|NONE;g=-;244;1..6;dx."""
    if not have_cand:
        return _tb("v=NONE;g=-;" + _NONE_SLOTS + ";dx=-")
    return _tb("v=CAND;g=-;" + _slots_body(words) + ";dx=" + (_hex(dx, 5) if have_stored else "-"))


def b6_text(have_cand: bool, words, have_stored: bool, dc: int, di: int) -> TextBuf:
    """B6 Review Context (candidate only): v;232;243;248;ring;230;245;247;dc;di."""
    if not have_cand:
        return _tb("v=NONE;" + _NONE_CONTEXT + ";dc=-;di=-")
    return _tb("v=CAND;" + _context_body(words) + ";dc=" + (_hex(dc, 3) if have_stored else "-")
               + ";di=" + (_hex(di, 2) if have_stored else "-"))


def _b7_saved(p: dict) -> str:
    """The SAVED form of B7 (the widest of the two saved views); may exceed TEXT_CAP (the C++ put_b7_saved)."""
    return ("v=SAVED;g=" + str(p["generation"]) + ";" + _slots_body(words_of(p)) + ";dx=-;b=" + _hex(p["binding"] >> 32, 8))


def _saved_view(p_load: int, p, cls: int) -> bool:
    """ONE predicate decides B7 AND B8 (the C++ saved_view): a trusted stored profile (_stored_trusted: authentic - VALID,
    INVALIDATED, CORRUPT_DOMAIN, hence also STALE - and an effective class that is not UNREADABLE) and a B7 SAVED text
    that fits TEXT_CAP. Over 200 characters (an authentic CORRUPT_DOMAIN record with every value 5 digits wide) NEITHER
    view claims a saved profile."""
    if not _stored_trusted(p_load, p, cls):
        return False
    return len(_b7_saved(p)) <= TEXT_CAP


def b7_text(p_load: int, p, cls: int) -> TextBuf:
    """B7 Slots (saved profile only): v=SAVED|NONE;g;244;1..6;dx=-;b. The NONE form whenever the saved view is false."""
    p = _prof(p)
    if _saved_view(p_load, p, cls):
        return TextBuf(_b7_saved(p))
    return _tb("v=NONE;g=-;" + _NONE_SLOTS + ";dx=-;b=-")


def b8_text(p_load: int, p, cls: int) -> TextBuf:
    """B8 Context (saved profile only): v;232;243;248;ring;230;245;247;dc=-;di=-;b. Same predicate as B7."""
    p = _prof(p)
    if _saved_view(p_load, p, cls):
        return _tb("v=SAVED;" + _context_body(words_of(p)) + ";dc=-;di=-;b=" + _hex(p["binding"] >> 32, 8))
    return _tb("v=NONE;" + _NONE_CONTEXT + ";dc=-;di=-;b=-")


# ---------------------------------------------------------------------------
# B9 Last Action-Result texts (`<OUTCOME> - detail`, <= 200, no card-regex hazard word)
# ---------------------------------------------------------------------------
def b9_seed_text() -> TextBuf:
    return _tb("No Fallback Profile action since boot")


def review_in_progress_text() -> TextBuf:
    return _tb("review in progress (read-only)")


def candidate_ready_text() -> TextBuf:
    return _tb("CANDIDATE READY - both read passes agree on all 31 registers; check the values, then arm and save within "
               "120 s")


def review_expired_text() -> TextBuf:
    return _tb("REVIEW EXPIRED - candidate expired (120 s); review again")


def review_cleared_domain_text(slot: int) -> TextBuf:
    return _tb("REVIEW CLEARED - a temporary operation started (" + domain_label(slot) + ")")


def review_cleared_writes_text() -> TextBuf:
    return _tb("REVIEW CLEARED - another ECCO write started since Review")


def breaker_text(lock_held: bool) -> TextBuf:
    return _tb("INTERNAL - Fallback Profile operation state reset by watchdog; "
               + ("write lock still held - reboot required" if lock_held else "write lock free"))


def internal_context_text() -> TextBuf:
    return _tb("INTERNAL - Fallback Profile dispatch context invalid; nothing written")


def invalidate_reason_publishes(reason: str) -> bool:
    """The invalidation script publishes B9 only for a non-empty reason that is not the `superseded` one."""
    return len(reason) > 0 and not reason.startswith(REASON_SUPERSEDED)


def read_fail_text(code: int, step: int, exception_code: int) -> TextBuf:
    blk = block_name(step)
    if code == READ_NO_RESPONSE:
        detail = f"no response reading registers {blk}"
    elif code == READ_EXCEPTION:
        detail = ("inverter returned exception code 0x" + _hex(exception_code & 0xFF, 2) + f" on registers {blk}"
                  if exception_code != 0 else f"inverter returned an exception on registers {blk}")
    elif code == READ_NOT_SENT:
        detail = f"read of registers {blk} could not be queued"
    elif code == READ_NONSTANDARD:
        detail = f"non-standard reply reading registers {blk}"
    elif code == READ_SHORT:
        detail = f"short reply reading registers {blk}"
    elif code == READ_BOUNDED_WAIT:
        detail = f"read of registers {blk} did not complete within 3 s"
    elif code == READ_IDLE_TIMEOUT:
        detail = "inverter bus stayed busy for 7 s; press Review again"
    else:
        detail = "read did not complete (unknown cause)"
    return _tb(NOT_COMPLETED_PREFIX + detail)


def pass_mismatch_text(a, b) -> TextBuf:
    k = first_diff(a, b)
    va, vb = (a[k], b[k]) if k >= 0 else (0, 0)
    return _tb(NOT_COMPLETED_PREFIX + f"live configuration changed during the read (register {reg_of(k)}: "
               f"{va} then {vb}); another controller may be editing - review again")


def _reason_text(item: int, words) -> str:
    kind, n = refusal_kind(item), refusal_slot(item)
    if kind == RF_244X:
        v = words[0]
        if v == 0:
            return "244=0 Allow Export - V1 can only save a Zero Export profile"
        if v == 1:
            return "244=1 Essentials - unsupported in V1"
        return f"244={v} unrecognised"
    if kind == RF_PWRL:
        return f"slot {n} power {words[n]} W < 500 W (V1 minimum)"
    if kind == RF_PWRH:
        if words[n] > fp.V1_TOU_POWER_MAX_W:
            return f"slot {n} power {words[n]} W > 8000 W"
        return f"slot {n} power {words[n]} W is above this site's configured ceiling"
    if kind == RF_SOCH:
        return f"slot {n} SOC {words[6 + n]} % > 100"
    if kind == RF_SRCG:
        return f"slot {n} source Generator / Grid+Generator unsupported in V1"
    if kind == RF_MODE:
        return f"slot {n} mode General/Backup/Charge unsupported in V1"
    if kind == RF_BITS:
        return f"slot {n} undecoded bits 0x{_hex(words[12 + n] & 0xFFE0, 4)} set"
    if kind == RF_HHMM:
        return f"slot {n} start {words[21 + n]} is not a valid HHMM time"
    if kind == RF_243X:
        return f"243={words[20]} is not a recognised energy-management mode (0 or 1)"
    if kind == RF_CLASS:
        if n == fd.EPC_UNREADABLE:
            return "stored profile UNREADABLE; reboot to re-derive it"
        if n == fd.EPC_SAVE_UNCONFIRMED:
            return "previous save outcome unknown; reboot to re-verify"
        return "stored profile state does not permit saving"
    return "stored profile read anomaly this boot; reboot to re-derive it"


def not_saveable_text(r: Refusals, words, cls: int, read_anomaly: int) -> TextBuf:
    """CANDIDATE NOT SAVEABLE - <first 2 reasons>[; +N more]. Reasons: the L2 refusals in code order, then the class."""
    items = [r.item[i] for i in range(r.count)]
    if not fd.save_class_permitted(cls):
        items.append((RF_CLASS << 8) | (cls & 0xFF))
    elif read_anomaly != 0:
        items.append(RF_ANOMALY << 8)
    if not items:
        return _tb("CANDIDATE NOT SAVEABLE - reason unavailable")
    text = "CANDIDATE NOT SAVEABLE - " + "; ".join(_reason_text(i, words) for i in items[:2])
    if len(items) > 2:
        text += f"; +{len(items) - 2} more"
    return _tb(text)


# ---------------------------------------------------------------------------
# FB-B3: Live Match (B10), the live-cache trust rule and the write fence
# ---------------------------------------------------------------------------
# Independent mirror of the C++ section of the same name. Written from the locked grammar and precedence (FINAL 3.8,
# S5 3.8 + Part A H2 / H3 / A.3 item 10, S3 11.5, S4 4.2 / 7.6), as an ordered rule list, not by translating the C++.
LIVE_FENCE_OFFSET = 2
LIVE_CACHE_MAX_AGE_MS = 180000

(LM_UNKNOWN, LM_NO_PROFILE, LM_PAUSED, LM_PAUSED_IO, LM_OUT_OF_DOMAIN, LM_EXPORT, LM_CONTEXT, LM_DRIFT,
 LM_MATCH) = range(9)
_LM_NAMES = ("UNKNOWN", "NO_PROFILE", "PAUSED", "PAUSED_IO", "OUT_OF_DOMAIN", "EXPORT", "CONTEXT", "DRIFT", "MATCH")

(CQ_BOOT, CQ_INVALID, CQ_POLL_OFF, CQ_STALE, CQ_PRE_FENCE, CQ_NOT_FILLED, CQ_FRESH) = range(7)
_CQ_LETTERS = "BIOSPMF"

EH_UNKNOWN, EH_NO, EH_YES = 0, 1, 2
ELIG_UNK, ELIG_OVL, ELIG_NO, ELIG_OK = 0, 1, 2, 3

FENCE_SEEDED = 1
FENCE_PREV_LEASE = 2


def lm_name(m: int) -> str:
    return _LM_NAMES[m] if 1 <= m < len(_LM_NAMES) else "UNKNOWN"


def cq_char(q: int) -> str:
    return _CQ_LETTERS[q] if 0 <= q < len(_CQ_LETTERS) else "B"


def eh_char(e: int) -> str:
    return {EH_NO: "0", EH_YES: "1"}.get(e, "U")


def elig_name(e: int) -> str:
    return {ELIG_OVL: "OVL", ELIG_NO: "NO", ELIG_OK: "OK"}.get(e, "UNK")


@dataclass
class FenceState:
    seq: int = 0
    edge_seq: int = 0
    writes_fp: int = 0
    flags: int = 0


@dataclass
class FenceSample:
    bus_hot: bool = True
    lease_nonclear: bool = True
    writes_fp: int = 0
    dispatch_seq: int = 0


def seq_max(a: int, b: int) -> int:
    return a if a > b else b


def fence_target(dispatch_seq: int) -> int:
    return (dispatch_seq + LIVE_FENCE_OFFSET) & U32


def fence_tick(s: FenceState, t: FenceSample) -> FenceState:
    seeded = bool(s.flags & FENCE_SEEDED)
    was_in_lease = bool(s.flags & FENCE_PREV_LEASE)
    edge = seeded and was_in_lease and not t.lease_nonclear
    reasons = (not seeded, t.bus_hot, t.lease_nonclear, edge, t.writes_fp != s.writes_fp)
    target = fence_target(t.dispatch_seq)
    seq = max(s.seq, target) if any(reasons) else s.seq
    edge_seq = max(s.edge_seq, target) if (t.lease_nonclear or edge) else s.edge_seq
    flags = FENCE_SEEDED | (FENCE_PREV_LEASE if t.lease_nonclear else 0)
    return FenceState(seq=seq, edge_seq=edge_seq, writes_fp=t.writes_fp, flags=flags)


def fence_passed(response_dispatch_seq: int, fence_seq: int) -> bool:
    return response_dispatch_seq >= fence_seq


@dataclass
class LiveCache:
    cache_valid: bool = False
    online: bool = False
    polling: bool = False
    filled: bool = False
    block_b_seq: int = 0
    block_b_ok_ms: int = 0
    now_ms: int = 0
    response_dispatch_seq: int = 0
    fence_seq: int = 0xFFFFFFFF


def live_trust(c: LiveCache, boot_loaded: bool) -> int:
    """First failing term of S3 11.5 in S3's order; B (boot not loaded) is the B10-only first term."""
    terms = (
        (not boot_loaded, CQ_BOOT),
        (not (c.cache_valid and c.online and c.block_b_seq != 0), CQ_INVALID),
        (not c.polling, CQ_POLL_OFF),
        (((c.now_ms - c.block_b_ok_ms) & U32) > LIVE_CACHE_MAX_AGE_MS, CQ_STALE),
        (not fence_passed(c.response_dispatch_seq, c.fence_seq), CQ_PRE_FENCE),
        (not c.filled, CQ_NOT_FILLED),
    )
    for failing, code in terms:
        if failing:
            return code
    return CQ_FRESH


def export_hazard(live_trusted: bool, live244: int, bad_domain: bool, dump_original_allows_export: bool) -> int:
    if not live_trusted:
        return EH_UNKNOWN
    if live244 != 0 or not bad_domain or dump_original_allows_export:
        return EH_NO
    return EH_YES


@dataclass
class LiveMatchInputs:
    g: GateInputs = field(default_factory=GateInputs)
    mtou_running: bool = True
    cls: int = fd.EPC_UNREADABLE
    write_outcome_unknown: bool = True
    read_anomaly: int = 1
    p_load: int = fp.LOAD_STORAGE_UNAVAILABLE
    p: object = None
    cache: LiveCache = field(default_factory=LiveCache)
    edge_fence_seq: int = 0xFFFFFFFF
    live: list = field(default_factory=lambda: [0] * REG_COUNT)
    dump_data_loaded: bool = False
    dump_snapshot_reg244: int = 0xFFFF
    dump_snapshot_reg256_261: list = field(default_factory=lambda: [0] * 6)
    ceiling_w: int = 8000


@dataclass
class LiveMatchResult:
    m: int = LM_UNKNOWN
    ca: int = CQ_BOOT
    compared: bool = False
    dx: int = 0
    cx: int = 0
    ox: int = 0
    ix: int = 0
    eh: int = EH_UNKNOWN
    obl_valid: bool = False
    fp: SlotClass = field(default_factory=SlotClass)
    dump: SlotClass = field(default_factory=SlotClass)
    r244: SlotClass = field(default_factory=SlotClass)
    bus: SlotClass = field(default_factory=SlotClass)
    elig: int = ELIG_UNK
    ew: Refusals = field(default_factory=Refusals)


def live_effective_class(cls: int, write_outcome_unknown: bool, read_anomaly: int) -> int:
    if write_outcome_unknown:
        return fd.EPC_SAVE_UNCONFIRMED
    if read_anomaly != 0:
        return fd.EPC_UNREADABLE
    return cls


def lease_slot_hazard(c: SlotClass) -> bool:
    return (not _slot_ram_clear(c)) and c.kind not in (OBL_ACTIVE, OBL_STARTING)


def live_match(i: LiveMatchInputs) -> LiveMatchResult:
    g = i.g
    r = LiveMatchResult()
    r.ca = live_trust(i.cache, g.boot_loaded)
    trusted = r.ca == CQ_FRESH
    r.obl_valid = bool(g.boot_loaded)
    r.fp, r.dump, r.r244 = classify_fp(g, PROBE_NONE), classify_dump(g, PROBE_NONE), classify_r244(g, PROBE_NONE)
    r.bus = classify_bus(g)
    leases = (r.fp, r.dump, r.r244)
    lease_nonclear = any(not _slot_ram_clear(c) for c in leases)
    lease_paused = lease_nonclear or not fence_passed(i.cache.response_dispatch_seq, i.edge_fence_seq)
    bus_not_idle = r.bus.kind != OBL_CLEAR_PROVEN or bool(i.mtou_running)

    prof = _prof(i.p) if i.p is not None else None
    stored = words_of(prof) if prof is not None else [0] * REG_COUNT
    eff = live_effective_class(i.cls, i.write_outcome_unknown, i.read_anomaly)
    has_profile = (prof is not None and eff == fd.EPC_VALID
                   and fp.classify_profile(i.p_load, prof) == fp.PROFILE_VALID)
    live = list(i.live)
    dx, cx, ox, ix = (e1_delta_mask(live, stored), ctx_mismatch_mask(live, stored), out_of_domain_mask(live),
                      info_mismatch_mask(live, stored))

    snap = list(i.dump_snapshot_reg256_261)
    exempt = bool(i.dump_data_loaded and i.dump_snapshot_reg244 == 0 and live[1:7] == snap)
    r.eh = export_hazard(trusted, live[0], any(lease_slot_hazard(c) for c in leases), exempt)

    if not g.boot_loaded or r.ca == CQ_BOOT:
        r.elig = ELIG_UNK
    elif lease_paused:
        r.elig = ELIG_OVL
    elif bus_not_idle or not trusted:
        r.elig = ELIG_UNK
    else:
        r.ew = capture_refusals(live, i.ceiling_w)
        r.elig = ELIG_OK if r.ew.count == 0 else ELIG_NO

    if not has_profile:
        r.m = LM_NO_PROFILE
    elif not g.boot_loaded:
        r.m = LM_UNKNOWN
    elif lease_paused:
        r.m = LM_PAUSED
    elif bus_not_idle:
        r.m = LM_PAUSED_IO
    elif not trusted:
        r.m = LM_UNKNOWN
    else:
        r.compared, r.dx, r.cx, r.ox, r.ix = True, dx, cx, ox, ix
        rules = ((ox != 0, LM_OUT_OF_DOMAIN), ((dx & 1) != 0 and live[0] == 0, LM_EXPORT), (cx != 0, LM_CONTEXT),
                 (dx != 0, LM_DRIFT))
        r.m = next((m for hit, m in rules if hit), LM_MATCH)
    return r


def b10_lease_code(c: SlotClass) -> str:
    return "CR" if _slot_ram_clear(c) else obl_code(c.kind, c.basis)


def b10_text(r: LiveMatchResult) -> TextBuf:
    def masks(width_hex: int, value: int) -> str:
        return _hex(value, width_hex) if r.compared else "-"

    obl = ("FP:" + b10_lease_code(r.fp) + ",DP:" + b10_lease_code(r.dump) + ",R4:" + b10_lease_code(r.r244)
           + ",BUS:" + obl_code(r.bus.kind, r.bus.basis)) if r.obl_valid else "-"
    ew = "-"
    if r.elig == ELIG_NO and r.ew.count != 0:
        ew = ",".join(_refusal_code(r.ew.item[k]) for k in range(min(r.ew.count, 3)))
        if r.ew.count > 3:
            ew += "+" + str(r.ew.count - 3)
    return _tb("m=" + lm_name(r.m) + ";dx=" + masks(5, r.dx) + ";cx=" + masks(3, r.cx) + ";ox=" + masks(5, r.ox)
               + ";ix=" + masks(2, r.ix) + ";eh=" + eh_char(r.eh) + ";obl=" + obl + ";ca=" + cq_char(r.ca)
               + ";elig=" + elig_name(r.elig) + ";ew=" + ew)


def b10_seed_text() -> TextBuf:
    return b10_text(LiveMatchResult())
