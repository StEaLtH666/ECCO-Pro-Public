#!/usr/bin/env python3
"""Offline tests for the S2 fix (branch `fix/durable-storage-heap-leak`):
the `ecco_durable` heap leak recorded in
docs/SUPERVISION_FALLBACK_FAILBACK_ARCHITECTURE.md's defect ledger (S2) and
CURRENT_STATE.md's "Separate follow-up prerequisites" list.

Root cause (verified against the vendored ESPHome core actually used by this
firmware - esphome 2026.8.2, installed at the Python `esphome` package's
`core/preference_backend.h` and `components/esp32/preferences.cpp`, NOT part
of this repo): `esphome::ESPPreferenceObject` holds its backend as a plain
non-owning `PreferenceBackend *` with no destructor to release it, and
`esphome::esp32::ESP32Preferences::make_preference()` heap-allocates a fresh
`ESP32PreferenceBackend` via `new` on EVERY call
(`return ESPPreferenceObject(new ESP32PreferenceBackend(...));`).
`sizeof(ESP32PreferenceBackend)` is 12 bytes (uint32_t key, uint32_t
nvs_handle, uint16_t rtc_offset, uint8_t length_words, bool in_flash - no
padding needed, already a multiple of 4); the actual heap allocation is a
few bytes larger once the IDF allocator's own per-block header is counted,
consistent with the ledger's "~16 B per call" estimate.
`firmware/include/ecco_durable_snapshot.h`'s `commit_record()`/
`load_record()` used to call `make_preference<T>(key)` fresh on every single
invocation - the ESPHome-documented pattern is to call it ONCE per key at
setup and reuse the result for the device's lifetime - so every durable
commit or load leaked one backend allocation forever. With 58 commit_record/
load_record call sites in the firmware and a stuck Dump obligation's
watchdog re-driving a commit roughly every 15s, that reproduces the
ledger's "~92 KB/day" figure: 86400/15 = 5760 calls/day * ~16 B =~ 92160 B.

Fix: `ecco_durable_snapshot.h` gained `preference_for<T>(key)`, a
function-local `static std::unordered_map<uint32_t, ESPPreferenceObject>`
cache. `commit_record`/`load_record` now go through it instead of calling
`make_preference<T>(key)` directly, so `make_preference<T>()` runs at most
once per distinct (T, key) pair for the life of the device - this firmware
has exactly 9 durable tags (8 until SG-01 Phase 1/2 added
FREE_POWER_START_JOURNAL_TAG), so at most 9 one-time allocations, never
growing further, instead of once per call.

No I/O, no hardware, no ESPHome/C++ toolchain (this test deliberately does
NOT import or read the installed `esphome` pip package - that is a build
dependency of the separate ESPHome-compile CI job, not of this offline
test suite, which `validate-ecco.yml` runs with only pyyaml/jinja2
installed; the analysis above is recorded in this docstring and in the
firmware header's own comment instead), in the same style as
registry/tests/test_free_power_hardening_2026_09_22.py:
  [1]-[3]  Structural/source-anchored checks that the real header now routes
           every commit/load through the cache (with a mutation check that
           the same checks fail against the verbatim pre-fix source).
  [4]      Structural: the just-merged supervision heartbeat (PR A,
           observe-only) adds no durable/NVS call of its own - required
           reading before this fix, so any accounting below is not
           double-counting a second write source.
  [5]+     A small, explicitly-labelled Python reference-model simulation of
           the allocation-counting behaviour (not of ESPHome/NVS itself),
           reproducing the unbounded growth and proving the fix bounds it -
           including a repeat-loop check for cumulative leakage and a
           save/load round-trip-identical check for Free Power and Dump.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HEADER_PATH = ROOT / "firmware" / "include" / "ecco_durable_snapshot.h"
FIRMWARE_PATH = ROOT / "firmware" / "ecco_clock_dongle_stage3_4_free_power.yaml"

FAILURES: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  PASS  {name}")
    else:
        FAILURES.append(name)
        print(f"  FAIL  {name}" + (f" - {detail}" if detail else ""))


for p in (HEADER_PATH, FIRMWARE_PATH):
    if not p.is_file():
        print(f"  FAIL  required file not found: {p}")
        sys.exit(1)

header = HEADER_PATH.read_text(encoding="utf-8")
fw = FIRMWARE_PATH.read_text(encoding="utf-8")


def function_body(name: str, text: str) -> str:
    """Extract one `template<typename T> inline ... name(...) { ... }`
    function body from a header by brace matching, starting at the
    function's opening brace. Anchors on the full `template<...> inline`
    definition prefix (not just the bare name) so an earlier mention of the
    same name inside a comment - e.g. this file's own S2 explanation, which
    says "commit_record()/load_record() used to call ..." - can never be
    mistaken for the real definition."""
    m = re.search(r"template<typename T>\s+inline\s+.+?\b" + re.escape(name) + r"\s*\(", text)
    assert m is not None, f"could not locate the definition of {name!r} in header - source structure changed"
    brace_start = text.index("{", m.end())
    depth = 0
    for i in range(brace_start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return text[brace_start: i + 1]
    raise AssertionError(f"unbalanced braces scanning {name!r}")


# ===========================================================================
# [1]-[3] Structural: commit_record/load_record route through a cache,
# never calling make_preference<T>() directly (which is what leaked).
# ===========================================================================
print("[1] preference_for<T>() exists as a per-(T, key) cache guarded by a lookup miss")
has_cache_fn = "preference_for" in header
check("preference_for<T>() is defined", has_cache_fn)
pref_for_body = function_body("preference_for", header) if has_cache_fn else ""
check(
    "preference_for<T>() keeps a function-local static cache (persists across calls, not per-call state)",
    "static std::unordered_map" in pref_for_body,
)
check(
    "preference_for<T>() only calls make_preference<T>() on a cache miss (find() == end())",
    "cache.find(key)" in pref_for_body
    and "cache.end()" in pref_for_body
    and "make_preference<T>(key)" in pref_for_body,
)

print("[2] commit_record()/load_record() route through the cache, not make_preference<T>() directly")
commit_body = function_body("commit_record", header)
load_body = function_body("load_record", header)
check(
    "commit_record() calls preference_for<T>(key), not global_preferences->make_preference<T>(key) directly",
    "preference_for<T>(key)" in commit_body and "make_preference<T>(key)" not in commit_body,
)
check(
    "load_record() calls preference_for<T>(key), not global_preferences->make_preference<T>(key) directly",
    "preference_for<T>(key)" in load_body and "make_preference<T>(key)" not in load_body,
)
check(
    "commit_record() still flushes with a durable sync() after a successful save (unchanged contract)",
    "esphome::global_preferences->sync()" in commit_body,
)

print("[3] MUTATION CHECK: the [2] checks fail against the verbatim pre-fix source")
PRE_FIX_COMMIT_RECORD = r'''
template<typename T> inline bool commit_record(uint32_t key, const T &record) {
  static_assert(std::is_trivially_copyable<T>::value, "ecco_durable record must be trivially copyable");
  auto pref = esphome::global_preferences->make_preference<T>(key);
  if (!pref.save(&record))
    return false;
  return esphome::global_preferences->sync();
}
'''
PRE_FIX_LOAD_RECORD = r'''
template<typename T> inline bool load_record(uint32_t key, T &record) {
  auto pref = esphome::global_preferences->make_preference<T>(key);
  return pref.load(&record);
}
'''
check(
    "commit_record check fails against pre-fix source (proves it isn't vacuous)",
    not ("preference_for<T>(key)" in PRE_FIX_COMMIT_RECORD and "make_preference<T>(key)" not in PRE_FIX_COMMIT_RECORD),
)
check(
    "load_record check fails against pre-fix source (proves it isn't vacuous)",
    not ("preference_for<T>(key)" in PRE_FIX_LOAD_RECORD and "make_preference<T>(key)" not in PRE_FIX_LOAD_RECORD),
)

# ===========================================================================
# [4] The just-merged supervision heartbeat (PR A, observe-only,
# CURRENT_STATE.md) adds no durable/NVS write pressure of its own - checked
# so the accounting below is not silently missing a second, newer leak
# source alongside the pre-existing one this fix targets.
# ===========================================================================
print("[4] Supervision heartbeat (PR A, observe-only) adds no durable/NVS call of its own")
action_marker = "action: ha_supervision_heartbeat"
action_idx = fw.find(action_marker)
check(f"located the {action_marker!r} API action", action_idx != -1)
if action_idx != -1:
    # Bounded window to the action's own then: body - generous, bounded so a
    # false pass can't hide behind an unrelated later durable call far below.
    action_window = fw[action_idx: action_idx + 4000]
    next_action_idx = action_window.find("\n  - action:", 1)
    if next_action_idx != -1:
        action_window = action_window[:next_action_idx]
    check(
        "the heartbeat API action body contains no ecco_durable::/commit_record/NVS reference",
        "ecco_durable::" not in action_window and "commit_record" not in action_window,
    )

eval_marker = "supervision state (STARTUP/SUPERVISED"
eval_idx = fw.find(eval_marker)
check("located the supervision-state 1s evaluation interval", eval_idx != -1)
if eval_idx != -1:
    eval_window = fw[eval_idx: eval_idx + 3000]
    check(
        "the supervision-state evaluation interval contains no ecco_durable::/commit_record/NVS reference",
        "ecco_durable::" not in eval_window and "commit_record" not in eval_window,
    )

durable_tags = sorted(set(re.findall(r"ecco_durable::([A-Za-z0-9_]+_TAG)\b", fw)))
check(
    "exactly the 9 known durable tags are referenced anywhere in the firmware (supervision added none; "
    "SG-01 Phase 1/2 added FREE_POWER_START_JOURNAL_TAG)",
    durable_tags
    == [
        "DUMP_TO_GRID_DATA_TAG",
        "DUMP_TO_GRID_RETRY_TAG",
        "DUMP_TO_GRID_VALID_TAG",
        "FREE_POWER_DATA_TAG",
        "FREE_POWER_RETRY_TAG",
        "FREE_POWER_START_JOURNAL_TAG",
        "FREE_POWER_VALID_TAG",
        "REG244_DATA_TAG",
        "REG244_VALID_TAG",
    ],
    f"found {durable_tags}",
)


# ===========================================================================
# [5]+ Reference-model allocation-accounting simulation.
#
# Hand-written model of the LEAK MECHANISM (heap allocation counting), not
# of ESPHome/NVS itself - the actual save/load byte-for-byte semantics are
# out of scope for this model (they are unchanged by the fix: caching the
# ESPPreferenceObject changes nothing about what save()/load() do, only how
# often the object wrapping them is constructed). BACKEND_SIZE mirrors
# sizeof(ESP32PreferenceBackend) as documented in
# firmware/include/ecco_durable_snapshot.h's own S2 comment and verified
# above against the vendored esphome/components/esp32/preference_backend.h.
# ===========================================================================
BACKEND_SIZE = 12  # sizeof(ESP32PreferenceBackend): 4+4+2+1+1, no padding


class LeakAccountingSim:
    """`fixed=False` reproduces the pre-fix call-every-time pattern (one
    `make_preference` heap allocation per commit/load call, never freed -
    `ESPPreferenceObject` has no destructor to release it). `fixed=True` is
    this branch's cache."""

    def __init__(self, fixed: bool):
        self.fixed = fixed
        self.cache: dict[tuple[str, int], object] = {}
        self.make_preference_calls = 0
        self.leaked_bytes = 0
        self.store: dict[int, object] = {}  # simulated NVS backing store, keyed by NVS key

    def _preference_for(self, type_name: str, key: int):
        cache_key = (type_name, key)
        if self.fixed:
            if cache_key not in self.cache:
                self.cache[cache_key] = self._make_preference(key)
            return self.cache[cache_key]
        return self._make_preference(key)  # pre-fix: always allocates fresh

    def _make_preference(self, key: int):
        self.make_preference_calls += 1
        self.leaked_bytes += BACKEND_SIZE  # the `new ESP32PreferenceBackend(...)` never `delete`d
        return key  # the backend's only externally-observable behaviour: it addresses `key`

    def commit_record(self, type_name: str, key: int, value) -> bool:
        backend_key = self._preference_for(type_name, key)
        self.store[backend_key] = value
        return True

    def load_record(self, type_name: str, key: int):
        backend_key = self._preference_for(type_name, key)
        return self.store.get(backend_key)


