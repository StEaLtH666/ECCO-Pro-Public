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
