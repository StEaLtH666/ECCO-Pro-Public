#!/usr/bin/env python3
"""SG-01 Phase 1 + Phase 2 - the Free Power START journal.

Phase 1 (firmware/include/ecco_durable_snapshot.h): the production journal
record FreePowerStartJournal (16 bytes, tag ecco_free_power_start_journal_v1),
the FNV-1a-64 binding helper free_power_start_journal_binding() and the
schema/binding validator free_power_start_journal_valid(), all constexpr and
pinned by compile-time golden vectors (static_assert).

Phase 2 (firmware/ecco_clock_dongle_stage3_4_free_power.yaml):
start_free_power_override durably commits the journal BEFORE each of its four
mutation writes (B1 reg232 mask 0x01, B2 reg230 0x03, B3 regs 268-279 0x07,
B4 regs 256-261 0x0F), aborts that write and every later one if the commit
fails, records START_VERIFIED best-effort after a positive activation verify,
and on_boot LOADS (never commits) the journal for a trusted RESTORE_REQUIRED
obligation. A missing/bad/unbound journal is never metadata corruption.
Since SG-01 Phase 3/4 the journal's ONLY consumer is the restore dispatch's
read-only SELF_PARTIAL classifier (covered by
registry/tests/test_sg01_self_partial_phase3_4.py); section [10] pins that.

No I/O beyond reading repository files, no hardware, no ESPHome/C++
toolchain. Behaviour is executed on the REAL firmware source: the whole
start_free_power_override script and the real Free Power block of on_boot run
through registry/tests/_dump_sim.py (transpiled lambdas, real action tree,
in-memory NVS with commit/load failure injection, one ordered timeline of
durable commits and Modbus operations). The C++ helpers' agreement with the
Python mirror (registry/tests/_sg01_journal_model.py) is established by
parsing the header's own static_assert golden vectors - the native firmware
build evaluates those same assertions in C++.

Sections:
  [1]  Phase 1 schema: struct, tag, magic, masks, flags, size/offset pins
  [2]  Phase 1 binding: header field order/domain parsed, C++ golden vectors
       re-derived by the Python mirror, NUL/endianness/exclusion pins
  [3]  Phase 1 validation: header rules parsed, every static_assert case
       agrees with the Python mirror, exhaustive rejection classes
  [4]  Phase 2 START happy path: exact commit-before-write timeline,
       record contents, binding == durable snapshot, RAM mirror
  [5]  Phase 2 journal commit failure before B1/B2/B3/B4 (C/D/E/F)
  [6]  Phase 2 START_VERIFIED success / failure (J/K)
  [7]  Phase 2 fault sweep: journal failure position x write outcomes
  [8]  Reboot at every commit boundary (A/B), plus pre-journal and stale-
       journal cuts
  [9]  on_boot validation: binding mismatch, missing, bad magic/reserved/
       flags/mask/verified-partial, load failure, wrong size (G/H/I);
       legacy boot behaviour byte-for-byte unchanged
  [10] No boot commit (L), static placement, no clear, no other consumer,
       Modbus surface of START unchanged
  [11] Mutation sensitivity: each safety-critical ordering/failure rule,
       broken on purpose, is detected
"""

from __future__ import annotations

import copy
import itertools
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FIRMWARE_PATH = ROOT / "firmware" / "ecco_clock_dongle_stage3_4_free_power.yaml"
HEADER_PATH = ROOT / "firmware" / "include" / "ecco_durable_snapshot.h"
EVIDENCE_HEADER_PATH = ROOT / "firmware" / "include" / "ecco_recovery_evidence.h"

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _dump_sim as ds  # noqa: E402
import _free_power_action_sim as fpsim  # noqa: E402
import _sg01_journal_model as jm  # noqa: E402

FAILURES: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  PASS  {name}")
    else:
        FAILURES.append(name)
        print(f"  FAIL  {name}" + (f" - {detail}" if detail else ""))


for required in (FIRMWARE_PATH, HEADER_PATH, EVIDENCE_HEADER_PATH):
    if not required.is_file():
        print(f"  FAIL  required file not found: {required}")
        sys.exit(1)

FW_TEXT = FIRMWARE_PATH.read_text(encoding="utf-8")
HEADER = HEADER_PATH.read_text(encoding="utf-8")
EVIDENCE_HEADER = EVIDENCE_HEADER_PATH.read_text(encoding="utf-8")
FW = ds.load_firmware(FIRMWARE_PATH)
D = ds.Durable

JKEY = D.FREE_POWER_START_JOURNAL_TAG
DATA_KEY = D.FREE_POWER_DATA_TAG
VALID_KEY = D.FREE_POWER_VALID_TAG
RETRY_KEY = D.FREE_POWER_RETRY_TAG
MASKS = (jm.JOURNAL_MASK_B1, jm.JOURNAL_MASK_B2, jm.JOURNAL_MASK_B3, jm.JOURNAL_MASK_B4)
START_WRITES = (232, 230, 268, 256)  # B1, B2, B3, B4
BLOCK = {232: (232,), 230: (230,), 268: tuple(range(268, 280)), 256: tuple(range(256, 262))}
VERIFIED = jm.JOURNAL_FLAG_START_VERIFIED


def raises(exc, fn) -> bool:
    try:
        fn()
    except exc:
        return True
    except Exception:  # noqa: BLE001 - a DIFFERENT exception is not the one under test
        return False
    return False


# ---------------------------------------------------------------------------
# Scenario: the inverter before START, and what START intends.
# ---------------------------------------------------------------------------
ORIGINAL = {
    230: 120, 231: 0, 232: 0x0010,
    **dict(zip(range(256, 262), (1000, 1200, 800, 1000, 100, 3000))),
    **{a: 0 for a in range(262, 268)},
    **dict(zip(range(268, 274), (20, 20, 30, 10, 20, 50))),
    **dict(zip(range(274, 280), (0x0000, 0x0004, 0x0008, 0x0010, 0x0021, 0x0106))),
    244: 1, **{a: 0 for a in range(245, 256)},
}
MAX_POWER_W, BATTERY_V = 3000, 52.0
AMPS = round(MAX_POWER_W / BATTERY_V)
INTENDED = {
    **ORIGINAL, 230: AMPS, 232: ORIGINAL[232] | 0x0001,
    **{a: MAX_POWER_W for a in range(256, 262)},
    **{a: 100 for a in range(268, 274)},
    **{a: (ORIGINAL[a] & 0xFFFC) | 0x0001 for a in range(274, 280)},
}


def _env(sim, max_power=MAX_POWER_W) -> None:
    # Other scripts START may trigger are recorded (sim.executed) but not run:
    # their own behaviour is covered by their own suites.
    sim.scripts = dict(sim.scripts)
    sim.scripts["restore_free_power_snapshot"] = {"then": []}
    sim.scripts["poll_inverter_configuration"] = {"then": []}
    sim.ent("free_power_write_enable").state = True
    sim.ent("configuration_online").state = True
    sim.g["ntp_synced"] = True
    sim.ent("ecco_battery_voltage").set(BATTERY_V)
    sim.ent("free_power_duration_minutes").set(60)
    sim.ent("free_power_max_power").set(max_power)


_POOL: dict = {}


def fresh_sim(fw=FW, pooled=False) -> "ds.Sim":
    """A power-on-reset device (RAM globals at their initial values, empty
    NVS unless the caller seeds it). `pooled=True` reuses ONE Sim per
    firmware variant (keeping its compiled-lambda cache) for the fault sweep;
    a pooled result is only valid until the next pooled run."""
    if not pooled:
        return ds.Sim(fw)
    sim = _POOL.get(id(fw))
    if sim is None:
        sim = _POOL[id(fw)] = ds.Sim(fw)
    sim.g = {g["id"]: sim._initial(g["type"], g.get("initial_value")) for g in fw["globals"]}
    sim.entities = {"ntp_time": ds.Clock(sim, "ntp_time")}
    sim.reset_durable()
    sim.event_hook = None
    sim.bank = {}
    sim.modbus_log = []
    sim.executed = []
    sim.running = set()
    sim.outcome_fn = lambda kind, addr, count: "ok"
    sim.read_override_fn = None
    return sim


def run_start(fw=FW, write_outcomes=None, fail_journal=(), nvs=None, hook=None, read_override=None,
              max_power=MAX_POWER_W, bank=None, pooled=False):
    """Runs the REAL start_free_power_override end to end. `hook(sim, event)`
    is called at every durable/Modbus event (see _dump_sim event_hook)."""
    sim = fresh_sim(fw, pooled)
    _env(sim, max_power)
    sim.bank = dict(bank or ORIGINAL)
    if nvs:
        sim.nvs = {k: v.copy() for k, v in nvs.items()}
    wo = write_outcomes or {}
    sim.outcome_fn = lambda kind, addr, count: wo.get(addr, "ok") if kind == "write" else "ok"
    sim.read_override_fn = read_override
    if fail_journal:
        sim.nvs_fail_attempts[JKEY] = set(fail_journal)
    sim.event_hook = (lambda e: hook(sim, e)) if hook else None
    sim.execute("start_free_power_override")
    return sim