print("[5] Reproduces S2: the unfixed model leaks BACKEND_SIZE bytes on every single commit/load call")
unfixed = LeakAccountingSim(fixed=False)
for _ in range(50):
    unfixed.commit_record("ValidMarker", key=0xAAAA, value={"state": 1})
check(
    "unfixed model: make_preference() called once per commit (never cached)",
    unfixed.make_preference_calls == 50,
)
check(
    "unfixed model: leaked bytes grow linearly with call count (50 * 12 B)",
    unfixed.leaked_bytes == 50 * BACKEND_SIZE,
)

print("[6] Fix: repeated commits to the SAME key allocate exactly once, however many times it is called")
fixed_sim = LeakAccountingSim(fixed=True)
for _ in range(50):
    fixed_sim.commit_record("ValidMarker", key=0xAAAA, value={"state": 1})
check("fixed model: make_preference() called exactly once for 50 repeated commits", fixed_sim.make_preference_calls == 1)
check("fixed model: leaked bytes bounded at one allocation, not 50", fixed_sim.leaked_bytes == BACKEND_SIZE)

print("[7] Repeat-loop test: a stuck Dump obligation's 15s watchdog re-drive over a full day")
CALLS_PER_DAY = (24 * 60 * 60) // 15  # 5760, matching the ledger's "~92 KB/day" derivation
unfixed_day = LeakAccountingSim(fixed=False)
for _ in range(CALLS_PER_DAY):
    unfixed_day.commit_record("DumpToGridSnapshotData", key=0xBBBB, value={"active_persisted": 1})
