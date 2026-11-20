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
| `scorecard.py` `advice_log`, `tools/advice_export.py` | durable advice log (an additive table created by the first advice write, not when the scorecard is opened; one row per kind per slot cycle, about 52 rows a day at most, 400-day retention, failure-isolated `record_advice`, each write read back by its row ids on the writing connection (not a durability proof); closed incidents of its failures in a small `advice_incident` table created only after a verified write; see "What is written" below) and a read-only (`mode=ro`) exporter printing the Ghost export's `advice` list (or, with `--incidents`, the incidents); the host calls `Scorecard.record_advice(to_entity_payloads(env), dump_duration_min=...)` after publishing |

The V1.1 modules are a foundation: nothing consumes them yet and the V1 report is unchanged. See
`docs/intelligence/INTELLIGENCE_V1_1_FOUNDATION.md`; their suites are `tests/test_intelligence_v11_*.py`.
| `profiles/` | `site_profile.example.json` template; copy to a git-ignored `<site>.local.json` with your own entity ids |

## Ghost, diagnostics-only

**It is a simulation.** Intelligence controlled nothing: the real battery did what the owner's existing TOU schedule made it do, and
the "advice" side is arithmetic on the recorded hourly energies (`ghost.py`, `ghost_feed.py`), applying only the advice that was actually
logged. The block itself reads, simulates and returns a dict: no entity, no contract change, no control authority, and the download writes, calls and arms nothing. The integration does make ONE durable write for it, the advice log (see "What is written" below).

**What it shows**, for the period and per local day, existing schedule against Intelligence advice (differences are advice minus existing):
(a) money in pence, only with a verified import tariff covering the period (otherwise `NO MONEY` and the behaviour only);
(b) SOC: minimum and end of day of both runs, and the difference; (c) reserve protection: the reserve in force, each run's minimum SOC and
its margin to the reserve, whether the advice run would have gone below it (also at the two altered efficiencies; judged on the hourly-mean or
end-of-hour SOC against the base reserve only, so a dip inside an hour can be missed); (d) uncertainty: the two
closing-stock rules, the round-trip efficiency band (+/- 3 points), the no-advice baseline replay error, the data-quality flags, and a
verdict: `ADVICE_AHEAD_BEYOND_NOISE`, `ADVICE_BEHIND_BEYOND_NOISE`, `WITHIN_NOISE`, `NO_ADVICE_EFFECT`, `NOT_ASSESSED_NO_MONEY` or
`NOT_ASSESSED_EXPORT_UNVERIFIED` (the export tariff is not verified, so export income is counted as 0 in both runs, and the advice run exports a
different amount: the pence figures stay visible, but no ahead or behind claim is made). The rule:
noise = efficiency spread + closing-stock rule spread + baseline error (summed, at least 0.5 p); a win or loss is claimed only when the advice
effect is strictly beyond the noise, so a result inside it is never read as a win. Expect `WITHIN_NOISE` for small effects: the efficiency
band moves the advice effect a lot when the advice changes how much the battery holds for several days.

**How it is computed.** Lazily, only when the diagnostics are downloaded, in the executor, from data the coordinator already holds: the last
cycle's `EngineJob` (a reference copy without its rows), the cached recorder rows turned into a `History` by a throw-away `HistoryReuse`,
the engine's own input judgement (`quality.assess_inputs`) for the verified tariffs, the decided `SiteConfig` and the reserve helper, and the
logged advice read through `RuntimeStateStore.advice_rows` (SQLite `mode=ro`). The computation adds nothing to the poll, refresh or slot
cycles: its cost is paid by the download only (the one write the integration makes for it is the advice log, below). One job at a time, a 30 s
budget (then `TIME_BUDGET`), and the block says which cycle it is as of (`inputs_as_of`). Measured on a development PC: about 0.23 s on 30 days of
history, 0.64 s on 120 days and 1.7 s with the 5000-row advice cap; a slower Home Assistant host may need several times that (the 30 s budget
holds). The block is at most 12 KB (oldest days dropped, counted).
Anything that fails gives a small block with a status (`INSUFFICIENT_HISTORY`, `NO_ADVICE_LOGGED`, `UNAVAILABLE`, `ERROR`) and a constant
reason code, never an exception or a partial figure; the rest of the download is unchanged. It carries dates, numbers and constant words
only: no entity id, coordinate, time zone name, secret or sensor text. The numbers ARE site-derived behaviour and money figures (daily pence,
SOC, kWh, throughput, the reserve percentage, dates and timestamps with an offset): they show when the house charges and discharges and what
that costs. The diagnostics redaction set is unchanged and does not remove them, so review a downloaded file before sharing it.

**What is written (a durable write).** The Ghost needs the advice that was published, so the slot cycle's store step logs it: the table
`advice_log`, in the integration's own `state/scorecard.sqlite3` (the same file as the scorecard; no other file or entity is added; one
small second table, `advice_incident`, below).
Each slot cycle (25 a day: every full hour and 21:30; 26 on the day the clocks go back) adds one row per kind (charge target, Dump-to-Grid),
so at most 52 rows a day (50 on a normal day) and, at the 400 days kept, about 21 000 rows (a few MB); older rows are deleted at write
time. The engine's validity is at most 900 s and slots are an hour apart, so the same advice is logged again every slot, every time as
its own row (the one skip: the same advice published again inside the validity of its own previous row, within one slot cycle): the Ghost
counts distinct advice (kind, window, target), not rows. The
table is created by the first advice write, not when the scorecard is opened, and the write runs in its own transaction after the scorecard
record: if it fails (a table of that name with other columns, a failing create, a full disk) the failure is counted and nothing else is
affected, not the scorecard record, the start-up writable gate, `outcome_metrics` or any published value.

