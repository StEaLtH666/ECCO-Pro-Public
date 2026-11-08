# ECCO Intelligence SHADOW: install runbook (status: install kit staged, PENDING DP-4)

> **Every live step in this runbook is NOT AVAILABLE** until all of these hold:
>
> 1. **PR-3** (the runtime) and **PR-5** (the deploy route for `/config/custom_components/ecco_intelligence/` and the site
>    file: `tools/deploy-ha-kit.ps1`, `tools/place-ha-site-file.ps1`) have merged, and **PR-6** (the presentation and
>    preferences packages) for the pause helper and the watchdog.
> 2. The isolated test Home Assistant (L3) has passed with no unresolved material failure, and the kit to install is
>    equivalent to the L3-tested kit (amendment A3).
> 3. The owner's release closeout is committed and the owner has given the separate go for the install and its one
>    restart (**DP-4**: the production installation and any restart stay separately gated).
>
> Nothing here has been installed or run on Home Assistant. SHADOW only: ASSISTED and AUTONOMOUS stay disabled.

What the integration does is described in [`INTELLIGENCE_HA_RUNTIME.md`](INTELLIGENCE_HA_RUNTIME.md); the deploy route in
`docs/user/intelligence-deploy.md`.

**Notation.** Placeholders are written `<like this>`. `<OFFLINE_EVIDENCE_DIR>` is the owner's local evidence folder; it is
never in a repository. `<production alias>` is the owner's SSH alias for the production host. Every PowerShell block
starts with `cls`. Run the blocks from the repository root of the reviewed, merged commit.

## 1. Go / no-go before any live step

Go only when **every** line below holds. Otherwise stop: this is a no-go.

| # | Criterion |
|---|---|
| G1 | PR-3, PR-5 and PR-6 have merged; L3 passed with no unresolved material failure; the owner's go for the install (DP-4) is given |
| G2 | no supervised live step is in progress, and the owner has reserved this period for the install; the owner is present; the owner's release closeout is committed |
| G3 | the owner has made a fresh **protected** full backup |
| G4 | a fresh read-only baseline shows supervision **SUPERVISED** and **stable**, the supervision heartbeat age is nominal, every write enable, arm and schedule is off, and the manual write counter is noted |
| G5 | the site's Home Assistant Core version and **Python version** have been re-read read-only and equal the versions L3 ran (the target platform: Core 2026.10.4, Python 3.14.9) |
| G6 | the kit verifies (section 2) and is equivalent to the L3-tested kit (its SHA256SUMS identical except the two `VENDOR_MANIFEST.json` lines, same `modules`); the offline suites are green; the mock-root drill passes |
| G7 | `site-check` on the owner's `site.local.json` exits 0 with the readiness the owner expects, its sha256 is recorded in `<OFFLINE_EVIDENCE_DIR>`, and it is placed (section 3) |
| G8 | the presentation package (`ecco_intelligence.yaml`: the pause helper `input_boolean.ecco_intel_paused` and the watchdog) and the preferences package (`ecco_intelligence_prefs.yaml`) are installed **before** the integration (section 4), the pause helper is **on**, and the watchdog carries the numbers of `ecco_intelligence.yaml`: `WATCHDOG_MAX_AGE_S` = **1200 s** (900 s validity + 60 s tick + 120 s budget + 2 x 60 s), `ALERT_AFTER_S` 1800 s, `CLOCK_AHEAD_S` 120 s, PAUSED fresh only while the helper is on (plus 130 s), STARTING bounded by 1200 s, a computed status fresh only with a `valid_until` still ahead (all PROPOSED) |
| G9 | the facts below were re-read read-only in the same session and match what L3 and the site file assume |

**Facts the install rests on** (read-only, each result recorded offline; ids and values only in the offline evidence and
the site file):

- the platform: Core, Python, Home Assistant OS and machine (G5); the SSH add-on's `/config` is itself a symlink, which the
  PR-5 route resolves once, prints and pins before its first write (amendment A26);
- no `custom_components/ecco_intelligence`, no `ecco_intelligence` config entry, no `/config/ecco/intelligence/state/`
  before the first install;
- the TOU table: six slots of six entities, exactly one grid-charge run not crossing midnight, both enables on, every
  overlay off; both poll texts (telemetry and configuration) moving about every 60 s; configuration-online and the
  read-only configuration-polling switch on;
