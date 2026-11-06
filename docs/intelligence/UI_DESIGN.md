# ECCO Intelligence: card UI design

Status: follows the output contract **`ecco-intel-entities/1`** (`intelligence/advisory_contract.py`, described in
[`INTELLIGENCE_FOUNDATION_CONTRACT.md`](INTELLIGENCE_FOUNDATION_CONTRACT.md)); the header names the next refresh
(section 2), and the 3D Overview link is dropped for v0.1 (section 14). The card
(`frontend/ecco-intelligence-card`), its standalone dashboard (`home-assistant/dashboards/ecco_intelligence.yaml`) and its
package (`home-assistant/packages/ecco_intelligence.yaml`) exist as **source only**: nothing is deployed, registered or wired to
Home Assistant, and none of them is in `deployment/ha-manifest.yaml`. Every Intelligence decision I-D1..I-D9 is OPEN; every
threshold marked PROPOSED is an engineering default, not an owner decision.

**Held out until PR-6 (decision ui-1).** The package and its behaviour suite
(`home-assistant/tests/test_ecco_intelligence_package.py`) are held back: they ship with PR-6; see
[INTELLIGENCE_CONTINUATION_GUIDE.md](INTELLIGENCE_CONTINUATION_GUIDE.md) section 5. Sections 10 and 13 describe them as
they will ship. Until PR-6 the card shows the watchdog and the pause as not installed, and the runtime reports
`PAUSE_CONTROL_MISSING`: not paused, with a WARN, so it still publishes its SHADOW advice.

The V1 design reference of 2026-10-05 (the five `sensor.ecco_intelligence_*` sensors, the mock in
`docs/intelligence/mockup/`, the prototype in `home-assistant/prototypes/intelligence-v1/`) is **superseded** by the contract
and stays frozen; sections 2, 3, 5, 6 and 11 below keep its vocabulary and layout rules, which the card follows.

## 1. Purpose

ECCO Intelligence is a SHADOW-only decision-support layer: read, learn, predict, recommend, score. The card answers three
questions in order, in plain English first and numbers second:

1. What does ECCO expect to happen? (demand, solar, battery level)
2. What would it advise? (next charge target, export and Dump to Grid advice) - or why it gives no advice
3. How far should I trust that? (confidence, data quality, input ages, recent accuracy, the open decisions)

It never controls anything. The deterministic ESP safety layer stays in charge; the card shows advice only, and has no write
path of any kind.

## 2. Information hierarchy

Top to bottom on every screen size (a 375 px card stacks everything in one column):

| # | Section | Job | Default state |
|---|---|---|---|
| 0 | SHADOW banner | Say, on every recognised state, that nothing is applied | always visible (hidden only for an unrecognised output) |
| 1 | Header | Title, `SHADOW` badge, status pill, report time and age, the next refresh | visible |
| 2 | Status callout | The status copy of section 4 (none for OK) | conditional |
| 3 | Next charge target | The charge target as shadow advice, or **No advice** with the blocker texts | visible |
| 4 | Advice items | Overnight demand, export event, Dump to Grid: a figure only when OK | visible |
| 5 | Forecasts | Demand forecast with its p10 to p90 band, solar tomorrow with its band, predicted morning battery; the tariff | visible |
| 6 | Value | Estimated value (GBP), only with a range and assumptions | conditional |
| 7 | Data quality | The data-quality state and the input ages | visible |
| 8 | Details | Reasons, confidence per item, blocked conditions, the open I-D decisions by label, recent accuracy, versions | collapsed |
| 9 | History | `last_good` under a null-rule status, labelled as history with its time | collapsed, conditional |
| 10 | Footer | The watchdog and the pause helper (state only) | visible |

Rule: a reader who stops after section 3 must already have the headline and its caveats.

**The next refresh.** The header ends with "next refresh HH:MM" while the status attribute `next_run_at` is still ahead of
the card's clock, and says nothing once it has passed. `next_run_at` is the earliest moment the next cycle can start
(see [`INTELLIGENCE_HA_RUNTIME.md`](INTELLIGENCE_HA_RUNTIME.md) section 2.2): with refresh before expiry that is usually a
refresh a minute or two ahead, not the next hourly schedule slot, and while the dongle's telemetry poll text is moving the
refresh starts at the first poll after that moment. It is a time, never a promise of advice: the refresh may still give
`BLOCKED`.

