#!/usr/bin/env python3
"""FB-B1 - host C++ compile of the pure capture header, parity with the Python mirror.

firmware/include/ecco_fallback_capture.h (namespace ecco_fbcap) is the pure half of the FB-B1 REVIEW flow: the
31-word index map, the L2 capture policy, the candidate id, the compare masks, the same-boot divergence rule, the
gate classifiers and EVERY text the review entities publish. All of it is constexpr (text included: a constexpr
TextBuf, no snprintf), so a C++ compiler running -fsyntax-only evaluates the header's golden vectors, golden
strings and golden-case tables as static_asserts - no native executable is needed, which matters because the
only compiler on a Windows development machine is ESPHome's xtensa cross compiler. This suite:

  [1] compiler: a GCC C++ compiler must exist - it FAILS, never skips (search order: $ECCO_CXX, g++ / c++ on
      PATH, then the xtensa-esp32-elf-g++ ESPHome installs);
  [2] compiles the header, with only the FB-A and FB-B0 model headers beside it, under g++ -std=gnu++17 and
      -std=gnu++20, -fsyntax-only -Wall -Wextra -Werror, included twice (#pragma once): every static_assert holds;
  [3] PARITY: every labelled golden static_assert is parsed, the Python mirror (registry/fallback_capture.py)
      must reproduce each value and each string EXACTLY, the header's generated golden block must equal what this
      file emits (`python registry/tests/test_fallback_capture_host_compile.py --emit-goldens`), and the three
      classifier golden-case tables must re-derive from the mirror;
  [4] RANDOMIZED parity: a seeded generator written twice (constexpr C++ in a test translation unit, and Python) feeds
      120 cases x 10 components (L2 and masks, candidate id, candidate texts, profile texts, evaluate_read,
      review_evaluate, the classifiers, gate_decide, every gate text and name, timing) through the header and
      through the mirror; one FNV digest per case and component is a static_assert, so the compiler itself proves
      C++ == Python on 1200 random inputs - no executable is ever run, so it works with the cross compiler;
  [5] negative controls: a deliberately wrong golden, a type error and violated header static_asserts are REAL
      compile rejections (a mutated golden vector, string, table row, classifier row, buffer cap, mask);
  [6] header discipline scans (includes, banned tokens, namespace, no durable tag, no formatted print).

Writes only to a temporary directory; no hardware, no network.
"""

from __future__ import annotations

import copy
import glob
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
INCLUDE_DIR = ROOT / "firmware" / "include"
HEADER_PATH = INCLUDE_DIR / "ecco_fallback_capture.h"
MODEL_PATH = INCLUDE_DIR / "ecco_fallback_durable_model.h"
FBA_PATH = INCLUDE_DIR / "ecco_fallback_profile.h"
THIS = Path(__file__).resolve()

sys.path.insert(0, str(ROOT / "registry"))
import fallback_capture as cap  # noqa: E402
import fallback_durable as fd  # noqa: E402
import fallback_profile as fp  # noqa: E402

FAILURES: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  PASS  {name}")
    else:
        FAILURES.append(name)
        print(f"  FAIL  {name}" + (f" - {detail}" if detail else ""))


# ===========================================================================
# The golden table: ONE description per golden, a C++ expression and its Python counterpart. The header's
# generated block (between the GENERATED-GOLDENS markers) is produced from it; the compiler then proves the C++
# expression equals the literal the Python mirror produced.
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


# ---- fixtures: the same logical inputs described once for C++ and for Python --------------------------------
GOLD_P = fp.seal_profile(fp.blank_profile(
    magic=fp.PROFILE_MAGIC, schema=1, size=96, generation=7, captured_epoch=1790000000, flags=0, reg244=2,
    reg256_261=[8000, 500, 4000, 3000, 2000, 1000], reg268_273=[100, 20, 0, 50, 100, 30], reg274_279=[1, 0, 1, 0, 0, 1],
    reg232=0x0011, reg243=1, reg248=1, reg250_255=[0, 530, 1000, 1600, 2100, 2330], reg230=185, reg245=8000, reg247=1))
GOLD_W = fd.make_provision(7, GOLD_P["binding"], 6, 0x1122334455667788, fd.FALLBACK_PROFILE_KEY, 1, fd.PROV_OP_SAVE)
GW = cap.words_of(GOLD_P)
LOAD_OK, LOAD_ABSENT, LOAD_WSZ, LOAD_RERR, LOAD_UNAV = 0, 1, 2, 3, 4


class Wd:
    """A CaptureWords value: a base plus word changes, rendered as a C++ expression and as a Python list."""

    def __init__(self, changes=None, base="GOLDEN_WORDS", base_py=None):
        self.changes = dict(changes or {})
        self.base = base
        self.base_py = list(GW if base_py is None else base_py)

    def cxx(self) -> str:
        expr = self.base
        for k, v in self.changes.items():
            expr = f"golden_words_with({expr}, {k}, {v}u)"
        return expr

    def py(self) -> list:
        w = list(self.base_py)
        for k, v in self.changes.items():
            w[k] = v
        return w


def WD(**kw) -> Wd:
    """WD(w0=0, w1=499) -> words with word 0 = 0 and word 1 = 499."""
    return Wd({int(k[1:]): v for k, v in kw.items()})


ALL_FFFF = Wd(base="golden_words_all(65535u)", base_py=[65535] * 31)
ALL_ZERO = Wd(base="golden_words_all(0u)", base_py=[0] * 31)


class Pf:
    """A sealed FallbackProfileV1 variant of the golden profile (C++ lambda text + Python dict)."""

    def __init__(self, seal=True, **changes):
        self.changes, self.seal = changes, seal

    def cxx(self) -> str:
        body = "ecco_fallback::FallbackProfileV1 p = GOLDEN_PROFILE; "
        for key, value in self.changes.items():
            body += f"p.{key} = {value}; "
        body += "return ecco_fallback::seal_profile(p); " if self.seal else "return p; "
        return "[]{ " + body + "}()"

    def py(self) -> dict:
        p = fp._copy(GOLD_P)
        for key, value in self.changes.items():
            m = re.fullmatch(r"(\w+)\[(\d+)\]", key)
            if m:
                p[m.group(1)][int(m.group(2))] = value
            else:
                p[key] = value
        return fp.seal_profile(p) if self.seal else p


def pf_all5(value: int = 65535) -> Pf:
    """Authentic CORRUPT_DOMAIN record whose every value is 5 digits wide (the B7 over-200 case)."""
    ch = {"reg244": value}
    for arr in ("reg256_261", "reg268_273", "reg274_279", "reg250_255"):
        for i in range(6):
            ch[f"{arr}[{i}]"] = value
    ch.update(reg232=value, reg243=value, reg248=value, reg230=value, reg245=value, reg247=value, generation=4294967295,
              captured_epoch=4294967295)
    return Pf(**ch)


class Wt:
    """A sealed witness variant (golden_witness arguments) as C++ text and Python dict."""

    def __init__(self, hw=7, prior_gen=6, prior_bind=0x1122334455667788, op=1, tag_key=None, schema=1, corrupt=False):
        self.hw, self.pg, self.pb, self.op, self.tag, self.schema, self.corrupt = hw, prior_gen, prior_bind, op, tag_key, schema, corrupt

    def cxx(self) -> str:
        tag = "ecco_fbdurable::FALLBACK_PROFILE_KEY" if self.tag is None else f"{self.tag}u"
        base = f"golden_witness({self.hw}u, {self.pg}u, 0x{self.pb:X}ULL, {self.op}, {tag}, {self.schema})"
        if self.corrupt:
            return "[]{ ecco_fbdurable::FailbackProvisionV1 w = " + base + "; w.binding ^= 1u; return w; }()"
        return base

    def py(self) -> dict:
        w = fd.make_provision(self.hw, GOLD_P["binding"], self.pg, self.pb,
                              fd.FALLBACK_PROFILE_KEY if self.tag is None else self.tag, self.schema, self.op)
        if self.corrupt:
            w = dict(w)
            w["binding"] ^= 1
        return w


# =========================== constants and names =====================================================================
for _name in ("CANDIDATE_TTL_MS", "IDLE_WAIT_MS", "STEP_WAIT_MS", "BREAKER_MS", "LOCK_STUCK_MS", "TEXT_CAP", "REG_COUNT", "B3_OBL_MAX",
              "B3_SV_MAX"):
    val(f"constant {_name}", _name, lambda n=_name: getattr(cap, n))
for _c in list(range(0, 10)) + [11, 255]:
    strg(f"epc_name {_c}", f"epc_name({_c})", lambda c=_c: cap.epc_name(c))
for _c in range(0, 7):
    strg(f"ld_name {_c}", f"ld_name({_c})", lambda c=_c: cap.ld_name(c))
for _c in range(0, 11):
    strg(f"df_name {_c}", f"df_name({_c})", lambda c=_c: cap.df_name(c))
for _c in range(0, 8):
    strg(f"w_name {_c}", f"w_name({_c})", lambda c=_c: cap.w_name(c))
for _c in range(0, 6):
    strg(f"op_name {_c}", f"op_name({_c})", lambda c=_c: cap.op_name(c))
for _c in range(0, 15):
    strg(f"why_name {_c}", f"why_name({_c})", lambda c=_c: cap.why_name(c))
for _c in range(0, 6):
    strg(f"capture_state_name {_c}", f"capture_state_name({_c})", lambda c=_c: cap.capture_state_name(c))
for _c in range(0, 7):
    strg(f"domain_label {_c}", f"domain_label({_c})", lambda c=_c: cap.domain_label(c))
for _c in range(0, 7):
    strg(f"block_name {_c}", f"block_name({_c})", lambda c=_c: cap.block_name(c))
_OBL_PAIRS = [("OBL_CLEAR_PROVEN", "BASIS_MARKER_CLEAR"), ("OBL_CLEAR_PROVEN", "BASIS_ABSENT"),
              ("OBL_CLEAR_PROVEN", "BASIS_NO_DURABLE_STATE"), ("OBL_CLEAR_PROVEN", "BASIS_BUS_IDLE"),
              ("OBL_CLEAR_PROVEN", "BASIS_NONE"), ("OBL_ACTIVE", "BASIS_LEASE"), ("OBL_STARTING", "BASIS_PRE_COMMIT"),
              ("OBL_RESTORE_REQUIRED", "BASIS_NONE"), ("OBL_PENDING_CLEAR", "BASIS_NONE"), ("OBL_ENDING", "BASIS_RESTORE_RUNNING"),
              ("OBL_OPERATOR_NEEDED", "BASIS_NONE"), ("UNK_DURABLE_UNREADABLE", "BASIS_BOOT_READ_ERROR"),
              ("UNK_METADATA_CORRUPT", "BASIS_BOOT_LOCKOUT"), ("UNK_BOOT_NOT_LOADED", "BASIS_NONE"),
              ("UNK_DIVERGED", "BASIS_GHOST_RR"), ("UNK_BUS_OR_LOCK_STUCK", "BASIS_LOCK_STUCK"),
              ("UNK_NOT_PROBED", "BASIS_NONE"), ("BUS_BUSY", "BASIS_BUS_TXN"), ("OBL_UNSET", "BASIS_NONE")]
for _k, _b in _OBL_PAIRS:
    strg(f"obl_code {_k} {_b}", f"obl_code({_k}, {_b})", lambda k=_k, b=_b: cap.obl_code(getattr(cap, k), getattr(cap, b)))

# =========================== index map, pass buffers =================================================================
val("index map: words_of(profile_from_words(GOLDEN_WORDS)) == GOLDEN_WORDS",
    "first_diff(words_of(profile_from_words(GOLDEN_WORDS)), GOLDEN_WORDS)",
    lambda: cap.first_diff(cap.words_of(cap.profile_from_words(GW)), GW))
for _k in (-1, 0, 1, 6, 7, 12, 13, 18, 19, 20, 21, 22, 27, 28, 29, 30, 31, 100):
    val(f"reg_of {_k}", f"reg_of({_k})", lambda k=_k: cap.reg_of(k))
val("first_diff: every single-word change is found at its own index",
    "[]{ for (size_t k = 0; k < REG_COUNT; k++) { if (first_diff(GOLDEN_WORDS, golden_words_with(GOLDEN_WORDS, k, 12345u)) != (int) k) "
    "return false; } return first_diff(GOLDEN_WORDS, GOLDEN_WORDS) == -1; }()",
    lambda: all(cap.first_diff(GW, WD(**{f"w{k}": 12345}).py()) == k for k in range(31)) and cap.first_diff(GW, GW) == -1)
val("first_diff: the FIRST of two differences (5 and 9)", f"first_diff(GOLDEN_WORDS, {WD(w5=1, w9=2).cxx()})",
    lambda: cap.first_diff(GW, WD(w5=1, w9=2).py()))


def _store_py(extra=None) -> list:
    v241 = [1000 + i for i in range(53)]
    v230 = [2000 + i for i in range(3)]
    w = [0] * 31
    cap.store_block_241(w, v241)
    cap.store_block_230(w, v230)
    return w


_STORE_CXX = ("[]{ std::array<uint16_t, 53> a{}; std::array<uint16_t, 3> b{}; for (size_t i = 0; i < 53; i++) a[i] = (uint16_t) (1000 + i); "
              "for (size_t i = 0; i < 3; i++) b[i] = (uint16_t) (2000 + i); CaptureWords w{}; store_block_241(w, a); store_block_230(w, b); ")
for _k in (0, 1, 6, 7, 12, 13, 18, 19, 20, 21, 22, 27, 28, 29, 30):
    val(f"store_block_241 / 230: word {_k} (register {cap.REGS[_k]})", _STORE_CXX + f"return w[{_k}]; }}()", lambda k=_k: _store_py()[k])
val("store_block_241 / 230: digest of all 31 stored words",
    _STORE_CXX + "uint64_t h = ecco_fallback::FNV1A64_OFFSET_BASIS; for (size_t k = 0; k < REG_COUNT; k++) h = step_le(h, w[k], 2); return h; }()",
    lambda: fp.fnv1a_64(struct.pack("<31H", *_store_py())))
val("store_block_241: a wrong size stores nothing and reports it",
    "[]{ std::array<uint16_t, 52> a{}; a[3] = 7; std::array<uint16_t, 4> b{}; b[0] = 9; CaptureWords w{}; const bool x = store_block_241(w, a); "
    "const bool y = store_block_230(w, b); return (x ? 100 : 0) + (y ? 10 : 0) + w[0] + w[28]; }()", lambda: 0)

# =========================== L2 refusals (sv= text), L2w warnings =====================================================
_SV = [
    ("golden words", Wd(), 8000), ("244=0", WD(w0=0), 8000), ("244=1", WD(w0=1), 8000), ("244=3", WD(w0=3), 8000),
    ("power 499 (slot 1)", WD(w1=499), 8000), ("power 500 (slot 1)", WD(w1=500), 8000),
    ("power 8000 (slot 6)", WD(w6=8000), 8000), ("power 8001 (slot 6)", WD(w6=8001), 8000),
    ("power 0 (slot 3)", WD(w3=0), 8000), ("power 6000 above a 5000 ceiling", WD(w2=6000), 5000),
    ("power 5000 at a 5000 ceiling", WD(w2=5000), 5000), ("power 9000 above 8000 and a 10000 ceiling", WD(w2=9000), 10000),
    ("SOC 100 (slot 2)", WD(w8=100), 8000), ("SOC 101 (slot 2)", WD(w8=101), 8000), ("SOC 65535 (slot 6)", WD(w12=65535), 8000),
    ("source 0 and 1", WD(w13=0, w14=1), 8000), ("source 2 (slot 3)", WD(w15=2), 8000), ("source 3 (slot 3)", WD(w15=3), 8000),
    ("source 4 = mode (slot 3)", WD(w15=4), 8000), ("source 0x1C = mode (slot 4)", WD(w16=0x1C), 8000),
    ("source 0x20 = bits (slot 3)", WD(w15=0x20), 8000), ("source 0x8000 = bits (slot 6)", WD(w18=0x8000), 8000),
    ("source 0x27 = all three (slot 3)", WD(w15=0x27), 8000), ("source 5 = mode only (slot 1)", WD(w13=5), 8000),
    ("HHMM 2359 (slot 4)", WD(w25=2359), 8000), ("HHMM 2400 (slot 4)", WD(w25=2400), 8000),
    ("HHMM 60 (slot 4)", WD(w25=60), 8000), ("HHMM 59 (slot 4)", WD(w25=59), 8000), ("HHMM 65535 (slot 6)", WD(w27=65535), 8000),
    ("243 = 0 and 1", WD(w20=0), 8000), ("243 = 2", WD(w20=2), 8000), ("243 = 65535", WD(w20=65535), 8000),
    ("232, 248, 230, 245, 247 never refuse", WD(w19=0xFFFF, w21=0xFFFF, w28=65535, w29=65535, w30=65535), 8000),
    ("off-grid and ring-breaking times never refuse", WD(w22=3, w23=3), 8000),
    ("four refusals: +1", WD(w0=0, w1=0, w2=9000, w8=101), 8000),
    ("three refusals: no +N", WD(w0=0, w1=0, w2=9000), 8000),
    ("every field wrong: 38 refusals, +35", ALL_FFFF, 8000),
]
for _label, _w, _c in _SV:
    txt(f"sv_text: {_label}", f"sv_text(capture_refusals({_w.cxx()}, {_c}u))",
        lambda w=_w, c=_c: cap.sv_text(cap.capture_refusals(w.py(), c)))


def _refusals_py(*items) -> "cap.Refusals":
    r = cap.Refusals()
    for kind, slot in items:
        cap._refusal_add(r, kind, slot)
    return r


def _refusals_cxx(*items) -> str:
    return "[]{ Refusals r{}; " + "".join(f"refusal_add(r, {k}, {s}); " for k, s in items) + "return r; }()"


# RH5: the text-only kinds (RF_CLASS, RF_ANOMALY), RF_NONE and an unknown kind render NOTHING in sv= in BOTH languages
# (none of them is ever added to a Refusals by capture_refusals; the C++ and the mirror used to differ here).
for _label, _items in (("a text-only RF_CLASS item renders no code", (("RF_PWRL", 2), ("RF_CLASS", 5))),
                       ("a text-only RF_ANOMALY item renders no code", (("RF_ANOMALY", 0), ("RF_244X", 0))),
                       ("RF_NONE and an unknown kind render no code", (("RF_NONE", 3), ("200", 7), ("RF_243X", 0)))):
    txt(f"sv_text: {_label}", f"sv_text({_refusals_cxx(*_items)})",
        lambda i=_items: cap.sv_text(_refusals_py(*[(getattr(cap, k) if not k.isdigit() else int(k), n) for k, n in i])))
val("ReviewVerdict default sv is empty (the mirror used to default to -)", "ReviewVerdict{}.sv.size()", lambda: len(cap.ReviewVerdict().sv))
val("capture_refusals: the all-0xFFFF words give 38 refusals (the maximum)", f"capture_refusals({ALL_FFFF.cxx()}, 8000u).count",
    lambda: cap.capture_refusals(ALL_FFFF.py(), 8000).count)
val("capture_refusals: the golden words give none", "capture_refusals(GOLDEN_WORDS, 8000u).count",
    lambda: cap.capture_refusals(GW, 8000).count)

_WARN = [
    ("golden words", Wd()),
    ("W1 FP overlay look-alike", WD(w7=100, w8=100, w9=100, w10=100, w11=100, w12=100, w13=1, w14=1, w15=1, w16=1, w17=1, w18=1)),
    ("W1 needs 232 bit0", WD(w7=100, w8=100, w9=100, w10=100, w11=100, w12=100, w13=1, w14=1, w15=1, w16=1, w17=1, w18=1, w19=0x10)),
    ("W2 uniform 3000 W", WD(w1=3000, w2=3000, w3=3000, w4=3000, w5=3000, w6=3000)),
    ("W2 uniform 3001 W is not Dump residue", WD(w1=3001, w2=3001, w3=3001, w4=3001, w5=3001, w6=3001)),
    ("W2 uniform 500 W", WD(w1=500, w2=500, w3=500, w4=500, w5=500, w6=500)),
    ("W3 248 bit0 off", WD(w21=0)), ("W3 248 upper bits do not matter", WD(w21=0x0003)),
    ("W4 grid source while 232 bit0 off", WD(w19=0x10)),
    ("W4 needs a grid (1) source", WD(w19=0x10, w13=0, w14=0, w15=0, w16=0, w17=0, w18=0)),
    ("W5 off the 5-minute grid", WD(w23=531)), ("W5 ignores an undecodable start", WD(w23=2461)),
    ("W6 duplicate start", WD(w23=0)), ("W6 out of order", WD(w23=2200)),
    ("W6 wraps the ring twice", WD(w22=0, w23=800, w24=1600, w25=200, w26=1000, w27=1800)),
    ("W6 undecodable start", WD(w24=2400)),
    ("a valid unsorted ring (rotated start) has no W6", WD(w22=2300, w23=300, w24=800, w25=1200, w26=1600, w27=2000)),
    ("every warning at once", WD(w1=3000, w2=3000, w3=3000, w4=3000, w5=3000, w6=3000, w7=100, w8=100, w9=100, w10=100, w11=100,
                                  w12=100, w13=1, w14=1, w15=1, w16=1, w17=1, w18=1, w19=0x11, w21=0, w23=531, w24=531)),
    ("all words zero", ALL_ZERO), ("all words 0xFFFF", ALL_FFFF),
]
for _label, _w in _WARN:
    val(f"capture_warnings: {_label}", f"capture_warnings({_w.cxx()})", lambda w=_w: cap.capture_warnings(w.py()))
for _label, _w in (("golden words", Wd()), ("W6 duplicate start", WD(w23=0)), ("undecodable 2400", WD(w24=2400)),
                   ("wraps twice", WD(w22=0, w23=800, w24=1600, w25=200, w26=1000, w27=1800)),
                   ("rotated start", WD(w22=2300, w23=300, w24=800, w25=1200, w26=1600, w27=2000)),
                   ("all zero", ALL_ZERO), ("one slot at 2359", WD(w27=2359, w26=2300))):
    val(f"ring_valid: {_label}", f"ring_valid({_w.cxx()})", lambda w=_w: cap.ring_valid(w.py()))
for _v in (0, 59, 60, 99, 100, 2359, 2360, 2399, 2400, 65535, 1259, 1260):
    val(f"hhmm_decodable {_v}", f"hhmm_decodable({_v})", lambda v=_v: cap.hhmm_decodable(v))
for _v in (0, 5, 1, 530, 531, 2355, 2359, 60, 65):
    val(f"on_5min_grid {_v}", f"on_5min_grid({_v})", lambda v=_v: cap.on_5min_grid(v))

# review_eligible
for _label, _w, _cls, _anom in (("clean, VALID", Wd(), 5, 0), ("clean, NOT_CAPTURED", Wd(), 1, 0), ("clean, CORRUPT", Wd(), 2, 0),
                                ("clean, UNREADABLE", Wd(), 0, 0), ("clean, SAVE_UNCONFIRMED", Wd(), 7, 0),
                                ("clean, STALE", Wd(), 8, 0), ("clean, LOST", Wd(), 6, 0), ("clean, VALID, anomaly", Wd(), 5, 4),
                                ("clean, VALID, anomaly 1 (profile key)", Wd(), 5, 1), ("clean, VALID, anomaly 2 (witness key)", Wd(), 5, 2),
                                ("clean, VALID, anomaly 3", Wd(), 5, 3),
                                ("refused, VALID", WD(w0=0), 5, 0)):
    val(f"review_eligible: {_label}", f"review_eligible(capture_refusals({_w.cxx()}, 8000u), {_cls}, {_anom})",
        lambda w=_w, c=_cls, a=_anom: cap.review_eligible(cap.capture_refusals(w.py(), 8000), c, a))

# =========================== candidate id ============================================================================
_ID_VECTORS = [(1, 1, 1, 0, 0), (0xDEADBEEF, 2, 5, 7, 0xD852A4FA2DF7DBA3), (0xFFFFFFFF, 0xFFFFFFFF, 8, 0xFFFFFFFF, 0xFFFFFFFFFFFFFFFF),
               (0, 0, 0, 0, 0)]
for _a in _ID_VECTORS:
    _args = f"{_a[0]}u, {_a[1]}u, {_a[2]}, {_a[3]}u, 0x{_a[4]:X}ULL, GOLDEN_WORDS"
    val(f"candidate_id (constants reading, THE locked one) {_a[0]:X}/{_a[1]}/{_a[2]}/{_a[3]}", f"candidate_id({_args})",
        lambda a=_a: cap.candidate_id(*a, GW))
    val(f"candidate_id_alt_zero_header_reading (rejected reading) {_a[0]:X}/{_a[1]}/{_a[2]}/{_a[3]}",
        f"candidate_id_alt_zero_header_reading({_args})", lambda a=_a: cap.candidate_id_alt_zero_header_reading(*a, GW))
val("candidate id: the two q readings differ", "candidate_id(1u, 1u, 1, 0u, 0ULL, GOLDEN_WORDS) != "
    "candidate_id_alt_zero_header_reading(1u, 1u, 1, 0u, 0ULL, GOLDEN_WORDS)",
    lambda: cap.candidate_id(1, 1, 1, 0, 0, GW) != cap.candidate_id_alt_zero_header_reading(1, 1, 1, 0, 0, GW))
