# ECCO Intelligence V1: card UI design

Status: design reference (2026-10-05). Nothing here is deployed, registered or wired to Home Assistant.
Companion mock (open it from `file://`, no network): `docs/intelligence/mockup/ecco_intelligence_card_mockup.html`.
Related prototype, built separately: `home-assistant/prototypes/intelligence-v1/` (Lovelace YAML view plus a frozen-data
template-sensor package). This document and the mock are the card-level reference; the YAML view is the quick dashboard test.

## 1. Purpose

ECCO Intelligence V1 is a shadow-only decision-support layer: read, learn, predict, recommend, score. The card answers
three questions in order, in plain English first and numbers second:

1. What does ECCO expect to happen? (demand, solar, battery level)
2. What would it advise? (overnight charge target, safe export, Saving Session cover)
3. How far should I trust that? (confidence, past accuracy, what is uncertain)

It never controls anything. The deterministic ESP safety layer stays in charge; the card shows advice only.

## 2. Information hierarchy

Top to bottom on every screen size (mobile is the same order, one column):

| # | Section | Job | Default state |
|---|---|---|---|
| 0 | SHADOW banner | Say, on every state, that nothing is applied | always visible, never collapsible |
| 1 | Header | Title, status pill, report time and age, model version | visible |
| 2 | Status callout | Only when status is not `LEARNING_NORMALLY`, or the report is old | conditional |
| 3 | "ECCO expects..." | 2 to 4 generated sentences, then one violet "Shadow advice" paragraph | visible |
| 4 | Actual | SOC, house load, PV, grid, measured now | visible |
| 5 | Battery chart | Predicted SOC path against floor, comfort, cheap window, sun | visible, table twin |
| 6 | Predicted | Demand ranges, solar with learned correction, battery points | visible; "More windows" collapsed |
| 7 | Recommended | Target, grid charge, safe export, Saving Session, disabled Apply | visible |
| 8 | Confidence | Label, 0 to 1 score, why it is not High | visible |
| 9 | Unusual load | Neutral anomaly strip | visible |
| 10 | Why | Engine reasons, uncertainty, assumptions | visible; assumptions collapsed |
| 11 | Technical detail | Hashes, weights, per-forecast and PV source tables, raw JSON | collapsed |
| 12 | Learning and accuracy | Status pill, 7-day table, last-14 predicted vs actual, insights | visible |

Rule: a reader who stops after section 3 must already have the headline and its caveats.

## 3. Vocabulary: Actual, Predicted, Recommended, Confidence

Four words, never interchanged, each with its own shape and texture so colour is never the only cue.

| Word | Meaning | Chip | Numbers in prose | Charts | Blocks |
|---|---|---|---|---|---|
| Actual | Measured by a sensor now | filled ink square, solid chip | bold, plain | solid dot or square, solid rule | solid 5px left rule |
| Predicted | The model's expectation | hollow circle, dashed chip | `~` prefix, bold, dashed blue underline | dashed line, hatched ribbon, hollow dot | dashed border |
| Recommended | Shadow advice, not applied | violet diamond, "shadow, not applied" | bold violet, soft highlight | violet diamond marker | violet border, striped Apply |
| Confidence | How much to trust the above | three-bar glyph, outlined chip | none (a word and a 0 to 1 score) | none | double top rule, scale with words |

Hard rules:

- A prediction is never written into an Actual number. Actual tiles read only the measured fields.
- Every predicted figure carries `~` and, where a band exists, its p10 to p90 range.
- Palette marks were run through the dataviz validator: blue (predicted), red (floor), violet (recommended) pass CVD and
  normal-vision separation in both modes. Meaning also rides on shape: dashed vs solid, hollow vs filled, labelled lines.
- The hatch on predicted bands is semantic, not decoration: it is the "this is not measured" texture, 45 degrees only.
- Precision: SOC to whole %, kWh to 0.1, totals of 20 kWh or more to whole kWh (their typical miss is several kWh).
- A forecast labelled LOW is greyed and says why. INSUFFICIENT shows "No estimate yet"; the raw numbers live only in
  Technical detail. Nothing is rounded to look more certain than the label.

## 4. Status states and exact copy

The pill is always in the header. Title and body show in a callout for every state except `LEARNING_NORMALLY`.
`{n}` is `confidence.history_days`; `{x}` is `pv.today_reanchor.live_ratio` as a whole percent; `{m}` is `actual.soc_age_s` in minutes.

