# intelligence/ — ECCO Intelligence V1 (shadow only)

Pure-Python (stdlib) read → learn → predict → recommend → score engine. **It has no write path**: no network, serial or
process imports, no control vocabulary (a test enforces this; the one allow-listed exception is the developer preview
tool `tools/preview_dashboard.py`, which runs a local Node.js process to render a preview). The deterministic ESP safety/control layer stays authoritative.

Design: `docs/intelligence/ECCO_INTELLIGENCE_V1_ARCHITECTURE.md`. Evidence: `docs/intelligence/PROTOTYPE_RESULTS.md`.

| Module | Role |
|---|---|
| `config.py` | site constants and the **battery reserve**: `user_reserve_soc_pct` (default 40 %, chosen per installation) and a separate `technical_min_soc_pct`; `effective_reserve()` = max(user reserve, technical minimum, any HA reserve), never lower, with the reason when something overrides the user |
| `history.py` | HA statistics → canonical hourly table (counters → kWh, gaps/stalls/flags, source merge), audit |
| `usage.py` | per-slot robust EWMA, window forecasts, intervals, nowcast, weekday test, expert promotion |
| `pv.py` | forecast-source correction, hour shape, useful-PV time |
| `battery.py`, `advisor.py` | SOC simulation; overnight target, safe export, session cover, reasons |
| `anomaly.py` | load anomalies, recurring signatures (neutral labels) |
| `engine.py`, `replay.py`, `backtest.py` | orchestration, leak-free replay, walk-forward backtest |
| `scorecard.py` | SQLite forecast/outcome store, metrics, bias insights |
| `synthetic.py` | seeded synthetic houses for tests |
| `tools/` | read-only HA statistics exporter, quality report, HA-sensor renderer, dashboard preview, `make_examples.py` (synthetic examples) |
| `inputs.py` | the one reading of system state: an `ecco_core` Snapshot -> `LiveInputs` (replays build their snapshot from History) |
| `explain.py` | V1.1: the `Advice` answer format (status, confidence factors, reasons, assumptions, blockers, input ages; SHADOW only) |
| `overnight.py` | V1.1: overnight demand learning, with conservative fallback and the return-from-away regime check |
| `charge_target.py`, `events.py`, `dump_advice.py` | V1.1: charge-target, Saving Session / export-event and reserve-aware Dump-to-Grid advice (energy budgets, fail closed) |
| `net_value.py` (the retrospective ledger; `value.py` is the plan-value module) | read-only battery value ledger: gross avoided import vs net benefit (export income the stored solar could really have earned, losses, optional wear; unknown wear is never folded into the net), well-mixed source tagging of the stored energy |
| `ghost.py`, `tools/ghost_report.py` | read-only Intelligence-vs-reality: a simulated ghost battery that follows recorded advice (`AdviceRecord`), both runs valued by `net_value.py`; per-day deltas, divergences in words, losing days, `ready_for_assisted_evidence` (evidence only; ghost below reserve must be 0); JSON export format in the tool docstring |
| `ghost_feed.py` | pure: builds the Ghost's input from the runtime's hourly `History`, the advice log (`Scorecard.advice_records`), the tariff (`TariffResult`: no verified tariff means no money, behaviour comparison only) and the `SiteConfig`, runs `run_ghost` at 60-minute slots and returns a JSON-safe summary of at most about 8 KB: last 14 days, actual vs ghost, deltas, advice followed or not, `ready_for_assisted_evidence`, uncertainty (stock rules, model baseline, efficiency +/- 3 points); a simulation, Intelligence controlled nothing |
| `ghost_compare.py`, `tools/ghost_diag_report.py` | pure: the Ghost's diagnostics-only block (the existing schedule against Intelligence's logged advice: money only with a verified tariff, SOC, reserve margin and breach, uncertainty and a within-noise verdict, bounded to 12 KB, failures as small blocks with a constant reason) and its plain-text report on a downloaded diagnostics file; read-only, see the section below |
| `scorecard.py` `advice_log`, `tools/advice_export.py` | durable advice log (additive table, one row per published charge-target / dump change, 400-day retention, failure-isolated `record_advice`) and a read-only (`mode=ro`) exporter printing the Ghost export's `advice` list; the host calls `Scorecard.record_advice(to_entity_payloads(env), dump_duration_min=...)` after publishing |

The V1.1 modules are a foundation: nothing consumes them yet and the V1 report is unchanged. See
`docs/intelligence/INTELLIGENCE_V1_1_FOUNDATION.md`; their suites are `tests/test_intelligence_v11_*.py`.
| `profiles/` | `site_profile.example.json` template; copy to a git-ignored `<site>.local.json` with your own entity ids |

## Ghost, diagnostics-only

**It is a simulation.** Intelligence controlled nothing: the real battery did what the owner's existing TOU schedule made it do, and
the "advice" side is arithmetic on the recorded hourly energies (`ghost.py`, `ghost_feed.py`), applying only the advice that was actually
logged. It reads, it simulates, it returns a dict. No entity, no contract change, no control authority, nothing written, called or armed.

