"""ovw2 (Overview V2.1: the polish and accuracy pass over the V2 dashboard, dashboard 7.21.1) change scope: exactly what ovw2 changes in the
files the pub0 export froze, and its exact inverse. Re-chained: made first on f0ddeb4 (as of ovw1), re-based onto public main 451f0c24 (after acs0); FE1's time_to_reserve lines are part of the text it reverts to.

Same technique as the earlier post-export scope modules: every verbatim edit is held HERE as the single source of truth, as an exact
(before, after) pair generated from the real diff and round-trip-checked, and each reverter raises unless each of its edits is present
exactly once. The post-export chain entry `ovw2` (registry/tests/_scope_chain.py POST_EXPORT_ENTRIES, appended last after fps1; registry/tests/_pex.py)
carries one frozen reverter per edited frozen file.

WHAT ovw2 IS. A dashboard-only correction and polish of the V2 Overview that ovw1 introduced (display only; no control, service call,
firmware, Home Assistant package, automation, registry, Intelligence or ecco_core change):
  - home-assistant/dashboards/ecco_pro.yaml (pub0 target, FROZEN):
      * ECCO Today (Overview and Intelligence views) and Smart Charge Strategy (Intelligence, Tariffs, Control, Recommended views):
        the SOC at the target time credits only the solar that can arrive BEFORE the target (the forecast is for the rest of the
        CURRENT calendar day), says which day the target is, and shows "Battery data unavailable" / "Projection unavailable" instead
        of NaN or an unsupported number; the reserve wording separates the ECCO setting from the modelled need;
      * the Overview: Battery estimate becomes Battery outlook (the learned load-only outlook and its accuracy), new Today so far and
        Coming up cards from existing sensors, scheduled-session counters, and ECCO Today without the tariff figures the Tariff now
        card already shows;
      * the three Power Flow charts: the dead "SOC Model" series (it read an undefined variable) is removed and a chart data-status
        strip tells a new day from a sensor that is not reporting;
      * the 7-day outlook score reads the entity ids that exist; the static "Suggested 15%" / "15% starting point" texts show the
        live ECCO reserve setting;
      * the v7.21.1 header note;
  - VERSION.yaml (enrolled, FROZEN): dashboard 7.21.1, staged (tested_in_home_assistant stays false); the 7.21.0 (FE1) and 7.20.0 records are kept.
ZERO firmware, Home Assistant package, registry, Intelligence or ecco_core change; ZERO Modbus operation; no new service call.

NOT frozen (ordinary edits, nothing to declare): CHANGELOG.md and docs/dev/post-export-edit-layer.md. Added: this module, test_ovw2_transition.py and home-assistant/tests/test_ecco_overview_v21.py.

This module imports no other scope module, not _scope_chain (the chain imports it) and not _pex. No I/O.
"""

from __future__ import annotations

import hashlib

# Public main commit the change is based on (FE-1 and FPS1 merged; the accepted V2.1 is re-chained on it).
BASE_COMMIT = "451f0c246a3e9016ef95bb03d41da64d995fcafd"

