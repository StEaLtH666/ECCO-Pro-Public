#!/usr/bin/env python3
"""FB-B0 - Fallback durable model: FBW witness, compose rules, outcome table,
generation, read latch, exclusivity and change scope (no runtime behaviour).

firmware/include/ecco_fallback_durable_model.h is the pure model,
firmware/include/ecco_fallback_durable.h the branch-free EspNvs adapter and
firmware/include/ecco_fallback_version_pins.h the two-sided version pins;
registry/fallback_durable.py is the C++-exact Python mirror. FB-B0 compiles
the headers into the firmware (esphome: includes) and adds ZERO call sites.

This suite parses the header's compile-time golden vectors, enums and
golden-case tables and re-derives every value from the mirror AND from
spec-literal oracles written from the architecture tables
(docs/architecture/fallback/FINAL_FBB_FBC_ARCHITECTURE.md 4.3-4.6,
design/S2_fbb_durable_final.md 2.5 / 5.4); the C++ side of the same tables is
evaluated by a real compiler in test_fallback_durable_host_compile.py.

Sections:
  [1]  FBW layout and constants (header == mirror == architecture offsets)
  [2]  FBW binding, the four golden vectors, golden-vector corruption
  [3]  Keys, decimal key strings, tag
  [4]  Enums: header == mirror numbering; 0 is the fail-closed value
  [5]  Per-key outcome table and readback classes (exhaustive vs spec oracle)
  [6]  Witness classifier: golden cases parsed from the header + sweeps
  [7]  compose_profile_class: golden cases parsed from the header + exhaustive oracle
  [8]  Permissions, writer-usable, generation (header static_asserts re-evaluated)
  [9]  Per-boot read latch (exhaustive vs oracle)
  [10] Transaction semantics of the mirror (witness first, refusals, RAM mirror)
  [11] Exclusivity X1-X4 / X7 and ZERO runtime call sites
  [12] Header discipline: includes, banned tokens, constexpr, branch-free adapter, version pins
  [13] Change scope (_fbb_scope): exact YAML delta, protected files, zero count deltas
  [14] Mutation sensitivity: Python-mirror mutants and header-text mutants
  [15] FB-T0 chain registration: the `fbb0` entry (appended after `fbc1`), tag promotion, negative controls

No I/O beyond reading repository files and one temporary copy of the base
firmware for the write-surface delta; no hardware, no network.
"""

from __future__ import annotations

import hashlib
import re
import shutil
import sys
import tempfile
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FIRMWARE_PATH = ROOT / "firmware" / "ecco_clock_dongle_stage3_4_free_power.yaml"
INCLUDE_DIR = ROOT / "firmware" / "include"
MODEL_H_PATH = INCLUDE_DIR / "ecco_fallback_durable_model.h"
ADAPTER_H_PATH = INCLUDE_DIR / "ecco_fallback_durable.h"
PINS_H_PATH = INCLUDE_DIR / "ecco_fallback_version_pins.h"
FBA_H_PATH = INCLUDE_DIR / "ecco_fallback_profile.h"
MIRROR_PATH = ROOT / "registry" / "fallback_durable.py"

