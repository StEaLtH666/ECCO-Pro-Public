# Health v2, stage H0: the semantics contract

Status: **DESIGN CONTRACT, offline. No behaviour is changed or approved by this document.**
Scope: what the ten existing Home Assistant health sensors mean today, and what a FUTURE read-only health rollup must mean.
Companion tests: `health/tests/test_health_v2_golden.py` with `health/tests/fixtures/health_v2_*.json` (stage H1).
Baseline: public main `555cf859`. Existing files, the registry, the Home Assistant packages, the dashboard, the firmware and the
older documents are **not edited**; where they disagree with each other or with this contract the disagreement is recorded in
section 11 and is not fixed here.

Terms used throughout: **evaluated** = the pure engine `health/system_health.py` run on synthetic input; **HA** = the Home
Assistant package `home-assistant/packages/ecco_system_health.yaml`; **PENDING** = a future semantic that nothing implements and
the tests do not assert.

## 1. What this contract is not

- It is not a rollup, a gate, a threshold change or a design approval. A decision marked O-n in section 13 is the owner's.
- It does not change any existing health behaviour. In particular it keeps every raw RTC warning visible (section 9).
- It does not say the installation is healthy. Nothing in this repository can: the registry records `live_proof_status:
  unknown` for all 63 checks, and the golden vectors are synthetic.
- It does not touch the 25 October conditional RTC exception, the DST plan, A10-P, firmware or any write authority.

## 2. What the ten existing sensors mean today

There are exactly ten `sensor.ecco_health_*` entities (test M-02). Each reports one of HEALTHY / DEGRADED / WARNING / FAILED /
UNKNOWN for **its own slice** of the registry.

| Sensor (`unique_id`) | Subsystem (tier) | Registry checks it represents | Notes |
|---|---|---|---|
| `ecco_health_communications` | communications (CRITICAL) | none by id; a **simplified** form of `telemetry_freshness` and `configuration_freshness` | online flags only, no 60/180/600 s brackets; any state other than `on`, including `unknown`/`unavailable`, is FAILED (M-08) |
| `ecco_health_runtime_configuration` | runtime_configuration (CRITICAL) | `runtime_config_ready` | relabel of an existing binary sensor; UNKNOWN when it is unknown/unavailable |
| `ecco_health_manual_write_system` | manual_write_system (CRITICAL) | `manual_write_duration` | duration from `last_changed`, restart caveat (M-12); `manual_write_failures_recent` and `manual_write_arm_unexpected` not represented |
| `ecco_health_rtc` | rtc_time (CRITICAL) | `rtc_correction_duration`, `rtc_stall_detected`, `rtc_ntp_synced`, `rtc_correction_failures_recent` | `rtc_read_freshness` and `rtc_drift_uncorrected` not represented |
| `ecco_health_free_power` | free_power (CRITICAL) | `free_power_operation_duration`, `free_power_active_state`, `free_power_snapshot_recovery` | `free_power_failures_recent`, `free_power_state_consistency` not represented |
| `ecco_health_start_failures` | free_power and manual_write_system (CRITICAL) | `free_power_start_failed_recent`, `dump_to_grid_start_failed_recent` | 240 s settle, 1800 s window |
| `ecco_health_configuration` | inverter_configuration (CRITICAL) | `config_cache_valid` | freshness and failure delta not represented |
| `ecco_health_inverter_telemetry` | inverter_telemetry (CRITICAL) | `inverter_alarm_fault`, `inverter_grid_connected` | freshness and failure delta not represented |
| `ecco_health_supervision` | supervision (STANDARD) | 5 supervision checks | display layer, non-blocking |
| `ecco_health_fallback` | fallback (STANDARD) | the 13 fallback checks | display layer, non-blocking |

**What "10/10" is.** It is the statement "each of these ten rows was HEALTHY at one instant". It is **not** overall system
clearance, and it must never be read as permission to write, to arm a schedule or to deploy, for these measured reasons:

