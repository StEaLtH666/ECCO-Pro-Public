"""acs0 (Advanced Configuration Stage 0: a guarded owner edit of ONE TOU slot's target SOC) change scope: exactly what acs0 changes
in the chain-pinned deployment manifest, and its exact inverse, plus the files it adds.

WHAT acs0 IS. A Home Assistant package (home-assistant/packages/ecco_tou_target_soc_edit.yaml: three result / plan helpers, the
lock and the in-flight marker, three scripts, one interrupted-edit watchdog automation) that lets the owner change ONE TOU slot's target SOC (register 267+N) through the EXISTING, verified
manual TOU firmware path (Load Current Slot N To Manual Staging -> Manual Configuration Write Enable -> Apply Manual Slot N
Settings): Review (writes nothing) -> a typed confirmation with a one-time review code -> Apply, with a fresh configuration read,
the Manual Controls helper sync at a fixed point, only the SOC staged, every other staged value proven equal to the live slot,
one Apply, and success only on the firmware's VERIFIED OK plus an independent later read of every written register. Fail-closed
refusal in every unsafe state; an uncertain outcome locks further edits until acknowledged. ZERO firmware byte, ZERO new
register (the write surface is unchanged).

THE TOKEN AMENDMENT (owner-approved Option A, 2026-10-12). The gate READS six reserved fallback / failback entity ids
(RESERVED_IDS). acs0 declares exactly its three files as banned_files and makes the five exact allowlist checks exempt exactly
those six ids in exactly those files - nothing is widened for any other file, id or operation. Where exactness is enforced:
the frozen FB-C3 strict rule (ecco_failback: only the shadow State id, all three files), the FB-B3 holder scan (Home Assistant
YAML: the package holds only the six ids) and the B10 scan (only the full live-match id, all three files); for the two .py files,
any other ecco_fallback-family id is refused by the editor's own suite (section [12]), as banned_files is a whole-file declaration
in every earlier entry too.

CHAIN-PINNED edit: deployment/ha-manifest.yaml, one home_assistant_packages stanza.
FROZEN edits (PEX): three older suites whose exact reserved-token allowlists acs0 amends - test_fallback_profile_schema.py (the
FB-C3 strict rule + its exactness proof, and the exact declared list), test_fallback_recovery_dashboard.py (the FB-B3 holder list,
unchanged, with the six ids removed from the editor package before the scan) and test_fallback_save_scope.py (the exact union of
declaring entries).
NOT frozen (ordinary edits): registry/tests/test_fallback_live_match.py (the B10 holder list, unchanged, with the full B10 id
removed from acs0's three files before the scan; its pairs are recorded below for audit), home-assistant/tests/_ha_script_sim.py (fps1's simulator: lists of packages, helper initial
states, state triggers on lists, queued mode, condition / stop / repeat for_each, input_number / input_datetime services),
registry/tests/test_pex_transition.py (the PEX ledger), CHANGELOG.md.

This module imports no other scope module, not _scope_chain (the chain imports it) and not _pex. No I/O.
"""

from __future__ import annotations

# Public main the change is based on (FSW1 merged).
BASE_COMMIT = "2afe6c3ffdec51ec808cb03a84a8471e503677d5"

ADDED_FILES = frozenset({
    "docs/dev/advanced-config-write-assessment.md",
    "docs/dev/advanced-config/conflict-map.md",
    "docs/dev/advanced-config/ha-surface.md",
    "docs/dev/advanced-config/register-evidence.md",
    "docs/dev/advanced-config/s3-tou-slot1-soc-writes-2026-10.md",
    "docs/dev/advanced-config/settings-map.md",
    "docs/dev/advanced-config/stage0-live-proof-procedure.md",
    "docs/dev/advanced-config/stage0-safety-case.md",
    "docs/dev/advanced-config/stage0b-card-plan.md",
    "docs/dev/advanced-config/write-surface.md",
    "docs/dev/dump-to-grid-restore-conflict-investigation.md",
    "home-assistant/packages/ecco_tou_target_soc_edit.yaml",
    "home-assistant/tests/_manual_tou_sim.py",
    "home-assistant/tests/test_ecco_tou_target_soc_edit.py",
    "registry/tests/_acs0_scope.py",
})


def _blk(s: str) -> str:
    assert s.startswith("\n") and s.endswith("\n") and "\r" not in s
    return s[1:]