ADDED_FILES = frozenset({
    "registry/tests/_ovw2_scope.py",
    "registry/tests/test_ovw2_transition.py",
    "home-assistant/tests/test_ecco_overview_v21.py",
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
        raise AssertionError(f"ovw2 scope: {what} must be {state} exactly once, found {n}x: {find[:70]!r}")
    i = text.index(find)
    return text[:i] + put + text[i + len(find):]


def _revert(text: str, edits: tuple, what: str) -> str:
    out = text
    for k, (before, after) in reversed(list(enumerate(edits))):
        out = _swap(out, after, before, f"{what} edit {k}", "present")
    for k, (before, _after) in enumerate(edits):
        n = out.count(before)
        if n != 1:
            raise AssertionError(f"ovw2 scope: {what} anchor {k} must be unique once the edits are removed, found {n}x")
    return out


def _apply(text: str, edits: tuple, what: str) -> str:
    out = text
    for k, (before, after) in enumerate(edits):
        if after in out:
            raise AssertionError(f"ovw2 scope: {what} edit {k} is already present")
        out = _swap(out, before, after, f"{what} anchor {k}", "found")
    return out

# ---- (PEX frozen edit) home-assistant/dashboards/ecco_pro.yaml ---------------------------------------------------------
DASHBOARD_REL = "home-assistant/dashboards/ecco_pro.yaml"
DASHBOARD_0_OLD = _blk(r"""
# summary. The estimate comes from the read-only package ecco_battery_runtime.yaml. Display only: no control, no
# firmware change.
# Built for Home Assistant Sections view + Flexible Horseshoe Card + Sunsynk Power Flow Card (secondary/detail views) + ApexCharts + card-mod
# Entity IDs matched from the ECCO entity dump captured 2026-09-12.
""")
DASHBOARD_0_NEW = _blk(r"""
# summary. The estimate comes from the read-only package ecco_battery_runtime.yaml. Display only: no control, no
# firmware change.
# v7.21.1 (OVW2, STAGED / NOT LIVE-PROVEN) is the Overview V2.1 polish and accuracy pass over 7.21.0 (it keeps FE1's time to reserve). ECCO Today and Smart Charge
# Strategy count only the solar that can arrive BEFORE their target time (between 00:00 and the 00:30 target the SOC at the
# target was overstated by about 25 points) and show "Battery data unavailable" or "Projection unavailable" instead of a number
# they cannot support. The dead SOC Model chart series (it used an undefined variable) is removed, a chart data-status strip
# tells a new day from a sensor that is not reporting, Battery outlook / Today so far / Coming up cards use existing data to
# fill the empty space, reserve wording separates the ECCO setting from the modelled need, and the 7-day outlook score reads
# the entity ids that exist. Display only: no control, firmware, package or automation change.
# Built for Home Assistant Sections view + Flexible Horseshoe Card + Sunsynk Power Flow Card (secondary/detail views) + ApexCharts + card-mod
# Entity IDs matched from the ECCO entity dump captured 2026-09-12.
""")
DASHBOARD_1_OLD = _blk(r"""
                  return `<div>
                    <div style="padding:9px 11px;border-radius:11px;background:${bg};border:1px solid ${border};">
                      <div style="font-size:20px;font-weight:900;letter-spacing:.3px;color:${colour};">${flow}</div>
                      <div style="font-size:12px;color:rgba(255,255,255,.68);margin-top:2px;">${detail}</div>
                    </div>
                    <div style="display:flex;flex-wrap:wrap;gap:6px;margin-top:8px;">
""")
DASHBOARD_1_NEW = _blk(r"""
                  return `<div>
                    <div style="padding:9px 11px;border-radius:11px;background:${bg};border:1px solid ${border};">
                      <div style="font-size:20px;font-weight:900;letter-spacing:.3px;line-height:1.2;white-space:normal;color:${colour};">${flow}</div>
                      <div style="font-size:12px;color:rgba(255,255,255,.68);margin-top:2px;white-space:normal;">${detail}</div>
                    </div>
                    <div style="display:flex;flex-wrap:wrap;gap:6px;margin-top:8px;">
""")
DASHBOARD_2_OLD = _blk(r"""

          # ---- CURRENT TOU / OPERATING PLAN (slim) ----
          - type: custom:button-card
            section_mode: true
            name: Current Plan
            icon: mdi:calendar-clock
            show_name: true
            show_icon: true
            show_state: false
            tap_action:
              action: none
            custom_fields:
              mode: >
                [[[
                  const em = states['sensor.ecco_clock_dongle_ecco_energy_management_model']?.state ?? 'Unknown';
                  const tou = states['binary_sensor.ecco_clock_dongle_ecco_time_of_use_enabled']?.state === 'on';
                  return `<span style="display:inline-block;padding:5px 10px;border-radius:999px;
                    background:rgba(143,124,255,0.12);border:1px solid rgba(143,124,255,0.28);
                    color:#b8adff;font-size:12px;font-weight:700;">
                    ${em}${tou ? ' • TOU active' : ' • TOU off'}
                  </span>`;
""")
DASHBOARD_2_NEW = _blk(r"""

          # ---- CURRENT TOU / OPERATING PLAN (slim) ----
          - type: custom:button-card
            section_mode: true
            name: Current Plan
            icon: mdi:calendar-clock
            show_name: true
            show_icon: true
            show_state: false
            tap_action:
              action: none
            custom_fields:
              mode: >
                [[[
                  const em = states['sensor.ecco_clock_dongle_ecco_energy_management_model']?.state ?? 'Unknown';
                  const tou = states['binary_sensor.ecco_clock_dongle_ecco_time_of_use_enabled']?.state === 'on';
                  return `<span style="display:inline-block;padding:4px 8px;border-radius:999px;
                    background:rgba(143,124,255,0.12);border:1px solid rgba(143,124,255,0.28);
                    color:#b8adff;font-size:11px;font-weight:700;">
                    ${em}${tou ? ' • TOU active' : ' • TOU off'}
                  </span>`;
""")
DASHBOARD_3_OLD = _blk(r"""
                next:
                  - justify-self: stretch
                access:
                  - justify-self: end
""")
DASHBOARD_3_NEW = _blk(r"""
                next:
                  - justify-self: stretch
                  - white-space: normal
                access:
                  - justify-self: end
""")
DASHBOARD_4_OLD = _blk(r"""
                      ${tile('EXPORT', p(exp), '#b36cff')}
                    </div>
                    <div style="font-size:12px;color:rgba(255,255,255,.62);margin-top:6px;">Today ${p(cheap)}–${p(peak)} p/kWh • spread ${p(spread)} p • next rate ${p(next)} p</div>
                  </div>`;
                ]]]
""")
DASHBOARD_4_NEW = _blk(r"""
                      ${tile('EXPORT', p(exp), '#b36cff')}
                    </div>
                    <div style="font-size:12px;color:rgba(255,255,255,.62);margin-top:6px;white-space:normal;">Today ${p(cheap)}–${p(peak)} p/kWh • spread ${p(spread)} p • next rate ${p(next)} p</div>
                  </div>`;
                ]]]
""")
DASHBOARD_5_OLD = _blk(r"""
                  - align-self: center
                body:
                  - justify-self: stretch
                  - width: 100%
            grid_options:
              columns: full
""")
DASHBOARD_5_NEW = _blk(r"""
                  - align-self: center
                body:
                  - justify-self: stretch
                  - width: 100%
            grid_options:
              columns: full
              rows: auto

          # ---- COMING UP (V2.1: the next 24 hours from existing data only - sun, grid-charge window, tariff changes, armed sessions; display only) ----
          # The Current Plan card above shows the slot that is active now. Nothing here can act; no tap action, no service.
          - type: custom:button-card
            section_mode: true
            name: Coming up
            show_icon: false
            show_state: false
            tap_action:
              action: none
            custom_fields:
              body: >
                [[[
                  const now = new Date();
                  const horizon = now.getTime() + 24 * 3600000;
                  const evs = [];
                  const addEv = (t, label, tone) => {
                    const d = t instanceof Date ? t : new Date(t);
                    const ms = d.getTime();
                    if (Number.isFinite(ms) && ms > now.getTime() && ms <= horizon) evs.push({ t: d, label, tone });
                  };
                  const sun = states['sun.sun'];
                  if (sun?.attributes?.next_rising) addEv(sun.attributes.next_rising, 'Sunrise', '#ffbd3d');
                  if (sun?.attributes?.next_setting) addEv(sun.attributes.next_setting, 'Sunset', '#ff9a5c');
                  const slotRead = (i, kind) => states[`sensor.ecco_clock_dongle_ecco_timezone${i}_${kind}`]?.state;
                  const toMin = t => {
                    const m = String(t ?? '').match(/^(\d{1,2}):(\d{2})$/);
                    return m ? Number(m[1]) * 60 + Number(m[2]) : null;
                  };
                  const nextAt = mins => {
                    const d = new Date(now);
                    d.setHours(Math.floor(mins / 60), mins % 60, 0, 0);
                    if (d <= now) d.setDate(d.getDate() + 1);
                    return d;
                  };
                  for (let i = 1; i <= 6; i++) {
                    const start = toMin(slotRead(i, 'time')), end = toMin(slotRead(i === 6 ? 1 : i + 1, 'time'));
                    const charge = slotRead(i, 'charge'), soc = Number(slotRead(i, 'soc'));
                    if (start === null || end === null || !charge || ['None', 'none', 'unknown', 'unavailable'].includes(charge)) continue;
                    addEv(nextAt(start), `${charge} charge starts${Number.isFinite(soc) ? ` · ${soc.toFixed(0)} % target` : ''}`, '#b8adff');
                    addEv(nextAt(end), `${charge} charge ends`, '#b8adff');
                  }
                  const events = Object.values(states).filter(s => s.entity_id.startsWith('event.'));
                  const isExport = s => s.entity_id.includes('export') || String(s?.attributes?.friendly_name ?? '').toLowerCase().includes('export');
                  const rates = [];
                  ['current_day_rates', 'next_day_rates'].forEach(needle => {
                    const ev = events.find(s => s.entity_id.includes('octopus_energy_electricity') && s.entity_id.includes(needle) && !isExport(s));
                    (Array.isArray(ev?.attributes?.rates) ? ev.attributes.rates : []).forEach(r => {
                      const p = Number(r.value_inc_vat) * 100, s0 = new Date(r.start), e0 = new Date(r.end);
                      if (Number.isFinite(p) && !isNaN(s0) && !isNaN(e0)) rates.push({ s: s0, e: e0, p });
                    });
                  });
                  rates.sort((a, b) => a.s - b.s);
                  if (rates.length) {
                    const lo = Math.min(...rates.map(r => r.p)), hi = Math.max(...rates.map(r => r.p));
                    let prev = null;
                    rates.forEach(r => {
                      if (prev && Math.abs(r.p - prev.p) > 0.35 && Math.abs(r.s - prev.e) < 60000) {
                        const peak = hi - lo > 1 && Math.abs(r.p - hi) <= 0.35;
                        const cheap = hi - lo > 1 && Math.abs(r.p - lo) <= 0.35;
                        addEv(r.s, `${peak ? 'Peak rate' : cheap ? 'Cheap rate' : 'Standard rate'} · ${r.p.toFixed(1)} p/kWh`, peak ? '#ff5f6d' : cheap ? '#55e58e' : '#66b3ff');
                      }
                      prev = r;
                    });
                  }
                  [['Free Power', 'input_boolean.ecco_free_power_schedule_armed', 'input_datetime.ecco_free_power_schedule_start'],
                   ['Dump to Grid', 'input_boolean.ecco_dump_to_grid_schedule_armed', 'input_datetime.ecco_dump_to_grid_schedule_start']].forEach(([label, armed, start]) => {
                    const when = String(states[start]?.state ?? '');
                    if (states[armed]?.state === 'on' && when.length === 19) addEv(new Date(when.replace(' ', 'T')), `${label} session · armed`, '#c07cff');
                  });
                  evs.sort((a, b) => a.t - b.t);
                  if (!evs.length) return `<div style="font-size:12px;color:rgba(255,255,255,.55);">No sun, tariff or session events found for the next 24 hours.</div>`;
                  const hhmm = d => `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
                  const left = d => {
                    const m = Math.round((d - now) / 60000);
                    return m < 60 ? `${m} min` : `${Math.floor(m / 60)} h${m % 60 ? ` ${m % 60} min` : ''}`;
                  };
                  const dayTag = d => d.toDateString() === now.toDateString() ? '' : ' tomorrow';
                  return `<div style="display:grid;gap:2px;">${evs.slice(0, 8).map(e => `<div style="display:grid;grid-template-columns:8px minmax(0,1fr) auto;gap:8px;align-items:baseline;padding:4px 0;border-bottom:1px solid rgba(255,255,255,.05);">
                    <span style="width:7px;height:7px;border-radius:50%;background:${e.tone};align-self:center;"></span>
                    <span style="font-size:12px;color:rgba(255,255,255,.80);text-align:left;"><b style="font-size:13px;color:#fff;">${hhmm(e.t)}</b><span style="font-size:10px;color:rgba(255,255,255,.45);">${dayTag(e.t)}</span> &nbsp;${e.label}</span>
                    <span style="font-size:11px;color:rgba(255,255,255,.46);white-space:nowrap;">in ${left(e.t)}</span>
                  </div>`).join('')}</div>`;
                ]]]
            styles:
              card:
                - border-radius: 16px
                - padding: 12px 14px
                - background: linear-gradient(145deg, rgba(20,28,45,0.98), rgba(10,15,27,0.98))
                - border: 1px solid rgba(255,255,255,0.08)
                - box-shadow: 0 10px 30px rgba(0,0,0,0.22)
              grid:
                - grid-template-areas: '"n" "body"'
                - grid-template-columns: 1fr
                - grid-template-rows: min-content 1fr
                - row-gap: 6px
              name:
                - justify-self: start
                - align-self: center
                - font-size: 11px
                - font-weight: 800
                - text-transform: uppercase
                - letter-spacing: 0.05em
                - color: rgba(255,255,255,0.5)
              custom_fields:
                body:
                  - justify-self: stretch
                  - width: 100%
                  - white-space: normal
            # Home Assistant screen condition: this copy is for four columns (1440 px of content + the 256 px sidebar). Narrower pages
            # show the identical copy under Electrical detail instead, so the right-hand column does not become taller than the section beside it.
            visibility:
              - condition: screen
                media_query: '(min-width: 1696px)'
            grid_options:
              columns: full
""")
DASHBOARD_6_OLD = _blk(r"""
                    label = 'Grid supporting the house'; colour = '#7ab8ff';
                  } else if (pv > 150 && batt > 100) {
                    label = 'Solar + battery supplying house'; colour = '#55e58e';
                  } else if (pv < 50 && batt > 100) {
                    label = 'Battery supplying house'; colour = '#39d27a';
                  }

                  return `<span style="
                    display:inline-flex;align-items:center;gap:8px;padding:6px 11px;
                    border-radius:999px;background:${colour}1f;border:1px solid ${colour}55;
                    color:${colour};font-weight:700;font-size:13px;">
                    <span style="width:8px;height:8px;border-radius:50%;background:${colour};box-shadow:0 0 8px ${colour};"></span>
                    ${label}
                  </span>`;
                ]]]
              recommendation: >
                [[[
                  const n = (id) => Number(states[id]?.state ?? 0);
                  const clamp = (v,a,b) => Math.max(a,Math.min(b,v));
                  const pv = n('sensor.ecco_clock_dongle_ecco_pv_power');
                  const load = n('sensor.ecco_clock_dongle_ecco_load_power');
                  const soc = n('sensor.ecco_clock_dongle_ecco_battery_soc');
                  const loadToday = n('sensor.ecco_clock_dongle_ecco_day_load_energy');
                  const capAh = n('sensor.ecco_clock_dongle_ecco_battery_capacity_ah') || 620;
                  const capKwh = capAh * 51.2 / 1000;

                  const sensors = Object.values(states).filter(s => s.entity_id.startsWith('sensor.'));
                  const events = Object.values(states).filter(s => s.entity_id.startsWith('event.'));
                  const friendly = (s) => String(s?.attributes?.friendly_name ?? s?.entity_id ?? '').toLowerCase();
                  const find = (need, exclude=[]) => sensors.find(s => {
                    const x = friendly(s);
                    return need.every(v => x.includes(v)) && !exclude.some(v => x.includes(v));
                  });
                  const num = (s) => {
                    const v = Number(s?.state);
                    return Number.isFinite(v) ? v : null;
                  };
                  const isExport = (s) => s.entity_id.includes('export') || friendly(s).includes('export');

                  const forecastToday = num(states['sensor.ecco_solar_forecast_today']);
                  const remaining = num(states['sensor.ecco_solar_forecast_remaining']);
                  const forecastNow = num(states['sensor.ecco_solar_forecast_power_now']);
                  const actualToday = n('sensor.ecco_clock_dongle_ecco_day_pv_energy');

                  let liveRatio = null;
                  if (forecastNow !== null && forecastNow >= 250) {
                    liveRatio = clamp(pv / forecastNow, 0.15, 1.50);
                  }

                  let factor = liveRatio !== null
                    ? clamp(0.65 + 0.35 * liveRatio, 0.70, 1.10)
                    : 1.0;

                  let dailyRatio = null;
                  if (forecastToday !== null && remaining !== null) {
                    const expectedSoFar = Math.max(forecastToday - remaining, 0);
                    if (expectedSoFar >= 2.0 && actualToday >= 0.5) {
                      dailyRatio = clamp(actualToday / expectedSoFar, 0.35, 1.35);
                      factor = clamp(factor * 0.60 + dailyRatio * 0.40, 0.65, 1.10);
                    }
                  }

                  // Confidence now reflects both forecast signal strength and how closely
                  // real production is tracking it. 50% of forecast is deliberately LOW.
                  let accuracy = null;
                  if (liveRatio !== null) {
                    accuracy = clamp(1 - Math.abs(1 - liveRatio), 0, 1);
                  }
                  if (dailyRatio !== null) {
                    const dailyAccuracy = clamp(1 - Math.abs(1 - dailyRatio), 0, 1);
                    accuracy = accuracy === null ? dailyAccuracy : (accuracy * 0.65 + dailyAccuracy * 0.35);
                  }

                  let confidence = 'Low';
                  if (forecastNow !== null && forecastNow >= 700 && accuracy !== null && accuracy >= 0.80) {
                    confidence = 'High';
                  } else if (forecastNow !== null && forecastNow >= 250 && accuracy !== null && accuracy >= 0.62) {
                    confidence = 'Medium';
                  }

                  const correctedSolar = Number.isFinite(remaining) ? remaining * factor * 0.95 : null;
                  const conservativeSolar = Number.isFinite(remaining)
                    ? remaining * Math.max(0.60, factor - 0.15) * 0.95
                    : null;

                  const now = new Date();
                  const elapsed = Math.max(now.getHours() + now.getMinutes()/60, 1);
                  const avgSoFar = loadToday / elapsed;
                  const liveKw = load / 1000;
                  const blendedKw = clamp(avgSoFar * 0.65 + liveKw * 0.35, 0.15, 5);

                  const targetTimeRaw = states['sensor.ecco_config_charge_start_time']?.state;
                  const targetMatch = String(targetTimeRaw ?? '').match(/^(\d{1,2}):(\d{2})$/);
                  const targetHour = targetMatch ? Number(targetMatch[1]) : 0;
                  const targetMinute = targetMatch ? Number(targetMatch[2]) : 30;
                  const targetTime = `${String(targetHour).padStart(2,'0')}:${String(targetMinute).padStart(2,'0')}`;
                  const nextCheapStart = new Date(now);
                  nextCheapStart.setHours(targetHour,targetMinute,0,0);
                  if (nextCheapStart <= now) nextCheapStart.setDate(nextCheapStart.getDate()+1);
                  const hoursToCheap = Math.max((nextCheapStart-now)/3600000, 0);
                  const loadToCheap = blendedKw * hoursToCheap;

                  const likelySoc = correctedSolar !== null
                    ? clamp(soc + ((correctedSolar-loadToCheap)/capKwh)*100, 0, 100)
                    : null;
                  const conservativeSoc = conservativeSolar !== null
                    ? clamp(soc + ((conservativeSolar-loadToCheap)/capKwh)*100, 0, 100)
                    : null;

                  const currentRateSensors = sensors.filter(s =>
                    s.entity_id.includes('octopus_energy_electricity') &&
                    s.entity_id.includes('current_rate')
                  );
                  const imp = currentRateSensors.find(s => !isExport(s));
                  const exp = currentRateSensors.find(s => isExport(s));
                  const importP = num(imp) !== null ? num(imp)*100 : null;
                  const exportP = num(exp) !== null ? num(exp)*100 : null;

                  // Use ALL of today's rates for cheap/peak reference, not just rates still ahead.
                  const todayEvents = events.filter(s =>
                    s.entity_id.includes('octopus_energy_electricity') &&
                    s.entity_id.includes('current_day_rates') &&
                    !isExport(s)
                  );
                  let dayRates = [];
                  todayEvents.forEach(e => {
                    if (Array.isArray(e.attributes?.rates)) dayRates.push(...e.attributes.rates);
                  });
                  dayRates = dayRates.map(r => Number(r.value_inc_vat)*100).filter(Number.isFinite);

                  const dayCheapP = dayRates.length
                    ? Math.min(...dayRates)
                    : (imp?.attributes?.current_day_min_rate != null ? Number(imp.attributes.current_day_min_rate)*100 : null);
                  const dayPeakP = dayRates.length
                    ? Math.max(...dayRates)
                    : (imp?.attributes?.current_day_max_rate != null ? Number(imp.attributes.current_day_max_rate)*100 : importP);

                  const spread = importP !== null && exportP !== null ? importP-exportP : null;

                  let headline = 'Live monitoring';
                  let detail = `SOC ${soc.toFixed(0)}% • adaptive solar factor ${(factor*100).toFixed(0)}% • ${confidence.toLowerCase()} confidence`;
                  let colour = '#7ab8ff';

                  if (likelySoc !== null && conservativeSoc !== null) {
                    if (conservativeSoc >= 25) {
                      headline = `No additional grid charge indicated • ${confidence.toLowerCase()} confidence`;
                      detail = `Likely SOC at ${targetTime} is ${likelySoc.toFixed(0)}% and conservative SOC is ${conservativeSoc.toFixed(0)}%.`;
                      colour = '#55e58e';
                    } else if (likelySoc >= 20) {
                      headline = `Keep watch on reserve • ${confidence.toLowerCase()} confidence`;
                      detail = `Likely SOC at ${targetTime} is ${likelySoc.toFixed(0)}%, but conservative modelling falls to ${conservativeSoc.toFixed(0)}%.`;
                      colour = '#ffbd3d';
                    } else {
                      headline = `Cheap-rate support may be worthwhile • ${confidence.toLowerCase()} confidence`;
                      detail = `Likely SOC at ${targetTime} is only ${likelySoc.toFixed(0)}% with ${conservativeSoc.toFixed(0)}% on the conservative model.`;
                      colour = '#ff6376';
                    }
                  }

                  if (liveRatio !== null) {
                    detail += ` Live PV is ${Math.round(liveRatio*100)}% of Forecast.Solar right now.`;
                  }

                  if (dayCheapP !== null && dayPeakP !== null) {
                    const deliveredCheap = dayCheapP / 0.90;
                    const avoided = dayPeakP - deliveredCheap;
                    detail += ` Today's tariff spans ${dayCheapP.toFixed(1)}–${dayPeakP.toFixed(1)}p/kWh; cheap-rate energy is about ${deliveredCheap.toFixed(1)}p/kWh delivered after a 90% round-trip assumption.`;
                    if (avoided > 0) {
                      detail += ` That is worth about ${avoided.toFixed(1)}p/kWh versus buying at today's peak rate.`;
                    }
                  }
                  if (spread !== null) {
                    detail += ` Current import/export spread is ${spread.toFixed(1)}p/kWh.`;
                  }

""")
DASHBOARD_6_NEW = _blk(r"""
                    label = 'Grid supporting the house'; colour = '#7ab8ff';
                  } else if (pv > 150 && batt > 100) {
                    label = 'Solar + battery supplying house'; colour = '#55e58e';
                  } else if (pv < 50 && batt > 100) {
                    label = 'Battery supplying house'; colour = '#39d27a';
                  }

                  return `<span style="
                    display:inline-flex;align-items:center;gap:8px;padding:6px 11px;
                    border-radius:999px;background:${colour}1f;border:1px solid ${colour}55;
                    color:${colour};font-weight:700;font-size:13px;">
                    <span style="width:8px;height:8px;border-radius:50%;background:${colour};box-shadow:0 0 8px ${colour};"></span>
                    ${label}
                  </span>`;
                ]]]
              recommendation: >
                [[[
                  const n = (id) => Number(states[id]?.state ?? 0);
                  const clamp = (v,a,b) => Math.max(a,Math.min(b,v));
                  const pv = n('sensor.ecco_clock_dongle_ecco_pv_power');
                  const load = n('sensor.ecco_clock_dongle_ecco_load_power');
                  const soc = n('sensor.ecco_clock_dongle_ecco_battery_soc');
                  const loadToday = n('sensor.ecco_clock_dongle_ecco_day_load_energy');
                  const capAh = n('sensor.ecco_clock_dongle_ecco_battery_capacity_ah') || 620;
                  const capKwh = capAh * 51.2 / 1000;

                  const sensors = Object.values(states).filter(s => s.entity_id.startsWith('sensor.'));
                  const events = Object.values(states).filter(s => s.entity_id.startsWith('event.'));
                  const friendly = (s) => String(s?.attributes?.friendly_name ?? s?.entity_id ?? '').toLowerCase();
                  const find = (need, exclude=[]) => sensors.find(s => {
                    const x = friendly(s);
                    return need.every(v => x.includes(v)) && !exclude.some(v => x.includes(v));
                  });
                  const num = (s) => {
                    const v = Number(s?.state);
                    return Number.isFinite(v) ? v : null;
                  };
                  const isExport = (s) => s.entity_id.includes('export') || friendly(s).includes('export');

                  const forecastToday = num(states['sensor.ecco_solar_forecast_today']);
                  const remaining = num(states['sensor.ecco_solar_forecast_remaining']);
                  const forecastNow = num(states['sensor.ecco_solar_forecast_power_now']);
                  const actualToday = n('sensor.ecco_clock_dongle_ecco_day_pv_energy');

                  let liveRatio = null;
                  if (forecastNow !== null && forecastNow >= 250) {
                    liveRatio = clamp(pv / forecastNow, 0.15, 1.50);
                  }

                  let factor = liveRatio !== null
                    ? clamp(0.65 + 0.35 * liveRatio, 0.70, 1.10)
                    : 1.0;

                  let dailyRatio = null;
                  if (forecastToday !== null && remaining !== null) {
                    const expectedSoFar = Math.max(forecastToday - remaining, 0);
                    if (expectedSoFar >= 2.0 && actualToday >= 0.5) {
                      dailyRatio = clamp(actualToday / expectedSoFar, 0.35, 1.35);
                      factor = clamp(factor * 0.60 + dailyRatio * 0.40, 0.65, 1.10);
                    }
                  }

                  // Confidence now reflects both forecast signal strength and how closely
                  // real production is tracking it. 50% of forecast is deliberately LOW.
                  let accuracy = null;
                  if (liveRatio !== null) {
                    accuracy = clamp(1 - Math.abs(1 - liveRatio), 0, 1);
                  }
                  if (dailyRatio !== null) {
                    const dailyAccuracy = clamp(1 - Math.abs(1 - dailyRatio), 0, 1);
                    accuracy = accuracy === null ? dailyAccuracy : (accuracy * 0.65 + dailyAccuracy * 0.35);
                  }

                  let confidence = 'Low';
                  if (forecastNow !== null && forecastNow >= 700 && accuracy !== null && accuracy >= 0.80) {
                    confidence = 'High';
                  } else if (forecastNow !== null && forecastNow >= 250 && accuracy !== null && accuracy >= 0.62) {
                    confidence = 'Medium';
                  }

                  // V2.1 (ovw2): never show a projection from a battery reading that is not a number.
                  const socRaw = states['sensor.ecco_clock_dongle_ecco_battery_soc']?.state;
                  if (socRaw === undefined || ['unknown','unavailable','none',''].includes(String(socRaw).toLowerCase()) || !Number.isFinite(Number(socRaw))) {
                    return `<div style="padding-top:2px;">
                      <div style="font-size:15px;font-weight:800;color:#aab4c3;">Battery data unavailable</div>
                      <div style="font-size:12px;line-height:1.5;color:rgba(255,255,255,0.64);margin-top:3px;">No projection is shown until the battery SOC reports again.</div>
                    </div>`;
                  }
                  const correctedSolar = Number.isFinite(remaining) ? remaining * factor * 0.95 : null;
                  const conservativeSolar = Number.isFinite(remaining)
                    ? remaining * Math.max(0.60, factor - 0.15) * 0.95
                    : null;

                  const now = new Date();
                  const elapsed = Math.max(now.getHours() + now.getMinutes()/60, 1);
                  const avgSoFar = loadToday / elapsed;
                  const liveKw = load / 1000;
                  const blendedKw = clamp(avgSoFar * 0.65 + liveKw * 0.35, 0.15, 5);

                  const targetTimeRaw = states['sensor.ecco_config_charge_start_time']?.state;
                  const targetMatch = String(targetTimeRaw ?? '').match(/^(\d{1,2}):(\d{2})$/);
                  const targetHour = targetMatch ? Number(targetMatch[1]) : 0;
                  const targetMinute = targetMatch ? Number(targetMatch[2]) : 30;
                  const targetTime = `${String(targetHour).padStart(2,'0')}:${String(targetMinute).padStart(2,'0')}`;
                  const nextCheapStart = new Date(now);
                  nextCheapStart.setHours(targetHour,targetMinute,0,0);
                  if (nextCheapStart <= now) nextCheapStart.setDate(nextCheapStart.getDate()+1);
                  const hoursToCheap = Math.max((nextCheapStart-now)/3600000, 0);
                  const loadToCheap = blendedKw * hoursToCheap;
                  // V2.1 (ovw2): the solar forecast is for the rest of the CURRENT calendar day. Only the part that can still arrive BEFORE
                  // the target time may lift the SOC AT the target. The credit is therefore the share of today's remaining daylight that ends
                  // before the target: 0 before sunrise or once today's daylight is over, 1 when the target is after sunset, and an approximate
                  // time-proportional share when the target falls inside the daylight window. Without sun times no projection is made.
                  const sunEntity = states['sun.sun'];
                  const solarWindow = (() => {
                    const set = sunEntity?.attributes?.next_setting ? new Date(sunEntity.attributes.next_setting) : null;
                    const rise = sunEntity?.attributes?.next_rising ? new Date(sunEntity.attributes.next_rising) : null;
                    if (!set || Number.isNaN(set.getTime())) return { known: false, share: null, partial: false };
                    let from = null;
                    if (sunEntity.state === 'above_horizon') from = now;
                    else if (rise && !Number.isNaN(rise.getTime()) && rise.toDateString() === now.toDateString()) from = rise;
                    if (from === null) return { known: true, share: 0, partial: false };
                    if (nextCheapStart >= set) return { known: true, share: 1, partial: false };
                    if (nextCheapStart <= from) return { known: true, share: 0, partial: false };
                    return { known: true, share: (nextCheapStart - from) / (set - from), partial: true };
                  })();
                  const solarShare = solarWindow.share;
                  if (solarWindow.partial) confidence = 'Low';
                  const minsToTarget = Math.round(hoursToCheap * 60);
                  const untilText = minsToTarget < 90 ? `in ${minsToTarget} min` : `in ${Math.round(hoursToCheap)} h`;
                  const targetLabel = `${targetTime} ${nextCheapStart.toDateString() === now.toDateString() ? 'today' : 'tomorrow'} (${untilText})`;

                  const likelySoc = correctedSolar !== null && solarShare !== null
                    ? clamp(soc + ((correctedSolar*solarShare-loadToCheap)/capKwh)*100, 0, 100)
                    : null;
                  const conservativeSoc = conservativeSolar !== null && solarShare !== null
                    ? clamp(soc + ((conservativeSolar*solarShare-loadToCheap)/capKwh)*100, 0, 100)
                    : null;

                  const currentRateSensors = sensors.filter(s =>
                    s.entity_id.includes('octopus_energy_electricity') &&
                    s.entity_id.includes('current_rate')
                  );
                  const imp = currentRateSensors.find(s => !isExport(s));
                  const exp = currentRateSensors.find(s => isExport(s));
                  const importP = num(imp) !== null ? num(imp)*100 : null;
                  const exportP = num(exp) !== null ? num(exp)*100 : null;

                  // Use ALL of today's rates for cheap/peak reference, not just rates still ahead.
                  const todayEvents = events.filter(s =>
                    s.entity_id.includes('octopus_energy_electricity') &&
                    s.entity_id.includes('current_day_rates') &&
                    !isExport(s)
                  );
                  let dayRates = [];
                  todayEvents.forEach(e => {
                    if (Array.isArray(e.attributes?.rates)) dayRates.push(...e.attributes.rates);
                  });
                  dayRates = dayRates.map(r => Number(r.value_inc_vat)*100).filter(Number.isFinite);

                  const dayCheapP = dayRates.length
                    ? Math.min(...dayRates)
                    : (imp?.attributes?.current_day_min_rate != null ? Number(imp.attributes.current_day_min_rate)*100 : null);
                  const dayPeakP = dayRates.length
                    ? Math.max(...dayRates)
                    : (imp?.attributes?.current_day_max_rate != null ? Number(imp.attributes.current_day_max_rate)*100 : importP);

                  const spread = importP !== null && exportP !== null ? importP-exportP : null;

                  let headline = 'Live monitoring';
                  let detail = `SOC ${soc.toFixed(0)}% • adaptive solar factor ${(factor*100).toFixed(0)}% • ${confidence.toLowerCase()} confidence`;
                  let colour = '#7ab8ff';

                  if (likelySoc !== null && conservativeSoc !== null) {
                    if (conservativeSoc >= 25) {
                      headline = `No additional grid charge indicated • ${confidence.toLowerCase()} confidence`;
                      detail = `Likely SOC at ${targetLabel} is ${likelySoc.toFixed(0)}% and conservative SOC is ${conservativeSoc.toFixed(0)}%.`;
                      colour = '#55e58e';
                    } else if (likelySoc >= 20) {
                      headline = `Keep watch on reserve • ${confidence.toLowerCase()} confidence`;
                      detail = `Likely SOC at ${targetLabel} is ${likelySoc.toFixed(0)}%, but conservative modelling falls to ${conservativeSoc.toFixed(0)}%.`;
                      colour = '#ffbd3d';
                    } else {
                      headline = `Cheap-rate support may be worthwhile • ${confidence.toLowerCase()} confidence`;
                      detail = `Likely SOC at ${targetLabel} is only ${likelySoc.toFixed(0)}% with ${conservativeSoc.toFixed(0)}% on the conservative model.`;
                      colour = '#ff6376';
                    }
                  }

                  if (likelySoc !== null && conservativeSoc !== null) {
                    if (solarShare === 0 && Number.isFinite(remaining) && remaining > 0.05) {
                      detail += ' No solar can arrive before then.';
                    } else if (solarWindow.partial) {
                      detail += ` About ${Math.round(solarShare * 100)}% of the remaining solar arrives before then (approximate).`;
                    }
                  } else if (!solarWindow.known) {
                    headline = 'Projection unavailable';
                    detail = `Sun times are unavailable, so ECCO cannot tell how much of the solar forecast arrives before ${targetLabel}. SOC is ${soc.toFixed(0)}%.`;
                    colour = '#aab4c3';
                  }

                  // V2.1: say which average house load the projection assumes (the model is unchanged: 65% of today's average load plus
                  // 35% of the load right now), so a short spike of load right now is visible as the reason for a low figure.
                  if (likelySoc !== null && conservativeSoc !== null) {
                    detail += ` Assumes about ${blendedKw.toFixed(1)} kW average house load until then (65% today's average, 35% the load right now).`;
                  }
                  if (liveRatio !== null) {
                    detail += ` Live PV is ${Math.round(liveRatio*100)}% of Forecast.Solar right now.`;
                  }

                  // V2.1: the tariff range and the import/export spread are shown by the Tariff now card in the right-hand column;
                  // only the derived round-trip value stays in this text.
                  if (dayCheapP !== null && dayPeakP !== null) {
                    const deliveredCheap = dayCheapP / 0.90;
                    const avoided = dayPeakP - deliveredCheap;
                    detail += ` Cheap-rate energy is about ${deliveredCheap.toFixed(1)}p/kWh delivered after a 90% round-trip assumption.`;
                    if (avoided > 0) {
                      detail += ` That is worth about ${avoided.toFixed(1)}p/kWh versus buying at today's peak rate.`;
                    }
                  }

""")
DASHBOARD_7_OLD = _blk(r"""
              rows: auto

          # ---- BATTERY ESTIMATE (existing ECCO template sensors; display only) ----
          - type: custom:button-card
            section_mode: true
            name: Battery estimate
            show_icon: false
            show_state: false
""")
DASHBOARD_7_NEW = _blk(r"""
              rows: auto

          # ---- TODAY SO FAR (V2.1: the six daily energy totals the dongle already reports; display only) ----
          # The same sensors as the System view's Daily Energy Totals chart, as one compact row. Nothing here can act.
          - type: custom:button-card
            section_mode: true
            name: Today so far
            show_icon: false
            show_state: false
            tap_action:
              action: none
            custom_fields:
              body: >
                [[[
                  const items = [
                    ['PV', 'sensor.ecco_clock_dongle_ecco_day_pv_energy', '#ffbd3d'],
                    ['House', 'sensor.ecco_clock_dongle_ecco_day_load_energy', '#42aaff'],
                    ['Imported', 'sensor.ecco_clock_dongle_ecco_day_grid_import', '#ff6376'],
                    ['Exported', 'sensor.ecco_clock_dongle_ecco_day_grid_export', '#b36cff'],
                    ['Battery in', 'sensor.ecco_clock_dongle_ecco_day_battery_charge', '#39d27a'],
                    ['Battery out', 'sensor.ecco_clock_dongle_ecco_day_battery_discharge', '#65e39a']
                  ];
                  const tile = ([label, id, colour]) => {
                    const raw = states[id]?.state;
                    const v = raw === undefined || ['unknown', 'unavailable', 'none', ''].includes(String(raw).toLowerCase()) ? null : Number(raw);
                    return `<div style="padding:7px 9px;border-radius:11px;background:rgba(255,255,255,.035);border:1px solid rgba(255,255,255,.07);min-width:0;display:flex;flex-direction:column;justify-content:center;">
                      <div style="font-size:10px;font-weight:700;letter-spacing:.45px;color:rgba(255,255,255,.46);text-transform:uppercase;white-space:nowrap;">${label}</div>
                      <div style="font-size:17px;font-weight:800;color:${colour};margin-top:1px;white-space:nowrap;">${v === null || !Number.isFinite(v) ? '--' : v.toFixed(1)} <span style="font-size:11px;color:rgba(255,255,255,.55);font-weight:700;">kWh</span></div>
                    </div>`;
                  };
                  return `<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(104px,1fr));grid-auto-rows:1fr;gap:8px;height:100%;">${items.map(tile).join('')}</div>`;
                ]]]
            styles:
              card:
                - border-radius: 16px
                - padding: 12px 14px
                - background: linear-gradient(145deg, rgba(20,28,45,0.98), rgba(10,15,27,0.98))
                - border: 1px solid rgba(255,255,255,0.08)
                - box-shadow: 0 10px 30px rgba(0,0,0,0.22)
              grid:
                - grid-template-areas: '"n" "body"'
                - grid-template-columns: 1fr
                - grid-template-rows: min-content 1fr
                - row-gap: 6px
              name:
                - justify-self: start
                - align-self: center
                - font-size: 11px
                - font-weight: 800
                - text-transform: uppercase
                - letter-spacing: 0.05em
                - color: rgba(255,255,255,0.5)
              custom_fields:
                body:
                  - justify-self: stretch
                  - align-self: stretch
                  - width: 100%
                  - white-space: normal
            grid_options:
              columns: 12
              rows: auto

          # ---- BATTERY OUTLOOK (V2.1: the Battery estimate tile plus the learned load-only outlook and its accuracy; display only) ----
          # Existing ECCO template sensors only. The reserve tile shows the ECCO minimum-reserve SETTING, which is independent of the
          # Dump to Grid stop SOC. The learned outlook is a load-only floor (it ignores solar) from the Battery Outlook task.
          - type: custom:button-card
            section_mode: true
            name: Battery outlook
            show_icon: false
            show_state: false
""")
DASHBOARD_8_OLD = _blk(r"""
                [[[
                  const n = id => {
                    const v = Number(states[id]?.state);
                    return Number.isFinite(v) ? v : null;
                  };
                  const f = (v, d=1) => v === null ? '--' : v.toFixed(d);
                  const kwh = n('sensor.ecco_battery_energy_estimate');
                  const soc = n('sensor.ecco_battery_soc');
""")
DASHBOARD_8_NEW = _blk(r"""
                [[[
                  const n = id => {
                    const raw = states[id]?.state;
                    if (raw === undefined || ['unknown','unavailable','none',''].includes(String(raw).toLowerCase())) return null;
                    const v = Number(raw);
                    return Number.isFinite(v) ? v : null;
                  };
                  const f = (v, d=1) => v === null ? '--' : v.toFixed(d);
                  const signed = (v, d=1) => v === null ? '--' : `${v >= 0 ? '+' : ''}${v.toFixed(d)}`;
                  const kwh = n('sensor.ecco_battery_energy_estimate');
                  const soc = n('sensor.ecco_battery_soc');
""")
DASHBOARD_9_OLD = _blk(r"""
                  const reserve = n('sensor.ecco_config_minimum_reserve_soc');
                  const predicted = n('sensor.ecco_predicted_soc_plus_1_hour_baseline');
                  const ttr = states['sensor.ecco_battery_time_to_reserve']?.attributes?.summary;
                  const esc = s => String(s).replace(/[&<>]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' })[c]);
                  return `<div>
                    <div style="display:flex;align-items:baseline;gap:10px;flex-wrap:wrap;">
                      <span style="font-size:17px;font-weight:800;color:#39d27a;white-space:nowrap;">${f(kwh)} kWh</span>
                      <span style="font-size:12px;color:rgba(255,255,255,.62);">stored · ${f(soc,0)} % of ${f(cap)} kWh</span>
                    </div>
                    <div style="font-size:12px;color:rgba(255,255,255,.62);margin-top:4px;">Reserve floor <b style="color:#fff;">${f(reserve,0)} %</b> · predicted SOC +1 h <b style="color:#fff;">${f(predicted,1)} %</b></div>
                    <div style="font-size:12px;color:rgba(255,255,255,.62);margin-top:4px;">Time to reserve <b style="color:#fff;">${ttr ? esc(ttr) : '--'}</b></div>
                  </div>`;
                ]]]
            styles:
              card:
                - border-radius: 16px
                - padding: 12px 14px
                - background: linear-gradient(145deg, rgba(20,28,45,0.98), rgba(10,15,27,0.98))
                - border: 1px solid rgba(255,255,255,0.08)
                - box-shadow: 0 10px 30px rgba(0,0,0,0.22)
              grid:
                - grid-template-areas: '"n" "body"'
                - grid-template-columns: 1fr
                - grid-template-rows: min-content 1fr
                - row-gap: 6px
              name:
                - justify-self: start
                - align-self: center
                - font-size: 11px
                - font-weight: 800
                - text-transform: uppercase
                - letter-spacing: 0.05em
                - color: rgba(255,255,255,0.5)
              custom_fields:
                body:
                  - justify-self: stretch
                  - width: 100%
            grid_options:
              columns: 12
""")
DASHBOARD_9_NEW = _blk(r"""
                  const reserve = n('sensor.ecco_config_minimum_reserve_soc');
                  const predicted = n('sensor.ecco_predicted_soc_plus_1_hour_baseline');
                  const floorSoc = n('sensor.ecco_predicted_soc_0035');
                  const loadKwh = n('sensor.ecco_expected_load_to_0035');
                  const scoredPrediction = n('sensor.ecco_battery_outlook_last_scored_prediction');
                  const scoredActual = n('sensor.ecco_battery_outlook_last_actual_soc');
                  const scoredError = n('sensor.ecco_battery_outlook_last_error');
                  const mae = n('sensor.ecco_battery_outlook_7_day_mae');
                  const bias = n('sensor.ecco_battery_outlook_7_day_bias');
                  const ttr = states['sensor.ecco_battery_time_to_reserve']?.attributes?.summary;
                  const esc = s => String(s).replace(/[&<>]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' })[c]);
                  const tile = (label, value, sub, colour) => `<div style="padding:8px 10px;border-radius:11px;background:rgba(255,255,255,.035);border:1px solid rgba(255,255,255,.07);min-width:0;">
                    <div style="font-size:10px;font-weight:700;letter-spacing:.45px;color:rgba(255,255,255,.46);text-transform:uppercase;">${label}</div>
                    <div style="font-size:19px;font-weight:800;color:${colour};margin-top:1px;white-space:nowrap;">${value}</div>
                    <div style="font-size:11px;color:rgba(255,255,255,.55);margin-top:1px;">${sub}</div>
                  </div>`;
                  const top = `<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:8px;">
                    ${tile('Stored', `${f(kwh)} kWh`, `${f(soc,0)} % of ${f(cap)} kWh`, '#39d27a')}
                    ${tile('Reserve setting', `${f(reserve,0)} %`, 'separate from the Dump to Grid stop', '#b8adff')}
                    ${tile('Next hour', predicted === null ? '--' : `${f(predicted)} %`, 'at the current battery power', '#7ab8ff')}
                  </div>`;
                  let learned;
                  if (floorSoc === null || loadKwh === null) {
                    learned = `<div style="margin-top:8px;font-size:11px;color:rgba(255,255,255,.50);">The learned outlook is not available yet (it needs the Battery Outlook task and its InfluxDB data).</div>`;
                  } else {
                    const err = scoredError;
                    const absErr = err === null ? null : Math.abs(err);
                    const colour = absErr === null ? '#8f7cff' : absErr <= 2 ? '#55e58e' : absErr <= 5 ? '#ffbd3d' : '#ff7a7a';
                    const score = scoredPrediction !== null && scoredActual !== null
                      ? `last night ${f(scoredPrediction)} % → ${f(scoredActual)} % <span style="color:${colour};font-weight:800;">(${signed(err)} pts)</span>${mae === null ? '' : ` · 7-day average miss ${f(mae)} pts`}${bias === null ? '' : ` · bias ${signed(bias)}`}`
                      : 'no score yet';
                    learned = `<div style="margin-top:8px;padding:9px 11px;border-radius:11px;background:rgba(143,124,255,.045);border:1px solid rgba(143,124,255,.16);">
                      <div style="font-size:10px;font-weight:700;letter-spacing:.45px;color:rgba(255,255,255,.46);text-transform:uppercase;">Learned outlook · load only, ignores solar</div>
                      <div style="display:flex;align-items:baseline;gap:10px;flex-wrap:wrap;margin-top:2px;">
                        <span style="font-size:19px;font-weight:800;color:#fff;">${f(floorSoc)} %</span>
                        <span style="font-size:12px;color:rgba(255,255,255,.62);">at 00:35 · expected load ${f(loadKwh,2)} kWh</span>
                      </div>
                      <div style="font-size:11px;color:rgba(255,255,255,.52);margin-top:2px;">Accuracy: ${score}</div>
                    </div>`;
                  }
                  const runtime = `<div style="font-size:12px;color:rgba(255,255,255,.62);margin-top:8px;">Time to reserve <b style="color:#fff;">${ttr ? esc(ttr) : '--'}</b></div>`;
                  return `<div>${top}${runtime}${learned}</div>`;
                ]]]
            styles:
              card:
                - border-radius: 16px
                - padding: 12px 14px
                - background: linear-gradient(145deg, rgba(20,28,45,0.98), rgba(10,15,27,0.98))
                - border: 1px solid rgba(255,255,255,0.08)
                - box-shadow: 0 10px 30px rgba(0,0,0,0.22)
              grid:
                - grid-template-areas: '"n" "body"'
                - grid-template-columns: 1fr
                - grid-template-rows: min-content 1fr
                - row-gap: 6px
              name:
                - justify-self: start
                - align-self: center
                - font-size: 11px
                - font-weight: 800
                - text-transform: uppercase
                - letter-spacing: 0.05em
                - color: rgba(255,255,255,0.5)
              custom_fields:
                body:
                  - justify-self: stretch
                  - width: 100%
                  - white-space: normal
            grid_options:
              columns: 12
""")
DASHBOARD_10_OLD = _blk(r"""
                  };
                  const word = v => unknown(v) ? '--' : String(v);
                  const row = (label, armedId, startId, powerId, durationId, stopSocId, statusId) => {
                    const armedRaw = st(armedId);
                    const armed = armedRaw === 'on';
""")
DASHBOARD_10_NEW = _blk(r"""
                  };
                  const word = v => unknown(v) ? '--' : String(v);
                  const cnt = (prefix, kind) => {
                    const v = num(`sensor.ecco_clock_dongle_${prefix}_${kind}_since_boot`);
                    return v === null ? '--' : v.toFixed(0);
                  };
                  const row = (label, armedId, startId, powerId, durationId, stopSocId, statusId, prefix) => {
                    const armedRaw = st(armedId);
                    const armed = armedRaw === 'on';
""")
DASHBOARD_11_OLD = _blk(r"""
                    return `<div style="display:grid;grid-template-columns:8px 1fr;align-items:start;gap:7px;padding:3px 0;border-bottom:1px solid rgba(255,255,255,.05);">
                      <span style="width:7px;height:7px;border-radius:50%;background:${tone};margin-top:5px;"></span>
                      <div style="min-width:0;">
                        <div style="font-size:12px;color:rgba(255,255,255,.86);"><b>${label}</b> · ${parts.join(' · ')} <span style="font-size:10px;font-weight:800;letter-spacing:.45px;color:rgba(255,255,255,.46);">${word(status).toUpperCase()}</span></div>
                        <div style="font-size:11px;color:rgba(255,255,255,.52);margin-top:1px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">Last result: ${unknown(last) ? '--' : String(last)}</div>
                      </div>
                    </div>`;
                  };
                  return `<div style="display:grid;gap:4px;">
                    ${row('Free Power', 'input_boolean.ecco_free_power_schedule_armed', 'input_datetime.ecco_free_power_schedule_start', 'input_number.ecco_free_power_schedule_power', 'input_number.ecco_free_power_schedule_duration', null, 'sensor.ecco_free_power_schedule_status')}
                    ${row('Dump to Grid', 'input_boolean.ecco_dump_to_grid_schedule_armed', 'input_datetime.ecco_dump_to_grid_schedule_start', 'input_number.ecco_dump_to_grid_schedule_power', 'input_number.ecco_dump_to_grid_schedule_duration', 'input_number.ecco_dump_to_grid_schedule_stop_soc', 'sensor.ecco_dump_to_grid_schedule_status')}
                  </div>`;
                ]]]
            styles:
              card:
                - border-radius: 16px
                - padding: 12px 14px
                - background: linear-gradient(145deg, rgba(20,28,45,0.98), rgba(10,15,27,0.98))
                - border: 1px solid rgba(255,255,255,0.08)
                - box-shadow: 0 10px 30px rgba(0,0,0,0.22)
              grid:
                - grid-template-areas: '"n" "body"'
                - grid-template-columns: 1fr
                - grid-template-rows: min-content 1fr
                - row-gap: 6px
              name:
                - justify-self: start
                - align-self: center
                - font-size: 11px
                - font-weight: 800
                - text-transform: uppercase
                - letter-spacing: 0.05em
                - color: rgba(255,255,255,0.5)
              custom_fields:
                body:
                  - justify-self: stretch
                  - width: 100%
            grid_options:
              columns: 12
              rows: auto

""")
DASHBOARD_11_NEW = _blk(r"""
                    return `<div style="display:grid;grid-template-columns:8px 1fr;align-items:start;gap:7px;padding:3px 0;border-bottom:1px solid rgba(255,255,255,.05);">
                      <span style="width:7px;height:7px;border-radius:50%;background:${tone};margin-top:5px;"></span>
                      <div style="min-width:0;text-align:left;">
                        <div style="font-size:12px;color:rgba(255,255,255,.86);"><b>${label}</b> · ${parts.join(' · ')} <span style="font-size:10px;font-weight:800;letter-spacing:.45px;color:rgba(255,255,255,.46);">${word(status).toUpperCase()}</span></div>
                        <div style="font-size:11px;color:rgba(255,255,255,.52);margin-top:1px;overflow:hidden;display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;overflow-wrap:anywhere;">Last result: ${unknown(last) ? '--' : String(last)}</div>
                        <div style="font-size:11px;color:rgba(255,255,255,.46);margin-top:1px;">Since the dongle last restarted: ${cnt(prefix, 'start_successes')} started · ${cnt(prefix, 'restore_successes')} restored · ${cnt(prefix, 'failures')} failed</div>
                      </div>
                    </div>`;
                  };
                  return `<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(min(300px,100%),1fr));gap:4px 16px;">
                    ${row('Free Power', 'input_boolean.ecco_free_power_schedule_armed', 'input_datetime.ecco_free_power_schedule_start', 'input_number.ecco_free_power_schedule_power', 'input_number.ecco_free_power_schedule_duration', null, 'sensor.ecco_free_power_schedule_status', 'free_power')}
                    ${row('Dump to Grid', 'input_boolean.ecco_dump_to_grid_schedule_armed', 'input_datetime.ecco_dump_to_grid_schedule_start', 'input_number.ecco_dump_to_grid_schedule_power', 'input_number.ecco_dump_to_grid_schedule_duration', 'input_number.ecco_dump_to_grid_schedule_stop_soc', 'sensor.ecco_dump_to_grid_schedule_status', 'dump_to_grid')}
                  </div>`;
                ]]]
            styles:
              card:
                - border-radius: 16px
                - padding: 12px 14px
                - background: linear-gradient(145deg, rgba(20,28,45,0.98), rgba(10,15,27,0.98))
                - border: 1px solid rgba(255,255,255,0.08)
                - box-shadow: 0 10px 30px rgba(0,0,0,0.22)
              grid:
                - grid-template-areas: '"n" "body"'
                - grid-template-columns: 1fr
                - grid-template-rows: min-content 1fr
                - row-gap: 6px
              name:
                - justify-self: start
                - align-self: center
                - font-size: 11px
                - font-weight: 800
                - text-transform: uppercase
                - letter-spacing: 0.05em
                - color: rgba(255,255,255,0.5)
              custom_fields:
                body:
                  - justify-self: stretch
                  - width: 100%
                  - white-space: normal
            grid_options:
              columns: full
              rows: auto

""")
DASHBOARD_12_OLD = _blk(r"""
        column_span: 3
        cards:
          # ---- MAIN POWER GRAPH ----
          - type: custom:apexcharts-card
            section_mode: true
            grid_options:
              columns: full
              rows: 7
            header:
              show: true
              title: Power Flow Today • 00:00–24:00
              show_states: true
              colorize_states: true
            graph_span: 24h
            span:
              start: day
            yaxis:
              - id: power
                decimals: 0
                min: '|-500|'
                max: '|+500|'
                apex_config:
                  tickAmount: 6
                  title:
                    text: Power (W)
              - id: soc
                opposite: true
                min: 0
                max: 100
                decimals: 0
                apex_config:
                  tickAmount: 5
                  title:
                    text: SOC (%)
            all_series_config:
              stroke_width: 2
              extend_to: now
              group_by:
                func: avg
                duration: 5min
                fill: 'null'
            series:
              - entity: sensor.ecco_clock_dongle_ecco_pv_power
                name: Solar
                yaxis_id: power
                type: area
                color: '#ffbd3d'
                opacity: 0.22
              - entity: sensor.ecco_clock_dongle_ecco_load_power
                name: House
                yaxis_id: power
                type: line
                color: '#42aaff'
                stroke_width: 3
              - entity: sensor.ecco_clock_dongle_ecco_battery_output_power
                name: Battery
                yaxis_id: power
                type: area
                color: '#39d27a'
                opacity: 0.14
              - entity: sensor.ecco_clock_dongle_ecco_grid_power_ct_clamp
                name: Grid
                yaxis_id: power
                type: line
                color: '#b36cff'
                stroke_width: 2
              - entity: sensor.ecco_clock_dongle_ecco_battery_soc
                name: SOC
                yaxis_id: soc
                type: line
                color: '#ff6376'
                stroke_width: 2
                opacity: 0.95
                group_by:
                  func: last
                  duration: 5min
                  fill: last
              - entity: sensor.ecco_clock_dongle_ecco_battery_soc
                name: SOC Model
                yaxis_id: soc
                type: line
                color: '#ffb347'
                stroke_width: 3
                opacity: 1
                extend_to: false
                show:
                  in_header: false
                data_generator: |
                  const n=(id)=>Number(hass.states[id]?.state??0);
                  const clamp=(v,a,b)=>Math.max(a,Math.min(b,v));
                  const sensors=Object.values(hass.states).filter(s=>s.entity_id.startsWith('sensor.'));
                  const friendly=(s)=>String(s?.attributes?.friendly_name??s?.entity_id??'').toLowerCase();
                  const find=(need,exclude=[])=>sensors.find(s=>{
                    const x=friendly(s);return need.every(v=>x.includes(v))&&!exclude.some(v=>x.includes(v));
                  });
                  const num=(s)=>{const v=Number(s?.state);return Number.isFinite(v)?v:null;};

                  const soc=n('sensor.ecco_clock_dongle_ecco_battery_soc');
                  const loadToday=n('sensor.ecco_clock_dongle_ecco_day_load_energy');
                  const loadW=n('sensor.ecco_clock_dongle_ecco_load_power');
                  const pvW=n('sensor.ecco_clock_dongle_ecco_pv_power');
                  const actualPV=n('sensor.ecco_clock_dongle_ecco_day_pv_energy');
                  const capAh=n('sensor.ecco_clock_dongle_ecco_battery_capacity_ah')||620;
                  const capKwh=capAh*51.2/1000;

                  const forecast=num(states['sensor.ecco_solar_forecast_today']);
                  const remaining=num(states['sensor.ecco_solar_forecast_remaining']);
                  const forecastNow=num(states['sensor.ecco_solar_forecast_power_now']);

                  let ratio=1;
                  if(forecastNow!==null&&forecastNow>=250)ratio=clamp(pvW/forecastNow,.15,1.5);
                  let factor=forecastNow!==null&&forecastNow>=250?clamp(.65+.35*ratio,.70,1.10):1;
                  const expectedSoFar=forecast!==null&&remaining!==null?Math.max(forecast-remaining,0):0;
                  if(expectedSoFar>=2&&actualPV>=.5){
                    const dailyRatio=clamp(actualPV/expectedSoFar,.35,1.35);
                    factor=clamp(factor*.60+dailyRatio*.40,.65,1.10);
                  }

                  const now=new Date();
                  const elapsed=Math.max(now.getHours()+now.getMinutes()/60,1);
                  const avgKw=loadToday/elapsed;
                  const liveKw=loadW/1000;
                  const loadKw=clamp(avgKw*.65+liveKw*.35,.15,5);

                  const sun=hass.states['sun.sun'];
                  const sunset=sun?.state==='above_horizon'?new Date(sun.attributes?.next_setting):now;
                  const hSun=Math.max((sunset-now)/3600000,0);
                  const solarKwh=remaining!==null?remaining*factor*.95:0;
                  const solarKw=hSun>0?solarKwh/hSun:0;

                  const modelEnd=new Date(now);
                  modelEnd.setHours(24,0,0,0);
                  const out=[[now.getTime(),soc]];
                  let model=soc;
                  let t=new Date(now);
                  while(t<modelEnd){
                    const next=new Date(Math.min(t.getTime()+30*60000,modelEnd.getTime()));
                    const dt=(next-t)/3600000;
                    const solar=next<=sunset?solarKw:0;
                    model=clamp(model+((solar-loadKw)*dt/capKwh)*100,0,100);
                    out.push([next.getTime(),model]);
                    t=next;
                  }
                  return out;
            now:
              show: true
""")
DASHBOARD_12_NEW = _blk(r"""
        column_span: 3
        cards:
          # ---- CHART DATA STATUS (V2.1): tells a quiet new day apart from a sensor that is not reporting ----
          # Shown only when it has something to say; display only.
          - type: custom:button-card
            section_mode: true
            show_name: false
            show_icon: false
            show_state: false
            tap_action:
              action: none
            variables:
              msg: >
                [[[
                  const ids = [['Solar', 'sensor.ecco_clock_dongle_ecco_pv_power'], ['House', 'sensor.ecco_clock_dongle_ecco_load_power'], ['Battery', 'sensor.ecco_clock_dongle_ecco_battery_output_power'], ['Grid', 'sensor.ecco_clock_dongle_ecco_grid_power_ct_clamp'], ['SOC', 'sensor.ecco_clock_dongle_ecco_battery_soc']];
                  const bad = ids.filter(([, id]) => {
                    const s = states[id]?.state;
                    return s === undefined || ['unknown', 'unavailable'].includes(String(s).toLowerCase());
                  }).map(([name]) => name);
                  const now = new Date();
                  const minutes = now.getHours() * 60 + now.getMinutes();
                  if (bad.length) {
                    return `<span style="color:#ffbd3d;font-weight:800;">Not reporting now: ${bad.join(', ')}.</span> A gap or flat line for ${bad.length > 1 ? 'these' : 'this'} is missing data, not a quiet day.`;
                  }
                  if (minutes < 90) {
                    return `<span style="color:#7ab8ff;font-weight:800;">New day.</span> The chart starts at 00:00 and fills as history builds (${minutes} min so far), so short lines are normal now.`;
                  }
                  return '';
                ]]]
            custom_fields:
              note: '[[[ return variables.msg; ]]]'
            styles:
              card:
                - display: '[[[ return variables.msg ? "block" : "none"; ]]]'
                - border-radius: 12px
                - padding: 7px 12px
                - background: rgba(122,184,255,0.06)
                - border: 1px solid rgba(122,184,255,0.18)
                - box-shadow: none
              grid:
                - grid-template-areas: '"note"'
                - grid-template-columns: 1fr
              custom_fields:
                note:
                  - justify-self: stretch
                  - font-size: 11px
                  - line-height: 1.45
                  - color: rgba(255,255,255,0.72)
                  - white-space: normal
            grid_options:
              columns: full
              rows: auto
          # ---- MAIN POWER GRAPH ----
          - type: custom:apexcharts-card
            section_mode: true
            grid_options:
              columns: full
              rows: 7
            header:
              show: true
              title: Power Flow Today • 00:00–24:00
              show_states: true
              colorize_states: true
            graph_span: 24h
            span:
              start: day
            yaxis:
              - id: power
                decimals: 0
                min: '|-500|'
                max: '|+500|'
                apex_config:
                  tickAmount: 6
                  title:
                    text: Power (W)
              - id: soc
                opposite: true
                min: 0
                max: 100
                decimals: 0
                apex_config:
                  tickAmount: 5
                  title:
                    text: SOC (%)
            all_series_config:
              stroke_width: 2
              extend_to: now
              group_by:
                func: avg
                duration: 5min
                fill: 'null'
            series:
              - entity: sensor.ecco_clock_dongle_ecco_pv_power
                name: Solar
                yaxis_id: power
                type: area
                color: '#ffbd3d'
                opacity: 0.22
              - entity: sensor.ecco_clock_dongle_ecco_load_power
                name: House
                yaxis_id: power
                type: line
                color: '#42aaff'
                stroke_width: 3
              - entity: sensor.ecco_clock_dongle_ecco_battery_output_power
                name: Battery
                yaxis_id: power
                type: area
                color: '#39d27a'
                opacity: 0.14
              - entity: sensor.ecco_clock_dongle_ecco_grid_power_ct_clamp
                name: Grid
                yaxis_id: power
                type: line
                color: '#b36cff'
                stroke_width: 2
              - entity: sensor.ecco_clock_dongle_ecco_battery_soc
                name: SOC
                yaxis_id: soc
                type: line
                color: '#ff6376'
                stroke_width: 2
                opacity: 0.95
                group_by:
                  func: last
                  duration: 5min
                  fill: last
            now:
              show: true
""")
DASHBOARD_13_OLD = _blk(r"""
                height: 365
                toolbar:
                  show: false
              dataLabels:
                enabled: false
              legend:
                position: top
                horizontalAlign: left
              stroke:
                curve: smooth
                dashArray: [0, 0, 0, 0, 0, 6]
              grid:
                borderColor: rgba(255,255,255,0.08)
""")
DASHBOARD_13_NEW = _blk(r"""
                height: 365
                toolbar:
                  show: false
              dataLabels:
                enabled: false
              legend:
                position: top
                horizontalAlign: left
              stroke:
                curve: smooth
                dashArray: [0, 0, 0, 0, 0]
              grid:
                borderColor: rgba(255,255,255,0.08)
""")
DASHBOARD_14_OLD = _blk(r"""
                  ];
                  return `<div style="display:grid;gap:3px;">
                    ${rows.map(r => `<div style="display:grid;grid-template-columns:8px 1fr auto;align-items:center;gap:7px;padding:4px 0;border-bottom:1px solid rgba(255,255,255,.05);">
                      <span style="width:7px;height:7px;border-radius:50%;background:${r[2]};"></span>
                      <span style="font-size:12px;color:rgba(255,255,255,.62);">${r[0]}</span>
                      <span style="font-size:12px;font-weight:700;color:rgba(255,255,255,.92);text-align:right;">${r[1]}</span>
                    </div>`).join('')}
""")
DASHBOARD_14_NEW = _blk(r"""
                  ];
                  return `<div style="display:grid;gap:3px;">
                    ${rows.map(r => `<div style="display:grid;grid-template-columns:8px minmax(0,1fr) auto;align-items:center;gap:7px;padding:4px 0;border-bottom:1px solid rgba(255,255,255,.05);">
                      <span style="width:7px;height:7px;border-radius:50%;background:${r[2]};"></span>
                      <span style="font-size:12px;color:rgba(255,255,255,.62);white-space:normal;">${r[0]}</span>
                      <span style="font-size:12px;font-weight:700;color:rgba(255,255,255,.92);text-align:right;">${r[1]}</span>
                    </div>`).join('')}
""")
DASHBOARD_15_OLD = _blk(r"""
                - width: 20px
                - color: '#8f7cff'
              name:
                - justify-self: start
                - align-self: center
                - font-size: 15px
                - font-weight: 700
                - color: rgba(255,255,255,0.92)
              custom_fields:
                body:
                  - justify-self: stretch
                  - width: 100%
            grid_options:
              columns: full
""")
DASHBOARD_15_NEW = _blk(r"""
                - width: 20px
                - color: '#8f7cff'
              name:
                - justify-self: start
                - align-self: center
                - font-size: 15px
                - font-weight: 700
                - color: rgba(255,255,255,0.92)
              custom_fields:
                body:
                  - justify-self: stretch
                  - width: 100%
            grid_options:
              columns: full
              rows: auto

          # ---- COMING UP for pages narrower than four columns (V2.1: the same card as the right-hand column's, shown here instead; display only) ----
          # See the right-hand column's copy: a Home Assistant screen condition shows exactly one of the two.
          - type: custom:button-card
            section_mode: true
            name: Coming up
            show_icon: false
            show_state: false
            tap_action:
              action: none
            custom_fields:
              body: >
                [[[
                  const now = new Date();
                  const horizon = now.getTime() + 24 * 3600000;
                  const evs = [];
                  const addEv = (t, label, tone) => {
                    const d = t instanceof Date ? t : new Date(t);
                    const ms = d.getTime();
                    if (Number.isFinite(ms) && ms > now.getTime() && ms <= horizon) evs.push({ t: d, label, tone });
                  };
                  const sun = states['sun.sun'];
                  if (sun?.attributes?.next_rising) addEv(sun.attributes.next_rising, 'Sunrise', '#ffbd3d');
                  if (sun?.attributes?.next_setting) addEv(sun.attributes.next_setting, 'Sunset', '#ff9a5c');
                  const slotRead = (i, kind) => states[`sensor.ecco_clock_dongle_ecco_timezone${i}_${kind}`]?.state;
                  const toMin = t => {
                    const m = String(t ?? '').match(/^(\d{1,2}):(\d{2})$/);
                    return m ? Number(m[1]) * 60 + Number(m[2]) : null;
                  };
                  const nextAt = mins => {
                    const d = new Date(now);
                    d.setHours(Math.floor(mins / 60), mins % 60, 0, 0);
                    if (d <= now) d.setDate(d.getDate() + 1);
                    return d;
                  };
                  for (let i = 1; i <= 6; i++) {
                    const start = toMin(slotRead(i, 'time')), end = toMin(slotRead(i === 6 ? 1 : i + 1, 'time'));
                    const charge = slotRead(i, 'charge'), soc = Number(slotRead(i, 'soc'));
                    if (start === null || end === null || !charge || ['None', 'none', 'unknown', 'unavailable'].includes(charge)) continue;
                    addEv(nextAt(start), `${charge} charge starts${Number.isFinite(soc) ? ` · ${soc.toFixed(0)} % target` : ''}`, '#b8adff');
                    addEv(nextAt(end), `${charge} charge ends`, '#b8adff');
                  }
                  const events = Object.values(states).filter(s => s.entity_id.startsWith('event.'));
                  const isExport = s => s.entity_id.includes('export') || String(s?.attributes?.friendly_name ?? '').toLowerCase().includes('export');
                  const rates = [];
                  ['current_day_rates', 'next_day_rates'].forEach(needle => {
                    const ev = events.find(s => s.entity_id.includes('octopus_energy_electricity') && s.entity_id.includes(needle) && !isExport(s));
                    (Array.isArray(ev?.attributes?.rates) ? ev.attributes.rates : []).forEach(r => {
                      const p = Number(r.value_inc_vat) * 100, s0 = new Date(r.start), e0 = new Date(r.end);
                      if (Number.isFinite(p) && !isNaN(s0) && !isNaN(e0)) rates.push({ s: s0, e: e0, p });
                    });
                  });
                  rates.sort((a, b) => a.s - b.s);
                  if (rates.length) {
                    const lo = Math.min(...rates.map(r => r.p)), hi = Math.max(...rates.map(r => r.p));
                    let prev = null;
                    rates.forEach(r => {
                      if (prev && Math.abs(r.p - prev.p) > 0.35 && Math.abs(r.s - prev.e) < 60000) {
                        const peak = hi - lo > 1 && Math.abs(r.p - hi) <= 0.35;
                        const cheap = hi - lo > 1 && Math.abs(r.p - lo) <= 0.35;
                        addEv(r.s, `${peak ? 'Peak rate' : cheap ? 'Cheap rate' : 'Standard rate'} · ${r.p.toFixed(1)} p/kWh`, peak ? '#ff5f6d' : cheap ? '#55e58e' : '#66b3ff');
                      }
                      prev = r;
                    });
                  }
                  [['Free Power', 'input_boolean.ecco_free_power_schedule_armed', 'input_datetime.ecco_free_power_schedule_start'],
                   ['Dump to Grid', 'input_boolean.ecco_dump_to_grid_schedule_armed', 'input_datetime.ecco_dump_to_grid_schedule_start']].forEach(([label, armed, start]) => {
                    const when = String(states[start]?.state ?? '');
                    if (states[armed]?.state === 'on' && when.length === 19) addEv(new Date(when.replace(' ', 'T')), `${label} session · armed`, '#c07cff');
                  });
                  evs.sort((a, b) => a.t - b.t);
                  if (!evs.length) return `<div style="font-size:12px;color:rgba(255,255,255,.55);">No sun, tariff or session events found for the next 24 hours.</div>`;
                  const hhmm = d => `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
                  const left = d => {
                    const m = Math.round((d - now) / 60000);
                    return m < 60 ? `${m} min` : `${Math.floor(m / 60)} h${m % 60 ? ` ${m % 60} min` : ''}`;
                  };
                  const dayTag = d => d.toDateString() === now.toDateString() ? '' : ' tomorrow';
                  return `<div style="display:grid;gap:2px;">${evs.slice(0, 8).map(e => `<div style="display:grid;grid-template-columns:8px minmax(0,1fr) auto;gap:8px;align-items:baseline;padding:4px 0;border-bottom:1px solid rgba(255,255,255,.05);">
                    <span style="width:7px;height:7px;border-radius:50%;background:${e.tone};align-self:center;"></span>
                    <span style="font-size:12px;color:rgba(255,255,255,.80);text-align:left;"><b style="font-size:13px;color:#fff;">${hhmm(e.t)}</b><span style="font-size:10px;color:rgba(255,255,255,.45);">${dayTag(e.t)}</span> &nbsp;${e.label}</span>
                    <span style="font-size:11px;color:rgba(255,255,255,.46);white-space:nowrap;">in ${left(e.t)}</span>
                  </div>`).join('')}</div>`;
                ]]]
            styles:
              card:
                - border-radius: 16px
                - padding: 12px 14px
                - background: linear-gradient(145deg, rgba(20,28,45,0.98), rgba(10,15,27,0.98))
                - border: 1px solid rgba(255,255,255,0.08)
                - box-shadow: 0 10px 30px rgba(0,0,0,0.22)
              grid:
                - grid-template-areas: '"n" "body"'
                - grid-template-columns: 1fr
                - grid-template-rows: min-content 1fr
                - row-gap: 6px
              name:
                - justify-self: start
                - align-self: center
                - font-size: 11px
                - font-weight: 800
                - text-transform: uppercase
                - letter-spacing: 0.05em
                - color: rgba(255,255,255,0.5)
              custom_fields:
                body:
                  - justify-self: stretch
                  - width: 100%
                  - white-space: normal
            # Home Assistant screen condition: this copy is for pages narrower than four columns; wider pages show the identical copy in the right-hand
            # column beside the Energy Flow.
            visibility:
              - condition: screen
                media_query: '(max-width: 1695px)'
            grid_options:
              columns: full
""")
DASHBOARD_16_OLD = _blk(r"""
                    const pct = Math.round((actualNow / forecastNow) * 100);
                    const diff = actualNow - forecastNow;
                    nowCompare = ` • actual now <b style="color:${diff >= 0 ? '#55e58e' : '#ffbd3d'}">${pct}%</b> of forecast`;
                  }

                  return `<div style="padding:10px 12px;border-radius:12px;background:rgba(255,189,61,0.055);
                    border:1px solid rgba(255,189,61,0.16);color:rgba(255,255,255,0.72);font-size:12px;line-height:1.55;">
                    <b style="color:#ffbd3d;">Solar model</b>
                    ${today !== null ? ` • <b>${today.toFixed(1)} kWh</b> today` : ''}
                    ${remaining !== null ? ` • <b>${remaining.toFixed(1)} kWh</b> remaining` : ''}
                    ${forecastNow !== null ? ` • <b>${Math.round(forecastNow)} W</b> forecast now` : ''}
                    ${nowCompare}
                    ${tomorrow !== null ? ` • next day <b>${tomorrow.toFixed(1)} kWh</b>` : ''}
                  </div>`;
                ]]]
              recommendation: >
                [[[
                  const n = (id) => Number(states[id]?.state ?? 0);
                  const clamp = (v,a,b) => Math.max(a,Math.min(b,v));
                  const pv = n('sensor.ecco_clock_dongle_ecco_pv_power');
                  const load = n('sensor.ecco_clock_dongle_ecco_load_power');
                  const soc = n('sensor.ecco_clock_dongle_ecco_battery_soc');
                  const loadToday = n('sensor.ecco_clock_dongle_ecco_day_load_energy');
                  const capAh = n('sensor.ecco_clock_dongle_ecco_battery_capacity_ah') || 620;
                  const capKwh = capAh * 51.2 / 1000;

                  const sensors = Object.values(states).filter(s => s.entity_id.startsWith('sensor.'));
                  const events = Object.values(states).filter(s => s.entity_id.startsWith('event.'));
                  const friendly = (s) => String(s?.attributes?.friendly_name ?? s?.entity_id ?? '').toLowerCase();
                  const find = (need, exclude=[]) => sensors.find(s => {
                    const x = friendly(s);
                    return need.every(v => x.includes(v)) && !exclude.some(v => x.includes(v));
                  });
                  const num = (s) => {
                    const v = Number(s?.state);
                    return Number.isFinite(v) ? v : null;
                  };
                  const isExport = (s) => s.entity_id.includes('export') || friendly(s).includes('export');

                  const forecastToday = num(states['sensor.ecco_solar_forecast_today']);
                  const remaining = num(states['sensor.ecco_solar_forecast_remaining']);
                  const forecastNow = num(states['sensor.ecco_solar_forecast_power_now']);
                  const actualToday = n('sensor.ecco_clock_dongle_ecco_day_pv_energy');

                  let liveRatio = null;
                  if (forecastNow !== null && forecastNow >= 250) {
                    liveRatio = clamp(pv / forecastNow, 0.15, 1.50);
                  }

                  let factor = liveRatio !== null
                    ? clamp(0.65 + 0.35 * liveRatio, 0.70, 1.10)
                    : 1.0;

                  let dailyRatio = null;
                  if (forecastToday !== null && remaining !== null) {
                    const expectedSoFar = Math.max(forecastToday - remaining, 0);
                    if (expectedSoFar >= 2.0 && actualToday >= 0.5) {
                      dailyRatio = clamp(actualToday / expectedSoFar, 0.35, 1.35);
                      factor = clamp(factor * 0.60 + dailyRatio * 0.40, 0.65, 1.10);
                    }
                  }

                  // Confidence now reflects both forecast signal strength and how closely
                  // real production is tracking it. 50% of forecast is deliberately LOW.
                  let accuracy = null;
                  if (liveRatio !== null) {
                    accuracy = clamp(1 - Math.abs(1 - liveRatio), 0, 1);
                  }
                  if (dailyRatio !== null) {
                    const dailyAccuracy = clamp(1 - Math.abs(1 - dailyRatio), 0, 1);
                    accuracy = accuracy === null ? dailyAccuracy : (accuracy * 0.65 + dailyAccuracy * 0.35);
                  }

                  let confidence = 'Low';
                  if (forecastNow !== null && forecastNow >= 700 && accuracy !== null && accuracy >= 0.80) {
                    confidence = 'High';
                  } else if (forecastNow !== null && forecastNow >= 250 && accuracy !== null && accuracy >= 0.62) {
                    confidence = 'Medium';
                  }

                  const correctedSolar = Number.isFinite(remaining) ? remaining * factor * 0.95 : null;
                  const conservativeSolar = Number.isFinite(remaining)
                    ? remaining * Math.max(0.60, factor - 0.15) * 0.95
                    : null;

                  const now = new Date();
                  const elapsed = Math.max(now.getHours() + now.getMinutes()/60, 1);
                  const avgSoFar = loadToday / elapsed;
                  const liveKw = load / 1000;
                  const blendedKw = clamp(avgSoFar * 0.65 + liveKw * 0.35, 0.15, 5);

                  const targetTimeRaw = states['sensor.ecco_config_charge_start_time']?.state;
                  const targetMatch = String(targetTimeRaw ?? '').match(/^(\d{1,2}):(\d{2})$/);
                  const targetHour = targetMatch ? Number(targetMatch[1]) : 0;
                  const targetMinute = targetMatch ? Number(targetMatch[2]) : 30;
                  const targetTime = `${String(targetHour).padStart(2,'0')}:${String(targetMinute).padStart(2,'0')}`;
                  const nextCheapStart = new Date(now);
                  nextCheapStart.setHours(targetHour,targetMinute,0,0);
                  if (nextCheapStart <= now) nextCheapStart.setDate(nextCheapStart.getDate()+1);
                  const hoursToCheap = Math.max((nextCheapStart-now)/3600000, 0);
                  const loadToCheap = blendedKw * hoursToCheap;

                  const likelySoc = correctedSolar !== null
                    ? clamp(soc + ((correctedSolar-loadToCheap)/capKwh)*100, 0, 100)
                    : null;
                  const conservativeSoc = conservativeSolar !== null
                    ? clamp(soc + ((conservativeSolar-loadToCheap)/capKwh)*100, 0, 100)
                    : null;

                  const currentRateSensors = sensors.filter(s =>
                    s.entity_id.includes('octopus_energy_electricity') &&
                    s.entity_id.includes('current_rate')
                  );
                  const imp = currentRateSensors.find(s => !isExport(s));
                  const exp = currentRateSensors.find(s => isExport(s));
                  const importP = num(imp) !== null ? num(imp)*100 : null;
                  const exportP = num(exp) !== null ? num(exp)*100 : null;

                  // Use ALL of today's rates for cheap/peak reference, not just rates still ahead.
                  const todayEvents = events.filter(s =>
                    s.entity_id.includes('octopus_energy_electricity') &&
                    s.entity_id.includes('current_day_rates') &&
                    !isExport(s)
                  );
                  let dayRates = [];
                  todayEvents.forEach(e => {
                    if (Array.isArray(e.attributes?.rates)) dayRates.push(...e.attributes.rates);
                  });
                  dayRates = dayRates.map(r => Number(r.value_inc_vat)*100).filter(Number.isFinite);

                  const dayCheapP = dayRates.length
                    ? Math.min(...dayRates)
                    : (imp?.attributes?.current_day_min_rate != null ? Number(imp.attributes.current_day_min_rate)*100 : null);
                  const dayPeakP = dayRates.length
                    ? Math.max(...dayRates)
                    : (imp?.attributes?.current_day_max_rate != null ? Number(imp.attributes.current_day_max_rate)*100 : importP);

                  const spread = importP !== null && exportP !== null ? importP-exportP : null;

                  let headline = 'Live monitoring';
                  let detail = `SOC ${soc.toFixed(0)}% • adaptive solar factor ${(factor*100).toFixed(0)}% • ${confidence.toLowerCase()} confidence`;
                  let colour = '#7ab8ff';

                  if (likelySoc !== null && conservativeSoc !== null) {
                    if (conservativeSoc >= 25) {
                      headline = `No additional grid charge indicated • ${confidence.toLowerCase()} confidence`;
                      detail = `Likely SOC at ${targetTime} is ${likelySoc.toFixed(0)}% and conservative SOC is ${conservativeSoc.toFixed(0)}%.`;
                      colour = '#55e58e';
                    } else if (likelySoc >= 20) {
                      headline = `Keep watch on reserve • ${confidence.toLowerCase()} confidence`;
                      detail = `Likely SOC at ${targetTime} is ${likelySoc.toFixed(0)}%, but conservative modelling falls to ${conservativeSoc.toFixed(0)}%.`;
                      colour = '#ffbd3d';
                    } else {
                      headline = `Cheap-rate support may be worthwhile • ${confidence.toLowerCase()} confidence`;
                      detail = `Likely SOC at ${targetTime} is only ${likelySoc.toFixed(0)}% with ${conservativeSoc.toFixed(0)}% on the conservative model.`;
                      colour = '#ff6376';
                    }
                  }

                  if (liveRatio !== null) {
                    detail += ` Live PV is ${Math.round(liveRatio*100)}% of Forecast.Solar right now.`;
""")
DASHBOARD_16_NEW = _blk(r"""
                    const pct = Math.round((actualNow / forecastNow) * 100);
                    const diff = actualNow - forecastNow;
                    nowCompare = ` • actual now <b style="color:${diff >= 0 ? '#55e58e' : '#ffbd3d'}">${pct}%</b> of forecast`;
                  }

                  return `<div style="padding:10px 12px;border-radius:12px;background:rgba(255,189,61,0.055);
                    border:1px solid rgba(255,189,61,0.16);color:rgba(255,255,255,0.72);font-size:12px;line-height:1.55;">
                    <b style="color:#ffbd3d;">Solar model</b>
                    ${today !== null ? ` • <b>${today.toFixed(1)} kWh</b> today` : ''}
                    ${remaining !== null ? ` • <b>${remaining.toFixed(1)} kWh</b> remaining` : ''}
                    ${forecastNow !== null ? ` • <b>${Math.round(forecastNow)} W</b> forecast now` : ''}
                    ${nowCompare}
                    ${tomorrow !== null ? ` • next day <b>${tomorrow.toFixed(1)} kWh</b>` : ''}
                  </div>`;
                ]]]
              recommendation: >
                [[[
                  const n = (id) => Number(states[id]?.state ?? 0);
                  const clamp = (v,a,b) => Math.max(a,Math.min(b,v));
                  const pv = n('sensor.ecco_clock_dongle_ecco_pv_power');
                  const load = n('sensor.ecco_clock_dongle_ecco_load_power');
                  const soc = n('sensor.ecco_clock_dongle_ecco_battery_soc');
                  const loadToday = n('sensor.ecco_clock_dongle_ecco_day_load_energy');
                  const capAh = n('sensor.ecco_clock_dongle_ecco_battery_capacity_ah') || 620;
                  const capKwh = capAh * 51.2 / 1000;

                  const sensors = Object.values(states).filter(s => s.entity_id.startsWith('sensor.'));
                  const events = Object.values(states).filter(s => s.entity_id.startsWith('event.'));
                  const friendly = (s) => String(s?.attributes?.friendly_name ?? s?.entity_id ?? '').toLowerCase();
                  const find = (need, exclude=[]) => sensors.find(s => {
                    const x = friendly(s);
                    return need.every(v => x.includes(v)) && !exclude.some(v => x.includes(v));
                  });
                  const num = (s) => {
                    const v = Number(s?.state);
                    return Number.isFinite(v) ? v : null;
                  };
                  const isExport = (s) => s.entity_id.includes('export') || friendly(s).includes('export');

                  const forecastToday = num(states['sensor.ecco_solar_forecast_today']);
                  const remaining = num(states['sensor.ecco_solar_forecast_remaining']);
                  const forecastNow = num(states['sensor.ecco_solar_forecast_power_now']);
                  const actualToday = n('sensor.ecco_clock_dongle_ecco_day_pv_energy');

                  let liveRatio = null;
                  if (forecastNow !== null && forecastNow >= 250) {
                    liveRatio = clamp(pv / forecastNow, 0.15, 1.50);
                  }

                  let factor = liveRatio !== null
                    ? clamp(0.65 + 0.35 * liveRatio, 0.70, 1.10)
                    : 1.0;

                  let dailyRatio = null;
                  if (forecastToday !== null && remaining !== null) {
                    const expectedSoFar = Math.max(forecastToday - remaining, 0);
                    if (expectedSoFar >= 2.0 && actualToday >= 0.5) {
                      dailyRatio = clamp(actualToday / expectedSoFar, 0.35, 1.35);
                      factor = clamp(factor * 0.60 + dailyRatio * 0.40, 0.65, 1.10);
                    }
                  }

                  // Confidence now reflects both forecast signal strength and how closely
                  // real production is tracking it. 50% of forecast is deliberately LOW.
                  let accuracy = null;
                  if (liveRatio !== null) {
                    accuracy = clamp(1 - Math.abs(1 - liveRatio), 0, 1);
                  }
                  if (dailyRatio !== null) {
                    const dailyAccuracy = clamp(1 - Math.abs(1 - dailyRatio), 0, 1);
                    accuracy = accuracy === null ? dailyAccuracy : (accuracy * 0.65 + dailyAccuracy * 0.35);
                  }

                  let confidence = 'Low';
                  if (forecastNow !== null && forecastNow >= 700 && accuracy !== null && accuracy >= 0.80) {
                    confidence = 'High';
                  } else if (forecastNow !== null && forecastNow >= 250 && accuracy !== null && accuracy >= 0.62) {
                    confidence = 'Medium';
                  }

                  // V2.1 (ovw2): never show a projection from a battery reading that is not a number.
                  const socRaw = states['sensor.ecco_clock_dongle_ecco_battery_soc']?.state;
                  if (socRaw === undefined || ['unknown','unavailable','none',''].includes(String(socRaw).toLowerCase()) || !Number.isFinite(Number(socRaw))) {
                    return `<div style="padding-top:2px;">
                      <div style="font-size:15px;font-weight:800;color:#aab4c3;">Battery data unavailable</div>
                      <div style="font-size:12px;line-height:1.5;color:rgba(255,255,255,0.64);margin-top:3px;">No projection is shown until the battery SOC reports again.</div>
                    </div>`;
                  }
                  const correctedSolar = Number.isFinite(remaining) ? remaining * factor * 0.95 : null;
                  const conservativeSolar = Number.isFinite(remaining)
                    ? remaining * Math.max(0.60, factor - 0.15) * 0.95
                    : null;

                  const now = new Date();
                  const elapsed = Math.max(now.getHours() + now.getMinutes()/60, 1);
                  const avgSoFar = loadToday / elapsed;
                  const liveKw = load / 1000;
                  const blendedKw = clamp(avgSoFar * 0.65 + liveKw * 0.35, 0.15, 5);

                  const targetTimeRaw = states['sensor.ecco_config_charge_start_time']?.state;
                  const targetMatch = String(targetTimeRaw ?? '').match(/^(\d{1,2}):(\d{2})$/);
                  const targetHour = targetMatch ? Number(targetMatch[1]) : 0;
                  const targetMinute = targetMatch ? Number(targetMatch[2]) : 30;
                  const targetTime = `${String(targetHour).padStart(2,'0')}:${String(targetMinute).padStart(2,'0')}`;
                  const nextCheapStart = new Date(now);
                  nextCheapStart.setHours(targetHour,targetMinute,0,0);
                  if (nextCheapStart <= now) nextCheapStart.setDate(nextCheapStart.getDate()+1);
                  const hoursToCheap = Math.max((nextCheapStart-now)/3600000, 0);
                  const loadToCheap = blendedKw * hoursToCheap;
                  // V2.1 (ovw2): the solar forecast is for the rest of the CURRENT calendar day. Only the part that can still arrive BEFORE
                  // the target time may lift the SOC AT the target. The credit is therefore the share of today's remaining daylight that ends
                  // before the target: 0 before sunrise or once today's daylight is over, 1 when the target is after sunset, and an approximate
                  // time-proportional share when the target falls inside the daylight window. Without sun times no projection is made.
                  const sunEntity = states['sun.sun'];
                  const solarWindow = (() => {
                    const set = sunEntity?.attributes?.next_setting ? new Date(sunEntity.attributes.next_setting) : null;
                    const rise = sunEntity?.attributes?.next_rising ? new Date(sunEntity.attributes.next_rising) : null;
                    if (!set || Number.isNaN(set.getTime())) return { known: false, share: null, partial: false };
                    let from = null;
                    if (sunEntity.state === 'above_horizon') from = now;
                    else if (rise && !Number.isNaN(rise.getTime()) && rise.toDateString() === now.toDateString()) from = rise;
                    if (from === null) return { known: true, share: 0, partial: false };
                    if (nextCheapStart >= set) return { known: true, share: 1, partial: false };
                    if (nextCheapStart <= from) return { known: true, share: 0, partial: false };
                    return { known: true, share: (nextCheapStart - from) / (set - from), partial: true };
                  })();
                  const solarShare = solarWindow.share;
                  if (solarWindow.partial) confidence = 'Low';
                  const minsToTarget = Math.round(hoursToCheap * 60);
                  const untilText = minsToTarget < 90 ? `in ${minsToTarget} min` : `in ${Math.round(hoursToCheap)} h`;
                  const targetLabel = `${targetTime} ${nextCheapStart.toDateString() === now.toDateString() ? 'today' : 'tomorrow'} (${untilText})`;

                  const likelySoc = correctedSolar !== null && solarShare !== null
                    ? clamp(soc + ((correctedSolar*solarShare-loadToCheap)/capKwh)*100, 0, 100)
                    : null;
                  const conservativeSoc = conservativeSolar !== null && solarShare !== null
                    ? clamp(soc + ((conservativeSolar*solarShare-loadToCheap)/capKwh)*100, 0, 100)
                    : null;

                  const currentRateSensors = sensors.filter(s =>
                    s.entity_id.includes('octopus_energy_electricity') &&
                    s.entity_id.includes('current_rate')
                  );
                  const imp = currentRateSensors.find(s => !isExport(s));
                  const exp = currentRateSensors.find(s => isExport(s));
                  const importP = num(imp) !== null ? num(imp)*100 : null;
                  const exportP = num(exp) !== null ? num(exp)*100 : null;

                  // Use ALL of today's rates for cheap/peak reference, not just rates still ahead.
                  const todayEvents = events.filter(s =>
                    s.entity_id.includes('octopus_energy_electricity') &&
                    s.entity_id.includes('current_day_rates') &&
                    !isExport(s)
                  );
                  let dayRates = [];
                  todayEvents.forEach(e => {
                    if (Array.isArray(e.attributes?.rates)) dayRates.push(...e.attributes.rates);
                  });
                  dayRates = dayRates.map(r => Number(r.value_inc_vat)*100).filter(Number.isFinite);

                  const dayCheapP = dayRates.length
                    ? Math.min(...dayRates)
                    : (imp?.attributes?.current_day_min_rate != null ? Number(imp.attributes.current_day_min_rate)*100 : null);
                  const dayPeakP = dayRates.length
                    ? Math.max(...dayRates)
                    : (imp?.attributes?.current_day_max_rate != null ? Number(imp.attributes.current_day_max_rate)*100 : importP);

                  const spread = importP !== null && exportP !== null ? importP-exportP : null;

                  let headline = 'Live monitoring';
                  let detail = `SOC ${soc.toFixed(0)}% • adaptive solar factor ${(factor*100).toFixed(0)}% • ${confidence.toLowerCase()} confidence`;
                  let colour = '#7ab8ff';

                  if (likelySoc !== null && conservativeSoc !== null) {
                    if (conservativeSoc >= 25) {
                      headline = `No additional grid charge indicated • ${confidence.toLowerCase()} confidence`;
                      detail = `Likely SOC at ${targetLabel} is ${likelySoc.toFixed(0)}% and conservative SOC is ${conservativeSoc.toFixed(0)}%.`;
                      colour = '#55e58e';
                    } else if (likelySoc >= 20) {
                      headline = `Keep watch on reserve • ${confidence.toLowerCase()} confidence`;
                      detail = `Likely SOC at ${targetLabel} is ${likelySoc.toFixed(0)}%, but conservative modelling falls to ${conservativeSoc.toFixed(0)}%.`;
                      colour = '#ffbd3d';
                    } else {
                      headline = `Cheap-rate support may be worthwhile • ${confidence.toLowerCase()} confidence`;
                      detail = `Likely SOC at ${targetLabel} is only ${likelySoc.toFixed(0)}% with ${conservativeSoc.toFixed(0)}% on the conservative model.`;
                      colour = '#ff6376';
                    }
                  }

                  if (likelySoc !== null && conservativeSoc !== null) {
                    if (solarShare === 0 && Number.isFinite(remaining) && remaining > 0.05) {
                      detail += ' No solar can arrive before then.';
                    } else if (solarWindow.partial) {
                      detail += ` About ${Math.round(solarShare * 100)}% of the remaining solar arrives before then (approximate).`;
                    }
                  } else if (!solarWindow.known) {
                    headline = 'Projection unavailable';
                    detail = `Sun times are unavailable, so ECCO cannot tell how much of the solar forecast arrives before ${targetLabel}. SOC is ${soc.toFixed(0)}%.`;
                    colour = '#aab4c3';
                  }

                  // V2.1: say which average house load the projection assumes (the model is unchanged: 65% of today's average load plus
                  // 35% of the load right now), so a short spike of load right now is visible as the reason for a low figure.
                  if (likelySoc !== null && conservativeSoc !== null) {
                    detail += ` Assumes about ${blendedKw.toFixed(1)} kW average house load until then (65% today's average, 35% the load right now).`;
                  }
                  if (liveRatio !== null) {
                    detail += ` Live PV is ${Math.round(liveRatio*100)}% of Forecast.Solar right now.`;
""")
DASHBOARD_17_OLD = _blk(r"""
                  const scoredActual = read('sensor.ecco_battery_outlook_last_actual_soc');
                  const scoredError = read('sensor.ecco_battery_outlook_last_error');
                  const scoreMae7d = read('sensor.ecco_battery_outlook_7d_mae');
                  const scoreBias7d = read('sensor.ecco_battery_outlook_7d_bias');

                  if (predictedSoc === null || loadRemaining === null) {
""")
DASHBOARD_17_NEW = _blk(r"""
                  const scoredActual = read('sensor.ecco_battery_outlook_last_actual_soc');
                  const scoredError = read('sensor.ecco_battery_outlook_last_error');
                  const scoreMae7d = read('sensor.ecco_battery_outlook_7_day_mae');
                  const scoreBias7d = read('sensor.ecco_battery_outlook_7_day_bias');

                  if (predictedSoc === null || loadRemaining === null) {
""")
DASHBOARD_18_OLD = _blk(r"""
          # ---- OCTOPUS TARIFF INTELLIGENCE ----
          - type: custom:button-card
            section_mode: true
            name: Smart Charge Strategy
            icon: mdi:battery-charging-medium
            show_name: true
            show_icon: true
            show_state: false
            tap_action:
              action: none
            custom_fields:
              body: >
                [[[
                  const n=(id)=>Number(states[id]?.state??0);
                  const clamp=(v,a,b)=>Math.max(a,Math.min(b,v));
                  const sensors=Object.values(states).filter(s=>s.entity_id.startsWith('sensor.'));
                  const events=Object.values(states).filter(s=>s.entity_id.startsWith('event.'));
                  const friendly=(s)=>String(s?.attributes?.friendly_name??s?.entity_id??'').toLowerCase();
                  const find=(need,exclude=[])=>sensors.find(s=>{
                    const x=friendly(s);return need.every(v=>x.includes(v))&&!exclude.some(v=>x.includes(v));
                  });
                  const num=(s)=>{const v=Number(s?.state);return Number.isFinite(v)?v:null;};
                  const isExport=(s)=>s.entity_id.includes('export')||friendly(s).includes('export');

                  const soc=n('sensor.ecco_clock_dongle_ecco_battery_soc');
                  const capAh=n('sensor.ecco_clock_dongle_ecco_battery_capacity_ah')||620;
                  const capKwh=capAh*51.2/1000;
                  const loadToday=n('sensor.ecco_clock_dongle_ecco_day_load_energy');
                  const loadW=n('sensor.ecco_clock_dongle_ecco_load_power');
                  const pvW=n('sensor.ecco_clock_dongle_ecco_pv_power');
                  const actualPV=n('sensor.ecco_clock_dongle_ecco_day_pv_energy');

                  const forecastToday=num(states['sensor.ecco_solar_forecast_today']);
                  const remaining=num(states['sensor.ecco_solar_forecast_remaining']);
                  const forecastNow=num(states['sensor.ecco_solar_forecast_power_now']);
                  const tomorrow=num(states['sensor.ecco_solar_forecast_tomorrow']);

                  let liveRatio=null;
                  if(forecastNow!==null&&forecastNow>=250)liveRatio=clamp(pvW/forecastNow,.15,1.5);
                  let factor=liveRatio!==null?clamp(.65+.35*liveRatio,.70,1.10):1;
                  const expectedSoFar=forecastToday!==null&&remaining!==null?Math.max(forecastToday-remaining,0):0;
                  if(expectedSoFar>=2&&actualPV>=.5){
                    const dailyRatio=clamp(actualPV/expectedSoFar,.35,1.35);
                    factor=clamp(factor*.60+dailyRatio*.40,.65,1.10);
                  }

                  const now=new Date();
                  const elapsed=Math.max(now.getHours()+now.getMinutes()/60,1);
                  const avgKw=loadToday/elapsed;
                  const liveKw=loadW/1000;
                  const runKw=clamp(avgKw*.65+liveKw*.35,.15,5);
                  const projectedDaily=clamp(runKw*24,6,60);

                  const adjustedTomorrow=tomorrow!==null?tomorrow*factor*.95:null;
                  const morningBridge=runKw*4.5;
                  const reserveKwh=capKwh*.10;
                  const dailyDeficit=adjustedTomorrow!==null?Math.max(projectedDaily-adjustedTomorrow,0):0;
                  const requiredEnergy=clamp(morningBridge+reserveKwh+dailyDeficit,capKwh*.20,capKwh);
                  const minimumReserveTarget=clamp(requiredEnergy/capKwh*100,20,100);

                  const configuredTarget=Number(states['sensor.ecco_clock_dongle_ecco_timezone1_soc']?.state??100);

                  const rateSensors=sensors.filter(s=>
                    s.entity_id.includes('octopus_energy_electricity')&&
                    s.entity_id.includes('current_rate')
                  );
                  const imp=rateSensors.find(s=>!isExport(s));

                  const parseEvent=(needle)=>{
                    const ev=events.find(s=>
                      s.entity_id.includes('octopus_energy_electricity')&&
                      s.entity_id.includes(needle)&&!isExport(s)
                    );
                    const rs=Array.isArray(ev?.attributes?.rates)?ev.attributes.rates:[];
                    return rs.map(r=>({
                      start:new Date(r.start),end:new Date(r.end),
                      p:Number(r.value_inc_vat)*100
                    })).filter(r=>Number.isFinite(r.p)&&!isNaN(r.start)&&!isNaN(r.end))
                      .sort((a,b)=>a.start-b.start);
                  };

                  const todayRates=parseEvent('current_day_rates');
                  const nextRates=parseEvent('next_day_rates');
                  const nextRateCoverageHours=nextRates.reduce((sum,r)=>sum+Math.max((r.end-r.start)/3600000,0),0);
                  const nextRatesReady=nextRates.length>=6 && nextRateCoverageHours>=3;
                  const todayMin=todayRates.length?Math.min(...todayRates.map(r=>r.p)):
                    (imp?.attributes?.current_day_min_rate!=null?Number(imp.attributes.current_day_min_rate)*100:null);
                  const todayMax=todayRates.length?Math.max(...todayRates.map(r=>r.p)):
                    (imp?.attributes?.current_day_max_rate!=null?Number(imp.attributes.current_day_max_rate)*100:null);

                  const eps=.35;
                  const windowFor=(rates,target,after)=>{
                    if(!rates.length||target===null)return null;
                    const hits=rates.filter(r=>r.end>after&&Math.abs(r.p-target)<=eps);
                    if(!hits.length)return null;
                    const first=hits[0];
                    let end=first.end;
                    for(const r of hits.slice(1)){
                      if(Math.abs(r.start-end)<60000)end=r.end;else break;
                    }
                    return {start:first.start,end,p:target};
                  };

                  let nextCheap= todayMin!==null ? windowFor(todayRates,todayMin,now) : null;
                  if(!nextCheap&&nextRatesReady){
                    const nm=Math.min(...nextRates.map(r=>r.p));
                    nextCheap=windowFor(nextRates,nm,now);
                  }

                  // Battery level expected at the live configured charge-slot start.
                  const targetTimeRaw=states['sensor.ecco_config_charge_start_time']?.state;
                  const targetMatch=String(targetTimeRaw??'').match(/^(\d{1,2}):(\d{2})$/);
                  const targetHour=targetMatch?Number(targetMatch[1]):0;
                  const targetMinute=targetMatch?Number(targetMatch[2]):30;
                  const targetTime=`${String(targetHour).padStart(2,'0')}:${String(targetMinute).padStart(2,'0')}`;
                  const cheapStart=new Date(now);
                  cheapStart.setHours(targetHour,targetMinute,0,0);
                  if(cheapStart<=now)cheapStart.setDate(cheapStart.getDate()+1);
                  const hCheap=Math.max((cheapStart-now)/3600000,0);

                  const likelySolar=remaining!==null?remaining*factor*.95:0;
                  const predictedAt0035=remaining!==null
                    ? clamp(soc+((likelySolar-runKw*hCheap)/capKwh)*100,0,100)
                    : soc;

                  // This is the extra energy needed for reserve/security only.
                  const batteryNeeded=Math.max(0,(minimumReserveTarget-predictedAt0035)/100*capKwh);
                  const gridNeeded=batteryNeeded/.94;

                  const nextCheapRate=nextCheap?.p ?? null;
                  const costRate=nextCheapRate ?? todayMin;
                  const costIsReference=nextCheapRate===null&&todayMin!==null;
                  const chargeCost=costRate!==null?gridNeeded*(costRate/100):null;
                  const avoidedValue=todayMax!==null?batteryNeeded*(todayMax/100):null;
                  const saving=chargeCost!==null&&avoidedValue!==null?avoidedValue-chargeCost:null;

                  const surplusPct=predictedAt0035-minimumReserveTarget;

                  let headline='Energy-reserve model says no top-up is needed';
                  let colour='#55e58e';
                  if(gridNeeded>0.2){
                    headline='Energy-reserve model recommends a cheap-rate top-up';
                    colour='#ffbd3d';
                  }else if(configuredTarget>minimumReserveTarget+15){
                    headline='Configured target is well above the minimum reserve needed';
                    colour='#7ab8ff';
                  }

                  return `<div>
                    <div style="font-size:16px;font-weight:800;color:${colour};">${headline}</div>

                    <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:9px;margin-top:12px;">
                      <div style="text-align:center;padding:9px;border-radius:10px;background:rgba(255,255,255,.035);border:1px solid rgba(255,255,255,.06);">
                        <div style="font-size:10px;color:rgba(255,255,255,.48);">Configured TOU target</div>
                        <div style="font-size:22px;font-weight:800;color:#b8adff;">${Number.isFinite(configuredTarget)?configuredTarget.toFixed(0):'--'}%</div>
                      </div>
                      <div style="text-align:center;padding:9px;border-radius:10px;background:rgba(255,255,255,.035);border:1px solid rgba(255,255,255,.06);">
                        <div style="font-size:10px;color:rgba(255,255,255,.48);">Minimum reserve needed</div>
                        <div style="font-size:22px;font-weight:800;color:#55e58e;">${minimumReserveTarget.toFixed(0)}%</div>
                      </div>
                      <div style="text-align:center;padding:9px;border-radius:10px;background:rgba(255,255,255,.035);border:1px solid rgba(255,255,255,.06);">
                        <div style="font-size:10px;color:rgba(255,255,255,.48);">Expected at ${targetTime}</div>
                        <div style="font-size:22px;font-weight:800;color:#ffbd3d;">${predictedAt0035.toFixed(0)}%</div>
                      </div>
                    </div>

                    <div style="margin-top:11px;font-size:11px;line-height:1.55;color:rgba(255,255,255,.60);">
                      Reserve margin at ${targetTime} <b style="color:${surplusPct>=0?'#55e58e':'#ff6376'}">${surplusPct>=0?'+':''}${surplusPct.toFixed(0)} points</b>
                      • next-day load model <b style="color:#fff">${projectedDaily.toFixed(1)} kWh</b>
                      ${adjustedTomorrow!==null?` • adaptive solar <b style="color:#ffbd3d">${adjustedTomorrow.toFixed(1)} kWh</b>`:''}
                      • reserve-only charge need <b style="color:#fff">${gridNeeded.toFixed(1)} kWh</b>
                      ${chargeCost!==null?` • estimated cost <b style="color:#fff">£${chargeCost.toFixed(2)}</b>${costIsReference?' using today’s cheap rate as a reference':''}`:''}
                      ${saving!==null&&saving>0&&gridNeeded>0.1?` • avoided peak-import value <b style="color:#55e58e">£${saving.toFixed(2)}</b>`:''}.
                    </div>

                    <div style="margin-top:9px;font-size:10px;line-height:1.45;color:rgba(255,255,255,.42);">
                      The minimum reserve target is an energy-security floor, not a proposed TOU setting.
                      ${nextCheap?` Next published cheap window: ${nextCheap.start.toLocaleTimeString([],{hour:'2-digit',minute:'2-digit'})}–${nextCheap.end.toLocaleTimeString([],{hour:'2-digit',minute:'2-digit'})} at ${nextCheap.p.toFixed(2)}p/kWh.`:' Next-day cheap rates are not published yet.'}
                      Export arbitrage and battery degradation are still excluded.
""")
DASHBOARD_18_NEW = _blk(r"""
          # ---- OCTOPUS TARIFF INTELLIGENCE ----
          - type: custom:button-card
            section_mode: true
            name: Smart Charge Strategy
            icon: mdi:battery-charging-medium
            show_name: true
            show_icon: true
            show_state: false
            tap_action:
              action: none
            custom_fields:
              body: >
                [[[
                  const n=(id)=>Number(states[id]?.state??0);
                  const clamp=(v,a,b)=>Math.max(a,Math.min(b,v));
                  const sensors=Object.values(states).filter(s=>s.entity_id.startsWith('sensor.'));
                  const events=Object.values(states).filter(s=>s.entity_id.startsWith('event.'));
                  const friendly=(s)=>String(s?.attributes?.friendly_name??s?.entity_id??'').toLowerCase();
                  const find=(need,exclude=[])=>sensors.find(s=>{
                    const x=friendly(s);return need.every(v=>x.includes(v))&&!exclude.some(v=>x.includes(v));
                  });
                  const num=(s)=>{const v=Number(s?.state);return Number.isFinite(v)?v:null;};
                  const isExport=(s)=>s.entity_id.includes('export')||friendly(s).includes('export');

                  const soc=n('sensor.ecco_clock_dongle_ecco_battery_soc');
                  const capAh=n('sensor.ecco_clock_dongle_ecco_battery_capacity_ah')||620;
                  const capKwh=capAh*51.2/1000;
                  const loadToday=n('sensor.ecco_clock_dongle_ecco_day_load_energy');
                  const loadW=n('sensor.ecco_clock_dongle_ecco_load_power');
                  const pvW=n('sensor.ecco_clock_dongle_ecco_pv_power');
                  const actualPV=n('sensor.ecco_clock_dongle_ecco_day_pv_energy');

                  const forecastToday=num(states['sensor.ecco_solar_forecast_today']);
                  const remaining=num(states['sensor.ecco_solar_forecast_remaining']);
                  const forecastNow=num(states['sensor.ecco_solar_forecast_power_now']);
                  const tomorrow=num(states['sensor.ecco_solar_forecast_tomorrow']);

                  let liveRatio=null;
                  if(forecastNow!==null&&forecastNow>=250)liveRatio=clamp(pvW/forecastNow,.15,1.5);
                  let factor=liveRatio!==null?clamp(.65+.35*liveRatio,.70,1.10):1;
                  const expectedSoFar=forecastToday!==null&&remaining!==null?Math.max(forecastToday-remaining,0):0;
                  if(expectedSoFar>=2&&actualPV>=.5){
                    const dailyRatio=clamp(actualPV/expectedSoFar,.35,1.35);
                    factor=clamp(factor*.60+dailyRatio*.40,.65,1.10);
                  }

                  const now=new Date();
                  const elapsed=Math.max(now.getHours()+now.getMinutes()/60,1);
                  const avgKw=loadToday/elapsed;
                  const liveKw=loadW/1000;
                  const runKw=clamp(avgKw*.65+liveKw*.35,.15,5);
                  const projectedDaily=clamp(runKw*24,6,60);

                  const adjustedTomorrow=tomorrow!==null?tomorrow*factor*.95:null;
                  const morningBridge=runKw*4.5;
                  const reserveKwh=capKwh*.10;
                  const dailyDeficit=adjustedTomorrow!==null?Math.max(projectedDaily-adjustedTomorrow,0):0;
                  const requiredEnergy=clamp(morningBridge+reserveKwh+dailyDeficit,capKwh*.20,capKwh);
                  const minimumReserveTarget=clamp(requiredEnergy/capKwh*100,20,100);

                  const configuredTarget=Number(states['sensor.ecco_clock_dongle_ecco_timezone1_soc']?.state??100);

                  const rateSensors=sensors.filter(s=>
                    s.entity_id.includes('octopus_energy_electricity')&&
                    s.entity_id.includes('current_rate')
                  );
                  const imp=rateSensors.find(s=>!isExport(s));

                  const parseEvent=(needle)=>{
                    const ev=events.find(s=>
                      s.entity_id.includes('octopus_energy_electricity')&&
                      s.entity_id.includes(needle)&&!isExport(s)
                    );
                    const rs=Array.isArray(ev?.attributes?.rates)?ev.attributes.rates:[];
                    return rs.map(r=>({
                      start:new Date(r.start),end:new Date(r.end),
                      p:Number(r.value_inc_vat)*100
                    })).filter(r=>Number.isFinite(r.p)&&!isNaN(r.start)&&!isNaN(r.end))
                      .sort((a,b)=>a.start-b.start);
                  };

                  const todayRates=parseEvent('current_day_rates');
                  const nextRates=parseEvent('next_day_rates');
                  const nextRateCoverageHours=nextRates.reduce((sum,r)=>sum+Math.max((r.end-r.start)/3600000,0),0);
                  const nextRatesReady=nextRates.length>=6 && nextRateCoverageHours>=3;
                  const todayMin=todayRates.length?Math.min(...todayRates.map(r=>r.p)):
                    (imp?.attributes?.current_day_min_rate!=null?Number(imp.attributes.current_day_min_rate)*100:null);
                  const todayMax=todayRates.length?Math.max(...todayRates.map(r=>r.p)):
                    (imp?.attributes?.current_day_max_rate!=null?Number(imp.attributes.current_day_max_rate)*100:null);

                  const eps=.35;
                  const windowFor=(rates,target,after)=>{
                    if(!rates.length||target===null)return null;
                    const hits=rates.filter(r=>r.end>after&&Math.abs(r.p-target)<=eps);
                    if(!hits.length)return null;
                    const first=hits[0];
                    let end=first.end;
                    for(const r of hits.slice(1)){
                      if(Math.abs(r.start-end)<60000)end=r.end;else break;
                    }
                    return {start:first.start,end,p:target};
                  };

                  let nextCheap= todayMin!==null ? windowFor(todayRates,todayMin,now) : null;
                  if(!nextCheap&&nextRatesReady){
                    const nm=Math.min(...nextRates.map(r=>r.p));
                    nextCheap=windowFor(nextRates,nm,now);
                  }

                  // Battery level expected at the live configured charge-slot start.
                  const targetTimeRaw=states['sensor.ecco_config_charge_start_time']?.state;
                  const targetMatch=String(targetTimeRaw??'').match(/^(\d{1,2}):(\d{2})$/);
                  const targetHour=targetMatch?Number(targetMatch[1]):0;
                  const targetMinute=targetMatch?Number(targetMatch[2]):30;
                  const targetTime=`${String(targetHour).padStart(2,'0')}:${String(targetMinute).padStart(2,'0')}`;
                  const cheapStart=new Date(now);
                  cheapStart.setHours(targetHour,targetMinute,0,0);
                  if(cheapStart<=now)cheapStart.setDate(cheapStart.getDate()+1);
                  const hCheap=Math.max((cheapStart-now)/3600000,0);

                  // V2.1 (ovw2): never show a reserve projection or top-up advice from a battery reading that is not a number.
                  const socRaw=states['sensor.ecco_clock_dongle_ecco_battery_soc']?.state;
                  if(socRaw===undefined||['unknown','unavailable','none',''].includes(String(socRaw).toLowerCase())||!Number.isFinite(Number(socRaw))){
                    return `<div style="font-size:16px;font-weight:800;color:#aab4c3;">Battery data unavailable</div><div style="margin-top:6px;font-size:11px;line-height:1.5;color:rgba(255,255,255,.55);">No reserve projection or top-up advice is shown until the battery SOC reports again.</div>`;
                  }

                  // V2.1 (ovw2): the solar forecast is for the rest of the CURRENT calendar day; only the share that can arrive BEFORE the
                  // target may lift the SOC at the target (same rule as the ECCO Today card). Unknown sun times credit no solar at all.
                  const sunEntity=states['sun.sun'];
                  const solarShare=(()=>{
                    const set=sunEntity?.attributes?.next_setting?new Date(sunEntity.attributes.next_setting):null;
                    const rise=sunEntity?.attributes?.next_rising?new Date(sunEntity.attributes.next_rising):null;
                    if(!set||Number.isNaN(set.getTime()))return 0;
                    let from=null;
                    if(sunEntity.state==='above_horizon')from=now;
                    else if(rise&&!Number.isNaN(rise.getTime())&&rise.toDateString()===now.toDateString())from=rise;
                    if(from===null)return 0;
                    if(cheapStart>=set)return 1;
                    if(cheapStart<=from)return 0;
                    return (cheapStart-from)/(set-from);
                  })();
                  const targetDay=cheapStart.toDateString()===now.toDateString()?'today':'tomorrow';
                  const likelySolar=remaining!==null?remaining*factor*.95:0;
                  const predictedAt0035=remaining!==null
                    ? clamp(soc+((likelySolar*solarShare-runKw*hCheap)/capKwh)*100,0,100)
                    : soc;

                  // This is the extra energy needed for reserve/security only.
                  const batteryNeeded=Math.max(0,(minimumReserveTarget-predictedAt0035)/100*capKwh);
                  const gridNeeded=batteryNeeded/.94;

                  const nextCheapRate=nextCheap?.p ?? null;
                  const costRate=nextCheapRate ?? todayMin;
                  const costIsReference=nextCheapRate===null&&todayMin!==null;
                  const chargeCost=costRate!==null?gridNeeded*(costRate/100):null;
                  const avoidedValue=todayMax!==null?batteryNeeded*(todayMax/100):null;
                  const saving=chargeCost!==null&&avoidedValue!==null?avoidedValue-chargeCost:null;

                  const surplusPct=predictedAt0035-minimumReserveTarget;

                  let headline='Energy-reserve model says no top-up is needed';
                  let colour='#55e58e';
                  if(gridNeeded>0.2){
                    headline='Energy-reserve model recommends a cheap-rate top-up';
                    colour='#ffbd3d';
                  }else if(configuredTarget>minimumReserveTarget+15){
                    headline='Configured target is well above the modelled reserve need';
                    colour='#7ab8ff';
                  }

                  return `<div>
                    <div style="font-size:16px;font-weight:800;color:${colour};">${headline}</div>

                    <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:9px;margin-top:12px;">
                      <div style="text-align:center;padding:9px;border-radius:10px;background:rgba(255,255,255,.035);border:1px solid rgba(255,255,255,.06);">
                        <div style="font-size:10px;color:rgba(255,255,255,.48);">Configured TOU target</div>
                        <div style="font-size:22px;font-weight:800;color:#b8adff;">${Number.isFinite(configuredTarget)?configuredTarget.toFixed(0):'--'}%</div>
                      </div>
                      <div style="text-align:center;padding:9px;border-radius:10px;background:rgba(255,255,255,.035);border:1px solid rgba(255,255,255,.06);">
                        <div style="font-size:10px;color:rgba(255,255,255,.48);">Modelled reserve need</div>
                        <div style="font-size:22px;font-weight:800;color:#55e58e;">${minimumReserveTarget.toFixed(0)}%</div>
                      </div>
                      <div style="text-align:center;padding:9px;border-radius:10px;background:rgba(255,255,255,.035);border:1px solid rgba(255,255,255,.06);">
                        <div style="font-size:10px;color:rgba(255,255,255,.48);">Expected at ${targetTime} ${targetDay}</div>
                        <div style="font-size:22px;font-weight:800;color:#ffbd3d;">${predictedAt0035.toFixed(0)}%</div>
                      </div>
                    </div>

                    <div style="margin-top:11px;font-size:11px;line-height:1.55;color:rgba(255,255,255,.60);">
                      Reserve margin at ${targetTime} <b style="color:${surplusPct>=0?'#55e58e':'#ff6376'}">${surplusPct>=0?'+':''}${surplusPct.toFixed(0)} points</b>
                      • next-day load model <b style="color:#fff">${projectedDaily.toFixed(1)} kWh</b>
                      ${adjustedTomorrow!==null?` • adaptive solar <b style="color:#ffbd3d">${adjustedTomorrow.toFixed(1)} kWh</b>`:''}
                      • reserve-only charge need <b style="color:#fff">${gridNeeded.toFixed(1)} kWh</b>
                      ${chargeCost!==null?` • estimated cost <b style="color:#fff">£${chargeCost.toFixed(2)}</b>${costIsReference?' using today’s cheap rate as a reference':''}`:''}
                      ${saving!==null&&saving>0&&gridNeeded>0.1?` • avoided peak-import value <b style="color:#55e58e">£${saving.toFixed(2)}</b>`:''}.
                    </div>

                    <div style="margin-top:9px;font-size:10px;line-height:1.45;color:rgba(255,255,255,.42);">
                      The modelled reserve need is an energy-security estimate, not the ECCO reserve setting and not a proposed TOU setting.
                      ${nextCheap?` Next published cheap window: ${nextCheap.start.toLocaleTimeString([],{hour:'2-digit',minute:'2-digit'})}–${nextCheap.end.toLocaleTimeString([],{hour:'2-digit',minute:'2-digit'})} at ${nextCheap.p.toFixed(2)}p/kWh.`:' Next-day cheap rates are not published yet.'}
                      Export arbitrage and battery degradation are still excluded.
""")
DASHBOARD_19_OLD = _blk(r"""
              rows: 6

          # ---- POWER FLOW / SOC MODEL ----
          - type: custom:apexcharts-card
            section_mode: true
            grid_options:
              columns: 48
              rows: 10
            header:
              show: true
              title: Power Flow Today • 00:00–24:00
              show_states: true
              colorize_states: true
            graph_span: 24h
            span:
              start: day
            yaxis:
              - id: power
                decimals: 0
                min: '|-500|'
                max: '|+500|'
                apex_config:
                  tickAmount: 6
                  title:
                    text: Power (W)
              - id: soc
                opposite: true
                min: 0
                max: 100
                decimals: 0
                apex_config:
                  tickAmount: 5
                  title:
                    text: SOC (%)
            all_series_config:
              stroke_width: 2
              extend_to: now
              group_by:
                func: avg
                duration: 5min
                fill: 'null'
            series:
              - entity: sensor.ecco_clock_dongle_ecco_pv_power
                name: Solar
                yaxis_id: power
                type: area
                color: '#ffbd3d'
                opacity: 0.22
              - entity: sensor.ecco_clock_dongle_ecco_load_power
                name: House
                yaxis_id: power
                type: line
                color: '#42aaff'
                stroke_width: 3
              - entity: sensor.ecco_clock_dongle_ecco_battery_output_power
                name: Battery
                yaxis_id: power
                type: area
                color: '#39d27a'
                opacity: 0.14
              - entity: sensor.ecco_clock_dongle_ecco_grid_power_ct_clamp
                name: Grid
                yaxis_id: power
                type: line
                color: '#b36cff'
                stroke_width: 2
              - entity: sensor.ecco_clock_dongle_ecco_battery_soc
                name: SOC
                yaxis_id: soc
                type: line
                color: '#ff6376'
                stroke_width: 2
                opacity: 0.95
                group_by:
                  func: last
                  duration: 5min
                  fill: last
              - entity: sensor.ecco_clock_dongle_ecco_battery_soc
                name: SOC Model
                yaxis_id: soc
                type: line
                color: '#ffb347'
                stroke_width: 3
                opacity: 1
                extend_to: false
                show:
                  in_header: false
                data_generator: |
                  const n=(id)=>Number(hass.states[id]?.state??0);
                  const clamp=(v,a,b)=>Math.max(a,Math.min(b,v));
                  const sensors=Object.values(hass.states).filter(s=>s.entity_id.startsWith('sensor.'));
                  const friendly=(s)=>String(s?.attributes?.friendly_name??s?.entity_id??'').toLowerCase();
                  const find=(need,exclude=[])=>sensors.find(s=>{
                    const x=friendly(s);return need.every(v=>x.includes(v))&&!exclude.some(v=>x.includes(v));
                  });
                  const num=(s)=>{const v=Number(s?.state);return Number.isFinite(v)?v:null;};

                  const soc=n('sensor.ecco_clock_dongle_ecco_battery_soc');
                  const loadToday=n('sensor.ecco_clock_dongle_ecco_day_load_energy');
                  const loadW=n('sensor.ecco_clock_dongle_ecco_load_power');
                  const pvW=n('sensor.ecco_clock_dongle_ecco_pv_power');
                  const actualPV=n('sensor.ecco_clock_dongle_ecco_day_pv_energy');
                  const capAh=n('sensor.ecco_clock_dongle_ecco_battery_capacity_ah')||620;
                  const capKwh=capAh*51.2/1000;

                  const forecast=num(states['sensor.ecco_solar_forecast_today']);
                  const remaining=num(states['sensor.ecco_solar_forecast_remaining']);
                  const forecastNow=num(states['sensor.ecco_solar_forecast_power_now']);

                  let ratio=1;
                  if(forecastNow!==null&&forecastNow>=250)ratio=clamp(pvW/forecastNow,.15,1.5);
                  let factor=forecastNow!==null&&forecastNow>=250?clamp(.65+.35*ratio,.70,1.10):1;
                  const expectedSoFar=forecast!==null&&remaining!==null?Math.max(forecast-remaining,0):0;
                  if(expectedSoFar>=2&&actualPV>=.5){
                    const dailyRatio=clamp(actualPV/expectedSoFar,.35,1.35);
                    factor=clamp(factor*.60+dailyRatio*.40,.65,1.10);
                  }

                  const now=new Date();
                  const elapsed=Math.max(now.getHours()+now.getMinutes()/60,1);
                  const avgKw=loadToday/elapsed;
                  const liveKw=loadW/1000;
                  const loadKw=clamp(avgKw*.65+liveKw*.35,.15,5);

                  const sun=hass.states['sun.sun'];
                  const sunset=sun?.state==='above_horizon'?new Date(sun.attributes?.next_setting):now;
                  const hSun=Math.max((sunset-now)/3600000,0);
                  const solarKwh=remaining!==null?remaining*factor*.95:0;
                  const solarKw=hSun>0?solarKwh/hSun:0;

                  const modelEnd=new Date(now);
                  modelEnd.setHours(24,0,0,0);
                  const out=[[now.getTime(),soc]];
                  let model=soc;
                  let t=new Date(now);
                  while(t<modelEnd){
                    const next=new Date(Math.min(t.getTime()+30*60000,modelEnd.getTime()));
                    const dt=(next-t)/3600000;
                    const solar=next<=sunset?solarKw:0;
                    model=clamp(model+((solar-loadKw)*dt/capKwh)*100,0,100);
                    out.push([next.getTime(),model]);
                    t=next;
                  }
                  return out;
            now:
              show: true
              color: '#6d7b91'
              label: Now
            apex_config:
              chart:
                height: 490
                toolbar:
                  show: false
              dataLabels:
                enabled: false
              legend:
                position: top
                horizontalAlign: left
              stroke:
                curve: smooth
                dashArray: [0, 0, 0, 0, 0, 6]
              grid:
                borderColor: rgba(255,255,255,0.08)
""")
DASHBOARD_19_NEW = _blk(r"""
              rows: 6

          # ---- CHART DATA STATUS (V2.1): tells a quiet new day apart from a sensor that is not reporting ----
          # Shown only when it has something to say; display only.
          - type: custom:button-card
            section_mode: true
            show_name: false
            show_icon: false
            show_state: false
            tap_action:
              action: none
            variables:
              msg: >
                [[[
                  const ids = [['Solar', 'sensor.ecco_clock_dongle_ecco_pv_power'], ['House', 'sensor.ecco_clock_dongle_ecco_load_power'], ['Battery', 'sensor.ecco_clock_dongle_ecco_battery_output_power'], ['Grid', 'sensor.ecco_clock_dongle_ecco_grid_power_ct_clamp'], ['SOC', 'sensor.ecco_clock_dongle_ecco_battery_soc']];
                  const bad = ids.filter(([, id]) => {
                    const s = states[id]?.state;
                    return s === undefined || ['unknown', 'unavailable'].includes(String(s).toLowerCase());
                  }).map(([name]) => name);
                  const now = new Date();
                  const minutes = now.getHours() * 60 + now.getMinutes();
                  if (bad.length) {
                    return `<span style="color:#ffbd3d;font-weight:800;">Not reporting now: ${bad.join(', ')}.</span> A gap or flat line for ${bad.length > 1 ? 'these' : 'this'} is missing data, not a quiet day.`;
                  }
                  if (minutes < 90) {
                    return `<span style="color:#7ab8ff;font-weight:800;">New day.</span> The chart starts at 00:00 and fills as history builds (${minutes} min so far), so short lines are normal now.`;
                  }
                  return '';
                ]]]
            custom_fields:
              note: '[[[ return variables.msg; ]]]'
            styles:
              card:
                - display: '[[[ return variables.msg ? "block" : "none"; ]]]'
                - border-radius: 12px
                - padding: 7px 12px
                - background: rgba(122,184,255,0.06)
                - border: 1px solid rgba(122,184,255,0.18)
                - box-shadow: none
              grid:
                - grid-template-areas: '"note"'
                - grid-template-columns: 1fr
              custom_fields:
                note:
                  - justify-self: stretch
                  - font-size: 11px
                  - line-height: 1.45
                  - color: rgba(255,255,255,0.72)
                  - white-space: normal
            grid_options:
              columns: 48
              rows: auto
          # ---- POWER FLOW / SOC MODEL ----
          - type: custom:apexcharts-card
            section_mode: true
            grid_options:
              columns: 48
              rows: 10
            header:
              show: true
              title: Power Flow Today • 00:00–24:00
              show_states: true
              colorize_states: true
            graph_span: 24h
            span:
              start: day
            yaxis:
              - id: power
                decimals: 0
                min: '|-500|'
                max: '|+500|'
                apex_config:
                  tickAmount: 6
                  title:
                    text: Power (W)
              - id: soc
                opposite: true
                min: 0
                max: 100
                decimals: 0
                apex_config:
                  tickAmount: 5
                  title:
                    text: SOC (%)
            all_series_config:
              stroke_width: 2
              extend_to: now
              group_by:
                func: avg
                duration: 5min
                fill: 'null'
            series:
              - entity: sensor.ecco_clock_dongle_ecco_pv_power
                name: Solar
                yaxis_id: power
                type: area
                color: '#ffbd3d'
                opacity: 0.22
              - entity: sensor.ecco_clock_dongle_ecco_load_power
                name: House
                yaxis_id: power
                type: line
                color: '#42aaff'
                stroke_width: 3
              - entity: sensor.ecco_clock_dongle_ecco_battery_output_power
                name: Battery
                yaxis_id: power
                type: area
                color: '#39d27a'
                opacity: 0.14
              - entity: sensor.ecco_clock_dongle_ecco_grid_power_ct_clamp
                name: Grid
                yaxis_id: power
                type: line
                color: '#b36cff'
                stroke_width: 2
              - entity: sensor.ecco_clock_dongle_ecco_battery_soc
                name: SOC
                yaxis_id: soc
                type: line
                color: '#ff6376'
                stroke_width: 2
                opacity: 0.95
                group_by:
                  func: last
                  duration: 5min
                  fill: last
            now:
              show: true
              color: '#6d7b91'
              label: Now
            apex_config:
              chart:
                height: 490
                toolbar:
                  show: false
              dataLabels:
                enabled: false
              legend:
                position: top
                horizontalAlign: left
              stroke:
                curve: smooth
                dashArray: [0, 0, 0, 0, 0]
              grid:
                borderColor: rgba(255,255,255,0.08)
""")
DASHBOARD_20_OLD = _blk(r"""
          # ---- TARIFF-AWARE NEXT-CHEAP STRATEGY ----
          - type: custom:button-card
            section_mode: true
            name: Smart Charge Strategy
            icon: mdi:battery-charging-medium
            show_name: true
            show_icon: true
            show_state: false
            tap_action:
              action: none
            custom_fields:
              body: >
                [[[
                  const n=(id)=>Number(states[id]?.state??0);
                  const clamp=(v,a,b)=>Math.max(a,Math.min(b,v));
                  const sensors=Object.values(states).filter(s=>s.entity_id.startsWith('sensor.'));
                  const events=Object.values(states).filter(s=>s.entity_id.startsWith('event.'));
                  const friendly=(s)=>String(s?.attributes?.friendly_name??s?.entity_id??'').toLowerCase();
                  const find=(need,exclude=[])=>sensors.find(s=>{
                    const x=friendly(s);return need.every(v=>x.includes(v))&&!exclude.some(v=>x.includes(v));
                  });
                  const num=(s)=>{const v=Number(s?.state);return Number.isFinite(v)?v:null;};
                  const isExport=(s)=>s.entity_id.includes('export')||friendly(s).includes('export');

                  const soc=n('sensor.ecco_clock_dongle_ecco_battery_soc');
                  const capAh=n('sensor.ecco_clock_dongle_ecco_battery_capacity_ah')||620;
                  const capKwh=capAh*51.2/1000;
                  const loadToday=n('sensor.ecco_clock_dongle_ecco_day_load_energy');
                  const loadW=n('sensor.ecco_clock_dongle_ecco_load_power');
                  const pvW=n('sensor.ecco_clock_dongle_ecco_pv_power');
                  const actualPV=n('sensor.ecco_clock_dongle_ecco_day_pv_energy');

                  const forecastToday=num(states['sensor.ecco_solar_forecast_today']);
                  const remaining=num(states['sensor.ecco_solar_forecast_remaining']);
                  const forecastNow=num(states['sensor.ecco_solar_forecast_power_now']);
                  const tomorrow=num(states['sensor.ecco_solar_forecast_tomorrow']);

                  let liveRatio=null;
                  if(forecastNow!==null&&forecastNow>=250)liveRatio=clamp(pvW/forecastNow,.15,1.5);
                  let factor=liveRatio!==null?clamp(.65+.35*liveRatio,.70,1.10):1;
                  const expectedSoFar=forecastToday!==null&&remaining!==null?Math.max(forecastToday-remaining,0):0;
                  if(expectedSoFar>=2&&actualPV>=.5){
                    const dailyRatio=clamp(actualPV/expectedSoFar,.35,1.35);
                    factor=clamp(factor*.60+dailyRatio*.40,.65,1.10);
                  }

                  const now=new Date();
                  const elapsed=Math.max(now.getHours()+now.getMinutes()/60,1);
                  const avgKw=loadToday/elapsed;
                  const liveKw=loadW/1000;
                  const runKw=clamp(avgKw*.65+liveKw*.35,.15,5);
                  const projectedDaily=clamp(runKw*24,6,60);

                  const adjustedTomorrow=tomorrow!==null?tomorrow*factor*.95:null;
                  const morningBridge=runKw*4.5;
                  const reserveKwh=capKwh*.10;
                  const dailyDeficit=adjustedTomorrow!==null?Math.max(projectedDaily-adjustedTomorrow,0):0;
                  const requiredEnergy=clamp(morningBridge+reserveKwh+dailyDeficit,capKwh*.20,capKwh);
                  const minimumReserveTarget=clamp(requiredEnergy/capKwh*100,20,100);

                  const configuredTarget=Number(states['sensor.ecco_clock_dongle_ecco_timezone1_soc']?.state??100);

                  const rateSensors=sensors.filter(s=>
                    s.entity_id.includes('octopus_energy_electricity')&&
                    s.entity_id.includes('current_rate')
                  );
                  const imp=rateSensors.find(s=>!isExport(s));

                  const parseEvent=(needle)=>{
                    const ev=events.find(s=>
                      s.entity_id.includes('octopus_energy_electricity')&&
                      s.entity_id.includes(needle)&&!isExport(s)
                    );
                    const rs=Array.isArray(ev?.attributes?.rates)?ev.attributes.rates:[];
                    return rs.map(r=>({
                      start:new Date(r.start),end:new Date(r.end),
                      p:Number(r.value_inc_vat)*100
                    })).filter(r=>Number.isFinite(r.p)&&!isNaN(r.start)&&!isNaN(r.end))
                      .sort((a,b)=>a.start-b.start);
                  };

                  const todayRates=parseEvent('current_day_rates');
                  const nextRates=parseEvent('next_day_rates');
                  const nextRateCoverageHours=nextRates.reduce((sum,r)=>sum+Math.max((r.end-r.start)/3600000,0),0);
                  const nextRatesReady=nextRates.length>=6 && nextRateCoverageHours>=3;
                  const todayMin=todayRates.length?Math.min(...todayRates.map(r=>r.p)):
                    (imp?.attributes?.current_day_min_rate!=null?Number(imp.attributes.current_day_min_rate)*100:null);
                  const todayMax=todayRates.length?Math.max(...todayRates.map(r=>r.p)):
                    (imp?.attributes?.current_day_max_rate!=null?Number(imp.attributes.current_day_max_rate)*100:null);

                  const eps=.35;
                  const windowFor=(rates,target,after)=>{
                    if(!rates.length||target===null)return null;
                    const hits=rates.filter(r=>r.end>after&&Math.abs(r.p-target)<=eps);
                    if(!hits.length)return null;
                    const first=hits[0];
                    let end=first.end;
                    for(const r of hits.slice(1)){
                      if(Math.abs(r.start-end)<60000)end=r.end;else break;
                    }
                    return {start:first.start,end,p:target};
                  };

                  let nextCheap= todayMin!==null ? windowFor(todayRates,todayMin,now) : null;
                  if(!nextCheap&&nextRatesReady){
                    const nm=Math.min(...nextRates.map(r=>r.p));
                    nextCheap=windowFor(nextRates,nm,now);
                  }

                  // Battery level expected at the live configured charge-slot start.
                  const targetTimeRaw=states['sensor.ecco_config_charge_start_time']?.state;
                  const targetMatch=String(targetTimeRaw??'').match(/^(\d{1,2}):(\d{2})$/);
                  const targetHour=targetMatch?Number(targetMatch[1]):0;
                  const targetMinute=targetMatch?Number(targetMatch[2]):30;
                  const targetTime=`${String(targetHour).padStart(2,'0')}:${String(targetMinute).padStart(2,'0')}`;
                  const cheapStart=new Date(now);
                  cheapStart.setHours(targetHour,targetMinute,0,0);
                  if(cheapStart<=now)cheapStart.setDate(cheapStart.getDate()+1);
                  const hCheap=Math.max((cheapStart-now)/3600000,0);

                  const likelySolar=remaining!==null?remaining*factor*.95:0;
                  const predictedAt0035=remaining!==null
                    ? clamp(soc+((likelySolar-runKw*hCheap)/capKwh)*100,0,100)
                    : soc;

                  // This is the extra energy needed for reserve/security only.
                  const batteryNeeded=Math.max(0,(minimumReserveTarget-predictedAt0035)/100*capKwh);
                  const gridNeeded=batteryNeeded/.94;

                  const nextCheapRate=nextCheap?.p ?? null;
                  const costRate=nextCheapRate ?? todayMin;
                  const costIsReference=nextCheapRate===null&&todayMin!==null;
                  const chargeCost=costRate!==null?gridNeeded*(costRate/100):null;
                  const avoidedValue=todayMax!==null?batteryNeeded*(todayMax/100):null;
                  const saving=chargeCost!==null&&avoidedValue!==null?avoidedValue-chargeCost:null;

                  const surplusPct=predictedAt0035-minimumReserveTarget;

                  let headline='Energy-reserve model says no top-up is needed';
                  let colour='#55e58e';
                  if(gridNeeded>0.2){
                    headline='Energy-reserve model recommends a cheap-rate top-up';
                    colour='#ffbd3d';
                  }else if(configuredTarget>minimumReserveTarget+15){
                    headline='Configured target is well above the minimum reserve needed';
                    colour='#7ab8ff';
                  }

                  return `<div>
                    <div style="font-size:16px;font-weight:800;color:${colour};">${headline}</div>

                    <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:9px;margin-top:12px;">
                      <div style="text-align:center;padding:9px;border-radius:10px;background:rgba(255,255,255,.035);border:1px solid rgba(255,255,255,.06);">
                        <div style="font-size:10px;color:rgba(255,255,255,.48);">Configured TOU target</div>
                        <div style="font-size:22px;font-weight:800;color:#b8adff;">${Number.isFinite(configuredTarget)?configuredTarget.toFixed(0):'--'}%</div>
                      </div>
                      <div style="text-align:center;padding:9px;border-radius:10px;background:rgba(255,255,255,.035);border:1px solid rgba(255,255,255,.06);">
                        <div style="font-size:10px;color:rgba(255,255,255,.48);">Minimum reserve needed</div>
                        <div style="font-size:22px;font-weight:800;color:#55e58e;">${minimumReserveTarget.toFixed(0)}%</div>
                      </div>
                      <div style="text-align:center;padding:9px;border-radius:10px;background:rgba(255,255,255,.035);border:1px solid rgba(255,255,255,.06);">
                        <div style="font-size:10px;color:rgba(255,255,255,.48);">Expected at ${targetTime}</div>
                        <div style="font-size:22px;font-weight:800;color:#ffbd3d;">${predictedAt0035.toFixed(0)}%</div>
                      </div>
                    </div>

                    <div style="margin-top:11px;font-size:11px;line-height:1.55;color:rgba(255,255,255,.60);">
                      Reserve margin at ${targetTime} <b style="color:${surplusPct>=0?'#55e58e':'#ff6376'}">${surplusPct>=0?'+':''}${surplusPct.toFixed(0)} points</b>
                      • next-day load model <b style="color:#fff">${projectedDaily.toFixed(1)} kWh</b>
                      ${adjustedTomorrow!==null?` • adaptive solar <b style="color:#ffbd3d">${adjustedTomorrow.toFixed(1)} kWh</b>`:''}
                      • reserve-only charge need <b style="color:#fff">${gridNeeded.toFixed(1)} kWh</b>
                      ${chargeCost!==null?` • estimated cost <b style="color:#fff">£${chargeCost.toFixed(2)}</b>${costIsReference?' using today’s cheap rate as a reference':''}`:''}
                      ${saving!==null&&saving>0&&gridNeeded>0.1?` • avoided peak-import value <b style="color:#55e58e">£${saving.toFixed(2)}</b>`:''}.
                    </div>

                    <div style="margin-top:9px;font-size:10px;line-height:1.45;color:rgba(255,255,255,.42);">
                      The minimum reserve target is an energy-security floor, not a proposed TOU setting.
                      ${nextCheap?` Next published cheap window: ${nextCheap.start.toLocaleTimeString([],{hour:'2-digit',minute:'2-digit'})}–${nextCheap.end.toLocaleTimeString([],{hour:'2-digit',minute:'2-digit'})} at ${nextCheap.p.toFixed(2)}p/kWh.`:' Next-day cheap rates are not published yet.'}
                      Export arbitrage and battery degradation are still excluded.
""")
DASHBOARD_20_NEW = _blk(r"""
          # ---- TARIFF-AWARE NEXT-CHEAP STRATEGY ----
          - type: custom:button-card
            section_mode: true
            name: Smart Charge Strategy
            icon: mdi:battery-charging-medium
            show_name: true
            show_icon: true
            show_state: false
            tap_action:
              action: none
            custom_fields:
              body: >
                [[[
                  const n=(id)=>Number(states[id]?.state??0);
                  const clamp=(v,a,b)=>Math.max(a,Math.min(b,v));
                  const sensors=Object.values(states).filter(s=>s.entity_id.startsWith('sensor.'));
                  const events=Object.values(states).filter(s=>s.entity_id.startsWith('event.'));
                  const friendly=(s)=>String(s?.attributes?.friendly_name??s?.entity_id??'').toLowerCase();
                  const find=(need,exclude=[])=>sensors.find(s=>{
                    const x=friendly(s);return need.every(v=>x.includes(v))&&!exclude.some(v=>x.includes(v));
                  });
                  const num=(s)=>{const v=Number(s?.state);return Number.isFinite(v)?v:null;};
                  const isExport=(s)=>s.entity_id.includes('export')||friendly(s).includes('export');

                  const soc=n('sensor.ecco_clock_dongle_ecco_battery_soc');
                  const capAh=n('sensor.ecco_clock_dongle_ecco_battery_capacity_ah')||620;
                  const capKwh=capAh*51.2/1000;
                  const loadToday=n('sensor.ecco_clock_dongle_ecco_day_load_energy');
                  const loadW=n('sensor.ecco_clock_dongle_ecco_load_power');
                  const pvW=n('sensor.ecco_clock_dongle_ecco_pv_power');
                  const actualPV=n('sensor.ecco_clock_dongle_ecco_day_pv_energy');

                  const forecastToday=num(states['sensor.ecco_solar_forecast_today']);
                  const remaining=num(states['sensor.ecco_solar_forecast_remaining']);
                  const forecastNow=num(states['sensor.ecco_solar_forecast_power_now']);
                  const tomorrow=num(states['sensor.ecco_solar_forecast_tomorrow']);

                  let liveRatio=null;
                  if(forecastNow!==null&&forecastNow>=250)liveRatio=clamp(pvW/forecastNow,.15,1.5);
                  let factor=liveRatio!==null?clamp(.65+.35*liveRatio,.70,1.10):1;
                  const expectedSoFar=forecastToday!==null&&remaining!==null?Math.max(forecastToday-remaining,0):0;
                  if(expectedSoFar>=2&&actualPV>=.5){
                    const dailyRatio=clamp(actualPV/expectedSoFar,.35,1.35);
                    factor=clamp(factor*.60+dailyRatio*.40,.65,1.10);
                  }

                  const now=new Date();
                  const elapsed=Math.max(now.getHours()+now.getMinutes()/60,1);
                  const avgKw=loadToday/elapsed;
                  const liveKw=loadW/1000;
                  const runKw=clamp(avgKw*.65+liveKw*.35,.15,5);
                  const projectedDaily=clamp(runKw*24,6,60);

                  const adjustedTomorrow=tomorrow!==null?tomorrow*factor*.95:null;
                  const morningBridge=runKw*4.5;
                  const reserveKwh=capKwh*.10;
                  const dailyDeficit=adjustedTomorrow!==null?Math.max(projectedDaily-adjustedTomorrow,0):0;
                  const requiredEnergy=clamp(morningBridge+reserveKwh+dailyDeficit,capKwh*.20,capKwh);
                  const minimumReserveTarget=clamp(requiredEnergy/capKwh*100,20,100);

                  const configuredTarget=Number(states['sensor.ecco_clock_dongle_ecco_timezone1_soc']?.state??100);

                  const rateSensors=sensors.filter(s=>
                    s.entity_id.includes('octopus_energy_electricity')&&
                    s.entity_id.includes('current_rate')
                  );
                  const imp=rateSensors.find(s=>!isExport(s));

                  const parseEvent=(needle)=>{
                    const ev=events.find(s=>
                      s.entity_id.includes('octopus_energy_electricity')&&
                      s.entity_id.includes(needle)&&!isExport(s)
                    );
                    const rs=Array.isArray(ev?.attributes?.rates)?ev.attributes.rates:[];
                    return rs.map(r=>({
                      start:new Date(r.start),end:new Date(r.end),
                      p:Number(r.value_inc_vat)*100
                    })).filter(r=>Number.isFinite(r.p)&&!isNaN(r.start)&&!isNaN(r.end))
                      .sort((a,b)=>a.start-b.start);
                  };

                  const todayRates=parseEvent('current_day_rates');
                  const nextRates=parseEvent('next_day_rates');
                  const nextRateCoverageHours=nextRates.reduce((sum,r)=>sum+Math.max((r.end-r.start)/3600000,0),0);
                  const nextRatesReady=nextRates.length>=6 && nextRateCoverageHours>=3;
                  const todayMin=todayRates.length?Math.min(...todayRates.map(r=>r.p)):
                    (imp?.attributes?.current_day_min_rate!=null?Number(imp.attributes.current_day_min_rate)*100:null);
                  const todayMax=todayRates.length?Math.max(...todayRates.map(r=>r.p)):
                    (imp?.attributes?.current_day_max_rate!=null?Number(imp.attributes.current_day_max_rate)*100:null);

                  const eps=.35;
                  const windowFor=(rates,target,after)=>{
                    if(!rates.length||target===null)return null;
                    const hits=rates.filter(r=>r.end>after&&Math.abs(r.p-target)<=eps);
                    if(!hits.length)return null;
                    const first=hits[0];
                    let end=first.end;
                    for(const r of hits.slice(1)){
                      if(Math.abs(r.start-end)<60000)end=r.end;else break;
                    }
                    return {start:first.start,end,p:target};
                  };

                  let nextCheap= todayMin!==null ? windowFor(todayRates,todayMin,now) : null;
                  if(!nextCheap&&nextRatesReady){
                    const nm=Math.min(...nextRates.map(r=>r.p));
                    nextCheap=windowFor(nextRates,nm,now);
                  }

                  // Battery level expected at the live configured charge-slot start.
                  const targetTimeRaw=states['sensor.ecco_config_charge_start_time']?.state;
                  const targetMatch=String(targetTimeRaw??'').match(/^(\d{1,2}):(\d{2})$/);
                  const targetHour=targetMatch?Number(targetMatch[1]):0;
                  const targetMinute=targetMatch?Number(targetMatch[2]):30;
                  const targetTime=`${String(targetHour).padStart(2,'0')}:${String(targetMinute).padStart(2,'0')}`;
                  const cheapStart=new Date(now);
                  cheapStart.setHours(targetHour,targetMinute,0,0);
                  if(cheapStart<=now)cheapStart.setDate(cheapStart.getDate()+1);
                  const hCheap=Math.max((cheapStart-now)/3600000,0);

                  // V2.1 (ovw2): never show a reserve projection or top-up advice from a battery reading that is not a number.
                  const socRaw=states['sensor.ecco_clock_dongle_ecco_battery_soc']?.state;
                  if(socRaw===undefined||['unknown','unavailable','none',''].includes(String(socRaw).toLowerCase())||!Number.isFinite(Number(socRaw))){
                    return `<div style="font-size:16px;font-weight:800;color:#aab4c3;">Battery data unavailable</div><div style="margin-top:6px;font-size:11px;line-height:1.5;color:rgba(255,255,255,.55);">No reserve projection or top-up advice is shown until the battery SOC reports again.</div>`;
                  }

                  // V2.1 (ovw2): the solar forecast is for the rest of the CURRENT calendar day; only the share that can arrive BEFORE the
                  // target may lift the SOC at the target (same rule as the ECCO Today card). Unknown sun times credit no solar at all.
                  const sunEntity=states['sun.sun'];
                  const solarShare=(()=>{
                    const set=sunEntity?.attributes?.next_setting?new Date(sunEntity.attributes.next_setting):null;
                    const rise=sunEntity?.attributes?.next_rising?new Date(sunEntity.attributes.next_rising):null;
                    if(!set||Number.isNaN(set.getTime()))return 0;
                    let from=null;
                    if(sunEntity.state==='above_horizon')from=now;
                    else if(rise&&!Number.isNaN(rise.getTime())&&rise.toDateString()===now.toDateString())from=rise;
                    if(from===null)return 0;
                    if(cheapStart>=set)return 1;
                    if(cheapStart<=from)return 0;
                    return (cheapStart-from)/(set-from);
                  })();
                  const targetDay=cheapStart.toDateString()===now.toDateString()?'today':'tomorrow';
                  const likelySolar=remaining!==null?remaining*factor*.95:0;
                  const predictedAt0035=remaining!==null
                    ? clamp(soc+((likelySolar*solarShare-runKw*hCheap)/capKwh)*100,0,100)
                    : soc;

                  // This is the extra energy needed for reserve/security only.
                  const batteryNeeded=Math.max(0,(minimumReserveTarget-predictedAt0035)/100*capKwh);
                  const gridNeeded=batteryNeeded/.94;

                  const nextCheapRate=nextCheap?.p ?? null;
                  const costRate=nextCheapRate ?? todayMin;
                  const costIsReference=nextCheapRate===null&&todayMin!==null;
                  const chargeCost=costRate!==null?gridNeeded*(costRate/100):null;
                  const avoidedValue=todayMax!==null?batteryNeeded*(todayMax/100):null;
                  const saving=chargeCost!==null&&avoidedValue!==null?avoidedValue-chargeCost:null;

                  const surplusPct=predictedAt0035-minimumReserveTarget;

                  let headline='Energy-reserve model says no top-up is needed';
                  let colour='#55e58e';
                  if(gridNeeded>0.2){
                    headline='Energy-reserve model recommends a cheap-rate top-up';
                    colour='#ffbd3d';
                  }else if(configuredTarget>minimumReserveTarget+15){
                    headline='Configured target is well above the modelled reserve need';
                    colour='#7ab8ff';
                  }

                  return `<div>
                    <div style="font-size:16px;font-weight:800;color:${colour};">${headline}</div>

                    <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:9px;margin-top:12px;">
                      <div style="text-align:center;padding:9px;border-radius:10px;background:rgba(255,255,255,.035);border:1px solid rgba(255,255,255,.06);">
                        <div style="font-size:10px;color:rgba(255,255,255,.48);">Configured TOU target</div>
                        <div style="font-size:22px;font-weight:800;color:#b8adff;">${Number.isFinite(configuredTarget)?configuredTarget.toFixed(0):'--'}%</div>
                      </div>
                      <div style="text-align:center;padding:9px;border-radius:10px;background:rgba(255,255,255,.035);border:1px solid rgba(255,255,255,.06);">
                        <div style="font-size:10px;color:rgba(255,255,255,.48);">Modelled reserve need</div>
                        <div style="font-size:22px;font-weight:800;color:#55e58e;">${minimumReserveTarget.toFixed(0)}%</div>
                      </div>
                      <div style="text-align:center;padding:9px;border-radius:10px;background:rgba(255,255,255,.035);border:1px solid rgba(255,255,255,.06);">
                        <div style="font-size:10px;color:rgba(255,255,255,.48);">Expected at ${targetTime} ${targetDay}</div>
                        <div style="font-size:22px;font-weight:800;color:#ffbd3d;">${predictedAt0035.toFixed(0)}%</div>
                      </div>
                    </div>

                    <div style="margin-top:11px;font-size:11px;line-height:1.55;color:rgba(255,255,255,.60);">
                      Reserve margin at ${targetTime} <b style="color:${surplusPct>=0?'#55e58e':'#ff6376'}">${surplusPct>=0?'+':''}${surplusPct.toFixed(0)} points</b>
                      • next-day load model <b style="color:#fff">${projectedDaily.toFixed(1)} kWh</b>
                      ${adjustedTomorrow!==null?` • adaptive solar <b style="color:#ffbd3d">${adjustedTomorrow.toFixed(1)} kWh</b>`:''}
                      • reserve-only charge need <b style="color:#fff">${gridNeeded.toFixed(1)} kWh</b>
                      ${chargeCost!==null?` • estimated cost <b style="color:#fff">£${chargeCost.toFixed(2)}</b>${costIsReference?' using today’s cheap rate as a reference':''}`:''}
                      ${saving!==null&&saving>0&&gridNeeded>0.1?` • avoided peak-import value <b style="color:#55e58e">£${saving.toFixed(2)}</b>`:''}.
                    </div>

                    <div style="margin-top:9px;font-size:10px;line-height:1.45;color:rgba(255,255,255,.42);">
                      The modelled reserve need is an energy-security estimate, not the ECCO reserve setting and not a proposed TOU setting.
                      ${nextCheap?` Next published cheap window: ${nextCheap.start.toLocaleTimeString([],{hour:'2-digit',minute:'2-digit'})}–${nextCheap.end.toLocaleTimeString([],{hour:'2-digit',minute:'2-digit'})} at ${nextCheap.p.toFixed(2)}p/kWh.`:' Next-day cheap rates are not published yet.'}
                      Export arbitrage and battery degradation are still excluded.
""")
DASHBOARD_21_OLD = _blk(r"""
              body: >
                [[[
                  return `<div style="font-size:12px;line-height:1.75;color:rgba(255,255,255,.70);">
                  <div><b style="color:#fff;">Minimum reserve</b> <span style="float:right;color:#55e58e;">Suggested 15%</span></div>
                  <div><b style="color:#fff;">Normal max target</b> <span style="float:right;">Adjustable / Auto</span></div>
                  <div><b style="color:#fff;">Round-trip efficiency</b> <span style="float:right;">Suggested 90%</span></div>
""")
DASHBOARD_21_NEW = _blk(r"""
              body: >
                [[[
                  const rs = Number(states['sensor.ecco_config_minimum_reserve_soc']?.state);
                  const reserveText = Number.isFinite(rs) ? `${rs.toFixed(0)}% (current setting)` : 'Setting unavailable';
                  return `<div style="font-size:12px;line-height:1.75;color:rgba(255,255,255,.70);">
                  <div><b style="color:#fff;">Minimum reserve</b> <span style="float:right;color:#55e58e;">${reserveText}</span></div>
                  <div><b style="color:#fff;">Normal max target</b> <span style="float:right;">Adjustable / Auto</span></div>
                  <div><b style="color:#fff;">Round-trip efficiency</b> <span style="float:right;">Suggested 90%</span></div>
""")
DASHBOARD_22_OLD = _blk(r"""
                  - line-height: 1.45
                  - overflow: visible
                  - white-space: normal
            grid_options:
              columns: 24
              rows: 5
          - type: custom:button-card
            section_mode: true
            name: Current Plan
            icon: mdi:calendar-clock
            show_name: true
            show_icon: true
            show_state: false
            tap_action:
              action: none
            custom_fields:
              mode: >
                [[[
                  const em = states['sensor.ecco_clock_dongle_ecco_energy_management_model']?.state ?? 'Unknown';
                  const tou = states['binary_sensor.ecco_clock_dongle_ecco_time_of_use_enabled']?.state === 'on';
                  return `<span style="display:inline-block;padding:5px 10px;border-radius:999px;
                    background:rgba(143,124,255,0.12);border:1px solid rgba(143,124,255,0.28);
                    color:#b8adff;font-size:12px;font-weight:700;">
                    ${em}${tou ? ' • TOU active' : ' • TOU off'}
                  </span>`;
                ]]]
              slot: >
                [[[
                  const read = (i, type) => states[`sensor.ecco_clock_dongle_ecco_timezone${i}_${type}`]?.state ?? '--';
                  const toMin = (t) => {
                    const m = String(t).match(/^(\d{1,2}):(\d{2})$/);
                    return m ? Number(m[1]) * 60 + Number(m[2]) : null;
                  };
                  const now = new Date();
                  const cur = now.getHours()*60 + now.getMinutes();
                  const slots = [];

                  for (let i=1; i<=6; i++) {
                    const next = i === 6 ? 1 : i + 1;
                    const startText = read(i,'time');
                    const endText = read(next,'time');
                    const start = toMin(startText);
                    const end = toMin(endText);
                    if (start === null || end === null) continue;
                    const active = end > start ? (cur >= start && cur < end) : (cur >= start || cur < end);
                    slots.push({
                      i, active, startText, endText,
                      power: Number(read(i,'power')),
                      soc: Number(read(i,'soc')),
                      charge: read(i,'charge')
                    });
                  }

                  const s = slots.find(x => x.active) ?? slots[0];
                  if (!s) return 'TOU schedule unavailable';

                  const power = Number.isFinite(s.power) ? `${(s.power/1000).toFixed(1)} kW ceiling` : '';
                  const charging = s.charge !== 'None';
                  const line1 = charging ? `${s.charge} charge enabled` : 'No forced charge';
                  const line2 = charging && Number.isFinite(s.soc)
                    ? `${s.soc.toFixed(0)}% charge target${power ? ` • ${power}` : ''}`
                    : power;

                  return `<div>
                    <div style="font-size:26px;font-weight:800;color:#ffffff;">Slot ${s.i}</div>
                    <div style="font-size:14px;font-weight:700;color:#b8adff;margin-top:2px;">${s.startText}–${s.endText}</div>
                    <div style="font-size:12px;color:rgba(255,255,255,0.64);margin-top:7px;line-height:1.5;">
                      ${line1}<br>${line2}
                    </div>
                  </div>`;
                ]]]
              next: >
                [[[
                  const read = (i, type) => states[`sensor.ecco_clock_dongle_ecco_timezone${i}_${type}`]?.state ?? '--';
                  const toMin = (t) => {
                    const m = String(t).match(/^(\d{1,2}):(\d{2})$/);
                    return m ? Number(m[1])*60 + Number(m[2]) : null;
                  };
                  const now = new Date();
                  const cur = now.getHours()*60 + now.getMinutes();
                  let best = null;
                  for (let i=1; i<=6; i++) {
                    const t = read(i,'time');
                    const mins = toMin(t);
                    if (mins === null) continue;
                    let delta = mins-cur;
                    if (delta <= 0) delta += 1440;
                    if (!best || delta < best.delta) best = {i,t,delta};
                  }
                  if (!best) return '';
                  const h = Math.floor(best.delta/60), m = best.delta%60;
                  const left = h ? `${h}h ${m}m` : `${m}m`;
                  return `<div style="margin-top:10px;padding:9px 11px;border-radius:11px;
                    background:rgba(255,255,255,0.035);border:1px solid rgba(255,255,255,0.07);
                    font-size:12px;color:rgba(255,255,255,0.67);">
                    Next transition <b style="color:#fff;">${best.t}</b> • ${left}
                  </div>`;
                ]]]
              access: >
                [[[
                  return `<div style="display:flex;align-items:center;gap:7px;margin-top:9px;
                    color:#55e58e;font-size:11px;font-weight:700;">
                    <ha-icon icon="mdi:shield-check" style="width:16px;"></ha-icon>
                    Observe only • no setting writes
                  </div>`;
                ]]]
            styles:
              card:
                - border-radius: 20px
                - padding: 16px 18px
                - background: linear-gradient(145deg, rgba(20,28,45,0.98), rgba(10,15,27,0.98))
                - border: 1px solid rgba(255,255,255,0.08)
                - box-shadow: 0 12px 32px rgba(0,0,0,0.22)
              grid:
                - grid-template-areas: '"i n" "mode mode" "slot slot" "next next" "access access"'
                - grid-template-columns: 34px 1fr
                - grid-template-rows: min-content min-content 1fr min-content min-content
                - row-gap: 8px
              icon:
                - width: 24px
                - color: '#b8adff'
              name:
                - justify-self: start
                - align-self: center
                - font-size: 20px
                - font-weight: 700
                - color: rgba(255,255,255,0.92)
              custom_fields:
                mode:
                  - justify-self: start
                slot:
                  - justify-self: stretch
                next:
                  - justify-self: stretch
                access:
                  - justify-self: stretch
            grid_options:
              columns: 16
              rows: 5

          # ---- SOLAR FORECAST ----
          - type: custom:button-card
            section_mode: true
            name: Smart Charge Strategy
            icon: mdi:battery-charging-medium
            show_name: true
            show_icon: true
            show_state: false
            tap_action:
              action: none
            custom_fields:
              body: >
                [[[
                  const n=(id)=>Number(states[id]?.state??0);
                  const clamp=(v,a,b)=>Math.max(a,Math.min(b,v));
                  const sensors=Object.values(states).filter(s=>s.entity_id.startsWith('sensor.'));
                  const events=Object.values(states).filter(s=>s.entity_id.startsWith('event.'));
                  const friendly=(s)=>String(s?.attributes?.friendly_name??s?.entity_id??'').toLowerCase();
                  const find=(need,exclude=[])=>sensors.find(s=>{
                    const x=friendly(s);return need.every(v=>x.includes(v))&&!exclude.some(v=>x.includes(v));
                  });
                  const num=(s)=>{const v=Number(s?.state);return Number.isFinite(v)?v:null;};
                  const isExport=(s)=>s.entity_id.includes('export')||friendly(s).includes('export');

                  const soc=n('sensor.ecco_clock_dongle_ecco_battery_soc');
                  const capAh=n('sensor.ecco_clock_dongle_ecco_battery_capacity_ah')||620;
                  const capKwh=capAh*51.2/1000;
                  const loadToday=n('sensor.ecco_clock_dongle_ecco_day_load_energy');
                  const loadW=n('sensor.ecco_clock_dongle_ecco_load_power');
                  const pvW=n('sensor.ecco_clock_dongle_ecco_pv_power');
                  const actualPV=n('sensor.ecco_clock_dongle_ecco_day_pv_energy');

                  const forecastToday=num(states['sensor.ecco_solar_forecast_today']);
                  const remaining=num(states['sensor.ecco_solar_forecast_remaining']);
                  const forecastNow=num(states['sensor.ecco_solar_forecast_power_now']);
                  const tomorrow=num(states['sensor.ecco_solar_forecast_tomorrow']);

                  let liveRatio=null;
                  if(forecastNow!==null&&forecastNow>=250)liveRatio=clamp(pvW/forecastNow,.15,1.5);
                  let factor=liveRatio!==null?clamp(.65+.35*liveRatio,.70,1.10):1;
                  const expectedSoFar=forecastToday!==null&&remaining!==null?Math.max(forecastToday-remaining,0):0;
                  if(expectedSoFar>=2&&actualPV>=.5){
                    const dailyRatio=clamp(actualPV/expectedSoFar,.35,1.35);
                    factor=clamp(factor*.60+dailyRatio*.40,.65,1.10);
                  }

                  const now=new Date();
                  const elapsed=Math.max(now.getHours()+now.getMinutes()/60,1);
                  const avgKw=loadToday/elapsed;
                  const liveKw=loadW/1000;
                  const runKw=clamp(avgKw*.65+liveKw*.35,.15,5);
                  const projectedDaily=clamp(runKw*24,6,60);

                  const adjustedTomorrow=tomorrow!==null?tomorrow*factor*.95:null;
                  const morningBridge=runKw*4.5;
                  const reserveKwh=capKwh*.10;
                  const dailyDeficit=adjustedTomorrow!==null?Math.max(projectedDaily-adjustedTomorrow,0):0;
                  const requiredEnergy=clamp(morningBridge+reserveKwh+dailyDeficit,capKwh*.20,capKwh);
                  const minimumReserveTarget=clamp(requiredEnergy/capKwh*100,20,100);

                  const configuredTarget=Number(states['sensor.ecco_clock_dongle_ecco_timezone1_soc']?.state??100);

                  const rateSensors=sensors.filter(s=>
                    s.entity_id.includes('octopus_energy_electricity')&&
                    s.entity_id.includes('current_rate')
                  );
                  const imp=rateSensors.find(s=>!isExport(s));

                  const parseEvent=(needle)=>{
                    const ev=events.find(s=>
                      s.entity_id.includes('octopus_energy_electricity')&&
                      s.entity_id.includes(needle)&&!isExport(s)
                    );
                    const rs=Array.isArray(ev?.attributes?.rates)?ev.attributes.rates:[];
                    return rs.map(r=>({
                      start:new Date(r.start),end:new Date(r.end),
                      p:Number(r.value_inc_vat)*100
                    })).filter(r=>Number.isFinite(r.p)&&!isNaN(r.start)&&!isNaN(r.end))
                      .sort((a,b)=>a.start-b.start);
                  };

                  const todayRates=parseEvent('current_day_rates');
                  const nextRates=parseEvent('next_day_rates');
                  const nextRateCoverageHours=nextRates.reduce((sum,r)=>sum+Math.max((r.end-r.start)/3600000,0),0);
                  const nextRatesReady=nextRates.length>=6 && nextRateCoverageHours>=3;
                  const todayMin=todayRates.length?Math.min(...todayRates.map(r=>r.p)):
                    (imp?.attributes?.current_day_min_rate!=null?Number(imp.attributes.current_day_min_rate)*100:null);
                  const todayMax=todayRates.length?Math.max(...todayRates.map(r=>r.p)):
                    (imp?.attributes?.current_day_max_rate!=null?Number(imp.attributes.current_day_max_rate)*100:null);

                  const eps=.35;
                  const windowFor=(rates,target,after)=>{
                    if(!rates.length||target===null)return null;
                    const hits=rates.filter(r=>r.end>after&&Math.abs(r.p-target)<=eps);
                    if(!hits.length)return null;
                    const first=hits[0];
                    let end=first.end;
                    for(const r of hits.slice(1)){
                      if(Math.abs(r.start-end)<60000)end=r.end;else break;
                    }
                    return {start:first.start,end,p:target};
                  };

                  let nextCheap= todayMin!==null ? windowFor(todayRates,todayMin,now) : null;
                  if(!nextCheap&&nextRatesReady){
                    const nm=Math.min(...nextRates.map(r=>r.p));
                    nextCheap=windowFor(nextRates,nm,now);
                  }

                  // Battery level expected at the live configured charge-slot start.
                  const targetTimeRaw=states['sensor.ecco_config_charge_start_time']?.state;
                  const targetMatch=String(targetTimeRaw??'').match(/^(\d{1,2}):(\d{2})$/);
                  const targetHour=targetMatch?Number(targetMatch[1]):0;
                  const targetMinute=targetMatch?Number(targetMatch[2]):30;
                  const targetTime=`${String(targetHour).padStart(2,'0')}:${String(targetMinute).padStart(2,'0')}`;
                  const cheapStart=new Date(now);
                  cheapStart.setHours(targetHour,targetMinute,0,0);
                  if(cheapStart<=now)cheapStart.setDate(cheapStart.getDate()+1);
                  const hCheap=Math.max((cheapStart-now)/3600000,0);

                  const likelySolar=remaining!==null?remaining*factor*.95:0;
                  const predictedAt0035=remaining!==null
                    ? clamp(soc+((likelySolar-runKw*hCheap)/capKwh)*100,0,100)
                    : soc;

                  // This is the extra energy needed for reserve/security only.
                  const batteryNeeded=Math.max(0,(minimumReserveTarget-predictedAt0035)/100*capKwh);
                  const gridNeeded=batteryNeeded/.94;

                  const nextCheapRate=nextCheap?.p ?? null;
                  const costRate=nextCheapRate ?? todayMin;
                  const costIsReference=nextCheapRate===null&&todayMin!==null;
                  const chargeCost=costRate!==null?gridNeeded*(costRate/100):null;
                  const avoidedValue=todayMax!==null?batteryNeeded*(todayMax/100):null;
                  const saving=chargeCost!==null&&avoidedValue!==null?avoidedValue-chargeCost:null;

                  const surplusPct=predictedAt0035-minimumReserveTarget;

                  let headline='Energy-reserve model says no top-up is needed';
                  let colour='#55e58e';
                  if(gridNeeded>0.2){
                    headline='Energy-reserve model recommends a cheap-rate top-up';
                    colour='#ffbd3d';
                  }else if(configuredTarget>minimumReserveTarget+15){
                    headline='Configured target is well above the minimum reserve needed';
                    colour='#7ab8ff';
                  }

                  return `<div>
                    <div style="font-size:16px;font-weight:800;color:${colour};">${headline}</div>

                    <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:9px;margin-top:12px;">
                      <div style="text-align:center;padding:9px;border-radius:10px;background:rgba(255,255,255,.035);border:1px solid rgba(255,255,255,.06);">
                        <div style="font-size:10px;color:rgba(255,255,255,.48);">Configured TOU target</div>
                        <div style="font-size:22px;font-weight:800;color:#b8adff;">${Number.isFinite(configuredTarget)?configuredTarget.toFixed(0):'--'}%</div>
                      </div>
                      <div style="text-align:center;padding:9px;border-radius:10px;background:rgba(255,255,255,.035);border:1px solid rgba(255,255,255,.06);">
                        <div style="font-size:10px;color:rgba(255,255,255,.48);">Minimum reserve needed</div>
                        <div style="font-size:22px;font-weight:800;color:#55e58e;">${minimumReserveTarget.toFixed(0)}%</div>
                      </div>
                      <div style="text-align:center;padding:9px;border-radius:10px;background:rgba(255,255,255,.035);border:1px solid rgba(255,255,255,.06);">
                        <div style="font-size:10px;color:rgba(255,255,255,.48);">Expected at ${targetTime}</div>
                        <div style="font-size:22px;font-weight:800;color:#ffbd3d;">${predictedAt0035.toFixed(0)}%</div>
                      </div>
                    </div>

                    <div style="margin-top:11px;font-size:11px;line-height:1.55;color:rgba(255,255,255,.60);">
                      Reserve margin at ${targetTime} <b style="color:${surplusPct>=0?'#55e58e':'#ff6376'}">${surplusPct>=0?'+':''}${surplusPct.toFixed(0)} points</b>
                      • next-day load model <b style="color:#fff">${projectedDaily.toFixed(1)} kWh</b>
                      ${adjustedTomorrow!==null?` • adaptive solar <b style="color:#ffbd3d">${adjustedTomorrow.toFixed(1)} kWh</b>`:''}
                      • reserve-only charge need <b style="color:#fff">${gridNeeded.toFixed(1)} kWh</b>
                      ${chargeCost!==null?` • estimated cost <b style="color:#fff">£${chargeCost.toFixed(2)}</b>${costIsReference?' using today’s cheap rate as a reference':''}`:''}
                      ${saving!==null&&saving>0&&gridNeeded>0.1?` • avoided peak-import value <b style="color:#55e58e">£${saving.toFixed(2)}</b>`:''}.
                    </div>

                    <div style="margin-top:9px;font-size:10px;line-height:1.45;color:rgba(255,255,255,.42);">
                      The minimum reserve target is an energy-security floor, not a proposed TOU setting.
                      ${nextCheap?` Next published cheap window: ${nextCheap.start.toLocaleTimeString([],{hour:'2-digit',minute:'2-digit'})}–${nextCheap.end.toLocaleTimeString([],{hour:'2-digit',minute:'2-digit'})} at ${nextCheap.p.toFixed(2)}p/kWh.`:' Next-day cheap rates are not published yet.'}
                      Export arbitrage and battery degradation are still excluded.
""")
DASHBOARD_22_NEW = _blk(r"""
                  - line-height: 1.45
                  - overflow: visible
                  - white-space: normal
            grid_options:
              columns: 24
              rows: 5
          - type: custom:button-card
            section_mode: true
            name: Current Plan
            icon: mdi:calendar-clock
            show_name: true
            show_icon: true
            show_state: false
            tap_action:
              action: none
            custom_fields:
              mode: >
                [[[
                  const em = states['sensor.ecco_clock_dongle_ecco_energy_management_model']?.state ?? 'Unknown';
                  const tou = states['binary_sensor.ecco_clock_dongle_ecco_time_of_use_enabled']?.state === 'on';
                  return `<span style="display:inline-block;padding:5px 10px;border-radius:999px;
                    background:rgba(143,124,255,0.12);border:1px solid rgba(143,124,255,0.28);
                    color:#b8adff;font-size:12px;font-weight:700;">
                    ${em}${tou ? ' • TOU active' : ' • TOU off'}
                  </span>`;
                ]]]
              slot: >
                [[[
                  const read = (i, type) => states[`sensor.ecco_clock_dongle_ecco_timezone${i}_${type}`]?.state ?? '--';
                  const toMin = (t) => {
                    const m = String(t).match(/^(\d{1,2}):(\d{2})$/);
                    return m ? Number(m[1]) * 60 + Number(m[2]) : null;
                  };
                  const now = new Date();
                  const cur = now.getHours()*60 + now.getMinutes();
                  const slots = [];

                  for (let i=1; i<=6; i++) {
                    const next = i === 6 ? 1 : i + 1;
                    const startText = read(i,'time');
                    const endText = read(next,'time');
                    const start = toMin(startText);
                    const end = toMin(endText);
                    if (start === null || end === null) continue;
                    const active = end > start ? (cur >= start && cur < end) : (cur >= start || cur < end);
                    slots.push({
                      i, active, startText, endText,
                      power: Number(read(i,'power')),
                      soc: Number(read(i,'soc')),
                      charge: read(i,'charge')
                    });
                  }

                  const s = slots.find(x => x.active) ?? slots[0];
                  if (!s) return 'TOU schedule unavailable';

                  const power = Number.isFinite(s.power) ? `${(s.power/1000).toFixed(1)} kW ceiling` : '';
                  const charging = s.charge !== 'None';
                  const line1 = charging ? `${s.charge} charge enabled` : 'No forced charge';
                  const line2 = charging && Number.isFinite(s.soc)
                    ? `${s.soc.toFixed(0)}% charge target${power ? ` • ${power}` : ''}`
                    : power;

                  return `<div>
                    <div style="font-size:26px;font-weight:800;color:#ffffff;">Slot ${s.i}</div>
                    <div style="font-size:14px;font-weight:700;color:#b8adff;margin-top:2px;">${s.startText}–${s.endText}</div>
                    <div style="font-size:12px;color:rgba(255,255,255,0.64);margin-top:7px;line-height:1.5;">
                      ${line1}<br>${line2}
                    </div>
                  </div>`;
                ]]]
              next: >
                [[[
                  const read = (i, type) => states[`sensor.ecco_clock_dongle_ecco_timezone${i}_${type}`]?.state ?? '--';
                  const toMin = (t) => {
                    const m = String(t).match(/^(\d{1,2}):(\d{2})$/);
                    return m ? Number(m[1])*60 + Number(m[2]) : null;
                  };
                  const now = new Date();
                  const cur = now.getHours()*60 + now.getMinutes();
                  let best = null;
                  for (let i=1; i<=6; i++) {
                    const t = read(i,'time');
                    const mins = toMin(t);
                    if (mins === null) continue;
                    let delta = mins-cur;
                    if (delta <= 0) delta += 1440;
                    if (!best || delta < best.delta) best = {i,t,delta};
                  }
                  if (!best) return '';
                  const h = Math.floor(best.delta/60), m = best.delta%60;
                  const left = h ? `${h}h ${m}m` : `${m}m`;
                  return `<div style="margin-top:10px;padding:9px 11px;border-radius:11px;
                    background:rgba(255,255,255,0.035);border:1px solid rgba(255,255,255,0.07);
                    font-size:12px;color:rgba(255,255,255,0.67);">
                    Next transition <b style="color:#fff;">${best.t}</b> • ${left}
                  </div>`;
                ]]]
              access: >
                [[[
                  return `<div style="display:flex;align-items:center;gap:7px;margin-top:9px;
                    color:#55e58e;font-size:11px;font-weight:700;">
                    <ha-icon icon="mdi:shield-check" style="width:16px;"></ha-icon>
                    Observe only • no setting writes
                  </div>`;
                ]]]
            styles:
              card:
                - border-radius: 20px
                - padding: 16px 18px
                - background: linear-gradient(145deg, rgba(20,28,45,0.98), rgba(10,15,27,0.98))
                - border: 1px solid rgba(255,255,255,0.08)
                - box-shadow: 0 12px 32px rgba(0,0,0,0.22)
              grid:
                - grid-template-areas: '"i n" "mode mode" "slot slot" "next next" "access access"'
                - grid-template-columns: 34px 1fr
                - grid-template-rows: min-content min-content 1fr min-content min-content
                - row-gap: 8px
              icon:
                - width: 24px
                - color: '#b8adff'
              name:
                - justify-self: start
                - align-self: center
                - font-size: 20px
                - font-weight: 700
                - color: rgba(255,255,255,0.92)
              custom_fields:
                mode:
                  - justify-self: start
                slot:
                  - justify-self: stretch
                next:
                  - justify-self: stretch
                access:
                  - justify-self: stretch
            grid_options:
              columns: 16
              rows: 5

          # ---- SOLAR FORECAST ----
          - type: custom:button-card
            section_mode: true
            name: Smart Charge Strategy
            icon: mdi:battery-charging-medium
            show_name: true
            show_icon: true
            show_state: false
            tap_action:
              action: none
            custom_fields:
              body: >
                [[[
                  const n=(id)=>Number(states[id]?.state??0);
                  const clamp=(v,a,b)=>Math.max(a,Math.min(b,v));
                  const sensors=Object.values(states).filter(s=>s.entity_id.startsWith('sensor.'));
                  const events=Object.values(states).filter(s=>s.entity_id.startsWith('event.'));
                  const friendly=(s)=>String(s?.attributes?.friendly_name??s?.entity_id??'').toLowerCase();
                  const find=(need,exclude=[])=>sensors.find(s=>{
                    const x=friendly(s);return need.every(v=>x.includes(v))&&!exclude.some(v=>x.includes(v));
                  });
                  const num=(s)=>{const v=Number(s?.state);return Number.isFinite(v)?v:null;};
                  const isExport=(s)=>s.entity_id.includes('export')||friendly(s).includes('export');

                  const soc=n('sensor.ecco_clock_dongle_ecco_battery_soc');
                  const capAh=n('sensor.ecco_clock_dongle_ecco_battery_capacity_ah')||620;
                  const capKwh=capAh*51.2/1000;
                  const loadToday=n('sensor.ecco_clock_dongle_ecco_day_load_energy');
                  const loadW=n('sensor.ecco_clock_dongle_ecco_load_power');
                  const pvW=n('sensor.ecco_clock_dongle_ecco_pv_power');
                  const actualPV=n('sensor.ecco_clock_dongle_ecco_day_pv_energy');

                  const forecastToday=num(states['sensor.ecco_solar_forecast_today']);
                  const remaining=num(states['sensor.ecco_solar_forecast_remaining']);
                  const forecastNow=num(states['sensor.ecco_solar_forecast_power_now']);
                  const tomorrow=num(states['sensor.ecco_solar_forecast_tomorrow']);

                  let liveRatio=null;
                  if(forecastNow!==null&&forecastNow>=250)liveRatio=clamp(pvW/forecastNow,.15,1.5);
                  let factor=liveRatio!==null?clamp(.65+.35*liveRatio,.70,1.10):1;
                  const expectedSoFar=forecastToday!==null&&remaining!==null?Math.max(forecastToday-remaining,0):0;
                  if(expectedSoFar>=2&&actualPV>=.5){
                    const dailyRatio=clamp(actualPV/expectedSoFar,.35,1.35);
                    factor=clamp(factor*.60+dailyRatio*.40,.65,1.10);
                  }

                  const now=new Date();
                  const elapsed=Math.max(now.getHours()+now.getMinutes()/60,1);
                  const avgKw=loadToday/elapsed;
                  const liveKw=loadW/1000;
                  const runKw=clamp(avgKw*.65+liveKw*.35,.15,5);
                  const projectedDaily=clamp(runKw*24,6,60);

                  const adjustedTomorrow=tomorrow!==null?tomorrow*factor*.95:null;
                  const morningBridge=runKw*4.5;
                  const reserveKwh=capKwh*.10;
                  const dailyDeficit=adjustedTomorrow!==null?Math.max(projectedDaily-adjustedTomorrow,0):0;
                  const requiredEnergy=clamp(morningBridge+reserveKwh+dailyDeficit,capKwh*.20,capKwh);
                  const minimumReserveTarget=clamp(requiredEnergy/capKwh*100,20,100);

                  const configuredTarget=Number(states['sensor.ecco_clock_dongle_ecco_timezone1_soc']?.state??100);

                  const rateSensors=sensors.filter(s=>
                    s.entity_id.includes('octopus_energy_electricity')&&
                    s.entity_id.includes('current_rate')
                  );
                  const imp=rateSensors.find(s=>!isExport(s));

                  const parseEvent=(needle)=>{
                    const ev=events.find(s=>
                      s.entity_id.includes('octopus_energy_electricity')&&
                      s.entity_id.includes(needle)&&!isExport(s)
                    );
                    const rs=Array.isArray(ev?.attributes?.rates)?ev.attributes.rates:[];
                    return rs.map(r=>({
                      start:new Date(r.start),end:new Date(r.end),
                      p:Number(r.value_inc_vat)*100
                    })).filter(r=>Number.isFinite(r.p)&&!isNaN(r.start)&&!isNaN(r.end))
                      .sort((a,b)=>a.start-b.start);
                  };

                  const todayRates=parseEvent('current_day_rates');
                  const nextRates=parseEvent('next_day_rates');
                  const nextRateCoverageHours=nextRates.reduce((sum,r)=>sum+Math.max((r.end-r.start)/3600000,0),0);
                  const nextRatesReady=nextRates.length>=6 && nextRateCoverageHours>=3;
                  const todayMin=todayRates.length?Math.min(...todayRates.map(r=>r.p)):
                    (imp?.attributes?.current_day_min_rate!=null?Number(imp.attributes.current_day_min_rate)*100:null);
                  const todayMax=todayRates.length?Math.max(...todayRates.map(r=>r.p)):
                    (imp?.attributes?.current_day_max_rate!=null?Number(imp.attributes.current_day_max_rate)*100:null);

                  const eps=.35;
                  const windowFor=(rates,target,after)=>{
                    if(!rates.length||target===null)return null;
                    const hits=rates.filter(r=>r.end>after&&Math.abs(r.p-target)<=eps);
                    if(!hits.length)return null;
                    const first=hits[0];
                    let end=first.end;
                    for(const r of hits.slice(1)){
                      if(Math.abs(r.start-end)<60000)end=r.end;else break;
                    }
                    return {start:first.start,end,p:target};
                  };

                  let nextCheap= todayMin!==null ? windowFor(todayRates,todayMin,now) : null;
                  if(!nextCheap&&nextRatesReady){
                    const nm=Math.min(...nextRates.map(r=>r.p));
                    nextCheap=windowFor(nextRates,nm,now);
                  }

                  // Battery level expected at the live configured charge-slot start.
                  const targetTimeRaw=states['sensor.ecco_config_charge_start_time']?.state;
                  const targetMatch=String(targetTimeRaw??'').match(/^(\d{1,2}):(\d{2})$/);
                  const targetHour=targetMatch?Number(targetMatch[1]):0;
                  const targetMinute=targetMatch?Number(targetMatch[2]):30;
                  const targetTime=`${String(targetHour).padStart(2,'0')}:${String(targetMinute).padStart(2,'0')}`;
                  const cheapStart=new Date(now);
                  cheapStart.setHours(targetHour,targetMinute,0,0);
                  if(cheapStart<=now)cheapStart.setDate(cheapStart.getDate()+1);
                  const hCheap=Math.max((cheapStart-now)/3600000,0);

                  // V2.1 (ovw2): never show a reserve projection or top-up advice from a battery reading that is not a number.
                  const socRaw=states['sensor.ecco_clock_dongle_ecco_battery_soc']?.state;
                  if(socRaw===undefined||['unknown','unavailable','none',''].includes(String(socRaw).toLowerCase())||!Number.isFinite(Number(socRaw))){
                    return `<div style="font-size:16px;font-weight:800;color:#aab4c3;">Battery data unavailable</div><div style="margin-top:6px;font-size:11px;line-height:1.5;color:rgba(255,255,255,.55);">No reserve projection or top-up advice is shown until the battery SOC reports again.</div>`;
                  }

                  // V2.1 (ovw2): the solar forecast is for the rest of the CURRENT calendar day; only the share that can arrive BEFORE the
                  // target may lift the SOC at the target (same rule as the ECCO Today card). Unknown sun times credit no solar at all.
                  const sunEntity=states['sun.sun'];
                  const solarShare=(()=>{
                    const set=sunEntity?.attributes?.next_setting?new Date(sunEntity.attributes.next_setting):null;
                    const rise=sunEntity?.attributes?.next_rising?new Date(sunEntity.attributes.next_rising):null;
                    if(!set||Number.isNaN(set.getTime()))return 0;
                    let from=null;
                    if(sunEntity.state==='above_horizon')from=now;
                    else if(rise&&!Number.isNaN(rise.getTime())&&rise.toDateString()===now.toDateString())from=rise;
                    if(from===null)return 0;
                    if(cheapStart>=set)return 1;
                    if(cheapStart<=from)return 0;
                    return (cheapStart-from)/(set-from);
                  })();
                  const targetDay=cheapStart.toDateString()===now.toDateString()?'today':'tomorrow';
                  const likelySolar=remaining!==null?remaining*factor*.95:0;
                  const predictedAt0035=remaining!==null
                    ? clamp(soc+((likelySolar*solarShare-runKw*hCheap)/capKwh)*100,0,100)
                    : soc;

                  // This is the extra energy needed for reserve/security only.
                  const batteryNeeded=Math.max(0,(minimumReserveTarget-predictedAt0035)/100*capKwh);
                  const gridNeeded=batteryNeeded/.94;

                  const nextCheapRate=nextCheap?.p ?? null;
                  const costRate=nextCheapRate ?? todayMin;
                  const costIsReference=nextCheapRate===null&&todayMin!==null;
                  const chargeCost=costRate!==null?gridNeeded*(costRate/100):null;
                  const avoidedValue=todayMax!==null?batteryNeeded*(todayMax/100):null;
                  const saving=chargeCost!==null&&avoidedValue!==null?avoidedValue-chargeCost:null;

                  const surplusPct=predictedAt0035-minimumReserveTarget;

                  let headline='Energy-reserve model says no top-up is needed';
                  let colour='#55e58e';
                  if(gridNeeded>0.2){
                    headline='Energy-reserve model recommends a cheap-rate top-up';
                    colour='#ffbd3d';
                  }else if(configuredTarget>minimumReserveTarget+15){
                    headline='Configured target is well above the modelled reserve need';
                    colour='#7ab8ff';
                  }

                  return `<div>
                    <div style="font-size:16px;font-weight:800;color:${colour};">${headline}</div>

                    <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:9px;margin-top:12px;">
                      <div style="text-align:center;padding:9px;border-radius:10px;background:rgba(255,255,255,.035);border:1px solid rgba(255,255,255,.06);">
                        <div style="font-size:10px;color:rgba(255,255,255,.48);">Configured TOU target</div>
                        <div style="font-size:22px;font-weight:800;color:#b8adff;">${Number.isFinite(configuredTarget)?configuredTarget.toFixed(0):'--'}%</div>
                      </div>
                      <div style="text-align:center;padding:9px;border-radius:10px;background:rgba(255,255,255,.035);border:1px solid rgba(255,255,255,.06);">
                        <div style="font-size:10px;color:rgba(255,255,255,.48);">Modelled reserve need</div>
                        <div style="font-size:22px;font-weight:800;color:#55e58e;">${minimumReserveTarget.toFixed(0)}%</div>
                      </div>
                      <div style="text-align:center;padding:9px;border-radius:10px;background:rgba(255,255,255,.035);border:1px solid rgba(255,255,255,.06);">
                        <div style="font-size:10px;color:rgba(255,255,255,.48);">Expected at ${targetTime} ${targetDay}</div>
                        <div style="font-size:22px;font-weight:800;color:#ffbd3d;">${predictedAt0035.toFixed(0)}%</div>
                      </div>
                    </div>

                    <div style="margin-top:11px;font-size:11px;line-height:1.55;color:rgba(255,255,255,.60);">
                      Reserve margin at ${targetTime} <b style="color:${surplusPct>=0?'#55e58e':'#ff6376'}">${surplusPct>=0?'+':''}${surplusPct.toFixed(0)} points</b>
                      • next-day load model <b style="color:#fff">${projectedDaily.toFixed(1)} kWh</b>
                      ${adjustedTomorrow!==null?` • adaptive solar <b style="color:#ffbd3d">${adjustedTomorrow.toFixed(1)} kWh</b>`:''}
                      • reserve-only charge need <b style="color:#fff">${gridNeeded.toFixed(1)} kWh</b>
                      ${chargeCost!==null?` • estimated cost <b style="color:#fff">£${chargeCost.toFixed(2)}</b>${costIsReference?' using today’s cheap rate as a reference':''}`:''}
                      ${saving!==null&&saving>0&&gridNeeded>0.1?` • avoided peak-import value <b style="color:#55e58e">£${saving.toFixed(2)}</b>`:''}.
                    </div>

                    <div style="margin-top:9px;font-size:10px;line-height:1.45;color:rgba(255,255,255,.42);">
                      The modelled reserve need is an energy-security estimate, not the ECCO reserve setting and not a proposed TOU setting.
                      ${nextCheap?` Next published cheap window: ${nextCheap.start.toLocaleTimeString([],{hour:'2-digit',minute:'2-digit'})}–${nextCheap.end.toLocaleTimeString([],{hour:'2-digit',minute:'2-digit'})} at ${nextCheap.p.toFixed(2)}p/kWh.`:' Next-day cheap rates are not published yet.'}
                      Export arbitrage and battery degradation are still excluded.
""")
DASHBOARD_23_OLD = _blk(r"""
              body: >
                [[[
                  return `<div style="font-size:12px;line-height:1.75;color:rgba(255,255,255,.70);">
                  <div><b style="color:#fff;">Initial automation mode</b> <span style="float:right;">Advisory</span></div>
                  <div><b style="color:#fff;">Normal grid charging</b> <span style="float:right;">Tariff-led</span></div>
                  <div><b style="color:#fff;">Minimum reserve</b> <span style="float:right;color:#55e58e;">15% starting point</span></div>
                  <div><b style="color:#fff;">Free-power behaviour</b> <span style="float:right;">Override & charge</span></div>
                  <div><b style="color:#fff;">Weekly full charge</b> <span style="float:right;">100% / 7 days</span></div>
""")
DASHBOARD_23_NEW = _blk(r"""
              body: >
                [[[
                  const rs = Number(states['sensor.ecco_config_minimum_reserve_soc']?.state);
                  const reserveText = Number.isFinite(rs) ? `${rs.toFixed(0)}% (current setting)` : 'Setting unavailable';
                  return `<div style="font-size:12px;line-height:1.75;color:rgba(255,255,255,.70);">
                  <div><b style="color:#fff;">Initial automation mode</b> <span style="float:right;">Advisory</span></div>
                  <div><b style="color:#fff;">Normal grid charging</b> <span style="float:right;">Tariff-led</span></div>
                  <div><b style="color:#fff;">Minimum reserve</b> <span style="float:right;color:#55e58e;">${reserveText}</span></div>
                  <div><b style="color:#fff;">Free-power behaviour</b> <span style="float:right;">Override & charge</span></div>
                  <div><b style="color:#fff;">Weekly full charge</b> <span style="float:right;">100% / 7 days</span></div>
""")
DASHBOARD_24_OLD = _blk(r"""
                  - width: 100%
                  - white-space: normal
            grid_options:
              columns: 48
              rows: 4

          - type: custom:button-card
            section_mode: true
            name: Current Plan
            icon: mdi:calendar-clock
            show_name: true
            show_icon: true
            show_state: false
            tap_action:
              action: none
            custom_fields:
              mode: >
                [[[
                  const em = states['sensor.ecco_clock_dongle_ecco_energy_management_model']?.state ?? 'Unknown';
                  const tou = states['binary_sensor.ecco_clock_dongle_ecco_time_of_use_enabled']?.state === 'on';
                  return `<span style="display:inline-block;padding:5px 10px;border-radius:999px;
                    background:rgba(143,124,255,0.12);border:1px solid rgba(143,124,255,0.28);
                    color:#b8adff;font-size:12px;font-weight:700;">
                    ${em}${tou ? ' • TOU active' : ' • TOU off'}
                  </span>`;
                ]]]
              slot: >
                [[[
                  const read = (i, type) => states[`sensor.ecco_clock_dongle_ecco_timezone${i}_${type}`]?.state ?? '--';
                  const toMin = (t) => {
                    const m = String(t).match(/^(\d{1,2}):(\d{2})$/);
                    return m ? Number(m[1]) * 60 + Number(m[2]) : null;
                  };
                  const now = new Date();
                  const cur = now.getHours()*60 + now.getMinutes();
                  const slots = [];

                  for (let i=1; i<=6; i++) {
                    const next = i === 6 ? 1 : i + 1;
                    const startText = read(i,'time');
                    const endText = read(next,'time');
                    const start = toMin(startText);
                    const end = toMin(endText);
                    if (start === null || end === null) continue;
                    const active = end > start ? (cur >= start && cur < end) : (cur >= start || cur < end);
                    slots.push({
                      i, active, startText, endText,
                      power: Number(read(i,'power')),
                      soc: Number(read(i,'soc')),
                      charge: read(i,'charge')
                    });
                  }

                  const s = slots.find(x => x.active) ?? slots[0];
                  if (!s) return 'TOU schedule unavailable';

                  const power = Number.isFinite(s.power) ? `${(s.power/1000).toFixed(1)} kW ceiling` : '';
                  const charging = s.charge !== 'None';
                  const line1 = charging ? `${s.charge} charge enabled` : 'No forced charge';
                  const line2 = charging && Number.isFinite(s.soc)
                    ? `${s.soc.toFixed(0)}% charge target${power ? ` • ${power}` : ''}`
                    : power;

                  return `<div>
                    <div style="font-size:26px;font-weight:800;color:#ffffff;">Slot ${s.i}</div>
                    <div style="font-size:14px;font-weight:700;color:#b8adff;margin-top:2px;">${s.startText}–${s.endText}</div>
                    <div style="font-size:12px;color:rgba(255,255,255,0.64);margin-top:7px;line-height:1.5;">
                      ${line1}<br>${line2}
                    </div>
                  </div>`;
                ]]]
              next: >
                [[[
                  const read = (i, type) => states[`sensor.ecco_clock_dongle_ecco_timezone${i}_${type}`]?.state ?? '--';
                  const toMin = (t) => {
                    const m = String(t).match(/^(\d{1,2}):(\d{2})$/);
                    return m ? Number(m[1])*60 + Number(m[2]) : null;
                  };
                  const now = new Date();
                  const cur = now.getHours()*60 + now.getMinutes();
                  let best = null;
                  for (let i=1; i<=6; i++) {
                    const t = read(i,'time');
                    const mins = toMin(t);
                    if (mins === null) continue;
                    let delta = mins-cur;
                    if (delta <= 0) delta += 1440;
                    if (!best || delta < best.delta) best = {i,t,delta};
                  }
                  if (!best) return '';
                  const h = Math.floor(best.delta/60), m = best.delta%60;
                  const left = h ? `${h}h ${m}m` : `${m}m`;
                  return `<div style="margin-top:10px;padding:9px 11px;border-radius:11px;
                    background:rgba(255,255,255,0.035);border:1px solid rgba(255,255,255,0.07);
                    font-size:12px;color:rgba(255,255,255,0.67);">
                    Next transition <b style="color:#fff;">${best.t}</b> • ${left}
                  </div>`;
                ]]]
              access: >
                [[[
                  return `<div style="display:flex;align-items:center;gap:7px;margin-top:9px;
                    color:#55e58e;font-size:11px;font-weight:700;">
                    <ha-icon icon="mdi:shield-check" style="width:16px;"></ha-icon>
                    Observe only • no setting writes
                  </div>`;
                ]]]
            styles:
              card:
                - border-radius: 20px
                - padding: 16px 18px
                - background: linear-gradient(145deg, rgba(20,28,45,0.98), rgba(10,15,27,0.98))
                - border: 1px solid rgba(255,255,255,0.08)
                - box-shadow: 0 12px 32px rgba(0,0,0,0.22)
              grid:
                - grid-template-areas: '"i n" "mode mode" "slot slot" "next next" "access access"'
                - grid-template-columns: 34px 1fr
                - grid-template-rows: min-content min-content 1fr min-content min-content
                - row-gap: 8px
              icon:
                - width: 24px
                - color: '#b8adff'
              name:
                - justify-self: start
                - align-self: center
                - font-size: 20px
                - font-weight: 700
                - color: rgba(255,255,255,0.92)
              custom_fields:
                mode:
                  - justify-self: start
                slot:
                  - justify-self: stretch
                next:
                  - justify-self: stretch
                access:
                  - justify-self: stretch
            grid_options:
              columns: 16
              rows: 5

          # ---- SOLAR FORECAST ----
          - type: custom:button-card
            section_mode: true
            name: Smart Charge Strategy
            icon: mdi:battery-charging-medium
            show_name: true
            show_icon: true
            show_state: false
            tap_action:
              action: none
            custom_fields:
              body: >
                [[[
                  const n=(id)=>Number(states[id]?.state??0);
                  const clamp=(v,a,b)=>Math.max(a,Math.min(b,v));
                  const sensors=Object.values(states).filter(s=>s.entity_id.startsWith('sensor.'));
                  const events=Object.values(states).filter(s=>s.entity_id.startsWith('event.'));
                  const friendly=(s)=>String(s?.attributes?.friendly_name??s?.entity_id??'').toLowerCase();
                  const find=(need,exclude=[])=>sensors.find(s=>{
                    const x=friendly(s);return need.every(v=>x.includes(v))&&!exclude.some(v=>x.includes(v));
                  });
                  const num=(s)=>{const v=Number(s?.state);return Number.isFinite(v)?v:null;};
                  const isExport=(s)=>s.entity_id.includes('export')||friendly(s).includes('export');

                  const soc=n('sensor.ecco_clock_dongle_ecco_battery_soc');
                  const capAh=n('sensor.ecco_clock_dongle_ecco_battery_capacity_ah')||620;
                  const capKwh=capAh*51.2/1000;
                  const loadToday=n('sensor.ecco_clock_dongle_ecco_day_load_energy');
                  const loadW=n('sensor.ecco_clock_dongle_ecco_load_power');
                  const pvW=n('sensor.ecco_clock_dongle_ecco_pv_power');
                  const actualPV=n('sensor.ecco_clock_dongle_ecco_day_pv_energy');

                  const forecastToday=num(states['sensor.ecco_solar_forecast_today']);
                  const remaining=num(states['sensor.ecco_solar_forecast_remaining']);
                  const forecastNow=num(states['sensor.ecco_solar_forecast_power_now']);
                  const tomorrow=num(states['sensor.ecco_solar_forecast_tomorrow']);

                  let liveRatio=null;
                  if(forecastNow!==null&&forecastNow>=250)liveRatio=clamp(pvW/forecastNow,.15,1.5);
                  let factor=liveRatio!==null?clamp(.65+.35*liveRatio,.70,1.10):1;
                  const expectedSoFar=forecastToday!==null&&remaining!==null?Math.max(forecastToday-remaining,0):0;
                  if(expectedSoFar>=2&&actualPV>=.5){
                    const dailyRatio=clamp(actualPV/expectedSoFar,.35,1.35);
                    factor=clamp(factor*.60+dailyRatio*.40,.65,1.10);
                  }

                  const now=new Date();
                  const elapsed=Math.max(now.getHours()+now.getMinutes()/60,1);
                  const avgKw=loadToday/elapsed;
                  const liveKw=loadW/1000;
                  const runKw=clamp(avgKw*.65+liveKw*.35,.15,5);
                  const projectedDaily=clamp(runKw*24,6,60);

                  const adjustedTomorrow=tomorrow!==null?tomorrow*factor*.95:null;
                  const morningBridge=runKw*4.5;
                  const reserveKwh=capKwh*.10;
                  const dailyDeficit=adjustedTomorrow!==null?Math.max(projectedDaily-adjustedTomorrow,0):0;
                  const requiredEnergy=clamp(morningBridge+reserveKwh+dailyDeficit,capKwh*.20,capKwh);
                  const minimumReserveTarget=clamp(requiredEnergy/capKwh*100,20,100);

                  const configuredTarget=Number(states['sensor.ecco_clock_dongle_ecco_timezone1_soc']?.state??100);

                  const rateSensors=sensors.filter(s=>
                    s.entity_id.includes('octopus_energy_electricity')&&
                    s.entity_id.includes('current_rate')
                  );
                  const imp=rateSensors.find(s=>!isExport(s));

                  const parseEvent=(needle)=>{
                    const ev=events.find(s=>
                      s.entity_id.includes('octopus_energy_electricity')&&
                      s.entity_id.includes(needle)&&!isExport(s)
                    );
                    const rs=Array.isArray(ev?.attributes?.rates)?ev.attributes.rates:[];
                    return rs.map(r=>({
                      start:new Date(r.start),end:new Date(r.end),
                      p:Number(r.value_inc_vat)*100
                    })).filter(r=>Number.isFinite(r.p)&&!isNaN(r.start)&&!isNaN(r.end))
                      .sort((a,b)=>a.start-b.start);
                  };

                  const todayRates=parseEvent('current_day_rates');
                  const nextRates=parseEvent('next_day_rates');
                  const nextRateCoverageHours=nextRates.reduce((sum,r)=>sum+Math.max((r.end-r.start)/3600000,0),0);
                  const nextRatesReady=nextRates.length>=6 && nextRateCoverageHours>=3;
                  const todayMin=todayRates.length?Math.min(...todayRates.map(r=>r.p)):
                    (imp?.attributes?.current_day_min_rate!=null?Number(imp.attributes.current_day_min_rate)*100:null);
                  const todayMax=todayRates.length?Math.max(...todayRates.map(r=>r.p)):
                    (imp?.attributes?.current_day_max_rate!=null?Number(imp.attributes.current_day_max_rate)*100:null);

                  const eps=.35;
                  const windowFor=(rates,target,after)=>{
                    if(!rates.length||target===null)return null;
                    const hits=rates.filter(r=>r.end>after&&Math.abs(r.p-target)<=eps);
                    if(!hits.length)return null;
                    const first=hits[0];
                    let end=first.end;
                    for(const r of hits.slice(1)){
                      if(Math.abs(r.start-end)<60000)end=r.end;else break;
                    }
                    return {start:first.start,end,p:target};
                  };

                  let nextCheap= todayMin!==null ? windowFor(todayRates,todayMin,now) : null;
                  if(!nextCheap&&nextRatesReady){
                    const nm=Math.min(...nextRates.map(r=>r.p));
                    nextCheap=windowFor(nextRates,nm,now);
                  }

                  // Battery level expected at the live configured charge-slot start.
                  const targetTimeRaw=states['sensor.ecco_config_charge_start_time']?.state;
                  const targetMatch=String(targetTimeRaw??'').match(/^(\d{1,2}):(\d{2})$/);
                  const targetHour=targetMatch?Number(targetMatch[1]):0;
                  const targetMinute=targetMatch?Number(targetMatch[2]):30;
                  const targetTime=`${String(targetHour).padStart(2,'0')}:${String(targetMinute).padStart(2,'0')}`;
                  const cheapStart=new Date(now);
                  cheapStart.setHours(targetHour,targetMinute,0,0);
                  if(cheapStart<=now)cheapStart.setDate(cheapStart.getDate()+1);
                  const hCheap=Math.max((cheapStart-now)/3600000,0);

                  const likelySolar=remaining!==null?remaining*factor*.95:0;
                  const predictedAt0035=remaining!==null
                    ? clamp(soc+((likelySolar-runKw*hCheap)/capKwh)*100,0,100)
                    : soc;

                  // This is the extra energy needed for reserve/security only.
                  const batteryNeeded=Math.max(0,(minimumReserveTarget-predictedAt0035)/100*capKwh);
                  const gridNeeded=batteryNeeded/.94;

                  const nextCheapRate=nextCheap?.p ?? null;
                  const costRate=nextCheapRate ?? todayMin;
                  const costIsReference=nextCheapRate===null&&todayMin!==null;
                  const chargeCost=costRate!==null?gridNeeded*(costRate/100):null;
                  const avoidedValue=todayMax!==null?batteryNeeded*(todayMax/100):null;
                  const saving=chargeCost!==null&&avoidedValue!==null?avoidedValue-chargeCost:null;

                  const surplusPct=predictedAt0035-minimumReserveTarget;

                  let headline='Energy-reserve model says no top-up is needed';
                  let colour='#55e58e';
                  if(gridNeeded>0.2){
                    headline='Energy-reserve model recommends a cheap-rate top-up';
                    colour='#ffbd3d';
                  }else if(configuredTarget>minimumReserveTarget+15){
                    headline='Configured target is well above the minimum reserve needed';
                    colour='#7ab8ff';
                  }

                  return `<div>
                    <div style="font-size:16px;font-weight:800;color:${colour};">${headline}</div>

                    <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:9px;margin-top:12px;">
                      <div style="text-align:center;padding:9px;border-radius:10px;background:rgba(255,255,255,.035);border:1px solid rgba(255,255,255,.06);">
                        <div style="font-size:10px;color:rgba(255,255,255,.48);">Configured TOU target</div>
                        <div style="font-size:22px;font-weight:800;color:#b8adff;">${Number.isFinite(configuredTarget)?configuredTarget.toFixed(0):'--'}%</div>
                      </div>
                      <div style="text-align:center;padding:9px;border-radius:10px;background:rgba(255,255,255,.035);border:1px solid rgba(255,255,255,.06);">
                        <div style="font-size:10px;color:rgba(255,255,255,.48);">Minimum reserve needed</div>
                        <div style="font-size:22px;font-weight:800;color:#55e58e;">${minimumReserveTarget.toFixed(0)}%</div>
                      </div>
                      <div style="text-align:center;padding:9px;border-radius:10px;background:rgba(255,255,255,.035);border:1px solid rgba(255,255,255,.06);">
                        <div style="font-size:10px;color:rgba(255,255,255,.48);">Expected at ${targetTime}</div>
                        <div style="font-size:22px;font-weight:800;color:#ffbd3d;">${predictedAt0035.toFixed(0)}%</div>
                      </div>
                    </div>

                    <div style="margin-top:11px;font-size:11px;line-height:1.55;color:rgba(255,255,255,.60);">
                      Reserve margin at ${targetTime} <b style="color:${surplusPct>=0?'#55e58e':'#ff6376'}">${surplusPct>=0?'+':''}${surplusPct.toFixed(0)} points</b>
                      • next-day load model <b style="color:#fff">${projectedDaily.toFixed(1)} kWh</b>
                      ${adjustedTomorrow!==null?` • adaptive solar <b style="color:#ffbd3d">${adjustedTomorrow.toFixed(1)} kWh</b>`:''}
                      • reserve-only charge need <b style="color:#fff">${gridNeeded.toFixed(1)} kWh</b>
                      ${chargeCost!==null?` • estimated cost <b style="color:#fff">£${chargeCost.toFixed(2)}</b>${costIsReference?' using today’s cheap rate as a reference':''}`:''}
                      ${saving!==null&&saving>0&&gridNeeded>0.1?` • avoided peak-import value <b style="color:#55e58e">£${saving.toFixed(2)}</b>`:''}.
                    </div>

                    <div style="margin-top:9px;font-size:10px;line-height:1.45;color:rgba(255,255,255,.42);">
                      The minimum reserve target is an energy-security floor, not a proposed TOU setting.
                      ${nextCheap?` Next published cheap window: ${nextCheap.start.toLocaleTimeString([],{hour:'2-digit',minute:'2-digit'})}–${nextCheap.end.toLocaleTimeString([],{hour:'2-digit',minute:'2-digit'})} at ${nextCheap.p.toFixed(2)}p/kWh.`:' Next-day cheap rates are not published yet.'}
                      Export arbitrage and battery degradation are still excluded.
""")
DASHBOARD_24_NEW = _blk(r"""
                  - width: 100%
                  - white-space: normal
            grid_options:
              columns: 48
              rows: 4

          - type: custom:button-card
            section_mode: true
            name: Current Plan
            icon: mdi:calendar-clock
            show_name: true
            show_icon: true
            show_state: false
            tap_action:
              action: none
            custom_fields:
              mode: >
                [[[
                  const em = states['sensor.ecco_clock_dongle_ecco_energy_management_model']?.state ?? 'Unknown';
                  const tou = states['binary_sensor.ecco_clock_dongle_ecco_time_of_use_enabled']?.state === 'on';
                  return `<span style="display:inline-block;padding:5px 10px;border-radius:999px;
                    background:rgba(143,124,255,0.12);border:1px solid rgba(143,124,255,0.28);
                    color:#b8adff;font-size:12px;font-weight:700;">
                    ${em}${tou ? ' • TOU active' : ' • TOU off'}
                  </span>`;
                ]]]
              slot: >
                [[[
                  const read = (i, type) => states[`sensor.ecco_clock_dongle_ecco_timezone${i}_${type}`]?.state ?? '--';
                  const toMin = (t) => {
                    const m = String(t).match(/^(\d{1,2}):(\d{2})$/);
                    return m ? Number(m[1]) * 60 + Number(m[2]) : null;
                  };
                  const now = new Date();
                  const cur = now.getHours()*60 + now.getMinutes();
                  const slots = [];

                  for (let i=1; i<=6; i++) {
                    const next = i === 6 ? 1 : i + 1;
                    const startText = read(i,'time');
                    const endText = read(next,'time');
                    const start = toMin(startText);
                    const end = toMin(endText);
                    if (start === null || end === null) continue;
                    const active = end > start ? (cur >= start && cur < end) : (cur >= start || cur < end);
                    slots.push({
                      i, active, startText, endText,
                      power: Number(read(i,'power')),
                      soc: Number(read(i,'soc')),
                      charge: read(i,'charge')
                    });
                  }

                  const s = slots.find(x => x.active) ?? slots[0];
                  if (!s) return 'TOU schedule unavailable';

                  const power = Number.isFinite(s.power) ? `${(s.power/1000).toFixed(1)} kW ceiling` : '';
                  const charging = s.charge !== 'None';
                  const line1 = charging ? `${s.charge} charge enabled` : 'No forced charge';
                  const line2 = charging && Number.isFinite(s.soc)
                    ? `${s.soc.toFixed(0)}% charge target${power ? ` • ${power}` : ''}`
                    : power;

                  return `<div>
                    <div style="font-size:26px;font-weight:800;color:#ffffff;">Slot ${s.i}</div>
                    <div style="font-size:14px;font-weight:700;color:#b8adff;margin-top:2px;">${s.startText}–${s.endText}</div>
                    <div style="font-size:12px;color:rgba(255,255,255,0.64);margin-top:7px;line-height:1.5;">
                      ${line1}<br>${line2}
                    </div>
                  </div>`;
                ]]]
              next: >
                [[[
                  const read = (i, type) => states[`sensor.ecco_clock_dongle_ecco_timezone${i}_${type}`]?.state ?? '--';
                  const toMin = (t) => {
                    const m = String(t).match(/^(\d{1,2}):(\d{2})$/);
                    return m ? Number(m[1])*60 + Number(m[2]) : null;
                  };
                  const now = new Date();
                  const cur = now.getHours()*60 + now.getMinutes();
                  let best = null;
                  for (let i=1; i<=6; i++) {
                    const t = read(i,'time');
                    const mins = toMin(t);
                    if (mins === null) continue;
                    let delta = mins-cur;
                    if (delta <= 0) delta += 1440;
                    if (!best || delta < best.delta) best = {i,t,delta};
                  }
                  if (!best) return '';
                  const h = Math.floor(best.delta/60), m = best.delta%60;
                  const left = h ? `${h}h ${m}m` : `${m}m`;
                  return `<div style="margin-top:10px;padding:9px 11px;border-radius:11px;
                    background:rgba(255,255,255,0.035);border:1px solid rgba(255,255,255,0.07);
                    font-size:12px;color:rgba(255,255,255,0.67);">
                    Next transition <b style="color:#fff;">${best.t}</b> • ${left}
                  </div>`;
                ]]]
              access: >
                [[[
                  return `<div style="display:flex;align-items:center;gap:7px;margin-top:9px;
                    color:#55e58e;font-size:11px;font-weight:700;">
                    <ha-icon icon="mdi:shield-check" style="width:16px;"></ha-icon>
                    Observe only • no setting writes
                  </div>`;
                ]]]
            styles:
              card:
                - border-radius: 20px
                - padding: 16px 18px
                - background: linear-gradient(145deg, rgba(20,28,45,0.98), rgba(10,15,27,0.98))
                - border: 1px solid rgba(255,255,255,0.08)
                - box-shadow: 0 12px 32px rgba(0,0,0,0.22)
              grid:
                - grid-template-areas: '"i n" "mode mode" "slot slot" "next next" "access access"'
                - grid-template-columns: 34px 1fr
                - grid-template-rows: min-content min-content 1fr min-content min-content
                - row-gap: 8px
              icon:
                - width: 24px
                - color: '#b8adff'
              name:
                - justify-self: start
                - align-self: center
                - font-size: 20px
                - font-weight: 700
                - color: rgba(255,255,255,0.92)
              custom_fields:
                mode:
                  - justify-self: start
                slot:
                  - justify-self: stretch
                next:
                  - justify-self: stretch
                access:
                  - justify-self: stretch
            grid_options:
              columns: 16
              rows: 5

          # ---- SOLAR FORECAST ----
          - type: custom:button-card
            section_mode: true
            name: Smart Charge Strategy
            icon: mdi:battery-charging-medium
            show_name: true
            show_icon: true
            show_state: false
            tap_action:
              action: none
            custom_fields:
              body: >
                [[[
                  const n=(id)=>Number(states[id]?.state??0);
                  const clamp=(v,a,b)=>Math.max(a,Math.min(b,v));
                  const sensors=Object.values(states).filter(s=>s.entity_id.startsWith('sensor.'));
                  const events=Object.values(states).filter(s=>s.entity_id.startsWith('event.'));
                  const friendly=(s)=>String(s?.attributes?.friendly_name??s?.entity_id??'').toLowerCase();
                  const find=(need,exclude=[])=>sensors.find(s=>{
                    const x=friendly(s);return need.every(v=>x.includes(v))&&!exclude.some(v=>x.includes(v));
                  });
                  const num=(s)=>{const v=Number(s?.state);return Number.isFinite(v)?v:null;};
                  const isExport=(s)=>s.entity_id.includes('export')||friendly(s).includes('export');

                  const soc=n('sensor.ecco_clock_dongle_ecco_battery_soc');
                  const capAh=n('sensor.ecco_clock_dongle_ecco_battery_capacity_ah')||620;
                  const capKwh=capAh*51.2/1000;
                  const loadToday=n('sensor.ecco_clock_dongle_ecco_day_load_energy');
                  const loadW=n('sensor.ecco_clock_dongle_ecco_load_power');
                  const pvW=n('sensor.ecco_clock_dongle_ecco_pv_power');
                  const actualPV=n('sensor.ecco_clock_dongle_ecco_day_pv_energy');

                  const forecastToday=num(states['sensor.ecco_solar_forecast_today']);
                  const remaining=num(states['sensor.ecco_solar_forecast_remaining']);
                  const forecastNow=num(states['sensor.ecco_solar_forecast_power_now']);
                  const tomorrow=num(states['sensor.ecco_solar_forecast_tomorrow']);

                  let liveRatio=null;
                  if(forecastNow!==null&&forecastNow>=250)liveRatio=clamp(pvW/forecastNow,.15,1.5);
                  let factor=liveRatio!==null?clamp(.65+.35*liveRatio,.70,1.10):1;
                  const expectedSoFar=forecastToday!==null&&remaining!==null?Math.max(forecastToday-remaining,0):0;
                  if(expectedSoFar>=2&&actualPV>=.5){
                    const dailyRatio=clamp(actualPV/expectedSoFar,.35,1.35);
                    factor=clamp(factor*.60+dailyRatio*.40,.65,1.10);
                  }

                  const now=new Date();
                  const elapsed=Math.max(now.getHours()+now.getMinutes()/60,1);
                  const avgKw=loadToday/elapsed;
                  const liveKw=loadW/1000;
                  const runKw=clamp(avgKw*.65+liveKw*.35,.15,5);
                  const projectedDaily=clamp(runKw*24,6,60);

                  const adjustedTomorrow=tomorrow!==null?tomorrow*factor*.95:null;
                  const morningBridge=runKw*4.5;
                  const reserveKwh=capKwh*.10;
                  const dailyDeficit=adjustedTomorrow!==null?Math.max(projectedDaily-adjustedTomorrow,0):0;
                  const requiredEnergy=clamp(morningBridge+reserveKwh+dailyDeficit,capKwh*.20,capKwh);
                  const minimumReserveTarget=clamp(requiredEnergy/capKwh*100,20,100);

                  const configuredTarget=Number(states['sensor.ecco_clock_dongle_ecco_timezone1_soc']?.state??100);

                  const rateSensors=sensors.filter(s=>
                    s.entity_id.includes('octopus_energy_electricity')&&
                    s.entity_id.includes('current_rate')
                  );
                  const imp=rateSensors.find(s=>!isExport(s));

                  const parseEvent=(needle)=>{
                    const ev=events.find(s=>
                      s.entity_id.includes('octopus_energy_electricity')&&
                      s.entity_id.includes(needle)&&!isExport(s)
                    );
                    const rs=Array.isArray(ev?.attributes?.rates)?ev.attributes.rates:[];
                    return rs.map(r=>({
                      start:new Date(r.start),end:new Date(r.end),
                      p:Number(r.value_inc_vat)*100
                    })).filter(r=>Number.isFinite(r.p)&&!isNaN(r.start)&&!isNaN(r.end))
                      .sort((a,b)=>a.start-b.start);
                  };

                  const todayRates=parseEvent('current_day_rates');
                  const nextRates=parseEvent('next_day_rates');
                  const nextRateCoverageHours=nextRates.reduce((sum,r)=>sum+Math.max((r.end-r.start)/3600000,0),0);
                  const nextRatesReady=nextRates.length>=6 && nextRateCoverageHours>=3;
                  const todayMin=todayRates.length?Math.min(...todayRates.map(r=>r.p)):
                    (imp?.attributes?.current_day_min_rate!=null?Number(imp.attributes.current_day_min_rate)*100:null);
                  const todayMax=todayRates.length?Math.max(...todayRates.map(r=>r.p)):
                    (imp?.attributes?.current_day_max_rate!=null?Number(imp.attributes.current_day_max_rate)*100:null);

                  const eps=.35;
                  const windowFor=(rates,target,after)=>{
                    if(!rates.length||target===null)return null;
                    const hits=rates.filter(r=>r.end>after&&Math.abs(r.p-target)<=eps);
                    if(!hits.length)return null;
                    const first=hits[0];
                    let end=first.end;
                    for(const r of hits.slice(1)){
                      if(Math.abs(r.start-end)<60000)end=r.end;else break;
                    }
                    return {start:first.start,end,p:target};
                  };

                  let nextCheap= todayMin!==null ? windowFor(todayRates,todayMin,now) : null;
                  if(!nextCheap&&nextRatesReady){
                    const nm=Math.min(...nextRates.map(r=>r.p));
                    nextCheap=windowFor(nextRates,nm,now);
                  }

                  // Battery level expected at the live configured charge-slot start.
                  const targetTimeRaw=states['sensor.ecco_config_charge_start_time']?.state;
                  const targetMatch=String(targetTimeRaw??'').match(/^(\d{1,2}):(\d{2})$/);
                  const targetHour=targetMatch?Number(targetMatch[1]):0;
                  const targetMinute=targetMatch?Number(targetMatch[2]):30;
                  const targetTime=`${String(targetHour).padStart(2,'0')}:${String(targetMinute).padStart(2,'0')}`;
                  const cheapStart=new Date(now);
                  cheapStart.setHours(targetHour,targetMinute,0,0);
                  if(cheapStart<=now)cheapStart.setDate(cheapStart.getDate()+1);
                  const hCheap=Math.max((cheapStart-now)/3600000,0);

                  // V2.1 (ovw2): never show a reserve projection or top-up advice from a battery reading that is not a number.
                  const socRaw=states['sensor.ecco_clock_dongle_ecco_battery_soc']?.state;
                  if(socRaw===undefined||['unknown','unavailable','none',''].includes(String(socRaw).toLowerCase())||!Number.isFinite(Number(socRaw))){
                    return `<div style="font-size:16px;font-weight:800;color:#aab4c3;">Battery data unavailable</div><div style="margin-top:6px;font-size:11px;line-height:1.5;color:rgba(255,255,255,.55);">No reserve projection or top-up advice is shown until the battery SOC reports again.</div>`;
                  }

                  // V2.1 (ovw2): the solar forecast is for the rest of the CURRENT calendar day; only the share that can arrive BEFORE the
                  // target may lift the SOC at the target (same rule as the ECCO Today card). Unknown sun times credit no solar at all.
                  const sunEntity=states['sun.sun'];
                  const solarShare=(()=>{
                    const set=sunEntity?.attributes?.next_setting?new Date(sunEntity.attributes.next_setting):null;
                    const rise=sunEntity?.attributes?.next_rising?new Date(sunEntity.attributes.next_rising):null;
                    if(!set||Number.isNaN(set.getTime()))return 0;
                    let from=null;
                    if(sunEntity.state==='above_horizon')from=now;
                    else if(rise&&!Number.isNaN(rise.getTime())&&rise.toDateString()===now.toDateString())from=rise;
                    if(from===null)return 0;
                    if(cheapStart>=set)return 1;
                    if(cheapStart<=from)return 0;
                    return (cheapStart-from)/(set-from);
                  })();
                  const targetDay=cheapStart.toDateString()===now.toDateString()?'today':'tomorrow';
                  const likelySolar=remaining!==null?remaining*factor*.95:0;
                  const predictedAt0035=remaining!==null
                    ? clamp(soc+((likelySolar*solarShare-runKw*hCheap)/capKwh)*100,0,100)
                    : soc;

                  // This is the extra energy needed for reserve/security only.
                  const batteryNeeded=Math.max(0,(minimumReserveTarget-predictedAt0035)/100*capKwh);
                  const gridNeeded=batteryNeeded/.94;

                  const nextCheapRate=nextCheap?.p ?? null;
                  const costRate=nextCheapRate ?? todayMin;
                  const costIsReference=nextCheapRate===null&&todayMin!==null;
                  const chargeCost=costRate!==null?gridNeeded*(costRate/100):null;
                  const avoidedValue=todayMax!==null?batteryNeeded*(todayMax/100):null;
                  const saving=chargeCost!==null&&avoidedValue!==null?avoidedValue-chargeCost:null;

                  const surplusPct=predictedAt0035-minimumReserveTarget;

                  let headline='Energy-reserve model says no top-up is needed';
                  let colour='#55e58e';
                  if(gridNeeded>0.2){
                    headline='Energy-reserve model recommends a cheap-rate top-up';
                    colour='#ffbd3d';
                  }else if(configuredTarget>minimumReserveTarget+15){
                    headline='Configured target is well above the modelled reserve need';
                    colour='#7ab8ff';
                  }

                  return `<div>
                    <div style="font-size:16px;font-weight:800;color:${colour};">${headline}</div>

                    <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:9px;margin-top:12px;">
                      <div style="text-align:center;padding:9px;border-radius:10px;background:rgba(255,255,255,.035);border:1px solid rgba(255,255,255,.06);">
                        <div style="font-size:10px;color:rgba(255,255,255,.48);">Configured TOU target</div>
                        <div style="font-size:22px;font-weight:800;color:#b8adff;">${Number.isFinite(configuredTarget)?configuredTarget.toFixed(0):'--'}%</div>
                      </div>
                      <div style="text-align:center;padding:9px;border-radius:10px;background:rgba(255,255,255,.035);border:1px solid rgba(255,255,255,.06);">
                        <div style="font-size:10px;color:rgba(255,255,255,.48);">Modelled reserve need</div>
                        <div style="font-size:22px;font-weight:800;color:#55e58e;">${minimumReserveTarget.toFixed(0)}%</div>
                      </div>
                      <div style="text-align:center;padding:9px;border-radius:10px;background:rgba(255,255,255,.035);border:1px solid rgba(255,255,255,.06);">
                        <div style="font-size:10px;color:rgba(255,255,255,.48);">Expected at ${targetTime} ${targetDay}</div>
                        <div style="font-size:22px;font-weight:800;color:#ffbd3d;">${predictedAt0035.toFixed(0)}%</div>
                      </div>
                    </div>

                    <div style="margin-top:11px;font-size:11px;line-height:1.55;color:rgba(255,255,255,.60);">
                      Reserve margin at ${targetTime} <b style="color:${surplusPct>=0?'#55e58e':'#ff6376'}">${surplusPct>=0?'+':''}${surplusPct.toFixed(0)} points</b>
                      • next-day load model <b style="color:#fff">${projectedDaily.toFixed(1)} kWh</b>
                      ${adjustedTomorrow!==null?` • adaptive solar <b style="color:#ffbd3d">${adjustedTomorrow.toFixed(1)} kWh</b>`:''}
                      • reserve-only charge need <b style="color:#fff">${gridNeeded.toFixed(1)} kWh</b>
                      ${chargeCost!==null?` • estimated cost <b style="color:#fff">£${chargeCost.toFixed(2)}</b>${costIsReference?' using today’s cheap rate as a reference':''}`:''}
                      ${saving!==null&&saving>0&&gridNeeded>0.1?` • avoided peak-import value <b style="color:#55e58e">£${saving.toFixed(2)}</b>`:''}.
                    </div>

                    <div style="margin-top:9px;font-size:10px;line-height:1.45;color:rgba(255,255,255,.42);">
                      The modelled reserve need is an energy-security estimate, not the ECCO reserve setting and not a proposed TOU setting.
                      ${nextCheap?` Next published cheap window: ${nextCheap.start.toLocaleTimeString([],{hour:'2-digit',minute:'2-digit'})}–${nextCheap.end.toLocaleTimeString([],{hour:'2-digit',minute:'2-digit'})} at ${nextCheap.p.toFixed(2)}p/kWh.`:' Next-day cheap rates are not published yet.'}
                      Export arbitrage and battery degradation are still excluded.
""")
DASHBOARD_25_OLD = _blk(r"""


          # ---- MAIN POWER GRAPH ----
          - type: custom:apexcharts-card
            section_mode: true
            grid_options:
              columns: 28
              rows: 11
            header:
              show: true
              title: Power Flow Today • 00:00–24:00
              show_states: true
              colorize_states: true
            graph_span: 24h
            span:
              start: day
            yaxis:
              - id: power
                decimals: 0
                min: '|-500|'
                max: '|+500|'
                apex_config:
                  tickAmount: 6
                  title:
                    text: Power (W)
              - id: soc
                opposite: true
                min: 0
                max: 100
                decimals: 0
                apex_config:
                  tickAmount: 5
                  title:
                    text: SOC (%)
            all_series_config:
              stroke_width: 2
              extend_to: now
              group_by:
                func: avg
                duration: 5min
                fill: 'null'
            series:
              - entity: sensor.ecco_clock_dongle_ecco_pv_power
                name: Solar
                yaxis_id: power
                type: area
                color: '#ffbd3d'
                opacity: 0.22
              - entity: sensor.ecco_clock_dongle_ecco_load_power
                name: House
                yaxis_id: power
                type: line
                color: '#42aaff'
                stroke_width: 3
              - entity: sensor.ecco_clock_dongle_ecco_battery_output_power
                name: Battery
                yaxis_id: power
                type: area
                color: '#39d27a'
                opacity: 0.14
              - entity: sensor.ecco_clock_dongle_ecco_grid_power_ct_clamp
                name: Grid
                yaxis_id: power
                type: line
                color: '#b36cff'
                stroke_width: 2
              - entity: sensor.ecco_clock_dongle_ecco_battery_soc
                name: SOC
                yaxis_id: soc
                type: line
                color: '#ff6376'
                stroke_width: 2
                opacity: 0.95
                group_by:
                  func: last
                  duration: 5min
                  fill: last
              - entity: sensor.ecco_clock_dongle_ecco_battery_soc
                name: SOC Model
                yaxis_id: soc
                type: line
                color: '#ffb347'
                stroke_width: 3
                opacity: 1
                extend_to: false
                show:
                  in_header: false
                data_generator: |
                  const n=(id)=>Number(hass.states[id]?.state??0);
                  const clamp=(v,a,b)=>Math.max(a,Math.min(b,v));
                  const sensors=Object.values(hass.states).filter(s=>s.entity_id.startsWith('sensor.'));
                  const friendly=(s)=>String(s?.attributes?.friendly_name??s?.entity_id??'').toLowerCase();
                  const find=(need,exclude=[])=>sensors.find(s=>{
                    const x=friendly(s);return need.every(v=>x.includes(v))&&!exclude.some(v=>x.includes(v));
                  });
                  const num=(s)=>{const v=Number(s?.state);return Number.isFinite(v)?v:null;};

                  const soc=n('sensor.ecco_clock_dongle_ecco_battery_soc');
                  const loadToday=n('sensor.ecco_clock_dongle_ecco_day_load_energy');
                  const loadW=n('sensor.ecco_clock_dongle_ecco_load_power');
                  const pvW=n('sensor.ecco_clock_dongle_ecco_pv_power');
                  const actualPV=n('sensor.ecco_clock_dongle_ecco_day_pv_energy');
                  const capAh=n('sensor.ecco_clock_dongle_ecco_battery_capacity_ah')||620;
                  const capKwh=capAh*51.2/1000;

                  const forecast=num(states['sensor.ecco_solar_forecast_today']);
                  const remaining=num(states['sensor.ecco_solar_forecast_remaining']);
                  const forecastNow=num(states['sensor.ecco_solar_forecast_power_now']);

                  let ratio=1;
                  if(forecastNow!==null&&forecastNow>=250)ratio=clamp(pvW/forecastNow,.15,1.5);
                  let factor=forecastNow!==null&&forecastNow>=250?clamp(.65+.35*ratio,.70,1.10):1;
                  const expectedSoFar=forecast!==null&&remaining!==null?Math.max(forecast-remaining,0):0;
                  if(expectedSoFar>=2&&actualPV>=.5){
                    const dailyRatio=clamp(actualPV/expectedSoFar,.35,1.35);
                    factor=clamp(factor*.60+dailyRatio*.40,.65,1.10);
                  }

                  const now=new Date();
                  const elapsed=Math.max(now.getHours()+now.getMinutes()/60,1);
                  const avgKw=loadToday/elapsed;
                  const liveKw=loadW/1000;
                  const loadKw=clamp(avgKw*.65+liveKw*.35,.15,5);

                  const sun=hass.states['sun.sun'];
                  const sunset=sun?.state==='above_horizon'?new Date(sun.attributes?.next_setting):now;
                  const hSun=Math.max((sunset-now)/3600000,0);
                  const solarKwh=remaining!==null?remaining*factor*.95:0;
                  const solarKw=hSun>0?solarKwh/hSun:0;

                  const modelEnd=new Date(now);
                  modelEnd.setHours(24,0,0,0);
                  const out=[[now.getTime(),soc]];
                  let model=soc;
                  let t=new Date(now);
                  while(t<modelEnd){
                    const next=new Date(Math.min(t.getTime()+30*60000,modelEnd.getTime()));
                    const dt=(next-t)/3600000;
                    const solar=next<=sunset?solarKw:0;
                    model=clamp(model+((solar-loadKw)*dt/capKwh)*100,0,100);
                    out.push([next.getTime(),model]);
                    t=next;
                  }
                  return out;
            now:
              show: true
              color: '#6d7b91'
              label: Now
            apex_config:
              chart:
                height: 490
                toolbar:
                  show: false
              dataLabels:
                enabled: false
              legend:
                position: top
                horizontalAlign: left
              stroke:
                curve: smooth
                dashArray: [0, 0, 0, 0, 0, 6]
              grid:
                borderColor: rgba(255,255,255,0.08)
""")
DASHBOARD_25_NEW = _blk(r"""


          # ---- CHART DATA STATUS (V2.1): tells a quiet new day apart from a sensor that is not reporting ----
          # Shown only when it has something to say; display only.
          - type: custom:button-card
            section_mode: true
            show_name: false
            show_icon: false
            show_state: false
            tap_action:
              action: none
            variables:
              msg: >
                [[[
                  const ids = [['Solar', 'sensor.ecco_clock_dongle_ecco_pv_power'], ['House', 'sensor.ecco_clock_dongle_ecco_load_power'], ['Battery', 'sensor.ecco_clock_dongle_ecco_battery_output_power'], ['Grid', 'sensor.ecco_clock_dongle_ecco_grid_power_ct_clamp'], ['SOC', 'sensor.ecco_clock_dongle_ecco_battery_soc']];
                  const bad = ids.filter(([, id]) => {
                    const s = states[id]?.state;
                    return s === undefined || ['unknown', 'unavailable'].includes(String(s).toLowerCase());
                  }).map(([name]) => name);
                  const now = new Date();
                  const minutes = now.getHours() * 60 + now.getMinutes();
                  if (bad.length) {
                    return `<span style="color:#ffbd3d;font-weight:800;">Not reporting now: ${bad.join(', ')}.</span> A gap or flat line for ${bad.length > 1 ? 'these' : 'this'} is missing data, not a quiet day.`;
                  }
                  if (minutes < 90) {
                    return `<span style="color:#7ab8ff;font-weight:800;">New day.</span> The chart starts at 00:00 and fills as history builds (${minutes} min so far), so short lines are normal now.`;
                  }
                  return '';
                ]]]
            custom_fields:
              note: '[[[ return variables.msg; ]]]'
            styles:
              card:
                - display: '[[[ return variables.msg ? "block" : "none"; ]]]'
                - border-radius: 12px
                - padding: 7px 12px
                - background: rgba(122,184,255,0.06)
                - border: 1px solid rgba(122,184,255,0.18)
                - box-shadow: none
              grid:
                - grid-template-areas: '"note"'
                - grid-template-columns: 1fr
              custom_fields:
                note:
                  - justify-self: stretch
                  - font-size: 11px
                  - line-height: 1.45
                  - color: rgba(255,255,255,0.72)
                  - white-space: normal
            grid_options:
              columns: 28
              rows: auto
          # ---- MAIN POWER GRAPH ----
          - type: custom:apexcharts-card
            section_mode: true
            grid_options:
              columns: 28
              rows: 11
            header:
              show: true
              title: Power Flow Today • 00:00–24:00
              show_states: true
              colorize_states: true
            graph_span: 24h
            span:
              start: day
            yaxis:
              - id: power
                decimals: 0
                min: '|-500|'
                max: '|+500|'
                apex_config:
                  tickAmount: 6
                  title:
                    text: Power (W)
              - id: soc
                opposite: true
                min: 0
                max: 100
                decimals: 0
                apex_config:
                  tickAmount: 5
                  title:
                    text: SOC (%)
            all_series_config:
              stroke_width: 2
              extend_to: now
              group_by:
                func: avg
                duration: 5min
                fill: 'null'
            series:
              - entity: sensor.ecco_clock_dongle_ecco_pv_power
                name: Solar
                yaxis_id: power
                type: area
                color: '#ffbd3d'
                opacity: 0.22
              - entity: sensor.ecco_clock_dongle_ecco_load_power
                name: House
                yaxis_id: power
                type: line
                color: '#42aaff'
                stroke_width: 3
              - entity: sensor.ecco_clock_dongle_ecco_battery_output_power
                name: Battery
                yaxis_id: power
                type: area
                color: '#39d27a'
                opacity: 0.14
              - entity: sensor.ecco_clock_dongle_ecco_grid_power_ct_clamp
                name: Grid
                yaxis_id: power
                type: line
                color: '#b36cff'
                stroke_width: 2
              - entity: sensor.ecco_clock_dongle_ecco_battery_soc
                name: SOC
                yaxis_id: soc
                type: line
                color: '#ff6376'
                stroke_width: 2
                opacity: 0.95
                group_by:
                  func: last
                  duration: 5min
                  fill: last
            now:
              show: true
              color: '#6d7b91'
              label: Now
            apex_config:
              chart:
                height: 490
                toolbar:
                  show: false
              dataLabels:
                enabled: false
              legend:
                position: top
                horizontalAlign: left
              stroke:
                curve: smooth
                dashArray: [0, 0, 0, 0, 0]
              grid:
                borderColor: rgba(255,255,255,0.08)
""")
DASHBOARD_EDITS = (
    (DASHBOARD_0_OLD, DASHBOARD_0_NEW),
    (DASHBOARD_1_OLD, DASHBOARD_1_NEW),
    (DASHBOARD_2_OLD, DASHBOARD_2_NEW),
    (DASHBOARD_3_OLD, DASHBOARD_3_NEW),
    (DASHBOARD_4_OLD, DASHBOARD_4_NEW),
    (DASHBOARD_5_OLD, DASHBOARD_5_NEW),
    (DASHBOARD_6_OLD, DASHBOARD_6_NEW),
    (DASHBOARD_7_OLD, DASHBOARD_7_NEW),
    (DASHBOARD_8_OLD, DASHBOARD_8_NEW),
    (DASHBOARD_9_OLD, DASHBOARD_9_NEW),
    (DASHBOARD_10_OLD, DASHBOARD_10_NEW),
    (DASHBOARD_11_OLD, DASHBOARD_11_NEW),
    (DASHBOARD_12_OLD, DASHBOARD_12_NEW),
    (DASHBOARD_13_OLD, DASHBOARD_13_NEW),
    (DASHBOARD_14_OLD, DASHBOARD_14_NEW),
    (DASHBOARD_15_OLD, DASHBOARD_15_NEW),
    (DASHBOARD_16_OLD, DASHBOARD_16_NEW),
    (DASHBOARD_17_OLD, DASHBOARD_17_NEW),
    (DASHBOARD_18_OLD, DASHBOARD_18_NEW),
    (DASHBOARD_19_OLD, DASHBOARD_19_NEW),
    (DASHBOARD_20_OLD, DASHBOARD_20_NEW),
    (DASHBOARD_21_OLD, DASHBOARD_21_NEW),
    (DASHBOARD_22_OLD, DASHBOARD_22_NEW),
    (DASHBOARD_23_OLD, DASHBOARD_23_NEW),
    (DASHBOARD_24_OLD, DASHBOARD_24_NEW),
    (DASHBOARD_25_OLD, DASHBOARD_25_NEW),
)

def pre_ovw2_dashboard(text: str) -> str:
    """home-assistant/dashboards/ecco_pro.yaml with exactly ovw2's edits undone (a frozen reverter of chain entry ovw2, PEX)."""
    return _revert(text, DASHBOARD_EDITS, "home-assistant/dashboards/ecco_pro.yaml")


pre_ovw2_dashboard.edits = DASHBOARD_EDITS   # the PEX contract: a reverter exposes its exact (before, after) pairs


def add_ovw2_dashboard(text: str) -> str:
    """Applies ovw2's home-assistant/dashboards/ecco_pro.yaml edits to the earlier text (the round trip)."""
    return _apply(text, DASHBOARD_EDITS, "home-assistant/dashboards/ecco_pro.yaml")

# ---- (PEX frozen edit) VERSION.yaml ------------------------------------------------------------------------------------
VERSION_REL = "VERSION.yaml"
VERSION_0_OLD = _blk(r"""
current:
  dashboard:
    version: "7.21.0"
    path: home-assistant/dashboards/ecco_pro.yaml
    # v7.21.0 (FE1) shows the batteries' time to reserve: the Overview Energy Flow card's battery node reads
    # sensor.ecco_battery_time_to_reserve (nodes.battery.time_to_reserve) and the battery estimate card adds its
""")
VERSION_0_NEW = _blk(r"""
current:
  dashboard:
    version: "7.21.1"
    path: home-assistant/dashboards/ecco_pro.yaml
    # v7.21.1 (OVW2) is the Overview V2.1 polish and accuracy pass over 7.21.0 (FE1's time to reserve is kept): the SOC projections in ECCO Today and Smart Charge
    # Strategy credit only the solar that can arrive before their target time and show an unavailable state instead of an
    # unsupported number; the dead SOC Model chart series is removed and a chart data-status strip is added; Battery outlook,
    # Today so far and Coming up cards use existing entities; reserve wording separates the ECCO setting from the modelled
    # need; the 7-day outlook score reads the entity ids that exist. Display only: no control path, firmware, package or
    # automation changed. It is STAGED: tested_in_home_assistant stays false. The 7.21.0 record follows.
    # v7.21.0 (FE1) shows the batteries' time to reserve: the Overview Energy Flow card's battery node reads
    # sensor.ecco_battery_time_to_reserve (nodes.battery.time_to_reserve) and the battery estimate card adds its
""")
VERSION_EDITS = (
    (VERSION_0_OLD, VERSION_0_NEW),
)

def pre_ovw2_version(text: str) -> str:
    """VERSION.yaml with exactly ovw2's edits undone (a frozen reverter of chain entry ovw2, PEX)."""
    return _revert(text, VERSION_EDITS, "VERSION.yaml")


pre_ovw2_version.edits = VERSION_EDITS   # the PEX contract: a reverter exposes its exact (before, after) pairs


def add_ovw2_version(text: str) -> str:
    """Applies ovw2's VERSION.yaml edits to the earlier text (the round trip)."""
    return _apply(text, VERSION_EDITS, "VERSION.yaml")

# Every frozen file ovw2 edits, with its reverter (the chain entry's frozen_reverts).
FROZEN_REVERTERS = {
    DASHBOARD_REL: pre_ovw2_dashboard,
    VERSION_REL: pre_ovw2_version,
}