1. The ten sensors together declare **32 of the 63** registry checks as represented. 31 are not (test: ledger count).
2. Three of the **11** checks the registry marks as able to block manual control are not fully represented:
   `esphome_reachable`, and the two freshness checks that exist only in the simplified online/offline form
   (`telemetry_freshness`, `configuration_freshness`). Vector **HV-A02** supplies *only* the represented checks, all healthy, to the
   engine; the engine reports overall **UNKNOWN** and control readiness **NOT READY** with those three missing.
3. Eight of the ten rows declare `partial_implementation: true` and `sufficient_for_control_decision: false`. The package states this in
   every one of them; none declares it true (tested).
4. There is no overall rollup entity and no gating readiness entity (M-02). The one readiness entity is labelled
   `REFERENCE ONLY, DO NOT USE TO GATE`.
5. Each row is a sample. For the RTC row in particular the closeout analysis (REPORTED, not re-checked here) found about 7 % of
   the time is WARNING-eligible from a known low-risk stale-clock pattern, so a 10/10 reading is true most of the time while
   the pattern is continuously present.

## 3. Semantics of a FUTURE read-only rollup (design-only)

The future rollup is a **display** value. It never gates anything, never feeds an automation or a write path, and carries the
attribute `sufficient_for_control_decision: false`. Control readiness is a separate computation (section 5).

### 3.1 States and ranks (unchanged from the engine)

HEALTHY = SUPPRESSED = 0 < DEGRADED = 1 < WARNING = UNKNOWN = 2 < FAILED = 3. The rank is used only for worst-of and cap
arithmetic. A label is never chosen by evaluation order (engine `_resolve_flavor_at_rank`, vectors HV-G06, HV-G07).

### 3.2 Worst-of with tier caps

For every subsystem that contributes to the automatic rollup, take the worst rank of its automatic checks, then cap it by tier:
CRITICAL 3, STANDARD 2, INFORMATIONAL 1 (vectors HV-G01 to HV-G04). The overall rank is the maximum capped rank. A real finding
at the winning rank always names the label (HV-G06); a capped finding is still reported as a definite finding of the capped
rank, never as UNKNOWN.

### 3.3 UNKNOWN is never mapped to HEALTHY

- No evidence supplied for a check, a missing timestamp, an unknown availability, an active transaction with an unknown start
  time, a counter with no usable baseline or one that went backwards, and a young baseline are all UNKNOWN, never HEALTHY
  (vectors HV-B01, HV-B03, HV-B04, HV-C06, HV-C09, HV-E01 to HV-E04; sweep: a bare `CheckInput` is HEALTHY for none of the 63 checks).
- UNKNOWN keeps its label under a tier cap (HV-B07). A subsystem whose automatic checks are all UNKNOWN is UNKNOWN.
- A definite finding beats UNKNOWN **in the label only**. The rollup must therefore also expose the UNKNOWN separately
  (`unknown_subsystems`, `unknown_checks`), because in HV-B06 the label is WARNING and the missing telemetry is visible only
  through contributors and readiness (PENDING HV-P04).
- A configured threshold may move a boundary between HEALTHY, DEGRADED, WARNING and FAILED within the documented floors
  (section 7). It can never turn UNKNOWN into anything else, and no configuration can suppress an UNKNOWN.

### 3.4 SUPPRESSED and diagnostic-only

SUPPRESSED means "not applicable now" and contributes rank 0 (HV-G08, where the overall itself reads SUPPRESSED). It is
legitimate only while the check's `applicability_condition` is false. It is **not** an excuse for a broken-but-ignored condition:
with automatic clock sync OFF the drift check is SUPPRESSED with no reason, overall stays HEALTHY and control stays ready
(HV-C11, M-10); the contract treats that as a gap to fix in a later stage, not as the intended meaning of SUPPRESSED.
`diagnostic_only` / `manual_only` checks (5 of 63) are excluded from the automatic state but stay visible (HV-G09, HV-G10).

