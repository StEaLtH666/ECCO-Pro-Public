# ECCO Intelligence V1.1 foundation (SHADOW)

Status: **foundation, offline only, synthetic data only.** These advisors compute and explain; nothing consumes them yet.
They have no write path, they are not wired into the V1 engine's report (whose output is unchanged), and no Home
Assistant entity publishes them. Model version string: `intel-v1.1.0-foundation-shadow`. The V1 engine keeps `intel-v1.0.0-shadow`.

Architecture context (state model, freshness, capability, authority, the bridge): [`docs/architecture/MODULAR_ARCHITECTURE.md`](../architecture/MODULAR_ARCHITECTURE.md).
V1 design: [`ECCO_INTELLIGENCE_V1_ARCHITECTURE.md`](ECCO_INTELLIGENCE_V1_ARCHITECTURE.md).

## 1. One answer format (`intelligence/explain.py`)

Every V1.1 advisor returns an `Advice`:

| Field | Meaning |
|---|---|
| `status` | `OK`; `BLOCKED` (a required input is stale, unknown or invalid, or a precondition fails); `INSUFFICIENT_DATA` (at most a conservative fallback, flagged) |
| `recommendation` | the numbers, immutable and strict JSON; always `None` when `BLOCKED` |
| `confidence` | score = product of named factors, each with a sentence; label on the V1 scale (HIGH >= 0.75, MEDIUM >= 0.5, LOW >= 0.25) |
| `reasons` | code + plain-language text with the numbers |
| `assumptions` | what the answer rests on |
| `blocking` | why it is withheld (only when `BLOCKED`) |
| `inputs` | each input's age against its limit: fresh / stale / unknown / not_required |
| `mode`, `applies_nothing` | always `SHADOW` and `true`: construction fails otherwise |

An `OK` advice cannot be built on a required input that is stale or of unknown age.

## 2. Overnight demand learning (`intelligence/overnight.py`)

The caller defines one recurring overnight period (for example the end of the cheap window to the next one) and supplies
one total per past night. `nightly_totals()` extracts these from the canonical hourly History; a night with less than
80 % coverage is `None`, never invented.

