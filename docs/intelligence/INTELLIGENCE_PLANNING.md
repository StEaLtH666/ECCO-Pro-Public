# Intelligence planning layer (SHADOW v0.1)

> **Offline, SHADOW-only, source only. SYNTHETIC data only.** Nothing here is installed or connected to Home Assistant,
> the dongle, the inverter or InfluxDB, and nothing is ever applied. Every decision I-D1..I-D9 is **OPEN** in the
> repository, so every battery-derived item is BLOCKED there. Every constant marked PROPOSED is an engineering suggestion,
> not an owner value. Every accuracy figure below is measured on SYNTHETIC campaigns; none is a real-data claim.

This document describes the body of the SHADOW cycle (`intelligence/shadow_cycle.py`) and the planning modules it uses:

| Module | What it does |
|---|---|
| [`intelligence/shadow_cycle.py`](../../intelligence/shadow_cycle.py) | `run_cycle(inputs: CycleInputs) -> AdvisoryEnvelope` (frozen signature and envelope schema): the composition below |
| [`intelligence/tariff.py`](../../intelligence/tariff.py) | integration-shaped rate and event payloads -> `VERIFIED_FROM_INTEGRATION` or a BLOCK / NO_VALUE finding |
| [`intelligence/tou_table.py`](../../intelligence/tou_table.py) | the grid-charge classification of the read-only TOU slot table (schema v2, fail closed) |
| [`intelligence/daily_plan.py`](../../intelligence/daily_plan.py) | the charge window, and one planning view around the V1.1 charge target |
| [`intelligence/baselines.py`](../../intelligence/baselines.py) | the baselines and the one energy replay used by the value and the backtest |
| [`intelligence/value.py`](../../intelligence/value.py) | projected savings as a GBP range, only with a verified tariff |
| [`intelligence/backtest_advice.py`](../../intelligence/backtest_advice.py) | leak-free walk-forward backtest of the cycle (SYNTHETIC) |

The contracts it builds on (decisions, gates, freshness, the envelope and its null rule) are in
[`INTELLIGENCE_FOUNDATION_CONTRACT.md`](INTELLIGENCE_FOUNDATION_CONTRACT.md); this layer changes none of them. Its
section 13 (SHADOW v0.1 completion) is the contract for the grid-charge classification, the configuration-poll
freshness, the refresh margin, the TOU claim and the raise-only reserve preference that this layer implements (WP-2;
section 10 below). The V1 / V1.1 modules are reused unchanged (`make_examples --check` stays byte-identical).

## 1. The cycle, step by step

Every step fails closed; the frozen suite `test_intel_shadow_cycle_contract.py` holds for this body.

1. **Paused** -> `paused_envelope` (all nulls). A pause value that is not `True`, `False` or `None` (for example `1` or
   `'on'`) is a broken pause control: `SELF_TEST_FAILED` with `PAUSE_CONTROL_INVALID` (all nulls), never advice.
2. **Quality.** `quality.assess_inputs` re-verifies every input; `quality.prepare_history` gives the learning history
   (none without a satisfied I-D8). Both are called through their frozen signatures.
3. **Tariff.** `tariff.assess_rates` judges `tariff.import_rates` and `tariff.export_rates` (section 2). The import rates
   count as verified only when they cover the whole period the charge window is looked for in
   (`[now, now + PROPOSED_WINDOW_SEARCH_H)`): a payload with only today's rates (tomorrow's not published yet) or only a
   few slots is `NOT_VERIFIED` (`TARIFF_COVERAGE_SHORT`), so it sets no window, no price and no value. The window check
   (step 4) reads the same reading judged without that coverage need, with the same parse, freshness and future-dated
   gates (ENG6-1, contract 13.5 "Which judgement of the import rates"): such a payload names no cheap run, so it never
   sets or confirms the window, but a slot it prices that conflicts with the TOU window still BLOCKs (tighten-only).
