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

The test roots CI runs live in one file, `tools/offline_test_roots.txt` (includes `intelligence/tests`).

**Data policy:** no real household consumption, occupancy or entity-account data is committed. Examples and fixtures are
synthetic (`intelligence/synthetic.py`, fictional year 2030). Real exports, quality-report output and site profiles stay local
(`*.local.json`, `hist_stats*.csv*` are git-ignored).
