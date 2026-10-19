# Intelligence S0: the input contract (DRAFT, owner decisions open)

Status: **draft, offline only, no decision made.** This document and its tool define *what the Intelligence advisors would
rest on* and check that a written-down set of inputs is consistent. It chooses no reserve, no capacity, no efficiency and no
freshness limit. Every number marked **PROPOSED** is a suggestion for the owner to accept, change or reject.

- Tool: [`intelligence/tools/s0_input_consistency.py`](../../intelligence/tools/s0_input_consistency.py) (pure functions, standard library
  plus `ecco_core.state`; reads only a declaration file the caller names; calls nothing, writes nothing, contacts nothing).
- Tests: [`intelligence/tests/test_s0_input_contract.py`](../../intelligence/tests/test_s0_input_contract.py) (synthetic data, offline).
- Context: [`INTELLIGENCE_V1_1_FOUNDATION.md`](INTELLIGENCE_V1_1_FOUNDATION.md), [`DATA_INVENTORY.md`](DATA_INVENTORY.md),
  [`../architecture/MODULAR_ARCHITECTURE.md`](../architecture/MODULAR_ARCHITECTURE.md), [`../../SAFETY.md`](../../SAFETY.md) section 9.

Nothing here changes `SiteConfig`, any runtime default, `ecco_core`, a Home Assistant package, the firmware, the registry or the
output of the V1 engine or the V1.1 advisors. Intelligence still has no write path.

## 1. Four different things are called "reserve"

A battery percentage can mean a preference, a helper, where one feature stops, or a protection. They differ in who sets them,
what reads them and whether anything enforces them. The diagnostic keeps them as four **roles** and never treats one as another.

| Role | Example (illustration only; sites differ) | Set by | Read by today | Enforced by | Writable by ECCO |
|---|---|---|---|---|---|
| `SOFT_PLANNING_FLOOR` | `SiteConfig.user_reserve_soc_pct`, default 40 | the installation's Intelligence configuration | every Intelligence advisor (plus a 5-point margin) | nothing; it only limits what Intelligence *recommends* | not applicable (a setting of the offline model) |
| `HA_RESERVE_HELPER` | `input_number.ecco_minimum_reserve_soc` (0-80 %), first-run default 40 since RSV1, older installs keep their own value (a value of 15 is the historical first-run default) | the owner in Home Assistant | the time-to-reserve estimate, the TOU target-SOC edit bound, and Intelligence as an input that can only **raise** the floor | nothing (SAFETY.md section 9) | a Home Assistant helper |
| `FEATURE_STOP_LEVEL` | the Dump to Grid **Stop SOC** (firmware minimum 10 %, Home Assistant bound 10-90 %) | the owner, per run | the Dump to Grid firmware and its scripts; **not** the planning floor or the helper | the dongle firmware, for that feature only | yes, through the feature's own guarded controls |
| `PHYSICAL_PROTECTION` | the inverter's own battery shutdown / low-battery levels (registers 217-219, read-only here) | the inverter / battery configuration | nobody in ECCO (Intelligence does **not** read it) | the inverter | **no**: no write path exists and the levels are owner-locked |

**Soft planning floor versus physical protection.** The planning floor is a promise the *advice* makes: "I will not recommend a
plan that takes the battery below this". It protects nothing by itself. The protection is what the inverter does regardless of any
advice. A floor below the protection level is therefore meaningless in practice (the protection binds first), and a feature stop
level below it asks for something the inverter will refuse or override.

**Scope of each today (so the owner can see what a change would affect):**

| Consumer | Reads the floor | Reads the helper | Reads the stop level | Reads the protection |
|---|---|---|---|---|
| V1 engine and V1.1 advisors (offline) | yes | as a raise-only input | no | no (`technical_min_soc_pct` is a placeholder default of 10 that the installation must set) |
| Dump to Grid (firmware) | no | no | yes | no |
| TOU target-SOC edit (ACS0) | no | yes (bound: the larger of shutdown SOC and helper) | no | yes (as the shutdown SOC) |
| Battery time-to-reserve (FE-1) | no | yes | no | no |
| Dashboard recommendation script | no | no (hard-codes 10 %) | no | no |

**Owner choices (not made here): D1 and D2 in section 8.**

## 2. Input inventory: unit, sign, provenance, age

