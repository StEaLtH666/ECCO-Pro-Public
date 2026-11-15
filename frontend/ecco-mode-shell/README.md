# ECCO Mode Shell

A dependency-free, **read-only** Home Assistant Lovelace card that gives one view **two presentations of the same data**
behind one polished switch:

- **Production Mode**: calm and simple. The view's own cards, one plain-language sentence, the alert strip.
- **Geek Mode**: every available non-secret data point of the view (every sensor, attribute, diagnostic, timestamp, derived
  value, assumption, limit, code and provenance), grouped, collapsible, searchable, filterable and paged, with update ages,
  source ids, descriptions, units, a redacted raw attributes view and copy / export of non-secret diagnostics.

This is the **first offline proof**, built for the ECCO Intelligence SHADOW view (contract `ecco-intel-entities/1`). Status:
source only. Nothing here is installed, registered or connected to Home Assistant. Licence: GPL-3.0-or-later; no third-party
code.

## The mode is a presentation toggle, nothing more

- It is **not** ECCO's Manual / Assisted / Automatic authority. Switching it never starts or stops Intelligence, never enables
  ASSISTED or AUTONOMOUS, never alters Manual control authority, never writes a register or helper, never cancels an armed
  session and never calls a service. The shell reads `hass.states` (plus `hass.locale` and `hass.themes` for formatting) and
  nothing else of `hass`.
- It lives **only in the element instance**: Production on first render and on every reload; reset to Production when the element
  is connected, when it is disconnected, when the location moves away from the path it was entered on (`location-changed`), on
  `pagehide`, and when the element becomes hidden (its box goes 0 x 0). A switch in one view never changes another view. It is
  never stored: no `localStorage`, `sessionStorage`, IndexedDB, cookie, history or URL state.
- **Safety-critical alerts, recovery state and owner-action-needed status stay visible in both modes.** They come from the
  catalogue's `alerts` list through one function (`deriveAlerts`) and are drawn by one function (`renderAlertStrip`) into a strip
  that sits **outside** both switchable bodies. A condition that cannot be checked (entity unavailable, unknown, missing, or
  attribute absent) is shown as "Cannot check this right now", never as silence.
- Geek Mode adds **no** permission: it shows, it offers no control and no installer-only write, and it bypasses nothing. The only
  things it can do besides read are: dispatch the standard `hass-more-info` event (open an entity), write to the clipboard on a
  button press, and offer a Blob download on a button press.

## Same data, one adapter

`buildSnapshot(states, catalogue, nowMs)` is the single adapter. The alert strip, the Production summary, the Geek header counts,
the instrument tiles and every row read the **one snapshot** built from the one `hass` object; the child cards receive that very
same `hass` object. Per-state-object caching means a change to one entity recomputes one row and re-renders one row.

## Honest inventory

Every data point has exactly one status, said in **words and with an icon**, never colour alone (and with a distinct border
style):

| Status | Meaning |
|---|---|
| Live | a value is reporting and, if the source has a freshness limit, it is within it (sources without a limit say "age not monitored") |
| Stale | older than the catalogue's `stale_after_s`; shown for reference, never as current |
| Unavailable / Unknown | Home Assistant says so; **no value is shown** |
| Not measured | the catalogue lists it but Home Assistant has no such entity; **nothing is invented** |
| Simulated | the source marks it simulated (`simulated`, `is_simulated`, `synthetic`, or `provenance` / `data_source` of SIMULATED) |
| Unverified | the source says so (`verified: false`, `provenance_ok: false`, `provenance: UNVERIFIED`) or it has a freshness limit but no usable timestamp |

A declared attribute that is absent is listed as "Not present". Attributes the catalogue does not know about are listed too (the
card tolerates unknown extra keys), and the first nesting level of a dict attribute is listed as sub-rows (deeper levels are in the
raw view).

## Nothing secret is surfaced

Replaced by a **withheld marker** (an icon and the word) in rows, raw view, search index, copy and export: values under keys such
as token, password, secret, api key, authorization, bearer, credential, private key, webhook, cookie, session; latitude,
longitude, location, address, e-mail, serial, MPAN; JWT-like strings, long hex and base64 blobs, URLs with credentials or token
query parameters, connection strings, IP and MAC addresses, coordinate pairs, private host names; the catalogue's own
`redaction.extra_key_patterns`; nested dicts and lists; key **names** that look secret. The export is passed through the redactor a
second time. A public git revision is the one deliberate exception (a 40-hex git object name is shown only under a revision key).
The redaction is a heuristic safety net: it errs towards withholding (for example a four-part dotted number reads as an address),
and the catalogue's `exceptions` list is where a source is excluded on purpose.

## Use

```yaml
type: custom:ecco-mode-shell
view_id: intelligence
title: ECCO Intelligence
catalogue: !include ecco_intelligence.catalogue.json   # inline data; the card fetches nothing
page_size: 25                                          # optional, 5 to 100
always:                                                # shown in BOTH modes: must be read-only
  - type: custom:ecco-intelligence-card
production:                                            # shown only in Production Mode, passed through unchanged
  - type: tile
    entity: input_boolean.ecco_intel_paused
    tap_action: { action: toggle }
    icon_tap_action: { action: toggle }
```

