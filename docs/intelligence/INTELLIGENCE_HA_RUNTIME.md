# ECCO Intelligence SHADOW runtime for Home Assistant (`custom_components/ecco_intelligence`)

> **Status: SHADOW package source; install kit staged, PENDING DP-4.** This document describes source code and an
> offline-built kit. Nothing is installed, connected to Home Assistant or running anywhere. In this repository every
> Intelligence decision I-D1..I-D9 is **OPEN**; a site records its decisions only in its own site file (section 4). Every
> runtime number marked PROPOSED is an engineering suggestion, **not an owner value**. Real Home Assistant tests: L3 (an
> isolated test instance pinned to the production versions) is decided (DP-4c in the continuation guide); its harness
> lands with PR-5, and the install waits for its pass (runbook G1). L4 is the site itself, after the install.

The integration reads Home Assistant states and recorder statistics, runs the SHADOW cycle
(`intelligence.shadow_cycle.run_cycle`) and publishes the result as read-only `sensor` / `binary_sensor` entities. It applies
nothing: it has no service, writes no foreign state and fires no event. Its code makes no registry call and no HA storage
(`Store`) call. Home Assistant itself does record a few things when the entry is added: the config entry, the eleven
entity-registry entries (each entity has a `unique_id`) and one device-registry entry (the service device from
`DeviceInfo`). Deleting the entry removes them, but Home Assistant keeps the eleven entity ids in the entity registry's
record of deleted entities (by unique id) and gives the same ids back when the entry is added again, a suffixed id
included, for as long as it keeps that record (it purges orphaned deleted-entity records after a retention period;
Home Assistant behaviour, seen on the pinned Core under L3 within minutes; the runbook's section 7 has the recovery from
an entity-id collision). The integration talks to no device, inverter, dongle, database or network.

Related: the contracts it implements are in [`INTELLIGENCE_FOUNDATION_CONTRACT.md`](INTELLIGENCE_FOUNDATION_CONTRACT.md)
(section 13 for the SHADOW v0.1 completion: the grid-charge TOU classification, configuration-poll freshness, the refresh
margin and the raise-only reserve preference), and the install, pause, acceptance, upgrade, rollback and uninstall steps
are in [`INTELLIGENCE_SHADOW_INSTALL_RUNBOOK.md`](INTELLIGENCE_SHADOW_INSTALL_RUNBOOK.md).

## 1. Option scoring (summary of the phase-1 choice)

Phase 1 chose a custom integration. This table summarises the reasons as the runtime stream applied them. Scores run from
0 (poor) to 2 (good).

| Option | Read-only can be enforced and tested | No third-party requirement | Offline testable (L1/L2) | Reversible install | Fits HA updates | Total |
|---|---|---|---|---|---|---|
| **Custom integration, sensor / binary_sensor only (chosen)** | 2 (AST allowlist of HA imports, no platforms that write) | 2 (`requirements: []`) | 2 (pure runtime plus a stdlib stand-in of HA) | 2 (one directory, hash-verified kit, backup and rename) | 1 (HA API drift: L3 later) | **9** |
| pyscript / AppDaemon app | 1 (a general scripting host that can call services) | 0 (needs the add-on or a HACS package) | 1 | 1 | 1 | 4 |
| Add-on container that posts states over the REST API | 0 (a token with write rights) | 1 | 1 | 1 | 2 | 5 |
| YAML templates plus `command_line` | 1 | 2 | 0 (logic in Jinja / shell) | 2 | 2 | 7 |
| Offline batch, results imported as a file | 2 | 2 | 2 | 2 | 2 | 10 (but it is not a live SHADOW: no freshness, no supervision) |

The offline batch scores highest, but it cannot check live freshness, so it does not meet the SHADOW goal. The custom
integration is the best live option.

## 2. Design

```
custom_components/ecco_intelligence/
  __init__.py        async_setup_entry / async_unload_entry; NO module-level homeassistant import; imports
                     coordinator.py in Home Assistant's import executor; the release of every executor job
  const.py           DOMAIN, MODE = 'SHADOW', PLATFORMS = (sensor, binary_sensor), the PROPOSED runtime constants
  coordinator.py     start-up gates, the one-minute tick, the poll-driven step, the schedule and refresh cadence, the
                     cycle in the executor, publishing, diagnostics
  entity_base.py     the shared entity mixin (contract ids, one device, payload -> state and attributes, unrecorded set)
  sensor.py          status (ENUM), the 7 advice items / forecasts, accuracy, data_quality (ENUM)
  binary_sensor.py   fresh
  config_flow.py     one confirm step, no fields, a single entry
  diagnostics.py     redacted diagnostics (async_redact_data)
  runtime/           NO homeassistant import at all (checked):
    sources.py         HA state views -> ecco_core Snapshot + SiteReadings; the strict site-file entity map
    history_source.py  recorder statistics rows -> intelligence.history.History (a read parsed once into an image, A50)
    engine_link.py     bridge.advisory_live_inputs -> CycleInputs -> run_cycle (injectable for tests); CPU time per job;
                       the parsed history reused between cycles (HistoryReuse, A50)
    gates.py           mode, zone and clock changes, site file, vendor manifest, versions
    selftest.py        PASS / INFO / WARN / FAIL checks
    store.py           the only file-system module; the only writer (state/ only)
  _vendor/           GENERATED by tools/build_ha_integration.py only, never committed
```

### 2.1 Start-up gates

Setup is refused with `ConfigEntryError` when the mode is not the constant `SHADOW`. If any other gate fails, the
integration publishes `SELF_TEST_FAILED`, with all nulls and the failing checks in `self_test`, and it computes nothing
until the entry is reloaded.

| Gate | Check |
|---|---|
| `MODE_SHADOW` | `const.MODE == advisory_contract.MODE == 'SHADOW'`, and the config entry stores no other mode. Anything else refuses setup |
| `TZ_EUROPE_LONDON` | `ZoneInfo('Europe/London')` loads; the BST / GMT offsets either side of 25 Oct 2026 and 28 Mar 2027 are right; `periods.period_profile` gives 25 h and 23 h |
| `SITE_FILE` | `<config>/ecco/intelligence/site.local.json` exists, is at most 256 KiB, is UTF-8 JSON without a byte-order mark whose top level is a JSON object, and holds no non-finite number (NaN, Infinity, or a literal beyond the double range such as `1e999` or an integer too large for a double). The FAIL text says which rule refused the file, never a value: "a UTF-8 byte-order mark" (Windows PowerShell 5.1 writes one for `-Encoding utf8`; save the file without it, RR1-5), "not valid JSON" with the exception type (a syntax error, a non-UTF-8 byte, a nesting too deep to read), "not a JSON object" with the top level's JSON type, or "a non-finite number" (A49) |
| `SITE_DECISIONS` | the `decisions` block loads with `DecisionSet.from_mapping(block, source='site_local')`. That is the only way the runtime obtains decisions. An unknown key FAILs; an INVALID decision WARNs and BLOCKs in the cycle; no block at all WARNs and leaves every decision OPEN |
| `SITE_ENTITY_MAP` | the `shadow_runtime` block (section 4) is strict: unknown keys, malformed specs and invalid entity ids FAIL (a `<placeholder>` left in counts as invalid). No block WARNs: nothing is mapped and every gated item BLOCKs |
| `SITE_HISTORY_SOURCES` | the V1 `sources` / `forecasts` give the statistic ids. Invalid ids, the example's placeholders among them, are never queried (WARN) |
| `SITE_HINT_IGNORED_*` | `site.user_reserve_soc_pct` / `technical_min_soc_pct` are ignored (INFO). Reserves come only from I-D1 / I-D2 |
| `VENDOR_MANIFEST` | the in-package `VENDOR_MANIFEST.json` matches the sha256 of every vendored module and integration file in place. The source tree is not a kit and FAILs here by design |
| `STORE_WRITABLE` | `state/` can be created inside an existing `ecco/intelligence/`, and `store_meta.json` and the scorecard initialise |
| `ENGINE_IMPORT` | the vendored engine imports; its version is recorded |
| `VERSIONS` (INFO) | the Home Assistant version, HA's own minimum Python version, and a feature probe of the running Python (see section 7) |
| `ENTITY_IDS` | every entity was registered under its contract id. A different id, for example a `_2` suffix, FAILs. So does a contract entity that Home Assistant never added once the platforms are set up (for example one disabled in the entity registry): the status entity carries `mode` and `applies_nothing`, so a missing entity stops all computing. The text names contract keys only |
| `ENTITY_WRITE` | a state write of one of its own entities raised (Home Assistant refuses, for example, an ENUM value outside its options). Each entity is updated in its own guard, so the others still follow the envelope; the failure FAILs the self-test and gives `SELF_TEST_FAILED` |
| `PAUSE_CONTROL` | the pause helper is readable. A missing helper WARNs: not paused, `pause_control: MISSING` |
| `RECORDER_READ`, `STORE_RECORD` | WARN when a statistics read or a scorecard step fails. There is then no history and the quality layer BLOCKs |
| `CPU_BUDGET` (at run time) | WARN while refreshes are suspended by the CPU guard (section 2.2); PASS again once the rolling hour is back within the budget |