def _swap(text: str, find: str, put: str, what: str, state: str) -> str:
    n = text.count(find)
    if n != 1:
        raise AssertionError(f"acs0 scope: {what} must be {state} exactly once, found {n}x: {find[:70]!r}")
    i = text.index(find)
    return text[:i] + put + text[i + len(find):]


MANIFEST_REL = "deployment/ha-manifest.yaml"
MANIFEST_0_OLD = _blk(r"""
    destination: /config/packages/ecco_battery_runtime.yaml
""")
MANIFEST_0_NEW = _blk(r"""
    destination: /config/packages/ecco_battery_runtime.yaml
    method: ssh_file_copy
    restart_required: true

  # Advanced Configuration Stage 0 - ACS0 (owner edit of ONE TOU slot's target SOC through the existing, verified manual
  # TOU firmware path; review + typed confirmation; NOT live-proven - see docs/dev/advanced-config/stage0-live-proof-procedure.md).
  - source: home-assistant/packages/ecco_tou_target_soc_edit.yaml
    destination: /config/packages/ecco_tou_target_soc_edit.yaml
""")
MANIFEST_EDITS = ((MANIFEST_0_OLD, MANIFEST_0_NEW),)


def pre_acs0_manifest(text: str) -> str:
    """deployment/ha-manifest.yaml with exactly acs0's edit undone (the chain reverter of entry acs0): its text as of fsw1."""
    out = _swap(text, MANIFEST_0_NEW, MANIFEST_0_OLD, "deployment/ha-manifest.yaml edit 0", "present")
    if out.count(MANIFEST_0_OLD) != 1:
        raise AssertionError("acs0 scope: manifest anchor must be unique once the edit is removed")
    return out


pre_acs0_manifest.edits = MANIFEST_EDITS   # the PEX contract: a reverter exposes its exact (before, after) pairs


def add_acs0_manifest(text: str) -> str:
    """Applies acs0's manifest edit to the text as of fsw1 (the round trip)."""
    if MANIFEST_0_NEW in text:
        raise AssertionError("acs0 scope: the manifest edit is already present")
    return _swap(text, MANIFEST_0_OLD, MANIFEST_0_NEW, "deployment/ha-manifest.yaml anchor 0", "found")


# ---- the reserved-token amendment (owner-approved Option A, 2026-10-12) ----------------------------------------------------------------
# The editor's fail-closed gate READS six reserved fallback / failback entity ids (the live match, the Review state, the three operator
# "available" gates and the failback shadow State). The FB-A / FB-B3 / FB-C3 token rule allows reserved tokens only in files a chain entry
# declares, and five exact allowlists pin today's holders. acs0 declares EXACTLY its three files (banned_files) and amends those five
# checks so that, in exactly those three files, exactly these six ids (spelled in full) are exempt - nothing else: a seventh id, a
# variant, a fragment, the six ids in any other file, and every other file are still leaks. Each id is read only (the editor's own suite
# pins that every occurrence in the package is inside states() / is_state(), and that no indirect route reaches fallback state).
BANNED_FILES = frozenset({
    "home-assistant/packages/ecco_tou_target_soc_edit.yaml",
    "home-assistant/tests/_manual_tou_sim.py",
    "home-assistant/tests/test_ecco_tou_target_soc_edit.py",
})
RESERVED_IDS = (
    "sensor.ecco_clock_dongle_ecco_fallback_profile_live_match",
    "sensor.ecco_clock_dongle_ecco_fallback_profile_review",
    "binary_sensor.ecco_fallback_save_available",
    "binary_sensor.ecco_fallback_replace_corrupt_available",
    "binary_sensor.ecco_fallback_invalidate_available",
    "sensor.ecco_clock_dongle_ecco_failback_shadow_state",
)


def _revert(text: str, edits: tuple, what: str) -> str:
    out = text
    for k, (before, after) in reversed(list(enumerate(edits))):
        out = _swap(out, after, before, f"{what} edit {k}", "present")
    for k, (before, _after) in enumerate(edits):
        n = out.count(before)
        if n != 1:
            raise AssertionError(f"acs0 scope: {what} anchor {k} must be unique once the edits are removed, found {n}x")
    return out


def _apply(text: str, edits: tuple, what: str) -> str:
    out = text
    for k, (before, after) in enumerate(edits):
        if after in out:
            raise AssertionError(f"acs0 scope: {what} edit {k} is already present")
        out = _swap(out, before, after, f"{what} anchor {k}", "found")
    return out


