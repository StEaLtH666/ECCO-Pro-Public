# Rendering the deployable files for your site

The repository is generic. Every Home Assistant entity id of the ECCO dongle uses the default device slug `ecco_clock_dongle`
(what a fresh Home Assistant install generates for the firmware's `name: ecco-clock-dongle`), and the Octopus Energy tariff
entities use the placeholders `your_meter_serial`, `your_import_mpan` and `your_export_mpan`.

If your installation uses the defaults and no Octopus tariff entities, deploy the files as they are. Otherwise render a local
copy with your values and deploy that copy. Your values never go into tracked files.

## 1. Create your site file

```
cp ecco_site.example.yaml ecco_site.local.yaml
```

`ecco_site.local.yaml` is git-ignored. Edit it:

| Key | Meaning |
|---|---|
| `device_slug` | The slug between `<domain>.` and `_<entity>` in your dongle's entity ids, e.g. `sensor.my_dongle_ecco_battery_soc` gives `my_dongle`. Lower-case letters, digits and single underscores |
| `keep_default_slug_entities` | Dongle entity ids that kept the default slug on your installation even though the device was renamed (rare) |
| `octopus` | Optional: `meter_serial`, `import_mpan`, `export_mpan` exactly as they appear (lower-case) in your Octopus Energy entity ids |
| `entity_map` | Optional: exact entity id renames for other site-specific entities the packages reference (whole ids only) |

## 2. Preview, then render

```
python tools/ecco_site_render.py --site ecco_site.local.yaml --dry-run
python tools/ecco_site_render.py --site ecco_site.local.yaml --diff
python tools/ecco_site_render.py --site ecco_site.local.yaml
```

The last command writes `dist/site/` (git-ignored): the Home Assistant packages and dashboard, the InfluxDB files, the card
assets and examples, and the local snapshot / flight-recorder tools, all with your values. `--diff` masks tariff values.

## How the renderer decides (exact rules, fail closed)

- `<domain>.ecco_clock_dongle_<object>` entity ids (sensor, binary_sensor, number, switch, button, select, ...) are rendered to
  your slug. A quoted mention of the bare slug (documentation) is rendered too.
- ESPHome action service names (`esphome.ecco_clock_dongle_<action>`) and firmware file names are **kept**: they come from the
  firmware's node name, not from Home Assistant's device slug.
- Tariff placeholders are replaced only inside whole Octopus Energy entity ids.
- Anything else that spells the default slug, a tariff placeholder outside an entity id, an `entity_map` id that occurs
  nowhere, or a site value that matches nothing stops the render with an error and writes nothing. A tree that was already
  rendered is refused as input.

The renderer is covered by `tools/tests/test_ecco_site_render.py`.

## Deploying

Deploy from `dist/site/`, not from the repository files. If you use the SSH deployment helpers, point them at the rendered
copy. Keep `dist/site/` and `ecco_site.local.yaml` out of version control and out of issue reports: they contain your
identifiers.

### Card bundles: the resource read-back gate

`tools/ecco_deploy_preflight.py plan` renders and stages each card as `dist/deploy/stage/<card>.<sha8>.js` and writes
`dist/deploy/plan.json`, without contacting Home Assistant. A card bundle then goes live in separate steps, and only the last one
proves it:

1. **Copy.** `tools/deploy-ha.ps1` copies the staged file to `/config/www/ecco/`, then `verify-served` checks the bytes Home
   Assistant serves. **Nothing a dashboard loads has changed yet.** After the copy, `deploy-ha.ps1` reads the persisted resource
   list once (read-only) and prints `RESOURCE NOT SWITCHED <card>: the dashboards still load <old URL>`, or `NOT REGISTERED`,
   `ALREADY POINTS AT THIS FILE` or `UNKNOWN`.
2. **Switch the resource by hand.** In Settings -> Dashboards -> Resources, edit the card's existing entry to
   `/local/ecco/<card>.<sha8>.js` (JavaScript module). No ECCO tool edits resources, and a resource is shared by every dashboard.
3. **Read back and verify.** Read the persisted list again now, and compare it with the plan and with a copy saved before step 2:

```powershell
cls
ssh <ha-host> "cat /config/.storage/lovelace_resources" | Out-File -Encoding utf8 resources-now.json
python tools\ecco_deploy_preflight.py verify-resource --plan dist\deploy\plan.json --resources resources-now.json --before resources-before.json --base-url <HA URL>
```

`--resources` and `--before` take the raw `lovelace_resources` storage file or the websocket `lovelace/resources` result. Both
carry the resource ids the checks need. Capture both lists the same way, because any difference in an entry counts as a change.
For each planned card, `verify-resource` checks that:

- exactly one resource loads the card, and its URL and type are the plan's;
- with `--before`, the card's entry kept its id and type, and no other resource was added, removed or changed;
- with `--base-url`, the bytes served at that exact URL hash to the plan's sha256;
- the read-back is at most `--max-age-minutes` (default 30) old.

The tool is read-only: it writes nothing, and its only network use is the optional GET. It prints one line per card:

| Line | Meaning |
|---|---|
| `RESOURCE VERIFIED <card> -> <url> (id <8>, persisted, read back at <UTC>)` | Printed only when every check of the run passed (exit 0). |
| `RESOURCE NOT SWITCHED <card>: still <url>` | The dashboards still load another bundle. |
| `RESOURCE NOT VERIFIED <card> -> <url>: <reasons>` | The URL was switched, but another check failed. |

Report a card install as done only after `verify-resource` exits 0, and quote its `RESOURCE VERIFIED` line. Until then, report
the copy as staged and not live, naming the resource the dashboards still load. Checking the card in a browser is a separate,
later step.
