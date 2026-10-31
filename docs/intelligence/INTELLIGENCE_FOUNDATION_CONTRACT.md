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
- I-D6: 300 s per dongle signal and gate reading, judged by the poll-text liveness time, within the 900 s ceiling;
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
| charge_target (yes) | I-D1, I-D2, I-D3, I-D5, I-D8 (+I-D4, I-D9 cond.) | `battery.soc`, history, dongle liveness, the I-D1 / I-D2 / I-D3 readings when those sources are chosen, `limits.max_grid_charge_w`, a charge-window source: a VERIFIED tariff (`tariff.import_rates`), else the read-only `tou.slot_table` with a WARN, else BLOCK | the SiteConfig example capacity, efficiency, window or 8 kW |
| export_event (yes) | I-D1, I-D2, I-D3, I-D5, I-D6, I-D8 (+I-D4 cond.) | the above (the charge-window source included: the refill window) plus house / PV / battery / grid power, `inverter.healthy`, `tariff.export_rates` | the SiteConfig example window |
| dump_to_grid (yes) | I-D1, I-D2, I-D3, I-D5, I-D6, I-D8 (+I-D4 cond.) | as export_event, plus `stop.dump_soc_pct` | the SiteConfig example window |
| predicted_morning_soc (yes) | I-D1, I-D2, I-D3, I-D5, I-D8 (+I-D4, I-D9 cond.) | as charge_target | - |
| predicted_day_load (yes) | I-D8 | history | - |
| pv_tomorrow (yes) | none | history, `pv.forecast_tomorrow_kwh` (date-scoped: issued on the same local date), the site fact `pv_array_kwp` | - |
| v1_summary (internal only) | I-D1, I-D2, I-D3, I-D5, I-D8 | as charge_target | - |
| engine_comparison (attribute) | emitted only when charge_target is OK | - | - |

Every dongle-sourced input (SOC, powers, inverter health; the raw SOC, Ah register, shutdown level, Dump stop level, TOU
table and clock offset readings) needs `liveness.dongle_poll_changed_at`. `gate(item, decisions, context, accept_provenance)`
returns the BLOCK findings; `required_inputs(item, decisions, accept_provenance)` the inputs.

`apply_to_siteconfig(base_cfg, decisions, readings, accept_provenance)` returns a `SiteConfig` built with
`dataclasses.replace` whose battery fields (user reserve, technical minimum, capacity, round-trip efficiency, grid-charge
limit) and cheap window come only from satisfied decisions and fresh readings, or `None` with the reasons. It never keeps
the example capacity, efficiency, 40 % reserve, 8 kW or cheap window. The cheap window is the judged input
`readings[CHARGE_WINDOW_KEY]` (`charge_window.local_minutes`: `(start_min, end_min)` after local midnight, ints with
`0 <= start < end <= 1440`, fresh under a defined limit), which the planning layer derives from its charge-window source
(a VERIFIED tariff, else the read-only TOU slot table); without one the result is `None` with `CHARGE_WINDOW_UNKNOWN`.
An `HA_RESERVE_HELPER` reading outside 0..100 BLOCKs (`RESERVE_HELPER_OUT_OF_RANGE`).

**Value shape of the tariff readings (CCR-PLAN-3).** `tariff.import_rates` and `tariff.export_rates` (unit `table`) carry
the tariff integration's rate rows `{start, end, value_inc_vat}`: ISO-8601 times with a UTC offset and a rate in GBP/kWh
(the integration's unit). The value is a list of rows, one rate event's attributes `{rates: [...], unit_of_measurement}`
(a stated unit must be GBP/kWh), or the rate events merged by the runtime, `{previous_day | current_day | next_day: ...}`.
The list shape states no unit, so the planning layer's unit check on it is a plausibility guard only; a stated
`unit_of_measurement` is preferred. `tariff.events` (unit `table`) is a list of `{start, end, kind}` periods (kind
`saving_session` or `free_electricity`) or the integration's event attributes. Any other shape, a naive time or a price
under another key is refused, never repaired (`intelligence/tariff.py`).

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

## 12. CONTRACT CHANGE REQUEST (CCR) procedure

1. A stream that needs a contract change does not edit a foundation-owned file. It writes a CCR into its report: the
   symbol, the change, why, whether it is additive, and the tests that prove it.
2. **Additive** CCRs (a new optional attribute key, a new `SITE_READING_KEYS` entry, a new fixture, a new reason code) are
   applied by the integrator as separate commits during integration.
3. A CCR that touches a symbol of section 8's "not open" list is refused in this slice; it needs an independent adversarial
   review and the owner's decision.
4. Every applied CCR keeps `test_intel_contract_signatures.py` and `test_intel_shadow_cycle_contract.py` passing; a CCR
   that would need either to change is not additive.