# ---- (PEX frozen edit) registry/tests/test_fallback_profile_schema.py ------------------------------------------------------------------
# (1) the FB-C3 strict rule: in acs0's three files exactly the shadow State id is exempt; (2) its exactness proof; (3) the exact declared
# allowlist grows by acs0's three files.
SUITE_PS_REL = "registry/tests/test_fallback_profile_schema.py"
SUITE_PS_0_OLD = _blk(r"""
SHADOW_ID_RE = re.compile(r"sensor\.ecco_clock_dongle_ecco_failback_shadow_(?:state|episode|soak|verdict|inputs)(?![a-z0-9_])")


def strict_hits(rel: str, text: str) -> list:
    if rel in SHADOW_ID_FILES:
        text = SHADOW_ID_RE.sub("", text)
    return [tok for tok in STRICT if tok in text]
""")
SUITE_PS_0_NEW = _blk(r"""
SHADOW_ID_RE = re.compile(r"sensor\.ecco_clock_dongle_ecco_failback_shadow_(?:state|episode|soak|verdict|inputs)(?![a-z0-9_])")
# acs0 (PEX, the owner-approved token amendment, Option A, 2026-10-12): the Advanced Configuration Stage 0 editor's three files - its
# package, its dongle model and its suite - may spell exactly ONE ecco_failback id: the shadow State, which the editor's fail-closed gate
# READS. Nothing else is exempt: another shadow id, a variant, the same id in any other file, FALLBACK_PROFILE and FAILBACK_STATE still leak.
ACS0_FILES = frozenset({"home-assistant/packages/ecco_tou_target_soc_edit.yaml", "home-assistant/tests/_manual_tou_sim.py",
                        "home-assistant/tests/test_ecco_tou_target_soc_edit.py"})
ACS0_SHADOW_RE = re.compile(r"(?<![a-z0-9_])sensor\.ecco_clock_dongle_ecco_failback_shadow_state(?![a-z0-9_])")


def strict_hits(rel: str, text: str) -> list:
    if rel in SHADOW_ID_FILES:
        text = SHADOW_ID_RE.sub("", text)
    if rel in ACS0_FILES:
        text = ACS0_SHADOW_RE.sub("", text)   # acs0: exactly this one id, in exactly these three files
    return [tok for tok in STRICT if tok in text]
""")
SUITE_PS_1_OLD = _blk(r"""
check("FB-B3 / FB-C3: frontend/ carries no reserved token at all, and the declared allowlist is exactly the eight named files (exact paths, no directory exemption; "
      "the eighth is FB-C3's HA suite, which spells ecco_fallback entity ids)",
      not [l for l in leaks if l.startswith("frontend/")] and sorted(CH.declared_banned_files()) == sorted([
          "deployment/ha-manifest.yaml", "home-assistant/dashboards/ecco_pro.yaml",
          "home-assistant/packages/ecco_fallback_profile_actions.yaml", "home-assistant/packages/ecco_fallback_status.yaml",
          "home-assistant/packages/ecco_system_health.yaml", "home-assistant/tests/test_ecco_fallback_packages.py",
          "home-assistant/tests/test_ecco_system_health_package.py", "home-assistant/tests/test_ecco_shadow_check_ux.py"]), str(sorted(CH.declared_banned_files())))
""")
SUITE_PS_1_NEW = _blk(r"""
_acs0_text = {f: (ROOT / f).read_text(encoding="utf-8") for f in sorted(ACS0_FILES)}
_acs0_pkg = "home-assistant/packages/ecco_tou_target_soc_edit.yaml"
check("acs0: the amendment is real (each of the editor's three files spells the shadow State id) and exact (another shadow id, a variant, "
      "the same id in any other file, FALLBACK_PROFILE or FAILBACK_STATE still leak)",
      all(ACS0_SHADOW_RE.search(t) and strict_hits(f, t) == [] for f, t in _acs0_text.items())
      and strict_hits(_acs0_pkg, _acs0_text[_acs0_pkg] + "\nsensor.ecco_clock_dongle_ecco_failback_shadow_episode") == ["ecco_" + "failback"]
      and strict_hits(_acs0_pkg, _acs0_text[_acs0_pkg] + "\nsensor.ecco_clock_dongle_ecco_failback_shadow_state_x") == ["ecco_" + "failback"]
      and strict_hits(_acs0_pkg, _acs0_text[_acs0_pkg] + "\nbinary_sensor.ecco_clock_dongle_ecco_failback_shadow_state") == ["ecco_" + "failback"]
      and strict_hits("home-assistant/packages/ecco_system_health.yaml", "sensor.ecco_clock_dongle_ecco_failback_shadow_state") == ["ecco_" + "failback"]
      and strict_hits("home-assistant/dashboards/ecco_pro.yaml", "sensor.ecco_clock_dongle_ecco_failback_shadow_state") == ["ecco_" + "failback"]
      and strict_hits(_acs0_pkg, "FALLBACK" + "_PROFILE") == ["FALLBACK" + "_PROFILE"] and strict_hits(_acs0_pkg, "FAILBACK" + "_STATE") == ["FAILBACK" + "_STATE"],
      str({f: strict_hits(f, t) for f, t in _acs0_text.items()}))
check("FB-B3 / FB-C3 / acs0: frontend/ carries no reserved token at all, and the declared allowlist is exactly the eleven named files (exact paths, no directory "
      "exemption; the eighth is FB-C3's HA suite, which spells ecco_fallback entity ids; the last three are acs0's editor package, model and suite, "
      "which read six reserved ids)",
      not [l for l in leaks if l.startswith("frontend/")] and sorted(CH.declared_banned_files()) == sorted([
          "deployment/ha-manifest.yaml", "home-assistant/dashboards/ecco_pro.yaml",
          "home-assistant/packages/ecco_fallback_profile_actions.yaml", "home-assistant/packages/ecco_fallback_status.yaml",
          "home-assistant/packages/ecco_system_health.yaml", "home-assistant/tests/test_ecco_fallback_packages.py",
          "home-assistant/tests/test_ecco_system_health_package.py", "home-assistant/tests/test_ecco_shadow_check_ux.py",
          "home-assistant/packages/ecco_tou_target_soc_edit.yaml", "home-assistant/tests/_manual_tou_sim.py",
          "home-assistant/tests/test_ecco_tou_target_soc_edit.py"])
      and CH.entry("acs0").banned_files == ACS0_FILES, str(sorted(CH.declared_banned_files())))
""")
SUITE_PS_EDITS = (
    (SUITE_PS_0_OLD, SUITE_PS_0_NEW),
    (SUITE_PS_1_OLD, SUITE_PS_1_NEW),
)