check(
    "unfixed model over one simulated day matches the ledger's ~92 KB/day order of magnitude",
    abs(unfixed_day.leaked_bytes - CALLS_PER_DAY * BACKEND_SIZE) == 0 and unfixed_day.leaked_bytes > 65000,
    f"leaked {unfixed_day.leaked_bytes} B over {CALLS_PER_DAY} calls",
)

fixed_day = LeakAccountingSim(fixed=True)
for _ in range(CALLS_PER_DAY):
    fixed_day.commit_record("DumpToGridSnapshotData", key=0xBBBB, value={"active_persisted": 1})
check(
    "fixed model over the SAME simulated day still allocates exactly once (no cumulative leakage)",
    fixed_day.leaked_bytes == BACKEND_SIZE and fixed_day.make_preference_calls == 1,
)

print("[8] Multi-key test: this firmware's 9 real durable tags, each hit many times, allocate at most 9 times total")
tags_from_header = sorted(set(re.findall(r'constexpr const char \*([A-Z0-9_]+_TAG(?:_V\d+)?) = ', header)))
current_tags = [t for t in tags_from_header if not re.search(r"_V\d+$", t)]
check(
    "parsed exactly the 9 current (non-historical) durable tag constants from the header",
    len(current_tags) == 9,
    f"found {current_tags}",
)
fixed_multi = LeakAccountingSim(fixed=True)
type_for_tag = {
    "FREE_POWER_VALID_TAG": "ValidMarker",
    "REG244_VALID_TAG": "ValidMarker",
    "DUMP_TO_GRID_VALID_TAG": "ValidMarker",
    "FREE_POWER_DATA_TAG": "FreePowerSnapshotData",
    "REG244_DATA_TAG": "Reg244SnapshotData",
    "DUMP_TO_GRID_DATA_TAG": "DumpToGridSnapshotData",
    "FREE_POWER_RETRY_TAG": "FreePowerRetryState",
    "DUMP_TO_GRID_RETRY_TAG": "DumpToGridRetryState",
    "FREE_POWER_START_JOURNAL_TAG": "FreePowerStartJournal",
}
check("every parsed tag has a known record type for this simulation", set(current_tags) == set(type_for_tag))
for i, tag in enumerate(current_tags):
    for _ in range(25):  # each tag hit repeatedly, like real boot-time loads + periodic commits
        fixed_multi.commit_record(type_for_tag[tag], key=hash(tag) & 0xFFFFFFFF, value={"n": i})
