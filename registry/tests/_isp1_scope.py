"""isp1 (ECCO Intelligence SHADOW v0.1: the presentation package, its preferences and dashboard registration packages, the
standalone dashboard and the card in the release files) change scope: exactly what isp1 changes in the two files the pub0 export
froze (VERSION.yaml and the V1 prototype suite, intelligence/tests/test_intelligence_dashboard_prototype.py) and in the chain-pinned
deployment manifest, and its exact inverse.

Same technique as the earlier post-export scope modules: every verbatim edit is held HERE as the single source of truth, as an exact
(before, after) pair generated from the real diff and round-trip-checked, and each reverter raises unless each of its edits is present
exactly once. The post-export chain entry `isp1` (registry/tests/_scope_chain.py POST_EXPORT_ENTRIES, appended after the newest entry
at build time; registry/tests/_pex.py) carries two frozen reverters (VERSION.yaml and the V1 prototype suite) and one chain-pinned
reverter (the manifest). Its fingerprint is sealed with _pex.sealed and must be sealed again if another entry merges before it.

WHAT isp1 IS. The Home Assistant side of ECCO Intelligence SHADOW v0.1 that the integration's own release left out: advice only, it
applies nothing. New files (ADDED_FILES):
  home-assistant/packages/ecco_intelligence.yaml            the pause helper, the dead-man watchdog and three notification-only
                                                            alerts (persistent_notification.create with fixed ecco_intel_ ids)
  home-assistant/packages/ecco_intelligence_prefs.yaml      the raise-only advisory reserve helper (one input_number, no `initial`)
  home-assistant/packages/ecco_intelligence_dashboard.yaml  the standalone dashboard's registration (one YAML-mode lovelace
                                                            dashboards entry, administrators only)
  their two offline suites under home-assistant/tests, and this module.
The integration (custom_components/ecco_intelligence), the standalone dashboard file and the card already exist in the tree; isp1
lists the dashboard and the card for deployment. ZERO firmware, registry data, Intelligence engine, runtime or ecco_core byte; ZERO
Modbus operation; no service call other than persistent_notification.create; the production dashboard is untouched.

FROZEN edits (PEX).
  VERSION.yaml                  current.home_assistant.intelligence_package, and a new current.intelligence block (version 0.1.0,
                                contract ecco-intel-entities/1, SHADOW, applies nothing, its paths, tested_in_home_assistant false);
                                project_version and the dashboard version are unchanged
  intelligence/tests/test_intelligence_dashboard_prototype.py
                                the frozen V1 prototype suite's isolation pin ("no `intelligence` in the manifest") narrowed to
                                the new exact truth: no prototype file or path in the manifest, and no manifest path naming
                                Intelligence other than exactly isp1's eleven (ISP1_MANIFEST_PATHS), a path line that carries a
                                trailing comment included (MANIFEST_PATH_RE); every other check unchanged
CHAIN-PINNED edit.
  deployment/ha-manifest.yaml   three home_assistant_packages stanzas, a new top-level intelligence_dashboard mapping and one
                                frontend_assets stanza (manual resource registration); no stanza for custom_components (the
                                integration has its own kit route)

This module imports no other scope module, not _scope_chain (the chain imports it) and not _pex. No I/O.
"""

from __future__ import annotations

import hashlib