## 3. Vocabulary: Actual, Predicted, Recommended, Confidence

Four words, never interchanged, each with its own shape and texture so colour is never the only cue (V1 rules, kept).

| Word | Meaning | In the card |
|---|---|---|
| Actual | Measured by a sensor now | not shown by this card (the live dashboard shows measured values) |
| Predicted | The model's expectation | `~` prefix, dashed underline, blue; the p10 to p90 band beside it |
| Recommended | Shadow advice, not applied | violet, with the words "shadow advice, not applied" |
| Confidence | How much to trust the above | the item's confidence label (HIGH / MEDIUM / LOW / INSUFFICIENT), a word, never a colour alone |

Precision: SOC to a whole %, kWh to 0.1, 20 kWh or more to a whole kWh, money to the penny. Nothing is rounded to look more
certain than its label.

## 4. Status states and exact copy

The pill is always in the header; the callout shows the title and body for every status except OK. The copy below is the
card's `STATUS_COPY` and `NOTICE_COPY` (the node tests compare the rendered text with these tables).

| Status (`sensor.ecco_intel_status`) | Pill | Callout title | Callout body |
|---|---|---|---|
| `OK` | Advice ready | none | none |
| `NO_ADVICE` | No advice needed | No advice this time | ECCO Intelligence ran and has nothing to advise for this period. |
| `BLOCKED` | Blocked | Advice blocked | Battery advice is withheld until the conditions below are met. Nothing is applied either way. |
| `INSUFFICIENT_DATA` | Not enough data | Not enough data yet | ECCO Intelligence does not have enough recent data to advise. Figures appear once it has. |
| `STALE` | Stale | Result is stale | The last result is older than its validity. No figures are shown until a fresh result arrives. |
| `PAUSED` | Paused | Paused | ECCO Intelligence is paused with the ECCO Intel Paused switch. It produces no advice until the switch is off. |
| `SELF_TEST_FAILED` | Self-test failed | Self-test failed | ECCO Intelligence failed its start-up self-test and publishes no advice. The failed checks are listed below. |
| `STARTING` | Starting | Starting | ECCO Intelligence is starting. The first result normally follows within a few minutes. |

Card-side states, independent of the engine status (the integration may be down):