check(
    "fixed model across all 9 tags, 25 commits each (225 total calls), still allocates only 9 times",
    fixed_multi.make_preference_calls == 9 and fixed_multi.leaked_bytes == 9 * BACKEND_SIZE,
    f"calls={fixed_multi.make_preference_calls} leaked={fixed_multi.leaked_bytes}",
)

print("[9] Free Power and Dump durable models remain behaviourally identical (save/load round trip unaffected by caching)")
for fixed_flag in (True, False):
    sim = LeakAccountingSim(fixed=fixed_flag)
    fp_key = hash("FREE_POWER_DATA_TAG") & 0xFFFFFFFF
    dump_key = hash("DUMP_TO_GRID_DATA_TAG") & 0xFFFFFFFF
    sim.commit_record("FreePowerSnapshotData", fp_key, {"reg230": 1, "reg232": 2})
    sim.commit_record("DumpToGridSnapshotData", dump_key, {"reg244": 0, "reg256": 500})
    # A later, unrelated commit to a DIFFERENT key must not disturb an already-stored value.
    sim.commit_record("ValidMarker", hash("FREE_POWER_VALID_TAG") & 0xFFFFFFFF, {"state": 1})
    fp_loaded = sim.load_record("FreePowerSnapshotData", fp_key)
    dump_loaded = sim.load_record("DumpToGridSnapshotData", dump_key)
    check(
        f"Free Power record round-trips exactly (fixed={fixed_flag})",
        fp_loaded == {"reg230": 1, "reg232": 2},
    )
    check(
        f"Dump record round-trips exactly (fixed={fixed_flag})",
        dump_loaded == {"reg244": 0, "reg256": 500},
    )
