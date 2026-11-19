# Intelligence PV persistence-skill gate (offline, switchable, OFF by default)

Status: source and tests only. **Nothing is installed, deployed or switched on by this change; enabling it anywhere is a separate
owner authorisation.** SHADOW engine, applies nothing, no new control path.

Code: `intelligence/pv.py` (`PvModel.skill_gate_verdict`, `forecast_day`). Tests: `intelligence/tests/test_intel_pv_skill_gate.py`
(synthetic data only, with 35 mutants of the implementation applied in memory).

## The problem it addresses

The engine's `pv_tomorrow` is the ECCO blend forecast for tomorrow multiplied by the median of the last 7 actual / forecast ratios,
with a band from walk-forward residuals. A scalar ratio can only fix a forecast that is wrong by a roughly constant factor. When the
raw sources carry **no rank skill** at a site (for example a shaded array whose daily output stays in a narrow band whatever the
forecast says, or an autumn in which the sources over-predict by a very different factor from one day to the next) the ratio cannot
fit, the corrected value is as wrong as the raw one, and the existing plausibility ceilings (`site_physical`, `history_max`,
`recent_max`) only catch values that are impossible, not values that are merely useless. In the 10-day acceptance run this produced a
forecast whose mean error was about twice that of plain persistence on the six days of the Q3 criterion.

## What the gate does

After the source choice and the unchanged plausibility guard, the corrected forecast is published only if it has recently **beaten
the model's own persistence estimate**:

1. For each of the 14 days before the target day (never the target day or later) take the corrected forecast the engine *would have
   published* that day (that day's raw forecast x the median ratio of the pairs *before* it, the engine's own clip and rules) and the
   persistence estimate computed from actuals *before* that day (`_persistence`: robust EWMA, alpha 0.3, k 3, window 28, the last 30 daily actuals).
2. Score both against that day's actual, on the days where all three exist and the forecast is a finite, non-negative number.
3. With at least **8** comparable days: keep the corrected forecast only if its mean absolute error is at most **0.9 x** the persistence
   mean absolute error. Otherwise publish persistence.
4. Fail closed: with fewer than 8 comparable days the comparison cannot be made, so persistence is published (it exists whenever a ratio
   exists, because both need at least 5 actual days). With fewer than 5 actual days the result is `INSUFFICIENT` exactly as before.

When the gate publishes persistence: `source` = `persistence`, `raw_kwh` and `ratio` are null, confidence 0.3 (`LOW`), the band is the
persistence band, `plausibility` is the ordinary block (a source rejected by the guard is still reported there), and `notes` carries
**one** plain line, either "PV forecast correction has not beaten persistence recently (mean error X vs Y kWh over N days); using persistence" or
"PV forecast correction could not be compared with persistence (N of 8 comparable days needed); using persistence". When the gate keeps the
corrected forecast the result is bit-identical to the ungated one (no extra note). The `to_dict()` keys, `PV_TOMORROW_SUMMARY_KEYS`, the
2048-byte summary limit, the date scoping of 'tomorrow' and `valid_until` are untouched; nothing outside `intelligence/pv.py` changed.

The constants (`SKILL_GATE_DAYS` 14, `SKILL_GATE_MIN_DAYS` 8, `SKILL_GATE_MARGIN` 0.9) were fixed before any replay result was looked
at and are not tuned to one. The gate is a fallback to a plain estimate, never a new forecast: it publishes only what `_persistence` already publishes.

## Switch and default

`PvModel(history, cfg, forecasts, skill_gate=None)`; `None` takes `PV_SKILL_GATE_DEFAULT`, which is **False** in this change. The
switch is a constructor argument and deliberately not a `SiteConfig` field: a new config field changes `config_hash()` of every configuration.

The default is OFF because enabling it moves one existing check, which was not edited: `intelligence/tests/test_intelligence_arithmetic.py`,
section "PV coverage feedback widens a band that stopped holding" ("a band that failed on recent days is widened and says so" and
"widening lowers confidence"). That check deliberately builds a forecast that is 4x too high for 14 days and expects the corrected path's
band to widen; with the gate on, that very forecast loses to persistence and persistence is published (no widening, which is the gate working
as designed). Every other suite that touches `intelligence/` is unchanged with the gate on and off (see the change record).
To turn it on in a test or an offline run pass `skill_gate=True`. Wiring it into the Home Assistant runtime (the `IntelligenceEngine` and
`run_cycle` build `PvModel` with the default) is NOT done here.

## Limits (read before relying on it)

- **n is small, one site, one autumn, and the gate was designed after seeing the failure** (hindsight risk). A replay of the real
  `PvModel` over the acceptance run and the weeks before it (kept offline, outside this repository) shows what it would have done on those
  days; it is not a proof for other days or sites and it does not re-grade the finished acceptance run or change any threshold.
- It will **publish persistence all autumn and winter** if the raw sources keep having no skill. That is the intended outcome, and also
  the limit of what it offers: persistence is a plain, honestly wide estimate, not a better forecast. It cannot produce skill the sources do not have.
- Persistence can be wrong by a lot after a regime change (a long dull spell followed by a bright day). The band reflects that, but the point estimate lags.
- The gate follows a regime change with a delay of about a week (the 14-day window and the 7-pair median must both turn over).
- The walk-forward corrected forecast of past days is `raw x ratio` and does not re-apply the plausibility ceilings of those days;
  a day the guard would have turned into persistence is scored as the corrected value. That can only make the gate stricter (fail-closed direction).
- 'Tomorrow' is evaluated while the current day is still in progress: today's actual counts only once at least 90 % of its hours exist
  (as for the ratio), so the decision can change between a morning and an evening run on the same day.
- One 0.9 margin and a 14-day window are one choice among many; the offline tests pin the behaviour around them, not their optimality.

## Optional second change: the recent-output envelope (separate commit, OFF by default)

The `recent_max` ceiling of the plausibility guard is 2.5 x the best observed day of the last 30 days. After a bright spell it is
loose enough to let an out-of-season corrected value through for weeks (a value several times the output of a dull day can sit just
under a ceiling set by the best days of the weeks before). With `PvModel(..., recent_envelope=True)` that one ceiling becomes **1.25 x the best actual of the last 14
days** (it needs at least 7 observed days in them, otherwise the legacy ceiling stays, so enabling it never removes a guard). A
corrected value above it is REJECTED exactly like any other ceiling breach: persistence, LOW confidence, the source, the values and the
limit named in `plausibility` and in the notes. The envelope is always tighter than the legacy ceiling (a 14-day best is never above
the 30-day best, and 1.25 < 2.5), so enabling it can only reject more, which is the safe direction for the advisor (less PV assumed,
more battery retained). Constants `PV_RECENT_ENVELOPE_DEFAULT` (False), `RECENT_ENVELOPE_DAYS` (14), `RECENT_ENVELOPE_HEADROOM` (1.25) and
`RECENT_ENVELOPE_MIN_OBS` (7); a constructor argument like the gate, not a `SiteConfig` field. Tests:
`intelligence/tests/test_intel_pv_recent_envelope.py` (synthetic data, 15 mutants applied in memory).

Limits: it is blunt. A genuinely bright day after two dull weeks is rejected and persistence is published instead (a deliberate
trade, see the plausibility paragraph in `ECCO_INTELLIGENCE_V1_ARCHITECTURE.md`); it addresses the over-forecast side only; it
changes nothing about a corrected value that is wrong but below the ceiling, which is the gate's job. It is independent of the gate
(either can be on without the other) and this commit can be dropped without touching the gate.