**No site value in a check text.** A check's text reaches the status entity (`self_test`, `blockers`) and the diagnostics
download, so it names a code, a field path (built from the contract's keys) or an exception type only. It never carries an
entity id, a key, a record reference or a source name from the site file, and never an exception message (an OS error
message carries a path). The offending value goes to one debug log line (`custom_components.ecco_intelligence.coordinator`),
which is shown only when the owner turns on debug logging. The same rule holds for runtime exceptions (only the type is
published).

### 2.2 Schedule, refresh cadence, time budget, staleness

Every value named here is a constant in `const.py` (section 6); the rules are the contract's section 13.4 as the
coordinator implements them.

**Two kinds of cycle.**

- **SLOT:** every full hour and 21:30 Europe/London (the 21:30 slot is computed with ZoneInfo, so it does not depend on
  Home Assistant's own time zone setting). A slot cycle reads the recorder statistics and the scorecard metrics, and
  records the scorecard once per slot. The first cycle runs `PROPOSED_STARTUP_GRACE_S` after `homeassistant_started`, or
  after setup when HA is already running.
- **REFRESH:** the same cycle between the slots, from fresh Home Assistant states and both poll-text liveness times, with
  the slot's cached recorder rows and metrics (the history parsed from those rows is reused while their content is
  unchanged: "The parsed history", below). It writes nothing to the state store. Cached rows that end before the slot's
  hour (the recorder compiles an hour shortly after it ends) are read again once, `PROPOSED_HISTORY_CATCHUP_S` after the
  slot; a failed recorder read is retried by a refresh at most every `PROPOSED_RECORDER_RETRY_S`.

A refresh changes no limit, no validity and no rule: the engine decides every value, and the 900 s validity ceiling, the
null rule and every gate stay the engine's.

**Refresh before expiry (the tick's rules).** At a tick a refresh starts when the published computed result

- has less than `REFRESH_MARGIN_S` = **125 s** of validity left (two ticks plus the 5 s tick margin: the shortest validity
  that is shown without a gap; it equals the engine's `shadow_cycle.REFRESH_MARGIN_S`, and a drift test compares them);
- holds an item or forecast the engine BLOCKED `INPUT_EXPIRING` (an OK item valid for less than the margin at compute time
  is withheld until its inputs are refreshed; since it no longer shortens the envelope's validity, the validity alone
  would keep it withheld until the envelope nears its end); or
- was published STALE (after the back-off below).

At most one cycle starts per `PROPOSED_REFRESH_FLOOR_S` (55 s: one per tick); a slot cycle wins when both are due. Without
polls the implied ceiling between two cycles is 900 - 125 + 60 = **835 s**.

**Poll-phase-aligned refresh (A23).** The dongle's telemetry poll text moves about every `PROPOSED_POLL_INTERVAL_S` (60 s
on the target platform), and the 60 s tick holds a phase against it that follows the last cycle's end (the quiet cycle,
below: near-fixed in steady operation). An item resting on a dongle input is
valid for at most the 180 s liveness bound less the liveness age, so a refresh started more than 55 s after a poll would
withhold every such item (`INPUT_EXPIRING`), episode after episode. So the coordinator follows the poll:

- **One state listener** (`async_track_state_change_event`) on the entity the site file maps for
  `liveness.dongle_poll_changed_at`; none when that key is not mapped. It is removed on unload, also before Home Assistant
  has started.
- **A new poll** is a poll text that differs from the last one the listener saw. A replayed text, `unavailable`,
  `unknown`, `Waiting` (no NTP time yet) and an attribute-only change are not new polls.
- **The poll-driven step** runs `PROPOSED_POLL_SETTLE_S` (3 s) after a new poll (`async_call_later`, at most one pending;
  unload cancels it), so the rest of that poll's entity writes land first. A later poll never moves a pending step later:
  it keeps the earliest due time (A33), so a poll text that changes faster than the settle delay cannot postpone it, and
  a step deferred to the floor's end moves only earlier, to the new poll's step, where the floor applies again (a slot
  that fell due meanwhile starts there). It starts a due slot
  cycle, or a refresh when the published result is STALE (after its back-off), has less than `POLL_REFRESH_THRESHOLD_S` =
  margin + one poll = **185 s** of validity left (so the margin is never entered between two polls), holds an item
  BLOCKED `INPUT_EXPIRING`, or holds an item BLOCKED for an input reason (a blocker among the quality rules whose inputs
  name a live signal or site reading, `INPUT_NOT_FRESH`, `TOU_*`, `CHARGE_WINDOW_*`, `TARIFF_*`,
  `PREF_RESERVE_RAISE_UNKNOWN`, `CALLER_FRESHNESS_DISAGREES`: recovery after a transient input fault takes one poll, not up
  to the 835 s ceiling). A code outside that set (an OPEN decision, the history) leaves the item to the tick's rules.
- **Floor, coverage, in flight.** A step inside the 55 s floor is deferred to the floor's end, never dropped. No step is
  armed while a cycle is in flight (the quiet cycle, under "Timers" below): a step pending at the cycle's start is
  cancelled with its due time kept, a poll meanwhile is noted and keeps the earlier due time (A33), and the step is armed
  when the cycle ends, at max(its due time, now) (after an engine thread abandoned at the time budget, when that thread
  ends). So a step that comes due during a cycle waits for its end, as the in-flight wait did, and a poll noted meanwhile
  is served by it. A cycle that started after the poll was seen has read it already,
  so the step is covered (unless a slot is due): by the settle hold below, such a cycle started at least the settle delay
  after that poll. So is a cycle that holds its snapshot for that poll (the settle hold at the snapshot, below), from the
  moment the hold begins.
- **The settle hold (A36): no cycle starts inside the settle delay of the newest poll seen.** The rule sits at the one
  place a cycle starts (`_maybe_start`), so it applies to every trigger. A cycle whose start would fall before the newest
  poll seen plus `PROPOSED_POLL_SETTLE_S` is held once to that moment, on the one pending step: a step already pending by
  then serves it (a poll-driven step starts whatever the tick would), otherwise the step is armed there as a settle hold.
  The cases are exactly these:
  - a refresh the tick asks for after STALE, also after the STALE back-off (a missed or late poll just before the tick);
  - the exception retry the tick asks for;
  - the tick's exception to its hold (covered by the same rule; with a poll just seen a step is pending, so it does not
    fire then);
  - a poll-driven step that a newer poll kept (A33 never moves a pending step later): a step deferred to the floor's end
    when a newer poll arrives in the last 3 s of the floor, and a step under a poll text faster than the settle delay;
  - a step armed when a cycle in flight ends inside the settle delay of a poll noted while it ran.

  The hold is one-shot (the held step starts without a second hold) and at most `PROPOSED_POLL_SETTLE_S` (3 s). A later
  poll never re-arms it, so a poll period below the settle delay cannot starve it, and it never applies when no poll was
  seen within the settle delay (a frozen dongle keeps the tick's own rules). A held cycle is a poll-driven start in
  `cycle_stats` (trigger `POLL`, `poll_age_s` 3). Every hold is counted in `settle_holds`, and a start made by a step
  armed as a settle hold in `settle_held_starts` (a hold that an already pending step serves starts as that step). The
  residual, documented and not fixed: two polls within one settle delay (an abnormal sub-settle poll period). The
  held cycle then starts inside the second poll's settle delay (counted in `settle_residual_starts`), and a cycle the
  tick asked for can start up to two settle delays after the first of those polls.

  The same hold at the snapshot. A cycle starts in one event-loop step and reads its snapshot a step or two later (the
  cycle's steps, below), so a poll text can arrive in between, after the start's check, at any start phase (the tick's
  refresh after STALE or its exception retry, a step deferred to the floor's end, a resumed step). When a new poll text
  was seen since the cycle's start (the listener's poll count moved) and its settle delay is still running, the
  snapshot is held once to the delay's end (`asyncio.sleep` in the cycle task, at most `PROPOSED_POLL_SETTLE_S` and never
  past the cycle's deadline; counted in `snapshot_holds`, its time in the cycle's `total_s`). The snapshot then reads
  the rest of that poll's writes, with the delay's end as the cycle time, and the cycle covers that poll: its own step,
  due at the same moment, starts no second cycle (a hold cancelled by an unload or a shutdown covers nothing). A cycle
  is held at most once at its start and once at its snapshot (at most two settle delays in all), and a later poll
  re-arms neither. The residual above has a second form here: when the second of two polls within one settle delay
  arrives while the snapshot is held, the snapshot is read inside its settle delay (counted in
  `snapshot_residual_reads`). That poll is not covered, so its step comes at the floor's end and refreshes when a
  refresh is due. A hold cut short by the cycle's deadline (the time budget) is read inside the settle delay too: it
  also counts in `snapshot_residual_reads` and covers nothing (RR-N1).
- **The tick holds back while polls arrive** (a new poll seen within `PROPOSED_POLL_ACTIVE_S` = 1.5 polls = 90 s): it starts
  no slot cycle (the next poll-driven step does, so every slot result is phased like a refresh: up to about one poll plus
  3 s after the slot boundary, also for the first cycle after the grace and after an unpause) and no refresh for validity
  or `INPUT_EXPIRING`, unless the published envelope would go STALE at the next tick before the next expected poll-driven
  step. A badly phased tick therefore never replaces a good result with a worse one. (A refresh after STALE and the
  exception retry still start at a tick, except inside the settle delay of a poll just seen, where the settle hold moves
  them to the delay's end.)
- **The fallback.** When the poll text stops moving, the tick resumes its own rules above unchanged, so a frozen dongle
  fails closed: dongle items BLOCKED (`INPUT_NOT_FRESH`), history-only items keep their numbers (V-4, section 2.3), no
  `CALLER_FRESHNESS_DISAGREES`.
- **A missed, late or frozen poll costs at most one STALE cycle (A32).** While the hold still expects a poll-driven step,
  the published result can reach the tick's publish horizon: one poll skipped or late, or the first ticks of a freeze, at
  some phases. That tick then writes STALE (every item null, `last_good` kept) and starts the refresh that replaces it,
  so the STALE lasts one cycle; when the tick falls inside the settle delay of a poll just seen, that refresh is held to
  the delay's end (A36), so the STALE row stands up to 3 s longer. This is accepted as fail closed (STALE nulls every
  item, stricter than per-item blocks; never a wrong number), and no staleness rule changes. After the episode come the
  fallback (a freeze) or the recovery:
  the cycle at the next poll plus the settle delay, deferred to the 55 s floor's end when the tick's refresh started less
  than 55 s before that step (so at most 55 s after the poll), restores every dongle item's number.
- **Supervision exposure when the polls stop (A31(b), A36 RR-1).** Supervision is not in any item's validity (contract
  13.4), so a published OK export or Dump item can outlive a supervision lapse until the next compute. While polls arrive
  that is about one poll plus the settle delay plus the compute time. When the polls stop, the dongle items go
  `INPUT_EXPIRING` at the first tick after the last poll plus `PROPOSED_POLL_ACTIVE_S`: at most about 150 s after the last
  poll plus the compute time, and never past the item's own validity (at most 180 s after its poll). Any ASSISTED use of
  export or Dump validity still needs supervision in the validity first (a separate owner decision).
- The pause helper, the self-test, the second-run guard, the CPU guard, the time-budget bar and the refresh switch apply
  to the poll-driven step and to a held cycle unchanged.

In the stand-in Home Assistant (L2), counted from the recorder rows (every write, not only the state after each cycle),
every refresh and slot cycle then starts 3 s (at most 4 s) after its poll at every phase offset, with one cycle per poll
(60 an hour) and no `INPUT_EXPIRING` or STALE over three simulated hours. A poll 90 s late, one skipped poll (120 s), a
150 s gap and a freeze, each swept over seven phase offsets, give at most one STALE status row per episode, replaced by a
computed status at the same tick or, inside a poll's settle delay, at the delay's end (A36), no number past its inputs'
bound, and the recovery above. L3 measures the same on the
pinned Core image, and the 72 h acceptance logs the phase (runbook T9); T3 / R3 allow STALE in at most 1 % of minutes, in
runs of at most two ticks (A13).

**Failures and guards.**

- **Second-run guard:** no cycle starts while one is in flight; an engine thread abandoned at the time budget counts as in
  flight until it ends (it keeps the guard but not the quiet cycle: the tick is attached again when the abandoned cycle
  ends, so the STALE and pause rules run every minute while the thread hangs, and a step noted meanwhile is armed when
  the thread ends). Skips are counted (`skipped_in_flight`, `refresh_skipped_in_flight`).
- **Time budget:** `PROPOSED_TIME_BUDGET_S` covers the whole cycle. When it is exceeded the cycle publishes
  `SELF_TEST_FAILED` with `CYCLE_TIME_BUDGET`, the last values move to `last_good`, the late result is discarded, and no
  refresh starts before the next slot (never while the abandoned thread runs).
- **Exceptions:** every exception gives `self_test_failed_envelope` with the reason `RUNTIME_EXCEPTION` (only the type is
  published), the last values only through `with_last_good`, and one retry `PROPOSED_EXCEPTION_RETRY_S` after the failed
  start; after that slot cycles only, until a result is published again.
- **STALE back-off:** a result published STALE as soon as it was computed (valid for less than one tick) holds the next
  refresh back 60 s, doubling to 300 s (`PROPOSED_STALE_BACKOFF_S`), reset by the next result published as computed.
- **CPU guard:** `engine_link.compute` measures each engine job's thread CPU time (`time.thread_time`). While the rolling
  hour's total exceeds `PROPOSED_CPU_BUDGET_S_PER_H` (180 s), refreshes are suspended (self-test WARN `CPU_BUDGET`, counter
  `refresh_suppressed_cpu`); slot cycles continue. The only effect is STALE, which fails closed. The guard's headroom is
  tracked explicitly, never inferred from STALE (A49): the diagnostics show `cadence.cpu_s_rolling_hour` (the guard's
  own sum), `cadence.refresh_suspended_cpu` and the counter, and every `cycle_stats` row carries its run's `cpu_s` and
  `started_at`, so the rolling hour can be recomputed over every run a download keeps. The install runbook reads them
  in its go / no-go row R3 and its 72 h row T9 (`refresh_suppressed_cpu` 0, `cadence.cpu_s_rolling_hour` p95 at most
  120 s per hour). A50 lowers the CPU a cycle takes without touching the guard: the engine keeps an exact memo of its
  slot profiles between cycles (contract 13.4) and the runtime reuses the parsed history (below). The 180 s budget, the
  cadence, the floor and every freshness, expiry and fail-closed rule stay exactly as they are.
- **In the executor:** the recorder read runs through the recorder's own executor; the scorecard read, the history build,
  the bridge and `run_cycle` run through `hass.async_add_executor_job`. `coordinator.py` itself, and through it most of
  the vendored engine (the modules it and the runtime package import; the rest, the engine cycle's own closure, load in
  the start-up gates' executor job), is imported in Home Assistant's import executor (`async_setup_entry` awaits
  `hass.async_add_import_executor_job`; `__init__.py` imports nothing of it at module level). Nothing blocking runs on
  the event loop. Every one of these jobs, and the start-up gates' file reads, is held until the event-loop step that
  submitted it has ended (`__init__.released_call`: the job polls a flag the loop sets in its next handle, every
  `SUBMIT_RELEASE_POLL_S`, for at most `SUBMIT_RELEASE_CAP_S`), so the job and the rest of that step never run at once.
  Every one of them also ends with a cool-down: once its target has returned (or raised), the job sleeps
  `SUBMIT_COOLDOWN_S` (0.15 s, more than one 100 ms CPU-quota period of a CPU-limited container) before it completes, so
  the loop-side completion and the cycle's next step start in a fresh quota period, not in the throttled tail of the
  job's own. `recorder_s`, `engine_s` and `store_s` run from each submit to its result, so they include each job's
  release wait and cool-down; `total_s` includes those and any settle hold; `cpu_s` includes neither.

**The parsed history (A50).** The recorder statistics change only at a read (a slot, the one catch-up, a retry), yet
parsing about 32k rows and building the History from them took about 0.08 s of every cycle on a desktop test machine,
about a third of a refresh once the engine's profile memo was in. The first cycle after a read parses it into a
`history_source.StatisticsImage`: the rows as immutable tuples, the row cap's cut and the position of every negative
zero, so nothing it holds can change after the parse. The slot's cache keeps that image instead of the raw read and
hands it to the later cycles. `engine_link.HistoryReuse` (the coordinator's, passed in every job) keeps the History
built from the whole image under a key of the image's exact content (equal only when the rows are bit for bit the same:
`==` alone cannot tell -0.0 from 0.0), the plan, the configuration and the zone. A cycle whose key equals it reuses that
History, cut at its own `now` into a new container (`history_source.truncate`), so it gets exactly what a fresh build
gives; the PV forecast series are copied for every cycle. A changed read always rebuilds: every read drops what is kept,
and any other content, plan, configuration or zone misses the key. A refused read (no statistics) drops it too and gives
no history, as before. Every freshness, age and expiry judgement still runs on every cycle from its own `now`. The
records are shared between cycles, so nothing downstream may change them. The audit: the quality layer and the PV model
only read them, `prepare_history` changes only its own deep copy, the scorecard step reads them, and the kept History
itself never leaves the holder. `tests/test_runtime_history_reuse.py` pins it: a scan of every write to an hour record
or a History index (only `build_history` on the records it creates, `HourRecord.flag`, `History.__init__` and
`quality._prepare` after its deepcopy, and offline-only modules the runtime never imports), a fingerprint of the kept
History before and after every cycle and scorecard step, and a differential run (the same envelopes, History and
diagnostics with and without the reuse, across hours, a refused, a repeated and a changed read). The diagnostics' last
cycle says whether it parsed a read (`history_parsed`) or reused the History (`history_reused`); the counters
`history_parses` and `history_reuses` count them.

**Timers.** The 60 s `async_track_time_interval` tick, the one state listener and at most one pending one-shot (the
poll-driven step or a settle hold, A36): nothing else. The tick samples both poll texts, applies the pause and the
staleness checks, re-renders the payloads and starts a due cycle; it runs on the event loop. All three are removed on
unload.

**The quiet cycle.** While a cycle is in flight (from the moment `_maybe_start` creates its task until the cycle has
ended) no timer of the integration fires and none is created. The tick is detached when the cycle starts
(`ticks_deferred`); a pending poll-driven step is cancelled, its due time kept (`poll_steps_held_busy`); the listener
still notes each poll (its text, time and count) but arms nothing. When the cycle ends (after its last step, or in the
done callback of a task cancelled before its first step), the second-run guard is released and the tick body runs once
as a catch-up (`catchup_ticks`: liveness, pause, self-test, STALE, the re-render and `_maybe_start`, so a slot that fell
due during the cycle starts there; the floor still bars a second refresh). Unless that started the next cycle, the tick
is attached again through `_attach_tick`, the one `async_track_time_interval` call site, so its phase now follows the
cycle's end, and the held step is armed at max(its due time, now) through `_arm_poll_step`'s one `async_call_later`, so
the floor, A33 and A36 apply as before. It is armed unheld, as a step that waited for a cycle in flight was resumed
before the quiet cycle: a settle hold's one-shot mark does not outlive the cycle, so a step that comes inside the
settle delay of a poll seen in the cycle's last 3 s is held once more. This end is the same whatever the cycle's
outcome (`self_test_failed` and `discarded_failed` included), and the tick and the step come back even when recording
the cycle's diagnostics or the catch-up raises. The tick body still runs at least every `TICK_S` + `PROPOSED_TICK_MARGIN_S` (65
s), counted from its last run, because the publish horizon maps every payload as of that moment. Inside a cycle its
deadline is its last run plus `TICK_S`, the moment the tick itself would have come, so the whole
`PROPOSED_TICK_MARGIN_S` before the horizon that last run mapped its payloads to is left for the deadline run's own
latency (asyncio's timeout of the job's wait and the cycle task's next step; their observed ranges are given below),
as it is for a late tick: no number stays on an entity past its `valid_until`. A cycle's first step runs the tick body
unless the tick body started the cycle (the tick, or the catch-up at the previous cycle's end, ran at its start;
`tick_start_runs`; before any job of the cycle, so nothing of the integration computes meanwhile), which puts its next
deadline at least `TICK_S` after the cycle's start. When that deadline comes while the cycle still waits for an
executor job, the job's wait ends there and the cycle task runs the tick body itself, as one of its own steps (not a
timer of the integration), and waits on (`tick_deadline_runs`). Only a cycle longer than `TICK_S` can meet it, so in
steady poll-driven operation (one cycle a poll, jobs of a few seconds), and in every slot cycle measured, the deadline
run never comes and no tick body runs while a job computes. The bound on a deadline run's lateness is the margin
itself, `PROPOSED_TICK_MARGIN_S` (5 s): a run less late than that comes before the horizon of the publish before it.
Probes at a quarter of a CPU with the cadence scaled down (a 6 s tick) and a 23 s slot cycle showed what it costs when
it does come. Its in-window handles (its asyncio timeout and its cycle step, run while the engine computed) took 0.10
to 0.19 s. Over the runs, the deadline run came up to about 1.4 s after its moment (0.067 s, 1.417 s and 0.185 s in one
re-run; 0.02 s at one CPU in the first run) and at least about 3.5 s before the horizon of the publish before it
(4.933 s, 3.583 s and 4.815 s): observed ranges, inside the margin, not a bound. That is a documented residual
(section 7, item 7): a cycle reaches it only after about `TICK_S`, which already breaks the runbook's 60 s cycle
maximum (T5). After an unload nothing is attached or armed again. Home Assistant's shutdown cancels the cycle task but
does not unload the entry, so the cycle's end after that cancel runs the catch-up (it publishes; `_maybe_start` starts
no cycle while Core is stopping), and the tick and a held step come back, as the tick stayed attached through a
shutdown before the quiet cycle. An engine thread abandoned at the time budget keeps the guard but not the quiet
cycle, by design (above, the second-run guard). The tick body therefore works while an engine thread hangs: inside
the cycle at its deadline until the time budget, by the tick after it.

