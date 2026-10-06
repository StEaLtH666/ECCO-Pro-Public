# ECCO Dashboards

ECCO Lovelace/dashboard YAML lives here.

Primary design goal: make Live Energy Flow the focal point of the Overview page, with supporting battery, tariff, forecast, weather, TOU and outage information around it.

`ecco_pro.yaml` is the current dashboard. It expects the custom cards listed in [THIRD_PARTY_NOTICES.md](../../THIRD_PARTY_NOTICES.md)
(installed separately) and the ECCO cards under `frontend/`. Its entity ids use the default device slug `ecco_clock_dongle`; render a
site copy with `tools/ecco_site_render.py` if yours differs.
