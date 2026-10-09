# ECCO Advanced / Experimental Configuration Card

A **read-only** Home Assistant Lovelace card that lists every inverter setting in ECCO's capability registry. It is
searchable and filterable. Each setting shows its live value from the ECCO controller's Home Assistant entities, its
register, its raw and decoded value, its status, the evidence behind that status, a danger class and the reason it is
not writable here. A dedicated panel covers **Global Power / Export Limit (register 245)**.

**Status.** The card is section 13 of the dashboard's Inverter / Advanced view (dashboard 7.19.0, post-export entry
`acfg1`), staged and not yet exercised in Home Assistant. Global Power writing is **not implemented**: the future write
controls are shown as a disabled design preview.

## The read-only guarantee

This card cannot change anything: not Home Assistant, not the ECCO controller, not the inverter. It is read-only by
construction:

- **It only reads states.** The `hass` setter keeps `hass.states` and nothing else. The Home Assistant object itself is
  never stored, so none of its service, websocket or API methods can be reached.
- **No calls, network, storage or timers.** The card makes no service call, no websocket message and no network
  request. It writes no browser storage, dispatches no events and starts no timers. The only module is the card
  itself; it has no runtime dependencies.
- **Only four local actions.** The card handles exactly these, and each changes only what the card shows:
  - search typing
  - filter chips
  - "clear search and filters"
  - expanding a row

  Any other action value is ignored.
- **Global Power controls are inert.** Unlock, Staged value and Apply are rendered `disabled` with no action
  attribute, so no handler can reach them.

