#!/usr/bin/env python3
"""FB-B2 - exhaustive checks of the pure SAVE / INVALIDATE model (registry/fallback_save.py).

The mirror is the Python half of firmware/include/ecco_fallback_save.h (namespace ecco_fbsave): the action router, the byte-exact
confirmation grammar, the SAVE gate G0-G16, the INVALIDATE gate, the own-hold masking of the SAVE final lambda, the intended FBP / FBW
pair (plan_save / plan_invalidate) and every operator text. The header's constexpr evaluation (a real C++ compiler,
registry/tests/test_fallback_save_host_compile.py) proves C++ == mirror on ~2500 goldens, 840 random digests and ~150 mutants; THIS suite
proves the mirror itself is the specification, with oracles written independently of it (a regex for the grammar, an ordered predicate list
for the gates, the FB-B0 / FB-A models for the pair, hand-written expected strings for the outcome cells):

  [1]  structure: constants, enum numbering, C++ / Python name parity, POD field lists, the mirror's imports
  [2]  action token and confirmation grammar against `re.fullmatch` and a dictionary oracle (exhaustive small grammar, every case
       permutation, every padding, embedded NUL, non-ASCII), the sanitised echo
  [3]  arm TTL (wrap), the SAVE integrity check, the RAM class overlay
  [4]  the SAVE gate: first-failure-wins over an ordered predicate list (every single failure, EVERY pair, random subsets), texts, the
       id-0 trap, arm_off_only, replace_corrupt, the capture-gate texts re-worded for SAVE
  [5]  the INVALIDATE gate: same method (I1-I12), nothing but the arm / phrase / mirror / bus / FBS decides
  [6]  own-hold masking, the final gate, the bus-quiet predicates, the clock check
  [7]  plan_save over EVERY permitted prior class and every refused one: generation formula, witness fields, authentic-or-0/0 prior,
       REPLACE CORRUPT, PO14, byte equality with an independent builder and with the FB-B0 validate_transition (no legitimate SAVE is
       refused, no class outside the permitted set is accepted); the FB-B0 golden witness vectors are reproduced
  [8]  plan_invalidate: payload verbatim, generation + 1, flag bit0, captured_epoch kept, W-INV shape, guards, no unguarded invalidate_profile
  [9]  outcome texts for every (op, TxnOutcome, refusal, witness_advanced) cell, B9 prefix set, hazard regexes, lengths, the B2 werr / us derivation
  [10] hygiene: the mirror is pure, POD defaults fail closed, the header's DEFAULTS note, the live-flip liveness of every gate input
  [11] mutation: a battery of the checks above is run against the mirror and against every one of ~170 deliberately broken mirrors

FB-B2 hdr-fix additions (all behavioural, all in the mutation battery): F2 the echo never publishes the words failed / deferred (regex oracle,
exhaustive small alphabet, random hazard-rich tokens, card-regex hygiene); SEM-1 ids / bindings that differ only in the high or only in the low
32 bits (G6, I9, plan_save's candidate prior incl. a CORRUPT raw fingerprint, plan_invalidate) and the writes fingerprint below / across the wrap
(G13); SEM-2 only a VALID witness' high-water counts; SEM-3 the lease owner of the BUS refusal; SEM-4 every fail-closed default refuses; SEM-5 /
SEM-6 the S2 Part B wording of the INVALIDATE gate bodies and of the log line; AW-5 the C widths the strict simulator wraps stores to.

Pure: no I/O beyond reading the repo's own files, no compiler needed.
"""

from __future__ import annotations

import importlib.util
import itertools
import random
import re
import sys
from dataclasses import asdict, fields, replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "registry"))
import fallback_capture as cap  # noqa: E402
import fallback_durable as fd  # noqa: E402
import fallback_profile as fp  # noqa: E402
import fallback_save as sv  # noqa: E402

HEADER_PATH = ROOT / "firmware" / "include" / "ecco_fallback_save.h"
MIRROR_PATH = ROOT / "registry" / "fallback_save.py"
FAILURES: list[str] = []
U32, U64 = 0xFFFFFFFF, 0xFFFFFFFFFFFFFFFF


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
KEY = fd.FALLBACK_PROFILE_KEY
LOAD_OK, LOAD_ABSENT, LOAD_WSZ, LOAD_RERR, LOAD_UNAV = 0, 1, 2, 3, 4
ID = 0x0123456789ABCDEF
HEX = format(ID, "016X")
CARD_PATTERNS = [re.compile(p, re.I) for p in (
    r"RECOVERY REQUIRED", r"OPERATOR DECISION REQUIRED", r"RESTORE BLOCKED", r"RECOVERY BLOCKED", r"\bFAILED\b", r"VERIFY ERROR",
    r"VERIFY TIMEOUT", r"VERIFY REFUSED", r"DEFERRED", r"ACCEPT REFUSED", r"Recovery Arm first", r"inverter writes? (?:are |is )?locked",
    r"deliberate recovery required", r"START FAILED", r"ACTIVATION (?:VERIFY|WRITE) FAILED", r"press End Free Power", r"retry restore",
    r"snapshot retained", r"^(?:RESTORING|STARTING|ACTIVATION VERIFY)")]
ALLOWED_PROGRESS = ("save in progress",)  # the lower-case acceptance line (not an outcome, like "review in progress (read-only)")
LOCKED_PREFIXES = ("SAVE REFUSED", "SAVED", "SAVE NOT COMMITTED", "SAVE OUTCOME UNKNOWN", "INVALIDATE REFUSED", "INVALIDATED", "INVALIDATE NOT COMMITTED",
                   "INVALIDATE OUTCOME UNKNOWN", "REFUSED", "RESTORE REFUSED", "ACKNOWLEDGE REFUSED", "INTERNAL")


def hazard(text: str) -> bool:
    return any(p.search(text) for p in CARD_PATTERNS) or bool(re.search(r"(?i)\b(failed|failure|deferred|supervision)\b", text))


def hx(i: int) -> str:
    return format(i & U64, "016X")


def gate_clear() -> cap.GateInputs:
    g = cap.GateInputs(boot_loaded=True, fbs_slot=fd.FBS_CLEAR_ABSENT)
    g.fp.free_power_marker_boot_load = 1
    g.dump.dump_marker_boot_load = 1
    g.r244.reg244_marker_boot_load = 1
    return g


# ---- the independent oracles --------------------------------------------------------------------------------------
TOKEN_ORACLE = {"SAVE": 1, "INVALIDATE": 2, "RESTORE": 3, "ACKNOWLEDGE": 4}
PHRASE_RE = re.compile(r"(SAVE|INVALIDATE) ([0-9A-F]{16})( REPLACE CORRUPT)?")


def oracle_token(s: str) -> int:
    return TOKEN_ORACLE.get(s, 0)


def oracle_phrase(s: str) -> tuple[int, int]:
    """(kind, id): 1 SAVE, 2 SAVE REPLACE CORRUPT, 3 INVALIDATE, 0 invalid; REPLACE CORRUPT only after SAVE; re.fullmatch (never `$`)."""
    m = PHRASE_RE.fullmatch(s)
    if not m or (m.group(1) == "INVALIDATE" and m.group(3)):
        return 0, 0
    return (3 if m.group(1) == "INVALIDATE" else 2 if m.group(3) else 1), int(m.group(2), 16)


def oracle_expected(kind: int, id_: int) -> str:
    return {1: f"SAVE {hx(id_)}", 2: f"SAVE {hx(id_)} REPLACE CORRUPT", 3: f"INVALIDATE {hx(id_)}"}.get(kind, "")


# SAVE gate: the S1 8.5 order as an ordered list of (code name, predicate over a scenario)
SAVE_ORDER = ["SG_IN_FLIGHT", "SG_UNSUPPORTED", "SG_ARM_OFF", "SG_NO_CANDIDATE", "SG_EXPIRED", "SG_ID_FORMAT", "SG_ID_MISMATCH", "SG_PHRASE", "SG_NOT_LOADED",
              "SG_UNCONFIRMED", "SG_ANOMALY", "SG_HB", "SG_TIME", "SG_ARMS", "SG_WRITES", "SG_BUS", "SG_FBS", "SG_FP"]


class Sc:
    """A SAVE gate scenario: every failure is an independent switch."""

    def __init__(self, **kw) -> None:
        self.f = set(kw.get("fail", ()))
        self.cls = kw.get("cls", 5)
        self.kind = kw.get("kind", "")


def build_save(m, sc: Sc):
    """(SaveGateInputs, action, target, confirmation, GateInputs, oracle code name) of a scenario; the oracle is the ordered predicate list."""
    si = m.SaveGateInputs()
    si.arm_was_on = "SG_ARM_OFF" not in sc.f
    si.cand_valid, si.cand_saveable, si.cand_id = True, True, ID
    if "SG_NO_CANDIDATE" in sc.f:
        kind = sc.kind or "invalid"
        si.cand_valid = kind != "invalid"
        si.cand_saveable, si.cand_id = (False, 0) if kind == "notsaveable" else (True, 0) if kind == "id0" else (False, ID) if kind == "idset_notsaveable" else (True, ID)
    si.cand_ms = 4294960000
    si.cand_prior_class = sc.cls
    si.cand_writes_fp = 1000
    si.now_ms = (4294960000 + (120000 if "SG_EXPIRED" in sc.f else 119999)) & U32
    si.writes_fp_now = 1001 if "SG_WRITES" in sc.f else 1000
    si.boot_loaded = "SG_NOT_LOADED" not in sc.f
    si.unconfirmed = "SG_UNCONFIRMED" in sc.f
    si.read_anomaly = 4 if "SG_ANOMALY" in sc.f else 0
    si.hb_ok = "SG_HB" not in sc.f
    si.time_trusted = "SG_TIME" not in sc.f
    cid = si.cand_id if si.cand_id else ID
    action = "capture" if "SG_UNSUPPORTED" in sc.f else "SAVE"
    target = ("g" + hx(cid)[1:]) if "SG_ID_FORMAT" in sc.f else hx(cid ^ 1) if "SG_ID_MISMATCH" in sc.f else hx(cid)
    need_replace = sc.cls == fd.EPC_CORRUPT
    conf = oracle_expected(2 if need_replace else 1, cid)
    if "SG_PHRASE" in sc.f:
        conf = oracle_expected(1 if need_replace else 2, cid)
    g = gate_clear()
    if "SG_IN_FLIGHT" in sc.f:
        g.bus.fallback_profile_op_in_progress = True
    if "SG_ARMS" in sc.f:
        g.free_power_write_enable = True
    if "SG_BUS" in sc.f:
        g.bus.manual_write_in_progress = True
    if "SG_FBS" in sc.f:
        g.fbs_slot = fd.FBS_OBLIGATION
    if "SG_FP" in sc.f:
        g.fp.free_power_marker_boot_load = 0
        g.fp.free_power_snapshot_valid = True
        g.fp.free_power_marker_state = 1
        g.fp.free_power_active_persisted = True
    want = next((c for c in SAVE_ORDER if c in sc.f), "SG_ACCEPT")
    return si, action, target, conf, g, want


def run_save(m, sc: Sc):
    si, a, t, c, g, want = build_save(m, sc)
    return m.save_gate_decide(si, a, len(a), t, len(t), c, len(c), g), want


# INVALIDATE gate
INV_ORDER = ["IG_IN_FLIGHT", "IG_UNSUPPORTED", "IG_ARM_OFF", "IG_ID_FORMAT", "IG_PHRASE", "IG_NOT_LOADED", "IG_ANOMALY", "IG_UNCONFIRMED", "IG_CLASS", "IG_ID_MISMATCH",
             "IG_GENERATION", "IG_BUS", "IG_FBS"]


def build_inv(m, fail: set):
    p = GOLD_P
    w = fd.make_provision(7, p["binding"], 6, 0x1122334455667788, KEY, 1, fd.PROV_OP_SAVE)
    in_ = m.InvalidateGateInputs()
    in_.arm_was_on = "IG_ARM_OFF" not in fail
    in_.boot_loaded = "IG_NOT_LOADED" not in fail
    in_.read_anomaly = 4 if "IG_ANOMALY" in fail else 0
    in_.unconfirmed = "IG_UNCONFIRMED" in fail
    in_.cls = fd.EPC_INVALIDATED if "IG_CLASS" in fail else fd.EPC_VALID
    in_.p_load, in_.p, in_.w_load, in_.w = LOAD_OK, p, LOAD_OK, w
    in_.seen_hw_gen = 8 if "IG_GENERATION" in fail else 0
    in_.bus = cap.BusInputs()
    if "IG_IN_FLIGHT" in fail:
        in_.bus.fallback_profile_op_in_progress = True
    if "IG_BUS" in fail:
        in_.bus.manual_write_in_progress = True
    in_.tx_buffer_empty, in_.tx_blocked = True, False
    in_.fbs_slot = fd.FBS_OBLIGATION if "IG_FBS" in fail else fd.FBS_CLEAR_ABSENT
    id_ = p["binding"]
    action = "SAVE" if "IG_UNSUPPORTED" in fail else "INVALIDATE"
    target = ("x" + hx(id_)[1:]) if "IG_ID_FORMAT" in fail else hx(id_ ^ 1) if "IG_ID_MISMATCH" in fail else hx(id_)
    conf = f"INVALIDATE {target}"
    if "IG_PHRASE" in fail:
        conf = f"INVALIDATE {hx(id_ ^ 2)}"
    if "IG_ID_FORMAT" in fail:
        conf = f"INVALIDATE {target}"
    return in_, action, target, conf


def run_inv(m, fail: set):
    in_, a, t, c = build_inv(m, fail)
    want = next((x for x in INV_ORDER if x in fail), "IG_ACCEPT")
    return m.invalidate_gate_decide(in_, a, len(a), t, len(t), c, len(c)), want


# ---- registry of mutation-capable checks: every check is fn(m, fast) -> None (pass) or a failure detail --------------------
CHECKS: list[tuple[str, object]] = []


def chk(name: str):
    def deco(fn):
        CHECKS.append((name, fn))
        return fn
    return deco


def code_of(m, name: str) -> int:
    return getattr(m, name)


# =========================================== [2] token and grammar =========================================================
@chk("action_token: exact and case-sensitive over every case permutation, every padding and every retired token")
def c_token(m, fast):
    corpus = ["", " ", "SAVE ", " SAVE", "SAVE\n", "\nSAVE", "SAVEX", "SAV", "S", "INVALIDATE ", "invalidate", "INVALID", "INVALIDATEX", "RESTORE ", "ACKNOWLEDGE\n",
              "CAPTURE", "APPLY", "RETRY_APPLY", "ACCEPT_LIVE", "PROVISION", "X" * 40, "SAVE\0x", "INVALIDATE\0", "RESTORE\0RESTORE", "save", "Save", "sAVE", "ACKNOWLEDGE ",
              "SAVE\t", "SAVE\r\n", "é", "SAVEé"]
    for tok in TOKEN_ORACLE:
        for bits in itertools.product((0, 1), repeat=min(len(tok), 7 if fast else 11)):
            corpus.append("".join(c.lower() if b else c for c, b in zip(tok, list(bits) + [0] * (len(tok) - len(bits)))))
    for s in corpus:
        want = oracle_token(s)
        if m.action_token(s, len(s.encode())) != want:
            return f"explicit {s!r}: {m.action_token(s, len(s.encode()))} != {want}"
        # NUL-terminated: the string ends at its first NUL
        if m.action_token(s) != oracle_token(s.split("\0")[0]):
            return f"terminated {s!r}"
        if m.is_invalidate_action(s, len(s.encode())) != (want == 2) or m.is_invalidate_action(s) != (oracle_token(s.split("\0")[0]) == 2):
            return f"router {s!r}"
    if m.action_token(None) != 0 or m.action_token(None, 4) != 0 or m.is_invalidate_action(None) or m.is_invalidate_action(None, 10):
        return "a null action is not UNSUPPORTED"
    if m.action_token("SAVEX", 4) != 1 or m.action_token("SAVE", 5) != 0 or m.action_token("SAVE", 3) != 0:
        return "explicit lengths"
    return None


@chk("grammar: parse_phrase / phrase_equals / is_hex16 / parse_hex16 equal re.fullmatch over an exhaustive small grammar, the fixture kinds and random strings")
def c_grammar(m, fast):
    toks = ["SAVE", "INVALIDATE", "save", " ", "  ", HEX, HEX.lower(), HEX[:15], HEX + "F", "REPLACE", "CORRUPT", "\n", ""]
    rng = random.Random(5)
    strings = []
    for n in range(1, (3 if fast else 4) + 1):
        for combo in itertools.product(toks, repeat=n):
            strings.append("".join(combo))
    strings += [oracle_expected(k, i) for k in (1, 2, 3) for i in (0, 1, ID, U64, 0xAB)]
    strings += [s + x for s in [oracle_expected(k, ID) for k in (1, 2, 3)] for x in ("", " ", "\n", "x", "\0y", " REPLACE CORRUPT", " REPLACE CORRUPT ", "  ")]
    alphabet = "SAVEINLDRPCOT 0123456789ABCDEFabcdef\n\0_"
    for _ in range(300 if fast else 3000):
        base = rng.choice([oracle_expected(rng.choice((1, 2, 3)), rng.getrandbits(64)), "".join(rng.choice(alphabet) for _ in range(rng.randrange(0, 48)))])
        if base and rng.random() < 0.5:
            i = rng.randrange(len(base))
            base = base[:i] + rng.choice(alphabet) + base[i + 1:]
        if base and rng.random() < 0.2:
            base = base[:-1]
        strings.append(base)
    for s in strings:
        n = len(s.encode())
        want = oracle_phrase(s)
        got = m.parse_phrase(s, n)
        if (got.kind, got.id) != want:
            return f"parse_phrase {s!r}: {(got.kind, got.id)} != {want}"
        cut = s.split("\0")[0]
        if m.parse_phrase(s).kind != oracle_phrase(cut)[0]:
            return f"NUL-terminated parse_phrase {s!r}"
        for k in (1, 2, 3):
            exp = oracle_expected(k, ID)
            e = m.expected_phrase(k, ID)
            if str(e) != exp:
                return f"expected_phrase {k}"
            if m.phrase_equals(s, n, e) != (s == exp) or m.phrase_equals(s, e) != (cut == exp):
                return f"phrase_equals {s!r} vs kind {k}"
        hexok = re.fullmatch(r"[0-9A-F]{16}", s) is not None
        if m.is_hex16(s, n) != hexok or m.parse_hex16(s, n) != (int(s, 16) if hexok else 0):
            return f"hex16 {s!r}"
        if m.is_hex16(s) != (re.fullmatch(r"[0-9A-F]{16}", cut) is not None):
            return f"NUL-terminated hex16 {s!r}"
        # the three entry points agree with each other: a confirmation equals the expected phrase of its own parse
        k, i = want
        if k and not m.phrase_equals(s, n, m.expected_phrase(k, i)):
            return f"parse and phrase_equals disagree on {s!r}"
    return None


@chk("grammar: the traps the naive `$`-anchored regex falls into are refused (trailing newline, lower-case hex, double space, 15 / 17 digits)")
def c_traps(m, fast):
    naive = re.compile(r"^(SAVE|INVALIDATE) [0-9A-F]{16}( REPLACE CORRUPT)?$")
    s = f"SAVE {HEX}\n"
    if not naive.match(s):
        return "the premise (the naive regex accepts a trailing newline) is wrong"
    for bad in (s, f"SAVE {HEX.lower()}", f"SAVE  {HEX}", f"SAVE {HEX[:15]}", f"SAVE {HEX}0", f"SAVE {HEX} REPLACE CORRUPT\n", f"SAVE {HEX} REPLACE CORRUPT ",
                f"INVALIDATE {HEX} REPLACE CORRUPT", f"SAVE {HEX} replace corrupt", f"SAVE {HEX} REPLACE  CORRUPT", f"SAVE {HEX} REPLACE", f"SAVE {HEX} CORRUPT",
                f" SAVE {HEX}", f"SAVE{HEX}", f"SAVE\t{HEX}", "SAVE ", "SAVE", ""):
        if m.parse_phrase(bad, len(bad)).kind != 0:
            return f"accepted {bad!r}"
    if (m.parse_phrase(f"SAVE {HEX}", 21).kind, m.parse_phrase(f"SAVE {HEX} REPLACE CORRUPT", 37).kind, m.parse_phrase(f"INVALIDATE {HEX}", 27).kind) != (1, 2, 3):
        return "a valid phrase is refused"
    if m.parse_phrase(f"SAVE {HEX}\0x", 23).kind != 0 or m.parse_phrase(f"SAVE {HEX}\0x").kind != 1:
        return "embedded NUL semantics"
    if m.phrase_equals("", 0, m.expected_phrase(0, ID)) or m.phrase_equals("", m.expected_phrase(0, ID)) or m.phrase_equals(None, 0, m.expected_phrase(1, ID)):
        return "an empty expected phrase (or a null confirmation) must never match"
    if m.phrase_equals(f"SAVE {HEX}\0", 22, m.expected_phrase(1, ID)) or m.phrase_equals(f"SAVE {HEX}x", 22, m.expected_phrase(1, ID)):
        return "a confirmation longer than the expected phrase must not match by its prefix"
    return None


