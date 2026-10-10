"""fe1 (FE-1: the batteries' time to reserve) change scope: exactly what fe1 changes in the files the pub0 export froze and in
the chain-pinned deployment manifest, and its exact inverse.

Same technique as the earlier post-export scope modules: every verbatim edit is held HERE as the single source of truth, as an exact
(before, after) pair generated from the real diff and round-trip-checked, and each reverter raises unless each of its edits is present
exactly once. The post-export chain entry `fe1` (registry/tests/_scope_chain.py POST_EXPORT_ENTRIES, appended last after ovw1;
registry/tests/_pex.py) carries one frozen reverter per edited frozen file and one chain-pinned reverter for the manifest.

WHAT fe1 IS. A read-only Home Assistant estimate of how long the batteries can keep discharging before they reach the configured
reserve (input_number.ecco_minimum_reserve_soc), from the existing battery power / SOC telemetry, shown on the Energy Flow card's
battery node through its FE-0 hook nodes.battery.time_to_reserve. New files (ADDED_FILES): the package
home-assistant/packages/ecco_battery_runtime.yaml (template entities only: no service call, script, automation or action), its
offline suite home-assistant/tests/test_ecco_battery_runtime.py, the card's FE-1 node tests, the documentation page and this module.
The Energy Flow card's source, README and bundle are neither frozen nor enrolled (ordinary edits). ZERO firmware, registry,
Intelligence or ecco_core byte; ZERO Modbus operation (64 reads / 52 writes unchanged); no new control surface.

FROZEN edits (PEX).
  home-assistant/dashboards/ecco_pro.yaml   the v7.21.0 header note, the time_to_reserve line of the Overview Energy Flow card's
                                            battery node, and the battery estimate card's time-to-reserve line (display only)
  VERSION.yaml                              dashboard 7.21.0 (staged) with its note, and the package path
CHAIN-PINNED edit.
  deployment/ha-manifest.yaml               one home_assistant_packages stanza for the new package

NOT frozen (ordinary edits, nothing to declare): frontend/ecco-energy-flow-card (src, README, dist, the generic example),
registry/tests/test_ovw1_transition.py (it no longer requires ovw1 to be the newest entry), registry/tests/test_pex_transition.py
(the PEX ledger), CHANGELOG.md.

This module imports no other scope module, not _scope_chain (the chain imports it) and not _pex. No I/O.
"""

from __future__ import annotations

import hashlib

# Public main the change is based on (Overview V2, squash-merged as PR #18).
BASE_COMMIT = "f0ddeb44f0f69c930cac7616b7bcf584c1727e99"