**The cycle's steps (event-loop hygiene).** The tick, the poll-driven step and the start-up callbacks do no cycle work:
`_maybe_start`, the one place a cycle starts, applies the cadence rules, sets the second-run guard and creates the cycle
task with `hass.async_create_background_task(..., eager_start=False)`. The pinned Core starts a task eagerly by default
(its coroutine would run inside the timer's callback up to its first suspension), so this callback only schedules it. The
cycle then runs in short event-loop steps, yielding between them: (1) the pause helper and the self-test; (2) the
snapshot, both poll texts and every mapped state in one step, after the settle hold at the snapshot when a poll text
arrived since the start (A36, above), with the cycle time read in that step, so no state in it is newer than the cycle
time although the cycle started earlier (the start itself, which the floor, the exception retry and `cycle_stats` use,
stays the moment `_maybe_start` started it); (3) the recorder statistics and the scorecard metrics, read at the cycle
time; (4) the engine job, built from that snapshot and submitted; (5) after the engine, the pause helper and the
self-test again, one publish (every changed entity in the same step, so the entities never show a mix of two envelopes)
and, for a slot cycle, the scorecard step; the cycle's end runs the catch-up tick body (the quiet cycle, above). The
liveness times are kept with the snapshot, so a tick body run between two steps (the deadline run inside the cycle)
cannot change the job. An unload or a shutdown cancels the task at whichever step it waits, the settle hold included; a
task cancelled before its first step ends with the outcome `cancelled` all the same (what its end does then: the quiet
cycle, above). Every cadence rule (A23, A33,
A36), the second-run guard, the time budget and the published results are unchanged; A36's hold also applies at the
snapshot, so no state is read inside the settle delay of a poll seen after the start's check (an eager start read its
states in the start's own step and had no such window), except in the two residuals counted in
`snapshot_residual_reads`: a second poll during the hold, and a hold cut short by the cycle's deadline (RR-N1). `tests/test_runtime_loop_steps.py` pins the steps, their order,
the results with and without the yields and the hold at the snapshot.

The rule these steps serve, checked under L3: in an asyncio debug session, at a quarter of a CPU and at one, no callback
attributable to the integration takes 0.1 s or more (asyncio's `slow_callback_duration`). In a debug session asyncio
records the creating stack of every future and handle, checking the source file of each frame; each such check hands the
GIL to a busy thread, so while the engine (or an import) computes, every future the loop creates waits for its turn.
Before this layout the poll-driven step's timer ran the start of the cycle eagerly, up to and past the engine submit,
and took 0.155 s and 0.126 s under L3, and the setup step that imported `coordinator.py` took 0.199 s. On a desktop test
machine in debug mode the same two handles took about 0.135 s and 0.16 s; with the steps but without the held submit,
the step that submits the engine job still took 0.13 to 0.21 s there, and with it 4 ms. Home Assistant shows the
integration's scheduled work by name: the cycle task is `CYCLE_TASK_NAME` (`ecco_intelligence_shadow_cycle`, shown in
full in a slow-callback line), the tick's interval timer is named `TICK_JOB_NAME` and the poll-driven step's one-shot is
a `HassJob` named `POLL_STEP_JOB_NAME`. asyncio shortens a job in such a line to its first 13 and last 14 characters
(`reprlib`). The poll-driven step's line shows `_run_async_call_action(<HomeAssistant RUNNING>, <Job
ecco_int...ntelligence>>>)` (the coordinator's own repr ends the job's text). The tick's handle holds the Core's
`_TrackTimeInterval._track_job`, named `ecco_intelligence tick: track time interval 60.0 <the tick's repr>` on
`_TrackTimeInterval._interval_listener`, so its line shows `_TrackTimeInterval._interval_listener(<Job
ecco_int...nt.py:1610>)>>)`: the tail is the end of the tracker's own repr, whose next timer handle was created at
`helpers/event.py:1610` of the pinned Core.