Entity names are the repository's generic ones; installation-specific ids belong in a local profile, never here. "Defined limit"
means a freshness limit the project already uses *for advisory purposes* (`ecco_core.freshness`); where it says *unresolved* there is
none, and the diagnostic treats the reading as never fresh until the owner supplies one.

| Signal (state-model name) | Unit / sign | Provenance | Age source | Defined advisory limit | Known hazard |
|---|---|---|---|---|---|
| `battery.soc` | % (integer steps) | controller register 184 (raw sensor); canonical alias `sensor.ecco_battery_soc` | poll text / report age | **900 s** (`advisor.STALE_SOC_SECONDS`); the Dump gate separately needs under 90 s | **the canonical alias renders an unreadable state as 0**; FE-1 therefore reads the raw sensor |
| `battery.power` | W, **positive = discharge** | controller register 190 | poll | unresolved | sign easily flipped by a consumer |
| `grid.power` | W, **positive = import**, negative = export | the external CT clamp (canonical alias); the inverter's own reading differs | poll | unresolved (control gate 90 s is a different purpose) | two sources, CT versus inverter |
| `house.power` | W, load | derived (`sensor.ecco_house_power`): native load when credible, inverter + grid CT when the native load is unavailable or reads exactly 0 W during export, unavailable otherwise | per-poll text, 60 s inside the sensor | unresolved | **pre-fix history is unreliable (section 4)** |
| `pv.power` | W, sum of strings | controller | poll | unresolved | display only in V1 |
| `pv.forecast.*` | kWh per source | Forecast.Solar, Solcast, blend | provider issue time | none | raw sources biased high in autumn and winter; the engine corrects and bounds them |
| hourly history | kWh per UTC hour from **counters** | HA statistics export, canonical History | newest complete hour | **6 h** (`engine.py`) | 0.1 kWh counter resolution; gaps; see section 4 |
| tariff windows and rates | local wall-clock windows; p/kWh | configuration (default 00:30-05:30) or the tariff integration's rate events | event time | none | Saving Session reward units unconfirmed (open decision O-4) |
| `reserve.ha_minimum_soc` | % | the reserve helper | state age | unresolved | can only raise the floor |
| inverter status | enumeration | controller | poll | unresolved | without a limit export advice is withheld by design |

### Battery capacity and efficiency sources

| Quantity | Source | Unit | Notes |
|---|---|---|---|
| capacity | `input_number.ecco_battery_model_capacity` (owner helper, 5-100) | kWh | mirrored as `sensor.ecco_config_battery_capacity` for InfluxDB |
| capacity | `SiteConfig.battery_capacity_kwh` | kWh | a shipped **example** value; the diagnostic flags it when nothing independent confirms it |
| capacity | FE-1 learned kWh per SOC % (`ecco_battery_runtime`) | kWh | measured from discharge episodes; has an age |
| capacity | register 204 (battery capacity, Ah) | Ah | read-only; currently unused; needs a nominal voltage to compare |
| capacity | InfluxDB Battery Outlook record (`model_capacity_kwh`) | kWh | the runtime-config copy that the Flux task stores |
| efficiency | `input_number.ecco_round_trip_efficiency` (70-100) | **percent**, **round-trip** | used whole by the tariff arithmetic (`cost / efficiency`) |
| efficiency | `SiteConfig.round_trip_efficiency` (0.5-1.0) | **fraction**, round-trip | the engine applies `sqrt()` each way (`battery.eta_one_way`) |
| efficiency | Battery Outlook task | percent in, **sqrt() inside**, clamped 0.5-1.0 | one-way value derived from the round-trip one |

All current sources are declared round-trip; the risk is a *future* consumer or a hand-entered value that is one-way, or a
percent read as a fraction. The diagnostic detects that (section 5). It does **not** know which capacity is right: the learned
value, the helper and the example can all differ, and the architecture states a +/-8 % capacity uncertainty.

## 3. The diagnostic (what it checks, fail closed)

Input: a *declaration* the caller writes (or `--example` / `--example-faulty`, synthetic). Output: a `Report` with `mode: SHADOW`,
`applies_nothing: true`, a verdict, findings and the decision register. There is no field in which it could state a recommended
value; it only says whether the declared values are consistent and what is still undecided.

```
python intelligence/tools/s0_input_consistency.py --example            # exit 1 while BLOCKED
python intelligence/tools/s0_input_consistency.py --example-faulty
python intelligence/tools/s0_input_consistency.py --declaration decl.json --json
```