*Verified write, incident.* After the commit, the connection that wrote the rows reads each of them back by its id and compares its kind,
issue time and content hash with what it wrote (a *same-connection read-back*); a write whose rows are found again as written is
*verified*. That proves exactly this much: the rows are visible to the connection that wrote them and match what was written. It is not a
durability or fsync proof, and it says nothing about what a power loss would keep. A write that raises nothing but whose rows are not
found again (or whose read-back fails) is *unverified*, not a success. A
failed or unverified write opens an *incident* (in memory, the newest 10): when it began and last failed, the attempts, the slot cycles
missed, the exception class name as the reason and the issue times of the advice that could not be written. A store step that times out
or raises opens or extends the incident too, but it is counted only inside the incident (its attempts and missed slot cycles), not in
`advice_write_failures` or `advice_unverified_writes` and not in the failed/unverified-since-start count of the `STORE_RECORD` text.
`self_test.STORE_RECORD`
is WARN, with the reason and the counts, while the latest attempt has failed or is unverified, and returns to PASS only after a
verified write, when the incident is closed and kept; a slot cycle with nothing to log changes nothing, and after a restart PASS shows only
after that run's own first verified write. Where to look: the diagnostics download's `counters.advice_write_failures` and
`counters.advice_unverified_writes` (history, never reset), `counters.advice_current_failure` (1 while an incident is open),
`advice_incidents`, `last_store.advice_error` (the class name) and `self_test.STORE_RECORD`; one warning is logged when an incident opens.

*What survives, what is lost.* Closed incidents are written, right after the next verified write, to the table `advice_incident` (at
most 10 rows: counts, times, a class name, never a message). It is created only then, never at start-up, when the scorecard is opened, by an
advice write, or while the database cannot take the advice write. It is shown in the download as `advice_incidents.stored` and printed by
`python intelligence/tools/advice_export.py <scorecard file> --incidents`. The write of an incident into it is a plain commit and is not
read back. An incident still open when Home Assistant restarts, or open
because the database never takes the advice write again, is not in that table: it then lives only in the one warning logged when it opened
(the class name only) and, until a restart, in memory and the diagnostics. If writing a closed incident fails or times out after a verified
advice write, nothing else changes (`STORE_RECORD` stays PASS, no published value differs): the failure shows only in
`advice_incidents.last_persist` (the class name), and the incident stays listed and is offered again at the next verified write. The table
keeps the newest 10 by the text of `first_failed_utc`, which is also an incident's key, so after the clock has been stepped backwards a new
incident whose first failure is older than the 10 rows already stored is written and then pruned at once: it is reported as persisted but
is not in the table (a known limit). All of this is diagnostics only (no entity, no published value,
status, mode or advice changes) and takes effect with the Ghost update's own restart. To roll back: install the previous kit (the tables
are then unused) and, to remove them, drop `advice_log` and `advice_incident` or delete `scorecard.sqlite3` while the integration is
stopped. The diagnostics download only reads them.

**What it cannot show.** Dump-to-Grid advice is logged without a window (the engine passes no intended duration), so it is not simulated.
Money covers only the days the tariff integration's rate table covers (a few days), not the whole 14-day history. SOC is an hourly mean and
advice windows snap to whole hours; spilled PV is unknown. It needs the site file to map the battery charge and discharge energy counters
(`chg_energy`, `dis_energy`); without them it says `INSUFFICIENT_HISTORY` and names the missing fields (`history_fields_absent`). It is one
house over a short period: evidence, not proof.

**Use it.** Settings, Devices and services, ECCO Intelligence, Download diagnostics; then
`python intelligence/tools/ghost_diag_report.py <downloaded file>` prints the compact comparison (`--json` prints the block). The tool
accepts the whole download, a file with a `ghost` key, or the block.

**Status.** Offline only; nothing is deployed and nothing is installed. The integration wiring (coordinator, diagnostics,
`runtime/ghost_link.py`, `RuntimeStateStore.advice_rows`) is APPLIED to this branch (owner approval of 17 Nov): it adds
`intelligence.ghost_compare` to the kit's vendor roots (`tools/build_ha_integration.py` ROOT_MODULES) and the two pinned tests that list
them were re-pinned in the same step (`test_runtime_build.py` ROOTS and `test_runtime_import_without_ha.py`'s runtime module list). The
block is computed only when the diagnostics are downloaded; the eleven-entity contract is unchanged. A kit built from this branch is
deployed only after the Intelligence acceptance run, the M2 scan and the staged approvals. `tests/test_runtime_ghost_diag.py` runs the
wired scenarios (`tests/_ghost_diag_l2.py`) against this tree; `tests/ghost_diag_wiring.patch` stays, unchanged, as the record of the wiring as first proven.
A later BLOCKED row (or a fallback that is not followed) of the same kind withdraws earlier advice from its issue time on, and the Ghost counts
advice rows and distinct advice separately (`advice.followed` is distinct; `records_in_period` and `not_followed` are rows).

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
