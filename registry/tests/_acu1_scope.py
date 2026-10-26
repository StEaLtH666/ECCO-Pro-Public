"""acu1 (ECCO TOU Settings card on the dashboard) change scope: exactly what acu1 changes in the files the pub0 export froze and in the
chain-pinned deployment manifest, and its exact inverse.

Same technique as the earlier post-export scope modules: every verbatim edit is held HERE as the single source of truth, as an exact
(before, after) pair generated from the real diff and round-trip-checked, and each reverter raises unless each of its edits is present
exactly once. The post-export chain entry `acu1` (registry/tests/_scope_chain.py POST_EXPORT_ENTRIES, appended last after acs1;
registry/tests/_pex.py) carries one frozen reverter per edited frozen file and one chain reverter for the manifest.

WHAT acu1 IS. The ECCO TOU Settings card (frontend/ecco-tou-settings-card, new files): the six live TOU slots and a guarded editor for the
target SOC, the power and the charge source of one slot, which calls ONLY the installed ACS1 editor scripts (Review, typed confirmation,
Apply, Acknowledge) through script.turn_on and reads the editor's helpers back. OWNER-APPROVED 2026-10-25 (A2, with decisions D1-D9 and
the refinements to D5 and D6): a separate card (the read-only catalogue card is untouched); it replaces section 7's read-only TOU table;
D3 as approved (the two FB-C3 display decoders read for the shadow latch) was NOT implementable: the FB-C3 shadow-check UX suite (check 15) pins that no frontend file names them, so the card explains the latch only on the Review's own refusal; one service shape (script.turn_on); a fixed 300 s spacing
between Applies, not configurable; Undo only after APPLIED AND VERIFIED with the records and a current live read agreeing (a recent report, or unchanged under a current
configuration poll); start times
display-only (L1); the Acknowledge phrase typed in the card; entry id acu1, dashboard 7.22.0.
  - home-assistant/dashboards/ecco_pro.yaml (pub0 target, FROZEN): the v7.22.0 header note, and section 7 of the Inverter / Advanced
    view keeps its heading and badge while its two read-only markdown cards (the register 244 note and the six-row table) become the
    card, configured with the quoted default device slug (the site renderer renders it for a site);
  - VERSION.yaml (enrolled, FROZEN): dashboard 7.22.0, staged (tested_in_home_assistant stays false); the 7.21.1 record is kept;
  - deployment/ha-manifest.yaml (chain-PINNED): one frontend_assets stanza (copy and resource registration stay manual).
ZERO firmware, Home Assistant package, registry, Intelligence or ecco_core change; ZERO Modbus operation; the card itself writes nothing
and calls no service other than the three ACS1 scripts (tools/tests/test_tou_settings_card.py and the card's own suite pin that).

NOT frozen (ordinary edits, nothing to declare): CHANGELOG.md, docs. Added: this module, the card folder and its CI wrapper suite.

This module imports no other scope module, not _scope_chain (the chain imports it) and not _pex. No I/O.
"""

from __future__ import annotations

import hashlib

# Public main the change is based on.
BASE_COMMIT = "a7235433ce711e6a8fae5dab0fc8ca6c6f533de6"