Verdict order: `BLOCKED` (any BLOCK) > `OPEN_DECISIONS` (all clear but a decision is open) > `CONSISTENT_WITH_WARNINGS` >
`CONSISTENT`. Fail closed means: a missing, non-numeric, unit-mismatching, sign-mismatching, stale or unknown-age reading is never
usable; a required signal with no defined limit can never be fresh; a source whose basis or unit is not stated is left out of
comparisons and reported, never guessed.

### Findings catalogue

| Code | Severity | Meaning |
|---|---|---|
| `PHYSICAL_PROTECTION_UNKNOWN` | BLOCK | the inverter protection level was not supplied; never assumed |
| `PROTECTION_DECLARED_WRITABLE` | BLOCK | a protection level declared writable by ECCO (there is no write path) |
| `NO_PLANNING_FLOOR_DECLARED` | BLOCK | no soft planning floor in the declaration |
| `RESERVE_VALUE_UNKNOWN` / `RESERVE_VALUE_INVALID` | BLOCK | no value / not a finite percentage in 0..100 |
| `RESERVE_ROLE_UNKNOWN` / `RESERVE_DUPLICATE_NAME` | BLOCK | declaration error |
| `ENFORCEMENT_CLAIM_UNVERIFIED` | WARN | a floor or helper claimed to be enforced; SAFETY.md section 9 says nothing enforces it |
| `PLANNING_FLOOR_BELOW_PROTECTION` | WARN | the protection binds first |
| `FEATURE_STOP_BELOW_PROTECTION` | WARN | a feature stop below the inverter protection |
| `TECHNICAL_MIN_BELOW_PROTECTION` | WARN | `SiteConfig.technical_min_soc_pct` (placeholder 10) is below the protection level |
| `HA_HELPER_BELOW_PLANNING_FLOOR` | INFO | the helper cannot lower the floor, so it has no effect |
| `FEATURE_STOP_BELOW_PLANNING_FLOOR` | INFO | that feature does not read the floor today |
| `CAPACITY_MISMATCH` | WARN | two sources differ by more than the band (PROPOSED 8 %, section 6) |
| `CAPACITY_WITHIN_BAND` / `CAPACITY_SINGLE_SOURCE` | INFO | all within the band / nothing to cross-check against |
| `CAPACITY_IS_EXAMPLE_DEFAULT` | WARN | the shipped example capacity is in use without independent confirmation |
| `CAPACITY_AH_NEEDS_VOLTAGE` | WARN | an Ah figure cannot be compared without a nominal voltage; left out |
| `CAPACITY_SOURCE_AGE_UNKNOWN` | WARN | a learned capacity with no age |
| `CAPACITY_VALUE_MISSING` | WARN | no positive finite value |
| `CAPACITY_IMPLAUSIBLE` | BLOCK | outside 0.5-500 kWh after unit conversion (usually Wh read as kWh) |
| `CAPACITY_UNIT_UNKNOWN` / `CAPACITY_KIND_UNKNOWN` / `CAPACITY_UNKNOWN` | BLOCK | declaration error / no usable source at all |
| `EFFICIENCY_ONE_WAY_ROUND_TRIP_MIX` | BLOCK | same basis claimed but one value is the square root of the other |
| `EFFICIENCY_DISAGREE` | WARN | round-trip equivalents differ by more than 0.01 (PROPOSED) |
| `EFFICIENCY_LOOKS_ONE_WAY` / `EFFICIENCY_LOOKS_ROUND_TRIP` | WARN | the value is implausible for the stated basis (above 0.97 round-trip, below 0.88 one-way; PROPOSED) |
| `EFFICIENCY_BASES_DIFFER_BUT_CONSISTENT` | INFO | different bases, same physics after conversion |
| `EFFICIENCY_UNIT_UNSTATED` / `EFFICIENCY_UNIT_MISMATCH` / `EFFICIENCY_BASIS_UNSTATED` / `EFFICIENCY_VALUE_MISSING` / `EFFICIENCY_OUT_OF_RANGE` | BLOCK | declaration error; the source is not used |
| `FALSE_ZERO_SUSPECTED` | BLOCK | a canonical 0 while the raw source gives no number |
| `ZERO_UNCONFIRMED` | WARN | a lone canonical SOC of 0 with no raw source |
| `READING_NOT_NUMERIC` / `NON_NUMERIC_STATE_WITH_VALUE` | WARN | no numeric value / a value carried over a non-numeric source state |
| `UNIT_MISMATCH` / `SIGN_CONVENTION_MISMATCH` / `READING_KIND_UNKNOWN` / `SIGNAL_UNKNOWN_NAME` | BLOCK | the reading is not in the state model's unit / sign / vocabulary |
| `SIGN_UNDECLARED` | WARN | a signed signal without a declared convention |
| `READING_STALE` | BLOCK (required) / WARN | older than its advisory limit |
| `READING_AGE_UNKNOWN` | BLOCK (required) / WARN | age missing, negative, non-numeric, or no limit defined for a required signal |
| `ADVISORY_LIMIT_UNRESOLVED` | INFO | no limit exists for a non-required signal; it can never be shown fresh |
| `REQUIRED_SIGNAL_MISSING` / `SIGNAL_NO_USABLE_SOURCE` | BLOCK | a required signal has no usable fresh reading |
| `SOURCE_DISAGREEMENT` | WARN | usable sources disagree beyond the tolerance (SOC 2 points; power max(100 W, 5 %); PROPOSED) |
| `FRESHNESS_OVERRIDE_REFUSED` / `FRESHNESS_OVERRIDE_INVALID` | WARN / BLOCK | an owner limit may tighten a defined one, never loosen it |
| `HD1_CUTOVER_UNKNOWN` | BLOCK | the instant the derived load sensor took effect is not recorded |
| `LOAD_HISTORY_PRE_HD1_UNRELIABLE` / `LOAD_HISTORY_STRADDLES_HD1` | WARN | load-power history before / across that instant |
| `LOAD_HISTORY_POST_HD1` | INFO | after it (still subject to the quality gate) |
| `LOAD_COUNTER_RELIABILITY_UNKNOWN` | WARN | the load energy counter cannot be classified offline |
| `HISTORY_SERIES_UNKNOWN` | BLOCK | unknown series |
| `NIGHT_LENGTH_DIFFERS` | WARN | an overnight window lasts a different number of hours because of a clock change |

