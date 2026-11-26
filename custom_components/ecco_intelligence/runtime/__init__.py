"""The Home-Assistant-free half of the ECCO Intelligence SHADOW integration.

Nothing in this package imports homeassistant (the runtime boundary suite checks it), so every module here imports and runs
in a plain interpreter and is tested there:

    sources.py         HA state views (plain dicts) -> an ecco_core Snapshot plus SiteReadings, from the site file's entity map
    history_source.py  recorder statistics rows (read by the caller in the executor) -> intelligence.history.History
    engine_link.py     the one call into the vendored engine: bridge.advisory_live_inputs, then shadow_cycle.run_cycle
    gates.py           the start-up gates (mode, time zone and clock changes, site file, vendor manifest, versions)
    selftest.py        the self-test record (PASS / WARN / FAIL per check)
    store.py           the ONLY module that touches the file system: reads the site file and the kit manifest, and writes only
                       under <config>/ecco/intelligence/state/
"""
