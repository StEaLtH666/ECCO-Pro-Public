# U3 inverter power-balance update: the short GO checklist

For the owner's decision on the third live Home Assistant update. The full detail is in `POWER_BALANCE_UPDATE_RUNBOOK.md`, cited
here as "runbook N" (a section number). Nothing in this list has been done.

## 1. The answer

**Prepared offline and never run in a real Home Assistant. NOT yet ready for your go.** Open preconditions (runbook 5): P1, P3, P4, P5, P6, P7 and P9.
Closed: P2 (one independent code review: one MAJOR and five minors, all fixed) and P8 (offline gates on this commit).

- **P1 (the one that matters most):** the L3 (WSL) kit-equivalence reference run on the exact kit, with the facts: the kit loads, a valid
  set gives `SITE_INVERTER_CONVERSION` PASS after a reload, an invalid set is WARN and withholds the two outputs, and the previous
  kit restored on the isolated instance still loads a site file that holds the facts. P9 (the reference kit's hash) follows it.
- P3 an independent review of these documents; P4 CI green on the exact commit (not pushed yet); P5 your M2 scan on that commit;
  P6 Ghost (U2) installed and verified first, or your deliberate ruling that U3 is independent; P7 your rulings on section 3.

**No automatic installation or live access is authorised.** Nothing is installed, restarted, reloaded or read live until every
precondition is closed, you have given the final GO on this list, and each live step has had its own go. No live change before
Ghost has its final GO.

Your words, kept: "keep the diagnosed inverter power-balance correction ready as the following **separate update**", the degradation
fixed, "but not bundled into Ghost". Intelligence stays SHADOW. This is U3: its own window, backup, restart and rollback.

| Pinned artefact (the kit as reviewed, built on the merged base) | `SHA256SUMS` sha256 |
|---|---|
| built with no commit recorded (53 files) | `8de99a8e1f981c48a4e4a193e64d3457aa01e645214436a2f44c00d0d7be5fa5` |
| built with the fixed reference commit `--git-sha 0000000` (53 files) | `71f2d132bc635616b9f951b668113d96705c664c4992580be589e8cd779cec4a` |

The kit you install is built with its own commit: it differs from these in two `VENDOR_MANIFEST.json` lines only. After U2 the commit
holds both updates and these numbers are repeated for it (runbook 3).

## 2. What changes, and what does not

| Changes | Detail |
|---|---|
| the integration's code | the folder `/config/custom_components/ecco_intelligence/` is replaced by the kit (none new, 5 changed, 48 identical to the merged base's) |
| a Home Assistant restart | one, yours, approved separately, short (an outage over about 5 minutes sets the supervision latch), in daylight |
| your site file | three facts in its `site` block (the inverter's two conversion factors and its standby draw), placed with `place-ha-site-file.ps1`; they take effect at a config-entry **reload** (a reload, not a second restart), approved separately |
| what you will see | the Dump to Grid and export-event outputs no longer withheld with `POWER_BALANCE_INCONSISTENT` (they may read unknown for another reason); data quality may return to OK or **stay DEGRADED** (any other open warning keeps it so); one more `self_test` line, `SITE_INVERTER_CONVERSION`, as the single word PASS; the status entity's `config_hash` changes |

**Not changed:** the eleven entities, the mode, helpers, schedules, packages, dashboards, the dongle, the inverter, the time-series
database. **No entity, helper or service is created** (RG-F3: section 3). **No table, column or row type is added**: the scorecard
file and `store_meta.json` are written as before. The writes of this update, in one line (runbook 2.1 and 2.4): the integration
folder (replaced by the kit), the site file (replaced by your new file), the staging and backup folders of the two tools, and nothing
in the state folder. The one helper the procedure touches is the existing pause helper, which you turn on and off.

## 3. Your acceptance items (I decide none)

| # | Item | Your ruling |
|---|---|---|
| D-U3-1 | the order against U2: U3 follows Ghost in a window of its own, and its commit then holds Ghost's code | open |
| D-U3-2 | the commit to install from, after green CI and your M2 scan | open |
| D-U3-3 | the restart window: one restart, in daylight, you watching | open |
| D-U3-4 | the facts take effect at a reload after the one restart (recommended), or before it so one restart reads both | open |
| D-U3-5 | the acceptance rule for the facts: the fit on the newest data, proposed facts not NOT USABLE and inside the bounds, at least 99 % accepted, the hold-out and fault-injection rows read by you | open |
| D-U3-6 | the recalibration rule: re-fit at each season change, after any inverter, setting, CT or sensor change, and when the balance blocker returns | open |
| D-U3-7 | data quality that stays DEGRADED is read, not chased: no rule loosened, no fact edited to reach OK | open |
| D-U3-8 | the legacy-device clean-up is separate from U3 and not in its window | open |
| D-U3-9 | the bounds 0.90 to 1.0 (factors) and 0 to 100 W (standby): PROPOSED, not your values; a change means a new kit and a repeat of P1 | open |

## 4. The sequence (each live step needs your own go, given at the time)

| Step | Who | What (runbook 7 and 8) | Expected | Stop |
|---|---|---|---|---|
| 0 | coordinator | offline gates on the exact commit: suites, kit build and compare, drills, the fit and the site-check | hashes as pinned; the drills PASS; facts accepted | any difference |
| 1 | coordinator + you, **go** | live read-only baseline: Core, listings and hashes, the site file's sha256, log lines, your UI reads of the three outputs, your download | everything saved; SHADOW, fresh; the installed loader is the one read | anything else |
| 2 | you | the protected full backup in the UI | a protected backup exists | none |
| 3 | you, **go** | PAUSE: pause helper on | status PAUSED | not PAUSED |
| 4 | coordinator, **go** | read the scorecard file's hash and size, twice | stable | it changes |
| 5 | coordinator, **go** | `deploy-ha-kit.ps1 -Action Plan`, then, on a separate go, `-Action Upgrade` | `ECCO INTELLIGENCE KIT UPGRADE PASSED`, the backup stamp, no restart | any failure line |
| 6 | coordinator, **go** | the installed folder equals the kit; the state folder and the site file untouched | `INSTALLED TREE EQUALS THE KIT` | any difference |
| 7 | you, **own approval** | **the restart** (nothing in this list restarts Home Assistant) | Core back, integration loads, no repair | over 5 minutes; no load |
| 8 | coordinator + you, **go** | load checks of the kit alone, still paused, site file unchanged | no FAIL, no `SITE_INVERTER_CONVERSION` line | any FAIL |
| 9 | coordinator, **go** | `place-ha-site-file.ps1 -Plan`, then, on a separate go, the placement of the new site file | `ECCO SITE FILE PLACED`, read-back equal | NO CHANGE, STOPPED |
| 10 | you, **own approval** | the config-entry reload (a reload, not a restart), after a download | entry loads, PAUSED | no load |
| 11 | coordinator + you, **go** | load checks with the facts, still paused | `SITE_INVERTER_CONVERSION` PASS, `config_hash` as the site-check's | WARN, FAIL |
| 12 | you, **go** | un-pause | a computed SHADOW status | `SELF_TEST_FAILED` |
| 13 | coordinator + you, **go** | after-checks over at least two slot cycles, read while PV or battery power is large | see 5 | see 5 |
| 14 | coordinator | close-out; a post or a push only on your go | evidence filed | none |

**Why this order** (runbook 7.1): the previous kit does not refuse the facts, so no order fails a start-up; the kit comes first with
one restart, then the facts, because the facts are the loosening step: last in, first out. The facts take effect only at a reload or a restart.

## 5. Verification (steps 8, 11 and 13)

Status SHADOW and fresh; `SITE_INVERTER_CONVERSION` PASS and `config_hash` equal to the site-check's; the two outputs' `blockers` without
`POWER_BALANCE_INCONSISTENT` (read while the flow is large; another blocker is not this update's); data quality OK or its codes read
(runbook 8.13); eleven entities and no suffix; the log has no error, budget or blocking-I/O line; slot cycle times within the bounds of the
install runbook's section 7 (slot `total_s` p95 at most 30 s, maximum at most 60 s); supervision, write enables and the manual write counter as in the baseline.

## 6. Rollback, in order (runbook 10; each proven against the step 1 baseline)

The facts go out first, the previous kit second (the facts are the loosening step). 1. **RB1 pause.** 2. **RB2 the facts out:**
`place-ha-site-file.ps1` with your offline copy of the previous site file; proof: the host file's sha256 equals the baseline's. 3. **RB3 reload**
the entry, only when the kit stays; proof: `SITE_INVERTER_CONVERSION` absent, `config_hash` as the baseline's. 4. **RB4 restore the previous
kit:** `deploy-ha-kit.ps1 -Action Rollback -BackupStamp <stamp>`; proof: the installed folder's hashes equal the baseline's. 5. **RB5 restart**
(yours, separate approval; if the rollback comes before the restart of step 7, whether it is needed is your call: runbook 10, S6); proof: no FAIL,
no `SITE_INVERTER_CONVERSION`. 6. **RB6 un-pause and re-read:** a computed SHADOW status; the comparison still empty. 7. **RB7 the protected
backup restore:** your decision, the heavy last resort and never the first rollback (it restarts Home Assistant and returns everything, the site
file and the scorecard file included, to backup time). A full rollback needs one restart; a facts-only rollback needs none.

## 7. Blockers

The open preconditions of section 1 (P1 first). No defect is known from the offline checks. Ghost (U2) is a window of its own: if another
supervised live step is in progress, this one waits. At install time: your reads, your protected backup, your presence, the offline copy of
your site file, and your go for each step.

## 8. What is NOT established

- It has **never run in a real Home Assistant**; the L3 (WSL) run on the exact kit is OPEN.
- The facts are calibrated, not known: whether they hold in another season is not established (recalibration is a rule).
- A wrong set inside the bounds can still hide faults: at 5 kW up to 600 W (discharge side) or 656 W (charge side) of expectation, against a
  250 W tolerance; the fit's fault-injection and hold-out rows, read by you, are the defence.
- Sign-reversal protection is measured offline on recorded history; a reversal that leaves the sum unchanged is invisible to any balance rule.
- Data quality may stay DEGRADED; the config-entry reload on the production host has never been run (recalled); the cost of computing the two
  outputs there is unmeasured; the rollback with the facts present has never run live; screen names are recalled.
