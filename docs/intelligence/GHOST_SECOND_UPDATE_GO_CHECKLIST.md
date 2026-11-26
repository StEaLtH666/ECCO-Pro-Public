# U2 Ghost diagnostics update: the short GO checklist

For the owner's decision on the second live Home Assistant update. The full detail is in `GHOST_SECOND_UPDATE_RUNBOOK.md`, cited
here as "runbook N" (a section number). Nothing in this list has been done.

## 1. The answer

**Prepared offline and never run in a real Home Assistant. NOT yet ready for your go.** Open preconditions (runbook 5): P1, P4, P5, P7 and P9.
Closed since the first draft: P2 (code review), P3 (one independent review of these documents and their suite: eight findings fixed and
pinned, no BLOCKER or MAJOR left open), P6 (U1 was installed and verified on 21 Nov 2026; U1 and U2 never share a window) and P8 (offline
gates re-verified).

- **P1 (the one that matters most):** the L3 (WSL) kit-equivalence reference run must be repeated on the exact kit. It has not been
  repeated since the kit changed. It must observe the executor reads in the diagnostics download and the log lines in a real Home
  Assistant. P9 (the reference kit's hash, which the Production route requires) follows it.
- P4 CI green on the exact commit (not pushed yet); P5 your M2 scan on that commit; P7 your rulings on section 3.

**No automatic installation or live access is authorised.** Nothing is installed, restarted or read live until every precondition is
closed, you have given the final GO on this list, and each live step has had its own go.

Your words, kept: Ghost is the **second update**, a separate one with its **own backup, restart and rollback verification**; a failed
advice write keeps an **incident record and shows the failure honestly**; health recovers only after a **later verified write** and the
earlier incident is kept for diagnosis. Intelligence stays SHADOW; this update is diagnostics only.

| Pinned artefact (the kit as reviewed) | `SHA256SUMS` sha256 |
|---|---|
| built with no commit recorded (58 files) | `ec9f31955ef635e8bf3f02c690f26b86cfecb5982f5b497796085196c7612525` |
| built with the fixed reference commit `--git-sha 0000000` (58 files) | `41fe3ab03b9222dcba476af9d1afdf7ea2bda8dd8b00ea3bef6485c3b0ae4ac1` |

The kit you install is built with its own commit: it differs from these in two `VENDOR_MANIFEST.json` lines only (runbook 3).

## 2. What changes, and what does not

| Changes | Detail |
|---|---|
| the integration's code | the folder `/config/custom_components/ecco_intelligence/` is replaced by the kit (5 new files, 5 changed, 47 identical to the merged base's) |
| a Home Assistant restart | one, yours, approved separately, short (an outage over about 5 minutes sets the supervision latch) |
| a durable write | per-slot advice rows in `advice_log` inside the existing scorecard file: at most 52 rows a day, an age bound of 400 days, about 21 000 rows (a few MB); the table is created at the first advice-log attempt, even if that attempt writes no row |
| a second small table | `advice_incident` (at most 10 rows), created by the incident persist that runs right after a verified write that follows a failed one, only when a closed incident is to be written |
| what you will see | STORE_RECORD INFO then PASS after the first verified write (the download shows the word PASS only), **WARN while an incident is open**, PASS again only after a later verified write; an `advice_incidents` block and the Ghost block in the diagnostics download; two log lines: the incident-open WARNING, and a close line logged at INFO that may not show at your logger level (its absence is not a failure; runbook 2.3) |

**Not changed:** the eleven entities and every published value, the mode, helpers, schedules, packages, dashboards, the site file, the dongle,
the inverter, the time-series database. **No entity, helper or service is created** (RG-F3: section 3). The writes of this update, in one
line (runbook 2.1 and 2.4): the integration folder (replaced by the kit), the staging and backup folders of the Upgrade, and, at run time,
the two tables in the scorecard file, with `store_meta.json` still written as before. The one helper the procedure touches is the existing
pause helper, which you turn on and off.

## 3. Your acceptance items (I decide none)

| # | Item | Your ruling |
|---|---|---|
| D-U2-1 | the new durable write (advice rows in the scorecard file) | open |
| D-U2-2 | both tables created lazily, neither at start-up: `advice_log` at the first advice-log attempt (even if that attempt writes no row), `advice_incident` by the incident persist after a verified write | open |
| D-U2-3 | at most 52 rows a day, the 400-day age bound (PROPOSED, not your value), at most 10 incidents; a change means a new kit and a repeat of P1 | open |
| D-U2-4 | the STORE_RECORD wording above is what you directed | open |
| D-U2-5 | the restart window | open |
| D-U2-6 | RG-F3: the update creates no entity; the exposure settings stay your tracked F3 issue; does your U1 treatment carry over? | open |
| D-U2-7 | `advice.followed` counts a row withdrawn by a later BLOCKED row before its window; the simulation's own use is `advice_in_force_hours` | open |
| D-U2-8 | `EXPORT_DIFF_EPS_KWH` 0.001 kWh (an export difference below it is treated as arithmetic noise) | open |
| D-U2-9 | the commit to install from, and the order against U1 | open |