A probe on the pinned image (one-shot containers at a quarter of a CPU and at one, the real Core helpers, the real engine
computing in the executor) then found that any timer of the integration that runs while an executor job computes can
take 0.1 s or more at a quarter of a CPU: every new handle, future and task captures its stack and checks its source
files, each check hands the GIL to the computing thread, and the container's CPU quota is throttled most of the time
while the engine runs (and the worker's full garbage collections stop everything). The poll-driven step, the tick
(the Core's interval re-arm plus the tick body) and the listener's one-shot inside the dongle's own write all reached
0.4 s or more, and a tick inside the job window came back every minute (the tick held a fixed phase against the polls).
After the job, its completion and the cycle's last step landed in the throttled tail of the quota period (up to
0.08 s). Hence the quiet cycle (no timer of the integration exists while a job can compute) and the cool-down (the
completion starts in a fresh quota period). The slow-callback lines the integration can now give: the cycle task's
steps (`<Task ... name='ecco_intelligence_shadow_cycle' coro=<EccoIntelCoordinator._async_run() ...>`, in full), which
run while a job computes only at the tick body's deadline (a cycle longer than `TICK_S`), at the time budget or when the
task is cancelled; asyncio's own timeout of a job's wait (`<TimerHandle when=... Timeout._on_timeout()
created at .../asyncio/timeouts.py:...>`, made by `asyncio.wait_for` in the cycle task, unnamed), which fires only at
that deadline or at the time budget, both while a job computes; the settle hold's `asyncio.sleep` timer
(`_set_result_unless_cancelled(<Future pendi...>, None)`), which runs before any job of its cycle; the tick and the
poll-driven step (above), which never run while a cycle is in flight; the release handle (`<Handle _release([True])
...>`), which runs before its job starts; and asyncio's completion of each job (`_chain_future.<locals>._set_state`),
which runs after the cool-down.

**Publish horizon (IP-4b).** What is written stays on the entities until the next write, at the latest the next run of the
tick body: the tick, the run at a cycle's first step and the catch-up at its end or, inside a cycle longer than
`TICK_S`, its deadline run `TICK_S` after its last run (the quiet cycle, above), at least every `TICK_S` +
`PROPOSED_TICK_MARGIN_S`.
Every publish therefore maps the envelope with `to_entity_payloads(env, now + TICK_S + PROPOSED_TICK_MARGIN_S)`, so an
item that would expire before the next tick has no number when it is written, and `binary_sensor.ecco_intel_fresh` is
never on past the result's `valid_until`. The null rule holds on the entities at every moment, not only at a tick. The
card re-checks `valid_until` with the browser clock as well.

**Per-entity writes and the recorder (A17).** Only the entities whose payload changed are written, plus any whose last
write raised. A refresh changes `generated_at`, so it writes all eleven: about 11 state writes per published cycle, 660 an
hour at one cycle per poll (about 15.8k recorder states rows a day). Every entity class keeps the contract's
`UNRECORDED_ATTRIBUTES` and the timestamp-only attributes (`generated_at`, `valid_until`, `next_run_at`;
`TIMESTAMP_ONLY_ATTRIBUTES`) out of the recorder, so a refresh whose values are unchanged adds a states row per entity but
no new attributes row. The published state and attributes stay exactly `to_entity_payloads`; only what the recorder
stores changes.

**Staleness.** A computed result whose `valid_until`, or whose `PROPOSED_RESULT_MAX_AGE_S` age limit (the defensive rule
for an envelope without a validity; the real cycle always sets one, at most 900 s ahead), falls before the publish horizon
gives `stale_from` -> `STALE` (all nulls, `last_good`). A fresh result that would expire before the next tick is published
`STALE` at once. With refresh before expiry and healthy polls (60 s plus or minus 3 s, any phase) there is no STALE. A
missed, late or frozen telemetry poll can give one STALE cycle per episode (the tick's STALE check runs before the
refresh it starts; A32, accepted as fail closed). STALE that lasts longer than one cycle means a real fault (an input,
the CPU guard, a hung cycle).

**`next_run_at`.** `run_cycle` is pure and knows no schedule. The runtime sets `next_run_at` with `with_next_run_at` on
every computed and STALE envelope: the earliest moment the next cycle can start. That is the next schedule slot or, when
earlier, the moment the validity left falls below the refresh margin (`valid_until` less 125 s; less 185 s while polls are
arriving, the moment from which a poll-driven step refreshes), never before the publish time, the refresh floor or a
STALE back-off. While an item is BLOCKED `INPUT_EXPIRING`, or, while polls are arriving, BLOCKED for an input reason, it
is the refresh floor. While refreshes are switched off, suspended by the CPU guard or barred after a time-budget overrun
it is the next slot alone. `paused_envelope` carries the next slot; STARTING and SELF_TEST_FAILED carry none. The card
shows it as "next refresh" (UI_DESIGN section 2). It is a timestamp-only attribute, so it is not recorded.

**Pause.** `input_boolean.ecco_intel_paused` is only read, never written. When it is on, the integration publishes
`PAUSED` and computes nothing; the last values stay in `last_good`. The helper is read again when a cycle's result
arrives: if it was turned on while the cycle ran, `PAUSED` is published, the result is discarded and nothing is recorded
in the scorecard. A failure published while the helper is on (a time-budget overrun, for example) also shows `PAUSED`
(PAUSED > SELF_TEST_FAILED). When the helper is turned off, the status shows `STARTING` (all nulls, `last_good` kept) and
a cycle runs at the next minute's tick (or, while polls arrive, at the next poll-driven step), but never before the
PROPOSED start-up grace has passed since setup. A helper turned on while a cycle is in flight shows at the cycle's end
(its result discarded), or earlier at the tick body's deadline run inside that cycle. Disabling the config entry also pauses. A restart is never needed.

**Diagnostics only** (never an entity attribute): `last_cycle_timing` {recorder_s, engine_s, store_s, total_s, cpu_s},
`cycle_duration_s`, `cycle_stats` (the last `PROPOSED_CYCLE_STATS_N` = 4800 runs, more than the 72 h acceptance can
start at the highest cycle rate, so one download at its end holds them all, A50; with the fields `started_at`, `kind`,
`outcome`, `total_s`, `recorder_s`, `engine_s`, `store_s`, `cpu_s`, `trigger` (TICK / POLL) and `poll_age_s` (the age of
the last poll text at the cycle's start); parse rows by the summary's `fields` list; `by_kind` gives the
p50 / p95 / maximum per kind; `job_cooldown_s` and `timings_with_cooldown` name the cool-down each job's time includes:
`recorder_s`, `engine_s`, `store_s` and `total_s`, not `cpu_s`), the `cadence` block (`refresh_enabled`, `last_start`, `last_kind`, `last_trigger`,
`cpu_s_rolling_hour`, `refresh_suspended_cpu`, `retry_at`, `stale_backoff_s`, `poll_listener`, `polls_arriving`,
`last_poll_seen_at`, `poll_step_due`, `poll_step_settle_hold`, `poll_step_armed`, `cycle_in_flight`, `tick_attached`,
`last_tick_at` (the tick body's last run, whichever ran it: the tick, the run at a cycle's first step, the catch-up at a
cycle's end or the deadline run inside a cycle; the tick's own phase follows the last cycle's end), `tick_poll_phase_s`
(that run's phase against the last poll seen: the seconds from that poll to that run, null while polls are not
arriving), ...), the `liveness`
ages of both poll texts, the counters (`runs_started`, `runs_published`, `refresh_runs_started`, `poll_runs_started`,
`refresh_suppressed_cpu`, `budget_exceeded`, `exceptions`, `tick_refresh_held`, `tick_slot_held`, `settle_holds`,
`settle_held_starts`, `settle_residual_starts`, `snapshot_holds`, `snapshot_residual_reads`, `entity_writes`,
`history_parses`, `history_reuses`, `ticks_deferred`, `catchup_ticks`, `tick_start_runs`, `tick_deadline_runs`,
`poll_steps_held_busy`, ...) and
`proposed_constants`.
Entity ids, the configuration hash, the location and the git sha are redacted. The last cycle's `source_notes` are shown
(A42, no longer redacted): each is a contract key and a constant code from `runtime/sources.SOURCE_NOTE_CODES` (for
example `["tariff.import_rates", "TABLE_ROWS_OUT_OF_ORDER"]`), never an entity id, an attribute name, a state text or a
site number, so a rate table the runtime refused is visible in the download. `source_notes_withheld` counts any note
that is not of that kind and is therefore left out (none: `test_runtime_sources.py` produces every code on its refusal
path and pins that no other note is made). The last cycle's `signals` lists the observations by contract name, and each
PV forecast observation by its day and position only (for example `pv.forecast.tomorrow.s000`), never by the site
file's source name, which is site text (A45, `runtime/sources.public_signals`); `signals_withheld` counts any other name,
left out (none). A test pins that a distinctive source name never appears in the download.

### 2.3 Freshness, liveness and SOC (`runtime/sources.py`)

- The dongle publishes a value only when it changes. Every dongle-sourced input (`site_decisions.DONGLE_SIGNALS` /
  `DONGLE_READINGS`, the TOU enables, the overlay and the supervision state and stable flag among them) therefore takes its
  observation time from the moment the telemetry poll text (`sensor.<slug>_last_telemetry_update`) was last seen to
  **change**:
  - a reconnect that replays the old text is not a new poll;
  - the first sighting after start-up is not a change;
  - `Waiting` (no NTP time yet) or an unavailable text gives no new poll;
  - a missing poll-text mapping gives no liveness reading, and the quality layer BLOCKs with `LIVENESS_MISSING`.
- **The configuration poll (contract 13.3).** The coordinator keeps a second liveness memory for the configuration-poll
  text (`liveness.config_poll_changed_at`) and passes its change time to `build_sources(..., config_liveness_at=...)`. The
  reading is published only while the mapped configuration-online entity's state is exactly `on`, never parsed from the
  text's state and never from a future or naive time. Every configuration-poll reading (`CONFIG_POLL_READINGS`: the TOU
  table, the current TOU target, both enables, the shutdown SOC, the Ah capacity) is observed at the **older** of the two
  liveness times, and is withheld without either, so the charge-window items BLOCK. The quality layer bounds the
  configuration liveness at 300 s (five polls).
- **The TOU table (schema v2).** Built from exactly six mapped slots of six entities each. A field that is unknown is null,
  never 0 and never a guess. The charge source and mode pass through exactly as published: the dongle's literal `None` is
  a value (no source), only Home Assistant's `unavailable` / `unknown` are null. `flags_raw` must be a whole number
  0..65535, and `end` is the next slot's start. A v1 (start / target only) table is never built. The planning layer
  classifies it (contract 13.5).
- **The overlay** (`tou.overlay_state`) is `NONE` only when every mapped overlay entity is exactly `off`, `ACTIVE` when any
  is exactly `on`, and withheld otherwise.
- **The raise-only reserve preference** (`pref.advisory_reserve_raise_pct`), once mapped, is published every cycle: its
  number when the state is a finite percentage 0..100, otherwise value null (never dropped, never 0), and the engine then
  BLOCKs the reserve items (`PREF_RESERVE_RAISE_UNKNOWN`). Unmapped, it gives nothing: no raise.
- `unavailable`, `unknown`, an empty, non-numeric or non-finite state, or an unsupported unit is **missing, never 0**.
- The raw SOC (`battery.soc_raw_pct`) is preferred for `battery.soc`. The canonical SOC is used only without a usable raw
  reading. A canonical value of exactly 0 with no raw confirmation counts as missing (a known false zero).
- Other readings take their observation time from the newest of `last_reported`, `last_updated` and `last_changed`. A spec
  with `fresh_by: refreshed_at` (a sensor of the configuration bridge, which re-renders every 5 minutes) takes the older of
  that attribute and `last_updated` instead, and is withheld when the attribute is missing, unparseable, naive, in the
  future or more than 5 s from `last_updated`: it can only make a reading older. A numeric reading of that class may take
  its number from an `attribute` (and one nested `key`).
- **Rate tables from the day events (A38 Part B, CCR-RT-DAYS).** A table reading copies its attribute's rows only when
  the entity's state is usable and the attribute is a list (otherwise `TABLE_MISSING`). `tariff.import_rates` and
  `tariff.export_rates` may instead list two or three day events in day order (previous, current, next; the recommended
  form is the current-day and next-day events, A42), and the runtime hands the engine one list (`merge_day_tables`):
  - a part whose entity is absent, unavailable or unknown, or whose attribute is absent, null or an empty list,
    contributes nothing (the next day's event before its rates are published, a missing previous day);
  - a contributing attribute that is not a list refuses the whole table (`TABLE_PART_NOT_LIST`);
  - the rows are concatenated in mapped order; a row with the start, end (as instants) and rate of an earlier row is
    dropped (a day event that still holds the day before); any other repeat or overlap (`TABLE_ROWS_OVERLAP`), rows out
    of order (`TABLE_ROWS_OUT_OF_ORDER`: the events listed in the wrong order included; the runtime never sorts) and a
    row whose start or end is unusable (`TABLE_ROW_TIME_UNUSABLE`) refuse the whole table; a gap (the current-day
    event unusable while the other two contribute) is passed on unchanged, never filled, and the engine's parse rule
    refuses a table with a gap (`TARIFF_GAP`), so that tariff is unusable for the cycle;
  - a refused table, or nothing contributing (`TABLE_MISSING`), gives no reading, so the engine sees no tariff; the
    window check then has nothing to compare with, and the TOU window stands with its WARN and INFO
    `CHARGE_WINDOW_NOT_PRICED` (section 7, risk 8); the refusal code is in the diagnostics' `source_notes` (section 2.2);
  - the merged reading is observed at its oldest contributing part's own time (the single form's rule, `fresh_by`
    included): a part with no usable time withholds the whole, and a part dated in the future dates the whole there
    (never fresh).
  The engine's parse, unit and coverage rules then apply unchanged.
- `engine_link` calls `ecco_core.bridge.advisory_live_inputs(snapshot, policy=FreshnessPolicy(ADVISORY,
  overrides=...))`. The overrides are `site_decisions.freshness_limits(decisions)` for the signals `ecco_core.state` knows
  (tighten-only, with the 900 s ceiling), each dongle signal's limit clamped to the quality layer's 180 s liveness bound
  (V-4: the caller and the quality layer then agree, so history-only items stay visible while the dongle is frozen). It
  passes the raw snapshot, the LiveInputs **and** the bridge's assessments; `quality.assess_inputs` re-verifies them and
  BLOCKs on `CALLER_FRESHNESS_DISAGREES`.
- The acceptance keyword is never passed, so the default `{OWNER_RECORD}` applies. The boundary suite and
  `test_runtime_mapping.py` check this by AST.

### 2.4 Vendoring (`tools/build_ha_integration.py`, the frozen command line)

`python tools/build_ha_integration.py --out <abs-dir> [--git-sha S]` builds from the working tree, with no git and no
network. It writes:

- `<out>/custom_components/ecco_intelligence/`;
- `<out>/VENDOR_MANIFEST.json`, with an identical copy inside the package for the start-up gate;
- `<out>/SHA256SUMS`.

What goes into the kit:

- **The vendor set:** the AST import closure, module level and function level, of `intelligence.shadow_cycle`,
  `intelligence.scorecard`, `intelligence.history` and `ecco_core.bridge`, plus the package `__init__` files.
- **Import rewriting:** every absolute `intelligence.` / `ecco_core.` import is rewritten to a package-relative one, at any
  depth, in the vendored modules and in the integration files. Examples:
  - `bridge.py`'s lazy import becomes `from ..intelligence.inputs import ...`;
  - `runtime/engine_link.py` imports `from .._vendor.intelligence...`.
- **Nothing else changes:** apart from imports, every vendored module is unchanged (an AST check), with line endings
  normalised to LF.
- **Imports outside the closure:** an integration import that is not in the closure refuses the build. `authority_vocab`,
  for example, is not vendored, so the runtime does not import it.

The output is byte-deterministic. The builder refuses an `--out` inside the repository, an existing non-empty `--out`, a
relative `--out`, a malformed `--git-sha`, a symlink, an unexpected file type, and a closure that would reach
`ecco_autonomy`, `ecco_core.authority` / `capability`, tests, tools, prototypes or profiles. Nothing generated is
committed. Only `.py` and `.json` files are in the kit; any change to `coordinator.py`, `const.py` or a runtime module
changes its `SHA256SUMS`. Kit equivalence between the L3-tested kit and the kit built from main (only the two
`VENDOR_MANIFEST.json` lines differ, by `git_sha`) is checked by the PR-5 deploy route (amendment A3).

## 3. Contract mapping (`ecco-intel-entities/1`)

| Contract | Where the runtime uses it |
|---|---|
| `starting_envelope(now, versions, decisions=, paused=)` | at setup (all nulls) |
| `starting_envelope(...)` + `with_last_good` | the pause helper turned off (until the next result) |
| `paused_envelope(...)` + `with_last_good` | pause helper on (at setup, on a tick, at a cycle's start, and when a cycle's result arrives); it carries the next slot as `next_run_at` |
| `self_test_failed_envelope(now, versions, failures, decisions=, paused=)` + `with_last_good` | a failed gate, an entity id mismatch or missing entity, an entity state write that raised, an exception, a time-budget overrun |
| `stale_from(previous, now, paused=)` + `with_next_run_at` | the timer: a validity or age limit that ends before the publish horizon; a fresh result valid for less than one tick |
| `run_cycle(CycleInputs)` + `with_next_run_at` | every computed envelope, slot or refresh (the runtime never calls `assemble_envelope` itself), with `next_run_at` = the earliest moment the next cycle can start (section 2.2) |
| `to_entity_payloads(env, horizon)` | THE mapping, as of the publish horizon (the next tick plus `PROPOSED_TICK_MARGIN_S`): each entity's state and attributes are exactly `(state, recorded, unrecorded)`. Home Assistant adds only `friendly_name`, `unit_of_measurement`, `device_class` and the ENUM `options` (goldens: `test_runtime_mapping.py` against every foundation fixture). Only an entity whose payload changed is written |
| `ENTITY_IDS` / `UNIQUE_IDS` | `entity_id` is set explicitly and `unique_id` is the object id; one device, entry type `service` |
| `UNRECORDED_ATTRIBUTES` | `_unrecorded_attributes` on every entity class: the contract's set (`self_test`, `input_ages`, `last_good`, `advice`, `engine_comparison`) plus the runtime's timestamp-only attributes `generated_at`, `valid_until`, `next_run_at` (A17; the published values are unchanged, only what the recorder stores) |
| `SystemStatus.ALL` / `DataQuality.ALL` | the options of the two ENUM sensors |
| `ITEM_UNITS` | the units of the seven value sensors. No state class, so nothing becomes a long-term statistic |
| `envelope_summary` | `CycleInputs.previous` (the last computed envelope) |
| `OutcomeMetrics` | from `Scorecard.metrics` for the last 7 days (`store.outcome_metrics`): every scored `load_kwh:*` kind the engine records (`next_1h`, `to_next_cheap`, `cheap_window`, `day`, `morning`, `overnight`, `to_useful_pv` or `to_useful_pv_from_now`) pooled, each kind's MAE and coverage weighted by its `n`, so the accuracy entity is the load forecasts' pooled accuracy, not the day-load forecast's; read by slot cycles before that slot's scoring step, so the published figure lags one slot; refreshes reuse the slot's copy |
| `scorecard_report` | recorded once per schedule slot, by the slot cycle only. It is refused if it carries `recommended` anywhere, so the scorecard's recommendations table stays empty |

Entities: `sensor.ecco_intel_status`, `sensor.ecco_intel_{charge_target, overnight_demand, export_event, dump_to_grid,
predicted_day_load, pv_tomorrow, predicted_morning_soc, accuracy, data_quality}` and `binary_sensor.ecco_intel_fresh`. The
package entities `input_boolean.ecco_intel_paused` and `binary_sensor.ecco_intel_watchdog_fresh` belong to the ui
stream's package, which is installed **before** the integration.

## 4. The site file (`<config>/ecco/intelligence/site.local.json`)

The site file is the V1 profile schema plus the `decisions` block plus the `shadow_runtime` entity map (schema v2 of the
TOU table, as `runtime/sources.parse_entity_map` requires). The owner writes it offline, checks it with
`tools/ecco_intel_drill.py site-check` (section 4.3), records its sha256 offline (in `<OFFLINE_EVIDENCE_DIR>`) and places it
with the PR-5 route (`tools/place-ha-site-file.ps1`, lands with PR-5). Entity ids come only from this file, never from
code, and the file never enters a repository. Unknown keys are refused, and keys beginning with `_` are documentation (also
inside a spec).

### 4.1 Example (fictional ids)

Every id below is **fictional** (`example_*`), and the decisions are all OPEN; the real file uses the site's own ids and
the owner's recorded decisions. This example loads exactly as written: `test_install_drill.py` runs `site-check` on it
(the entity map PASSes, nothing a published item needs is unmapped, and it maps no capacity source v0.1 leaves out).

```json
{
  "_comment": "FICTIONAL example site file: every id is invented (example_*); the owner writes the real file offline",
  "site": {"pv_array_kwp": 6.0},
  "decisions": {
    "I-D1": {"status": "OPEN"}, "I-D2": {"status": "OPEN"}, "I-D3": {"status": "OPEN"},
    "I-D4": {"status": "OPEN"}, "I-D5": {"status": "OPEN"}, "I-D6": {"status": "OPEN"},
    "I-D7": {"status": "OPEN"}, "I-D8": {"status": "OPEN"}, "I-D9": {"status": "OPEN"}
  },
  "sources": [
    {"name": "dongle", "priority": 1, "entities": {
      "load_energy": {"id": "sensor.example_dongle_ecco_total_load_energy"},
      "pv_energy": {"id": "sensor.example_dongle_ecco_total_pv_energy"},
      "imp_energy": {"id": "sensor.example_dongle_ecco_total_grid_import"},
      "exp_energy": {"id": "sensor.example_dongle_ecco_total_grid_export"},
      "chg_energy": {"id": "sensor.example_dongle_ecco_total_battery_charge"},
      "dis_energy": {"id": "sensor.example_dongle_ecco_total_battery_discharge"},
      "load_power": {"id": "sensor.example_dongle_ecco_load_power"},
      "pv_power": {"id": "sensor.example_dongle_ecco_pv_power"},
      "batt_power": {"id": "sensor.example_dongle_ecco_battery_output_power"},
      "grid_power": {"id": "sensor.example_dongle_ecco_grid_power_ct_clamp"},
      "soc": {"id": "sensor.example_dongle_ecco_battery_soc"}
    }}
  ],
  "forecasts": {"example_forecast_day": {"id": "sensor.example_solar_forecast_today"}},
  "shadow_runtime": {
    "signals": {
      "battery.soc": {"entity": "sensor.example_battery_soc"},
      "battery.power": {"entity": "sensor.example_dongle_ecco_battery_output_power", "sign": 1},
      "grid.power": {"entity": "sensor.example_dongle_ecco_grid_power_ct_clamp"},
      "house.power": {"entity": "sensor.example_house_power"},
      "pv.power": {"entity": "sensor.example_dongle_ecco_pv_power"},
      "inverter.healthy": {"entity": "sensor.example_dongle_ecco_inverter_system_state", "healthy_states": ["Normal"]}
    },
    "readings": {
      "liveness.dongle_poll_changed_at": {"entity": "sensor.example_dongle_last_telemetry_update"},
      "liveness.config_poll_changed_at": {"entity": "sensor.example_dongle_last_configuration_update",
                                          "online_entity": "binary_sensor.example_dongle_configuration_online"},
      "battery.soc_raw_pct": {"entity": "sensor.example_dongle_ecco_battery_soc"},
      "protection.shutdown_soc_pct": {"entity": "sensor.example_dongle_ecco_battery_shutdown"},
      "stop.dump_soc_pct": {"entity": "sensor.example_dongle_ecco_dump_stop_soc"},
      "inverter.clock_offset_s": {"entity": "sensor.example_dongle_clock_difference"},
      "supervision.state": {"entity": "sensor.example_dongle_supervision_state"},
      "supervision.stable": {"entity": "binary_sensor.example_dongle_supervision_stable"},
      "supervision.heartbeat_age_s": {"entity": "sensor.example_dongle_supervision_heartbeat_age"},
      "tou.slot_table": {"slots": [
        {"start": "sensor.example_dongle_ecco_timezone1_time", "target_soc": "sensor.example_dongle_ecco_timezone1_soc",
         "charge_source": "sensor.example_dongle_ecco_timezone1_charge", "power": "sensor.example_dongle_ecco_timezone1_power",
         "flags_raw": "sensor.example_dongle_ecco_timezone1_raw_flags", "mode": "sensor.example_dongle_ecco_timezone1_mode"},
        {"start": "sensor.example_dongle_ecco_timezone2_time", "target_soc": "sensor.example_dongle_ecco_timezone2_soc",
         "charge_source": "sensor.example_dongle_ecco_timezone2_charge", "power": "sensor.example_dongle_ecco_timezone2_power",
         "flags_raw": "sensor.example_dongle_ecco_timezone2_raw_flags", "mode": "sensor.example_dongle_ecco_timezone2_mode"},
        {"start": "sensor.example_dongle_ecco_timezone3_time", "target_soc": "sensor.example_dongle_ecco_timezone3_soc",
         "charge_source": "sensor.example_dongle_ecco_timezone3_charge", "power": "sensor.example_dongle_ecco_timezone3_power",
         "flags_raw": "sensor.example_dongle_ecco_timezone3_raw_flags", "mode": "sensor.example_dongle_ecco_timezone3_mode"},
        {"start": "sensor.example_dongle_ecco_timezone4_time", "target_soc": "sensor.example_dongle_ecco_timezone4_soc",
         "charge_source": "sensor.example_dongle_ecco_timezone4_charge", "power": "sensor.example_dongle_ecco_timezone4_power",
         "flags_raw": "sensor.example_dongle_ecco_timezone4_raw_flags", "mode": "sensor.example_dongle_ecco_timezone4_mode"},
        {"start": "sensor.example_dongle_ecco_timezone5_time", "target_soc": "sensor.example_dongle_ecco_timezone5_soc",
         "charge_source": "sensor.example_dongle_ecco_timezone5_charge", "power": "sensor.example_dongle_ecco_timezone5_power",
         "flags_raw": "sensor.example_dongle_ecco_timezone5_raw_flags", "mode": "sensor.example_dongle_ecco_timezone5_mode"},
        {"start": "sensor.example_dongle_ecco_timezone6_time", "target_soc": "sensor.example_dongle_ecco_timezone6_soc",
         "charge_source": "sensor.example_dongle_ecco_timezone6_charge", "power": "sensor.example_dongle_ecco_timezone6_power",
         "flags_raw": "sensor.example_dongle_ecco_timezone6_raw_flags", "mode": "sensor.example_dongle_ecco_timezone6_mode"}
      ]},
      "tou.enabled": {"entity": "binary_sensor.example_dongle_ecco_time_of_use_enabled"},
      "tou.grid_charge_enabled": {"entity": "binary_sensor.example_dongle_ecco_battery_grid_charge_enabled"},
      "tou.overlay_state": {"entities": ["binary_sensor.example_dongle_free_power_active",
                                         "binary_sensor.example_dongle_dump_to_grid_active",
                                         "binary_sensor.example_dongle_manual_write_in_progress"]},
      "limits.max_grid_charge_w": {"entity": "sensor.example_config_maximum_grid_charge_power", "fresh_by": "refreshed_at"},
      "capacity.helper_kwh": {"entity": "sensor.example_config_battery_capacity", "fresh_by": "refreshed_at"},
      "tariff.import_rates": [{"entity": "event.example_current_day_rates", "attribute": "rates"},
                              {"entity": "event.example_next_day_rates", "attribute": "rates"}],
      "tariff.export_rates": {"entity": "event.example_export_rates", "attribute": "rates"},
      "tariff.events": {"entity": "event.example_saving_events", "attribute": "events"},
      "pv.forecast_tomorrow_kwh": {"entity": "sensor.example_solar_forecast_tomorrow"}
    },
    "pv_forecast_sources": {"tomorrow": {"example_forecast": "sensor.example_solar_forecast_tomorrow"}}
  }
}
```

Notes on the example:

- `inverter.healthy` lists the state texts that mean healthy; `Normal` is fictional, use the site's own text.
- `capacity.helper_kwh` is a second capacity source beside I-D3's stated value, so I-D4 (the band) is then required and
  the two must agree within it. Map a bridge sensor with `fresh_by: refreshed_at`, never an `input_number` (nothing
  re-reports it, so it would never be fresh).
- Values derived from the dongle map to the dongle's own entities, never to a bridge sensor that wraps them.
- **The import rates read the tariff integration's day events in the recommended form (A38 Part B, CCR-RT-DAYS; A42)**:
  the current-day and next-day rate events, listed in that order. The runtime merges their rows into one list (section
  2.3), so from the moment the next day's rates are published the import rates cover the 24 h search period and the
  window check sees the night's cheap slots before and after now; before that, today's own slots (the passed cheap ones
  included) are the window check's comparison. The three-event form, with the previous-day event first, is allowed;
  add the previous-day event only once its report cadence is known to stay within its I-D6 limit (the runbook's
  section 1 records each event's cadence; the merged table is as old as its oldest event). The single
  `{entity, attribute}` form stays valid (the export rates above use it); `tariff.export_rates` may take the same list.
  No entity and attribute may be named by two of the import rates, the export rates and the events (section 4.2).
- **v0.1 leaves two capacity sources unmapped (amendment A25):** `capacity.fe1_wh_per_pct` / `capacity.fe1_basis` (the
  learned capacity) and `capacity.reg204_ah` (it reads in Ah and needs a nominal voltage nobody has recorded). `site-check`
  refuses a file that maps any of them. The learned figure is compared read-only, outside the runtime, during acceptance
  (runbook section 9, Q8).
- `pref.advisory_reserve_raise_pct` is optional: `{"entity": "input_number.ecco_advisory_reserve_raise_pct"}`, the helper
  of `home-assistant/packages/ecco_intelligence_prefs.yaml` (0-100 %, no `initial`). Map it only once that package is
  installed: a mapped helper that is missing, unavailable, non-numeric or outside
  0..100 BLOCKs the reserve items (`PREF_RESERVE_RAISE_UNKNOWN`). Unmapped means no raise.
- `reserve.ha_minimum_soc` (signal) is needed only when I-D1 takes its value from the Home Assistant reserve helper
  (`HA_RESERVE_HELPER`); the SHADOW defaults record I-D1 as the Intelligence user reserve instead.

### 4.2 Which keys take which spec

`signals` takes the `ecco_core` signal names; `readings` takes any `advisory_contract.SITE_READING_KEYS` key.

| Keys | Spec | `fresh_by` | `attribute` / `key` |
|---|---|---|---|
| `battery.power`, `grid.power`, `house.power`, `pv.power` (signals) | `{entity, sign}` (`sign` 1 or -1, default 1) | refused | refused |
| `inverter.healthy` (signal) | `{entity, healthy_states: [non-empty texts]}` | refused | refused |
| `battery.soc` (signal) | `{entity}` | refused (a dongle signal) | refused |
| `reserve.ha_minimum_soc` (signal) | `{entity}` | allowed | refused |
| `liveness.dongle_poll_changed_at` | `{entity}`: the telemetry poll text (the coordinator's state listener follows it) | refused | refused |
| `liveness.config_poll_changed_at` | `{entity, online_entity}`: the configuration-poll text and the configuration-online binary sensor, both required | refused | refused |
| `tou.slot_table` | `{slots: [exactly 6 x {start, target_soc, charge_source, power, flags_raw, mode}]}`, every field its own entity | refused | refused |
| `tou.overlay_state` | `{entities: [1..16 distinct binary entities]}` (Free Power, Dump to Grid, manual write) | refused | refused |
| `tou.enabled`, `tou.grid_charge_enabled`, `tou.current_target_soc_pct`, `supervision.state`, `supervision.stable`, `battery.soc_raw_pct`, `protection.shutdown_soc_pct`, `stop.dump_soc_pct`, `inverter.clock_offset_s`, `capacity.reg204_ah` (dongle and configuration-poll readings) | `{entity}` | refused | refused |
| `pref.wear_cost_p_per_kwh`, `pref.normal_max_charge_target_pct`, `pref.advisory_reserve_raise_pct` (preferences: they never age) | `{entity}` | refused | refused |
| `tariff.import_rates`, `tariff.export_rates` (rate tables) | `{entity, attribute}` (the attribute holding the rows), or a list of 2 or 3 of them: the day events in day order (previous, current, next; A38 Part B), each entity listed once | allowed (per event) | `attribute` required (per event) |
| `tariff.events` (table) | `{entity, attribute}` (a list is refused: it holds periods, not one day's rates) | allowed | `attribute` required |
| `limits.max_grid_charge_w`, `capacity.helper_kwh`, `capacity.fe1_wh_per_pct`, `efficiency.helper_pct`, `pv.forecast_today_kwh`, `pv.forecast_tomorrow_kwh`, `supervision.heartbeat_age_s` (numbers aged by their own report time) | `{entity}` | allowed | allowed (`key` only with `attribute`) |
| `capacity.fe1_basis` (text aged by its own report time) | `{entity}` | allowed | refused |

`pv_forecast_sources` maps `today` / `tomorrow` to `{source name: entity}`. A refused map FAILs `SITE_ENTITY_MAP` with the
field path only (for example `shadow_runtime.readings.tou.slot_table.slots[3].mode: not a valid entity id`); the offending
value goes to the debug log. One entity mapped to two slot fields, or listed twice as an overlay, is refused, and so is a
`liveness.config_poll_changed_at` entity or `online_entity` equal to the `liveness.dongle_poll_changed_at` entity (A33: a
copy-paste error would age every configuration-poll reading by the telemetry poll), and any two of the boolean gate
readings `supervision.stable`, `tou.enabled` and `tou.grid_charge_enabled` on one entity (A36, RR-3: each must read `on`
for the items it gates, so a copy-paste error between the two TOU enables would let one enable's `on` stand for the
other, and charge-window advice would stand while the grid-charge enable is off), and one rate event (entity and
attribute) under two of `tariff.import_rates`, `tariff.export_rates` and `tariff.events` (A42, RT4-2); `site-check` then
exits 1.

The refused pairs, in full (each by field path only; `site-check` exits 1 and the runtime publishes
`SELF_TEST_FAILED`):

| Pair | Why |
|---|---|
| two fields of the TOU slot table, or one overlay entity listed twice | a copy-paste error could hide a second grid slot or an overlay |
| `liveness.config_poll_changed_at` (its `entity` or its `online_entity`) and `liveness.dongle_poll_changed_at` (A33, RT-3) | every configuration-poll reading would be aged by the telemetry poll |
| any two of `supervision.stable`, `tou.enabled`, `tou.grid_charge_enabled` (A36, RR-3) | one gate's `on` would stand for the other's |
| any of `supervision.stable`, `tou.enabled`, `tou.grid_charge_enabled` and the configuration poll's `online_entity` (A39, RT3-1 / RT3B-1) | that entity reads `on` whenever the configuration poll is online, so an enable that is off or supervision that is not stable would never be read (charge advice or Dump OK instead of BLOCKED) |
| `battery.soc_raw_pct` and the `battery.soc` signal on the same entity and attribute (A39, RT3B-2) | the raw reading is preferred, so the canonical sensor's known false zero would pass as a raw 0 and the morning SOC would rest on it while the battery does not discharge |
| the same entity twice in a rate table's list of day events (A38 Part B) | one day would be read twice and another not at all |
| the same entity and attribute under two of `tariff.import_rates`, `tariff.export_rates` and `tariff.events`, every day event of a list counted, the later key in code order named against the earlier (A42, RT4-2) | one event would be read for both keys, and its freshness would stand in for the other key's own event: with an import day event copied into the export mapping the real export rates event is never read, so a stale export event would not BLOCK export and Dump advice (`INPUT_NOT_FRESH`), and the export rows would be the import's |

The same entity under another attribute is accepted (one entity may hold the import and the export rates in separate
attributes). A site whose import and export rates are one attribute is refused (fail-closed): each table key maps its
own events or attributes (runbook section 1).

**Units.** A numeric reading's `unit_of_measurement` must be one its canonical unit accepts:

| Canonical unit | Accepted |
|---|---|
| % | % |
| W | W, kW |
| kWh | kWh, Wh |
| s | s, min |
| Ah | Ah |
| Wh/% | Wh/% |
| p/kWh | p/kWh, GBP/kWh |

A missing unit attribute is taken as the canonical unit. Any other unit counts as missing. An attribute number carries no
unit of its own and is taken in the canonical unit.

**Decisions.** The typed record of each decision is in the foundation contract, section 1. An entry is
`{"status": "RECORDED", "provenance": "OWNER_RECORD", "record_ref": "REC-YYYYMMDD-<slug>", "value": {...}}` or
`{"status": "OPEN"}`. Almost every item needs I-D6: every gate reading is never fresh (UNRESOLVED) until I-D6 gives it a
limit, within the 900 s ceiling; neither liveness reading is ever an I-D6 key.

### 4.3 Checking the file offline (`site-check`)

```
python -I -B tools/ecco_intel_drill.py site-check --site <site.local.json> [--json]
```

It loads the file with the runtime's own loader (`runtime/gates.load_site`) and prints the file's sha256 and the runtime's
`config_hash` (the first 16 hex digits: the status entity's `config_hash` attribute), every load check, each
decision's status and provenance, and each published item's static readiness: **BLOCKED** with the reasons the file
alone already causes (`DECISION_D<n>_OPEN` / `_INVALID`, `NOT_MAPPED:<key>`, `NO_I_D6_LIMIT:<key>`, `SITE_FACT_MISSING`,
`NO_HISTORY_SOURCE`, `SELF_TEST_FAILED:<check>`), or **LIVE_INPUTS_DECIDE** (the file blocks
nothing; the check can prove BLOCKED, never OK). It prints no entity id, record reference, source name or decision value.
It exits 1 for a FAIL load check, an INVALID decision or a capacity source v0.1 leaves unmapped, otherwise 0. The example
profile `intelligence/profiles/site_profile.example.json` (every I-D OPEN, no entity map) exits 0 with every published
item BLOCKED; used as a site file in the stand-in Home Assistant it gives a BLOCKED status with no number on any item (L2
tested).

## 5. Home Assistant APIs relied on

This is the complete list: the boundary suite's positive allowlist admits nothing else, and each event helper may be called
from exactly one place, in `coordinator.py`.

| API | Use | Covered only by the L2 fake (check under L3) |
|---|---|---|
| `homeassistant.core`: `HomeAssistant`, `callback`, `CoreState`, `HassJob(target, name)` (the poll-driven step's named job); `hass.states.get` (read); `hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STARTED)` (the only bus listener); `hass.async_add_executor_job`; `hass.async_add_import_executor_job` (the import of `coordinator.py`, in `__init__.py`); `hass.async_create_background_task(target, name, eager_start=False)` (the cycle task, never eager); `hass.loop.call_soon` (the release of each executor job); `hass.state` (a cycle starts only while it is `running`); `hass.config.config_dir / latitude / longitude` | reads, scheduling | yes: listen-once removal after it fired; `State.last_reported` presence and semantics (HA >= 2024.3); the Core's eager default for tasks and its import executor (the fake models both; the signatures were checked against the pinned Core's source: `async_create_background_task(target, name, eager_start=True)`, `async_add_import_executor_job(target, *args)`, `HassJob(target, name=None, *, cancel_on_shutdown=None, job_type=None)`) |
| `homeassistant.const`: `EVENT_HOMEASSISTANT_STARTED`, `__version__`, `REQUIRED_PYTHON_VER` | start-up, versions | yes |
| `homeassistant.config_entries`: `ConfigFlow`, `ConfigFlowResult`; `entry.data`, `entry.runtime_data`; `hass.config_entries.async_forward_entry_setups / async_unload_platforms` | setup / unload | yes: `runtime_data` (HA >= 2024.4), `single_config_entry` in the manifest |
| `homeassistant.exceptions.ConfigEntryError` | refuse a non-SHADOW mode | yes |
| `homeassistant.components.sensor`: `SensorEntity`, `SensorDeviceClass.ENUM`; `homeassistant.components.binary_sensor.BinarySensorEntity` | the entities; `_unrecorded_attributes`; `async_write_ha_state` of their own state | yes: the recorder honouring `_unrecorded_attributes` on these classes (the timestamp-only attributes included); the 16 KiB attribute limit; the ENUM options validation |
| `homeassistant.components.diagnostics.async_redact_data` | the diagnostics download | yes |
| `homeassistant.components.recorder.get_instance(hass).async_add_executor_job`; `recorder.statistics.statistics_during_period(hass, start, end, ids, "hour", None, types)` | history (read-only, the recorder's executor) | yes: the row shape (`start` as a float timestamp), the `types` set, behaviour for unknown ids, cost on the site recorder backend |
| `homeassistant.helpers.event.async_track_time_interval(hass, action, interval, name=TICK_JOB_NAME)` | the one timer (60 s), named | yes: the Core names the timer's job `<name>: track time interval ...` |
| `homeassistant.helpers.event.async_track_state_change_event` | the one state listener: the mapped telemetry poll text (A23); none when it is not mapped; removed on unload | yes: `event.data["new_state"]`; delivery of a state change while the other entities of the same poll are still being written (the 3 s settle delay covers it); attribute-only changes |
| `homeassistant.helpers.event.async_call_later(hass, delay, HassJob(...))` | the poll-driven step, at most one pending, cancelled on unload; its job named `POLL_STEP_JOB_NAME` | yes: the callback's argument; cancellation by the returned function; a `HassJob` accepted as the action |
| `homeassistant.helpers.device_registry`: `DeviceInfo`, `DeviceEntryType` | one service device | yes |
| `homeassistant.helpers.entity_platform` (`AddEntitiesCallback`), `homeassistant.helpers.typing` | the platform signatures | yes |
| `homeassistant.util.dt.utcnow` | the clock | yes |

Explicit entity ids follow HA's behaviour: a taken id becomes `_2`, and `ENTITY_IDS` FAILs. The fake reproduces it, and
the pinned Core under L3 shows the same, together with two consequences the recovery has to respect: Home Assistant
gives a re-added entry its deleted entities' ids back (a `_2` included) for as long as it keeps their deleted-entity
records (it purges orphaned ones after a retention period), and after a rename back to the contract id it
logs that it cannot migrate the suffixed id's history when the contract id has recorded history of its own. The recovery
(find what holds the contract id, rename the suffixed entities, reload the entry; never delete and re-add) is in the
runbook, section 7.

## 6. Runtime constants

**PROPOSED (engineering choices, NOT owner values).** None of them can make a gated number appear; each bounds how long a
cycle may run or when one starts.

| Constant | Value | Where | Role |
|---|---|---|---|
| `PROPOSED_TIME_BUDGET_S` | 120 s | `const.py` | a cycle that takes longer is abandoned (`CYCLE_TIME_BUDGET`) |
| `PROPOSED_STARTUP_GRACE_S` | 180 s | `const.py` | the first cycle waits this long after HA has started |
| `PROPOSED_RESULT_MAX_AGE_S` | 8100 s (2 h 15 min) | `const.py` | the defensive age limit of an envelope without a validity |
| `PROPOSED_TICK_MARGIN_S` | 5 s | `const.py` | a late tick: payloads are mapped as of the next tick plus this |
| `PROPOSED_REFRESH_FLOOR_S` | 55 s | `const.py` | at least this long between two cycle starts for a refresh |
| `PROPOSED_CPU_BUDGET_S_PER_H` | 180 s | `const.py` | engine CPU per rolling hour above which refreshes are suspended |
| `PROPOSED_EXCEPTION_RETRY_S` | 300 s | `const.py` | the one retry after `RUNTIME_EXCEPTION` |
| `PROPOSED_STALE_BACKOFF_S` | 60 s, doubling to 300 s | `const.py` | the refresh back-off after a result went STALE at once |
| `PROPOSED_HISTORY_CATCHUP_S` | 300 s | `const.py` | cached rows ending before the slot's hour are read again once, this long after the slot |
| `PROPOSED_RECORDER_RETRY_S` | 600 s | `const.py` | a failed recorder read is retried by a refresh at most this often |
| `PROPOSED_CYCLE_STATS_N` | 4800 runs | `const.py` | `cycle_stats` keeps the last this many runs (diagnostics): more than 72 h can start at the highest cycle rate (at most 4713 starts 55 s apart plus 26 slots a day, 4791; A50), so T1, T5 and T9 can be read from one download at the end of a window that spans at most 72 h (runbook section 8); a bounded deque |
| `PROPOSED_POLL_INTERVAL_S` | 60 s | `const.py` | the telemetry poll text's nominal period (the target platform's) |
| `PROPOSED_POLL_SETTLE_S` | 3 s | `const.py` | the poll-driven step waits this long after a new poll |
| `PROPOSED_POLL_ACTIVE_S` | 90 s (1.5 polls) | `const.py` | polls count as arriving while a new poll was seen within this long |
| `PROPOSED_RETENTION_DAYS` | 400 days | `runtime/store.py` | scorecard retention |
| `PROPOSED_HISTORY_ROW_CAP` | 150 000 rows (the newest kept) | `runtime/history_source.py` | bounds a recorder read |
| `PROPOSED_HISTORY_LOOKBACK_DAYS` | 120 days | `runtime/history_source.py` | the statistics window |

**Derived or fixed (not tunables).**

| Constant | Value | Rule |
|---|---|---|
| `TICK_S` | 60 s | the one timer (from the work order) |
| schedule | every full hour and 21:30 Europe/London | from the work order (`SCHEDULE_DAILY_LOCAL`) |
| `REFRESH_MARGIN_S` | 125 s | 2 x `TICK_S` + `PROPOSED_TICK_MARGIN_S`; equal to the engine's `shadow_cycle.REFRESH_MARGIN_S` (drift test) |
| `POLL_REFRESH_THRESHOLD_S` | 185 s | `REFRESH_MARGIN_S` + `PROPOSED_POLL_INTERVAL_S` |
| `CPU_WINDOW_S` | 3600 s | the CPU guard's rolling window |
| `SUBMIT_RELEASE_POLL_S`, `SUBMIT_RELEASE_CAP_S` | 1 ms, 1 s | an executor job polls the loop's release flag this often, and starts after the cap at the latest (`__init__.released_call`) |
| `SUBMIT_COOLDOWN_S` | 0.15 s | every executor job sleeps this long after its target before it completes: at least one 100 ms CPU-quota period (event-loop hygiene; no cadence, limit or value depends on it) |
| `TIMESTAMP_ONLY_ATTRIBUTES` | `generated_at`, `valid_until`, `next_run_at` | kept out of the recorder (A17) |
| implied refresh ceiling | 835 s | 900 - 125 + 60: the longest gap between cycles on the tick's rules |

**Safety caps in the readers (not owner values):** `FRESH_BY_TOLERANCE_S` 5 s, a copied table at most 200 rows, at most 16
overlay entities, a time text at most 64 characters (`runtime/sources.py`); the site file at most 256 KiB
(`runtime/store.py`).

**Engine bounds the cadence is built around** (the engine's, PROPOSED there, never set by the runtime): the dongle liveness
bound 180 s and the configuration liveness bound 300 s (`quality.DQ_PROPOSED`), the 900 s advice validity ceiling
(`site_decisions.PROPOSED_FRESHNESS_CEILING_S`).

## 7. Risks and UNKNOWNs

**Risks**

1. **HA API drift.** Everything in section 5 is L2-only evidence until L3 has passed (its harness lands with PR-5). The
   fake is hand-written from the documented behaviour; the state listener and the one-shot are the newest uses.
2. **Poll phase.** The cadence rests on the telemetry poll text moving about every 60 s (on the target platform). If it
   stops moving, the tick's own rules return and the dongle items BLOCK (fail closed), after at most one STALE cycle. One
   missed or late poll can also give one STALE cycle at some phases (A32; fail closed, never a wrong number; T3 / R3 bound
   it). If its period grows well beyond 90 s, polls stop counting as arriving and the tick's rules apply between polls, so
   dongle items can show `INPUT_EXPIRING` part of the time (fail closed, visible as BLOCKED, never a wrong number). A
   faster poll gives no more cycles: a pending poll-driven step is never moved later (A33), the 55 s floor still allows
   one cycle per 55 s, and a refresh still needs less than 185 s of validity left (a text changing every 2 s, faster than
   the settle delay, gives a cycle at each floor's end plus at most 3 s; L2 tested). If the poll text changes before the
   rest of the poll's entities are written, the 3 s settle delay covers it: no cycle starts inside the settle delay of
   the newest poll seen (A36, section 2.2). The cases the hold covers, each L2 tested with an entity written after the
   text: a refresh the tick asks for after STALE (a late poll 0.5 s before the tick), the exception retry the tick asks
   for (1 s after a poll), a step deferred to the floor's end when a newer poll arrives in the last 3 s of the floor,
   and a step re-armed when a cycle in flight ends inside a newer poll's settle delay; the tick's exception to its hold
   and a step under a poll text faster than the settle delay pass the same rule. L3 checks the ordering on the real Core.
   A poll text that arrives between a cycle's start and its snapshot (the cycle starts a loop step or two before it
   reads) is covered too, by the settle hold at the snapshot (L2 tested with the text alone first and a reading 1 s
   later). Two cases are not covered. Writes that land more than 3 s after the text are outside the settle delay by
   definition. And two polls within one settle delay (an abnormal sub-settle poll period): the hold is one-shot and
   never re-armed by a later poll (so it cannot starve), so the held cycle starts inside the second poll's settle delay
   (`settle_residual_starts`), or, when the second poll arrives while a cycle holds its snapshot for the first, the
   snapshot is read inside the second poll's settle delay (`snapshot_residual_reads`; that poll is not covered, so its
   step refreshes at the floor's end when a refresh is due). Such a cycle can read the newest poll text with some of the
   previous poll's values, so its numbers rest on data up to one poll older than their stated freshness, until the next
   compute (at the latest the item's own validity, at most 180 s after the poll it rests on).
3. **Recorder rows (A17).** About 11 states rows per published cycle, one cycle per poll: about 15.8k states rows a day.
   Attributes rows are added only when a recorded value changes. The recorder bytes per day and HA's memory slope are
   measured under L3 (M6) and in the 72 h acceptance (T10) against the live baseline.
4. **CPU on the target host.** The CPU time of a cycle on the target host is UNKNOWN (L3 measures it on its own test
   machine, not on the target host). The guard degrades to STALE, never to wrong advice, and its headroom is tracked
   explicitly rather than inferred from STALE (A49, section 2.2): the runbook's R3 reads `cadence.cpu_s_rolling_hour`
   beside `refresh_suppressed_cpu` once an hour of refreshes has run, and the 72 h acceptance measures it (T5, T9:
   `refresh_suppressed_cpu` 0 and the rolling hour's p95 at most 120 s against the 180 s guard, from the diagnostics
   downloads; one at the end holds every run of a window that spans at most 72 h, A50). A50 lowers a cycle's CPU (the
   engine's profile memo and the reuse of the parsed history, section 2.2) without changing the guard or any rule; the
   target's own figure is still what R3 and T9 read.
5. **Restart latch.** A Home Assistant outage of more than about 5 minutes sets `SHADOW_WOULD_AWAIT_ACK` in the existing
   supervision. Every install step that needs a restart is owner-approved and kept short (see the runbook).
6. **Recorder cost.** A 120-day hourly read of about 10 to 30 ids runs once per slot (refreshes reuse it). It is bounded
   by the row cap and the time budget, but the cost on the site's recorder backend is UNKNOWN.
7. **Event-loop safety.** Every file and database access runs in an executor, and the fake records any off-loop call. HA's
   own blocking-I/O detector is only exercised under L3. The import of `coordinator.py` runs in the import executor, the
   cycle task is never started eagerly and runs in short steps, and every executor job starts only after the step that
   submitted it (section 2.2, the cycle's steps). The slow-callback rule (no callback of the integration at 0.1 s or
   more in an asyncio debug session) is an L3 check: the L2 suites pin the steps, not their duration. While a cycle is in
   flight no timer of the integration exists (the quiet cycle, section 2.2), every job ends with a cool-down, and the tick
   body runs while one of its jobs computes only at its deadline, in a cycle longer than `TICK_S` (a residual: its
   timeout and its cycle step can reach 0.1 to 0.2 s at a quarter of a CPU, in a cycle that already breaks T5's 60 s
   maximum).
   Outside the integration's control: Home Assistant's own handles that run while the engine computes are slowed as
   well. A deliberate exception of the integration's own: while an engine thread abandoned at the time budget still
   runs, the tick is attached again (the thread keeps the guard, not the quiet), so the STALE and pause rules run every
   minute; that tick can be slowed the same way, after a cycle that already failed its time budget.
8. **Inputs that are not re-reported.** A reading whose entity is not re-reported within its I-D6 limit is never fresh
   and BLOCKs what needs it (an `input_number` mapped directly; the tariff tables, whose report cadence is not yet known,
   so export and Dump advice will probably stay BLOCKED until it is). The configuration bridge's sensors with
   `fresh_by: refreshed_at` avoid it for the helper values. A rate table read from the day events is as old as its
   oldest contributing event, so one event that is not re-reported within the limit makes the whole table not fresh,
   as any stale tariff: no price or value, and the window check has no tariff to compare with, so the TOU window stands
   with its WARN "no verified tariff" (A35) and INFO `CHARGE_WINDOW_NOT_PRICED` (A41), even a window misplaced to the
   peak. The same holds while the runtime refuses the merged table (the events listed out of order, a conflicting or
   non-list event, a row with an unusable time) and while the engine refuses its gap (the current-day event unusable
   after the next day's rates are published) or a row it cannot use (for example a null rate, or a row that ends
   before it starts): the A38 cross-check is then absent and nothing blocks (a BLOCK of the charge-window items for
   that case is not in v0.1; it is decided on the 72 h data, continuation guide section 4).
   The case is visible: the status entity's `reason_codes` show the import table's own code in place of
   `TARIFF_VERIFIED` (before the next-day publication, in place of `TARIFF_VERIFIED` and `TARIFF_COVERAGE_SHORT`), for
   example `TARIFF_NOT_FRESH`, `TARIFF_MISSING`, `TARIFF_GAP`, `TARIFF_RATE_INVALID` or `TARIFF_SLOT_INVALID` and, after
   the publication, `TARIFF_COVERAGE_SHORT` (the import table's age is in `input_ages`, a live check that is not
   recorded). The cheap-run codes `TARIFF_NO_CHEAP_WINDOW`, `TARIFF_CHEAP_RUN_TOO_LONG`, `TARIFF_NO_PRICE_SPREAD` and
   `TARIFF_NO_SLOTS_AHEAD` can stand beside `TARIFF_VERIFIED`: they describe a verified table's shape (a flat tariff,
   or one without a clear cheap run), not a fault, so the acceptance rows read only the import table's own code (A47).
   A table that is missing, refused, gapped or not fresh also gives the charge-window items the WARN
   `CHARGE_WINDOW_FROM_TOU_TABLE` and INFO `CHARGE_WINDOW_NOT_PRICED`, and a refusal by the runtime also leaves its
   code in the diagnostics' `source_notes` (for example `TABLE_ROWS_OUT_OF_ORDER`; section 2.2). `site-check` cannot
   see the events' order (it reads no rows), so the acceptance checks the result on the site (A42, A45): the
   runbook's go / no-go row **R5** (after the first next-day publication the import rates show `TARIFF_VERIFIED`,
   which implies the table fresh within its limit), the 72 h row **T11** (VERIFIED in every computed cycle from each
   day's next-day publication to local midnight, a documented tariff-feed outage excepted; a null status is judged by
   T2, T3 and the pause rule) and the 7-day row **Q6** (a computed cycle without `TARIFF_VERIFIED`, and before the
   next-day publication without `TARIFF_COVERAGE_SHORT` too, counts as an input fault although it blocks nothing).
   These rows fail while the events' report cadence does not fit the freshness limit: that is the intended fail-closed
   outcome. The runbook's section 1 records each event's report cadence.
   **The day-rates mapping (A38, A42).** A site maps the import rates as the two day events [current day, next day], the
   recommended form (Part B, CCR-RT-DAYS, section 2.3). The three-event form, with the previous-day event first, is
   allowed; add the previous-day event only once its report cadence is known to stay within its I-D6 limit. Before the
   next day's rates are published the merged table prices today only and does not cover the 24 h search period: the
   import tariff names no cheap run and gives no price or value, and the planning layer cross-checks the TOU window
   whenever the table prices its occurrence, against the cheapest slot it prices in the 24 h before or after now (the
   look-back, Part A; today's passed cheap slots included). Once the next day is published the table covers the period,
   so the window is checked against its whole priced occurrence (by the named run, or, for a tariff that names none, for
   example a flat one, by the A35 spread check), and the prices and the value return. The accepted residual (an
   occurrence the table does not price keeps the WARN, with INFO `CHARGE_WINDOW_NOT_PRICED`) is limited to the hours
   before the next day's rates are published, after today's occurrence has ended (contract section 3 and 13.5;
   `test_runtime_tariff_days.py` pins these hours for both forms). A site file that maps one day event (the single form)
   keeps Part A's residual: on the current-day event, from the end of today's occurrence to local midnight.
9. **Disabling one entity stops the integration.** A contract entity that Home Assistant does not add (for example one the
   owner disabled in the entity registry) fails `ENTITY_IDS`, so nothing is computed. Pause with the helper or disable the
   whole entry instead.
10. **Frozen boundary finding (resolved at integration step IP-4a).** The frozen boundary suite failed one check on the
    built kit (`re.compile` in the vendored `site_decisions`). CCR-1 revision 2 was applied at IP-4a (section 9), and the
    suite passes on the source and on the freshly built kit.

**UNKNOWNs** (to resolve read-only or under L3, before the install)

- The target platform is Home Assistant Core 2026.10.4 with Python 3.14.9; the install re-checks both read-only (runbook
  G5) and L3 pins the same image. The runtime records HA's `REQUIRED_PYTHON_VER` and a feature probe; the exact Python
  version cannot be read inside the integration because `sys` and `platform` are not on the runtime allowlist.
- The `last_reported` behaviour of the site's entities, and the report cadence of the tariff entities.
- The target host's CPU headroom for a cycle (history build plus engine), and so whether the PROPOSED 120 s budget fits.
- Whether `ha core check` validates custom integrations (it loads them, but the depth is UNKNOWN).
- The recorder backend: `get_instance(hass).dialect_name` would tell, but only at L3. The default is SQLite.

## 8. Tests and evidence (offline, standard library only)

| Suite | What it proves |
|---|---|
| `test_runtime_boundaries.py` (foundation, frozen, tighten-only) | the positive HA import allowlist (`homeassistant.helpers.event` limited to `async_track_time_interval`, `async_track_state_change_event` and `async_call_later`, each called from one place in `coordinator.py`; the only bus listener the one-shot `homeassistant_started`), the banned names and strings, the platforms, the manifest, writes only in `runtime/store.py`, provenance never widened. It runs on the source and on a freshly built kit |
| `test_runtime_mapping.py` | goldens: every foundation fixture through the real entity classes; ids, units, ENUM options, the unrecorded set (the contract's plus the timestamp-only attributes), no RestoreEntity; the AST acceptance check |
| `test_runtime_sources.py` | missing never 0, raw SOC preferred, false zero, poll-text liveness (moving, frozen, replayed, first sighting, missing), the configuration-poll liveness (`online_entity`, the older of the two times, never the telemetry poll text's entity), no two boolean gate readings on one entity (A36, RR-3), no boolean gate on the configuration-online entity and no raw SOC on the canonical SOC's entity (A39), rate tables from the day events (A38 Part B: the list form and its refusals, the merge, the next day unpublished, the previous day missing, repeated rows collapsed, a conflicting repeat, an overlap, rows out of order, a non-list part and unusable row times refused, a gap kept for the engine, which refuses it (`TARIFF_GAP`), nothing contributing, the age of the oldest part, `fresh_by` per part, a future-dated part; RT4B-1: only an exactly equal rate collapses, 0.30 against 0.3001 GBP/kWh is refused, an int and a float of equal value collapse), one rate event under two tariff tables refused (A42, RT4-2: entity and attribute, every day event of a list, either key order; the same entity under another attribute accepted), the source notes (A42: every note a contract key and a `SOURCE_NOTE_CODES` code, every code produced on its refusal path, the vocabulary matched to the module's code literals, `public_notes` withholding anything else, and `engine_link.compute` putting exactly that list in the diagnostics: forged notes added to a real build are withheld and counted), the diagnostics' signal names (A45, RV9-3: `public_signals` keeps a contract signal's name and a PV forecast observation's day and position, withholds anything else, and `engine_link.compute` gives the diagnostics no source name), the schema v2 slot table, the overlay, the raise preference, `fresh_by`, attribute readings, the strict entity map, the history rows and cap, gaps |
| `test_runtime_store.py` | writes only under `state/`, schema version, retention, scorecard once per slot, no recommendation rows, refusals |
| `test_runtime_selftest.py` | every gate, pure and through the stand-in; a tampered kit; the source tree is not a kit; the `SITE_FILE` texts (A49): "a UTF-8 byte-order mark" whatever follows it (RR1-5), "not a JSON object" with the top level's JSON type, "a non-finite number" for NaN, Infinity and a literal beyond the double range (an integer too large for a double no longer raises out of the loader), "not valid JSON" with the exception type (a nesting too deep to read no longer raises either), each value-free and within the 80 published characters, also through the stand-in |
| `test_runtime_build.py` | byte-identical builds, manifest hashes, the exact closure, no absolute import at any depth, only imports changed, the built tree runs alone and gives the repository's envelope, exclusions, refusals |
| `test_runtime_loop_steps.py` (L2) | the event-loop steps under a fake that starts tasks eagerly unless told otherwise (as the pinned Core): the import check (labelled IMPORT), the coordinator module (and most of the vendored engine) imported in the import executor through the integration's own job, nothing of the package first imported on the event loop thread during setup, the import started only after the submitting step ended; the poll-driven step and the tick, fired inside the loop, return before any cycle work runs (the task named, `eager_start=False`, not entered) and the second-run guard holds a second start back; the checks, the snapshot, the history inputs, the engine submit and the publish each in their own loop step, in that order, the tick body in the first step of a cycle the tick body did not start, and the catch-up tick body in the cycle task's last step; identical results with the yields and with them made not to suspend; the settle hold at the snapshot (A36): a poll written between the start and the snapshot step holds the snapshot once to its settle delay's end (in the cycle task, counted), which reads it with that moment as the cycle time and no future observation, a partial poll (the text alone, the SOC 1 s later) is read whole, the held cycle covers that poll (its own step, after the hold, or due during it and so armed at the cycle's end, starts no second cycle and is not deferred), the residual (a second poll during the hold) is counted and its step refreshes at the floor's end, a residual held start is not held again, the hold is cut to the deadline, a SLOT cycle reads its history inputs at the cycle time; a tick body run between the snapshot and the engine job (inside a cycle: the deadline run) leaves the job the snapshot's liveness; an unload and a cancel at each step (before the first, after the checks, during the settle hold, after the snapshot, after the history inputs, during the recorder read, the engine and the store write) end the cycle once as `cancelled`, release the guard and write nothing after an unload (a cancelled hold covers no poll); the job names, the tick's slow-callback text with its timer laid out as the pinned Core's `_TrackTimeInterval`; the release of executor jobs (started only after the submitting step, the flag set by the next handle, the cap) and the cool-down after the target |
| `test_runtime_quiet_cycle.py` (L2) | the quiet cycle: a cycle's start detaches the tick and cancels a pending step (its due time kept), a poll during the cycle is noted but arms nothing (its due time only earlier, A33), no timer or one-shot is created until the end; the end releases the guard, runs the catch-up tick body in the cycle task, attaches the tick again (its phase following the end) and arms the held step at max(its due time, now), where the floor still defers it; a slot that fell due during a cycle starts from the catch-up, and while that slot cycle runs no timer or one-shot is active or created and the held step stays held; the tick body at the first step of a cycle it did not start (63 s and 2 s after its last run; not in a cycle the tick started), so the deadline comes `TICK_S` after the cycle's start; the tick body at its deadline inside an engine job held 140 s (twice, `TICK_S` after each last run), each deadline run the whole `PROPOSED_TICK_MARGIN_S` before the horizon of the publish before it; the real job wait; the tick body never more than `TICK_S` + `PROPOSED_TICK_MARGIN_S` without running over 90 simulated minutes of polls with jobs that take time on the stand-in's clock (snapshot holds, slot reads, a 110 s engine job), and no deadline run in steady poll-driven operation; the cool-down on every executor job (the import, the start-up gates, the recorder read, the metrics, the engine, the store) and on a raising target, and `cycle_stats` naming the timings that include it; an unload during a cycle (nothing left armed or attached, no catch-up after it), a cancel (the catch-up, the tick and the step back), Home Assistant's shutdown (Core stopping, the entry not unloaded: the catch-up runs and publishes, no cycle starts although a slot is due, the tick and the step back), an engine thread abandoned at the time budget, through the real job wait (the job not cancelled, the tick back at once, no step armed until the thread ends, none after an unload); RR-N1, a snapshot hold cut short by the deadline counted as a residual and covering nothing; the end of a cycle that ended `self_test_failed` (an entity write that raised in its start run) or `discarded_failed` (one that raised at its deadline run): the catch-up, the tick and the step back; a settle hold's step held through a cycle armed unheld at its end, so it is held once more inside the settle delay of a poll seen in the cycle's last 3 s; a `_finish` that raises at the end: the guard released, the catch-up, the tick and the step back; a catch-up whose tick body raises: the exception leaves the cycle task, the tick and the step back |
| `test_runtime_import_without_ha.py` | the package and every `runtime/*.py` import with homeassistant absent, from the source and from the kit, with nothing on the global path |
| `test_runtime_fake_ha.py` (L2) | every scenario of the work order on the built kit, each with zero write attempts: refresh before expiry (never STALE over three hours on fresh inputs, at any tick or in any recorder row; statistics once per slot), the exception retry, a hanging job, the frozen dongle (V-4), the CPU guard, `next_run_at`, per-entity writes and state rows per hour, and the lifecycle (exactly one state listener on the mapped telemetry poll text, removed on unload, none when unmapped); A50: every read parsed once and the other cycles reusing the parsed history (parses = reads, parses + reuses = cycles), a refused read keeping none, `cycle_stats` keeping at least 4800 runs (more than 72 h can start) in a bounded deque with the full download small, JSON and redacted. Its world is set between ticks without `state_changed` events, so it pins the tick's own rules |
| `test_runtime_history_reuse.py` (A50) | the parsed history reused between cycles: the image of a read (immutable; equal content exactly when the rows are bit for bit the same, a zero's sign included); `build` = `build_full` then `truncate` at every `now`; a differential run through `engine_link.compute` and the real `run_cycle` (owner-record decisions and every decision OPEN; across hours without a read, a refused, a repeated and a changed read, a read changed in place, a zero whose sign changed, another configuration): the same envelopes, History and diagnostics as a parse and build every cycle, the reuse happening and every changed or refused read rebuilding; `EngineJob.statistics` annotated with the image, and an image handed in without a `HistoryReuse` giving no history, as a refused read does (RUN-4); no mutation: the kept History fingerprinted before and after every cycle and scorecard step, never handed out, the PV forecast series new dicts every cycle, `prepare_history` changing only its copy, a cycle that writes a shared record caught; the audit pinned: every write to an hour record or a History index in the engine, `ecco_core` and the runtime is in `build_history`, `HourRecord.flag`, `History.__init__` or `quality._prepare` (after its deepcopy), or in offline-only modules outside the runtime's import closure; the parsed-history paragraph of section 2.2 and `engine_link`'s docstring give the measured share and name no workstation (REV-E-4, RUN-5) |
| `test_runtime_poll_phase.py` (L2, A23) | STALE, `INPUT_EXPIRING` and numbers counted from the recorder rows (every write, A32). The poll text every 60 s plus or minus 3 s at swept phase offsets (0.5, 1.5, 3, 15, 30, 45, 55, 56, 58 and 59.5 s, the poll's phase from the start; the tick's phase then follows each cycle's end) and a random walk, three simulated hours each: no `INPUT_EXPIRING` and no STALE, no number past its inputs' bound, the tick body never more than 65 s without running and no deadline run, every cycle poll-driven, at most one cycle per poll, at most 11 state writes per published cycle; recovery from an unknown slot, a frozen configuration text and a frozen telemetry text within one poll plus the settle delay (a frozen telemetry text still fails closed); a poll 90 s late, one skipped poll, a 150 s gap and a freeze over seven phases each: at most one STALE cycle per episode, never a wrong number, then the fallback or the recovery; in the freeze every dongle item, Dump among them, loses its number no later than the first tick after the last poll plus `PROPOSED_POLL_ACTIVE_S`, at most 150 s after it, and with the supervision heartbeat stopped too the first compute after the last poll's (more than 90 s and at most 150 s after it) BLOCKs export and Dump `SUPERVISION_NOT_STABLE` (A31(b), the polls-stop exposure); supervision lapsing while polls continue (A31(b): export and Dump BLOCKED `SUPERVISION_NOT_STABLE` at the first poll-driven compute after the 90 s bound lapses); a poll text every 2 s (a pending step is never moved later, A33, and the settle hold is one-shot: a cycle at each floor's end plus at most 3 s, never starving); the settle hold (A36: no cycle starts inside the settle delay of the newest poll seen; with an entity written after the text, the exception retry the tick asks for 1 s after a poll, a step deferred to the floor's end with a newer poll in its last 3 s, a STALE refresh 0.5 s after a late poll and the in-flight wait when a newer poll arrives while the step waits each start at that poll's settle delay's end and read its late writes); the settle delay, floor deferral, coverage, the guards and pause (a poll while a cycle is in flight arms no step; the step comes at the cycle's end), what counts as a new poll, unload, the 185 s threshold and the tick's exception to its hold |
| `test_runtime_tariff_days.py` (L2, A38 Part B, A42) | the import rates as day events, the next day's rates published at 16:00, through the built kit's own runtime and `run_cycle`. Three events: a TOU window misplaced to the 17:00-19:00 peak BLOCKs `CHARGE_WINDOW_SOURCES_DISAGREE` with no number at every half-hour of the day (the window check's lowest rate from 00:30 to 15:30, the named run at local midnight and from 16:00); the single current-day event shows the residual from 19:00 that the day events close, with INFO `CHARGE_WINDOW_NOT_PRICED` on the entities of exactly the published charge-window items (A41, passed through the runtime); a window equal to the cheap run is OK with a number at every half-hour and carries `CHARGE_WINDOW_NOT_PRICED` exactly from 05:30 to 15:30 (the residual hours); a refused merge gives the engine no import rates and the diagnostics download shows `["tariff.import_rates", "TABLE_ROWS_OVERLAP"]` in `source_notes`, unredacted, with no entity id anywhere (A42); a previous-day event not re-reported for 3600 s makes the merged table as old (the status entity shows `TARIFF_NOT_FRESH` and the import table's `input_ages` row 3600 s stale, with the WARN `CHARGE_WINDOW_FROM_TOU_TABLE` and INFO `CHARGE_WINDOW_NOT_PRICED`: risk 8); the current-day event unavailable gives no gap before the next day is published and, after it, a gap the engine refuses (`TARIFF_GAP`). The recommended form [current, next] (A42): the peak window BLOCKs at every half-hour, from the 16:00 publication the status entity shows `TARIFF_VERIFIED` (what R5 and T11 read; the live `input_ages` row is fresh beside it), and the agreeing window carries `CHARGE_WINDOW_NOT_PRICED` exactly from 05:30 to 15:30. A45: a next-day row the engine cannot use (a null rate, a row that ends before it starts) gives `TARIFF_RATE_INVALID` / `TARIFF_SLOT_INVALID` after the publication, never `TARIFF_VERIFIED`, with no `TABLE_*` note in `source_notes` (RV9-2); the download lists three PV forecast sources of distinctive names by day and position only, and no source name appears in it, in any entity or in any recorder row (RV9-3); a STALE publication records no tariff code (RV9-1). A47 (RV10-1): a verified import table that names no cheap run (a flat tariff, a cheap run without a clear spread, one cheap half-hour) records `TARIFF_VERIFIED` with the cheap-run code beside it and no other `TARIFF_*` code, and the runbook's R5 / Q6 rule (the import table's own code) finds no fault there, while it finds one after the publication for an engine-refused next-day row |
| `test_runtime_tou_e2e.py` (L2, WP-E) | the grid-charge classification from Home Assistant states to the entities: slot 1 `Grid` gives OK, an unknown slot, an overlay on, an enable off, a frozen configuration text and `configuration_online` off each BLOCK |
| `test_integration_e2e.py` | the built kit's own `run_cycle` in a fresh `-I` interpreter, the null rule, SHADOW and the paused status; the WP-E cases |
| `test_install_drill.py` | install / upgrade / rollback / uninstall on a marked tempfile mock root; refusals; the runbook printer (its step 8: PAUSED with the helper on, then STARTING and a computed status); `site-check` (the example profile shows every published item BLOCKED and exits 0, an INVALID decision, a v0.1 capacity source, a configuration-poll liveness or online entity equal to the telemetry poll text, the two TOU enables or a TOU enable and `supervision.stable` on one entity (A36, RR-3), a boolean gate on the configuration-online entity and the raw SOC on the canonical SOC's entity (A39), a day event listed twice, four day events or a list for `tariff.events` (A38 Part B), and one rate event under two tariff tables, a day event of a list included (A42, RT4-2) exit 1, a complete fictional file with the import rates as the two day events [current, next] (the recommended form, A42) or as three day events exits 0, one entity holding the import and export rates under separate attributes exits 0, a complete fictional file is not blocked by the file, no id or record reference in the output, this document's section 4.1 example loads and maps the import rates as the current-day and next-day events); the runbook document's pins (R5, T11 and Q6 read the import table's own code and name exactly the cheap-run codes `intelligence/tariff.py` emits, A47; T7's `valid_until` clause a live check of the entities, which the download does not hold (RR1-2); the diagnostics downloads: one at the end holds every run of a window that spans at most 72 h (`PROPOSED_CYCLE_STATS_N` = 4800, A50), a paused stretch's first hours read from the earlier downloads (RUN-1), T1, T5 and T9 read from its rows, a restart or reload empties them (RR1-4); R3 names `cadence.cpu_s_rolling_hour` beside `refresh_suppressed_cpu` and T9 tracks the CPU guard's headroom, A49; the entity-id collision recovery split by what holds the id, a change to a foreign entity a separate owner decision (RR1-1), and the deleted entity ids HA keeps while it keeps their records (RR1-7); `site.local.json` saved without a byte-order mark, with a command that writes it so (RR1-5, RUN-2); the collision recovery's steps 2 to 4 need no restart, step 1's freeing of a holder may (RUN-3); the [current day, next day] mapping named as the recommended form); no dated owner or decision phrase and no commit id in the Home Assistant runtime's docs, code or tests (fictional samples, RR1-3); no process or network use |

L3 (a real HA Core with this kit, pinned to the production image) is approved; its harness lands with PR-5. L4 is
the site, after the install.

## 9. Contract change requests

- **CCR-1 revision 2 (APPLIED at integration step IP-4a, behaviour-preserving):** `intelligence/site_decisions.py` used
  `re.compile` twice. The frozen boundary suite's vendor scan treats any call named `compile` as forbidden, so the built
  kit failed that one check (the integration also removed the plan body's own `re.compile` the same way; see the
  continuation guide, section 3).
  The CCR replaces the two compiled constants with pattern strings used through `re.match` / `re.fullmatch` (identical
  patterns, identical behaviour). Revision 1 deleted the public name `RECORD_REF_RE`, which the policy stream uses in
  three places. Revision 2 replaces it with a public `RECORD_REF_PATTERN` string and a public `record_ref_ok(ref)` (the
  full-match check). `_ref_ok` stays as an internal alias, so its four callers in `site_decisions` do not change. In the
  same integration step the integrator moves `ecco_autonomy/journal.py` and `ecco_autonomy/modes.py` to `record_ref_ok`,
  and moves the test oracle in `ecco_autonomy/tests/_autonomy_props.py` to `re.fullmatch` over `RECORD_REF_PATTERN`, so the
  oracle stays apart from the predicate it checks. The CCR is two unified diffs that carry their base blob ids: one for
  `site_decisions.py` and one for the three policy files. The frozen vendor scan is not loosened.
- **CCR-2 (additive, optional):** allow `WARN: ...` in `self_test`, plus a `with_self_test` constructor, so that the
  runtime's WARN checks (for example the missing pause helper) also appear on the status entity. Meanwhile they appear in
  the diagnostics, and the contract's own `pause_control: MISSING` / `PAUSE_CONTROL_MISSING` show on the entity.
- **CCR-RT-DAYS (amendment A38 Part B; APPLIED in the runtime, PR-3):** a rate table key may map an ordered
  list of two or three day events, which the runtime merges into one list of rows (sections 2.3 and 4.2). The value
  handed to the engine keeps its shape (a list of rows), and the engine's parse, unit and coverage rules are
  unchanged; no contract key, reason code or published value changes. A39 (the configuration-online entity and the
  raw SOC refused as pairs) is applied in the same step. A42 adds the recommended form (the current-day and next-day
  events), the refusal of one rate event under two tariff tables and the unredacted source notes (sections 2.2, 4.1,
  4.2 and risk 8).
- **SHADOW v0.1 completion (CCR-CFG-1, CCR-TOU-1, CCR-PREF-1; APPLIED in the engine and the runtime):** the new readings, the
  schema v2 TOU table, configuration-poll freshness, `INPUT_EXPIRING` and the raise-only preference; contract section 13.
