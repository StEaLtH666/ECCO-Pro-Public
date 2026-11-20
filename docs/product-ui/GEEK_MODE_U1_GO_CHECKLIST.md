# U1 Production Mode / Geek Mode: the short GO checklist

For the owner's decision on the first live Home Assistant update. The full detail is in `GEEK_MODE_FIRST_UPDATE_RUNBOOK.md`, cited here as
"runbook N" (a section number). Written 20 Nov 2026. Nothing in this list has been done.

## 1. The answer

**Prepared offline and never run in a real Home Assistant or a real browser.** The kit is offline-verified (the pinned bytes, the generator, the
two read-back gates run on a hand-made plan, the PowerShell blocks against stand-ins, the suites of runbook 13) and not yet run live. That is not a
claim that it works: the supervised first look is where that is learned.

It is ready for your GO decision on three conditions: you choose the commit (D-U1-1) and its offline checks are green; you record the
voice-assistant setting (D-U1-2); you are present with a fresh protected full backup. The blockers are in section 7. The card is read-only;
Intelligence stays NOT ACCEPTED and in SHADOW (advice only); no firmware, inverter, InfluxDB or restart is involved.

| Pinned artefact (the same at every commit of this branch) | Size and sha256 |
|---|---|
| the card, file name `ecco-mode-shell.17410163.js` (sha8 `17410163`) | 155,843 bytes, `17410163c016578f73428900087dc714f89336bbc55cc77ec5cbfc2e240d5775` |
| the generated dashboard text | 147,178 bytes, `4abf3b1e8eca72a6a1bebb0a22eaa535ba5bcf705ab8e9ba745059bfdbd82167` |

## 2. What is installed, and what is not

| # | Installed | Exact | By |
|---|---|---|---|
| A1 | one file | `/config/www/ecco/ecco-mode-shell.17410163.js` | the coordinator, with `deploy-ha.ps1` |
| A2 | one module resource | URL `/local/ecco/ecco-mode-shell.17410163.js`, type module | you, by hand |
| A3 | one admin-only dashboard | new, storage mode, the generated text pasted | you, in the UI |

**Not touched:** the production Overview; the existing Intelligence dashboard and integration; packages, helpers, automations, scripts and safety alerts;
firmware, dongle, inverter, InfluxDB. No entity is created and Home Assistant is not restarted. The one write the new page can cause is the existing
pause tile's toggle, the same write the existing Intelligence dashboard already offers; nobody taps it (runbook 1.1).

## 3. The five checks of your directive