## 4. History reliability: what offline code cannot know

1. **Canonical SOC can turn an invalid input into a false 0.** Unreadable states in some canonical sensors render as 0 (recorded in
   `MODULAR_ARCHITECTURE.md` section 12). A SOC of 0 is plausible only at the protection level, so the diagnostic treats a canonical
   0 over a non-numeric raw state as `FALSE_ZERO_SUSPECTED` (BLOCK) and a lone 0 as `ZERO_UNCONFIRMED`.
2. **House-load power before the derived sensor is unreliable while exporting.** The native load register can read 0 W during an
   export; the derived sensor (`HOUSE_LOAD_HD1.md`) corrects this from the date it took effect. Load-power history older than that
   instant must not be used as truth for export periods. The instant is **site-specific and not in this repository**; the diagnostic
   takes it as an owner-supplied input (`hd1_effective_from`) and BLOCKS until it is given.
3. **Whether the load energy *counter* shares the fault is unknown.** The learners use hourly counter deltas, not the power
   reading, so they may be unaffected, but nothing here shows that. Settling it needs a check on real data (owner-authorised,
   read-only). Until then every counter period carries `LOAD_COUNTER_RELIABILITY_UNKNOWN`.
4. **Away days and other abnormal periods** are the owner's statement to make (`DECLARED_AWAY` and similar), never inferred.

## 5. Efficiency: one-way versus round-trip

The engine takes `round_trip_efficiency` and applies `sqrt()` each way. A round-trip 0.90 means 0.9487 one-way. Entering 0.9487
as the "round-trip" value silently makes the battery look better than it is; entering 0.90 where a one-way value is expected
makes it look worse. The diagnostic (a) normalises every source to a round-trip fraction using its declared unit and basis,
(b) refuses a source with no stated unit or basis, (c) warns when a value is implausible for its declared basis, and (d) BLOCKS
when two sources claim the same basis but one is the square root of the other. A round-trip 90 % and a one-way 0.9487 are reported
as consistent (INFO). Which basis and unit is canonical is **D5**.

## 6. Capacity mismatch band (PROPOSED, not accepted)

