# Production Mode / Geek Mode: the first supervised Home Assistant update (U1) runbook

**Status: PREPARED OFFLINE, NOT RUN.** Nothing in this document has been done on Home Assistant. The card has never run in a
real Home Assistant or a real browser (section 9). Every live step below needs its own owner authorisation, in the session, at the
time (column "own authorisation" of the step table).

> **Every live step in this runbook is NOT AVAILABLE** until all of these hold:
>
> 1. The offline gates of step 0 are green on the exact commit that will be installed, and the owner has chosen that commit
>    (decision D-U1-1, section 12).
> 2. The owner has reserved a quiet period, is present for steps 2 to 7, and has made a fresh **protected** full backup (step 2).
> 3. The owner has given the go for each live step, one by one. A go for one step is not a go for the next.
>
> No firmware is flashed, no inverter register is written, no Home Assistant restart is made, no entity is created, no package,
> helper, automation or existing dashboard is edited, and Intelligence stays SHADOW (advice only). ASSISTED and AUTONOMOUS are not
> touched.

**What U1 is.** The first low-risk, read-only user-interface update after the Intelligence acceptance run: one new, admin-only
dashboard that shows the ECCO Intelligence view through the Production / Geek Mode shell card. Production Mode is the existing
Intelligence card and the existing watchdog and status card, unchanged, plus the existing pause tile, plus a catalogue-driven
alert strip. Geek Mode shows every available non-secret data point of the view (17 sources, 344 attribute rows, 19 alerts in the
catalogue), grouped, searchable, with update ages and withheld markers. Switching the mode is a presentation choice only.

**What U1 is not.** Ghost diagnostics is U2 and has its own track (it needs a Home Assistant restart, a new durable log write, a
new reference-kit run and an independent review). R9 and Stage 3 are separately gated by their own known limitations. The overall
Intelligence acceptance stays **NOT ACCEPTED** until its outstanding criteria are resolved; this update does not change that, and a
good first look says nothing about forecast accuracy.

**Notation.** Placeholders are written `<like this>`. `<production alias>` is the owner's SSH alias for the production host (the
deploy tools default to `ecco-ha`). `<HA URL>` is the owner's address of Home Assistant. `<OFFLINE_EVIDENCE_DIR>` is the owner's
local evidence folder; it is never in a repository, and nothing that holds a site value (an address, a read-back, a screenshot with
values) is ever copied into a repository. `<checkout>` is a clean checkout of the chosen commit (step 0). `<PY>` is a Python 3.12
interpreter with PyYAML installed in that interpreter itself. Every PowerShell block starts with `cls`. This runbook quotes no
secret, host, address, token, entity id or site value: it names roles.

## 1. What is installed, and what is not touched