val("candidate id: every input changes the id (salt, seq, class, generation, binding, each of the 31 words)",
    "[]{ const uint64_t base = candidate_id(1u, 1u, 1, 0u, 0ULL, GOLDEN_WORDS); "
    "if (candidate_id(2u, 1u, 1, 0u, 0ULL, GOLDEN_WORDS) == base || candidate_id(1u, 2u, 1, 0u, 0ULL, GOLDEN_WORDS) == base || "
    "candidate_id(1u, 1u, 2, 0u, 0ULL, GOLDEN_WORDS) == base || candidate_id(1u, 1u, 1, 1u, 0ULL, GOLDEN_WORDS) == base || "
    "candidate_id(1u, 1u, 1, 0u, 1ULL, GOLDEN_WORDS) == base) return false; "
    "for (size_t k = 0; k < REG_COUNT; k++) { if (candidate_id(1u, 1u, 1, 0u, 0ULL, golden_words_with(GOLDEN_WORDS, k, (uint16_t) (GOLDEN_WORDS[k] ^ 1u))) "
    "== base) return false; } return true; }()",
    lambda: (lambda base: all(x != base for x in (cap.candidate_id(2, 1, 1, 0, 0, GW), cap.candidate_id(1, 2, 1, 0, 0, GW),
                                                  cap.candidate_id(1, 1, 2, 0, 0, GW), cap.candidate_id(1, 1, 1, 1, 0, GW),
                                                  cap.candidate_id(1, 1, 1, 0, 1, GW)))
             and all(cap.candidate_id(1, 1, 1, 0, 0, WD(**{f"w{k}": GW[k] ^ 1}).py()) != base for k in range(31)))(
                 cap.candidate_id(1, 1, 1, 0, 0, GW)))
txt("id_text: a 16-digit id", "id_text(candidate_id(1u, 1u, 1, 0u, 0ULL, GOLDEN_WORDS))", lambda: cap.id_text(cap.candidate_id(1, 1, 1, 0, 0, GW)))
txt("id_text: leading zeros are kept", "id_text(0x00000000000000ABULL)", lambda: cap.id_text(0xAB))
txt("b4_text: saveable", "b4_text(true, 0x1D63D8CBC6CB4D55ULL)", lambda: cap.b4_text(True, 0x1D63D8CBC6CB4D55))
txt("b4_text: not saveable", "b4_text(false, 0x1D63D8CBC6CB4D55ULL)", lambda: cap.b4_text(False, 0x1D63D8CBC6CB4D55))

# =========================== masks ===================================================================================
_MASK_CASES = [("identical", Wd()), ("244", WD(w0=0)), ("256", WD(w1=1)), ("261", WD(w6=1)), ("268", WD(w7=1)), ("273", WD(w12=1)),
               ("274 full word 1 -> 3", WD(w13=3)), ("274 full word 1 -> 0x8001", WD(w13=0x8001)), ("279", WD(w18=2)),
               ("232 bit0", WD(w19=0x10)), ("232 bit1 (info only)", WD(w19=0x13)), ("232 all upper bits", WD(w19=0xFFF1)),
               ("243", WD(w20=0)), ("248 bit0", WD(w21=0)), ("248 upper bits", WD(w21=0x0003)), ("248 bit0 and upper bits", WD(w21=0x0002)),
               ("250", WD(w22=1)), ("255", WD(w27=1)), ("230", WD(w28=1)), ("245", WD(w29=1)), ("247 bit0", WD(w30=0)),
               ("247 upper bits", WD(w30=0x8001)), ("every word", Wd({k: GW[k] ^ 0xFFFF for k in range(31)})),
               ("all words 0xFFFF", ALL_FFFF), ("all words zero", ALL_ZERO)]
for _label, _w in _MASK_CASES:
    val(f"e1_delta_mask: {_label}", f"e1_delta_mask({_w.cxx()}, GOLDEN_WORDS)", lambda w=_w: cap.e1_delta_mask(w.py(), GW))
    val(f"ctx_mismatch_mask: {_label}", f"ctx_mismatch_mask({_w.cxx()}, GOLDEN_WORDS)", lambda w=_w: cap.ctx_mismatch_mask(w.py(), GW))
    val(f"info_mismatch_mask: {_label}", f"info_mismatch_mask({_w.cxx()}, GOLDEN_WORDS)", lambda w=_w: cap.info_mismatch_mask(w.py(), GW))
for _label, _w in (("golden words", Wd()), ("244 = 0 is a valid FROM", WD(w0=0)), ("244 = 1", WD(w0=1)), ("power 499", WD(w1=499)),
                   ("power 8001", WD(w6=8001)), ("SOC 101", WD(w7=101)), ("source 2", WD(w18=2)), ("all 0xFFFF", ALL_FFFF),
                   ("all zero", ALL_ZERO)):
    val(f"out_of_domain_mask: {_label}", f"out_of_domain_mask({_w.cxx()})", lambda w=_w: cap.out_of_domain_mask(w.py()))

# =========================== timing, fingerprints, integrity =========================================================
for _born in (0, 1000, 4294960000, 4294967295):
    for _age in (0, 1, 119998, 119999, 120000, 120001, 4000000000):
        _now = (_born + _age) % 2 ** 32
        val(f"candidate_expired born={_born} age={_age} (now={_now})", f"candidate_expired({_now}u, {_born}u)",
            lambda n=_now, b=_born: cap.candidate_expired(n, b))
for _age in (0, 1, 999, 1000, 1001, 59999, 60000, 60001, 118999, 119000, 119001, 119999, 120000, 120001, 4000000000):
    val(f"exp_seconds age {_age} ms", f"exp_seconds({_age}u + 1000u, 1000u)", lambda a=_age: cap.exp_seconds(a + 1000, 1000))
val("exp_seconds across the 2^32 wrap (age 61000)", "exp_seconds(60999u, 4294967295u - 4294u)", lambda: cap.exp_seconds(60999, 4294967295 - 4294))
for _args in ((1, 2, 3, 4, 5), (0, 0, 0, 0, 0), (4294967295, 1, 0, 0, 0), (4294967295, 4294967295, 0, 0, 2), (10, 20, 30, 40, 50),
              (2147483647, 2147483647, 2, 0, 0)):
    val(f"writes_fingerprint {_args}", f"writes_fingerprint({', '.join(f'{a}u' for a in _args)})", lambda a=_args: cap.writes_fingerprint(*a))
for _op, _purpose in ((True, 1), (True, 0), (False, 1), (False, 0), (True, 2)):
    val(f"review_integrity_ok op={_op} purpose={_purpose}", f"review_integrity_ok({str(_op).lower()}, {_purpose})",
        lambda o=_op, p=_purpose: cap.review_integrity_ok(o, p))

# =========================== prior fingerprint ======================================================================
_BAD_MAGIC = Pf(magic=0x1234)
_FP_CASES = [("authentic VALID", LOAD_OK, Pf(), 0), ("authentic INVALIDATED", LOAD_OK, Pf(flags=1, generation=8), 0),
             ("authentic CORRUPT_DOMAIN", LOAD_OK, Pf(reg244=1, generation=9), 0),
             ("CORRUPT + LOAD_OK keeps the raw fields", LOAD_OK, _BAD_MAGIC, 0),
             ("CORRUPT binding defect keeps the raw fields", LOAD_OK, Pf(seal=False, generation=11), 0),
             ("CORRUPT + WRONG_SIZE: (0, stored length)", LOAD_WSZ, Pf(), 40),
             ("CORRUPT + WRONG_SIZE: stored length 65535 (the 16-bit edge)", LOAD_WSZ, Pf(), 65535),
             ("CORRUPT + WRONG_SIZE: stored length 65536", LOAD_WSZ, Pf(), 65536),
             ("CORRUPT + WRONG_SIZE: stored length 70000 (above 16 bits)", LOAD_WSZ, Pf(), 70000),
             ("CORRUPT + WRONG_SIZE: stored length 4294967295", LOAD_WSZ, Pf(), 4294967295),
             ("NOT_CAPTURED", LOAD_ABSENT, Pf(), 0), ("READ_ERROR", LOAD_RERR, Pf(), 0), ("UNAVAILABLE", LOAD_UNAV, Pf(), 0)]
for _label, _load, _p, _len in _FP_CASES:
    val(f"prior_fingerprint generation: {_label}", f"prior_fingerprint({_load}, {_p.cxx()}, {_len}u).generation",
        lambda l=_load, p=_p, n=_len: cap.prior_fingerprint(l, p.py(), n).generation)
    val(f"prior_fingerprint binding: {_label}", f"prior_fingerprint({_load}, {_p.cxx()}, {_len}u).binding",
        lambda l=_load, p=_p, n=_len: cap.prior_fingerprint(l, p.py(), n).binding)

# RH4(b): review_evaluate carries the WRONG_SIZE stored length (above 16 bits) into the prior binding unchanged.
for _len in (97, 70000, 4294967295):
    val(f"review_evaluate: prior_binding of a WRONG_SIZE record with stored length {_len}",
        f"[]{{ ReviewInputs in; in.words = GOLDEN_WORDS; in.cls = 2; in.p_load = 2; in.p_stored_len = {_len}u; return review_evaluate(in).prior_binding; }}()",
        lambda n=_len: cap.review_evaluate(cap.ReviewInputs(words=GW, cls=2, p_load=2, p_stored_len=n)).prior_binding)

# FW0: the review masks (dx / dc / di) exist only against a TRUSTED stored profile: authentic (FB-A class VALID / INVALIDATED / CORRUPT_DOMAIN)
# AND effective class != UNREADABLE - the predicate saved_view uses for B7 / B8, minus the B7 length clause. Before the fix has_stored followed
# the FB-A class alone, so a valid FBP + a CRC-bad witness (effective class UNREADABLE) showed dx=00000 / dc=000 / di=00 next to B7 / B8 v=NONE.
_FW0_CHG = WD(w0=0, w1=499, w13=3, w19=GW[19] ^ 1, w28=1)
_FW0_FIX = [("authentic VALID", LOAD_OK, Pf(), 0, True), ("authentic INVALIDATED", LOAD_OK, Pf(flags=1, generation=8), 0, True),
            ("authentic CORRUPT_DOMAIN", LOAD_OK, Pf(reg244=1, generation=9), 0, True), ("CORRUPT (bad magic)", LOAD_OK, Pf(magic=1), 0, False),
            ("ABSENT", LOAD_ABSENT, Pf(), 0, False), ("WRONG_SIZE", LOAD_WSZ, Pf(), 40, False), ("READ_ERROR", LOAD_RERR, Pf(), 0, False)]
for _label, _load, _p, _len, _auth in _FW0_FIX:
    for _cls in (range(0, 9) if _auth else (0, 2, 5)):
        val(f"review_evaluate has_stored: {_label} record, effective class {_cls}",
            f"[]{{ ReviewInputs in; in.words = {_FW0_CHG.cxx()}; in.cls = {_cls}; in.p_load = {_load}; in.p = {_p.cxx()}; in.p_stored_len = {_len}u; "
            "return review_evaluate(in).has_stored; }()",
            lambda l=_load, p=_p, c=_cls, n=_len: cap.review_evaluate(cap.ReviewInputs(words=_FW0_CHG.py(), cls=c, p_load=l, p=p.py(), p_stored_len=n)).has_stored)
for _cls in range(0, 9):
    val(f"stored_trusted: the golden profile under effective class {_cls}", f"stored_trusted(0, GOLDEN_PROFILE, {_cls})",
        lambda c=_cls: cap._stored_trusted(0, GOLD_P, c))
for _cls in (5, 0):
    for _m in ("dx", "dc", "di"):
        val(f"review_evaluate {_m}: a candidate that differs from the authentic golden profile, effective class {_cls} ({'masks computed' if _cls == 5 else 'not trusted: 0'})",
            f"[]{{ ReviewInputs in; in.words = {_FW0_CHG.cxx()}; in.cls = {_cls}; in.p_load = 0; in.p = GOLDEN_PROFILE; return review_evaluate(in).{_m}; }}()",
            lambda c=_cls, m=_m: getattr(cap.review_evaluate(cap.ReviewInputs(words=_FW0_CHG.py(), cls=c, p_load=0, p=GOLD_P)), m))
    _RVC = f"[]{{ ReviewInputs in; in.words = {_FW0_CHG.cxx()}; in.cls = {_cls}; in.p_load = 0; in.p = GOLDEN_PROFILE; const ReviewVerdict v = review_evaluate(in); "
    txt(f"b5_text from the review verdict: a candidate that differs from the authentic golden profile, effective class {_cls}",
        _RVC + "return b5_text(true, in.words, v.has_stored, v.dx); }()",
        lambda c=_cls: (lambda v: cap.b5_text(True, _FW0_CHG.py(), v.has_stored, v.dx))(
            cap.review_evaluate(cap.ReviewInputs(words=_FW0_CHG.py(), cls=c, p_load=0, p=GOLD_P))))
    txt(f"b6_text from the review verdict: a candidate that differs from the authentic golden profile, effective class {_cls}",
        _RVC + "return b6_text(true, in.words, v.has_stored, v.dc, v.di); }()",
        lambda c=_cls: (lambda v: cap.b6_text(True, _FW0_CHG.py(), v.has_stored, v.dc, v.di))(
            cap.review_evaluate(cap.ReviewInputs(words=_FW0_CHG.py(), cls=c, p_load=0, p=GOLD_P))))

# =========================== same-boot divergence, evaluate_read ====================================================
_PB = "ecco_fallback::encode_profile(GOLDEN_PROFILE)"
_WB = "ecco_fbdurable::encode_provision(GOLDEN_WITNESS)"
for _a, _b, _eq in ((0, 0, True), (0, 0, False), (0, 3, True), (1, 1, True), (3, 3, False), (4, 1, True)):
    val(f"diverged: last load {_a}, new load {_b}, bytes equal {_eq}", f"diverged({_a}, {_b}, {str(_eq).lower()})", lambda a=_a, b=_b, e=_eq: cap.diverged(a, b, e))
val("profile_diverged: identical load and bytes", f"profile_diverged(0, {_PB}, 0, {_PB})", lambda: False)
val("profile_diverged: a different load", f"profile_diverged(0, {_PB}, 3, {_PB})", lambda: True)
val("profile_diverged: different bytes",
    f"profile_diverged(0, {_PB}, 0, ecco_fallback::encode_profile({Pf(generation=8).cxx()}))", lambda: True)
val("profile_diverged: same zero bytes under two non-OK loads is a load change", "profile_diverged(1, ecco_fallback::ProfileBytes{}, 3, ecco_fallback::ProfileBytes{})",
    lambda: True)
val("profile_diverged: same non-OK load, zero bytes", "profile_diverged(3, ecco_fallback::ProfileBytes{}, 3, ecco_fallback::ProfileBytes{})",
    lambda: False)
val("witness_diverged: identical", f"witness_diverged(0, {_WB}, 0, {_WB})", lambda: False)
val("witness_diverged: different bytes", f"witness_diverged(0, {_WB}, 0, ecco_fbdurable::encode_provision({Wt(hw=8, prior_gen=7).cxx()}))",
    lambda: True)

_RI_PRELUDE = ("ReadInputs in; in.p_load = 0; in.p = GOLDEN_PROFILE; in.w_load = 0; in.w = GOLDEN_WITNESS; in.healthy = true; "
               f"in.baseline_valid = true; in.last_p_load = 0; in.last_p_bytes = {_PB}; in.last_w_load = 0; in.last_w_bytes = {_WB}; ")


def _ri_py(**over) -> cap.ReadInputs:
    base = cap.ReadInputs(p_load=0, p=GOLD_P, w_load=0, w=GOLD_W, healthy=True, baseline_valid=True, last_p_load=0,
                          last_p_bytes=fp.pack_profile(GOLD_P), last_w_load=0, last_w_bytes=fd.pack_provision(GOLD_W))
    for k, v in over.items():
        setattr(base, k, v)
    return base


_READ_CASES = [
    ("consistent read", "", {}),
    ("the profile bytes changed (a resealed record)", f"in.p = {Pf(generation=8).cxx()};", {"p": Pf(generation=8).py()}),
    ("the witness bytes changed", f"in.w = {Wt(hw=8, prior_gen=7).cxx()};", {"w": Wt(hw=8, prior_gen=7).py()}),
    ("the profile load changed to READ_ERROR", "in.p_load = 3; in.p = ecco_fallback::FallbackProfileV1{};", {"p_load": 3, "p": fp.blank_profile()}),
    ("the profile now reads ABSENT after being seen", "in.p_load = 1; in.p = ecco_fallback::FallbackProfileV1{}; in.present_seen = 3;",
     {"p_load": 1, "p": fp.blank_profile(), "present_seen": 3}),
    ("a changed record is not divergence without a baseline", f"in.baseline_valid = false; in.p = {Pf(generation=8).cxx()};",
     {"baseline_valid": False, "p": Pf(generation=8).py()}),
    ("the health gate reported unhealthy after the read", "in.healthy = false;", {"healthy": False}),
    ("an earlier anomaly stays sticky", "in.read_anomaly = 1;", {"read_anomaly": 1}),
    ("seen_hw_gen is only ever raised", "in.seen_hw_gen = 40;", {"seen_hw_gen": 40}),
    ("first boot read, nothing stored", "in.baseline_valid = false; in.p_load = 1; in.p = ecco_fallback::FallbackProfileV1{}; in.w_load = 1; "
     "in.w = ecco_fbdurable::FailbackProvisionV1{};", {"baseline_valid": False, "p_load": 1, "p": fp.blank_profile(), "w_load": 1,
                                                       "w": fd.blank_provision()}),
]
for _label, _mod, _over in _READ_CASES:
    for _field, _cx in (("cls", "e.cls"), ("why", "e.why"), ("rule", "e.rule"), ("latch.present_seen", "e.latch.present_seen"),
                        ("latch.read_anomaly", "e.latch.read_anomaly"), ("seen_hw_gen", "e.seen_hw_gen"),
                        ("p_fba_class", "e.p_fba_class"), ("w_class", "e.w_class"), ("p_diverged", "e.p_diverged"),
                        ("w_diverged", "e.w_diverged")):
        def _py(over=_over, field=_field):
            r = cap.evaluate_read(_ri_py(**over))
            obj = r
            for part in field.split("."):
                obj = getattr(obj, part)
            return obj
        val(f"evaluate_read [{_label}]: {_field}", "[]{ " + _RI_PRELUDE + _mod + f" const ReadEval e = evaluate_read(in); return {_cx}; }}()", _py)

# FW0 end to end (the review's repro rv_fw/a5): a valid FBP + a witness that cannot be read -> the effective class is UNREADABLE (B1), B7 / B8 say NONE, and
# the review masks are NOT shown (dx / dc / di '-'), all derived from the SAME class through the real read -> review chain.
_PIPE_C = ("[]{ ReadInputs ri; ri.p_load = 0; ri.p = GOLDEN_PROFILE; ri.w_load = 3; ri.w = ecco_fbdurable::FailbackProvisionV1{}; ri.healthy = true; "
           "const ReadEval e = evaluate_read(ri); ReviewInputs in; in.words = GOLDEN_WORDS; in.cls = e.cls; in.read_anomaly = e.latch.read_anomaly; "
           "in.p_load = 0; in.p = GOLDEN_PROFILE; const ReviewVerdict v = review_evaluate(in); (void) v; ")


def _pipe_py():
    e = cap.evaluate_read(cap.ReadInputs(p_load=0, p=GOLD_P, w_load=3, w=fd.blank_provision(), healthy=True))
    v = cap.review_evaluate(cap.ReviewInputs(words=list(GW), cls=e.cls, read_anomaly=e.latch.read_anomaly, p_load=0, p=GOLD_P))
    return e, v


val("FW0 pipeline [valid FBP + unreadable witness]: the effective class", _PIPE_C + "return e.cls; }()", lambda: _pipe_py()[0].cls)
val("FW0 pipeline [valid FBP + unreadable witness]: has_stored", _PIPE_C + "return v.has_stored; }()", lambda: _pipe_py()[1].has_stored)
val("FW0 pipeline [valid FBP + unreadable witness]: eligible", _PIPE_C + "return v.eligible; }()", lambda: _pipe_py()[1].eligible)
txt("FW0 pipeline [valid FBP + unreadable witness]: b5_text dx is -", _PIPE_C + "return b5_text(true, in.words, v.has_stored, v.dx); }()",
    lambda: cap.b5_text(True, GW, _pipe_py()[1].has_stored, _pipe_py()[1].dx))
txt("FW0 pipeline [valid FBP + unreadable witness]: b6_text dc and di are -", _PIPE_C + "return b6_text(true, in.words, v.has_stored, v.dc, v.di); }()",
    lambda: cap.b6_text(True, GW, _pipe_py()[1].has_stored, _pipe_py()[1].dc, _pipe_py()[1].di))
txt("FW0 pipeline [valid FBP + unreadable witness]: b7_text is the NONE form", _PIPE_C + "return b7_text(0, GOLDEN_PROFILE, e.cls); }()",
    lambda: cap.b7_text(0, GOLD_P, _pipe_py()[0].cls))
txt("FW0 pipeline [valid FBP + unreadable witness]: b8_text is the NONE form", _PIPE_C + "return b8_text(0, GOLDEN_PROFILE, e.cls); }()",
    lambda: cap.b8_text(0, GOLD_P, _pipe_py()[0].cls))

# =========================== marker probe, latch =====================================================================
_MAGIC = "MARKER_RECORD_MAGIC"
for _label, _load, _magic, _state in (("absent", 1, cap.MARKER_RECORD_MAGIC, 0), ("clear", 0, cap.MARKER_RECORD_MAGIC, 0),
                                      ("restore required", 0, cap.MARKER_RECORD_MAGIC, 1), ("pending clear", 0, cap.MARKER_RECORD_MAGIC, 2),
                                      ("unknown state 3", 0, cap.MARKER_RECORD_MAGIC, 3), ("unknown state 255", 0, cap.MARKER_RECORD_MAGIC, 255),
                                      ("bad magic", 0, 0x12345678, 0), ("zero magic", 0, 0, 1), ("wrong size", 2, cap.MARKER_RECORD_MAGIC, 0),
                                      ("read error", 3, cap.MARKER_RECORD_MAGIC, 0), ("storage unavailable", 4, cap.MARKER_RECORD_MAGIC, 0),
                                      ("unknown load 9", 9, cap.MARKER_RECORD_MAGIC, 0)):
    val(f"probe_result: {_label}", f"probe_result({_load}, {'MARKER_RECORD_MAGIC' if _magic == cap.MARKER_RECORD_MAGIC else str(_magic) + 'u'}, {_state})",
        lambda l=_load, m=_magic, s=_state: cap.probe_result(l, m, s))
for _p in range(0, 8):
    val(f"probe_latch_code {_p}", f"probe_latch_code({_p})", lambda p=_p: cap.probe_latch_code(p))
for _label, _cx, _py in (
        ("set FP=1", "latch_set(0, DOM_FP, 1)", lambda: cap.latch_set(0, 0, 1)), ("set DUMP=2", "latch_set(0, DOM_DUMP, 2)", lambda: cap.latch_set(0, 1, 2)),
        ("set R244=4", "latch_set(0, DOM_R244, 4)", lambda: cap.latch_set(0, 2, 4)),
        ("a set nibble is never changed", "latch_set(latch_set(0, DOM_FP, 1), DOM_FP, 3)", lambda: cap.latch_set(cap.latch_set(0, 0, 1), 0, 3)),
        ("code 0 never writes", "latch_set(0x0010, DOM_DUMP, 0)", lambda: cap.latch_set(0x0010, 1, 0)),
        ("another domain still sets", "latch_set(0x0001, DOM_R244, 2)", lambda: cap.latch_set(0x0001, 2, 2)),
        ("an unknown domain is ignored", "latch_set(0x0001, 5, 2)", lambda: cap.latch_set(0x0001, 5, 2)),
        ("get FP", "latch_get(0x0321, DOM_FP)", lambda: cap.latch_get(0x0321, 0)), ("get DUMP", "latch_get(0x0321, DOM_DUMP)", lambda: cap.latch_get(0x0321, 1)),
        ("get R244", "latch_get(0x0321, DOM_R244)", lambda: cap.latch_get(0x0321, 2)),
        ("get an unknown domain", "latch_get(0xFFFF, 9)", lambda: cap.latch_get(0xFFFF, 9))):
    val(f"latch: {_label}", _cx, _py)
for _l in (0x0000, 0x0001, 0x0010, 0x0100, 0x0011, 0x0101, 0x0110, 0x0111, 0x1000, 0x0004, 0xF000):
    txt(f"latch_text 0x{_l:04X}", f"latch_text(0x{_l:04X})", lambda l=_l: cap.latch_text(l))

# =========================== bus slot, FBS, MTOU =====================================================================
_BUS_FLAGS = ("manual_write_in_progress", "correction_in_progress", "verification_pending", "verification_read_active",
              "free_power_operation_in_progress", "free_power_recovery_force_in_progress", "free_power_recovery_accept_in_progress",
              "reg244_apply_in_progress", "dump_operation_in_progress", "fallback_profile_op_in_progress",
              "fallback_profile_capture_dispatch_running")
