#!/usr/bin/env python3
"""SG-01 Phase 0 - test-harness support for the future Free Power START journal.

SCOPE: test infrastructure. This file proves the harness can model what SG-01
Phases 1/2 need. Phase 0 itself changed no firmware; since SG-01 Phase 1/2
landed, section [A] pins the resulting production baseline instead of the
journal's absence (the journal's own behaviour is covered by
registry/tests/test_sg01_journal_phase1_2.py; the SG-01 Phase 3/4
SELF_PARTIAL classifier by registry/tests/test_sg01_self_partial_phase3_4.py).

What Phase 0 added (all test-side):
  * registry/tests/_sg01_journal_model.py - the future 16-byte journal schema,
    tag, magic, valid masks, flag bit, classifier and the FNV-1a-64 binding
    mirror.
  * registry/tests/_dump_sim.py - a durable store that understands the Free
    Power / Register 244 records the header already defines AND the future
    journal record; commit-failure ("next N"), load-failure and raw-content
    injection.
  * registry/tests/_free_power_action_sim.py - a fail-closed guard: any
    lambda/condition/script mentioning the START journal raises instead of
    being silently skipped by LENIENT mode (since Phase 2, a top-level
    journal lambda can instead be EXECUTED against a durable store via
    simulate(journal_sim=...)).

Sections:
  [A] Baseline: production Modbus surface unchanged since main @ 6c62417;
      the SG-01 Phase 1/2 journal is present (tag, struct, 5 commits, 1
      load); SELF_PARTIAL (Phase 3/4) confined to the restore dispatch and
      its Python mirror; no new writer
  [B] _dump_sim durably models every existing Free Power / Reg244 record
  [C] Future journal record: schema, round trip, classification, failure
      and corrupt-content injection
  [D] Binding mirror: known-answer FNV, golden vectors, sensitivity
  [E] _free_power_action_sim fails closed on the journal; unrelated lenient
      behaviour is unchanged
"""

from __future__ import annotations

import ctypes
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
import _scope_chain as chain  # noqa: E402 - FB-T0: the [A] baseline pins are evaluated as of chain entry "dump_v2"

FAILURES: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  PASS  {name}")
    else:
        FAILURES.append(name)
        print(f"  FAIL  {name}" + (f" - {detail}" if detail else ""))


for required in (FIRMWARE_PATH, HEADER_PATH):
    if not required.is_file():
        print(f"  FAIL  required file not found: {required}")
        sys.exit(1)

FW_TEXT = FIRMWARE_PATH.read_text(encoding="utf-8")
HEADER = HEADER_PATH.read_text(encoding="utf-8")
FW = ds.load_firmware(FIRMWARE_PATH)
# FB-T0: the [A] production-baseline pins (Modbus op counts, durable call-site counts, referenced tags) are evaluated
# on the firmware AS OF chain entry "dump_v2" (main @ ca7474e): every LATER chain entry is undone by its exact-match
# reverter first (registry/tests/_scope_chain.py), so a later PR's declared deltas never re-hash these pins and an
# undeclared edit still breaks them. Today nothing follows "dump_v2": the texts are byte-for-byte the live ones.
SCOPE_FW_TEXT = chain.CHAIN.as_of(chain.FIRMWARE, "dump_v2", FW_TEXT)
SCOPE_FW = ds.load_firmware_text(SCOPE_FW_TEXT)


def new_sim() -> "ds.Sim":
    return ds.Sim(FW)


def raises(exc, fn) -> bool:
    try:
        fn()
    except exc:
        return True
    except Exception:  # noqa: BLE001 - a DIFFERENT exception is not the one under test
        return False
    return False


# ===========================================================================
print("[A] Production baseline: Modbus surface unchanged; SG-01 Phase 1/2 journal present; SELF_PARTIAL confined to the restore dispatch")
# ===========================================================================
SCRIPT_WRITES = {
    "write_inverter_rtc": 1, "start_free_power_override": 4, "restore_free_power_snapshot_dispatch": 4,
    "free_power_recovery_force_restore_dispatch": 4, "apply_manual_slot1": 5, "apply_manual_slot2": 5,
    "apply_manual_slot3": 5, "apply_manual_slot4": 5, "apply_manual_slot5": 5, "apply_manual_slot6": 6,
    "apply_reg244_settings": 1, "restore_reg244_snapshot": 1, "start_dump_to_grid_override": 2,
    "dump_controller_tick": 1, "restore_dump_to_grid_snapshot": 2, "dump_lockout_containment": 1,
}
_, SCRIPTS = fpsim.load_scripts(FIRMWARE_PATH)
def count_actions(node, key) -> int:
    if isinstance(node, dict):
        return sum((1 if k == key else 0) + count_actions(v, key) for k, v in node.items())
    if isinstance(node, list):
        return sum(count_actions(v, key) for v in node)
    return 0


measured_writes = {}
for sid, node in {s["id"]: s for s in SCOPE_FW["script"]}.items():
    w = count_actions(node["then"], fpsim.WRITE)
    if w:
        measured_writes[sid] = w
n_writes = count_actions(SCOPE_FW, fpsim.WRITE)  # whole document, not just scripts
n_reads = count_actions(SCOPE_FW, fpsim.READ)

check("Modbus write actions: exactly 52 (main @ 6c62417 - SG-02 containment write included)",
      n_writes == 52, str(n_writes))
check("Modbus read actions: exactly 60", n_reads == 60, str(n_reads))
check("the set of writing scripts and each one's write count is unchanged (no new Modbus writer)",
      measured_writes == SCRIPT_WRITES and sum(measured_writes.values()) == n_writes, str(measured_writes))

