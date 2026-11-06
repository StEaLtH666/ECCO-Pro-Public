# Historical data quality: method and failure modes

This note describes **how** the history behind ECCO Intelligence is audited and which defects the history builder is designed
for. It deliberately contains **no real consumption, occupancy or per-day series**: the numbers from the audit of the reference
installation stay private. Everything here is reproducible on your own data:

```
python intelligence/tools/export_ha_statistics.py --ids ids.txt --out /tmp/hist     # read-only, run where the recorder lives
python intelligence/tools/quality_report.py --hourly /tmp/hist_hourly.csv.gz --profile intelligence/profiles/<site>.local.json
```

`quality_report.py` writes its numbers to a local JSON file (git-ignored); nothing from a real installation is committed.
Nothing is written to Home Assistant and InfluxDB is not queried.

Sections 10 to 12 describe the SHADOW layer on top of this: the input re-verification rules of `intelligence/quality.py`,
their PROPOSED detection thresholds, the seeded fault injectors and fuzz that prove them, and the offline capture validator
(`intelligence/tools/validate_capture.py`, aggregate summary only; runbook: [`REAL_DATA_CAPTURE_KIT.md`](REAL_DATA_CAPTURE_KIT.md)).

## 1. Depth and sampling (what to expect from an HA installation)

| Series | Typical depth | Sampling |
|---|---|---|
| Hourly long-term statistics | as long as the integration has existed (kept indefinitely) | hourly mean / min / max for power and SOC, hourly last state for counters |
| 5-minute statistics and raw states | about 10 days at default recorder settings | raw power every few seconds; SOC and counters **on change** |
| Dongle energy counters | | published about every 10 minutes, 0.1 kWh resolution |

Consequence: the model runs at **hourly resolution**. Long hourly history is the training set; 5-minute and raw data only
support recurring-signature discovery and SOC validation. If the dongle's own history is short and a legacy integration covers
the same instants, the history builder merges them (dongle first, legacy fill-in).

## 2. Completeness and gaps

The audit counts expected vs present hours, lists missing runs, and reports how many hours were filled by spreading a counter
delta across a gap (up to 6 h, flagged `gap_interpolated`). A merged two-source history should be complete; a source that has
dropouts (reboots, OTA updates, HA restarts produce `unavailable` / `unknown` states) is covered by the other.

## 3. Units, scale and consistency

* Counters may be in different units across integrations (kWh vs MWh): the profile carries a `scale` per entity and a unit test
  pins the legacy MWh case. Powers are W; SOC is a percentage with integer resolution (1 % is about 0.3 kWh on a ~30 kWh
  battery); counters have 0.1 kWh resolution.
* Two paths that measure the same registers should agree to counter resolution over their overlap; the audit reports the mean
  and mean absolute hourly difference and the lag at which the 5-minute power series correlate best (no lag = no time offset).

## 4. Dropouts, stale values and resets (what the builder handles)

* **Flat-lined instantaneous power**: some integrations hold the last power value (min = max, > 0) for hours while the cumulative
  counters keep counting. These hours are flagged and never used for the power integral.
* **Counter stalls**: a counter frozen while power says the house is drawing more than a threshold, then a catch-up jump. The
  jump is re-spread across the run (`stall_redistributed`).
* **Negative deltas and resets** in the *total* counters are treated as faults (flagged, not summed).
* **Day counters are not safe for local-date totals**: they reset at the inverter's clock midnight, which can drift from local
  midnight. Use differences of `total_*` counters, never `day_*`.
* **SOC**: a 0 % reading is flagged only when the battery is simultaneously delivering power (a deep discharge can legitimately
  reach 0); impossible hourly SOC jumps are flagged.
* **A trap, found and documented**: an hourly-*mean* SOC is a poor point value near a charge start, because the mean already
  includes the charge that begins part-way through the hour. SOC outcomes must be scored from point values (HA history / Influx),
  not hourly means; the scorecard does this where it can and says where it cannot.

## 5. Cumulative energy vs instantaneous power

Counters (differenced per hour) are preferred: the power integral drifts by a few percent and is wrong on flat-lined hours,
and the two agree closely on a healthy path. Rule used: interval energy = counter delta; the power integral is a fallback
(flagged `power_integral`) and is never used when power is flat-lined. Counter resolution (0.1 kWh) makes 5- or 10-minute energy
meaningless, so **hourly is the finest honest resolution**.

## 6. Energy-balance sanity and PV alignment

The daily balance PV + import + discharge - load - export - charge should leave a small, stable residual (conversion and standby
losses). A *growing* residual is an anomaly signal. PV and load that share a poll and a clock need no alignment correction.
Effective battery capacity can be regressed from counters vs SOC; it cannot overrule the configured capacity, so a few percent
of uncertainty is carried as a stated assumption.

## 7. Time zone and DST

All storage is UTC; the cheap window and every human-facing window are **local wall-clock**. DST days are 23 / 25 hours;
windows spanning the change keep their wall-clock endpoints (the overnight window lasts one hour longer or shorter on those days;
unit-tested). A fall-back day's repeated local hour is averaged into one slot; a spring-forward day has 23 slots.

