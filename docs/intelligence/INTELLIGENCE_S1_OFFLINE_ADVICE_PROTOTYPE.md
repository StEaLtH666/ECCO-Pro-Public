# Intelligence S1: offline advice harness (PROTOTYPE, decisions D1-D9 OPEN)

> **PROTOTYPE | offline, synthetic inputs only | SHADOW, applies nothing | not production runtime | not configured policy |
> Intelligence decisions D1-D9 (I-D1..I-D9) OPEN**
>
> The harness turns explicit mock records into a typed report built from the existing V1.1 advisors. It has no runner, no Home
> Assistant contact, no statistics export, no network, no schedule and no control path. An OPEN decision withholds every item
> that depends on it; no value in this document is a setting for any installation.

- Code: [`intelligence/prototypes/s1_advice/`](../../intelligence/prototypes/s1_advice/) (`scenario.py` inputs, `harness.py` the run,
  `fixtures.py` synthetic scenarios, `__main__.py` a CLI that prints the synthetic examples).
- Tests: [`intelligence/tests/test_s1_advice_prototype.py`](../../intelligence/tests/test_s1_advice_prototype.py).
- Builds on: [`INTELLIGENCE_V1_1_FOUNDATION.md`](INTELLIGENCE_V1_1_FOUNDATION.md), the Intelligence S0 input contract
  ([`INTELLIGENCE_S0_INPUT_CONTRACT.md`](INTELLIGENCE_S0_INPUT_CONTRACT.md)), the shared foundation contract
  ([`INTELLIGENCE_FOUNDATION_CONTRACT.md`](INTELLIGENCE_FOUNDATION_CONTRACT.md)) and
  [`DATA_QUALITY_METHOD.md`](DATA_QUALITY_METHOD.md).

Nothing existing is changed: the V1 engine, the V1.1 advisors, `SiteConfig`, `ecco_core`, Home Assistant packages, firmware and
the registry are only imported or read. The decision register, its typed values, provenance, gates, freshness limits and
`apply_to_siteconfig` come from [`intelligence/site_decisions.py`](../../intelligence/site_decisions.py), and clock-change
periods are measured by [`intelligence/periods.py`](../../intelligence/periods.py). The prototype declares none of these itself.

## 1. What it does

```
Scenario (explicit, typed)                       Report (SHADOW, applies_nothing: true)
  now, mock hourly records, SiteConfig            items: overnight_demand, charge_target, export_event,
    (site facts; its battery fields and window          dump_to_grid, v1_report_summary
     are replaced, never kept)                    each: status, advice (or withheld_because), decisions_used,
  tariff cheap window + rates                          decision_provenance, notes
  SOC / inverter status / reserve helper /  -->  issues, data_quality, inputs (ages and limits),
    grid-charge limit, each with the instant      reserve_semantics, decisions (I-D labels), accept_provenance
    it was observed
  typed decisions D1-D9 (OPEN unless a typed SYNTHETIC_TEST record)
  events, Dump duration, power limits
```

Each item calls the existing advisor unchanged and returns its answer as is: `overnight.learn_overnight` (via `nightly_totals`),
`charge_target.advise_charge_target`, `events.advise_event`, `dump_advice.advise_dump`, and a summary of
`engine.IntelligenceEngine.run`. A test pins that the charge-target and overnight items are byte-identical to calling those
functions directly. The harness only adds:

1. **An input gate.** Hour records that are naive, unaligned, non-finite, negative, implausible, duplicated (every copy) or not
   yet complete are excluded and counted; `now` must be aware. A history whose newest complete hour is older than its limit
   (6 h, or tighter under I-D6), a missing or invalid tariff, an invalid decision, an input that is not fresh under its own
   limit or a capacity source outside the band withholds what depends on it.
2. **The decision gates.** See section 3.
3. **One report shape** with an invariant check: every item is SHADOW and applies nothing; a BLOCKED item carries no advice and
   names why; an item that is not BLOCKED rests only on satisfied decisions; no key reads like an instruction; the report is
   strict JSON (no NaN).

```
python -m intelligence.prototypes.s1_advice --example blocked --summary     # every decision OPEN
python -m intelligence.prototypes.s1_advice --example shadow --summary      # SYNTHETIC_TEST decisions
python -m intelligence.prototypes.s1_advice --example dst-open              # a clock-change period, D9 OPEN
python -m intelligence.prototypes.s1_advice --example dst-normalised        # the same, D9 a SYNTHETIC_TEST record
```