@chk("the sanitised echo: at most 24 bytes, [A-Za-z0-9_] kept, every other byte (and every UTF-8 byte) is '?', NUL-terminated stops at the NUL, explicit length counts it")
def c_echo(m, fast):
    rng = random.Random(9)
    for _ in range(200 if fast else 1500):
        s = "".join(rng.choice("AbZ_09 -?\n\t'\"é\0x") for _ in range(rng.randrange(0, 60)))
        b = s.encode("utf-8")
        exp = "".join(chr(c) if (48 <= c <= 57 or 65 <= c <= 90 or 97 <= c <= 122 or c == 95) else "?" for c in b[:24])
        t = str(m.unsupported_action_text(s, len(b)))
        if t != f"REFUSED - unsupported action '{exp}'":
            return f"explicit {s!r}: {t!r}"
        cut = s.split("\0")[0].encode("utf-8")
        exp2 = "".join(chr(c) if (48 <= c <= 57 or 65 <= c <= 90 or 97 <= c <= 122 or c == 95) else "?" for c in cut[:24])
        if str(m.unsupported_action_text(s)) != f"REFUSED - unsupported action '{exp2}'":
            return f"terminated {s!r}"
    if m.echo_char_ok(ord("a")) is not True or m.echo_char_ok(ord(" ")) or m.echo_char_ok(0) or m.echo_char_ok(255):
        return "echo_char_ok"
    for tok, exp in ((3, "RESTORE REFUSED - not implemented in this firmware"), (4, "ACKNOWLEDGE REFUSED - not implemented in this firmware")):
        if str(m.action_refusal_text(tok, "x", 1)) != exp:
            return f"action_refusal_text {tok}"
    if str(m.action_refusal_text(0, "RETRY_APPLY", 11)) != "REFUSED - unsupported action 'RETRY_APPLY'" or \
            str(m.action_refusal_text(1, "SAVE", 4)) != "REFUSED - unsupported action 'SAVE'" or \
            str(m.action_refusal_text(9, "SAVE", 4)) != "REFUSED - unsupported action 'SAVE'":
        return "an unsupported token must echo"
    return None


# =========================================== [3] arm TTL, integrity, overlay ===============================================
@chk("arm TTL: 119999 ms on, 120000 ms expired, for every born value including those straddling the 2^32 wrap; the constant is 120000")
def c_arm(m, fast):
    if (m.ARM_TTL_MS, m.PRECOMMIT_WAIT_MS, m.PURPOSE_SAVE, m.ECHO_MAX, m.ID_DIGITS) != (120000, 3000, 2, 24, 16):
        return "constants"
    M32 = 2 ** 32
    for born in (0, 1, 1000, M32 - 120000, M32 - 119999, M32 - 5, M32 - 1, 2 ** 31):
        for age in (0, 1, 119998, 119999, 120000, 120001, 5000000, M32 - 1):
            if m.arm_expired((born + age) % M32, born) != (age >= 120000):
                return f"born {born} age {age}"
    return None


@chk("integrity and overlay: purpose SAVE only; the overlay is SAVE_UNCONFIRMED (7) for every class")
def c_integrity(m, fast):
    if not m.save_integrity_ok(True, 2) or any(m.save_integrity_ok(o, p) for o, p in ((False, 2), (True, 1), (True, 0), (True, 3), (False, 0), (True, 255))):
        return "save_integrity_ok"
    for cls in list(range(0, 10)) + [255]:
        if m.overlay_class(cls, True) != 7 or m.overlay_class(cls, False) != cls:
            return f"overlay {cls}"
    return None


# =========================================== [4] the SAVE gate =============================================================
@chk("SAVE gate: all inputs pass -> accept; EVERY single failure refuses with its own code; EVERY pair gives the earlier code; random subsets equal the ordered oracle")
def c_save_gate(m, fast):
    base, want = run_save(m, Sc())
    if base.code != m.SG_ACCEPT or want != "SG_ACCEPT" or base.text != "" or base.arm_off_only or base.replace_corrupt:
        return f"the all-pass scenario: {base.code} {base.text!r}"
    rep, _ = run_save(m, Sc(cls=2))
    if rep.code != m.SG_ACCEPT or not rep.replace_corrupt:
        return "a CORRUPT prior accepts with the REPLACE CORRUPT phrase and reports replace_corrupt"
    conds = SAVE_ORDER[:]
    for c in conds:
        r, want = run_save(m, Sc(fail=[c]))
        if code_of(m, want) != r.code:
            return f"single {c}: {r.code} != {want}"
        if r.arm_off_only != (c == "SG_IN_FLIGHT") or r.replace_corrupt:
            return f"flags of {c}"
    for a, b in itertools.combinations(conds, 2):
        r, want = run_save(m, Sc(fail=[a, b]))
        if code_of(m, want) != r.code:
            return f"pair {a}+{b}: {r.code} != {want}"
    rng = random.Random(3)
    for _ in range(300 if fast else 2500):
        fl = [c for c in conds if rng.random() < 0.3]
        r, want = run_save(m, Sc(fail=fl, cls=rng.choice((5, 5, 2, 1, 3, 4, 6, 8))))
        if code_of(m, want) != r.code:
            return f"subset {fl}: {r.code} != {want}"
    return None


@chk("SAVE gate: the id-0 trap - a NOT SAVEABLE preview (valid, id 0) and a saveable candidate with id 0 can never be saved with 0000000000000000")
def c_id0(m, fast):
    for kind in ("notsaveable", "id0", "invalid", "idset_notsaveable"):
        si, a, t, c, g, _ = build_save(m, Sc(fail=["SG_NO_CANDIDATE"], kind=kind))
        si.cand_id = 0 if kind in ("notsaveable", "id0") else ID
        t, c = hx(si.cand_id), f"SAVE {hx(si.cand_id)}"
        r = m.save_gate_decide(si, a, len(a), t, len(t), c, len(c), g)
        if r.code != m.SG_NO_CANDIDATE:
            return f"{kind}: {r.code}"
    return None


@chk("SAVE gate: the REPLACE CORRUPT phrase variant - exactly the CORRUPT prior needs it, every other class refuses it, every phrase variant is exact")
def c_replace(m, fast):
    for cls in range(0, 10):
        need = cls == fd.EPC_CORRUPT
        for have_replace in (False, True):
            si, a, t, c, g, _ = build_save(m, Sc(cls=cls))
            c = oracle_expected(2 if have_replace else 1, ID)
            r = m.save_gate_decide(si, a, len(a), t, len(t), c, len(c), g)
            if (r.code == m.SG_ACCEPT) != (have_replace == need) or (r.code != m.SG_ACCEPT and r.code != m.SG_PHRASE):
                return f"class {cls} replace={have_replace}: {r.code}"
            if r.code == m.SG_PHRASE and f"expected '{oracle_expected(2 if need else 1, ID)}'" not in str(r.text):
                return "the refusal must echo the EXPECTED phrase"
    return None


@chk("SAVE gate: capture-gate precedence - V1 outranks everything, arms outrank the bus, the bus outranks FBS, FBS outranks the leases; the capture gate never probes")
def c_save_gate_slots(m, fast):
    g = gate_clear()
    si, a, t, c, _g, _ = build_save(m, Sc())
    clear = m.save_gate_decide(si, a, len(a), t, len(t), c, len(c), g)
    if clear.code != m.SG_ACCEPT or str(clear.obl) != "FP:NP,DP:NP,R4:NP,MT:CN,FS:CA,BUS:OK":
        return f"{clear.code} {clear.obl!r} (nothing is probed in the SAVE gate: the vector stays NP)"
    cases = [("op", lambda x: setattr(x.bus, "fallback_profile_op_in_progress", True), m.SG_IN_FLIGHT),
             ("dispatch", lambda x: setattr(x.bus, "fallback_profile_capture_dispatch_running", True), m.SG_IN_FLIGHT),
             ("arm", lambda x: setattr(x, "dump_write_enable", True), m.SG_ARMS), ("manual arm", lambda x: setattr(x, "manual_config_write_enable", True), m.SG_ARMS),
             ("bus", lambda x: setattr(x.bus, "correction_in_progress", True), m.SG_BUS), ("fbs", lambda x: setattr(x, "fbs_slot", fd.FBS_CORRUPT), m.SG_FBS),
             ("fbs unreadable", lambda x: setattr(x, "fbs_slot", fd.FBS_UNREADABLE), m.SG_FBS), ("latch", lambda x: setattr(x, "probe_latch", 0x0100), m.SG_R244),
             ("dump op", lambda x: setattr(x.bus, "dump_operation_in_progress", True), m.SG_BUS)]
    for label, mod, code in cases:
        x = gate_clear()
        mod(x)
        r = m.save_gate_decide(si, a, len(a), t, len(t), c, len(c), x)
        if r.code != code:
            return f"{label}: {r.code} != {code}"
    x = gate_clear()
    x.free_power_write_enable = True
    x.bus.manual_write_in_progress = True
    x.fbs_slot = fd.FBS_OBLIGATION
    if m.save_gate_decide(si, a, len(a), t, len(t), c, len(c), x).code != m.SG_ARMS:
        return "arms outrank the bus"
    x = gate_clear()
    x.bus.manual_write_in_progress = True
    x.fbs_slot = fd.FBS_OBLIGATION
    if m.save_gate_decide(si, a, len(a), t, len(t), c, len(c), x).code != m.SG_BUS:
        return "the bus outranks FBS"
    x = gate_clear()
    x.fbs_slot = fd.FBS_OBLIGATION
    x.fp.free_power_marker_state = 1
    if m.save_gate_decide(si, a, len(a), t, len(t), c, len(c), x).code != m.SG_FBS:
        return "FBS outranks the leases"
    x = gate_clear()
    x.fp.free_power_marker_state = 1
    x.dump.dump_marker_state = 1
    if m.save_gate_decide(si, a, len(a), t, len(t), c, len(c), x).code != m.SG_FP:
        return "Free Power outranks Dump"
    return None


@chk("SAVE gate texts: every refusal is the documented SAVE REFUSED text, the token texts carry no prefix, every text is <= 200 and hazard-free, the phrase echo is the expected one")
def c_save_texts(m, fast):
    want = {"SG_IN_FLIGHT": "SAVE REFUSED - another Fallback Profile operation is in progress", "SG_ARM_OFF": "SAVE REFUSED - ECCO Fallback Profile Arm is not on",
            "SG_NO_CANDIDATE": "SAVE REFUSED - no saveable candidate - press Review Current Configuration first",
            "SG_EXPIRED": "SAVE REFUSED - candidate expired (120 s) - review again", "SG_ID_FORMAT": "SAVE REFUSED - candidate ID must be 16 hex characters",
            "SG_ID_MISMATCH": "SAVE REFUSED - candidate ID does not match the current candidate", "SG_NOT_LOADED": "SAVE REFUSED - durable state not loaded yet",
            "SG_UNCONFIRMED": "SAVE REFUSED - previous save outcome unknown this boot - reboot to re-verify first",
            "SG_ANOMALY": "SAVE REFUSED - stored profile read anomaly this boot; reboot to re-derive it first",
            "SG_HB": "SAVE REFUSED - Home Assistant heartbeat is not stable; wait until the dashboard shows it healthy, then review and save again",
            "SG_TIME": "SAVE REFUSED - clock not NTP-synchronised this boot; the capture time would be untrusted",
            "SG_ARMS": "SAVE REFUSED - a Free Power / Dump to Grid / Manual Configuration write arm is on; finish or turn it off first",
            "SG_WRITES": "SAVE REFUSED - another ECCO inverter write started since Review - review again",
            "SG_BUS": "SAVE REFUSED - another inverter transaction is in progress (manual write); try again shortly",
            "SG_FBS": "SAVE REFUSED - a failback episode record exists; only the firmware that created it can resolve it",
            "SG_FP": "SAVE REFUSED - Free Power is active; live settings are a temporary overlay - end it first",
            "SG_UNSUPPORTED": "REFUSED - unsupported action 'capture'", "SG_PHRASE": f"SAVE REFUSED - confirmation phrase mismatch (expected 'SAVE {HEX}')"}
    for code, text in want.items():
        r, _ = run_save(m, Sc(fail=[code]))
        if str(r.text) != text:
            return f"{code}: {str(r.text)!r}"
        if hazard(str(r.text)) or len(r.text) > 200 or not str(r.text).isascii():
            return f"{code} text hygiene"
    for tok, exp in (("RESTORE", "RESTORE REFUSED - not implemented in this firmware"), ("ACKNOWLEDGE", "ACKNOWLEDGE REFUSED - not implemented in this firmware"),
                     ("INVALIDATE", "REFUSED - unsupported action 'INVALIDATE'"), ("RETRY_APPLY", "REFUSED - unsupported action 'RETRY_APPLY'"),
                     ("", "REFUSED - unsupported action ''")):
        si, a, t, c, g, _ = build_save(m, Sc())
        r = m.save_gate_decide(si, tok, len(tok), t, len(t), c, len(c), g)
        if r.code != m.SG_UNSUPPORTED or str(r.text) != exp:
            return f"token {tok!r}: {r.code} {str(r.text)!r}"
    return None


@chk("SAVE gate: forged capture-gate decisions - an unset or unknown code never accepts, a MTOU slot refusal is SG_MTOU, the in-flight code is G1")
def c_save_forged(m, fast):
    si, a, t, c, g, _ = build_save(m, Sc())
    for code in (0, 12, 99, 255):
        r = m.save_gate_with_result(si, a, len(a), t, len(t), c, len(c), g, cap.GateResult(code=code))
        if r.code != m.SG_UNSET or str(r.text) != "SAVE REFUSED - internal: gate state unavailable; nothing written":
            return f"forged {code}: {r.code}"
    r = m.save_gate_with_result(si, a, len(a), t, len(t), c, len(c), g, cap.GateResult(code=cap.GATE_REFUSE_MTOU, mtou=cap.SlotClass(cap.UNK_NOT_PROBED, cap.BASIS_NONE)))
    if r.code != m.SG_MTOU or not str(r.text).startswith("SAVE REFUSED - Manual TOU"):
        return f"mtou {r.code} {r.text!r}"
    r = m.save_gate_with_result(si, a, len(a), t, len(t), c, len(c), g, cap.GateResult(code=cap.GATE_REFUSE_IN_FLIGHT))
    if r.code != m.SG_IN_FLIGHT or not r.arm_off_only:
        return "forged in flight"
    r = m.save_gate_with_result(si, a, len(a), t, len(t), c, len(c), g, cap.GateResult(code=cap.GATE_REFUSE_NOT_LOADED))
    if r.code != m.SG_NOT_LOADED:
        return "forged not loaded (the capture gate disagrees with G8)"
    for code in (cap.GATE_ACCEPT, cap.GATE_NEED_PROBE):
        if m.save_gate_with_result(si, a, len(a), t, len(t), c, len(c), g, cap.GateResult(code=code)).code != m.SG_ACCEPT:
            return f"forged {code}"
    return None


@chk("save_in_flight_gate (G1 before the one-shot preamble): either flag refuses with arm_off_only, neither is SG_UNSET with an empty text")
def c_save_in_flight(m, fast):
    for op, dsp in itertools.product((False, True), repeat=2):
        r = m.save_in_flight_gate(op, dsp)
        if (r.code == m.SG_IN_FLIGHT) != (op or dsp) or r.arm_off_only != (op or dsp) or (str(r.text) == "") != (not (op or dsp)):
            return f"{op} {dsp}"
        r2 = m.invalidate_in_flight_gate(op, dsp)
        if (r2.code == m.IG_IN_FLIGHT) != (op or dsp) or r2.arm_off_only != (op or dsp):
            return f"invalidate {op} {dsp}"
    return None


@chk("SAVE slot refusals are SAVE-worded for every slot, kind and basis: prefix, no review wording, <= 200 even at the widest owner / age / containment")
def c_slot_texts(m, fast):
    longest = 0
    for slot in range(0, 6):
        for kind in range(0, 15):
            for basis in range(0, 20):
                t = str(m.save_slot_refusal_text(slot, cap.SlotClass(kind, basis), 255, "Register 244 test", 4294967))
                longest = max(longest, len(t))
                if not t.startswith("SAVE REFUSED - ") or len(t) > 200 or hazard(t) or re.search(r"(?i)\breview\b|NTP", t):
                    return f"{slot}/{kind}/{basis}: {t!r}"
    if longest > 200:
        return "too long"
    if str(m.save_slot_refusal_text(cap.SLOT_BUS, cap.SlotClass(cap.UNK_BUS_OR_LOCK_STUCK, cap.BASIS_LOCK_STUCK), 0, "", 301)) != \
            "SAVE REFUSED - inverter write lock held for 301 s (possible leak); a reboot may be required":
        return "stuck lock text"
    if str(m.save_slot_refusal_text(cap.SLOT_R244, cap.SlotClass(cap.OBL_PENDING_CLEAR, 0), 0, "", 0)) != \
            "SAVE REFUSED - Register 244 test restore verified; durable clear still pending - press Restore Original (armed)":
        return "R244 pending clear text"
    if str(m.save_slot_refusal_text(cap.SLOT_DUMP, cap.SlotClass(cap.UNK_METADATA_CORRUPT, cap.BASIS_BOOT_LOCKOUT), 5, "", 0)) != \
            "SAVE REFUSED - Dump to Grid recovery metadata is CORRUPT (hard lockout); Fallback never overwrites or proceeds past it; do not erase NVS; containment K=5":
        return "dump corrupt text"
    return None


# =========================================== [5] the INVALIDATE gate =======================================================
@chk("INVALIDATE gate: all inputs pass -> accept; EVERY single failure and EVERY pair equals the ordered oracle I1-I12; random subsets too")
def c_inv_gate(m, fast):
    r, want = run_inv(m, set())
    if r.code != m.IG_ACCEPT or want != "IG_ACCEPT" or str(r.text) != "" or r.arm_off_only:
        return f"all-pass {r.code} {r.text!r}"
    for c in INV_ORDER:
        r, want = run_inv(m, {c})
        if code_of(m, want) != r.code or r.arm_off_only != (c == "IG_IN_FLIGHT"):
            return f"single {c}: {r.code} != {want}"
    for a, b in itertools.combinations(INV_ORDER, 2):
        r, want = run_inv(m, {a, b})
        if code_of(m, want) != r.code:
            return f"pair {a}+{b}: {r.code} != {want}"
    rng = random.Random(4)
    for _ in range(300 if fast else 2000):
        fl = {c for c in INV_ORDER if rng.random() < 0.3}
        r, want = run_inv(m, fl)
        if code_of(m, want) != r.code:
            return f"subset {sorted(fl)}"
    return None


@chk("INVALIDATE gate: no heartbeat, clock, write-arm, lease or obligation input exists - and the decision does not depend on anything but its own inputs")
def c_inv_inputs(m, fast):
    names = {f.name for f in fields(m.InvalidateGateInputs)}
    if names & {"hb_ok", "time_trusted", "free_power_write_enable", "dump_write_enable", "manual_config_write_enable", "supervision_state"}:
        return f"forbidden inputs {names}"
    if any(("arm" in n and n != "arm_was_on") or "lease" in n or "obligation" in n for n in names):
        return str(names)
    return None


