# Intelligence foundation contract (SHADOW v0.1)

> **Offline, SHADOW-only, source only.** Nothing here is installed, deployed or connected to Home Assistant, the dongle,
> the inverter or InfluxDB. Every Intelligence decision I-D1..I-D9 is **OPEN**: the repository records none. Every number
> marked PROPOSED is an engineering suggestion, **not an owner decision**, and is never applied while its decision is OPEN.

This document is the single description of the shared Intelligence contracts that every later stream builds on:

| Module | What it owns |
|---|---|
| [`intelligence/site_decisions.py`](../../intelligence/site_decisions.py) | the decision register, provenance and acceptance, reserve roles, the proposed thresholds, the freshness mirror and ceiling, the item gates, the required inputs, `apply_to_siteconfig`, the one `Finding` type |
| [`intelligence/periods.py`](../../intelligence/periods.py) | local wall-clock periods across clock changes (DST) |
| [`intelligence/advisory_contract.py`](../../intelligence/advisory_contract.py) | `CycleInputs`, the `AdvisoryEnvelope`, the entity contract `ecco-intel-entities/1` and its null rule |
| [`intelligence/authority_vocab.py`](../../intelligence/authority_vocab.py) | modes, action kinds, outcomes, preconditions, refusal codes (data only) |
| `intelligence/quality.py`, `intelligence/shadow_cycle.py` (published with the engine, after these contracts) | the frozen seams `assess_inputs`, `prepare_history`, `run_cycle` (minimal fail-closed bodies until the streams fill them) |

The S0 diagnostic ([`INTELLIGENCE_S0_INPUT_CONTRACT.md`](INTELLIGENCE_S0_INPUT_CONTRACT.md)) consumes the register and periods.
The V1 / V1.1 modules, `SiteConfig`, `ecco_core` and `render_ha_prototype` are unchanged; the prototype renderer and its
`ecco_intelligence_*` entities are **superseded** by the entity contract below and stay frozen.

**What is published when.** SHADOW v0.1 is published in four parts, in this order:

1. the contracts in the table above, with S0;
2. the engine: `intelligence/quality.py`, `intelligence/shadow_cycle.py` and the planning modules, with
   `test_intel_contract_signatures.py` and `test_intel_shadow_cycle_contract.py`;
3. the Home Assistant runtime `custom_components/ecco_intelligence/`, with its boundary suite, the build command line and
   the `custom_components/ecco_intelligence/tests` root;
4. `ecco_autonomy/`, with the `ecco_autonomy/tests` root.

Sections 8 to 12 and the runtime rules in section 2 name files from all four parts. A file that a part has not yet published
is described here as the contract that part must meet; it does not exist in the repository until then.

## 1. The decision register

Internal ids stay `D1..D9` (finding codes `DECISION_D<n>_OPEN` / `DECISION_D<n>_INVALID`); every display surface uses the
label **`I-D<n>`**; the loader accepts both. Statuses are `OPEN`, `RECORDED` and `INVALID`. Free text and bare numbers are
never `RECORDED`; an incomplete record is `INVALID`; `INVALID` always BLOCKs: every item the decision can gate at all
(`items_gated_by`: its unconditional and its conditional items) is blocked, and the cycle reports a top-level
`DECISION_D<n>_INVALID`, whether or not the conditional scope applies.

The invariants live on the type, so no code path can build a decision the loader would refuse: a `Decision` with status
`RECORDED` needs a valid typed value (its `problems()` empty), a known provenance and, for an `OWNER_RECORD`, a full-match
`record_ref`; an `OPEN` decision carries nothing; an `INVALID` one names its problems. `satisfied()` re-validates the
record, so an object mutated after construction never counts.

| Label | Typed record | Fail-closed rule |
|---|---|---|
| I-D1 | `PlanningFloor{source: INTELLIGENCE_USER_RESERVE / HA_RESERVE_HELPER / FEATURE_STOP_LEVEL / NEW_SINGLE_SETTING, value_pct (first and last only), advice_honours}` | `HA_RESERVE_HELPER` and `FEATURE_STOP_LEVEL` need a fresh, finite reading with a defined freshness limit at every cycle, otherwise BLOCK; never the example 40 or the placeholder. Intelligence never writes the helper. **Firmware features (Dump to Grid) do not honour any planning floor** (SAFETY.md section 9): the floor limits what the advice recommends |
| I-D2 | `Protection{supplied_by: OWNER_STATEMENT (value_pct, observed_at) / READ_ONLY_SENSOR_SNAPSHOT}` | technical minimum = max(placeholder, value), raise-only; with a snapshot a missing, stale or non-numeric `protection.shutdown_soc_pct` BLOCKs `PHYSICAL_PROTECTION_UNKNOWN`, never a placeholder |
| I-D3 | `CapacityAuthority{kind (not EXAMPLE_DEFAULT), value_kwh or resolve_at_run, nominal_voltage_v for Ah}` | a resolve-at-run kind needs a fresh, plausible reading |
| I-D4 | `CapacityBand{pct}` | conditional: with two or more capacity sources present an OPEN band BLOCKs, a mismatch beyond the band BLOCKs, and a mismatch that cannot be computed BLOCKs (`CAPACITY_MISMATCH_UNKNOWN`). Sources are counted and converted to kWh by `capacity_sources_context`: a satisfied I-D3 stated value, `capacity.helper_kwh`, `capacity.fe1_wh_per_pct` x 100 / 1000, `capacity.reg204_ah` x the voltage stated in I-D3 / 1000; a reading counts whether fresh or not, and an Ah reading without a stated voltage makes the mismatch unknown |
| I-D5 | `Efficiency{value, unit: fraction / percent, basis: ROUND_TRIP / ONE_WAY}` | normalised by `efficiency_round_trip` to `SiteConfig.round_trip_efficiency` |
| I-D6 | `FreshnessOverrides{key: seconds}` | tighten-only for a defined limit; at most the 900 s ceiling for an unresolved one (section 4 says how the ceiling is read); unknown keys refused; any refused entry makes I-D6 INVALID and **nothing** is applied |
| I-D7 | retired: `REQUIRED_SIGNALS` / `REQUIRED_READINGS` are code constants; `RequiredInputsOverride` may only ADD per item | an INVALID I-D7 blocks every item |
| I-D8 | `HD1Cutover{cutover (aware), load_power_policy: EXCLUDE / KEEP_NON_EXPORTING_ONLY, load_counter_policy: EXCLUDE_PRE_CUTOVER / KEEP_AFTER_COUNTER_CHECK, counter_check_evidence_ref}` | both KEEP options need an evidence reference `REC-YYYYMMDD-<slug>`, otherwise INVALID; the cut-over instant is a site fact |
| I-D9 | `DSTPolicy{history_rule: EXCLUDE_CHANGED_PERIODS / NORMALISE_TO_NOMINAL, target_rule: SCALE_TO_ACTUAL / SCALE_UP_ONLY}` | fixed rule whatever I-D9 says: a period boundary in a repeated or missing hour BLOCKs; conditional gate: a period, or a learning period within `OvernightSettings.lookback_nights` (28), crosses a clock change |

**PROPOSED answers (not owner decisions).** `site_decisions.PROPOSED_ANSWERS` holds them as text labelled
`PROPOSED_PENDING_OWNER`; they are never applied while OPEN and cannot be loaded as decisions:

- I-D4: 8.0 %;
- I-D6: 300 s per dongle signal and gate reading, judged by the poll-text liveness time, within the 900 s ceiling
  (section 13.3 splits this text by key class);
- I-D8 policy: `EXCLUDE` + `EXCLUDE_PRE_CUTOVER`;
- I-D9: `NORMALISE_TO_NOMINAL` + `SCALE_UP_ONLY`.

`ProposedThresholds` (the S0 values: 8 % band, 0.5-500 kWh plausibility, efficiency plausibility and agreement tolerances)
has one copy, in `site_decisions`.

**Reserve roles** stay apart: `SOFT_PLANNING_FLOOR`, `HA_RESERVE_HELPER` (ACS1's lower bound; raise-only in advice),
`FEATURE_STOP_LEVEL`, `PHYSICAL_PROTECTION` (read-only), `INVERTER_TOU_SETTING` (a slot target SOC), `DERIVED_EFFECTIVE`
(`SiteConfig.effective_reserve`, computed, never set).

## 2. Provenance and acceptance

- Provenance is one of `SYNTHETIC_TEST`, `SYNTHETIC_EXAMPLE`, `CALLER_DECLARATION_UNVERIFIED`, `OWNER_RECORD`.
- `DecisionSet.from_mapping(mapping, source=...)` is strict (unknown keys refused, no file I/O). An `OWNER_RECORD` is accepted
  only with `source='site_local'` and a `record_ref` matching `^REC-[0-9]{8}-[a-z0-9][a-z0-9-]{2,63}$` over the whole
  string (`fullmatch`: a trailing newline is refused), an opaque id of a private record; public code holds no private
  path. The check is the public `site_decisions.record_ref_ok(ref)` over the public pattern string `RECORD_REF_PATTERN`
  (no compiled pattern object is exported: the vendor scan refuses any call named `compile`). It is never minted in
  code: `decide()` and `DecisionSet.with_decision()` give `INVALID` for an `OWNER_RECORD`
  (they serve tests and declarations), and a `DecisionSet` whose source is not `site_local` refuses a RECORDED
  `OWNER_RECORD` decision object.
- **A decision is satisfied only if it is RECORDED and its provenance is in `accept_provenance`, whose default is
  `{OWNER_RECORD}`.** A recorded decision with another provenance counts as OPEN in every gate.
- Only tests and the S1 command line pass `SYNTHETIC_TEST` explicitly. `CycleInputs.accept_provenance` is keyword-only.
  The Home Assistant runtime never passes it in any form: its boundary suite bans the keyword, a positional route into
  `gate` / `satisfied` / `required_inputs` / `freshness_limits` / `apply_to_siteconfig` / `capacity_sources_context` /
  `provenance_ok` / `CycleInputs`, `*` / `**` expansion into those calls or `replace()`, the provenance constants, and
  building a decision in code; the runtime loads decisions only with `DecisionSet.from_mapping(..., source='site_local')`.
- The example profile [`intelligence/profiles/site_profile.example.json`](../../intelligence/profiles/site_profile.example.json)
  ships a `decisions` block with every I-D OPEN. Its site hints `site.user_reserve_soc_pct` and `technical_min_soc_pct`
  stay (pinned by `test_intelligence_reserve.py`) and are **ignored by the SHADOW path** (INFO `SITE_HINT_IGNORED`):
  reserves come only from I-D1 / I-D2. The example profile used as a site file gives every gated item BLOCKED.

## 3. Gates and required inputs (`ITEM_GATES`, `REQUIRED_SIGNALS`, `REQUIRED_READINGS`; add-only)

| Item (published?) | Decisions | Required fresh inputs | Never sourced from |
|---|---|---|---|
| overnight_demand (yes) | I-D8 (+I-D9 cond.) | `history.hourly` (6 h) | - |
| charge_target (yes) | I-D1, I-D2, I-D3, I-D5, I-D8 (+I-D4, I-D9 cond.) | `battery.soc`, history, dongle liveness, the I-D1 / I-D2 / I-D3 readings when those sources are chosen, `limits.max_grid_charge_w`, a charge window: the read-only `tou.slot_table` classified as one grid-charge run (13.5), cross-checked against `tariff.import_rates` when that is VERIFIED (a conflicting priced slot BLOCKs; a tariff alone is never a window), else BLOCK | the SiteConfig example capacity, efficiency, window or 8 kW |
| export_event (yes) | I-D1, I-D2, I-D3, I-D5, I-D6, I-D8 (+I-D4 cond.) | the above (the charge-window source included: the refill window) plus house / PV / battery / grid power, `inverter.healthy`, `tariff.export_rates` | the SiteConfig example window |
| dump_to_grid (yes) | I-D1, I-D2, I-D3, I-D5, I-D6, I-D8 (+I-D4 cond.) | as export_event, plus `stop.dump_soc_pct` | the SiteConfig example window |
| predicted_morning_soc (yes) | I-D1, I-D2, I-D3, I-D5, I-D8 (+I-D4, I-D9 cond.) | as charge_target | - |
| predicted_day_load (yes) | I-D8 | history | - |
| pv_tomorrow (yes) | none | history, `pv.forecast_tomorrow_kwh` (date-scoped: issued on the same local date), the site fact `pv_array_kwp` | - |
| v1_summary (internal only) | I-D1, I-D2, I-D3, I-D5, I-D8 | as charge_target | - |
| engine_comparison (attribute) | emitted only when charge_target is OK | - | - |

Every dongle-sourced input (SOC, powers, inverter health; the raw SOC, Ah register, shutdown level, Dump stop level, TOU
table and clock offset readings) needs `liveness.dongle_poll_changed_at`. `gate(item, decisions, context, accept_provenance)`
returns the BLOCK findings; `required_inputs(item, decisions, accept_provenance)` the inputs. Section 13 adds the
configuration-poll liveness reading to the required inputs of every charge-window item (13.3) and makes the TOU table's
grid-charge classification the only charge-window source, which a VERIFIED import tariff cross-checks but never
replaces (13.5, A30); the charge_target row above states that rule, and the table is otherwise unchanged.

`apply_to_siteconfig(base_cfg, decisions, readings, accept_provenance)` returns a `SiteConfig` built with
`dataclasses.replace` whose battery fields (user reserve, technical minimum, capacity, round-trip efficiency, grid-charge
limit) and cheap window come only from satisfied decisions and fresh readings, or `None` with the reasons. It never keeps
the example capacity, efficiency, 40 % reserve, 8 kW or cheap window. The cheap window is the judged input
`readings[CHARGE_WINDOW_KEY]` (`charge_window.local_minutes`: `(start_min, end_min)` after local midnight, ints with
`0 <= start < end <= 1440`, fresh under a defined limit), which the planning layer derives from the read-only TOU slot
table's grid-charge run, cross-checked against a VERIFIED import tariff when there is one (a tariff alone is never a
window: 13.5); without one the result is `None` with `CHARGE_WINDOW_UNKNOWN`.
An `HA_RESERVE_HELPER` reading outside 0..100 BLOCKs (`RESERVE_HELPER_OUT_OF_RANGE`).