def journal_events(sim):
    return [e for e in sim.events if e[0] == "commit" and e[1] == JKEY]


def ok_journal_masks(sim):
    return [(e[2].start_attempted, e[2].flags) for e in journal_events(sim) if e[3]]


def writes(sim):
    return [e[1] for e in sim.events if e[0] == "write"]


def ram_journal(sim):
    return tuple(sim.g[k] for k in jm.RAM_GLOBALS)


def statuses(sim):
    return [str(s) for s in sim.ent("free_power_status").published]


def durable_data_binding(sim) -> int:
    return jm.journal_binding(sim.nvs[DATA_KEY])


# on_boot slices (the REAL firmware text).
FP_BOOT_START = "// Durable recovery snapshots (Free Power, Register 244) now live in"
FP_BOOT_END = "// Manual Dump-to-Grid V1 (2026-09-26) - same fail-closed marker/"
JOURNAL_BOOT_MARK = "// SG-01 Phase 2: load the Free Power START journal"


def boot_text(fw) -> str:
    return fw["esphome"]["on_boot"]["then"][0]["lambda"]


def fp_boot_block(fw=FW) -> str:
    boot = boot_text(fw)
    return boot[boot.index(FP_BOOT_START):boot.index(FP_BOOT_END)]


def journal_boot_block(fw=FW) -> str:
    block = fp_boot_block(fw)
    open_idx = block.rindex("{", 0, block.index(JOURNAL_BOOT_MARK))
    return block[open_idx: open_idx + fpsim._skip_one_statement(block[open_idx:])]


def fp_boot_block_without_journal(fw=FW) -> str:
    return fp_boot_block(fw).replace(journal_boot_block(fw), "")


def boot(nvs: dict, fw=FW, block=None, fail_load=()) -> "ds.Sim":
    """A fresh ESP boot over `nvs`: runs the real Free Power boot block
    (marker/data load, retry-state load, START journal load)."""
    sim = fresh_sim(fw)
    sim.nvs = {k: v.copy() for k, v in nvs.items()}
    sim.nvs_fail_load_tags = set(fail_load)
    sim.run_lambda(block if block is not None else fp_boot_block(fw))
    return sim


def non_journal_ram(sim) -> dict:
    return {k: v for k, v in sim.g.items() if k not in jm.RAM_GLOBALS}


# ===========================================================================
print("[1] Phase 1: production journal schema")
# ===========================================================================
struct_m = re.search(r"struct FreePowerStartJournal \{(.*?)\n\};", HEADER, re.S)
check("header defines struct FreePowerStartJournal", struct_m is not None)
fields = re.findall(r"\b(uint\d+_t) (\w+);", struct_m.group(1)) if struct_m else []
check("fields are exactly uint32 magic, uint8 start_attempted, uint8 flags, uint16 reserved, uint64 binding",
      fields == [("uint32_t", "magic"), ("uint8_t", "start_attempted"), ("uint8_t", "flags"),
                 ("uint16_t", "reserved"), ("uint64_t", "binding")], str(fields))
check("...in the model's order", [f for _t, f in fields] == jm.JOURNAL_FIELDS)
check("sizeof == 16 is a compile-time assertion",
      'static_assert(sizeof(FreePowerStartJournal) == 16, "SG-01 START journal record must be exactly 16 bytes");' in HEADER)
check("field offsets 0/4/5/6/8 are compile-time assertions",
      all(f"offsetof(FreePowerStartJournal, {f}) == {o}" in HEADER
          for f, o in (("magic", 0), ("start_attempted", 4), ("flags", 5), ("reserved", 6), ("binding", 8))))
check("record is asserted trivially copyable (commit_record's own requirement)",
      "static_assert(std::is_trivially_copyable<FreePowerStartJournal>::value" in HEADER)
check("the model's native-layout mirror agrees: 16 bytes, offsets 0/4/5/6/8",
      jm.ctypes.sizeof(jm.JournalC) == 16
      and [getattr(jm.JournalC, f).offset for f in jm.JOURNAL_FIELDS] == [0, 4, 5, 6, 8])
tag_m = re.search(r'constexpr const char \*FREE_POWER_START_JOURNAL_TAG = "([^"]+)";', HEADER)
check("tag is ecco_free_power_start_journal_v1 (header == model == sim)",
      tag_m is not None and tag_m.group(1) == jm.JOURNAL_TAG == JKEY == "ecco_free_power_start_journal_v1")
magic_m = re.search(r"constexpr uint32_t FREE_POWER_START_JOURNAL_MAGIC = (0x[0-9A-Fa-f]+)u;", HEADER)
check("magic is 0x4543534A (header == model)", magic_m is not None and int(magic_m.group(1), 16) == jm.JOURNAL_MAGIC == 0x4543534A)
hdr_consts = {n: int(v, 16) for n, v in re.findall(r"constexpr uint8_t (FREE_POWER_START_JOURNAL_\w+) = (0x[0-9A-Fa-f]+);", HEADER)}
check("prefix masks B1..B4 are 0x01/0x03/0x07/0x0F (header == model == sim)",
      [hdr_consts.get(f"FREE_POWER_START_JOURNAL_MASK_B{i}") for i in (1, 2, 3, 4)] == list(MASKS) == [1, 3, 7, 15]
      and [getattr(D, f"FREE_POWER_START_JOURNAL_MASK_B{i}") for i in (1, 2, 3, 4)] == [1, 3, 7, 15], str(hdr_consts))
check("START_VERIFIED is flag bit0 and the only known flag (header == model)",
      hdr_consts.get("FREE_POWER_START_JOURNAL_FLAG_START_VERIFIED") == jm.JOURNAL_FLAG_START_VERIFIED == 1
      and "FREE_POWER_START_JOURNAL_KNOWN_FLAGS = FREE_POWER_START_JOURNAL_FLAG_START_VERIFIED;" in HEADER)
check("the header keeps every PRE-EXISTING record struct byte-for-byte (no durable format changed)",
      all(s in HEADER for s in ("struct ValidMarker {\n  uint32_t magic;\n  uint8_t state;  // one of MarkerState\n};",
                                "struct Reg244SnapshotData {\n  uint16_t value;\n};",
                                "struct FreePowerRetryState {\n  uint8_t operator_needed;",
                                "struct DumpToGridRetryState {\n  uint8_t operator_needed;\n};"))
      and re.findall(r"\buint(?:8|16|32)_t (\w+);", re.search(r"struct FreePowerSnapshotData \{(.*?)\n\};", HEADER, re.S).group(1))
      == ds._RECORD_FIELDS["FreePowerSnapshotData"])
check("every pre-existing tag string is unchanged",
      all(f'"{v}"' in HEADER for v in ("ecco_free_power_snapshot_data_v4", "ecco_free_power_snapshot_valid_v1",
                                        "ecco_reg244_snapshot_data_v1", "ecco_reg244_snapshot_valid_v1",
                                        "ecco_dump_to_grid_snapshot_data_v1", "ecco_dump_to_grid_snapshot_valid_v1",
                                        "ecco_free_power_retry_state_v1", "ecco_dump_to_grid_retry_state_v1")))

# ===========================================================================
print("[2] Phase 1: binding helper - C++ definition and golden vectors vs the Python mirror")
# ===========================================================================


def header_binding_spec(header: str):
    """(domain, nul_excluded, basis, prime, [(width, field), ...]) as the
    header's free_power_start_journal_binding() actually computes it."""
    body_m = re.search(r"constexpr uint64_t free_power_start_journal_binding\(const FreePowerSnapshotData &s\) \{(.*?)\n\}",
                       header, re.S)
    if not body_m:
        return None
    body = body_m.group(1)
    dom = re.search(r'constexpr char FREE_POWER_START_JOURNAL_BINDING_DOMAIN\[\] = "([^"]*)";', header)
    nul_excluded = "for (size_t i = 0; i + 1 < sizeof(FREE_POWER_START_JOURNAL_BINDING_DOMAIN); i++)" in body
    starts_at_basis = "uint64_t h = ecco_recovery_evidence::FNV64_OFFSET_BASIS;" in body
    step_uses_prime = "return (hash ^ byte) * ecco_recovery_evidence::FNV64_PRIME;" in header
    order = re.findall(r"h = fnv1a64_step_(u16le|u32le)\(h, s\.(\w+)\);", body)
    return dom.group(1) if dom else None, nul_excluded, starts_at_basis, step_uses_prime, order