`examples/intelligence-modes.yaml` is the full example: it wraps the **existing** ECCO Intelligence card, its watchdog / status
entities card and its pause tile **unchanged** (`test/test_example_dashboard.py` proves they are equal to the existing dashboard's).

**The `always` guard.** `validateChildCards` refuses, with a visible notice and a shell alert, any `always` card that carries an
action other than `none`, `more-info` or `navigate`, a service-call shaped key, a write-capable type (button, light, thermostat,
iframe ...), an entities row of a writable domain, or a tile on a writable domain without explicit safe actions. Cards in
`production` are **not** filtered: that is where controls live, and they keep exactly the permissions they have today (the shell
passes the very same configuration object). Consequence, flagged for the owner: **Geek Mode hides the pause tile** (it only
shows); a control stays one tap away in Production, and Geek Mode says so. Custom cards can only be checked by what their
configuration shows; the Intelligence card is pinned read-only by its own test suite.

## The catalogue (interface 1, schema `ecco-geek-catalogue/1`)

Produced by the Python side, consumed as data: `groups`, `sources` (stable ledger `id`, `entity_id`, group, title, description,
priority headline / normal / obscure, unit, `expected_update_s`, `stale_after_s`, origin, attributes with dotted paths into the
first nesting level of a dict attribute), `discover` (entity prefixes, group, exclusions), `alerts`, `exceptions` (secret, privacy,
unsupported_source, not_exposed_in_states) and `redaction`. `validateCatalogue` fails **closed**: an unknown schema or a malformed
source switches the Geek inventory off with a visible error listing each problem, while every individually valid alert still
drives the strip. `catalogueItemIds` returns every source id and `source#attribute` path the card can show, for the ledger
cross-check. New safe entities with a discover prefix (for example `ecco_intel_`) appear in the **Discovered** group with no new
hand-designed card.

## Element contract (data attributes the tests rely on)

`[data-ecco-mode-switch]` (radio group) with `[data-mode-option="production|geek"]`; `[data-ecco-alert-strip]`;
`[data-ecco-body="production|geek"]`; `[data-ecco-inspector]`, `[data-inspector-search]`,
`[data-inspector-filter="status|group|priority|problems"]`, `[data-inspector-row]` (`data-entity-id`, `data-status`),
`[data-inspector-raw]`, `[data-inspector-copy]`, `[data-inspector-export="json|csv"]`, `[data-inspector-page-next|prev]`,
`[data-withheld]`. The element exposes a read-only `mode` getter (assigning it throws).

## Tests

```
cls
cd frontend\ecco-mode-shell
node --test test/*.test.mjs                                  # everything, including the mutation proof
python -I -B -X utf8 test\test_example_dashboard.py          # the example wraps the existing cards unchanged
```

| File | What it proves |
|---|---|
| `test/core.test.mjs` | controller, catalogue validation, classification, redaction (hostile secrets assembled in code), snapshot, alerts, search, windowing, export, the child guard, performance |
| `test/element.test.mjs` | AC1-AC14 and AC16 on the element against `test/minidom.mjs` (a node DOM that records every tag, attribute name and style property and **throws on innerHTML**) |
| `test/coverage.test.mjs` | the card-side coverage check, generic: set `ECCO_GEEK_CATALOGUE` and `ECCO_GEEK_STATES` to run it on the real catalogue and fixtures |
| `test/static.test.mjs` | forbidden APIs absent, `hass` reads pinned, names never computed from data, one adapter / one strip renderer, ASCII-only source |
| `test/mutations.test.mjs` | 78 deliberate breaks on scratch copies of the card; every one must be killed (at least 6 each for AC5, AC6, AC10, AC13) |

Fixtures are synthetic: `test/fixtures/mini.catalogue.json`, `mini.states.json`, `hostile.states.json`. No house image, layout,
site entity id, location or real measured value appears in any file. The hostile **secret** values are assembled from fragments in
`test/secrets.mjs` so that no committed file holds a token shape.

## Preview

`preview/index.html` runs the real card against a mock `hass` with scenarios (normal, stale, down, alert, large = 5000 entities,
hostile text, invalid and missing catalogue), light and dark, and a width control. Serve the repository root on loopback:

```
cls
python -m http.server 8765 --bind 127.0.0.1
# http://127.0.0.1:8765/frontend/ecco-mode-shell/preview/?s=normal&theme=dark&mode=geek
```

## Design notes

- Mobile first: the layout answers to the card's own width (container queries), tables become stacked rows, 44 px targets,
  visible focus rings, `prefers-reduced-motion` stops every animation and transition, light and dark follow `hass.themes`, text
  and status colours are checked against WCAG AA by the tests. Verified in headless Chrome at 375 px: no horizontal overflow.
- Performance: the DOM never holds more than one page of rows (default 25, at most 100); unchanged rows keep their node; strings,
  lists, dicts and attribute counts are capped with a visible marker.
- Source is ASCII only; every non-ASCII character is a `\u` escape.

## Recommendation: one reusable switch and adapter, not two dashboards

Roll this out to the other tabs as **this one element plus one catalogue per view**, never as a Production dashboard and a
separate Geek dashboard: the shell, the adapter, the redactor, the alert derivation and the inspector are view-independent; a view
contributes only its catalogue (data) and its child cards. Roll out in this order after the real Intelligence catalogue passes the
ledger check: Overview, Controls, Advanced.

## Integration TODO (owner steps; none done here)

1. Merge the catalogue workstream (`dev/mode-shell-catalogue`); run `coverage.test.mjs` with `ECCO_GEEK_CATALOGUE` and
   `ECCO_GEEK_STATES`, and reconcile `catalogueItemIds` with the generated ledger's id format.
2. Add the card resource to `deployment/ha-manifest.yaml` and the Lovelace resources; add a CHANGELOG line and the scope-chain
   entries the release process requires (pinned files: not edited here).
3. Add a Python pin suite under `tools/tests` mirroring `tools/tests/test_intelligence_card.py` (CI runs no Node).
4. Decide whether a reviewed control may ever sit in a Geek-visible region (today: no).
5. Live check in a real Home Assistant: `location-changed` and the kept-alive behaviour were tested here with stand-ins and in
   headless Chrome only.
