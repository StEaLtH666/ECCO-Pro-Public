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
