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

**A Lovelace module resource is global, and this is said plainly.** Once A2 is registered, Home Assistant's frontend loads the
155 KB shell module on **every dashboard page of every client**: the production Overview, the existing Intelligence dashboard,
non-admin users, and wall and phone clients included, even though only the new dashboard places the card. The module only defines
the element and its card-picker entry (it creates no entity, sends nothing and reads nothing until a dashboard places the card),
but it is loaded everywhere until the owner deletes the resource (section 7). So "other dashboards are untouched" means their files
and configuration, not what their pages load. Step 4 therefore ends with one look at the production Overview (5.4), and section 9
lists the known console noise.

**Admin-only is a visibility setting, not a security boundary.** "Require admin" on the new dashboard (A3) is what keeps the page out of a
non-admin user's sidebar: Home Assistant's frontend hides the panel from, and does not register it for, non-admin users (recalled from Home
Assistant's behaviour, not verified: no non-admin account was used to confirm it). It is a visibility control for the page. It is **not** a security
boundary against a non-admin who calls Home Assistant's own API (recalled, not verified: whether such a call can read the stored dashboard text), and
it does not limit what the module resource (A2) loads: that resource is global (above). What follows: the dashboard configuration holds only
descriptive text and the Intelligence entity names of the repository's example, no secret, no address and no token (the generator's own privacy scan
and the pin suite check the text, section 2), so nothing in it needs protecting; and the states the card shows are readable by any signed-in user
through Home Assistant's own interfaces whether or not this page exists (recalled, not verified), which this update neither widens nor narrows.

**Not touched, by design:** the files and configuration of the production Overview and of every other dashboard, every existing
resource (the Overview is guarded by the site's dashboard preservation gate; this update never writes a dashboard file, so the
gate does not apply and is not bypassed), every package, helper, automation, script and entity, the Intelligence integration and
its site file, the card of the Intelligence integration, firmware, the dongle, the inverter and InfluxDB. The shell creates **no
entity**. The existing pause tile is shown in Production unchanged and keeps the toggle it has today (a write to the pause
helper, exactly as on the existing Intelligence dashboard); Geek Mode hides it. Nothing in this update taps it (step 7).

**Why a new storage dashboard (decision H1).** It touches no pinned file (the existing Intelligence dashboard file is pinned by
several suites and the production Overview is protected), uses no `!include` of a JSON file (never proven on a real Home Assistant),
confines any failure to one new dashboard, needs no restart (a storage dashboard is registered live; a new `lovelace: dashboards:`
entry in YAML would need one), and the rollback is two deletions. The catalogue is inside the dashboard configuration, so it is
never placed under `/config/www`, which is served without authentication (it names entity ids and texts). The alternative (a
second view in the existing Intelligence YAML dashboard with an `!include` of the catalogue) is **not prepared**: it needs
owner-approved edits of two protected assertions and an `!include` read that has never run on the real host.

### 1.1 What U1 preserves, and how that was checked

Checked offline on the exact tip (round 3, section 13). None of it has been observed on a real Home Assistant.

| Preserved | What was checked | Where |
|---|---|---|
| the production Overview and the existing Intelligence dashboard (their files and configuration) | no step writes a dashboard file: the deploy tool writes ONE new `.js` file under `/config/www/ecco/` (and its backup folder), the resource and the dashboard are made by the owner in the UI, and step 6 compares the sha256 of every `.storage/lovelace*` file and every file under `ecco/dashboards/` with the baseline | steps 3, 5, 6; 5.6 |
| the existing Intelligence view | the three cards Production shows (the Intelligence card with its 13 entity options, the watchdog and status entities card with its 4 rows, the pause tile) and the text-fallback markdown card are **deep-equal** to the cards of the existing Intelligence dashboard definition in this repository, in the example and in the generated configuration | `frontend/ecco-mode-shell/examples/`; the generator suite |
| existing safety alerts and control behaviour | the shell's source has no service call, request, websocket, storage or dynamic code (a word-bounded search of the card source finds none, and the pin suite's forbidden-API rule scans the whole text); it reads only the states, the locale and the theme of Home Assistant's object, and has three click-only actions (open an entity's dialog by the standard event, copy to the clipboard, download a file); no step creates an entity, helper, automation or package, restarts Home Assistant or edits an existing dashboard | `tools/tests/test_ecco_mode_shell_card.py`, rules [2] to [5]; the Node trap on every `hass` function |

**The one write.** The pause tile toggles the pause helper: the same write the existing Intelligence dashboard already offers, now also on a second
page. The shell itself never writes, and nobody taps the tile during this update (step 7, S2).

**What is different from the existing Intelligence page, all of it by design:** (1) it is a NEW storage-mode dashboard with "Require admin"; the
existing one is a YAML dashboard that is not edited; (2) the same cards sit inside one shell card, so the page order is the switch and a fixed
note, the alert strip, the Intelligence card, the watchdog and status card, the one Production sentence and the pause tile, then the text fallback
outside the shell (the existing page order is the Intelligence card, the pause tile, the watchdog and status card, the text fallback); (3) the shell
adds the switch, the note, the sentence, the catalogue-driven alert strip (19 rules) and, in Geek Mode, the inspector (17 sources, 344 attribute rows),
and Geek Mode hides the pause tile and keeps the two read-only cards; (4) one module resource is registered for every page (above).

## 2. The artefacts and their hashes

The pins are held in `tools/tests/test_ecco_mode_shell_card.py`; any change to the card, the catalogue, the example or the
generated configuration is a deliberate edit of that file. Full values are in section 13 for the exact tip. The suite's rules
(forbidden APIs, the exact surface, the read-only sets, the member-access rules, the pinned redaction words) are **defence in
depth, not a proof**: they catch the careless and the obvious, and an edit written to get past them can. The byte pin is the real
guard, and any repin of it needs a review of the full diff of the card, never only a green run of the suite.

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
| G5 | release gate RG-F3 (the two voice-assistant settings "expose new entities", for Assist and for Google Assistant) is recorded: the owner states in the session whether both are off, or consciously waived because this update creates **no entity**. Any later install that creates entities waits for both to be off |
| G6 | the browser used for the look is a desktop browser whose clock is within five minutes of Home Assistant's clock (section 10) |
| G7 | the owner agrees in advance that the first look is **Production Mode only**, that Geek Mode follows only after the owner says go, and that the pause tile is never tapped |

## 4. The steps

| Step | What | Who | Offline / live | Read-only / write | Own owner authorisation | Expected result | Stop condition |
|---|---|---|---|---|---|---|---|
| 0 | offline gates on the exact commit: the verification table (section 13), the owner's M2 private-pattern scan, the push, draft pull request and CI, the choice D-U1-1 | COORDINATOR (the M2 scan is the owner's tool, run only on the owner's go) | offline (the push and CI touch GitHub only) | read-only on the live system; a push is a GitHub write | **yes**, each of: the M2 scan, the push, the pull request, the choice of commit | the table is green or its failures are named as known; CI green on the pushed tip if the owner chose to push | any new failure; a card or catalogue hash that is not the pinned one |
| 1 | live read-only baseline (5.1) | COORDINATOR | live | read-only | **yes** (a live read) | the baseline files saved offline, among them a byte-exact copy of each `.storage/lovelace*` file; G4 holds | anything of A1 to A3 already present; the Intelligence card's resource missing; Core not running; a copy that is not byte-exact |
| 2 | the owner's protected full backup in the UI; RG-F3 decision recorded; quiet window confirmed | OWNER | live (UI) | the owner's own backup action | the owner's own action | a protected backup exists (its name and time recorded offline, never its password) | no protected backup |
| 3 | copy the card with `deploy-ha.ps1` to the content-addressed destination, then `verify-served` (5.3) | COORDINATOR | live | **write** (one new file under `/config/www/ecco/`, its backup folder) | **yes** | `ECCO DEPLOYMENT PASSED`, `Restart     : no`, a `RESOURCE NOT REGISTERED` reminder; `verify-served` PASS | any failure line; a hash mismatch; the tool's own rollback message; anything but the one new file |
| 4 | the owner adds ONE module resource by hand; the coordinator reads the persisted list and runs `verify-resource`; then one owner look at the production Overview, because the resource is global (5.4) | OWNER (the add, the look), COORDINATOR (the read-back) | live | the add is a Home Assistant write by the owner; the read-back and the look are read-only | the owner's action; **yes** for the read-back | `RESOURCE VERIFIED ecco-mode-shell -> ...` and exit 0; the list differs from the baseline by exactly one added item; the Overview renders as before with no new console error that names the shell | any other line; any other resource changed; the Overview shows an error that names the shell |
| 5 | the owner creates the admin-only storage dashboard, makes the two pre-save checks and pastes the generated configuration (5.5) | OWNER | live (UI) | a Home Assistant write by the owner | the owner's action | the dashboard exists, "Require admin" is on, the paste saved in the NEW dashboard | the raw editor is not offered; Home Assistant refuses the text; either pre-save check fails |
| 6 | read-only after-checks (5.6) | COORDINATOR | live | read-only | **yes** (a live read) | the Overview file and every other dashboard file have their baseline sha256; the resource list differs by exactly one item; the dashboard list by exactly one item; the stored configuration (copied with `scp`) equals the generated one; no new lovelace, frontend or shell line in the log; Intelligence status and pause helper unchanged | any other difference |
| 7 | ONE owner look: Production first, then Geek only after the owner says go (5.7) | OWNER | live (browser) | read-only (a presentation toggle). **Never tap the pause tile** | the owner's action; the Geek look needs the owner's separate go | the checks of 5.7 | any of the stop lines of 5.7 or section 10 |
| 8 | no-write evidence (5.8) | COORDINATOR | live | read-only | **yes** (a live read) | no control entity changed since the baseline (the states are the same and the state history shows one row each); Intelligence still publishing | any control entity changed |
| 9 | close-out (5.9) | COORDINATOR | offline | local files and local commits; a post to the coordination channel and a push only on the owner's go | **yes** for the post and any push | the evidence is filed | n/a |