**Value shape of the tariff readings (CCR-PLAN-3).** `tariff.import_rates` and `tariff.export_rates` (unit `table`) carry
the tariff integration's rate rows `{start, end, value_inc_vat}`: ISO-8601 times with a UTC offset and a rate in GBP/kWh
(the integration's unit). The planning adapter accepts a list of rows, one rate event's attributes `{rates: [...],
unit_of_measurement}` (a stated unit must be GBP/kWh), or rate events merged into `{previous_day | current_day |
next_day: ...}`. **Mapping (A38 Part B, CCR-RT-DAYS: the contract the Home Assistant runtime implements; it replaces
ENG6-2's "the runtime merges nothing").** A rate table key maps either one `{entity, attribute}`, whose value is passed
only when it is a list of rows (anything else is `TABLE_MISSING`), or an ordered list of two or three of them: the
integration's day rate events in day order (current day, next day; or previous day, current day, next day). The runtime
reads each and hands the engine one list of rows (INTELLIGENCE_HA_RUNTIME 2.3):
an event that is unavailable, or whose attribute is absent or an empty list, contributes nothing (the next day before
its rates are published); every contributing attribute must be a list, otherwise the whole table is refused; the rows
are concatenated in mapped order, and a row with the same start, end and rate as an earlier row is collapsed; any other
overlap, rows out of order or a row whose start or end is unusable refuses the whole table; a gap (in the three-event
form, the current-day event unavailable while the other two contribute) is passed on unchanged, never filled, and the
planning layer's parse rule refuses a table with a gap (`TARIFF_GAP`), so that tariff is unusable for the cycle; the
merged reading's age and validity are those of its oldest contributing event (the single form's rule applied to that
event); an empty merge is `TABLE_MISSING`. A refused table gives no reading, so the engine sees no tariff (a classified
TOU window then stands with the WARN "no verified tariff" and INFO `CHARGE_WINDOW_NOT_PRICED`, 13.5; the runtime's
refusal code is in the diagnostics' `source_notes`). The same entity listed twice, and the same entity and attribute
under two of `tariff.import_rates`, `tariff.export_rates` and `tariff.events` (every day event of a list counted; A42),
are refused by the entity map (`site-check` exits 1), and `tariff.events` takes the single form only. The production site
file maps the import rates as the two-event list `[current day, next day]` (A42). The three-event form is allowed; the
previous-day event is added only by a later decision, once a readiness read shows that its report cadence stays within
its I-D6 limit (the merged reading is as old as its oldest contributing event). On a site the value is therefore always
a list of rows; the quality layer, too, accepts only a list for a table reading, so the two mapping shapes are parsed
only when the adapter is called directly (the offline suites). The list shape states no unit, so the planning layer's
unit check on it is a plausibility guard only. One day-rates event of the tariff integration prices one local day,
which covers the 24 h charge-window search period (13.5) only in a cycle at local midnight itself; the day events cover
it from the moment the next day's rates are published, and before that they price the current day (and, in the
three-event form, the previous day). A reading that does not cover the period is not VERIFIED for prices, the
tariff block or the value, it names no cheap run (so the A30 check does not run on it), and the window check compares
the TOU occurrence's priced slots with the lowest rate the reading prices from 24 h before `now` to 24 h after it (13.5,
"The look-back" and "What remains on one day-rates event"). `tariff.events` (unit `table`) is a list of `{start, end,
kind}` periods (kind `saving_session` or `free_electricity`) or the integration's event attributes. Any other shape, a
naive time or a price under another key is refused, never repaired (`intelligence/tariff.py`).

## 4. Freshness (defence in depth)

1. **Mirror.** `site_decisions.ADVISORY_LIMITS_S` mirrors the `ecco_core.freshness` ADVISORY catalogue: SOC 900 s, hourly
   history 6 h, everything else UNRESOLVED (`None`: never fresh). A drift test compares them.
   `PROPOSED_FRESHNESS_CEILING_S = 900`. `freshness_limits(decisions, accept_provenance)` applies a satisfied I-D6 with the
   FreshnessPolicy semantics (tighten-only, unknown keys refused) plus the ceiling, and re-validates every entry before
   applying anything: a recorded I-D6 that does not re-validate applies nothing and BLOCKs (`DECISION_D6_INVALID`).
   The I-D6 keys include the readings the quality layer needs to judge a required input
   (`QUALIFYING_READING_KEYS`: `battery.soc_raw_pct`, `inverter.clock_offset_s`, `tariff.events`; CCR-DQ-1) and the
   reading the planning layer judges although no item requires it (`PLANNING_READING_KEYS`:
   `tou.current_target_soc_pct`; CCR-PLAN-1). Neither has a default limit: each is UNRESOLVED until a site records one.

   **How the ceiling is read (an interpretation for the integrator to accept).** The plan's text says "an override above
   the ceiling makes I-D6 INVALID". The code applies the 900 s ceiling to every signal and reading **without** a defined
   limit, and applies tighten-only to the two that have one: `battery.soc` (900 s, equal to the ceiling) and
   `history.hourly` (6 h). So a `history.hourly` override up to 21600 s is RECORDED and one above it is INVALID. Capping
   hourly history at 900 s instead would make the history never fresh (its newest hour normally ends more than 15 minutes
   before a cycle), and the tighten-only rule already fails closed. Both readings refuse every loosening; they differ only
   for a `history.hourly` override between 900 s and 6 h.
2. **Runtime.** It builds the Snapshot with `observed_at`, calls `ecco_core.bridge.advisory_live_inputs` with the ADVISORY
   policy and the I-D6 overrides, and passes the raw snapshot, the LiveInputs and the caller's assessments to the cycle.
3. **Re-verification.** `quality.assess_inputs` recomputes every age from `now`: for a dongle-sourced input from the
   poll-text change time (the dongle publishes only changed values); a missing liveness reading BLOCKs; an UNRESOLVED limit
   BLOCKs; an input the caller called fresh that quality computes stale BLOCKs with `CALLER_FRESHNESS_DISAGREES`.
4. **Configuration poll.** A reading published by the dongle's configuration poll is also aged by that poll's own text
   (`liveness.config_poll_changed_at`, a fixed bound that no I-D6 entry can loosen): section 13.3.

## 5. DST (`intelligence/periods.py`)

`period_profile(day, start_min, end_min, tz='Europe/London')` returns nominal and actual hours, `factor`, `change_kind`
(NONE / AUTUMN_BACK / SPRING_FORWARD) and `start_boundary` / `end_boundary` (OK / AMBIGUOUS / NONEXISTENT), using
`timeutil.local_wall` (the engine's mapping). `change_kind` comes from the length, or, when the length is unchanged (a
window ending in the skipped hour), from a change strictly inside `(start_utc, end_utc)`, so `.changed` is true whenever a
window crosses a change. It refuses `actual_h <= 0` (the spring gap) and a window wholly inside the gap, and raises only
`ValueError` (an unknown zone or out-of-range minutes included).

The reference SHADOW cycle wires the conditional I-D9 gate and the fixed rule: a change within the learning lookback or
the forward 48 h horizon puts I-D9 in scope, and a fresh TOU slot whose start or end lies in a repeated or missing hour
(or in the spring gap) on today's or tomorrow's local date, or a change ahead with no window that can be profiled, BLOCKs
`DST_BOUNDARY_IN_CHANGED_HOUR`. An unusable zone fails closed.
`clock_changes(start, end)` lists the changes in a half-open range. Fixtures: 25 Oct 2026 (25 h), 28 Mar 2027 (23 h),
2026-2030.

## 6. The entity contract `ecco-intel-entities/1` and the null rule

Entities (unique_id = object id; a test asserts no overlap with any id or unique_id under `home-assistant/`):
`sensor.ecco_intel_status` (state = system status), `sensor.ecco_intel_{charge_target, overnight_demand, export_event,
dump_to_grid}`, `sensor.ecco_intel_{predicted_day_load, pv_tomorrow, predicted_morning_soc}`,
`sensor.ecco_intel_{accuracy, data_quality}`, `binary_sensor.ecco_intel_fresh`, and the package entities
`input_boolean.ecco_intel_paused` and `binary_sensor.ecco_intel_watchdog_fresh`.

**Status precedence:** PAUSED > SELF_TEST_FAILED > STALE > STARTING > BLOCKED > INSUFFICIENT_DATA > NO_ADVICE > OK. BLOCKED
means data quality is BLOCKED, or no advice item is OK and at least one is BLOCKED. A missing pause control means not
paused, `pause_control: MISSING` and the reason code `PAUSE_CONTROL_MISSING`.

**Null rule (not open to a change request):**

- under STARTING, PAUSED, STALE or SELF_TEST_FAILED every item, forecast and diagnostic state is None; the last values
  appear only in the unrecorded `last_good{generated_at, values}`;
- otherwise an item is numeric only if its status is OK and `now <= valid_until`;
- a BLOCKED or INSUFFICIENT_DATA item carries no number in its state or in any attribute.

**Status attributes:** `mode: SHADOW`, `applies_nothing: true`, `contract_version`, `integration_version`,
`engine_version`, `git_sha`, `config_hash`, `generated_at`, `valid_until`, `next_run_at`, `blockers[{code,text}]`,
`reason_codes[]`, `decisions{"I-D1"..: OPEN|RECORDED|INVALID}`, `provenance_ok`, `pause_control`, `data_quality`, and the
pre-declared blocks `tariff{provenance,window,price_range}`, `value{range_gbp,assumptions,baselines}`,
`plan{precharge_by,headroom_ceiling_pct,reserve_runout_at}`, `accuracy{mae_7d,coverage_7d,n}`, `drift` and `calibration`
(reserved, always null in v0.1). Unrecorded: `self_test{}`, `input_ages[]`, `last_good`. Item entities carry the
`ecco_core.bridge.AdvisoryRecord.display_attributes` names (`mode`, `applies_nothing`, `kind`, `status`, `generated_at`,
`advice`). `scorecard_report` is never published and never contains `recommended`. Every entity's JSON is at most 16 KiB
(per-field caps; a test builds the maximal envelope).