fw_commits = len(re.findall(r"ecco_durable::commit_record\s*\(", SCOPE_FW_TEXT))
fw_loads = len(re.findall(r"ecco_durable::load_record\s*\(", SCOPE_FW_TEXT))
fw_status_loads = len(re.findall(r"ecco_durable::load_record_status\s*\(", SCOPE_FW_TEXT))
fw_tags = sorted(set(re.findall(r"ecco_durable::([A-Za-z0-9_]+_TAG)\b", SCOPE_FW_TEXT)))
check("production commit_record call sites: exactly 57 (50 pre-SG-01 + 5 SG-01 START journal commits + Dump V2's "
      "2: the controller save-before-write evidence commit and the START V1 rollback tombstone)",
      fw_commits == 57, str(fw_commits))
check("production load call sites: exactly 10 (8 pre-SG-01 + 1 SG-01 boot journal load + 1 Dump V2 diagnostic "
      "legacy-V1 probe) - 7 load_record + SG-06's 3 marker load_record_status",
      (fw_loads, fw_status_loads) == (7, 3), f"{fw_loads}/{fw_status_loads}")
check("production durable tags referenced by the firmware: exactly the 8 pre-SG-01 tags + the journal tag",
      fw_tags == ["DUMP_TO_GRID_DATA_TAG", "DUMP_TO_GRID_RETRY_TAG", "DUMP_TO_GRID_VALID_TAG",
                  "FREE_POWER_DATA_TAG", "FREE_POWER_RETRY_TAG", "FREE_POWER_START_JOURNAL_TAG",
                  "FREE_POWER_VALID_TAG", "REG244_DATA_TAG", "REG244_VALID_TAG"], str(fw_tags))
hdr_current_tags = [t for t in re.findall(r"constexpr const char \*([A-Z0-9_]+_TAG(?:_V\d+)?) = ",
                                               chain.CHAIN.as_of(chain.DURABLE_HEADER, "dump_v2", HEADER))
                    if not re.search(r"_V\d+$", t)]
check("production header defines exactly the same 9 current tags", sorted(hdr_current_tags) == fw_tags,
      str(hdr_current_tags))

production_sources = {
    "firmware YAML": FW_TEXT,
    "ecco_durable_snapshot.h": HEADER,
    "ecco_recovery_evidence.h": EVIDENCE_HEADER_PATH.read_text(encoding="utf-8") if EVIDENCE_HEADER_PATH.is_file() else "",
}
reference_model_sources = {p.name: p.read_text(encoding="utf-8") for p in (ROOT / "registry").glob("*.py")}
# SG-01 Phase 3/4: SELF_PARTIAL exists ONLY as the restore dispatch's
# classifier (+ its RAM flag) and its Python mirror,
# registry/free_power_self_partial.py - never in a durable header (no new
# schema) and in no other script, interval or boot code.
SELF_PARTIAL_MODEL = "free_power_self_partial.py"
for label, text in production_sources.items():
    if label != "firmware YAML":
        check(f"{label}: no SELF_PARTIAL (no durable schema change)", not re.search(r"self_?partial", text, re.IGNORECASE))


def _code_strings(node):
    """Every string leaf of a YAML node (lambdas, conditions, handlers,
    write values...), comments stripped - so an explanatory comment never
    counts, and nothing nested can hide behind another string's comment."""
    if isinstance(node, dict):
        for v in node.values():
            yield from _code_strings(v)
    elif isinstance(node, list):
        for v in node:
            yield from _code_strings(v)
    elif isinstance(node, str):
        yield fpsim._strip_code(node)


def _mentions_self_partial(node) -> bool:
    return any(re.search(r"self_?partial", s, re.IGNORECASE) for s in _code_strings(node))


_sp_code_sites = sorted(sid for sid, node in SCRIPTS.items() if _mentions_self_partial(node["then"]))
check("firmware YAML: SELF_PARTIAL code appears only in restore_free_power_snapshot_dispatch",
      _sp_code_sites == ["restore_free_power_snapshot_dispatch"], str(_sp_code_sites))
check("firmware YAML: no interval, on_boot or other top-level component code references SELF_PARTIAL",
      not any(_mentions_self_partial(v) for k, v in FW.items() if k not in ("script", "globals") and not k.startswith("_")))
check("firmware YAML: the only SELF_PARTIAL global is the per-attempt free_power_live_self_partial flag",
      [g["id"] for g in FW["globals"] if re.search(r"self_?partial", g["id"], re.IGNORECASE)] == ["free_power_live_self_partial"])
for label, text in reference_model_sources.items():
    if label == SELF_PARTIAL_MODEL:
        continue
    check(f"{label}: no SELF_PARTIAL classifier behaviour", not re.search(r"self_?partial", text, re.IGNORECASE))
    check(f"{label}: the other Python reference models do not model the START journal",
          not re.search(r"start_?journal", text, re.IGNORECASE))
check(f"registry/{SELF_PARTIAL_MODEL} exists (the Phase 3 Python mirror)", SELF_PARTIAL_MODEL in reference_model_sources)
check("firmware YAML references the START journal tag (SG-01 Phase 2)",
      "ecco_durable::FREE_POWER_START_JOURNAL_TAG" in FW_TEXT)
check('production header defines FREE_POWER_START_JOURNAL_TAG = "ecco_free_power_start_journal_v1"',
      'constexpr const char *FREE_POWER_START_JOURNAL_TAG = "ecco_free_power_start_journal_v1";' in HEADER)
check("production header defines the 0x4543534A journal magic",
      "constexpr uint32_t FREE_POWER_START_JOURNAL_MAGIC = 0x4543534Au;" in HEADER)
header_journal = re.search(r"struct FreePowerStartJournal \{(.*?)\n\};", HEADER, re.S)
check("production header's FreePowerStartJournal has exactly the model's five fields, types and order",
      header_journal is not None
      and re.findall(r"\b(uint\d+_t) (\w+);", header_journal.group(1))
      == [("uint32_t", "magic"), ("uint8_t", "start_attempted"), ("uint8_t", "flags"), ("uint16_t", "reserved"),
          ("uint64_t", "binding")])
check("production header pins sizeof(FreePowerStartJournal) == 16 at compile time",
      "static_assert(sizeof(FreePowerStartJournal) == 16," in HEADER)

