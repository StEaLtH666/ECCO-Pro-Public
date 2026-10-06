#!/usr/bin/env python3
"""FB-A - Fallback Profile V1 / Failback State V1 schema and model (no behaviour).

firmware/include/ecco_fallback_profile.h freezes the two durable record
layouts, their FNV-1a-64 bindings, the V1 register classification and
context-compare granularity, the V1 domain rules, the numeric
state/reason/result codes and two pure record classifiers.
registry/fallback_profile.py is the independent Python mirror. The header is
STANDALONE: it is in no `esphome: includes:` list and no production source
includes it (section [9] proves that).

No I/O beyond reading repository files, no hardware. C++/Python agreement:
this suite parses the header's compile-time golden vectors and golden-case
tables and re-derives every value from the Python mirror;
registry/tests/test_fallback_profile_host_compile.py has a real C++ compiler
evaluate the same assertions.

Sections:
  [1]  Layout: fields, sizes, offsets, no implicit padding, constants
  [2]  Bindings: domains, byte range, field-by-field encoders, golden vectors
  [3]  Register classification and context-compare granularity
  [4]  Domain rules: schema TOU bound vs configured ceiling, 244 direction
  [5]  Profile classifier: exact precedence, golden cases, exhaustive sweeps
  [6]  Generation and INVALIDATE
  [7]  Failback record: codes, flags, apply_committed, CLEAR contract, classifier
  [8]  Tags and preference keys (independent inventory, both hash algorithms)
  [9]  Change scope: FB-A adds no production behaviour
  [10] Mutation sensitivity (model source mutants + header text mutants)
"""

from __future__ import annotations

import ctypes
import hashlib
import re
import struct
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FIRMWARE_PATH = ROOT / "firmware" / "ecco_clock_dongle_stage3_4_free_power.yaml"
HEADER_PATH = ROOT / "firmware" / "include" / "ecco_fallback_profile.h"
INCLUDE_DIR = ROOT / "firmware" / "include"
DURABLE_HEADER_PATH = INCLUDE_DIR / "ecco_durable_snapshot.h"
EVIDENCE_HEADER_PATH = INCLUDE_DIR / "ecco_recovery_evidence.h"
MODEL_PATH = ROOT / "registry" / "fallback_profile.py"
VERSION_PATH = ROOT / "VERSION.yaml"