### 3.5 Completeness (coverage) rule, proposed

The engine's overall ignores a check that was simply not evaluated: **overall can read HEALTHY while a required check is
missing** (HV-B02, M-04). A future rollup must not. It carries a `coverage` object:

```
coverage: { registry_checks, automatic_checks, evaluated, missing_required[], insufficient_required[], complete }
```

and, while `complete` is false, either reports UNKNOWN (option A) or reports the worst evaluated state with the label
"PARTIAL" and `complete: false` (option B). This is owner decision **O-1**. Until it is made, the contract assumes option A for
any entity named like a system-wide health value.

## 4. Evidence model: age, source, last good, provenance

Every health input, check result, subsystem result and the rollup carries the following. `engine today` is the current pure engine.

| Field | Meaning | Engine today |
|---|---|---|
| `observed_at` | when the source last reported, in UTC (epoch seconds); for ESPHome values that are only re-sent on change, the poll-time text entity, not the value, is the liveness source | accepted as `last_updated`; not returned |
| `evidence_age_s` | `evaluated_at - observed_at`; never negative; a time later than `evaluated_at` (beyond a small skew allowance, O-5) is UNKNOWN | `age_seconds` on freshness and transaction results only; **negative ages are accepted as fresh** (HV-D11, M-05) |
| `last_good_at` | the last time this check was HEALTHY | absent (M-03) |
| `source` | the entity ids, firmware sensor names or computation the value came from | the registry `source` is data; no result carries it |
| `provenance` | `raw`, `normalised` or `derived`, as in `ecco_core.state.Observation` | absent |
| `quality` | flags such as `restart_resumed`, `baseline_pending` | absent |
| `unknown_reason` | one machine value of the table below when the state is UNKNOWN | free text only (M-13) |

**UNKNOWN subtypes** (PENDING HV-P11). Today each has its own distinct free-text reason, asserted distinct by the suite:

| Subtype | Meaning | Engine reason text today |
|---|---|---|
| `NEVER_OBSERVED` | the entity has never reported | "Never observed" / "Never updated" |
| `UNAVAILABLE` | reported before, state now unknown | "Observed before, but current availability is unknown" |
| `START_TIME_UNKNOWN` | a transaction is active, its start is not known | "Active, but its start time is unknown" |
| `BASELINE_PENDING` | counter baseline younger than its window | "Baseline is only Ns old ... not enough evidence yet" |
| `NO_BASELINE` | no baseline, or the counter value is unavailable | "No baseline available yet" |
| `COUNTER_RESET` | the since-boot counter went backwards | "Counter went backwards" |
| `NOT_EVALUATED` | the check has no result at all | **no result exists**; readiness lists it as missing |
| `THRESHOLD_UNRESOLVED` | a manual diagnostic with no evidenced threshold | "No evidence-based threshold exists" |
| `FUTURE_TIMESTAMP` | the observation is later than now | not produced today (HV-D11) |

## 5. Fail-closed status

- **Control readiness is not health.** `evaluate_control_readiness` starts from the registry's complete set of 11 checks capable
  of blocking manual control. A required check that is missing, UNKNOWN, or SUPPRESSED without an explicit safe-for-control
  declaration makes readiness False; the three lists `blocking_checks`, `missing_required_checks`, `insufficient_evidence_checks`
  say which (sweep: removing any one required check, or giving it a bare input, makes readiness False). Nothing in the registry
  today declares a safe UNKNOWN or safe SUPPRESSED among the required checks.
- A non-blocking finding (a stall, a failed-correction window, a DEGRADED telemetry age) leaves readiness True (HV-C01, HV-C07, HV-D03);
  a blocking one (a correction in progress, STALE telemetry or configuration, an unreachable device) makes it False (HV-C03,
  HV-D05, HV-D10, HV-B05). The contract does not change which findings block.
