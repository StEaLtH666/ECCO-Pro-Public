# Intelligence PV persistence-skill gate (offline, switchable, OFF by default)

Status: source and tests only. **Nothing is installed, deployed or switched on by this change; enabling it anywhere is a separate
owner authorisation.** SHADOW engine, applies nothing, no new control path.

Code: `intelligence/pv.py` (`PvModel.skill_gate_verdict`, `forecast_day`, and for the planning fix `PvForecast.planning_band`,
`conservative_band`, `prefers_ungated`), `intelligence/engine.py`, `intelligence/shadow_cycle.py`. Tests: `intelligence/tests/test_intel_pv_skill_gate.py`
(synthetic data only, with 35 mutants of the implementation applied in memory) and, for the planning fix,
`intelligence/tests/test_intel_pv_gate_planning.py` with the frozen world generators `intelligence/tests/_pv_worlds.py` and
`intelligence/tests/_pv_worlds2.py` (synthetic data only, 57 mutants applied in memory; a full run takes about nine minutes, nearly all of it
the property test over 1,200 worlds).

**Status of the planning fix (20 Nov 2026, round 2): complete. With the gate ON the recommended charge target is never below the gate-OFF
engine's, by construction on the fallback path and verified on unseen worlds. Nothing is enabled or deployed; enabling remains blocked.** See
"The planning fix" below and "Before it is enabled anywhere".

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

## The planning fix: the gate must not lower a charge target (20 Nov 2026, two rounds)

**The defect.** After a fallback, the published persistence value can be HIGHER than the corrected one (a bright spell followed by a
dull day) and its p10 far above a widened corrected p10. The engine sized the overnight target on that published value, so with the
gate ON the target could fall below what the ungated engine recommends: in a synthetic whole-engine world (a source with no skill, a
bright spell) from 80 to 70 percent, the unsafe direction (less battery retained). A fallback also added no LOW cap and no reason code,
unlike a rejected forecast. Round 1 fixed most of it (planning on the per-quantile lower of the two values); a validation on fresh
worlds then lowered the recommended target once more (80 to 75 in 1 of 300) and the unrounded pessimistic-case target in 5 of 300.
That is why round 2 exists: the owner's requirement is a guarantee, not a rate.

**What is PUBLISHED does not change** (persistence, LOW, 0.3, the scoreable `pv_kwh:day` record, `to_dict()`,
`PV_TOMORROW_SUMMARY_KEYS`, the 2048-byte summary, the date scoping, `valid_until`, the reason codes of the `pv_tomorrow` item). What
PLANNING sizes energy actions on does. Two layers, independent of each other:

**Layer 1: the planning band keeps the ungated spread (`conservative_band`).**
- `PvForecast.planning_band`: p50 and p90 are the LOWER of the persistence value the gate published and the value the UNGATED
  corrected path would have produced for the same inputs (after the unchanged plausibility guard); p10 is that lower value moved down
  further by as much as the median was lowered below the corrected median, floored at zero. So the band keeps at least the ungated
  spread below the median. Why it matters: the Planner's pessimistic PV for a day is `p50 - k (p50 - p10)`, floored at zero, with
  `k = band_kappa x 1.5 (LOW widening) x band inflation`, which is above 1 in the usual LOW case (0.71 x 1.5 = 1.06, up to 3.4), and
  then DEcreases when p50 rises. A plain per-quantile minimum (round 1) lowers the median but may leave p10 where it was, and the
  pessimistic PV can then be HIGHER than the ungated one.