# ===========================================================================
print("[B] _dump_sim durably models every EXISTING Free Power / Register 244 record")
# ===========================================================================
header_tag_values = dict(re.findall(r'constexpr const char \*([A-Z0-9_]+_TAG(?:_V\d+)?) = "([^"]+)";', HEADER))
for _alias, _target in re.findall(r"constexpr const char \*([A-Z0-9_]+_TAG) = ([A-Z0-9_]+);", HEADER):
    header_tag_values[_alias] = header_tag_values[_target]  # e.g. FREE_POWER_DATA_TAG -> ..._V4
D = ds.Durable
for attr in ("FREE_POWER_DATA_TAG", "FREE_POWER_VALID_TAG", "FREE_POWER_RETRY_TAG", "REG244_DATA_TAG",
             "REG244_VALID_TAG", "DUMP_TO_GRID_DATA_TAG", "DUMP_TO_GRID_VALID_TAG", "DUMP_TO_GRID_RETRY_TAG"):
    check(f"sim {attr} equals the header's string", getattr(D, attr, None) == header_tag_values.get(attr),
          f"{getattr(D, attr, None)!r} vs {header_tag_values.get(attr)!r}")

header_structs = set(re.findall(r"^struct (\w+) \{", HEADER, re.M))
used_types = sorted(set(re.findall(r"ecco_durable::([A-Z][a-z][A-Za-z0-9]+)\b", FW_TEXT)) & header_structs)
check("the firmware uses all 8 header record types (6 pre-SG-01 + FreePowerStartJournal + Dump V2's retired "
      "DumpToGridSnapshotDataV1 layout, for the rollback tombstone)",
      used_types == ["DumpToGridRetryState", "DumpToGridSnapshotData", "DumpToGridSnapshotDataV1", "FreePowerRetryState",
                     "FreePowerSnapshotData", "FreePowerStartJournal", "Reg244SnapshotData", "ValidMarker"],
      str(used_types))
check("every header record type has a sim constructor AND a record kind",
      all(hasattr(D, s) and s in ds._RECORD_FIELDS for s in header_structs), str(sorted(header_structs)))
used_consts = sorted(set(re.findall(r"ecco_durable::([A-Z][A-Z0-9_]+)\b", FW_TEXT)))
check("every ecco_durable:: constant the firmware uses exists on the sim",
      all(hasattr(D, c) for c in used_consts), str([c for c in used_consts if not hasattr(D, c)]))

header_snapshot_fields = re.findall(
    r"\buint(?:8|16|32)_t (\w+);", re.search(r"struct FreePowerSnapshotData \{(.*?)\n\};", HEADER, re.S).group(1))
check("sim FreePowerSnapshotData has exactly the header's 26 fields in the header's order",
      ds._RECORD_FIELDS["FreePowerSnapshotData"] == header_snapshot_fields and len(header_snapshot_fields) == 26,
      str(header_snapshot_fields))
check("sim Reg244SnapshotData / FreePowerRetryState fields match the header",
      ds._RECORD_FIELDS["Reg244SnapshotData"] == ["value"]
      and ds._RECORD_FIELDS["FreePowerRetryState"] == ["operator_needed"])

sim = new_sim()
snap = sim.D.FreePowerSnapshotData()
for i, f in enumerate(ds._RECORD_FIELDS["FreePowerSnapshotData"]):
    setattr(snap, f, 100 + i)
key = sim.D.key_for(D.FREE_POWER_DATA_TAG)
check("Free Power snapshot data commits", sim.D.commit_record(key, snap) is True)
loaded = sim.D.FreePowerSnapshotData()
check("Free Power snapshot data loads back", sim.D.load_record(key, loaded) is True)
check("every one of the 26 Free Power snapshot fields round-trips",
      all(getattr(loaded, f) == getattr(snap, f) for f in ds._RECORD_FIELDS["FreePowerSnapshotData"]))
check("load into a different record TYPE under the same key fails (size mismatch analogue)",
      sim.D.load_record(key, sim.D.Reg244SnapshotData()) is False)
check("an unwritten Free Power tag loads as not-present",
      sim.D.load_record(sim.D.key_for(D.FREE_POWER_VALID_TAG), sim.D.ValidMarker()) is False)

marker = sim.D.ValidMarker(D.VALID_MARKER_MAGIC, D.MARKER_RESTORE_REQUIRED)
retry = sim.D.FreePowerRetryState(1)
reg244 = sim.D.Reg244SnapshotData(2)
check("Free Power validity marker / retry record / Reg244 snapshot all commit under their own tags",
      sim.D.commit_record(D.FREE_POWER_VALID_TAG, marker) and sim.D.commit_record(D.FREE_POWER_RETRY_TAG, retry)
      and sim.D.commit_record(D.REG244_DATA_TAG, reg244))
back_marker, back_retry, back_244 = sim.D.ValidMarker(), sim.D.FreePowerRetryState(), sim.D.Reg244SnapshotData()
check("...and each loads back independently (tags do not alias)",
      sim.D.load_record(D.FREE_POWER_VALID_TAG, back_marker) and back_marker.state == 1
      and sim.D.load_record(D.FREE_POWER_RETRY_TAG, back_retry) and back_retry.operator_needed == 1
      and sim.D.load_record(D.REG244_DATA_TAG, back_244) and back_244.value == 2)

