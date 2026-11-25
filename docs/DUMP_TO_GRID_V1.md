# Dump-to-Grid V1: design record

The full Dump-to-Grid V1 design record (with its dated live-proof notes) belongs to the project's private development archive
and is not published; see [project-history/README.md](project-history/README.md). This path is kept because a pinned card
README links to it.

A concise public specification of Dump-to-Grid is planned after 0.9.0 (see the CHANGELOG). Until then:

What applies today:

- What Dump-to-Grid writes (registers 244 and 250-261), its durable snapshot and verified restore, and its stop-level bounds:
  [SAFETY.md](../SAFETY.md), sections 1, 8 and 9.
- Evidence level (two hardware-tested scenarios; every other path offline only): [SUPPORTED_HARDWARE.md](../SUPPORTED_HARDWARE.md).
- The dashboard card that drives it: [frontend/ecco-energy-actions-card/README.md](../frontend/ecco-energy-actions-card/README.md).
- The command ceiling: 3000 W by default, configurable at build time up to 8000 W, with its proof levels (only 3000 W is
  hardware tested) and the runaway backstop: [dev/dump-to-grid-ceiling.md](dev/dump-to-grid-ceiling.md).

## R9: missed scheduled runs after a Home Assistant restart (deploy note)

The scheduled Export to Grid and Charge Battery packages never start a missed run after a Home Assistant restart: a start time earlier
than (or in the same second as) the captured Home Assistant start is recorded as `MISSED`, notified and disarmed. The capture is written by
an automation on the `homeassistant` start event, and only once the dongle's NTP is synced and Home Assistant's clock agrees with the
dongle's NTP time (within 120 s; it waits up to 10 minutes). If it is never trustworthy the capture stays unknown and every guard fails
closed. **Install this change with a FULL Home Assistant restart, not a package reload:** after a reload the capture stays unknown, so the
watchdog will not rescue a lost on-time start until the next full restart. Residual risk: the dongle's `NTP Time` text is in the dongle's
own timezone; if that differs from Home Assistant's, the capture never becomes trustworthy (fail closed, schedules still start on time).

## Clock changes: scheduled Export to Grid and Charge Battery (offline; not installed)

On the nights the UK clocks change, the local hour 01:00 to 01:59 does not exist (clocks go forward) or happens twice (clocks go back). Both
schedule packages now refuse, when the schedule is armed, a start time that is such a skipped or repeated local time, or one that cannot be read,
with `REJECTED - the start time is a skipped, repeated or unreadable local time (clock change); pick another time`. The check comes before
`must be in the future`, so arming in the second 01:xx hour for a 01:xx start no longer reports a misleading `must be in the future`. Pick a start
outside that hour. Every deadline in the packages (the window end, the retry deadline, the run length) was already epoch arithmetic and is exact
across a clock change; nothing else about a scheduled start changes.

The Export to Grid package's early check that the run does not overlap a TOU slot with a charge source set now walks the run on the real instants
(each minute of the run is converted to its local time of day), so a window that crosses a clock change checks the slots it really covers. Before,
on the day the clocks go forward it missed a charge slot that begins after the skipped hour, and on the day they go back it refused a window that was
clear. The firmware's own START gate is not changed (a firmware change is a separate flash) and, read from its text, walks the window the old way:
on the day the clocks go forward the arm check is the only one that sees such a slot. An unreadable slot table still defers to the firmware.

What is not verified: how Home Assistant's template functions read a naive local time (the first occurrence of a repeated time, the offset before
the change for a skipped one) and which zone they use are recalled, not checked against a real Home Assistant; the offline suite models both ways of
reading a repeated time. A supervised read-only template check on the real Home Assistant is still open. The check runs when the schedule is armed
(the card locks the start while it is armed).

## Charge Battery: result integrity (offline; not installed)

The scheduled Charge Battery (Free Power) package no longer turns a result into a success that nobody verified. `STARTED OK` is written only by this
run's own verified start. While Free Power is found active after a refused, failed, blocked or cancelled run (it was started some other way, for
example from the dongle's own Start button), the result stays as written, a run that was still starting reads `FAILED TO START ... this run did not
confirm that it started it` (or `CANCELLED` if the owner cancelled it), and the end-of-run alert says Free Power is active now. After a Home
Assistant restart during a session the recovery writes `STARTED OK - running` only over a result that already started with `STARTED`; a `FAILED`,
`BLOCKED` or `CANCELLED` result stays, and any other result becomes an `UNCONFIRMED` text. A `FAILED` text can be a false negative (the dongle started
late after a start transaction that began); the alert flags it. The scheduled Export to Grid package is not changed by this item.