for _f in _BUS_FLAGS:
    strg(f"classify_bus with only {_f}", "[]{ GateInputs g = golden_gate_clear(); g.bus." + _f + " = true; const SlotClass c = classify_bus(g); "
         "return obl_code(c.kind, c.basis); }()",
         lambda f=_f: (lambda g: cap.obl_code(cap.classify_bus(g).kind, cap.classify_bus(g).basis))(
             _gi_with(bus={f: True})))
    strg(f"bus_owner_text with only {_f}", "[]{ BusInputs b; b." + _f + " = true; return bus_owner_text(b); }()",
         lambda f=_f: cap.bus_owner_text(cap.BusInputs(**{f: True})))
# RH4(a): SEVERAL owner flags at once. bus_owner_text names the most specific owner by a fixed priority (Free Power >
# Register 244 test > Dump to Grid > Fallback Profile > clock correction > clock verification > manual write); a mutant that
# swaps two neighbours is only visible when both flags are set, so every neighbouring pair is a golden.
_OWNER_COMBOS = [
    ("all eleven flags", _BUS_FLAGS),
    ("Free Power operation + Dump + R244", ("free_power_operation_in_progress", "dump_operation_in_progress", "reg244_apply_in_progress")),
    ("Free Power force + manual write", ("free_power_recovery_force_in_progress", "manual_write_in_progress")),
    ("Free Power accept + clock correction", ("free_power_recovery_accept_in_progress", "correction_in_progress")),
    ("Free Power outranks Register 244 test", ("free_power_operation_in_progress", "reg244_apply_in_progress")),
    ("Register 244 test outranks Dump to Grid", ("reg244_apply_in_progress", "dump_operation_in_progress")),
    ("Register 244 test outranks the Fallback Profile and the clocks", ("reg244_apply_in_progress", "fallback_profile_op_in_progress",
                                                                          "correction_in_progress", "manual_write_in_progress")),
    ("Dump to Grid outranks the Fallback Profile", ("dump_operation_in_progress", "fallback_profile_op_in_progress")),
    ("Dump to Grid outranks a clock", ("dump_operation_in_progress", "verification_pending")),
    ("the Fallback Profile operation outranks clock correction", ("fallback_profile_op_in_progress", "correction_in_progress")),
    ("the Fallback Profile dispatch outranks clock verification", ("fallback_profile_capture_dispatch_running", "verification_read_active")),
    ("clock correction outranks clock verification", ("correction_in_progress", "verification_pending", "verification_read_active")),
    ("clock verification outranks the manual write", ("verification_pending", "manual_write_in_progress")),
    ("a verification read with the manual write", ("verification_read_active", "manual_write_in_progress")),
]
for _label, _fl in _OWNER_COMBOS:
    strg(f"bus_owner_text with several owners: {_label}", "[]{ BusInputs b; " + "".join(f"b.{f} = true; " for f in _fl) + "return bus_owner_text(b); }()",
         lambda fl=_fl: cap.bus_owner_text(cap.BusInputs(**{f: True for f in fl})))
    strg(f"classify_bus with several owners: {_label}", "[]{ GateInputs g = golden_gate_clear(); " + "".join(f"g.bus.{f} = true; " for f in _fl)
         + "const SlotClass c = classify_bus(g); return obl_code(c.kind, c.basis); }()",
         lambda fl=_fl: (lambda c: cap.obl_code(c.kind, c.basis))(cap.classify_bus(_gi_with(bus={f: True for f in fl}))))
# FW1: the BUS refusal names an ACTIVE lease when the generic mutex flag is the ONLY owner flag (the Dump / Free Power controller ticks hold the shared lock
# through manual_write_in_progress alone). Only OBL_ACTIVE names a lease; Free Power before Dump to Grid; every named owner flag keeps the plain answer.
_LEASE_SLOTS = {"ACTIVE": ("SlotClass{OBL_ACTIVE, BASIS_LEASE}", cap.SlotClass(cap.OBL_ACTIVE, cap.BASIS_LEASE)),
                "NP": ("SlotClass{UNK_NOT_PROBED, BASIS_NONE}", cap.SlotClass(cap.UNK_NOT_PROBED, cap.BASIS_NONE)),
                "RR": ("SlotClass{OBL_RESTORE_REQUIRED, BASIS_NONE}", cap.SlotClass(cap.OBL_RESTORE_REQUIRED, cap.BASIS_NONE)),
                "ON": ("SlotClass{OBL_OPERATOR_NEEDED, BASIS_NONE}", cap.SlotClass(cap.OBL_OPERATOR_NEEDED, cap.BASIS_NONE)),
                "DV": ("SlotClass{UNK_DIVERGED, BASIS_RAM_INCONSISTENT}", cap.SlotClass(cap.UNK_DIVERGED, cap.BASIS_RAM_INCONSISTENT)),
                "ST": ("SlotClass{OBL_STARTING, BASIS_COMMITTED}", cap.SlotClass(cap.OBL_STARTING, cap.BASIS_COMMITTED)),
                "UNSET": ("SlotClass{}", cap.SlotClass())}
for _label, _flags, _fs, _ds in (
        ("the mutex alone, Free Power ACTIVE", ("manual_write_in_progress",), "ACTIVE", "NP"),
        ("the mutex alone, Dump ACTIVE", ("manual_write_in_progress",), "NP", "ACTIVE"),
        ("the mutex alone, both ACTIVE (Free Power first)", ("manual_write_in_progress",), "ACTIVE", "ACTIVE"),
        ("the mutex alone, no lease ACTIVE", ("manual_write_in_progress",), "NP", "NP"),
        ("the mutex alone, the all-zero SlotClass (fail-closed default) is not a lease", ("manual_write_in_progress",), "UNSET", "UNSET"),
        ("the mutex alone, leases restore-required (not ACTIVE)", ("manual_write_in_progress",), "RR", "RR"),
        ("the mutex alone, leases operator-needed (not ACTIVE)", ("manual_write_in_progress",), "ON", "ON"),
        ("the mutex alone, leases diverged (not ACTIVE)", ("manual_write_in_progress",), "DV", "DV"),
        ("the mutex alone, leases starting (not ACTIVE)", ("manual_write_in_progress",), "ST", "ST"),
        ("no flag at all, both ACTIVE", (), "ACTIVE", "ACTIVE")):
    strg(f"bus_owner_text_with_leases: {_label}",
         "[]{ BusInputs b; " + "".join(f"b.{f} = true; " for f in _flags) + f"return bus_owner_text_with_leases(b, {_LEASE_SLOTS[_fs][0]}, {_LEASE_SLOTS[_ds][0]}); }}()",
         lambda fl=_flags, f_=_fs, d_=_ds: cap.bus_owner_text_with_leases(cap.BusInputs(**{f: True for f in fl}), _LEASE_SLOTS[f_][1], _LEASE_SLOTS[d_][1]))
for _f in _BUS_FLAGS[1:]:
    strg(f"bus_owner_text_with_leases: the mutex + {_f} + both leases ACTIVE (a named owner outranks a lease)",
         "[]{ BusInputs b; b.manual_write_in_progress = true; b." + _f + f" = true; return bus_owner_text_with_leases(b, {_LEASE_SLOTS['ACTIVE'][0]}, {_LEASE_SLOTS['ACTIVE'][0]}); }}()",
         lambda f=_f: cap.bus_owner_text_with_leases(cap.BusInputs(manual_write_in_progress=True, **{f: True}), _LEASE_SLOTS["ACTIVE"][1], _LEASE_SLOTS["ACTIVE"][1]))
for _f in _BUS_FLAGS[1:]:
    strg(f"bus_owner_text_with_leases: {_f} without the mutex + both leases ACTIVE (the plain answer)",
         "[]{ BusInputs b; b." + _f + f" = true; return bus_owner_text_with_leases(b, {_LEASE_SLOTS['ACTIVE'][0]}, {_LEASE_SLOTS['ACTIVE'][0]}); }}()",
         lambda f=_f: cap.bus_owner_text_with_leases(cap.BusInputs(**{f: True}), _LEASE_SLOTS["ACTIVE"][1], _LEASE_SLOTS["ACTIVE"][1]))
for _label, _extra in (("a stuck lock outranks a busy bus (LK, not BY)", dict(dump_operation_in_progress=True)),
                       ("a lock held 299999 ms with other owners is still BY", dict(dump_operation_in_progress=True, diag_write_lock_since_ms=2000))):
    _kw = dict(manual_write_in_progress=True, diag_write_lock_held=True, diag_write_lock_since_ms=1000, now_ms=301000)
    _kw.update(_extra)
    strg(f"classify_bus: {_label}", "[]{ GateInputs g = golden_gate_clear(); " + "".join(
        f"g.bus.{k} = {str(v).lower() if isinstance(v, bool) else str(v) + 'u'}; " for k, v in _kw.items())
        + "const SlotClass c = classify_bus(g); return obl_code(c.kind, c.basis); }()",
         lambda kw=_kw: (lambda c: cap.obl_code(c.kind, c.basis))(cap.classify_bus(_gi_with(bus=kw))))
for _label, _flags in (("lock held 299999 ms", dict(manual_write_in_progress=True, diag_write_lock_held=True, diag_write_lock_since_ms=1000, now_ms=300999)),
                       ("lock held 300000 ms", dict(manual_write_in_progress=True, diag_write_lock_held=True, diag_write_lock_since_ms=1000, now_ms=301000)),
                       ("lock held, diagnostic says not held", dict(manual_write_in_progress=True, diag_write_lock_held=False, diag_write_lock_since_ms=1000, now_ms=999999)),
                       ("diagnostic held but the mutex is free", dict(manual_write_in_progress=False, diag_write_lock_held=True, diag_write_lock_since_ms=1000, now_ms=999999)),
                       ("lock age across the 2^32 wrap", dict(manual_write_in_progress=True, diag_write_lock_held=True, diag_write_lock_since_ms=4294967000, now_ms=300000 - 296)),
                       ("idle bus", dict())):
    _cx = "[]{ BusInputs b; " + "".join(f"b.{k} = {str(v).lower() if isinstance(v, bool) else str(v) + 'u'}; " for k, v in _flags.items()) + "return b; }()"
    val(f"lock_stuck: {_label}", f"lock_stuck({_cx})", lambda f=_flags: cap.lock_stuck(cap.BusInputs(**f)))
    val(f"bus_busy: {_label}", f"bus_busy({_cx})", lambda f=_flags: cap.bus_busy(cap.BusInputs(**f)))
    val(f"lock_age_ms: {_label}", f"lock_age_ms({_cx})", lambda f=_flags: cap.lock_age_ms(cap.BusInputs(**f)))
for _slot in range(0, 7):
    strg(f"classify_fbs slot {_slot}", "[]{ GateInputs g = golden_gate_clear(); g.fbs_slot = " + str(_slot) + "; const SlotClass c = classify_fbs(g); "
         "return obl_code(c.kind, c.basis); }()",
         lambda s=_slot: (lambda c: cap.obl_code(c.kind, c.basis))(cap.classify_fbs(_gi_with(fbs_slot=s))))
strg("classify_fbs: boot not loaded", "[]{ GateInputs g = golden_gate_clear(); g.boot_loaded = false; const SlotClass c = classify_fbs(g); "
     "return obl_code(c.kind, c.basis); }()", lambda: (lambda c: cap.obl_code(c.kind, c.basis))(cap.classify_fbs(_gi_with(boot_loaded=False))))
strg("classify_mtou: bus clear", "[]{ GateInputs g = golden_gate_clear(); const SlotClass c = classify_mtou(g); return obl_code(c.kind, c.basis); }()",
     lambda: (lambda c: cap.obl_code(c.kind, c.basis))(cap.classify_mtou(_gi_with())))
strg("classify_mtou: bus busy", "[]{ GateInputs g = golden_gate_clear(); g.bus.manual_write_in_progress = true; const SlotClass c = classify_mtou(g); "
     "return obl_code(c.kind, c.basis); }()",
     lambda: (lambda c: cap.obl_code(c.kind, c.basis))(cap.classify_mtou(_gi_with(bus={"manual_write_in_progress": True}))))
strg("classify_mtou: boot not loaded", "[]{ GateInputs g = golden_gate_clear(); g.boot_loaded = false; const SlotClass c = classify_mtou(g); "
     "return obl_code(c.kind, c.basis); }()", lambda: (lambda c: cap.obl_code(c.kind, c.basis))(cap.classify_mtou(_gi_with(boot_loaded=False))))


def _gi_with(**over) -> cap.GateInputs:
    """GateInputs mirror of golden_gate_clear() with overrides (bus={...}, fp={...}, dump={...}, r244={...}, other fields)."""
    g = cap.GateInputs(boot_loaded=True, fbs_slot=fd.FBS_CLEAR_ABSENT)
    g.fp.free_power_marker_boot_load = 1
    g.dump.dump_marker_boot_load = 1
    g.r244.reg244_marker_boot_load = 1
    for key, value in over.items():
        if key in ("bus", "fp", "dump", "r244"):
            for f, v in value.items():
                setattr(getattr(g, key), f, v)
        else:
            setattr(g, key, value)
    return g


# =========================== gate decisions ==========================================================================
def _gate_cxx(mods: str, probes: str = "ProbeResults{}") -> str:
    return "[]{ GateInputs g = golden_gate_clear(); " + mods + f" return gate_decide(g, {probes}); }}()"


_PROBE_ALL_CLEAR = ("ProbeResults{PROBE_ABSENT, PROBE_CLEAR, PROBE_ABSENT}", cap.ProbeResults(cap.PROBE_ABSENT, cap.PROBE_CLEAR, cap.PROBE_ABSENT))
# FW1: an ACTIVE lease (RAM leg: snapshot valid, marker RESTORE_REQUIRED, active_persisted) as the Dump / Free Power controller tick leaves it
_DUMP_ACT_CXX = "g.dump.dump_marker_boot_load = 0; g.dump.dump_snapshot_valid = true; g.dump.dump_marker_state = 1; g.dump.dump_active_persisted = true;"
_DUMP_ACT_PY = {"dump_marker_boot_load": 0, "dump_snapshot_valid": True, "dump_marker_state": 1, "dump_active_persisted": True}
_FP_ACT_CXX = "g.fp.free_power_marker_boot_load = 0; g.fp.free_power_snapshot_valid = true; g.fp.free_power_marker_state = 1; g.fp.free_power_active_persisted = true;"
_FP_ACT_PY = {"free_power_marker_boot_load": 0, "free_power_snapshot_valid": True, "free_power_marker_state": 1, "free_power_active_persisted": True}
_MW = "g.bus.manual_write_in_progress = true; "
_GATES = [
    ("all clear, nothing probed yet", "", {}, ("ProbeResults{}", cap.ProbeResults())),
    ("all clear, all probes clean", "", {}, _PROBE_ALL_CLEAR),
    ("all clear, FP probed only (the rest still pending)", "", {}, ("ProbeResults{PROBE_CLEAR, PROBE_NONE, PROBE_NONE}", cap.ProbeResults(cap.PROBE_CLEAR))),
    ("V1 an operation is in flight", "g.bus.fallback_profile_op_in_progress = true;", {"bus": {"fallback_profile_op_in_progress": True}}, None),
    ("V1 the capture dispatch is running", "g.bus.fallback_profile_capture_dispatch_running = true; g.boot_loaded = false;",
     {"bus": {"fallback_profile_capture_dispatch_running": True}, "boot_loaded": False}, None),
    ("V2 durable state not loaded", "g.boot_loaded = false;", {"boot_loaded": False}, None),
    ("V3 Free Power arm on", "g.free_power_write_enable = true;", {"free_power_write_enable": True}, None),
    ("V3 Dump arm on", "g.dump_write_enable = true;", {"dump_write_enable": True}, None),
    ("V3 Manual configuration arm on", "g.manual_config_write_enable = true;", {"manual_config_write_enable": True}, None),
    ("V3 outranks a busy bus", "g.free_power_write_enable = true; g.bus.manual_write_in_progress = true;",
     {"free_power_write_enable": True, "bus": {"manual_write_in_progress": True}}, None),
    ("V4 manual write holds the bus", "g.bus.manual_write_in_progress = true;", {"bus": {"manual_write_in_progress": True}}, None),
    ("V4 clock correction holds the bus", "g.bus.correction_in_progress = true;", {"bus": {"correction_in_progress": True}}, None),
    ("V4 the write lock is stuck",
     "g.bus.manual_write_in_progress = true; g.bus.diag_write_lock_held = true; g.bus.diag_write_lock_since_ms = 1000u; g.bus.now_ms = 481000u;",
     {"bus": {"manual_write_in_progress": True, "diag_write_lock_held": True, "diag_write_lock_since_ms": 1000, "now_ms": 481000}}, None),
    ("V4 several owners at once (Free Power, Dump, R244, clock correction): the text names Free Power",
     "g.bus.free_power_operation_in_progress = true; g.bus.dump_operation_in_progress = true; g.bus.reg244_apply_in_progress = true; "
     "g.bus.correction_in_progress = true; g.bus.manual_write_in_progress = true;",
     {"bus": {"free_power_operation_in_progress": True, "dump_operation_in_progress": True, "reg244_apply_in_progress": True,
              "correction_in_progress": True, "manual_write_in_progress": True}}, None),
    ("V4 Free Power holds the bus (and the lease flag)", "g.bus.free_power_operation_in_progress = true; g.bus.manual_write_in_progress = true;",
     {"bus": {"free_power_operation_in_progress": True, "manual_write_in_progress": True}}, None),
    ("V4 manual write holds the bus while a Dump lease is ACTIVE (the Dump controller tick): the text names Dump to Grid", _MW + _DUMP_ACT_CXX,
     {"bus": {"manual_write_in_progress": True}, "dump": _DUMP_ACT_PY}, None),
    ("V4 manual write holds the bus while a Free Power lease is ACTIVE (the Free Power controller tick): the text names Free Power", _MW + _FP_ACT_CXX,
     {"bus": {"manual_write_in_progress": True}, "fp": _FP_ACT_PY}, None),
    ("V4 manual write holds the bus while both leases are ACTIVE: the text names Free Power", _MW + _FP_ACT_CXX + " " + _DUMP_ACT_CXX,
     {"bus": {"manual_write_in_progress": True}, "fp": _FP_ACT_PY, "dump": _DUMP_ACT_PY}, None),
    ("V4 clock correction with the manual write and an ACTIVE Dump lease: the named owner outranks the lease", _MW + "g.bus.correction_in_progress = true; " + _DUMP_ACT_CXX,
     {"bus": {"manual_write_in_progress": True, "correction_in_progress": True}, "dump": _DUMP_ACT_PY}, None),
    ("V4 the write lock is stuck while a Dump lease is ACTIVE: the stuck text is unchanged",
     _MW + "g.bus.diag_write_lock_held = true; g.bus.diag_write_lock_since_ms = 1000u; g.bus.now_ms = 481000u; " + _DUMP_ACT_CXX,
     {"bus": {"manual_write_in_progress": True, "diag_write_lock_held": True, "diag_write_lock_since_ms": 1000, "now_ms": 481000}, "dump": _DUMP_ACT_PY}, None),
    ("V6 the same ACTIVE Dump lease with the bus free is refused at its own slot", _DUMP_ACT_CXX, {"dump": _DUMP_ACT_PY}, None),
    ("V3 the arms outrank a busy bus with an ACTIVE Dump lease", "g.dump_write_enable = true; " + _MW + _DUMP_ACT_CXX,
     {"dump_write_enable": True, "bus": {"manual_write_in_progress": True}, "dump": _DUMP_ACT_PY}, None),
    ("V5 FBS episode", "g.fbs_slot = ecco_fbdurable::FBS_OBLIGATION;", {"fbs_slot": fd.FBS_OBLIGATION}, None),
    ("V5 FBS corrupt", "g.fbs_slot = ecco_fbdurable::FBS_CORRUPT;", {"fbs_slot": fd.FBS_CORRUPT}, None),
    ("V5 FBS unreadable at boot", "g.fbs_slot = ecco_fbdurable::FBS_UNREADABLE;", {"fbs_slot": fd.FBS_UNREADABLE}, None),
    ("V5 FBS valid and CLEAR passes", "g.fbs_slot = ecco_fbdurable::FBS_CLEAR_VALID;", {"fbs_slot": fd.FBS_CLEAR_VALID}, _PROBE_ALL_CLEAR),
    ("V6 Free Power lease active",
     "g.fp.free_power_marker_boot_load = 0; g.fp.free_power_snapshot_valid = true; g.fp.free_power_marker_state = 1; g.fp.free_power_active_persisted = true;",
     {"fp": {"free_power_marker_boot_load": 0, "free_power_snapshot_valid": True, "free_power_marker_state": 1, "free_power_active_persisted": True}}, None),
    ("V6 Dump needs an operator",
     "g.dump.dump_marker_boot_load = 0; g.dump.dump_snapshot_valid = true; g.dump.dump_marker_state = 1; g.dump.dump_operator_needed = true;",
     {"dump": {"dump_marker_boot_load": 0, "dump_snapshot_valid": True, "dump_marker_state": 1, "dump_operator_needed": True}}, None),
    ("V6 Dump hard lockout with containment K",
     "g.dump.dump_marker_boot_load = 0; g.dump.dump_recovery_metadata_corrupt = true; g.dump.dump_containment_state = 3;",
     {"dump": {"dump_marker_boot_load": 0, "dump_recovery_metadata_corrupt": True, "dump_containment_state": 3}}, None),
    ("V6 Dump boot READ_ERROR (K = 8)",
     "g.dump.dump_marker_boot_load = 3; g.dump.dump_recovery_metadata_corrupt = true; g.dump.dump_containment_state = 8;",
     {"dump": {"dump_marker_boot_load": 3, "dump_recovery_metadata_corrupt": True, "dump_containment_state": 8}}, None),
    ("V6 R244 pending clear", "g.r244.reg244_snapshot_valid = true; g.r244.reg244_marker_state = 2;",
     {"r244": {"reg244_snapshot_valid": True, "reg244_marker_state": 2}}, None),
    ("V6 R244 apply running", "g.r244.run_apply = true;", {"r244": {"run_apply": True}}, None),
    ("V6 FP start running before its commit", "g.fp.run_start = true;", {"fp": {"run_start": True}}, None),
    ("V6 first non-clear wins: FP before Dump before R244",
     "g.fp.free_power_marker_state = 1; g.dump.dump_marker_state = 1; g.r244.reg244_marker_state = 1;",
     {"fp": {"free_power_marker_state": 1}, "dump": {"dump_marker_state": 1}, "r244": {"reg244_marker_state": 1}}, None),
    ("V6 a latched domain refuses (FP, unreadable)", "g.probe_latch = 0x0001;", {"probe_latch": 0x0001}, None),
    ("V6 a latched domain refuses (R244, ghost restore required)", "g.probe_latch = 0x0300;", {"probe_latch": 0x0300}, None),
    ("V7 FP marker unreadable at runtime", "", {}, ("ProbeResults{PROBE_UNREADABLE, PROBE_CLEAR, PROBE_ABSENT}", cap.ProbeResults(cap.PROBE_UNREADABLE, cap.PROBE_CLEAR, cap.PROBE_ABSENT))),
    ("V7 Dump marker malformed", "", {}, ("ProbeResults{PROBE_ABSENT, PROBE_MALFORMED, PROBE_ABSENT}", cap.ProbeResults(cap.PROBE_ABSENT, cap.PROBE_MALFORMED, cap.PROBE_ABSENT))),
    ("V7 R244 ghost restore required", "", {}, ("ProbeResults{PROBE_ABSENT, PROBE_CLEAR, PROBE_RESTORE_REQUIRED}", cap.ProbeResults(cap.PROBE_ABSENT, cap.PROBE_CLEAR, cap.PROBE_RESTORE_REQUIRED))),
    ("V7 FP ghost pending clear", "", {}, ("ProbeResults{PROBE_PENDING_CLEAR, PROBE_CLEAR, PROBE_CLEAR}", cap.ProbeResults(cap.PROBE_PENDING_CLEAR, cap.PROBE_CLEAR, cap.PROBE_CLEAR))),
    ("V7 all three unreadable", "", {}, ("ProbeResults{PROBE_UNREADABLE, PROBE_UNREADABLE, PROBE_MALFORMED}", cap.ProbeResults(cap.PROBE_UNREADABLE, cap.PROBE_UNREADABLE, cap.PROBE_MALFORMED))),
    ("V7 a set latch is never rewritten", "g.probe_latch = 0x0001;", {"probe_latch": 0x0001}, ("ProbeResults{PROBE_PENDING_CLEAR, PROBE_UNREADABLE, PROBE_ABSENT}", cap.ProbeResults(cap.PROBE_PENDING_CLEAR, cap.PROBE_UNREADABLE, cap.PROBE_ABSENT))),
    ("V7 a probe result is still latched when another slot already refuses", "g.bus.manual_write_in_progress = true;", {"bus": {"manual_write_in_progress": True}},
     ("ProbeResults{PROBE_UNREADABLE, PROBE_UNREADABLE, PROBE_UNREADABLE}", cap.ProbeResults(cap.PROBE_UNREADABLE, cap.PROBE_UNREADABLE, cap.PROBE_UNREADABLE))),
]
_PACKED_CXX = ("(uint64_t) r.code | ((uint64_t) r.slot << 8) | ((uint64_t) ((r.probe_fp ? 4 : 0) + (r.probe_dump ? 2 : 0) + (r.probe_r244 ? 1 : 0)) << 16) "
               "| ((uint64_t) r.latch << 24)")