def pre_acs0_suite_ps(text: str) -> str:
    """registry/tests/test_fallback_profile_schema.py with exactly acs0's edits undone (a frozen reverter of chain entry acs0, PEX)."""
    return _revert(text, SUITE_PS_EDITS, SUITE_PS_REL)


pre_acs0_suite_ps.edits = SUITE_PS_EDITS   # the PEX contract: a reverter exposes its exact (before, after) pairs


def add_acs0_suite_ps(text: str) -> str:
    """Applies acs0's registry/tests/test_fallback_profile_schema.py edits to the earlier text (the round trip)."""
    return _apply(text, SUITE_PS_EDITS, SUITE_PS_REL)


# ---- (PEX frozen edit) registry/tests/test_fallback_recovery_dashboard.py --------------------------------------------------------------
# FB-B3's reserved-token holder list is NOT widened: in the editor package exactly the six ids are removed before the scan.
SUITE_RD_REL = "registry/tests/test_fallback_recovery_dashboard.py"
SUITE_RD_0_OLD = _blk(r"""
    banned_holders = sorted(rel for rel, text in holders.items() if BANNED.search(text))
""")
SUITE_RD_0_NEW = _blk(r"""
    # acs0 (PEX, the owner-approved token amendment, Option A, 2026-10-12): the Advanced Configuration Stage 0 editor package READS exactly
    # six reserved ids for its fail-closed gate. They are removed from that one file before the scan, so it is still a holder if it spells
    # any other reserved token (a seventh id, a variant), every other file is scanned unchanged, and the allowlist below is NOT widened.
    ACS0_PKG = "home-assistant/packages/ecco_tou_target_soc_edit.yaml"
    ACS0_IDS_RE = re.compile(r"(?<![a-z0-9_])(?:sensor\.ecco_clock_dongle_ecco_fallback_profile_(?:live_match|review)"
                             r"|binary_sensor\.ecco_fallback_(?:save|replace_corrupt|invalidate)_available"
                             r"|sensor\.ecco_clock_dongle_ecco_failback_shadow_state)(?![a-z0-9_])")

    def acs0_view(rel: str, text: str) -> str:
        return ACS0_IDS_RE.sub("", text) if rel == ACS0_PKG else text
    check("acs0: the exemption is real (the editor package spells all six ids) and exact (a seventh reserved id, a variant, or one of the "
          "six ids in any other file is still a holder)",
          len(set(ACS0_IDS_RE.findall(holders[ACS0_PKG]))) == 6
          and BANNED.search(acs0_view(ACS0_PKG, holders[ACS0_PKG] + "\nswitch.ecco_clock_dongle_ecco_fallback_profile_arm"))
          and BANNED.search(acs0_view(ACS0_PKG, holders[ACS0_PKG] + "\nsensor.ecco_clock_dongle_ecco_fallback_profile_review_id"))
          and BANNED.search(acs0_view(ACS0_PKG, holders[ACS0_PKG] + "\nbinary_sensor.ecco_clock_dongle_ecco_fallback_profile_review"))
          and BANNED.search(acs0_view(HB_PKG, "binary_sensor.ecco_fallback_save_available")),
          str(sorted(set(ACS0_IDS_RE.findall(holders[ACS0_PKG])))))
    banned_holders = sorted(rel for rel, text in holders.items() if BANNED.search(acs0_view(rel, text)))
""")
SUITE_RD_EDITS = (
    (SUITE_RD_0_OLD, SUITE_RD_0_NEW),
)


