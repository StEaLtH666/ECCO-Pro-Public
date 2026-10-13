#!/usr/bin/env python3
"""ovw2 transition proofs: Overview V2.1 (the polish and accuracy pass over the V2 dashboard, dashboard 7.21.1), declared as the
post-export chain entry ovw2 (registry/tests/_ovw2_scope.py), appended after acs0 (re-chained on public main 451f0c24, after acs0).

  [0] the declaration: ovw2 is the fifteenth post-export entry, right after acs0; no chain-pinned reverter / checkpoint / delta (the
      manifest is untouched); its frozen edits are exactly the dashboard and VERSION.yaml, both already frozen (no new enrolment); the
      three added files exist; its fingerprint and every older one are the pinned values, and the closed pre-export record is unchanged
  [1] as of ovw2 (the successor pins): the dashboard's and VERSION.yaml's sha256
  [2] as of acs0 (ovw2 undone exactly): both files are byte for byte their acs0 blobs (public main 451f0c24); the manifest's checkpoint
      is unchanged
  [3] what ovw2 does NOT touch, measured: every view other than the six it edits is byte-identical to ovw1's; the animated Energy Flow
      card, the status banner (S1), the Energy Actions card block and the Known-Good Profile bar are byte-identical; the dashboard has no
      new service call, navigation or toggle handler; dashboard 7.21.1 staged in VERSION.yaml with the 7.21.0 record kept
  [4] exactness: both reverters round-trip and refuse an altered, undone or duplicated hunk, or the wrong-era text; reading the
      dashboard as of acs0 refuses an undeclared byte

The behaviour of the changed dashboard JavaScript (the SOC projection, the new cards, the chart status strip) is proved by
home-assistant/tests/test_ecco_overview_v21.py, which runs the real templates under node.

Test-only. No firmware build, no hardware, no Home Assistant, no network, no npm. I/O: reads repo files.
"""

from __future__ import annotations

import hashlib
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
import yaml  # noqa: E402

import _ovw2_scope as O  # noqa: E402
import _scope_chain as sc  # noqa: E402
import _pex  # noqa: E402  (PEX: this suite reads the frozen files AS OF ovw2 and AS OF ovw1; it fails closed on an undeclared edit)

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


DASH, VERSION = O.DASHBOARD_REL, O.VERSION_REL
FROZEN_FILES = (DASH, VERSION)
LAST_EDITOR = {DASH: "fsw1", VERSION: "fe1"}   # the last entry before ovw2 to edit each file (its checkpoint is the pin)
ADDED = {"registry/tests/_ovw2_scope.py", "registry/tests/test_ovw2_transition.py", "home-assistant/tests/test_ecco_overview_v21.py"}