spec = header_binding_spec(HEADER)
check("header binding helper found", spec is not None)
if spec:
    domain, nul_excluded, at_basis, uses_prime, order = spec
    check("domain is exactly the model's 24 ASCII bytes", domain.encode("ascii") == jm.BINDING_DOMAIN and len(domain) == 24)
    check("domain loop stops before the NUL terminator (`i + 1 < sizeof(...)`) - the NUL is never hashed", nul_excluded)
    check("the header also asserts the 24-byte, NUL-free domain length at compile time",
          'static_assert(sizeof(FREE_POWER_START_JOURNAL_BINDING_DOMAIN) - 1 == 24, "binding domain is 24 bytes, no NUL");' in HEADER)
    check("hash starts at ecco_recovery_evidence::FNV64_OFFSET_BASIS and steps with FNV64_PRIME (FNV-1a: xor, then multiply)",
          at_basis and uses_prime)
    ev_consts = dict(re.findall(r"constexpr uint64_t (FNV64_\w+) = (0x[0-9a-fA-F]+)ULL;", EVIDENCE_HEADER))
    check("the reused ecco_recovery_evidence constants are the model's FNV-1a-64 basis/prime",
          int(ev_consts.get("FNV64_OFFSET_BASIS", "0"), 16) == jm.FNV64_OFFSET_BASIS
          and int(ev_consts.get("FNV64_PRIME", "0"), 16) == jm.FNV64_PRIME)
    check("the reused evidence helper is the same FNV-1a step (xor byte, multiply prime) - SG-01 adds no second algorithm",
          "hash ^= data[i];\n    hash *= FNV64_PRIME;" in EVIDENCE_HEADER)
    check("end_epoch is hashed FIRST, as u32 little-endian", order[:1] == [("u32le", "end_epoch")], str(order[:1]))
    check("then exactly the model's 23 u16 LE fields, in FreePowerSnapshotData order",
          order[1:] == [("u16le", f) for f in jm.BINDING_U16_FIELDS], str(order[1:]))
    check("active_persisted and restore_requested are NOT hashed",
          not any(f in jm.BINDING_EXCLUDED_FIELDS for _w, f in order))
    check("u16le hashes low byte then high byte; u32le = low u16le then high u16le",
          "fnv1a64_step(fnv1a64_step(hash, (uint8_t) (v & 0xFF)), (uint8_t) ((v >> 8) & 0xFF))" in HEADER
          and "fnv1a64_step_u16le(fnv1a64_step_u16le(hash, (uint16_t) (v & 0xFFFF)), (uint16_t) ((v >> 16) & 0xFFFF))" in HEADER)

# The header's compile-time golden vectors, re-derived in Python.
SNAP_FIELDS = ds._RECORD_FIELDS["FreePowerSnapshotData"]


def _c_int(tok: str) -> int:
    return int(tok.strip().rstrip("uUlL"), 0)


golden = re.findall(
    r"static_assert\(free_power_start_journal_binding\(FreePowerSnapshotData\{(.*?)\}\) == (0x[0-9A-F]+)ULL,", HEADER, re.S)
check("header carries 4 compile-time binding golden vectors (zero, typical, typical with flipped lifecycle flags, all-ones)",
      len(golden) == 4, str(len(golden)))
for init, expected in golden:
    values = [_c_int(t) for t in init.split(",")] if init.strip() else []
    snap = dict(zip(SNAP_FIELDS, values + [0] * (len(SNAP_FIELDS) - len(values))))
    py = jm.journal_binding(snap)
    check(f"C++ golden vector {expected}: the Python mirror computes the same value",
          len(values) in (0, 26) and py == int(expected, 16), f"python={py:#018x}")
check("the typical and flipped-lifecycle-flag vectors pin the SAME value (exclusion is compile-time pinned)",
      len(golden) == 4 and golden[1][1] == golden[2][1] and golden[1][0] != golden[2][0])
fnv_m = re.search(r"'f'\), 'o'\), 'o'\), 'b'\), 'a'\), 'r'\) ==\s*(0x[0-9A-F]+)ULL", HEADER)
check("header's FNV-1a-64 'foobar' known answer matches the Python mirror",
      fnv_m is not None and int(fnv_m.group(1), 16) == jm.fnv1a_64(b"foobar"))
typical = dict(zip(SNAP_FIELDS, [_c_int(t) for t in golden[1][0].split(",")])) if len(golden) == 4 else jm.blank_snapshot()
tail = jm.binding_input_bytes(typical)[len(jm.BINDING_DOMAIN):]
check("including the domain's NUL terminator would change the typical vector (so the golden vector pins its absence)",
      jm.fnv1a_64(jm.BINDING_DOMAIN + b"\0" + tail) != jm.journal_binding(typical))
be = jm.BINDING_DOMAIN + typical["end_epoch"].to_bytes(4, "big") + b"".join(
    typical[f].to_bytes(2, "big") for f in jm.BINDING_U16_FIELDS)
check("big-endian encoding would change the typical vector (so it pins little-endian)",
      jm.fnv1a_64(be) != jm.journal_binding(typical))
with_flags = jm.BINDING_DOMAIN + jm.binding_input_bytes(typical)[len(jm.BINDING_DOMAIN):len(jm.BINDING_DOMAIN) + 4] \
    + bytes([typical["active_persisted"], typical["restore_requested"]]) + tail[4:]
check("hashing active_persisted/restore_requested would change the typical vector (so it pins their exclusion)",
      jm.fnv1a_64(with_flags) != jm.journal_binding(typical))
# Mutation: the spec parser is not vacuous.
for label, old, new in (
    ("NUL included", "i + 1 < sizeof(FREE_POWER_START_JOURNAL_BINDING_DOMAIN)", "i < sizeof(FREE_POWER_START_JOURNAL_BINDING_DOMAIN)"),
    ("reg230/reg232 swapped", "h = fnv1a64_step_u16le(h, s.reg230);\n  h = fnv1a64_step_u16le(h, s.reg232);",
     "h = fnv1a64_step_u16le(h, s.reg232);\n  h = fnv1a64_step_u16le(h, s.reg230);"),
    ("active_persisted added", "h = fnv1a64_step_u16le(h, s.reg230);\n", "h = fnv1a64_step_u16le(h, s.active_persisted);\n  h = fnv1a64_step_u16le(h, s.reg230);\n"),
):
    mutated = header_binding_spec(HEADER.replace(old, new, 1))
    check(f"mutation [{label}] of the header binding is detected by the spec checks",
          HEADER.count(old) == 1 and mutated != spec
          and not (mutated[1] and mutated[4] == [("u32le", "end_epoch")] + [("u16le", f) for f in jm.BINDING_U16_FIELDS]))

# ===========================================================================
print("[3] Phase 1: validation rules - header vs Python mirror")
# ===========================================================================
valid_m = re.search(r"constexpr bool free_power_start_journal_valid\(const FreePowerStartJournal &j, uint64_t expected_binding\) \{(.*?)\n\}",
                    HEADER, re.S)
vbody = " ".join(valid_m.group(1).split()) if valid_m else ""
for label, fragment in (
    ("magic", "j.magic == FREE_POWER_START_JOURNAL_MAGIC"),
    ("reserved must be zero", "j.reserved == 0"),
    ("unknown flag bits", "(j.flags & (uint8_t) ~FREE_POWER_START_JOURNAL_KNOWN_FLAGS) == 0"),
    ("prefix mask", "free_power_start_journal_mask_valid(j.start_attempted)"),
    ("START_VERIFIED only with mask 15", "((j.flags & FREE_POWER_START_JOURNAL_FLAG_START_VERIFIED) == 0 || j.start_attempted == FREE_POWER_START_JOURNAL_MASK_B4)"),
    ("binding", "j.binding == expected_binding"),
):
    check(f"header validator enforces: {label}", fragment in vbody)
check("header validator is a single &&-conjunction (every rule is mandatory)", vbody.count("&&") == 5 and "||" in vbody
      and vbody.count("||") == 1)
mask_m = re.search(r"constexpr bool free_power_start_journal_mask_valid\(uint8_t mask\) \{(.*?)\n\}", HEADER, re.S)
check("header mask validator accepts exactly 0 and the four prefix masks",
      mask_m is not None and " ".join(mask_m.group(1).split())
      == "return mask == 0 || mask == FREE_POWER_START_JOURNAL_MASK_B1 || mask == FREE_POWER_START_JOURNAL_MASK_B2 || "
         "mask == FREE_POWER_START_JOURNAL_MASK_B3 || mask == FREE_POWER_START_JOURNAL_MASK_B4;")

CONSTS = {"FREE_POWER_START_JOURNAL_MAGIC": jm.JOURNAL_MAGIC}
cases = re.findall(r"(!?)free_power_start_journal_valid\(FreePowerStartJournal\{([^}]*)\}, (\d+)\)", HEADER)
n_agree = 0
for neg, init, expected_binding in cases:
    vals = [CONSTS[t.strip()] if t.strip() in CONSTS else _c_int(t) for t in init.split(",")]
    rec = ds.Record(jm.JOURNAL_KIND, *vals)
    if jm.journal_valid(rec, int(expected_binding)) == (neg != "!"):
        n_agree += 1
check(f"every one of the header's {len(cases)} compile-time validation cases agrees with the Python mirror",
      len(cases) >= 20 and n_agree == len(cases), f"{n_agree}/{len(cases)}")