@chk("INVALIDATE gate: VALID with ANY witness relation is invalidatable; every other effective class refuses; the generation / permission guard and the seen high-water")
def c_inv_class(m, fast):
    in_, a, t, c = build_inv(m, set())
    ok = lambda: m.invalidate_gate_decide(in_, a, len(a), t, len(t), c, len(c)).code  # noqa: E731
    for wk in range(0, 17):
        pl, p, _n = (LOAD_OK, GOLD_P, 0)
        wl, w, _l = _wit(wk, p)
        in_.w_load, in_.w = wl, w
        cls = fd.compose_profile_class(pl, p, wl, w, 0)[0]
        in_.cls = cls
        want = m.IG_ACCEPT if cls == fd.EPC_VALID else m.IG_CLASS
        if ok() != want:
            return f"witness kind {wk} (class {cls}): {ok()} != {want}"
    in_, a, t, c = build_inv(m, set())
    for g, wc_hw, seen, want in ((7, 7, 0, m.IG_ACCEPT), (7, 7, 7, m.IG_ACCEPT), (7, 7, 8, m.IG_GENERATION), (7, 6, 100, m.IG_GENERATION)):
        in_.seen_hw_gen = seen
        if ok() != want:
            return f"g {g} seen {seen}: {ok()}"
    in_.seen_hw_gen = 0
    pmax = golden_profile(generation=0xFFFFFFFF)
    in_.p, in_.cls = pmax, fd.EPC_VALID
    in_.w = fd.make_provision(0xFFFFFFFF, pmax["binding"], 0xFFFFFFFE, 0xAB, KEY, 1, 1)
    tm = hx(pmax["binding"])
    if m.invalidate_gate_decide(in_, "INVALIDATE", 10, tm, 16, f"INVALIDATE {tm}", 27).code != m.IG_GENERATION:
        return "generation 0xFFFFFFFF"
    in_ = build_inv(m, set())[0]
    in_.p = golden_profile(flags=1, generation=8)  # the mirror class says VALID but the record is INVALIDATED
    tm = hx(in_.p["binding"])
    if m.invalidate_gate_decide(in_, "INVALIDATE", 10, tm, 16, f"INVALIDATE {tm}", 27).code != m.IG_GENERATION:
        return "permission guard"
    return None


@chk("INVALIDATE gate texts: the documented refusals, the id echo of the phrase, the FBS texts, the busy literal 'inverter busy; try again'")
def c_inv_texts(m, fast):
    want = {"IG_IN_FLIGHT": "INVALIDATE REFUSED - another Fallback Profile operation is in progress", "IG_ARM_OFF": "INVALIDATE REFUSED - ECCO Fallback Profile Arm is not on",
            "IG_ID_FORMAT": "INVALIDATE REFUSED - profile ID must be 16 hex characters",
            "IG_PHRASE": f"INVALIDATE REFUSED - confirmation phrase mismatch (expected 'INVALIDATE {HEX[:-1]}{format((GOLD_P['binding'] & 15), 'X')}')",
            # FB-B2 SEM-5: the S2 Part B 4.2 bodies of I5 and I6 (before: 'durable state not loaded yet' / '... re-derive it first')
            "IG_NOT_LOADED": "INVALIDATE REFUSED - durable state not loaded yet (starting up)",
            "IG_ANOMALY": "INVALIDATE REFUSED - stored profile read anomaly this boot; reboot to re-derive first",
            "IG_UNCONFIRMED": "INVALIDATE REFUSED - previous Fallback Profile write outcome unknown this boot - reboot to re-verify first",
            "IG_CLASS": "INVALIDATE REFUSED - profile is INVALIDATED; only a VALID profile can be invalidated",
            "IG_ID_MISMATCH": "INVALIDATE REFUSED - profile ID does not match the stored VALID profile",
            "IG_GENERATION": "INVALIDATE REFUSED - profile generation is not ahead of this boot's generation high-water mark; reboot to re-verify",
            "IG_BUS": "INVALIDATE REFUSED - inverter busy; try again",
            "IG_FBS": "INVALIDATE REFUSED - a failback episode record exists; only the firmware that created it can resolve it",
            "IG_UNSUPPORTED": "REFUSED - unsupported action 'SAVE'"}
    for code, text in want.items():
        r, _ = run_inv(m, {code})
        if code == "IG_PHRASE":
            text = f"INVALIDATE REFUSED - confirmation phrase mismatch (expected 'INVALIDATE {hx(GOLD_P['binding'])}')"
        if str(r.text) != text:
            return f"{code}: {str(r.text)!r} != {text!r}"
        if hazard(str(r.text)) or len(r.text) > 200:
            return f"{code} hygiene"
    return None


# =========================================== [6] masking, final gate, bus predicates ======================================
def _rand_gate(rng: random.Random) -> cap.GateInputs:
    g = gate_clear()
    flags = ["fallback_profile_op_in_progress", "fallback_profile_capture_dispatch_running", "manual_write_in_progress", "correction_in_progress",
             "verification_pending", "verification_read_active", "free_power_operation_in_progress", "free_power_recovery_force_in_progress",
             "free_power_recovery_accept_in_progress", "reg244_apply_in_progress", "dump_operation_in_progress", "diag_write_lock_held"]
    for f in flags:
        if rng.random() < 0.18:
            setattr(g.bus, f, True)
    g.bus.diag_write_lock_since_ms = rng.randrange(0, 1000)
    g.bus.now_ms = rng.randrange(0, 700000)
    g.free_power_write_enable = rng.random() < 0.07
    g.dump_write_enable = rng.random() < 0.05
    g.fbs_slot = rng.choice([1, 1, 1, 2, 0, 3, 4])
    g.probe_latch = rng.choice([0, 0, 0, 0x0001, 0x0020, 0x0300])
    g.boot_loaded = rng.random() < 0.95
    g.fp.free_power_marker_state = rng.choice([0, 0, 0, 1, 2])
    g.dump.dump_snapshot_valid = rng.random() < 0.05
    return g


@chk("own-hold masking: final_phase_inputs clears EXACTLY the op flag, the capture dispatch and the write lock; the input is not modified; nested records are not shared")
def c_mask(m, fast):
    rng = random.Random(8)
    holds = ("fallback_profile_op_in_progress", "fallback_profile_capture_dispatch_running", "manual_write_in_progress")
    for _ in range(100 if fast else 600):
        g = _rand_gate(rng)
        before = asdict(g)
        out = m.final_phase_inputs(g)
        if asdict(g) != before:
            return "the input was modified"
        want = asdict(g)
        for h in holds:
            want["bus"][h] = False
        if asdict(out) != want:
            return "not exactly the three holds"
        out.fp.free_power_marker_state = 9
        out.bus.correction_in_progress = not out.bus.correction_in_progress
        if asdict(g) != before:
            return "nested records are shared with the input"
    return None


@chk("final gate: gate_decide over the masked inputs - the three own holds never refuse, any OTHER busy flag does, the arms still refuse, the stuck lock is the SAVE's own")
def c_final_gate(m, fast):
    rng = random.Random(12)
    holds = ("fallback_profile_op_in_progress", "fallback_profile_capture_dispatch_running", "manual_write_in_progress")
    for _ in range(150 if fast else 800):
        g = _rand_gate(rng)
        pr = rng.choice([cap.ProbeResults(), cap.ProbeResults(cap.PROBE_ABSENT, cap.PROBE_CLEAR, cap.PROBE_ABSENT), cap.ProbeResults(cap.PROBE_UNREADABLE, cap.PROBE_CLEAR, cap.PROBE_NONE),
                         cap.ProbeResults(cap.PROBE_ABSENT, cap.PROBE_RESTORE_REQUIRED, cap.PROBE_ABSENT)])
        f = m.final_gate_decide(g, pr)
        g2 = replace(g, bus=replace(g.bus, **{h: False for h in holds}), fp=replace(g.fp), dump=replace(g.dump), r244=replace(g.r244))
        want = cap.gate_decide(g2, pr)
        if (f.gr.code, f.gr.slot, f.gr.latch, str(f.gr.obl), str(f.gr.text)) != (want.code, want.slot, want.latch, str(want.obl), str(want.text)):
            return f"gate result differs: {f.gr.code} vs {want.code}"
        if f.gr.code in (cap.GATE_ACCEPT, cap.GATE_NEED_PROBE):
            if str(f.text) != "":
                return "text on an accept"
        else:
            if not str(f.text).startswith("SAVE REFUSED - ") and f.gr.code != cap.GATE_REFUSE_IN_FLIGHT:
                return f"refusal text {f.text!r}"
            if f.gr.code == cap.GATE_REFUSE_IN_FLIGHT:
                return "the masked gate reported IN_FLIGHT"
    g = gate_clear()
    for h in holds:
        setattr(g.bus, h, True)
    if m.final_gate_decide(g, cap.ProbeResults()).gr.code != cap.GATE_NEED_PROBE:
        return "the three own holds alone must leave the gate at NEED_PROBE"
    for other in ("correction_in_progress", "verification_pending", "verification_read_active", "free_power_operation_in_progress", "free_power_recovery_force_in_progress",
                  "free_power_recovery_accept_in_progress", "reg244_apply_in_progress", "dump_operation_in_progress"):
        g = gate_clear()
        setattr(g.bus, other, True)
        for h in holds:
            setattr(g.bus, h, True)
        if m.final_gate_decide(g, cap.ProbeResults()).gr.code != cap.GATE_REFUSE_BUS:
            return f"{other} must still refuse"
    g = gate_clear()
    g.free_power_write_enable = True
    for h in holds:
        setattr(g.bus, h, True)
    if m.final_gate_decide(g, cap.ProbeResults()).gr.code != cap.GATE_REFUSE_ARMS:
        return "a write arm must still refuse"
    g = gate_clear()
    g.bus.manual_write_in_progress, g.bus.diag_write_lock_held, g.bus.diag_write_lock_since_ms, g.bus.now_ms = True, True, 1000, 400000
    if cap.gate_decide(g, cap.ProbeResults()).code != cap.GATE_REFUSE_BUS or m.final_gate_decide(g, cap.ProbeResults()).gr.code != cap.GATE_NEED_PROBE:
        return "the stuck lock is the SAVE's own (masked) hold"
    return None


@chk("bus predicates: commit_bus_quiet and invalidate_bus_idle equal their truth tables; clock_trusted_for_save needs a trusted clock AND a non-zero epoch")
def c_bus(m, fast):
    for op, mu, co, te, tb in itertools.product((False, True), repeat=5):
        if m.commit_bus_quiet(op, mu, co, te, tb) != (op and mu and not co and te and not tb):
            return f"commit_bus_quiet {op, mu, co, te, tb}"
    flags = ["manual_write_in_progress", "correction_in_progress", "verification_pending", "verification_read_active", "free_power_operation_in_progress",
             "free_power_recovery_force_in_progress", "free_power_recovery_accept_in_progress", "reg244_apply_in_progress", "dump_operation_in_progress",
             "fallback_profile_op_in_progress", "fallback_profile_capture_dispatch_running"]
    for te, tb in itertools.product((False, True), repeat=2):
        if m.invalidate_bus_idle(cap.BusInputs(), te, tb) != (te and not tb):
            return f"idle {te, tb}"
        for f in flags:
            b = cap.BusInputs()
            setattr(b, f, True)
            if m.invalidate_bus_idle(b, te, tb):
                return f"{f} must make the bus busy"
    b = cap.BusInputs()
    b.diag_write_lock_held = True
    if not m.invalidate_bus_idle(b, True, False):
        return "the lock diagnostic alone is not a busy flag"
    for t, e, want in ((True, 1790000000, True), (True, 0, False), (False, 1790000000, False), (False, 0, False), (True, 1, True), (True, U32, True)):
        if m.clock_trusted_for_save(t, e) != want:
            return f"clock {t, e}"
    return None


# =========================================== [7] plan_save =================================================================
def _wit(wk: int, p: dict):
    """The witness kinds of the golden-case tables, relative to a stored profile p (mirrors the header's fx_w, written independently)."""
    g = p["generation"] or 9
    b = p["binding"]
    pb = 0x1122334455667788
    pg1, pbb = (g - 1) & U32 if g > 1 else 0, pb if g > 1 else 0
    mk = lambda hw, hb, pg, pbind, tag=KEY, op=1: fd.make_provision(hw & U32, hb, pg & U32, pbind, tag, 1, op)  # noqa: E731
    return {0: (LOAD_ABSENT, fd.blank_provision(), 0), 1: (LOAD_OK, mk(g, b, pg1, pbb), 0), 2: (LOAD_OK, mk(g - 1, 0x77, g - 2, pb), 0),
            3: (LOAD_OK, {**mk(g, b, pg1, pbb), "binding": mk(g, b, pg1, pbb)["binding"] ^ 1}, 0), 4: (LOAD_WSZ, fd.blank_provision(), 40),
            5: (LOAD_RERR, fd.blank_provision(), 0), 6: (LOAD_OK, mk(1, 0x99, 0, 0), 0), 7: (LOAD_OK, mk(5, 0x99, 4, 0xAB), 0),
            8: (LOAD_OK, mk(g + 1, 0x99, g, b), 0), 9: (LOAD_OK, mk(g + 3, 0x99, g + 2, 0xAB), 0), 10: (LOAD_OK, mk(0xFFFFFFFF, b, 0xFFFFFFFE, 0xAB), 0),
            11: (LOAD_OK, mk(g, b, pg1, pbb, 5), 0), 12: (LOAD_OK, mk(g, b, pg1, pbb, KEY, 2), 0), 13: (LOAD_OK, mk(g, b ^ 1, pg1, pbb), 0),
            # SEM-2: a witness that is NOT valid whose bytes carry a huge high-water field (corrupt / wrong size / absent): it must never count
            14: (LOAD_OK, {**mk(0x7FFFFFFF, b, pg1, pbb), "binding": mk(0x7FFFFFFF, b, pg1, pbb)["binding"] ^ 1}, 0),
            15: (LOAD_WSZ, mk(0x7FFFFFFF, b, 0, 0), 40), 16: (LOAD_ABSENT, mk(0x7FFFFFFF, b, 0, 0), 0)}[wk]


def _prof(pk: int):
    none = fp.blank_profile()
    return {0: (LOAD_ABSENT, none, 0), 1: (LOAD_OK, golden_profile(), 0), 2: (LOAD_OK, golden_profile(generation=8, flags=1), 0),
            3: (LOAD_OK, golden_profile(generation=9, reg244=1), 0), 4: (LOAD_OK, {**golden_profile(generation=11), "binding": golden_profile(generation=11)["binding"] ^ 1}, 0),
            5: (LOAD_WSZ, none, 40), 6: (LOAD_RERR, none, 0), 7: (LOAD_UNAV, none, 0), 8: (LOAD_OK, golden_profile(generation=0xFFFFFFFF), 0),
            9: (LOAD_OK, golden_profile(generation=3), 0)}[pk]


def faithful_save(m, pl, p, plen, wl, w, wlen, seen=0, words=None, epoch=1790000500):
    in_ = m.SavePlanInputs()
    in_.p_load, in_.p, in_.p_stored_len, in_.w_load, in_.w, in_.w_stored_len = pl, p, plen, wl, w, wlen
    cls, why, _r = fd.compose_profile_class(pl, p, wl, w, 0)
    in_.cls, in_.why, in_.read_anomaly, in_.unconfirmed, in_.seen_hw_gen = cls, why, 0, False, seen
    f = cap.prior_fingerprint(pl, p, plen)
    in_.cand_prior_class, in_.cand_prior_gen, in_.cand_prior_binding = cls, f.generation, f.binding
    in_.replace_corrupt = cls == fd.EPC_CORRUPT
    in_.words = list(GW if words is None else words)
    in_.captured_epoch = epoch
    return in_


PERMITTED = {fd.EPC_NOT_CAPTURED, fd.EPC_CORRUPT, fd.EPC_CORRUPT_DOMAIN, fd.EPC_INVALIDATED, fd.EPC_VALID, fd.EPC_PROFILE_LOST, fd.EPC_PROFILE_STALE}


def independent_pair(words, gen, epoch, prior_auth_gen, prior_auth_binding, op):
    """The intended FBP / FBW written from the architecture alone (register slices, not cap.profile_from_words, not sv)."""
    w = list(words)
    p = fp.blank_profile(magic=fp.PROFILE_MAGIC, schema=fp.PROFILE_SCHEMA, size=fp.PROFILE_SIZE, generation=gen, captured_epoch=epoch, flags=0,
                         reg244=w[0], reg256_261=w[1:7], reg268_273=w[7:13], reg274_279=w[13:19], reg232=w[19], reg243=w[20], reg248=w[21],
                         reg250_255=w[22:28], reg230=w[28], reg245=w[29], reg247=w[30])
    p = fp.seal_profile(p)
    wit = fd.seal_provision(fd.blank_provision(magic=fd.PROVISION_MAGIC, schema=1, size=48, hw_generation=gen, prior_generation=prior_auth_gen,
                                               hw_binding=p["binding"], prior_binding=prior_auth_binding, hw_tag_key=KEY, hw_record_schema=1, last_op=op, flags=0))
    return p, wit


def plan_matrix(m, fast: bool):
    """Yield (label, inputs, plan) over every stored pair kind, a seen floor and a trusted clock."""
    step = 7 if fast else 1
    n = 0
    for pk in range(0, 10):
        for wk in range(0, 17):
            for seen in (0, 9, 0xFFFFFFFF) if not fast else (0, 9):
                n += 1
                if n % step:
                    continue
                pl, p, plen = _prof(pk)
                wl, w, wlen = _wit(wk, p)
                in_ = faithful_save(m, pl, p, plen, wl, w, wlen, seen)
                yield f"pk{pk} wk{wk} seen{seen}", in_, m.plan_save(in_)


@chk("plan_save over every stored pair: permitted classes accept (unless the counter is exhausted), UNREADABLE / SAVE_UNCONFIRMED refuse; generation, op, witness fields and "
     "both records equal an independent builder; the FB-B0 transition validator accepts every plan (no legitimate SAVE is refused, nothing outside the set is accepted)")
def c_plan_matrix(m, fast):
    for label, in_, plan in plan_matrix(m, fast):
        pl, p = in_.p_load, in_.p
        pc = fp.classify_profile(pl, p)
        wc = fd.classify_witness(in_.w_load, in_.w)
        cls = fd.compose_profile_class(pl, p, in_.w_load, in_.w, 0)[0]
        base = max(p["generation"] if fd.fba_authentic(pc) else 0, in_.w["hw_generation"] if wc == fd.W_VALID else 0, in_.seen_hw_gen)
        want_ok = cls in PERMITTED and base != 0xFFFFFFFF
        if (plan.code == m.PLAN_OK) != want_ok:
            return f"{label}: class {cls} base {base}: code {plan.code}"
        if not want_ok:
            if plan.code not in (m.PLAN_CLASS, m.PLAN_GENERATION) or plan.op != 0 or plan.generation != 0 or str(plan.text) == "":
                return f"{label}: refusal shape {plan.code} {plan.op}"
            if (cls in PERMITTED) != (plan.code == m.PLAN_GENERATION):
                return f"{label}: refusal reason"
            continue
        op = fd.PROV_OP_REPLACE_CORRUPT if cls == fd.EPC_CORRUPT else fd.PROV_OP_SAVE
        auth = fd.fba_authentic(pc)
        ep, ew = independent_pair(in_.words, base + 1, in_.captured_epoch, p["generation"] if auth else 0, p["binding"] if auth else 0, op)
        if plan.generation != base + 1 or plan.op != op or plan.p_new != ep or plan.w_new != ew or str(plan.text) != "":
            return f"{label}: the built pair differs from the independent builder"
        if not fd.validate_transition(plan.w_new, in_.w, (in_.w_load, in_.w_stored_len), plan.p_new, p, (pl, in_.p_stored_len)):
            return f"{label}: the FB-B0 validate_transition refuses the plan"
        if fp.classify_profile(0, plan.p_new) != fp.PROFILE_VALID or fd.compose_profile_class(0, plan.p_new, 0, plan.w_new, 0)[:2] != (fd.EPC_VALID, fd.WHY_NONE):
            return f"{label}: the pair does not compose to VALID / NONE"
    return None


