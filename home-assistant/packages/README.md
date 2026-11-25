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

Every per-clock sensor has a `reasons` attribute, a list whose entries each start with the verdict they support. A clock is the worst of its rules.

| Clock | Rule (constant, and why) | Verdict |
|---|---|---|
| HA clock | skew = Home Assistant's clock when the dongle's NTP text arrived (its `last_changed`) minus the text, whole seconds. Not `now()` minus the text: that carries the text's age (up to about 60 s, more when a publication is late) | \|skew\| <= 120 s TRUSTED (the bound R9's capture accepts; about the 2 minutes of clock error that requirement REQ-D1 of the draft dynamic energy control requirements allows any use of time of day), <= 300 s DEGRADED (the firmware's `kLargeErrorS`), more UNTRUSTED |
| HA clock | the text unreadable, not a time, or not changed for more than 300 s | UNKNOWN (it cannot be compared; not an accusation of Home Assistant) |
| Dongle NTP | the dongle's NTP Synced flag, the text a time (not "Waiting for NTP" or "NTP time invalid"), and the text changed within the last 300 s (published every 60 s: five missed publications; the proxy for the sync age the dongle does not publish) | all three TRUSTED; any off, not a time or frozen UNTRUSTED; any unreadable UNKNOWN |
| Inverter clock | \|difference\| (inverter minus NTP): 60 s is the RTC monitor's trip level, 120 s the tolerance REQ-D1 gives any use of time of day | <= 60 s TRUSTED, <= 120 s DEGRADED, more UNTRUSTED |
| Inverter clock | failed corrections since boot > 0, or maximum clock error since boot > 120 s (the monitor's trip conditions; both latch until the dongle reboots) | DEGRADED |
| Inverter clock | the stall flag on for 10 minutes of continuous ON (a 10 minute `delay_on`: the flag is on for 60 s, a few 120 s, about 85 times a day and never longer in the saved data) | DEGRADED |
| Inverter clock | a correction in progress for 5 minutes of continuous ON (the firmware releases the lock at 90 s and Home Assistant alerts at 180 s) | UNTRUSTED |
| Inverter clock | the dongle's NTP not synced (the difference is measured against it), or the inverter time text unchanged for more than 300 s (the clock is no longer being read, and the last difference stays in place) | UNKNOWN |

**Fail safe.** Any input that is missing, unavailable, unknown, not a number (or not finite) can never produce TRUSTED: the clock reads UNKNOWN (or worse), the overall state is at best UNKNOWN and the three
consumers read off. The consumers are allow-lists; a consumer must test `is_state('binary_sensor.ecco_time_trusted_for_leases', 'on')` and never "not off" or "not unavailable".

**The time-zone assumption** (the one R9 already makes). The dongle's NTP text is its local time and carries no offset; `as_timestamp()` reads such a text as local time in Home Assistant's own zone, so the two
zones must be the same. If they differ the skew reads as whole hours and is UNTRUSTED, never TRUSTED. The repeated hour of the autumn clock change reads one hour wrong (the repeated local time is read as
its first occurrence): the HA clock is UNTRUSTED for that hour, which fails safe.

**Replay of the saved 10 days** (15 to 25 Nov 2026; the real package run through the offline model against a saved history export, format `ecco-ha-history/1`, kept outside the repository; counts only). The
history records a state change of the clock difference, not every read: 10,140 recorded reads. With the three counters that have no recorded row before 22 Nov (failed corrections, maximum clock error,
NTP synced) held at the values the unbroken counters imply (no dongle reboot in the window: 0 failed, at most 77 s, synced): **10,115 reads TRUSTED, 16 DEGRADED, 9 UNKNOWN, 0 UNTRUSTED**; 14,805 of the
14,820 minutes TRUSTED. The 16 DEGRADED reads are exactly the reads above 60 s (largest 71 s), each a single read lasting at most 73 s: the longest DEGRADED run is 1 read. The 9 UNKNOWN reads are the
4 recorded outages of the dongle and the first read after each return (within a few seconds, inputs still arriving), plus the first read of the file (the correction flag's first row, with the same timestamp, comes after it); UNKNOWN lasted 4 s at most. With those three inputs left missing
(strict) the first 7 days read UNKNOWN by design: 3,190 TRUSTED, 5 DEGRADED, 6,945 UNKNOWN. The stall flag was on in 852 episodes, the longest 120 s: **no stall episode ever lasted 10 minutes (or
5 minutes), so the sustained-stall helper never turned on**; a correction was in progress in 485 episodes, the longest 24 s, so the stuck-correction helper never turned on either. The NTP text is not in the
export, so the HA clock and the dongle NTP clock are not replayed (their rules are proven against a model in the suite).

**NOT ESTABLISHED, and limits.** It checks that two clocks agree, not that either is true: a dongle whose NTP server stopped answering keeps counting on its own oscillator, its text keeps advancing and its
"synced" flag never clears after the first sync (pinned against the firmware in the suite); the freshness proxy detects a dead or frozen text, not that. A real sync age is one firmware field (a flash, approved
separately). Whether the inverter clock really stalls or the 60 s read cadence produces the stall flag (a firmware question) is not decided here: the package only classifies how long the flag stays on. The rules run when an input changes and at the start of every minute, so a frozen text is noticed 5 to 6 minutes after its last change. The two debounce timers count from when Home Assistant first sees
the flag on: a restart or a template reload restarts the count, so a stall that began earlier is noticed up to 10 minutes late (the model pins both outcomes). Recalled, NOT verified on a real Home Assistant (the model
of them is in the suite): that `states['<entity id>']` and its `last_changed` behave as modelled, that a template using `now()` is re-rendered at the start of each minute, how `delay_on` and `availability` behave
across a change of the template result, that a list attribute arrives as a list, and how `as_timestamp()` reads a text with no offset. Nothing is installed and no live read was made.

**Install.** One file copy to `/config/packages/ecco_time_trust.yaml`, a configuration check, then reload the template entities (Developer tools, YAML, Template entities, or the `template.reload` service): no
restart, no other package, no helper to create. The deployment manifest lists it (`restart_required: false`) and the pin chain carries it as the append-only post-export entry `ttr1`. The suite is
`home-assistant/tests/test_ecco_time_trust.py` (the real package against a model of Home Assistant's template entities, `home-assistant/tests/_time_trust_sim.py`, with independent models and mutants).