- A rollup HEALTHY must never be presented, named or wired as readiness. The H2 stage may add a display rollup; a gating entity is
  a separate owner-approved scope and is not part of H0 to H2.

## 6. Reason-code ownership

- `registry/health_reason_codes.yaml` is the **only** owner of a reason code, its severity, `blocks_manual_control` and
  `affects_forecast`. Firmware text, Home Assistant templates, dashboards and Intelligence consume codes by name.
- A code used anywhere that is not in the registry is a defect. A new code (for example the working names `RTC_SYNC_DISABLED`,
  `RTC_STALL_TRANSIENT`, `RTC_STALL_SUSTAINED`, `FUTURE_TIMESTAMP`) needs: a registry entry with severity and blocking flag, the
  registry validator passing, a golden vector, and a docs line, in one reviewed change. No HA-local invented code.
- A code's severity and blocking flag are not tunable per installation. Thresholds that choose between two existing codes are
  (section 7).
- The registry currently holds 70 reason codes; the architecture document says 46 (M-01).

## 7. Source of freshness limits

- The check thresholds live in `registry/system_health_checks.yaml` (`warning_threshold_seconds`, `failure_threshold_seconds`).
  Telemetry 60/180 s, configuration 180/600 s, RTC read 180 s (single tier), correction stuck 180 s, counter windows 600 s and 1800 s.
- `ecco_core/freshness.py` is the intended single catalogue for limits shared with other layers. It carries the **failure**
  thresholds (180 s, 600 s) and notes the warning tiers only in text (M-14). HA carries none: its communications row uses online flags.
- Rules for any future configurable limit: it may only **tighten** a defined limit, never loosen it (the existing
  `FreshnessPolicy` rule); a limit with no defined source stays unresolved and is UNKNOWN, never fresh; the effective value and its
  source are exposed with the result; a threshold change is a reviewed change with a golden vector, not a silent helper edit.

## 8. Registry versus Home Assistant implementation

| Measure | Value | Source |
|---|---|---|
| Registry checks | 63 (58 automatic, 3 diagnostic_only, 2 manual_only) | registry, tested |
| Registry `implementation_status` | 41 designed, 22 implemented_offline | registry, tested |
| Registry `live_proof_status` | 63 of 63 "unknown", even for the checks the architecture document calls live-proven; the field is not maintained | registry, tested |
| Reason codes | 70 | registry, tested |
| Checks required to be able to block control | 11 | engine, tested |
| Checks declared represented by the ten HA sensors | 32 | package attributes, tested |
| Checks not represented | 31, including the ten the architecture document lists and the two simplified freshness checks | derived |
| Architecture document header | "the full 43-check architecture" and "17 of 46 reason codes", stale against 63 / 70 | M-01 |
| Referenced design documents | `SYSTEM_HEALTH_HA_DESIGN.md`, `SYSTEM_HEALTH_DASHBOARD_DESIGN.md`, `SYSTEM_HEALTH_REASON_CODES.md` are cited by the public architecture document but exist only in the private repository | observed |

The stale header is **recorded, not edited** (a docs-only change in this repository must first pass the proof-chain suites; that is a
separate scope).

## 9. Preserving the raw RTC warnings (design-only)

The measured RTC behaviour (closeout of 17 October, REPORTED) is a stale inverter clock image on roughly 6 % of reads, 84 stall
periods a day, none beyond 133 s, with no write gated by the stall flag. The contract keeps that **visible and unmodified**:

- The raw `rtc_stall_detected` boolean, the `RTC_STALL_DETECTED` code and the WARNING-eligible record stay available at all times.
  Today the engine reports WARNING for any stall, isolated or sustained (HV-C01, HV-C02, M-09).