## 8. PV forecast sources

Day-ahead values from forecast providers are compared with actual array output (energy from the PV counter). Providers can be
biased by season on a given array, so the engine learns a trailing 7-day median actual/forecast ratio per source (see
`PROTOTYPE_RESULTS.md`, section 2) and, since the safety cleanup, also rejects a forecast that is physically impossible or far
outside anything observed (`ECCO_INTELLIGENCE_V1_ARCHITECTURE.md`, section 7a).

## 9. What the data cannot support

Appliance identification (aggregate CT data only); weather or temperature effects (not consumed); sub-hourly energy; behaviour
across DST in data you do not have yet. If a legacy integration is ever removed, V1 degrades to the dongle's own history:
**do not decommission legacy entities or their statistics before the long Influx history is validated** (decision O-5).

## 10. SHADOW input re-verification (`intelligence/quality.py`)

The SHADOW cycle never trusts its caller. `quality.assess_inputs(CycleInputs)` recomputes every age from the cycle time
and the raw observation times and judges every input the items need (`site_decisions.required_inputs`). It returns
`QualityResult{findings, blocked_items, data_quality, ages}`; the cycle blocks every item in `blocked_items`. Rules, codes
and the items each one affects (BLOCK withholds the item, WARN is shown with the item, INFO is a note):

