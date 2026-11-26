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