# Failure injection against the EXISTING Free Power tags.
sim = new_sim()
sim.D.commit_record(D.FREE_POWER_RETRY_TAG, sim.D.FreePowerRetryState(0))
sim.nvs_fail_tags.add(D.FREE_POWER_RETRY_TAG)
check("commit failure (fail_tags) returns false", sim.D.commit_record(D.FREE_POWER_RETRY_TAG, sim.D.FreePowerRetryState(1)) is False)
check("a failed commit leaves the previously stored record untouched", sim.nvs[D.FREE_POWER_RETRY_TAG].operator_needed == 0)
check("a failed commit is still LOGGED as an attempt", len(sim.commits_for(D.FREE_POWER_RETRY_TAG)) == 2)
sim.nvs_fail_tags.clear()
sim.nvs_fail_next[D.FREE_POWER_DATA_TAG] = 2
outcomes = [sim.D.commit_record(D.FREE_POWER_DATA_TAG, sim.D.FreePowerSnapshotData()) for _ in range(3)]
check("nvs_fail_next fails exactly the next N commits for that key, then recovers", outcomes == [False, False, True], str(outcomes))
check("nvs_fail_next is per key (another tag is unaffected)", sim.D.commit_record(D.REG244_DATA_TAG, sim.D.Reg244SnapshotData(1)) is True)
sim.nvs_fail_all = True
check("nvs_fail_all fails every tag", sim.D.commit_record(D.FREE_POWER_VALID_TAG, marker) is False)
sim.nvs_fail_all = False
sim.nvs_fail_load_tags.add(D.FREE_POWER_RETRY_TAG)
probe = sim.D.FreePowerRetryState()
check("load failure (per tag) reports not-present even though the record exists",
      sim.D.load_record(D.FREE_POWER_RETRY_TAG, probe) is False and D.FREE_POWER_RETRY_TAG in sim.nvs)
check("...other tags still load", sim.D.load_record(D.REG244_DATA_TAG, sim.D.Reg244SnapshotData()) is True)
sim.nvs_fail_load_tags.clear()
sim.nvs_fail_load_all = True
check("load failure (global) fails every load", sim.D.load_record(D.REG244_DATA_TAG, sim.D.Reg244SnapshotData()) is False)
sim.nvs_fail_load_all = False
check("every load attempt is logged", len(sim.nvs_loads) >= 3)

# The REAL transpiled-lambda path (how firmware code reaches the store).
sim = new_sim()
sim.run_lambda(
    "ecco_durable::FreePowerRetryState retry{};\n"
    "retry.operator_needed = 1;\n"
    "ecco_durable::commit_record(ecco_durable::key_for(ecco_durable::FREE_POWER_RETRY_TAG), retry);"
)
check("a firmware-shaped lambda commits a FreePowerRetryState through the sim",
      sim.nvs[D.FREE_POWER_RETRY_TAG].operator_needed == 1)

# ===========================================================================
print("[C] SG-01 journal record model (mirror of the production record)")
# ===========================================================================
check("journal tag is ecco_free_power_start_journal_v1", jm.JOURNAL_TAG == "ecco_free_power_start_journal_v1")
check("sim exposes the tag and magic like the header would", D.FREE_POWER_START_JOURNAL_TAG == jm.JOURNAL_TAG
      and D.FREE_POWER_START_JOURNAL_MAGIC == 0x4543534A)
check("journal magic is 0x4543534A", jm.JOURNAL_MAGIC == 0x4543534A)
check("valid start_attempted masks are exactly 0, 1, 3, 7, 15", jm.JOURNAL_VALID_START_ATTEMPTED_MASKS == (0, 1, 3, 7, 15))
check("flag bit0 is START_VERIFIED and it is the only known flag",
      jm.JOURNAL_FLAG_START_VERIFIED == 0x01 and jm.JOURNAL_KNOWN_FLAGS == 0x01)
check("logical schema is 16 bytes (struct module)", jm.JOURNAL_SIZE == 16 and len(jm.pack_journal(new_sim().D.FreePowerStartJournal())) == 16)
check("logical schema is 16 bytes with NATIVE C layout (ctypes mirror)", ctypes.sizeof(jm.JournalC) == 16)
check("field offsets are magic@0 start_attempted@4 flags@5 reserved@6 binding@8",
      [getattr(jm.JournalC, f).offset for f in jm.JOURNAL_FIELDS] == [0, 4, 5, 6, 8])
check("sim record kind has exactly the five schema fields in order",
      ds._RECORD_FIELDS[jm.JOURNAL_KIND] == ["magic", "start_attempted", "flags", "reserved", "binding"])
check("a default-constructed journal is all zero, hence NOT valid (bad magic)",
      jm.classify_journal(new_sim().D.FreePowerStartJournal()) == jm.JOURNAL_BAD_MAGIC)

sim = new_sim()
jkey = sim.D.key_for(D.FREE_POWER_START_JOURNAL_TAG)
j = sim.D.FreePowerStartJournal(jm.JOURNAL_MAGIC, 7, 1, 0xBEEF, 0x0123456789ABCDEF)
check("journal commit succeeds", sim.D.commit_record(jkey, j) is True)
lj = sim.D.FreePowerStartJournal()
check("journal load succeeds", sim.D.load_record(jkey, lj) is True)
check("all five journal fields round-trip through commit/load",
      (lj.magic, lj.start_attempted, lj.flags, lj.reserved, lj.binding)
      == (jm.JOURNAL_MAGIC, 7, 1, 0xBEEF, 0x0123456789ABCDEF))
raw = sim.nvs_journal_bytes(jkey)
check("stored journal serialises to the 16-byte little-endian image",
      raw == bytes.fromhex("4a534345" "07" "01" "efbe" "efcdab8967452301"), raw.hex() if raw else "None")
check("pack/unpack round-trips", jm.unpack_journal(raw) == {"magic": jm.JOURNAL_MAGIC, "start_attempted": 7, "flags": 1,
                                                          "reserved": 0xBEEF, "binding": 0x0123456789ABCDEF})
check("unpack rejects a wrong-length image", raises(ValueError, lambda: jm.unpack_journal(raw + b"\0"))
      and raises(ValueError, lambda: jm.unpack_journal(raw[:-1])))
check("a stored journal does not alias the caller's object (commit copies)", (setattr(j, "start_attempted", 0) or True)
      and sim.nvs[jkey].start_attempted == 7)
check("missing journal (first boot) loads as not-present",
      new_sim().D.load_record(jkey, new_sim().D.FreePowerStartJournal()) is False)
check("a journal is not readable as a different record type", sim.D.load_record(jkey, sim.D.Reg244SnapshotData()) is False)

