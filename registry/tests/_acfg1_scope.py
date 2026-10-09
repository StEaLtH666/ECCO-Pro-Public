"""acfg1 (Advanced Configuration card on the dashboard) change scope: exactly what acfg1 changes in the files the pub0 export froze
and in the chain-pinned deployment manifest, and its exact inverse.

Same technique as the earlier post-export scope modules: every verbatim edit is held HERE as the single source of truth, as an exact
(before, after) pair generated from the real diff and round-trip-checked, and each reverter raises unless each of its edits is present
exactly once. The post-export chain entry `acfg1` (registry/tests/_scope_chain.py POST_EXPORT_ENTRIES, appended last; registry/tests/
_pex.py) carries one frozen reverter per edited frozen file and one chain reverter for the manifest.

WHAT acfg1 IS. The read-only Advanced / Experimental Configuration card (frontend/ecco-advanced-config-card, added as new files by
the Phase 1A change) is put on the dashboard and listed for deployment:
  - home-assistant/dashboards/ecco_pro.yaml (pub0 target, FROZEN): section 13 at the end of the Inverter / Advanced view, the card
    alone, configured with the quoted default device slug (the site renderer renders it for a site), and the v7.19.0 header note;
  - VERSION.yaml (enrolled, FROZEN): dashboard 7.19.0, staged (tested_in_home_assistant stays false); the 7.18.0 record is kept;
  - deployment/ha-manifest.yaml (chain-PINNED): one frontend_assets stanza (copy and resource registration stay manual);
  - two older suites (pub0 targets, FROZEN) whose LIVE "exactly two frontend assets" pins are FB-B1 / FB-B3 pub0-era facts: the
    count is read AS OF pub0 (test_ecco_fallback_packages.py reuses its existing pub0-era manifest; test_fallback_recovery_dashboard.py
    [10] reads the manifest as of pub0, one declared PEX routing); every pinned value is unchanged.
ZERO firmware, Home Assistant package, registry, Intelligence or ecco_core change; ZERO Modbus operation (64 reads / 52 writes); the
card cannot write (it reads hass.states only; its Global Power controls are disabled).

NOT frozen (ordinary edits, nothing to declare): the card's suite (tools/tests/test_advanced_config_catalogue.py) and README,
CHANGELOG.md, docs/dev/post-export-edit-layer.md and test_pex_transition.py (its ledger). Added: this module.

This module imports no other scope module, not _scope_chain (the chain imports it) and not _pex. No I/O.
"""

from __future__ import annotations

import hashlib

# Public main the change is based on.
BASE_COMMIT = "2247e7a8f7766ff65a17b0312486c57a2320d4e2"

ADDED_FILES = frozenset({
    "registry/tests/_acfg1_scope.py",
})


def _blk(s: str) -> str:
    """A raw triple-quoted literal that starts on the line after the opening quotes: drops that first newline."""
    assert s.startswith("\n") and s.endswith("\n") and "\r" not in s
    return s[1:]


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _swap(text: str, find: str, put: str, what: str, state: str) -> str:
    n = text.count(find)
    if n != 1:
        raise AssertionError(f"acfg1 scope: {what} must be {state} exactly once, found {n}x: {find[:70]!r}")
    i = text.index(find)
    return text[:i] + put + text[i + len(find):]


def _revert(text: str, edits: tuple, what: str) -> str:
    out = text
    for k, (before, after) in reversed(list(enumerate(edits))):
        out = _swap(out, after, before, f"{what} edit {k}", "present")
    for k, (before, _after) in enumerate(edits):
        n = out.count(before)
        if n != 1:
            raise AssertionError(f"acfg1 scope: {what} anchor {k} must be unique once the edits are removed, found {n}x")
    return out


def _apply(text: str, edits: tuple, what: str) -> str:
    out = text
    for k, (before, after) in enumerate(edits):
        if after in out:
            raise AssertionError(f"acfg1 scope: {what} edit {k} is already present")
        out = _swap(out, before, after, f"{what} anchor {k}", "found")
    return out