ADDED_FILES = frozenset({
    "docs/BATTERY_TIME_TO_RESERVE.md",
    "frontend/ecco-energy-flow-card/test/reserveRuntime.test.ts",
    "home-assistant/packages/ecco_battery_runtime.yaml",
    "home-assistant/tests/test_ecco_battery_runtime.py",
    "registry/tests/_fe1_scope.py",
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
        raise AssertionError(f"fe1 scope: {what} must be {state} exactly once, found {n}x: {find[:70]!r}")
    i = text.index(find)
    return text[:i] + put + text[i + len(find):]


def _revert(text: str, edits: tuple, what: str) -> str:
    out = text
    for k, (before, after) in reversed(list(enumerate(edits))):
        out = _swap(out, after, before, f"{what} edit {k}", "present")
    for k, (before, _after) in enumerate(edits):
        n = out.count(before)
        if n != 1:
            raise AssertionError(f"fe1 scope: {what} anchor {k} must be unique once the edits are removed, found {n}x")
    return out


def _apply(text: str, edits: tuple, what: str) -> str:
    out = text
    for k, (before, after) in enumerate(edits):
        if after in out:
            raise AssertionError(f"fe1 scope: {what} edit {k} is already present")
        out = _swap(out, before, after, f"{what} anchor {k}", "found")
    return out


# ---- (PEX frozen edit) home-assistant/dashboards/ecco_pro.yaml ----------------------------------------------------------------
DASHBOARD_REL = "home-assistant/dashboards/ecco_pro.yaml"
DASHBOARD_0_OLD = _blk(r"""
# beside an electrical detail list, and one merged System Health card. Display only: no control, no firmware change.
""")
DASHBOARD_0_NEW = _blk(r"""
# beside an electrical detail list, and one merged System Health card. Display only: no control, no firmware change.
# v7.21.0 (FE1, STAGED / NOT LIVE-PROVEN) shows the batteries' time to reserve: the Overview Energy Flow card's battery
# node reads sensor.ecco_battery_time_to_reserve (nodes.battery.time_to_reserve) and the battery estimate card adds its
# summary. The estimate comes from the read-only package ecco_battery_runtime.yaml. Display only: no control, no
# firmware change.
""")
DASHBOARD_1_OLD = _blk(r"""
                power_sign: discharge_positive
""")
DASHBOARD_1_NEW = _blk(r"""
                power_sign: discharge_positive
                time_to_reserve: sensor.ecco_battery_time_to_reserve
""")
DASHBOARD_2_OLD = _blk(r"""
                  const predicted = n('sensor.ecco_predicted_soc_plus_1_hour_baseline');
""")
DASHBOARD_2_NEW = _blk(r"""
                  const predicted = n('sensor.ecco_predicted_soc_plus_1_hour_baseline');
                  const ttr = states['sensor.ecco_battery_time_to_reserve']?.attributes?.summary;
                  const esc = s => String(s).replace(/[&<>]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' })[c]);
""")
DASHBOARD_3_OLD = _blk(r"""
                    <div style="font-size:12px;color:rgba(255,255,255,.62);margin-top:4px;">Reserve floor <b style="color:#fff;">${f(reserve,0)} %</b> · predicted SOC +1 h <b style="color:#fff;">${f(predicted,1)} %</b></div>
""")
DASHBOARD_3_NEW = _blk(r"""
                    <div style="font-size:12px;color:rgba(255,255,255,.62);margin-top:4px;">Reserve floor <b style="color:#fff;">${f(reserve,0)} %</b> · predicted SOC +1 h <b style="color:#fff;">${f(predicted,1)} %</b></div>
                    <div style="font-size:12px;color:rgba(255,255,255,.62);margin-top:4px;">Time to reserve <b style="color:#fff;">${ttr ? esc(ttr) : '--'}</b></div>
""")
DASHBOARD_EDITS = (
    (DASHBOARD_0_OLD, DASHBOARD_0_NEW),
    (DASHBOARD_1_OLD, DASHBOARD_1_NEW),
    (DASHBOARD_2_OLD, DASHBOARD_2_NEW),
    (DASHBOARD_3_OLD, DASHBOARD_3_NEW),
)


def pre_fe1_dashboard(text: str) -> str:
    """home-assistant/dashboards/ecco_pro.yaml with exactly fe1's edits undone (a frozen reverter of chain entry fe1, PEX): its text as of ovw1."""
    return _revert(text, DASHBOARD_EDITS, "home-assistant/dashboards/ecco_pro.yaml")


pre_fe1_dashboard.edits = DASHBOARD_EDITS   # the PEX contract: a reverter exposes its exact (before, after) pairs


def add_fe1_dashboard(text: str) -> str:
    """Applies fe1's home-assistant/dashboards/ecco_pro.yaml edits to the text as of ovw1 (the round trip)."""
    return _apply(text, DASHBOARD_EDITS, "home-assistant/dashboards/ecco_pro.yaml")


# ---- (PEX frozen edit) VERSION.yaml -------------------------------------------------------------------------------------------
VERSION_REL = "VERSION.yaml"
VERSION_0_OLD = _blk(r"""
    version: "7.20.0"
""")
VERSION_0_NEW = _blk(r"""
    version: "7.21.0"
""")
VERSION_1_OLD = _blk(r"""
    path: home-assistant/dashboards/ecco_pro.yaml
""")
VERSION_1_NEW = _blk(r"""
    path: home-assistant/dashboards/ecco_pro.yaml
    # v7.21.0 (FE1) shows the batteries' time to reserve: the Overview Energy Flow card's battery node reads
    # sensor.ecco_battery_time_to_reserve (nodes.battery.time_to_reserve) and the battery estimate card adds its
    # summary. The estimate is the new read-only package ecco_battery_runtime.yaml (offline template tests only).
    # Display only: no control path or firmware changed. It is STAGED: tested_in_home_assistant stays false until
    # the estimate is observed on the reference installation. The 7.20.0 record follows.
""")
VERSION_2_OLD = _blk(r"""
    battery_outlook_readback: home-assistant/packages/ecco_battery_outlook_influx.yaml
""")
VERSION_2_NEW = _blk(r"""
    battery_outlook_readback: home-assistant/packages/ecco_battery_outlook_influx.yaml
    battery_runtime: home-assistant/packages/ecco_battery_runtime.yaml
""")
VERSION_EDITS = (
    (VERSION_0_OLD, VERSION_0_NEW),
    (VERSION_1_OLD, VERSION_1_NEW),
    (VERSION_2_OLD, VERSION_2_NEW),
)


def pre_fe1_version(text: str) -> str:
    """VERSION.yaml with exactly fe1's edits undone (a frozen reverter of chain entry fe1, PEX): its text as of ovw1."""
    return _revert(text, VERSION_EDITS, "VERSION.yaml")


pre_fe1_version.edits = VERSION_EDITS   # the PEX contract: a reverter exposes its exact (before, after) pairs


def add_fe1_version(text: str) -> str:
    """Applies fe1's VERSION.yaml edits to the text as of ovw1 (the round trip)."""
    return _apply(text, VERSION_EDITS, "VERSION.yaml")


# ---- (chain-pinned edit) deployment/ha-manifest.yaml --------------------------------------------------------------------------
MANIFEST_REL = "deployment/ha-manifest.yaml"
MANIFEST_0_OLD = _blk(r"""
    destination: /config/packages/ecco_fallback_profile_actions.yaml
""")
MANIFEST_0_NEW = _blk(r"""
    destination: /config/packages/ecco_fallback_profile_actions.yaml
    method: ssh_file_copy
    restart_required: true
  # Battery time to reserve - FE1 (read-only estimate for the Energy Flow card's battery node;
  # no service call, no control; NOT live-proven). Deploy before dashboard 7.21.0.
  - source: home-assistant/packages/ecco_battery_runtime.yaml
    destination: /config/packages/ecco_battery_runtime.yaml
""")
MANIFEST_EDITS = (
    (MANIFEST_0_OLD, MANIFEST_0_NEW),
)


def pre_fe1_manifest(text: str) -> str:
    """deployment/ha-manifest.yaml with exactly fe1's edits undone (the chain reverter of entry fe1 for the pinned manifest): its text as of ovw1."""
    return _revert(text, MANIFEST_EDITS, "deployment/ha-manifest.yaml")


pre_fe1_manifest.edits = MANIFEST_EDITS   # the PEX contract: a reverter exposes its exact (before, after) pairs


def add_fe1_manifest(text: str) -> str:
    """Applies fe1's deployment/ha-manifest.yaml edits to the text as of ovw1 (the round trip)."""
    return _apply(text, MANIFEST_EDITS, "deployment/ha-manifest.yaml")


# Every frozen file fe1 edits, with its reverter (the chain entry's frozen_reverts).
FROZEN_REVERTERS = {
    DASHBOARD_REL: pre_fe1_dashboard,
    VERSION_REL: pre_fe1_version,
}
# The chain-pinned file fe1 edits, with its reverter (the chain entry's reverts).
PINNED_REVERTERS = {
    MANIFEST_REL: pre_fe1_manifest,
}