| Status | Pill | Callout title | Callout body |
|---|---|---|---|
| `LEARNING_NORMALLY` | Learning normally | none | none |
| `LEARNING` | Still learning | Still learning | {n} days of history so far. Forecasts are usable but their ranges are wide. ECCO reaches full confidence at 28 days. |
| `INSUFFICIENT_HISTORY` | Not enough history | Not enough history yet | {n} of the 7 days ECCO needs. It is not forecasting yet: greyed numbers are placeholders, and the cautious advice is simply to keep the battery charged. |
| `ABNORMAL_DAY` | Abnormal day | Abnormal day | House load is well above its normal pattern. ECCO is treating today with extra caution: safe export is cut and confidence is lowered. It does not know the cause. |
| `DATA_STALE` | Data stale | Data is stale | The battery reading is {m} min old. ECCO is withholding export advice and trusting its forecasts less until fresh data arrives. |
| `PV_UNDERPERFORMING` | Solar under-performing | Solar is under-performing | Solar is running at {x}% of ECCO's corrected forecast so far today. The rest of today's solar estimate has been scaled down to match. |

Card-side states, independent of the engine status (the engine may be down):

| Condition | Copy | Effect |
|---|---|---|
| Report older than 30 min | "Report is {age} old. ECCO normally publishes every few minutes. The figures below describe the time of the report, not now." | quiet callout |
| Report older than 3 h | "Report is {age} old. Predictions and advice are greyed because they may no longer apply. Check that the ECCO Intelligence job is still running." | Predicted, Recommended and chart greyed to 50% |
| `mode` is not `SHADOW` or `applies_nothing` is not `true` | "Report is not marked shadow-only. The card hides all advice." | everything below the header hidden |
| Entity `unavailable` / `unknown` | "ECCO Intelligence is not publishing." | empty state, banner stays |

The 30 min and 3 h thresholds are proposals to confirm against the real publish interval.

## 5. Card layout

Container-query layout (the card, not the viewport, decides), like the existing ECCO cards. Breakpoints 560, 760, 900.

The figures in this wireframe are illustrative. The mockup in `docs/intelligence/mockup/` is generated from the current
synthetic examples (`intelligence/tools/make_examples.py`) and shows the real engine output.

```
SHADOW MODE - advice only, nothing is applied          (full-bleed violet band, hatched edge)
ECCO Intelligence  [Learning normally]      Report from 21:30 today, 2 min ago   intel-v1.0.0-shadow
[status callout, only when not LEARNING_NORMALLY]
ECCO expects the house to use about ~8.7 kWh overnight (range 7.2 to 10.6) ...          serif prose
| Shadow advice, not applied: Charge to 100% in the cheap window ... 1.0 kWh exportable
+- ACTUAL ---------------------------------------------------------------------------+
|  Battery 62% [====|  ]   House load 2.1 kW   Solar 4 W   Grid (live sensor)         |
+- PREDICTED battery path (chart) ---------------------------------------------[table]+
|  100% ....____.                                                                      |
|   45% ..........  comfort     hatched ribbon, dashed median, solid dot = now         |
|   40% ==========  min. reserve    [cheap window]     sunrise  sunset  useful solar    |
+- PREDICTED (7 cols) ------------------------+ +- RECOMMENDED (5 cols) ---------------+
| Next hour / Until useful solar / Overnight /| | Charge to 100%   typical 70 / poor 100 |
| Whole day  (bar = p10..p90, dot = p50)      | | Grid charge yes, 16 kWh                |
| Solar: Solcast says 42; ECCO expects ~23 x0.55| | Safe export 1.0 kWh (or why withheld) |
| Battery points if advice followed           | | Saving Session cover                   |
+---------------------------------------------+ | [ Apply recommendation ] (disabled)    |
                                                +- CONFIDENCE ---------------------------+
                                                | High 1.00  [scale]  why not High      |
+- Unusual load -------------------------------------------------------------------------+
+- Why: reasons | what is uncertain | assumptions | Technical detail -------------------+
+- Learning and accuracy: pill, 7-day table | last-14 predicted vs actual chart --------+
```

On a 375 px card everything stacks in the section order of section 2; the chart redraws at the card width.

### Shadow safety UI

- Banner text is exactly `SHADOW MODE - advice only, nothing is applied`.
- The Apply control is a visibly disabled mock: `aria-disabled="true"`, dashed striped fill, lock icon, a `title`, and
  the visible caption "Not connected: ECCO Intelligence never writes to the inverter. The deterministic ESP safety layer
  stays in charge." It stays focusable so screen-reader users can reach the explanation. It has no click handler.
  The real card must ship with no write path at all (no `callService`, no `button.press`, no switch toggle).

## 6. Chart and accuracy visuals