def J(magic=jm.JOURNAL_MAGIC, mask=1, flags=0, reserved=0, binding=5):
    return ds.Record(jm.JOURNAL_KIND, magic, mask, flags, reserved, binding)


check("valid: masks 0/1/3/7/15 with flags 0, and 15 + START_VERIFIED",
      all(jm.journal_valid(J(mask=m), 5) for m in (0, 1, 3, 7, 15)) and jm.journal_valid(J(mask=15, flags=1), 5))
check("wrong magic rejected (every single-bit flip of the magic)",
      all(not jm.journal_valid(J(magic=jm.JOURNAL_MAGIC ^ (1 << b)), 5) for b in range(32)))
check("non-zero reserved rejected (every single bit)", all(not jm.journal_valid(J(reserved=1 << b), 5) for b in range(16)))
check("unknown flag bits rejected (bits 1..7, alone and with VERIFIED)",
      all(not jm.journal_valid(J(mask=15, flags=f), 5) for b in range(1, 8) for f in (1 << b, (1 << b) | 1)))
check("every start_attempted outside {0,1,3,7,15} rejected (all 251 values)",
      all(not jm.journal_valid(J(mask=m), 5) for m in range(256) if m not in (0, 1, 3, 7, 15)))
check("START_VERIFIED with a partial mask rejected", all(not jm.journal_valid(J(mask=m, flags=1), 5) for m in (0, 1, 3, 7)))
check("binding mismatch rejected (any other expected binding)",
      all(not jm.journal_valid(J(mask=15, flags=1, binding=5), other) for other in (0, 4, 6, 5 ^ (1 << 63))))
check("the sim's firmware-facing validator is the mirror", D.free_power_start_journal_valid(J(), 5) is True
      and D.free_power_start_journal_valid(J(reserved=1), 5) is False)

# ===========================================================================
print("[4] Phase 2: START happy path - commit BEFORE each write, exact timeline")
# ===========================================================================
sim = run_start()
ev = [(e[0], e[1]) if e[0] != "commit" else ("commit", e[1], e[2].start_attempted if e[1] == JKEY else None, e[3])
      for e in sim.events]
EXPECTED_TIMELINE = [
    ("read", 230), ("read", 256), ("read", 244),
    ("commit", DATA_KEY, None, True), ("commit", VALID_KEY, None, True), ("commit", RETRY_KEY, None, True),
    ("commit", JKEY, 0x01, True), ("write", 232),
    ("commit", JKEY, 0x03, True), ("write", 230),
    ("commit", JKEY, 0x07, True), ("write", 268), ("read", 268),
    ("commit", JKEY, 0x0F, True), ("write", 256),
    ("read", 230), ("read", 256),
    ("commit", DATA_KEY, None, True), ("commit", JKEY, 0x0F, True),
]
check("happy path timeline is exactly: snapshot reads, data, marker, retry, J1, W232, J3, W230, J7, W268, R268, "
      "J15, W256, verify reads, active_persisted re-commit, J15+VERIFIED", ev == EXPECTED_TIMELINE, str(ev))
for k, addr in enumerate(START_WRITES):
    i = next(n for n, e in enumerate(sim.events) if e[0] == "write" and e[1] == addr)
    prev = sim.events[i - 1]
    check(f"the event IMMEDIATELY before write B{k + 1} ({addr}) is its successful journal commit (mask {MASKS[k]:#04x})",
          prev[0] == "commit" and prev[1] == JKEY and prev[3] and prev[2].start_attempted == MASKS[k], str(prev[:2]))
first_j = next(n for n, e in enumerate(sim.events) if e[0] == "commit" and e[1] == JKEY)
first_w = next(n for n, e in enumerate(sim.events) if e[0] == "write")
check("B1 journal is committed AFTER the snapshot, marker and retry-reset commits and BEFORE any write",
      [e[1] for e in sim.events[:first_j] if e[0] == "commit"] == [DATA_KEY, VALID_KEY, RETRY_KEY] and first_j < first_w)
recs = [e[2] for e in journal_events(sim)]
check("every journal record: magic 0x4543534A, reserved 0", all(r.magic == jm.JOURNAL_MAGIC and r.reserved == 0 for r in recs))
check("journal (mask, flags) sequence is (1,0) (3,0) (7,0) (15,0) (15,VERIFIED)",
      [(r.start_attempted, r.flags) for r in recs] == [(1, 0), (3, 0), (7, 0), (15, 0), (15, VERIFIED)])
check("every journal record's binding == FNV binding of the DURABLE snapshot record START committed",
      len({r.binding for r in recs}) == 1 and recs[0].binding == durable_data_binding(sim))
check("...and of the FIRST snapshot commit specifically (the one START made before any write)",
      recs[0].binding == jm.journal_binding(sim.commits_for(DATA_KEY)[0]))
check("durable journal ends at mask 15 + START_VERIFIED and is valid against the durable snapshot",
      jm.journal_valid(sim.nvs[JKEY], durable_data_binding(sim)) and sim.nvs[JKEY].start_attempted == 15
      and sim.nvs[JKEY].flags == VERIFIED)
check("RAM mirror = (valid, 15, VERIFIED, binding)", ram_journal(sim) == (True, 15, VERIFIED, recs[0].binding))
check("activation unchanged: bank holds exactly the intended state, ACTIVE - VERIFIED OK, no restore",
      sim.bank == INTENDED and sim.g["free_power_active_persisted"] is True and not sim.g["free_power_write_failed"]
      and statuses(sim)[-1].startswith("ACTIVE - VERIFIED OK")
      and [s for s, _ in sim.executed] == ["start_free_power_override", "poll_inverter_configuration"])
check("the journal never makes metadata corrupt and never touches the obligation marker",
      not sim.g["free_power_recovery_metadata_corrupt"] and sim.nvs[VALID_KEY].state == D.MARKER_RESTORE_REQUIRED)

# START entry resets the RAM mirror; no durable reset record.
stale_nvs = dict(sim.nvs)
stale_nvs[VALID_KEY] = ds.Record("ValidMarker", D.VALID_MARKER_MAGIC, D.MARKER_CLEAR)  # lease since restored/cleared
sim2 = fresh_sim()
_env(sim2)
sim2.bank = dict(ORIGINAL)
sim2.nvs = {k: v.copy() for k, v in stale_nvs.items()}
sim2.g.update(dict(zip(jm.RAM_GLOBALS, (True, 15, VERIFIED, 0xDEAD))))
sim2.outcome_fn = lambda kind, addr, count: "error" if (kind, addr) == ("read", 230) else "ok"
sim2.execute("start_free_power_override")
check("START entry resets RAM mirror to (false, 0, 0, 0) even when START then aborts before any commit",
      ram_journal(sim2) == (False, 0, 0, 0) and writes(sim2) == [])
check("...with NO durable journal write at all (no reset record); the stale durable journal is untouched",
      journal_events(sim2) == [] and sim2.nvs[JKEY].start_attempted == 15 and sim2.nvs[JKEY].binding == recs[0].binding)
sim3 = run_start(nvs=stale_nvs, max_power=2000)
check("the next START's B1 commit is its FIRST durable journal write and overwrites the stale record "
      "(new binding, mask 1 -> ... -> 15+VERIFIED)",
      [(r.start_attempted, r.flags) for r in (e[2] for e in journal_events(sim3))][0] == (1, 0)
      and journal_events(sim3)[0][2].binding == durable_data_binding(sim3) != recs[0].binding
      and sim3.nvs[JKEY].binding == durable_data_binding(sim3))

# ===========================================================================
print("[5] Phase 2: journal commit failure before B1 / B2 / B3 / B4 (C/D/E/F)")
# ===========================================================================


def obligation_intact(sim) -> list[str]:
    p = []
    if sim.nvs.get(VALID_KEY) is None or sim.nvs[VALID_KEY].state != D.MARKER_RESTORE_REQUIRED:
        p.append("durable marker not RESTORE_REQUIRED")
    if DATA_KEY not in sim.nvs:
        p.append("durable snapshot missing")
    if not sim.g["free_power_snapshot_valid"]:
        p.append("snapshot_valid cleared")
    if sim.g["free_power_active_persisted"]:
        p.append("active_persisted set")
    if sim.g["free_power_recovery_metadata_corrupt"]:
        p.append("metadata_corrupt set")
    if sim.g["free_power_operation_in_progress"] or sim.g["manual_write_in_progress"]:
        p.append("ownership locks not released")
    if not sim.g["free_power_write_failed"]:
        p.append("write_failed not set")
    return p


sim = run_start(fail_journal={1})
check("[C] B1 journal commit fails -> ZERO START writes", writes(sim) == [], str(writes(sim)))
check("[C] ...inverter untouched", sim.bank == ORIGINAL)
check("[C] ...no journal committed durably, RAM mirror stays invalid",
      JKEY not in sim.nvs and ram_journal(sim) == (False, 0, 0, 0))
