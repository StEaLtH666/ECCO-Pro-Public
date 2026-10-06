"""FB-B3 (Slice B + C + integration) edits to the three PRE-EXISTING non-firmware artifacts the final stage changes, as exact hunks
against main @ 87e6151 (GENERATED from the git diff; do not hand-edit - regenerate and re-pin the chain checkpoint when the
artifacts change): the dashboard home-assistant/dashboards/ecco_pro.yaml, the deployment manifest deployment/ha-manifest.yaml
and VERSION.yaml.

Same technique as _fbb3_scope.py / _fbb2_scope.py: every hunk is (left, old, new, right) of unchanged context lines around the
edit; `pre_fbb3_*` undoes exactly these hunks (each `after` must occur exactly once, else AssertionError) and reproduces the
file on main @ BASE_COMMIT byte for byte (BASE_SHA); `add_fbb3_*` is the inverse. Nothing here claims any other file.

No I/O.
"""

from __future__ import annotations

import hashlib

BASE_COMMIT = "87e6151fa04a2cada568ef6c36a871a8ffcc7303"

def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


DASHBOARD_REL = "home-assistant/dashboards/ecco_pro.yaml"
DASHBOARD_BASE_SHA = "63b35e4197a14339b006539b9310f400b2cd556eac5c06fab75e72f7bf917b3c"
DASHBOARD_AFTER_SHA = "c78ed0f50fb49c6a3f9b3d9dc15356e4949f2e8f465add64a90fb98ae3bdc6f4"
DASHBOARD_HUNKS = (
    (
        """# 2026-09-25 with a successful return to READY. See
# frontend/ecco-energy-actions-card/README.md and docs/FREE_POWER_LIVE_PROOF_2026-09-24.md.
""",
        """""",
        """# v7.17.0 (FB-B3, STAGED / NOT LIVE-PROVEN) adds the Safety view (supervision + Known-Good Profile),
# an Overview Known-Good Profile tile, SUPERVISION / FALLBACK hero chips, Supervision / Fallback rows in
# the compact System Health card, and an advisory Fallback banner in Manual Controls. Display plus
# operator-only buttons; nothing here is a control gate. See docs/architecture/fallback/.
""",
        """# Built for Home Assistant Sections view + Flexible Horseshoe Card + Sunsynk Power Flow Card (secondary/detail views) + ApexCharts + card-mod
# Entity IDs matched from the ECCO entity dump captured 2026-09-12.
""",
    ),
    (
        """                  const snapshot = get('binary_sensor.@@ECCO_PRIVATE_SLUG@@_free_power_snapshot_valid');
                  const snapshotPending = snapshot === 'on' && !freeActive && !freeBusy;
""",
        """""",
        """                  // FB-B3: display words only (sensor.ecco_supervision_status / sensor.ecco_fallback_status).
                  // Deliberately NOT in `required` (a fallback Unknown must not turn the headline into
                  // STATUS PARTIAL) and only supervision Lost is hardAttention; fallback states are not.
                  const sup = get('sensor.ecco_supervision_status');
                  const fb = get('sensor.ecco_fallback_status');
""",
        """
                  const required = [comm,runtime,telemetry,configOnline,ntp,cache,inverter,warning,fault,manualState,rtcState,freeOpState,freeActiveState,snapshot];
""",
    ),
    (
        """                    warning !== '00000000' ||
                    fault !== '0000000000000000' ||
""",
        """                    snapshotPending;
""",
        """                    snapshotPending ||
                    sup === 'Lost';
""",
        """                  const busy = manualBusy || rtcBusy || freeBusy || freeActive;

""",
    ),
    (
        """                  const txChip = chipState(true, manualBusy || freeBusy || freeActive, txUnknown);
                  const recoveryChip = chipState(!snapshotPending, false, unknown(snapshot) || unknown(freeActiveState));
""",
        """""",
        """                  const supChips = {'Healthy': ['HEALTHY', 'good'], 'Recovering': ['RECOVERING', 'info'], 'Awaiting Heartbeat': ['AWAITING', 'muted'], 'Suspect': ['SUSPECT', 'warn'], 'Lost': ['LOST', 'warn']};
                  const supChip = supChips[sup] || ['UNKNOWN', 'muted'];
                  const fbChips = {'Ready': ['READY', 'good'], 'Drifted': ['DRIFTED', 'warn'], 'Not Captured': ['NOT SAVED', 'muted'], 'Invalidated': ['INVALIDATED', 'muted'], 'Blocked': ['BLOCKED', 'warn']};
                  const fbChip = fbChips[fb] || ['UNKNOWN', 'muted'];
""",
        """
                  const soc = num('sensor.@@ECCO_PRIVATE_SLUG@@_ecco_battery_soc');
""",
    ),
    (
        """                      ${pill('TRANSACTIONS', txChip[0], txChip[1])}
                      ${pill('RECOVERY', recoveryChip[0], recoveryChip[1])}
""",
        """""",
        """                      ${pill('SUPERVISION', supChip[0], supChip[1])}
                      ${pill('FALLBACK', fbChip[0], fbChip[1])}
""",
        """                    </div>

""",
    ),
    (
        """                  health: >
                    [[[
""",
        """                      const tone = s => s === 'HEALTHY' ? '#39d27a' : s === 'WARNING' ? '#ffbd3d' : s === 'FAILED' ? '#ff5f6d' : '#aab4c3';
                      const read = id => {
                        const s = states[id]?.state;
                        return ['HEALTHY', 'WARNING', 'FAILED'].includes(s) ? s : 'UNKNOWN';
""",
        """                      const tone = s => s === 'HEALTHY' ? '#39d27a' : s === 'DEGRADED' ? '#66b3ff' : s === 'WARNING' ? '#ffbd3d' : s === 'FAILED' ? '#ff5f6d' : '#aab4c3';
                      const read = id => {
                        const s = states[id]?.state;
                        return ['HEALTHY', 'DEGRADED', 'WARNING', 'FAILED'].includes(s) ? s : 'UNKNOWN';
""",
        """                      };
                      const rows = [
""",
    ),
    (
        """                        ['Free Power', read('sensor.ecco_health_free_power')],
                        ['Configuration', read('sensor.ecco_health_configuration')],
""",
        """                        ['Inverter Telemetry', read('sensor.ecco_health_inverter_telemetry')]
""",
        """                        ['Inverter Telemetry', read('sensor.ecco_health_inverter_telemetry')],
                        ['Supervision', read('sensor.ecco_health_supervision')],
                        ['Fallback', read('sensor.ecco_health_fallback')]
""",
        """                      ];
                      return `<div style="display:grid;gap:6px;">
""",
    ),
    (
        """                  box-shadow: 0 12px 32px rgba(0,0,0,0.22);
                }
""",
        """""",
        """
          # ---- KNOWN-GOOD PROFILE (FB-B3; READ-ONLY tile) ----
          # Display only: state word + subline of sensor.ecco_fallback_status and a one-line summary
          # of the saved profile. No write action here - tap opens the standard more-info dialog.
          # Saving, arming and invalidating live ONLY on the Safety view.
          - type: custom:button-card
            section_mode: true
            entity: sensor.ecco_fallback_status
            name: Known-Good Profile
            icon: mdi:shield-check-outline
            show_name: true
            show_icon: true
            show_state: false
            tap_action:
              action: more-info
            custom_fields:
              body: >
                [[[
                  const get = id => states[id]?.state ?? 'unknown';
                  const word = get('sensor.ecco_fallback_status');
                  const sub = states['sensor.ecco_fallback_status']?.attributes?.subline ?? '';
                  const b2 = ';' + get('sensor.@@ECCO_PRIVATE_SLUG@@_ecco_fallback_profile_summary') + ';';
                  const kv = k => { const i = b2.indexOf(';' + k + '='); return i < 0 ? '-' : b2.slice(i + k.length + 2).split(';')[0]; };
                  const g = kv('g'), id = kv('id'), at = kv('at');
                  const tones = {
                    'Ready': '#55e58e', 'Drifted': '#ffbd3d', 'Blocked': '#ffbd3d',
                    'Not Captured': '#aab4c3', 'Invalidated': '#aab4c3', 'Unknown': '#aab4c3'
                  };
                  const colour = tones[word] || '#aab4c3';
                  const when = at === '0' ? 'capture time unknown' : new Date(Number(at) * 1000).toLocaleString();
                  const saved = g === '-' ? 'No profile saved yet' : `Saved ${when} \u00b7 generation ${g} \u00b7 ID ${id.slice(0, 8)}`;
                  return `<div>
                    <div style="display:flex;align-items:center;justify-content:space-between;gap:10px;">
                      <div style="font-size:22px;font-weight:900;letter-spacing:.3px;color:${colour};">${String(word).toUpperCase()}</div>
                      <div style="font-size:10px;font-weight:800;letter-spacing:.45px;color:rgba(255,255,255,.42);">OPEN THE SAFETY TAB</div>
                    </div>
                    <div style="font-size:12px;color:rgba(255,255,255,.62);margin-top:4px;">${saved}</div>
                    <div style="font-size:12px;color:rgba(255,255,255,.62);margin-top:2px;">${sub}</div>
                  </div>`;
                ]]]
            styles:
              card:
                - border-radius: 18px
                - padding: 14px 16px
                - background: linear-gradient(145deg, rgba(20,28,45,0.98), rgba(10,15,27,0.98))
                - border: 1px solid rgba(255,255,255,0.08)
                - box-shadow: 0 10px 30px rgba(0,0,0,0.22)
              grid:
                - grid-template-areas: '"i n" "body body"'
                - grid-template-columns: 34px 1fr
                - grid-template-rows: min-content 1fr
                - row-gap: 8px
              icon:
                - width: 24px
                - color: '#8f7cff'
              name:
                - justify-self: start
                - align-self: center
                - font-size: 13px
                - font-weight: 700
                - text-transform: uppercase
                - letter-spacing: 0.05em
                - color: rgba(255,255,255,0.5)
              custom_fields:
                body:
                  - justify-self: stretch
                  - align-self: start
                  - width: 100%
            grid_options:
              columns: 48
              rows: 3
""",
        """
          # ---- ECCO BLENDED PV FORECAST HEADLINES ----
""",
    ),
    (
        """              columns: 48
              rows: auto
""",
        """""",
        """  - title: Safety
    path: ecco-safety
    icon: mdi:shield-home-outline
    type: sections
    max_columns: 4
    dense_section_placement: true
    sections:
      # ================= SAFETY (FB-B3: supervision + Known-Good Profile) =================
      # Display + operator surface for the Fallback Profile. Everything shown here is a template
      # over firmware entities (B1-B10) and the display layer in ecco_fallback_status.yaml; the
      # safety decoders (244 / 243 / source / 232 / 248, drift cells) are template ATTRIBUTES of
      # sensor.ecco_fallback_status, not dashboard logic. There are no HA saved-view copy sensors.
      # Home Assistant is NOT a control authority: the only writes reachable from this page are
      # (a) the firmware Review button (zero-write), (b) the Arm switch, toggled by a HUMAN tap
      # (it turns itself off after 2 minutes), and (c) the three operator scripts, each behind a
      # confirmation dialog and visible only while the matching *_available sensor is on. The
      # firmware re-validates arm, id, phrase, TTL and every precondition. No automation or
      # script turns the arm on. There is no restore control and no shadow-evaluator control.
      - type: grid
        column_span: 4
        cards:
          - type: heading
            heading: Safety
            heading_style: title
            icon: mdi:shield-home-outline
            badges:
              - type: entity
                entity: sensor.ecco_supervision_status
                name: Supervision
                show_state: true
                color: green
              - type: entity
                entity: sensor.ecco_fallback_status
                name: Fallback
                show_state: true
                color: blue
              - type: entity
                entity: binary_sensor.@@ECCO_PRIVATE_SLUG@@_ntp_synced
                name: NTP
                show_state: true
                color: blue
            grid_options:
              columns: 48
              rows: auto

          # ---- 1. SUPERVISION ----
          - type: markdown
            grid_options:
              columns: 48
              rows: auto
            content: |
              {% set d = states('sensor.ecco_supervision_status') %}
              ### Home Assistant supervision: {{ d | upper }}

              {{ state_attr('sensor.ecco_supervision_status', 'subline') }}

              Stable: **{{ 'yes' if is_state('binary_sensor.@@ECCO_PRIVATE_SLUG@@_ecco_supervision_stable', 'on') else 'no' }}** \u00b7
              API client connected: **{{ 'yes' if is_state('binary_sensor.@@ECCO_PRIVATE_SLUG@@_ecco_api_client_connected', 'on') else 'no' }}** \u00b7
              longest gap **{{ states('sensor.@@ECCO_PRIVATE_SLUG@@_ecco_supervision_longest_gap') }}**
            card_mod: *ecco_card_mod

          # ---- 2. GENERATION HIGH-WATER WARNING (shown only when regressed) ----
          - type: markdown
            visibility:
              - condition: state
                entity: sensor.ecco_fallback_status_code
                state: profile_regressed
            grid_options:
              columns: 48
              rows: auto
            content: |
              ### \u26a0 Saved profile may have been lost or rolled back

              The dongle reports a lower profile generation than Home Assistant has seen
              (**generation {{ states('sensor.@@ECCO_PRIVATE_SLUG@@_ecco_fallback_profile_summary').split(';')[0] | replace('g=', '') }}**
              on the dongle, highest seen **{{ states('sensor.ecco_fallback_generation_high_water') }}**).
              Lease records may also be affected - check Free Power and Dump to Grid status first.
              This is a detection warning only; it never blocks anything. Review your configuration and
              save again, or investigate before resetting the detection history (see Technical detail).
            card_mod: *ecco_card_mod

          # ---- 3. KNOWN-GOOD PROFILE (everyday form) ----
          - type: markdown
            grid_options:
              columns: 48
              rows: auto
            content: |
              {% set B2 = ';' ~ states('sensor.@@ECCO_PRIVATE_SLUG@@_ecco_fallback_profile_summary') ~ ';' %}
              {% set g = B2.split(';g=')[1].split(';')[0] if ';g=' in B2 else '-' %}
              {% set bid = B2.split(';id=')[1].split(';')[0] if ';id=' in B2 else '-' %}
              {% set at = B2.split(';at=')[1].split(';')[0] if ';at=' in B2 else '-' %}
              {% set S = ';' ~ states('sensor.@@ECCO_PRIVATE_SLUG@@_ecco_fallback_profile_slots') ~ ';' %}
              {% set C = ';' ~ states('sensor.@@ECCO_PRIVATE_SLUG@@_ecco_fallback_profile_context') ~ ';' %}
              {% set cells = state_attr('sensor.ecco_fallback_status', 'drift_cells') or [] %}
              {% set srcs = (state_attr('sensor.ecco_fallback_status', 'saved_sources') or '').split(' | ') %}
              ### Known-Good Profile: {{ states('sensor.ecco_fallback_status') | upper }}

              {{ state_attr('sensor.ecco_fallback_status', 'subline') }}

              {% if g == '-' %}**No profile saved yet.**
              {% else %}Saved **{{ 'capture time unknown' if at == '0' else (at | int(0) | timestamp_custom('%d %b %Y %H:%M')) }}** \u00b7 generation **{{ g }}** \u00b7 ID **{{ bid[:8] }}**
              {% endif %}
              {% if ';v=SAVED;' in S or S.startswith(';v=SAVED;') %}
              | Slot | Time | Power | Target SOC | Source |
              |:---|:---|---:|---:|:---|
              {% for n in range(1, 7) -%}
              {% set t = S.split(';' ~ n ~ '=')[1].split(';')[0] if (';' ~ n ~ '=') in S else '-' -%}
              {% set f = t.split('/') -%}
              {% set nx = S.split(';' ~ (1 if n == 6 else n + 1) ~ '=')[1].split(';')[0].split('/')[0] if (';' ~ (1 if n == 6 else n + 1) ~ '=') in S else '----' -%}
              {% if f | length == 4 -%}
              | {{ n }} | {{ f[0][:2] }}:{{ f[0][2:] }}-{{ nx[:2] }}:{{ nx[2:] }}{{ ' \u25c0 now ' ~ states('sensor.@@ECCO_PRIVATE_SLUG@@_ecco_timezone' ~ n ~ '_time') if ('time' ~ n) in cells or ('time' ~ (n - 1 if n > 1 else 6)) in cells else '' }} | {{ f[1] }} W{{ ' \u25c0 now ' ~ states('sensor.@@ECCO_PRIVATE_SLUG@@_ecco_timezone' ~ n ~ '_power') ~ ' W' if ('power' ~ n) in cells else '' }} | {{ f[2] }} %{{ ' \u25c0 now ' ~ states('sensor.@@ECCO_PRIVATE_SLUG@@_ecco_timezone' ~ n ~ '_soc') ~ ' %' if ('soc' ~ n) in cells else '' }} | {{ srcs[n - 1] if srcs | length >= n else '-' }}{{ ' \u25c0 now ' ~ states('sensor.@@ECCO_PRIVATE_SLUG@@_ecco_timezone' ~ n ~ '_charge') if ('source' ~ n) in cells else '' }} |
              {% endif -%}
              {% endfor %}
              Export mode **{{ state_attr('sensor.ecco_fallback_status', 'saved_export_mode') }}**{{ ' \u25c0 differs now' if 'export_mode' in cells else '' }} \u00b7
              Energy mode **{{ state_attr('sensor.ecco_fallback_status', 'saved_energy_mode') }}**{{ ' \u25c0 differs now' if 'energy_mode' in cells else '' }}

              Grid charging **{{ state_attr('sensor.ecco_fallback_status', 'saved_grid_charging') }}**{{ ' \u25c0 differs now' if 'grid_charging' in cells else '' }} \u00b7
              TOU schedule **{{ state_attr('sensor.ecco_fallback_status', 'saved_tou_schedule') }}**{{ ' \u25c0 differs now' if 'tou_schedule' in cells else '' }}

              Not restored by Fallback V1: grid charge current **{{ C.split(';230=')[1].split(';')[0] if ';230=' in C else '-' }} A** \u00b7
              reg 245 **{{ C.split(';245=')[1].split(';')[0] if ';245=' in C else '-' }}** (not evidence of export limitation) \u00b7
              reg 247 **0x{{ C.split(';247=')[1].split(';')[0] if ';247=' in C else '-' }}**
              {% endif %}
            card_mod: *ecco_card_mod

          # ---- 4. LIVE MATCH + READINESS ----
          - type: markdown
            grid_options:
              columns: 24
              rows: auto
            content: |
              {% set L = ';' ~ states('sensor.@@ECCO_PRIVATE_SLUG@@_ecco_fallback_profile_live_match') ~ ';' %}
              {% set m = L.split(';m=')[1].split(';')[0] if ';m=' in L else 'UNKNOWN' %}
              {% set elig = L.split(';elig=')[1].split(';')[0] if ';elig=' in L else 'UNK' %}
              {% set ew = L.split(';ew=')[1].split(';')[0] if ';ew=' in L else '-' %}
              {% set eh = L.split(';eh=')[1].split(';')[0] if ';eh=' in L else 'U' %}
              {% set words = {'MATCH': 'Live settings match the saved profile.', 'DRIFT': 'Live values differ from the saved profile.', 'CONTEXT': 'Slot times or context changed since the profile was saved.', 'EXPORT': 'Export mode is Allow Export; the saved profile uses Zero Export.', 'OUT_OF_DOMAIN': 'Live settings are outside what Fallback V1 supports.', 'PAUSED': 'Comparison paused while a temporary operation manages settings.', 'PAUSED_IO': 'Comparison paused while an inverter write or bus operation is in progress.', 'UNKNOWN': 'Live comparison unavailable (configuration data not fresh).', 'NO_PROFILE': 'No usable saved profile to compare with.'} %}
              ### Live match

              **{{ m }}** - {{ words.get(m, 'Unrecognised live-match state.') }}

              {% if elig == 'OK' %}Your current settings can be saved as the known-good profile.
              {% elif elig == 'NO' %}Your current settings cannot be saved in Fallback V1: {{ ew }}.
              {% elif elig == 'OVL' %}Saving is unavailable while a temporary operation manages settings.
              {% else %}Saveability is not known yet.
              {% endif %}
              {% if eh == '1' %}

              \u26a0 Export is currently ENABLED while a temporary operation needs recovery.
              {% elif eh == 'U' and 'DP:' in L and ('DP:CR' not in L and 'DP:CM' not in L and 'DP:CA' not in L and 'DP:CN' not in L) %}

              \u26a0 Export state unknown - check the inverter.
              {% endif %}
            card_mod: *ecco_card_mod

          - type: markdown
            grid_options:
              columns: 24
              rows: auto
            content: |
              {% set R = ';' ~ states('sensor.@@ECCO_PRIVATE_SLUG@@_ecco_fallback_profile_review') ~ ';' %}
              {% set st = R.split(';st=')[1].split(';')[0] if ';st=' in R else 'IDLE' %}
              {% set arm = is_state('switch.@@ECCO_PRIVATE_SLUG@@_ecco_fallback_profile_arm', 'on') %}
              {% set sup = states('sensor.ecco_supervision_status') %}
              ### Save needs

              {{ '\u2713' if st == 'CANDIDATE_READY' else '\u25ef' }} Review \u00b7
              {{ '\u2713' if arm else '\u25ef' }} Arm \u00b7
              {{ '\u2713' if sup == 'Healthy' else '\u25ef' }} Supervision stable \u00b7
              {{ '\u2713' if is_state('binary_sensor.@@ECCO_PRIVATE_SLUG@@_ntp_synced', 'on') else '\u25ef' }} NTP time

              {% if sup != 'Healthy' %}Save needs stable Home Assistant supervision (currently {{ sup }}).{% endif %}

              **Last action:** {{ states('sensor.@@ECCO_PRIVATE_SLUG@@_ecco_fallback_profile_last_action_result') }}
            card_mod: *ecco_card_mod

      # ---- REVIEW (CANDIDATE) PANEL ----
      - type: grid
        column_span: 4
        cards:
          - type: markdown
            grid_options:
              columns: 48
              rows: auto
            content: |
              {% set R = ';' ~ states('sensor.@@ECCO_PRIVATE_SLUG@@_ecco_fallback_profile_review') ~ ';' %}
              {% set st = R.split(';st=')[1].split(';')[0] if ';st=' in R else 'IDLE' %}
              {% if st in ['IDLE', 'unknown', 'unavailable', ''] %}
              ### Review - current configuration

              No review in progress. Press **Review Current Configuration** below (read-only: it changes nothing on the inverter).
              {% else %}
              {% set prior = R.split(';prior=')[1].split(';')[0] if ';prior=' in R else '-' %}
              {% set exp = (R.split(';exp=')[1].split(';')[0] if ';exp=' in R else '-') %}
              {% set warn = (R.split(';warn=')[1].split(';')[0] if ';warn=' in R else '-') %}
              {% set rid = states('sensor.@@ECCO_PRIVATE_SLUG@@_ecco_fallback_profile_review_id') %}
              {% set head = {'READING': 'READING INVERTER (READ-ONLY)', 'CANDIDATE_READY': 'CANDIDATE READY', 'CANDIDATE_NOT_SAVEABLE': 'NOT SAVEABLE', 'SAVING': 'SAVING - RE-READING INVERTER'} %}
              {% set wtext = {'W1': 'Looks like a Free Power overlay - confirm this is your normal setup.', 'W2': 'All six slot powers are equal and at most 3000 W - this resembles Dump to Grid residue; confirm.', 'W3': "TOU schedule (248) is OFF: this profile's slot settings are inactive on the inverter.", 'W4': 'Grid charging is globally disabled (232) while slots select Grid.'} %}
              {% set S = ';' ~ states('sensor.@@ECCO_PRIVATE_SLUG@@_ecco_fallback_profile_review_slots') ~ ';' %}
              {% set C = ';' ~ states('sensor.@@ECCO_PRIVATE_SLUG@@_ecco_fallback_profile_review_context') ~ ';' %}
              {% set SV = ';' ~ states('sensor.@@ECCO_PRIVATE_SLUG@@_ecco_fallback_profile_slots') ~ ';' %}
              {% set chg = state_attr('sensor.ecco_fallback_status', 'candidate_changed_cells') or [] %}
              {% set srcs = (state_attr('sensor.ecco_fallback_status', 'candidate_sources') or '').split(' | ') %}
              ### Review - current configuration: {{ head.get(st, st) }}

              Review ID **{{ rid }}**{% if exp | int(-1) >= 0 %} \u00b7 expires in **{{ '%d:%02d' | format(exp | int(0) // 60, exp | int(0) % 60) }}**{% endif %}

              Replaces: **{{ prior }}**{{ ' (generation ' ~ (states('sensor.@@ECCO_PRIVATE_SLUG@@_ecco_fallback_profile_summary').split(';')[0] | replace('g=', '')) ~ ')' if prior == 'VALID' else '' }}

              {{ state_attr('sensor.ecco_fallback_status', 'next_generation_text') or 'Will save a new generation' }}

              | Slot | Time | Power | Target SOC | Source |
              |:---|:---|---:|---:|:---|
              {% for n in range(1, 7) -%}
              {% set t = S.split(';' ~ n ~ '=')[1].split(';')[0] if (';' ~ n ~ '=') in S else '-' -%}
              {% set f = t.split('/') -%}
              {% set tv = SV.split(';' ~ n ~ '=')[1].split(';')[0].split('/') if (';' ~ n ~ '=') in SV else [] -%}
              {% set nx = S.split(';' ~ (1 if n == 6 else n + 1) ~ '=')[1].split(';')[0].split('/')[0] if (';' ~ (1 if n == 6 else n + 1) ~ '=') in S else '----' -%}
              {% if f | length == 4 -%}
              {% set lab = srcs[n - 1] if srcs | length == 6 else '-' -%}
              | {{ n }} | {{ f[0][:2] }}:{{ f[0][2:] }}-{{ nx[:2] }}:{{ nx[2:] }} | {{ f[1] }} W{{ ' \u25c0 saved ' ~ tv[1] if (tv | length == 4 and ('power' ~ n) in chg) else '' }} | {{ f[2] }} %{{ ' \u25c0 saved ' ~ tv[2] if (tv | length == 4 and ('soc' ~ n) in chg) else '' }} | {{ lab }} |
              {% endif -%}
              {% endfor %}
              Export mode (244) **{{ state_attr('sensor.ecco_fallback_status', 'candidate_export_mode') or '-' }}** \u00b7
              Energy mode (243) **{{ state_attr('sensor.ecco_fallback_status', 'candidate_energy_mode') or '-' }}**

              Grid charging (232) **{{ state_attr('sensor.ecco_fallback_status', 'candidate_grid_charging') or '-' }}** \u00b7
              TOU schedule (248) **{{ state_attr('sensor.ecco_fallback_status', 'candidate_tou_schedule') or '-' }}**

              Slot times form a valid 24 h ring: **{{ 'yes' if (C.split(';ring=')[1].split(';')[0] if ';ring=' in C else '-') == 'OK' else 'NO' }}**

              Info (never restored in V1): 230 **{{ C.split(';230=')[1].split(';')[0] if ';230=' in C else '-' }}** \u00b7 245 **{{ C.split(';245=')[1].split(';')[0] if ';245=' in C else '-' }}** \u00b7 247 **0x{{ C.split(';247=')[1].split(';')[0] if ';247=' in C else '-' }}**

              {% if warn != '-' %}{% for w in warn.split(',') %}\u26a0 {{ w }} {{ wtext.get(w, 'Review warning.') }}

              {% endfor %}{% endif %}
              {% if st == 'CANDIDATE_NOT_SAVEABLE' %}Why: {{ states('sensor.@@ECCO_PRIVATE_SLUG@@_ecco_fallback_profile_review') }} (see the Live match panel for the reasons).{% endif %}
              {% endif %}
            card_mod: *ecco_card_mod

      # ---- CONTROLS (operator-only; every write is behind its own gate) ----
      - type: grid
        column_span: 4
        cards:
          - type: heading
            heading: Controls
            heading_style: subtitle
            icon: mdi:gesture-tap-button
            grid_options:
              columns: 48
              rows: auto
          - type: entities
            title: Review and arm
            show_header_toggle: false
            grid_options:
              columns: 24
              rows: auto
            entities:
              - entity: button.@@ECCO_PRIVATE_SLUG@@_ecco_fallback_profile_review_current_configuration
                name: Review Current Configuration
              - entity: switch.@@ECCO_PRIVATE_SLUG@@_ecco_fallback_profile_arm
                name: Arm (turns off after 2 min)
            card_mod: *ecco_card_mod
          - type: button
            name: Save Known-Good Profile
            icon: mdi:content-save-check-outline
            show_state: false
            visibility:
              - condition: state
                entity: binary_sensor.ecco_fallback_save_available
                state: 'on'
            tap_action:
              action: perform-action
              perform_action: script.ecco_fallback_profile_save
              confirmation:
                text: Save the reviewed configuration as your known-good profile? The Review ID shown on screen is used. The inverter is not changed.
            grid_options:
              columns: 24
              rows: 2
          - type: button
            name: Replace Damaged Profile
            icon: mdi:file-replace-outline
            show_state: false
            visibility:
              - condition: state
                entity: binary_sensor.ecco_fallback_replace_corrupt_available
                state: 'on'
            tap_action:
              action: perform-action
              perform_action: script.ecco_fallback_profile_replace_corrupt
              confirmation:
                text: This replaces a damaged saved profile after logging its raw bytes. It does not erase NVS and does not change the inverter. Continue?
            grid_options:
              columns: 24
              rows: 2
          - type: button
            name: Invalidate Profile
            icon: mdi:file-cancel-outline
            show_state: false
            visibility:
              - condition: state
                entity: binary_sensor.ecco_fallback_invalidate_available
                state: 'on'
            tap_action:
              action: perform-action
              perform_action: script.ecco_fallback_profile_invalidate
              confirmation:
                text: Invalidate the known-good profile? It is kept for reference but will never be used until you save a new one. The inverter is not changed.
            grid_options:
              columns: 24
              rows: 2

      # ---- TECHNICAL DETAIL (behind the helper toggle) ----
      - type: grid
        column_span: 4
        cards:
          - type: entities
            show_header_toggle: false
            grid_options:
              columns: 48
              rows: auto
            entities:
              - entity: input_boolean.ecco_safety_show_technical_detail
                name: Show technical detail
            card_mod: *ecco_card_mod
          - type: markdown
            visibility:
              - condition: state
                entity: input_boolean.ecco_safety_show_technical_detail
                state: 'on'
            grid_options:
              columns: 48
              rows: auto
            content: |
              {% set L = ';' ~ states('sensor.@@ECCO_PRIVATE_SLUG@@_ecco_fallback_profile_live_match') ~ ';' %}
              {% set R = ';' ~ states('sensor.@@ECCO_PRIVATE_SLUG@@_ecco_fallback_profile_review') ~ ';' %}
              {% set obl = (L.split(';obl=')[1].split(';')[0] if ';obl=' in L else '-') %}
              {% set dom = {'FP': 'Free Power', 'DP': 'Dump to Grid', 'R4': 'Register 244 test', 'MT': 'Manual TOU', 'FS': 'Failback record', 'BUS': 'Inverter bus'} %}
              {% set kind = {'CM': 'clear marker', 'CA': 'no record stored', 'CN': 'no durable state', 'CR': 'clear (live legs only)', 'AC': 'active', 'ST': 'starting', 'RR': 'restore required', 'PC': 'pending clear', 'EN': 'ending', 'ON': 'needs your decision', 'UR': 'recovery state unreadable', 'MC': 'recovery metadata corrupt', 'ML': 'recovery metadata corrupt', 'CT': 'recovery metadata corrupt', 'DV': 'stored state disagrees with memory', 'LK': 'inverter write lock stuck', 'NP': 'not yet checked', 'BL': 'starting up', 'IF': 'in flight', 'OK': 'idle', 'BY': 'busy'} %}
              ### Technical detail

              **Status code:** `{{ states('sensor.ecco_fallback_status_code') }}` \u00b7 **Live match:** `{{ state_attr('sensor.ecco_fallback_status_code', 'live_match') }}` \u00b7
              **Profile class:** `{{ states('sensor.@@ECCO_PRIVATE_SLUG@@_ecco_fallback_profile_state') }}` \u00b7
              **Drift cells:** `{{ state_attr('sensor.ecco_fallback_status', 'drift_cells') }}` ({{ state_attr('sensor.ecco_fallback_status', 'drift_count') }})

              **Temporary operations (live obligations):**
              {% for e in (obl.split(',') if obl != '-' else []) -%}
              - {{ dom.get(e.split(':')[0], e.split(':')[0]) }}: {{ kind.get(e.split(':')[1], e.split(':')[1]) }} (`{{ e }}`)
              {% endfor %}
              **Review obligations:** `{{ R.split(';obl=')[1].split(';')[0] if ';obl=' in R else '-' }}` \u00b7 probe latch `{{ R.split(';latch=')[1].split(';')[0] if ';latch=' in R else '-' }}` \u00b7 saveability `{{ R.split(';sv=')[1].split(';')[0] if ';sv=' in R else '-' }}`

              **Raw strings**

              - Summary: `{{ states('sensor.@@ECCO_PRIVATE_SLUG@@_ecco_fallback_profile_summary') }}`
              - Review: `{{ states('sensor.@@ECCO_PRIVATE_SLUG@@_ecco_fallback_profile_review') }}`
              - Review ID: `{{ states('sensor.@@ECCO_PRIVATE_SLUG@@_ecco_fallback_profile_review_id') }}`
              - Review slots: `{{ states('sensor.@@ECCO_PRIVATE_SLUG@@_ecco_fallback_profile_review_slots') }}`
              - Review context: `{{ states('sensor.@@ECCO_PRIVATE_SLUG@@_ecco_fallback_profile_review_context') }}`
              - Saved slots: `{{ states('sensor.@@ECCO_PRIVATE_SLUG@@_ecco_fallback_profile_slots') }}`
              - Saved context: `{{ states('sensor.@@ECCO_PRIVATE_SLUG@@_ecco_fallback_profile_context') }}`
              - Live match: `{{ states('sensor.@@ECCO_PRIVATE_SLUG@@_ecco_fallback_profile_live_match') }}`
              - Last action-result: `{{ states('sensor.@@ECCO_PRIVATE_SLUG@@_ecco_fallback_profile_last_action_result') }}`

              **Generation high-water (Home Assistant detection only):** `{{ states('sensor.ecco_fallback_generation_high_water') }}`
            card_mod: *ecco_card_mod
          - type: entities
            title: Supervision diagnostics
            show_header_toggle: false
            visibility:
              - condition: state
                entity: input_boolean.ecco_safety_show_technical_detail
                state: 'on'
            grid_options:
              columns: 24
              rows: auto
            entities:
              - entity: sensor.@@ECCO_PRIVATE_SLUG@@_ecco_supervision_state
                name: Supervision state (firmware)
              - entity: sensor.@@ECCO_PRIVATE_SLUG@@_ecco_supervision_heartbeat_age
                name: Heartbeat age
              - entity: sensor.@@ECCO_PRIVATE_SLUG@@_ecco_supervision_last_gap
                name: Last gap
              - entity: sensor.@@ECCO_PRIVATE_SLUG@@_ecco_supervision_longest_gap
                name: Longest gap
              - entity: sensor.@@ECCO_PRIVATE_SLUG@@_ecco_supervision_valid_heartbeat_count
                name: Valid heartbeats
              - entity: sensor.@@ECCO_PRIVATE_SLUG@@_ecco_supervision_invalid_heartbeat_count
                name: Invalid heartbeats
              - entity: sensor.@@ECCO_PRIVATE_SLUG@@_ecco_supervision_last_invalid_heartbeat_reason
                name: Last invalid reason
              - entity: binary_sensor.@@ECCO_PRIVATE_SLUG@@_ecco_api_client_connected
                name: API client connected
            card_mod: *ecco_card_mod
          - type: button
            name: Reset detection history (Home Assistant only)
            icon: mdi:backup-restore
            show_state: false
            visibility:
              - condition: state
                entity: input_boolean.ecco_safety_show_technical_detail
                state: 'on'
            tap_action:
              action: perform-action
              perform_action: script.ecco_fallback_reset_high_water
              confirmation:
                text: Reset Home Assistant's detection history for the saved-profile generation? This resets only Home Assistant's own record of the highest generation it has seen. It does NOT change the dongle or the inverter. Operator use only, after investigating a lost or rolled-back profile warning.
            grid_options:
              columns: 24
              rows: 2
""",
        """  - title: Manual Controls
    path: ecco-manual-controls
""",
    ),
    (
        """              columns: 48
              rows: auto
""",
        """          - type: markdown
            grid_options:
              columns: 48
              rows: 3
""",
        """          # ---- FALLBACK PROFILE DRIFT BANNER (FB-B3; ADVISORY / DISPLAY ONLY) ----
          # Shown only while the saved known-good profile no longer matches the inverter. It never
          # blocks, delays or changes a Manual TOU apply; the profile does NOT update itself.
          - type: markdown
            visibility:
              - condition: state
                entity: sensor.ecco_fallback_status_code
                state:
                  - drift_values
                  - drift_context
                  - drift_export
                  - live_out_of_domain
            grid_options:
              columns: 48
              rows: auto
            content: |
              {% set c = states('sensor.ecco_fallback_status_code') %}
              {% set n = state_attr('sensor.ecco_fallback_status', 'drift_count') | int(0) %}
              {% set L = ';' ~ states('sensor.@@ECCO_PRIVATE_SLUG@@_ecco_fallback_profile_live_match') ~ ';' %}
              {% set ew = L.split(';ew=')[1].split(';')[0].split(',')[0].split('+')[0] if ';ew=' in L else '-' %}
              {% if c == 'drift_values' %}
              Your saved known-good profile no longer matches the inverter ({{ n }} {{ 'setting differs' if n == 1 else 'settings differ' }}). It will NOT update itself. If this change is your new normal, open the Safety tab \u2192 Review Current Configuration \u2192 Save.
              {% elif c == 'drift_context' %}
              Your saved known-good profile no longer matches the inverter. It will NOT update itself. Slot times or context changed: a restore of the saved profile would be refused until you save again or put the times back. To save the new setup, open the Safety tab \u2192 Review Current Configuration \u2192 Save.
              {% elif c == 'drift_export' %}
              Export mode is Allow Export; your saved known-good profile uses Zero Export. This setting cannot be saved as a fallback - change it back here in Manual Controls. The profile will NOT update itself; once the settings are saveable, open the Safety tab \u2192 Review Current Configuration \u2192 Save.
              {% else %}
              Current settings are outside what Fallback V1 can save or restore ({{ ew if ew not in ['-', ''] else 'see the Safety tab' }}). Change them here before saving a new profile. The saved profile will NOT update itself: Safety tab \u2192 Review Current Configuration \u2192 Save.
              {% endif %}

              Advisory only - this does not block or change Manual Controls.
            card_mod: *ecco_card_mod
          - type: markdown
            grid_options:
              columns: 48
              rows: auto
""",
        """            content: |
              Automatic optimisation is **OFF** - every change on this page is manual and human-triggered
""",
    ),
    (
        """              press Apply. See the ECCO README/manual-write architecture docs for the full transaction
              model this page reuses unchanged.
""",
        """""",
        """              {% set ns = namespace(notes=[]) %}
              {% for n in range(1, 7) %}
              {% set p = states('input_number.ecco_manual_slot_' ~ n ~ '_power_staged') | int(-1) %}
              {% set src = states('select.@@ECCO_PRIVATE_SLUG@@_manual_slot_' ~ n ~ '_charge_source') %}
              {% if p >= 0 and p < 500 %}{% set ns.notes = ns.notes + ['Note: staged Slot ' ~ n ~ ' (power ' ~ p ~ ' W is below 500 W) is outside what Fallback V1 can save or restore.'] %}{% endif %}
              {% if src in ['Generator', 'Grid + Generator'] %}{% set ns.notes = ns.notes + ['Note: staged Slot ' ~ n ~ ' (charge source ' ~ src ~ ') is outside what Fallback V1 can save or restore.'] %}{% endif %}
              {% endfor %}
              {% for note in ns.notes %}

              {{ note }} (Advisory only - Apply is not blocked.)
              {% endfor %}
""",
        """            card_mod: &ecco_manual_markdown_card_mod
              style: |
""",
    ),
)

