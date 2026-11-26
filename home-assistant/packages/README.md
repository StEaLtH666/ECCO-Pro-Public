# Home Assistant packages

ECCO's Home Assistant packages: helpers, template sensors, scripts, schedules, System Health, the supervision heartbeat and the
fallback status / operator wrappers. They are plain YAML that you deploy yourself (see `deployment/ha-manifest.yaml` for the
deployable set).

Entity ids use the default device slug `ecco_clock_dongle` and the tariff entities use `your_*` placeholders. If your
installation differs, render a site copy with `tools/ecco_site_render.py` (see `ecco_site.example.yaml`) and deploy that copy.

## Time trust

`ecco_time_trust.yaml` (read only; offline, NOTHING INSTALLED) turns what the dongle already publishes into one explicit timing-safety input. ECCO acts on time on three clocks: Home Assistant
starts schedules on its clock, the dongle ends every lease and checks every start against its NTP time, and the inverter switches its TOU slots on its own clock, which the dongle corrects
against NTP about twice an hour and which stalls for 60 s about 85 times a day. If trustworthy time cannot be established, anything that depends on it must fail safely. This package
builds the input only: nothing reads it yet (wiring it into the start gates is a separate step with its own approval), and it writes nothing.

| Entity | Values | Meaning |
|---|---|---|
| `sensor.ecco_time_trust_ha_clock` | TRUSTED, DEGRADED, UNTRUSTED, UNKNOWN | Home Assistant's clock against the dongle's NTP time text |
| `sensor.ecco_time_trust_dongle_ntp` | TRUSTED, UNTRUSTED, UNKNOWN | the dongle's NTP time: synced, and the text still advancing |
| `sensor.ecco_time_trust_inverter_clock` | TRUSTED, DEGRADED, UNTRUSTED, UNKNOWN | the inverter's clock against NTP, with the RTC correction health |
| `sensor.ecco_time_trust` | the same four | the worst of the three (ranked TRUSTED < DEGRADED < UNKNOWN < UNTRUSTED, so UNKNOWN never reads better than DEGRADED); attributes: the three states, `ha_clock_skew_s`, `inverter_difference_s`, `reasons` |
| `binary_sensor.ecco_time_trusted_for_leases` | on / off | lease ends and schedule starts: the dongle NTP is TRUSTED and the HA clock is TRUSTED or DEGRADED |
| `binary_sensor.ecco_time_trusted_for_ha_schedules` | on / off | Home Assistant's own schedules: the HA clock is TRUSTED or DEGRADED and the dongle NTP is TRUSTED |
| `binary_sensor.ecco_time_trusted_for_slot_edits` | on / off | the slot-time edit gate: the inverter clock is TRUSTED |
| `binary_sensor.ecco_time_trust_rtc_stall_sustained`, `..._rtc_correction_stuck` | on / off | the two debounced flags the inverter rule uses (internal) |
| `binary_sensor.ecco_time_trust_ntp_text_readable`, `..._inverter_text_readable` | on / off | on while the text is readable; their `last_changed` is the moment the text last became readable, which the LIVE condition measures against (internal) |

Eleven template entities in all, and nothing else (no automation, helper, script, trigger, action or service call). Every per-clock sensor has a `reasons` attribute, a list whose entries each start with the verdict they support. A clock is the worst of its rules.

**Freshness is judged by the values.** Home Assistant resets a state's `last_changed` on a restart and on every reconnect of the dongle's API (ESPHome re-sends its cached states on subscribe, so a copy of any age arrives
"now"), so a text that merely arrived recently proves nothing. Each dongle text therefore has to pass three conditions, and only the first is the proof; the other two can only withdraw trust:

| Condition | Rule | Verdict when it fails |
|---|---|---|
| VALUE (the proof) | the time the text carries lies within 600 s of Home Assistant's clock: 300 s of freshness (five missed publications or reads) plus the 300 s by which Home Assistant's own clock may be off before it reads UNTRUSTED. For the NTP text that is \|now() - text\| <= 600 s; for the inverter it is the age of the read, \|now() - (inverter text - difference)\| <= 600 s (the inverter text minus the clock difference is the NTP time at which the read was made, on the right date) | UNKNOWN (a stale copy and a Home Assistant clock that is far off cannot be told apart; in the second case the HA clock reads UNTRUSTED and every consumer is off) |
| LIVE (an extra) | the text changed more than 10 s after its helper (`..._ntp_text_readable`, `..._inverter_text_readable`) last changed, that is after the text last became readable: the first value after a restart, a reconnect or a dongle boot is the copy that was re-sent, not a publication | UNKNOWN until the next publication (about a minute when the dongle is alive, never when its read path is dead) |
| ARRIVAL (an extra, the earlier rule) | the text changed within the last 300 s (`last_changed`): it notices a frozen text after 5 to 6 minutes, sooner than the value bound can | UNKNOWN for the HA clock and the inverter, UNTRUSTED for the dongle NTP (a frozen text) |

A text is a time only in the exact form the firmware writes it, `YYYY-MM-DD HH:MM:SS` (`strptime` with that format): Home Assistant's own date parser also reads a date alone, no seconds, a `T`, fractions and an offset, and none of those is a time here.