**What it shows**, for the period and per local day, existing schedule against Intelligence advice (differences are advice minus existing):
(a) money in pence, only with a verified import tariff covering the period (otherwise `NO MONEY` and the behaviour only);
(b) SOC: minimum and end of day of both runs, and the difference; (c) reserve protection: the reserve in force, each run's minimum SOC and
its margin to the reserve, whether the advice run would have gone below it (also at the two altered efficiencies); (d) uncertainty: the two
closing-stock rules, the round-trip efficiency band (+/- 3 points), the no-advice baseline replay error, the data-quality flags, and a
verdict: `ADVICE_AHEAD_BEYOND_NOISE`, `ADVICE_BEHIND_BEYOND_NOISE`, `WITHIN_NOISE`, `NO_ADVICE_EFFECT` or `NOT_ASSESSED_NO_MONEY`. The rule:
noise = efficiency spread + closing-stock rule spread + baseline error (summed, at least 0.5 p); a win or loss is claimed only when the advice
effect is strictly beyond the noise, so a result inside it is never read as a win. Expect `WITHIN_NOISE` for small effects: the efficiency
band moves the advice effect a lot when the advice changes how much the battery holds for several days.

**How it is computed.** Lazily, only when the diagnostics are downloaded, in the executor, from data the coordinator already holds: the last
cycle's `EngineJob` (a reference copy without its rows), the cached recorder rows turned into a `History` by a throw-away `HistoryReuse`,
the engine's own input judgement (`quality.assess_inputs`) for the verified tariffs, the decided `SiteConfig` and the reserve helper, and the
logged advice read through `RuntimeStateStore.advice_rows` (SQLite `mode=ro`). The poll cycle does no extra work and has no new failure path.
One job at a time, a 30 s budget (then `TIME_BUDGET`), and the block says which cycle it is as of (`inputs_as_of`). Measured on synthetic
data: the pure comparison on a 14-day hourly table takes about 0.05 s; the whole job on the cached 30-day table about 0.04 s; a download
with the block about 0.2 s (0.15 s of it is the integration's fixed job cool-down). The block is at most 12 KB (oldest days dropped, counted).
Anything that fails gives a small block with a status (`INSUFFICIENT_HISTORY`, `NO_ADVICE_LOGGED`, `UNAVAILABLE`, `ERROR`) and a constant
reason code, never an exception or a partial figure; the rest of the download is unchanged. It carries dates, numbers and constant words
only: no entity id, site value, coordinate, time zone name or sensor text.

**What it cannot show.** Dump-to-Grid advice is logged without a window (the engine passes no intended duration), so it is not simulated.
Money covers only the days the tariff integration's rate table covers (a few days), not the whole 14-day history. SOC is an hourly mean and
advice windows snap to whole hours; spilled PV is unknown. It needs the site file to map the battery charge and discharge energy counters
(`chg_energy`, `dis_energy`); without them it says `INSUFFICIENT_HISTORY` and names the missing fields (`history_fields_absent`). It is one
house over a short period: evidence, not proof.

**Use it.** Settings, Devices and services, ECCO Intelligence, Download diagnostics; then
`python intelligence/tools/ghost_diag_report.py <downloaded file>` prints the compact comparison (`--json` prints the block). The tool
accepts the whole download, a file with a `ghost` key, or the block.

**Status.** Offline only; nothing is deployed. The integration wiring (coordinator, diagnostics, `runtime/ghost_link.py`,
`RuntimeStateStore.advice_rows`) is delivered as `custom_components/ecco_intelligence/tests/ghost_diag_wiring.patch`, not applied: it
adds `intelligence.ghost_compare` to the kit's vendor roots (`tools/build_ha_integration.py` ROOT_MODULES), which two pinned tests list
(`test_runtime_build.py` ROOTS and `test_runtime_import_without_ha.py`'s runtime module list), so applying it is an owner-approved re-pin.
`tests/test_runtime_ghost_diag.py` applies the patch to a temporary copy and proves the wiring there.

Run the tests (each is a plain script, same convention as `health/tests`):

    python intelligence/tests/test_intelligence_foundations.py
    python intelligence/tests/test_intelligence_scenarios.py
    python intelligence/tests/test_intelligence_scorecard.py
    python intelligence/tests/test_intelligence_safety_guards.py   # PV plausibility, absence guard, effective-minimum guard, input hardening
    python intelligence/tests/test_intelligence_examples.py        # shipped examples == a fresh synthetic run
    python intelligence/tests/test_intelligence_dashboard_prototype.py   # needs PyYAML (+ Node for the render checks)

The test roots CI runs live in one file, `tools/offline_test_roots.txt` (includes `intelligence/tests`, `ecco_core/tests` and the
SHADOW runtime boundary root `custom_components/ecco_intelligence/tests`; see `docs/intelligence/INTELLIGENCE_FOUNDATION_CONTRACT.md`).

**Data policy:** no real household consumption, occupancy or entity-account data is committed. Examples and fixtures are
synthetic (`intelligence/synthetic.py`, fictional year 2030). Real exports, quality-report output and site profiles stay local
(`*.local.json`, `hist_stats*.csv*` are git-ignored).