# The successor pins (ovw2 on public main 451f0c24 + this change; LF text).
OVW2_FINGERPRINT = "034edf1b9a62f36f034f9563988f9e6856c1850e5eb1c022aef630f270c8ac14"
# The fourteen post-export fingerprints recorded before ovw2, in chain order (pex0 first, acs0 last); an older entry can never be rewritten.
OLDER_FINGERPRINTS = (
    "c91d3a5834cef6b69f692bd8c301a478138ac7627b29c53a0a0e35cac29b36f8",
    "313f73eadd0c104cd1e81f35690fac52e0b065b0eef3eed35c9718f965baeb6c",
    "46cf76256da78b24e2fd59692f0bf126eba059352c37006542708c64b38e8f8c",
    "02d4bf53955acc3788c9df5972327bb62d5af028d8b9e46e0aa872c4fc94b0a0",
    "ee161454359816ee40e44c04dd0c009d0b96838ba912bcf606975bcb0049d528",
    "462f44d25c0c5dc7aa9df86c8865f6474b56193d80553804daaf3e3ff34feb5d",
    "43331ffff6819253b6106e1af9056253aa5105cec3b77be0a2c3b6ccf9554286",
    "1a56962c110b98a28537a649998b40f9c2635176de756ac505eda0513a972f3a",
    "211221b095bcdb61b2e7a2cfdd38fb28c871319d46d9acaf6e4f315a690de57e",
    "1e8aa9e4fc0e5907ef7331003eb9cfb427dc0c6925bcb277c85b08e1c7798284",
    "85808fd4ea7af13a57737a12cdff92ab2cf568eab88a53463dec6e9228b3a590",
    "65c52d137893cdde64c8d7a5cd850582093da5a39412a3e2e2d316e82b39bf36",
    "a380efdfa34b1acfc626ceaa47c8faf56347960d5603a9b98c47077ef7439db5",
    "d1a56996a4f82cab796c6d01410630453517faca0131824c95f114f53d28253e",
)
HISTORICAL_CHAIN_SHA = "d61b7b6a231006b2913ce62733f07df562056cffd6b633b5d8035ec06217dd4e"
# sha256 (LF) of the two frozen files AFTER ovw2 (the entry's frozen checkpoints, restated here as the successor pins).
AFTER = {
    DASH: "7191ab0043e78f2c4a74f4e6f0aec3a382ea47de1166f2530b891b3f50157106",
    VERSION: "3fae70d3e7cce2854d4b76be97ede7d9e8531f0a5e10a3b858d205254924894e",
}
# sha256 (LF) of the two frozen files BEFORE ovw2: public main @ 451f0c24 (`git show 451f0c24:<path>`) == fe1's frozen checkpoints.
BEFORE = {
    DASH: "de1d291a4b610152b04371ddf049d691f56e1c763394a724934b833bf01ce6b5",
    VERSION: "c4cf1288a3f37b9f06850009135337d2934c8f99cbe3fd8c34c7a2e24cfa3588",
}
OVERVIEW_SPANS = [4, 4, 3, 1, 2, 2, 3, 1, 4]
EDITED_VIEWS = ["ecco-overview", "ecco-intelligence", "ecco-tariffs", "ecco-control", "ecco-recommended", "ecco-system"]

CHAIN = sc.CHAIN
POST = sc.POST_EXPORT_ENTRIES
OVW2 = CHAIN.entry("ovw2")

# ===========================================================================
print("[0] the declaration")
# ===========================================================================
ids = [e.id for e in POST]
check("ovw2 is the fifteenth post-export entry, appended right after acs0 (the fourteenth; pex0 is the first; ovw1, fe1 and acs0 precede it)",
      "ovw2" in ids and CHAIN.prev_id("ovw2") == "acs0" and ids.index("ovw2") == 14 and ids[0] == "pex0" and ids[7] == "ovw1" and ids[8] == "fe1" and ids[13] == "acs0", str(ids))
check("ovw2 carries no chain-pinned change: no reverter / checkpoint / delta / op path / include / substitution / banned token / tag",
      not OVW2.reverts and not OVW2.checkpoints and not OVW2.deltas and not OVW2.op_paths_changed and not OVW2.includes_added
      and not OVW2.subst_added and not OVW2.subst_changed and not OVW2.subst_removed and not OVW2.banned_fw_added
      and not OVW2.banned_files and not OVW2.fbh_includers and not OVW2.tags_declared and not OVW2.tags_promoted)
check("its frozen edits are exactly the dashboard and VERSION.yaml, each with its reverter and checkpoint",
      set(OVW2.frozen_reverts) == set(OVW2.frozen_checkpoints) == set(O.FROZEN_REVERTERS) == set(FROZEN_FILES) == set(AFTER) == set(BEFORE)
      and all(OVW2.frozen_reverts[r] is O.FROZEN_REVERTERS[r] for r in O.FROZEN_REVERTERS))
check("its frozen checkpoints are the pinned after-values", all(OVW2.frozen_checkpoints[r] == AFTER[r] for r in FROZEN_FILES))
check("both files were already frozen before ovw2 (the dashboard is a pub0 target, VERSION.yaml is enrolled): ovw2 enrols nothing "
      "(ENROLLED is still the six files)",
      DASH in _pex.FROZEN and VERSION in _pex.FROZEN and VERSION in _pex.ENROLLED and DASH not in _pex.ENROLLED and len(_pex.ENROLLED) == 6)
check("ovw2 edits no file ovw1 edited other than those two: the card, bundle and three folder-pin suites are not in its scope",
      set(OVW2.frozen_reverts) < set(CHAIN.entry("ovw1").frozen_reverts))
check("ovw2 declares the three files it adds (its scope module, this suite and the dashboard behaviour suite), and each exists",
      OVW2.added_files == O.ADDED_FILES == ADDED and all((ROOT / f).is_file() for f in OVW2.added_files))