@chk("plan_save: the FB_B2_IMPLEMENTATION_NOTES.md section 6 table - generation and witness prior_* for every prior class (first save, recapture, B8 / B14 / B15, INVALIDATED, CORRUPT_DOMAIN, LOST B5/B6/B7, STALE, REPLACE CORRUPT incl. WRONG_SIZE)")
def c_plan_table(m, fast):
    rows = [  # (pk, wk, seen, gen, op, prior gen, prior binding is the stored record's)
        (0, 0, 0, 1, 1, 0, False), (1, 1, 0, 8, 1, 7, True), (1, 2, 0, 8, 1, 7, True), (1, 0, 0, 8, 1, 7, True), (1, 3, 0, 8, 1, 7, True), (1, 4, 0, 8, 1, 7, True),
        (2, 1, 0, 9, 1, 8, True), (3, 1, 0, 10, 1, 9, True), (0, 7, 0, 6, 1, 0, False), (0, 6, 0, 2, 1, 0, False), (0, 3, 0, 1, 1, 0, False), (0, 3, 3, 4, 1, 0, False),
        (1, 8, 0, 9, 1, 7, True), (9, 9, 0, 7, 1, 3, True), (4, 1, 0, 12, 3, 0, False), (4, 0, 0, 1, 3, 0, False), (4, 0, 12, 13, 3, 0, False), (5, 1, 0, 10, 3, 0, False),
        (5, 0, 0, 1, 3, 0, False), (1, 1, 20, 21, 1, 7, True), (1, 1, 0xFFFFFFFE, 0xFFFFFFFF, 1, 7, True)]
    for pk, wk, seen, gen, op, pg, auth in rows:
        pl, p, plen = _prof(pk)
        wl, w, wlen = _wit(wk, p)
        plan = m.plan_save(faithful_save(m, pl, p, plen, wl, w, wlen, seen))
        if plan.code != m.PLAN_OK or (plan.generation, plan.op, plan.w_new["prior_generation"]) != (gen, op, pg) or \
                plan.w_new["prior_binding"] != (p["binding"] if auth else 0) or plan.w_new["hw_generation"] != gen or plan.w_new["hw_binding"] != plan.p_new["binding"]:
            return f"row {(pk, wk, seen)}: {plan.code} {plan.generation} {plan.op}"
    for pk, wk, seen in ((6, 1, 0), (7, 1, 0), (1, 5, 0), (1, 1, 0xFFFFFFFF), (8, 10, 0), (8, 1, 0)):
        pl, p, plen = _prof(pk)
        wl, w, wlen = _wit(wk, p)
        plan = m.plan_save(faithful_save(m, pl, p, plen, wl, w, wlen, seen))
        if plan.code not in (m.PLAN_CLASS, m.PLAN_GENERATION):
            return f"refused row {(pk, wk, seen)}: {plan.code}"
    return None


@chk("plan_save: the prior must be the candidate's bound prior, the overlay / anomaly / context / clock refusals and their D14 ORDER")
def c_plan_gates(m, fast):
    def mk(**kw):
        pl, p, plen = _prof(1)
        wl, w, wlen = _wit(1, p)
        in_ = faithful_save(m, pl, p, plen, wl, w, wlen)
        for k, v in kw.items():
            setattr(in_, k, v)
        return in_
    code = lambda **kw: m.plan_save(mk(**kw)).code  # noqa: E731
    if code() != m.PLAN_OK:
        return "base"
    if code(cand_prior_class=1) != m.PLAN_PRIOR_CHANGED or code(cand_prior_gen=8) != m.PLAN_PRIOR_CHANGED or code(cand_prior_binding=1) != m.PLAN_PRIOR_CHANGED:
        return "prior changed"
    if code(unconfirmed=True) != m.PLAN_UNCONFIRMED or code(read_anomaly=4) != m.PLAN_ANOMALY:
        return "overlay / anomaly"
    if code(replace_corrupt=True) != m.PLAN_CONTEXT or code(captured_epoch=0) != m.PLAN_CLOCK:
        return "context / clock"
    if code(cand_prior_class=1, unconfirmed=True) != m.PLAN_PRIOR_CHANGED or code(unconfirmed=True, read_anomaly=4) != m.PLAN_UNCONFIRMED \
            or code(read_anomaly=4, replace_corrupt=True) != m.PLAN_ANOMALY or code(replace_corrupt=True, captured_epoch=0) != m.PLAN_CONTEXT \
            or code(captured_epoch=0, seen_hw_gen=0xFFFFFFFF) != m.PLAN_CLOCK:
        return "order"
    # a class that does not permit a save: composed UNREADABLE (any why) and the overlay class value 7
    pl, p, plen = _prof(6)
    wl, w, wlen = _wit(1, p)
    plan = m.plan_save(faithful_save(m, pl, p, plen, wl, w, wlen))
    if plan.code != m.PLAN_CLASS or "stored profile UNREADABLE (PRD)" not in str(plan.text):
        return f"unreadable: {plan.code} {plan.text!r}"
    return None


@chk("plan_save reproduces the FB-B0 golden witness vectors W-FIRST 0xA8B8788B4C915BB6 (first save of the FB-A golden payload) and the FB-A golden binding chain")
def c_plan_golden(m, fast):
    in_ = faithful_save(m, LOAD_ABSENT, fp.blank_profile(), 0, LOAD_ABSENT, fd.blank_provision(), 0, 0, epoch=1790000000)
    plan = m.plan_save(in_)
    if plan.code != m.PLAN_OK or plan.generation != 1 or plan.w_new["hw_binding"] != 0xB74CE0FA6297474D or plan.w_new["binding"] != 0xA8B8788B4C915BB6:
        return f"W-FIRST: {plan.code} {plan.w_new.get('binding', 0):X} {plan.w_new.get('hw_binding', 0):X}"
    if plan.p_new["binding"] != 0xB74CE0FA6297474D or fp.pack_profile(plan.p_new) != fp.pack_profile(fd_profile_g1()):
        return "the first-save record is the golden payload at generation 1"
    return None


def fd_profile_g1() -> dict:
    p = fp._copy(GOLD_P)
    p["generation"] = 1
    return fp.seal_profile(p)


@chk("PO14 pre-validation: a pair whose profile is not VALID, whose witness is invalid, that does not compose to VALID / NONE, whose generation does not advance or whose witness names another record is refused")
def c_po14(m, fast):
    pn, wn = independent_pair(GW, 8, 1790000500, 7, GOLD_P["binding"], 1)
    if not m.save_pair_valid(pn, wn, 7):
        return "the good pair"
    bad = [("generation not advancing", pn, wn, 8), ("profile not valid", {**pn, "binding": pn["binding"] ^ 1}, wn, 7),
           ("INVALIDATED profile", fp.seal_profile({**pn, "flags": 1}), wn, 7), ("witness invalid", pn, {**wn, "binding": wn["binding"] ^ 1}, 7),
           ("witness names another record", pn, fd.make_provision(8, pn["binding"] ^ 1, 7, GOLD_P["binding"], KEY, 1, 1), 7),
           ("witness generation differs", pn, fd.make_provision(9, pn["binding"], 7, GOLD_P["binding"], KEY, 1, 1), 7),
           ("foreign tag does not compose to VALID", pn, fd.make_provision(8, pn["binding"], 7, GOLD_P["binding"], 5, 1, 1), 7)]
    for label, p_, w_, base in bad:
        if m.save_pair_valid(p_, w_, base):
            return f"accepted: {label}"
    pi, wi = independent_pair(GW, 8, 1790000500, 7, GOLD_P["binding"], 2)
    inv = fd.invalidate_profile_cxx(GOLD_P)
    wi = fd.make_provision(8, inv["binding"], 7, GOLD_P["binding"], KEY, 1, 2)
    if not m.invalidate_pair_valid(inv, wi, GOLD_P):
        return "the good invalidate pair"
    badi = [("payload changed", fp.seal_profile({**inv, "reg244": 0}), wi), ("not INVALIDATED", pn, wi), ("witness op SAVE", inv, fd.make_provision(8, inv["binding"], 7, GOLD_P["binding"], KEY, 1, 1)),
            ("witness names another record", inv, fd.make_provision(8, inv["binding"] ^ 1, 7, GOLD_P["binding"], KEY, 1, 2)),
            ("captured_epoch changed", fp.seal_profile({**inv, "captured_epoch": 1}), wi)]
    for label, p_, w_ in badi:
        if m.invalidate_pair_valid(p_, w_, GOLD_P):
            return f"accepted: {label}"
    return None


# =========================================== [8] plan_invalidate ===========================================================
def faithful_inv(m, pl, p, plen, wl, w, wlen, seen=0):
    in_ = m.InvalidatePlanInputs()
    in_.p_load, in_.p, in_.p_stored_len, in_.w_load, in_.w, in_.w_stored_len = pl, p, plen, wl, w, wlen
    in_.cls = fd.compose_profile_class(pl, p, wl, w, 0)[0]
    in_.read_anomaly, in_.unconfirmed, in_.seen_hw_gen, in_.target_id = 0, False, seen, p["binding"]
    return in_


@chk("plan_invalidate over every stored pair: only an effective VALID profile is invalidated; payload verbatim, generation + 1, flag bit0, captured_epoch kept, "
     "W-INV shaped witness; the FB-B0 transition validator accepts it; the guards refuse g = 0xFFFFFFFF and a seen floor at g + 1")
def c_inv_plan(m, fast):
    n = 0
    for pk in range(0, 10):
        for wk in range(0, 17):
            for seen in (0, 7, 8, 0xFFFFFFFF):
                n += 1
                if fast and n % 6:
                    continue
                pl, p, plen = _prof(pk)
                wl, w, wlen = _wit(wk, p)
                in_ = faithful_inv(m, pl, p, plen, wl, w, wlen, seen)
                plan = m.plan_invalidate(in_)
                cls = in_.cls
                wc = fd.classify_witness(wl, w)
                permitted = cls == fd.EPC_VALID and p["generation"] < 0xFFFFFFFF and p["generation"] + 1 > (w["hw_generation"] if wc == fd.W_VALID else 0) \
                    and p["generation"] + 1 > seen
                if (plan.code == m.PLAN_OK) != permitted:
                    return f"pk{pk} wk{wk} seen{seen}: class {cls}: {plan.code}"
                if not permitted:
                    if plan.op != 0 or plan.generation != 0 or str(plan.text) == "":
                        return f"refusal shape pk{pk} wk{wk}"
                    continue
                inv = fd.invalidate_profile_cxx(p)
                want_w = fd.make_provision(p["generation"] + 1, inv["binding"], p["generation"], p["binding"], KEY, 1, 2)
                a, b = fp.pack_profile(plan.p_new), fp.pack_profile(p)
                if plan.p_new != inv or plan.w_new != want_w or plan.generation != p["generation"] + 1 or plan.op != 2:
                    return f"pk{pk} wk{wk}: the pair"
                if a[0:8] != b[0:8] or a[12:16] != b[12:16] or a[18:88] != b[18:88] or not plan.p_new["flags"] & 1 or plan.p_new["captured_epoch"] != p["captured_epoch"]:
                    return f"pk{pk} wk{wk}: the payload must be preserved verbatim"
                if not fd.validate_transition(plan.w_new, w, (wl, wlen), plan.p_new, p, (pl, plen)):
                    return f"pk{pk} wk{wk}: validate_transition refuses"
    # W-INV: hw 8, prior 7, hw_binding the INVALIDATED golden binding, prior_binding the golden binding, op INVALIDATE
    pl, p, plen = _prof(1)
    wl, w, wlen = _wit(1, p)
    plan = m.plan_invalidate(faithful_inv(m, pl, p, plen, wl, w, wlen))
    if plan.w_new["binding"] != 0x9E8AEC8F7D7DF2D7 or plan.w_new["hw_binding"] != 0xF49A36C9C9720301 or plan.w_new["prior_binding"] != 0xD852A4FA2DF7DBA3:
        return f"W-INV vector: {plan.w_new['binding']:X}"
    return None


@chk("plan_invalidate: the overlay / anomaly / class / binding / generation refusals and their order; the named binding is the FULL 64-bit value")
def c_inv_plan_gates(m, fast):
    pl, p, plen = _prof(1)
    wl, w, wlen = _wit(1, p)

    def code(**kw):
        in_ = faithful_inv(m, pl, p, plen, wl, w, wlen)
        for k, v in kw.items():
            setattr(in_, k, v)
        return m.plan_invalidate(in_).code
    if code() != m.PLAN_OK or code(unconfirmed=True) != m.PLAN_UNCONFIRMED or code(read_anomaly=4) != m.PLAN_ANOMALY or code(cls=fd.EPC_INVALIDATED) != m.PLAN_CLASS:
        return "gates"
    if code(target_id=p["binding"] ^ 1) != m.PLAN_BINDING_CHANGED or code(target_id=p["binding"] ^ (1 << 63)) != m.PLAN_BINDING_CHANGED or code(target_id=p["binding"] & 0xFFFFFFFF) != m.PLAN_BINDING_CHANGED:
        return "the full binding must match"
    if code(unconfirmed=True, read_anomaly=4) != m.PLAN_UNCONFIRMED or code(read_anomaly=4, cls=fd.EPC_INVALIDATED) != m.PLAN_ANOMALY \
            or code(cls=fd.EPC_INVALIDATED, target_id=1) != m.PLAN_CLASS or code(target_id=1, seen_hw_gen=100) != m.PLAN_BINDING_CHANGED:
        return "order"
    if code(seen_hw_gen=8) != m.PLAN_GENERATION or code(seen_hw_gen=7) != m.PLAN_OK:
        return "seen floor"
    return None


# =========================================== [9] outcome texts =============================================================
def tr(w=(0, 0, 0, 0, 0), p=(0, 0, 3, 0, 0), adv=0, ref=0) -> fd.TxnResult:
    r = fd.TxnResult()
    r.w = fd.KeyReport(err=w[0], rb_class=w[1], outcome=w[2], us=w[3])
    r.p = fd.KeyReport(err=p[0], rb_class=p[1], outcome=p[2], us=p[3])
    r.witness_advanced, r.refusal = bool(adv), ref
    return r


@chk("outcome texts: every (op, TxnOutcome, refusal, witness_advanced) cell equals the hand-written wording (master 4.7 for SAVE, S2 4.4 for INVALIDATE)")
def c_outcome_cells(m, fast):
    S, V, RC = 1, 2, 3
    cells = [
        (S, 1, tr(w=(0, 1, 1, 10), p=(0, 1, 1, 20)), 7, 6, "SAVED - known-good profile generation 7 saved (verified this boot)"),
        (RC, 1, tr(w=(0, 1, 1, 10), p=(0, 1, 1, 20)), 4294967295, 0, "SAVED - known-good profile generation 4294967295 saved (verified this boot)"),
        (S, 2, tr(w=(0x1107, 2, 2, 5)), 8, 7, "SAVE NOT COMMITTED - storage refused the write (E1107); nothing changed"),
        (S, 2, tr(w=(0x1104, 2, 2, 5)), 8, 7, "SAVE NOT COMMITTED - storage refused the write (E1104); nothing changed"),
        (S, 2, tr(w=(0, 1, 1, 5), p=(0x1107, 2, 2, 5), adv=1), 8, 7, "SAVE NOT COMMITTED - witness advanced; profile unchanged; stored profile is now out of step - review and save again"),
        (S, 0, tr(w=(0x1102, 3, 0, 5)), 8, 7, "SAVE OUTCOME UNKNOWN - storage reported E1102/OTHER_BYTES; reboot the dongle (when no temporary operation is active) to re-verify; saving disabled until then"),
        (S, 0, tr(w=(0, 1, 0, 5)), 8, 7, "SAVE OUTCOME UNKNOWN - storage reported -/INTENDED; reboot the dongle (when no temporary operation is active) to re-verify; saving disabled until then"),
        (S, 0, tr(w=(0, 1, 1, 5), p=(0x1105, 5, 0, 5)), 8, 7, "SAVE OUTCOME UNKNOWN - storage reported E1105/WRONG_SIZE; reboot the dongle (when no temporary operation is active) to re-verify; saving disabled until then"),
        (S, 3, tr(ref=2), 8, 7, "SAVE REFUSED - previous save outcome unknown this boot - reboot to re-verify first"),
        (S, 3, tr(ref=3), 8, 7, "SAVE REFUSED - internal: built record did not validate; nothing written"),
        (S, 3, tr(ref=4), 8, 7, "SAVE REFUSED - storage unavailable - nothing saved"),
        (S, 3, tr(ref=5), 8, 7, "SAVE REFUSED - storage not healthy - nothing saved"),
        (S, 3, tr(ref=1), 8, 7, "SAVE REFUSED - internal: write refused for an unknown reason; nothing written"),
        (V, 1, tr(w=(0, 1, 1, 10), p=(0, 1, 1, 20)), 8, 7, "INVALIDATED - profile generation 7 is no longer usable (now INVALIDATED g8); payload kept for reference; save a new profile to re-enable"),
        (V, 2, tr(w=(0x1107, 2, 2, 5)), 8, 7, "INVALIDATE NOT COMMITTED - storage refused the write (E1107); profile still VALID g7"),
        (V, 2, tr(w=(0, 1, 1, 5), p=(0x1107, 2, 2, 5), adv=1), 8, 7, "INVALIDATE NOT COMMITTED for the profile record, but the generation record advanced: g7 is now STALE (unusable)"),
        (V, 0, tr(w=(0x1102, 3, 0, 5)), 8, 7, "INVALIDATE OUTCOME UNKNOWN - E1102/OTHER_BYTES; treat the profile as unusable; reboot to re-verify (Fallback Profile writes locked until reboot)"),
        (V, 3, tr(ref=2), 8, 7, "INVALIDATE REFUSED - previous Fallback Profile write outcome unknown this boot - reboot to re-verify first"),
        (V, 3, tr(ref=3), 8, 7, "INVALIDATE REFUSED - internal: built record did not validate; nothing written"),
        (V, 3, tr(ref=4), 8, 7, "INVALIDATE REFUSED - storage unavailable - nothing written"),
        (V, 3, tr(ref=5), 8, 7, "INVALIDATE REFUSED - storage not healthy - nothing written"),
        (0, 1, tr(), 8, 7, "INTERNAL - Fallback Profile dispatch context invalid; nothing written"),
        (7, 0, tr(), 8, 7, "INTERNAL - Fallback Profile dispatch context invalid; nothing written"),
    ]
    for op, o, r, g, pg, want in cells:
        got = str(m.txn_outcome_text(op, o, r, g, pg))
        if got != want:
            return f"{(op, o)}: {got!r} != {want!r}"
    # an UNKNOWN outcome that carries no per-key detail is never rendered as a success; unknown outcomes fail closed to UNKNOWN
    if not str(m.txn_outcome_text(S, 9, tr(), 1, 0)).startswith("SAVE OUTCOME UNKNOWN"):
        return "an unknown outcome value must read as UNKNOWN"
    return None


@chk("outcome texts: every text of every cell is <= 200 at the widest values, starts with a locked B9 prefix, matches no card pattern, never says failed / deferred / supervision")
def c_outcome_hygiene(m, fast):
    longest = 0
    for op in (1, 2, 3, 0, 5):
        for o in range(0, 5):
            for rb in range(0, 10):
                for adv in (0, 1):
                    for rf in range(0, 7):
                        r = tr(w=(-1, rb, 0, U32), p=(-1, rb, 0, U32), adv=adv, ref=rf)
                        t = str(m.txn_outcome_text(op, o, r, U32, 4294967294))
                        longest = max(longest, len(t))
                        if len(t) > 200 or not t.startswith(LOCKED_PREFIXES) or hazard(t) or not t.isascii():
                            return f"{(op, o, rb, adv, rf)}: {t!r}"
    return None if longest <= 200 else "too long"


