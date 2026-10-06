# Home Assistant packages

ECCO's Home Assistant packages: helpers, template sensors, scripts, schedules, System Health, the supervision heartbeat and the
fallback status / operator wrappers. They are plain YAML that you deploy yourself (see `deployment/ha-manifest.yaml` for the
deployable set).

Entity ids use the default device slug `ecco_clock_dongle` and the tariff entities use `your_*` placeholders. If your
installation differs, render a site copy with `tools/ecco_site_render.py` (see `ecco_site.example.yaml`) and deploy that copy.