for _label, _mods, _over, _probe in _GATES:
    _pc, _pp = _probe if _probe else ("ProbeResults{}", cap.ProbeResults())
    _head = "[]{ GateInputs g = golden_gate_clear(); " + _mods + f" const GateResult r = gate_decide(g, {_pc}); "
    _gpy = lambda over=_over, pp=_pp: cap.gate_decide(_gi_with(**over), pp)
    val(f"gate_decide [{_label}]: code | slot << 8 | probe flags << 16 | latch << 24", _head + f"return {_PACKED_CXX}; }}()",
        lambda g=_gpy: (lambda r: r.code | (r.slot << 8) | ((r.probe_fp * 4 + r.probe_dump * 2 + r.probe_r244) << 16) | (r.latch << 24))(g()))
    txt(f"gate_decide [{_label}]: obl", _head + "return r.obl; }()", lambda g=_gpy: g().obl)
    txt(f"gate_decide [{_label}]: text", _head + "return r.text; }()", lambda g=_gpy: g().text)

# housekeeping predicates
for _label, _mods, _over in (("nothing running", "", {}),
                             ("FP start running", "g.fp.run_start = true;", {"fp": {"run_start": True}}),
                             ("Dump restore running", "g.dump.run_restore = true;", {"dump": {"run_restore": True}}),
                             ("R244 apply running", "g.r244.run_apply = true;", {"r244": {"run_apply": True}}),
                             ("FP and Dump", "g.fp.free_power_marker_state = 1; g.dump.dump_marker_state = 1;",
                              {"fp": {"free_power_marker_state": 1}, "dump": {"dump_marker_state": 1}}),
                             ("only the bus is busy (not a lease domain)", "g.bus.manual_write_in_progress = true;", {"bus": {"manual_write_in_progress": True}}),
                             ("FBS episode is not a lease domain", "g.fbs_slot = ecco_fbdurable::FBS_OBLIGATION;", {"fbs_slot": fd.FBS_OBLIGATION}),
                             ("a latched domain", "g.probe_latch = 0x0010;", {"probe_latch": 0x0010})):
    val(f"lease_domain_nonclear: {_label}", "[]{ GateInputs g = golden_gate_clear(); " + _mods + " return lease_domain_nonclear(g); }()",
        lambda o=_over: cap.lease_domain_nonclear(_gi_with(**o)))
for _op, _run, _age, _start in ((True, False, 30000, 0), (True, False, 30001, 0), (True, True, 99999, 0), (False, False, 99999, 0),
                                (True, False, 29999, 0), (True, False, 30001, 4294937295), (True, False, 30000, 4294937295),
                                (True, False, 4000000000, 5)):
    _now = (_start + _age) % 2 ** 32
    val(f"breaker_fired op={_op} running={_run} age={_age} start={_start}",
        f"breaker_fired({str(_op).lower()}, {str(_run).lower()}, {_now}u, {_start}u)", lambda o=_op, r=_run, n=_now, s=_start: cap.breaker_fired(o, r, n, s))

# =========================== B2 / B3 / B4 / B5 / B6 / B7 / B8 =======================================================
_GP, _GWT = "GOLDEN_PROFILE", "GOLDEN_WITNESS"
_ABS_P = "ecco_fallback::FallbackProfileV1{}"
_ABS_W = "ecco_fbdurable::FailbackProvisionV1{}"
_B2 = [
    ("consistent VALID", LOAD_OK, "GOLDEN_PROFILE", GOLD_P, LOAD_OK, "GOLDEN_WITNESS", GOLD_W, 0, 0, 0),
    ("both absent (fresh device)", LOAD_ABSENT, _ABS_P, fp.blank_profile(), LOAD_ABSENT, _ABS_W, fd.blank_provision(), 0, 0, 0),
    ("profile lost: FBP absent, witness valid", LOAD_ABSENT, _ABS_P, fp.blank_profile(), LOAD_OK, "GOLDEN_WITNESS", GOLD_W, 0, 0, 0),
    ("VALID with the witness missing", LOAD_OK, "GOLDEN_PROFILE", GOLD_P, LOAD_ABSENT, _ABS_W, fd.blank_provision(), 6, 0, 0),
    ("VALID with a lagging witness", LOAD_OK, "GOLDEN_PROFILE", GOLD_P, LOAD_OK, Wt(hw=6, prior_gen=5).cxx(), Wt(hw=6, prior_gen=5).py(), 5, 0, 0),
    ("VALID with a corrupt witness", LOAD_OK, "GOLDEN_PROFILE", GOLD_P, LOAD_OK, Wt(corrupt=True).cxx(), Wt(corrupt=True).py(), 7, 0, 0),
    ("VALID with an unreadable witness", LOAD_OK, "GOLDEN_PROFILE", GOLD_P, LOAD_RERR, _ABS_W, fd.blank_provision(), 9, 0, 0),
    ("witness INVALIDATE op", LOAD_OK, "GOLDEN_PROFILE", GOLD_P, LOAD_OK, Wt(op=2).cxx(), Wt(op=2).py(), 0, 0, 0),
    ("witness REPLACE_CORRUPT op", LOAD_OK, "GOLDEN_PROFILE", GOLD_P, LOAD_OK, Wt(op=3).cxx(), Wt(op=3).py(), 0, 0, 0),
    ("witness first-save-unconfirmed shape", LOAD_ABSENT, _ABS_P, fp.blank_profile(), LOAD_OK, Wt(hw=1, prior_gen=0, prior_bind=0).cxx(),
     Wt(hw=1, prior_gen=0, prior_bind=0).py(), 11, 0, 0),
    ("stale: mismatch", LOAD_OK, Pf(generation=7, captured_epoch=5).cxx(), Pf(generation=7, captured_epoch=5).py(), LOAD_OK, "GOLDEN_WITNESS", GOLD_W, 3, 0, 0),
    ("INVALIDATED", LOAD_OK, Pf(flags=1, generation=8).cxx(), Pf(flags=1, generation=8).py(), LOAD_OK, Wt(hw=8, prior_gen=7, op=2).cxx(),
     Wt(hw=8, prior_gen=7, op=2).py(), 0, 0, 0),
    ("CORRUPT: bad magic", LOAD_OK, Pf(magic=1).cxx(), Pf(magic=1).py(), LOAD_OK, "GOLDEN_WITNESS", GOLD_W, 0, 0, 0),
    ("CORRUPT: bad schema", LOAD_OK, Pf(schema=2).cxx(), Pf(schema=2).py(), LOAD_ABSENT, _ABS_W, fd.blank_provision(), 0, 0, 0),
    ("CORRUPT: bad size field", LOAD_OK, Pf(size=95).cxx(), Pf(size=95).py(), LOAD_OK, "GOLDEN_WITNESS", GOLD_W, 0, 0, 0),
    ("CORRUPT: bad binding", LOAD_OK, Pf(seal=False, generation=8).cxx(), Pf(seal=False, generation=8).py(), LOAD_OK, "GOLDEN_WITNESS", GOLD_W, 0, 0, 0),
    ("CORRUPT: reserved bits", LOAD_OK, Pf(reserved0=1).cxx(), Pf(reserved0=1).py(), LOAD_OK, "GOLDEN_WITNESS", GOLD_W, 0, 0, 0),
    ("CORRUPT: unknown flag", LOAD_OK, Pf(flags=2).cxx(), Pf(flags=2).py(), LOAD_OK, "GOLDEN_WITNESS", GOLD_W, 0, 0, 0),
    ("CORRUPT: generation 0", LOAD_OK, Pf(generation=0).cxx(), Pf(generation=0).py(), LOAD_OK, "GOLDEN_WITNESS", GOLD_W, 0, 0, 0),
    ("CORRUPT_DOMAIN: 244 = 1 (authentic)", LOAD_OK, Pf(reg244=1).cxx(), Pf(reg244=1).py(), LOAD_OK, "GOLDEN_WITNESS", GOLD_W, 5, 0, 0),
    ("CORRUPT_DOMAIN: worst widths", LOAD_OK, pf_all5().cxx(), pf_all5().py(), LOAD_OK,
     Wt(hw=4294967294, prior_gen=4294967293, op=1).cxx(), Wt(hw=4294967294, prior_gen=4294967293, op=1).py(), 5, 0, 0),
    ("wrong stored size", LOAD_WSZ, _ABS_P, fp.blank_profile(), LOAD_OK, "GOLDEN_WITNESS", GOLD_W, 0, 0, 0),
    ("profile read error", LOAD_RERR, _ABS_P, fp.blank_profile(), LOAD_OK, "GOLDEN_WITNESS", GOLD_W, 8, 0, 0),
    ("storage unavailable", LOAD_UNAV, _ABS_P, fp.blank_profile(), LOAD_UNAV, _ABS_W, fd.blank_provision(), 8, 0, 0),
    ("werr and us set (the FB-B2 shape)", LOAD_OK, "GOLDEN_PROFILE", GOLD_P, LOAD_OK, "GOLDEN_WITNESS", GOLD_W, 0, 4359, 1234),
    ("werr and us at their widest", LOAD_OK, "GOLDEN_PROFILE", GOLD_P, LOAD_OK, "GOLDEN_WITNESS", GOLD_W, 0, 4294967295, 4294967295),
]
for _label, _pl, _pc, _pp, _wl, _wc, _wp, _why, _err, _us in _B2:
    txt(f"b2_text: {_label}", f"b2_text({_pl}, {_pc}, {_wl}, {_wc}, {_why}, {_err}u, {_us}u)",
        lambda pl=_pl, pp=_pp, wl=_wl, wp=_wp, why=_why, err=_err, us=_us: cap.b2_text(pl, pp, wl, wp, why, err, us))

_CAND_W = [("golden", Wd()), ("all 0xFFFF", ALL_FFFF), ("all zero", ALL_ZERO), ("five-digit HHMM and SRC", WD(w22=65535, w27=65535, w13=65535)),
           ("a mix", WD(w0=0, w1=499, w8=101, w15=3, w25=2400))]
for _label, _w in _CAND_W:
    txt(f"b5_text: {_label}, with stored dx 0x1A2B3", f"b5_text(true, {_w.cxx()}, true, 0x1A2B3u)", lambda w=_w: cap.b5_text(True, w.py(), True, 0x1A2B3))
    txt(f"b5_text: {_label}, no authentic stored profile", f"b5_text(true, {_w.cxx()}, false, 0x1A2B3u)", lambda w=_w: cap.b5_text(True, w.py(), False, 0x1A2B3))
    txt(f"b6_text: {_label}, with stored dc 0x1FF di 0x1F", f"b6_text(true, {_w.cxx()}, true, 0x1FFu, 0x1Fu)", lambda w=_w: cap.b6_text(True, w.py(), True, 0x1FF, 0x1F))
    txt(f"b6_text: {_label}, no authentic stored profile", f"b6_text(true, {_w.cxx()}, false, 0x1FFu, 0x1Fu)", lambda w=_w: cap.b6_text(True, w.py(), False, 0x1FF, 0x1F))
txt("b5_text: no candidate (NONE form)", "b5_text(false, GOLDEN_WORDS, true, 0x1A2B3u)", lambda: cap.b5_text(False, GW, True, 0x1A2B3))
txt("b6_text: no candidate (NONE form)", "b6_text(false, GOLDEN_WORDS, true, 0x1FFu, 0x1Fu)", lambda: cap.b6_text(False, GW, True, 0x1FF, 0x1F))
txt("b5_text: dx 0x7FFFF", "b5_text(true, GOLDEN_WORDS, true, 0x7FFFFu)", lambda: cap.b5_text(True, GW, True, 0x7FFFF))
val("b5_text: worst case fits (all words 0xFFFF, dx 7FFFF)", f"b5_text(true, {ALL_FFFF.cxx()}, true, 0x7FFFFu).size()", lambda: len(cap.b5_text(True, ALL_FFFF.py(), True, 0x7FFFF)))
val("b6_text: worst case fits", f"b6_text(true, {ALL_FFFF.cxx()}, true, 0x1FFu, 0x1Fu).size()", lambda: len(cap.b6_text(True, ALL_FFFF.py(), True, 0x1FF, 0x1F)))

_SAVED = [("VALID", LOAD_OK, Pf(), 5), ("INVALIDATED", LOAD_OK, Pf(flags=1, generation=8), 4), ("CORRUPT_DOMAIN", LOAD_OK, Pf(reg244=1, generation=9), 3),
          ("PROFILE_STALE over an authentic record", LOAD_OK, Pf(), 8), ("UNREADABLE class over an authentic record", LOAD_OK, Pf(), 0),
          ("NOT_CAPTURED", LOAD_ABSENT, Pf(), 1), ("CORRUPT", LOAD_OK, Pf(magic=1), 2), ("PROFILE_LOST", LOAD_ABSENT, Pf(), 6),
          ("wrong size", LOAD_WSZ, Pf(), 2), ("read error", LOAD_RERR, Pf(), 0),
          ("worst widths, domain-valid VALID", LOAD_OK, Pf(generation=4294967295, **{"reg250_255[0]": 65535, "reg250_255[5]": 65535}), 5),
          ("CORRUPT_DOMAIN with every value 5 digits (over 200: the NONE form)", LOAD_OK, pf_all5(), 3),
          ("CORRUPT_DOMAIN with narrower values still fits", LOAD_OK, Pf(reg244=65535, generation=4294967295), 3)]
for _label, _load, _p, _cls in _SAVED:
    txt(f"b7_text: {_label}", f"b7_text({_load}, {_p.cxx()}, {_cls})", lambda l=_load, p=_p, c=_cls: cap.b7_text(l, p.py(), c))
    txt(f"b8_text: {_label}", f"b8_text({_load}, {_p.cxx()}, {_cls})", lambda l=_load, p=_p, c=_cls: cap.b8_text(l, p.py(), c))
val("b7_text: the domain-valid worst case is below 200 chars", f"b7_text(0, {_SAVED[10][2].cxx()}, 5).size()", lambda: len(cap.b7_text(0, _SAVED[10][2].py(), 5)))

# RH1: B7 and B8 share ONE predicate (saved_view). An authentic CORRUPT_DOMAIN record with every value 5 digits wide makes the
# B7 SAVED text 202 characters: BOTH views then publish their NONE form (B7 used to fall back alone while B8 still said SAVED).
_NONE7 = "v=NONE;g=-;244=-;1=-;2=-;3=-;4=-;5=-;6=-;dx=-;b=-"
_NONE8 = "v=NONE;232=-;243=-;248=-;ring=-;230=-;245=-;247=-;dc=-;di=-;b=-"
_ALL5 = pf_all5()
for _cls in (3, 4, 5, 8, 0):
    val(f"B7 and B8 agree: the all-5-digit authentic CORRUPT_DOMAIN record under effective class {_cls} gives the NONE form in BOTH views",
        f"[]{{ const ecco_fallback::FallbackProfileV1 rec = {_ALL5.cxx()}; return text_is(\"{_NONE7}\", b7_text(0, rec, {_cls})) && "
        f"text_is(\"{_NONE8}\", b8_text(0, rec, {_cls})); }}()",
        lambda c=_cls: str(cap.b7_text(0, _ALL5.py(), c)) == _NONE7 and str(cap.b8_text(0, _ALL5.py(), c)) == _NONE8)
val("B7 and B8 agree: both views give the same SAVED / NONE verdict on every fixture of the B7 / B8 table",
    "[]{ bool ok = true; " + "".join(
        f"ok = ok && (b7_text({_l}, {_p.cxx()}, {_c}).buf[2] == b8_text({_l}, {_p.cxx()}, {_c}).buf[2]); " for _lb, _l, _p, _c in _SAVED)
    + "return ok; }()",
    lambda: all(str(cap.b7_text(l, p.py(), c))[2] == str(cap.b8_text(l, p.py(), c))[2] for _lb, l, p, c in _SAVED))

for _label, _st, _have, _prior, _exp, _warn, _obl, _latch, _sv in (
        ("boot value (IDLE, nothing evaluated)", 0, False, 0, 0, 0, "-", 0, "-"),
        ("READING with the persisted vector", 1, False, 0, 0, 0, "FP:CA,DP:CA,R4:CA,MT:CN,FS:CA,BUS:OK", 0, "-"),
        ("CANDIDATE_READY typical", 2, True, 5, 120, 0, "FP:CA,DP:CM,R4:CA,MT:CN,FS:CA,BUS:OK", 0, "OK"),
        ("CANDIDATE_READY, exp 57, warnings W1,W6", 2, True, 1, 57, 0x21, "FP:CM,DP:CM,R4:CM,MT:CN,FS:CM,BUS:OK", 0, "OK"),
        ("CANDIDATE_NOT_SAVEABLE typical", 3, True, 0, 119, 0, "FP:CA,DP:CA,R4:CA,MT:CN,FS:CA,BUS:OK", 0, "OK"),
        ("CANDIDATE_NOT_SAVEABLE with refusals", 3, True, 5, 3, 0x04, "FP:CA,DP:CA,R4:CA,MT:CN,FS:CA,BUS:OK", 0, "NO:244X,PWRL1+2"),
        ("IDLE after a refusal: vector and latch kept, the rest -", 0, False, 5, 100, 0x3F, "FP:UR,DP:NP,R4:NP,MT:CN,FS:CA,BUS:OK", 0x0001, "NO:244X"),
        ("latch FP,DP,R4", 0, False, 0, 0, 0, "FP:UR,DP:MC,R4:DV,MT:CN,FS:CA,BUS:OK", 0x0211, "-"),
        ("worst case widths", 3, True, 7, 120, 0x3F, "FP:UR,DP:UR,R4:UR,MT:NP,FS:UR,BUS:LK", 0x0111, "NO:PWRL1,PWRL2,PWRL3+35"),
        ("an empty obl and an empty sv fall back to -", 2, True, 8, 9, 0, "", 0, ""),
        ("prior PROFILE_STALE", 2, True, 8, 10, 0x08, "FP:CM,DP:CM,R4:CM,MT:CN,FS:CA,BUS:OK", 0, "OK"),
        # RH2: the robustness rule - an obl longer than 36 / an sv longer than 26 characters renders `-` (never cut), every key present
        ("an obl of 37 characters falls back to - (never cut)", 2, True, 5, 120, 0, "FP:CA,DP:CM,R4:CA,MT:CN,FS:CA,BUS:OKX", 0, "OK"),
        ("an obl of 300 characters falls back to - and every key is still present", 3, True, 5, 120, 0x3F, "X" * 300, 0x0111, "NO:244X"),
        ("an sv of exactly 26 characters is kept", 2, True, 5, 120, 0, "FP:CA,DP:CM,R4:CA,MT:CN,FS:CA,BUS:OK", 0, "NO:" + "P" * 23),
        ("an sv of 27 characters falls back to -", 2, True, 5, 120, 0, "FP:CA,DP:CM,R4:CA,MT:CN,FS:CA,BUS:OK", 0, "NO:" + "P" * 24),
        ("an sv of 300 characters falls back to -", 2, True, 5, 120, 0, "FP:CA,DP:CM,R4:CA,MT:CN,FS:CA,BUS:OK", 0, "S" * 300),
        ("an over-long obl AND sv: the latch and every key survive", 3, True, 7, 120, 0x3F, "O" * 200, 0x0111, "S" * 200),
        ("an over-long sv without a candidate is - like any sv", 0, False, 0, 0, 0, "FP:CA,DP:CA,R4:CA,MT:CN,FS:CA,BUS:OK", 0, "S" * 300)):
    txt(f"b3_text: {_label}", f"b3_text({_st}, {str(_have).lower()}, {_prior}, {_exp}u, 0x{_warn:X}u, \"{_obl}\", 0x{_latch:X}u, \"{_sv}\")",
        lambda st=_st, h=_have, pr=_prior, e=_exp, w=_warn, o=_obl, la=_latch, sv=_sv: cap.b3_text(st, h, pr, e, w, o, la, sv))
txt("b3_text: a null obl and a null sv fall back to -", "b3_text(2, true, 5, 9u, 0x0u, nullptr, 0x0u, nullptr)", lambda: cap.b3_text(2, True, 5, 9, 0, None, 0, None))
for _s, _m in (("", 5), ("a", 1), ("ab", 1), ("abc", 3), ("abcd", 3), ("X" * 36, 36), ("X" * 37, 36), ("X" * 300, 36), ("X" * 26, 26),
               ("X" * 27, 26)):
    val(f"b3_value_fits {len(_s)} chars, max {_m}", f"b3_value_fits(\"{_s}\", {_m})", lambda s=_s, m=_m: cap.b3_value_fits(s, m))
val("b3_value_fits: a null value", "b3_value_fits(nullptr, 5)", lambda: False)
for _w in (0, 1, 2, 4, 8, 16, 32, 0x21, 0x3F, 0x40):
    txt(f"warn_text 0x{_w:02X}", f"warn_text(0x{_w:X}u)", lambda w=_w: cap.warn_text(w))
txt("vector_text: a mixed vector", "vector_text(SlotClass{OBL_CLEAR_PROVEN, BASIS_MARKER_CLEAR}, SlotClass{UNK_NOT_PROBED, BASIS_NONE}, "
    "SlotClass{OBL_ACTIVE, BASIS_LEASE}, SlotClass{OBL_CLEAR_PROVEN, BASIS_NO_DURABLE_STATE}, SlotClass{UNK_METADATA_CORRUPT, BASIS_BOOT_LOCKOUT}, "
    "SlotClass{BUS_BUSY, BASIS_BUS_TXN})", lambda: cap.vector_text(
        cap.SlotClass(cap.OBL_CLEAR_PROVEN, cap.BASIS_MARKER_CLEAR), cap.SlotClass(cap.UNK_NOT_PROBED, cap.BASIS_NONE),
        cap.SlotClass(cap.OBL_ACTIVE, cap.BASIS_LEASE), cap.SlotClass(cap.OBL_CLEAR_PROVEN, cap.BASIS_NO_DURABLE_STATE),
        cap.SlotClass(cap.UNK_METADATA_CORRUPT, cap.BASIS_BOOT_LOCKOUT), cap.SlotClass(cap.BUS_BUSY, cap.BASIS_BUS_TXN)))
txt("vector_text: the all-zero SlotClass renders UR everywhere (fail-closed)", "vector_text(SlotClass{}, SlotClass{}, SlotClass{}, SlotClass{}, SlotClass{}, SlotClass{})",
    lambda: cap.vector_text(*[cap.SlotClass() for _ in range(6)]))

# =========================== B9 texts ===============================================================================
for _name in ("b9_seed_text", "review_in_progress_text", "candidate_ready_text", "review_expired_text", "review_cleared_writes_text",
              "internal_context_text"):
    txt(f"{_name}", f"{_name}()", lambda n=_name: getattr(cap, n)())
for _s in (cap.SLOT_FP, cap.SLOT_DUMP, cap.SLOT_R244):
    txt(f"review_cleared_domain_text {_s}", f"review_cleared_domain_text({_s})", lambda s=_s: cap.review_cleared_domain_text(s))
for _held in (True, False):
    txt(f"breaker_text lock_held={_held}", f"breaker_text({str(_held).lower()})", lambda h=_held: cap.breaker_text(h))
for _code in range(0, 9):
    for _step in (1, 2, 3, 4):
        txt(f"read_fail_text code {_code} step {_step}", f"read_fail_text({_code}, {_step}, 0)", lambda c=_code, s=_step: cap.read_fail_text(c, s, 0))
txt("read_fail_text: exception code 0x02 on step 2", "read_fail_text(READ_EXCEPTION, 2, 2)", lambda: cap.read_fail_text(cap.READ_EXCEPTION, 2, 2))
txt("read_fail_text: exception code 0xFF on step 1", "read_fail_text(READ_EXCEPTION, 1, 255)", lambda: cap.read_fail_text(cap.READ_EXCEPTION, 1, 255))
txt("read_fail_text: an unknown step", "read_fail_text(READ_SHORT, 9, 0)", lambda: cap.read_fail_text(cap.READ_SHORT, 9, 0))
for _label, _w in (("first difference is register 244", WD(w0=0)), ("first difference is 256", WD(w1=501)), ("first is 274 (index 13)", WD(w13=3, w25=1)),
                   ("232 (index 19)", WD(w19=0x13)), ("247 (index 30)", WD(w30=65535)), ("both at 5 and 20: the lower index", WD(w20=0, w5=1)),
                   ("the passes agree", Wd())):
    txt(f"pass_mismatch_text: {_label}", f"pass_mismatch_text(GOLDEN_WORDS, {_w.cxx()})", lambda w=_w: cap.pass_mismatch_text(GW, w.py()))