- Any later **presentation** split (isolated or transient versus sustained, PENDING HV-P01) is separate from the raw record, needs
  owner decision **O-2**, and may never: reach FAILED from a stall alone; hide RTC_CORRECTION_ACTIVE/STUCK, NTP loss or a failed
  correction; reclassify UNKNOWN; or lower the existing blocking behaviour.
- Automatic clock sync OFF must become its own visible condition (PENDING HV-P02, **O-7**), not a silent SUPPRESSED (HV-C11).
- Correction busy keeps its brackets: ACTIVE below 180 s and blocking, STUCK FAILED from 180 s (HV-C03 to HV-C05).
- No threshold is downgraded by this contract or by H1.

## 10. Time handling: UTC-aware, and the UK 25 h and 23 h nights

The engine subtracts datetimes. Python subtracts two aware datetimes that **share one tzinfo object** by wall clock and ignores the
UTC offset. On a UK clock-change night local wall clocks repeat or skip an hour, so with `Europe/London` local datetimes the result
is wrong, in both directions:

| Night | Instants (UTC) | Correct (UTC-aware) | Same-tzinfo local datetimes | Vectors |
|---|---|---|---|---|
| 25 Oct 2026, 25 h (fall-back, 01:00-02:00 repeats) | 00:59:50 to 01:00:50, 60 s apart | DEGRADED, age 60 s | **HEALTHY, age -3540 s** | HV-F01, HV-F02 |
| 28 Mar 2027, 23 h (spring-forward, 01:00-02:00 skipped) | 00:59:50 to 01:00:50, 60 s apart | DEGRADED, age 60 s | **FAILED, age 3660 s** (false, and not ready) | HV-F04, HV-F05 |
| 25 Oct 2026, correction active 180 s | 00:59:00 to 01:02:00 | FAILED STUCK | **HEALTHY, age -3420 s** (stuck correction missed) | HV-F06, HV-F07 |
| 25 Oct 2026, failed-correction window | baseline 00:30, now 01:10 | WARNING | UNKNOWN (fails quiet) | HV-F08, HV-F09 |

Mixed inputs (local `now`, UTC inputs) are correct (HV-F03). The contract rule: **every timestamp reaching the engine or a future
Home Assistant health computation is UTC-aware or epoch seconds, never a local datetime** (M-06, PENDING HV-P12). Home Assistant's
`as_timestamp()` is epoch-based and so is safe by construction; a reference-engine caller must normalise. This section is about time
arithmetic only. It does not touch the DST plan, the 25 October conditional exception or any firmware or RTC behaviour.

## 11. Design versus implementation mismatches (all recorded, none fixed)

| Id | Area | Statement |
|---|---|---|
| M-01 | docs | The architecture document says 43 checks and 46 reason codes; the registry has 63 and 70. |
| M-02 | HA | Only ten per-subsystem sensors exist; no rollup, no attention flag, no gating readiness entity. |
| M-03 | engine | Result types lack `last_good`, `source_signals`, the subsystem flags and the other evidence fields the architecture document lists. |
| M-04 | engine | An absent check is not UNKNOWN in the overall; overall can be HEALTHY while a required check is missing (readiness does fail closed). |
| M-05 | engine | A future timestamp is HEALTHY (negative age); `ecco_core.freshness` treats it as never fresh. |
| M-06 | engine | Same-tzinfo local datetimes give wrong ages across UK clock changes. |
| M-07 | engine | UNKNOWN from an INFORMATIONAL subsystem is reported with rank 1 while UNKNOWN's own rank is 2. |
| M-08 | HA | Communications uses online flags only and maps unknown/unavailable to FAILED. |
| M-09 | engine | A stall is a plain boolean; isolated and sustained are indistinguishable. |
| M-10 | engine/HA | Sync OFF is SUPPRESSED with no reason, overall HEALTHY, ready; not represented in HA. |
| M-11 | engine vs HA | Counter-delta window semantics differ: baseline-aged-window with UNKNOWN on reset (engine) versus a latched 1800 s window with reset as baseline-only (HA, per its documentation; HA templates were not evaluated). |
| M-12 | HA | Durations from `last_changed` under-report across a restart or reconnect (documented limitation). |
| M-13 | engine | The UNKNOWN reason is free text only. |
| M-14 | freshness | Limits exist in three places; only failure thresholds are in the shared catalogue. |

