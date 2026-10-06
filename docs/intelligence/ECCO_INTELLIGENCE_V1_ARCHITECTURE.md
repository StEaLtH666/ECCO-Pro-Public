# ECCO Intelligence V1 — architecture

Status: **design + working local prototype, SHADOW ONLY, not deployed, 2026-10-05.**
Code: `intelligence/` (pure Python 3.9+, stdlib only). Tests: `intelligence/tests/`. Evidence: `PROTOTYPE_RESULTS.md`,
`DATA_QUALITY_METHOD.md`. UI: `UI_DESIGN.md`, `home-assistant/prototypes/intelligence-v1/`.

## 1. Purpose and the one rule

Learn how this household uses energy, predict the next hours and days with honest uncertainty, recommend battery targets
and safe export, and **score every prediction against what happened**. `READ → LEARN → PREDICT → RECOMMEND → SCORE`.

**Authority.** The deterministic ESP safety/control layer stays authoritative. Intelligence has **no write path**: the
package imports no network, serial or process module and contains no control vocabulary (enforced by a static test); its
only outputs are a report dictionary, optional read-only HA display sensors, and its own SQLite scorecard file. The
effective minimum SOC is `max(user reserve, technical minimum)` (the user reserve defaults to 40 % and is chosen per installation); an HA reserve can raise
it but no code path lowers it below those two; every recommendation is computed against it (see §8).

## 2. Findings that shaped the design (all measured; details in PROTOTYPE_RESULTS.md)

1. **Memory beats structure.** On about a year of one real household's history (private, not shipped; aggregate findings only), an exponentially weighted mean with ~5-day memory beat a 30-day mean, a 14-day median, a same-weekday average and every blend of them, on every window (whole-day error about 9 % against roughly 10-15 % for the alternatives). Weekday explained under 8 % of residual variance (F below the 2.2 threshold). After the level is removed, daily residuals are white noise (lag-1 autocorrelation 0.05) and uncorrelated with PV. **There is no hidden structure for ML to find in the signals ECCO has; a gradient-boosted model would be curve-fitting noise.** Candidate new signals (temperature, occupancy) are an experiment, not a V1 assumption.
2. **Adaptive expert weighting did not help** (inverse-error blending was slightly *worse* than the fast expert alone on every window). So experts are *promoted only on clear evidence* (§5), and by default the fast expert stands alone.
3. **PV forecast providers must be corrected, not trusted.** A raw forecast source can be around ×2 too high in autumn/winter on a given array; a 7-day median actual/forecast ratio roughly halves its error. A source can also be impossibly wrong (a unit error, a stale value): see section 7a. The existing "best source" logic picks by raw error and never corrects.
4. **Counters, not power.** In the legacy integration's data instantaneous power sometimes flat-lined (a held value) for hours while the counters kept counting. Energy comes from counter deltas, hourly (counters have 0.1 kWh resolution and a ~10-minute publish interval).
5. **Hourly means are poor SOC points.** SOC outcomes are scored from point values where possible and the scorecard says where it cannot.

## 3. Pipeline

```
HA statistics (hourly) ──► history.py ──► canonical hourly table ──┐
  dongle ▸ legacy fill-in     counters→kWh, gaps, stalls, flags     │
                                                                    ▼
live inputs (SOC, powers, PV forecasts, tariff windows, sessions) ► engine.run(now) ──► report (JSON)
                                                                    │   usage.py   slot profiles, windows, intervals, nowcast
                                                                    │   pv.py      per-source ratio correction, hour shape, useful-PV time
                                                                    │   anomaly.py sustained load, base load, unusual day, shift, signatures
                                                                    │   battery.py hourly SOC simulation (unconstrained + floor-holding)
                                                                    │   advisor.py target SOC, safe export, session cover, reasons
                                                                    ▼
                          scorecard.py (SQLite) ◄── forecast_records ── later: resolve(history) → errors, metrics, insights
```

`engine.run` is deterministic (explicit `now`, no clock, no randomness; byte-identical output is tested, also under
input re-ordering). A `feature_hash` ties each stored forecast to exactly what produced it. `replay.py` reruns the engine
at any past instant using only history strictly before it (a test makes absurd future data and proves it changes nothing).