@chk("B2 werr / us (D11): first_non_ok is the first non-zero of the witness then the profile error (negative IDF codes are u32), total_us the wrapping sum; b2_text renders them")
def c_werr_us(m, fast):
    for a, b, want in ((0, 0, 0), (5, 0, 5), (0, 5, 5), (-1, 7, U32), (0x1107, 0x1104, 0x1107), (0, -1, U32), (-2147483647, 0, 0x80000001)):
        if m.first_non_ok(a, b) != want:
            return f"first_non_ok {a, b}"
    for a, b in ((0, 0), (5, 7), (U32, 1), (U32, U32), (2 ** 31, 2 ** 31)):
        if m.total_us(a, b) != (a + b) & U32:
            return f"total_us {a, b}"
    w = fd.make_provision(7, GOLD_P["binding"], 6, 0x1122334455667788, KEY, 1, fd.PROV_OP_SAVE)
    b2 = str(cap.b2_text(0, GOLD_P, 0, w, 0, m.first_non_ok(0x1107, 0), m.total_us(1200, 34)))
    if not b2.endswith(";werr=E1107;us=1234") or len(b2) > 200:
        return b2
    if not str(cap.b2_text(0, GOLD_P, 0, w, 0, m.first_non_ok(0, 0), m.total_us(0, 0))).endswith(";werr=-;us=-"):
        return "zero renders -"
    return None


@chk("log lines: txn_log_text carries op, generation, both keys, the total and the outcome; the forensic REPLACE CORRUPT lines carry the discarded record; all <= 200")
def c_logs(m, fast):
    r = tr(w=(0x1107, 2, 2, 12), p=(0, 0, 3, 0))
    t = str(m.txn_log_text(3, 2, r, 12))
    # FB-B2 SEM-6: the long operation name and total_us= of S2 Part B 1.9 (before: txn=RC ... us=12 ... us=0 tot=12; the per-key us= fields are not printed:
    # with the long names the line would be 213 characters at the widest values, over the 200-character TextBuf)
    if t != "txn=REPLACE_CORRUPT gen=12 w:err=E1107 rb=PRIOR out=NOT_COMMITTED p:err=- rb=NOT_READ out=NOT_ATTEMPTED total_us=12 -> NOT_COMMITTED":
        return t
    for op, name in ((1, "SAVE"), (2, "INVALIDATE"), (3, "REPLACE_CORRUPT"), (0, "-"), (4, "-"), (255, "-")):
        if not str(m.txn_log_text(op, 1, r, 7)).startswith(f"txn={name} gen=7 ") or m.txn_op_name(op) != name:
            return f"operation name of {op}"
    worst = str(m.txn_log_text(1, 3, tr(w=(-1, 4, 3, U32), p=(-1, 4, 3, U32)), U32))
    if len(worst) > 200:
        return f"{len(worst)}"
    p = GOLD_P
    raw = fp.pack_profile(p)
    p0, p1 = str(m.replace_corrupt_log_text(LOAD_OK, p, 0, 0)), str(m.replace_corrupt_log_text(LOAD_OK, p, 0, 1))
    if p0 != "REPLACE CORRUPT discards stored profile bytes 0-47: " + raw[:48].hex().upper() or p1 != "REPLACE CORRUPT discards stored profile bytes 48-95: " + raw[48:].hex().upper():
        return "forensic parts"
    if str(m.replace_corrupt_log_text(LOAD_WSZ, p, 40, 0)) != "REPLACE CORRUPT discards a stored profile of the wrong size, stored length 40" or \
            str(m.replace_corrupt_log_text(LOAD_WSZ, p, 40, 1)) != "" or str(m.replace_corrupt_log_text(LOAD_ABSENT, p, 0, 0)) != "" or str(m.replace_corrupt_log_text(LOAD_OK, p, 0, 2)) != "":
        return "forensic wrong size / empty cases"
    return None


@chk("every SAVE-final refusal builder: the documented wording, the REVIEW prefix never leaks, <= 200 at the widest words")
def c_final_texts(m, fast):
    allf, zero = [65535] * 31, [0] * 31
    want = [(m.save_read_fail_text(cap.READ_EXCEPTION, 2, 2), "SAVE REFUSED - inverter returned exception code 0x02 on registers 241/53; profile unchanged"),
            (m.save_read_fail_text(cap.READ_NO_RESPONSE, 1, 0), "SAVE REFUSED - no response reading registers 230/3; profile unchanged"),
            (m.save_read_fail_text(cap.READ_NOT_SENT, 4, 0), "SAVE REFUSED - read of registers 241/53 could not be queued; profile unchanged"),
            (m.save_read_fail_text(cap.READ_BOUNDED_WAIT, 3, 0), "SAVE REFUSED - read of registers 230/3 did not complete within 3 s; profile unchanged"),
            (m.save_read_fail_text(cap.READ_IDLE_TIMEOUT, 0, 0), "SAVE REFUSED - inverter bus stayed busy for 7 s; profile unchanged; review again"),
            (m.save_changed_during_read_text(GW, [0] + GW[1:]), "SAVE REFUSED - live configuration changed during the read (register 244: 2 then 0); profile unchanged"),
            (m.save_changed_since_review_text(GW, [GW[0], 501] + GW[2:]), "SAVE REFUSED - live configuration changed since Review (register 256: reviewed 8000, now 501); profile unchanged; review again"),
            (m.save_prior_changed_text(), "SAVE REFUSED - stored profile changed since Review; profile unchanged"),
            (m.save_generation_text(), "SAVE REFUSED - profile generation counter exhausted; profile unchanged"),
            (m.save_internal_record_text(), "SAVE REFUSED - internal: built record did not validate; nothing written"),
            (m.save_bus_quiet_text(), "SAVE REFUSED - inverter bus not quiet at commit; profile unchanged"),
            (m.save_class_text(0, 10), "SAVE REFUSED - stored profile UNREADABLE (ANOM); reboot to re-derive it (it will then read VALID, LOST or NOT_CAPTURED)"),
            (m.save_class_text(7, 0), "SAVE REFUSED - previous save outcome unknown this boot - reboot to re-verify first"),
            (m.save_class_text(9, 0), "SAVE REFUSED - stored profile state does not permit saving"),
            (m.save_l2_text(cap.capture_refusals([0] + GW[1:], 8000), [0] + GW[1:]), "SAVE REFUSED - 244=0 Allow Export - V1 can only save a Zero Export profile; profile unchanged")]
    for got, exp in want:
        if str(got) != exp:
            return f"{str(got)!r} != {exp!r}"
    for t in (m.save_changed_since_review_text(allf, zero), m.save_changed_during_read_text(allf, zero), m.save_l2_text(cap.capture_refusals(allf, 8000), allf)):
        if len(t) > 200 or not str(t).startswith("SAVE REFUSED - "):
            return f"{str(t)[:80]!r} {len(t)}"
    return None


@chk("the SAVE acceptance line is the documented one and every gate text is distinct from it")
def c_progress_text(m, fast):
    t = str(m.save_in_progress_text())
    if t != "save in progress - re-reading live configuration":
        return t
    for c in SAVE_ORDER:
        if str(run_save(m, Sc(fail=[c]))[0].text) == t:
            return c
    return None


@chk("the B9 prefix set: every SAVE / INVALIDATE gate and final text starts with a locked prefix; the in-flight / refusal texts of every gate code too")
def c_prefixes(m, fast):
    seen = set()
    for c in SAVE_ORDER:
        r, _ = run_save(m, Sc(fail=[c]))
        seen.add(str(r.text).split(" - ")[0])
        if not str(r.text).startswith(LOCKED_PREFIXES):
            return f"{c}: {r.text!r}"
    for c in INV_ORDER:
        r, _ = run_inv(m, {c})
        seen.add(str(r.text).split(" - ")[0])
        if not str(r.text).startswith(LOCKED_PREFIXES):
            return f"{c}: {r.text!r}"
    return None if {"SAVE REFUSED", "INVALIDATE REFUSED", "REFUSED"} <= seen else str(seen)


# =========================================== FB-B2 hdr-fix: the new behavioural checks ===================================
HZ_RE = re.compile("fail|defer", re.I)
ECHO_BAD = re.compile(r"(?i)fail|defer")


def oracle_echo(b: bytes, n: int) -> str:
    """F2 oracle, written independently of the mirror (a regex over the sanitised text, not str.find): sanitise the first min(n, 28) bytes, mask every
    case-insensitive 'fail' / 'defer' (the matched letters only), publish the first 24."""
    s = "".join(chr(c) if (48 <= c <= 57 or 65 <= c <= 90 or 97 <= c <= 122 or c == 95) else "?" for c in b[:min(n, 28)])
    out = list(s)
    for mt in HZ_RE.finditer(s):
        out[mt.start():mt.end()] = ["?"] * (mt.end() - mt.start())
    return "".join(out[:24])


@chk("F2 the echo of an unsupported action never publishes the words failed / deferred: every case-insensitive 'fail' / 'defer' of the SANITISED token becomes '?', a "
     "word cut by the 24-byte cut is masked as far as visible; equals a regex oracle for both overloads, explicit lengths and NULs, exhaustively over a small alphabet, "
     "over random hazard-rich tokens, and no echo matches a card regex (re.I)")
def c_echo_mask(m, fast):
    pre = "REFUSED - unsupported action '"
    named = {"failed": "????ed", "FAILED": "????ED", "Failed": "????ed", "fAiLeD": "????eD", "deferred": "?????red", "DEFERRED": "?????RED", "xDeFeRrEdx": "x?????rEdx",
             "failfail": "????" "????", "faildefer": "????" "?????", "failure": "????ure", "fai": "fai", "def": "def", "efer": "efer", "fa il": "fa?il", "fail\0failed": "?????????ed",
             "x" * 20 + "failed": "x" * 20 + "????", "x" * 21 + "failed": "x" * 21 + "???", "x" * 22 + "failed": "x" * 22 + "??", "x" * 23 + "failed": "x" * 23 + "?",
             "x" * 24 + "failed": "x" * 24, "x" * 23 + "deferred": "x" * 23 + "?", "x" * 20 + "deferred": "x" * 20 + "????", "x" * 23 + "fox": "x" * 23 + "f",
             "x" * 23 + "fa": "x" * 23 + "f", "x" * 22 + "fai": "x" * 22 + "fa", "x" * 25 + "x": "x" * 24, "\xe9fail": "??" "????", "FAIL_DEFER": "????_?????"}
    for tok, want in named.items():
        b = tok.encode("utf-8")
        if str(m.unsupported_action_text(tok, len(b))) != pre + want + "'":
            return f"explicit {tok!r}: {str(m.unsupported_action_text(tok, len(b)))!r} != {want!r}"
        cut = tok.split("\0")[0]
        if str(m.unsupported_action_text(tok)) != pre + oracle_echo(cut.encode("utf-8"), len(cut.encode("utf-8"))) + "'":
            return f"NUL-terminated {tok!r}"
        if str(m.action_refusal_text(0, tok, len(b))) != pre + want + "'":
            return f"action_refusal_text {tok!r}"
    # an explicit length cuts the token: an occurrence cut by the LENGTH (not by the 24-byte cut) is not an occurrence
    for tok, n, want in (("failed", 3, "fai"), ("failed", 4, "????"), ("failed", 5, "????e"), ("deferred", 4, "defe"), ("deferred", 5, "?????"), ("failed", 0, ""),
                         ("x" * 23 + "deferred", 24, "x" * 23 + "d"), ("x" * 23 + "deferred", 27, "x" * 23 + "d"), ("x" * 23 + "deferred", 28, "x" * 23 + "?")):
        if str(m.unsupported_action_text(tok, n)) != pre + want + "'":
            return f"cut {tok!r} to {n}: {str(m.unsupported_action_text(tok, n))!r}"
    bad = []

    def verify(b: bytes, n: int) -> None:
        got = str(m.unsupported_action_text(b, n))
        want = pre + oracle_echo(b, n) + "'"
        if got != want or ECHO_BAD.search(got) or hazard(got):
            bad.append((b[:40], n, got, want))
        cut = b.split(b"\0")[0]
        got2 = str(m.unsupported_action_text(b))
        want2 = pre + oracle_echo(cut, min(len(cut), 29)) + "'"
        if got2 != want2 or ECHO_BAD.search(got2):
            bad.append((b[:40], "NUL-terminated", got2, want2))
    alphabet = "faildeFDx"
    for ln in range(0, (4 if fast else 5) + 1):
        for combo in itertools.product(alphabet, repeat=ln):
            b = "".join(combo).encode()
            verify(b, len(b))
            if bad:
                return str(bad[:2])
    rng = random.Random(21)
    pieces = ["fail", "FAIL", "Fail", "fAiL", "defer", "DEFER", "dEfEr", "Defer", "ed", "red", "x", "_", "a", "7", " ", "fai", "def", "il", "fer", "\0", "\xe9", "'"]
    for _ in range(600 if fast else 6000):
        b = "".join(rng.choice(pieces) for _ in range(rng.randrange(1, 12))).encode("utf-8")
        verify(b, len(b))
        verify(b, rng.randrange(0, len(b) + 1))
        if bad:
            return str(bad[:2])
    return None


HI_LO_FLIPS = (1 << 63, 1 << 32, 0xFFFFFFFF00000000, 0x8000000100000000, (1 << 63) | 1, 1, 1 << 31, 0xFFFFFFFF)
HI_LO_VARIANTS = [("xor", f_) for f_ in HI_LO_FLIPS] + [("lo", 0), ("hi", 0)]


def vary(b: int, variant) -> int:
    """A 64-bit id that differs from b in one word only: an XOR flip, only the LOW 32 bits kept, or only the HIGH 32 bits kept."""
    kind, arg = variant
    return b ^ arg if kind == "xor" else (b & U32) if kind == "lo" else (b >> 32) << 32


@chk("SEM-1 ids / bindings that differ ONLY in the high 32 bits (or only in the low 32) are different: G6 (outranking the phrase), I9, plan_save's candidate prior binding "
     "(VALID, INVALIDATED, CORRUPT raw fingerprint, wrong size) and plan_invalidate's binding re-check - the full 64 bits decide")
def c_hi_lo_ids(m, fast):
    # G6: the target id and the candidate id differ in one word only
    for flip in HI_LO_FLIPS:
        for who in ("target", "candidate"):
            for phrase_ok in (True, False):
                si, a, t, c, g, _ = build_save(m, Sc())
                if who == "target":
                    t = hx(ID ^ flip)
                else:
                    si.cand_id = ID ^ flip
                if not phrase_ok:
                    c = ""
                r = m.save_gate_decide(si, a, len(a), t, len(t), c, len(c), g)
                if r.code != m.SG_ID_MISMATCH:
                    return f"G6 flip {flip:X} ({who}, phrase_ok={phrase_ok}): {r.code}"
    si, a, t, c, g, _ = build_save(m, Sc())
    if m.save_gate_decide(si, a, len(a), t, len(t), c, len(c), g).code != m.SG_ACCEPT:
        return "G6 control"
    # I9: the operator names a binding that differs only in one word (the phrase carries the named id, so I3 / I4 pass)
    for variant in HI_LO_VARIANTS:
        in_, a, t, c = build_inv(m, set())
        t = hx(vary(in_.p["binding"], variant))
        c = f"INVALIDATE {t}"
        r = m.invalidate_gate_decide(in_, a, len(a), t, len(t), c, len(c))
        if r.code != m.IG_ID_MISMATCH:
            return f"I9 named {t} ({variant}): {r.code}"
    # plan_save: the candidate's bound prior binding
    for pk in (1, 2, 3, 4, 5, 9):
        pl, p, plen = _prof(pk)
        wl, w, wlen = _wit(1, p)
        if m.plan_save(faithful_save(m, pl, p, plen, wl, w, wlen)).code != m.PLAN_OK:
            return f"plan_save control pk{pk}"
        for variant in HI_LO_VARIANTS:
            in_ = faithful_save(m, pl, p, plen, wl, w, wlen)
            changed = vary(in_.cand_prior_binding, variant)
            if changed == in_.cand_prior_binding:
                continue  # nothing to change (a wrong-size prior's 'binding' is a small stored length)
            in_.cand_prior_binding = changed
            if m.plan_save(in_).code != m.PLAN_PRIOR_CHANGED:
                return f"plan_save pk{pk} {variant}: {m.plan_save(in_).code}"
    # plan_invalidate: the binding re-check against the fresh read
    pl, p, plen = _prof(1)
    wl, w, wlen = _wit(1, p)
    for variant in HI_LO_VARIANTS:
        in_ = faithful_inv(m, pl, p, plen, wl, w, wlen)
        in_.target_id = vary(p["binding"], variant)
        if m.plan_invalidate(in_).code != m.PLAN_BINDING_CHANGED:
            return f"plan_invalidate {variant}: {m.plan_invalidate(in_).code}"
    return None


@chk("SEM-1 G13: ANY difference of the writes fingerprint refuses (above, BELOW, across the uint32 wrap, across the signed boundary), equality never does")
def c_g13(m, fast):
    pairs = [(1000, 1000), (1000, 1001), (1000, 999), (U32, 0), (0, U32), (U32, U32), (0x80000000, 0x7FFFFFFF), (0x7FFFFFFF, 0x80000000), (0, 0), (5, 3), (3, 5), (0, 1),
             (1, 0), (U32 - 1, U32), (U32, U32 - 1), (0x10000, 0), (0, 0x10000), (0x12340000, 0x56780000)]
    rng = random.Random(13)
    pairs += [(rng.getrandbits(32), rng.getrandbits(32)) for _ in range(150 if fast else 2000)]
    pairs += [(x, x) for x in (rng.getrandbits(32) for _ in range(50))]
    for cand, now in pairs:
        si, a, t, c, g, _ = build_save(m, Sc())
        si.cand_writes_fp, si.writes_fp_now = cand, now
        r = m.save_gate_decide(si, a, len(a), t, len(t), c, len(c), g)
        want = m.SG_ACCEPT if cand == now else m.SG_WRITES
        if r.code != want:
            return f"reviewed {cand:#x} now {now:#x}: {r.code} != {want}"
    return None


@chk("SEM-2 only a VALID witness' high-water counts: a corrupt / wrong-size / absent witness whose hw field is huge never refuses (plan_invalidate, I10, plan_save); a VALID "
     "witness at hw g+1 / g+3 does (the class forced to VALID) - and a lagging witness never does")
def c_witness_hw(m, fast):
    pl, p, plen = _prof(1)
    for wk in (14, 15, 16, 3, 4, 0, 1, 2, 12):
        wl, w, wlen = _wit(wk, p)
        plan = m.plan_invalidate(faithful_inv(m, pl, p, plen, wl, w, wlen))
        if plan.code != m.PLAN_OK or plan.generation != 8:
            return f"plan_invalidate witness kind {wk}: {plan.code} g{plan.generation}"
        sp = m.plan_save(faithful_save(m, pl, p, plen, wl, w, wlen))
        if sp.code != m.PLAN_OK or sp.generation != 8:
            return f"plan_save witness kind {wk}: {sp.code} g{sp.generation}"
        in_, a, t, c = build_inv(m, set())
        in_.w_load, in_.w, in_.cls = wl, w, fd.compose_profile_class(pl, p, wl, w, 0)[0]
        if m.invalidate_gate_decide(in_, a, len(a), t, len(t), c, len(c)).code != m.IG_ACCEPT:
            return f"I10 witness kind {wk}: {m.invalidate_gate_decide(in_, a, len(a), t, len(t), c, len(c)).code}"
    for wk in (8, 9):  # a VALID witness ahead of the profile: its hw counts (the class is forced to VALID, as a stale mirror could carry)
        wl, w, wlen = _wit(wk, p)
        in_ = faithful_inv(m, pl, p, plen, wl, w, wlen)
        in_.cls = fd.EPC_VALID
        if m.plan_invalidate(in_).code != m.PLAN_GENERATION:
            return f"plan_invalidate VALID witness kind {wk}: {m.plan_invalidate(in_).code}"
        gi, a, t, c = build_inv(m, set())
        gi.w_load, gi.w, gi.cls = wl, w, fd.EPC_VALID
        if m.invalidate_gate_decide(gi, a, len(a), t, len(t), c, len(c)).code != m.IG_GENERATION:
            return f"I10 VALID witness kind {wk}: {m.invalidate_gate_decide(gi, a, len(a), t, len(t), c, len(c)).code}"
    return None


@chk("SEM-3 the BUS refusal names the lease that owns the write lock: '(Free Power)' / '(Dump to Grid)' when the lock is held ALONE by an ACTIVE lease, '(manual write)' when "
     "nobody else claims it, the plain owner when another busy flag is set")
