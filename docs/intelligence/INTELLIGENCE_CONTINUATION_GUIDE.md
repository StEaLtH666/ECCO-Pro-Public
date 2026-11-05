# Intelligence SHADOW v0.1: continuation guide

What the Intelligence track has built, how to test it, and what is still open. It describes the Intelligence source as
it stands after integration steps IP-4a and IP-4b (the review fixes) and the SHADOW v0.1 completion (the grid-charge TOU
classification, configuration-poll freshness, refresh before expiry with the poll-phase-aligned refresh, the raise-only
reserve preference, and the site-file check). It is a working guide for whoever continues the track. The decisions
themselves stay with the owner.

**Status.** Everything here is SHADOW: it advises, applies nothing and writes nothing to Home Assistant, the dongle or the
inverter. Nothing is installed or deployed. The Home Assistant install kit is staged, PENDING DP-4. The data in every
suite is synthetic.

## 1. What exists

| Area | Files | Document |
|---|---|---|
| Contracts (foundation) | `intelligence/{site_decisions,periods,advisory_contract,authority_vocab}.py`; S0 reconciled onto them | [INTELLIGENCE_FOUNDATION_CONTRACT.md](INTELLIGENCE_FOUNDATION_CONTRACT.md), [INTELLIGENCE_S0_INPUT_CONTRACT.md](INTELLIGENCE_S0_INPUT_CONTRACT.md) |
| S1 offline advice prototype | `intelligence/prototypes/s1_advice/` (reconciled onto the register and periods) | [INTELLIGENCE_S1_OFFLINE_ADVICE_PROTOTYPE.md](INTELLIGENCE_S1_OFFLINE_ADVICE_PROTOTYPE.md) |
| Data quality | `intelligence/quality.py` (body), `intelligence/faults.py`, `intelligence/tools/validate_capture.py` | [DATA_QUALITY_METHOD.md](DATA_QUALITY_METHOD.md), [REAL_DATA_CAPTURE_KIT.md](REAL_DATA_CAPTURE_KIT.md) |
| Planning | `intelligence/shadow_cycle.py` (body), `intelligence/{tariff,tou_table,daily_plan,baselines,value,backtest_advice}.py` | [INTELLIGENCE_PLANNING.md](INTELLIGENCE_PLANNING.md), [INTELLIGENCE_FOUNDATION_CONTRACT.md](INTELLIGENCE_FOUNDATION_CONTRACT.md) section 13 |
| Home Assistant runtime | `custom_components/ecco_intelligence/` (sensor and binary_sensor only), `tools/build_ha_integration.py`, `tools/ecco_intel_drill.py` (mock-root drills, the runbook printer, `site-check` for the owner's site file) | [INTELLIGENCE_HA_RUNTIME.md](INTELLIGENCE_HA_RUNTIME.md), [INTELLIGENCE_SHADOW_INSTALL_RUNBOOK.md](INTELLIGENCE_SHADOW_INSTALL_RUNBOOK.md) |
| Card and dashboard | `frontend/ecco-intelligence-card/`, `home-assistant/dashboards/ecco_intelligence.yaml` | [UI_DESIGN.md](UI_DESIGN.md) |
| End-to-end test | `custom_components/ecco_intelligence/tests/test_integration_e2e.py`: the built kit's own `run_cycle` in a fresh `-I` interpreter (all OPEN, SYNTHETIC_TEST accepted, paused, and dq's `no_pv` fault), with the null rule, SHADOW and the paused status pinned; between cycles, the kit's own mapping past the validity and its `stale_from` | this guide |

The frozen interfaces and the items that are not open to a change request are listed in section 8 of the foundation contract.
The boundary suite `custom_components/ecco_intelligence/tests/test_runtime_boundaries.py` can only be tightened.

## 2. How to run the tests

Use Python 3.12 with PyYAML, as CI does. Run every suite isolated, with `-I -B`, and with `PYTHONDONTWRITEBYTECODE=1` set. On
Windows, give the runner `-X utf8`, because a failing suite's output can contain characters that a cp1252 console cannot print.