### 3.1 Canonical hourly table (`history.py`)
Per UTC hour: interval energies (load, pv, import, export, charge, discharge), hourly SOC mean/min/max, power means,
per-field quality flags and source. Counters become interval energy (gaps ≤ 6 h spread and flagged; resets/stalls
detected; unrecoverable hours stay missing — never invented). Sources merge per hour in priority order with a site profile
(`profiles/site_profile.example.json`, copied to a git-ignored `*.local.json` per site), mirroring the repo's canonical/legacy telemetry pattern. No entity id is in code.

### 3.2 Usage learning (`usage.py`)
The house's expected energy in any window is the **sum of its expected energy per local-hour slot**, and a slot's
expectation is a robust exponentially weighted mean (α 0.30, 60-day lookback) of that slot on recent days. EWMA is linear,
so *every* horizon — next hour, tonight (sunset→sunrise), cheap window, "to the next cheap window", whole day — is
consistent with every other and explainable as "the recency-weighted average of what this house used in those hours".
DST needs no special code (windows are local wall-clock mapped per date; a repeated hour is averaged).

* **Short-term persistence.** Hourly residuals have lag-1 autocorrelation 0.37; the next ~4 hours get a decaying additive adjustment (0.37·0.65^k × last residual). This is what lowers the next-hour error and why an abnormal load immediately raises the near-term forecast.
* **Weekday / weekend.** Measured, not assumed: `weekday_effect()` runs an F-test on level-removed residuals; a shrunk multiplicative weekday factor (clipped 0.7–1.4) is applied **only if** F > 2.2 *and* ≥ 8 % of variance is explained. Here it is not; on a synthetic house with a real weekend effect it switches on and the weekend forecast lands within 12 %.
* **Season.** Handled by recency (5-day memory tracks the season); the slow (α 0.08, 120-day) and 14-day-median experts exist as *baselines* and are promoted only if they beat the fast expert on ≥ 70 % of the last 28 scored days **and** by ≥ 10 % trimmed MAE (so one abnormal day can neither promote nor demote anything).
* **Similar days.** Selection of "similar" days (same weekday class, similar season) is used for *context* in explanations ("similar Sundays: median 31 kWh") rather than as a predictor, because the backtest shows same-weekday history is the worst predictor in the backtest.
* **Uncertainty.** Per window kind, the p10/p90 come from the model's own walk-forward relative residuals (last 90 days), never narrower than the Gaussian band from the residual spread; fewer than 20 residuals blend toward a deliberately wide prior; empirical coverage is reported (80 % nominal; measured 79–88 %).
* **Abnormal days do not corrupt the model.** Every observation is winsorised to median ± 5 robust σ (MAD) of the preceding 28 days before it updates any profile, so one abnormal day moves a slot by at most α·5σ (tested: a 9 kWh hour moves its slot by a fraction of what a plain EWMA would move it).

### 3.3 PV (`pv.py`)
Per forecast source: winsorised trailing **7-day median of actual/forecast**; the source with the lowest trailing *corrected*
MAE is used; p10/p90 from walk-forward residuals with **coverage feedback** (if the band failed on the last 21 days it is
widened up to ×1.5 and the confidence drops). Hourly shape = per-slot median of the last 14 days. Today's remainder is
re-anchored on how today is actually going (live ratio, weight ≤ 0.7). No forecast → persistence with a wide band and a
note. "Useful PV" = hourly PV ≥ 500 W (configurable), predicted as sunrise (NOAA algorithm, ~1 min) + learned offset
(median of the last 14 days, p10/p90 for the band).

### 3.4 Battery simulation and advice (`battery.py`, `advisor.py`)
Hourly SOC arithmetic with the configured capacity and √(round-trip) efficiency (validated: 3.2 SOC points per kWh of
load measured vs 3.33 physics; 2.5-hour-ahead SOC MAE 1.26 points on 9 nights). Inside a cheap-window charge step *below* the target the grid carries the house and charges the battery; *above* it the
simulation lets the battery cover the house **down to the target** (the slot SOC acting as a floor) and the grid carries the rest.
How the real inverter slot behaves above its SOC setting is **unverified** (`docs/DUMP_TO_GRID_V1.md` lists the effect of slot SOC on
discharge as unknown), so the cautious reading is used; an independent review showed the alternative ("hold where it was") would let a
low recommended target look safe when it is not (decision O-12). Steps split at the window edges (00:30/05:30), not at whole hours. Two tracks are run: *unconstrained*
(what SOC would do) and *floor-holding* (how much peak import it would take).