| # | Artefact | Where | How it gets there | Reversible by |
|---|---|---|---|---|
| A1 | the card file, content-addressed: `ecco-mode-shell.<sha8>.js` (the LF file, one ES module, no import, no secret) | `/config/www/ecco/` on the host, served unauthenticated as `/local/ecco/ecco-mode-shell.<sha8>.js` like every card bundle | `tools/deploy-ha.ps1` (backup, sha256 of the upload and of the installed file, `ha core check`, no restart) | the file stays inert when no resource points at it; moved by hand (section 7) |
| A2 | one Lovelace resource of type `module` for A1 | Home Assistant's resource list (`.storage`) | **the owner, by hand** (Settings, Dashboards, Resources): no ECCO tool edits resources | the owner deletes that one item |
| A3 | one new admin-only storage-mode dashboard whose raw configuration is the generated text (the catalogue INLINE in the shell card's configuration) | Home Assistant's dashboard list and its own `.storage` file | **the owner, in the UI**: Add dashboard, "Require admin", paste into the raw configuration editor | the owner deletes the dashboard |

**Not touched, by design:** the production Overview and every other dashboard file, every existing resource (the Overview is guarded
by the site's dashboard preservation gate; this update never writes a dashboard file, so the gate does not apply and is not
bypassed), every package, helper, automation, script and entity, the Intelligence integration and its site file, the card of the
Intelligence integration, firmware, the dongle, the inverter and InfluxDB. The shell creates **no entity**. The existing pause
tile is shown in Production unchanged and keeps the toggle it has today (a write to the pause helper, exactly as on the existing
Intelligence dashboard); Geek Mode hides it. Nothing in this update taps it (step 7).

**Why a new storage dashboard (decision H1).** It touches no pinned file (the existing Intelligence dashboard file is pinned by
several suites and the production Overview is protected), uses no `!include` of a JSON file (never proven on a real Home Assistant),
confines any failure to one new dashboard, needs no restart (a storage dashboard is registered live; a new `lovelace: dashboards:`
entry in YAML would need one), and the rollback is two deletions. The catalogue is inside the dashboard configuration, so it is
never placed under `/config/www`, which is served without authentication (it names entity ids and texts). The alternative (a
second view in the existing Intelligence YAML dashboard with an `!include` of the catalogue) is **not prepared**: it needs
owner-approved edits of two protected assertions and an `!include` read that has never run on the real host.

## 2. The artefacts and their hashes

The pins are held in `tools/tests/test_ecco_mode_shell_card.py`; any change to the card, the catalogue, the example or the
generated configuration is a deliberate edit of that file. Full values are in section 13 for the exact tip.

| Artefact | Source | Pinned by |
|---|---|---|
| the card | `frontend/ecco-mode-shell/ecco-mode-shell.js` (155,843 bytes, ASCII, LF) | size and sha256; the forbidden-API list; the exact surface |
| the catalogue | `frontend/ecco-mode-shell/catalogue/intelligence.catalogue.json` (93,873 bytes; 17 sources, 344 attribute rows, 19 alerts) | size and sha256; counts; a privacy scan |
| the generated dashboard configuration | `tools/geek_mode_dashboard_config.py` (the example's cards with the catalogue inline; JSON, ASCII, LF; 147,178 bytes) | size and sha256; equality with the committed catalogue |
| the resource plan | `tools/geek_mode_dashboard_config.py --resource-plan` | read by the real `verify-resource` in its suite |

## 3. Go / no-go before any live step

Go only when **every** line holds. Otherwise stop: this is a no-go.

| # | Criterion |
|---|---|
| G1 | step 0 is green on the exact commit (section 13), and the owner has chosen the commit to install from (D-U1-1) |
| G2 | the owner has reserved a quiet period, is present, and no other supervised live step is in progress |
| G3 | the owner has made a fresh **protected** full backup in the Home Assistant UI (step 2). A backup made over SSH is full but UNPROTECTED: no session handles a backup encryption password |
| G4 | the live baseline (step 1) is saved and shows: Home Assistant Core running and its version noted; the Intelligence status reading SHADOW with a fresh result (or its state noted if not); the pause helper's state noted; no resource, file or dashboard of this update already present; the Intelligence card's resource registered; the control entities of the earlier supervised installs unchanged since their last record |
| G5 | RG-F3 is recorded: "expose new entities" is ON for Assist and Google Assistant (finding of 17 Nov). This update creates **no entity**, so it is not a blocker for U1, but the owner states in the session whether both are now off or waived for U1. Any later install that creates entities waits for both to be off |
| G6 | the browser used for the look is a desktop browser whose clock is within five minutes of Home Assistant's clock (section 10) |
| G7 | the owner agrees in advance that the first look is **Production Mode only**, that Geek Mode follows only after the owner says go, and that the pause tile is never tapped |

## 4. The steps

| Step | What | Who | Offline / live | Read-only / write | Own owner authorisation | Expected result | Stop condition |
|---|---|---|---|---|---|---|---|
| 0 | offline gates on the exact commit: the verification table (section 13), the owner's M2 private-pattern scan, the push, draft pull request and CI, the choice D-U1-1 | COORDINATOR (the M2 scan is the owner's tool, run only on the owner's go) | offline (the push and CI touch GitHub only) | read-only on the live system; a push is a GitHub write | **yes**, each of: the M2 scan, the push, the pull request, the choice of commit | the table is green or its failures are named as known; CI green on the pushed tip if the owner chose to push | any new failure; a card or catalogue hash that is not the pinned one |
| 1 | live read-only baseline (5.1) | COORDINATOR | live | read-only | **yes** (a live read) | the baseline files saved offline; G4 holds | anything of A1 to A3 already present; the Intelligence card's resource missing; Core not running |
| 2 | the owner's protected full backup in the UI; RG-F3 decision recorded; quiet window confirmed | OWNER | live (UI) | the owner's own backup action | the owner's own action | a protected backup exists (its name and time recorded offline, never its password) | no protected backup |
| 3 | copy the card with `deploy-ha.ps1` to the content-addressed destination, then `verify-served` (5.3) | COORDINATOR | live | **write** (one new file under `/config/www/ecco/`, its backup folder) | **yes** | `ECCO DEPLOYMENT PASSED`, `Restart : no`, a `RESOURCE NOT REGISTERED` reminder; `verify-served` PASS | any failure line; a hash mismatch; the tool's own rollback message; anything but the one new file |
| 4 | the owner adds ONE module resource by hand; the coordinator reads the persisted list and runs `verify-resource` (5.4) | OWNER (the add), COORDINATOR (the read-back) | live | the add is a Home Assistant write by the owner; the read-back is read-only | the owner's action; **yes** for the read-back | `RESOURCE VERIFIED ecco-mode-shell -> ...` and exit 0; the list differs from the baseline by exactly one added item | any other line; any other resource changed |
| 5 | the owner creates the admin-only storage dashboard and pastes the generated configuration (5.5) | OWNER | live (UI) | a Home Assistant write by the owner | the owner's action | the dashboard exists, "Require admin" is on, the paste saved | the raw editor is not offered; Home Assistant refuses the text |
| 6 | read-only after-checks (5.6) | COORDINATOR | live | read-only | **yes** (a live read) | the Overview file and every other dashboard file have their baseline sha256; the resource list differs by exactly one item; the dashboard list by exactly one item; the stored configuration equals the generated one; no new lovelace or frontend error in the log; Intelligence status and pause helper unchanged | any other difference |
| 7 | ONE owner look: Production first, then Geek only after the owner says go (5.7) | OWNER | live (browser) | read-only (a presentation toggle). **Never tap the pause tile** | the owner's action; the Geek look needs the owner's separate go | the checks of 5.7 | any of the stop lines of 5.7 or section 10 |
| 8 | no-write evidence (5.8) | COORDINATOR | live | read-only | **yes** (a live read) | no control entity changed since the start of the look; Intelligence still publishing | any control entity changed |
| 9 | close-out (5.9) | COORDINATOR | offline | local files and local commits; a bridge post and a push only on the owner's go | **yes** for the bridge post and any push | the evidence is filed | n/a |

No step restarts Home Assistant. A step that would need a restart is out of scope and stops the update.

## 5. The steps in detail

### 5.0 Step 0: offline gates

Work from a clean checkout of the exact commit, made without line-ending conversion (a CRLF checkout changes the card's bytes and
therefore its content address; the master status records that the main clone is a CRLF checkout on a Windows host):

```powershell
cls
git -c core.autocrlf=false -C <public clone> worktree add --detach <checkout> <commit>
Set-Location <checkout>
(Get-FileHash -Algorithm SHA256 frontend\ecco-mode-shell\ecco-mode-shell.js).Hash.ToLower()
```

The printed hash must equal the card's sha256 of section 13, character for character. If it does not, stop: the checkout is not the
reviewed one (or it is CRLF).

Run the offline suites exactly as section 13 lists them (the Python roots with `<PY> -I -B -X utf8`; the Node suites, the
mutation run and the headless strip check only through the memory guard, one process at a time, the mutation run last and alone).
The M2 private-pattern scan is the owner's tool with the owner's pattern file; it runs only when the owner says go, and what is
reported back is counts only.

Make the generated files, outside any tracked folder (`dist\` is git-ignored):

```powershell
cls
New-Item -ItemType Directory -Force dist\geek-u1 | Out-Null
& <PY> -I -B -X utf8 tools\geek_mode_dashboard_config.py --out dist\geek-u1\dashboard-config.json --resource-plan dist\geek-u1\plan.json
& <PY> -I -B -X utf8 tools\geek_mode_dashboard_config.py --check dist\geek-u1\dashboard-config.json
```

The first command prints the size and sha256 of the configuration and the resource URL with the card's sha256. The second prints
`OK: <bytes> bytes, sha256 <64 hex>` and exits 0 only when the file equals a fresh generation byte for byte and the checks pass
(section 13 lists the size and sha256 for the exact tip). Both need no network and write nothing else. `plan.json` is a small
hand-made plan for the existing resource gate (its one card: tag `ecco-mode-shell`, the content-addressed file name, the URL, type
`module` and the card's sha256); `tools/ecco_deploy_preflight.py` lists its cards in a constant that does not name the shell, so the
plan is made here and **that safety tool is not edited**.

**D-U1-1, the commit to install from.** Because the card file is content-addressed, what is installed is identified by its
sha256, not by a commit. (a) Install from the branch commit after the draft pull request's CI is green, and merge afterwards: the
merged file must have the same sha256 (re-check at the merge; a different one is a new content address, so a new U-step). (b) Merge
first, then install from the merge commit: the installed bytes then always equal the repository's main. The owner decides; neither
is assumed. If the card file changes in review, nothing already installed is overwritten (a new name; the resource is repointed;
section 7 covers the repoint and its rollback).

### 5.1 Step 1: the live read-only baseline

A live read; it needs the owner's authorisation in the session. Everything below is read-only and written to `<OFFLINE_EVIDENCE_DIR>`,
never to a repository. The same commands are run again, unchanged, in step 6, so the two sets can be compared.

```powershell
cls
$H = '<production alias>'
$E = '<OFFLINE_EVIDENCE_DIR>\u1-baseline'
New-Item -ItemType Directory -Force $E | Out-Null
Get-Date -Format o | Out-File -Encoding utf8 "$E\time-before.txt"
ssh $H "cat /config/.storage/lovelace_resources" | Out-File -Encoding utf8 "$E\resources-before.json"
ssh $H "cat /config/.storage/lovelace_dashboards" | Out-File -Encoding utf8 "$E\dashboards-before.json"
ssh $H "cd /config && sha256sum .storage/lovelace* ecco/dashboards/*.yaml" | Out-File -Encoding utf8 "$E\sha-before.txt"
ssh $H "ls -l /config/www/ecco/" | Out-File -Encoding utf8 "$E\www-ecco-before.txt"
ssh $H "ha core info" | Out-File -Encoding utf8 "$E\core-info-before.txt"
(Select-String -Path "$E\resources-before.json" -SimpleMatch 'ecco-intelligence-card').Count
(Select-String -Path "$E\resources-before.json" -SimpleMatch 'ecco-mode-shell').Count
(Select-String -Path "$E\www-ecco-before.txt" -SimpleMatch 'ecco-mode-shell').Count
```

These are the same read-only forms the repository's own documentation uses (`cat` of the persisted resource list,
`sha256sum`, `ha core info`). What each file is for: `resources-before.json` is the pre-change capture that `verify-resource
--before` needs (it must be the raw persisted file, in the same form as the later read-back); `sha-before.txt` holds the sha256 of
the persisted resource list, the dashboard list, every persisted dashboard configuration and every dashboard file (the production
Overview and the existing Intelligence dashboard among them); `core-info-before.txt` holds the Home Assistant version. The three
counts at the end must be at least 1 (the Intelligence card's resource is registered: the new dashboard reuses it) and then 0 and 0
(nothing of this update exists yet). The host's Home Assistant `.storage` file names are those of Home Assistant itself
(`lovelace_resources`, `lovelace_dashboards`, `lovelace.<dashboard id>`); the first read shows what is there, and any name that
does not match is reported, not guessed.

Also read, with the coordinator's existing read-only state reader (the same Supervisor-API route as `tools/ecco-snapshot.ps1`; no
token is ever put in a command line or a file), and record offline: the Intelligence status entity (its state, `mode` and
`applies_nothing` attributes and when it was last updated), the Intelligence freshness and watchdog entities, the pause helper's
state and its `last_changed`, and the control entities of the earlier supervised installs (the write enables, the arm and schedule
switches, the dongle's manual write counter, the TOU edit helper), exactly as their baselines list them.

The owner reads the two voice-assistant exposure settings (Settings, Voice assistants, Expose: "expose new entities" for Assist and
for Google Assistant) and states the RG-F3 decision (G5).

### 5.2 Step 2: the owner's protected backup

The owner makes a full backup in the Home Assistant UI with a protected (encrypted) option, notes its name and time in
`<OFFLINE_EVIDENCE_DIR>`, and keeps the password out of every chat, file and repository. The coordinator never asks for it and never
makes a backup over SSH as a substitute (the deploy tool's own backup folder, `/config/ecco-backups/<stamp>/`, holds only a copy of
the resource list for this update; it is a convenience, not a backup).

### 5.3 Step 3: copy the card (a write: one new file)

The destination is the content-addressed name. `<sha8>` is the first eight hex characters of the card's sha256 (section 13).
`-Destination` must be given: the tool derives a default only for a `dist` asset or a package or dashboard. The destination is on
the tool's allowlist (`/config/www/ecco/`); the tool refuses `/config/ecco/site-local/`, `/config/ecco/intelligence/` and
`/config/ecco/staging/` and, with the shell, nothing there is touched.

```powershell
cls
Set-Location <checkout>
$PY = '<PY>'
.\tools\deploy-ha.ps1 -Source frontend\ecco-mode-shell\ecco-mode-shell.js -Destination /config/www/ecco/ecco-mode-shell.<sha8>.js -Python $PY
```

When the owner's SSH alias is not the tool's default `ecco-ha`, add `-SshHost <production alias> -Target Production` (the tool then
requires `-Target`, and refuses `Production` for a host that carries the test-instance marker).

Preconditions the tool enforces itself: the source is a file inside the checkout, the working tree is clean (the generated files
under `dist\` are git-ignored), repository validation passes with `-Python`, the SSH probe passes and the target guard proves the
host is the production one. Never pass `-SkipValidation`, `-AllowDirtyWorkingTree` or `-Restart`. If a local gate pin file
(`ecco_dashboard_gate.local.txt`, git-ignored) exists in the checkout the run states the pinned gate; a fresh checkout has none, and
the gate does not apply to a `.js` destination either way.

Expected output, in order (from the tool's code): `Target : Production - ...`; `Running the dashboard preservation gate
(read-only)...` followed by `not a dashboard destination: the dashboard preservation gate does not apply`; `No existing remote file;
rollback will remove the new file if validation fails.`; `Uploading frontend/ecco-mode-shell/ecco-mode-shell.js ->
/config/www/ecco/ecco-mode-shell.<sha8>.js`; `Upload SHA256 verified: <the card's sha256>`; `Post-install SHA256 verified: <the same>`;
`Running Home Assistant configuration check...`; `Configuration check passed. Home Assistant was NOT restarted.`; then the block
`ECCO DEPLOYMENT PASSED` with `Restart : no` and `Backup : none (new file); ...`, and the reminder `RESOURCE NOT REGISTERED
ecco-mode-shell: no resource loads this card. This copy is NOT LIVE until a resource with URL /local/ecco/ecco-mode-shell.<sha8>.js
(JavaScript module) is added.` Nothing a dashboard loads has changed yet.

Then check the bytes Home Assistant serves, before anything is registered:

```powershell
cls
& $PY tools\ecco_deploy_preflight.py verify-served --plan dist\geek-u1\plan.json --base-url <HA URL>
```

Expected: one `PASS  served ecco-mode-shell.<sha8>.js: sha256 matches` line and exit 0. (It is one GET of the file a browser would
fetch.)

If the tool prints a rollback message, it removed its own new file and re-ran the configuration check; read the message to the
end, record it offline and stop. Do not retry without the owner.

### 5.4 Step 4: the owner adds the one resource; the read-back

The owner opens Settings, Dashboards, the three-dot menu, Resources (advanced mode must be on in the owner's profile), adds a
resource with the URL `/local/ecco/ecco-mode-shell.<sha8>.js` and the type **JavaScript module**, and saves. **One item, nothing
else.** No ECCO tool edits resources, and a resource is shared by every dashboard: this one is new and loads only the shell.

Then the coordinator reads the persisted list again and runs the existing read-back gate. The read-back must be less than 30 minutes
old when the gate runs (it checks the file time) and must be captured the same way as the baseline:

```powershell
cls
$H = '<production alias>'
$E = '<OFFLINE_EVIDENCE_DIR>\u1-baseline'
ssh $H "cat /config/.storage/lovelace_resources" | Out-File -Encoding utf8 "$E\resources-now.json"
& $PY tools\ecco_deploy_preflight.py verify-resource --plan dist\geek-u1\plan.json --resources "$E\resources-now.json" --before "$E\resources-before.json" --base-url <HA URL>
```

Expected: the check lines, then `RESOURCE VERIFIED ecco-mode-shell -> /local/ecco/ecco-mode-shell.<sha8>.js (id <8 hex>, persisted,
read back at <UTC>)` and `verify-resource PASSED: 1 card(s) verified; not checked: nothing`, exit 0. The gate checks that exactly
one resource loads the card, that its URL and type are the plan's, that the card had no resource before (so this is a new entry),
that **no other resource was added, removed or changed** since the baseline, that the bytes served at that URL hash to the plan's
sha256, and that the read-back is fresh. Report the resource as live only after this exit 0. Any other line (`NOT SWITCHED`, `NOT
VERIFIED`, `refused`) is a stop: the owner corrects or deletes the resource and the gate is run again; nothing proceeds.

The plan is hand-made because the tool lists its own cards in a constant that does not include this one. No safety tool is edited
and none is bypassed: the same checks run, on this one resource.

### 5.5 Step 5: the owner creates the dashboard

The owner opens Settings, Dashboards, Add dashboard, chooses a new dashboard from scratch, gives it a title (suggested: `ECCO Modes
(first look)`) and a URL (suggested: `ecco-modes-u1`; Home Assistant needs a hyphen), switches **Require admin** on, and creates it.
Then in that dashboard: Edit dashboard, the three-dot menu, Raw configuration editor, select all, paste the generated text, Save.
(The menu labels are those of the Home Assistant frontend the author has not seen on the production host: use what the screen shows;
**stop if the raw configuration editor is not offered for this dashboard**.)

To put the text on the clipboard without opening a 147 KB file by eye:

```powershell
cls
Get-Content -Raw -Encoding utf8 <checkout>\dist\geek-u1\dashboard-config.json | Set-Clipboard
```

The text is JSON (a subset of YAML, which the editor accepts), so there is no indentation or quoting to get wrong, and it holds the
catalogue inline: there is no file to include and no address in it.

### 5.6 Step 6: read-only after-checks

The coordinator, with the owner's authorisation, repeats the baseline reads (5.1) into `$E\...-after...` files and compares:

```powershell
cls
$H = '<production alias>'
$E = '<OFFLINE_EVIDENCE_DIR>\u1-baseline'
ssh $H "cd /config && sha256sum .storage/lovelace* ecco/dashboards/*.yaml" | Out-File -Encoding utf8 "$E\sha-after.txt"
ssh $H "cat /config/.storage/lovelace_resources" | Out-File -Encoding utf8 "$E\resources-after.json"
ssh $H "cat /config/.storage/lovelace_dashboards" | Out-File -Encoding utf8 "$E\dashboards-after.json"
ssh $H "ls -l /config/www/ecco/" | Out-File -Encoding utf8 "$E\www-ecco-after.txt"
Compare-Object (Get-Content "$E\sha-before.txt") (Get-Content "$E\sha-after.txt")
Compare-Object (Get-Content "$E\dashboards-before.json") (Get-Content "$E\dashboards-after.json")
Compare-Object (Get-Content "$E\www-ecco-before.txt") (Get-Content "$E\www-ecco-after.txt")
```

The expected differences, and only these: in `sha-after.txt`, the persisted resource list and the persisted dashboard list have new
hashes and one new line names the new dashboard's own configuration file; **every other line is identical, in particular every file
under `ecco/dashboards/` (the production Overview and the existing Intelligence dashboard)**. In the dashboard list exactly one item
is added, with admin-only set and the storage mode; in `/config/www/ecco/` exactly one new file. The resource list differs by exactly
one added item (`verify-resource` already proved it in step 4; re-run it here with the fresh read-back if more than 30 minutes have
passed: the plan and the `--before` file are the same).

Read the dashboard's persisted configuration and compare it with the generated text. This proves the paste arrived exactly as
generated (the key order and the formatting do not matter; the content does):

```powershell
cls
ssh $H "cat /config/.storage/lovelace.<dashboard id>" | Out-File -Encoding utf8 "$E\stored-config.json"
& <PY> -I -B -X utf8 tools\geek_mode_dashboard_config.py --verify-storage "$E\stored-config.json"
```

Expected: `STORED CONFIGURATION EQUALS THE GENERATED ONE`, exit 0. `<dashboard id>` is the item's `id` in
`dashboards-after.json`. The tool reads the persisted file's `data.config` (or a bare configuration) and refuses, exit 2, a file it
cannot read as JSON; it does not guess a different layout.

Home Assistant's log: read the recent lines and compare with a read taken at the baseline (the tools print only; they change
nothing):

```powershell
cls
.\tools\ha-logs.ps1 -Lines 400 -Pattern 'lovelace'
.\tools\ha-logs.ps1 -Lines 400 -Pattern 'frontend'
```

No new line may mention the dashboard, the resource or the card. **The log shows server-side errors only; a browser error never
reaches it** (step 7 reads the browser's console).

Finally re-read the Intelligence status entity and the pause helper with the same reader as in 5.1: the status entity's state,
`mode` and `applies_nothing` are as at the baseline, it is still publishing on its own schedule, and the pause helper's state and
`last_changed` are unchanged.

### 5.7 Step 7: the owner's look (ONE look)

Desktop browser, a fresh page load (Ctrl+F5, so the new resource is fetched), the new dashboard.

**First, Production Mode only.** In this look the owner checks, and records yes or no with a screenshot kept offline:

1. the shell loads and starts in Production (the switch shows Production selected), with no red or yellow error card;
2. the existing ECCO Intelligence card and the watchdog and status card are shown and read as they do on the existing Intelligence
   dashboard (open that dashboard in a second tab and compare: same figures, same status);
3. the **alert strip** tells the same story as that card: nothing contradictory (an all-clear card and a critical strip line, or the
   reverse, is a stop); the strip is never blank (a blank strip is a defect: stop);
4. the Production sentence under the switch is present and plain;
5. the existing pause tile is present, shows its current state, and is **not tapped**. No other control is touched;
6. the browser console (F12) shows no error that names the shell or its resource (other cards' messages are noted, not judged);
7. the page stays responsive (no freeze; the card has a bounded work budget, but real performance is unmeasured: section 9).

**Then, only after the owner says go: Geek Mode.** Press the Geek switch once and check:

1. the strip is unchanged (same lines, same words);
2. the inspector lists **17 source rows**, in five groups (3, 4, 3, 2 and 5 rows: status and health, advice, forecasts, data quality
   and accuracy, controls and alerts); a sixth group, "Discovered", has rows only if Home Assistant holds an Intelligence entity the
   catalogue does not name: record its count, it is information, not a failure;
3. opening a row shows its attributes (the catalogue declares 344 attribute rows in all); a count of "not present" on a few
   conditional rows is expected (42 declared rows were absent in the one live capture of 14 Nov, section 9);
4. every row shows an age ("updated ... ago") or says honestly that it cannot tell; a value the shell withholds shows `[withheld]`
   (two declared attributes are withheld by design);
5. the search box and the filters work; the three buttons (open an entity's dialog for a sensor, copy to the clipboard, download a
   file) are optional and **not part of this look**: nothing needs them;
6. switch back to Production; the Production body is as it was;
7. the console is still free of shell errors; nothing was written (step 8 proves it).

The pause tile is hidden in Geek Mode: that is by design. Anything the owner sees that is not on these lists is noted, not fixed
at the look.

### 5.8 Step 8: no-write evidence

With the owner's authorisation, immediately after the look and before anything else changes: read the control entities of the
baseline (the pause helper, the write enables, the arm and schedule switches, the dongle's manual write counter, the TOU edit
helper, the Intelligence status) and read the Home Assistant logbook for the period from the start of step 3 to now for those entities.
Expected: no control entity's state or `last_changed` is newer than the baseline's, the manual write counter is unchanged, and the
Intelligence status entity has published only on its own schedule. What this does **not** prove, and what carries the rest: a service
call that changes no state leaves no durable record. The case against a write rests on three things together: the card's source has no
service call (pinned in `tools/tests/test_ecco_mode_shell_card.py`: no `call_service`, `callService`, `fetch`, websocket, storage,
dynamic code, one timer, two window listeners, three click-only actions, and `hass` read for `states`, `locale` and `themes` only),
the Node suite's trap on every `hass` function (`frontend/ecco-mode-shell/test/generated-config.test.mjs`), and the owner's
statement that nothing was tapped.

### 5.9 Step 9: close-out

- an inbox status update in the private repository (`docs/project-management/status-updates/inbox/`): what ran, when, the hashes,
  the outcome of each step, the owner's decisions. **Never edit the master status from a working session.**
- the offline evidence in `<OFFLINE_EVIDENCE_DIR>`: the baseline and after files, the `verify-served` and `verify-resource` output, the
  deploy output with its backup folder name, the screenshots, the console text, the times;
- a bridge post, **counts only** (no value, no entity id, no address), and only on the owner's go; a push likewise.

## 6. Stop conditions (any step)

Stop, change nothing more, record the state, and ask the owner, when: a tool prints anything but the expected line; a hash differs
from its pin; a read finds something of this update already present; the baseline shows Core not running or the Intelligence
status not what it was; the resource gate does not exit 0; the dashboard list or the resource list differs by more than the one item
the step added; any file under `ecco/dashboards/` changes; a control entity changes; the look shows a strip that contradicts the
existing card, a blank strip, a freeze, or an error naming the shell; a step would need a restart. Never retry a live write without
the owner. Never approve, work around or weaken a permission prompt or a safety gate.

## 7. Rollback, in order

Each artefact is rolled back separately, newest first, and only by the owner's action or with the owner's authorisation. Nothing is
restarted. The tool's own automatic rollback (step 3) already removes the new file and re-runs the configuration check if the copy fails.

1. **A3, the dashboard.** The owner deletes it (Settings, Dashboards, the new dashboard, Delete). The dashboard list returns to
   `dashboards-before.json`; the persisted configuration file of that dashboard is gone with it.
2. **A2, the resource.** The owner deletes the one resource (Settings, Dashboards, Resources, the item, Delete), then the coordinator
   re-reads the persisted list and compares it with the saved baseline copy:

   ```powershell
   cls
   ssh $H "cat /config/.storage/lovelace_resources" | Out-File -Encoding utf8 "$E\resources-after-rollback.json"
   Compare-Object (Get-Content "$E\resources-before.json") (Get-Content "$E\resources-after-rollback.json")
   ```

   No output means equal. The shell element then no longer exists in any page after a hard refresh.
3. **A1, the card file.** It may stay: with no resource pointing at it, a file under `/config/www/ecco/` is never loaded (it is
   served on request only). If the owner wants it gone, it is **moved by hand, never deleted**, into a new backup folder, with the owner's
   authorisation. `deploy-ha.ps1 -Action Retire` does not cover it (that action moves only the exact Intelligence files its code lists).
   A plain move (one host command; no `cp -p`, because Home Assistant caches YAML dashboards by file time and this file is not one):
   `ssh $H "mkdir -p /config/ecco-backups/<stamp>-u1-rollback && mv /config/www/ecco/ecco-mode-shell.<sha8>.js /config/ecco-backups/<stamp>-u1-rollback/"`.
4. **Re-check.** Repeat the sha256 listing of 5.6: the production Overview and every other dashboard file have their baseline sha256;
   the resource list equals the baseline copy; `/config/www/ecco/` equals `www-ecco-before.txt` (or lacks only the moved file).

**A later version** of the card is a new file with a new content address and one resource edit (repoint) by the owner, with
`verify-resource` and the old file left inert: the rollback of a repoint is the owner editing the URL back, then the same read-back.

## 8. The deploy backup folder

The deploy run leaves `/config/ecco-backups/<stamp>/` holding a copy of the resource list. It is kept (nothing is deleted by any
ECCO tool) and listed in the evidence; the owner cleans such folders up when the owner decides.

## 9. What is NOT established

Say these plainly in every report about this update.

- **The shell has never run in a real Home Assistant or a real browser.** It has run in Node with a stand-in DOM and in headless
  Chrome against a stand-in `hass`. Unverified until the look: how the real frontend nests the child cards it creates through the
  card helpers, the real theme variables, console cleanliness, and real performance on the real data.
- **42 of the 344 declared attribute rows are conditional** and were absent in the one live capture (14 Nov): they are expected to read
  "Not present" on the real host until the condition holds. One declared helper (the reserve helper) is **NOT_CHECKED_LIVE**: the
  capture's filter did not cover its name. The catalogue is compared with the live shape of 14 Nov only; run the comparison again
  after any contract change.
- The pins and the mutation proof are offline. The Node suites, the 518-mutant run and the headless strip check run on this PC only; CI
  runs no Node. CI's guard is the Python static pin suite.
- A service call that changes no state leaves no durable record (5.8).
- Intelligence is NOT ACCEPTED overall. The look says nothing about forecast accuracy, the solar forecast, R9 or Stage 3.
- Phone and tablet layouts are not part of U1; a desktop look is.

## 10. What a first-look failure looks like, and what it means

| What the owner sees | What it means | What to do |
|---|---|---|
| a red card "Custom element doesn't exist: ecco-mode-shell" | the resource is not loaded: wrong URL, type not module, a cached page, or the file not served | hard refresh; check the resource's URL and type; run `verify-resource`; stop if it still shows |
| the shell shows but a strip line says the catalogue is not valid | the pasted configuration is damaged (truncated or altered) | run `--verify-storage`; repaste; stop if it differs again |
| a strip line says the card configuration has a problem | a list in the pasted text is not a list | the same: compare with `--verify-storage` |
| a child card shows "Card could not be shown" or Home Assistant's own error card for a child | the Intelligence card's resource is not loaded, or a core card could not be built | check the baseline's count of the Intelligence resource; note the message |
| a blank alert strip | a defect: the strip must never be blank | **stop**, screenshot, do not open Geek Mode |
| the strip and the existing card contradict each other | a defect or a stale read | **stop**, record both, do not fix at the look |
| every row reads "Unverified" or "cannot tell the age" | the browser's clock is more than five minutes ahead of Home Assistant's (a time in the future is not trusted) | correct the PC clock, reload; not a card defect |
| every row reads "Not measured" or "Not present" | the Intelligence entities are not published (the integration is off or unavailable), or the ids differ from the catalogue | compare with the baseline status; stop if the baseline had them |
| the page freezes or the tab is slow | real performance is unmeasured | close the tab, record the time and the browser; stop |
| a console error naming the shell | a defect on the real host | record the text; stop |
| the pause tile is hidden in Production | a defect of the pass-through | stop |
| the pause tile is visible in Geek | a defect (Geek hides it) | stop |

A look that fails stops the update; the rollback is section 7. A look that passes is a first look on one desktop, nothing more.

## 11. Release bookkeeping is deferred (decision H4)

This change adds the card, its catalogue, its tests, the generator and this runbook to the repository. It does **not** add the
manifest stanza, the pin-chain entry, the PEX line or a `VERSION.yaml` edit: those are merge-time release bookkeeping, and the
scope-chain file is edited by every pull request in flight (R9, Stage 3, grid-loss, F5), so the owner decides the order. The U1
install does not need any of them: the deploy tool does not read `deployment/ha-manifest.yaml`. A deliberate tripwire in
`tools/tests/test_geek_mode_example.py` refuses any pinned file (the manifest, `VERSION.yaml`, the scope chain, the Intelligence
dashboard, the changelog) that names the shell by its hyphenated name: this change keeps to it, and the changelog entry says "shell card"
in words. The owner may retire the tripwire at the merge.

## 12. Decisions the owner must make

| # | Decision | Notes |
|---|---|---|
| D-U1-1 | install from the branch commit (after green CI) or merge the draft pull request first (5.0) | the card is content-addressed, so the installed bytes are identified by their sha256 either way |
| D-U1-2 | RG-F3: "expose new entities" for Assist and Google Assistant, off or waived for U1 | U1 creates no entity |
| D-U1-3 | the order of the release bookkeeping against R9, Stage 3, grid-loss and F5 | section 11 |
| D-U1-4 | when to push and open the draft pull request, and when the owner's M2 scan runs | each is its own go |
| D-U1-5 | the title and URL of the new dashboard, and whether it shows in the sidebar | suggestions in 5.5 |
| D-U1-6 | whether the Geek look follows the Production look in the same session | H5: only after the owner says go |

## 13. Evidence: the offline verification on the exact tip

Filled after the final verification run; see the end of this file.
