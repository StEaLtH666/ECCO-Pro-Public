# ECCO Intelligence (SHADOW) Home Assistant integration: source only

**Source only; install only from the built kit.** This directory is the reviewed source of the SHADOW integration. It is
not installable as it stands: it has no `_vendor/` engine copy and no `VENDOR_MANIFEST.json`, so its start-up self-test
fails closed. A kit is built offline with

```
python tools/build_ha_integration.py --out <absolute directory outside the repository> [--git-sha <commit>]
```

and installed only through the runbook (`docs/intelligence/INTELLIGENCE_SHADOW_INSTALL_RUNBOOK.md`), whose steps stay
**NOT AVAILABLE** until the deploy route (PR-5: `tools/deploy-ha-kit.ps1` for the kit, `tools/place-ha-site-file.ps1` for
the site file) has merged and the owner has given the separate go for the install (DP-4). Status: install kit staged,
PENDING DP-4. Nothing here is installed or deployed.

- SHADOW only: `sensor` and `binary_sensor` entities, no services, `requirements: []`; it reads states and recorder
  statistics and applies nothing. Its only subscriptions are the one-minute tick, one state listener on the site file's
  telemetry poll text (the poll-phase-aligned refresh) and at most one pending one-shot timer; while a cycle is in flight
  neither timer exists (the quiet cycle).
- Design, the refresh cadence, contract mapping, the site-file format, the Home Assistant APIs it relies on, risks and open
  questions: `docs/intelligence/INTELLIGENCE_HA_RUNTIME.md`. Check a site file offline with
  `python tools/ecco_intel_drill.py site-check --site <site.local.json>` (no ids printed).
- Tests: `python tools/run_offline_tests.py --root custom_components/ecco_intelligence/tests` (standard library only; a
  hand-written fake of the allowed Home Assistant modules, no `homeassistant` package).