**Inner shapes of the pre-declared blocks (CCR-INT-1, additive, integration step IP-4b).** As the SHADOW cycle publishes
them:

- `tariff.window`: the charge window the plan used, `{start, end}` as aware ISO-8601 timestamps in UTC (`start < end`),
  or null when there is none. It is published whatever the provenance; a reader shows it only with a VERIFIED tariff;
- `tariff.price_range` and `value.range_gbp`: `[low, high]`, two finite numbers with `low <= high` (p/kWh and GBP);
- `value.assumptions`: a list of texts; `value.baselines`: `{name: [low, high]}`;
- `plan.precharge_by` and `plan.reserve_runout_at`: aware ISO-8601 timestamps or null; `plan.headroom_ceiling_pct`: a
  finite number or null.

The envelope does not refuse other inner shapes, so a reader of these blocks stays tolerant of them.

**What the envelope refuses** (ValueError at construction, so no body can publish a gated number):

- an OK item or forecast while data quality is BLOCKED, while a decision it depends on is not RECORDED, or while any
  decision that can gate it is INVALID; `assemble_envelope` also checks satisfaction under `accept_provenance`
  (`site_decisions.gate`), needs a `valid_until` covering `now` on every OK item and an envelope `valid_until` when any
  item is OK (an expired item can never leave the status at OK);
- under STARTING / PAUSED / STALE / SELF_TEST_FAILED any tariff, value, plan, accuracy or engine-comparison block;
- a pre-declared block with a key it does not declare; an accuracy figure that is not a finite number >= 0 (`n` an int);
- `tariff.price_range` unless `tariff.provenance` is VERIFIED (`VERIFIED` or `VERIFIED_FROM_INTEGRATION`); a `value`
  block unless the tariff is VERIFIED and charge_target is OK; a `plan` block unless charge_target is OK;
- an `input_ages` row that is not exactly `{name, age_s, limit_s, status}` with a known, unique signal or reading name, ages
  None or finite >= 0 and a status in fresh / stale / unknown / missing; a `self_test` value other than `PASS` or
  `FAIL: ...`; a pv_tomorrow summary with a key outside the V1 `PvForecast.to_dict()` keys.

`stale_from` with the pause control ON gives PAUSED (PAUSED > STALE), keeping `last_good`. `to_entity_payloads`
re-checks `mode`, `applies_nothing` and the contract version, so an object mutated after construction is never published.

`to_entity_payloads(envelope)` is THE mapping. The constructors `assemble_envelope`, `starting_envelope`,
`paused_envelope`, `stale_from`, `self_test_failed_envelope`, `with_last_good` and `with_next_run_at` mean the runtime
never builds an envelope by hand, and the envelope refuses to exist unless `mode == 'SHADOW'` and `applies_nothing is True`.
`with_next_run_at(env, t)` (additive, integration step IP-4b) sets only the status attribute `next_run_at`; `run_cycle` is
pure and knows no schedule, so the runtime sets it on every computed and STALE envelope. It refuses a naive time and a
time before the envelope's `generated_at`. Golden
fixtures (`intelligence/tests/fixtures/advisory_contract/`) are generated from literal constructors by
`intelligence/tests/_gen_contract_fixtures.py --write`, never from `run_cycle`.

## 7. The action vocabulary (`intelligence/authority_vocab.py`)

`Mode {OFF, SHADOW, ASSISTED, AUTONOMOUS}`, `DEFAULT_MODE = SHADOW`, `RUNTIME_ALLOWED_MODES = {OFF, SHADOW}`. Candidate
`ActionKind`s: TOU slot target SOC, TOU slot charge power, TOU slot charge source, notify owner. `NEVER_ALLOWED`:
protection registers 217-219, Free Power arm, Dump to Grid arm, raw manual slot write, export-mode register 244, raw bus
write, firmware change, reserve helper write, clock write, unattended Dump (A10-P), ACS1 Review or phrase automation.
`Outcome {RECOMMENDED, PREPARED, REQUESTED, REFUSED, EXECUTED_MOCK, VERIFIED_MOCK, FAILED, RESTORE_REQUIRED,
RESTORED_MOCK}`; **PREPARED is a record only**: no HA write, no Review start, no staging of ACS1 helpers. `Precondition`
ids and `RefusalCode`s complete it. The vocabulary acts on nothing.

## 8. Frozen interfaces and what is not open to a change request

Frozen (pinned by `intelligence/tests/test_intel_contract_signatures.py`):

- `shadow_cycle.run_cycle(inputs: CycleInputs) -> AdvisoryEnvelope`;
- `quality.assess_inputs(inputs: CycleInputs) -> QualityResult{findings, blocked_items, data_quality, ages}`;
- `quality.prepare_history(history, decisions, now) -> (History | None, findings)`;
- the field sets of `CycleInputs`, `QualityResult`, `SiteReading`, `AdvisoryEnvelope`, `ItemView`, `ForecastView`;
- `ENTITY_IDS`, `CONTRACT_VERSION`, `SITE_READING_KEYS` (a superset may grow).

`intelligence/tests/test_intel_shadow_cycle_contract.py` holds for any body: all decisions OPEN on a complete fresh input
gives every advice item, `predicted_morning_soc` and `predicted_day_load` BLOCKED and no finite number anywhere in the
payloads except `pv_tomorrow` and the diagnostics; the example profile as a site file gives the same; paused gives PAUSED
with all nulls; a caller-fresh / quality-stale input gives `CALLER_FRESHNESS_DISAGREES`; 500 seeded malformed inputs
never raise; two interpreter processes give identical results; no clock read, `open`, `os`, dynamic import or exec in
the seams; the conditional gates are wired (several capacity sources with I-D4 OPEN block every capacity item; the eve of
a clock change with I-D9 OPEN blocks charge_target, overnight_demand and predicted_morning_soc, and a window starting in
the repeated hour BLOCKs whatever I-D9 says) and an INVALID decision BLOCKs at the top level and on every item it can
gate. Its all-OPEN exemptions are hard-coded in the suite (pv_tomorrow with its PV-forecast advice keys, the two
diagnostic entities, `input_ages[].age_s / limit_s` and `accuracy.{mae_7d, coverage_7d, n}`), and every string is
scanned for the example window (00:30-05:30) and, outside those entities, for a number with a unit. The fixture TOU
window is 01:00-04:30 so it cannot be confused with the example. Streams may not edit these two suites.

**Not open to a change request in this slice** (a change needs an independent adversarial review AND the owner):
`DEFAULT_MODE`, `RUNTIME_ALLOWED_MODES`, `NEVER_ALLOWED`; the envelope SHADOW check and the null rule; `ITEM_GATES` and
`REQUIRED_*` (add-only); `ADVISORY_LIMITS_S` and the freshness ceiling; the default `accept_provenance`;
`REAL_WRITES_POSSIBLE`; both boundary suites (tighten-only); the HA platform allowlist (sensor and binary_sensor only).

## 9. The build command line (frozen)

`python tools/build_ha_integration.py --out <abs-dir> [--git-sha S]`

- builds from the working tree, with no git and no network;
- writes `<out>/custom_components/ecco_intelligence/` plus `VENDOR_MANIFEST.json` and `SHA256SUMS`;
- exits 0 on success;
- refuses an `--out` inside the repository.

**Vendor closure roots:** the AST import closure (module level and function level) of `intelligence.shadow_cycle`,
`intelligence.scorecard`, `intelligence.history` and `ecco_core.bridge`, plus the package `__init__` files on the path. All
absolute `intelligence.` / `ecco_core.` imports are rewritten; `ecco_autonomy`, `ecco_core/authority.py`,
`ecco_core/capability.py`, tests, tools, prototypes and profiles are never vendored, and `_vendor/` is never committed.
`custom_components/ecco_intelligence/tests/test_runtime_boundaries.py` checks the built artefact whenever the build tool
exists.

## 10. Test roots and boundary suites

`tools/offline_test_roots.txt` gains `custom_components/ecco_intelligence/tests` (the runtime boundary suite: a positive
Home Assistant import allowlist and a positive allowlist for every other import, banned write names and families (the
sync `hass.states.set` / `remove` and `hass.bus.fire` included), no dynamic import / exec / computed getattr / dunder
access, sensor / binary_sensor platforms only (modules or packages), no services, no `hacs.json`, no compiled or
path-hook files, writes only in `runtime/store.py`, the manifest rules, no route to widen `accept_provenance`, the
built-artefact scan) and `ecco_autonomy/tests` (the autonomy boundary suite: a positive pure standard-library allowlist,
no dynamic calls, the allowed repo imports, no entity-id shaped string (format fields and f-string pieces included),
nothing under intelligence/, custom_components/, ecco_core/, home-assistant/, frontend/, tools/, registry/ or health/
imports it (also through `__import__` / `import_module`), `REAL_WRITES_POSSIBLE = False` bound exactly once). Only each
package's own top-level `tests/` is excluded; a nested tests package is production code. Each suite is vacuous while its
package is absent and strict once anything exists.

## 11. File ownership after FOUNDATION_SHA

| Stream | Owns |
|---|---|
| dq | the body of `intelligence/quality.py`; `intelligence/faults.py`; `tools/validate_capture.py`; its `test_intel_*` suites and `fixtures/dq/**`; its docs |
| plan | the body of `intelligence/shadow_cycle.py`; `intelligence/{tariff,daily_plan,baselines,value,backtest_advice}.py`; its suites and `fixtures/plan/**`; its doc |
| runtime | `custom_components/ecco_intelligence/**` except `tests/test_runtime_boundaries.py` and `tests/test_integration_e2e.py`; `tools/{build_ha_integration,ecco_intel_drill}.py`; its docs |
| ui | `frontend/ecco-intelligence-card/**`; its card and package tests; `home-assistant/{dashboards,packages}/ecco_intelligence.yaml`; its doc |
| policy | `ecco_autonomy/**` except `tests/test_autonomy_boundaries.py`; its doc |
| integration | every other foundation-owned file (this document, the four contract modules, `_cycle_fixtures.py`, `_gen_contract_fixtures.py`, the fixtures, the two contract suites, both boundary suites, the roots file, the README lines, the example profile, the S0 / S1 files) |

For the section 13 work, the work packages own disjoint files; this document and `_cycle_fixtures.py` stay with the
integration (after WP-0 they change only through the integrator), and section 13 already holds the text every package
needs, so no package edits this document.

## 12. CONTRACT CHANGE REQUEST (CCR) procedure

1. A stream that needs a contract change does not edit a foundation-owned file. It writes a CCR into its report: the
   symbol, the change, why, whether it is additive, and the tests that prove it.
2. **Additive** CCRs (a new optional attribute key, a new `SITE_READING_KEYS` entry, a new fixture, a new reason code) are
   applied by the integrator as separate commits during integration.
3. A CCR that touches a symbol of section 8's "not open" list is refused in this slice; it needs an independent adversarial
   review and the owner's decision.
4. Every applied CCR keeps `test_intel_contract_signatures.py` and `test_intel_shadow_cycle_contract.py` passing; a CCR
   that would need either to change is not additive.

The additive CCRs of section 13 (CCR-CFG-1, CCR-TOU-1, CCR-PREF-1) were applied by WP-0 with both suites unchanged.

## 13. SHADOW v0.1 completion: grid-charge TOU classification, configuration-poll freshness, raise-only reserve preference