```
python -X utf8 -I -B tools/run_offline_tests.py --root intelligence/tests --parallel 1
python -X utf8 -I -B tools/run_offline_tests.py --root ecco_core/tests --parallel 1
python -X utf8 -I -B tools/run_offline_tests.py --root custom_components/ecco_intelligence/tests --parallel 1
python -I -B custom_components/ecco_intelligence/tests/test_integration_e2e.py
python -I -B intelligence/tools/make_examples.py --check
```

The roots are listed in `tools/offline_test_roots.txt`. Measured on the full Intelligence source after the SHADOW v0.1
completion, the `intelligence/tests` root takes about 6 minutes and `custom_components/ecco_intelligence/tests` about 6
minutes (the poll-phase suite `test_runtime_poll_phase.py` alone about 3.5 minutes). The card's Node suite (`frontend/ecco-intelligence-card`, `node --test test/*.test.mjs`) runs locally only;
`tools/tests/test_intelligence_card.py` pins it statically for CI.

Run the `home-assistant/tests` root (about 30 minutes), the `tools/tests` root and the registry suites when the machine
can spare the time and no supervised live step is in progress. They belong to the full local gate before a PR. The
registry suites are `test_pex_transition`, `test_scope_chain`, `test_pub0_transition` and
`test_offline_suite_exit_codes`.

Two runtime builds of one tree are byte-identical. `test_runtime_build.py` checks that, and the e2e test builds its own kit in a
temporary directory.

## 3. Change requests applied at integration (IP-4a, IP-4b)

- **CCR-1 revision 2 (runtime).** The vendored kit has no `compile` call. `site_decisions` keeps the record-reference and
  decision-id patterns as strings and exports `RECORD_REF_PATTERN` and `record_ref_ok`. The three policy call sites use
  `record_ref_ok`, and the plan body's published-text guard is a pattern string too. The frozen vendor scan passes on the source
  and on the freshly built kit.
- **CCR-DQ-1 and CCR-PLAN-1.** These add I-D6 keys with no default limit. `QUALIFYING_READING_KEYS` covers
  `battery.soc_raw_pct`, `inverter.clock_offset_s` and `tariff.events`. `PLANNING_READING_KEYS` covers
  `tou.current_target_soc_pct`. Each key stays UNRESOLVED until a site records a limit, and the 900 s ceiling caps that limit.
- **CCR-PLAN-4.** The texts of `GRID_CHARGE_LIMIT_UNKNOWN`, `SITECONFIG_INVALID` and `EFFICIENCY_OUT_OF_RANGE` state no value.
  The numbers and the exception go to the finding's evidence instead.
- **CCR-PLAN-3.** The foundation contract states the value shape of the tariff readings.
- **CCR-INT-1 (IP-4b, additive).** The foundation contract states the inner shapes of the tariff, value and plan blocks.
  `tariff.window` is `{start, end}` as aware ISO-8601 UTC timestamps (it was a local `HH:MM-HH:MM` label, which the card
  does not read). The envelope does not refuse other shapes; the card suite [10] runs the SHADOW cycle with a verified
  tariff and pins that the card reads every block it publishes.
- **`with_next_run_at` (IP-4b, additive).** A contract constructor that sets only the status attribute `next_run_at`.
  The runtime applies the next schedule slot to every computed and STALE envelope (it was always null there).

The integration fixups are listed below. None of them loosens a fail-closed rule, a frozen suite or a boundary suite.

- The planning suite's fixtures rebuild the LiveInputs from the snapshot they change. The CCR-PLAN-1 simulation only tightens
  limits now that the keys are real. A reserve helper outside 0..100 is refused by the quality layer itself, and the "configuration
  None while quality passes" case now uses a 60 kW grid-charge limit (`SITECONFIG_INVALID`).