check("every valid start_attempted mask with flags 0, and mask 15 with START_VERIFIED, classifies ok",
      all(jm.classify_journal(sim.D.FreePowerStartJournal(jm.JOURNAL_MAGIC, m, 0, 0, 1)) == jm.JOURNAL_OK
          for m in (0, 1, 3, 7, 15))
      and jm.classify_journal(sim.D.FreePowerStartJournal(jm.JOURNAL_MAGIC, 15, 1, 0, 1)) == jm.JOURNAL_OK)
check("SG-01 Phase 1: START_VERIFIED with a partial mask (0/1/3/7) is rejected",
      all(jm.classify_journal(sim.D.FreePowerStartJournal(jm.JOURNAL_MAGIC, m, 1, 0, 1))
          == jm.JOURNAL_BAD_VERIFIED_PARTIAL for m in (0, 1, 3, 7)))
check("every non-prefix / out-of-range start_attempted value is rejected",
      all(jm.classify_journal(sim.D.FreePowerStartJournal(jm.JOURNAL_MAGIC, m, 0, 0, 1)) == jm.JOURNAL_BAD_START_ATTEMPTED
          for m in (2, 4, 5, 6, 8, 9, 10, 11, 12, 13, 14, 16, 31, 127, 255)))
check("every unknown flag bit (and any combination with a valid mask) is rejected",
      all(jm.classify_journal(sim.D.FreePowerStartJournal(jm.JOURNAL_MAGIC, 1, f, 0, 1)) == jm.JOURNAL_BAD_FLAGS
          for f in (0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80, 0x03, 0xFF, 0xFE)))
for bad_magic in (0, 0x4543534B, 0x4A534345, 0xFFFFFFFF, jm.JOURNAL_MAGIC ^ 1):
    check(f"bad magic {bad_magic:#010x} is flagged even though load_record() itself succeeds",
          (sim.nvs_put_journal_bytes(jkey, jm.pack_journal(sim.D.FreePowerStartJournal(bad_magic, 1, 0, 0, 5))) or True)
          and sim.D.load_record(jkey, lj) is True and jm.classify_journal(lj) == jm.JOURNAL_BAD_MAGIC)
check("bad magic wins over other defects (stable classification order)",
      jm.classify_journal(sim.D.FreePowerStartJournal(0, 2, 0xFF, 0, 0)) == jm.JOURNAL_BAD_MAGIC)
sim.nvs_put_journal_bytes(jkey, b"\x00" * 15)
check("a wrong-SIZE stored image (schema change / truncation) loads as not-present",
      sim.D.load_record(jkey, sim.D.FreePowerStartJournal()) is False)
sim.nvs_put_journal_bytes(jkey, b"\x00" * 17)
check("...in either direction", sim.D.load_record(jkey, sim.D.FreePowerStartJournal()) is False)
check("nvs_journal_bytes is None for an absent or non-journal entry", new_sim().nvs_journal_bytes(jkey) is None
      and sim.nvs_journal_bytes(jkey) is None)

# Failure injection on the journal tag.
sim = new_sim()
good = sim.D.FreePowerStartJournal(jm.JOURNAL_MAGIC, 0, 0, 0, 11)
sim.D.commit_record(jkey, good)
sim.nvs_fail_tags.add(jkey)
attempt = sim.D.FreePowerStartJournal(jm.JOURNAL_MAGIC, 1, 0, 0, 11)
check("journal commit failure (fail_tags) returns false", sim.D.commit_record(jkey, attempt) is False)
check("...leaving the last good journal intact (start_attempted still 0)", sim.nvs[jkey].start_attempted == 0)
check("...and the failed attempt is visible in the commit log (commit-before-write tests need this)",
      [r.start_attempted for r in sim.commits_for(jkey)] == [0, 1])
sim.nvs_fail_tags.clear()
sim.nvs_fail_next[jkey] = 1
check("journal nvs_fail_next: the failing commit returns false and leaves the last good journal (0) intact",
      sim.D.commit_record(jkey, attempt) is False and sim.nvs[jkey].start_attempted == 0)
check("...and the retry then succeeds", sim.D.commit_record(jkey, attempt) is True and sim.nvs[jkey].start_attempted == 1)
sim.nvs_fail_load_tags.add(jkey)
check("journal load failure injection reports not-present while the record exists",
      sim.D.load_record(jkey, sim.D.FreePowerStartJournal()) is False and jkey in sim.nvs)
sim.nvs_fail_load_tags.clear()
sim.nvs_fail_all = True
check("nvs_fail_all also fails journal commits", sim.D.commit_record(jkey, attempt) is False)
sim.nvs_fail_all = False

# Through the real transpiler: a firmware-shaped journal lambda.
sim = new_sim()
result = sim.run_lambda(
    "ecco_durable::FreePowerStartJournal j{ecco_durable::FREE_POWER_START_JOURNAL_MAGIC, 3, 1, 0, 0x0123456789ABCDEFULL};\n"
    "bool ok = ecco_durable::commit_record(ecco_durable::key_for(ecco_durable::FREE_POWER_START_JOURNAL_TAG), j);\n"
    "ecco_durable::FreePowerStartJournal back{};\n"
    "bool loaded = ecco_durable::load_record(ecco_durable::key_for(ecco_durable::FREE_POWER_START_JOURNAL_TAG), back);\n"
    "return ok && loaded && back.magic == ecco_durable::FREE_POWER_START_JOURNAL_MAGIC && back.start_attempted == 3;"
)
check("a firmware-shaped lambda commits AND reloads the journal through the transpiler", result is True, repr(result))
check("...and the commit is recorded under the journal tag", len(sim.commits_for(jkey)) == 1
      and sim.nvs[jkey].binding == 0x0123456789ABCDEF)

# ===========================================================================
print("[D] Journal binding mirror (FNV-1a-64)")
# ===========================================================================
check("FNV-1a-64 known answer: empty string", jm.fnv1a_64(b"") == 0xCBF29CE484222325)
check("FNV-1a-64 known answer: 'a'", jm.fnv1a_64(b"a") == 0xAF63DC4C8601EC8C)
check("FNV-1a-64 known answer: 'foobar'", jm.fnv1a_64(b"foobar") == 0x85944171F73967E8)