- Proof (also in the docstring). With p50' <= p50c and spread s' = p50' - p10' >= s_c = p50c - p10c: `p50' - k s' <= p50' - k s_c <= p50c - k s_c`
  for every k >= 0 (the first step because the spread is at least as wide, the second because the median is not higher). The rule
  gives s' >= s_c: p10' = min(lower p10, p10c - (p50c - p50')) so s' >= p50' - p10c + p50c - p50' = s_c. The clamp at zero can raise p10' to
  0 and shrink the spread; then the path is `p50' (1 - k)`, which for k <= 1 is at most `p50c (1 - k) <= p50c - k s_c` (because p10c >= 0) and for
  k > 1 is negative, which the Planner floors at zero, so the clamp only ever moves in the conservative direction. Every quantile is at or below
  both inputs at the same rank. The identity holds when the corrected median is the lower one.
- `planning_inflation` is the larger of the published band inflation and the ungated one (persistence's own is always 1). Today's remaining
  PV is the LOWER of the re-anchoring on the planning median and on the ungated median (the 2 kWh threshold of the re-anchoring is not
  monotone in the median, so the planning median alone could otherwise assume MORE remaining PV just below it).
- A fallback caps overall confidence at 0.45 (LOW) exactly like a rejected forecast, adds `PV_SKILL_GATE_FALLBACK` to
  `confidence.downgrade_reasons` and one reason and one WATCH uncertainty entry per fallback day to the advice.

**Layer 2: the guard (by construction), in BOTH advisor paths.** On a day set where the gate fell back, the advice is computed TWICE:
on the planning values (layer 1) and exactly as the gate-OFF engine would have computed it (the ungated corrected PV days, the confidence
label the OFF engine computes BEFORE the gate's LOW cap, the ungated band inflation, today re-anchored on the ungated median). The advice with
the strictly HIGHER recommended charge target is published; a tie keeps the planning run (`pv.prefers_ungated`; a target that is not a finite
number keeps the planning run). When the ungated advice is published the gate's LOW cap, `PV_SKILL_GATE_FALLBACK` and its notes still apply
and one more plain reason, `PV_SKILL_GATE_UNGATED_KEPT`, says that the ungated corrected forecast would have given the higher target and was kept.
- V1 engine (`engine.py`): `advise(...)` runs twice on a fallback; the replicated gate-OFF run is checked in every world of the suite to give
  exactly the gate-OFF engine's overnight target and safe-export block.
- Shadow cycle (`shadow_cycle.py`): `advise_charge_target` runs twice; the planning run takes no PV credit on a fallback (fail closed, label LOW),
  the second run takes the credit the gate-OFF cycle would have offered (its p10 and label). Because the planning run takes no credit, its target
  can only be at or above the other, so in this path the guard is a pure safeguard against a later change of the credit rule (tested with a lowered
  planning target injected). The V1 target inside the cycle comes from the engine and has the engine's guard.
- Without a fallback (gate OFF, the gate keeps the corrected forecast, or the forecast is REJECTED) the code path, the output and the cost are
  those of the pre-fix tree: nothing is computed twice and the whole report is identical with the gate ON and OFF.

**The guarantee, stated precisely.** The recommended charge target (the V1 engine's `recommended_target_soc_pct` and the V1.1 charge target of
the shadow cycle) with the gate ON is never below what the gate-OFF engine would have recommended for the same inputs: **by construction on the
fallback path** (the gate-OFF answer is recomputed and the higher target published) and **verified on 600 unseen engine worlds and
200 unseen shadow-cycle worlds** (0 violations), and on the 600 regression worlds of round 1. The other items of the advice (safe export,
trajectories, reasons) come from the advice that was published.

**What it does NOT guarantee.**
- The target may be HIGHER than needed: the gate can only raise a target, and with a LOW label and a fallback it often does (in the real-PV replay
  below it raised the fictional house's target on 31 of 49 days). More battery is retained, at a cost in cheap-tariff energy that this
  change does not price.
- Persistence can lag a regime change (a long dull spell followed by a bright day, or the reverse); the published forecast is still persistence
  and can be wrong in either direction. Only the energy actions are protected, not the forecast.
- It is the ADVICE that is protected. It is advisory SHADOW: nothing in this change applies, writes or schedules anything, and nothing is enabled.
- The guarantee is only as good as the replication of the gate-OFF engine: if a later change alters how the gate-OFF engine builds its Planner
  without the guard being updated, the equality checks of the suite (the ungated advice IS the gate-OFF answer, in every world) fail.
- When the ungated advice is published, its other items (safe export, trajectories) are the gate-OFF engine's, computed with the OFF confidence
  label; the published `confidence` block stays the capped LOW. On the worlds of the suite the guard never needed to fire in the real code (the
  spread-preserving band was enough: 0 of 1,200 engine worlds and 0 of 200 cycle worlds); it was exercised by injecting broken planning rules.
- The compute of the planning step is doubled on a fallback day set.

**Evidence (synthetic, written failing-first; counts only).**
- Failing-first, round 2: the new checks were run against the unchanged round-1 code first: 62 checks failed (world 8077: 80 to 75 with the round-1
  band and 80 to 70 with persistence unchanged; no guard; the spread not kept: on 4000 random band pairs the round-1 band's pessimistic PV was
  above the ungated one in 1571 of 32000 pairs x k; no `prefers_ungated`; on the 300 worlds of 8000-8299: I1 1, I3 5, I7 106, I8 202 violations).
- Seeds 7000-7299 and 8000-8299 (600 worlds) informed the round-2 decision and are BURNED; they stay as regression: with the fixed code 0
  violations of I1-I8, the recommended target never lowered (raised in 97 and 93 worlds, equal in 203 and 207), the unrounded pessimistic-case
  target never lowered (round 1: 2 and 5 worlds), what the engine publishes about PV byte-identical to the pre-fix tree in every world.
- UNSEEN range, pre-registered before the code under test ran on it (`_pv_worlds2.py`, eight regimes: the six of round 1 plus a stale persistence
  after a long dull spell and a skilled source whose forecast the gate keeps; 600 worlds, seeds 9000-9599; 200 shadow-cycle worlds of the same range):
  all pre-registered criteria met with ZERO violations: the recommended target with the gate ON was raised in 189 worlds, equal in 411 and lowered in 0 (the gate as it was before any fix lowered it in 212 of the same 600 worlds); the target stayed within [desired minimum, max SOC] with the reserve policy, floor and SHADOW untouched (I2: 0); the unrounded pessimistic-case target never lower (I3: 0); what the engine publishes about PV byte-identical to the pre-fix tree over all 600 worlds in both modes (I4); a world without a fallback day identical ON and OFF (I5: 0); the LOW cap, the code and one reason and one uncertainty entry per fallback day (I6: 0); the planning band, spread and pessimistic PV checks (I7: 0); the guard's consistency (I8: 0). The gate fell back in 375 of the 600 worlds. Shadow cycle: the V1.1 charge target not lowered (I9a) and the V1 target inside the cycle not lowered (I9b) in 200 of 200 worlds (a fallback in 116); the plan's headroom ceiling lower in 0 and the safe-export advice above the gate-OFF one in 0 worlds (informational). The guard itself published the ungated advice in 0 of these worlds (the planning band alone was enough).
  For scale, the gate as it was before any fix lowered the recommended target in 212 of these 600 worlds (35 percent).
- Mutation: 57 in-memory mutants of the band and the guard (the old per-quantile minimum, p10 not clamped, the guard missing in the engine and in the cycle,
  the guard picking the lower target, a flipped tie rule, the ungated run using the LOW label, the ungated PV days or inflation of the planning run, today's
  re-anchor on the planning median in the ungated run, the guard result without its reason or cap, ...) all killed. One mutant ("the ungated run uses the
  planning inflation") is equivalent (the planning inflation is by construction the ungated one) and was replaced by one that drops the inflation.

**Real-data replay (offline, counts only; one site, one autumn).** The offline PV series holds daily actuals and the day-ahead blend only: no hourly
load, no SOC, no tariff windows, no reserve or battery settings. A replay of the SITE's own targets is therefore impossible and was not done. Two
replays on the 49 target days 27 Sep - 14 Nov, re-run on the final code: (A) the real `PvModel` on the real PV series: the gate fell back on 49 of 49
days and kept the corrected forecast on 0; the pre-fix gate published a value above the ungated corrected one in some quantile on 33 of them; the
planning band exceeded the ungated band on 0 days and the published forecast differed from the pre-fix one on 0 days; (B) a HYBRID, the real engine path with
the real PV days against a fictional house and battery (NOT the site's targets): the pre-fix gate lowered the overnight target on 16 of 49 days (33 percent;
5 to 35 points), the fixed gate on 0 (raised on 31, equal on 18), the unrounded pessimistic-case target below the ungated one on 0 days (round 1: 1), confidence
label LOW on all 49 fallback days, the reason code on all 49.

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
- **What the replay on real data shows (kept offline): the gate kept the corrected forecast on 0 of 39 days (12 Oct to 19 Nov) and, in the planning replay, on 0 of 49 days (27 Sep to 14 Nov); one site, one autumn.**
  On that data it therefore equals "always publish persistence"; the replay's passes only say that persistence beat the corrected path at that
  site that autumn. There is no real-data evidence of how it behaves where the corrected path has skill (only synthetic tests cover that).
- A step change in the actuals can fool it: when the actuals step from dull to bright and the persistence baseline lags, a source with no
  skill can briefly beat the lagging baseline and be kept (reproduced on a synthetic world). There is no hysteresis, and no test of flapping near the 0.9 margin.
- Only the chosen (best-error) source is gated: if it fails but another source would pass, persistence is published (a test pins this).
- The fallback trace is structured only in the V1 engine report (`PV_SKILL_GATE_FALLBACK` in `downgrade_reasons`, the advice reasons and
  uncertainty). The published `pv_tomorrow` item and the envelope's top-level reason codes are contract-pinned and carry no code: the gate
  verdict (day count and the two errors) is only in the note text there.
- **Before it is enabled anywhere.** What was fixed (20 Nov 2026, two rounds): the advisor effect described under "The planning fix": with the gate
  ON the recommended charge target is never below what the gate-OFF engine would recommend (a planning band that keeps the ungated spread, a guard that
  recomputes the gate-OFF advice and publishes the higher target, a LOW cap and reason codes), shown failing-first, on 600 pre-registered unseen
  synthetic worlds and on the 49 real PV days with a fictional house. What is STILL required before any enable: (1) the owner's go (nothing is enabled
  or deployed; `PV_SKILL_GATE_DEFAULT` stays False); (2) the independent review of the planning fix, the guard and their limits; (3) the edit of the one
  arithmetic check the gate moves (`test_intelligence_arithmetic.py`, band widening), which is deliberately NOT edited here; (4) every limit in this
  list stays true: the gate kept the corrected forecast on none of the 49 real days (so the replays say nothing about a regime where a source has
  skill), one site and one autumn, designed after seeing the failure, not a guaranteed forecast improvement (the planning fix protects the energy
  advice from a bad forecast, it does not make the forecast better), and the Q3 reading of the finished acceptance run is unchanged. On the real
  replay the published gated p50 was above the actual on 25 of 39 days (18 ungated) because persistence lags the autumn decline: the planning value
  does not change that published number, only what the target is sized on.

## Optional second change: the recent-output envelope (separate commit, OFF by default)

The `recent_max` ceiling of the plausibility guard is 2.5 x the best observed day of the last 30 days. After a bright spell it is
loose enough to let an out-of-season corrected value through for weeks (a value several times the output of a dull day can sit just
under a ceiling set by the best days of the weeks before). With `PvModel(..., recent_envelope=True)` that one ceiling becomes **1.25 x the best actual of the last 14
days** (it needs at least 7 observed days in them, otherwise the legacy ceiling stays, so enabling it never removes a guard). A
corrected value above it is REJECTED exactly like any other ceiling breach: persistence, LOW confidence, the source, the values and the
limit named in `plausibility` and in the notes. The ceiling used is the LOWER of the legacy ceiling and the envelope (a configured
`pv_recent_headroom` between 1.0 and 5.0 is allowed, and below 1.25 the legacy ceiling can already be the lower one, so a plain replacement would
loosen it; a review found that and the code now takes the minimum). Enabling it therefore can only reject more, which is the safe direction for the advisor (less PV assumed,
more battery retained). Constants `PV_RECENT_ENVELOPE_DEFAULT` (False), `RECENT_ENVELOPE_DAYS` (14), `RECENT_ENVELOPE_HEADROOM` (1.25) and
`RECENT_ENVELOPE_MIN_OBS` (7); a constructor argument like the gate, not a `SiteConfig` field. Tests:
`intelligence/tests/test_intel_pv_recent_envelope.py` (synthetic data, 18 mutants applied in memory).

Limits: it is blunt. A genuinely bright day after two dull weeks is rejected and persistence is published instead (a deliberate
trade, see the plausibility paragraph in `ECCO_INTELLIGENCE_V1_ARCHITECTURE.md`); it addresses the over-forecast side only; it
changes nothing about a corrected value that is wrong but below the ceiling, which is the gate's job. It is independent of the gate
(either can be on without the other) and this commit can be dropped without touching the gate.