- The planning suite follows the value-free texts of CCR-PLAN-4.
- The SHADOW cycle leaves an unusable history entry out of the PV model's history instead of failing its self-test.
  An earlier version of this fixup kept any hour record filed under its own start, which is looser than the quality
  layer's record rule; the fixup now takes the quality layer's own well-formed records, the set `prepare_history` starts
  from. `test_intel_cycle_planning` [14] pins the result: a fresh history with a junk, None or malformed entry
  publishes exactly what the same history without that entry gives, and never `SELF_TEST_FAILED`. One outcome changed
  with it: with all decisions OPEN, an hour record whose energies are not a mapping used to raise inside the PV model
  (`SELF_TEST_FAILED`). It is now left out like every other malformed entry (dq's `HISTORY_RECORD_MALFORMED`, WARN).
- The stand-in Home Assistant suite follows the real dq and plan bodies:
  - a history-only item follows the history's own freshness;
  - a BLOCKED result turns STALE when its validity ends.
- The presentation package is held out (section 5).
- IP-4b, after the read-only end-to-end review (none loosens anything either):
  - an item resting on a dongle input is never valid longer than the quality layer's liveness bound minus the liveness
    age (the SHADOW cycle skipped the liveness reading when it bounded the validity);
  - the runtime maps every publish as of the next tick plus `PROPOSED_TICK_MARGIN_S` (the publish horizon), so no number
    and no `fresh` = on outlives its `valid_until` between ticks; a result valid for less than a tick is published STALE;
  - the stand-in Home Assistant harness gives the CCR-DQ-1 / CCR-PLAN-1 keys a limit and seeds two days of import rates,
    so charge_target is OK on fresh inputs and the withholding checks can fail; a publish-horizon scenario pins the
    entities over two hours of ticks;
  - the e2e test renders the kit's payloads past the validity and through `stale_from`;
  - texts: the real cycle's BLOCKED result is valid for at most 900 s (the age rule covers only an envelope without a
    validity), the runtime note marks CCR-1 revision 2 as applied, the dashboard marks the package held out, and the
    PR-1 and PR-2 texts no longer point at this guide.
- Wording that the integration made stale: the capture validator's `backtest` text says what the backtest still needs
  (section 4), the data-quality suite labels its clean-base section by whether CCR-DQ-1 has landed, and the card
  design, card README and install runbook mark the package as held out until PR-6.

**The SHADOW v0.1 completion.** The contract is section 13 of the foundation contract; what each part changed:

- **Engine (PR-2):** the new readings (`liveness.config_poll_changed_at`, `tou.enabled`, `tou.grid_charge_enabled`,
  `tou.overlay_state`, `pref.advisory_reserve_raise_pct`), configuration-poll freshness (300 s bound), the schema v2 TOU
  table and its fail-closed grid-charge classification (`intelligence/tou_table.py`), `INPUT_EXPIRING` below the 125 s
  refresh margin, the TOU claim as INFO codes only, `MORNING_SOC_ASSUMES_CHARGE`, the register-230 WARN and the raise-only
  reserve preference. No frozen interface changed.