# The PRE-EXISTING commit-failure route (the same one a failed retry-lockout
# reset already takes - SG-01 reuses it unchanged): "START FAILED ... nothing
# written", then the sibling activation gate's else-branch hands the
# still-committed snapshot to restore_free_power_snapshot.
check("[C] ...takes the existing commit-failure route: START FAILED (nothing written), then restore of the "
      "committed snapshot, with the durable obligation intact (not cleared)",
      not obligation_intact(sim)
      and "START FAILED - could not durably commit the recovery snapshot; nothing written" in statuses(sim)
      and [s for s, _ in sim.executed] == ["start_free_power_override", "restore_free_power_snapshot"],
      f"{obligation_intact(sim)} {statuses(sim)} {sim.executed}")
retry_fail = fresh_sim()
_env(retry_fail)
retry_fail.bank = dict(ORIGINAL)
retry_fail.nvs_fail_attempts[RETRY_KEY] = {1}
retry_fail.execute("start_free_power_override")
check("[C] ...byte-for-byte the same route and outcome as the pre-SG-01 retry-reset commit failure",
      statuses(retry_fail) == statuses(sim) and [x for x, _ in retry_fail.executed] == [x for x, _ in sim.executed]
      and {k: v for k, v in retry_fail.g.items() if k not in jm.RAM_GLOBALS}
      == {k: v for k, v in sim.g.items() if k not in jm.RAM_GLOBALS})
for k, (fail_at, expect_writes, label) in enumerate(((2, [232], "D"), (3, [232, 230], "E"), (4, [232, 230, 268], "F")),
                                                      start=2):
    sim = run_start(fail_journal={fail_at})
    check(f"[{label}] B{k} journal commit fails -> only {expect_writes} written, no later START write",
          writes(sim) == expect_writes, str(writes(sim)))
    check(f"[{label}] ...the durable journal still holds the last GOOD prefix ({MASKS[k - 2]:#04x}) and RAM matches it",
          sim.nvs[JKEY].start_attempted == MASKS[k - 2] and ram_journal(sim)[:3] == (True, MASKS[k - 2], 0))
    check(f"[{label}] ...routed to the existing restore with the obligation intact",
          not obligation_intact(sim) and [s for s, _ in sim.executed] == ["start_free_power_override", "restore_free_power_snapshot"]
          and statuses(sim)[-1] == "ACTIVATION WRITE FAILED - restoring saved snapshot",
          f"{obligation_intact(sim)} {sim.executed} {statuses(sim)[-1:]}")
    blocks_written = [a for w in expect_writes for a in BLOCK[w]]
    check(f"[{label}] ...every block START did not write is still ORIGINAL",
          all(sim.bank[a] == ORIGINAL[a] for a in ORIGINAL if a not in blocks_written))
check("[F] ...TOU Power ceilings (256-261) keep their originals", all(sim.bank[a] == ORIGINAL[a] for a in range(256, 262)))
check("[F] B4 journal commit is not even attempted when the 268-279 readback did not confirm the overlay",
      (lambda s: [r.start_attempted for r in (e[2] for e in journal_events(s))] == [1, 3, 7] and writes(s) == [232, 230, 268])(
          run_start(read_override=lambda addr, count, v: [99] + v[1:] if (addr, count) == (268, 12) else v)))

# ===========================================================================
print("[6] Phase 2: START_VERIFIED - success persists, failure is harmless (J/K)")
# ===========================================================================
ok_sim = run_start()
check("[J] successful START_VERIFIED: durable journal = mask 15 + VERIFIED, RAM flags VERIFIED",
      (ok_sim.nvs[JKEY].start_attempted, ok_sim.nvs[JKEY].flags) == (15, VERIFIED) and ok_sim.g["free_power_start_journal_flags"] == VERIFIED)
check("[J] START_VERIFIED is the LAST durable write of START, after the active_persisted re-commit",
      ok_sim.events[-1][0] == "commit" and ok_sim.events[-1][1] == JKEY and ok_sim.events[-2][1] == DATA_KEY
      and ok_sim.events[-2][2].active_persisted == 1)
k_sim = run_start(fail_journal={5})
check("[K] START_VERIFIED commit fails: the verified lease stays ACTIVE (active_persisted, no write_failed)",
      k_sim.g["free_power_active_persisted"] is True and not k_sim.g["free_power_write_failed"]
      and statuses(k_sim)[-1].startswith("ACTIVE - VERIFIED OK"))
check("[K] ...no rollback: no restore executed, no extra Modbus write, bank still the intended state",
      [s for s, _ in k_sim.executed] == ["start_free_power_override", "poll_inverter_configuration"]
      and writes(k_sim) == list(START_WRITES) and k_sim.bank == INTENDED)
check("[K] ...the verified flag is NOT assumed durable: RAM flags 0, durable journal still mask 15 / flags 0",
      k_sim.g["free_power_start_journal_flags"] == 0 and (k_sim.nvs[JKEY].start_attempted, k_sim.nvs[JKEY].flags) == (15, 0)
      and k_sim.g["free_power_start_journal_mask"] == 15 and k_sim.g["free_power_start_journal_valid"] is True)
check("[K] ...no metadata corruption, obligation marker untouched, failure counters untouched",
      not k_sim.g["free_power_recovery_metadata_corrupt"] and k_sim.nvs[VALID_KEY].state == D.MARKER_RESTORE_REQUIRED
      and k_sim.g["free_power_failures"] == 0 and k_sim.g["free_power_start_successes"] == 1)
check("[K] ...apart from the journal flags, the device ends byte-for-byte as in the successful case",
      {k: v for k, v in k_sim.g.items() if k != "free_power_start_journal_flags"}
      == {k: v for k, v in ok_sim.g.items() if k != "free_power_start_journal_flags"}
      and k_sim.modbus_log == ok_sim.modbus_log and statuses(k_sim) == statuses(ok_sim))
bad_verify = run_start(read_override=lambda addr, count, v: [v[0] + 1] + v[1:] if (addr, count) == (256, 24) else v)
check("START_VERIFIED is never written when activation verify FAILS (journal stays 15 / flags 0, restore runs)",
      [(r.start_attempted, r.flags) for r in (e[2] for e in journal_events(bad_verify))] == [(1, 0), (3, 0), (7, 0), (15, 0)]
      and bad_verify.g["free_power_start_journal_flags"] == 0
      and [s for s, _ in bad_verify.executed][-1] == "restore_free_power_snapshot")

# ===========================================================================
print("[7] Phase 2: fault sweep - journal commit failure position x START write outcomes")
# ===========================================================================
SWEEP_WRITE_OUTCOMES = ("ok", "ack_not_applied", "error", "timeout_landed", "no_response_lost")
n = 0
bad = {k: [] for k in ("adjacent", "after_fail", "prefix", "ram", "cover", "obligation", "verified", "binding", "corrupt")}
for fail_at in (None, 1, 2, 3, 4, 5):
    for outs in itertools.product(SWEEP_WRITE_OUTCOMES, repeat=4):
        wo = dict(zip(START_WRITES, outs))
        s = run_start(write_outcomes=wo, fail_journal={fail_at} if fail_at else (), pooled=True)
        n += 1
        w = writes(s)
        # (a) each START write is IMMEDIATELY preceded by its own successful journal commit.
        for idx, e in enumerate(s.events):
            if e[0] == "write":
                k = START_WRITES.index(e[1])
                prev = s.events[idx - 1]
                if not (prev[0] == "commit" and prev[1] == JKEY and prev[3] and prev[2].start_attempted == MASKS[k]):
                    bad["adjacent"].append((fail_at, wo, e[1]))
        # (b) nothing is written after a failed journal commit.
        failed_idx = [i for i, e in enumerate(s.events) if e[0] == "commit" and e[1] == JKEY and not e[3]]
        if failed_idx and any(e[0] == "write" for e in s.events[failed_idx[0]:]):
            bad["after_fail"].append((fail_at, wo))
        # (c) writes are a strict prefix of B1..B4.
        if w != list(START_WRITES[:len(w)]):
            bad["prefix"].append((fail_at, wo, w))
        # (d) RAM mirror never runs ahead of durable truth.
        good = ok_journal_masks(s)
        exp_ram = (bool(good), good[-1][0] if good else 0, good[-1][1] if good else 0)
        if ram_journal(s)[:3] != exp_ram or (JKEY in s.nvs and (s.nvs[JKEY].start_attempted, s.nvs[JKEY].flags) != good[-1]):
            bad["ram"].append((fail_at, wo, ram_journal(s), good))
        # (e) the durable mask covers every block START attempted to write.
        if w and (JKEY not in s.nvs or s.nvs[JKEY].start_attempted < MASKS[len(w) - 1]):
            bad["cover"].append((fail_at, wo))
        # (f) START never clears the obligation / sets corruption.
        if s.nvs[VALID_KEY].state != D.MARKER_RESTORE_REQUIRED or not s.g["free_power_snapshot_valid"]:
            bad["obligation"].append((fail_at, wo))
        if s.g["free_power_recovery_metadata_corrupt"]:
            bad["corrupt"].append((fail_at, wo))
        # (g) VERIFIED only after a positive verify, and only as the final journal commit.
        verified_commits = [i for i, e in enumerate(s.events) if e[0] == "commit" and e[1] == JKEY and e[2].flags]
        if verified_commits and (not s.g["free_power_active_persisted"] or verified_commits[0] != len(s.events) - 1):
            bad["verified"].append((fail_at, wo))
        # (h) every journal record is bound to this START's durable snapshot.
        if any(e[2].binding != durable_data_binding(s) for e in journal_events(s)):
            bad["binding"].append((fail_at, wo))