def c_lease_owner(m, fast):
    pre, post = "SAVE REFUSED - another inverter transaction is in progress (", "); try again shortly"

    def lock(g):
        g.bus.manual_write_in_progress = True

    def fp_lease(g):
        g.fp.free_power_marker_boot_load, g.fp.free_power_snapshot_valid, g.fp.free_power_marker_state, g.fp.free_power_active_persisted = 0, True, 1, True

    def dump_lease(g):
        g.dump.dump_marker_boot_load, g.dump.dump_snapshot_valid, g.dump.dump_marker_state, g.dump.dump_active_persisted = 0, True, 1, True
    cases = [("lock + active Free Power lease", [lock, fp_lease], "Free Power"), ("lock + active Dump lease", [lock, dump_lease], "Dump to Grid"),
             ("lock alone", [lock], "manual write"), ("lock + both leases (Free Power first)", [lock, fp_lease, dump_lease], "Free Power"),
             ("lock + lease + a clock correction", [lock, fp_lease, lambda g: setattr(g.bus, "correction_in_progress", True)], "clock correction"),
             ("lock + Free Power lease + a Dump operation flag", [lock, fp_lease, lambda g: setattr(g.bus, "dump_operation_in_progress", True)], "Dump to Grid"),
             ("lock + Dump lease + a Register 244 apply", [lock, dump_lease, lambda g: setattr(g.bus, "reg244_apply_in_progress", True)], "Register 244 test")]
    for label, steps, owner in cases:
        si, a, t, c, g, _ = build_save(m, Sc())
        for s in steps:
            s(g)
        r = m.save_gate_decide(si, a, len(a), t, len(t), c, len(c), g)
        if r.code != m.SG_BUS or str(r.text) != pre + owner + post:
            return f"{label}: {r.code} {str(r.text)!r}"
        gr = cap.gate_decide(g, cap.ProbeResults())
        if str(m.save_gate_refusal_text(gr, g)) != pre + owner + post:
            return f"{label}: save_gate_refusal_text {str(m.save_gate_refusal_text(gr, g))!r}"
    return None


# SEM-4: the fields whose in-struct DEFAULT must refuse on its own (the all-pass input with that one field put back to its default)
DEFAULT_FIELDS = (
    ("SaveGateInputs", "arm_was_on", "SG_ARM_OFF"), ("SaveGateInputs", "cand_valid", "SG_NO_CANDIDATE"), ("SaveGateInputs", "cand_saveable", "SG_NO_CANDIDATE"),
    ("SaveGateInputs", "cand_id", "SG_NO_CANDIDATE"), ("SaveGateInputs", "cand_ms", "SG_EXPIRED"), ("SaveGateInputs", "cand_writes_fp", "SG_WRITES"),
    ("SaveGateInputs", "writes_fp_now", "SG_WRITES"), ("SaveGateInputs", "boot_loaded", "SG_NOT_LOADED"), ("SaveGateInputs", "unconfirmed", "SG_UNCONFIRMED"),
    ("SaveGateInputs", "read_anomaly", "SG_ANOMALY"), ("SaveGateInputs", "hb_ok", "SG_HB"), ("SaveGateInputs", "time_trusted", "SG_TIME"),
    ("InvalidateGateInputs", "arm_was_on", "IG_ARM_OFF"), ("InvalidateGateInputs", "boot_loaded", "IG_NOT_LOADED"), ("InvalidateGateInputs", "read_anomaly", "IG_ANOMALY"),
    ("InvalidateGateInputs", "unconfirmed", "IG_UNCONFIRMED"), ("InvalidateGateInputs", "cls", "IG_CLASS"), ("InvalidateGateInputs", "p_load", "IG_ID_MISMATCH"),
    ("InvalidateGateInputs", "p", "IG_ID_MISMATCH"), ("InvalidateGateInputs", "seen_hw_gen", "IG_GENERATION"), ("InvalidateGateInputs", "tx_buffer_empty", "IG_BUS"),
    ("InvalidateGateInputs", "tx_blocked", "IG_BUS"), ("InvalidateGateInputs", "fbs_slot", "IG_FBS"),
    ("SavePlanInputs", "p_load", "PLAN_PRIOR_CHANGED"), ("SavePlanInputs", "p", "PLAN_PRIOR_CHANGED"), ("SavePlanInputs", "cls", "PLAN_PRIOR_CHANGED"),
    ("SavePlanInputs", "read_anomaly", "PLAN_ANOMALY"), ("SavePlanInputs", "unconfirmed", "PLAN_UNCONFIRMED"), ("SavePlanInputs", "seen_hw_gen", "PLAN_GENERATION"),
    ("SavePlanInputs", "cand_prior_class", "PLAN_PRIOR_CHANGED"), ("SavePlanInputs", "cand_prior_gen", "PLAN_PRIOR_CHANGED"),
    ("SavePlanInputs", "cand_prior_binding", "PLAN_PRIOR_CHANGED"), ("SavePlanInputs", "captured_epoch", "PLAN_CLOCK"),
    ("InvalidatePlanInputs", "p_load", "PLAN_BINDING_CHANGED"), ("InvalidatePlanInputs", "p", "PLAN_BINDING_CHANGED"), ("InvalidatePlanInputs", "cls", "PLAN_CLASS"),
    ("InvalidatePlanInputs", "read_anomaly", "PLAN_ANOMALY"), ("InvalidatePlanInputs", "unconfirmed", "PLAN_UNCONFIRMED"),
    ("InvalidatePlanInputs", "seen_hw_gen", "PLAN_GENERATION"), ("InvalidatePlanInputs", "target_id", "PLAN_BINDING_CHANGED"))


@chk("SEM-4 every fail-closed default refuses on its own: the all-pass input with ONE field (hb_ok, time_trusted, boot_loaded, unconfirmed, read_anomaly, seen_hw_gen, "
     "tx_blocked, ...) put back to its dataclass default is refused with the documented code, in all four decisions")
def c_defaults_refuse(m, fast):
    bad = []
    for struct, fld, expect in DEFAULT_FIELDS:
        default = getattr(getattr(m, struct)(), fld)
        if struct == "SaveGateInputs":
            si, a, t, c, g, _ = build_save(m, Sc())
            si.now_ms = si.cand_ms  # age 0: a default (0) birth time is then expired, not wrapped back into the TTL
            if m.save_gate_decide(si, a, len(a), t, len(t), c, len(c), g).code != m.SG_ACCEPT:
                return "the SAVE gate all-pass control"
            setattr(si, fld, default)
            got = m.save_gate_decide(si, a, len(a), t, len(t), c, len(c), g).code
        elif struct == "InvalidateGateInputs":
            in_, a, t, c = build_inv(m, set())
            if m.invalidate_gate_decide(in_, a, len(a), t, len(t), c, len(c)).code != m.IG_ACCEPT:
                return "the INVALIDATE gate all-pass control"
            setattr(in_, fld, default)
            got = m.invalidate_gate_decide(in_, a, len(a), t, len(t), c, len(c)).code
        elif struct == "SavePlanInputs":
            pl, p, plen = _prof(1)
            wl, w, wlen = _wit(1, p)
            in_ = faithful_save(m, pl, p, plen, wl, w, wlen)
            if m.plan_save(in_).code != m.PLAN_OK:
                return "the SAVE plan all-pass control"
            setattr(in_, fld, default)
            got = m.plan_save(in_).code
        else:
            pl, p, plen = _prof(1)
            wl, w, wlen = _wit(1, p)
            in_ = faithful_inv(m, pl, p, plen, wl, w, wlen)
            if m.plan_invalidate(in_).code != m.PLAN_OK:
                return "the INVALIDATE plan all-pass control"
            setattr(in_, fld, default)
            got = m.plan_invalidate(in_).code
        if got != getattr(m, expect):
            bad.append((struct, fld, got, expect))
    return str(bad[:4]) if bad else None


@chk("AW-5 every scalar field of every POD dataclass declares the C type of its header field in CTYPES (uint8_t / uint32_t / uint64_t / bool; the words array its element "
     "type), and the strict simulator's PodValue wraps a store to that width: a 70-bit value stored into a uint8_t / uint32_t / uint64_t field is truncated like C++, a bool stays a bool")
def c_ctypes(m, fast):
    header = HEADER_PATH.read_text(encoding="utf-8")
    code = re.sub(r"//[^\n]*", "", header[:header.index("// ---- GOLDENS-BEGIN ----")])
    structs = re.findall(r"^struct (\w+) \{", code, re.M)
    sys.path.insert(0, str(ROOT / "registry" / "tests"))
    import _fbb1_fbcap as FB  # noqa: E402 - the strict firmware simulator's namespace adapter (lazy: only this check needs it)
    v = (1 << 70) + (1 << 40) + (1 << 20) + 0x1B7
    wrapped = {"uint8_t": 0xB7, "uint32_t": (1 << 20) + 0x1B7, "uint64_t": (1 << 40) + (1 << 20) + 0x1B7, "bool": True, "uint16_t": 0x1B7}
    n_fields = 0
    for name in structs:
        body = re.search(rf"^struct {name} \{{(.*?)^\}};", code, re.M | re.S).group(1)
        want = {fld: ty for ty, fld in re.findall(r"^\s+(uint8_t|uint32_t|uint64_t|bool)\s+(\w+)(?:\{\})?(?: = [^;]+)?;", body, re.M)}
        if name == "SavePlanInputs":
            want["words"] = "uint16_t"  # CaptureWords words{}: std::array<uint16_t, 31>
        cls = getattr(m, name)
        got = dict(getattr(cls, "CTYPES", {}))
        if got != want:
            return f"{name}: CTYPES {got} != the header's {want}"
        pv = FB.PodValue(cls(), None)
        for fld, ct in want.items():
            n_fields += 1
            if fld == "words":
                pv.words[3] = v
                if pv.words[3] != wrapped["uint16_t"]:
                    return f"{name}.words[3]: {pv.words[3]}"
                continue
            setattr(pv, fld, v)
            if getattr(pv, fld) != wrapped[ct] or (ct == "bool" and getattr(pv, fld) is not True):
                return f"{name}.{fld} ({ct}): stored {v}, read {getattr(pv, fld)}"
    return None if n_fields >= 55 else f"only {n_fields} fields"


@chk("SEM-6 the log line is exactly 'txn=<SAVE|INVALIDATE|REPLACE_CORRUPT> gen=<n> w:err=.. rb=.. out=.. p:err=.. rb=.. out=.. total_us=<n> -> <TxnOutcome>' for every op, outcome, "
     "readback class and key outcome at the widest values: complete (never cut at the TextBuf), total_us the wrapping sum, no per-key us=")
def c_log_format(m, fast):
    rx = re.compile(r"txn=(SAVE|INVALIDATE|REPLACE_CORRUPT|-) gen=(\d+) w:err=(-|E[0-9A-F]+) rb=([\w?]+) out=([\w?]+) p:err=(-|E[0-9A-F]+) rb=([\w?]+) out=([\w?]+) total_us=(\d+) -> ([\w?]+)")
    combos = ((0, 0), (2, 3), (4, 4), (1, 0)) if fast else tuple(itertools.product(range(0, 5), repeat=2))
    for op in (1, 2, 3, 0, 5):
        for o in range(0, 5):
            for rb in range(0, 10):
                for wo, po in combos:
                    t = str(m.txn_log_text(op, o, tr(w=(-1, rb, wo, U32), p=(-1, rb, po, 5)), U32))
                    mt = rx.fullmatch(t)
                    if not mt or int(mt.group(2)) != U32 or int(mt.group(9)) != (U32 + 5) & U32 or len(t) > 200 or not t.endswith(" -> " + m.txn_name(o)):
                        return f"{(op, o, rb, wo, po)}: {len(t)} {t!r}"
    return None


# =========================================== [11] the runner of the checks ================================================
def run_battery(mod, fast: bool) -> list[tuple[str, str]]:
    out = []
    for name, fn in CHECKS:
        try:
            detail = fn(mod, fast)
        except Exception as exc:  # a broken mirror may raise anywhere: that is a detection
            detail = f"raised {type(exc).__name__}: {exc}"
        if detail is not None:
            out.append((name, detail))
    return out


def load_mirror(text: str, label: str):
    name = f"fallback_save_mut_{abs(hash(label)) % 10 ** 8}"
    spec = importlib.util.spec_from_loader(name, loader=None)
    mod = importlib.util.module_from_spec(spec)
    mod.__file__ = str(MIRROR_PATH)
    sys.modules[name] = mod  # dataclasses resolves annotations through sys.modules
    try:
        exec(compile(text, f"<mutant {label}>", "exec"), mod.__dict__)
    finally:
        sys.modules.pop(name, None)
    return mod