SOC chart (inline SVG, hand-written, redrawn on resize): dashed median, hatched pessimistic-to-optimistic ribbon (the
engine's `soc_low` and `soc_high` are its pessimistic and optimistic paths, close to but not exactly p10 and p90), solid
red minimum-battery-reserve line (the effective minimum from `recommended.reserve`; 40% by default), dotted comfort line (effective minimum + margin), shaded cheap window, sunrise and sunset glyphs, a useful-solar bar (p50 with
early and late whiskers), a violet diamond at the recommended target, a solid dot for the actual SOC at "now", and a marked
poor-case minimum when it dips below the floor. Hover or arrow keys show a tooltip; "Show table" swaps in the same data as a
table. Accuracy chart: per day a hatched band (predicted range), hollow dot (predicted), solid square (actual), and a
red ring plus bold day label when the actual falls outside the range. Under-coverage is flagged in words ("misses often").

## 7. Home Assistant entity contract

Five read-only sensors, all `mode: SHADOW` (generated by `intelligence/tools/render_ha_prototype.py`, which is the
single source of the mapping). The card must treat the attribute names below as a versioned API.

| Entity | State | Attributes (compact) |
|---|---|---|
| `sensor.ecco_intelligence_status` | engine status (`LEARNING_NORMALLY`, ...) | `mode`, `applies_nothing`, `generated_for`, `model_version`, `config_hash`, `confidence{overall,label,usage,pv,history_days}`, `notes[]`, `reasons[]` (texts), `reason_codes[]`, `anomaly_flags{abnormal_load_now,excess_kw_now,base_load_kw,base_load_norm_kw}`, `uncertainty[]`, `assumptions[]`, `anomalies[]`, `floor_pct`, `desired_min_pct`, `weekday_effect` |
| `sensor.ecco_intelligence_predicted` | whole-day kWh (p50) | `forecasts{kind:[p10,p50,p90,label,n_residuals,coverage,notes[],window_start,window_end]}` (**null when the engine marks a forecast unusable, i.e. INSUFFICIENT: the card must show nothing for it**), `pv_days{date:{source,raw,ratio,p10,p50,p90,label,notes}}`, `day_so_far_kwh`, `day_projection_kwh`, `useful_pv_start{p50,early_p10,late_p90}`, `sunrise`, `sunset`, `next_sunrise` (the one `soc_at_sunrise` refers to), `pv_reanchor_today{live_ratio,weight,factor}` |
| `sensor.ecco_intelligence_recommended` | target SOC % | `target{recommended_target_soc_pct,median_case_...,pessimistic_case_...,feasible_on_pessimistic_path,grid_charge_needed,grid_charge_kwh_median,window[],expected_import_...}`, `predicted_soc{}`, `safe_export{kwh,withheld_because?,reduced_for?,net_value_p_per_kwh?}`, `saving_session`, `status` |
| `sensor.ecco_intelligence_trajectory` | number of points | `points[[iso,median,low,high],...]` |
| `sensor.ecco_intelligence_accuracy` | 7-day day-load MAE (kWh) | `last_7_days{kind:{n,mae,rmse,bias,coverage,band_nominal,...}}`, `series_last_14{kind:[{t:'MM-DD',p:predicted,lo,hi,a:actual,ok:inside-band}]}` (compact rows, to stay under the 16 kB attribute limit), `error_sign` (error = actual − predicted; positive bias = under-forecast), `insights[]` |

Conventions: ISO-8601 UTC timestamps; the card formats in `Europe/London`. Report age is `now - status.generated_for`
(never `last_changed`, which is unrelated to when the engine ran). Frozen-prototype attribute `frozen_sample: true` makes the
card (and the YAML view) label the data "FROZEN SAMPLE".

Size (HA drops attributes past 16 KB from the recorder and logbook): measured on the example reports, status 1.2 to 1.5 KB,
predicted 1.4 KB, recommended 1.1 to 1.2 KB, trajectory 1.2 to 1.8 KB, accuracy 7.4 KB (three series). All well under
16 KB; accuracy has the least headroom (a fourth series, about 9.9 KB). Keep numbers at 2 decimals, never add the raw
trajectory or `expert_preds` to attributes, and keep the full report in a file or the engine's own store for technical detail.

ACTUAL is not in this contract on purpose: the card reads live entities named in its config (battery SOC, house power,
PV power, grid power, SOC age), so the Actual block is never a stale copy from a report.

### Contract gaps found while building the mock

The mock reads the full engine report; against the compact contract the real card would lose these, so decide whether to add them:

1. Per-forecast `notes` and `t0`/`t1` are dropped by `band()`. The card needs the notes to say why a LOW or INSUFFICIENT row is
   grey ("only 4 days of history: below the 7-day minimum"). Suggest adding `notes` for LOW and INSUFFICIENT rows only, plus window ends.
2. `pv.today_reanchor` (live ratio, weight, factor) is dropped; add it to `predicted` for the PV_UNDERPERFORMING copy.
3. `reasons` drops codes; keep `{code,text}` (about 40 bytes each) so the card can group and label them.
4. `anomalies` has no `base_load_kw` / `base_load_norm_kw`; the "base load 0.7 kW against a normal 0.7 kW" line is lost.
5. `feature_hash` and `forecast_records` are not published; Technical detail shows them as "not present".
6. *(resolved in the contract)* `series_last_14` now includes `load_kwh:morning`, `reason_codes`, `anomaly_flags`, `pv_reanchor_today`, per-forecast notes/window times and `next_sunrise`; INSUFFICIENT forecasts are `null`; PV confidence now drops when its band recently failed (the mock's 'HIGH with 43 % coverage' case); the sign convention is stated in the payload.
7. No grid power in the engine's `actual` (the live entity covers it).

## 8. Where it sits on the dashboard

`home-assistant/dashboards/ecco_pro.yaml` already has a view `Intelligence` (`path: ecco-intelligence`, `sections`,
`max_columns: 4`). The intended placement is the card as the first, full-width (`column_span: 4`) section of that view, with
the existing intelligence cards below it as the comparison the owner already trusts. The new `Fallback / Recovery` view
(`ecco-fallback-recovery`) is unrelated and untouched. Card styling follows the shared `&ecco_card_mod` ground
(`#0d1728`, 18px radius, Roboto / Segoe UI); the card adds a light theme and uses `getGridOptions()` full width.

Until the card exists, `home-assistant/prototypes/intelligence-v1/ecco_intelligence_v1_prototype_dashboard.yaml` is the
standalone preview (one view, button-card and apexcharts-card, frozen sensors from `ecco_intelligence_v1_mock_package.yaml`).
It is read-only (tap actions none or more-info) and not in `deployment/ha-manifest.yaml`. Neither prototype file nor this mock
should be deployed without an owner decision. The custom card replaces the YAML view's repeated button-cards with one
component that owns the vocabulary, the sentences and the chart.

## 9. Implementation notes: vanilla-JS custom card

Follow `frontend/ecco-fallback-recovery-card` (read its README and the header of `ecco-fallback-recovery-card.js`):

- One dependency-free ES module (`ecco-intelligence-card.js`): no build step, no npm packages, no network, no CDN, no web fonts.
  Registers `ecco-intelligence-card` once (guarded `customElements.get`) and pushes a `window.customCards` picker entry.
- Same file layout: constants and config validation; parsing; decoders and text tables (every user-visible string in one
  place); `deriveModel`; pure HTML-string renderers; the custom element. All of it except the class is exported for tests.
- Every entity id comes from config (`validateConfig` throws an error naming the key); the card spells no id. Config:
  `entities.status`, `predicted`, `recommended`, `trajectory`, `accuracy`, and live `actual` entities (`soc`, `load`, `pv`, `grid`, `soc_age`).
- `setConfig`, `set hass` with a fingerprint of the five entity `last_updated` and attribute sizes so unchanged data does not
  re-render, `getCardSize`, `getGridOptions`, `connectedCallback` / `disconnectedCallback` (drop the resize observer and timers).
- Read-only by construction: no service calls, no `isTrusted` write paths. The disabled Apply control has no handler.
- The prose generator is a pure function `narrative(model)`; the mock's function of the same name is the reference. Never
  hardcode a scenario; every number comes from the model and passes through the rounding helpers.
- Escape every engine string (`esc`), use `textContent` for tooltips. Charts are SVG strings sized from the card width.
- Time: `Intl.DateTimeFormat` with `Europe/London`; shift sunrise and useful-PV times by whole days to the next occurrence.
- Theme: CSS custom properties; `prefers-color-scheme` with a `data-theme` override; in HA read `hass.themes.darkMode`.
- Accessibility: landmark per block, real buttons, visible focus, chart is a focusable group with arrow-key stepping and a
  table twin, `aria-live` tooltip, `forced-colors` safe, no motion.
- Node-testable core: keep date and number formatting injectable (`makeFormatters({locale,timeZone})`) like the fallback card.

## 10. Test plan

Same approach as `frontend/ecco-fallback-recovery-card/test/`: `node --test test/*.test.mjs`, a tiny DOM stand-in (`minidom.mjs`),
fixtures from this folder's `examples/*.json` run through `render_ha_prototype.py` to produce the five-sensor state.

| Area | Tests |
|---|---|
| Contract | every example maps to the five sensors; attribute JSON under 16 KB; missing or `unavailable` entities give the empty state; `mode != SHADOW` hides advice |
| Rounding | SOC whole %, kWh 0.1, 20 kWh and over whole; `~` prefix on every predicted figure; no `NaN`, `undefined`, `null` in rendered text for any fixture |
| Vocabulary | Actual tiles never contain a predicted value; Predicted figures carry the dashed class; Recommended figures carry the violet class |
| Narrative | per fixture, golden sentences (normal evening, summer no-charge, cold start, live inputs); no sentence mentions a number absent from the model |
| Status | all six statuses plus old-report and mode-guard states: pill text, callout title and body match section 4 exactly |
| Honesty | LOW and INSUFFICIENT rows greyed with a reason; INSUFFICIENT shows no p50; safe export shows `withheld_because` and `reduced_for` |
| Safety | rendered DOM has no enabled button besides view toggles; Apply has `aria-disabled="true"`, the caption text, no listener; the module source contains no `callService` / `button.press` |
| Chart | point count, floor and comfort lines at the right Y, window rectangle at the right X, sunrise shifted into range, below-floor poor-case marker present when `soc_low < floor` |
| Accuracy | 7-day table rows, "misses often" flag at coverage below 60%, empty insights text, last-14 outside-range count |
| Time | BST and GMT fixtures render the local window `00:30 to 05:30` |
| A11y | every chart has a name, a table twin and keyboard stepping; contrast of the token pairs in both themes |
| Visual | screenshot at 375 px and 1000 px, both schemes, for each scenario (manual for now) |

Add synthetic fixtures for ABNORMAL_DAY, DATA_STALE and LEARNING from the mock's `mutate()` so those states are covered
until the engine emits them.

## 11. What is real and what is mocked

Engine output (unchanged, on a SYNTHETIC household; regenerate with `intelligence/tools/make_examples.py`): everything in the six `examples/*.json` reports and `example_accuracy_history.json`: all
forecasts and bands, PV ratios and notes, reasons, assumptions, trajectory, floor and comfort levels, confidence, model
version and hashes, the accuracy table and the last-14 series.

Computed in the mock's JS from that data: the sentences, rounding, local-time formatting, sunrise and useful-PV day shifts,
confidence "why not High" lines, accuracy flags.

Mocked:

- Synthetic state demos: Still learning, Abnormal day, Data stale and Saving Session are example reports edited in JS
  (`mutate()`), always labelled "synthetic state demo". The "Force state" control applies the same edits to any scenario.
- Report age is a dropdown (2 min, 40 min, 4 h); in the real card it comes from `generated_for`.
- Actual values come from the report's snapshot; the real card reads live entities. Grid power has no value in the mock.
- The accuracy history is an illustrative walk-forward replay on a synthetic household (its own `_description` says so), not live scorecard data.
- The Apply button is a disabled prop. Theme toggle, scenario switcher and the "Mock controls" panel are not part of the card.
- Wording (status copy, section names) is a proposal for owner review.

## 12. Minimum Battery Reserve (a setting, design only)

The reserve is the user's own number, not a project-wide constant. The card and the configuration area should show:

| Label | Source | Notes |
|---|---|---|
| **Minimum Battery Reserve** | `recommended.reserve.user_reserve_pct` | Default **40 %**; each installation chooses its own (0-95 % is accepted, see ARCHITECTURE §8). |
| Technical minimum | `recommended.reserve.technical_min_pct` | Hardware constraint (ideally the inverter's battery shutdown SOC). Not user-facing preference. |
| Effective minimum | `recommended.reserve.effective_pct` (also `floor_pct`) | `max(reserve, technical minimum)`, raised by any HA reserve. This is the red line on the SOC chart. |
| Why | `recommended.reserve.override_reason` | Shown only when something overrides the user's number, e.g. "You asked for a 20% minimum battery reserve, but this battery/inverter needs at least 25%, so 25% is used." The same text is a `TECHNICAL_MIN_OVERRIDES_USER_RESERVE` reason. |

Local prototype only: the prototype dashboard and the card mockup display these values read-only. There is no apply button, no
service and no live entity for editing the reserve in this change; how the setting is edited (profile file, an HA helper, a
config-flow) is a later owner decision (O-1). The same effective reserve is intended to be the single value later
modules (dynamic charge, Dump-to-Grid, Saving Session optimisation, `intelligence_bridge`, modular battery control) read.