Four scenarios: median; **pessimistic** (load p90 and PV p10, each scaled by √½, ×1.5 when confidence is LOW, PV additionally
widened when its band recently failed — this equals the combined p90 only when the two uncertainties are equal; with PV at zero it is
nearer the 82nd percentile, so it is *not* called a p90); **hard** (both bands in full, used for export because an independent replay
sweep showed the √½ path alone let ~8 % of export advices dip under the comfort margin); optimistic (chart bands only). Outputs:

* **Overnight target** = smallest SOC at charge end whose *pessimistic* path stays ≥ floor + 5 % until the next cheap window, rounded up to 5 %; also the median-case target for transparency; `SHORTFALL` with expected peak-rate import when even 100 % cannot (never a smaller number); pre-window floor risk reported separately because no target can fix it. INSUFFICIENT history → 100 % ("retain the battery").
* **Safe export now** = largest energy whose removal keeps the **hard** path ≥ floor + 5 % until the cheap window opens (bisection); halved for an abnormal load and for LOW confidence; **fail-closed — withheld** for INSUFFICIENT history, stale learning data, SOC age unknown or > 15 min, inverter status unknown or unhealthy, an open charge window, or a Saving Session running or due within 3 h. Pinned by an analytic test (flat load, no PV: export = (SOC − floor − margin − discharge until the window) × capacity × η). Economics: export rate − cheap rate/round-trip.
* **Saving Session cover**: can the battery carry the session on the pessimistic path, and the minimum SOC at session start.
* **Explanations**: structured reasons (code + text with numbers), uncertainty factors, assumptions.

### 3.5 Anomalies (`anomaly.py`) — descriptive, never accusatory
Sustained load (≥ 3 consecutive hours with robust z ≥ 2.5 *and* ≥ 0.4 kW above expectation; 2 h = WATCH), unusually high overnight base load (01–05 h median vs 28 nights), unusual day (vs expectation, with similar-weekday context), behaviour shift (14 vs previous 42 days, standard-error guarded), sustained low load. **Recurring load signatures** need ≥ 1-minute data: 1-minute medians, paired step-up/step-down events, binned by amplitude and duration, ≥ 4 events on ≥ 3 days → "Recurring load signature A: ~1.7 kW for <8 min, seen on 9 days, usually around 17:00". **No appliance is ever named** (`appliance: null`; a name needs independent evidence the caller supplies).

## 4. Learning-from-error and the scorecard (`scorecard.py`)

SQLite, its own file (never the HA recorder DB). Tables: `model_runs` (issued time, model version, config hash, feature hash,
feature snapshot, status, confidence, mode), `forecasts` (kind, issued/horizon start/end, lead minutes, target weekday/hour,
predicted p50, band low/high, nominal coverage, confidence, model/feature id, explanation JSON, status
PENDING/SCORED/VOID_NO_DATA/VOID_SCENARIO, **actual, error = actual − predicted, abs_error, pct_error, in_band**, scored time),
`recommendations` (shadow only; outcome column for the future ledger), `schema_meta`. Recording is idempotent; nothing is scored before
horizon end + 2 h; a plan-conditional SOC forecast whose plan was not what happened is `VOID_SCENARIO` with a reason (a
control decision is not a forecast error). `metrics()` gives MAE, RMSE, bias, band coverage, MAPE, groupable by weekday/hour.
`insights()` produces sentences like *"I have been underestimating Wednesday mornings by 1.2 kWh (n=8)"* but only past a
multiple-comparison-corrected t-test (≈ 50 weekday × window comparisons; the 2-σ rule would raise a false finding about every
other week) and a 0.3 kWh floor. A private-data campaign found none; an injected 1.2 kWh Wednesday bias is found (synthetic test).
Live residuals progressively replace walk-forward residuals as the interval source.

Forecast kinds recorded: `load_kwh:{next_1h,cheap_window,morning,overnight,to_useful_pv(_from_now),to_next_cheap,day}`,
`pv_kwh:day` (future days only), `soc_pct:pre_window_hour`. INSUFFICIENT forecasts are not recorded.

## 5. Weights, memory and robustness — one place