- **Runtime (PR-3):** the v2 site-file mapping (six-entity slots, `{entity, online_entity}` configuration liveness, both
  enables, the overlay entities, the raise helper, `fresh_by: refreshed_at`, attribute readings), the second liveness
  memory, refresh before expiry (slot and refresh cycles, the 55 s floor, the CPU guard, the retry and the back-offs), the
  poll-phase-aligned refresh (amendment A23: one state listener on the telemetry poll text, a poll-driven step 3 s after
  each new poll, the tick held back while polls arrive and back on its own rules when they stop), the V-4 clamp, per-entity
  writes with the timestamp-only attributes kept out of the recorder (A17), and the cadence diagnostics. The stand-in Home
  Assistant delivers `state_changed` and fires one-shot timers; `test_runtime_poll_phase.py` sweeps the poll phase and
  counts STALE from the recorder rows (A32), with missed, late and frozen polls over seven phases (at most one STALE cycle
  per episode), the supervision heartbeat lapsing while polls continue and stopping with them (A31(b)), a poll text
  every 2 s (a pending poll-driven step is never moved later, A33) and the settle hold (A36: no cycle starts inside the
  settle delay of the newest poll seen, so the exception retry, a STALE refresh, a floor-deferred step and a step that
  waited for a cycle in flight each read a poll's late writes; the hold is one-shot, so the 2 s text still runs). The
  entity map refuses a configuration-poll liveness or online entity equal to the telemetry poll text (A33), two
  boolean gate readings (the TOU enables, `supervision.stable`) on one entity (A36, RR-3), a boolean gate on the
  configuration-online entity and the raw SOC on the canonical SOC's entity (A39), and one rate event (entity and
  attribute) under two tariff tables (A42, RT4-2). The diagnostics download shows the source notes, each a contract key
  and a constant code (A42), and lists each PV forecast observation by its day and position only, never by the site
  file's source name (A45). A50: the history parsed from a recorder read is reused between cycles while the read's
  exact content is unchanged (a changed or refused read rebuilds; the shared records are never changed downstream,
  `test_runtime_history_reuse.py`), and `cycle_stats` keeps 4800 runs, so one diagnostics download at the end holds
  every run of a window that spans at most 72 h (after an outage pauses the clock, the first hours come from the
  earlier downloads; runbook section 8).
- **Docs and drill (PR-3, WP-5):** the runtime note, the runbook (R3, R5, T1-T11, Q1-Q9, the capacity check, the PR-5
  commands marked "lands with PR-5"), this guide, the card design (the next refresh in the header; the 3D Overview link
  dropped) and `tools/ecco_intel_drill.py site-check`.

## 4. Open change requests and decisions

