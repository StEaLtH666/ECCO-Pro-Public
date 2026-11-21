# ECCO Intelligence: the Ghost diagnostics update (U2), the second supervised Home Assistant update: runbook

**Status: PREPARED OFFLINE, NOT RUN, NOT READY.** Nothing in this document has been done on Home Assistant. The update has
never run in a real Home Assistant (section 12). It is not ready for a go until the preconditions of section 5 that are marked
OPEN are closed (P1, P3, P4, P5, P6, P7 and P9 at the time of writing). Every live step below needs its own owner
authorisation, in the session, at the time (column "own authorisation" of the step table).

> **Every live step in this runbook is NOT AVAILABLE** until all of these hold:
>
> 1. Every precondition of section 5 is closed, and the owner has recorded the acceptance items of section 4.
> 2. The owner has reserved a quiet period, is present, has made a fresh **protected** full backup (step 2) and has given the
>    final installation go on the completed checklist (`GHOST_SECOND_UPDATE_GO_CHECKLIST.md`).
> 3. The owner has given the go for each live step, one by one. A go for one step is not a go for the next.
>
> **No automatic installation or live access is authorised.** Nothing is installed, restarted or read live until those three
> hold. ASSISTED and AUTONOMOUS stay disabled; Intelligence stays SHADOW (advice only).

