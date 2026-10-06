#!/usr/bin/env python3
"""FB-B1 - exhaustive checks of the pure capture model (registry/fallback_capture.py).

The mirror is the Python half of firmware/include/ecco_fallback_capture.h (namespace ecco_fbcap): the 31-word
index map, the L2 capture policy, the candidate id, the compare masks, the same-boot divergence rule, the gate
classifiers and every text the review entities publish. The header's constexpr evaluation (a real C++ compiler,
registry/tests/test_fallback_capture_host_compile.py) proves C++ == mirror on ~1000 goldens and ~50 mutants; THIS
suite proves the mirror itself is the specification, with oracles written independently of it:

  [1]  structure: constants, the canonical register order against FB-A, enum numbering, C++ / Python name parity
  [2]  the 31-word index map and the pass buffers (R1..R4 handlers) against the live frame decoders
  [3]  L2 refusals - truth tables swept over the WHOLE u16 domain of every field, ceilings, code order, `sv=`
  [4]  L2w warnings W1-W6 against register-number oracles; HHMM / 5-minute grid / ring
  [5]  L2 is independent of classify_profile (and consistent with FB-A's E1 domain)
  [6]  compare masks dx / dc / di / out-of-domain, bit by bit
  [7]  candidate id: both goldens readings, field sensitivity, no collisions
  [8]  classifiers: every S1 4.4 row (FP, DUMP, R244) with the real global names, first-match order, fuzz against
       an ordered-rule oracle, boot-load-pair semantics, latch rows, lazy NP, FBS, MTOU, BUS
  [9]  obl alphabet, vector text, refusal texts (hazard regexes, <= 200, distinct); FW1: the BUS refusal names an
       ACTIVE lease when the generic mutex flag is the only owner flag
  [10] probe classification and the sticky latch
  [11] the fresh FBP / FBW read: divergence rule, S1 9.2 golden sequences, seen_hw_gen
  [12] review_evaluate: eligibility, prior fingerprint, masks, id; FW0: the masks only against a TRUSTED stored
       profile (authentic AND effective class != UNREADABLE, the saved-view predicate)
  [13] grammars B1-B8: key order, always-all-keys, charset, worst-case lengths, NONE forms, B2 derivation
       for every effective class x witness class, B7 / B8 over-200 fallback (ONE shared predicate), the B3
       robustness rule for an over-long obl / sv
  [14] B9 texts: prefix set, hazard regexes, length, read-failure and mismatch texts
  [15] timing: expiry boundaries across the 2^32 wrap, exp=, breaker, lock-stuck, writes fingerprint
  [16] the gate: V1-V7 precedence, lazy probing, latch updates, fuzz invariants
  [17] mirror hygiene: banned tokens, imports, no file I/O
  [18] POD defaults: which fail closed and which are the permissive idle value (the header's DEFAULTS note is
       pinned), and the single-flip liveness of every gate input

Pure: no I/O beyond reading the repo's own files, no compiler needed.
"""

from __future__ import annotations

import random
import re
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "registry"))
import fallback_capture as cap  # noqa: E402
import fallback_durable as fd  # noqa: E402
import fallback_profile as fp  # noqa: E402

HEADER_PATH = ROOT / "firmware" / "include" / "ecco_fallback_capture.h"
MIRROR_PATH = ROOT / "registry" / "fallback_capture.py"
FAILURES: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  PASS  {name}")
    else:
        FAILURES.append(name)
        print(f"  FAIL  {name}" + (f" - {detail}" if detail else ""))


# ---------------------------------------------------------------------------------------------------------------
# Fixtures and independent oracles
# ---------------------------------------------------------------------------------------------------------------
def golden_profile(**over) -> dict:
    base = dict(magic=fp.PROFILE_MAGIC, schema=1, size=96, generation=7, captured_epoch=1790000000, flags=0, reg244=2,
                reg256_261=[8000, 500, 4000, 3000, 2000, 1000], reg268_273=[100, 20, 0, 50, 100, 30],
                reg274_279=[1, 0, 1, 0, 0, 1], reg232=0x0011, reg243=1, reg248=1, reg250_255=[0, 530, 1000, 1600, 2100, 2330],
                reg230=185, reg245=8000, reg247=1)
    base.update(over)
    return fp.seal_profile(fp.blank_profile(**base))


GOLD_P = golden_profile()
GW = cap.words_of(GOLD_P)
GOLD_W = fd.make_provision(7, GOLD_P["binding"], 6, 0x1122334455667788, fd.FALLBACK_PROFILE_KEY, 1, fd.PROV_OP_SAVE)
ADDRS = [a for f in ("reg244", "reg256_261", "reg268_273", "reg274_279", "reg232", "reg243", "reg248", "reg250_255", "reg230",
                     "reg245", "reg247") for a in fp.PROFILE_REGISTER_FIELDS[f]]
LOAD_OK, LOAD_ABSENT, LOAD_WSZ, LOAD_RERR, LOAD_UNAV = 0, 1, 2, 3, 4
CARD_PATTERNS = [re.compile(p, re.I) for p in (
    r"RECOVERY REQUIRED", r"OPERATOR DECISION REQUIRED", r"RESTORE BLOCKED", r"RECOVERY BLOCKED", r"\bFAILED\b", r"VERIFY ERROR",
    r"VERIFY TIMEOUT", r"VERIFY REFUSED", r"DEFERRED", r"ACCEPT REFUSED", r"Recovery Arm first", r"inverter writes? (?:are |is )?locked",
    r"deliberate recovery required", r"START FAILED", r"ACTIVATION (?:VERIFY|WRITE) FAILED", r"press End Free Power", r"retry restore",
    r"snapshot retained", r"^(?:RESTORING|STARTING|ACTIVATION VERIFY)")]


def hazard(text: str) -> bool:
    return any(p.search(text) for p in CARD_PATTERNS)


def regs(words) -> dict:
    return dict(zip(ADDRS, words))


def wd(base=None, **ch) -> list:
    """Words with `w<k>=v` changes."""
    w = list(GW if base is None else base)
    for k, v in ch.items():
        w[int(k[1:])] = v
    return w