SHADOW v0.1 adds the missing grid-charge classification of the TOU table, built on the inverter's verified TOU and
charging settings and kept read-only: an unknown, stale or conflicting input blocks the advice it affects, no charging
period is invented, and a configured grid source is never taken as proof that charging will happen. This section is the
contract for that work and for the freshness and preference rules that come with it. Every rule is additive or
tighten-only.

**What does not change.** Nothing in section 8: no new `AdvisoryEnvelope` field, no `tou` status attribute or block, the
null rule, the all-OPEN no-number invariant, the pinned signatures and field sets, `ITEM_GATES`, `REQUIRED_SIGNALS` /
`REQUIRED_READINGS`, `ADVISORY_LIMITS_S` and the 900 s ceiling all stay as they are. The TOU claim is expressed only as
reason codes (13.6).

**Status.** Each rule names the work package (WP) that implements it. WP-0 landed the contract keys, the constants, the
schema v2 data, the shared fixture values and the `build_sources` signature (13.1, 13.2, the constants of 13.3, 13.9).
The engine rules (WP-1, WP-2) are published with the engine, and the runtime rules (WP-3, WP-4) with the Home Assistant
runtime; until the runtime is published, its rules here are the contract it must meet. 13.11 records what integrating
the packages added. The text below is written once, here; no package edits this document (after WP-0 only the
integrator does).

### 13.1 New site readings (additive: CCR-CFG-1, CCR-TOU-1, CCR-PREF-1; WP-0)

| Key | Unit | Value | Source and age |
|---|---|---|---|
| `liveness.config_poll_changed_at` | datetime | the time the dongle's configuration-poll text last changed as the runtime saw it (value = `observed_at`), the twin of `liveness.dongle_poll_changed_at` | the runtime's second liveness memory (13.3); never an I-D6 key |
| `tou.enabled` | bool | the inverter's TOU enable (register 248 bit 0) | the configuration poll (Block B) |
| `tou.grid_charge_enabled` | bool | the grid-charge enable (register 232 bit 0) | the configuration poll (Block A) |
| `tou.overlay_state` | enum `NONE` / `ACTIVE` (`TOU_OVERLAY_STATES`) | `ACTIVE` while Free Power, Dump to Grid or a manual write overrides the table; `NONE` only when every mapped overlay entity is exactly off | dongle telemetry (joins `DONGLE_READINGS`, WP-1) |
| `pref.advisory_reserve_raise_pct` | % | a raise-only advisory reserve preference, 0..100 | an HA helper read every cycle; a preference: it does not age, it is never a decision and never an I-D6 key (13.7) |

`OPTIONAL_READING_KEYS` lists the readings whose absence (not mapped) is never a blocker: `pref.wear_cost_p_per_kwh`,
`pref.normal_max_charge_target_pct` and `pref.advisory_reserve_raise_pct`. An optional reading that is mapped but
unusable may still block (13.7). The other four keys are not optional: from WP-1 and WP-2 on, every item that rests on
the charge window needs them fresh, and `tou.enabled`, `tou.grid_charge_enabled` and `tou.overlay_state` become I-D6
keys (gate readings, UNRESOLVED until a site records a limit; WP-1).

### 13.2 The value of `tou.slot_table`, schema v2 (CCR-TOU-1; data WP-0, judgement WP-2, mapping WP-3)

The data lives in `advisory_contract`: `TOU_SLOT_TABLE_SCHEMA` (2), `TOU_SLOT_TABLE_ROWS` (6), `TOU_SLOT_ROW_KEYS`,
`TOU_CHARGE_SOURCE_BITS` and `TOU_MODE_BITS`. The value is a list of exactly six rows in slot order, each with exactly
these keys:

| Row key | Type | Meaning |
|---|---|---|
| `slot` | int 1..6 | the slot number, in order |
| `start` | `"HH:MM"` | the slot start on the inverter's local wall clock (registers 250-255) |
| `end` | `"HH:MM"` | the next row's start (slot 6 runs into slot 1); derived by the runtime, never mapped |
| `target_soc_pct` | number 0..100 | the slot target SOC (registers 268-273) |
| `charge_source` | text | exactly as the dongle publishes it: `None`, `Grid`, `Generator` or `Grid + Generator` |
| `flags_raw` | int 0..65535 | the slot flags word (registers 274-279): bits 0-1 the source (`TOU_CHARGE_SOURCE_BITS`), bits 2-4 the mode (`TOU_MODE_BITS`); bits 5-15 are not decoded, and any of them set makes the slot UNKNOWN (13.5) |
| `mode` | text | exactly as published: `None`, `General`, `Backup` or `Charge` (the dongle publishes `Unknown 0xNN` for other bits) |
| `power_w` | number >= 0, W | the slot power (registers 256-261) |

A field that is unknown (its entity unavailable or unknown, or its state not parseable) is null, never 0 and never a
guess. There is no per-slot enable. The table is data inside the reading's value, not an envelope field.

**Mapping (WP-3).** The site file's `tou.slot_table` spec lists exactly six slots, each mapping all six entities
`{start, target_soc, charge_source, power, flags_raw, mode}`; anything else is refused. `charge_source` and `mode` pass
through as received (`unavailable` / `unknown` become null), `target_soc` and `power` go through the numeric reader,
`flags_raw` must read as a whole number 0..65535 (otherwise null), and `entity_ids()` covers every slot entity. The
runtime never builds a start / target-only (v1) table again. One entity mapped to two slot fields is refused (a
copy-paste error could hide a second grid slot), and an unknown `start` gives a null `start` (and a null `end` on the
row before) while the table is still published: the planning layer then refuses the ring (`TOU_RING_INVALID`).
`tou.overlay_state` takes a new spec `{"entities": [...]}`: `NONE` only when every listed entity is exactly `off`,
`ACTIVE` when any is `on`, and no reading at all when any is missing or in another state. `tou.enabled` and
`tou.grid_charge_enabled` take the plain `{"entity": ...}` spec (a binary sensor, `on` / `off`).

### 13.3 Configuration-poll freshness (CCR-CFG-1; constants WP-0, rules WP-1, runtime WP-3 and WP-4)

- **Constants (WP-0).** `site_decisions.CONFIG_LIVENESS_KEY = "liveness.config_poll_changed_at"` and
  `site_decisions.CONFIG_POLL_READINGS` = `tou.slot_table`, `tou.current_target_soc_pct`, `tou.enabled`,
  `tou.grid_charge_enabled`, `protection.shutdown_soc_pct`, `capacity.reg204_ah`: the readings the dongle's
  configuration poll (about every 60 s: Block A battery and grid-charge settings, Block B TOU) publishes.
  `stop.dump_soc_pct` is not one: it is a dongle setting that poll does not read.
- **Why.** These values come only from the configuration poll, which is skipped while read-only configuration polling is
  off, during inverter writes and during clock corrections. Aged by the telemetry poll text alone, a frozen table would
  still count as fresh.
- **Rule (WP-1, tighten-only).** Every configuration-poll reading stays in `DONGLE_READINGS` (`tou.enabled` and
  `tou.grid_charge_enabled` join it), so the telemetry liveness rule still applies; its age is the larger of the
  telemetry liveness age and the configuration liveness age. It is fresh only while the telemetry liveness is within
  its bound (180 s), the configuration liveness within `DQ_PROPOSED.config_liveness_max_age_s` = **300 s** (PROPOSED:
  five polls, so one late poll is tolerated) and that larger age within the reading's own I-D6 limit.
- **Codes (WP-1).** `CONFIG_LIVENESS_MISSING` (no reading, or not an aware time), `CONFIG_LIVENESS_IN_FUTURE` and
  `CONFIG_LIVENESS_STALE` BLOCK every item whose required inputs include `CONFIG_LIVENESS_KEY`; `quality.RULE_INPUTS`
  names each with `(CONFIG_LIVENESS_KEY,)`. Unlike `LIVENESS_*`, they are raised on each such item (the finding's
  subject is the item, with the age and bound, or the reason, as evidence); there is no separate finding on the key.
  The bound is a fixed detection constant (`DQ_PROPOSED.config_liveness_max_age_s`), never an I-D6 value.
- **Required inputs (WP-1).** `required_inputs` adds `CONFIG_LIVENESS_KEY` for every item in `CHARGE_WINDOW_ITEMS` and
  whenever a required reading is in `CONFIG_POLL_READINGS` (a function-body change, tighten-only; `REQUIRED_*` stay as
  they are). `overnight_demand` rests on its charge window, so the table's freshness binds it through the window.
- **Never loosened (WP-0 pins it, WP-1 keeps it).** `CONFIG_LIVENESS_KEY` is excluded from `FRESHNESS_OVERRIDE_KEYS`
  exactly like `LIVENESS_KEY`: `freshness_limits` gives it no entry and an I-D6 entry naming it is refused
  (`FRESHNESS_OVERRIDE_UNKNOWN_KEY`: I-D6 INVALID, nothing applied, BLOCK). WP-1 names the pair `LIVENESS_KEYS` in
  `site_decisions` = (`LIVENESS_KEY`, `CONFIG_LIVENESS_KEY`): both are gate readings (so an I-D7 entry may add either,
  tighten-only), neither is an I-D6 key.
- **TOU gate readings (WP-1).** `TOU_GATE_READING_KEYS` in `site_decisions` = `tou.enabled`, `tou.grid_charge_enabled`,
  `tou.overlay_state`: gate readings and I-D6 keys with no default limit (UNRESOLVED until a site records one). The
  quality layer judges all three on every run; the overlay value must be exactly `NONE` or `ACTIVE` (otherwise
  `READING_INVALID`, so it counts as missing).