sys.path.insert(0, str(ROOT / "registry"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(ROOT / "tools"))
import fallback_durable as fd  # noqa: E402
import fallback_profile as fp  # noqa: E402
import _dump_sim as ds  # noqa: E402
import _fbb_harness as H  # noqa: E402
import _fbb_scope as fbbs  # noqa: E402
import _free_power_action_sim as fpsim  # noqa: E402
import _scope_chain as chain  # noqa: E402
import _tag_inventory as ti  # noqa: E402
import analyze_write_surface as aws  # noqa: E402

FAILURES: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  PASS  {name}")
    else:
        FAILURES.append(name)
        print(f"  FAIL  {name}" + (f" - {detail}" if detail else ""))


def raises(fn, exc) -> BaseException | None:
    """The exception of type `exc` that fn() raised, else None (another exception type propagates)."""
    try:
        fn()
    except exc as e:
        return e
    return None


for required in (FIRMWARE_PATH, MODEL_H_PATH, ADAPTER_H_PATH, PINS_H_PATH, FBA_H_PATH, MIRROR_PATH):
    if not required.is_file():
        print(f"  FAIL  required file not found: {required}")
        sys.exit(1)

MODEL_H = MODEL_H_PATH.read_text(encoding="utf-8")
ADAPTER_H = ADAPTER_H_PATH.read_text(encoding="utf-8")
PINS_H = PINS_H_PATH.read_text(encoding="utf-8")
# FB-T0: this suite is anchored at chain entry "fbb0" (registry/tests/_scope_chain.py). It reads the firmware AS OF fbb0 - every
# LATER entry's declared edits reverted exactly, newest first - so a later PR never re-hashes or edits it, while an undeclared
# edit still breaks the revert. FB-B0 was prepared on b3fcdfc and is reconciled on top of FB-T0 and FB-C1 (chain entry fbc1), so
# the firmware as of fbb0 also carries FB-C1's declared `ecco_failback_shadow_*` substitution keys (see without_declared_subst).
LIVE_FW_TEXT = FIRMWARE_PATH.read_text(encoding="utf-8")
FW_TEXT = chain.CHAIN.as_of(chain.FIRMWARE, "fbb0", LIVE_FW_TEXT)
MIRROR_TEXT = MIRROR_PATH.read_text(encoding="utf-8")
FW = ds.load_firmware_text(FW_TEXT)


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def c_int(tok: str) -> int:
    return int(tok.strip().rstrip("uUlL"), 0)


def strip_comments(code: str) -> str:
    code = re.sub(r"/\*.*?\*/", "", code, flags=re.S)
    return re.sub(r"//[^\n]*", "", code)


def strip_code(code: str) -> str:
    """Comments AND string-literal contents removed (a message or a comment
    naming an API is not a use of it)."""
    code = re.sub(r"/\*.*?\*/", "", code, flags=re.S)
    code = re.sub(r'"(?:\\.|[^"\\\n])*"', '""', code)
    return re.sub(r"//[^\n]*", "", code)


CODE_OF = {"B": "uint8_t", "H": "uint16_t", "I": "uint32_t", "Q": "uint64_t"}
SIZE_OF = {"uint8_t": 1, "uint16_t": 2, "uint32_t": 4, "uint64_t": 8}
ARCH_OFFSETS = [0, 4, 6, 8, 12, 16, 24, 32, 36, 38, 39, 40]  # FINAL 4.5 / 16.2
SPEC_GOLDENS = {"W-ZERO": 0x1FDA24BEF28230CF, "W-FF": 0x06E1F1CA2CBB0327, "W-FIRST": 0xA8B8788B4C915BB6,
                "W-INV": 0x9E8AEC8F7D7DF2D7}


def header_struct(text: str, name: str):
    m = re.search(rf"struct {name} \{{(.*?)\n\}};", text, re.S)
    if not m:
        return None
    return [(t, f) for t, f in re.findall(r"\b(uint\d+_t) (\w+);", strip_comments(m.group(1)))]


def header_offsets(text: str, name: str) -> dict:
    return {f: int(o) for f, o in re.findall(rf"offsetof\({name}, (\w+)\) == (\d+)", text)}


def header_const(text: str, name: str):
    m = re.search(rf"constexpr (?:uint\d+_t|int32_t|size_t) {name} = (-?0x[0-9A-Fa-f]+u?|-?\d+u?);", text)
    return c_int(m.group(1)) if m else None


def header_enum(text: str, name: str) -> dict:
    m = re.search(rf"enum {name} : uint8_t \{{(.*?)\}};", text, re.S)
    if not m:
        return {}
    return {n: int(v) for n, v in re.findall(r"\b([A-Z][A-Z0-9_]*) = (\d+)", strip_comments(m.group(1)))}


def split_args(s: str) -> list[str]:
    """Split a C++ argument list on its top-level commas."""
    out, depth, cur = [], 0, ""
    for ch in s:
        if ch == "," and depth == 0:
            out.append(cur.strip())
            cur = ""
            continue
        depth += (ch in "([{") - (ch in ")]}")
        cur += ch
    return out + [cur.strip()] if cur.strip() else out


def table_rows(text: str, array: str) -> list[list[str]]:
    m = re.search(rf"constexpr \w+ {array}\[\] = \{{(.*?)\n\}};", text, re.S)
    if not m:
        return []
    return [[t.strip() for t in row.split(",")] for row in re.findall(r"\{([^{}]*)\}", strip_comments(m.group(1)))]


# ---------------------------------------------------------------------------
# Records used throughout (FB-A golden payload, FBW goldens and variants)
# ---------------------------------------------------------------------------
GOLD7 = fp.seal_profile(fp.blank_profile(
    magic=fp.PROFILE_MAGIC, schema=1, size=96, generation=7, captured_epoch=1790000000, flags=0, reg244=2,
    reg256_261=[8000, 500, 4000, 3000, 2000, 1000], reg268_273=[100, 20, 0, 50, 100, 30], reg274_279=[1, 0, 1, 0, 0, 1],
    reg232=0x0011, reg243=1, reg248=1, reg250_255=[0, 530, 1000, 1600, 2100, 2330], reg230=185, reg245=8000, reg247=1,
    reserved0=0, reserved1=0, binding=0))
K, S1 = fd.FALLBACK_PROFILE_KEY, fp.PROFILE_SCHEMA


def gen(p: dict, g: int, **kw) -> dict:
    return fp.seal_profile(dict(p, generation=g, **kw))


def build_records(m):
    """The header's named record variants, built with mirror `m`."""
    g1 = gen(GOLD7, 1)
    inv8 = m.invalidate_profile_cxx(GOLD7)
    dom7 = fp.seal_profile(dict(GOLD7, reg244=0))
    G = GOLD7["binding"]
    w_first = m.make_provision(1, g1["binding"], 0, 0, K, S1, m.PROV_OP_SAVE)
    w_inv = m.make_provision(8, inv8["binding"], 7, G, K, S1, m.PROV_OP_INVALIDATE)
    pv = {
        "PV_GOLD7": GOLD7, "PV_INV8": inv8, "PV_DOM7": dom7,
        "PV_BAD7": dict(GOLD7, binding=(G + 1) & 0xFFFFFFFFFFFFFFFF), "PV_GOLD9": gen(GOLD7, 9), "PV_GOLD5": gen(GOLD7, 5),
        "PV_ALT7": fp.seal_profile(dict(GOLD7, captured_epoch=GOLD7["captured_epoch"] + 60)),
        "PV_ZERO": fp.unpack_profile(bytes(fp.PROFILE_SIZE)),
    }
    wv = {
        "WV_HW7_G": m.make_provision(7, G, 6, 0x6666, K, S1, m.PROV_OP_SAVE),
        "WV_HW7_X": m.make_provision(7, 0x1234, 6, 0x6666, K, S1, m.PROV_OP_SAVE),
        "WV_HW6": m.make_provision(6, 0x5555, 5, 0x4444, K, S1, m.PROV_OP_SAVE),
        "WV_HW8_SAVE_P7": m.make_provision(8, 0x8888, 7, G, K, S1, m.PROV_OP_SAVE),
        "WV_HW9_P8": m.make_provision(9, 0x9999, 8, 0x8888, K, S1, m.PROV_OP_SAVE),
        "WV_FOREIGN_TAG": m.make_provision(7, G, 6, 0x6666, 0x12345678, S1, m.PROV_OP_SAVE),
        "WV_FOREIGN_SCH": m.make_provision(7, G, 6, 0x6666, K, 2, m.PROV_OP_SAVE),
        "WV_FOREIGN_LAG": m.make_provision(6, 0x5555, 5, 0x4444, 0x12345678, S1, m.PROV_OP_SAVE),
        "WV_FIRST": w_first,
        "WV_FIRST_INVOP": m.make_provision(1, g1["binding"], 0, 0, K, S1, m.PROV_OP_INVALIDATE),
        "WV_H2_P0": m.make_provision(2, 0x2222, 0, 0, K, S1, m.PROV_OP_SAVE),
        "WV_INV": w_inv,
        "WV_HW7_DOM": m.make_provision(7, dom7["binding"], 6, 0x6666, K, S1, m.PROV_OP_SAVE),
        "WV_BAD": dict(w_inv, binding=(w_inv["binding"] + 1) & 0xFFFFFFFFFFFFFFFF),
        "WV_ZERO": m.unpack_provision(bytes(48)),
    }
    return {"g1": g1, "inv8": inv8, "dom7": dom7, "w_first": w_first, "w_inv": w_inv, "pv": pv, "wv": wv}


REC = build_records(fd)

# ===========================================================================
print("[1] FBW layout and constants (header == mirror == architecture)")
# ===========================================================================


def layout_agrees(m, text: str = MODEL_H) -> bool:
    hs = header_struct(text, "FailbackProvisionV1")
    ho = header_offsets(text, "FailbackProvisionV1")
    if not all(n == 1 for _f, _c, n in m.PROVISION_LAYOUT):
        return False  # FBW has no array fields
    if not hs or hs != [(CODE_OF[c], f) for f, c, _n in m.PROVISION_LAYOUT]:
        return False
    natural, off = {}, 0
    for t, f in hs:
        size = SIZE_OF[t]
        if off % size:
            return False  # an implicit padding hole would be needed
        natural[f] = off
        off += size
    return (off == 48 and natural == ho == dict(m.PROVISION_OFFSETS) and sorted(ho.values()) == ARCH_OFFSETS
            and re.search(r"static_assert\(sizeof\(FailbackProvisionV1\) == 48,", text) is not None
            and m.PROVISION_SIZE == 48)


check("FailbackProvisionV1: header fields/types == mirror PROVISION_LAYOUT, offsets == natural packing == "
      "architecture 0,4,6,8,12,16,24,32,36,38,39,40, sizeof 48, no implicit padding", layout_agrees(fd))


def codec_fields(text: str, fn: str, pat: str) -> dict:
    m = re.search(rf"constexpr \w+ {fn}\(.*?\n\}}", text, re.S)
    return {f: int(n) for f, n in re.findall(pat, m.group(0))} if m else {}


widths = {f: SIZE_OF[CODE_OF[c]] for f, c, _n in fd.PROVISION_LAYOUT}
enc = codec_fields(MODEL_H, "encode_provision", r"put_le\(b, offsetof\(FailbackProvisionV1, (\w+)\), w\.\1, (\d)\)")
dec = codec_fields(MODEL_H, "decode_provision", r"w\.(\w+) = (?:\(uint\d+_t\) )?ecco_fallback::get_le\(b, offsetof\(FailbackProvisionV1, \1\), (\d)\)")
check("encode_provision / decode_provision write and read EVERY field, field by field, at its offset with its width "
      "(little-endian via FB-A put_le / get_le)", enc == widths == dec, f"{enc} / {dec}")


def constants_agree(m, text: str = MODEL_H) -> bool:
    dom = re.search(r'constexpr char PROVISION_BINDING_DOMAIN\[\] = "([^"]+)";', text)
    return (header_const(text, "PROVISION_MAGIC") == m.PROVISION_MAGIC == 0x45434657
            and header_const(text, "PROVISION_SCHEMA") == m.PROVISION_SCHEMA == 1
            and header_const(text, "PROVISION_SIZE") == m.PROVISION_SIZE == 48
            and header_const(text, "PROVISION_BOUND_BYTES") == m.PROVISION_BOUND_BYTES == 40
            and dom is not None and dom.group(1).encode() == m.PROVISION_BINDING_DOMAIN == b"ECCO-FAILBACK-PROVISION-v1"
            and header_const(text, "GENERATION_MAX") == m.GENERATION_MAX == 0xFFFFFFFF)


check("constants header == mirror == architecture: magic 0x45434657 ('ECFW'), schema 1, size 48, bound bytes 40, "
      "domain \"ECCO-FAILBACK-PROVISION-v1\" (26 bytes, no NUL), GENERATION_MAX 0xFFFFFFFF", constants_agree(fd))
check("the FBW magic differs from ECFP, ECFB, ECCV and ECSJ (header static_assert + mirror)",
      len({fd.PROVISION_MAGIC, fp.PROFILE_MAGIC, fp.FAILBACK_MAGIC, 0x45434356, 0x4543534A}) == 5
      and "PROVISION_MAGIC != 0x45434356u && PROVISION_MAGIC != 0x4543534Au" in MODEL_H)
check("pack/unpack round-trip is the identity on the golden witnesses and on random-looking records",
      all(fd.unpack_provision(fd.pack_provision(w)) == w for w in (REC["w_first"], REC["w_inv"], *REC["wv"].values()))
      and all(fd.pack_provision(fd.unpack_provision(bytes((i * 37 + k) & 0xFF for i in range(48)))) ==
              bytes((i * 37 + k) & 0xFF for i in range(48)) for k in range(16)))

# ===========================================================================
print("[2] FBW binding, golden vectors, golden-vector corruption")
# ===========================================================================
GOLDEN_ASSERT = re.compile(r'==\s+(0x[0-9A-F]+)ULL,\s*"FBW golden vector (W-[A-Z]+)"')


def header_goldens(text: str) -> dict:
    return {name: c_int(v) for v, name in GOLDEN_ASSERT.findall(text)}


def mirror_goldens(m) -> dict:
    r = build_records(m)
    return {"W-ZERO": m.provision_binding(bytes(48)), "W-FF": m.provision_binding(b"\xff" * 48),
            "W-FIRST": r["w_first"]["binding"], "W-INV": r["w_inv"]["binding"]}


check("the header asserts exactly the four published golden vectors (W-ZERO, W-FF, W-FIRST, W-INV) with the "
      "architecture's values", header_goldens(MODEL_H) == SPEC_GOLDENS, str({k: hex(v) for k, v in header_goldens(MODEL_H).items()}))
check("the mirror RECOMPUTES all four exactly (W-FIRST = first SAVE of FB-A's golden payload at g1, W-INV = invalidate "
      "of GOLDEN_PROFILE_V1 g7 -> g8)", mirror_goldens(fd) == SPEC_GOLDENS,
      str({k: hex(v) for k, v in mirror_goldens(fd).items()}))
check("inputs of the witness goldens: FB-A GOLDEN_PROFILE_V1 binding 0xD852A4FA2DF7DBA3, at g1 0xB74CE0FA6297474D, "
      "invalidated 0xF49A36C9C9720301 (header asserts the same three)",
      (GOLD7["binding"], REC["g1"]["binding"], REC["inv8"]["binding"]) == (0xD852A4FA2DF7DBA3, 0xB74CE0FA6297474D, 0xF49A36C9C9720301)
      and all(f"{v:#018X}ULL".replace("0X", "0x") in MODEL_H for v in (0xD852A4FA2DF7DBA3, 0xB74CE0FA6297474D, 0xF49A36C9C9720301)))
wf, wi = REC["w_first"], REC["w_inv"]
check("W-FIRST field values: hw 1 / hw_binding(g1) / prior 0/0 / tag 0x5FEE6196 / record schema 1 / op SAVE / flags 0",
      (wf["hw_generation"], wf["hw_binding"], wf["prior_generation"], wf["prior_binding"], wf["hw_tag_key"],
       wf["hw_record_schema"], wf["last_op"], wf["flags"]) == (1, 0xB74CE0FA6297474D, 0, 0, K, 1, 1, 0))
check("W-INV field values: hw 8 / INV binding / prior 7 / GOLDEN binding / op INVALIDATE",
      (wi["hw_generation"], wi["hw_binding"], wi["prior_generation"], wi["prior_binding"], wi["last_op"])
      == (8, 0xF49A36C9C9720301, 7, 0xD852A4FA2DF7DBA3, 2))
check("binding = FNV-1a-64(domain || bytes[0,40)): independent recomputation from raw bytes (not via the mirror)",
      all(fp.fnv1a_64(b"ECCO-FAILBACK-PROVISION-v1" + fd.pack_provision(w)[:40]) == w["binding"] for w in (wf, wi)))
check("the binding does NOT cover its own field: changing bytes [40,48) leaves provision_binding unchanged",
      all(fd.provision_binding(fd.pack_provision(wi)[:40] + bytes([k]) * 8) == wi["binding"] for k in (0, 0x5A, 0xFF)))
flip_valid, flip_defects = [], set()
for base in (wf, wi):
    raw = fd.pack_provision(base)
    for i in range(48):
        for bit in range(8):
            mutated = bytearray(raw)
            mutated[i] ^= 1 << bit
            w = fd.unpack_provision(bytes(mutated))
            if fd.classify_witness(fd.LOAD_OK, w) != fd.W_CORRUPT:
                flip_valid.append((i, bit))
            flip_defects.add(fd.witness_defect(w))
check("golden-vector corruption: every one of the 2 x 384 single-bit flips of W-FIRST / W-INV classifies W_CORRUPT "
      "(never VALID); MAGIC, SCHEMA, SIZE and BINDING defects all occur", not flip_valid and
      {fd.WIT_DEFECT_MAGIC, fd.WIT_DEFECT_SCHEMA, fd.WIT_DEFECT_SIZE, fd.WIT_DEFECT_BINDING} <= flip_defects, str(flip_valid[:5]))
check("golden-vector corruption: a flipped golden value in the header is caught at compile time (the host suite's "
      "HEADER_MUTANTS) and here: the parsed header goldens would no longer equal the spec",
      header_goldens(MODEL_H.replace("0xA8B8788B4C915BB6ULL", "0xA8B8788B4C915BB7ULL")) != SPEC_GOLDENS)

# ===========================================================================
print("[3] Keys, decimal key strings, tag")
# ===========================================================================
check("FBP / FBW / FBS keys == ESPHome FNV-1 32 of their tags (header constants == mirror == FB-A tag_key_fnv1_32)",
      (header_const(MODEL_H, "FALLBACK_PROFILE_KEY"), header_const(MODEL_H, "FAILBACK_PROVISION_KEY"),
       header_const(MODEL_H, "FAILBACK_STATE_KEY"))
      == (fd.FALLBACK_PROFILE_KEY, fd.FAILBACK_PROVISION_KEY, fd.FAILBACK_STATE_KEY)
      == (fp.tag_key_fnv1_32(fp.FALLBACK_PROFILE_TAG), fp.tag_key_fnv1_32(fd.FAILBACK_PROVISION_TAG),
          fp.tag_key_fnv1_32(fp.FAILBACK_STATE_TAG)) == (0x5FEE6196, 0x3BA3DF61, 0x808485C3))
check("decimal key strings exactly as ESPHome's uint32_to_str renders them: 1609458070, 1000595297, 2156168643 "
      "(header static_asserts + mirror); 0 -> \"0\", 10 -> \"10\", UINT32_MAX -> \"4294967295\"",
      [fd.decimal_key(k) for k in (fd.FALLBACK_PROFILE_KEY, fd.FAILBACK_PROVISION_KEY, fd.FAILBACK_STATE_KEY)]
      == ["1609458070", "1000595297", "2156168643"] and (fd.decimal_key(0), fd.decimal_key(10), fd.decimal_key(0xFFFFFFFF))
      == ("0", "10", "4294967295") and all(f'decimal_key({n}), "{s}")' in MODEL_H for n, s in (
          ("FALLBACK_PROFILE_KEY", "1609458070"), ("FAILBACK_PROVISION_KEY", "1000595297"), ("FAILBACK_STATE_KEY", "2156168643"))))
tag = re.search(r'constexpr char FAILBACK_PROVISION_TAG\[\] = "([^"]+)";', MODEL_H)
check("the model header DECLARES FAILBACK_PROVISION_TAG = \"ecco_failback_provision_v1\" (== mirror): the tag FB-A "
      "reserved for it (architecture 4.5; collision proof in test_fallback_nvs_keyhash.py)",
      tag is not None and tag.group(1) == fd.FAILBACK_PROVISION_TAG == "ecco_failback_provision_v1")
check("the three key/tag static_asserts are in the header (tag_key_fnv1_32 of each tag == its key)",
      MODEL_H.count("ecco_fallback::tag_key_fnv1_32(") == 3)

# ===========================================================================
print("[4] Enums: header == mirror numbering; 0 is the fail-closed value")
# ===========================================================================
ENUMS = {
    "WriteErrClass": ("WERR_", "WERR_OTHER"), "ReadbackClass": ("RB_", "RB_NOT_READ"),
    "KeyOutcome": ("KEY_", "KEY_UNKNOWN_REBOOT"), "TxnOutcome": ("TXN_", "TXN_UNKNOWN_REBOOT"),
    "TxnRefusal": ("REFUSAL_", "REFUSAL_UNSET"), "ProvisionOp": ("PROV_OP_", "PROV_OP_INVALID"),
    "WitnessDefect": ("WIT_DEFECT_", "WIT_DEFECT_NONE"), "WitnessClass": ("W_", "W_UNREADABLE"),
    "EffectiveProfileClass": ("EPC_", "EPC_UNREADABLE"), "EpcWhy": ("WHY_", "WHY_NONE"),
    "ComposeRule": ("RULE_", "RULE_NONE"), "FbsSlot": ("FBS_", "FBS_UNREADABLE"),
}


def enum_mirror_value(m, name: str):
    if name.startswith("RULE_B") and name != "RULE_B2A":
        return int(name[6:])
    return getattr(m, name, None)


def enums_agree(m, text: str = MODEL_H) -> list:
    bad = []
    for enum, (prefix, zero) in ENUMS.items():
        members = header_enum(text, enum)
        if not members or not all(n.startswith(prefix) for n in members):
            bad.append(f"{enum}: not parsed")
            continue
        if sorted(members.values()) != list(range(len(members))):
            bad.append(f"{enum}: values not dense 0..{len(members) - 1}")
        if members.get(zero) != 0:
            bad.append(f"{enum}: {zero} is not 0")
        for n, v in members.items():
            if enum_mirror_value(m, n) != v:
                bad.append(f"{enum}.{n}: header {v} != mirror {enum_mirror_value(m, n)}")
    return bad


check("every model enum (12) is parsed, dense from 0, and numbered exactly as the mirror", not enums_agree(fd),
      str(enums_agree(fd)[:5]))
check("0 is the fail-closed value of every outcome / readback / error-class / class enum (WERR_OTHER, RB_NOT_READ, "
      "KEY_UNKNOWN_REBOOT, TXN_UNKNOWN_REBOOT, REFUSAL_UNSET, PROV_OP_INVALID, W_UNREADABLE, EPC_UNREADABLE, "
      "FBS_UNREADABLE) and the header static_asserts it (incl. zero-initialised outcomes)",
      (fd.WERR_OTHER, fd.RB_NOT_READ, fd.KEY_UNKNOWN_REBOOT, fd.TXN_UNKNOWN_REBOOT, fd.REFUSAL_UNSET, fd.PROV_OP_INVALID,
       fd.W_UNREADABLE, fd.EPC_UNREADABLE, fd.FBS_UNREADABLE) == (0,) * 9
      and "KeyOutcome{} == KEY_UNKNOWN_REBOOT && TxnOutcome{} == TXN_UNKNOWN_REBOOT && ReadbackClass{} == RB_NOT_READ" in MODEL_H)
check("a zero-initialised result is fail-closed: KeyReport() outcome UNKNOWN_REBOOT, TxnResult() refusal UNSET, "
      "EffectiveProfile {0,0,0} not writer-usable", fd.KeyReport().outcome == fd.KEY_UNKNOWN_REBOOT
      and fd.TxnResult().refusal == fd.REFUSAL_UNSET and not fd.profile_writer_usable(0, 0))
check("EffectiveProfileClass 0..5 share FB-A ProfileClass numbering (header static_assert; mirror)",
      (fd.EPC_UNREADABLE, fd.EPC_NOT_CAPTURED, fd.EPC_CORRUPT, fd.EPC_CORRUPT_DOMAIN, fd.EPC_INVALIDATED, fd.EPC_VALID)
      == (fp.PROFILE_UNREADABLE, fp.PROFILE_NOT_CAPTURED, fp.PROFILE_CORRUPT, fp.PROFILE_CORRUPT_DOMAIN,
          fp.PROFILE_INVALIDATED, fp.PROFILE_VALID) and "(int) EPC_VALID == (int) ecco_fallback::PROFILE_VALID" in MODEL_H)
check("WitnessClass numbering mirrors FB-A FailbackRecordClass (UNREADABLE 0, ABSENT 1, CORRUPT 2, VALID 3)",
      (fd.W_UNREADABLE, fd.W_ABSENT, fd.W_CORRUPT, fd.W_VALID) == (fp.FAILBACK_RECORD_UNREADABLE, fp.FAILBACK_RECORD_ABSENT,
                                                                  fp.FAILBACK_RECORD_CORRUPT, fp.FAILBACK_RECORD_VALID))

# ===========================================================================
print("[5] Per-key outcome table and readback classes (exhaustive vs spec oracle)")
# ===========================================================================
IDF_CODES = sorted({v for n, v in vars(fd).items() if n.startswith("IDF_") and isinstance(v, int)} |
                   set(range(-8, 0x40)) | set(range(0x100, 0x120)) | set(range(0x1100, 0x1120)) | {0x6001, 0x6002, 0x6003})


def spec_pre_write(e: int) -> bool:  # FINAL 4.3 row 2, verbatim: exactly these three codes
    return e in (0x1107, 0x1104, 0x1101)  # INVALID_HANDLE, READ_ONLY, NOT_INITIALIZED


def outcome_oracle(e: int, rb: int, healthy: bool) -> int:
    if e == 0 and rb == fd.RB_INTENDED and healthy:
        return fd.KEY_COMMITTED
    if spec_pre_write(e) and rb == fd.RB_PRIOR and healthy:
        return fd.KEY_NOT_COMMITTED
    return fd.KEY_UNKNOWN_REBOOT


def outcome_table_agrees(m) -> list:
    bad = []
    for e in IDF_CODES:
        want = m.WERR_OK if e == 0 else (m.WERR_PRE_WRITE if spec_pre_write(e) else m.WERR_OTHER)
        if m.classify_write_err(e) != want:
            bad.append(f"classify_write_err({e:#x})")
        for rb in range(8):
            for healthy in (False, True):
                if m.classify_key_outcome(m.classify_write_err(e), rb, healthy) != outcome_oracle(e, rb, healthy):
                    bad.append(f"outcome({e:#x}, rb {rb}, healthy {healthy})")
    return bad


check(f"per-key outcome over {len(IDF_CODES)} result codes x 8 readback classes x health == the architecture 4.3 table: "
      "COMMITTED only (OK, INTENDED, healthy); NOT_COMMITTED only (INVALID_HANDLE / READ_ONLY / NOT_INITIALIZED, "
      "PRIOR, healthy); every other cell UNKNOWN_REBOOT; NOT_ATTEMPTED never produced", not outcome_table_agrees(fd),
      str(outcome_table_agrees(fd)[:4]))
pre = re.search(r"constexpr WriteErrClass classify_write_err\(int32_t e\) \{(.*?)\n\}", MODEL_H, re.S)
pre_names = set(re.findall(r"e == (IDF_\w+)", pre.group(1))) if pre else set()
check("the header's classify_write_err names exactly IDF_OK plus the three pre-write codes, whose values are the "
      "IDF 5.5.5 ones (0x1107, 0x1104, 0x1101); the adapter static_asserts each against the real macro",
      pre_names == {"IDF_OK", "IDF_ERR_NVS_INVALID_HANDLE", "IDF_ERR_NVS_READ_ONLY", "IDF_ERR_NVS_NOT_INITIALIZED"}
      and {header_const(MODEL_H, n) for n in pre_names - {"IDF_OK"}} == {0x1107, 0x1104, 0x1101}
      and all(f"{n} == ESP_ERR_NVS_{n[12:]}" in ADAPTER_H for n in pre_names - {"IDF_OK"}), str(pre_names))
LOADS = (fp.LOAD_OK, fp.LOAD_ABSENT, fp.LOAD_WRONG_SIZE, fp.LOAD_READ_ERROR, fp.LOAD_STORAGE_UNAVAILABLE, 5, 9, 255)


def readback_oracle(rb_load, rb_len, eq_int, prior_load, prior_len, eq_prior) -> int:
    """S2 1.6 / header comment: RB_PRIOR needs a POSITIVE match of the prior - equal bytes for a present record,
    ABSENT for an absent one, the same stored length for a wrong-size one."""
    table = [
        (lambda: rb_load == fp.LOAD_OK and eq_int, fd.RB_INTENDED),
        (lambda: rb_load == fp.LOAD_OK and prior_load == fp.LOAD_OK and eq_prior, fd.RB_PRIOR),
        (lambda: rb_load == fp.LOAD_OK, fd.RB_OTHER_BYTES),
        (lambda: rb_load == fp.LOAD_ABSENT and prior_load == fp.LOAD_ABSENT, fd.RB_PRIOR),
        (lambda: rb_load == fp.LOAD_ABSENT, fd.RB_ABSENT_UNEXPECTED),
        (lambda: rb_load == fp.LOAD_WRONG_SIZE and prior_load == fp.LOAD_WRONG_SIZE and prior_len == rb_len, fd.RB_PRIOR),
        (lambda: rb_load == fp.LOAD_WRONG_SIZE, fd.RB_WRONG_SIZE),
        (lambda: rb_load == fp.LOAD_STORAGE_UNAVAILABLE, fd.RB_UNAVAILABLE),
        (lambda: True, fd.RB_READ_ERROR),
    ]
    return next(v for cond, v in table if cond())


def readback_agrees(m) -> list:
    bad = []
    for rb_load in LOADS:
        for rb_len in (40, 48, 52):
            for eq_int in (False, True):
                for prior_load in LOADS:
                    for prior_len in (40, 48, 52):
                        for eq_prior in (False, True):
                            got = m.readback_class(rb_load, rb_len, eq_int, prior_load, prior_len, eq_prior)
                            if got != readback_oracle(rb_load, rb_len, eq_int, prior_load, prior_len, eq_prior):
                                bad.append((rb_load, rb_len, eq_int, prior_load, prior_len, eq_prior))
    return bad


check("readback_class over every (readback load x length x eq-intended x prior load x prior length x eq-prior) == the "
      "positive-prior-match oracle (13,824 cells)", not readback_agrees(fd), str(readback_agrees(fd)[:3]))
check("NOT_COMMITTED is reachable ONLY through a positive prior match: no (pre-write code, readback) cell other than "
      "RB_PRIOR yields it, and an unexpected ABSENT / other bytes / read error never does",
      all(fd.classify_key_outcome(fd.WERR_PRE_WRITE, rb, True) == fd.KEY_UNKNOWN_REBOOT for rb in range(8) if rb != fd.RB_PRIOR))

# ===========================================================================
print("[6] Witness classifier: golden cases parsed from the header + sweeps")
# ===========================================================================


def resolve(tok: str, m, extra: dict | None = None) -> int:
    tok = tok.strip()
    if extra and tok in extra:
        return extra[tok]
    if tok.startswith("ecco_fallback::"):
        return getattr(fp, tok.split("::", 1)[1])
    if re.fullmatch(r"-?(0x[0-9A-Fa-f]+|\d+)[uU]?", tok):
        return c_int(tok)
    if tok.startswith("RULE_B") and tok != "RULE_B2A":
        return int(tok[6:])
    return getattr(m, tok)


def witness_cases_agree(m, text: str = MODEL_H) -> list:
    rows = table_rows(text, "WITNESS_GOLDEN_CASES")
    if len(rows) < 40:
        return ["table not parsed"]
    r = build_records(m)
    bad = []
    for row in rows:
        base, load, off_a, val_a, off_b, val_b, reseal, defect, expected = (resolve(t, m) for t in row)
        raw = m.pack_provision(r["w_first"] if base == 0 else r["w_inv"])
        if off_a != 0xFF:
            raw = m.pack_u16_at(raw, off_a, val_a)
        if off_b != 0xFF:
            raw = m.pack_u16_at(raw, off_b, val_b)
        w = m.unpack_provision(raw)
        if reseal:
            w = m.seal_provision(w)
        if m.witness_defect(w) != defect or m.classify_witness(load, w) != expected:
            bad.append(row)
    return bad


WROWS = table_rows(MODEL_H, "WITNESS_GOLDEN_CASES")
check(f"all {len(WROWS)} header witness golden cases hold in the mirror (load first, then the first failing defect "
      "rule, re-seal semantics)", len(WROWS) >= 40 and not witness_cases_agree(fd), str(witness_cases_agree(fd)[:2]))
check("the witness golden cases cover every defect rule (NONE, MAGIC ... RECSCHEMA) and every witness class",
      {resolve(r[7], fd) for r in WROWS} == set(range(11)) and {resolve(r[8], fd) for r in WROWS} == {0, 1, 2, 3})
DEFECT_RULES = [  # S2 2.3 / FINAL 4.5, in precedence order
    (fd.WIT_DEFECT_MAGIC, lambda w, raw: w["magic"] != 0x45434657),
    (fd.WIT_DEFECT_SCHEMA, lambda w, raw: w["schema"] != 1),
    (fd.WIT_DEFECT_SIZE, lambda w, raw: w["size"] != 48),
    (fd.WIT_DEFECT_BINDING, lambda w, raw: w["binding"] != fp.fnv1a_64(b"ECCO-FAILBACK-PROVISION-v1" + raw[:40])),
    (fd.WIT_DEFECT_FLAGS, lambda w, raw: w["flags"] != 0),
    (fd.WIT_DEFECT_HW, lambda w, raw: w["hw_generation"] == 0),
    (fd.WIT_DEFECT_PRIOR, lambda w, raw: w["prior_generation"] >= w["hw_generation"]
     or (w["prior_generation"] == 0) != (w["prior_binding"] == 0)),
    (fd.WIT_DEFECT_OP, lambda w, raw: w["last_op"] not in (1, 2, 3)),
    (fd.WIT_DEFECT_TAG, lambda w, raw: w["hw_tag_key"] == 0),
    (fd.WIT_DEFECT_RECSCHEMA, lambda w, raw: w["hw_record_schema"] == 0),
]


def defect_oracle(w: dict) -> int:
    raw = fd.pack_provision(w)
    return next((d for d, cond in DEFECT_RULES if cond(w, raw)), fd.WIT_DEFECT_NONE)


def witness_class_oracle(load: int, w: dict) -> int:
    if load == fp.LOAD_ABSENT:
        return fd.W_ABSENT
    if load == fp.LOAD_WRONG_SIZE:
        return fd.W_CORRUPT
    if load != fp.LOAD_OK:
        return fd.W_UNREADABLE
    return fd.W_VALID if defect_oracle(w) == fd.WIT_DEFECT_NONE else fd.W_CORRUPT


SWEEP = []
for op in range(256):
    SWEEP.append(fd.seal_provision(dict(wi, last_op=op)))
for fl in range(256):
    SWEEP.append(fd.seal_provision(dict(wi, flags=fl)))
for hw in range(5):
    for pg in range(5):
        for pbv in (0, 0x77):
            SWEEP.append(fd.seal_provision(dict(wi, hw_generation=hw, prior_generation=pg, prior_binding=pbv)))
for tagv in (0, 1, K, 0xFFFFFFFF):
    for sch in (0, 1, 2, 0xFFFF):
        SWEEP.append(fd.seal_provision(dict(wi, hw_tag_key=tagv, hw_record_schema=sch)))
for mg in (0, 0x45434656, 0x45434657, 0x45434658, 0xFFFFFFFF):
    for scv in (0, 1, 2):
        for sz in (0, 47, 48, 49, 96):
            SWEEP.append(fd.seal_provision(dict(wi, magic=mg, schema=scv, size=sz)))


def witness_sweep_agrees(m) -> list:
    bad = []
    for w in SWEEP:
        if m.witness_defect(w) != defect_oracle(w):
            bad.append(("defect", w["last_op"], w["flags"], w["hw_generation"]))
        for load in LOADS:
            if m.classify_witness(load, w) != witness_class_oracle(load, w):
                bad.append(("class", load))
    return bad


check(f"witness defect / class sweeps ({len(SWEEP)} re-sealed records x 8 loads: every last_op, every flags value, "
      "hw x prior x prior_binding grid, tag x record-schema, magic x schema x size) == the spec precedence oracle",
      not witness_sweep_agrees(fd), str(witness_sweep_agrees(fd)[:3]))

# ===========================================================================
print("[7] compose_profile_class: header golden cases + exhaustive spec oracle")
# ===========================================================================
AUTH = (fp.PROFILE_VALID, fp.PROFILE_INVALIDATED, fp.PROFILE_CORRUPT_DOMAIN)


def compose_oracle(p_load, p, w_load, w, anomaly):
    """S2 2.5 table B1..B15 (+ B2a, B5 with hw == 1), transcribed as a first-match decision list."""
    c = fp.classify_profile(p_load, p)
    wc = witness_class_oracle(w_load, w)
    auth = c in AUTH
    g, b = (p["generation"], p["binding"]) if p_load == fp.LOAD_OK else (None, None)
    rows = [
        (1, lambda: c == fp.PROFILE_UNREADABLE, (fd.EPC_UNREADABLE, fd.WHY_PROFILE_READ)),
        (2, lambda: wc == fd.W_UNREADABLE, (fd.EPC_UNREADABLE, fd.WHY_WITNESS_READ)),
        (16, lambda: anomaly != 0, (fd.EPC_UNREADABLE, fd.WHY_READ_ANOMALY)),
        (3, lambda: c == fp.PROFILE_CORRUPT, (fd.EPC_CORRUPT, fd.WHY_NONE)),
        (4, lambda: c == fp.PROFILE_NOT_CAPTURED and wc == fd.W_ABSENT, (fd.EPC_NOT_CAPTURED, fd.WHY_NONE)),
        (5, lambda: c == fp.PROFILE_NOT_CAPTURED and wc == fd.W_VALID and w["prior_generation"] == 0
         and w["last_op"] == fd.PROV_OP_SAVE and w["hw_generation"] == 1, (fd.EPC_PROFILE_LOST, fd.WHY_FIRST_SAVE_UNCONFIRMED)),
        (6, lambda: c == fp.PROFILE_NOT_CAPTURED and wc == fd.W_VALID, (fd.EPC_PROFILE_LOST, fd.WHY_NONE)),
        (7, lambda: c == fp.PROFILE_NOT_CAPTURED and wc == fd.W_CORRUPT, (fd.EPC_PROFILE_LOST, fd.WHY_LOST_WIT_CORRUPT)),
        (8, lambda: auth and wc == fd.W_VALID and g > w["hw_generation"], (c, fd.WHY_WIT_LAGGING)),
        (9, lambda: auth and wc == fd.W_VALID and (w["hw_tag_key"] != K or w["hw_record_schema"] != 1),
         (fd.EPC_PROFILE_STALE, fd.WHY_SUPERSEDED)),
        (10, lambda: auth and wc == fd.W_VALID and g == w["hw_generation"] and b == w["hw_binding"], (c, fd.WHY_NONE)),
        (11, lambda: auth and wc == fd.W_VALID and g == w["hw_generation"], (fd.EPC_PROFILE_STALE, fd.WHY_MISMATCH)),
        (12, lambda: auth and wc == fd.W_VALID and g == w["prior_generation"] and b == w["prior_binding"],
         (fd.EPC_PROFILE_STALE, fd.WHY_INTERRUPTED)),
        (13, lambda: auth and wc == fd.W_VALID, (fd.EPC_PROFILE_STALE, fd.WHY_ROLLBACK)),
        (14, lambda: auth and wc == fd.W_ABSENT, (c, fd.WHY_WIT_MISSING)),
        (15, lambda: auth and wc == fd.W_CORRUPT, (c, fd.WHY_WIT_CORRUPT)),
    ]
    for rule, cond, (cls, why) in rows:
        if cond():
            return cls, why, rule
    raise AssertionError("compose oracle: no row matched (the table must be total)")


def compose_cases_agree(m, text: str = MODEL_H) -> list:
    rows = table_rows(text, "COMPOSE_GOLDEN_CASES")
    if len(rows) < 40:
        return ["table not parsed"]
    r = build_records(m)
    consts = {n: int(v) for n, v in re.findall(r"\b((?:PV|WV)_\w+) = (\d+)", text)}
    pv_by = {consts[n]: rec for n, rec in r["pv"].items() if n in consts}
    wv_by = {consts[n]: rec for n, rec in r["wv"].items() if n in consts}
    if len(pv_by) != 8 or len(wv_by) != 15:
        return ["variant constants not parsed"]
    bad = []
    for row in rows:
        p_load, pvn, w_load, wvn, anomaly, cls, why, rule = (resolve(t, m, consts) for t in row)
        got = m.compose_profile_class(p_load, pv_by[pvn], w_load, wv_by[wvn], anomaly)
        if tuple(got) != (cls, why, rule):
            bad.append((row, got))
    return bad


CROWS = table_rows(MODEL_H, "COMPOSE_GOLDEN_CASES")
check(f"all {len(CROWS)} header compose golden cases hold in the mirror (class, why AND deciding rule)",
      len(CROWS) >= 40 and not compose_cases_agree(fd), str(compose_cases_agree(fd)[:2]))
check("the compose golden cases exercise every rule B1..B15 and B2a",
      {resolve(r[7], fd) for r in CROWS} == set(range(1, 17)))
check("...and every row also agrees with the spec oracle (the header table itself matches S2 2.5)",
      bool(CROWS) and all(compose_oracle(resolve(r[0], fd), REC["pv"][r[1]], resolve(r[2], fd), REC["wv"][r[3]], resolve(r[4], fd))
                          == (resolve(r[5], fd), resolve(r[6], fd), resolve(r[7], fd)) for r in CROWS))


def wvar_text_agrees(text: str = MODEL_H) -> list:
    """The Python variant builders are checked against the header's witness_variant() make_provision() calls."""
    body = re.search(r"constexpr FailbackProvisionV1 witness_variant\(uint8_t v\) \{(.*?)\n\}", text, re.S)
    if not body:
        return ["witness_variant not found"]
    env = {"K": K, "S": S1, "G": GOLD7["binding"], "PROV_OP_SAVE": 1, "PROV_OP_INVALIDATE": 2,
           "profile_with_generation(ecco_fallback::GOLDEN_PROFILE_V1, 1u).binding": REC["g1"]["binding"],
           "profile_variant(PV_DOM7).binding": REC["dom7"]["binding"]}
    bad, seen = [], 0
    for name, args in re.findall(r"if \(v == (WV_\w+)\)\s*return make_provision\(([^;]*?)\);", body.group(1), re.S):
        vals = [env[a] if a in env else c_int(a) for a in split_args(" ".join(args.split()))]
        seen += 1
        if fd.make_provision(*vals) != REC["wv"][name]:
            bad.append(name)
    return bad if seen == 11 else [f"parsed {seen} make_provision variants"]


check("the Python witness variants equal the header's witness_variant() make_provision() calls (11 variants parsed "
      "and evaluated; FIRST/INV/BAD/ZERO are the goldens and their corruption)", not wvar_text_agrees(), str(wvar_text_agrees()))
P_LOADS = (fp.LOAD_OK, fp.LOAD_ABSENT, fp.LOAD_WRONG_SIZE, fp.LOAD_READ_ERROR, fp.LOAD_STORAGE_UNAVAILABLE, 7)
EXTRA_W = [fd.make_provision(g, bnd, pg, pbd, tg, sc, op) for g, bnd, pg, pbd, tg, sc, op in (
    (7, GOLD7["binding"], 6, 0x6666, K, 1, 3), (7, GOLD7["binding"], 6, 0x6666, K, 1, 2), (5, 0x55, 0, 0, K, 1, 1),
    (1, 0x11, 0, 0, K, 1, 3), (8, REC["inv8"]["binding"], 7, GOLD7["binding"], 0x12345678, 1, 2),
    (0xFFFFFFFF, 0xAB, 0xFFFFFFFE, 0xCD, K, 1, 1), (9, gen(GOLD7, 9)["binding"], 0, 0, K, 1, 1))]
EXTRA_P = [gen(GOLD7, 1), gen(GOLD7, 0xFFFFFFFF), fp.seal_profile(dict(GOLD7, reg245=0)), fd.invalidate_profile_cxx(gen(GOLD7, 5))]


def compose_exhaustive(m, loads=P_LOADS, anomalies=(0, 1, 2, 4, 7), extra=True) -> tuple[int, list]:
    ps = list(REC["pv"].values()) + (EXTRA_P if extra else [])
    ws = list(REC["wv"].values()) + (EXTRA_W if extra else [])
    n, bad = 0, []
    for p_load in loads:
        for p in ps:
            for w_load in loads:
                for w in ws:
                    for an in anomalies:
                        n += 1
                        got = tuple(m.compose_profile_class(p_load, p, w_load, w, an))
                        if got != compose_oracle(p_load, p, w_load, w, an):
                            bad.append((p_load, w_load, an, got))
    return n, bad


n_comp, bad_comp = compose_exhaustive(fd)
check(f"compose_profile_class == the S2 2.5 oracle on the full cross product ({n_comp} inputs: 6 loads x 12 profiles x "
      "6 loads x 22 witnesses x 5 anomaly masks), never SAVE_UNCONFIRMED", not bad_comp, str(bad_comp[:3]))

# ===========================================================================
print("[8] Permissions, writer-usable, generation (header static_asserts re-evaluated)")
# ===========================================================================
check("writer-usable is EXACTLY (VALID, WHY_NONE) over all 9 x 13 (class, why) pairs (A5 / D10: B8 lagging, B14 "
      "missing, B15 corrupt witness are not usable)",
      [(c, w) for c in range(9) for w in range(13) if fd.profile_writer_usable(c, w)] == [(fd.EPC_VALID, fd.WHY_NONE)])
check("SAVE permitted for every class except UNREADABLE and SAVE_UNCONFIRMED; the REPLACE CORRUPT phrase exactly for "
      "CORRUPT; INVALIDATE exactly for VALID (architecture 4.6 table)",
      [c for c in range(9) if fd.save_class_permitted(c)] == [1, 2, 3, 4, 5, 6, 8]
      and [c for c in range(9) if fd.save_requires_replace_phrase(c)] == [fd.EPC_CORRUPT]
      and [c for c in range(9) if fd.invalidate_class_permitted(c)] == [fd.EPC_VALID])


def static_assert_terms(text: str, message_fragment: str) -> list[str]:
    m = re.search(r"static_assert\(((?:(?!static_assert).)*?),\s*\"[^\"]*" + re.escape(message_fragment), text, re.S)
    if not m:
        return []
    return [t.strip() for t in " ".join(m.group(1).split()).split("&&")]


def eval_term(term: str, m) -> bool:
    neg = term.startswith("!")
    term = term[1:] if neg else term
    mm = re.fullmatch(r"(\w+)\((.*?)\)(?: == (.+))?", term)
    if not mm:
        raise ValueError(f"unparsed static_assert term {term!r}")
    fn, args, want = mm.group(1), mm.group(2), mm.group(3)

    def val(tok: str) -> int:
        tok = tok.strip()
        if tok.endswith(" - 1u"):
            return val(tok[:-5]) - 1
        return resolve(tok, m)

    got = getattr(m, fn)(*[val(a) for a in args.split(",")])
    result = (got == val(want)) if want is not None else bool(got)
    return (not result) if neg else result


def generation_asserts_agree(m, text: str = MODEL_H) -> list:
    bad = []
    for frag in ("only VALID && WHY_NONE is writer-usable", "SAVE generation base = max(authentic g, W_VALID hw, seen)",
                 "INVALIDATE requires g < max and g + 1 > max(hw, seen)"):
        terms = static_assert_terms(text, frag)
        if len(terms) < 5:
            bad.append(f"{frag}: not parsed")
        for t in terms:
            try:
                if not eval_term(t, m):
                    bad.append(t)
            except Exception as e:  # noqa: BLE001 - an unparsable / crashing term is a failure
                bad.append(f"{t}: {e}")
    return bad


check("every term of the header's writer-usable / SAVE-generation / INVALIDATE-generation static_asserts is "
      "re-evaluated against the mirror and holds (C++ == Python on the pinned points)", not generation_asserts_agree(fd),
      str(generation_asserts_agree(fd)[:3]))
GVALS = (0, 1, 6, 7, 8, 12, 0xFFFFFFFE, 0xFFFFFFFF)


def generation_agrees(m) -> list:
    bad = []
    for cls in range(6):
        for wc in range(4):
            for g in GVALS:
                for hw in GVALS:
                    for seen in GVALS:
                        want = max(g if cls in AUTH else 0, hw if wc == fd.W_VALID else 0, seen)
                        if m.save_generation_base(cls, g, wc, hw, seen) != want:
                            bad.append(("base", cls, wc, g, hw, seen))
                        if m.next_seen_hw_gen(seen, cls, g, wc, hw) != want:
                            bad.append(("seen", cls, wc, g, hw, seen))
                        if cls == 0 and m.invalidate_generation_permitted(g, wc, hw, seen) != (
                                g < 0xFFFFFFFF and g + 1 > (hw if wc == fd.W_VALID else 0) and g + 1 > seen):
                            bad.append(("inv", wc, g, hw, seen))
    return bad


check("generation (architecture 3.9 / S2 m11) exhaustively over classes x witness classes x g x hw x seen: SAVE base = "
      "max(authentic g, W_VALID hw, seen_hw_gen) (CORRUPT / NOT_CAPTURED g never counts), next seen == the same max, "
      "INVALIDATE iff g < max and g + 1 > max(W_VALID hw, seen)", not generation_agrees(fd), str(generation_agrees(fd)[:3]))
check("never wraps and never goes backwards: base GENERATION_MAX refuses SAVE; a loss (FBP ABSENT, W_VALID hw 12) "
      "still gives 13; a lagging witness never lowers it",
      not fd.save_generation_available(0xFFFFFFFF) and fd.save_generation_available(0xFFFFFFFE)
      and fd.save_generation_base(fp.PROFILE_NOT_CAPTURED, 0, fd.W_VALID, 12, 0) + 1 == 13
      and fd.save_generation_base(fp.PROFILE_VALID, 9, fd.W_VALID, 6, 0) == 9)

# ===========================================================================
print("[9] Per-boot read latch (exhaustive vs oracle)")
# ===========================================================================


def latch_oracle(ps: int, ra: int, bit: int, load: int, healthy: bool) -> tuple[int, int]:
    """S2 5.4 R-D3 / R-D4: OK / WRONG_SIZE mark present; READ_ERROR / STORAGE_UNAVAILABLE / unknown, or ABSENT after
    present this boot, set the key's sticky anomaly bit; an unhealthy store sets bit 2. Nothing is ever cleared."""
    if load in (fp.LOAD_OK, fp.LOAD_WRONG_SIZE):
        ps |= bit
    elif load == fp.LOAD_ABSENT:
        ra |= bit if ps & bit else 0
    else:
        ra |= bit
    return ps, ra | (0 if healthy else 4)


def latch_agrees(m) -> list:
    bad = []
    for ps in range(4):
        for ra in range(8):
            for bit in (1, 2):
                for load in range(256):
                    for healthy in (False, True):
                        got = m.note_read(ps, ra, bit, load, healthy)
                        if tuple(got) != latch_oracle(ps, ra, bit, load, healthy):
                            bad.append((ps, ra, bit, load, healthy))
                        if (got[0] & ps) != ps or (got[1] & ra) != ra:
                            bad.append(("cleared", ps, ra, bit, load))
                if tuple(m.note_committed(ps, ra, bit)) != (ps | bit, ra):
                    bad.append(("committed", ps, ra, bit))
    return bad


check("note_read over every (present_seen x read_anomaly x key bit x load 0..255 x health) == the S2 5.4 oracle; bits "
      "are never cleared; note_committed sets only the present bit (32,768 transitions)", not latch_agrees(fd),
      str(latch_agrees(fd)[:3]))
check("the same-boot flip READ_ERROR -> (erased) ABSENT is caught: after an unreadable read, a later ABSENT read still "
      "composes UNREADABLE (READ_ANOMALY, B2a) instead of NOT_CAPTURED / LOST",
      (lambda s: fd.compose_profile_class(fp.LOAD_ABSENT, REC["pv"]["PV_ZERO"], fp.LOAD_ABSENT, REC["wv"]["WV_ZERO"], s[1])[:2]
       == (fd.EPC_UNREADABLE, fd.WHY_READ_ANOMALY))(fd.note_read(0, 0, 1, fp.LOAD_READ_ERROR, True)))
latch_fn = re.search(r"constexpr bool read_latch_transitions_hold\(\) \{(.*?)\n\}", MODEL_H, re.S)
check("the header static_asserts its own latch transitions (sticky, same-boot vanish, per-key bits, unknown load, "
      "health bit, note_committed)", latch_fn is not None and "static_assert(read_latch_transitions_hold()" in MODEL_H
      and latch_fn.group(1).count("note_read(") >= 10)

# ===========================================================================
print("[10] Transaction semantics of the mirror (witness first, refusals, RAM mirror)")
# ===========================================================================
G8 = gen(GOLD7, 8, captured_epoch=1790086400)
W7 = fd.make_provision(7, GOLD7["binding"], 6, 0x6666, K, S1, fd.PROV_OP_SAVE)
W8 = fd.make_provision(8, G8["binding"], 7, GOLD7["binding"], K, S1, fd.PROV_OP_SAVE)
PB, WB = fp.pack_profile, fd.pack_provision


def txn(m, faults=(), latch=False, healthy=True, handle_at_commit=1, prior_p=None, prior_w=None, new_p=None, new_w=None):
    nvs = H.DirectNvs()
    nvs.put(m.FALLBACK_PROFILE_KEY, PB(prior_p or GOLD7))
    nvs.put(m.FAILBACK_PROVISION_KEY, WB(prior_w or W7))
    for key, f in faults:
        nvs.faults.setdefault(m.FAILBACK_PROVISION_KEY if key == "W" else m.FALLBACK_PROFILE_KEY, []).append(f)
    pl, pbytes, dp = m.read_direct(nvs, m.FALLBACK_PROFILE_KEY, 96)
    wl, wbytes, dw = m.read_direct(nvs, m.FAILBACK_PROVISION_KEY, 48)
    nvs.ops.clear()
    nvs.healthy = healthy
    nvs.handle_value = handle_at_commit
    lt = m.WriteLatch(latch)
    o, r = m.commit_transition(nvs, lt, WB(new_w or W8), wbytes, (wl, dw.stored_len), PB(new_p or G8), pbytes,
                               (pl, dp.stored_len))
    return o, r, lt, nvs, m.mirror_after(o, r, pbytes, pl, wbytes, wl)


def txn_probes(m) -> list:
    bad = []
    o, r, lt, nvs, mir = txn(m)
    sets = [op[1] for op in nvs.ops if op[0] == "set"]
    if (o, sets, lt.write_latched) != (m.TXN_COMMITTED, ["1000595297", "1609458070"], False) or mir[0] != PB(G8):
        bad.append(("clean", o, sets))
    if [op[0] for op in nvs.ops] != ["stats", "set", "get", "read", "stats", "set", "get", "read", "stats"]:
        bad.append(("event order", [op[0] for op in nvs.ops]))
    o, r, lt, nvs, _m = txn(m, [("W", H.WriteFault(fd.IDF_ERR_NVS_READ_ONLY, H.VIS_OLD))])
    if (o, r.p.outcome, lt.write_latched, nvs.set_count()) != (m.TXN_NOT_COMMITTED, m.KEY_NOT_ATTEMPTED, False, 1):
        bad.append(("W pre-write", o))
    o, r, lt, nvs, mir = txn(m, [("W", H.WriteFault(fd.IDF_OK, H.VIS_OTHER, other=WB(W7)[:40] + bytes(8)))])
    if (o, r.p.outcome, lt.write_latched, nvs.set_count()) != (m.TXN_UNKNOWN_REBOOT, m.KEY_NOT_ATTEMPTED, True, 1) \
            or mir[:2] != (PB(GOLD7), WB(W7)):
        bad.append(("W other bytes", o, lt.write_latched))
    o, r, lt, nvs, _m = txn(m, latch=True)
    if (o, r.refusal, nvs.set_count()) != (m.TXN_REFUSED_LATCHED, m.REFUSAL_LATCHED, 0):
        bad.append(("latched", o))
    o, r, lt, nvs, _m = txn(m, healthy=False)
    if (o, r.refusal, nvs.set_count()) != (m.TXN_REFUSED_LATCHED, m.REFUSAL_STORAGE_UNHEALTHY, 0):
        bad.append(("unhealthy", o))
    o, r, lt, nvs, _m = txn(m, handle_at_commit=0)
    if (o, r.refusal, nvs.set_count()) != (m.TXN_REFUSED_LATCHED, m.REFUSAL_STORAGE_UNAVAILABLE, 0):
        bad.append(("handle 0", o))
    o, r, lt, nvs, mir = txn(m, [("W", H.WriteFault()), ("P", H.WriteFault(fd.IDF_ERR_NVS_INVALID_HANDLE, H.VIS_OLD))])
    if (o, bool(r.witness_advanced), lt.write_latched, mir[1]) != (m.TXN_NOT_COMMITTED, True, False, WB(W8)):
        bad.append(("P pre-write", o))
    o, r, lt, nvs, _m = txn(m, [("W", H.WriteFault(healthy_after=False))])
    if (o, r.w.outcome, lt.write_latched, nvs.set_count()) != (m.TXN_UNKNOWN_REBOOT, m.KEY_UNKNOWN_REBOOT, True, 1):
        bad.append(("unhealthy after W", o))
    bad_prior = dict(GOLD7, binding=GOLD7["binding"] + 1)
    wh12 = fd.make_provision(12, 0x1212, 11, 0x1111, K, S1, fd.PROV_OP_SAVE)
    g13 = gen(GOLD7, 13)
    o, r, *_rest = txn(m, prior_p=bad_prior, prior_w=wh12, new_p=g13,
                       new_w=fd.make_provision(13, g13["binding"], 0, 0, K, S1, fd.PROV_OP_SAVE))
    if (o, r.refusal) != (m.TXN_REFUSED_LATCHED, m.REFUSAL_INVALID_TRANSITION):
        bad.append(("plain SAVE over CORRUPT", o))
    o, r, *_rest = txn(m, prior_p=bad_prior, prior_w=wh12, new_p=g13,
                       new_w=fd.make_provision(13, g13["binding"], 0, 0, K, S1, fd.PROV_OP_REPLACE_CORRUPT))
    if o != m.TXN_COMMITTED:
        bad.append(("REPLACE CORRUPT", o))
    nvs = H.DirectNvs()
    nvs.put(m.FALLBACK_PROFILE_KEY, PB(GOLD7), crc_ok=False)
    first = m.read_direct(nvs, m.FALLBACK_PROFILE_KEY, 96)[0]
    second = m.read_direct(nvs, m.FALLBACK_PROFILE_KEY, 96)[0]
    if (first, second) != (fp.LOAD_READ_ERROR, fp.LOAD_READ_ERROR):
        bad.append(("CRC-erased read", first, second))
    return bad


check("mirror transaction probes: clean SAVE = witness set THEN profile set with the exact 9-event order; FBW "
      "pre-write+PRIOR -> NOT_COMMITTED, profile not attempted; FBW OK+other bytes -> UNKNOWN, latch, RAM mirror keeps "
      "the prior; latched / unhealthy / handle 0 -> refused with zero sets; FBP pre-write after FBW OK -> "
      "NOT_COMMITTED with the witness advanced; plain SAVE over CORRUPT refused, REPLACE CORRUPT accepted; a CRC-bad "
      "chunk reads READ_ERROR, then (erased index) READ_ERROR again (never ABSENT on the same step)",
      not txn_probes(fd), str(txn_probes(fd)[:3]))
_nvs_third = H.DirectNvs()
e_third = raises(lambda: fd.write_one(_nvs_third, fd.WriteLatch(), fd.FAILBACK_STATE_KEY, bytes(80), bytes(80), 0, 80,
                                      fd.KeyReport()), ValueError)
e_size = raises(lambda: fd.write_one(_nvs_third, fd.WriteLatch(), fd.FAILBACK_PROVISION_KEY, bytes(96), bytes(96), 0, 96,
                                     fd.KeyReport()), ValueError)
check("the Python write path refuses a third target: write_one(FAILBACK_STATE_KEY) and an FBW write of the profile's "
      "size raise ValueError naming exclusivity pin X2, and touch nothing",
      e_third is not None and "exclusivity pin X2" in str(e_third) and e_size is not None and not _nvs_third.ops)

# ===========================================================================
print("[11] Exclusivity X1-X4 / X7 and ZERO runtime call sites")
# ===========================================================================
CODE_SUFFIXES = {".h", ".hpp", ".c", ".cpp", ".cc"}


def firmware_code_files() -> dict:
    """Every C/C++ source under firmware/ (tracked or new), path -> text."""
    return {p.relative_to(ROOT).as_posix(): p.read_text(encoding="utf-8") for p in sorted((ROOT / "firmware").rglob("*"))
            if p.is_file() and p.suffix in CODE_SUFFIXES and ".esphome" not in p.parts}


def firmware_yaml_files() -> dict:
    files = {p.relative_to(ROOT).as_posix(): p.read_text(encoding="utf-8") for p in sorted((ROOT / "firmware").glob("*.yaml"))
             if p.name != "secrets.yaml"}
    files[fbbs.FIRMWARE_REL] = FW_TEXT        # the production firmware as of chain entry fbb0 (a later PR's call sites are its own)
    return files


# FB-C1 (chain entry fbc1, merged before FB-B0) declares five `ecco_failback_shadow_*` substitution KEYS, and its RAM-only
# interval reads them as `${...}`. They are not FB-B0 durable runtime, and the scans below must not start exempting a name
# PREFIX (FB-T0 forbids prefix / glob exemptions): only the EXACT key strings the chain entries declare are removed from the
# text before the scan, so an undeclared `ecco_failback_shadow_extra_ms`, an `ecco_failback_provision_v1` or any other
# ecco_fallback* / ecco_failback* token still counts.
DECLARED_SUBST_KEYS = tuple(sorted(chain.CHAIN.declared_subst(), key=len, reverse=True))


def without_declared_subst(text: str, keys=DECLARED_SUBST_KEYS) -> str:
    for key in keys:
        text = text.replace(key, "")
    return text


def lambdas_of(node, out=None) -> list[str]:
    out = [] if out is None else out
    if isinstance(node, dict):
        for k, v in node.items():
            if k == "lambda" and isinstance(v, str):
                out.append(v)
            else:
                lambdas_of(v, out)
    elif isinstance(node, list):
        for v in node:
            lambdas_of(v, out)
    elif isinstance(node, ds.LambdaStr):
        out.append(str(node))
    return out


def yaml_lambdas(text: str) -> list[str]:
    doc = ds.load_firmware_text(text)
    return lambdas_of({k: v for k, v in doc.items() if not k.startswith("_")})


NVS_WRITE_RE = re.compile(r"\bnvs_(?:set_\w+|erase\w*|commit)\b")


def x1_violations(code_files: dict, yaml_texts: dict) -> list:
    bad = []
    for rel, text in code_files.items():
        hits = NVS_WRITE_RE.findall(strip_code(text))
        if rel == "firmware/include/ecco_fallback_durable.h":
            if hits != ["nvs_set_blob"] or len(re.findall(r"\bnvs_set_blob\s*\(", strip_code(text))) != 1:
                bad.append(f"{rel}: {hits}")
        elif hits:
            bad.append(f"{rel}: {hits}")
    for rel, text in yaml_texts.items():
        for lam in yaml_lambdas(text):
            code = fpsim._without_comments(lam)
            if re.search(r"\bnvs_", code):
                bad.append(f"{rel}: a lambda names nvs_")
    return bad


CODE_FILES, YAML_FILES = firmware_code_files(), firmware_yaml_files()
check("X1: nvs_set_blob / nvs_erase_* / nvs_set_* / nvs_commit appear (comment- and string-stripped) in exactly ONE "
      "firmware file, ecco_fallback_durable.h, as exactly one nvs_set_blob( call; no firmware YAML lambda names nvs_ "
      f"({len(CODE_FILES)} C/C++ files, {len(YAML_FILES)} YAMLs scanned)", not x1_violations(CODE_FILES, YAML_FILES),
      str(x1_violations(CODE_FILES, YAML_FILES)))


def x2_violations(model_text: str, others: dict) -> list:
    code = strip_code(model_text)
    inst = re.findall(r"\bwrite_one_<\s*(\w+)\s*,\s*(\w+)\s*>\s*\(", code)
    spec = re.findall(r"template<> struct WriteTarget<(\w+), (\w+)> \{\s*static constexpr bool allowed = true;", code)
    want = [("FailbackProvisionV1", "FAILBACK_PROVISION_KEY"), ("FallbackProfileV1", "FALLBACK_PROFILE_KEY")]
    bad = []
    if inst != want:
        bad.append(f"write_one_ instantiations {inst}")
    if sorted(spec) != sorted(want):
        bad.append(f"WriteTarget specializations {spec}")
    if len(re.findall(r"\.set_blob\(", code)) != 1 or not re.search(r"nvs\.set_blob\(KEY, &intended, sizeof\(T\)\)", code):
        bad.append("set_blob call sites")
    if "static constexpr bool allowed = false;" not in code or "exclusivity pin X2" not in model_text:
        bad.append("primary template / X2 message")
    for rel, text in others.items():
        if re.search(r"\bwrite_one_\s*<|\bWriteTarget\s*<", strip_code(text)):
            bad.append(f"{rel} names write_one_ / WriteTarget")
    return bad


OTHER_CODE = {r: t for r, t in CODE_FILES.items() if not r.endswith("ecco_fallback_durable_model.h")}
check("X2: write_one_< is instantiated exactly twice - (FailbackProvisionV1, FAILBACK_PROVISION_KEY) then "
      "(FallbackProfileV1, FALLBACK_PROFILE_KEY) - the only two WriteTarget specialisations; set_blob is called once, with "
      "the compile-time KEY (no key parameter); no FBS target; no other file names write_one_ / WriteTarget",
      not x2_violations(MODEL_H, {**OTHER_CODE, **YAML_FILES}), str(x2_violations(MODEL_H, {**OTHER_CODE, **YAML_FILES})))
X3_APIS = re.compile(r"preference_for\s*<|commit_record|load_record|load_record_status|make_preference|"
                     r"make_entity_preference|load_from_key")
X3_FB = re.compile(r"FALLBACK_PROFILE_TAG|FAILBACK_PROVISION_TAG|FAILBACK_STATE_TAG|FALLBACK_PROFILE_KEY|"
                   r"FAILBACK_PROVISION_KEY|FAILBACK_STATE_KEY|1609458070|1000595297|2156168643")


def x3_violations(code_files: dict, yaml_texts: dict) -> list:
    bad = []
    units = [(rel, strip_comments(t)) for rel, t in code_files.items()]
    units += [(rel, fpsim._without_comments(lam)) for rel, t in yaml_texts.items() for lam in yaml_lambdas(t)]
    for rel, code in units:
        for piece in re.split(r"[;\n]", code):
            if X3_APIS.search(piece) and X3_FB.search(piece):
                bad.append(f"{rel}: {piece.strip()[:90]}")
    return bad


check("X3: no preference_for< / commit_record / load_record(_status) / make_(entity_)preference / load_from_key on "
      "the same line or statement as an FB tag, key or decimal key string, anywhere under firmware/",
      not x3_violations(CODE_FILES, YAML_FILES), str(x3_violations(CODE_FILES, YAML_FILES)[:3]))
FB_RUNTIME = re.compile(r"ecco_fbdurable|commit_transition|read_direct|read_pair|write_one_|EspNvs|nvs_healthy|"
                        r"storage_healthy|FailbackProvisionV1|FallbackProfileV1|FailbackStateV1|ecco_fallback::|"
                        r"ecco_failback|fallback_profile_|FALLBACK_PROFILE_|FAILBACK_(?:PROVISION|STATE)_")


def call_sites(yaml_texts: dict) -> list:
    sites = []
    for rel, text in yaml_texts.items():
        for lineno, line in enumerate(without_declared_subst(text).splitlines(), 1):
            if FB_RUNTIME.search(line):
                sites.append(f"{rel}:{lineno}")
    return sites


check("X4 / zero runtime call sites: no firmware YAML line - lambda, comment, entity or script - names "
      "ecco_fbdurable, commit_transition, read_direct / read_pair, write_one_, EspNvs, nvs_healthy, an FB record type, "
      "tag or key, or the ecco_fallback:: / ecco_failback namespaces (runtime call-site count 0)",
      not call_sites(YAML_FILES), str(call_sites(YAML_FILES)[:5]))
fb_lines = [ln for ln in without_declared_subst(FW_TEXT).splitlines() if re.search(r"ecco_fallback|ecco_failback", ln)]
check("the ONLY firmware-YAML lines naming ecco_fallback* / ecco_failback* are the four esphome includes entries (== _fbb_scope), "
      "once FB-C1's five EXACT declared substitution keys (chain entry fbc1) are set aside; an undeclared key of the same family "
      "or FB-B0's own tag still counts (negative controls)",
      fb_lines == list(fbbs.FW_FB_TOKEN_LINES)
      and DECLARED_SUBST_KEYS and all(k.startswith("ecco_failback_shadow_") for k in DECLARED_SUBST_KEYS)
      and call_sites({"x.yaml": '  ecco_failback_shadow_extra_ms: "5"\n'}) == ["x.yaml:1"]
      and call_sites({"x.yaml": "  - id(failback_provision) = ecco_failback_provision_v1;\n"}) == ["x.yaml:1"]
      and call_sites({"x.yaml": "  " + DECLARED_SUBST_KEYS[0] + ': "1"\n'}) == [], str(fb_lines))
fb_lambdas = [lam for lam in yaml_lambdas(FW_TEXT) if fpsim.mentions_fallback(without_declared_subst(lam))]
guard_hits = [raises(lambda s=src, lx=lenient: fpsim._ops_for(s, lenient=lx), fpsim.FallbackNotModelled) is not None
              for src in ("ecco_fbdurable::commit_transition_t(nvs, a, b, c, d, e, f, r);", "id(fallback_profile_class) = 5;",
                          "auto k = ecco_fbdurable::FAILBACK_PROVISION_KEY;")
              for lenient in (False, True)]
check("BLK-43: no firmware lambda trips the FP simulator's FallbackNotModelled guard today; the guard raises on FB "
      "lambdas in strict AND lenient mode, on a condition and on a script id, and ignores comments",
      not fb_lambdas and len(guard_hits) == 6 and all(guard_hits)
      and raises(lambda: fpsim.eval_condition("return id(fallback_profile_armed);", {}), fpsim.FallbackNotModelled) is not None
      and raises(lambda: fpsim.guard_against_unmodelled_fallback("fallback_profile_save", "script.execute"),
                 fpsim.FallbackNotModelled) is not None
      and raises(lambda: fpsim.guard_against_unmodelled_fallback("// ecco_fbdurable only in a comment\nx = 1;"),
                 fpsim.FallbackNotModelled) is None)

# X7 (negative controls): each forbidden insertion is killed by its pin.
BOOT_ANCHOR = "          id(ntp_synced_sensor).publish_state(false);\n"
FW_REL = fbbs.FIRMWARE_REL


def inject(line: str) -> dict:
    assert FW_TEXT.count(BOOT_ANCHOR) == 1
    return {**YAML_FILES, FW_REL: FW_TEXT.replace(BOOT_ANCHOR, f"          {line}\n" + BOOT_ANCHOR, 1)}


x7_commit = inject("ecco_durable::commit_record(ecco_fbdurable::FALLBACK_PROFILE_KEY, rec);")
x7_nvs = inject('nvs_set_blob(h, "1609458070", &rec, sizeof(rec));')
x7_txn = inject("ecco_fbdurable::commit_transition_t(nvs, wn, wp, wd, pn, pp, pd, r);")
x7_load = inject("ecco_durable::load_record(1609458070, rec);")
third = MODEL_H.replace("  if (op == KEY_COMMITTED)\n    return TXN_COMMITTED;",
                        "  (void) write_one_<FailbackStateV1, FAILBACK_STATE_KEY>(nvs, s, s, p_pd, s, r.p);\n"
                        "  if (op == KEY_COMMITTED)\n    return TXN_COMMITTED;", 1)
fbs_target = MODEL_H.replace("template<> struct WriteTarget<FallbackProfileV1, FALLBACK_PROFILE_KEY> {",
                             "template<> struct WriteTarget<FailbackStateV1, FAILBACK_STATE_KEY> {\n  static constexpr bool "
                             "allowed = true;\n};\ntemplate<> struct WriteTarget<FallbackProfileV1, FALLBACK_PROFILE_KEY> {", 1)
second_set = ADAPTER_H.replace("    return nvs_get_blob(this->handle(), k, out, len);",
                               "    (void) nvs_set_blob(this->handle(), k, out, *len);\n    return nvs_get_blob(this->handle(), k, out, len);", 1)
erase_in_model = MODEL_H.replace("inline bool write_latched() { return s_write_latched; }",
                                 "inline bool write_latched() { return s_write_latched; }\ninline void wipe(uint32_t h) { nvs_erase_all(h); }", 1)
check("X7: inserting `ecco_durable::commit_record(ecco_fbdurable::FALLBACK_PROFILE_KEY, ...)` into a firmware lambda is "
      "killed by X3 (and by the zero-call-site pin); `ecco_durable::load_record(1609458070, ...)` by X3",
      x3_violations(CODE_FILES, x7_commit) and call_sites(x7_commit) and x3_violations(CODE_FILES, x7_load))
check("X7: a raw nvs_set_blob in a lambda is killed by X1; a commit_transition_t call in a lambda by X4",
      x1_violations(CODE_FILES, x7_nvs) and call_sites(x7_txn) and not x1_violations(CODE_FILES, YAML_FILES))
check("X7: a THIRD write_one_< instantiation (FailbackStateV1 / FAILBACK_STATE_KEY) and a third WriteTarget "
      "specialisation are killed by X2 (the host compile also rejects them)",
      MODEL_H.count("  if (op == KEY_COMMITTED)\n    return TXN_COMMITTED;") == 1 and x2_violations(third, OTHER_CODE)
      and x2_violations(fbs_target, OTHER_CODE))
check("X7: a second nvs_set_blob call in the adapter, or an nvs_erase_all anywhere in the model, is killed by X1",
      x1_violations({**CODE_FILES, "firmware/include/ecco_fallback_durable.h": second_set}, YAML_FILES)
      and x1_violations({**CODE_FILES, "firmware/include/ecco_fallback_durable_model.h": erase_in_model}, YAML_FILES))

# ===========================================================================
print("[12] Header discipline: includes, banned tokens, constexpr, branch-free adapter, version pins")
# ===========================================================================
INCLUDE_RE = re.compile(r"#include\s*([<\"][^>\"]+[>\"])")
check("the model header includes only <array>, <cstddef>, <cstdint>, <type_traits> and the FB-A header (standalone, "
      "host-compilable)", INCLUDE_RE.findall(MODEL_H) == ["<array>", "<cstddef>", "<cstdint>", "<type_traits>",
                                                           '"ecco_fallback_profile.h"'], str(INCLUDE_RE.findall(MODEL_H)))
check("the adapter includes exactly <nvs.h>, the three ESPHome core headers, the version pins and the model",
      INCLUDE_RE.findall(ADAPTER_H) == ["<nvs.h>", "<cstddef>", "<cstdint>", "<type_traits>", '"esphome/core/hal.h"',
                                        '"esphome/core/helpers.h"', '"esphome/core/preferences.h"',
                                        '"ecco_fallback_version_pins.h"', '"ecco_fallback_durable_model.h"'],
      str(INCLUDE_RE.findall(ADAPTER_H)))
check("the version-pin header includes only the generated esphome/core/version.h and esp_idf_version.h",
      INCLUDE_RE.findall(PINS_H) == ['"esphome/core/version.h"', '"esp_idf_version.h"'])
MODEL_BANNED = (("commit_record", r"commit_record"), ("load_record", r"load_record"), ("make_preference", r"make_preference"),
                ("global_preferences", r"global_preferences"), ("nvs_", r"nvs_"), ("modbus", r"(?i)modbus"),
                ("uart", r"(?i)\buart"), ("App.", r"\bApp\."), ("id(", r"\bid\("), ('#include "esphome', r'#\s*include\s*["<]esphome'),
                ("esphome::", r"esphome::"), ("ESP_LOG", r"ESP_LOG"), ("millis(", r"\bmillis\s*\("), ("delay(", r"\bdelay\s*\("))


def banned_hits(text: str) -> list:
    return [label for label, pat in MODEL_BANNED if re.search(pat, text)]


check("the model header (comments included) contains none of: commit_record, load_record, make_preference, "
      "global_preferences, nvs_, modbus, uart, App., id(, #include \"esphome, esphome::, ESP_LOG, millis(, delay( "
      "(FB-A discipline; all I/O goes through the NVS policy)", not banned_hits(MODEL_H), str(banned_hits(MODEL_H)))
CODE_M = strip_comments(MODEL_H)
CODE_M2 = re.sub(r"^(template<[^>\n]*>)\s*\n", r"\1 ", CODE_M, flags=re.M)
KW = r"(?!static_assert\b|struct\b|enum\b|namespace\b|using\b|return\b|if\b|for\b)"
DEFS = re.findall(r"^(?:template<[^>\n]*> )?" + KW + r"((?:constexpr |inline )?[A-Za-z_][\w:<>]*) (\w+)\(", CODE_M2, re.M)
NON_CONSTEXPR = sorted({n for q, n in DEFS if not q.startswith("constexpr")})
check("every model function is constexpr except exactly the policy templates and the latch accessor: "
      "commit_transition_t, read_direct_t, read_pair_t, storage_healthy, write_latched, write_one_",
      len(DEFS) >= 40 and NON_CONSTEXPR == ["commit_transition_t", "read_direct_t", "read_pair_t", "storage_healthy",
                                            "write_latched", "write_one_"], str(NON_CONSTEXPR))
ns_vars = re.findall(r"^(?!static_assert|struct|enum|namespace|using|template|\}|#|\s)(\S[^(\n;]*?)\s(\w+)(?:\[\])? =", CODE_M, re.M)
check("every namespace-scope object is constexpr except the ONE per-boot write latch (inline bool s_write_latched = "
      "false: RAM, reset only by a reboot)", bool(ns_vars) and [n for q, n in ns_vars if not q.startswith("constexpr")]
      == ["s_write_latched"] and re.findall(r"^inline [^\n]*", CODE_M, re.M)
      == ["inline bool s_write_latched = false;", "inline bool write_latched() { return s_write_latched; }"],
      str([n for q, n in ns_vars if not q.startswith("constexpr")]))
ESPNVS = re.search(r"struct EspNvs \{(.*?)\n\};", ADAPTER_H, re.S)
HEALTHY = re.search(r"inline bool nvs_healthy\(\) \{[^\n]*\}", ADAPTER_H)


def branch_hits(text: str) -> list:
    code = strip_code(text)
    return [t for t in (r"\bif\b", r"\belse\b", r"\?", r"\bfor\b", r"\bwhile\b", r"\bdo\b", r"\bswitch\b", r"\bgoto\b",
                        r"&&", r"\|\|", r"\bcatch\b", r"\btry\b") if re.search(t, code)]


def adapter_shape(text: str) -> list:
    bad = []
    s = re.search(r"struct EspNvs \{(.*?)\n\};", text, re.S)
    h = re.search(r"inline bool nvs_healthy\(\) \{ return storage_healthy\(EspNvs\{\}\); \}", text)
    if not s or not h:
        return ["EspNvs / nvs_healthy not found"]
    members = re.findall(r"^\s+(?:[\w:]+ )+(\w+)\((?:[^)]*)\) (?:const )?\{", strip_code(s.group(1)), re.M)
    if members != ["handle", "set_blob", "get_blob", "get_stats", "now_us"]:
        bad.append(f"members {members}")
    code = strip_code(re.sub(r"static_assert\(.*?\);", "", text, flags=re.S))
    outside = code.replace(strip_code(s.group(0)), "").replace(h.group(0), "")
    if re.search(r"\{[^}]*\breturn\b", outside) or re.search(r"\bstruct\b|\bclass\b|\btemplate\b", outside):
        bad.append("definitions outside EspNvs / nvs_healthy")
    if re.search(r"commit_transition|write_one_|read_direct_t|read_pair_t|compose_profile_class|validate_transition", code):
        bad.append("model logic in the adapter")
    if branch_hits(s.group(0) + h.group(0)):
        bad.append(f"branches {branch_hits(s.group(0) + h.group(0))}")
    if "global_preferences->nvs_handle" not in code or code.count("esphome::uint32_to_str(k, key);") != 2:
        bad.append("handle / key rendering")
    return bad


check("the adapter is ONLY EspNvs (handle / set_blob / get_blob / get_stats / now_us) plus nvs_healthy(): "
      "branch-free (no if, else, ?:, loop, switch, goto, &&, ||, try), no model logic, the preference handle and "
      "ESPHome's own uint32_to_str() decimal key", ESPNVS is not None and HEALTHY is not None and not adapter_shape(ADAPTER_H),
      str(adapter_shape(ADAPTER_H)))
check("get_stats reads RAM-only statistics of the default partition (nvs_get_stats(nullptr, ...)); no nvs_open, no "
      "nvs_commit, no erase in the adapter", "return nvs_get_stats(nullptr, &st);" in ADAPTER_H
      and not re.search(r"nvs_open|nvs_commit|nvs_erase|nvs_flash", strip_code(ADAPTER_H)))
PIN_ESPHOME = re.search(r"ESPHOME_VERSION_CODE >= VERSION_CODE\((\d+), (\d+), (\d+)\) && ESPHOME_VERSION_CODE < "
                        r"VERSION_CODE\((\d+), (\d+), (\d+)\)", PINS_H)
PIN_IDF = re.search(r"ESP_IDF_VERSION >= ESP_IDF_VERSION_VAL\((\d+), (\d+), (\d+)\) && ESP_IDF_VERSION < "
                    r"ESP_IDF_VERSION_VAL\((\d+), (\d+), (\d+)\)", PINS_H)
check("version pins: ESPHome [2026.8.2, 2026.9.0) and ESP-IDF [5.5.5, 5.6.0), each in a static_assert naming "
      "ecco_fbdurable (negative controls in the host suite)",
      PIN_ESPHOME is not None and tuple(map(int, PIN_ESPHOME.groups())) == (2026, 8, 2, 2026, 9, 0)
      and PIN_IDF is not None and tuple(map(int, PIN_IDF.groups())) == (5, 5, 5, 5, 6, 0) and PINS_H.count("static_assert(") == 2
      and PINS_H.count('"ecco_fbdurable: ') == 2)
ESPH = FW["esphome"]
check("firmware esphome.min_version is 2026.8.2 - the pins' lower bound", str(ESPH.get("min_version")) == "2026.8.2")
wf_pins = {p.name: re.findall(r"esphome==([\d.]+)", p.read_text(encoding="utf-8"))
           for p in sorted((ROOT / ".github" / "workflows").glob("*.yml"))}
wf_versions = [tuple(map(int, v.split("."))) for vs in wf_pins.values() for v in vs]
check("every CI workflow that installs ESPHome pins a version inside the pins' range (native config/compile runs "
      "the static_asserts)", bool(wf_versions) and all((2026, 8, 2) <= v < (2026, 9, 0) for v in wf_versions),
      str({k: v for k, v in wf_pins.items() if v}))
check("the esp32 framework is esp-idf with NO explicit version (ESPHome 2026.8.2's recommended IDF 5.5.5; any other "
      "version fails the IDF pin at compile time)", FW["esp32"]["framework"].get("type") == "esp-idf"
      and "version" not in FW["esp32"]["framework"])
INCLUDES = [str(i) for i in ESPH.get("includes") or []]
closure_missing = []
for inc in INCLUDES:
    for dep in re.findall(r'#include\s*"([^"]+)"', (FIRMWARE_PATH.parent / inc).read_text(encoding="utf-8")):
        if not dep.startswith("esphome/") and f"include/{dep}" not in INCLUDES and dep != "esp_idf_version.h":
            closure_missing.append(f"{inc} -> {dep}")
check("esphome.includes = the two existing headers + FB-A, pins, model, adapter (in dependency order), and it is "
      "closed under quoted #include (ESPHome copies each listed file next to main.cpp)",
      INCLUDES == [*fbbs.BASE_INCLUDES, *fbbs.ADDED_INCLUDES] and not closure_missing, f"{INCLUDES} {closure_missing}")

# ===========================================================================
print("[13] Change scope (_fbb_scope): exact YAML delta, protected files, zero count deltas")
# ===========================================================================
PRE_TEXT = fbbs.pre_fbb0_firmware(FW_TEXT)
_FBC1_REVERT = chain.CHAIN.entry("fbc1").reverts[chain.FIRMWARE]
check("reverting exactly FB-B0's YAML edits reproduces the firmware as of chain entry fbc1 (FB-C1, merged before FB-B0) byte for "
      f"byte, and reverting FB-C1's declared edits as well reproduces main @ b3fcdfc, FB-B0's prep base (sha256 "
      f"{fbbs.BASE_FIRMWARE_SHA[:12]}...)",
      sha(PRE_TEXT) == chain.CHAIN.checkpoint(chain.FIRMWARE, "fbc1") and sha(_FBC1_REVERT(PRE_TEXT)) == fbbs.BASE_FIRMWARE_SHA)
check("the reverter is exact: applied to the base it fails (edit absent), and a duplicated edit fails",
      raises(lambda: fbbs.pre_fbb0_firmware(PRE_TEXT), AssertionError) is not None
      and raises(lambda: fbbs.pre_fbb0_firmware(FW_TEXT + fbbs.FIRMWARE_TEXT_EDITS[1][1]), AssertionError) is not None)
PRE = ds.load_firmware_text(PRE_TEXT)
diff_keys = sorted(k for k in set(FW) | set(PRE) if k not in ("_text",) and FW.get(k) != PRE.get(k))
check("the parsed firmware differs from the base ONLY in the esphome: block, and there only in min_version and "
      "includes (pre_fbb0_esphome reverts it exactly)", diff_keys == ["esphome"]
      and fbbs.pre_fbb0_esphome(FW["esphome"]) == PRE["esphome"]
      and sorted(k for k in set(FW["esphome"]) | set(PRE["esphome"]) if FW["esphome"].get(k) != PRE["esphome"].get(k))
      == ["includes", "min_version"], str(diff_keys))
PROTECTED = {
    "firmware/include/ecco_fallback_profile.h": "dc9de036dd4b8da658ab3d1649e032e8bf9714b2b5f858946a05540c2fd8f94f",
    "firmware/include/ecco_durable_snapshot.h": "d57cd3b5b951b97e45872be4485c63beec58f604db08ef33fb660b8251e871af",
    "firmware/include/ecco_recovery_evidence.h": "c9b9b1d670ce8ef8ec33c5c1208326abd0213f042e8a69b1115b4ea85620875e",
    "firmware/ecco_clock_dongle_stage3_2_manual_slot1.yaml": "fd70d9db4870ab746ed452ff27a7c0d11afa5acc073623bba267d87e4bc00158",
    "firmware/ecco_clock_dongle_stage3_3_manual_tou6.yaml": "b9061850e1fef286450c8986d2df24a81afebe4c41cabb3a9a01723553be0eb3",
}
changed = [rel for rel, want in PROTECTED.items() if sha((ROOT / rel).read_text(encoding="utf-8")) != want]
check("FB-A's header, the durable and evidence headers, and the two older firmware YAMLs are byte-identical to main @ "
      "b3fcdfc (FB-B0 edits none of them)", not changed, str(changed))
# FB-A's mirror is pinned byte-exact EXCEPT the PROSPECTIVE_TAGS assignment (and its comment): the S2 X6 conversion of
# #54's [8] (FB-T0 / #54 rebase) moves ecco_failback_provision_v1 from "prospective" to "declared by FB-B" there.
X6_REGION = re.compile(r"(?:#[^\n]*\n)*PROSPECTIVE_TAGS = [^\n]*\n")
FBA_MIRROR = (ROOT / "registry" / "fallback_profile.py").read_text(encoding="utf-8")
check("registry/fallback_profile.py is byte-identical to main @ b3fcdfc outside the X6 PROSPECTIVE_TAGS region, and "
      "PROSPECTIVE_TAGS is either the base value or the X6-converted empty tuple",
      len(X6_REGION.findall(FBA_MIRROR)) == 1
      and sha(X6_REGION.sub("PROSPECTIVE_TAGS = <X6>\n", FBA_MIRROR)) == "7a639b97afc0b1de333fcf7c2eb219350e3db5e421df3328461e7d882e3becb7"
      and tuple(fp.PROSPECTIVE_TAGS) in (("ecco_failback_provision_v1",), ()))
_x6_converted = X6_REGION.sub("# ecco_failback_provision_v1 is declared by ecco_fallback_durable_model.h (FB-B0).\n"
                              "PROSPECTIVE_TAGS = ()\n", FBA_MIRROR)
check("...the tolerance is exactly the X6 region: an X6-converted mirror still matches, any change elsewhere does not",
      sha(X6_REGION.sub("PROSPECTIVE_TAGS = <X6>\n", _x6_converted)) == sha(X6_REGION.sub("PROSPECTIVE_TAGS = <X6>\n", FBA_MIRROR))
      and sha(X6_REGION.sub("PROSPECTIVE_TAGS = <X6>\n", FBA_MIRROR.replace("FAILBACK_SIZE = 80", "FAILBACK_SIZE = 81")))
      != sha(X6_REGION.sub("PROSPECTIVE_TAGS = <X6>\n", FBA_MIRROR)))
# FB-B1 (D14): this listing was a LIVE-tree pin of "the six headers that exist after FB-B0". A later PR necessarily adds its own
# header (FB-B1: ecco_fallback_capture.h), so the pin is now chain-relative, exactly as test_failback_shadow_core.py's
# `later_headers`: the six known headers PLUS the firmware/include headers that entries AFTER fbb0 declare in `added_files`. It is
# not weakened: an undeclared extra header still fails, and a declared header that is missing fails too.
_LATER_HEADERS_14 = sorted(Path(f).name for e in chain.CHAIN.after("fbb0") for f in e.added_files if f.startswith("firmware/include/"))
check("firmware/include holds exactly the three pre-existing headers plus the three FB-B0 headers, plus (chain-relative, FB-T0) "
      "exactly the headers that chain entries after fbb0 declare in added_files",
      sorted(p.name for p in INCLUDE_DIR.iterdir()) == sorted(["ecco_durable_snapshot.h", "ecco_recovery_evidence.h",
                                                               "ecco_fallback_profile.h", "ecco_fallback_version_pins.h",
                                                               "ecco_fallback_durable_model.h", "ecco_fallback_durable.h",
                                                               *_LATER_HEADERS_14]),
      str(sorted(p.name for p in INCLUDE_DIR.iterdir())))
check("every file _fbb_scope declares as added exists", all((ROOT / rel).is_file() for rel in fbbs.ADDED_FILES),
      str([rel for rel in fbbs.ADDED_FILES if not (ROOT / rel).is_file()]))


def object_counts(fw) -> tuple:
    return (len(fw["script"]), len(fw["globals"]), len(fw["api"].get("actions", [])), len(fw.get("interval", [])),
            *(len(fw.get(k) or []) for k in ("sensor", "binary_sensor", "text_sensor", "switch", "button", "number", "select")))


def durable_counts(text: str) -> tuple:
    return tuple(len(re.findall(rf"ecco_durable::{fn}\s*\(", text)) for fn in ("commit_record", "load_record", "load_record_status"))


check("zero object-count delta: scripts, globals, API actions, intervals and every entity platform are unchanged",
      object_counts(FW) == object_counts(PRE), f"{object_counts(PRE)} -> {object_counts(FW)}")
check("zero durable-surface delta: ecco_durable commit_record / load_record / load_record_status call counts unchanged "
      f"{durable_counts(PRE_TEXT)}", durable_counts(FW_TEXT) == durable_counts(PRE_TEXT))
_tmp = Path(tempfile.mkdtemp(prefix="ecco_fbb0_scope_"))
try:
    (_tmp / "include").mkdir()
    for inc in fbbs.BASE_INCLUDES:
        shutil.copy(FIRMWARE_PATH.parent / inc, _tmp / inc)
    (_tmp / FIRMWARE_PATH.name).write_text(PRE_TEXT, encoding="utf-8")
    WS_PRE = aws.analyze(_tmp / FIRMWARE_PATH.name)
finally:
    shutil.rmtree(_tmp, ignore_errors=True)
WS_POST = chain.CHAIN.analyze_as_of("fbb0", live_fw_text=LIVE_FW_TEXT)   # the analyzer on the firmware + headers AS OF fbb0


def op_list(ws) -> list:
    return sorted((p.kind, p.name, o.kind, str(getattr(o, "address", "")), str(getattr(o, "count", ""))) for p in ws["paths"] for o in p.ops)


n_w = sum(1 for p in WS_POST["paths"] for o in p.ops if o.kind == "write")
n_r = sum(1 for p in WS_POST["paths"] for o in p.ops if o.kind == "read")
check(f"zero Modbus delta: the write-surface analyzer finds the identical op list before and after FB-B0 ({n_w} write / "
      f"{n_r} read ops), no bus-access finding - including its scan of the four newly included headers",
      op_list(WS_POST) == op_list(WS_PRE) and (n_w, n_r) == (52, 60) and WS_POST["bus_access_findings"] == []
      and WS_POST["unknown_extent_writes"] == [] and WS_PRE["bus_access_findings"] == [])
check("zero NVS runtime write delta: no firmware YAML lambda writes or reads NVS directly, and the only new "
      "set-blob call site (the adapter) is unreachable (no call site of ecco_fbdurable anywhere in the YAML)",
      not x1_violations(CODE_FILES, YAML_FILES) and not call_sites(YAML_FILES))
check("the Python mirror is pure (stdlib + fallback_profile): no file writes, network, process or clock access",
      set(re.findall(r"^(?:import|from) (\w+)", MIRROR_TEXT, re.M)) == {"__future__", "struct", "dataclasses", "pathlib",
                                                                          "sys", "fallback_profile"}
      and not re.search(r"write_text|write_bytes|open\(|subprocess|socket|os\.system|time\.", MIRROR_TEXT))
check("no registry/*.py module names the SG-01 journal / self-partial tokens (their scope suites scan registry/)",
      not re.search(r"(?i)start_?journal|self_?partial", MIRROR_TEXT))

# ===========================================================================
print("[14] Mutation sensitivity: Python-mirror mutants and header-text mutants")
# ===========================================================================


def load_mirror(source: str):
    mod = types.ModuleType("fallback_durable_mutant")
    mod.__file__ = str(MIRROR_PATH)
    sys.modules[mod.__name__] = mod  # dataclasses resolve their module through sys.modules
    try:
        exec(compile(source, str(MIRROR_PATH), "exec"), mod.__dict__)
    finally:
        del sys.modules[mod.__name__]
    return mod


def mirror_detectors(m) -> dict:
    out = {}
    for name, fn in (
        ("layout", lambda: layout_agrees(m)),
        ("constants", lambda: constants_agree(m)),
        ("goldens", lambda: mirror_goldens(m) == SPEC_GOLDENS),
        ("enums", lambda: not enums_agree(m)),
        ("keys", lambda: [m.decimal_key(k) for k in (0, 10, m.FALLBACK_PROFILE_KEY)] == ["0", "10", "1609458070"]),
        ("outcome", lambda: not outcome_table_agrees(m)),
        ("readback", lambda: not readback_agrees(m)),
        ("witness cases", lambda: not witness_cases_agree(m)),
        ("witness sweep", lambda: not witness_sweep_agrees(m)),
        ("compose cases", lambda: not compose_cases_agree(m)),
        ("compose oracle", lambda: not compose_exhaustive(m, (fp.LOAD_OK, fp.LOAD_ABSENT, fp.LOAD_WRONG_SIZE, fp.LOAD_READ_ERROR),
                                                          (0, 1), False)[1]),
        ("permissions", lambda: [(c, w) for c in range(9) for w in range(13) if m.profile_writer_usable(c, w)] == [(5, 0)]
         and [c for c in range(9) if m.save_class_permitted(c)] == [1, 2, 3, 4, 5, 6, 8]
         and [c for c in range(9) if m.invalidate_class_permitted(c)] == [5]),
        ("generation", lambda: not generation_asserts_agree(m) and not generation_agrees(m)),
        ("latch", lambda: not latch_agrees(m)),
        ("transaction", lambda: not txn_probes(m)),
    ):
        try:
            out[name] = bool(fn())
        except Exception:  # noqa: BLE001 - a mutant that crashes a detector is detected
            out[name] = False
    return out


control = mirror_detectors(load_mirror(MIRROR_TEXT))
check("control: the unmutated mirror passes every detector", all(control.values()), str(control))
MIRROR_MUTANTS = [
    ("magic 'ECFX'", "PROVISION_MAGIC = 0x45434657", "PROVISION_MAGIC = 0x45434658"),
    ("binding covers its own field", "bytes(raw[:PROVISION_BOUND_BYTES])", "bytes(raw[:PROVISION_SIZE])"),
    ("binding domain v2", 'PROVISION_BINDING_DOMAIN = b"ECCO-FAILBACK-PROVISION-v1"', 'PROVISION_BINDING_DOMAIN = b"ECCO-FAILBACK-PROVISION-v2"'),
    ("tag key / record schema swapped", '("hw_tag_key", "I", 1), ("hw_record_schema", "H", 1)', '("hw_record_schema", "H", 1), ("hw_tag_key", "I", 1)'),
    ("decimal key zero-padded", "    return str(key)", '    return f"{key:010d}"'),
    ("TIMEOUT classified pre-write", "PRE_WRITE_CODES = (IDF_ERR_NVS_INVALID_HANDLE, IDF_ERR_NVS_READ_ONLY, IDF_ERR_NVS_NOT_INITIALIZED)",
     "PRE_WRITE_CODES = (IDF_ERR_NVS_INVALID_HANDLE, IDF_ERR_NVS_READ_ONLY, IDF_ERR_NVS_NOT_INITIALIZED, IDF_ERR_TIMEOUT)"),
    ("outcome ignores health", "    if not healthy_after:\n        return KEY_UNKNOWN_REBOOT\n", ""),
    ("OK + prior readback commits", "    if e == WERR_OK and r == RB_INTENDED:", "    if e == WERR_OK and r in (RB_INTENDED, RB_PRIOR):"),
    ("wrong-size prior compared without length", "(prior_load == LOAD_WRONG_SIZE and prior_len == rb_len)", "(prior_load == LOAD_WRONG_SIZE)"),
    ("absent prior never RB_PRIOR", "return RB_PRIOR if prior_load == LOAD_ABSENT else RB_ABSENT_UNEXPECTED", "return RB_ABSENT_UNEXPECTED"),
    ("witness flags unchecked", '    if w["flags"] != 0:\n        return WIT_DEFECT_FLAGS\n', ""),
    ("witness prior rule weakened", 'w["prior_generation"] >= w["hw_generation"]', 'w["prior_generation"] > w["hw_generation"]'),
    ("witness WRONG_SIZE -> ABSENT", "    if load == LOAD_WRONG_SIZE:\n        return W_CORRUPT", "    if load == LOAD_WRONG_SIZE:\n        return W_ABSENT"),
    ("B2a after B3", "    if anomaly_bits != 0:\n        return EPC_UNREADABLE, WHY_READ_ANOMALY, RULE_B2A\n    if c == fp.PROFILE_CORRUPT:\n        return EPC_CORRUPT, WHY_NONE, 3\n",
     "    if c == fp.PROFILE_CORRUPT:\n        return EPC_CORRUPT, WHY_NONE, 3\n    if anomaly_bits != 0:\n        return EPC_UNREADABLE, WHY_READ_ANOMALY, RULE_B2A\n"),
    ("B5 without hw == 1", ' and wr["last_op"] == PROV_OP_SAVE and wr["hw_generation"] == 1:', ' and wr["last_op"] == PROV_OP_SAVE:'),
    ("B8 after B9", '        if g > wr["hw_generation"]:\n            return c, WHY_WIT_LAGGING, 8\n        if wr["hw_tag_key"] != FALLBACK_PROFILE_KEY or wr["hw_record_schema"] != fp.PROFILE_SCHEMA:\n            return EPC_PROFILE_STALE, WHY_SUPERSEDED, 9\n',
     '        if wr["hw_tag_key"] != FALLBACK_PROFILE_KEY or wr["hw_record_schema"] != fp.PROFILE_SCHEMA:\n            return EPC_PROFILE_STALE, WHY_SUPERSEDED, 9\n        if g > wr["hw_generation"]:\n            return c, WHY_WIT_LAGGING, 8\n'),
    ("B12 interrupted usable", "return EPC_PROFILE_STALE, WHY_INTERRUPTED, 12", "return c, WHY_NONE, 12"),
    ("B14 missing witness consistent", "return c, WHY_WIT_MISSING, 14", "return c, WHY_NONE, 14"),
    ("B6 LOST -> NOT_CAPTURED", "            return EPC_PROFILE_LOST, WHY_NONE, 6", "            return EPC_NOT_CAPTURED, WHY_NONE, 6"),
    ("writer-usable accepts a lagging witness", "    return cls == EPC_VALID and why == WHY_NONE", "    return cls == EPC_VALID and why in (WHY_NONE, WHY_WIT_LAGGING)"),
    ("UNREADABLE overwritable", "    return cls in (EPC_NOT_CAPTURED, EPC_CORRUPT,", "    return cls in (EPC_UNREADABLE, EPC_NOT_CAPTURED, EPC_CORRUPT,"),
    ("generation base ignores seen", "hw if wc == W_VALID else 0, seen_hw_gen)\n\n\ndef save_generation_available",
     "hw if wc == W_VALID else 0, 0)\n\n\ndef save_generation_available"),
    ("INVALIDATE allowed at g + 1 == hw", "g + 1 > (hw if wc == W_VALID else 0)", "g + 1 >= (hw if wc == W_VALID else 0)"),
    ("same-boot vanish not an anomaly", "        if present_seen & key_bit:\n            read_anomaly |= key_bit\n", "        pass\n"),
    ("health bit dropped", "        read_anomaly |= ANOMALY_BIT_UNHEALTHY", "        pass"),
    ("profile written before the witness", "    ow, r.w_rb = write_one(nvs, latch, FAILBACK_PROVISION_KEY,",
     "    write_one(nvs, latch, FALLBACK_PROFILE_KEY, _pbytes(p_new), _pbytes(p_prior), p_pd[0], p_pd[1], KeyReport())\n"
     "    ow, r.w_rb = write_one(nvs, latch, FAILBACK_PROVISION_KEY,"),
    ("latch not checked", "    if latch.write_latched:\n        r.refusal = REFUSAL_LATCHED", "    if False:\n        r.refusal = REFUSAL_LATCHED"),
    ("profile attempted after an UNKNOWN witness", "    if ow != KEY_COMMITTED:\n        return TXN_UNKNOWN_REBOOT, r", "    if False:\n        return TXN_UNKNOWN_REBOOT, r"),
    ("latch never set", "        latch.write_latched = True", "        pass"),
    ("RAM mirror from the readbacks after UNKNOWN", "    return bytes(p_prior), bytes(w_prior), p_prior_load, w_prior_load",
     "    return r.p_rb, r.w_rb, r.p.rb_load, r.w.rb_load"),
    ("CRC-erased read taken as ABSENT", "    e, got, data = nvs.get_blob(key, size)\n    d.data_err = e\n",
     "    e, got, data = nvs.get_blob(key, size)\n    d.data_err = e\n    if e == IDF_ERR_NVS_NOT_FOUND:\n        return LOAD_ABSENT, zero, d\n"),
    ("REPLACE CORRUPT rule dropped", "    if (op == PROV_OP_REPLACE_CORRUPT) != (prior_cls == EPC_CORRUPT) and op != PROV_OP_INVALIDATE:\n        return False\n", ""),
    ("health gate before the commit dropped", "    if not storage_healthy(nvs):\n        r.refusal = REFUSAL_STORAGE_UNHEALTHY", "    if False:\n        r.refusal = REFUSAL_STORAGE_UNHEALTHY"),
    ("zero handle not refused", "    if nvs.handle() == 0:\n        r.refusal = REFUSAL_STORAGE_UNAVAILABLE", "    if False:\n        r.refusal = REFUSAL_STORAGE_UNAVAILABLE"),
]
for label, old, new in MIRROR_MUTANTS:
    if MIRROR_TEXT.count(old) != 1:
        check(f"mirror mutant [{label}] applies exactly once to registry/fallback_durable.py", False, repr(old[:70]))
        continue
    res = mirror_detectors(load_mirror(MIRROR_TEXT.replace(old, new, 1)))
    check(f"mirror mutant [{label}] is killed ({', '.join(k for k, v in res.items() if not v) or 'SURVIVED'})",
          not all(res.values()))


def header_detectors(model: str, adapter: str) -> dict:
    out = {}
    other = {**OTHER_CODE, "firmware/include/ecco_fallback_durable.h": adapter}
    for name, fn in (
        ("layout", lambda: layout_agrees(fd, model)),
        ("constants", lambda: constants_agree(fd, model)),
        ("goldens", lambda: header_goldens(model) == SPEC_GOLDENS),
        ("enums", lambda: not enums_agree(fd, model)),
        ("witness cases", lambda: not witness_cases_agree(fd, model)),
        ("compose cases", lambda: not compose_cases_agree(fd, model)),
        ("static_asserts", lambda: not generation_asserts_agree(fd, model)),
        ("pre-write codes", lambda: set(re.findall(r"e == (IDF_\w+)", re.search(
            r"constexpr WriteErrClass classify_write_err\(int32_t e\) \{(.*?)\n\}", model, re.S).group(1))) == pre_names),
        ("X1", lambda: not x1_violations({**CODE_FILES, "firmware/include/ecco_fallback_durable_model.h": model,
                                          "firmware/include/ecco_fallback_durable.h": adapter}, YAML_FILES)),
        ("X2", lambda: not x2_violations(model, other)),
        ("banned", lambda: not banned_hits(model)),
        ("adapter", lambda: not adapter_shape(adapter)),
    ):
        try:
            out[name] = bool(fn())
        except Exception:  # noqa: BLE001
            out[name] = False
    return out


hcontrol = header_detectors(MODEL_H, ADAPTER_H)
check("control: the real headers pass every header-text detector", all(hcontrol.values()), str(hcontrol))
HEADER_TEXT_MUTANTS = [
    ("model", "golden W-INV value edited", "0x9E8AEC8F7D7DF2D7ULL", "0x9E8AEC8F7D7DF2D6ULL"),
    ("model", "KEY_COMMITTED / KEY_NOT_COMMITTED renumbered", "  KEY_COMMITTED = 1,\n  KEY_NOT_COMMITTED = 2,",
     "  KEY_COMMITTED = 2,\n  KEY_NOT_COMMITTED = 1,"),
    ("model", "struct fields swapped", "  uint32_t hw_tag_key;        // 32", "  uint16_t hw_tag_key;        // 32"),
    ("model", "flags offset edited", "offsetof(FailbackProvisionV1, flags) == 39", "offsetof(FailbackProvisionV1, flags) == 40"),
    ("model", "witness golden row flipped", "{1, ecco_fallback::LOAD_OK, 38, 0x0102, 0xFF, 0x0000, 1, WIT_DEFECT_FLAGS, W_CORRUPT},",
     "{1, ecco_fallback::LOAD_OK, 38, 0x0102, 0xFF, 0x0000, 1, WIT_DEFECT_NONE, W_VALID},"),
    ("model", "compose golden row flipped", "WV_HW8_SAVE_P7, 0, EPC_PROFILE_STALE, WHY_INTERRUPTED, RULE_B12},",
     "WV_HW8_SAVE_P7, 0, EPC_VALID, WHY_NONE, RULE_B10},"),
    ("model", "binding domain edited", '"ECCO-FAILBACK-PROVISION-v1";', '"ECCO-FAILBACK-PROVISION-v2";'),
    ("model", "NOT_FOUND classified pre-write", "(e == IDF_ERR_NVS_INVALID_HANDLE || e == IDF_ERR_NVS_READ_ONLY ||",
     "(e == IDF_ERR_NVS_NOT_FOUND || e == IDF_ERR_NVS_INVALID_HANDLE || e == IDF_ERR_NVS_READ_ONLY ||"),
    ("model", "third write_one_ instantiation", "  if (op == KEY_COMMITTED)\n    return TXN_COMMITTED;",
     "  (void) write_one_<FailbackStateV1, FAILBACK_STATE_KEY>(nvs, s, s, p_pd, s, r.p);\n  if (op == KEY_COMMITTED)\n    return TXN_COMMITTED;"),
    ("model", "nvs_ token in the model", "// Offline mirror: registry/fallback_durable.py (C++-exact).",
     "// Offline mirror: registry/fallback_durable.py (C++-exact). Calls nvs_get_blob."),
    ("model", "generation static_assert edited", "PROFILE_NOT_CAPTURED, 0u, W_VALID, 12u, 0u) == 12u &&",
     "PROFILE_NOT_CAPTURED, 0u, W_VALID, 12u, 0u) == 13u &&"),
    ("adapter", "branch in the adapter", "  uint32_t handle() const { return esphome::global_preferences->nvs_handle; }",
     "  uint32_t handle() const { return esphome::global_preferences ? esphome::global_preferences->nvs_handle : 0; }"),
    ("adapter", "second set-blob call", "    return nvs_get_blob(this->handle(), k, out, len);",
     "    (void) nvs_set_blob(this->handle(), k, out, *len);\n    return nvs_get_blob(this->handle(), k, out, len);"),
    ("adapter", "logic moved into the adapter", "inline bool nvs_healthy() { return storage_healthy(EspNvs{}); }",
     "inline bool nvs_healthy() { return storage_healthy(EspNvs{}); }\ninline bool commit() { EspNvs n; return write_latched(); }"),
]
for which, label, old, new in HEADER_TEXT_MUTANTS:
    base = MODEL_H if which == "model" else ADAPTER_H
    if base.count(old) != 1:
        check(f"header mutant [{label}] applies exactly once", False, repr(old[:70]))
        continue
    mutated = base.replace(old, new, 1)
    res = header_detectors(mutated, ADAPTER_H) if which == "model" else header_detectors(MODEL_H, mutated)
    check(f"header mutant [{label}] is detected ({', '.join(k for k, v in res.items() if not v) or 'SURVIVED'})",
          not all(res.values()))

# ===========================================================================
print("[15] FB-T0 chain registration: FB-B0 is the `fbb0` entry, appended after `fbc1`, with exact declarations")
# ===========================================================================
C15 = chain.CHAIN
E15 = C15.entry("fbb0")
ids15 = C15.ids()
LIVE15 = {p: chain.read_live(p) for p in chain.PINNED}
M_FBC1 = chain.measure(C15.as_of_all("fbc1", LIVE15))
M_FBB0 = chain.measure(C15.as_of_all("fbb0", LIVE15))
M_DIFF = {m: M_FBB0[m] - M_FBC1[m] for m in chain.METRICS}
_FBB0_REVERT = E15.reverts[chain.FIRMWARE]
check("fbb0 is appended IMMEDIATELY after fbc1 (merge order: ... dump_v2 -> fbc1 -> fbb0) and is not the root",
      ids15.index("fbb0") == ids15.index("fbc1") + 1 and ids15[:4] == ["fba", "mtou1", "dump_v2", "fbc1"] and E15.pr == "FB-B0")
check("the fbb0 reverter is FB-B0's own exact-match _fbb_scope.pre_fbb0_firmware, for the firmware YAML only (no other pinned "
      "artifact), with a recorded checkpoint",
      set(E15.reverts) == {chain.FIRMWARE} and _FBB0_REVERT is fbbs.pre_fbb0_firmware and _FBB0_REVERT.__module__ == "_fbb_scope"
      and set(E15.checkpoints) == {chain.FIRMWARE} and len(E15.checkpoints[chain.FIRMWARE]) == 64)
check("the fbb0 checkpoint is the sha256 of the firmware AS OF fbb0, and reverting exactly FB-B0's edits from it gives fbc1's "
      "recorded checkpoint (dd9bc598...) - FB-B0's and FB-C1's reverters commute on the firmware",
      sha(FW_TEXT) == E15.checkpoints[chain.FIRMWARE] == C15.checkpoint(chain.FIRMWARE, "fbb0")
      and sha(PRE_TEXT) == C15.checkpoint(chain.FIRMWARE, "fbc1") == C15.entry("fbc1").checkpoints[chain.FIRMWARE]
      and sha(PRE_TEXT).startswith("dd9bc59890d6d514")
      and _FBC1_REVERT(_FBB0_REVERT(FW_TEXT)) == _FBB0_REVERT(_FBC1_REVERT(FW_TEXT)))
check("the declared deltas are exactly the measured ones: +4 includes (+4 banned-token lines) and nothing else; in particular ZERO "
      "Modbus writes / reads, ZERO commit_record / load_record / load_record_status sites, ZERO durable-header tag strings, and no "
      "script / global / interval / entity / API action / substitution",
      dict(E15.deltas) == {"includes": 4} and {m: d for m, d in M_DIFF.items() if d} == {"includes": 4, "banned_fw": 4}
      and M_DIFF["modbus_writes"] == M_DIFF["modbus_reads"] == 0
      and M_DIFF["commit_record"] == M_DIFF["load_record"] == M_DIFF["load_record_status"] == 0
      and (M_FBB0["modbus_writes"], M_FBB0["modbus_reads"]) == (52, 60), str(M_DIFF))
check("the four include additions are declared in order - FB-A header, pins, model, adapter - appended to the existing list, and "
      "there is no op-path change, no added / changed / removed substitution and no banned-file leak",
      E15.includes_added == tuple(fbbs.ADDED_INCLUDES) == ("include/ecco_fallback_profile.h", "include/ecco_fallback_version_pins.h",
                                                           "include/ecco_fallback_durable_model.h", "include/ecco_fallback_durable.h")
      and chain._includes(FW_TEXT) == chain._includes(PRE_TEXT) + list(E15.includes_added)
      and E15.op_paths_changed == frozenset() and not E15.subst_added and not E15.subst_changed and not E15.subst_removed
      and E15.banned_files == frozenset())
check("the exact FB-A includers after FB-B0 are declared: the firmware YAML (its includes: list) and the model header - "
      "exact paths, no glob, no prefix",
      E15.fbh_includers == frozenset(fbbs.FBA_INCLUDERS) == frozenset(
          {"firmware/ecco_clock_dongle_stage3_4_free_power.yaml", "firmware/include/ecco_fallback_durable_model.h"}))
_bn = [ln for ln in FW_TEXT.splitlines() if chain.BANNED.search(ln)]
_bn_pre = [ln for ln in PRE_TEXT.splitlines() if chain.BANNED.search(ln)]
check("banned-token accounting: exactly 4 occurrences added in the firmware, and they are the four `- include/ecco_fallback*` lines "
      "(no lambda, entity, script, global or substitution); FB-C1's 14 (chain entry fbc1) are unchanged",
      E15.banned_fw_added == len(chain.BANNED.findall(FW_TEXT)) - len(chain.BANNED.findall(PRE_TEXT)) == 4
      and [ln for ln in _bn if ln not in _bn_pre] == list(fbbs.FW_FB_TOKEN_LINES)
      and C15.entry("fbc1").banned_fw_added == 14 and len(chain.BANNED.findall(PRE_TEXT)) == 14)
check("added_files is EXACTLY FB-B0's twelve new files (no glob), every one exists, and is declared by no other entry",
      E15.added_files == frozenset(fbbs.ADDED_FILES) and len(E15.added_files) == 12
      and all((ROOT / f).is_file() for f in E15.added_files)
      and all(f not in C15.entry(e).added_files for e in ids15 if e != "fbb0" for f in E15.added_files))
_hdr_tags = {v for _n, v in ti.inventory(MODEL_H)}
check("tag declaration / promotion: the model header declares exactly ecco_failback_provision_v1 - the SAME string FB-A reserved as "
      "PROSPECTIVE - which the entry declares AND promotes; the adapter and pins headers declare no tag",
      _hdr_tags == {fd.FAILBACK_PROVISION_TAG} == set(E15.tags_declared) == set(E15.tags_promoted) == {"ecco_failback_provision_v1"}
      and tuple(fp.PROSPECTIVE_TAGS) == ("ecco_failback_provision_v1",)
      and not ti.inventory(ADAPTER_H) and not ti.inventory(PINS_H) and "ecco_failback_provision_v1" in C15.declared_tags())
_all_tags = ti.all_declared_tags(INCLUDE_DIR)
_tag_strings = list(_all_tags.values())
check("the witness tag's preference key is UNCHANGED by the promotion (same exact string, same FNV-1 32 key 1000595297 == "
      "FAILBACK_PROVISION_KEY), no historical proof is re-hashed, and over EVERY tag in every firmware header (13 durable + evidence "
      "domain tag + the two FB-A tags + the FBW tag) there is no duplicate string and no 32-bit key collision",
      fp.tag_key_fnv1_32(fd.FAILBACK_PROVISION_TAG) == fd.FAILBACK_PROVISION_KEY == 0x3BA3DF61 == 1000595297
      and _tag_strings.count(fd.FAILBACK_PROVISION_TAG) == 1 and len(_tag_strings) >= 17
      and not ti.collision_problems(_tag_strings, fp.tag_key_fnv1_32), str(ti.collision_problems(_tag_strings, fp.tag_key_fnv1_32)))
_magics = [fp.PROFILE_MAGIC, fp.FAILBACK_MAGIC, 0x45434356, 0x4543534A, fd.PROVISION_MAGIC]
check("the FBW magic 'ECFW' 0x45434657 enters the distinctness check: the five durable magics (ECFP, ECFB, ECCV, ECSJ, ECFW) are "
      "pairwise distinct", fd.PROVISION_MAGIC == 0x45434657 and len(set(_magics)) == 5)
_EXISTING15 = [v for k, v in _all_tags.items() if not k.startswith(("ecco_fallback_durable_model.h:", "ecco_fallback_profile.h:"))]
_FBA15 = (fp.FALLBACK_PROFILE_TAG, fp.FAILBACK_STATE_TAG)
_LATER15 = {"ecco_fallback_durable_model.h": MODEL_H}
check("the tag accounting accepts the real later header (no problem), and REJECTS a wrong tag string, a missing declaration and a "
      "tag that collides with an existing one (negative controls)",
      ti.check_later_headers(_LATER15, C15.declared_tags(), C15.declared_promoted_tags(), _EXISTING15, fp.PROSPECTIVE_TAGS, _FBA15,
                             fp.tag_key_fnv1_32) == []
      and ti.check_later_headers(_LATER15, frozenset({"ecco_failback_provision_v2"}), frozenset(), _EXISTING15, fp.PROSPECTIVE_TAGS,
                                 _FBA15, fp.tag_key_fnv1_32) != []
      and ti.check_later_headers(_LATER15, frozenset(), frozenset(), _EXISTING15, fp.PROSPECTIVE_TAGS, _FBA15,
                                 fp.tag_key_fnv1_32) != []
      and ti.check_later_headers(_LATER15, C15.declared_tags(), C15.declared_promoted_tags(),
                                 [*_EXISTING15, fd.FAILBACK_PROVISION_TAG], fp.PROSPECTIVE_TAGS, _FBA15, fp.tag_key_fnv1_32) != [])


def _replace_entry(entry, **kw):
    d = {f: getattr(entry, f) for f in entry.__dataclass_fields__}
    d.update(kw)
    return chain.Entry(**d)


def _chain_report_fails(mutated_entry, needle: str) -> bool:
    entries = tuple(mutated_entry if e.id == "fbb0" else e for e in C15.entries)
    return any((not ok) and needle in name for name, ok, _d in chain.integrity_report(chain.Chain(entries), LIVE15))


check("integrity report: the whole chain (root .. fbb0, and every later entry) is green against the live tree",
      all(ok for _n, ok, _d in chain.integrity_report(C15, LIVE15)))
check("chain negative controls: a wrong delta (+5 includes), the four includes in the wrong order, a missing include declaration, "
      "an undeclared op-path change, a declared Modbus read, a wrong checkpoint and a wrong banned-token count are each rejected",
      _chain_report_fails(_replace_entry(E15, deltas={"includes": 5}), "declared deltas")
      and _chain_report_fails(_replace_entry(E15, includes_added=tuple(reversed(fbbs.ADDED_INCLUDES))), "includes")
      and _chain_report_fails(_replace_entry(E15, includes_added=fbbs.ADDED_INCLUDES[:3], deltas={"includes": 3}), "includes")
      and _chain_report_fails(_replace_entry(E15, op_paths_changed=frozenset({"write_inverter_rtc"})), "op_paths_changed")
      and _chain_report_fails(_replace_entry(E15, deltas={"includes": 4, "modbus_reads": 1}), "declared deltas")
      and _chain_report_fails(_replace_entry(E15, checkpoints={chain.FIRMWARE: "0" * 64}), "checkpoint")
      and _chain_report_fails(_replace_entry(E15, banned_fw_added=3), "declared deltas"))

print("")
if FAILURES:
    print(f"FAILED: {len(FAILURES)} check(s)")
    for f in FAILURES:
        print(f"  - {f}")
    sys.exit(1)
print("All FB-B0 Fallback durable model checks passed.")