# ---- (PEX frozen edit) home-assistant/dashboards/ecco_pro.yaml -----------------------------------------------------------------------
DASHBOARD_REL = "home-assistant/dashboards/ecco_pro.yaml"
# The v7.19.0 header note, then section 13 of the Inverter / Advanced view.
DASHBOARD_0_OLD = _blk(r"""
# the five existing dongle shadow strings); no control, no Energy Actions change.
""")
DASHBOARD_0_NEW = _blk(r"""
# the five existing dongle shadow strings); no control, no Energy Actions change.
# v7.19.0 (ACFG1, STAGED / NOT LIVE-PROVEN) adds section 13 to the Inverter / Advanced view: the read-only Advanced /
# Experimental Configuration card (every capability-registry record with its live value, evidence and lock reason, and the
# Global Power / Export Limit register 245 panel). Display only: the card cannot write; no control, no firmware change.
# 7.19.0 also carries the read-only Weather & Solar view after Overview (wsc1), added without a version bump of
# its own.
""")
DASHBOARD_1_OLD = _blk(r"""
            card_mod: *ecco_card_mod
  - title: Fallback / Recovery
""")
DASHBOARD_1_NEW = _blk(r"""
            card_mod: *ecco_card_mod

      # ================= 13. ADVANCED / EXPERIMENTAL CONFIGURATION (read-only) =================
      # The read-only register catalogue (frontend/ecco-advanced-config-card, a manual Lovelace resource): every
      # capability-registry record with its live value, evidence and lock reason, and the Global Power / Export Limit
      # (register 245) panel. The card reads states only; it has no write path and its Global Power controls are disabled.
      - type: grid
        column_span: 4
        cards:
          - type: custom:ecco-advanced-config-card
            title: 13 · Advanced / Experimental Configuration
            entity_prefix: "ecco_clock_dongle"
            grid_options:
              columns: 48
              rows: auto
  - title: Fallback / Recovery
""")
DASHBOARD_EDITS = (
    (DASHBOARD_0_OLD, DASHBOARD_0_NEW),
    (DASHBOARD_1_OLD, DASHBOARD_1_NEW),
)


def pre_acfg1_dashboard(text: str) -> str:
    """home-assistant/dashboards/ecco_pro.yaml with exactly acfg1's edits undone (a frozen reverter of chain entry acfg1, PEX)."""
    return _revert(text, DASHBOARD_EDITS, "home-assistant/dashboards/ecco_pro.yaml")


pre_acfg1_dashboard.edits = DASHBOARD_EDITS   # the PEX contract: a reverter exposes its exact (before, after) pairs


def add_acfg1_dashboard(text: str) -> str:
    """Applies acfg1's home-assistant/dashboards/ecco_pro.yaml edits to the earlier text (the round trip)."""
    return _apply(text, DASHBOARD_EDITS, "home-assistant/dashboards/ecco_pro.yaml")

# ---- (PEX frozen edit) VERSION.yaml --------------------------------------------------------------------------------------------------
VERSION_REL = "VERSION.yaml"
# Dashboard 7.18.0 -> 7.19.0 (staged); the 7.18.0 record is kept below the new note.
VERSION_0_OLD = _blk(r"""
    version: "7.18.0"
    path: home-assistant/dashboards/ecco_pro.yaml
""")
VERSION_0_NEW = _blk(r"""
    version: "7.19.0"
    path: home-assistant/dashboards/ecco_pro.yaml
    # v7.19.0 (ACFG1) adds the read-only Advanced / Experimental Configuration card as section 13 of the
    # Inverter / Advanced view (display only; the card cannot write). It also carries the read-only Weather & Solar
    # view after Overview (wsc1), which changed the dashboard without a version bump of its own. It is STAGED:
    # tested_in_home_assistant stays false until both are exercised on the reference installation. The 7.18.0
    # record follows.
""")
VERSION_EDITS = (
    (VERSION_0_OLD, VERSION_0_NEW),
)


def pre_acfg1_version(text: str) -> str:
    """VERSION.yaml with exactly acfg1's edits undone (a frozen reverter of chain entry acfg1, PEX)."""
    return _revert(text, VERSION_EDITS, "VERSION.yaml")


pre_acfg1_version.edits = VERSION_EDITS   # the PEX contract: a reverter exposes its exact (before, after) pairs


def add_acfg1_version(text: str) -> str:
    """Applies acfg1's VERSION.yaml edits to the earlier text (the round trip)."""
    return _apply(text, VERSION_EDITS, "VERSION.yaml")

# ---- (PEX frozen edit) home-assistant/tests/test_ecco_fallback_packages.py -----------------------------------------------------------
SUITE_FBP_REL = "home-assistant/tests/test_ecco_fallback_packages.py"
# The live asset count becomes the pub0-era count (the existing _man0, no new PEX call).
SUITE_FBP_0_OLD = _blk(r"""
      any("ecco-fallback-recovery-card" in a["source"] for a in man["frontend_assets"]) and len(man["frontend_assets"]) == 2)
""")
SUITE_FBP_0_NEW = _blk(r"""
      any("ecco-fallback-recovery-card" in a["source"] for a in man["frontend_assets"])
      and len(_man0["frontend_assets"]) == 2)   # PEX (acfg1): the asset count is a pub0-era pin (acfg1 adds a third asset)
""")
SUITE_FBP_EDITS = (
    (SUITE_FBP_0_OLD, SUITE_FBP_0_NEW),
)