- **Validity (WP-2).** An item resting on a configuration-poll reading is valid no longer than both liveness bounds
  allow (the planning layer's validity rule takes both liveness keys).
- **Supervision (WP-1).** `supervision.state` and `supervision.stable` join `DONGLE_READINGS`: they are published only
  when they change, so they are observed at the telemetry poll-text change time. The 90 s supervision rule is kept.
- **I-D6 text (WP-1).** `PROPOSED_ANSWERS["I-D6"]` (text only, never applied) is split by key class: 300 s for dongle keys
  (the configuration-poll readings included), 600 s for keys fed by the Home Assistant configuration bridge, 900 s for
  tariff tables; the 900 s ceiling is unchanged. The text is written from three `site_decisions` constants:
  `PROPOSED_D6_CLASS_LIMITS_S` (class -> seconds), `PROPOSED_D6_KEY_CLASSES` (class -> keys) and
  `PROPOSED_D6_NO_PROPOSAL` (`capacity.fe1_wh_per_pct`, `history.hourly`: no cadence observed, no proposal); together
  they partition the I-D6 keys exactly, and the proposal would validate as an I-D6.
- **Runtime (WP-4, WP-3).** The coordinator tracks the configuration-poll text with a second `LivenessMemory` through
  `track_liveness` (WP-4) and passes its change time as `build_sources(..., config_liveness_at=...)`, a keyword-only
  parameter whose signature WP-0 fixed (default None; accepted and not used until WP-3). The
  `liveness.config_poll_changed_at` spec is `{"entity": <the configuration-poll text>, "online_entity": <the dongle's
  configuration-online binary sensor>}` (both required; neither may be the telemetry poll-text entity mapped for
  `liveness.dongle_poll_changed_at`, A33: the map is refused by field path). The `CONFIG_LIVENESS_KEY` reading is published only from
  `config_liveness_at` and only while the online entity is exactly `on`, never parsed from the poll text's state and
  never from a future or naive time (before WP-3 a mapped key gave no reading, note `NOT_WIRED`). The `observed_at` of
  every `CONFIG_POLL_READINGS` reading is the older of the telemetry and configuration liveness times; without either
  time those readings are withheld (note `NO_CONFIG_LIVENESS`), so the charge-window items BLOCK.
- **Bridge render time and attribute readings (WP-3, runtime only, tighten-only).** A reading or signal aged by its own
  report time (not a dongle, configuration-poll, liveness, overlay or preference key; the supervision readings are dongle
  readings since WP-1) may name `fresh_by: refreshed_at`: its observed time is then the older of that attribute and
  `last_updated`, and it is withheld (a `FRESH_BY_*` note, so the requiring items BLOCK `INPUT_NOT_FRESH`) when the
  attribute is missing, unparseable, naive, in the future or more than 5 s from `last_updated`. A numeric reading of
  that class may name an `attribute` (and one nested `key`); a value that is not a finite number, or any value while the
  entity is unavailable, is missing, never 0.

### 13.4 Validity and the refresh margin (engine WP-2, runtime WP-4)

- `REFRESH_MARGIN_S = 125` is an engine constant (`intelligence/shadow_cycle.py`): two 60 s runtime ticks plus 5 s, the
  shortest validity that is shown without a gap between ticks.
- An OK item whose validity at compute time (`valid_until - now`) is below `REFRESH_MARGIN_S` becomes BLOCKED with
  `INPUT_EXPIRING` (per item, tighten-only, no number). It therefore no longer shortens the whole envelope (which is valid
  until its first OK item expires): an item resting only on slow inputs, such as `pv_tomorrow`, stays OK while a TOU item
  expires.
- **The inputs of the quality gates (A31).** An item's validity is bounded by its required inputs, its charge-window
  sources, the event list (export and Dump) and both liveness readings, and also by the inputs of the quality-layer gates
  it rests on (`VALIDITY_GATE_READINGS`, `intelligence/shadow_cycle.py`): `inverter.clock_offset_s` bounds every
  charge-window item (`CHARGE_WINDOW_ITEMS`; the quality layer gates them on it with `CHARGE_WINDOW_CLOCK_*`).
  Tighten-only: with a short I-D6 limit for the clock offset the charge-window items are valid only as long as it is
  fresh (or `INPUT_EXPIRING`).
- **Documented exemption: supervision (A31).** The supervision readings (`quality.SUPERVISION_KEYS`: state, stable and
  the heartbeat, each bounded at 90 s) gate export and Dump advice (`SUPERVISION_NOT_STABLE`) but are deliberately not in
  any item's validity: the 90 s bound is shorter than `REFRESH_MARGIN_S`, so including them would make export and Dump
  permanently `INPUT_EXPIRING`. Supervision is enforced at every compute instead. The **worst-case exposure** of a
  published OK `export_event` or `dump_to_grid` after the supervision lapses is the time to the next compute:
  - while telemetry polls arrive, the runtime's poll-driven refresh (A23) computes after every poll: about one telemetry
    poll plus `PROPOSED_POLL_SETTLE_S` plus the compute time;
  - when the polls stop, no poll-driven compute comes, and the tick holds its refresh for validity or `INPUT_EXPIRING`
    while the last poll seen is at most `PROPOSED_POLL_ACTIVE_S` (90 s) old. The first refresh (the dongle items
    `INPUT_EXPIRING`, export and Dump `SUPERVISION_NOT_STABLE` once supervision has lapsed) therefore starts at the
    first tick after that: at most about 150 s after the last poll (90 s plus one 60 s tick), plus the compute time, so
    a supervision lapse just after the last poll's compute is exposed for up to about 150 s;
  - in every runtime state (the CPU guard, the refresh switch off, a time-budget bar, a failed cycle) the item never
    outlives its own validity: the runtime nulls every number whose `valid_until` falls before the publish horizon
    (STALE), and an export or Dump item is valid at most the 180 s liveness bound after the telemetry poll it rests on.

  No bound, margin or limit changes. The engine suite pins the exemption (an OK Dump item valid for the liveness bound,
  longer than the supervision gate has left, and `SUPERVISION_NOT_STABLE` at the next compute after the lapse); the
  runtime suite pins both runtime halves (supervision stops while polls continue: export and Dump BLOCKED
  `SUPERVISION_NOT_STABLE` at the first poll-driven compute after the lapse; the polls stop: every item resting on a
  dongle input loses its number no later than the first tick after the last poll plus `PROPOSED_POLL_ACTIVE_S`, and
  never holds one past its inputs' bound; with the supervision heartbeat stopped too, the first compute after the last
  poll's BLOCKs export and Dump `SUPERVISION_NOT_STABLE`). **Any ASSISTED use of export or Dump validity needs
  supervision in the validity first; that is a separate owner decision.**
- **Refresh before expiry (WP-4, runtime only).** A refresh cycle starts at a tick when less than `REFRESH_MARGIN_S` of
  the envelope's validity is left, or when the published result holds an item or forecast BLOCKED `INPUT_EXPIRING`
  (integration fixup: such an item is withheld until its inputs are refreshed, and since it no longer shortens the
  envelope's validity, that validity alone would keep it withheld until the envelope nears its end, up to the 900 s
  advice validity), at most once a tick (55 s floor), with a CPU guard of 180 s per rolling hour (refreshes suspended,
  slot cycles continue; the only effect is STALE) and the existing second-run guard. A drift test compares the runtime's
  margin with the engine constant. `next_run_at` = min(the next slot, `valid_until` - margin), or the refresh floor while
  an item is BLOCKED `INPUT_EXPIRING`. STALE keeps its meaning; no contract change.
- **Poll-phase-aligned refresh (A23, runtime only; cadence, no rule change).** The dongle's telemetry poll text moves about
  every 60 s on the target platform, and the 60 s tick holds a near-fixed phase against it; a refresh started more than 55 s after a poll
  would withhold every item resting on a dongle input (`INPUT_EXPIRING`: the 180 s liveness bound less the 125 s margin).
  The coordinator therefore holds exactly one state listener (`async_track_state_change_event`), on the entity the site
  file maps for `liveness.dongle_poll_changed_at` (none when it is not mapped), removed on unload. A new poll text (not a
  replay of the last one, not unavailable, unknown or `Waiting`) schedules one poll-driven step
  `PROPOSED_POLL_SETTLE_S` = **3 s** later (`async_call_later`, at most one pending, cancelled on unload), so the rest of
  that poll's entity writes land first; a later poll never moves a pending step later (it keeps the earliest due time,
  A33). That step starts a due slot cycle, or a refresh when the published result is
  STALE (after its back-off), has less than `POLL_REFRESH_THRESHOLD_S` = margin + `PROPOSED_POLL_INTERVAL_S` (60 s) =
  **185 s** of validity left (so the margin is never entered between two polls), holds an item BLOCKED `INPUT_EXPIRING`,
  or holds an item BLOCKED for an input reason (a blocker among the quality rules whose inputs name a live signal or site
  reading, `TOU_*`, `CHARGE_WINDOW_*`, `TARIFF_*`, `PREF_RESERVE_RAISE_UNKNOWN`, `CALLER_FRESHNESS_DISAGREES`; so recovery
  after a transient input fault takes one poll, not up to the 835 s ceiling). A refresh inside the 55 s floor is deferred
  to the floor's end, never dropped; while a cycle is in flight the step waits for its end, then runs (a poll that
  arrived while it waited keeps the step, A33, and is served by it). **The settle hold (A36): no cycle starts inside the
  settle delay of the newest poll seen.** At the one place a cycle starts, a cycle of any trigger whose start would fall
  before the newest poll seen plus `PROPOSED_POLL_SETTLE_S` is held once to that moment, on the one pending step (a step
  already pending by then serves it; a poll-driven step starts whatever the tick would). The cases are exactly: a
  refresh the tick asks for after STALE (also after its back-off), the exception retry, the tick's exception to its
  hold, a poll-driven step that a newer poll kept (a step deferred to the floor's end when a newer poll arrives in the
  last 3 s of the floor, a step under a poll text faster than the settle delay) and a step re-armed when a cycle in
  flight ends inside a newer poll's settle delay. The hold is one-shot, at most `PROPOSED_POLL_SETTLE_S`, never re-armed
  by a later poll (so a sub-settle poll period cannot starve it), and never applies when no poll was seen within the
  settle delay. A cycle that started after the poll was seen has therefore read it already (the step is covered). One
  residual is documented, not fixed: two polls within one settle delay (an abnormal sub-settle poll period), where the
  held cycle starts inside the second poll's settle delay and can rest on values up to one poll older than its stated
  freshness, until the next compute (at the latest the item's own validity). Writes that land more than the settle
  delay after the text are outside it by definition (L3 checks the ordering on the real Core). While poll-driven steps
  are arriving (a new poll text within `PROPOSED_POLL_ACTIVE_S` =
  1.5 polls = **90 s**), the tick starts no slot cycle (the next poll-driven step does,
  so every slot result is phased like a refresh) and no refresh for validity or `INPUT_EXPIRING` unless the published
  envelope would go STALE at the next tick before the next expected poll-driven step; so a badly phased tick never
  replaces a good result with a worse one. When the poll text stops moving the tick resumes its present rules, so a
  frozen dongle fails closed (the dongle items BLOCK). **Acceptance (A32, which amends A23's):** healthy polls (60 s plus
  or minus 3 s, at any phase) give no STALE and no `INPUT_EXPIRING` over 3 h; a missed, late or frozen poll gives at most
  one STALE cycle per episode (a tick whose publish horizon passes the result's validity while the hold still expects a
  poll-driven step writes STALE before the refresh it starts; inside a poll's settle delay that refresh is held to the
  delay's end, A36, so the STALE row stands up to 3 s longer), never a wrong number, then the fallback (frozen) or the
  recovery at the next poll plus the settle delay (deferred to the 55 s floor's end when the tick's refresh started less
  than 55 s before). That STALE is accepted as fail closed (it nulls every item, stricter than per-item blocks); no
  staleness rule changes, and T3 / R3 stay as A13 (STALE in at most 1 % of minutes, runs of at most two ticks). The L2
  suite counts STALE from the stand-in's recorder rows. The pause helper, the self-test, the second-run guard, the CPU guard, the
  time-budget bar and the refresh switch apply to the poll-driven step unchanged. While polls are arriving `next_run_at`
  keeps its meaning, the earliest moment the next cycle can start: `valid_until` - `POLL_REFRESH_THRESHOLD_S`, or the
  floor while an item is BLOCKED for an input reason. No limit, margin, floor value, gate, validity or published item
  value changes. The PROPOSED values are runtime engineering choices (`const.py`), not owner values; the diagnostics show
  them, the cadence state (`polls_arriving`, `last_poll_seen_at`, `poll_step_due`, `poll_step_settle_hold`,
  `tick_poll_phase_s`; the counters `settle_holds`, `settle_held_starts`, `settle_residual_starts`) and, per cycle in
  `cycle_stats`, what started it (`TICK` / `POLL`) and the poll text's age at its start (the tick-to-poll phase L3 logs).
- **Caller agreement (WP-4, tighten-only).** `engine_link.advisory_overrides` sets each dongle signal's limit to
  min(its limit, the quality layer's liveness bound); a missing limit stays unset. The caller and the quality layer then
  agree, so `CALLER_FRESHNESS_DISAGREES` no longer blocks the items that rest on no dongle input while the dongle is
  frozen, so history-only items stay visible then (accepted: amendment A29, V-4).
- **Recorder load (WP-4).** The runtime may keep the timestamp-only attributes `generated_at`, `valid_until` and
  `next_run_at` out of Home Assistant's recorder (`_unrecorded_attributes`; `input_ages` is already unrecorded) only if
  every published value stays identical. `to_entity_payloads`, `RECORDED_ATTRIBUTES` and `UNRECORDED_ATTRIBUTES` do not
  change: they say which part of a payload an attribute belongs to, and the null rule is judged on the values.

### 13.5 The grid-charge classification of the TOU table (WP-2; fail closed)

A new pure module `intelligence/tou_table.py` replaces `daily_plan.tou_window`; the single-slot fallback, the grid-flag
guess and the tariff / TOU overlap rule are deleted.

**Slot class.** By the exact texts only: `Grid` and `Grid + Generator` are GRID; `None` and `Generator` are NOT_GRID. A
slot is UNKNOWN when its `charge_source` or `mode` is null or not one of the exact texts, or its `flags_raw` is null or
disagrees with them (`flags_raw & 0x03` against the source, `flags_raw & 0x1C` against the mode), or has any bit outside
`0x1F` set (`tou_table.DECODED_FLAGS_MASK`: bits 5-15 are not decoded, so their meaning is unknown; A33). A slot is
**effectively GRID** only when it is GRID, `tou.enabled` and `tou.grid_charge_enabled` are fresh and true, and
`tou.overlay_state` is fresh and `NONE`.

**BLOCK codes.** Each BLOCKs every item that rests on the charge window (`CHARGE_WINDOW_ITEMS` and `overnight_demand`):

| Code | When |
|---|---|
| `TOU_TABLE_LEGACY_SCHEMA` | a v1 table (rows without `charge_source`, such as start / end / target only) |
| `TOU_TABLE_MALFORMED` | not a list of mappings, a row key missing or outside `TOU_SLOT_ROW_KEYS`, `slot` not 1..6 in order, a field of the wrong type or out of range |
| `TOU_RING_INVALID` | not exactly six rows, a null or invalid `start` / `end`, an `end` that is not the next row's `start`, a zero-length slot, or not exactly one wrap past midnight |
| `TOU_SLOT_SOURCE_UNKNOWN` | any slot is UNKNOWN (an unknown slot could be a second grid window) |
| `TOU_SOURCE_DECODE_CONFLICT` | added when a slot is UNKNOWN because `flags_raw` disagrees with its texts |
| `TOU_FLAGS_UNDECODED_BITS` | added when a slot is UNKNOWN because `flags_raw` has a bit outside `0x1F` set (A33) |
| `TOU_SLOT_TARGET_UNKNOWN` | any slot's `target_soc_pct` is null |
| `TOU_SLOT_POWER_UNKNOWN` | any slot's `power_w` is null |
| `TOU_ENABLE_UNKNOWN` / `TOU_DISABLED` | `tou.enabled` missing, not fresh or not a bool / false |
| `TOU_GRID_CHARGE_ENABLE_UNKNOWN` / `TOU_GRID_CHARGE_DISABLED` | `tou.grid_charge_enabled` missing, not fresh or not a bool / false |
| `TOU_OVERLAY_STATE_UNKNOWN` / `TOU_OVERLAY_ACTIVE` | `tou.overlay_state` missing, not fresh or not one of `TOU_OVERLAY_STATES` / `ACTIVE` |
| `TOU_NO_GRID_SLOT` | no slot is effectively GRID |
| `TOU_MULTIPLE_GRID_WINDOWS` | the effectively GRID slots form more than one separate run around the ring |
| `TOU_SLOT_POWER_ZERO` | a slot of the run has `power_w` 0 |
| `CHARGE_WINDOW_CROSSES_MIDNIGHT` | the run crosses local midnight (a WARN before; now a BLOCK) |
| `CHARGE_WINDOW_NOT_REPRESENTABLE` | the run lasts the whole day (a WARN before; now a BLOCK) |

**The window.** The single maximal run of ring-adjacent, effectively GRID slots, at its next occurrence that ends after
`now`. Its input keys are the table, both enables and the overlay reading, and its validity is bounded by them and by
both liveness keys. No period is invented, and the SiteConfig example window is never used.

**With a VERIFIED tariff.**

| Sources | Result |
|---|---|
| a VERIFIED tariff that names a cheap run and a classified TOU window | the TOU occurrence, clipped to `[max(now, start), end)`, is checked against the tariff's rate slots (A30): every slot overlapping it priced in the cheap band (at or below `CheapWindow.ceiling_p_per_kwh`) gives the TOU window, with INFO `CHARGE_WINDOW_TOU_INSIDE_TARIFF` and INFO `CHARGE_WINDOW_FROM_TARIFF` (the window is still the TOU window; the tariff block keeps its provenance and prices); a slot above the ceiling BLOCKs `CHARGE_WINDOW_SOURCES_DISAGREE` (the overlap rule is removed); slots that do not cover the clipped occurrence BLOCK `CHARGE_WINDOW_TOU_UNCHECKED` |
| a VERIFIED tariff that names no cheap run (search period not covered, the window check's judgement below; no slot ahead, no run long enough, a run too long or no spread) and a classified TOU window | the same clipped occurrence is checked against the slots the tariff prices (A35): any slot overlapping it priced at or above `low` + `PROPOSED_MIN_CHEAP_SPREAD_P_PER_KWH`, where `low` is the lowest rate among the slots that overlap `[now - PROPOSED_WINDOW_SEARCH_H, now + PROPOSED_WINDOW_SEARCH_H)` (`tariff.horizon_low_p_per_kwh`, whatever slots exist, the slot that holds `now` included: the look-back, A38), BLOCKs `CHARGE_WINDOW_SOURCES_DISAGREE`, also when the occurrence is only partly priced; otherwise the TOU window, with the existing WARN `CHARGE_WINDOW_FROM_TOU_TABLE`, whose text says which case applies (every priced slot within the spread, or the tariff does not price the whole TOU window, no slot ahead included), and in the second case also INFO `CHARGE_WINDOW_NOT_PRICED` (A41); the tariff's own `TARIFF_*` WARN stays. A tariff that does not price the window gives nothing to conflict with, so that alone is no BLOCK here (unlike a named run, row above) |
| a classified TOU window and no VERIFIED tariff | the TOU window, with the existing WARN `CHARGE_WINDOW_FROM_TOU_TABLE` (its text says no verified tariff) and INFO `CHARGE_WINDOW_NOT_PRICED` (A41) |
| a VERIFIED tariff that names a cheap run and a fresh table that does not classify | BLOCK `CHARGE_WINDOW_TOU_UNCHECKED` (a WARN before) |
| a fresh table that does not classify beside no VERIFIED tariff, or one that names no cheap run | BLOCK `CHARGE_WINDOW_UNKNOWN`, with the table's own code from the table above |
| no fresh table | BLOCK, as before (`CHARGE_WINDOW_UNKNOWN` from the quality layer) |

The check never uses the cheap run's start and end: `tariff.cheap_window` finds the run among the slots still running at
`now` and cuts it at its 24 h search horizon, so in a window and near the horizon those boundaries are not the tariff's
(the cause of a false disagreement for most of every window before A30). The tariff's cheap run may cross local
midnight; only the TOU window must lie on one local date (a TOU run across midnight BLOCKs above). Every
`CHARGE_WINDOW_*` code keeps exactly its 13.8 severity: the tariff path emits no `CHARGE_WINDOW_CROSSES_MIDNIGHT` or
`CHARGE_WINDOW_NOT_REPRESENTABLE` of its own.

**Which judgement of the import rates (ENG6-1).** The cycle judges the one `tariff.import_rates` reading twice. With the
coverage need `[now, now + PROPOSED_WINDOW_SEARCH_H)` it gives `TARIFF_VERIFIED`, the prices, the tariff block's
provenance and price range, and the value. Without that need, and with the same parse, freshness and future-dated
gates, it gives the window check above. A reading that passes every gate but does not cover the search period is
therefore, for the window check, a VERIFIED tariff that names no cheap run (`cheap_window` refuses it with
`TARIFF_COVERAGE_SHORT`, so it never sets or confirms the window: the second row applies), while the envelope's tariff
provenance stays `NOT_VERIFIED` and no price or value is shown. This is tighten-only: the result is the A35 BLOCK or the
same TOU window with the same WARN. A reading that is missing, stale, malformed or future-dated is no VERIFIED tariff in
either judgement (third row).

**Without a named run (A35).** `cheap_window` names no run for any smooth tariff, or after one shoulder slot within 2 p
of the cheapest rate anywhere in the next 24 h, so a verified tariff never skips the check: a priced slot of the TOU
occurrence that conflicts blocks. The no-run threshold (`PROPOSED_MIN_CHEAP_SPREAD_P_PER_KWH`, 2 p) is deliberately
wider than the named run's band (`PROPOSED_CHEAP_BAND_P_PER_KWH`, 0.5 p): without a named run, only a slot clearly
above the cheapest rate is a conflict. A flat tariff passes; a smooth Agile-style tariff passes only where the window
is within 2 p of `low`, the lowest rate priced in the 24 h before and after `now`; a plunge price anywhere in that
period can BLOCK (fail closed). The comparison is on the difference rounded to the slots' own 0.0001 p precision, so a
slot exactly at the spread counts as at it. No PROPOSED value changes.

**The look-back (A38 Part A).** `low` is the lowest rate among the slots of the window-check judgement (above) that
overlap `[now - PROPOSED_WINDOW_SEARCH_H, now + PROPOSED_WINDOW_SEARCH_H)`: the 24 h search period and the 24 h before
`now`. The slot that holds `now` counts; a slot that ended exactly 24 h before `now`, or starts exactly 24 h after it,
does not. Only `low` looks back: the slots checked against it are still those overlapping the clipped TOU occurrence,
and the named-run path (`cheap_window`, its band and `CheapWindow.ceiling_p_per_kwh`) is unchanged and never looks
back. A lower `low` can only add BLOCKs (tighten-only). The reason: one day-rates event (section 3) prices one local day, so
without the look-back `low` came from the rest of that day only, and once the night's cheap run had passed, a TOU window
misplaced to the evening peak was compared with the dear rates left and stood OK for most of the day.

**Known fail-closed limitation (F2, A35; widened by A38).** Because `low` is the lowest rate priced from 24 h before
`now` to 24 h after it, a correctly placed window BLOCKs `CHARGE_WINDOW_SOURCES_DISAGREE` (no number) whenever a slot
of its occurrence is priced 2 p or more above the cheapest rate of that whole period, although tariff and TOU agree:

- a price drop: on the night a cheap rate falls by 2 p or more at local midnight (a tariff or price-cap change), the
  low comes from the next night, so tonight's cheap slots lie above the band's ceiling (with a named run) or at least
  the spread above that rate (without one), for most of that night (A35);
- a price rise: after the cheap rate rises by 2 p or more (a tariff or price-cap change), a reading that still prices
  the old, cheaper slots gives the low from them, so without a named run the window BLOCKs until the last of those
  slots is 24 h old (A38). With a named run the band decides and the look-back plays no part, so a two-rate tariff
  whose night rate rises keeps its window;
- a dynamic tariff, said plainly: on an Agile-style tariff, which names no cheap run, any day whose window slots are
  priced 2 p or more above the cheapest slot of the previous 24 h or the next 24 h that the reading prices BLOCKs the
  window, and every item on it (the charge target, the morning SOC, export, Dump, the overnight demand), for as long
  as that cheaper slot stays in the period. On such a tariff the charge advice can be withheld for many cycles of
  many days. This is fail-closed (no number, never a wrong number) and accepted; it is not a fault of the TOU table.

Smaller differences never do (the planning suite pins the drop, the rise and the agreeing windows). Narrowing the
lowest-rate search to the TOU window would be a loosening (a window at the evening peak, looked at in the afternoon,
would read as cheap), so it is not done.

**What remains on one day-rates event (ENG6-1, ENG6-2, A38).** With the single form the runtime passes the rows of one
mapped rate event (section 3). With the look-back the check compares the TOU occurrence with the cheapest slot that event
prices, passed or not: with the current-day event, a TOU window misconfigured to the evening peak BLOCKs
`CHARGE_WINDOW_SOURCES_DISAGREE` at every cycle of the day until today's occurrence has ended (the night's cheap slots
stay in the look-back); with the next-day event it BLOCKs once the occurrence is the next day's. A TOU window equal to
the cheap run never disagrees. Accepted residual (visible as INFO `CHARGE_WINDOW_NOT_PRICED`, below): a TOU occurrence
the reading does not price at all (it lies beyond the payload's last slot, or before its first) has nothing to conflict
with, so it keeps the WARN `CHARGE_WINDOW_FROM_TOU_TABLE` (its text: "... does not price the whole TOU window"), the
charge-window items carry INFO `CHARGE_WINDOW_NOT_PRICED`, and the advice stands on the TOU table alone. With the
current-day event that is from the end of today's occurrence until local midnight (the longer, the earlier the window
ends); with the next-day event alone, from local midnight until today's occurrence has ended. During those hours an OK
charge target does not show that the TOU window lies in the cheap run. A one-day reading still names no cheap run
outside local midnight and gives no price or value; the tariff's `TARIFF_COVERAGE_SHORT` and the `NOT_VERIFIED`
provenance show the case, and the planning suite pins it.

**With the day events (A38 Part B, CCR-RT-DAYS: the contract the Home Assistant runtime implements).** The production
site file maps the import rates as the current-day and next-day events, `[current day, next day]` (section 3, A42). The
three-event form, with the previous-day event first, is allowed; the previous-day event is added only by a later
decision, once a readiness read shows its report cadence within its I-D6 limit. The current day is always priced, so the
look-back always finds today's cheap slots (in the three-event form also the previous day's), and once the next day's
rates are published (in the afternoon) the reading covers the search period, so the window is checked against its whole
priced occurrence: by the named run (A30), or, for a tariff that names none (for example a flat one), by the A35 spread
check; prices and value return. A TOU window misconfigured to the evening peak BLOCKs `CHARGE_WINDOW_SOURCES_DISAGREE`
at every cycle of the day (the runtime suite `test_runtime_tariff_days` pins it at every half-hour, the next day's rates
appearing at 16:00). The accepted residual is limited to the hours before the next day's rates are published: an
occurrence that is tomorrow's (today's has ended) while tomorrow is not yet priced keeps the WARN "... does not price
the whole TOU window" and INFO `CHARGE_WINDOW_NOT_PRICED`. A window that ends after the publication time has no such
hours; one that ends earlier has them from its end until the publication. All of this holds only while the merged table
is accepted and fresh: a table the runtime refuses, one with a gap (`TARIFF_GAP`) and one whose oldest event is not
re-reported within its I-D6 limit (`TARIFF_NOT_FRESH`) give no usable tariff, so the window stands with the WARN "no
verified tariff" and INFO `CHARGE_WINDOW_NOT_PRICED` (INTELLIGENCE_HA_RUNTIME, risk 8).

**Only the codes of WARN and INFO findings are published; the residual's code (A41).** A WARN or INFO finding's text
stays inside the engine: the published items carry its code only. A BLOCK finding's text is published as its blocker
text (section 6, `blockers[{code,text}]`: a fixed, value-free phrase, guarded against value-shaped tokens), but the
residual's WARN text is not. The WARN `CHARGE_WINDOW_FROM_TOU_TABLE` is the same code for a window whose whole
occurrence a verified tariff priced within the spread and for one that no price check covered. INFO
`CHARGE_WINDOW_NOT_PRICED` tells them apart. It is emitted on every charge-window item whose window stands on the TOU
table without a price check of its whole clipped occurrence: no usable verified tariff for the window check (none
mapped, refused, stale, gapped or otherwise not verified), or a verified tariff that names no cheap run and does not
price the whole occurrence (the residual above, no slot ahead included). It is not emitted when the whole occurrence was
priced and found within the spread, never beside `CHARGE_WINDOW_TOU_INSIDE_TARIFF` (a named run checked it) and never on
a refused window. It carries no number, never blocks and changes no status, value or validity. It is how the residual is
observed in the 72 h technical acceptance and the 7-day recommendation-quality monitoring: the cycles whose **OK**
`charge_target` carries it are the cycles whose charge advice stood on the TOU table alone. The code is on every
charge-window item whatever its status, so on a BLOCKED or INSUFFICIENT_DATA item (blocked for another reason, such as
`INPUT_EXPIRING`, `DEMAND_NOT_AVAILABLE` or `DST_BOUNDARY_IN_CHANGED_HOUR`) it says only that the window was not
price-checked: that cycle published no charge advice, and the count leaves it out.

**Power cap.** The grid-charge power handed to `apply_to_siteconfig` is min(`limits.max_grid_charge_w`, the lowest
`power_w` in the run): it can only lower it.

**Not modelled.** The register-230 grid-charge current limit: WARN `GRID_CHARGE_CURRENT_LIMIT_NOT_MODELLED` (no number)
on `charge_target`, `predicted_morning_soc` and the internal `v1_summary`, until a later change models it with a fresh
battery-voltage reading.

### 13.6 What the advice may claim (WP-2)

- Exactly one INFO code of `TOU_CLAIM_CONFIGURED`, `TOU_CLAIM_NOT_EXPECTED` and `TOU_CLAIM_UNCERTAIN`, only on an OK
  `charge_target` and an OK `predicted_morning_soc`, never on another item and never under another status. It carries no
  window, target or other number (its text is a fixed phrase) and never upgrades an item.
- **CONFIGURED** ("the inverter is configured to grid-charge in this window up to its slot target") needs all of: one
  target across the run, above the highest plausible SOC at the window start (low load, high PV); `power_w` above 0 and
  `limits.max_grid_charge_w` above 0; `inverter.healthy` fresh and true; a fresh clock offset within its bound; a fresh,
  classified table with both enables on and no overlay. **NOT_EXPECTED**: the target is at or below the lowest plausible
  SOC at the window start (high load, low PV). **UNCERTAIN**: anything else.
- **Cap (fail closed).** While register 248 bits 1-15 are not decoded (they may restrict TOU to some weekdays),
  CONFIGURED is replaced by UNCERTAIN. The cap is one engine constant whose default is capped; lifting it needs the
  owner's decision and an independent review.
- **Morning SOC.** `predicted_morning_soc` starts from the planned SOC at the window end, so it carries WARN
  `MORNING_SOC_ASSUMES_CHARGE` while the claim is not CONFIGURED (with the cap: always). No advice text says that charging
  will happen: a grid-sourced slot is necessary, never sufficient.
- `inverter.healthy` gates only the claim; it is not added to `REQUIRED_SIGNALS`.

### 13.7 The raise-only reserve preference (engine WP-2, runtime WP-3)

- `pref.advisory_reserve_raise_pct` can only raise the advisory planning floor above I-D1: floor = max(the I-D1 floor,
  the raise). It never lowers anything, never changes I-D1, I-D2 or the technical minimum, never becomes a decision, and
  no firmware feature honours it (Dump to Grid honours no planning floor).
- **Runtime.** An unmapped helper gives no reading. A mapped helper gives the reading every cycle: the number when its
  state is a finite percentage in 0..100, otherwise value null (unavailable, unknown, not numeric, out of range), with
  `observed_at` its state's observed time, or the cycle time when the entity is absent. It is never dropped while mapped,
  and a missing value is never 0.
- **Engine.** No reading: no raise. A usable reading strictly above the I-D1 floor, the technical minimum and the HA
  helper's value (when one is supplied) raises the floor, with INFO `PREF_RESERVE_RAISE` (no number); one at or below
  any of them changes nothing and adds no code. A reading that is present but unusable (`SiteReading.problems()`, a
  value that is not a finite number in 0..100, an observation time in the future) BLOCKs `PREF_RESERVE_RAISE_UNKNOWN`
  on every item I-D1 gates, so a raised reserve never falls back silently.
- **Never reported as the HA helper (A33, ENG-5).** The preference is a run-time input of its own beside the HA reserve
  helper (`SiteConfig.effective_reserve(ha_reserve_pct, reserve_raise_pct)`, and a `reserve_raise_pct` field on every
  advisor input that takes the helper), so every consumer of the effective reserve takes both. The published reserve
  breakdown (`summary.reserve` of `charge_target`, `export_event` and `dump_to_grid`) keeps `ha_reserve_pct` as the
  helper's own value and adds `reserve_raise_pct` (present whenever a usable preference is supplied, absent otherwise,
  so the V1 breakdown is unchanged). When the preference binds (strictly above the I-D1 floor, the technical minimum and
  the helper), `binding` is `reserve_raise` and `override_code` is `PREF_RESERVE_RAISE` with a text that names the
  preference; `HA_RESERVE_RAISES_USER_RESERVE` (binding `ha_reserve`) appears only when the helper itself binds. The
  `binding` values are `user_reserve`, `technical_min`, `ha_reserve` and `reserve_raise`. No number changes: the floor
  is the same maximum as before.