MANIFEST_REL = "deployment/ha-manifest.yaml"
MANIFEST_BASE_SHA = "d15d8fd2781e43585ddb8829f5af4cfa34e3e8b0b62e67d37fd5656b398bb832"
MANIFEST_AFTER_SHA = "3cebe846fa7ff6692b28ff850d799c0a56ce314499f03a3d8ed902df2c279757"
MANIFEST_HUNKS = (
    (
        """schema_version: 2
""",
        """release: "2026-09-18-system-health-phase1"
""",
        """release: "2026-10-02-fbb3-dashboard"
""",
        """
home_assistant_packages:
""",
    ),
    (
        """    method: ssh_file_copy
    restart_required: true
""",
        """""",
        """  # Fallback Profile / supervision display layer (FB-B3; read-only, NOT live-proven until the FB-B3
  # live proof). Requires firmware with the FB-B1/FB-B2/FB-B3 entities.
  - source: home-assistant/packages/ecco_fallback_status.yaml
    destination: /config/packages/ecco_fallback_status.yaml
    method: ssh_file_copy
    restart_required: true
  # Operator-only wrappers for esphome.<node>_fallback_profile_execute (FB-B3). Never called by
  # automations; only the dashboard's human-pressed buttons reach them.
  - source: home-assistant/packages/ecco_fallback_profile_actions.yaml
    destination: /config/packages/ecco_fallback_profile_actions.yaml
    method: ssh_file_copy
    restart_required: true
""",
        """
dashboard:
""",
    ),
    (
        """    destination: influxdb_task_ecco_battery_outlook_daily_score
    method: manual_task_editor
""",
        """  - source: influxdb/ecco_influxdb_options_v1_2.yaml
""",
        """  - source: influxdb/ecco_influxdb_options_v1_3.yaml
""",
        """    destination: home_assistant_influx_export_configuration
    method: reference_only
""",
    ),
    (
        """  - ecco_system_health.yaml is Phase 1 only: read-only, partial, and not a complete manual-control readiness gate.
  - Never include secrets.yaml, API tokens, Wi-Fi credentials, Home Assistant auth tokens or SSH private keys in a deployment bundle.
""",
        """""",
        """  - Fallback packages require firmware with FB-B1/FB-B2/FB-B3 entities; deploy firmware first, then packages, then the dashboard.
""",
        """""",
    ),
)