| Condition | Copy | Effect |
|---|---|---|
| The status entity is missing, `unknown` or `unavailable` | **ECCO Intelligence is not publishing.** | banner, notice and footer only |
| `contract_version` is not `ecco-intel-entities/1`, `integration_version` is missing, empty or blank (spaces only), `mode` is not `SHADOW`, `applies_nothing` is not `true`, `kind` is not `status` or the state is not a known status | **Intelligence output not recognised** - "This card shows only output of contract ecco-intel-entities/1 that is marked SHADOW and applies nothing. Nothing from this output is shown." | one fixed notice; no banner, no figure, nothing from the output |
| The card's clock is past the status `valid_until` | pill **Expired**; **Result expired** - "This result is past its validity. No figures are shown until a fresh result arrives." | no figure; input ages and accuracy hidden |
| The status `generated_at` is more than 120 s (PROPOSED, the watchdog's `CLOCK_AHEAD_S`) ahead of the card's clock | pill **Not current**; **Result time is ahead of this device** - "This result is timed more than 2 minutes after this device's clock, so its validity cannot be checked here. No figures are shown. Check the clock of this device and of Home Assistant." | no figure; input ages and accuracy hidden |
| The package watchdog `binary_sensor.ecco_intel_watchdog_fresh` reads `off` (it judges freshness on Home Assistant's clock) | pill **Not current**; **Result not confirmed fresh** - "The ECCO Intel watchdog in Home Assistant does not see this result as fresh. No figures are shown until it does." | no figure; input ages and accuracy hidden. A missing or unknown watchdog leaves the card's own clock checks |
| The status reports `pause_control: MISSING` | "The integration cannot see the pause helper (PAUSE_CONTROL_MISSING): install the ECCO Intelligence package." | footer note |

A live result never shows the "Advice ready" pill while its figures are withheld: the pill names why ("Expired" or "Not
current"). A small clock difference (up to the 120 s tolerance) reads "just now", not "in the future".

The status precedence is the contract's: PAUSED > SELF_TEST_FAILED > STALE > STARTING > BLOCKED > INSUFFICIENT_DATA > NO_ADVICE > OK.

## 5. Card layout

Container-query layout (the card, not the viewport, decides): one column below 560 px, the advice items and forecasts in two
columns from 560 px. Theme: Home Assistant's CSS variables (`--primary-text-color`, `--secondary-text-color`,
`--card-background-color`, `--divider-color`) with light fallbacks and a `prefers-color-scheme: dark` accent set;
`forced-colors` safe. No web font, no image, no icon set.

```
SHADOW MODE - advice only, nothing is applied
ECCO Intelligence  [SHADOW]  [Blocked]
Report from Tue 15 Jan, 21:00, 2 min ago · next refresh 21:03
| Advice blocked: Battery advice is withheld until the conditions below are met. ...
NEXT CHARGE TARGET
  No advice
  - I-D1 (Canonical soft planning floor) is OPEN; this item depends on it   (one line per blocker)
Overnight demand ............................ Blocked (see Details for the conditions)
Export event / Dump to Grid ................. Blocked (see Details for the conditions)
FORECASTS
Demand forecast (day) ....................... Blocked
Solar tomorrow .............................. Not enough data
Predicted morning battery ................... Blocked
Tariff ...................................... Tariff not verified
DATA QUALITY: OK   input ages
> Details   (reasons, confidence, blocked conditions, open decisions, recent accuracy)
Watchdog: fresh   Pause: off (change it with the Pause tile)
```

With an OK result the hero reads "Charge to 80%" (violet, "shadow advice, not applied"), the forecasts read for example
"~14.2 kWh (11.0 kWh to 17.5 kWh)", all from the golden synthetic fixture.

## 6. Charts

v0.1 has no chart: the contract publishes no trajectory. The V1 chart rules (dashed median, hatched band, labelled lines,
table twin) apply when a later contract version adds a series.

## 7. Home Assistant entity contract (`ecco-intel-entities/1`)

The card treats these ids and attribute names as a versioned API. The defaults of its `entities:` configuration are exactly
`advisory_contract.ENTITY_IDS` (pinned by `tools/tests/test_intelligence_card.py`):

| Key | Entity | Published by |
|---|---|---|
| `status` | `sensor.ecco_intel_status` | the integration (state = the system status) |
| `charge_target` | `sensor.ecco_intel_charge_target` | the integration (advice item, %) |
| `overnight_demand` | `sensor.ecco_intel_overnight_demand` | the integration (advice item, kWh) |
| `export_event` | `sensor.ecco_intel_export_event` | the integration (advice item, kWh) |
| `dump_to_grid` | `sensor.ecco_intel_dump_to_grid` | the integration (advice item, kWh) |
| `predicted_day_load` | `sensor.ecco_intel_predicted_day_load` | the integration (forecast, kWh, p10 / p90) |
| `pv_tomorrow` | `sensor.ecco_intel_pv_tomorrow` | the integration (forecast, kWh, p10 / p90) |
| `predicted_morning_soc` | `sensor.ecco_intel_predicted_morning_soc` | the integration (forecast, %) |
| `accuracy` | `sensor.ecco_intel_accuracy` | the integration (diagnostic: the 7-day mean error and band coverage of the load forecasts, every scored `load_kwh` kind pooled, not the day load alone; n, the forecasts scored; it lags one slot) |
| `data_quality` | `sensor.ecco_intel_data_quality` | the integration (diagnostic: OK / DEGRADED / BLOCKED / UNKNOWN) |
| `fresh` | `binary_sensor.ecco_intel_fresh` | the integration |
| `paused` | `input_boolean.ecco_intel_paused` | the package (the owner's pause helper) |
| `watchdog_fresh` | `binary_sensor.ecco_intel_watchdog_fresh` | the package (the dead-man watchdog) |

Attributes the card reads (all in the contract's recorded or unrecorded set): `mode`, `applies_nothing`, `contract_version`,
`integration_version`, `engine_version`, `kind`, `status`, `generated_at`, `valid_until`, `next_run_at`, `blockers[{code,text}]`,
`reason_codes[]`, `decisions{"I-D1".."I-D9"}`, `pause_control`, `data_quality`, `tariff{provenance,window,price_range}`,
`value{range_gbp,assumptions}`, `plan{precharge_by,headroom_ceiling_pct,reserve_runout_at}`, `self_test{}`,
`input_ages[{name,age_s,limit_s,status}]`, `last_good{generated_at,values}`, and on the items `confidence`, `advice`, `p10`, `p90`;
on the accuracy entity `coverage_7d` and `n`.

**The null rule, as the card applies it** (the contract's rule, re-checked with the card's clock):

- under STARTING, PAUSED, STALE or SELF_TEST_FAILED no figure at all; `last_good` only as collapsed history labelled
  "History: last good result from <time>" and "Not current advice";
- an item shows a figure only when its own entity carries the contract fields and its kind, its status is OK, its state is a
  finite number, its `generated_at` equals the status's, and the card's clock is at or before both its own and the status's
  `valid_until`;
- no figure at all while a live result is withheld: expired on the card's clock, timed more than 120 s (PROPOSED) ahead of it,
  or the package watchdog reads `off` (section 4);
- a BLOCKED, INSUFFICIENT_DATA, NO_ADVICE or WITHHELD item never shows a number, even if a state were forged numeric, and its
  row carries no digit at all (no condition count; the conditions are listed in Details);
- the accuracy figures and the data-quality entity are used only when their `generated_at` is the status's (the same
  publish); otherwise the accuracy is not shown and the data quality is the status's own `data_quality` attribute;
- the tariff's window and price range only with provenance `VERIFIED` or `VERIFIED_FROM_INTEGRATION`, otherwise "Tariff not
  verified"; the value block only with a two-number range and at least one assumption (and, by the contract, a verified
  tariff and an OK charge target).

The foundation contract states the inner shapes the SHADOW cycle publishes (CCR-INT-1, integration step IP-4b): `tariff.window`
is `{start, end}` (aware ISO-8601, UTC), and `tariff.price_range` and `value.range_gbp` are `[low, high]`. The envelope does not
refuse other shapes, so the card stays tolerant. It reads a window as `{start, end}` or `[start, end]` (ISO-8601 with an
offset), a range as `[low, high]`, `{min, max}` or `{low, high}` of numbers (prices in p/kWh); anything else shows "given, in
a format this card does not read" and no number. The card suite (`tools/tests/test_intelligence_card.py` [10]) runs the
SHADOW cycle with a verified tariff and pins that its tariff, value and plan blocks are in shapes the card reads.

**Superseded:** the V1 prototype's five sensors (`sensor.ecco_intelligence_status`, `_predicted`, `_recommended`,
`_trajectory`, `_accuracy`) and `intelligence/tools/render_ha_prototype.py` stay frozen. The card refuses a configuration that
points at a `ecco_intelligence_*` id, and a prototype-shaped status (no `contract_version`) is "not recognised".

## 8. Where it sits: a standalone dashboard

`home-assistant/dashboards/ecco_intelligence.yaml` is a standalone one-view YAML dashboard. `ecco_pro.yaml` is FROZEN and
live and is not touched. The view holds:

- the ECCO Intelligence card with the contract ids;
- a core **tile** card on `input_boolean.ecco_intel_paused`: the only control, and the only place the pause is offered (the
  custom card never offers it);
- a core **entities** card: the watchdog, the integration's own freshness, the status and the data quality (read-only rows);
- a core **markdown** card as a text fallback that works without the card's resource: status, report time, the open decision
  labels, the watchdog and the pause, with the same contract guard and no figure.

**One-time registration (an owner step).** In this order: the package first, then the integration; then the card's
resource (copy `ecco-intelligence-card.js` to `/config/www/ecco/`, add it as a JavaScript module resource); then the
dashboard (copy it to `/config/ecco/dashboards/` and add the `lovelace: dashboards:` entry its header gives; that entry
needs a Home Assistant restart, which needs its own approval). Each step is reversible by removing it.

## 9. Implementation notes: vanilla-JS custom card

Follows `frontend/ecco-fallback-recovery-card`:

- One dependency-free ES module (`ecco-intelligence-card.js`): no build step, no npm packages, no network, no CDN, no web
  fonts. Registers `ecco-intelligence-card` once (guarded `customElements.get`) and pushes one `window.customCards` entry.
- Layout: constants and configuration validation; parsing and the guards (`att`, `finite`, `parseTime`, `contractFields`,
  `statusGuard`); the text tables (`STATUS_COPY`, `NOTICE_COPY`, `ITEM_LABEL`, `TEXT`); `deriveModel`; pure HTML-string
  renderers; the custom element. All of it except the element is exported for the tests.
- Configuration: `title` (optional) and `entities` (optional; each key defaults to the contract id). `validateConfig` throws
  an error naming the key for an unknown key, a malformed id, a wrong domain, a repeated id or a prototype id.
- `set hass` re-renders only when a fingerprint of the configured entities changes; a 30 s tick re-renders for the report age
  and the validity check; `disconnectedCallback` clears it. Open `<details>` stay open across renders.
- Read-only by construction: the card reads `hass.states` only; there is no `callService`, `callWS`, button, event, fetch,
  storage or timer other than the tick. It renders no `<button>`, link, form or image.
- Every engine string passes through `esc`. Times use `Intl.DateTimeFormat` in `Europe/London` (injectable through
  `makeFormatters({locale, timeZone})` for the tests).

## 10. Test plan (implemented)

| Suite | What it proves | Where it runs |
|---|---|---|
| `frontend/ecco-intelligence-card/test/*.test.mjs` (`node --test`) | over the six golden fixtures `intelligence/tests/fixtures/advisory_contract/{all_open_blocked,synthetic_ok,stale,paused,self_test_failed,starting}.json`, read in place: the exact copy of section 4; no figure for BLOCKED / INSUFFICIENT_DATA / NO_ADVICE items or in STALE / PAUSED / SELF_TEST_FAILED / STARTING (last_good only as labelled history); every advice hidden for a wrong or missing `contract_version` / `integration_version`, a mode other than SHADOW or `applies_nothing` not true, and for the prototype's shape; per-item guards; card-side expiry; tariff, value and plan conditions; escaping; no button or link; the element reads `hass.states` only and calls nothing; the timer's lifecycle | local (CI runs no Node) |
| `tools/tests/test_intelligence_card.py` | the static pins: folder, licence, no write or network API, the attribute names and default ids against the contract, the guard and the null rule in the source, that the held-out package and its suite are absent (decision ui-1; their checks return with PR-6), the dashboard's cards and actions, tokens, the site render, scope | CI (`tools/tests`) |
| `home-assistant/tests/test_ecco_intelligence_package.py` (held out until PR-6, decision ui-1: it ships with the package) | the package's automations driven by `home-assistant/tests/_ha_script_sim.py`: watchdog fresh / stale at the PROPOSED boundaries over the golden fixtures and an oracle (status ages included), SELF_TEST_FAILED, contract mismatch (a blank version included), both also when already published at Home Assistant's start (a restart), a good status at the start quiet, pause and unpause, a start-up that never finishes, a watchdog stuck unknown, an absent or unavailable integration; each automation's keys, triggers, conditions and its one `{action, data}` step pinned; only `persistent_notification.create` with `ecco_intel_` ids is ever called and nothing is written; mutants killed | CI (`home-assistant/tests`), once PR-6 restores it |
| headless captures | `preview/index.html` for the six fixtures at 375 px and about 500 px (headless Chrome clamps its window near 500 px) | local, never committed |

## 11. What is real and what is mocked

Everything the card shows comes from the contract's entities. The golden fixtures are SYNTHETIC (fictional 2030 values) and
not site data. The preview (`frontend/ecco-intelligence-card/preview/index.html`) feeds them to the real card through a
stand-in `hass` that holds only `states`.

## 12. Decisions shown by label

The card lists every decision that is not RECORDED in its Details block, by its display label and title (the titles are
`intelligence/site_decisions.py` `DECISION_TITLES`, pinned):

| Label | Title |
|---|---|
| I-D1 | Canonical soft planning floor |
| I-D2 | Inverter physical protection level |
| I-D3 | Battery capacity authority |
| I-D4 | Capacity mismatch band |
| I-D5 | Efficiency basis |
| I-D6 | Advisory freshness limits |
| I-D7 | Required signals per advisor (retired) |
| I-D8 | Derived house-load cut-over and pre-fix history |
| I-D9 | Clock-change night policy |

The blocker texts the integration publishes name the same labels ("I-D1 (Canonical soft planning floor) is OPEN; this item
depends on it"). Minimum battery reserve (V1 section 12) is now decision I-D1 and is not edited from this card.

## 13. The package: pause, watchdog, alerts

> Held out until PR-6 (decision ui-1): the package ships with PR-6; see
> [INTELLIGENCE_CONTINUATION_GUIDE.md](INTELLIGENCE_CONTINUATION_GUIDE.md) section 5. This section describes it as it
> will ship.

`home-assistant/packages/ecco_intelligence.yaml`:

- `input_boolean.ecco_intel_paused` (no `initial:`; Home Assistant restores the owner's choice). Only the owner toggles it.
- `binary_sensor.ecco_intel_watchdog_fresh`, a dead-man watchdog computed in Home Assistant: on only while the status is
  OK / NO_ADVICE / BLOCKED / INSUFFICIENT_DATA / STARTING / PAUSED, the contract fields match (a blank `integration_version`
  does not), `generated_at` is no older than 2700 s and no more than 120 s ahead (both PROPOSED), `valid_until` (when present)
  has not passed, and a STARTING status has not lasted longer than 2700 s (by the status entity's `last_changed`: a start-up
  that never finishes is not fresh even when each STARTING publish carries a new `generated_at`).

  **Changes PR-6 brings (the package half of the SHADOW v0.1 completion).** With refresh before expiry a healthy result is
  never older than the refresh ceiling plus the cycle budget, so the 2700 s limit becomes `WATCHDOG_MAX_AGE_S` = **1200 s**,
  derived from the integration's constants (the 900 s validity ceiling + one 60 s tick + the 120 s time budget + two ticks;
  the package suite pins the formula); `valid_until` is required for a computed status; PAUSED counts as fresh only while
  the pause helper is on (plus 130 s); STARTING is bounded by the same 1200 s. `ALERT_AFTER_S` (1800 s) and `CLOCK_AHEAD_S`
  (120 s) stay. The raise-only reserve helper ships in its own package, `ecco_intelligence_prefs.yaml`, never in this one.
  All PROPOSED.
- Three automations that only call `persistent_notification.create` with a fixed `ecco_intel_` id, each with exactly one
  action:
  - stale: the watchdog not-on (off, or unknown after a template fault) for a PROPOSED 1800 s, the pause not on and unchanged
    for 1800 s (an unpause gives the next cycle time to publish), the integration installed, and neither fault below;
  - SELF_TEST_FAILED: when the status turns SELF_TEST_FAILED, **and at Home Assistant's start when it already is**;
  - contract mismatch: when the status starts not matching the contract, **and at Home Assistant's start when it already
    does not**.

  The start triggers exist because persistent notifications do not survive a restart, a template trigger that is already
  true when Home Assistant attaches it is armed without firing, and a state trigger fires only on a later change: without
  them a fault that persists across a restart (the integration upgraded out of step with this package) would raise nothing.
  Each start trigger re-checks the same fault in its condition, so a start with a good status is quiet. Residuals, stated and
  not alerted: the watchdog entity itself missing (it is in the same package), and an automation reload while a fault
  persists (no second notification; the first is still shown, since notifications survive a reload).

  Nothing dismisses a notification; there is no recorder block and no other write.
- **Install route.** The package and the dashboard are not in `deployment/ha-manifest.yaml`, so the deploy bundle never copies
  them, and the deploy preflight renders both (the site render's YAML globs) but stages neither. The single-file
  `tools/deploy-ha.ps1` has no manifest gate: given either file by name as `-Source` it copies it (packages to
  `/config/packages/`, dashboards to `/config/ecco/dashboards/`). So the install runbook must name that route explicitly, as
  its own approved step, package first; `tools/tests/test_intelligence_card.py` keeps the dashboard rendering byte-identical
  under the site render, so it cannot break the dashboard preflight. The same check for the package left the card suite
  with the package (decision ui-1), and PR-6 restores it.

## 14. Linking the 3D Overview card to this card: dropped for v0.1

Dropped. The SHADOW v0.1 engineering defaults drop the link, so PR-6 carries no Overview change.
`home-assistant/dashboards/ecco_pro.yaml` is FROZEN and live and stays untouched, and so does the 3D Overview card, and
no site-protected dashboard is part of this work.

What was proposed, for the record: the 3D Overview card's status block would have shown one read-only line taken from
`sensor.ecco_intel_status` and the charge target under this card's contract guard and null rule, with a tap opening the
standalone dashboard. Reopening it is a new change to a frozen, live dashboard, on the owner's choice (a post-export pull
request), never part of the SHADOW install. Until then the standalone ECCO Intelligence dashboard is the only place the
advice and the pause are shown, and the Overview is unchanged.