- `DECISION_VALUE_FROM_HELPER` (WARN) on every item I-D1 gates while a satisfied I-D1 takes its value from the HA helper
  (source `HA_RESERVE_HELPER`), so a helper never acts as a decision unseen.
- The helper entity lives in its own package (published with the presentation package), not in
  `ecco_intelligence.yaml`.

### 13.8 New and changed reason codes

| Code | Severity | On | Rule |
|---|---|---|---|
| `CONFIG_LIVENESS_MISSING`, `CONFIG_LIVENESS_IN_FUTURE`, `CONFIG_LIVENESS_STALE` | BLOCK | every item requiring the configuration-poll liveness | 13.3 (WP-1) |
| `INPUT_EXPIRING` | BLOCK | an otherwise OK item valid for less than `REFRESH_MARGIN_S` | 13.4 (WP-2) |
| `TOU_TABLE_NOT_FRESH` | WARN | the charge-window items and `overnight_demand`, beside the quality layer's BLOCK `CHARGE_WINDOW_UNKNOWN` when no fresh table exists | 13.5 (WP-2) |
| the `TOU_*` table codes of 13.5 | BLOCK | the charge-window items and `overnight_demand` | 13.5 (WP-2) |
| `CHARGE_WINDOW_TOU_UNCHECKED`, `CHARGE_WINDOW_CROSSES_MIDNIGHT`, `CHARGE_WINDOW_NOT_REPRESENTABLE` | BLOCK (each a WARN before) | as above | 13.5 (WP-2) |
| `CHARGE_WINDOW_SOURCES_DISAGREE` | BLOCK, always (the overlap WARN is removed) | as above | 13.5 (WP-2; A30 with a named cheap run, A35 without one, its `low` looking back 24 h: A38) |
| `CHARGE_WINDOW_FROM_TOU_TABLE` (existing) | WARN, unchanged | the charge-window items | 13.5: the planning layer emits it only when nothing conflicts (A30, A35), its text saying which case applies; the quality layer's WARN of the same code is dropped only when the tariff checks and accepts the window (`CHARGE_WINDOW_FROM_TARIFF`), so it stays among the reason codes beside the BLOCK of a refused window (no number) (ENG6-3) |
| `CHARGE_WINDOW_FROM_TARIFF` (existing) | INFO | the envelope's top-level codes and `charge_target`, `export_event`, `dump_to_grid`, `predicted_morning_soc` | 13.5 (A30): a VERIFIED tariff's named cheap run checked and accepted the TOU window (beside `CHARGE_WINDOW_TOU_INSIDE_TARIFF`); the window is still the TOU window, and a tariff alone is never a window |
| `CHARGE_WINDOW_TOU_INSIDE_TARIFF` | INFO | the charge-window items | 13.5 (WP-2) |
| `CHARGE_WINDOW_NOT_PRICED` | INFO | the charge-window items | 13.5 (A41): the window stands on the TOU table without a price check of its whole occurrence (no usable verified tariff for the window check, or one that does not price the whole occurrence); never beside `CHARGE_WINDOW_TOU_INSIDE_TARIFF`, never when the whole occurrence was priced within the spread, never on a refused window; it blocks nothing and changes no status or number; on an item that is not OK it says only that the window was not price-checked (13.5) |
| `GRID_CHARGE_CURRENT_LIMIT_NOT_MODELLED` | WARN | `charge_target`, `predicted_morning_soc`, `v1_summary` | 13.5 (WP-2) |
| `TOU_CLAIM_CONFIGURED`, `TOU_CLAIM_NOT_EXPECTED`, `TOU_CLAIM_UNCERTAIN` | INFO | an OK `charge_target` and an OK `predicted_morning_soc` only | 13.6 (WP-2) |
| `MORNING_SOC_ASSUMES_CHARGE` | WARN | `predicted_morning_soc` | 13.6 (WP-2) |
| `PREF_RESERVE_RAISE` | INFO | the items I-D1 gates, when the raise binds | 13.7 (WP-2) |
| `PREF_RESERVE_RAISE_UNKNOWN` | BLOCK | the items I-D1 gates | 13.7 (WP-2) |
| `DECISION_VALUE_FROM_HELPER` | WARN | the items I-D1 gates | 13.7 (WP-2) |