VERSION_REL = "VERSION.yaml"
VERSION_BASE_SHA = "4da82b87f49b61f46c168892d7b5cb91c4a83819e71e64d6419197b03c83ce6a"
VERSION_AFTER_SHA = "3d87783b2b62f6a116844cf3d4f9163a684e0b477cb2d878da9fcefbfc782065"
VERSION_HUNKS = (
    (
        """  main_commit: a39c8d3c46d30449d581a1b0c05df48d58962233
  dashboard:
""",
        """    version: "7.16.0"
    path: home-assistant/dashboards/ecco_pro.yaml
    # v7.16.0 Energy Actions was live-tested in Home Assistant on 2026-09-22:
    # manual NOW and automatic Scheduled LATER 500 W / 1-minute transactions
    # both completed ACTIVE -> verified restore; final counters 3/3/3, failures 0.
    tested_in_home_assistant: true
""",
        """    version: "7.17.0"
    path: home-assistant/dashboards/ecco_pro.yaml
    # v7.17.0 (FB-B3: Safety view, Known-Good Profile tile, supervision/fallback chips and health rows,
    # Manual Controls advisory banner) was live-tested in Home Assistant on 2026-10-03 (LP-B3, PR #61):
    # SAVE / INVALIDATE / SAVE through the HA wrappers, Live Match MATCH / DRIFT / CONTEXT / NO_PROFILE,
    # confirmation dialogs, Safety view, chips and health rows, two HA restarts, InfluxDB v1.3 applied live.
    # Known limitation carried forward: Live Match (B10) is settled only in short quiet windows because
    # routine RTC corrections re-open the deliberate trust fence (follow-up with the liveness / RTC work).
    # v7.16.0 Energy Actions was live-tested in Home Assistant on 2026-09-22:
    # manual NOW and automatic Scheduled LATER 500 W / 1-minute transactions
    # both completed ACTIVE -> verified restore; final counters 3/3/3, failures 0.
    tested_in_home_assistant: true
""",
        """  firmware:
    version: "stage3.4"
""",
    ),
    (
        """    battery_outlook_readback: home-assistant/packages/ecco_battery_outlook_influx.yaml
  influxdb:
""",
        """    export_config: influxdb/ecco_influxdb_options_v1_2.yaml
""",
        """    export_config: influxdb/ecco_influxdb_options_v1_3.yaml
""",
        """    battery_outlook_task: influxdb/tasks/ecco_battery_outlook_5m.flux
    battery_outlook_model: load_only_v1_2
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
        raise AssertionError(f"FB-B3 HA scope: {what} must be {state} exactly once, found {n}x: {find[:70]!r}")
    i = text.index(find)
    return text[:i] + put + text[i + len(find):]


def _revert(text: str, hunks, what: str) -> str:
    out = text
    for k, (left, old, new, right) in reversed(list(enumerate(hunks))):
        out = _swap(out, left + new + right, left + old + right, f"{what} hunk {k}", "present")
    for k, (left, old, new, right) in enumerate(hunks):
        n = out.count(left + old + right)
        if n != 1:
            raise AssertionError(f"FB-B3 HA scope: the {what} hunk {k} anchor must be unique once reverted, found {n}x")
    return out


def _apply(text: str, hunks, what: str) -> str:
    out = text
    for k, (left, old, new, right) in enumerate(hunks):
        if (left + new + right) in out:
            raise AssertionError(f"FB-B3 HA scope: {what} hunk {k} already present")
        out = _swap(out, left + old + right, left + new + right, f"{what} hunk {k} anchor", "found")
    return out


def pre_fbb3_dashboard(text: str) -> str:
    """The dashboard with exactly the FB-B3 edits undone (main @ BASE_COMMIT, DASHBOARD_BASE_SHA)."""
    return _revert(text, DASHBOARD_HUNKS, "dashboard")


def pre_fbb3_manifest(text: str) -> str:
    return _revert(text, MANIFEST_HUNKS, "manifest")


def pre_fbb3_version(text: str) -> str:
    return _revert(text, VERSION_HUNKS, "VERSION")


def add_fbb3_dashboard(text: str) -> str:
    return _apply(text, DASHBOARD_HUNKS, "dashboard")


def add_fbb3_manifest(text: str) -> str:
    return _apply(text, MANIFEST_HUNKS, "manifest")


def add_fbb3_version(text: str) -> str:
    return _apply(text, VERSION_HUNKS, "VERSION")