sys.path.insert(0, str(ROOT / "registry"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(ROOT / "tools"))
import fallback_profile as fp  # noqa: E402
import _dump_sim as ds  # noqa: E402
import _dump_v2_scope as dv2s  # noqa: E402 - Dump V2 (ownership evidence) landed after the FB-A base; its exact edits are reverted before the pins
import _scope_chain as chain  # noqa: E402
import _tag_inventory as ti  # noqa: E402 - FB-T0 hardening: declaration-style-independent durable-tag inventory - FB-T0: the change-scope pins ([8] inventory, [9]) are chain-relative; see _scope_chain.py
import analyze_write_surface as aws  # noqa: E402

FAILURES: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  PASS  {name}")
    else:
        FAILURES.append(name)
        print(f"  FAIL  {name}" + (f" - {detail}" if detail else ""))


for required in (FIRMWARE_PATH, HEADER_PATH, DURABLE_HEADER_PATH, EVIDENCE_HEADER_PATH, MODEL_PATH, VERSION_PATH):
    if not required.is_file():
        print(f"  FAIL  required file not found: {required}")
        sys.exit(1)

HEADER = HEADER_PATH.read_text(encoding="utf-8")
DURABLE_HEADER = DURABLE_HEADER_PATH.read_text(encoding="utf-8")
EVIDENCE_HEADER = EVIDENCE_HEADER_PATH.read_text(encoding="utf-8")
FW_TEXT = FIRMWARE_PATH.read_text(encoding="utf-8")
MODEL_TEXT = MODEL_PATH.read_text(encoding="utf-8")

# main @ 004040b (SG-06 merged) - the FB-A base. sha256 of the LF text.
# These files are still byte-identical to that base after Manual TOU Phase 1 (PR #53).
BASE_SHA = {
    "firmware/include/ecco_durable_snapshot.h": "36c764bce649755c0865aad09f3669d56c64cef2bfd5edbd9252c9c735cfff01",
    "firmware/include/ecco_recovery_evidence.h": "c9b9b1d670ce8ef8ec33c5c1208326abd0213f042e8a69b1115b4ea85620875e",
    "registry/inverter_capabilities.yaml": "ea9a0bc97d6cbc593898631d3a20d85887e12a1839ec2dda651611287e68bf32",
    "registry/transaction_state_machine.py": "50d1d54792403a0c41069c4f88c6144707aa93bacdd240dbf749128c99ceb4ce",
    "deployment/ha-manifest.yaml": "d582beb6b3873109365c9d901f3c9dfe6c26033e7c11551814179c953412815f",
}

# The firmware YAML is NOT byte-identical to 004040b once Manual TOU Phase 1 (PR #53) is applied on top of FB-A:
# PR #53 legitimately edits it. FB-A itself (PR #54) still adds nothing to it (see the FB-A reference scan below);
# this pin is the sha256 of the LF text of the YAML as of main + PR #53 (FB-A + Manual TOU Phase 1).
POST_MTOU1_FIRMWARE_SHA = {
    "firmware/ecco_clock_dongle_stage3_4_free_power.yaml": "943856c4ca46f652b34dffdb331955e8aac0d011e21cc23fac35b56b8f9c944e",
}


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def c_int(tok: str) -> int:
    return int(tok.strip().rstrip("uUlL"), 0)


def strip_comments(code: str) -> str:
    code = re.sub(r"/\*.*?\*/", "", code, flags=re.S)
    return re.sub(r"//[^\n]*", "", code)


CODE = strip_comments(HEADER)
CTYPE_SIZE = {"uint8_t": 1, "uint16_t": 2, "uint32_t": 4, "uint64_t": 8}
CODE_OF = {"B": "uint8_t", "H": "uint16_t", "I": "uint32_t", "Q": "uint64_t"}
FW_CEILING = fp.firmware_tou_power_ceiling_w()


def header_struct(name: str):
    m = re.search(rf"struct {name} \{{(.*?)\n\}};", HEADER, re.S)
    if not m:
        return None
    return [(t, f, int(n) if n else 1) for t, f, n in re.findall(r"\b(uint\d+_t) (\w+)(?:\[(\d+)\])?;", m.group(1))]


def header_u(name: str):
    m = re.search(rf"constexpr (?:uint\d+_t|size_t) {name} = (0x[0-9A-Fa-f]+u?|\d+u?);", HEADER)
    return c_int(m.group(1)) if m else None


def header_enum(prefix: str) -> dict:
    return {n: int(v) for n, v in re.findall(rf"\b({prefix}\w*) = (\d+),", HEADER)}


def body(signature_regex: str, code: str = CODE) -> str:
    m = re.search(signature_regex + r" \{(.*?)\n\}", code, re.S)
    return " ".join(m.group(1).split()) if m else ""


HDR_PROFILE = header_struct("FallbackProfileV1") or []
HDR_FAILBACK = header_struct("FailbackStateV1") or []
HDR_OFFSETS = {s: {f: int(o) for f, o in re.findall(rf"offsetof\({s}, (\w+)\) == (\d+)", HEADER)}
               for s in ("FallbackProfileV1", "FailbackStateV1")}
HDR_SIZES = {s: int(v) for s, v in re.findall(r"static_assert\(sizeof\((\w+)\) == (\d+),", HEADER)}

# ===========================================================================
print("[1] Layout: FallbackProfileV1 / FailbackStateV1")
# ===========================================================================


def layout_agrees(m) -> bool:
    """Model layout == header struct (names, types, array lengths, order),
    offsets == the header's asserted offsets, sizes == 96 / 80."""
    return (HDR_PROFILE == [(CODE_OF[c], f, n) for f, c, n in m.PROFILE_LAYOUT]
            and HDR_FAILBACK == [(CODE_OF[c], f, n) for f, c, n in m.FAILBACK_LAYOUT]
            and m.PROFILE_OFFSETS == HDR_OFFSETS["FallbackProfileV1"]
            and m.FAILBACK_OFFSETS == HDR_OFFSETS["FailbackStateV1"]
            and m.struct_for(m.PROFILE_LAYOUT).size == HDR_SIZES.get("FallbackProfileV1") == 96
            and m.struct_for(m.FAILBACK_LAYOUT).size == HDR_SIZES.get("FailbackStateV1") == 80)


EXPECTED_PROFILE_OFFSETS = {"magic": 0, "schema": 4, "size": 6, "generation": 8, "captured_epoch": 12, "flags": 16,
                            "reg244": 18, "reg256_261": 20, "reg268_273": 32, "reg274_279": 44, "reg232": 56,
                            "reg243": 58, "reg248": 60, "reg250_255": 62, "reg230": 74, "reg245": 76, "reg247": 78,
                            "reserved0": 80, "reserved1": 84, "binding": 88}
EXPECTED_FAILBACK_OFFSETS = {"magic": 0, "schema": 4, "size": 6, "state": 8, "reason": 9, "result": 10, "flags": 11,
                             "event_seq": 12, "event_epoch": 16, "profile_generation": 20, "apply_attempts": 24,
                             "verify_mismatches": 25, "from_244": 26, "from_256_261": 28, "from_268_279": 40,
                             "profile_binding": 64, "binding": 72}
check("FallbackProfileV1 offsets are exactly the locked V1 layout (96 B)",
      HDR_OFFSETS["FallbackProfileV1"] == fp.PROFILE_OFFSETS == EXPECTED_PROFILE_OFFSETS and HDR_SIZES.get("FallbackProfileV1") == 96)
check("FailbackStateV1 offsets are exactly the locked V1 layout (80 B)",
      HDR_OFFSETS["FailbackStateV1"] == fp.FAILBACK_OFFSETS == EXPECTED_FAILBACK_OFFSETS and HDR_SIZES.get("FailbackStateV1") == 80)
check("header struct fields == model layout (name, type, array length, order), and every offset is a static_assert",
      layout_agrees(fp) and set(HDR_OFFSETS["FallbackProfileV1"]) == {f for f, _c, _n in fp.PROFILE_LAYOUT}
      and set(HDR_OFFSETS["FailbackStateV1"]) == {f for f, _c, _n in fp.FAILBACK_LAYOUT})
for sname, fields, offsets, size, cstruct in (
        ("FallbackProfileV1", HDR_PROFILE, fp.PROFILE_OFFSETS, 96, fp.FallbackProfileV1C),
        ("FailbackStateV1", HDR_FAILBACK, fp.FAILBACK_OFFSETS, 80, fp.FailbackStateV1C)):
    running, gaps = 0, []
    for t, f, n in fields:
        if offsets.get(f) != running:
            gaps.append(f)
        running += CTYPE_SIZE[t] * n
    check(f"{sname}: contiguous, no implicit padding, ends exactly at {size}", not gaps and running == size, str(gaps))
    check(f"{sname}: every field on its natural alignment", all(offsets[f] % CTYPE_SIZE[t] == 0 for t, f, _n in fields))
    check(f"{sname}: native ctypes mirror has the same size and offsets",
          ctypes.sizeof(cstruct) == size and {f: getattr(cstruct, f).offset for f in offsets} == offsets)
    check(f"{sname}: asserted trivially copyable and standard layout",
          f"static_assert(std::is_trivially_copyable<{sname}>::value" in HEADER
          and f"static_assert(std::is_standard_layout<{sname}>::value" in HEADER)
check("profile magic 0x45434650 / schema 1 / size 96; failback magic 0x45434642 / schema 1 / size 80 (header == model)",
      (header_u("PROFILE_MAGIC"), header_u("PROFILE_SCHEMA"), header_u("PROFILE_SIZE"),
       header_u("FAILBACK_MAGIC"), header_u("FAILBACK_SCHEMA"), header_u("FAILBACK_SIZE"))
      == (fp.PROFILE_MAGIC, fp.PROFILE_SCHEMA, fp.PROFILE_SIZE, fp.FAILBACK_MAGIC, fp.FAILBACK_SCHEMA, fp.FAILBACK_SIZE)
      == (0x45434650, 1, 96, 0x45434642, 1, 80))
check("binding ranges: profile [0,88), failback [0,72) - exactly each record's `binding` offset",
      header_u("PROFILE_BOUND_BYTES") == fp.PROFILE_BOUND_BYTES == 88
      and header_u("FAILBACK_BOUND_BYTES") == fp.FAILBACK_BOUND_BYTES == 72)
check("the header asserts a little-endian target", "static_assert(__BYTE_ORDER__ == __ORDER_LITTLE_ENDIAN__," in HEADER)

# ===========================================================================
print("[2] Bindings: domains, byte range, field-by-field encoders, golden vectors")
# ===========================================================================
dom_p = re.search(r'constexpr char PROFILE_BINDING_DOMAIN\[\] = "([^"]*)";', HEADER)
dom_f = re.search(r'constexpr char FAILBACK_BINDING_DOMAIN\[\] = "([^"]*)";', HEADER)
check("domains: 'ECCO-FALLBACK-PROFILE-v1' (24 B) and 'ECCO-FAILBACK-STATE-v1' (22 B), header == model, NUL not hashed",
      bool(dom_p and dom_f) and dom_p.group(1).encode() == fp.PROFILE_BINDING_DOMAIN == b"ECCO-FALLBACK-PROFILE-v1"
      and dom_f.group(1).encode() == fp.FAILBACK_BINDING_DOMAIN == b"ECCO-FAILBACK-STATE-v1"
      and "for (size_t i = 0; i + 1 < N; i++)" in HEADER
      and "static_assert(sizeof(PROFILE_BINDING_DOMAIN) - 1 == 24," in HEADER
      and "static_assert(sizeof(FAILBACK_BINDING_DOMAIN) - 1 == 22," in HEADER)
ev = dict(re.findall(r"constexpr uint64_t (FNV64_\w+) = (0x[0-9a-fA-F]+)ULL;", EVIDENCE_HEADER))
check("FNV-1a-64 constants equal ecco_recovery_evidence.h's canonical ones (restated, never included)",
      "constexpr uint64_t FNV1A64_OFFSET_BASIS = 0xCBF29CE484222325ULL;" in HEADER
      and "constexpr uint64_t FNV1A64_PRIME = 0x100000001B3ULL;" in HEADER
      and int(ev["FNV64_OFFSET_BASIS"], 16) == fp.FNV1A64_OFFSET_BASIS and int(ev["FNV64_PRIME"], 16) == fp.FNV1A64_PRIME
      and "return (hash ^ byte) * FNV1A64_PRIME;" in HEADER)
for fn, dom, bound, rec, btype, enc in (
        ("profile_binding", "PROFILE_BINDING_DOMAIN", "PROFILE_BOUND_BYTES", "FallbackProfileV1 &p", "ProfileBytes", "encode_profile(p)"),
        ("failback_binding", "FAILBACK_BINDING_DOMAIN", "FAILBACK_BOUND_BYTES", "FailbackStateV1 &s", "FailbackBytes", "encode_failback(s)")):
    b = body(rf"constexpr uint64_t {fn}\(const {rec}\)")
    check(f"{fn} hashes the domain, then {enc} stored bytes [0, {bound}) - never raw struct memory",
          b == f"const {btype} b = {enc}; uint64_t h = fnv1a64_literal(FNV1A64_OFFSET_BASIS, {dom}); "
               f"for (size_t i = 0; i < {bound}; i++) h = fnv1a64_step(h, b[i]); return h;", b)
check("no reinterpret_cast / memcpy / union type-punning anywhere in the header",
      not re.search(r"reinterpret_cast|memcpy|\bunion\b|\(const uint8_t \*\)", CODE))


def encoder_fields(fn: str, sname: str) -> dict:
    m = re.search(rf"constexpr \w+ {fn}\(.*?\n\}}\n", HEADER, re.S)
    return {f: w for f, w in re.findall(rf"offsetof\({sname}, (\w+)\)(?: \+ 2 \* i)?, \w+\.\w+(?:\[i\])?, (\d)\)",
                                        m.group(0) if m else "")}


WIDTH = {"B": "1", "H": "2", "I": "4", "Q": "8"}
for fn, sname, layout in (("encode_profile", "FallbackProfileV1", fp.PROFILE_LAYOUT),
                          ("encode_failback", "FailbackStateV1", fp.FAILBACK_LAYOUT)):
    check(f"{fn}: EVERY field serialised at its offsetof() with its own little-endian width",
          encoder_fields(fn, sname) == {f: WIDTH[c] for f, c, _n in layout})
check("put_le/get_le are little-endian (low byte first)",
      "b[off + i] = (uint8_t) ((v >> (8 * i)) & 0xFF);" in HEADER and "v |= (uint64_t) b[off + i] << (8 * i);" in HEADER)

NAMED = {"PROFILE_MAGIC": fp.PROFILE_MAGIC, "PROFILE_SCHEMA": fp.PROFILE_SCHEMA, "PROFILE_SIZE": fp.PROFILE_SIZE,
         "FAILBACK_MAGIC": fp.FAILBACK_MAGIC, "FAILBACK_SCHEMA": fp.FAILBACK_SCHEMA, "FAILBACK_SIZE": fp.FAILBACK_SIZE,
         **{f"FAILBACK_{v}": k for k, v in fp.FAILBACK_STATE_NAMES.items()},
         **{f"FAILBACK_REASON_{v}": k for k, v in fp.FAILBACK_REASON_NAMES.items()},
         **{f"FAILBACK_RESULT_{v}": k for k, v in fp.FAILBACK_RESULT_NAMES.items()}}


def parse_initializer(text: str, layout, extra=None):
    toks = [t.strip() for t in re.findall(r"\{[^{}]*\}|[^,\s][^,]*", text.strip())]
    if len(toks) != len(layout):
        return None
    out = {}
    for (f, _c, n), tok in zip(layout, toks):
        if n > 1:
            out[f] = [c_int(t) for t in tok.strip("{}").split(",")]
        elif extra and tok in extra:
            out[f] = extra[tok]
        else:
            out[f] = NAMED[tok] if tok in NAMED else c_int(tok)
    return out


def golden_records(m):
    """GOLDEN_PROFILE_V1 and GOLDEN_FAILBACK_V1[] as the header defines them, sealed by model `m`."""
    gp = re.search(r"constexpr FallbackProfileV1 GOLDEN_PROFILE_V1 = seal_profile\(FallbackProfileV1\{(.*?)\}\);", HEADER, re.S)
    arr = re.search(r"constexpr FailbackStateV1 GOLDEN_FAILBACK_V1\[\] = \{(.*?)\n\};", HEADER, re.S)
    profile = m.seal_profile(parse_initializer(gp.group(1), m.PROFILE_LAYOUT))
    bases = []
    for mm in re.finditer(r"failback_clear_record\((\d+)u\)|seal_failback\(FailbackStateV1\{(.*?)\}\)", arr.group(1), re.S):
        if mm.group(1):
            bases.append(m.failback_clear_record(int(mm.group(1))))
        else:
            rec = parse_initializer(mm.group(2), m.FAILBACK_LAYOUT, {"GOLDEN_PROFILE_V1.binding": profile["binding"]})
            bases.append(m.seal_failback(rec))
    return profile, bases


GP, GF = golden_records(fp)
check("header GOLDEN_PROFILE_V1 parsed (20 fields) and is VALID in the model", fp.classify_profile(fp.LOAD_OK, GP) == fp.PROFILE_VALID)
check("header GOLDEN_FAILBACK_V1[] parsed: 6 records (CLEAR, PREEMPT, APPLY, LATCHED/APPLIED_VERIFIED, BLOCKED x2), all VALID",
      [b["state"] for b in GF] == [0, 1, 2, 3, 4, 4]
      and all(fp.classify_failback(fp.LOAD_OK, b) == fp.FAILBACK_RECORD_VALID for b in GF))


def golden_binding_vectors(m):
    gp, gf = golden_records(m)
    out = {
        "profile binding: all-zero record": m.profile_binding(m.blank_profile()),
        "profile binding: GOLDEN_PROFILE_V1": gp["binding"],
        "profile binding: all-0xFF record": m.profile_binding(b"\xff" * 96),
        "profile binding: GOLDEN_PROFILE_V1 invalidated": m.invalidate_profile(gp)["binding"],
        "failback binding: all-zero record": m.failback_binding(m.blank_failback()),
        "failback binding: all-0xFF record": m.failback_binding(b"\xff" * 80),
    }
    out.update({f"failback binding: GOLDEN_FAILBACK_V1[{i}]": b["binding"] for i, b in enumerate(gf)})
    return out


HDR_BIND = {lab: c_int(v) for v, lab in re.findall(r'==\s*(0x[0-9A-F]+)ULL,\s*"FB-A (\w+ binding: [\w\[\] -]+)"', HEADER)}
EXP_BIND = golden_binding_vectors(fp)
check("header carries 12 compile-time binding golden vectors", set(HDR_BIND) == set(EXP_BIND) and len(HDR_BIND) == 12,
      str(sorted(set(HDR_BIND) ^ set(EXP_BIND))))
for label in sorted(EXP_BIND):
    check(f"C++ golden vector [{label}] == Python mirror", HDR_BIND.get(label) == EXP_BIND[label])
gp_bytes, gf_bytes = fp.pack_profile(GP), fp.pack_failback(GF[2])
check("profile binding == FNV-1a-64(domain || packed bytes[0:88]); failback == FNV-1a-64(domain || packed bytes[0:72])",
      GP["binding"] == fp.fnv1a_64(b"ECCO-FALLBACK-PROFILE-v1" + gp_bytes[:88])
      and GF[2]["binding"] == fp.fnv1a_64(b"ECCO-FAILBACK-STATE-v1" + gf_bytes[:72]))
check("the bindings exclude themselves (bytes [88,96) / [72,80) never change them)",
      fp.profile_binding(gp_bytes[:88] + bytes(8)) == GP["binding"] and fp.failback_binding(gf_bytes[:72] + bytes(8)) == GF[2]["binding"])
check("the failback binding covers profile_binding (bytes 64..71)",
      all(fp.failback_binding(gf_bytes[:i] + bytes([gf_bytes[i] ^ 1]) + gf_bytes[i + 1:]) != GF[2]["binding"] for i in range(64, 72)))
check("every single bound byte changes its binding (profile 0..87, failback 0..71)",
      all(fp.profile_binding(gp_bytes[:i] + bytes([gp_bytes[i] ^ 0x80]) + gp_bytes[i + 1:]) != GP["binding"] for i in range(88))
      and all(fp.failback_binding(gf_bytes[:i] + bytes([gf_bytes[i] ^ 0x80]) + gf_bytes[i + 1:]) != GF[2]["binding"] for i in range(72)))
check("big-endian packing, a NUL-terminated domain, a byte-8 start or hashing all 96 bytes would each change the golden binding",
      len({GP["binding"], fp.fnv1a_64(fp.PROFILE_BINDING_DOMAIN + fp.pack_profile(GP, ">")[:88]),
           fp.fnv1a_64(fp.PROFILE_BINDING_DOMAIN + b"\0" + gp_bytes[:88]), fp.fnv1a_64(fp.PROFILE_BINDING_DOMAIN + gp_bytes[8:88]),
           fp.fnv1a_64(fp.PROFILE_BINDING_DOMAIN + gp_bytes)}) == 5)
check("model pack/unpack round-trips every golden record", fp.unpack_profile(gp_bytes) == GP
      and all(fp.unpack_failback(fp.pack_failback(b)) == b for b in GF))

# ===========================================================================
print("[3] Register classification and context-compare granularity")
# ===========================================================================
E1 = {244, *range(256, 262), *range(268, 280)}
CTX = {232, 243, 248, *range(250, 256)}
INFO = {230, 245, 247}
by_class = {c: {a for a in range(0x10000) if fp.register_class(a) == c} for c in (fp.REG_E1, fp.REG_CTX, fp.REG_INFO)}
check("E1 = 244, 256-261, 268-273, 274-279", by_class[fp.REG_E1] == E1)
check("CTX = 232, 243, 248, 250-255", by_class[fp.REG_CTX] == CTX)
check("INFO = 230, 245, 247 (230 is INFO, not E1)", by_class[fp.REG_INFO] == INFO and fp.register_class(230) == fp.REG_INFO)
check("excluded: 22-24, 246, 249, 262-267 and every other address; the table holds exactly 31 registers",
      all(fp.register_class(a) == fp.REG_EXCLUDED and fp.register_class_mask(a) == 0 for a in fp.EXPLICITLY_EXCLUDED)
      and len(fp.REGISTER_TABLE) == 31)
check("compare masks: 232 bit 0, 248 bit 0, 243 full word, 250-255 full word; 274-279 bits 0-1; other E1/INFO full word",
      fp.register_class_mask(232) == 0x0001 and fp.register_class_mask(248) == 0x0001 and fp.register_class_mask(243) == 0xFFFF
      and all(fp.register_class_mask(a) == 0xFFFF for a in range(250, 256))
      and all(fp.register_class_mask(a) == 0x0003 for a in range(274, 280))
      and all(fp.register_class_mask(a) == 0xFFFF for a in (E1 | INFO) - set(range(274, 280))))
check("header masks REG232_CTX_MASK = REG248_CTX_MASK = 0x0001, SLOT_SOURCE_BITS_MASK = 0x0003",
      (header_u("REG232_CTX_MASK"), header_u("REG248_CTX_MASK"), header_u("SLOT_SOURCE_BITS_MASK")) == (1, 1, 3))
reg_digest = re.search(r'static_assert\(register_class_digest\(\) == (0x[0-9A-F]+)ULL, "FB-A register classification digest"\);', HEADER)
check("header's register class/mask digest over all 65536 addresses == model", reg_digest is not None
      and c_int(reg_digest.group(1)) == fp.register_class_digest())
check("ctx_matches: 232/248 compare bit 0 only (bits 1-15 informational), 243/250-255 the full word",
      fp.ctx_matches(232, 0x0001, 0xFFFF) and not fp.ctx_matches(232, 0x0001, 0xFFFE) and fp.ctx_matches(248, 0, 0xFFFE)
      and not fp.ctx_matches(248, 1, 0) and not fp.ctx_matches(243, 1, 3) and not fp.ctx_matches(250, 0x530, 0x531)
      and all(fp.ctx_matches(a, p, l) == ((p ^ l) & 1 == 0) for a in (232, 248)
              for p in (0, 1, 0xFFFE, 0xFFFF) for l in (0, 1, 2, 0x8001)))
check("header pins the same compare granularity at compile time",
      '"FB-A: 232/248 compare bit 0 only; 243/250-255 the full word; non-CTX never matches"' in HEADER)
check("the record stores exactly the E1 + CTX + INFO registers, each once",
      sorted(a for regs in fp.PROFILE_REGISTER_FIELDS.values() for a in regs) == sorted(E1 | CTX | INFO))

# ===========================================================================
print("[4] Domain rules: schema TOU bound vs configured ceiling, 244 direction")
# ===========================================================================
ver_ceiling = re.search(r"^\s+inverter_tou_power_ceiling_w: (\d+)$", VERSION_PATH.read_text(encoding="utf-8"), re.M)
check("V1_TOU_POWER_MAX_W = 8000 (schema constant) currently equals ${ecco_inverter_tou_power_ceiling_w} and VERSION.yaml",
      header_u("V1_TOU_POWER_MAX_W") == fp.V1_TOU_POWER_MAX_W == 8000 == FW_CEILING
      and ver_ceiling is not None and int(ver_ceiling.group(1)) == FW_CEILING)
check("V1_TOU_POWER_MIN_W = 500, SOC_MAX = 100, REG244_PROFILE_REQUIRED = 2 (header == model)",
      (header_u("V1_TOU_POWER_MIN_W"), header_u("SOC_MAX"), header_u("REG244_PROFILE_REQUIRED"))
      == (fp.V1_TOU_POWER_MIN_W, fp.SOC_MAX, fp.REG244_PROFILE_REQUIRED) == (500, 100, 2))
check("profile validity never takes a runtime/site ceiling: no ceiling parameter on any validator or classifier",
      "constexpr bool tou_power_domain_valid(uint16_t v) { return v >= V1_TOU_POWER_MIN_W && v <= V1_TOU_POWER_MAX_W; }" in HEADER
      and "constexpr ProfileClass classify_profile(uint8_t load, const FallbackProfileV1 &p)" in HEADER
      and not re.search(r"ceiling_w\b", CODE))
DIG = {k: c_int(v) for k, v in re.findall(r"static_assert\(domain_digest\((DOMAIN_\w+)\) == (0x[0-9A-F]+)ULL", HEADER)}
PREDICATES = {"DOMAIN_REG244": "reg244_domain_valid", "DOMAIN_TOU_POWER": "tou_power_domain_valid",
              "DOMAIN_SOC": "soc_domain_valid", "DOMAIN_SLOT_SOURCE": "slot_source_domain_valid",
              "DOMAIN_FROM_244": "from_244_domain_valid"}
for kind, pred in PREDICATES.items():
    check(f"{kind}: header digest over all 65536 values == model", DIG.get(kind) == fp.domain_digest(getattr(fp, pred)))
check("244 profile domain: exactly {2}; FROM 244: exactly {0, 2}",
      [v for v in range(0x10000) if fp.reg244_domain_valid(v)] == [2]
      and [v for v in range(0x10000) if fp.from_244_domain_valid(v)] == [0, 2])
check("256-261: exactly 500..8000; 268-273: exactly 0..100; 274-279: exactly {0, 1}",
      [v for v in range(0x10000) if fp.tou_power_domain_valid(v)] == list(range(500, 8001))
      and [v for v in range(0x10000) if fp.soc_domain_valid(v)] == list(range(101))
      and [v for v in range(0x10000) if fp.slot_source_domain_valid(v)] == [0, 1])
pairs = [(a, b) for a in (0, 1, 2, 3, 0x8000, 0xFFFF) for b in (0, 1, 2, 3, 0x8000, 0xFFFF)]
check("244 direction: 0 -> 2 is the ONLY permitted write (header pins the same)",
      [p for p in pairs if fp.reg244_write_permitted(*p)] == [(0, 2)]
      and "return live == 0 && target == REG244_PROFILE_REQUIRED;" in HEADER)
check("CTX / INFO fields are never domain-checked (any word stays VALID once sealed)",
      all(fp.classify_profile(fp.LOAD_OK, fp.seal_profile(dict(GP, **{f: [v] * 6 if f == "reg250_255" else v}))) == fp.PROFILE_VALID
          for f in ("reg232", "reg243", "reg248", "reg250_255", "reg230", "reg245", "reg247") for v in (0, 1, 0xFFFE, 0xFFFF)))
check("header profile_domain_valid reads exactly 244, 256-261, 268-273, 274-279",
      set(re.findall(r"p\.(\w+)", body(r"constexpr bool profile_domain_valid\(const FallbackProfileV1 &p\)")))
      == {"reg244", "reg256_261", "reg268_273", "reg274_279"})

# ===========================================================================
print("[5] Profile classifier: exact precedence, golden cases, exhaustive sweeps")
# ===========================================================================
check("load enum OK=0, ABSENT=1, WRONG_SIZE=2, READ_ERROR=3, STORAGE_UNAVAILABLE=4 (header == model == ecco_durable 0..3)",
      header_enum("LOAD_") == {"LOAD_OK": 0, "LOAD_ABSENT": 1, "LOAD_WRONG_SIZE": 2, "LOAD_READ_ERROR": 3,
                               "LOAD_STORAGE_UNAVAILABLE": 4}
      == {"LOAD_OK": fp.LOAD_OK, "LOAD_ABSENT": fp.LOAD_ABSENT, "LOAD_WRONG_SIZE": fp.LOAD_WRONG_SIZE,
          "LOAD_READ_ERROR": fp.LOAD_READ_ERROR, "LOAD_STORAGE_UNAVAILABLE": fp.LOAD_STORAGE_UNAVAILABLE}
      and {k: int(v) for k, v in re.findall(r"\b(LOAD_(?:OK|ABSENT|WRONG_SIZE|READ_ERROR)) = (\d+),", DURABLE_HEADER)}
      == {"LOAD_OK": 0, "LOAD_ABSENT": 1, "LOAD_WRONG_SIZE": 2, "LOAD_READ_ERROR": 3})
CLASS = {f"PROFILE_{v}": k for k, v in fp.PROFILE_CLASS_NAMES.items()}
check("profile classes UNREADABLE=0 (zero-init fail-closed) .. VALID=5; there is NO SCHEMA_OUTDATED",
      {k: v for k, v in header_enum("PROFILE_").items() if k in CLASS} == CLASS
      and len(CLASS) == 6 and "SCHEMA_OUTDATED" not in HEADER and "SCHEMA_OUTDATED" not in MODEL_TEXT)
PDEF = {f"PROFILE_DEFECT_{v}": k for k, v in fp.PROFILE_DEFECT_NAMES.items()}
check("profile defect codes NONE=0, MAGIC=1, SCHEMA=2, SIZE=3, BINDING=4, RESERVED=5, FLAGS=6, GENERATION=7, DOMAIN=8",
      header_enum("PROFILE_DEFECT_") == PDEF and list(PDEF.values()) == list(range(9)))
check("header profile_defect() rule order is exactly magic, schema, size, binding, reserved, flags, generation, domain",
      body(r"constexpr ProfileDefect profile_defect\(const FallbackProfileV1 &p\)") ==
      "if (p.magic != PROFILE_MAGIC) return PROFILE_DEFECT_MAGIC; if (p.schema != PROFILE_SCHEMA) return PROFILE_DEFECT_SCHEMA; "
      "if (p.size != PROFILE_SIZE) return PROFILE_DEFECT_SIZE; if (p.binding != profile_binding(p)) return PROFILE_DEFECT_BINDING; "
      "if (p.reserved0 != 0 || p.reserved1 != 0) return PROFILE_DEFECT_RESERVED; "
      "if ((p.flags & (uint16_t) ~PROFILE_KNOWN_FLAGS) != 0) return PROFILE_DEFECT_FLAGS; "
      "if (p.generation == 0) return PROFILE_DEFECT_GENERATION; if (!profile_domain_valid(p)) return PROFILE_DEFECT_DOMAIN; "
      "return PROFILE_DEFECT_NONE;")
check("header classify_profile(): load status first, then defect -> CORRUPT_DOMAIN / CORRUPT, then INVALIDATED, else VALID",
      body(r"constexpr ProfileClass classify_profile\(uint8_t load, const FallbackProfileV1 &p\)") ==
      "if (load == LOAD_ABSENT) return PROFILE_NOT_CAPTURED; if (load == LOAD_WRONG_SIZE) return PROFILE_CORRUPT; "
      "if (load != LOAD_OK) return PROFILE_UNREADABLE; const ProfileDefect d = profile_defect(p); "
      "if (d == PROFILE_DEFECT_DOMAIN) return PROFILE_CORRUPT_DOMAIN; if (d != PROFILE_DEFECT_NONE) return PROFILE_CORRUPT; "
      "if (p.flags & PROFILE_FLAG_INVALIDATED) return PROFILE_INVALIDATED; return PROFILE_VALID;")

N = r"(0x[0-9A-Fa-f]+|\d+)"
LOADS = {"LOAD_OK": 0, "LOAD_ABSENT": 1, "LOAD_WRONG_SIZE": 2, "LOAD_READ_ERROR": 3, "LOAD_STORAGE_UNAVAILABLE": 4}


def _load(tok):
    return LOADS[tok] if tok in LOADS else int(tok)


pc_block = re.search(r"constexpr ProfileGoldenCase PROFILE_GOLDEN_CASES\[\] = \{(.*?)\n\};", HEADER, re.S)
PCASES = [(_load(ld), c_int(a), c_int(va), c_int(b), c_int(vb), int(rs), PDEF[df], CLASS[ex])
          for ld, a, va, b, vb, rs, df, ex in
          re.findall(rf"\{{(\w+), {N}, {N}, {N}, {N}, ([01]), (\w+), (\w+)\}}", pc_block.group(1) if pc_block else "")]
check("header profile golden-case table parsed completely",
      pc_block is not None and len(PCASES) == len(re.findall(r"^\s*\{", pc_block.group(1), re.M)) >= 90, str(len(PCASES)))


def mutate(raw: bytes, off_a, val_a, off_b, val_b) -> bytes:
    b = bytearray(raw)
    for off, val in ((off_a, val_a), (off_b, val_b)):
        if off != 0xFF:
            b[off:off + 2] = struct.pack("<H", val)
    return bytes(b)


def run_pcase(m, gp, c):
    load, a, va, b, vb, reseal, _d, _e = c
    p = m.unpack_profile(mutate(m.pack_profile(gp), a, va, b, vb))
    if reseal:
        p = m.seal_profile(p)
    return m.profile_defect(p), m.classify_profile(load, p)


def profile_cases_agree(m) -> bool:
    gp, _gf = golden_records(m)
    return all(run_pcase(m, gp, c) == (c[6], c[7]) for c in PCASES)


bad = [c for c in PCASES if run_pcase(fp, GP, c) != (c[6], c[7])]
check(f"all {len(PCASES)} C++ profile golden cases: the model gives the same defect AND class", not bad, str(bad[:4]))
check("the table exercises every defect code and every class",
      {c[6] for c in PCASES} == set(PDEF.values()) and {c[7] for c in PCASES} == set(CLASS.values()))
every_load = {ld: fp.classify_profile(ld, GP) for ld in range(256)}
check("ONLY a proven ABSENT load is NOT_CAPTURED (all 256 load values)",
      [ld for ld, c in every_load.items() if c == fp.PROFILE_NOT_CAPTURED] == [fp.LOAD_ABSENT])
check("READ_ERROR, STORAGE_UNAVAILABLE and every unknown value (5..255) are UNREADABLE; WRONG_SIZE is CORRUPT",
      all(every_load[ld] == fp.PROFILE_UNREADABLE for ld in (3, 4, *range(5, 256)))
      and every_load[fp.LOAD_WRONG_SIZE] == fp.PROFILE_CORRUPT)
check("bytes are never inspected unless load == OK (a None record is accepted for every non-OK load)",
      all(fp.classify_profile(ld, None) == every_load[ld] for ld in range(1, 256)))
WORD_DEFECT = {0: fp.PROFILE_DEFECT_MAGIC, 2: fp.PROFILE_DEFECT_MAGIC, 4: fp.PROFILE_DEFECT_SCHEMA, 6: fp.PROFILE_DEFECT_SIZE}
check("ANY single corrupted word in [0,88) without a re-seal is CORRUPT - 44/44 words (MAGIC/SCHEMA/SIZE for words 0-3, "
      "BINDING for every later word)",
      all(run_pcase(fp, GP, (0, off, struct.unpack_from("<H", gp_bytes, off)[0] ^ 0x0101, 0xFF, 0, 0, 0, 0))
          == (WORD_DEFECT.get(off, fp.PROFILE_DEFECT_BINDING), fp.PROFILE_CORRUPT) for off in range(0, 88, 2)))
check("flags: every value other than 0 (VALID) and 1 (INVALIDATED) is CORRUPT (all 65536)",
      all(run_pcase(fp, GP, (0, 16, v, 0xFF, 0, 1, 0, 0))[1] == (fp.PROFILE_VALID if v == 0 else fp.PROFILE_INVALIDATED if v == 1
                                                                 else fp.PROFILE_CORRUPT) for v in range(0x10000)))
check("schema: every value other than 1 is SCHEMA (no migration under the v1 tag); size: every value other than 96 is SIZE",
      all(run_pcase(fp, GP, (0, 4, v, 0xFF, 0, 1, 0, 0))[0] == (fp.PROFILE_DEFECT_NONE if v == 1 else fp.PROFILE_DEFECT_SCHEMA)
          for v in range(0x10000))
      and all(run_pcase(fp, GP, (0, 6, v, 0xFF, 0, 1, 0, 0))[0] == (fp.PROFILE_DEFECT_NONE if v == 96 else fp.PROFILE_DEFECT_SIZE)
              for v in range(0x10000)))
check("every one of the six slots of 256-261 / 268-273 / 274-279 is checked at both edges",
      all(run_pcase(fp, GP, (0, base + 2 * s, ok, 0xFF, 0, 1, 0, 0))[1] == fp.PROFILE_VALID
          and run_pcase(fp, GP, (0, base + 2 * s, bad_v, 0xFF, 0, 1, 0, 0))[1] == fp.PROFILE_CORRUPT_DOMAIN
          for s in range(6) for base, ok, bad_v in ((20, 500, 499), (20, 8000, 8001), (32, 100, 101), (44, 1, 2))))
check("all-zero and all-0xFF stored profiles are CORRUPT", fp.classify_profile(0, bytes(96)) == fp.PROFILE_CORRUPT
      and fp.classify_profile(0, b"\xff" * 96) == fp.PROFILE_CORRUPT)

# ===========================================================================
print("[6] Generation and INVALIDATE")
# ===========================================================================
inv = fp.invalidate_profile(GP)
inv_bytes = fp.pack_profile(inv)
check("INVALIDATE preserves the payload verbatim: only generation, flags and binding differ (bytes 0-7, 12-15, 18-87 identical)",
      [f for f in GP if GP[f] != inv[f]] == ["generation", "flags", "binding"]
      and gp_bytes[:8] == inv_bytes[:8] and gp_bytes[12:16] == inv_bytes[12:16] and gp_bytes[18:88] == inv_bytes[18:88])
check("INVALIDATE advances the generation by exactly 1 and sets only the INVALIDATED bit",
      inv["generation"] == GP["generation"] + 1 and inv["flags"] == GP["flags"] | 1
      and fp.classify_profile(fp.LOAD_OK, inv) == fp.PROFILE_INVALIDATED)
check("INVALIDATED is one-way: an INVALIDATED record may not be invalidated again (only a fresh CAPTURE restores VALID)",
      not fp.profile_invalidate_permitted(inv) and fp.profile_invalidate_permitted(GP))
check("INVALIDATE of a CORRUPT / CORRUPT_DOMAIN record, or at generation 0xFFFFFFFF, is not permitted",
      not fp.profile_invalidate_permitted(fp.seal_profile(dict(GP, reg244=0)))
      and not fp.profile_invalidate_permitted(dict(GP, binding=0))
      and not fp.profile_invalidate_permitted(fp.seal_profile(dict(GP, generation=0xFFFFFFFF)))
      and fp.profile_invalidate_permitted(fp.seal_profile(dict(GP, generation=0xFFFFFFFE))))
check("generation strictly increases on every commit (advance(prev, next) iff next > prev); generation 0 is CORRUPT",
      all(fp.profile_generation_advances(a, b) == (b > a) for a in (0, 1, 7, 0xFFFFFFFE) for b in (0, 1, 7, 8, 0xFFFFFFFF))
      and run_pcase(fp, GP, (0, 8, 0, 10, 0, 1, 0, 0))[0] == fp.PROFILE_DEFECT_GENERATION)
check("header pins INVALIDATE semantics and the generation rule at compile time",
      '"FB-A: INVALIDATE advances the generation and is one-way"' in HEADER
      and '"FB-A: every profile commit strictly increases the generation"' in HEADER
      and body(r"constexpr FallbackProfileV1 invalidate_profile\(FallbackProfileV1 p\)")
      == "p.generation = p.generation + 1; p.flags = (uint16_t) (p.flags | PROFILE_FLAG_INVALIDATED); return seal_profile(p);")
check("the header documents generation as one logical counter shared across schema versions",
      "it is ONE logical counter shared across schema versions" in HEADER)

# ===========================================================================
print("[7] Failback record: codes, flags, apply_committed, CLEAR contract, classifier")
# ===========================================================================
check("states CLEAR=0, PREEMPT_REQUIRED=1, APPLY_IN_PROGRESS=2, LATCHED_COMPLETE=3, BLOCKED=4 (explicit numbers)",
      {k: v for k, v in header_enum("FAILBACK_").items() if k[9:] in fp.FAILBACK_STATE_NAMES.values()}
      == {f"FAILBACK_{v}": k for k, v in fp.FAILBACK_STATE_NAMES.items()})
check("reasons NONE=0, SUPERVISION_LOST=1, OPERATOR_APPLY=2 (explicit numbers, header == model)",
      header_enum("FAILBACK_REASON_") == {f"FAILBACK_REASON_{v}": k for k, v in fp.FAILBACK_REASON_NAMES.items()})
check("results NONE=0; LATCHED 1-4 (PREEMPTED_ONLY, PREEMPTED_NO_PROFILE, ALREADY_AT_PROFILE, APPLIED_VERIFIED); BLOCKED 5-11",
      header_enum("FAILBACK_RESULT_") == {f"FAILBACK_RESULT_{v}": k for k, v in fp.FAILBACK_RESULT_NAMES.items()}
      and fp.LATCHED_RESULTS == (1, 2, 3, 4) and fp.BLOCKED_RESULTS == tuple(range(5, 12)))
enum_bodies = re.findall(r"enum \w+ : uint8_t \{(.*?)\};", CODE, re.S)
check("every enumerator of every durable enum has an explicit numeric value (no implicit numbering)",
      enum_bodies and all(re.fullmatch(r"\s*[A-Z_0-9]+ = \d+,\s*", ln + ",") or not ln.strip()
                          for eb in enum_bodies for ln in eb.split(",")))
check("flags: bit0 lease_preempted, bit1 apply_committed, bit2 divergence_reboot_used; bits 3-7 unknown",
      (header_u("FAILBACK_FLAG_LEASE_PREEMPTED"), header_u("FAILBACK_FLAG_APPLY_COMMITTED"),
       header_u("FAILBACK_FLAG_DIVERGENCE_REBOOT_USED")) == (1, 2, 4) == (fp.FAILBACK_FLAG_LEASE_PREEMPTED,
                                                                          fp.FAILBACK_FLAG_APPLY_COMMITTED,
                                                                          fp.FAILBACK_FLAG_DIVERGENCE_REBOOT_USED)
      and fp.FAILBACK_KNOWN_FLAGS == 7 and "fallback_write_started" not in HEADER and "fallback_write_started" not in MODEL_TEXT)
FDEF = {f"FAILBACK_DEFECT_{n}": i for i, n in enumerate(("NONE", "MAGIC", "SCHEMA", "SIZE", "BINDING", "FLAGS", "STATE",
                                                          "REASON", "RESULT", "INVARIANT"))}
check("failback defect codes NONE..INVARIANT = 0..9 (header == model)", header_enum("FAILBACK_DEFECT_") == FDEF
      and all(getattr(fp, k) == v for k, v in FDEF.items()))
RCLASS = {f"FAILBACK_RECORD_{v}": k for k, v in fp.FAILBACK_RECORD_NAMES.items()}
check("failback record classes UNREADABLE=0, ABSENT=1, CORRUPT=2, VALID=3", header_enum("FAILBACK_RECORD_") == RCLASS)
check("header failback_defect() order: magic, schema, size, binding, flags, state, reason, result, invariants",
      body(r"constexpr FailbackDefect failback_defect\(const FailbackStateV1 &s\)") ==
      "if (s.magic != FAILBACK_MAGIC) return FAILBACK_DEFECT_MAGIC; if (s.schema != FAILBACK_SCHEMA) return FAILBACK_DEFECT_SCHEMA; "
      "if (s.size != FAILBACK_SIZE) return FAILBACK_DEFECT_SIZE; if (s.binding != failback_binding(s)) return FAILBACK_DEFECT_BINDING; "
      "if ((s.flags & (uint8_t) ~FAILBACK_KNOWN_FLAGS) != 0) return FAILBACK_DEFECT_FLAGS; "
      "if (s.state > FAILBACK_BLOCKED) return FAILBACK_DEFECT_STATE; if (s.reason > FAILBACK_REASON_MAX) return FAILBACK_DEFECT_REASON; "
      "if (s.result > FAILBACK_RESULT_MAX) return FAILBACK_DEFECT_RESULT; "
      "if (!failback_invariants_hold(s)) return FAILBACK_DEFECT_INVARIANT; return FAILBACK_DEFECT_NONE;")
check("header classify_failback(): ABSENT, WRONG_SIZE -> CORRUPT, non-OK -> UNREADABLE, then defect",
      body(r"constexpr FailbackRecordClass classify_failback\(uint8_t load, const FailbackStateV1 &s\)") ==
      "if (load == LOAD_ABSENT) return FAILBACK_RECORD_ABSENT; if (load == LOAD_WRONG_SIZE) return FAILBACK_RECORD_CORRUPT; "
      "if (load != LOAD_OK) return FAILBACK_RECORD_UNREADABLE; "
      "return failback_defect(s) == FAILBACK_DEFECT_NONE ? FAILBACK_RECORD_VALID : FAILBACK_RECORD_CORRUPT;")

fc_block = re.search(r"constexpr FailbackGoldenCase FAILBACK_GOLDEN_CASES\[\] = \{(.*?)\n\};", HEADER, re.S)
FCASES = [(int(bs), _load(ld), c_int(a), c_int(va), c_int(b), c_int(vb), int(rs), FDEF[df], RCLASS[ex])
          for bs, ld, a, va, b, vb, rs, df, ex in
          re.findall(rf"\{{(\d), (\w+), {N}, {N}, {N}, {N}, ([01]), (\w+), (\w+)\}}", fc_block.group(1) if fc_block else "")]
check("header failback golden-case table parsed completely",
      fc_block is not None and len(FCASES) == len(re.findall(r"^\s*\{", fc_block.group(1), re.M)) >= 90, str(len(FCASES)))


def run_fcase(m, gf, c):
    base, load, a, va, b, vb, reseal, _d, _e = c
    s = m.unpack_failback(mutate(m.pack_failback(gf[base]), a, va, b, vb))
    if reseal:
        s = m.seal_failback(s)
    return m.failback_defect(s), m.classify_failback(load, s)


def failback_cases_agree(m) -> bool:
    _gp, gf = golden_records(m)
    return all(run_fcase(m, gf, c) == (c[7], c[8]) for c in FCASES)


fbad = [c for c in FCASES if run_fcase(fp, GF, c) != (c[7], c[8])]
check(f"all {len(FCASES)} C++ failback golden cases: the model gives the same defect AND class", not fbad, str(fbad[:4]))
check("the failback table exercises every defect code, every class and every base record",
      {c[7] for c in FCASES} == set(FDEF.values()) and {c[8] for c in FCASES} == set(RCLASS.values())
      and {c[0] for c in FCASES} == set(range(6)))
every_fload = {ld: fp.classify_failback(ld, None if ld != 0 else GF[0]) for ld in range(256)}
check("failback: ABSENT is ABSENT, never a (valid) CLEAR record; a present CLEAR record is VALID",
      every_fload[fp.LOAD_ABSENT] == fp.FAILBACK_RECORD_ABSENT and every_fload[fp.LOAD_OK] == fp.FAILBACK_RECORD_VALID
      and GF[0]["state"] == fp.FAILBACK_CLEAR)
check("failback: WRONG_SIZE CORRUPT; READ_ERROR, STORAGE_UNAVAILABLE, 5..255 UNREADABLE; bytes never inspected unless OK",
      every_fload[2] == fp.FAILBACK_RECORD_CORRUPT and all(every_fload[ld] == fp.FAILBACK_RECORD_UNREADABLE for ld in range(3, 256)))
check("state / reason / result: exactly 0..4 / 0..2 / 0..11 pass the range checks (all 256 values each)",
      [v for v in range(256) if fp.failback_defect(fp.seal_failback(dict(GF[2], state=v))) != fp.FAILBACK_DEFECT_STATE] == list(range(5))
      and [v for v in range(256) if fp.failback_defect(fp.seal_failback(dict(GF[2], reason=v))) != fp.FAILBACK_DEFECT_REASON] == [0, 1, 2]
      and [v for v in range(256) if fp.failback_defect(fp.seal_failback(dict(GF[2], result=v))) != fp.FAILBACK_DEFECT_RESULT] == list(range(12)))
check("flags: exactly the 8 combinations of bits 0-2 pass the flag check (all 256 values)",
      [v for v in range(256) if fp.failback_defect(fp.seal_failback(dict(GF[2], flags=v))) != fp.FAILBACK_DEFECT_FLAGS] == list(range(8)))


def valid(rec) -> bool:
    return fp.failback_defect(fp.seal_failback(rec)) == fp.FAILBACK_DEFECT_NONE


apply_rec, pre_rec = GF[2], GF[1]
check("APPLY_IN_PROGRESS requires apply_committed", not valid(dict(apply_rec, flags=0x01)) and valid(apply_rec)
      and not valid(dict(pre_rec, state=fp.FAILBACK_APPLY_IN_PROGRESS)))
check("all from_* == 0 iff apply_committed is clear (both directions)",
      not valid(dict(pre_rec, from_256_261=[3000] + [0] * 5)) and not valid(dict(pre_rec, from_244=2))
      and not valid(dict(apply_rec, from_244=0, from_256_261=[0] * 6, from_268_279=[0] * 12)))
check("with apply_committed: from_244 in {0,2}, 256-261 in 500..8000, 268-273 <= 100, 274-279 bits outside bit0 zero",
      [v for v in (0, 1, 2, 3) if valid(dict(apply_rec, from_244=v))] == [0, 2]
      and [v for v in (499, 500, 8000, 8001) if valid(dict(apply_rec, from_256_261=[v] * 6))] == [500, 8000]
      and [v for v in (100, 101) if valid(dict(apply_rec, from_268_279=[v] * 6 + [0] * 6))] == [100]
      and [v for v in (0, 1, 2, 3, 0x40, 0x8000) if valid(dict(apply_rec, from_268_279=[50] * 6 + [v] * 6))] == [0, 1])
check("apply_committed requires a bound profile; apply counters require apply_committed",
      not valid(dict(apply_rec, profile_generation=0, profile_binding=0))
      and not valid(dict(pre_rec, apply_attempts=1)) and not valid(dict(pre_rec, verify_mismatches=1)))
check("retry never recaptures FROM: capture permitted iff apply_committed is clear (every flag combination)",
      all(fp.failback_from_capture_permitted(dict(apply_rec, flags=f)) == (not f & 2) for f in range(8))
      and '"FB-A: no FROM recapture once apply_committed is set"' in HEADER)
check("profile_generation == 0 iff profile_binding == 0 (no profile bound), in every state",
      all(not valid(dict(r, profile_generation=0)) for r in GF[1:5])
      and not valid(dict(GF[5], profile_generation=1)) and not valid(dict(GF[5], profile_binding=1))
      and valid(dict(GF[5], profile_generation=1, profile_binding=1)))
clear = fp.failback_clear_record(1234)
check("CLEAR contract: the canonical CLEAR record keeps only event_seq; every episode field is zero; it is VALID",
      valid(clear) and clear["event_seq"] == 1234
      and all(clear[f] in (0, [0] * 6, [0] * 12) for f in clear if f not in ("magic", "schema", "size", "event_seq", "binding")))
check("CLEAR contract: any retained reason/result/flag/epoch/profile/counter/FROM makes a CLEAR record CORRUPT",
      all(not valid(dict(clear, **{f: v})) for f, v in (("reason", 1), ("result", 4), ("flags", 1), ("flags", 2), ("flags", 4),
                                                         ("event_epoch", 1), ("profile_generation", 1), ("profile_binding", 1),
                                                         ("apply_attempts", 1), ("verify_mismatches", 1), ("from_244", 2),
                                                         ("from_256_261", [500] * 6))))
check("non-CLEAR records need a reason and event_seq >= 1; LATCHED needs a latched result with apply_committed iff "
      "APPLIED_VERIFIED; BLOCKED needs a blocked result; PREEMPT/APPLY carry no result",
      not valid(dict(pre_rec, reason=0)) and not valid(dict(pre_rec, event_seq=0))
      and [r for r in range(12) if valid(dict(GF[4], state=3, result=r))] == [1, 2, 3]
      and [r for r in range(12) if valid(dict(GF[3], result=r))] == [4]
      and [r for r in range(12) if valid(dict(GF[4], result=r))] == list(range(5, 12))
      and [r for r in range(12) if valid(dict(apply_rec, result=r))] == [0] and [r for r in range(12) if valid(dict(pre_rec, result=r))] == [0])
check("the header documents the CLEAR contract and apply_committed semantics",
      "CLEAR contract: a CLEAR record carries ONLY event_seq" in HEADER
      and "set in the SAME durable commit that enters\n//                           APPLY_IN_PROGRESS and stores from_*, BEFORE any" in HEADER)

# ===========================================================================
print("[8] Tags and preference keys (independent inventory, both hash algorithms)")
# ===========================================================================
# FB-T0 hardening (Cloud B red-team): the inventory no longer depends on ONE declaration style. registry/tests/_tag_inventory.py
# finds every string constant in every header - any spacing, pointer / array / sized-array form, std::string_view, wrapped or
# concatenated literals, #define, and names that do not end `_TAG` - whose name mentions "tag" or whose value follows the repo's
# `ecco_<words>_v<N>` durable-tag convention. The OLD regex is kept below only as an INDEPENDENT second implementation that must
# agree on the pre-existing headers; a separate literal scan proves no durable-looking string literal escapes the accounting.
LEGACY_TAG_DECL = re.compile(r'constexpr (?:const )?char (?:\*\s*)?([A-Z0-9_]+_TAG(?:_V\d+)?)(?:\[\])? = "([^"]+)";')
TAGS = ti.all_declared_tags(INCLUDE_DIR)
# FB-T0: headers a LATER chain entry declares it added (registry/tests/_scope_chain.py `added_files`) are not part of the
# pre-existing inventory this suite pinned; their tags are "later" tags, still subject to the global collision check below.
_LATER_HEADERS = {Path(f).name for f in chain.CHAIN.declared_added_files() if f.startswith("firmware/include/")}
existing = {k: v for k, v in TAGS.items() if not k.startswith("ecco_fallback_profile.h:") and k.split(":")[0] not in _LATER_HEADERS}
later = {k: v for k, v in TAGS.items() if k.split(":")[0] in _LATER_HEADERS and not k.startswith("ecco_fallback_profile.h:")}
new = {k.split(":")[1]: v for k, v in TAGS.items() if k.startswith("ecco_fallback_profile.h:")}


def keys_distinct(m) -> bool:
    """Every existing *_TAG string (any header, any namespace), every documented prospective tag and the two FB-A
    tags: no duplicate string and no duplicate preference key."""
    # FB-T0: LIVE tree - every pre-existing tag, every tag a later chain entry declares in its own headers, every documented
    # prospective tag NOT yet promoted by a chain entry (a promoted one is counted once, as a later tag), and the two FB-A tags.
    strings = (list(existing.values()) + list(later.values())
               + [s for s in m.PROSPECTIVE_TAGS if s not in chain.CHAIN.declared_promoted_tags()]
               + [m.FALLBACK_PROFILE_TAG, m.FAILBACK_STATE_TAG])
    return not ti.collision_problems(strings, m.tag_key_fnv1_32)


durable_tag_strings = {v for k, v in existing.items() if k.startswith("ecco_durable_snapshot.h:")}
check("independent inventory (every header, every namespace) finds the 13 durable tag strings (9 active + 4 retired: "
      "Free Power V1-V3 and, since Dump V2, Dump data V1 - whose V2 tag is the ACTIVE one) plus "
      "ecco_recovery_evidence.h's FINGERPRINT_DOMAIN_TAG; all are included in the collision check",
      len(durable_tag_strings) == 13 and set(existing.values()) - durable_tag_strings == {"ECCO-FP-RECOVERY-EVIDENCE-v1"})
check("the FB-A header declares exactly FALLBACK_PROFILE_TAG / FAILBACK_STATE_TAG (header == model)",
      new == {"FALLBACK_PROFILE_TAG": "ecco_fallback_profile_v1", "FAILBACK_STATE_TAG": "ecco_failback_state_v1"}
      == {"FALLBACK_PROFILE_TAG": fp.FALLBACK_PROFILE_TAG, "FAILBACK_STATE_TAG": fp.FAILBACK_STATE_TAG})
check("preference keys (ESPHome 32-bit FNV-1 of the tag) of every existing, new and prospective tag are pairwise distinct",
      keys_distinct(fp), str({v: hex(fp.tag_key_fnv1_32(v)) for v in sorted(set(TAGS.values()))}))
_inc_texts = {h.name: h.read_text(encoding="utf-8") for h in sorted(INCLUDE_DIR.glob("*.h"))}
_legacy = {f"{n}:{name}": v for n, tx in _inc_texts.items() for name, v in LEGACY_TAG_DECL.findall(tx)
           if n not in _LATER_HEADERS or n == "ecco_fallback_profile.h"}
_robust_pre = {k: v for k, v in TAGS.items() if k.split(":")[0] not in _LATER_HEADERS or k.startswith("ecco_fallback_profile.h:")}
check("the hardened inventory and the ORIGINAL single-style regex (an independent second implementation) agree exactly on every "
      "pre-existing header and the FB-A header (16 declarations: 13 durable + 1 evidence domain tag + the 2 FB-A tags)",
      _legacy == _robust_pre and len(_legacy) == 16, f"{sorted(set(_legacy.items()) ^ set(_robust_pre.items()))}")
_all_values = set(TAGS.values())
_lost = {n: sorted(ti.unaccounted_literals(tx, _all_values)) for n, tx in _inc_texts.items() if ti.unaccounted_literals(tx, _all_values)}
check("no durable-looking string literal (`ecco_<words>_v<N>`) in ANY firmware/include header - declared or used any other way - "
      "escapes the inventory, so none can escape the collision accounting", not _lost, str(_lost))
_later_headers = {n: tx for n, tx in _inc_texts.items() if n in _LATER_HEADERS and n != "ecco_fallback_profile.h"}
_problems = ti.check_later_headers(_later_headers, chain.CHAIN.declared_tags(), chain.CHAIN.declared_promoted_tags(),
                                   existing.values(), fp.PROSPECTIVE_TAGS, (fp.FALLBACK_PROFILE_TAG, fp.FAILBACK_STATE_TAG),
                                   fp.tag_key_fnv1_32)
check("tags declared by headers LATER chain entries add are EXACTLY the set those entries declare (a wrong string such as "
      "ecco_failback_provision_v2, a missing or an extra tag fails), every promoted prospective tag is really declared, and "
      "over existing + later + unpromoted-prospective + FB-A tags there is no duplicate string and no 32-bit key collision "
      "(none today: no later entry declares a tag)", _problems == [], str(_problems))
check("the chain declares no tag the headers do not (no stale declaration)",
      chain.CHAIN.declared_tags() == {v for k, v in later.items()}, str(sorted(chain.CHAIN.declared_tags() ^ set(later.values()))))
check("the new tag strings differ from every existing / retired / prospective tag string",
      not set(new.values()) & (set(existing.values()) | set(fp.PROSPECTIVE_TAGS)))
check("known answers: FNV-1 32 ('')=0x811C9DC5, ('a')=0x050C5D7E, ('foobar')=0x31F0B262",
      (fp.fnv1_32(""), fp.fnv1_32("a"), fp.fnv1_32("foobar")) == (0x811C9DC5, 0x050C5D7E, 0x31F0B262))
check("known answers: FNV-1a-64 ('')=0xCBF29CE484222325, ('a')=0xAF63DC4C8601EC8C, ('foobar')=0x85944171F73967E8",
      (fp.fnv1a_64(b""), fp.fnv1a_64(b"a"), fp.fnv1a_64(b"foobar")) == (0xCBF29CE484222325, 0xAF63DC4C8601EC8C, 0x85944171F73967E8))
check("the header pins the same known answers for both algorithms and the two new keys at compile time",
      all(s in HEADER for s in ('== 0x811C9DC5u, "FNV-1 32 known answer', '== 0x050C5D7Eu, "FNV-1 32 known answer',
                                '== 0x31F0B262u, "FNV-1 32 known answer', '== 0xAF63DC4C8601EC8CULL, "FNV-1a-64 known answer',
                                '== 0x85944171F73967E8ULL, "FNV-1a-64 known answer',
                                f'tag_key_fnv1_32(FALLBACK_PROFILE_TAG) == 0x{fp.tag_key_fnv1_32(fp.FALLBACK_PROFILE_TAG):08X}u',
                                f'tag_key_fnv1_32(FAILBACK_STATE_TAG) == 0x{fp.tag_key_fnv1_32(fp.FAILBACK_STATE_TAG):08X}u')))
check("the key replica is ESPHome's fnv1_hash as ecco_durable::key_for() uses it (multiply, then xor)",
      "inline uint32_t key_for(const char *tag) { return esphome::fnv1_hash(tag); }" in DURABLE_HEADER
      and "hash *= FNV1_32_PRIME;\n    hash ^= (uint8_t) *tag;" in HEADER)
check("the FB-A magics differ from every existing durable magic ('ECCV', 'ECSJ') and each other",
      len({fp.PROFILE_MAGIC, fp.FAILBACK_MAGIC, 0x45434356, 0x4543534A}) == 4
      and "VALID_MARKER_MAGIC = 0x45434356u" in DURABLE_HEADER and "FREE_POWER_START_JOURNAL_MAGIC = 0x4543534Au" in DURABLE_HEADER)
# FB-T0: pinned as of chain entry dump_v2; a later entry's declared tokens are reverted exactly first, and the live count of
# FB-A tag references is covered by [9]'s "live banned-token occurrences == declared" check.
_SCOPE_FW_TEXT_8 = chain.CHAIN.as_of(chain.FIRMWARE, "dump_v2", FW_TEXT)
fw_tags = set(re.findall(r"ecco_durable::([A-Za-z0-9_]+_TAG)\b", _SCOPE_FW_TEXT_8))
check("ACTIVE durable tags unchanged: the firmware (as of chain entry dump_v2) still references exactly the 9 ecco_durable "
      "tags and no FB-A tag",
      len(fw_tags) == 9 and not any(t in _SCOPE_FW_TEXT_8 for t in list(new) + list(new.values())))

# ===========================================================================
print("[9] Change scope: FB-A adds no production behaviour")
# ===========================================================================
# FB-T0: every pin here is CHAIN-RELATIVE (registry/tests/_scope_chain.py). The chain is, in merge order on main:
#     root (004040b) -> fba (#54, this PR) -> mtou1 (#53) -> dump_v2 (#52) -> [later PRs, appended by their own entries]
# as_of(artifact, entry, live) undoes every entry NEWER than `entry` with exact-match reverters, newest first, so:
#   * "FB-A leaves X byte-identical to 004040b" is pinned on as_of(X, "fba"): a later PR's declared edits never re-hash it,
#     an undeclared edit still breaks it;
#   * the counts / include list / banned-token scan are pinned as of "dump_v2" (the state they were written against) AND the
#     live tree must equal that state plus exactly the deltas later entries DECLARE (live == as-of + declared).
# Nothing here is a re-hash of the current tree: BASE_SHA / POST_MTOU1_FIRMWARE_SHA are the hashes of main @ 004040b / @ 37f9958.
CH = chain.CHAIN
FW_TEXT_FBA = CH.as_of(chain.FIRMWARE, "fba", FW_TEXT)          # == main @ 004040b (FB-A edited no firmware)
SCOPE_FW_TEXT = CH.as_of(chain.FIRMWARE, "dump_v2", FW_TEXT)    # == main @ ca7474e, the state the count pins were written against
for rel, want in BASE_SHA.items():
    check(f"{rel} is byte-identical to main @ 004040b (as of chain entry fba: every later entry's declared edits reverted exactly)",
          sha(CH.as_of(rel, "fba", (ROOT / rel).read_text(encoding="utf-8"))) == want)
check("FB-A itself declares NO edit to any chain-pinned artifact (firmware YAML, durable header, evidence header, "
      "inverter_capabilities, transaction_state_machine, ha-manifest): no reverters, and every pinned artifact as of fba is "
      "main @ 004040b's", CH.entry("fba").reverts == {} and all(
          sha(CH.as_of(p, "fba", (ROOT / p).read_text(encoding="utf-8"))) == chain.ROOT_SHA[p] for p in chain.PINNED))
check(f"{chain.FIRMWARE} as of fba is byte-identical to main @ 004040b (FB-A adds nothing to the firmware)",
      sha(FW_TEXT_FBA) == chain.ROOT_SHA[chain.FIRMWARE] == dv2s.BASE_FIRMWARE_SHA)
for rel, want in POST_MTOU1_FIRMWARE_SHA.items():
    check(f"{rel} as of chain entry mtou1 is pinned to the main + Manual TOU Phase 1 (PR #53) content (FB-A itself leaves "
          "it untouched; Dump V2's and every later entry's edits reverted exactly)",
          sha(CH.as_of(chain.FIRMWARE, "mtou1", FW_TEXT)) == want)
_FIRMWARE_CHECKPOINT = {e.id: e.checkpoints.get(chain.FIRMWARE) for e in CH.entries}
check("the chain's recorded checkpoint for Manual TOU Phase 1 is that same hash (one source of truth)",
      _FIRMWARE_CHECKPOINT["mtou1"] == POST_MTOU1_FIRMWARE_SHA[chain.FIRMWARE])
FW = ds.load_firmware(FIRMWARE_PATH)
FW_SCOPE = ds.load_firmware_text(SCOPE_FW_TEXT)
FW_PRE_DUMP_V2_TEXT = dv2s.pre_dump_v2_firmware(SCOPE_FW_TEXT)
FW_PRE_DUMP_V2 = ds.load_firmware_text(FW_PRE_DUMP_V2_TEXT)
check("the FB-A header is NOT in esphome.includes as of dump_v2 (exactly the two pre-existing headers), and the live include "
      "list is that plus exactly the includes later chain entries declare",
      FW_SCOPE["esphome"]["includes"] == ["include/ecco_durable_snapshot.h", "include/ecco_recovery_evidence.h"]
      and FW["esphome"]["includes"] == FW_SCOPE["esphome"]["includes"] + list(CH.declared_includes("dump_v2")),
      str(FW["esphome"]["includes"]))
SCAN_DIRS = ("firmware", "registry", "tools", "home-assistant", "frontend", "deployment", "health", "influxdb", ".github")
TEXT_SUFFIXES = {".h", ".hpp", ".c", ".cpp", ".yaml", ".yml", ".py", ".ts", ".js", ".json", ".ps1", ".psm1", ".sh", ".jinja"}


def repo_files():
    for d in SCAN_DIRS:
        base = ROOT / d
        if base.is_dir():
            for p in base.rglob("*"):
                if p.is_file() and p.suffix in TEXT_SUFFIXES and ".esphome" not in p.parts and "node_modules" not in p.parts:
                    yield p


FB_A_TESTS = {"registry/tests/test_fallback_profile_schema.py", "registry/tests/test_fallback_profile_host_compile.py"}
includers = [p.relative_to(ROOT).as_posix() for p in repo_files()
             if p.relative_to(ROOT).as_posix() not in FB_A_TESTS and re.search(r'#\s*include\s*[<"][^>"]*ecco_fallback_profile\.h|-\s*include/ecco_fallback_profile\.h',
                          p.read_text(encoding="utf-8", errors="ignore"))]
check("no production or pre-existing file includes the FB-A header (no #include, no YAML includes entry); only the "
      "host-compile test's temporary TU does - since FB-T0, exactly the files chain entries DECLARE as includers "
      "(an undeclared includer still fails, and a declared one that no longer includes it fails too)",
      set(includers) == CH.declared_includers() - FB_A_TESTS, str(sorted(set(includers) ^ (CH.declared_includers() - FB_A_TESTS))))
check("the chain's fba entry declares exactly the two FB-A suites as includers (they are this scan's only exclusions)",
      CH.entry("fba").fbh_includers == FB_A_TESTS)
BANNED = re.compile(r"ecco_fallback|FALLBACK_PROFILE|FAILBACK_STATE|ecco_failback")
leaks = [p.relative_to(ROOT).as_posix() for d in ("home-assistant", "frontend", "deployment") if (ROOT / d).is_dir()
         for p in (ROOT / d).rglob("*") if p.is_file() and BANNED.search(p.read_text(encoding="utf-8", errors="ignore"))]
# FB-T0: the rule is NOT broadened - the same four tokens, the same four places. As of chain entry dump_v2 there is none
# (and FB-A declares none); a LATER PR may add them only where its chain entry DECLARES them: an exact occurrence count in the
# firmware YAML (live count == the sum of declared counts) and an exact file allowlist for home-assistant/, frontend/,
# deployment/ (live leak set == the declared set). An undeclared token anywhere still fails.
check("no ecco_fallback / FALLBACK_PROFILE / FAILBACK_STATE / ecco_failback reference in the firmware YAML as of chain "
      "entry dump_v2 (FB-A adds none; every later entry's declared tokens reverted exactly), home-assistant/, frontend/ or "
      "deployment/ beyond the files entries declare",
      chain.BANNED.pattern == BANNED.pattern and not BANNED.search(SCOPE_FW_TEXT) and CH.declared_banned_fw("dump_v2") == 0
      and all(not CH.entry(e).banned_files for e in ("fba", "mtou1", "dump_v2")) and set(leaks) == CH.declared_banned_files(),
      str(sorted(set(leaks) ^ CH.declared_banned_files())))
# FB-B3 (final integration): the four-token rule is NOT weakened. Only `ecco_fallback` may appear under home-assistant/ or deployment/, and only in the
# exact files an entry declares; FALLBACK_PROFILE, FAILBACK_STATE and ecco_failback stay banned in every one of those places, and frontend/ carries no
# token at all (no new fallback control logic in the frontend). Tokens are assembled here so this file never trips the scan itself.
STRICT = ("FALLBACK" + "_PROFILE", "FAILBACK" + "_STATE", "ecco_" + "failback")
# FB-C3 (BLK-46, the token-ban amendment FINAL 2.2 requires before FB-C3 may merge): FALLBACK_PROFILE and FAILBACK_STATE stay banned EVERYWHERE under
# those three directories, and `ecco_failback` stays banned everywhere EXCEPT one exact place: the status package, and only in the form of the FIVE
# existing firmware shadow entity ids (sensor.<device slug>_ecco_failback_shadow_<state|episode|soak|verdict|inputs>) its read-only decoder reads. Any
# other occurrence (a sixth id, a different file, the dashboard, a package, frontend/) is still a leak.
SHADOW_ID_FILES = frozenset({"home-assistant/packages/ecco_fallback_status.yaml"})
SHADOW_ID_RE = re.compile(r"sensor\.ecco_clock_dongle_ecco_failback_shadow_(?:state|episode|soak|verdict|inputs)(?![a-z0-9_])")


def strict_hits(rel: str, text: str) -> list:
    if rel in SHADOW_ID_FILES:
        text = SHADOW_ID_RE.sub("", text)
    return [tok for tok in STRICT if tok in text]


strict_leaks = [(p.relative_to(ROOT).as_posix(), tok) for d in ("home-assistant", "frontend", "deployment") if (ROOT / d).is_dir()
                for p in (ROOT / d).rglob("*") if p.is_file() and "node_modules" not in p.parts
                for tok in strict_hits(p.relative_to(ROOT).as_posix(), p.read_text(encoding="utf-8", errors="ignore"))]
check("FB-B3 / FB-C3: FALLBACK_PROFILE, FAILBACK_STATE and ecco_failback occur NOWHERE under home-assistant/, frontend/ or deployment/ except the five shadow "
      "entity ids in the status package (the rule is narrowed to exactly that, not weakened)",
      not strict_leaks, str(strict_leaks))
_status_rel = "home-assistant/packages/ecco_fallback_status.yaml"
_status_text = (ROOT / _status_rel).read_text(encoding="utf-8")
check("FB-C3: the amendment is real (the status package does spell exactly the five shadow ids) and exact (a sixth id, another file or the dashboard still leaks)",
      sorted(set(SHADOW_ID_RE.findall(_status_text))) == sorted({f"sensor.ecco_clock_dongle_ecco_failback_shadow_{s}" for s in ("state", "episode", "soak", "verdict", "inputs")})
      and strict_hits(_status_rel, _status_text) == []
      and strict_hits(_status_rel, _status_text + "\nsensor.ecco_clock_dongle_ecco_failback_shadow_extra") == ["ecco_" + "failback"]
      and strict_hits(_status_rel, _status_text + "\nsensor.ecco_clock_dongle_ecco_failback_shadow_state_x") == ["ecco_" + "failback"]
      and strict_hits("home-assistant/dashboards/ecco_pro.yaml", "sensor.ecco_clock_dongle_ecco_failback_shadow_state") == ["ecco_" + "failback"]
      and strict_hits("home-assistant/packages/ecco_system_health.yaml", "sensor.ecco_clock_dongle_ecco_failback_shadow_verdict") == ["ecco_" + "failback"]
      and strict_hits(_status_rel, "FALLBACK" + "_PROFILE_X") == ["FALLBACK" + "_PROFILE"] and strict_hits(_status_rel, "FAILBACK" + "_STATE") == ["FAILBACK" + "_STATE"])
check("FB-B3 / FB-C3: frontend/ carries no reserved token at all, and the declared allowlist is exactly the eight named files (exact paths, no directory exemption; "
      "the eighth is FB-C3's HA suite, which spells ecco_fallback entity ids)",
      not [l for l in leaks if l.startswith("frontend/")] and sorted(CH.declared_banned_files()) == sorted([
          "deployment/ha-manifest.yaml", "home-assistant/dashboards/ecco_pro.yaml",
          "home-assistant/packages/ecco_fallback_profile_actions.yaml", "home-assistant/packages/ecco_fallback_status.yaml",
          "home-assistant/packages/ecco_system_health.yaml", "home-assistant/tests/test_ecco_fallback_packages.py",
          "home-assistant/tests/test_ecco_system_health_package.py", "home-assistant/tests/test_ecco_shadow_check_ux.py"]), str(sorted(CH.declared_banned_files())))
check("...and the LIVE firmware YAML carries exactly the banned-token occurrences that chain entries declare (none today)",
      len(BANNED.findall(FW_TEXT)) == CH.declared_banned_fw(), f"{len(BANNED.findall(FW_TEXT))} vs {CH.declared_banned_fw()}")
HEADER_BANNED = (("commit_record", r"commit_record"), ("load_record", r"load_record"), ("make_preference", r"make_preference"),
                 ("global_preferences", r"global_preferences"), ("nvs_", r"nvs_"), ("modbus", r"(?i)modbus"),
                 ("App.", r"\bApp\."), ("id( (ESPHome accessor; word-bounded so valid( is not a hit)", r"\bid\("),
                 ('#include "esphome', r'#\s*include\s*["<]esphome'))
hits = [label for label, pat in HEADER_BANNED if re.search(pat, HEADER)]
check("the header (comments included) contains none of: commit_record, load_record, make_preference, global_preferences, "
      "nvs_, modbus, App., id(, #include \"esphome", not hits, str(hits))
check("the header includes only <array>, <cstddef>, <cstdint>, <type_traits> (standalone)",
      re.findall(r"#include\s*([<\"][^>\"]+[>\"])", HEADER) == ["<array>", "<cstddef>", "<cstdint>", "<type_traits>"])
ns_vars = re.findall(r"^(?!static_assert|struct|enum|namespace|using|template|\}|#|\s)(\S[^(\n;]*?)\s(\w+)(?:\[\])? =", CODE, re.M)
check("every namespace-scope object is constexpr (no non-constexpr initializer, no static-init behaviour)",
      bool(ns_vars) and all(q.startswith("constexpr") for q, _n in ns_vars)
      and not re.search(r"^\s*(?:static|extern|inline)\s+(?!constexpr)", CODE, re.M),
      str([n for q, n in ns_vars if not q.startswith("constexpr")]))
fn_defs = re.findall(r"^(?:template<[^>]*> )?([a-z][\w:<>, ]*?) (\w+)\([^;{]*\) \{", CODE, re.M)
check("every function the header defines is constexpr", bool(fn_defs) and all(r.startswith("constexpr") for r, _n in fn_defs),
      str([n for r, n in fn_defs if not r.startswith("constexpr")]))
def _object_counts(fw):
    return (len(fw["script"]), len(fw["globals"]), len(fw["api"].get("actions", [])), len(fw.get("interval", [])),
            *(len(fw.get(k) or []) for k in ("sensor", "binary_sensor", "text_sensor", "switch", "button", "number", "select")))


counts = _object_counts(FW_PRE_DUMP_V2)
check("object counts as of main + Manual TOU Phase 1 (PR #53; FB-A adds none; Dump V2's own later edits reverted): 30 scripts, "
      "420 globals (418 + 2 RAM-only PR #53 globals), 2 API actions, 9 intervals (8 + 1 RAM-only PR #53 interval), "
      "164/25/63 sensors, 9 switches, 28 buttons, 30 numbers, 13 selects", counts == (30, 420, 2, 9, 164, 25, 63, 9, 28, 30, 13), str(counts))
check("...and with Dump V2 on top (as of chain entry dump_v2) the ONLY object-count change is its 2 RAM-only globals "
      "(dump_evidence_pending_ceiling, dump_controller_evidence_commit_failed): 422 globals",
      _object_counts(FW_SCOPE) == (30, 422, 2, 9, 164, 25, 63, 9, 28, 30, 13) and len(dv2s.ADDED_GLOBALS) == 2, str(_object_counts(FW_SCOPE)))
_live_counts = _object_counts(FW)
_declared_counts = tuple(n + CH.declared_since(m, "dump_v2") for n, m in zip(_object_counts(FW_SCOPE), (
    "scripts", "globals", "api_actions", "intervals", "sensors", "binary_sensors", "text_sensors", "switches", "buttons",
    "numbers", "selects")))
check("...and the LIVE object counts are that plus exactly the deltas later chain entries declare (none today)",
      _live_counts == _declared_counts, f"{_live_counts} vs {_declared_counts}")


def _durable_counts(text):
    return (len(re.findall(r"ecco_durable::commit_record\s*\(", text)), len(re.findall(r"ecco_durable::load_record\s*\(", text)),
            len(re.findall(r"ecco_durable::load_record_status\s*\(", text)))


check("unchanged durable surface (FB-A adds none; Dump V2's own later edits reverted): 55 commit_record, 6 load_record, "
      "3 load_record_status", _durable_counts(FW_PRE_DUMP_V2_TEXT) == (55, 6, 3), str(_durable_counts(FW_PRE_DUMP_V2_TEXT)))
check("...and with Dump V2 on top the durable surface is exactly its documented growth: 57 commit_record (evidence commit "
      "+ V1 rollback tombstone), 7 load_record (diagnostic legacy-V1 probe), 3 load_record_status",
      _durable_counts(SCOPE_FW_TEXT) == (57, 7, 3), str(_durable_counts(SCOPE_FW_TEXT)))
_dc_live, _dc_scope = _durable_counts(FW_TEXT), _durable_counts(SCOPE_FW_TEXT)
check("...and the LIVE durable surface is that plus exactly the commit/load sites later chain entries declare (none today)",
      _dc_live == (_dc_scope[0] + CH.declared_since("commit_record", "dump_v2"), _dc_scope[1] + CH.declared_since("load_record", "dump_v2"),
                   _dc_scope[2] + CH.declared_since("load_record_status", "dump_v2")), str(_dc_live))
WS = CH.analyze_as_of("dump_v2", FW_TEXT)          # the write-surface analyzer on the firmware as of chain entry dump_v2
surface = aws.write_surface(WS["paths"])
check("unchanged Modbus surface (as of chain entry dump_v2): 52 write / 60 read ops, written set 22-24, 230, 232, 244, 250-261, "
      "268-279, no findings",
      sum(1 for p in WS["paths"] for o in p.ops if o.kind == "write") == 52
      and sum(1 for p in WS["paths"] for o in p.ops if o.kind == "read") == 60
      and set(surface) == {22, 23, 24, 230, 232, 244, *range(250, 262), *range(268, 280)}
      and WS["bus_access_findings"] == [] and WS["unknown_extent_writes"] == [])
WS_LIVE = aws.analyze(FIRMWARE_PATH)
surface_live = aws.write_surface(WS_LIVE["paths"])
check("...and the LIVE Modbus surface is that plus exactly the ops later chain entries declare (none today); the LIVE written "
      "register set is still 22-24, 230, 232, 244, 250-261, 268-279 and the live analyzer reports no finding",
      sum(1 for p in WS_LIVE["paths"] for o in p.ops if o.kind == "write") == 52 + CH.declared_since("modbus_writes", "dump_v2")
      and sum(1 for p in WS_LIVE["paths"] for o in p.ops if o.kind == "read") == 60 + CH.declared_since("modbus_reads", "dump_v2")
      and set(surface_live) == {22, 23, 24, 230, 232, 244, *range(250, 262), *range(268, 280)}
      and WS_LIVE["bus_access_findings"] == [] and WS_LIVE["unknown_extent_writes"] == [])
check("the Python model is pure stdlib (ctypes, re, struct, pathlib): no write, network or process access",
      set(re.findall(r"^(?:import|from) (\w+)", MODEL_TEXT, re.M)) == {"__future__", "ctypes", "re", "struct", "pathlib"}
      and not re.search(r"write_text|write_bytes|open\(|subprocess|socket|os\.system", MODEL_TEXT))

# ===========================================================================
print("[10] Mutation sensitivity")
# ===========================================================================


def load_model(source: str):
    mod = types.ModuleType("fallback_profile_mutant")
    mod.__file__ = str(MODEL_PATH)
    exec(compile(source, str(MODEL_PATH), "exec"), mod.__dict__)
    return mod


def site_ceiling_independent(m) -> bool:
    """Profile validity must not move when the configured site ceiling does."""
    original = m.firmware_tou_power_ceiling_w
    try:
        results = []
        for ceiling in (6000, 9000):
            m.firmware_tou_power_ceiling_w = lambda *_a, c=ceiling: c
            gp, _gf = golden_records(m)
            results.append(profile_cases_agree(m) and m.classify_profile(m.LOAD_OK, gp) == m.PROFILE_VALID)
        return all(results)
    finally:
        m.firmware_tou_power_ceiling_w = original


def detectors(m) -> dict:
    out = {}
    for name, fn in (
        ("layout", lambda: layout_agrees(m)),
        ("binding vectors", lambda: golden_binding_vectors(m) == HDR_BIND),
        ("profile cases", lambda: profile_cases_agree(m)),
        ("failback cases", lambda: failback_cases_agree(m)),
        ("register digest", lambda: reg_digest is not None and m.register_class_digest() == c_int(reg_digest.group(1))),
        ("domain digests", lambda: all(DIG.get(k) == m.domain_digest(getattr(m, p)) for k, p in PREDICATES.items())),
        ("tags", lambda: keys_distinct(m) and (m.FALLBACK_PROFILE_TAG, m.FAILBACK_STATE_TAG) == tuple(new.values())),
        ("site ceiling", lambda: site_ceiling_independent(m)),
        ("non-OK loads", lambda: all(m.classify_profile(ld, None) == every_load[ld] for ld in range(1, 256))
         and all(m.classify_failback(ld, None) == every_fload[ld] for ld in range(1, 256))),
    ):
        try:
            out[name] = bool(fn())
        except Exception:  # noqa: BLE001 - a mutant that crashes a detector is detected
            out[name] = False
    return out


control = detectors(load_model(MODEL_TEXT))
check("control: the unmutated model passes every detector", all(control.values()), str(control))

MUTANTS = [
    ("schema widened and offsets shift", '("magic", "I", 1), ("schema", "H", 1)', '("magic", "I", 1), ("schema", "I", 1)'),
    ("swapped reg232/reg243", '("reg232", "H", 1), ("reg243", "H", 1)', '("reg243", "H", 1), ("reg232", "H", 1)'),
    ("missing reserved field", '("reserved0", "I", 1), ("reserved1", "I", 1), ', '("reserved0", "I", 1), '),
    ("binding includes itself", "bytes(raw[:PROFILE_BOUND_BYTES])", "bytes(raw[:PROFILE_SIZE])"),
    ("binding starts at byte 8", "bytes(raw[:PROFILE_BOUND_BYTES])", "bytes(raw[8:PROFILE_BOUND_BYTES])"),
    ("failback binding omits profile_binding", "bytes(raw[:FAILBACK_BOUND_BYTES])", "bytes(raw[:64])"),
    ("domain string hashes terminating NUL", "fnv1a_64(PROFILE_BINDING_DOMAIN + bytes(", 'fnv1a_64(PROFILE_BINDING_DOMAIN + b"\\0" + bytes('),
    ("wrong domain string", 'PROFILE_BINDING_DOMAIN = b"ECCO-FALLBACK-PROFILE-v1"', 'PROFILE_BINDING_DOMAIN = b"ECCO-FALLBACK-PROFILE-v2"'),
    ("Python mirror big-endian", 'def pack_profile(record: dict, byte_order: str = "<")', 'def pack_profile(record: dict, byte_order: str = ">")'),
    ("READ_ERROR -> NOT_CAPTURED", "    if load_result != LOAD_OK:\n        return PROFILE_UNREADABLE",
     "    if load_result != LOAD_OK:\n        return PROFILE_NOT_CAPTURED"),
    ("WRONG_SIZE -> NOT_CAPTURED", "    if load_result == LOAD_WRONG_SIZE:\n        return PROFILE_CORRUPT",
     "    if load_result == LOAD_WRONG_SIZE:\n        return PROFILE_NOT_CAPTURED"),
    ("unknown load status -> NOT_CAPTURED", "    if load_result != LOAD_OK:\n        return PROFILE_UNREADABLE",
     "    if load_result in (LOAD_READ_ERROR, LOAD_STORAGE_UNAVAILABLE):\n        return PROFILE_UNREADABLE\n"
     "    if load_result != LOAD_OK:\n        return PROFILE_NOT_CAPTURED"),
    ("bytes inspected when load != OK", '    raw bytes) is not inspected unless load_result is LOAD_OK."""\n',
     '    raw bytes) is not inspected unless load_result is LOAD_OK."""\n'
     '    if profile_defect(_as_profile(record)) == PROFILE_DEFECT_MAGIC:\n        return PROFILE_CORRUPT\n'),
    ("failback ABSENT treated as CLEAR", "    if load_result == LOAD_ABSENT:\n        return FAILBACK_RECORD_ABSENT",
     "    if load_result == LOAD_ABSENT:\n        return FAILBACK_RECORD_VALID"),
    ("schema 2 accepted under the v1 tag", 'if p["schema"] != PROFILE_SCHEMA:', 'if p["schema"] not in (1, 2):'),
    ("size not checked", '    if p["size"] != PROFILE_SIZE:\n        return PROFILE_DEFECT_SIZE',
     '    if False:\n        return PROFILE_DEFECT_SIZE'),
    ("reserved bits accepted", 'if p["reserved0"] != 0 or p["reserved1"] != 0:', "if False:"),
    ("flags 0x8001 accepted", 'if p["flags"] & ~PROFILE_KNOWN_FLAGS & 0xFFFF:', 'if p["flags"] & ~PROFILE_KNOWN_FLAGS & 0x7FFF:'),
    ("generation 0 accepted", 'if p["generation"] == 0:', "if False:"),
    ("INVALIDATED before binding", "    p = _as_profile(record)\n    d = profile_defect(p)",
     '    p = _as_profile(record)\n    if p["flags"] & PROFILE_FLAG_INVALIDATED and p["magic"] == PROFILE_MAGIC:\n'
     "        return PROFILE_INVALIDATED\n    d = profile_defect(p)"),
    ("INVALIDATED before domain validation", "    if d == PROFILE_DEFECT_DOMAIN:\n        return PROFILE_CORRUPT_DOMAIN",
     '    if d == PROFILE_DEFECT_DOMAIN:\n        return PROFILE_INVALIDATED if p["flags"] & PROFILE_FLAG_INVALIDATED else PROFILE_CORRUPT_DOMAIN'),
    ("244 accepts 0 or 1", "def reg244_domain_valid(v: int) -> bool:\n    return v == REG244_PROFILE_REQUIRED",
     "def reg244_domain_valid(v: int) -> bool:\n    return v in (0, 1, 2)"),
    ("lower bound 499 accepted", "V1_TOU_POWER_MIN_W = 500", "V1_TOU_POWER_MIN_W = 499"),
    ("8001 accepted", "V1_TOU_POWER_MAX_W = 8000", "V1_TOU_POWER_MAX_W = 8001"),
    ("runtime ceiling used instead of schema constant", "return V1_TOU_POWER_MIN_W <= v <= V1_TOU_POWER_MAX_W",
     "return V1_TOU_POWER_MIN_W <= v <= firmware_tou_power_ceiling_w()"),
    ("SOC 101 accepted", "return 0 <= v <= SOC_MAX", "return 0 <= v <= SOC_MAX + 1"),
    ("274 value 2/3/0x40 accepted", "return (v & ~SLOT_SOURCE_BITS_MASK & 0xFFFF) == 0 and (v & SLOT_SOURCE_BITS_MASK) <= 1",
     "return (v & ~0x43 & 0xFFFF) == 0"),
    ("232 bit0 put into E1", "    232: (REG_CTX, 0x0001),", "    232: (REG_E1, 0x0001),"),
    ("full-word 232 comparison", "    232: (REG_CTX, 0x0001),", "    232: (REG_CTX, 0xFFFF),"),
    ("full-word 248 comparison", "    248: (REG_CTX, 0x0001),", "    248: (REG_CTX, 0xFFFF),"),
    ("230 restored to E1", "    230: (REG_INFO, 0xFFFF),", "    230: (REG_E1, 0xFFFF),"),
    ("excluded register 246 added to a table", "    245: (REG_INFO, 0xFFFF),", "    245: (REG_INFO, 0xFFFF),\n    246: (REG_INFO, 0xFFFF),"),
    ("excluded register 262 added to E1", "    **{a: (REG_E1, 0xFFFF) for a in range(256, 262)},",
     "    **{a: (REG_E1, 0xFFFF) for a in range(256, 263)},"),
    ("state 5 accepted", 'if s["state"] > FAILBACK_BLOCKED:', 'if s["state"] > FAILBACK_BLOCKED + 1:'),
    ("unknown reason accepted", 'if s["reason"] not in FAILBACK_REASON_NAMES:', 'if s["reason"] > 3:'),
    ("unknown result accepted", 'if s["result"] not in FAILBACK_RESULT_NAMES:', 'if s["result"] > 12:'),
    ("APPLY_IN_PROGRESS accepted with apply_committed clear",
     'if st == FAILBACK_APPLY_IN_PROGRESS and (not committed or s["result"] != FAILBACK_RESULT_NONE):',
     'if st == FAILBACK_APPLY_IN_PROGRESS and s["result"] != FAILBACK_RESULT_NONE:'),
    ("nonzero FROM accepted with apply_committed clear", "if failback_from_all_zero(s) == committed:",
     "if committed and failback_from_all_zero(s):"),
    ("FROM domain not checked", "if committed and not failback_from_domain_valid(s):", "if False:"),
    ("profile_generation 0 with a binding accepted", 'if (s["profile_generation"] == 0) != (s["profile_binding"] == 0):',
     'if s["profile_generation"] != 0 and s["profile_binding"] == 0:'),
    ("CLEAR retains the last result", 'if (s["reason"], s["result"], s["flags"]', 'if (s["reason"], 0, s["flags"]'),
    ("failback flag bit 3 accepted", "FAILBACK_KNOWN_FLAGS = 0x07", "FAILBACK_KNOWN_FLAGS = 0x0F"),
    ("fallback tag collides with an existing tag", 'FALLBACK_PROFILE_TAG = "ecco_fallback_profile_v1"',
     'FALLBACK_PROFILE_TAG = "ecco_free_power_snapshot_valid_v1"'),
]
for label, old, new_text in MUTANTS:
    if MODEL_TEXT.count(old) < 1:
        check(f"mutant [{label}] applies to the model source", False, repr(old[:60]))
        continue
    res = detectors(load_model(MODEL_TEXT.replace(old, new_text, 1)))
    check(f"mutant [{label}] is killed", not all(res.values()), "survived every detector")

PIN_DEFECT = body(r"constexpr ProfileDefect profile_defect\(const FallbackProfileV1 &p\)")
PIN_CLASSIFY = body(r"constexpr ProfileClass classify_profile\(uint8_t load, const FallbackProfileV1 &p\)")
HEADER_MUTANTS = [
    ("header: INVALIDATED before domain", "  if (d == PROFILE_DEFECT_DOMAIN)\n    return PROFILE_CORRUPT_DOMAIN;\n",
     "  if (d == PROFILE_DEFECT_DOMAIN)\n    return (p.flags & PROFILE_FLAG_INVALIDATED) ? PROFILE_INVALIDATED : PROFILE_CORRUPT_DOMAIN;\n"),
    ("header: binding checked after reserved", "  if (p.binding != profile_binding(p))\n    return PROFILE_DEFECT_BINDING;\n"
     "  if (p.reserved0 != 0 || p.reserved1 != 0)\n    return PROFILE_DEFECT_RESERVED;\n",
     "  if (p.reserved0 != 0 || p.reserved1 != 0)\n    return PROFILE_DEFECT_RESERVED;\n"
     "  if (p.binding != profile_binding(p))\n    return PROFILE_DEFECT_BINDING;\n"),
    ("header: domain string hashes NUL", "for (size_t i = 0; i + 1 < N; i++)", "for (size_t i = 0; i < N; i++)"),
    ("header: runtime ceiling parameter", "constexpr bool tou_power_domain_valid(uint16_t v) {",
     "constexpr bool tou_power_domain_valid(uint16_t v, uint32_t tou_power_ceiling_w = 8000) {"),
]
for label, old, new_text in HEADER_MUTANTS:
    mutated = strip_comments(HEADER.replace(old, new_text, 1))
    detected = (body(r"constexpr ProfileDefect profile_defect\(const FallbackProfileV1 &p\)", mutated) != PIN_DEFECT
                or body(r"constexpr ProfileClass classify_profile\(uint8_t load, const FallbackProfileV1 &p\)", mutated) != PIN_CLASSIFY
                or "for (size_t i = 0; i + 1 < N; i++)" not in mutated
                or "constexpr bool tou_power_domain_valid(uint16_t v) {" not in mutated or bool(re.search(r"ceiling_w\b", mutated)))
    check(f"{label} is detected by the header text pins", HEADER.count(old) == 1 and detected)

print("")
if FAILURES:
    print(f"FAILED: {len(FAILURES)} check(s)")
    for f in FAILURES:
        print(f"  - {f}")
    sys.exit(1)
print("All FB-A Fallback Profile schema checks passed.")