txt("pass_mismatch_text: widest values", f"pass_mismatch_text({ALL_FFFF.cxx()}, {ALL_ZERO.cxx()})", lambda: cap.pass_mismatch_text(ALL_FFFF.py(), ALL_ZERO.py()))
for _label, _w, _cls, _anom in (
        ("one refusal", WD(w0=0), 5, 0), ("two refusals", WD(w0=0, w1=499), 5, 0), ("three refusals: +1 more", WD(w0=0, w1=499, w8=101), 5, 0),
        ("every refusal: +36 more", ALL_FFFF, 5, 0), ("class only: UNREADABLE", Wd(), 0, 4), ("class only: SAVE_UNCONFIRMED", Wd(), 7, 0),
        ("class only: a class that does not permit saving", Wd(), 9, 0), ("anomaly with a permitted class", Wd(), 5, 4),
        ("anomaly 1 (the profile key bit) with a permitted VALID class", Wd(), 5, 1), ("anomaly 2 (the witness key bit) with a permitted class", Wd(), 5, 2),
        ("anomaly 3 (both key bits) with a permitted class", Wd(), 5, 3), ("a refusal and anomaly 1 with a permitted class", WD(w0=0), 5, 1),
        ("anomaly 1 with a class that does not permit saving: the class reason wins", Wd(), 0, 1),
        ("a refusal and the class", WD(w0=1), 0, 4), ("two refusals and the class: +1 more", WD(w0=0, w1=0), 0, 0),
        ("no reason at all", Wd(), 5, 0), ("244 = 7 is unrecognised", WD(w0=7), 5, 0), ("power above a 5000 ceiling is reported as site ceiling", WD(w1=6000), 5, 0),
        ("SOC", WD(w9=101), 5, 0), ("source flags", WD(w15=0x27), 5, 0), ("HHMM", WD(w23=2400), 5, 0), ("243", WD(w20=7), 5, 0),
        ("power 8001", WD(w2=8001), 5, 0), ("power 0", WD(w3=0), 5, 0)):
    txt(f"not_saveable_text: {_label}", f"not_saveable_text(capture_refusals({_w.cxx()}, 8000u), {_w.cxx()}, {_cls}, {_anom})",
        lambda w=_w, c=_cls, a=_anom: cap.not_saveable_text(cap.capture_refusals(w.py(), 8000), w.py(), c, a))
txt("not_saveable_text: a site ceiling of 5000 (the PWRH reason names the site)",
    f"not_saveable_text(capture_refusals({WD(w1=6000).cxx()}, 5000u), {WD(w1=6000).cxx()}, 5, 0)",
    lambda: cap.not_saveable_text(cap.capture_refusals(WD(w1=6000).py(), 5000), WD(w1=6000).py(), 5, 0))
for _r in ("", "superseded", "superseded by a new Review", "expired", "REVIEW EXPIRED - candidate expired (120 s); review again", "supersede", "s"):
    val(f"invalidate_reason_publishes {_r!r}", f"invalidate_reason_publishes(\"{_r}\")", lambda r=_r: cap.invalidate_reason_publishes(r))
val("invalidate_reason_publishes: a null reason", "invalidate_reason_publishes(nullptr)", lambda: False)

# =========================== gate refusal texts, slot by slot =======================================================
_SLOT_KINDS = [("OBL_ACTIVE", "BASIS_LEASE"), ("OBL_ACTIVE", "BASIS_FBS_EPISODE"), ("OBL_STARTING", "BASIS_PRE_COMMIT"), ("OBL_STARTING", "BASIS_COMMITTED"),
               ("OBL_RESTORE_REQUIRED", "BASIS_NONE"), ("OBL_PENDING_CLEAR", "BASIS_NONE"), ("OBL_ENDING", "BASIS_OPERATOR_ACTION_RUNNING"),
               ("OBL_ENDING", "BASIS_RESTORE_RUNNING"), ("OBL_OPERATOR_NEEDED", "BASIS_NONE"), ("UNK_DURABLE_UNREADABLE", "BASIS_BOOT_READ_ERROR"),
               ("UNK_DURABLE_UNREADABLE", "BASIS_RUNTIME_PROBE"), ("UNK_METADATA_CORRUPT", "BASIS_BOOT_LOCKOUT"), ("UNK_METADATA_CORRUPT", "BASIS_RUNTIME_PROBE"),
               ("UNK_BOOT_NOT_LOADED", "BASIS_NONE"), ("UNK_DIVERGED", "BASIS_GHOST_RR"), ("UNK_DIVERGED", "BASIS_GHOST_PC"),
               ("UNK_DIVERGED", "BASIS_RAM_INCONSISTENT"), ("UNK_BUS_OR_LOCK_STUCK", "BASIS_OP_FLAG_UNATTRIBUTED"), ("UNK_NOT_PROBED", "BASIS_NONE")]
for _slot_name, _slot in (("SLOT_R244", cap.SLOT_R244), ("SLOT_FP", cap.SLOT_FP), ("SLOT_DUMP", cap.SLOT_DUMP), ("SLOT_FBS", cap.SLOT_FBS)):
    for _k, _b in _SLOT_KINDS:
        if _slot_name != "SLOT_R244" and (_k, _b) not in (("OBL_ACTIVE", "BASIS_LEASE"), ("UNK_METADATA_CORRUPT", "BASIS_BOOT_LOCKOUT"),
                                                          ("UNK_DURABLE_UNREADABLE", "BASIS_BOOT_READ_ERROR"), ("OBL_ACTIVE", "BASIS_FBS_EPISODE"),
                                                          ("OBL_PENDING_CLEAR", "BASIS_NONE"), ("OBL_STARTING", "BASIS_PRE_COMMIT")):
            continue
        txt(f"refusal_text {_slot_name} {_k} {_b}", f"refusal_text({_slot_name}, SlotClass{{{_k}, {_b}}}, 0, \"x\", 0u)",
            lambda s=_slot, k=_k, b=_b: cap.refusal_text(s, cap.SlotClass(getattr(cap, k), getattr(cap, b)), 0, "x", 0))
txt("refusal_text SLOT_DUMP corrupt with containment K=5", "refusal_text(SLOT_DUMP, SlotClass{UNK_METADATA_CORRUPT, BASIS_BOOT_LOCKOUT}, 5, \"\", 0u)",
    lambda: cap.refusal_text(cap.SLOT_DUMP, cap.SlotClass(cap.UNK_METADATA_CORRUPT, cap.BASIS_BOOT_LOCKOUT), 5, "", 0))
txt("refusal_text SLOT_FP corrupt ignores the Dump K", "refusal_text(SLOT_FP, SlotClass{UNK_METADATA_CORRUPT, BASIS_BOOT_LOCKOUT}, 5, \"\", 0u)",
    lambda: cap.refusal_text(cap.SLOT_FP, cap.SlotClass(cap.UNK_METADATA_CORRUPT, cap.BASIS_BOOT_LOCKOUT), 5, "", 0))
for _owner in ("Free Power", "Register 244 test", "Dump to Grid", "Fallback Profile", "clock correction", "clock verification", "manual write"):
    txt(f"refusal_text SLOT_BUS busy, owner {_owner}", f"refusal_text(SLOT_BUS, SlotClass{{BUS_BUSY, BASIS_BUS_TXN}}, 0, \"{_owner}\", 0u)",
        lambda o=_owner: cap.refusal_text(cap.SLOT_BUS, cap.SlotClass(cap.BUS_BUSY, cap.BASIS_BUS_TXN), 0, o, 0))
for _age in (300, 4294967):
    txt(f"refusal_text SLOT_BUS stuck, {_age} s", f"refusal_text(SLOT_BUS, SlotClass{{UNK_BUS_OR_LOCK_STUCK, BASIS_LOCK_STUCK}}, 0, \"\", {_age}u)",
        lambda a=_age: cap.refusal_text(cap.SLOT_BUS, cap.SlotClass(cap.UNK_BUS_OR_LOCK_STUCK, cap.BASIS_LOCK_STUCK), 0, "", a))
for _name in ("refused_in_flight_text", "refused_not_loaded_text", "refused_arms_text"):
    txt(_name, f"{_name}()", lambda n=_name: getattr(cap, n)())

# =========================== text lengths ===========================================================================
_B2_WORST = (f"b2_text(0, {pf_all5().cxx()}, 0, {Wt(hw=4294967294, prior_gen=4294967293).cxx()}, 5, 4294967295u, 4294967295u)")
val("length of the b2 worst case", f"({_B2_WORST}).size()",
    lambda: len(cap.b2_text(0, pf_all5().py(), 0, Wt(hw=4294967294, prior_gen=4294967293).py(), 5, 4294967295, 4294967295)))
val("length of the b3 worst case", "b3_text(3, true, 7, 120u, 0x3Fu, \"FP:UR,DP:UR,R4:UR,MT:NP,FS:UR,BUS:LK\", 0x0111u, \"NO:PWRL1,PWRL2,PWRL3+35\").size()",
    lambda: len(cap.b3_text(3, True, 7, 120, 0x3F, "FP:UR,DP:UR,R4:UR,MT:NP,FS:UR,BUS:LK", 0x0111, "NO:PWRL1,PWRL2,PWRL3+35")))
val("length of the b3 absolute worst case (every argument at its maximum: 172)",
    "b3_text(3, true, 7, 4294967295u, 0xFFFFu, \"FP:UR,DP:UR,R4:UR,MT:NP,FS:UR,BUS:LK\", 0xFFFFu, \"" + "N" * 26 + "\").size()",
    lambda: len(cap.b3_text(3, True, 7, 4294967295, 0xFFFF, "FP:UR,DP:UR,R4:UR,MT:NP,FS:UR,BUS:LK", 0xFFFF, "N" * 26)))


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
            lines.append(f"static_assert(({g.cxx}) == {lit}, \"FB-B1 value: {g.label}\");")
        elif g.kind == "text":
            s = str(v)
            assert '"' not in s and "\\" not in s, s
            lines.append(f"static_assert(text_is(\"{s}\", {g.cxx}), \"FB-B1 text: {g.label}\");")
        else:
            s = str(v)
            assert '"' not in s and "\\" not in s, s
            lines.append(f"static_assert(str_is({g.cxx}, \"{s}\"), \"FB-B1 name: {g.label}\");")
    return "\n".join(lines) + "\n"


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


def read_header() -> str:
    return HEADER_PATH.read_text(encoding="utf-8")


class Toolchain:
    """Stages the three headers in an include directory and compiles translation units against it."""

    def __init__(self, cxx: str) -> None:
        self.cxx = cxx
        self.tmp = Path(tempfile.mkdtemp(prefix="ecco_fbb1_cap_"))

    def stage(self, name: str, capture_text: str | None = None) -> Path:
        inc = self.tmp / name / "include"
        inc.mkdir(parents=True, exist_ok=True)
        shutil.copy(FBA_PATH, inc / FBA_PATH.name)
        shutil.copy(MODEL_PATH, inc / MODEL_PATH.name)
        (inc / HEADER_PATH.name).write_text(read_header() if capture_text is None else capture_text, encoding="utf-8", newline="\n")
        return inc

    def compile(self, inc: Path, source: str, std: str = "gnu++17", extra=()) -> subprocess.CompletedProcess:
        tu = inc.parent / f"tu_{abs(hash((source, std, tuple(extra)))) % 10 ** 9}.cpp"
        tu.write_text(source, encoding="utf-8", newline="\n")
        return run([self.cxx, f"-std={std}", "-fsyntax-only", *STRICT, *extra, "-I", str(inc), str(tu)])


TWICE = '#include "ecco_fallback_capture.h"\n#include "ecco_fallback_capture.h"\nint main() { return 0; }\n'


def table_rows(text: str, name: str) -> list[list[str]]:
    """The rows of `constexpr <Row> NAME[] = { {..}, ... };` as lists of tokens (comments stripped)."""
    m = re.search(rf"constexpr \w+ {name}\[\] = \{{(.*?)\n\}};", text, re.S)
    assert m, name
    body = re.sub(r"//[^\n]*", "", m.group(1))
    return [[t.strip() for t in row.split(",")] for row in re.findall(r"\{([^{}]*)\}", body)]


def token_value(tok: str) -> int:
    return int(tok) if re.fullmatch(r"\d+", tok) else getattr(cap, tok)


# ===========================================================================================================
def section_compiler(tc: Toolchain):
    print("[1] compiler")
    check("the capture header exists", HEADER_PATH.is_file(), str(HEADER_PATH))
    version = run([tc.cxx, "--version"]).stdout.splitlines()[:1]
    print(f"  info  compiler: {tc.cxx}")
    print(f"  info  version:  {version[0] if version else '?'}")
    macros = run([tc.cxx, "-x", "c++", "-dM", "-E", os.devnull]).stdout
    check("the compiler is GCC (defines __GNUC__, not __clang__) - the constexpr limits the header relies on are GCC's",
          "#define __GNUC__ " in macros and "__clang__" not in macros)


def section_compile(tc: Toolchain):
    print("[2] compile: standalone, gnu++17 / gnu++20, -Wall -Wextra -Werror, every static_assert")
    inc = tc.stage("clean")
    check("the include directory holds ONLY the FB-A profile header, the FB-B0 model header and the capture header",
          sorted(p.name for p in inc.iterdir()) == sorted([FBA_PATH.name, MODEL_PATH.name, HEADER_PATH.name]))
    for std in ("gnu++17", "gnu++20"):
        r = tc.compile(inc, TWICE, std)
        check(f"the header compiles under -std={std} {' '.join(STRICT)} -fsyntax-only (included twice: #pragma once) - every "
              "golden static_assert, golden-case table and layout proof holds", r.returncode == 0, (r.stderr or r.stdout)[-2500:])
    r = tc.compile(inc, '#include "ecco_fallback_capture.h"\nint main() { return 0; }\n', "gnu++17", ["-O2"])
    check("...and optimised (-O2) too", r.returncode == 0, (r.stderr or r.stdout)[-1500:])


def check_value_line(g: Golden, line: str) -> bool:
    m = re.fullmatch(r'static_assert\(\((.*)\) == (-?\d+u?|0x[0-9A-F]+ULL), "FB-B1 value: (.*)"\);', line)
    if not m or m.group(3) != g.label or m.group(1) != g.cxx:
        return False
    lit = m.group(2)
    got = int(lit[:-3], 16) if lit.endswith("ULL") else int(lit.rstrip("u"))
    return got == int(g.py())


def check_text_line(g: Golden, line: str) -> bool:
    m = re.fullmatch(r'static_assert\(text_is\("([^"]*)", (.*)\), "FB-B1 text: (.*)"\);', line)
    return bool(m) and m.group(3) == g.label and m.group(2) == g.cxx and m.group(1) == str(g.py())


def check_str_line(g: Golden, line: str) -> bool:
    m = re.fullmatch(r'static_assert\(str_is\((.*), "([^"]*)"\), "FB-B1 name: (.*)"\);', line)
    return bool(m) and m.group(3) == g.label and m.group(1) == g.cxx and m.group(2) == str(g.py())


def section_parity():
    print("[3] PARITY: every golden value / string / table row equals what the Python mirror produces")
    text = read_header()
    begin = text.index("// ---- GENERATED-GOLDENS-BEGIN")
    end = text.index("// ---- GENERATED-GOLDENS-END ----")
    block = text[text.index("\n", begin) + 1:end]
    lines = block.splitlines()
    block_ok = block == emit_block()
    check(f"the header's generated golden block ({len(lines)} static_asserts) is exactly what this file emits from the Python mirror "
          "(regenerate: python registry/tests/test_fallback_capture_host_compile.py --emit-goldens <file>, then paste between the markers)",
          block_ok)
    check("one static_assert line per golden, labels unique and every one parsed", len(lines) == len(GOLDENS)
          and len({g.label for g in GOLDENS}) == len(GOLDENS))
    bad = []
    for g, line in zip(GOLDENS, lines):
        ok = {"value": check_value_line, "text": check_text_line, "str": check_str_line}[g.kind](g, line)
        if not ok:
            bad.append(g.label)
    check(f"each of the {len(GOLDENS)} header goldens parses and equals the mirror's value exactly (independent regex parse)",
          not bad, str(bad[:5]))
    agree = [g for g in GOLDENS if g.label.startswith("B7 and B8 agree")]
    check(f"the {len(agree)} B7 / B8 agreement goldens are TRUE (the all-5-digit CORRUPT_DOMAIN record is NONE in BOTH views; "
          "the SAVED / NONE verdicts agree on every fixture)", len(agree) == 6 and all(g.py() is True for g in agree))
    kinds = {k: sum(1 for g in GOLDENS if g.kind == k) for k in ("value", "text", "str")}
    print(f"  info  goldens: {kinds}")
    check("the golden set covers every text builder, every classifier and every mask by name",
          all(any(name in g.cxx for g in GOLDENS) for name in (
              "b2_text", "b3_text", "b4_text", "b5_text", "b6_text", "b7_text", "b8_text", "sv_text", "latch_text", "vector_text",
              "warn_text", "read_fail_text", "pass_mismatch_text", "not_saveable_text", "refusal_text", "candidate_ready_text",
              "review_expired_text", "breaker_text", "classify_bus", "classify_fbs", "classify_mtou", "gate_decide", "candidate_id",
              "e1_delta_mask", "ctx_mismatch_mask", "info_mismatch_mask", "out_of_domain_mask", "evaluate_read", "prior_fingerprint",
              "profile_diverged", "witness_diverged", "probe_result", "latch_set", "candidate_expired", "exp_seconds",
              "writes_fingerprint", "lease_domain_nonclear", "breaker_fired", "store_block_241", "store_block_230", "ring_valid",
              "capture_warnings", "hhmm_decodable", "on_5min_grid", "bus_owner_text_with_leases", "stored_trusted", "review_evaluate")))

    # classifier golden-case tables: parse, re-derive from the mirror
    fp_rows = table_rows(text, "FP_CASES")
    dump_rows = table_rows(text, "DUMP_CASES")
    r244_rows = table_rows(text, "R244_CASES")
    check(f"classifier golden-case tables parse: FP {len(fp_rows)} rows x 19, DUMP {len(dump_rows)} x 17, R244 {len(r244_rows)} x 12",
          all(len(r) == 19 for r in fp_rows) and all(len(r) == 17 for r in dump_rows) and all(len(r) == 12 for r in r244_rows)
          and len(fp_rows) >= 50 and len(dump_rows) >= 40 and len(r244_rows) >= 25)

    def fp_gate(r):
        v = [token_value(t) for t in r]
        g = cap.GateInputs(boot_loaded=bool(v[0]))
        g.probe_latch = cap.latch_set(0, cap.DOM_FP, v[15])
        g.fp.free_power_marker_boot_load, g.fp.free_power_recovery_metadata_corrupt = v[1], bool(v[2])
        g.bus.free_power_recovery_force_in_progress, g.bus.free_power_recovery_accept_in_progress = bool(v[3]), bool(v[4])
        g.bus.free_power_operation_in_progress = bool(v[5])
        g.fp.free_power_snapshot_valid, g.fp.free_power_marker_state = bool(v[6]), v[7]
        g.fp.free_power_operator_needed, g.fp.free_power_active_persisted = bool(v[8]), bool(v[9])
        g.fp.free_power_restore_requested, g.fp.expired = bool(v[10]), bool(v[11])
        g.fp.run_start, g.fp.run_restore, g.fp.run_operator = bool(v[12]), bool(v[13]), bool(v[14])
        return g, v[16], v[17], v[18]

    def dump_gate(r):
        v = [token_value(t) for t in r]
        g = cap.GateInputs(boot_loaded=bool(v[0]))
        g.probe_latch = cap.latch_set(0, cap.DOM_DUMP, v[13])
        g.dump.dump_marker_boot_load, g.dump.dump_recovery_metadata_corrupt = v[1], bool(v[2])
        g.dump.dump_containment_state, g.bus.dump_operation_in_progress = v[3], bool(v[4])
        g.dump.dump_snapshot_valid, g.dump.dump_marker_state = bool(v[5]), v[6]
        g.dump.dump_operator_needed, g.dump.dump_active_persisted = bool(v[7]), bool(v[8])
        g.dump.dump_restore_requested, g.dump.expired = bool(v[9]), bool(v[10])
        g.dump.run_start, g.dump.run_restore = bool(v[11]), bool(v[12])
        return g, v[14], v[15], v[16]

    def r244_gate(r):
        v = [token_value(t) for t in r]
        g = cap.GateInputs(boot_loaded=bool(v[0]))
        g.probe_latch = cap.latch_set(0, cap.DOM_R244, v[8])
        g.r244.reg244_marker_boot_load, g.r244.reg244_recovery_metadata_corrupt = v[1], bool(v[2])
        g.bus.reg244_apply_in_progress, g.r244.reg244_snapshot_valid = bool(v[3]), bool(v[4])
        g.r244.reg244_marker_state, g.r244.run_apply, g.r244.run_restore = v[5], bool(v[6]), bool(v[7])
        return g, v[9], v[10], v[11]

    for name, rows, build, fn in (("FP", fp_rows, fp_gate, cap.classify_fp), ("DUMP", dump_rows, dump_gate, cap.classify_dump),
                                  ("R244", r244_rows, r244_gate, cap.classify_r244)):
        bad = []
        for r in rows:
            g, probe, kind, basis = build(r)
            c = fn(g, probe)
            if (c.kind, c.basis) != (kind, basis):
                bad.append((r, (c.kind, c.basis)))
        check(f"the {name} golden-case table (every row's expected kind / basis, written by hand from S1 4.4) equals the mirror's classification",
              not bad, str(bad[:2]))

    # enum numbering and constants parity
    enum_bad, n_enum = [], 0
    for ename, body in re.findall(r"enum (\w+) : uint8_t \{(.*?)\};", text, re.S):
        for name, value in re.findall(r"(\w+) = (\d+)", re.sub(r"//[^\n]*", "", body)):
            n_enum += 1
            if not hasattr(cap, name) or getattr(cap, name) != int(value):
                enum_bad.append((ename, name, value))
    check(f"every enumerator of the header's {n_enum} (explicit numbers) equals the mirror's constant of the same name",
          n_enum >= 100 and not enum_bad, str(enum_bad[:4]))
    const_bad = []
    for name, value in re.findall(r"^constexpr (?:uint8_t|uint16_t|uint32_t|size_t|bool) (\w+) = (\w+?)u?;", text, re.M):
        if hasattr(cap, name) and name.isupper():
            want = {"true": True, "false": False}.get(value, int(value, 0) if re.fullmatch(r"(0x)?[0-9A-Fa-f]+", value) else None)
            if want is not None and getattr(cap, name) != want:
                const_bad.append((name, value))
    check("every scalar constant the header defines equals the mirror's", not const_bad, str(const_bad))
    m = re.search(r"constexpr std::array<uint16_t, REG_COUNT> REGS = \{([^}]*)\};", text)
    check("REGS (the canonical 31-register order) equals the mirror's", bool(m) and tuple(int(x) for x in m.group(1).split(",")) == cap.REGS)
    check("the candidate-id domain string is the 34-byte S1 9.3 literal in both languages",
          'constexpr char CANDIDATE_DOMAIN[] = "ECCO-FALLBACK-PROFILE-CANDIDATE-v1";' in text
          and cap.CANDIDATE_DOMAIN == b"ECCO-FALLBACK-PROFILE-CANDIDATE-v1" and len(cap.CANDIDATE_DOMAIN) == 34)