check(f"all {n} combinations executed (6 journal-failure positions x 5^4 write outcomes)", n == 6 * 5 ** 4)
for key, text in (
    ("adjacent", "every START write is immediately preceded by its own successful journal commit"),
    ("after_fail", "no START write ever follows a failed journal commit"),
    ("prefix", "START writes are always a strict prefix of B1..B4"),
    ("ram", "the RAM mirror always equals the last SUCCESSFUL durable journal commit (never ahead of it)"),
    ("cover", "the durable journal mask always covers every block START attempted to write"),
    ("obligation", "START never clears the durable RESTORE_REQUIRED obligation"),
    ("corrupt", "the journal never sets metadata_corrupt"),
    ("verified", "START_VERIFIED is only ever written after a positive activation verify, as START's last durable write"),
    ("binding", "every journal commit is bound to the durable snapshot of the same START"),
):
    check(f"sweep: {text}", not bad[key], f"{len(bad[key])} bad, first: {bad[key][:1]}")

# ===========================================================================
print("[8] Reboot at every commit boundary (A/B)")
# ===========================================================================
cuts = []
run_start(hook=lambda s, e: cuts.append((e, {k: v.copy() for k, v in s.nvs.items()}, dict(s.bank))))
happy_binding = None


def _label(e):
    if e[0] == "commit":
        return f"commit {e[1]}" + (f" mask {e[2].start_attempted:#04x} flags {e[2].flags}" if e[1] == JKEY else "")
    return f"{e[0]} {e[1]}"


for i, (e, nvs, bank) in enumerate(cuts):
    if e[0] == "read":
        continue
    b = boot(nvs)
    if e[0] == "commit" and e[1] == DATA_KEY and VALID_KEY not in nvs:
        continue  # data without marker: no obligation yet - covered by the marker suites
    after = _label(e)
    boot_commits = [x for x in b.events if x[0] == "commit"]
    check(f"reboot after [{after}]: boot performs NO durable commit", boot_commits == [] and b.nvs_commits == [])
    check(f"reboot after [{after}]: never metadata corrupt; obligation still RESTORE_REQUIRED",
          not b.g["free_power_recovery_metadata_corrupt"] and b.g["free_power_snapshot_valid"]
          and b.g["free_power_marker_state"] == D.MARKER_RESTORE_REQUIRED)
    if JKEY not in nvs:
        check(f"reboot after [{after}]: no journal yet -> RAM journal invalid (legacy behaviour)",
              ram_journal(b) == (False, 0, 0, 0))
        continue
    stored = nvs[JKEY]
    check(f"reboot after [{after}]: journal loads valid with the durable mask/flags, bound to the loaded snapshot",
          ram_journal(b) == (True, stored.start_attempted, stored.flags, stored.binding)
          and stored.binding == jm.journal_binding(nvs[DATA_KEY]))
    done = [w for w in START_WRITES if any(x[0] == "write" and x[1] == w for x, _n, _b in cuts[:i + 1])]
    for w in START_WRITES:
        k = START_WRITES.index(w)
        bit_present = stored.start_attempted >= MASKS[k]
        if w in done:
            if not (bit_present and all(bank[a] == INTENDED[a] for a in BLOCK[w])):
                check(f"reboot after [{after}]: written block {w} is INTENDED and its journal bit is present", False)
        elif bit_present:
            check(f"[A] reboot after [{after}]: block {w}'s journal bit is present but the block is still ORIGINAL "
                  f"(commit landed, write did not) - no corruption inferred",
                  all(bank[a] == ORIGINAL[a] for a in BLOCK[w]) and not b.g["free_power_recovery_metadata_corrupt"])
        elif any(bank[a] != ORIGINAL[a] for a in BLOCK[w]):
            check(f"reboot after [{after}]: block {w} changed without its journal bit", False)
    if e[0] == "write":
        k = START_WRITES.index(e[1])
        check(f"[B] reboot after [{after}] lands: journal bit {k + 1} present, the written block is INTENDED, "
              "and the snapshot/intended mirrors needed by Phase 3 are all restored",
              stored.start_attempted == MASKS[k] and all(bank[a] == INTENDED[a] for a in BLOCK[e[1]])
              and b.g["free_power_target_reg230"] == AMPS and b.g["free_power_target_tou_power"] == MAX_POWER_W
              and all(b.g[f"free_power_snapshot_reg{a}"] == ORIGINAL[a] for a in (230, 232, *range(256, 262), *range(268, 280)))
              and b.g["free_power_lease_context_reg244"] == ORIGINAL[244])
check("reboot cuts covered: pre-journal, J1, W232, J3, W230, J7, W268, J15, W256, active re-commit, VERIFIED",
      [_label(e) for e, _n, _b in cuts if e[0] != "read"] == [
          f"commit {DATA_KEY}", f"commit {VALID_KEY}", f"commit {RETRY_KEY}",
          f"commit {JKEY} mask 0x01 flags 0", "write 232", f"commit {JKEY} mask 0x03 flags 0", "write 230",
          f"commit {JKEY} mask 0x07 flags 0", "write 268", f"commit {JKEY} mask 0x0f flags 0", "write 256",
          f"commit {DATA_KEY}", f"commit {JKEY} mask 0x0f flags 1"])

# A STALE journal from an earlier, completed lease must never vouch for a new one.
first = run_start()
old_journal = first.nvs[JKEY].copy()
cleared = {k: v.copy() for k, v in first.nvs.items()}
cleared[VALID_KEY] = ds.Record("ValidMarker", D.VALID_MARKER_MAGIC, D.MARKER_CLEAR)
stale_cuts = []
run_start(nvs=cleared, max_power=2000,
          hook=lambda s, e: stale_cuts.append((e, {k: v.copy() for k, v in s.nvs.items()})))
pre_j1 = next(nv for e, nv in stale_cuts if e[0] == "commit" and e[1] == RETRY_KEY)
b = boot(pre_j1)
check("[G] reboot between a new START's marker commit and its B1 journal commit: the previous lease's journal "
      "(mask 15 + VERIFIED) is still stored but its binding does not match -> invalid, no corruption",
      pre_j1[JKEY].binding == old_journal.binding and pre_j1[JKEY].flags == VERIFIED
      and ram_journal(b) == (False, 0, 0, 0) and not b.g["free_power_recovery_metadata_corrupt"]
      and b.g["free_power_snapshot_valid"])

# ===========================================================================
print("[9] on_boot journal validation (G/H/I) and legacy behaviour")
# ===========================================================================
SNAP = ds.Record("FreePowerSnapshotData")
for f, v in {"end_epoch": 1_790_003_600, "active_persisted": 0, "restore_requested": 0,
             **{f"reg{a}": ORIGINAL[a] for a in (230, 232, *range(256, 262), *range(268, 280))},
             "reg230_intended": AMPS, "reg_tou_power_intended": MAX_POWER_W, "reg244_lease_context_plus1": 2}.items():
    setattr(SNAP, f, v)
BIND = jm.journal_binding(SNAP)
MARKER_REQ = ds.Record("ValidMarker", D.VALID_MARKER_MAGIC, D.MARKER_RESTORE_REQUIRED)
BASE_NVS = {VALID_KEY: MARKER_REQ, DATA_KEY: SNAP}


def with_journal(**kw):
    rec = J(**{"mask": 7, "binding": BIND, **kw})
    return {**BASE_NVS, JKEY: rec}


legacy = boot(BASE_NVS)
check("[H] missing journal (pre-SG-01 obligation): RAM journal invalid, one load attempt, no corruption",
      ram_journal(legacy) == (False, 0, 0, 0) and legacy.nvs_loads.count(JKEY) == 1
      and not legacy.g["free_power_recovery_metadata_corrupt"] and legacy.g["free_power_snapshot_valid"])
good = boot(with_journal())
check("a valid bound journal loads: RAM = (true, 7, 0, binding)", ram_journal(good) == (True, 7, 0, BIND))
check("loading the journal changes NO other RAM global vs the missing-journal boot",
      non_journal_ram(good) == non_journal_ram(legacy))