**Notation.** Placeholders are written `<like this>`. `<production alias>` is the owner's SSH alias for the production host.
`<OFFLINE_EVIDENCE_DIR>` is the owner's local evidence folder; it is never in a repository, and nothing that holds a site value
(a download, a read-back, a listing) is ever copied into a repository. `<checkout>` is a clean checkout of the chosen commit.
`<PY>` is a Python 3.12 interpreter with PyYAML installed in that interpreter itself. `<version>` is the content of the host's
Home Assistant version file as read in step 1. Every PowerShell block starts with `cls`. This runbook quotes no secret, host,
address, token, entity id or site value: it names roles. It reuses the commands and tools of
[`INTELLIGENCE_SHADOW_INSTALL_RUNBOOK.md`](INTELLIGENCE_SHADOW_INSTALL_RUNBOOK.md) ("the install runbook", cited as "install
runbook N" by section number) and invents none.

## 1. The owner's directions, and what this update is and is not

The owner's words (20 and 21 Nov 2026), quoted:

> "Keep Ghost as the second update, with its own restart and rollback requirements."
>
> "Ghost remains a separate second update with its own backup, restart and rollback verification."
>
> "For a failed advice write, retain an incident record and show the failure honestly. After a subsequent verified successful
> write, allow current health to recover while retaining the earlier incident for diagnosis."

| The direction | Where it is met in this runbook |
|---|---|
| a separate second update | it is its own update (U2), after the first (a read-only dashboard card, U1) or deliberately independent of it (P6); nothing of U1 is done in the same window |
| its own backup | step 2 (the owner's protected full backup, made for this update) and the deploy tool's verified backup of the installed folder (step 5) |
| its own restart | step 7: one restart, approved separately, short (the latch caveat of install runbook 6) |
| its own rollback verification | section 10: the order, a proof for each, measured against the baseline of step 1 |
| a failed advice write keeps an incident record and shows the failure honestly | section 2.3: STORE_RECORD is WARN while an incident is open, the incident is kept in memory and, once closed, in a small table |
| health recovers only after a later verified write; the earlier incident is kept | section 2.3: PASS only after a verified write; the closed incident stays listed and is written to the table |

**What U2 is.** The second supervised update, and unlike the first it is not read-only: it replaces the Intelligence integration's
code (the kit built by `tools/build_ha_integration.py`) on the live host, needs one Home Assistant restart, and adds durable
writes: a per-slot advice log table and a small advice incident table, both created lazily inside the existing scorecard file. It
adds the Ghost diagnostics block to the diagnostics download and the incident-aware health of the advice log. It is diagnostics
only.

**What U2 is not.** It is not a change of any published value, entity, helper, schedule, mode or advice: the eleven entities
and the contract are unchanged and Intelligence stays SHADOW (advice only). It is not acceptance of Intelligence, and it says
nothing about forecast accuracy: the Ghost block is a simulation, evidence for the owner's decision and never a decision. It is
not U1, R9, Stage 3 or the PV gate, each of which has its own track.

## 2. What changes on the host, and what does not

### 2.1 The artefacts

| # | Artefact | Where | How it gets there | Reversible by |
|---|---|---|---|---|
| A1 | the Intelligence integration folder, replaced as a whole by the kit (57 files; 5 new, 5 changed, 47 identical to a kit built from the merged base) | `/config/custom_components/ecco_intelligence/` | `tools/deploy-ha-kit.ps1 -Action Upgrade` (stage, verified backup, atomic swap, `ha core check`; no restart) | `-Action Rollback -BackupStamp` (section 10) |
| A2 | the table `advice_log`, created by the first advice write of the running integration | inside `/config/ecco/intelligence/state/scorecard.sqlite3` | the running integration, at a slot cycle's store step; no tool creates it | it stays, unused, after a rollback (section 10) |
| A3 | the table `advice_incident` (at most 10 rows), created only after a verified advice write that follows an incident | the same file | the running integration; not at start-up, not when the file is opened, not by an advice write | the same |
| A4 | the staging folder and the backup folder of the Upgrade run | `/config/ecco/staging/<stamp>/` and `/config/ecco-backups/<stamp>/` | the deploy tool; nothing is ever deleted | kept; the owner cleans up when the owner decides |

Not written by this update: the site file, any helper, entity, automation, package, schedule, dashboard, resource, firmware,
the dongle, the inverter or the time-series database (`store_meta.json` and the scorecard's own tables are written exactly as
before). The one helper the procedure touches is the existing pause helper, which the **owner** turns on before the upgrade and
off after the restart checks (install runbook 10 and 11), exactly as the install runbook says.

### 2.2 The kit's files

The kit has 58 files (36 vendored modules, 20 integration files and the generated manifests); the installed folder holds 57
of them (the root `VENDOR_MANIFEST.json` is not installed). Against a kit built the same way from the merged base (the tree
this work branched from; recorded during this preparation, not pinned by a suite), five files are new and five change:

| New files | Role |
|---|---|
| `_vendor/intelligence/ghost.py`, `ghost_compare.py`, `ghost_feed.py` | the Ghost simulation, its diagnostics-only comparison block and its input builder (pure, read-only) |
| `_vendor/intelligence/net_value.py` | the read-only battery value ledger the Ghost uses |
| `runtime/ghost_link.py` | the glue that runs the Ghost block in the executor when the diagnostics are downloaded |

| Changed files | What changes |
|---|---|
| `_vendor/intelligence/scorecard.py` | the advice log table, the verified write (a same-connection read-back after the commit), the incident table, the age bound |
| `runtime/store.py` | the health ledger (`AdviceHealth`: incidents, verified writes), the advice write inside the slot cycle's store step, the read-only reads of the two tables |
| `coordinator.py` | feeds the ledger after each slot cycle's store step, STORE_RECORD, the log lines, the stored-incident read for the download |
| `diagnostics.py` | the `ghost` block and the `advice_incidents` block (with its `stored` member) in the download; no new top-level key |
| `VENDOR_MANIFEST.json` | the hashes of the above (the start-up self-test reads it) |

The install baseline (step 1) records what is really installed; the comparison block of 8.1 lists exactly which files differ from
the owner's installed folder. If the installed folder is not the merged base's kit, the difference is read and explained before
any write.

### 2.3 What the owner will see after the update

All of it is in the diagnostics download (Settings, Devices and services, ECCO Intelligence, Download diagnostics) and the Home
Assistant log. Nothing new appears on a dashboard and no entity is added.

- **The durable write.** One row per kind (charge target, Dump to Grid) per slot cycle in `advice_log`: 25 slot cycles a day (every
  full hour and 21:30, local time), 26 on the day the clocks go back, so at most 52 rows a day (50 on a normal day). Rows older
  than an age bound of 400 days are deleted at write time, so the table settles near 21 000 rows (a few MB). Every slot cycle's
  advice is its own row, also when it equals the last (no deduplication; the one skip is the same advice published again inside
  the validity of its own previous row within one slot cycle). The table is created by the first advice write, not at start-up.
- **A verified write.** After the commit, the connection that wrote the rows reads each back by its id and compares kind, issue
  time and content hash. That proves exactly this much and is **not** a durability or fsync proof (section 12).
- **STORE_RECORD** (a self-test check in the download). Before a slot cycle has run after the start it is not shown. INFO (never
  PASS) while a run has written and verified nothing yet. PASS only after a verified write (its text: "the scorecard step
  completed; the advice log write is verified"). **WARN while an advice write incident is open** ("advice log not verified (`<class name>`): `<n>`
  slot(s) missed, `<n>` failed/unverified since start; PASS needs a verified write"): the failure is shown honestly. It
  returns to PASS only after a **later verified write**. A slot cycle that wrote nothing changes nothing. After a restart nothing
  is assumed: PASS shows only after that run's own first verified write.
- **Incidents.** A failed or unverified advice write (or a store step that times out or raises) opens an incident, kept in memory
  (the newest 10): when it began and last failed, the attempts, the slot cycles missed, the exception class name as the reason
  (never a message) and the issue times of the advice that could not be written. After a later verified write the incident is
  closed and **kept**, and written to `advice_incident` (a plain commit, not read back). The download shows `advice_incidents`
  (the open incident, the closed ones, `verified_writes`, `last_persist`) and, in its `stored` member, what the table holds
  (read-only, in the executor, at most 5 s). The counters `advice_write_failures` and `advice_unverified_writes` are history and
  are never reset; `advice_current_failure` is 1 while an incident is open.
- **The Ghost block** (`ghost`, computed only when the download is made, read-only, in the executor, at most 30 s): the existing
  schedule against Intelligence's logged advice. It says `NO_ADVICE_LOGGED` or `INSUFFICIENT_HISTORY` until enough advice and history
  are logged (the block needs at least a day): that is expected for the first day and is not a failure. Its numbers are site-derived (dates, pence, SOC, kWh): a
  download is kept in `<OFFLINE_EVIDENCE_DIR>` and reviewed before it is shared.
- **Log lines** (class names only, never a message, a path or a value): one warning when an incident opens and one line when it
  closes.
- **Slot cycle time.** The advice write and its read-back run inside the slot cycle's store step, so a slot cycle's `store_s` grows by
  the write's own time. The install runbook's R3 bounds (slot `total_s` p95 at most 30 s, maximum at most 60 s) still apply.

### 2.4 The write statement

What is written, and by whom. The integration writes only under `/config/ecco/intelligence/state/`: `store_meta.json` and the
scorecard file, as before. The new writes are the advice rows (A2) and the incident rows (A3) in the scorecard file, and nothing
else. It writes nothing to Home Assistant entities, helpers, schedules, the inverter or the dongle, calls no service, and fires no
event; the Ghost block and the stored-incident read open the file read-only (`mode=ro`). The old scorecard behaviour and the
store's start-up are unchanged: opening the file creates neither table. The deploy tool writes A1 and A4 only, and never touches
the site file or the state folder (it reads their hashes before and after and refuses if they changed).

### 2.5 What does not change

The eleven entities and their contract, every published value's rules, the mode (SHADOW), the pause helper, the watchdog, the
site file, the decisions, the engine's rules, the schedule, the recorder reads, and the scorecard's own tables and writes. **No
entity, helper, service, package or dashboard is created or edited by this update** (RG-F3: section 4, D-U2-6). The integration's
version string in its manifest is unchanged. The files of the sensor and binary sensor platforms, the shared entity mixin, the
constants, the config flow, the package init and the integration manifest are byte-identical to the merged base's (a
`git diff` of this preparation; not pinned by a suite); the suite pins that the platforms are sensor and binary sensor only and that
the integration has eleven contract entities.

## 3. The artefacts and their hashes

The kit is built by the repository's own tool, `tools/build_ha_integration.py --out <dir> [--git-sha S]`, from the working tree
(offline, byte-deterministic, outside the repository). Two reference builds are pinned by `test_ghost_update_docs.py`, which
rebuilds the kit and compares:

| Build | Command | Files | `SHA256SUMS` sha256 |
|---|---|---|---|
| no commit recorded | `--out <dir>` | 58 (36 vendored modules, 20 integration files) | `ec9f31955ef635e8bf3f02c690f26b86cfecb5982f5b497796085196c7612525` |
| the fixed reference commit | `--out <dir> --git-sha 0000000` | 58 (the same) | `41fe3ab03b9222dcba476af9d1afdf7ea2bda8dd8b00ea3bef6485c3b0ae4ac1` |

The two differ only in the two `VENDOR_MANIFEST.json` lines (the recorded commit). The kit that is **installed** is built with
`--git-sha` of the commit it is installed from (the deploy tool compares it with the checkout's HEAD and rebuilds it), so its
`SHA256SUMS` sha256 differs from both numbers above in those two lines only. The install runbook's equivalence rule applies:
the kit is accepted when its sums equal the reference kit's, or equal them except those two lines with manifests that differ only
in `git_sha`.

These numbers hold for the kit sources as reviewed. Any change of a kit source (the coordinator, the diagnostics, the runtime
store, the vendored modules, anything the build reads) changes them: the suite fails and this document is updated in that
change, and the reviews, the L3 run (P1) and the owner's acceptance are repeated. The base kit's numbers (53 files; the same
command without `--git-sha` gives `47391f0d67144739774034e471486814dae2fd47229a130aae8109968a70ee40`) are recorded for the
baseline comparison and are not pinned.

## 4. The owner's acceptance items

Decisions are the owner's. This table lists them; it decides none. "Open" means no ruling is recorded.

| # | Item | What it is, as built | Status |
|---|---|---|---|
| D-U2-1 | the durable write | the integration newly writes advice rows to `advice_log` in the scorecard file (one per kind per slot cycle) | **open**: nothing is installed without the owner's acceptance; the owner directed per-slot records with bounded retention and no deduplication |
| D-U2-2 | the lazily created tables | `advice_log` at the first advice write, `advice_incident` only after the first verified write that follows an incident, neither at start-up | **open** |
| D-U2-3 | per-slot logging and its bounds | at most 52 rows a day, an age bound of 400 days (PROPOSED: an engineering suggestion, not an owner value), at most 10 incidents kept | **open**: confirm or change; a change is a code change, so a new kit, new hashes, and the reviews, P1 and this document repeated |
| D-U2-4 | STORE_RECORD semantics | INFO before the first verified write, WARN while an incident is open, PASS only after a verified write, the incident kept (section 2.3) | **open**: confirm the wording and that it is the behaviour the owner directed |
| D-U2-5 | the restart | one restart, short, approved separately, the owner watching; an outage of more than about 5 minutes sets the supervision latch (install runbook 6) | **open**: the owner chooses the window |
| D-U2-6 | RG-F3 for U2 | **this update creates no entity** (section 2.5), so no new entity can be exposed; the two voice-assistant exposure settings stay the owner's separately tracked F3 issue | **open**: the owner says whether the treatment decided for U1 carries over; this is not acceptance of F3 and not permission to introduce new exposed controls |
| D-U2-7 | the withdrawn-before-window treatment of `advice.followed` | a row that is followable but was withdrawn by a later BLOCKED row before its window took effect is still counted as followed in `advice.followed`; what the simulation really acted on is `advice_in_force_hours` | **open**: an owner decision; not decided here |
| D-U2-8 | `EXPORT_DIFF_EPS_KWH` | 0.001 kWh (the resolution of the recorded energies): below it an export difference is arithmetic noise; above it, with an unverified export price, the verdict is `NOT_ASSESSED_EXPORT_UNVERIFIED` | **open**: an owner decision; not decided here |
| D-U2-9 | the commit to install from, and the order against U1 | the branch commit after green CI, or the merge commit; U1 first or deliberately independent | **open** |

## 5. Preconditions

The update is **NOT READY** while any line below is OPEN. At the time of writing the OPEN lines are P1, P3, P4, P5, P6, P7 and P9.

| # | Precondition | Status |
|---|---|---|
| P1 | **The L3 (WSL) kit-equivalence reference run, repeated on the exact kit.** It has not been repeated since the kit changed. It must show, on the isolated test instance pinned to the production Home Assistant and Python versions: (a) the exact kit installs through the same route (`deploy-ha-kit.ps1 -Target Test`), Home Assistant loads it, no FAIL in the self-test, the eleven entities and no suffix; (b) at least three slot cycles in the real Home Assistant, with two advice rows per slot, `advice_verified` true, STORE_RECORD absent then PASS, and the tables created lazily; (c) **the executor reads in the diagnostics download observed in the real Home Assistant**: the stored-incident read and the Ghost block's read of the advice log run in the executor, within their budgets, with no blocking-I/O or slow-callback warning from the integration; (d) **the log lines observed in the real Home Assistant**: the warning when an incident opens and the line when it closes, class names only, induced on the isolated instance only (never on production); (e) an incident open at a restart is gone after it (only the logged warning remains); (f) the run's `SHA256SUMS` sha256 recorded: it is `-ReferenceSumsSha256` of the production run | **OPEN** |
| P2 | independent review of the code (the advice log, the verified write, the incident health), findings fixed, the kit unchanged since the reviewed build (proven by the build comparison of section 3) | closed (offline) |
| P3 | independent review of these documents and their suite | **OPEN** |
| P4 | CI green on the exact commit (the branch has not been pushed and has no pull request) | **OPEN** |
| P5 | the owner's M2 private-pattern scan on the exact commit, generated assets, commit metadata and pull request text included | **OPEN** |
| P6 | U1 finished (its first look done and its record filed), or the owner deliberately decides U2 is independent of it; never both in one window | **OPEN** |
| P7 | the owner's rulings on D-U2-1 to D-U2-9 recorded | **OPEN** |
| P8 | the offline gates green on the exact commit: the suites, the kit build comparison, the mock-root drill with this kit and the PowerShell parse (step 0) | closed at the time of writing; repeated at step 0 |
| P9 | the reference kit and its `SHA256SUMS` sha256 from P1 recorded offline (the Production route refuses without them) | **OPEN** (follows P1) |

## 6. Go / no-go on the day

Go only when **every** line holds; otherwise stop: this is a no-go. These are the install runbook's gates G2 to G6, G8 and G9
as they apply to an upgrade (its G7, the site file, does not apply: the site file is never touched).

| # | Criterion |
|---|---|
| U2-G1 | section 5 is closed and the owner's final installation go is given on the checklist; the commit is the one P4 and P5 ran on |
| U2-G2 | the owner has reserved a quiet period, is present, and no other supervised live step is in progress (U1 included) |
| U2-G3 | the owner has made a fresh **protected** full backup in the Home Assistant UI (step 2). A backup made over SSH is full but UNPROTECTED: no session handles a backup encryption password |
| U2-G4 | the baseline (step 1) shows supervision SUPERVISED and stable with the heartbeat age nominal, every write enable, arm and schedule off, the manual write counter noted, Intelligence SHADOW with a fresh result, the pause helper's state noted and the config entry loaded |
| U2-G5 | the host's Home Assistant Core and Python versions, re-read read-only, equal the versions the L3 run pinned (P1) |
| U2-G6 | the kit verifies against its `SHA256SUMS`, is equivalent to the L3-tested kit, the offline suites are green and the mock-root drill passes (step 0) |
| U2-G7 | the baseline of step 1 is saved: every listing and copy below is in `<OFFLINE_EVIDENCE_DIR>`, the diagnostics download taken before the restart is among them |

## 7. The steps

| Step | What | Who | Offline / live | Read-only / write | Own owner authorisation | Expected result | Stop condition |
|---|---|---|---|---|---|---|---|
| 0 | offline gates on the exact commit: the suites, the kit build and compare (8.0), the drill on a marked mock root, the PowerShell parse, section 5 | COORDINATOR | offline | no live access | not a live step | hashes as pinned (section 3), the drill PASS, P1 to P9 as the checklist says | any new failure; a hash that is not the pinned one; a changed commit repeats the gates and the scans |
| 1 | live read-only baseline: Core and its version, the integration folder listing (hashes and sizes), the state folder listing, the log lines, the owner's reads in the UI, and the diagnostics download taken before the restart (8.1) | COORDINATOR (reads), OWNER (UI reads and the download) | live | read-only | **yes** (a live read) | every listing saved; Core running; U2-G4 holds; the comparison with the kit is as 2.2 says | Core not running; Intelligence not SHADOW or not fresh; supervision not stable; a listing that cannot be read |
| 2 | the owner's protected full backup in the Home Assistant UI; its name and time noted offline, never its password | OWNER | live (UI) | the owner's own backup action | the owner's own action | a protected backup exists | no protected backup |
| 3 | PAUSE: the owner turns the pause helper on (install runbook 10 and 11: pause before an upgrade) | OWNER | live (UI) | **write** (the existing pause helper, as always) | **yes** | the status reads PAUSED; the watchdog stays fresh (PAUSED counts as fresh while the helper is on); no cycle is computed | anything but PAUSED within a few minutes |
| 4 | live read-only: the status reads PAUSED, then, after the longest cycle has ended, the scorecard file's hash and size and the listings again (8.4) | COORDINATOR | live | read-only | **yes** | the state listing is stable across two reads one minute apart | the file changes while paused |
| 5 | stage the new kit with the repository's own tool and verify hashes: `deploy-ha-kit.ps1 -Action Plan` (read-only), then `-Action Upgrade` (8.5) | COORDINATOR | live | Plan read-only; Upgrade **write** (A1, A4) | **yes**, for the Upgrade separately | `ECCO INTELLIGENCE KIT UPGRADE PASSED`, the backup path printed (record its stamp), `HA check : passed`, **RESTART REQUIRED - separately gated, not performed** | any failure line; NO CHANGE; a hash mismatch; the tool's own rollback message; ROLLBACK NOT CONFIRMED |
| 6 | live read-only, before any restart: the installed folder equals the kit, the state folder and the site file are untouched (8.6) | COORDINATOR | live | read-only | **yes** | `INSTALLED TREE EQUALS THE KIT`; no line of difference for the state folder | any difference |
| 7 | **the restart**: the owner restarts Home Assistant, once, short, watching; Core running again before and after the checks of 8.7 | OWNER | live | the owner's restart | **yes, its own approval, separate from the Upgrade** | Core running, the integration loads, no repair or error line, the outage well under 5 minutes | an outage of more than about 5 minutes (the latch: a supervised dongle reboot by the owner); the integration does not load; a repair or error line |
| 8 | live read-only, still paused: the load checks and a diagnostics download (8.8) | COORDINATOR (reads), OWNER (the download) | live | read-only | **yes** | status PAUSED; no FAIL in `self_test` (the VENDOR_MANIFEST check passes on the new kit); `advice_incidents` present; eleven entities, no suffix; watchdog fresh | a FAIL; the old code still running (no `advice_incidents` block); a new entity; a `_2` suffix |
| 9 | UN-PAUSE: the owner turns the pause helper off; the status goes to STARTING, then a computed one after the start-up grace | OWNER | live (UI) | **write** (the pause helper) | **yes** | a computed status, SHADOW | `SELF_TEST_FAILED`; no computed status after the grace |
| 10 | after-checks within the first slot cycles (at least the next two slot times): status SHADOW and fresh, STORE_RECORD as designed, the advice rows two per slot cycle, no new entity, no error or budget line, no change of any published value against the baseline (8.10) | COORDINATOR (reads), OWNER (downloads) | live | read-only | **yes** | the checks of 8.10 | any of the stop lines of section 9 |
| 11 | close-out: the evidence is filed offline; the status update; a post or a push only on the owner's go | COORDINATOR | offline | local files and local commits | **yes** for a post or a push | evidence filed | none |

No step restarts Home Assistant except step 7, which is the owner's. A step that would need a second restart is out of scope and
stops the update.

## 8. The steps in detail

**How the blocks work.** Each PowerShell block sets its own variables and moves to `<checkout>` where it needs the repository's
tools, so it runs alone in a fresh Windows PowerShell 5.1 console. Fill the placeholders in its first lines. Text read from the host
is ASCII (hashes, sizes, names); the blocks that capture it set the console encoding to UTF-8 without a byte-order mark first.

### 8.0 Step 0: offline gates

Work from a clean checkout of the exact commit, made without line-ending conversion. Build the kit outside the repository and
compare it with section 3 (install runbook 2):

```powershell
cls
$PY = '<PY>'
$KIT = '<absolute kit directory outside the repository, new or empty>'
Set-Location <checkout>
& $PY -I -B -X utf8 tools\build_ha_integration.py --out $KIT --git-sha 0000000
(Get-FileHash -Algorithm SHA256 (Join-Path $KIT 'SHA256SUMS')).Hash.ToLower()
```

The tool prints `built custom_components/ecco_intelligence with 36 vendored modules and 20 integration files; 58 files` and the
`SHA256SUMS` sha256, and the second line prints the same number again; it must equal the fixed-reference row of section 3. The
same command without `--git-sha` (into a second new directory) must give the first row. If either differs, stop: the checkout
is not the reviewed one.

Then build the kit that will be installed, with the commit it is installed from, and record its `SHA256SUMS` sha256 offline (it
is `-ExpectedSumsSha256` of every run with it):

```powershell
cls
$PY = '<PY>'
$KIT = '<absolute kit directory for the install, outside the repository, new or empty>'
Set-Location <checkout>
& $PY -I -B -X utf8 tools\build_ha_integration.py --out $KIT --git-sha (git rev-parse HEAD)
& $PY -I -B tools\ecco_intel_drill.py runbook --kit $KIT
(Get-FileHash -Algorithm SHA256 (Join-Path $KIT 'SHA256SUMS')).Hash.ToLower()
```

`runbook --kit` verifies the kit and exits 1 when it does not verify. Drill install, upgrade, rollback and uninstall with this kit on a
marked mock root (install runbook 2; the root must contain the marker file, and the drill refuses any other directory):

```powershell
cls
$PY = '<PY>'
$KIT = '<the install kit above>'
$MOCK = '<an empty temporary directory>'
Set-Location <checkout>
New-Item -ItemType Directory -Force (Join-Path $MOCK 'ecco\intelligence') | Out-Null
Set-Content -Encoding utf8 (Join-Path $MOCK '.ecco_mock_config_root') 'mock'
& $PY -I -B tools\ecco_intel_drill.py drill --config-root $MOCK --kit $KIT
```

**What the drill proves, exactly.** On a mock root, the swap steps (install, upgrade, rollback, uninstall) leave the site file, the state
folder (with whatever scorecard file it holds, the two new tables included) and every other integration byte-identical: their hashes
are compared before and after each step. The suite of this runbook repeats that with a scorecard file that really holds both
tables. The drill does **not** run the previous kit on such a file; that was checked once, offline, on synthetic data (section 10, R3).
It never touches a real Home Assistant.

Run the offline suites of install runbook 2 on the exact commit (the runtime root and the engine root, one at a time), the
suite of this runbook, `tools/validate_repo.py` and the public privacy suite. The owner's M2 scan is the owner's tool and runs on the
exact commit (P5).

### 8.1 Step 1: the live read-only baseline

A live read; it needs the owner's authorisation in the session. Everything is written to `<OFFLINE_EVIDENCE_DIR>`, never to a
repository. The same listings are read again in steps 4, 6 and in the rollback, so the sets can be compared.

**Block 1: Core, the integration folder and the state folder.** The listings are captured as text exactly as the host prints
them, with the console encoding set first, and saved without any edit (byte-exact copies):

```powershell
cls
$H = '<production alias>'
$E = '<OFFLINE_EVIDENCE_DIR>\u2-baseline'
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
$OutputEncoding = [Console]::OutputEncoding
New-Item -ItemType Directory -Force $E | Out-Null
Set-Location <checkout>
Get-Date -Format o | Out-File -Encoding utf8 "$E\time-before.txt"
.\tools\ha-status.ps1 -SshHost $H 6>&1 | Out-File -Encoding utf8 "$E\core-info-before.txt"
ssh $H "cd /config/custom_components/ecco_intelligence && find . -type f ! -path '*/__pycache__/*' -exec sha256sum {} +" | Sort-Object | Out-File -Encoding utf8 "$E\integration-before.txt"
ssh $H "ls -lR /config/custom_components/ecco_intelligence | grep -v '^total'" | Out-File -Encoding utf8 "$E\integration-ls-before.txt"
ssh $H "cd /config/ecco/intelligence/state && ls -l | grep -v '^total'" | Out-File -Encoding utf8 "$E\state-ls-before.txt"
.\tools\ha-logs.ps1 -SshHost $H -Lines 400 -Pattern ecco_intelligence 6>&1 | Out-File -Encoding utf8 "$E\log-before.txt"
(Get-Content "$E\integration-before.txt" | Measure-Object).Count
```

The last line prints the number of files in the installed folder: it must be 52 if the installed kit is the merged base's, and the
difference otherwise is explained before going on. `ha-status.ps1` and `ha-logs.ps1` are the repository's read-only tools; the
`find`, `ls` and `sha256sum` reads are new combinations of commands the deploy tools themselves use and have not been run on the
production host (section 12). The state folder's hash is read in step 4, with the integration paused, because the file is written
once per slot cycle while the integration runs.

**Block 2: what will change (offline, on the saved listing).** Compare the baseline with the kit's `SHA256SUMS`:

```powershell
cls
$E = '<OFFLINE_EVIDENCE_DIR>\u2-baseline'
$KIT = '<the install kit>'
$prefix = 'custom_components/ecco_intelligence/'
$want = @{}
foreach ($l in Get-Content (Join-Path $KIT 'SHA256SUMS')) {
    $p = $l -split '  ', 2
    if ($p.Count -eq 2 -and $p[1].StartsWith($prefix)) { $want[$p[1].Substring($prefix.Length)] = $p[0] }
}
$have = @{}
foreach ($l in Get-Content "$E\integration-before.txt") {
    $p = $l.Trim() -split '\s+', 2
    if ($p.Count -eq 2) {
        $rel = $p[1]
        if ($rel.StartsWith('./')) { $rel = $rel.Substring(2) }
        $have[$rel] = $p[0]
    }
}
$added = @($want.Keys | Where-Object { -not $have.ContainsKey($_) } | Sort-Object)
$changed = @($want.Keys | Where-Object { $have.ContainsKey($_) -and $have[$_] -ne $want[$_] } | Sort-Object)
$removed = @($have.Keys | Where-Object { -not $want.ContainsKey($_) } | Sort-Object)
'ADDED   ({0}): {1}' -f $added.Count, ($added -join ', ')
'CHANGED ({0}): {1}' -f $changed.Count, ($changed -join ', ')
'REMOVED ({0}): {1}' -f $removed.Count, ($removed -join ', ')
```

Expected if the installed folder is the merged base's kit: 5 ADDED (the four vendored Ghost modules and `runtime/ghost_link.py`),
5 CHANGED (`coordinator.py`, `diagnostics.py`, `runtime/store.py`, the vendored `scorecard.py` and `VENDOR_MANIFEST.json`) and 0 REMOVED
(section 2.2). Anything else is a stop until it is explained.

**The owner's reads in the Home Assistant UI** (the install runbook reads them the same way; each is noted offline): Intelligence's
status entity reads a computed status with `mode` SHADOW and `applies_nothing` true and a recent update; the freshness entity and the
watchdog read fresh; the pause helper's state is noted; the integration's page shows one loaded entry and no repair; supervision
reads SUPERVISED and stable with the heartbeat age nominal; every write enable, arm and schedule is off and the manual write
counter is noted (install runbook G4). Then the owner downloads the diagnostics (Download diagnostics) and saves the file as
`diagnostics-before.json` in the evidence folder: `cycle_stats` lives in memory and the restart empties it (install runbook 8), so
this is the only record of the run before the restart.

### 8.2 Step 2: the owner's protected backup

The owner makes a full backup in the Home Assistant UI with a protected (encrypted) option, notes its name and time in
`<OFFLINE_EVIDENCE_DIR>`, and keeps the password out of every chat, file and repository. The coordinator never asks for it and
never makes a backup over SSH as a substitute (the deploy tool's own backup, `/config/ecco-backups/<stamp>/`, holds a copy of the
installed integration folder only: it is a convenience for the rollback, not a backup of the state folder).

**What restoring this backup would do (said plainly, because it is the last resort and never the first rollback).** A full backup holds
the configuration folder, so the scorecard file, `store_meta.json` and the site file as they were when it was made (recalled, not verified). Restoring it is a heavy action and the owner's
decision: as the Home Assistant interface offers it (recalled, not verified on this host) it restarts Home Assistant and returns
everything the backup holds to its state at that time, so whatever changed or was recorded since (settings, helper and control
states, the history the recorder kept, the scorecard rows the integration recorded, anything an add-on or the owner changed meanwhile)
goes back with it. The rollback of section 10 undoes only this update, with one restart.

### 8.3 Step 3: pause

The owner turns the pause helper on (the install runbook's pause, section 10 there: "never a restart"). The status reads PAUSED,
nothing is computed, and a cycle already running is discarded when it ends. Wait until the longest cycle's time budget has passed
(about two minutes) before step 4.

### 8.4 Step 4: the paused read

```powershell
cls
$H = '<production alias>'
$E = '<OFFLINE_EVIDENCE_DIR>\u2-baseline'
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
$OutputEncoding = [Console]::OutputEncoding
ssh $H "cd /config/ecco/intelligence/state && ls -l | grep -v '^total' && sha256sum *" | Out-File -Encoding utf8 "$E\state-paused-1.txt"
Start-Sleep -Seconds 60
ssh $H "cd /config/ecco/intelligence/state && ls -l | grep -v '^total' && sha256sum *" | Out-File -Encoding utf8 "$E\state-paused-2.txt"
ssh $H "cd /config/custom_components/ecco_intelligence && find . -type f ! -path '*/__pycache__/*' -exec sha256sum {} +" | Sort-Object | Out-File -Encoding utf8 "$E\integration-paused.txt"
'--- state folder, two reads a minute apart (no output means stable):'
Compare-Object (Get-Content "$E\state-paused-1.txt") (Get-Content "$E\state-paused-2.txt")
'--- integration folder against the baseline (no output means equal):'
Compare-Object (Get-Content "$E\integration-before.txt") (Get-Content "$E\integration-paused.txt")
```

`state-paused-1.txt` holds the scorecard file's hash and size: the reference for step 6 (the file itself is in the owner's protected
backup). A write in flight when the pause began would show as a difference between the two state reads: stop and read again.

### 8.5 Step 5: stage and swap with the repository's own tool

`Plan` is read-only. Before any ssh call it requires a clean working tree and runs the repository validation with the given
`-Python`, then verifies the kit locally (its `SHA256SUMS` against `-ExpectedSumsSha256`, `git_sha` equal to this checkout's HEAD, a
byte-identical rebuild, equivalence to the reference kit). It then reads the host and prints the target, the resolved `/config` root,
the dashboard preservation gate and its pin (unchanged from the install), the Core version check, the installed tree, the free space,
the site file's hash prefix, the state folder, the config-entry count, every destination, the swap, the restart line and the rollback
command. Read it fully, then give the go for the Upgrade:

```powershell
cls
$H = '<production alias>'
$PY = '<PY>'
$KIT = '<the install kit>'
Set-Location <checkout>
.\tools\deploy-ha-kit.ps1 -Action Plan -SshHost $H -Target Production -ExpectedHaVersion <version> `
    -Kit $KIT -ExpectedSumsSha256 <sha256> -ReferenceKit <the L3-tested kit> -ReferenceSumsSha256 <its sha256> -Python $PY
```

```powershell
cls
$H = '<production alias>'
$PY = '<PY>'
$KIT = '<the install kit>'
Set-Location <checkout>
.\tools\deploy-ha-kit.ps1 -Action Upgrade -SshHost $H -Target Production -ExpectedHaVersion <version> `
    -Kit $KIT -ExpectedSumsSha256 <sha256> -ReferenceKit <the L3-tested kit> -ReferenceSumsSha256 <its sha256> -Python $PY
```

The Upgrade stages under `/config/ecco/staging/<stamp>/` (never inside `custom_components/`), verifies the staged copy on the
host, backs up the installed folder to `/config/ecco-backups/<stamp>/` and verifies the backup against its `BACKUP_SHA256SUMS`,
swaps by atomic rename (the replaced tree moves under the staging folder; nothing is deleted), verifies every file in place, and
runs `ha core check`. A failure from the swap on goes through the tool's one rollback routine ("was rolled back" only when verified).
**Record the stamp it prints in the backup line: it is the `-BackupStamp` of the rollback.** The tool never restarts Home
Assistant and tells you to keep the pause helper on until after the restart (lazy imports could otherwise load new modules into the
old process).

### 8.6 Step 6: the installed folder equals the kit

```powershell
cls
$H = '<production alias>'
$E = '<OFFLINE_EVIDENCE_DIR>\u2-baseline'
$KIT = '<the install kit>'
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
$OutputEncoding = [Console]::OutputEncoding
ssh $H "cd /config/custom_components/ecco_intelligence && find . -type f ! -path '*/__pycache__/*' -exec sha256sum {} +" | Sort-Object | Out-File -Encoding utf8 "$E\integration-after-swap.txt"
ssh $H "cd /config/ecco/intelligence/state && ls -l | grep -v '^total' && sha256sum *" | Out-File -Encoding utf8 "$E\state-after-swap.txt"
$prefix = 'custom_components/ecco_intelligence/'
$want = @{}
foreach ($l in Get-Content (Join-Path $KIT 'SHA256SUMS')) {
    $p = $l -split '  ', 2
    if ($p.Count -eq 2 -and $p[1].StartsWith($prefix)) { $want[$p[1].Substring($prefix.Length)] = $p[0] }
}
$got = @{}
foreach ($l in Get-Content "$E\integration-after-swap.txt") {
    $p = $l.Trim() -split '\s+', 2
    if ($p.Count -eq 2) {
        $rel = $p[1]
        if ($rel.StartsWith('./')) { $rel = $rel.Substring(2) }
        $got[$rel] = $p[0]
    }
}
$bad = @($want.Keys | Where-Object { $got[$_] -ne $want[$_] }) + @($got.Keys | Where-Object { -not $want.ContainsKey($_) })
if ($bad.Count -eq 0) { 'INSTALLED TREE EQUALS THE KIT ({0} files)' -f $want.Count } else { 'DIFFERENT: ' + ($bad -join ', ') }
'--- state folder against the paused read (no output means untouched):'
Compare-Object (Get-Content "$E\state-paused-1.txt") (Get-Content "$E\state-after-swap.txt")
```

Expected: `INSTALLED TREE EQUALS THE KIT (57 files)` and no line for the state folder: nothing wrote while the integration was paused and
the tool never touches it. The site file is covered by the tool's own before-and-after check of its hash (the Plan prints its prefix).

### 8.7 Step 7: the restart

Custom integrations load at start-up, so Home Assistant restarts **once, only with the owner's explicit approval, separate from the
Upgrade**, while the owner watches. The restart is the owner's action in the Home Assistant UI; no tool in this runbook performs it.
Immediately before: Core is running, the pause helper is on, the owner is present, no other live change is in progress, the
protected backup exists. Keep the restart short: an outage of more than about 5 minutes sets the supervision latch, and recovery is
then a supervised dongle reboot by the owner (install runbook 6). Immediately after: Core running again; the integration page shows
the entry loaded and no repair; the log shows no error line from the integration (step 8 reads it).

### 8.8 Step 8: the load checks, still paused

A live read, with the owner's own go. The owner downloads the diagnostics as `diagnostics-restart.json`. Read the load checks
(install runbook 7, step 2) and the new blocks with one offline read of the file:

```powershell
cls
$PY = '<PY>'
$E = '<OFFLINE_EVIDENCE_DIR>\u2-baseline'
$F = "$E\diagnostics-restart.json"
& $PY -I -B -X utf8 -c "import json, sys; d = json.load(open(sys.argv[1], encoding='utf-8-sig')); d = d.get('data', d); c = d.get('counters', {}); a = d.get('advice_incidents') or {}; s = a.get('stored') or {}; print('status', d.get('status')); print('self_test FAIL', [k for k, v in (d.get('self_test') or {}).items() if str(v).startswith('FAIL')]); print('STORE_RECORD', (d.get('self_test') or {}).get('STORE_RECORD')); print('advice counters', c.get('advice_write_failures'), c.get('advice_unverified_writes'), c.get('advice_current_failure')); print('advice_incidents present', bool(a), 'verified_writes', a.get('verified_writes'), 'open', a.get('open') is not None, 'closed', len(a.get('closed') or []), 'stored', s.get('status'), len(s.get('incidents') or [])); print('last_store advice', {k: v for k, v in (d.get('last_store') or {}).items() if k.startswith('advice')}); print('budget_exceeded', c.get('budget_exceeded'), 'exceptions', c.get('exceptions'))" $F
.\tools\ha-logs.ps1 -SshHost '<production alias>' -Lines 400 -Pattern ecco_intelligence 6>&1 | Out-File -Encoding utf8 "$E\log-restart.txt"
```

Expected while paused: status PAUSED; `self_test FAIL []` (the VENDOR_MANIFEST check passes on the new kit, STORE_WRITABLE passes);
no STORE_RECORD yet; `advice_incidents present True` with `verified_writes 0`, nothing open and nothing closed, and `stored OK 0`
(the table does not exist, so no stored incident); the advice counters `0 0 0`; `budget_exceeded` and `exceptions` 0. The block is the
proof that the new code is the code that runs (the old code has no `advice_incidents` block). The owner also confirms the entities:
exactly eleven, no `_2` suffix, the watchdog fresh and no `ecco_intel` notification (install runbook 7). The keys the read
uses are those of the coordinator's diagnostics; the file's outer `data` wrapper is recalled, not verified (`d.get('data', d)` reads
either form). Keep the file in the evidence folder.

### 8.9 Step 9: un-pause

The owner turns the pause helper off. The status changes to STARTING; the first cycle runs after the start-up grace, at the first
poll-driven step or the next minute's tick (install runbook 7, step 3); the first slot cycle comes at the next full hour or 21:30
(local time).

### 8.10 Step 10: the after-checks within the first slot cycles

Wait for at least the next two slot times (allow about two and a half hours), then the owner downloads the diagnostics as
`diagnostics-after-1.json` (and again as `-2` after the second slot cycle), and the coordinator reads each with the block of 8.8 (change
`$F`), and the log again with `-Pattern ecco_intelligence` into `log-after.txt`. Expected, and each a check:

1. **Status SHADOW with a fresh computed result.** `status` is a computed one (an item without its decisions or fresh inputs is BLOCKED, as
   before), `mode` SHADOW, `applies_nothing` true; no `SELF_TEST_FAILED`; `budget_exceeded` and `exceptions` 0.
2. **STORE_RECORD as designed.** Absent before the first slot cycle; after it, PASS with "the advice log write is verified" (INFO only if
   that slot cycle had nothing to write); never WARN unless an incident is open, which is the designed honest failure (section 11).
3. **The advice rows grow by two per slot cycle.** In the download, `last_store` shows `advice_rows` 2 and `advice_verified` true for the
   latest slot cycle, and `advice_incidents.verified_writes` has grown by one per slot cycle since the un-pause (one verified write of
   two rows each). The table itself is not read in these steps.
4. **No incident, no failure.** `advice_current_failure` 0, `advice_write_failures` 0, `advice_unverified_writes` 0, nothing open or closed in
   `advice_incidents`, `stored` OK with no rows.
5. **No new entity.** Exactly eleven entities with the contract ids, no suffix, the same attribute names as in the baseline.
6. **No change of any published value against the baseline.** The structure is the baseline's (the same entities, attributes, SHADOW,
   applies nothing); each item's status and reason codes are read against the baseline's for the same inputs, and a difference is
   explained by the inputs (time, tariff, readings), never by this update. Offline, the L2 suites pin the published entities
   byte-identical to a reference run of the same inputs; live, this is a reading, not a proof.
7. **No error or budget line.** The log shows no warning or error from the integration (in particular none about the advice log and no
   blocking-I/O warning); `cadence.refresh_suspended_cpu` false; `cycle_stats` slot rows within the install runbook's R3 bounds, with
   `store_s` read beside `total_s` (the update adds the write to the slot cycle).
8. **The write statement holds.** Supervision stays SUPERVISED and stable with the heartbeat age nominal, every write enable, arm and
   schedule is as in the baseline, the manual write counter is unchanged, and the pause helper is off: nothing in this update
   writes to a Home Assistant entity, helper, schedule, the inverter or the dongle (section 2.4).
9. **The Ghost block** says `NO_ADVICE_LOGGED` or `INSUFFICIENT_HISTORY` for now (section 2.3), or a computed block with the banner that it is a
   simulation; either way it changes nothing and is not a check of accuracy.

The deliberate-failure drill (a failing or unverifiable write, to see the WARN and the log lines) is **offline only**: it is run by
the suites on a stand-in and on the isolated test instance (P1), never on production, and nothing in this runbook makes the
production database fail.

### 8.11 Step 11: close-out

The evidence is filed in `<OFFLINE_EVIDENCE_DIR>`, the status update is written, and a post to the coordination channel or a push
happens only on the owner's go. The deploy backup and staging folders are kept; the owner cleans them up.

## 9. Stop conditions (any step)

Stop, change nothing more, record the state, and ask the owner, when: a tool prints anything but the expected line; a hash differs
from its pin; the baseline shows Core not running, Intelligence not SHADOW or not fresh, or supervision not stable; the installed
folder is not what 2.2 expects and is not explained; the state folder changes while the integration is paused; the Upgrade prints
NO CHANGE, a hash mismatch, ROLLBACK NOT CONFIRMED or a failed `ha core check`; the restart outage exceeds about 5 minutes; after the
restart the integration does not load, a self-test check FAILs, a repair or error line appears, the old code is still running, a
new entity or a `_2` suffix appears; after the un-pause `SELF_TEST_FAILED`, `budget_exceeded` or `exceptions` above 0, a blocking-I/O
warning from the integration, or a write enable, arm, schedule or counter that differs from the baseline; a step would need a second
restart. Never retry a live write without the owner. Never approve, work around or weaken a permission prompt or a safety gate.
Any no-go after the swap means the pause stays on and the rollback of section 10 follows (install runbook 7, 10 and 11).

## 10. Rollback, in order

Each item is the owner's decision to start and needs its own go. The rollback is measured against two things made before any live
write: **(i) the baseline** of step 1 (the integration folder listing and its hashes, the state folder listing, Core's version, the log
lines, the owner's UI reads, the diagnostics download), and **(ii) the owner's protected full backup** of step 2, the last resort.

1. **RB1, pause.** The owner turns the pause helper on if it is not on (install runbook 11: pause, then roll back). Proof: the status reads
   PAUSED; the state listing is stable across two reads.
2. **RB2, restore the previous kit.** The coordinator runs the repository's own rollback with the stamp recorded in step 5:

   ```powershell
   cls
   $H = '<production alias>'
   $PY = '<PY>'
   Set-Location <checkout>
   .\tools\deploy-ha-kit.ps1 -Action Rollback -BackupStamp <stamp> -SshHost $H -Target Production -ExpectedHaVersion <version> -Python $PY
   ```

   It verifies the backup against its `BACKUP_SHA256SUMS`, stages and verifies the restore copy, backs up the current tree, swaps,
   verifies in place and runs `ha core check`; it never restarts. Proof: the PASSED block (`Restored` and `HA check : passed`), and an
   independent comparison of the installed folder with the baseline (RB2 below):

   ```powershell
   cls
   $H = '<production alias>'
   $E = '<OFFLINE_EVIDENCE_DIR>\u2-baseline'
   $ErrorActionPreference = 'Stop'
   [Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
   $OutputEncoding = [Console]::OutputEncoding
   ssh $H "cd /config/custom_components/ecco_intelligence && find . -type f ! -path '*/__pycache__/*' -exec sha256sum {} +" | Sort-Object | Out-File -Encoding utf8 "$E\integration-rollback.txt"
   '--- integration folder against the baseline (no output means byte-identical hashes):'
   Compare-Object (Get-Content "$E\integration-before.txt") (Get-Content "$E\integration-rollback.txt")
   ```

3. **RB3, restart.** The restart is the owner's, approved separately, short (the latch caveat). Proof: Core running; the integration loads
   with no repair or error line; the diagnostics download has **no** `advice_incidents` block (the previous code runs) and no FAIL in
   `self_test`; the entities are the same eleven. **What happens to the two tables.** They stay in the scorecard file, unused, and are
   harmless to the previous kit. What was proved, exactly: the drill leaves the state folder byte-identical through every swap
   (a suite check, with a scorecard file that holds both tables); and one offline experiment of this preparation (scratch only,
   synthetic data, not a repository suite) had the previous scorecard and store code open a file holding both tables, pass the
   start-up writable gate, record and score further slots and report its counts, with `PRAGMA integrity_check` ok and both tables
   unchanged. It has not been run live, and no suite runs the previous code. A live check after R3: STORE_WRITABLE passes, the first slot
   cycle records, and no new incident of the previous kit appears.
4. **RB4, un-pause and re-read.** After the checks of RB3 the owner turns the pause helper off; the status computes again; the baseline's UI
   reads (the install runbook's R1 and R4: supervision, write enables, the counter) are as before. Proof: the status is a
   computed SHADOW one, and the listing comparison of R2 is still empty.
5. **RB5, optionally drop the two tables, on a copy only.** No tool in this repository drops them on the host and this runbook invents
   none: the tables may stay (a few MB at most). To see the documented statement work, use a copy of the scorecard file (the owner's file taken out of the protected backup by the owner,
   or a copy read with the integration paused under its own go; never the live file) in a scratch folder and, with the Python 3.12
   interpreter, run the documented statement on the copy: `DROP TABLE IF EXISTS advice_log; DROP TABLE IF EXISTS advice_incident;` (the runtime document: "drop the tables
   `advice_log` and `advice_incident`, or delete `scorecard.sqlite3`, while the integration is stopped"). Proof: `PRAGMA integrity_check`
   on the copy reads `ok` and the scorecard's own tables keep their row counts. Doing it on the host would need the integration stopped
   (its entry disabled), a way to run the statement there and its own authorisation; none is prepared here.
6. **RB6, the protected backup restore, the heavy last resort.** The owner's decision, never the first rollback: read 8.2 first. It
   restarts Home Assistant and returns everything the backup holds, the scorecard file included, to its state at backup time. Proof:
   after it the owner's UI reads of 8.1 are repeated and the integration folder listing is read again and compared with the baseline
   as in RB2; what the backup does not hold (anything done since) is gone, and the owner has weighed that first.

**Special cases.** *S1, the Upgrade stops before the swap* ("nothing installed changed"): nothing to roll back; record the message,
un-pause. *S2, the tool rolled itself back after the swap* ("was rolled back", verified): compare the installed folder with the baseline
as in R2; no restart is needed because no restart has happened; un-pause. *S3, ROLLBACK NOT CONFIRMED*: stop; touch nothing; the staging
and backup folders are kept; the owner decides (R2 with the stamp, or R6). *S4, the restart outage exceeds about 5 minutes*: the
supervision latch may be set; recovery is a supervised dongle reboot by the owner (install runbook 6), then R1 to R4 if the owner chooses.
*S5, the pause helper was left on or turned off by mistake*: record the time and the state, put it back, and re-read the status.

## 11. What a first-look failure looks like, and what it means

| What the owner sees | What it means | What to do |
|---|---|---|
| the integration does not load after the restart, a repair issue, or `SELF_TEST_FAILED` | the new kit failed a start-up gate | stop; pause stays on; section 10 |
| the self-test's VENDOR_MANIFEST check FAILs | the installed files are not the kit's | stop; compare with 8.6; section 10 |
| no `advice_incidents` block in the download | the old code is still running (no restart yet, or the swap is not in place) | check step 5 and 6, then the restart |
| STORE_RECORD WARN "advice log not verified (`<class name>`)" | an advice write failed or could not be read back: the designed honest display; no published value is affected | record the class name and the counts; read `advice_incidents`; whether to roll back is the owner's decision |
| STORE_RECORD WARN "the scorecard step exceeded the time budget" or "failed" | the slot cycle's store step timed out or raised (the real database's write latency is unknown); an incident is open | record `store_s` of the slot rows and the class name; owner's decision |
| STORE_RECORD stays INFO after several slot cycles | nothing was written: no advice to log, or no slot cycle has computed | read the status and the reason codes; not a defect by itself |
| `advice_incidents.stored` says ERROR or UNAVAILABLE | the read-only read of the incident table failed or timed out (a class name or `TIME_BUDGET`) | record it; diagnostics only; the integration is unaffected |
| `ghost` says `NO_ADVICE_LOGGED` or `INSUFFICIENT_HISTORY` | not enough logged advice or history yet | wait a day; expected |
| `ghost` says `UNAVAILABLE` with `BUSY` or `TIME_BUDGET`, or `ERROR` | a download asked while a Ghost job ran, or it outlived its 30 s budget, or it failed (a constant reason, never a message) | download again; record the reason; diagnostics only |
| a blocking-I/O or slow-callback warning from the integration | an executor read or a write ran on the event loop, or too long | stop; record the text; section 10 |
| a twelfth entity, or a `_2` suffix | an entity-id collision (not this update's code: it adds no entity) | the install runbook's recovery (7); never delete and re-add the entry |
| `exceptions` or `budget_exceeded` above 0 | a cycle failed or overran | stop; section 9 |
| the latch is set after the restart | the outage exceeded about 5 minutes | a supervised dongle reboot by the owner (install runbook 6) |

## 12. What is NOT established

Say these plainly in every report about this update.

- **The update has never run in a real Home Assistant.** The code has run offline, on a stand-in Home Assistant (L2) with real SQLite, on
  synthetic data. Nothing here has been observed on the production host.
- **The L3 (WSL) kit-equivalence reference run has not been repeated on the exact kit (P1, OPEN).** Until it has, the executor reads in the
  download and the log lines are unobserved in a real Home Assistant, and `-ReferenceKit` has no kit to name.
- **The real database's write latency and disk behaviour are unknown.** The advice write and its read-back run inside the slot cycle's
  store step; how long they take on the production host's storage, and how the file behaves when the disk is full or slow, has not been
  measured. The first creation of the table on the real file has never happened.
- **A same-connection read-back is not a durability proof.** A verified write means the rows were visible to the connection that wrote
  them and matched; it says nothing about what a power loss would keep. The incident write is a plain commit and is not read back.
- **An incident that is open at a restart is lost,** and so is one that stays open because the database never takes the write again: it
  then lives only in the one warning logged when it opened (the class name) and, until the restart, in memory and the download.
  An incident written to the table can be pruned: the table keeps the newest 10 by the text of the first failure time, so after the clock
  has been stepped backwards a new, older incident is reported persisted and pruned at once (a known limit, diagnostics only).
- **The log lines** (the warning when an incident opens, the line when it closes) have never been seen in a real Home Assistant.
- **The diagnostics download's executor reads** (the stored-incident read and the Ghost block) have never run in a real Home Assistant:
  a blocking-I/O warning is not excluded until P1.
- **Rows per day on the real engine are unmeasured.** At most 52 a day is a bound, not a measurement; BLOCKED rows are logged too. The
  figure of about 21 000 rows (a few MB) at the age bound is an estimate.
- **The rollback with the tables present has never been run live.** The drill proves the swap leaves the state folder byte-identical;
  one offline experiment on synthetic data had the previous code open such a file. Nothing proves the first live Rollback, and no suite
  runs the previous code.
- **The baseline's listing commands** (`find`, `ls -lR`, `sha256sum` over the state folder) have not been run on the production host, and
  the diagnostics file's outer wrapper key is recalled, not verified. The repository's own tools (`ha-status.ps1`, `ha-logs.ps1`,
  `deploy-ha-kit.ps1`) are the read-only and write routes; the Upgrade and Rollback actions have run offline in the drill, and this
  runbook does not claim they have run on the production host.
- **The Ghost block is a simulation.** Intelligence controlled nothing; its numbers are site-derived behaviour and money figures, are
  evidence and not proof, and say nothing about forecast accuracy. Intelligence stays in SHADOW and its overall acceptance is not changed
  by this update.
- **The two owner questions stay open** (D-U2-7, D-U2-8) and so do the other items of section 4: this runbook decides none.
- Several Home Assistant screen names and the behaviour of a protected-backup restore are recalled, not verified on this host.