Capacities from different sources are compared pairwise with a **symmetric** relative difference `|a - b| / mean(a, b)`. A pair
above the band raises `CAPACITY_MISMATCH` (WARN). The proposed band is **8 %**, taken from the +/-8 % capacity uncertainty already
stated in the V1 architecture; it is a proposal because the learned value, a nameplate figure and an owner helper legitimately
differ by different amounts. An owner-recorded band replaces it and the report says which one applied. The comparison is
informational: it never selects a capacity. An Ah figure is compared only with a nominal voltage; a figure outside 0.5-500 kWh
is implausible (a Wh value read as kWh is the usual cause).

## 7. Clock-change nights: the 25 h and 23 h local days

Windows are local wall-clock times mapped per date, so the energy over "00:30 to 05:30" is correct on every night. The window's
*length* is not constant:

| Night starting | Local day | 00:30-05:30 window | 22:00-06:00 window |
|---|---|---|---|
| 24 Oct 2026 | 24 h | 5 h | 9 h (spans the clock going back) |
| **25 Oct 2026** | **25 h** | **6 h** | 8 h (starts after the change) |
| 27 Mar 2027 | 24 h | 5 h | 7 h (spans the clock going forward) |
| **28 Mar 2027** | **23 h** | **4 h** | 8 h (starts after the change) |

Verified offline against the real code with a flat 1 kWh/h synthetic house: `nightly_totals` reports 5.0, **6.0** and **4.0** kWh, and
dividing by the diagnostic's length factor (1.2 and 0.8) makes the nights comparable again (5.0).

**Known limitation of the current V1.1 learner (recorded, not changed):** `learn_overnight` learns raw nightly totals. On the 25 h
night it plans from ordinary 5 h nights (expected about 5.0 kWh, planning about 5.1 kWh) while the night uses 6.0 kWh, an
under-plan of roughly an hour of base load in the unsafe direction; on the 23 h night it over-plans (the safe direction). The
test pins this so it stays visible and is expected to be replaced when a length-aware learner exists. How such nights should be
treated is **D9**. This is advisory arithmetic only; it does not touch the 25 Oct write plan, which is unchanged.

## 8. Decision register and blocker matrix

Status is computed by the tool from what the owner has supplied; `OPEN` means the tool will not fill it in.

| ID | Decision (owner) | Options the tool can express | Blocks (findings / later stages) | Status now |
|---|---|---|---|---|
| D1 | Which setting is **the** soft planning floor, and must precharge / Dump advice honour it or only display it | helper; Intelligence user reserve; a feature stop level; one new single setting | reserve consistency; S3 display, S5a, S6b | OPEN |
| D2 | The inverter's own protection level, and how it is supplied without a write | owner reads it from the inverter display; later an authorised read-only capture | `PHYSICAL_PROTECTION_UNKNOWN`; the `technical_min_soc_pct` placeholder | OPEN |
| D3 | The capacity authority | owner helper; learned from discharge; Ah x stated voltage | capacity findings; S3, S5a | OPEN |
| D4 | The capacity mismatch band | 8 % proposed; any other | `CAPACITY_MISMATCH` | OPEN (proposal only) |
| D5 | The canonical efficiency basis and unit | round-trip fraction (engine) or percent (helper) | efficiency findings | OPEN |
| D6 | Advisory freshness limits for house / PV / battery / grid power, inverter status, reserve helper | per-signal seconds (tighten only for defined ones) | `READING_AGE_UNKNOWN`; S2, S3 | OPEN |
| D7 | Which signals are required for the overnight, charge-target and export advisors | a list per advisor | `REQUIRED_SIGNAL_MISSING` | OPEN |
| D8 | The derived-load cut-over instant and the treatment of earlier history | exclude; replace; keep only non-exporting hours after a counter check | `HD1_CUTOVER_UNKNOWN`; S1 | OPEN |
| D9 | Clock-change night policy | exclude from learning; normalise per hour; plan as its own length | `NIGHT_LENGTH_DIFFERS`; S1 | OPEN |

**Smallest later owner-approved action:** record D2 (read the protection level from the inverter display and tell me) and D1
(which setting is the floor and whether features must honour it). Those two unblock the reserve checks without any data access or
software change. D4/D5/D9 are one-line answers. D3, D6, D7 and D8 need the owner's knowledge of the installation. Nothing needs a
live read until the later S1 data-quality step, which is a separate authorisation.

## 9. What this does not do

No runner, no Home Assistant contact, no statistics export, no sensor, no helper, no change to a default, no recommendation, no
control and no effect on the 25 October clock-change plan. It does not settle capacity, reserve or freshness; it makes the open
choices explicit and the consistency of whatever the owner decides checkable.
