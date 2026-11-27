# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); the project uses semantic versioning for releases. Component versions
(firmware stage, dashboard version, Intelligence model version) are listed in `VERSION.yaml`.

Development before the first public release happened in a private repository; see
[docs/project-history/README.md](docs/project-history/README.md).

## [Unreleased]

### Added
- **Reserve floor read-back (read-only; offline, nothing installed)**: `home-assistant/packages/ecco_reserve_floor_status.yaml`, the read half of making the battery reserve editable from the panel with an inverter-level floor. It reads back, from the dongle's configuration read that already runs, the registers that could hold a floor (the lowest target SOC among the non-charging TOU slots, the battery shutdown SOC, and the TOU flag) and compares them with the plan's effective reserve: `sensor.ecco_reserve_floor_status` reads MATCH, BELOW, ABOVE, PENDING (a lease, a restore, another write, an open recovery, an editor Apply in flight, or a read older than 150 s) or UNREADABLE (any input that is missing, unavailable, unknown, not a whole percent or not a charge source the firmware writes; a read stale for more than 1800 s), with the floor, the difference, a reason in words and every input with its freshness as attributes; `binary_sensor.ecco_reserve_floor_registers_below_reserve` ("the registers read below the reserve, or cannot be read") is on only for BELOW and UNREADABLE; one opt-in helper `input_boolean.ecco_tell_me_reserve_floor_registers` (no initial value) enables ONE persistent notification after 10 minutes of that. Ids and names were renamed from the first draft before any install so that none says held, holds or enforced; the behavioural NOT HOLDING check (on grid, no lease, SOC under the floor, discharge over 150 W for 5 minutes) is not built, and the charging slots' targets are listed (`charging_slot_targets`), not judged (open question for the owner, the same as proof R6). Two time limits make a wait end: Configuration Online off for more than 1800 s and any single pending cause older than 6 hours read UNREADABLE (counted from `last_changed`, so only over continuous Home Assistant uptime). A register is not behaviour: it makes no claim of enforcement (whether a slot target acts as a discharge floor is proof R6, not run) and has no DRIFT state (no reliable fact exists to base one on). On the house today the non-charging slots read 0 percent, so it reads BELOW: the reserve is a software value only. It reads no forecast and no Intelligence entity, writes nothing but the notification, and installs with a file copy and three reloads (`restart_required: false`). Suite `home-assistant/tests/test_ecco_reserve_floor_status.py` with a model (`_reserve_floor_status_sim.py`), an independent differential and 99 mutants; recorder footprint is an estimate.
- **Reserve control (offline, nothing installed)**: `home-assistant/packages/ecco_reserve_control.yaml`, ONE guarded script `script.ecco_reserve_set` (fields `value`, a whole percent from 0 to 80, and `confirm`) that writes only `input_number.ecco_minimum_reserve_soc`, reads it back and leaves a result text in a new input_text. It refuses (stable codes NOT_A_NUMBER, OUT_OF_RANGE, NOT_WHOLE, HELPER_UNREADABLE, RESERVE_UNREADABLE) or asks to be confirmed (CONFIRM_NEEDED) for a value below the reserve the plan uses now or below the owner's own; a raise needs no confirmation; lowering the owner's reserve during a Prepare for power cut reserve is allowed with confirm and the result says the effective reserve does not fall. It writes no inverter, dongle, TOU, number, switch or button entity (the suite pins the write vocabulary), changes no register and the panel's editing control is a later change. It is a second writer of the reserve helper: the existing suite `test_ecco_reserve_default.py` pins exactly one writer and fails on it by design until that one pinned line names this script. Install: a file copy and a reload of Input texts and Scripts, no restart. Suite `home-assistant/tests/test_ecco_reserve_control.py` with a model (`_reserve_control_sim.py`) running the real plan package, and mutants.
- **Dongle lost during a lease (read-only; offline, nothing installed)**: `home-assistant/packages/ecco_dongle_lost_alert.yaml`, two automations: when a Free Power or Dump to Grid lease (or the restore a start that failed half-way still owes: Snapshot Valid or Operation In Progress on with Active off) was reported and the dongle's telemetry has then stayed offline for 5 minutes, ONE persistent notification says in plain words that no firmware guard may be running and what to do (the vendor app: Zero Export, or the usual time-of-use table); it dismisses itself when telemetry returns. Every trigger is a change from `on` (one of the six lease flags to unavailable, or telemetry off or unavailable while one reads on), so a restart, a reload or an unavailable-to-on transition never creates it, and the only service calls are the notification's create and dismiss; the notice stays until the telemetry flag reads on. Install: a file copy and a reload of Automations. Suite `home-assistant/tests/test_ecco_dongle_lost_alert.py` with a model (`_dongle_lost_alert_sim.py`) and mutants. All three packages belong to post-export entry `rrb1` (the manifest stanzas); `rsv1` is an older entry on main (the reserve helper's first-run value), so this one has its own id.
- **R9 clock-change fixes and the Charge Battery result-integrity fix** (offline; both schedule packages; not installed; part of post-export entry `r9`). Arming now refuses a start time that is a skipped local time (the hour that does not exist when the UK clocks go forward), a repeated one (the hour that happens twice when they go back) or one that cannot be read, with `REJECTED - the start time is a skipped, repeated or unreadable local time (clock change); pick another time` (fail closed, before `must be in the future`, which was misleading in the second 01:xx hour). The Export to Grid arm-time TOU overlap check walks the run on the real instants, so a window that crosses a clock change checks the slots it really covers (before: a missed charge slot on the day the clocks go forward, a false refusal on the day they go back). The firmware is not changed and still walks the window the old way. The Charge Battery package no longer turns a refused, failed, blocked, cancelled or still-starting result into `STARTED OK` when Free Power is found active after the retry loop, nor in the startup recovery after a Home Assistant restart (the result stays as written, or reads `FAILED TO START ... did not confirm that it started it` / `UNCONFIRMED`; the end-of-run alert says Free Power is active now); `STARTED OK` is written only by the run's own verified start. This supersedes, for Charge Battery only, the R9 bullet below's 'a restart during a running session ... unchanged'. How Home Assistant reads a naive local time is recalled, not verified (a supervised template check is still open). Tests: `registry/tests/test_ha_r9_missed_runs.py` [5] and [6], `home-assistant/tests/test_ecco_free_power_schedule_reliability.py` [17], simulator support for a real time zone.
- **R9: no automatic start of a missed scheduled run after a Home Assistant restart** (offline; both schedule packages, Charge Battery and Export to Grid; not installed). A captured Home Assistant start time (a helper written only by a new capture automation on the `homeassistant` start event) now guards both start paths: the schedule watchdog and the startup recovery never start a run whose start time fell before the Home Assistant start, or while that time is unknown or stale (fail closed). The miss is recorded (`MISSED - not started after a Home Assistant restart`), notified and only that occurrence is disarmed; a future occurrence stays armed and starts on time, and the on-time start, the watchdog's start of a start that fell while Home Assistant ran, and a restart during a running session are unchanged. Declared as post-export entry `r9`; `registry/tests/test_ha_r9_missed_runs.py`. Behaviour change: after a restart a missed session is no longer started late. The capture waits (up to 10 minutes) for the dongle's NTP to be synced and Home Assistant's clock to agree with it, so a host booting with a wrong clock never stores a false start; install with a FULL Home Assistant restart (a reload leaves the capture unknown, so the watchdog will not rescue a lost on-time start until then). The deployment manifest now states the FULL-restart requirement in a comment above each of the two package stanzas (comments only; the edit is declared in the `r9` pin-chain entry).
- **Gentle rate advice and an offline replay (read only; nothing installed, nothing actuated)**: `frontend/ecco-plan-core/src/gentleAdvice.ts`, `adviseGentleRate`, a stateless, pure layer over the Gentle model that answers "what is the gentlest charge rate that still reaches the target by the deadline" with one reason code from a closed list, an outcome (on time, late, missed, at target, unknown), the practical minimum, the safe maximum, the margins the rate carries and, with a pack voltage, the rate as a current. Missing, stale or implausible data gives no advice and says why; the rate is never above the smallest known safe ceiling or the grid cap, never above what the deadline needs, never below the practical minimum; monotone in SOC, target, time, buffer and capacity (seeded sweeps); no service call, network, file or clock (a static pin). Deliberately not exported by the package index (the card bundle is declared by `epc4`). `intelligence/tools/gentle_replay.py` replays it against recorded Home Assistant history files through `frontend/ecco-plan-core/tools/adviseBatch.ts` and prints what the battery did next to what would have been advised (it writes nothing but `--output`). `frontend/ecco-plan-core/GENTLE_LIVE_ACTUATION_PROOF.md` lists the independent proofs required before any live actuation; nothing is authorised by it.
- **Production Mode / Geek Mode shell card, first supervised update prepared** (offline only: nothing installed, registered or deployed; no restart, no entity added, no existing dashboard, package, helper or resource changed): the read-only Lovelace card that gives the ECCO Intelligence view a calm Production Mode and a Geek Mode with every non-secret data point (its catalogue: 17 sources, 344 attribute rows, 19 alerts), its Node suites with the 518-mutant proof and the headless strip check (local evidence), a Python static pin suite that CI can run (the card's exact bytes, no service call, no network, no dynamic code, one timer, two window listeners and three click-only actions), a generator for the raw configuration of a new admin-only dashboard that hosts it (the catalogue inline) and the runbook for the supervised install (a backup, one resource, one dashboard, read-backs and rollback: [docs/product-ui/GEEK_MODE_FIRST_UPDATE_RUNBOOK.md](docs/product-ui/GEEK_MODE_FIRST_UPDATE_RUNBOOK.md)). The card has never run in a real Home Assistant or browser. Release bookkeeping (manifest entry, scope-chain and PEX entries, `VERSION.yaml`) is deferred to the merge.
- **The repository's Overview dashboard carries the Stage 3 plan options on the Energy Actions card (display configuration only; post-export entry `ovw4`)**: `show_plan: true`, the `plan` block (the generic quoted device slug as `entity_prefix`, which `tools/ecco_site_render.py` renders per site as for the TOU Settings cards, and the reserve helper) and `dump_to_grid.guarded_start` on the one Energy Actions card of the Overview view, so a render of this repository equals an Overview that already uses them and a whole-file dashboard deploy no longer removes them. The dashboard version is not bumped; the site policy's protected flow card is untouched; no firmware, package, deployment, registry or Intelligence change; pinned by `home-assistant/tests/test_ecco_energy_actions_plan_options.py` and `registry/tests/_ovw4_scope.py`.
- **Start-button bypass detector (detect and alert only; offline, nothing installed)**: `home-assistant/packages/ecco_start_bypass_detector.yaml`, option O2 of the R9 / Stage 3 integration plan. When a Dump to Grid or Charge Battery session turns active without ECCO's own record of the start (the schedule's own `STARTED OK`, or the guarded start), it records an incident (always: time, kind, text, counter; the plan facts at that moment: an export hold, a staged Stop SOC below the effective reserve, an unreadable plan reading) and raises a persistent notification (for Dump to Grid on every such start; for Charge Battery only when an export hold is active or a plan reading is unreadable, because the card's own Start for Charge Battery has no guarded path and would otherwise raise a popup on every start; the mute switch hides popups only). The notice says "no ECCO record of this start was found within 45 s", not that ECCO did not start it (it can be an ECCO run whose record was late or unconfirmed). It prevents nothing, is blind while Home Assistant is down, cannot tell a deliberate owner start from the dongle's own screen from a script that holds the API key, and reports `CANNOT CLASSIFY` (never an all clear) when a marker cannot be read. It writes only its own helpers and notifications, adds no template entity and changes no existing package. The suite `home-assistant/tests/test_ecco_start_bypass_detector.py` runs the real package and the real scripts against the dongle models, with independent models and over 80 mutants. Two minor defects found on an isolated Home Assistant test instance (Core 2026.11.0, 25 Nov 2026) are fixed in the package: an automation reload during a live check, with the detect automation unchanged, no longer raises a false "check interrupted" notice next to the real one (the interrupted-check automation stays silent while the detect automation has a running instance), and with the mute switch on the last-check text says the popup was muted instead of "see the notification"; the suite carries their cases and 14 mutants. The Start button itself stays unbound (a firmware gate is a separate approval). Listed in the deployment manifest and carried by the post-export pin-chain entry `bpd1`; nothing is installed.
- **R9 clock-change fixes and the Charge Battery result-integrity fix** (offline; both schedule packages; not installed; part of post-export entry `r9`). Arming now refuses a start time that is a skipped local time (the hour that does not exist when the UK clocks go forward), a repeated one (the hour that happens twice when they go back) or one that cannot be read, with `REJECTED - the start time is a skipped, repeated or unreadable local time (clock change); pick another time` (fail closed, before `must be in the future`, which was misleading in the second 01:xx hour). The Export to Grid arm-time TOU overlap check walks the run on the real instants, so a window that crosses a clock change checks the slots it really covers (before: a missed charge slot on the day the clocks go forward, a false refusal on the day they go back). The firmware is not changed and still walks the window the old way. The Charge Battery package no longer turns a refused, failed, blocked, cancelled or still-starting result into `STARTED OK` when Free Power is found active after the retry loop, nor in the startup recovery after a Home Assistant restart (the result stays as written, or reads `FAILED TO START ... did not confirm that it started it` / `UNCONFIRMED`; the end-of-run alert says Free Power is active now); `STARTED OK` is written only by the run's own verified start. This supersedes, for Charge Battery only, the R9 bullet below's 'a restart during a running session ... unchanged'. How Home Assistant reads a naive local time is recalled, not verified (a supervised template check is still open). Tests: `registry/tests/test_ha_r9_missed_runs.py` [5] and [6], `home-assistant/tests/test_ecco_free_power_schedule_reliability.py` [17], simulator support for a real time zone.
- **R9: no automatic start of a missed scheduled run after a Home Assistant restart** (offline; both schedule packages, Charge Battery and Export to Grid; not installed). A captured Home Assistant start time (a helper written only by a new capture automation on the `homeassistant` start event) now guards both start paths: the schedule watchdog and the startup recovery never start a run whose start time fell before the Home Assistant start, or while that time is unknown or stale (fail closed). The miss is recorded (`MISSED - not started after a Home Assistant restart`), notified and only that occurrence is disarmed; a future occurrence stays armed and starts on time, and the on-time start, the watchdog's start of a start that fell while Home Assistant ran, and a restart during a running session are unchanged. Declared as post-export entry `r9`; `registry/tests/test_ha_r9_missed_runs.py`. Behaviour change: after a restart a missed session is no longer started late. The capture waits (up to 10 minutes) for the dongle's NTP to be synced and Home Assistant's clock to agree with it, so a host booting with a wrong clock never stores a false start; install with a FULL Home Assistant restart (a reload leaves the capture unknown, so the watchdog will not rescue a lost on-time start until then). The deployment manifest now states the FULL-restart requirement in a comment above each of the two package stanzas (comments only; the edit is declared in the `r9` pin-chain entry).
- **Gentle Smart Charging controller model (offline, read only; nothing installed, nothing actuated)**: `frontend/ecco-plan-core/src/gentleController.ts`, a pure model that turns SOC, remaining time and the smallest known safe power ceiling into a recommended charge-power setpoint (lowest 100 W step that reaches the target, 100 % included, by the finish-early deadline; assumed BMS taper; hysteresis, dwell and a changes budget), labelled "model, not a command" with `actuationSupported: false` (today's firmware fixes the Free Power rate at START). A closed-loop battery simulator and 400 seeded scenarios test it; post-export entry `epc3`. Version 2 (same files, still read only): an optional household group (demand now and forecast, solar now and forecast with a confidence factor, a KNOWN grid import limit) caps the setpoint at the pessimistic grid headroom (an unknown limit applies no constraint and says so, nothing is guessed); safe fallback policies (keep current, use the static plan rate, none); an optional slew limit; anti-flapping holds; a parameter provenance table (provisional, owner set, measured required); every decision says the target is NOT guaranteed. With no household input the v1 output is bit-identical (golden master); 360 household closed-loop scenarios, 93 mutants (92 killed, one equivalent).
- **ECCO plan overrides, stage 3 (offline; nothing installed)**: the guarded Hold battery / Skip tonight / Prepare for power cut overrides.
  `home-assistant/packages/ecco_plan_helpers.yaml` (the owner's limits, seeded once with the accepted starting values; the plan revision; the
  override records; two guarded scripts that enforce the validator's rules server-side with stable refusal codes and write only these
  helpers; the export-hold and effective-reserve sensors), `ecco_dump_to_grid_guarded_start.yaml` (the card's manual Dump to Grid start,
  behind the same two checks) and the scheduled Dump to Grid start refusing during an override and raising its Stop SOC to the effective
  reserve. Prepare for power cut raises the reserve ECCO's own plan uses (it does not change the inverter's own reserve) and never charges. The Energy Actions card gains start and cancel controls that
  can call only those scripts. One parity table runs against the validator and against the script. Post-export entries `epc1` (stage 2 views)
  and `epc2` (stage 3). The dongle's own Start button entity stays unbound (a firmware gate is a separate approval).
- **Stage 3 limitation stated in every place a reader meets it (text only; nothing installed)**: the overrides are a PARTIAL protection
  (release gate RG-ST3). The Energy Actions card's Quick overrides block carries an always-visible note, and the card README, the plan-core
  README and the headers of the two Stage 3 packages carry the same sentence: the dongle's own Start button can still be pressed from Home Assistant
  or by an assistant, the helpers are plain helpers an administrator or assistant can write, and binding the Start button needs a firmware gate
  (a flash, approved separately). A static suite (`home-assistant/tests/test_ecco_stage3_limitation.py`) requires the sentence in each place
  and in the rebuilt bundle and that the card adds no service call or write path for it. The card bundle was rebuilt; `epc2` and `epc3` were
  re-sealed. The `test_ovw1_transition` card-folder pin (owner decision of 17 Nov 2026) now sets aside only the files a LATER post-export entry
  declares as added; every file hash, the 28-file count and the folder hash stay pinned.
- **Stage 3 start scripts refuse an invalid effective reserve (reason `RESERVE_INVALID`; offline, nothing installed)**: the scheduled Dump to Grid
  start and the guarded manual start now accept the effective reserve only as a finite number from 0 to 100, tested as a positive range.
  `float()` also accepts nan, inf and -inf and inf cannot be rounded (a bare nan or inf is kept as text by the result parser, in the offline interpreter
  and, by reading Home Assistant's code, in Home Assistant, so the next comparison raises), so a reserve of nan or inf was not refused cleanly: the start
  script aborted before any refusal was recorded (nothing staged or pressed), and a comparison with nan is always false.
  Both scripts now record the refusal exactly like their other refusals (the last-result text and the persistent notification). On the scheduled start
  nothing is staged, armed or pressed and the dongle write enable ends off; the guarded start presses nothing and never touches the write enable (it calls
  no switch service, so a write enable the owner had turned on stays as it was after a guarded refusal). The reasons are `RESERVE_INVALID` (nan,
  infinity, anything above 100) beside the existing `RESERVE_UNKNOWN` (cannot be read, or below 0) and `RESERVE_TOO_HIGH` (91 to 100, scheduled
  start). The guarded start also refuses a staged Stop SOC read-back that is not a finite number from 0 to 100 (`STOP_SOC_UNREADABLE`). A valid reserve behaves as before and no threshold moved; the plan sensor
  that produces the reserve is unchanged. A finite reserve above 100 used to be reported as `RESERVE_TOO_HIGH` (scheduled start) or
  `STOP_SOC_BELOW_RESERVE` (guarded start); it was refused then and still is, now as `RESERVE_INVALID`. The dongle's own Start button stays
  unbound (unresolved; binding it needs a firmware gate, a separate approval). Added to `test_ecco_plan_enforcement.py` (+74 checks)
  and `test_ecco_r9_stage3_composition.py` (+53 checks); `epc2` and `epc3` were re-sealed.
- **Deployment manifest wording for Stage 3 (comments only; nothing installed)**: the scheduled Dump to Grid stanza of `deployment/ha-manifest.yaml`
  now says that the changed package needs `ecco_plan_helpers.yaml` installed in the same deployment, before the one full Home Assistant restart that
  R9 already requires (the order of the stanzas in the list does not matter: the deploy tool copies every package, checks the configuration and restarts
  Home Assistant only as a separately approved step), and that until the helpers are installed and Home Assistant has restarted fully every scheduled
  start is refused (`OVERRIDE_UNREADABLE`) and every guarded start is refused. The plan helpers stanza, the guarded-start stanza and the guarded
  start package header say the same. It also carries the active-override warning: while a Hold battery, Skip tonight or Prepare for power cut override is active, or the plan records
  cannot be read, or the reserve is invalid, every scheduled and every guarded start is refused, and the owner sees this only at the start time,
  through the blocked alert and the last-result text. The guarded-start stanza states the unresolved limitation in one sentence (the dongle's own
  Start button is not bound by these protections; binding it needs a firmware gate, approved separately) and the manifest never calls the protection
  fully enforced. No key, value, order or indentation moved; the comments are declared in `epc2`'s manifest pairs, and `epc2` and `epc3` were
  re-sealed. `test_ecco_stage3_limitation.py` now also requires the sentence in the manifest, the notes above the schedule stanza and the
  same-deployment wording (no copy-order claim) on the three Stage 3 stanzas and in the guarded start package header (+23 checks).
- **Stage 3 export hold reads an override's expiry from the helper's timestamp attribute, so the repeated hour of the October clock change no longer releases it early in the offline model (finding 1 of the independent review of 18 Nov 2026; offline, nothing installed; one residual, stated below)**:
  the export-hold sensor (its state and its `held_by` attribute), the effective-reserve sensor's power-cut expiry and the cancel script read each override's expiry
  from the date-and-time helper's `timestamp` attribute (the true instant in the offline model) instead of parsing its state string, which is local wall-clock time. On the Europe/London
  fall-back day the string parse takes the first of the two equal local times, so an override that ended in the repeated hour (a 120 minute override started at
  00:40 BST ends at 01:40 GMT) was released up to 60 minutes early: the scheduled start then pressed while the card still showed the override as active, and the
  cancel script could refuse a running override as not active. A missing or non-numeric attribute, or an unknown, unavailable or empty state, is an unreadable record
  (the hold reads unknown, which refuses; the reserve skips the record; cancel proceeds), and stricter than before when the attribute is missing (a valid state with
  no attribute used to be readable). The expiry second is unchanged (held until the second before the expiry, clear from it) and the sensor still notices an expiry
  within a minute (late, which keeps the hold; the re-render itself never releases it early). The spring-forward and ordinary days are unaffected. **Residual, not fixed and
  not proven in real Home Assistant:** the fix relies on the attribute holding the true instant, and the offline models never restore a helper across a restart. As recalled
  from Home Assistant core (not verified here), a restart restores a date-and-time helper from its state string, which has no offset, so a time in the repeated hour reads
  as the first of the two: a restart while an override is running whose expiry falls in the repeated hour (01:00 to 01:59 GMT on the fall-back day) would then restore that
  expiry 60 minutes early, the original failure in a much narrower case. The attribute is not claimed to be preserved across a restart. This was an open owner decision (accept
  the residual, or have the start script push such an expiry past the repeated hour); it was decided on 19 Nov 2026 (owner decision r14, the bullet below: an absolute epoch record
  next to the date-and-time expiry) and remains an item for the supervised check (plan-core README, known limitations 19 and 23).
  Running checks added to `test_ecco_plan_helpers_package.py` (+22) and `test_ecco_plan_enforcement.py` (+13), with 18 and 9 mutants; the previous
  package fails them. The helper package is an added file of `epc2`, so no pin changed.
- **Stage 3 scheduled start reads the hold and the reserve again immediately before the press (finding 2 of the independent review of 18 Nov 2026; offline, nothing installed)**:
  the scheduled Dump to Grid start read the hold and the reserve once, at its start, and then, when the dongle was offline or another write was in progress, waited
  and retried for up to 10 minutes and pressed without reading them again, so a Hold battery, Skip tonight or Prepare for power cut started during that wait did
  not stop the press (the code comment said a later change ends the next start only). The script now re-reads both just before the press, as the second condition of
  its pre-press check, sanitised exactly as at the start. If the hold is no longer clear (held, or cannot be read), or the reserve can no longer be read or is not a
  finite number from 0 to 100, or the Stop SOC staged for that run is below the rounded-up reserve of that moment, the run ends as a BLOCKED result with the same
  stable codes (`OVERRIDE_ACTIVE`, `OVERRIDE_UNREADABLE`, `RESERVE_UNKNOWN`, `RESERVE_INVALID`, `RESERVE_TOO_HIGH` for the staged Stop SOC) that says it happened while
  the run was waiting: nothing is pressed, the write enable ends off, the schedule is disarmed, the end-of-run alert raises the notification (unless Dump to Grid is
  found active when the loop ends: see below), and the run is never retried. The staging of that last attempt (three numbers, the write enable on,
  then off) has happened and stays on the dongle; the press has not. A run with no plan change behaves
  exactly as before (361 old-versus-new runs, including runs that wait, are bit-identical). An override started in the instant between the re-read and the press is
  not seen, and the dongle's own Start button stays unbound. The recheck runs on every attempt, the first included, after the staging (up to about six seconds) and
  before the press, so a "while this run was waiting" text can also come from a change during that staging; it fails closed, so a hold or reserve sensor that is
  momentarily unknown or unavailable at that moment (a template reload) ends the run as BLOCKED, alerts and disarms the schedule, and that night's scheduled export is
  lost until the owner arms it again (it is not refused for good); and, because the BLOCKED text is written inside the retry loop, a run whose Dump to Grid is found
  active when the loop ends (started from the dongle's own Start button, or manually) has its BLOCKED text overwritten with STARTED OK, no alert and the schedule
  notification dismissed, with nothing pressed by the script (known limitations 20 to 22 of the plan-core README). The plan-core README's enforcement row says so. Running checks added to `test_ecco_plan_enforcement.py`
  (+20) and `test_ecco_r9_stage3_composition.py` (+47), with 16 and 5 mutants; the previous package fails them. No existing check or assertion changed; the scope pairs
  of `epc2` were re-derived, and `epc2` and `epc3` were re-sealed.
- **Stage 3 effective reserve is published rounded up (finding 5 of the independent review of 18 Nov 2026; offline, nothing installed)**: the effective-reserve sensor
  published `round(0)`, which rounds half to even, so an owner reserve of 62.4 or 62.5 was published as 62, below the owner's own value, and the start scripts'
  rounded-up comparison then accepted a Stop SOC of 62. (The helper is whole in the UI, but a service call checks only its minimum and maximum.) Each input, the owner's
  reserve and the running Prepare for power cut reserve, is now rounded UP to a whole percent before the larger is taken (62.4 is published as 63, 62.0 as 62, 0.2 as 1).
  Whole values are unchanged. Running checks added to `test_ecco_plan_helpers_package.py` (+8: the table, every tenth from 0.0 to 100.0, five mutants including the
  floor mutant that survived the review) and `test_ecco_plan_enforcement.py` (+4: the scheduled start stages 63 for 62.4 and the guarded start refuses a staged
  Stop SOC of 62, with the real sensor). The plan-core README's row for the sensor says so. The helper package is an added file of `epc2`, so no pin changed.
- **Stage 3 plan helper suite: five mutants that survived are now killed (finding 4 of the independent review of 18 Nov 2026; tests only, no package change)**: the
  README states that cancel ends only its own kind, but the mutants "cancelling Skip tonight also ends Hold battery" and "cancelling Prepare for power cut also ends Skip
  tonight" passed every check, as did a raise-only test weakened to "the power-cut reserve may be 5 below the owner's" (the only refusal case had a 10 point gap), Hold
  battery released 45 s early (now killed with the clock-change checks, for every kind) and the hold sensor ignoring an unreadable Prepare for power cut record (the only
  unreadable-record case used Skip tonight). `test_ecco_plan_helpers_package.py` now cancels each kind with all three active in every order and requires the other two
  records, the hold, `held_by` and the effective reserve to be exactly as they were; runs the raise-only boundary (equal, 0.5, 1 and 5 points on each side); and breaks the
  record of each kind in four ways (+19 checks, 14 mutants including all six cross-kind cancels). Nothing existing was edited or loosened.
- **Stage 3 wording: what the overrides do and do not do (finding 3 of the independent review of 18 Nov 2026; wording only, offline, nothing installed)**: the card
  and the documents said that Prepare for power cut "raises a protected reserve (never lowers it)". That over-stated it. The raised reserve is the reserve ECCO's
  plan uses (`sensor.ecco_plan_effective_reserve`: the larger of the owner's reserve and a running power-cut reserve, each rounded up). The trusted backend refuses
  the scheduled Dump to Grid start and the card's guarded manual start when that reserve cannot be read, is not a finite number from 0 to 100 or is too high for the
  Stop SOC, and raises the Stop SOC the scheduled start stages to at least that reserve. No override changes the inverter's own reserve or any inverter setting,
  stops the house using the battery, stops the battery charging or discharging or charges the battery, and none binds the dongle's own Start button (the known
  unresolved limitation, RG-ST3). Hold battery and Skip tonight gate ECCO's own scheduled and guarded export starts only. The card's blurbs and its Quick overrides
  note, the plan view's effect and status texts, the card README, the plan-core README and the comments of the plan helper package now say so; the Stage 3
  limitation sentence, the statements that an override never charges and the refusal text "an override never lowers a reserve" (true there) are unchanged. The card
  bundle was rebuilt (only the changed strings differ), the card README pair and the bundle pairs of `epc2` were re-derived and `epc2` and `epc3` re-sealed; no pin
  assertion, scan, gate or hash of a frozen file was edited. One card test compared the exact old effect text (`planOverrides.test.ts`) and now compares the new text.
- **Stage 3 known limitations written down, and the wording checks (finding list of the independent review of 18 Nov 2026; docs and a static suite only, no package or script change)**:
  `frontend/ecco-plan-core/README.md` has a new section "Known limitations (stated, not fixed in this change)" with 18 numbered items, each with its direction of
  failure (fail open or fail closed) and what the owner would see: an unreadable input falls back to the other value in the effective reserve; raise-only is compared with
  the owner's reserve only; start and cancel can interleave; the guarded start has no press error handling and no success text; the card's own Start button is unguarded unless
  `guarded_start` is set; an override's start is floored to the minute; the seed marker is a plain helper; the `owner_reserve` attribute rounds half to even; a reserve in
  (0, 0.0001) was suspected to read as unreadable (not reproduced: see the bullet below); the schedule packages' start-time reads were not reviewed for the clock-change day; the `timestamp` attribute is modelled, not live-proven;
  the press-time recheck is not atomic; and six smaller ones. The card README points to it. `test_ecco_stage3_limitation.py` has a new section [6] (additive): the corrected
  wording stands at each place that carries it, "protected reserve" (any case) is absent from the card sources, the bundle, both READMEs and the plan helper package, the
  inverter's-own-reserve statement stands in the card text and the plan-core README, the section exists with all its items, and the Stage 3 limitation sentence is still in every
  place; each new check fails on the tree without the change (shown on a scratch copy). Nothing existing was edited or loosened; the card README pointer is a re-derived pair
  of `epc2`, which was re-sealed with `epc3`.
- **Stage 3 follow-up to the second independent review of the fixes (18 Nov 2026; running checks, comments and documents only, no package logic line; offline, nothing installed)**:
  the re-review of the four Stage 3 fix commits found the fixes correct in the offline model and asked for honest wording and four more running checks. **Wording:** the
  comments of `ecco_plan_helpers.yaml` and the CHANGELOG no longer say the helper's `timestamp` attribute is the true instant without a caveat; they state the residual that a
  restart inside the repeated hour of the autumn clock change may restore an expiry an hour early (as recalled from Home Assistant core, not verified, not modelled), as an open owner
  decision and a supervised-check item, and the first CHANGELOG bullet above now calls a missing attribute an unreadable record that is stricter than before (a valid state with no
  attribute used to be readable) instead of calling it the same as an unparseable state. The header comment of `ecco_dump_to_grid_schedule.yaml` says that the press-time recheck runs on every attempt (the first included), that a momentarily
  unreadable sensor costs that night's scheduled export, that the staging stays on the dongle, and that a run BLOCKED at the press-time recheck whose Dump to Grid is found active when the
  loop ends has its BLOCKED text overwritten with STARTED OK (no alert, schedule notification dismissed, nothing pressed by the script). The comment text is declared in `epc2`'s header
  pair, so the pair's `after` text, the epc2 package checkpoint and the `epc2` and `epc3` fingerprints were re-derived and re-sealed with `_pex.sealed`; the epc2 reverter still lands byte for
  byte on the r9 state. **Known limitations:** the plan-core README section now has 22 items. Item 9 (a reserve in (0, 0.0001)) was written from a task text; run against the current
  packages and simulators it is NOT a failure (the value reads as a number and is published as 1), and the item now says what was reproduced and what was not examined. Item 10 (the
  schedule packages' start-time reads on the clock-change day) now says what was read and that the rest was not examined. Item 11 is reworded; new items 19 (the restart inside the repeated
  hour), 20 (the press-time BLOCKED text overwritten by STARTED OK), 21 (the cost of a momentarily unreadable sensor at press time) and 22 (the leftover staging). `test_ecco_stage3_limitation.py`
  [6] requires all 22 items by name (never fewer than before), the status wording of items 9, 10 and 19 to 22, and the new comment and CHANGELOG sentences, each shown to fail on a copy
  without them. **Running checks (tests only):** `test_ecco_plan_enforcement.py` [11] (+10) and `test_ecco_r9_stage3_composition.py` [17] [18] (+61) force the hold sensor and the effective
  reserve sensor themselves to unavailable, unknown, empty and junk (and nan, inf, 150, -5) during the wait, on the on-time start and the watchdog's rescue, busy and offline: each ends as
  BLOCKED with the right code and no press; the mutant that survived the review (`h != 'clear'` changed to `h == 'unknown'`) and five more are caught; a running pin, labelled as documenting
  and not approving, records the STARTED OK overwrite above. `test_ecco_plan_helpers_package.py` [13] (+13) removes the state guard at each of the ten timestamp read sites in turn (the three
  that survived the review included): each removal is caught by the running check of that site. Nothing existing was edited or loosened (a check label was reworded where a sentence
  became untrue; its assertion is untouched).
- **Stage 3: a press-time BLOCKED result stays BLOCKED (owner decision r14, 19 Nov 2026; known limitation 20 fixed; offline, nothing installed)**: the step after the scheduled Dump to Grid
  start's retry loop no longer replaces a result that starts with BLOCKED by STARTED OK when Dump to Grid is found active (started from the dongle's own Start button, still not bound (RG-ST3), or
  by hand). The text stays as the press-time recheck wrote it, the end-of-run alert is raised as for any BLOCKED result, the schedule notifications are not dismissed and the write enable still
  ends off; the script presses nothing. The alert's message gains ONE sentence, only while Dump to Grid is active at that moment: it is active now, this run did not start it, check it and the plan
  overrides before assuming it is held (it therefore also appears on the alert of a start-time BLOCKED result when Dump to Grid is active). STARTING, FAILED and CANCELLED results keep their old
  rule (replaced by STARTED OK while Dump to Grid is active). This supersedes what the two bullets above say about the overwrite. `test_ecco_plan_enforcement.py` [12] (+23 checks net, 13 mutants, the
  old overwrite among them) replaces the [11] pin of the old behaviour and fails on the previous package; `test_ecco_stage3_limitation.py` [8] (+41) states the new wording. Two declared edit
  pairs were added to `epc2` and its header pair re-derived, then `epc2` and `epc3` were re-sealed; no pin assertion, scan, gate, threshold or hash of a frozen file was edited.
- **Stage 3: a STARTING, FAILED or CANCELLED result is no longer turned into STARTED OK either (owner decision r15, 19 Nov 2026; known limitation 20 extended; offline, nothing installed)**: the step
  after the scheduled Dump to Grid start's retry loop replaced EVERY result but STARTED (BLOCKED excepted since r14) by "STARTED OK - Dump to Grid is active; this run could not confirm the start as
  its own ..." whenever Dump to Grid was active (started from the dongle's own Start button, still not bound (RG-ST3), by hand or another path), so a start refused at the gate, a press nobody
  answered, a run the owner cancelled and a run still retrying were reported as a success. Now the steps after the loop write no success text: a FAILED or CANCELLED result stays exactly as written; a result that is still
  STARTING with Dump to Grid active (no verified start of this run) becomes CANCELLED if the owner cancelled the schedule, else a FAILED TO START text that says the retries ended, repeats the last status
  and says Dump to Grid is active now and this run did not confirm that it started it (within 255 characters), so the end-of-run alert fires and the schedule notifications stay; a result another
  writer left (ARMED, REJECTED, MISSED) is left alone. STARTED OK is written only in the loop, after this run's own press, a start transaction that began and Dump to Grid active: unchanged in every shape.
  The alert's active-now sentence stays true for each result it can accompany: for BLOCKED "this run did not start it", for FAILED "this run did not confirm that it started it" (an unconfirmed outcome can be
  a late start of this run's own press, a false negative the alert flags). With Dump to Grid not active nothing changes (compared run for run with the previous package). This supersedes the sentence of the bullet above that says
  STARTING, FAILED and CANCELLED results keep their old rule, and what the two earlier Stage 3 bullets say about the overwrite. `test_ecco_plan_enforcement.py` [14] (the table of 19 result texts x Dump to Grid active or not
  x armed through the package's own steps, 12 end-to-end runs, 7 shapes of a verified start, 22 mutants) and [12] (its three controls replaced by the opposite expectation, the old overwrite now a mutant for each class) fail on
  the previous package; `test_ecco_stage3_limitation.py` [10] states the new wording. The `epc2` pairs of the schedule package (header, post-loop step, alert message) were re-derived, then `epc2` and
  `epc3` were re-sealed; no pin assertion, scan, gate, threshold or hash of a frozen file was edited. Not changed: the Free Power schedule package has the same fallback text; the startup recovery after a Home
  Assistant restart writes its own "STARTED OK - running" when Dump to Grid is active inside the window.
- **Stage 3: an override's expiry is also an absolute epoch record, read raise-only (owner decision r14, 19 Nov 2026; known limitations 19 and 23; offline, nothing installed)**: each override's
  expiry is now held twice, as the date-and-time helper and as an absolute epoch record (an input_number per kind, the same number the start script already computes, written before the
  date-and-time expiry; the cancel script writes the cancel instant into both). Every read (the hold sensor's state and `held_by`, the effective reserve and the cancel script) takes the later
  of the two valid instants, so a restart that restores the date-and-time expiry an hour early in the repeated hour of the October clock change (recalled, modelled offline, not verified)
  no longer releases the override early, and nothing is extended or shortened. A kind with either source unreadable is unreadable (the hold reads unknown, which refuses, unless another
  record holds) and the power-cut reserve stays raised until a cancel or a readable record reconciles it (it was skipped before). This supersedes what the earlier bullet about the timestamp
  attribute says about the residual and the open owner decision. The card is not changed: it reads the attribute only and may show an override as ended up to an hour early after such a
  restart (new known limitation 23, display only; the backend decides). The dongle's own Start button is still not bound by any override (RG-ST3). `test_ecco_plan_helpers_package.py` [14]
  (33 mutants), `test_ecco_plan_enforcement.py` [13] and the helper, limitation and proposal suites carry the checks; the helper package is an added file of `epc2`, so no pin changed.
- **Stage 3: the card offers the guarded Cancel for an override the backend holds only through its epoch record or cannot read, with a readback of both records (owner decision r15, 19 Nov 2026; known limitation 23 fixed; offline, nothing installed)**: the Energy Actions card
  now reads the three epoch records next to the date-and-time records and mirrors the backend's read rule: the later valid instant wins; a kind is running while either record is in the future, held by Home Assistant when a record cannot be read, and ended only when both are readable and
  neither is in the future; an older package without the epoch records is judged by the date-and-time record only, and the card says so. For a running or held kind it offers the same Cancel as before, through the existing guarded cancel path only (`script.turn_on` on the cancel script with
  the stored revision; no new service, no second control route, no direct helper write), and after the call it reads back the plan revision and BOTH records and says plainly Cancel confirmed, Cancel sent (pending) or Cancel NOT confirmed, quoting the script's own answer when it refused.
  This supersedes the sentence of the r14 bullet that says the card is not changed (known limitation 23, display only; the backend decides). The card bundle was rebuilt; `epc2` and `epc3` were re-sealed; no pin assertion, scan, gate, threshold or hash of a frozen file was edited.
  Modelled and tested offline only (`frontend/ecco-energy-actions-card/test/planEpochCancel.test.ts`, with source mutants), not seen in a browser or on a real Home Assistant. The dongle's own Start button is still not bound by any override (RG-ST3).
- **Stage 3: the startup recovery never writes STARTED OK over a result this schedule did not verify (owner decision r15, 19 Nov 2026; known limitation 20, the last path; offline, nothing installed)**: after
  a Home Assistant restart the scheduled Dump to Grid package's startup recovery wrote "STARTED OK - running (Home Assistant restarted during the session)" whenever the schedule was armed, now was inside the
  window and Dump to Grid was active, whatever the last result was, so a refused (BLOCKED), failed, cancelled or restart-killed STARTING run read as a success when the dongle's own Start button (still not bound
  (RG-ST3)), a manual start or another path had started Dump to Grid. Now only a last result that already starts with STARTED (this schedule's own verified start, recorded before the restart) keeps that text and
  the disarm, byte for byte; a result that starts with FAILED, BLOCKED or CANCELLED is final and stays exactly as written (the schedule is still disarmed; no alert is added, because the text, and for FAILED or
  BLOCKED the status FAILED once Dump to Grid is not active, stay visible); every other result (STARTING, ARMED, empty, REJECTED, MISSED, foreign text) becomes an UNCONFIRMED text that says Dump to Grid is active
  after a Home Assistant restart and that this schedule did not confirm that it started it (within 255 characters). The recovery presses or starts nothing, and every other branch and every case with Dump to Grid
  not active is unchanged. This supersedes the sentence of the r15 bullet above that says the startup recovery was not changed. Still true: the Free Power schedule package still has its own old fallback and recovery,
  unchanged and outside this change, and a FAILED text can be a false negative (the dongle started late after a start transaction that began). `test_ecco_plan_enforcement.py` [15] (the real recovery for 25 result
  texts x Dump to Grid active or not x armed x where now is relative to the window, compared with the previous package; 5 end-to-end runs through the real start script, a restart and the recovery; 23 mutants, the old
  unconditional write among them) and `registry/tests/test_ha_r9_missed_runs.py` (the one check that pinned STARTED OK for a session the dongle's own button started is replaced for the Dump to Grid package by the
  opposite, the old write now a mutant) fail on the previous package; `test_ecco_stage3_limitation.py` [12] states the new wording. Two notes were added to known limitation 23 (a record that ends inside a minute can
  make the card offer Cancel for up to 59 seconds after the backend cleared it; on a new package with an epoch helper entity missing the card may show a kind as cleared without a Cancel). The `epc2` pairs of the
  schedule package (the header pair re-derived, one pair added for the recovery branch) were re-derived, then `epc2` and `epc3` were re-sealed; no pin assertion, scan, gate, threshold or hash of a frozen file was edited.
- **Stage 3: known limitation 10 (the schedule packages' start-time reads on the clock-change day) was examined offline and rewritten (owner decision r15, 19 Nov 2026; documentation only, nothing changed, nothing installed)**: SUPERSEDED IN PART on 20 Nov 2026 (owner decision r30, see the next bullet): this bullet
  records what was true on 19 Nov 2026, before R9; since then the refusal of a skipped, repeated or unreadable start label (P-A) and the TOU walk on the real instants (P-B) have been implemented offline in R9, so
  the findings below about the start label, the misleading refusal text when arming in the second 01:xx hour and the TOU walk, and the sentence about the proposals, are replaced for P-A and P-B by the next bullet. The
  item said that these reads were not examined. A zone-aware (Europe/London) offline harness ran the packages' own template expressions and the repository's simulators on 28 Mar 2027 (spring forward), 31 Oct 2027 (fall back) and the past
  25 Oct 2026, each with an ordinary-day control. Reproduced and exact: every window end, retry deadline, run length and plan override expiry is epoch arithmetic (nothing is extended, shortened or started twice, also around a restart).
  Reproduced then (before R9) and NOT fail closed: a start time typed as a skipped or repeated local label is read as the first reading of that label and is not refused (a skipped 01:30 starts at 02:30 BST, 60 minutes later than typed, while the ARMED text
  still shows 01:30), and the TOU overlap check of the Dump to Grid arm validation walks the window as continuous wall-clock minutes (a false accept on the spring day, a false refusal on the autumn day, older than R9; the dongle
  firmware's start gate walks the same way, reasoned from the code and not run, so there was no backstop on 19 Nov 2026). Reproduced and FAIL CLOSED: arming in the second 01:xx hour for a time inside it (with a misleading text), a Home Assistant start in
  the second 01:xx hour (never captured for R9, so for that boot the watchdog does not rescue a lost on-time start) and Skip tonight pressed 07:00 to 07:59 on the day before the autumn change (EXPIRY_ABOVE_CAP). NOT EXAMINABLE offline: the
  real Home Assistant time-trigger rule, its process time zone for the naive-string read, whether a date-and-time helper accepts a skipped time, its restore after a restart, and the dongle's timers and TOU gate across a clock change.
  PROPOSED on 19 Nov 2026, each needing the owner's decision (the first two, P-A and P-B, were implemented offline by R9 on 20 Nov 2026: see the next bullet; the others are not implemented): refuse a skipped, repeated or unreadable start label at arm time (P-A); an epoch-correct TOU walk or a refusal when the window spans the change (P-B); documentation of the second-hour
  capture loss and of the Skip tonight cap; a supervised read-only template check of the three conversions (P-F). The next clock change is 28 Mar 2027. This supersedes the sentences of the earlier bullets that say these reads were
  not reviewed or not examined for the clock-change day. Only `frontend/ecco-plan-core/README.md` (item 10 and the Known limitations introduction), this file and `test_ecco_stage3_limitation.py` [13] (the new wording required; the old wording
  forbidden and a killed mutant) changed: no package, card, bundle, pin assertion, scan, gate, threshold or hash of a frozen file was edited. The dongle's own Start button is still not bound by any override (RG-ST3).
- **Stage 3: known limitation 10 now says which clock-change refusals and checks R9 implements offline (P-A, P-B), what is not verified on a real Home Assistant and what is unchanged (owner decision
  r30, 20 Nov 2026; documentation and its static check only, nothing installed)**: the owner approved updating the wording of limitation 10 after R9 (merged into this branch) changed the two schedule
  packages offline, keeping offline proof and real Home Assistant verification apart. Implemented offline in R9: P-A (arming refuses a start time that is a skipped, a repeated or an unreadable local
  time, in both schedule packages, before 'must be in the future', so arming in the second 01:xx hour for a 01:xx start still fails closed but with the clock-change text) and P-B (the Export to Grid
  package's arm-time TOU overlap check walks the run on the real instants; the Charge Battery package has no such check). The proof is offline only: the repository's own simulators under the real
  Europe/London zone, an independent oracle (every real UTC minute of each change day walked, counting how often each wall-clock label occurs) compared with the real arm validation label by label
  (each of the 1440 wall-clock minute labels of a day armed once: exactly the 60 skipped or repeated minutes of 28 Mar 2027, 31 Oct 2027 and 25
  Oct 2026 are refused, none on an ordinary day), failing-first runs on the unchanged packages and mutants. Not verified on a real Home Assistant: how its template functions read a naive local time
  and which zone they use (recalled, not verified), its time trigger, whether a date-and-time helper accepts a skipped time and its restore after a restart; P-F, the supervised read-only template
  check, is still open. Unchanged: the dongle firmware's START gate (it still walks the TOU window the old way; a flash is a separate decision), the arm-time-only check (a start helper edited while
  the schedule is armed is not checked again), the unreadable-table case (the Export to Grid TOU walk runs only when the TOU slot table can be read; otherwise the package does not walk the window
  and the arm defers to the firmware's own gate, as before; whether an unreadable table should fail closed stays an open question for the owner, not decided here), the repeated-time probe
  (a constant one-hour shift: the UK only), the second-hour capture loss, the Skip tonight cap and the epoch arithmetic of every
  deadline. This supersedes, for P-A and P-B, the sentences of the r15 bullet above that say a skipped or repeated start label is not refused, that arming in the second 01:xx hour gets a misleading
  text, that the TOU overlap check walks wall-clock minutes and that the proposals are not implemented; the r15 bullet stays the record of 19 Nov 2026. Only `frontend/ecco-plan-core/README.md` (item 10 and the Known limitations introduction), this file and
  `test_ecco_stage3_limitation.py` changed: its check [13] and the item 10 phrases of its check [7] were replaced by stricter ones (the r15 sentences that R9 made false are forbidden texts and killed
  mutants, the new facts are pinned one by one, the claims about the packages are tied to the package text, and the wording is checked by a word-list guard that catches the
  common over-claims (defence in depth, not a proof that no over-claim can be written); its section [13b] holds the killed mutants of the review fixes): the pin of the wording is stricter. No
  package, card, bundle, scan, gate, threshold, pin-chain declaration or hash of a frozen file was edited. The dongle's own Start button is still not bound by any override (RG-ST3).
- **Dashboard preservation gate** (`tools/ecco_dashboard_guard.py`, fail closed): `deploy-ha.ps1` / `deploy-dashboard.ps1` refuse, before any remote write, a dashboard that drops a site's protected layer (site-local host policy `/config/ecco/site-local/dashboard-protection.json`, never in the repository), a required resource or a custom card type the live dashboard uses, and re-verify after the install; `apply` / `make-policy` carry a site layer onto a new render ([docs/user/site-render.md](docs/user/site-render.md)).
- **Dashboard preservation gate, hardening**: `deploy-ha.ps1 -AllowDriftRecovery` (guard `check --allow-drift-recovery`) passes, with loud warnings, a candidate that restores the site policy's protected layer exactly over a live file that drifted from it (never a candidate without that layer; without the switch drift still blocks); an optional gate pin (`-ExpectedSiteGate`, or the git-ignored `ecco_dashboard_gate.local.txt`) refuses a dashboard that would pass under any other gate, so a host policy moved aside cannot fall back to `DASHBOARD_PRESERVE_GATE` silently (while the policy is deliberately aside, `-ExpectedSiteGate DASHBOARD_PRESERVE_GATE` is the one-run override; the pin stays); `ecco_deploy_preflight.py plan --site-policy` prints the guard's `apply` step before the dashboard deployment, checks in memory that it will succeed (including the post-condition), and on a re-run into the same `--out` deploys the applied file already there or fails when that file is not `apply`'s output ([docs/user/site-render.md](docs/user/site-render.md)).
- **Intelligence SHADOW v0.1, contracts** (offline, SHADOW only, applies nothing): the typed decision register I-D1..I-D9 with
  provenance and acceptance, periods and the DST rules, the advisory contract `ecco-intel-entities/1` with its null rule, the
  authority vocabulary, and S0 reconciled onto them ([docs/intelligence/INTELLIGENCE_FOUNDATION_CONTRACT.md](docs/intelligence/INTELLIGENCE_FOUNDATION_CONTRACT.md)).
  S0 stays a DRAFT: decisions D1-D9 OPEN, thresholds PROPOSED, offline, SHADOW-only, NOT configured runtime policy; its
  examples are synthetic, with fictional values.
- **Intelligence SHADOW v0.1, engine** (offline, synthetic data only): the S1 advice prototype reconciled onto the register, the
  data-quality layer (fault injectors, a seeded fuzz suite, a capture validator that writes an aggregate summary only) and the
  planning layer (tariff adapter, daily plan, baselines, value, advice backtest) behind the frozen `run_cycle`. The charge window
  comes from a read-only grid-charge classification of the inverter's TOU slot table (fail closed: an unknown, stale or
  conflicting slot, enable or overlay blocks the charge advice, no charging period is invented, and a grid-sourced slot is never
  taken as proof that charging will happen) and is cross-checked against a verified import tariff's rate slots (A30, A35, A38:
  a conflicting priced slot blocks; INFO `CHARGE_WINDOW_NOT_PRICED` marks a window that no price check covered whole). Input
  expiry: configuration-poll freshness, `INPUT_EXPIRING` for an item valid for less than the 125 s refresh margin, and the
  inverter clock offset in the charge-window items' validity. V1 example outputs unchanged.
- **Intelligence SHADOW v0.1, Home Assistant runtime and card** (source only; install kit staged, PENDING DP-4; nothing installed
  or deployed): `custom_components/ecco_intelligence` (sensor and binary_sensor only), the kit builder and mock install drills,
  the read-only intelligence card and its standalone dashboard, an end-to-end test of the built kit, and
  [docs/intelligence/INTELLIGENCE_CONTINUATION_GUIDE.md](docs/intelligence/INTELLIGENCE_CONTINUATION_GUIDE.md).
- **Intelligence SHADOW v0.1, Home Assistant presentation** (post-export entry `isp1`; nothing installed or registered): the
  presentation package `home-assistant/packages/ecco_intelligence.yaml` (the pause helper, three notification-only alerts and
  a dead-man watchdog that follows the install runbook's gate G8: a 1200 s age bound derived from the runtime's constants, a
  `valid_until` still ahead for a computed status, STARTING bounded by 1200 s, PAUSED fresh while the pause is on plus 130 s;
  the self-test alert stays quiet at a start without the integration), the raise-only reserve helper package
  `ecco_intelligence_prefs.yaml` and the standalone dashboard's registration package `ecco_intelligence_dashboard.yaml`, each
  with its suite. `deployment/ha-manifest.yaml` lists the three packages, the standalone dashboard and the card (manual
  resource registration); `VERSION.yaml` records Intelligence 0.1.0 (SHADOW, applies nothing, not tested in Home Assistant).
- **Intelligence SHADOW v0.1, advice log: a verified write and an incident record** (diagnostics only; offline source; nothing installed
  or deployed; no entity, published value, status, mode or advice changes; it takes effect with the Ghost update's own restart): each
  advice write is read back by its row ids after the commit, on the same connection that wrote it, comparing kind, issue time and
  content hash (a same-connection read-back: it shows that the rows are visible to the writing connection and match what was written;
  it is not a durability or fsync proof and says nothing about what a power loss would keep); a failed or unverified write opens an
  incident (when it began and last failed, the attempts, the slot cycles missed, the exception class name, the issue times of the advice
  that could not be written; the newest 10 are kept in memory and shown in the diagnostics download as `advice_incidents`; a store step
  that times out or raises counts only inside the incident, not in the two counters below). `self_test.STORE_RECORD` is WARN while the
  latest attempt has failed or is unverified and PASS again only after a verified write, when the incident is closed and kept; the
  cumulative counters `advice_write_failures` and `advice_unverified_writes` are history and are never reset (`advice_current_failure`
  is). Closed incidents are written after the next verified write to a small table, `advice_incident` (at most 10 rows), created only
  then; a failed or timed-out write of an incident changes nothing else and keeps it pending for the next verified write (the table keeps
  the newest 10 by the text of `first_failed_utc`: after a backward clock step a new, older incident is stored and pruned at once, a
  known limit); an incident still open at a restart is not in it and lives only in the warning logged when it opened. Every slot cycle's advice
  stays its own row (about 50 a day, 400 days); the old scorecard and the start-up behaviour are unchanged. `advice_export.py --incidents`
  prints the table.
- **Intelligence SHADOW v0.1, data quality: the live power balance can allow for the inverter's conversion** (optional; offline
  and in the runtime's site loader, never run in a real Home Assistant): PV and battery power are DC-side readings and the house
  power is the inverter's output plus the grid CT, so a lossless balance withholds export and Dump advice for a reason that is
  physics. Three optional site facts in the site file's `site` block (`inverter_dc_to_ac_factor`, `inverter_ac_to_dc_factor`,
  `inverter_standby_w`, all or none; factors 0.90 to 1.0, standby 0 to 100 W, inclusive) make the expected house power
  loss-aware, in the balance and in both sign-reversal tests alike. Absent, the rule is the previous rule bit for bit; incomplete
  or invalid facts are reported (`SITE_INVERTER_CONVERSION` WARN, `site-check` PROBLEMS, `POWER_LOSS_FACTS_INVALID` BLOCK on
  export and Dump) and never loosen the check. `intelligence/tools/power_balance_fit.py` fits the facts from recorded history
  (offline, stdlib only). The facts are PROPOSED engineering parameters calibrated per site, not owner decisions.
  `QUALITY_VERSION` is `intel-quality-0.3.2-cfg` so that summaries made before and after are told apart
  ([docs/intelligence/DATA_QUALITY_METHOD.md](docs/intelligence/DATA_QUALITY_METHOD.md) section 10.1).
- **ECCO 3D Energy Flow card, V2** (`frontend/ecco-flow-3d-card`, `custom:ecco-flow-3d-card`; read-only; placed on the
  production Overview by `ovw3`, see Changed; supersedes the V1 prototype of PR #44). An isometric house scene from the
  owner-approved V4 scene pack (ten
  weather / season plates, chosen by date, `sun.sun` and the weather condition, with crossfades; the plates are deployed as a local
  resource, never loaded from a CDN and not stored in this repository) with the live figures and the animated power routes as SVG
  overlays: solar per array, battery (reversing for charge / discharge), grid (reversing for import / export) and home. V2 routing is
  perspective-aware: each building axis is a direction field fitted to the plate's measured edges (`src/scene/perspective.ts`), every
  route segment follows one axis, so every bend is a real-world right angle; the routes follow the plate's own edges, avoid the
  surveyed obstacles, rise into the inverter's underside along the five painted cables, and the house feed ends at the wall light; the
  battery route is hidden only where it passes behind a surveyed obstacle, with its particle timing continuous. Information cards sit
  clear of the equipment and link to it with fine dotted links that breathe slowly, with the card's border, while their flow carries
  power (`scene.links`: `pulse` by default, `particles` or `off`). Reuses the installed Energy Flow card's power model unchanged (sign
  conventions, `resolveHomeW`, PV aggregation, idle threshold, motion curve; pinned by a parity test), the FE-1 time to reserve, the
  Free Power / Dump to Grid session sensors, the TOU slot table, the blended solar forecast and the health sensors. Unknown is `--`
  with a static dashed route; stale telemetry stops every route. All routing is data in `src/scene/routing-v4.ts`, overridable from
  the configuration (`scene.routing`; V1 override keys are not compatible). Preview harness, headless capture, 86 Node tests and
  `tools/tests/test_flow_3d_card.py` (folder shape, read-only allowlist, repository-sourced entity ids, isolated routing, site render,
  scope). Preview-dashboard install and upgrade steps: `frontend/ecco-flow-3d-card/INSTALL_PREVIEW.md`. The V2 merge itself changed no
  firmware, Home Assistant package, dashboard or registry file.
- **Advanced Configuration Stage 1, midnight-crossing hold** (post-export entry `acs1x`; offline, source only, corrected for an
  independent review's findings and awaiting its re-check, NOT installed; [docs/dev/acs1x-crossing-hold.md](docs/dev/acs1x-crossing-hold.md)).
  The guarded TOU editor's scripts refuse any start-time edit that would move the midnight crossing (the one slot pair whose next start is
  earlier in HH:MM than its own; slot 5 -> 6 in the owner's layout) to another slot boundary (the owner's restriction, enforced in the
  scripts rather than only by the dashboard or by operating instructions). Approving a supervised relocated-crossing test does not lift
  the hold: only a separately authorised, reviewed and installed code change does. Checked in all four copies of the gate, right after the proposed-layout rule, failing closed on anything unreadable, with
  a plain-language refusal. On the owner's layout it refuses slot 5 moved past midnight and slot 6 moved before it, and changes nothing
  else: target SOC, power and charge-source edits, every other start-time edit, every guard, proof, press, readback and lock keep the
  rules and behaviour acs1c left them, apart from four refusal texts that are reworded (two of them, power and fallback live match, can
  also be the result of target SOC, power and charge-source edits). **Fixed:** four refusal texts that did not fit the last check's 255-character result (acs1c's cycle and neighbour
  refusals, the power and the fallback live match refusals) are rewritten, shorter and never truncated: a refusal there had left no
  result, no notice and no F2 re-Load. Recorded as a third invertible transform on the acs1c text (12 exact pairs, `home-assistant/prototypes/acs-stage1/acs1x_transform.py`); the acs1 and acs1c records are
  unchanged. No firmware, register, write path, dashboard or card change; start times stay display-only in the TOU Settings card.
- **Advanced Configuration Stage 1, cyclic TOU correction** (post-export entry `acs1c`; offline, source only, independently
  reviewed offline on 2026-10-25/26, NOT installed, NOT live-proven; [docs/dev/acs1c-cyclic-tou.md](docs/dev/acs1c-cyclic-tou.md)). The editor's start-time
  ordering rule becomes one 24-hour cycle in slot order (every start on the 5-minute grid, every slot at least 5 minutes, exactly one
  wrap past midnight; the new start strictly between the previous and the next slot's start counted round the clock, slot 6 before
  slot 1; the proposed layout itself one cycle; the active-slot-now guard in unwrapped minutes), instead of strictly ascending HH:MM
  values, which refused every start-time Review of the owner's live layout (slot 5 running 22:00 -> 00:25). Every other guard, the
  staged-equals-live proof, the one quiet-window press, the readback, F1 / F2 and the lock are unchanged; the written value is still
  the typed HH:MM on the grid; every copy of the gate also re-checks that the review record's value is a well-formed HH:MM on the grid
  (a hand-edited record is refused by the gate itself). Recorded as a second invertible transform on the Stage 1 text (21 exact pairs,
  `home-assistant/prototypes/acs-stage1/acs1c_transform.py`); the acs1 transform, pins and chain entry are unchanged. No firmware
  change, no new register or write path. Policy P3 ("strictly ascending") is superseded only on the owner's approval after review.
- **ECCO TOU Settings card** (post-export entry `acu1`; offline candidate, NOT installed, NOT exercised in Home Assistant, NOT
  live-proven; `frontend/ecco-tou-settings-card/README.md`). Section 7 of the Inverter / Advanced view (dashboard 7.22.0, staged) keeps
  its heading and replaces the read-only TOU table with the card: the six live slots (window, power, target SOC, charge source, mode,
  freshness, the active slot) and a guarded editor for the target SOC, the power and the charge source of one slot through the
  installed ACS1 editor scripts only - Review (writes nothing), the typed confirmation phrase, Apply, and Acknowledge after an
  UNCERTAIN outcome - each as one `script.turn_on`. The card holds no safety logic of its own (every gate stays in the scripts and the
  Review's refusal is shown verbatim), reports success only on the editor's `APPLIED AND VERIFIED`, binds Apply to the slot, setting and value reviewed
  in that card (the one-time code is read from the live plan record), enforces a fixed provisional 300 s spacing after every Apply that passed the editor's first gate, whatever its outcome (a REFUSED Apply
  adds none; not a firmware rule, not configurable), offers Undo only when
  the result text, the owner-edit record and a current live read agree (a value reported recently, or unchanged under a
  current configuration poll), keeps start times display-only (the site's layout wraps midnight,
  L1) and explains the shadow latch only on the Review's own refusal (owner decision D3, reading the FB-C3 display decoders, could
  not be implemented: the FB-C3 suite pins those decoders out of every frontend file). The dongle's `YYYY-MM-DD HH:MM:SS` Europe/London poll time is parsed explicitly as Europe/London (the same in every browser zone and
  across GMT / BST), cross-checked with the entity's UTC `last_changed`, and fails closed when unparsable or in the future; the slot clock,
  the clock-change nights and the scheduled starts are read on the same London clock. One manual `frontend_assets` stanza in the deployment
  manifest; the read-only Advanced / Experimental Configuration card (section 13) is unchanged. Owner decisions D1-D9 of 2026-10-25
  (D5 and D6 refined) are recorded in the chain entry's note. No firmware, Home Assistant package or registry change.
- **Advanced Configuration Stage 1: the guarded TOU settings editor** (post-export entry `acs1`; offline, source only, NOT installed,
  NOT live-proven; [docs/dev/acs-stage1-integration.md](docs/dev/acs-stage1-integration.md)). It replaces the Stage 0 target-SOC editor
  at the same package path (`ecco_tou_target_soc_edit.yaml`, so the deployment manifest is unchanged): one setting of one TOU slot per
  request - the target SOC as before, the power (500-8000 W in steps of 100), the start time (5-minute grid) or the charge source
  (None or Grid) - through the existing verified manual TOU firmware path, with the same review, typed confirmation, fresh read,
  staged-equals-live proof, one Apply in a quiet gap of the Modbus poll cycle, firmware readback plus two later reads and manual-review
  lock. No firmware change, no new register or write path.
  - The scripts are renamed `script.ecco_cfg_review_tou_slot_setting` (fields `slot`, `setting`, `value`) and
    `script.ecco_cfg_apply_tou_slot_setting`; the helpers, the acknowledge script and the watchdog automation keep their ids.
  - **Target-SOC behaviour differs from Stage 0 in three ways** (every other Stage 0 refusal and outcome is unchanged):
    - it is refused 00:00-03:00 local on the UK clock change nights (last Sunday of March and of October), as is every setting;
    - it is refused when the slot's raw flags are unreadable (they are needed by the charge-source verdict, so they are now a
      precondition for every setting);
    - the "inverter shutdown SOC unavailable", "ECCO reserve unavailable" and "live slot SOC unavailable" refusals now apply to
      target-SOC edits only (they are that bound's inputs); the other Stage 0 refusals apply to every setting.
  - **Stricter than Stage 0 (also for SOC edits): "nothing pressed" is no longer taken to mean "no manual-path write".** The Manual
    Configuration Write Enable is shared and the firmware accepts ANY Apply press while it is on, so an Apply by someone else can land
    while the editor is armed. When a run stops after staging and before its press, the editor now disarms at once, waits 35 s for
    the firmware's gate-pass counter to publish, and reports "nothing written" (no manual-path, armed write; the automatic RTC clock
    writes do not use the write enable and are outside this proof) only if that counter is unchanged since before the staging and
    no write was seen; otherwise the outcome is UNCERTAIN, the editor locks and the notification lists the observed values.
  - The package is derived from the Stage 0 text by 62 exact edits (the 40 reviewed ones plus 22 appended for the follow-ups below); the
    transform is invertible (`unrender_stage1`), which gives the rollback file and the provenance proof without git history.
  - **N2, owner-approved 2026-10-21 (stricter than Stage 0, also for SOC edits):** the success verdict also needs the firmware's
    gate-pass counter to have moved by exactly 1 since before the staging, read at least 37 s after the Apply press (the counter publishes
    every 30 s). Another Apply (possibly of a different slot) that passed in the armed window, a counter that did not move, was reset or
    cannot be read gives UNCERTAIN, the lock and the manual-recovery notification, with no undo offer and no F1 Load. The one documented
    exception is another actor's Apply that wrote the reviewed staging while the editor's own press was refused: delta 1, APPLIED.
    N1 was accepted at the same time: the write-seen helper and recorder automation stay as built.
  - **Owner-approved follow-ups (2026-10-20):**
    - **F1:** after a verified start-time edit of slot N the editor presses Load Current Slot N-1 (slot 1 -> slot 6) once and checks
      that slot's staged end; when the Load is refused or does not match, the edit stays successful and the notice says plainly that
      the staging could not be refreshed. It writes no register, never arms and never presses an Apply.
    - **F2 (conditional):** after a FAILED run the editor re-Loads slot N only after a PROVEN outcome: a stop before the Apply press with
      the firmware's gate-pass counter unchanged since before the staging (after it published) and no write seen, or the firmware
      refusal proven by its text, an unchanged counter and both later reads. Never after an UNCERTAIN, partial or unproven outcome,
      and uncertainty is never cleared automatically. Adds the helper `input_boolean.ecco_cfg_edit_write_seen` and the automation
      `ecco_cfg_edit_write_seen` (a record of any manual-path write seen while an edit is in flight).
    - **F3:** a power edit is refused when the live slot power is not a multiple of 100 W.
    - **F4:** the Review notification says not to use SmartDeye or the inverter's own panel until the edit is finished, and warns that
      a charge source set on a slot makes a Dump to Grid whose window overlaps it refuse at start (charge source -> Grid, and a
      start-time edit on a slot whose live source is not None).
  - **Owner decisions of 2026-10-21:** D1 the 2026-10-12 reserved-token amendment (Option A), first given for a SOC-only editor, is
    re-approved for the wider editor (the package reads exactly the same six ids in the same three files); D2 the chain entry `acs1`; D3 ACS0
    is replaced by the single Stage 1 editor; D4 DCO sign-off (the owner's); P1 power 500-8000 W in steps of 100; P2 charge source None /
    Grid only (no generator is connected); P3 the start-time and inverter-clock rules; P4 the clock-change-night guard, SOC edits included.
    **Still open:** I1 install by restart or by reloads; I2 the manifest comment; I3 the supervised live proof; I4 push, pull request, merge,
    install and each live step (each needs its own authorisation).
- **Read-back gate for the manual Lovelace resource switch** (`tools/ecco_deploy_preflight.py verify-resource`, read-only;
  [docs/user/site-render.md](docs/user/site-render.md#card-bundles-the-resource-read-back-gate)). Copying a card bundle and
  checking that it is served change nothing a dashboard loads until its resource points at the new file, and no ECCO tool edits
  resources.
  - Usage: `verify-resource --plan plan.json --resources <persisted list read back now> [--before <pre-change capture>]
    [--base-url <HA URL>]`.
  - For each planned card it checks that exactly one resource loads the card, that its URL and type are the plan's, and that the
    read-back is fresh. With `--before`, the entry kept its id and type and no other resource changed. With `--base-url`, the
    bytes served at that exact URL match the plan's sha256.
  - One fixed line per card. `RESOURCE VERIFIED <tag> -> <url> (id <8>, persisted, read back at <UTC>)` is printed only when the
    whole run passes. Otherwise it prints `RESOURCE NOT SWITCHED <tag>: still <url>` or
    `RESOURCE NOT VERIFIED <tag> -> <url>: <reasons>` and exits non-zero. A card install is reported done only after it passes.
  - It writes nothing, and its only network use is the optional GET. `tools/tests/test_ecco_deploy_preflight.py` covers, with
    synthetic fixtures: a pass, not switched, another resource changed, added or removed, a changed id or type, a duplicate card
    resource, a served-sha mismatch and a stale read-back.
- **Firmware source assembler and navigator (S2a, tooling only)** ([docs/dev/firmware-source-modules.md](docs/dev/firmware-source-modules.md)).
  `tools/assemble_firmware.py` splits the production firmware YAML into ordered region fragments grouped by review area and
  reassembles them byte for byte, fail closed. It also maps lines, ids and device-log positions to areas (`--map`, `--where`,
  `--lookup`, `--xref`, `--diff-regions`). `tools/firmware_areas.yaml` is the reviewed item-to-area map.
  - Areas are review and navigation boundaries, not safety isolation.
  - No firmware file is created or changed: fragments exist only in caller-chosen directories outside the repository, and
    the monolith stays the only file ESPHome, the write-surface analyser, the S0 checker and the proof chain read.
  - New suite `tools/tests/test_firmware_assembly.py`: the S1 acceptance checks A1-A8 and negative controls N1-N14 on
    derived plans (no firmware shape pinned), path safety, line endings, navigation and an AST safety scan.

- **The owner's manual Dump to Grid / Free Power values restored after a scheduled start** (post-export entry `smr1`;
  [docs/dev/schedule-manual-restore.md](docs/dev/schedule-manual-restore.md)). A scheduled start stages its own values into
  the dongle's single set of request numbers, which the manual controls share, and nothing put the owner's values back
  (after a scheduled Dump with Stop SOC 15 % the manual Stop SOC read 15 % instead of the owner's 10 %).
  - A Home Assistant package saves each value a running scheduled start replaces, once per episode, and restores it in ONE
    verified attempt once nothing owns control: no lease, start transaction, pending snapshot or armed write enable, no
    manual inverter write, no scheduled start running.
  - Only a valid saved value is written, and only where the number still holds the schedule's value; the owner's own later
    change always wins.
  - Failures are notified and never retried. An obligation older than 24 h is dropped with a notification, without a write,
    even while something still blocks it.
  - No firmware change; the schedule packages are unchanged; no Modbus, switch, button, script or esphome action.

- **Dump to Grid limits in Home Assistant** (post-export entry `fcc1`; for the fcp1 / fcp2 firmware, not yet flashed;
  [docs/dev/full-capability-controls.md](docs/dev/full-capability-controls.md)).
  - A package that describes the dongle's limits: VALID, NOT CONFIGURED, INVALID or AWAITING CONFIRMATION; the power ceiling
    against the owner's record of the highest supervised, proven level (3000 W until the owner records more); flags for an
    unconfigured export limit and for attention. A persistent notification warns while a Dump schedule is armed but its START
    would be refused. The package writes nothing to the dongle. With the old firmware it reads UNAVAILABLE and stays silent.
  - A separate dashboard for the administrator with the limits, the dongle's own two limit boxes and their arm (write-capable,
    every request validated by the dongle; `require_admin` only hides the dashboard, it is not access control), the restore,
    containment and operator-lockout states, and Safe To Flash, Flash Readiness, Restart Status and Build Identity.

- Advanced Configuration Stage 0 (post-export entry `acs0`; offline, NOT live-proven): a guarded owner edit of ONE TOU slot's
  target SOC (register 267+N) through the existing, verified manual TOU firmware path (no firmware change, no new register).
  Review (writes nothing) -> typed confirmation with a one-time review code -> Apply: a fresh configuration read, a Load, the
  Manual Controls helper sync at a fixed point, only the SOC staged, every other staged value proven equal to the live slot,
  one Apply; success only on the firmware's VERIFIED OK plus two later configuration reads (strictly later update times) of
  every written register. The lower
  bound is the greater of the inverter shutdown SOC and the ECCO reserve, read fresh. Refused, fail-closed, in every unsafe
  state (Free Power, Dump to Grid, register 244, recovery, fallback arm / Review / Save, supervision, failback shadow, leases,
  schedules). Any uncertain outcome stops, disarms, alerts and locks further edits until acknowledged; never retried. A run interrupted
  by a restart or reload is caught by a watchdog that locks and alerts at once. The fallback gate parses the live match and the
  Review state exactly (a fresh, trusted, compared verdict; exactly one IDLE Review), so unknown, stale, malformed or incompatible
  fallback state refuses. The owner-approved reserved-token amendment authorises exactly six fallback / failback ids, read only,
  in exactly the editor's three files; five exact allowlist checks are amended (three frozen suites by PEX), nothing else is
  widened. Fresh evidence, not just a connected API: before the Load the Apply requires a live round trip (the dongle's
  own heartbeat count rises) and a genuinely new configuration poll stamped by the dongle's clock, strictly later and within
  120 s of Home Assistant's clock; every gate also requires a current configuration time and heartbeat age. See
  [docs/dev/advanced-config/stage0-safety-case.md](docs/dev/advanced-config/stage0-safety-case.md), the S3 evidence record
  and the supervised live-proof procedure (not executed).
- **Dump to Grid safety hardening, phase 2** (post-export entry `fcp2`; firmware, not yet flashed anywhere;
  [docs/dev/dump-to-grid-safety-fcp2.md](docs/dev/dump-to-grid-safety-fcp2.md)).
  - The closed-loop controller never writes once a lease is ending. An End or restore request that arrives while it is checking
    the inverter before a write now cancels that write (SG-40).
  - The battery runaway guard also judges a window of the last 8 samples. An overshoot that alternates above and below the
    threshold now ends the lease, a skipped or NaN reading no longer resets it, and the decision cannot be missed between two
    watchdog ticks.
  - Above 3000 W the absolute backstop allows for the battery's normal DC conversion loss (a profile value, 12 % for the
    reference profile), so a healthy high-power lease is not ended by mistake. At 3000 W and below it is unchanged.
  - The Dump restore first reads the inverter.
    - It restores only what ECCO still owns, one register at a time when needed, and never overwrites a setting someone else
      changed.
    - If export cannot be proven switched off, it holds ECCO's own TOU power settings at the 500 W floor instead of restoring
      them, and keeps retrying.
    - It asks for Force Restore Original or Accept Current State only once everything ECCO owns has been restored and checked.
    - A repeat after a verified restore no longer rewrites anything.
  - Telemetry that keeps arriving but never changes now ends a Dump lease safely: a grid CT, battery power or SOC that stays
    exactly the same when it should move. After the inverter link comes back, an owed restore is retried at once instead of up to
    5 minutes later.
  - The **Restart** button no longer restarts the dongle in the middle of an inverter transaction, or while a lease, restore or
    recovery decision is owed. An owed obligation (never a transaction in flight) can be overridden with **Restart Override Arm**.
    New diagnostics: **ECCO Safe To Flash**, **ECCO Flash Readiness**, **ECCO Build Identity** and **Restart Status**. The
    `safe_mode:` settings are now explicit, with no change in behaviour.
  - An inverter transaction lock is never released because a timer ran out. A lock held far beyond any transaction's bound is
    reported. If a lease or restore is owed, the lease is ended durably and the dongle restarts so the owed restore completes.
  - Export safety (still a backup to the inverter's own export limit, which ECCO never writes):
    - The maximum grid export guard now works from the first second of a lease and ends it within about a second of one reading
      far over the limit, or of two readings over it.
    - START refuses when the meter already shows export above the limit, when PV alone already exceeds it, or when the target
      leaves no headroom.
  - After the Dump power limits are reported invalid, both the power ceiling and the maximum grid export must be set again.
  - Accept Current State refuses while ECCO's own raised TOU power setting is still in place.
  - The runaway guard also ends a lease on a sustained average excess.
  - A battery idle at exactly 0 W is no longer mistaken for frozen telemetry, but only when the grid meter agrees it is idle.
  - Battery power is cross-checked against the grid meter: net export minus PV is the least the battery must be delivering. A
    battery reading stuck at 0 W (or reading far too low) while the meter shows export now ends the lease within about a minute,
    even with the SOC stuck as well.
  - A change to the Dump power ceiling or maximum grid export is saved to flash at once, before it is reported. A power cut
    straight after a reduction no longer brings the previous, higher value back.
  - After a restart with a restore still owed, the Stop SOC supervision keeps the lease's own Stop SOC, and fails closed when it
    cannot be recovered or the SOC reading is not fresh.
  - The export guard also ends a lease on readings alternating just over and under the limit (two of the last three over, or the
    average of four above it).
  - Statuses and alarms name any externally changed TOU power setting that cannot be held at 500 W while export is not proven
    off.
- **Inverter capability profiles and persisted Dump to Grid operating limits** (post-export entry `fcp1`; firmware, not yet
  flashed anywhere; [docs/dev/inverter-capability-profiles.md](docs/dev/inverter-capability-profiles.md)). One firmware image can
  now serve an inverter's full validated capability, with power levels chosen in Home Assistant instead of by rebuilding.
  - The inverter's Dump capability is a **profile** value (`ecco_dump_capability_w`); there is no global maximum. The reference
    profile is 8 kW, and other profiles are listed in `registry/inverter_profiles.yaml`.
  - New run-time settings, stored and enforced **on the dongle**, so Home Assistant being unavailable never lifts them:
    - **Dump to Grid Power Ceiling** (factory 3000 W);
    - **Dump to Grid Max Grid Export** (factory: not configured, so every Dump START is refused until it is set).
    Raising either needs the new **Dump Power Limits Write Enable** arm and Dump idle; lowering works at any time.
  - Each lease locks its ceiling at START. A later raise never reaches a running lease, and a reduction lowers it at once.
  - An export guard ends a lease whose measured net grid export exceeds the configured limit.
  - Settings that are corrupt, out of range or stored for another profile are refused, never replaced by a larger value.
  - No new Modbus operation or inverter write domain (register 245 is never written).
  - The durable records keep their schemas: the previous firmware can still be flashed back.

- Post-export edit layer (PEX, schema `ecco-pex/1`, foundation entry `pex0`). It is the declared, exact and hash-linked way to change
  files that the `pub0` export froze. The `pub0` proof now runs on the files as of `pub0`, byte for byte. Test and proof
  infrastructure only: no firmware, Home Assistant, dashboard or behaviour change. See
  [docs/dev/post-export-edit-layer.md](docs/dev/post-export-edit-layer.md).
- `ecco_core/` (offline only; no firmware change; no new write path): a host-side reference model with five modules.
  - **State:** raw, normalised and derived observations with source and observation time.
  - **Freshness:** one catalogue of the freshness limits the project already uses, per signal and purpose, each checked
    against its source; limits nobody defined stay unresolved.
  - **Capability:** device capabilities derived only from the capability registry, with unsupported and unknown failing
    closed, plus proof per controller variant.
  - **Authority:** the controller's write authority as one table, checked against the firmware write surface, the
    registry's `read_write` records and the transaction model; plus a pure reference decision model that never
    authorises advisory code.
  - **Bridge:** the single bridge to Intelligence.
- Intelligence V1.1 foundation (shadow, synthetic tests, not yet consumed):
  - the `Advice` explanation format;
  - overnight demand learning with a return-from-away regime check;
  - charge-target advice;
  - Saving Session / export-event advice;
  - reserve-aware Dump-to-Grid stop-level advice.
- New offline test root `ecco_core/tests`.
- Public fallback design basis and stage status,
  [docs/architecture/fallback/FALLBACK_DESIGN_BASIS.md](docs/architecture/fallback/FALLBACK_DESIGN_BASIS.md): the supervision
  model, the durable fallback profile, the Review / Save / Invalidate boundary, Live Match, the zero-authority shadow evaluator
  and its display, the RTC / poll liveness work, what is and is not authoritative, the status of every stage (implemented,
  deployed, live-proven or partially live-proven) and the evidence still owed before operator Restore (FB-E) or automatic
  failback (FB-F), neither of which is implemented. Records and documentation only, declared as post-export entry `fbrp1`:
  no firmware, Home Assistant package, dashboard, frontend or behaviour change.
- **RTC correction-failure health alert** (FB-D1 follow-up; offline only, not live-proven). The `ECCO Health RTC` sensor
  now represents the check `rtc_correction_failures_recent` using the existing firmware sensor "Failed Corrections Since
  Boot". The 90 s RTC deadline breaker increments that same counter.
  - **What triggers it:** an observed increase of the counter.
  - **What it reports:** WARNING with `RTC_CORRECTION_FAILURES_RECENT` for 1800 s. Each further increase restarts the
    window.
  - **What never triggers it:** a reboot reset, the first value after a Home Assistant restart, and an attribute-only
    update.
  - **An unreadable counter** reports UNKNOWN, never HEALTHY.
  - **New attributes:** the failure time, the correction result text at that moment, and the RTC lock max age.
  - **Unchanged:** every other RTC health check and its presentation.
  - **Scope:** Home Assistant health package, check registry and documentation only, declared as post-export entry
    `rtcf1`. No firmware, dashboard, frontend or Modbus change.

- **Failed-start health warning** (FB-D1 follow-up; offline only, not live-proven). A Free Power or Dump to Grid start that
  fails before it writes anything leaves the recovery state at `NONE`, so the Overview could still say SYSTEMS NOMINAL. The new
  sensor `ECCO Health Start Failures` detects it from four existing firmware counters: the Free Power and Dump to Grid start
  attempts and start successes.
  - **What counts:** a rise of unresolved attempts (attempts minus successes) that is still there after the counters were
    quiet for 240 s. The firmware counts an attempt only after every start gate has passed, so a refusal is never counted.
    240 s outlasts a start in flight (success seen within 57 s) plus a silent Wi-Fi loss (the ESPHome client drops the link
    within 110 s). This timing assumption must be re-checked against the live Home Assistant version before deployment.
    The failures-since-boot counters are not used, because they also count failed restores.
  - **What never counts:** a nonzero count, the first values after a Home Assistant start or a reconnection, a counter
    reset, an inconsistent pair, and the free-text status. These only set the baseline.
  - **What it reports:** WARNING with `FREE_POWER_START_FAILED` and/or `DUMP_TO_GRID_START_FAILED` for 1800 s after the
    failed attempt. Each further failure restarts that feature's window; the two features are independent. Unreadable
    counters report UNKNOWN, never HEALTHY.
  - **Registry:** two checks and two reason codes (Dump to Grid sits in `manual_write_system`, because the registry has no
    dump subsystem).
  - **Overview:** the status hero reads the sensor's `reason_codes` and shows ATTENTION with its own subline and a START
    FAILED pill. Every existing reason keeps its subline and priority, and STATUS PARTIAL still comes first.
  - **Scope:** Home Assistant health package, check and reason-code registries, documentation and the dashboard hero,
    declared as post-export entry `fsw1`. No firmware, frontend or Modbus change.
  - **Compatibility:** the scheduled Free Power (fps1) and scheduled Dump to Grid (dgs1) packages retry only gate refusals, which
    are never counted, so their retries and their own failure alerts coexist with this warning (the suite drives both real
    packages against their dongle models). Firmware gate refusals never increment these counters, so this warning does not report
    them; neither scheduler package is changed here. `docs/FAILED_START_HEALTH.md` records the detection matrix, the timing
    contract, deployment, rollback and the passive live acceptance criteria.

- **ECCO Weather & Solar card** (`frontend/ecco-weather-solar-card`, read-only): current weather, the hourly and five-day Met.no
  forecast, sun times, the ECCO blended solar forecast (today, remaining today, tomorrow) with its Solcast and Forecast.Solar
  inputs, an hourly chart of Solcast's profile against actual PV with cloud cover and rain, forecast freshness, the existing
  accuracy scorecard and explanatory notes. It sends only two read-only websocket messages (the forecast subscription and hourly
  statistics); no service call, no new data provider, the blend weighting unchanged. It has its own dashboard view right after
  Overview, declared as post-export entry `wsc1`.

- **The Advanced / Experimental Configuration card is on the dashboard** (dashboard 7.19.0, staged; 7.19.0 also carries the
  Weather & Solar view). It is section 13 of the Inverter / Advanced view: the read-only catalogue of every capability-registry
  record, with live values, evidence and lock reasons, and the Global Power / Export Limit (register 245) panel. The deployment
  manifest lists its bundle (manual copy and resource registration, like the other cards). Declared as post-export entry `acfg1`;
  two older suites' "exactly two frontend assets" pins now read the export-era manifest, with their values unchanged. The card
  cannot write: no Home Assistant service, no Modbus, no firmware change.

- **Battery time to reserve (FE-1, STAGED / NOT LIVE-PROVEN).** A read-only Home Assistant package,
  `home-assistant/packages/ecco_battery_runtime.yaml`, estimates how long the batteries can keep discharging at recent usage
  before they reach the configured reserve (`input_number.ecco_minimum_reserve_soc`, whatever it is set to).
  - **Method:** one battery-power sample a minute while telemetry is fresh. Freshness comes from the dongle's per-poll
    timestamp, which must actually change, because ESPHome does not re-send an unchanged reading.
  - **Usage:** the winsorized mean of the last 30 minutes. Up to 4 one-minute samples of a load (a kettle) are clipped,
    while a load present in 5 or more minutes of the half hour (an oven or hob switching) counts in full.
  - **Direction:** a sustained 8-minute run decides at once; otherwise the usage decides, with hysteresis.
  - **Discharge:** the usage, raised to a sustained run's level, plus a 3-hour allowance for the energy the clipping removes
    (learned only while discharging). The method and its measured error in both directions (short for long on-phases, long for
    a new or a rarely recurring load) are in the documentation.
  - **Capacity:** the configured capacity until the energy per SOC percent has been measured over 15 points of real discharge.
    Measuring restarts on a capacity change or on two agreeing measurements more than 20 % off.
  - **States:** explicit stale, insufficient-data, charging, holding and at-reserve states.
  - **Display:** the Energy Flow card's battery node shows it through its FE-0 hook (`nodes.battery.time_to_reserve`) as one small
    static line such as "≈5h 20m to reserve", with the likely range and "an estimate, not a guarantee" in the tooltip. The
    Overview's battery estimate card adds the summary. Dashboard 7.21.0 is staged.
  - **Safety:** display only. The package has no service call, script, automation or action. No firmware, registry or Modbus
    change.
  - **Bookkeeping:** declared as post-export entry `fe1`. See [docs/BATTERY_TIME_TO_RESERVE.md](docs/BATTERY_TIME_TO_RESERVE.md)
    for the method and its limitations.

### Changed

- **The Overview shows the ECCO 3D Energy Flow card** (post-export entry `ovw3`; dashboard 7.23.0, staged, NOT installed, NOT
  live-proven). Section S3 of the Overview view shows the read-only 3D card (V2, sources and bundle unchanged) in place of the 2D
  Energy Flow card, configured as the card's example, which is the owner-accepted ECCO 3D Preview's configuration: the 2D card's
  nodes, today, format and grid layout settings are kept (not its `card_mod` style; the 3D card styles its own card), its grid
  voltage, connection and frequency are read from `nodes.grid`, and the ECCO status block (Free Power, Dump to Grid, TOU slot,
  forecast, health), the scene pack and the freshness settings are added, in the dashboard's generic entity naming. The inverter's
  output power and state, which the 2D card showed on its face, move into the 3D card's details panel; the status banner (S1) and
  the electrical detail list (S8) keep them at a glance. The card loads through the Lovelace resource the preview already
  registered, so the deployment is the dashboard file alone: `tools/ecco_deploy_preflight.py` now knows the card (`flow-3d`) for its
  dashboard check but leaves it out of its default card list, so a plan stages no copy of its bundle and plans no resource change
  for it. **Prerequisite:** the card's bundle, its JavaScript-module resource and the ten plates under `/config/www/ecco/scenes/`
  must already be installed (`INSTALL_PREVIEW.md` sections 2-3), and production must run dashboard 7.22.0 with this tree's
  other ECCO card bundles and resources installed; check read-only that exactly one resource loads the card, at
  `/local/ecco/ecco-flow-3d-card.<sha256-8 of this tree's bundle>.js` (the plan does not check it; a known limitation). Plan it
  dashboard-only with `python -I -B tools/ecco_deploy_preflight.py plan --root . --site <site> --snapshot <states> --baseline-dashboard
  <live ecco_pro.yaml> --resources <lovelace_resources> --expect-sha <merged sha> --deploy= --out <dir>` (write `--deploy=`: Windows
  PowerShell 5.1 drops the empty argument of `--deploy ""`, and the tool then refuses the command); the plan must stage only `ecco_pro.yaml`, with no card copy, no resource action and no
  restart. Every other section and view is byte-identical; the FE-1 suite's 2D-card wiring pins read the dashboard as of `acs1x`
  (PEX) and new live checks follow the Overview's flow card. No firmware, Home Assistant package, deployment manifest, registry or
  card source change; no service call.

- **The Overview's daily weather forecast opens a day's hourly forecast in the same card** (Weather & Solar card,
  `daily_compact` layout; source only, not installed). Each day row of the Overview's "Next days" block is now a button.
  Selecting one replaces the list with a Back to days control and the date, that day's summary line and its hourly cells in one
  horizontally scrolling strip; the cells are the dedicated Weather & Solar view's own (`hourCell()`, unchanged), fed by the
  same read-only `weather/subscribe_forecast` hourly message. The idle list keeps only the daily subscription; the hourly one
  exists only while a day is open. Days follow the Home Assistant time zone: 2026-10-25 shows 25 hours (01:00 BST, then 01:00
  GMT) and 2027-03-28 shows 23 with no 01:00; missing hours are never filled in, and a day the forecast does not reach says so.
  Focus moves to Back on open and returns to the day row on close. The `full` layout and the solar strip are unchanged; the
  card's Python suite now pins its three local view actions (`chart-day`, `weather-days`, `weather-hours`) and still one
  click listener and no service call. Display only: no firmware, package, dashboard YAML, service call or Modbus change.
  **Deployment:** the card stays a manual Lovelace resource; the new bundle takes effect only once the owner copies it and
  refreshes the resource.
- **Overview V2.1 polish and accuracy pass** (dashboard 7.21.1, staged; display only; re-chained after FE-1 and FPS1, keeping FE-1's time to reserve). ECCO Today and Smart Charge Strategy now
  count only the solar that can arrive before their target time (between 00:00 and the 00:30 target the projected SOC had been
  overstated by about 25 points, because the forecast is for the rest of the current day), say which day the target is, and show
  "Battery data unavailable" or "Projection unavailable" instead of NaN or an unsupported number. The Overview's Battery estimate
  becomes Battery outlook (the learned load-only outlook and how accurate it was), with new Today so far and Coming up cards and
  scheduled-session counters built from existing sensors to fill the empty space beside Energy Actions. The dead SOC Model chart
  series (it read an undefined variable, the source of the browser's "states is not defined" warning) is removed, and a data-status
  strip on the Power Flow charts tells a new day from a sensor that is not reporting. The 7-day outlook score reads the entity ids
  that exist, and the static "Suggested 15%" / "15% starting point" texts show the live ECCO reserve setting. Text that was cut off
  (Grid Status unit, Current Plan countdown, Electrical detail on a phone) now wraps. At four columns Coming up fills the right-hand
  column beside the Energy Flow; on narrower pages an identical copy sits under Electrical detail instead (a Home Assistant screen
  condition at 1696 px: the 1440 px of content at which the sections view switches to four columns, plus the 256 px sidebar), so the
  right-hand column does not become taller than the section beside it. No control path,
  firmware, package or automation changed; declared as post-export entry `ovw2`.
- **The Overview is rebuilt** (dashboard 7.20.0, staged) as nine sections: a compact status banner that keeps the hero's state
  machine, pills and vocabulary and now also reads the Dump to Grid lease states and both recovery-state sensors (a recovery
  condition raises ATTENTION even when no lease flag is set); the Weather & Solar card's new solar strip and compact daily layouts;
  the Energy Flow card, its configuration unchanged, beside a slim Grid Status / Current Plan / Tariff column; the Energy Actions card in
  its new presentation-only `layout: tabbed` (one track visible at a time, both tracks' states always classified, a cross-track
  alert for the hidden one) followed directly by the Known-Good Profile bar; decision support from existing entities; the Power
  Flow chart beside an electrical detail list in place of the four gauges; and one merged System Health card. Display only: no
  control path, firmware, package, automation or service call changed. Declared as post-export entry `ovw1`, which enrols the
  Energy Actions card's source and config in the PEX frozen set (owner decision O3, amended 2026-10-09); the historical
  card-folder and licence pins keep their values and skip the two files the entry adds. **Deployment prerequisite:** the Overview
  now uses the Weather & Solar card, which stays a manual Lovelace resource (it is not in the deployment manifest); register its
  bundle and redeploy the rebuilt Energy Actions bundle before the 7.20.0 dashboard, or the two Overview cards show as missing.
- **Dump-to-Grid command ceiling is configurable at build time.** `ecco_dump_controller_max_ceiling_w` stays the single
  source of truth and keeps its 3000 W default, the only hardware-tested value. A build may select up to 8000 W; values that
  are not a decimal multiple of 100 W, not above the 500 W floor, or above the site TOU ceiling or 8000 W are refused at
  compile time. Above 3000 W everything is **offline only**: 6000 W is the first staged live checkpoint, and 7000-8000 W is
  an architectural capability, not hardware proven. A diagnostic sensor reports the configured value. See
  [docs/dev/dump-to-grid-ceiling.md](docs/dev/dump-to-grid-ceiling.md).
- **The absolute runaway backstop follows the current command above 3000 W.** It was `configured ceiling + 750 W`. It is
  unchanged for any ceiling up to 3000 W, and never looser above it.
- **The W2 fallback-capture warning ("resembles Dump to Grid residue") follows the configured ceiling** instead of a fixed
  3000 W. The W2 wording of the recovery card and of the dashboard's Safety view no longer names a wattage; the dashboard
  line is a declared post-export (PEX) edit of the export-frozen file.
- **The first-run value of the battery reserve helper is 40 %, not 15 %.** `input_number.ecco_minimum_reserve_soc` is still the
  user's own setting (0-80 %, changeable in Home Assistant at any time) and Home Assistant restores it across restarts and
  updates. Only the one-time defaults automation changed, and it runs once, so an installation that has already been initialised
  keeps its value. 40 % is a starting value, not a limit, and no runtime decision hard-codes it. Declared as post-export entry
  `rsv1` (one line of the export-frozen core package) and pinned by `home-assistant/tests/test_ecco_reserve_default.py`.
  Nothing else changes: no firmware, Dump-to-Grid, Free Power, Intelligence or dashboard change.

The transaction, ownership, stop and restore model and the Modbus write surface are unchanged.

- `intelligence.replay.inputs_from_history` now builds its inputs through an `ecco_core` snapshot. The result is
  identical for every finite input, and byte-identical engine reports are tested. A reading that is not a finite number
  is now dropped at the snapshot boundary.

### Security

- **The Energy Actions card builds with esbuild 0.28.1** (was 0.21.5; advisory GHSA-67mh-4wv8-2f99, an esbuild development-server
  issue fixed in 0.25.0). The card's build never starts that server, so the advisory was not reachable; the upgrade is
  maintenance. The rebuilt bundle's executable code is byte-identical; only its trailing Lit licence block is regrouped, with the
  same notices. Declared as post-export entry `esb1`, which enrols the card's `package.json`, `package-lock.json` and bundle in
  the PEX frozen set (owner decision O3, amended); the historical card-folder and licence pins keep their values. Every tracked
  card now resolves esbuild 0.28.1. No firmware, Home Assistant, dashboard or Modbus change.

### Fixed
- **Intelligence SHADOW v0.1, data quality: the CT-reversal share counts only the hours in which import and export can be
  told apart** (`intelligence/quality.py`, `QUALITY_VERSION` `intel-quality-0.3.1-cfg`). Over the whole history and over the
  learning lookback, the share rule's numerator counted every hour that balances only with import and export swapped, also
  hours in which the two are within the balance tolerance of each other and so cannot be told apart, while its denominator
  counted only the hours in which they can (the recent window already counted only those). A long history with a few such
  borderline hours and few distinguishable ones (for example 13 against one) read as a share far above 100 %, raised the BLOCK
  `HISTORY_CT_REVERSED` on every history item and made `prepare_history` return no history: fail closed, but no learning at
  all. `quality.balance_counts` adds `distinguishable_only_swapped` (its other keys keep their meanings, and the residual rule
  still totals every hour with all six counters), `recent_balance_counts` returns its counts under the same names, and
  `ct_reversed` reads only those two. The evidence of `HISTORY_CT_REVERSED` states the two counts the rule read in each window
  (`history_*`, `lookback_*`, `recent_*`) next to `windows`, and the capture validator's `energy_balance` reports the new count
  (`intel-validate-capture-0.1.1`; the summary schema stays `ecco-intel-capture-summary/1`, as the change only adds a key).
  No threshold, window or PROPOSED value changes; a genuine reversal still blocks in every window, and both PROPOSED bounds
  stay inclusive. Like the share, the minimum hours now count only the told-apart hours that balance only swapped (over the
  whole history and the lookback they also counted the borderline hours).
  Tests: `test_intel_quality` [10b], `test_intel_capture_kit`.
- **Deployment rollback restores a fresh modification time**: `Invoke-EccoDeploymentRollback` restored the backup with `cp -p`, bringing back the file's old modification time, and Home Assistant keeps serving its cached YAML dashboard while the file is not newer than that cache. It now restores with a plain `cp` and `touch`, and a dashboard rollback ends with a reminder to read back `lovelace/config`. The rollback of a drift recovery adds `DRIFT RECOVERY ROLLED BACK`: its backup is the drifted file, without the policy's layer.
- **`tools/deploy-ha.ps1` prints the manual-resource reminder for every file it copies to `/config/www/ecco/`**, not only for
  `frontend/<card>/dist/<file>` sources.
  - Before: the documented content-addressed deploy (`dist/deploy/stage/<card>.<sha8>.js`) printed only
    `ECCO DEPLOYMENT PASSED`, with no sign that the dashboards still loaded the previous bundle.
  - Now: after a passed copy the script reads the persisted resource list once, read-only. It reports the card's resource as
    `NOT SWITCHED` (the copy is not live), `NOT REGISTERED`, `ALREADY POINTS AT THIS FILE` or `UNKNOWN`, and names
    `verify-resource` as the gate.
  - It still never edits `.storage`. The parsing and wording are pure functions in `tools/EccoDeploy.psm1`, tested in
    `tools/tests/Test-EccoDeploy.ps1` (run locally) and statically in `tools/tests/test_ecco_deploy_preflight.py`.
- **House load no longer reads 0 W while exporting** (post-export entry `hd1`;
  [docs/HOUSE_LOAD_HD1.md](docs/HOUSE_LOAD_HD1.md)). The inverter's native load (register 178) reads 0 W in some states,
  notably during export. `sensor.ecco_house_power` (same entity, unit and statistics) is now derived with the Energy Flow
  card's and the firmware's rule: the native load when credible, inverter AC output + grid CT when the native load is
  unavailable or falsely 0 W. It is unavailable, never 0 W, when the evidence is stale or cannot confirm a zero. A new
  diagnostic `sensor.ecco_house_power_model` holds the resolution.
  - The House Load Snapshot, the learning gate and 16 dashboard house-load reads now use it. The register table still
    shows register 178. Seven runtime blends use their average alone while it is unavailable, so they never show NaN.
  - The Battery Outlook learning excludes 0 W samples. No history is rewritten.
  - No firmware, inverter write or write-surface change. FE-1 and the Energy Flow card are unchanged.


- Advanced Configuration Stage 0 (`acs0`) no longer presses Apply into a routine Modbus poll (acs0r1; source only, NOT
  installed; [docs/dev/advanced-config/stage0-safety-case.md](docs/dev/advanced-config/stage0-safety-case.md) section 3b).
  - **What happened:** in the 2026-10-16 supervised live proof on the S3:
    - slot 1 100 -> 99 % was APPLIED AND VERIFIED;
    - both 99 -> 100 % restores were refused by the firmware's Apply gate (`Modbus bus busy`, nothing written: counter and
      later reads agree). The Apply pressed a fixed ~5.3 s after the configuration read, at the 10 s telemetry poll's last
      frame. The first edit succeeded only because its Load was delayed 7 s;
    - the owner restored 100 % through Manual Controls (verified, B10 MATCH).
  - **The fix** (Home Assistant package only):
    - before the fresh read, the Apply observes one inverter clock read (its phase) and two clean telemetry completions
      (their period);
    - after the staging it presses 1.5 s after an observed clean completion, only when that window holds no clock read and
      lies at most 25 s after the fresh read;
    - otherwise FAILED, nothing pressed. Neither observation is ever assumed.
  - **Unchanged:** still exactly one press; a refusal is still final; every gate, the fresh evidence, the staged == live
    proof and the independent later-read verdict.
  - **Tests:** the offline suite (162 checks) reproduces B2, a B1-type and an A-type refusal or success on the exact pre-fix
    package, and sweeps phases, scheduler jitter and changed poll timing.
- Scheduled Free Power now starts reliably and reports every failure (post-export entry `fps1`; incident record
  [docs/incidents/2026-10-11-scheduled-free-power-start.md](docs/incidents/2026-10-11-scheduled-free-power-start.md)). On
  11 Oct 2026 the 11:00 session never started. The firmware start gate correctly refused both presses because a routine telemetry
  read was on the Modbus bus, and the package's fixed timing (+2 s, one retry at +35 s) was locked to the 10 s poll. Nothing was
  written and nobody was told. Home Assistant scheduling layer only:
  - bounded, unevenly spaced retries of a transient start-gate refusal (no side effects), each answer proven to belong to its
    press, never a retry once a start transaction began or when the outcome is unconfirmed, success only on Free Power Active;
  - a cancel (or cancel and re-arm) stops the run before the next press; the limit is checked on every attempt; nothing is
    staged into another transaction;
  - each run retries for at most 10 min and never in the window's last 30 s; a late start is shortened to end with the window;
  - a readiness check 5 min before, a missed-trigger watchdog 3 min after, and a persistent notification for every failure or
    missed start;
  - schedule status STARTING / FAILED / COMPLETED in addition to ACTIVE / ARMED / IDLE.
  No firmware, dashboard or Modbus change.
- Scheduled Dump to Grid gets the same start reliability and failure reporting (post-export entry `dgs1`; review record
  [docs/incidents/2026-10-12-scheduled-dump-to-grid-start-review.md](docs/incidents/2026-10-12-scheduled-dump-to-grid-start-review.md)).
  No scheduled Dump to Grid start has failed so far, but its start gate has the same bus-busy refusal and the package used the same
  locked +2 s / +35 s timing (in the offline model it fails to start at about 9 % of poll phases). The old retry also pressed
  again after a start transaction had begun, could leave the write enable on when the firmware dropped a press, stopped for good
  if the dongle read offline at the start instant, and alerted nobody. The fix is in the Home Assistant scheduling layer only and
  mirrors `fps1`:
  - bounded, unevenly spaced retries of a transient start-gate refusal only, each answer proven to belong to its press;
  - never a retry once a start transaction began or when the outcome is unconfirmed;
  - all three staged values (export power, Stop SOC, duration) confirmed before every press; nothing staged into another
    transaction;
  - a start deadline and a duration clamp inside the authorised window;
  - a readiness check (including a battery already at the Stop SOC), a missed-trigger watchdog, restart recovery, persistent
    notifications, and STARTING / FAILED / COMPLETED status.
  No firmware, dashboard or Modbus change.
- **Power Flow Today chart: the shared tooltip stays inside the card and the viewport** (`home-assistant/dashboards/ecco_pro.yaml`,
  post-export entry `ptt1`; the dashboard stays at 7.23.0, staged, not live-proven). The chart's tooltip lists five readings (Solar,
  House, Battery, Grid, SOC). ApexCharts places it from the plot grid only and the card's own `overflow: hidden` clips it, so on the
  Overview chart (card height 7 rows) the last reading, SOC, was cut off, and more of it on a phone layout. Each of the three copies of
  the chart (Overview, Intelligence, System) gains one `apex_config.chart.events.mounted` EVAL string (the chart already uses EVAL for
  its TOU annotation): a MutationObserver sees ApexCharts move the tooltip and moves it the shortest way into the card and the
  viewport (all four edges, mouse and touch, window scroll and resize); only when that move would put it under the pointer is it put
  beside it instead. The geometry is one pure function; the code writes only the tooltip's `style.left` / `style.top`, never its
  content, class or styling, and cleans up when the chart is destroyed. No series, colour, value, axis, legend, annotation, grid,
  `card_mod` or third-party card change, no service call, no entity. New suite
  `home-assistant/tests/test_ecco_power_chart_tooltip.py` (an exhaustive grid for the pure function against an independent oracle, 19
  mutants of it, a DOM stand-in for the glue with 10 mutants, the structural proof that nothing else in the dashboard moved) and the
  exact reverter `registry/tests/_ptt1_scope.py`.
- **Power Flow Today chart: the tooltip lists all five readings (the Solar series fills an empty 5-minute bucket with its last value)**
  (`home-assistant/dashboards/ecco_pro.yaml`, post-export entry `ovw5`; the dashboard stays at 7.23.0, staged, not live-proven).
  apexcharts-card shows the shared tooltip with every series only while all series have the same time points. All series of the chart turned
  an empty 5-minute bucket into a null point (`fill: 'null'`) and the card drops a series' trailing buckets that hold no value, so whenever
  the PV reading did not change inside the newest bucket (evening, night) the Solar series ended one bucket before the others and the
  tooltip listed Solar alone. Each of the three copies of the chart (Overview, Intelligence, System) now gives the Solar series its own
  `group_by` (`func: avg`, `duration: 5min`, `fill: last`; four lines per chart, twelve in all), as the SOC series already has. The same edit
  was applied to the production Overview on 25 Nov 2026; this entry records it in the repository so that a whole-file dashboard deployment
  cannot undo it. Trade-off, recorded in `docs/dev/post-export-edit-layer.md`: `fill: last` has no age limit, so a held, stale PV value is
  drawn flat like a steady one, and an entity that goes `unavailable` still draws a gap; a freshness limit (a template sensor gated by the
  dongle's telemetry) is described there and not built. No other series, colour, value, axis, legend, annotation, grid or third-party card
  change, no service call, no entity. New suite `home-assistant/tests/test_ecco_power_flow_solar_fill.py` and the exact reverter
  `registry/tests/_ovw5_scope.py`.

### Fixed (documentation)

- `docs/dev/register-provenance.md` swapped the evidence status of two registry records.
- `docs/INVERTER_CAPABILITY_REGISTRY.md` had an out-of-date record count, a statement that no W3 record is writable
  (register 244's policy record is), and an incomplete list of writing scripts.
- Stale fallback status in `VERSION.yaml` (the 7.18.0 dashboard comment), `README.md`, `SUPPORTED_HARDWARE.md` and
  `ARCHITECTURE.md`: the FB-C3 shadow-check display was described as offline only. It is deployed on the reference
  installation and its everyday display path was checked live; its supervision-loss (Shadow Recovery) path is not yet
  live-proven, so `tested_in_home_assistant` stays `false` for dashboard 7.18.0. The RTC policy row now records the FB-D1
  deployment and that its 7-day continuous run is still pending.

## [0.9.0] - first public pre-release

Experimental. One reference installation; per-feature evidence levels are in [SUPPORTED_HARDWARE.md](SUPPORTED_HARDWARE.md).

### Included

- ESPHome firmware `stage3.4` for a classic ESP32 dongle and an ESP32-S3 (N16R8) hardware wrapper, with the guarded write
  transactions (RTC correction, manual six-slot TOU, Free Power, register 244 export mode, Dump-to-Grid), durable recovery
  records, the fallback profile (save / invalidate / compare) and the supervision heartbeat.
- Home Assistant packages, dashboard 7.18.0 and three custom cards; optional InfluxDB Battery Outlook.
- Intelligence V1: shadow-only advisory engine with a configurable battery reserve (default 40 %) and a site-specific
  technical minimum; synthetic examples only; no write path.
- Offline test suites, the proof chain, the declared public-export transition `pub0`, the declared licence-alignment
  transition `lic0`, the site renderer (`tools/ecco_site_render.py`), the public privacy scan and a simple validation
  workflow with every action pinned to a commit SHA.
- Licence: GPL-3.0-or-later for the whole project, including the three custom cards; Lit's BSD-3-Clause notices ship inside
  the two prebuilt card bundles. Contributions need a Developer Certificate of Origin sign-off; no CLA.

### Known limitations (not in 0.9.0)

- Dump-to-Grid does not use the configured battery reserve: its firmware enforces only its own stop-level bounds. Reserve
  enforcement for Dump-to-Grid is deferred until it can be hardware-proven.
- Fallback restore and automatic failback are not implemented.
- No automatic optimiser control exists; Intelligence is advisory and shadow-only.
- Exact inverter model and firmware strings of the reference installation are not published (not recorded in the evidence).

### Planned after 0.9.0

- Run the card tests (`npm test`, typecheck, build reproducibility) in CI; automated action-pin updates.
- A step-by-step installation guide and concise public specifications (Dump-to-Grid first).
- Moving the InfluxDB tasks' fixed timezone into the installation profile.