| Rule | Code(s) | Severity | Items |
|---|---|---|---|
| Age re-verification: a dongle-sourced input's age is the poll-text liveness age (the dongle publishes only changed values); a reading published by the dongle's configuration poll (`site_decisions.CONFIG_POLL_READINGS`: the TOU table, the current TOU target, both TOU enables, the shutdown level and the Ah register) is aged by the larger of the telemetry and the configuration-poll liveness ages and is fresh only while both liveness readings are within their bounds; a snapshot signal is never younger than its snapshot (`now - snapshot.as_of`); a future or unknown observation time, a value of the wrong type or outside its plausible range (section 11) is never fresh | `INPUT_NOT_FRESH` (evidence `reason`: missing, invalid, future, age_unknown, limit_unresolved, liveness, config_liveness, stale, empty, caller_withheld) | BLOCK | every item requiring the input |
| The snapshot was taken more than the PROPOSED bound before the cycle | `SNAPSHOT_STALE` | BLOCK | every item resting on a snapshot signal |
| The caller called an input fresh that is not | `CALLER_FRESHNESS_DISAGREES` | BLOCK, data quality BLOCKED | all |
| Caller assessments malformed, fresh without a usable age, or one input assessed both ways | `CALLER_ASSESSMENT_MALFORMED`, `_INCONSISTENT`, `_CONFLICT` | BLOCK, data quality BLOCKED | all |
| The caller withheld an input quality finds fresh: a dongle-sourced one (the caller ages it from its last change; the liveness decides) / any other one (it is not used) | `CALLER_JUDGED_NOT_FRESH` | INFO / WARN, and its items BLOCK `INPUT_NOT_FRESH` (reason caller_withheld) | - / items requiring the input |
| Missing or UNRESOLVED (no defined freshness limit) required input | `INPUT_NOT_FRESH` | BLOCK | requiring items |
| Dongle liveness reading missing or invalid, in the future, or older than the PROPOSED bound | `LIVENESS_MISSING`, `LIVENESS_IN_FUTURE`, `LIVENESS_STALE` | BLOCK | every dongle-sourced item |
| Configuration-poll liveness reading (`liveness.config_poll_changed_at`, the time the dongle's configuration-poll text last changed) missing or not an aware time, in the future, or older than its PROPOSED bound (the older of its value and its observation time counts). Required by every charge-window item and by any item that requires a configuration-poll reading (`site_decisions.required_inputs`, A6). Its bound is fixed: an I-D6 entry naming it is refused (A5) | `CONFIG_LIVENESS_MISSING` (evidence `reason`: missing, invalid), `CONFIG_LIVENESS_IN_FUTURE`, `CONFIG_LIVENESS_STALE` (evidence `age_s`, `bound_s`) | BLOCK | every item requiring the configuration-poll liveness |
| SOC false zero: canonical SOC zero, fresh raw SOC above zero | `SOC_FALSE_ZERO_RAW_USED` (the raw value becomes the judged SOC in `ages`) | WARN | - |
| SOC false zero without a fresh raw SOC (always while the site's I-D6 records no limit for the raw SOC, an I-D6 key with no default limit since CCR-DQ-1) | `SOC_FALSE_ZERO_UNRESOLVED` | BLOCK | SOC items |
| SOC zero while the battery discharges | `SOC_ZERO_WHILE_DISCHARGING` | BLOCK | SOC items |
| Canonical and raw SOC disagree beyond the S0 tolerance | `SOC_SOURCES_DISAGREE` | BLOCK | SOC items |
| Canonical or fresh raw SOC not a percentage | `SOC_OUT_OF_RANGE` | BLOCK | SOC items |
| An online flag (it holds its last state; no timeout) reads on while the liveness is not fresh | `ONLINE_FLAG_UNCONFIRMED` | BLOCK for `inverter.healthy`; WARN for the controller and canonical telemetry flags | export_event, dump_to_grid |
| The inverter does not report normal operation | `INVERTER_NOT_HEALTHY` | BLOCK | export_event, dump_to_grid |
| Live power balance (house = PV + battery + grid) fits only with the grid sign reversed, only with the battery sign reversed, or neither way | `CT_SIGN_REVERSED`, `BATTERY_SIGN_REVERSED`, `POWER_BALANCE_INCONSISTENT` | BLOCK | export_event, dump_to_grid |
| Native-load false zero: house load zero while inverter + grid show a load (HD1) | `LOAD_FALSE_ZERO` | BLOCK | export_event, dump_to_grid |
| Negative house load | `HOUSE_POWER_NEGATIVE` | BLOCK | export_event, dump_to_grid |
| The LiveInputs carry a value (or a time) different from the snapshot's, so the two do not describe the same moment and neither is trusted; the LiveInputs is not a LiveInputs | `LIVE_INPUTS_DISAGREE`, `LIVE_INPUTS_MALFORMED` | BLOCK | every item resting on a snapshot signal, whichever signal differs (the reserve helper included) |
| Supervision not SUPERVISED, not stable, the state or stable reading older than the PROPOSED bound (its age is the telemetry liveness age: both are published only on a change), heartbeat too old (its reported age plus its reading's own age), or a supervision reading missing | `SUPERVISION_NOT_STABLE` | BLOCK export and Dump; WARN for the rest | export_event, dump_to_grid |
| Event table missing or not fresh (presence and age only; the content is the planning layer's). The table is an I-D6 key with no default limit (CCR-DQ-1): while the site's I-D6 records none it is UNRESOLVED, so this BLOCKs. The planning layer also BLOCKs Dump with this code, but only when the event list is Dump's only problem | `TARIFF_EVENTS_NOT_FRESH` | BLOCK export_event; WARN for Dump | export_event |
| Import rates present, or present but not usable | `TARIFF_IMPORT_RATES_PRESENT`, `TARIFF_IMPORT_RATES_NOT_FRESH` | INFO, WARN | - |
| No fresh TOU slot table. This layer does not judge the tariff, so it fails closed: every charge-window item needs a fresh TOU table, also when a verified tariff checks the window (the change requests CCR-DQ-2 / CCR-PLAN-2 that would relax this are deferred) | `CHARGE_WINDOW_UNKNOWN` | BLOCK | charge-window items |
| With a fresh TOU slot table (otherwise the row above applies first): the inverter clock offset missing or not fresh (always while the site's I-D6 records no limit for the offset, an I-D6 key with no default limit since CCR-DQ-1), or beyond the PROPOSED bound. The TOU slot times run on the inverter's clock; every charge-window item needs a known, small offset, also when a verified tariff checks the window (fail closed; CCR-DQ-2 / CCR-PLAN-2 deferred) | `CHARGE_WINDOW_CLOCK_UNKNOWN`, `CHARGE_WINDOW_CLOCK_OFFSET` | BLOCK | charge-window items |
| The window would come from the read-only TOU slot table (the planning layer drops this WARN only when a verified tariff's named cheap run checks and accepts the window; when a verified tariff conflicts with it the planning layer adds a BLOCK and this WARN stays beside it, with no number; see the rule on the tariff cross-check below) | `CHARGE_WINDOW_FROM_TOU_TABLE` | WARN | charge-window items |
| Inverter clock offset beyond the warning bound | `INVERTER_CLOCK_OFFSET` | WARN | - |
| Two or more capacity sources disagree beyond the recorded I-D4 band, or their agreement cannot be computed | `CAPACITY_SOURCES_CONFLICT`, `CAPACITY_MISMATCH_UNKNOWN` | BLOCK | capacity items |
| SOC within the PROPOSED margin of the protection level (the highest of the placeholder technical minimum, a fresh protection reading and a satisfied I-D2 statement), or no level known | `SOC_NEAR_PROTECTION`, `PROTECTION_LEVEL_UNKNOWN` | BLOCK | export_event, dump_to_grid |
| Malformed structure: now, time zone, snapshot, decisions, readings, a duplicate reading, an unexpected internal error | `NOW_INVALID`, `TZ_INVALID`, `SNAPSHOT_MALFORMED`, `SNAPSHOT_IN_FUTURE`, `DECISIONS_MALFORMED`, `SITE_READINGS_MALFORMED`, `SITE_READING_DUPLICATE`, `QUALITY_INTERNAL_ERROR` | BLOCK | all, or the requiring items |
| A malformed, implausible or future-dated reading (it then counts as missing); an entry that is not a SiteReading | `READING_INVALID`, `READING_IN_FUTURE`, `SITE_READING_MALFORMED` | WARN | - (the requiring items BLOCK `INPUT_NOT_FRESH`) |
| A day-ahead PV forecast above the PROPOSED yield per kWp of the array | `PV_FORECAST_IMPLAUSIBLE` | WARN | pv_tomorrow BLOCKs `INPUT_NOT_FRESH` (reason invalid) |
| History: only well-formed hour records count (an int key, an `HourRecord` filed under its own start, dict energies, flags and sources); the history's age comes from the newest one with a finite energy; anything else is ignored | `HISTORY_RECORD_MALFORMED` | WARN | - |
| History: repeated recovered dropouts in the last day (flaps) | `TELEMETRY_FLAPPING` | BLOCK the dongle items; WARN the history-only items | dongle items |
| History: a long recovered gap in the lookback; the last week too incomplete | `HISTORY_GAP`; `HISTORY_COVERAGE_LOW` | WARN; BLOCK | -; every history item |
| History: counter stalls, catch-up jumps, non-finite energies, zero SOC while discharging | `HISTORY_COUNTER_STALL`, `HISTORY_COUNTER_CATCHUP`, `HISTORY_VALUE_INVALID`, `HISTORY_SOC_SUSPECT` | WARN | - |
| History: the hourly energy balance fits only with import and export swapped (a reversed CT), judged by `quality.ct_reversal` over the whole history, over the learning lookback and over the most recent distinguishable hours (a recent onset), each by the share rule over the hours in which import and export can be told apart only (both sides of the share); many hours do not balance (counted over every hour with all six counters, including hours that balance only swapped but cannot be told apart) | `HISTORY_CT_REVERSED` (evidence `windows` and, for each of `history`, `lookback` and `recent`, the two counts the rule read: `<window>_distinguishable` and `<window>_distinguishable_only_swapped`); `HISTORY_BALANCE_RESIDUAL` (evidence `quality.balance_counts`) | BLOCK; WARN | every history item; - |
| History: a clock-change night in the learning lookback (I-D9 governs) | `DST_NIGHT_IN_LOOKBACK` | WARN | - |
| Prolonged zero PV against a forecast that said there would be some | `PV_NO_OUTPUT_VS_FORECAST` (evidence `item_status: INSUFFICIENT_DATA`; `QualityResult.insufficient_items()`) | BLOCK pv_tomorrow (fail closed; a cycle reading `insufficient_items()` may show it INSUFFICIENT_DATA instead, never with a number); WARN charge_target and predicted_morning_soc | pv_tomorrow |

Rules of the layer:

- dq BLOCKs only on inputs declared in `REQUIRED_SIGNALS`, `REQUIRED_READINGS` or `SITE_READING_KEYS` (plus the reserve
  helper signal that the I-D1 `HA_RESERVE_HELPER` source adds) or on a malformed `CycleInputs`; `quality.RULE_INPUTS` lists
  every BLOCK code with its inputs, and `test_intel_quality` checks both directions.
- Missing, stale, conflicting or disagreeing inputs BLOCK; nothing is defaulted silently. A threshold can only add a block.
- **The qualifying readings (CCR-DQ-1, landed at integration).** Three readings the rules need, the raw SOC
  (`battery.soc_raw_pct`), the inverter clock offset (`inverter.clock_offset_s`) and the event table (`tariff.events`), are
  I-D6 keys with no default limit (`quality.QUALIFYING_READING_KEYS`, part of `site_decisions.GATE_READING_KEYS`). While
  I-D6 is OPEN, or records no limit for one of them, that reading stays UNRESOLVED like every other key without a limit
  and is never fresh, so a SOC false zero BLOCKs (`SOC_FALSE_ZERO_UNRESOLVED`) and export_event BLOCKs
  (`TARIFF_EVENTS_NOT_FRESH`) until a site's I-D6 records a limit (at most the 900 s ceiling). Every charge-window item
  BLOCKs as well, under the first rule that fails: with I-D6 OPEN the TOU slot table has no limit either, so the code is
  `CHARGE_WINDOW_UNKNOWN`; `CHARGE_WINDOW_CLOCK_UNKNOWN` (also when a verified tariff checks the window) is the code
  when the TOU table is fresh but the clock offset has no limit. The clean synthetic fixture, whose synthetic I-D6 gives
  them 300 s, raises no BLOCK. The
  rule suites' in-process simulation of CCR-DQ-1 (`_dq_helpers.simulate_ccr_dq1`) does nothing on the integrated code,
  and their guarded strict branches, written before CCR-DQ-1 landed, never run.
- Supervision is judged by its own content (state, stable, each current within the PROPOSED bound; heartbeat age plus the
  reading's age). The state and the stable flag are dongle readings published only when they change
  (`site_decisions.DONGLE_READINGS`), so their age is the telemetry liveness age: steady supervision stays current while
  the poll text moves and becomes old when the poll text is frozen beyond the supervision bound or the liveness reading
  is missing. This is a deliberate loosening against the reading's own observation time (accepted: amendment A29):
  before it, steady supervision always read as old, and export and Dump advice were blocked permanently on a real
  site. It is bounded by the heartbeat, re-published every 20 s, which keeps its own observation time: a frozen
  supervision publisher still blocks export and Dump advice within the bound.
- **Supervision is not in item validity (documented exemption, A31; contract section 13.4).** The planning layer bounds
  an item's validity by the inputs it rests on, including the inputs of the gates of this layer (the inverter clock
  offset for every charge-window item), with one exemption: the supervision readings. Their 90 s bound is shorter than
  the planning layer's 125 s refresh margin, so putting them in the validity would make export and Dump advice
  permanently `INPUT_EXPIRING`. This layer judges supervision at every compute instead (`SUPERVISION_NOT_STABLE` BLOCKs
  export and Dump). Worst-case exposure: a published OK export or Dump item can outlive a supervision lapse until the
  next compute. While polls arrive, the runtime's poll-driven refresh (A23) computes after every poll: about one
  telemetry poll plus the settle delay plus the compute time. When the polls stop, the tick holds its refresh while the
  last poll seen is at most `PROPOSED_POLL_ACTIVE_S` (90 s) old, so the first refresh (the dongle items
  `INPUT_EXPIRING`) comes at the first tick after that: at most about 150 s after the last poll, plus the compute time.
  In every runtime state (CPU guard, refresh switch off, a failed cycle) the item never outlives its own validity, at
  most the 180 s liveness bound after the telemetry poll it rests on (the runtime publishes STALE before that). No
  bound changes. Any ASSISTED use of export or Dump validity needs supervision in the validity first (a separate owner
  decision).
- **Configuration-poll readings (CCR-CFG-1; contract section 13.3).** The TOU table, the current TOU target, both TOU
  enables, the shutdown level and the Ah register come from the dongle's configuration poll (about every 60 s), which
  is skipped while read-only configuration polling is off, during inverter writes and during clock corrections. Aged by
  the telemetry poll text alone a frozen table would still count as fresh, so each stays a dongle reading (the
  telemetry rule still applies) and is also aged by the configuration-poll liveness: its age is the larger of the two
  liveness ages, judged against its own I-D6 limit, and it is fresh only while the telemetry liveness is within 180 s
  and the configuration-poll liveness within 300 s (tighten-only). Every charge-window item also requires the
  configuration-poll liveness itself (A6), so a frozen configuration poll blocks it with `CONFIG_LIVENESS_STALE` even
  when a verified tariff checks the window. The runtime publishes the configuration-poll liveness reading only while
  the dongle reports the configuration poll online (contract 13.3, runtime work package).
- The TOU readings the grid-charge classification needs (both enables and the overlay state) are judged on every run
  whatever the decisions say, so the planning layer reads this layer's judgement (with the configuration-poll ageing
  for the enables) rather than a telemetry-only age; the current TOU target stays the planning layer's own judgement
  (CCR-PLAN-1). The overlay state must be exactly `NONE` or `ACTIVE`. The TOU enables and the overlay state are I-D6
  keys with no default limit (`site_decisions.TOU_GATE_READING_KEYS`, CCR-TOU-1): UNRESOLVED until a site records one.
- **The tariff cross-check is the planning layer's (contract 13.5, A30, A35 and A38).** This layer judges only the
  presence and age of the import rates; the planning layer checks the TOU window against a VERIFIED import tariff's rate
  slots, clipped to `[max(now, start), end)`, whether or not the tariff's cheap-run analysis names a run, so a priced
  slot of the TOU occurrence that conflicts always blocks. For this check the import rates are judged without
  the coverage need (the same parse, freshness and future-dated gates), so rates short of the search period are
  checked too, while their prices and value are not used (ENG6-1). With a named run, a slot above the cheap band's
  ceiling BLOCKs `CHARGE_WINDOW_SOURCES_DISAGREE` (slots short of the occurrence: `CHARGE_WINDOW_TOU_UNCHECKED`).
  Without one (any smooth tariff, one shoulder slot within 2 p of the cheapest rate, or rates short of the search
  period), a slot of the occurrence priced at or above `low` plus `PROPOSED_MIN_CHEAP_SPREAD_P_PER_KWH` BLOCKs
  `CHARGE_WINDOW_SOURCES_DISAGREE`, also when the occurrence is only partly priced, where `low` is the lowest rate
  priced from 24 h before now to 24 h after it (the look-back, A38: the slot that holds now included; only `low` looks
  back, the named run's band never does, and a lower `low` can only add BLOCKs); only otherwise does the TOU window
  stand, with the planning layer's own WARN text saying which case applies.
  This layer's `CHARGE_WINDOW_FROM_TOU_TABLE` WARN is dropped only when a named run checks and accepts the window, so it
  also stays among the reason codes beside the BLOCK of a refused window, which carries no number (ENG6-3). A tariff
  that does not price the window gives nothing to conflict with, so without a named run that alone is no BLOCK.
  Known fail-closed limitation (F2, widened by A38): a correctly placed window BLOCKs `CHARGE_WINDOW_SOURCES_DISAGREE`
  (no number) although tariff and TOU agree whenever a slot of its occurrence is 2 p or more above the cheapest rate
  priced in the 24 h before or after now: on the night a cheap rate falls by 2 p or more at local midnight; after a
  rise of 2 p or more, without a named run, until the old cheaper slots are 24 h old; and on a dynamic Agile-style
  tariff on every day priced 2 p or more above a cheaper slot of the previous or next 24 h, so on such a tariff the
  charge-window items can be withheld for many cycles of many days (accepted, fail closed). What remains on one
  day-rates event (contract 13.5): with the single form the runtime passes the rows of one mapped rate event; with the
  look-back a misconfigured TOU window BLOCKs whenever that event prices its occurrence, and an occurrence it does not
  price at all (on the current-day event, from the end of today's occurrence to local midnight) keeps the WARN whose
  text says "... does not price the whole TOU window" (the accepted residual). With the day events (A38 Part B, the
  contract the Home Assistant runtime implements; contract section 3) the runtime merges the day events' rows; a site
  maps `[current day, next day]`, the recommended form (A42; the three-event form, with the previous day first, is
  allowed, and the previous-day event is added only once its report cadence is known to stay within its I-D6 limit), so
  the residual is limited to the hours before the next day's rates are published, while the merged table is accepted and
  fresh (a table the runtime or the engine refuses, a gap or a stale oldest event gives no usable tariff:
  INTELLIGENCE_HA_RUNTIME, risk 8).
  Only the codes of WARN and INFO findings are published (A41; contract 13.5 and 13.8): a WARN or INFO finding's text
  stays in the engine (a BLOCK finding's text is published as its blocker text; the residual's WARN text is not), and
  the WARN `CHARGE_WINDOW_FROM_TOU_TABLE` is the same code for a window whose whole occurrence was priced within the
  spread and for one that no price check covered. INFO `CHARGE_WINDOW_NOT_PRICED` on every charge-window item marks
  the second: no usable verified tariff for the window check (none, refused, stale, gapped or otherwise not verified),
  or one that names no cheap run and does not price the whole occurrence. It is never emitted beside
  `CHARGE_WINDOW_TOU_INSIDE_TARIFF`, when the whole occurrence was priced within the spread, or on a refused window,
  and it never blocks. This code is how the residual is observed in the 72 h technical acceptance and the 7-day
  recommendation-quality monitoring: only a cycle whose OK `charge_target` carries it had charge advice that stood on
  the TOU table alone. The code is on every charge-window item whatever its status, so on a non-OK item it says only
  that the window was not price-checked.
- Finding texts never carry a number with a unit; the numbers are in `Finding.evidence`, which is not published.
- `ages` feeds the envelope's `input_ages` (`QualityResult.input_ages()`: at most 24 rows, the required inputs first;
  both liveness readings are rows).

**Freshness classes and the I-D6 proposal.** `site_decisions.PROPOSED_ANSWERS["I-D6"]` is text only, never applied, and
is written from `PROPOSED_D6_KEY_CLASSES` / `PROPOSED_D6_CLASS_LIMITS_S`, a partition of every I-D6 key (checked by
`test_intel_site_decisions`, which also checks that the proposal would re-validate as an I-D6):

| Class | Keys | Proposed limit | Why |
|---|---|---|---|
| dongle | every dongle signal and dongle reading that is an I-D6 key, the configuration-poll readings, the TOU enables and the overlay included | 300 s | judged by the poll-text liveness times, whose fixed bounds (180 s telemetry, 300 s configuration poll) decide first |
| bridged | `capacity.helper_kwh`, `limits.max_grid_charge_w`, `reserve.ha_minimum_soc` | 600 s | the Home Assistant configuration bridge re-renders every 5 min; a gap-free result needs at least 300 s + 125 s, and 600 s also tolerates one late render |
| tariff | `tariff.events`, `tariff.export_rates`, `tariff.import_rates` | 900 s | the tariff integration's re-report cadence is not observed yet: the ceiling |
| no proposal | `capacity.fe1_wh_per_pct`; `history.hourly` | - | the learned capacity's cadence is not observed (UNRESOLVED; only an I-D3 `LEARNED_FROM_DISCHARGE` source requires it); the history keeps its defined 6 h limit |

The supervision readings and both liveness readings are not I-D6 keys: their bounds are this layer's fixed rules.

`quality.prepare_history(history, decisions, now)` returns `(History | None, findings)`, never modifies its input and never
raises (anything unexpected returns None with BLOCK `HISTORY_MALFORMED`). It returns None unless I-D8 is satisfied
(`DECISION_D8_OPEN` / `_INVALID`, `HISTORY_MISSING`, `DECISIONS_MISSING`, `ACCEPT_PROVENANCE_INVALID`, `NOW_INVALID`
otherwise). Otherwise it returns a copy of the well-formed hours that had ended by `now` (`HISTORY_RECORD_MALFORMED`
counts what it left out), with I-D8 applied before the cut-over (`HISTORY_PRE_CUTOVER_LOAD_REMOVED`, INFO, counts it):

| I-D8 policy | Applied to the copy |
|---|---|
| `load_power_policy: EXCLUDE` | load power removed (and load energy integrated from load power) |
| `load_power_policy: KEEP_NON_EXPORTING_ONLY` | load power kept only for hours with a recorded zero export and no exporting grid mean |
| `load_counter_policy: EXCLUDE_PRE_CUTOVER` | the load counter removed |
| `load_counter_policy: KEEP_AFTER_COUNTER_CHECK` | the load counter kept only where the counter check ran and passed: hours that read zero while exporting, hours that disagree with the balance-derived load (pv + import - export + discharge - charge) and hours lacking a counter the check needs are removed (`HISTORY_LOAD_FALSE_ZERO_REMOVED`, `HISTORY_COUNTER_CHECK_REMOVED`, `HISTORY_COUNTER_CHECK_UNAVAILABLE`, WARN with the counts) |

At any time it removes counter stalls and catch-up hours, non-finite or negative energies, out-of-range SOC and zero SOC
while discharging. After the cut-over a load that reads zero while exporting is removed; several such hours return None
(`HISTORY_LOAD_FALSE_ZERO_AFTER_CUTOVER`: the recorded cut-over instant cannot be right). A history whose energy balance
shows a reversed CT (`quality.ct_reversal`, the same judgement and windows as `assess_inputs`) returns None
(`HISTORY_CT_REVERSED`).

**Limit of the balance check.** A reversed CT shows only against an independent load measurement. When the house load is
itself derived from the same CT (HD1's inverter + grid), the reversed reading still balances; that fault is out of reach of
this check and needs the counter check or a supervised look.

## 11. PROPOSED detection thresholds

Every value is a technical detection constant (`quality.DQ_PROPOSED`, status `PROPOSED`), never an owner value or decision.
Each is set in the direction that blocks more, and none can make an input fresh or unblock an item. The S0 agreement
tolerances and the capacity plausibility range are reused from `site_decisions.PROPOSED` (one copy).

| Threshold | Value | Source and direction |
|---|---|---|
| `liveness_max_age_s` | 180 s | the Battery Outlook model's poll-text rule ([`../BATTERY_TIME_TO_RESERVE.md`](../BATTERY_TIME_TO_RESERVE.md)); tighter than the 300 s I-D6 proposal |
| `config_liveness_max_age_s` | 300 s | the configuration poll runs about every 60 s: five polls, so one late or deferred poll is tolerated (a 240 s bound would not survive one late poll without making a result valid for less than the 125 s refresh margin); fixed, never an I-D6 key |
| `snapshot_max_age_s` | 180 s | the runtime builds the snapshot at cycle time; one older than the liveness bound is an old snapshot |
| `supervision_max_heartbeat_age_s` | 90 s | the firmware's SUSPECT threshold, applied to the reported age plus the reading's own age (stricter than the firmware) |
| `supervision_reading_max_age_s` | 90 s | the same bound on the supervision state and stable readings' age, which is the telemetry liveness age (both are published only on a change, so the poll text dates them) |
| `soc_zero_max_pct` | 0.5 points | SOC has whole-percent resolution: anything that rounds to zero is zero |
| `soc_zero_discharge_w` | 100 W | a zero SOC while discharging more than this is not credible (below the 300 W stall power) |
| `soc_agree_points` (S0) | 2 points | one SOC step either way |
| `protection_margin_pct` | 10 points | export and Dump advice withheld this close to the protection level |
| `power_agree_w`, `power_agree_fraction` (S0) | 100 W, 5 % | the live power-balance tolerance: the larger of the two |
| `load_zero_max_w`, `load_false_zero_flow_w` | 0.5 W, 150 W | HD1's rule: a native zero is false when inverter + grid exceed 150 W ([`../HOUSE_LOAD_HD1.md`](../HOUSE_LOAD_HD1.md)) |
| `clock_offset_warn_s` | 30 s | the firmware's background clock-correction floor |
| `clock_offset_block_s` | 30 s | equal to the warning bound: any offset worth a warning refuses a TOU-derived charge window (the work order's "WARN; BLOCK a charge window derived from the TOU slot table", read in the direction that blocks more; the firmware's 120 s correction threshold is not used) |
| plausibility (`READING_INVALID`) | % 0 to 100; W 0 to `power_max_w` = 100 kW (the grid-charge limit above 0); kWh 0 to 500 (the capacity helper 0.5 to 500, S0's `capacity_plausible_kwh`); Wh/% as 0.5 to 500 kWh; Ah above 0 to `capacity_ah_max` = 20000; heartbeat age not negative; the TOU overlay state exactly `NONE` or `ACTIVE` | domestic sanity bounds; the raw SOC's range is the SOC rule's (`SOC_OUT_OF_RANGE`) |
| `pv_forecast_max_kwh_per_kwp` | 10 kWh per kWp per day | above any physical daily yield of a fixed array in the UK |
| `flap_window_h`, `flap_min_dropouts` | 24 h, 2 | two recovered dropouts in a day count as flapping |
| `gap_warn_h` | 6 h | the history builder's longest spread gap |
| `coverage_window_h`, `coverage_min_fraction` | 168 h, 80 % | `History.energy_scaled`'s default coverage, over the most recent week |
| `stall_energy_max_kwh`, `stall_power_min_w` | 0.005 kWh, 300 W | `history.counter_to_hourly`'s stall test and `SiteConfig.stall_power_w` |
| `catchup_excess_min_kwh` | 1.0 kWh | a counter hour more than twice its power integral and this much above it |
| `balance_tol_kwh`, `balance_tol_fraction` | 0.2 kWh, 10 % | two counter steps, or a tenth of the largest term |
| `ct_reversal_min_hours`, `ct_reversal_min_share` | 6, 50 % | of the hours in which import and export can be told apart, in each window: at least this many of them, and at least this share of them, balance only swapped (`distinguishable_only_swapped` against `distinguishable`, both bounds inclusive); an hour in which they cannot be told apart counts on neither side, since it says nothing about the CT's direction |
| `ct_recent_hours`, `ct_recent_window_h` | 12 hours, 72 h | the most recent distinguishable hours within the last three days, judged on their own (a recent onset) |
| `export_evidence_kwh` | 0.05 kWh | an hour exporting more than this is an exporting hour |
| `false_zero_after_cutover_block_hours` | 3 | repeated zero-while-exporting hours after the cut-over |
| `counter_check_tol_kwh`, `counter_check_tol_fraction` | 0.1 kWh, 10 % | the I-D8 counter against the balance-derived load |
| `pv_zero_day_max_kwh`, `pv_forecast_min_kwh`, `pv_zero_min_days` | 0.05 kWh, 0.5 kWh, 2 days | a day with almost no PV while a forecast said at least this much, on the most recent consecutive days |
| `history_day_min_coverage` | 90 % | a day counts for the zero-PV rule only when this well covered |

## 12. Fault injection, fuzz and the capture kit

- `intelligence/faults.py`: deterministic, seeded injectors over `_cycle_fixtures` inputs and `synthetic.make_history`
  houses (CT reversal, native-load false zero, SOC false zero, SOC disagreement, frozen poll text, a frozen
  configuration-poll text while the telemetry poll moves, a missing, malformed or future configuration-poll liveness
  reading, a telemetry poll text frozen beyond the supervision bound only, online flag with stale liveness, supervisor
  outage, SOC near protection, clock offset far and a little beyond the bound, an old snapshot, a
  LiveInputs that disagrees with the snapshot, malformed, missing and future readings, flaps, gaps, stalls, catch-up
  jumps, prolonged zero PV, a reversed CT in the counters from early on and from the last one to three days, a stale
  history with an unusable entry under the newest key, zero SOC while discharging, zero load after the cut-over,
  clock-change nights). `FAULTS` names the rule that must detect each one.
- `test_intel_faults.py`: every injector is detected by its rule on 25 seeds (a CT reversal by `assess_inputs` and by
  `prepare_history`), and the clean bases (the fixture, a clean synthetic house per seed, the same with balanced counters,
  the fixture through the year, the clock-change cases) raise no BLOCK on the same seeds, the three CCR-DQ-1 readings
  judged under the synthetic I-D6's own 300 s (section 10); its [0] check on the clean fixture is that it raises no BLOCK.
- `test_intel_quality.py`: a positive and a negative case for every rule above; it also checks that every code
  `quality.py` can emit is named in one of its cases. Its [10b] pins the CT share rule's counts: hours that balance only
  swapped but cannot be told apart never make a reversal (in `assess_inputs` and `prepare_history`), a genuine reversal
  fires in each window on its own with the counts it read as evidence, both PROPOSED bounds are inclusive, and the
  residual rule still counts every hour that balances only swapped.
- `test_intel_quality_fuzz.py`: 2400 seeded malformed inputs and 1600 more on a second seed (its CCR-DQ-1 simulation does
  nothing on the integrated code, so both sets are judged under the contract's own limits) never raise, and an
  independent oracle (`_dq_helpers`: written out from this document, not from `quality.py`) confirms that no
  unblocked item relies on a stale, missing, implausible or disagreeing input: required inputs fresh and plausible, a
  snapshot signal never younger than its snapshot, a forecast from the cycle's local date, the history dated by its
  well-formed records only, a configuration-poll reading aged by the larger of the two liveness ages with both within
  their bounds, the configuration-poll liveness fresh for every charge-window item, no input the caller withheld, a
  LiveInputs that agrees with the snapshot, a recent snapshot, a zero SOC resolved by a fresh raw SOC, a TOU-derived
  window with a fresh, small clock offset, export_event with a fresh event table, and export and Dump advice with
  current, stable supervision (state and stable aged by the telemetry poll text, the heartbeat by its own time). The
  bases include a frozen configuration poll, an aged but valid one, a telemetry poll frozen beyond the supervision bound
  only and steady supervision, and the suite checks that each of these paths is exercised both ways. 400 `prepare_history` cases (junk energies, flags and sources included) keep the I-D8 policies, a
  pre-cut-over counter only where its check ran and passed.
- `intelligence/tools/validate_capture.py` and [`REAL_DATA_CAPTURE_KIT.md`](REAL_DATA_CAPTURE_KIT.md): the offline
  validator for a real export, aggregate summary only (its key tree is pinned by `test_intel_capture_kit`). The real-data
  run is PENDING (the owner's separate go/no-go, after the owner's release closeout is committed). The advice backtest
  step stays PENDING: it needs DP-1 (the owner's decision on the source of each decided input; OPEN), synthetic
  decisions are never used on real data, and a capture that carries the TOU and tariff readings at each issue time,
  which a statistics capture does not.