No step restarts Home Assistant. A step that would need a restart is out of scope and stops the update.

## 5. The steps in detail

**How the blocks work.** Each PowerShell block is self-contained: it sets its own `$H` (the production alias), `$E` (the evidence
folder), `$PY` (the Python 3.12 interpreter) and moves to `<checkout>` where it needs the repository's tools, so it runs alone in a
fresh Windows PowerShell console (not the ISE, which cannot change the console encoding). Fill the placeholders in its first lines.
A block that is run more than once (the state read, the state comparison) says which line to change.

**Text read from the host is read byte for byte.** A stored file is copied with `scp`, as the repository's own deploy tools do
(their comment: a captured `ssh` `cat` is re-decoded by the console code page). Where a block does capture `ssh` output with
`Out-File`, its first lines set the console encoding to UTF-8 without a byte order mark. Why: Windows PowerShell decodes what a
native program prints with the console's code page (an OEM page such as 850 or 437), and that turns every non-ASCII character of
a stored dashboard (the configuration holds two middle dots) into wrong characters. **A mismatch that is caused by the console
code page is a false failure of the check, not a defect of the dashboard**; `--verify-storage` names that cause when it sees it
(5.6), and the remedy is the `scp` copy, not a second paste.

### 5.0 Step 0: offline gates

Work from a clean checkout of the exact commit, made without line-ending conversion (a CRLF checkout changes the card's bytes and
therefore its content address; a Windows clone with automatic line-ending conversion is such a checkout):

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
$PY = '<PY>'
Set-Location <checkout>
New-Item -ItemType Directory -Force dist\geek-u1 | Out-Null
& $PY -I -B -X utf8 tools\geek_mode_dashboard_config.py --out dist\geek-u1\dashboard-config.json --resource-plan dist\geek-u1\plan.json
& $PY -I -B -X utf8 tools\geek_mode_dashboard_config.py --check dist\geek-u1\dashboard-config.json
```

The first command prints the size and sha256 of the configuration and the resource URL with the card's sha256. The second prints
`OK: <bytes> bytes, sha256 <64 hex>` and exits 0 only when the file equals a fresh generation byte for byte and the checks pass
(section 13 lists the size and sha256 for the exact tip). Both need no network and write nothing else (the first refuses, exit 2, to replace an
existing output file whose bytes differ, unless `--overwrite` is added). `plan.json` is a small
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
never to a repository. The same reads are run again in step 6 (and the state read in step 8), so the sets can be compared.

**Block 1: the files, the lists and a byte-exact copy of every persisted dashboard file.**

```powershell
cls
$H = '<production alias>'
$E = '<OFFLINE_EVIDENCE_DIR>\u1-baseline'
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
$OutputEncoding = [Console]::OutputEncoding
New-Item -ItemType Directory -Force "$E\lovelace-before" | Out-Null
Get-Date -Format o | Out-File -Encoding utf8 "$E\time-before.txt"
ssh $H "cat /config/.storage/lovelace_resources" | Out-File -Encoding utf8 "$E\resources-before.json"
ssh $H "cat /config/.storage/lovelace_dashboards" | Out-File -Encoding utf8 "$E\dashboards-before.json"
ssh $H "cd /config && sha256sum .storage/lovelace* ecco/dashboards/*.yaml" | Out-File -Encoding utf8 "$E\sha-before.txt"
ssh $H "ls -l /config/www/ecco/ | grep -v '^total'" | Out-File -Encoding utf8 "$E\www-ecco-before.txt"
ssh $H "ha core info" | Out-File -Encoding utf8 "$E\core-info-before.txt"
foreach ($line in Get-Content "$E\sha-before.txt") {
    $parts = $line -split '\s+', 2
    if ($parts.Count -eq 2 -and $parts[1] -like '.storage/lovelace*') {
        $name = Split-Path -Leaf $parts[1]
        scp -q "${H}:/config/$($parts[1])" "$E\lovelace-before\$name"
        if ($LASTEXITCODE -ne 0) { throw "the copy of $($parts[1]) failed" }
        $got = (Get-FileHash -Algorithm SHA256 "$E\lovelace-before\$name").Hash.ToLower()
        '{0}  {1}' -f $(if ($got -eq $parts[0]) { 'EXACT    ' } else { 'NOT EXACT' }), $name
    }
}
(Select-String -Path "$E\resources-before.json" -SimpleMatch 'ecco-intelligence-card').Count
(Select-String -Path "$E\resources-before.json" -SimpleMatch 'ecco-mode-shell').Count
(Select-String -Path "$E\www-ecco-before.txt" -SimpleMatch 'ecco-mode-shell').Count
```

These are read-only forms that already exist in the repository: the `cat` of the persisted resource list is the capture that
`docs/user/site-render.md` documents for `verify-resource`, `ha core info` is the call of `tools/ha-status.ps1`, and `sha256sum` and `scp` are what
`tools/deploy-ha.ps1` itself runs for its hashes and its upload. The `sha256sum` over a file glob and the `scp` of each stored dashboard file are new
combinations of them and have not been run on the production host. What each file is for: `resources-before.json` is the pre-change capture that
`verify-resource --before` needs (it must be the raw persisted file, in the same form as the later read-back); `sha-before.txt`
holds the sha256 of the persisted resource list, the dashboard list, every persisted dashboard configuration and every dashboard
file (the production Overview and the existing Intelligence dashboard among them); `core-info-before.txt` holds the Home Assistant
version; `www-ecco-before.txt` lists the card folder (the `total` line is left out, as it changes with any file).
`lovelace-before\` holds **a byte-exact copy of each persisted `.storage/lovelace*` file**, so that a paste into the wrong
dashboard can be pasted back (section 7): each copy is checked against its sha256 line and must print `EXACT`; a `NOT EXACT` line
is a stop. The three counts at the end must be at least 1 (the Intelligence card's resource is registered: the new dashboard reuses
it) and then 0 and 0 (nothing of this update exists yet). The host's Home Assistant `.storage` file names are those of Home
Assistant itself (`lovelace_resources`, `lovelace_dashboards`, `lovelace.<dashboard id>`); the first read shows what is there, and
any name that does not match is reported, not guessed.

**Block 2: the entity list, made once.** The states to read are the Intelligence entities of the catalogue (the status, freshness,
watchdog and pause helper are among its 17 sources) plus the control entities of the earlier supervised installs (the write
enables, the arm and schedule switches, the dongle's manual write counter, the TOU edit helper). The list holds entity ids, so it
lives in `<OFFLINE_EVIDENCE_DIR>`, never in a repository:

```powershell
cls
$E = '<OFFLINE_EVIDENCE_DIR>\u1-baseline'
$PY = '<PY>'
Set-Location <checkout>
& $PY -I -B -X utf8 -c "import json; d = json.load(open('frontend/ecco-mode-shell/catalogue/intelligence.catalogue.json', encoding='utf-8')); print('\n'.join(sorted({s['entity_id'] for s in d['sources']})))" | Out-File -Encoding ascii "$E\u1-entities.txt"
```

Then the owner opens `u1-entities.txt` and adds, one id per line, the control entities exactly as their earlier baselines list
them.

**Block 3: the state read.** One read-only GET of the states through the Supervisor on the host, the same remote script as
`tools/ecco-snapshot.ps1` and the flight recorder use (the token is read on the host and is never printed, passed on a command
line or written to a file). Only the listed entities are kept:

```powershell
cls
$H = '<production alias>'
$E = '<OFFLINE_EVIDENCE_DIR>\u1-baseline'
$Tag = 'before'    # change this one line: 'before' in step 1, 'after' in step 6, 'look' in step 8
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
$OutputEncoding = [Console]::OutputEncoding
$ids = @(Get-Content "$E\u1-entities.txt" | ForEach-Object { $_.Trim() } | Where-Object { $_ -ne '' })
if ($ids.Count -eq 0 -or @($ids | Where-Object { $_ -notmatch '^[a-z0-9_]+\.[a-z0-9_]+$' }).Count -gt 0) { throw 'u1-entities.txt is empty or holds a line that is not an entity id' }
$remote = 'if [ -z "$SUPERVISOR_TOKEN" ]; then echo __ECCO_NO_SUPERVISOR_TOKEN__; exit 42; fi; curl -fsS -H "Authorization: Bearer $SUPERVISOR_TOKEN" http://supervisor/core/api/states'
$cmd = 'printf %s ' + [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($remote)) + ' | base64 -d | sh'
$raw = (& ssh -o BatchMode=yes $H $cmd) -join "`n"
if ($LASTEXITCODE -ne 0) { throw "the state read failed (ssh exit $LASTEXITCODE)" }
$all = $raw | ConvertFrom-Json
if ($null -ne $all.PSObject.Properties['data']) { $all = $all.data }
$index = @{}
foreach ($s in $all) { $index[[string]$s.entity_id] = $s }
$out = @(foreach ($id in $ids) { if ($index.ContainsKey($id)) { $index[$id] } else { [pscustomobject]@{ entity_id = $id; absent = $true } } })
ConvertTo-Json -InputObject $out -Depth 20 | Out-File -Encoding utf8 "$E\states-$Tag.json"
$out | Select-Object entity_id, state, last_changed, absent | Format-Table -AutoSize
```

Record from it, offline: the Intelligence status entity (its state, `mode` and `applies_nothing` attributes and when it was last
updated), the freshness and watchdog entities, the pause helper's state and its `last_changed`, and every control entity. An id
shown as absent is noted, not guessed. (This route was not run on the production host by the author: if it prints the
no-supervisor-token message or an error, stop; the same states can be read by hand in the Home Assistant UI, Developer tools,
States, and written down offline.)

**Block 4: the log baseline** (the tool prints only; it changes nothing; `-SshHost` is needed for an alias that is not the tool's
default `ecco-ha`):

```powershell
cls
$H = '<production alias>'
$E = '<OFFLINE_EVIDENCE_DIR>\u1-baseline'
Set-Location <checkout>
foreach ($p in 'lovelace', 'frontend', 'ecco-mode-shell') {
    .\tools\ha-logs.ps1 -SshHost $H -Lines 400 -Pattern $p 6>&1 | Out-File -Encoding utf8 "$E\log-$p-before.txt"
}
```

Each file holds the last 400 log lines that match (or the tool's "No matches" line); `6>&1` is there because the tool writes with
`Write-Host`. If the log is busy and 400 lines do not reach back far enough, raise `-Lines` (the tool allows up to 2000) for the
baseline and for step 6 alike.

The owner reads the two voice-assistant exposure settings (Settings, Voice assistants, Expose: "expose new entities" for Assist and
for Google Assistant) and states the RG-F3 decision (G5).

### 5.2 Step 2: the owner's protected backup

The owner makes a full backup in the Home Assistant UI with a protected (encrypted) option, notes its name and time in
`<OFFLINE_EVIDENCE_DIR>`, and keeps the password out of every chat, file and repository. The coordinator never asks for it and never
makes a backup over SSH as a substitute (the deploy tool's own backup folder, `/config/ecco-backups/<stamp>/`, holds only a copy of
the resource list for this update; it is a convenience, not a backup).

**What restoring this backup would do (said plainly, because it is the last resort and never the first rollback).** Restoring a Home Assistant
backup is a heavy action and the owner's decision: as the Home Assistant interface offers it (recalled, not verified on this host) it restarts Home
Assistant, and it returns everything the backup holds to its state at the time the backup was made, so that whatever changed or was recorded since
(settings, helper and control states, the history the database kept, other dashboards, anything an add-on or the owner changed meanwhile) goes back with
it. The small rollback of section 7 (delete the dashboard, delete the resource, leave or move the file) undoes only this update and restarts nothing.
The backup is for the case in which section 7 cannot undo what happened (S1 names it), and then only after the owner has weighed what has changed since
the backup was made.

### 5.3 Step 3: copy the card (a write: one new file)

The destination is the content-addressed name. `<sha8>` is the first eight hex characters of the card's sha256 (section 13).
`-Destination` must be given: the tool derives a default only for a `dist` asset or a package or dashboard. The destination is on
the tool's allowlist (`/config/www/ecco/`); the tool refuses `/config/ecco/site-local/`, `/config/ecco/intelligence/` and
`/config/ecco/staging/` and, with the shell, nothing there is touched.

**The exact names.** For the pinned card (sha256 `17410163c016...`, so `<sha8>` is `17410163`) three values must agree, character for character,
in the deploy line, in the owner's resource and in `plan.json`:

| What | Exact value |
|---|---|
| the file on the host (A1), the `-Destination` | `/config/www/ecco/ecco-mode-shell.17410163.js` |
| the resource URL (A2): no host, no query string, no `?v=` | `/local/ecco/ecco-mode-shell.17410163.js` |
| the resource type (A2) | `module` (the screen shows "JavaScript module") |

`plan.json` carries the URL and the type (`resource_url`, `resource_type`), made from the card file's own bytes, and `verify-served` and
`verify-resource` check against the plan, not against this text. **The deploy tool does not check that a name equals the content address**: it
installs the name it is given, inside its allowlist. The name is proven afterwards by `verify-served`, which fetches the plan's URL and compares the
sha256 (a wrong name is a 404 or a mismatch there, before any resource exists). A card that is not the pinned one has another name, and these three
values change with it.

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
host is the production one. Never pass `-SkipValidation`, `-AllowDirtyWorkingTree` or `-Restart`: the tool accepts all three (it does not refuse
them), so this is a rule of the runbook, and the output shows that it was kept (the line `Running repository validation before deployment...` is
there, no warning names `-AllowDirtyWorkingTree`, and the result block says `Restart     : no`). If a local gate pin file
(`ecco_dashboard_gate.local.txt`, git-ignored) exists in the checkout the run states the pinned gate; a fresh checkout has none. The dashboard
preservation gate does not apply to a `.js` destination, but when the site's protection policy is on the host the tool still reads that policy and
every protected dashboard it names, as read-only copies into a temporary folder on this PC that it deletes again, before it writes anything (it uses
`-Python` for this); if one of them cannot be read it stops with a `BLOCKED` message and nothing has been written: record it and stop.

Expected output (from the tool's code). The lines below are a **subset, in this order**: the tool prints more between them (the
repository validation, the SSH probe, the output of `ha core check`), and those are not listed. `Target      : Production - ...` (the tool pads each
label with spaces so that the colons line up);
`Running the dashboard preservation gate (read-only)...` followed by `not a dashboard destination: the dashboard preservation gate
does not apply`; `No existing remote file;
rollback will remove the new file if validation fails.`; `Uploading frontend/ecco-mode-shell/ecco-mode-shell.js ->
/config/www/ecco/ecco-mode-shell.<sha8>.js`; `Upload SHA256 verified: <the card's sha256>`; `Post-install SHA256 verified: <the same>`;
`Running Home Assistant configuration check...`; `Configuration check passed. Home Assistant was NOT restarted.`; then the block
`ECCO DEPLOYMENT PASSED` with `Restart     : no` and `Backup      : none (new file); ...`, and the reminder `RESOURCE NOT REGISTERED
ecco-mode-shell: no resource loads this card. This copy is NOT LIVE until a resource with URL /local/ecco/ecco-mode-shell.<sha8>.js
(JavaScript module) is added.` Nothing a dashboard loads has changed yet.