| Clock | Rule (constant, and why) | Verdict |
|---|---|---|
| HA clock | skew = Home Assistant's clock when the dongle's NTP text arrived (its `last_changed`) minus the text, whole seconds. Not `now()` minus the text: that carries the text's age (up to about 60 s, more when a publication is late). The VALUE rule does not apply to this sensor (the value of the text is the skew); LIVE and ARRIVAL do | \|skew\| <= 120 s TRUSTED (the bound R9's capture accepts; about the 2 minutes of clock error that requirement REQ-D1 of the draft dynamic energy control requirements allows any use of time of day), <= 300 s DEGRADED (the firmware's `kLargeErrorS`), more UNTRUSTED, however large |
| HA clock | the text unreadable, not a time, not changed for more than 300 s, or not live | UNKNOWN (it cannot be compared; not an accusation of Home Assistant) |
| Dongle NTP | the dongle's NTP Synced flag, the text a time (not "Waiting for NTP" or "NTP time invalid"), and the text passing ARRIVAL (published every 60 s: five missed publications; the proxy for the sync age the dongle does not publish), VALUE and LIVE | all TRUSTED; any off, not a time or frozen UNTRUSTED; any unreadable, or failing VALUE or LIVE, UNKNOWN |
| Inverter clock | \|difference\| (inverter minus NTP): 60 s is the RTC monitor's trip level, 120 s the tolerance REQ-D1 gives any use of time of day | <= 60 s TRUSTED, <= 120 s DEGRADED, more UNTRUSTED (a whole hour, 3600 s, or half a day, 43200 s, included) |
| Inverter clock | failed corrections since boot > 0, or maximum clock error since boot > 120 s (the monitor's trip conditions; both latch until the dongle reboots, however large the counter) | DEGRADED |
| Inverter clock | the stall flag on for 3 minutes 30 seconds of continuous ON (a `delay_on` of 00:03:30: the flag is evaluated once per 60 s read, so four consecutive reads of it ON, an episode of 240 s, trip it and three, 180 s, do not; 210 s lies between them so the timing of the reads cannot decide, and it is 1.75 times the longest episode in the saved data: the flag is on for 60 s, a few 120 s, about 85 times a day) | DEGRADED |
| Inverter clock | a correction in progress for 5 minutes of continuous ON (the firmware releases the lock at 90 s and Home Assistant alerts at 180 s; it skips the regular clock read while a correction runs) | UNTRUSTED |
| Inverter clock | the dongle's NTP not synced (the difference is measured against it), or the inverter time text not a time, not changed for more than 300 s (the clock is no longer being read, and the last difference stays in place), or failing VALUE or LIVE | UNKNOWN |

**Fail safe.** Any input that is missing, unavailable, unknown, not a number (or not finite) can never produce TRUSTED: the clock reads UNKNOWN (or worse), the overall state is at best UNKNOWN and the three
consumers read off. The consumers are allow-lists; a consumer must test `is_state('binary_sensor.ecco_time_trusted_for_leases', 'on')` and never "not off" or "not unavailable". A restart, a template reload, a reconnect or a
dongle outage creates no trust: it makes inputs unreadable (UNKNOWN), and every value that comes back, a cached copy included, has to pass VALUE and LIVE again before a clock can read TRUSTED. The one thing it can do is restart the two debounce
counts, which delays a trip by at most its delay.

**The time-zone assumption** (the one R9 already makes). The dongle's NTP text is its local time and carries no offset; `as_timestamp()` reads such a time as local time in Home Assistant's own zone, so the two
zones must be the same. If they differ the skew reads as whole hours and is UNTRUSTED, never TRUSTED, and the dongle NTP and the inverter clock read UNKNOWN (their texts are an hour from Home Assistant's clock: the VALUE rule), so
slot edits are off too. The repeated hour of the autumn clock change reads one hour wrong (the repeated local time is read as its first occurrence): the HA clock is UNTRUSTED for that hour and the other two UNKNOWN, which fails safe.

**Replay of the saved 10 days** (15 to 25 Nov 2026; the real package run through the offline model against a saved history export, format `ecco-ha-history/1`, kept outside the repository; counts only). The
history records a state change of the clock difference, not every read: 10,140 recorded reads. **Four inputs of this replay are inferred, not recorded.** Three counters have no recorded row before 22 Nov (failed corrections, maximum clock error,
NTP synced) and are held at the values the unbroken counters imply (no dongle reboot in the window: 0 failed, at most 77 s, synced). The export has no row of the inverter time text either, so the replay feeds a SYNTHESIZED one, a fresh text
every 60 s and none during the 4 outages: a fourth inferred input. The 300 s arrival rule, the VALUE rule (the synthesized text is consistent with the recorded difference by construction) and the LIVE condition of the inverter time text are therefore not exercised by real data, only by that
synthetic feed, and the inverter-clock counts below rest on it. The NTP time text is not in the export and is left out, so the HA clock and the dongle NTP clock are not replayed (their rules are proven against a model in the suite).
Result: **10,112 reads TRUSTED, 16 DEGRADED, 12 UNKNOWN, 0 UNTRUSTED**; 14,800 of the 14,820 minutes TRUSTED. The 16 DEGRADED reads are exactly the reads above 60 s (largest 71 s), each a single read lasting at most 73 s: the longest DEGRADED run is 1 read.
The 12 UNKNOWN reads are the first read of the file and the read 49 s later (no text has changed yet since it became readable) and, at each of the 4 recorded outages of the dongle, the read at the outage, the first read after the return (within a few seconds, inputs still arriving) and, for
two of the outages, one more read within a minute (the first text after a return is the copy that was re-sent, so the clock waits for the next one: the LIVE condition, here an effect of how the synthetic text restarts); UNKNOWN lasted 64 s at most and 5 minutes in all. With the three counters left missing
(strict) the first 7 days read UNKNOWN by design: 3,188 TRUSTED, 5 DEGRADED, 6,947 UNKNOWN. The stall flag was on in 852 episodes, the longest 120 s and none over 120 s: **no stall episode ever came near the 210 s that trips the sustained-stall helper, so it never turned on**; a correction was in progress in 485 episodes,
the longest 24 s, so the stuck-correction helper never turned on either.

**NOT ESTABLISHED, and limits.** It checks that two clocks agree, not that either is true: a dongle whose NTP server stopped answering keeps counting on its own oscillator, its text keeps advancing and its
"synced" flag never clears after the first sync (pinned against the firmware in the suite); the freshness proxy detects a dead or frozen text, not that. A real sync age is one firmware field (a flash, approved
separately). Whether the inverter clock really stalls or the 60 s read cadence produces the stall flag (a firmware question) is not decided here: the package only classifies how long the flag stays on. The rules run when an input changes and at the start of every minute, so a frozen text is noticed 5 to 6 minutes after its last change.
The VALUE bound is a bound on Home Assistant's clock too: one that is more than about 9 to 10 minutes off (UNTRUSTED long before) makes the dongle NTP and the inverter clock UNKNOWN, and one near that edge can make them flap with the publication phase. The LIVE condition costs up to about a minute after every restart, reconnect, dongle boot or template reload (a stalled inverter clock or a skipped read can make it two).
The debounce counts: an unreadable flag does not restart a count in progress (the availability template of a binary template sensor is a super template: the count runs through the gap, so a 60 s episode followed by an outage of 3.5 minutes or more that returns ON trips the helper, which fails safe);
a restart or a template reload creates the helpers again and each takes back the state it had (on or off), so a helper that was on stays on, a count in progress restarts (a stall that began earlier is noticed up to 3.5 minutes late, a stuck correction up to 5 minutes late, and the stale inverter text and LIVE keep the inverter clock UNKNOWN meanwhile) and a helper with nothing to take back (a first installation) reads unknown, which is UNKNOWN for the inverter clock, until its delay ends.
Recalled from Home Assistant core, NOT verified on a real Home Assistant (the model of them is in the suite): that `states['<entity id>']` and its `last_changed` behave as modelled (new on a restart and on a reconnect), that a template using `now()` is re-rendered at the start of each minute, that `delay_on` restarts its count only when a changed result is delivered,
that an availability template is a super template (while it is false the state template is not rendered and an unchanged result is not delivered again when it turns true), that a binary template sensor with a delay restores its last on or off state when it is created (on a reload as on a restart), that a list attribute arrives as a list, that `strptime(text, format, default)` is Python's, and how `as_timestamp()` reads a naive datetime (as local time in Home Assistant's own zone); recalled from ESPHome in the same way: that the dongle's API sends every entity's cached state when a connection begins, the premise of the LIVE condition. Nothing is installed and no live read was made.

**Install.** One file copy to `/config/packages/ecco_time_trust.yaml`, a configuration check, then reload the template entities (Developer tools, YAML, Template entities, or the `template.reload` service): no
restart, no other package, no helper to create. The deployment manifest lists it (`restart_required: false`) and the pin chain carries it as the append-only post-export entry `ttr1`. The suite is
`home-assistant/tests/test_ecco_time_trust.py` (the real package against a model of Home Assistant's template entities, `home-assistant/tests/_time_trust_sim.py`, with independent models and mutants).

## Start gate and lease guards

`ecco_start_gate.yaml` and `ecco_lease_guards.yaml` (offline, NOTHING INSTALLED, nothing live-proven) are item N2 of the architecture reconciliation: ONE start gate for both functions, a guarded Free Power start bound to it, and guards that end a lease whose plan, time or supply no
longer allows it. They add no engine and no write path of their own: every start still goes through the dongle's own start button and its firmware gate, and every end through the existing END button.

**The gate is SOFT.** Home Assistant gates bind only what goes through them. The dongle's own Start button (`button.ecco_clock_dongle_start_free_power_charge_now`, `button.ecco_clock_dongle_start_dump_to_grid_now`) can still be pressed from Home Assistant or by an assistant, past every check here, until a
firmware gate binds it (a flash, approved separately; architecture item N6). The Energy Actions card is NOT changed in this step: its Free Power Start still presses the dongle's start button directly (its Dump Start is guarded only where `dump_to_grid.guarded_start` is set), and pointing it at
`script.ecco_free_power_start_guarded` is a separate card change. Nothing else reads the gate yet.

| Entity | Package | Meaning |
|---|---|---|
| `binary_sensor.ecco_charge_start_allowed` | start gate | on only when a Charge Battery (Free Power) start passes every check below; attributes `reasons` and `blocked_by` |
| `binary_sensor.ecco_export_start_allowed` | start gate | the same for Export to Grid (Dump to Grid) |
| `input_number.ecco_grid_import_ceiling_w` | start gate | the owner's grid-import SAFETY ceiling in watts; no initial value; 0, unknown or unavailable means NO CEILING CONFIGURED |
| `script.ecco_free_power_start_guarded` | start gate | the guarded Free Power start (below), a new start path bound to the gate |
| `ecco_lease_guard_dump_end`, `ecco_lease_guard_free_power_time`, `ecco_lease_guard_free_power_import` | lease guards | three automations, each only ever pressing an existing END button (below) |

**What the gate checks** (each reads only a fact ECCO already has; the order is the order of `blocked_by`). `reasons` lists every blocking cause as `<CODE>: <text>` naming the entity and what it reads, then any `NOTE <CODE>: <text>` that does not block, with `ALLOWED: every check passed`
first when nothing blocks; `blocked_by` lists the codes only. Any missing, unavailable, unknown or non-numeric input closes the gate and is named; a consumer tests `is_state('binary_sensor.ecco_charge_start_allowed', 'on')` and never "not off".

| Code | Gate | Closes it when |
|---|---|---|
| `TIME_LEASES`, `TIME_SCHEDULES` | both | `binary_sensor.ecco_time_trusted_for_leases` or `..._for_ha_schedules` (the time trust package) does not read on |
| `TELEMETRY_OFFLINE`, `CONFIGURATION_OFFLINE` | both | `binary_sensor.ecco_clock_dongle_telemetry_online` or `..._configuration_online` does not read on |
| `TELEMETRY_STALE` | both | `sensor.ecco_clock_dongle_last_telemetry_update` (published only after a complete poll) is not a time in the firmware's form `YYYY-MM-DD HH:MM:SS` within 300 s of Home Assistant's clock; judged by the VALUE, never by its arrival (a reconnect re-sends a cached text as if it were new) |
| `FREE_POWER_ACTIVE`, `FREE_POWER_OPERATION`, `FREE_POWER_SNAPSHOT` | both | the Free Power lease, its start-or-restore transaction or its saved snapshot (the open recovery obligation) does not read off |
| `DUMP_ACTIVE`, `DUMP_OPERATION`, `DUMP_SNAPSHOT` | both | the same three for Dump to Grid: "already running or owed" for its own function, "the other function" for the other |
| `MANUAL_WRITE` | both | a manual inverter write is in progress |
| `OVERRIDE_ACTIVE`, `OVERRIDE_UNREADABLE` | Export | `sensor.ecco_plan_export_hold` reads held (a Hold battery, Skip tonight or Prepare for power cut), or anything but clear |
| `RESERVE_UNKNOWN`, `RESERVE_INVALID` | Export | `sensor.ecco_plan_effective_reserve` cannot be read, or is not a finite number from 0 to 100 |
| `STOP_SOC_UNREADABLE`, `STOP_SOC_BELOW_RESERVE` | Export | the staged Stop SOC (`number.ecco_clock_dongle_dump_to_grid_stop_soc`) is not a number from 0 to 100, or is below the effective reserve (refused, never changed) |
| `REVISION_UNREADABLE` | Export | `input_number.ecco_plan_revision` is not a whole number from 0 up |
| `IMPORT_HEADROOM`, `IMPORT_UNREADABLE`, `REQUEST_UNREADABLE`, `IMPORT_CEILING_INVALID` | Charge | only with a ceiling configured: the staged request plus the measured grid import (never below 0) exceeds the ceiling, the import or the request cannot be read, or the ceiling is not a number from 1 to 100000 |

**The import ceiling.** `input_number.ecco_grid_import_ceiling_w` has no initial value, so a fresh helper reads 0: the check reports `NOT_CONFIGURED` (a note in `reasons`: `NOTE IMPORT_NOT_CONFIGURED: ...`), does not block and says so. The ceiling is a safety ceiling, never a target: the most the grid may supply at the moment (the main fuse or
the supply agreement). Configured, the gate refuses `request + max(import, 0) > ceiling`, with the import read from `sensor.ecco_clock_dongle_ecco_grid_power_ct_clamp` (the dongle's CT reading, positive = importing). No charger-loss factor and no margin is applied (none is established: control-authority rung R5 measures them),
so a request that just fits can still breach by the charger's losses; the in-lease import guard ends a lease on a measured breach. A value that cannot be a ceiling (text, negative, nan, infinite, above 100000, below 1) closes the gate rather than switching the check off.

**The guarded Free Power start** (`script.ecco_free_power_start_guarded`) is the analogue of the guarded Dump start, which presses the start button only after its checks. It tries once (a manual start has no retry loop) and its order is: validate the request; read the gate (a closed gate refuses before anything is staged; a gate closed only by `IMPORT_HEADROOM` or `REQUEST_UNREADABLE`
is judged again after an explicit request is staged); stage the power and then the duration with `number.set_value`, only a value that differs from what is staged; arm the write enable and wait up to 5 s for the dongle to confirm the arm and both values; read the gate again; press the start button once; wait for the dongle's answer; end with the write enable off.
Optional fields `power_w` and `duration_minutes` stage a request the way the scheduled start does; with neither it starts the request already staged on the dongle, as the card does. The result text is `input_text.ecco_plan_last_result`, the one the guarded Dump start writes: `REFUSED <CODE> - <text>` for a refusal,
`FAILED <CODE> - <text>` after a press that did not start Free Power, `STARTED free_power at <P> W for <D> min (guarded start).` on success, with one persistent notification (`ecco_free_power_start_blocked`). It does not use the Free Power schedule's result text: that text belongs to the schedule's state machine (its status sensor, retry loop,
R9 recovery and alert read its prefixes) and the start bypass detector reads `STARTED OK - <n>W for <m> min` in it as the proof of a SCHEDULED run, which a manual start must not forge or overwrite.

| Code | Meaning |
|---|---|
| `GATE_UNREADABLE`, `GATE_BLOCKED` | the gate cannot be read, or is closed (the blocking codes are named); nothing staged, armed or pressed |
| `SCHEDULED_START_RUNNING` | a scheduled Free Power start is running or cannot be read (before the stage), or began meanwhile (at the press-time check) |
| `LIMIT_UNREADABLE`, `POWER_INVALID`, `DURATION_INVALID` | the effective grid charge limit cannot be read; the power is not a multiple of 100 W from 500 W to the limit; the duration is not a whole number of minutes from 1 to 240 |
| `GATE_CLOSED`, `NOT_CONFIRMED`, `LIMIT_LOWERED` | the press-time check: the gate closed while the request was staged, the dongle did not confirm the arm and the values within 5 s, or the limit fell below the request; nothing is pressed |
| `FIRMWARE_REFUSED`, `START_FAILED`, `NO_ANSWER` | after the press: the dongle's own gate refused it (nothing written), a start transaction began but Free Power did not become active (the firmware restores its saved snapshot itself), or the dongle did not answer (unconfirmed, never retried) |

Two things it does not do. The start bypass detector (bpd1, pinned) knows only the scheduled run's `STARTED OK` and the guarded Dump start as ECCO's own records, so a start made by this script is recorded by the detector as a start with no ECCO record (the incident record and counter are written; a popup only when an override is active or a plan reading
is unreadable); teaching the detector about it is an edit of a pinned package and is not made here. And smr1 puts the owner's request numbers back only after a SCHEDULED start: a start with explicit values replaces the owner's staged request and nothing restores it (a start with none changes nothing).

**The lease guards** each need the owner's separate install authorisation, read nothing from one another and stand alone. Each only ever presses an existing END button (the same press the card's End & Restore Now makes: the dongle restores the exact values it saved before the lease; END is always allowed), then raises one persistent notification that says what was ended and why, and pauses for a minute
(one violation, one press). They start, arm and write nothing. The Free Power side is two automations, not one, because each counts its own delay and a run that is counting drops every trigger that arrives meanwhile (mode single).

| Guard | Ends | When | Constant and why |
|---|---|---|---|
| `ecco_lease_guard_dump_end` | Dump to Grid, `END DUMP TO GRID - RESTORE NOW` | `sensor.ecco_plan_export_hold` turns to held (a Hold battery, Skip tonight or Prepare for power cut), or the effective reserve changes, or the lease turns active, and the reserve is above the Stop SOC the lease latched (`sensor.ecco_clock_dongle_dump_to_grid_active_stop_soc`) | the latched sensor updates every 5 s, so a lease that has only just turned active is waited for up to 15 s; the dongle enforces only the latched Stop SOC, so nothing else ends a lease when the reserve rises |
| `ecco_lease_guard_free_power_time` | Free Power, `END FREE POWER - RESTORE NOW` | `binary_sensor.ecco_time_trusted_for_leases` changes from on to off while a lease is active, or a lease turns active while it reads off (an unavailable, unknown or missing sensor is not a reading), and it has not read on for 5 minutes | the lease ends on the dongle's own NTP time; 5 minutes is more than the LIVE condition costs after a reconnect (about a minute, two at worst) and more than the 3 minutes 30 seconds stall debounce, so a reconnect or restart alone never ends a lease |
| `ecco_lease_guard_free_power_import` | Free Power, `END FREE POWER - RESTORE NOW` | a ceiling is configured and the measured grid import stays above it for 30 seconds while a lease is active | three 10 s polls: a short confirmation, not an average; with no ceiling the guard is inert |

A guard acts only on a positive reading: a hold that reads held, a reserve and a latched Stop SOC that are both numbers, a time-trust sensor that was on and now reads off (or reads off when a lease starts), an import that is a number above a configured ceiling. A restart, a template reload, a reconnect and a boot never end a lease by themselves: every trigger must be a change from a reading (not from unavailable, unknown or nothing), nothing runs at the Home Assistant start, and a count in progress dies with
a restart. A violation that already stands when Home Assistant starts is not acted on until the next change; a measured import breach that persists after the entities return is still ended after its 30 seconds (it is a fact about the supply, not about the restart). The guards are SOFT: Home Assistant down, a dead dongle or a press the dongle does not act on ends nothing, and they do not retry.
There is no target-reached guard for Charge Battery in this step.

**Install.** `ecco_start_gate.yaml`: copy the file to `/config/packages/`, check the configuration, then reload the template entities, the input_number helpers and the scripts (Developer tools, YAML), one at a time, never "reload all"; no restart. It needs `ecco_time_trust.yaml`, `ecco_plan_helpers.yaml` and the two schedule packages (without them the gate reads off and the script refuses).
`ecco_lease_guards.yaml`: copy, check the configuration, reload the automations; no restart; it needs the plan sensors, the time trust sensors and, for the import guard, the ceiling helper; without a source a guard stays inert. Delete the file and reload the same domains to remove either.

**NOT ESTABLISHED.** Nothing here has run on a real Home Assistant, dongle or inverter. Recalled from Home Assistant core and not verified (the model of them is in the suite): that a state trigger carries `trigger.from_state` (none for an entity that did not exist), that `to: ~` fires on a change of the state and never on an attribute alone, that a template trigger fires on false to true and is not armed while already true, that `wait_template`
with `continue_on_timeout` continues at once when its template is already true, that `mode: single` with `max_exceeded: silent` drops a trigger while a run is busy, that a list rendered by an attribute template arrives as a list, and that a script field that was not given reads as undefined. The gate is soft; the import check judges one instant and applies no loss factor; the 8000 W setpoint question and the charge actuator are untouched.
The offline suite is `home-assistant/tests/test_ecco_start_gate.py` (the real files against `home-assistant/tests/_start_gate_sim.py`, on the repository's FPS1 interpreter, the template model of the time trust suite and the Free Power model of the schedule suites, with an independent model of the gate and mutants).