# the mutants: (label, old, new) - `old` occurs exactly once in registry/fallback_save.py
MIRROR_MUTANTS = [
    ("token: lower case accepted", '    if exact(action, n, "SAVE"):', '    if exact(action, n, "SAVE") or exact(action, n, "save"):'),
    ("token: a prefix accepted", '    if exact(action, n, "INVALIDATE"):', '    if starts_with(action, n, "INVALIDATE"):'),
    ("token: RESTORE is SAVE", '    if exact(action, n, "RESTORE"):\n        return ACT_RESTORE', '    if exact(action, n, "RESTORE"):\n        return ACT_SAVE'),
    ("router: SAVE routes to INVALIDATE", "    return action_token(action, n) == ACT_INVALIDATE", "    return action_token(action, n) != ACT_SAVE"),
    ("hex: lower case accepted", "    return 48 <= c <= 57 or 65 <= c <= 70", "    return 48 <= c <= 57 or 65 <= c <= 70 or 97 <= c <= 102"),
    ("hex: 15 digits accepted", "    if b is None or n != ID_DIGITS or len(b) < ID_DIGITS:\n        return False\n    return all(hex_digit_ok(b[i]) for i in range(ID_DIGITS))",
     "    if b is None or n > ID_DIGITS:\n        return False\n    return all(hex_digit_ok(b[i]) for i in range(n))"),
    ("phrase: INVALIDATE takes REPLACE CORRUPT", '    if kind == PHRASE_SAVE and n > after and exact(b[after:], n - after, " REPLACE CORRUPT"):',
     '    if n > after and exact(b[after:], n - after, " REPLACE CORRUPT"):'),
    ("phrase: a trailing space accepted", "    if n == after:\n        p.kind = kind", "    if n == after or (n == after + 1 and b[after:after + 1] == b\" \"):\n        p.kind = kind"),
    ("phrase: lower-case verb accepted", '    if starts_with(confirmation, n, "SAVE "):', '    if starts_with(confirmation, n, "SAVE ") or starts_with(confirmation, n, "save "):'),
    ("expected: no REPLACE CORRUPT suffix", '    if kind == PHRASE_SAVE_REPLACE_CORRUPT:\n        text += " REPLACE CORRUPT"', "    pass"),
    ("phrase_equals: prefix match", "    if b is None or len(expected) == 0 or n != len(expected):\n        return False\n    return b[:n] == str(expected).encode(\"utf-8\")",
     "    if b is None or len(expected) == 0 or n < len(expected):\n        return False\n    return b[:len(expected)] == str(expected).encode(\"utf-8\")"),
    ("phrase_equals: empty matches", "    if b is None or len(expected) == 0 or n != len(expected):", "    if b is None or n != len(expected):"),
    # FB-B2: re-anchored for F2 (the 24-byte cut now happens in _echo_mask(..., ECHO_MAX) over the examined bytes; the same mutant, the same killer)
    ("echo: not truncated", '    return _echo_mask("".join(chr(b[i]) if echo_char_ok(b[i]) else "?" for i in range(m)), ECHO_MAX)',
     '    return _echo_mask("".join(chr(b[i]) if echo_char_ok(b[i]) else "?" for i in range(m)), 99)'),
    ("echo: a space is kept", "    return 65 <= c <= 90 or 97 <= c <= 122 or 48 <= c <= 57 or c == 95", "    return 65 <= c <= 90 or 97 <= c <= 122 or 48 <= c <= 57 or c == 95 or c == 32"),
    ("arm: exclusive boundary", "    return ((now_ms - on_ms) & U32) >= ARM_TTL_MS", "    return ((now_ms - on_ms) & U32) > ARM_TTL_MS"),
    ("arm: not wrap safe", "    return ((now_ms - on_ms) & U32) >= ARM_TTL_MS", "    return now_ms >= on_ms + ARM_TTL_MS"),
    ("integrity: any purpose", "    return bool(op_in_progress) and op_purpose == PURPOSE_SAVE", "    return bool(op_in_progress) and op_purpose != 0"),
    ("overlay: composed class wins", "    return fd.EPC_SAVE_UNCONFIRMED if unconfirmed else cls", "    return cls"),
    ("G1 skipped", "    if gr.code == cap.GATE_REFUSE_IN_FLIGHT:  # G1", "    if False:  # G1"),
    ("G1 touches more than the arm", "        r = save_refuse(r, SG_IN_FLIGHT, save_in_flight_text())\n        r.arm_off_only = True", "        r = save_refuse(r, SG_IN_FLIGHT, save_in_flight_text())"),
    ("G0 skipped", "    if token != ACT_SAVE:  # G0", "    if False:  # G0"),
    ("G2 skipped", "    if not inp.arm_was_on:  # G2", "    if False:  # G2"),
    ("G3 id-0 trap", "    if not inp.cand_valid or not inp.cand_saveable or inp.cand_id == 0:  # G3", "    if not inp.cand_valid or not inp.cand_saveable:  # G3"),
    ("G3 saveable ignored", "    if not inp.cand_valid or not inp.cand_saveable or inp.cand_id == 0:  # G3", "    if not inp.cand_valid or inp.cand_id == 0:  # G3"),
    ("G4 exclusive", "    if cap.candidate_expired(inp.now_ms, inp.cand_ms):  # G4", "    if ((inp.now_ms - inp.cand_ms) & U32) > cap.CANDIDATE_TTL_MS:  # G4"),
    ("G4 not wrap safe", "    if cap.candidate_expired(inp.now_ms, inp.cand_ms):  # G4", "    if inp.now_ms >= inp.cand_ms + cap.CANDIDATE_TTL_MS:  # G4"),
    ("G5 skipped", "    if not is_hex16(target_id, target_len):  # G5", "    if False:  # G5"),
    ("G6 skipped", "    if parse_hex16(target_id, target_len) != inp.cand_id:  # G6", "    if False:  # G6"),
    ("G7 plain phrase only", "    replace_ = fd.save_requires_replace_phrase(inp.cand_prior_class)", "    replace_ = False"),
    ("G7 skipped", "    if not phrase_equals(confirmation, confirmation_len, expected):  # G7", "    if False:  # G7"),
    ("G8 skipped", "    if not inp.boot_loaded:  # G8", "    if False:  # G8"),
    ("G9 skipped", "    if inp.unconfirmed:  # G9", "    if False:  # G9"),
    ("G9a skipped", "    if inp.read_anomaly != 0:  # G9a", "    if False:  # G9a"),
    ("G10 skipped", "    if not inp.hb_ok:  # G10", "    if False:  # G10"),
    ("G11 skipped", "    if not inp.time_trusted:  # G11", "    if False:  # G11"),
    ("G12 skipped", "    if gr.code == cap.GATE_REFUSE_ARMS:  # G12", "    if False:  # G12"),
    ("G13 skipped", "    if (inp.writes_fp_now & U32) != (inp.cand_writes_fp & U32):  # G13", "    if False:  # G13"),
    ("G14 reported as FBS", "code_of = {cap.GATE_REFUSE_BUS: SG_BUS,", "code_of = {cap.GATE_REFUSE_BUS: SG_FBS,"),
    ("unknown gate decision accepts", "    return save_refuse(r, SG_UNSET, save_internal_text())  # GATE_UNSET or an unknown code: never an accept", "    r.code = SG_ACCEPT\n    return r"),
    ("accept forgets replace_corrupt", "        r.replace_corrupt = replace_", "        r.replace_corrupt = False"),
    ("the SAVE gate masks the own holds", "                                 cap.gate_decide(g, cap.ProbeResults()))", "                                 cap.gate_decide(final_phase_inputs(g), cap.ProbeResults()))"),
    ("order: G9 before G8", "    if not inp.boot_loaded:  # G8\n        return save_refuse(r, SG_NOT_LOADED, save_not_loaded_text())\n    if inp.unconfirmed:  # G9\n        return save_refuse(r, SG_UNCONFIRMED, save_prior_unknown_text())",
     "    if inp.unconfirmed:  # G9\n        return save_refuse(r, SG_UNCONFIRMED, save_prior_unknown_text())\n    if not inp.boot_loaded:  # G8\n        return save_refuse(r, SG_NOT_LOADED, save_not_loaded_text())"),
    ("order: G13 before G12", "    if gr.code == cap.GATE_REFUSE_ARMS:  # G12\n        return save_refuse(r, SG_ARMS, save_arms_text())\n    if (inp.writes_fp_now & U32) != (inp.cand_writes_fp & U32):  # G13\n        return save_refuse(r, SG_WRITES, save_writes_text())",
     "    if (inp.writes_fp_now & U32) != (inp.cand_writes_fp & U32):  # G13\n        return save_refuse(r, SG_WRITES, save_writes_text())\n    if gr.code == cap.GATE_REFUSE_ARMS:  # G12\n        return save_refuse(r, SG_ARMS, save_arms_text())"),
    ("order: G4 before G3", "    if not inp.cand_valid or not inp.cand_saveable or inp.cand_id == 0:  # G3\n        return save_refuse(r, SG_NO_CANDIDATE, save_no_candidate_text())\n    if cap.candidate_expired(inp.now_ms, inp.cand_ms):  # G4\n        return save_refuse(r, SG_EXPIRED, save_expired_text())",
     "    if cap.candidate_expired(inp.now_ms, inp.cand_ms):  # G4\n        return save_refuse(r, SG_EXPIRED, save_expired_text())\n    if not inp.cand_valid or not inp.cand_saveable or inp.cand_id == 0:  # G3\n        return save_refuse(r, SG_NO_CANDIDATE, save_no_candidate_text())"),
    ("I1 skipped", "    if inp.bus.fallback_profile_op_in_progress or inp.bus.fallback_profile_capture_dispatch_running:  # I1", "    if False:  # I1"),
    ("I2 skipped", "    if not inp.arm_was_on:  # I2", "    if False:  # I2"),
    ("I4 SAVE verb", "    expected = expected_phrase(PHRASE_INVALIDATE, id_)", "    expected = expected_phrase(PHRASE_SAVE, id_)"),
    ("I6 skipped", "    if inp.read_anomaly != 0:  # I6", "    if False:  # I6"),
    ("I7 skipped", "    if inp.unconfirmed:  # I7", "    if False:  # I7"),
    ("I8 any saveable class", "    if not fd.invalidate_class_permitted(inp.cls):  # I8", "    if not fd.save_class_permitted(inp.cls):  # I8"),
    ("I9 skipped", "    if inp.p_load != fp.LOAD_OK or p[\"binding\"] != id_:  # I9", "    if False:  # I9"),
    ("I10 seen ignored", "p[\"generation\"], wc, w[\"hw_generation\"], inp.seen_hw_gen):  # I10", "p[\"generation\"], wc, w[\"hw_generation\"], 0):  # I10"),
    ("I11 skipped", "    if not invalidate_bus_idle(inp.bus, inp.tx_buffer_empty, inp.tx_blocked):  # I11", "    if False:  # I11"),
    ("I12 skipped", "    if not fd.fbs_slot_clear(inp.fbs_slot):  # I12", "    if False:  # I12"),
    ("bus idle ignores the transmit block", "    return bool((not cap.bus_busy(b)) and tx_buffer_empty and not tx_blocked)", "    return bool((not cap.bus_busy(b)) and tx_buffer_empty)"),
    ("bus idle ignores the busy flags", "    return bool((not cap.bus_busy(b)) and tx_buffer_empty and not tx_blocked)", "    return bool(tx_buffer_empty and not tx_blocked)"),
    ("mask forgets the write lock", "                  manual_write_in_progress=False)", "                  manual_write_in_progress=g.bus.manual_write_in_progress)"),
    ("mask forgets the dispatch", "fallback_profile_capture_dispatch_running=False,", "fallback_profile_capture_dispatch_running=g.bus.fallback_profile_capture_dispatch_running,"),
    ("mask clears a correction too", "                  manual_write_in_progress=False)", "                  manual_write_in_progress=False, correction_in_progress=False)"),
    ("final gate unmasked", "    f.gr = cap.gate_decide(m, pr)", "    f.gr = cap.gate_decide(g, pr)"),
    ("commit quiet: no op flag", "    return bool(op_in_progress and mutex_held and not correction_in_progress and tx_buffer_empty and not tx_blocked)",
     "    return bool(mutex_held and not correction_in_progress and tx_buffer_empty and not tx_blocked)"),
    ("commit quiet: no blocked check", "    return bool(op_in_progress and mutex_held and not correction_in_progress and tx_buffer_empty and not tx_blocked)",
     "    return bool(op_in_progress and mutex_held and not correction_in_progress and tx_buffer_empty)"),
    ("clock: zero epoch", "    return bool(time_trusted and (epoch & U32) != 0)", "    return bool(time_trusted)"),
    ("plan: class not compared", "    if inp.cls != inp.cand_prior_class or f.generation != inp.cand_prior_gen or f.binding != inp.cand_prior_binding:",
     "    if f.generation != inp.cand_prior_gen or f.binding != inp.cand_prior_binding:"),
    ("plan: overlay not refused", "    if inp.unconfirmed:\n        return plan_refuse(r, PLAN_UNCONFIRMED, save_prior_unknown_text())", "    pass"),
    ("plan: anomaly not refused", "    if inp.read_anomaly != 0:\n        return plan_refuse(r, PLAN_ANOMALY, save_anomaly_text())", "    pass"),
    ("plan: seen ignored", "fd.save_generation_base(pc, p[\"generation\"], wc, w[\"hw_generation\"], inp.seen_hw_gen)", "fd.save_generation_base(pc, p[\"generation\"], wc, w[\"hw_generation\"], 0)"),
    ("plan: no advance", "    gen = (base + 1) & U32", "    gen = base & U32"),
    ("plan: exhaustion not refused", "    if not fd.save_generation_available(base):\n        return plan_refuse(r, PLAN_GENERATION, save_generation_text())", "    pass"),
    ("plan: witness always names the prior", "p[\"generation\"] if authentic else 0, p[\"binding\"] if authentic else 0,\n                           fd.FALLBACK_PROFILE_KEY", "p[\"generation\"], p[\"binding\"],\n                           fd.FALLBACK_PROFILE_KEY"),
    ("plan: REPLACE CORRUPT as plain SAVE", "    op = fd.PROV_OP_REPLACE_CORRUPT if replace_ else fd.PROV_OP_SAVE", "    op = fd.PROV_OP_SAVE"),
    ("plan: epoch not stored", "    pn[\"captured_epoch\"] = inp.captured_epoch & U32", "    pn[\"captured_epoch\"] = 0"),
    ("plan: zero epoch accepted", "    if (inp.captured_epoch & U32) == 0:\n        return plan_refuse(r, PLAN_CLOCK, save_time_text())", "    pass"),
    ("plan: replace flag not cross-checked", "    if bool(inp.replace_corrupt) != replace_:\n        return plan_refuse(r, PLAN_CONTEXT, cap.internal_context_text())", "    pass"),
    ("invalidate plan: class not required", "    if not fd.invalidate_class_permitted(cls):\n        return plan_refuse(r, PLAN_CLASS, invalidate_class_now_text(cls))", "    pass"),
    ("invalidate plan: binding not compared", "    if inp.p_load != fp.LOAD_OK or p[\"binding\"] != (inp.target_id & U64):\n        return plan_refuse(r, PLAN_BINDING_CHANGED, invalidate_changed_text())", "    pass"),
    ("invalidate plan: unguarded", "    if not fp.profile_invalidate_permitted(p) or not fd.invalidate_generation_permitted(\n            p[\"generation\"], wc, w[\"hw_generation\"], inp.seen_hw_gen):\n        return plan_refuse(r, PLAN_GENERATION, invalidate_generation_text(p[\"generation\"] == fd.GENERATION_MAX))", "    pass"),
    ("invalidate plan: witness op SAVE", "                           fp.PROFILE_SCHEMA, fd.PROV_OP_INVALIDATE)\n    if not invalidate_pair_valid", "                           fp.PROFILE_SCHEMA, fd.PROV_OP_SAVE)\n    if not invalidate_pair_valid"),
    ("werr: profile first", "    return (err_w if err_w != 0 else err_p) & U32", "    return (err_p if err_p != 0 else err_w) & U32"),
    ("us: maximum", "    return (w_us + p_us) & U32", "    return max(w_us, p_us) & U32"),
    ("outcome: witness_advanced inverted", "        if r.witness_advanced:\n            return invalidate_witness_advanced_text", "        if not r.witness_advanced:\n            return invalidate_witness_advanced_text"),
    ("outcome: SAVED shows the prior generation", "    return invalidated_text(prior_generation, generation) if inv else saved_text(generation)", "    return invalidated_text(prior_generation, generation) if inv else saved_text(prior_generation)"),
    ("outcome: unknown always the witness", "    k = r.w if r.w.outcome == fd.KEY_UNKNOWN_REBOOT else r.p", "    k = r.w"),
    ("outcome: SAVED loses its clause", '(verified this boot)")', '")'),
    ("text: the acceptance line", '"save in progress - re-reading live configuration"', '"review in progress (read-only)"'),
    ("text: heartbeat names supervision", '"Home Assistant heartbeat is not stable;', '"Home Assistant supervision heartbeat is not stable;'),
    ("text: not committed says failed", '"SAVE NOT COMMITTED - storage refused the write', '"SAVE NOT COMMITTED - storage write failed'),
    ("text: phrase echo is not the expected one", "    return save_refused(\"confirmation phrase mismatch (expected '\" + str(expected) + \"')\")", "    return save_refused(\"confirmation phrase mismatch (expected 'SAVE')\")"),
    ("text: R244 loses its hint", ' + (" - press Restore Original (armed)" if slot == cap.SLOT_R244 else "")', ' + ""'),
    ("text: IDLE read failure loses its suffix", '        return save_refused("inverter bus stayed busy for 7 s; profile unchanged; review again")', '        return save_refused("inverter bus stayed busy for 7 s")'),
    # ---- F2: the masked echo
    ("echo F2: mask removed", '    return _echo_mask("".join(chr(b[i]) if echo_char_ok(b[i]) else "?" for i in range(m)), ECHO_MAX)',
     '    return "".join(chr(b[i]) if echo_char_ok(b[i]) else "?" for i in range(m))[:ECHO_MAX]'),
    ("echo F2: mask case-sensitive", "    low = t.lower()\n", "    low = t\n"),
    ("echo F2: mask applied after the truncation", "    m = min(n, ECHO_MAX + ECHO_LOOK, len(b))", "    m = min(n, ECHO_MAX, len(b))"),
    ("echo F2: the mask looks 3 bytes past the cut", "    m = min(n, ECHO_MAX + ECHO_LOOK, len(b))", "    m = min(n, ECHO_MAX + 3, len(b))"),
    ("echo F2: 'fail' not masked", '    for word in ("fail", "defer"):', '    for word in ("defer",):'),
    ("echo F2: 'defer' not masked", '    for word in ("fail", "defer"):', '    for word in ("fail",):'),
    ("echo F2: first occurrence only", "            start = low.find(word, start + 1)", "            start = -1"),
    ("echo F2: masked letters dropped", '                out[k] = "?"', '                out[k] = ""'),
    ("echo F2: only the first letter masked", "            for k in range(start, start + len(word)):", "            for k in range(start, start + 1):"),
    ("echo F2: NUL-terminated overload does not look past the cut", "        n = bounded_len(action, ECHO_MAX + ECHO_LOOK)", "        n = bounded_len(action, ECHO_MAX)"),
    # ---- SEM-1: 32-bit compares, G13
    ("G6 low 32 bits only", "    if parse_hex16(target_id, target_len) != inp.cand_id:  # G6", "    if (parse_hex16(target_id, target_len) & U32) != (inp.cand_id & U32):  # G6"),
    ("G6 high 32 bits only", "    if parse_hex16(target_id, target_len) != inp.cand_id:  # G6", "    if (parse_hex16(target_id, target_len) >> 32) != (inp.cand_id >> 32):  # G6"),
    ("I9 low 32 bits only", '    if inp.p_load != fp.LOAD_OK or p["binding"] != id_:  # I9', '    if inp.p_load != fp.LOAD_OK or (p["binding"] & U32) != (id_ & U32):  # I9'),
    ("I9 high 32 bits only", '    if inp.p_load != fp.LOAD_OK or p["binding"] != id_:  # I9', '    if inp.p_load != fp.LOAD_OK or (p["binding"] >> 32) != (id_ >> 32):  # I9'),
    ("plan_invalidate binding low 32 bits only", '    if inp.p_load != fp.LOAD_OK or p["binding"] != (inp.target_id & U64):', '    if inp.p_load != fp.LOAD_OK or (p["binding"] & U32) != (inp.target_id & U32):'),
    ("plan_invalidate binding high 32 bits only", '    if inp.p_load != fp.LOAD_OK or p["binding"] != (inp.target_id & U64):', '    if inp.p_load != fp.LOAD_OK or (p["binding"] >> 32) != ((inp.target_id & U64) >> 32):'),
    ("plan_save prior binding low 32 bits only", "    if inp.cls != inp.cand_prior_class or f.generation != inp.cand_prior_gen or f.binding != inp.cand_prior_binding:",
     "    if inp.cls != inp.cand_prior_class or f.generation != inp.cand_prior_gen or (f.binding & U32) != (inp.cand_prior_binding & U32):"),
    ("plan_save prior binding high 32 bits only", "    if inp.cls != inp.cand_prior_class or f.generation != inp.cand_prior_gen or f.binding != inp.cand_prior_binding:",
     "    if inp.cls != inp.cand_prior_class or f.generation != inp.cand_prior_gen or (f.binding >> 32) != (inp.cand_prior_binding >> 32):"),
    ("G13 greater-than", "    if (inp.writes_fp_now & U32) != (inp.cand_writes_fp & U32):  # G13", "    if (inp.writes_fp_now & U32) > (inp.cand_writes_fp & U32):  # G13"),
    ("G13 less-than", "    if (inp.writes_fp_now & U32) != (inp.cand_writes_fp & U32):  # G13", "    if (inp.writes_fp_now & U32) < (inp.cand_writes_fp & U32):  # G13"),
    ("G13 signed difference", "    if (inp.writes_fp_now & U32) != (inp.cand_writes_fp & U32):  # G13", "    if 0 < ((inp.writes_fp_now - inp.cand_writes_fp) & U32) < 0x80000000:  # G13"),
    ("G13 low 16 bits only", "    if (inp.writes_fp_now & U32) != (inp.cand_writes_fp & U32):  # G13", "    if (inp.writes_fp_now & 0xFFFF) != (inp.cand_writes_fp & 0xFFFF):  # G13"),
    # ---- SEM-2: only a VALID witness' high-water counts
    ("plan_invalidate: every witness counts as VALID", '    wc = fd.classify_witness(inp.w_load, w)\n    if not fp.profile_invalidate_permitted(p) or not fd.invalidate_generation_permitted(\n            p["generation"], wc, w["hw_generation"], inp.seen_hw_gen):\n        return plan_refuse(',
     '    wc = fd.W_VALID\n    if not fp.profile_invalidate_permitted(p) or not fd.invalidate_generation_permitted(\n            p["generation"], wc, w["hw_generation"], inp.seen_hw_gen):\n        return plan_refuse('),
    ("plan_invalidate: no witness ever counts", '    wc = fd.classify_witness(inp.w_load, w)\n    if not fp.profile_invalidate_permitted(p) or not fd.invalidate_generation_permitted(\n            p["generation"], wc, w["hw_generation"], inp.seen_hw_gen):\n        return plan_refuse(',
     '    wc = fd.W_ABSENT\n    if not fp.profile_invalidate_permitted(p) or not fd.invalidate_generation_permitted(\n            p["generation"], wc, w["hw_generation"], inp.seen_hw_gen):\n        return plan_refuse('),
    ("I10: every witness counts as VALID", '    wc = fd.classify_witness(inp.w_load, w)\n    if not fp.profile_invalidate_permitted(p) or not fd.invalidate_generation_permitted(\n            p["generation"], wc, w["hw_generation"], inp.seen_hw_gen):  # I10',
     '    wc = fd.W_VALID\n    if not fp.profile_invalidate_permitted(p) or not fd.invalidate_generation_permitted(\n            p["generation"], wc, w["hw_generation"], inp.seen_hw_gen):  # I10'),
    ("I10: no witness ever counts", '    wc = fd.classify_witness(inp.w_load, w)\n    if not fp.profile_invalidate_permitted(p) or not fd.invalidate_generation_permitted(\n            p["generation"], wc, w["hw_generation"], inp.seen_hw_gen):  # I10',
     '    wc = fd.W_ABSENT\n    if not fp.profile_invalidate_permitted(p) or not fd.invalidate_generation_permitted(\n            p["generation"], wc, w["hw_generation"], inp.seen_hw_gen):  # I10'),
    ("plan_save: every witness counts as VALID", "    wc = fd.classify_witness(inp.w_load, w)\n    base = fd.save_generation_base(", "    wc = fd.W_VALID\n    base = fd.save_generation_base("),
    ("plan_save: no witness ever counts", "    wc = fd.classify_witness(inp.w_load, w)\n    base = fd.save_generation_base(", "    wc = fd.W_ABSENT\n    base = fd.save_generation_base("),
    # ---- SEM-3: the lease owner
    ("bus owner: the plain owner, not the lease", "    owner = cap.bus_owner_text_with_leases(g.bus, gr.fp, gr.dump)", "    owner = cap.bus_owner_text(g.bus)"),
    # ---- SEM-5 / SEM-6: wording
    ("text: INVALIDATE not-loaded loses (starting up)", '    return invalidate_refused("durable state not loaded yet (starting up)")', '    return invalidate_refused("durable state not loaded yet")'),
    ("text: INVALIDATE anomaly says re-derive it first", '    return invalidate_refused("stored profile read anomaly this boot; reboot to re-derive first")',
     '    return invalidate_refused("stored profile read anomaly this boot; reboot to re-derive it first")'),
    ("log: the capture header's short operation name", "    return _tb(f\"txn={txn_op_name(op)} gen=", "    return _tb(f\"txn={cap.op_name(op)} gen="),
    ("log: total_us printed as tot", " total_us={total_us(r.w.us, r.p.us)} -> ", " tot={total_us(r.w.us, r.p.us)} -> "),
    ("log: INVALIDATE abbreviated", 'fd.PROV_OP_INVALIDATE: "INVALIDATE", fd.PROV_OP_REPLACE_CORRUPT: "REPLACE_CORRUPT"}.get(op, "-")',
     'fd.PROV_OP_INVALIDATE: "INV", fd.PROV_OP_REPLACE_CORRUPT: "REPLACE_CORRUPT"}.get(op, "-")'),
    ("log: unknown operation named SAVE", 'fd.PROV_OP_REPLACE_CORRUPT: "REPLACE_CORRUPT"}.get(op, "-")', 'fd.PROV_OP_REPLACE_CORRUPT: "REPLACE_CORRUPT"}.get(op, "SAVE")'),
    ("log: the per-key us fields come back", '               f"out={key_name(r.w.outcome)} p:err=', '               f"out={key_name(r.w.outcome)} us={r.w.us & U32} p:err='),
    # ---- AW-5: the C widths
    ("ctypes: cand_id declared uint32_t", '"cand_id": "uint64_t", "cand_ms": "uint32_t"', '"cand_id": "uint32_t", "cand_ms": "uint32_t"'),
    ("ctypes: now_ms declared uint8_t", '"now_ms": "uint32_t", "writes_fp_now"', '"now_ms": "uint8_t", "writes_fp_now"'),
    ("ctypes: hb_ok declared uint8_t", '"hb_ok": "bool", "time_trusted": "bool"}', '"hb_ok": "uint8_t", "time_trusted": "bool"}'),
    ("ctypes: the Plan widths are dropped", '    CTYPES = {"code": "uint8_t", "op": "uint8_t", "generation": "uint32_t"}\n', ""),
    ("ctypes: target_id declared uint32_t", '"seen_hw_gen": "uint32_t", "target_id": "uint64_t"}', '"seen_hw_gen": "uint32_t", "target_id": "uint32_t"}'),
    ("ctypes: the words array has no element type", '"replace_corrupt": "bool", "words": "uint16_t",', '"replace_corrupt": "bool",'),
]