# ===========================================================================================================
# Negative controls
# ===========================================================================================================
def mutants() -> list[tuple[str, str, str, str]]:
    """(label, old, new, message that must appear in the compiler's output). Each `old` occurs exactly once."""
    return [
        ("candidate id golden flipped", "static_assert((candidate_id(1u, 1u, 1, 0u, 0x0ULL, GOLDEN_WORDS)) == 0x1D63D8CBC6CB4D55ULL",
         "static_assert((candidate_id(1u, 1u, 1, 0u, 0x0ULL, GOLDEN_WORDS)) == 0x1D63D8CBC6CB4D56ULL", "FB-B1 value: candidate_id (constants reading"),
        ("candidate id hashes the whole 96 bytes (binding included)",
         "  for (size_t i = 0; i < ecco_fallback::PROFILE_BOUND_BYTES; i++)\n    h = ecco_fallback::fnv1a64_step(h, b[i]);\n  return h;\n}\n\n// THE locked reading",
         "  for (size_t i = 0; i < ecco_fallback::PROFILE_SIZE; i++)\n    h = ecco_fallback::fnv1a64_step(h, b[i]);\n  return h;\n}\n\n// THE locked reading",
         "FB-B1 value: candidate_id"),
        ("candidate id q carries zero magic (the rejected reading adopted)",
         "  return candidate_id_over(profile_from_words(words), salt, seq, prior_class, prior_generation, prior_binding);",
         "  return candidate_id_alt_zero_header_reading(salt, seq, prior_class, prior_generation, prior_binding, words);",
         "FB-B1 value: candidate_id (constants reading"),
        # FB-B2 (D8): the READY wording is no longer review-only (a Save exists now); mutants 04 / 05 are re-anchored to the new text
        ("a golden text string edited", 'text_is("CANDIDATE READY - both read passes agree on all 31 registers; check the values, then arm and save within 120 s", candidate_ready_text())',
         'text_is("CANDIDATE READY - both read passes agree on all 31 registers; check the values, then arm and save within 121 s", candidate_ready_text())',
         "FB-B1 text: candidate_ready_text"),
        ("the candidate text edited in the builder", 'then arm and save within "\n         "120 s");', 'then arm and save within "\n         "125 s");',
         "FB-B1 text: candidate_ready_text"),
        # FB-B2 (D8): the new SAVING capture state has a name
        ("the SAVING capture state loses its name", '         : state == CAPTURE_SAVING                 ? "SAVING"\n', '',
         "FB-B1 name: capture_state_name 4"),
        ("FP golden-case row flipped", "{1, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 2, OBL_CLEAR_PROVEN, BASIS_MARKER_CLEAR},",
         "{1, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 2, OBL_CLEAR_PROVEN, BASIS_ABSENT},", "FB-B1 classifier golden cases: FP"),
        ("DUMP golden-case row flipped", "{1, 0, 1, 3, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, UNK_METADATA_CORRUPT, BASIS_BOOT_LOCKOUT},",
         "{1, 0, 1, 3, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, UNK_METADATA_CORRUPT, BASIS_RUNTIME_PROBE},", "FB-B1 classifier golden cases: DUMP"),
        ("R244 golden-case row flipped", "{1, 0, 0, 0, 1, 1, 0, 0, 0, 0, OBL_OPERATOR_NEEDED, BASIS_NONE},", "{1, 0, 0, 0, 1, 1, 0, 0, 0, 0, OBL_RESTORE_REQUIRED, BASIS_NONE},",
         "FB-B1 classifier golden cases: R244"),
        ("FP row 12: the expired term is dropped", "d.free_power_active_persisted && !d.free_power_restore_requested &&\n      !d.expired)",
         "d.free_power_active_persisted && !d.free_power_restore_requested)", "FB-B1 classifier golden cases: FP"),
        ("FP rows 6 and 7 swapped (a running start outranks a restore)",
         "  if (d.run_restore)\n    return {OBL_ENDING, BASIS_RESTORE_RUNNING};\n  if (d.run_start && !sv)\n    return {OBL_STARTING, BASIS_PRE_COMMIT};\n  if (d.run_start && sv)\n    return {OBL_STARTING, BASIS_COMMITTED};\n  if (b.free_power_operation_in_progress)",
         "  if (d.run_start && !sv)\n    return {OBL_STARTING, BASIS_PRE_COMMIT};\n  if (d.run_start && sv)\n    return {OBL_STARTING, BASIS_COMMITTED};\n  if (d.run_restore)\n    return {OBL_ENDING, BASIS_RESTORE_RUNNING};\n  if (b.free_power_operation_in_progress)",
         "FB-B1 classifier golden cases: FP"),
        ("the probe latch row for UNREADABLE is dropped",
         "  if (latch_code == LATCH_UNREADABLE)\n    return {UNK_DURABLE_UNREADABLE, BASIS_RUNTIME_PROBE};\n  if (latch_code == LATCH_MALFORMED)",
         "  if (latch_code == LATCH_MALFORMED)", "FB-B1 classifier golden cases"),
        ("boot truth uses the corrupt flag alone (READ_ERROR no longer UNKNOWN)",
         "  if (corrupt && load == BOOT_LOAD_READ_ERROR)\n    return {UNK_DURABLE_UNREADABLE, BASIS_BOOT_READ_ERROR};\n", "", "FB-B1 classifier golden cases"),
        ("Dump restore_requested becomes a clear-term", "  if (d.dump_active_persisted || d.dump_operator_needed || ms != MARKER_STATE_CLEAR)",
         "  if (d.dump_active_persisted || d.dump_restore_requested || d.dump_operator_needed || ms != MARKER_STATE_CLEAR)",
         "FB-B1 classifier golden cases: DUMP"),
        ("FP stale operator_needed becomes an obligation", "  if (d.free_power_active_persisted || d.free_power_restore_requested || ms != MARKER_STATE_CLEAR)",
         "  if (d.free_power_active_persisted || d.free_power_restore_requested || d.free_power_operator_needed || ms != MARKER_STATE_CLEAR)",
         "FB-B1 classifier golden cases: FP"),
        ("L2: the 500 W boundary becomes inclusive", "if (pw < ecco_fallback::V1_TOU_POWER_MIN_W)", "if (pw <= ecco_fallback::V1_TOU_POWER_MIN_W)", "FB-B1 text: sv_text"),
        ("L2: the site ceiling is ignored", "|| (uint32_t) pw > ceiling_w)", ")", "FB-B1 text: sv_text"),
        ("L2: HHMM 2400 decodes", "constexpr bool hhmm_decodable(uint16_t raw) { return raw / 100 <= 23 && raw % 100 <= 59; }",
         "constexpr bool hhmm_decodable(uint16_t raw) { return raw / 100 <= 24 && raw % 100 <= 59; }", "FB-B1 value: hhmm_decodable"),
        ("L2: the 5-minute grid refuses (policy leak)", "    if (!hhmm_decodable(w[21 + n]))\n      refusal_add(r, RF_HHMM, n);",
         "    if (!hhmm_decodable(w[21 + n]) || !on_5min_grid(w[21 + n]))\n      refusal_add(r, RF_HHMM, n);", "FB-B1 text: sv_text"),
        ("L2: source words are masked instead of refused", "if (!ecco_fallback::slot_source_domain_valid(src)) {",
         "if (!ecco_fallback::slot_source_domain_valid((uint16_t) (src & 3u))) {", "FB-B1 text: sv_text"),
        ("L2: 243 may be 2", "  if (w[20] > 1)\n    refusal_add(r, RF_243X, 0);", "  if (w[20] > 2)\n    refusal_add(r, RF_243X, 0);", "FB-B1 text: sv_text"),
        ("ring: the gap sum is not checked", "  return sum == 1440;\n}", "  return true;\n}", "FB-B1 value: ring_valid"),
        ("warnings: W2 threshold 3001", "all_equal && w[1] <= DUMP_CONTROLLER_MAX_W", "all_equal && w[1] <= 3001", "FB-B1 value: capture_warnings"),
        ("masks: dx masks the source words (274-279 compared on bits 0-1)",
         "  for (size_t k = 0; k < 19; k++) {\n    if (a[k] != b[k])\n      m |= (1u << k);",
         "  for (size_t k = 0; k < 19; k++) {\n    if ((a[k] & (k >= 13 ? 3u : 0xFFFFu)) != (b[k] & (k >= 13 ? 3u : 0xFFFFu)))\n      m |= (1u << k);",
         "FB-B1 value: e1_delta_mask"),
        ("masks: info bit3 compares bit0 too", "if (((a[19] ^ b[19]) & 0xFFFEu) != 0)", "if (((a[19] ^ b[19]) & 0xFFFFu) != 0)", "FB-B1 value: info_mismatch_mask"),
        ("expiry: > instead of >=", "return (uint32_t) (now_ms - born_ms) >= CANDIDATE_TTL_MS;", "return (uint32_t) (now_ms - born_ms) > CANDIDATE_TTL_MS;",
         "FB-B1 value: candidate_expired"),
        ("expiry: not wrap safe", "return (uint32_t) (now_ms - born_ms) >= CANDIDATE_TTL_MS;", "return now_ms >= born_ms + CANDIDATE_TTL_MS;",
         "FB-B1 value: candidate_expired"),
        ("exp= rounds up", "return age >= CANDIDATE_TTL_MS ? 0u : (CANDIDATE_TTL_MS - age) / 1000u;",
         "return age >= CANDIDATE_TTL_MS ? 0u : (CANDIDATE_TTL_MS - age + 999u) / 1000u;", "FB-B1 value: exp_seconds"),
        ("writes fingerprint ORs", "return (uint32_t) (a + b + c + d + e);", "return (uint32_t) (a | b | c | d | e);", "FB-B1 value: writes_fingerprint"),
        ("divergence ignores a changed load code", "  return last_load != new_load || !bytes_equal;\n}", "  return !bytes_equal;\n}", "FB-B1 value: diverged"),
        ("divergence applies without a baseline", "  out.p_diverged = in.baseline_valid &&\n                   profile_diverged(", "  out.p_diverged = profile_diverged(",
         "FB-B1 value: evaluate_read"),
        ("the seen high-water is not updated",
         "  out.seen_hw_gen = ecco_fbdurable::next_seen_hw_gen(in.seen_hw_gen, out.p_fba_class, in.p.generation, out.w_class,\n                                                     in.w.hw_generation);",
         "  out.seen_hw_gen = in.seen_hw_gen;", "FB-B1 value: evaluate_read"),
        ("the class is not re-composed with the divergence bits",
         "ecco_fbdurable::compose_profile_class(in.p_load, in.p, in.w_load, in.w, latch.read_anomaly);",
         "ecco_fbdurable::compose_profile_class(in.p_load, in.p, in.w_load, in.w, in.read_anomaly);", "FB-B1 value: evaluate_read"),
        ("the latch is overwritten instead of set-only", "if (domain > 3 || code == 0 || latch_get(latch, domain) != 0)\n    return latch;",
         "if (domain > 3 || code == 0)\n    return latch;", "FB-B1 value: latch"),
        ("the gate asks for every probe even when a RAM leg refuses (not lazy)",
         "  r.probe_fp = r.fp.kind == UNK_NOT_PROBED;\n  r.probe_dump = r.dump.kind == UNK_NOT_PROBED;\n  r.probe_r244 = r.r244.kind == UNK_NOT_PROBED;\n",
         "  r.probe_fp = true;\n  r.probe_dump = true;\n  r.probe_r244 = true;\n", "FB-B1 value: gate_decide"),
        ("the gate ignores the write arms", "  if (arms_on(g)) {", "  if (false) {", "FB-B1 value: gate_decide"),
        ("the gate skips the in-flight check",
         "  if (g.bus.fallback_profile_op_in_progress || g.bus.fallback_profile_capture_dispatch_running) {\n    r.code = GATE_REFUSE_IN_FLIGHT;",
         "  if (false) {\n    r.code = GATE_REFUSE_IN_FLIGHT;", "FB-B1 value: gate_decide"),
        ("lock stuck uses a 30 s threshold", "lock_age_ms(b) >= LOCK_STUCK_MS;", "lock_age_ms(b) >= 30000u;", "FB-B1 value: lock_stuck"),
        ("the bus term list drops verification_pending", "b.correction_in_progress || b.verification_pending ||\n         b.verification_read_active",
         "b.correction_in_progress ||\n         b.verification_read_active", "FB-B1 name: classify_bus"),
        ("the breaker fires at 30 s exactly", "(uint32_t) (now_ms - started_ms) > BREAKER_MS;", "(uint32_t) (now_ms - started_ms) >= BREAKER_MS;",
         "FB-B1 value: breaker_fired"),
        ("the saved view ignores the 200-character limit (B7 publishes a truncated text)", "  put_b7_saved(probe, p);\n  return !probe.overflow;",
         "  put_b7_saved(probe, p);\n  return true;", "FB-B1 text: b7_text"),
        ("B8 decides SAVED with its own predicate (B7 NONE next to B8 SAVED, the old asymmetry)",
         '  TextBuf t;\n  if (saved_view(p_load, p, cls)) {\n    put(t, "v=SAVED;");',
         '  TextBuf t;\n  if (ecco_fbdurable::fba_authentic(ecco_fallback::classify_profile(p_load, p)) && cls != ecco_fbdurable::EPC_UNREADABLE) {\n'
         '    put(t, "v=SAVED;");', "FB-B1 text: b8_text"),
        ("B3: an over-long obl is cut instead of replaced by -", "  if (b3_value_fits(obl, B3_OBL_MAX))\n    put(t, obl);",
         "  if (obl != nullptr && obl[0] != '\\0')\n    put(t, obl);", "FB-B1 text: b3_text"),
        ("B3: an over-long sv is cut instead of replaced by -", "  if (have_cand && b3_value_fits(sv, B3_SV_MAX))",
         "  if (have_cand && sv != nullptr && sv[0] != '\\0')", "FB-B1 text: b3_text"),
        ("B3: the obl bound is 35", "constexpr size_t B3_OBL_MAX = 36;", "constexpr size_t B3_OBL_MAX = 35;", "FB-B1 value: constant B3_OBL_MAX"),
        ("b3_value_fits accepts max + 1 characters", "  for (size_t i = 1; i <= max_chars; i++) {", "  for (size_t i = 1; i <= max_chars + 1; i++) {",
         "FB-B1 value: b3_value_fits"),
        ("bus owner: Dump to Grid outranks Register 244 test", '         : b.reg244_apply_in_progress    ? "Register 244 test"\n         : b.dump_operation_in_progress  ? "Dump to Grid"',
         '         : b.dump_operation_in_progress  ? "Dump to Grid"\n         : b.reg244_apply_in_progress    ? "Register 244 test"', "FB-B1 name: bus_owner_text"),
        ("bus owner: clock verification outranks clock correction",
         '         : b.correction_in_progress      ? "clock correction"\n         : (b.verification_pending || b.verification_read_active) ? "clock verification"',
         '         : (b.verification_pending || b.verification_read_active) ? "clock verification"\n         : b.correction_in_progress      ? "clock correction"',
         "FB-B1 name: bus_owner_text"),
        ("the prior fingerprint truncates a WRONG_SIZE stored length to 16 bits", "    return {0u, (uint64_t) stored_len};",
         "    return {0u, (uint64_t) (uint16_t) stored_len};", "FB-B1 value: prior_fingerprint"),
        ("the not-saveable text only sees a read anomaly above 1", "  } else if (read_anomaly != 0) {\n    extra = (uint16_t) (RF_ANOMALY << 8);",
         "  } else if (read_anomaly > 1) {\n    extra = (uint16_t) (RF_ANOMALY << 8);", "FB-B1 text: not_saveable_text"),
        ("a text-only refusal kind renders its slot digits in sv=", "    default:\n      return;\n  }\n  put_u(t, refusal_slot(item));",
         "    default:\n      break;\n  }\n  put_u(t, refusal_slot(item));", "FB-B1 text: sv_text"),
        ("B2 shows g for a non-authentic record", '  put(t, "g=");\n  if (authentic)', '  put(t, "g=");\n  if (true)', "FB-B1 text: b2_text"),
        ("B3 prior is shown without a candidate", '  put(t, ";prior=");\n  if (have_cand)', '  put(t, ";prior=");\n  if (true)', "FB-B1 text: b3_text"),
        ("the text buffer cap is 199", "constexpr size_t TEXT_CAP = 200;", "constexpr size_t TEXT_CAP = 199;", "FB-B1 value: constant TEXT_CAP"),
        ("store_block_241 also overwrites word 28", "    if (k == 19 || k == 28)\n      continue;", "    if (k == 19)\n      continue;", "FB-B1 value: store_block_241"),
        ("store_block_241 accepts any size", "  if (values.size() != 53)\n    return false;", "  if (values.size() < 3)\n    return false;",
         "FB-B1 value: store_block_241"),
        ("a read-failure text names the wrong block",
         'constexpr const char *block_name(uint8_t step) {\n  return (step == 1 || step == 3) ? "230/3"',
         'constexpr const char *block_name(uint8_t step) {\n  return (step == 1 || step == 2) ? "230/3"', "FB-B1 text: read_fail_text"),
        ("the epc names lose PROFILE_LOST", '    case ecco_fbdurable::EPC_PROFILE_LOST:\n      return "PROFILE_LOST";\n', "", "FB-B1 name: epc_name"),
        ("the not-saveable text drops the +N counter", '    put(t, "; +");\n    put_u(t, total - 2);', '    put(t, "; +");\n    put_u(t, 0u);',
         "FB-B1 text: not_saveable_text"),
        ("review is eligible with a read anomaly", "  return r.count == 0 && ecco_fbdurable::save_class_permitted(cls) && read_anomaly == 0;",
         "  return r.count == 0 && ecco_fbdurable::save_class_permitted(cls);", "FB-B1 value: review_eligible"),
        ("the prior fingerprint of a WRONG_SIZE record uses its generation", "    return {0u, (uint64_t) stored_len};", "    return {p.generation, p.binding};",
         "FB-B1 value: prior_fingerprint"),
        ("REGS: 245 and 247 swapped", "251, 252, 253, 254, 255, 230, 245, 247};", "251, 252, 253, 254, 255, 230, 247, 245};", "FB-B1 value: reg_of"),
        # FW0: the review masks only against a TRUSTED stored profile (authentic AND class != UNREADABLE)
        ("FW0: has_stored follows the FB-A class alone (dx / dc / di against an untrusted profile)", "  v.has_stored = stored_trusted(in.p_load, in.p, in.cls);",
         "  v.has_stored = ecco_fbdurable::fba_authentic(ecco_fallback::classify_profile(in.p_load, in.p));", "FB-B1 value: review_evaluate has_stored"),
        ("FW0: the trusted predicate drops the effective-class clause (has_stored and the saved views)",
         "  return ecco_fbdurable::fba_authentic(ecco_fallback::classify_profile(p_load, p)) &&\n         cls != ecco_fbdurable::EPC_UNREADABLE;",
         "  return ecco_fbdurable::fba_authentic(ecco_fallback::classify_profile(p_load, p)) &&\n         cls != 99;", "FB-B1 value: review_evaluate has_stored"),
        ("FW0: the saved views stop using the shared predicate (B7 / B8 SAVED for an UNREADABLE class)", "  if (!stored_trusted(p_load, p, cls))\n    return false;",
         "  if (!ecco_fbdurable::fba_authentic(ecco_fallback::classify_profile(p_load, p)))\n    return false;", "FB-B1 text: b7_text"),
        ("FW0: the mask is shown for a CORRUPT record too (trusted = loaded OK)", "  return ecco_fbdurable::fba_authentic(ecco_fallback::classify_profile(p_load, p)) &&\n         cls != ecco_fbdurable::EPC_UNREADABLE;",
         "  return p_load == ecco_fallback::LOAD_OK && cls != ecco_fbdurable::EPC_UNREADABLE;", "FB-B1 value: review_evaluate has_stored"),
        # FW1: the BUS refusal names an ACTIVE lease when the generic mutex flag is the only owner flag
        ("FW1: the gate's BUS refusal names the plain owner again (an active lease is 'manual write')",
         "                            bus_owner_text_with_leases(g.bus, r.fp, r.dump), lock_age_ms(g.bus) / 1000u);",
         "                            bus_owner_text(g.bus), lock_age_ms(g.bus) / 1000u);", "FB-B1 text: gate_decide [V4 manual write holds the bus while a Dump lease is ACTIVE"),
        ("FW1: a lease is named although another owner flag is set (the guard is dropped)",
         "  const bool mutex_only =\n      b.manual_write_in_progress &&\n      !(b.correction_in_progress || b.verification_pending || b.verification_read_active ||\n"
         "        b.free_power_operation_in_progress || b.free_power_recovery_force_in_progress ||\n        b.free_power_recovery_accept_in_progress || b.reg244_apply_in_progress || b.dump_operation_in_progress ||\n"
         "        b.fallback_profile_op_in_progress || b.fallback_profile_capture_dispatch_running);",
         "  const bool mutex_only = b.manual_write_in_progress;", "FB-B1 name: bus_owner_text_with_leases"),
        ("FW1: the guard forgets the clock-correction flag (a clock owner is outranked by a lease)", "      !(b.correction_in_progress || b.verification_pending || b.verification_read_active ||\n",
         "      !(b.verification_pending || b.verification_read_active ||\n", "FB-B1 name: bus_owner_text_with_leases"),
        ("FW1: the lease is named without the mutex flag", "  const bool mutex_only =\n      b.manual_write_in_progress &&\n", "  const bool mutex_only =\n      true &&\n",
         "FB-B1 name: bus_owner_text_with_leases"),
        ("FW1: Dump to Grid is named before Free Power",
         '  if (mutex_only && fp_slot.kind == OBL_ACTIVE)\n    return "Free Power";\n  if (mutex_only && dump_slot.kind == OBL_ACTIVE)\n    return "Dump to Grid";',
         '  if (mutex_only && dump_slot.kind == OBL_ACTIVE)\n    return "Dump to Grid";\n  if (mutex_only && fp_slot.kind == OBL_ACTIVE)\n    return "Free Power";',
         "FB-B1 name: bus_owner_text_with_leases"),
        ("FW1: any slot that is not RAM-clear is named (not only OBL_ACTIVE)", "  if (mutex_only && fp_slot.kind == OBL_ACTIVE)", "  if (mutex_only && fp_slot.kind != UNK_NOT_PROBED)",
         "FB-B1 name: bus_owner_text_with_leases"),
    ]


def section_negative(tc: Toolchain):
    print("[5] negative controls: the static_asserts are really evaluated (every mutant must be a REAL compile rejection)")
    text = read_header()
    inc = tc.stage("negative")
    r = tc.compile(inc, '#include "ecco_fallback_capture.h"\n'
                   'static_assert(ecco_fbcap::candidate_id(1u, 1u, 1, 0u, 0ULL, ecco_fbcap::GOLDEN_WORDS) == 0, "negative control: a false golden");\n')
    check("a deliberately WRONG golden (candidate id == 0) fails to compile with its message",
          r.returncode != 0 and "static assertion failed" in r.stderr and "negative control: a false golden" in r.stderr, r.stderr[-500:])
    r = tc.compile(inc, '#include "ecco_fallback_capture.h"\nint main() { return ecco_fbcap::epc_name("x") == nullptr; }\n')
    check("a TYPE error (a string passed as a class number) is rejected as an ordinary compile error, not a static_assert",
          r.returncode != 0 and "error:" in r.stderr and "static assertion" not in r.stderr, r.stderr[-400:])
    r = tc.compile(inc, '#include "ecco_fallback_capture.h"\nint main() { ecco_fbcap::GateInputs g; g.no_such_input = true; return 0; }\n')
    check("a misspelled POD field is rejected", r.returncode != 0 and "no_such_input" in r.stderr)
    r = tc.compile(inc, '#include "ecco_fallback_capture.h"\nstatic_assert(!ecco_fbcap::text_is("OK", ecco_fbcap::sv_text(ecco_fbcap::Refusals{})), "negative control: sv OK");\n')
    check("a VIOLATED static_assert in a client TU fails with its own message",
          r.returncode != 0 and "negative control: sv OK" in r.stderr)
    r = tc.compile(inc, '#include "ecco_fallback_capture.h"\nstatic_assert(ecco_fbcap::text_is("OK", ecco_fbcap::sv_text(ecco_fbcap::Refusals{})), "ok");\nint main() { return 0; }\n')
    check("...while the true form of the same assertion compiles (the control is specific)", r.returncode == 0, r.stderr[-300:])

    muts = mutants()
    problems = []
    for label, old, new, msg in muts:
        if text.count(old) != 1:
            problems.append(f"{label}: pattern found {text.count(old)}x")
    check(f"all {len(muts)} mutation patterns occur exactly once in the header", not problems, "; ".join(problems[:4]))

    def one(item):
        label, old, new, msg = item
        if text.count(old) != 1:
            return label, None, msg
        mutated = text.replace(old, new, 1)
        d = tc.stage("mut_" + re.sub(r"\W+", "_", label)[:50], mutated)
        r = tc.compile(d, '#include "ecco_fallback_capture.h"\nint main() { return 0; }\n')
        return label, r, msg

    with ThreadPoolExecutor(max_workers=max(1, min(8, os.cpu_count() or 1))) as pool:
        results = list(pool.map(one, muts))
    for label, r, msg in results:
        ok = r is not None and r.returncode != 0 and ("static assertion failed" in r.stderr or "error:" in r.stderr) and msg in r.stderr
        check(f"mutant [{label}] is rejected by a static_assert naming '{msg}'", ok,
              "compiled" if r is not None and r.returncode == 0 else (r.stderr[-500:] if r is not None else "pattern missing"))




# ===========================================================================================================
# Randomized parity: the SAME seeded generator in C++ (constexpr, evaluated by the compiler) and in Python
# ===========================================================================================================
RANDOM_CASES = 120
RANDOM_COMPONENTS = ("L2 and masks", "candidate id", "candidate texts", "profile texts", "evaluate_read", "review_evaluate",
                     "classifiers", "gate_decide", "gate texts and names", "timing")

