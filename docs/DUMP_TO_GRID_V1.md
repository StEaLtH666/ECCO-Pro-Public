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
