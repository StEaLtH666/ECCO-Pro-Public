"""pex0 - the PEX FOUNDATION (schema ecco-pex/1): the first post-export entry, which installs the layer and changes nothing else.

WHY. See registry/tests/_pex.py. Three older suites pin pub0-era facts of files a post-export entry may edit (the dashboard, the
deployment manifest, VERSION.yaml). pex0 routes exactly those historical pins through _pex.as_of_pub0 (owner decision O4: the pins
only; every live safety invariant keeps reading the live file), so a later declared entry (the Dump power work, house demand / stale
handling) does not have to edit these suites again.

WHAT pex0 CHANGES (the complete list; ZERO product or feature content: no firmware, Home Assistant package, dashboard, manifest or
registry byte, so the chain entry _scope_chain.PEX0 has no chain-pinned reverter and no delta):
  frozen   (pub0 targets; FROZEN_EDITS, undone by _scope_chain.PEX0's frozen reverters)
    registry/tests/test_fallback_recovery_dashboard.py   [2] the two FB-B3 view-list pins read the dashboard as of pub0, plus one live
                                                         check keeping the adjacency Fallback / Recovery -> Safety -> Manual Controls;
                                                         [15] the FB-C3 / FB-B3 / FB-B1 dashboard history reads it as of pub0
    home-assistant/tests/test_ecco_fallback_packages.py  [13] the same two view-list pins plus the same live adjacency check; [19] the
                                                         Energy Actions block pin; [20] the 11-package count and the release string;
                                                         [21] the FB-B3 / FB-C3 VERSION.yaml facts
    home-assistant/tests/test_ecco_shadow_check_ux.py    [7] the Energy Actions block pin and the three FB-C3 VERSION.yaml pins (the
                                                         VERSION.yaml private-history check keeps reading the live file); [14] the
                                                         per-package control-surface pin covers the pub0-era package SET (a package a
                                                         post-export entry declares as added is not part of it; contents stay live)
  gate     (NOT frozen; GATE_EDITS, hash-pinned by test_pex_transition.py: GATE_SHA after pex0, GATE_BASE_SHA at 883068d)
    registry/tests/test_pub0_transition.py               the four approved routings / restatements (owner decision O1): LIVE and the
                                                         chain-pinned artifacts read AS OF pub0; [1] restated (pub0 right after ENTRIES,
                                                         only declared post-export entries after it); [6] OWN names the PEX files
  other    (neither frozen nor chain-pinned; found by declared sweeps) two older suites anchored a historical baseline on the LIVE
           chain-pinned text, so any later declared edit to it broke them: registry/tests/test_fallback_live_match.py (its one as-of
           measurement reads through the tree's CHAIN instead of Chain(), the twelve ENTRIES only; found with a declared manifest
           stanza) and registry/tests/test_fbd1_liveness.py (its pre-FB-D1 baseline reads the firmware as of fbd1; found with a
           declared firmware edit). Their live behaviour checks still run on the live files
  added    ADDED_FILES: the layer, this module, its proof suite and the documentation page
  docs     CONTRIBUTING.md (one paragraph) and CHANGELOG.md ([Unreleased]); neither is frozen

The pairs are generated from the real diff against public main @ 883068d and verified by round trip. Undoing them requires every
`after` to occur exactly once (applying them, every `before`); anything else raises Pex0Error, so any OTHER change to these lines still
breaks the pins that use them.

No I/O.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

BASE_COMMIT = "883068daf63e51ff0e79c9f2cc427a3124f6cccb"

ADDED_FILES = frozenset({
    "docs/dev/post-export-edit-layer.md",
    "registry/tests/_pex.py",
    "registry/tests/_pex0_scope.py",
    "registry/tests/test_pex_transition.py",
})

# rel -> ((before, after), ...): every frozen file pex0 edits, in file order.
FROZEN_EDITS = {
    "home-assistant/tests/test_ecco_fallback_packages.py": (
        (
            "import _lic0_scope as _lic0  # noqa: E402  (LIC0: the declared v0.9.0 licence alignment of the Energy Actions card)\n",
            "import _lic0_scope as _lic0  # noqa: E402  (LIC0: the declared v0.9.0 licence alignment of the Energy Actions card)\n"
            "import _pex  # noqa: E402  (PEX0: the historical pins below read their file AS OF pub0; live safety invariants read the live file)\n",
        ),
        (
            "      safety.get(\"path\") == \"ecco-safety\" and safety.get(\"icon\") == \"mdi:shield-home-outline\" and safety.get(\"type\") == \"sections\")\n",
            "      safety.get(\"path\") == \"ecco-safety\" and safety.get(\"icon\") == \"mdi:shield-home-outline\" and safety.get(\"type\") == \"sections\")\n"
            "# PEX0 (O4): the two view-list pins below are FB-B3's pub0-era layout, so they read the dashboard AS OF pub0; the live adjacency\n"
            "# Fallback / Recovery -> Safety -> Manual Controls they carried stays a live check (the third check).\n"
            "_titles0 = [v[\"title\"] for v in yaml.load(_pex.as_of_pub0(\"home-assistant/dashboards/ecco_pro.yaml\", dash_text), Loader=TaggedSafeLoader)[\"views\"]]   # PEX0: as of pub0\n",
        ),
        (
            "      titles[-2:] == [\"Safety\", \"Manual Controls\"] and titles[-3] == \"Fallback / Recovery\", str(titles))\n",
            "      _titles0[-2:] == [\"Safety\", \"Manual Controls\"] and _titles0[-3] == \"Fallback / Recovery\", str(_titles0))\n",
        ),
        (
            "      [t for t in titles if t != \"Safety\"] == [\"Overview\", \"Intelligence\", \"Tariffs\", \"Control\", \"Recommended\", \"System\",\n"
            "                                                \"Inverter / Advanced\", \"Fallback / Recovery\", \"Manual Controls\"])\n",
            "      [t for t in _titles0 if t != \"Safety\"] == [\"Overview\", \"Intelligence\", \"Tariffs\", \"Control\", \"Recommended\", \"System\",\n"
            "                                                  \"Inverter / Advanced\", \"Fallback / Recovery\", \"Manual Controls\"])\n"
            "check(\"live: Fallback / Recovery, Safety and Manual Controls are consecutive views in this order (PEX0: the live part of the FB-B3 placement)\",\n"
            "      \"Fallback / Recovery\" in titles and titles[titles.index(\"Fallback / Recovery\"):titles.index(\"Fallback / Recovery\") + 3]\n"
            "      == [\"Fallback / Recovery\", \"Safety\", \"Manual Controls\"], str(titles))\n",
        ),
        (
            "_dash_private = _pub0.private_view(\"home-assistant/dashboards/ecco_pro.yaml\", dash_text)   # PUB0: the pin is the private block's\n",
            "_dash_private = _pub0.private_view(\"home-assistant/dashboards/ecco_pro.yaml\", _pex.as_of_pub0(\"home-assistant/dashboards/ecco_pro.yaml\", dash_text))   # PUB0: the pin is the private block's; PEX0: as of pub0\n",
        ),
        (
            "check(\"the manifest has exactly two new package entries (11 packages in total)\", len(pk) == 11, str(len(pk)))\n",
            "_man0 = yaml.safe_load(_pex.as_of_pub0(\"deployment/ha-manifest.yaml\", man_text))   # PEX0: FB-B3's package count and release are pub0-era pins\n"
            "check(\"the manifest has exactly two new package entries (11 packages in total)\", len(_man0[\"home_assistant_packages\"]) == 11,\n"
            "      str(len(_man0[\"home_assistant_packages\"])))\n",
        ),
        (
            "check(\"the manifest release string is updated\", man[\"release\"] == \"2026-10-02-fbb3-dashboard\")\n",
            "check(\"the manifest release string is updated\", _man0[\"release\"] == \"2026-10-02-fbb3-dashboard\")   # PEX0: as of pub0\n",
        ),
        (
            "ver = yaml.safe_load(lf(VERSION))\n",
            "ver = yaml.safe_load(_pex.as_of_pub0(\"VERSION.yaml\", lf(VERSION)))   # PEX0: the FB-B3 / FB-C3 version facts below are pub0-era pins\n",
        ),
    ),
    "home-assistant/tests/test_ecco_shadow_check_ux.py": (
        (
            "import _lic0_scope as _lic0  # noqa: E402  (LIC0: the declared v0.9.0 licence alignment of the Energy Actions card)\n",
            "import _lic0_scope as _lic0  # noqa: E402  (LIC0: the declared v0.9.0 licence alignment of the Energy Actions card)\n"
            "import _pex  # noqa: E402  (PEX0: the historical pins below read their file AS OF pub0; live safety invariants read the live file)\n",
        ),
        (
            "PKG_SURFACE = {name: {k: len(v) for k, v in d.items() if k != \"template\"} for name, d in all_pkgs.items()}\n",
            "# PEX0 (O4): the per-package pin below is FB-C3's pub0-era package SET: a package a post-export entry declares as added is not part of\n"
            "# it (an undeclared new package still fails). The package contents stay live, and every other check here reads all packages.\n"
            "_pkgs_pub0 = {n: d for n, d in all_pkgs.items() if f\"home-assistant/packages/{n}\" not in _pex.post_export_added()}   # PEX0: the pub0-era set\n"
            "PKG_SURFACE = {name: {k: len(v) for k, v in d.items() if k != \"template\"} for name, d in _pkgs_pub0.items()}\n",
        ),
        (
            "_dash_private = _pub0.private_view(\"home-assistant/dashboards/ecco_pro.yaml\", dash_text)   # PUB0: the pin is the private block's\n",
            "_dash_private = _pub0.private_view(\"home-assistant/dashboards/ecco_pro.yaml\", _pex.as_of_pub0(\"home-assistant/dashboards/ecco_pro.yaml\", dash_text))   # PUB0: the pin is the private block's; PEX0: as of pub0\n",
        ),
        (
            "ver = yaml.safe_load(lf(VERSION))\n",
            "ver = yaml.safe_load(lf(VERSION))\n"
            "_ver0_text = _pex.as_of_pub0(\"VERSION.yaml\", lf(VERSION))   # PEX0: the three FB-C3 version / record pins below read VERSION.yaml AS OF pub0\n"
            "_ver0 = yaml.safe_load(_ver0_text)\n",
        ),
        (
            "      ver[\"current\"][\"dashboard\"][\"version\"] == \"7.18.0\" and ver[\"current\"][\"dashboard\"][\"tested_in_home_assistant\"] is False\n"
            "      and ver[\"current\"][\"firmware\"][\"version\"] == \"stage3.4\" and ver[\"current\"][\"firmware\"][\"hardware_verified\"] is True)\n",
            "      _ver0[\"current\"][\"dashboard\"][\"version\"] == \"7.18.0\" and _ver0[\"current\"][\"dashboard\"][\"tested_in_home_assistant\"] is False\n"
            "      and _ver0[\"current\"][\"firmware\"][\"version\"] == \"stage3.4\" and _ver0[\"current\"][\"firmware\"][\"hardware_verified\"] is True)\n",
        ),
        (
            "      \"previous dashboard release (7.17.0,\" in ver_text and \"FB-B3\" in ver_text and \"tested_in_home_assistant is therefore false for 7.18.0\" in ver_text)\n"
            "check(\"version: FB-C3 is recorded as OFFLINE / STAGED / NOT LIVE-PROVEN\", \"FB-C3\" in ver_text and \"OFFLINE / STAGED / NOT LIVE-PROVEN\" in ver_text)\n",
            "      \"previous dashboard release (7.17.0,\" in _ver0_text and \"FB-B3\" in _ver0_text and \"tested_in_home_assistant is therefore false for 7.18.0\" in _ver0_text)\n"
            "check(\"version: FB-C3 is recorded as OFFLINE / STAGED / NOT LIVE-PROVEN\", \"FB-C3\" in _ver0_text and \"OFFLINE / STAGED / NOT LIVE-PROVEN\" in _ver0_text)\n",
        ),
    ),
    "registry/tests/test_fallback_recovery_dashboard.py": (
        (
            "import _lic0_scope as _lic0  # noqa: E402  (LIC0: the declared v0.9.0 licence alignment of the Energy Actions card)\n",
            "import _lic0_scope as _lic0  # noqa: E402  (LIC0: the declared v0.9.0 licence alignment of the Energy Actions card)\n"
            "import _pex  # noqa: E402  (PEX0: the historical pins below read the dashboard AS OF pub0; live safety invariants read the live file)\n",
        ),
        (
            "    # FB-B3: Safety is the ONLY view FB-B3 adds, and it sits immediately before Manual Controls, after Fallback / Recovery\n",
            "    # FB-B3: Safety is the ONLY view FB-B3 adds, and it sits immediately before Manual Controls, after Fallback / Recovery\n"
            "    # PEX0 (O4): the two view-list pins below are FB-B3's pub0-era layout, so they read the dashboard AS OF pub0; the live adjacency\n"
            "    # Fallback / Recovery -> Safety -> Manual Controls they carried stays a live check (the third check).\n"
            "    _views0 = yaml.safe_load(_pex.as_of_pub0(\"home-assistant/dashboards/ecco_pro.yaml\", dash_text))[\"views\"]   # PEX0: the dashboard as of pub0\n"
            "    _titles0 = [v[\"title\"] for v in _views0]\n"
            "    _i0 = next((n for n, v in enumerate(_views0) if v.get(\"path\") == VIEW_PATH), -1)\n",
        ),
        (
            "          i > 0 and titles[i - 1] == \"Inverter / Advanced\" and titles[i] == VIEW_TITLE and titles[i + 1] == SAFETY_TITLE and titles[i + 2] == \"Manual Controls\"\n"
            "          and titles[-1] == \"Manual Controls\", str(titles))\n",
            "          _i0 > 0 and _titles0[_i0 - 1] == \"Inverter / Advanced\" and _titles0[_i0] == VIEW_TITLE and _titles0[_i0 + 1] == SAFETY_TITLE\n"
            "          and _titles0[_i0 + 2] == \"Manual Controls\" and _titles0[-1] == \"Manual Controls\", str(_titles0))\n",
        ),
        (
            "          [t for t in titles if t not in (VIEW_TITLE, SAFETY_TITLE)] == [\"Overview\", \"Intelligence\", \"Tariffs\", \"Control\", \"Recommended\", \"System\", \"Inverter / Advanced\", \"Manual Controls\"]\n"
            "          and len(titles) == 10 and titles.count(SAFETY_TITLE) == 1 and [v.get(\"path\") for v in views].count(\"ecco-safety\") == 1, str(titles))\n",
            "          [t for t in _titles0 if t not in (VIEW_TITLE, SAFETY_TITLE)] == [\"Overview\", \"Intelligence\", \"Tariffs\", \"Control\", \"Recommended\", \"System\", \"Inverter / Advanced\", \"Manual Controls\"]\n"
            "          and len(_titles0) == 10 and _titles0.count(SAFETY_TITLE) == 1 and [v.get(\"path\") for v in _views0].count(\"ecco-safety\") == 1, str(_titles0))\n"
            "    check(\"live: Fallback / Recovery, Safety and Manual Controls are consecutive views in this order, Safety exactly once (PEX0: the live part of the FB-B3 placement)\",\n"
            "          i > 0 and titles[i:i + 3] == [VIEW_TITLE, SAFETY_TITLE, \"Manual Controls\"] and titles.count(SAFETY_TITLE) == 1\n"
            "          and [v.get(\"path\") for v in views].count(\"ecco-safety\") == 1, str(titles))\n",
        ),
        (
            "    lf_full = _pub0.private_view(\"home-assistant/dashboards/ecco_pro.yaml\", dash_text.replace(\"\\r\\n\", \"\\n\"))\n",
            "    # PEX0: every pin of this section is the FB-C3 / FB-B3 / FB-B1 history of the file, so it reads the dashboard AS OF pub0 (exact).\n"
            "    lf_full = _pub0.private_view(\"home-assistant/dashboards/ecco_pro.yaml\", _pex.as_of_pub0(\"home-assistant/dashboards/ecco_pro.yaml\", dash_text.replace(\"\\r\\n\", \"\\n\")))\n",
        ),
    ),
}

# The PUB0 gate (owner decision O1 + the mandatory post-pex0 hash pin): its four approved routings / restatements, as exact pairs.
GATE_REL = "registry/tests/test_pub0_transition.py"
GATE_BASE_SHA = "2d430905d66f846e57714fdd87ffa43bf167f9a9f44482b027f63437a8b2c001"   # git show 883068d:registry/tests/test_pub0_transition.py | sha256sum
GATE_SHA = "e007b1ec5a65a45682d09a403898f9170e2c0fff26ea180af0c6317efda6ef3e"         # the gate after pex0 (LF text)
GATE_EDITS = (
    (
        "with forward() and proven. In the public export (EXPORTED True) the live files ARE the export: the proof views are reversed exactly.\n",
        "with forward() and proven. In the public export (EXPORTED True) the live files ARE the export: the proof views are reversed exactly.\n"
        "\n"
        "PEX0 (the post-export edit layer, registry/tests/_pex.py, owner decision O1): in the public export, changes made on the export are\n"
        "declared post-export chain entries (_scope_chain.POST_EXPORT_ENTRIES, after pub0). Every file this suite proves is read AS OF pub0\n"
        "through the layer (each declared edit undone exactly, newest first, sha256-checked at every step; the identity in the private tree),\n"
        "so every check below runs on the pub0 export byte for byte. test_pex_transition.py proves the post-export entries themselves.\n",
    ),
    (
        "import _scope_chain as sc  # noqa: E402\n",
        "import _scope_chain as sc  # noqa: E402\n"
        "import _pex  # noqa: E402  (PEX0: the post-export edit layer; the export's files are proven AS OF pub0)\n",
    ),
    (
        "LIVE = {rel: P.read_repo(rel) for rel in P.TARGETS}\n",
        "LIVE = {rel: _pex.as_of_pub0(rel, P.read_repo(rel)) for rel in P.TARGETS}   # PEX0: every target AS OF pub0 (exact; identity in the private tree)\n",
    ),
    (
        "check(\"the chain carries pub0 exactly when the tree is the export\", (sc.CHAIN.ids()[-1] == \"pub0\") == EXPORTED\n"
        "      and sc.CHAIN.ids().count(\"pub0\") == int(EXPORTED))\n",
        "# PEX0 (O1): restated from `ids()[-1] == \"pub0\"`. pub0 sits immediately after the merge-ordered ENTRIES, exactly once, exactly when the\n"
        "# tree is the export, and only the declared post-export entries follow it (none in the private tree).\n"
        "_ids, _n = sc.CHAIN.ids(), len(sc.ENTRIES)\n"
        "check(\"the chain carries pub0 exactly when the tree is the export: the merge-ordered ENTRIES, then pub0, then only the declared \"\n"
        "      \"post-export (PEX) entries\", _ids[:_n] == [e.id for e in sc.ENTRIES] and (_ids[_n:_n + 1] == [\"pub0\"]) == EXPORTED\n"
        "      and _ids.count(\"pub0\") == int(EXPORTED) and _ids[_n + 1:] == ([e.id for e in sc.POST_EXPORT_ENTRIES] if EXPORTED else []))\n",
    ),
    (
        "LIVE_PINNED = {p: sc.read_live(p) for p in sc.PINNED}\n",
        "LIVE_PINNED = {p: _pex.as_of_pub0(p, sc.read_live(p)) for p in sc.PINNED}   # PEX0: the chain-pinned artifacts AS OF pub0 (exact)\n",
    ),
    (
        "       \"registry/tests/test_lic0_transition.py\"}   # lic0 (v0.9.0) proves its own transition on the private text: not an older suite\n",
        "       \"registry/tests/test_lic0_transition.py\",   # lic0 (v0.9.0) proves its own transition on the private text: not an older suite\n"
        "       # PEX0: the post-export layer, pex0's own routing data (its exact hunks quote the routed lines) and its proofs: not older suites\n"
        "       \"registry/tests/_pex.py\", \"registry/tests/_pex0_scope.py\", \"registry/tests/test_pex_transition.py\"}\n",
    ),
)


class Pex0Error(AssertionError):
    """A declared pex0 edit is absent, altered or duplicated (a failed proof, never a skipped one)."""


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _swap(text: str, find: str, put: str, what: str) -> str:
    n = text.count(find)
    if n != 1:
        raise Pex0Error(f"{what}: the declared text must occur exactly once, found {n}x: {find[:70]!r}")
    return text.replace(find, put)


def revert(text: str, edits: tuple, what: str) -> str:
    """`text` with exactly `edits` undone (newest hunk first)."""
    for before, after in reversed(edits):
        text = _swap(text, after, before, what)
    return text


def apply(text: str, edits: tuple, what: str) -> str:
    """`text` with exactly `edits` applied (the forward direction, for the round-trip proofs)."""
    for before, after in edits:
        text = _swap(text, before, after, what)
    return text


def reverter(rel: str):
    """The frozen reverter of `rel` for _scope_chain.PEX0; it exposes its exact pairs as `.edits` (the PEX contract)."""
    edits = FROZEN_EDITS[rel]

    def revert_(text: str) -> str:
        return revert(text, edits, f"pex0 {rel}")

    revert_.__name__ = f"pre_pex0_{Path(rel).stem}"
    revert_.edits = edits
    return revert_


def pre_pex0_gate(text: str) -> str:
    """The PUB0 gate with exactly pex0's four routings undone: test_pub0_transition.py as of public main @ 883068d."""
    return revert(text, GATE_EDITS, f"pex0 {GATE_REL}")