RANDOM_TU_CXX = r'''#include "ecco_fallback_capture.h"
using namespace ecco_fbcap;
namespace rnd {
struct Rng {
  uint32_t s;
  constexpr uint32_t next() { s = s * 1664525u + 1013904223u; return s; }
  constexpr uint32_t below(uint32_t n) { return (next() >> 8) % n; }
};
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
constexpr CaptureWords gen_clean_words(Rng &r) {
  constexpr uint16_t PW[4] = {500, 1000, 3000, 8000};
  constexpr uint16_t SOCP[3] = {0, 50, 100};
  constexpr uint16_t SCP[3] = {0x11, 0x10, 0x13};
  constexpr uint16_t TIM[6] = {0, 530, 1000, 1600, 2100, 2330};
  CaptureWords w = GOLDEN_WORDS;
  for (size_t n = 0; n < 6; n++) { const uint32_t c = r.below(100); if (c < 30) { const uint32_t i = r.below(4); w[1 + n] = PW[i]; } }
  for (size_t n = 0; n < 6; n++) { const uint32_t c = r.below(100); if (c < 30) { const uint32_t i = r.below(3); w[7 + n] = SOCP[i]; } }
  for (size_t n = 0; n < 6; n++) { const uint32_t c = r.below(100); if (c < 30) { const uint32_t i = r.below(2); w[13 + n] = (uint16_t) i; } }
  { const uint32_t c = r.below(100); if (c < 30) { const uint32_t i = r.below(3); w[19] = SCP[i]; } }
  { const uint32_t c = r.below(100); if (c < 20) { const uint32_t i = r.below(4); w[21] = (uint16_t) i; } }
  for (size_t n = 0; n < 6; n++) { const uint32_t c = r.below(100); if (c < 25) { const uint32_t i = r.below(6); w[22 + n] = TIM[i]; } }
  { const uint32_t c = r.below(100); if (c < 20) { const uint32_t i = r.below(300); w[28] = (uint16_t) i; } }
  return w;
}
constexpr CaptureWords gen_mixed_words(Rng &r, uint32_t pchange) {
  const uint32_t m = r.below(100);
  if (m < 50)
    return gen_words(r, pchange);
  return gen_clean_words(r);
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
  if (r.below(100) < 8) {
    p.generation = 4294967295u; p.captured_epoch = 4294967295u; p.reg244 = 65535;
    for (size_t i = 0; i < 6; i++) { p.reg256_261[i] = 65535; p.reg268_273[i] = 65535; p.reg274_279[i] = 65535; p.reg250_255[i] = 65535; }
    p.reg232 = 65535; p.reg243 = 65535; p.reg248 = 65535; p.reg230 = 65535; p.reg245 = 65535; p.reg247 = 65535;
  }
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
constexpr GateInputs gen_gate_clean(Rng &r) {
  GateInputs g{};
  g.boot_loaded = true;
  { const uint32_t i = r.below(2); g.fbs_slot = i == 0 ? ecco_fbdurable::FBS_CLEAR_ABSENT : ecco_fbdurable::FBS_CLEAR_VALID; }
  { const uint32_t a = r.below(2); g.fp.free_power_marker_boot_load = (uint8_t) a; }
  { const uint32_t a = r.below(2); g.dump.dump_marker_boot_load = (uint8_t) a; }
  { const uint32_t a = r.below(2); g.r244.reg244_marker_boot_load = (uint8_t) a; }
  const uint32_t f = r.below(20);
  if (f == 0) g.free_power_write_enable = true;
  else if (f == 1) g.bus.manual_write_in_progress = true;
  else if (f == 2) g.fbs_slot = ecco_fbdurable::FBS_OBLIGATION;
  else if (f == 3) g.fp.free_power_marker_state = 1;
  else if (f == 4) g.dump.dump_marker_state = 1;
  else if (f == 5) g.r244.reg244_marker_state = 1;
  else if (f == 6) g.probe_latch = 0x0010;
  else if (f == 7) g.fp.run_start = true;
  else if (f == 8) g.bus.fallback_profile_op_in_progress = true;
  else if (f == 9) g.boot_loaded = false;
  return g;
}
constexpr GateInputs gen_gate(Rng &r) {
  const uint32_t m = r.below(100);
  if (m < 45)
    return gen_gate_clean(r);
  constexpr uint8_t BLP[8] = {0, 1, 1, 1, 1, 2, 3, 255};
  constexpr uint8_t MSP[8] = {0, 0, 0, 0, 0, 0, 1, 2};
  constexpr uint8_t NIB[18] = {0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 2, 3, 4, 5, 15};
  constexpr uint8_t FBSP[7] = {1, 1, 1, 2, 0, 3, 4};
  GateInputs g{};
  g.boot_loaded = r.below(100) < 95;
  { const uint32_t i = r.below(7); g.fbs_slot = FBSP[i]; }
  { const uint32_t a = r.below(18); const uint32_t b = r.below(18); const uint32_t c = r.below(18);
    g.probe_latch = latch_set(latch_set(latch_set(0, DOM_FP, NIB[a]), DOM_DUMP, NIB[b]), DOM_R244, NIB[c]); }
  g.free_power_write_enable = r.below(100) < 3;
  g.dump_write_enable = r.below(100) < 3;
  g.manual_config_write_enable = r.below(100) < 3;
  g.bus.manual_write_in_progress = r.below(100) < 4;
  g.bus.correction_in_progress = r.below(100) < 4;
  g.bus.verification_pending = r.below(100) < 4;
  g.bus.verification_read_active = r.below(100) < 4;
  g.bus.free_power_operation_in_progress = r.below(100) < 4;
  g.bus.free_power_recovery_force_in_progress = r.below(100) < 4;
  g.bus.free_power_recovery_accept_in_progress = r.below(100) < 4;
  g.bus.reg244_apply_in_progress = r.below(100) < 4;
  g.bus.dump_operation_in_progress = r.below(100) < 4;
  g.bus.fallback_profile_op_in_progress = r.below(100) < 4;
  g.bus.fallback_profile_capture_dispatch_running = r.below(100) < 4;
  g.bus.diag_write_lock_held = r.below(100) < 30;
  g.bus.diag_write_lock_since_ms = r.next();
  g.bus.now_ms = r.next();
  { const uint32_t i = r.below(8); g.fp.free_power_marker_boot_load = BLP[i]; }
  g.fp.free_power_recovery_metadata_corrupt = r.below(100) < 4;
  g.fp.free_power_snapshot_valid = r.below(100) < 8;
  { const uint32_t i = r.below(8); g.fp.free_power_marker_state = MSP[i]; }
  g.fp.free_power_operator_needed = r.below(100) < 25;
  g.fp.free_power_active_persisted = r.below(100) < 5;
  g.fp.free_power_restore_requested = r.below(100) < 5;
  g.fp.expired = r.below(100) < 10;
  g.fp.run_start = r.below(100) < 3;
  g.fp.run_restore = r.below(100) < 3;
  g.fp.run_operator = r.below(100) < 3;
  { const uint32_t i = r.below(8); g.dump.dump_marker_boot_load = BLP[i]; }
  g.dump.dump_recovery_metadata_corrupt = r.below(100) < 4;
  { const bool c = r.below(100) < 8; const uint32_t which = r.below(2); g.dump.dump_containment_state = c ? (which == 0 ? 3 : 8) : 0; }
  g.dump.dump_snapshot_valid = r.below(100) < 8;
  { const uint32_t i = r.below(8); g.dump.dump_marker_state = MSP[i]; }
  g.dump.dump_operator_needed = r.below(100) < 25;
  g.dump.dump_active_persisted = r.below(100) < 5;
  g.dump.dump_restore_requested = r.below(100) < 10;
  g.dump.expired = r.below(100) < 10;
  g.dump.run_start = r.below(100) < 3;
  g.dump.run_restore = r.below(100) < 3;
  { const uint32_t i = r.below(8); g.r244.reg244_marker_boot_load = BLP[i]; }
  g.r244.reg244_recovery_metadata_corrupt = r.below(100) < 4;
  g.r244.reg244_snapshot_valid = r.below(100) < 8;
  { const uint32_t i = r.below(8); g.r244.reg244_marker_state = MSP[i]; }
  g.r244.run_apply = r.below(100) < 3;
  g.r244.run_restore = r.below(100) < 3;
  return g;
}
constexpr ProbeResults gen_probes(Rng &r) {
  constexpr uint8_t PRB[9] = {0, 0, 1, 2, 2, 3, 4, 5, 6};
  ProbeResults p{};
  { const uint32_t i = r.below(9); p.fp = PRB[i]; }
  { const uint32_t i = r.below(9); p.dump = PRB[i]; }
  { const uint32_t i = r.below(9); p.r244 = PRB[i]; }
  return p;
}
constexpr void fold_slot(Dg &d, const SlotClass &c) { d.u(c.kind); d.u(c.basis); d.s(obl_code(c.kind, c.basis)); }

constexpr uint64_t comp_digest(uint32_t seed, uint32_t comp) {
  Rng r{seed * 2654435761u + comp * 40503u + 12345u};
  Dg d;
  if (comp == 0) {
    const CaptureWords w = gen_mixed_words(r, 45);
    constexpr uint32_t CEIL[4] = {8000u, 5000u, 3000u, 10000u};
    const uint32_t ci = r.below(4);
    const uint32_t ceiling = CEIL[ci];
    const CaptureWords w2 = gen_words(r, 30);
    const Refusals ref = capture_refusals(w, ceiling);
    d.u(ref.count);
    for (uint8_t i = 0; i < ref.count; i++) d.u(ref.item[i]);
    d.t(sv_text(ref));
    d.u(capture_warnings(w));
    d.u(ring_valid(w) ? 1 : 0);
    d.u(e1_delta_mask(w, w2)); d.u(ctx_mismatch_mask(w, w2)); d.u(info_mismatch_mask(w, w2));
    d.u(e1_delta_mask(w, GOLDEN_WORDS)); d.u(ctx_mismatch_mask(w, GOLDEN_WORDS)); d.u(info_mismatch_mask(w, GOLDEN_WORDS));
    d.u(out_of_domain_mask(w));
    d.u((uint64_t) (first_diff(w, w2) + 1));
    d.t(warn_text(capture_warnings(w2)));
  } else if (comp == 1) {
    const uint32_t salt = r.next();
    const uint32_t seq = r.next();
    const uint32_t pc = r.below(9);
    const uint32_t pg = r.next();
    const uint32_t hi = r.next();
    const uint32_t lo = r.next();
    const uint64_t pb = ((uint64_t) hi << 32) | lo;
    const CaptureWords w = gen_words(r, 40);
    d.u(candidate_id(salt, seq, (uint8_t) pc, pg, pb, w));
    d.u(candidate_id_alt_zero_header_reading(salt, seq, (uint8_t) pc, pg, pb, w));
    d.t(id_text(candidate_id(salt, seq, (uint8_t) pc, pg, pb, w)));
  } else if (comp == 2) {
    const CaptureWords w = gen_mixed_words(r, 60);
    const CaptureWords w2 = gen_words(r, 30);
    const bool stored = r.below(2) == 1;
    const uint32_t dx = r.below(0x80000);
    const uint32_t dc = r.below(0x200);
    const uint32_t di = r.below(0x20);
    constexpr uint32_t CEIL[4] = {8000u, 5000u, 3000u, 10000u};
    const uint32_t ci = r.below(4);
    const Refusals ref = capture_refusals(w, CEIL[ci]);
    const uint32_t cls = r.below(10);
    const uint32_t an = r.below(3);
    d.t(b5_text(true, w, stored, dx));
    d.t(b5_text(false, w, stored, dx));
    d.t(b6_text(true, w, stored, (uint16_t) dc, (uint8_t) di));
    d.t(b6_text(false, w, stored, (uint16_t) dc, (uint8_t) di));
    d.t(not_saveable_text(ref, w, (uint8_t) cls, an == 0 ? (uint8_t) 4 : (uint8_t) 0));
    d.t(pass_mismatch_text(w, w2));
    d.u(review_eligible(ref, (uint8_t) cls, an == 0 ? (uint8_t) 4 : (uint8_t) 0) ? 1 : 0);
  } else if (comp == 3) {
    const Rec p = gen_profile(r);
    const WRec w = gen_witness(r, p.p);
    constexpr uint32_t ERRP[5] = {0u, 0u, 0u, 4359u, 4294967295u};
    constexpr uint32_t USP[3] = {0u, 1234u, 4294967295u};
    const uint32_t why = r.below(13);
    const uint32_t ei = r.below(5);
    const uint32_t ui = r.below(3);
    const uint32_t cls = r.below(9);
    d.t(b2_text(p.load, p.p, w.load, w.w, (uint8_t) why, ERRP[ei], USP[ui]));
    d.t(b7_text(p.load, p.p, (uint8_t) cls));
    d.t(b8_text(p.load, p.p, (uint8_t) cls));
    const PriorFingerprint f = prior_fingerprint(p.load, p.p, p.len);
    d.u(f.generation);
    d.u(f.binding);
  } else if (comp == 4) {
    constexpr uint8_t RAP[6] = {0, 0, 0, 1, 2, 4};
    constexpr uint32_t SEENP[3] = {0u, 3u, 9u};
    const Rec p = gen_profile(r);
    const WRec w = gen_witness(r, p.p);
    const Rec p2 = gen_profile(r);
    const WRec w2 = gen_witness(r, p2.p);
    ReadInputs in;
    in.p_load = p.load; in.p = p.p; in.w_load = w.load; in.w = w.w;
    in.healthy = r.below(100) < 90;
    in.present_seen = (uint8_t) r.below(4);
    { const uint32_t i = r.below(6); in.read_anomaly = RAP[i]; }
    { const uint32_t i = r.below(3); in.seen_hw_gen = SEENP[i]; }
    in.baseline_valid = r.below(100) < 70;
    const bool same = r.below(100) < 50;
    in.last_p_load = same ? p.load : p2.load;
    in.last_p_bytes = ecco_fallback::encode_profile(same ? p.p : p2.p);
    in.last_w_load = same ? w.load : w2.load;
    in.last_w_bytes = ecco_fbdurable::encode_provision(same ? w.w : w2.w);
    const ReadEval e = evaluate_read(in);
    d.u(e.latch.present_seen); d.u(e.latch.read_anomaly); d.u(e.p_fba_class); d.u(e.w_class); d.u(e.cls); d.u(e.why); d.u(e.rule);
    d.u(e.seen_hw_gen); d.u(e.p_diverged ? 1 : 0); d.u(e.w_diverged ? 1 : 0);
  } else if (comp == 5) {
    const CaptureWords w = gen_mixed_words(r, 40);
    constexpr uint32_t CEIL[4] = {8000u, 5000u, 3000u, 10000u};
    const uint32_t ci = r.below(4);
    const Rec p = gen_profile(r);
    const uint32_t cls = r.below(9);
    const uint32_t an = r.below(4);
    ReviewInputs in;
    in.words = w; in.ceiling_w = CEIL[ci]; in.cls = (uint8_t) cls; in.read_anomaly = an == 0 ? (uint8_t) 4 : (uint8_t) 0;
    in.p_load = p.load; in.p = p.p; in.p_stored_len = p.len;
    in.salt = r.next();
    in.seq_next = r.next();
    const ReviewVerdict v = review_evaluate(in);
    d.u(v.refusals.count); d.u(v.warnings); d.u(v.eligible ? 1 : 0); d.u(v.has_stored ? 1 : 0); d.u(v.prior_generation); d.u(v.prior_binding);
    d.u(v.id); d.u(v.dx); d.u(v.dc); d.u(v.di); d.t(v.sv);
  } else if (comp == 6) {
    const GateInputs g = gen_gate(r);
    const ProbeResults pr = gen_probes(r);
    fold_slot(d, classify_fp(g, pr.fp));
    fold_slot(d, classify_dump(g, pr.dump));
    fold_slot(d, classify_r244(g, pr.r244));
    fold_slot(d, classify_bus(g));
    fold_slot(d, classify_fbs(g));
    fold_slot(d, classify_mtou(g));
    d.u(bus_busy(g.bus) ? 1 : 0);
    d.u(lock_stuck(g.bus) ? 1 : 0);
    d.u(lock_age_ms(g.bus));
    d.s(bus_owner_text(g.bus));
    d.s(bus_owner_text_with_leases(g.bus, classify_fp(g, pr.fp), classify_dump(g, pr.dump)));
    {  // FW1: the mutex flag (almost) alone with ACTIVE leases forced often: the BUS refusal of the real gate and the owner it names
      GateInputs h = g;
      h.boot_loaded = true;
      h.free_power_write_enable = false; h.dump_write_enable = false; h.manual_config_write_enable = false;
      h.probe_latch = 0;
      h.bus.manual_write_in_progress = true;
      h.bus.diag_write_lock_held = false;
      h.bus.fallback_profile_op_in_progress = false;
      h.bus.fallback_profile_capture_dispatch_running = false;
      h.bus.correction_in_progress = r.below(10) == 0;
      h.bus.verification_pending = r.below(10) == 0;
      h.bus.verification_read_active = r.below(10) == 0;
      h.bus.free_power_operation_in_progress = r.below(10) == 0;
      h.bus.free_power_recovery_force_in_progress = r.below(10) == 0;
      h.bus.free_power_recovery_accept_in_progress = r.below(10) == 0;
      h.bus.reg244_apply_in_progress = r.below(10) == 0;
      h.bus.dump_operation_in_progress = r.below(10) == 0;
      const uint32_t lm = r.below(4);
      if (lm == 0 || lm == 2) {
        h.fp.free_power_marker_boot_load = 0; h.fp.free_power_recovery_metadata_corrupt = false; h.fp.free_power_snapshot_valid = true;
        h.fp.free_power_marker_state = 1; h.fp.free_power_operator_needed = false; h.fp.free_power_active_persisted = true;
        h.fp.free_power_restore_requested = false; h.fp.expired = false; h.fp.run_start = false; h.fp.run_restore = false; h.fp.run_operator = false;
      }
      if (lm == 1 || lm == 2) {
        h.dump.dump_marker_boot_load = 0; h.dump.dump_recovery_metadata_corrupt = false; h.dump.dump_containment_state = 0;
        h.dump.dump_snapshot_valid = true; h.dump.dump_marker_state = 1; h.dump.dump_operator_needed = false; h.dump.dump_active_persisted = true;
        h.dump.dump_restore_requested = false; h.dump.expired = false; h.dump.run_start = false; h.dump.run_restore = false;
      }
      const GateResult z = gate_decide(h, ProbeResults{});
      d.u(z.code); d.u(z.slot); d.t(z.text); d.t(z.obl);
      d.s(bus_owner_text_with_leases(h.bus, z.fp, z.dump));
    }
  } else if (comp == 7) {
    const GateInputs g = gen_gate(r);
    const ProbeResults pr = gen_probes(r);
    const GateResult x = gate_decide(g, pr);
    d.u(x.code); d.u(x.slot); d.u(x.probe_fp ? 1 : 0); d.u(x.probe_dump ? 1 : 0); d.u(x.probe_r244 ? 1 : 0); d.u(x.latch);
    d.t(x.obl); d.t(x.text);
    fold_slot(d, x.bus); fold_slot(d, x.fbs); fold_slot(d, x.fp); fold_slot(d, x.dump); fold_slot(d, x.r244); fold_slot(d, x.mtou);
    d.u(lease_domain_nonclear(g));
    const GateResult y = gate_decide(g, ProbeResults{});
    d.u(y.code); d.u(y.latch); d.t(y.text);
  } else if (comp == 8) {
    constexpr uint8_t SLOTP[5] = {SLOT_FP, SLOT_DUMP, SLOT_R244, SLOT_FBS, SLOT_BUS};
    constexpr const char *OWN[7] = {"Free Power", "Register 244 test", "Dump to Grid", "Fallback Profile", "clock correction", "clock verification", "manual write"};
    const uint32_t si = r.below(5);
    const uint32_t kind = r.below(15);
    const uint32_t basis = r.below(20);
    const uint32_t k = r.below(10);
    const uint32_t oi = r.below(7);
    const uint32_t age = r.next();
    d.t(refusal_text(SLOTP[si], SlotClass{(uint8_t) kind, (uint8_t) basis}, (uint8_t) k, OWN[oi], age));
    const uint32_t code = r.below(9);
    const uint32_t step = r.below(6);
    const uint32_t exc = r.below(256);
    d.t(read_fail_text((uint8_t) code, (uint8_t) step, (uint8_t) exc));
    const uint32_t st = r.below(5);
    const bool have = r.below(2) == 1;
    const uint32_t pc = r.below(10);
    const uint32_t ex = r.below(130);
    const uint32_t wm = r.below(128);
    const uint32_t lt = r.below(65536);
    const uint32_t sv = r.below(5);
    constexpr const char *SVP[5] = {"OK", "NO:244X,PWRL1,SOCH2+1", "", "NO:PWRL1,PWRL2,PWRL3,XXXXX", "NO:PWRL1,PWRL2,PWRL3,XXXXXX"};
    constexpr const char *OBLP[5] = {"FP:CA,DP:CM,R4:CA,MT:CN,FS:CA,BUS:OK", "FP:UR,DP:NP,R4:NP,MT:CN,FS:CA,BUS:OK", "",
                                     "FP:UR,DP:UR,R4:UR,MT:NP,FS:UR,BUS:LKX", "FP:UR,DP:UR,R4:UR,MT:NP,FS:UR,BUS:LK,FP:UR,DP:UR,R4:UR,MT:NP"};
    const uint32_t oi2 = r.below(5);
    d.t(b3_text((uint8_t) st, have, (uint8_t) pc, ex, (uint16_t) wm, OBLP[oi2], (uint16_t) lt, SVP[sv]));
    d.t(latch_text((uint16_t) lt));
    d.t(warn_text((uint16_t) wm));
    const uint32_t k1 = r.below(15); const uint32_t b1 = r.below(20);
    const uint32_t k2 = r.below(15); const uint32_t b2 = r.below(20);
    const uint32_t k3 = r.below(15); const uint32_t b3 = r.below(20);
    d.t(vector_text(SlotClass{(uint8_t) k1, (uint8_t) b1}, SlotClass{(uint8_t) k2, (uint8_t) b2}, SlotClass{(uint8_t) k3, (uint8_t) b1},
                    SlotClass{(uint8_t) k2, (uint8_t) b3}, SlotClass{(uint8_t) k1, (uint8_t) b2}, SlotClass{(uint8_t) k3, (uint8_t) b3}));
    const uint32_t lh = r.below(2);
    d.t(breaker_text(lh == 1));
    const uint32_t cs = r.below(7);
    d.t(review_cleared_domain_text((uint8_t) cs));
    const uint32_t cl = r.below(12);
    d.s(epc_name((uint8_t) cl));
    d.s(ld_name((uint8_t) r.below(7)));
    const uint32_t dfi = r.below(11);
    d.s(df_name((uint8_t) dfi));
    const uint32_t wi = r.below(8);
    d.s(w_name((uint8_t) wi));
    const uint32_t oi3 = r.below(6);
    d.s(op_name((uint8_t) oi3));
    const uint32_t wy = r.below(15);
    d.s(why_name((uint8_t) wy));
    const uint32_t bs = r.below(7);
    d.s(block_name((uint8_t) bs));
    d.s(domain_label((uint8_t) r.below(7)));
    d.s(capture_state_name((uint8_t) r.below(6)));
    const uint32_t ok = r.below(16);
    const uint32_t ob = r.below(21);
    d.s(obl_code((uint8_t) ok, (uint8_t) ob));
  } else {
    const uint32_t now = r.next();
    const uint32_t born = r.next();
    constexpr uint32_t AGEP[8] = {0u, 1u, 119999u, 120000u, 120001u, 30000u, 30001u, 4000000000u};
    const uint32_t ai = r.below(8);
    const uint32_t born2 = r.next();
    const uint32_t now2 = born2 + AGEP[ai];
    d.u(candidate_expired(now, born) ? 1 : 0);
    d.u(exp_seconds(now, born));
    d.u(candidate_expired(now2, born2) ? 1 : 0);
    d.u(exp_seconds(now2, born2));
    const bool op = r.below(2) == 1;
    const bool run = r.below(4) == 0;
    d.u(breaker_fired(op, run, now2, born2) ? 1 : 0);
    const uint32_t a = r.next(); const uint32_t b = r.next(); const uint32_t c = r.next(); const uint32_t dd = r.next(); const uint32_t e = r.next();
    d.u(writes_fingerprint(a, b, c, dd, e));
    BusInputs bus;
    bus.manual_write_in_progress = r.below(2) == 1;
    bus.diag_write_lock_held = r.below(2) == 1;
    bus.diag_write_lock_since_ms = born2;
    bus.now_ms = now2;
    d.u(lock_stuck(bus) ? 1 : 0);
    d.u(lock_age_ms(bus));
    const bool o1 = r.below(2) == 1;
    const uint32_t o2 = r.below(3);
    d.u(review_integrity_ok(o1, (uint8_t) o2) ? 1 : 0);
  }
  return d.h;
}
}  // namespace rnd
'''


class PRng:
    def __init__(self, s: int) -> None:
        self.s = s & 0xFFFFFFFF

    def next(self) -> int:
        self.s = (self.s * 1664525 + 1013904223) & 0xFFFFFFFF
        return self.s

    def below(self, n: int) -> int:
        return (self.next() >> 8) % n


class PDg:
    def __init__(self) -> None:
        self.h = fp.FNV1A64_OFFSET_BASIS

    def u(self, v) -> None:
        self.h = cap.step_le(self.h, int(v), 8)

    def s(self, t) -> None:
        self.h = fp.fnv1a_64(str(t).encode() + b"\xff", self.h)

    t = s


R_POOL = [0, 1, 2, 3, 0x20, 0x27, 59, 60, 99, 100, 101, 499, 500, 2359, 2400, 3000, 3001, 8000, 8001, 65535]
R_CEIL = [8000, 5000, 3000, 10000]


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