ADDED_FILES = frozenset({
    'frontend/ecco-tou-settings-card/.gitignore',
    'frontend/ecco-tou-settings-card/README.md',
    'frontend/ecco-tou-settings-card/build.mjs',
    'frontend/ecco-tou-settings-card/dist/ecco-tou-settings-card.js',
    'frontend/ecco-tou-settings-card/examples/tou-settings-example.yaml',
    'frontend/ecco-tou-settings-card/hacs.json',
    'frontend/ecco-tou-settings-card/package-lock.json',
    'frontend/ecco-tou-settings-card/package.json',
    'frontend/ecco-tou-settings-card/src/actions.ts',
    'frontend/ecco-tou-settings-card/src/ecco-tou-settings-card.ts',
    'frontend/ecco-tou-settings-card/src/model.ts',
    'frontend/ecco-tou-settings-card/src/render.ts',
    'frontend/ecco-tou-settings-card/src/styles.ts',
    'frontend/ecco-tou-settings-card/src/types.ts',
    'frontend/ecco-tou-settings-card/test/build.test.ts',
    'frontend/ecco-tou-settings-card/test/card.test.ts',
    'frontend/ecco-tou-settings-card/test/dom-shim.ts',
    'frontend/ecco-tou-settings-card/test/fixtures.ts',
    'frontend/ecco-tou-settings-card/test/model.test.ts',
    'frontend/ecco-tou-settings-card/test/render.test.ts',
    'frontend/ecco-tou-settings-card/test/static.test.ts',
    'frontend/ecco-tou-settings-card/tsconfig.json',
    'registry/tests/_acu1_scope.py',
    'tools/tests/test_tou_settings_card.py',
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
        raise AssertionError(f"acu1 scope: {what} must be {state} exactly once, found {n}x: {find[:70]!r}")
    i = text.index(find)
    return text[:i] + put + text[i + len(find):]


def _revert(text: str, edits: tuple, what: str) -> str:
    out = text
    for k, (before, after) in reversed(list(enumerate(edits))):
        out = _swap(out, after, before, f"{what} edit {k}", "present")
    for k, (before, _after) in enumerate(edits):
        n = out.count(before)
        if n != 1:
            raise AssertionError(f"acu1 scope: {what} anchor {k} must be unique once the edits are removed, found {n}x")
    return out


def _apply(text: str, edits: tuple, what: str) -> str:
    out = text
    for k, (before, after) in enumerate(edits):
        if after in out:
            raise AssertionError(f"acu1 scope: {what} edit {k} is already present")
        out = _swap(out, before, after, f"{what} anchor {k}", "found")
    return out


# ---- (PEX frozen edit) home-assistant/dashboards/ecco_pro.yaml -----------------------------------------------------------------------
DASHBOARD_REL = "home-assistant/dashboards/ecco_pro.yaml"
# The v7.22.0 header note, then the body of section 7 of the Inverter / Advanced view (the heading card stays).
DASHBOARD_0_OLD = _blk(r"""
# the entity ids that exist. Display only: no control, firmware, package or automation change.
""")
DASHBOARD_0_NEW = _blk(r"""
# the entity ids that exist. Display only: no control, firmware, package or automation change.
# v7.22.0 (ACU1, STAGED / NOT LIVE-PROVEN) replaces the read-only TOU table of section 7 of the Inverter / Advanced view with the
# ECCO TOU Settings card (frontend/ecco-tou-settings-card, a manual Lovelace resource): the six live slots and a guarded editor for
# the target SOC, the power and the charge source of one slot, through the installed ACS1 editor scripts only (Review, typed
# confirmation, Apply; Acknowledge after an UNCERTAIN outcome). The card holds no safety logic and no other write path; start times
# stay display-only (the site's layout wraps midnight, L1). The heading of section 7 and every other section are unchanged.
""")
DASHBOARD_1_OLD = _blk(r"""
          - type: markdown
            grid_options:
              columns: 48
              rows: 2
            content: |
              {% if is_state('sensor.ecco_clock_dongle_ecco_load_limit_exp_ess_non_ess', 'Zero Export') %}
              ℹ️ Load Limit = **Zero Export** — the **Discharge limit** column below caps battery discharge per slot; grid supplies any load above it.
              {% elif is_state('sensor.ecco_clock_dongle_ecco_load_limit_exp_ess_non_ess', 'Allow Export') %}
              ℹ️ Load Limit = **Allow Export** — the **Export limit** column below caps export power per slot.
              {% else %}
              ℹ️ Load Limit = **{{ states('sensor.ecco_clock_dongle_ecco_load_limit_exp_ess_non_ess') }}** — the Power column's exact effect in this mode is not confirmed; shown as informational only.
              {% endif %}
            card_mod: *ecco_card_mod
          - type: markdown
            grid_options:
              columns: 48
              rows: 6
            content: >
              {% set label = 'Discharge limit' if is_state('sensor.ecco_clock_dongle_ecco_load_limit_exp_ess_non_ess', 'Zero Export') else 'Export limit' if is_state('sensor.ecco_clock_dongle_ecco_load_limit_exp_ess_non_ess', 'Allow Export') else 'Power' %}

              | Slot | Time window | {{ label }} | Target SOC | Charge from |

              |:---:|:---|---:|---:|:---|

              | **1** | {{ states('sensor.ecco_clock_dongle_ecco_timezone1_time') }}–{{ states('sensor.ecco_clock_dongle_ecco_timezone2_time') }} | {{ states('sensor.ecco_clock_dongle_ecco_timezone1_power')|float(0)|round(0)|int }} W | {{ states('sensor.ecco_clock_dongle_ecco_timezone1_soc')|float(0)|round(0)|int }}% | {{ states('sensor.ecco_clock_dongle_ecco_timezone1_charge') }} |

              | **2** | {{ states('sensor.ecco_clock_dongle_ecco_timezone2_time') }}–{{ states('sensor.ecco_clock_dongle_ecco_timezone3_time') }} | {{ states('sensor.ecco_clock_dongle_ecco_timezone2_power')|float(0)|round(0)|int }} W | {{ states('sensor.ecco_clock_dongle_ecco_timezone2_soc')|float(0)|round(0)|int }}% | {{ states('sensor.ecco_clock_dongle_ecco_timezone2_charge') }} |

              | **3** | {{ states('sensor.ecco_clock_dongle_ecco_timezone3_time') }}–{{ states('sensor.ecco_clock_dongle_ecco_timezone4_time') }} | {{ states('sensor.ecco_clock_dongle_ecco_timezone3_power')|float(0)|round(0)|int }} W | {{ states('sensor.ecco_clock_dongle_ecco_timezone3_soc')|float(0)|round(0)|int }}% | {{ states('sensor.ecco_clock_dongle_ecco_timezone3_charge') }} |

              | **4** | {{ states('sensor.ecco_clock_dongle_ecco_timezone4_time') }}–{{ states('sensor.ecco_clock_dongle_ecco_timezone5_time') }} | {{ states('sensor.ecco_clock_dongle_ecco_timezone4_power')|float(0)|round(0)|int }} W | {{ states('sensor.ecco_clock_dongle_ecco_timezone4_soc')|float(0)|round(0)|int }}% | {{ states('sensor.ecco_clock_dongle_ecco_timezone4_charge') }} |

              | **5** | {{ states('sensor.ecco_clock_dongle_ecco_timezone5_time') }}–{{ states('sensor.ecco_clock_dongle_ecco_timezone6_time') }} | {{ states('sensor.ecco_clock_dongle_ecco_timezone5_power')|float(0)|round(0)|int }} W | {{ states('sensor.ecco_clock_dongle_ecco_timezone5_soc')|float(0)|round(0)|int }}% | {{ states('sensor.ecco_clock_dongle_ecco_timezone5_charge') }} |

              | **6** | {{ states('sensor.ecco_clock_dongle_ecco_timezone6_time') }}–{{ states('sensor.ecco_clock_dongle_ecco_timezone1_time') }} | {{ states('sensor.ecco_clock_dongle_ecco_timezone6_power')|float(0)|round(0)|int }} W | {{ states('sensor.ecco_clock_dongle_ecco_timezone6_soc')|float(0)|round(0)|int }}% | {{ states('sensor.ecco_clock_dongle_ecco_timezone6_charge') }} |
            card_mod: *ecco_card_mod

""")
DASHBOARD_1_NEW = _blk(r"""
          # ACU1: the six live slots and the guarded editor (frontend/ecco-tou-settings-card, a manual Lovelace resource). The card
          # calls only the installed ACS1 editor scripts (Review, typed confirmation, Apply, Acknowledge) and reads the editor's
          # helpers back; it has no write path of its own, holds no safety logic, and leaves start times display-only (L1).
          - type: custom:ecco-tou-settings-card
            title: Slots and guarded editor (ACS1)
            entity_prefix: "ecco_clock_dongle"
            grid_options:
              columns: 48
              rows: auto

""")
DASHBOARD_EDITS = (
    (DASHBOARD_0_OLD, DASHBOARD_0_NEW),
    (DASHBOARD_1_OLD, DASHBOARD_1_NEW),
)


def pre_acu1_dashboard(text: str) -> str:
    """home-assistant/dashboards/ecco_pro.yaml with exactly acu1's edits undone (a frozen reverter of chain entry acu1, PEX)."""
    return _revert(text, DASHBOARD_EDITS, "home-assistant/dashboards/ecco_pro.yaml")


pre_acu1_dashboard.edits = DASHBOARD_EDITS   # the PEX contract: a reverter exposes its exact (before, after) pairs


def add_acu1_dashboard(text: str) -> str:
    """Applies acu1's home-assistant/dashboards/ecco_pro.yaml edits to the earlier text (the round trip)."""
    return _apply(text, DASHBOARD_EDITS, "home-assistant/dashboards/ecco_pro.yaml")

# ---- (PEX frozen edit) VERSION.yaml --------------------------------------------------------------------------------------------------
VERSION_REL = "VERSION.yaml"
# Dashboard 7.21.1 -> 7.22.0 (staged); the 7.21.1 record is kept below the new note.
VERSION_0_OLD = _blk(r"""
    version: "7.21.1"
    path: home-assistant/dashboards/ecco_pro.yaml
""")
VERSION_0_NEW = _blk(r"""
    version: "7.22.0"
    path: home-assistant/dashboards/ecco_pro.yaml
    # v7.22.0 (ACU1) replaces the read-only TOU table of section 7 of the Inverter / Advanced view with the ECCO TOU
    # Settings card: the six live slots and a guarded editor for the target SOC, the power and the charge source of one
    # slot, through the installed ACS1 editor scripts only (Review, typed confirmation, Apply; Acknowledge after an
    # UNCERTAIN outcome). The card holds no safety logic and no other write path; start times stay display-only. It is
    # STAGED: tested_in_home_assistant stays false until the card is exercised on the reference installation. The 7.21.1
    # record follows.
""")
VERSION_EDITS = (
    (VERSION_0_OLD, VERSION_0_NEW),
)


def pre_acu1_version(text: str) -> str:
    """VERSION.yaml with exactly acu1's edits undone (a frozen reverter of chain entry acu1, PEX)."""
    return _revert(text, VERSION_EDITS, "VERSION.yaml")


pre_acu1_version.edits = VERSION_EDITS   # the PEX contract: a reverter exposes its exact (before, after) pairs


def add_acu1_version(text: str) -> str:
    """Applies acu1's VERSION.yaml edits to the earlier text (the round trip)."""
    return _apply(text, VERSION_EDITS, "VERSION.yaml")

# ---- (chain-pinned edit) deployment/ha-manifest.yaml -----------------------------------------------------------------------------------
MANIFEST_REL = "deployment/ha-manifest.yaml"
# One frontend_assets stanza, the last of the list, before the firmware section.
MANIFEST_0_OLD = _blk(r"""

firmware:
  source: firmware/ecco_clock_dongle_stage3_4_free_power.yaml
""")
MANIFEST_0_NEW = _blk(r"""
  # ECCO TOU Settings card - ACU1 (the six live TOU slots and a guarded editor that calls only the
  # installed ACS1 editor scripts; no write path of its own). Copying the file and registering the
  # resource stay deliberate manual steps.
  - source: frontend/ecco-tou-settings-card/dist/ecco-tou-settings-card.js
    destination: /config/www/ecco/ecco-tou-settings-card.js
    method: ssh_file_copy
    restart_required: false
    resource_registration: manual
    resource_url: /local/ecco/ecco-tou-settings-card.js

firmware:
  source: firmware/ecco_clock_dongle_stage3_4_free_power.yaml
""")
MANIFEST_EDITS = (
    (MANIFEST_0_OLD, MANIFEST_0_NEW),
)


def pre_acu1_manifest(text: str) -> str:
    """deployment/ha-manifest.yaml with exactly acu1's edits undone (the chain reverter of entry acu1 for the pinned manifest)."""
    return _revert(text, MANIFEST_EDITS, "deployment/ha-manifest.yaml")


pre_acu1_manifest.edits = MANIFEST_EDITS   # the PEX contract: a reverter exposes its exact (before, after) pairs


def add_acu1_manifest(text: str) -> str:
    """Applies acu1's deployment/ha-manifest.yaml edits to the earlier text (the round trip)."""
    return _apply(text, MANIFEST_EDITS, "deployment/ha-manifest.yaml")


# Every frozen file acu1 edits, with its reverter (the chain entry's frozen_reverts).
FROZEN_REVERTERS = {
    DASHBOARD_REL: pre_acu1_dashboard,
    VERSION_REL: pre_acu1_version,
}
# The chain-pinned file acu1 edits, with its reverter (the chain entry's reverts).
PINNED_REVERTERS = {
    MANIFEST_REL: pre_acu1_manifest,
}