Then check the bytes Home Assistant serves, before anything is registered:

```powershell
cls
$PY = '<PY>'
Set-Location <checkout>
& $PY -I -B -X utf8 tools\ecco_deploy_preflight.py verify-served --plan dist\geek-u1\plan.json --base-url <HA URL>
```

Expected: one line `  PASS  served ecco-mode-shell.<sha8>.js: sha256 matches - <content type>; Cache-Control: <value>` and exit 0 (the content type and
the cache header are what Home Assistant sent: they are printed, not judged). It is one GET of the file a browser would fetch, with no sign-in. A
`FAIL` line exits 1: `sha256 DIFFERS`, or `GET /local/ecco/... - HTTP Error 404` (the file is not served under that name: compare the name with the
table above and with the host listing), or a connection or certificate error (Python does not trust the certificate of `<HA URL>`: the tool has no
option to skip that check and the runbook adds none; use an address whose certificate Python trusts, or stop and ask the owner). Any `FAIL` is a stop.

If the tool prints a rollback message, it removed its own new file and re-ran the configuration check; read the message to the
end, record it offline and stop. Do not retry without the owner.

### 5.4 Step 4: the owner adds the one resource; the read-back

The owner opens Settings, Dashboards, the three-dot menu, Resources (advanced mode must be on in the owner's profile; recalled, not verified: use
what the screen shows), adds a resource with the URL `/local/ecco/ecco-mode-shell.17410163.js` (the exact value of 5.3) and the type **JavaScript
module**, and saves. **One item, nothing
else.** No ECCO tool edits resources. A resource is **global**: from the moment it is saved, every dashboard page on every client
loads this module (section 1), although only the new dashboard places the card; the resource is new and its module loads nothing
else.

Then the coordinator reads the persisted list again and runs the existing read-back gate. The read-back must be less than 30 minutes
old when the gate runs (it checks the file time) and must be captured the same way as the baseline:

```powershell
cls
$H = '<production alias>'
$E = '<OFFLINE_EVIDENCE_DIR>\u1-baseline'
$PY = '<PY>'
Set-Location <checkout>
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
$OutputEncoding = [Console]::OutputEncoding
ssh $H "cat /config/.storage/lovelace_resources" | Out-File -Encoding utf8 "$E\resources-now.json"
& $PY -I -B -X utf8 tools\ecco_deploy_preflight.py verify-resource --plan dist\geek-u1\plan.json --resources "$E\resources-now.json" --before "$E\resources-before.json" --base-url <HA URL>
```

Expected: the check lines, then `RESOURCE VERIFIED ecco-mode-shell -> /local/ecco/ecco-mode-shell.<sha8>.js (id <8 hex>, persisted,
read back at <UTC>)` and `verify-resource PASSED: 1 card(s) verified; not checked: nothing`, exit 0. The gate checks that exactly
one resource loads the card, that its URL and type are the plan's, that the card had no resource before (so this is a new entry),
that **no other resource was added, removed or changed** since the baseline, that the bytes served at that URL hash to the plan's
sha256, and that the read-back is fresh. Report the resource as live only after this exit 0. Any other line (`NOT SWITCHED`, `NOT
VERIFIED`, `refused`) is a stop: the owner corrects or deletes the resource and the gate is run again; nothing proceeds.

The plan is hand-made because the tool lists its own cards in a constant that does not include this one. No safety tool is edited
and none is bypassed: the same checks run, on this one resource.

**What "exactly one resource added, none changed" rests on.** `resources-before.json` (step 1) and `resources-now.json` are both the raw persisted
list, captured the same way. The gate compares them by resource id: the card had no resource in the before list; the new list has exactly one resource
whose file name is `ecco-mode-shell.<anything>` (a second one, or a leftover, fails); that resource's URL (the whole string, so no `?v=`) and type
equal the plan's; every other resource has the same id, URL and type as before (none added, removed or edited); the new list's file time is at most 30
minutes old (`--max-age-minutes`; it is the modification time of the local file the capture wrote, that is, when it was captured); and, with
`--base-url`, the file served at that URL has the plan's sha256. If anyone changes a resource between step 1 and now, the gate fails and the baseline is
taken again, by the owner's decision.