- **Estimate:** a recency-weighted mean (alpha 0.30, the V1 fast expert's) over the last 28 nights, each night clipped to
  5 robust sigmas of the nights before it, so one odd night moves the estimate by at most alpha x 5 sigma. The planning
  value is the 90th percentile from walk-forward relative errors, never narrower than a Gaussian band (and from a
  deliberately wide prior until 10 errors exist).
- **Learned versus limits:** the learner knows nothing about the reserve or the battery. `charge_target.py` combines them.
- **Weak history:** with fewer than 7 clean nights the result is `INSUFFICIENT_DATA`. With a configured default
  (`prior_kwh`) it returns a flagged conservative fallback, planning at least the default. Without one it returns no
  number. A default is blended in with weight n / (n + 7) until 28 nights exist.
- **Confidence factors:** history depth, band evidence, night-to-night dispersion, regime, data age and outlier share.
- **Hygiene:** nights on or after the target night are ignored (no leakage). Duplicated or invalid totals are ignored
  and counted. Caller-declared exclusions such as `DECLARED_AWAY` are a user's statement, not an inference, and are
  never learned from.

**Return from away / abnormal demand.** The last 3 nights are compared with the older nights in the window:

| Regime | Rule | Effect |
|---|---|---|
| `LOW_RECENT` | recent median at least 25 % below and 2 robust sigmas under the baseline (an empty house) | planning value raised to at least the baseline's; expected value untouched; confidence x0.7 |
| `HIGH_RECENT` | the same, above | planning at least the recent level; confidence x0.8 |
| `INSUFFICIENT_RECENT` | fewer than 2 of the last 3 nights have data | planning at least the baseline's; confidence x0.8 |
| `UNKNOWN` | fewer than 5 older nights | stated; confidence x0.9 |

This mirrors the V1 baseline guard (`usage.baseline_guard`): only the cautious value moves, never the expected one.

## 3. Charge-target advice (`intelligence/charge_target.py`)

```
target = ceil_to_step( max(effective reserve + margin, desired morning SOC) + planned demand / eta / capacity )
```

- **Inputs:**
  - effective reserve = `SiteConfig.effective_reserve()`: user reserve (default 40 %), never below the technical
    minimum, and raised but never lowered by a run-time HA reserve;
  - margin = `soc_safety_margin_pct` (5);
  - planned demand = the learner's planning value minus any PV credit the caller vouches for at MEDIUM or higher;
  - charge window and current SOC, used only for what the window can reach and the grid energy needed.
- **Output:**
  - the target and its unrounded value;
  - the binding constraint: `RESERVE`, `DESIRED_MORNING_SOC`, `DEMAND`, `MAX_SOC` (a shortfall: even full may not cover
    the period) or `CHARGE_WINDOW` (the window cannot reach it from the current SOC);
  - grid energy, confidence, assumptions;
  - given the previous advice, `changed_from_previous`: each input that moved, with its effect in points, applied in a
    fixed order.
- **Fail-safe:** INSUFFICIENT demand evidence gives the maximum SOC ("retain the battery"), as V1 does. A stale or
  unknown SOC withholds only the grid energy and the reach check, not the target, which does not depend on the current SOC.
- **Difference from V1:** this is a closed-form budget, so it does not model when, inside the period, demand and PV
  happen. The V1 shadow report keeps its hourly simulated target. V1.1 is the explainable foundation a future
  dynamic-charging feature would start from.

## 4. Saving Session / export-event advice (`intelligence/events.py`)

For one event, on planning demand before, during and after it:

- whether the battery can carry the house through the event without import while keeping what is needed after it above
  the reserve plus margin;
- how much it could export on top, limited by the discharge limit (battery side) and the export limit (grid side) when
  both are known; the binding constraint is `ENERGY_ABOVE_RESERVE` or `POWER_LIMIT`;
- no reward or price model (open decision O-4): energy only.

**BLOCKED** when the SOC is stale or unknown (15-minute advisory limit), the inverter status is not known healthy, a
demand figure is missing or rests on insufficient history, or the event is invalid or over. Unknown power limits
withhold only the export amount.

## 5. Dynamic Dump-to-Grid advice (`intelligence/dump_advice.py`)

```
stop = ceil( effective reserve + margin + planned demand until the next refill / eta / capacity ),  within the feature's 10-90 %
export = (SOC - stop) x capacity x eta,  limited by min(discharge x eta, export limit) x duration when supplied
```

The answer reports `stop_set_by` (`RESERVE_AND_DEMAND`, `FEATURE_MINIMUM` or `ABOVE_FEATURE_RANGE`) and, separately,
`export_limited_by` (`STOP_LEVEL` or `POWER_LIMIT`).

**BLOCKED** when:

- the SOC is stale or unknown (the controller's own START gate separately requires a reading under 90 s old);
- the inverter status is not known healthy, or the charging window is open or its state unknown;
- a Saving Session is running or due within 3 hours (the V1 rule);
- the demand figure is unknown or rests on insufficient history;
- the refill time is not in the future.

Dump-to-Grid in 0.9.0 does not read this. It still stops at the user's chosen level (`SAFETY.md` section 9).

## 6. Tests (synthetic data only, fictional year 2030)

| Suite | Pins |
|---|---|
| `test_intelligence_v11_explain.py` | Advice invariants, fail-closed input ages, confidence arithmetic |
| `test_intelligence_v11_overnight.py` | level tracking, confidence growing with history, bounded outlier influence, fallback / refusal, leakage, hygiene, the four regimes |
| `test_intelligence_v11_charge_target.py` | the budget analytically; 144 reserve / technical-minimum / HA-reserve / demand combinations; binding constraints; PV credit rule; retain-battery fallback; stale-SOC behaviour; change attribution |
| `test_intelligence_v11_export_advice.py` | both budgets analytically; 108 + 96 property combinations (never below reserve + margin + kept demand; stop within 10-90 %); every blocking condition |
| `test_intelligence_v11_migration.py` | the migrated input path against the old implementation (section 8 of the architecture document) |
| `ecco_core/tests/test_core_bridge.py` | end to end: snapshot -> engine -> SHADOW record; the inverter status withheld by default |

## 7. Not done, and what would be needed

- **Wiring into the V1 report and the display sensors.** This changes the report, so the examples and the mock package
  must be regenerated.
- **A runner and publication on the Home Assistant host.** Open decision O-2.
- **Owner-configured inputs:** the overnight period, the default overnight demand (`prior_kwh`), and site freshness
  limits (the inverter status is unresolved by default).
- **Scoring the V1.1 answers in the scorecard** before any of them is trusted.
- **Any "apply" step.** It would need its own design, review and hardware proof, and would go through the existing
  interlocked Energy Actions, never directly from Intelligence.
