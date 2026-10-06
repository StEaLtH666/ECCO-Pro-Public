# Prototype results and evaluation plan

**All numbers in this file come from a seeded SYNTHETIC household** (`intelligence/synthetic.py`, fictional year 2030) and are
reproducible with `python intelligence/tools/make_examples.py`. They show that the machinery works and how its output reads;
they are **not** evidence about any real home. The engine was also run privately against one real household's history to choose
its design (section 2, aggregate and undated); that data is not part of this repository and no real, dated consumption or
occupancy history is shipped here.

## 1. Shadow campaign on the synthetic household (scorecard)

Nightly 21:30 runs (60 nights), each using only the history known then, recorded, then scored against later history
(`scorecard.resolve`). Percentages are mean absolute percentage errors.

| Forecast kind | n | MAE | Bias (actual - predicted) | Band coverage (nominal 80 %) |
|---|---|---|---|---|
| Next hour | 60 | 0.09 kWh (8 %) | +0.00 | 87 % |
| Cheap window | 59 | 0.44 kWh (10 %) | +0.04 | 76 % |
| Morning | 59 | 0.45 kWh (10 %) | +0.05 | 78 % |
| Overnight (sunset to sunrise) | 59 | 0.63 kWh (8 %) | +0.06 | 80 % |
| Whole day | 60 | 2.89 kWh (10 %) | +0.28 | 80 % |
| To next cheap window | 59 | 2.48 kWh (9 %) | +0.31 | 76 % |
| PV day ahead | 59 | 3.15 kWh (11 %) | -1.38 | 81 % |

Because the synthetic household is built from a profile plus seeded noise, its errors are essentially the injected noise and
are NOT a prediction of real accuracy. What the table does show is that the scoring pipeline (record, resolve, aggregate) is
sound and that band coverage and bias are reported honestly.

## 2. Design evidence from private data (aggregate, undated)

Choices in the engine were made on about a year of one real household's hourly history, every forecast using only history
strictly before its target. Findings only, no series:

* A ~5-day exponentially weighted mean per hour-of-day slot beat a 30-day mean, a 14-day median, a same-weekday average and
  every blend or inverse-error ensemble tried, on every window; whole-day error was around 9 % of use, evening about 16 %.
* Weekday explained under 8 % of residual variance and was not material, so it is measured (`weekday_effect()`), not used.
* Winsorising each observation (median +- k robust sigma) trades a little accuracy for robustness: k = 3 cost accuracy on the
  heavy-tailed evening load, k = 5 keeps most of the protection and is the shipped default (`SiteConfig.winsor_k`).
* Raw PV forecast sources were biased high in autumn and winter (up to about a factor of two for one source on that array)
  and closer to unbiased in midsummer; a trailing 7-day median actual/forecast ratio roughly halved the error and beat 5, 10,
  14 and 21 days in every period tried. The corrected band still under-covered during a seasonal decline (about two thirds
  against 80 % nominal); coverage feedback widens it and lowers confidence, and the shortfall is reported rather than hidden.
* Short-horizon hourly residuals are autocorrelated (about 0.37 at lag 1, fading by 6 h), which is what the next-hour
  persistence adjustment uses.

These claims were chosen on the data they were scored on; treat them as design rationale, not as a guarantee.

## 3. Example recommendations (synthetic household, minimum reserve 40 % (the default), comfort 45 %)

"Feasible" = the pessimistic path stays at or above 45 % until the next cheap window at the recommended target. "Import
after" is the peak-rate import that path would need after the charge window even at the maximum target; "import before" is the
shortfall before the window opens (nothing the target can change). Targets in brackets are the median / pessimistic-case
targets. Files: `docs/intelligence/examples/`.

| Scenario | Status / confidence | Overnight target | Feasible? | Import after / before (pessimistic) | Safe export |
|---|---|---|---|---|---|
| Normal evening, SOC 62 % | learning normally / HIGH | **100 %** (100 / 100) | no | 4.98 / 0.0 kWh | 1.7 kWh |
| Afternoon, PV far below forecast, SOC 78 % | pv underperforming / HIGH | **100 %** (100 / 100) | no | 4.98 / 5.26 kWh | 0.0 kWh |
| Late afternoon, SOC 75 % | learning normally / HIGH | **100 %** (100 / 100) | no | 4.24 / 0.0 kWh | 0.0 kWh |
| Summer evening, SOC 85 % | learning normally / HIGH | **70 %** (45 / 69) | yes | 0.0 / 0.0 kWh | 9.0 kWh |
| Cold start (4 days of history), SOC 62 % | insufficient history / INSUFFICIENT | **100 %** (100 / 100) | no | n/a / n/a | withheld |
| Morning with live-style inputs, SOC 88 % | learning normally / HIGH | **60 %** (55 / 56) | yes | 0.0 / 5.81 kWh | 0.0 kWh |

The honest shape of V1: when solar is scarce it will often say "charge to 100 %" (the conservative behaviour), now with a reason,
a stated cost of being wrong and an uncertainty; when solar is plentiful it licenses lower targets and export. Sentences it
produces: *"At current usage the battery is predicted to reach 40 % at HH:MM"*, *"Expected demand before useful PV is X kWh"*,
*"Recommended overnight target: N %"*, *"PV is underperforming versus forecast; retain more battery"*, *"Safe export available:
about X kWh while preserving the configured reserve"*, *"House demand is abnormal ..."*.

## 4. Safety-guard regression tests

`intelligence/tests/test_intelligence_safety_guards.py` (synthetic, seeded): an impossible (10x) PV forecast is rejected and
cannot raise confidence above LOW or lower the target; the recent-output ceiling catches what the all-time maximum lets
through; NaN / infinite / negative / string / boolean inputs are ignored; a week-away history activates the baseline guard,
raises the pessimistic target and lowers export while leaving every median forecast unchanged; behaviour-shift and
abnormal-load triggers; the effective minimum SOC (user reserve, default 40 %, vs a separate technical minimum) cannot be lowered by config or input; configuration constants are validated;
cold start fails closed; and the report is byte-identical across processes and interpreter hash seeds. Twelve source mutations
(removing each guard, ceiling and confidence cap) were each caught.

## 5. Evaluation plan once shadow-running live

1. Score every forecast kind nightly; publish the 7-day table (MAE, bias, band coverage vs nominal) and the 28-day trend.
2. Gate: at least 28 scored days; whole-day MAE at or below 10 % of mean; every band's out-of-sample coverage in 70-90 % (PV at
   least 65 %); at least 95 % of runs complete; **zero recommendations flagged `feasible_on_pessimistic_path = true` whose
   independently re-simulated pessimistic path dips below floor + margin** (a hard invariant, tested). Runs that are
   infeasible (SHORTFALL) are not violations: they are counted and reported separately and the gate for them is that the
   shortfall is stated, with its kWh, and the recommendation is the maximum. The realised-breach rate is also tracked.
3. Compare against the incumbents on the same nights: Battery Outlook (SOC at charge start), the HA PV scoreboard and "always
   charge to 100 %". Report what the recommended target would have saved or risked in kWh and pence using the real tariff, as
   hindsight, never as a promise.
4. Every model change must beat the incumbent in a walk-forward backtest on the same data before shipping.
5. Track insights and anomalies as precision problems: the owner reviews each flagged event (useful / noise) to set thresholds.

## 6. What the prototype does not prove

It has never run against a live, unlabelled day; the PV forecasts for tomorrow in the replays come from a pre-dawn issue value
rather than the evening snapshot a live runner would use (slightly optimistic for tomorrow); a year of data holds one seasonal
cycle; and the economic value of any recommendation is not measured.