**If the URL is wrong** (anything but the one URL of 5.3). Round 3 ran the real gate offline against each case below (the one request replaced by a
function). Every case exits 1 and ends with `verify-resource FAILED: ...; the switch is not verified and the install must not be reported as done`:

| What was saved | The verdict line | Why |
|---|---|---|
| the card's name without the content address, a typo in the eight characters, or `?v=` added | `RESOURCE NOT SWITCHED ecco-mode-shell: still <the saved URL>` | the URL is not the plan's |
| a name that does not start with `ecco-mode-shell` | `RESOURCE NOT SWITCHED ecco-mode-shell: no resource for this card is registered`, and a `FAIL` that names the added resource | the gate does not see it as this card's resource |
| the right URL, a type but module (for example `js`) | `RESOURCE NOT VERIFIED ... failed: the resource type is the plan's 'module'` | wrong type |
| a second resource for the card, or any other resource added, removed or edited | `RESOURCE NOT VERIFIED ...` and the `FAIL` line that names it | not exactly one, or something else changed |
| the right URL, but the file is not served or its bytes differ | `RESOURCE NOT VERIFIED ... failed: GET ...` or `sha256 DIFFERS from the plan` | step 3 is not finished |
| a read-back older than 30 minutes | `RESOURCE NOT VERIFIED ...` and `FAIL  the read-back is fresh` | capture the list again |

In Home Assistant itself, a resource with a wrong URL is a failed request on every page of every client, because the resource is global (recalled, not
verified: the browser logs the failed load of that address and nothing else happens), and the new dashboard would show "Custom element doesn't exist:
ecco-mode-shell" (section 10). The remedy is always the owner's: correct the URL, or delete the resource (section 7, item 2), capture the list again and
run the gate again. Nothing proceeds without `RESOURCE VERIFIED`.

**One look at the production Overview (owner, desktop browser, hard refresh with Ctrl+F5).** Because the resource is global, this
is the first page that loads the new module without using the card. The owner checks, and records yes or no:

1. the Overview renders as it did before (the same cards, nothing red, no new error card);
2. the browser console (F12) shows no new error that names the shell module or its resource (messages of other cards are noted,
   not judged);
3. if the Overview shows anything of the shell, or an error names it: **stop**, record the text, and the owner deletes the resource
   (section 7, item 2); do not go on to step 5.

Known console noise, not a defect of the card: a client with an old mobile web view (iOS Safari before 16.4 cannot read the regular
expression look-behind the card uses) logs a module syntax error on every dashboard page it opens. Only that module fails to load
there; the card is not usable on such a client, and the other resources are loaded one by one (unverified on a real host). A phone
or tablet that logs this is noted, not a stop; a desktop browser that logs it is a stop.

### 5.5 Step 5: the owner creates the dashboard

The owner opens Settings, Dashboards, Add dashboard, chooses a new dashboard from scratch, gives it a title (suggested: `ECCO Modes
(first look)`) and a URL (suggested: `ecco-modes-u1`; Home Assistant needs a hyphen), switches **Require admin** on, and creates it.
Then in that dashboard: Edit dashboard, the three-dot menu, Raw configuration editor, select all, paste the generated text, Save.
(The menu labels are those of the Home Assistant frontend the author has not seen on the production host: use what the screen shows;
**stop if the raw configuration editor is not offered for this dashboard**.) A brand-new dashboard may first show an automatically generated page, and
Home Assistant may ask the owner to "take control" before it offers the raw editor (recalled, not verified). That is acceptable **only** for this new
dashboard, with its own address in the address bar: never take control of, or open the raw editor of, the production Overview or any other dashboard
in this update. "Require admin" is a visibility setting, not a security boundary (section 1); step 6 reads the stored flag back.

To put the text on the clipboard without opening a 147 KB file by eye:

```powershell
cls
Get-Content -Raw -Encoding utf8 <checkout>\dist\geek-u1\dashboard-config.json | Set-Clipboard
```

The text is JSON (a subset of YAML, which the editor accepts), so there is no indentation or quoting to get wrong, and it holds the
catalogue inline: there is no file to include and no address in it.

**Two checks, every time, before anything is saved.** The paste replaces everything in the editor it lands in, and the raw editor
of another dashboard looks the same as the new one:

1. **before pasting**, the raw editor shows an empty or default new configuration (a title and at most an empty or placeholder
   view: a few lines), with no ECCO card in it and nothing near the length of the text about to be pasted;
2. **after pasting and before pressing Save**, the browser's address bar shows the path of the NEW dashboard (the URL chosen above,
   `ecco-modes-u1` if the suggestion was used) and the page header shows its title, and **not** the production Overview, the
   existing Intelligence dashboard or any other dashboard.

If either is not so: **stop, do not Save.** Close the editor without saving (nothing is stored until Save), then open the new
dashboard from Settings, Dashboards and start again. If a paste was already saved into the wrong dashboard, section 7 (a
mis-pasted dashboard) is the way back; step 6 would show it as a changed sha256 line of an existing `.storage/lovelace*` file.

### 5.6 Step 6: read-only after-checks

The coordinator, with the owner's authorisation, repeats the baseline reads (5.1) into `$E\...-after...` files and compares:

```powershell
cls
$H = '<production alias>'
$E = '<OFFLINE_EVIDENCE_DIR>\u1-baseline'
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
$OutputEncoding = [Console]::OutputEncoding
ssh $H "cd /config && sha256sum .storage/lovelace* ecco/dashboards/*.yaml" | Out-File -Encoding utf8 "$E\sha-after.txt"
ssh $H "cat /config/.storage/lovelace_resources" | Out-File -Encoding utf8 "$E\resources-after.json"
ssh $H "cat /config/.storage/lovelace_dashboards" | Out-File -Encoding utf8 "$E\dashboards-after.json"
ssh $H "ls -l /config/www/ecco/ | grep -v '^total'" | Out-File -Encoding utf8 "$E\www-ecco-after.txt"
ssh $H "ha core info" | Out-File -Encoding utf8 "$E\core-info-after.txt"
function Read-Sums($Path) {
    $h = @{}
    foreach ($line in Get-Content $Path) {
        $p = $line -split '\s+', 2
        if ($p.Count -eq 2) { $h[$p[1].Trim().TrimStart('*')] = $p[0] }
    }
    return $h
}
$b = Read-Sums "$E\sha-before.txt"
$a = Read-Sums "$E\sha-after.txt"
'changed : ' + ((@($b.Keys | Where-Object { $a.ContainsKey($_) -and $a[$_] -ne $b[$_] }) | Sort-Object) -join ', ')
'new     : ' + ((@($a.Keys | Where-Object { -not $b.ContainsKey($_) }) | Sort-Object) -join ', ')
'gone    : ' + ((@($b.Keys | Where-Object { -not $a.ContainsKey($_) }) | Sort-Object) -join ', ')
Compare-Object (Get-Content "$E\dashboards-before.json") (Get-Content "$E\dashboards-after.json")
Compare-Object (Get-Content "$E\www-ecco-before.txt") (Get-Content "$E\www-ecco-after.txt")
$ids = @((Get-Content -Raw -Encoding utf8 "$E\dashboards-before.json" | ConvertFrom-Json).data.items | ForEach-Object { $_.id })
'--- the new dashboard item (read back from the persisted list):'
(Get-Content -Raw -Encoding utf8 "$E\dashboards-after.json" | ConvertFrom-Json).data.items | Where-Object { $ids -notcontains $_.id } | Format-List id, url_path, title, require_admin, mode
```

The expected differences, and only these. **The targeting proof** is the `changed` / `new` / `gone` verdict, made from `sha-before.txt` and
`sha-after.txt`: `changed` is exactly `.storage/lovelace_dashboards` and `.storage/lovelace_resources`; `new` is exactly ONE file,
`.storage/lovelace.<dashboard id>` (the new dashboard's own configuration); `gone` is empty. So **every other `.storage/lovelace*` file and every
file under `ecco/dashboards/` (the production Overview and the existing Intelligence dashboard) has its baseline sha256** (a changed hash of any other
`.storage/lovelace*` file is a paste into the wrong dashboard: section 7, S1). In the dashboard list exactly one item is added, and the listing at the
end of the block shows it: its `id` (the `<dashboard id>` above), the `url_path` that was chosen, the title, **`require_admin` true** (stop if it is
not: the page would be visible to every user; the owner turns "Require admin" on, then this is read again) and the storage mode (field names recalled,
not verified: the read shows what is there); in `/config/www/ecco/`
exactly one new file (the `total` line is not in the listing, so the comparison shows exactly one line). The resource list differs
by exactly one added item (`verify-resource` already proved it in step 4; re-run it here with the fresh read-back if more than 30
minutes have passed: the plan and the `--before` file are the same). `core-info-after.txt` shows Home Assistant Core running and
the version of the baseline (`core-info-before.txt`; a newly offered update is noted, not a stop).

Now the stored configuration of the new dashboard, compared with the generated text. This proves the paste arrived exactly as
generated (the key order and the formatting do not matter; the content does). The file is **copied with `scp`**, not captured
through `ssh` and `Out-File`:

```powershell
cls
$H = '<production alias>'
$E = '<OFFLINE_EVIDENCE_DIR>\u1-baseline'
$PY = '<PY>'
Set-Location <checkout>
scp -q "${H}:/config/.storage/lovelace.<dashboard id>" "$E\stored-config.json"
if ($LASTEXITCODE -ne 0) { throw 'the copy of the stored dashboard failed' }
& $PY -I -B -X utf8 tools\geek_mode_dashboard_config.py --verify-storage "$E\stored-config.json"
```

Expected: `STORED CONFIGURATION EQUALS THE GENERATED ONE`, exit 0. `<dashboard id>` is the item's `id` in `dashboards-after.json`
(the new `.storage` file name is also the one new line of `sha-after.txt`). The tool reads the persisted file's `data.config` (or a
bare configuration) and refuses, exit 2, a file it cannot read as UTF-8 JSON (a UTF-16 file from a redirect is named as such); it
does not guess a different layout. It compares **parsed** JSON, so the stored file's raw UTF-8 middle dots and the generated text's
escaped dots (U+00B7 as a backslash-u escape) are equal, and a byte order mark or CRLF line ends do not matter. If it prints `DIFFERS`, it names the top-level
keys that differ and where the first difference is (keys and list indexes only, never card text).