# Independently written reference: field order spelled out LITERALLY here so
# a reordering in the module cannot silently agree with itself.
ORDER = (["end_epoch"] + ["reg230", "reg232"] + ["reg256", "reg257", "reg258", "reg259", "reg260", "reg261"]
         + ["reg268", "reg269", "reg270", "reg271", "reg272", "reg273", "reg274", "reg275", "reg276", "reg277",
            "reg278", "reg279"] + ["reg230_intended", "reg_tou_power_intended", "reg244_lease_context_plus1"])


def reference_binding(s: dict) -> int:
    data = bytearray(b"ECCO-FP-START-JOURNAL-v1")
    data += (s["end_epoch"] & 0xFFFFFFFF).to_bytes(4, "little")
    for name in ORDER[1:]:
        data += (s[name] & 0xFFFF).to_bytes(2, "little")
    h = 14695981039346656037
    for byte in data:
        h = ((h ^ byte) * 1099511628211) % (1 << 64)
    return h


check("module field order equals the literal order in this test", jm.BINDING_FIELDS == ORDER)
check("binding covers 24 fields: end_epoch + 23 uint16 (reg230, reg232, 256-261, 268-279, 3 intended/context)",
      len(jm.BINDING_FIELDS) == 24 and len(jm.BINDING_U16_FIELDS) == 23)
check("hashed image is 24 (domain) + 4 + 46 = 74 bytes", len(jm.binding_input_bytes(jm.blank_snapshot())) == 74)
check("domain is the 24 ASCII bytes ECCO-FP-START-JOURNAL-v1, no terminator",
      jm.BINDING_DOMAIN == b"ECCO-FP-START-JOURNAL-v1" and len(jm.BINDING_DOMAIN) == 24)
check("excluded fields are exactly active_persisted and restore_requested",
      jm.BINDING_EXCLUDED_FIELDS == ("active_persisted", "restore_requested")
      and not set(jm.BINDING_EXCLUDED_FIELDS) & set(jm.BINDING_FIELDS))

GOLDEN_ZERO = jm.blank_snapshot()
GOLDEN_TYPICAL = jm.blank_snapshot(
    end_epoch=1790003600, reg230=0x0002, reg232=0x0140,
    reg256=1000, reg257=1100, reg258=1200, reg259=1300, reg260=1400, reg261=1500,
    reg268=50, reg269=60, reg270=70, reg271=80, reg272=90, reg273=100,
    reg274=0x0102, reg275=0x0102, reg276=0x0102, reg277=0x0102, reg278=0x0102, reg279=0x0102,
    reg230_intended=0x0006, reg_tou_power_intended=4000, reg244_lease_context_plus1=3,
    active_persisted=1, restore_requested=0)
GOLDEN_MAX = {f: 0xFFFF for f in jm.BINDING_U16_FIELDS}
GOLDEN_MAX["end_epoch"] = 0xFFFFFFFF
for label, vec, expected in (("all-zero snapshot", GOLDEN_ZERO, 0x9752C546FF6459E7),
                             ("typical Free Power snapshot", GOLDEN_TYPICAL, 0x2B4C46D4D207B486),
                             ("all-ones snapshot", GOLDEN_MAX, 0x9FFACD2E50744DAD)):
    check(f"golden vector - {label}: {expected:#018x}", jm.journal_binding(vec) == expected,
          f"{jm.journal_binding(vec):#018x}")
    check(f"golden vector - {label}: agrees with the independently written reference",
          reference_binding(vec) == expected)
check("binding is deterministic across calls", jm.journal_binding(GOLDEN_TYPICAL) == jm.journal_binding(dict(GOLDEN_TYPICAL)))
check("domain separation: hashing the same bytes WITHOUT the domain differs",
      jm.fnv1a_64(jm.binding_input_bytes(GOLDEN_TYPICAL)[len(jm.BINDING_DOMAIN):]) != jm.journal_binding(GOLDEN_TYPICAL))

base = jm.journal_binding(GOLDEN_TYPICAL)
seen = {base}
for name in jm.BINDING_FIELDS:
    mutated = dict(GOLDEN_TYPICAL)
    mutated[name] = (mutated[name] + 1) & (0xFFFFFFFF if name == "end_epoch" else 0xFFFF)
    b = jm.journal_binding(mutated)
    check(f"changing bound field {name} alters the binding", b != base)
    check(f"...and matches the reference for that mutation", b == reference_binding(mutated))
    seen.add(b)
check("all 24 single-field mutations give 24 distinct bindings", len(seen) == 25)

check("changing active_persisted does NOT alter the binding",
      jm.journal_binding({**GOLDEN_TYPICAL, "active_persisted": 0}) == base
      and jm.journal_binding({**GOLDEN_TYPICAL, "active_persisted": 255}) == base)
check("changing restore_requested does NOT alter the binding",
      jm.journal_binding({**GOLDEN_TYPICAL, "restore_requested": 1}) == base
      and jm.journal_binding({**GOLDEN_TYPICAL, "restore_requested": 255}) == base)
check("the binding needs no lifecycle flags at all (helper accepts a snapshot without them)",
      jm.journal_binding({k: v for k, v in GOLDEN_TYPICAL.items() if k not in jm.BINDING_EXCLUDED_FIELDS}) == base)

swapped = dict(GOLDEN_TYPICAL, reg230=GOLDEN_TYPICAL["reg232"], reg232=GOLDEN_TYPICAL["reg230"])
check("field ORDER matters: swapping the values of reg230 and reg232 changes the binding",
      jm.journal_binding(swapped) != base)
swapped_slots = dict(GOLDEN_TYPICAL, reg256=GOLDEN_TYPICAL["reg261"], reg261=GOLDEN_TYPICAL["reg256"])
check("field ORDER matters: reversing the ends of 256..261 changes the binding", jm.journal_binding(swapped_slots) != base)
check("u16 values are little-endian: 0x0102 != 0x0201", jm.journal_binding({**GOLDEN_ZERO, "reg230": 0x0102})
      != jm.journal_binding({**GOLDEN_ZERO, "reg230": 0x0201}))