| Mechanism | Rule | Why |
|---|---|---|
| Recency | EWMA α 0.30 (≈ 5 days), per slot | won the backtest on every window |
| Outlier day | winsorise to median ± 5 robust σ before any update (k=3 cost 4–15 % MAE on heavy-tailed evenings) | bounded influence: ≤ α·5σ |
| Expert promotion | beat fast on ≥ 70 % of 28 days **and** ≥ 10 % trimmed MAE → weight ≤ 0.35 | blending lost the backtest; evidence-gated, one day cannot flip it |
| Weekday | F-test material → shrunk factor | measured, currently off |
| Interval | walk-forward relative residuals, p10/p90, coverage-checked | immediately calibrated, no waiting |
| PV ratio | 7-day winsorised median, coverage feedback widening | tracks the seasonal drift |
| Confidence | history depth × interval calibration × residual count; PV adds band-coverage penalty; data age; abnormal-load factor | LOW/INSUFFICIENT widens or withholds advice |

## 6. Deployment shape (proposal, nothing deployed)

1. **Runner**: a small read-only job on the HA host (candidates: Python in the existing SSH add-on on a schedule, or a dedicated add-on; HA-core `command_line` is possible because the package is stdlib-only). Hourly + 21:30 run: export statistics (read-only SQLite), read live states (HA REST, the existing `ecco-snapshot.ps1` pattern), `engine.run`, `scorecard.record_run/resolve`.
2. **Publisher**: `render_ha_prototype.contract` shows the exact mapping to five read-only sensors (`sensor.ecco_intelligence_{status,predicted,recommended,trajectory,accuracy}`); live they would be written through the HA states API with `mode=SHADOW` and `applies_nothing=true`.
3. **UI**: card/view per `UI_DESIGN.md`; Apply control permanently disabled in V1.
4. **Failure behaviour**: if the runner stops, the sensors go stale (the card shows DATA_STALE and withholds advice); nothing else in ECCO depends on it.

## 7. Safety/authority statement (what is guaranteed and how)

* No write path: static test forbids network/serial/process imports and control vocabulary in `intelligence/*.py`.
* Persisted mode is SHADOW; every report says `applies_nothing: true`; the dashboard prototype contains no service call, no control entity, only `none`/`more-info` taps, and a *disabled* Apply button (tested).
* Effective minimum SOC: `effective_min_soc = max(user_reserve_soc_pct, technical_min_soc_pct)`, raised (never lowered) by a finite HA reserve; the user reserve defaults to 40. A 40-scenario seeded property sweep (default reserve) and a 63-case sweep over user reserves 0 / 20 / 30 / 40 / 50 / 70 %, technical minimums 10 / 25 / 30 % and HA reserve 15 / 60 / none (`test_intelligence_reserve.py`) assert target ∈ [minimum + margin, 100], "feasible ⇒ pessimistic path respects the minimum" and export never breaching the minimum at the instant of advice. **Honest caveat:** "feasible ⇒ respects the floor" is true by construction; what the engine cannot promise is that the *real* house stays above the floor (its pessimism is a judgement, the simulation is hourly, and the slot behaviour is unverified). The realised-breach rate of advised exports is therefore a scorecard metric (PROTOTYPE_RESULTS §7).
* Mutation checks: two rounds. Round 1 (9 defects, by me) let 5 survive; an independent reviewer then ran 41 mutations and found 22 surviving (the suite pinned directions, not arithmetic: export maths, discharge efficiency, margin, window gates, session guard, t-table, weekday key, PV widening, interval floor, anomaly persistence, useful-PV threshold, authority scan). `test_intelligence_arithmetic.py` was added to pin those; re-running the reviewer's survivors (17 of them) now fails the suite for every one. Remaining known equivalent mutant: ignoring the floor in the target scan is neutralised by a second `max(…, desired)` guard.

## 7a. Final safety guards (added in the pre-review cleanup)

* **PV forecast plausibility** (`pv.py`, `SiteConfig.pv_*`). Each forecast source is checked against up to three ceilings:
  the array's physical limit (`pv_array_kwp x pv_max_kwh_per_kwp_day`, only when the site size is configured), 1.25x the best
  day ever observed, and 2.5x the best day of the last 30 observed (the recent ceiling is what catches an out-of-season value
  that the all-time maximum would let through). A source above its ceiling is REJECTED: it is not used, the report's
  `pv[day].plausibility` lists the source, the raw and corrected values and the limit that was broken, the day falls back to
  persistence at LOW confidence, overall confidence is capped at LOW (`confidence.downgrade_reasons`), and the recommendation
  carries a `PV_FORECAST_REJECTED` reason and a HIGH uncertainty entry. Rejecting is the safe direction for the advisor.
  Non-finite, negative, string or boolean forecast values are ignored the same way. The rule is deliberately simple and
  explainable; it does not try to model weather.