check("ovw2's fingerprint is the pinned value; every older post-export fingerprint is its recorded value (none rewritten)",
      OVW2.fingerprint == OVW2_FINGERPRINT and tuple(e.fingerprint for e in POST[:14]) == OLDER_FINGERPRINTS, OVW2.fingerprint)
check("ovw2's fingerprint is the sha256 of its canonical record, linked to acs0's fingerprint",
      _pex.fingerprint(OVW2) == OVW2_FINGERPRINT and _pex.record(OVW2)["parent"] == OLDER_FINGERPRINTS[-1])   # PEX: the hash link
# PEX: the closed pre-export record (root, the twelve ENTRIES and pub0) hashes to its 883068d value
check("the closed pre-export chain record is unchanged", _pex.historical_chain_sha() == _pex.HISTORICAL_CHAIN_SHA == HISTORICAL_CHAIN_SHA)
check("ovw2's base is public main @ 451f0c24 (FE-1 and FPS1 merged; the accepted V2.1 re-chained on it)", O.BASE_COMMIT == "451f0c246a3e9016ef95bb03d41da64d995fcafd")

# ===========================================================================
print("")
print("[1] as of ovw2 (the successor pins)")
# ===========================================================================
TXT = {r: at_or_none(r, "ovw2") for r in FROZEN_FILES}
check("both frozen files are exactly their declared ovw2 state (live == newest; PEX refuses an undeclared edit)",
      all(TXT[r] is not None for r in FROZEN_FILES), str([r for r in FROZEN_FILES if TXT[r] is None]))
for r in FROZEN_FILES:   # the rest of this suite reads the live text where PEX refused, so every later check still runs and fails loudly
    if TXT[r] is None:
        TXT[r] = _pex.read(r)   # PEX: fallback after a refusal
check("both frozen files as of ovw2 are their pinned sha256", all(sha(TXT[r]) == AFTER[r] for r in FROZEN_FILES),
      str({r: sha(TXT[r])[:16] for r in FROZEN_FILES if sha(TXT[r]) != AFTER[r]}))

# ===========================================================================
print("")
print("[2] as of acs0 (ovw2 undone exactly)")
# ===========================================================================
P1 = {r: at_or_none(r, "acs0") for r in FROZEN_FILES}
check("ovw2 undone exactly: both frozen files as of acs0 are byte for byte their 451f0c24 blob (sha256)",
      all(P1[r] is not None and sha(P1[r]) == BEFORE[r] for r in FROZEN_FILES),
      str({r: (sha(P1[r])[:16] if P1[r] is not None else None) for r in FROZEN_FILES if P1[r] is None or sha(P1[r]) != BEFORE[r]}))
check("the chain's declared state as of acs0 is that same blob for both files (the checkpoints of the last entry to edit each file agree with the pins)",
      all(_pex.checkpoint(r, "acs0") == BEFORE[r] == CHAIN.entry(LAST_EDITOR[r]).frozen_checkpoints[r] for r in FROZEN_FILES))   # PEX: the declared checkpoint before ovw2
check("the manifest is untouched: its checkpoint as of ovw2 is acs0's", CHAIN.checkpoint(sc.HA_MANIFEST, "ovw2") == CHAIN.checkpoint(sc.HA_MANIFEST, "acs0"))

# ===========================================================================
print("")
print("[3] what ovw2 does not touch")
# ===========================================================================
new_doc = yaml.load(TXT[DASH], Loader=TaggedSafeLoader)
old_doc = yaml.load(P1[DASH] or "", Loader=TaggedSafeLoader) or {"views": []}
new_views = {v.get("path"): v for v in new_doc["views"]}
old_views = {v.get("path"): v for v in old_doc["views"]}
check("the view list (paths and order) is unchanged: eleven views", [v.get("path") for v in new_doc["views"]] == [v.get("path") for v in old_doc["views"]]
      and len(new_doc["views"]) == 11, str(list(new_views)))
changed = sorted(p for p in new_views if new_views[p] != old_views.get(p))
check("exactly the six views ovw2 edits differ from acs0's; the other four (Weather & Solar, Inverter / Advanced, Fallback / Recovery, "
      "Safety and Manual Controls) are byte-identical", changed == sorted(EDITED_VIEWS), str(changed))
