"""Cumulative change-scope chain (FB-T0).

WHY. Older suites (SG-01 Phase 0/3-4/5, SG-06, PR-A supervision, Manual TOU
Phase 1, Dump V2, FB-A) each prove "nothing outside my change sites moved" by
pinning a pre-existing artifact byte-for-byte (sha256), or by pinning a count
measured on it. Every later PR necessarily edits some of those artifacts.
Re-hashing the pins would "silently widen what they accept" and is FORBIDDEN
(see _sg06_scope.py). The technique used so far is a per-feature *exact-match
reverter*: the current text with exactly that feature's edits undone, which
must reproduce the feature's base byte-for-byte. Chaining those reverters by
hand inside every older suite costs O(N^2) test edits.

THE CHAIN. One ordered list of ENTRIES, in MERGE order on main, one per PR that
edits a pinned artifact or that older pins must be told about:

    root (main @ 004040b) -> fba (#54) -> mtou1 (#53) -> dump_v2 (#52) -> fbc1 (#57) -> fbb0 (FB-B0) -> fbb1 (FB-B1) -> fbb2 (FB-B2) -> fbb3 (FB-B3) -> fbc2 (FB-C2) -> fbc3 (FB-C3) -> fbd1 (FB-D1) -> lic0 (v0.9.0 licence alignment)
    [-> pub0 (the public-export sanitisation: in CHAIN only in the exported tree; see PUB0 below and _pub0_scope.py)
     -> pex0 -> dtgp1 (configurable Dump-to-Grid ceiling) -> ... (the POST-EXPORT EDIT LAYER, schema ecco-pex/1: declared changes made ON the
        export; POST_EXPORT_ENTRIES, _pex.py)]

Each entry carries
  * `reverts`     exact-match reverters, one per edited artifact (each raises
                  AssertionError unless every edit it undoes is present exactly
                  the expected number of times - so any OTHER change still
                  breaks the pins that use it);
  * `checkpoints` the sha256 of each edited artifact right AFTER the PR (the
                  content of that merge commit on main, verifiable with
                  `git show <commit>:<path>`); an entry that edits nothing has
                  no reverters and no checkpoints and inherits the previous
                  state;
  * declared deltas: the measured change in every counted quantity (scripts,
                  globals, Modbus reads/writes, durable call sites ...), the
                  Modbus paths whose op list changed, added `esphome.includes`,
                  added substitutions, and the files allowed to carry the FB-A
                  banned tokens / to include the FB-A header.

`as_of(path, entry_id, live_text)` undoes every entry NEWER than `entry_id`,
newest first, and returns the artifact exactly as it was right after that PR.
An older suite calls `as_of(..., "<its own anchor>")` ONCE and keeps every
pin it already had, unchanged; later PRs never touch it again. test_scope_chain
proves, for every entry, that as_of() reproduces the recorded checkpoint, that
the declared deltas equal the measured differences between consecutive states,
and that live == root + the sum of every declared delta.

ADDING A PR (FB-C1, FB-B0, ...). Append ONE `Entry` at the END of ENTRIES:
  1. write that PR's exact-match reverters (before/after text pairs, generated
     from the real diff and verified by round trip, as _sg06_scope /
     _dump_v2_scope do) in its own `_<name>_scope.py`;
  2. `reverts={FIRMWARE: <fn>, ...}` for each pinned artifact it edits, and
     `checkpoints={FIRMWARE: <sha256 after the PR>, ...}`;
  3. declare its deltas (only non-zero metrics), `op_paths_changed`,
     `includes_added`, `subst_added` ({key: EXACT value}; `subst_changed` / `subst_removed` for edits to existing
     ones), `fbh_includers`, `banned_fw_added`, `banned_files`, `added_files`, `tags_declared` (the EXACT durable tag
     strings its added headers declare) and `tags_promoted`;
  4. do NOT edit any older suite - their anchors are fixed entry ids.
     (Recorded exception, FB-B1 / D14: four older suites carry minimal, commented edits - see the fbb1 Entry.
     Recorded exception, FB-B2: a short list of older pins is narrowed to the new exact truth, each edit commented
     `FB-B2:` (the D8 ones `FB-B2 (D8):`) - see the fbb2 Entry and test_fallback_save_scope.py [6].)
An edit that is not declared, or a declaration the measurement contradicts,
fails test_scope_chain.py. No older suite is re-hashed, ever.

ADDING A POST-EXPORT CHANGE (the public tree; PEX, registry/tests/_pex.py). The public tree IS the pub0 export: its 57 pub0 targets
are frozen at pub0's result hashes (registry/tests/fixtures/pub0_manifest.json), and ENTRIES above are closed. A change made on the
export is ONE Entry appended at the END of POST_EXPORT_ENTRIES (merge order on the public main), after pub0:
  1. its exact-match reverters in its own `_<id>_scope.py` (generated from the real diff, verified by round trip): `reverts` /
     `checkpoints` for the chain-pinned artifacts it edits (exactly as above), and `frozen_reverts` / `frozen_checkpoints` for the
     frozen files it edits (_pex.FROZEN: the pub0 targets that are not chain-pinned, plus _pex.ENROLLED). Every frozen reverter
     exposes its exact (before, after) pairs as `.edits`;
  2. its declared deltas etc., as above (test_scope_chain measures the chain-pinned ones);
  3. its `fingerprint`: _pex.fingerprint() of the entry, which hashes its parent's fingerprint (pub0's manifest fingerprint for the
     first) - so an older entry can never be rewritten without changing every later one;
  4. an older suite that pins the pub0-era state of a file the entry edits reads it through _pex.as_of_pub0() (a declared,
     commented `PEX` edit, counted by test_pex_transition.py's ledger); live safety invariants keep reading the live file.
test_pex_transition.py proves every post-export entry (exactness, checkpoints, live == newest, privacy, the deny-list, the
fingerprint links, the ledger); test_pub0_transition.py proves the pub0 export on the files AS OF pub0.

No I/O except reading repo files and a TemporaryDirectory for analyzer runs.
"""

from __future__ import annotations