check("end_epoch is a full u32 (upper bytes participate)",
      jm.journal_binding({**GOLDEN_ZERO, "end_epoch": 0x01000000}) != jm.journal_binding({**GOLDEN_ZERO, "end_epoch": 0}))
check("a value that does not fit a uint16 is rejected, not silently truncated",
      raises(ValueError, lambda: jm.journal_binding({**GOLDEN_ZERO, "reg230": 0x10000}))
      and raises(ValueError, lambda: jm.journal_binding({**GOLDEN_ZERO, "reg268": -1})))

snap_rec = new_sim().D.FreePowerSnapshotData()
for f, v in GOLDEN_TYPICAL.items():
    setattr(snap_rec, f, v)
check("the binding accepts the sim's FreePowerSnapshotData record directly and agrees with the dict form",
      jm.journal_binding(snap_rec) == base)
snap_rec.active_persisted, snap_rec.restore_requested = 0, 1
check("...flipping the record's lifecycle flags still does not alter it", jm.journal_binding(snap_rec) == base)

# ===========================================================================
print("[E] _free_power_action_sim fails CLOSED on the START journal (unless a durable store executes it)")
# ===========================================================================
COMMIT_JOURNAL = (
    "ecco_durable::commit_record(ecco_durable::key_for(ecco_durable::FREE_POWER_START_JOURNAL_TAG), journal);"
)
COMMIT_RETRY = "ecco_durable::commit_record(ecco_durable::key_for(ecco_durable::FREE_POWER_RETRY_TAG), retry);"

# Baseline (pre-existing) behaviour - a DURABLE statement that is not the
# journal is still skipped and recorded, exactly as before Phase 0.
st = {"a": False}
skipped = fpsim.exec_lambda(COMMIT_RETRY + "\nid(a) = true;", st, lenient=True)
check("UNCHANGED: a non-journal durable commit is still skipped-and-recorded in lenient mode",
      len(skipped) == 1 and "FREE_POWER_RETRY_TAG" in skipped[0] and st["a"] is True, str(skipped))

# The new guard.
for label, code in (
    ("bare journal commit statement", COMMIT_JOURNAL + "\nid(a) = true;"),
    ("journal commit assigned to a global", "id(a) = " + COMMIT_JOURNAL.rstrip(";") + ";"),
    ("journal commit captured in a local bool", "bool ok = " + COMMIT_JOURNAL.rstrip(";") + ";\nid(a) = ok;"),
    ("journal commit inside an if block", "if (id(a)) {\n" + COMMIT_JOURNAL + "\n}"),
    ("journal struct declaration", "ecco_durable::FreePowerStartJournal journal{};"),
    ("journal tag as a string literal", 'const char *t = "ecco_free_power_start_journal_v1";'),
    ("a journal RAM global", "id(fp_start_journal_committed) = true;"),
    ("upper-case spelling", "id(a) = FREE_POWER_START_JOURNAL_VERIFIED;"),
):
    st = {"a": False}
    check(f"lenient mode RAISES on: {label}", raises(fpsim.JournalNotModelled, lambda c=code, s=st: fpsim.exec_lambda(c, s, lenient=True)))
    check(f"strict mode RAISES on: {label}", raises(fpsim.JournalNotModelled, lambda c=code, s=dict(st): fpsim.exec_lambda(c, s)))
check("JournalNotModelled is an UnsupportedLambda (existing handlers of that type still catch it)",
      issubclass(fpsim.JournalNotModelled, fpsim.UnsupportedLambda))
check("the journal statement is NOT recorded in a skipped list - it never reaches one", raises(
    fpsim.JournalNotModelled, lambda: fpsim.exec_lambda(COMMIT_JOURNAL, {}, lenient=True)))
check("the guard is not defeated by whitespace or a preceding comment on the same statement",
      raises(fpsim.JournalNotModelled, lambda: fpsim.exec_lambda("// x\n  ecco_durable :: commit_record ( key_for(START_JOURNAL_TAG) , j ) ;", {}, lenient=True)))
check("a firmware COMMENT that merely mentions the journal does not trip the guard",
      fpsim.exec_lambda("// SG-01 START_JOURNAL is committed before B1\n/* start_journal */ id(a) = true;", {"a": False}, lenient=True) is not None)
check("guard applies to a write-values lambda",
      raises(fpsim.JournalNotModelled, lambda: fpsim.eval_write_values("uint16_t v = id(start_journal_v);\nreturn std::vector<uint16_t>{v};", {"start_journal_v": 1})))
check("guard applies to a condition lambda",
      raises(fpsim.JournalNotModelled, lambda: fpsim.eval_condition("return !id(fp_start_journal_pending);", {"fp_start_journal_pending": False})))
check("a normal condition is unaffected", fpsim.eval_condition("return !id(a);", {"a": False}) is True)

WRITE, READ = fpsim.WRITE, fpsim.READ


def tree_with(lambda_code: str) -> list:
    return [
        {"lambda": "id(a) = true;"},
        {"lambda": lambda_code},
        {WRITE: {"start_address": 230, "values": "return std::vector<uint16_t>{1};", "on_response": {"then": []}}},
    ]


def run_tree(actions):
    return fpsim.simulate(actions, {230: "ok"}, {}, {230: 0}, {"a": False})


bank, state, attempted, _v, skipped_l = run_tree(tree_with(COMMIT_RETRY))
check("UNCHANGED: simulate() over a tree with a non-journal durable commit still runs and reaches the write",
      attempted and attempted[0][:2] == ("write", 230) and bank[230] == 1 and len(skipped_l) == 1, str(skipped_l))
check("simulate() RAISES when a top-level lambda action commits the journal (instead of skipping it and writing)",
      raises(fpsim.JournalNotModelled, lambda: run_tree(tree_with(COMMIT_JOURNAL))))
