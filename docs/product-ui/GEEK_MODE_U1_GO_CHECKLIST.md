# U1 Production Mode / Geek Mode: the short GO checklist

For the owner's decision on the first live Home Assistant update. The full detail is in `GEEK_MODE_FIRST_UPDATE_RUNBOOK.md`, cited here as
"runbook N" (a section number). Written 20 Nov 2026, updated 21 Nov 2026 for the owner's decision. Nothing in this list has been done.
Length, said honestly: it was 136 lines; with the decision, the exact targets, the write-path statement, the release gates and the per-dashboard check it is now
186 lines (its suite allows 200). Every table says what is yours and what is the coordinator's.

## 1. The answer

**Prepared offline and never run in a real Home Assistant or a real browser.** The kit is offline-verified (the pinned bytes, the generator, the
two read-back gates run on a hand-made plan, the PowerShell blocks against stand-ins, the suites of runbook 13) and not yet run live. That is not a
claim that it works: the supervised first look is where that is learned.

**Your decision of 21 Nov 2026.** Push `dev/geek-mode-u1`, open a DRAFT pull request, run the complete M2 private-pattern scan on the exact commit first
(generated assets, commit metadata and pull request text included), run CI (D-U1-4). Install from the branch commit after green CI; merge is a separate later
decision and the card's sha256 must be unchanged at the merge (D-U1-1, option a). RG-F3 (D-U1-2) is resolved for U1 only: the existing voice-assistant exposure
settings remain a separately tracked F3 issue because this installation creates no new entity. That is not acceptance of F3 and not permission to introduce new
exposed controls; any later install that creates an entity still needs both settings off. **No automatic installation or live access is authorised by that
approval:** nothing is installed and nothing live is touched until your final installation GO, given on this completed list, and each live step needs its own
go. Ghost stays the second update, with its own restart and rollback requirements.

What stands between this list and your GO: the draft pull request's CI green on the exact commit and the M2 scan (step 0); then, at install time, your reads,
your protected full backup and your presence (section 7). The card is read-only; Intelligence stays NOT ACCEPTED and in SHADOW (advice only); no firmware,
inverter, InfluxDB or restart is involved.

| Pinned artefact (the same at every commit of this branch) | Size and sha256 |
|---|---|
| the card, file name `ecco-mode-shell.17410163.js` (sha8 `17410163`) | 155,843 bytes, `17410163c016578f73428900087dc714f89336bbc55cc77ec5cbfc2e240d5775` |
| the generated dashboard text | 147,178 bytes, `4abf3b1e8eca72a6a1bebb0a22eaa535ba5bcf705ab8e9ba745059bfdbd82167` |

## 2. What is installed, what is read, and what is not touched

| # | Installed or read | Exact | By |
|---|---|---|---|
| A1 | one file | `/config/www/ecco/ecco-mode-shell.17410163.js` | the coordinator, with `deploy-ha.ps1` |
| A2 | one module resource | URL `/local/ecco/ecco-mode-shell.17410163.js`, type module | you, by hand |
| A3 | one admin-only dashboard | new, storage mode, URL path `ecco-modes-u1`, title `ECCO Modes (first look)` (D-U1-5, the default), the generated text pasted | you, in the UI |
| read | read, never written | `.storage/lovelace_resources`, `.storage/lovelace_dashboards`, every `.storage/lovelace*` file, `ecco/dashboards/*.yaml` (hashes), the `/config/www/ecco/` listing | the coordinator, read-only |

**Verify the targets** (runbook 1.2; an unmet check is a stop at that step): (a) step 1: the baseline shows the existing Intelligence card's resource URL under
`/local/ecco/` too, so `/config/www/ecco/` is the right folder; (b) step 1: the dashboard path `ecco-modes-u1` and the resource URL are not already in the
baseline lists; (c) step 3: `verify-served` proves the `/config/www/ecco/` to `/local/ecco/` mapping and the bytes before any resource exists; (d) step 4:
`verify-resource` proves the registered URL and type equal the plan.