import hashlib
import re
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Mapping

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
for _p in (str(HERE), str(REPO / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import _dtgp1_scope as _dtgp1  # noqa: E402
import _dump_v2_scope as _dv2  # noqa: E402
import _esb1_scope as _esb1  # noqa: E402
import _fba_scope as _fba  # noqa: E402
import _fbb1_scope as _fbb1  # noqa: E402
import _fbb2_scope as _fbb2  # noqa: E402
import _fbb3_scope as _fbb3  # noqa: E402
import _fbb_scope as _fbb  # noqa: E402
import _fbc2_scope as _fbc2  # noqa: E402
import _fbc3_scope as _fbc3  # noqa: E402
import _fbd1_scope as _fbd1  # noqa: E402
import _fbc_scope as _fbc  # noqa: E402
import _fbrp1_scope as _fbrp1  # noqa: E402
import _lic0_scope as _lic0  # noqa: E402
import _mtou1_scope as _mtou1  # noqa: E402
import _pex0_scope as _pex0  # noqa: E402
import _pub0_scope as _pub0  # noqa: E402
import _rtcf1_scope as _rtcf1  # noqa: E402
import _tag_inventory as _tags  # noqa: E402

FIRMWARE = "firmware/ecco_clock_dongle_stage3_4_free_power.yaml"
DURABLE_HEADER = "firmware/include/ecco_durable_snapshot.h"
EVIDENCE_HEADER = "firmware/include/ecco_recovery_evidence.h"
CAPABILITIES = "registry/inverter_capabilities.yaml"
STATE_MACHINE = "registry/transaction_state_machine.py"
HA_MANIFEST = "deployment/ha-manifest.yaml"
# Every artifact an entry may declare edits to (and that has a root hash).
PINNED = (FIRMWARE, DURABLE_HEADER, EVIDENCE_HEADER, CAPABILITIES, STATE_MACHINE, HA_MANIFEST)

ROOT_ID = "root"
ROOT_COMMIT = "004040b91b8fb94b783a6fbd40cae610c3316e08"
# sha256 (LF text, as Path.read_text returns it) of each pinned artifact on
# main @ 004040b. `git show 004040b:<path> | sha256sum`.
ROOT_SHA = {
    FIRMWARE: "934ba7ddd6806592b64d7cc63795aa0ee372238d2eaa314612565e2639cdd4d5",
    DURABLE_HEADER: "36c764bce649755c0865aad09f3669d56c64cef2bfd5edbd9252c9c735cfff01",
    EVIDENCE_HEADER: "c9b9b1d670ce8ef8ec33c5c1208326abd0213f042e8a69b1115b4ea85620875e",
    CAPABILITIES: "ea9a0bc97d6cbc593898631d3a20d85887e12a1839ec2dda651611287e68bf32",
    STATE_MACHINE: "50d1d54792403a0c41069c4f88c6144707aa93bacdd240dbf749128c99ceb4ce",
    HA_MANIFEST: "d582beb6b3873109365c9d901f3c9dfe6c26033e7c11551814179c953412815f",
}

# Counted quantities. Every Entry.deltas key must be one of these; a missing key
# means 0.
METRICS = (
    "scripts", "globals", "api_actions", "intervals", "sensors", "binary_sensors", "text_sensors",
    "switches", "buttons", "numbers", "selects",
    "commit_record", "load_record", "load_record_status",   # ecco_durable:: call sites in the firmware
    "modbus_writes", "modbus_reads",                         # analyzer ops
    "substitutions", "includes",                             # firmware YAML
    "durable_tag_strings",                                   # *_TAG declarations in the durable header
    "banned_fw",                                             # FB-A banned tokens in the firmware YAML
)

# The tokens FB-A reserved for itself; see test_fallback_profile_schema.py [9].
BANNED = re.compile(r"ecco_fallback|FALLBACK_PROFILE|FAILBACK_STATE|ecco_failback")

Reverter = Callable[[str], str]


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def read_live(rel: str) -> str:
    return (REPO / rel).read_text(encoding="utf-8")


@dataclass(frozen=True)
class Entry:
    id: str
    pr: str
    commit: str                                  # main @ this merge: the state `checkpoints` describe
    reverts: Mapping[str, Reverter] = field(default_factory=dict)
    checkpoints: Mapping[str, str] = field(default_factory=dict)
    deltas: Mapping[str, int] = field(default_factory=dict)
    op_paths_changed: frozenset = frozenset()    # analyzer path names added or whose op list changed
    includes_added: tuple = ()                   # esphome.includes entries added (in order, appended)
    subst_added: Mapping[str, str] = field(default_factory=dict)   # substitution key -> EXACT value added
    subst_changed: Mapping[str, tuple] = field(default_factory=dict)  # existing key -> (old value, new value) changed
    subst_removed: tuple = ()                    # existing substitution keys removed
    fbh_includers: frozenset = frozenset()       # files that include the FB-A header (or name it in a YAML includes list)
    banned_fw_added: int = 0                     # FB-A banned-token occurrences added to the firmware YAML
    banned_files: frozenset = frozenset()        # home-assistant/ frontend/ deployment/ files allowed to carry them
    added_files: frozenset = frozenset()         # repo files the PR adds (not hashed; firmware/include/*.h entries are
                                                 # excluded from the pre-existing tag inventory, see declared_added_files)
    tags_declared: frozenset = frozenset()       # EXACT set of durable tag strings the headers this PR adds declare
                                                 # (any declaration style: see _tag_inventory.py)
    tags_promoted: frozenset = frozenset()       # subset of tags_declared that FB-A's model lists as PROSPECTIVE and this
                                                 # PR now declares for real (so they are not counted twice)
    note: str = ""
    # PEX (post-export entries only, _pex.py): exact-match reverters and the sha256 right AFTER the entry of each FROZEN file it edits
    # (a pub0 target that is not chain-pinned, or a _pex.ENROLLED file), and the entry's fingerprint (_pex.fingerprint: it hashes the
    # parent entry's fingerprint, so the post-export entries form one hash-linked, append-only sequence).
    frozen_reverts: Mapping[str, Reverter] = field(default_factory=dict)
    frozen_checkpoints: Mapping[str, str] = field(default_factory=dict)
    fingerprint: str = ""


# ---------------------------------------------------------------------------
# The chain, in MERGE order on main. APPEND new entries at the end.
# ---------------------------------------------------------------------------
ENTRIES: tuple[Entry, ...] = (
    Entry(
        id="fba", pr="#54", commit="97450aa",
        # FB-A edited NONE of the pinned artifacts: no reverters, no checkpoints.
        fbh_includers=_fba.HEADER_INCLUDERS,
        added_files=_fba.ADDED_FILES,
        note="fallback profile schema v1 - behaviour-free; adds a header, its Python model and two suites",
    ),
    Entry(
        id="mtou1", pr="#53", commit="37f9958",
        reverts={FIRMWARE: _mtou1.pre_mtou1_text},
        checkpoints={FIRMWARE: "943856c4ca46f652b34dffdb331955e8aac0d011e21cc23fac35b56b8f9c944e"},
        deltas={"globals": 2, "intervals": 1},
        note="Manual TOU Phase 1 ownership gates: six apply scripts, seven Load buttons, 2 RAM globals, 1 RAM-only interval",
    ),
    Entry(
        id="dump_v2", pr="#52", commit="ca7474e",
        reverts={FIRMWARE: _dv2.pre_dump_v2_firmware, DURABLE_HEADER: _dv2.pre_dump_v2_header},
        checkpoints={
            FIRMWARE: "9d09152744250623ec2f4e3e206a928f1251fb0b1dcf7b3ae1a858c5ae4ec314",
            DURABLE_HEADER: "d57cd3b5b951b97e45872be4485c63beec58f604db08ef33fb660b8251e871af",
        },
        deltas={"globals": 2, "commit_record": 2, "load_record": 1, "durable_tag_strings": 1},
        note="Dump V2 durable ownership evidence: three Dump scripts, on_boot, 2 RAM globals, durable header",
    ),
    Entry(
        # Not merged yet: the checkpoint is the firmware content this branch adds, which a merge leaves unchanged.
        id="fbc1", pr="FB-C1", commit="unmerged",
        reverts={FIRMWARE: _fbc.pre_fbc1_text},
        checkpoints={FIRMWARE: "dd9bc59890d6d514c8e60f6a6c6a48615192429f414df2c244c26b9d9950d6d3"},
        # Zero Modbus reads/writes, zero commit/load/status sites, zero durable tags, zero op paths, no include:
        # all measured by test_scope_chain.py / test_failback_shadow_core.py [S], none declared.
        deltas={"globals": 42, "intervals": 1, "text_sensors": 5, "substitutions": 5},
        subst_added={
            "ecco_failback_shadow_episode_close_ms": "300000",
            "ecco_failback_shadow_start_max_ms": "30000",
            "ecco_failback_shadow_assumed_reboot_timeout_ms": "900000",
            "ecco_failback_shadow_publish_min_ms": "10000",
            "ecco_failback_shadow_soak_publish_min_ms": "60000",
        },
        banned_fw_added=14,                      # 5 substitution keys + 9 ${ecco_failback_shadow_*} uses in the interval
        added_files=_fbc.ADDED_FILES,
        note="Failback Shadow instrumentation: RAM-only, zero-authority observer - 5 substitutions, 42 RAM globals, "
             "5 diagnostic text sensors, 1 RAM-only 1s interval; no Modbus, durable, NVS, script or control change",
    ),
    Entry(
        # Not merged yet: the checkpoint is the firmware content this branch produces, which a merge leaves unchanged.
        # FB-B0 was prepared on b3fcdfc (before FB-T0 / FB-C1); its reverter edits only the esphome: block, so it commutes
        # with fbc1's and, applied to the live firmware, reproduces fbc1's checkpoint (dd9bc598...) byte for byte.
        id="fbb0", pr="FB-B0", commit="unmerged",
        reverts={FIRMWARE: _fbb.pre_fbb0_firmware},
        checkpoints={FIRMWARE: "a61709c3fe42a8da60e16652891888988d96254be9f37e844ab665543d8c5881"},
        # The esphome: block only (min_version 2026.4.0 -> 2026.8.2 is not a counted quantity). Zero Modbus reads/writes,
        # zero commit/load/status sites, zero durable-header tag strings (the new tag lives in FB-B0's OWN header, see
        # tags_declared), zero op paths, zero entities / scripts / globals / intervals: measured, not declared.
        deltas={"includes": 4},
        includes_added=_fbb.ADDED_INCLUDES,
        # The ONLY files that include the FB-A header after FB-B0: the firmware YAML (its includes: list) and the model header.
        fbh_includers=frozenset(_fbb.FBA_INCLUDERS),
        banned_fw_added=4,                       # exactly the four `- include/ecco_fallback*` lines; no lambda, entity or substitution
        added_files=frozenset(_fbb.ADDED_FILES),
        # The FBW witness tag: FB-A reserved it as PROSPECTIVE (same exact string, same preference key); FB-B0 declares it.
        tags_declared=frozenset({"ecco_failback_provision_v1"}),
        tags_promoted=frozenset({"ecco_failback_provision_v1"}),
        note="Fallback durable foundation: witness-first direct NVS primitive compiled in via 4 esphome includes "
             "(min_version 2026.8.2), ZERO call sites, no runtime NVS write, no Modbus, no entity / script change",
    ),
    Entry(
        # Not merged yet: the checkpoints are the content this branch produces, which a merge leaves unchanged.
        # FB-B1 = the read-only "Review Current Configuration". It edits the firmware YAML in thirteen places (ten pure
        # insertions, three reworded operator texts; _fbb1_scope.HUNKS) and the deployment manifest in one (a frontend_assets
        # stanza). Its reverter applies to the live text FIRST (newest first), so fbb0's include-list reverter then sees the
        # include list ending in ecco_fallback_durable.h exactly as before. The new interval sits between the FP evidence-expiry
        # interval and FB-C1's, never last (the Manual TOU tick must stay the last interval).
        # Four OLDER suites could not be chain-scoped and carry minimal, commented FB-B1 / D14 edits (each keeps its assertions):
        # test_sg06_boot_durable_read_fail_closed (SG-06's exact reverter now gets the as-of-dump_v2 boot lambda),
        # test_fallback_durable_model (include-dir listing is chain-relative), test_sg01_phase0_harness (the FB lambdas are split
        # off the 'guard changes no parse' sweep and proven refused separately) and test_fallback_durable_harness ([6] FbbSim).
        id="fbb1", pr="FB-B1", commit="unmerged",
        reverts={FIRMWARE: _fbb1.pre_fbb1_firmware, HA_MANIFEST: _fbb1.pre_fbb1_manifest},
        checkpoints={
            FIRMWARE: "aa0d9f5286f8613d20957af1b561134007bfc69d8b50f0528295548b6e0d24de",
            HA_MANIFEST: "d15d8fd2781e43585ddb8829f5af4cfa34e3e8b0b62e67d37fd5656b398bb832",
        },
        # Zero Modbus WRITES, zero commit/load/status sites (the boot read goes through the direct primitive, never
        # ecco_durable::load_record*), zero durable-header tag strings, zero substitutions / API actions / switches / numbers /
        # selects / sensors: all measured by test_scope_chain.py / test_fallback_capture_scope.py [S], none declared.
        deltas={"scripts": 3, "globals": 46, "text_sensors": 9, "buttons": 1, "intervals": 1, "modbus_reads": 4, "includes": 1},
        # The three new paths: the capture dispatch (the only one with ops: FOUR FC03 reads 230/3, 241/53, 230/3, 241/53), the
        # synchronous review gate and the button that dispatches it (no ops of their own).
        op_paths_changed=frozenset({"fallback_profile_capture_dispatch", "fallback_profile_review",
                                    "fallback_profile_review_button"}),
        includes_added=_fbb1.ADDED_INCLUDES,
        banned_fw_added=9,
        banned_files=frozenset({"home-assistant/dashboards/ecco_pro.yaml"}),
        added_files=_fbb1.ADDED_FILES,
        note="Review Current Configuration: READ-ONLY review of the inverter fallback-profile registers (4 FC03 reads, zero "
             "Modbus writes, zero NVS writes, zero authority) - boot-time read-only load of the saved views, 3 scripts, 1 button, "
             "9 text sensors, 1 RAM-only 10 s interval, 3 boot-load retention globals, 3 reworded unreadable-marker texts",
    ),
    Entry(
        # Not merged yet: the checkpoint is the content this branch produces, which a merge leaves unchanged.
        # FB-B2 = Fallback Profile SAVE / REPLACE CORRUPT / INVALIDATE on the ESP NVS (witness FBW first, then profile FBP).
        # It edits the firmware YAML in twenty-one places (_fbb2_scope.HUNKS: fourteen pure insertions and seven one-line
        # replacements; fourteen of the twenty-one sit INSIDE FB-B1's own text), and nothing else that is chain-pinned.
        # Its reverter applies to the live text FIRST (newest first), so fbb1's reverter then finds its anchors again.
        # What does NOT move: the Modbus surface (SAVE re-reads through the EXISTING four FC03 reads of the
        # capture dispatch: reads 64 -> 64, writes 52 -> 52), commit_record / load_record / load_record_status stay 57 / 7 / 3,
        # no durable tag string, no substitution, no text sensor, no button, no interval (the arm lifetime is a second lambda of
        # the existing 10 s interval). The ONE new analyzer path is the SAVE gate (it only script.execute()s the dispatch); the
        # INVALIDATE script has no op and takes no lock. The FB durable call sites (commit_transition_t 0 -> 2, nvs_set_blob 1 -> 1,
        # write_one_ 2 -> 2) are not chain metrics: test_fallback_save_scope.py counts them.
        # Older suites edited by FB-B2 (every edit carries an `FB-B2:` or `FB-B2 (D8):` comment, none weakened). The COMPLETE ledger, each
        # entry with an exact-content check and a completeness check, is test_fallback_save_scope.py [6]:
        #   test_fallback_nvs_keyhash.py            switch count 9 -> 10 (the arm switch)
        #   test_fallback_durable_harness.py        the std::array global set 5 -> 6 (fallback_profile_save_ctx_words)
        #   test_fallback_profile_capture.py        D8: READY_B9 is the reworded CANDIDATE READY text (a Save exists now)
        #   test_fallback_capture_model.py          D8: capture-state group gains CAPTURE_SAVING, READY text, one new READY check
        #   test_fallback_capture_host_compile.py   D8: mutants 04 / 05 re-anchored to the new READY text, one SAVING-name mutant
        #   test_fallback_recovery_dashboard.py     the card's write surface (entity / service-domain / B2 werr-us / B3 SAVING / node-floor pins)
        #   support modules (additive)              _fbb_harness.py, _fbb1_engine.py, _fbb1_xpile.py, _fbb1_types.py, _fbb1_fbcap.py,
        #                                           _fbb1_lambda_compile.py (the D8 header + mirror edit ecco_fallback_capture.h / fallback_capture.py)
        # Every other firmware-count pin is chain-anchored and needed no edit (those suites carry no FB-B2 mention at all).
        id="fbb2", pr="FB-B2", commit="unmerged",
        reverts={FIRMWARE: _fbb2.pre_fbb2_firmware},
        checkpoints={FIRMWARE: "dd062d02310f3d28e0d5cfb1eb9dc398dd63cafee8b50669ea76f7bd48125f68"},
        deltas={"scripts": 2, "globals": 18, "api_actions": 1, "switches": 1, "includes": 1},
        op_paths_changed=frozenset({"fallback_profile_save"}),
        includes_added=_fbb2.ADDED_INCLUDES,
        banned_fw_added=12,
        added_files=_fbb2.ADDED_FILES,
        note="Fallback Profile SAVE / REPLACE CORRUPT / INVALIDATE: api action fallback_profile_execute + arm switch + SAVE gate "
             "script (dispatches the existing 4-read capture dispatch, SAVE_FINAL = verify + commit) + synchronous INVALIDATE "
             "script; ZERO new Modbus operation, ZERO inverter write, FBW then FBP via the single FB-B0 commit_transition_t "
             "(2 call sites), RAM-only state, no durable tag",
    ),
    Entry(
        # Not merged yet: the checkpoints are the content this branch produces, which a merge leaves unchanged.
        # FB-B3 = the COMPLETE final stage (Slices A + B + C + integration): the Live Match firmware foundation, the Home Assistant
        # status / operator-action / System Health layer, the dashboard + manifest + InfluxDB v1.3 + VERSION surfaces.
        # CHAIN-PINNED edits (exact-match reverters, checkpoints below):
        #   firmware YAML  _fbb3_scope.HUNKS - thirteen PURE INSERTIONS, no pre-existing line modified: ten RAM globals (six RAW_CACHE_EXT
        #                  + four fence scalars), RAW_CACHE_EXT assignments in the existing config-poll response handlers (Block A / B,
        #                  zero new Modbus operation), the B10 text sensor + boot seed, ONE lambda-only script `fallback_profile_live_refresh`
        #                  (fence tick + Live Match, synchronous), its execution from the 10 s housekeeping interval and from the five
        #                  runtime paths that publish B1 (so B10 never lags B1)
        #   ha-manifest    _fbb3_ha_scope.MANIFEST_HUNKS - two package entries, InfluxDB reference v1.3, firmware-first note, release stamp
        # NOT chain-pinned but exact-reverted by the same generated module (_fbb3_ha_scope): the dashboard (11 hunks -> main @ 87e6151 byte
        # for byte, proven by test_fallback_recovery_dashboard.py [15]) and VERSION.yaml (2 hunks).
        # Measured, not declared: zero Modbus reads / writes (64 / 52), zero commit / load / status / NVS sites, zero durable tags, no
        # substitution, no include, no api action, no switch / button / interval.
        # NEW files are listed in added_files (packages, HA suite, InfluxDB v1.3, notes, scope modules, the two FB-B3 suites). Older suites
        # edited by FB-B3 carry minimal commented `FB-B3` edits (test_fallback_recovery_dashboard, test_fallback_save_scope, the FB-B1
        # harness / invalidate-kit support modules and the HA / health suites); see FB_B3_IMPLEMENTATION_NOTES.md section 5.
        id="fbb3", pr="FB-B3", commit="unmerged",
        reverts={FIRMWARE: _fbb3.pre_fbb3_firmware, HA_MANIFEST: _fbb3.pre_fbb3_manifest},
        checkpoints={FIRMWARE: "645a297a009403fcf4092d930f8735f627294642c2934dcdde5caa756e37d65f", HA_MANIFEST: "3cebe846fa7ff6692b28ff850d799c0a56ce314499f03a3d8ed902df2c279757"},
        deltas={"scripts": 1, "globals": 10, "text_sensors": 1},
        banned_fw_added=_fbb3.BANNED_FW_ADDED,
        banned_files=_fbb3.BANNED_FILES,
        added_files=_fbb3.ADDED_FILES,
        note="FB-B3 complete: Live Match foundation (RAW_CACHE_EXT, RAM-only write fence, B10 + synchronous refresh script) + HA status / "
             "operator-action / System Health packages + Safety view / tile / chips / banner + InfluxDB v1.3 + manifest; ZERO Modbus "
             "operation, ZERO NVS access, ZERO inverter authority",
    ),
    Entry(
        # Not merged yet: the checkpoint is the content this branch produces, which a merge leaves unchanged.
        # FB-C2 = the real Failback Shadow EVALUATOR (shadow-only): ONE pure evaluator header (ecco_failback_shadow.h, a new
        # esphome include) called ONCE per 1 s tick (MODE_IF_LOST, the readiness plan = the Verdict) by the existing FB-C interval,
        # and the Verdict / Inputs / Episode / Soak publication that carries its plan. CHAIN-PINNED edit: firmware YAML
        # _fbc2_scope.EDITS - fourteen exact (before, after) edits
        # (one substitution, one include, 39 RAM globals, a comment, the cache-age static asserts of lambda 0 and the tick lambda's
        # evaluator block / edge freeze / close outcome / verdict counting / publication). Reverted FIRST, newest first, so the older
        # suites still see the FB-B3 firmware byte for byte; none of them was re-hashed.
        # Measured, not declared: ZERO Modbus reads / writes (64 / 52), zero commit / load / status / NVS sites, zero durable tags,
        # zero scripts / api actions / switches / buttons / numbers / selects / intervals / sensors / text sensors, no op path.
        id="fbc2", pr="FB-C2", commit="unmerged",
        reverts={FIRMWARE: _fbc2.pre_fbc2_firmware},
        checkpoints={FIRMWARE: "592c25a21095d63342b1ab08531af494db2ad04bb2df13c66f57f95bc45595d7"},
        deltas={"globals": len(_fbc2.NEW_GLOBAL_IDS), "includes": 1, "substitutions": 1},
        subst_added={_fbc2.SUBSTITUTION[0]: _fbc2.SUBSTITUTION[1]},
        includes_added=(_fbc2.INCLUDE_ENTRY,),
        banned_fw_added=_fbc2.BANNED_FW_ADDED,
        added_files=_fbc2.ADDED_FILES,
        note="FB-C2 shadow evaluator: pure header + mirror, the 1 s shadow tick gathers by value and publishes the deterministic plan "
             "(Verdict / Inputs / Episode kind + frozen edge plan / would-latched / Soak); ZERO Modbus operation, ZERO NVS access, ZERO "
             "inverter authority, nothing reads the shadow",
    ),
    Entry(
        # Not merged yet; replayed onto main @ 5e59d9c (fbc2 = FB-C2 merged as PR #63, remediated d172574; PR #64 is CI only) and
        # reconciled with the final FB-C2 contract (readiness Verdict, Inputs alt / pa). FB-C3 = the Home Assistant shadow UX (status row shadow_episode,
        # FAILBACK_SHADOW_EPISODE, the decoder sensor, the Safety-view line / banner / technical block). It edits NO chain-pinned
        # artifact: the firmware YAML, the shared headers and the deployment manifest are byte-identical to main / FB-C2 (so there is no reverter and
        # no checkpoint here) and every counted quantity (Modbus reads / writes, durable sites, scripts, entities, globals ...) is unchanged:
        # nothing is declared because nothing moved, and test_scope_chain measures that. Its one pre-existing non-pinned edit, the dashboard,
        # is undone exactly by _fbc3_scope.pre_fbc3_dashboard (applied before the FB-B3 reverter by test_fallback_recovery_dashboard.py).
        # BLK-46 token-ban amendment: the HA suite spells `ecco_fallback` entity ids (declared below); `ecco_failback` is spelled only as the
        # five existing shadow entity ids in the status package (test_fallback_profile_schema.py [FB-C3]).
        id="fbc3", pr="FB-C3", commit="unmerged",
        banned_files=_fbc3.BANNED_FILES,
        added_files=_fbc3.ADDED_FILES,
        note="FB-C3 shadow UX: HA-only (status row, decoder sensor, health reason / check, Safety view); ZERO firmware change, ZERO "
             "Modbus operation, ZERO NVS access, ZERO inverter authority, zero new control surface",
    ),
    Entry(
        # FB-D1 (RTC / polling / liveness hardening, branch feature/fbd1-rtc-liveness): edits the firmware YAML in twelve places -
        # _fbd1_scope.EDITS: the RTC write / read terminal handlers (on_not_sent, on_custom_response), the NTP-abort release,
        # the deadline breaker / invariant gate / lock-release edge in the 1 s RTC tick, the quiet-bus write dispatch, the
        # pure correction policy (include/ecco_rtc_policy.h) in the read handler, the telemetry / configuration poll
        # ownership re-checks before every delayed block with the unified invalidation handlers, and the configuration poll
        # catch-up interval. The reverter reproduces the FB-C2 firmware byte for byte (FB-C3 edits no firmware), so the older
        # suites still see it unchanged; none of them was re-hashed.
        # Measured, not declared: ZERO Modbus reads / writes (64 / 52), zero commit / load / status / NVS sites, zero durable
        # tags, zero scripts / api actions / switches / buttons / numbers / selects / sensors / text sensors, no op path.
        id="fbd1", pr="FB-D1", commit="unmerged",
        reverts={FIRMWARE: _fbd1.pre_fbd1_firmware},
        checkpoints={FIRMWARE: "104033c319d71f4d98ebcf8dc37fa2e4b6838a6597dec1da5eeb93c879a51aa2"},
        deltas={"globals": len(_fbd1.NEW_GLOBAL_IDS), "intervals": 1, "includes": 1},
        includes_added=(_fbd1.INCLUDE_ENTRY,),
        banned_fw_added=_fbd1.BANNED_FW_ADDED,
        added_files=_fbd1.ADDED_FILES,
        note="FB-D1 RTC / poll liveness: every RTC and poll Modbus action has all five terminal handlers, no RTC path can strand "
             "correction_in_progress (NTP-abort release + 90 s quiet-bus deadline breaker), polls re-check ownership before every "
             "delayed block and owe a catch-up instead of interleaving, and the pure ecco_rtc policy decides when an automatic "
             "correction may be queued; ZERO new Modbus operation, ZERO NVS access, ZERO new inverter authority",
    ),
    Entry(
        # lic0 (the v0.9.0 public-release licence alignment, _lic0_scope.py): the Energy Actions card becomes GPL-3.0-or-later and
        # its bundle is rebuilt from the UNCHANGED source with legalComments "eof", so Lit's BSD-3-Clause notices ship inside it
        # (the old bytes + one appended licence block). It edits no chain-pinned artifact: no reverter, no checkpoint, zero deltas
        # (measured by test_scope_chain.py). The three older suites that pin the card folder hash lic0's pre_lic0_bytes(...) of each
        # file (commented `LIC0:`), the exact pre-lic0 bytes, so none of them was re-hashed; test_lic0_transition.py proves it.
        id="lic0", pr="LIC0", commit="public-release-0.9.0",
        added_files=frozenset({"registry/tests/_lic0_scope.py", "registry/tests/test_lic0_transition.py"}),
        note="v0.9.0 licence alignment of frontend/ecco-energy-actions-card: GPL-3.0-or-later declared, Lit BSD-3-Clause notices kept "
             "at the end of the rebuilt bundle (code bytes identical); ZERO firmware change, ZERO Modbus operation, ZERO behaviour change",
    ),
)

# ---------------------------------------------------------------------------
# pub0: the PUBLIC-EXPORT transition (docs/public-release/PUBLIC_RELEASE_BUILD_SPEC.md C.3). Not a PR on main: the declared,
# exact, reversible sanitisation that turns this private tree into the public export (_pub0_scope.py; the manifest of every site is
# registry/tests/fixtures/pub0_manifest.json, fingerprint PUB0_FINGERPRINT). It is the NEWEST entry of the exported tree's chain and
# is in CHAIN only there (_pub0.EXPORTED, flipped by pub0 itself): in the private tree the live artifacts are pub0's SOURCE, so
# appending it would be a false claim. test_pub0_transition.py proves this entry in the private tree too, on the in-memory export.
# CHAIN-PINNED edit: registry/inverter_capabilities.yaml only (its device-slug entity ids; no entry before pub0 ever edited it, so
# its reverter returns the root file byte for byte). The firmware, both headers, the state machine and the manifest spell no pub0
# token: no reverter, no checkpoint, zero deltas, all measured by test_scope_chain.py.
# Older suites whose pins hash a pub0-edited file that is NOT chain-pinned (the dashboard, the Energy Actions frontend folder, the
# InfluxDB v1.2 options, the status / heartbeat packages) carry a minimal commented `PUB0:` edit: they hash _pub0.private_view(...)
# of the file - the identity in the private tree, the exact reverse in the export. The complete ledger is test_pub0_transition.py [6].
# FRESH-HISTORY (recorded exception, no pin touched): _fbb2_static_lib.base_text() now undoes only the fbb1..fbb2 entries from the
# as-of-fbb2 text it is handed (test_fresh_history_fallback.py), so test_fallback_save_static_pins passes without commit 65e4be5.
# ---------------------------------------------------------------------------
PUB0_FINGERPRINT = "921c3ffefb5b233ffc7fd4d579f1c710fa1278fde03f9567eff9bf61269f45d6"
PUB0 = Entry(
    id="pub0", pr="PUB0", commit="public-export",
    reverts={CAPABILITIES: _pub0.reverter(CAPABILITIES)},
    checkpoints={CAPABILITIES: "efc8bc7e5b7a086ce42c01b7bcedcb62114afcf1e99feecba0d49b7a98a89ca5"},
    note="public-export sanitisation: the private device slug -> the generic default slug, the Octopus meter serial / MPANs -> "
         "placeholders, the export flag, the register map's provenance wording and its six personal-name attributions; exact sites from the pub0 manifest, exact reverse for the proofs; ZERO firmware change, "
         "ZERO Modbus operation, ZERO behaviour change",
)
EXPORT_ENTRIES: tuple[Entry, ...] = (PUB0,)

# ---------------------------------------------------------------------------
# PEX: the POST-EXPORT EDIT LAYER (schema ecco-pex/1; registry/tests/_pex.py, docs/dev/post-export-edit-layer.md). The public tree is
# the pub0 export and the development base: every later change is made ON the export. Each one is ONE Entry appended here, in merge
# order on the public main, AFTER pub0 (never in ENTRIES, which are closed: test_pex_transition.py pins them). It declares its
# chain-pinned edits exactly as above, its edits to the files pub0 froze (frozen_reverts / frozen_checkpoints), and its hash-linked
# fingerprint. In CHAIN only in the export (like PUB0). _pex.as_of_pub0() undoes these entries newest first, sha256-checked at every
# step: test_pub0_transition.py proves pub0 on the tree AS OF pub0 (byte for byte the 57 manifest result hashes), and an older suite
# whose historical pin names a file a post-export entry may edit reads that file the same way (each such read is a commented `PEX`
# edit, counted by test_pex_transition.py [8]); its live safety invariants keep reading the live file.
# pex0 = the foundation: the layer itself and the routing of those historical pins (_pex0_scope.py). ZERO product / feature change:
# no firmware, Home Assistant package, dashboard, manifest or registry edit (no chain-pinned reverter, no delta).
# ---------------------------------------------------------------------------
PEX0 = Entry(
    id="pex0", pr="PEX0", commit="unmerged",
    frozen_reverts={rel: _pex0.reverter(rel) for rel in _pex0.FROZEN_EDITS},
    frozen_checkpoints={   # sha256 (LF) of each routed suite after pex0; as of pub0 each is its pub0 manifest result
        "home-assistant/tests/test_ecco_fallback_packages.py": "cf06781407ba89f83c52099b2fed4fe1dbd7e1d1071153023c45c9d5a08ec34e",
        "home-assistant/tests/test_ecco_shadow_check_ux.py": "8794ce164f410da7147466a77950b0e66b6e74515cc71a281463135f2502a632",
        "registry/tests/test_fallback_recovery_dashboard.py": "a14cbf4771491f58ee3c0eac0ab94202f553dbc2f9c6f46753b8c0717516d43a",
    },
    added_files=_pex0.ADDED_FILES,
    # _pex.fingerprint(PEX0): hashes its parent PUB0_FINGERPRINT and the before / after sha256 of the three routed suites
    fingerprint="c91d3a5834cef6b69f692bd8c301a478138ac7627b29c53a0a0e35cac29b36f8",
    note="PEX foundation (schema ecco-pex/1): the post-export edit layer and the routing of the historical pins of three older suites "
         "through _pex.as_of_pub0; ZERO firmware, Home Assistant, dashboard, manifest or registry change, ZERO behaviour change",
)
# dtgp1 (configurable Dump-to-Grid command ceiling; _dtgp1_scope.py, docs/dev/dump-to-grid-ceiling.md): the first product change made
# on the export after the foundation pex0. CHAIN-PINNED edit: the firmware YAML in seven places, _dtgp1_scope.EDITS - the source of
# truth's comment, one substitution (the runaway backstop floor), the command-relative absolute backstop in ecco_battery_power's
# on_value and its END text, a fifth compile-time-only on_boot lambda, one diagnostic read-back sensor and the REVIEW final lambda
# re-judging W2 against the configured ceiling after review_evaluate. No other firmware file changes (the W2 header keeps its generic
# 3000 W constant: test_failback_shadow_ha_contract.py pins every git-tracked firmware file except this YAML, and a firmware header is
# neither frozen nor chain-pinned). The reverter reproduces the FB-D1 firmware byte for byte (lic0, pub0 and pex0 edit no firmware),
# so every older suite still sees it unchanged; none of them was re-hashed.
# FROZEN edit (PEX): the dashboard's W2 wording, one line (_dtgp1_scope.DASHBOARD_EDITS: the recovery card's wording, no wattage); as
# of pub0 the dashboard is the export byte for byte.
# ONE older suite carries a minimal commented `DTGP1:` edit, no pin touched: test_fallback_durable_model.py takes the substitution keys
# it sets aside from the entries up to its own anchor fbb0 (exactly FB-C1's five) instead of from every entry, because dtgp1 is the
# first entry to declare a substitution outside the ecco_failback_shadow_* family. test_fbd1_liveness.py needs none: since pex0 it
# reads its FB-D1 baseline as of fbd1 through the chain.
# Measured, not declared: ZERO Modbus reads / writes (64 / 52), zero commit / load / status / NVS sites, zero durable tags, zero
# scripts / api actions / switches / buttons / numbers / selects / globals / intervals / text sensors, no op path.
DTGP1 = Entry(
    id="dtgp1", pr="DTGP1", commit="unmerged",
    reverts={FIRMWARE: _dtgp1.pre_dtgp1_firmware},
    checkpoints={FIRMWARE: "9e49b229b31568e059da353ef30fd7a3b8d8cf9af1068c3edb19b7cb0d044c55"},
    deltas={"sensors": 1, "substitutions": 1},
    subst_added={_dtgp1.SUBSTITUTION[0]: _dtgp1.SUBSTITUTION[1]},
    banned_fw_added=_dtgp1.BANNED_FW_ADDED,
    added_files=_dtgp1.ADDED_FILES,
    frozen_reverts={_dtgp1.DASHBOARD_REL: _dtgp1.pre_dtgp1_dashboard},
    frozen_checkpoints={   # sha256 (LF) of the dashboard after dtgp1; as of pub0 it is its pub0 manifest result
        _dtgp1.DASHBOARD_REL: "fa0efedfe686fcd9cf57adf7e4b5838987efa81929d966ffd945d37145b579c9",
    },
    # _pex.fingerprint(DTGP1): hashes its parent pex0's fingerprint and every declaration above
    fingerprint="313f73eadd0c104cd1e81f35690fac52e0b065b0eef3eed35c9718f965baeb6c",
    note="configurable Dump-to-Grid command ceiling: ecco_dump_controller_max_ceiling_w stays the one source of truth (default "
         "3000 W) with compile-time validation (decimal, above the floor, a rounding multiple, <= the site TOU ceiling, <= 8000 W); "
         "the absolute runaway backstop follows the current command above the live-validated 3000 W level (identical at or below "
         "it); W2 follows the configured ceiling; one read-back sensor; ZERO new Modbus operation, ZERO NVS access, ZERO new "
         "inverter authority",
)
# fbrp1 (public fallback records / design basis; _fbrp1_scope.py, docs/architecture/fallback/FALLBACK_DESIGN_BASIS.md): a records and
# documentation change made on the export after dtgp1. It publishes the fallback design basis and the stage status (FB-B3 closed;
# FB-C2 / FB-C3 / FB-D1 deployed and partially live-proven) and corrects public status text that still called the FB-C3 shadow display
# offline only. FROZEN edit (PEX): VERSION.yaml's 7.18.0 dashboard comment, one block (_fbrp1_scope.VERSION_EDITS);
# tested_in_home_assistant stays false; as of pub0 VERSION.yaml is the export byte for byte (its enrolled hash). README.md,
# SUPPORTED_HARDWARE.md, ARCHITECTURE.md and CHANGELOG.md are not frozen. No older suite is edited: the pub0-era VERSION.yaml pins
# already read the file through _pex.as_of_pub0 (pex0).
# Measured, not declared: no chain-pinned reverter, no checkpoint, no delta, no op path; ZERO firmware, Home Assistant package,
# dashboard, frontend, deployment, registry, Intelligence or ecco_core byte; ZERO Modbus reads / writes (64 / 52).
FBRP1 = Entry(
    id="fbrp1", pr="FBRP1", commit="unmerged",
    added_files=_fbrp1.ADDED_FILES,
    frozen_reverts={_fbrp1.VERSION_REL: _fbrp1.pre_fbrp1_version},
    frozen_checkpoints={   # sha256 (LF) of VERSION.yaml after fbrp1; as of pub0 it is its enrolled hash
        _fbrp1.VERSION_REL: "73566c51c016734d251fc5da0794aa16c2e3abdc7362e2238925d616c2cde980",
    },
    # _pex.fingerprint(FBRP1): hashes its parent dtgp1's fingerprint and every declaration above
    fingerprint="46cf76256da78b24e2fd59692f0bf126eba059352c37006542708c64b38e8f8c",
    note="public fallback records / design basis: the fallback design basis and stage status published "
         "(docs/architecture/fallback/FALLBACK_DESIGN_BASIS.md) and the stale FB-C3 status corrected (VERSION.yaml comment; "
         "tested_in_home_assistant stays false); records and documentation only: ZERO firmware, Home Assistant package, dashboard, "
         "frontend, deployment, registry, Intelligence or ecco_core change, ZERO Modbus operation, ZERO behaviour change",
)
# rtcf1 (FB-D1 follow-up: the RTC correction-failure health alert; _rtcf1_scope.py): a Home Assistant health change made on the export
# after fbrp1. sensor.ecco_health_rtc represents the designed check rtc_correction_failures_recent from the EXISTING firmware sensor
# "Failed Corrections Since Boot": WARNING / RTC_CORRECTION_FAILURES_RECENT for 1800 s after an observed numeric increase (never a
# reboot reset or a first value after unknown), UNKNOWN for an unreadable counter, with last_failure_at / last_result attributes; the
# other RTC checks, ranks, reason codes and presentation are unchanged. FROZEN edits (PEX): the health package, the check registry
# record (designed -> implemented_offline) and docs/SYSTEM_HEALTH_ARCHITECTURE.md (_rtcf1_scope.FROZEN_REVERTERS); as of pub0 each is
# the export byte for byte. CHANGELOG.md is not frozen. No older suite is edited.
# Measured, not declared: no chain-pinned reverter, no checkpoint, no delta, no op path; ZERO firmware, frontend, dashboard,
# deployment, Intelligence or ecco_core byte; ZERO Modbus reads / writes (64 / 52); no HA control surface (template keys only).
RTCF1 = Entry(
    id="rtcf1", pr="RTCF1", commit="unmerged",
    added_files=_rtcf1.ADDED_FILES,
    frozen_reverts=dict(_rtcf1.FROZEN_REVERTERS),
    frozen_checkpoints={   # sha256 (LF) of each file after rtcf1; as of pub0 each is its pub0 manifest result
        _rtcf1.HEALTH_PKG_REL: "a76d43a598cf1ce1639c1a0f67b8cc47eb4a433169f61024c2dd74243e81a165",
        _rtcf1.CHECKS_REL: "12904c78b851923ad3252a4c2d7e9469538e0baf7381857f31865b5de2817855",
        _rtcf1.ARCH_DOC_REL: "6e3609c16aacc97e5e2396d9a112f3e049b5f111980b0ac12774eb4b2332858f",
    },
    # _pex.fingerprint(RTCF1): hashes its parent fbrp1's fingerprint and every declaration above
    fingerprint="02d4bf53955acc3788c9df5972327bb62d5af028d8b9e46e0aa872c4fc94b0a0",
    note="RTC correction-failure health alert (FB-D1 follow-up): sensor.ecco_health_rtc represents rtc_correction_failures_recent from "
         "the existing Failed Corrections Since Boot sensor (WARNING for 1800 s after an observed increase, reboot reset and Home "
         "Assistant restart never count, unreadable is UNKNOWN); Home Assistant health and records only: ZERO firmware, frontend, "
         "dashboard, deployment, Intelligence or ecco_core change, ZERO Modbus operation, no new control surface",
)
# esb1 (security maintenance: the Energy Actions card builds with esbuild 0.28.1, Dependabot PR #12, GHSA-67mh-4wv8-2f99;
# _esb1_scope.py): made on the export after rtcf1. The card's package.json / package-lock.json are PR #12's exact blobs and the bundle
# is rebuilt: its code bytes before the licence block are IDENTICAL (lic0's pre-lic0 bundle, the FB-B3 code), only the trailing Lit
# licence block is regrouped by the newer esbuild (the same files, the same BSD-3-Clause notices). FROZEN edits (PEX): the three card
# files, enrolled by the owner-approved O3 amendment (_pex.ENROLLED; their pub0 state is their 883068d hash), and the three suites
# that pin the card folder's FB-B3 state, whose folder pin now reads a frozen card file AS OF pub0 (the pin value is unchanged)
# (_esb1_scope.FROZEN_REVERTERS); as of pub0 each file is the export byte for byte. test_lic0_transition.py, test_pex_transition.py,
# _pex.py, THIRD_PARTY_NOTICES.md, CHANGELOG.md and docs/dev/post-export-edit-layer.md are not frozen.
# Measured, not declared: no chain-pinned reverter, no checkpoint, no delta, no op path; ZERO firmware, Home Assistant package,
# dashboard, deployment, registry, Intelligence or ecco_core byte; ZERO Modbus reads / writes (64 / 52); ZERO behaviour change.
ESB1 = Entry(
    id="esb1", pr="ESB1", commit="unmerged",
    added_files=_esb1.ADDED_FILES,
    frozen_reverts=dict(_esb1.FROZEN_REVERTERS),
    frozen_checkpoints={   # sha256 (LF) of each file after esb1; as of pub0 each is its pub0 state (manifest result / enrolled hash)
        _esb1.PACKAGE_JSON_REL: "045e797d225140538f6b357683d8e5bd0a81fc4b92e10279d6dbd5a77a43933c",
        _esb1.PACKAGE_LOCK_REL: "f7ca9d7f0e48cc1680e06fada91c84b6ba4285228d7bbe623bf61430f2f4b52d",
        _esb1.BUNDLE_REL: "7674bc1acc13b5a305d37b6e0055b200cbb86c172395e07cb286567a76c07d2d",
        _esb1.SUITE_FBP_REL: "eb774df00f1ef0c158bdb03c4e5f69068fea80cd23e88d3bf6774ab1aa3566b8",
        _esb1.SUITE_SCU_REL: "25d13a54fd0bda3a67ef2835e3da50f41a1f5f98b7b00e0142bdb166e35df4fe",
        _esb1.SUITE_FRD_REL: "436c177be2e8796d57559ea1378a258ac387e6f9008ca192894e07239bc5a029",
    },
    # _pex.fingerprint(ESB1): hashes its parent rtcf1's fingerprint and every declaration above
    fingerprint="ee161454359816ee40e44c04dd0c009d0b96838ba912bcf606975bcb0049d528",
    note="Energy Actions card esbuild 0.21.5 -> 0.28.1 (Dependabot PR #12, GHSA-67mh-4wv8-2f99): package.json / package-lock.json "
         "(esbuild only) and the rebuilt bundle, whose code bytes are identical (only the Lit licence block is regrouped); the three "
         "card files enrolled (O3 amendment) and the three FB-B3 / FB-C3 folder pins read them as of pub0 (pin unchanged): ZERO "
         "firmware, Home Assistant, dashboard, deployment, registry, Intelligence or ecco_core change, ZERO Modbus operation",
)
POST_EXPORT_ENTRIES: tuple[Entry, ...] = (PEX0, DTGP1, FBRP1, RTCF1, ESB1)

_SHA256 = re.compile(r"[0-9a-f]{64}")


class ChainError(AssertionError):
    pass


def _posix_relative_exact(p: str) -> bool:
    return (isinstance(p, str) and bool(p) and "\\" not in p and not p.startswith("/") and ":" not in p
            and ".." not in p.split("/") and not p.endswith("/") and not any(c in p for c in "*?[]{}"))


class Chain:
    def __init__(self, entries: tuple[Entry, ...] = ENTRIES):
        ids = [e.id for e in entries]
        if len(set(ids)) != len(ids) or ROOT_ID in ids:
            raise ChainError(f"chain ids must be unique and not 'root': {ids}")
        export_at = ids.index(PUB0.id) if PUB0.id in ids else None
        for i, e in enumerate(entries):
            # PEX: frozen edits and the fingerprint exist only AFTER pub0 (a change made on the export); every such entry is fingerprinted.
            if set(e.frozen_reverts) != set(e.frozen_checkpoints):
                raise ChainError(f"{e.id}: every frozen reverter needs its result sha256 and every frozen checkpoint its reverter")
            for p, h in e.frozen_checkpoints.items():
                if not _posix_relative_exact(p) or p in PINNED:
                    raise ChainError(f"{e.id}: frozen path {p!r} must be an exact repo-relative POSIX path that is NOT chain-pinned "
                                     "(a chain-pinned artifact is declared through reverts / checkpoints)")
                if not (isinstance(h, str) and _SHA256.fullmatch(h)):
                    raise ChainError(f"{e.id}: the frozen checkpoint of {p} must be a 64-hex sha256")
            if export_at is not None and i > export_at:
                if not (isinstance(e.fingerprint, str) and _SHA256.fullmatch(e.fingerprint)):
                    raise ChainError(f"{e.id}: a post-export entry carries its 64-hex PEX fingerprint (_pex.fingerprint)")
            elif e.frozen_reverts or e.fingerprint:
                raise ChainError(f"{e.id}: frozen edits and a PEX fingerprint belong to post-export entries only (after {PUB0.id!r})")
            for k in e.deltas:
                if k not in METRICS:
                    raise ChainError(f"{e.id}: unknown delta metric {k!r}")
            for p in e.reverts:
                if p not in PINNED:
                    raise ChainError(f"{e.id}: reverter for unpinned artifact {p!r}")
                if p not in e.checkpoints:
                    raise ChainError(f"{e.id}: reverter for {p} has no checkpoint (every declared edit needs an exact result hash)")
            for p in e.checkpoints:
                if p not in e.reverts:
                    raise ChainError(f"{e.id}: checkpoint for {p} has no reverter")
            for p in (*e.fbh_includers, *e.banned_files, *e.added_files):
                if not _posix_relative_exact(p):
                    raise ChainError(f"{e.id}: declared path {p!r} must be an exact repo-relative POSIX path (no backslash, "
                                     "drive, leading slash, '..' or glob characters) - prefix/glob exemptions are not allowed")
            if not e.tags_promoted <= e.tags_declared:
                raise ChainError(f"{e.id}: tags_promoted must be a subset of tags_declared")
            both = set(e.subst_added) & (set(e.subst_changed) | set(e.subst_removed))
            if both or set(e.subst_changed) & set(e.subst_removed):
                raise ChainError(f"{e.id}: a substitution may be declared added, changed or removed, not several")
            for k, v in (*e.subst_added.items(), *((k, nv) for k, (_ov, nv) in e.subst_changed.items())):
                if not isinstance(k, str) or not isinstance(v, str) or not k or "*" in k or "?" in k:
                    raise ChainError(f"{e.id}: substitution declarations are exact string key -> string value pairs, got {k!r}: {v!r}")
        self.entries = tuple(entries)

    # -- navigation ---------------------------------------------------------
    def ids(self) -> list[str]:
        return [e.id for e in self.entries]

    def entry(self, entry_id: str) -> Entry:
        for e in self.entries:
            if e.id == entry_id:
                return e
        raise ChainError(f"unknown chain entry {entry_id!r} (have {self.ids()})")

    def _index(self, entry_id: str) -> int:
        """Number of entries applied at `entry_id` (root = 0)."""
        return 0 if entry_id == ROOT_ID else self.ids().index(self.entry(entry_id).id) + 1

    def upto(self, entry_id: str) -> tuple[Entry, ...]:
        return self.entries[: self._index(entry_id)]

    def after(self, entry_id: str) -> tuple[Entry, ...]:
        return self.entries[self._index(entry_id):]

    def prev_id(self, entry_id: str) -> str:
        i = self._index(entry_id)
        return ROOT_ID if i <= 1 else self.entries[i - 2].id

    # -- exact reverts ------------------------------------------------------
    def as_of(self, path: str, entry_id: str, text: str) -> str:
        """`text` (the LIVE artifact) with every entry newer than `entry_id`
        reverted, newest first. Exact-match: raises if any reverter's edits are
        not present exactly as declared."""
        if path not in PINNED:
            raise ChainError(f"{path} is not a chain-pinned artifact")
        for e in reversed(self.after(entry_id)):
            fn = e.reverts.get(path)
            if fn is not None:
                text = fn(text)
        return text

    def as_of_all(self, entry_id: str, live: Mapping[str, str] | None = None) -> dict[str, str]:
        live = live or {}
        return {p: self.as_of(p, entry_id, live[p] if p in live else read_live(p)) for p in PINNED}

    def frozen_checkpoint(self, path: str, entry_id: str, base: str) -> str:
        """PEX: sha256 a frozen file must have at `entry_id`: the newest frozen checkpoint at or before it, else `base` (the file's
        pub0 state, _pex.base()). The exact, sha256-checked undo of the frozen reverters is _pex.as_of()."""
        sha_ = base
        for e in self.upto(entry_id):
            sha_ = e.frozen_checkpoints.get(path, sha_)
        return sha_

    def checkpoint(self, path: str, entry_id: str) -> str:
        """sha256 the artifact must have at `entry_id`: the newest checkpoint at
        or before it, else the root hash."""
        sha_ = ROOT_SHA[path]
        for e in self.upto(entry_id):
            sha_ = e.checkpoints.get(path, sha_)
        return sha_

    def touched_after(self, entry_id: str, path: str) -> bool:
        return any(path in e.reverts for e in self.after(entry_id))

    # -- declared (non-firmware) scope --------------------------------------
    def declared_includes(self, after: str = ROOT_ID) -> tuple:
        return tuple(i for e in self.after(after) for i in e.includes_added)

    def declared_subst(self, after: str = ROOT_ID) -> dict:
        """Substitution key -> value additions declared by the entries after `after`."""
        return {k: v for e in self.after(after) for k, v in e.subst_added.items()}

    def declared_tags(self) -> frozenset:
        return frozenset().union(frozenset(), *(e.tags_declared for e in self.entries))

    def declared_includers(self) -> frozenset:
        return frozenset().union(*(e.fbh_includers for e in self.entries))

    def declared_banned_files(self) -> frozenset:
        return frozenset().union(*(e.banned_files for e in self.entries))

    def declared_banned_fw(self, upto: str | None = None) -> int:
        return sum(e.banned_fw_added for e in (self.entries if upto is None else self.upto(upto)))

    def declared_delta(self, metric: str, upto: str | None = None) -> int:
        return sum(e.deltas.get(metric, 0) for e in (self.entries if upto is None else self.upto(upto)))

    def declared_added_files(self) -> frozenset:
        return frozenset().union(*(e.added_files for e in self.entries))

    def declared_promoted_tags(self) -> frozenset:
        return frozenset().union(*(e.tags_promoted for e in self.entries))

    def declared_since(self, metric: str, entry_id: str) -> int:
        """Sum of the deltas declared by every entry AFTER `entry_id`."""
        return sum(e.deltas.get(metric, 0) for e in self.after(entry_id))

    def declared_op_paths(self, after: str = ROOT_ID) -> frozenset:
        return frozenset().union(frozenset(), *(e.op_paths_changed for e in self.after(after)))

    # -- measurement --------------------------------------------------------
    def measure(self, texts: Mapping[str, str]) -> dict[str, int]:
        return measure(texts)

    def expected(self, entry_id: str, live: Mapping[str, str] | None = None) -> dict[str, int]:
        """Root measurements (computed from the exactly-reverted root artifacts,
        never typed) plus the sum of every declared delta up to `entry_id`."""
        root = measure(self.as_of_all(ROOT_ID, live))
        return {m: root[m] + self.declared_delta(m, entry_id) if m != "banned_fw"
                else root[m] + self.declared_banned_fw(entry_id) for m in METRICS}

    def analyze_as_of(self, entry_id: str, live_fw_text: str | None = None,
                      live: Mapping[str, str] | None = None) -> dict:
        """The write-surface analyzer run on the firmware AND its included headers
        as of `entry_id` (so findings are exactly that state's)."""
        live = dict(live or {})
        if live_fw_text is not None:
            live[FIRMWARE] = live_fw_text
        texts = self.as_of_all(entry_id, live)
        return analyze_text(texts[FIRMWARE], _headers_of(texts))


# ---------------------------------------------------------------------------
# Measurement helpers
# ---------------------------------------------------------------------------
_ANALYZE_CACHE: dict[str, dict] = {}


def analyze_text(fw_text: str, headers: Mapping[str, str] | None = None) -> dict:
    """tools/analyze_write_surface.analyze() on in-memory firmware text (cached
    by content hash). The analyzer resolves `esphome: includes:` relative to the
    firmware file and scans those headers for raw bus access, so they are
    materialised next to the temporary firmware file: `headers` maps a path
    relative to firmware/ (e.g. "include/ecco_durable_snapshot.h") to its text
    (pass the as-of headers); any other include the text lists is copied from
    the live firmware/ tree if present."""
    headers = dict(headers or {})
    key = sha(fw_text + "".join(f"\0{k}\0{sha(v)}" for k, v in sorted(headers.items())))
    if key not in _ANALYZE_CACHE:
        import analyze_write_surface as aws
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            for rel in load_fw(fw_text)["esphome"].get("includes", []):
                dest = root / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                if rel in headers:
                    dest.write_text(headers[rel], encoding="utf-8", newline="\n")
                elif (REPO / "firmware" / rel).is_file():
                    dest.write_text((REPO / "firmware" / rel).read_text(encoding="utf-8"), encoding="utf-8", newline="\n")
            p = root / "firmware.yaml"
            p.write_text(fw_text, encoding="utf-8", newline="\n")
            _ANALYZE_CACHE[key] = aws.analyze(p)
    return _ANALYZE_CACHE[key]


def _headers_of(texts: Mapping[str, str]) -> dict[str, str]:
    return {"include/ecco_durable_snapshot.h": texts[DURABLE_HEADER], "include/ecco_recovery_evidence.h": texts[EVIDENCE_HEADER]}


def per_path_ops(fw_text: str, headers: Mapping[str, str] | None = None) -> dict[str, tuple]:
    return {p.name: tuple((o.kind, o.start_address, o.count) for o in p.ops) for p in analyze_text(fw_text, headers)["paths"]}


_FW_CACHE: dict[str, dict] = {}


def load_fw(fw_text: str) -> dict:
    """_dump_sim.load_firmware_text() cached by content hash (parsing the
    firmware with the pure-Python YAML loader is the slow step)."""
    import _dump_sim as ds
    key = sha(fw_text)
    if key not in _FW_CACHE:
        _FW_CACHE[key] = ds.load_firmware_text(fw_text)
    return _FW_CACHE[key]


def measure(texts: Mapping[str, str]) -> dict[str, int]:
    fw_text = texts[FIRMWARE]
    fw = load_fw(fw_text)
    ops = [o.kind for p in analyze_text(fw_text, _headers_of(texts))["paths"] for o in p.ops]
    return {
        "scripts": len(fw["script"]),
        "globals": len(fw["globals"]),
        "api_actions": len(fw["api"].get("actions", [])),
        "intervals": len(fw.get("interval", [])),
        "sensors": len(fw.get("sensor") or []),
        "binary_sensors": len(fw.get("binary_sensor") or []),
        "text_sensors": len(fw.get("text_sensor") or []),
        "switches": len(fw.get("switch") or []),
        "buttons": len(fw.get("button") or []),
        "numbers": len(fw.get("number") or []),
        "selects": len(fw.get("select") or []),
        "commit_record": len(re.findall(r"ecco_durable::commit_record\s*\(", fw_text)),
        "load_record": len(re.findall(r"ecco_durable::load_record\s*\(", fw_text)),
        "load_record_status": len(re.findall(r"ecco_durable::load_record_status\s*\(", fw_text)),
        "modbus_writes": ops.count("write"),
        "modbus_reads": ops.count("read"),
        "substitutions": len(fw["_substitutions"]),
        "includes": len(fw["esphome"].get("includes", [])),
        "durable_tag_strings": len(_tags.inventory(texts[DURABLE_HEADER])),
        "banned_fw": len(BANNED.findall(fw_text)),
    }


def exact_reverter(edits, what: str) -> Reverter:
    """Build an exact-match reverter from (before, after) text pairs, the same
    contract as _sg06_scope / _dump_v2_scope: every `after` must occur EXACTLY
    once in the text handed in (else AssertionError), and is replaced by its
    `before`. Generate the pairs from the real diff and verify by round trip."""
    edits = tuple(edits)

    def revert(text: str) -> str:
        for before, after in reversed(edits):      # undo the newest edit first, so dependent edits revert cleanly
            n = text.count(after)
            if n != 1:
                raise AssertionError(f"{what}: expected exactly one occurrence of the edited text, found {n}: {after[:80]!r}")
            text = text.replace(after, before)
        return text

    return revert


def _includes(fw_text: str) -> list:
    return list(load_fw(fw_text)["esphome"].get("includes", []))


def _substitutions(fw_text: str) -> dict:
    return dict(load_fw(fw_text)["_substitutions"])


def integrity_report(chain: Chain, live: Mapping[str, str] | None = None) -> list[tuple[str, bool, str]]:
    """Machine-check a chain against the artifacts in `live` (default: the repo).
    Returns (name, ok, detail) rows; every row must be ok.

    For each entry E (previous state P): as_of(E) reproduces E's recorded
    checkpoints exactly; every declared reverter really changes the text; the
    declared deltas equal the measured difference between P and E; the declared
    op-path / include / substitution additions equal the measured ones. Finally
    live == root + the sum of every declared delta."""
    rows: list[tuple[str, bool, str]] = []
    live = dict(live) if live else {p: read_live(p) for p in PINNED}
    state: dict[str, dict[str, str]] = {}
    meas: dict[str, dict[str, int]] = {}
    for eid in [ROOT_ID, *chain.ids()]:
        try:
            state[eid] = chain.as_of_all(eid, live)
        except Exception as exc:  # noqa: BLE001 - a reverter that cannot apply is a FAILED proof, never a skipped one
            rows.append((f"{eid}: exact-match reverters apply to the live artifacts", False, f"{type(exc).__name__}: {str(exc)[:200]}"))
            return rows
        meas[eid] = measure(state[eid])
    rows.append(("root: every pinned artifact reverts to its main @ 004040b hash",
                 all(sha(state[ROOT_ID][p]) == ROOT_SHA[p] for p in PINNED),
                 str([p for p in PINNED if sha(state[ROOT_ID][p]) != ROOT_SHA[p]])))
    for e in chain.entries:
        prev = chain.prev_id(e.id)
        bad = [p for p in PINNED if sha(state[e.id][p]) != chain.checkpoint(p, e.id)]
        rows.append((f"{e.id}: as_of reproduces every recorded checkpoint ({e.commit}) byte-for-byte", not bad, str(bad)))
        vacuous = [p for p, fn in e.reverts.items() if fn(state[e.id][p]) == state[e.id][p]]
        rows.append((f"{e.id}: every declared reverter changes its artifact (none is an identity)", not vacuous, str(vacuous)))
        untouched = [p for p in PINNED if p not in e.reverts and state[e.id][p] != state[prev][p]]
        rows.append((f"{e.id}: artifacts it declares no edit to are identical to the previous state", not untouched, str(untouched)))
        want = {m: (e.banned_fw_added if m == "banned_fw" else e.deltas.get(m, 0)) for m in METRICS}
        got = {m: meas[e.id][m] - meas[prev][m] for m in METRICS}
        rows.append((f"{e.id}: declared deltas == measured difference from {prev}", want == got,
                     str({m: (want[m], got[m]) for m in METRICS if want[m] != got[m]})))
        fw_e, fw_p = state[e.id][FIRMWARE], state[prev][FIRMWARE]
        ops_e, ops_p = per_path_ops(fw_e, _headers_of(state[e.id])), per_path_ops(fw_p, _headers_of(state[prev]))
        changed = frozenset(n for n in set(ops_e) | set(ops_p) if ops_e.get(n) != ops_p.get(n))
        rows.append((f"{e.id}: op_paths_changed == the analyzer paths whose op list was added/removed/changed",
                     changed == e.op_paths_changed, f"measured {sorted(changed)} declared {sorted(e.op_paths_changed)}"))
        inc_e, inc_p = _includes(fw_e), _includes(fw_p)
        rows.append((f"{e.id}: esphome.includes == previous + includes_added", inc_e == inc_p + list(e.includes_added),
                     f"{inc_e} vs {inc_p} + {list(e.includes_added)}"))
        sub_e, sub_p = _substitutions(fw_e), _substitutions(fw_p)
        added = {k: v for k, v in sub_e.items() if k not in sub_p}
        removed = tuple(sorted(k for k in sub_p if k not in sub_e))
        changed = {k: (sub_p[k], sub_e[k]) for k in sub_e if k in sub_p and sub_p[k] != sub_e[k]}
        rows.append((f"{e.id}: substitutions added == declared subst_added key AND value (no undeclared key, none missing, "
                     "no wrong value)", added == dict(e.subst_added), f"measured {added} declared {dict(e.subst_added)}"))
        rows.append((f"{e.id}: existing substitutions removed / changed == declared subst_removed / subst_changed (none silently)",
                     removed == tuple(sorted(e.subst_removed)) and changed == {k: tuple(v) for k, v in e.subst_changed.items()},
                     f"removed {removed} vs {tuple(sorted(e.subst_removed))}; changed {changed} vs {dict(e.subst_changed)}"))
    last = chain.ids()[-1] if chain.entries else ROOT_ID
    exp = chain.expected(last, live)
    rows.append(("live == root + sum of every declared delta (computed root, not typed)", exp == meas[last],
                 str({m: (exp[m], meas[last][m]) for m in METRICS if exp[m] != meas[last][m]})))
    rows.append(("live pinned artifacts == the newest entry's checkpoints (no undeclared edit anywhere)",
                 all(sha(live[p]) == chain.checkpoint(p, last) for p in PINNED),
                 str([p for p in PINNED if sha(live[p]) != chain.checkpoint(p, last)])))
    return rows


# The export carries pub0 and then the post-export (PEX) entries; the private tree carries neither (PEX is public-tree-only).
CHAIN = Chain(ENTRIES + (EXPORT_ENTRIES + POST_EXPORT_ENTRIES if _pub0.EXPORTED else ()))