## 4. The sequence (each live step needs your own go, given at the time)

| Step | Who | What (runbook 7 and 8) | Expected | Stop |
|---|---|---|---|---|
| 0 | coordinator | offline gates on the exact commit: suites, kit build and compare, mock-root drill | hashes as pinned; the drill PASS | any difference |
| 1 | coordinator + you, **go** | live read-only baseline: Core version, folder listing and hashes, state listing, log lines, your UI reads, your diagnostics download | everything saved; SHADOW, fresh, supervision stable | anything else |
| 2 | you | the protected full backup in the UI | a protected backup exists | none |
| 3 | you, **go** | PAUSE: pause helper on (the install runbook's step before an upgrade) | status PAUSED | not PAUSED |
| 4 | coordinator, **go** | read the scorecard file's hash and size, twice | stable | it changes |
| 5 | coordinator, **go** | `deploy-ha-kit.ps1 -Action Plan`, then, on a separate go, `-Action Upgrade` (stage, verified backup, swap, `ha core check`) | `ECCO INTELLIGENCE KIT UPGRADE PASSED`, the backup stamp, no restart | any failure line |
| 6 | coordinator, **go** | the installed folder equals the kit; the state folder untouched | `INSTALLED TREE EQUALS THE KIT` | any difference |
| 7 | you, **own approval** | **the restart** (nothing in this list restarts Home Assistant) | Core back, integration loads, no repair | over 5 minutes; no load |
| 8 | coordinator + you, **go** | load checks, still paused: no FAIL, the `advice_incidents` block present, eleven entities | as stated | any FAIL; old code |
| 9 | you, **go** | un-pause | a computed SHADOW status | `SELF_TEST_FAILED` |
| 10 | coordinator + you, **go** | after-checks over at least two slot cycles | see 5 | see 5 |
| 11 | coordinator | close-out; a post or a push only on your go | evidence filed | none |

## 5. Verification (steps 8 and 10)

Status SHADOW and fresh; STORE_RECORD absent, then PASS after the first verified write; `last_store` shows 2 advice rows and verified for each slot
cycle, `verified_writes` +1 per slot cycle; no incident, no failure counter; eleven entities and no suffix; the log has no error, budget or
blocking-I/O line, read at a noted logger level (the INFO close line of a closed incident may not show: not a failure); slot cycle times
within the cycle-time bounds of the install runbook's section 7 (slot `total_s` p95 at most 30 s, maximum at most 60 s); every published value read against the baseline (a difference is
explained by the inputs); supervision, write enables and the manual write counter as in the baseline. A deliberate-failure drill is
**offline only**.

## 6. Rollback, in order (runbook 10; each proven against the step 1 baseline)

1. **RB1 pause** (pause helper on). 2. **RB2 restore the previous kit:** `deploy-ha-kit.ps1 -Action Rollback -BackupStamp <stamp>`; proof: the
installed folder's hashes equal the baseline's. 3. **RB3 restart** (yours, separate approval; if the rollback comes before the restart of step 7, whether it is needed is your call:
runbook 10, S6); proof: no `advice_incidents` block, no FAIL. The two tables
stay, unused, harmless to the previous kit (the drill proves the state folder is untouched; one offline experiment on synthetic data opened such a file
with the previous code). 4. **RB4 un-pause and re-read:** a computed SHADOW status; the comparison still empty. 5. **RB5 optionally drop the two tables, on a
copy only:** no host tool exists; the tables may stay. 6. **RB6 the protected backup restore:** your decision, the heavy last resort and never the first rollback (it restarts Home
Assistant and returns everything, the scorecard file included, to backup time).

## 7. Blockers

The open preconditions of section 1 (P1 first). No defect is known from the offline checks. U1 is already installed: U2 is a window of its own. At install time: your reads, your protected backup, your
presence, and your go for each step. If another supervised live step is in progress (U1 included), this one waits.

## 8. What is NOT established

- It has **never run in a real Home Assistant**; the L3 (WSL) run on the exact kit is OPEN.
- The real database's write latency and disk behaviour are unknown; the first creation of the table on the real file has never happened.
- A same-connection read-back is not a durability proof; an incident open at a restart is lost.
- The log lines and the download's executor reads have not been seen in a real Home Assistant; rows per day on the real engine are unmeasured.
- The rollback with the tables present has never run live; the baseline's listing commands have not run on the production host.
- The Ghost block is a simulation and says nothing about forecast accuracy; Intelligence stays SHADOW; D-U2-7 and D-U2-8 are your decisions.
- Several screen names and the diagnostics file's outer wrapper are recalled, not verified.
