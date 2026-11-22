# ECCO Intelligence: the inverter power-balance update (U3), a supervised Home Assistant update: runbook

**Status: PREPARED OFFLINE, RUN ONCE ON AN ISOLATED TEST INSTANCE, NEVER ON THE OWNER'S HOME ASSISTANT, NOT READY.** Nothing in this
document has been done on the owner's Home Assistant. The update has never run in a real Home Assistant that is the owner's (section
12): the one run of the stacked kit in a real Home Assistant Core was on an isolated test instance (P1, closed 22 Nov 2026). It is not
ready for a go until the preconditions of section 5 that are marked OPEN are closed (P4, P5 and P7 at the time of writing; P1, P2,
P3, P6, P8 and P9 are closed, and P1 reopens after any Core or Python update of the host, U3-G5). Every live step below needs its own
owner authorisation, in the session, at the time (column "own authorisation" of the step table). **This branch is stacked on the
commit the Ghost update (U2) was installed from**: its kit holds U2's files and changes only the four sources and the manifests
that section 2.2 lists, so the installed Ghost kit is the baseline of every comparison below.

> **Every live step in this runbook is NOT AVAILABLE** until all of these hold:
>
> 1. Every precondition of section 5 is closed, and the owner has recorded the acceptance items of section 4.
> 2. The owner has reserved a quiet period, is present, has made a fresh **protected** full backup (step 2) and has given the
>    final installation go on the completed checklist (`POWER_BALANCE_UPDATE_GO_CHECKLIST.md`).
> 3. The owner has given the go for each live step, one by one. A go for one step is not a go for the next.
>
> **No automatic installation or live access is authorised.** Nothing is installed, restarted, reloaded or read live until those
> three hold. ASSISTED and AUTONOMOUS stay disabled; Intelligence stays SHADOW (advice only).

**Notation.** Placeholders are written `<like this>`. `<production alias>` is the owner's SSH alias for the production host.
`<OFFLINE_EVIDENCE_DIR>` is the owner's local evidence folder; it is never in a repository, and nothing that holds a site value
(a download, a read-back, a listing, the fit tool's output, a site file) is ever copied into a repository. `<checkout>` is a clean
checkout of the chosen commit. `<PY>` is a Python 3.12 interpreter with PyYAML installed in that interpreter itself. `<version>`
is the content of the host's Home Assistant version file as read in step 1. `<site file>` is the owner's new site file (the one now
on the host plus the three facts), a file outside every repository. Every PowerShell block starts with `cls`. This runbook quotes
no secret, host, address, token, entity id or site value: it names roles. **The three calibrated facts are site values**: they live
in `<OFFLINE_EVIDENCE_DIR>` and in the site file, never in a repository, a commit message or a pull request. It reuses the commands
and tools of [`INTELLIGENCE_SHADOW_INSTALL_RUNBOOK.md`](INTELLIGENCE_SHADOW_INSTALL_RUNBOOK.md) ("the install runbook", cited as
"install runbook N" by section number) and invents none.

## 1. The owner's direction, and what this update is and is not

The owner's words (22 Nov 2026), quoted:

> "Also keep the diagnosed inverter power-balance correction ready as the following separate update. I want that degradation
> fixed, but not bundled into Ghost."
>
> "Do not make live changes or restart Home Assistant until Ghost has its final GO."

| The direction | Where it is met in this runbook |
|---|---|
| the following separate update | it is its own update (U3), after Ghost (U2): its own window, backup, restart and rollback verification; never in U2's window (P6, U3-G2, D-U3-1) |
| not bundled into Ghost | the kit of this update changes four source files of the engine and the loader and nothing of Ghost (section 2.2); the Ghost update's own runbook and checklist are separate documents |
| that degradation fixed | section 2.3 says what the update changes and 8.13 what is read to see it; data quality may stay DEGRADED for another reason, and the runbook says so (D-U3-7) |
| no live change until Ghost has its final GO | Ghost (U2) is installed (P6 is closed, section 5); every live step of section 7 is still NOT AVAILABLE until the rest of section 5 is closed |

**The cause, in one paragraph.** On the owner's Home Assistant the export-event and dump-to-grid outputs read unknown, each with the
blocker `POWER_BALANCE_INCONSISTENT`, and data quality reads DEGRADED; it has been so since the shadow install and it is not new. A
read-only diagnosis of 21 Nov 2026 (its evidence is offline and holds site values, so nothing of it is quoted here) found a physical
cause and no data fault: the engine's balance check expects house = PV + battery + grid with no loss, while PV and battery power are
DC-side readings and the house power is the inverter's output plus the grid CT, so the residual is the inverter's conversion loss
plus its own draw, larger than the tolerance (the larger of 100 W and 5 % of the largest magnitude) whenever PV or battery power
is large. It is not a sign fault, not a stale input and not the legacy devices. The method is in
[`DATA_QUALITY_METHOD.md`](DATA_QUALITY_METHOD.md) section 10.1.

**What U3 is.** The third supervised update, after U1 (a read-only dashboard card) and U2 (Ghost diagnostics, a kit upgrade with
its own tables). It replaces the Intelligence integration's code (the kit built by `tools/build_ha_integration.py`) on the live
host, needs **one** Home Assistant restart, and then changes the owner's site file: three optional facts in the `site` block (the
inverter's DC-to-AC factor, its AC-to-DC factor and its standby draw) that make the balance check expect the inverter's loss. The
facts take effect at a separately approved config-entry reload (a reload, not a second restart). **It adds no durable write**
(section 2.4). It changes the verdict of one rule for two outputs, the export event and Dump to Grid, and nothing else.

**What U3 is not.** It is not a loosening by default: with no facts the rule is the previous rule bit for bit, facts that are
incomplete or invalid are reported and never loosen it, and the two sign-reversal tests use the same expectation as the balance. It
is not an owner decision about the facts: they are PROPOSED engineering parameters calibrated per site by the fitting tool. It is
not acceptance of Intelligence, which stays SHADOW. It is not the legacy-device clean-up (D-U3-8), U1, U2, R9, Stage 3, the PV gate
or the Gentle controller, each of which has its own track.

## 2. What changes on the host, and what does not

### 2.1 The artefacts

| # | Artefact | Where | How it gets there | Reversible by |
|---|---|---|---|---|
| A1 | the Intelligence integration folder, replaced as a whole by the kit (57 files installed; none new, 5 changed, 52 identical to the installed Ghost kit) | `/config/custom_components/ecco_intelligence/` | `tools/deploy-ha-kit.ps1 -Action Upgrade` (stage, verified backup, atomic swap, `ha core check`; no restart) | `-Action Rollback -BackupStamp` (section 10, RB4) |
| A2 | the owner's site file, its `site` block gaining the three facts | `/config/ecco/intelligence/site.local.json` | `tools/place-ha-site-file.ps1` (a verified backup of the file now there, an upload hashed on the host, an atomic rename, a read-back); it takes effect only at a config-entry reload or a restart | placing the previous file again (section 10, RB2) |
| A3 | the staging and backup folders of the Upgrade, and the backup folder of the placement | `/config/ecco/staging/<stamp>/` and `/config/ecco-backups/<stamp>/` | the two tools; nothing is ever deleted | kept; the owner cleans up when the owner decides |

Not written by this update: any table, column or row type (the scorecard file and `store_meta.json` are written exactly as
before), any helper, entity, automation, package, schedule, dashboard, resource, firmware, the dongle, the inverter or the
time-series database. The one helper the procedure touches is the existing pause helper, which the **owner** turns on before the
Upgrade and off after the checks (install runbook 10 and 11), exactly as the install runbook says.

### 2.2 The kit's files

The kit has 58 files (36 vendored modules, 20 integration files and the generated manifests); the installed folder holds 57 of
them (the root `VENDOR_MANIFEST.json` is not installed). Against the kit of the installed Ghost update, built the same way from the
tree this branch is stacked on (the suite rebuilds that kit from the history and compares, or prints SKIP where the history is not
in the checkout), no file is new, none is removed and five change; U2's five new files (`ghost.py`, `ghost_compare.py`,
`ghost_feed.py` and `net_value.py` under `_vendor/intelligence/`, and `runtime/ghost_link.py`) are in this kit, byte for byte the
Ghost kit's, as are the Ghost-changed `scorecard.py`, `store.py`, `coordinator.py` and `diagnostics.py`:

| Changed files | What changes |
|---|---|
| `_vendor/intelligence/site_decisions.py` | the three fact names, their bounds, `InverterConversion` (the expected house power) and `inverter_conversion` (judges the facts: all absent is lossless, all three valid is loss-aware, anything else is reported and the lossless rule stays) |
| `_vendor/intelligence/quality.py` | the live balance and both sign-reversal tests use that expectation; the blocker `POWER_LOSS_FACTS_INVALID`; the rule-set version `intel-quality-0.3.2-cfg` |
| `_vendor/intelligence/advisory_contract.py` | `SiteFacts` carries the three optional fields |
| `runtime/gates.py` | the site loader reads the three keys of the `site` block and reports the check `SITE_INVERTER_CONVERSION` |
| `VENDOR_MANIFEST.json` | the hashes of the above (the start-up self-test reads it) |

The fitting tool `intelligence/tools/power_balance_fit.py` and the site-check in `tools/ecco_intel_drill.py` are repository tools
that run offline on the owner's PC; they are not kit files. The install baseline (step 1) records what is really installed; the
comparison block of 8.1 lists exactly which files differ from the owner's installed folder. If the installed folder is not the one
the commit was built on top of, the difference is read and explained before any write (section 3 says what that means: the
installed folder must be the Ghost kit).

### 2.3 What the owner will see after the update

- **Two outputs.** The export event and Dump to Grid are no longer withheld with `POWER_BALANCE_INCONSISTENT` while the inverter's
  loss is what the readings show and the facts say so. Whether they then carry a number depends on every other gate they rest on
  (decisions, fresh inputs, tariff events, supervision): they may still read unknown, with another blocker, and that is not a
  failure of this update (8.13). The two sign-reversal blockers `CT_SIGN_REVERSED` and `BATTERY_SIGN_REVERSED` stay, judged on the
  same loss-aware expectation.
- **Data quality** may return to OK. It may stay DEGRADED: any other blocked item or any warning keeps it so (8.13 and D-U3-7).
- **The diagnostics download** (Settings, Devices and services, ECCO Intelligence, Download diagnostics) gets one more line in
  `self_test` once the facts are loaded: `SITE_INVERTER_CONVERSION`. The download shows a passing check as the single word PASS and
  a warning as `WARN:` and its short text, which names no value. With no facts there is no such line at all.
- **The status entity's `config_hash` attribute** changes when the new site file is loaded (the diagnostics download redacts it).
- Nothing else: no new entity, no new log line at the usual level (the fact names and reasons of an invalid set go to the debug
  log only), no new table.