## 12. Tests: what they prove

`python health/tests/test_health_v2_golden.py` (offline, no network, fixed `now`, about a second):

| Block | Content | A PASS means |
|---|---|---|
| ENGINE vectors HV-A01 to HV-F09 (47) | healthy/current, UNKNOWN/unavailable/missing, RTC stall, correction busy/stuck/failed, sync OFF, telemetry 59/60/70/179/180/200 s, configuration 179/180/599/600 s, future timestamp, HA restart, counter reset, the 25 h and 23 h nights | the **current engine** gives exactly that result on that synthetic input |
| Aggregation HV-G01 to HV-G11 (11) | worst-of, caps, UNKNOWN vs WARNING and DEGRADED, SUPPRESSED, diagnostic-only, empty | the current aggregation rules |
| Sweeps (8) | a bare input is never HEALTHY; each required check omitted or bare makes readiness False; ageing is monotonic; determinism and order-independence; tier map complete | those rules hold across the whole registry |
| Ledger M-01 to M-14 and the HA mapping | the recorded facts about the registry, the documents and the package | the fact **still holds**; a failure means existing code changed and this contract must be revisited |
| PENDING HV-P01 to HV-P12 | future semantics | **nothing**: only that each is well formed and cites a ledger entry. They are never counted as PASS. |

A negative control was run outside the repository: planting three engine bugs in a scratch copy (a `>=`/`>` boundary, a counter
reset read as no failure, an unknown active flag read as healthy) made the suite fail each time.

What the suite does **not** prove: any Home Assistant behaviour (templates are not rendered), any live threshold, any behaviour of
the real system, or any PENDING semantic. The synthetic vectors say nothing about how often any condition occurs.

## 13. Owner decisions needed before H2 and H4

| Id | Question | Needed before |
|---|---|---|
| O-1 | A system-wide display rollup: strict UNKNOWN until required coverage is complete (A), or worst-evaluated state labelled PARTIAL with `complete: false` (B)? | H2 |
| O-2 | RTC stall presentation: may an isolated stall below a configurable duration show below WARNING (for example DEGRADED), with the raw record untouched? What duration and recurrence limits? | H4 |
| O-3 | HA communications: should `unknown`/`unavailable` become UNKNOWN rather than FAILED, as in the engine? | H2/H3 |
| O-4 | Counter reset rule: engine UNKNOWN until a fresh window, or HA baseline-only? One rule for both. | H3 |
| O-5 | A timestamp later than now: UNKNOWN (working name FUTURE_TIMESTAMP) with what skew allowance, in seconds? | engine follow-up, H3 |
| O-6 | Is a display-only rollup acceptable at all now, and under what name, so it cannot be mistaken for readiness? | H2 |
| O-7 | Automatic clock sync OFF: a new visible reason (working name RTC_SYNC_DISABLED) and its severity? | H4 |
| O-8 | Are runtime fixes to the existing engine wanted (M-04 absent-check, M-05 future time, M-06 time normalisation, M-07 rank)? `health/system_health.py` is read-only in this job, so this is a separate scope with its own proof-chain check. | after H1 |
| O-9 | A separate docs-only change to reconcile the stale 43/46 header and to bring the three private design documents into the public tree? | optional |

## 14. Boundaries

H0 and H1 add only this document, `health/tests/test_health_v2_golden.py` and three `health_v2_*.json` fixtures. They change no
existing file, install nothing, read nothing live and write nothing outside the working tree. The pure engine remains a reference
and test engine; it is not the production Home Assistant implementation.