def r_clean_words(r: PRng) -> list:
    PW, SOCP, SCP, TIM = [500, 1000, 3000, 8000], [0, 50, 100], [0x11, 0x10, 0x13], [0, 530, 1000, 1600, 2100, 2330]
    w = list(GW)
    for n in range(6):
        c = r.below(100)
        if c < 30:
            i = r.below(4)
            w[1 + n] = PW[i]
    for n in range(6):
        c = r.below(100)
        if c < 30:
            i = r.below(3)
            w[7 + n] = SOCP[i]
    for n in range(6):
        c = r.below(100)
        if c < 30:
            i = r.below(2)
            w[13 + n] = i
    c = r.below(100)
    if c < 30:
        i = r.below(3)
        w[19] = SCP[i]
    c = r.below(100)
    if c < 20:
        i = r.below(4)
        w[21] = i
    for n in range(6):
        c = r.below(100)
        if c < 25:
            i = r.below(6)
            w[22 + n] = TIM[i]
    c = r.below(100)
    if c < 20:
        i = r.below(300)
        w[28] = i
    return w


def r_mixed_words(r: PRng, pchange: int) -> list:
    m = r.below(100)
    if m < 50:
        return r_words(r, pchange)
    return r_clean_words(r)


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
    if r.below(100) < 8:   # a "wide" record: every value 5 digits (the B7 over-200 case)
        p["generation"], p["captured_epoch"], p["reg244"] = 4294967295, 4294967295, 65535
        for name in ("reg256_261", "reg268_273", "reg274_279", "reg250_255"):
            p[name] = [65535] * 6
        for name in ("reg232", "reg243", "reg248", "reg230", "reg245", "reg247"):
            p[name] = 65535
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


def r_gate_clean(r: PRng) -> cap.GateInputs:
    g = cap.GateInputs()
    g.boot_loaded = True
    i = r.below(2)
    g.fbs_slot = fd.FBS_CLEAR_ABSENT if i == 0 else fd.FBS_CLEAR_VALID
    g.fp.free_power_marker_boot_load = r.below(2)
    g.dump.dump_marker_boot_load = r.below(2)
    g.r244.reg244_marker_boot_load = r.below(2)
    f = r.below(20)
    if f == 0:
        g.free_power_write_enable = True
    elif f == 1:
        g.bus.manual_write_in_progress = True
    elif f == 2:
        g.fbs_slot = fd.FBS_OBLIGATION
    elif f == 3:
        g.fp.free_power_marker_state = 1
    elif f == 4:
        g.dump.dump_marker_state = 1
    elif f == 5:
        g.r244.reg244_marker_state = 1
    elif f == 6:
        g.probe_latch = 0x0010
    elif f == 7:
        g.fp.run_start = True
    elif f == 8:
        g.bus.fallback_profile_op_in_progress = True
    elif f == 9:
        g.boot_loaded = False
    return g


def r_gate(r: PRng) -> cap.GateInputs:
    m = r.below(100)
    if m < 45:
        return r_gate_clean(r)
    BLP = [0, 1, 1, 1, 1, 2, 3, 255]
    MSP = [0, 0, 0, 0, 0, 0, 1, 2]
    NIB = [0] * 12 + [1, 2, 3, 4, 5, 15]
    FBSP = [1, 1, 1, 2, 0, 3, 4]
    g = cap.GateInputs()
    g.boot_loaded = r.below(100) < 95
    g.fbs_slot = FBSP[r.below(7)]
    a, b, c = r.below(18), r.below(18), r.below(18)
    g.probe_latch = cap.latch_set(cap.latch_set(cap.latch_set(0, cap.DOM_FP, NIB[a]), cap.DOM_DUMP, NIB[b]), cap.DOM_R244, NIB[c])
    g.free_power_write_enable = r.below(100) < 3
    g.dump_write_enable = r.below(100) < 3
    g.manual_config_write_enable = r.below(100) < 3
    for name in ("manual_write_in_progress", "correction_in_progress", "verification_pending", "verification_read_active",
                 "free_power_operation_in_progress", "free_power_recovery_force_in_progress", "free_power_recovery_accept_in_progress",
                 "reg244_apply_in_progress", "dump_operation_in_progress", "fallback_profile_op_in_progress",
                 "fallback_profile_capture_dispatch_running"):
        setattr(g.bus, name, r.below(100) < 4)
    g.bus.diag_write_lock_held = r.below(100) < 30
    g.bus.diag_write_lock_since_ms = r.next()
    g.bus.now_ms = r.next()
    g.fp.free_power_marker_boot_load = BLP[r.below(8)]
    g.fp.free_power_recovery_metadata_corrupt = r.below(100) < 4
    g.fp.free_power_snapshot_valid = r.below(100) < 8
    g.fp.free_power_marker_state = MSP[r.below(8)]
    g.fp.free_power_operator_needed = r.below(100) < 25
    g.fp.free_power_active_persisted = r.below(100) < 5
    g.fp.free_power_restore_requested = r.below(100) < 5
    g.fp.expired = r.below(100) < 10
    g.fp.run_start = r.below(100) < 3
    g.fp.run_restore = r.below(100) < 3
    g.fp.run_operator = r.below(100) < 3
    g.dump.dump_marker_boot_load = BLP[r.below(8)]
    g.dump.dump_recovery_metadata_corrupt = r.below(100) < 4
    c2 = r.below(100) < 8
    which = r.below(2)
    g.dump.dump_containment_state = (3 if which == 0 else 8) if c2 else 0
    g.dump.dump_snapshot_valid = r.below(100) < 8
    g.dump.dump_marker_state = MSP[r.below(8)]
    g.dump.dump_operator_needed = r.below(100) < 25
    g.dump.dump_active_persisted = r.below(100) < 5
    g.dump.dump_restore_requested = r.below(100) < 10
    g.dump.expired = r.below(100) < 10
    g.dump.run_start = r.below(100) < 3
    g.dump.run_restore = r.below(100) < 3
    g.r244.reg244_marker_boot_load = BLP[r.below(8)]
    g.r244.reg244_recovery_metadata_corrupt = r.below(100) < 4
    g.r244.reg244_snapshot_valid = r.below(100) < 8
    g.r244.reg244_marker_state = MSP[r.below(8)]
    g.r244.run_apply = r.below(100) < 3
    g.r244.run_restore = r.below(100) < 3
    return g


def r_probes(r: PRng) -> cap.ProbeResults:
    PRB = [0, 0, 1, 2, 2, 3, 4, 5, 6]
    return cap.ProbeResults(PRB[r.below(9)], PRB[r.below(9)], PRB[r.below(9)])


def r_fold_slot(d: PDg, c: cap.SlotClass) -> None:
    d.u(c.kind)
    d.u(c.basis)
    d.s(cap.obl_code(c.kind, c.basis))


def r_comp_digest(seed: int, comp: int) -> int:
    r = PRng(seed * 2654435761 + comp * 40503 + 12345)
    d = PDg()
    if comp == 0:
        w = r_mixed_words(r, 45)
        ceiling = R_CEIL[r.below(4)]
        w2 = r_words(r, 30)
        ref = cap.capture_refusals(w, ceiling)
        d.u(ref.count)
        for i in range(ref.count):
            d.u(ref.item[i])
        d.t(cap.sv_text(ref))
        d.u(cap.capture_warnings(w))
        d.u(1 if cap.ring_valid(w) else 0)
        d.u(cap.e1_delta_mask(w, w2)); d.u(cap.ctx_mismatch_mask(w, w2)); d.u(cap.info_mismatch_mask(w, w2))
        d.u(cap.e1_delta_mask(w, GW)); d.u(cap.ctx_mismatch_mask(w, GW)); d.u(cap.info_mismatch_mask(w, GW))
        d.u(cap.out_of_domain_mask(w))
        d.u(cap.first_diff(w, w2) + 1)
        d.t(cap.warn_text(cap.capture_warnings(w2)))
    elif comp == 1:
        salt, seq, pc, pg = r.next(), r.next(), r.below(9), r.next()
        hi, lo = r.next(), r.next()
        pb = (hi << 32) | lo
        w = r_words(r, 40)
        d.u(cap.candidate_id(salt, seq, pc, pg, pb, w))
        d.u(cap.candidate_id_alt_zero_header_reading(salt, seq, pc, pg, pb, w))
        d.t(cap.id_text(cap.candidate_id(salt, seq, pc, pg, pb, w)))
    elif comp == 2:
        w = r_mixed_words(r, 60)
        w2 = r_words(r, 30)
        stored = r.below(2) == 1
        dx, dc, di = r.below(0x80000), r.below(0x200), r.below(0x20)
        ci = r.below(4)
        ref = cap.capture_refusals(w, R_CEIL[ci])
        cls = r.below(10)
        an = r.below(3)
        anomaly = 4 if an == 0 else 0
        d.t(cap.b5_text(True, w, stored, dx))
        d.t(cap.b5_text(False, w, stored, dx))
        d.t(cap.b6_text(True, w, stored, dc, di))
        d.t(cap.b6_text(False, w, stored, dc, di))
        d.t(cap.not_saveable_text(ref, w, cls, anomaly))
        d.t(cap.pass_mismatch_text(w, w2))
        d.u(1 if cap.review_eligible(ref, cls, anomaly) else 0)
    elif comp == 3:
        pl, p, ln = r_profile(r)
        wl, w = r_witness(r, p)
        why = r.below(13)
        ei, ui = r.below(5), r.below(3)
        cls = r.below(9)
        d.t(cap.b2_text(pl, p, wl, w, why, [0, 0, 0, 4359, 4294967295][ei], [0, 1234, 4294967295][ui]))
        d.t(cap.b7_text(pl, p, cls))
        d.t(cap.b8_text(pl, p, cls))
        f = cap.prior_fingerprint(pl, p, ln)
        d.u(f.generation)
        d.u(f.binding)
    elif comp == 4:
        RAP = [0, 0, 0, 1, 2, 4]
        pl, p, _ln = r_profile(r)
        wl, w = r_witness(r, p)
        pl2, p2, _ln2 = r_profile(r)
        wl2, w2 = r_witness(r, p2)
        healthy = r.below(100) < 90
        present_seen = r.below(4)
        read_anomaly = RAP[r.below(6)]
        seen = [0, 3, 9][r.below(3)]
        baseline = r.below(100) < 70
        same = r.below(100) < 50
        e = cap.evaluate_read(cap.ReadInputs(
            p_load=pl, p=p, w_load=wl, w=w, healthy=healthy, present_seen=present_seen, read_anomaly=read_anomaly, seen_hw_gen=seen,
            baseline_valid=baseline, last_p_load=pl if same else pl2, last_p_bytes=fp.pack_profile(p if same else p2),
            last_w_load=wl if same else wl2, last_w_bytes=fd.pack_provision(w if same else w2)))
        d.u(e.latch.present_seen); d.u(e.latch.read_anomaly); d.u(e.p_fba_class); d.u(e.w_class); d.u(e.cls); d.u(e.why); d.u(e.rule)
        d.u(e.seen_hw_gen); d.u(1 if e.p_diverged else 0); d.u(1 if e.w_diverged else 0)
    elif comp == 5:
        w = r_mixed_words(r, 40)
        ci = r.below(4)
        pl, p, ln = r_profile(r)
        cls = r.below(9)
        an = r.below(4)
        salt = r.next()
        seq = r.next()
        v = cap.review_evaluate(cap.ReviewInputs(words=w, ceiling_w=R_CEIL[ci], cls=cls, read_anomaly=4 if an == 0 else 0, p_load=pl, p=p,
                                                 p_stored_len=ln, salt=salt, seq_next=seq))
        d.u(v.refusals.count); d.u(v.warnings); d.u(1 if v.eligible else 0); d.u(1 if v.has_stored else 0); d.u(v.prior_generation)
        d.u(v.prior_binding); d.u(v.id); d.u(v.dx); d.u(v.dc); d.u(v.di); d.t(v.sv)
    elif comp == 6:
        g = r_gate(r)
        pr = r_probes(r)
        r_fold_slot(d, cap.classify_fp(g, pr.fp))
        r_fold_slot(d, cap.classify_dump(g, pr.dump))
        r_fold_slot(d, cap.classify_r244(g, pr.r244))
        r_fold_slot(d, cap.classify_bus(g))
        r_fold_slot(d, cap.classify_fbs(g))
        r_fold_slot(d, cap.classify_mtou(g))
        d.u(1 if cap.bus_busy(g.bus) else 0)
        d.u(1 if cap.lock_stuck(g.bus) else 0)
        d.u(cap.lock_age_ms(g.bus))
        d.s(cap.bus_owner_text(g.bus))
        d.s(cap.bus_owner_text_with_leases(g.bus, cap.classify_fp(g, pr.fp), cap.classify_dump(g, pr.dump)))
        h = copy.deepcopy(g)   # FW1 (the same block as the C++ generator)
        h.boot_loaded = True
        h.free_power_write_enable = h.dump_write_enable = h.manual_config_write_enable = False
        h.probe_latch = 0
        h.bus.manual_write_in_progress = True
        h.bus.diag_write_lock_held = False
        h.bus.fallback_profile_op_in_progress = False
        h.bus.fallback_profile_capture_dispatch_running = False
        for name in ("correction_in_progress", "verification_pending", "verification_read_active", "free_power_operation_in_progress",
                     "free_power_recovery_force_in_progress", "free_power_recovery_accept_in_progress", "reg244_apply_in_progress",
                     "dump_operation_in_progress"):
            setattr(h.bus, name, r.below(10) == 0)
        lm = r.below(4)
        if lm in (0, 2):
            h.fp.free_power_marker_boot_load, h.fp.free_power_recovery_metadata_corrupt, h.fp.free_power_snapshot_valid = 0, False, True
            h.fp.free_power_marker_state, h.fp.free_power_operator_needed, h.fp.free_power_active_persisted = 1, False, True
            h.fp.free_power_restore_requested, h.fp.expired, h.fp.run_start, h.fp.run_restore, h.fp.run_operator = False, False, False, False, False
        if lm in (1, 2):
            h.dump.dump_marker_boot_load, h.dump.dump_recovery_metadata_corrupt, h.dump.dump_containment_state = 0, False, 0
            h.dump.dump_snapshot_valid, h.dump.dump_marker_state, h.dump.dump_operator_needed, h.dump.dump_active_persisted = True, 1, False, True
            h.dump.dump_restore_requested, h.dump.expired, h.dump.run_start, h.dump.run_restore = False, False, False, False
        z = cap.gate_decide(h, cap.ProbeResults())
        d.u(z.code); d.u(z.slot); d.t(z.text); d.t(z.obl)
        d.s(cap.bus_owner_text_with_leases(h.bus, z.fp, z.dump))
    elif comp == 7:
        g = r_gate(r)
        pr = r_probes(r)
        x = cap.gate_decide(g, pr)
        d.u(x.code); d.u(x.slot); d.u(1 if x.probe_fp else 0); d.u(1 if x.probe_dump else 0); d.u(1 if x.probe_r244 else 0); d.u(x.latch)
        d.t(x.obl); d.t(x.text)
        for c in (x.bus, x.fbs, x.fp, x.dump, x.r244, x.mtou):
            r_fold_slot(d, c)
        d.u(cap.lease_domain_nonclear(g))
        y = cap.gate_decide(g, cap.ProbeResults())
        d.u(y.code); d.u(y.latch); d.t(y.text)
    elif comp == 8:
        SLOTP = [cap.SLOT_FP, cap.SLOT_DUMP, cap.SLOT_R244, cap.SLOT_FBS, cap.SLOT_BUS]
        OWN = ["Free Power", "Register 244 test", "Dump to Grid", "Fallback Profile", "clock correction", "clock verification", "manual write"]
        si, kind, basis, k, oi = r.below(5), r.below(15), r.below(20), r.below(10), r.below(7)
        age = r.next()
        d.t(cap.refusal_text(SLOTP[si], cap.SlotClass(kind, basis), k, OWN[oi], age))
        code, step, exc = r.below(9), r.below(6), r.below(256)
        d.t(cap.read_fail_text(code, step, exc))
        st = r.below(5)
        have = r.below(2) == 1
        pc, ex, wm, lt, sv = r.below(10), r.below(130), r.below(128), r.below(65536), r.below(5)
        SVP = ["OK", "NO:244X,PWRL1,SOCH2+1", "", "NO:PWRL1,PWRL2,PWRL3,XXXXX", "NO:PWRL1,PWRL2,PWRL3,XXXXXX"]
        OBLP = ["FP:CA,DP:CM,R4:CA,MT:CN,FS:CA,BUS:OK", "FP:UR,DP:NP,R4:NP,MT:CN,FS:CA,BUS:OK", "",
                "FP:UR,DP:UR,R4:UR,MT:NP,FS:UR,BUS:LKX", "FP:UR,DP:UR,R4:UR,MT:NP,FS:UR,BUS:LK,FP:UR,DP:UR,R4:UR,MT:NP"]
        oi2 = r.below(5)
        d.t(cap.b3_text(st, have, pc, ex, wm, OBLP[oi2], lt, SVP[sv]))
        d.t(cap.latch_text(lt))
        d.t(cap.warn_text(wm))
        k1, b1 = r.below(15), r.below(20)
        k2, b2 = r.below(15), r.below(20)
        k3, b3 = r.below(15), r.below(20)
        S = cap.SlotClass
        d.t(cap.vector_text(S(k1, b1), S(k2, b2), S(k3, b1), S(k2, b3), S(k1, b2), S(k3, b3)))
        lh = r.below(2)
        d.t(cap.breaker_text(lh == 1))
        cs = r.below(7)
        d.t(cap.review_cleared_domain_text(cs))
        cl = r.below(12)
        d.s(cap.epc_name(cl))
        d.s(cap.ld_name(r.below(7)))
        dfi = r.below(11)
        d.s(cap.df_name(dfi))
        wi = r.below(8)
        d.s(cap.w_name(wi))
        oi3 = r.below(6)
        d.s(cap.op_name(oi3))
        wy = r.below(15)
        d.s(cap.why_name(wy))
        bs = r.below(7)
        d.s(cap.block_name(bs))
        d.s(cap.domain_label(r.below(7)))
        d.s(cap.capture_state_name(r.below(6)))
        ok_, ob_ = r.below(16), r.below(21)
        d.s(cap.obl_code(ok_, ob_))
    else:
        now, born = r.next(), r.next()
        AGEP = [0, 1, 119999, 120000, 120001, 30000, 30001, 4000000000]
        ai = r.below(8)
        born2 = r.next()
        now2 = (born2 + AGEP[ai]) & 0xFFFFFFFF
        d.u(1 if cap.candidate_expired(now, born) else 0)
        d.u(cap.exp_seconds(now, born))
        d.u(1 if cap.candidate_expired(now2, born2) else 0)
        d.u(cap.exp_seconds(now2, born2))
        op = r.below(2) == 1
        run = r.below(4) == 0
        d.u(1 if cap.breaker_fired(op, run, now2, born2) else 0)
        a, b, c, dd, e = r.next(), r.next(), r.next(), r.next(), r.next()
        d.u(cap.writes_fingerprint(a, b, c, dd, e))
        bus = cap.BusInputs()
        bus.manual_write_in_progress = r.below(2) == 1
        bus.diag_write_lock_held = r.below(2) == 1
        bus.diag_write_lock_since_ms = born2
        bus.now_ms = now2
        d.u(1 if cap.lock_stuck(bus) else 0)
        d.u(cap.lock_age_ms(bus))
        o1 = r.below(2) == 1
        o2 = r.below(3)
        d.u(1 if cap.review_integrity_ok(o1, o2) else 0)
    return d.h


def random_tu() -> str:
    lines = [RANDOM_TU_CXX]
    for seed in range(1, RANDOM_CASES + 1):
        for comp in range(len(RANDOM_COMPONENTS)):
            lines.append(f'static_assert(rnd::comp_digest({seed}u, {comp}u) == 0x{r_comp_digest(seed, comp):016X}ULL, '
                         f'"FB-B1 random parity: {RANDOM_COMPONENTS[comp]} case {seed}");')
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
    # a mutated mirror digest must be a compile error (the check is not vacuous)
    bad = tu.replace("== 0x", "== 0x1", 1)
    r = tc.compile(inc, bad, "gnu++17")
    check("negative control: one corrupted digest is a static_assert failure naming its component and case",
          r.returncode != 0 and "FB-B1 random parity" in r.stderr, r.stderr[-300:])


# ===========================================================================================================
# Header discipline
# ===========================================================================================================
def strip_comments(text: str) -> str:
    return re.sub(r"//[^\n]*", "", re.sub(r"/\*.*?\*/", " ", text, flags=re.S))


def section_discipline():
    print("[6] header discipline (the same pins the other fallback headers carry, plus the FB-B1 ones)")
    sys.path.insert(0, str(THIS.parent))
    import _tag_inventory as ti  # noqa: E402
    text = read_header()
    code = strip_comments(text)
    check("#pragma once is the first line", text.startswith("#pragma once\n"))
    includes = re.findall(r'#\s*include\s*([<"][^>"]+[>"])', text)
    check("it includes only <array>, <cstddef>, <cstdint>, <type_traits> and the FB-B0 model header (which brings the FB-A header)",
          includes == ["<array>", "<cstddef>", "<cstdint>", "<type_traits>", '"ecco_fallback_durable_model.h"'], str(includes))
    banned = [("id( (the ESPHome accessor)", r"\bid\("), ("nvs_", r"nvs_"), ("modbus", r"(?i)modbus"), ("supervision", r"(?i)supervision"),
              ("self-partial", r"(?i)self_?partial"), ("start-journal", r"(?i)start_?journal"), ("an ESPHome include", r'#\s*include\s*["<]esphome'),
              ("App.", r"\bApp\."), ("commit_record", r"commit_record"), ("load_record", r"load_record"), ("make_preference", r"make_preference"),
              ("global_preferences", r"global_preferences"), ("esphome::", r"esphome::"), ("ESP_LOG", r"ESP_LOG"), ("millis(", r"\bmillis\s*\("),
              ("delay(", r"\bdelay\s*\("), ("uart", r"(?i)\buart"), ("random_uint32", r"random_uint32"), ("ntp_", r"\bntp_"),
              ("snprintf / printf / sprintf", r"\b(?:snprintf|printf|sprintf|vsnprintf)\b"), ("std::string / <string>", r"std::string|<string>"),
              ("the writer side: commit_transition", r"commit_transition"), ("write_one_", r"write_one_"), ("WriteTarget", r"WriteTarget"),
              ("s_write_latched", r"s_write_latched"), ("make_provision", r"make_provision"), ("seal_provision", r"seal_provision"),
              ("invalidate_profile", r"invalidate_profile"), ("note_committed", r"note_committed"), ("mirror_after", r"mirror_after"),
              ("a Save / arm entity name", r"fallback_profile_arm|fallback_profile_execute|save_unconfirmed|exec_action"),
              ("a bus-layer include", r"#\s*include\s*[<\"]modbus")]
    hits = [label for label, pat in banned if re.search(pat, text)]
    check("the header (comments included) names none of: id(, nvs_, the bus layer, supervision, the journal / partial classifiers, an ESPHome "
          "include, App., commit_record, load_record, make_preference, global_preferences, esphome::, ESP_LOG, millis(, delay(, uart, "
          "random_uint32, the clock globals, printf, std::string, or any writer-side symbol (commit_transition, write_one_, make_provision, "
          "invalidate_profile, note_committed, mirror_after, the arm / execute / save_unconfirmed names)", not hits, str(hits))
    check("exactly one namespace, ecco_fbcap, and no anonymous or nested namespace",
          re.findall(r"^\s*namespace\s*(\w*)\s*\{", code, re.M) == ["ecco_fbcap"] and "}  // namespace ecco_fbcap" in text)
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
    check(f"none of the header's {len(literals)} string literals (golden strings included) matches an Energy Actions card pattern, case-insensitively",
          not bad, str(bad[:3]))
    check("the bus-layer-free wording of the exception read-failure text is the one the header carries",
          "inverter returned exception code 0x" in text and "inverter returned an exception on registers " in text)
    check("MTOU_JOURNAL_NOT_IMPLEMENTED appears in the MTOU classifier",
          re.search(r"constexpr SlotClass classify_mtou\(const GateInputs &g\) \{.*?MTOU_JOURNAL_NOT_IMPLEMENTED.*?\n\}", text, re.S) is not None)
    l2 = re.search(r"constexpr Refusals capture_refusals\(.*?\n\}\n", text, re.S).group(0) + \
        re.search(r"constexpr uint16_t capture_warnings\(.*?\n\}\n", text, re.S).group(0)
    check("L2 independence: capture_refusals / capture_warnings never call the stored-record classifier (classify_profile, profile_defect, "
          "profile_domain_valid, fba_authentic, compose) - only FB-A's leaf domain validators",
          not re.search(r"classify_profile|profile_defect|profile_domain_valid|fba_authentic|compose_profile_class|classify_witness", l2)
          and "ecco_fallback::reg244_domain_valid" in l2 and "ecco_fallback::tou_power_domain_valid" in l2, l2[:200])
    review = re.search(r"constexpr ReviewVerdict review_evaluate\(.*?\n\}\n", text, re.S).group(0)
    check("review_evaluate contains no write-side durable symbol", not re.search(r"commit|write_one|seal_|make_prov|invalidate", review))


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
    print("All FB-B1 capture host-compile checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