**Why `scp` and not `ssh ... > file`:** Home Assistant writes `.storage` as raw UTF-8, and Windows PowerShell decodes `ssh`
output with the console's code page, so each of the two middle dots of the text fallback would arrive as two wrong characters and
the tool would print `DIFFERS` for a correct paste. That is a **false failure caused by the console code page**, not a defect of
the dashboard or the paste; when the whole difference is of that kind the tool says so (it still exits 1, and nothing is assumed).
The remedy is the `scp` copy above, not a second paste. If `scp` is not available, capture with the two encoding lines of the
other blocks (UTF-8, no byte order mark) before `ssh $H "cat /config/.storage/lovelace.<dashboard id>" | Out-File -Encoding utf8`.

Home Assistant's log: read the same lines as at the baseline and show only the lines that are new (the tool prints only; it
changes nothing):

```powershell
cls
$H = '<production alias>'
$E = '<OFFLINE_EVIDENCE_DIR>\u1-baseline'
Set-Location <checkout>
foreach ($p in 'lovelace', 'frontend', 'ecco-mode-shell') {
    .\tools\ha-logs.ps1 -SshHost $H -Lines 400 -Pattern $p 6>&1 | Out-File -Encoding utf8 "$E\log-$p-after.txt"
    "--- new lines for '$p' (in the after read only):"
    Compare-Object (Get-Content "$E\log-$p-before.txt") (Get-Content "$E\log-$p-after.txt") | Where-Object { $_.SideIndicator -eq '=>' } | ForEach-Object { $_.InputObject }
}
```