# The journal lambda precedes the write in the tree: the raise must happen
# there, so the write (and its bank mutation) is never simulated.
_probe_bank = {230: 0}
_raised = False
try:
    fpsim.simulate(tree_with(COMMIT_JOURNAL), {230: "ok"}, {}, _probe_bank, {"a": False})
except fpsim.JournalNotModelled:
    _raised = True
check("...and the caller's bank is untouched (the write after the journal statement never ran)",
      _raised and _probe_bank == {230: 0})
check("simulate() RAISES on a script.execute of a journal script",
      raises(fpsim.JournalNotModelled, lambda: fpsim.simulate([{"script.execute": {"id": "commit_start_journal"}}], {}, {}, {}, {})))
check("simulate() RAISES on an if: whose condition mentions the journal",
      raises(fpsim.JournalNotModelled, lambda: fpsim.simulate(
          [{"if": {"condition": {"lambda": "return !id(fp_start_journal_ok);"}, "then": []}}], {}, {}, {}, {"fp_start_journal_ok": True})))
check("simulate() RAISES on a journal statement inside a write's on_response handler",
      raises(fpsim.JournalNotModelled, lambda: fpsim.simulate(
          [{WRITE: {"start_address": 230, "values": "return std::vector<uint16_t>{1};",
                    "on_response": {"then": [{"lambda": COMMIT_JOURNAL}]}}}], {230: "ok"}, {}, {230: 0}, {})))

# The real firmware: the guard changes no parse result for any lambda that
# does NOT mention the journal - every such lambda parses identically to the
# pre-Phase-0 path (strip -> _parse_ops) - and it DOES refuse every real
# lambda that mentions the journal (SG-01 Phase 2), in both modes.
# FB-B1 (D14): the real firmware now ALSO carries lambdas that name the Fallback Profile code (the Review scripts). The FB-B0 guard
# (fpsim.FallbackNotModelled) refuses those in strict AND lenient mode by design - they are simulated only by FbbSim - so they
# cannot be part of the "guard changes no parse outcome" comparison. Exactly like the journal lambdas they are split off and
# proven separately: every one of them IS refused (never skipped), and none lives in a pre-existing script.
n_lambdas = n_same = 0
n_journal = n_journal_refused = 0
n_fb = n_fb_refused = 0
fb_scripts: set[str] = set()


def _outcome(fn):
    """Comparable summary of a parse: the op kinds + skipped statements, or
    the exception type + message (compiled code objects are not comparable)."""
    try:
        ops, skipped = fn()
        return ("ok", [op[0] for op in ops], list(skipped))
    except Exception as e:  # noqa: BLE001 - some pre-existing lambdas raise SyntaxError; compare it too
        return ("raises", type(e).__name__, str(e))


for sid, node in SCRIPTS.items():
    for kind, _gates, body in fpsim.flatten(node["then"]):
        if kind != "lambda":
            continue
        if fpsim.mentions_journal(body):
            for lenient in (False, True):
                n_journal += 1
                if raises(fpsim.JournalNotModelled, lambda: fpsim._ops_for(body, lenient=lenient)):
                    n_journal_refused += 1
            continue
        if fpsim.mentions_fallback(body):
            fb_scripts.add(sid)
            for lenient in (False, True):
                n_fb += 1
                if raises(fpsim.FallbackNotModelled, lambda: fpsim._ops_for(body, lenient=lenient)):
                    n_fb_refused += 1
            continue
        for lenient in (False, True):
            n_lambdas += 1
            pre = _outcome(lambda: fpsim._parse_ops(fpsim._strip_code(body), lenient=lenient))
            post = _outcome(lambda: fpsim._ops_for(body, lenient=lenient))
            if pre == post:
                n_same += 1
check(f"guard changes no parse outcome for any of the real firmware's {n_lambdas} non-journal (lambda x mode) parses",
      n_lambdas > 100 and n_same == n_lambdas, f"{n_same}/{n_lambdas}")
check(f"guard refuses every one of the {n_journal} real journal (lambda x mode) parses - never skipped",
      n_journal > 0 and n_journal_refused == n_journal, f"{n_journal_refused}/{n_journal}")
# FB-B1 (D14): the FB-B0 guard stays proven against the REAL firmware, with FallbackNotModelled specifically (not any exception).
_PRE_FB_SCRIPT_IDS = {s["id"] for s in ds.load_firmware_text(chain.CHAIN.as_of(chain.FIRMWARE, "fbb0", FW_TEXT))["script"]}
check(f"guard refuses every one of the {n_fb} real Fallback Profile (lambda x mode) parses with FallbackNotModelled - never skipped "
      "(strict AND lenient)", n_fb > 0 and n_fb_refused == n_fb, f"{n_fb_refused}/{n_fb}")
check("every real lambda that names the Fallback Profile code sits in a script chain entries added AFTER fbb0 (no pre-existing script "
      "mentions it, so the 'guard changes no parse outcome' comparison above still covers every pre-existing lambda)",
      bool(fb_scripts) and not fb_scripts & _PRE_FB_SCRIPT_IDS, str(sorted(fb_scripts & _PRE_FB_SCRIPT_IDS)))
guard_hits = [sid for sid, node in SCRIPTS.items()
              for kind, _g, body in fpsim.flatten(node["then"])
              if kind == "lambda" and fpsim.JOURNAL_GUARD_PATTERN.search(fpsim._without_comments(body))]
check("the real firmware lambda ACTIONS that mention the journal are exactly START's five "
      "(entry RAM reset, B1 commit, B2/B3/B4 commits) plus the restore dispatch's ONE SELF_PARTIAL "
      "classifier (SG-01 Phase 3) - no other script touches it",
      guard_hits == ["start_free_power_override"] * 5 + ["restore_free_power_snapshot_dispatch"], str(guard_hits))

print("")
if FAILURES:
    print(f"FAILED: {len(FAILURES)} check(s)")
    for f in FAILURES:
        print(f"  - {f}")
    sys.exit(1)
print("All SG-01 Phase 0 harness checks passed.")
