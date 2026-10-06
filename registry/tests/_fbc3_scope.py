"""FB-C3 (Home Assistant shadow UX) scope: the new files it adds and the exact hunks of its ONE edit to a pinned pre-existing artifact.

FB-C3 changes no firmware. Its only edit to an artifact that older suites pin is the dashboard home-assistant/dashboards/ecco_pro.yaml
(Safety view: the SHADOW CHECK line, the shadow-episode banner and the technical shadow block; one chip-map entry; one tile-tone entry;
a header note). The FB-B3 reverter (_fbb3_ha_scope.pre_fbb3_dashboard) is an exact-match reverter whose hunks cover the whole Safety view, so
it can only be applied to the dashboard AS OF FB-B3: `pre_fbc3_dashboard` undoes exactly the hunks below first (newest first, like the
chain's `as_of`) and must reproduce the FB-B3 dashboard (== main @ 5e59d9c, unchanged by FB-C2 and the CI streamlining,
DASHBOARD_BASE_SHA) byte for byte.

Same technique as _fbb3_ha_scope.py: every hunk is (left, old, new, right) of unchanged context lines around the edit; the reverter swaps
`left + new + right` back to `left + old + right` (each must occur exactly once, else AssertionError); the inverse `add_fbc3_dashboard`
re-applies them. GENERATED from the git diff of the dashboard against main @ 5e59d9c (first generated against fd8edda, whose dashboard is
byte-identical; regenerated for the reconciliation with the final FB-C2 Verdict contract); do not hand-edit - regenerate and re-pin the
two hashes when the dashboard changes. Nothing here claims any other file. No I/O.
"""

from __future__ import annotations

import hashlib

BASE_COMMIT = "5e59d9c920dddc839c53a96f33691d3ff1a20534"   # main after FB-C2 (PR #63) and the CI streamlining (PR #64): this stage's parent


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# Every NEW repo file FB-C3 adds (the chain entry's `added_files`; exact POSIX paths, no glob). Existing files it modifies (the status /
# health packages, the dashboard, VERSION, the registries, older suites with `FB-C3` comments) are not declared anywhere.
ADDED_FILES = frozenset({
    "docs/architecture/fallback/FB_C3_IMPLEMENTATION_NOTES.md",
    "home-assistant/tests/test_ecco_shadow_check_ux.py",
    "registry/tests/_fbc3_scope.py",
    "registry/tests/test_failback_shadow_ha_contract.py",
})

# The ONLY files under home-assistant/ added by FB-C3 that spell the FB-A reserved token `ecco_fallback` (the HA suite asserts on the
# existing FB-B3 entity ids). `ecco_failback` is spelled only in the status package, as the five existing shadow entity ids (see
# test_fallback_profile_schema.py, the BLK-46 token-ban amendment); FALLBACK_PROFILE and FAILBACK_STATE stay banned everywhere there.
BANNED_FILES = frozenset({
    "home-assistant/tests/test_ecco_shadow_check_ux.py",
})