def _default_mutants() -> list:
    """SEM-4: one mutant per default flipped to its fail-open value (found by class and field, so `old` is unique)."""
    src = MIRROR_PATH.read_text(encoding="utf-8")
    spec = (("SaveGateInputs", "arm_was_on", "True"), ("SaveGateInputs", "cand_valid", "True"), ("SaveGateInputs", "cand_saveable", "True"), ("SaveGateInputs", "hb_ok", "True"),
            ("SaveGateInputs", "time_trusted", "True"), ("SaveGateInputs", "boot_loaded", "True"), ("SaveGateInputs", "unconfirmed", "False"), ("SaveGateInputs", "read_anomaly", "0"),
            ("InvalidateGateInputs", "arm_was_on", "True"), ("InvalidateGateInputs", "boot_loaded", "True"), ("InvalidateGateInputs", "unconfirmed", "False"),
            ("InvalidateGateInputs", "read_anomaly", "0"), ("InvalidateGateInputs", "seen_hw_gen", "0"), ("InvalidateGateInputs", "tx_buffer_empty", "True"),
            ("InvalidateGateInputs", "tx_blocked", "False"), ("InvalidateGateInputs", "fbs_slot", "fd.FBS_CLEAR_ABSENT"), ("InvalidateGateInputs", "cls", "fd.EPC_VALID"),
            ("SavePlanInputs", "seen_hw_gen", "0"), ("SavePlanInputs", "read_anomaly", "0"), ("SavePlanInputs", "unconfirmed", "False"), ("SavePlanInputs", "captured_epoch", "1"),
            ("InvalidatePlanInputs", "seen_hw_gen", "0"), ("InvalidatePlanInputs", "unconfirmed", "False"), ("InvalidatePlanInputs", "read_anomaly", "0"),
            ("InvalidatePlanInputs", "cls", "fd.EPC_VALID"))
    out = []
    for struct, fld, value in spec:
        a = src.index(f"class {struct}:\n")
        m = re.compile(rf"^    {fld}: [\w\[\], .]+ = ([^\n]+)\n", re.M).search(src, a)
        old = src[a:m.end()]
        new = old[:m.start(1) - a] + value + old[m.end(1) - a:]
        out.append((f"default: {struct}.{fld} is {value} (fail-open)", old, new))
    return out


MIRROR_MUTANTS += _default_mutants()


def mirror_mutation_section() -> None:
    print("[11] mutation: the battery of checks against the mirror itself and against every broken mirror")
    src = MIRROR_PATH.read_text(encoding="utf-8")
    base = run_battery(sv, fast=True)
    check("control: the unmutated mirror passes the whole (fast) battery", not base, str(base[:2]))
    problems = [f"{label}: found {src.count(old)}x" for label, old, _n in MIRROR_MUTANTS if src.count(old) != 1]
    check(f"all {len(MIRROR_MUTANTS)} mutation patterns occur exactly once in the mirror", not problems, "; ".join(problems[:5]))
    survivors = []
    for label, old, new in MIRROR_MUTANTS:
        if src.count(old) != 1:
            continue
        mod = load_mirror(src.replace(old, new, 1), label)
        failed = run_battery(mod, fast=True)
        check(f"mutant [{label}] is killed by {'; '.join(n[:46] for n, _d in failed[:2]) if failed else '-'}", bool(failed))
        if not failed:
            survivors.append(label)
    print(f"  info  mirror mutants: {len(MIRROR_MUTANTS)} total, {len(MIRROR_MUTANTS) - len(survivors)} killed")
    check("every mirror mutant is killed", not survivors, str(survivors))


# =========================================== [1] structure ================================================================
def section_structure():
    print("[1] structure: constants, enum numbering, C++ / Python name parity, POD field lists, the mirror's imports")
    groups = {
        "action token": ("ACT_UNSUPPORTED", "ACT_SAVE", "ACT_INVALIDATE", "ACT_RESTORE", "ACT_ACKNOWLEDGE"),
        "phrase kind": ("PHRASE_INVALID", "PHRASE_SAVE", "PHRASE_SAVE_REPLACE_CORRUPT", "PHRASE_INVALIDATE"),
        "SAVE gate": ("SG_UNSET", "SG_ACCEPT", "SG_IN_FLIGHT", "SG_UNSUPPORTED", "SG_ARM_OFF", "SG_NO_CANDIDATE", "SG_EXPIRED", "SG_ID_FORMAT", "SG_ID_MISMATCH", "SG_PHRASE",
                      "SG_NOT_LOADED", "SG_UNCONFIRMED", "SG_ANOMALY", "SG_HB", "SG_TIME", "SG_ARMS", "SG_WRITES", "SG_BUS", "SG_FBS", "SG_FP", "SG_DUMP", "SG_R244", "SG_MTOU"),
        "INVALIDATE gate": ("IG_UNSET", "IG_ACCEPT", "IG_IN_FLIGHT", "IG_UNSUPPORTED", "IG_ARM_OFF", "IG_ID_FORMAT", "IG_PHRASE", "IG_NOT_LOADED", "IG_ANOMALY", "IG_UNCONFIRMED",
                            "IG_CLASS", "IG_ID_MISMATCH", "IG_GENERATION", "IG_BUS", "IG_FBS"),
        "plan": ("PLAN_UNSET", "PLAN_OK", "PLAN_PRIOR_CHANGED", "PLAN_UNCONFIRMED", "PLAN_ANOMALY", "PLAN_CLASS", "PLAN_CONTEXT", "PLAN_CLOCK", "PLAN_GENERATION", "PLAN_INTERNAL",
                 "PLAN_BINDING_CHANGED"),
    }
    check("every enum group is numbered 0..N-1 in the documented order, the fail-closed zero first (UNSET / INVALID / UNSUPPORTED)",
          all([getattr(sv, n) for n in names] == list(range(len(names))) for names in groups.values()))
    check("constants: arm TTL 120000 ms, pre-commit drain 3000 ms, purpose SAVE 2 (REVIEW is 1), echo 24, id 16 digits",
          (sv.ARM_TTL_MS, sv.PRECOMMIT_WAIT_MS, sv.PURPOSE_SAVE, sv.ECHO_MAX, sv.ID_DIGITS) == (120000, 3000, 2, 24, 16) and cap.PURPOSE_REVIEW == 1
          and sv.PURPOSE_SAVE != cap.PURPOSE_REVIEW and sv.TEXT_CAP == 200)
    check("FB-B2 D8: the capture header / mirror gained CAPTURE_SAVING = 4 (B3 st=SAVING), 5 is still unmapped (IDLE)",
          cap.CAPTURE_SAVING == 4 and cap.capture_state_name(4) == "SAVING" and cap.capture_state_name(5) == "IDLE" and cap.capture_state_name(3) == "CANDIDATE_NOT_SAVEABLE"
          and str(cap.b3_text(cap.CAPTURE_SAVING, False, 0, 0, 0, "-", 0, "-")).startswith("st=SAVING;prior=-;"))
    header = HEADER_PATH.read_text(encoding="utf-8")
    prod = header[:header.index("// ---- GOLDENS-BEGIN ----")]
    code = re.sub(r"//[^\n]*", "", prod)
    cxx_funcs = set(re.findall(r"constexpr (?:const )?[\w:<>, ]+?[ *&](\w+)\(", code))
    py_funcs = {n for n, v in vars(sv).items() if callable(v) and not n.startswith("_") and getattr(v, "__module__", "") == "fallback_save" and not isinstance(v, type)}
    # FB-B2: F2 added the four byte-loop helpers of the echo mask to the C++-only set (the mirror masks with str.find: an independent algorithm)
    cxx_only = {"put_sanitised", "put_slot_refusal_body", "put_err", "put_unknown_detail", "echo_fold", "echo_byte", "echo_word_at", "echo_masked"}
    check("every public function of the mirror exists in the header under the same name", not (py_funcs - cxx_funcs), str(sorted(py_funcs - cxx_funcs)))
    check("every header function exists in the mirror, except the eight C++-only text-buffer helpers (put_sanitised, put_slot_refusal_body, put_err, put_unknown_detail "
          "and the four byte-loop helpers of the F2 echo mask: echo_fold, echo_byte, echo_word_at, echo_masked)",
          not (cxx_funcs - py_funcs - cxx_only), str(sorted(cxx_funcs - py_funcs - cxx_only)))
    cxx_structs = set(re.findall(r"^struct (\w+)", code, re.M))
    py_structs = {n for n, v in vars(sv).items() if isinstance(v, type) and getattr(v, "__module__", "") == "fallback_save"}
    check("every header struct has a mirror dataclass of the same name", cxx_structs == py_structs, str(sorted(cxx_structs ^ py_structs)))
    detail, ok = [], True
    for name in sorted(cxx_structs):
        mm = re.search(rf"^struct {name} \{{(.*?)^\}};", code, re.M | re.S)
        cxx_fields = re.findall(r"^\s+(?:[\w:<>, ]+?)\s+(\w+)(?:\{\})?(?: = [^;]+)?;", mm.group(1), re.M)
        py_fields = [f for f in getattr(sv, name).__dataclass_fields__]
        if cxx_fields != py_fields:
            ok = False
            detail.append((name, cxx_fields, py_fields))
    check("every POD struct has the same fields, in the same order, in the header and in the mirror", ok, str(detail[:2]))
    cxx_consts = dict(re.findall(r"^constexpr (?:uint8_t|uint16_t|uint32_t|size_t) ([A-Z][A-Z0-9_]+) = (\d+)u?;", code, re.M))
    check("every scalar constant of the header exists in the mirror with the same value",
          bool(cxx_consts) and all(hasattr(sv, c) and getattr(sv, c) == int(v) for c, v in cxx_consts.items()), str([c for c in cxx_consts if not hasattr(sv, c)]))
    doc = header[:header.index("namespace ecco_fbsave")]
    entry_names = set(re.findall(r"\b([a-z]+(?:_[a-z0-9]+)+)\b", doc[doc.index("ENTRY POINTS"):doc.index("WHO CALLS WHAT")]))
    entry_names -= {"entry_points"}
    check("the header's ENTRY POINTS list names only functions that exist in the header, and the mirror docstring lists the main ones",
          all(n in cxx_funcs for n in entry_names) and all(n in (sv.__doc__ or "") for n in (
              "action_token", "is_invalidate_action", "save_gate_decide", "final_gate_decide", "plan_save", "plan_invalidate", "txn_outcome_text", "arm_expired")),
          str(sorted(n for n in entry_names if n not in cxx_funcs)))
    src = MIRROR_PATH.read_text(encoding="utf-8")
    imports = sorted(set(re.findall(r"^(?:from|import) ([\w.]+)", src, re.M)))
    check("the mirror imports exactly __future__, dataclasses, fallback_capture, fallback_durable, fallback_profile, pathlib, sys (stdlib + the three models only)",
          imports == ["__future__", "dataclasses", "fallback_capture", "fallback_durable", "fallback_profile", "pathlib", "sys"], str(imports))
    check("the mirror does no I/O: no open(, no time / subprocess / os use, no public function named after the writer (commit_transition / write_one / nvs_ / execute), no banned identifier",
          not re.search(r"\bopen\(|\btime\.|subprocess|\bos\.", src) and not any(re.search(r"commit_transition|write_one|nvs_|execute", n) for n in py_funcs)
          and not re.search(r"(?i:supervision)|\bntp_|save_unconfirmed", src))


def section_checks():
    print("[2]-[9] the mutation-capable checks (every one of them is re-run against every broken mirror in [11])")
    for name, fn in CHECKS:
        detail = fn(sv, False)
        check(name, detail is None, str(detail))


# =========================================== [10] hygiene: defaults, liveness =============================================
def section_hygiene():
    print("[10] hygiene: POD defaults fail closed (and are documented), every gate input is live, the header's DEFAULTS note")
    d = sv.SaveGateInputs()
    check("SaveGateInputs defaults are fail-closed: arm off, no candidate (id 0), unconfirmed true, read_anomaly 0xFF, hb / time false, boot not loaded",
          (d.arm_was_on, d.cand_valid, d.cand_saveable, d.cand_id, d.unconfirmed, d.read_anomaly, d.hb_ok, d.time_trusted, d.boot_loaded)
          == (False, False, False, 0, True, 0xFF, False, False, False))
    g0 = gate_clear()
    r = sv.save_gate_decide(d, "SAVE", 4, "0" * 16, 16, "SAVE " + "0" * 16, 21, g0)
    check("a default SAVE gate never accepts, and a default SAVE gate result is SG_UNSET with empty texts", r.code != sv.SG_ACCEPT and sv.SaveGateResult().code == sv.SG_UNSET
          and str(sv.SaveGateResult().text) == "" and not sv.SaveGateResult().arm_off_only and not sv.SaveGateResult().replace_corrupt)
    di = sv.InvalidateGateInputs()
    check("InvalidateGateInputs defaults are fail-closed: arm off, not loaded, anomaly 0xFF, unconfirmed, class UNREADABLE, seen 0xFFFFFFFF, queue not empty, blocked, FBS unreadable",
          (di.arm_was_on, di.boot_loaded, di.read_anomaly, di.unconfirmed, di.cls, di.seen_hw_gen, di.tx_buffer_empty, di.tx_blocked, di.fbs_slot)
          == (False, False, 0xFF, True, fd.EPC_UNREADABLE, 0xFFFFFFFF, False, True, fd.FBS_UNREADABLE)
          and sv.invalidate_gate_decide(di, "INVALIDATE", 10, "0" * 16, 16, "INVALIDATE " + "0" * 16, 27).code != sv.IG_ACCEPT)
    dp, di2 = sv.SavePlanInputs(), sv.InvalidatePlanInputs()
    check("plan input defaults are fail-closed: UNAVAILABLE loads, class UNREADABLE, anomaly 0xFF, unconfirmed, seen 0xFFFFFFFF, epoch 0; a default plan is never OK",
          (dp.p_load, dp.w_load, dp.cls, dp.read_anomaly, dp.unconfirmed, dp.seen_hw_gen, dp.captured_epoch) == (4, 4, fd.EPC_UNREADABLE, 0xFF, True, 0xFFFFFFFF, 0)
          and (di2.cls, di2.unconfirmed, di2.read_anomaly, di2.seen_hw_gen) == (fd.EPC_UNREADABLE, True, 0xFF, 0xFFFFFFFF)
          and sv.plan_save(dp).code != sv.PLAN_OK and sv.plan_invalidate(di2).code != sv.PLAN_OK and sv.Plan().code == sv.PLAN_UNSET and sv.Plan().op == 0)
    flips = {"arm_was_on": False, "cand_valid": False, "cand_saveable": False, "cand_id": 0, "cand_ms": (4294960000 + 120000) & U32, "cand_prior_class": 2, "cand_writes_fp": 7, "now_ms": 4294960000 + 120000,
             "writes_fp_now": 1001, "boot_loaded": False, "unconfirmed": True, "read_anomaly": 1, "hb_ok": False, "time_trusted": False}
    dead = []
    for field_name, value in flips.items():
        si, a, t, c, g, _ = build_save(sv, Sc())
        setattr(si, field_name, value)
        if sv.save_gate_decide(si, a, len(a), t, len(t), c, len(c), g).code == sv.SG_ACCEPT:
            dead.append(field_name)
    check(f"liveness: each of the {len(flips)} SaveGateInputs fields, flipped alone from the all-pass inputs, refuses (no dead input)",
          not dead and set(flips) == {f.name for f in fields(sv.SaveGateInputs)}, str(dead))
    iflips = {"arm_was_on": False, "boot_loaded": False, "read_anomaly": 2, "unconfirmed": True, "cls": fd.EPC_PROFILE_STALE, "p_load": 3, "seen_hw_gen": 100, "tx_buffer_empty": False,
              "tx_blocked": True, "fbs_slot": fd.FBS_OBLIGATION, "bus": replace(cap.BusInputs(), manual_write_in_progress=True), "p": golden_profile(generation=8),
              "w": fd.make_provision(8, GOLD_P["binding"], 7, 0x1122, KEY, 1, 1), "w_load": 3}
    dead = []
    for field_name, value in iflips.items():
        in_, a, t, c = build_inv(sv, set())
        setattr(in_, field_name, value)
        if sv.invalidate_gate_decide(in_, a, len(a), t, len(t), c, len(c)).code == sv.IG_ACCEPT:
            dead.append(field_name)
    # a lone witness load flip (READ_ERROR) changes only the class the caller composes; the gate reads the class, so it may ignore it
    dead = [x for x in dead if x != "w_load"]
    check("liveness: each InvalidateGateInputs field (the lone witness load excepted: the class carries it) refuses when flipped from the all-pass inputs",
          not dead and set(iflips) == {f.name for f in fields(sv.InvalidateGateInputs)}, str(dead))
    pl, p, plen = _prof(1)
    wl, w, wlen = _wit(8, p)
    base = sv.plan_save(faithful_save(sv, pl, p, plen, wl, w, wlen))
    pflips = {"p_load": 1, "p": golden_profile(generation=9), "w_load": 1, "w": _wit(1, p)[1], "cls": 1, "read_anomaly": 1, "unconfirmed": True,
              "seen_hw_gen": 50, "cand_prior_class": 1, "cand_prior_gen": 3, "cand_prior_binding": 5, "replace_corrupt": True, "words": [0] + GW[1:], "captured_epoch": 5}
    dead = []
    for field_name, value in pflips.items():
        in_ = faithful_save(sv, pl, p, plen, wl, w, wlen)
        setattr(in_, field_name, value)
        out = sv.plan_save(in_)
        if (out.code, out.generation, out.p_new, out.w_new) == (base.code, base.generation, base.p_new, base.w_new):
            dead.append(field_name)
    check("liveness: every SavePlanInputs field that can matter (all but why and the stored lengths of LOAD_OK records) changes the verdict or the built pair when flipped",
          not dead, str(dead))
    header = HEADER_PATH.read_text(encoding="utf-8")
    top = header[:header.index("namespace ecco_fbsave")]
    check("the header's DEFAULTS note says every input POD is fail-closed, lists the closed defaults and names the two inherited permissive exceptions",
          "DEFAULTS ARE FAIL-CLOSED" in top and "BusInputs" in top and "permissive" in top and all(w_ in top for w_ in ("arm off", "read_anomaly 0xFF", "seen_hw_gen 0xFFFFFFFF", "tx_blocked true", "unconfirmed true")))


def section_texts():
    print("[9b] every parameterless text builder of the mirror: documented, <= 200, ASCII, hazard-free, locked prefix")
    texts = []
    for n, v in sorted(vars(sv).items()):
        if n.endswith("_text") and callable(v) and getattr(v, "__module__", "") == "fallback_save" and v.__code__.co_argcount == 0:
            texts.append((n, str(v())))
    check(f"all {len(texts)} parameterless text builders are <= 200 characters, ASCII, free of every card-regex pattern and of failed / deferred / supervision, and carry a locked prefix",
          len(texts) >= 25 and all(len(t) <= 200 and t.isascii() and not hazard(t) and t.startswith(LOCKED_PREFIXES + ALLOWED_PROGRESS) for _n, t in texts),
          str([(n, t) for n, t in texts if not t.startswith(LOCKED_PREFIXES + ALLOWED_PROGRESS)][:3]))
    check("the SAVE acceptance line is exactly 'save in progress - re-reading live configuration'", str(sv.save_in_progress_text()) == "save in progress - re-reading live configuration")
    check("the SAVE heartbeat refusal never says supervision (the word is banned in headers) and names the heartbeat",
          "supervision" not in str(sv.save_hb_text()).lower() and "heartbeat" in str(sv.save_hb_text()))


# ===============================================================================================================
def main() -> int:
    section_structure()
    section_checks()
    section_texts()
    section_hygiene()
    mirror_mutation_section()
    print("")
    if FAILURES:
        print(f"FAILED: {len(FAILURES)} check(s)")
        for f in FAILURES:
            print(f"  - {f}")
        return 1
    print("All FB-B2 save model checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