for label, kw in (
    ("G binding mismatch", {"binding": BIND ^ 1}),
    ("I bad magic", {"magic": 0x4543534B}),
    ("I non-zero reserved", {"reserved": 1}),
    ("I unknown flag bit", {"mask": 15, "flags": 0x02}),
    ("I non-prefix mask 5", {"mask": 5}),
    ("I non-prefix mask 16", {"mask": 16}),
    ("I VERIFIED with mask 7", {"mask": 7, "flags": 1}),
    ("I VERIFIED with mask 0", {"mask": 0, "flags": 1}),
):
    b = boot(with_journal(**kw))
    check(f"[{label}] journal invalid ONLY: RAM (false,0,0,0), no metadata_corrupt, every other RAM global "
          "identical to the missing-journal boot",
          ram_journal(b) == (False, 0, 0, 0) and not b.g["free_power_recovery_metadata_corrupt"]
          and non_journal_ram(b) == non_journal_ram(legacy))
b = boot(with_journal(), fail_load={JKEY})
check("journal load FAILURE: invalid only, no corruption, nothing else differs",
      ram_journal(b) == (False, 0, 0, 0) and non_journal_ram(b) == non_journal_ram(legacy))
wrong = boot(BASE_NVS)
wrong.nvs_put_journal_bytes(JKEY, b"\x00" * 15)
wrong_nvs = dict(wrong.nvs)
b = boot(wrong_nvs)
check("wrong-size stored journal: invalid only, no corruption, nothing else differs",
      ram_journal(b) == (False, 0, 0, 0) and non_journal_ram(b) == non_journal_ram(legacy))
b = boot({**with_journal(mask=15, flags=1), DATA_KEY: SNAP})
check("a valid mask-15 + VERIFIED journal loads with its flag", ram_journal(b) == (True, 15, 1, BIND))
act = SNAP.copy()
act.active_persisted = 1
b = boot({**with_journal(), DATA_KEY: act})
check("binding ignores active_persisted at boot too (active lease -> restore_requested, journal still valid)",
      ram_journal(b)[0] is True and b.g["free_power_restore_requested"] is True)
ctx0 = SNAP.copy()
ctx0.reg244_lease_context_plus1 = 0
b = boot({**with_journal(binding=jm.journal_binding(ctx0)), DATA_KEY: ctx0})
check("lease context 'not captured' (plus-one 0 -> RAM -1) still round-trips into the binding",
      ram_journal(b)[0] is True and b.g["free_power_lease_context_reg244"] == -1)

# The journal is inert (NOT even loaded) unless the obligation is a trusted RESTORE_REQUIRED.
bad_ctx = SNAP.copy()
bad_ctx.reg244_lease_context_plus1 = 9
for label, nvs in (
    ("marker absent (CLEAR)", {JKEY: J(binding=BIND)}),
    ("marker CLEAR", {**with_journal(), VALID_KEY: ds.Record("ValidMarker", D.VALID_MARKER_MAGIC, D.MARKER_CLEAR)}),
    ("marker RESTORE_VERIFIED_PENDING_CLEAR", {**with_journal(), VALID_KEY: ds.Record(
        "ValidMarker", D.VALID_MARKER_MAGIC, D.MARKER_RESTORE_VERIFIED_PENDING_CLEAR)}),
    ("marker malformed", {**with_journal(), VALID_KEY: ds.Record("ValidMarker", 0x1234, 1)}),
    ("RESTORE_REQUIRED with unreadable snapshot data", {VALID_KEY: MARKER_REQ, JKEY: J(binding=BIND)}),
    ("RESTORE_REQUIRED with corrupt lease-context field", {**with_journal(binding=jm.journal_binding(bad_ctx)), DATA_KEY: bad_ctx}),
):
    b = boot(nvs)
    ref = boot({k: v for k, v in nvs.items() if k != JKEY})
    check(f"[{label}] journal not loaded, RAM journal invalid, boot otherwise identical to the no-journal boot",
          JKEY not in b.nvs_loads and ram_journal(b) == (False, 0, 0, 0) and non_journal_ram(b) == non_journal_ram(ref))

# Legacy behaviour: the SG-01 boot block changes nothing else, in any scenario.
without = fp_boot_block_without_journal(FW)
check("the journal boot block is a self-contained statement AFTER the Free Power retry-state load",
      JOURNAL_BOOT_MARK not in without and fp_boot_block(FW).index("FREE_POWER_RETRY_TAG")
      < fp_boot_block(FW).index(JOURNAL_BOOT_MARK))
scenarios = {
    "no records": {}, "required": BASE_NVS, "required+journal": with_journal(), "required+bad journal": with_journal(magic=0),
    "pending clear": {VALID_KEY: ds.Record("ValidMarker", D.VALID_MARKER_MAGIC, D.MARKER_RESTORE_VERIFIED_PENDING_CLEAR)},
    "malformed": {VALID_KEY: ds.Record("ValidMarker", 1, 7)}, "unreadable data": {VALID_KEY: MARKER_REQ},
    "active lease": {**with_journal(), DATA_KEY: act},
    "retry lockout": {**with_journal(), RETRY_KEY: ds.Record("FreePowerRetryState", 1)},
}
same = [label for label, nvs in scenarios.items()
        if non_journal_ram(boot(nvs)) == non_journal_ram(boot(nvs, block=without))]
check(f"[H] across {len(scenarios)} boot scenarios, every non-journal RAM global is identical with and without the "
      "SG-01 journal block (legacy restore/lockout inputs untouched)", same == list(scenarios), str(same))

# ===========================================================================
print("[10] No boot commit (L), static placement, no clear, no other consumer, START Modbus surface unchanged")
# ===========================================================================
boot_all = boot_text(FW)
check("[L] the whole on_boot lambda's CODE (comments/strings stripped) contains no commit_record at all",
      "commit_record" not in fpsim._strip_code(boot_all))
jb = journal_boot_block(FW)
check("[L] the boot journal block has exactly one load_record, no commit_record, no Modbus, no script execution",
      jb.count("ecco_durable::load_record(") == 1 and "commit_record" not in jb
      and not re.search(r"modbus|\.execute\(|script", jb))
check("[L] the boot journal block never assigns metadata_corrupt, snapshot_valid, marker or any restore input",
      not re.search(r"id\((free_power_recovery_metadata_corrupt|free_power_snapshot_valid|free_power_marker_state|"
                    r"free_power_restore_requested|free_power_active_persisted|free_power_operator_needed)\)\s*=(?!=)", jb))
check("[L] every boot scenario above performed zero durable commits",
      all(boot(nvs).nvs_commits == [] for nvs in scenarios.values()))

inits = re.findall(r"ecco_durable::FreePowerStartJournal journal\{\s*ecco_durable::FREE_POWER_START_JOURNAL_MAGIC, "
                   r"ecco_durable::(FREE_POWER_START_JOURNAL_MASK_B\d),\s*(0|ecco_durable::FREE_POWER_START_JOURNAL_FLAG_START_VERIFIED), "
                   r"0, ([^}]+)\}", FW_TEXT)
check("exactly 5 journal records are ever built for commit: B1, B2, B3, B4 (flags 0) and B4+VERIFIED, reserved literally 0",
      [(m, f.split("::")[-1]) for m, f, _b in inits] == [
          ("FREE_POWER_START_JOURNAL_MASK_B1", "0"), ("FREE_POWER_START_JOURNAL_MASK_B2", "0"),
          ("FREE_POWER_START_JOURNAL_MASK_B3", "0"), ("FREE_POWER_START_JOURNAL_MASK_B4", "0"),
          ("FREE_POWER_START_JOURNAL_MASK_B4", "FREE_POWER_START_JOURNAL_FLAG_START_VERIFIED")], str(inits))
check("the B1 record binds free_power_start_journal_binding(data) of the just-committed snapshot; B2-VERIFIED carry the RAM binding",
      [b.strip() for _m, _f, b in inits] == ["journal_binding"] + ["id(free_power_start_journal_binding)"] * 4
      and "uint64_t journal_binding = ecco_durable::free_power_start_journal_binding(data);" in FW_TEXT)
check("the journal is NEVER explicitly cleared: no mask-0 record, no zeroed record committed, no erase",
      "FreePowerStartJournal journal{}" not in re.sub(r"ecco_durable::FreePowerStartJournal journal\{\};\s*bool have_journal", "", FW_TEXT)
      and len(re.findall(r"commit_record\(\s*ecco_durable::key_for\(ecco_durable::FREE_POWER_START_JOURNAL_TAG\)", FW_TEXT)) == 5)
_, SCRIPTS = fpsim.load_scripts(FIRMWARE_PATH)
consumers = sorted(sid for sid in SCRIPTS if sid != "start_free_power_override"
                   and fpsim.mentions_journal(fpsim.script_body(FW_TEXT, sid)))
check("no other script (Force, Accept, Review, Dump, reg244, watchdog scripts...) references the journal - "
      "except the restore dispatch's SG-01 Phase 3 SELF_PARTIAL classifier",
      consumers == ["restore_free_power_snapshot_dispatch"], str(consumers))
_dispatch_journal_lambdas = [b for k, _g, b in fpsim.flatten(SCRIPTS["restore_free_power_snapshot_dispatch"]["then"])
                             if k == "lambda" and fpsim.mentions_journal(b)]