DASHBOARD_REL = "home-assistant/dashboards/ecco_pro.yaml"
DASHBOARD_BASE_SHA = "c78ed0f50fb49c6a3f9b3d9dc15356e4949f2e8f465add64a90fb98ae3bdc6f4"    # == _fbb3_ha_scope.DASHBOARD_AFTER_SHA == the dashboard on main (and fd8edda)
DASHBOARD_AFTER_SHA = "6ed2d63829624df8390bab7d3b05b035326a47a2f410091d7981a6c92069ed3a"
DASHBOARD_HUNKS = (
    (
        """# the compact System Health card, and an advisory Fallback banner in Manual Controls. Display plus
# operator-only buttons; nothing here is a control gate. See docs/architecture/fallback/.
""",
        """""",
        """# v7.18.0 (FB-C3, STAGED / NOT LIVE-PROVEN) adds the Safety-view SHADOW CHECK: an everyday "SHADOW CHECK · NO ACTION TAKEN"
# line, a shadow-episode banner, a Failback shadow evaluator block behind the existing technical-detail toggle, and a
# SHADOW chip / tile tone for the new Shadow Recovery status. Display only (it reads sensor.ecco_shadow_check, a decoder of
# the five existing dongle shadow strings); no control, no Energy Actions change.
""",
        """# Built for Home Assistant Sections view + Flexible Horseshoe Card + Sunsynk Power Flow Card (secondary/detail views) + ApexCharts + card-mod
# Entity IDs matched from the ECCO entity dump captured 2026-09-12.
""",
    ),
    (
        """                  const supChips = {'Healthy': ['HEALTHY', 'good'], 'Recovering': ['RECOVERING', 'info'], 'Awaiting Heartbeat': ['AWAITING', 'muted'], 'Suspect': ['SUSPECT', 'warn'], 'Lost': ['LOST', 'warn']};
                  const supChip = supChips[sup] || ['UNKNOWN', 'muted'];
""",
        """                  const fbChips = {'Ready': ['READY', 'good'], 'Drifted': ['DRIFTED', 'warn'], 'Not Captured': ['NOT SAVED', 'muted'], 'Invalidated': ['INVALIDATED', 'muted'], 'Blocked': ['BLOCKED', 'warn']};
""",
        """                  const fbChips = {'Ready': ['READY', 'good'], 'Drifted': ['DRIFTED', 'warn'], 'Not Captured': ['NOT SAVED', 'muted'], 'Invalidated': ['INVALIDATED', 'muted'], 'Blocked': ['BLOCKED', 'warn'], 'Shadow Recovery': ['SHADOW', 'warn']};
""",
        """                  const fbChip = fbChips[fb] || ['UNKNOWN', 'muted'];

""",
    ),
    (
        """                  const g = kv('g'), id = kv('id'), at = kv('at');
                  const tones = {
""",
        """                    'Ready': '#55e58e', 'Drifted': '#ffbd3d', 'Blocked': '#ffbd3d',
""",
        """                    'Ready': '#55e58e', 'Drifted': '#ffbd3d', 'Blocked': '#ffbd3d', 'Shadow Recovery': '#ffbd3d',
""",
        """                    'Not Captured': '#aab4c3', 'Invalidated': '#aab4c3', 'Unknown': '#aab4c3'
                  };
""",
    ),
    (
        """              rows: auto

""",
        """""",
        """          # ---- FB-C3 SHADOW EPISODE BANNER (DISPLAY ONLY; shown while a shadow episode is open) ----
          # Everything is a template ATTRIBUTE of sensor.ecco_shadow_check (a decoder of the five existing dongle shadow
          # strings); nothing here is decoded in the dashboard and nothing writes. It is shown whenever a shadow episode is
          # open, also when a recovery state (lease unreadable / lockout) keeps the canonical Fallback status: it is then shown
          # alongside, never in place of, that state.
          - type: markdown
            visibility:
              - condition: state
                entity: binary_sensor.ecco_shadow_episode_open
                state: 'on'
            grid_options:
              columns: 48
              rows: auto
            content: |
              {% set ep = state_attr('sensor.ecco_shadow_check', 'episode') or {} %}
              ### SHADOW CHECK - HOME ASSISTANT SUPERVISION WAS LOST

              **SHADOW mode: NOTHING WAS WRITTEN.** {{ ep.get('banner_lost', 'Home Assistant supervision was lost.') }}

              {{ ep.get('banner_would', 'If automatic failback were enabled it would have: nothing recorded.') }}

              {{ ep.get('banner_edge', '') }}
              {% if ep.get('banner_details') %}
              {{ ep.get('banner_details') }}
              {% endif %}
              Closes automatically after 5 minutes of continuous stable supervision.
              {% if state_attr('sensor.ecco_shadow_check', 'status_masks_shadow') %}

              The Fallback status above stays on **{{ state_attr('sensor.ecco_shadow_check', 'canonical_status') }}**, which takes priority over a shadow episode; this shadow information is shown alongside it.
              {% else %}

              While this episode is open the status above shows Shadow Recovery, so saved-profile warnings (drifted, lost or rolled back) are not shown there until it closes.
              {% endif %}
            card_mod: *ecco_card_mod

""",
        """          # ---- 1. SUPERVISION ----
          - type: markdown
""",
    ),
    (
        """              API client connected: **{{ 'yes' if is_state('binary_sensor.@@ECCO_PRIVATE_SLUG@@_ecco_api_client_connected', 'on') else 'no' }}** ·
              longest gap **{{ states('sensor.@@ECCO_PRIVATE_SLUG@@_ecco_supervision_longest_gap') }}**
""",
        """""",
        """            card_mod: *ecco_card_mod

          # ---- FB-C3 SHADOW CHECK LINE (everyday; DISPLAY ONLY; S5 6.4: the operator wording of the C2 Verdict, which is the
          # READINESS plan - "if Home Assistant were lost now" outside an episode, the continuation plan inside one) ----
          - type: markdown
            grid_options:
              columns: 48
              rows: auto
            content: |
              {% set s = states('sensor.ecco_shadow_check') %}
              {% set h = state_attr('sensor.ecco_shadow_check', 'verdict_heading') %}
              **SHADOW CHECK · NO ACTION TAKEN**{{ ' — ' ~ h if h else '' }}

              {{ 'Shadow check not available' if s in ['unknown', 'unavailable', ''] else s }}
""",
        """            card_mod: *ecco_card_mod

""",
    ),
    (
        """
              **Generation high-water (Home Assistant detection only):** `{{ states('sensor.ecco_fallback_generation_high_water') }}`
""",
        """""",
        """            card_mod: *ecco_card_mod
          # ---- FB-C3 SHADOW EVALUATOR DETAIL (technical detail only; DIAGNOSTIC, writes nothing) ----
          # Decoded by sensor.ecco_shadow_check from the five existing shadow strings (grammar and Verdict contract of FB-C2 as
          # merged, PR #63). Held in dongle RAM for this boot only: this is not persisted shadow history.
          - type: markdown
            visibility:
              - condition: state
                entity: input_boolean.ecco_safety_show_technical_detail
                state: 'on'
            grid_options:
              columns: 48
              rows: auto
            content: |
              {% set sc = 'sensor.ecco_shadow_check' %}
              {% set inp = state_attr(sc, 'inputs') or {} %}
              {% set ep = state_attr(sc, 'episode') or {} %}
              {% set sk = state_attr(sc, 'soak') or {} %}
              {% set hist = sk.get('gap_histogram') or {} %}
              {% set wr = sk.get('starts_seen_while_would_refuse') or {} %}
              {% set xh = sk.get('export_hazard_s') or {} %}
              {% set cs = sk.get('cache_s') or {} %}
              {% set unk = state_attr(sc, 'unknown_keys') or [] %}
              {% set raw = state_attr(sc, 'raw') or {} %}
              ### Failback shadow evaluator (diagnostic - writes nothing)

              {% set basis = {'readiness': 'if Home Assistant were lost now', 'episode': 'continuation while the shadow episode is open', 'not_evaluated': 'not evaluated yet', 'unrecognised': 'not recognised', 'not_available': 'not available'} %}
              **State:** `{{ state_attr(sc, 'shadow_state') or 'unknown' }}` · **Verdict ({{ basis.get(state_attr(sc, 'verdict_scope'), 'not available') }}):** `{{ state_attr(sc, 'verdict') or 'unknown' }}` - {{ states(sc) }}

              **Readiness plan (Inputs `pl` / `rs`):** `{{ inp.get('if_lost_plan', '-') }}` - {{ inp.get('if_lost_wording', '-') }} · reason `{{ inp.get('if_lost_reason', '-') }}`{{ ' (the plan underneath the modelled FB-F latch)' if state_attr(sc, 'latched') else '' }}

              **Inputs (last evaluation)**

              - Supervision: {{ inp.get('supervision', '-') }}, {{ inp.get('stable', '-') }}
              - Free Power: {{ inp.get('free_power', '-') }} · Dump to Grid: {{ inp.get('dump_to_grid', '-') }} · Register 244 test: {{ inp.get('register_244_test', '-') }} · Manual TOU: {{ inp.get('manual_tou', '-') }}
              - Known-good profile: {{ inp.get('profile_class', '-') }} · generation {{ inp.get('profile_generation', '-') }} · binding `{{ inp.get('profile_binding', '-') }}`
              - Live settings vs profile: {{ inp.get('e1', '-') }} · context: {{ inp.get('context', '-') }} · info registers (never restored in V1): {{ inp.get('info', '-') }}
              - Live data cache: {{ inp.get('cache', '-') }} · write locks: {{ inp.get('locks', '-') }}
              - Registers that differ: {{ inp.get('delta_count', '-') }} · projected frames: {{ (inp.get('projected_frames') or ['none']) | join(', ') }}
              - If an absent lease record were accepted as clear (`alt`): `{{ inp.get('absence_accepted_plan', '-') }}` · after the awaited pre-empt / restore (`pa`): `{{ inp.get('projected_after_plan', '-') }}`

              **Last episode** `{{ ep.get('id', '-') }}` · phase {{ ep.get('phase', '-') }} · kind {{ ep.get('kind', '-') }} · trigger {{ ep.get('trigger', '-') }}

              - Loss declared: {{ ep.get('edge_time', '-') }} (dongle uptime {{ ep.get('edge_uptime_s', '-') }} s) · API client at the edge: {{ ep.get('client_at_edge', '-') }} · no-client reboot margin: {{ 'n/a (API client connected)' if ep.get('reboot_margin_s', '-') == '-' else ep.get('reboot_margin_s') ~ ' s' }}
              - Frozen edge plan: `{{ ep.get('edge_plan', '-') }}` (underlying plan when latched: `{{ ep.get('underlying_plan', '-') }}`) · FB-A result `{{ ep.get('fba_result', '-') }}` · blocking domain: {{ ep.get('blocking_domain', '-') }}
              - Pre-empt: {{ (ep.get('preempt') or ['none']) | join(' + ') }} · projected frames: {{ (ep.get('projected_frames') or ['none']) | join(', ') }} · registers differing: {{ ep.get('delta_count', '-') }}
              - Home Assistant back after: {{ ep.get('returned_after', '-') }} (gap {{ ep.get('return_gap_s', '-') }} s) · re-lost {{ ep.get('re_lost', '-') }} · verdict changes {{ ep.get('verdict_changes', '-') }}
              - Closed after: {{ ep.get('closed_after', '-') }} · close outcome: {{ ep.get('close_outcome', '-') }}
              - A future failback would have: {{ ep.get('would_have', '-') }}

              **This boot** · boot id `{{ sk.get('boot_id', '-') }}` · episodes {{ sk.get('episodes', '-') }} · ECCO Reset Reason: {{ states('sensor.@@ECCO_PRIVATE_SLUG@@_ecco_reset_reason') }}

              - Heartbeat gaps: {% for k, v in hist.items() %}{{ k }}: {{ v }}{{ ' · ' if not loop.last else '' }}{% endfor %}
              - Longest gap {{ sk.get('max_gap_s', '-') }} s · last long gap {{ sk.get('last_long_gap_s', '-') }} s · gaps missed {{ sk.get('gaps_missed', '-') }}
              - Start attempts seen while a failback would refuse: Free Power {{ wr.get('free_power', '-') }} · Dump to Grid {{ wr.get('dump_to_grid', '-') }} · Register 244 test {{ wr.get('register_244_test', '-') }} · profile changes {{ wr.get('profile_changes', '-') }}
              - API client drops {{ sk.get('api_client_drops', '-') }} · longest without a client {{ sk.get('longest_no_client_s', '-') }} s
              - Export hazard seen: yes {{ xh.get('yes', '-') }} s · unknown {{ xh.get('unknown', '-') }} s
              - Live-data cache: fresh {{ cs.get('fresh', '-') }} s · pre-fence {{ cs.get('pre_fence', '-') }} s · other {{ cs.get('other', '-') }} s
              {% if unk %}
              **Unrecognised keys (shown raw):** {% for u in unk %}`{{ u }}` {% endfor %}
              {% endif %}
              **Raw strings**

              - Inputs: `{{ raw.get('inputs', '-') }}`
              - Episode: `{{ raw.get('episode', '-') }}`
              - Soak: `{{ raw.get('soak', '-') }}`

              {{ state_attr(sc, 'scope_note') or '' }}
""",
        """            card_mod: *ecco_card_mod
          - type: entities
""",
    ),
)