- the readings the site file maps: each entity present, its unit accepted, and its report cadence within the I-D6 limit
  recorded for it (the tariff tables' cadence is not yet known: until it is, export and Dump advice stay BLOCKED);
  `tariff.import_rates` maps the two day events of the recommended form (the current day, then the next day; A38 Part
  B, A42, INTELLIGENCE_HA_RUNTIME 4.1): each event present with its rows under the mapped attribute, its report cadence
  recorded as for the other tables (the merged table is as old as its oldest contributing event), and the next-day
  event's publication time noted. Record the previous-day event's cadence too: the three-event form (the previous day
  first) is allowed, and a site adds the previous-day event only once its report cadence is known to stay within its
  I-D6 limit. Before the next day's rates are published the merged table names no cheap run, prices or
  value, and the TOU window is cross-checked whenever the table prices its occurrence; an unpriced occurrence keeps its
  WARN and INFO `CHARGE_WINDOW_NOT_PRICED`, limited to the hours before that publication (contract section 3 and 13.5,
  "With the day events"). `site-check` reads no rows, so it cannot check the events' order: check it by hand; R5
  (section 7) checks the result on the site. Events listed out of order, an event not re-reported within the limit, or
  a row the engine cannot use leave the TOU window without its tariff cross-check and BLOCK nothing; the status
  entity's reason codes then show the import table's own code in place of `TARIFF_VERIFIED` (before the next-day
  publication, in place of `TARIFF_VERIFIED` and `TARIFF_COVERAGE_SHORT`), for example `TARIFF_MISSING`,
  `TARIFF_NOT_FRESH`, `TARIFF_GAP`, `TARIFF_RATE_INVALID`, `TARIFF_SLOT_INVALID` or, after the publication,
  `TARIFF_COVERAGE_SHORT`, and a refusal by the runtime also leaves a `TABLE_*` note in the diagnostics'
  `source_notes` (INTELLIGENCE_HA_RUNTIME, risk 8). The cheap-run codes that can stand beside `TARIFF_VERIFIED`
  describe a verified table's shape and are no fault (R5). `tariff.export_rates` and
  `tariff.events` each map their own events: `site-check` refuses (exit 1) the same entity and attribute under two of
  the three tariff tables (A42; INTELLIGENCE_HA_RUNTIME 4.2);
- the capacity figures for the capacity check (section 9).

## 2. Offline: build, verify and drill the kit (available now; touches nothing live)

Build the kit outside the repository, from the merged commit:

```powershell
cls
$PY = "<path to a Python 3.12 interpreter with tzdata>"
$KIT = "<absolute kit directory outside the repository>"
& $PY -I -B tools\build_ha_integration.py --out $KIT --git-sha (git rev-parse HEAD)
```

Verify the kit and print the pending steps. This exits 1 when the kit does not verify:

```powershell
cls
& $PY -I -B tools\ecco_intel_drill.py runbook --kit $KIT
(Get-FileHash -Algorithm SHA256 (Join-Path $KIT 'SHA256SUMS')).Hash.ToLower()
```

Record that sha256 offline: it is the `-ExpectedSumsSha256` of every PR-5 run with this kit, and the L3 run's value is the
`-ReferenceSumsSha256` of the production run.

Run the offline suites:

```powershell
cls
$env:PYTHONDONTWRITEBYTECODE = "1"
& $PY -X utf8 -I -B tools\run_offline_tests.py --root custom_components/ecco_intelligence/tests --parallel 1
& $PY -X utf8 -I -B tools\run_offline_tests.py --root intelligence/tests --parallel 1
```

Drill install, upgrade, rollback and uninstall on a marked mock root. The root must contain the marker file
`.ecco_mock_config_root`; the drill refuses any other directory:

```powershell
cls
$MOCK = "<an empty temporary directory>"
New-Item -ItemType Directory -Force (Join-Path $MOCK 'ecco\intelligence') | Out-Null
Set-Content -Encoding utf8 (Join-Path $MOCK '.ecco_mock_config_root') 'mock'
& $PY -I -B tools\ecco_intel_drill.py drill --config-root $MOCK --kit $KIT
```

## 3. The site file (owner)

The owner writes `site.local.json` offline, outside every repository. Its format, a fictional example and the spec of
every key are in [`INTELLIGENCE_HA_RUNTIME.md`](INTELLIGENCE_HA_RUNTIME.md), section 4. It contains:

- the V1 profile (`site`, `sources`, `forecasts`);
- the `decisions` block: every I-D OPEN unless recorded as `OWNER_RECORD` with a `REC-YYYYMMDD-<slug>` ref (the owner's
  provisional values carry `-provisional` slugs until Q8 and Q9 retire them; section 9);
- the `shadow_runtime` entity map in the v2 schema (six-entity TOU slots, the configuration-poll liveness with its online
  entity, both TOU enables, the overlay entities). In v0.1 it never maps `capacity.fe1_*` or `capacity.reg204_ah`
  (amendment A25).

Save it as UTF-8 **without a byte-order mark**: Windows PowerShell 5.1's `Out-File` / `Set-Content -Encoding utf8` writes
one, and `site-check` and the runtime then refuse the file (`SITE_FILE` names the mark; RR1-5). In an editor, choose the
encoding "UTF-8", not "UTF-8 with BOM". From Windows PowerShell 5.1, this writes a UTF-8 file back without a mark, its
text kept as it is (a mark already there is dropped; a file saved in a legacy code page stops with an error and is left as
it was):

```powershell
cls
$SITE = "<the owner's site.local.json>"
$full = (Resolve-Path -LiteralPath $SITE).ProviderPath
$text = [System.IO.File]::ReadAllText($full, (New-Object System.Text.UTF8Encoding $false, $true))
[System.IO.File]::WriteAllText($full, $text, (New-Object System.Text.UTF8Encoding $false))
```

Check it, then record its sha256 before it goes anywhere. `site-check` prints decision status, item readiness and the
sha256, never an id, a record reference or a value; it exits 1 for a refused block, an INVALID decision or a capacity
source v0.1 leaves unmapped:

```powershell
cls
$SITE = "<the owner's site.local.json>"
& $PY -I -B tools\ecco_intel_drill.py site-check --site $SITE
(Get-FileHash -Algorithm SHA256 $SITE).Hash.ToLower() | Out-File -Encoding utf8 (Join-Path '<OFFLINE_EVIDENCE_DIR>' 'site.local.json.sha256')
```

The `config_hash` it prints is what the status entity's `config_hash` attribute shows once the file is loaded (T8; the
diagnostics download redacts it).