def pre_acfg1_suite_fbp(text: str) -> str:
    """home-assistant/tests/test_ecco_fallback_packages.py with exactly acfg1's edits undone (a frozen reverter of chain entry acfg1, PEX)."""
    return _revert(text, SUITE_FBP_EDITS, "home-assistant/tests/test_ecco_fallback_packages.py")


pre_acfg1_suite_fbp.edits = SUITE_FBP_EDITS   # the PEX contract: a reverter exposes its exact (before, after) pairs


def add_acfg1_suite_fbp(text: str) -> str:
    """Applies acfg1's home-assistant/tests/test_ecco_fallback_packages.py edits to the earlier text (the round trip)."""
    return _apply(text, SUITE_FBP_EDITS, "home-assistant/tests/test_ecco_fallback_packages.py")

# ---- (PEX frozen edit) registry/tests/test_fallback_recovery_dashboard.py ------------------------------------------------------------
SUITE_FRD_REL = "registry/tests/test_fallback_recovery_dashboard.py"
# [10] reads the manifest as of pub0 (one PEX routing; this module QUOTES it).
SUITE_FRD_0_OLD = _blk(r"""
    man_text = read(MANIFEST)
    man = yaml.safe_load(man_text)
    assets = man["frontend_assets"]
""")
SUITE_FRD_0_NEW = _blk(r"""
    man_text = _pex.as_of_pub0("deployment/ha-manifest.yaml", read(MANIFEST))   # PEX (acfg1): FB-B1's stanza pins are pub0-era (acfg1 adds a third asset)
    man = yaml.safe_load(man_text)
    assets = man["frontend_assets"]
""")
SUITE_FRD_EDITS = (
    (SUITE_FRD_0_OLD, SUITE_FRD_0_NEW),
)


def pre_acfg1_suite_frd(text: str) -> str:
    """registry/tests/test_fallback_recovery_dashboard.py with exactly acfg1's edits undone (a frozen reverter of chain entry acfg1, PEX)."""
    return _revert(text, SUITE_FRD_EDITS, "registry/tests/test_fallback_recovery_dashboard.py")


pre_acfg1_suite_frd.edits = SUITE_FRD_EDITS   # the PEX contract: a reverter exposes its exact (before, after) pairs


def add_acfg1_suite_frd(text: str) -> str:
    """Applies acfg1's registry/tests/test_fallback_recovery_dashboard.py edits to the earlier text (the round trip)."""
    return _apply(text, SUITE_FRD_EDITS, "registry/tests/test_fallback_recovery_dashboard.py")

# ---- (chain-pinned edit) deployment/ha-manifest.yaml -----------------------------------------------------------------------------------
MANIFEST_REL = "deployment/ha-manifest.yaml"
# One frontend_assets stanza after the Fallback / Recovery card's.
MANIFEST_0_OLD = _blk(r"""
    resource_url: /local/ecco/ecco-fallback-recovery-card.js

firmware:
""")
MANIFEST_0_NEW = _blk(r"""
    resource_url: /local/ecco/ecco-fallback-recovery-card.js
  # Advanced / Experimental Configuration card - ACFG1 (read-only register catalogue with
  # the Global Power / Export Limit register 245 panel; it cannot write). Copying the file
  # and registering the resource stay deliberate manual steps.
  - source: frontend/ecco-advanced-config-card/dist/ecco-advanced-config-card.js
    destination: /config/www/ecco/ecco-advanced-config-card.js
    method: ssh_file_copy
    restart_required: false
    resource_registration: manual
    resource_url: /local/ecco/ecco-advanced-config-card.js

firmware:
""")
MANIFEST_EDITS = (
    (MANIFEST_0_OLD, MANIFEST_0_NEW),
)


def pre_acfg1_manifest(text: str) -> str:
    """deployment/ha-manifest.yaml with exactly acfg1's edits undone (the chain reverter of entry acfg1 for the pinned manifest)."""
    return _revert(text, MANIFEST_EDITS, "deployment/ha-manifest.yaml")


pre_acfg1_manifest.edits = MANIFEST_EDITS   # the PEX contract: a reverter exposes its exact (before, after) pairs


def add_acfg1_manifest(text: str) -> str:
    """Applies acfg1's deployment/ha-manifest.yaml edits to the earlier text (the round trip)."""
    return _apply(text, MANIFEST_EDITS, "deployment/ha-manifest.yaml")


# Every frozen file acfg1 edits, with its reverter (the chain entry's frozen_reverts).
FROZEN_REVERTERS = {
    DASHBOARD_REL: pre_acfg1_dashboard,
    VERSION_REL: pre_acfg1_version,
    SUITE_FBP_REL: pre_acfg1_suite_fbp,
    SUITE_FRD_REL: pre_acfg1_suite_frd,
}
# The chain-pinned file acfg1 edits, with its reverter (the chain entry's reverts).
PINNED_REVERTERS = {
    MANIFEST_REL: pre_acfg1_manifest,
}