| Check | How it is proven | Stop condition |
|---|---|---|
| **Exact module resource** | the name comes from the card's own sha256; `verify-served` fetches it and compares the sha256; `verify-resource` proves one new resource, none changed, URL and type equal the plan (runbook 5.3, 5.4) | any line but `RESOURCE VERIFIED`; a wrong URL gives `NOT SWITCHED` or `NOT VERIFIED` (every case run offline) |
| **Admin-only dashboard setup** | "Require admin" on at creation; step 6 reads `require_admin` back from the stored list (runbook 5.5, 5.6) | `require_admin` not true; no raw editor offered |
| **Backup** | your protected full backup in the UI before any live write; byte-exact copies of every `.storage/lovelace*` file, each hash-checked `EXACT` (runbook 5.1, 5.2) | no protected backup; a copy `NOT EXACT` |
| **Rollback** | section 6: dashboard, resource, file, each separate, no restart; re-read and compared with the baseline (runbook 7) | a re-check that is not equal |
| **Correct-dashboard targeting** | two checks before Save (a new empty configuration; the new dashboard's address in the address bar), then a changed/new/gone verdict: exactly one new `.storage/lovelace.<id>` file, every other dashboard file at its baseline hash (runbook 5.5, 5.6) | a failed pre-save check (do not Save); any other file changed (runbook 7, S1) |

## 4. The installation sequence

Each live step needs your own go, given at the time; a go for one step is not a go for the next. Any other output than the expected one is a stop.

| Step | Who | What (the full block is in the runbook section named) | Expected | Stop |
|---|---|---|---|---|
| 0 | coordinator | offline gates on the chosen commit; the generation below; your M2 scan, push and draft pull request, each on your go (runbook 5.0) | suites green, hashes as pinned, CI green | any new failure; a hash that is not the pinned one |
| 1 | coordinator, your go | live read-only baseline: lists, hashes, byte-exact copies, states, log lines (runbook 5.1) | every copy `EXACT`; nothing of A1 to A3 present | anything of A1 to A3 already there; Core not running; a copy that is not `EXACT` |
| 2 | you | protected full backup; RG-F3 recorded; quiet window (runbook 5.2) | a protected backup exists | no protected backup |
| 3 | coordinator, your go | copy the card with `deploy-ha.ps1`, then `verify-served` (runbook 5.3) | `ECCO DEPLOYMENT PASSED`, `Restart     : no`, `RESOURCE NOT REGISTERED`; one PASS line | any failure line; a hash mismatch; the tool's own rollback message; more than the one new file |
| 4 | you add, coordinator reads, your go | the one resource, then `verify-resource`, then one look at the production Overview (runbook 5.4) | `RESOURCE VERIFIED`; the Overview as before | any other line; another resource changed; an Overview error that names the shell |
| 5 | you | create the dashboard, Require admin on, the two checks, paste, Save (runbook 5.5) | the dashboard exists, admin-only | no raw editor; Home Assistant refuses the text; a failed pre-save check |
| 6 | coordinator, your go | read-only after-checks and `--verify-storage` (runbook 5.6) | verdict as expected; `STORED CONFIGURATION EQUALS THE GENERATED ONE` | any difference that is not listed |
| 7 | you | ONE look: Production first; Geek only after you say go; never tap the pause tile (runbook 5.7) | the checks of runbook 5.7 | a freeze, a blank or contradicting strip, a console error that names the shell |
| 8 | coordinator, your go | no-write evidence: states and history of the control entities (runbook 5.8) | nothing changed | any control entity changed |
| 9 | coordinator | close-out: the status update; a post or push only on your go (runbook 5.9) | evidence filed | none |

```powershell
cls
$PY = '<PY>'; Set-Location <checkout>
& $PY -I -B -X utf8 tools\geek_mode_dashboard_config.py --out dist\geek-u1\dashboard-config.json --resource-plan dist\geek-u1\plan.json
& $PY -I -B -X utf8 tools\geek_mode_dashboard_config.py --check dist\geek-u1\dashboard-config.json
```

```powershell
cls
.\tools\deploy-ha.ps1 -Source frontend\ecco-mode-shell\ecco-mode-shell.js -Destination /config/www/ecco/ecco-mode-shell.17410163.js -Python $PY
& $PY -I -B -X utf8 tools\ecco_deploy_preflight.py verify-served --plan dist\geek-u1\plan.json --base-url <HA URL>
& $PY -I -B -X utf8 tools\ecco_deploy_preflight.py verify-resource --plan dist\geek-u1\plan.json --resources "$E\resources-now.json" --before "$E\resources-before.json" --base-url <HA URL>
& $PY -I -B -X utf8 tools\geek_mode_dashboard_config.py --verify-storage "$E\stored-config.json"
```

The first block is step 0. The second holds the commands of steps 3, 4 and 6 in the order they are run, with the owner's own actions between them
(steps 4 and 5) and the captures that feed them (`resources-now.json`, `stored-config.json`) in the runbook blocks. These are the short
forms: each runbook block sets `$H`, `$E`, `$PY` and the checkout folder itself, and its placeholders are filled in first.

## 5. After the install (all read-only)

1. The production Overview renders as before and the console shows no error that names the shell (runbook 5.4).
2. The new dashboard is listed once, `require_admin` true, and the verdict is as expected: `changed` is the two lists, `new` is one file (runbook 5.6).
3. `STORED CONFIGURATION EQUALS THE GENERATED ONE`; no new lovelace, frontend or shell line in the log (runbook 5.6).
4. Production look: the shell starts in Production; the Intelligence card and the watchdog card read as on the existing Intelligence dashboard;
   the alert strip is never blank and does not contradict them (runbook 5.7).
5. Geek look, after your go: 17 source rows in five groups; the pause tile is hidden (runbook 5.7).
6. No control entity changed and each shows one history row (runbook 5.8). If anything fails: runbook 10 says what it means.

## 6. Rollback, in this order (runbook 7); nothing is restarted

1. **A3, the dashboard.** You delete it in the UI. Proven by re-reading: the dashboard list equals the baseline and no `lovelace.<id>` file is left.
2. **A2, the resource.** You delete the one resource in the UI. Proven: the resource list equals the baseline (compared as parsed items).
3. **A1, the card file.** It may stay (it is inert without a resource); if you want it gone it is moved by hand, never deleted.
4. **Re-check.** Every other dashboard file has its baseline sha256; `/config/www/ecco/` equals the baseline or lacks only the moved file.

Special cases: S1, a paste into the wrong dashboard (paste the saved byte-exact copy back and compare); S2, the pause tile tapped (tap it again,
or set the helper back, and record both). Restoring the Home Assistant backup is a heavy last resort: it restarts Home Assistant and returns
everything the backup holds to its state at backup time. It is your decision and never the first rollback (runbook 5.2).

## 7. Blockers and your decisions

No open defect is known from the offline checks. What stands between this list and a GO: nothing is pushed and CI has not run on this branch (D-U1-4); your M2
private-pattern scan has not run; D-U1-1 and D-U1-2 are not decided; the host reads (state, history, log, the globbed `sha256sum`, the stored-file
`scp`) have not run on the real host.

| Decision | Recommended answer | If undecided |
|---|---|---|
| D-U1-1 the commit to install from | the branch commit after green CI on the draft pull request, merged afterwards; the card's sha256 must be unchanged at the merge | no install: step 0 cannot finish |
| D-U1-2 RG-F3, the voice-assistant "expose new entities" settings | record both today and waive for U1 only (no entity is created); required again for any install that creates one | no install (runbook 3, G5) |
| D-U1-3 the order of the release bookkeeping against R9, Stage 3, grid-loss, F5 | defer it all until after the first look; the install needs none of it | the install is unaffected; the merge waits |
| D-U1-4 when to push and open the draft pull request, and when the M2 scan runs | push as a draft now so CI runs; the M2 scan on the exact commit before the install | step 0 cannot finish: no install |
| D-U1-5 the dashboard's title, address and sidebar entry | `ECCO Modes (first look)`, `ecco-modes-u1`, shown in the sidebar (admin-only) | those suggestions are used |
| D-U1-6 the Geek look in the same session | yes, only after the Production look passes and you say go | Production only |

## 8. What is NOT established

- The shell has never run in a real Home Assistant or a real browser: it ran in Node with a stand-in page and in headless Chrome against a stand-in
  state. How the real frontend nests its child cards, real theme variables, console cleanliness and real speed are unknown until the look.
- A module resource is global: once it is registered, every dashboard page on every client loads the shell module, whatever the admin-only setting says
  (the production Overview is looked at once for that reason; an old phone web view logs a harmless module error).
- Require admin is a visibility setting for the page, not a security boundary against a non-admin who calls Home Assistant's own API. It keeps the page
  out of a non-admin sidebar (recalled from Home Assistant's behaviour, not verified). The text holds no secret.
- 42 of the 344 declared attribute rows are conditional and read "Not present" until their condition holds; the catalogue was compared with one live
  capture of 14 Nov only, and one helper was not checked live.
- The pause tile still writes when tapped: the same write as on the existing Intelligence dashboard, now on a second page.
- Several Home Assistant screen names and stored-file details are recalled, not verified (runbook 9).
- Nothing here says anything about forecast accuracy. Intelligence stays NOT ACCEPTED and in SHADOW; R9, Stage 3, Ghost and the PV gate are separate.