## 2. Status values

| Status | Meaning |
|---|---|
| `OK` | the advisor answered; the numbers rest on the stated (synthetic) decisions and inputs |
| `INSUFFICIENT_DATA` | the advisor answered with a flagged conservative fallback (for example "retain the battery") |
| `BLOCKED` | withheld: a decision is OPEN, INVALID or not accepted, an input is stale / unknown / malformed, or a precondition fails; no number |

## 3. Decision gates

The gates are `site_decisions.ITEM_GATES` (the S1 kind `v1_report_summary` is the register's `v1_summary`) applied by
`site_decisions.gate`:

| Item | Depends on | Also blocked by |
|---|---|---|
| `overnight_demand` | D8; D9 when its period, or a period in its learning history, crosses a clock change | stale history, no / invalid tariff, a period starting or ending inside a repeated or missing hour (fixed rule, whatever D9 says) |
| `charge_target` | D1, D2, D3, D5, D8 (+ D9 as above, and when its charge window itself crosses a clock change; + D4 when two or more capacity sources are present) | the above, a charge window starting or ending inside a repeated or missing hour (fixed rule, `DST_BOUNDARY_IN_CHANGED_HOUR` from `site_decisions.gate`), capacity mismatch, no fresh grid-charge limit or charge window, a reserve helper present but not fresh or out of range |
| `export_event` | D1, D2, D3, D5, D6, D8 (+ D4 as above; + D9 when a segment crosses a change, stricter than the register) | the above (for the refill window); the advisor's own rules (stale SOC, unhealthy or unknown inverter) |
| `dump_to_grid` | D1, D2, D3, D5, D6, D8 (+ D4, D9 as for export) | the above (for the next and the refill window); the advisor's own rules (stale SOC, unhealthy or unknown inverter, open window) |
| `v1_report_summary` | D1, D2, D3, D5, D8 (+ D4) | the above, the fixed rule over every window the engine is given; not D9, because the V1 engine sums per-hour slots instead of period totals |

The cheap window is measured with `periods.period_profile` on each date an item uses it (the next window, the refill
windows, the V1 engine's four windows). A window that crosses a clock change puts I-D9 in scope for the charge target; a
window whose start or end lies in the repeated autumn hour or the missing spring hour, or which `periods` refuses, BLOCKs
the charge target, export, Dump and V1 summary with `DST_BOUNDARY_IN_CHANGED_HOUR` whatever I-D9 says. The prototype
judges I-D9 scope per period (the window, the planned period and its learning periods); the reference SHADOW cycle uses a
forward 48 h horizon instead, which is broader.

- **Typed decisions.** A decision is filled only by a `DecisionRecord` whose value is the register's typed record
  (`PlanningFloor`, `Protection`, `CapacityAuthority`, `CapacityBand`, `Efficiency`, `FreshnessOverrides`, `HD1Cutover`,
  `DSTPolicy`). A bare number, free text or an incomplete record is INVALID, and an INVALID decision BLOCKs every item it can
  gate (an INVALID D9 also withholds export and Dump advice). Keys `D<n>` and `I-D<n>` both load.
- **Provenance.** Only `SYNTHETIC_TEST` is accepted: the harness and the CLI pass `accept_provenance={SYNTHETIC_TEST}` to the
  register explicitly and refuse any wider set. A known other provenance counts as OPEN; an unknown one or an `OWNER_RECORD`
  is INVALID (an owner record is never built in code). Every item that used a filled decision says
  `decision_provenance: SYNTHETIC_TEST`. The prototype cannot mark a decision as the owner's.
- **Effective configuration.** `site_decisions.apply_to_siteconfig` builds it from satisfied D1 / D2 / D3 / D5 and judged
  readings only: the grid-charge limit reading (`limits.max_grid_charge_w`, never the example 8 kW), the reserve helper when
  D1 names it, and the charge window (the scenario's declared tariff window, judged as observed at `now` under the I-D6
  limit of `tariff.import_rates` and reported as a WARN: it is not a verified tariff). A window that crosses local midnight
  cannot be carried into `SiteConfig` by the foundation contract (`CHARGE_WINDOW_KEY` takes `0 <= start < end <= 1440`), so
  the battery items are then withheld. This is a capability loss against the prototype before reconciliation, which
  planned such a window (23:30-05:30, 6 h) from the declared tariff, never from the SiteConfig example window: the V1.1
  advisors take the window explicitly. It fails closed and is pending the integrator's contract change request CCR-1. A
  D2 sensor snapshot or a D1 feature stop level needs a fresh reading the prototype's scenarios do not carry, so those
  choices BLOCK.
- **Capacity (D4).** The band check is the register's (`site_decisions.gate` with `capacity_context`: the largest pairwise
  difference between the capacity in use and the scenario's sources); the prototype's `CAPACITY_MISMATCH` issue and blocker
  only mirror its `CAPACITY_MISMATCH_BEYOND_BAND` / `_UNKNOWN` finding, so both codes appear on a withheld item.
- **Freshness, per signal (D6).** Every input is judged under its own limit from `site_decisions.freshness_limits`: the
  defined SOC (900 s) and hourly-history (6 h) limits, tightened only, and the limits a satisfied D6 supplies within the
  900 s ceiling. A signal without a limit (for example the inverter status while D6 has none for it) is never fresh.
- **D7** is retired: the required inputs are the code constants `REQUIRED_SIGNALS` / `REQUIRED_READINGS` (add-only). The
  prototype's scenarios carry no power observations and do not consult them; the advisors' own input requirements apply, and
  the report says so. **Residual divergence:** export and Dump advice are given (OK) without the `stop.dump_soc_pct` and
  `tariff.export_rates` readings and the house / PV / battery / grid power signals the register requires for them. The
  SHADOW cycle, not this prototype, must enforce `REQUIRED_SIGNALS` / `REQUIRED_READINGS`.
- **D8** is `HD1Cutover{cutover, load_power_policy, load_counter_policy, counter_check_evidence_ref}`: EXCLUDE drops
  pre-cut-over load power, EXCLUDE_PRE_CUTOVER drops the pre-cut-over load energy that learning uses; both KEEP options need
  an evidence reference. There is no option to keep pre-cut-over load unchecked.
- **D9** is `DSTPolicy{history_rule, target_rule}`: EXCLUDE_CHANGED_PERIODS or NORMALISE_TO_NOMINAL for the learning history;
  SCALE_UP_ONLY (never scale a short period down) unless SCALE_TO_ACTUAL is recorded. The learning history is the learner's
  own `OvernightSettings.lookback_nights` (28 nights).

Only periods that had completely ended by `now` are learned from.

**Example, BLOCKED (decisions OPEN, synthetic records):**

```json
{"kind": "charge_target", "status": "BLOCKED", "advice": null, "decisions_used": ["D1", "D2", "D3", "D5", "D8"],
 "withheld_because": ["RESERVE_HELPER_NOT_FRESH", "DECISION_D1_OPEN", "DECISION_D2_OPEN", "DECISION_D3_OPEN",
                      "DECISION_D5_OPEN", "DECISION_D8_OPEN"]}
```

**Example, SHADOW (every decision but the retired D7 a SYNTHETIC_TEST record, synthetic household):** `dump_to_grid` OK,
confidence HIGH, `decision_provenance: SYNTHETIC_TEST`, stop level 56 %, export 1.8 kWh, reason "your 40% reserve plus a 5%
margin, plus 10 points for 3.1 kWh of planned demand until the next refill", input `soc` 30 s old against a 900 s limit. Not
a recommendation for any installation.

## 4. Reserve semantics (kept apart in every report)

| Level | Role | Used in the arithmetic |
|---|---|---|
| The planning floor (D1: the Intelligence user reserve, a new single setting, the HA helper or a feature stop level) | soft planning floor | yes |
| Home Assistant reserve helper | raise-only input: it can raise the floor, never lower it; present but not fresh BLOCKs | yes, only upwards |
| Inverter battery shutdown SOC | physical protection (D2), enforced by the inverter, never written by ECCO | yes: raises the technical minimum, never lowers it |
| A TOU slot's target SOC | an inverter schedule setting | no (reported only) |
| Dump to Grid stop SOC | a feature's stop level, enforced for that feature only | no (reported only) |

So a 5 % helper with a 40 % planning floor plans at 40 % (binding: `user_reserve`), a 60 % helper raises it to 60 %, and a
protection level above the floor binds. The protection level is UNKNOWN while D2 is OPEN and is never assumed.

## 5. Owner decision sheet (D1-D9)

General, installation-independent guidance. "Safe default to consider" is a suggestion for the owner's decision, not a choice
made here; until a decision is recorded the gate stays OPEN. The register's typed options are in the foundation contract.

| ID | Decision | Known inputs (generic) | Safe default to consider | Cannot be decided without the owner | Consequence while OPEN | Consequence once recorded |
|---|---|---|---|---|---|---|
| D1 | Which setting is the soft planning floor, and must advice honour it | shipped user reserve 40; the HA helper (owner-set, raise-only); feature stop levels are separate | keep the planning floor separate from the helper; plan at the higher of the two | the owner's preferred floor and whether advice may ever plan below the shipped 40 | charge target, events, Dump and V1 summary BLOCKED | the floor enters every budget, always at or above the protection level |
| D2 | The inverter's own protection level (shutdown SOC) and how it is supplied | a read-only inverter setting; ECCO has no write path | the owner reads it from the inverter display and states it | its actual value on the installation | same items BLOCKED; protection shown UNKNOWN | it raises the technical minimum (never lowers it) |
| D3 | Battery capacity authority | owner helper, a learned kWh per SOC %, an Ah register (needs a voltage), the shipped example (never an authority) | the owner-set helper as the authority, the others as cross-checks | which figure is right for the installation | battery items BLOCKED | the authority is used; other sources are checked against the band (D4) |
| D4 | Capacity mismatch band | the architecture states +/-8 % capacity uncertainty | 8 % symmetric (PROPOSED, not an owner decision) | whether 8 % suits the installation's sources | with two or more capacity sources present the battery items are BLOCKED (DECISION_D4_OPEN); the PROPOSED 8 % is never applied | the recorded band is checked; a mismatch beyond it BLOCKs |
| D5 | Canonical efficiency | helper (percent, round-trip), SiteConfig (fraction, round-trip; sqrt each way) | one round-trip fraction | the installation's measured or rated value | battery items BLOCKED | normalised to round-trip; one-way = sqrt |
| D6 | Advisory freshness limits, per signal | only SOC (900 s) and hourly history (6 h) are defined; 900 s ceiling for the others | short limits, a few poll intervals | the limits that suit the installation's polling | export and Dump advice BLOCKED; every input without a limit (the grid-charge limit, the helper, the tariff window) is never fresh, so the battery items are BLOCKED too | each signal is usable when fresh under its own limit |
| D7 | Required signals per advisor (retired) | the code constants REQUIRED_SIGNALS / REQUIRED_READINGS | none: no longer an owner decision | nothing (a site may only add requirements) | the advisors' own rules apply | additions only |
| D8 | Derived house-load cut-over and pre-fix history | the derived load sensor took effect at an installation-specific instant | exclude pre-cut-over load power and energy until the energy counter is shown unaffected | the cut-over instant; whether the counter is affected (a real-data check) | every item BLOCKED (learning withheld) | the policy is applied to the history (exclude, or keep only with an evidence reference) |
| D9 | Clock-change period policy | 25 h / 23 h local days; the learner uses raw totals | normalise history to the nominal length and never scale a short period down (PROPOSED, not an owner decision) | the owner's preference | a period crossing a change, or a learning history holding one, is BLOCKED (ordinary periods are unaffected) | the history rule is applied and the planning value scaled by the target rule |

## 6. Findings (recorded, not changed)

1. `events.advise_event` reports a predicted `soc_at_start_pct` that can be negative (for example -18.5 on the heavy synthetic
   household) when the planned demand before the event exceeds the stored energy. The advice itself is correct (cover false,
   export 0), but a display must not show that number as a battery level.
2. On the heavy synthetic household the closed-form charge target needs more than 100 % (a SHORTFALL at 100 %) while the V1
   engine's hourly simulation recommends 80 %: the V1.1 budget ignores PV unless the caller vouches for it and plans on p90
   demand. Both are conservative in different ways; a later stage must choose one, or show both clearly.
3. The V1.1 learner plans a 25 h period from ordinary periods (the S0 KNOWN LIMITATION). The harness blocks such a period while
   D9 is OPEN instead of under-planning it.
4. An independent read-only review of the first draft found eight defects, all fixed and pinned by tests: an exception for a
   period inside the repeated autumn hour; D4 and D6 used without being named as dependencies; a learning history containing a
   clock-change period learned as raw totals while D9 was OPEN; the period still in progress at `now` being learned from;
   shipped default numbers shown while D1 / D2 were OPEN; exceptions on a malformed prior or decision record; and an invariant
   check that did not verify the decision gates. Its debatable points (a helper that pushes the floor above 100 %, a protection
   level below the placeholder, the V1 summary's D9 label, the severity of an unknown decision id) are handled as notes.
5. Reconciliation onto the shared register (foundation, part B), all pinned by tests: any recorded D9 value was read as
   "normalise" (fail-open), now an invalid D9 is INVALID and BLOCKs; the unchecked `KEEP_PRE_CUTOVER_LOAD` option is removed;
   a changed target period is scaled up only unless SCALE_TO_ACTUAL is recorded; D6 gates per signal; the inverter input is
   `inverter.healthy`; the learning lookback is the learner's own 28 nights (it was 40 days, which kept D9 in scope 12 days
   longer than the learner looks back); the effective configuration no longer keeps the example grid-charge limit or window;
   free-text decision values are INVALID. The orchestration glue (the history gate, the period learning and the item order)
   stays in the prototype until the SHADOW cycle takes it over; that duplication is recorded, not removed.
6. Two adversarial reviews of the reconciliation, fixed and pinned by tests: the charge window itself was never put under
   the DST rules (a window crossing a change with D9 OPEN, or starting in the repeated or missing hour, still gave a charge
   target); the I-D4 band arithmetic was duplicated in the prototype (now the register's only); a fresh helper outside
   0..100 was reported as not fresh (now `RESERVE_HELPER_OUT_OF_RANGE`); several fixes had no check that fails when they
   are reverted. Recorded residuals, not changed here: `REQUIRED_SIGNALS` / `REQUIRED_READINGS` are not consulted (section
   3, D7); a midnight-crossing window is withheld until CCR-1; the I-D9 scope is per period, not the cycle's 48 h horizon.
   The SHADOW fixture's D1 (40 %), D3 (the example capacity), D5 (0.90) and tariff window (00:30-05:30) all
   equal the SiteConfig example values, so the command-line before / after output is no evidence against an example-value
   leak; checks with distinct D1 / D3 / D5 values and a 01:00-04:30 window pin that every advisor plans on the effective
   configuration.

## 7. A minimal future S1 measured backtest (NOT EXECUTED)

Each step needs its own owner authorisation; none is performed by this prototype.

1. **One read-only copy.** The owner makes a one-time copy of the Home Assistant recorder database (or exports hourly long-term
   statistics with the existing `export_ha_statistics.py`) from a backup, not from the running system. No Home Assistant REST
   or InfluxDB access by an agent. The copy stays in local, offline storage and is never committed.
2. **Quality gate first.** Run `quality_report.py` on the copy. Record per signal: depth, coverage, gaps, stalls, duplicate and
   unit problems, and the share of hours with export (where native load can read 0 W).
3. **Source exclusion record.** Write down, before scoring: the derived-load cut-over and the D8 policy, declared away periods,
   the clock-change periods and the D9 policy, any hours excluded by the quality gate. Nothing is excluded after seeing scores.
4. **Walk-forward scorecard.** Replay the engine and the V1.1 advisors at a fixed local time each day using only history before
   that instant (`replay`, `scorecard`), with the recorded decisions D1-D9. Score next-hour, overnight and whole-day load, PV
   day-ahead, and the realised floor-breach rate of any advice.
5. **Report without claims.** Publish only aggregate error, bias and band coverage with sample sizes, against the gate already
   in the V1 architecture (section 10.4), and say what could not be scored. No accuracy claim is made before this exists.

Site-configuration decisions that step 1-4 need: D1-D9, the overnight conservative default (`overnight_prior_kwh`), the
installation's array size (PV plausibility), the grid-charge limit, the tariff's cheap window and the replay time of day.

## 8. Not implemented (on purpose)

No runner, no Home Assistant entity, no sensor publication, no dashboard, no schedule, no battery-control decision, no command
of any kind, no real-data backtest, no production use. The harness is a prototype for review.