Read each new line. A new line that names the new dashboard, the resource or the card is a stop; an unrelated new line is noted.
(A line that merely scrolled in because the log is a rolling tail is unrelated.) **The log shows server-side errors only; a browser
error never reaches it** (step 7 reads the browser's console).

Finally re-read the states: run the state read of 5.1 (block 3) with `$Tag = 'after'`, then compare it with the baseline:

```powershell
cls
$E = '<OFFLINE_EVIDENCE_DIR>\u1-baseline'
$From = 'before'    # 'before' ...
$To = 'after'       # ... against 'after' in step 6, against 'look' in step 8
$a = Get-Content -Raw -Encoding utf8 "$E\states-$From.json" | ConvertFrom-Json
$b = Get-Content -Raw -Encoding utf8 "$E\states-$To.json" | ConvertFrom-Json
foreach ($x in $a) {
    $y = $b | Where-Object { $_.entity_id -eq $x.entity_id } | Select-Object -First 1
    $same = { param($u, $v) if ($u -eq $v) { 'same     ' } else { 'DIFFERENT' } }
    '{0}  state {1}  last_changed {2}  mode {3}  applies_nothing {4}  absent {5}' -f $x.entity_id, (& $same $x.state $y.state),
        (& $same $x.last_changed $y.last_changed), (& $same $x.attributes.mode $y.attributes.mode),
        (& $same $x.attributes.applies_nothing $y.attributes.applies_nothing), (& $same $x.absent $y.absent)
}
```

Read it by role. The Intelligence status entity: `mode` and `applies_nothing` are `same`; its `state` and `last_changed` may differ
(it publishes on its own schedule: compare with the cadence at the baseline) and it must still be publishing. The pause helper and
every control entity of the earlier installs: `state` and `last_changed` are `same`; a `DIFFERENT` there is a stop.

### 5.7 Step 7: the owner's look (ONE look)

Desktop browser, a fresh page load (Ctrl+F5, so the new resource is fetched), the new dashboard.

**First, Production Mode only.** In this look the owner checks, and records yes or no with a screenshot kept offline:

1. the shell loads and starts in Production (the switch shows Production selected), with no red or yellow error card;
2. the existing ECCO Intelligence card and the watchdog and status card are shown and read as they do on the existing Intelligence
   dashboard (open that dashboard in a second tab and compare: same figures, same status);
3. the **alert strip** tells the same story as that card: nothing contradictory (an all-clear card and a critical strip line, or the
   reverse, is a stop); the strip is never blank (a blank strip is a defect: stop);
4. the one plain Production sentence (below the two cards that both modes show, above the pause tile) is present, and so is the fixed note under
   the switch ("This switch only changes what is shown. It never changes what ECCO does.");
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

With the owner's authorisation, immediately after the look and before anything else changes, two read-only reads of the entities in
`u1-entities.txt` (the control entities of the baseline: the pause helper, the write enables, the arm and schedule switches, the
dongle's manual write counter, the TOU edit helper; and the Intelligence entities).

**(a) The states.** Run the state read of 5.1 (block 3) with `$Tag = 'look'`, then the comparison of 5.6 with `$From = 'before'`
and `$To = 'look'`.

**(b) The state history of the same entities, from the baseline to now.** The repository has no tool that reads the Home Assistant
logbook; the read below is the history route that the repository's own evidence documents use (`tools/fbd1_soak/README.md`: `GET
/api/history/period/<start>` with `end_time`, `filter_entity_id`, `minimal_response` and `no_attributes`), made through the same
Supervisor route as the state read (read-only; the token stays on the host). It starts at the baseline's time (`time-before.txt`,
which is earlier than step 3, so the window is a little wider than needed):

```powershell
cls
$H = '<production alias>'
$E = '<OFFLINE_EVIDENCE_DIR>\u1-baseline'
$PY = '<PY>'
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
$OutputEncoding = [Console]::OutputEncoding
$ids = @(Get-Content "$E\u1-entities.txt" | ForEach-Object { $_.Trim() } | Where-Object { $_ -ne '' })
if ($ids.Count -eq 0 -or @($ids | Where-Object { $_ -notmatch '^[a-z0-9_]+\.[a-z0-9_]+$' }).Count -gt 0) { throw 'u1-entities.txt is empty or holds a line that is not an entity id' }
$fmt = "yyyy-MM-dd'T'HH:mm:ss'Z'"
$inv = [Globalization.CultureInfo]::InvariantCulture
$start = [DateTimeOffset]::Parse((Get-Content "$E\time-before.txt" -Raw).Trim(), $inv).UtcDateTime.ToString($fmt, $inv)
$end = [DateTime]::UtcNow.ToString($fmt, $inv)
$remote = 'if [ -z "$SUPERVISOR_TOKEN" ]; then echo __ECCO_NO_SUPERVISOR_TOKEN__; exit 42; fi; curl -fsS -H "Authorization: Bearer $SUPERVISOR_TOKEN" "http://supervisor/core/api/history/period/' + $start + '?end_time=' + $end + '&filter_entity_id=' + ($ids -join ',') + '&minimal_response&no_attributes"'
$cmd = 'printf %s ' + [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($remote)) + ' | base64 -d | sh'
$raw = (& ssh -o BatchMode=yes $H $cmd) -join "`n"
if ($LASTEXITCODE -ne 0) { throw "the history read failed (ssh exit $LASTEXITCODE)" }
$raw | Out-File -Encoding utf8 "$E\history-look.json"
& $PY -I -B -X utf8 -c "import json, sys; d = json.load(open(sys.argv[1], encoding='utf-8-sig')); d = d['data'] if isinstance(d, dict) and 'data' in d else d; print(len(d), 'series'); [print(len(s), s[0].get('entity_id', '?'), s[-1].get('last_changed', '?')) for s in d if s]" "$E\history-look.json"
```

It prints the number of series and, per entity, the number of rows and the `last_changed` of the last row. Home Assistant lists the
state at the start of the window as the first row, so **one row means no change in the window**. (The Logbook page of the Home
Assistant UI for the same entities and period is the equivalent manual look and may be used as a cross-check.)

Expected: every control entity has one row, its state and `last_changed` are `same` in (a), the manual write counter is
unchanged, and the Intelligence entities show only the rows their own schedule explains (more rows are expected there). A control
entity with a second row, or a `DIFFERENT` in (a), is a stop. What this does **not** prove, and what carries the rest: a service
call that changes no state leaves no durable record. The case against a write rests on three things together: the card's source has no
service call (pinned in `tools/tests/test_ecco_mode_shell_card.py`: no `call_service`, `callService`, `fetch`, websocket, storage,
dynamic code, one timer, two window listeners, three click-only actions, and `hass` read for `states`, `locale` and `themes` only),
the Node suite's trap on every `hass` function (`frontend/ecco-mode-shell/test/generated-config.test.mjs`), and the owner's
statement that nothing was tapped.

### 5.9 Step 9: close-out

- a status update in the owner's project record, by that record's own procedure: what ran, when, the hashes, the outcome of each
  step, the owner's decisions. **Never edit the master status document from a working session.**
- the offline evidence in `<OFFLINE_EVIDENCE_DIR>`: the baseline and after files, the `verify-served` and `verify-resource` output, the
  deploy output with its backup folder name, the screenshots, the console text, the times;
- a post to the coordination channel, **counts only** (no value, no entity id, no address), and only on the owner's go; a push likewise.

## 6. Stop conditions (any step)

Stop, change nothing more, record the state, and ask the owner, when: a tool prints anything but the expected line; a hash differs
from its pin; a read finds something of this update already present; the baseline shows Core not running or the Intelligence
status not what it was; the resource gate does not exit 0; the dashboard list or the resource list differs by more than the one item
the step added; any file under `ecco/dashboards/` changes, or any `.storage/lovelace*` file other than the new dashboard's and the
two lists; a copy of the baseline that is not byte-exact; either pre-save check of 5.5 fails; a control entity changes; the
production Overview shows an error naming the shell; the look shows a strip that contradicts the existing card, a blank strip, a
freeze, or an error naming the shell; a step would need a restart. Never retry a live write without the owner. Never approve, work
around or weaken a permission prompt or a safety gate.

## 7. Rollback, in order

Each artefact is rolled back separately, newest first (the dashboard A3, then the resource A2, then the file A1), and only by the owner's action
or with the owner's authorisation. Nothing is restarted. **A3 and A2 need only the owner's own action in the Home Assistant UI** (two deletions: no
tool, no host command, no restart); A1 may simply stay (item 3); the coordinator's part is read-only (item 4). The tool's own automatic rollback
(step 3) already removes the new file and re-runs the configuration check if the copy fails.

**Two special cases come first, before the order below.**

**S1. A paste went into the wrong dashboard** (the owner noticed it at the pre-save checks of 5.5 too late, or step 6 shows a
changed sha256 line of an existing `.storage/lovelace*` file). Stop; touch nothing else. The baseline holds a byte-exact copy of
every such file in `$E\lovelace-before\`. The owner opens the damaged dashboard (Edit dashboard, Raw configuration editor), selects
all, pastes the saved content and saves. The saved content is the `data.config` of the copy; this puts it on the clipboard as text
(`<stored file name>` is the damaged dashboard's file name in `lovelace-before\`, for example the one whose sha256 line changed):

```powershell
cls
$E = '<OFFLINE_EVIDENCE_DIR>\u1-baseline'
$PY = '<PY>'
& $PY -I -B -X utf8 -c "import json, sys; d = json.load(open(sys.argv[1], encoding='utf-8-sig')); print(json.dumps(d['data']['config'], indent=2))" "$E\lovelace-before\<stored file name>" | Set-Clipboard
```

Then the coordinator reads the stored file again and compares it with the baseline: first the sha256 line (the `sha-before.txt`
line of that file; an equal hash means restored exactly), and, because Home Assistant may write the same content in its own layout
and so give a different hash, the content:

```powershell
cls
$H = '<production alias>'
$E = '<OFFLINE_EVIDENCE_DIR>\u1-baseline'
$PY = '<PY>'
ssh $H "cd /config && sha256sum .storage/<stored file name>"
Get-Content "$E\sha-before.txt" | Select-String -SimpleMatch '<stored file name>'
scp -q "${H}:/config/.storage/<stored file name>" "$E\lovelace-rollback.json"
& $PY -I -B -X utf8 -c "import json, sys; a, b = (json.load(open(p, encoding='utf-8-sig'))['data']['config'] for p in sys.argv[1:3]); print('SAME CONTENT' if a == b else 'DIFFERENT')" "$E\lovelace-before\<stored file name>" "$E\lovelace-rollback.json"
```

Restored means the two sha256 values are equal, or the content prints `SAME CONTENT`. If neither holds, or anything is unclear:
**restore the protected backup of step 2** (the owner's action in the Home Assistant UI; read 5.2 first: a restore is a heavy last resort that
restarts Home Assistant and puts everything back to its state at the time of the backup, so it is the owner's decision and never the first rollback);
do not guess. Then continue with the order below for the new dashboard.

**S2. The pause tile was tapped by accident** (Production shows it; it toggles the pause helper, the one write the existing tile has
always made). One more tap undoes it, or the owner sets the helper back to its baseline state (`states-before.json`). Then record
the time, both changes and the baseline state offline, and re-run step 8: its history will show the two changes made in the owner's
session, which are explained, not hidden. Nothing else is touched.

1. **A3, the dashboard.** The owner deletes it (Settings, Dashboards, the new dashboard, Delete). The dashboard list returns to
   `dashboards-before.json`; the persisted configuration file of that dashboard is gone with it (recalled, not verified: item 4 shows whether it
   is; a leftover file that no list names is inert: record it, and never edit `.storage` by hand).
2. **A2, the resource.** The owner deletes the one resource (Settings, Dashboards, Resources, the item, Delete), then the coordinator
   re-reads the persisted list and compares it with the saved baseline copy:

   ```powershell
   cls
   $H = '<production alias>'
   $E = '<OFFLINE_EVIDENCE_DIR>\u1-baseline'
   $ErrorActionPreference = 'Stop'
   [Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
   $OutputEncoding = [Console]::OutputEncoding
   ssh $H "cat /config/.storage/lovelace_resources" | Out-File -Encoding utf8 "$E\resources-after-rollback.json"
   Compare-Object (Get-Content "$E\resources-before.json") (Get-Content "$E\resources-after-rollback.json")
   ```

   No output means the lines are equal (if a line differs, the parsed comparison of item 4 says whether the content is the same). The shell
   element then no longer exists in any page after a hard refresh.
3. **A1, the card file.** It may stay: with no resource pointing at it, a file under `/config/www/ecco/` is never loaded (it is
   served on request only). If the owner wants it gone, it is **moved by hand, never deleted**, into a new backup folder, with the owner's
   authorisation. `deploy-ha.ps1 -Action Retire` does not cover it (that action moves only the exact Intelligence files its code lists).
   A plain move (one host command, with `$H` set to the production alias; no `cp -p`, because Home Assistant caches YAML dashboards by file time and this file is not one):
   `ssh $H "mkdir -p /config/ecco-backups/<stamp>-u1-rollback && mv /config/www/ecco/ecco-mode-shell.<sha8>.js /config/ecco-backups/<stamp>-u1-rollback/"`.
4. **Re-check, proving each rollback against the baseline.** The coordinator reads the same lists again into NEW files (the `-rollback` files, so the
   evidence of step 6 is not overwritten) and compares them with the baseline:

   ```powershell
   cls
   $H = '<production alias>'
   $E = '<OFFLINE_EVIDENCE_DIR>\u1-baseline'
   $PY = '<PY>'
   $ErrorActionPreference = 'Stop'
   [Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
   $OutputEncoding = [Console]::OutputEncoding
   ssh $H "cd /config && sha256sum .storage/lovelace* ecco/dashboards/*.yaml" | Out-File -Encoding utf8 "$E\sha-rollback.txt"
   ssh $H "cat /config/.storage/lovelace_resources" | Out-File -Encoding utf8 "$E\resources-rollback.json"
   ssh $H "cat /config/.storage/lovelace_dashboards" | Out-File -Encoding utf8 "$E\dashboards-rollback.json"
   ssh $H "ls -l /config/www/ecco/ | grep -v '^total'" | Out-File -Encoding utf8 "$E\www-ecco-rollback.txt"
   '--- sha256 lines that differ from the baseline (none expected after a complete rollback):'
   Compare-Object (Get-Content "$E\sha-before.txt") (Get-Content "$E\sha-rollback.txt")
   '--- the two lists compared as parsed items (SAME ITEMS expected):'
   foreach ($n in 'resources', 'dashboards') {
       & $PY -I -B -X utf8 -c "import json, sys; a, b = (json.load(open(p, encoding='utf-8-sig'))['data']['items'] for p in sys.argv[1:3]); print(sys.argv[3], 'SAME ITEMS' if a == b else 'DIFFERENT')" "$E\$n-before.json" "$E\$n-rollback.json" $n
   }
   '--- /config/www/ecco/ against the baseline (none expected, or only the file left in place):'
   Compare-Object (Get-Content "$E\www-ecco-before.txt") (Get-Content "$E\www-ecco-rollback.txt")
   ```

   What each result proves. **A3** is undone when the dashboard list is `SAME ITEMS` and no `.storage/lovelace.<dashboard id>` line is left (it would
   show as a `=>` line in the first comparison). **A2** is undone when the resource list is `SAME ITEMS` (the comparison of item 2 is the same proof,
   line for line). **A1** is undone, or left inert on purpose, when the `/config/www/ecco/` comparison is empty (the file was moved) or shows exactly one
   `=>` line for the card file (left in place). The production Overview, the existing Intelligence dashboard and every other dashboard file (every
   `.storage/lovelace*` file other than the removed one, too) have their baseline sha256: the first comparison shows no line for them. A single line
   that differs for `lovelace_resources` or `lovelace_dashboards` while its `SAME ITEMS` line is printed is Home Assistant's own formatting of the same
   content: record it, it is not a stop. The same holds for a dashboard file that was put back after S1: its line may differ while the `SAME CONTENT`
   line of S1 was printed. Anything else: stop and ask the owner.

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
- **The resource is global.** After step 4 every dashboard page on every client loads the 155 KB shell module: the production
  Overview, non-admin users, and wall and phone clients included (section 1). The look at the production Overview (5.4) is the one
  check made; nothing is known about the wall or phone clients before the owner looks at one.
- **Known console noise:** an old mobile web view (iOS Safari before 16.4, which cannot read the regular-expression look-behind the
  card uses) logs a module syntax error on every dashboard page it opens, once the resource exists. It is noise, not a defect of
  the Overview; the card does not work on such a client, and the effect on that client's other resources is unverified.
- Intelligence is NOT ACCEPTED overall. The look says nothing about forecast accuracy, the solar forecast, R9 or Stage 3.
- **Admin-only is a visibility setting, not a security boundary** (section 1): it keeps the page out of a non-admin user's sidebar; it does not stop a
  non-admin who calls Home Assistant's own API, and it does not limit what the global resource (A2) loads.
- **Recalled from Home Assistant's behaviour, not verified on this host** (each is marked where it is used): the menu labels and the order of the
  dashboard and resource screens; that a new dashboard may ask the owner to take control before the raw editor is offered; that "Require admin" hides
  the panel from non-admin users; the field names of the stored lists (`id`, `url`, `type`, `url_path`, `require_admin`) and the dashboard's storage
  file name (`lovelace.<dashboard id>`, holding `data.config`); that deleting the dashboard removes that file; how a resource with a wrong URL shows
  in the browser; that restoring a backup restarts Home Assistant.
- The tools of steps 3 and 4 were read, run with `--help` and run offline (the real `verify-served` and `verify-resource` against the hand-made plan,
  the one request replaced by a function; section 13, round 3); the PowerShell blocks parse and ran against stand-ins. None of it ran against the
  real host.
- Phone and tablet layouts are not part of U1; a desktop look is (the module still loads on a phone or tablet, see above).
- The state read, the history read and the log reads of 5.1, 5.6 and 5.8 are written from the repository's own tools and from the
  Home Assistant interfaces they use, and have not been run on the production host.

## 10. What a first-look failure looks like, and what it means

| What the owner sees | What it means | What to do |
|---|---|---|
| a red card "Custom element doesn't exist: ecco-mode-shell" | the resource is not loaded: wrong URL, type not module, a cached page, or the file not served | hard refresh; check the resource's URL and type; run `verify-resource`; stop if it still shows |
| the shell shows but a strip line says the catalogue is not valid | the pasted configuration is damaged (truncated or altered) | run `--verify-storage` on the `scp` copy (5.6); repaste only if it truly differs (not by the console code page); stop if it differs again |
| a strip line says the card configuration has a problem | a list in the pasted text is not a list | the same: compare with `--verify-storage` |
| a child card shows "Card could not be shown" or Home Assistant's own error card for a child | the Intelligence card's resource is not loaded, or a core card could not be built | check the baseline's count of the Intelligence resource; note the message |
| a blank alert strip | a defect: the strip must never be blank | **stop**, screenshot, do not open Geek Mode |
| the strip and the existing card contradict each other | a defect or a stale read | **stop**, record both, do not fix at the look |
| every row reads "Unverified" or "cannot tell the age" | the browser's clock is more than five minutes ahead of Home Assistant's (a time in the future is not trusted) | correct the PC clock, reload; not a card defect |
| every row reads "Not measured" or "Not present" | the Intelligence entities are not published (the integration is off or unavailable), or the ids differ from the catalogue | compare with the baseline status; stop if the baseline had them |
| the page freezes or the tab is slow | real performance is unmeasured | close the tab, record the time and the browser; stop |
| a console error naming the shell | a defect on the real host | record the text; stop |
| a console error naming the shell on the production Overview or another dashboard, or the Overview not rendering as before | the resource is global: that page loaded the module too, and something in it failed | stop; record the text and the page; the owner deletes the resource (section 7, item 2); on a phone with an old web view this is the known noise of section 9 and is only noted |
| the pause tile is hidden in Production | a defect of the pass-through | stop |
| the pause tile is visible in Geek | a defect (Geek hides it) | stop |
| the pause tile was tapped by accident | the toggle of the pause helper, a write the existing tile has always made | one more tap, or set the helper back to its baseline state; record the time and both changes; re-run step 8 (section 7, S2) |
| the text of the pasted dashboard was saved into a different dashboard | the pre-save checks of 5.5 were missed | stop; section 7, S1: paste the saved content back and compare, else restore the protected backup |
| `--verify-storage` prints `DIFFERS` and says the console code page explains it | the stored file was captured through `ssh` and `Out-File` (a false failure of the capture) | copy the file with `scp` (5.6) and run it again; not a second paste |

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
| D-U1-2 | RG-F3: the voice-assistant "expose new entities" settings (Assist, Google Assistant), off or waived for U1 | U1 creates no entity |
| D-U1-3 | the order of the release bookkeeping against R9, Stage 3, grid-loss and F5 | section 11 |
| D-U1-4 | when to push and open the draft pull request, and when the owner's M2 scan runs | each is its own go |
| D-U1-5 | the title and URL of the new dashboard, and whether it shows in the sidebar | suggestions in 5.5 |
| D-U1-6 | whether the Geek look follows the Production look in the same session | H5: only after the owner says go |

## 13. Evidence: the offline verification on the exact tip

Verified on 20 Nov 2026, offline, serially (one heavy process at a time; Node only through a heap-capped, memory-guarded runner with
`--test-concurrency=2`; the mutation run last and alone), with a Python 3.12 interpreter (`-I -B -X utf8`, and
`PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1` for the suites the runner starts). Nothing was pushed, merged, installed, registered or
deployed, and no live system was contacted.

**Three rounds** (round 3 follows the pinned artefacts). Round 1 is the first verification: the commit `9586377b1dd5` was extracted with `git archive` into a clean folder
and verified there (its table is kept below as "round 1"). An independent review of that runbook found eight points (F1 to F8);
they are fixed in four new commits on the same branch: `66009ef` (the generator's `--verify-storage` and its suite), `748e68a`
(the card's pin suite), `a4fa2d0` (a comment kept ASCII) and `f188a5a` (this runbook). Round 2 was run in a clean clone
(`git clone --no-hardlinks`, no line-ending conversion) of `f188a5a`; the commit that holds this section differs from `f188a5a`
**only in this document**, so every number of round 2 holds for it too. Against the base of the review, `de783b4`, only four files
differ: this runbook, the generator and its two suites. The card, the catalogue, the example and every protected file are
byte-identical (sha256 below, checked at both ends); no manifest, scope chain, preflight or deploy tool was touched.

**The pinned artefacts (the same at every commit of all three rounds):**

| Artefact | Size | sha256 |
|---|---|---|
| the card, `frontend/ecco-mode-shell/ecco-mode-shell.js` (git LF) | 155,843 bytes | `17410163c016578f73428900087dc714f89336bbc55cc77ec5cbfc2e240d5775` |
| the catalogue, `.../catalogue/intelligence.catalogue.json` | 93,873 bytes | `0614de5e21426e46bcdb2b9a1ea2e50a461191a6046167d419d8331cfb5b6316` |
| the example, `.../examples/intelligence-modes.yaml` | 6,852 bytes | `c891e8fbf22d95eb9cf9a2e166629af84fdaeddfdc1532544aaf5b0308fa035c` |
| the generated dashboard configuration (`--out`) | 147,178 bytes | `4abf3b1e8eca72a6a1bebb0a22eaa535ba5bcf705ab8e9ba745059bfdbd82167` |
| the resource plan (`--resource-plan`) | 483 bytes | `8c216cfef4804c04cfd1f2e5614196d5679f227e0680010e5fc9e6dadf3d7c8f` |
| the destination file name | | `ecco-mode-shell.17410163.js` (so `<sha8>` is `17410163`) |

**Round 3** (20 Nov 2026: the owner's directive to make U1 the first deployment candidate). Docs and one new suite only. The commits on top of
`5b8f29d` are `dc63e2d` (the runbook corrections), `db96c46` (one sentence of them), `4e6fda1` (the GO checklist
`docs/product-ui/GEEK_MODE_U1_GO_CHECKLIST.md` and its suite `tools/tests/test_geek_mode_checklist.py`), `80f22f9` (the checklist's Stop column)
and the commit that holds this section, which differs from `80f22f9` **only in this document**. The five pinned hashes were recomputed before
the first edit and again at the end, and are unchanged (table above); the card, the catalogue, the example, the generator and every pin and protected
assertion are untouched. What was done:

1. **A command-truth audit.** Every command and tool call this runbook asks a person to run (19 PowerShell blocks and the inline forms) was set
   against the real definition of the tool (argument names, required arguments, defaults, exit codes, the lines it prints), the Python tools were run
   with `--help`, and `verify-served` and `verify-resource` were run in-process against the hand-made plan with their one request replaced by a function
   (3 and 16 cases: the right switch passes with exit 0; every wrong URL, type, count, change, byte or age fails with exit 1; an unreadable list is
   refused with exit 2). Eleven mismatches or gaps were fixed (5.0, 5.1, 5.3, 5.4, 5.7, section 7).
2. **The five checks of the directive** (the exact module resource, the admin-only setup, the backup, the rollback, the correct-dashboard targeting)
   were each read against the text and corrected where it was thin: the exact names (5.3), what the gate rests on and the wrong-URL table (5.4), what
   admin-only is and is not (section 1), what restoring a backup does (5.2), the targeting verdict (5.6), and the rollback proofs (section 7).
3. **A preservation audit** (section 1.1): the cards Production shows are deep-equal to the existing Intelligence dashboard's; the card source has no
   service call, request, websocket, storage or dynamic code (a word-bounded search); no remote command of this runbook writes except the optional move
   of the card file in section 7.
4. **The PowerShell blocks.** All 19 blocks of this runbook and the 2 of the checklist parse (the Windows PowerShell 5.1 parser). Fourteen of the 19
   ran against stand-ins (seventeen runs: `ssh` and `scp` replaced by functions over a scratch folder, the real generator, the clipboard stubbed); the
   other five are the checkout line, the deploy line, the two preflight calls (those tools ran offline as in item 1) and the clipboard copy of the
   147 KB text. The new verdict and rollback blocks also ran against a paste into the wrong dashboard, a dashboard that is not admin-only, a list that
   Home Assistant formats differently and an incomplete rollback, and print what the text says.
5. **The checklist and its suite.** The suite has 82 checks and 33 in-memory mutants, all killed. It was shown to fail first (a checklist that does not
   exist, and one with a wrong card hash: exit 1) and then to pass on the real checklist (exit 0). Its first run of the mutants exposed two weak spots in
   the suite itself (an address followed by a full stop was not seen; one mutant changed prose, not the command): both fixed and re-run.

Not run, said plainly: GitHub CI (nothing is pushed), the owner's M2 private-pattern scan (the owner's go only), the other CI roots, the other twelve
Node suites, the 518-mutant run and the headless strip check (the card, the catalogue, the example and the generator's output are byte-identical to
rounds 1 and 2, so nothing they test changed), and anything on a live system.

**Round 3 results** (the worktree of the branch; Python: `<PY> -I -B -X utf8`; serially, one process at a time):

| What | Command | rc | Count |
|---|---|---|---|
| repository validator | `tools/validate_repo.py` | 0 | PASSED (yaml 52, python 393, json 81, text 652) |
| CI root `tools/tests`, every suite, serially | `tools/run_offline_tests.py --root tools/tests --parallel 1` | 0 | 24/24 passed (230 s); round 2: 23/23, the new suite is the 24th |
| the pin suite | `tools/tests/test_ecco_mode_shell_card.py` | 0 | 107 PASS, 0 FAIL, 0 SKIP (unchanged) |
| the generator suite | `tools/tests/test_geek_mode_dashboard_config.py` | 0 | 104 PASS, 0 FAIL (unchanged) |
| the new consistency suite | `tools/tests/test_geek_mode_checklist.py` | 0 | 82 PASS, 0 FAIL; 33 mutants (28 of the checklist, 5 of the runbook), all killed |
| neighbours | `test_geek_mode_example.py`; `test_intelligence_card.py`; `test_geek_mode_privacy.py`; `test_geek_mode_catalogue.py`; `test_geek_mode_coverage.py`; `test_geek_mode_fixtures.py`; `test_geek_mode_ledger.py` | 0 each | 35; 81; 195; 134; 219; 102; 68 PASS, 0 FAIL |
| privacy suite (without the owner's pattern file) | `tools/tests/test_public_privacy.py` | 0 | 25 PASS, 1 SKIP (the owner's private pattern file) |
| generators | `tools/geek_mode_dashboard_config.py --check`; `tools/geek_mode_coverage.py --check`; `tools/gen_geek_fixtures.py --check` | 0; 0; 0 | `OK: 147178 bytes, sha256 4abf3b1e...` (unchanged); no drift; no drift |
| the Node suite that runs the generator (local, guarded) | `node --test --test-concurrency=2 test/generated-config.test.mjs` | 0 | 5 of 5 pass |
| PowerShell blocks | the Windows PowerShell 5.1 parser over every fenced block | 0 | 19 of the runbook and 2 of the checklist parse; 14 of the runbook's ran against stand-ins |

**Round 2 results** (a clean clone of `f188a5a`; Python: `<PY> -I -B -X utf8`):

| What | Command | rc | Count |
|---|---|---|---|
| repository validator | `tools/validate_repo.py` | 0 | PASSED (yaml 52, python 392, json 81, text 650) |
| CI root `tools/tests`, every suite, serially | `tools/run_offline_tests.py --root tools/tests --parallel 1` | 0 | 23/23 passed (219 s) |
| the pin suite | `tools/tests/test_ecco_mode_shell_card.py` | 0 | 107 PASS, 0 FAIL, 0 SKIP (round 1: 85). New: the redaction vocabulary pinned (6 word lists, 23 value-rule reasons), the member-access rules, 16 rule mutants run with the byte pin off, all caught; the rules find nothing on the unchanged card. Without git on the PATH the one git check prints SKIP and is counted apart: 106 PASS, 1 SKIP, rc 0 |
| the generator suite | `tools/tests/test_geek_mode_dashboard_config.py` | 0 | 104 PASS, 0 FAIL (round 1: 81). New: six round-trip read-backs (raw UTF-8, escaped, BOM, BOM with CRLF, bare, integers for floats) EQUAL; a changed card and a changed title DIFFER and name the key and path, never card text; console-code-page damage is a DIFFERENCE with its cause named; UTF-16 refused; a boolean is not a number; 4 in-memory mutants of the comparison, 4 of 4 killed. The new checks were run first on the unchanged generator: 8 FAIL |
| neighbours | `tools/tests/test_geek_mode_example.py`; `tools/tests/test_intelligence_card.py` | 0; 0 | 35 PASS (its tripwire untouched and passing); 81 PASS |
| privacy suite (without the owner's pattern file) | `tools/tests/test_public_privacy.py` | 0 | 25 PASS, 1 SKIP (the owner's private pattern file: the M2 scan is the owner's own step and was not run) |
| generators | `tools/geek_mode_dashboard_config.py --check`; `tools/geek_mode_coverage.py --check`; `tools/gen_geek_fixtures.py --check` | 0; 0; 0 | `OK: 147178 bytes, sha256 4abf3b1e...` (unchanged); no drift; no drift |
| the Node suite that runs the generator (local, guarded) | `node --test --test-concurrency=2 test/generated-config.test.mjs` | 0 | 5 of 5 pass (the generator's output is unchanged byte for byte; no other Node suite is affected, none was re-run) |
| the runbook's PowerShell blocks (this PC, stand-ins for `ssh` and `scp`, no network) | the 18 blocks of sections 5 and 7 | 0 | all 18 parse; the baseline, entity list, state read, log, after, stored-configuration, state comparison and history blocks run against stand-ins and print what the text says; the two Python one-liners of section 7 run on sample files |

**Not re-run in round 2, said plainly:** the other CI roots (`intelligence/tests`, `ecco_core/tests`, `health/tests`, `influxdb`,
`custom_components/ecco_intelligence/tests`, `home-assistant/tests`, `registry/tests`), the other twelve Node suites, the 518-mutant
run, the headless strip check and the HA bundle builder: nothing they test changed (the card, the catalogue, the example and the
generator's output are byte-identical to round 1, and no other file of the repository changed), so the round 1 results below stand.
The two known registry failures (a native C++ compiler this PC lacks) are as in round 1.

**Round 1 results.** "archive" is the clean `git archive` (no `.git`); "clone" is a clean clone of the same commit made without
line-ending conversion, used only for the suites that call `git ls-files` or read history (they fail in an archive for want of
`.git`, which says nothing about the code). The two rows for the pin suite and the generator suite (85 and 81 checks) are
superseded by round 2 (107 and 104).

| What | Command (Python: `<PY> -I -B -X utf8`) | rc | Count |
|---|---|---|---|
| repository validator | `tools/validate_repo.py` | 0 | PASSED (yaml 52, python 392, json 81, text 650) |
| workflow policy; write-surface analysis | `tools/check_workflows.py --require-sha-pins`; `tools/analyze_write_surface.py` | 0; 0 | 1 workflow, 0 problems; fails closed, none |
| HA bundle builder (CI job `ha-bundle`) | `tools/build_ha_bundle.py` | 0 (clone); 2 (archive: it refuses untracked sources) | built (REVIEW ONLY) |
| CI root `tools/tests` | `tools/run_offline_tests.py --root tools/tests --parallel 1` | 1 in the archive, then 0 for the 5 failing suites in the clone | 18/23 in the archive; the other 5 (deploy preflight, site render, firmware assembly, firmware equivalence, public privacy) pass in the clone: 23/23 |
| CI root `intelligence/tests` | the same, `--root intelligence/tests` | 0 | 33/33 |
| CI root `ecco_core/tests`; `health/tests`; `influxdb` | the same | 0; 0; 0 | 6/6; 2/2; 2/2 |
| CI root `custom_components/ecco_intelligence/tests` | the same | 0 | 16/16 |
| CI root `home-assistant/tests` | the same | 1 in the archive, then 0 in the clone | 16/18; the other 2 (they pin git-tracked files) pass in the clone: 18/18 |
| CI root `registry/tests` | the same, 7200 s per suite | 1 in the archive | 69/78 in the archive; 7 more pass in the clone; **2 fail, known and not new**: `test_rtc_policy.py` and `test_fallback_durable_host_compile.py` need a native C++ compiler this PC lacks (they fail identically on the branch base `c6e5a58`): 76/78 |
| the new pin suite | `tools/tests/test_ecco_mode_shell_card.py` | 0 | 85 checks pass, among them 39 card mutants (and one comment-letter case that only the byte pin catches), 9 catalogue and 5 configuration mutants, each caught by its own rule |
| the new generator suite | `tools/tests/test_geek_mode_dashboard_config.py` | 0 | 81 checks pass (30 mutants; the plan read by the real `verify-resource`: one correct switch verified, eleven wrong ones refused) |
| generators | `tools/geek_mode_coverage.py --check`; `tools/gen_geek_fixtures.py --check`; `tools/geek_mode_dashboard_config.py --check` | 0; 0; 0 | no drift; no drift; `OK: 147178 bytes, sha256 4abf3b1e...` |
| Node suites (local; 13 files, one process each) | `node --test --test-concurrency=2 test/<file>.test.mjs` through the guard | all 0 | core 157, element 150, coverage 4, static 60, real-catalogue 159, scan 16, budget 14, async 41, cache 9, differential 5, perf 11, strip-check 14, generated-config 5: **645 tests, 645 pass, 0 skipped** |
| the mutation proof (local; run last and alone) | `node --test --test-concurrency=2 test/mutations.test.mjs` | 0 | **518/518 mutants killed**; 538 tests, 538 pass; 1,399 s |
| headless strip check (local; Chrome) | `node preview/check-strip.mjs --require` | 0 | PASS: 6816 of 6816 checks |
| its self-test | `node preview/check-strip.mjs --selftest --require` | 0 | SELFTEST PASS: the real card passes, 38 of 38 broken copies are caught |

**Not run here, said plainly:** GitHub CI (nothing is pushed), the firmware compile jobs of CI, the PowerShell syntax parse of CI
(no `.ps1` file is touched), `tools/tests/Test-EccoDeploy.ps1` (no deploy tool is touched), the owner's M2 private-pattern scan
(owner's go only), and anything on a live system. The two failures above are the only ones, and both predate this change.