The file goes to `/config/ecco/intelligence/site.local.json`. The integration only reads it, at start-up and at a config-entry
reload. The single-file deploy route refuses everything under `/config/ecco/intelligence/`; the only way the file reaches
the host is the placement command. `-Plan` is read-only. A file already
in place is replaced only with `-ReplaceExistingSha256 <its live sha256>`, after a verified backup; the output shows sizes
and hashes only. The new file takes effect at a separately approved config-entry reload or restart:

```powershell
cls
.\tools\place-ha-site-file.ps1 -SiteFile $SITE -ExpectedSha256 <sha256> -SshHost <production alias> -Target Production -Plan
.\tools\place-ha-site-file.ps1 -SiteFile $SITE -ExpectedSha256 <sha256> -SshHost <production alias> -Target Production
```

## 4. Install the ui package first (owner approval; NOT AVAILABLE: PR-5, DP-4)

The presentation package (`home-assistant/packages/ecco_intelligence.yaml`: the pause helper, the watchdog and three
notification-only alerts) and the preferences package (`home-assistant/packages/ecco_intelligence_prefs.yaml`: the
raise-only reserve helper `input_number.ecco_advisory_reserve_raise_pct`) are installed with the established single-file
route, `tools/deploy-ha.ps1` (an allowlisted destination, staging, a sha256 check, a backup, `ha core check` and an
automatic rollback), each under its own approval and **before** the integration. Both are listed in
`deployment/ha-manifest.yaml`; nothing installs them automatically. Like every package they take effect at the one approved
restart (section 6). Turn the pause helper **on** after that restart and before the integration first starts, so the first
start computes nothing (gate G8). Map `pref.advisory_reserve_raise_pct` in the site file only once its helper exists (a
mapped helper that is missing BLOCKs the reserve items); while it is unmapped it raises nothing.

```powershell
cls
# NOT AVAILABLE until PR-5 has merged and DP-4 is decided.
.\tools\deploy-ha.ps1 home-assistant/packages/ecco_intelligence.yaml -SshHost <production alias> -Target Production -Python $PY
.\tools\deploy-ha.ps1 home-assistant/packages/ecco_intelligence_prefs.yaml -SshHost <production alias> -Target Production -Python $PY
```

The standalone dashboard and the card are optional for SHADOW (the advice is on the entities); each is a separate approved
step with the same route:

1. the dashboard file `home-assistant/dashboards/ecco_intelligence.yaml` (to `/config/ecco/dashboards/`). It is a new
   dashboard that the site's preservation policy does not protect, so when a gate pin is set the step names
   `-ExpectedSiteGate DASHBOARD_PRESERVE_GATE`; the production dashboard is never touched;
2. then its registration package `home-assistant/packages/ecco_intelligence_dashboard.yaml`: one YAML-mode
   `lovelace: dashboards:` entry, `ecco-intelligence`, for administrators only. Home Assistant merges it into the
   configuration's own `lovelace:` block; the isolated test Home Assistant proves that merge and the panel first. If Home
   Assistant does not accept it, `ha core check` fails and the route restores the previous state; the fallback is the same
   entry added to `configuration.yaml` by the owner;
3. the card: `-Source frontend/ecco-intelligence-card/ecco-intelligence-card.js -Destination
   /config/www/ecco/ecco-intelligence-card.js`, then the owner adds the resource
   `/local/ecco/ecco-intelligence-card.js?v=0.1.0` (JavaScript module) in Settings, Dashboards, Resources.

After the restart, read-only: `get_panels` lists `ecco-intelligence` in YAML mode; `.storage/lovelace_resources` holds
exactly one item for the card (type module) and no other item changed; the served card file's sha256 equals the
repository file's; the dashboard guard's `verify-live` on the production dashboard shows its protected layer intact.

## 5. Install the integration (NOT AVAILABLE: PR-5, DP-4)

The PR-5 route (`tools/deploy-ha-kit.ps1`) does what the drill exercises offline, plus the host checks:

1. local checks before any ssh call: the kit's SHA256SUMS sha matches `-ExpectedSumsSha256`, every line is an allowed
   path, the folder holds exactly the listed files, `git_sha` = this checkout's HEAD and a rebuild is byte-identical, and
   the kit is equivalent to the L3-tested kit (`-ReferenceKit`, mandatory with `-Target Production`);
2. read-only host checks: the `/config` root resolved and printed (A26), the `-Target` guard (no test marker, not
   loopback, not the test machine), the dashboard preservation gate and its pin, `/config/.HA_VERSION` =
   `-ExpectedHaVersion`, a symlink test of every segment below `/config`, one device for `custom_components` and `ecco/`,
   free space, the installed tree, the protected site file and state snapshot, the config-entry count;
3. stage under `/config/ecco/staging/<stamp>/`, never inside `/config/custom_components/`, and verify the staged copy's
   sha256 on the host;
4. back up an installed `/config/custom_components/ecco_intelligence/` to `/config/ecco-backups/<stamp>/` and verify the
   backup against its `BACKUP_SHA256SUMS`;
5. swap by atomic rename (a replaced tree moves under the staging folder; nothing is deleted);
6. verify every file in place, re-check the protected snapshot, then run `ha core check`;
7. on any failure after the swap, roll back through one rollback routine ("was rolled back" only when verified).

It never touches `/config/ecco/intelligence/site.local.json` or `/config/ecco/intelligence/state/` and never restarts
Home Assistant. `Plan` sends read-only commands only and prints every destination, the swap, the restart line and the
rollback command:

```powershell
cls
# NOT AVAILABLE until PR-5 has merged and DP-4 is decided.
.\tools\deploy-ha-kit.ps1 -Action Plan -SshHost <production alias> -Target Production -ExpectedHaVersion <version> `
    -Kit $KIT -ExpectedSumsSha256 <sha256> -ReferenceKit <the L3-tested kit> -ReferenceSumsSha256 <its sha256> -Python $PY
.\tools\deploy-ha-kit.ps1 -Action Install -SshHost <production alias> -Target Production -ExpectedHaVersion <version> `
    -Kit $KIT -ExpectedSumsSha256 <sha256> -ReferenceKit <the L3-tested kit> -ReferenceSumsSha256 <its sha256> -Python $PY
```

The PASSED block prints the backup path and **RESTART REQUIRED - separately gated, not performed**. Keep the pause helper
on until after that restart.

## 6. Restart (owner approval only; keep it short)

Custom integrations load at start-up, so Home Assistant restarts **once, only with the owner's explicit approval**, while
the owner watches.

**The latch caveat.** A Home Assistant outage longer than about 5 minutes sets `SHADOW_WOULD_AWAIT_ACK` in the existing
supervision. Keep the restart short. If the latch is set, recovery is a **supervised dongle reboot by the owner**.

## 7. Add and verify (NOT AVAILABLE: PR-5, DP-4)

1. Add the integration: Settings, Devices and services, Add integration, *ECCO Intelligence (SHADOW)*, then confirm. There
   are no fields.
2. Verify, read-only, with the pause helper still on:
   - exactly eleven entities with the contract ids (`sensor.ecco_intel_status`, ..., `binary_sensor.ecco_intel_fresh`), and
     **no `_2` suffix** (a suffix is an entity-id collision: recover as described below the go / no-go table, never by
     deleting and re-adding the entry);
   - `sensor.ecco_intel_status` reads `PAUSED` (during a collision the integration's status entity is the suffixed one,
     and it too reads `PAUSED` while the helper is on: `PAUSED` wins over `SELF_TEST_FAILED`, so the collision shows as
     the suffix and as `ENTITY_IDS` FAIL in the diagnostics);
   - the diagnostics download shows no `FAIL` in `self_test` (VENDOR_MANIFEST, TZ_EUROPE_LONDON, SITE_*, STORE_WRITABLE,
     ENTITY_IDS), `decisions` as the site-check showed them, and `cadence.poll_listener` true (the telemetry poll text
     is mapped);
   - `pause_control` reads `ON`;
   - `binary_sensor.ecco_intel_watchdog_fresh` reads `on` (PAUSED is fresh while the helper is on, gate G8) and no
     `ecco_intel_*` notification is shown.
3. Turn the pause helper **off**. The status changes to `STARTING`. The first cycle runs after the PROPOSED 180 s start-up
   grace has passed since setup, at the first poll-driven step (a few seconds after a telemetry poll) or, without polls,
   at the next minute's tick; a later un-pause runs a cycle the same way.
   The watchdog stays `on` through the change: PAUSED stays fresh for 130 s after the helper turns off, and the
   integration publishes `STARTING` at its next tick.
4. Leave every entity of the integration enabled. A contract entity disabled in the entity registry fails the self-test
   (`ENTITY_IDS`) and stops all computing. To stop it, use the pause helper (section 10) or disable the whole entry.

**Go / no-go during the first observed runs** (at least three slot cycles and 60 minutes of refreshes; for R5, until the
first next-day publication of the import rates has happened). Any no-go means section 10, then section 11:

| # | Criterion |
|---|---|
| R1 | supervision stays **SUPERVISED / stable** and the **supervision heartbeat age** stays nominal across every observed run |
| R2 | the status is a computed one (an item without its decisions or fresh inputs is `BLOCKED`, as expected), and **no gated item carries a number** it should not: none while its decisions are OPEN, none in a null status, none past `valid_until` (a live check: each item publishes its `valid_until`, which is not recorded, A17) |
| R3 | no `SELF_TEST_FAILED`. `STALE` only in gaps of at most two ticks while every mapped input and both poll texts are fresh (`input_ages` explains any longer gap). The counters `budget_exceeded` and `exceptions` stay 0. The CPU guard's headroom is read, not inferred from STALE (A49): the counter `refresh_suppressed_cpu` stays 0 and, once an hour of refreshes has run, the diagnostics' `cadence.cpu_s_rolling_hour` beside it is at most 120 s (T9's bound; the guard is 180 s), `cadence.refresh_suspended_cpu` is false and `self_test` has no `CPU_BUDGET` WARN; both readings are recorded offline. No blocking-I/O warning from `ecco_intelligence` in the HA log. `cycle_stats` (`by_kind`): refresh `total_s_p95` at most 5 s, slot `total_s_p95` at most 30 s and `total_s_max` at most 60 s; `total_s` counts the settle hold at the snapshot (up to `PROPOSED_POLL_SETTLE_S`, 3 s; a hold at a cycle's start comes before that start and is not counted) and each executor job's cool-down (`SUBMIT_COOLDOWN_S`, 0.15 s: one job in a refresh, up to three when it reads the recorder or the metrics, four in a slot cycle; `cycle_stats.timings_with_cooldown`), and the bounds include both. While the telemetry poll text moves: `cadence.polls_arriving` true, `last_trigger` `POLL`, each cycle's `poll_age_s` about the 3 s settle delay, and no item BLOCKED `INPUT_EXPIRING` |
| R4 | nothing else changed: the manual write counter, every write enable, arm and schedule, and the TOU slots are as in the baseline |
| R5 | the import rates (A42): after the first next-day publication, the status entity's `reason_codes` show `TARIFF_VERIFIED`, the import table's own code for a table that is accepted, fresh and whole. R5 reads that code's presence, as T11 does (A47): without it R5 fails, and the import table's own code stands in its place, for example `TARIFF_MISSING`, `TARIFF_NOT_FRESH`, `TARIFF_GAP`, `TARIFF_OVERLAP`, `TARIFF_FUTURE_DATED`, `TARIFF_RATE_INVALID`, `TARIFF_SLOT_INVALID` or `TARIFF_COVERAGE_SHORT` (A45). The cheap-run codes `TARIFF_NO_CHEAP_WINDOW`, `TARIFF_CHEAP_RUN_TOO_LONG`, `TARIFF_NO_PRICE_SPREAD` and `TARIFF_NO_SLOTS_AHEAD` describe the shape of a verified table (a flat tariff, or one without a clear cheap run): they stand beside `TARIFF_VERIFIED` and do not fail R5. `TARIFF_VERIFIED` implies the table fresh within its limit; `input_ages` is a live check (it is not recorded). It fails while the import events' report cadence does not fit their I-D6 limit (not yet known): that is the intended fail-closed outcome, never a reason to loosen the row. A failing R5's cause is the import table's own code in the status entity's `reason_codes`; a refusal by the runtime also leaves a `TABLE_*` note in the diagnostics' `source_notes` |

**An entity-id collision (a `_2` suffix).** Home Assistant gives an entity a suffixed id when its contract id is already
taken, for example by an entity left from an earlier install or by a state that another integration or an API call has
set. The integration then FAILs `ENTITY_IDS` and computes nothing. The ui package's "output not recognised"
notification can fire when such a state appears or when the entry is added: a symptom of the same collision. Home
Assistant keeps the eleven entity ids of a deleted entry in its entity registry's record of deleted entities (by unique
id) and gives the same ids back when the entry is added again, for as long as it keeps that record (it purges orphaned
records after a retention period), so deleting and re-adding the entry brings the suffix back (seen on the pinned Core
under L3). Recover with the pause helper still on. Steps 2 to 4 need no restart; freeing a holder that has no unique id
may need a separately approved restart (step 1):

1. find what holds the contract id (Settings, Devices and services, Entities: search for it). Freeing it changes
   something that is not part of the integration, so it is **a separate owner decision**, recorded offline against the
   R4 baseline; the install's approval does not cover it. If the owner does not change the holder, this is a no-go
   (section 10, then section 11). How the id is freed depends on what holds it:
   - an entity of the entity registry (it has a unique id): remove it or give it another id in its settings;
   - a state with no unique id (set by an API call, or a YAML entity without `unique_id`): the UI can neither remove
     nor rename it. Stop what sets it (or give the YAML entity another id); the state then goes at the next
     owner-approved restart, or the owner removes it with the REST API's delete-state call.

   The contract id must be free before step 2. Never disable one of the integration's own entities (risk 9 of
   INTELLIGENCE_HA_RUNTIME);