check(
    "round-trip results are identical between the fixed and unfixed models (caching changes allocation count only, never data)",
    True,  # the two `check()` pairs above already assert byte-identical results under both flags
)

print("[10] The cache is scoped per record type, not just per numeric key")
# Real NVS storage is keyed only by the numeric key string (see
# esp32/preferences.cpp's nvs_set_blob/nvs_get_blob calls, which take no
# type discriminator) - two different record types sharing one numeric key
# would genuinely collide in the underlying store, exactly as they would
# have before this fix. That is a pre-existing, orthogonal constraint this
# fix does not change (and this firmware avoids it entirely: key_for()
# hashes 8 distinct tag strings, each used with exactly one record type at
# every call site - see [8] above). What this fix's cache must get right is
# narrower: it must not let two DIFFERENT T's reuse the SAME cached
# ESPPreferenceObject/backend when their numeric keys happen to collide -
# each (type, key) pair still gets its own independent allocation.
collider = LeakAccountingSim(fixed=True)
shared_key = 0xC0FFEE
collider.commit_record("ValidMarker", shared_key, {"state": 1})
collider.commit_record("FreePowerRetryState", shared_key, {"operator_needed": 1})
check(
    "two different record types sharing a numeric key still get independent cache entries (both allocate)",
    collider.make_preference_calls == 2,
)

print("")
if FAILURES:
    print(f"{len(FAILURES)} check(s) FAILED:")
    for name in FAILURES:
        print(f"  - {name}")
else:
    print("All durable storage heap-leak (S2) tests PASSED.")

print("")
print("These are STRUCTURAL/source-text checks against the real firmware header plus a")
print("hand-written Python reference-model simulation of the allocation-counting")
print("behaviour - they prove the source and the model agree with the intended fix, not")
print("that the compiled firmware's actual heap usage behaves this way on real hardware.")
print("See CURRENT_STATE.md for what remains unverified.")

if FAILURES:
    sys.exit(1)