def pre_acs0_suite_rd(text: str) -> str:
    """registry/tests/test_fallback_recovery_dashboard.py with exactly acs0's edits undone (a frozen reverter of chain entry acs0, PEX)."""
    return _revert(text, SUITE_RD_EDITS, SUITE_RD_REL)


pre_acs0_suite_rd.edits = SUITE_RD_EDITS   # the PEX contract: a reverter exposes its exact (before, after) pairs


def add_acs0_suite_rd(text: str) -> str:
    """Applies acs0's registry/tests/test_fallback_recovery_dashboard.py edits to the earlier text (the round trip)."""
    return _apply(text, SUITE_RD_EDITS, SUITE_RD_REL)


# ---- (PEX frozen edit) registry/tests/test_fallback_save_scope.py ----------------------------------------------------------------------
# The exact union of the entries that declare banned files gains acs0, whose declaration is pinned to its exact three files.
SUITE_SS_REL = "registry/tests/test_fallback_save_scope.py"
SUITE_SS_0_OLD = _blk(r"""
          and set(leaks) == set(CH.entry("fbb1").banned_files) | set(CH.entry("fbb3").banned_files) | set(CH.entry("fbc3").banned_files), str(leaks))
""")
SUITE_SS_0_NEW = _blk(r"""
          # acs0 (PEX, the owner-approved token amendment, Option A, 2026-10-12): its entry declares exactly its own three files (the Stage 0
          # editor's package, dongle model and suite, which read six reserved ids), nothing else
          and set(CH.entry("acs0").banned_files) == {"home-assistant/packages/ecco_tou_target_soc_edit.yaml", "home-assistant/tests/_manual_tou_sim.py",
                                                     "home-assistant/tests/test_ecco_tou_target_soc_edit.py"}
          and set(leaks) == set(CH.entry("fbb1").banned_files) | set(CH.entry("fbb3").banned_files) | set(CH.entry("fbc3").banned_files)
          | set(CH.entry("acs0").banned_files), str(leaks))
""")
SUITE_SS_EDITS = (
    (SUITE_SS_0_OLD, SUITE_SS_0_NEW),
)


def pre_acs0_suite_ss(text: str) -> str:
    """registry/tests/test_fallback_save_scope.py with exactly acs0's edits undone (a frozen reverter of chain entry acs0, PEX)."""
    return _revert(text, SUITE_SS_EDITS, SUITE_SS_REL)


pre_acs0_suite_ss.edits = SUITE_SS_EDITS   # the PEX contract: a reverter exposes its exact (before, after) pairs


def add_acs0_suite_ss(text: str) -> str:
    """Applies acs0's registry/tests/test_fallback_save_scope.py edits to the earlier text (the round trip)."""
    return _apply(text, SUITE_SS_EDITS, SUITE_SS_REL)