ADDED_FILES = frozenset({
    "home-assistant/packages/ecco_intelligence.yaml",
    "home-assistant/packages/ecco_intelligence_dashboard.yaml",
    "home-assistant/packages/ecco_intelligence_prefs.yaml",
    "home-assistant/tests/test_ecco_intelligence_package.py",
    "home-assistant/tests/test_ecco_intelligence_prefs_package.py",
    "registry/tests/_isp1_scope.py",
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
        raise AssertionError(f"isp1 scope: {what} must be {state} exactly once, found {n}x: {find[:70]!r}")
    i = text.index(find)
    return text[:i] + put + text[i + len(find):]


def _revert(text: str, edits: tuple, what: str) -> str:
    out = text
    for k, (before, after) in reversed(list(enumerate(edits))):
        out = _swap(out, after, before, f"{what} edit {k}", "present")
    for k, (before, _after) in enumerate(edits):
        n = out.count(before)
        if n != 1:
            raise AssertionError(f"isp1 scope: {what} anchor {k} must be unique once the edits are removed, found {n}x")
    return out


def _apply(text: str, edits: tuple, what: str) -> str:
    out = text
    for k, (before, after) in enumerate(edits):
        if after in out:
            raise AssertionError(f"isp1 scope: {what} edit {k} is already present")
        out = _swap(out, before, after, f"{what} anchor {k}", "found")
    return out


# ---- (PEX frozen edit) VERSION.yaml -------------------------------------------------------------------------------------------
VERSION_REL = "VERSION.yaml"
VERSION_0_OLD = _blk(r"""
    battery_runtime: home-assistant/packages/ecco_battery_runtime.yaml
""")
VERSION_0_NEW = _blk(r"""
    battery_runtime: home-assistant/packages/ecco_battery_runtime.yaml
    intelligence_package: home-assistant/packages/ecco_intelligence.yaml
""")
VERSION_1_OLD = _blk(r"""
  site_profile:
""")
VERSION_1_NEW = _blk(r"""
  intelligence:
    # ECCO Intelligence SHADOW v0.1 (isp1): the read-only Home Assistant integration publishes advice under contract
    # ecco-intel-entities/1 and applies nothing. Its presentation package (the pause helper, the watchdog and three
    # notification-only alerts), the raise-only reserve helper package, the standalone dashboard with its registration
    # package and the card are listed in deployment/ha-manifest.yaml; the integration installs by its own kit route.
    # ASSISTED and AUTONOMOUS stay disabled. It is STAGED: tested_in_home_assistant stays false until it is installed and
    # accepted on the reference installation (an isolated test Home Assistant does not count).
    version: "0.1.0"
    contract: ecco-intel-entities/1
    mode: SHADOW
    applies_nothing: true
    path: custom_components/ecco_intelligence
    package: home-assistant/packages/ecco_intelligence.yaml
    prefs_package: home-assistant/packages/ecco_intelligence_prefs.yaml
    dashboard_registration: home-assistant/packages/ecco_intelligence_dashboard.yaml
    dashboard: home-assistant/dashboards/ecco_intelligence.yaml
    card: frontend/ecco-intelligence-card/ecco-intelligence-card.js
    tested_in_home_assistant: false
  site_profile:
""")
VERSION_EDITS = (
    (VERSION_0_OLD, VERSION_0_NEW),
    (VERSION_1_OLD, VERSION_1_NEW),
)


def pre_isp1_version(text: str) -> str:
    """VERSION.yaml with exactly isp1's edits undone (a frozen reverter of chain entry isp1, PEX): its text as of the entry before."""
    return _revert(text, VERSION_EDITS, "VERSION.yaml")


pre_isp1_version.edits = VERSION_EDITS   # the PEX contract: a reverter exposes its exact (before, after) pairs


def add_isp1_version(text: str) -> str:
    """Applies isp1's VERSION.yaml edits to the text as of the entry before (the round trip)."""
    return _apply(text, VERSION_EDITS, "VERSION.yaml")


# ---- (chain-pinned edit) deployment/ha-manifest.yaml --------------------------------------------------------------------------
MANIFEST_REL = "deployment/ha-manifest.yaml"
MANIFEST_0_OLD = _blk(r"""
    destination: /config/packages/ecco_schedule_manual_restore.yaml
    method: ssh_file_copy
    restart_required: true
""")
MANIFEST_0_NEW = _blk(r"""
    destination: /config/packages/ecco_schedule_manual_restore.yaml
    method: ssh_file_copy
    restart_required: true

  # ECCO Intelligence SHADOW v0.1 - isp1 (advice only; applies nothing). The presentation package (the pause helper, the dead-man
  # watchdog and three notification-only alerts) and the raise-only reserve helper: install both BEFORE the integration and turn
  # the pause helper on before the integration first starts (the install runbook, gate G8). The integration itself
  # (custom_components/ecco_intelligence) installs by its own kit route and is not listed here.
  - source: home-assistant/packages/ecco_intelligence.yaml
    destination: /config/packages/ecco_intelligence.yaml
    method: ssh_file_copy
    restart_required: true
  - source: home-assistant/packages/ecco_intelligence_prefs.yaml
    destination: /config/packages/ecco_intelligence_prefs.yaml
    method: ssh_file_copy
    restart_required: true
  # The ECCO Intelligence dashboard's registration (one YAML-mode lovelace dashboards entry, nothing else). Deploy it after the
  # dashboard file (intelligence_dashboard below).
  - source: home-assistant/packages/ecco_intelligence_dashboard.yaml
    destination: /config/packages/ecco_intelligence_dashboard.yaml
    method: ssh_file_copy
    restart_required: true
""")
MANIFEST_1_OLD = _blk(r"""
  method: ssh_file_copy_staged
  restart_required: false
  activation_required: true
""")
MANIFEST_1_NEW = _blk(r"""
  method: ssh_file_copy_staged
  restart_required: false
  activation_required: true

# ECCO Intelligence SHADOW v0.1 - isp1: the standalone ECCO Intelligence dashboard (YAML mode, read-only apart from the pause
# tile). It is separate from the production dashboard above and never changes it; ecco_intelligence_dashboard.yaml registers it,
# which takes effect at a Home Assistant restart.
intelligence_dashboard:
  source: home-assistant/dashboards/ecco_intelligence.yaml
  destination: /config/ecco/dashboards/ecco_intelligence.yaml
  method: ssh_file_copy
  restart_required: false
  activation_required: true
""")
# Appended as the last frontend_assets stanza, right before the top-level firmware mapping (the anchor names no other card).
MANIFEST_2_OLD = _blk(r"""

firmware:
""")
MANIFEST_2_NEW = _blk(r"""
  # ECCO Intelligence card - isp1 (read-only display of the ecco-intel-entities/1 output; no write path of any kind).
  # A single dependency-free ES module (no dist build step). Copying the file and registering the resource stay
  # deliberate manual steps.
  - source: frontend/ecco-intelligence-card/ecco-intelligence-card.js
    destination: /config/www/ecco/ecco-intelligence-card.js
    method: ssh_file_copy
    restart_required: false
    resource_registration: manual
    resource_url: /local/ecco/ecco-intelligence-card.js

firmware:
""")
MANIFEST_EDITS = (
    (MANIFEST_0_OLD, MANIFEST_0_NEW),
    (MANIFEST_1_OLD, MANIFEST_1_NEW),
    (MANIFEST_2_OLD, MANIFEST_2_NEW),
)


def pre_isp1_manifest(text: str) -> str:
    """deployment/ha-manifest.yaml with exactly isp1's edits undone (the chain reverter of entry isp1 for the pinned manifest): its
    text as of the entry before."""
    return _revert(text, MANIFEST_EDITS, "deployment/ha-manifest.yaml")


pre_isp1_manifest.edits = MANIFEST_EDITS   # the PEX contract: a reverter exposes its exact (before, after) pairs


def add_isp1_manifest(text: str) -> str:
    """Applies isp1's deployment/ha-manifest.yaml edits to the text as of the entry before (the round trip)."""
    return _apply(text, MANIFEST_EDITS, "deployment/ha-manifest.yaml")


# ---- (PEX frozen edit) intelligence/tests/test_intelligence_dashboard_prototype.py --------------------------------------------
# The frozen V1 prototype suite proves its prototype isolated from production with "no `intelligence` anywhere in the manifest".
# isp1 lists the SHADOW v0.1 release files there, so the pin is narrowed to the new exact truth: no prototype file or path, and
# no manifest path that names Intelligence other than exactly isp1's eleven (sources, destinations and the card's resource url).
PROTO_SUITE_REL = "intelligence/tests/test_intelligence_dashboard_prototype.py"
ISP1_MANIFEST_PATHS = frozenset({
    "home-assistant/packages/ecco_intelligence.yaml", "/config/packages/ecco_intelligence.yaml",
    "home-assistant/packages/ecco_intelligence_prefs.yaml", "/config/packages/ecco_intelligence_prefs.yaml",
    "home-assistant/packages/ecco_intelligence_dashboard.yaml", "/config/packages/ecco_intelligence_dashboard.yaml",
    "home-assistant/dashboards/ecco_intelligence.yaml", "/config/ecco/dashboards/ecco_intelligence.yaml",
    "frontend/ecco-intelligence-card/ecco-intelligence-card.js", "/config/www/ecco/ecco-intelligence-card.js",
    "/local/ecco/ecco-intelligence-card.js",
})
# The pin's path-line pattern, verbatim as in PROTO_0_NEW: a source, destination or resource_url value, with or without a trailing
# YAML comment (a `#` after a blank). The package suite reads the live manifest with it and checks that it is the hunk's own.
MANIFEST_PATH_RE = r"^\s*(?:-\s*)?(?:source|destination|resource_url):\s*(\S+)(?:[ \t]+#.*)?\s*$"
PROTO_0_OLD = _blk(r"""
check("prototype files are not in the deployment manifest", "prototypes" not in manifest and "intelligence" not in manifest.lower())
""")
PROTO_0_NEW = _blk(r"""
# PEX (isp1): the manifest lists the ECCO Intelligence SHADOW v0.1 release files (post-export entry isp1); the prototype stays out.
# Exempt are exactly isp1's eleven paths; any other manifest path that names Intelligence, and any prototype file, still fails.
# A path line counts with or without a trailing comment.
_ISP1_PATHS = {"home-assistant/packages/ecco_intelligence.yaml", "/config/packages/ecco_intelligence.yaml",
               "home-assistant/packages/ecco_intelligence_prefs.yaml", "/config/packages/ecco_intelligence_prefs.yaml",
               "home-assistant/packages/ecco_intelligence_dashboard.yaml", "/config/packages/ecco_intelligence_dashboard.yaml",
               "home-assistant/dashboards/ecco_intelligence.yaml", "/config/ecco/dashboards/ecco_intelligence.yaml",
               "frontend/ecco-intelligence-card/ecco-intelligence-card.js", "/config/www/ecco/ecco-intelligence-card.js",
               "/local/ecco/ecco-intelligence-card.js"}
_man_paths = re.findall(r"^\s*(?:-\s*)?(?:source|destination|resource_url):\s*(\S+)(?:[ \t]+#.*)?\s*$", manifest, re.M)
check("prototype files are not in the deployment manifest", "prototypes" not in manifest and "intelligence_v1" not in manifest.lower()
      and "intelligence-v1" not in manifest.lower() and len(_man_paths) > 30
      and not [p for p in _man_paths if "intelligence" in p.lower() and p not in _ISP1_PATHS])
""")
PROTO_EDITS = (
    (PROTO_0_OLD, PROTO_0_NEW),
)


def pre_isp1_proto_suite(text: str) -> str:
    """The prototype suite with exactly isp1's edit undone (a frozen reverter of chain entry isp1, PEX): its text as of the entry
    before."""
    return _revert(text, PROTO_EDITS, PROTO_SUITE_REL)


pre_isp1_proto_suite.edits = PROTO_EDITS   # the PEX contract: a reverter exposes its exact (before, after) pairs


def add_isp1_proto_suite(text: str) -> str:
    """Applies isp1's prototype-suite edit to the text as of the entry before (the round trip)."""
    return _apply(text, PROTO_EDITS, PROTO_SUITE_REL)


# The frozen files isp1 edits, with their reverters (the chain entry's frozen_reverts).
FROZEN_REVERTERS = {
    VERSION_REL: pre_isp1_version,
    PROTO_SUITE_REL: pre_isp1_proto_suite,
}
# The chain-pinned file isp1 edits, with its reverter (the chain entry's reverts).
PINNED_REVERTERS = {
    MANIFEST_REL: pre_isp1_manifest,
}
