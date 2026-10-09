#!/usr/bin/env python3
"""ovw1 transition proofs: ECCO Overview V2 (the dashboard's Overview view rebuilt as nine sections, the Energy Actions card's
presentation-only `layout: tabbed`), declared as the post-export chain entry ovw1 (registry/tests/_ovw1_scope.py), appended after acfg1.

  [0] the declaration: ovw1 is the eighth post-export entry, right after acfg1; no chain-pinned reverter / checkpoint / delta (the
      manifest is untouched); its frozen edits are exactly the nine declared files; the three new enrolments (O3 amendment) at their
      883068d hashes (the README it also edits is a pub0 target); the four added files exist; its fingerprint and every older one are the pinned values, and the closed pre-export
      record is unchanged
  [1] as of ovw1 (the successor pins): every frozen file's sha256; the card folder as of ovw1 (28 Git-tracked files) is pinned
  [2] as of acfg1 (ovw1 undone exactly): every frozen file is byte for byte its pre-ovw1 blob (the acfg1 / esb1 checkpoints, the
      883068d enrolment hashes); the manifest's checkpoint is acfg1's; the folder pins' pub0-era file set is the 26 pre-ovw1 files and
      every card file ovw1 changes is read as of pub0 (its enrolled hash), so the FB-B3 pin value and lic0's folder pins reproduce
      (each of those four suites proves its own value)
  [3] the live Overview: nine `type: grid` sections with the declared spans; S5 = Energy Actions then Known-Good Profile; the hero's
      pinned lines; one System Health card (7 subsystem rows + 8 dongle diagnostics rows); exactly one solar_strip and one daily_compact
      Weather & Solar instance; the Energy Actions block is the pub0-era block plus exactly `layout: tabbed` and its grid_options
      columns; no perform_action / call-service / service: in the Overview; Shadow Recovery exactly twice; the view list and every
      other view byte-identical to acfg1
  [4] the Energy Actions card: the callService sites and (domain, service) pairs equal the as-of-acfg1 source's, and no hunk adds one;
      trackSelection.ts has no regex literal (no slash outside comments) and no runtime import, and calls nothing; `layout` is read only
      by the two `=== "tabbed"` comparisons (every other value takes the pre-existing side-by-side render); both tracks' classifiers run
      unconditionally in _trackSummary()
  [5] exactness: every reverter round-trips and refuses an altered, undone or duplicated hunk; as of acfg1 refuses an undeclared byte

Test-only. No firmware build, no hardware, no Home Assistant, no network, no npm. I/O: reads repo files and `git ls-files`.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
import yaml  # noqa: E402

import _ovw1_scope as O  # noqa: E402
import _scope_chain as sc  # noqa: E402
import _pex  # noqa: E402  (PEX: this suite reads the frozen files AS OF ovw1, AS OF acfg1 and AS OF pub0; it fails closed on an undeclared edit)

FAILURES: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  PASS  {name}")
    else:
        FAILURES.append(name)
        print(f"  FAIL  {name}" + (f" - {detail}" if detail else ""))


def raises(fn) -> bool:
    try:
        fn()
    except AssertionError:
        return True
    return False


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def at(rel: str, entry_id: str, text: str | None = None) -> str:
    """`rel` (LF text; the live file unless `text` is given) with every post-export entry newer than `entry_id` undone exactly."""
    live = _pex.read(rel) if text is None else text   # PEX: the live file as the suites read it
    return _pex.as_of(rel, entry_id, live)   # PEX: fails closed on any undeclared edit


def at_or_none(rel: str, entry_id: str):
    """at(), or None when PEX refuses (an undeclared edit): reported as a FAIL below, never a crash."""
    try:
        return at(rel, entry_id)
    except AssertionError:
        return None


class TaggedSafeLoader(yaml.SafeLoader):
    """Tolerates Home Assistant custom !tags (the dashboard carries none today, but the suites read it this way)."""


def _construct_unknown(loader, _tag_suffix, node):
    if isinstance(node, yaml.ScalarNode):
        return loader.construct_scalar(node)
    if isinstance(node, yaml.SequenceNode):
        return loader.construct_sequence(node)
    return loader.construct_mapping(node)


TaggedSafeLoader.add_multi_constructor("", _construct_unknown)


def walk(node):
    if isinstance(node, dict):
        yield node
        for v in node.values():
            yield from walk(v)
    elif isinstance(node, list):
        for v in node:
            yield from walk(v)


CARD = "frontend/ecco-energy-actions-card/"
DASH, VERSION = O.DASHBOARD_REL, O.VERSION_REL
SRC, CONFIG, README, DIST = O.CARD_SRC_REL, O.CARD_CONFIG_REL, O.CARD_README_REL, O.BUNDLE_REL
SUITES = (O.SUITE_FBP_REL, O.SUITE_SCU_REL, O.SUITE_FRD_REL)
FROZEN_FILES = (DASH, VERSION, SRC, CONFIG, README, DIST, *SUITES)
NEW_ENROLLED = (SRC, CONFIG)   # the README is a pub0 target (frozen through the manifest), not an enrolment
ADDED = {"registry/tests/_ovw1_scope.py", "registry/tests/test_ovw1_transition.py",
         CARD + "src/trackSelection.ts", CARD + "test/trackSelection.test.ts"}

# The successor pins (ovw1 @ public main 42baa20 + this change; LF text).
OVW1_FINGERPRINT = "1a56962c110b98a28537a649998b40f9c2635176de756ac505eda0513a972f3a"
# The seven post-export fingerprints recorded on main before ovw1, in chain order (pex0 first, acfg1 last); an older entry can never
# be rewritten. Kept by position: each entry's own suite owns the ledger of files that name it.
OLDER_FINGERPRINTS = (
    "c91d3a5834cef6b69f692bd8c301a478138ac7627b29c53a0a0e35cac29b36f8",
    "313f73eadd0c104cd1e81f35690fac52e0b065b0eef3eed35c9718f965baeb6c",
    "46cf76256da78b24e2fd59692f0bf126eba059352c37006542708c64b38e8f8c",
    "02d4bf53955acc3788c9df5972327bb62d5af028d8b9e46e0aa872c4fc94b0a0",
    "ee161454359816ee40e44c04dd0c009d0b96838ba912bcf606975bcb0049d528",
    "462f44d25c0c5dc7aa9df86c8865f6474b56193d80553804daaf3e3ff34feb5d",
    "43331ffff6819253b6106e1af9056253aa5105cec3b77be0a2c3b6ccf9554286",
)
HISTORICAL_CHAIN_SHA = "d61b7b6a231006b2913ce62733f07df562056cffd6b633b5d8035ec06217dd4e"
# sha256 (LF) of every frozen file AFTER ovw1 (the entry's frozen checkpoints, restated here as the successor pins).
AFTER = {
    DASH: "8f0da9f9ed3597e3128325b04cd54ca11698512d7f52c6d9598ec1ff26ac5c2e",
    VERSION: "04b7b66b85688f7a40ab0d893505de65e45a0d283a93eae80c3fcdab4aad9c7a",
    SRC: "d8be18eea439db76badc0f3a25980b9582c6b971aa61fdc9548b6cd992bb35da",
    CONFIG: "2e6d66839e7ac0a6714f2734a9287dffcc4835bc9c49983e1ab3496be40549a8",
    README: "520c5f5f1ffa83d21af0a68e15eecfc5c4e062ed17e379276a79d8ade48a1adb",
    DIST: "2f5f6f9bbd8fa05347a7ca63a4dab94b6c533a69e01ad679dec4927c7952fa01",
    O.SUITE_FBP_REL: "969dd6fa2f20324f4d7022740a6d1c14b52af79247260a6bed084068553e526e",
    O.SUITE_SCU_REL: "ebc277766e17c57d599ba06a7a2193310261520f29bbb0648de2bc3c3d4e8340",
    O.SUITE_FRD_REL: "02f43e171584696e6749048d8e4add21fe0e80efb18a60ce8653b2adae54304b",
}
# sha256 (LF) of every frozen file BEFORE ovw1: public main @ 42baa20 (`git show 42baa20:<path>`): the acfg1 checkpoints of the dashboard,
# VERSION.yaml and two suites, esb1's of the bundle and the third suite, and the 883068d hashes of the three newly enrolled files.
BEFORE = {
    DASH: "afae2a2b2e206355474d553567127546568ece6c43df83dc3ea57a117b1d2cac",
    VERSION: "f47a36ba97fa5869891872b7e563bdf7600983ed2befae2b7c6fc5cfcc9bd3f1",
    SRC: "1aa8b65fe658545616411da8891c6f19ac39127faf6d60e49c395e0311e877b7",
    CONFIG: "3628471e4d4e957b49cdbaf17d3e325a80679dc8526e3f620f1f4b4fb2da96ba",
    README: "823cb754887d1cc3f6ff37b4be25ba7951fc8199d18c7add26369f9eb3efd6bd",
    DIST: "7674bc1acc13b5a305d37b6e0055b200cbb86c172395e07cb286567a76c07d2d",
    O.SUITE_FBP_REL: "97800ea41b530243922385b7193bf67c0fde051ad1235b2965da159d8c0c3301",
    O.SUITE_SCU_REL: "25d13a54fd0bda3a67ef2835e3da50f41a1f5f98b7b00e0142bdb166e35df4fe",
    O.SUITE_FRD_REL: "7fefccfd13dc31b85a2cc3245d4e4f7f8a7e3ab2cdd258449e42c85677a727ae",
}
# The two newly enrolled card files' pub0 state: their sha256 (LF) at public main 883068d, restated here independently of _pex.ENROLLED.
ENROLLED_883068D = {SRC: BEFORE[SRC], CONFIG: BEFORE[CONFIG]}
# The card folder as of ovw1: sha256 over every Git-tracked file (repository-relative path, then its LF text as of ovw1).
FOLDER_OVW1_SHA256 = "e36f48ec1962f27e57974bacae0a904a5505cc65b0ca9f25ed8057f4542e9526"
SPANS = [4, 4, 3, 1, 2, 2, 3, 1, 4]
HERO_PINNED = (   # the hero's JavaScript lines the FB-B3 / FB-C3 suites pin, kept verbatim (test_ecco_fallback_packages.py [14])
    "get('sensor.ecco_supervision_status')", "get('sensor.ecco_fallback_status')", "const required =", "const hardAttention",
    "sup === 'Lost'", "pill('RECOVERY'", "pill('SUPERVISION', supChip[0], supChip[1])", "pill('FALLBACK', fbChip[0], fbChip[1])",
    "'Awaiting Heartbeat'", "'Shadow Recovery': ['SHADOW', 'warn']", "MONITORING ONLY", "SYSTEMS NOMINAL", "STATUS PARTIAL",
    "FREE POWER ACTIVE", "OPERATION IN PROGRESS", "DUMP TO GRID ACTIVE",
)
HEALTH_ROWS = (   # the seven subsystem rows, verbatim
    "['Manual Write', read('sensor.ecco_health_manual_write_system')]", "['RTC', read('sensor.ecco_health_rtc')]",
    "['Free Power', read('sensor.ecco_health_free_power')]", "['Configuration', read('sensor.ecco_health_configuration')]",
    "['Inverter Telemetry', read('sensor.ecco_health_inverter_telemetry')]", "['Supervision', read('sensor.ecco_health_supervision')]",
    "['Fallback', read('sensor.ecco_health_fallback')]",
)
EA_HEAD = "          - type: custom:ecco-energy-actions-card\n"
EA_END = "          # ---- KNOWN-GOOD PROFILE (FB-B3; READ-ONLY tile) ----"
EA_LAYOUT_LINE = "            layout: tabbed\n"
EA_COLUMNS_OLD, EA_COLUMNS_NEW = "              columns: 48\n", "              columns: full\n"
WS = "custom:ecco-weather-solar-card"

CHAIN = sc.CHAIN
POST = sc.POST_EXPORT_ENTRIES
OVW1 = CHAIN.entry("ovw1")

# ===========================================================================
print("[0] the declaration")
# ===========================================================================
ids = [e.id for e in POST]
check("ovw1 is the eighth post-export entry, appended right after acfg1 (the seventh; pex0 is the first)",
      "ovw1" in ids and CHAIN.prev_id("ovw1") == "acfg1" and ids.index("ovw1") == 7 and ids[0] == "pex0" and ids[6] == "acfg1"
      and CHAIN.ids()[-1] == "ovw1", str(ids))
check("ovw1 carries no chain-pinned change: no reverter / checkpoint / delta / op path / include / substitution / banned token / tag",
      not OVW1.reverts and not OVW1.checkpoints and not OVW1.deltas and not OVW1.op_paths_changed and not OVW1.includes_added
      and not OVW1.subst_added and not OVW1.subst_changed and not OVW1.subst_removed and not OVW1.banned_fw_added
      and not OVW1.banned_files and not OVW1.fbh_includers and not OVW1.tags_declared and not OVW1.tags_promoted)
check("its frozen edits are exactly the nine declared files (dashboard, VERSION.yaml, four card files, three folder-pin suites), each "
      "with its reverter and checkpoint",
      set(OVW1.frozen_reverts) == set(OVW1.frozen_checkpoints) == set(O.FROZEN_REVERTERS) == set(FROZEN_FILES) == set(AFTER) == set(BEFORE)
      and all(OVW1.frozen_reverts[r] is O.FROZEN_REVERTERS[r] for r in O.FROZEN_REVERTERS) and len(FROZEN_FILES) == 9)
check("its frozen checkpoints are the pinned after-values", all(OVW1.frozen_checkpoints[r] == AFTER[r] for r in FROZEN_FILES))
check("the card's source and config are newly enrolled (owner-approved O3 amendment, 2026-10-09) at their 883068d hash, and frozen; "
      "the bundle keeps its esb1 enrolment; the card's README is frozen as a pub0 target, not enrolled",
      all(_pex.ENROLLED.get(r) == h for r, h in ENROLLED_883068D.items()) and set(NEW_ENROLLED) <= _pex.FROZEN
      and _pex.ENROLLED.get(DIST) == "c1bd37deb0dab7ad1933e5276e70388643b14b55ed57842f055eadfb1933c207" and len(_pex.ENROLLED) == 6
      and README in _pex.FROZEN and README not in _pex.ENROLLED)
check("the dashboard, VERSION.yaml and the three suites are frozen; the suites were edited before by pex0 and esb1",
      {DASH, VERSION, *SUITES} <= _pex.FROZEN and set(SUITES) == set(CHAIN.entry("pex0").frozen_reverts)
      and set(SUITES) <= set(CHAIN.entry("esb1").frozen_reverts))
check("ovw1 declares the four files it adds (its scope module, this suite, the track selection module and its tests), and each exists",
      OVW1.added_files == O.ADDED_FILES == ADDED and all((ROOT / f).is_file() for f in OVW1.added_files))
check("ovw1's fingerprint is the pinned value; every older post-export fingerprint is its recorded value (none rewritten)",
      OVW1.fingerprint == OVW1_FINGERPRINT and tuple(e.fingerprint for e in POST[:7]) == OLDER_FINGERPRINTS, OVW1.fingerprint)
check("ovw1's fingerprint is the sha256 of its canonical record, linked to acfg1's fingerprint",
      _pex.fingerprint(OVW1) == OVW1_FINGERPRINT and _pex.record(OVW1)["parent"] == OLDER_FINGERPRINTS[-1])   # PEX: the hash link
# PEX: the closed pre-export record (root, the twelve ENTRIES and pub0) hashes to its 883068d value
check("the closed pre-export chain record is unchanged", _pex.historical_chain_sha() == _pex.HISTORICAL_CHAIN_SHA == HISTORICAL_CHAIN_SHA)
check("ovw1's base is public main @ 42baa20 (ACFG1 merged)", O.BASE_COMMIT == "42baa20a75b33bbc4e12ca1202eebbccc0257b50")

# ===========================================================================
print("")
print("[1] as of ovw1 (the successor pins)")
# ===========================================================================
TXT = {r: at_or_none(r, "ovw1") for r in FROZEN_FILES}
check("every frozen file ovw1 edits is exactly its declared ovw1 state (live == newest; PEX refuses an undeclared edit)",
      all(TXT[r] is not None for r in FROZEN_FILES), str([r for r in FROZEN_FILES if TXT[r] is None]))
for r in FROZEN_FILES:   # the rest of this suite reads the live text where PEX refused, so every later check still runs and fails loudly
    if TXT[r] is None:
        TXT[r] = _pex.read(r)   # PEX: fallback after a refusal
check("every frozen file as of ovw1 is its pinned sha256", all(sha(TXT[r]) == AFTER[r] for r in FROZEN_FILES),
      str({r: sha(TXT[r])[:16] for r in FROZEN_FILES if sha(TXT[r]) != AFTER[r]}))
tracked = sorted(f for f in subprocess.run(["git", "ls-files", "-z", "--", CARD], cwd=str(ROOT), capture_output=True)
                 .stdout.decode("utf-8").split("\0") if f)
folder = hashlib.sha256()
for rel in tracked:
    folder.update(rel.encode())
    folder.update((TXT[rel] if rel in TXT else (ROOT / rel).read_bytes().replace(b"\r\n", b"\n").decode("utf-8")).encode("utf-8"))
check("the card folder as of ovw1 is pinned (28 Git-tracked files: path and LF text; the two added files are tracked)",
      len(tracked) == 28 and {SRC, CONFIG, README, DIST, CARD + "src/trackSelection.ts", CARD + "test/trackSelection.test.ts"} <= set(tracked)
      and folder.hexdigest() == FOLDER_OVW1_SHA256, f"{len(tracked)} {folder.hexdigest()}")

# ===========================================================================
print("")
print("[2] as of acfg1 (ovw1 undone exactly) and the pub0-era folder pins")
# ===========================================================================
P1 = {r: at_or_none(r, "acfg1") for r in FROZEN_FILES}
P0 = {r: at_or_none(r, "pub0") for r in FROZEN_FILES}
check("ovw1 undone exactly: every frozen file as of acfg1 is byte for byte its 42baa20 blob (sha256)",
      all(P1[r] is not None and sha(P1[r]) == BEFORE[r] for r in FROZEN_FILES),
      str({r: (sha(P1[r])[:16] if P1[r] is not None else None) for r in FROZEN_FILES if P1[r] is None or sha(P1[r]) != BEFORE[r]}))
check("the chain's declared state as of acfg1 is that same blob for every file (the checkpoints agree with the pins)",
      all(_pex.checkpoint(r, "acfg1") == BEFORE[r] for r in FROZEN_FILES))   # PEX: the declared checkpoint before ovw1
check("as of pub0 the two newly enrolled files are their 883068d state, the README is its pub0 manifest result (the same 883068d hash), "
      "and no entry before ovw1 edited them (as of acfg1 == as of pub0)",
      all(P0[r] is not None and sha(P0[r]) == ENROLLED_883068D[r] and P0[r] == P1[r] for r in NEW_ENROLLED)
      and P0[README] is not None and sha(P0[README]) == _pex.base(README) == BEFORE[README] and P0[README] == P1[README])   # PEX: the manifest result
check("as of pub0 the bundle is its enrolled 883068d hash (lic0's post-lic0 bundle) and as of acfg1 it is esb1's bundle",
      P0[DIST] is not None and sha(P0[DIST]) == _pex.ENROLLED[DIST] and sha(P1[DIST]) == CHAIN.entry("esb1").frozen_checkpoints[DIST])
check("the manifest is untouched: its checkpoint as of ovw1 is acfg1's", CHAIN.checkpoint(sc.HA_MANIFEST, "ovw1") == CHAIN.checkpoint(sc.HA_MANIFEST, "acfg1")
      == CHAIN.entry("acfg1").checkpoints[sc.HA_MANIFEST])
added = _pex.post_export_added()   # PEX: the files a post-export entry declares as added (the folder pins skip them)
pub0_set = [f for f in tracked if f not in added]
check("the folder pins' pub0-era file set is the 26 pre-ovw1 files: exactly the two added card files are skipped",
      len(pub0_set) == 26 and set(tracked) - set(pub0_set) == {CARD + "src/trackSelection.ts", CARD + "test/trackSelection.test.ts"})
PUB0_STATE = {**ENROLLED_883068D, README: BEFORE[README], DIST: _pex.ENROLLED[DIST]}   # the bundle's pub0 state is lic0's bundle (esb1 came later)
check("every tracked card file ovw1 changes is frozen, so the pins read it as of pub0: its 883068d hash (the pin VALUE 57c97982... and "
      "lic0's folder pins are reproduced by their own suites, which this change does not re-hash)",
      all(r in _pex.FROZEN and P0[r] is not None and sha(P0[r]) == PUB0_STATE[r] for r in (SRC, CONFIG, README, DIST)))
check("each suite keeps the FB-B3 folder pin value, still routes a frozen card file as of pub0 (esb1) and now skips the added files (one "
      "`PEX (ovw1)` routing each)",
      all(TXT[r].count("57c9798206d8a1850047474e9bdf89401523b03de89a2562a0cc18d81ac17471") == 1
          and TXT[r].count("if rel in _pex.FROZEN else _fe_lf") == 1 and TXT[r].count("if rel in _pex.post_export_added():") == 1
          and TXT[r].count("PEX (ovw1)") == 1 for r in SUITES))

# ===========================================================================
print("")
print("[3] the live Overview")
# ===========================================================================
dash = TXT[DASH]
doc = yaml.load(dash, Loader=TaggedSafeLoader)
views = doc["views"]
ov = views[0]
secs = ov.get("sections") or []
check("the Overview is the first view, a sections view of nine `type: grid` sections with the declared column spans",
      ov.get("title") == "Overview" and ov.get("type") == "sections" and len(secs) == 9
      and [s.get("column_span") for s in secs] == SPANS and all(s.get("type") == "grid" for s in secs), str([s.get("column_span") for s in secs]))
s5 = secs[4].get("cards") or [] if len(secs) == 9 else []
check("S5 is the Energy Actions card (layout: tabbed) followed directly by the Known-Good Profile bar, and nothing else",
      len(s5) == 2 and s5[0].get("type") == "custom:ecco-energy-actions-card" and s5[0].get("layout") == "tabbed"
      and s5[1].get("name") == "Known-Good Profile" and s5[1].get("entity") == "sensor.ecco_fallback_status"
      and s5[1].get("tap_action") == {"action": "more-info"}, str([c.get("type") for c in s5]))
hero = [n for n in walk(ov) if isinstance(n, dict) and n.get("name") == "ECCO Pro" and isinstance(n.get("custom_fields"), dict)]
hero_js = hero[0]["custom_fields"].get("body", "") if len(hero) == 1 else ""
check("one hero (S1, the status banner) whose JavaScript keeps every pinned line, each exactly once (STATUS PARTIAL twice: headline and subline)",
      len(hero) == 1 and secs[0].get("cards", [{}])[0] is hero[0]
      and all(hero_js.count(s) == (2 if s == "STATUS PARTIAL" else 1) for s in HERO_PINNED),
      str([s for s in HERO_PINNED if hero_js.count(s) != (2 if s == "STATUS PARTIAL" else 1)]))
check("the hero's headline logic reads the three Dump to Grid lease states (D4: operation in progress, active, snapshot valid) and keeps "
      "the FINAL chip vocabulary with no Applying word",
      all(f"get('binary_sensor.ecco_clock_dongle_dump_to_grid_{k}')" in hero_js for k in ("operation_in_progress", "active", "snapshot_valid"))
      and "'DUMP TO GRID ACTIVE'" in hero_js and hero_js.count("Shadow Recovery") == 1 and "Applying" not in hero_js
      and all(w in hero_js for w in ["'Ready'", "'Drifted'", "'Not Captured'", "'Invalidated'", "'Blocked'", "'Healthy'", "'Recovering'",
                                     "'Suspect'", "'Lost'"]))
_req_line = next((l for l in hero_js.splitlines() if l.strip().startswith("const required =")), "")
_hard = hero_js[hero_js.index("const hardAttention"):hero_js.index("const busy")] if "const hardAttention" in hero_js and "const busy" in hero_js else ""
check("the hero reads both recovery-state sensors STRUCTURALLY (firmware enums: NONE and ACCEPTED are settled, anything else is a recovery "
      "condition, no status-text matching): both count as unavailable inputs with their own test (NONE is the idle value), both raise ATTENTION and turn the RECOVERY chip",
      all(f"get('sensor.ecco_clock_dongle_{k}_recovery_state')" in hero_js for k in ("free_power", "dump_to_grid"))
      and "freeRecovery" not in _req_line and "dumpRecovery" not in _req_line
      and "const hasUnknown = required.some(unknown) || recoveryUnavailable(freeRecovery) || recoveryUnavailable(dumpRecovery);" in hero_js
      and "const recoveryUnavailable = v => ['unknown','unavailable',''].includes(String(v).toLowerCase());" in hero_js
      and "freeRecoveryAttention ||" in _hard and "dumpRecoveryAttention ||" in _hard
      and "const recoverySettled = v => v === 'NONE' || String(v).startsWith('ACCEPTED');" in hero_js
      and "!freeRecoveryAttention && !dumpRecoveryAttention" in hero_js
      and not re.search(r"(START|VERIFY) ?FAILED|RECOVERY REQUIRED|OPERATOR DECISION|RESTORE BLOCKED|DEFERRED", hero_js))

# The hero's headline matrix, executed with Node (the template is plain JavaScript over a `states` map; no Home Assistant needed).
_HERO_IDS = sorted(set(re.findall(r"get\('([a-z_]+\.[a-z0-9_]+)'\)", hero_js)))


def _default(eid: str) -> str:
    if eid.endswith(("telemetry_online", "configuration_online", "ntp_synced", "raw_cache_valid")):
        return "on"
    if eid.startswith("binary_sensor."):
        return "off"
    if eid.startswith("sensor.ecco_health_"):
        return "HEALTHY"
    if eid.endswith("inverter_system_state"):
        return "normal"
    if eid.endswith("inverter_warning"):
        return "00000000"
    if eid.endswith("inverter_fault"):
        return "0000000000000000"
    if eid.endswith("_recovery_state"):
        return "NONE"
    if eid == "sensor.ecco_supervision_status":
        return "Healthy"
    if eid == "sensor.ecco_fallback_status":
        return "Ready"
    return "2026-10-09 06:57:20"


def _states(over: dict) -> dict:
    base = {eid: _default(eid) for eid in _HERO_IDS}
    base.update(over)
    return {eid: {"state": v, "attributes": {}} for eid, v in base.items()}


_D = "sensor.ecco_clock_dongle_dump_to_grid_recovery_state"
_F = "sensor.ecco_clock_dongle_free_power_recovery_state"
_SCENARIOS = [
    ("nominal", {}, "SYSTEMS NOMINAL"),
    ("dump active", {"binary_sensor.ecco_clock_dongle_dump_to_grid_active": "on"}, "DUMP TO GRID ACTIVE"),
    ("dump transaction in flight", {"binary_sensor.ecco_clock_dongle_dump_to_grid_operation_in_progress": "on"}, "OPERATION IN PROGRESS"),
    ("dump restore obligation (snapshot pending, idle)", {"binary_sensor.ecco_clock_dongle_dump_to_grid_snapshot_valid": "on"}, "ATTENTION"),
    ("dump recovery LOCKED (metadata unavailable; no snapshot flag)", {_D: "LOCKED - durable recovery metadata unavailable"}, "ATTENTION"),
    ("dump recovery LOCKED (operator decision)", {_D: "LOCKED - operator decision required"}, "ATTENTION"),
    ("dump recovery NEITHER (fail-closed default)", {_D: "NEITHER (fail-closed default) - repeated restore verify mismatch"}, "ATTENTION"),
    ("dump recovery PENDING at boot", {_D: "PENDING - outstanding snapshot found at boot; automatic restore expected"}, "ATTENTION"),
    ("dump recovery ACCEPTED (settled)", {_D: "ACCEPTED - operator chose to keep the live inverter state"}, "SYSTEMS NOMINAL"),
    ("dump active while a recovery condition is latched (attention wins)",
     {"binary_sensor.ecco_clock_dongle_dump_to_grid_active": "on", _D: "LOCKED - operator decision required"}, "ATTENTION"),
    ("free power active", {"binary_sensor.ecco_clock_dongle_free_power_active": "on"}, "FREE POWER ACTIVE"),
    ("free power recovery LOCKED_NEITHER", {_F: "LOCKED_NEITHER"}, "ATTENTION"),
    ("free power recovery LOCKED_ORIGINAL", {_F: "LOCKED_ORIGINAL"}, "ATTENTION"),
    ("free power accept running", {_F: "ACCEPT_RUNNING"}, "ATTENTION"),
    ("free power restore obligation", {"binary_sensor.ecco_clock_dongle_free_power_snapshot_valid": "on"}, "ATTENTION"),
    ("dump recovery state unavailable", {_D: "unavailable"}, "STATUS PARTIAL"),
    ("free power recovery state unknown", {_F: "unknown"}, "STATUS PARTIAL"),
    ("supervision lost", {"sensor.ecco_supervision_status": "Lost"}, "ATTENTION"),
    ("inverter fault", {"sensor.ecco_clock_dongle_ecco_inverter_fault": "0000000000000001"}, "ATTENTION"),
]
_NODE_SCRIPT = (
    "const inp = JSON.parse(require('fs').readFileSync(0, 'utf8'));"
    "const fn = new Function('states', inp.body);"
    "const out = {};"
    "for (const s of inp.scenarios) { const html = String(fn(s.states));"
    "  const m = html.match(/STATUS PARTIAL|DUMP TO GRID ACTIVE|FREE POWER ACTIVE|OPERATION IN PROGRESS|SYSTEMS NOMINAL|ATTENTION/);"
    "  out[s.name] = m ? m[0] : null; }"
    "process.stdout.write(JSON.stringify(out));"
)
_node = shutil.which("node")
check("Node is available to execute the hero's headline matrix (the dashboard's JavaScript is plain; the Weather & Solar suite needs Node too)",
      bool(_node), str(_node))
_got: dict = {}
if _node and hero_js.strip().startswith("[[[") and hero_js.strip().endswith("]]]"):
    _body = hero_js.strip()[3:-3]
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as _tf:
        _tf.write(_NODE_SCRIPT)
    try:
        _run = subprocess.run([_node, _tf.name], input=json.dumps({"body": _body, "scenarios": [{"name": n, "states": _states(o)} for n, o, _e in _SCENARIOS]}),
                              capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
        _got = json.loads(_run.stdout) if _run.returncode == 0 and _run.stdout else {"<node>": (_run.stderr or "")[:300]}
    finally:
        Path(_tf.name).unlink(missing_ok=True)
_bad = [(n, e, _got.get(n)) for n, _o, e in _SCENARIOS if _got.get(n) != e]
check(f"hero headline matrix ({len(_SCENARIOS)} scenarios, executed with Node over a states map): every Dump to Grid / Free Power lease, "
      "restore-obligation and recovery-state case raises its headline, attention outranks an active lease, the settled values stay "
      "SYSTEMS NOMINAL, an unavailable recovery sensor is STATUS PARTIAL", not _bad and bool(_got), str(_bad[:4] or _got))

health = [n for n in walk(ov) if isinstance(n, dict) and n.get("name") == "System Health"]
health_js = health[0].get("custom_fields", {}).get("health", "") if len(health) == 1 else ""
diag = health_js[health_js.find("const diag = ["):health_js.find("];", health_js.find("const diag = ["))] if "const diag = [" in health_js else ""
diag_rows = re.findall(r"(?m)^\s*\['([^']+)', ", diag)
check("exactly one System Health card (S9): the seven subsystem rows verbatim, the DEGRADED mapping and tone, and eight dongle diagnostics "
      "rows (Telemetry, Configuration, NTP Sync, RTC Stall, Clock Error, Wi-Fi, Read Failures, Correction Failures): 15 rows",
      len(health) == 1 and secs[8].get("cards", [{}])[0] is health[0] and all(health_js.count(r) == 1 for r in HEALTH_ROWS)
      and "['HEALTHY', 'DEGRADED', 'WARNING', 'FAILED'].includes(s)" in health_js and "s === 'DEGRADED' ? '#66b3ff'" in health_js
      and len(diag_rows) == 8 and diag_rows[:5] == ["Telemetry", "Configuration", "NTP Sync", "RTC Stall", "Clock Error"]
      and diag_rows[6:] == ["Read Failures", "Correction Failures"] and "reason_codes" in health_js, str(diag_rows))
ws = [c for s in secs for c in (s.get("cards") or []) if isinstance(c, dict) and c.get("type") == WS]
check("exactly one solar_strip (S2) and one daily_compact (S4) Weather & Solar instance in the Overview, each a type / layout / "
      "grid_options (/ daily_days) mapping with no entity id typed in",
      [c.get("layout") for c in ws] == ["solar_strip", "daily_compact"] and ws[0] in (secs[1].get("cards") or []) and ws[1] in (secs[3].get("cards") or [])
      and all(set(c) <= {"type", "layout", "grid_options", "daily_days"} and c.get("grid_options") == {"columns": "full", "rows": "auto"} for c in ws)
      and ws[1].get("daily_days") == 7, str(ws))
ov_a, ov_b = dash.index("  - title: Overview\n"), dash.index("  - title: Weather & Solar\n")
ov_text = dash[ov_a:ov_b]
ea_live = ov_text[ov_text.index(EA_HEAD):ov_text.index(EA_END)]
ea_pub0 = P0[DASH][P0[DASH].index(EA_HEAD):P0[DASH].index(EA_END)] if P0[DASH] is not None and EA_HEAD in P0[DASH] else ""
check("the Energy Actions block is the pub0-era block plus exactly `layout: tabbed` and its grid_options columns (48 -> full); as of acfg1 "
      "the block was still the pub0-era one",
      bool(ea_pub0) and dash.count(EA_HEAD) == 1 and ea_live.count(EA_LAYOUT_LINE) == 1 and ea_live.count(EA_COLUMNS_NEW) == 1
      and ea_live.replace(EA_LAYOUT_LINE, "", 1).replace(EA_COLUMNS_NEW, EA_COLUMNS_OLD, 1) == ea_pub0
      and P1[DASH] is not None and P1[DASH][P1[DASH].index(EA_HEAD):P1[DASH].index(EA_END)] == ea_pub0)
check("no perform_action / call-service / service: anywhere in the Overview, the Energy Actions block included; tap actions are none or more-info",
      not any(w in ov_text for w in ("perform_action", "call-service", "service:"))
      and {n.get("tap_action", {}).get("action") for n in walk(ov) if isinstance(n, dict) and isinstance(n.get("tap_action"), dict)} <= {"none", "more-info"})
ov_dump = yaml.dump(ov)
check("the Overview spells Shadow Recovery exactly twice (hero map, Known-Good Profile tone map) and no shadow-check entity or heading",
      ov_dump.count("Shadow Recovery") == 2 and "ecco_shadow_" not in ov_dump and "SHADOW CHECK" not in ov_dump
      and "Failback shadow evaluator" not in ov_dump)
check("only the already-installed custom card types are used in the Overview",
      {n.get("type") for n in walk(ov) if isinstance(n, dict) and str(n.get("type", "")).startswith("custom:")}
      <= {"custom:button-card", "custom:ecco-energy-flow-card", "custom:ecco-energy-actions-card", WS, "custom:apexcharts-card"})
doc1 = yaml.load(P1[DASH], Loader=TaggedSafeLoader) if P1[DASH] is not None else {"views": []}
check("the view list is unchanged and every view but the Overview is identical to acfg1's (YAML structure)",
      [v.get("title") for v in views] == [v.get("title") for v in doc1["views"]] and len(views) == 11
      and all(yaml.dump(views[i]) == yaml.dump(doc1["views"][i]) for i in range(1, len(views))))
def _flow_card(view):
    return next((c for s in (view.get("sections") or []) for c in (s.get("cards") or [])
                 if isinstance(c, dict) and c.get("type") == "custom:ecco-energy-flow-card"), None)


def _sans_grid(card):
    return {k: v for k, v in card.items() if k != "grid_options"} if isinstance(card, dict) else None


_flow_now, _flow_then = _flow_card(ov), (_flow_card(doc1["views"][0]) if doc1["views"] else None)
check("the Energy Flow card's configuration is byte-for-byte acfg1's (entities, animation, today strip, inverter details, features, format, "
      "card_mod): only its grid placement changed (columns 32 -> full; rows auto both)",
      _flow_now is not None and _flow_then is not None and _sans_grid(_flow_now) == _sans_grid(_flow_then)
      and _flow_then.get("grid_options") == {"columns": 32, "rows": "auto"} and _flow_now.get("grid_options") == {"columns": "full", "rows": "auto"}
      and (_flow_now.get("features") or {}).get("animate_flow") is True and "inverter_details" in _flow_now and "today" in _flow_now,
      str({k for k in set(_sans_grid(_flow_now) or {}) | set(_sans_grid(_flow_then) or {})
           if (_sans_grid(_flow_now) or {}).get(k) != (_sans_grid(_flow_then) or {}).get(k)}))
check("the dashboard reverter is two pairs: the v7.20.0 header note and the whole Overview view block (title line to the line before the "
      "Weather & Solar view); the first line of the file and `&ecco_card_mod` are untouched",
      len(O.DASHBOARD_EDITS) == 2 and O.DASHBOARD_EDITS[1][0].startswith("  - title: Overview\n") and O.DASHBOARD_EDITS[1][1] == ov_text
      and "# v7.20.0 (OVW1, STAGED / NOT LIVE-PROVEN)" in O.DASHBOARD_EDITS[0][1] and "v7.20.0" not in O.DASHBOARD_EDITS[0][0]
      and dash.startswith("# ECCO Pro Dashboard v7.16.0 - ") and dash.count("&ecco_card_mod") == 1)
ver = yaml.safe_load(TXT[VERSION])
check("VERSION.yaml: dashboard 7.20.0, staged (tested_in_home_assistant stays false), the 7.19.0 record kept; one pair",
      ver["current"]["dashboard"]["version"] == "7.20.0" and ver["current"]["dashboard"].get("tested_in_home_assistant") is False
      and "v7.19.0 (ACFG1)" in TXT[VERSION] and len(O.VERSION_EDITS) == 1, str(ver["current"]["dashboard"]))

# ===========================================================================
print("")
print("[4] the Energy Actions card")
# ===========================================================================
src, src1 = TXT[SRC], P1[SRC] or ""
PAIR = re.compile(r'_callService\("(\w+)",\s*(?:"(\w+)"|\w+ \? "(\w+)" : "(\w+)")')


def pairs(text: str) -> set:
    return {(m[0], s) for m in PAIR.findall(text) for s in m[1:] if s}


def sites(text: str) -> list:
    return sorted(re.findall(r"_callService(?:Obj)?\(.*", text))


check("the card's callService sites and (domain, service) pairs are unchanged versus the as-of-acfg1 source (no new service call)",
      bool(src1) and src.count("callService") == src1.count("callService") and sites(src) == sites(src1) and pairs(src) == pairs(src1)
      and pairs(src) == {("button", "press"), ("switch", "turn_on"), ("switch", "turn_off"), ("number", "set_value")},
      f"{src.count('callService')} vs {src1.count('callService')}; {sorted(pairs(src) ^ pairs(src1))}")
check("no ovw1 hunk of the source adds a callService, a hass member read or a regex literal",
      all(a.count("callService") == b.count("callService") and a.count("hass.") == b.count("hass.")
          and not re.search(r"(?<![\w)\]])/(?![/*\s])[^/\n]*/[gimsuy]*", a.replace(b, "")) for b, a in O.CARD_SRC_EDITS))
sel = src[src.find("private _selectTrack("):src.find("private _renderTabbed(")]
check("the tab click handler (_selectTrack) only clears both pending End & Restore confirmations and sets the track: no service call, no "
      "entity write", bool(sel) and "callService" not in sel and "hass" not in sel and sel.count("this._track = track;") == 1
      and "this._confirmEndRestore = false;" in sel and "this._confirmEndDump = false;" in sel)
summary = src[src.find("private _trackSummary("):src.find("private _selectTrack(")]
check("both tracks' classifiers run unconditionally in _trackSummary() (before any branch), so the hidden track is never short-circuited",
      bool(summary) and 0 < summary.index("this._freePowerVisualStateForInterlock();") < summary.index("this._dumpVisualStateForInterlock();")
      < summary.index("if ") and "isInterlocked(fpVisual, dumpVisual)" in summary and "isInterlocked(dumpVisual, fpVisual)" in summary)
check("`layout` is read only by the two `=== \"tabbed\"` comparisons (willUpdate, render): any other value takes the pre-existing "
      "side-by-side render path; config.ts types it as optional \"side-by-side\" | \"tabbed\"",
      len(re.findall(r"_config\??\.layout\b", src)) == 2 and src.count('layout === "tabbed"') == 2
      and 'layout?: "side-by-side" | "tabbed";' in TXT[CONFIG] and TXT[CONFIG].count("layout") == 1)
ts = _pex.read(CARD + "src/trackSelection.ts")   # PEX: an added file, read live (it is not frozen)
ts_code = re.sub(r"//[^\n]*", "", re.sub(r"/\*.*?\*/", "", ts, flags=re.S))
ts_body = "\n".join(ln for ln in ts_code.split("\n") if not ln.startswith("import "))   # the two `import type` paths carry the only slashes
check("trackSelection.ts has no regex literal (no slash at all outside comments and the import paths), no RegExp, and only `import type` "
      "imports (no runtime import, no Lit, no DOM, no hass, no service call)",
      "/" not in ts_body and "RegExp" not in ts and all(ln.startswith("import type ") for ln in ts.split("\n") if ln.startswith("import"))
      and not re.search(r"\b(hass|callService|fetch|document|window|lit)\b", ts_code))
check("trackSelection.ts exports the pure helpers the card imports, and its tests exist",
      all(f"export function {fn}(" in ts for fn in ("trackRank", "canChooseTrack", "initialTrack", "hiddenTrackAlert", "alertTone", "trackName",
                                                      "hiddenTrackAlertText"))
      and all(fn in src for fn in ("canChooseTrack", "initialTrack", "hiddenTrackAlert", "alertTone", "trackName", "hiddenTrackAlertText"))
      and (ROOT / CARD / "test/trackSelection.test.ts").is_file())
check("the README documents the layout option as presentation-only with side-by-side as the default; one pair",
      "### Layouts" in TXT[README] and "side-by-side" in TXT[README] and "tabbed" in TXT[README] and len(O.CARD_README_EDITS) == 1)
check("the bundle as of ovw1 is the rebuilt bundle (one whole-file pair) that still ends with exactly one Lit licence block",
      len(O.BUNDLE_EDITS) == 1 and TXT[DIST].count("/*! Bundled license information:\n") == 1 and TXT[DIST].rstrip().endswith("*/")
      and "SPDX-License-Identifier: BSD-3-Clause" in TXT[DIST] and "track-alert" in TXT[DIST])

# ===========================================================================
print("")
print("[5] exactness and negative controls")
# ===========================================================================
roundtrip = {DASH: O.add_ovw1_dashboard, VERSION: O.add_ovw1_version, SRC: O.add_ovw1_card_source, CONFIG: O.add_ovw1_card_config,
             README: O.add_ovw1_card_readme, DIST: O.add_ovw1_bundle, O.SUITE_FBP_REL: O.add_ovw1_fallback_packages_suite,
             O.SUITE_SCU_REL: O.add_ovw1_shadow_check_ux_suite, O.SUITE_FRD_REL: O.add_ovw1_fallback_recovery_dashboard_suite}
check("every ovw1 reverter round-trips: applying its pairs to the text as of acfg1 gives the text as of ovw1",
      set(roundtrip) == set(FROZEN_FILES) and all(P1[r] is not None and fn(P1[r]) == TXT[r] for r, fn in roundtrip.items()))
check("every pair is a real change and every reverter exposes its pairs as .edits", all(_pex.exact_pairs(fn.edits) for fn in O.FROZEN_REVERTERS.values()))   # PEX contract
bad = []
for rel, fn in O.FROZEN_REVERTERS.items():
    for before, after in fn.edits:
        k = len(after) // 2
        for m in (TXT[rel].replace(after, after[:k] + ("~" if after[k] != "~" else "^") + after[k + 1:], 1),
                  TXT[rel].replace(after, before, 1), TXT[rel] + after):
            if not raises(lambda m=m, fn=fn: fn(m)):
                bad.append(rel)
check("every reverter refuses each of its hunks altered by one character, already undone, or duplicated", not bad, str(sorted(set(bad))))
check("reading the dashboard as of acfg1 refuses one changed byte in the Overview (it is no declared state), and a second Overview block",
      raises(lambda: at(DASH, "acfg1", dash.replace("  - title: Overview\n", "  - title: Overview \n", 1)))
      and raises(lambda: at(DASH, "acfg1", dash + ov_text)))
check("...and an undeclared byte in the card source, the bundle or VERSION.yaml",
      raises(lambda: at(SRC, "acfg1", TXT[SRC] + " ")) and raises(lambda: at(DIST, "acfg1", "!" + TXT[DIST][1:]))
      and raises(lambda: at(VERSION, "acfg1", TXT[VERSION].replace('"7.20.0"', '"7.21.0"', 1))))
check("ovw1's bundle reverter refuses the esb1-era bundle, and its dashboard reverter the acfg1-era dashboard (their hunks are not ovw1's)",
      P1[DIST] is not None and P1[DASH] is not None and raises(lambda: O.pre_ovw1_bundle(P1[DIST]))
      and raises(lambda: O.pre_ovw1_dashboard(P1[DASH])))

print("")
if FAILURES:
    print(f"FAILED: {len(FAILURES)} check(s)")
    for f in FAILURES:
        print(f"  - {f}")
    sys.exit(1)
print("All ovw1 transition checks passed.")
print("These prove that the Overview V2 rebuild and the Energy Actions card's tabbed layout are declared, exact and reversible, that the "
      "Overview keeps its pinned safety lines and adds no control path, and that the card's service calls are unchanged; they prove "
      "nothing about hardware.")
