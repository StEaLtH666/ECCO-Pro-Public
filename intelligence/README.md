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
| `scorecard.py` `advice_log`, `tools/advice_export.py` | durable advice log (additive table, one row per published charge-target / dump change, 400-day retention, failure-isolated `record_advice`) and a read-only (`mode=ro`) exporter printing the Ghost export's `advice` list; the host calls `Scorecard.record_advice(to_entity_payloads(env), dump_duration_min=...)` after publishing |

The V1.1 modules are a foundation: nothing consumes them yet and the V1 report is unchanged. See
`docs/intelligence/INTELLIGENCE_V1_1_FOUNDATION.md`; their suites are `tests/test_intelligence_v11_*.py`.
| `profiles/` | `site_profile.example.json` template; copy to a git-ignored `<site>.local.json` with your own entity ids |

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
