# ECCO Intelligence card

A dependency-free, **read-only** Home Assistant Lovelace card for ECCO Intelligence **SHADOW** advice: the output contract
`ecco-intel-entities/1` (`intelligence/advisory_contract.py`). It shows what ECCO Intelligence would advise and why, and
**applies nothing**. The deterministic ESP safety layer stays in charge of the inverter.

Status: source only. Nothing here is installed, registered or connected to Home Assistant. Licence: GPL-3.0-or-later (the
repository's licence); the card contains no third-party code.

## What it shows

- a `SHADOW MODE - advice only, nothing is applied` banner, a `SHADOW` badge, the status pill, the report age and, while
  `next_run_at` is still ahead, the next refresh time ("next refresh HH:MM": the earliest moment the next cycle can start);
- the status callout, with the exact copy of `STATUS_COPY` / `NOTICE_COPY` in the module (see `docs/intelligence/UI_DESIGN.md`
  section 4);
- the **next charge target** (shadow advice, not applied), or **No advice** with the blocker texts;
- overnight demand, the export event and Dump to Grid advice items (a figure only when the item is OK);
- the forecasts: demand for the day with its p10 to p90 range, solar tomorrow with its range, the predicted morning battery level;
- the tariff: its cheap window and price range only when the tariff block's provenance is `VERIFIED` or
  `VERIFIED_FROM_INTEGRATION`, otherwise **Tariff not verified**;
- an estimated value (GBP) only when the value block has a range and assumptions (which the contract allows only with a
  verified tariff and an OK charge target);
- data quality and the input ages;
- a **Details** drill-down: reasons, confidence per item, blocked conditions, the open decisions by their I-D label
  (I-D1 .. I-D9) and recent accuracy;
- the watchdog (`binary_sensor.ecco_intel_watchdog_fresh`) and the pause helper's state.

## The guards (fail closed)

1. Advice is rendered only when `sensor.ecco_intel_status` carries the `contract_version` `ecco-intel-entities/1`, a non-blank
   `integration_version` (spaces only is blank), `mode: SHADOW`, `applies_nothing: true`, `kind: status`, and a known status. Anything else (a
   newer contract, the frozen V1 prototype's shape, a wrong mode) shows one fixed notice, **Intelligence output not
   recognised**, and nothing from the output.
2. The null rule: no figure for a BLOCKED, INSUFFICIENT_DATA, NO_ADVICE or WITHHELD item, and none at all under STALE, PAUSED,
   SELF_TEST_FAILED or STARTING. The last good values (`last_good`) appear only in a collapsed block labelled
   **History: last good result from ...** and "Not current advice".
3. A figure also needs the item entity's own contract fields and kind, its status OK, a finite state, the same
   `generated_at` as the status, and the card's clock at or before both validities. Past the status `valid_until` the card
   shows **Result expired** and no figure, even if the integration has stopped publishing.
4. No figure either, with a **Not current** notice, while the status `generated_at` is more than 120 s (PROPOSED) ahead of
   the card's clock (this device's clock lags, so the validity cannot be checked here) or while the package watchdog
   `binary_sensor.ecco_intel_watchdog_fresh`, which judges freshness on Home Assistant's clock, reads `off`. A missing or
   unknown watchdog leaves the card's own clock checks. The accuracy figures and the data-quality entity count only from
   the same publish as the status (`generated_at` equal). BLOCKED / INSUFFICIENT_DATA rows show no digit at all.
5. Every string from the entities is escaped before it reaches the markup.
6. No write path: no service call, no websocket message, no button press, no `fetch` / `XMLHttpRequest` / `WebSocket`, no
   `eval`, no storage. The card reads `hass.states` only. The **pause** is offered by the dashboard's core tile card on
   `input_boolean.ecco_intel_paused`, never by this card.

## Configuration

Every entity is optional: the defaults are the contract's ids.

```yaml
type: custom:ecco-intelligence-card
title: "ECCO Intelligence"        # optional
entities:                         # optional; each key defaults to the contract id
  status: sensor.ecco_intel_status
  charge_target: sensor.ecco_intel_charge_target
  watchdog_fresh: binary_sensor.ecco_intel_watchdog_fresh
```

Keys: `status`, `charge_target`, `overnight_demand`, `export_event`, `dump_to_grid`, `predicted_day_load`, `pv_tomorrow`,
`predicted_morning_soc`, `accuracy`, `data_quality`, `fresh`, `paused`, `watchdog_fresh`. The frozen V1 prototype's
`sensor.ecco_intelligence_*` ids are refused.

## Installing it (a one-time owner step; not done by anything in this repository)

The standalone dashboard `home-assistant/dashboards/ecco_intelligence.yaml` uses this card. Order:

1. the package `home-assistant/packages/ecco_intelligence.yaml` first (the pause helper and the watchdog), then the ECCO
   Intelligence integration;
2. copy `ecco-intelligence-card.js` to `/config/www/ecco/` and add it as a Lovelace resource of type JavaScript module
   (for example `/local/ecco/ecco-intelligence-card.js?v=0.1.0`);
3. copy the dashboard file, then install its registration package `home-assistant/packages/ecco_intelligence_dashboard.yaml`
   (one `lovelace: dashboards:` entry; the dashboard's header gives the same entry for `configuration.yaml` as the fallback).

`deployment/ha-manifest.yaml` lists the card (a `frontend_assets` stanza, resource registration manual), the dashboard
(`intelligence_dashboard`) and the packages (post-export entry isp1); nothing copies or registers them automatically. The
install runbook (`docs/intelligence/INTELLIGENCE_SHADOW_INSTALL_RUNBOOK.md`, section 4) gives each step.

## Tests

- `node --test frontend/ecco-intelligence-card/test/*.test.mjs` (from the repository root): the pure core, the rendered
  markup over the six golden fixtures in `intelligence/tests/fixtures/advisory_contract/` (read in place), the custom element
  against a small DOM stand-in (`test/minidom.mjs`) and source pins. Local evidence only: CI runs no Node.
- `tools/tests/test_intelligence_card.py`: the static pin suite CI runs (no write or network API, the licence, the attribute
  names against the contract, the default ids, the contract guard, the package and the dashboard).

## Preview

`preview/index.html` runs the real card on the golden fixtures. It needs the repository root served on the loopback
address (the fixtures live outside this folder); its header comment gives the command and the query options.