nov, oov = new_views.get("ecco-overview", {}), old_views.get("ecco-overview", {})
flow = lambda v: next((c for c in walk(v) if c.get("type") == "custom:ecco-energy-flow-card"), None)   # noqa: E731
check("the animated Energy Flow card is byte-for-byte acs0's (configuration, including FE1's time_to_reserve line, and grid placement)", flow(nov) is not None and flow(nov) == flow(oov))
n_secs, o_secs = nov.get("sections") or [], oov.get("sections") or []
check("the Overview still has nine `type: grid` sections with the declared spans; the status banner (S1) and the Energy Actions section (S5) "
      "are byte-identical to acs0's",
      len(n_secs) == 9 and [s.get("column_span") for s in n_secs] == OVERVIEW_SPANS and all(s.get("type") == "grid" for s in n_secs)
      and n_secs[0] == o_secs[0] and n_secs[4] == o_secs[4])
ACTION = re.compile(r"(?m)^\s*(tap_action|hold_action|double_tap_action):[ \t]*\r?\n\s*action:\s*(\S+)")


def census(text: str) -> dict:
    out: dict = {}
    for m in ACTION.finditer(text):
        out[m.groups()] = out.get(m.groups(), 0) + 1
    return out


gained = {k: n - census(P1[DASH] or "").get(k, 0) for k, n in census(TXT[DASH]).items() if n > census(P1[DASH] or "").get(k, 0)}
check("the dashboard gained no handler other than `action: none`, and no perform-action / call-service construct (read-only additions)",
      all(k[1] == "none" for k in gained) and TXT[DASH].count("perform-action") == (P1[DASH] or "").count("perform-action")
      and TXT[DASH].count("call-service") == (P1[DASH] or "").count("call-service"), str(gained))
ver = yaml.safe_load(TXT[VERSION])
check("VERSION.yaml: dashboard 7.21.1, staged (tested_in_home_assistant stays false), the 7.21.0 record kept; one pair",
      ver["current"]["dashboard"]["version"] == "7.21.1" and ver["current"]["dashboard"].get("tested_in_home_assistant") is False
      and "v7.20.0 (OVW1)" in TXT[VERSION] and len(O.VERSION_EDITS) == 1, str(ver["current"]["dashboard"]))
check("the dashboard carries the v7.21.1 header note and keeps the pinned first line and the single `&ecco_card_mod` anchor",
      "# v7.21.1 (OVW2, STAGED / NOT LIVE-PROVEN)" in TXT[DASH] and TXT[DASH].startswith("# ECCO Pro Dashboard v7.16.0 - ")
      and TXT[DASH].count("&ecco_card_mod") == 1)

# ===========================================================================
print("")
print("[4] exactness and negative controls")
# ===========================================================================
roundtrip = {DASH: O.add_ovw2_dashboard, VERSION: O.add_ovw2_version}
check("both ovw2 reverters round-trip: applying their pairs to the text as of acs0 gives the text as of ovw2",
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
check("reading the dashboard as of acs0 refuses one changed byte of ovw2's text and a duplicated hunk (no declared state)",
      raises(lambda: at(DASH, "acs0", TXT[DASH].replace("# v7.21.1 (OVW2", "# v7.21.2 (OVW2", 1))) and raises(lambda: at(DASH, "acs0", TXT[DASH] + O.DASHBOARD_EDITS[0][1])))
check("...and an undeclared byte in VERSION.yaml", raises(lambda: at(VERSION, "acs0", TXT[VERSION].replace('"7.21.1"', '"7.21.0"', 1))))
check("ovw2's reverters refuse the acs0-era text (their hunks are not acs0's)",
      P1[DASH] is not None and P1[VERSION] is not None and raises(lambda: O.pre_ovw2_dashboard(P1[DASH])) and raises(lambda: O.pre_ovw2_version(P1[VERSION])))

print("")
if FAILURES:
    print(f"FAILED: {len(FAILURES)} check(s)")
    for f in FAILURES:
        print(f"  - {f}")
    sys.exit(1)
print("All ovw2 transition checks passed.")
print("These prove that the Overview V2.1 changes are declared, exact and reversible, that nothing outside the six edited views, the "
      "Energy Flow card, the status banner and the Energy Actions section changed, and that no control path was added; they prove "
      "nothing about hardware or about how Home Assistant renders the dashboard.")