# PUBLIC-EXPORT: this generated module spells no private device slug. Its hunks carry SLUG_MARK where the private dashboard spells
# the slug, and are bound ONCE, here at import, to the exact private slug that _pub0_scope reconstructs from its single declared
# literal (_pub0_scope.PRIVATE_SLUG). The bound tuples are byte-identical to the hunks as generated from the git diff:
# registry/tests/test_pub0_transition.py [7] pins the sha256 of every bound tuple, so the conversion cannot drift.
import _pub0_scope as _pub0  # noqa: E402

SLUG_MARK = "@@ECCO_PRIVATE_SLUG@@"


def _bind(hunks: tuple) -> tuple:
    return tuple(tuple(s.replace(SLUG_MARK, _pub0.PRIVATE_SLUG) for s in hunk) for hunk in hunks)


DASHBOARD_HUNKS = _bind(DASHBOARD_HUNKS)

def _swap(text: str, find: str, put: str, what: str, state: str) -> str:
    n = text.count(find)
    if n != 1:
        raise AssertionError(f"FB-C3 scope: {what} must be {state} exactly once, found {n}x: {find[:70]!r}")
    i = text.index(find)
    return text[:i] + put + text[i + len(find):]


def _revert(text: str, hunks, what: str) -> str:
    out = text
    for k, (left, old, new, right) in reversed(list(enumerate(hunks))):
        out = _swap(out, left + new + right, left + old + right, f"{what} hunk {k}", "present")
    for k, (left, old, new, right) in enumerate(hunks):
        n = out.count(left + old + right)
        if n != 1:
            raise AssertionError(f"FB-C3 scope: the {what} hunk {k} anchor must be unique once reverted, found {n}x")
    return out


def _apply(text: str, hunks, what: str) -> str:
    out = text
    for k, (left, old, new, right) in enumerate(hunks):
        if (left + new + right) in out:
            raise AssertionError(f"FB-C3 scope: {what} hunk {k} already present")
        out = _swap(out, left + old + right, left + new + right, f"{what} hunk {k} anchor", "found")
    return out


def pre_fbc3_dashboard(text: str) -> str:
    """The dashboard with exactly the FB-C3 edits undone (the FB-B3 dashboard, DASHBOARD_BASE_SHA)."""
    return _revert(text, DASHBOARD_HUNKS, "dashboard")


def add_fbc3_dashboard(text: str) -> str:
    return _apply(text, DASHBOARD_HUNKS, "dashboard")