* **Absence / return-day protection** (`usage.baseline_guard`, `Planner`). The fast profile has a ~5-day memory, so after an
  empty week it under-forecasts the first normal day back. The long baseline is, per hour, the higher of the 30-day median and
  the slow expert. The guard is ACTIVE when a sustained abnormal load, a behaviour shift or a sustained low load is flagged, or
  the fast 24 h total is below 80 % of the baseline's. When active, only the pessimistic and hard scenario paths use
  `max(fast, baseline)`; the median and optimistic paths and every median forecast are unchanged. The report carries
  `load_baseline_guard` (triggers, both daily totals, the uplift), the advice a `LOAD_BASELINE_GUARD` reason, and overall
  confidence is held below HIGH while it is material. With fewer than 14 complete days the guard reports itself unavailable.
* **Battery reserve.** 40 % is the DEFAULT user reserve (`user_reserve_soc_pct = 40`), not an immutable floor: an installation chooses its own
  reserve. A separate `technical_min_soc_pct` (default 10, a site-specific placeholder and NOT a universal battery-safety minimum: set it to the
  minimum permitted by your inverter / battery configuration, for example the inverter's battery shutdown SOC) is the hardware constraint
  the preference can never go below, and it does not encode the 40 % preference. `SiteConfig.effective_reserve()` returns the maximum of the two and a finite
  HA reserve (capped at 100) as plain data: configured reserve, technical minimum, effective minimum, which of them was binding, and a plain-language
  `override_reason` when the technical minimum (or an HA reserve) overrides what the user asked for. The advisor emits it as `recommended.reserve`
  (with the legacy `floor_pct` = the effective minimum) and as a `TECHNICAL_MIN_OVERRIDES_USER_RESERVE` / `HA_RESERVE_RAISES_USER_RESERVE` reason.
  `SiteConfig` refuses, at construction, a non-finite, boolean or out-of-range (0-100) reserve or technical minimum, a `max_soc_pct` at or below the
  effective minimum, a technical minimum at or above `max_soc_pct`, a reserve that leaves no room for the safety margin below `max_soc_pct`, a negative or
  non-finite margin and nonsense advisor constants, so no configuration can put a recommended target at or below the effective minimum. The same
  `EffectiveReserve` value is what dynamic charge, Dump-to-Grid, Saving Session optimisation, `intelligence_bridge` and modular battery control should
  consume later; none of those is implemented here, and nothing in this package applies it.
* **Input hardening.** Non-finite or negative PV forecasts, readings (`load_w`, `pv_w`, `pv_actual_so_far_kwh`), HA reserve and
  SOC age are dropped or treated as stale (SOC age NaN, infinite, negative, boolean or non-numeric is stale: export withheld,
  status DATA_STALE); reports stay valid JSON.
* **Constants that are configuration, not code**: the grid-charge cap (`max_grid_charge_kw`, 8 as an example value: set your inverter's grid-charge limit), the target step
  (`target_step_pct`, 5) and the pessimistic band share (`band_kappa`, sqrt(1/2)) live in `SiteConfig` and are part of the config hash.

## 8. Known limitations (honest list)

* Hourly resolution: sub-hour spikes are averaged; the 00:30/05:30 boundaries are apportioned.
* The plausibility ceilings are blunt: a genuinely bright day after a dull month can be rejected (the advisor then plans on persistence, which retains more battery). The long load baseline is a 30-day median, so a holiday longer than about two weeks erodes it; the slow expert limits that only partly.
* No weather/temperature; the unexplained day-to-day variance (roughly 10 % of daily use) is a floor for any model using these signals.
* PV day-ahead error remains the weakest link (autumn error around 20 % of the day total, band coverage below the 80 % nominal); the advisor leans on it conservatively; in autumn/winter this drives the recommendation to 100 % (which is the usual behaviour today, so V1's value there is the *explanation and the cost of being wrong*; its value shows in spring/summer when the target can be 45–70 %).
* Capacity/efficiency uncertainty ±8 %; pessimism level (√½ rule) and 5 % margin are judgement calls (O-3).
* Useful-PV time resolution ≈ 30 min; start threshold 500 W is a definition (O-9).
* **Predicted SOC is plan-conditional**: every SOC in the report assumes the *recommended* target is followed (it says so: `assumes_recommended_target_followed`), whereas the inverter's configured TOU slot target may differ; the dashboard labels the chart accordingly.
* `empirical_coverage` in a forecast is **in-sample** (the band is built from the same residuals), so it sits near 80 % by construction and is not used in the confidence score; only the scorecard / campaign coverage is out-of-sample.
* Constants (α 0.30, winsor k, 7-day PV window, nowcast ρ) were chosen on the data they are scored on, and the replay's "tomorrow" PV uses the target day's pre-dawn issue value, which is better-informed than the evening value a live run has (the live PV band will be wider). "Ensemble worse than fast" rests on MAE gaps of 0.02–0.16 kWh without a paired test; the conclusion that matters is "no *better*".
* "Cheap window" times come from configuration unless live Octopus rate events are supplied; the engine says which it used.
* About a year of history is a *single* seasonal cycle: no year-on-year seasonality is learned.

## 9. Open design decisions (assumptions needing a yes/no)

| # | Decision | Recommendation |
|---|---|---|
| O-1 | The chosen reserve (default 40 %) may not be in HA (the reserve helper and inverter shutdown SOC can be set lower). Align `input_number.ecco_minimum_reserve_soc` with it, or make that helper the source of the user reserve? | Yes, as a display/consistency step; Intelligence already enforces its own configured reserve and only ever raises it for a higher HA helper. |
| O-2 | Where does the runner live (SSH add-on cron vs dedicated add-on vs HA-core command_line)? | Dedicated tiny add-on or scheduled script; decide before building. |
| O-3 | Pessimism: √½ rule at p90 and 5 % margin — keep, or choose more/less cautious? | Keep for the 4-week shadow; tune on scored data. |
| O-4 | Saving Sessions: reward is baseline-relative and the integration reports `octopoints_per_kwh` — confirm units/£ and whether export counts. V1 only checks battery *cover*. | Defer value modelling; confirm semantics first. |
| O-5 | Keep legacy `<legacy>_*` statistics until Influx depth is verified; also export Solcast sensors to Influx (currently excluded by the include list). | Yes to both. |
| O-6 | Allow a weather/temperature feature experiment? | Yes, as a later, measured experiment. |
| O-7 | Dashboard: replace the JS-only *Intelligence* view content, or add a view? | Add alongside, retire JS recommendation later. |
| O-8 | Scorecard file location/retention (own SQLite under `/config/ecco/intelligence/`, no purge for 1 year). | Yes. |
| O-9 | "Useful PV" = 500 W hourly mean — acceptable? | Yes for V1. |
| O-10 | Lat/lon from HA core config at runtime (not stored in repo). | Yes. |
| O-12 | **Verify how the inverter's TOU slot behaves when SOC is above the slot's SOC setting** (does it hold, or let the battery discharge down to the setting?). Until verified, never present a target below the current SOC as safe; the engine already assumes the cautious reading. | **Verify read-only first** (observe a night; no writes). |
| O-11 | Cheap windows from Octopus rate events (`…_current/next_day_rates`) rather than configuration. | Yes; when tomorrow's rates are not yet published, fall back and say so. |

## 10. Recommended implementation order

1. Review/merge the package + tests + docs as a **no-behaviour-change PR** (adds `intelligence/**` tests to CI selection — see `docs/ci/`).
2. Read-only runner + statistics export on the HA host; scorecard file; **no sensors yet**; run 2 weeks silently.
3. Publish the five shadow sensors; add the prototype view; keep Apply disabled.
4. Gate review at ≥ 28 scored days: whole-day MAE ≤ 10 %, band coverage 70–90 % per kind, PV coverage ≥ 65 %, zero recommendations violating the floor, no stale/unscored backlog.
5. Experiments, each scored against the incumbent: weather feature; 1-minute data for signatures (Influx); PV intraday re-anchoring beyond the ratio.
6. Only then, separately and with its own review: recommendation ledger (feature board R3) and any "apply" path **through the existing interlocked Energy Actions**, never directly.