2. rename each suffixed entity of the integration back to its contract id (the entity's settings, Entity ID);
3. reload the ECCO Intelligence entry (a reload, not a restart);
4. verify step 2 again: eleven entities with the contract ids, no suffix, no `FAIL` in `self_test`.

The recorder keeps what it recorded under the suffixed id. When the contract id has recorded history of its own (from
whatever held it), Home Assistant logs that it cannot migrate the suffixed id's history to the contract id because that
id is already in use. That warning is expected after this recovery; the 72 h clock has not started (the helper is on).

## 8. Technical acceptance: 72 hours

The clock starts when the integration is installed and un-paused with the site file in place. Any integration failure (a
FAIL below) restarts it; an upstream outage (the dongle, the network, a tariff feed) only pauses it; a pause or an
approved restart stops it. Measured from the diagnostics downloads, the recorder and the HA log; synthetic-test success is
no evidence here. One table (amendment A13); all thresholds PROPOSED.

**The diagnostics downloads (A47, A50).** The download holds no history beyond `cycle_stats`, which keeps the last
`PROPOSED_CYCLE_STATS_N` = 4800 runs: more than the 72 h can start at the highest cycle rate (at most 4713 starts 55 s
apart plus 26 schedule slots a day). One download taken at the end of the 72 h therefore holds every run of a window
whose wall-clock span is at most 72 h, and T1, T5 and T9 are read from its `runs` rows that started inside the window
(not from `by_kind`, which summarises every kept run). An upstream outage pauses the clock while the cycles go on, so
after a paused stretch the window spans more than 72 h of wall time and its first hours can fall before the end
download's oldest kept run: read those hours from the earlier downloads (the oldest-row rule below). `cycle_stats` lives
in memory: a Home Assistant restart or a reload of the entry empties it, so take a download before any approved restart
or reload too, and read the window across the downloads. Keep every download in `<OFFLINE_EVIDENCE_DIR>`. A download is
also a convenient moment for T7's live read of the entities; take one at least once a day so that a lost end download
leaves at most a day unproven. The window is proven only where the kept rows reach: the oldest row of the download that
covers the clock's start must be at or before it; hours no kept row covers leave T1, T5 and T9 unproven for those hours.

| # | Check | Pass |
|---|---|---|
| T1 | every schedule slot published | each slot has a `SLOT` row with outcome `published` in `cycle_stats`, read from the downloads' `runs` rows (above); `runs_published` = `runs_started` while not paused |
| T2 | no failure | zero `SELF_TEST_FAILED`; `exceptions`, `budget_exceeded`, `late_results_discarded` and `entity_write_failures` stay 0 |
| T3 | freshness | `STALE` in at most 1 % of minutes while the inputs are fresh, in gaps of at most 2 ticks (status history); no dongle item BLOCKED `INPUT_EXPIRING` while both poll texts move |
| T4 | the watchdog | `binary_sensor.ecco_intel_watchdog_fresh` stays on, judged from its first render with the status entity present after each Home Assistant start, which comes within 600 s of the start or of the window start (a later first render fails T4): before it, Home Assistant shows the state it saved for the watchdog before the restart, and a first render while the status entity does not exist yet is off, which nothing acts on and which T4 does not judge (the card shows "not publishing" and no figure while the status entity is absent); after it, a missing status entity fails T4; no `ecco_intel_*` notification |
| T5 | cycle times and stability | cycle `total_s_p95` at most 30 s and maximum at most 60 s, refresh `total_s_p95` at most 5 s, computed from the `total_s` of the downloads' `runs` rows that started inside the 72 h (above; `cycle_stats.by_kind` covers every kept run and is only a cross-check); `total_s` includes the settle hold at the snapshot (up to 3 s) and every job's 0.15 s cool-down (R3), and the bounds include them; no blocking-I/O warning; supervision stable throughout (R1) |
| T6 | nothing else changed | the R4 baseline equal at the start and at the end |
| T7 | the null rule | in the recorded states no number in a null status or for an item whose decisions are OPEN. `valid_until` is not recorded (A17: a timestamp-only attribute), so "no number past `valid_until`" is a live check: at each live read of the entities (each item's state and its `valid_until` attribute, read for example at the time of each diagnostics download; the download itself carries neither), no item shows a number while the time is past its own `valid_until` (the runtime half, the publish horizon, is pinned by the L2 suites) |
| T8 | the configuration | the status entity's `decisions` map equals the owner's recorded decisions (the site file's decisions block), `provenance_ok` is true, and its `config_hash` equals the site-check's `config_hash` (the offline sha256 prefix) |
| T9 | CPU and cadence | `cadence.cpu_s_rolling_hour` p95 at most 120 s per hour (the guard is 180 s) and `refresh_suppressed_cpu` 0 (A49: tracked explicitly, never inferred from STALE). The p95 is taken over the 72 h from the downloads' `cycle_stats` rows (above): at each run's `started_at`, the sum of `cpu_s` over the runs that started in the hour before it (the guard's own rolling sum, to within one cycle's duration); each download's `cadence.cpu_s_rolling_hour` and `cadence.refresh_suspended_cpu` are recorded beside it, and `self_test` shows no `CPU_BUDGET` WARN in any download. Logged: `cadence.tick_poll_phase_s` (the phase of the tick body's last run, `cadence.last_tick_at`, against the last poll seen: whichever ran it, the tick, the run at a cycle's first step, the catch-up at a cycle's end or the deadline run inside a cycle; not the tick's own phase, which follows the last cycle's end) and each cycle's `poll_age_s` (the age of the last poll at the cycle's start) |
| T10 | resources | HA memory slope and recorder database growth against the live baseline (A17): recorder states rows per day near the expected 15.8k (one cycle per poll, 11 entities), attributes rows far fewer, no steady RSS growth |
| T11 | the import rates (A42) | on each day, from the next-day publication to local midnight, the import rates are VERIFIED in every computed cycle (`TARIFF_VERIFIED` in the status entity's recorded `reason_codes`), except during a documented tariff-feed outage, which pauses the clock (above). T11 counts computed cycles only (A45): a null status (`STALE`, `PAUSED`, `STARTING` or `SELF_TEST_FAILED`) carries no tariff code and is not counted here; `STALE` stays judged by T3, `SELF_TEST_FAILED` by T2, and `PAUSED` and `STARTING` by the pause rule (above). `TARIFF_VERIFIED` implies the table fresh within its limit; `input_ages` is a live check (it is not recorded). A cycle that fails because the import table is not usable (missing, refused, gapped or not fresh) also shows INFO `CHARGE_WINDOW_NOT_PRICED` on the charge-window items wherever a TOU window stands; one that fails only because the table ends before the search period ends (`TARIFF_COVERAGE_SHORT`) shows it only when the table does not price the whole TOU occurrence (A41) |

## 9. Advisory acceptance: seven more days, and the capacity check

**Seven days of quality monitoring** before the advisory system is declared operationally accepted. Production data
only, never fixtures: synthetic-test success is not real-household accuracy.

| # | Check | Pass |
|---|---|---|
| Q1 | coverage | the OK share per item per day, with every block explained by its blocker codes |
| Q2 | `predicted_day_load` | MAE and p10-p90 coverage against the recorded actuals; coverage near 0.8, the error no worse than a naive persistence baseline |
| Q3 | `pv_tomorrow` | as Q2, against the recorded PV energy |
| Q4 | morning SOC | the actual morning SOC is at or above the floor whenever `predicted_morning_soc` was OK, counting only nights where the inverter's configured target was at least the planned target and grid import was seen in the window (the advice never says charging will happen) |
| Q5 | stability | `charge_target` changes at most 3 times a night |
| Q6 | inputs | zero blockers caused by an input whose entity is not re-reported within its I-D6 limit, and zero computed cycles without `TARIFF_VERIFIED` (before the next-day publication, with neither `TARIFF_VERIFIED` nor `TARIFF_COVERAGE_SHORT`) in the status entity's recorded `reason_codes`: the mapped import table is then missing, refused, gapped, not fresh or (after the publication) short of the search period, and its own code stands in place of `TARIFF_VERIFIED`; it blocks nothing, yet it counts as an input fault (A42, A45). Q6 reads the import table's own code as R5 and T11 do (A47): the cheap-run codes beside `TARIFF_VERIFIED` (`TARIFF_NO_CHEAP_WINDOW`, `TARIFF_CHEAP_RUN_TOO_LONG`, `TARIFF_NO_PRICE_SPREAD`, `TARIFF_NO_SLOTS_AHEAD`) describe a verified table's shape and are not counted. The import table's own codes listed here are examples: `TARIFF_MISSING`, `TARIFF_NOT_FRESH`, `TARIFF_GAP`, `TARIFF_OVERLAP`, `TARIFF_FUTURE_DATED`, `TARIFF_RATE_INVALID`, `TARIFF_SLOT_INVALID`, `TARIFF_UNIT_IMPLAUSIBLE` and, after the publication, `TARIFF_COVERAGE_SHORT`. A table that is refused, gapped or not fresh also shows INFO `CHARGE_WINDOW_NOT_PRICED` on the charge-window items wherever a TOU window stands (A41); before the next-day publication the residual shows it too, so the import table's own code is what tells them apart (T11 says when the residual shows it); a refusal by the runtime also leaves a `TABLE_*` note in the diagnostics' `source_notes` |
| Q7 | the TOU claim, per weekday | on every night of each weekday the charge window was published, grid import was seen in the TOU grid window. Register 248's upper bits are undecoded (possibly a weekday mask), so the claim stays at most UNCERTAIN; any mismatch blocks operational acceptance and opens a firmware item to expose register 248 |
| Q8 | capacity | the learned capacity (read read-only, outside the runtime) agrees with the I-D3 stated value within the I-D4 band |
| Q9 | efficiency | the round-trip efficiency measured from the recorder's battery energy in and out, compared with I-D5 |

Q2 and Q3 come from the recorder. The `accuracy` entity is no Q2 or Q3 figure: it pools every scored `load_kwh` kind of
the last 7 days (`next_1h`, `to_next_cheap`, `cheap_window`, `day`, `morning`, `overnight`, `to_useful_pv` or
`to_useful_pv_from_now`), weighted by each kind's n, holds no PV forecast and lags one slot (a slot cycle reads it
before that slot's scoring step). If the charge window stays BLOCKED, its n = 0 is expected.
After Q8 and Q9 a new OWNER_RECORD retires the `-provisional` record slugs (amendment A16).

**The capacity check (amendment A25).** v0.1 maps no learned or register-204 capacity source: I-D3 rests on
the owner's stated value (`SITECONFIG_VALUE`, provisional), and the Home Assistant capacity helper may be mapped as a
second source (`capacity.helper_kwh`, which then has to agree within the I-D4 band at every cycle). The learned figure is
checked outside the runtime instead: it is read read-only (the battery runtime model's learned capacity, and
only while its basis says it was measured) at commissioning and during the 72 h and 7-day acceptance, and compares it with
the I-D3 value. A difference beyond the I-D4 band goes back to the owner; nothing is changed automatically. A runtime
learned-capacity source with a measured-basis condition and its own freshness class is a later change, not v0.1.

## 10. Pause (any time; never a restart)

Turn `input_boolean.ecco_intel_paused` **on**. The status reads `PAUSED`, nothing is computed, and the last values remain
only in `last_good`. A cycle already running when the helper is turned on is discarded when it ends: its result is not
published and not recorded. Alternatively disable the config entry.

## 11. Upgrade, rollback, uninstall (NOT AVAILABLE: PR-5, DP-4)

- **Upgrade:** build and verify the new kit (section 2), pause, then `deploy-ha-kit.ps1 -Action Upgrade` (backup, then
  swap). Restart only with approval (section 6), then verify (section 7).
- **Rollback:** pause, then `deploy-ha-kit.ps1 -Action Rollback -BackupStamp <stamp>`: it verifies
  `/config/ecco-backups/<stamp>/custom_components__ecco_intelligence/` against its `BACKUP_SHA256SUMS`, stages and verifies
  the copy, backs up the current tree and swaps. Restart with approval, then verify.
- **Uninstall:**
  1. pause;
  2. delete the integration entry in the UI (`Uninstall` is refused while Home Assistant's config-entry store names
     `ecco_intelligence`);
  3. `deploy-ha-kit.ps1 -Action Uninstall`: the tree is backed up and moved to `/config/ecco/staging/<stamp>/uninstalled/`,
     never deleted;
  4. only for a full removal, and only once step 2 is done: retire the PR-6 files (the two packages, the dashboard's
     registration package, the dashboard and the card) one at a time with `deploy-ha.ps1 -Action Retire -Destination
     <file>` (moved to `/config/ecco-backups/<stamp>/`, never deleted). The presentation package holds the
     pause helper: retired while the entry still exists, it would leave the integration with no pause control at the next
     restart, which the integration reads as not paused (`PAUSE_CONTROL_MISSING`) and so computes. Never retire it before
     the entry is deleted, and never as part of an upgrade or a rollback;
  5. restart with approval (one restart covers steps 3 and 4).

  `site.local.json` and `state/` are the owner's data and stay where they are.

  **What Home Assistant itself recorded.** The integration's code makes no registry or storage call. When the entry was
  added, Home Assistant recorded the config entry, the eleven entity-registry entries and one device-registry entry (the
  service device *ECCO Intelligence (SHADOW)*). Deleting the entry in step 2 removes the config entry and the device and
  takes the eleven entities out of the entity registry, but Home Assistant keeps their ids in the registry's record of
  deleted entities (by unique id): adding the entry again later gives the same eleven ids back, a suffixed id included,
  for as long as Home Assistant keeps that record (it purges orphaned deleted-entity records after a retention period;
  seen on the pinned Core under L3 within minutes; section 7 says how to recover from a collision). Rollback and
  upgrade keep the entry, so these records stay. The recorder's history of the entities' recorded attributes stays
  until the recorder's own purge removes it.

Every command ends with `ha core check` and leaves the restart to the owner:

```powershell
cls
# NOT AVAILABLE until PR-5 has merged and DP-4 is decided.
.\tools\deploy-ha-kit.ps1 -Action Upgrade -SshHost <production alias> -Target Production -ExpectedHaVersion <version> `
    -Kit $KIT -ExpectedSumsSha256 <sha256> -ReferenceKit <the L3-tested kit> -ReferenceSumsSha256 <its sha256> -Python $PY
.\tools\deploy-ha-kit.ps1 -Action Rollback -BackupStamp <stamp> -SshHost <production alias> -Target Production -ExpectedHaVersion <version>
.\tools\deploy-ha-kit.ps1 -Action Uninstall -SshHost <production alias> -Target Production -ExpectedHaVersion <version>
```