check("...and that consumer is ONE lambda that only READS the journal RAM mirror: no commit/load, no journal "
      "RAM assignment, no journal tag, no Modbus",
      len(_dispatch_journal_lambdas) == 1
      and not re.search(r"commit_record|load_record|FREE_POWER_START_JOURNAL_TAG|modbus|"
                        r"id\(free_power_start_journal_\w+\)\s*=(?!=)",
                        fpsim._strip_code(_dispatch_journal_lambdas[0]))
      and "FREE_POWER_START_JOURNAL_TAG" not in fpsim._strip_code(fpsim.script_body(FW_TEXT, "restore_free_power_snapshot_dispatch")))
intervals_text = "\n".join(str(iv) for iv in FW.get("interval", []))
check("no interval/watchdog references the journal", not fpsim.mentions_journal(intervals_text))
check("no on_boot code outside the journal block references the journal RAM/record",
      not fpsim.mentions_journal(boot_all.replace(jb, "")))
start_flat = fpsim.flatten(SCRIPTS["start_free_power_override"]["then"])
modbus_seq = [(k.split(".")[1], b["start_address"], b.get("count")) for k, _g, b in start_flat if k in (fpsim.READ, fpsim.WRITE)]
check("START's Modbus action sequence is unchanged by SG-01 (same reads/writes, same order, same addresses)",
      modbus_seq == [("read_holding_registers", 230, 3), ("read_holding_registers", 256, 24),
                     ("read_holding_registers", 244, 12), ("write_multiple_registers", 232, None),
                     ("write_multiple_registers", 230, None), ("write_multiple_registers", 268, None),
                     ("read_holding_registers", 268, 12), ("write_multiple_registers", 256, None),
                     ("read_holding_registers", 230, 3), ("read_holding_registers", 256, 24)], str(modbus_seq))
journal_lambdas = [b for k, _g, b in start_flat if k == "lambda" and fpsim.mentions_journal(b)]
check("no journal lambda touches Modbus (journal commits are NVS-only)",
      len(journal_lambdas) == 5 and all(not re.search(r"modbus|write_multiple|read_holding", fpsim._strip_code(b)) for b in journal_lambdas))
gates = {addr: g for _i, addr, g in fpsim.writes_in(start_flat)}
check("PR #45 gate semantics preserved: B2/B3 inside `!write_failed`, B4 inside `!write_failed && overlay_confirmed`",
      ("return !id(free_power_write_failed);", "then") in gates[230]
      and ("return !id(free_power_write_failed);", "then") in gates[268]
      and ("return !id(free_power_write_failed) && id(free_power_pre_power_overlay_confirmed);", "then") in gates[256])

# ===========================================================================
print("[11] Mutation sensitivity - each safety rule, broken on purpose, is detected")
# ===========================================================================


def fw_variant(mutate_tree=None, text_old=None, text_new=None):
    if text_old is not None:
        if FW_TEXT.count(text_old) != 1:
            raise AssertionError(f"mutation anchor not unique: {text_old[:60]!r}")
        return ds.load_firmware_text(FW_TEXT.replace(text_old, text_new))
    fw = copy.deepcopy(FW)
    mutate_tree(fw)
    return fw


def _find_list_with(actions, needle):
    for i, action in enumerate(actions or []):
        (kind, body), = action.items()
        if kind == "lambda" and needle in body:
            return actions, i
        if kind == "if":
            for branch in ("then", "else"):
                hit = _find_list_with(body.get(branch), needle)
                if hit:
                    return hit
    return None


def swap_b2_after_write(fw):
    lst, i = _find_list_with(fw["script"][[s["id"] for s in fw["script"]].index("start_free_power_override")]["then"],
                             "Could not durably commit the START journal (B2)")
    lst[i], lst[i + 1] = lst[i + 1], lst[i]


def adjacency_ok(sim):
    for idx, e in enumerate(sim.events):
        if e[0] == "write":
            prev = sim.events[idx - 1]
            if not (prev[0] == "commit" and prev[1] == JKEY and prev[3]):
                return False
    return True


m1 = fw_variant(swap_b2_after_write)
check("M1 [B2 journal commit moved AFTER the reg230 write] is detected by the commit-before-write check",
      adjacency_ok(run_start()) and not adjacency_ok(run_start(fw=m1)))
m2 = fw_variant(text_old='''                              id(free_power_write_failed) = true;
                              ESP_LOGE("free_power", "Could not durably commit the START journal (B3)''',
                text_new='''                              ESP_LOGE("free_power", "Could not durably commit the START journal (B3)''')
check("M2 [B3 journal failure does not set write_failed] is detected: 268-279 would be written after the failure",
      writes(run_start(fail_journal={3})) == [232, 230] and 268 in writes(run_start(fw=m2, fail_journal={3})))
m3 = fw_variant(text_old='''                              ESP_LOGE("free_power", "START journal is not at the B3 prefix - NOT overlaying TOU Power (256-261)");
                              return;
                            }
''', text_new='''                              ESP_LOGE("free_power", "START journal is not at the B3 prefix - NOT overlaying TOU Power (256-261)");
                              return;
                            }
                            id(free_power_start_journal_mask) = ecco_durable::FREE_POWER_START_JOURNAL_MASK_B4;
''')
s3 = run_start(fw=m3, fail_journal={4})
check("M3 [RAM mask advanced before the B4 durable commit] is detected: RAM 15 while durable stays 7",
      ram_journal(run_start(fail_journal={4}))[1] == 7 and ram_journal(s3)[1] == 15 and s3.nvs[JKEY].start_attempted == 7)
m4 = fw_variant(text_old='''                                          ESP_LOGW("free_power", "Could not durably record START_VERIFIED in the START journal - activation remains verified and active; only the journal's verified flag is unconfirmed");''',
                text_new='''                                          id(free_power_active_persisted) = false;
                                          id(free_power_write_failed) = true;''')
s4 = run_start(fw=m4, fail_journal={5})
check("M4 [START_VERIFIED treated as mandatory] is detected by the K checks",
      not (s4.g["free_power_active_persisted"] is True and not s4.g["free_power_write_failed"]))
m5 = fw_variant(text_old='''                ESP_LOGW("free_power", "No valid START journal for this obligation''',
                text_new='''                id(free_power_recovery_metadata_corrupt) = true;
                ESP_LOGW("free_power", "No valid START journal for this obligation''')
check("M5 [invalid boot journal sets metadata_corrupt] is detected by the G/H checks",
      not boot(with_journal(binding=BIND ^ 1)).g["free_power_recovery_metadata_corrupt"]
      and boot(with_journal(binding=BIND ^ 1), fw=m5).g["free_power_recovery_metadata_corrupt"])
m6 = fw_variant(text_old='''                id(free_power_start_journal_binding) = journal.binding;
''', text_new='''                id(free_power_start_journal_binding) = journal.binding;
                ecco_durable::commit_record(ecco_durable::key_for(ecco_durable::FREE_POWER_START_JOURNAL_TAG), journal);
''')
check("M6 [a durable commit added to the boot journal load] is detected by the L checks",
      boot(with_journal()).nvs_commits == [] and boot(with_journal(), fw=m6).nvs_commits != []
      and "commit_record" in boot_text(m6))
m7 = fw_variant(text_old='''                            id(free_power_write_failed) = true;
                            ESP_LOGE("free_power", "Could not durably commit the START journal (B1)''',
                text_new='''                            ESP_LOGE("free_power", "Could not durably commit the START journal (B1)''')
check("M7 [B1 journal failure does not block START] is detected by the C check (writes would follow)",
      writes(run_start(fail_journal={1})) == [] and writes(run_start(fw=m7, fail_journal={1})) != [])
m8 = fw_variant(text_old='''              bound.reg232 = id(free_power_snapshot_reg232);
''', text_new='''              bound.reg232 = id(free_power_snapshot_reg232) | 0x0001;
''')
check("M8 [boot binding computed from non-snapshot (intended) data] is detected: a genuine journal no longer validates",
      ram_journal(boot(with_journal()))[0] is True and ram_journal(boot(with_journal(), fw=m8))[0] is False)
m9 = fw_variant(text_old='''                            if (id(free_power_write_failed)) return;
                            if (!id(free_power_start_journal_valid) ||
                                id(free_power_start_journal_mask) != ecco_durable::FREE_POWER_START_JOURNAL_MASK_B1) {''',
                text_new='''                            if (!id(free_power_start_journal_valid) ||
                                id(free_power_start_journal_mask) != ecco_durable::FREE_POWER_START_JOURNAL_MASK_B1) {''')
s9 = run_start(fw=m9, write_outcomes={232: "error"})
check("M9 [B2 journal committed even after B1 failed] is detected: durable mask would claim B2 was eligible",
      run_start(write_outcomes={232: "error"}).nvs[JKEY].start_attempted == 1 and s9.nvs[JKEY].start_attempted != 1)

print("")
if FAILURES:
    print(f"FAILED: {len(FAILURES)} check(s)")
    for f in FAILURES:
        print(f"  - {f}")
    sys.exit(1)
print("All SG-01 Phase 1/2 START journal checks passed.")