The tests prove this three ways (see [Development](#development)):

1. A recording DOM shim drives every rendered control against a Home Assistant object that records every property read
   and every call. Only `states` is read, and nothing is called.
2. A static scan of the source and the built bundle.
3. A Python suite that runs in CI.

ECCO's firmware is the sole Modbus master. Any future write feature belongs in the firmware's guarded transactions, not
in this card.

## What the card shows

### Catalogue

There are 165 registry records in nine sections:

| Section | Contents |
|---|---|
| Battery and Charging | battery state, charge curve, protection thresholds and grid / generator charging |
| Grid and Export | grid measurements, the export policy, solar export and grid peak shaving |
| Inverter Power | inverter output, house load, the energy pattern and the Global Power / Export Limit setting |
| Time of Use | the six time-of-use slots and the master time-of-use switch |
| Generator / AUX / Smart Load | generator charging and run times, the AUX port function and smart-load thresholds |
| Solar / PV | PV string voltages, currents and power, and PV energy |
| Protection and Safety | grid protection thresholds, fault and warning words and transformer temperatures |
| Communications and Diagnostics | inverter state, clock, basic settings and ECCO's own diagnostic counters |
| Experimental / Undocumented | records whose register or meaning is not established (never controls) |

Each row shows the name, current value, register, status, evidence code, danger class and freshness. Expanding a row
shows:

- the current value
- register, raw value and decoded value
- status, and why the setting is not writable here
- evidence (registry proof status, write policy, current access)
- danger class
- available options (decoded enumerations and documented bounds, each labelled with its source)
- explanation, and interactions with other settings
- the source entity and the firmware decode it comes from
- provenance (the registry record and the firmware and Home Assistant evidence it cites)

**Search** matches name, description, explanation, section and entity. A number such as `245`, `r245` or `reg245`
matches that register exactly. Every word typed must match.

**Filters** select by status, evidence and category. Filters combine with AND.

### Status

A status can only be made *more* restrictive by the presentation overlay, never less.

| Status | Meaning |
|---|---|
| Proven (elsewhere in ECCO) | A hardware-tested write path exists in ECCO's own guarded controls. This page cannot write it. |
| Experimental | A firmware write path exists but is not hardware-proven. This page cannot write it. |
| Read only | ECCO has no write path. Shown for inspection only. |
| Locked | Safety-critical (for example the grid protection thresholds, battery chemistry and voltages). Permanently read-only on this installation. |
| Unsupported | The register or meaning is not established. Never a control. |

### Evidence

Evidence codes are taken from the registry's `live_proof_status`:

| Code | Meaning |
|---|---|
| M3 | write-proven on hardware |
| M2 | read-proven on hardware |
| M1 | documented, not live-proven |
| M0 | inferred from the repository |
| MX | unknown |

### Danger

| Class | Meaning |
|---|---|
| D0 | telemetry |
| D1 | cost / tariff |
| D2 | availability |
| D3 | regulatory |
| D4 | equipment / safety |

### Values and freshness

- **Unknown values are never shown as zero.** A missing entity reads "Entity not found in Home Assistant". An
  `unavailable` or `unknown` state reads "Unavailable" or "Unknown". A record no ECCO entity carries reads "Not exposed
  by an ECCO entity". A malformed state reads "Unexpected value".
- **A value is only called live when its own entity reported recently.** The maximum age depends on the poll block:
  - telemetry: 120 s
  - configuration: 300 s
  - inverter clock: 300 s
- **"Current (poll online)"** means the entity has not reported recently, but the controller's poll for that block
  (`telemetry_online` / `configuration_online`) is on and fresh.
- **Other labels:**
  - "Stale": the value is too old.
  - "Freshness not verified": there is no valid timestamp, or the timestamp is in the future.
  - "No live value": the entity has no value.
- **Raw words:**
  - When the firmware publishes the raw word, it is shown as *reported*.
  - When a value is an exact inverse of a plain firmware scaling, the raw word is shown as *derived*.
  - Otherwise no raw word is shown.

### Global Power / Export Limit (register 245)

The owner confirmed on 2026-10-08 that the inverter setting labelled "Export Limit" (register 245) is the setting
referred to as Global Power.

The panel shows:

- current value, raw value and unit (W)
- read freshness
- the source entity (`sensor.<device slug>_ecco_export_limit`)
- the mapping evidence
- the read-only status
- the limitations

The panel also enforces these rules:

- **No assumed hardware maximum.** The inverter's actual maximum for this setting has not been verified, so the panel
  shows **"Hardware maximum not verified"**. It never assumes a value. ECCO's firmware time-of-use power ceiling is a
  site setting, not this setting's hardware maximum.
- **Separate regulatory allowance.** The export allowance in the connection agreement is a separate, regulatory limit.
  It is not recorded, and it is never inferred from what the inverter can do.
- **Disabled design preview.** The future controls are shown, all disabled:
  - Unlock
  - Staged value
  - Permitted technical range
  - Apply
  - Verification status
  - Previous value
  - History

**Why Global Power is read-only:**

- ECCO's firmware has no write path for register 245. The pinned write surface excludes it, and
  `registry/tests/test_write_surface_invariants.py` forbids one.
- Writing it is not proven on the ESP32-S3 controller.
- The hardware maximum is not verified.
- The regulatory allowance is not recorded.

## Configuration

```yaml
type: custom:ecco-advanced-config-card
title: Advanced / Experimental Configuration   # optional
entity_prefix: "ecco_clock_dongle"            # optional: your ECCO device slug
max_age_telemetry_s: 120                       # optional, 5-86400
max_age_configuration_s: 300                   # optional, 5-86400
max_age_rtc_s: 300                             # optional, 5-86400
```

Unknown options are refused, so there is no hidden switch.

Entity ids are built at run time as `<domain>.<entity_prefix>_<object id>`. The catalogue therefore carries no device
slug. `tools/ecco_site_render.py` renders the quoted slug in `examples/advanced-config-example.yaml` for your site.

## On the ECCO dashboard

The post-export entry `acfg1` (`registry/tests/_acfg1_scope.py`) puts the card on the dashboard:

- **Dashboard.** Section 13 of the Inverter / Advanced view holds the card alone, with
  `entity_prefix: "ecco_clock_dongle"` quoted so `tools/ecco_site_render.py` renders it for your site. This is dashboard
  7.19.0, staged.
- **Manifest.** `deployment/ha-manifest.yaml` lists the bundle as a `frontend_assets` stanza: copy it to
  `/config/www/ecco/ecco-advanced-config-card.js` and register the Lovelace resource `/local/ecco/ecco-advanced-config-card.js`
  (JavaScript module) by hand, as for the other ECCO cards.

Section [9] of `tools/tests/test_advanced_config_catalogue.py` pins exactly this: one use of the card, one manifest stanza and the
entry that declares them.

## Development

```bash
npm ci --offline          # or: npm ci
npm test                  # Node test suites (node:test, mocked Home Assistant state)
npm run typecheck         # tsc --noEmit
npm run build             # dist/ecco-advanced-config-card.js (deterministic: same sources -> same bytes)
```

The tests run TypeScript directly through Node's type stripping, so they need a Node release where it is on by default
(validated with Node 24). The build tools are pinned exactly in `package.json` and `package-lock.json`.

The catalogue (`src/catalogue.generated.ts`) is generated, never edited by hand:

```bash
python tools/build_advanced_config_catalogue.py           # regenerate
python tools/build_advanced_config_catalogue.py --check   # exit 1 if the committed module is stale
python tools/build_advanced_config_catalogue.py --report  # entity-link report
python tools/tests/test_advanced_config_catalogue.py      # the generator's suite (runs in CI)
```

### Generator inputs

The generator reads three inputs and writes none of them:

- `registry/inverter_capabilities.yaml`, the capability registry;
- `registry/advanced_config_overlay.yaml`, a presentation overlay of sections, danger classes, lock reasons,
  explanations and the Global Power panel text;
- the firmware's main YAML, for entity names and the steady-poll decode.

### Generator rules

The generator fails closed on malformed input. It refuses:

- an overlay that would promote a status;
- an entity link that contradicts the firmware decode;
- a hardware maximum without recorded evidence.

### Keeping the bundle current

After any change to the registry, the overlay or the firmware's entities or poll decode:

1. Regenerate the catalogue.
2. Run `npm run build`.
3. Commit both outputs.

The CI suite and `npm test` flag a stale module or bundle.

### Files

| Path | Purpose |
|---|---|
| `src/ecco-advanced-config-card.ts` | the custom element (events, rendering, the read-only `hass` setter) |
| `src/model.ts` | pure logic: configuration, values, freshness, raw words, search, filters, the Global Power view |
| `src/render.ts` | HTML rendering (every dynamic value escaped) |
| `src/styles.ts` | mobile-first styles (one column, 44 px touch targets, wider layout from 700 px) |
| `src/types.ts` | types of the catalogue and view models |
| `src/catalogue.generated.ts` | the generated catalogue |
| `test/` | Node suites: model, rendering, the element through a DOM shim, catalogue integrity, static no-write scan, build reproducibility |
| `dist/ecco-advanced-config-card.js` | the built bundle |

## License

GPL-3.0-or-later, the licence of the ECCO-Pro project (see the repository's `LICENSE` file). The card has no runtime
dependencies, so the built bundle contains only this project's own code.