Every code is at most `MAX_CODE_CHARS` long, and every text stays value-free (section 6 and the planning layer's text
guard).

### 13.9 The shared fixture (WP-0)

`intelligence/tests/_cycle_fixtures.py` gives every reading above a fresh, well-formed value that already meets 13.3 to
13.7: the configuration-poll liveness 30 s old; the TOU table in the schema v2 shape (`TOU_TABLE_V2`) with exactly one
`Grid` slot, 01:00-04:30 (the same window as before, never the example window), five `None` slots, flags agreeing with
the texts and every slot's power equal to the fixture's grid-charge limit (so the power cap lowers nothing); both
enables on; the overlay `NONE`; a raise preference of 0 % (usable, never above any floor). Wiring the rules therefore
changes no expectation built on the fixture. All values are synthetic (2030).

### 13.10 Changes that leave this contract alone

The deploy route and the isolated test Home Assistant (kit equivalence, the `-Target Test|Production` guard, per-segment
symlink refusal, the toolbox, the card check and the container setup), the preferences package and the documentation
of the presentation package, and the acceptance and process rules change no symbol, reading or rule of this contract.
They are documented where they land.

### 13.11 Integration notes (phase 3)

What merging WP-0 to WP-4 added, beyond each package's own rules (each a separate integration commit):