| Item | State | Meanwhile |
|---|---|---|
| CCR-1 r2/r3 (S1: a charge window crossing local midnight) | DEFERRED to the owner | E14 is accepted as a contract-induced, fail-closed result: a window across local midnight BLOCKs the charge-window items (`CHARGE_WINDOW_CROSSES_MIDNIGHT` from the TOU classification, `CHARGE_WINDOW_UNKNOWN` before it). The change would touch six V1 readers of `cheap_window_end_min` |
| CCR-DQ-2 / CCR-PLAN-2 (a charge window from a VERIFIED tariff without a fresh TOU table) | DEFERRED | fail closed: no TOU table, no charge window; a verified tariff alone is never a window, it only checks the TOU window |
| CCR-DQ-3 (show a no-PV `pv_tomorrow` as INSUFFICIENT_DATA) | DEFERRED | BLOCKED carries no number either; the e2e test pins that `no_pv` never gives `pv_tomorrow` OK |
| CCR-2 (the runtime self-test WARN on the status entity) | DEFERRED | the WARN stays in diagnostics |
| CCR-policy-01 (additive refusal codes) | DEFERRED | every rule already refuses |
| CCR-ui-2 (the runner's echo of a failing suite on a cp1252 console) | DEFERRED, not Intelligence-owned | run the runner with `-X utf8` |
| ui-1 r3 (the presentation package) | HELD OUT until PR-6 | section 5 |
| No pause control while the package is held out | OPEN, for PR-6 and DP-4 | By the frozen contract a missing pause helper means not paused, with a WARN (`PAUSE_CONTROL_MISSING`), so the runtime keeps publishing SHADOW advice and the owner cannot pause it. Nothing is installed. PR-6 restores the package, and DP-4 must keep the runbook's order: the package installed and the pause helper on before the integration first starts |
| Advice backtest in the capture validator | PENDING | The capture validator's summary field `backtest` stays PENDING. A backtest campaign needs owner decisions, which are OPEN; synthetic decisions are never used on real data. It also needs the TOU readings and tariff payloads at each issue time, which a statistics capture does not carry. The summary schema is pinned by the data-quality suite. Wiring it needs DP-1 and a capture that carries those readings |
| Runtime cadence against the cycle's validity | RESOLVED in the runtime (SHADOW v0.1 completion); measured under L3 and in the 72 h acceptance | Found at integration: hourly cycles left a result STALE for most of each hour. Refresh before expiry (foundation contract 13.4) recomputes between the slots when less than 125 s of validity is left or an item is BLOCKED `INPUT_EXPIRING`, at most once a tick, under a CPU guard. On the target platform the telemetry poll text moves every 60 s, so the poll-phase-aligned refresh (amendment A23) starts each refresh 3 s after a poll; the stand-in suite, counting from its recorder rows, shows no `INPUT_EXPIRING` and no STALE over three hours at any phase. A missed, late or frozen poll gives at most one STALE cycle per episode (amendment A32: accepted as fail closed, never a wrong number, no staleness rule changed), then the recovery at the next poll plus the settle delay (or the 55 s floor's end), or, when the poll text stops, the tick's own rules, with the dongle items failing closed. A poll text faster than the settle delay no longer postpones the poll-driven step (A33), and no cycle starts inside the settle delay of the newest poll seen (A36; residual: two polls within one settle delay). Remaining: L3 M6 / the 72 h T3 and T9 measure it on the real Core (T3 / R3: STALE in at most 1 % of minutes, runs of at most two ticks). A50 lowers the CPU a cycle takes (the engine's exact profile memo and the runtime's reuse of the parsed history) without changing the CPU guard, the cadence or any rule; R3 and T9 read the target's own figure |
| Tariff report cadence | OPEN (a live fact) | The tariff entities' report cadence is not known yet; an I-D6 limit has to cover it, within the 900 s ceiling, or export and Dump advice stay BLOCKED. The import rates read the day events in the recommended form [current day, next day] (A38 Part B, A42), and the merged table is as old as its oldest contributing event, so each event's cadence counts; a site adds the previous-day event only once its cadence is known to stay within its I-D6 limit. The runbook's R5 and T11 fail while the cadence does not fit (fail closed). A coverage-based tariff freshness rule would need an independent review and the owner; none is proposed |
| The merged import table refused or never fresh (RT4-1) | OPEN for part (d) only, decided on the 72 h data | A42 decided parts (a) to (c). (a) The runbook's go / no-go row R5, the 72 h row T11 and the 7-day row Q6 require the import table accepted and fresh after the next-day publication; each reads the import table's own code: a computed cycle without `TARIFF_VERIFIED` (before the next-day publication, with neither it nor `TARIFF_COVERAGE_SHORT`) counts as an input fault although it blocks nothing, T11 counts computed cycles only (A45), and the cheap-run codes that stand beside `TARIFF_VERIFIED` on a verified table naming no cheap run (a flat or smooth tariff) describe its shape and count as no fault (A47). (b) The diagnostics download shows the runtime's refusal code: `source_notes` is no longer redacted, each note a contract key and a constant code (a suite pins it on every refusal path). (c) The recommended form maps the two day events [current day, next day]; the three-event form is allowed, a site adding the previous-day event only once its cadence is known to stay within its I-D6 limit. With A41 the charge-window items carry INFO `CHARGE_WINDOW_NOT_PRICED` whenever no price check covered the window, so a missing cross-check is visible on the items too. Open, not in v0.1: (d) whether a refused, gapped or stale mapped import table BLOCKs the charge-window items instead of the TOU-only WARN (INTELLIGENCE_HA_RUNTIME risk 8) |
| One rate event under two table keys (RT4-2) | RESOLVED (A42) | `parse_entity_map` and `site-check` (exit 1) refuse the same entity and attribute named by any two of `tariff.import_rates`, `tariff.export_rates` and `tariff.events`, every day event of a list counted, by field path only (INTELLIGENCE_HA_RUNTIME 4.2). The same entity under another attribute is accepted; a site whose import and export rates are one attribute is refused (fail-closed) |

## 5. The held-out presentation package (PR-6)

`home-assistant/packages/ecco_intelligence.yaml` (the pause helper and the watchdog) and its behaviour suite
`home-assistant/tests/test_ecco_intelligence_package.py` are held back: they ship with PR-6, the single post-export entry.
Until then:

- the card shows the watchdog and the pause as not installed;
- the runtime reports `pause_control: MISSING` with the WARN `PAUSE_CONTROL_MISSING`. A missing pause control means not
  paused (the frozen contract), so the runtime still publishes its SHADOW advice, with numbers wherever an item is OK.
  The owner has no pause control until PR-6 restores the package. This is an open item for PR-6 and DP-4 (section 4);
- the dashboard's registration steps still begin with installing the package (PR-6 restores it), but a comment line above
  them (IP-4b) marks the package held out until PR-6 and says the dashboard is not to be registered before then: its pause
  tile, watchdog row and the markdown fallback's pause and watchdog lines read entities that nothing defines until PR-6.

The card suite (`tools/tests/test_intelligence_card.py`) no longer reads either file. One check in it fails as soon as either
file comes back. Its package section moved out because the package suite pins every one of those checks. PR-6 must restore
these card-suite checks, which the package suite does not pin:

1. the reserved fallback and recovery token scan over the package and its suite (four tokens of the card suite's list are
   missing from the package suite's list);
2. the scan for the `custom:` form of the 3D card's tag over both files (the package suite bans only the full name);
3. the scan for the two vestigial bare object ids over both files (the package suite bans only the full entity ids);
4. the tariff-placeholder scan over the package, and the prototype-entity-id scan over the package's comments and over its suite;
5. the private-value scan over both files: workstation paths, e-mail addresses, private addresses, MAC addresses and
   13-digit numbers;
6. the site-render check that the package renders byte-identical for the default, a renamed-slug and a supplier site, and that
   the package is in the render set.

PR-6 also brings the chain entry with its fingerprint. The fingerprint depends on the entry before it, so it is recomputed when
PR-6 is built.

## 6. What PR-5, PR-6 and the owner's decisions still need

- **PR-5 (built on its own branch; merges after PR-3).** The deploy route is decided (DP-4b, below). It is
  `tools/deploy-ha-kit.ps1` (Plan / Install / Upgrade / Rollback / Uninstall of exactly the files of a verified kit, kit
  equivalence to the L3-tested kit, staging under `/config/ecco/staging/`, verified backups, one rollback routine,
  nothing deleted, no restart), `tools/place-ha-site-file.ps1` (the site file only, with a verified backup and a
  read-back), `deploy-ha.ps1 -Target Test|Production` and `-Action Retire`, the `/config` symlink handling (A26), the
  per-segment symlink refusal (A15), the single-file route's refusal of `/config/ecco/intelligence/**` and
  `/config/ecco/staging/**`, `docs/user/intelligence-deploy.md`, and the L3 harness (`tools/ha-test-instance/`). It is a
  safety-gate change: the full gate, an independent review and an L3 pass before it merges. The runbook marks its
  commands "lands with PR-5".
- **PR-6 (built on main after PR-3).** The single post-export entry:
  - the manifest stanzas;
  - `VERSION.yaml`;
  - its documentation, and the removal of the "lands with PR-5" markers in the runbook and this guide;
  - the presentation package with its suite and the card checks of section 5, which also restores the owner's pause
    control (section 4), with the watchdog's `WATCHDOG_MAX_AGE_S` at 1200 s derived from the runtime's constants;
  - the raise-only reserve helper in its own package (`ecco_intelligence_prefs.yaml`) with its own suite.

  The 3D Overview link is dropped (an engineering default of SHADOW v0.1; UI_DESIGN section 14), so PR-6 does
  not touch the Overview. It is serialised after PR-1 to PR-5.
- **The owner's decisions DP-1 to DP-5.** Opaque ids, like I-D1 to I-D9: each line says what the id decides and its
  status. A site records its decided values in its own site file, never in this repository.
  - DP-1 (OPEN): the source of each decided input. None is proposed; each needs a fresh reading, and no placeholder
    fallback is used.
  - DP-2 (OPEN): the battery capacity and efficiency figures and their checks (I-D3, I-D4, I-D5).
  - DP-3 (OPEN): the freshness limits and the ceiling (I-D6, including the keys added at integration and the TOU gate
    readings). A limit has to cover how often its entity reports: the stand-in suite gives the tariff tables, reported
    5 minutes before a cycle, the 900 s ceiling, because a 300 s limit leaves a result resting on them no validity at
    all. The PROPOSED limits are split by key class: 300 s for dongle keys, 600 s for bridge-fed keys, 900 s for
    tariff tables (`site_decisions.PROPOSED_ANSWERS`, text only). `site-check` lists every mapped key that still has
    no limit.
  - DP-4a (OPEN): the restart policy, with the caveat that a Home Assistant restart of more than about 5 minutes
    latches.
  - DP-4b (decided): the deploy route is PR-5, the established deploy tool extended for this integration only (an
    explicit path allowlist, staging, verified backups, hash and read-back checks, a tested rollback, no manual copy);
    its merge still needs its gates.
  - DP-4c (decided for L3): L3 is an isolated test Home Assistant on the production versions, with no production
    secrets, no device connection and no inverter write; L4 is the site after the install.
  - DP-4 (OPEN): the production install and its restart, each separately gated (runbook G1).
  - DP-5 (OPEN): any real ASSISTED or AUTONOMOUS mode.
  - The install go/no-go checklist is the runbook's section 1; the real-data capture has its own go/no-go
    ([REAL_DATA_CAPTURE_KIT.md](REAL_DATA_CAPTURE_KIT.md)).
- **Still blocked or pending.**
  - any live install;
  - the real-data capture run;
  - real-data accuracy and the I-D8 counter check;
  - drift, calibration and the outcomes store (v0.2);
  - an options flow;
  - real writes of any kind.

**Building PR-1 to PR-4 from the combined source (found at IP-4b).** The combined source holds all four slices, and five
files carry the content of more than one of them. Checking them out whole from it gives an invalid head before PR-4: a
roots file that names a directory the head does not have stops the test runner (`test root ... is not a directory`,
exit 2), so CI would build no test matrix. Each PR edits them for its own slice instead:

| File | PR-1 and PR-2 | PR-3 | PR-4 |
|---|---|---|---|
| `tools/offline_test_roots.txt` | as on main (no new root) | adds `custom_components/ecco_intelligence/tests` (the foundation's F-B1 version) | adds `ecco_autonomy/tests` (the combined source's version) |
| `README.md` (the roots sentence) and `intelligence/README.md` (the boundary roots) | as on main | the F-B1 versions | the combined source's versions |
| `CHANGELOG.md` | main's `CHANGELOG.md` (every entry of main kept) plus the `[Unreleased]` line of each PR merged so far, its own included | the same | the same (all four lines) |
| this guide | not included | without the `ecco_autonomy` rows and commands | the combined source's version |

Every other file of a PR is one the Intelligence work adds or changes, and it is taken from the combined source
unchanged. Each head is built on main: a file the Intelligence work does not touch is main's, never the combined
source's, so a head never removes or reverts anything main gained after the combined source branched from it (main's
dashboard preservation gate and its deploy-tool changes, for example). Each head's equality check therefore compares
only the paths the Intelligence work adds or changes with the combined source, excludes these five files until PR-4,
and leaves every other path equal to main's. After PR-4, main holds the combined source's version of every path the
Intelligence work changed and its own version of every other path. The texts in PR-1 and PR-2 do not point at this
guide, which lands with PR-3.

## 7. Rules for whoever continues

- This guide replaces any handover file; do not add a `HANDOVER_*` file.
- New commits only, signed off (DCO). No force-push, no history rewrite.
- A change to a frozen interface, the null rule, `ITEM_GATES` / `REQUIRED_*`, the freshness limits or ceiling, the default
  acceptance, `REAL_WRITES_POSSIBLE`, a boundary suite or the platform allowlist needs an independent adversarial review AND the
  owner (foundation contract, section 8).
- Keep every value synthetic in public files: no site values, no private addresses, no workstation paths.