- **U2 is installed**, so its advice log keeps its own bounds and writes the same number of rows. The Dump to Grid rows it logs
  are then real advice instead of withheld rows from the day this update takes effect. The Ghost block simulates charge-target
  advice only and counts Dump advice as not followed (U2's own limit), so this update changes nothing in the Ghost comparison;
  the logged Dump rows only become real data for a later revision.

### 2.4 The write statement

What is written, and by whom. The integration writes only under `/config/ecco/intelligence/state/`: `store_meta.json` and the
scorecard file, as before. **This update adds no table, column or row type and no file there**: the four changed source files
contain no file, database or network write (a suite check), the loader only reads bytes the store gives it, and the engine
computes. It writes nothing to Home Assistant entities, helpers, schedules, the inverter or the dongle, calls no service and fires
no event. The deploy tool writes A1 and A3 only, and never touches the site file or the state folder (it reads their hashes before
and after and refuses if they changed). The placement tool writes A2 and its own backup folder, never names the state folder, and
never restarts or reloads Home Assistant. In one line, the writes of this update are the integration folder (A1, replaced by the
kit), the site file (A2, replaced by the owner's new file), the staging and backup folders of the two tools (A3) and nothing in the
state folder (no tool of this update writes there; what the integration's own start-up rewrites is said next); the one helper the
procedure touches is the existing pause helper, which the owner switches (2.1).

**What a restart does to the state folder.** The tools of this update (the Upgrade, the Rollback and the placement) leave the state
folder byte-identical: that is what the drill proves and what the steps before the restart compare. A restart does not: the integration's own start-up
(the store's open, run at every start, so at a config-entry reload as well, as before this update and by the same code in the Ghost
kit and in this one) writes `store_meta.json` again with the same content and rewrites three pages of the scorecard file: the change
counter in the SQLite header page, and the `schema_meta` table with its index, set to the same values by the store's own
`INSERT OR REPLACE INTO schema_meta`. No table, row or trigger changes. So **before the restart of step 7 the state folder is
byte-identical to the paused read of step 4; across a restart it has the same logical content but not the same bytes** (the
scorecard file's sha256 differs, and so does its modification time), and the L3 run saw exactly that at every restart. The state
folder is therefore compared byte for byte only between two reads that have no restart or reload between them: the references for
step 9 are read again after the restart (8.8), and no proof after a restart compares a hash with a read made before it.

### 2.5 What does not change

The eleven entities and their contract, every published value's rules except the one balance rule for the two outputs, the mode
(SHADOW), the pause helper, the watchdog, the decisions, the schedule, the recorder reads, the scorecard's tables and writes, and
the integration's version string. **No entity, helper, service, package or dashboard is created or edited by this update** (RG-F3:
no new exposed control can appear; the exposure settings stay the owner's separately tracked F3 issue). The suite pins that the
platforms are sensor and binary sensor only, that the integration has eleven contract entities and that the files directly under
the kit's package are the known set.

## 3. The artefacts and their hashes

The kit is built by the repository's own tool, `tools/build_ha_integration.py --out <dir> [--git-sha S]`, from the working tree
(offline, byte-deterministic, outside the repository). Two reference builds of this kit, stacked on the installed Ghost code, are
pinned by `test_power_balance_update_docs.py`, which rebuilds the kit and compares:

| Build | Command | Files | `SHA256SUMS` sha256 |
|---|---|---|---|
| no commit recorded | `--out <dir>` | 58 (36 vendored modules, 20 integration files) | `c0a22729441156ead482d5d03ac566146f281309d27297c10e65bbc598fba64b` |
| the fixed reference commit | `--out <dir> --git-sha 0000000` | 58 (the same) | `4e3cb4bb6a4dc152eb56861734dbe64a0934732fcb30ae3be1dcef44dcb98208` |

The two differ only in the two `VENDOR_MANIFEST.json` lines (the recorded commit). The kit that is **installed** is built with
`--git-sha` of the commit it is installed from (the deploy tool compares it with the checkout's HEAD and rebuilds it), so its
`SHA256SUMS` sha256 differs from both numbers above in those two lines only. The install runbook's equivalence rule applies: the kit
is accepted when its sums equal the reference kit's, or equal them except those two lines with manifests that differ only in
`git_sha`.

**The baseline is the installed Ghost kit.** The Ghost update (U2) was installed from the tree this branch is stacked on, so the
kit of that tree (the same 58 files; the same two commands give
`ec9f31955ef635e8bf3f02c690f26b86cfecb5982f5b497796085196c7612525` without `--git-sha` and
`41fe3ab03b9222dcba476af9d1afdf7ea2bda8dd8b00ea3bef6485c3b0ae4ac1` with the fixed reference) is what is on the host. The suite
rebuilds it from the history and compares it with the two rows above: where the checkout does not hold that history it prints SKIP
for the comparison and counts it as neither a pass nor a failure, and the documents' own pins stay what they are. Against it this
kit has no file new, none removed and five changed (2.2).

These numbers hold for the kit sources as reviewed, built on the installed Ghost code. Any change of a kit source changes them: the
suite fails and this document is updated in that change, and the reviews, the L3 run (P1) and the owner's acceptance are repeated.
**Why the stacking matters:** a kit built from the U3 commits alone (without U2's code, 53 files) installed over the Ghost kit would
remove U2's five new files and revert its four changed sources: the comparison of 8.1 (block 2) would list them as REMOVED and
step 1 stops. That stand-alone build is not what this document describes; the numbers above are not those of it. A commit that
changes only documents or suites changes neither a kit source nor the rows above: the kit built from it differs from the L3-tested
kit in the two `VENDOR_MANIFEST.json` lines only, and the build comparison of step 0 proves that each time.

**The three site facts** (the `site` block of the site file; all three or none; they are judged by the loader, never by the owner's
eye):

| Site fact | Meaning | Bound (inclusive) |
|---|---|---|
| `inverter_dc_to_ac_factor` | share of the net DC-side power (PV + battery) that reaches the AC side while that power is not negative | 0.90 to 1.0 |
| `inverter_ac_to_dc_factor` | share of the AC power that reaches the DC side while the net DC-side power is negative (the battery charges) | 0.90 to 1.0 |
| `inverter_standby_w` | the inverter's own draw, taken off the AC side | 0 to 100 W |

All three absent (or null) is the lossless rule, the default. Present means all three, each a finite number inside its bound.
Anything else (one or two of the three, a string, true or false, a list, an object, a number outside its bound) is reported and never read as a looser rule: the loader WARNs `SITE_INVERTER_CONVERSION`, and the engine judges
the balance lossless and BLOCKs the two outputs with `POWER_LOSS_FACTS_INVALID`. A JSON integer too large for a float is not a fact problem but a malformed file: the loader refuses the whole file (`SITE_FILE` FAIL), and the placement tool and the site-check refuse it before it reaches the host. The bounds are PROPOSED engineering suggestions,
not owner values (D-U3-9). What a wrong set inside the bounds can still hide is stated in section 12 and in
[`DATA_QUALITY_METHOD.md`](DATA_QUALITY_METHOD.md) section 10.1.

## 4. The owner's acceptance items

Decisions are the owner's. This table lists them; it decides none. "Open" means no ruling is recorded.

| # | Item | What it is, as built | Status |
|---|---|---|---|
| D-U3-1 | the order against U2 (Ghost) | U3 follows U2 in a window of its own, after U2's close-out, and the commit it installs from holds U2's code (this branch is stacked on the commit U2 was installed from); U2's advice log keeps withheld Dump rows until U3 takes effect | **open**: the owner chooses; never both in one window |
| D-U3-2 | the commit to install from | a commit whose kit sources are this branch's, on top of everything already installed, after green CI and the owner's M2 scan: the squash commit on main or the branch tip | **open**: the commit is the owner's choice |
| D-U3-3 | the restart | one restart, short, approved separately, the owner watching, in daylight (the after-checks need real PV or battery flow); an outage of more than about 5 minutes sets the supervision latch (install runbook 6) | **open**: the owner chooses the window |
| D-U3-4 | when the facts take effect | the kit first, one restart, then the facts placed and a separately approved config-entry reload (a reload, not a second restart), all in one window; the alternative is to place the facts before the restart so the one restart reads both (no reload, but the kit's first start is also the facts' first start) | **open**: the owner chooses; this runbook describes the first |
| D-U3-5 | the acceptance rule for the facts | the fit run on the newest recorded data; the proposed facts printed and not marked NOT USABLE, inside the bounds; the loss-aware rule accepting at least 99 % with no WARNING line; the hold-out second part accepted; every reversal that matters blocked in the loss-aware rows; the facts entered as printed, never edited by hand | **open**: the owner reads the rows of 8.0 and rules |
| D-U3-6 | the recalibration rule | re-fit at every season change (the PV share rises), after any change of the inverter, its settings, a CT or a sensor, and when `POWER_BALANCE_INCONSISTENT` returns on the two outputs while every input is fresh; the new facts pass the same acceptance rule and are placed with their own go | **open** |
| D-U3-7 | data quality that stays DEGRADED | not a failure of U3: the codes are read (8.13), no rule is loosened and no fact is edited to reach OK; any other cause is a separate item | **open** |
| D-U3-8 | the legacy-device clean-up | separate from U3 and not in its window: leave, move the Energy dashboard to the dongle's totals, disable the one enabled legacy automation, or remove after a backup are each the owner's later decision | **open** |
| D-U3-9 | the bounds | 0.90 to 1.0 for the two factors and 0 to 100 W for the standby draw (PROPOSED: an engineering suggestion, not an owner value); a change is a code change, so a new kit, new hashes and the reviews, P1 and this document repeated | **open**: confirm or change |

## 5. Preconditions

The update is **NOT READY** while any line below is OPEN. At the time of writing the OPEN lines are P4, P5 and P7. P1 is closed for
the Home Assistant Core and Python versions its run was made on and reopens for any other (U3-G5, section 6).

| # | Precondition | Status |
|---|---|---|
| P1 | **The L3 (WSL) kit-equivalence reference run, on the exact kit.** It must show, on the isolated test instance pinned to a Home Assistant Core and Python version that U3-G5 compares with the host's: (a) the exact kit (this branch, stacked on the installed Ghost code) installs through the same route (`deploy-ha-kit.ps1 -Target Test`; as an Upgrade over the previous kit, which is the Ghost kit, where the run can), Home Assistant loads it, no FAIL in the self-test, the eleven entities and no suffix; (b) a site file with a valid set of facts placed with `place-ha-site-file.ps1 -Target Test` and the entry reloaded: `SITE_INVERTER_CONVERSION` PASS in the download, and with synthetic loss-affected inputs the two outputs are not blocked by `POWER_BALANCE_INCONSISTENT` where the same inputs without the facts are; (c) an invalid set, induced on the isolated instance only (never on production): WARN and the two outputs BLOCKED with `POWER_LOSS_FACTS_INVALID`; (d) **the previous kit restored on the isolated instance loads with a site file that still holds the facts** (no FAIL and no `SITE_INVERTER_CONVERSION` line): the reading of 7.1 observed in a real Home Assistant; (e) the config-entry reload observed there, with the download taken before it; (f) at least three slot cycles with cycle times inside the install runbook's bounds and no blocking-I/O or slow-callback warning from the integration; (g) the run's `SHA256SUMS` sha256 recorded: it is `-ReferenceSumsSha256` of the production run | closed 22 Nov 2026: the stacked kit (the kit these documents pin; a later commit that changes only documents or suites builds the same kit but for its two `VENDOR_MANIFEST.json` lines) ran on the isolated test instance pinned to Home Assistant Core 2026.11.0 and Python 3.14.10: (a) to (f) passed, with the limits of section 12, and (g) is recorded offline (P9); the run's result is kept in the private project record, not here. **The closure holds only for those two versions.** U3-G5 requires the host's Core and Python to equal them: after ANY Core or Python update of the host the run is repeated on the new versions and P1 reopens until it has been. That run did not read the production versions. A run on the stand-alone kit of this branch (before it was stacked on Ghost) was a precursor and did not close it |
| P2 | independent review of the code (the loss-aware expectation, the bounds, the loader, the fitting tool), findings fixed, the kit unchanged since the reviewed build (proven by the build comparison of section 3) | closed (offline, lean mode, per the project record of 22 Nov 2026): one independent review, no BLOCKER, one MAJOR (the factor bounds were too wide) and five minors, all fixed in a follow-up round (the bounds tightened, a huge integer fact reported and never raised, the rule-set version bumped, the native-load false-zero rule pinned with facts configured, mutants of the real source added); the record names no second review |
| P3 | independent review of these documents and their suite | closed 22 Nov 2026: one independent review (lean mode) of the documents as stacked on Ghost (the Ghost baseline, the file counts, the pins, the drills) found no BLOCKER, no MAJOR and one MINOR, fixed in the suite and pinned by mutants (the commit id named in P6 was only skipped when it did not match the history; it is now checked, rule 28 of the suite); the stand-alone version had been reviewed before, its findings fixed. What no reviewer has read: the edits made after that review (the closure of P1, P3 and P9, the limits of the L3 run in section 12, and the wording of what a restart does to the state folder with the one state read added to step 8); the suite pins them |
| P4 | CI green on the exact commit (the branch has not been pushed and has no pull request) | **OPEN**: closed only by a green run on the exact commit; any later commit repeats it |
| P5 | the owner's M2 private-pattern scan on the exact commit, generated assets, commit metadata and pull request text included | **OPEN**: runs before any push; any later commit repeats it |
| P6 | U2 (Ghost) installed and verified first, its installation record filed, and the commit installed holds its code (section 3), or the owner deliberately decides U3 is independent of it; never both in one window | closed 22 Nov 2026: Ghost installed from 87f26df; this branch is stacked on that commit, so the kit of this update holds U2's code (section 3); U3 is still a window of its own, after U2's close-out |
| P7 | the owner's rulings on D-U3-1 to D-U3-9 recorded | **OPEN** |
| P8 | the offline gates green on the exact commit: the suites, the kit build comparison, the mock-root drills with this kit and the PowerShell parse (step 0) | closed on the stacked commit these documents were written on (22 Nov 2026): the engine and runtime roots, the repository validation, the public privacy suite and the deploy suite, all green on the tree stacked on Ghost; this document's suite and the Ghost documents' suite, both builds equal to the pins and the Ghost kit rebuilt from the history; the drills of 8.0 with the installed Ghost kit as the previous kit (install, place the facts, upgrade, roll back, uninstall) and the scorecard file with U2's two tables byte-identical through them; repeated in full at step 0 on the commit that is installed |
| P9 | the reference kit and its `SHA256SUMS` sha256 from P1 recorded offline (the Production route refuses without them) | closed 22 Nov 2026: the reference kit and its `SHA256SUMS` sha256 of the L3 run are recorded offline in the private project record; they are not in this repository, so the `-ReferenceKit` and `-ReferenceSumsSha256` placeholders of the Plan and Upgrade lines stay placeholders here, and the coordinator fills them from the offline record. P9 follows P1: when P1 reopens (U3-G5) and the run is repeated, the new reference kit and sums are recorded again and replace these |

## 6. Go / no-go on the day

Go only when **every** line holds; otherwise stop: this is a no-go. These are the install runbook's gates G2 to G6, G8 and G9 as
they apply to an upgrade, and its G7 for a site file that already exists.

| # | Criterion |
|---|---|
| U3-G1 | section 5 is closed and the owner's final installation go is given on the checklist; the commit is the one P4 and P5 ran on |
| U3-G2 | the owner has reserved a quiet period, is present, and no other supervised live step is in progress (U2 and U1 included) |
| U3-G3 | the owner has made a fresh **protected** full backup in the Home Assistant UI (step 2). A backup made over SSH is full but UNPROTECTED: no session handles a backup encryption password |
| U3-G4 | the baseline (step 1) shows supervision SUPERVISED and stable with the heartbeat age nominal, every write enable, arm and schedule off, the manual write counter noted, Intelligence SHADOW with a fresh result, the pause helper's state noted and the config entry loaded; the three outputs' states and blockers are noted, taken while PV or battery power was large |
| U3-G5 | the host's Home Assistant Core and Python versions, re-read read-only, equal the versions the L3 run pinned (P1: Core 2026.11.0, Python 3.14.10). If either differs after ANY Core or Python update, this is a no-go: the L3 run is repeated on the new versions, P1 reopens until it has been, and the reference kit and sums of P9 are recorded again |
| U3-G6 | the kit verifies against its `SHA256SUMS`, is equivalent to the L3-tested kit, the offline suites are green and the mock-root drills pass (step 0) |
| U3-G7 | the baseline of step 1 is saved: every listing and copy is in `<OFFLINE_EVIDENCE_DIR>`; the installed `runtime/gates.py` has the hash the old-loader reading of 7.1 was made on; the owner's offline copy of the site file now on the host has the same sha256 as the live one |
| U3-G8 | the facts are accepted by the rule of D-U3-5 on the fit of 8.0, the new site file passes the site-check (exit 0, the PASS line), and its sha256 is recorded in `<OFFLINE_EVIDENCE_DIR>` |

## 7. The steps

| Step | What | Who | Offline / live | Read-only / write | Own owner authorisation | Expected result | Stop condition |
|---|---|---|---|---|---|---|---|
| 0 | offline gates on the exact commit: the suites, the kit build and compare (8.0), the drills on a marked mock root, the fit of the facts, whose rows the owner reads, and the site-check of the new site file (8.0), the PowerShell parse, section 5 | COORDINATOR | offline | no live access | not a live step | hashes as pinned (section 3), the drills PASS, the facts accepted by D-U3-5, site-check exit 0 with its PASS line | any new failure; a hash that is not the pinned one; facts not accepted; a changed commit repeats the gates and the scans |
| 1 | live read-only baseline: Core and its version, the integration folder listing (hashes and sizes), the state folder listing, the site file's sha256 on the host, the log lines, the owner's UI reads of the status and of the three outputs, and the diagnostics download taken before the restart (8.1) | COORDINATOR (reads), OWNER (UI reads and the download) | live | read-only | **yes** (a live read) | every listing saved; Core running; U3-G4 and U3-G7 hold; the comparison with the kit is as 2.2 says | Core not running; Intelligence not SHADOW or not fresh; supervision not stable; the installed `runtime/gates.py` is not the one 7.1 was read on; the offline copy of the site file differs from the live one; a listing that cannot be read |
| 2 | the owner's protected full backup in the Home Assistant UI; its name and time noted offline, never its password | OWNER | live (UI) | the owner's own backup action | the owner's own action | a protected backup exists | no protected backup |
| 3 | PAUSE: the owner turns the pause helper on (install runbook 10 and 11: pause before an upgrade) | OWNER | live (UI) | **write** (the existing pause helper, as always) | **yes** | the status reads PAUSED; the watchdog stays fresh (PAUSED counts as fresh while the helper is on); no cycle is computed | anything but PAUSED within a few minutes |
| 4 | live read-only: the status reads PAUSED, then, after the longest cycle has ended, the scorecard file's hash and size and the listings again (8.4) | COORDINATOR | live | read-only | **yes** | the state listing is stable across two reads one minute apart | the file changes between these two paused reads |
| 5 | stage the new kit with the repository's own tool and verify hashes: `deploy-ha-kit.ps1 -Action Plan` (read-only), then `-Action Upgrade` (8.5) | COORDINATOR | live | Plan read-only; Upgrade **write** (A1, A3) | **yes**, for the Upgrade separately | `ECCO INTELLIGENCE KIT UPGRADE PASSED`, the backup path printed (record its stamp), `HA check    : passed`, **RESTART REQUIRED - separately gated, not performed** | any failure line; NO CHANGE; a hash mismatch; the tool's own rollback message; ROLLBACK NOT CONFIRMED |
| 6 | live read-only, before any restart: the installed folder equals the kit, the state folder and the site file are untouched (8.6) | COORDINATOR | live | read-only | **yes** | `INSTALLED TREE EQUALS THE KIT`; no line of difference for the state folder; the site file's sha256 is the baseline's | any difference |
| 7 | **the restart**: the owner restarts Home Assistant, once, short, watching; Core running again before and after the checks of 8.7 | OWNER | live | the owner's restart | **yes, its own approval, separate from the Upgrade** | Core running, the integration loads, no repair or error line, the outage well under 5 minutes | an outage of more than about 5 minutes (the latch: a supervised dongle reboot by the owner); the integration does not load; a repair or error line |
| 8 | live read-only, still paused: the load checks of the kit alone, with the site file unchanged, a diagnostics download, and the state folder read again after the restart as the reference for step 9 (8.8) | COORDINATOR (reads), OWNER (the download) | live | read-only | **yes** | status PAUSED; no FAIL in `self_test`; no `SITE_INVERTER_CONVERSION` line; eleven entities, no suffix; watchdog fresh; the same state file names as before the restart (the scorecard file's hash may differ: the restart rewrote three of its pages, 2.4) | a FAIL; a new entity; a `_2` suffix; a `SITE_INVERTER_CONVERSION` line (the facts are not supposed to be on the host yet); another set of state file names or another `store_meta.json` hash |
| 9 | the site file with the three facts: `place-ha-site-file.ps1 -Plan`, then the placement (8.9) | COORDINATOR | live | Plan read-only; the placement **write** (A2, A3) | **yes**, for the placement separately | `ECCO SITE FILE PLACED`, the read-back equal to `-ExpectedSha256`, the backup path printed; the state folder as read after the restart (step 8) | NO CHANGE; STOPPED; a read-back mismatch; the state folder differs from the read of step 8; any message that the restore could NOT be confirmed |
| 10 | **the config-entry reload** (a reload, not a restart), still paused: the owner takes a diagnostics download first, then reloads the ECCO Intelligence entry in the UI (8.10) | OWNER | live (UI) | the owner's reload | **yes, its own approval, separate from the placement** | the entry loads again, status PAUSED, no repair or error line | the entry does not load; a repair or error line; `SELF_TEST_FAILED` |
| 11 | live read-only, still paused: the load checks with the facts and a diagnostics download (8.11) | COORDINATOR (reads), OWNER (the download) | live | read-only | **yes** | `SITE_INVERTER_CONVERSION` PASS; no FAIL; the status entity's `config_hash` equals the site-check's | a WARN or a FAIL; no `SITE_INVERTER_CONVERSION` line; a different `config_hash` |
| 12 | UN-PAUSE: the owner turns the pause helper off; the status goes to STARTING, then a computed one after the start-up grace | OWNER | live (UI) | **write** (the pause helper) | **yes** | a computed status, SHADOW | `SELF_TEST_FAILED`; no computed status after the grace |
| 13 | after-checks within the first slot cycles (at least the next two slot times), read while PV or battery power is large: status SHADOW and fresh, the two outputs, data quality, no new entity, no error or budget line, nothing else changed (8.13) | COORDINATOR (reads), OWNER (downloads) | live | read-only | **yes** | the checks of 8.13 | any of the stop lines of section 9 |
| 14 | close-out: the evidence is filed offline; the status update; a post or a push only on the owner's go | COORDINATOR | offline | local files and local commits | **yes** for a post or a push | evidence filed | none |

No step restarts Home Assistant except step 7, which is the owner's. Step 10 is a reload of the one config entry and is not a
restart. A step that would need a second restart is out of scope and stops the update.

### 7.1 The order, and why

**The old loader does not refuse the facts.** The question that decides how careful the order must be is whether the previous
kit, which is what a rollback restores, refuses a site file that carries these three keys. It does not. Read from the sources: the
previous loader (`runtime/gates.py`, `load_site`) reads the site file as one JSON object and takes from its `site` block only the
PV array size (and notes two reserve hints); the only strict parts are the `decisions` block and the `shadow_runtime` entity map;
no code in the previous loader rejects, counts or reports another key of the `site` block. The new loader reads the three keys by
name and adds one check. One offline experiment of this preparation (scratch only, synthetic data) ran the
merged base's loader on a site file whose `site` block held the three keys valid, partial, out of bounds, of the wrong types and
null: every load gave no FAIL, no extra check and the same decisions, entity map and array size as the file without them. The
Ghost update's loader is the same file as the merged base's (checked by a diff during this preparation, recorded and not pinned),
and the previous kit of this branch is the Ghost kit, so the reading is about the loader that is installed. The suite pins what
makes it true of the new tree (the keys are read only by name, no code refuses an unknown key of the `site` block) and, where the
checkout holds the history before this change (the Ghost tree), repeats the experiment on that tree and compares the previous
kit's loader hash with the one step 1 reads; in a checkout without that history (a shallow clone) the suite prints SKIP for these
two checks and counts them as neither a pass nor a failure. The reading is about the loader, not about
the whole previous integration: P1(d) showed the previous kit as a whole on such a file, in a real Home Assistant Core on the
isolated test instance (22 Nov 2026): the Ghost kit, restored over a site file that still held the facts, loaded (no FAIL, no
`SITE_INVERTER_CONVERSION` line) and ignored them, so the two outputs were blocked with `POWER_BALANCE_INCONSISTENT` again: safe,
but the correction is silently lost, which is why the clean order stays (the facts out first, then the previous kit). That was not
observed on the production host.

**So no order refuses a file or fails a start-up from this cause.** The new kit with the unchanged site file is the old rule bit for
bit (absent facts are lossless; the L2 suites compare the two over thousands of sets), and the previous kit with the new site file
ignores the keys. The order of this runbook is chosen for what it separates and for the direction of the risk:

1. **Kit first, one restart, then the facts.** The only restart carries the kit alone, whose behaviour with the unchanged site file
   is the old one: step 8 is a checkpoint at which nothing but the code has changed. The facts then arrive by a placement and a
   reload, so a problem is assigned to the kit (step 8) or to the facts (step 11), and the rollback has a stopping place between them.
2. **The facts are the loosening step.** They make the check accept what the lossless rule blocked, so they come last on the way in
   and go first on the way out: the stricter state is the one that is kept if any step stops half-way.
3. **The facts take effect only at a reload or a restart.** The placement tool says so itself (`Takes effect: only at a config-entry
   reload or a restart, each separately gated; neither was performed`), and the integration reads the site file at start-up and at a
   reload only (install runbook 3). So the placement changes nothing live by itself, and the reload is its own approval.
4. **The pause stays on from step 3 to step 12.** The restart and the reload both happen paused, so no cycle runs on a half-applied
   state, and the kit's lazy imports cannot load new modules into the old process before the restart.

**The other order is allowed, not recommended** (D-U3-4): the facts placed before the restart, so that the one restart reads both
and no reload is needed. It saves the reload, but the kit's first start is then also the facts' first start and the checkpoint of
step 8 does not exist. The owner chooses; this runbook and the checklist are then re-issued for that order.

**The rollback runs the other way** (section 10): the facts out first (the site file put back to the baseline's bytes), then the
previous kit, then one restart. The previous kit would load with the facts left in the file (above), so the order does not decide
whether the old kit starts; it is kept because the stricter rule is restored first, the proofs compare the site file's sha256 with
the baseline's, and a rollback that stops half-way leaves the stricter state. Putting the previous kit back first would work too
and would leave the facts in the file until they are taken out.

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

The tool prints `built custom_components/ecco_intelligence with 36 vendored modules and 20 integration files; 58 files; SHA256SUMS sha256 <hash>` and a `status:` line; the `Get-FileHash` line prints the same hash again, and it must equal the fixed-reference row of section 3. The same
command without `--git-sha` (into a second new directory) must give the first row. If either differs, stop: the checkout is not
the reviewed one (3 says why the kit must be the one stacked on U2).

Then build the kit that will be installed, with the commit it is installed from, and record its `SHA256SUMS` sha256 offline (it is
`-ExpectedSumsSha256` of every run with it):

```powershell
cls
$PY = '<PY>'
$KIT = '<absolute kit directory for the install, outside the repository, new or empty>'
Set-Location <checkout>
& $PY -I -B -X utf8 tools\build_ha_integration.py --out $KIT --git-sha (git rev-parse HEAD)
& $PY -I -B tools\ecco_intel_drill.py runbook --kit $KIT
(Get-FileHash -Algorithm SHA256 (Join-Path $KIT 'SHA256SUMS')).Hash.ToLower()
```

`runbook --kit` verifies the kit and exits 1 when it does not verify. Drill install, upgrade, rollback and uninstall on a marked
mock root, **with the previous kit installed first and this kit as the upgrade**, which is the order of the live steps (install
runbook 2; the root must contain the marker file, and the drill refuses any other directory). `<previous kit>` is the installed
Ghost kit: built the same way from the commit that is installed on the host now (U2's):

```powershell
cls
$PY = '<PY>'
$PREV = '<the previous kit: built from the commit installed now>'
$KIT = '<the install kit above>'
$MOCK = '<an empty temporary directory>'
Set-Location <checkout>
New-Item -ItemType Directory -Force (Join-Path $MOCK 'ecco\intelligence') | Out-Null
Set-Content -Encoding utf8 (Join-Path $MOCK '.ecco_mock_config_root') 'mock'
& $PY -I -B tools\ecco_intel_drill.py drill --config-root $MOCK --kit $PREV --upgrade-kit $KIT
```

**What the drill proves, exactly.** On a mock root, the swap steps (install, upgrade, rollback, uninstall) leave the site file, the
state folder (with whatever scorecard file it holds) and every other integration byte-identical: their hashes are compared before
and after each step. The suite of this runbook repeats that with a synthetic site file that holds the three facts, placed on the
mock root between the install and the upgrade by a plain file copy (the drill has no placement step: the placement tool needs ssh
and never runs offline), and checks that the tree after the rollback equals the previous kit's. Its state folder holds a real
scorecard file with both of U2's tables (`advice_log` and `advice_incident`), so the byte-identity covers the file the Ghost update
made; where the history is in the checkout the previous kit installed first is the real Ghost kit, otherwise a synthetic copy of
this kit. The placement tool's own logic
(its local checks, the backup, the upload, the read-back and its rollback messages) is exercised against a stand-in host by
`tools/tests/Test-EccoDeploy.ps1`; that is a stand-in, not the production host. The drill does **not** run the previous
integration as a whole on a site file with the facts; the previous loader alone was run on one (7.1), and P1(d) showed the rest on
the isolated test instance. The drill restarts nothing, so it says nothing about what a restart does to the state folder (2.4).
It never touches a real Home Assistant.

**The facts, offline.** The fit needs a recorded history of the four readings (the house power, the PV power, the battery power and
the grid power): a CSV of time-aligned samples or the Home Assistant history JSON, one file per reading and period. Reading that
history from Home Assistant is a live read-only action with its own authorisation; no tool of this runbook does it, and the files
stay in `<OFFLINE_EVIDENCE_DIR>`. Step 0 uses the history already held there; a newer history read, if the owner wants the fit repeated on newer data, is one more live read-only action taken with step 1, with its own authorisation. The fitting tool reads the files it is given, prints a report and writes nothing:

```powershell
cls
$PY = '<PY>'
$E = '<OFFLINE_EVIDENCE_DIR>\u3-facts'
Set-Location <checkout>
& $PY -I -B -X utf8 intelligence\tools\power_balance_fit.py ha-history --house "$E\house.json" --pv "$E\pv.json" --battery "$E\battery.json" --grid "$E\grid.json" | Out-File -Encoding utf8 "$E\fit-output.txt"
Get-Content "$E\fit-output.txt"
```

For a CSV history use `power_balance_fit.py csv --file <file>` instead. **The rows the owner reads** (D-U3-5), in the tool's own
words:

1. Part (a) prints the proposed facts as `proposed site facts (the site block of the site file), rounded as entered` on one line.
   If it prints `NOT USABLE as site facts`, or the values lie outside the bounds of section 3, the facts are not used.
2. Part (b), the `loss-aware rule (proposed facts)` row, must accept at least 99 % of the samples; below that the tool prints a
   `WARNING` line (the history probably holds a sign fault, a mixed regime or a reading problem) and the facts are not used until
   the history is reviewed.
3. Part (c), **the fault-injection rows**: for the grid CT sign reversed and for the battery sign reversed, the row
   `loss-aware rule (proposed facts)` must block every reversal that matters, in its `all` column and in its
   `accepted before the fault` column (a rule that blocks most samples anyway detects nothing, so the second column is the one that
   counts). The row `loss-aware at the bounds (not a fit)` is not a fit: it shows what the bounds alone could hide, and it is read,
   not assumed.
4. Part (d), **the hold-out rows**: the facts fitted on the first part, judged on the second: the `second part, loss-aware` row must
   accept (nearly) every sample, and the `second part, CT sign reversed` and `battery sign reversed` rows must block every
   reversal that matters.

The tool's output holds site values: it stays in `<OFFLINE_EVIDENCE_DIR>`. The facts that pass are entered in a **copy** of the
site file: the three keys in the `site` block, as printed, saved without a byte-order mark (install runbook 3), as a new file next
to the offline copy of the file now on the host, which is kept unchanged:

```json
"site": {
    "...": "the keys already there stay as they are",
    "inverter_dc_to_ac_factor": <as printed by the tool>,
    "inverter_ac_to_dc_factor": <as printed by the tool>,
    "inverter_standby_w": <as printed by the tool>
}
```

Check the new file with the site-check of the commit that is installed, and record its sha256 before it goes anywhere:

```powershell
cls
$PY = '<PY>'
$SITE = '<the new site file, outside every repository>'
Set-Location <checkout>
& $PY -I -B tools\ecco_intel_drill.py site-check --site $SITE
$LASTEXITCODE
(Get-FileHash -Algorithm SHA256 $SITE).Hash.ToLower()
```

It must exit 0 and print the load check `PASS  SITE_INVERTER_CONVERSION` and `Result      : OK`; the two outputs then read
`LIVE_INPUTS_DECIDE` (or a blocker that is not `POWER_LOSS_FACTS_INVALID`). A file that is not usable gives `PROBLEMS`, exit 1, and
`POWER_LOSS_FACTS_INVALID` on the two outputs. The placement tool refuses every file the loader refuses as a whole (a byte-order mark, a non-finite number, an integer too large for a float) but does not judge the three facts themselves: invalid facts are only a WARN in the loader and would be placed. The site-check (U3-G8) is what catches them, so it runs on the new file before every placement. The
`config_hash` it prints is what the status entity's `config_hash` attribute shows once the file is loaded (step 11).

Run the offline suites of install runbook 2 on the exact commit (the runtime root and the engine root, one at a time):

```powershell
cls
$PY = '<PY>'
$env:PYTHONDONTWRITEBYTECODE = '1'
Set-Location <checkout>
& $PY -X utf8 -I -B tools\run_offline_tests.py --root custom_components/ecco_intelligence/tests --parallel 1
& $PY -X utf8 -I -B tools\run_offline_tests.py --root intelligence/tests --parallel 1
```

Then the suite of this runbook (it also runs inside the runtime root), `tools/validate_repo.py`, the public privacy suite and the
deploy suite `tools/tests/Test-EccoDeploy.ps1` (one heavy run at a time). The owner's M2 scan is the owner's tool and runs on the
exact commit (P5).

### 8.1 Step 1: the live read-only baseline

A live read; it needs the owner's authorisation in the session. Everything is written to `<OFFLINE_EVIDENCE_DIR>`, never to a
repository. The same listings are read again in steps 4, 6 and in the rollback, so the sets can be compared.

**Block 1: Core, the integration folder, the state folder and the site file.** The listings are captured as text exactly as the
host prints them, with the console encoding set first, and saved without any edit (byte-exact copies). `<the offline copy of the
site file now on the host>` is the owner's own file, kept unchanged for the whole update:

```powershell
cls
$H = '<production alias>'
$E = '<OFFLINE_EVIDENCE_DIR>\u3-baseline'
$COPY = '<the offline copy of the site file now on the host>'
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
ssh $H "sha256sum /config/ecco/intelligence/site.local.json | cut -d ' ' -f 1" | Out-File -Encoding utf8 "$E\site-file-sha-before.txt"
.\tools\ha-logs.ps1 -SshHost $H -Lines 400 -Pattern ecco_intelligence 6>&1 | Out-File -Encoding utf8 "$E\log-before.txt"
(Get-Content "$E\integration-before.txt" | Measure-Object).Count
$LIVE = (Get-Content "$E\site-file-sha-before.txt" | Select-Object -First 1).Trim()
$HAVE = (Get-FileHash -Algorithm SHA256 -LiteralPath $COPY).Hash.ToLower()
if ($LIVE -ceq $HAVE) { 'THE OFFLINE COPY EQUALS THE SITE FILE ON THE HOST' } else { 'DIFFERENT: stop' }
```

The count line is the number of files in the installed folder: it must be 57, the installed Ghost kit's count (U2 is installed), and
U3 changes it by nothing; any other number is explained before going on. The hash read of the site
file is the command the placement tool itself runs on the host (`sha256sum` of that one path); it shows no content. `ha-status.ps1`
and `ha-logs.ps1` are the repository's read-only tools; the `find` and `ls` reads are new combinations of commands the deploy tools
themselves use and have not been run on the production host (section 12). The state folder's hash is read in step 4, with the
integration paused, because the file is written once per slot cycle while the integration runs.

**The loader guard.** The listing's line for `./runtime/gates.py` must show the sha256 the old-loader reading of 7.1 was made on:
`659239f3cca7393d3e82b779a504075c9b6291403195923757712016f591305b` (the installed Ghost kit's file, the same file as the merged base's kit). If the
installed loader is another file, that reading does not cover it: stop, and read the installed loader against 7.1 before any write.

**Block 2: what will change (offline, on the saved listing).** Compare the baseline with the kit's `SHA256SUMS`:

```powershell
cls
$E = '<OFFLINE_EVIDENCE_DIR>\u3-baseline'
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

Expected, with the installed folder the Ghost kit and this kit built on top of it: 0 ADDED, 5 CHANGED
(`_vendor/intelligence/advisory_contract.py`, `_vendor/intelligence/quality.py`, `_vendor/intelligence/site_decisions.py`,
`runtime/gates.py` and `VENDOR_MANIFEST.json`) and 0 REMOVED (section 2.2). **Any REMOVED file means the kit does not contain
what is installed (U2 would be undone): stop.** Anything else is a stop until it is explained.

**The owner's reads in the Home Assistant UI** (the install runbook reads them the same way; each is noted offline): Intelligence's
status entity reads a computed status with `mode` SHADOW and `applies_nothing` true and a recent update; the freshness entity and
the watchdog read fresh; the pause helper's state is noted; the integration's page shows one loaded entry and no repair; supervision
reads SUPERVISED and stable with the heartbeat age nominal; every write enable, arm and schedule is off and the manual write counter
is noted (install runbook G4). **The thing being fixed is read too:** the states, the `blockers` and the `reason_codes` of the Dump
to Grid output, the export-event output and the data quality entity, with the time and with PV and battery power at that moment
noted (the baseline is informative only while the flow is large, as in the diagnosis). Then the owner downloads the diagnostics
(Download diagnostics) and saves the file as `diagnostics-before.json` in the evidence folder: `cycle_stats` lives in memory and the
restart empties it (install runbook 8), so this is the only record of the run before the restart.

### 8.2 Step 2: the owner's protected backup

The owner makes a full backup in the Home Assistant UI with a protected (encrypted) option, notes its name and time in
`<OFFLINE_EVIDENCE_DIR>`, and keeps the password out of every chat, file and repository. The coordinator never asks for it and never
makes a backup over SSH as a substitute (the deploy tool's own backup, `/config/ecco-backups/<stamp>/`, holds a copy of the
installed integration folder only, and the placement tool's backup holds a copy of the site file only: they are conveniences for the
rollback, not a backup of the state folder).

**What restoring this backup would do (said plainly, because it is the last resort and never the first rollback).** A full backup
holds the configuration folder, so the site file, the scorecard file and `store_meta.json` as they were when it was made (recalled,
not verified). Restoring it is a heavy action and the owner's decision: as the Home Assistant interface offers it (recalled, not
verified on this host) it restarts Home Assistant and returns everything the backup holds to its state at that time, so whatever
changed or was recorded since (settings, helper and control states, the history the recorder kept, the scorecard rows the
integration recorded, anything an add-on or the owner changed meanwhile) goes back with it. The rollback of section 10 undoes only
this update, with at most one restart.

### 8.3 Step 3: pause

The owner turns the pause helper on (the install runbook's pause, section 10 there: "never a restart"). The status reads PAUSED,
nothing is computed, and a cycle already running is discarded when it ends. Wait until the longest cycle's time budget has passed
(about two minutes) before step 4. The pause stays on until step 12.

### 8.4 Step 4: the paused read

```powershell
cls
$H = '<production alias>'
$E = '<OFFLINE_EVIDENCE_DIR>\u3-baseline'
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

`state-paused-1.txt` holds the scorecard file's hash and size: the reference for step 6, which is read before the restart (the file
itself is in the owner's protected backup). It is not the reference for step 9: a restart rewrites three scorecard pages, so step 8
reads the folder again after the restart (2.4). A write in flight when the pause began would show as a difference between the two
state reads: stop and read again.

### 8.5 Step 5: stage and swap with the repository's own tool

`Plan` is read-only. Before any ssh call it requires a clean working tree and runs the repository validation with the given
`-Python`, then verifies the kit locally (its `SHA256SUMS` against `-ExpectedSumsSha256`, `git_sha` equal to this checkout's HEAD, a
byte-identical rebuild, equivalence to the reference kit). It then reads the host and prints the target, the resolved `/config`
root, the dashboard preservation gate and its pin, the Core version check, the installed tree, the free space, the site file's hash
prefix, the state folder, the config-entry count, every destination, the swap, the restart line and the rollback command. Read it
fully, then give the go for the Upgrade:

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

The Upgrade stages under `/config/ecco/staging/<stamp>/` (never inside `custom_components/`), verifies the staged copy on the host,
backs up the installed folder to `/config/ecco-backups/<stamp>/` and verifies the backup against its `BACKUP_SHA256SUMS`, swaps by
atomic rename (the replaced tree moves under the staging folder; nothing is deleted), verifies every file in place, and runs
`ha core check`. A failure from the swap on goes through the tool's one rollback routine ("was rolled back" only when verified).
**Record the stamp it prints in the backup line: it is the `-BackupStamp` of the rollback** (its `To undo` line repeats the rollback
command with the stamp in it, but without `-Python`: add the same `-Python` as the Upgrade used). The tool never restarts Home
Assistant and tells you to keep the pause helper on until after the restart (lazy imports could otherwise load new modules into the
old process).

### 8.6 Step 6: the installed folder equals the kit

```powershell
cls
$H = '<production alias>'
$E = '<OFFLINE_EVIDENCE_DIR>\u3-baseline'
$KIT = '<the install kit>'
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
$OutputEncoding = [Console]::OutputEncoding
ssh $H "cd /config/custom_components/ecco_intelligence && find . -type f ! -path '*/__pycache__/*' -exec sha256sum {} +" | Sort-Object | Out-File -Encoding utf8 "$E\integration-after-swap.txt"
ssh $H "cd /config/ecco/intelligence/state && ls -l | grep -v '^total' && sha256sum *" | Out-File -Encoding utf8 "$E\state-after-swap.txt"
ssh $H "sha256sum /config/ecco/intelligence/site.local.json | cut -d ' ' -f 1" | Out-File -Encoding utf8 "$E\site-file-sha-after-swap.txt"
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
'--- site file against the baseline (no output means untouched):'
Compare-Object (Get-Content "$E\site-file-sha-before.txt") (Get-Content "$E\site-file-sha-after-swap.txt")
```

Expected: `INSTALLED TREE EQUALS THE KIT (57 files)` and no line for the state folder or the site file: nothing wrote while the
integration was paused and the tool never touches either. No restart has happened yet, so here the state folder is still
byte-identical to the paused read of step 4 (after the restart it is not: 2.4).

### 8.7 Step 7: the restart

Custom integrations load at start-up, so Home Assistant restarts **once, only with the owner's explicit approval, separate from the
Upgrade**, while the owner watches. The restart is the owner's action in the Home Assistant UI; no tool in this runbook performs it.
Immediately before: Core is running, the pause helper is on, the owner is present, no other live change is in progress, the
protected backup exists. Keep the restart short: an outage of more than about 5 minutes sets the supervision latch, and recovery is
then a supervised dongle reboot by the owner (install runbook 6). Immediately after: Core running again; the integration page shows
the entry loaded and no repair; the log shows no error line from the integration (step 8 reads it). This is the only restart of the
update.

### 8.8 Step 8: the load checks of the kit alone, still paused

A live read, with the owner's own go. The owner downloads the diagnostics as `diagnostics-restart.json`. Read the load checks
(install runbook 7, step 2) with one offline read of the file:

```powershell
cls
$H = '<production alias>'
$PY = '<PY>'
$E = '<OFFLINE_EVIDENCE_DIR>\u3-baseline'
$F = "$E\diagnostics-restart.json"
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
$OutputEncoding = [Console]::OutputEncoding
Set-Location <checkout>
& $PY -I -B -X utf8 -c "import json, sys; d = json.load(open(sys.argv[1], encoding='utf-8-sig')); d = d.get('data', d); c = d.get('counters', {}); st = d.get('self_test') or {}; print('status', d.get('status')); print('self_test FAIL', [k for k, v in st.items() if str(v).startswith('FAIL')]); print('SITE_FILE', st.get('SITE_FILE')); print('VENDOR_MANIFEST', st.get('VENDOR_MANIFEST')); print('SITE_INVERTER_CONVERSION', st.get('SITE_INVERTER_CONVERSION')); print('budget_exceeded', c.get('budget_exceeded'), 'exceptions', c.get('exceptions')); print('cycle_stats kept', (d.get('cycle_stats') or {}).get('kept'))" $F
.\tools\ha-logs.ps1 -SshHost $H -Lines 400 -Pattern ecco_intelligence 6>&1 | Out-File -Encoding utf8 "$E\log-restart.txt"
```

Expected while paused: status PAUSED; `self_test FAIL []` (the VENDOR_MANIFEST check passes on the new kit, SITE_FILE passes);
**`SITE_INVERTER_CONVERSION None`** (the site file has no facts yet, so the loader adds no such check: the new kit behaves as the old
one by design, so this download cannot show that the new code runs); `cycle_stats kept` small or 0 (the restart emptied it, which
shows the process restarted); `budget_exceeded` and `exceptions` 0. The owner also confirms the entities: exactly eleven, no `_2`
suffix, the watchdog fresh and no `ecco_intel` notification (install runbook 7). The keys the read uses are those of the
coordinator's diagnostics; the file's outer `data` wrapper is recalled, not verified (`d.get('data', d)` reads either form). **The
proof that the new code is the code that runs is step 11:** only the new loader produces `SITE_INVERTER_CONVERSION`. Keep the file
in the evidence folder.

**The state folder, read again after the restart.** The restart rewrote `store_meta.json` (same content) and three pages of the
scorecard file (same values) through the integration's own start-up (2.4), so the scorecard file's hash can differ from the paused
read of step 4 although nothing was added or lost; that is not a stop. Read the folder once more now (still paused, so nothing
writes until the un-pause or a reload) and keep the read: it is the reference for step 9, and it is not compared with the read
of step 4 byte for byte:

```powershell
cls
$H = '<production alias>'
$E = '<OFFLINE_EVIDENCE_DIR>\u3-baseline'
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
$OutputEncoding = [Console]::OutputEncoding
ssh $H "cd /config/ecco/intelligence/state && ls -l | grep -v '^total' && sha256sum *" | Out-File -Encoding utf8 "$E\state-after-restart.txt"
Get-Content "$E\state-after-restart.txt"
```

Expected: the same file names as `state-paused-1.txt` and no new file; the `sha256` of `store_meta.json` equal to the paused read's; the
scorecard file's `sha256` equal to the paused read's or not (the L3 run saw it differ at every restart; it was not seen on this
host). A different set of file names, or a different `store_meta.json` hash, is a stop (section 9).

### 8.9 Step 9: the site file with the three facts

`-Plan` is read-only; the placement needs the checkout clean, the file outside every repository, and its sha256 equal to
`-ExpectedSha256`. Replacing the file that is there needs `-ReplaceExistingSha256` equal to the live file's sha256 (the value read
in step 1), after a verified backup. Read the Plan fully (the new file's size and sha256, the live file's sha256, the backup path),
then give the go for the placement:

```powershell
cls
$H = '<production alias>'
$PY = '<PY>'
$SITE = '<the new site file, outside every repository>'
Set-Location <checkout>
.\tools\place-ha-site-file.ps1 -SiteFile $SITE -ExpectedSha256 <sha256 of the new site file> -SshHost $H -Target Production `
    -ReplaceExistingSha256 <sha256 of the site file now on the host> -Python $PY -Plan
```

```powershell
cls
$H = '<production alias>'
$PY = '<PY>'
$SITE = '<the new site file, outside every repository>'
Set-Location <checkout>
.\tools\place-ha-site-file.ps1 -SiteFile $SITE -ExpectedSha256 <sha256 of the new site file> -SshHost $H -Target Production `
    -ReplaceExistingSha256 <sha256 of the site file now on the host> -Python $PY
```

Expected: `ECCO SITE FILE PLACED`, `Read back` with the new sha256 matching `-ExpectedSha256`, the backup path of the previous file
(`/config/ecco-backups/<stamp>/config__ecco__intelligence__site.local.json`, a verified copy of the previous file) and the line that
the file takes effect only at a config-entry reload or a restart, neither performed. `NO CHANGE` means the host already holds
exactly this file. A `STOPPED` message names what the tool could and could not confirm; a failure at or after the rename restores
the backup, and the message says when that could NOT be confirmed (S7). Independent proof, read-only:

```powershell
cls
$H = '<production alias>'
$E = '<OFFLINE_EVIDENCE_DIR>\u3-baseline'
$NEW = '<sha256 of the new site file>'
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
$OutputEncoding = [Console]::OutputEncoding
ssh $H "sha256sum /config/ecco/intelligence/site.local.json | cut -d ' ' -f 1" | Out-File -Encoding utf8 "$E\site-file-sha-after-place.txt"
ssh $H "cd /config/ecco/intelligence/state && ls -l | grep -v '^total' && sha256sum *" | Out-File -Encoding utf8 "$E\state-after-place.txt"
$GOT = (Get-Content "$E\site-file-sha-after-place.txt" | Select-Object -First 1).Trim()
if ($GOT -ceq $NEW) { 'THE SITE FILE ON THE HOST IS THE PLACED ONE' } else { 'DIFFERENT: stop' }
'--- state folder against the read after the restart of step 8 (no output means untouched by the placement):'
Compare-Object (Get-Content "$E\state-after-restart.txt") (Get-Content "$E\state-after-place.txt")
```

Nothing is live yet: the running integration holds the site file it loaded at the restart (the one without the facts) until step 10.

### 8.10 Step 10: the config-entry reload

The owner downloads the diagnostics first (`diagnostics-before-reload.json`): `cycle_stats` lives in memory and a reload empties it
(install runbook 8). With the pause helper still on, the owner reloads the ECCO Intelligence entry (Settings, Devices and services,
ECCO Intelligence, the entry's menu, Reload; the screen names are recalled, not verified on this host). It is a reload of one entry,
not a restart: Home Assistant stays up, the entry is unloaded and set up again, and the setup reads the site file. The install
runbook uses the same reload to recover from an entity-id collision (install runbook 7); it does not record that the reload was
run on a real Home Assistant, so P1(e) observed it on the isolated test instance: three reloads, each answered without a restart
being required, the entry loaded again each time and a start-up slot of its own ran (so the integration was not paused in those
observations; a reload with the pause helper on, as here, was not separately observed, and the production host has never run
it). Every start of the integration, a reload included, rewrites a little of the state folder with the same content (2.4).
Expected: the entry loads, the status reads PAUSED, no repair or error line. Never delete and re-add the entry.

### 8.11 Step 11: the load checks with the facts, still paused

The owner downloads the diagnostics as `diagnostics-reload.json`; the coordinator reads it with the block of 8.8 (change `$F`) and
the log again into `log-reload.txt`. Expected while paused: status PAUSED; `self_test FAIL []`;
**`SITE_INVERTER_CONVERSION PASS`** (the download shows the single word); `SITE_FILE PASS`; `budget_exceeded` and `exceptions` 0;
`cycle_stats kept` small again (the reload emptied it). The owner reads the status entity's `config_hash` attribute and compares it
with the `config_hash` the site-check printed for the new file (install runbook, check T8 of its section 8); they must be equal.
A WARN on `SITE_INVERTER_CONVERSION` means the loader found the facts incomplete or invalid, the lossless rule stays in force and the
two outputs are withheld with `POWER_LOSS_FACTS_INVALID` (section 11): stricter than before, never looser. The owner confirms eleven
entities, no `_2` suffix, the watchdog fresh and no `ecco_intel` notification.

### 8.12 Step 12: un-pause

The owner turns the pause helper off. The status changes to STARTING; the first cycle runs after the start-up grace, at the first
poll-driven step or the next minute's tick (install runbook 7, step 3); the first slot cycle comes at the next full hour or 21:30
(local time).

### 8.13 Step 13: the after-checks within the first slot cycles

Wait for at least the next two slot times (allow about two and a half hours), then the owner downloads the diagnostics as
`diagnostics-after-1.json` (and again as `-2` after the second slot cycle), and the coordinator reads each with the block of 8.8
(change `$F`), and the log again with `-Pattern ecco_intelligence` into `log-after.txt`. That block prints only the status, the self-test, the counters and the kept cycle count: read checks 1 (the mode, `applies_nothing`), 2 (the blockers of the two outputs) and 7 (`cadence.refresh_suspended_cpu` and the slot `total_s` p95 and maximum, which the download carries under `cadence` and `cycle_stats`) where the baseline read them, in the owner's UI reads and in the downloaded file. **Read while PV or battery power is
large**, as the baseline was: with little flow the old rule passed too and a clean read proves nothing. Expected, and each a check:

1. **Status as in the baseline, SHADOW, fresh.** `status` is the computed status the baseline showed (OK while the inputs are
   fresh), `mode` SHADOW, `applies_nothing` true; no `SELF_TEST_FAILED`; `budget_exceeded` and `exceptions` 0;
   `SITE_INVERTER_CONVERSION` still PASS.
2. **The two outputs.** The `blockers` of the Dump to Grid output and of the export-event output no longer contain
   `POWER_BALANCE_INCONSISTENT`, and contain neither `CT_SIGN_REVERSED`, `BATTERY_SIGN_REVERSED` nor `POWER_LOSS_FACTS_INVALID`, at the
   reads where the baseline showed the first. They may still read unknown for another reason, with another blocker (a decision
   still open, an input not fresh, a tariff event, supervision): that is not a failure of this update; read the codes. An instant
   with a real balance fault is still blocked, as it should be. **The success criterion is the absence of the balance blocker while
   the inputs are fresh, not a number on the outputs.**
3. **Data quality.** It may be OK now. It may stay DEGRADED: the rule (`quality.py`) is DEGRADED while any item is blocked or any
   finding is a WARN or a BLOCK, so one other open item keeps it so, and the method document says the same (section 10.1: clearing
   the balance blocker does not by itself make data quality OK). That is not a failure of this update (D-U3-7). What to read next:
   the data quality entity's `reason_codes` and each item's `blockers` and `reason_codes`, the status entity's `reason_codes`, and
   the `WARN` lines of `self_test`; each code names its rule in [`DATA_QUALITY_METHOD.md`](DATA_QUALITY_METHOD.md) section 10. Never
   loosen a rule and never edit a fact to reach OK.
4. **No new entity.** Exactly eleven entities with the contract ids, no suffix, the same attribute names as in the baseline.
5. **Nothing else changed.** Supervision stays SUPERVISED and stable with the heartbeat age nominal, every write enable, arm and
   schedule is as in the baseline, the manual write counter is unchanged, the pause helper is off, and the state folder lists the
   same files as the baseline (the scorecard file written once per slot cycle, as before; no new file).
6. **No change of any other published value against the baseline.** The structure is the baseline's; each other item's status and
   reason codes are read against the baseline's for the same inputs, and a difference is explained by the inputs (time, tariff,
   readings), never by this update. Offline, the L2 suites pin the published entities byte-identical to a reference run of the same
   inputs without the facts; live, this is a reading, not a proof.
7. **No error or budget line.** The log shows no warning or error from the integration (in particular no blocking-I/O warning);
   `cadence.refresh_suspended_cpu` false; `cycle_stats` slot rows within the cycle-time bounds of the install runbook's section 7
   go / no-go for the first observed runs (slot `total_s` p95 at most 30 s, maximum at most 60 s): the two outputs are computed
   where they were withheld, and what that costs on the production host has not been measured.
8. **The write statement holds.** Nothing in this update writes to a Home Assistant entity, helper, schedule, the inverter or the
   dongle (section 2.4).

**What this does not show.** The live reads show that the balance blocker is gone for these inputs, not that the facts are right:
that the loss-aware rule still catches a sign reversal is measured offline on recorded history, by the fit's fault-injection and
hold-out rows, and a live fault is never injected. A reversal that leaves the sum unchanged (the grid charging the battery: grid and
battery cancel) is invisible to any balance rule, lossless or not.

### 8.14 Step 14: close-out

The evidence is filed in `<OFFLINE_EVIDENCE_DIR>`, the status update is written, and a post to the coordination channel or a push
happens only on the owner's go. The deploy backup and staging folders and the placement's backup folder are kept; the owner cleans
them up. The owner's offline copies of the previous and the new site file are kept, each with its sha256, for the next recalibration.

## 9. Stop conditions (any step)

Stop, change nothing more, record the state, and ask the owner, when: a tool prints anything but the expected line; a hash differs
from its pin; the baseline shows Core not running, Intelligence not SHADOW or not fresh, or supervision not stable; the installed
folder is not what 2.2 expects and is not explained, or a file would be REMOVED; the installed loader is not the one 7.1 was read
on; the offline copy of the site file differs from the live one; the state folder changes between two reads of one paused period
with no restart or reload between them (a restart or a reload rewrites three scorecard pages and `store_meta.json` with the same
content, 2.4, and that alone is not a change; another set of file names or another `store_meta.json` hash is); the Upgrade prints NO CHANGE, a hash mismatch, ROLLBACK NOT CONFIRMED or a failed `ha core check`; the placement prints NO CHANGE,
STOPPED, a read-back mismatch or a restore that could NOT be confirmed; the restart outage exceeds about 5 minutes; after the
restart or the reload the integration does not load, a self-test check FAILs, a repair or error line appears, a new entity or a
`_2` suffix appears; step 8 shows a `SITE_INVERTER_CONVERSION` line; step 11 shows a WARN or no such line, or a `config_hash` that
is not the site-check's; after the un-pause `SELF_TEST_FAILED`, `budget_exceeded` or `exceptions` above 0, a blocking-I/O warning
from the integration, or a write enable, arm, schedule or counter that differs from the baseline; `CT_SIGN_REVERSED` or
`BATTERY_SIGN_REVERSED` on an output after the facts; a step would need a second restart. Never retry a live write without the
owner. Never approve, work around or weaken a permission prompt or a safety gate. Never edit a fact by hand to make a check pass.
Any no-go after the swap means the pause stays on and the rollback of section 10 follows (install runbook 7, 10 and 11).

## 10. Rollback, in order

Each item is the owner's decision to start and needs its own go. The rollback is measured against two things made before any live
write: **(i) the baseline** of step 1 (the integration folder listing and its hashes, the state folder listing (its file names, and
its hashes only before a restart: 2.4), the site file's sha256, Core's version, the log lines, the owner's UI reads, the diagnostics download), and **(ii) the owner's protected full
backup** of step 2, the last resort. **A facts-only rollback** (the kit stays) is RB1, RB2, RB3 and RB6. **A full rollback** is RB1,
RB2 (only if step 9 placed the facts: after a no-go at step 8 the site file was never changed, and RB2 is skipped), RB4, RB5 and RB6. The facts go out first, and the previous kit second (7.1 says why).

1. **RB1, pause.** The owner turns the pause helper on if it is not on (install runbook 11: pause, then roll back). Proof: the status
   reads PAUSED; the state listing is stable across two reads (the block of 8.4: the same two reads, a minute apart, in one paused
   period with no restart or reload between them).
2. **RB2, the facts out: put the previous site file back.** The coordinator places the owner's offline copy of the previous file
   with the same tool, `-ExpectedSha256` its recorded sha256 (the baseline's) and `-ReplaceExistingSha256` the sha256 of the file now
   on the host (the new one); read the Plan first, then give the go for the placement:

   ```powershell
   cls
   $H = '<production alias>'
   $PY = '<PY>'
   $PREVSITE = '<the offline copy of the previous site file>'
   Set-Location <checkout>
   .\tools\place-ha-site-file.ps1 -SiteFile $PREVSITE -ExpectedSha256 <the baseline sha256 of the site file> -SshHost $H -Target Production `
       -ReplaceExistingSha256 <sha256 of the new site file> -Python $PY -Plan
   ```

   ```powershell
   cls
   $H = '<production alias>'
   $PY = '<PY>'
   $PREVSITE = '<the offline copy of the previous site file>'
   Set-Location <checkout>
   .\tools\place-ha-site-file.ps1 -SiteFile $PREVSITE -ExpectedSha256 <the baseline sha256 of the site file> -SshHost $H -Target Production `
       -ReplaceExistingSha256 <sha256 of the new site file> -Python $PY
   ```

   The tool needs `<checkout>` clean, as in step 9. Proof: `ECCO SITE FILE PLACED` with the read-back equal to the baseline's sha256,
   and an independent read of the host file's sha256 equal to `site-file-sha-before.txt` (the read of 8.9 with `$NEW` set to the
   baseline's sha256). The placement takes effect only at a reload or a restart: nothing is live yet.
3. **RB3, reload the entry, only when the kit stays.** The owner downloads the diagnostics, then reloads the entry as in 8.10, paused.
   Proof: `SITE_INVERTER_CONVERSION` is absent from `self_test` again, the status entity's `config_hash` equals the first 16 hex digits of the baseline's site-file sha256 (step 1 records that sha256; the loader derives `config_hash` from the raw file bytes, and the download redacts it), no FAIL;
   after RB6 the two outputs read as the baseline's again (the lossless rule is back, so the balance blocker returns while the flow
   is large). In a full rollback this item is skipped: the restart of RB5 reads the file.
4. **RB4, restore the previous kit (a full rollback).** The coordinator runs the repository's own rollback with the stamp recorded in
   step 5:

   ```powershell
   cls
   $H = '<production alias>'
   $PY = '<PY>'
   Set-Location <checkout>
   .\tools\deploy-ha-kit.ps1 -Action Rollback -BackupStamp <stamp> -SshHost $H -Target Production -ExpectedHaVersion <version> -Python $PY
   ```

   Like every action of this tool it needs `<checkout>` clean: it refuses a dirty working tree and runs the repository validation
   with `-Python` before it sends anything (a refusal on either changes nothing on the host, and `-SkipValidation` is never used
   here). It verifies the backup against its `BACKUP_SHA256SUMS`, stages and verifies the restore copy, backs up the current tree,
   swaps, verifies in place, compares the site file and the state folder before and after and rolls itself back if they changed
   (this is why RB1 comes first) and runs `ha core check`;
   it never restarts. Proof: the PASSED block (`Restored` names the backup's file count, which is the baseline listing's: 57, the installed Ghost kit's; and `HA check    : passed`), and an independent comparison of the
   installed folder with the baseline (the block below):

   ```powershell
   cls
   $H = '<production alias>'
   $E = '<OFFLINE_EVIDENCE_DIR>\u3-baseline'
   $ErrorActionPreference = 'Stop'
   [Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
   $OutputEncoding = [Console]::OutputEncoding
   ssh $H "cd /config/custom_components/ecco_intelligence && find . -type f ! -path '*/__pycache__/*' -exec sha256sum {} +" | Sort-Object | Out-File -Encoding utf8 "$E\integration-rollback.txt"
   '--- integration folder against the baseline (no output means byte-identical hashes):'
   Compare-Object (Get-Content "$E\integration-before.txt") (Get-Content "$E\integration-rollback.txt")
   ```

5. **RB5, restart (a full rollback).** The restart is the owner's, approved separately, short (the latch caveat). Proof: Core
   running; the integration loads with no repair or error line; the download, saved as `diagnostics-rollback.json` and read with
   the block of 8.8 (change `$F`), reads `self_test FAIL []` and `SITE_INVERTER_CONVERSION None`, as the baseline's
   `diagnostics-before.json` reads (the previous loader has no such check, and the file is the baseline's again); the entities are
   the same eleven. The state folder is not compared hash for hash with the baseline after this restart: it rewrote
   `store_meta.json` (same content) and three scorecard pages (same values), 2.4; the proof here is the same file names, the load and the
   download. **What happens to the two outputs:** after RB6 they read as the baseline's, the balance blocker returning
   while the flow is large. If the facts were left in the file by mistake, the previous kit still loads it (7.1) and
   `SITE_INVERTER_CONVERSION` is absent from the download all the same: the file's sha256 against the baseline is then the proof
   that RB2 was done, and RB2 is repeated.
6. **RB6, un-pause and re-read.** After the checks of RB3 or RB5 the owner turns the pause helper off; the status computes again;
   the baseline's UI reads (the install runbook's section 7 go / no-go for the first observed runs: supervision stays SUPERVISED and
   stable with the heartbeat age nominal, and nothing else changed, that is the manual write counter, every write enable, arm and
   schedule, and the TOU slots, as in the baseline) are as before. Proof: the status is a computed SHADOW one, the listing comparison
   of RB4 is still empty, and the site file's sha256 is still the baseline's.
7. **RB7, the protected backup restore, the heavy last resort.** The owner's decision, never the first rollback: read 8.2 first. It
   restarts Home Assistant and returns everything the backup holds, the site file and the scorecard file included, to its state at
   backup time. Proof: after it the owner's UI reads of 8.1 are repeated, and the integration folder listing and the site file's
   sha256 are read again and compared with the baseline as in RB4; what the backup does not hold (anything done since) is gone, and
   the owner has weighed that first.

**Special cases.** *S1, the Upgrade stops before the swap* ("nothing installed changed"): nothing to roll back; record the message,
un-pause. *S2, the tool rolled itself back after the swap* ("was rolled back", verified): compare the installed folder with the
baseline as in RB4; no restart has happened since the swap, so whether RB5 is then needed is S6's question; un-pause only after the
owner has answered it. *S3, ROLLBACK NOT CONFIRMED*: stop; touch nothing; the staging and backup folders are kept; the owner decides
(RB4 with the stamp, or RB7). *S4, the restart outage exceeds about 5 minutes*: the supervision latch may be set; recovery is a
supervised dongle reboot by the owner (install runbook 6), then RB1 to RB6 if the owner chooses. *S5, the pause helper was left on
or turned off by mistake*: record the time and the state, put it back, and re-read the status. *S6, a no-go at step 6, or any
rollback after the swap and before the restart of step 7*: RB1 and RB4 follow as always (RB2 only if the site file was already
placed, which it is not before step 9). If Home Assistant has not restarted since the swap, the old code is still running in the
process (custom integrations load only at start-up: the install runbook's section 6, and the deploy tool's own line says Home
Assistant loads or forgets custom integration code only at a restart), the same reasoning as S2, and RB5 would not be needed to take
the new code out; if a restart has happened (step 7 or later), RB5 applies as written. The install runbook does not say that a
rollback before any restart needs none: its section 11 says "Restart with approval, then verify" after a rollback, and the deploy
tool prints RESTART REQUIRED after a Rollback too. Nor does anything offline show that the running process loaded no module of the
new kit between the swap and the rollback (recalled, not verified). So **ask the owner** before skipping RB5, record the answer, and
read the proofs of RB5 either way. *S7, the placement stopped or restored itself* ("STOPPED", "was rolled back", or a restore that
could NOT be confirmed): the site file on the host is then the previous file or in an unknown state; read its sha256 against the
baseline's (8.9, with `$NEW` set to the baseline's), touch nothing else, and let the owner decide: the placement again, RB2, or
RB7. *S8, the reload or the restart brings `SELF_TEST_FAILED` after the facts were loaded*: pause stays on; RB2 and RB3 (a reload
with the baseline's file) bring the check back; if the failure is not the site file's, the full rollback follows.

## 11. What a first-look failure looks like, and what it means

| What the owner sees | What it means | What to do |
|---|---|---|
| the integration does not load after the restart or the reload, a repair issue, or `SELF_TEST_FAILED` | a start-up gate failed (the kit or the site file) | stop; pause stays on; read the failing line of `self_test`; section 10 |
| the self-test's VENDOR_MANIFEST check FAILs | the installed files are not the kit's | stop; compare with 8.6; section 10 |
| `SITE_INVERTER_CONVERSION` WARN after the reload | the facts in the file are incomplete or invalid (a fact missing, not a number, or outside its bound): the lossless rule stays and the two outputs are withheld with `POWER_LOSS_FACTS_INVALID`, which is stricter than before and never looser | stop; RB2 and RB3, or correct the file offline (the site-check names the problem), check it again and place it again with its own go |
| no `SITE_INVERTER_CONVERSION` line after the facts were placed and the entry reloaded | the reload did not read the new file, or the file on the host is not the placed one, or the old code still runs | read the host file's sha256 (8.9) and the `config_hash`, and whether the restart of step 7 happened; do not place again without the owner |
| the two outputs still carry `POWER_BALANCE_INCONSISTENT` after the facts | the loss-aware rule still finds the residual outside the tolerance: the facts do not fit the present season or flow, or an input is wrong | not a defect of the kit; record the time and the flow; re-fit on the newest data and apply the acceptance rule again (D-U3-6) |
| the two outputs read unknown with another blocker | another gate they rest on (an open decision, an input not fresh, a tariff event, supervision) | not this update's; read the `blockers` codes (8.13) |
| `CT_SIGN_REVERSED` or `BATTERY_SIGN_REVERSED` on an output after the facts | with the loss-aware expectation the balance fits only with a sign reversed: either a real sign fault is now visible or the facts are off | stop; read the fit's fault-injection rows; the owner decides; never edit a fact by hand |
| data quality stays DEGRADED | another blocked item or a WARN finding keeps it so (8.13) | D-U3-7: read the codes; not a failure of this update |
| the placement prints NO CHANGE | the host already holds exactly this file | nothing to do; read its sha256 |
| the placement prints STOPPED, or "was rolled back", or that the restore could NOT be confirmed | the upload did not arrive intact, or the rename or the read-back failed | S7; read the host file's sha256 against the baseline's |
| a twelfth entity, or a `_2` suffix | an entity-id collision (not this update's code: it adds no entity) | the install runbook's recovery (7); never delete and re-add the entry |
| `exceptions` or `budget_exceeded` above 0 | a cycle failed or overran | stop; section 9 |
| a blocking-I/O or slow-callback warning from the integration | an executor read or a write ran on the event loop, or too long | stop; record the text; section 10 |
| the latch is set after the restart | the outage exceeded about 5 minutes | a supervised dongle reboot by the owner (install runbook 6) |

## 12. What is NOT established

Say these plainly in every report about this update.

- **The update has never run in a real Home Assistant that is the owner's.** The code has run offline, on a stand-in Home Assistant
  (L2) and in the engine's own suites, on synthetic data, once in a real Home Assistant Core on an isolated test instance (the L3
  run, next bullet), and the facts were fitted offline on recorded history. Nothing here has been observed on the production host.
- **The L3 (WSL) kit-equivalence reference run is closed (P1, 22 Nov 2026), and its limits are these.** It ran the stacked kit on
  the isolated test instance (Home Assistant Core 2026.11.0, Python 3.14.10; 1 h 53 min of instance time; 13 slot cycles, 9 of them
  on the stacked kit): (a) to (f) passed and (g) is recorded offline. It was never run in the owner's Home Assistant, it did not
  read the production versions, and it used synthetic round-number readings and a fictional site file: never the owner's facts.
  The closure holds only for those two versions: after any Core or Python update of the host the run is repeated on the new
  versions and P1 reopens (U3-G5).
  - **The flip of data quality to OK is not shown there.** The harness maps no export or dump inputs, so the export event and Dump to
    Grid read unknown there for other reasons (an input not fresh, supervision not stable, tariff events not fresh) with or without
    the facts, and data quality read DEGRADED in every state. The run shows `POWER_BALANCE_INCONSISTENT` leaving the blocker list
    when the facts are valid and staying when they are invalid, not a released number: a released number is shown by the repository
    suites, and on the host by the reads of step 13.
  - **Slow-callback lines under load.** The run's 0.25-CPU debug session logged 13 slow-callback lines while diagnostics downloads
    were being taken, none naming the integration; which frames ran inside the three request-handler steps was not cleared. The
    harness's log scan exits 1 for the known time-format gap (it cannot parse the time-zone suffix of Core 2026.11.0's log lines, so an
    unnamed task fails closed), not for a line of the integration. No blocking-I/O line appeared at all.
  - **No Uninstall and no clean-order rollback on this pair.** The order of section 10 (the facts out first, then the Rollback, then
    the restart) was proved on the stand-alone pair earlier and was not repeated on the stacked pair: the Rollback and its restart ran
    there with the facts left in the file, and the Ghost kit loaded that file and ignored them (7.1). The Uninstall ran only in the
    offline drill.
- **The facts are calibrated, not known.** They are PROPOSED engineering parameters of one site, fitted from a recorded window of
  one season. Whether they hold on another day or in another season is not established; the recalibration rule (D-U3-6) is a
  rule, not a measurement.
- **A wrong set inside the bounds can still hide faults.** The bounds limit how wrong a set can be, not whether it is wrong. Two
  sets inside the bounds put the expected house power at most 0.1 x d + 100 W apart on the discharge side and 0.111 x |d| + 100 W
  on the charge side (d is the net DC-side power); at 5 kW that is 600 W and 656 W, against a balance tolerance of 100 W or 5 % of
  the largest magnitude (250 W at 5 kW). A fault whose effect on the balance is smaller than that shift plus the tolerance can be
  absorbed by a wrong set: a sign reversal of up to about half of the two together, or a house sensor that reads low by about the
  share the shift is of the house power. This is the residual exposure of an in-bounds set that is wrong, which is why the facts
  come from the fitting tool and its fault-injection and hold-out rows are read ([`DATA_QUALITY_METHOD.md`](DATA_QUALITY_METHOD.md)
  section 10.1 quantifies it).
- **Sign-reversal protection is measured offline.** The fault-injection and hold-out rows are computed on recorded history; a live
  fault is never injected on production. A reversal that leaves the sum unchanged is invisible to any balance rule.
- **Data quality may stay DEGRADED** (8.13): this update removes one cause, and the diagnosis recorded no other finding at the time,
  which is a reading of one day and not a promise for the next.
- **The config-entry reload on the production host with this integration has never been run.** It is the install runbook's own
  recovery step, and that runbook does not record it as run on a real Home Assistant; the L3 run observed it on the isolated
  instance only, three reloads with the pause helper off (each started a start-up slot and the status read STARTING for about three
  and a half minutes afterwards), not with the pause helper on as step 10 does; the Home Assistant screen names are recalled, not
  verified on this host.
- **The cost of computing the two outputs on the production host is unmeasured.** They were withheld before; the cycle-time bounds
  of the install runbook's section 7 are read in 8.13.
- **The rollback with the facts present has never been run live.** The drill proves the swap steps leave the site file and the
  state folder byte-identical on a mock root (it restarts nothing: a restart rewrites three scorecard pages and `store_meta.json`
  with the same content, 2.4); one offline experiment on synthetic data ran the previous loader on a file with the facts. The
  previous integration as a whole ran on such a file once, in the L3 run on the isolated instance (P1(d): it loaded and ignored the
  facts), and no suite runs the previous code.
- **The baseline's listing commands** (`find`, `ls -lR`, `sha256sum` over the state folder and the site file) have not been run on
  the production host, and the diagnostics file's outer wrapper key is recalled, not verified. The repository's own tools
  (`ha-status.ps1`, `ha-logs.ps1`, `deploy-ha-kit.ps1`, `place-ha-site-file.ps1`) are the read-only and write routes; the Upgrade,
  the Rollback and the placement have run offline in the drill and against a stand-in host, and this runbook does not claim they
  have run on the production host.
- **Intelligence stays SHADOW** and its overall acceptance is not changed by this update; the facts are not owner decisions.
- **The owner's items stay open** (section 4): this runbook decides none. Several Home Assistant screen names and the behaviour of
  a protected-backup restore are recalled, not verified on this host.