**Not touched:** the production Overview; the existing Intelligence dashboard and integration; packages, helpers, automations, scripts and safety alerts;
firmware, dongle, inverter, InfluxDB. No entity is created and Home Assistant is not restarted. The one write the new page can cause is the existing
pause tile's toggle, the same write the existing Intelligence dashboard already offers; nobody taps it (runbook 1.1). That statement is scoped to the card's own
code and what the page places: the standard more-info dialog keeps Home Assistant's own admin settings (entity registry edits), as on any dashboard (recalled,
not verified).

**Write-path statement** (runbook 1.1; no card change). (a) Switching Production and Geek invokes no service: the switch handler only sets a presentation choice
(`createModeController` has no reference to `hass`). Node tests, exact names: "generated config: both modes and a state change touch nothing but hass.states,
locale and themes (no service, no websocket, no storage, no network)" (the real generated configuration; every `hass` function and every network, storage and
window API trapped; that file ran 5 of 5, 0 skipped) and "AC5 the switch never changes helper or service state: Production-only and always cards see no extra hass
call from a mode change" (element suite 150 of 150, core suite 157 of 157). (b) The pause tile is the only write-capable control the page places: the card's own code
has no service call, fetch, websocket, storage or dynamic code; the one write-capable control is the existing pause tile (an input boolean toggle: the same tile and
write as on the existing Intelligence dashboard). Geek Mode hides it ("generated config: Geek Mode shows the 17 sources and the 344 declared attribute rows, and the
Production-only tile is hidden"). Geek Mode's "Open in Home Assistant" opens Home Assistant's own more-info dialog only for sensor, binary sensor and event entities
(every other domain gets "Copy entity id"; "AC16 [r1] Geek Mode opens a dialog only for read-only domains: over every domain the real catalogue discovers no writable
one offers it, and none dispatches hass-more-info"). That dialog is Home Assistant's own and keeps its settings for an administrator: not an ECCO write path and not
part of the first look, which presses none of Open in Home Assistant, Copy, JSON or CSV.

## 3. The five checks of your directive

| Check | How it is proven | Stop condition |
|---|---|---|
| **Exact module resource** | the name comes from the card's own sha256; `verify-served` fetches it (before any resource exists) and compares the sha256; `verify-resource` proves one new resource, none changed, URL and type equal the plan (runbook 5.3, 5.4) | any line but `RESOURCE VERIFIED`; a wrong URL gives `NOT SWITCHED` or `NOT VERIFIED` (every case run offline) |
| **Admin-only dashboard setup** | "Require admin" on at creation; step 6 reads `require_admin` back from the stored list (runbook 5.5, 5.6) | `require_admin` not true; no raw editor offered |
| **Backup** | your protected full backup in the UI before any live write; byte-exact copies of every `.storage/lovelace*` file, each hash-checked `EXACT` (runbook 5.1, 5.2) | no protected backup; a copy `NOT EXACT` |
| **Rollback** | section 6: dashboard, resource, file, each separate, no restart; re-read and compared with the baseline (runbook 7) | a re-check that is not equal |
| **Correct-dashboard targeting** | two checks before Save (an empty, default or auto-generated configuration of the NEW dashboard, never an existing one's content; the new dashboard's address in the address bar), then a changed/new/gone verdict: exactly one new `.storage/lovelace.<id>` file, every other dashboard file at its baseline hash (runbook 5.5, 5.6) | a failed pre-save check (do not Save); any other file changed, or a SECOND new lovelace file (runbook 7, S1) |

## 4. The installation sequence

Each live step needs your own go, given at the time; a go for one step is not a go for the next. Any other output than the expected one is a stop.

| Step | Who | What (the full block is in the runbook section named) | Expected | Stop |
|---|---|---|---|---|
| 0 | coordinator | offline gates on the chosen commit; the generation below; the M2 scan on the exact commit, the push, the draft pull request and CI (your decision of 21 Nov, D-U1-4) (runbook 5.0) | suites green, hashes as pinned, M2 clean, CI green | any new failure; a hash that is not the pinned one; a changed commit repeats the checks and scans |
| 1 | coordinator, your go | live read-only baseline: lists, hashes, byte-exact copies, log lines, target checks (a) and (b) (runbook 5.1) | every copy `EXACT`; nothing of A1 to A3 present; (a) and (b) hold | anything of A1 to A3 already there; the Intelligence card's resource not under `/local/ecco/`; Core not running; a copy that is not `EXACT` |
| 1b | coordinator, your separate go | live shape check: block 3 (the state read), then the offline tool `geek_mode_live_shape_check.py` on `states-before.json` (runbook 5.1b) | exit 0; 17 of 17 declared entities present, 0 undeclared, 0 unexplained | anything UNDECLARED, a declared entity missing or an unexplained absence: stop and ask you (the catalogue is out of date for this host, so the Geek inspector would be wrong; Production is unaffected) |
| 2 | you | protected full backup; quiet window (runbook 5.2) | a protected backup exists | no protected backup |
| 3 | coordinator, your go | copy the card with `deploy-ha.ps1`, then `verify-served` (runbook 5.3) | `ECCO DEPLOYMENT PASSED`, `Restart     : no`, `RESOURCE NOT REGISTERED`; one PASS line | any failure line; a hash mismatch; the tool's own rollback message; more than the one new file |
| 4 | you add, coordinator reads, your go | the one resource, then `verify-resource`, then your check of EACH existing dashboard (runbook 5.4) | `RESOURCE VERIFIED`; every existing dashboard: yes, yes, yes | any other line; another resource changed; a no on any dashboard (you delete the one resource) |
| 5 | you | create the dashboard, Require admin on, the two checks, paste, Save (runbook 5.5) | the dashboard exists, admin-only | no raw editor; Home Assistant refuses the text; a failed pre-save check |
| 6 | coordinator, your go | read-only after-checks and `--verify-storage` (runbook 5.6) | verdict as expected; `STORED CONFIGURATION EQUALS THE GENERATED ONE` | any difference that is not listed |
| 7 | you | ONE look: Production first; Geek only after you say go; never tap the pause tile (runbook 5.7) | the checks of runbook 5.7 | a freeze, a blank or contradicting strip, a console error that names the shell |
| 8 | coordinator, your go | no-write evidence: states and history of the control entities (runbook 5.8) | nothing changed | any control entity changed |
| 9 | coordinator | close-out: the status update; a post or push only on your go (runbook 5.9) | evidence filed | none |

```powershell
cls
$PY = '<PY>'; Set-Location <checkout>
New-Item -ItemType Directory -Force dist\geek-u1 | Out-Null
& $PY -I -B -X utf8 tools\geek_mode_dashboard_config.py --out dist\geek-u1\dashboard-config.json --resource-plan dist\geek-u1\plan.json
& $PY -I -B -X utf8 tools\geek_mode_dashboard_config.py --check dist\geek-u1\dashboard-config.json
```

```powershell
cls
& $PY -I -B -X utf8 tools\geek_mode_live_shape_check.py "$E\states-before.json"
.\tools\deploy-ha.ps1 -Source frontend\ecco-mode-shell\ecco-mode-shell.js -Destination /config/www/ecco/ecco-mode-shell.17410163.js -Python $PY
& $PY -I -B -X utf8 tools\ecco_deploy_preflight.py verify-served --plan dist\geek-u1\plan.json --base-url <HA URL>
& $PY -I -B -X utf8 tools\ecco_deploy_preflight.py verify-resource --plan dist\geek-u1\plan.json --resources "$E\resources-now.json" --before "$E\resources-before.json" --base-url <HA URL>
& $PY -I -B -X utf8 tools\geek_mode_dashboard_config.py --verify-storage "$E\stored-config.json"
```

The first block is step 0. The second holds the commands of steps 1b, 3, 4 and 6 in the order they are run, with the owner's own actions between them
(steps 4 and 5) and the captures that feed them (`states-before.json`, `resources-now.json`, `stored-config.json`) in the runbook blocks. These are the short
forms: each runbook block sets `$H`, `$E`, `$PY` and the checkout folder itself, and its placeholders are filled in first.

## 5. After the install (all read-only)

1. Every existing dashboard answers yes to three questions: it renders as before (same cards, nothing red, no new error card), the console shows no new error that
   names the shell or its resource, and the page responds. The list is `dashboards-to-check.txt`, written by the coordinator from the baseline before step 4: the
   production Overview, the existing Intelligence dashboard, every other dashboard and YAML dashboard file, and any wall or phone client (a note for the known
   old-web-view error). Any no is a stop: you delete the one resource (rollback A2) and the same list is looked at again. The Overview's file hash stays at
   its baseline (runbook 5.4, 5.6).
2. The new dashboard is listed once, `require_admin` true, and the verdict is as expected: `changed` is the two lists, `new` is one file; a second new file is a stop (runbook 5.6).
3. `STORED CONFIGURATION EQUALS THE GENERATED ONE`; no new lovelace, frontend or shell line in the log (runbook 5.6).
4. Production look: the shell starts in Production; the Intelligence card and the watchdog card read as on the existing Intelligence dashboard;
   the alert strip is never blank and does not contradict them (runbook 5.7).
5. Geek look, after your go: 17 source rows in five groups; the pause tile is hidden (runbook 5.7).
6. No control entity changed and each shows one history row (runbook 5.8). If anything fails: runbook 10 says what it means.

## 6. Rollback, newest first: A3 the dashboard, A2 the resource, A1 the file (runbook 7); nothing is restarted

Measured against two things made before any live write: **(i) the baseline**, the read-only reads of runbook 5.1 (the resource and dashboard lists, the sha256 of
every `.storage/lovelace*` file and dashboard file, the card folder listing, the Home Assistant version, the states and the log lines) with a **byte-exact copy** of
each `.storage/lovelace*` file, each hash-checked `EXACT`; and **(ii) your protected full backup**, made in the Home Assistant UI (runbook 5.2), the last resort.

1. **A3, the dashboard.** You delete it in the UI. Proven by re-reading: the dashboard list equals the baseline and no `lovelace.<id>` file is left.
2. **A2, the resource.** You delete the one resource in the UI. Proven: the resource list equals the baseline (compared as parsed items).
3. **A1, the card file.** It may stay (it is inert without a resource); if you want it gone it is moved by hand, never deleted. Proven: `/config/www/ecco/` equals the baseline, or differs by only that file when it is left in place.
4. **Re-check.** Every other dashboard file has its baseline sha256, the production Overview and the existing Intelligence dashboard among them (the `-rollback` reads of runbook 7).

Special cases: S1, a paste into the wrong dashboard (a changed file: paste the saved byte-exact copy back and compare; a SECOND new lovelace file: no
baseline copy exists, so clear that dashboard's stored configuration through its own UI, else the protected backup); S2, the pause tile tapped (tap it again,
or set the helper back, and record both). Restoring the Home Assistant backup is a heavy last resort: it restarts Home Assistant and returns
everything the backup holds to its state at backup time. It is your decision and never the first rollback (runbook 5.2).

## 7. Blockers and your decisions

No open defect is known from the offline checks. What stands between this list and a GO: step 0 is the coordinator's (the M2 scan on the exact commit, the push, the
draft pull request and CI: at the time of this text none of the four had been done); then, at install time, the host reads (state, history, log, the globbed `sha256sum`,
the stored-file `scp`, the shape check: none has run on the real host), your protected backup and your presence; and your final installation GO.

| Decision | Status (your decision of 21 Nov 2026) | If undecided |
|---|---|---|
| D-U1-1 the commit to install from | **decided, option (a):** the branch commit after green CI on the draft pull request; the card file is content-addressed, so the installed bytes equal the reviewed card whatever later commits do; merge is a separate later decision and the card's sha256 must be unchanged at the merge | (decided) |
| D-U1-2 RG-F3, the voice-assistant "expose new entities" settings | **decided, for U1 only:** the existing voice-assistant exposure settings remain a separately tracked F3 issue because this installation creates no new entity; not acceptance of F3 and not permission to introduce new exposed controls; both settings off again for any install that creates an entity | (decided) |
| D-U1-3 the order of the release bookkeeping against R9, Stage 3, grid-loss, F5 | default: defer it all until after the first look; the install needs none of it | the install is unaffected; the merge waits |
| D-U1-4 when to push and open the draft pull request, and when the M2 scan runs | **decided:** push, a DRAFT pull request, the complete M2 scan on the exact commit first (generated assets, commit metadata, pull request text), CI | (decided) |
| D-U1-5 the dashboard's title, address and sidebar entry | default: `ECCO Modes (first look)`, `ecco-modes-u1`, shown in the sidebar (admin-only) | those suggestions are used |
| D-U1-6 the Geek look in the same session | default: yes, only after the Production look passes and you say go | Production only |

**Release gates** (runbook 3). Only G1 is met by the offline work, and only in part; the rest are yours or the coordinator's at install time.

| Gate | What | Status |
|---|---|---|
| G1 | step 0 green on the exact commit: the suites, the M2 scan, the push, the draft pull request's CI; the commit chosen | satisfied by the offline work (suites, hashes, the choice D-U1-1); the M2 scan and CI run on the exact commit before your GO |
| G2 | a quiet period reserved, you present, no other live step running | yours at install time |
| G3 | a fresh protected full backup made in the Home Assistant UI | yours at install time |
| G4 | the live baseline saved (steps 1 and 1b), the shape check exits 0, the states noted | yours at install time (your go for each read) |
| G5, RG-F3 | the voice-assistant "expose new entities" settings | resolved for U1 by the owner on 21 Nov: separately tracked F3, no new entity |
| G6 | a desktop browser whose clock is within five minutes of Home Assistant's | yours at install time |
| G7 | the first look is Production only, Geek only after you say go, the pause tile never tapped | yours at install time |

## 8. What is NOT established

- The shell has never run in a real Home Assistant or a real browser: it ran in Node with a stand-in page and in headless Chrome against a stand-in
  state. How the real frontend nests its child cards, real theme variables, console cleanliness and real speed are unknown until the look.
- A module resource is global: once it is registered, every dashboard page on every client loads the shell module, whatever the admin-only setting says
  (every existing dashboard is checked for that reason; an old phone web view logs a harmless module error). Phone and tablet layouts are not part of U1.
- Require admin is a visibility setting for the page, not a security boundary against a non-admin who calls Home Assistant's own API. It keeps the page
  out of a non-admin sidebar (recalled from Home Assistant's behaviour, not verified). The text holds no secret.
- 42 of the 344 declared attribute rows are conditional and read "Not present" until their condition holds; the catalogue was compared with one live
  capture of 14 Nov only, and one helper was not checked live (step 1b compares it again on the install day).
- The pause tile still writes when tapped: the same write as on the existing Intelligence dashboard, now on a second page.
- A service call that changes no state leaves no durable record, so the no-write proof of step 8 has that limit (runbook 5.8): it also rests on the card's
  source having no service call and on your word that nothing was tapped.
- CI runs no Node: the Node suites, the mutation proof and the headless check ran on one PC only; CI's guard is the Python pin suite (runbook 9).
- The deploy and preflight tools, the shape check and the host reads (the globbed `sha256sum`, the `scp` of the `.storage` files, the Supervisor state, history
  and log reads) have never run against the real host (runbook 9).
- Several Home Assistant screen names and stored-file details are recalled, not verified (runbook 9).
- Nothing here says anything about forecast accuracy. Intelligence stays NOT ACCEPTED and in SHADOW; R9, Stage 3, Ghost and the PV gate are separate.