- **Refresh on `INPUT_EXPIRING` (runtime).** The refresh trigger of 13.4 also fires while the published result holds an
  item BLOCKED `INPUT_EXPIRING`, so such an item is recomputed at the next tick instead of when the envelope nears its
  end. No limit, validity or published value changes.
- **The backtest builds the configuration-poll liveness** (30 s before the issue time, like the shared fixture), so its
  charge items are judged on the same rules as the cycle; the SYNTHETIC figures are unchanged.
- **Recorder set.** Every entity class, and the shared entity mixin, keeps `UNRECORDED_ATTRIBUTES` plus the runtime's
  timestamp-only attributes out of the recorder (13.4); the mapping suite pins that set.
- **Tests on the real rules.** The planning suites' in-process WP-1 simulation is removed, and the L2 checks that waited
  for WP-1 or WP-2 are strict.
- **Poll-phase-aligned refresh (A23, runtime).** On the target platform the telemetry poll text moves every 60 s, not 10 s as designed, so
  refreshes follow the poll (13.4): one state listener on the mapped telemetry poll text, a poll-driven step
  `PROPOSED_POLL_SETTLE_S` after each new poll, the tick held back while polls arrive and back on its present rules when
  they stop. New constants in `const.py`: `PROPOSED_POLL_INTERVAL_S` (60 s), `PROPOSED_POLL_SETTLE_S` (3 s),
  `PROPOSED_POLL_ACTIVE_S` (90 s) and the derived `POLL_REFRESH_THRESHOLD_S` (185 s). The runtime boundary suite now allows
  `async_track_state_change_event` and `async_call_later` beside the one timer, each called from one place in
  `coordinator.py`, and the L2 pin "no event listener" is now "exactly one state listener, on the mapped telemetry poll
  text, removed on unload". The stand-in Home Assistant delivers `state_changed` to state listeners and fires one-shot
  timers at their times; `test_runtime_poll_phase.py` drives the poll text every 60 s plus or minus 3 s at swept phase
  offsets from the tick (no `INPUT_EXPIRING` and no STALE over three simulated hours at each offset; recovery from an
  unknown slot, a frozen configuration text and a frozen telemetry text within one poll plus the settle delay; a frozen
  telemetry text still fails closed). The earlier L2 suites set their world between ticks without events and keep
  pinning the tick's own rules.
- **Missed polls, supervision, fast poll texts (A31(b), A32, A33; runtime tests and docs, no rule change).** The poll-phase
  suite counts STALE, `INPUT_EXPIRING` and the numbers from the stand-in's recorder rows (every write, not only the state
  after each cycle) and adds: a poll 90 s late, one skipped poll (120 s), a 150 s gap and a freeze (480 s), each at seven
  phase offsets (at most one STALE cycle per episode, never a number past its inputs' bound, then the fallback or the
  recovery of 13.4); the supervision heartbeat lapsing while polls continue (export and Dump BLOCKED
  `SUPERVISION_NOT_STABLE` at the first poll-driven compute after the 90 s bound lapses, at most one poll plus the settle
  delay later); a poll text changing every 2 s (a pending poll-driven step is never moved later, so cycles still start at
  each 55 s floor's end; before A33 nothing was ever computed). `runtime/sources.parse_entity_map` refuses a
  configuration-poll liveness entity or online entity equal to the telemetry poll-text entity (by field path only;
  `site-check` exits 1).
- **The polls-stop exposure and the in-flight wait (second runtime review; runtime tests, docs and one tighten-only
  cadence fix).** In the freeze the supervision heartbeat stops with the polls; the poll-phase suite pins, at seven
  phase offsets, that the first compute after the last poll's comes more than `PROPOSED_POLL_ACTIVE_S` and at most
  150 s after it and BLOCKs export and Dump `SUPERVISION_NOT_STABLE` (13.4, A31(b)). A poll-driven step that waited
  for a cycle in flight is armed, when that cycle ends, no earlier than the settle delay after the newest poll seen:
  a poll that arrived while it waited keeps the step (A33), and before this fix a cycle ending inside that poll's
  settle delay started the refresh at once, with that poll's text and liveness time but the previous poll's other
  values. No bound, margin, floor, gate or published-value rule changes.
- **The settle hold and the boolean gates (third runtime review, A36; runtime only, tighten-only).** No cycle starts
  inside the settle delay of the newest poll seen (13.4): the hold sits at the one place a cycle starts, so a refresh the
  tick asks for after STALE, the exception retry, a step deferred to the floor's end and a step resumed after a cycle in
  flight all start at that poll's settle delay's end and read its late writes. Before this, a cycle the tick started
  inside the delay (the exception retry 1 s after a poll) read the poll's text and liveness time with the previous
  poll's other values and covered the poll's step, and a floor-deferred step could start inside a newer poll's delay.
  The resumed step needs no rule of its own now (the hold at the start covers it). A poll text every 2 s still gives a
  cycle at each floor's end plus at most 3 s (the hold is one-shot). `runtime/sources.parse_entity_map` refuses any two
  of the boolean gate readings (`supervision.stable`, `tou.enabled`, `tou.grid_charge_enabled`) on one entity, by field
  path only (`site-check` exits 1; RR-3). No bound, margin, floor, gate or published-value rule changes.
- **The window check reads import rates short of the search period (engine review ENG6-1 to ENG6-3; engine,
  tighten-only, and docs).** The cycle judged `tariff.import_rates` once, with the coverage need, before the window
  check, so a payload short of the 24 h search period reached `choose_charge_window` as no verified tariff and the
  A35 rule never ran on it: a TOU window with a priced slot well above the slot holding `now` stood OK. The window
  check now gets the same reading judged without that need (13.5, "Which judgement of the import rates"); prices, the
  tariff block and the value keep it. Section 3 then stopped saying the runtime merges the rate events (it mapped one
  event per key until A38 Part B, below), 13.5 states the one-day-event limitation, and 13.8 says where the quality layer's
  `CHARGE_WINDOW_FROM_TOU_TABLE` WARN stays. No PROPOSED value or bound changes; the only published change is a BLOCK
  where a priced slot conflicts.
- **Register 217 at 0 % (engine test).** The cycle-planning suite pins the finite 0 % boundary case: I-D2 read from
  `protection.shutdown_soc_pct` at a finite 0 % (finite but uninformative) is satisfied, lowers nothing (the technical
  minimum stays the 10 % placeholder, the 40 % advisory reserve binds) and claims no BMS limit.
- **The window check's lowest rate looks back 24 h (engine review N1 / N2, A38 Part A; engine, tighten-only, and
  docs).** On one day-rates event, `low` came only from the rest of the day, so a TOU window misplaced to the evening
  peak stood OK once the night's cheap run had passed (about three quarters of each day). `tariff.horizon_low_p_per_kwh`
  now reads the window-check judgement's slots over `[now - PROPOSED_WINDOW_SEARCH_H, now + PROPOSED_WINDOW_SEARCH_H)`,
  the slot that holds `now` included (13.5, "The look-back"); the slots checked, the named-run path and every
  PROPOSED value are unchanged. Such a window now BLOCKs at every cycle until its occurrence ends; an occurrence the
  reading does not price keeps the WARN (the accepted residual); the F2 limitation widens to price rises and to
  dynamic tariffs (13.5). The only published change is a BLOCK, when no cheap run is named, where a priced slot of the
  occurrence is 2 p or more above a slot priced in the past 24 h.
- **Rate tables from the day events and two more refused pairs (third runtime review, A38 Part B and A39; runtime,
  tighten-only, and docs).** With one day-rates event mapped, the import rates named no cheap run outside local
  midnight, and a TOU window misplaced to the peak stood OK with a WARN once today's occurrence had ended (the Part A
  residual). A rate table key may now map two or three day events in day order (CCR-RT-DAYS; the production site file
  maps the current-day and next-day events, A42); the runtime merges their rows under the fail-closed rules of section 3 and
  the engine's parse, unit and coverage rules are unchanged. With the next day's rates published at 16:00 such a window
  BLOCKs at every half-hour of the day (the L2 suite `test_runtime_tariff_days`), and the residual is limited to the
  hours before the next day's rates are published.
  `runtime/sources.parse_entity_map` also refuses any boolean gate reading (`supervision.stable`, `tou.enabled`,
  `tou.grid_charge_enabled`) on the configuration poll's online entity, and `battery.soc_raw_pct` on the `battery.soc`
  signal's entity and attribute (A39, RT3-1 / RT3B-1, RT3B-2: each would silently skip a fail-closed check; by field
  path only, `site-check` exits 1). No PROPOSED value, bound, reason code or published-value rule changes.
- **The import table checked on the site, one event per tariff table (fourth runtime review, A42, RT4-1 / RT4-2;
  runtime, tighten-only, and docs).** A merged import table that is refused, gapped or not fresh gives the engine no
  usable tariff, so the window check is absent and nothing blocks (a BLOCK for that case is not in v0.1; it is decided
  on the 72 h data). The install runbook's go / no-go row R5, its 72 h row T11 and its 7-day row Q6 now require the
  import rates `TARIFF_VERIFIED` and fresh after the next-day publication; the diagnostics download shows the runtime's
  source notes (each a contract key and a constant code, so a refusal such as `TABLE_ROWS_OUT_OF_ORDER` is visible);
  and the production site file maps the two day events `[current day, next day]`. `runtime/sources.parse_entity_map`
  also refuses one rate event (entity and attribute) under two of the tariff tables, which would let its freshness
  stand in for the other table's own event (by field path only, `site-check` exits 1). No PROPOSED value, bound,
  reason code or published-value rule changes.
- **The residual made visible (fourth engine review, A41, R7-E3; engine, one INFO code).** The published items carry
  codes only, and the WARN `CHARGE_WINDOW_FROM_TOU_TABLE` was the same code for a window checked within the spread and
  for one that no price check covered (the residual of 13.5), so the 72 h and 7-day acceptance could not count the
  residual. `daily_plan.choose_charge_window` now adds INFO `CHARGE_WINDOW_NOT_PRICED` when the window stands on the
  TOU table without a price check of its whole occurrence, and the cycle carries it to every charge-window item
  (13.5, 13.8). No status, number, validity, bound or PROPOSED value changes; the planning suites pin where it appears
  and that the envelope without it is otherwise identical.