# ---- (ordinary edit, NOT frozen; recorded here for audit) registry/tests/test_fallback_live_match.py ------------------------------------
# The B10 holder list is NOT widened: in acs0's three files exactly the full B10 id is removed before the scan.
SUITE_LM_REL = "registry/tests/test_fallback_live_match.py"
SUITE_LM_0_OLD = _blk(r"""
    leak, b10_holders = [], []
""")
SUITE_LM_0_NEW = _blk(r"""
    leak, b10_holders = [], []
    # acs0 (the owner-approved token amendment, Option A, 2026-10-12): the Advanced Configuration Stage 0 editor's three files READ the B10
    # entity id for their fail-closed gate, spelled in full. That exact id is removed from those three files before the scan, so any other
    # spelling (a variant, a fragment) still makes them holders, every other file is scanned unchanged, and the list below is NOT widened.
    ACS0_B10_FILES = frozenset({"home-assistant/packages/ecco_tou_target_soc_edit.yaml", "home-assistant/tests/_manual_tou_sim.py",
                                "home-assistant/tests/test_ecco_tou_target_soc_edit.py"})
    ACS0_B10_RE = re.compile(r"(?<![a-z0-9_])sensor\.ecco_clock_dongle_ecco_fallback_profile_live_match(?![a-z0-9_])")
""")
SUITE_LM_1_OLD = _blk(r"""
        if "fallback_profile_live_match" in txt:
            b10_holders.append(rel)
""")
SUITE_LM_1_NEW = _blk(r"""
        if "fallback_profile_live_match" in (ACS0_B10_RE.sub("", txt) if rel in ACS0_B10_FILES else txt):   # acs0: exactly the full id
            b10_holders.append(rel)
""")
SUITE_LM_2_OLD = _blk(r"""
                                  "home-assistant/tests/test_ecco_fallback_packages.py", "home-assistant/tests/test_ecco_shadow_check_ux.py"],
          str(b10_holders))
""")
SUITE_LM_2_NEW = _blk(r"""
                                  "home-assistant/tests/test_ecco_fallback_packages.py", "home-assistant/tests/test_ecco_shadow_check_ux.py"],
          str(b10_holders))
    _acs0_b10 = {f: (ROOT / f).read_text(encoding="utf-8") for f in sorted(ACS0_B10_FILES)}
    check("acs0: the B10 exemption is real (each of the editor's three files spells the full id) and exact (a variant, a fragment or the id "
          "in any other file is still a holder)",
          all(ACS0_B10_RE.search(t) and "fallback_profile_live_match" not in ACS0_B10_RE.sub("", t) for t in _acs0_b10.values())
          and "fallback_profile_live_match" in ACS0_B10_RE.sub("", "sensor.ecco_clock_dongle_ecco_fallback_profile_live_match_x")
          and "fallback_profile_live_match" in ACS0_B10_RE.sub("", "binary_sensor.ecco_clock_dongle_ecco_fallback_profile_live_match")
          and "fallback_profile_live_match" in ACS0_B10_RE.sub("", "states('sensor.ecco_clock_dongle_ecco_' ~ 'fallback_profile_live_match')")
          and "home-assistant/packages/ecco_system_health.yaml" not in ACS0_B10_FILES, str(sorted(_acs0_b10)))
""")
SUITE_LM_EDITS = (
    (SUITE_LM_0_OLD, SUITE_LM_0_NEW),
    (SUITE_LM_1_OLD, SUITE_LM_1_NEW),
    (SUITE_LM_2_OLD, SUITE_LM_2_NEW),
)


def add_acs0_suite_lm(text: str) -> str:
    """Applies acs0's registry/tests/test_fallback_live_match.py edits (an ordinary file; the round trip)."""
    return _apply(text, SUITE_LM_EDITS, SUITE_LM_REL)


def pre_acs0_suite_lm(text: str) -> str:
    """registry/tests/test_fallback_live_match.py with exactly acs0's edits undone (audit only: the file is not frozen)."""
    return _revert(text, SUITE_LM_EDITS, SUITE_LM_REL)


# Every frozen file acs0 edits, with its reverter (the chain entry's frozen_reverts).
FROZEN_REVERTERS = {
    SUITE_PS_REL: pre_acs0_suite_ps,
    SUITE_RD_REL: pre_acs0_suite_rd,
    SUITE_SS_REL: pre_acs0_suite_ss,
}
# The chain-pinned file acs0 edits, with its reverter (the chain entry's reverts).
PINNED_REVERTERS = {
    MANIFEST_REL: pre_acs0_manifest,
}