4. **Charge window.** `daily_plan.choose_charge_window`: the charge window is always the TOU slot table's single
   grid-charge run, classified fail closed by `tou_table` (section 10.1): the inverter grid-charges only in its slots,
   so no other source can name the window. With a VERIFIED import tariff whose cheap-run analysis names a cheap run,
   every rate slot of the TOU occurrence from now on must be priced in the tariff's cheap band (INFO
   `CHARGE_WINDOW_TOU_INSIDE_TARIFF`; the window is still the TOU window, and the tariff block keeps its provenance and
   prices), otherwise BLOCK `CHARGE_WINDOW_SOURCES_DISAGREE` (rates that do not cover that occurrence BLOCK
   `CHARGE_WINDOW_TOU_UNCHECKED`); a fresh table that does not classify beside a verified tariff that names a cheap run
   BLOCKs `CHARGE_WINDOW_TOU_UNCHECKED` (beside no verified tariff, or one that names no cheap run, the
   `CHARGE_WINDOW_UNKNOWN` result below applies, with the table's own `TOU_*` code), and a verified tariff without a
   fresh table is never a window (`CHARGE_WINDOW_UNKNOWN`). A verified tariff that names no cheap run (its own
   `TARIFF_*` WARN stays) still checks the slots it prices (A35, section 3): a slot of the TOU occurrence from now on
   priced at or above `low` plus `PROPOSED_MIN_CHEAP_SPREAD_P_PER_KWH` BLOCKs `CHARGE_WINDOW_SOURCES_DISAGREE`, where
   `low` is the lowest rate the reading prices from 24 h before now to 24 h after it (the look-back, A38; the slot that
   holds now included). Otherwise it, or no verified tariff, leaves the TOU window with a WARN
   (`CHARGE_WINDOW_FROM_TOU_TABLE`, whose text says which case applies: no verified tariff, every priced slot within the
   spread, or the window not wholly priced), and in the first and the last case with INFO `CHARGE_WINDOW_NOT_PRICED` on
   the charge-window items (A41: no price check covered the whole occurrence; section 3); without a classified TOU
   window, BLOCK (`CHARGE_WINDOW_UNKNOWN`). Never the SiteConfig example window, never an invented period, never an
   overlap of the two sources. Every refusal BLOCKs every item that rests on the window: the charge-window items
   (`charge_target`, `export_event`, `dump_to_grid`, `predicted_morning_soc` and the internal `v1_summary`;
   `site_decisions.CHARGE_WINDOW_ITEMS`) and `overnight_demand`, whose period is the window. The quality layer still
   requires, for every charge-window item, a fresh TOU slot table and a known, small inverter clock offset
   (`CHARGE_WINDOW_UNKNOWN`, `CHARGE_WINDOW_CLOCK_UNKNOWN`, `CHARGE_WINDOW_CLOCK_OFFSET`).
   Before the window is judged, every configuration-poll reading (`site_decisions.CONFIG_POLL_READINGS`: the table,
   the current target, both enables, the shutdown level, the Ah register) is aged by the larger of the telemetry and
   the configuration liveness ages and is never fresh without a fresh configuration liveness (section 10.2;
   tighten-only, the quality layer's own rule applied again).
5. **Gates.** `site_decisions.gate` per item, with the conditional context wired (capacity sources for I-D4; clock
   changes in the lookback and the 48 h horizon, and the TOU / judged window boundaries for I-D9 and the fixed DST
   rule). A decision counts only via `satisfied(decision, accept_provenance)`; the default accepts OWNER_RECORD only.
   Any INVALID decision is a top-level BLOCK and, stricter than the per-item gate, blocks **all** advice
   (`SITE_DECISIONS_INVALID`) until the site decisions file is corrected; `pv_tomorrow` rests on no decision.
6. **Decided configuration.** `site_decisions.apply_to_siteconfig(base, decisions, readings, accept)` with the judged
   window as `readings["charge_window.local_minutes"]` and the grid-charge limit capped at the lowest slot power of the
   TOU run (min of the two: it can only lower it). When it returns None, every battery-derived item
   (`charge_target`, `export_event`, `dump_to_grid`) and `predicted_morning_soc` is BLOCKED. The example capacity,
   efficiency, 40 % reserve, 10 % placeholder, window and 8 kW are never used for anything published.
7. **Forecasts.** The V1 models (`engine.IntelligenceEngine`, its `UsageModel` and `PvModel`) on the prepared history.
   The V1 report (`engine.run`) runs on the **decided** configuration when there is one, otherwise on the forecast-only
   configuration (site facts plus the judged window). Every battery-derived V1 output of a forecast-only run
   (recommended, trajectory, export, floor ETA, SOC forecast records) is discarded before assembly. PV learning uses the
   PV channel only, so `pv_tomorrow` needs no I-D8.
8. **Advisors**, only when the item's gates pass and its inputs are fresh; the item view is `ItemView.from_advice` of
   the V1.1 `Advice` (the single answer format). Non-OK views keep codes and texts only. Published blocker texts are
   fixed phrases (numbers stay in `Finding.evidence`, which is not published); the two upstream texts known to state a
   value (`GRID_CHARGE_LIMIT_UNKNOWN`, `SITECONFIG_INVALID`) are published as the plan's own fixed phrase. A text that
   still carries a value-shaped token (a number with a unit, a decimal, a clock time) is never rewritten piecemeal: the
   whole text is replaced by one fixed sentence and the item and the status carry `PUBLISHED_TEXT_REDACTED` as their
   first reason code, so the replacement is visible. The planning suites assert that no text is redacted on their
   inputs; the guard is a last resort, not the frozen suite's detector.
   The HA reserve helper (`reserve.ha_minimum_soc`) is ACS1's lower bound and raise-only in advice: with I-D1 =
   `HA_RESERVE_HELPER` it is the floor (and every item I-D1 gates carries WARN `DECISION_VALUE_FROM_HELPER`); with any
   other I-D1 source a fresh in-range helper value still raises the effective reserve, never lowers it
   (`HA_RESERVE_HELPER_RAISE_ONLY`; a present but unusable one gives `HA_RESERVE_HELPER_IGNORED`). This reading is
   UNKNOWN for the integrator and the owner to confirm (I-D1). The raise-only reserve preference
   (`pref.advisory_reserve_raise_pct`, section 10.4) enters the same way and can only raise the floor.
   An OK item valid for less than `REFRESH_MARGIN_S` (125 s) at compute time is BLOCKED `INPUT_EXPIRING` (section
   10.3); what rests on it is withheld too. An OK `charge_target` and an OK `predicted_morning_soc` carry exactly one TOU
   claim code (section 10.5).
9. **Blocks.** `tariff{provenance, window, price_range}` (the window is the charge window used, `{start, end}` as aware
   ISO-8601 UTC timestamps, or None: CCR-INT-1; prices only with a VERIFIED tariff **and** an OK charge
   target), `value` (section 5), `plan{precharge_by, headroom_ceiling_pct, reserve_runout_at}` (only with an OK charge
   target), `accuracy` from `outcome_metrics`; `drift` and `calibration` stay None. `engine_comparison` appears only when
   `charge_target` is OK. `scorecard_report` is the V1 report without `recommended` (SOC records only from a decided run)
   and is never published.

The status, its precedence and the null rule come from `advisory_contract.assemble_envelope`; the body never derives
them itself. An internal error gives `SELF_TEST_FAILED`; bad data never raises.

### Items

| Item | Method | Validity |
|---|---|---|
| `overnight_demand` | `overnight.learn_overnight` over the period from the window end to the next window start (local wall clock), on complete past periods only; I-D9: a changed history period is excluded (`EXCLUDE_CHANGED_PERIODS`) or normalised to nominal; a changed target period is scaled to its actual length (`SCALE_TO_ACTUAL`) or only up (`SCALE_UP_ONLY`) | inputs and the charge-window source(s) |
| `charge_target` | `charge_target.advise_charge_target` on the decided configuration: THE target. PV credit = the p10 of the window-end day's PV after the window-end hour, only at MEDIUM or HIGH confidence; the SOC at the window start is predicted with planning (p90) drain, held at the effective reserve | inputs, and at most the window end |
| `export_event` | `events.advise_event` on planning (p90) demand during / after the next joined Saving Session, no PV credit, power limits unknown (household cover only); no reward model. The start SOC (`daily_plan.event_start_basis`): with no charge window before the event, the SOC now; with exactly one window before it (the normal case: tomorrow evening), the plan's window-end SOC, only with an OK charge target and plan (`EVENT_START_FROM_PLANNED_WINDOW_END`); otherwise (an event inside a window, or after two refills) BLOCKED `EVENT_AFTER_REFILL_NOT_MODELLED`. The drain until the event start is taken on the reserve-held account (`EVENT_START_HELD_AT_RESERVE` when the reserve binds); an SOC outside 0..100 is never published (`EVENT_SOC_OUT_OF_RANGE`) | inputs, the event list, at most the event end (and the charge target's validity when it rests on it) |
| `dump_to_grid` | `dump_advice.advise_dump`: refill at the next window start, planning (p90) demand until then, Saving Sessions from the tariff events and the live list | inputs, the event list, at most the refill |
| `predicted_day_load` | the V1 usage forecast of the next local day (00:00-24:00) | history, at most the next local midnight (date-scoped) |
| `pv_tomorrow` | the V1 PV forecast of the next local day from `pv.forecast_tomorrow_kwh` (summary = the V1 `PvForecast.to_dict` keys) | history and the date-scoped forecast |
| `predicted_morning_soc` | from the planned window-end SOC to 09:00 local (PROPOSED anchor) on the forecast load and PV, on the reserve-held account (never below the effective reserve; `MORNING_SOC_AT_RESERVE` when p10 reaches it): p10 from high load and low PV, p90 from low load and high PV, the load band from its own V1 forecast | inputs, at most the window end |

Each OK item is valid from now for at most `PROPOSED_ADVICE_VALIDITY_S` and never longer than the shortest remaining
freshness of what it rests on: its required inputs, its charge-window sources (for `overnight_demand` too, whose
period is the charge window: the TOU table, both enables and the overlay reading, plus the import rates when a
verified tariff checked the window) and, for export and Dump advice, the event list. Whenever any of these is a dongle
input (a dongle signal or reading, such as a window read from the TOU slot table), the dongle liveness reading bounds
the validity as well, so such an item is never valid longer than the quality layer's liveness bound (180 s, PROPOSED)
minus the liveness age, even when I-D6 gives the dongle inputs themselves a longer limit. Whenever any of them is a
configuration-poll reading, the configuration liveness bounds it too (300 s, PROPOSED, minus its age). An OK item with
less than `REFRESH_MARGIN_S` of validity left is BLOCKED `INPUT_EXPIRING` instead, so the envelope, valid until its
first OK item expires, is valid for at least the margin whenever any item is OK.

## 2. Tariff (`intelligence/tariff.py`)

- **Shapes:** the rate events of the Octopus Energy integration. The `SiteReading` value of `tariff.import_rates` /
  `tariff.export_rates` (unit `table`) is a **list of rows** `{start, end, value_inc_vat}`. The site file maps one
  rate event, or two or three day events in day order (A38 Part B, CCR-RT-DAYS: the contract the Home Assistant
  runtime implements, contract section 3). The production site file maps the import rates as `[current day, next day]`
  (A42). The three-event form, with the previous-day event first, is allowed; the previous-day event is added only by
  a later decision, once a readiness read shows its report cadence within its I-D6 limit. The runtime merges the
  events' rows into one list under fail-closed rules (an unpublished or unavailable event contributes nothing, a
  repeated row is collapsed, any other overlap or rows out of order refuse the table, the age is the oldest event's),
  and this adapter's parse, unit and coverage rules apply to that list unchanged. One day-rates event prices one local
  day and covers the 24 h search period only in a cycle at local midnight itself; the day events cover it once the
  next day's rates are published, and price the current day (in the three-event form also the previous day) before
  that. A reading that does not cover the period is not verified for a cheap run, prices or value, and the window
  check compares the TOU occurrence's priced slots with the lowest rate it prices from 24 h before now to 24 h after
  it (section 3, "The look-back" and "What remains on one day-rates event").
  The adapter also parses one event's attributes `{rates, unit_of_measurement}` and `{previous_day | current_day |
  next_day}` directly, but the quality layer accepts only a list for a table reading. Entity ids are site-private and come only from the site-local profile (for example
  `event.your_..._current_day_rates`).
- **Units:** the integration's GBP/kWh x 100 = p/kWh. A magnitude above `PROPOSED_MAX_ABS_GBP_PER_KWH`, or a stated
  unit other than GBP/kWh, is a unit mismatch (BLOCK), never rescaled; so is a payload whose median rate is above
  `PROPOSED_MAX_MEDIAN_GBP_PER_KWH` (`TARIFF_UNIT_IMPLAUSIBLE`: a p/kWh table whose every figure is small). The list
  shape states no unit, so this is a plausibility guard, not a proof: a p/kWh table whose every figure is below the
  median bound would still pass (UNKNOWN; the runtime should prefer the mapping shape with `unit_of_measurement`). Rows
  with a price under another key are refused.
- **Times:** every slot needs a UTC offset; the slots must be contiguous (no gap, no overlap). DST days are covered by
  elapsed half-hours: 50 on a 25 h day, 46 on a 23 h day.
- **Age:** fresh only under a defined limit judged by the quality layer (an I-D6 override; UNRESOLVED is never fresh)
  and never observed in the future.
- **Coverage:** `covers`, `covers_local_day`, `price_range` refuse anything outside the verified slots.
- **Result:** `VERIFIED_FROM_INTEGRATION`, or BLOCK (malformed) / NO_VALUE (missing, stale, coverage short) with a
  finding. It never invents a price. **VAT and the standing charge are UNKNOWN and excluded**: rates are used exactly as
  the payload states them, and the standing charge is the same under every plan compared.
- **Cheap window:** the longest contiguous run (earliest on a tie) within `PROPOSED_CHEAP_BAND_P_PER_KWH` of the
  cheapest rate in the next `PROPOSED_WINDOW_SEARCH_H` hours, at least `PROPOSED_MIN_CHEAP_WINDOW_MIN` and at most
  `PROPOSED_MAX_CHEAP_WINDOW_MIN` long, and at least `PROPOSED_MIN_CHEAP_SPREAD_P_PER_KWH` cheaper than every slot
  outside the cheap band. The rates must cover the whole search period (`TARIFF_COVERAGE_SHORT` otherwise: a cheaper
  run could lie in the part not yet published). So a current-day-only or peak-only payload names no run, and a flat
  or nearly flat tariff names none either (`TARIFF_CHEAP_RUN_TOO_LONG`, `TARIFF_NO_PRICE_SPREAD`). A cheap run is
  never a window by itself: the TOU table always sets the window, and the tariff only checks it (section 3, A30 with a
  named run and A35 without one), else BLOCK. The run found may cross local midnight; it is cut at `now` and at the
  search horizon, so its start and end are never the boundaries a window is checked against.
  `horizon_low_p_per_kwh` gives the lowest rate among the slots that overlap `[now - PROPOSED_WINDOW_SEARCH_H,
  now + PROPOSED_WINDOW_SEARCH_H)`, the search period and the same span before it, whatever slots exist there (the
  `low` of the A35 check, A38; the slot that holds now counts; with a covered period and no cheaper slot in the
  look-back it equals the rate the cheap band starts from). The cheap run and its band never look back.
- **Events:** Saving Session and free-electricity periods; rewards (octopoints) are not read (O-4). The event list
  counts only when it is fresh: the quality layer's judgement when it makes one, else the same rule here (no defined
  limit = never fresh). Without it, export and Dump advice are BLOCKED (`TARIFF_EVENTS_NOT_FRESH`).

## 3. Daily plan (`intelligence/daily_plan.py`)

One planning view around one OK V1.1 charge target; the planner never computes a second target.

- **Planned SOC** at the window end: min(target, what the window can reach), or the predicted window-start SOC when that
  is already above the target (a window charges up to a target, never down to it). The plan is OK only at or above the
  effective reserve plus the safety margin (`PLAN_BELOW_RESERVE_MARGIN` otherwise); a `DailyPlan` that breaks this cannot
  be built.
- **Grid-charge limit:** `limits.max_grid_charge_w` through `apply_to_siteconfig` (never the example 8 kW).
- **Window cross-check (A30):** with a VERIFIED tariff whose cheap-run analysis (`tariff.cheap_window`: search horizon,
  coverage, length, spread) names a cheap run, the TOU occurrence the window refers to (the one `tou_table.grid_window`
  returns), clipped to `[max(now, start), end)`, is checked against the tariff's **rate slots**, never against the cheap
  run's start and end (`cheap_window` finds the run among the slots still running at `now` and cuts it at its 24 h
  horizon, so those boundaries are not the tariff's). Every slot overlapping the clipped occurrence priced at or below
  the cheap band's ceiling (`CheapWindow.ceiling_p_per_kwh`: the lowest candidate rate plus
  `PROPOSED_CHEAP_BAND_P_PER_KWH`) gives the TOU window (the inverter charges only in its slots; the tariff confirms
  every remaining minute of them is cheap), with INFO `CHARGE_WINDOW_TOU_INSIDE_TARIFF`, and its validity rests on the
  import rates, the table, both enables and the overlay reading. A slot above the ceiling BLOCKs
  (`CHARGE_WINDOW_SOURCES_DISAGREE`); slots that do not cover the clipped occurrence BLOCK
  (`CHARGE_WINDOW_TOU_UNCHECKED`); the former overlap rule is deleted. The tariff's cheap run may cross local midnight
  (only the TOU window must lie on one local date; `tou_table` refuses a TOU run across midnight). A fresh table that
  does not classify beside such a tariff BLOCKs (`CHARGE_WINDOW_TOU_UNCHECKED`, with the table's own `TOU_*` code);
  beside no verified tariff, or one that names no cheap run, it BLOCKs `CHARGE_WINDOW_UNKNOWN` with the table's own
  code. When the tariff checks the window, the quality layer's `CHARGE_WINDOW_FROM_TOU_TABLE` WARN is dropped from the
  items (it does not apply). No `CHARGE_WINDOW_*` code is emitted with a severity other than contract 13.8's.
- **Window cross-check without a named run (A35):** a VERIFIED tariff whose cheap-run analysis names no run (the
  search period not covered, no slot ahead, no run long enough, a run too long or no spread: any smooth tariff, or one
  shoulder slot within 2 p of the cheapest rate anywhere in the next 24 h) still checks the slots it prices. `low` is
  the lowest rate among the slots that overlap `[now - PROPOSED_WINDOW_SEARCH_H, now + PROPOSED_WINDOW_SEARCH_H)`
  (`tariff.horizon_low_p_per_kwh`, whatever slots exist; the look-back below); the TOU occurrence is clipped as
  above. Any slot overlapping the clipped occurrence priced at or above `low + PROPOSED_MIN_CHEAP_SPREAD_P_PER_KWH`
  BLOCKs (`CHARGE_WINDOW_SOURCES_DISAGREE`), also when the occurrence is only partly priced. Otherwise the TOU window stands
  with the WARN `CHARGE_WINDOW_FROM_TOU_TABLE`, whose text says "every priced slot of the TOU window is within the
  minimum cheap spread of its lowest rate" or "does not price the whole TOU window" (partly or not priced, no slot
  ahead included), and the tariff's own `TARIFF_*` WARN stays. A tariff that does not price the window gives nothing to
  conflict with, so that alone is no BLOCK here (a named run that does not cover it BLOCKs `CHARGE_WINDOW_TOU_UNCHECKED`
  above). The no-run threshold (2 p) is deliberately wider than the named run's band (0.5 p): a flat tariff passes, a
  smooth Agile-style tariff passes only where the window is within 2 p of `low`, and a plunge price anywhere in the 24 h
  before or after now can BLOCK (fail closed). No PROPOSED value changes. In the cycle "the search
  period not covered" reaches this rule (ENG6-1): the window check is given the import reading judged without the
  coverage need (the same parse, freshness and future-dated gates; step 3), while prices, the tariff block and the
  value keep the need (`NOT_VERIFIED`, `TARIFF_COVERAGE_SHORT`). Tighten-only: the result is this BLOCK or the same
  TOU window with the same WARN.
- **The look-back (A38 Part A; contract 13.5):** `low` reads the window-check judgement's slots (step 3) from 24 h
  before now to 24 h after it. The slot that holds now counts; a slot that ended exactly 24 h before now, or starts
  exactly 24 h after it, does not. Only `low` looks back: the slots checked are those of the clipped occurrence, and the
  named-run path (`cheap_window`, its band and ceiling) never looks back. A lower `low` can only add BLOCKs. Without it,
  `low` on one day-rates event came from the rest of that day only, so a TOU window misplaced to the evening peak stood
  OK once the night's cheap run had passed.
- **Known fail-closed limitation (F2, widened by A38):** a correctly placed window BLOCKs
  `CHARGE_WINDOW_SOURCES_DISAGREE` (no number) although tariff and TOU agree whenever a slot of its occurrence is priced
  2 p or more above the cheapest rate priced in the 24 h before or after now: on the night a cheap rate falls by 2 p or
  more at local midnight (the low comes from the next night; also with a named run, whose band then starts there); after
  a rise of 2 p or more while the reading still prices the old, cheaper slots (without a named run, until the last of
  them is 24 h old; a two-rate tariff whose night rate rises keeps its named run and its window); and, said plainly, on
  a dynamic Agile-style tariff (no named run), on every day whose window slots are 2 p or more above the cheapest slot of
  the previous or the next 24 h that the reading prices: there the charge-window items (charge target, morning SOC,
  export, Dump, overnight demand) are withheld for as long as that cheaper slot stays in the period, which can be many
  cycles of many days. Smaller differences do not. Narrowing the lowest-rate search to the TOU window would be a
  loosening, so it is not done (contract 13.5).
- **What remains on one day-rates event (ENG6-1, ENG6-2, A38; contract 13.5):** with the single form the runtime passes
  the rows of one mapped rate event (section 2). With the look-back, a TOU window misconfigured to the evening peak
  BLOCKs at every cycle until today's occurrence has ended on the current-day event (the night's cheap slots stay in the
  look-back), and once the occurrence is the next day's on the next-day event. A TOU window equal to the cheap run never
  disagrees (`test_intel_daily_plan` [1d] and `test_intel_cycle_planning` pin both). Accepted residual (visible as INFO
  `CHARGE_WINDOW_NOT_PRICED`, below): an occurrence the reading does not price at all has nothing to conflict with and
  keeps the WARN whose text says "... does not price the whole TOU window": on the current-day event from the end of
  today's occurrence until local midnight, on the next-day event alone from local midnight until today's occurrence
  has ended. During those hours an OK charge target does not show that the TOU window lies in the cheap run.
- **With the day events (A38 Part B, the contract the Home Assistant runtime implements; contract 13.5):** the
  production site file maps `[current day, next day]` (A42; the three-event form is allowed, section 2). The current day
  is always priced, so the look-back always finds today's cheap slots, and once the next day's rates are published the
  reading covers the search period, so the window is checked against its whole priced occurrence: by the named run
  (A30), or, for a tariff that names none (for example a flat one), by the A35 spread check. A window misconfigured to
  the evening peak BLOCKs at every cycle of the day (the runtime suite `test_runtime_tariff_days`, the next day's rates
  appearing at 16:00), and the accepted residual is limited to the hours before the next day's rates are published,
  after today's occurrence has ended. Only while the merged table is accepted and fresh: a refused table, a gap
  (`TARIFF_GAP`) or a stale oldest event (`TARIFF_NOT_FRESH`) gives no usable tariff, and the window stands with the
  WARN "no verified tariff" and INFO `CHARGE_WINDOW_NOT_PRICED` (INTELLIGENCE_HA_RUNTIME, risk 8).
- **Only the codes of WARN and INFO findings are published; the residual's code (A41; contract 13.5 and 13.8):** a WARN
  or INFO finding's text stays in the engine, and the published items carry its code only; a BLOCK finding's text is
  published as its blocker text (step 8), but the residual's WARN text is not. The WARN `CHARGE_WINDOW_FROM_TOU_TABLE`
  is the same code for a window whose whole occurrence was priced within the spread and for one that no price check
  covered, so the planning layer adds INFO `CHARGE_WINDOW_NOT_PRICED` on every charge-window item whose window stands on
  the TOU table without a price check of its whole occurrence: no usable verified tariff for the window check, or one
  that names no cheap run and does not price the whole occurrence (the residual above). It is never emitted when the
  whole occurrence was priced within the spread, beside `CHARGE_WINDOW_TOU_INSIDE_TARIFF` or on a refused window,
  carries no number and never blocks. The 72 h technical acceptance and the 7-day recommendation-quality monitoring
  observe the residual by this code: the cycles whose **OK** `charge_target` carries it stood on the TOU table alone
  (`test_intel_daily_plan` [1e] and `test_intel_cycle_planning` [9] pin it). The code is on every charge-window item
  whatever its status, so on a BLOCKED or INSUFFICIENT_DATA item (blocked for another reason) it says only that the
  window was not price-checked; that cycle published no charge advice and is not counted.
- **Grid-charge power:** min(`limits.max_grid_charge_w`, the lowest `power_w` of the TOU run), handed to
  `apply_to_siteconfig`; it can only lower the limit. The register-230 grid-charge current limit is not modelled
  (WARN `GRID_CHARGE_CURRENT_LIMIT_NOT_MODELLED` on `charge_target`, `predicted_morning_soc` and `v1_summary`, no
  number).
- **Precharge timing:** from the V1 advisor's `PRE_WINDOW_RISK` / `PRE_WINDOW_FLOOR` reasons of a run on the decided
  configuration: the first trajectory point before the window at or below the reserve.
- **Headroom ceiling:** the highest window-end SOC from which the conservative path after the window (PV at p10 / p50,
  load at p90 / p50) clips no PV, on the reserve-held account of `baselines.replay` (a PV surplus after a deep drain
  starts from the reserve), found by bisection, rounded up, never below the effective reserve plus margin (when even
  that clips, the ceiling is the reserve plus margin: the reserve comes first). Informational: the target stays the
  authority (`TARGET_ABOVE_HEADROOM_CEILING` is only a reason code).
- **Reserve runout:** when the battery would reach the effective reserve without grid charging (load p50, PV p10).
- **Morning SOC:** the band on the same reserve-held account, so it is never below the effective reserve (to the 0.1
  point it is published at); `MORNING_SOC_AT_RESERVE` when its p10 reaches the reserve.
- **Saving Session energy plan:** `events.advise_event` (section 1), starting from `event_start_basis` and with the
  drain before the event on the reserve-held account (`held_soc_after`, the same rule as the charge target's
  window-start SOC). No reward model (O-4).
- **Cycling cost:** only when `pref.wear_cost_p_per_kwh` is present (a preference does not go stale): the preference
  times the grid charge energy. It is never published as money.

## 4. Baselines (`intelligence/baselines.py`)

| Baseline | Target | Present |
|---|---|---|
| `ALWAYS_100` | the maximum SOC every window | always |
| `HOLD_CURRENT` | `tou.current_target_soc_pct` (read-only) | only with a fresh percentage reading; absent otherwise |
| `V1_CONFIG_WINDOW` | the V1 engine's simulated target on the decided configuration | only when every decision it rests on is satisfied |

`baselines.baselines()` is the one definition: the value block calls it with the cycle's judged readings, and the
backtest calls it with the judgement the cycle itself made at the issue time (`shadow_cycle.judged_reading`), so the
backtest scores exactly the baselines the cycle could have shown. `tou.current_target_soc_pct` is an I-D6 key with no
default limit (CCR-PLAN-1): while I-D6 is OPEN it stays UNRESOLVED, never fresh, so `HOLD_CURRENT` is absent in both;
once a site's I-D6 records a limit, `HOLD_CURRENT` is present whenever the cycle judges the reading fresh (as in the
SYNTHETIC campaigns of section 6, whose synthetic I-D6 gives it 300 s).

**The one energy replay** (`replay`), used by the value and the backtest on the same inputs: inside the charge window the
grid carries the house and charges the battery toward the target at up to the grid-charge limit (PV still reaches the
battery); outside it the battery covers deficits down to the effective reserve, below which the grid carries the house
(peak import; a battery already below the reserve is held, never raised); a PV surplus fills the battery and the rest is
exported. An unconstrained track is kept beside it. How the real inverter slot behaves above its target is UNVERIFIED;
every policy is replayed with the same assumption.

## 5. Value (`intelligence/value.py`) and why no GBP appears without a verified tariff

A money figure needs prices, and a price that is assumed, defaulted or taken from the example configuration would make
the figure an invention. So `project_value` returns **NO_VALUE with a reason** unless the import tariff is
`VERIFIED_FROM_INTEGRATION` and covers at least the charge window; the envelope refuses a value block otherwise, and the
cycle publishes one only with an OK charge target as well.

With a verified tariff: the advice and each baseline are replayed on three forecast scenarios (low load with high PV,
the median, high load with low PV) up to the horizon end (the next window start) or the end of the verified rates,
costed at the verified rate of each step. Energy left in the battery above the reserve at that end is credited at the
lowest and at the highest verified import rate (both kept). Exported PV earns the verified export rate, or anything from
nothing to the highest verified import rate when the export tariff is not verified. The saving against a baseline is
its cost minus the advice's; the published `range_gbp` (against `HOLD_CURRENT`, else `ALWAYS_100`) is the lowest and
highest over the scenarios and valuations, **rounded outward** to `PROPOSED_VALUE_STEP_GBP`. It is a projection, never a
measured saving.

## 6. Backtest (`intelligence/backtest_advice.py`), SYNTHETIC

Walk-forward at 21:30 local on `History.truncated(t)`, with inputs built like the shared fixtures (fresh readings
observed shortly before t; the day-ahead PV forecast as issued that day). Scored against the campaign's own future:

- forecast MAE and the share inside p10..p90 for the next day's load and PV, and for the morning SOC against the replayed
  SOC at its anchor;
- **reserve violations of OK advice:** a feasible OK charge target (binding constraint not `MAX_SOC` /
  `CHARGE_WINDOW`, which state that the reserve may be reached) whose replay goes below the effective reserve after the
  window, and an OK Dump-to-Grid advice whose export, replayed, takes the battery below the reserve before its refill.
  **The acceptance metric counts FEASIBLE OK advice only.** OK targets with a stated shortfall are counted separately,
  and those whose replay reaches the reserve are reported beside the zero (`stated_shortfall_reached_reserve`), so the
  zero is never read as "OK advice never reaches the reserve". Positive controls pin both detectors: an injected unsafe
  OK target is a violation, and a constructed OK Dump view is scored (a breach is a violation, a safe export is not);
- **conservative energy regret:** the advice's import minus each baseline's, replayed on the same actual load and PV
  (positive = the advice imported more);
- **GBP regret** only when the campaign's tariff verified at the issue time (ex post at the realised rates); otherwise
  `NO_VALUE`.

The suite proves the leak-freeness (absurd future data changes no envelope byte) and the determinism across two
interpreter processes.

**SYNTHETIC results** (generated households of `intelligence/synthetic.py`, a 20 kWh synthetic battery, the synthetic
decisions accepted explicitly, a synthetic Go-like tariff at fictional 2030 prices; 10 issue days each, as the suite
runs them; the figures are the ones `test_intel_backtest_advice.py` prints, with `n` the issue days on which the
forecast was scored):

| Campaign (SYNTHETIC) | Load MAE / coverage (n) | PV MAE / coverage (n) | Morning SOC MAE / coverage (n) | Reserve violations (feasible OK advice) | Feasible / stated-shortfall nights | Stated-shortfall nights reaching the reserve | OK Dump advice scored / Dump violations |
|---|---|---|---|---|---|---|---|
| winter, heavy house | 3.331 kWh / 0.7 (10) | 2.05 kWh / 0.889 (9) | 4.926 points / 0.7 (10) | 0 | 1 / 9 | 5 | 6 / 0 |
| winter, medium house | 2.329 kWh / 0.7 (10) | 2.05 kWh / 0.889 (9) | 3.724 points / 0.6 (10) | 0 | 6 / 4 | 0 | 10 / 0 |
| summer, light house | 1.497 kWh / 0.7 (10) | 4.274 kWh / 0.857 (7) | 1.108 points / 1.0 (10) | 0 | 6 / 4 | 0 | 10 / 0 |

The heavy winter zero rests on one feasible night: on 5 of its 9 stated-shortfall nights (binding `MAX_SOC` or
`CHARGE_WINDOW`, so the advice itself says the battery cannot carry the period) the replay does reach the reserve. The
medium-house winter campaign is there so the winter zero is not vacuous (6 feasible nights).

**Dump-to-Grid scoring:** `tariff.events` is an I-D6 key with no default limit (CCR-DQ-1 / CCR-PLAN-1). The synthetic
I-D6 gives it 300 s, so the cycle judges the event list fresh and publishes OK Dump advice, and the backtest scores the
cycle's own OK Dump advice: `dump_ok_scored` 6, 10 and 10 in the three campaigns (SYNTHETIC), with 0 Dump reserve
violations. The positive control still pins the Dump detector on constructed views (a breach is a violation, a safe
export is not). With I-D6 OPEN, as in the repository, export and Dump advice are BLOCKED, and among their codes: I-D6
gates both (`DECISION_D6_OPEN`), and no gate reading has a limit (`INPUT_NOT_FRESH`), so the TOU slot table is never
fresh (`CHARGE_WINDOW_UNKNOWN`). The event list stays UNRESOLVED too; the quality layer names that on `export_event`
(`TARIFF_EVENTS_NOT_FRESH`). `dump_to_grid` carries `TARIFF_EVENTS_NOT_FRESH` only when the event list is its only
problem (a site I-D6 that gives every other input a limit but not `tariff.events`).

Synthetic observation, not a claim: the energy-only charge target imports less than `ALWAYS_100` but, with a synthetic
export rate above the cheap import rate, can cost slightly more than filling the battery from the grid and exporting the
PV surplus. The V1.1 target is a reserve-first energy budget, not a money optimiser.

## 7. PROPOSED constants (engineering suggestions, not owner values)

| Constant | Value | Why (conservative direction) |
|---|---|---|
| `tariff.PROPOSED_MAX_ABS_GBP_PER_KWH` | 1.5 | a GBP/kWh rate beyond this is a p/kWh figure in the wrong unit: refuse, never rescale |
| `tariff.PROPOSED_MAX_MEDIAN_GBP_PER_KWH` | 0.75 | a payload whose median rate is above this is taken as a unit mismatch: refuse |
| `tariff.PROPOSED_CHEAP_BAND_P_PER_KWH` | 0.5 | only slots this close to the cheapest rate form the cheap run |
| `tariff.PROPOSED_MIN_CHEAP_WINDOW_MIN` | 60 | a shorter cheap run is not a named run (the TOU window is then checked against `low`, the lowest rate priced in the 24 h before and after now, A35 / A38) |
| `tariff.PROPOSED_MAX_CHEAP_WINDOW_MIN` | 720 | a longer cheap run means a flat or nearly flat tariff: no cheap run from it |
| `tariff.PROPOSED_MIN_CHEAP_SPREAD_P_PER_KWH` | 2.0 | a run less clearly cheaper than every other slot names no run; without a named run, a slot of the TOU window at least this above `low` (the lowest rate priced in the 24 h before and after now, A38) BLOCKs (A35; wider than the 0.5 p band, so only a clear conflict blocks) |
| `tariff.PROPOSED_WINDOW_SEARCH_H` | 24 | the window is looked for in the next day only, and the rates must cover all of it; without a named run the window check's `low` also reads the same span before now (the look-back, A38: tighten-only, a lower `low` only adds BLOCKs) |
| `shadow_cycle.HORIZON_H` | 48 | the forward periods a cycle plans (tonight and tomorrow): the DST scope and the Saving Sessions considered |
| `daily_plan.PROPOSED_MORNING_ANCHOR_MIN` | 540 (09:00) | the end of the V1 "morning" window |
| `daily_plan.PROPOSED_ADVICE_VALIDITY_S` | 900 | equal to the SOC advisory limit; never longer than the inputs' remaining freshness |
| `shadow_cycle.REFRESH_MARGIN_S` | 125 | two 60 s runtime ticks plus 5 s (contract constant, section 13.4): an OK item valid for less is withheld (`INPUT_EXPIRING`) |
| `shadow_cycle.TOU_CLAIM_CAPPED` | True | register 248 bits 1-15 are not decoded: CONFIGURED is reported as UNCERTAIN (lifting it needs the owner and an independent review) |
| TOU claim start-SOC bounds | low: high load, low PV, down to the technical minimum; high: low load, high PV, the effective reserve held | a CONFIGURED claim needs the target above the highest, NOT_EXPECTED at or below the lowest |
| `value.PROPOSED_VALUE_STEP_GBP` | 0.05 | ranges rounded outward: no precision beyond the evidence |
| overnight period | window end -> next window start | the period the charge target must carry (V1 `to_next_cheap`) |
| PV credit | p10, after the window-end hour, MEDIUM or HIGH only | less PV assumed = more battery retained |
| window-start SOC, Saving Session start SOC | planning (p90) drain, held at the effective reserve (`held_soc_after`) | the same energy account as the baselines |
| headroom ceiling | PV p10 / p50, load p90 / p50, reserve-held account, rounded up | a higher ceiling never under-charges |
| morning SOC band | the reserve-held account, published to 0.1 point | the same energy account as the plan holds |

## 8. What is not modelled

- **Weather and season** beyond what the V1 models learn from recent history (open decision O-6).
- **Saving Session rewards** and any baseline-relative reward rule (open decision O-4): energy only.
- **Drift and calibration** (v0.2): the blocks stay None; `accuracy` only carries what `outcome_metrics` supplies.
- **VAT and the standing charge** (UNKNOWN, excluded), Agile-style fragmented cheap windows shorter than the PROPOSED
  minimum or without the PROPOSED spread (no named run: the TOU window is checked against `low`, A35), windows crossing
  local midnight, free-electricity sessions as a refill (parsed, not planned), the rate unit of a list payload (a
  plausibility guard only, UNKNOWN).
- **Export and Dump advice** stay BLOCKED while the event list is not judged fresh: `tariff.events` is an I-D6 key with
  no default limit (CCR-DQ-1 / CCR-PLAN-1), so it stays UNRESOLVED and never fresh until a site's I-D6 records a limit.
  `export_event` then carries `TARIFF_EVENTS_NOT_FRESH` (from the quality layer); `dump_to_grid` carries it only when
  the event list is its only problem. With I-D6 OPEN both are BLOCKED in any case (`DECISION_D6_OPEN`, and
  `CHARGE_WINDOW_UNKNOWN` because the TOU slot table has no limit either). Power limits for export are not known. The OK export / Dump
  paths are exercised in the planning suites under the synthetic I-D6 limit (and, for a stricter site limit, a
  tighten-only in-process simulation, test only). A Saving Session inside a charge window, or after more than one
  refill, is not modelled (BLOCKED).
- **Inverter slot behaviour** above a target SOC (UNVERIFIED), sub-hour load, battery wear in the value range. Of the
  TOU table only the grid-charge run is read (section 10.1): what the mode bits mean for charging, how the battery-first
  / load-first setting (register 243) changes TOU behaviour, register 248 bits 1-15 (perhaps a weekday mask) and the
  slot SOC acting as a discharge floor in slots that do not grid-charge are UNKNOWN and not modelled; the claim is
  capped at UNCERTAIN for the register 248 bits.
- **The register-230 grid-charge current limit** (WARN `GRID_CHARGE_CURRENT_LIMIT_NOT_MODELLED`, until a later change
  models it with a fresh battery-voltage reading). A grid-charge window that crosses local midnight stays BLOCKED by
  design.
- **`pref.normal_max_charge_target_pct`** is not used in v0.1.
- **Real-data accuracy:** none is claimed. The capture validator's real-data run is PENDING.

## 9. Tests

| Suite | Pins |
|---|---|
| `test_intel_cycle_planning.py` | SYNTHETIC_TEST decisions accepted -> items OK with confidence and reasons; the default acceptance -> BLOCKED; `engine_comparison` only with an OK charge target; `scorecard_report` without `recommended`; window and grid-limit sources; no example battery value (also with `apply_to_siteconfig` None while quality passes: HA helper 150); DST 2030; INVALID blocks all advice; partial / flat tariffs never a window source; the TOU window checked against the tariff (inside: INFO, outside: BLOCK; A35: a tariff naming no cheap run, one shoulder slot or an Agile-like day, BLOCKs a peak window and passes one within the spread; ENG6-1: import rates short of the search period still checked end to end, a partly priced window with a conflicting slot BLOCKs, a stale payload checks nothing, one day-rates event pinned with the TOU slot at the peak and equal to the cheap run, prices keep the coverage need; A38: the look-back keeps one event's passed cheap slots, so the peak window BLOCKs at every half-hour until it ends (N1 end to end), the slot that holds now counts (N2), a slot straddling now + 24 h counts (R7-E1), the unpriced-occurrence residual; A41: INFO `CHARGE_WINDOW_NOT_PRICED` on exactly the published charge-window items while no price check covered the whole occurrence, the envelope otherwise identical); the morning SOC never below the reserve; the HA helper raise-only; malformed pause values; the event list not fresh / stale / fresh (a site limit simulated in process, tighten-only), validity bounded by it, the Saving Session after the refill; date-scoped validity; `overnight_demand` bounded by its window sources and the liveness bound; a verified tariff without a fresh TOU table BLOCKED `CHARGE_WINDOW_UNKNOWN` with no window; no published text redacted on the suite's inputs, and a redaction visible; the grid-charge classification in the cycle, the power cap, `INPUT_EXPIRING`, the TOU claim and its cap, the raise-only reserve preference, `DECISION_VALUE_FROM_HELPER`, the configuration-poll ageing and validity; without the WP-1 outputs every TOU item BLOCKs |
| `test_intel_tou_table.py` | the slot classes by the exact texts (and flags), unknown slots, the schema (v1, ring, malformed), runs (adjacent, separate, across midnight also by one slot edge, whole day), the enables and the overlay, target and power, the window occurrence and its freshness (never empty in the spring-forward gap), every code a fixed value-free BLOCK named in contract 13.5, 2000 seeded mutated tables never raise, the module pure |
| `test_intel_tariff.py` | parsing, fail-closed cases, DST 23 h / 25 h coverage, cheap window (coverage of the search period, maximum length, spread), the band's ceiling, the window check's lowest rate over the 24 h before and after now (A35 / A38: both ends exact, a slot straddling now - 24 h or now + 24 h, the slot that holds now (N2), the band never looks back), the median unit guard, events, fixtures fictional 2030 |
| `test_intel_daily_plan.py` | the charge window always the TOU run (inside the tariff: INFO; outside: BLOCK; not classifying beside a tariff: BLOCK; a tariff alone never a window), A30 (slots, clip, coverage, also half coverage), A35 (a tariff naming no cheap run: shoulder slot, Agile-like, short and long runs, the boundary, partly priced, the clip, a 24 h sweep, F2 pinned), A38 (the look-back: N1 over a whole day, N2, a flat price rise blocking while the old rate is in the look-back, a two-rate rise keeping its named run, agreeing windows on full / current-day / next-day payloads, the unpriced-occurrence residual), A41 (INFO `CHARGE_WINDOW_NOT_PRICED` exactly when the window stands without a price check of its whole occurrence, in a sweep and per case), the old readers gone, whole-day windows refused, a 600-case seeded property sweep (morning band never below the reserve), every output BLOCKED without its decisions, cycling cost, precharge timing, the event start basis, the reserve-held headroom ceiling |
| `test_intel_baselines.py` | baselines present / absent, `HOLD_CURRENT` in the cycle exactly when its reading is judged fresh (fresh and stale cases, a site limit simulated in process, tighten-only), the replay, the same inputs for every policy, `cost_p` |
| `test_intel_value.py` | no GBP without VERIFIED, ordered finite ranges on the step, coverage |
| `test_intel_backtest_advice.py` | SYNTHETIC label, leak test, determinism across processes, zero reserve violations of feasible OK advice with the stated-shortfall nights reaching the reserve reported beside it, a non-vacuous winter campaign, positive controls for the charge-target and Dump detectors, the cycle's own OK Dump advice scored, the cycle's own baselines, no GBP without VERIFIED |

## 10. SHADOW v0.1 completion (WP-2): grid-charge classification, freshness, refresh margin, claim, reserve raise

The contract is [`INTELLIGENCE_FOUNDATION_CONTRACT.md`](INTELLIGENCE_FOUNDATION_CONTRACT.md) section 13; this section says
how the planning layer meets it. Every rule is additive or tighten-only; no frozen symbol, envelope field, gate or
limit changes.

### 10.1 The grid-charge classification of the TOU table (`intelligence/tou_table.py`, contract 13.5)

The table is the schema v2 value of `tou.slot_table` (exactly six rows in slot order, `end` the next row's `start`, a
null field unknown). The slot class is read from the exact dongle texts only: `Grid` and `Grid + Generator` are GRID,
`None` (the literal text: an explicit "no source", never an unknown value) and `Generator` are NOT_GRID. A slot is
UNKNOWN when its source or mode is null or not one of the exact texts (`Unknown 0xNN` included), or its flags word is
null or disagrees with them (bits 0-1 against the source, bits 2-4 against the mode; `TOU_SOURCE_DECODE_CONFLICT`), or
has a bit outside those set (bits 5-15 are not decoded; `TOU_FLAGS_UNDECODED_BITS`, A33). A slot is effectively GRID only when it is GRID, `tou.enabled` and `tou.grid_charge_enabled` are fresh and true, and
`tou.overlay_state` is fresh and `NONE`. The window is the single maximal run of ring-adjacent effectively GRID slots
(adjacent Grid slots merge), at its next occurrence that ends after now.

Each of these BLOCKs every item that rests on the window, with its code: a v1 table (`TOU_TABLE_LEGACY_SCHEMA`); a
wrong key, slot number, type or range (`TOU_TABLE_MALFORMED`); not six rows, a missing or invalid time, an end that is
not the next start, a zero-length slot or not exactly one wrap past midnight (`TOU_RING_INVALID`); any UNKNOWN slot
(`TOU_SLOT_SOURCE_UNKNOWN`: an unknown slot could be a second window); any null target or power
(`TOU_SLOT_TARGET_UNKNOWN`, `TOU_SLOT_POWER_UNKNOWN`); an enable unknown or off (`TOU_ENABLE_UNKNOWN` / `TOU_DISABLED`,
`TOU_GRID_CHARGE_ENABLE_UNKNOWN` / `TOU_GRID_CHARGE_DISABLED`); the overlay unknown or active
(`TOU_OVERLAY_STATE_UNKNOWN` / `TOU_OVERLAY_ACTIVE`: Free Power, Dump to Grid or a manual write overriding the table);
no effectively GRID slot (`TOU_NO_GRID_SLOT`); more than one separate run (`TOU_MULTIPLE_GRID_WINDOWS`); a zero slot
power in the run (`TOU_SLOT_POWER_ZERO`); a run across local midnight (`CHARGE_WINDOW_CROSSES_MIDNIGHT`) or of the whole
day (`CHARGE_WINDOW_NOT_REPRESENTABLE`). A stale table gives no window (`CHARGE_WINDOW_UNKNOWN`). The single-slot
fallback, the grid-flag guess and the tariff / TOU overlap rule are deleted: no period is ever invented.

### 10.2 Configuration-poll freshness, the planning half (contract 13.3)

The quality layer judges the configuration-poll liveness (`liveness.config_poll_changed_at`, 300 s PROPOSED; WP-1)
and publishes it in its ages beside the telemetry liveness. The planning layer reads it and, tighten-only:

- ages every configuration-poll reading (`site_decisions.CONFIG_POLL_READINGS`) by the larger of the telemetry and the
  configuration liveness ages, never fresh without a fresh configuration liveness, both for the readings the quality
  layer judged and for those it judges itself (`_own_state`; the enables are such readings);
- bounds the validity of every item that rests on a configuration-poll reading by both liveness keys.

Without a judged configuration liveness no configuration-poll reading is fresh, so every item that rests on the TOU
window BLOCKs: fail closed. The planning suites run on the real WP-1 rules, with no in-process simulation
(`test_intel_cycle_planning` [0] and [20]).

### 10.3 The refresh margin and `INPUT_EXPIRING` (contract 13.4)

`shadow_cycle.REFRESH_MARGIN_S = 125` (two 60 s runtime ticks plus 5 s; the runtime has a drift test against it). An
OK item whose validity at compute time is below it becomes BLOCKED `INPUT_EXPIRING` (a fixed text, no number), per
item: a TOU item whose configuration liveness is late no longer shortens the envelope, so `pv_tomorrow` and
`predicted_day_load` stay OK and the envelope stays valid for at least the margin. Whatever rests on a withheld item is
withheld too (a charge target on an expiring overnight demand is `DEMAND_NOT_AVAILABLE`).

### 10.4 The raise-only reserve preference (contract 13.7)

`pref.advisory_reserve_raise_pct` enters like a run-time reserve (beside the HA reserve helper, as its own input), so the
effective reserve is max(the I-D1 floor, the technical minimum, the HA helper, the raise): it can only raise the floor,
never changes I-D1, I-D2 or the technical minimum and never becomes a decision; a raise the configuration cannot hold
is the advisors' own SHORTFALL. Unmapped (no reading): no raise. A usable reading strictly above the I-D1 floor, the
technical minimum and the HA helper's value (when one is supplied): INFO `PREF_RESERVE_RAISE` on the items I-D1 gates;
one at or below any of them changes nothing and adds no code. Mapped but unusable (a null value, not a finite
percentage in 0..100, a
malformed reading, observed in the future, or given twice): BLOCK `PREF_RESERVE_RAISE_UNKNOWN` on the items I-D1 gates,
so a raised reserve never falls back silently. An I-D1 taken from the HA helper carries WARN
`DECISION_VALUE_FROM_HELPER` on those items.

The preference is never reported as the HA reserve helper (A33, ENG-5): it travels as its own run-time input
(`reserve_raise_pct` beside `ha_reserve_pct` on every advisor input, `build_plan`, `session_advice` and the V1 run), and
the reserve breakdown keeps the helper's own value in `ha_reserve_pct`, adds `reserve_raise_pct`, and names a binding
preference as `binding` `reserve_raise` with `override_code` `PREF_RESERVE_RAISE`; `HA_RESERVE_RAISES_USER_RESERVE`
appears only when the helper itself binds. The arithmetic is unchanged (the planning suite compares every published
number with the helper route to the same floor).

### 10.5 What the advice may claim (contract 13.6)

Exactly one INFO code of `TOU_CLAIM_CONFIGURED`, `TOU_CLAIM_NOT_EXPECTED` and `TOU_CLAIM_UNCERTAIN`, first among the
reason codes of an OK `charge_target` and an OK `predicted_morning_soc` only, with no window, target or other number.
CONFIGURED needs one target across the run above the highest plausible SOC at the window start (low load, high PV,
the effective reserve held), every slot power and the grid-charge limit above 0, `inverter.healthy` fresh and true, a
fresh clock offset within its bound and a fresh, classified window. NOT_EXPECTED: the target is at or below the lowest
plausible SOC at the window start (high load, low PV, down to the technical minimum; the SOC now when the window has
started). UNCERTAIN: anything else. `TOU_CLAIM_CAPPED` (default True) reports CONFIGURED as UNCERTAIN while register
248 bits 1-15 are not decoded. `predicted_morning_soc` starts from the planned window-end SOC, so it carries WARN
`MORNING_SOC_ASSUMES_CHARGE` whenever the claim is not CONFIGURED (with the cap: always). No text says that charging
will happen: a grid-sourced slot is necessary, never sufficient. `inverter.healthy` gates only the claim.