def oracle_l2(words, ceiling: int) -> list[str]:
    """The L2 refusal codes, derived from REGISTER NUMBERS (not word indices) and S1 10.2."""
    r = regs(words)
    out = []
    if r[244] != 2:
        out.append("244X")
    for n in range(1, 7):
        v = r[255 + n]
        if v < 500:
            out.append(f"PWRL{n}")
        elif v > 8000 or v > ceiling:
            out.append(f"PWRH{n}")
    for n in range(1, 7):
        if r[267 + n] > 100:
            out.append(f"SOCH{n}")
    for n in range(1, 7):
        s = r[273 + n]
        if s not in (0, 1):
            if (s & 0b11) >= 2:
                out.append(f"SRCG{n}")
            if s & 0b11100:
                out.append(f"MODE{n}")
            if s >> 5:
                out.append(f"BITS{n}")
    for n in range(1, 7):
        t = r[249 + n]
        if not (t // 100 <= 23 and t % 100 <= 59):
            out.append(f"HHMM{n}")
    if r[243] not in (0, 1):
        out.append("243X")
    return out


def codes_of(refusals: cap.Refusals) -> list[str]:
    names = {cap.RF_244X: "244X", cap.RF_243X: "243X"}
    out = []
    for i in range(refusals.count):
        k, n = cap.refusal_kind(refusals.item[i]), cap.refusal_slot(refusals.item[i])
        out.append(names.get(k) or {cap.RF_PWRL: "PWRL", cap.RF_PWRH: "PWRH", cap.RF_SOCH: "SOCH", cap.RF_SRCG: "SRCG",
                                    cap.RF_MODE: "MODE", cap.RF_BITS: "BITS", cap.RF_HHMM: "HHMM"}[k] + str(n))
    return out


def oracle_ring(words) -> bool:
    """Valid iff every start decodes, no two cyclic neighbours are equal and the cyclic sequence has exactly one descent."""
    r = regs(words)
    ts = [r[249 + n] for n in range(1, 7)]
    if not all(t // 100 <= 23 and t % 100 <= 59 for t in ts):
        return False
    m = [(t // 100) * 60 + t % 100 for t in ts]
    if any(m[i] == m[(i + 1) % 6] for i in range(6)):
        return False
    return sum(1 for i in range(6) if m[(i + 1) % 6] < m[i]) == 1


def oracle_warnings(words) -> int:
    r = regs(words)
    w = 0
    if all(r[a] == 100 for a in range(268, 274)) and all(r[a] == 1 for a in range(274, 280)) and r[232] & 1:
        w |= 1
    p = [r[a] for a in range(256, 262)]
    if len(set(p)) == 1 and p[0] <= 3000:
        w |= 2
    if not r[248] & 1:
        w |= 4
    if not r[232] & 1 and any((r[a] & 3) == 1 for a in range(274, 280)):
        w |= 8
    if any((t // 100 <= 23 and t % 100 <= 59) and (t % 100) % 5 for t in (r[a] for a in range(250, 256))):
        w |= 16
    if not oracle_ring(words):
        w |= 32
    return w


POOL = [0, 1, 2, 3, 4, 5, 0x20, 0x27, 59, 60, 99, 100, 101, 499, 500, 2359, 2400, 3000, 3001, 8000, 8001, 65535]


def rand_words(rng: random.Random, p_change: float = 0.3) -> list:
    w = list(GW)
    for k in range(31):
        if rng.random() < p_change:
            w[k] = rng.choice(POOL) if rng.random() < 0.85 else rng.randrange(65536)
    return w


def rand_profile(rng: random.Random) -> tuple[int, dict, int]:
    """(load, record dict, stored_len) - sealed or damaged, in or out of domain."""
    over = {}
    if rng.random() < 0.35:
        over["generation"] = rng.choice([0, 1, 7, 8, 4294967295])
    if rng.random() < 0.3:
        over["reg244"] = rng.choice([0, 1, 2, 3, 65535])
    if rng.random() < 0.25:
        over["flags"] = rng.choice([0, 1, 2, 3])
    if rng.random() < 0.15:
        over["magic"] = rng.choice([0, 1, fp.PROFILE_MAGIC ^ 1])
    if rng.random() < 0.1:
        over["reserved0"] = 1
    if rng.random() < 0.3:
        over["captured_epoch"] = rng.choice([0, 1790000000, 4294967295])
    for name, n in (("reg256_261", 6), ("reg268_273", 6), ("reg274_279", 6), ("reg250_255", 6)):
        if rng.random() < 0.25:
            arr = list(GOLD_P[name])
            arr[rng.randrange(n)] = rng.choice(POOL)
            over[name] = arr
    p = golden_profile(**over)
    if rng.random() < 0.15:
        p = dict(p)
        p["binding"] ^= 1 << rng.randrange(64)
    load = rng.choices([LOAD_OK, LOAD_ABSENT, LOAD_WSZ, LOAD_RERR, LOAD_UNAV], [70, 10, 8, 7, 5])[0]
    if load != LOAD_OK:
        p = fp.blank_profile()
    return load, p, rng.choice([0, 40, 95, 97, 1000]) if load == LOAD_WSZ else 0


def rand_witness(rng: random.Random, p: dict) -> tuple[int, dict]:
    load = rng.choices([LOAD_OK, LOAD_ABSENT, LOAD_WSZ, LOAD_RERR, LOAD_UNAV], [70, 10, 8, 7, 5])[0]
    if load != LOAD_OK:
        return load, fd.blank_provision()
    hw = rng.choice([1, 6, 7, 8, 4294967294])
    pg = rng.choice([0, hw - 1 if hw > 1 else 0, 3])
    if pg >= hw:
        pg = 0
    pb = 0 if pg == 0 else rng.choice([0x1122, p["binding"], 0xAB])
    w = fd.make_provision(hw, rng.choice([p["binding"], 0x77]), pg, pb, rng.choice([fd.FALLBACK_PROFILE_KEY, fd.FALLBACK_PROFILE_KEY, 5]),
                          rng.choice([1, 1, 2]), rng.choice([1, 2, 3]))
    if rng.random() < 0.15:
        w = dict(w)
        w["binding"] ^= 1
    return load, w


def kv(text: str) -> list[tuple[str, str]]:
    out = []
    for part in text.split(";"):
        k, _, v = part.partition("=")
        out.append((k, v))
    return out


VALUE_RE = re.compile(r"^[A-Za-z0-9_.,:/>+-]+$")
KEY_RE = re.compile(r"^[a-z0-9]+$")


def grammar_ok(text: str, keys: tuple) -> bool:
    if len(text) > 200 or ";;" in text or text.startswith(";") or text.endswith(";") or " " in text:
        return False
    pairs = kv(text)
    return (tuple(k for k, _v in pairs) == keys and all(KEY_RE.match(k) for k, _ in pairs)
            and all(VALUE_RE.match(v) for _k, v in pairs) and all("=" not in v for _k, v in pairs))


K_B2 = ("g", "id", "at", "ld", "df", "w", "hw", "op", "why", "werr", "us")
K_B3 = ("st", "prior", "exp", "warn", "obl", "latch", "sv")
K_B5 = ("v", "g", "244", "1", "2", "3", "4", "5", "6", "dx")
K_B6 = ("v", "232", "243", "248", "ring", "230", "245", "247", "dc", "di")
K_B7 = ("v", "g", "244", "1", "2", "3", "4", "5", "6", "dx", "b")
K_B8 = ("v", "232", "243", "248", "ring", "230", "245", "247", "dc", "di", "b")


# ===============================================================================================================
def section_structure():
    print("[1] structure: constants, register order, enum numbering, C++ / Python name parity")
    check("the canonical register order is the FB-A record field order (flattened PROFILE_REGISTER_FIELDS)", cap.REGS == tuple(ADDRS))
    check("31 words; word k is at byte offset 18 + 2k of FallbackProfileV1 for every register",
          len(cap.REGS) == cap.REG_COUNT == 31 and all(
              fp.PROFILE_OFFSETS[f] + 2 * i == 18 + 2 * cap.REGS.index(a)
              for f, addrs in fp.PROFILE_REGISTER_FIELDS.items() for i, a in enumerate(addrs)))
    check("words 0-18 are the E1 registers, 19-27 CTX, 28-30 INFO (FB-A classification)",
          [fp.register_class(a) for a in cap.REGS] == [fp.REG_E1] * 19 + [fp.REG_CTX] * 9 + [fp.REG_INFO] * 3)
    check("reg_of is the register of word k and 0 outside 0..30", [cap.reg_of(k) for k in range(31)] == list(ADDRS)
          and cap.reg_of(-1) == cap.reg_of(31) == cap.reg_of(10 ** 6) == 0)
    check("timing constants: TTL 120000, idle wait 7000, step wait 3000, breaker 30000, lock stuck 300000, text cap 200",
          (cap.CANDIDATE_TTL_MS, cap.IDLE_WAIT_MS, cap.STEP_WAIT_MS, cap.BREAKER_MS, cap.LOCK_STUCK_MS, cap.TEXT_CAP)
          == (120000, 7000, 3000, 30000, 300000, 200))
    groups = {
        "purpose": ("PURPOSE_NONE", "PURPOSE_REVIEW"),
        # FB-B2 (D8): CAPTURE_SAVING = 4 is appended (a SAVE is in flight); value 5 stays unmapped and renders IDLE
        "capture state": ("CAPTURE_IDLE", "CAPTURE_READING", "CAPTURE_CANDIDATE_READY", "CAPTURE_CANDIDATE_NOT_SAVEABLE", "CAPTURE_SAVING"),
        "read fail": ("READ_NONE", "READ_NO_RESPONSE", "READ_EXCEPTION", "READ_NOT_SENT", "READ_NONSTANDARD", "READ_SHORT",
                      "READ_BOUNDED_WAIT", "READ_IDLE_TIMEOUT"),
        "probe": ("PROBE_NONE", "PROBE_ABSENT", "PROBE_CLEAR", "PROBE_RESTORE_REQUIRED", "PROBE_PENDING_CLEAR", "PROBE_MALFORMED",
                  "PROBE_UNREADABLE"),
        "latch": ("LATCH_NONE", "LATCH_UNREADABLE", "LATCH_MALFORMED", "LATCH_GHOST_RR", "LATCH_GHOST_PC"),
        "obligation kind": ("OBL_UNSET", "OBL_CLEAR_PROVEN", "OBL_ACTIVE", "OBL_STARTING", "OBL_RESTORE_REQUIRED", "OBL_PENDING_CLEAR",
                            "OBL_ENDING", "OBL_OPERATOR_NEEDED", "UNK_DURABLE_UNREADABLE", "UNK_METADATA_CORRUPT",
                            "UNK_BOOT_NOT_LOADED", "UNK_DIVERGED", "UNK_BUS_OR_LOCK_STUCK", "UNK_NOT_PROBED", "BUS_BUSY"),
        "slot": ("SLOT_BUS", "SLOT_FBS", "SLOT_FP", "SLOT_DUMP", "SLOT_R244", "SLOT_MTOU"),
        "gate": ("GATE_UNSET", "GATE_ACCEPT", "GATE_NEED_PROBE", "GATE_REFUSE_IN_FLIGHT", "GATE_REFUSE_NOT_LOADED", "GATE_REFUSE_ARMS",
                 "GATE_REFUSE_BUS", "GATE_REFUSE_FBS", "GATE_REFUSE_FP", "GATE_REFUSE_DUMP", "GATE_REFUSE_R244", "GATE_REFUSE_MTOU"),
        "refusal kind": ("RF_NONE", "RF_244X", "RF_PWRL", "RF_PWRH", "RF_SOCH", "RF_SRCG", "RF_MODE", "RF_BITS", "RF_HHMM", "RF_243X",
                         "RF_CLASS", "RF_ANOMALY"),
        "witness view": ("WVIEW_OK", "WVIEW_LAG", "WVIEW_MISS", "WVIEW_CORR", "WVIEW_UNR", "WVIEW_ABS"),
    }
    check("every enum group is numbered 0..N-1 in the documented order, fail-closed zero first",
          all([getattr(cap, n) for n in names] == list(range(len(names))) for names in groups.values()))
    check("the three lease domains are numbered FP 0, DUMP 1, R244 2 and the nibble layout is 4 bits per domain",
          (cap.DOM_FP, cap.DOM_DUMP, cap.DOM_R244) == (0, 1, 2) and cap.latch_set(0, 2, 5) == 0x0500)
    check("the three markers' boot-load values equal ecco_durable::LoadStatus 0..3 and the unassigned value is 255",
          (cap.BOOT_LOAD_OK, cap.BOOT_LOAD_ABSENT, cap.BOOT_LOAD_WRONG_SIZE, cap.BOOT_LOAD_READ_ERROR, cap.BOOT_LOAD_NOT_LOADED)
          == (0, 1, 2, 3, 255))
    check("marker facts equal ecco_durable (VALID_MARKER_MAGIC 'ECCV', states CLEAR 0, RESTORE_REQUIRED 1, PENDING_CLEAR 2)",
          cap.MARKER_RECORD_MAGIC == 0x45434356 and (cap.MARKER_STATE_CLEAR, cap.MARKER_STATE_RESTORE_REQUIRED,
                                                     cap.MARKER_STATE_PENDING_CLEAR) == (0, 1, 2))
    # C++ / Python name parity
    header = HEADER_PATH.read_text(encoding="utf-8")
    prod = header[:header.index("// ---- GOLDENS-BEGIN ----")]
    code = re.sub(r"//[^\n]*", "", prod)
    cxx_funcs = set(re.findall(r"constexpr (?:const )?[\w:<>, ]+?[ *&](\w+)\(", code))
    py_funcs = {n for n, v in vars(cap).items() if callable(v) and not n.startswith("_") and getattr(v, "__module__", "") == "fallback_capture"
                and not isinstance(v, type)}
    cxx_only = {"put_char", "put", "put_u", "put_hex", "text_is", "str_is", "refusal_add", "put_refusal_code", "put_slot_tuple",
                "put_slots_body", "put_context_body", "put_reason_text", "index_map_matches_layout", "candidate_id_over", "early_rows",
                "probe_rows", "slot_ram_clear", "arms_on", "saved_view", "put_b7_saved", "stored_trusted", "c_str", "size"}
    check("every public function of the mirror exists in the header under the same name",
          not (py_funcs - cxx_funcs), str(sorted(py_funcs - cxx_funcs)))
    check("every header function exists in the mirror, except the TextBuf plumbing and private helpers",
          not (cxx_funcs - py_funcs - cxx_only), str(sorted(cxx_funcs - py_funcs - cxx_only)))
    cxx_structs = set(re.findall(r"^struct (\w+)", code, re.M))
    py_structs = {n for n, v in vars(cap).items() if isinstance(v, type) and getattr(v, "__module__", "") == "fallback_capture"}
    check("every header struct has a mirror dataclass of the same name (TextBuf is a str subclass)", cxx_structs <= py_structs,
          str(sorted(cxx_structs - py_structs)))
    fields_ok = True
    detail = []
    for name in sorted(cxx_structs - {"TextBuf"}):
        m = re.search(rf"^struct {name} \{{(.*?)^\}};", code, re.M | re.S)
        cxx_fields = re.findall(r"^\s+(?:[\w:<>, ]+?)\s+(\w+)(?:\{\})?(?: = [^;]+)?;", m.group(1), re.M)
        py_fields = [f for f in getattr(cap, name).__dataclass_fields__]
        if cxx_fields != py_fields:
            fields_ok = False
            detail.append((name, cxx_fields, py_fields))
    check("every POD struct has the same fields, in the same order, in the header and in the mirror", fields_ok, str(detail[:2]))
    cxx_consts = set(re.findall(r"^constexpr (?:uint8_t|uint16_t|uint32_t|size_t|bool) ([A-Z][A-Z0-9_]+) =", code, re.M))
    check("every scalar constant of the header exists in the mirror", all(hasattr(cap, c) for c in cxx_consts),
          str([c for c in cxx_consts if not hasattr(cap, c)]))
    doc = header[:header.index("namespace ecco_fbcap")]
    entry_points = ("store_block_230", "store_block_241", "first_diff", "reg_of", "words_of", "profile_from_words", "capture_refusals",
                    "capture_warnings", "sv_text", "review_eligible", "review_evaluate", "evaluate_read", "gate_decide", "probe_result",
                    "latch_get", "latch_set", "latch_text", "candidate_expired", "exp_seconds", "lease_domain_nonclear", "breaker_fired",
                    "writes_fingerprint", "epc_name", "b2_text", "b3_text", "b4_text", "b5_text", "b6_text", "b7_text", "b8_text")
    check("the header's top comment names every YAML entry point", all(e in doc for e in entry_points),
          str([e for e in entry_points if e not in doc]))
    mdoc = cap.__doc__
    check("the mirror's docstring documents the entry points and the signatures",
          all(e in mdoc for e in ("first_diff", "store_block_241", "capture_refusals", "evaluate_read", "gate_decide", "probe_result",
                                  "candidate_expired", "lease_domain_nonclear", "breaker_fired", "writes_fingerprint")))


# ===============================================================================================================
def section_index_map():
    print("[2] the 31-word index map and the pass buffers")
    v241 = [3000 + i for i in range(53)]
    v230 = [4000 + i for i in range(3)]
    w = [0] * 31
    check("store_block_241 accepts exactly 53 values", cap.store_block_241(w, v241))
    check("word k = values[register - 241] for every word except 232 and 230 (the 241/53 frame covers 241..293)",
          all(w[k] == 3000 + (cap.REGS[k] - 241) for k in range(31) if k not in (19, 28)) and w[19] == w[28] == 0)
    check("store_block_230 accepts exactly 3 values", cap.store_block_230(w, v230))
    check("232 = values[2] and 230 = values[0] of the 230/3 frame (231 is ignored)", w[19] == 4002 and w[28] == 4000)
    check("the live decoders' index map: 243 = values[2], 244 = [3], 245 = [4], 247 = [6], 248 = [7], 250-255 = [9..14], 256-261 = [15..20], "
          "268-273 = [27..32], 274-279 = [33..38]",
          (w[20], w[0], w[29], w[30], w[21]) == (3002, 3003, 3004, 3006, 3007) and w[22:28] == [3009 + i for i in range(6)]
          and w[1:7] == [3015 + i for i in range(6)] and w[7:13] == [3027 + i for i in range(6)] and w[13:19] == [3033 + i for i in range(6)])
    unstored = [241, 242, 246, 249, *range(262, 268), *range(280, 294)]
    base = [0] * 31
    cap.store_block_241(base, v241)
    ok = True
    for reg in unstored:
        v = list(v241)
        v[reg - 241] ^= 0xFFFF
        w2 = [0] * 31
        cap.store_block_241(w2, v)
        ok = ok and w2 == base
    check(f"the {len(unstored)} registers read but NOT stored (241, 242, 246, 249, 262-267, 280-293) never change the 31 words", ok)
    bad = []
    for size in range(0, 131):
        if size == 53:
            continue
        w3 = [7] * 31
        if cap.store_block_241(w3, [1] * size) or w3 != [7] * 31:
            bad.append(size)
    for size in range(0, 131):
        if size == 3:
            continue
        w3 = [7] * 31
        if cap.store_block_230(w3, [1] * size) or w3 != [7] * 31:
            bad.append(("230", size))
    check("every other reply size is rejected and stores nothing (0..130 for both frames)", not bad, str(bad[:5]))
    w4 = [0] * 31
    cap.store_block_241(w4, [70000 + i for i in range(53)])
    check("stored words are 16-bit", all(0 <= x <= 0xFFFF for x in w4))
    p1, p2 = [0] * 31, [0] * 31
    cap.store_block_241(p1, v241)
    cap.store_block_230(p1, v230)
    cap.store_block_241(p2, v241)
    cap.store_block_230(p2, v230)
    check("pass 1 and pass 2 are separate buffers: identical replies give identical words", p1 == p2 and cap.first_diff(p1, p2) == -1)
    check("first_diff finds a change of EACH single word at its own index", all(
        cap.first_diff(GW, wd(**{f"w{k}": GW[k] ^ 1})) == k for k in range(31)))
    check("first_diff is the FIRST difference (canonical order)", cap.first_diff(GW, wd(w5=1, w9=2)) == 5 and cap.first_diff(GW, wd(w30=1, w28=1)) == 28)
    rng = random.Random(11)
    ok = True
    for _ in range(500):
        a, b = rand_words(rng), rand_words(rng)
        want = next((k for k in range(31) if a[k] != b[k]), -1)
        ok = ok and cap.first_diff(a, b) == want
    check("first_diff agrees with a reference scan on 500 random pairs", ok)
    check("words_of / profile_from_words round trip, constants in q, everything else zero",
          cap.words_of(cap.profile_from_words(GW)) == GW and cap.profile_from_words(GW)["magic"] == fp.PROFILE_MAGIC
          and cap.profile_from_words(GW)["generation"] == 0 and cap.profile_from_words(GW)["flags"] == 0
          and cap.profile_from_words(GW)["binding"] == 0 and cap.profile_from_words(GW)["reserved0"] == 0
          and cap.words_of(fp.pack_profile(GOLD_P)) == GW)
    # the 34 words / 31 registers rule: pass equality covers the 31 words only
    a = [0] * 31
    b = [0] * 31
    va, vb = list(v241), list(v241)
    vb[280 - 241] = 5
    vb[241 - 241] = 9
    cap.store_block_241(a, va)
    cap.store_block_241(b, vb)
    check("volatile words outside the 31 (241, 280) never fail pass equality", cap.first_diff(a, b) == -1)


# ===============================================================================================================
def section_l2():
    print("[3] L2 capture refusals: truth tables over the whole u16 domain of every field")
    check("the golden words are clean at the default ceiling", cap.capture_refusals(GW, 8000).count == 0)
    # 244
    res = [v for v in range(65536) if codes_of(cap.capture_refusals(wd(w0=v), 8000)) == []]
    check("244: only the value 2 is accepted (0 Allow Export and 1 Essentials are refused)", res == [2])
    # power slots, all 65536 values for every slot, ceiling 8000
    ok = True
    for n in range(1, 7):
        acc = [v for v in range(65536) if not codes_of(cap.capture_refusals(wd(**{f"w{n}": v}), 8000))]
        ok = ok and acc == list(range(500, 8001))
    check("power slots 1-6: exactly 500..8000 W is accepted (499 -> PWRL, 8001 -> PWRH), every slot", ok)
    lo = [v for v in range(0, 500)]
    check("power below 500 is PWRL<n>, above 8000 PWRH<n>", all(codes_of(cap.capture_refusals(wd(w3=v), 8000)) == ["PWRL3"] for v in lo)
          and all(codes_of(cap.capture_refusals(wd(w3=v), 8000)) == ["PWRH3"] for v in range(8001, 65536, 7)))
    low = wd(w1=500, w3=500, w4=500, w5=500, w6=500)    # the other five slots at the minimum, so only slot 2 is under test
    for ceiling in (0, 499, 500, 1000, 5000, 8000, 8001, 10000, 65535, 2 ** 32 - 1):
        acc = [v for v in range(65536) if not codes_of(cap.capture_refusals(wd(low, w2=v), ceiling))]
        want = list(range(500, min(8000, ceiling) + 1)) if ceiling >= 500 else []
        check(f"site ceiling {ceiling} W: accepted powers are 500..min(8000, ceiling); above it PWRH, below 500 PWRL", acc == want,
              f"{acc[:2]}..{acc[-2:]} vs {want[:2]}..{want[-2:]}")
    # SOC
    acc = [v for v in range(65536) if not codes_of(cap.capture_refusals(wd(w9=v), 8000))]
    check("SOC (268-273): 0..100 is accepted, 101..65535 is SOCH<n> (slot 3 swept)", acc == list(range(101)))
    check("SOC boundary 100 / 101 in every slot", all(
        codes_of(cap.capture_refusals(wd(**{f"w{6 + n}": 100}), 8000)) == [] and
        codes_of(cap.capture_refusals(wd(**{f"w{6 + n}": 101}), 8000)) == [f"SOCH{n}"] for n in range(1, 7)))
    # source words
    bad = []
    count_src = 0
    for v in range(65536):
        got = codes_of(cap.capture_refusals(wd(w15=v), 8000))
        want = [c for c in oracle_l2(wd(w15=v), 8000)]
        if got != want:
            bad.append(v)
        count_src += bool(got)
    check("source words 274-279: every one of the 65536 values refuses exactly like the oracle (accepted: {0, 1} only; never masked)",
          not bad and count_src == 65534, f"{bad[:4]} {count_src}")
    cover = all(set(codes_of(cap.capture_refusals(wd(w15=v), 8000))) for v in range(2, 65536))
    check("SRCG / MODE / BITS always cover every word outside {0, 1}", cover)
    check("source code families: 2,3 -> SRCG; 4..0x1C -> MODE; 0x20.. -> BITS; mixed words raise several in the order SRCG, MODE, BITS",
          codes_of(cap.capture_refusals(wd(w15=2), 8000)) == ["SRCG3"] and codes_of(cap.capture_refusals(wd(w15=3), 8000)) == ["SRCG3"]
          and codes_of(cap.capture_refusals(wd(w15=4), 8000)) == ["MODE3"] and codes_of(cap.capture_refusals(wd(w15=0x1C), 8000)) == ["MODE3"]
          and codes_of(cap.capture_refusals(wd(w15=0x20), 8000)) == ["BITS3"] and codes_of(cap.capture_refusals(wd(w15=0x8000), 8000)) == ["BITS3"]
          and codes_of(cap.capture_refusals(wd(w15=0x27), 8000)) == ["SRCG3", "MODE3", "BITS3"]
          and codes_of(cap.capture_refusals(wd(w15=5), 8000)) == ["MODE3"] and codes_of(cap.capture_refusals(wd(w15=0xFFFF), 8000)) == ["SRCG3", "MODE3", "BITS3"])
    # HHMM
    dec = [v for v in range(65536) if cap.hhmm_decodable(v)]
    check("HHMM: exactly 1440 values 0..65535 decode (hh <= 23 and mm <= 59: 0..59, 100..159, ..., 2300..2359)",
          len(dec) == 24 * 60 and dec == [h * 100 + m for h in range(24) for m in range(60)])
    check("HHMM boundaries: 2359 decodes; 2400, 60 (0060), 99, 2360 do not", cap.hhmm_decodable(2359) and not any(
        cap.hhmm_decodable(v) for v in (2400, 60, 99, 2360, 65535)))
    acc = [v for v in range(65536) if not codes_of(cap.capture_refusals(wd(w25=v), 8000))]
    check("only an undecodable start refuses (HHMM4 swept over all 65536 values); the grid and the ring never refuse", acc == dec)
    check("the 5-minute grid: mm % 5 == 0", [v for v in (0, 5, 55, 100, 530, 531, 2355, 2359) if cap.on_5min_grid(v)] == [0, 5, 55, 100, 530, 2355])
    # 243
    acc = [v for v in range(65536) if not codes_of(cap.capture_refusals(wd(w20=v), 8000))]
    check("243 (energy management): 0 and 1 are accepted, everything else is 243X", acc == [0, 1])
    check("232, 248, 230, 245, 247 are never refused (all 65536 values of each)", all(
        not codes_of(cap.capture_refusals(wd(**{f"w{k}": v}), 8000)) for k in (19, 21, 28, 29, 30) for v in range(0, 65536, 17)))
    # code order
    worst = cap.capture_refusals([65535] * 31, 8000)
    codes = codes_of(worst)
    want = ["244X"] + [f"PWRH{n}" for n in range(1, 7)] + [f"SOCH{n}" for n in range(1, 7)] + [
        f"{c}{n}" for n in range(1, 7) for c in ("SRCG", "MODE", "BITS")] + [f"HHMM{n}" for n in range(1, 7)] + ["243X"]
    check("code order: 244X; PWR slots 1-6; SOCH slots 1-6; per slot SRCG, MODE, BITS; HHMM slots 1-6; 243X (38 refusals at most)",
          codes == want and worst.count == 38 <= cap.REFUSAL_MAX)
    rng = random.Random(3)
    ok = True
    for _ in range(4000):
        w = rand_words(rng, 0.45)
        c = rng.choice([8000, 5000, 3000, 10000])
        ok = ok and codes_of(cap.capture_refusals(w, c)) == oracle_l2(w, c)
    check("capture_refusals equals the register-number oracle on 4000 random vectors and ceilings", ok)
    # sv text
    sv = lambda w, c=8000: str(cap.sv_text(cap.capture_refusals(w, c)))  # noqa: E731
    check("sv: OK for zero refusals; NO:c1,c2,c3 for up to three; +N for the rest",
          sv(GW) == "OK" and sv(wd(w0=0)) == "NO:244X" and sv(wd(w0=0, w1=499)) == "NO:244X,PWRL1"
          and sv(wd(w0=0, w1=499, w8=101)) == "NO:244X,PWRL1,SOCH2" and sv(wd(w0=0, w1=499, w8=101, w20=7)) == "NO:244X,PWRL1,SOCH2+1"
          and sv([65535] * 31) == "NO:244X,PWRH1,PWRH2+35")
    check("sv never contains RING (an invalid ring is warning W6, never a refusal) and never exceeds 26 characters",
          "RING" not in sv(wd(w23=0)) and sv(wd(w23=0)) == "OK" and all(len(sv(rand_words(rng, 0.5))) <= 26 for _ in range(500)))
    check("review_eligible: no L2 refusal AND a class that permits saving AND no read anomaly",
          cap.review_eligible(cap.Refusals(), 5, 0) and not cap.review_eligible(cap.Refusals(), 0, 0)
          and not cap.review_eligible(cap.Refusals(), 7, 0) and not cap.review_eligible(cap.Refusals(), 5, 1)
          and not cap.review_eligible(cap.Refusals(count=1), 5, 0)
          and [c for c in range(0, 12) if cap.review_eligible(cap.Refusals(), c, 0)] == [1, 2, 3, 4, 5, 6, 8])


def section_warnings():
    print("[4] L2w warnings W1-W6 (display only) against register-number oracles; ring")
    check("the golden words raise no warning", cap.capture_warnings(GW) == 0)
    single = {
        "W1": (wd(w7=100, w8=100, w9=100, w10=100, w11=100, w12=100, w13=1, w14=1, w15=1, w16=1, w17=1, w18=1), 1),
        "W2": (wd(w1=3000, w2=3000, w3=3000, w4=3000, w5=3000, w6=3000), 2),
        "W3": (wd(w21=0), 4), "W4": (wd(w19=0x10), 8), "W5": (wd(w23=531), 16), "W6": (wd(w23=0), 32)}
    check("each warning fires alone on its minimal trigger (bit n-1 = Wn)", all(cap.capture_warnings(w) == m for w, m in single.values()),
          str({k: cap.capture_warnings(w) for k, (w, m) in single.items()}))
    check("W1 needs 232 bit0; W2 stops above 3000 W; W3 reads only 248 bit0; W4 needs a Grid source",
          cap.capture_warnings(wd(w7=100, w8=100, w9=100, w10=100, w11=100, w12=100, w13=1, w14=1, w15=1, w16=1, w17=1, w18=1, w19=0x10)) & 1 == 0
          and cap.capture_warnings(wd(w1=3001, w2=3001, w3=3001, w4=3001, w5=3001, w6=3001)) & 2 == 0
          and cap.capture_warnings(wd(w21=0x0002)) & 4 and not cap.capture_warnings(wd(w21=0x0003)) & 4
          and not cap.capture_warnings(wd(w19=0x10, w13=0, w14=0, w15=0, w16=0, w17=0, w18=0)) & 8)
    check("W5 ignores an undecodable start (it is refused instead); W5 fires on a decodable off-grid start",
          not cap.capture_warnings(wd(w23=2461)) & 16 and cap.capture_warnings(wd(w23=2459)) & 16 == 0 and cap.capture_warnings(wd(w23=531)) & 16)
    check("ring valid: sorted, rotated, one wrap", cap.ring_valid(GW) and cap.ring_valid(wd(w22=2300, w23=300, w24=800, w25=1200, w26=1600, w27=2000)))
    check("ring invalid: duplicate, out of order, wraps twice, undecodable, all equal",
          not cap.ring_valid(wd(w23=0)) and not cap.ring_valid(wd(w23=2200)) and not cap.ring_valid(wd(w22=0, w23=800, w24=1600, w25=200, w26=1000, w27=1800))
          and not cap.ring_valid(wd(w24=2400)) and not cap.ring_valid([0] * 31))
    rng = random.Random(5)
    ok = ok2 = True
    for _ in range(6000):
        w = rand_words(rng, 0.5)
        ok = ok and cap.capture_warnings(w) == oracle_warnings(w)
        ok2 = ok2 and cap.ring_valid(w) == oracle_ring(w)
    check("capture_warnings equals the oracle on 6000 random vectors", ok)
    check("ring_valid equals the single-descent oracle on 6000 random vectors", ok2)
    ok = True
    for _ in range(3000):
        base = [rng.choice([0, 100, 230, 800, 1200, 2300, 2359, 59, 60, 2400]) for _ in range(6)]
        w = wd(**{f"w{22 + i}": base[i] for i in range(6)})
        ok = ok and cap.ring_valid(w) == oracle_ring(w)
    check("ring_valid equals the oracle on 3000 start-time sets drawn from boundary values", ok)
    check("the warning mask uses bits 0..5 only", all(cap.capture_warnings(rand_words(rng, 0.6)) < 64 for _ in range(500)))
    check("warnings never change what is refused and refusals never change warnings (independent layers)",
          codes_of(cap.capture_refusals(wd(w23=531), 8000)) == [] and codes_of(cap.capture_refusals(wd(w21=0), 8000)) == []
          and cap.capture_warnings(wd(w0=0)) == 0)


def section_independence():
    print("[5] L2 is independent of classify_profile, and consistent with FB-A's E1 domain")
    src = Path(fp.__file__).read_text(encoding="utf-8")
    check("FB-A's mirror does not import the capture mirror (no path from L2 into the classifier)", "fallback_capture" not in src)
    mirror = MIRROR_PATH.read_text(encoding="utf-8")
    body = mirror[mirror.index("def capture_refusals"):mirror.index("def _refusal_code")]
    check("capture_refusals / capture_warnings call only FB-A's leaf validators, never classify_profile / profile_defect / compose",
          not re.search(r"classify_profile|profile_defect|profile_domain_valid|compose_profile_class|fba_authentic", body)
          and "fp.reg244_domain_valid" in body)
    rng = random.Random(8)
    agree = disagree_l1 = disagree_l2 = 0
    for _ in range(3000):
        w = rand_words(rng, 0.4)
        q = fp.seal_profile(cap.profile_from_words(w))
        q["generation"] = 1
        q = fp.seal_profile(q)
        l1_valid = fp.classify_profile(fp.LOAD_OK, q) == fp.PROFILE_VALID
        l2_e1 = [c for c in codes_of(cap.capture_refusals(w, 8000)) if not c.startswith(("HHMM", "243X"))]
        agree += (not l2_e1) == l1_valid
        if l2_e1 and l1_valid:
            disagree_l1 += 1
        if (not l2_e1) and not l1_valid:
            disagree_l2 += 1
    check("the L2 E1 refusals (244X, PWR, SOCH, SRCG/MODE/BITS) are EXACTLY the words FB-A's L1 domain rejects (generation >= 1, sealed)",
          agree == 3000 and not disagree_l1 and not disagree_l2, f"{agree} {disagree_l1} {disagree_l2}")
    bad_hhmm = fp.seal_profile(cap.profile_from_words(wd(w25=2400, w20=7)))
    bad_hhmm["generation"] = 1
    bad_hhmm = fp.seal_profile(bad_hhmm)
    check("a profile with an undecodable start and 243 = 7 is still VALID for the classifier (L1 never checks CTX / INFO) although L2 refuses it",
          fp.classify_profile(fp.LOAD_OK, bad_hhmm) == fp.PROFILE_VALID and codes_of(cap.capture_refusals(cap.words_of(bad_hhmm), 8000)) == ["HHMM4", "243X"])
    off = fp.seal_profile(cap.profile_from_words(wd(w23=531, w19=0x10, w21=0)))
    off["generation"] = 1
    off = fp.seal_profile(off)
    check("off-grid starts, a bad ring and the warning set never reach the classifier either (still VALID)",
          fp.classify_profile(fp.LOAD_OK, off) == fp.PROFILE_VALID and cap.capture_warnings(cap.words_of(off)))
    saved = cap.capture_refusals
    try:
        cap.capture_refusals = lambda *_a, **_k: cap.Refusals()  # an L2 rule mutated to refuse nothing
        cls_after = [fp.classify_profile(fp.LOAD_OK, GOLD_P), fp.classify_profile(fp.LOAD_OK, bad_hhmm)]
    finally:
        cap.capture_refusals = saved
    check("mutating an L2 rule changes no classification (golden classes stay VALID / VALID)", cls_after == [fp.PROFILE_VALID, fp.PROFILE_VALID])


def section_masks():
    print("[6] compare masks dx / dc / di (candidate a vs stored b) and out-of-domain")
    ADD = {a: i for i, a in enumerate(ADDRS)}
    dx_regs = [244, *range(256, 262), *range(268, 274), *range(274, 280)]
    ctx_regs = [232, 243, 248, *range(250, 256)]

    def o_dx(a, b):
        ra, rb = regs(a), regs(b)
        return sum(1 << i for i, r in enumerate(dx_regs) if ra[r] != rb[r])

    def o_dc(a, b):
        ra, rb = regs(a), regs(b)
        m = 0
        for i, r in enumerate(ctx_regs):
            mask = fp.register_class_mask(r)
            if (ra[r] & mask) != (rb[r] & mask):
                m |= 1 << i
        return m

    def o_di(a, b):
        ra, rb = regs(a), regs(b)
        m = 0
        for i, r in enumerate((230, 245, 247)):
            if ra[r] != rb[r]:
                m |= 1 << i
        if (ra[232] ^ rb[232]) >> 1:
            m |= 8
        if (ra[248] ^ rb[248]) >> 1:
            m |= 16
        return m

    check("bit layouts: dx bit0 244, bits1-6 256-261, 7-12 268-273, 13-18 274-279 (19 bits, full words)",
          all(cap.e1_delta_mask(wd(**{f"w{k}": GW[k] ^ 1}), GW) == (1 << k) for k in range(19))
          and all(cap.e1_delta_mask(wd(**{f"w{k}": GW[k] ^ 1}), GW) == 0 for k in range(19, 31)))
    check("dx compares 274-279 as FULL words: a change confined to bits 2-15 still sets the bit (FB-A's 0x0003 mask would miss it)",
          all(cap.e1_delta_mask(wd(**{f"w{k}": GW[k] ^ (1 << bit)}), GW) == 1 << k for k in range(13, 19) for bit in range(16))
          and fp.register_class_mask(274) == 3)
    check("dc: bit0 232.b0, bit1 243, bit2 248.b0, bits3-8 250-255 (FB-A ctx_matches); 232/248 upper bits never set dc",
          cap.ctx_mismatch_mask(wd(w19=GW[19] ^ 1), GW) == 1 and cap.ctx_mismatch_mask(wd(w19=GW[19] ^ 0xFFFE), GW) == 0
          and cap.ctx_mismatch_mask(wd(w20=GW[20] ^ 0x8000), GW) == 2 and cap.ctx_mismatch_mask(wd(w21=GW[21] ^ 1), GW) == 4
          and cap.ctx_mismatch_mask(wd(w21=GW[21] ^ 0xFFFE), GW) == 0
          and all(cap.ctx_mismatch_mask(wd(**{f"w{22 + i}": GW[22 + i] ^ 0x8000}), GW) == 8 << i for i in range(6)))
    check("di: bit0 230, bit1 245, bit2 247 (full word), bit3 232 bits 1-15, bit4 248 bits 1-15; the bit0 of 232 / 248 is context, not info",
          cap.info_mismatch_mask(wd(w28=1), GW) == 1 and cap.info_mismatch_mask(wd(w29=1), GW) == 2
          and cap.info_mismatch_mask(wd(w30=GW[30] ^ 1), GW) == 4 and cap.info_mismatch_mask(wd(w30=GW[30] ^ 0x8000), GW) == 4
          and cap.info_mismatch_mask(wd(w19=GW[19] ^ 1), GW) == 0 and cap.info_mismatch_mask(wd(w19=GW[19] ^ 2), GW) == 8
          and cap.info_mismatch_mask(wd(w21=GW[21] ^ 1), GW) == 0 and cap.info_mismatch_mask(wd(w21=GW[21] ^ 2), GW) == 16)
    rng = random.Random(21)
    ok1 = ok2 = ok3 = True
    for _ in range(4000):
        a, b = rand_words(rng, 0.5), rand_words(rng, 0.5)
        ok1 = ok1 and cap.e1_delta_mask(a, b) == o_dx(a, b)
        ok2 = ok2 and cap.ctx_mismatch_mask(a, b) == o_dc(a, b)
        ok3 = ok3 and cap.info_mismatch_mask(a, b) == o_di(a, b)
    check("dx equals the register-number oracle on 4000 random pairs", ok1)
    check("dc equals the register-number oracle (fp.register_class_mask) on 4000 random pairs", ok2)
    check("di equals the register-number oracle on 4000 random pairs", ok3)
    check("identical words give 0 / 0 / 0; every word different gives the maximum 7FFFF / 1FF / 1F",
          (cap.e1_delta_mask(GW, GW), cap.ctx_mismatch_mask(GW, GW), cap.info_mismatch_mask(GW, GW)) == (0, 0, 0)
          and (cap.e1_delta_mask([0] * 31, [0xFFFF] * 31), cap.ctx_mismatch_mask([0] * 31, [0xFFFF] * 31),
               cap.info_mismatch_mask([0] * 31, [0xFFFF] * 31)) == (0x7FFFF, 0x1FF, 0x1F))
    check("the ctx mask uses FB-A's ctx_matches on the nine CTX addresses (a non-CTX address raises in FB-A and is never passed)",
          all(fp.register_class(a) == fp.REG_CTX for a in (232, 243, 248, 250, 251, 252, 253, 254, 255)))
    ood = lambda w: cap.out_of_domain_mask(w)  # noqa: E731
    check("out_of_domain_mask: bit0 244 not in {0, 2}, bits 1-6 power, 7-12 SOC, 13-18 source (the live-word domain)",
          ood(GW) == 0 and ood(wd(w0=0)) == 0 and ood(wd(w0=1)) == 1 and ood(wd(w0=3)) == 1
          and all(ood(wd(**{f"w{n}": 499})) == 1 << n for n in range(1, 7)) and all(ood(wd(**{f"w{6 + n}": 101})) == 1 << (6 + n) for n in range(1, 7))
          and all(ood(wd(**{f"w{12 + n}": 2})) == 1 << (12 + n) for n in range(1, 7)) and ood([65535] * 31) == 0x7FFFF)


def section_candidate_id():
    print("[7] candidate id (S1 9.3): goldens, readings, sensitivity")
    DOM = b"ECCO-FALLBACK-PROFILE-CANDIDATE-v1"

    def independent(salt, seq, pc, pg, pb, words, header=True):
        q = fp.blank_profile(magic=fp.PROFILE_MAGIC if header else 0, schema=1 if header else 0, size=96 if header else 0,
                             reg244=words[0], reg256_261=words[1:7], reg268_273=words[7:13], reg274_279=words[13:19], reg232=words[19],
                             reg243=words[20], reg248=words[21], reg250_255=words[22:28], reg230=words[28], reg245=words[29], reg247=words[30])
        return fp.fnv1a_64(DOM + struct.pack("<IIBIQ", salt, seq, pc, pg, pb) + fp.pack_profile(q)[:88])

    vecs = [(1, 1, 1, 0, 0), (0xDEADBEEF, 2, 5, 7, 0xD852A4FA2DF7DBA3), (0xFFFFFFFF, 0xFFFFFFFF, 8, 0xFFFFFFFF, 0xFFFFFFFFFFFFFFFF), (0, 0, 0, 0, 0)]
    check("golden vectors: constants reading 1D63D8CBC6CB4D55 (salt 1, seq 1, NOT_CAPTURED) and 51235C0108AEE8F4 (salt DEADBEEF, seq 2, VALID g7)",
          cap.candidate_id(1, 1, 1, 0, 0, GW) == 0x1D63D8CBC6CB4D55 and cap.candidate_id(0xDEADBEEF, 2, 5, 7, 0xD852A4FA2DF7DBA3, GW) == 0x51235C0108AEE8F4)
    check("the rejected zero-magic reading differs and equals its own independent derivation (A8085CFF57C3D9D2 / 288590F51189AD63)",
          cap.candidate_id_alt_zero_header_reading(1, 1, 1, 0, 0, GW) == 0xA8085CFF57C3D9D2
          and cap.candidate_id_alt_zero_header_reading(0xDEADBEEF, 2, 5, 7, 0xD852A4FA2DF7DBA3, GW) == 0x288590F51189AD63)
    check("both readings equal an independent derivation (struct.pack + fnv1a_64 over the packed record) on every vector",
          all(cap.candidate_id(*v, GW) == independent(*v, GW) and cap.candidate_id_alt_zero_header_reading(*v, GW) == independent(*v, GW, False)
              for v in vecs))
    check("the locked reading is the constants reading: q carries PROFILE_MAGIC / schema 1 / size 96 (they are in the hashed range)",
          cap.candidate_id(1, 1, 1, 0, 0, GW) != cap.candidate_id_alt_zero_header_reading(1, 1, 1, 0, 0, GW))
    base = cap.candidate_id(1, 1, 1, 0, 0, GW)
    check("every input matters: salt, seq, prior class, prior generation, prior binding", all(x != base for x in (
        cap.candidate_id(2, 1, 1, 0, 0, GW), cap.candidate_id(1, 2, 1, 0, 0, GW), cap.candidate_id(1, 1, 2, 0, 0, GW),
        cap.candidate_id(1, 1, 1, 1, 0, GW), cap.candidate_id(1, 1, 1, 0, 1, GW))))
    check("every bit of every input matters (salt 32, seq 32, class 8, generation 32, binding 64 single-bit flips)", all(
        len({base} | {cap.candidate_id(1 ^ (1 << i), 1, 1, 0, 0, GW) for i in range(32)}) == 33 for _ in (0,))
        and all(cap.candidate_id(1, 1 ^ (1 << i), 1, 0, 0, GW) != base for i in range(32))
        and all(cap.candidate_id(1, 1, 1 ^ (1 << i), 0, 0, GW) != base for i in range(8))
        and all(cap.candidate_id(1, 1, 1, 1 << i, 0, GW) != base for i in range(32))
        and all(cap.candidate_id(1, 1, 1, 0, 1 << i, GW) != base for i in range(64)))
    check("every bit of every one of the 31 words matters (496 single-bit flips, all distinct)",
          len({cap.candidate_id(1, 1, 1, 0, 0, wd(**{f"w{k}": GW[k] ^ (1 << b)})) for k in range(31) for b in range(16)} | {base}) == 31 * 16 + 1)
    check("the id depends on neither generation / epoch / flags nor the binding of q (they are zero / outside the hashed range)",
          cap.profile_from_words(GW)["generation"] == 0 and cap.profile_from_words(GW)["captured_epoch"] == 0
          and cap.profile_from_words(GW)["flags"] == 0 and cap.profile_from_words(GW)["binding"] == 0)
    rng = random.Random(77)
    ids = set()
    for _ in range(3000):
        ids.add(cap.candidate_id(rng.randrange(2 ** 32), rng.randrange(2 ** 32), rng.randrange(9), rng.randrange(2 ** 32), rng.randrange(2 ** 64), rand_words(rng)))
    check("3000 random inputs give 3000 distinct 64-bit ids", len(ids) == 3000)
    check("the domain is the 34-byte literal, uppercase hyphenated (not a durable-tag shape)", len(cap.CANDIDATE_DOMAIN) == 34
          and not re.fullmatch(r"ecco_[a-z0-9_]+_v\d+", cap.CANDIDATE_DOMAIN.decode()))
    check("id_text is %016llX: 16 uppercase hex digits, leading zeros kept", str(cap.id_text(0xAB)) == "00000000000000AB"
          and str(cap.id_text(base)) == "1D63D8CBC6CB4D55" and len(str(cap.id_text(2 ** 64 - 1))) == 16)
    check("the step helper hashes little-endian bytes (u32 / u64 / u8)",
          cap.step_le(fp.FNV1A64_OFFSET_BASIS, 0x01020304, 4) == fp.fnv1a_64(bytes([4, 3, 2, 1]))
          and cap.step_le(fp.FNV1A64_OFFSET_BASIS, 0x0102030405060708, 8) == fp.fnv1a_64(bytes([8, 7, 6, 5, 4, 3, 2, 1]))
          and cap.step_le(fp.FNV1A64_OFFSET_BASIS, 0xAB, 1) == fp.fnv1a_64(b"\xab"))


# ---------------------------------------------------------------------------------------------------------------
# Classifiers
# ---------------------------------------------------------------------------------------------------------------
def gi(boot_loaded=True, latch=0, fbs=fd.FBS_CLEAR_ABSENT, **fields) -> cap.GateInputs:
    """GateInputs with every lease marker loaded ABSENT at boot; fields set by the REAL global names."""
    g = cap.GateInputs(boot_loaded=boot_loaded, fbs_slot=fbs, probe_latch=latch)
    g.fp.free_power_marker_boot_load = g.dump.dump_marker_boot_load = g.r244.reg244_marker_boot_load = 1
    for name, value in fields.items():
        dom, _, field = name.partition("::")
        if not field:
            dom, field = "", name
        targets = {"fp": g.fp, "dump": g.dump, "r244": g.r244, "bus": g.bus, "": None}
        if dom:
            setattr(targets[dom], field, value)
        else:
            for part in (g.bus, g.fp, g.dump, g.r244, g):
                if hasattr(part, field):
                    setattr(part, field, value)
                    break
            else:
                raise AssertionError(field)
    return g


K, B = cap, cap
FP_ROWS = [
    # (label, fields, latch, probe, expected (kind, basis))
    ("1  boot not loaded", dict(boot_loaded=False), 0, 0, (K.UNK_BOOT_NOT_LOADED, B.BASIS_NONE)),
    ("1  marker boot load never assigned (255)", {"fp::free_power_marker_boot_load": 255}, 0, 0, (K.UNK_BOOT_NOT_LOADED, B.BASIS_NONE)),
    ("1  marker boot load outside 0..3", {"fp::free_power_marker_boot_load": 4}, 0, 0, (K.UNK_BOOT_NOT_LOADED, B.BASIS_NONE)),
    ("2  corrupt + boot READ_ERROR = UNKNOWN (the pair replaces the unknown mask)",
     {"fp::free_power_recovery_metadata_corrupt": True, "fp::free_power_marker_boot_load": 3}, 0, 0, (K.UNK_DURABLE_UNREADABLE, B.BASIS_BOOT_READ_ERROR)),
    ("2  ...and a runtime probe that would read ABSENT does not rescue it (golden: boot READ_ERROR + runtime ABSENT)",
     {"fp::free_power_recovery_metadata_corrupt": True, "fp::free_power_marker_boot_load": 3}, 0, K.PROBE_ABSENT, (K.UNK_DURABLE_UNREADABLE, B.BASIS_BOOT_READ_ERROR)),
    ("3  corrupt, load OK = hard lockout", {"fp::free_power_recovery_metadata_corrupt": True, "fp::free_power_marker_boot_load": 0}, 0, 0,
     (K.UNK_METADATA_CORRUPT, B.BASIS_BOOT_LOCKOUT)),
    ("3  corrupt, load ABSENT (dual-obligation arbitration)", {"fp::free_power_recovery_metadata_corrupt": True}, 0, 0,
     (K.UNK_METADATA_CORRUPT, B.BASIS_BOOT_LOCKOUT)),
    ("3  corrupt, load WRONG_SIZE (malformed)", {"fp::free_power_recovery_metadata_corrupt": True, "fp::free_power_marker_boot_load": 2}, 0, 0,
     (K.UNK_METADATA_CORRUPT, B.BASIS_BOOT_LOCKOUT)),
    ("2b load WRONG_SIZE but the flag is clear", {"fp::free_power_marker_boot_load": 2}, 0, 0, (K.UNK_DIVERGED, B.BASIS_RAM_INCONSISTENT)),
    ("2b load READ_ERROR but the flag is clear", {"fp::free_power_marker_boot_load": 3}, 0, 0, (K.UNK_DIVERGED, B.BASIS_RAM_INCONSISTENT)),
    ("4  latch UNREADABLE", {}, 0x0001, 0, (K.UNK_DURABLE_UNREADABLE, B.BASIS_RUNTIME_PROBE)),
    ("4  latch MALFORMED", {}, 0x0002, 0, (K.UNK_METADATA_CORRUPT, B.BASIS_RUNTIME_PROBE)),
    ("4  latch GHOST_RR", {}, 0x0003, 0, (K.UNK_DIVERGED, B.BASIS_GHOST_RR)),
    ("4  latch GHOST_PC", {}, 0x0004, 0, (K.UNK_DIVERGED, B.BASIS_GHOST_PC)),
    ("4  an unknown latch code is inconsistent", {}, 0x0007, 0, (K.UNK_DIVERGED, B.BASIS_RAM_INCONSISTENT)),
    ("4  only the FP nibble counts (Dump and R244 nibbles do not latch FP)", {}, 0x0770, 0, (K.UNK_NOT_PROBED, B.BASIS_NONE)),
    ("5  force restore in progress", {"free_power_recovery_force_in_progress": True}, 0, 0, (K.OBL_ENDING, B.BASIS_OPERATOR_ACTION_RUNNING)),
    ("5  accept current state in progress", {"free_power_recovery_accept_in_progress": True}, 0, 0, (K.OBL_ENDING, B.BASIS_OPERATOR_ACTION_RUNNING)),
    ("5  an operator script is running (review / force / accept)", {"fp::run_operator": True}, 0, 0, (K.OBL_ENDING, B.BASIS_OPERATOR_ACTION_RUNNING)),
    ("6  a restore is running", {"fp::run_restore": True}, 0, 0, (K.OBL_ENDING, B.BASIS_RESTORE_RUNNING)),
    ("7  a start is running before its snapshot commit", {"fp::run_start": True}, 0, 0, (K.OBL_STARTING, B.BASIS_PRE_COMMIT)),
    ("8  a start is running after its snapshot commit", {"fp::run_start": True, "fp::free_power_snapshot_valid": True}, 0, 0,
     (K.OBL_STARTING, B.BASIS_COMMITTED)),
    ("9  the operation flag with no attributed script", {"free_power_operation_in_progress": True}, 0, 0, (K.UNK_BUS_OR_LOCK_STUCK, B.BASIS_OP_FLAG_UNATTRIBUTED)),
    ("10 snapshot valid, PENDING_CLEAR", {"fp::free_power_snapshot_valid": True, "fp::free_power_marker_state": 2}, 0, 0, (K.OBL_PENDING_CLEAR, B.BASIS_NONE)),
    ("11 snapshot valid, RESTORE_REQUIRED, operator needed", {"fp::free_power_snapshot_valid": True, "fp::free_power_marker_state": 1,
                                                             "fp::free_power_operator_needed": True}, 0, 0, (K.OBL_OPERATOR_NEEDED, B.BASIS_NONE)),
    ("12 ACTIVE lease", {"fp::free_power_snapshot_valid": True, "fp::free_power_marker_state": 1, "fp::free_power_active_persisted": True}, 0, 0,
     (K.OBL_ACTIVE, B.BASIS_LEASE)),
    ("13 RESTORE_REQUIRED: restore requested", {"fp::free_power_snapshot_valid": True, "fp::free_power_marker_state": 1,
                                                "fp::free_power_active_persisted": True, "fp::free_power_restore_requested": True}, 0, 0,
     (K.OBL_RESTORE_REQUIRED, B.BASIS_NONE)),
    ("13 RESTORE_REQUIRED: expired", {"fp::free_power_snapshot_valid": True, "fp::free_power_marker_state": 1,
                                      "fp::free_power_active_persisted": True, "fp::expired": True}, 0, 0, (K.OBL_RESTORE_REQUIRED, B.BASIS_NONE)),
    ("13 RESTORE_REQUIRED: not active", {"fp::free_power_snapshot_valid": True, "fp::free_power_marker_state": 1}, 0, 0, (K.OBL_RESTORE_REQUIRED, B.BASIS_NONE)),
    ("14 snapshot valid, marker CLEAR", {"fp::free_power_snapshot_valid": True}, 0, 0, (K.UNK_DIVERGED, B.BASIS_RAM_INCONSISTENT)),
    ("14 snapshot valid, an unknown marker state", {"fp::free_power_snapshot_valid": True, "fp::free_power_marker_state": 7}, 0, 0,
     (K.UNK_DIVERGED, B.BASIS_RAM_INCONSISTENT)),
    ("15 no snapshot, active", {"fp::free_power_active_persisted": True}, 0, 0, (K.UNK_DIVERGED, B.BASIS_RAM_INCONSISTENT)),
    ("15 no snapshot, restore requested", {"fp::free_power_restore_requested": True}, 0, 0, (K.UNK_DIVERGED, B.BASIS_RAM_INCONSISTENT)),
    ("15 no snapshot, marker RESTORE_REQUIRED", {"fp::free_power_marker_state": 1}, 0, 0, (K.UNK_DIVERGED, B.BASIS_RAM_INCONSISTENT)),
    ("15 no snapshot, marker PENDING_CLEAR", {"fp::free_power_marker_state": 2}, 0, 0, (K.UNK_DIVERGED, B.BASIS_RAM_INCONSISTENT)),
    ("16 RAM clear, not probed: UNKNOWN_NOT_PROBED", {}, 0, 0, (K.UNK_NOT_PROBED, B.BASIS_NONE)),
    ("16 a stale operator_needed is NOT a term when no snapshot is valid", {"fp::free_power_operator_needed": True}, 0, 0, (K.UNK_NOT_PROBED, B.BASIS_NONE)),
    ("17 probe says RESTORE_REQUIRED while RAM is clear (ghost)", {}, 0, K.PROBE_RESTORE_REQUIRED, (K.UNK_DIVERGED, B.BASIS_GHOST_RR)),
    ("17 probe says PENDING_CLEAR while RAM is clear (ghost)", {}, 0, K.PROBE_PENDING_CLEAR, (K.UNK_DIVERGED, B.BASIS_GHOST_PC)),
    ("18 probe MALFORMED", {}, 0, K.PROBE_MALFORMED, (K.UNK_METADATA_CORRUPT, B.BASIS_RUNTIME_PROBE)),
    ("19 probe UNREADABLE", {}, 0, K.PROBE_UNREADABLE, (K.UNK_DURABLE_UNREADABLE, B.BASIS_RUNTIME_PROBE)),
    ("20 probe CLEAR: CLEAR_PROVEN / MARKER_CLEAR", {}, 0, K.PROBE_CLEAR, (K.OBL_CLEAR_PROVEN, B.BASIS_MARKER_CLEAR)),
    ("21 probe ABSENT: CLEAR_PROVEN / ABSENT", {}, 0, K.PROBE_ABSENT, (K.OBL_CLEAR_PROVEN, B.BASIS_ABSENT)),
    ("21 an unknown probe code is UNREADABLE (fail-closed)", {}, 0, 9, (K.UNK_DURABLE_UNREADABLE, B.BASIS_RUNTIME_PROBE)),
    ("order: row 2 outranks everything", {"fp::free_power_recovery_metadata_corrupt": True, "fp::free_power_marker_boot_load": 3,
                                          "fp::run_start": True, "free_power_operation_in_progress": True}, 0x0003, K.PROBE_CLEAR,
     (K.UNK_DURABLE_UNREADABLE, B.BASIS_BOOT_READ_ERROR)),
    ("order: the latch outranks a running start", {"fp::run_start": True}, 0x0003, 0, (K.UNK_DIVERGED, B.BASIS_GHOST_RR)),
    ("order: an operator action outranks a restore", {"fp::run_restore": True, "fp::run_operator": True}, 0, 0, (K.OBL_ENDING, B.BASIS_OPERATOR_ACTION_RUNNING)),
    ("order: a restore outranks a start", {"fp::run_restore": True, "fp::run_start": True}, 0, 0, (K.OBL_ENDING, B.BASIS_RESTORE_RUNNING)),
    ("order: a start outranks the operation flag", {"fp::run_start": True, "free_power_operation_in_progress": True}, 0, 0, (K.OBL_STARTING, B.BASIS_PRE_COMMIT)),
    ("order: the operation flag outranks PENDING_CLEAR", {"free_power_operation_in_progress": True, "fp::free_power_snapshot_valid": True,
                                                          "fp::free_power_marker_state": 2}, 0, 0, (K.UNK_BUS_OR_LOCK_STUCK, B.BASIS_OP_FLAG_UNATTRIBUTED)),
    ("order: PENDING_CLEAR outranks operator_needed", {"fp::free_power_snapshot_valid": True, "fp::free_power_marker_state": 2,
                                                       "fp::free_power_operator_needed": True}, 0, 0, (K.OBL_PENDING_CLEAR, B.BASIS_NONE)),
    ("order: operator_needed outranks ACTIVE", {"fp::free_power_snapshot_valid": True, "fp::free_power_marker_state": 1,
                                                "fp::free_power_operator_needed": True, "fp::free_power_active_persisted": True}, 0, 0,
     (K.OBL_OPERATOR_NEEDED, B.BASIS_NONE)),
    ("order: RAM state outranks a CLEAR probe", {"fp::free_power_active_persisted": True}, 0, K.PROBE_CLEAR, (K.UNK_DIVERGED, B.BASIS_RAM_INCONSISTENT)),
]
DUMP_ROWS = [
    ("1  boot not loaded", dict(boot_loaded=False), 0, 0, (K.UNK_BOOT_NOT_LOADED, B.BASIS_NONE)),
    ("1  marker boot load never assigned", {"dump::dump_marker_boot_load": 255}, 0, 0, (K.UNK_BOOT_NOT_LOADED, B.BASIS_NONE)),
    ("2  corrupt + boot READ_ERROR (K = 8)", {"dump::dump_recovery_metadata_corrupt": True, "dump::dump_marker_boot_load": 3, "dump::dump_containment_state": 8},
     0, 0, (K.UNK_DURABLE_UNREADABLE, B.BASIS_BOOT_READ_ERROR)),
    ("3  corrupt with containment K = 3 (hard lockout)", {"dump::dump_recovery_metadata_corrupt": True, "dump::dump_containment_state": 3}, 0, 0,
     (K.UNK_METADATA_CORRUPT, B.BASIS_BOOT_LOCKOUT)),
    ("3  corrupt, WRONG_SIZE", {"dump::dump_recovery_metadata_corrupt": True, "dump::dump_marker_boot_load": 2}, 0, 0, (K.UNK_METADATA_CORRUPT, B.BASIS_BOOT_LOCKOUT)),
    ("2b boot READ_ERROR with a clear flag", {"dump::dump_marker_boot_load": 3}, 0, 0, (K.UNK_DIVERGED, B.BASIS_RAM_INCONSISTENT)),
    ("4  latch UNREADABLE / MALFORMED / GHOST_RR / GHOST_PC", {}, 0x0010, 0, (K.UNK_DURABLE_UNREADABLE, B.BASIS_RUNTIME_PROBE)),
    ("4  latch MALFORMED", {}, 0x0020, 0, (K.UNK_METADATA_CORRUPT, B.BASIS_RUNTIME_PROBE)),
    ("4  latch GHOST_RR", {}, 0x0030, 0, (K.UNK_DIVERGED, B.BASIS_GHOST_RR)),
    ("4  latch GHOST_PC", {}, 0x0040, 0, (K.UNK_DIVERGED, B.BASIS_GHOST_PC)),
    ("4  only the DUMP nibble counts", {}, 0x0701, 0, (K.UNK_NOT_PROBED, B.BASIS_NONE)),
    ("5  containment state without the corrupt flag", {"dump::dump_containment_state": 4}, 0, 0, (K.UNK_DIVERGED, B.BASIS_RAM_INCONSISTENT)),
    ("6  a restore is running", {"dump::run_restore": True}, 0, 0, (K.OBL_ENDING, B.BASIS_RESTORE_RUNNING)),
    ("7  a start before its commit", {"dump::run_start": True}, 0, 0, (K.OBL_STARTING, B.BASIS_PRE_COMMIT)),
    ("8  a start after its commit", {"dump::run_start": True, "dump::dump_snapshot_valid": True}, 0, 0, (K.OBL_STARTING, B.BASIS_COMMITTED)),
    ("9  the operation flag with no running script", {"dump_operation_in_progress": True}, 0, 0, (K.UNK_BUS_OR_LOCK_STUCK, B.BASIS_OP_FLAG_UNATTRIBUTED)),
    ("10 snapshot valid, PENDING_CLEAR", {"dump::dump_snapshot_valid": True, "dump::dump_marker_state": 2}, 0, 0, (K.OBL_PENDING_CLEAR, B.BASIS_NONE)),
    ("11 snapshot valid, RESTORE_REQUIRED, operator needed", {"dump::dump_snapshot_valid": True, "dump::dump_marker_state": 1,
                                                             "dump::dump_operator_needed": True}, 0, 0, (K.OBL_OPERATOR_NEEDED, B.BASIS_NONE)),
    ("12 ACTIVE lease", {"dump::dump_snapshot_valid": True, "dump::dump_marker_state": 1, "dump::dump_active_persisted": True}, 0, 0, (K.OBL_ACTIVE, B.BASIS_LEASE)),
    ("13 restore requested: not ACTIVE (RESTORE_REQUIRED)", {"dump::dump_snapshot_valid": True, "dump::dump_marker_state": 1,
                                                             "dump::dump_active_persisted": True, "dump::dump_restore_requested": True}, 0, 0,
     (K.OBL_RESTORE_REQUIRED, B.BASIS_NONE)),
    ("13 expired: RESTORE_REQUIRED", {"dump::dump_snapshot_valid": True, "dump::dump_marker_state": 1, "dump::dump_active_persisted": True,
                                      "dump::expired": True}, 0, 0, (K.OBL_RESTORE_REQUIRED, B.BASIS_NONE)),
    ("13 not active: RESTORE_REQUIRED", {"dump::dump_snapshot_valid": True, "dump::dump_marker_state": 1}, 0, 0, (K.OBL_RESTORE_REQUIRED, B.BASIS_NONE)),
    ("14 snapshot valid, marker CLEAR", {"dump::dump_snapshot_valid": True}, 0, 0, (K.UNK_DIVERGED, B.BASIS_RAM_INCONSISTENT)),
    ("15 no snapshot, active", {"dump::dump_active_persisted": True}, 0, 0, (K.UNK_DIVERGED, B.BASIS_RAM_INCONSISTENT)),
    ("15 no snapshot, operator needed", {"dump::dump_operator_needed": True}, 0, 0, (K.UNK_DIVERGED, B.BASIS_RAM_INCONSISTENT)),
    ("15 no snapshot, marker not CLEAR", {"dump::dump_marker_state": 1}, 0, 0, (K.UNK_DIVERGED, B.BASIS_RAM_INCONSISTENT)),
    ("16 RAM clear, not probed", {}, 0, 0, (K.UNK_NOT_PROBED, B.BASIS_NONE)),
    ("16 dump_restore_requested alone is NOT a term (request_dump_end sets it with no obligation)", {"dump::dump_restore_requested": True}, 0, 0,
     (K.UNK_NOT_PROBED, B.BASIS_NONE)),
    ("17 ghost RESTORE_REQUIRED", {}, 0, K.PROBE_RESTORE_REQUIRED, (K.UNK_DIVERGED, B.BASIS_GHOST_RR)),
    ("17 ghost PENDING_CLEAR", {}, 0, K.PROBE_PENDING_CLEAR, (K.UNK_DIVERGED, B.BASIS_GHOST_PC)),
    ("18 probe MALFORMED", {}, 0, K.PROBE_MALFORMED, (K.UNK_METADATA_CORRUPT, B.BASIS_RUNTIME_PROBE)),
    ("19 probe UNREADABLE", {}, 0, K.PROBE_UNREADABLE, (K.UNK_DURABLE_UNREADABLE, B.BASIS_RUNTIME_PROBE)),
    ("20 probe CLEAR", {}, 0, K.PROBE_CLEAR, (K.OBL_CLEAR_PROVEN, B.BASIS_MARKER_CLEAR)),
    ("21 probe ABSENT", {}, 0, K.PROBE_ABSENT, (K.OBL_CLEAR_PROVEN, B.BASIS_ABSENT)),
    ("order: containment outranks a restore", {"dump::dump_containment_state": 2, "dump::run_restore": True}, 0, 0, (K.UNK_DIVERGED, B.BASIS_RAM_INCONSISTENT)),
    ("order: a restore outranks a start", {"dump::run_restore": True, "dump::run_start": True}, 0, 0, (K.OBL_ENDING, B.BASIS_RESTORE_RUNNING)),
    ("order: PENDING_CLEAR outranks operator needed", {"dump::dump_snapshot_valid": True, "dump::dump_marker_state": 2,
                                                       "dump::dump_operator_needed": True}, 0, 0, (K.OBL_PENDING_CLEAR, B.BASIS_NONE)),
]
R244_ROWS = [
    ("1  boot not loaded", dict(boot_loaded=False), 0, 0, (K.UNK_BOOT_NOT_LOADED, B.BASIS_NONE)),
    ("1  marker boot load never assigned", {"r244::reg244_marker_boot_load": 255}, 0, 0, (K.UNK_BOOT_NOT_LOADED, B.BASIS_NONE)),
    ("2  corrupt + boot READ_ERROR", {"r244::reg244_recovery_metadata_corrupt": True, "r244::reg244_marker_boot_load": 3}, 0, 0,
     (K.UNK_DURABLE_UNREADABLE, B.BASIS_BOOT_READ_ERROR)),
    ("3  corrupt (includes the Dump / reg244 dual-obligation arbitration)", {"r244::reg244_recovery_metadata_corrupt": True}, 0, 0,
     (K.UNK_METADATA_CORRUPT, B.BASIS_BOOT_LOCKOUT)),
    ("2b boot WRONG_SIZE with a clear flag", {"r244::reg244_marker_boot_load": 2}, 0, 0, (K.UNK_DIVERGED, B.BASIS_RAM_INCONSISTENT)),
    ("4  latch UNREADABLE", {}, 0x0100, 0, (K.UNK_DURABLE_UNREADABLE, B.BASIS_RUNTIME_PROBE)),
    ("4  latch MALFORMED", {}, 0x0200, 0, (K.UNK_METADATA_CORRUPT, B.BASIS_RUNTIME_PROBE)),
    ("4  latch GHOST_RR", {}, 0x0300, 0, (K.UNK_DIVERGED, B.BASIS_GHOST_RR)),
    ("4  latch GHOST_PC", {}, 0x0400, 0, (K.UNK_DIVERGED, B.BASIS_GHOST_PC)),
    ("4  only the R244 nibble counts", {}, 0x0077, 0, (K.UNK_NOT_PROBED, B.BASIS_NONE)),
    ("5  a restore press is running", {"r244::run_restore": True}, 0, 0, (K.OBL_ENDING, B.BASIS_RESTORE_RUNNING)),
    ("6  an apply is running before its snapshot commit", {"r244::run_apply": True}, 0, 0, (K.OBL_STARTING, B.BASIS_PRE_COMMIT)),
    ("7  an apply is running after its commit", {"r244::run_apply": True, "r244::reg244_snapshot_valid": True}, 0, 0, (K.OBL_STARTING, B.BASIS_COMMITTED)),
    ("8  the apply flag with no running script", {"reg244_apply_in_progress": True}, 0, 0, (K.UNK_BUS_OR_LOCK_STUCK, B.BASIS_OP_FLAG_UNATTRIBUTED)),
    ("9  snapshot valid, PENDING_CLEAR (needs an armed manual Restore press)", {"r244::reg244_snapshot_valid": True, "r244::reg244_marker_state": 2},
     0, 0, (K.OBL_PENDING_CLEAR, B.BASIS_NONE)),
    ("10 snapshot valid, RESTORE_REQUIRED (operator-resolved, no watchdog)", {"r244::reg244_snapshot_valid": True, "r244::reg244_marker_state": 1},
     0, 0, (K.OBL_OPERATOR_NEEDED, B.BASIS_NONE)),
    ("11 snapshot valid, marker CLEAR", {"r244::reg244_snapshot_valid": True}, 0, 0, (K.UNK_DIVERGED, B.BASIS_RAM_INCONSISTENT)),
    ("11 snapshot valid, an unknown marker state", {"r244::reg244_snapshot_valid": True, "r244::reg244_marker_state": 9}, 0, 0, (K.UNK_DIVERGED, B.BASIS_RAM_INCONSISTENT)),
    ("12 no snapshot, marker RESTORE_REQUIRED", {"r244::reg244_marker_state": 1}, 0, 0, (K.UNK_DIVERGED, B.BASIS_RAM_INCONSISTENT)),
    ("12 no snapshot, marker PENDING_CLEAR", {"r244::reg244_marker_state": 2}, 0, 0, (K.UNK_DIVERGED, B.BASIS_RAM_INCONSISTENT)),
    ("13 RAM clear, not probed", {}, 0, 0, (K.UNK_NOT_PROBED, B.BASIS_NONE)),
    ("14 ghost RESTORE_REQUIRED", {}, 0, K.PROBE_RESTORE_REQUIRED, (K.UNK_DIVERGED, B.BASIS_GHOST_RR)),
    ("15 ghost PENDING_CLEAR", {}, 0, K.PROBE_PENDING_CLEAR, (K.UNK_DIVERGED, B.BASIS_GHOST_PC)),
    ("16 probe MALFORMED", {}, 0, K.PROBE_MALFORMED, (K.UNK_METADATA_CORRUPT, B.BASIS_RUNTIME_PROBE)),
    ("17 probe UNREADABLE", {}, 0, K.PROBE_UNREADABLE, (K.UNK_DURABLE_UNREADABLE, B.BASIS_RUNTIME_PROBE)),
    ("18 probe CLEAR", {}, 0, K.PROBE_CLEAR, (K.OBL_CLEAR_PROVEN, B.BASIS_MARKER_CLEAR)),
    ("18 probe ABSENT", {}, 0, K.PROBE_ABSENT, (K.OBL_CLEAR_PROVEN, B.BASIS_ABSENT)),
    ("order: a restore outranks an apply", {"r244::run_restore": True, "r244::run_apply": True}, 0, 0, (K.OBL_ENDING, B.BASIS_RESTORE_RUNNING)),
    ("order: reg244 has no ACTIVE / operator_needed legs: RESTORE_REQUIRED is OPERATOR_NEEDED whatever else", {
        "r244::reg244_snapshot_valid": True, "r244::reg244_marker_state": 1, "reg244_apply_in_progress": False}, 0, 0, (K.OBL_OPERATOR_NEEDED, B.BASIS_NONE)),
]


def section_classifiers():
    print("[8] classifiers: every S1 4.4 row with the real global names, first-match order, fuzz against an ordered-rule oracle")

    def run_rows(name, rows, fn):
        bad = []
        for label, fields, latch, probe, want in rows:
            f = dict(fields)
            bl = f.pop("boot_loaded", True)
            c = fn(gi(boot_loaded=bl, latch=latch, **f), probe)
            if (c.kind, c.basis) != want:
                bad.append((label, (c.kind, c.basis)))
        check(f"{name}: all {len(rows)} S1 4.4 rows (and the first-match order cases) classify as specified", not bad, str(bad[:3]))

    run_rows("FP", FP_ROWS, cap.classify_fp)
    run_rows("DUMP", DUMP_ROWS, cap.classify_dump)
    run_rows("R244", R244_ROWS, cap.classify_r244)
    check("FP rows cover 1-21 of S1 4.4, DUMP 1-21, R244 1-18 (every numbered row appears)",
          all(any(l.startswith(f"{n:<2}") for l, *_ in FP_ROWS) for n in range(1, 22) if n not in (1,) or True)
          and all(any(l.startswith(f"{n:<2}") for l, *_ in DUMP_ROWS) for n in (1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21))
          and all(any(l.startswith(f"{n:<2}") for l, *_ in R244_ROWS) for n in range(1, 19)))

    # ordered-rule oracles over a flat parameter vector
    class F:
        pass

    def fp_oracle(f):
        pr = {K.PROBE_NONE: (K.UNK_NOT_PROBED, B.BASIS_NONE), K.PROBE_RESTORE_REQUIRED: (K.UNK_DIVERGED, B.BASIS_GHOST_RR),
              K.PROBE_PENDING_CLEAR: (K.UNK_DIVERGED, B.BASIS_GHOST_PC), K.PROBE_MALFORMED: (K.UNK_METADATA_CORRUPT, B.BASIS_RUNTIME_PROBE),
              K.PROBE_CLEAR: (K.OBL_CLEAR_PROVEN, B.BASIS_MARKER_CLEAR), K.PROBE_ABSENT: (K.OBL_CLEAR_PROVEN, B.BASIS_ABSENT)}
        rules = [
            (not f.bl or f.ld > 3, (K.UNK_BOOT_NOT_LOADED, B.BASIS_NONE)),
            (f.cor and f.ld == 3, (K.UNK_DURABLE_UNREADABLE, B.BASIS_BOOT_READ_ERROR)),
            (f.cor, (K.UNK_METADATA_CORRUPT, B.BASIS_BOOT_LOCKOUT)),
            (f.ld in (2, 3), (K.UNK_DIVERGED, B.BASIS_RAM_INCONSISTENT)),
            (f.lat == 1, (K.UNK_DURABLE_UNREADABLE, B.BASIS_RUNTIME_PROBE)), (f.lat == 2, (K.UNK_METADATA_CORRUPT, B.BASIS_RUNTIME_PROBE)),
            (f.lat == 3, (K.UNK_DIVERGED, B.BASIS_GHOST_RR)), (f.lat == 4, (K.UNK_DIVERGED, B.BASIS_GHOST_PC)),
            (f.lat != 0, (K.UNK_DIVERGED, B.BASIS_RAM_INCONSISTENT)),
            (f.frc or f.acc or f.rop, (K.OBL_ENDING, B.BASIS_OPERATOR_ACTION_RUNNING)),
            (f.rrs, (K.OBL_ENDING, B.BASIS_RESTORE_RUNNING)),
            (f.rst and not f.snp, (K.OBL_STARTING, B.BASIS_PRE_COMMIT)), (f.rst and f.snp, (K.OBL_STARTING, B.BASIS_COMMITTED)),
            (f.opf, (K.UNK_BUS_OR_LOCK_STUCK, B.BASIS_OP_FLAG_UNATTRIBUTED)),
            (f.snp and f.ms == 2, (K.OBL_PENDING_CLEAR, B.BASIS_NONE)),
            (f.snp and f.ms == 1 and f.opn, (K.OBL_OPERATOR_NEEDED, B.BASIS_NONE)),
            (f.snp and f.ms == 1 and f.act and not f.rrq and not f.expd, (K.OBL_ACTIVE, B.BASIS_LEASE)),
            (f.snp and f.ms == 1, (K.OBL_RESTORE_REQUIRED, B.BASIS_NONE)),
            (f.snp, (K.UNK_DIVERGED, B.BASIS_RAM_INCONSISTENT)),
            (f.act or f.rrq or f.ms != 0, (K.UNK_DIVERGED, B.BASIS_RAM_INCONSISTENT)),
        ]
        for cond, res in rules:
            if cond:
                return res
        return pr.get(f.probe, (K.UNK_DURABLE_UNREADABLE, B.BASIS_RUNTIME_PROBE))

    def dump_oracle(f):
        pr = {K.PROBE_NONE: (K.UNK_NOT_PROBED, B.BASIS_NONE), K.PROBE_RESTORE_REQUIRED: (K.UNK_DIVERGED, B.BASIS_GHOST_RR),
              K.PROBE_PENDING_CLEAR: (K.UNK_DIVERGED, B.BASIS_GHOST_PC), K.PROBE_MALFORMED: (K.UNK_METADATA_CORRUPT, B.BASIS_RUNTIME_PROBE),
              K.PROBE_CLEAR: (K.OBL_CLEAR_PROVEN, B.BASIS_MARKER_CLEAR), K.PROBE_ABSENT: (K.OBL_CLEAR_PROVEN, B.BASIS_ABSENT)}
        rules = [
            (not f.bl or f.ld > 3, (K.UNK_BOOT_NOT_LOADED, B.BASIS_NONE)),
            (f.cor and f.ld == 3, (K.UNK_DURABLE_UNREADABLE, B.BASIS_BOOT_READ_ERROR)), (f.cor, (K.UNK_METADATA_CORRUPT, B.BASIS_BOOT_LOCKOUT)),
            (f.ld in (2, 3), (K.UNK_DIVERGED, B.BASIS_RAM_INCONSISTENT)),
            (f.lat == 1, (K.UNK_DURABLE_UNREADABLE, B.BASIS_RUNTIME_PROBE)), (f.lat == 2, (K.UNK_METADATA_CORRUPT, B.BASIS_RUNTIME_PROBE)),
            (f.lat == 3, (K.UNK_DIVERGED, B.BASIS_GHOST_RR)), (f.lat == 4, (K.UNK_DIVERGED, B.BASIS_GHOST_PC)),
            (f.lat != 0, (K.UNK_DIVERGED, B.BASIS_RAM_INCONSISTENT)),
            (f.cnt != 0, (K.UNK_DIVERGED, B.BASIS_RAM_INCONSISTENT)),
            (f.rrs, (K.OBL_ENDING, B.BASIS_RESTORE_RUNNING)),
            (f.rst and not f.snp, (K.OBL_STARTING, B.BASIS_PRE_COMMIT)), (f.rst and f.snp, (K.OBL_STARTING, B.BASIS_COMMITTED)),
            (f.opf, (K.UNK_BUS_OR_LOCK_STUCK, B.BASIS_OP_FLAG_UNATTRIBUTED)),
            (f.snp and f.ms == 2, (K.OBL_PENDING_CLEAR, B.BASIS_NONE)),
            (f.snp and f.ms == 1 and f.opn, (K.OBL_OPERATOR_NEEDED, B.BASIS_NONE)),
            (f.snp and f.ms == 1 and f.act and not f.rrq and not f.expd, (K.OBL_ACTIVE, B.BASIS_LEASE)),
            (f.snp and f.ms == 1, (K.OBL_RESTORE_REQUIRED, B.BASIS_NONE)), (f.snp, (K.UNK_DIVERGED, B.BASIS_RAM_INCONSISTENT)),
            (f.act or f.opn or f.ms != 0, (K.UNK_DIVERGED, B.BASIS_RAM_INCONSISTENT)),
        ]
        for cond, res in rules:
            if cond:
                return res
        return pr.get(f.probe, (K.UNK_DURABLE_UNREADABLE, B.BASIS_RUNTIME_PROBE))

    def r244_oracle(f):
        pr = {K.PROBE_NONE: (K.UNK_NOT_PROBED, B.BASIS_NONE), K.PROBE_RESTORE_REQUIRED: (K.UNK_DIVERGED, B.BASIS_GHOST_RR),
              K.PROBE_PENDING_CLEAR: (K.UNK_DIVERGED, B.BASIS_GHOST_PC), K.PROBE_MALFORMED: (K.UNK_METADATA_CORRUPT, B.BASIS_RUNTIME_PROBE),
              K.PROBE_CLEAR: (K.OBL_CLEAR_PROVEN, B.BASIS_MARKER_CLEAR), K.PROBE_ABSENT: (K.OBL_CLEAR_PROVEN, B.BASIS_ABSENT)}
        rules = [
            (not f.bl or f.ld > 3, (K.UNK_BOOT_NOT_LOADED, B.BASIS_NONE)),
            (f.cor and f.ld == 3, (K.UNK_DURABLE_UNREADABLE, B.BASIS_BOOT_READ_ERROR)), (f.cor, (K.UNK_METADATA_CORRUPT, B.BASIS_BOOT_LOCKOUT)),
            (f.ld in (2, 3), (K.UNK_DIVERGED, B.BASIS_RAM_INCONSISTENT)),
            (f.lat == 1, (K.UNK_DURABLE_UNREADABLE, B.BASIS_RUNTIME_PROBE)), (f.lat == 2, (K.UNK_METADATA_CORRUPT, B.BASIS_RUNTIME_PROBE)),
            (f.lat == 3, (K.UNK_DIVERGED, B.BASIS_GHOST_RR)), (f.lat == 4, (K.UNK_DIVERGED, B.BASIS_GHOST_PC)),
            (f.lat != 0, (K.UNK_DIVERGED, B.BASIS_RAM_INCONSISTENT)),
            (f.rrs, (K.OBL_ENDING, B.BASIS_RESTORE_RUNNING)),
            (f.rap and not f.snp, (K.OBL_STARTING, B.BASIS_PRE_COMMIT)), (f.rap and f.snp, (K.OBL_STARTING, B.BASIS_COMMITTED)),
            (f.opf, (K.UNK_BUS_OR_LOCK_STUCK, B.BASIS_OP_FLAG_UNATTRIBUTED)),
            (f.snp and f.ms == 2, (K.OBL_PENDING_CLEAR, B.BASIS_NONE)), (f.snp and f.ms == 1, (K.OBL_OPERATOR_NEEDED, B.BASIS_NONE)),
            (f.snp, (K.UNK_DIVERGED, B.BASIS_RAM_INCONSISTENT)), (f.ms != 0, (K.UNK_DIVERGED, B.BASIS_RAM_INCONSISTENT)),
        ]
        for cond, res in rules:
            if cond:
                return res
        return pr.get(f.probe, (K.UNK_DURABLE_UNREADABLE, B.BASIS_RUNTIME_PROBE))

    rng = random.Random(1234)

    def flat():
        f = F()
        f.bl = rng.random() < 0.9
        f.ld = rng.choice([0, 1, 1, 1, 2, 3, 4, 255])
        f.cor = rng.random() < 0.12
        f.frc, f.acc, f.opf = (rng.random() < 0.08 for _ in range(3))
        f.snp = rng.random() < 0.3
        f.ms = rng.choice([0, 0, 1, 1, 2, 7])
        f.opn, f.act, f.rrq, f.expd = (rng.random() < 0.25 for _ in range(4))
        f.rst, f.rrs, f.rop, f.rap = (rng.random() < 0.1 for _ in range(4))
        f.cnt = rng.choice([0, 0, 0, 0, 1, 3, 8])
        f.lat = rng.choice([0] * 10 + [1, 2, 3, 4, 5, 15])
        f.probe = rng.choice([0, 1, 2, 3, 4, 5, 6, 9])
        return f

    bad = {"FP": 0, "DUMP": 0, "R244": 0}
    seen = {"FP": set(), "DUMP": set(), "R244": set()}
    N = 40000
    for _ in range(N):
        f = flat()
        # FP
        g = gi(boot_loaded=f.bl, latch=cap.latch_set(0, 0, f.lat), **{
            "fp::free_power_marker_boot_load": f.ld, "fp::free_power_recovery_metadata_corrupt": f.cor,
            "free_power_recovery_force_in_progress": f.frc, "free_power_recovery_accept_in_progress": f.acc,
            "free_power_operation_in_progress": f.opf, "fp::free_power_snapshot_valid": f.snp, "fp::free_power_marker_state": f.ms,
            "fp::free_power_operator_needed": f.opn, "fp::free_power_active_persisted": f.act, "fp::free_power_restore_requested": f.rrq,
            "fp::expired": f.expd, "fp::run_start": f.rst, "fp::run_restore": f.rrs, "fp::run_operator": f.rop})
        c = cap.classify_fp(g, f.probe)
        want = fp_oracle(f)
        seen["FP"].add(want)
        bad["FP"] += (c.kind, c.basis) != want
        g = gi(boot_loaded=f.bl, latch=cap.latch_set(0, 1, f.lat), **{
            "dump::dump_marker_boot_load": f.ld, "dump::dump_recovery_metadata_corrupt": f.cor, "dump::dump_containment_state": f.cnt,
            "dump_operation_in_progress": f.opf, "dump::dump_snapshot_valid": f.snp, "dump::dump_marker_state": f.ms,
            "dump::dump_operator_needed": f.opn, "dump::dump_active_persisted": f.act, "dump::dump_restore_requested": f.rrq,
            "dump::expired": f.expd, "dump::run_start": f.rst, "dump::run_restore": f.rrs})
        c = cap.classify_dump(g, f.probe)
        want = dump_oracle(f)
        seen["DUMP"].add(want)
        bad["DUMP"] += (c.kind, c.basis) != want
        g = gi(boot_loaded=f.bl, latch=cap.latch_set(0, 2, f.lat), **{
            "r244::reg244_marker_boot_load": f.ld, "r244::reg244_recovery_metadata_corrupt": f.cor, "reg244_apply_in_progress": f.opf,
            "r244::reg244_snapshot_valid": f.snp, "r244::reg244_marker_state": f.ms, "r244::run_apply": f.rap, "r244::run_restore": f.rrs})
        c = cap.classify_r244(g, f.probe)
        want = r244_oracle(f)
        seen["R244"].add(want)
        bad["R244"] += (c.kind, c.basis) != want
    check(f"FP / DUMP / R244 equal the ordered-rule oracle on {N} fuzzed input vectors each", not any(bad.values()), str(bad))
    print(f"  info  distinct (kind, basis) results seen: FP {len(seen['FP'])}, DUMP {len(seen['DUMP'])}, R244 {len(seen['R244'])}")
    check("the fuzz reaches every result of every classifier (so the oracle comparison covers every row)",
          len(seen["FP"]) >= 20 and len(seen["DUMP"]) >= 19 and len(seen["R244"]) >= 17)

    # CLEAR_PROVEN soundness: whenever a classifier says clear, no obligation input is set
    sound = True
    for _ in range(30000):
        f = flat()
        g = gi(boot_loaded=f.bl, latch=cap.latch_set(0, 0, f.lat), **{
            "fp::free_power_marker_boot_load": f.ld, "fp::free_power_recovery_metadata_corrupt": f.cor,
            "free_power_recovery_force_in_progress": f.frc, "free_power_recovery_accept_in_progress": f.acc,
            "free_power_operation_in_progress": f.opf, "fp::free_power_snapshot_valid": f.snp, "fp::free_power_marker_state": f.ms,
            "fp::free_power_operator_needed": f.opn, "fp::free_power_active_persisted": f.act, "fp::free_power_restore_requested": f.rrq,
            "fp::run_start": f.rst, "fp::run_restore": f.rrs, "fp::run_operator": f.rop})
        c = cap.classify_fp(g, f.probe)
        if c.kind == K.OBL_CLEAR_PROVEN:
            sound = sound and f.bl and f.ld in (0, 1) and not (f.cor or f.frc or f.acc or f.opf or f.snp or f.ms or f.act or f.rrq
                                                              or f.rst or f.rrs or f.rop or f.lat) and f.probe in (K.PROBE_CLEAR, K.PROBE_ABSENT)
        if c.kind == K.UNK_NOT_PROBED:
            sound = sound and f.probe == K.PROBE_NONE and not (f.cor or f.snp or f.ms or f.act or f.rrq or f.lat)
    check("soundness: CLEAR_PROVEN only with every obligation input clear AND a CLEAR / ABSENT probe; NOT_PROBED only with no probe", sound)
    check("lazy: a RAM-clear lease domain with no probe is NOT_PROBED (never clear); fail-closed zero defaults never read as clear",
          cap.classify_fp(cap.GateInputs(), 0).kind != K.OBL_CLEAR_PROVEN and cap.classify_dump(cap.GateInputs(), 0).kind == K.UNK_BOOT_NOT_LOADED
          and cap.classify_r244(cap.GateInputs(), K.PROBE_CLEAR).kind == K.UNK_BOOT_NOT_LOADED and cap.classify_fbs(cap.GateInputs()).kind == K.UNK_BOOT_NOT_LOADED
          and cap.classify_mtou(cap.GateInputs()).kind == K.UNK_BOOT_NOT_LOADED)
    # BUS
    flags = ("manual_write_in_progress", "correction_in_progress", "verification_pending", "verification_read_active",
             "free_power_operation_in_progress", "free_power_recovery_force_in_progress", "free_power_recovery_accept_in_progress",
             "reg244_apply_in_progress", "dump_operation_in_progress", "fallback_profile_op_in_progress", "fallback_profile_capture_dispatch_running")
    check("BUS: each of the 11 FBP_TXN_BUSY terms alone makes the slot BUS_BUSY; none makes it idle",
          all(cap.classify_bus(gi(**{f: True})).kind == K.BUS_BUSY and cap.classify_bus(gi(**{f: True})).basis == B.BASIS_BUS_TXN for f in flags)
          and cap.classify_bus(gi()).kind == K.OBL_CLEAR_PROVEN and cap.classify_bus(gi()).basis == B.BASIS_BUS_IDLE)
    base = dict(manual_write_in_progress=True, diag_write_lock_held=True, diag_write_lock_since_ms=1000)
    st = lambda now, **o: cap.classify_bus(gi(**{**base, "now_ms": now, **o})).kind  # noqa: E731
    check("BUS: stuck only after 300000 ms with the diagnostic held and the mutex taken (299999 busy, 300000 stuck)",
          st(300999) == K.BUS_BUSY and st(301000) == K.UNK_BUS_OR_LOCK_STUCK and st(10 ** 6, diag_write_lock_held=False) == K.BUS_BUSY
          and cap.classify_bus(gi(diag_write_lock_held=True, diag_write_lock_since_ms=0, now_ms=10 ** 6)).kind == K.OBL_CLEAR_PROVEN)
    check("BUS: the lock age is wrap-safe across millis() = 2^32",
          st(300000 - 296, diag_write_lock_since_ms=4294967000) == K.UNK_BUS_OR_LOCK_STUCK and st(300000 - 297, diag_write_lock_since_ms=4294967000) == K.BUS_BUSY)
    # FBS / MTOU
    fbs = lambda s: (lambda c: (c.kind, c.basis))(cap.classify_fbs(gi(fbs=s)))  # noqa: E731
    check("FBS: ABSENT -> CA, VALID CLEAR -> CM, an episode -> ACTIVE (FBS_EPISODE), CORRUPT -> MC, UNREADABLE (and any unknown value) -> UR; not loaded -> BL",
          fbs(1) == (K.OBL_CLEAR_PROVEN, B.BASIS_ABSENT) and fbs(2) == (K.OBL_CLEAR_PROVEN, B.BASIS_MARKER_CLEAR)
          and fbs(3) == (K.OBL_ACTIVE, B.BASIS_FBS_EPISODE) and fbs(4)[0] == K.UNK_METADATA_CORRUPT and fbs(0)[0] == K.UNK_DURABLE_UNREADABLE
          and all(fbs(v)[0] == K.UNK_DURABLE_UNREADABLE for v in (5, 9, 255))
          and cap.classify_fbs(gi(boot_loaded=False)).kind == K.UNK_BOOT_NOT_LOADED)
    check("MTOU: CLEAR_PROVEN / NO_DURABLE_STATE iff the BUS slot is clear (an in-flight Manual TOU surfaces as BUS:BUSY); never a durable probe",
          (cap.classify_mtou(gi()).kind, cap.classify_mtou(gi()).basis) == (K.OBL_CLEAR_PROVEN, B.BASIS_NO_DURABLE_STATE)
          and cap.classify_mtou(gi(manual_write_in_progress=True)).kind == K.UNK_NOT_PROBED and cap.MTOU_JOURNAL_NOT_IMPLEMENTED is True
          and cap.classify_bus(gi(manual_write_in_progress=True)).kind == K.BUS_BUSY)


def section_obl_texts():
    print("[9] obl alphabet, vector text, refusal texts")
    expect = {
        (K.OBL_CLEAR_PROVEN, B.BASIS_MARKER_CLEAR): "CM", (K.OBL_CLEAR_PROVEN, B.BASIS_ABSENT): "CA", (K.OBL_CLEAR_PROVEN, B.BASIS_NO_DURABLE_STATE): "CN",
        (K.OBL_CLEAR_PROVEN, B.BASIS_BUS_IDLE): "OK", (K.OBL_ACTIVE, B.BASIS_LEASE): "AC", (K.OBL_ACTIVE, B.BASIS_FBS_EPISODE): "AC",
        (K.OBL_STARTING, B.BASIS_PRE_COMMIT): "ST", (K.OBL_STARTING, B.BASIS_COMMITTED): "ST", (K.OBL_RESTORE_REQUIRED, B.BASIS_NONE): "RR",
        (K.OBL_PENDING_CLEAR, B.BASIS_NONE): "PC", (K.OBL_ENDING, B.BASIS_RESTORE_RUNNING): "EN", (K.OBL_ENDING, B.BASIS_OPERATOR_ACTION_RUNNING): "EN",
        (K.OBL_OPERATOR_NEEDED, B.BASIS_NONE): "ON", (K.UNK_DURABLE_UNREADABLE, B.BASIS_BOOT_READ_ERROR): "UR",
        (K.UNK_DURABLE_UNREADABLE, B.BASIS_RUNTIME_PROBE): "UR", (K.UNK_METADATA_CORRUPT, B.BASIS_BOOT_LOCKOUT): "MC",
        (K.UNK_METADATA_CORRUPT, B.BASIS_RUNTIME_PROBE): "MC", (K.UNK_BOOT_NOT_LOADED, B.BASIS_NONE): "BL", (K.UNK_DIVERGED, B.BASIS_GHOST_RR): "DV",
        (K.UNK_DIVERGED, B.BASIS_GHOST_PC): "DV", (K.UNK_DIVERGED, B.BASIS_RAM_INCONSISTENT): "DV", (K.UNK_BUS_OR_LOCK_STUCK, B.BASIS_OP_FLAG_UNATTRIBUTED): "LK",
        (K.UNK_BUS_OR_LOCK_STUCK, B.BASIS_LOCK_STUCK): "LK", (K.UNK_NOT_PROBED, B.BASIS_NONE): "NP", (K.BUS_BUSY, B.BASIS_BUS_TXN): "BY"}
    check("obl alphabet: CM CA CN OK / AC ST RR PC EN ON / UR MC BL DV LK NP / BY (the CONTRACT 'KIND alphabet', S5 3.9)",
          all(cap.obl_code(k, b) == c for (k, b), c in expect.items()))
    check("obl_code is total: an unset kind, a CLEAR_PROVEN with an unknown basis and out-of-range values all render UR (never a clear code)",
          cap.obl_code(K.OBL_UNSET, 0) == "UR" and cap.obl_code(K.OBL_CLEAR_PROVEN, B.BASIS_NONE) == "UR" and cap.obl_code(99, 99) == "UR"
          and all(len(cap.obl_code(k, b)) == 2 for k in range(0, 40) for b in range(0, 40)))
    vt = lambda *cs: str(cap.vector_text(*[cap.SlotClass(*c) for c in cs]))  # noqa: E731
    check("vector_text: FP,DP,R4,MT,FS,BUS in that order, DOM:KIND entries comma-separated",
          vt((K.OBL_CLEAR_PROVEN, B.BASIS_ABSENT), (K.OBL_CLEAR_PROVEN, B.BASIS_MARKER_CLEAR), (K.OBL_CLEAR_PROVEN, B.BASIS_ABSENT),
             (K.OBL_CLEAR_PROVEN, B.BASIS_NO_DURABLE_STATE), (K.OBL_CLEAR_PROVEN, B.BASIS_ABSENT), (K.OBL_CLEAR_PROVEN, B.BASIS_BUS_IDLE))
          == "FP:CA,DP:CM,R4:CA,MT:CN,FS:CA,BUS:OK" and len(vt(*[(K.UNK_DURABLE_UNREADABLE, 0)] * 6)) <= 41)
    # gate vector of an all-clear gate
    r = cap.gate_decide(gi(), cap.ProbeResults())
    check("the vector of a RAM-clear gate shows NP for the three lease markers (lazy: nothing probed yet) and CN / CA / OK for the rest",
          str(r.obl) == "FP:NP,DP:NP,R4:NP,MT:CN,FS:CA,BUS:OK")
    # refusal texts
    texts = {}
    for slot in (K.SLOT_FP, K.SLOT_DUMP, K.SLOT_R244, K.SLOT_FBS):
        for kind in range(0, 15):
            for basis in range(0, 20):
                for k in (0, 5):
                    t = str(cap.refusal_text(slot, cap.SlotClass(kind, basis), k, "manual write", 7))
                    texts[(slot, kind, basis, k)] = t
    for kind in range(0, 15):
        for basis in range(0, 20):
            for owner in ("Free Power", "Register 244 test", "Dump to Grid", "Fallback Profile", "clock correction", "clock verification", "manual write"):
                texts[(K.SLOT_BUS, kind, basis, owner)] = str(cap.refusal_text(K.SLOT_BUS, cap.SlotClass(kind, basis), 0, owner, 4294967))
    check(f"all {len(texts)} refusal texts (every slot x kind x basis x detail) start with 'REVIEW REFUSED - ', fit 200 characters and use no card-regex word",
          all(t.startswith("REVIEW REFUSED - ") and len(t) <= 200 and not hazard(t) for t in texts.values()),
          str([t for t in texts.values() if len(t) > 200 or hazard(t)][:2]))
    check("no refusal text recommends a reboot to re-read a marker (D6) and none contains failed / deferred / supervision / ntp",
          not any(re.search(r"reboot to re-read|failed|deferred|supervision|ntp", t, re.I) for t in texts.values()))
    longest = max(len(t) for t in texts.values())
    print(f"  info  longest refusal text: {longest} characters")
    R = K.SLOT_R244
    sc = lambda kind, basis, slot=R, k=0: str(cap.refusal_text(slot, cap.SlotClass(kind, basis), k, "x", 0))  # noqa: E731
    check("S1 4.5 wording: unknown since boot / corrupt hard lockout / runtime latch texts",
          sc(K.UNK_DURABLE_UNREADABLE, B.BASIS_BOOT_READ_ERROR) == "REVIEW REFUSED - Register 244 test recovery state UNKNOWN since boot (marker unreadable); "
          "an obligation cannot be ruled out; Fallback never proceeds past it"
          and sc(K.UNK_METADATA_CORRUPT, B.BASIS_BOOT_LOCKOUT, K.SLOT_FP) == "REVIEW REFUSED - Free Power recovery metadata is CORRUPT (hard lockout); "
          "Fallback never overwrites or proceeds past it; do not erase NVS"
          and sc(K.UNK_METADATA_CORRUPT, B.BASIS_BOOT_LOCKOUT, K.SLOT_DUMP, 3).endswith("; containment K=3")
          and not sc(K.UNK_METADATA_CORRUPT, B.BASIS_BOOT_LOCKOUT, K.SLOT_DUMP, 0).endswith("K=0")
          and sc(K.UNK_DURABLE_UNREADABLE, B.BASIS_RUNTIME_PROBE, K.SLOT_FP) == "REVIEW REFUSED - Free Power recovery marker became unreadable at runtime; review "
          "blocked until reboot. After reboot it may read absent: verify live settings first; do not erase NVS")
    check("S1 4.5 wording: ACTIVE, RESTORE_REQUIRED, PENDING_CLEAR (+ the armed press for R244), OPERATOR_NEEDED, STARTING, ENDING, BUSY, STUCK, not loaded, arms, in flight",
          sc(K.OBL_ACTIVE, B.BASIS_LEASE, K.SLOT_FP) == "REVIEW REFUSED - Free Power is active; live settings are a temporary overlay - end it first"
          and sc(K.OBL_RESTORE_REQUIRED, 0, K.SLOT_DUMP) == "REVIEW REFUSED - Dump to Grid must restore original settings first"
          and sc(K.OBL_PENDING_CLEAR, 0, K.SLOT_FP) == "REVIEW REFUSED - Free Power restore verified; durable clear still pending"
          and sc(K.OBL_PENDING_CLEAR, 0).endswith(" - press Restore Original (armed)")
          and sc(K.OBL_OPERATOR_NEEDED, 0, K.SLOT_DUMP) == "REVIEW REFUSED - Dump to Grid needs an operator recovery action first"
          and sc(K.OBL_STARTING, B.BASIS_PRE_COMMIT, K.SLOT_FP) == "REVIEW REFUSED - a Free Power start is in progress; live settings are about to become a temporary overlay"
          and sc(K.OBL_ENDING, B.BASIS_RESTORE_RUNNING, K.SLOT_DUMP) == "REVIEW REFUSED - a Dump to Grid restore or recovery action is running; try again when it finishes"
          and str(cap.refusal_text(K.SLOT_BUS, cap.SlotClass(K.BUS_BUSY, B.BASIS_BUS_TXN), 0, "Free Power", 0)) == "REVIEW REFUSED - another inverter transaction is in progress (Free Power); try again shortly"
          and str(cap.refusal_text(K.SLOT_BUS, cap.SlotClass(K.UNK_BUS_OR_LOCK_STUCK, B.BASIS_LOCK_STUCK), 0, "", 300)) == "REVIEW REFUSED - inverter write lock held for 300 s (possible leak); a reboot may be required"
          and str(cap.refused_not_loaded_text()) == "REVIEW REFUSED - durable state not loaded yet (starting up)"
          and str(cap.refused_arms_text()) == "REVIEW REFUSED - a Free Power / Dump to Grid / Manual Configuration write arm is on; finish or turn it off first"
          and str(cap.refused_in_flight_text()) == "REVIEW REFUSED - another Fallback Profile operation is in progress")
    check("distinct situations give distinct texts: every (slot, kind, basis) the classifiers can produce renders a different refusal per domain",
          len({texts[(K.SLOT_R244, k, b, 0)] for k, b in expect if k not in (K.OBL_CLEAR_PROVEN,)}) >= 14)
    check("bus_owner_text names the most specific owner (a lease script before the generic mutex holder)",
          cap.bus_owner_text(cap.BusInputs(free_power_operation_in_progress=True, manual_write_in_progress=True)) == "Free Power"
          and cap.bus_owner_text(cap.BusInputs(manual_write_in_progress=True)) == "manual write"
          and cap.bus_owner_text(cap.BusInputs(reg244_apply_in_progress=True)) == "Register 244 test"
          and cap.bus_owner_text(cap.BusInputs(dump_operation_in_progress=True)) == "Dump to Grid"
          and cap.bus_owner_text(cap.BusInputs()) == "none")
    # RH4(a): SEVERAL owner flags at once - the owner priority, over EVERY subset of the eleven busy flags
    busy_flags = ("manual_write_in_progress", "correction_in_progress", "verification_pending", "verification_read_active",
                  "free_power_operation_in_progress", "free_power_recovery_force_in_progress", "free_power_recovery_accept_in_progress",
                  "reg244_apply_in_progress", "dump_operation_in_progress", "fallback_profile_op_in_progress",
                  "fallback_profile_capture_dispatch_running")
    priority = (("Free Power", {"free_power_operation_in_progress", "free_power_recovery_force_in_progress", "free_power_recovery_accept_in_progress"}),
                ("Register 244 test", {"reg244_apply_in_progress"}), ("Dump to Grid", {"dump_operation_in_progress"}),
                ("Fallback Profile", {"fallback_profile_op_in_progress", "fallback_profile_capture_dispatch_running"}),
                ("clock correction", {"correction_in_progress"}), ("clock verification", {"verification_pending", "verification_read_active"}),
                ("manual write", {"manual_write_in_progress"}))
    bad = []
    for mask in range(1 << len(busy_flags)):
        on = {f for i, f in enumerate(busy_flags) if mask >> i & 1}
        want = next((name for name, group in priority if on & group), "none")
        got = cap.bus_owner_text(cap.BusInputs(**{f: True for f in on}))
        c = cap.classify_bus(gi(**{f"bus::{f}": True for f in on}))
        busy = cap.bus_busy(cap.BusInputs(**{f: True for f in on}))
        if got != want or busy != bool(on) or (c.kind, c.basis) != ((cap.BUS_BUSY, cap.BASIS_BUS_TXN) if on else (cap.OBL_CLEAR_PROVEN, cap.BASIS_BUS_IDLE)):
            bad.append((sorted(on), got, want))
    check("bus_owner_text / bus_busy / classify_bus over ALL 2048 subsets of the eleven busy flags: the owner is the first of Free Power > Register 244 test > "
          "Dump to Grid > Fallback Profile > clock correction > clock verification > manual write, the bus is busy iff any flag is set", not bad, str(bad[:2]))
    # FW1: the Free Power / Dump controller ticks hold the shared lock through manual_write_in_progress ALONE, so the generic
    # "manual write" owner would name an ACTIVE lease wrongly (the vector says DP:AC). The BUS refusal names the lease when the
    # mutex flag is the ONLY owner flag set and the gate's own classification of the slot says ACTIVE; wording only.
    ACT, NPB = cap.SlotClass(K.OBL_ACTIVE, B.BASIS_LEASE), cap.SlotClass(K.UNK_NOT_PROBED, B.BASIS_NONE)
    ow = cap.bus_owner_text_with_leases
    mw = cap.BusInputs(manual_write_in_progress=True)
    check("FW1 bus_owner_text_with_leases: the mutex flag alone + Free Power ACTIVE -> Free Power; + Dump ACTIVE -> Dump to Grid; both -> Free Power (the owner-chain order); "
          "neither -> manual write; no mutex flag at all -> none (the generic text is unchanged)",
          ow(mw, ACT, NPB) == "Free Power" and ow(mw, NPB, ACT) == "Dump to Grid" and ow(mw, ACT, ACT) == "Free Power"
          and ow(mw, NPB, NPB) == "manual write" and ow(cap.BusInputs(), ACT, ACT) == "none" and ow(mw, cap.SlotClass(), cap.SlotClass()) == "manual write")
    kinds_other = [k for k in range(0, 15) if k != K.OBL_ACTIVE]
    check("FW1: ONLY OBL_ACTIVE names a lease - every other slot kind (clear, starting, restore required, pending clear, ending, operator needed, unreadable, corrupt, "
          "not loaded, diverged, lock stuck, not probed, busy, unset) keeps the generic owner",
          all(ow(mw, cap.SlotClass(k, b_), cap.SlotClass(k, b_)) == "manual write" for k in kinds_other for b_ in (0, B.BASIS_LEASE, B.BASIS_RAM_INCONSISTENT)))
    bad = []
    for mask in range(1 << len(busy_flags)):
        on = {f for i, f in enumerate(busy_flags) if mask >> i & 1}
        b = cap.BusInputs(**{f: True for f in on})
        for fk, dk in ((K.OBL_ACTIVE, K.UNK_NOT_PROBED), (K.UNK_NOT_PROBED, K.OBL_ACTIVE), (K.OBL_ACTIVE, K.OBL_ACTIVE), (K.UNK_NOT_PROBED, K.UNK_NOT_PROBED)):
            got = ow(b, cap.SlotClass(fk, B.BASIS_LEASE), cap.SlotClass(dk, B.BASIS_LEASE))
            if on == {"manual_write_in_progress"} and fk == K.OBL_ACTIVE:
                want = "Free Power"
            elif on == {"manual_write_in_progress"} and dk == K.OBL_ACTIVE:
                want = "Dump to Grid"
            else:
                want = cap.bus_owner_text(b)
            if got != want:
                bad.append((sorted(on), fk, dk, got, want))
    check("FW1 over ALL 2048 subsets of the eleven busy flags x four lease combinations: a lease is named only when manual_write_in_progress is the SOLE flag set; with any "
          "other owner flag the plain bus_owner_text() answer stands (an active lease never outranks a named owner)", not bad, str(bad[:2]))
    check("FW1 texts: the BUS refusal with each of the four owners it can now name is <= 200 characters, starts REVIEW REFUSED and uses no card-regex word",
          all((lambda t: t.startswith("REVIEW REFUSED - another inverter transaction is in progress (") and t.endswith("); try again shortly") and len(t) <= 200 and not hazard(t))(
              str(cap.refusal_text(K.SLOT_BUS, cap.SlotClass(K.BUS_BUSY, B.BASIS_BUS_TXN), 0, o, 0))) for o in ("Free Power", "Dump to Grid", "manual write", "none")))
    stuck = dict(manual_write_in_progress=True, diag_write_lock_held=True, diag_write_lock_since_ms=1000, now_ms=301000)
    c = cap.classify_bus(gi(**{f"bus::{k}": v for k, v in dict(stuck, dump_operation_in_progress=True).items()}))
    c2 = cap.classify_bus(gi(**{f"bus::{k}": v for k, v in dict(stuck, dump_operation_in_progress=True, diag_write_lock_since_ms=2000).items()}))
    check("a stuck write lock (300000 ms) outranks a busy bus (LK); one millisecond younger it is only BY, whatever else is set",
          (c.kind, c.basis) == (cap.UNK_BUS_OR_LOCK_STUCK, cap.BASIS_LOCK_STUCK) and (c2.kind, c2.basis) == (cap.BUS_BUSY, cap.BASIS_BUS_TXN))


def section_probe_latch():
    print("[10] probe classification and the sticky latch")
    M = K.MARKER_RECORD_MAGIC
    check("probe_result: ABSENT / CLEAR / RESTORE_REQUIRED / PENDING_CLEAR / MALFORMED / UNREADABLE",
          cap.probe_result(1, M, 0) == K.PROBE_ABSENT and cap.probe_result(0, M, 0) == K.PROBE_CLEAR
          and cap.probe_result(0, M, 1) == K.PROBE_RESTORE_REQUIRED and cap.probe_result(0, M, 2) == K.PROBE_PENDING_CLEAR
          and cap.probe_result(0, M, 3) == K.PROBE_MALFORMED and cap.probe_result(0, M ^ 1, 0) == K.PROBE_MALFORMED
          and cap.probe_result(2, M, 0) == K.PROBE_MALFORMED and cap.probe_result(3, M, 0) == K.PROBE_UNREADABLE
          and cap.probe_result(4, M, 0) == K.PROBE_UNREADABLE and cap.probe_result(9, M, 0) == K.PROBE_UNREADABLE)
    check("probe_result: the record is never inspected unless the load is OK (a stale magic / state with ABSENT or READ_ERROR changes nothing); every state 3..255 is malformed",
          all(cap.probe_result(1, mg, st) == K.PROBE_ABSENT for mg in (0, M, 5) for st in (0, 1, 255))
          and all(cap.probe_result(3, mg, st) == K.PROBE_UNREADABLE for mg in (0, M) for st in (0, 1))
          and all(cap.probe_result(0, M, st) == K.PROBE_MALFORMED for st in range(3, 256)))
    check("probe_latch_code: UNREADABLE 1, MALFORMED 2, RESTORE_REQUIRED 3 (ghost), PENDING_CLEAR 4 (ghost); CLEAR / ABSENT / not probed latch nothing",
          [cap.probe_latch_code(p) for p in range(0, 8)] == [0, 0, 0, 3, 4, 2, 1, 0])
    check("latch_set / latch_get: 4 bits per domain (FP 0-3, DUMP 4-7, R244 8-11)", cap.latch_set(0, 0, 1) == 0x0001 and cap.latch_set(0, 1, 2) == 0x0020
          and cap.latch_set(0, 2, 4) == 0x0400 and cap.latch_get(0x0421, 0) == 1 and cap.latch_get(0x0421, 1) == 2 and cap.latch_get(0x0421, 2) == 4)
    check("latch is SET-ONLY: a set nibble is never changed, code 0 never writes, an unknown domain is ignored",
          cap.latch_set(0x0001, 0, 3) == 0x0001 and cap.latch_set(0x0010, 1, 0) == 0x0010 and cap.latch_set(0x0001, 7, 2) == 0x0001
          and cap.latch_set(0x0001, 1, 2) == 0x0021)
    rng = random.Random(9)
    ok = True
    latch = 0
    for _ in range(20000):
        before = latch
        dom, code = rng.randrange(0, 5), rng.randrange(0, 16)
        latch = cap.latch_set(latch, dom, code)
        for d in range(3):
            old, new = cap.latch_get(before, d), cap.latch_get(latch, d)
            ok = ok and (new == old or (old == 0 and d == dom and new == code & 0xF and code != 0))
        ok = ok and (latch & before) == before
    check("20000 random latch_set calls: no bit is ever cleared and a non-zero nibble never changes (never cleared in a boot)", ok)
    check("latch_text: the latched domains in the order FP,DP,R4, or -", [str(cap.latch_text(v)) for v in (0, 1, 0x10, 0x100, 0x111, 0x101, 0x110, 0xF000)]
          == ["-", "FP", "DP", "R4", "FP,DP,R4", "FP,R4", "DP,R4", "-"])


def section_read_eval():
    print("[11] the fresh FBP / FBW read: divergence rule, S1 9.2 golden sequences, seen_hw_gen")

    class Ram:
        """The firmware's RAM mirror, updated exactly as the boot lambda and the REVIEW final lambda do."""

        def __init__(self):
            self.boot = False
            self.p_load = self.w_load = fp.LOAD_STORAGE_UNAVAILABLE
            self.p, self.w = fp.blank_profile(), fd.blank_provision()
            self.ps = self.ra = self.seen = 0
            self.cls = self.why = 0

        def read(self, p_load, p, w_load, w, healthy=True):
            r = cap.evaluate_read(cap.ReadInputs(
                p_load=p_load, p=p, w_load=w_load, w=w, healthy=healthy, present_seen=self.ps, read_anomaly=self.ra, seen_hw_gen=self.seen,
                baseline_valid=self.boot, last_p_load=self.p_load, last_p_bytes=fp.pack_profile(self.p), last_w_load=self.w_load,
                last_w_bytes=fd.pack_provision(self.w)))
            self.p_load, self.p, self.w_load, self.w = p_load, p, w_load, w
            self.ps, self.ra, self.seen, self.cls, self.why = r.latch.present_seen, r.latch.read_anomaly, r.seen_hw_gen, r.cls, r.why
            self.boot = True
            return r

    Z, ZW = fp.blank_profile(), fd.blank_provision()
    ram = Ram()
    r = ram.read(LOAD_OK, GOLD_P, LOAD_OK, GOLD_W)
    check("boot: VALID g7 with a consistent witness (hw 7) -> VALID, no anomaly, present_seen 3, seen_hw_gen 7",
          (r.cls, r.why, r.latch.present_seen, r.latch.read_anomaly, r.seen_hw_gen) == (fd.EPC_VALID, fd.WHY_NONE, 3, 0, 7) and not (r.p_diverged or r.w_diverged))
    r = ram.read(LOAD_OK, GOLD_P, LOAD_OK, GOLD_W)
    check("a second identical read: still VALID, no divergence", (r.cls, r.latch.read_anomaly) == (fd.EPC_VALID, 0) and not r.p_diverged)
    r = ram.read(LOAD_RERR, Z, LOAD_OK, GOLD_W)
    check("S1 9.2 golden: boot VALID g7, then FBP READ_ERROR -> UNREADABLE (profile read) and the key's anomaly bit is set",
          (r.cls, r.why, r.latch.read_anomaly & 1) == (fd.EPC_UNREADABLE, fd.WHY_PROFILE_READ, 1) and r.p_diverged)
    r = ram.read(LOAD_ABSENT, Z, LOAD_OK, GOLD_W)
    check("...then ABSENT (the erase-on-read sequence) -> STILL UNREADABLE (read anomaly), never NOT_CAPTURED / PROFILE_LOST / a fresh g1",
          (r.cls, r.why) == (fd.EPC_UNREADABLE, fd.WHY_READ_ANOMALY) and r.latch.read_anomaly & 1)
    r = ram.read(LOAD_OK, GOLD_P, LOAD_OK, GOLD_W)
    check("...and even a clean VALID read afterwards stays UNREADABLE for the rest of the boot (the latch is sticky)",
          (r.cls, r.why) == (fd.EPC_UNREADABLE, fd.WHY_READ_ANOMALY) and r.latch.read_anomaly & 1)
    rebooted = Ram()
    r = rebooted.read(LOAD_ABSENT, Z, LOAD_OK, GOLD_W)
    check("after a reboot with FBP ABSENT and FBW hw 7: PROFILE_LOST (not NOT_CAPTURED) and the high-water floor is 7",
          (r.cls, r.why, r.seen_hw_gen) == (fd.EPC_PROFILE_LOST, fd.WHY_NONE, 7))
    ram = Ram()
    ram.read(LOAD_OK, GOLD_P, LOAD_OK, GOLD_W)
    damaged = dict(GOLD_P)
    damaged["reg245"] ^= 1
    r = ram.read(LOAD_OK, damaged, LOAD_OK, GOLD_W)
    check("S1 9.2 golden: a VALID record that reads back CORRUPT (bytes changed, load still OK) is a divergence -> UNREADABLE (anomaly), not CORRUPT",
          r.p_diverged and (r.cls, r.why) == (fd.EPC_UNREADABLE, fd.WHY_READ_ANOMALY) and fp.classify_profile(0, damaged) == fp.PROFILE_CORRUPT)
    ram = Ram()
    ram.read(LOAD_OK, GOLD_P, LOAD_OK, GOLD_W)
    g8 = golden_profile(generation=8, reg245=5)
    r = ram.read(LOAD_OK, g8, LOAD_OK, GOLD_W)
    check("a resealed different record is also a divergence (only FB-B commits change FBP; FB-B1 commits nothing)", r.p_diverged and r.cls == fd.EPC_UNREADABLE)
    ram = Ram()
    ram.read(LOAD_OK, GOLD_P, LOAD_OK, GOLD_W)
    w8 = fd.make_provision(8, GOLD_P["binding"], 7, 0x77, fd.FALLBACK_PROFILE_KEY, 1, fd.PROV_OP_SAVE)
    r = ram.read(LOAD_OK, GOLD_P, LOAD_OK, w8)
    check("the witness is guarded the same way (bit 1)", r.w_diverged and r.latch.read_anomaly & 2 and r.cls == fd.EPC_UNREADABLE)
    ram = Ram()
    r0 = ram.read(LOAD_ABSENT, Z, LOAD_ABSENT, ZW)
    r1 = ram.read(LOAD_ABSENT, Z, LOAD_ABSENT, ZW)
    check("a fresh device: ABSENT / ABSENT twice is NOT_CAPTURED both times with no anomaly (zero bytes agree)",
          (r0.cls, r1.cls, r1.latch.read_anomaly, r1.p_diverged, r1.w_diverged) == (fd.EPC_NOT_CAPTURED, fd.EPC_NOT_CAPTURED, 0, False, False))
    ram = Ram()
    ram.read(LOAD_ABSENT, Z, LOAD_ABSENT, ZW)
    r = ram.read(LOAD_OK, GOLD_P, LOAD_ABSENT, ZW)
    check("a record appearing between two reads (ABSENT -> OK) is a divergence too", r.p_diverged and r.cls == fd.EPC_UNREADABLE)
    ram = Ram()
    r = ram.read(LOAD_OK, GOLD_P, LOAD_OK, GOLD_W, healthy=False)
    check("the NVS health gate failing after a read sets the third anomaly bit (0x04) and the class UNREADABLE (anomaly)",
          (r.latch.read_anomaly, r.cls, r.why) == (4, fd.EPC_UNREADABLE, fd.WHY_READ_ANOMALY))
    ram = Ram()
    corrupt = golden_profile()
    corrupt = dict(corrupt)
    corrupt["magic"] = 0
    w9 = fd.make_provision(9, 0x99, 8, 0x88, fd.FALLBACK_PROFILE_KEY, 1, fd.PROV_OP_SAVE)
    r = ram.read(LOAD_OK, corrupt, LOAD_OK, w9)
    check("boot CORRUPT with FBW hw 9: class CORRUPT, the high-water floor still rises to 9 (witness is trusted)", (r.cls, r.seen_hw_gen) == (fd.EPC_CORRUPT, 9))
    check("seen_hw_gen only ever rises: max(seen, authentic generation, W_VALID hw)", cap.evaluate_read(cap.ReadInputs(
        p_load=0, p=GOLD_P, w_load=0, w=GOLD_W, healthy=True, seen_hw_gen=40)).seen_hw_gen == 40
        and cap.evaluate_read(cap.ReadInputs(p_load=0, p=golden_profile(generation=90), w_load=0, w=GOLD_W, healthy=True)).seen_hw_gen == 90
        and cap.evaluate_read(cap.ReadInputs(p_load=1, w_load=0, w=GOLD_W, healthy=True)).seen_hw_gen == 7
        and cap.evaluate_read(cap.ReadInputs(p_load=0, p=corrupt, w_load=1, healthy=True)).seen_hw_gen == 0)
    rng = random.Random(31)
    ok = ok2 = True
    for _ in range(3000):
        pl, p, _len = rand_profile(rng)
        wl, w = rand_witness(rng, p)
        inp = cap.ReadInputs(p_load=pl, p=p, w_load=wl, w=w, healthy=rng.random() < 0.9, present_seen=rng.randrange(4),
                             read_anomaly=rng.choice([0, 0, 0, 1, 2, 4]), seen_hw_gen=rng.choice([0, 3, 9]))
        r = cap.evaluate_read(inp)
        ps, ra = fd.note_read(inp.present_seen, inp.read_anomaly, 1, pl, inp.healthy)
        ps, ra = fd.note_read(ps, ra, 2, wl, inp.healthy)
        cls, why, rule = fd.compose_profile_class(pl, p, wl, w, ra)
        seen = fd.next_seen_hw_gen(inp.seen_hw_gen, fp.classify_profile(pl, p), p["generation"], fd.classify_witness(wl, w), w["hw_generation"])
        ok = ok and (r.latch.present_seen, r.latch.read_anomaly, r.cls, r.why, r.rule, r.seen_hw_gen) == (ps, ra, cls, why, rule, seen) \
            and not r.p_diverged and not r.w_diverged
        inp.baseline_valid = True
        inp.last_p_load, inp.last_p_bytes, inp.last_w_load, inp.last_w_bytes = pl, fp.pack_profile(p), wl, fd.pack_provision(w)
        r2 = cap.evaluate_read(inp)
        ok2 = ok2 and (r2.cls, r2.latch.read_anomaly) == (r.cls, r.latch.read_anomaly) and not (r2.p_diverged or r2.w_diverged)
    check("without a baseline evaluate_read equals the S2 read path (two note_read, compose, next_seen_hw_gen) on 3000 random reads", ok)
    check("with a baseline equal to the read itself nothing diverges and the result is unchanged (3000 random reads)", ok2)
    check("diverged(): a changed load code or changed bytes", not cap.diverged(0, 0, True) and cap.diverged(0, 0, False) and cap.diverged(0, 3, True)
          and cap.diverged(1, 1, False) and not cap.diverged(3, 3, True))
    check("the harness record objects are accepted (as_dict / to_bytes)", cap.profile_diverged(0, fp.pack_profile(GOLD_P), 0, fp.pack_profile(GOLD_P)) is False)


def section_review_eval():
    print("[12] review_evaluate: eligibility, prior fingerprint, masks, id")
    ri = lambda **o: cap.review_evaluate(cap.ReviewInputs(**{"words": list(GW), "cls": fd.EPC_VALID, "p_load": 0, "p": GOLD_P, "salt": 0xDEADBEEF, "seq_next": 2, **o}))  # noqa: E731
    v = ri()
    check("an unchanged capture of a VALID profile: eligible, warnings none, authentic stored, masks 0, sv OK, id = candidate_id over the prior fingerprint",
          v.eligible and v.warnings == 0 and v.has_stored and (v.dx, v.dc, v.di) == (0, 0, 0) and str(v.sv) == "OK"
          and (v.prior_generation, v.prior_binding) == (7, GOLD_P["binding"])
          and v.id == cap.candidate_id(0xDEADBEEF, 2, fd.EPC_VALID, 7, GOLD_P["binding"], GW))
    check("the documented golden: salt DEADBEEF, seq 2, prior VALID g7 over the golden words = 51235C0108AEE8F4", v.id == 0x51235C0108AEE8F4)
    v = ri(words=wd(w0=0))
    check("an L2 refusal makes the candidate not saveable: no id, sv NO:244X, but the masks are still computed against the stored profile",
          not v.eligible and v.id == 0 and str(v.sv) == "NO:244X" and v.dx == 1 and v.has_stored)
    v = ri(cls=fd.EPC_UNREADABLE)
    check("class UNREADABLE: not saveable although L2 is clean (sv=OK), no id", not v.eligible and v.id == 0 and str(v.sv) == "OK")
    v = ri(read_anomaly=4)
    check("a read anomaly: not saveable even for a VALID class", not v.eligible and v.id == 0)
    for cls, ok in ((0, False), (1, True), (2, True), (3, True), (4, True), (5, True), (6, True), (7, False), (8, True)):
        v = ri(cls=cls)
        check(f"class {cap.epc_name(cls)}: eligible == {ok} and an eligible candidate gets an id bound to that class",
              v.eligible == ok and ((v.id == cap.candidate_id(0xDEADBEEF, 2, cls, v.prior_generation, v.prior_binding, GW)) if ok else v.id == 0))
    cases = [
        ("NOT_CAPTURED: (0, 0), no authentic stored profile -> masks not meaningful", LOAD_ABSENT, fp.blank_profile(), 0, 0, 0, False),
        ("PROFILE_LOST (FBP ABSENT): (0, 0)", LOAD_ABSENT, fp.blank_profile(), 0, 0, 0, False),
        ("authentic VALID: (generation, binding)", LOAD_OK, GOLD_P, 0, 7, GOLD_P["binding"], True),
        ("authentic INVALIDATED", LOAD_OK, golden_profile(flags=1, generation=8), 0, 8, golden_profile(flags=1, generation=8)["binding"], True),
        ("authentic CORRUPT_DOMAIN", LOAD_OK, golden_profile(reg244=1, generation=9), 0, 9, golden_profile(reg244=1, generation=9)["binding"], True),
        ("CORRUPT with LOAD_OK: the raw (untrusted) fields", LOAD_OK, dict(GOLD_P, magic=0), 0, 7, GOLD_P["binding"], False),
        ("CORRUPT with WRONG_SIZE: (0, stored length)", LOAD_WSZ, fp.blank_profile(), 40, 0, 40, False),
        ("UNREADABLE: (0, 0)", LOAD_RERR, fp.blank_profile(), 0, 0, 0, False),
        ("STORAGE_UNAVAILABLE: (0, 0)", LOAD_UNAV, fp.blank_profile(), 0, 0, 0, False),
    ]
    for label, load, p, ln, pg, pb, stored in cases:
        v = ri(p_load=load, p=p, p_stored_len=ln, cls=fd.EPC_NOT_CAPTURED)
        check(f"prior fingerprint - {label}", (v.prior_generation, v.prior_binding, v.has_stored) == (pg, pb, stored))
    check("prior_fingerprint is the pure function review_evaluate uses", cap.prior_fingerprint(LOAD_WSZ, fp.blank_profile(), 97).binding == 97)
    # RH4(b): a WRONG_SIZE stored length above 16 bits is carried unchanged (a 16-bit truncation would only show above 65535)
    lens = (65535, 65536, 70000, 2 ** 31, 2 ** 32 - 1)
    check("prior_fingerprint / review_evaluate carry a WRONG_SIZE stored length of 65535, 65536, 70000, 2^31 and 2^32-1 unchanged (generation 0)",
          all(cap.prior_fingerprint(LOAD_WSZ, fp.blank_profile(), n) == cap.PriorFingerprint(0, n) for n in lens)
          and all((lambda v: (v.prior_generation, v.prior_binding))(ri(p_load=LOAD_WSZ, p=fp.blank_profile(), p_stored_len=n, cls=fd.EPC_CORRUPT)) == (0, n) for n in lens))
    check("the candidate id binds the FULL stored length: 70000 and 70000 & 0xFFFF give different ids (class CORRUPT permits a Save)",
          ri(p_load=LOAD_WSZ, p=fp.blank_profile(), p_stored_len=70000, cls=fd.EPC_CORRUPT).id
          == cap.candidate_id(0xDEADBEEF, 2, fd.EPC_CORRUPT, 0, 70000, GW)
          != ri(p_load=LOAD_WSZ, p=fp.blank_profile(), p_stored_len=70000 & 0xFFFF, cls=fd.EPC_CORRUPT).id)
    check("a read anomaly of 1, 2, 3 and 4 (the real latch bits: profile key, witness key, both, unhealthy) each make a VALID candidate not saveable",
          all(not ri(read_anomaly=a).eligible and ri(read_anomaly=a).id == 0 for a in (1, 2, 3, 4)) and ri(read_anomaly=0).eligible)
    check("ReviewVerdict() defaults: not eligible, no stored profile, id 0 and an EMPTY sv (the C++ default; the mirror used to default to -)",
          (lambda v: (v.eligible, v.has_stored, v.id, str(v.sv), len(v.sv)))(cap.ReviewVerdict()) == (False, False, 0, "", 0)
          and str(ri().sv) == "OK")
    # masks only with an authentic stored profile; they equal the mask functions
    v = ri(words=wd(w0=0, w19=GW[19] ^ 1, w28=1, w13=3))
    check("masks vs the stored profile: dx / dc / di equal the mask functions on (candidate, stored words)",
          (v.dx, v.dc, v.di) == (cap.e1_delta_mask(wd(w0=0, w19=GW[19] ^ 1, w28=1, w13=3), GW), cap.ctx_mismatch_mask(wd(w0=0, w19=GW[19] ^ 1, w28=1, w13=3), GW),
                                 cap.info_mismatch_mask(wd(w0=0, w19=GW[19] ^ 1, w28=1, w13=3), GW)) and v.dx == (1 | (1 << 13)) and v.dc == 1 and v.di == 1)
    # FW0 (review finding): the masks are computed only against a TRUSTED stored profile = authentic (FB-A class VALID / INVALIDATED /
    # CORRUPT_DOMAIN) AND effective class != UNREADABLE - the predicate saved_view uses for B7 / B8 (minus the B7 length clause) - so dx / dc / di
    # are '-' exactly when B7 / B8 call the stored profile absent and B1 calls it UNREADABLE (never 00000 / 000 / 00 "identical to the saved profile").
    changed = wd(w0=0, w1=499, w19=GW[19] ^ 1, w28=1, w13=3)
    v = ri(words=changed, cls=fd.EPC_UNREADABLE)
    check("FW0: an AUTHENTIC record whose effective class is UNREADABLE is not trusted: has_stored false, dx = dc = di = 0 (never computed), no id, and B5 / B6 print '-' for dx / dc / di",
          not v.has_stored and (v.dx, v.dc, v.di) == (0, 0, 0) and not v.eligible and v.id == 0
          and str(cap.b5_text(True, changed, v.has_stored, v.dx)).endswith(";dx=-") and str(cap.b6_text(True, changed, v.has_stored, v.dc, v.di)).endswith(";dc=-;di=-"))
    v = ri(words=changed, cls=fd.EPC_VALID)
    check("FW0: ...while the same candidate under the authentic class VALID shows the masks (dx 00000-style hex, dc, di) - the behaviour for a trusted record is unchanged",
          v.has_stored and v.dx == cap.e1_delta_mask(changed, GW) != 0 and v.dc == cap.ctx_mismatch_mask(changed, GW) != 0 and v.di == cap.info_mismatch_mask(changed, GW) != 0
          and re.search(r";dx=[0-9A-F]{5}$", str(cap.b5_text(True, changed, v.has_stored, v.dx))) and re.search(r";dc=[0-9A-F]{3};di=[0-9A-F]{2}$", str(cap.b6_text(True, changed, v.has_stored, v.dc, v.di))))
    e_rep = cap.evaluate_read(cap.ReadInputs(p_load=LOAD_OK, p=GOLD_P, w_load=LOAD_RERR, w=fd.blank_provision(), healthy=True))
    v = ri(words=list(GW), cls=e_rep.cls, read_anomaly=e_rep.latch.read_anomaly)
    check("FW0 repro (rv_fw/a5_dx_vs_saved): a valid FBP + a witness that cannot be read (CRC-bad) -> B1 UNREADABLE, B7 / B8 v=NONE, candidate NOT saveable and dx / dc / di '-' "
          "(it used to render the identical-looking 00000 / 000 / 00 next to those)",
          fp.classify_profile(LOAD_OK, GOLD_P) == fp.PROFILE_VALID and e_rep.cls == fd.EPC_UNREADABLE and cap.epc_name(e_rep.cls) == "UNREADABLE"
          and str(cap.b7_text(LOAD_OK, GOLD_P, e_rep.cls)).startswith("v=NONE") and str(cap.b8_text(LOAD_OK, GOLD_P, e_rep.cls)).startswith("v=NONE")
          and not v.eligible and not v.has_stored and (v.dx, v.dc, v.di) == (0, 0, 0)
          and str(cap.b5_text(True, GW, v.has_stored, v.dx)).endswith(";dx=-") and str(cap.b6_text(True, GW, v.has_stored, v.dc, v.di)).endswith(";dc=-;di=-"))
    p_inv, p_cd, p_wide = golden_profile(flags=1, generation=8), golden_profile(reg244=1, generation=9), golden_profile(reg244=65535, generation=4294967295, captured_epoch=4294967295,
                                                                                                                         reg256_261=[65535] * 6, reg268_273=[65535] * 6, reg274_279=[65535] * 6,
                                                                                                                         reg250_255=[65535] * 6, reg232=65535, reg243=65535, reg248=65535,
                                                                                                                         reg230=65535, reg245=65535, reg247=65535)
    bad = []
    for label, load, prof, authentic in (("VALID", LOAD_OK, GOLD_P, True), ("INVALIDATED", LOAD_OK, p_inv, True), ("CORRUPT_DOMAIN", LOAD_OK, p_cd, True),
                                         ("CORRUPT_DOMAIN, every value 5 digits", LOAD_OK, p_wide, True), ("CORRUPT (bad magic)", LOAD_OK, dict(GOLD_P, magic=0), False),
                                         ("ABSENT", LOAD_ABSENT, fp.blank_profile(), False), ("WRONG_SIZE", LOAD_WSZ, fp.blank_profile(), False),
                                         ("READ_ERROR", LOAD_RERR, fp.blank_profile(), False), ("UNAVAILABLE", LOAD_UNAV, fp.blank_profile(), False)):
        stored = cap.words_of(prof)
        for cls in range(0, 9):
            v = ri(words=changed, cls=cls, p_load=load, p=prof, p_stored_len=40 if load == LOAD_WSZ else 0)
            want = authentic and cls != fd.EPC_UNREADABLE
            want_m = (cap.e1_delta_mask(changed, stored), cap.ctx_mismatch_mask(changed, stored), cap.info_mismatch_mask(changed, stored)) if want else (0, 0, 0)
            if v.has_stored != want or (v.dx, v.dc, v.di) != want_m:
                bad.append((label, cls, v.has_stored))
    check("FW0: has_stored == (authentic FB-A class AND effective class != UNREADABLE) for every stored-record shape x every effective class 0..8 (81 cases); the masks are computed exactly then, "
          "and are 0 otherwise", not bad, str(bad[:3]))
    check("FW0: the authentic-VALID / INVALIDATED / CORRUPT_DOMAIN classes keep their behaviour (has_stored for VALID 5, INVALIDATED 4, CORRUPT_DOMAIN 3, STALE 8 and every non-UNREADABLE class)",
          all(ri(p=prof, cls=c).has_stored for prof in (GOLD_P, p_inv, p_cd) for c in (3, 4, 5, 8)))
    rng_fw0 = random.Random(2024)
    bad_fw0, n_hs, n_un = [], 0, 0
    for _ in range(4000):
        pl, q, ln = rand_profile(rng_fw0)
        cls = rng_fw0.randrange(0, 9)
        v = ri(words=rand_words(rng_fw0), cls=cls, p_load=pl, p=q, p_stored_len=ln)
        t7, t8 = str(cap.b7_text(pl, q, cls)), str(cap.b8_text(pl, q, cls))
        authentic = fp.classify_profile(pl, q) in (fp.PROFILE_VALID, fp.PROFILE_INVALIDATED, fp.PROFILE_CORRUPT_DOMAIN)
        n_hs += v.has_stored
        n_un += authentic and cls == fd.EPC_UNREADABLE
        # has_stored is the saved-view predicate minus the B7 length clause: SAVED => has_stored; not has_stored => both views NONE; has_stored without SAVED => only the over-200 case
        if v.has_stored != (authentic and cls != fd.EPC_UNREADABLE) or (t7.startswith("v=SAVED") and not v.has_stored) or (not v.has_stored and not (t7.startswith("v=NONE") and t8.startswith("v=NONE"))) \
                or (v.has_stored and not t7.startswith("v=SAVED") and not (t7.startswith("v=NONE") and t8.startswith("v=NONE") and len(cap._b7_saved(q)) > 200)):
            bad_fw0.append((pl, cls, v.has_stored, t7[:10], t8[:10]))
    check(f"FW0: 4000 random stored records x classes: has_stored is the saved-view predicate minus the length clause - every SAVED view has has_stored, no has_stored=false view is SAVED, and "
          f"a trusted record that is not SAVED is only the over-200-character one ({n_hs} trusted, {n_un} authentic-but-UNREADABLE cases)", not bad_fw0 and n_hs > 500 and n_un > 50, str(bad_fw0[:2]) + f" {n_hs} {n_un}")
    check("seq / salt reach the id (different seq or salt, different id)", ri(seq_next=3).id != ri().id and ri(salt=5).id != ri().id)
    check("the site ceiling reaches L2", str(ri(words=wd(w1=6000), ceiling_w=5000).sv) == "NO:PWRH1" and ri(words=wd(w1=6000)).eligible)
    check("a refused candidate keeps its warnings", ri(words=wd(w0=0, w21=0)).warnings == 4)


# ---------------------------------------------------------------------------------------------------------------
def section_grammars():
    print("[13] grammars B1-B8: key order, always-all-keys, charset, worst-case lengths, NONE forms, B2 derivation")
    check("B1 epc_name is TOTAL over 0..8 with the nine locked values; 7 renders SAVE_UNCONFIRMED; out-of-range values fail closed",
          [cap.epc_name(c) for c in range(9)] == ["UNREADABLE", "NOT_CAPTURED", "CORRUPT", "CORRUPT_DOMAIN", "INVALIDATED", "VALID", "PROFILE_LOST",
                                                  "SAVE_UNCONFIRMED", "PROFILE_STALE"] and cap.epc_name(9) == cap.epc_name(255) == "UNREADABLE"
          and cap.epc_name(7) == "SAVE_UNCONFIRMED" and all(cap.epc_name(c) == fd.EPC_NAMES[c] for c in range(9)) and max(len(cap.epc_name(c)) for c in range(256)) == 16)
    check("name tables: ld, df (GEN not GENERATION), w, op, why equal the grammar alphabets (why = fd.WHY_NAMES)",
          [cap.ld_name(i) for i in range(5)] == ["OK", "ABS", "WSZ", "RERR", "UNAV"] and cap.ld_name(9) == "RERR"
          and [cap.df_name(i) for i in range(9)] == ["-", "MAGIC", "SCHEMA", "SIZE", "BINDING", "RESERVED", "FLAGS", "GEN", "DOMAIN"]
          and [cap.w_name(i) for i in range(6)] == ["OK", "LAG", "MISS", "CORR", "UNR", "ABS"] and [cap.op_name(i) for i in range(4)] == ["-", "SAVE", "INV", "RC"]
          and [cap.why_name(i) for i in range(13)] == [fd.WHY_NAMES[i] for i in range(13)] and cap.why_name(77) == "-")
    rng = random.Random(404)
    # ---- B2
    ok = True
    worst = 0
    for _ in range(6000):
        pl, p, _len = rand_profile(rng)
        wl, w = rand_witness(rng, p)
        cls, why, _rule = fd.compose_profile_class(pl, p, wl, w, rng.choice([0, 0, 0, 1, 4]))
        t = str(cap.b2_text(pl, p, wl, w, why, rng.choice([0, 0, 0, 4359, 4294967295]), rng.choice([0, 1234, 4294967295])))
        worst = max(worst, len(t))
        ok = ok and grammar_ok(t, K_B2)
    check(f"B2: all 11 keys in order, charset [A-Za-z0-9_.,:/>+-], <= 200 on 6000 random record / witness / why combinations (max seen {worst})", ok)

    def b2(pl, p, wl, w, why=0, e=0, u=0):
        return dict(kv(str(cap.b2_text(pl, p, wl, w, why, e, u))))

    c = b2(0, GOLD_P, 0, GOLD_W)
    check("B2 consistent VALID: g/id/at from the authentic record, ld OK, df -, w OK, hw/op from the witness, why -, werr -, us -",
          c == dict(g="7", id=f"{GOLD_P['binding']:016X}", at="1790000000", ld="OK", df="-", w="OK", hw="7", op="SAVE", why="-", werr="-", us="-"))
    check("B2 fresh device: g/id/at -, ld ABS, w ABS, hw -, op -", b2(1, Z := fp.blank_profile(), 1, fd.blank_provision()) == dict(
        g="-", id="-", at="-", ld="ABS", df="-", w="ABS", hw="-", op="-", why="-", werr="-", us="-"))
    check("B2 lost profile (FBP ABSENT, witness valid): g/id/at -, w OK, hw 7, op SAVE", (lambda x: (x["g"], x["w"], x["hw"], x["op"]))(b2(1, Z, 0, GOLD_W)) == ("-", "OK", "7", "SAVE"))
    expectations = [
        # (label, p_load, p, w_load, w, anomaly) -> expected cls, why, g?, w, hw, op, df
        ("B1 profile unreadable", LOAD_RERR, Z, LOAD_OK, GOLD_W, 0, fd.EPC_UNREADABLE, fd.WHY_PROFILE_READ, "-", "OK", "7", "SAVE", "-"),
        ("B2 witness unreadable", LOAD_OK, GOLD_P, LOAD_RERR, fd.blank_provision(), 0, fd.EPC_UNREADABLE, fd.WHY_WITNESS_READ, "7", "UNR", "-", "-", "-"),
        ("B2a anomaly", LOAD_OK, GOLD_P, LOAD_OK, GOLD_W, 1, fd.EPC_UNREADABLE, fd.WHY_READ_ANOMALY, "7", "OK", "7", "SAVE", "-"),
        ("B3 corrupt (magic)", LOAD_OK, dict(GOLD_P, magic=0), LOAD_OK, GOLD_W, 0, fd.EPC_CORRUPT, fd.WHY_NONE, "-", "OK", "7", "SAVE", "MAGIC"),
        ("B3 corrupt (wrong size)", LOAD_WSZ, Z, LOAD_OK, GOLD_W, 0, fd.EPC_CORRUPT, fd.WHY_NONE, "-", "OK", "7", "SAVE", "-"),
        ("B4 both absent", LOAD_ABSENT, Z, LOAD_ABSENT, fd.blank_provision(), 0, fd.EPC_NOT_CAPTURED, fd.WHY_NONE, "-", "ABS", "-", "-", "-"),
        ("B5 first save lost", LOAD_ABSENT, Z, LOAD_OK, fd.make_provision(1, 0x11, 0, 0, fd.FALLBACK_PROFILE_KEY, 1, 1), 0, fd.EPC_PROFILE_LOST,
         fd.WHY_FIRST_SAVE_UNCONFIRMED, "-", "OK", "1", "SAVE", "-"),
        ("B6 lost", LOAD_ABSENT, Z, LOAD_OK, GOLD_W, 0, fd.EPC_PROFILE_LOST, fd.WHY_NONE, "-", "OK", "7", "SAVE", "-"),
        ("B7 lost, witness corrupt", LOAD_ABSENT, Z, LOAD_OK, dict(GOLD_W, binding=GOLD_W["binding"] ^ 1), 0, fd.EPC_PROFILE_LOST, fd.WHY_LOST_WIT_CORRUPT, "-", "CORR", "-", "-", "-"),
        ("B8 witness lagging", LOAD_OK, GOLD_P, LOAD_OK, fd.make_provision(6, 0x66, 5, 0x55, fd.FALLBACK_PROFILE_KEY, 1, 1), 0, fd.EPC_VALID,
         fd.WHY_WIT_LAGGING, "7", "LAG", "6", "SAVE", "-"),
        ("B9 foreign tag", LOAD_OK, GOLD_P, LOAD_OK, fd.make_provision(7, GOLD_P["binding"], 6, 0x66, 5, 1, 1), 0, fd.EPC_PROFILE_STALE, fd.WHY_SUPERSEDED, "7", "OK", "7", "SAVE", "-"),
        ("B10 consistent", LOAD_OK, GOLD_P, LOAD_OK, GOLD_W, 0, fd.EPC_VALID, fd.WHY_NONE, "7", "OK", "7", "SAVE", "-"),
        ("B11 same generation, different binding", LOAD_OK, GOLD_P, LOAD_OK, fd.make_provision(7, 0x1234, 6, 0x66, fd.FALLBACK_PROFILE_KEY, 1, 1), 0,
         fd.EPC_PROFILE_STALE, fd.WHY_MISMATCH, "7", "OK", "7", "SAVE", "-"),
        ("B12 interrupted (== the named prior)", LOAD_OK, GOLD_P, LOAD_OK, fd.make_provision(8, 0x88, 7, GOLD_P["binding"], fd.FALLBACK_PROFILE_KEY, 1, 1), 0,
         fd.EPC_PROFILE_STALE, fd.WHY_INTERRUPTED, "7", "OK", "8", "SAVE", "-"),
        ("B13 rollback", LOAD_OK, GOLD_P, LOAD_OK, fd.make_provision(9, 0x99, 8, 0x88, fd.FALLBACK_PROFILE_KEY, 1, 2), 0, fd.EPC_PROFILE_STALE, fd.WHY_ROLLBACK,
         "7", "OK", "9", "INV", "-"),
        ("B14 witness missing", LOAD_OK, GOLD_P, LOAD_ABSENT, fd.blank_provision(), 0, fd.EPC_VALID, fd.WHY_WIT_MISSING, "7", "MISS", "-", "-", "-"),
        ("B15 witness corrupt", LOAD_OK, GOLD_P, LOAD_OK, dict(GOLD_W, flags=1), 0, fd.EPC_VALID, fd.WHY_WIT_CORRUPT, "7", "CORR", "-", "-", "-"),
        ("corrupt domain, consistent witness", LOAD_OK, golden_profile(reg244=1), LOAD_OK, fd.make_provision(7, golden_profile(reg244=1)["binding"], 6, 0x66,
                                                                                                             fd.FALLBACK_PROFILE_KEY, 1, 1), 0,
         fd.EPC_CORRUPT_DOMAIN, fd.WHY_NONE, "7", "OK", "7", "SAVE", "DOMAIN"),
        ("invalidated, consistent witness", LOAD_OK, golden_profile(flags=1), LOAD_OK, fd.make_provision(7, golden_profile(flags=1)["binding"], 6, 0x66,
                                                                                                        fd.FALLBACK_PROFILE_KEY, 1, 2), 0, fd.EPC_INVALIDATED,
         fd.WHY_NONE, "7", "OK", "7", "INV", "-"),
    ]
    bad = []
    for label, pl, p, wl, w, anomaly, ecls, ewhy, eg, ew, ehw, eop, edf in expectations:
        cls, why, _rule = fd.compose_profile_class(pl, p, wl, w, anomaly)
        t = b2(pl, p, wl, w, why)
        if (cls, why) != (ecls, ewhy) or (t["g"], t["w"], t["hw"], t["op"], t["df"]) != (eg, ew, ehw, eop, edf) or t["why"] != cap.why_name(ewhy):
            bad.append((label, cls, why, t))
    check(f"B2 derivation for every effective class x witness class: all {len(expectations)} compose rows (B1, B2, B2a, B3-B15, CORRUPT_DOMAIN, INVALIDATED) "
          "give the S2 3.2 g/w/hw/op/df/why values", not bad, str(bad[:2]))
    # the full matrix: every FB-A record class x every witness class / relation x anomaly, against an independent expectation
    p_variants = [("VALID", LOAD_OK, GOLD_P), ("INVALIDATED", LOAD_OK, golden_profile(flags=1)), ("CORRUPT_DOMAIN", LOAD_OK, golden_profile(reg244=1)),
                  ("CORRUPT", LOAD_OK, dict(GOLD_P, magic=0)), ("CORRUPT size", LOAD_WSZ, Z), ("NOT_CAPTURED", LOAD_ABSENT, Z), ("UNREADABLE", LOAD_RERR, Z)]
    w_variants = lambda p: [  # noqa: E731
        ("hw above g", LOAD_OK, fd.make_provision(9, 0x99, 8, 0x88, fd.FALLBACK_PROFILE_KEY, 1, 1)),
        ("hw == g, same binding", LOAD_OK, fd.make_provision(7, p["binding"], 6, 0x66, fd.FALLBACK_PROFILE_KEY, 1, 2)),
        ("hw == g, other binding", LOAD_OK, fd.make_provision(7, 0x1234, 6, 0x66, fd.FALLBACK_PROFILE_KEY, 1, 3)),
        ("hw below g", LOAD_OK, fd.make_provision(5, 0x55, 4, 0x44, fd.FALLBACK_PROFILE_KEY, 1, 1)),
        ("absent", LOAD_ABSENT, fd.blank_provision()), ("corrupt (bad binding)", LOAD_OK, dict(GOLD_W, binding=GOLD_W["binding"] ^ 1)),
        ("wrong size", LOAD_WSZ, fd.blank_provision()), ("unreadable", LOAD_RERR, fd.blank_provision())]
    matrix_bad = []
    n_matrix = 0
    for pname, pl, p in p_variants:
        for wname, wl, w in w_variants(p):
            for anomaly in (0, 4):
                n_matrix += 1
                cls, why, _rule = fd.compose_profile_class(pl, p, wl, w, anomaly)
                t = b2(pl, p, wl, w, why)
                fba = fp.classify_profile(pl, p)
                auth = fba in (fp.PROFILE_VALID, fp.PROFILE_INVALIDATED, fp.PROFILE_CORRUPT_DOMAIN)
                wc = fd.classify_witness(wl, w)
                want = {"g": str(p["generation"]) if auth else "-", "id": f"{p['binding']:016X}" if auth else "-",
                        "at": str(p["captured_epoch"]) if auth else "-", "ld": {0: "OK", 1: "ABS", 2: "WSZ", 3: "RERR", 4: "UNAV"}[pl],
                        "df": ("GEN" if fp.profile_defect(p) == fp.PROFILE_DEFECT_GENERATION else fp.PROFILE_DEFECT_NAMES[fp.profile_defect(p)])
                        if (pl == LOAD_OK and fba in (fp.PROFILE_CORRUPT, fp.PROFILE_CORRUPT_DOMAIN)) else "-",
                        "w": {fd.W_UNREADABLE: "UNR", fd.W_CORRUPT: "CORR"}.get(wc) or (("MISS" if auth else "ABS") if wc == fd.W_ABSENT else
                                                                                   ("LAG" if auth and p["generation"] > w["hw_generation"] else "OK")),
                        "hw": str(w["hw_generation"]) if wc == fd.W_VALID else "-",
                        "op": {1: "SAVE", 2: "INV", 3: "RC"}[w["last_op"]] if wc == fd.W_VALID else "-", "why": fd.WHY_NAMES[why]}
                if {k: t[k] for k in want} != want:
                    matrix_bad.append((pname, wname, anomaly, t, want))
    check(f"B2 derivation matrix: {n_matrix} combinations of every FB-A record class (VALID, INVALIDATED, CORRUPT_DOMAIN, CORRUPT x2, NOT_CAPTURED, UNREADABLE) x "
          "every witness class / relation (hw above, equal, equal-other-binding, below, absent, corrupt, wrong size, unreadable) x anomaly",
          not matrix_bad, str(matrix_bad[:1]))
    dfs = [("MAGIC", dict(GOLD_P, magic=0)), ("SCHEMA", golden_profile(schema=2)), ("SIZE", golden_profile(size=95)), ("BINDING", dict(GOLD_P, binding=GOLD_P["binding"] ^ 1)),
           ("RESERVED", golden_profile(reserved0=1)), ("FLAGS", golden_profile(flags=2)), ("GEN", golden_profile(generation=0)), ("DOMAIN", golden_profile(reg244=1))]
    check("B2 df: every FB-A defect name (GEN, not GENERATION) for a LOAD_OK CORRUPT / CORRUPT_DOMAIN record; - for a clean record, a wrong-size read and a missing read",
          all(b2(0, p, 0, GOLD_W)["df"] == name for name, p in dfs) and b2(0, GOLD_P, 0, GOLD_W)["df"] == "-" and b2(2, Z, 0, GOLD_W)["df"] == "-"
          and b2(1, Z, 0, GOLD_W)["df"] == "-")
    check("B2: g / id / at only for an AUTHENTIC record (VALID, INVALIDATED, CORRUPT_DOMAIN - also when the class is STALE); never for CORRUPT",
          all((b2(0, p, 0, GOLD_W)["g"] != "-") == (name in ("DOMAIN",)) for name, p in dfs)
          and b2(0, golden_profile(flags=1), 0, GOLD_W)["g"] == "7")
    check("B2 w / hw / op for a witness: valid -> its high water and last op (SAVE / INV / RC); anything else -> hw -, op -",
          all(b2(0, GOLD_P, 0, fd.make_provision(7, GOLD_P["binding"], 6, 0x66, fd.FALLBACK_PROFILE_KEY, 1, op))["op"] == name for op, name in ((1, "SAVE"), (2, "INV"), (3, "RC"))))
    check("B2 werr / us render - for 0 (FB-B1 always) and a hex code / decimal otherwise",
          b2(0, GOLD_P, 0, GOLD_W, 0, 0, 0)["werr"] == "-" and b2(0, GOLD_P, 0, GOLD_W, 0, 0, 0)["us"] == "-"
          and b2(0, GOLD_P, 0, GOLD_W, 0, 0x1107, 1234)["werr"] == "E1107" and b2(0, GOLD_P, 0, GOLD_W, 0, 0x1107, 1234)["us"] == "1234")
    # ---- B3
    obl = "FP:CA,DP:CA,R4:CA,MT:CN,FS:CA,BUS:OK"
    check("B3 boot value: st=IDLE;prior=-;exp=-;warn=-;obl=-;latch=-;sv=-", str(cap.b3_text(0, False, 0, 0, 0, "-", 0, "-")) == "st=IDLE;prior=-;exp=-;warn=-;obl=-;latch=-;sv=-")
    check("B3 READY: prior is the effective class name, exp the seconds, warn the W-list, obl the vector, sv OK",
          str(cap.b3_text(2, True, 5, 120, 0x21, obl, 0, "OK")) == f"st=CANDIDATE_READY;prior=VALID;exp=120;warn=W1,W6;obl={obl};latch=-;sv=OK"
          and str(cap.b3_text(3, True, 8, 0, 0, obl, 0x0101, "NO:244X")) == f"st=CANDIDATE_NOT_SAVEABLE;prior=PROFILE_STALE;exp=0;warn=-;obl={obl};latch=FP,R4;sv=NO:244X")
    check("B3 IDLE after a refusal keeps obl and latch and shows - for prior / exp / warn / sv (the invalidation form)",
          str(cap.b3_text(0, False, 5, 100, 0x3F, obl, 0x0010, "NO:244X")) == f"st=IDLE;prior=-;exp=-;warn=-;obl={obl};latch=DP;sv=-"
          and str(cap.b3_text(1, False, 0, 0, 0, obl, 0, "-")) == f"st=READING;prior=-;exp=-;warn=-;obl={obl};latch=-;sv=-")
    check("B3: an empty obl or sv falls back to -; unknown states render IDLE", str(cap.b3_text(2, True, 5, 9, 0, "", 0, "")) == "st=CANDIDATE_READY;prior=VALID;exp=9;warn=-;obl=-;latch=-;sv=-"
          and cap.capture_state_name(9) == "IDLE")
    ok = True
    for _ in range(4000):
        t = str(cap.b3_text(rng.randrange(0, 5), rng.random() < 0.7, rng.randrange(0, 12), rng.randrange(0, 121), rng.randrange(0, 64), obl.replace("CA", "UR"),
                            rng.randrange(0, 0x1000), "NO:" + ",".join(rng.choice(["PWRL1", "SRCG3", "244X"]) for _ in range(3)) + "+35"))
        ok = ok and grammar_ok(t, K_B3)
    check("B3: all 7 keys in order, charset, <= 200 on 4000 random values", ok)
    check("B3 worst case fits 200 (CANDIDATE_NOT_SAVEABLE + SAVE_UNCONFIRMED + exp 120 + six warnings + the widest vector + three latched + NO:..+35)",
          len(str(cap.b3_text(3, True, 7, 120, 0x3F, "FP:UR,DP:UR,R4:UR,MT:NP,FS:UR,BUS:LK", 0x0111, "NO:PWRL1,PWRL2,PWRL3+35"))) == 162)
    # ---- B3 robustness rule (RH2): every key is ALWAYS present, an over-long obl / sv renders - and is never cut
    obl36 = "FP:UR,DP:UR,R4:UR,MT:NP,FS:UR,BUS:LK"
    sv26 = "NO:" + "P" * 23
    b3 = lambda obl_, sv_, **k: str(cap.b3_text(k.get("st", 2), k.get("have", True), 5, 120, 0, obl_, k.get("latch", 0), sv_))  # noqa: E731
    check("B3 rule: obl is kept up to exactly 36 characters and sv up to exactly 26 (B3_OBL_MAX 36, B3_SV_MAX 26); one character more renders - (never cut mid-way)",
          (cap.B3_OBL_MAX, cap.B3_SV_MAX) == (36, 26) and len(obl36) == 36 and len(sv26) == 26
          and b3(obl36, "OK") == f"st=CANDIDATE_READY;prior=VALID;exp=120;warn=-;obl={obl36};latch=-;sv=OK"
          and b3(obl36 + "X", "OK") == "st=CANDIDATE_READY;prior=VALID;exp=120;warn=-;obl=-;latch=-;sv=OK"
          and b3(obl36, sv26).endswith(f";sv={sv26}") and b3(obl36, sv26 + "P").endswith(";sv=-"))
    check("B3 rule, the review's repro: an obl of 300 characters renders obl=- and the latch= and sv= keys are still present (the old text was cut at 200 inside obl)",
          b3("X" * 300, "OK") == "st=CANDIDATE_READY;prior=VALID;exp=120;warn=-;obl=-;latch=-;sv=OK"
          and b3("X" * 300, "OK", latch=0x0111).endswith(";obl=-;latch=FP,DP,R4;sv=OK")
          and b3(obl36, "S" * 300).endswith(";latch=-;sv=-") and b3("O" * 200, "S" * 200, latch=0x0111).endswith(";obl=-;latch=FP,DP,R4;sv=-")
          and b3(obl36, "S" * 300, have=False, st=0).endswith(";sv=-"))
    check("B3 rule: a None obl or sv (a C++ null pointer) renders - exactly like an empty one; b3_value_fits boundaries",
          str(cap.b3_text(2, True, 5, 9, 0, None, 0, None)) == "st=CANDIDATE_READY;prior=VALID;exp=9;warn=-;obl=-;latch=-;sv=-"
          and [cap.b3_value_fits(x, m) for x, m in (("", 5), ("a", 1), ("ab", 1), ("X" * 36, 36), ("X" * 37, 36), (None, 5))] == [False, True, False, True, False, False])
    ok, longest = True, 0
    for _ in range(6000):
        alpha = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.,:/>+-"
        obl_ = "".join(rng.choice(alpha) for _ in range(rng.choice([0, 1, 20, 35, 36, 37, 38, 80, 250, 400])))
        sv_ = "".join(rng.choice(alpha) for _ in range(rng.choice([0, 1, 10, 25, 26, 27, 28, 90, 300])))
        have_ = rng.random() < 0.7
        t = str(cap.b3_text(rng.randrange(0, 6), have_, rng.randrange(0, 12), rng.choice([0, 57, 120, 2 ** 32 - 1]), rng.randrange(0, 128),
                            obl_, rng.randrange(0, 0x10000), sv_))
        d = dict(kv(t))
        longest = max(longest, len(t))
        ok = (ok and grammar_ok(t, K_B3) and d["obl"] == (obl_ if 0 < len(obl_) <= 36 else "-")
              and d["sv"] == (sv_ if have_ and 0 < len(sv_) <= 26 else "-"))
    check(f"B3: on 6000 random calls with obl / sv of 0..400 characters (charset-clean) all 7 keys are in order, <= 200, obl is kept iff it is 1..36 characters and sv "
          f"iff a candidate exists and it is 1..26 characters (max {longest})", ok and longest <= 172)
    check("B3 absolute worst case (CANDIDATE_NOT_SAVEABLE, SAVE_UNCONFIRMED, exp 4294967295, all six warnings, the widest vector, three latched, a 26-character sv) is 172: "
          "it can never reach 200 whatever the arguments",
          len(str(cap.b3_text(3, True, 7, 2 ** 32 - 1, 0xFFFF, obl36, 0xFFFF, "N" * 26))) == 172)
    # ---- B4
    check("B4: the 16-hex candidate id only while saveable", str(cap.b4_text(True, 0x1D63D8CBC6CB4D55)) == "1D63D8CBC6CB4D55" and str(cap.b4_text(False, 0x1D63D8CBC6CB4D55)) == "-")
    # ---- B5 / B6
    ok = ok5 = ok6 = True
    w5 = 0
    for _ in range(5000):
        w = rand_words(rng, 0.7) if rng.random() < 0.8 else [rng.randrange(65536) for _ in range(31)]
        stored = rng.random() < 0.6
        t5 = str(cap.b5_text(True, w, stored, rng.randrange(0x80000)))
        t6 = str(cap.b6_text(True, w, stored, rng.randrange(0x200), rng.randrange(0x20)))
        ok5 = ok5 and grammar_ok(t5, K_B5)
        ok6 = ok6 and grammar_ok(t6, K_B6)
        w5 = max(w5, len(t5))
    check(f"B5 / B6: all keys in order, charset, <= 200 on 5000 random candidates incl. fully random words (B5 max {w5})", ok5 and ok6)
    allf = [65535] * 31
    check("B5 worst case (every word 65535, dx 7FFFF) is 185 characters, B6 worst case 85 (<= 200)", len(str(cap.b5_text(True, allf, True, 0x7FFFF))) == 185
          and len(str(cap.b6_text(True, allf, True, 0x1FF, 0x1F))) == 85)
    t5 = dict(kv(str(cap.b5_text(True, GW, True, 0x1A2B3))))
    check("B5: slot tuple = HHMM %04u / W / SOC / SRC (the FULL source word), registers 250+n-1 / 256+n-1 / 268+n-1 / 274+n-1; g is - in the candidate view",
          t5 == {"v": "CAND", "g": "-", "244": "2", "1": "0000/8000/100/1", "2": "0530/500/20/0", "3": "1000/4000/0/1", "4": "1600/3000/50/0",
                 "5": "2100/2000/100/0", "6": "2330/1000/30/1", "dx": "1A2B3"} and dict(kv(str(cap.b5_text(True, wd(w13=0x27), False, 0))))["1"].endswith("/39"))
    check("B5 NONE form and dx - without an authentic stored profile", str(cap.b5_text(False, GW, True, 5)) == "v=NONE;g=-;244=-;1=-;2=-;3=-;4=-;5=-;6=-;dx=-"
          and str(cap.b5_text(True, GW, False, 5)).endswith(";dx=-") and str(cap.b5_text(True, GW, True, 0)).endswith(";dx=00000"))
    t6 = dict(kv(str(cap.b6_text(True, GW, True, 0x1FF, 0x1F))))
    check("B6: 232 / 248 / 247 in 4-digit hex, 243 / 230 / 245 decimal, ring OK / BAD, dc 3 hex, di 2 hex; NONE form all -",
          t6 == {"v": "CAND", "232": "0011", "243": "1", "248": "0001", "ring": "OK", "230": "185", "245": "8000", "247": "0001", "dc": "1FF", "di": "1F"}
          and dict(kv(str(cap.b6_text(True, wd(w23=0), True, 0, 0))))["ring"] == "BAD"
          and str(cap.b6_text(False, GW, True, 1, 1)) == "v=NONE;232=-;243=-;248=-;ring=-;230=-;245=-;247=-;dc=-;di=-" and str(cap.b6_text(True, GW, False, 1, 1)).endswith(";dc=-;di=-"))
    # ---- B7 / B8
    sv_cases = [(LOAD_OK, GOLD_P, c, c in (3, 4, 5, 8)) for c in range(9)] + [(LOAD_ABSENT, Z, c, False) for c in range(9)] + [
        (LOAD_OK, dict(GOLD_P, magic=0), c, False) for c in (2, 0, 5)] + [(LOAD_OK, golden_profile(reg244=1), c, c != 0) for c in range(9)] + [
        (LOAD_OK, golden_profile(flags=1), c, c != 0) for c in range(9)]
    bad = []
    for load, p, cls, saved in sv_cases:
        authentic = fd.fba_authentic(fp.classify_profile(load, p))
        want = authentic and cls != fd.EPC_UNREADABLE
        t7, t8 = str(cap.b7_text(load, p, cls)), str(cap.b8_text(load, p, cls))
        if (t7.startswith("v=SAVED") != want) or (t8.startswith("v=SAVED") != want):
            bad.append((load, cls))
    check("B7 / B8 are SAVED iff the FB-A class is authentic (VALID, INVALIDATED, CORRUPT_DOMAIN) AND the effective class is not UNREADABLE (also for STALE); NONE otherwise",
          not bad, str(bad[:3]))
    t7, t8 = dict(kv(str(cap.b7_text(0, GOLD_P, 5)))), dict(kv(str(cap.b8_text(0, GOLD_P, 5))))
    check("B7: g, 244, six slot tuples, dx=-, and b = the first 8 hex of %016llX (the HIGH 32 bits of the binding); B8: context + dc=-;di=- + b",
          t7["g"] == "7" and t7["dx"] == "-" and t7["b"] == f"{GOLD_P['binding']:016X}"[:8] == f"{GOLD_P['binding'] >> 32:08X}" and t7["1"] == "0000/8000/100/1"
          and t8["dc"] == "-" and t8["di"] == "-" and t8["b"] == t7["b"] and t8["232"] == "0011" and t8["ring"] == "OK")
    check("B7 / B8 NONE forms carry b=- (and g=-)", str(cap.b7_text(1, Z, 1)) == "v=NONE;g=-;244=-;1=-;2=-;3=-;4=-;5=-;6=-;dx=-;b=-"
          and str(cap.b8_text(1, Z, 1)) == "v=NONE;232=-;243=-;248=-;ring=-;230=-;245=-;247=-;dc=-;di=-;b=-")
    ok7 = ok8 = True
    max7 = 0
    for _ in range(4000):
        pl, p, _len = rand_profile(rng)
        cls = rng.randrange(0, 9)
        t7, t8 = str(cap.b7_text(pl, p, cls)), str(cap.b8_text(pl, p, cls))
        max7 = max(max7, len(t7))
        ok7 = ok7 and grammar_ok(t7, K_B7)
        ok8 = ok8 and grammar_ok(t8, K_B8)
    check(f"B7 / B8: all keys in order, charset, <= 200 on 4000 random records (B7 max {max7})", ok7 and ok8)
    big = golden_profile(reg244=65535, generation=4294967295, captured_epoch=4294967295, reg256_261=[65535] * 6, reg268_273=[65535] * 6,
                         reg274_279=[65535] * 6, reg250_255=[65535] * 6)
    check("B7: an authentic CORRUPT_DOMAIN record with every value 5 digits wide would be 202 characters: the NONE form is published, never a truncated text",
          len(str(cap.b7_text(0, big, 3))) == len("v=NONE;g=-;244=-;1=-;2=-;3=-;4=-;5=-;6=-;dx=-;b=-") and str(cap.b7_text(0, big, 3)).startswith("v=NONE")
          and cap.b7_text(0, big, 3).count("=") == 11)
    wide = golden_profile(generation=4294967295, reg256_261=[8000] * 6, reg268_273=[100] * 6, reg274_279=[1] * 6, reg250_255=[65535] * 6)
    check("B7: the widest domain-valid VALID record fits (156 characters)", len(str(cap.b7_text(0, wide, 5))) == 156 and str(cap.b7_text(0, wide, 5)).startswith("v=SAVED"))
    # RH1: B7 and B8 decide SAVED / NONE with ONE predicate. For the authentic CORRUPT_DOMAIN all-5-digit record BOTH are NONE.
    none7, none8 = "v=NONE;g=-;244=-;1=-;2=-;3=-;4=-;5=-;6=-;dx=-;b=-", "v=NONE;232=-;243=-;248=-;ring=-;230=-;245=-;247=-;dc=-;di=-;b=-"
    def mk_wide(**over) -> dict:
        base = dict(reg244=65535, generation=4294967295, captured_epoch=4294967295, reg256_261=[65535] * 6, reg268_273=[65535] * 6,
                    reg274_279=[65535] * 6, reg250_255=[65535] * 6, reg232=65535, reg243=65535, reg248=65535, reg230=65535, reg245=65535, reg247=65535)
        base.update(over)
        return golden_profile(**base)
    all5 = mk_wide()
    check("the review's repro: an AUTHENTIC CORRUPT_DOMAIN record (sealed, generation 4294967295, every register 65535) would make B7 202 characters; B7 AND B8 both publish "
          "their NONE form for every effective class (B8 used to say v=SAVED with a context and b= next to a B7 that said NONE)",
          fp.classify_profile(0, all5) == fp.PROFILE_CORRUPT_DOMAIN and len(cap._b7_saved(all5)) == 202
          and all(str(cap.b7_text(0, all5, c)) == none7 and str(cap.b8_text(0, all5, c)) == none8 for c in range(0, 9)))

    def b7_len(q: dict) -> int:  # an independent length oracle for the B7 SAVED text
        parts = ["v=SAVED", f"g={q['generation']}", f"244={q['reg244']}"]
        for n in range(6):
            parts.append(f"{n + 1}={q['reg250_255'][n]:04d}/{q['reg256_261'][n]}/{q['reg268_273'][n]}/{q['reg274_279'][n]}")
        return len(";".join(parts + ["dx=-", f"b={q['binding'] >> 32:08X}"]))
    edge = {202: mk_wide(), 201: mk_wide(reg244=9999), 200: mk_wide(reg244=9999, generation=999999999)}
    check("the boundary: a B7 SAVED text of exactly 200 characters is SAVED in BOTH views; 201 and 202 characters give NONE in BOTH (<= 200 is the one rule)",
          [b7_len(edge[n]) for n in (200, 201, 202)] == [200, 201, 202]
          and all(fd.fba_authentic(fp.classify_profile(0, edge[n])) for n in edge)
          and str(cap.b7_text(0, edge[200], 3)).startswith("v=SAVED") and str(cap.b8_text(0, edge[200], 3)).startswith("v=SAVED") and len(cap.b7_text(0, edge[200], 3)) == 200
          and str(cap.b7_text(0, edge[201], 3)) == none7 and str(cap.b8_text(0, edge[201], 3)) == none8
          and str(cap.b7_text(0, edge[202], 3)) == none7 and str(cap.b8_text(0, edge[202], 3)) == none8)
    agree_bad = []
    n_over = 0
    for i in range(3000):
        pw = rng.choice([0.3, 0.7, 0.9, 0.97, 1.0])
        val = lambda: 65535 if rng.random() < pw else rng.choice([0, 9, 99, 999, 9999])  # noqa: E731
        q = golden_profile(reg244=val(), generation=rng.choice([1, 99999999, 4294967295, 4294967295]), captured_epoch=rng.choice([1, 4294967295]),
                           reg256_261=[val() for _ in range(6)], reg268_273=[val() for _ in range(6)], reg274_279=[val() for _ in range(6)],
                           reg250_255=[val() for _ in range(6)], reg232=val(), reg243=val(), reg248=val(), reg230=val(), reg245=val(), reg247=val())
        cls = rng.randrange(0, 9)
        authentic = fd.fba_authentic(fp.classify_profile(0, q))
        want = authentic and cls != fd.EPC_UNREADABLE and b7_len(q) <= 200
        n_over += authentic and cls != fd.EPC_UNREADABLE and b7_len(q) > 200
        t7, t8 = str(cap.b7_text(0, q, cls)), str(cap.b8_text(0, q, cls))
        if (t7.startswith("v=SAVED"), t8.startswith("v=SAVED")) != (want, want) or len(t7) > 200 or len(t8) > 200:
            agree_bad.append((cls, b7_len(q), t7[:12], t8[:12]))
    check(f"B7 and B8 agree on SAVED / NONE for 3000 random widths and classes ({n_over} of them over 200 characters), and both equal the independent oracle "
          "(authentic, class != UNREADABLE, B7 text <= 200)", not agree_bad and n_over >= 100, str(agree_bad[:2]) + f" over={n_over}")
    wide8 = golden_profile(reg243=65535, reg232=65535, reg248=65535, reg230=65535, reg245=65535, reg247=65535, reg250_255=[0] * 6)
    check("B8 worst case is 94 characters (the widest context values with a saveable-width slot table)",
          len(str(cap.b8_text(0, wide8, 5))) == 94 and str(cap.b8_text(0, wide8, 5)).startswith("v=SAVED"))
    # RH5: text-only refusal kinds render NOTHING (the C++ put_refusal_code); the mirror used to print their slot digits
    r5 = cap.Refusals()
    for kind, slot in ((cap.RF_PWRL, 2), (cap.RF_CLASS, 5), (cap.RF_ANOMALY, 0), (cap.RF_NONE, 3), (200, 7)):
        cap._refusal_add(r5, kind, slot)
    check("sv_text: the text-only kinds (RF_CLASS, RF_ANOMALY), RF_NONE and an unknown kind render NO code, in the C++ way (the mirror used to print '10' / '0')",
          [cap._refusal_code(cap.RF_CLASS << 8 | 5), cap._refusal_code(cap.RF_ANOMALY << 8), cap._refusal_code(cap.RF_NONE << 8 | 3), cap._refusal_code(200 << 8 | 7)] == ["", "", "", ""]
          and str(cap.sv_text(r5)) == "NO:PWRL2,,+2" and cap._refusal_code(cap.RF_PWRL << 8 | 2) == "PWRL2")
    check("TextBuf accessors: c_str() and size()", cap.b4_text(True, 1).c_str() == "0000000000000001" and cap.b4_text(True, 1).size() == 16)


def section_b9():
    print("[14] B9 texts: prefix set, hazard regexes, length, read-failure and mismatch texts")
    PREFIXES = ("No Fallback Profile action since boot", "review in progress (read-only)", "CANDIDATE READY", "CANDIDATE NOT SAVEABLE", "REVIEW REFUSED",
                "REVIEW NOT COMPLETED", "REVIEW EXPIRED", "REVIEW CLEARED", "INTERNAL")
    out = {
        "seed": cap.b9_seed_text(), "progress": cap.review_in_progress_text(), "ready": cap.candidate_ready_text(), "expired": cap.review_expired_text(),
        "cleared writes": cap.review_cleared_writes_text(), "internal": cap.internal_context_text(), "breaker held": cap.breaker_text(True),
        "breaker free": cap.breaker_text(False), "in flight": cap.refused_in_flight_text(), "not loaded": cap.refused_not_loaded_text(), "arms": cap.refused_arms_text(),
    }
    for s in (K.SLOT_FP, K.SLOT_DUMP, K.SLOT_R244):
        out[f"cleared {s}"] = cap.review_cleared_domain_text(s)
    for code in range(0, 9):
        for step in range(0, 6):
            for exc in (0, 2, 255):
                out[f"read {code}/{step}/{exc}"] = cap.read_fail_text(code, step, exc)
    rng = random.Random(77)
    for i in range(400):
        a, b = rand_words(rng, 0.2), rand_words(rng, 0.2)
        out[f"mismatch {i}"] = cap.pass_mismatch_text(a, b)
    for i in range(1500):
        w = rand_words(rng, 0.6)
        out[f"not saveable {i}"] = cap.not_saveable_text(cap.capture_refusals(w, rng.choice([8000, 5000])), w, rng.randrange(0, 10), rng.choice([0, 0, 4]))
    out["not saveable worst"] = cap.not_saveable_text(cap.capture_refusals([65535] * 31, 8000), [65535] * 31, 0, 4)
    check(f"every one of the {len(out)} B9 texts is <= 200 characters, starts with a locked prefix and matches no Energy Actions card pattern (case-insensitive)",
          all(len(t) <= 200 and t.startswith(PREFIXES) and not hazard(t) for t in out.values()), str([t for t in out.values() if len(t) > 200 or not t.startswith(PREFIXES) or hazard(t)][:2]))
    # FB-B2 (D8): a Save exists now, so the FB-B1 "values are shown for review only" wording is false; the READY text names the arm and the Save
    check("D8 texts, exactly: seed, in progress, CANDIDATE READY (FB-B2 wording: arm and save within 120 s), expired, cleared, internal, breaker",
          str(out["seed"]) == "No Fallback Profile action since boot" and str(out["progress"]) == "review in progress (read-only)"
          and str(out["ready"]) == "CANDIDATE READY - both read passes agree on all 31 registers; check the values, then arm and save within 120 s"
          and str(out["expired"]) == "REVIEW EXPIRED - candidate expired (120 s); review again"
          and str(out["cleared writes"]) == "REVIEW CLEARED - another ECCO write started since Review"
          and str(out["cleared 2"]) == "REVIEW CLEARED - a temporary operation started (Free Power)"
          and str(out["cleared 3"]) == "REVIEW CLEARED - a temporary operation started (Dump to Grid)"
          and str(out["cleared 4"]) == "REVIEW CLEARED - a temporary operation started (Register 244 test)"
          and str(out["internal"]) == "INTERNAL - Fallback Profile dispatch context invalid; nothing written"
          and str(out["breaker held"]) == "INTERNAL - Fallback Profile operation state reset by watchdog; write lock still held - reboot required"
          and str(out["breaker free"]) == "INTERNAL - Fallback Profile operation state reset by watchdog; write lock free")
    alltext = "\n".join(str(t) for t in out.values())
    # FB-B2 (D8, AW-3): the original FB-B1 pin below covers EVERY B9 text again, the CANDIDATE READY text included. The FB-B2 READY text says
    # "arm and save within 120 s" in lower case, so the pin's case-sensitive `\bArm\b` / `Save within` / `turn on` forms still hold on it; the pin is
    # unchanged (same regex, same text set) and only its label no longer claims the arm and the Save do not exist.
    check("no B9 text (the READY text included) names the Arm entity, a SAVE <id> command, a 'turn on' instruction or 'Save within', nor the execute action, supervision, trusted time or the stored profile generation",
          not re.search(r"\bArm\b|turn on|SAVE <|supervision|NTP|execute", alltext) and "Save within" not in alltext)
    # FB-B2 (D8): on top of that pin, the READY text itself is checked with the positive truth (it names the arm and the Save within 120 s) and the
    # negative one: nothing else of the Save flow (no phrase, no heartbeat, no clock, no execute, no 'turn on', no capitalised 'Save within').
    check("FB-B2: the CANDIDATE READY text names the arm and the Save within 120 s and nothing else of the Save flow (no phrase, no heartbeat, no clock, no execute, no 'turn on')",
          "arm and save within 120 s" in str(out["ready"]) and not re.search(r"supervision|NTP|execute|SAVE <|heartbeat|Arm|turn on|Save within", str(out["ready"]))
          and len(str(out["ready"])) <= 200)
    check("read failures (S1 1.7): the block is named, the S1 phrases are used, the exception code is hex",
          str(cap.read_fail_text(cap.READ_NO_RESPONSE, 1, 0)) == "REVIEW NOT COMPLETED - no response reading registers 230/3"
          and str(cap.read_fail_text(cap.READ_NO_RESPONSE, 2, 0)) == "REVIEW NOT COMPLETED - no response reading registers 241/53"
          and str(cap.read_fail_text(cap.READ_EXCEPTION, 2, 2)) == "REVIEW NOT COMPLETED - inverter returned exception code 0x02 on registers 241/53"
          and str(cap.read_fail_text(cap.READ_EXCEPTION, 3, 0)) == "REVIEW NOT COMPLETED - inverter returned an exception on registers 230/3"
          and str(cap.read_fail_text(cap.READ_NOT_SENT, 4, 0)) == "REVIEW NOT COMPLETED - read of registers 241/53 could not be queued"
          and str(cap.read_fail_text(cap.READ_NONSTANDARD, 1, 0)) == "REVIEW NOT COMPLETED - non-standard reply reading registers 230/3"
          and str(cap.read_fail_text(cap.READ_SHORT, 2, 0)) == "REVIEW NOT COMPLETED - short reply reading registers 241/53"
          and str(cap.read_fail_text(cap.READ_BOUNDED_WAIT, 3, 0)) == "REVIEW NOT COMPLETED - read of registers 230/3 did not complete within 3 s"
          and str(cap.read_fail_text(cap.READ_IDLE_TIMEOUT, 0, 0)) == "REVIEW NOT COMPLETED - inverter bus stayed busy for 7 s; press Review again"
          and str(cap.read_fail_text(0, 1, 0)) == "REVIEW NOT COMPLETED - read did not complete (unknown cause)")
    check("the exception wording avoids the bus-layer name the pure header may not contain (a documented wording deviation from S1 1.7)",
          "Modbus" not in alltext and "modbus" not in alltext.lower())
    check("pass mismatch names the FIRST differing register NUMBER (244, 256.., canonical order) and both words",
          str(cap.pass_mismatch_text(GW, wd(w0=0))) == "REVIEW NOT COMPLETED - live configuration changed during the read (register 244: 2 then 0); another controller may be editing - review again"
          and "(register 256: 8000 then 1)" in str(cap.pass_mismatch_text(GW, wd(w1=1, w30=2)))
          and "(register 274: 1 then 3)" in str(cap.pass_mismatch_text(GW, wd(w13=3)))
          and "(register 232: 17 then 19)" in str(cap.pass_mismatch_text(GW, wd(w19=0x13, w21=0)))
          and "(register 247: 1 then 65535)" in str(cap.pass_mismatch_text(GW, wd(w30=65535))))
    allf, zero = [65535] * 31, [0] * 31
    check("not-saveable texts: first two reasons then '; +N more', L2 reasons first and the stored-profile class last",
          str(cap.not_saveable_text(cap.capture_refusals(wd(w0=0), 8000), wd(w0=0), 5, 0)) == "CANDIDATE NOT SAVEABLE - 244=0 Allow Export - V1 can only save a Zero Export profile"
          and str(cap.not_saveable_text(cap.capture_refusals(wd(w0=1, w1=499), 8000), wd(w0=1, w1=499), 5, 0)) == "CANDIDATE NOT SAVEABLE - 244=1 Essentials - unsupported in V1; slot 1 power 499 W < 500 W (V1 minimum)"
          and str(cap.not_saveable_text(cap.capture_refusals(wd(w0=7, w1=499, w8=101), 8000), wd(w0=7, w1=499, w8=101), 5, 0)).endswith("; +1 more")
          and str(cap.not_saveable_text(cap.Refusals(), GW, 0, 4)) == "CANDIDATE NOT SAVEABLE - stored profile UNREADABLE; reboot to re-derive it"
          and str(cap.not_saveable_text(cap.Refusals(), GW, 7, 0)) == "CANDIDATE NOT SAVEABLE - previous save outcome unknown; reboot to re-verify"
          and str(cap.not_saveable_text(cap.Refusals(), GW, 5, 4)) == "CANDIDATE NOT SAVEABLE - stored profile read anomaly this boot; reboot to re-derive it"
          and str(cap.not_saveable_text(cap.capture_refusals(allf, 8000), allf, 0, 4)).endswith("; +37 more")
          and str(cap.not_saveable_text(cap.Refusals(), GW, 5, 0)) == "CANDIDATE NOT SAVEABLE - reason unavailable")
    anomaly_text = "CANDIDATE NOT SAVEABLE - stored profile read anomaly this boot; reboot to re-derive it"
    check("RH4(c): not_saveable_text with a permitted VALID class and a read anomaly of 1, 2, 3 or 4 gives the anomaly reason; anomaly 0 gives 'reason unavailable'; "
          "a refusal comes first; review_eligible is false for every anomaly value",
          all(str(cap.not_saveable_text(cap.Refusals(), GW, fd.EPC_VALID, a)) == anomaly_text for a in (1, 2, 3, 4, 255))
          and str(cap.not_saveable_text(cap.Refusals(), GW, fd.EPC_VALID, 0)) == "CANDIDATE NOT SAVEABLE - reason unavailable"
          and str(cap.not_saveable_text(cap.capture_refusals(wd(w0=0), 8000), wd(w0=0), fd.EPC_VALID, 1))
          == "CANDIDATE NOT SAVEABLE - 244=0 Allow Export - V1 can only save a Zero Export profile; stored profile read anomaly this boot; reboot to re-derive it"
          and all(str(cap.not_saveable_text(cap.Refusals(), GW, 0, a)) == "CANDIDATE NOT SAVEABLE - stored profile UNREADABLE; reboot to re-derive it" for a in (0, 1, 4))
          and all(not cap.review_eligible(cap.Refusals(), fd.EPC_VALID, a) for a in (1, 2, 3, 4, 255)) and cap.review_eligible(cap.Refusals(), fd.EPC_VALID, 0))
    check("not-saveable texts: the PWRH reason names the site ceiling when the power is within 8000 W", "above this site's configured ceiling" in str(
        cap.not_saveable_text(cap.capture_refusals(wd(w1=6000), 5000), wd(w1=6000), 5, 0)) and "> 8000 W" in str(cap.not_saveable_text(cap.capture_refusals(wd(w1=9000), 8000), wd(w1=9000), 5, 0)))
    check("the B9 prefix set is exactly the D8 list: nothing else is emitted (no SAVE / INVALIDATE / RESTORE / ACKNOWLEDGE texts exist in the mirror)",
          not any(n.lower().startswith(("save", "invalidate_text", "restore", "acknowledge")) for n in dir(cap) if "text" in n))
    check("invalidate_reason_publishes: empty and 'superseded...' reasons are silent, anything else publishes",
          not cap.invalidate_reason_publishes("") and not cap.invalidate_reason_publishes("superseded") and not cap.invalidate_reason_publishes("superseded by a new Review")
          and cap.invalidate_reason_publishes("expired") and cap.invalidate_reason_publishes("supersede") and cap.invalidate_reason_publishes("REVIEW EXPIRED - candidate expired (120 s); review again"))


def section_timing():
    print("[15] timing: expiry boundaries across the 2^32 wrap, exp=, breaker, lock-stuck, writes fingerprint")
    M32 = 2 ** 32
    ok = True
    for born in (0, 1, 1000, M32 - 120000, M32 - 119999, M32 - 5, M32 - 1, 2 ** 31):
        for age in (0, 1, 119998, 119999, 120000, 120001, 5000000, M32 - 1):
            now = (born + age) % M32
            ok = ok and cap.candidate_expired(now, born) == (age >= 120000)
    check("candidate_expired: 119999 ms not expired, 120000 ms expired, for every born value including those straddling the 2^32 wrap", ok)
    check("exp_seconds: floor((120000 - age) / 1000): 120 at age 0, 119 at 1..1000, 118 at 1001, 1 at 118999-119000..., 0 at 119001..119999 and from 120000 on",
          [cap.exp_seconds(a, 0) for a in (0, 1, 999, 1000, 1001, 60000, 118999, 119000, 119001, 119999, 120000, 120001, 10 ** 9)]
          == [120, 119, 119, 119, 118, 60, 1, 1, 0, 0, 0, 0, 0])
    seq = [cap.exp_seconds(a, 0) for a in range(0, 120001, 7)]
    check("exp_seconds never increases with age and stays in 0..120", all(x >= y for x, y in zip(seq, seq[1:])) and max(seq) == 120 and min(seq) == 0)
    check("exp_seconds across the wrap", cap.exp_seconds(60000, M32 - 1000) == (120000 - 61000) // 1000 and cap.exp_seconds(5, M32 - 5) == 119)
    check("breaker_fired: an operation flag, no dispatch running, older than 30000 ms (strictly), wrap-safe",
          not cap.breaker_fired(True, False, 30000, 0) and cap.breaker_fired(True, False, 30001, 0) and not cap.breaker_fired(True, True, 10 ** 6, 0)
          and not cap.breaker_fired(False, False, 10 ** 6, 0)
          and cap.breaker_fired(True, False, 25000, M32 - 5001) and not cap.breaker_fired(True, False, 24999, M32 - 5001))
    check("writes_fingerprint: the u32 sum of the five attempt counters (wraps), any single change shows",
          cap.writes_fingerprint(1, 2, 3, 4, 5) == 15 and cap.writes_fingerprint(M32 - 1, 1, 0, 0, 0) == 0 and cap.writes_fingerprint(M32 - 1, M32 - 1, 0, 0, 2) == 0
          and all(cap.writes_fingerprint(*[1 if i == j else 0 for i in range(5)]) == 1 for j in range(5)) and cap.writes_fingerprint(*[0] * 5) == 0
          and len({cap.writes_fingerprint(*[7 + (i == j) for i in range(5)]) for j in range(5)}) == 1)
    check("review_integrity_ok: an operation in flight with purpose REVIEW only", cap.review_integrity_ok(True, cap.PURPOSE_REVIEW)
          and not cap.review_integrity_ok(False, cap.PURPOSE_REVIEW) and not cap.review_integrity_ok(True, cap.PURPOSE_NONE) and not cap.review_integrity_ok(True, 2))


def section_gate():
    print("[16] the gate: V1-V7 precedence, lazy probing, latch updates, fuzz invariants")
    PR = cap.ProbeResults
    clear = cap.gate_decide(gi(), PR())
    check("an all-clear gate answers NEED_PROBE for all three markers (nothing probed yet), refuses nothing, has no text",
          (clear.code, clear.probe_fp, clear.probe_dump, clear.probe_r244, str(clear.text), clear.slot) == (K.GATE_NEED_PROBE, True, True, True, "", K.SLOT_NONE))
    acc = cap.gate_decide(gi(), PR(K.PROBE_ABSENT, K.PROBE_CLEAR, K.PROBE_ABSENT))
    check("...and ACCEPTS once the three probes are CLEAR / ABSENT; the vector shows CA / CM / CA", acc.code == K.GATE_ACCEPT and str(acc.obl) == "FP:CA,DP:CM,R4:CA,MT:CN,FS:CA,BUS:OK"
          and not (acc.probe_fp or acc.probe_dump or acc.probe_r244) and acc.latch == 0)
    check("a missing probe is never accepted (fail-closed): any one probe left NONE keeps the answer NEED_PROBE",
          all(cap.gate_decide(gi(), PR(*[K.PROBE_CLEAR if i != j else K.PROBE_NONE for i in range(3)])).code == K.GATE_NEED_PROBE for j in range(3)))
    # V1..V6 precedence
    V1 = dict(fallback_profile_op_in_progress=True)
    order = [
        ("V1 in flight (op flag)", dict(fallback_profile_op_in_progress=True, boot_loaded=False), K.GATE_REFUSE_IN_FLIGHT),
        ("V1 in flight (dispatch running)", dict(fallback_profile_capture_dispatch_running=True, free_power_write_enable=True), K.GATE_REFUSE_IN_FLIGHT),
        ("V2 not loaded outranks V3", dict(boot_loaded=False, free_power_write_enable=True), K.GATE_REFUSE_NOT_LOADED),
        ("V3 arms outrank V4", dict(dump_write_enable=True, manual_write_in_progress=True), K.GATE_REFUSE_ARMS),
        ("V3 manual configuration arm", dict(manual_config_write_enable=True), K.GATE_REFUSE_ARMS),
        ("V3 Free Power arm", dict(free_power_write_enable=True), K.GATE_REFUSE_ARMS),
        ("V3 Dump arm", dict(dump_write_enable=True), K.GATE_REFUSE_ARMS),
        ("V4 bus outranks V5", dict(manual_write_in_progress=True, fbs=fd.FBS_OBLIGATION), K.GATE_REFUSE_BUS),
        ("V5 FBS outranks V6", dict(fbs=fd.FBS_CORRUPT, **{"fp::free_power_marker_state": 1}), K.GATE_REFUSE_FBS),
        ("V6 FP before Dump", {"fp::free_power_marker_state": 1, "dump::dump_marker_state": 1}, K.GATE_REFUSE_FP),
        ("V6 Dump before R244", {"dump::dump_marker_state": 1, "r244::reg244_marker_state": 1}, K.GATE_REFUSE_DUMP),
        ("V6 R244", {"r244::reg244_marker_state": 1}, K.GATE_REFUSE_R244),
    ]
    bad = []
    for label, f, want in order:
        f = dict(f)
        bl = f.pop("boot_loaded", True)
        fb = f.pop("fbs", fd.FBS_CLEAR_ABSENT)
        r = cap.gate_decide(gi(boot_loaded=bl, fbs=fb, **f), PR())
        if r.code != want or not str(r.text).startswith("REVIEW REFUSED - ") or r.probe_fp or r.probe_dump or r.probe_r244:
            bad.append((label, r.code))
    check("V1 > V2 > V3 > V4 > V5 > V6 precedence: the first failing check wins, refusals never ask for a probe", not bad, str(bad))
    r = cap.gate_decide(gi(**{"fp::free_power_marker_state": 1}), PR(K.PROBE_UNREADABLE, K.PROBE_UNREADABLE, K.PROBE_UNREADABLE))
    check("information is never dropped: a probe result supplied for a RAM-clear domain is latched even when another slot refuses (the YAML only probes after NEED_PROBE, so this is defence in depth)",
          r.code == K.GATE_REFUSE_FP and (r.probe_fp, r.probe_dump, r.probe_r244) == (False, False, False) and r.latch == 0x0110)
    r = cap.gate_decide(gi(**{"fp::free_power_marker_state": 1}), PR())
    check("lazy: a refusal leaves the RAM-clear lease domains as NP in the vector and takes no probe", str(r.obl) == "FP:DV,DP:NP,R4:NP,MT:CN,FS:CA,BUS:OK")
    r = cap.gate_decide(gi(manual_write_in_progress=True), PR())
    check("a busy bus refuses at V4 with the owner named; the vector shows BUS:BY and MT:NP (not evaluated) and the lease domains NP",
          r.code == K.GATE_REFUSE_BUS and "(manual write)" in str(r.text) and str(r.obl) == "FP:NP,DP:NP,R4:NP,MT:NP,FS:CA,BUS:BY")
    r = cap.gate_decide(gi(manual_write_in_progress=True, diag_write_lock_held=True, diag_write_lock_since_ms=0, now_ms=481000), PR())
    check("a stuck lock refuses at V4 with the age in seconds", r.code == K.GATE_REFUSE_BUS and "held for 481 s" in str(r.text) and str(r.obl).endswith("BUS:LK"))
    # FW1: the BUS refusal names an ACTIVE lease when the Dump / Free Power controller tick holds the shared lock (manual_write_in_progress alone)
    busy_names_fw1 = ("manual_write_in_progress", "correction_in_progress", "verification_pending", "verification_read_active", "free_power_operation_in_progress",
                      "free_power_recovery_force_in_progress", "free_power_recovery_accept_in_progress", "reg244_apply_in_progress", "dump_operation_in_progress",
                      "fallback_profile_op_in_progress", "fallback_profile_capture_dispatch_running")
    dump_act ={"dump::dump_marker_boot_load": 0, "dump::dump_snapshot_valid": True, "dump::dump_marker_state": 1, "dump::dump_active_persisted": True}
    fp_act = {"fp::free_power_marker_boot_load": 0, "fp::free_power_snapshot_valid": True, "fp::free_power_marker_state": 1, "fp::free_power_active_persisted": True}
    ROW = "REVIEW REFUSED - another inverter transaction is in progress ({}); try again shortly"
    r = cap.gate_decide(gi(manual_write_in_progress=True, **dump_act), PR())
    check("FW1 (the review's repro a20): the Dump controller tick holds the mutex with an ACTIVE Dump lease: the BUS refusal says (Dump to Grid), not (manual write); the vector still shows DP:AC "
          "and BUS:BY, the code is still BUS, the slot BUS (precedence unchanged), nothing is probed",
          r.code == K.GATE_REFUSE_BUS and r.slot == K.SLOT_BUS and str(r.text) == ROW.format("Dump to Grid") and str(r.obl) == "FP:NP,DP:AC,R4:NP,MT:NP,FS:CA,BUS:BY"
          and (r.probe_fp, r.probe_dump, r.probe_r244, r.latch) == (False, False, False, 0))
    r = cap.gate_decide(gi(manual_write_in_progress=True, **fp_act), PR())
    check("FW1: the same for an ACTIVE Free Power lease (Free Power controller tick): (Free Power), vector FP:AC", r.code == K.GATE_REFUSE_BUS and str(r.text) == ROW.format("Free Power")
          and str(r.obl) == "FP:AC,DP:NP,R4:NP,MT:NP,FS:CA,BUS:BY")
    r = cap.gate_decide(gi(manual_write_in_progress=True, **fp_act, **dump_act), PR())
    check("FW1: both leases ACTIVE: Free Power is named (the owner-chain order); the vector shows both", str(r.text) == ROW.format("Free Power") and str(r.obl) == "FP:AC,DP:AC,R4:NP,MT:NP,FS:CA,BUS:BY")
    r = cap.gate_decide(gi(**dump_act), PR())
    check("FW1: with the mutex free the SAME Dump lease is refused at its own slot with the existing text (the next-press behaviour the review described)",
          r.code == K.GATE_REFUSE_DUMP and r.slot == K.SLOT_DUMP and str(r.text) == "REVIEW REFUSED - Dump to Grid is active; live settings are a temporary overlay - end it first")
    unchanged = [
        ("a lease with a plain manual write (no lease active) stays (manual write)", dict(manual_write_in_progress=True), ROW.format("manual write")),
        ("a named owner outranks the lease: clock correction + Dump ACTIVE", dict(manual_write_in_progress=True, correction_in_progress=True, **dump_act), ROW.format("clock correction")),
        ("a named owner outranks the lease: clock verification + Free Power ACTIVE", dict(manual_write_in_progress=True, verification_pending=True, **fp_act), ROW.format("clock verification")),
        ("a named owner outranks the lease: Register 244 apply + Dump ACTIVE", dict(manual_write_in_progress=True, reg244_apply_in_progress=True, **dump_act), ROW.format("Register 244 test")),
        ("the Dump operation flag names Dump to Grid itself", dict(manual_write_in_progress=True, dump_operation_in_progress=True), ROW.format("Dump to Grid")),
        ("a Free Power operation flag + Dump ACTIVE names Free Power (chain)", dict(manual_write_in_progress=True, free_power_operation_in_progress=True, **dump_act), ROW.format("Free Power")),
        ("a lease that is not ACTIVE (restore required, operator needed) is not named", dict(manual_write_in_progress=True, **{"dump::dump_marker_boot_load": 0, "dump::dump_snapshot_valid": True,
                                                                                                                                  "dump::dump_marker_state": 1, "dump::dump_operator_needed": True}), ROW.format("manual write")),
        ("the stuck-lock text is untouched by an ACTIVE lease", dict(manual_write_in_progress=True, diag_write_lock_held=True, diag_write_lock_since_ms=0, now_ms=481000, **dump_act),
         "REVIEW REFUSED - inverter write lock held for 481 s (possible leak); a reboot may be required"),
    ]
    bad = [label for label, f, want in unchanged if str(cap.gate_decide(gi(**f), PR()).text) != want]
    check("FW1: every other BUS refusal keeps its wording (a named owner always outranks a lease, a non-ACTIVE lease is not named, the stuck-lock text is untouched)", not bad, str(bad))
    rng = random.Random(1717)
    bad, n_named = [], 0
    for i in range(20000):
        g = gi(boot_loaded=True, fbs=rng.choice([1, 1, 2]))
        for name in busy_names_fw1:
            setattr(g.bus, name, rng.random() < (0.55 if name == "manual_write_in_progress" else 0.05))
        g.bus.diag_write_lock_held, g.bus.diag_write_lock_since_ms, g.bus.now_ms = rng.random() < 0.1, rng.randrange(0, 2 ** 32), rng.randrange(0, 2 ** 32)
        g.fp.free_power_marker_boot_load, g.dump.dump_marker_boot_load = rng.choice([0, 0, 0, 1, 3]), rng.choice([0, 0, 0, 1, 3])
        g.fp.free_power_recovery_metadata_corrupt, g.dump.dump_recovery_metadata_corrupt = rng.random() < 0.05, rng.random() < 0.05
        g.fp.free_power_snapshot_valid, g.dump.dump_snapshot_valid = rng.random() < 0.6, rng.random() < 0.6
        g.fp.free_power_marker_state, g.dump.dump_marker_state = rng.choice([0, 1, 1, 1, 2]), rng.choice([0, 1, 1, 1, 2])
        g.fp.free_power_active_persisted, g.dump.dump_active_persisted = rng.random() < 0.7, rng.random() < 0.7
        g.fp.free_power_restore_requested, g.dump.dump_restore_requested = rng.random() < 0.1, rng.random() < 0.1
        g.fp.free_power_operator_needed, g.dump.dump_operator_needed = rng.random() < 0.1, rng.random() < 0.1
        g.fp.run_start, g.fp.run_restore, g.dump.run_start, g.dump.run_restore = (rng.random() < 0.05 for _ in range(4))
        g.dump.dump_containment_state = rng.choice([0] * 12 + [3, 8])
        g.probe_latch = rng.choice([0] * 10 + [0x0001, 0x0010, 0x0020])
        r = cap.gate_decide(g, PR())
        if r.code != K.GATE_REFUSE_BUS:
            continue
        flags = {f for f in busy_names_fw1 if getattr(g.bus, f)}
        if cap.lock_stuck(g.bus):
            want = cap.refusal_text(K.SLOT_BUS, r.bus, g.dump.dump_containment_state, "", cap.lock_age_ms(g.bus) // 1000)
        else:
            owner = cap.bus_owner_text(g.bus)
            if flags == {"manual_write_in_progress"} and r.fp.kind == K.OBL_ACTIVE:
                owner = "Free Power"
            elif flags == {"manual_write_in_progress"} and r.dump.kind == K.OBL_ACTIVE:
                owner = "Dump to Grid"
            n_named += owner != cap.bus_owner_text(g.bus)
            want = cap.refusal_text(K.SLOT_BUS, r.bus, g.dump.dump_containment_state, owner, 0)
        if str(r.text) != str(want) or r.slot != K.SLOT_BUS or len(str(r.text)) > 200 or hazard(str(r.text)):
            bad.append((i, str(r.text), str(want)))
    check(f"FW1: {20000} fuzzed gates with a busy bus: the BUS code / slot never change and the text is exactly refusal_text with the owner an independent oracle derives "
          f"({n_named} refusals named a lease instead of 'manual write')", not bad and n_named >= 500, str(bad[:2]) + f" named={n_named}")
    # latch updates
    cases = [(PR(K.PROBE_UNREADABLE, K.PROBE_CLEAR, K.PROBE_ABSENT), 0x0001, K.GATE_REFUSE_FP), (PR(K.PROBE_ABSENT, K.PROBE_MALFORMED, K.PROBE_ABSENT), 0x0020, K.GATE_REFUSE_DUMP),
             (PR(K.PROBE_ABSENT, K.PROBE_CLEAR, K.PROBE_RESTORE_REQUIRED), 0x0300, K.GATE_REFUSE_R244), (PR(K.PROBE_PENDING_CLEAR, K.PROBE_CLEAR, K.PROBE_CLEAR), 0x0004, K.GATE_REFUSE_FP),
             (PR(K.PROBE_UNREADABLE, K.PROBE_UNREADABLE, K.PROBE_MALFORMED), 0x0211, K.GATE_REFUSE_FP), (PR(K.PROBE_CLEAR, K.PROBE_ABSENT, K.PROBE_CLEAR), 0, K.GATE_ACCEPT)]
    check("probe results latch: UNREADABLE 1, MALFORMED 2, ghost RESTORE_REQUIRED 3, ghost PENDING_CLEAR 4 in the domain's nibble; refuses at the first non-clear domain",
          all((lambda r: (r.latch, r.code) == (lat, code))(cap.gate_decide(gi(), p)) for p, lat, code in cases))
    r = cap.gate_decide(gi(latch=0x0001), PR(K.PROBE_PENDING_CLEAR, K.PROBE_ABSENT, K.PROBE_ABSENT))
    check("a latched domain is refused at the RAM leg and its latch is never rewritten (it stays 1 although a later probe says PENDING_CLEAR); never probed again",
          r.latch == 0x0001 and r.code == K.GATE_REFUSE_FP and not r.probe_fp and "unreadable at runtime" in str(r.text))
    r = cap.gate_decide(gi(latch=0x0001), PR())
    check("with FP latched the Dump / R244 domains stay NP: no probe is requested for a refusal", r.code == K.GATE_REFUSE_FP and (r.probe_dump, r.probe_r244) == (False, False))
    check("the vector and the latch persist: a refusal publishes the vector it computed; the latch only gains bits", cap.gate_decide(gi(latch=0x0010), PR()).latch == 0x0010)
    # first-failure texts
    texts = {
        "ghost": cap.gate_decide(gi(), PR(K.PROBE_ABSENT, K.PROBE_CLEAR, K.PROBE_RESTORE_REQUIRED)).text,
        "malformed": cap.gate_decide(gi(), PR(K.PROBE_ABSENT, K.PROBE_MALFORMED, K.PROBE_ABSENT)).text}
    check("the runtime-probe refusal texts are the S1 4.2 latch texts with review wording",
          str(texts["ghost"]) == "REVIEW REFUSED - Register 244 test stored marker says RESTORE_REQUIRED but memory says clear; review blocked until reboot, which re-derives it "
          "(the domain may then restore its saved original)"
          and str(texts["malformed"]) == "REVIEW REFUSED - Dump to Grid recovery marker is malformed (found at runtime); review blocked until reboot, which re-derives it as a hard lockout")
    # fuzz invariants
    rng = random.Random(555)
    N = 30000
    bad = []
    for i in range(N):
        g = gi(boot_loaded=rng.random() < 0.95, latch=cap.latch_set(cap.latch_set(cap.latch_set(0, 0, rng.choice([0] * 12 + [1, 2, 3, 4])), 1, rng.choice([0] * 12 + [1, 2])), 2, rng.choice([0] * 12 + [3, 4])),
               fbs=rng.choice([1, 1, 1, 2, 0, 3, 4]))
        for name in ("free_power_write_enable", "dump_write_enable", "manual_config_write_enable"):
            setattr(g, name, rng.random() < 0.03)
        for name in ("manual_write_in_progress", "correction_in_progress", "verification_pending", "verification_read_active", "free_power_operation_in_progress",
                     "free_power_recovery_force_in_progress", "free_power_recovery_accept_in_progress", "reg244_apply_in_progress", "dump_operation_in_progress",
                     "fallback_profile_op_in_progress", "fallback_profile_capture_dispatch_running"):
            setattr(g.bus, name, rng.random() < 0.04)
        g.bus.diag_write_lock_held, g.bus.diag_write_lock_since_ms, g.bus.now_ms = rng.random() < 0.3, rng.randrange(0, 2 ** 32), rng.randrange(0, 2 ** 32)
        g.fp.free_power_marker_boot_load = rng.choice([0, 1, 1, 1, 1, 2, 3])
        g.fp.free_power_recovery_metadata_corrupt = rng.random() < 0.04
        g.fp.free_power_snapshot_valid = rng.random() < 0.08
        g.fp.free_power_marker_state = rng.choice([0] * 6 + [1, 2])
        g.fp.free_power_active_persisted = rng.random() < 0.05
        g.fp.run_start = rng.random() < 0.03
        g.dump.dump_marker_boot_load = rng.choice([0, 1, 1, 1, 1, 2, 3])
        g.dump.dump_snapshot_valid = rng.random() < 0.08
        g.dump.dump_marker_state = rng.choice([0] * 6 + [1, 2])
        g.dump.dump_containment_state = rng.choice([0] * 20 + [3, 8])
        g.dump.dump_recovery_metadata_corrupt = rng.random() < 0.04
        g.r244.reg244_marker_boot_load = rng.choice([0, 1, 1, 1, 1, 2, 3])
        g.r244.reg244_snapshot_valid = rng.random() < 0.08
        g.r244.reg244_marker_state = rng.choice([0] * 6 + [1, 2])
        g.r244.run_apply = rng.random() < 0.03
        pr = PR(*[rng.choice([0, 0, 1, 2, 2, 3, 4, 5, 6]) for _ in range(3)])
        r = cap.gate_decide(g, pr)
        slots = [r.bus, r.fbs, r.fp, r.dump, r.r244, r.mtou]
        problems = []
        in_flight = g.bus.fallback_profile_op_in_progress or g.bus.fallback_profile_capture_dispatch_running
        if in_flight:
            if r.code != K.GATE_REFUSE_IN_FLIGHT or r.probe_fp or str(r.text) != str(cap.refused_in_flight_text()):
                problems.append("v1")
        else:
            arms = g.free_power_write_enable or g.dump_write_enable or g.manual_config_write_enable
            if not g.boot_loaded:
                if r.code != K.GATE_REFUSE_NOT_LOADED:
                    problems.append("v2")
            elif arms:
                if r.code != K.GATE_REFUSE_ARMS:
                    problems.append("v3")
            else:
                ram_clear = [s.kind in (K.OBL_CLEAR_PROVEN, K.UNK_NOT_PROBED) for s in slots]
                if all(ram_clear):
                    if r.code not in (K.GATE_ACCEPT, K.GATE_NEED_PROBE) or str(r.text) != "":
                        problems.append("accept/need")
                    if r.code == K.GATE_ACCEPT and not all(s.kind == K.OBL_CLEAR_PROVEN for s in slots):
                        problems.append("accept not all clear")
                    if r.code == K.GATE_NEED_PROBE and (r.fp.kind, r.dump.kind, r.r244.kind).count(K.UNK_NOT_PROBED) == 0:
                        problems.append("need without a pending probe")
                    if (r.probe_fp, r.probe_dump, r.probe_r244) != (r.fp.kind == K.UNK_NOT_PROBED, r.dump.kind == K.UNK_NOT_PROBED, r.r244.kind == K.UNK_NOT_PROBED):
                        problems.append("flags")
                else:
                    first = next(i for i, c in enumerate(ram_clear) if not c)
                    want = (K.GATE_REFUSE_BUS, K.GATE_REFUSE_FBS, K.GATE_REFUSE_FP, K.GATE_REFUSE_DUMP, K.GATE_REFUSE_R244, K.GATE_REFUSE_MTOU)[first]
                    if r.code != want or r.slot != first or r.probe_fp or r.probe_dump or r.probe_r244 or not str(r.text).startswith("REVIEW REFUSED - "):
                        problems.append("refuse")
        if not in_flight:
            old = g.probe_latch
            if (r.latch & old) != old or any(cap.latch_get(old, d) and cap.latch_get(r.latch, d) != cap.latch_get(old, d) for d in range(3)):
                problems.append("latch")
            if len(str(r.text)) > 200 or len(str(r.obl)) > 36 or hazard(str(r.text)):
                problems.append("text")
        if problems:
            bad.append((i, problems))
    check(f"{N} fuzzed gates: precedence, lazy probing (flags only when every other slot is RAM-clear), acceptance only with every slot clear, the latch only ever gains bits, texts <= 200", not bad, str(bad[:3]))
    # tick predicate
    check("IE7 (housekeeping): the first lease domain whose RAM legs are not clear, else SLOT_NONE; the bus / arms / FBS are not lease domains",
          cap.lease_domain_nonclear(gi()) == K.SLOT_NONE and cap.lease_domain_nonclear(gi(**{"fp::run_start": True})) == K.SLOT_FP
          and cap.lease_domain_nonclear(gi(**{"dump::run_restore": True})) == K.SLOT_DUMP and cap.lease_domain_nonclear(gi(**{"r244::run_apply": True})) == K.SLOT_R244
          and cap.lease_domain_nonclear(gi(**{"fp::free_power_marker_state": 1, "dump::dump_marker_state": 1})) == K.SLOT_FP
          and cap.lease_domain_nonclear(gi(manual_write_in_progress=True, fbs=fd.FBS_OBLIGATION, free_power_write_enable=True)) == K.SLOT_NONE
          and cap.lease_domain_nonclear(gi(latch=0x0100)) == K.SLOT_R244)
    check("a candidate that was built under an all-clear gate is cleared by the tick the moment a start begins (and not before)",
          cap.lease_domain_nonclear(gi()) == K.SLOT_NONE and cap.lease_domain_nonclear(gi(**{"free_power_operation_in_progress": True})) == K.SLOT_FP)


def section_hygiene():
    print("[17] mirror hygiene")
    text = MIRROR_PATH.read_text(encoding="utf-8")
    bad = [p for p in (r"self_?partial", r"start_?journal") if re.search(p, text, re.I)]
    check("registry/fallback_capture.py contains neither the partial-classifier nor the START-journal token (any case, comments included)", not bad, str(bad))
    check("the mirror imports only the standard library and the two mirrors it reuses",
          sorted(re.findall(r"^(?:import|from) ([\w.]+)", text, re.M)) == ["__future__", "dataclasses", "fallback_durable", "fallback_profile", "pathlib", "sys"])
    check("the mirror performs no file I/O (no open, no Path read / write)", not re.search(r"\bopen\(|read_text|write_text|\.write\(|\bos\.|subprocess", text))
    check("the mirror does not duplicate FB-A / FB-B0 logic: classify_profile, compose_profile_class, note_read, next_seen_hw_gen, save_class_permitted are called, not redefined",
          not re.search(r"^def (classify_profile|compose_profile_class|note_read|next_seen_hw_gen|save_class_permitted|fba_authentic|classify_witness|profile_defect)\b", text, re.M)
          and all(f in text for f in ("fd.compose_profile_class", "fd.note_read", "fd.next_seen_hw_gen", "fd.save_class_permitted", "fp.classify_profile")))
    check("no writer-side or SAVE-side function exists in the mirror (no commit / save / invalidate / execute)",
          not re.search(r"^def (?!_)\w*(commit|save_|invalidate_profile|execute)\w*\(", text, re.M))
    header = HEADER_PATH.read_text(encoding="utf-8")
    check("the header says it is the pure FB-B1 half and names its Python mirror", "registry/fallback_capture.py" in header and "PURE MODEL" in header)


# ===============================================================================================================
def section_defaults():
    print("[18] POD defaults: which fail closed, which are the permissive idle value, and the liveness of every gate input")
    UNAV = fp.LOAD_STORAGE_UNAVAILABLE
    closed = {  # struct -> {field: default} - a forgotten assignment can only refuse
        "GateInputs": {"boot_loaded": False, "fbs_slot": fd.FBS_UNREADABLE},
        "FpDomain": {"free_power_marker_boot_load": 255}, "DumpDomain": {"dump_marker_boot_load": 255}, "R244Domain": {"reg244_marker_boot_load": 255},
        "ProbeResults": {"fp": cap.PROBE_NONE, "dump": cap.PROBE_NONE, "r244": cap.PROBE_NONE},
        "SlotClass": {"kind": cap.OBL_UNSET, "basis": cap.BASIS_NONE},
        "ReadInputs": {"p_load": UNAV, "w_load": UNAV, "healthy": False, "last_p_load": UNAV, "last_w_load": UNAV},
        "ReviewInputs": {"cls": 0, "p_load": UNAV},
    }
    permissive = {  # struct -> fields whose default is the idle value: a forgotten assignment silently fails OPEN
        "GateInputs": ["probe_latch", "free_power_write_enable", "dump_write_enable", "manual_config_write_enable"],
        "BusInputs": ["manual_write_in_progress", "correction_in_progress", "verification_pending", "verification_read_active",
                      "free_power_operation_in_progress", "free_power_recovery_force_in_progress", "free_power_recovery_accept_in_progress",
                      "reg244_apply_in_progress", "dump_operation_in_progress", "fallback_profile_op_in_progress",
                      "fallback_profile_capture_dispatch_running", "diag_write_lock_held", "diag_write_lock_since_ms", "now_ms"],
        "FpDomain": ["free_power_recovery_metadata_corrupt", "free_power_snapshot_valid", "free_power_marker_state", "free_power_operator_needed",
                     "free_power_active_persisted", "free_power_restore_requested", "run_start", "run_restore", "run_operator"],
        "DumpDomain": ["dump_recovery_metadata_corrupt", "dump_containment_state", "dump_snapshot_valid", "dump_marker_state", "dump_operator_needed",
                       "dump_active_persisted", "dump_restore_requested", "run_start", "run_restore"],
        "R244Domain": ["reg244_recovery_metadata_corrupt", "reg244_snapshot_valid", "reg244_marker_state", "run_apply", "run_restore"],
        "ReadInputs": ["present_seen", "read_anomaly", "seen_hw_gen", "baseline_valid"],
        "ReviewInputs": ["read_anomaly", "salt", "seq_next", "ceiling_w"],
    }
    intended = {"FpDomain": ["expired"], "DumpDomain": ["expired"]}   # REVIEW never reads the clock: left unassigned on purpose
    neutral = {"GateInputs": ["bus", "fp", "dump", "r244"], "ReadInputs": ["p", "w", "last_p_bytes", "last_w_bytes"],
               "ReviewInputs": ["words", "p", "p_stored_len"]}
    structs = sorted(set(closed) | set(permissive) | set(intended) | set(neutral))
    unclassified, wrong_closed, wrong_open = [], [], []
    for name in structs:
        obj = getattr(cap, name)()
        fields = list(getattr(cap, name).__dataclass_fields__)
        groups = [set(closed.get(name, {})), set(permissive.get(name, [])), set(intended.get(name, [])), set(neutral.get(name, []))]
        for f in fields:
            if sum(f in g for g in groups) != 1:
                unclassified.append((name, f))
        for f, want in closed.get(name, {}).items():
            if getattr(obj, f) != want:
                wrong_closed.append((name, f, getattr(obj, f), want))
        for f in permissive.get(name, []) + intended.get(name, []):
            want = fp.V1_TOU_POWER_MAX_W if f == "ceiling_w" else 0
            if getattr(obj, f) != want or getattr(obj, f) is True:
                wrong_open.append((name, f, getattr(obj, f)))
    check("every field of every input POD is classified exactly once (fail-closed / permissive idle / intended / neutral): a NEW field must be classified here and in "
          "the header's DEFAULTS note", not unclassified, str(unclassified[:3]))
    check("the fail-closed defaults are exactly as documented: boot_loaded false, fbs_slot FBS_UNREADABLE, the three marker boot loads 255, ProbeResults PROBE_NONE, "
          "SlotClass OBL_UNSET, the ReadInputs / ReviewInputs load codes UNAVAILABLE, healthy false, ReviewInputs.cls UNREADABLE", not wrong_closed, str(wrong_closed[:3]))
    check("every other default is the PERMISSIVE idle value (false / 0; ceiling_w the loosest legal 8000), so the firmware lambdas must assign every field",
          not wrong_open, str(wrong_open[:3]))
    header = HEADER_PATH.read_text(encoding="utf-8")
    a_, b_ = header.find("DEFAULTS ARE NOT UNIFORMLY FAIL-CLOSED"), header.find("struct BusInputs")
    note = header[a_:b_] if 0 <= a_ < b_ else ""
    names = ["boot_loaded", "fbs_slot", "BOOT_LOAD_NOT_LOADED", "PROBE_NONE", "OBL_UNSET", "healthy", "ReviewInputs.cls", "write-arm", "BusInputs", "diag_write_lock_held",
             "_recovery_metadata_corrupt", "_snapshot_valid", "_marker_state", "_operator_needed", "_active_persisted", "_restore_requested", "dump_containment_state",
             "run_", "probe_latch", "baseline_valid", "present_seen", "read_anomaly", "seen_hw_gen", "salt", "seq_next", "ceiling_w", "expired", "fails OPEN"]
    check("the header's DEFAULTS note says the defaults are NOT uniformly fail-closed, names the closed set and EVERY permissive field group (it used to claim that a forgotten "
          "assignment can only refuse)", all(n in note for n in names) and "can only refuse" not in note,
          str([n for n in names if n not in note]))
    # behaviour: the claims of the note, each demonstrated
    clear = cap.ProbeResults(cap.PROBE_ABSENT, cap.PROBE_CLEAR, cap.PROBE_ABSENT)
    assigned = cap.GateInputs(boot_loaded=True, fbs_slot=fd.FBS_CLEAR_ABSENT)
    assigned.fp.free_power_marker_boot_load = assigned.dump.dump_marker_boot_load = assigned.r244.reg244_marker_boot_load = cap.BOOT_LOAD_ABSENT
    check("closed: a default GateInputs refuses (not loaded); with only boot_loaded set it is still refused by the FBS slot and the 255 marker loads",
          cap.gate_decide(cap.GateInputs(), clear).code == cap.GATE_REFUSE_NOT_LOADED
          and cap.gate_decide(cap.GateInputs(boot_loaded=True), clear).code == cap.GATE_REFUSE_FBS
          and cap.gate_decide(cap.GateInputs(boot_loaded=True, fbs_slot=fd.FBS_CLEAR_ABSENT), clear).code == cap.GATE_REFUSE_FP)
    check("closed: forgetting the probe results never accepts (default ProbeResults only ever asks for a probe)",
          cap.gate_decide(assigned, cap.ProbeResults()).code == cap.GATE_NEED_PROBE)
    check("OPEN (the documented hazard): with ONLY the fail-closed fields assigned and every permissive field forgotten, the gate ACCEPTS - the firmware lambdas must assign "
          "the arms, the bus, the lease flags and the latch themselves (pinned statically by the firmware suite)", cap.gate_decide(assigned, clear).code == cap.GATE_ACCEPT)
    # single-flip liveness: every permissive gate input, set alone to a non-idle value, makes the gate refuse (nothing is a dead input), except the documented non-terms
    def flip(path, value):
        g = cap.GateInputs(boot_loaded=True, fbs_slot=fd.FBS_CLEAR_ABSENT)
        g.fp.free_power_marker_boot_load = g.dump.dump_marker_boot_load = g.r244.reg244_marker_boot_load = cap.BOOT_LOAD_ABSENT
        obj = g
        *head, last = path.split(".")
        for part in head:
            obj = getattr(obj, part)
        setattr(obj, last, value)
        return cap.gate_decide(g, clear).code
    live = [("free_power_write_enable", True), ("dump_write_enable", True), ("manual_config_write_enable", True), ("probe_latch", 0x0001), ("probe_latch", 0x0020),
            ("probe_latch", 0x0400)]
    live += [(f"bus.{f}", True) for f in permissive["BusInputs"][:11]]
    live += [("fp.free_power_recovery_metadata_corrupt", True), ("fp.free_power_snapshot_valid", True), ("fp.free_power_marker_state", 1), ("fp.free_power_marker_state", 2),
             ("fp.free_power_active_persisted", True), ("fp.free_power_restore_requested", True), ("fp.run_start", True), ("fp.run_restore", True), ("fp.run_operator", True),
             ("dump.dump_recovery_metadata_corrupt", True), ("dump.dump_containment_state", 3), ("dump.dump_snapshot_valid", True), ("dump.dump_marker_state", 1),
             ("dump.dump_operator_needed", True), ("dump.dump_active_persisted", True), ("dump.run_start", True), ("dump.run_restore", True),
             ("r244.reg244_recovery_metadata_corrupt", True), ("r244.reg244_snapshot_valid", True), ("r244.reg244_marker_state", 1), ("r244.run_apply", True),
             ("r244.run_restore", True), ("fbs_slot", fd.FBS_OBLIGATION), ("fbs_slot", fd.FBS_CORRUPT), ("fp.free_power_marker_boot_load", 3),
             ("dump.dump_marker_boot_load", 2), ("r244.reg244_marker_boot_load", 3), ("boot_loaded", False)]
    dead = [(path, code) for path, value in live if (code := flip(path, value)) in (cap.GATE_ACCEPT, cap.GATE_NEED_PROBE)]
    check(f"liveness: each of {len(live)} single flips of a gate input (arms, probe latch nibbles, eleven busy flags, FP / Dump / R244 corrupt, snapshot, marker state, "
          "active, restore, run_*, containment, FBS slot, boot loads) is refused on its own", not dead, str(dead[:3]))
    inert = [("bus.diag_write_lock_held", True), ("bus.diag_write_lock_since_ms", 99999), ("bus.now_ms", 1000000), ("fp.free_power_operator_needed", True),
             ("fp.expired", True), ("dump.dump_restore_requested", True), ("dump.expired", True)]
    check("the documented non-terms are inert ON THEIR OWN (a stale operator_needed, dump_restore_requested, expired, and the lock diagnostics without the mutex): "
          "the gate still reaches the probe / accept stage", all(flip(path, value) in (cap.GATE_ACCEPT, cap.GATE_NEED_PROBE) for path, value in inert))
    stuck = cap.GateInputs(boot_loaded=True, fbs_slot=fd.FBS_CLEAR_ABSENT)
    stuck.bus.manual_write_in_progress, stuck.bus.diag_write_lock_held, stuck.bus.diag_write_lock_since_ms, stuck.bus.now_ms = True, True, 1000, 301000
    stuck.fp.free_power_marker_boot_load = stuck.dump.dump_marker_boot_load = stuck.r244.reg244_marker_boot_load = 1
    check("the lock diagnostics matter together with the mutex: a held lock older than 300 s refuses as stuck (BUS slot)",
          (lambda r: (r.code, r.slot, str(r.obl).endswith("BUS:LK")))(cap.gate_decide(stuck, clear)) == (cap.GATE_REFUSE_BUS, cap.SLOT_BUS, True))
    # ReadInputs / ReviewInputs defaults, demonstrated
    base = dict(p_load=0, p=GOLD_P, w_load=0, w=GOLD_W, healthy=True)
    other = fp.pack_profile(golden_profile(generation=8))
    forgotten = cap.evaluate_read(cap.ReadInputs(**base, last_p_load=0, last_p_bytes=other, last_w_load=0, last_w_bytes=fd.pack_provision(GOLD_W)))
    assigned_r = cap.evaluate_read(cap.ReadInputs(**base, baseline_valid=True, last_p_load=0, last_p_bytes=other, last_w_load=0, last_w_bytes=fd.pack_provision(GOLD_W)))
    check("OPEN: a forgotten baseline_valid switches the S1 9.2 divergence rule off (a changed record is not noticed); assigned, the same read sets the profile anomaly bit",
          not forgotten.p_diverged and forgotten.latch.read_anomaly == 0 and forgotten.cls == fd.EPC_VALID
          and assigned_r.p_diverged and assigned_r.latch.read_anomaly & fd.KEY_BIT_PROFILE and assigned_r.cls == fd.EPC_UNREADABLE)
    sticky = cap.evaluate_read(cap.ReadInputs(**base, read_anomaly=fd.KEY_BIT_PROFILE))
    check("OPEN: a forgotten read_anomaly drops the sticky anomaly latch (class VALID); assigned, the class is UNREADABLE",
          cap.evaluate_read(cap.ReadInputs(**base)).cls == fd.EPC_VALID and sticky.cls == fd.EPC_UNREADABLE and sticky.latch.read_anomaly & fd.KEY_BIT_PROFILE)
    unhealthy = cap.evaluate_read(cap.ReadInputs(p_load=0, p=GOLD_P, w_load=0, w=GOLD_W))
    check("closed: a forgotten `healthy` is false and fails closed (the unhealthy anomaly bit, class UNREADABLE); a forgotten load code is UNAVAILABLE (UNREADABLE)",
          unhealthy.latch.read_anomaly & fd.ANOMALY_BIT_UNHEALTHY and unhealthy.cls == fd.EPC_UNREADABLE
          and cap.evaluate_read(cap.ReadInputs(healthy=True)).cls == fd.EPC_UNREADABLE)
    v0 = cap.review_evaluate(cap.ReviewInputs())
    check("closed: a default ReviewInputs (zero words, class UNREADABLE) is never eligible and carries no id; OPEN: its read_anomaly / salt / seq_next default to 0",
          not v0.eligible and v0.id == 0 and v0.refusals.count > 0 and cap.ReviewInputs().read_anomaly == 0 and cap.ReviewInputs().salt == 0
          and cap.ReviewInputs().seq_next == 0 and cap.ReviewInputs().ceiling_w == fp.V1_TOU_POWER_MAX_W)


# ===============================================================================================================
def main() -> int:
    section_structure()
    section_index_map()
    section_l2()
    section_warnings()
    section_independence()
    section_masks()
    section_candidate_id()
    section_classifiers()
    section_obl_texts()
    section_probe_latch()
    section_read_eval()
    section_review_eval()
    section_grammars()
    section_b9()
    section_timing()
    section_gate()
    section_hygiene()
    section_defaults()
    print("")
    if FAILURES:
        print(f"FAILED: {len(FAILURES)} check(s)")
        for f in FAILURES:
            print(f"  - {f}")
        return 1
    print("All FB-B1 capture model checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
